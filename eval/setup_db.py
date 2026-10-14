"""Build the evaluation database: the real 50k-row sales table plus a
synthetic, seeded relational dataset (customers, products, orders and an
orders_archive with the same columns) loaded through the app's own upload path.

    NLP_DB_PATH=eval/eval.db python -m eval.setup_db

Deterministic: the same seed always produces the same data, so the benchmark's
gold SQL has the same answers on every machine.
"""
import csv
import datetime as dt
import os
import random
from pathlib import Path

os.environ.setdefault("NLP_DB_PATH", "eval/eval.db")

from app.db import import_uploaded_file, load_sales_data  # noqa: E402

DATA_DIR = Path("eval/data")
SEED = 7

FIRST = ["Asha", "Ben", "Chitra", "Dev", "Esha", "Farhan", "Gita", "Harsh", "Isha", "Jay", "Kavya", "Lalit",
         "Meera", "Nikhil", "Omkar", "Priya", "Qadir", "Rahul", "Sana", "Tarun", "Uma", "Varun", "Waseem",
         "Xena", "Yash", "Zoya"]
LAST = ["Sharma", "Verma", "Iyer", "Nair", "Khan", "Patel", "Reddy", "Gupta", "Das", "Joshi", "Mehta", "Singh",
        "Kapoor", "Bose", "Rao", "Menon"]
CITIES = ["Mumbai", "Delhi", "Pune", "Bengaluru", "Chennai", "Kolkata", "Hyderabad", "Jaipur"]
# Deliberately unequal sizes so "which category has the most products" has one answer.
CATEGORIES = {"Electronics": 9, "Accessories": 7, "Home": 6, "Office": 5, "Fitness": 3}
STATUSES = ["delivered", "returned", "cancelled"]


def _date(rng: random.Random, start: dt.date, end: dt.date) -> str:
    return (start + dt.timedelta(days=rng.randint(0, (end - start).days))).isoformat()


def build() -> None:
    rng = random.Random(SEED)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    names = [f"{f} {l}" for f in FIRST for l in LAST]
    rng.shuffle(names)
    customers = []
    for i in range(1, 151):
        tier = rng.choices(["gold", "silver", "bronze"], weights=[20, 35, 45])[0]
        customers.append([i, names[i - 1], rng.choice(CITIES), tier, _date(rng, dt.date(2023, 1, 1), dt.date(2024, 12, 31))])

    products, prices = [], set()
    pid = 1
    for category, n in CATEGORIES.items():
        for k in range(n):
            price = rng.randint(200, 90000)
            while price in prices:
                price = rng.randint(200, 90000)
            prices.add(price)
            products.append([pid, f"{category} Item {k + 1}", category, price])
            pid += 1

    product_weights = [rng.random() + 0.2 for _ in products]

    def order_rows(first_id: int, n: int, start: dt.date, end: dt.date) -> list[list]:
        rows = []
        for i in range(n):
            # customers 141-150 never order, so "customers with no orders" has an answer
            rows.append([
                first_id + i,
                rng.randint(1, 140),
                rng.choices(range(1, len(products) + 1), weights=product_weights)[0],
                rng.randint(1, 5),
                _date(rng, start, end),
                rng.choices(STATUSES, weights=[80, 12, 8])[0],
            ])
        return rows

    orders = order_rows(1, 1200, dt.date(2024, 1, 1), dt.date(2025, 3, 31))
    archive = order_rows(5001, 300, dt.date(2023, 1, 1), dt.date(2023, 12, 31))

    files = {
        "customers": (["id", "name", "city", "tier", "signup_date"], customers),
        "products": (["id", "product_name", "category", "price"], products),
        "orders": (["order_id", "customer_id", "product_id", "quantity", "order_date", "status"], orders),
        "orders_archive": (["order_id", "customer_id", "product_id", "quantity", "order_date", "status"], archive),
    }
    for name, (header, rows) in files.items():
        with (DATA_DIR / f"{name}.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)


def main() -> None:
    build()
    load_sales_data()
    for name in ("customers", "products", "orders", "orders_archive"):
        info = import_uploaded_file(DATA_DIR / f"{name}.csv", f"{name}.csv")[0]
        print(f"loaded {info['table']}: {info['row_count']} rows")


if __name__ == "__main__":
    main()
