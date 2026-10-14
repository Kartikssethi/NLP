# Evaluation results — heldout_v1

Model: `gemma4:31b-cloud` · 40 questions · gold SQL executed on the same database.

## 1. Execution accuracy (answer-containing match), 95% Wilson interval

| System | All questions (n=40) | Sales (English) (n=20) | Multi-table (uploaded files) (n=20) |
|---|---|---|---|
| Rule-based only | 12.5% [5–26] | 25.0% [11–47] | 0.0% [0–16] |
| LLM, plain prompt (baseline) | 65.0% [50–78] | 45.0% [26–66] | 85.0% [64–95] |
| LLM, engineered prompt | 75.0% [60–86] | 95.0% [76–99] | 55.0% [34–74] |
| Hybrid (rules, then LLM) — deployed | 57.5% [42–71] | 60.0% [39–78] | 55.0% [34–74] |

Strict match (identical table, same column order) and valid-SQL rate, all questions:

| System | Strict EX | Lenient EX | Valid SQL | No SQL produced |
|---|---|---|---|---|
| Rule-based only | 7.5% | 12.5% | 32.5% | 67.5% |
| LLM, plain prompt (baseline) | 65.0% | 65.0% | 100.0% | 0.0% |
| LLM, engineered prompt | 67.5% | 75.0% | 100.0% | 0.0% |
| Hybrid (rules, then LLM) — deployed | 47.5% | 57.5% | 100.0% | 0.0% |

## 2. What the rule engine handles on its own

The rules only know the `sales` schema, so they apply to 20 of 40 questions (the 20 multi-table questions always go to the LLM).

| Measure | Value |
|---|---|
| Questions the rules answered (coverage) | 13 / 20 (65.0%) |
| Correct when they answered (precision) | 5 / 13 (38.5% [18–64]) |
| Answered but wrong (confident errors) | 8 |
| Abstained (passed to the LLM) | 7 |
| LLM-only accuracy on those same 13 questions | 12 / 13 (92.3%) |

## 3. Paired comparisons (same questions; exact McNemar test)

| A vs B | A only correct | B only correct | Both | Neither | p |
|---|---|---|---|---|---|
| hybrid vs llm | 1 | 8 | 22 | 9 | 0.039 |
| llm vs plain | 10 | 6 | 20 | 4 | 0.454 |
| hybrid vs plain | 6 | 9 | 17 | 8 | 0.607 |

## 4. Response time (SQL generation; median / mean / 90th percentile)

| System | All questions | Questions it answered without the LLM |
|---|---|---|
| Rule-based only | 0 ms / 0 ms / 0 ms | 0 ms / 0 ms / 0 ms |
| LLM, plain prompt (baseline) | 0.90 s / 0.96 s / 1.24 s | — |
| LLM, engineered prompt | 0.87 s / 1.08 s / 1.23 s | — |
| Hybrid (rules, then LLM) — deployed | 0.68 s / 0.55 s / 0.92 s | 0 ms / 0 ms / 0 ms |

Hybrid answered **13 of 40** questions (32.5%) with no LLM call (mean 0 ms) and sent 27 to the LLM (mean 0.82 s), so the average hybrid response was 0.55 s versus 1.08 s for the engineered LLM alone.

## 5. Accuracy by question type

| Category | n | Rules | LLM plain | LLM engineered | Hybrid |
|---|---|---|---|---|---|
| count | 2 | 50.0% | 50.0% | 100.0% | 100.0% |
| scalar_agg | 1 | 100.0% | 0.0% | 100.0% | 100.0% |
| group_by | 4 | 25.0% | 25.0% | 100.0% | 50.0% |
| top_n | 1 | 0.0% | 0.0% | 100.0% | 0.0% |
| filter_cmp | 2 | 0.0% | 0.0% | 100.0% | 0.0% |
| multi_value | 1 | 0.0% | 100.0% | 100.0% | 100.0% |
| superlative | 2 | 50.0% | 50.0% | 50.0% | 100.0% |
| exclusion | 1 | 0.0% | 0.0% | 100.0% | 0.0% |
| temporal | 1 | 0.0% | 100.0% | 100.0% | 0.0% |
| compound | 5 | 20.0% | 80.0% | 100.0% | 80.0% |
| single_table | 6 | 0.0% | 83.3% | 83.3% | 83.3% |
| join2 | 6 | 0.0% | 83.3% | 33.3% | 33.3% |
| join3 | 2 | 0.0% | 100.0% | 50.0% | 50.0% |
| join2_products | 4 | 0.0% | 75.0% | 25.0% | 25.0% |
| merge | 2 | 0.0% | 100.0% | 100.0% | 100.0% |

