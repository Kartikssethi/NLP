"""One-sentence plain-English answers computed directly from a result set.

This is deliberately not LLM-written: a model asked to "describe these
numbers" will occasionally invent or mis-round one, and an answer line that
states a wrong figure is worse than none. The shapes below cover what the
charts cover; anything else returns None so the caller can fall back to
`nl2sql.summarize_with_llm`.
"""
import re
from typing import Any

NON_ADDITIVE = re.compile(r"\b(avg|min|max)\s*\(", re.I)
ALREADY_A_RATIO = re.compile(r"share|percent|pct|ratio|rate|proportion", re.I)
HAS_LIMIT = re.compile(r"\blimit\s+\d+", re.I)
TEMPORAL = re.compile(r"^\d{4}[-/]\d{1,2}")


def is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def fmt(v: Any) -> str:
    if isinstance(v, float):
        text = f"{v:,.2f}"
        return text.rstrip("0").rstrip(".") if "." in text else text
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:,}"
    return str(v)


def label_name(column: str) -> str:
    return column.replace("_", " ")


def summarize(columns: list[str], rows: list[tuple[Any, ...]], sql: str = "") -> str | None:
    if not rows:
        return "No rows matched."

    if columns == ["rows_affected"]:
        n = rows[0][0]
        return f"{fmt(n)} row{'' if n == 1 else 's'} affected."

    if len(columns) == 1 and len(rows) == 1:
        return f"The {label_name(columns[0])} is {fmt(rows[0][0])}."

    if len(columns) != 2 or len(rows) < 2 or not all(is_number(r[1]) for r in rows):
        return None

    dim, metric = label_name(columns[0]), label_name(columns[1])
    pairs = [("(empty)" if r[0] is None else str(r[0]), r[1]) for r in rows]

    if len(pairs) > 25 or all(TEMPORAL.match(label) for label, _ in pairs):
        peak = max(pairs, key=lambda p: p[1])
        low = min(pairs, key=lambda p: p[1])
        first, last = pairs[0], pairs[-1]
        return (
            f"Across {len(pairs):,} {dim} values, {metric} peaks at {fmt(peak[1])} ({peak[0]}) "
            f"and bottoms out at {fmt(low[1])} ({low[0]}); it ends at {fmt(last[1])} "
            f"({last[0]}) versus {fmt(first[1])} at the start ({first[0]})."
        )

    top = max(pairs, key=lambda p: p[1])
    low = min(pairs, key=lambda p: p[1])
    if top[1] == low[1]:
        return f"Every {dim} has the same {metric}: {fmt(top[1])}."

    sentence = f"{top[0]} has the highest {metric} at {fmt(top[1])}"

    values = [v for _, v in pairs]
    total = sum(values)
    # A share of the total only means something for values that add up
    # (sums/counts) — "28% of the average price" is nonsense.
    if (
        total > 0
        and min(values) >= 0
        and not NON_ADDITIVE.search(sql)
        and not ALREADY_A_RATIO.search(columns[1])
    ):
        share = top[1] / total * 100
        pct = "under 1%" if share < 1 else f"about {round(share)}%"
        scope = "total shown" if HAS_LIMIT.search(sql) else "total"
        sentence += f", {pct} of the {scope}"

    return f"{sentence}. {low[0]} is the lowest at {fmt(low[1])}."


def partial_edges(values: list[float], threshold: float = 0.7, max_each: int = 2) -> tuple[int, int]:
    """How many points at the start / end of a time series look like incomplete
    periods (data usually starts and stops mid-period, and the last stretch
    often tapers off over more than one period): each well under what the
    periods in between typically are. Looked for up to `max_each` deep per
    side; needs enough points left over to still be a series."""
    n = len(values)
    if n < 6:
        return 0, 0
    middle = sorted(values[max_each:n - max_each]) or sorted(values)
    median = middle[len(middle) // 2]
    if median <= 0:
        return 0, 0
    head = 0
    while head < max_each and values[head] < threshold * median:
        head += 1
    tail = 0
    while tail < max_each and values[n - 1 - tail] < threshold * median:
        tail += 1
    if n - head - tail < 4:
        return 0, 0
    return head, tail
