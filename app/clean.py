"""Cleaning an uploaded dataset by plain-language command.

"remove duplicate rows", "fill empty price with the average", "remove rows
where city is missing", "rename column cust to customer", "drop column notes".

These are matched with rules rather than sent to the model: they change data,
so they must do exactly what was said, show what will be affected first, and
never touch the built-in `sales` table. They return a `CleanPlan`; the caller
shows the preview, asks for confirmation, then runs `plan.sql`.
"""
import re
import statistics
from dataclasses import dataclass

from app.db import SALES_TABLE, _quote, _sanitize_identifier, get_connection

_NULLISH = r"(?:empty|missing|blank|null|nan|n/a)"


class CleanError(ValueError):
    """The command was understood but can't be run (unknown column, ...)."""


@dataclass
class CleanPlan:
    table: str
    sql: str = ""
    preview_sql: str | None = None   # rows that would be changed, for the preview
    count: int | None = None         # how many rows that is (None for a schema change)
    ask: str = ""                    # confirmation question; may contain {n}
    done: str = ""                   # result message; may contain {n}
    nothing: str = ""                # set instead of the above when there is nothing to do


def _norm(name: str) -> str:
    return re.sub(r"[\s_]+", " ", name.strip().lower())


def _columns(table: str) -> list[dict]:
    conn = get_connection()
    try:
        return [dict(c) for c in conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()]
    finally:
        conn.close()


def _scalar(sql: str):
    conn = get_connection()
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


def _literal(value) -> str:
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def _find_column(text: str, cols: list[dict]) -> str | None:
    """The longest column whose name appears as whole words in `text`
    ("unit price" matches unit_price)."""
    t = f" {_norm(text)} "
    hits = [c["name"] for c in cols if f" {_norm(c['name'])} " in t]
    return max(hits, key=len) if hits else None


def _match_column(phrase: str, cols: list[dict]) -> str:
    want = _norm(phrase.strip(" '\"`"))
    for c in cols:
        if _norm(c["name"]) == want:
            return c["name"]
    raise CleanError(f"There's no column called '{phrase.strip()}'. Columns: {', '.join(c['name'] for c in cols)}.")


def _resolve_table(text: str, tables: list[str]) -> str | None:
    candidates = [t for t in tables if t != SALES_TABLE]
    if not candidates:
        return None  # the built-in sales table is never edited
    if len(candidates) == 1:
        return candidates[0]
    t = f" {_norm(text)} "
    named = [c for c in candidates if f" {_norm(c)} " in t]
    if len(named) == 1:
        return named[0]
    raise CleanError(
        "Which dataset? Select just one, or name it — e.g. 'remove duplicate rows from "
        f"{candidates[0]}'. Selected: {', '.join(candidates)}."
    )


def _dedupe(table: str, cols: list[dict]) -> CleanPlan:
    group = ", ".join(_quote(c["name"]) for c in cols)
    q = _quote(table)
    keep = f"SELECT MIN(rowid) FROM {q} GROUP BY {group}"
    n = _scalar(f"SELECT COUNT(*) FROM {q} WHERE rowid NOT IN ({keep})")
    if n == 0:
        return CleanPlan(table, nothing=f"No duplicate rows found in {table}.")
    return CleanPlan(
        table,
        sql=f"DELETE FROM {q} WHERE rowid NOT IN ({keep})",
        preview_sql=f"SELECT * FROM {q} WHERE rowid NOT IN ({keep}) LIMIT 200",
        count=n,
        ask=f"Remove {{n}} duplicate row{{s}} from {table}? One copy of each stays.",
        done=f"Removed {{n}} duplicate row{{s}} from {table}.",
    )


def _remove_empty(table: str, cols: list[dict], column: str | None) -> CleanPlan:
    q = _quote(table)
    if column:
        cond, what = f"{_quote(column)} IS NULL", f"where {column} is empty"
    else:
        cond = " OR ".join(f"{_quote(c['name'])} IS NULL" for c in cols)
        what = "with any empty value"
    n = _scalar(f"SELECT COUNT(*) FROM {q} WHERE {cond}")
    if n == 0:
        return CleanPlan(table, nothing=f"No rows {what} in {table}.")
    return CleanPlan(
        table,
        sql=f"DELETE FROM {q} WHERE {cond}",
        preview_sql=f"SELECT * FROM {q} WHERE {cond} LIMIT 200",
        count=n,
        ask=f"Remove {{n}} row{{s}} {what} from {table}?",
        done=f"Removed {{n}} row{{s}} {what} from {table}.",
    )


