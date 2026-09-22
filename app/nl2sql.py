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
import re
from dataclasses import dataclass

from app.config import OLLAMA_MODEL, OLLAMA_HOST
from app.db import get_schema

TABLE = "sales"
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
}

# Words that name a dimension to GROUP BY, for "<agg> <metric> by <dim>" and
# "top N <dim> by <metric>".
DIMENSION_WORDS = {
    "product": "product", "products": "product",
    "brand": "brand", "brands": "brand",
    "region": "region", "regions": "region",
    "customer": "customer_name", "customers": "customer_name",
}

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

    # generic "show/list/find [all] sales [filters]"
    if re.search(r"\b(show|list|find|get)\b", t):
        where = _extract_filters(t)
        sql = f"SELECT * FROM {TABLE}"
        if where:
            sql += f" WHERE {where}"
        sql += " LIMIT 200"
        return ParseResult(sql, "rule")

    return None


class OllamaUnavailable(Exception):
    """Raised when the Ollama fallback can't be reached or fails to answer."""


def ollama_fallback(text: str) -> ParseResult:
    """Ask an Ollama model to generate SQL when the rules don't match.

    Requires `ollama serve` running (locally, or OLLAMA_HOST pointed at a
    reachable instance) and OLLAMA_MODEL available there — either pulled
    locally (`ollama pull <model>`) or, for a `*-cloud` model, an Ollama
    account with usage available for it.
    """
    import ollama  # imported lazily so the app still runs without it installed/running

    schema = get_schema()
    prompt = (
        "You are a SQL generator for a SQLite database.\n"
        f"Schema:\n{schema}\n\n"
        f"Write ONE SQLite SQL statement (no explanation, no markdown "
        f"fences, no comments) that does this: {text}"
    )
    client = ollama.Client(host=OLLAMA_HOST)
    try:
        response = client.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # noqa: BLE001 - connection errors, model errors, etc.
        raise OllamaUnavailable(
            f"Couldn't get SQL from Ollama model {OLLAMA_MODEL!r} at {OLLAMA_HOST}: {exc}"
        ) from exc

    sql = response["message"]["content"].strip()
    # strip ```sql ... ``` fences if the model added them anyway
    sql = re.sub(r"^```(?:sql)?\s*|\s*```$", "", sql, flags=re.I | re.M).strip()
    is_write = bool(re.match(r"\s*(delete|update|insert)", sql, re.I))
    return ParseResult(sql, "ollama", is_write=is_write)


def parse(text: str) -> ParseResult:
    result = rule_based_parse(text)
    if result is not None:
        return result
    return ollama_fallback(text)
