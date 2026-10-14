"""Turn a results file from run_eval.py into the tables for the paper.

    python -m eval.report eval/results/v1.json            # prints + writes v1_report.md

Everything is computed from the saved per-question results — no model calls —
so the analysis can be re-run, and any single failure inspected, at any time.
"""
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

SYSTEM_ORDER = ["rule", "plain", "llm", "hybrid"]
LABEL = {
    "rule": "Rule-based only",
    "plain": "LLM, plain prompt (baseline)",
    "llm": "LLM, engineered prompt",
    "hybrid": "Hybrid (rules, then LLM) — deployed",
}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact p-value for paired binary outcomes; b and c are the two
    kinds of disagreement (A right & B wrong, A wrong & B right)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def pct(k: int, n: int) -> str:
    return f"{100 * k / n:.1f}%" if n else "—"


def with_ci(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"{100 * k / n:.1f}% [{100 * lo:.0f}–{100 * hi:.0f}]" if n else "—"


def secs(values: list[float]) -> str:
    if not values:
        return "—"
    s = sorted(values)
    p90 = s[min(len(s) - 1, math.ceil(0.9 * len(s)) - 1)]
    med = statistics.median(s)
    unit = (lambda v: f"{v * 1000:.0f} ms") if med < 0.05 else (lambda v: f"{v:.2f} s")
    return f"{unit(med)} / {unit(statistics.mean(s))} / {unit(p90)}"


def build(path: str) -> str:
    data = json.loads(Path(path).read_text())
    questions = {q["id"]: q for q in data["questions"]}
    results = data["results"]
    systems = [s for s in SYSTEM_ORDER if all(s in r for r in results.values())]
    ids = list(questions)

    def ok(system: str, qid: str, key: str = "lenient") -> bool:
        return bool(results[qid][system][key])

    is_multi = lambda i: questions[i]["dataset"] == "multi"  # noqa: E731
    is_hinglish = lambda i: questions[i]["category"] == "hinglish"  # noqa: E731
    subsets = {
        "All questions": ids,
        "Sales (English)": [i for i in ids if not is_multi(i) and not is_hinglish(i)],
        "Sales (Hinglish)": [i for i in ids if is_hinglish(i)],
        "Multi-table (uploaded files)": [i for i in ids if is_multi(i)],
    }
    subsets = {name: sub for name, sub in subsets.items() if sub}
    out = [f"# Evaluation results — {Path(path).stem}", "",
           f"Model: `{data['model']}` · {len(ids)} questions · gold SQL executed on the same database.", ""]

    # ---- 1. headline accuracy --------------------------------------------------------------------
    out += ["## 1. Execution accuracy (answer-containing match), 95% Wilson interval", "",
            "| System | " + " | ".join(f"{name} (n={len(sub)})" for name, sub in subsets.items()) + " |",
            "|---|" + "---|" * len(subsets)]
    for s in systems:
        out.append(f"| {LABEL[s]} | " + " | ".join(with_ci(sum(ok(s, i) for i in sub), len(sub)) for sub in subsets.values()) + " |")
    out += ["", "Strict match (identical table, same column order) and valid-SQL rate, all questions:", "",
            "| System | Strict EX | Lenient EX | Valid SQL | No SQL produced |", "|---|---|---|---|---|"]
    n = len(ids)
    for s in systems:
        out.append(f"| {LABEL[s]} | {pct(sum(ok(s, i, 'strict') for i in ids), n)} | {pct(sum(ok(s, i) for i in ids), n)} | "
                   f"{pct(sum(results[i][s]['valid'] for i in ids), n)} | {pct(sum(results[i][s]['sql'] is None for i in ids), n)} |")

    # ---- 2. the rule engine ---------------------------------------------------------------------------
    applicable = [i for i in ids if not is_multi(i)]
    answered = [i for i in applicable if results[i]["rule"]["sql"] is not None] if "rule" in systems else []
    if answered:
        right = [i for i in answered if ok("rule", i)]
        out += ["", "## 2. What the rule engine handles on its own", "",
                f"The rules only know the `sales` schema, so they apply to {len(applicable)} of {len(ids)} questions "
                f"(the {len(ids) - len(applicable)} multi-table questions always go to the LLM).", "",
                "| Measure | Value |", "|---|---|",
                f"| Questions the rules answered (coverage) | {len(answered)} / {len(applicable)} ({pct(len(answered), len(applicable))}) |",
                f"| Correct when they answered (precision) | {len(right)} / {len(answered)} ({with_ci(len(right), len(answered))}) |",
                f"| Answered but wrong (confident errors) | {len(answered) - len(right)} |",
                f"| Abstained (passed to the LLM) | {len(applicable) - len(answered)} |"]
        if "llm" in systems:
            llm_on_same = sum(ok("llm", i) for i in answered)
            out.append(f"| LLM-only accuracy on those same {len(answered)} questions | {llm_on_same} / {len(answered)} ({pct(llm_on_same, len(answered))}) |")

    # ---- 3. head-to-head tests --------------------------------------------------------------------------------
    out += ["", "## 3. Paired comparisons (same questions; exact McNemar test)", "",
            "| A vs B | A only correct | B only correct | Both | Neither | p |", "|---|---|---|---|---|---|"]
    for a, b in [("hybrid", "llm"), ("llm", "plain"), ("hybrid", "plain")]:
        if a in systems and b in systems:
            only_a = sum(ok(a, i) and not ok(b, i) for i in ids)
            only_b = sum(ok(b, i) and not ok(a, i) for i in ids)
            both = sum(ok(a, i) and ok(b, i) for i in ids)
            neither = n - only_a - only_b - both
            out.append(f"| {a} vs {b} | {only_a} | {only_b} | {both} | {neither} | {mcnemar_exact(only_a, only_b):.3f} |")

    # ---- 4. latency ---------------------------------------------------------------------------------------------------
    out += ["", "## 4. Response time (SQL generation; median / mean / 90th percentile)", "",
            "| System | All questions | Questions it answered without the LLM |", "|---|---|---|"]
    for s in systems:
        times = [results[i][s]["gen_s"] for i in ids if results[i][s]["gen_s"] is not None]
        no_llm = [results[i][s]["gen_s"] for i in ids if results[i][s].get("source") == "rule" and results[i][s]["sql"]]
        out.append(f"| {LABEL[s]} | {secs(times)} | {secs(no_llm) if no_llm else '—'} |")
    if "hybrid" in systems:
        by_rule = [i for i in ids if results[i]["hybrid"].get("source") == "rule" and results[i]["hybrid"]["sql"]]
        via_llm = [i for i in ids if i not in by_rule and results[i]["hybrid"]["gen_s"] is not None]
        t_rule = statistics.mean(results[i]["hybrid"]["gen_s"] for i in by_rule) if by_rule else 0
        t_llm = statistics.mean(results[i]["hybrid"]["gen_s"] for i in via_llm) if via_llm else 0
        out += ["", f"Hybrid answered **{len(by_rule)} of {n}** questions ({pct(len(by_rule), n)}) with no LLM call "
                    f"(mean {t_rule * 1000:.0f} ms) and sent {len(via_llm)} to the LLM (mean {t_llm:.2f} s), "
                    f"so the average hybrid response was {(len(by_rule) * t_rule + len(via_llm) * t_llm) / n:.2f} s "
                    + (f"versus {statistics.mean(results[i]['llm']['gen_s'] for i in ids if results[i]['llm']['gen_s'] is not None):.2f} s for the engineered LLM alone." if 'llm' in systems else ".")]

    # ---- 5. by category ----------------------------------------------------------------------------------------------------
    by_cat: dict[str, list[str]] = defaultdict(list)
    for i in ids:
        by_cat[questions[i]["category"]].append(i)
    out += ["", "## 5. Accuracy by question type", "",
            "| Category | n | " + " | ".join(LABEL[s].split(" (")[0].split(",")[0] if s != "plain" else "LLM plain" for s in systems) + " |",
            "|---|---|" + "---|" * len(systems)]
    short = {"rule": "Rules", "plain": "LLM plain", "llm": "LLM engineered", "hybrid": "Hybrid"}
    out[-2] = "| Category | n | " + " | ".join(short[s] for s in systems) + " |"
    for cat, sub in by_cat.items():
        out.append(f"| {cat} | {len(sub)} | " + " | ".join(pct(sum(ok(s, i) for i in sub), len(sub)) for s in systems) + " |")

    # ---- 6. failures to inspect ----------------------------------------------------------------------------------------------
    if "hybrid" in systems:
        fails = [i for i in ids if not ok("hybrid", i)]
        out += ["", f"## 6. Hybrid failures ({len(fails)}) — for error analysis", ""]
        for i in fails:
            q, r = questions[i], results[i]["hybrid"]
            state = "no valid SQL" if not r["valid"] else "wrong result"
            out += [f"**{i}** ({q['category']}, {state}) — {q['question']}",
                    f"- gold: `{q['gold_sql']}`",
                    f"- hybrid [{r.get('source')}]: `{' '.join((r['sql'] or '(none)').split())}`" + (f"  — error: {r['error']}" if r.get("error") else ""),
                    ""]
    return "\n".join(out)


def main() -> None:
    path = sys.argv[1]
    report = build(path)
    Path(path).with_name(Path(path).stem + "_report.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