## 6. Hybrid failures (17) — for error analysis

**T04** (top_n, wrong result) — Which three brands have the highest average price?
- gold: `SELECT brand, AVG(price) AS a FROM sales GROUP BY brand ORDER BY a DESC LIMIT 3`
- hybrid [rule]: `SELECT brand, AVG(price) AS avg_price FROM sales GROUP BY brand ORDER BY avg_price DESC LIMIT 1`

**T05** (filter_cmp, wrong result) — How many laptops cost more than 150000?
- gold: `SELECT COUNT(*) FROM sales WHERE product='Laptop' AND price > 150000`
- hybrid [rule]: `SELECT COUNT(*) AS count FROM sales WHERE LOWER(product) = 'laptop'`

**T06** (filter_cmp, wrong result) — How many phones cost under 20000?
- gold: `SELECT COUNT(*) FROM sales WHERE product='Mobile Phone' AND price < 20000`
- hybrid [rule]: `SELECT COUNT(*) AS count FROM sales WHERE LOWER(product) = 'mobile phone'`

**T07** (group_by, wrong result) — total quantity sold for each product
- gold: `SELECT product, SUM(quantity_sold) FROM sales GROUP BY product`
- hybrid [rule]: `SELECT SUM(quantity_sold) AS total_quantity_sold FROM sales`

**T11** (exclusion, wrong result) — average price of laptops excluding Apple
- gold: `SELECT AVG(price) FROM sales WHERE product='Laptop' AND brand != 'Apple'`
- hybrid [rule]: `SELECT AVG(price) AS average_price FROM sales WHERE LOWER(product) = 'laptop' AND LOWER(brand) = 'apple'`

**T12** (temporal, wrong result) — How many sales records were dispatched between 2024-01-01 and 2024-03-31?
- gold: `SELECT COUNT(*) FROM sales WHERE dispatch_date >= '2024-01-01' AND dispatch_date <= '2024-03-31'`
- hybrid [rule]: `SELECT COUNT(*) AS count FROM sales`

**T14** (compound, wrong result) — How many different brands are there?
- gold: `SELECT COUNT(DISTINCT brand) FROM sales`
- hybrid [rule]: `SELECT COUNT(*) AS count FROM sales`

**T19** (group_by, wrong result) — average price by RAM size for phones
- gold: `SELECT ram, AVG(price) FROM sales WHERE product='Mobile Phone' GROUP BY ram`
- hybrid [rule]: `SELECT AVG(price) AS average_price FROM sales WHERE LOWER(product) = 'mobile phone'`

**U02** (join2, wrong result) — Total quantity ordered by bronze customers
- gold: `SELECT SUM(o.quantity) FROM orders o JOIN customers c ON o.customer_id = c.id WHERE c.tier='bronze'`
- hybrid [ollama]: `SELECT SUM(all_orders.quantity) AS total_quantity_ordered FROM (SELECT customer_id, quantity FROM "orders" UNION ALL SELECT customer_id, quantity FROM orders_archive) AS all_orders INNER JOIN customers ON all_orders.customer_id = customers.id WHERE customers.tier = 'bronze'`

**U03** (single_table, wrong result) — How many orders were cancelled?
- gold: `SELECT COUNT(*) FROM orders WHERE status='cancelled'`
- hybrid [ollama]: `SELECT count(*) AS cancelled_orders_count FROM (SELECT "status" FROM "orders" UNION ALL SELECT "status" FROM "orders_archive") AS all_orders WHERE all_orders."status" = 'cancelled'`

