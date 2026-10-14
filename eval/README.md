# Evaluation

Execution-accuracy evaluation of the NL→SQL pipeline on a labelled benchmark.

## What is measured

A question is **correct** when the SQL a system produces, *executed on the
database*, returns the same answer as the hand-written gold SQL (execution
accuracy, as in Spider/BIRD). Two strengths are reported:

* **Lenient (primary)** — the prediction *contains* the gold answer: every gold
  column appears with the same values on the same rows; extra columns and a
  different column order are allowed. `('Google', 14412)` correctly answers
  "which brand sold the most?" even though the gold is `('Google',)`.
* **Strict** — an identical table (same columns in the same order).

Numbers are compared after rounding to 2 decimals; row order matters only when
the gold query has `ORDER BY`. A system that produces no SQL, or invalid SQL, is
wrong.

## Systems compared (same questions, same model)

| Name | What it is |
|---|---|
| `rule` | Rule-based parser alone (abstains when no pattern matches; not applicable to uploaded tables) |
| `plain` | The LLM with the least prompt that could work: schema + question |
| `llm` | The LLM with the project's engineered prompt (schema scoping, example values, relationship hints, query plan, strict rules, few-shot examples) |
| `hybrid` | The deployed pipeline `nl2sql.parse()`: rules first, LLM only if no rule fires |

## Data and questions

* `sales` — the real 50,000-row table (`mobile_sales_data.csv`).
* `customers`, `products`, `orders`, `orders_archive` — a **synthetic, seeded**
  relational dataset (`setup_db.py`), loaded through the app's own upload path.
* `benchmark.py` — **150 questions**: 90 sales (English), 15 sales (Hinglish),
  45 multi-table (joins, three-table joins, UNION merges). Each has gold SQL.
  Multi-table questions are asked with all four tables selected.
* `heldout.py` — **40 further questions**, written before the error analysis of
  the main set and never used to guide a change. They check that fixes made
  after the first run generalise.
* `validate.py` checks every gold query runs, returns a non-empty answer, and
  does not tie at a `LIMIT` cutoff.

## Reproduce

```bash
source .venv/bin/activate
export NLP_DB_PATH=eval/eval.db
python -m eval.setup_db                        # build the database (deterministic)
python -m eval.validate                        # sanity-check all gold SQL
python -m eval.run_eval --out eval/results/run.json --workers 1
python -m eval.run_eval --set heldout --out eval/results/heldout.json --workers 1
python -m eval.report eval/results/run.json    # tables for the paper
```

Needs a reachable Ollama model (`NLP_OLLAMA_MODEL`, default `gemma4:31b-cloud`).
`--workers 1` runs one question at a time so latency is not inflated by
parallel calls. Results are saved per question, so `eval.report` can be re-run
and every failure inspected without calling the model again.

## Results

`RESULTS.md` has the consolidated tables and error analysis. In `results/`:
`v1.json` / `v2.json` are the main benchmark before and after the fixes found
by error analysis, `heldout_v1.json` / `heldout_v2.json` likewise for the
held-out set; `run.json` and `heldout.json` are copies of the final (v2) runs,
and each has a `*_report.md`. v1 is the system at commit `abd9d21`.

## Caveats

* Gold SQL and questions were written by the system's author, who also wrote
  the rule patterns, so the rule engine is likely to look better here than on
  questions from independent users. Evaluation on an external benchmark
  (Spider/BIRD) and with independent question writers remains future work.
* The model is a hosted LLM; temperature is 0 but outputs can still vary
  between runs.
* Latency includes network time to the hosted model.
