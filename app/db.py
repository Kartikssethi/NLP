"""SQLite access layer: connect, inspect schema, run SQL, load the dataset."""
import csv
import re
import sqlite3
from pathlib import Path
from typing import Any

from app.config import DB_PATH, SALES_CSV_PATH


def get_connection() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Some mounted/networked filesystems (e.g. a synced project folder) don't
    # support the POSIX locking SQLite's default rollback journal needs, and
    # fail with "disk I/O error". journal_mode=MEMORY avoids touching a
    # separate journal file on disk and works everywhere. Fine for a
    # single-process college project; revisit if you need multi-process
    # writers or crash-safe durability.
    conn.execute("PRAGMA journal_mode=MEMORY")
    return conn


def get_schema(table: str | None = None) -> str:
    """Return a compact text description of every table + its columns.

    This is what gets fed into the Ollama fallback prompt so the model
    knows what it's allowed to query, and it's handy for debugging too.
    Pass `table` to scope it to just one table — used for an uploaded
    dataset so the prompt isn't cluttered with the unrelated sample schema.
    """
    conn = get_connection()
    try:
        if table:
            tables = [{"name": table}]
        else:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        lines = []
        for t in tables:
            tname = t["name"]
            cols = conn.execute(f"PRAGMA table_info({tname})").fetchall()
            col_desc = ", ".join(f"{c['name']} {c['type']}" for c in cols)
            lines.append(f"{tname}({col_desc})")
        return "\n".join(lines)
    finally:
        conn.close()


def execute_sql(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Run a single SQL statement. Returns (column_names, rows).

    For SELECT this returns the result set. For INSERT/UPDATE/DELETE it
    commits and returns an empty result set with rowcount reported via
    columns=['rows_affected'].
    """
    conn = get_connection()
    try:
        cur = conn.execute(sql)
        if sql.strip().lower().startswith("select"):
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
            return columns, [tuple(r) for r in rows]
        conn.commit()
        return ["rows_affected"], [(cur.rowcount,)]
    finally:
        conn.close()


_SALES_COLUMNS = [
    "product",
    "brand",
    "product_code",
    "product_spec",
    "price",
    "inward_date",
    "dispatch_date",
    "quantity_sold",
    "customer_name",
    "customer_location",
    "region",
    "core_spec",
    "processor_spec",
    "ram",
    "rom",
    "ssd",
]


def _clean_row(row: dict) -> tuple:
    def s(key: str) -> str | None:
        val = (row.get(key) or "").strip()
        return val or None

    def n(key: str) -> int | None:
        val = (row.get(key) or "").strip()
        try:
            return int(float(val)) if val else None
        except ValueError:
            return None

    return (
        s("Product"),
        s("Brand"),
        s("Product Code"),
        s("Product Specification"),
        n("Price"),
        s("Inward Date"),
        s("Dispatch Date"),
        n("Quantity Sold"),
        s("Customer Name"),
        s("Customer Location"),
        s("Region"),
        s("Core Specification"),
        s("Processor Specification"),
        s("RAM"),
        s("ROM"),
        s("SSD"),
    )


def load_sales_data() -> None:
    """Create the `sales` table and load it from SALES_CSV_PATH, if empty.

    Idempotent: does nothing if the table already has rows, so restarts
    don't re-import 50k rows every time.
    """
    conn = get_connection()
    try:
        numeric_cols = {"price": "INTEGER", "quantity_sold": "INTEGER"}
        cols_sql = ",\n                ".join(
            f"{c} {numeric_cols.get(c, 'TEXT')}" for c in _SALES_COLUMNS
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                {cols_sql}
            )
            """
        )
        count = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        if count > 0:
            return

        csv_path = Path(SALES_CSV_PATH)
        if not csv_path.exists():
            return  # nothing to import; table stays empty

        placeholders = ", ".join("?" for _ in _SALES_COLUMNS)
        insert_sql = f"INSERT INTO sales ({', '.join(_SALES_COLUMNS)}) VALUES ({placeholders})"

        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            batch = []
            for row in reader:
                batch.append(_clean_row(row))
                if len(batch) >= 2000:
                    conn.executemany(insert_sql, batch)
                    batch.clear()
            if batch:
                conn.executemany(insert_sql, batch)
        conn.commit()
    finally:
        conn.close()