**U06** (join2, wrong result) — How many orders did customers from Chennai place?
- gold: `SELECT COUNT(*) FROM orders o JOIN customers c ON o.customer_id = c.id WHERE c.city='Chennai'`
- hybrid [ollama]: `SELECT count(*) AS total_orders FROM (SELECT "orders".customer_id FROM "orders" UNION ALL SELECT "orders_archive".customer_id FROM "orders_archive") AS all_orders JOIN customers ON all_orders.customer_id = customers.id WHERE customers.city = 'Chennai'`

**U09** (join2_products, wrong result) — Number of orders per product category
- gold: `SELECT p.category, COUNT(*) FROM orders o JOIN products p ON o.product_id = p.id GROUP BY p.category`
- hybrid [ollama]: `SELECT T1.category, COUNT(*) AS order_count FROM (SELECT product_id FROM "orders" UNION ALL SELECT product_id FROM orders_archive) AS T2 JOIN products AS T1 ON T2.product_id = T1.id GROUP BY T1.category`

**U10** (join2, wrong result) — How many customers placed more than 12 orders?
- gold: `SELECT COUNT(*) FROM (SELECT customer_id FROM orders GROUP BY customer_id HAVING COUNT(*) > 12)`
- hybrid [ollama]: `SELECT COUNT(*) AS customer_count FROM (SELECT customers.id FROM customers JOIN (SELECT customer_id FROM "orders" UNION ALL SELECT customer_id FROM orders_archive) AS all_orders ON customers.id = all_orders.customer_id GROUP BY customers.id HAVING COUNT(*) > 12) AS frequent_customers`

**U11** (join2_products, wrong result) — What is the total revenue for cancelled orders?
- gold: `SELECT SUM(o.quantity * p.price) FROM orders o JOIN products p ON o.product_id = p.id WHERE o.status='cancelled'`
- hybrid [ollama]: `SELECT SUM(all_orders.quantity * products.price) AS total_revenue FROM ( SELECT "orders".product_id, "orders".quantity, "orders".status FROM "orders" UNION ALL SELECT "orders_archive".product_id, "orders_archive".quantity, "orders_archive".status FROM "orders_archive" ) AS all_orders JOIN products ON all_orders.product_id = products.id WHERE all_orders.status = 'cancelled'`

**U16** (join2, wrong result) — Which cities have more than 21 returned orders?
- gold: `SELECT c.city FROM orders o JOIN customers c ON o.customer_id = c.id WHERE o.status='returned' GROUP BY c.city HAVING COUNT(*) > 21`
- hybrid [ollama]: `SELECT T1.city FROM customers AS T1 JOIN (SELECT customer_id, status FROM "orders" UNION ALL SELECT customer_id, status FROM orders_archive) AS T2 ON T1.id = T2.customer_id WHERE T2.status = 'returned' GROUP BY T1.city HAVING COUNT(*) > 21`

**U17** (join3, wrong result) — Average spend per customer who has ordered
- gold: `SELECT SUM(o.quantity * p.price) * 1.0 / COUNT(DISTINCT o.customer_id) FROM orders o JOIN products p ON o.product_id = p.id`
- hybrid [ollama]: `SELECT AVG(customer_spend.total_spent) AS average_spend_per_customer FROM ( SELECT all_orders.customer_id, SUM(all_orders.quantity * products.price) AS total_spent FROM ( SELECT customer_id, product_id, quantity FROM "orders" UNION ALL SELECT customer_id, product_id, quantity FROM orders_archive ) AS all_orders JOIN products ON all_orders.product_id = products.id GROUP BY all_orders.customer_id ) AS customer_spend`

**U18** (join2_products, wrong result) — How many orders contain products priced above 50000?
- gold: `SELECT COUNT(*) FROM orders o JOIN products p ON o.product_id = p.id WHERE p.price > 50000`
- hybrid [ollama]: `SELECT count(*) AS order_count FROM (SELECT "orders".order_id, "orders".product_id FROM "orders" UNION ALL SELECT "orders_archive".order_id, "orders_archive".product_id FROM "orders_archive") AS all_orders JOIN products ON all_orders.product_id = products.id WHERE products.price > 50000`
