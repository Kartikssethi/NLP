"""A deliberately simple forecast: fit a straight line to a time series and
extend it. Cheap, explainable, and honest about being a rough guide — the
answer line states the fit quality so a noisy series isn't oversold."""
import datetime
import re

import numpy as np

from app.summary import fmt, is_number, label_name, partial_edges

_FORECAST_WORDS = re.compile(
    r"\b(predict|prediction|predictions|forecast|forecasts|projection|projections|extrapolate|"
    r"next\s+(?:\d+\s+)?(?:day|week|month|quarter|year)s?)\b",
    re.I,
)
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_YEAR = re.compile(r"^\d{4}$")

DEFAULT_PERIODS = 3
MAX_PERIODS = 24
MIN_POINTS = 4


def wants_forecast(text: str) -> bool:
    return bool(_FORECAST_WORDS.search(text))


def periods_requested(text: str) -> int:
    """"next 6 months" -> 6; otherwise 3. The unit is ignored: the forecast
    always continues in the series' own period (months stay months)."""
    m = re.search(r"next\s+(\d+)", text, re.I)
    return max(1, min(int(m.group(1)), MAX_PERIODS)) if m else DEFAULT_PERIODS


def _next_labels(labels: list[str], n: int) -> list[str] | None:
    """The `n` labels following the last of `labels`, in the same format, or
    None when the labels aren't a recognizable date series."""
    if all(_MONTH.match(l) for l in labels):
        y, m = map(int, _MONTH.match(labels[-1]).groups())
        out = []
        for _ in range(n):
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
            out.append(f"{y:04d}-{m:02d}")
        return out
    if all(_YEAR.match(l) for l in labels):
        return [str(int(labels[-1]) + i) for i in range(1, n + 1)]
    if all(_DAY.match(l) for l in labels):
        days = [datetime.date.fromisoformat(l) for l in labels]
        gaps = sorted((b - a).days for a, b in zip(days, days[1:]) if (b - a).days > 0)
        step = datetime.timedelta(days=gaps[len(gaps) // 2] if gaps else 1)
        return [(days[-1] + step * i).isoformat() for i in range(1, n + 1)]
    return None


def forecast(columns: list[str], rows: list[tuple], periods: int = DEFAULT_PERIODS) -> dict | None:
    """Extend a (date label, number) series by `periods` points, or None if
    the result isn't such a series."""
    if len(columns) != 2 or len(rows) < MIN_POINTS or not all(is_number(r[1]) for r in rows):
        return None
    labels = [str(r[0]) for r in rows]
    future_labels = _next_labels(labels, periods)
    if future_labels is None:
        return None

    y_all = np.array([float(r[1]) for r in rows])
    # A series usually starts/ends mid-period; fitting through a half-empty
    # first or last month would drag the line and fake a crash or surge.
    head, tail = partial_edges(list(y_all))
    keep = np.arange(head, len(y_all) - tail)
    dropped = labels[:head] + labels[len(labels) - tail:]
    x, y = keep.astype(float), y_all[keep]

    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - float(((y - fitted) ** 2).sum()) / ss_tot if ss_tot > 0 else 0.0

    future_x = np.arange(len(y_all), len(y_all) + periods)
    values = [max(0.0, float(slope * fx + intercept)) for fx in future_x]  # counts/sums can't go negative
    ints = all(isinstance(r[1], int) for r in rows)
    values = [int(round(v)) if ints else round(v, 2) for v in values]

    return {
        "periods": periods,
        "labels": future_labels,
        "values": values,
        "slope": float(slope),
        "r2": round(r2, 3),
        "method": "linear trend",
        "ignored": dropped,  # edge periods that looked incomplete and weren't fitted
        "head_partial": int(head),   # leading / trailing periods that looked incomplete
        "tail_partial": int(tail),
        # What the fitted line says each incomplete trailing period would be —
        # the chart draws its dashed line through these, not the partial values.
        "trailing_values": [max(0.0, float(slope * i + intercept)) for i in range(len(y_all) - tail, len(y_all))],
        "baseline": float(y[-3:].mean()),  # typical recent level, for "versus"
    }


def forecast_summary(columns: list[str], rows: list[tuple], fc: dict) -> str:
    metric = label_name(columns[1])
    last_pred = fc["values"][-1]
    baseline = fc["baseline"]
    direction = "rise" if fc["slope"] > 0 else "fall"
    sentence = (
        f"If the trend continues in a straight line, {metric} would {direction} "
        f"to about {fmt(last_pred)} by {fc['labels'][-1]}"
    )
    if baseline:
        sentence += f" ({(last_pred - baseline) / baseline * 100:+.0f}% versus the recent typical {fmt(round(baseline))})"
    if fc["r2"] < 0.3:
        sentence += ". The history is noisy and shows no clear direction, so treat this as very rough"
    else:
        sentence += ". A straight-line estimate, so a rough guide rather than a promise"
    if fc["ignored"]:
        sentence += f" (left out of the fit as incomplete: {', '.join(fc['ignored'])})"
    return sentence + "."
