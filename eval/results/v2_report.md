# Evaluation results — v2

Model: `gemma4:31b-cloud` · 150 questions · gold SQL executed on the same database.

## 1. Execution accuracy (answer-containing match), 95% Wilson interval

| System | All questions (n=150) | Sales (English) (n=90) | Sales (Hinglish) (n=15) | Multi-table (uploaded files) (n=45) |
|---|---|---|---|---|
| Rule-based only | 27.3% [21–35] | 45.6% [36–56] | 0.0% [0–20] | 0.0% [0–8] |
| LLM, plain prompt (baseline) | 58.7% [51–66] | 52.2% [42–62] | 40.0% [20–64] | 77.8% [64–87] |
| LLM, engineered prompt | 94.7% [90–97] | 93.3% [86–97] | 100.0% [80–100] | 95.6% [85–99] |
| Hybrid (rules, then LLM) — deployed | 94.0% [89–97] | 93.3% [86–97] | 93.3% [70–99] | 95.6% [85–99] |

Strict match (identical table, same column order) and valid-SQL rate, all questions:

| System | Strict EX | Lenient EX | Valid SQL | No SQL produced |
|---|---|---|---|---|
| Rule-based only | 22.7% | 27.3% | 28.7% | 71.3% |
| LLM, plain prompt (baseline) | 58.0% | 58.7% | 100.0% | 0.0% |
| LLM, engineered prompt | 84.0% | 94.7% | 100.0% | 0.0% |
| Hybrid (rules, then LLM) — deployed | 81.3% | 94.0% | 100.0% | 0.0% |

## 2. What the rule engine handles on its own

The rules only know the `sales` schema, so they apply to 105 of 150 questions (the 45 multi-table questions always go to the LLM).

| Measure | Value |
|---|---|
| Questions the rules answered (coverage) | 43 / 105 (41.0%) |
| Correct when they answered (precision) | 41 / 43 (95.3% [85–99]) |
| Answered but wrong (confident errors) | 2 |
| Abstained (passed to the LLM) | 62 |
| LLM-only accuracy on those same 43 questions | 41 / 43 (95.3%) |

## 3. Paired comparisons (same questions; exact McNemar test)

| A vs B | A only correct | B only correct | Both | Neither | p |
|---|---|---|---|---|---|
| hybrid vs llm | 2 | 3 | 139 | 6 | 1.000 |
| llm vs plain | 57 | 3 | 85 | 5 | 0.000 |
| hybrid vs plain | 56 | 3 | 85 | 6 | 0.000 |

## 4. Response time (SQL generation; median / mean / 90th percentile)

| System | All questions | Questions it answered without the LLM |
|---|---|---|
| Rule-based only | 0 ms / 0 ms / 0 ms | 0 ms / 0 ms / 0 ms |
| LLM, plain prompt (baseline) | 0.74 s / 0.91 s / 1.55 s | — |
| LLM, engineered prompt | 0.81 s / 1.13 s / 1.24 s | — |
| Hybrid (rules, then LLM) — deployed | 0.74 s / 0.87 s / 0.96 s | 0 ms / 0 ms / 0 ms |

Hybrid answered **43 of 150** questions (28.7%) with no LLM call (mean 0 ms) and sent 107 to the LLM (mean 1.22 s), so the average hybrid response was 0.87 s versus 1.13 s for the engineered LLM alone.

## 5. Accuracy by question type

| Category | n | Rules | LLM plain | LLM engineered | Hybrid |
|---|---|---|---|---|---|
| count | 12 | 75.0% | 33.3% | 100.0% | 100.0% |
| scalar_agg | 12 | 66.7% | 41.7% | 91.7% | 91.7% |
| group_by | 12 | 41.7% | 66.7% | 100.0% | 91.7% |
| top_n | 10 | 60.0% | 30.0% | 100.0% | 100.0% |
| superlative | 10 | 70.0% | 80.0% | 80.0% | 90.0% |
| multi_filter | 8 | 62.5% | 12.5% | 87.5% | 87.5% |
| spec_filter | 6 | 16.7% | 50.0% | 83.3% | 83.3% |
| temporal | 10 | 0.0% | 70.0% | 90.0% | 90.0% |
| compound | 10 | 0.0% | 80.0% | 100.0% | 100.0% |
| hinglish | 15 | 0.0% | 40.0% | 100.0% | 93.3% |
| single_table | 10 | 0.0% | 90.0% | 100.0% | 100.0% |
| join2 | 10 | 0.0% | 80.0% | 100.0% | 100.0% |
| join2_products | 8 | 0.0% | 62.5% | 100.0% | 100.0% |
| join3 | 8 | 0.0% | 100.0% | 100.0% | 100.0% |
| merge | 4 | 0.0% | 100.0% | 100.0% | 100.0% |
| temporal_join | 5 | 0.0% | 20.0% | 60.0% | 60.0% |

