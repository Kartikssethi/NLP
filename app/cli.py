"""Minimal terminal UI: speak (or type) a request, see SQL + results.

Run with:
    python -m app.cli

Nothing fancy on purpose (per project scope) — just a loop:
  1. record 30s of audio (or type instead if you pass --text)
  2. transcribe it
  3. turn it into SQL (rules first, Ollama fallback)
  4. run it against the DB
  5. print results + a Mermaid chart you can paste into
     https://mermaid.live to view
"""
import argparse

from app.db import execute_sql, seed_sample_db
from app.nl2sql import parse
from app.viz import build_chart


def run_once(text: str) -> None:
    print(f"\nYou said: {text!r}")
    parsed = parse(text)
    print(f"SQL ({parsed.source}): {parsed.sql}")

    try:
        columns, rows = execute_sql(parsed.sql)
    except Exception as exc:  # noqa: BLE001
        print(f"SQL error: {exc}")
        return

    print(f"\nColumns: {columns}")
    for row in rows:
        print(row)

    chart = build_chart(columns, rows)
    print("\n--- Mermaid / table (paste into https://mermaid.live) ---")
    print(chart)
    print("---")


def main() -> None:
    ap = argparse.ArgumentParser(description="Voice-to-SQL CLI")
    ap.add_argument("--text", help="Type a request instead of speaking it")
    ap.add_argument("--seconds", type=int, default=None, help="Override recording length")
    args = ap.parse_args()

    seed_sample_db()

    if args.text:
        run_once(args.text)
        return

    from app.config import RECORD_SECONDS
    from app.stt import record_and_transcribe

    while True:
        try:
            input(f"\nPress Enter to record ({args.seconds or RECORD_SECONDS}s), Ctrl+C to quit...")
        except KeyboardInterrupt:
            print("\nBye.")
            return
        text = record_and_transcribe(args.seconds or RECORD_SECONDS)
        if not text:
            print("Didn't catch any speech, try again.")
            continue
        run_once(text)


if __name__ == "__main__":
    main()
