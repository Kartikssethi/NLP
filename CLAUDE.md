# NLP Project — Claude Configuration

This file gives Claude (Cowork / Claude Code) context when working in this repository.

## Status

Scaffolded and working: voice/text -> SQL -> results -> Mermaid chart, backed
by a sample SQLite `people` table. See README.md for setup/run instructions.

## Project

A college project: a natural-language-to-SQL tool for people who don't know
SQL. The user speaks (up to a 30s window) or types a request like "remove
the 10 people in Mumbai in Engineering" or "how many people are in each
department" — it gets parsed into a SQL query, run against a database, and
the results get visualized.

Pipeline: speech capture -> local transcription (faster-whisper) -> NL->SQL
(rule-based first, Ollama model fallback) -> SQLite execution -> Mermaid
chart. See README.md for the full breakdown.

Stack: Python 3.10, FastAPI + uvicorn (web API), a plain CLI (no frontend
framework — kept deliberately simple per project scope), SQLite, faster-whisper,
Ollama (optional fallback), mermaid-py / raw Mermaid syntax for charts.

## Conventions

- Package manager: `pip` + a `.venv` virtualenv (see README "Setup"). Always
  `source .venv/bin/activate` before running anything.
- No test suite yet — the closest thing is manually hitting `/query` or
  running `python -m app.cli --text "..."` with a few sample utterances.
  If you add real tests, use `pytest` and put them under `tests/`.
- No linter/formatter configured yet. Keep to the existing style (type
  hints, small focused functions, docstrings explaining *why* not just
  *what* — see existing files in `app/` as the reference).
- Folder layout: see README.md "Project layout".
- **Important — SQLite over this mounted folder**: this repo lives on a
  bridged/synced folder, and SQLite's default rollback-journal locking
  fails there with `disk I/O error`. `app/db.py`'s `get_connection()` sets
  `PRAGMA journal_mode=MEMORY` to work around it — don't remove that
  unless you've confirmed the underlying filesystem issue is gone, and
  don't add WAL mode (same problem).
- `app/nl2sql.py`'s rule-based parser is intentionally narrow (tuned to the
  sample `people` table). When the real dataset is decided, update
  `TABLE`/`COLUMNS`/`KNOWN_CITIES`/`KNOWN_DEPARTMENTS` there and extend the
  regex patterns to match it.
- `*.db`, `.venv/`, and recorded `*.wav` files are gitignored — don't commit
  them even if asked to "save everything".

## Working notes

- Repo root: `~/V1_PROJECT/NLP` (on Kartik's Mac)
- Remote: `origin` → `github.com/Kartikssethi/NLP.git`, tracking `main`
- Kartik is running Claude both via this Cowork session (device-bridged to
  this same folder) and via Claude Code CLI/`</>` in the same repo — either
  surface sees the same files since it's the same folder on disk.