def _fill(table: str, cols: list[dict], column: str, value_text: str) -> CleanPlan:
    q, qc = _quote(table), _quote(column)
    ctype = next(c["type"] for c in cols if c["name"] == column).upper()
    numeric = ctype in ("INTEGER", "REAL")

    word = re.sub(r"^(?:the|its|a|an)\s+", "", value_text.strip().lower()).strip(" .'\"")
    word = re.sub(r"\s+(?:value|of the column)$", "", word)
    if word in ("average", "mean", "avg", "median"):
        if not numeric:
            raise CleanError(f"'{column}' isn't a numeric column, so it has no {word}.")
        if word == "median":
            vals = [r[0] for r in get_connection().execute(f"SELECT {qc} FROM {q} WHERE {qc} IS NOT NULL").fetchall()]
            if not vals:
                raise CleanError(f"'{column}' has no values to take a {word} of.")
            value = statistics.median(vals)
        else:
            value = _scalar(f"SELECT AVG({qc}) FROM {q}")
            if value is None:
                raise CleanError(f"'{column}' has no values to take a {word} of.")
        value = round(value, 2)
        label = f"the {word} ({value:g})"
    elif word in ("zero", "0"):
        value, label = 0, "0"
    else:
        raw = value_text.strip().strip(" .'\"")
        if numeric:
            try:
                value = int(raw) if ctype == "INTEGER" and re.fullmatch(r"-?\d+", raw) else float(raw)
            except ValueError:
                raise CleanError(f"'{column}' is numeric, so it can only be filled with a number, not '{raw}'.")
        else:
            value = raw
        label = f"'{raw}'" if not numeric else str(value)

    n = _scalar(f"SELECT COUNT(*) FROM {q} WHERE {qc} IS NULL")
    if n == 0:
        return CleanPlan(table, nothing=f"No empty values in {column} of {table}.")
    return CleanPlan(
        table,
        sql=f"UPDATE {q} SET {qc} = {_literal(value)} WHERE {qc} IS NULL",
        preview_sql=f"SELECT * FROM {q} WHERE {qc} IS NULL LIMIT 200",
        count=n,
        ask=f"Fill {{n}} empty value{{s}} in {column} with {label}?",
        done=f"Filled {{n}} empty value{{s}} in {column} with {label}.",
    )


def plan_clean_command(text: str, tables: list[str]) -> CleanPlan | None:
    """A CleanPlan if `text` is a cleaning command for one of the uploaded
    `tables`, else None (so it's treated as an ordinary question)."""
    t = text.strip().lower()
    t = re.sub(r"[?!.]+$", "", t)

    verb_fill = re.search(r"\b(?:fill|replace|impute)\b", t)
    nullish = re.search(rf"\b{_NULLISH}\b", t)
    is_fill = verb_fill and nullish and re.search(r"\bwith\b", t)
    is_dedupe = re.search(r"\bdedup(?:e|licate)\b", t) or re.search(
        r"\b(?:remove|delete|drop|clean|get rid of)\b.*\b(?:duplicates?|dupes?)\b", t
    )
    is_remove_empty = (
        re.search(r"\b(?:remove|delete|drop)\b.*\brows?\b", t)
        and nullish
        and not verb_fill
    )
    rename = re.search(r"\brename\b\s+(?:the\s+)?(?:column\s+)?(.+?)\s+(?:column\s+)?to\s+(.+)$", t)
    drop_col = re.search(r"\b(?:drop|remove|delete)\b\s+(?:the\s+)?column\s+(.+)$", t)

    if not (is_fill or is_dedupe or is_remove_empty or rename or drop_col):
        return None
    table = _resolve_table(t, tables)
    if table is None:
        return None
    cols = _columns(table)

    if is_fill:
        column = _find_column(t.split(" with ")[0], cols)
        if not column:
            raise CleanError(f"Which column? Columns in {table}: {', '.join(c['name'] for c in cols)}.")
        # The fill value keeps the casing the user typed ("Unknown", not "unknown").
        value_text = re.split(r"\s+with\s+", text.strip().rstrip("?!. "), maxsplit=1, flags=re.I)[1]
        return _fill(table, cols, column, value_text)

    if is_remove_empty:
        return _remove_empty(table, cols, _find_column(t, cols))

    if is_dedupe:
        return _dedupe(table, cols)

    if rename:
        old = _match_column(re.sub(rf"\s+(?:in|of|from)\s+{re.escape(_norm(table))}$", "", rename.group(1)), cols)
        new = _sanitize_identifier(re.sub(rf"\s+(?:in|of|from)\s+{re.escape(_norm(table))}$", "", rename.group(2)), "col")
        if new != old and new in {c["name"] for c in cols}:
            raise CleanError(f"{table} already has a column called '{new}'.")
        if new == old:
            return CleanPlan(table, nothing=f"That column is already called '{old}'.")
        return CleanPlan(
            table,
            sql=f"ALTER TABLE {_quote(table)} RENAME COLUMN {_quote(old)} TO {_quote(new)}",
            ask=f"Rename column '{old}' to '{new}' in {table}?",
            done=f"Renamed column '{old}' to '{new}' in {table}.",
        )

    column = _match_column(re.sub(rf"\s+(?:in|of|from)\s+{re.escape(_norm(table))}$", "", drop_col.group(1)), cols)
    if len(cols) == 1:
        raise CleanError("That's the only column, so it can't be dropped.")
    return CleanPlan(
        table,
        sql=f"ALTER TABLE {_quote(table)} DROP COLUMN {_quote(column)}",
        ask=f"Drop column '{column}' from {table}? Its values are lost.",
        done=f"Dropped column '{column}' from {table}.",
    )


def message(template: str, n: int | None) -> str:
    """Fill `{n}` / `{s}` (plural suffix) in a plan's ask/done text."""
    n = n or 0
    return template.format(n=f"{n:,}", s="" if n == 1 else "s")
