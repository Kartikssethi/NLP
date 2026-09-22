# NLP Project — Claude Configuration

This file gives Claude (Cowork / Claude Code) context when working in this repository.

## Status

Working end-to-end: voice/text -> SQL -> results -> Mermaid chart, backed by
a real 50k-row electronics sales dataset (`mobile_sales_data.csv`) loaded
into SQLite. All four paths have been run and verified: CLI text queries,
the FastAPI endpoints, the Ollama fallback (against `gemma4:31b-cloud`), and
voice transcription (via faster-whisper on synthesized speech — a live mic
still needs a human in the loop to verify end-to-end). See README.md for
setup/run instructions and example queries.

## Project

A college project: a natural-language-to-SQL tool for people who don't know
SQL. The user speaks (up to a 30s window) or types a request like "top 5
brands by quantity sold" or "how many laptops were sold in the west region"
— it gets parsed into a SQL query, run against a database, and the results
get visualized.

Pipeline: speech capture -> local transcription (faster-whisper) -> NL->SQL
(rule-based first, Ollama model fallback) -> SQLite execution -> Mermaid
chart. See README.md for the full breakdown.

Stack: Python 3.10/3.11, FastAPI + uvicorn (web API), a plain CLI (no
frontend framework — kept deliberately simple per project scope), SQLite,
faster-whisper, Ollama (cloud model by default, swappable for local),
mermaid-py / raw Mermaid syntax for charts.

## Conventions

- Package manager: `pip` + a `.venv` virtualenv (see README "Setup"). Always
  `source .venv/bin/activate` before running anything — and if `python`
  inside an activated venv doesn't resolve to `.venv/bin/python3`/`sys.prefix
  == .venv`, something's shadowing it (e.g. a shell alias); use
  `.venv/bin/python3` explicitly rather than trust `source activate` blindly.
- No test suite yet — the closest thing is manually hitting `/query` or
  running `python -m app.cli --text "..."` with a few sample utterances (see
  README's "Example queries"). If you add real tests, use `pytest` and put
  them under `tests/`.
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
- `app/nl2sql.py`'s rule-based parser is tuned to the `sales` table's real
  columns (product, brand, region, ram, rom, price, quantity_sold,
  customer_name). `KNOWN_PRODUCTS`/`KNOWN_BRANDS`/`KNOWN_REGIONS`/
  `KNOWN_RAM`/`KNOWN_ROM` are the literal values it matches against — if the
  dataset changes, update those sets (and `DIMENSION_WORDS`/
  `COLUMN_ALIASES` for group-by/aggregate phrasings) to match.
- **DELETE safety**: never make a recognized delete/remove utterance execute
  without a confirmation step (CLI: prints affected rows, requires typed
  `yes`; API: returns a preview + `requires_confirmation: true` unless the
  request includes `"confirm": true`). Don't remove this when touching
  `nl2sql.py`/`cli.py`/`main.py`.
- `*.db`, `.venv/`, and recorded `*.wav` files are gitignored — don't commit
  them even if asked to "save everything". `mobile_sales_data.csv` IS
  committed (it's the source dataset, needed for anyone cloning the repo to
  rebuild `data/nlp.db`).
- Ollama fallback default model is `gemma4:31b-cloud` (a free-tier cloud
  model on this Ollama account — not all `*-cloud` models on `ollama list`
  are free; check before switching). To use a local model instead, pull it
  and set `NLP_OLLAMA_MODEL`.

## Working notes

- Repo root: `~/V1_PROJECT/NLP` (on Kartik's Mac)
- Remote: `origin` → `github.com/Kartikssethi/NLP.git`, tracking `main`
- Kartik is running Claude both via this Cowork session (device-bridged to
  this same folder) and via Claude Code CLI/`</>` in the same repo — either
  surface sees the same files since it's the same folder on disk.
- `nigeria_messy_sales_dataset.csv` is a leftover from an earlier dataset
  choice that got swapped out — the app doesn't reference it. Safe to
  delete if you don't need it, or ask Kartik before removing it.
