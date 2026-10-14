"""Notable things worth pointing out in a result, found with plain arithmetic.

Like the answer line (app/summary.py) this is never LLM-written: a callout
that claims "sales fell 38%" has to be exactly right. Each insight is
`{"kind": "up" | "down" | "info", "text": ...}`; at most three are returned,
and only for things that clear a threshold, so most results have none.
"""
import statistics

from app.summary import (
    ALREADY_A_RATIO,
    HAS_LIMIT,
    NON_ADDITIVE,
    TEMPORAL,
    fmt,
    is_number,
    label_name,
    partial_edges,
)

_SWING_PCT = 20      # a period-over-period change smaller than this isn't news
_BELOW_PEAK_PCT = 20
_Z_OUTLIER = 2.2
_MAX_INSIGHTS = 3


def _pct(x: float) -> str:
    return f"{abs(x):,.0f}%"


def _series_insights(pairs: list[tuple[str, float]], metric: str, dim: str) -> list[dict]:
    out: list[dict] = []
    head, tail = partial_edges([p[1] for p in pairs])
    # Edge periods that look incomplete would show up as a fake crash/surge, so
    # they are left out of the maths below, and mentioned instead.
    dropped = pairs[:head] + pairs[len(pairs) - tail:]
    if dropped:
        names = ", ".join(f"{label} ({fmt(v)})" for label, v in dropped)
        out.append({"kind": "info", "text": f"{names} look{'s' if len(dropped) == 1 else ''} incomplete, so left out of these comparisons"})
    pairs = pairs[head:len(pairs) - tail]
    if len(pairs) < 4:
        return out
    labels, values = [p[0] for p in pairs], [p[1] for p in pairs]
    last = len(pairs) - 1

    # Biggest step from one period to the next. A step from the very first
    # point is skipped (a series usually starts mid-period, so it "grows" from
    # a partial value), and one that ends on the last point is flagged, since
    # the latest period is often incomplete.
    swings = [
        (i, (values[i] - values[i - 1]) / values[i - 1] * 100)
        for i in range(2, len(values))
        if values[i - 1] > 0
    ]
    swing_label = None
    if swings:
        i, change = max(swings, key=lambda t: abs(t[1]))
        if abs(change) >= _SWING_PCT:
            swing_label = labels[i]
            text = f"{metric.capitalize()} {'rose' if change > 0 else 'fell'} {_pct(change)} in {labels[i]} compared with {labels[i - 1]}"
            if i == last:
                text += " (the latest period may be incomplete)"
            out.append({"kind": "up" if change > 0 else "down", "text": text})

    peak_i = max(range(len(values)), key=lambda i: values[i])
    if peak_i != last and values[peak_i] > 0:
        below = (values[peak_i] - values[last]) / values[peak_i] * 100
        if below >= _BELOW_PEAK_PCT:
            out.append({
                "kind": "down",
                "text": f"The latest value ({fmt(values[last])}) is {_pct(below)} below the peak ({labels[peak_i]})",
            })

    if len(values) >= 6:
        mean, sd = statistics.mean(values), statistics.pstdev(values)
        if sd > 0:
            i = max(range(len(values)), key=lambda i: abs(values[i] - mean))
            z = (values[i] - mean) / sd
            if abs(z) >= _Z_OUTLIER and labels[i] != swing_label:
                out.append({
                    "kind": "up" if z > 0 else "down",
                    "text": f"{labels[i]} is unusually {'high' if z > 0 else 'low'} ({fmt(values[i])}) compared with the typical {fmt(mean)}",
                })
    return out


def _category_insights(pairs: list[tuple[str, float]], sql: str, columns: list[str]) -> list[dict]:
    out: list[dict] = []
    ranked = sorted(pairs, key=lambda p: p[1], reverse=True)
    values = [v for _, v in pairs]
    additive = (
        min(values) >= 0
        and sum(values) > 0
        and not NON_ADDITIVE.search(sql)
        and not ALREADY_A_RATIO.search(columns[1])
    )

    # (The single top share is already in the answer line, so only a
    # concentration across several categories is added here.)
    if additive and len(pairs) >= 6:
        top3 = ranked[:3]
        share = sum(v for _, v in top3) / sum(values) * 100
        if share >= 60:
            scope = "total shown" if HAS_LIMIT.search(sql) else "total"
            out.append({"kind": "info", "text": f"The top 3 ({', '.join(l for l, _ in top3)}) make up {_pct(share)} of the {scope}"})

    top, low = ranked[0], ranked[-1]
    if low[1] > 0 and top[1] / low[1] >= 3:
        out.append({"kind": "info", "text": f"{top[0]} is {top[1] / low[1]:.1f}× {low[0]}"})

    if len(values) >= 6:
        mean, sd = statistics.mean(values), statistics.pstdev(values)
        if sd > 0 and mean > 0:
            z = (top[1] - mean) / sd
            if z >= _Z_OUTLIER:
                out.append({"kind": "up", "text": f"{top[0]} stands out at {fmt(top[1])}, {top[1] / mean:.1f}× the average"})
    return out


def insights(columns: list[str], rows: list[tuple], sql: str = "") -> list[dict]:
    if len(columns) != 2 or len(rows) < 3 or not all(is_number(r[1]) for r in rows):
        return []
    pairs = [("(empty)" if r[0] is None else str(r[0]), r[1]) for r in rows]
    metric, dim = label_name(columns[1]), label_name(columns[0])

    if len(pairs) >= 4 and all(TEMPORAL.match(label) for label, _ in pairs):
        found = _series_insights(pairs, metric, dim)
    elif len(pairs) <= 25:
        found = _category_insights(pairs, sql, columns)
    else:
        found = []
    notices = [i for i in found if i['text'].endswith('left out of these comparisons')]
    findings = [i for i in found if i not in notices]
    return (findings + notices)[:_MAX_INSIGHTS]
