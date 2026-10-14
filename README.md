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

- `POST /query` — `{"text": "top 5 brands by quantity sold"}` (optionally `"tables": ["orders", "customers"]`, and `"drill": {"column", "value"}` for a clicked chart bar; see below) → SQL + results + chart. For a DELETE utterance, returns a preview (`requires_confirmation: true`) unless you also pass `"confirm": true`.
- `POST /voice-query` — records 30s from the server's mic, transcribes, then same as `/query`
- `POST /upload-dataset` — upload a CSV or Excel (`.xlsx`) file. A CSV becomes its own table named after the file (`customers.csv` → `customers`); a workbook becomes one table per non-empty sheet (`shop.xlsx` with sheets Customers/Orders → `shop_customers`, `shop_orders`). Upload as many as you like — re-uploading a name replaces that table.
- `GET /datasets`, `DELETE /datasets/{table}` — list / remove uploaded tables
- `POST /suggest-questions` — `{"tables": [...]}` → starter questions generated from those tables' schema
- `POST /summarize` — LLM-written answer sentence for result shapes `/query` doesn't summarize itself
- `POST /run-sql` — run SQL you edited by hand (read-only: SELECT/WITH only, and SQLite itself refuses writes)
- `GET /er-diagram?tables=a,b` — Mermaid ER diagram of tables and the links detected between them
- `POST /transcribe?multilingual=true&to_english=true` — Hindi/Hinglish speech → English question
- `GET /chart` — the last chart as a standalone HTML page (open in a browser)
- `GET /schema` — current DB schema
- `GET /health` — liveness check

**Joining your own files**: in the web UI, click *Upload datasets* and pick
any number of CSV or Excel files. Each shows up as a chip under the chat; click chips
to choose which tables a question runs against (the built-in `sales` table
can be mixed in too). With more than one selected, just ask across them —
"total revenue per customer city", "combine orders and orders_extra and count
them" — and the model writes the JOIN / UNION ALL. It's given each table's
schema, sample values, and detected relationships (shared column names,
`<x>_id` → `<x>.id`, identical column sets) to pick join keys from. Queries
over uploaded tables always go through Ollama (the rule-based parser only
knows `sales`), and any query is stopped after 15 seconds so a missing join
condition can't hang the server.

**Answers, charts and voice**: every result opens with a one-sentence answer
("Delhi has the highest total revenue at 2,720, about 36% of the total.").
For the common shapes it is computed straight from the rows in `app/summary.py`
(never LLM-written, so the numbers can't be invented); other shapes ask the
model via `/summarize`. A 2-column label + number result can be shown as a
**Bar, Line or Pie** chart — the switcher appears when more than one fits, and
the first view follows the wording ("share of…" → pie, "trend" → line).
*Listen* reads an answer aloud with the browser's speech synthesis, *Voice
replies* reads every answer, and answers to questions you *speak* are always
read. Starter questions under the chat box are generated from the selected
tables (fixed ones for the sample data).

**More things the web UI does**:

- **Hindi / Hinglish voice** — the *Voice* toggle switches the mic to Hindi or
  Hinglish. Whisper (`small`, a one-time ~460 MB download; set
  `NLP_WHISPER_MULTILINGUAL_MODEL` to change) transcribes in the language
  spoken and the LLM rewrites it as an English question using the table schema
  to repair mishearings ("branches" → "brands"). The live caption shows what
  was heard; the chat shows both. Typed Hinglish works too.
- **Click a bar or pie slice** to break that value down ("Delhi" → Delhi by
  product); the previous query is narrowed and regrouped by another column.
- **Insight pills** under the answer ("Units fell 38% in 2024-04 compared with
  2024-03") are found by arithmetic, never by the model. Data usually starts
  and stops mid-period, so incomplete first/last periods are detected, left out
  of comparisons and forecasts, and called out.
- **Forecast** — "predict the next 3 months of sales" fits a straight line to the
  monthly series and draws it dashed. It says how well the line fits.
- **Data health card** after each upload (duplicate rows, empty cells per
  column, distinct counts) with one-click cleaning suggestions, plus a diagram of
  how your files connect.
- **Cleaning by command**, on uploaded tables only (never the sample data):
  "remove duplicate rows", "fill empty price with the average / median / 0 /
  Unknown", "remove rows where city is missing", "rename column cust to
  customer", "drop column notes". Each shows exactly what it will change and
  waits for confirmation. It edits the loaded copy, not your original file.
- **Pin** results to build a dashboard (saved in this browser) and **Report**
  to print either the dashboard or the whole chat — *Print / Save as PDF*.
- **Edit SQL** on any result to tweak the query and re-run it (read-only).

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
  db.py      SQLite connection, schema/join-hint introspection, sales + uploaded-CSV table loading
  viz.py     query results -> Mermaid chart definition
data/
  nlp.db     SQLite database (gitignored; rebuilt automatically from the CSV)
mobile_sales_data.csv   the source dataset
```

## Evaluation

`eval/` holds a labelled benchmark (150 questions + 40 held-out, with gold SQL,
over the real sales table and a seeded multi-table dataset) and the code to run
it. Headline results on the held-out set: the hybrid pipeline reaches 100%
(40/40) execution accuracy versus 62.5% for a plain-prompt LLM; on the main set
94.0% vs 94.7% for the LLM alone (no significant difference), with 29% of
questions answered by the rules with no LLM call. See `eval/RESULTS.md` for
all tables, the error analysis and the caveats, and `eval/README.md` to rerun.

## Known limitations

- The rule-based parser knows `sales` table columns (product, brand, region,
  RAM, ROM, price, quantity sold, customer) and a solid but not exhaustive
  set of phrasings. Genuinely novel phrasings fall through to the Ollama
  model.
- `customer_location` (25k+ nearly-unique fake city names) and
  `product_spec` (random filler text) are stored but not treated as
  filterable dimensions — too high-cardinality to be useful for NL filters.
- Join keys for uploaded files are the model's best inference from column
  names and sample values; a CSV with cryptic column names may join wrongly,
  so check the SQL shown with each answer.
- The Ollama fallback trusts the model's SQL output as-is; fine for a class
  demo, but don't point this at a database you care about.