UPLOADED_TABLE = "user_data"


def _sanitize_identifier(name: str, fallback: str) -> str:
    cleaned = re.sub(r"\W+", "_", name.strip()).strip("_").lower()
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"{fallback}_{cleaned}" if cleaned else fallback
    return cleaned


def _dedupe_columns(columns: list[str], reserved: set[str] = frozenset()) -> list[str]:
    # `reserved` seeds the "already seen" set so a column colliding with a
    # name we use ourselves (e.g. the "id" primary key every uploaded table
    # gets) is renamed instead of causing a "duplicate column name" error.
    seen: dict[str, int] = {name: 0 for name in reserved}
    result = []
    for col in columns:
        if col not in seen:
            seen[col] = 0
            result.append(col)
        else:
            seen[col] += 1
            result.append(f"{col}_{seen[col]}")
    return result


def _infer_column_types(rows: list[dict], columns: list[str]) -> dict[str, str]:
    types = {}
    for col in columns:
        values = [r[col].strip() for r in rows[:500] if (r.get(col) or "").strip()]
        if not values:
            types[col] = "TEXT"
            continue
        if all(re.fullmatch(r"-?\d+", v) for v in values):
            types[col] = "INTEGER"
        elif all(re.fullmatch(r"-?\d+\.\d+", v) for v in values):
            types[col] = "REAL"
        else:
            types[col] = "TEXT"
    return types


def import_uploaded_csv(csv_path: Path, original_filename: str) -> dict:
    """Load an arbitrary user-provided CSV into UPLOADED_TABLE, replacing
    whatever was there before (only one uploaded dataset active at a time).

    Column names are sanitized to valid SQL identifiers and types are
    inferred by sampling — this table has no hand-written rule-based parser
    support (unlike `sales`), so it's only ever queried via the Ollama
    fallback, which reads the schema straight from the DB.
    """
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        raw_columns = reader.fieldnames or []
        if not raw_columns:
            raise ValueError("CSV has no header row")
        rows = list(reader)

    columns = _dedupe_columns(
        [_sanitize_identifier(c, f"col{i}") for i, c in enumerate(raw_columns)],
        reserved={"id"},
    )
    col_map = dict(zip(raw_columns, columns))
    typed_rows = [{col_map[k]: v for k, v in row.items() if k in col_map} for row in rows]
    col_types = _infer_column_types(typed_rows, columns)

    conn = get_connection()
    try:
        conn.execute(f"DROP TABLE IF EXISTS {UPLOADED_TABLE}")
        cols_sql = ",\n                ".join(f"{c} {col_types[c]}" for c in columns)
        conn.execute(
            f"""
            CREATE TABLE {UPLOADED_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                {cols_sql}
            )
            """
        )

        placeholders = ", ".join("?" for _ in columns)
        insert_sql = f"INSERT INTO {UPLOADED_TABLE} ({', '.join(columns)}) VALUES ({placeholders})"

        def coerce(col: str, val: str):
            val = (val or "").strip()
            if not val:
                return None
            if col_types[col] == "INTEGER":
                try:
                    return int(val)
                except ValueError:
                    return None
            if col_types[col] == "REAL":
                try:
                    return float(val)
                except ValueError:
                    return None
            return val

        batch = []
        for row in typed_rows:
            batch.append(tuple(coerce(c, row.get(c, "")) for c in columns))
            if len(batch) >= 2000:
                conn.executemany(insert_sql, batch)
                batch.clear()
        if batch:
            conn.executemany(insert_sql, batch)
        conn.commit()
    finally:
        conn.close()

    return {
        "table": UPLOADED_TABLE,
        "filename": original_filename,
        "columns": columns,
        "row_count": len(typed_rows),
    }
