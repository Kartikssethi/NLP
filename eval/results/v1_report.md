# Evaluation results — v1

Model: `gemma4:31b-cloud` · 150 questions · gold SQL executed on the same database.

## 1. Execution accuracy (answer-containing match), 95% Wilson interval

| System | All questions (n=150) | Sales (English) (n=90) | Sales (Hinglish) (n=15) | Multi-table (uploaded files) (n=45) |
|---|---|---|---|---|
| Rule-based only | 30.0% [23–38] | 47.8% [38–58] | 13.3% [4–38] | 0.0% [0–8] |
| LLM, plain prompt (baseline) | 59.3% [51–67] | 52.2% [42–62] | 40.0% [20–64] | 80.0% [66–89] |
| LLM, engineered prompt | 79.3% [72–85] | 93.3% [86–97] | 100.0% [80–100] | 44.4% [31–59] |
| Hybrid (rules, then LLM) — deployed | 54.7% [47–62] | 57.8% [47–67] | 66.7% [42–85] | 44.4% [31–59] |

Strict match (identical table, same column order) and valid-SQL rate, all questions:

| System | Strict EX | Lenient EX | Valid SQL | No SQL produced |
|---|---|---|---|---|
| Rule-based only | 23.3% | 30.0% | 57.3% | 42.7% |
| LLM, plain prompt (baseline) | 59.3% | 59.3% | 100.0% | 0.0% |
| LLM, engineered prompt | 70.0% | 79.3% | 100.0% | 0.0% |
| Hybrid (rules, then LLM) — deployed | 43.3% | 54.7% | 99.3% | 0.0% |

## 2. What the rule engine handles on its own

The rules only know the `sales` schema, so they apply to 105 of 150 questions (the 45 multi-table questions always go to the LLM).

| Measure | Value |
|---|---|
| Questions the rules answered (coverage) | 86 / 105 (81.9%) |
| Correct when they answered (precision) | 45 / 86 (52.3% [42–63]) |
| Answered but wrong (confident errors) | 41 |
| Abstained (passed to the LLM) | 19 |
| LLM-only accuracy on those same 86 questions | 81 / 86 (94.2%) |

## 3. Paired comparisons (same questions; exact McNemar test)

| A vs B | A only correct | B only correct | Both | Neither | p |
|---|---|---|---|---|---|
| hybrid vs llm | 2 | 39 | 80 | 29 | 0.000 |
| llm vs plain | 51 | 21 | 68 | 10 | 0.001 |
| hybrid vs plain | 34 | 41 | 48 | 27 | 0.489 |

## 4. Response time (SQL generation; median / mean / 90th percentile)

| System | All questions | Questions it answered without the LLM |
|---|---|---|
| Rule-based only | 0 ms / 0 ms / 0 ms | 0 ms / 0 ms / 0 ms |
| LLM, plain prompt (baseline) | 0.79 s / 1.57 s / 1.50 s | — |
| LLM, engineered prompt | 0.77 s / 0.92 s / 1.21 s | — |
| Hybrid (rules, then LLM) — deployed | 0 ms / 423 ms / 1120 ms | 0 ms / 0 ms / 0 ms |

Hybrid answered **86 of 150** questions (57.3%) with no LLM call (mean 0 ms) and sent 64 to the LLM (mean 0.99 s), so the average hybrid response was 0.42 s versus 0.92 s for the engineered LLM alone.

## 5. Accuracy by question type

| Category | n | Rules | LLM plain | LLM engineered | Hybrid |
|---|---|---|---|---|---|
| count | 12 | 83.3% | 33.3% | 100.0% | 91.7% |
| scalar_agg | 12 | 83.3% | 41.7% | 91.7% | 83.3% |
| group_by | 12 | 50.0% | 66.7% | 100.0% | 66.7% |
| top_n | 10 | 20.0% | 30.0% | 100.0% | 20.0% |
| superlative | 10 | 80.0% | 80.0% | 80.0% | 90.0% |
| multi_filter | 8 | 62.5% | 12.5% | 87.5% | 62.5% |
| spec_filter | 6 | 16.7% | 50.0% | 83.3% | 33.3% |
| temporal | 10 | 0.0% | 70.0% | 90.0% | 0.0% |
| compound | 10 | 10.0% | 80.0% | 100.0% | 50.0% |
| hinglish | 15 | 13.3% | 40.0% | 100.0% | 66.7% |
| single_table | 10 | 0.0% | 90.0% | 80.0% | 80.0% |
| join2 | 10 | 0.0% | 80.0% | 40.0% | 40.0% |
| join2_products | 8 | 0.0% | 75.0% | 25.0% | 25.0% |
| join3 | 8 | 0.0% | 100.0% | 12.5% | 12.5% |
| merge | 4 | 0.0% | 100.0% | 100.0% | 100.0% |
| temporal_join | 5 | 0.0% | 20.0% | 20.0% | 20.0% |

