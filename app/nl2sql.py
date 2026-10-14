"""Natural language -> SQL, for the `sales` table (electronics sales data).

Two-stage pipeline, as decided for this project:

1. `rule_based_parse()` tries to match the utterance against a handful of
   common patterns (filter / group-by / top-N / delete / count / sum / avg)
   using regex + a set of known dimension values. Fast, free, deterministic
   — but only covers the phrasings it knows about.
2. If that returns None (no confident match), `ollama_fallback()` asks a
   local Ollama model to write the SQL instead, given the DB schema.

Schema: sales(product, brand, product_code, product_spec, price,
inward_date, dispatch_date, quantity_sold, customer_name,
customer_location, region, core_spec, processor_spec, ram, rom, ssd)
"""
import json
import re
from dataclasses import dataclass

from app.config import OLLAMA_MODEL, OLLAMA_HOST
from app.db import SALES_TABLE, get_join_hints, get_schema
from app.forecast import wants_forecast

TABLE = SALES_TABLE
COLUMNS = [
    "id",
    "product",
    "brand",
    "product_code",
    "product_spec",
    "price",
    "inward_date",
    "dispatch_date",
    "quantity_sold",
    "customer_name",
    "customer_location",
    "region",
    "core_spec",
    "processor_spec",
    "ram",
    "rom",
    "ssd",
]

# Filterable dimensions: known values (lowercase) -> the column they filter.
KNOWN_PRODUCTS = {"laptop", "mobile phone"}
KNOWN_BRANDS = {
    "acer", "apple", "asus", "dell", "google", "hp", "huawei", "lenovo",
    "microsoft", "motorola", "nokia", "oneplus", "oppo", "realme", "redmi",
    "samsung", "sony", "toshiba", "vivo", "iqoo",
}
KNOWN_REGIONS = {"west", "south", "north", "central", "east"}
KNOWN_RAM = {"4gb", "6gb", "8gb", "12gb", "16gb", "32gb"}
KNOWN_ROM = {"64gb", "128gb", "256gb", "512gb", "1tb"}

# Common ways people say a product/column name that don't match the literal
# value or column name. Checked before the known-value scan.
PRODUCT_ALIASES = {
    "phone": "mobile phone", "phones": "mobile phone",
    "mobile": "mobile phone", "mobiles": "mobile phone",
    "laptop": "laptop", "laptops": "laptop",
}

# Friendly words -> the numeric column they mean, for avg/sum/top-N.
COLUMN_ALIASES = {
    "price": "price", "cost": "price", "prices": "price",
    "qty": "quantity_sold", "quantity": "quantity_sold",
    "units": "quantity_sold", "sold": "quantity_sold",
    "selling": "quantity_sold", "sells": "quantity_sold", "sell": "quantity_sold",
}

# Words that name a dimension to GROUP BY, for "<agg> <metric> by <dim>" and
# "top N <dim> by <metric>".
DIMENSION_WORDS = {
    "product": "product", "products": "product",
    "brand": "brand", "brands": "brand",
    "region": "region", "regions": "region",
    "customer": "customer_name", "customers": "customer_name",
}

# Superlative phrasing ("most expensive", "which brand sold the most",
# "cheapest laptop") — common in real speech, and previously forced to the
# Ollama fallback entirely since nothing here recognized it.
_SUPERLATIVE_DESC = {"highest", "most", "top", "best", "maximum", "max", "greatest", "largest", "biggest"}
_SUPERLATIVE_ASC = {"lowest", "least", "minimum", "min", "smallest", "worst"}
# "expensive"/"cheap" imply the price column specifically, even with no
# explicit column word ("what's the most expensive laptop").
_PRICE_WORDS_DESC = {"expensive", "priciest", "costliest"}
_PRICE_WORDS_ASC = {"cheap", "cheapest"}


def _resolve_superlative_direction(t: str) -> str | None:
    if re.search(r"\b(" + "|".join(_PRICE_WORDS_DESC | _SUPERLATIVE_DESC) + r")\b", t):
        return "DESC"
    if re.search(r"\b(" + "|".join(_PRICE_WORDS_ASC | _SUPERLATIVE_ASC) + r")\b", t):
        return "ASC"
    return None


def _resolve_superlative_metric(t: str) -> str | None:
    if re.search(r"\b(" + "|".join(_PRICE_WORDS_DESC | _PRICE_WORDS_ASC) + r")\b", t):
        return "price"
    for word, col in COLUMN_ALIASES.items():
        if re.search(rf"\b{word}\b", t):
            return col
    return None


