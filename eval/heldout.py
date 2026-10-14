"""Held-out questions: written *before* the full error analysis of the main
benchmark, and never used to guide a change to the system. After the
defects found on the main set were fixed, these 40 unseen questions test
whether the fixes generalise (rather than just patching the questions that
exposed them). Same conventions as benchmark.py.
"""
from eval.benchmark import MULTI_TABLES, _q

SALES_HELD = [
    _q("T01", "count", "Number of Nokia phones in the south",
       "SELECT COUNT(*) FROM sales WHERE brand='Nokia' AND product='Mobile Phone' AND region='South'"),
    _q("T02", "scalar_agg", "What's the mean price for Toshiba laptops?",
       "SELECT AVG(price) FROM sales WHERE brand='Toshiba' AND product='Laptop'"),
    _q("T03", "group_by", "Give me total units by brand for the central region",
       "SELECT brand, SUM(quantity_sold) FROM sales WHERE region='Central' GROUP BY brand"),
    _q("T04", "top_n", "Which three brands have the highest average price?",
       "SELECT brand, AVG(price) AS a FROM sales GROUP BY brand ORDER BY a DESC LIMIT 3"),
    _q("T05", "filter_cmp", "How many laptops cost more than 150000?",
       "SELECT COUNT(*) FROM sales WHERE product='Laptop' AND price > 150000"),
    _q("T06", "filter_cmp", "How many phones cost under 20000?",
       "SELECT COUNT(*) FROM sales WHERE product='Mobile Phone' AND price < 20000"),
    _q("T07", "group_by", "total quantity sold for each product",
       "SELECT product, SUM(quantity_sold) FROM sales GROUP BY product"),
    _q("T08", "multi_value", "What is the combined quantity sold for Apple and Samsung?",
       "SELECT SUM(quantity_sold) FROM sales WHERE brand IN ('Apple', 'Samsung')"),
    _q("T09", "group_by", "number of laptop sales records per region",
       "SELECT region, COUNT(*) FROM sales WHERE product='Laptop' GROUP BY region"),
    _q("T10", "superlative", "Which region has the fewest sales records?",
       "SELECT region FROM sales GROUP BY region ORDER BY COUNT(*) ASC LIMIT 1"),
    _q("T11", "exclusion", "average price of laptops excluding Apple",
       "SELECT AVG(price) FROM sales WHERE product='Laptop' AND brand != 'Apple'"),
    _q("T12", "temporal", "How many sales records were dispatched between 2024-01-01 and 2024-03-31?",
       "SELECT COUNT(*) FROM sales WHERE dispatch_date >= '2024-01-01' AND dispatch_date <= '2024-03-31'"),
    _q("T13", "compound", "What is the highest total quantity sold by a single brand?",
       "SELECT MAX(t) FROM (SELECT SUM(quantity_sold) AS t FROM sales GROUP BY brand)"),
    _q("T14", "compound", "How many different brands are there?",
       "SELECT COUNT(DISTINCT brand) FROM sales"),
    _q("T15", "compound", "Which regions have more than 10000 sales records?",
       "SELECT region FROM sales GROUP BY region HAVING COUNT(*) > 10000"),
    _q("T16", "superlative", "Which phone brand has the highest average price?",
       "SELECT brand FROM sales WHERE product='Mobile Phone' GROUP BY brand ORDER BY AVG(price) DESC LIMIT 1"),
    _q("T17", "compound", "total revenue for Apple (price times quantity)",
       "SELECT SUM(price * quantity_sold) FROM sales WHERE brand='Apple'"),
    _q("T18", "compound", "What percentage of sales records are from the west region?",
       "SELECT 100.0 * SUM(region='West') / COUNT(*) FROM sales"),
    _q("T19", "group_by", "average price by RAM size for phones",
       "SELECT ram, AVG(price) FROM sales WHERE product='Mobile Phone' GROUP BY ram"),
    _q("T20", "count", "How many sales records are there in total?",
       "SELECT COUNT(*) FROM sales"),
]