## 6. Hybrid failures (68) — for error analysis

**S10** (count, wrong result) — How many laptops have an i7 processor?
- gold: `SELECT COUNT(*) FROM sales WHERE product='Laptop' AND core_spec='i7'`
- hybrid [rule]: `SELECT COUNT(*) AS count FROM sales WHERE LOWER(product) = 'laptop'`

**S18** (scalar_agg, wrong result) — What is the highest price of any Dell product?
- gold: `SELECT MAX(price) FROM sales WHERE brand='Dell'`
- hybrid [rule]: `SELECT product, SUM(price) AS sum_price FROM sales WHERE LOWER(brand) = 'dell' GROUP BY product ORDER BY sum_price DESC LIMIT 1`

**S22** (scalar_agg, wrong result) — How many units did Lenovo sell in the east region?
- gold: `SELECT SUM(quantity_sold) FROM sales WHERE brand='Lenovo' AND region='East'`
- hybrid [rule]: `SELECT COUNT(*) AS count FROM sales WHERE LOWER(brand) = 'lenovo' AND LOWER(region) = 'east'`

**S29** (group_by, wrong result) — show total quantity sold per brand for laptops
- gold: `SELECT brand, SUM(quantity_sold) FROM sales WHERE product='Laptop' GROUP BY brand`
- hybrid [rule]: `SELECT SUM(quantity_sold) AS total_quantity_sold FROM sales WHERE LOWER(product) = 'laptop'`

**S31** (group_by, wrong result) — total units sold per brand in the west region
- gold: `SELECT brand, SUM(quantity_sold) FROM sales WHERE region='West' GROUP BY brand`
- hybrid [rule]: `SELECT SUM(quantity_sold) AS total_quantity_sold FROM sales WHERE LOWER(region) = 'west'`

**S34** (group_by, wrong result) — What is the total quantity sold for each RAM size?
- gold: `SELECT ram, SUM(quantity_sold) FROM sales GROUP BY ram`
- hybrid [rule]: `SELECT SUM(quantity_sold) AS total_quantity_sold FROM sales`

**S36** (group_by, wrong result) — total quantity sold by region and product
- gold: `SELECT region, product, SUM(quantity_sold) FROM sales GROUP BY region, product`
- hybrid [rule]: `SELECT region, SUM(quantity_sold) AS sum_quantity_sold FROM sales GROUP BY region ORDER BY sum_quantity_sold DESC`

**S38** (top_n, wrong result) — top three regions by total quantity sold
- gold: `SELECT region, SUM(quantity_sold) AS t FROM sales GROUP BY region ORDER BY t DESC LIMIT 3`
- hybrid [rule]: `SELECT region, SUM(quantity_sold) AS sum_quantity_sold FROM sales GROUP BY region ORDER BY sum_quantity_sold DESC LIMIT 1`

**S39** (top_n, wrong result) — What are the prices of the 3 most expensive laptops?
- gold: `SELECT price FROM sales WHERE product='Laptop' ORDER BY price DESC LIMIT 3`
- hybrid [rule]: `SELECT * FROM sales WHERE LOWER(product) = 'laptop' ORDER BY price DESC LIMIT 1`

**S40** (top_n, wrong result) — top 10 customers by total quantity bought
- gold: `SELECT customer_name, SUM(quantity_sold) AS t FROM sales GROUP BY customer_name ORDER BY t DESC LIMIT 10`
- hybrid [rule]: `SELECT customer_name, SUM(quantity_sold) AS sum_quantity_sold FROM sales GROUP BY customer_name ORDER BY sum_quantity_sold DESC LIMIT 1`

**S41** (top_n, wrong result) — top 3 brands by average price
- gold: `SELECT brand, AVG(price) AS a FROM sales GROUP BY brand ORDER BY a DESC LIMIT 3`
- hybrid [rule]: `SELECT brand, AVG(price) AS avg_price FROM sales GROUP BY brand ORDER BY avg_price DESC LIMIT 1`