def _resolve_superlative_dimension(t: str) -> str | None:
    for word, col in DIMENSION_WORDS.items():
        if re.search(rf"\b{word}\b", t):
            return col
    return None

# Spoken numbers, e.g. Whisper transcribing "top five" instead of "top 5" —
# the digit-only regexes below (\d+) never see it unless we normalize first.
_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
    "nineteen": "19", "twenty": "20",
}


def _normalize_numbers(text: str) -> str:
    return re.sub(
        r"\b(" + "|".join(_NUMBER_WORDS) + r")\b",
        lambda m: _NUMBER_WORDS[m.group(1)],
        text,
    )


@dataclass
class ParseResult:
    sql: str
    source: str  # "rule" or "ollama"
    is_write: bool = False
    # For a write (DELETE), a SELECT that shows exactly which rows would be
    # affected, so the caller can preview before committing.
    preview_sql: str | None = None


def _find_known(text: str, known: set[str]) -> str | None:
    # Longest first so multi-word values (e.g. "mobile phone") win over a
    # shorter value that happens to be a substring.
    for val in sorted(known, key=len, reverse=True):
        if re.search(rf"\b{re.escape(val)}s?\b", text):
            return val
    return None


def _extract_filters(text: str) -> str | None:
    conditions = []

    product = None
    for alias, canonical in PRODUCT_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", text):
            product = canonical
            break
    if not product:
        product = _find_known(text, KNOWN_PRODUCTS)
    if product:
        conditions.append(f"LOWER(product) = '{product}'")

    brand = _find_known(text, KNOWN_BRANDS)
    if brand:
        conditions.append(f"LOWER(brand) = '{brand}'")

    region = _find_known(text, KNOWN_REGIONS)
    if region:
        conditions.append(f"LOWER(region) = '{region}'")

    ram = _find_known(text, KNOWN_RAM)
    if ram:
        conditions.append(f"LOWER(ram) = '{ram}'")

    rom = _find_known(text, KNOWN_ROM)
    if rom:
        conditions.append(f"LOWER(rom) = '{rom}'")

    return " AND ".join(conditions) if conditions else None


def _resolve_metric(word: str) -> str | None:
    word = word.rstrip("s") if word not in COLUMN_ALIASES else word
    if word in COLUMN_ALIASES:
        return COLUMN_ALIASES[word]
    if word in ("price", "quantity_sold"):
        return word
    return None


def _resolve_dimension(word: str) -> str | None:
    if word in DIMENSION_WORDS:
        return DIMENSION_WORDS[word]
    singular = word.rstrip("s")
    if singular in DIMENSION_WORDS:
        return DIMENSION_WORDS[singular]
    return None


