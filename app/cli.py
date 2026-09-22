"""Minimal terminal UI: speak (or type) a request, see SQL + results.

Run with:
    python -m app.cli              interactive typing loop (default)
    python -m app.cli --voice      record from the mic each turn instead
    python -m app.cli --text "..." a single one-shot query, then exit

Nothing fancy on purpose (per project scope) — just a loop:
  1. get the request (typed, or recorded + transcribed with --voice)
  2. turn it into SQL (rules first, Ollama fallback)
  3. run it against the DB
  4. print results + a Mermaid chart you can paste into
     https://mermaid.live to view
"""
import argparse

from app.db import execute_sql, load_sales_data
from app.nl2sql import OllamaUnavailable, parse
from app.viz import build_chart


def run_once(text: str) -> None:
    print(f"\nYou said: {text!r}")
    try:
        parsed = parse(text)
    except OllamaUnavailable as exc:
        print(f"Couldn't turn that into SQL: {exc}")
        return
    print(f"SQL ({parsed.source}): {parsed.sql}")

    if parsed.is_write:
        try:
            preview_cols, preview_rows = execute_sql(parsed.preview_sql)
        except Exception as exc:  # noqa: BLE001
            print(f"SQL error: {exc}")
            return
        if not preview_rows:
            print("No matching rows — nothing to do.")
            return
        print(f"\nThis will affect {len(preview_rows)} row(s):")
        print(f"Columns: {preview_cols}")
        for row in preview_rows:
            print(row)
        answer = input(f"\nType 'yes' to run this DELETE, anything else to cancel: ").strip().lower()
        if answer != "yes":
            print("Cancelled.")
            return

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
    ap.add_argument("--text", help="Run a single query and exit")
    ap.add_argument("--voice", action="store_true", help="Record from the mic each turn instead of typing")
    ap.add_argument("--seconds", type=int, default=None, help="Override recording length (--voice only)")
    args = ap.parse_args()

    load_sales_data()

    if args.text:
        run_once(args.text)
        return

    if args.voice:
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
        return

    print("Type a query and press Enter (Ctrl+C to quit).")
    while True:
        try:
            text = input("\n> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            return
        if not text:
            continue
        run_once(text)


if __name__ == "__main__":
    main()