**S42** (top_n, wrong result) — Which 5 brands have the lowest total quantity sold?
- gold: `SELECT brand, SUM(quantity_sold) AS t FROM sales GROUP BY brand ORDER BY t ASC LIMIT 5`
- hybrid [rule]: `SELECT brand, SUM(quantity_sold) AS sum_quantity_sold FROM sales GROUP BY brand ORDER BY sum_quantity_sold ASC LIMIT 1`

**S43** (top_n, wrong result) — top 4 brands by number of laptop sales records
- gold: `SELECT brand, COUNT(*) AS c FROM sales WHERE product='Laptop' GROUP BY brand ORDER BY c DESC LIMIT 4`
- hybrid [rule]: `SELECT brand, COUNT(*) AS count FROM sales WHERE LOWER(product) = 'laptop' GROUP BY brand ORDER BY count DESC LIMIT 1`

**S44** (top_n, wrong result) — top 5 phone brands by quantity sold
- gold: `SELECT brand, SUM(quantity_sold) AS t FROM sales WHERE product='Mobile Phone' GROUP BY brand ORDER BY t DESC LIMIT 5`
- hybrid [rule]: `SELECT * FROM sales WHERE LOWER(product) = 'mobile phone' ORDER BY quantity_sold DESC LIMIT 5`

**S46** (top_n, wrong result) — show the prices of the 3 cheapest phones
- gold: `SELECT price FROM sales WHERE product='Mobile Phone' ORDER BY price ASC LIMIT 3`
- hybrid [rule]: `SELECT * FROM sales WHERE LOWER(product) = 'mobile phone' ORDER BY price ASC LIMIT 1`

**S52** (superlative, wrong result) — Which sells more units, laptops or phones?
- gold: `SELECT product FROM sales GROUP BY product ORDER BY SUM(quantity_sold) DESC LIMIT 1`
- hybrid [ollama]: `SELECT product, SUM(quantity_sold) AS total_sold FROM sales WHERE LOWER(product) = 'laptop' OR LOWER(product) = 'mobile phone' GROUP BY product`

**S58** (multi_filter, wrong result) — How many Apple laptops with a 512GB ssd are in the south region?
- gold: `SELECT COUNT(*) FROM sales WHERE brand='Apple' AND product='Laptop' AND ssd='512GB' AND region='South'`
- hybrid [rule]: `SELECT COUNT(*) AS count FROM sales WHERE LOWER(product) = 'laptop' AND LOWER(brand) = 'apple' AND LOWER(region) = 'south' AND LOWER(rom) = '512gb'`

**S59** (multi_filter, wrong result) — total quantity sold of Dell laptops with an i7 in the north region
- gold: `SELECT SUM(quantity_sold) FROM sales WHERE brand='Dell' AND product='Laptop' AND core_spec='i7' AND region='North'`
- hybrid [rule]: `SELECT SUM(quantity_sold) AS total_quantity_sold FROM sales WHERE LOWER(product) = 'laptop' AND LOWER(brand) = 'dell' AND LOWER(region) = 'north'`

**S63** (multi_filter, wrong result) — average price of Asus laptops with a Ryzen 7
- gold: `SELECT AVG(price) FROM sales WHERE brand='Asus' AND product='Laptop' AND core_spec='Ryzen 7'`
- hybrid [rule]: `SELECT AVG(price) AS average_price FROM sales WHERE LOWER(product) = 'laptop' AND LOWER(brand) = 'asus'`

**S66** (spec_filter, wrong result) — How many phones have a Snapdragon 8 Gen processor?
- gold: `SELECT COUNT(*) FROM sales WHERE product='Mobile Phone' AND processor_spec='Snapdragon 8 Gen'`
- hybrid [rule]: `SELECT COUNT(*) AS count FROM sales WHERE LOWER(product) = 'mobile phone'`

**S67** (spec_filter, wrong result) — total quantity sold of phones with an Apple A-Series processor
- gold: `SELECT SUM(quantity_sold) FROM sales WHERE product='Mobile Phone' AND processor_spec='Apple A-Series'`
- hybrid [rule]: `SELECT SUM(quantity_sold) AS total_quantity_sold FROM sales WHERE LOWER(product) = 'mobile phone' AND LOWER(brand) = 'apple'`

**S68** (spec_filter, wrong result) — average price by RAM size for laptops
- gold: `SELECT ram, AVG(price) FROM sales WHERE product='Laptop' GROUP BY ram`
- hybrid [rule]: `SELECT AVG(price) AS average_price FROM sales WHERE LOWER(product) = 'laptop'`