def rule_based_parse(text: str) -> ParseResult | None:
    t = _normalize_numbers(text.strip().lower())

    # "<sum|total|average|avg|mean> <metric...> by <dimension>" — metric may
    # be multiple words ("quantity sold"); take whichever word sits right
    # before "by" since that's the one _resolve_metric actually needs.
    m = re.search(r"(sum|total|average|avg|mean)\s+.*?(\w+)\s+by\s+(\w+)", t)
    if m:
        agg_word, metric_word, dim_word = m.groups()
        metric = _resolve_metric(metric_word)
        dim = _resolve_dimension(dim_word)
        if metric and dim:
            agg = "AVG" if agg_word in ("average", "avg", "mean") else "SUM"
            where = _extract_filters(t)
            sql = f"SELECT {dim}, {agg}({metric}) AS {agg.lower()}_{metric} FROM {TABLE}"
            if where:
                sql += f" WHERE {where}"
            sql += f" GROUP BY {dim} ORDER BY {agg.lower()}_{metric} DESC"
            return ParseResult(sql, "rule")

    # "top N <dimension(s)> by <metric>" -> aggregate top-N
    m = re.search(r"top\s+(\d+)\s+(\w+?)s?\s+by\s+(\w+)", t)
    if m:
        n, dim_word, metric_word = m.groups()
        dim = _resolve_dimension(dim_word)
        metric = _resolve_metric(metric_word)
        if dim and metric:
            where = _extract_filters(t)
            sql = f"SELECT {dim}, SUM({metric}) AS total_{metric} FROM {TABLE}"
            if where:
                sql += f" WHERE {where}"
            sql += f" GROUP BY {dim} ORDER BY total_{metric} DESC LIMIT {n}"
            return ParseResult(sql, "rule")

    # "top N ... by <column>" -> row-level top-N
    m = re.search(r"top\s+(\d+).*?by\s+(\w+)", t)
    if m:
        n, col_word = m.groups()
        col = _resolve_metric(col_word) or (col_word if col_word in COLUMNS else None)
        if col:
            where = _extract_filters(t)
            sql = f"SELECT * FROM {TABLE}"
            if where:
                sql += f" WHERE {where}"
            sql += f" ORDER BY {col} DESC LIMIT {n}"
            return ParseResult(sql, "rule")

    # Superlative: "which brand sold the most units", "cheapest laptop",
    # "region with the lowest average price", "most popular brand" — no
    # explicit "top N"/"by", just a direction word (+ optionally a dimension
    # to group by, and/or a metric column). Checked after the explicit
    # numbered top-N patterns above (so "top 5 ... by ..." still gets that
    # more specific LIMIT-5 handling) and before delete/count/scalar below,
    # since e.g. "highest average price by brand" would otherwise get
    # mis-matched by the plain scalar "average of <col>" pattern further
    # down, ignoring "highest" and "by brand" entirely.
    direction = _resolve_superlative_direction(t)
    if direction:
        dim = _resolve_superlative_dimension(t)
        metric = _resolve_superlative_metric(t)
        where = _extract_filters(t)
        if dim:
            # "expensive"/"cheap" default to AVG (a per-unit notion of
            # "expensive brand"); everything else defaults to SUM unless
            # the utterance explicitly says average/avg/mean.
            wants_avg = bool(re.search(r"\b(average|avg|mean)\b", t)) or (
                metric == "price" and re.search(r"\b(expensive|priciest|costliest|cheap|cheapest)\b", t)
            )
            if metric:
                agg = "AVG" if wants_avg else "SUM"
                sql = f"SELECT {dim}, {agg}({metric}) AS {agg.lower()}_{metric} FROM {TABLE}"
                order_col = f"{agg.lower()}_{metric}"
            else:
                # No metric word found ("most popular brand") — rank by
                # row count instead of failing outright.
                sql = f"SELECT {dim}, COUNT(*) AS count FROM {TABLE}"
                order_col = "count"
            if where:
                sql += f" WHERE {where}"
            sql += f" GROUP BY {dim} ORDER BY {order_col} {direction} LIMIT 1"
            return ParseResult(sql, "rule")
        elif metric:
            # No dimension to group by — a single-row request, e.g.
            # "most expensive laptop" / "cheapest phone in the west".
            sql = f"SELECT * FROM {TABLE}"
            if where:
                sql += f" WHERE {where}"
            sql += f" ORDER BY {metric} {direction} LIMIT 1"
            return ParseResult(sql, "rule")
        # direction word present but no dimension AND no metric resolved —
        # too vague for a rule (e.g. bare "the best one"); let Ollama try.

    # "remove/delete N ... [filters]" -> DELETE, with a preview SELECT
    m = re.search(r"(remove|delete)\s+(\d+)", t)
    if m:
        n = m.group(2)
        where = _extract_filters(t)
        sub = f"SELECT id FROM {TABLE}"
        if where:
            sub += f" WHERE {where}"
        sub += f" LIMIT {n}"
        sql = f"DELETE FROM {TABLE} WHERE id IN ({sub})"
        preview_sql = f"SELECT * FROM {TABLE} WHERE id IN ({sub})"
        return ParseResult(sql, "rule", is_write=True, preview_sql=preview_sql)

    # "how many / count ..." [in each <dim> | by <dim>] [filters]
    if re.search(r"\bhow many\b|\bcount\b", t):
        m = re.search(r"(?:in each|group(?:ed)? by|per|by)\s+(\w+)", t)
        group_col = _resolve_dimension(m.group(1)) if m else None
        where = _extract_filters(t)
        if group_col:
            sql = f"SELECT {group_col}, COUNT(*) AS count FROM {TABLE}"
            if where:
                sql += f" WHERE {where}"
            sql += f" GROUP BY {group_col} ORDER BY count DESC"
            return ParseResult(sql, "rule")
        sql = f"SELECT COUNT(*) AS count FROM {TABLE}"
        if where:
            sql += f" WHERE {where}"
        return ParseResult(sql, "rule")

    # "average/avg/mean of <column>" (scalar, no group-by)
    m = re.search(r"(average|avg|mean)\s+(?:of\s+)?(\w+)", t)
    if m:
        col = _resolve_metric(m.group(2))
        if col:
            where = _extract_filters(t)
            sql = f"SELECT AVG({col}) AS average_{col} FROM {TABLE}"
            if where:
                sql += f" WHERE {where}"
            return ParseResult(sql, "rule")

    # "sum/total of <column>" (scalar, no group-by)
    m = re.search(r"(sum|total)\s+(?:of\s+)?(\w+)", t)
    if m:
        col = _resolve_metric(m.group(2))
        if col:
            where = _extract_filters(t)
            sql = f"SELECT SUM({col}) AS total_{col} FROM {TABLE}"
            if where:
                sql += f" WHERE {where}"
            return ParseResult(sql, "rule")

    # generic "show/list/find/get/display [all] sales [filters]" — anchored
    # at the start of the utterance, not just "contains the word somewhere",
    # so a question like "can I get a graph on..." (which isn't actually a
    # show-me-rows request) falls through to the Ollama fallback instead of
    # being misread as one. Also skipped when the phrase asks for a chart or
    # a superlative ("worst selling", "most popular") — this rule only knows
    # how to dump filtered raw rows, not compute an aggregate/ranking, so
    # "show me a chart of the worst selling product" needs Ollama too, even
    # though it starts with "show".
    wants_aggregate = re.search(
        r"\b(chart|graph|plot|visuali[sz]e|best|worst|most|least|trend|trends|"
        r"over time|breakdown|distribution|compare|comparison)\b",
        t,
    )
    if not wants_aggregate and re.match(r"(?:please\s+)?(show|list|find|get|display)\b", t):
        where = _extract_filters(t)
        sql = f"SELECT * FROM {TABLE}"
        if where:
            sql += f" WHERE {where}"
        sql += " LIMIT 200"
        return ParseResult(sql, "rule")

    return None


