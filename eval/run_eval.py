"""Run the benchmark: generate SQL with each system, execute it, and compare the
*result* against the gold query's result (execution accuracy).

Systems compared on the same questions:
  rule    the rule-based parser alone (abstains when no pattern matches)
  plain   the LLM with a minimal prompt: schema + question, nothing else
  llm     the LLM with this project's engineered prompt (schema scoping, example
          values, relationship hints, query plan, strict rules, few-shot examples)
  hybrid  the deployed pipeline, nl2sql.parse(): rules first, LLM if no rule fires

    NLP_DB_PATH=eval/eval.db python -m eval.run_eval --out eval/results/run1.json

Results are saved per question so the analysis (eval/report.py) can be re-run,
and every failure inspected, without calling the model again.
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from itertools import product
from pathlib import Path

os.environ.setdefault("NLP_DB_PATH", "eval/eval.db")

from app.config import OLLAMA_HOST, OLLAMA_MODEL  # noqa: E402
from app.db import execute_sql, get_schema  # noqa: E402
from app.nl2sql import OllamaUnavailable, UnsafeSQL, ollama_fallback, parse, rule_based_parse  # noqa: E402
from eval.benchmark import all_questions  # noqa: E402
from eval.heldout import heldout_questions  # noqa: E402


# --------------------------------------------------------------------------------------------
# comparing results
# --------------------------------------------------------------------------------------------

def _norm(v):
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return round(float(v), 2)  # 94188.8666 and 94188.87 are the same answer
    return str(v)


def _norm_rows(rows) -> list[tuple]:
    return [tuple(_norm(v) for v in r) for r in rows]


def _is_ordered(gold_sql: str) -> bool:
    return bool(re.search(r"\bORDER BY\b", gold_sql, re.I))


def strict_match(gold_rows, pred_rows, ordered: bool) -> bool:
    """Exactly the same table: same columns in the same order, same rows."""
    g, p = _norm_rows(gold_rows), _norm_rows(pred_rows)
    if g and p and len(g[0]) != len(p[0]):
        return False
    return g == p if ordered else Counter(g) == Counter(p)


def lenient_match(gold_rows, pred_rows, ordered: bool) -> bool:
    """The prediction contains the gold answer: every gold column appears, with
    its values on the same rows, somewhere among the predicted columns (extra
    columns and a different column order are fine). "Which brand sold the most?"
    is answered correctly by ('Google', 14412) as well as by ('Google',)."""
    g, p = _norm_rows(gold_rows), _norm_rows(pred_rows)
    if len(g) != len(p):
        return False
    if not g:
        return True
    k, m = len(g[0]), len(p[0])
    if m < k:
        return False
    gcols, pcols = list(zip(*g)), list(zip(*p))

    def sig(col):
        return tuple(col) if ordered else tuple(sorted(col, key=repr))

    candidates = [[j for j in range(m) if sig(pcols[j]) == sig(gcols[i])] for i in range(k)]
    for assign in product(*candidates):
        if len(set(assign)) < k:
            continue
        projected = [tuple(row[j] for j in assign) for row in p]
        if (projected == g) if ordered else (Counter(projected) == Counter(g)):
            return True
    return False


# --------------------------------------------------------------------------------------------
# the systems
# --------------------------------------------------------------------------------------------

def _clean(sql: str) -> str:
    sql = re.sub(r"^```(?:sql)?\s*|\s*```$", "", sql.strip(), flags=re.I | re.M).strip()
    return sql.rstrip(";").strip()


def plain_llm(question: str, tables: list[str]) -> tuple[str, str]:
    """The baseline: the same model with the least prompt that could work."""
    import ollama

    prompt = (
        f"Database schema (SQLite):\n{get_schema(tables)}\n\n"
        f"Write one SQL query that answers this question: {question}\n"
        "Return only the SQL."
    )
    resp = ollama.Client(host=OLLAMA_HOST).chat(
        model=OLLAMA_MODEL, messages=[{"role": "user", "content": prompt}], options={"temperature": 0}
    )
    return _clean(resp["message"]["content"]), "plain"


def engineered_llm(question: str, tables: list[str]) -> tuple[str, str]:
    r = ollama_fallback(question, tables=tables)
    return r.sql, r.source


def hybrid(question: str, tables: list[str]) -> tuple[str, str]:
    r = parse(question, tables=tables)
    return r.sql, r.source


def rule_only(question: str, tables: list[str]) -> tuple[str | None, str]:
    # The rule patterns are written for the `sales` schema; the app never applies
    # them to uploaded tables, so on those questions the rule system abstains.
    if tables != ["sales"]:
        return None, "rule"
    r = rule_based_parse(question)
    return (r.sql if r else None), "rule"


SYSTEMS = {"rule": rule_only, "plain": plain_llm, "llm": engineered_llm, "hybrid": hybrid}
LLM_SYSTEMS = {"plain", "llm", "hybrid"}


def run_one(system: str, q: dict, gold: tuple[list, list]) -> dict:
    fn = SYSTEMS[system]
    out = {"sql": None, "source": None, "gen_s": None, "error": None, "valid": False, "strict": False, "lenient": False}
    for attempt in range(3):  # transient cloud errors shouldn't be scored as wrong answers
        t0 = time.perf_counter()
        try:
            sql, source = fn(q["question"], q["tables"])
            out.update(sql=sql, source=source, gen_s=time.perf_counter() - t0, error=None)
            break
        except (OllamaUnavailable, UnsafeSQL) as exc:
            out.update(error=f"{type(exc).__name__}: {exc}", gen_s=time.perf_counter() - t0)
            if isinstance(exc, UnsafeSQL):
                break
            time.sleep(3 * (attempt + 1))
        except Exception as exc:  # noqa: BLE001
            out.update(error=f"{type(exc).__name__}: {exc}", gen_s=time.perf_counter() - t0)
            time.sleep(3 * (attempt + 1))

    if out["sql"] is None:
        return out  # abstained (rule) or failed to generate

    try:
        cols, rows = execute_sql(out["sql"], read_only=True)
    except Exception as exc:  # noqa: BLE001 - invalid SQL is a wrong answer, not a crash
        out["error"] = f"exec: {exc}"
        return out
    out["valid"] = True
    gold_cols, gold_rows = gold
    ordered = _is_ordered(q["gold_sql"])
    out["strict"] = strict_match(gold_rows, rows, ordered)
    out["lenient"] = lenient_match(gold_rows, rows, ordered)
    out["n_rows"] = len(rows)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="eval/results/run.json")
    ap.add_argument("--workers", type=int, default=3, help="parallel LLM calls for plain/llm")
    ap.add_argument("--only", help="comma-separated question ids (smoke test)")
    ap.add_argument("--set", choices=["dev", "heldout"], default="dev")
    ap.add_argument("--systems", default="rule,plain,llm,hybrid")
    args = ap.parse_args()

    questions = all_questions() if args.set == "dev" else heldout_questions()
    if args.only:
        wanted = set(args.only.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    gold = {q["id"]: execute_sql(q["gold_sql"], read_only=True) for q in questions}

    results: dict[str, dict] = {q["id"]: {} for q in questions}
    timings: dict[str, float] = {}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)

    def checkpoint():
        Path(args.out).write_text(json.dumps({"model": OLLAMA_MODEL, "questions": questions, "results": results,
                                              "wall_seconds": timings}, indent=1, default=str))

    for system in args.systems.split(","):
        t0 = time.perf_counter()
        # hybrid is timed one question at a time so its latency isn't inflated by
        # parallel calls; plain/llm run a few at once to keep the run short.
        workers = args.workers if system in ("plain", "llm") else 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {q["id"]: pool.submit(run_one, system, q, gold[q["id"]]) for q in questions}
            for i, (qid, fut) in enumerate(futures.items(), 1):
                results[qid][system] = fut.result()
                if i % 10 == 0 or i == len(futures):
                    done = sum(r[system]["lenient"] for r in results.values() if system in r)
                    print(f"[{system}] {i}/{len(futures)} done, {done} correct so far", flush=True)
        timings[system] = time.perf_counter() - t0
        checkpoint()
    print(f"wrote {args.out}")


if __name__ == "__main__":
    sys.exit(main())