**S69** (spec_filter, wrong result) — How many laptops use a Ryzen 5?
- gold: `SELECT COUNT(*) FROM sales WHERE product='Laptop' AND core_spec='Ryzen 5'`
- hybrid [rule]: `SELECT COUNT(*) AS count FROM sales WHERE LOWER(product) = 'laptop'`

**S71** (temporal, wrong result) — How many units were dispatched in 2024?
- gold: `SELECT SUM(quantity_sold) FROM sales WHERE dispatch_date >= '2024-01-01' AND dispatch_date < '2025-01-01'`
- hybrid [rule]: `SELECT COUNT(*) AS count FROM sales`

**S72** (temporal, wrong result) — What is the total quantity sold per year, by dispatch date?
- gold: `SELECT strftime('%Y', dispatch_date), SUM(quantity_sold) FROM sales GROUP BY 1`
- hybrid [rule]: `SELECT SUM(quantity_sold) AS total_quantity_sold FROM sales`

**S73** (temporal, wrong result) — Show the total quantity sold per month by dispatch date
- gold: `SELECT strftime('%Y-%m', dispatch_date), SUM(quantity_sold) FROM sales GROUP BY 1`
- hybrid [rule]: `SELECT SUM(quantity_sold) AS total_quantity_sold FROM sales`

**S74** (temporal, wrong result) — How many sales records were received (inward) in 2023?
- gold: `SELECT COUNT(*) FROM sales WHERE inward_date >= '2023-01-01' AND inward_date < '2024-01-01'`
- hybrid [rule]: `SELECT COUNT(*) AS count FROM sales`

**S75** (temporal, wrong result) — How many laptop sales records were dispatched after 1 January 2025?
- gold: `SELECT COUNT(*) FROM sales WHERE product='Laptop' AND dispatch_date >= '2025-01-01'`
- hybrid [rule]: `SELECT COUNT(*) AS count FROM sales WHERE LOWER(product) = 'laptop'`

**S76** (temporal, wrong result) — average price of phones dispatched in 2024
- gold: `SELECT AVG(price) FROM sales WHERE product='Mobile Phone' AND dispatch_date >= '2024-01-01' AND dispatch_date < '2025-01-01'`
- hybrid [rule]: `SELECT AVG(price) AS average_price FROM sales WHERE LOWER(product) = 'mobile phone'`

**S77** (temporal, wrong result) — total units dispatched in the first half of 2024
- gold: `SELECT SUM(quantity_sold) FROM sales WHERE dispatch_date >= '2024-01-01' AND dispatch_date < '2024-07-01'`
- hybrid [rule]: `SELECT SUM(quantity_sold) AS total_quantity_sold FROM sales`

**S78** (temporal, wrong result) — Which month of 2024 had the highest quantity dispatched?
- gold: `SELECT strftime('%Y-%m', dispatch_date) AS m FROM sales WHERE dispatch_date >= '2024-01-01' AND dispatch_date < '2025-01-01' GROUP BY m ORDER BY SUM(quantity_sold) DESC LIMIT 1`
- hybrid [rule]: `SELECT * FROM sales ORDER BY quantity_sold DESC LIMIT 1`

**S79** (temporal, wrong result) — How many sales records were dispatched in March 2024?
- gold: `SELECT COUNT(*) FROM sales WHERE dispatch_date >= '2024-03-01' AND dispatch_date < '2024-04-01'`
- hybrid [rule]: `SELECT COUNT(*) AS count FROM sales`

**S80** (temporal, wrong result) — On average, how many days pass between inward and dispatch?
- gold: `SELECT AVG(julianday(dispatch_date) - julianday(inward_date)) FROM sales`
- hybrid [rule]: `SELECT COUNT(*) AS count FROM sales`

**S81** (compound, wrong result) — Which brands have an average price above 104300?
- gold: `SELECT brand FROM sales GROUP BY brand HAVING AVG(price) > 104300`
- hybrid [rule]: `SELECT AVG(price) AS average_price FROM sales`

**S84** (compound, wrong result) — How many distinct customers are there?
- gold: `SELECT COUNT(DISTINCT customer_name) FROM sales`
- hybrid [rule]: `SELECT COUNT(*) AS count FROM sales`

**S85** (compound, wrong result) — average quantity sold per record for laptops versus phones
- gold: `SELECT product, AVG(quantity_sold) FROM sales GROUP BY product`
- hybrid [rule]: `SELECT AVG(quantity_sold) AS average_quantity_sold FROM sales WHERE LOWER(product) = 'mobile phone'`