class OllamaUnavailable(Exception):
    """Raised when the Ollama fallback can't be reached or fails to answer."""


class UnsafeSQL(Exception):
    """The model wrote a data-changing statement that can't be previewed."""


_TREND_WORDS = re.compile(
    r"\b(trend|trends|over time|timeline|monthly|weekly|daily|yearly|per month|"
    r"each month|by month|per year|by year|per day|by day|predict|prediction|forecast|"
    r"projection|extrapolate|next \d+ (?:day|week|month|year)s?)\b"
)


def _build_query_plan(text: str) -> str | None:
    """A lightweight structured read of the question — metric / group-by /
    filters / sort direction / limit — built from the same extraction
    helpers rule_based_parse() uses (_resolve_superlative_*, _extract_filters).

    Handed to the Ollama prompt as extra scaffolding so it lands on the
    right column and aggregation even for a phrasing none of the rule-based
    patterns fully match — the LLM equivalent of "show your work" before
    writing the SQL. Only meaningful for the `sales` schema, since these
    extractors key off its specific known values/aliases; callers skip this
    for an uploaded dataset's arbitrary schema.
    """
    t = _normalize_numbers(text.strip().lower())

    metric = _resolve_superlative_metric(t)
    dimension = _resolve_superlative_dimension(t)
    direction = _resolve_superlative_direction(t)
    filters = _extract_filters(t)
    limit_match = re.search(r"top\s+(\d+)", t)

    # "trend of the product sales" mentions a dimension word (product) but the
    # question is about change over time — a dimension guessed from keywords
    # must not override that.
    if _TREND_WORDS.search(t):
        dimension = (
            "time — one row per month, strftime('%Y-%m', dispatch_date) "
            "(or inward_date if the question is about stock received)"
        )

    if not any([metric, dimension, direction, filters, limit_match]):
        return None

    return (
        f"metric: {metric or '(none detected — infer from the question)'}\n"
        f"group_by: {dimension or '(none)'}\n"
        f"filters: {filters or '(none)'}\n"
        f"sort: {direction or '(unspecified)'}\n"
        f"limit: {limit_match.group(1) if limit_match else '(none)'}"
    )


def _is_sales_only(tables: list[str] | None) -> bool:
    return not tables or set(tables) == {TABLE}


