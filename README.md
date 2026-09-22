# NLP — Voice-to-SQL

A college project: speak a request in plain English (e.g. *"top 5 brands by
quantity sold"* or *"how many laptops were sold in the west region"*), it
gets turned into a SQL query, run against a database, and the results get
visualized.

## The dataset

`mobile_sales_data.csv` — 50,000 rows of electronics sales: `Laptop` /
`Mobile Phone`, 20 brands (Apple, Samsung, Dell, ...), 5 regions (West,
South, North, Central, East), plus price, quantity sold, RAM/ROM/processor
spec, customer info, and dates. Loaded into a `sales` table in SQLite on
first run — see `app/db.py::load_sales_data()`.

## How it works

1. **Speech capture** — record up to 30s from the mic.
2. **Transcription** — local speech-to-text via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (no API key, runs offline).
3. **NL → SQL** — a rule-based parser (`app/nl2sql.py`) matches common phrasings first: filter by product/brand/region/RAM/ROM, top-N (row-level or grouped/aggregated), count, group-by, sum/average (scalar or grouped), delete. It understands both digits and spelled-out numbers ("top 5" / "top five" — the latter matters since Whisper transcribes numbers as words). If nothing matches, it falls back to an [Ollama](https://ollama.com) model to generate the SQL.
4. **Execution** — the SQL runs against a SQLite database (`data/nlp.db`).
5. **Visualization** — results get turned into a [Mermaid](https://mermaid.js.org) chart definition (bar chart for label/value pairs, a scalar for single values, a markdown table otherwise).

**Safety:** a recognized "delete N ..." utterance never executes immediately.
It's parsed into a DELETE statement plus a preview SELECT showing exactly
which rows would be affected. The CLI prints the preview and asks for a
typed `yes`; the API returns the preview with `requires_confirmation: true`
and only executes once you resubmit with `"confirm": true`.

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
ollama serve   # if not already running
```

By default this project uses `gemma4:31b-cloud` (an Ollama cloud model —
needs `ollama signin` and usage available on your account, no local
download). To use a local model instead, `ollama pull <model>` and set
`NLP_OLLAMA_MODEL=<model>`.

## Running it

**Web API** (FastAPI):

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

- `POST /query` — `{"text": "top 5 brands by quantity sold"}` → SQL + results + chart. For a DELETE utterance, returns a preview (`requires_confirmation: true`) unless you also pass `"confirm": true`.
- `POST /voice-query` — records 30s from the server's mic, transcribes, then same as `/query`
- `GET /chart` — the last chart as a standalone HTML page (open in a browser)
- `GET /schema` — current DB schema
- `GET /health` — liveness check

**CLI**:

```bash
source .venv/bin/activate
python -m app.cli                          # voice loop, 30s per turn
python -m app.cli --text "top 3 brands by quantity sold"   # skip the mic, just type it
```

Query results are printed as a Mermaid chart definition — paste it into
<https://mermaid.live> to see it rendered, or hit `/chart` on the web API.

### Example queries

```
show laptops in the west region
how many mobile phones were sold in south
top 5 brands by quantity sold
average price of samsung phones
total quantity sold by region
count by product
sum of price for apple laptops
delete 2 laptops in the central region
```

## Project layout

```
app/
  main.py    FastAPI app (the web API)
  cli.py     terminal UI (voice loop or --text)
  nl2sql.py  rule-based parser + Ollama fallback
  stt.py     mic recording + faster-whisper transcription
  db.py      SQLite connection, schema introspection, CSV -> sales table load
  viz.py     query results -> Mermaid chart definition
data/
  nlp.db     SQLite database (gitignored; rebuilt automatically from the CSV)
mobile_sales_data.csv   the source dataset
```

## Known limitations

- The rule-based parser knows `sales` table columns (product, brand, region,
  RAM, ROM, price, quantity sold, customer) and a solid but not exhaustive
  set of phrasings. Genuinely novel phrasings fall through to the Ollama
  model.
- `customer_location` (25k+ nearly-unique fake city names) and
  `product_spec` (random filler text) are stored but not treated as
  filterable dimensions — too high-cardinality to be useful for NL filters.
- The Ollama fallback trusts the model's SQL output as-is; fine for a class
  demo, but don't point this at a database you care about.
