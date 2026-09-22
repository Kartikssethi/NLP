# NLP — Voice-to-SQL

A college project: speak a request in plain English (e.g. *"remove the 10
people from Mumbai in Engineering"*), it gets turned into a SQL query, run
against a database, and the results get visualized.

## How it works

1. **Speech capture** — record up to 30s from the mic.
2. **Transcription** — local speech-to-text via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (no API key, runs offline).
3. **NL → SQL** — a small rule-based parser (`app/nl2sql.py`) tries to match common phrasings first (filter, top-N, delete, count, sum, average, group-by). If nothing matches, it falls back to a local [Ollama](https://ollama.com) model to generate the SQL.
4. **Execution** — the SQL runs against a SQLite database (`data/nlp.db`, seeded with a sample `people` table).
5. **Visualization** — results get turned into a [Mermaid](https://mermaid.js.org) chart definition (bar chart for label/value pairs, a scalar for single values, a markdown table otherwise).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional, only needed for the Ollama fallback (utterances the rule-based
parser doesn't recognize):

```bash
# install Ollama from https://ollama.com, then:
ollama pull llama3.1
ollama serve   # if not already running
```

## Running it

**Web API** (FastAPI):

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

- `POST /query` — `{"text": "show me all people in mumbai"}` → SQL + results + chart
- `POST /voice-query` — records 30s from the server's mic, transcribes, then same as `/query`
- `GET /chart` — the last chart as a standalone HTML page (open in a browser)
- `GET /schema` — current DB schema
- `GET /health` — liveness check

**CLI**:

```bash
source .venv/bin/activate
python -m app.cli                          # voice loop, 30s per turn
python -m app.cli --text "top 3 people by age"   # skip the mic, just type it
```

Query results are printed as a Mermaid chart definition — paste it into
<https://mermaid.live> to see it rendered, or hit `/chart` on the web API.

## Project layout

```
app/
  main.py    FastAPI app (the web API)
  cli.py     terminal UI (voice loop or --text)
  nl2sql.py  rule-based parser + Ollama fallback
  stt.py     mic recording + faster-whisper transcription
  db.py      SQLite connection, schema introspection, sample data seed
  viz.py     query results -> Mermaid chart definition
data/
  nlp.db     SQLite database (gitignored; recreated automatically with sample data)
```

## Known limitations (starting point, not finished)

- The rule-based parser only knows the sample `people` table's columns
  (`name`, `age`, `city`, `department`) and a handful of phrasings. Swap in
  your real dataset by updating `TABLE`/`COLUMNS`/`KNOWN_CITIES`/
  `KNOWN_DEPARTMENTS` in `app/nl2sql.py`, and extend the regex patterns to
  match the phrasings you actually plan to demo.
- No confirmation step before running a generated `DELETE` — worth adding
  before a live demo (e.g. print the SQL and ask y/n before executing).
- The Ollama fallback trusts the model's SQL output as-is; for a class demo
  that's fine, but don't point this at a database you care about.