_MULTI_TABLE_RULES = (
    "MULTI-TABLE RULES:\n"
    "1. Use only the tables and columns listed in the schema above — never "
    "invent one.\n"
    "2. Qualify every column with its table name or alias (orders.region, "
    "not region) whenever more than one table is in the query.\n"
    "3. Join tables on columns that hold the same kind of value — use the "
    "relationship hints and the example values shown. Every JOIN needs an "
    "explicit ON condition; never write a CROSS JOIN or a comma join without "
    "a WHERE condition linking the tables.\n"
    "4. Use INNER JOIN by default; use LEFT JOIN only when the question asks "
    "to keep rows that have no match.\n"
    "5. If the question asks to merge/combine/stack/append tables with the "
    "same columns, use UNION ALL. If it asks to merge/combine tables on a "
    "key, use a JOIN.\n"
    "6. Joining a one-to-many relationship repeats the \"one\" side's rows — "
    "aggregate the measure from the correct table, and use COUNT(DISTINCT ...) "
    "when counting entities on the \"one\" side.\n"
    "7. Give computed columns clear aliases (AS total_sales) so the result "
    "reads well and can be charted.\n"
    "8. Wrap any table or column named like an SQL keyword (order, group, "
    "key...) in double quotes.\n"
    "9. Output exactly one SQL statement, nothing else — no markdown fences, "
    "no explanation, no comments.\n\n"
)