**S88** (compound, wrong result) — How many sales records have a quantity of 10?
- gold: `SELECT COUNT(*) FROM sales WHERE quantity_sold = 10`
- hybrid [rule]: `SELECT COUNT(*) AS count FROM sales`

**S90** (compound, wrong result) — How many customers appear in more than one sales record?
- gold: `SELECT COUNT(*) FROM (SELECT customer_name FROM sales GROUP BY customer_name HAVING COUNT(*) > 1)`
- hybrid [rule]: `SELECT COUNT(*) AS count FROM sales`

**H01** (hinglish, wrong result) — west region mein kitne laptops hain
- gold: `SELECT COUNT(*) FROM sales WHERE product='Laptop' AND region='West'`
- hybrid [ollama]: `SELECT region, SUM(quantity_sold) FROM sales WHERE LOWER(product) = 'laptop' AND LOWER(region) = 'west' GROUP BY region`

**H03** (hinglish, wrong result) — region wise total quantity dikhao
- gold: `SELECT region, SUM(quantity_sold) FROM sales GROUP BY region`
- hybrid [rule]: `SELECT SUM(quantity_sold) AS total_quantity_sold FROM sales`

**H06** (hinglish, wrong result) — har brand ka average price dikhao
- gold: `SELECT brand, AVG(price) FROM sales GROUP BY brand`
- hybrid [rule]: `SELECT AVG(price) AS average_price FROM sales`

**H09** (hinglish, wrong result) — phones aur laptops ka total quantity alag alag dikhao
- gold: `SELECT product, SUM(quantity_sold) FROM sales GROUP BY product`
- hybrid [rule]: `SELECT SUM(quantity_sold) AS total_quantity_sold FROM sales WHERE LOWER(product) = 'mobile phone'`

**H15** (hinglish, wrong result) — top 3 regions batao quantity ke hisaab se
- gold: `SELECT region, SUM(quantity_sold) AS t FROM sales GROUP BY region ORDER BY t DESC LIMIT 3`
- hybrid [rule]: `SELECT region, SUM(quantity_sold) AS sum_quantity_sold FROM sales GROUP BY region ORDER BY sum_quantity_sold DESC LIMIT 1`

**M05** (single_table, wrong result) — How many orders have been returned?
- gold: `SELECT COUNT(*) FROM orders WHERE status='returned'`
- hybrid [ollama]: `SELECT count(*) AS returned_orders_count FROM (SELECT "status" FROM "orders" UNION ALL SELECT "status" FROM "orders_archive") AS all_orders WHERE all_orders."status" = 'returned'`

**M06** (single_table, wrong result) — How many orders are there for each status?
- gold: `SELECT status, COUNT(*) FROM orders GROUP BY status`
- hybrid [ollama]: `SELECT T1.status, COUNT(*) AS order_count FROM (SELECT status FROM "orders" UNION ALL SELECT status FROM orders_archive) AS T1 GROUP BY T1.status`

**M11** (join2, wrong result) — How many orders did customers in each city place?
- gold: `SELECT c.city, COUNT(*) FROM orders o JOIN customers c ON o.customer_id = c.id GROUP BY c.city`
- hybrid [ollama]: `SELECT customers.city, COUNT(*) AS order_count FROM (SELECT customer_id FROM "orders" UNION ALL SELECT customer_id FROM orders_archive) AS all_orders JOIN customers ON all_orders.customer_id = customers.id GROUP BY customers.city`

**M12** (join2, wrong result) — Total quantity ordered by gold tier customers
- gold: `SELECT SUM(o.quantity) FROM orders o JOIN customers c ON o.customer_id = c.id WHERE c.tier='gold'`
- hybrid [ollama]: `SELECT SUM(all_orders.quantity) AS total_quantity_ordered FROM (SELECT customer_id, quantity FROM "orders" UNION ALL SELECT customer_id, quantity FROM orders_archive) AS all_orders INNER JOIN customers ON all_orders.customer_id = customers.id WHERE customers.tier = 'gold'`

**M14** (join2, wrong result) — How many orders were placed by customers of each tier?
- gold: `SELECT c.tier, COUNT(*) FROM orders o JOIN customers c ON o.customer_id = c.id GROUP BY c.tier`
- hybrid [ollama]: `SELECT customers.tier, COUNT(*) AS order_count FROM (SELECT customer_id FROM "orders" UNION ALL SELECT customer_id FROM orders_archive) AS all_orders JOIN customers ON all_orders.customer_id = customers.id GROUP BY customers.tier`

