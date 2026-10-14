# Evaluation results

Execution accuracy of four NL→SQL systems on a labelled benchmark. Model:
`gemma4:31b-cloud` (hosted Ollama), temperature 0. Everything below is read
from the saved per-question outputs in `eval/results/`; the full tables
(including per-category accuracy and every failing question) are in the
`*_report.md` files. See `README.md` for how to reproduce.

**Systems** — all use the same model on the same questions:
**Rule** = rule-based parser alone · **Plain** = LLM, schema + question only ·
**LLM** = LLM with this project's engineered prompt · **Hybrid** = the deployed
pipeline (rules first, LLM only when no rule applies).

**Metric** — a question is correct when the SQL's *executed result* contains the
gold query's result ("lenient" execution accuracy; strict = identical table is
reported separately). A system that produces no SQL, or invalid SQL, is wrong.
Intervals are 95% Wilson.

## Two versions of the system

The benchmark was run twice, so the effect of one round of error analysis is
visible:

* **v1** — the system exactly as first built (commit `abd9d21`).
* **v2** — after fixing the defects v1's errors exposed (below). `run.json`,
  `heldout.json` and their reports are v2.

Defects found by analysing v1's failures:

1. **The rule engine answered confidently when it didn't understand.** It matched a
   keyword and silently dropped everything else in the question — "per brand",
   "i7 processor", "in 2024", "above 104300", "region wise" — and a "top 3"
   ranking returned one row. 41 of its 86 answers were wrong. *Fix:* a rule
   answer only counts if every word of the question is one the patterns account
   for; otherwise it abstains and the LLM answers. Also corrected: "top N … by
   total X" ignoring N, and "how many units" treated as a row count.
2. **The multi-table prompt over-merged.** A hint saying two tables "can be
   stacked with UNION ALL" made the model union `orders` with `orders_archive`
   when the question named only `orders`. All 25 of the engineered LLM's
   multi-table errors had this single cause (the plain prompt got 18 of the same
   25 right). *Fix:* stacking is now opt-in in the hint and the rules.

## 1. Accuracy — main benchmark (150 questions)

| System | v1 all | v2 all | v2 Sales EN (90) | v2 Hinglish (15) | v2 Multi-table (45) |
|---|---|---|---|---|---|
| Rule-based only | 30.0% [23–38] | 27.3% [21–35] | 45.6% [36–56] | 0.0% [0–20] | 0.0% [0–8] |
| LLM, plain prompt | 59.3% [51–67] | 58.7% [51–66] | 52.2% [42–62] | 40.0% [20–64] | 77.8% [64–87] |
| LLM, engineered prompt | 79.3% [72–85] | **94.7% [90–97]** | 93.3% [86–97] | 100% [80–100] | 95.6% [85–99] |
| Hybrid (deployed) | 54.7% [47–62] | **94.0% [89–97]** | 93.3% [86–97] | 93.3% [70–99] | 95.6% [85–99] |

Strict match (identical table), v2: Rule 22.7% · Plain 58.0% · LLM 84.0% · Hybrid 81.3%.
Valid-SQL rate, v2: Plain, LLM and Hybrid 100%; Rule 28.7% (it abstains otherwise).

**These v2 numbers are optimistic**: the fixes were designed by looking at these
same 150 questions. The held-out set below is the less biased estimate.

## 2. What the rule engine handles on its own (the 105 sales questions)

| | v1 | v2 |
|---|---|---|
| Questions the rules answered (coverage) | 86 / 105 (81.9%) | 43 / 105 (41.0%) |
| Correct when they answered (precision) | 45 / 86 = 52.3% [42–63] | 41 / 43 = **95.3%** [85–99] |
| Answered but wrong (confident errors) | 41 | 2 |
| Abstained (sent to the LLM) | 19 | 62 |
| LLM-only accuracy on the same answered questions | 81 / 86 (94.2%) | 41 / 43 (95.3%) |

In v1 the rules answered most questions but got half of them wrong, which is
why the hybrid was *worse* than the LLM alone. The safeguard traded coverage
for precision: rules now answer fewer questions but nearly always correctly.

## 3. Head-to-head (paired, exact McNemar)