MULTI_HELD = [
    _q("U01", "single_table", "How many products are in the Office category?",
       "SELECT COUNT(*) FROM products WHERE category='Office'"),
    _q("U02", "join2", "Total quantity ordered by bronze customers",
       "SELECT SUM(o.quantity) FROM orders o JOIN customers c ON o.customer_id = c.id WHERE c.tier='bronze'"),
    _q("U03", "single_table", "How many orders were cancelled?",
       "SELECT COUNT(*) FROM orders WHERE status='cancelled'"),
    _q("U04", "single_table", "Which tier has the most customers?",
       "SELECT tier FROM customers GROUP BY tier ORDER BY COUNT(*) DESC LIMIT 1"),
    _q("U05", "single_table", "Average price of Electronics products",
       "SELECT AVG(price) FROM products WHERE category='Electronics'"),
    _q("U06", "join2", "How many orders did customers from Chennai place?",
       "SELECT COUNT(*) FROM orders o JOIN customers c ON o.customer_id = c.id WHERE c.city='Chennai'"),
    _q("U07", "join3", "Total revenue from orders placed in 2025",
       "SELECT SUM(o.quantity * p.price) FROM orders o JOIN products p ON o.product_id = p.id WHERE o.order_date >= '2025-01-01'"),
    _q("U08", "single_table", "Which customers from Jaipur are gold tier?",
       "SELECT name FROM customers WHERE city='Jaipur' AND tier='gold'"),
    _q("U09", "join2_products", "Number of orders per product category",
       "SELECT p.category, COUNT(*) FROM orders o JOIN products p ON o.product_id = p.id GROUP BY p.category"),
    _q("U10", "join2", "How many customers placed more than 12 orders?",
       "SELECT COUNT(*) FROM (SELECT customer_id FROM orders GROUP BY customer_id HAVING COUNT(*) > 12)"),
    _q("U11", "join2_products", "What is the total revenue for cancelled orders?",
       "SELECT SUM(o.quantity * p.price) FROM orders o JOIN products p ON o.product_id = p.id WHERE o.status='cancelled'"),
    _q("U12", "join2_products", "Which product has been ordered the most units?",
       "SELECT p.product_name FROM orders o JOIN products p ON o.product_id = p.id GROUP BY p.id ORDER BY SUM(o.quantity) DESC LIMIT 1"),
    _q("U13", "merge", "Combine both order tables and count the orders for each status",
       "SELECT status, COUNT(*) FROM (SELECT status FROM orders UNION ALL SELECT status FROM orders_archive) GROUP BY status"),
    _q("U14", "single_table", "How many orders are in the archive?",
       "SELECT COUNT(*) FROM orders_archive"),
    _q("U15", "merge", "Total quantity ordered in 2023",
       "SELECT SUM(quantity) FROM (SELECT quantity, order_date FROM orders UNION ALL SELECT quantity, order_date FROM orders_archive) WHERE order_date >= '2023-01-01' AND order_date < '2024-01-01'"),
    _q("U16", "join2", "Which cities have more than 21 returned orders?",
       "SELECT c.city FROM orders o JOIN customers c ON o.customer_id = c.id WHERE o.status='returned' GROUP BY c.city HAVING COUNT(*) > 21"),
    _q("U17", "join3", "Average spend per customer who has ordered",
       "SELECT SUM(o.quantity * p.price) * 1.0 / COUNT(DISTINCT o.customer_id) FROM orders o JOIN products p ON o.product_id = p.id"),
    _q("U18", "join2_products", "How many orders contain products priced above 50000?",
       "SELECT COUNT(*) FROM orders o JOIN products p ON o.product_id = p.id WHERE p.price > 50000"),
    _q("U19", "join2", "For each tier, how many different customers have placed an order?",
       "SELECT c.tier, COUNT(DISTINCT o.customer_id) FROM orders o JOIN customers c ON o.customer_id = c.id GROUP BY c.tier"),
    _q("U20", "join2", "How many orders in 2024 were placed by silver customers?",
       "SELECT COUNT(*) FROM orders o JOIN customers c ON o.customer_id = c.id WHERE c.tier='silver' AND o.order_date >= '2024-01-01' AND o.order_date < '2025-01-01'"),
]


def heldout_questions() -> list[dict]:
    out = [{**item, "dataset": "sales", "tables": ["sales"]} for item in SALES_HELD]
    out += [{**item, "dataset": "multi", "tables": MULTI_TABLES} for item in MULTI_HELD]
    return out