**M15** (join2, wrong result) — Which customers have placed at least 15 orders?
- gold: `SELECT c.name FROM orders o JOIN customers c ON o.customer_id = c.id GROUP BY c.id HAVING COUNT(*) >= 15`
- hybrid [ollama]: `SELECT T1.name FROM customers AS T1 JOIN (SELECT customer_id FROM "orders" UNION ALL SELECT customer_id FROM orders_archive) AS T2 ON T1.id = T2.customer_id GROUP BY T1.id HAVING COUNT(*) >= 15`

**M18** (join2, wrong result) — Average quantity per order for silver customers
- gold: `SELECT AVG(o.quantity) FROM orders o JOIN customers c ON o.customer_id = c.id WHERE c.tier='silver'`
- hybrid [ollama]: `SELECT AVG(all_orders.quantity) AS average_quantity FROM ( SELECT customer_id, quantity FROM "orders" UNION ALL SELECT customer_id, quantity FROM orders_archive ) AS all_orders JOIN customers ON all_orders.customer_id = customers.id WHERE customers.tier = 'silver'`

**M20** (join2, wrong result) — For each city, how many returned orders do its customers have?
- gold: `SELECT c.city, COUNT(*) FROM orders o JOIN customers c ON o.customer_id = c.id WHERE o.status='returned' GROUP BY c.city`
- hybrid [ollama]: `SELECT customers.city, COUNT(*) AS returned_orders_count FROM customers JOIN (SELECT customer_id, status FROM "orders" UNION ALL SELECT customer_id, status FROM orders_archive) AS all_orders ON customers.id = all_orders.customer_id WHERE all_orders.status = 'returned' GROUP BY customers.city`

**M21** (join2_products, wrong result) — Total units ordered per product category
- gold: `SELECT p.category, SUM(o.quantity) FROM orders o JOIN products p ON o.product_id = p.id GROUP BY p.category`
- hybrid [ollama]: `SELECT T2.category, SUM(T1.quantity) AS total_units_ordered FROM (SELECT quantity, product_id FROM "orders" UNION ALL SELECT quantity, product_id FROM orders_archive) AS T1 INNER JOIN products AS T2 ON T1.product_id = T2.id GROUP BY T2.category`

**M22** (join2_products, wrong result) — What is the total revenue per product category?
- gold: `SELECT p.category, SUM(o.quantity * p.price) FROM orders o JOIN products p ON o.product_id = p.id GROUP BY p.category`
- hybrid [ollama]: `SELECT T1.category, SUM(T2.quantity * T1.price) AS total_revenue FROM products AS T1 JOIN (SELECT product_id, quantity FROM "orders" UNION ALL SELECT product_id, quantity FROM orders_archive) AS T2 ON T1.id = T2.product_id GROUP BY T1.category`

**M23** (join2_products, wrong result) — Names of the top 5 products by units ordered
- gold: `SELECT p.product_name FROM orders o JOIN products p ON o.product_id = p.id GROUP BY p.id ORDER BY SUM(o.quantity) DESC LIMIT 5`
- hybrid [ollama]: `SELECT T1.product_name AS product_name, SUM(T2.quantity) AS total_units_ordered FROM products AS T1 JOIN (SELECT product_id, quantity FROM "orders" UNION ALL SELECT product_id, quantity FROM orders_archive) AS T2 ON T1.id = T2.product_id GROUP BY T1.product_name ORDER BY total_units_ordered DESC LIMIT 5`

**M25** (join2_products, wrong result) — What is the average order value (quantity times price)?
- gold: `SELECT AVG(o.quantity * p.price) FROM orders o JOIN products p ON o.product_id = p.id`
- hybrid [ollama]: `SELECT AVG(all_orders.quantity * products.price) AS average_order_value FROM (SELECT quantity, product_id FROM "orders" UNION ALL SELECT quantity, product_id FROM orders_archive) AS all_orders JOIN products ON all_orders.product_id = products.id`

**M26** (join2_products, wrong result) — How many orders were for Electronics products?
- gold: `SELECT COUNT(*) FROM orders o JOIN products p ON o.product_id = p.id WHERE p.category='Electronics'`
- hybrid [ollama]: `SELECT count(*) AS order_count FROM (SELECT product_id FROM "orders" UNION ALL SELECT product_id FROM orders_archive) AS all_orders JOIN products ON all_orders.product_id = products.id WHERE products.category = 'Electronics'`

