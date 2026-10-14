# Evaluation results — heldout_v2

Model: `gemma4:31b-cloud` · 40 questions · gold SQL executed on the same database.

## 1. Execution accuracy (answer-containing match), 95% Wilson interval

| System | All questions (n=40) | Sales (English) (n=20) | Multi-table (uploaded files) (n=20) |
|---|---|---|---|
| Rule-based only | 10.0% [4–23] | 20.0% [8–42] | 0.0% [0–16] |
| LLM, plain prompt (baseline) | 62.5% [47–76] | 45.0% [26–66] | 80.0% [58–92] |
| LLM, engineered prompt | 100.0% [91–100] | 100.0% [84–100] | 100.0% [84–100] |
| Hybrid (rules, then LLM) — deployed | 100.0% [91–100] | 100.0% [84–100] | 100.0% [84–100] |

Strict match (identical table, same column order) and valid-SQL rate, all questions:

| System | Strict EX | Lenient EX | Valid SQL | No SQL produced |
|---|---|---|---|---|
| Rule-based only | 7.5% | 10.0% | 10.0% | 90.0% |
| LLM, plain prompt (baseline) | 62.5% | 62.5% | 100.0% | 0.0% |
| LLM, engineered prompt | 90.0% | 100.0% | 100.0% | 0.0% |
| Hybrid (rules, then LLM) — deployed | 92.5% | 100.0% | 100.0% | 0.0% |

## 2. What the rule engine handles on its own

The rules only know the `sales` schema, so they apply to 20 of 40 questions (the 20 multi-table questions always go to the LLM).

| Measure | Value |
|---|---|
| Questions the rules answered (coverage) | 4 / 20 (20.0%) |
| Correct when they answered (precision) | 4 / 4 (100.0% [51–100]) |
| Answered but wrong (confident errors) | 0 |
| Abstained (passed to the LLM) | 16 |
| LLM-only accuracy on those same 4 questions | 4 / 4 (100.0%) |

## 3. Paired comparisons (same questions; exact McNemar test)

| A vs B | A only correct | B only correct | Both | Neither | p |
|---|---|---|---|---|---|
| hybrid vs llm | 0 | 0 | 40 | 0 | 1.000 |
| llm vs plain | 15 | 0 | 25 | 0 | 0.000 |
| hybrid vs plain | 15 | 0 | 25 | 0 | 0.000 |

## 4. Response time (SQL generation; median / mean / 90th percentile)

| System | All questions | Questions it answered without the LLM |
|---|---|---|
| Rule-based only | 0 ms / 0 ms / 0 ms | 0 ms / 0 ms / 0 ms |
| LLM, plain prompt (baseline) | 0.80 s / 0.86 s / 1.12 s | — |
| LLM, engineered prompt | 0.88 s / 0.94 s / 1.11 s | — |
| Hybrid (rules, then LLM) — deployed | 0.84 s / 1.00 s / 1.23 s | 0 ms / 0 ms / 0 ms |

Hybrid answered **4 of 40** questions (10.0%) with no LLM call (mean 0 ms) and sent 36 to the LLM (mean 1.11 s), so the average hybrid response was 1.00 s versus 0.94 s for the engineered LLM alone.

## 5. Accuracy by question type

| Category | n | Rules | LLM plain | LLM engineered | Hybrid |
|---|---|---|---|---|---|
| count | 2 | 50.0% | 50.0% | 100.0% | 100.0% |
| scalar_agg | 1 | 100.0% | 0.0% | 100.0% | 100.0% |
| group_by | 4 | 25.0% | 25.0% | 100.0% | 100.0% |
| top_n | 1 | 0.0% | 0.0% | 100.0% | 100.0% |
| filter_cmp | 2 | 0.0% | 0.0% | 100.0% | 100.0% |
| multi_value | 1 | 0.0% | 100.0% | 100.0% | 100.0% |
| superlative | 2 | 50.0% | 50.0% | 100.0% | 100.0% |
| exclusion | 1 | 0.0% | 0.0% | 100.0% | 100.0% |
| temporal | 1 | 0.0% | 100.0% | 100.0% | 100.0% |
| compound | 5 | 0.0% | 80.0% | 100.0% | 100.0% |
| single_table | 6 | 0.0% | 83.3% | 100.0% | 100.0% |
| join2 | 6 | 0.0% | 66.7% | 100.0% | 100.0% |
| join3 | 2 | 0.0% | 100.0% | 100.0% | 100.0% |
| join2_products | 4 | 0.0% | 75.0% | 100.0% | 100.0% |
| merge | 2 | 0.0% | 100.0% | 100.0% | 100.0% |

## 6. Hybrid failures (0) — for error analysis
