"""SQLite access layer: connect, inspect schema, run SQL, load the dataset."""
import csv
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


def get_schema() -> str:
    """Return a compact text description of every table + its columns.

    This is what gets fed into the Ollama fallback prompt so the model
    knows what it's allowed to query, and it's handy for debugging too.
    """
    conn = get_connection()
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        lines = []
        for t in tables:
            table = t["name"]
            cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
            col_desc = ", ".join(f"{c['name']} {c['type']}" for c in cols)
            lines.append(f"{table}({col_desc})")
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
