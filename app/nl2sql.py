"""Natural language -> SQL.

Two-stage pipeline, as decided for this project:

1. `rule_based_parse()` tries to match the utterance against a handful of
   common patterns (select / filter / top-N / delete / count / sum / avg)
   using regex over a fixed table+columns. Fast, free, deterministic —
   but only covers the phrasings it knows about.
2. If that returns None (no confident match), `ollama_fallback()` asks a
   local Ollama model to write the SQL instead, given the DB schema.

This is intentionally a *starting point*: the regexes are tuned for the
sample `people` table in app/db.py (name, age, city, department). When you
swap in your real dataset, update TABLE/COLUMNS below and extend the
patterns in `rule_based_parse` to match your columns and the phrasings
your users actually say.
"""
import re
from dataclasses import dataclass

from app.config import OLLAMA_MODEL, OLLAMA_HOST
from app.db import get_schema

TABLE = "people"
COLUMNS = ["id", "name", "age", "city", "department"]

# very small set of recognized filter phrasings: "in <city>", "from <city>",
# "department is/are <dept>", "<column> is/= <value>"
# Known values for the sample `people` table. When you swap in your real
# dataset, replace these with your actual city/department values (or better,
# query DISTINCT values from the DB at startup) so filters resolve to the
# right column instead of guessing.
KNOWN_CITIES = {"mumbai", "pune", "delhi", "bengaluru", "chennai"}
KNOWN_DEPARTMENTS = {"engineering", "sales", "marketing"}

_FILTER_PATTERNS = [
    re.compile(r"\bdepartment\s+(?:is|are|=)\s+(?P<val>[a-zA-Z ]+)", re.I),
    re.compile(r"\bcity\s+(?:is|are|=)\s+(?P<val>[a-zA-Z ]+)", re.I),
    re.compile(r"\b(?:in|from)\s+(?P<val>[a-zA-Z ]+?)\b(?=\s|$)", re.I),
]


@dataclass
class ParseResult:
    sql: str
    source: str  # "rule" or "ollama"


def _extract_filter(text: str) -> str | None:
    # Case-insensitive on both sides: the utterance is lowercased already,
    # and stored values (e.g. "Mumbai") are Title-cased, so we compare with
    # LOWER() rather than assuming casing matches.
    for pat in _FILTER_PATTERNS:
        m = pat.search(text)
        if m:
            val = m.group("val").strip()
            val_lower = val.lower()
            if val_lower in KNOWN_DEPARTMENTS:
                return f"LOWER(department) = '{val_lower}'"
            if val_lower in KNOWN_CITIES:
                return f"LOWER(city) = '{val_lower}'"
            # Unknown value (e.g. stray word like "each"/"the" matched by the
            # generic "in/from X" pattern): don't filter on a guess.
    return None


def _extract_groupby(text: str) -> str | None:
    """'how many ... in each <col>' / 'count by <col>' / 'group by <col>'."""
    m = re.search(r"(?:in each|group(?:ed)? by|per|by)\s+(\w+)", text)
    if not m:
        return None
    word = m.group(1).rstrip("s")  # crude singularize: "departments" -> "department"
    for col in ("department", "city"):
        if word == col or word == col.rstrip("y") or word in col:
            return col
    return None


def rule_based_parse(text: str) -> ParseResult | None:
    t = text.strip().lower()

    # "top N ... by <column>"
    m = re.search(r"top\s+(\d+).*?by\s+(\w+)", t)
    if m:
        n, col = m.group(1), m.group(2)
        if col in COLUMNS:
            where = _extract_filter(t)
            sql = f"SELECT * FROM {TABLE}"
            if where:
                sql += f" WHERE {where}"
            sql += f" ORDER BY {col} DESC LIMIT {n}"
            return ParseResult(sql, "rule")

    # "remove/delete N ... [filters]"
    m = re.search(r"(remove|delete)\s+(\d+)", t)
    if m:
        n = m.group(2)
        where = _extract_filter(t)
        sub = f"SELECT id FROM {TABLE}"
        if where:
            sub += f" WHERE {where}"
        sub += f" LIMIT {n}"
        sql = f"DELETE FROM {TABLE} WHERE id IN ({sub})"
        return ParseResult(sql, "rule")

    # "how many / count ..."
    if re.search(r"\bhow many\b|\bcount\b", t):
        group_col = _extract_groupby(t)
        if group_col:
            sql = f"SELECT {group_col}, COUNT(*) AS count FROM {TABLE} GROUP BY {group_col}"
            return ParseResult(sql, "rule")
        where = _extract_filter(t)
        sql = f"SELECT COUNT(*) AS count FROM {TABLE}"
        if where:
            sql += f" WHERE {where}"
        return ParseResult(sql, "rule")

    # "average/avg/mean of <column>"
    m = re.search(r"(average|avg|mean)\s+(?:of\s+)?(\w+)", t)
    if m and m.group(2) in COLUMNS:
        col = m.group(2)
        where = _extract_filter(t)
        sql = f"SELECT AVG({col}) AS average_{col} FROM {TABLE}"
        if where:
            sql += f" WHERE {where}"
        return ParseResult(sql, "rule")

    # "sum/total of <column>"
    m = re.search(r"(sum|total)\s+(?:of\s+)?(\w+)", t)
    if m and m.group(2) in COLUMNS:
        col = m.group(2)
        where = _extract_filter(t)
        sql = f"SELECT SUM({col}) AS total_{col} FROM {TABLE}"
        if where:
            sql += f" WHERE {where}"
        return ParseResult(sql, "rule")

    # generic "show/list/find [all] people [filters]"
    if re.search(r"\b(show|list|find|get)\b", t):
        where = _extract_filter(t)
        sql = f"SELECT * FROM {TABLE}"
        if where:
            sql += f" WHERE {where}"
        return ParseResult(sql, "rule")

    return None


def ollama_fallback(text: str) -> ParseResult:
    """Ask a local Ollama model to generate SQL when the rules don't match.

    Requires `ollama serve` running locally (or OLLAMA_HOST pointed at a
    reachable instance) and the model pulled, e.g. `ollama pull llama3.1`.
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
    response = client.chat(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    sql = response["message"]["content"].strip()
    # strip ```sql ... ``` fences if the model added them anyway
    sql = re.sub(r"^```(?:sql)?\s*|\s*```$", "", sql, flags=re.I | re.M).strip()
    return ParseResult(sql, "ollama")


def parse(text: str) -> ParseResult:
    result = rule_based_parse(text)
    if result is not None:
        return result
    return ollama_fallback(text)