**M27** (join2_products, wrong result) — Total revenue from delivered orders
- gold: `SELECT SUM(o.quantity * p.price) FROM orders o JOIN products p ON o.product_id = p.id WHERE o.status='delivered'`
- hybrid [ollama]: `SELECT SUM(all_orders.quantity * products.price) AS total_revenue FROM ( SELECT "orders".product_id, "orders".quantity, "orders".status FROM "orders" UNION ALL SELECT orders_archive.product_id, orders_archive.quantity, orders_archive.status FROM orders_archive ) AS all_orders JOIN products ON all_orders.product_id = products.id WHERE all_orders.status = 'delivered'`

**M29** (join3, wrong result) — Total revenue per customer city
- gold: `SELECT c.city, SUM(o.quantity * p.price) FROM orders o JOIN customers c ON o.customer_id = c.id JOIN products p ON o.product_id = p.id GROUP BY c.city`
- hybrid [ollama]: `SELECT customers.city, SUM(all_orders.quantity * products.price) AS total_revenue FROM (SELECT product_id, customer_id, quantity FROM "orders" UNION ALL SELECT product_id, customer_id, quantity FROM orders_archive) AS all_orders JOIN customers ON all_orders.customer_id = customers.id JOIN products ON all_orders.product_id = products.id GROUP BY customers.city`

**M30** (join3, wrong result) — Revenue by customer tier and product category
- gold: `SELECT c.tier, p.category, SUM(o.quantity * p.price) FROM orders o JOIN customers c ON o.customer_id = c.id JOIN products p ON o.product_id = p.id GROUP BY c.tier, p.category`
- hybrid [ollama]: `SELECT T1.tier, T2.category, SUM(T3.quantity * T2.price) AS total_revenue FROM customers AS T1 JOIN ( SELECT customer_id, product_id, quantity FROM "orders" UNION ALL SELECT customer_id, product_id, quantity FROM orders_archive ) AS T3 ON T1.id = T3.customer_id JOIN products AS T2 ON T3.product_id = T2.id GROUP BY T1.tier, T2.category`

**M31** (join3, wrong result) — Top 3 cities by revenue
- gold: `SELECT c.city FROM orders o JOIN customers c ON o.customer_id = c.id JOIN products p ON o.product_id = p.id GROUP BY c.city ORDER BY SUM(o.quantity * p.price) DESC LIMIT 3`
- hybrid [ollama]: `SELECT T1.city, SUM(T2.quantity * T3.price) AS total_revenue FROM customers AS T1 JOIN (SELECT customer_id, product_id, quantity FROM "orders" UNION ALL SELECT customer_id, product_id, quantity FROM orders_archive) AS T2 ON T1.id = T2.customer_id JOIN products AS T3 ON T2.product_id = T3.id GROUP BY T1.city ORDER BY total_revenue DESC LIMIT 3`

**M32** (join3, no valid SQL) — Which gold customer spent the most?
- gold: `SELECT c.name FROM orders o JOIN customers c ON o.customer_id = c.id JOIN products p ON o.product_id = p.id WHERE c.tier='gold' GROUP BY c.id ORDER BY SUM(o.quantity * p.price) DESC LIMIT 1`
- hybrid [ollama]: `SELECT T1.name, SUM(T3.quantity * T2.price) AS total_spent FROM customers AS T1 JOIN products AS T2 ON (T2.id = T2.id) -- This is a placeholder, corrected below JOIN ( SELECT customer_id, product_id, quantity FROM "orders" UNION ALL SELECT customer_id, product_id, quantity FROM orders_archive ) AS T3 ON T1.id = T3.customer_id JOIN products AS P ON T3.product_id = P.id WHERE T1.tier = 'gold' GROUP BY T1.id ORDER BY total_spent DESC LIMIT 1; -- Correcting the join logic for the final output: SELECT T1.name, SUM(T3.quantity * P.price) AS total_spent FROM customers AS T1 JOIN ( SELECT customer_id, product_id, quantity FROM "orders" UNION ALL SELECT customer_id, product_id, quantity FROM orders_archive ) AS T3 ON T1.id = T3.customer_id JOIN products AS P ON T3.product_id = P.id WHERE T1.tier = 'gold' GROUP BY T1.id, T1.name ORDER BY total_spent DESC LIMIT 1`  — error: exec: You can only execute one statement at a time.

**M33** (join3, wrong result) — How much did customers from Delhi spend on Electronics?
- gold: `SELECT SUM(o.quantity * p.price) FROM orders o JOIN customers c ON o.customer_id = c.id JOIN products p ON o.product_id = p.id WHERE c.city='Delhi' AND p.category='Electronics'`
- hybrid [ollama]: `SELECT SUM(all_orders.quantity * products.price) AS total_spend FROM ( SELECT customer_id, product_id, quantity FROM "orders" UNION ALL SELECT customer_id, product_id, quantity FROM orders_archive ) AS all_orders JOIN customers ON all_orders.customer_id = customers.id JOIN products ON all_orders.product_id = products.id WHERE customers.city = 'Delhi' AND products.category = 'Electronics'`