| Comparison | v1 (A only / B only, p) | v2 (A only / B only, p) |
|---|---|---|
| Hybrid vs LLM-only | 2 / 39, **p < 0.001** (hybrid worse) | 2 / 3, p = 1.00 (no difference) |
| Engineered vs plain prompt | 51 / 21, p = 0.001 | 57 / 3, **p < 0.001** |
| Hybrid vs plain prompt | 34 / 41, p = 0.49 | 56 / 3, **p < 0.001** |

* The engineered prompt is clearly better than a plain prompt (v2: 94.7% vs 58.7%).
* **The hybrid is not more accurate than the engineered LLM alone** (94.0% vs
  94.7%, p = 1.0). Its benefit is speed and determinism, not accuracy.

## 4. Response time (SQL generation; median / mean / 90th percentile)

| System | v1 | v2 |
|---|---|---|
| Rule-based only | 0 ms | 0 ms |
| LLM, plain prompt | 0.79 / 1.57 / 1.50 s | 0.74 / 0.91 / 1.55 s |
| LLM, engineered prompt | 0.77 / 0.92 / 1.21 s | 0.81 / 1.13 / 1.24 s |
| Hybrid | 0 ms / 0.42 s / 1.12 s | 0.74 / 0.87 / 0.96 s |

v2 hybrid: **43 of 150 questions (28.7%) answered with no LLM call** (0 ms); the
other 107 took a mean 1.22 s. Average response 0.87 s vs 1.13 s for the
engineered LLM alone (about 23% faster). The speed-up is smaller than in v1
(0.42 s) because v1's rules answered more questions — but wrongly. Times are
dominated by the network round trip to the hosted model; each question was run
one at a time.

## 5. Held-out set (40 questions written before the error analysis)

| System | v1 all | v2 all | v2 Sales (20) | v2 Multi-table (20) |
|---|---|---|---|---|
| Rule-based only | 12.5% [5–26] | 10.0% [4–23] | 20.0% | 0.0% |
| LLM, plain prompt | 65.0% [50–78] | 62.5% [47–76] | 45.0% | 80.0% |
| LLM, engineered prompt | 75.0% [60–86] | **100%** [91–100] | 100% | 100% |
| Hybrid | 57.5% [42–71] | **100%** [91–100] | 100% | 100% |

Rule engine on these: v1 answered 13/40 and was right on 5 (38.5%); v2 answered
4/40 and was right on all 4. Hybrid vs LLM-only: v1 1 / 8, p = 0.039; v2 0 / 0,
p = 1.0. Engineered vs plain prompt (v2): 15 / 0, p < 0.001.

The fixes carried over to unseen questions: hybrid 57.5% → 100%.

## 6. Error analysis — the 9 remaining hybrid failures (v2, main set)

| Cause | Questions | Note |
|---|---|---|
| Rule engine answered wrongly (it understood part of the question) | S18, S36 | "highest price of any Dell product" read as a group-by; "by region **and** product" grouped by region only |
| LLM ignored a filter / used the wrong column | S58, S67 | dropped "Apple A-Series processor" (used brand instead); used `rom` for "ssd" |
| Ambiguous measure (row count vs units) | S58, H01 | "how many laptops" answered with SUM(quantity) |
| Boundary / interpretation | S75, S52 | "after 1 January" taken as `>` not `>=`; "which sells more" returned both rows, not the winner |
| Label format only (counts correct) | M41, M42 | months returned as `01`–`12` instead of `2024-01`; a person would accept these, the metric does not |

## 7. Limitations of this evaluation

* **Not independent.** The questions and gold SQL were written by the system's
  author, who also wrote the rule patterns. The held-out questions were written
  after a smoke test had already revealed the two defect types, so they are
  only partly independent of the fixes. An external benchmark (Spider / BIRD)
  and independent question writers are future work.
* **Dev-set numbers are optimistic after fixing** (see §1); use the held-out figures.
* **One model, one run.** Temperature 0, but a hosted model can still vary
  between runs; no repeated-run variance is reported.
* **Synthetic multi-table data.** The multi-table results use a small seeded
  dataset (150 customers, 30 products, 1,500 orders), not a real warehouse.
* **Question wording was made unambiguous** ("sales records" = row count,
  "units" = SUM of quantity), which real users will not do; S58 and H01 show how
  the models behave when wording is ambiguous.
* The Hindi/Hinglish questions here are **typed**; the speech path was checked
  separately on a handful of synthesised utterances, not benchmarked.