## 6. Hybrid failures (9) — for error analysis

**S18** (scalar_agg, wrong result) — What is the highest price of any Dell product?
- gold: `SELECT MAX(price) FROM sales WHERE brand='Dell'`
- hybrid [rule]: `SELECT product, SUM(price) AS sum_price FROM sales WHERE LOWER(brand) = 'dell' GROUP BY product ORDER BY sum_price DESC LIMIT 1`

**S36** (group_by, wrong result) — total quantity sold by region and product
- gold: `SELECT region, product, SUM(quantity_sold) FROM sales GROUP BY region, product`
- hybrid [rule]: `SELECT region, SUM(quantity_sold) AS sum_quantity_sold FROM sales GROUP BY region ORDER BY sum_quantity_sold DESC`

**S52** (superlative, wrong result) — Which sells more units, laptops or phones?
- gold: `SELECT product FROM sales GROUP BY product ORDER BY SUM(quantity_sold) DESC LIMIT 1`
- hybrid [ollama]: `SELECT product, SUM(quantity_sold) AS total_sold FROM sales WHERE LOWER(product) IN ('laptop', 'mobile phone') GROUP BY product`

**S58** (multi_filter, wrong result) — How many Apple laptops with a 512GB ssd are in the south region?
- gold: `SELECT COUNT(*) FROM sales WHERE brand='Apple' AND product='Laptop' AND ssd='512GB' AND region='South'`
- hybrid [ollama]: `SELECT SUM(quantity_sold) FROM sales WHERE LOWER(product) = 'laptop' AND LOWER(brand) = 'apple' AND LOWER(region) = 'south' AND LOWER(rom) = '512gb'`

**S67** (spec_filter, wrong result) — total quantity sold of phones with an Apple A-Series processor
- gold: `SELECT SUM(quantity_sold) FROM sales WHERE product='Mobile Phone' AND processor_spec='Apple A-Series'`
- hybrid [ollama]: `SELECT SUM(quantity_sold) FROM sales WHERE LOWER(product) = 'mobile phone' AND LOWER(brand) = 'apple'`

**S75** (temporal, wrong result) — How many laptop sales records were dispatched after 1 January 2025?
- gold: `SELECT COUNT(*) FROM sales WHERE product='Laptop' AND dispatch_date >= '2025-01-01'`
- hybrid [ollama]: `SELECT COUNT(*) AS count FROM sales WHERE LOWER(product) = 'laptop' AND dispatch_date > '2025-01-01'`

**H01** (hinglish, wrong result) — west region mein kitne laptops hain
- gold: `SELECT COUNT(*) FROM sales WHERE product='Laptop' AND region='West'`
- hybrid [ollama]: `SELECT SUM(quantity_sold) FROM sales WHERE LOWER(product) = 'laptop' AND LOWER(region) = 'west'`

**M41** (temporal_join, wrong result) — How many orders were placed in each month of 2024?
- gold: `SELECT strftime('%Y-%m', order_date), COUNT(*) FROM orders WHERE order_date >= '2024-01-01' AND order_date < '2025-01-01' GROUP BY 1`
- hybrid [ollama]: `SELECT strftime('%m', "orders".order_date) AS order_month, COUNT("orders".order_id) AS order_count FROM "orders" WHERE "orders".order_date LIKE '2024%' GROUP BY order_month ORDER BY order_month`

**M42** (temporal_join, wrong result) — Which month of 2024 had the highest revenue?
- gold: `SELECT strftime('%Y-%m', o.order_date) AS m FROM orders o JOIN products p ON o.product_id = p.id WHERE o.order_date >= '2024-01-01' AND o.order_date < '2025-01-01' GROUP BY m ORDER BY SUM(o.quantity * p.price) DESC LIMIT 1`
- hybrid [ollama]: `SELECT strftime('%m', "orders".order_date) AS order_month, SUM("orders".quantity * products.price) AS total_revenue FROM "orders" JOIN products ON "orders".product_id = products.id WHERE "orders".order_date LIKE '2024%' GROUP BY order_month ORDER BY total_revenue DESC LIMIT 1`
