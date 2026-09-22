# Handoff — where things stand

Written after scaffolding the project via Cowork (desktop app), for whoever
picks this up next (you, in Claude Code, most likely). CLAUDE.md has the
ongoing conventions; this file is a one-time checklist of what's pending.

## Do first

- [ ] `git push origin main` — there's a local commit (`5344cd5`,
      "Scaffold voice-to-SQL app...") that hasn't been pushed yet. The
      Cowork session that built it couldn't push (its sandboxed shell has
      no GitHub credentials); a normal terminal / Claude Code should push
      fine using your existing git auth.

## Untested — verify these actually work

- [ ] **Voice path**: `python -m app.cli` (no `--text` flag) records 30s
      from the mic and transcribes with faster-whisper. Never tested with
      a real mic — the sandboxed session that built this had no mic
      access. Try it and see how transcription quality/latency feels.
- [ ] **Ollama fallback**: `app/nl2sql.py`'s `ollama_fallback()` only
      fires when the rule-based parser doesn't recognize the phrasing.
      Every test utterance so far matched a rule, so this path has never
      actually run. Needs `ollama serve` running + `ollama pull llama3.1`
      (or change `OLLAMA_MODEL` in `app/config.py`) before it'll work.

## Real decisions still needed

- [ ] **The real dataset.** Everything currently runs against a seeded
      sample `people` table (name, age, city, department) in
      `app/db.py::seed_sample_db()`. Once the actual dataset is picked,
      swap that out and update `TABLE` / `COLUMNS` / `KNOWN_CITIES` /
      `KNOWN_DEPARTMENTS` in `app/nl2sql.py`, plus extend the regex
      patterns in `rule_based_parse()` to match the phrasings you'll
      actually demo.
- [ ] **Safety on DELETE.** Right now a recognized "remove/delete N ..."
      utterance runs immediately, no confirmation. Fine for testing, risky
      for a live demo — add a print-the-SQL-and-confirm step before it
      executes, in `app/cli.py` and/or `app/main.py`.

## Known gotcha, already worked around — don't "fix" it back

This repo folder is on a bridged/synced mount. SQLite's default
rollback-journal locking fails there with `disk I/O error`. `app/db.py`'s
`get_connection()` sets `PRAGMA journal_mode=MEMORY` to work around it.
Leave that alone unless you've independently confirmed the filesystem
issue is gone (e.g. you're now running purely locally, not through a
bridge) — and don't switch it to WAL mode, same problem.

## Everything else

See `README.md` for setup/run instructions and `CLAUDE.md` for ongoing
conventions Claude should follow while working in this repo.
