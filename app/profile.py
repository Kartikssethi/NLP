"""Describe an uploaded table (the "data health card") and draw how a set of
tables relate. Everything here is plain SQL/string work — no model involved,
so it is instant and can't hallucinate a column."""
from app.db import _quote, get_connection, get_relationships


def profile_table(table: str) -> dict:
    """Rows, per-column empties/distinct counts, and duplicate rows."""
    conn = get_connection()
    try:
        cols = conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
        names = [c["name"] for c in cols]
        parts = ["COUNT(*)"]
        for n in names:
            parts += [f"COUNT({_quote(n)})", f"COUNT(DISTINCT {_quote(n)})"]
        row = conn.execute(f"SELECT {', '.join(parts)} FROM {_quote(table)}").fetchone()
        total = row[0]

        columns = []
        for i, c in enumerate(cols):
            filled, distinct = row[1 + 2 * i], row[2 + 2 * i]
            columns.append({"name": c["name"], "type": c["type"], "empty": total - filled, "distinct": distinct})

        # Rows beyond the first of each identical group. GROUP BY treats NULLs
        # as equal, which is what "duplicate row" should mean here.
        group = ", ".join(_quote(n) for n in names)
        dupes = conn.execute(
            f"SELECT COALESCE(SUM(c - 1), 0) FROM (SELECT COUNT(*) AS c FROM {_quote(table)} "
            f"GROUP BY {group} HAVING COUNT(*) > 1)"
        ).fetchone()[0]

        return {
            "table": table,
            "row_count": total,
            "columns": columns,
            "empty_cells": sum(c["empty"] for c in columns),
            "duplicate_rows": dupes,
        }
    finally:
        conn.close()


def build_er_diagram(tables: list[str]) -> str:
    """A Mermaid erDiagram of the tables and the links detected between them."""
    relationships = get_relationships(tables)
    fk_cols = {(r["from_table"], r["from_col"]) for r in relationships if r["kind"] == "fk"}

    conn = get_connection()
    try:
        lines = ["erDiagram"]
        for t in tables:
            lines.append(f"    {t} {{")
            for c in conn.execute(f"PRAGMA table_info({_quote(t)})").fetchall():
                tag = " PK" if c["name"] == "id" else (" FK" if (t, c["name"]) in fk_cols else "")
                lines.append(f"        {c['type'] or 'TEXT'} {c['name']}{tag}")
            lines.append("    }")
    finally:
        conn.close()

    for r in relationships:
        if r["kind"] == "fk":
            lines.append(f'    {r["from_table"]} }}o--|| {r["to_table"]} : "{r["from_col"]}"')
        elif r["kind"] == "shared":
            first, *rest = r["tables"]
            for other in rest:
                lines.append(f'    {first} }}o--o{{ {other} : "{r["column"]}"')
        else:
            a, b = r["tables"]
            lines.append(f'    {a} ||--|| {b} : "same columns"')
    return "\n".join(lines)