**M34** (join3, wrong result) — Average revenue per order for each customer tier
- gold: `SELECT c.tier, AVG(o.quantity * p.price) FROM orders o JOIN customers c ON o.customer_id = c.id JOIN products p ON o.product_id = p.id GROUP BY c.tier`
- hybrid [ollama]: `SELECT T1.tier, AVG(T2.total_order_value) AS avg_revenue_per_order FROM customers AS T1 JOIN ( SELECT o.order_id, o.customer_id, SUM(o.quantity * p.price) AS total_order_value FROM ( SELECT order_id, customer_id, product_id, quantity FROM "orders" UNION ALL SELECT order_id, customer_id, product_id, quantity FROM orders_archive ) AS o JOIN products AS p ON o.product_id = p.id GROUP BY o.order_id, o.customer_id ) AS T2 ON T1.id = T2.customer_id GROUP BY T1.tier`

**M36** (join3, wrong result) — How many different products have customers from Pune bought?
- gold: `SELECT COUNT(DISTINCT o.product_id) FROM orders o JOIN customers c ON o.customer_id = c.id WHERE c.city='Pune'`
- hybrid [ollama]: `SELECT COUNT(DISTINCT all_orders.product_id) AS unique_products_bought FROM ( SELECT product_id, customer_id FROM "orders" UNION ALL SELECT product_id, customer_id FROM orders_archive ) AS all_orders JOIN customers ON all_orders.customer_id = customers.id WHERE customers.city = 'Pune'`

**M41** (temporal_join, wrong result) — How many orders were placed in each month of 2024?
- gold: `SELECT strftime('%Y-%m', order_date), COUNT(*) FROM orders WHERE order_date >= '2024-01-01' AND order_date < '2025-01-01' GROUP BY 1`
- hybrid [ollama]: `SELECT strftime('%m', all_orders.order_date) AS order_month, COUNT(*) AS order_count FROM (SELECT order_date FROM "orders" UNION ALL SELECT order_date FROM orders_archive) AS all_orders WHERE all_orders.order_date LIKE '2024%' GROUP BY order_month ORDER BY order_month`

**M42** (temporal_join, wrong result) — Which month of 2024 had the highest revenue?
- gold: `SELECT strftime('%Y-%m', o.order_date) AS m FROM orders o JOIN products p ON o.product_id = p.id WHERE o.order_date >= '2024-01-01' AND o.order_date < '2025-01-01' GROUP BY m ORDER BY SUM(o.quantity * p.price) DESC LIMIT 1`
- hybrid [ollama]: `SELECT strftime('%m', all_orders.order_date) AS order_month, SUM(all_orders.quantity * products.price) AS total_revenue FROM (SELECT product_id, quantity, order_date FROM "orders" UNION ALL SELECT product_id, quantity, order_date FROM orders_archive) AS all_orders JOIN products ON all_orders.product_id = products.id WHERE all_orders.order_date LIKE '2024%' GROUP BY order_month ORDER BY total_revenue DESC LIMIT 1`

**M44** (temporal_join, wrong result) — What percentage of orders were returned?
- gold: `SELECT 100.0 * SUM(status='returned') / COUNT(*) FROM orders`
- hybrid [ollama]: `SELECT CAST(SUM(CASE WHEN all_orders.status = 'returned' THEN 1 ELSE 0 END) AS FLOAT) * 100 / COUNT(*) AS percentage_returned FROM (SELECT status FROM "orders" UNION ALL SELECT status FROM orders_archive) AS all_orders`

**M45** (temporal_join, wrong result) — Revenue from returned orders for each product category
- gold: `SELECT p.category, SUM(o.quantity * p.price) FROM orders o JOIN products p ON o.product_id = p.id WHERE o.status='returned' GROUP BY p.category`
- hybrid [ollama]: `SELECT T1.category, SUM(T2.quantity * T1.price) AS returned_revenue FROM products AS T1 JOIN (SELECT product_id, quantity FROM "orders" WHERE status = 'returned' UNION ALL SELECT product_id, quantity FROM orders_archive WHERE status = 'returned') AS T2 ON T1.id = T2.product_id GROUP BY T1.category`