def ollama_fallback(
    text: str,
    history: list[dict[str, str]] | None = None,
    tables: list[str] | None = None,
    drill: dict[str, str] | None = None,
) -> ParseResult:
    """Ask an Ollama model to generate SQL when the rules don't match.

    Requires `ollama serve` running (locally, or OLLAMA_HOST pointed at a
    reachable instance) and OLLAMA_MODEL available there — either pulled
    locally (`ollama pull <model>`) or, for a `*-cloud` model, an Ollama
    account with usage available for it.

    `history` is prior turns in this conversation, oldest first, each a
    {"text": ..., "sql": ...} dict — lets a follow-up like "now break that
    down by region" resolve "that" against what was already asked/run.

    `drill` ({"column", "value"}) means the user clicked one bar/slice of the
    previous chart: the model is told to narrow the previous query to that
    value and break it down by another column.

    `tables` scopes the schema shown to the model to just those tables —
    user-uploaded datasets (see app/db.py::import_uploaded_csv) have no
    hand-written rule-based parser support, so they always go through here,
    without the unrelated `sales` schema cluttering the prompt. With more
    than one table the model is also given example values and relationship
    hints, plus rules for joining/merging them. The sales-specific query
    plan/strict-rules/few-shot blocks below are skipped unless `sales` is the
    only table, since they assume its schema.
    """
    import ollama  # imported lazily so the app still runs without it installed/running

    is_sales = _is_sales_only(tables)
    multi = bool(tables) and len(tables) > 1
    schema = get_schema(tables, with_samples=multi)

    history_block = ""
    if history:
        turns = "\n".join(f"Q: {h['text']}\nSQL: {h['sql']}" for h in history[-5:])
        history_block = (
            "Earlier turns in this conversation (most recent last) — use them "
            "to resolve references like \"that\", \"it\", \"those\", or a "
            f"follow-up refinement of a prior question:\n{turns}\n\n"
        )
    table_line = ""
    if tables:
        table_line = "Write SQL against " + (
            f"these tables: {', '.join(f'`{t}`' for t in tables)}.\n" if multi
            else f"the `{tables[0]}` table.\n"
        )

    hints_block = ""
    if multi:
        hints = get_join_hints(tables)
        if hints:
            hints_block = f"Likely relationships between the tables:\n{hints}\n\n"

    drill_block = ""
    if drill:
        drill_block = (
            f"The user clicked \"{drill['value']}\" in a chart of the previous result "
            f"(the chart's label column was `{drill['column']}`). Take the previous "
            "query, keep its filters, add a condition selecting that one value, and "
            f"group by a different, informative column (not `{drill['column']}`) so the "
            "result is a new breakdown of just that value. Use the previous SQL's real "
            "table/column names for the condition.\n\n"
        )

    plan_block = ""
    if is_sales and not drill:
        plan = _build_query_plan(text)
        if plan:
            plan_block = (
                "Extracted query plan (a best-effort guess from keyword "
                "matching — trust the question over the plan if they "
                f"conflict):\n{plan}\n\n"
            )

    rules_block = ""
    examples_block = ""
    if is_sales:
        rules_block = (
            "STRICT RULES:\n"
            "1. Only use tables and columns that appear in the schema above "
            "— never invent one.\n"
            "2. Generate a SELECT unless the question explicitly asks to "
            "delete/remove rows, in which case generate exactly one DELETE "
            "statement instead.\n"
            "3. SQLite has no YEAR() function and no separate year column — "
            "filter a date column with a range instead, e.g. "
            "inward_date >= '2025-01-01' AND inward_date < '2026-01-01'.\n"
            "4. WHERE comes before GROUP BY, which comes before ORDER BY.\n"
            "5. A question about how many units sold should SUM(quantity_sold); "
            "a question about how many orders/rows should COUNT(*); a "
            "question about price should AVG(price) unless a total is "
            "explicitly asked for.\n"
            "6. A trend / over-time question groups by month: "
            "strftime('%Y-%m', dispatch_date), ordered chronologically.\n"
            "7. Output exactly one SQL statement, nothing else — no markdown "
            "fences, no explanation, no comments.\n\n"
        )
        examples_block = (
            "EXAMPLES:\n\n"
            "Q: total quantity sold by brand\n"
            "SQL: SELECT brand, SUM(quantity_sold) AS total_quantity_sold "
            "FROM sales GROUP BY brand ORDER BY total_quantity_sold DESC\n\n"
            "Q: average price of samsung phones in the west region\n"
            "SQL: SELECT AVG(price) AS avg_price FROM sales WHERE "
            "LOWER(brand) = 'samsung' AND LOWER(product) = 'mobile phone' "
            "AND LOWER(region) = 'west'\n\n"
            "Q: show me the sales trend over time\n"
            "SQL: SELECT strftime('%Y-%m', dispatch_date) AS month, "
            "SUM(quantity_sold) AS total_quantity_sold FROM sales "
            "GROUP BY month ORDER BY month\n\n"
            "Q: how many laptops were dispatched after january 2024\n"
            "SQL: SELECT COUNT(*) AS count FROM sales WHERE "
            "LOWER(product) = 'laptop' AND dispatch_date >= '2024-01-01'\n\n"
        )

    prompt = (
        "You are a highly reliable SQLite SQL generator.\n\n"
        f"{history_block}"
        f"{drill_block}"
        f"{table_line}"
        f"Schema:\n{schema}\n\n"
        f"{hints_block}"
        f"{_MULTI_TABLE_RULES if multi else ''}"
        f"{plan_block}"
        f"{rules_block}"
        f"{examples_block}"
        f"Question: {text}\n\n"
        "The question may be in English, Hindi or Hinglish (Hindi in English "
        "letters); interpret it either way.\n"
        "If it asks to predict/forecast, return the historical series to extend: "
        "one row per month (or day), ordered by date, as (period, value).\n"
        "If this asks for a chart/graph/plot/trend/breakdown/comparison, "
        "prefer a GROUP BY query that returns multiple comparable rows (e.g. "
        "one per category, or one per date/month for a trend over time) "
        "rather than a single row, unless a specific top-N count was "
        "requested.\n\n"
        "Return ONLY the SQL query."
    )
    client = ollama.Client(host=OLLAMA_HOST)
    try:
        response = client.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0},
        )
    except Exception as exc:  # noqa: BLE001 - connection errors, model errors, etc.
        raise OllamaUnavailable(
            f"Couldn't get SQL from Ollama model {OLLAMA_MODEL!r} at {OLLAMA_HOST}: {exc}"
        ) from exc

    sql = response["message"]["content"].strip()
    # strip ```sql ... ``` fences if the model added them anyway
    sql = re.sub(r"^```(?:sql)?\s*|\s*```$", "", sql, flags=re.I | re.M).strip()
    # the odd model escapes a wildcard/underscore in markdown-adjacent output
    sql = sql.replace("\\*", "*").replace("\\_", "_")
    sql = sql.strip().rstrip(";").strip()
    is_write = bool(re.match(r"\s*(delete|update|insert)", sql, re.I))
    preview_sql = None
    if is_write:
        # A write is only run after showing what it would touch, which for a
        # DELETE is the same FROM/WHERE as a SELECT. Anything else (UPDATE,
        # INSERT, DROP...) has no such preview, so it is refused, not run blind.
        m = re.match(r"\s*delete\s+from\s+(.+)$", sql, re.I | re.S)
        if not m:
            raise UnsafeSQL(
                "That would change the data in a way I can't preview first, so I didn't run it. "
                "Cleaning commands like 'remove duplicate rows' or 'fill empty price with the average' are supported."
            )
        preview_sql = f"SELECT * FROM {m.group(1)}"
    return ParseResult(sql, "ollama", is_write=is_write, preview_sql=preview_sql)


