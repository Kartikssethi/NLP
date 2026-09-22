# Handoff — where things stand

Previous checklist is done: dataset swapped in, DELETE safety added, voice
and Ollama paths tested. This is what's left.

## Verified this round

- [x] Real dataset (`mobile_sales_data.csv`, 50k rows) loaded into a `sales`
      table, replacing the old fake `people` table.
- [x] Rule-based parser rewritten for the real schema — filters
      (product/brand/region/RAM/ROM), grouped/aggregate top-N, count,
      group-by, sum/average (scalar and grouped), delete. Handles spelled-out
      numbers ("top five") for voice input, not just digits.
- [x] DELETE confirmation: CLI prints affected rows and requires a typed
      `yes`; API returns a preview with `requires_confirmation: true` unless
      `confirm: true` is sent. Tested both accept and decline paths, CLI and
      API.
- [x] Voice path: faster-whisper transcription tested against synthesized
      speech (macOS `say`), fed through the full pipeline successfully.
      **Not yet tested with a live human speaker** — that still needs you.
- [x] Ollama fallback: tested for real against `gemma4:31b-cloud` (now the
      default `OLLAMA_MODEL`) — both a genuinely out-of-scope query and a
      genuinely complex in-scope one, both produced sane SQL.

## Still open

- [ ] **Live mic test.** Run `python -m app.cli` (no `--text`) and actually
      speak into it. The synthesized-speech test proves the STT pipeline
      works; it doesn't prove mic capture, ambient noise handling, or real
      speech patterns work.
- [ ] **No automated tests.** Everything above was verified by hand. If this
      needs to survive changes without manual re-checking every path,
      consider a small `pytest` suite under `tests/` covering `nl2sql.py`'s
      parser (it's pure functions, easy to test) at least.
- [ ] **`nigeria_messy_sales_dataset.csv`** is a leftover from an earlier
      dataset choice — unused by the app. Delete it or keep it, your call.
- [ ] **Ollama cloud dependency.** `gemma4:31b-cloud` is free on this
      account today; that could change, or the account running the demo
      might not have it. If you want zero external dependency for the
      fallback, pull a small local model instead and change
      `NLP_OLLAMA_MODEL`.

## Known gotcha, already worked around — don't "fix" it back

This repo folder is on a bridged/synced mount. SQLite's default
rollback-journal locking fails there with `disk I/O error`. `app/db.py`'s
`get_connection()` sets `PRAGMA journal_mode=MEMORY` to work around it.
Leave that alone unless you've independently confirmed the filesystem
issue is gone (e.g. you're now running purely locally, not through a
bridge) — and don't switch it to WAL mode, same problem.

## Everything else

See `README.md` for setup/run instructions, example queries, and known
limitations, and `CLAUDE.md` for ongoing conventions Claude should follow
while working in this repo.
