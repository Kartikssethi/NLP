"""SQLite access layer: connect, inspect schema, run SQL, seed sample data."""
import sqlite3
from pathlib import Path
from typing import Any

from app.config import DB_PATH


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


def seed_sample_db() -> None:
    """Create a small 'people' table with sample data, if it doesn't exist yet.

    This exists so you have something to talk to immediately. Swap it out
    for your real dataset whenever it's ready (see README).
    """
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                age INTEGER,
                city TEXT,
                department TEXT
            )
            """
        )
        count = conn.execute("SELECT COUNT(*) FROM people").fetchone()[0]
        if count == 0:
            sample = [
                ("Aarav Sharma", 24, "Mumbai", "Engineering"),
                ("Diya Patel", 29, "Pune", "Sales"),
                ("Vihaan Rao", 35, "Bengaluru", "Engineering"),
                ("Ananya Iyer", 22, "Mumbai", "Marketing"),
                ("Kabir Singh", 31, "Delhi", "Sales"),
                ("Ishaan Nair", 27, "Chennai", "Engineering"),
                ("Myra Gupta", 26, "Mumbai", "Marketing"),
                ("Reyansh Joshi", 40, "Pune", "Engineering"),
                ("Saanvi Mehta", 33, "Delhi", "Sales"),
                ("Arjun Kapoor", 28, "Bengaluru", "Marketing"),
                ("Aadhya Desai", 30, "Mumbai", "Engineering"),
                ("Vivaan Chawla", 25, "Chennai", "Sales"),
            ]
            conn.executemany(
                "INSERT INTO people (name, age, city, department) VALUES (?, ?, ?, ?)",
                sample,
            )
            conn.commit()
    finally:
        conn.close()