# Explanatory diagram requests ("explain this dataset with a flowchart",
# "sequence diagram of...", "ER diagram") are a fundamentally different ask
# from a data query: they want a description of the dataset's *structure*,
# not an aggregation of its *values*. Forcing that through the SQL pipeline
# produces something technically valid but meaningless (e.g. a random
# GROUP BY rendered as a one-bar chart). Detected separately, before SQL
# parsing/generation ever runs — see main.py::_run_query.
_DIAGRAM_WORDS = re.compile(
    r"\b(flowchart|flow chart|sequence diagram|mind ?map|er diagram|"
    r"entity relationship|class diagram|diagram)\b",
    re.I,
)


def wants_diagram(text: str) -> bool:
    return bool(_DIAGRAM_WORDS.search(text))


def generate_diagram(text: str, tables: list[str] | None = None) -> str:
    """Ask Ollama for a Mermaid diagram (not SQL) describing the dataset's
    structure, per an explicit flowchart/sequence-diagram/etc. request. With
    several uploaded tables, the relationship hints let an ER diagram draw
    the links between them."""
    import ollama  # imported lazily so the app still runs without it installed/running

    schema = get_schema(tables)
    hints = get_join_hints(tables) if tables and len(tables) > 1 else ""
    hints_block = f"Likely relationships between the tables:\n{hints}\n\n" if hints else ""
    prompt = (
        "You produce Mermaid diagrams only — no SQL, no explanation outside "
        "the diagram itself.\n"
        f"Database schema:\n{schema}\n\n"
        f"{hints_block}"
        f"Request: {text}\n\n"
        "Pick whichever Mermaid diagram type actually fits the request "
        "(flowchart TD, erDiagram, sequenceDiagram, mindmap, classDiagram, "
        "etc.) and describe the dataset's structure — its tables, columns, "
        "and how they relate — not example data values. Output ONLY the "
        "Mermaid source, starting with the diagram-type keyword. No markdown "
        "fences, no commentary before or after."
    )
    client = ollama.Client(host=OLLAMA_HOST)
    try:
        response = client.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # noqa: BLE001 - connection errors, model errors, etc.
        raise OllamaUnavailable(
            f"Couldn't get a diagram from Ollama model {OLLAMA_MODEL!r} at {OLLAMA_HOST}: {exc}"
        ) from exc

    diagram = response["message"]["content"].strip()
    diagram = re.sub(r"^```(?:mermaid)?\s*|\s*```$", "", diagram, flags=re.I | re.M).strip()
    return diagram


def explain_sql(sql: str, question: str, tables: list[str] | None = None) -> str:
    """Ask Ollama for a short plain-English explanation of a SQL query
    already generated for `question` — a "show your work" aid, not part of
    the query pipeline itself."""
    import ollama  # imported lazily so the app still runs without it installed/running

    schema = get_schema(tables)
    prompt = (
        "Explain what this SQL query does, in plain English, for someone "
        "who doesn't know SQL. 2-4 short sentences, no jargon, no markdown, "
        "no restating the SQL syntax line by line — describe what data it "
        "looks at and what it computes.\n\n"
        f"Database schema:\n{schema}\n\n"
        f"Original question: {question}\n"
        f"SQL:\n{sql}"
    )
    client = ollama.Client(host=OLLAMA_HOST)
    try:
        response = client.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # noqa: BLE001 - connection errors, model errors, etc.
        raise OllamaUnavailable(
            f"Couldn't get an explanation from Ollama model {OLLAMA_MODEL!r} at {OLLAMA_HOST}: {exc}"
        ) from exc

    return response["message"]["content"].strip()


def _ollama_text(prompt: str, what: str) -> str:
    import ollama  # imported lazily so the app still runs without it installed/running

    client = ollama.Client(host=OLLAMA_HOST)
    try:
        response = client.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0},
        )
    except Exception as exc:  # noqa: BLE001 - connection errors, model errors, etc.
        raise OllamaUnavailable(
            f"Couldn't get {what} from Ollama model {OLLAMA_MODEL!r} at {OLLAMA_HOST}: {exc}"
        ) from exc
    return response["message"]["content"].strip()


def translate_question(text: str, tables: list[str] | None = None) -> str:
    """Rewrite a spoken Hindi / Hinglish request (as transcribed — possibly in
    Devanagari or Urdu script, possibly with mishearings) as one clear English
    question about the data. The table schema is what lets it repair a
    mishearing: "branches" is almost certainly "brands" when the schema has a
    brand column."""
    schema = get_schema(tables)
    prompt = (
        "A person asked a question about a database out loud, in Hindi, Hinglish "
        "(Hindi in English letters) or English. It was transcribed by a "
        "speech-recognition system, so it may be in Devanagari/Urdu script and "
        "may contain misheard words.\n\n"
        f"Database schema:\n{schema}\n\n"
        f"Transcript: {text}\n\n"
        "Rewrite it as ONE clear English question or command about this data. "
        "Where a word looks misheard, pick the schema column or value it most "
        "likely meant. If it is already clear English, return it unchanged. "
        "Return ONLY the English sentence."
    )
    return _ollama_text(prompt, "a translation").strip().strip('"')


def summarize_with_llm(question: str, columns: list[str], rows: list[list]) -> str:
    """One or two sentences answering `question` from a result set whose
    shape the deterministic summarizer (app/summary.py) doesn't cover — e.g.
    several columns. Only the first rows are shown to the model."""
    shown = rows[:30]
    table = "\n".join([" | ".join(columns)] + [" | ".join("" if v is None else str(v) for v in r) for r in shown])
    note = f" (first {len(shown)} of {len(rows)} rows)" if len(rows) > len(shown) else ""
    prompt = (
        "Answer the question below in ONE or TWO plain sentences, using only "
        "the data table. Use only numbers that appear in the table — never "
        "compute or estimate new ones. No markdown, no preamble.\n\n"
        f"Question: {question}\n\nData{note}:\n{table}"
    )
    return _ollama_text(prompt, "a summary")


def suggest_questions(tables: list[str] | None, count: int = 4) -> list[str]:
    """A few starter questions a non-technical person could ask about these
    tables. With several tables, some should need them combined — it's the
    quickest way to show off the join support."""
    schema = get_schema(tables, with_samples=True)
    multi = bool(tables) and len(tables) > 1
    hints = get_join_hints(tables) if multi else ""
    prompt = (
        "Suggest questions a non-technical person might ask about this "
        "database, in plain everyday language (no SQL, no column names in "
        "code style).\n\n"
        f"Schema:\n{schema}\n\n"
        + (f"Likely relationships between the tables:\n{hints}\n\n" if hints else "")
        + f"Write exactly {count} short questions (under 12 words each) that "
        "can be answered from this data. Make them varied: at least one "
        "ranking or total, and one that asks for a chart. "
        + ("At least two must need information from more than one table. " if multi else "")
        + "Return ONLY a JSON array of strings."
    )
    content = _ollama_text(prompt, "question suggestions")

    match = re.search(r"\[.*\]", content, re.S)
    try:
        items = json.loads(match.group(0)) if match else []
    except json.JSONDecodeError:
        items = []
    if not items:  # model ignored the JSON instruction — salvage a bulleted/numbered list
        items = [re.sub(r"^[-*\d.)\s]+", "", line).strip(' "') for line in content.splitlines()]
    questions = [q.strip() for q in items if isinstance(q, str) and 8 <= len(q.strip()) <= 140]
    return questions[:count]


def parse(
    text: str,
    history: list[dict[str, str]] | None = None,
    tables: list[str] | None = None,
    drill: dict[str, str] | None = None,
) -> ParseResult:
    # Anything other than `sales` alone means user-uploaded data (possibly
    # several tables to join), not the sample table the rule-based parser is
    # hand-tuned for — its patterns reference sales-specific columns and known
    # values (KNOWN_BRANDS, KNOWN_REGIONS, ...), so they'd misfire against an
    # arbitrary schema. Go straight to Ollama, schema-scoped to those tables.
    if not _is_sales_only(tables):
        return ollama_fallback(text, history=history, tables=tables, drill=drill)

    # A drill-down is "this one value of the previous result", a forecast needs
    # the monthly series rather than a single number — neither is something
    # the rule patterns understand, and they'd misread e.g. "next 3 months".
    if drill or wants_forecast(text):
        return ollama_fallback(text, history=history, tables=tables, drill=drill)

    # The rule-based parser has no conversational memory — it's a fast path
    # for standalone phrasings. A follow-up ("now just for laptops") won't
    # match any of its patterns anyway, so it naturally falls through here.
    result = rule_based_parse(text)
    if result is not None:
        return result
    return ollama_fallback(text, history=history)
