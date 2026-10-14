"""Turn a SQL result set into Mermaid chart definitions.

We keep this dead simple: no chart is *the* right answer for arbitrary
query results, so we use a small heuristic and always return valid
Mermaid source text that can be dropped straight into a markdown file,
a web page (via the mermaid.js CDN), or rendered with mermaid-py.

A "chartable" result is exactly two columns whose second is numeric (a label
and a measure). For one, `chart_options()` offers every chart type that stays
legible, so the UI can let the user switch between them:
- bar  (xychart-beta)  <= 25 rows; anchored at zero so bars compare honestly
- line (xychart-beta)  >= 3 rows; downsampled to stay readable (a trend)
- pie                  2-12 positive slices (a share of a whole)

Everything else (several columns, text-only, ...) falls back to a markdown
table, since Mermaid has no generic table diagram. 1x1 results are a scalar.
"""
import re
from typing import Any

_MAX_LINE_POINTS = 15  # xychart-beta has no label rotation; more than this
                        # overlaps on a typical chat-width chart
_MAX_BARS = 25
_MAX_PIE_SLICES = 12


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _label(v: Any) -> str:
    # A double quote or newline inside a label would end the quoted string
    # (or the line) in the Mermaid source.
    if v is None:
        return "(empty)"
    return str(v).replace('"', "'").replace("\n", " ")


def _num(v: Any) -> Any:
    return round(v, 2) if isinstance(v, float) else v


def _downsample(labels: list[str], values: list[Any], max_points: int) -> tuple[list[str], list[Any]]:
    if len(labels) <= max_points:
        return labels, values
    step = len(labels) / max_points
    idx = [int(i * step) for i in range(max_points)]
    return [labels[i] for i in idx], [values[i] for i in idx]


def _xy_chart(kind: str, title: str, y_title: str, labels: list[str], values: list[Any], y_range: str = "") -> str:
    label_list = ", ".join(f'"{l}"' for l in labels)
    value_list = ", ".join(str(v) for v in values)
    return (
        "xychart-beta\n"
        f'    title "{title}"\n'
        f"    x-axis [{label_list}]\n"
        f'    y-axis "{y_title}"{y_range}\n'
        f"    {kind} [{value_list}]"
    )


def chart_options(columns: list[str], rows: list[tuple[Any, ...]]) -> dict[str, str]:
    """Every chart type that suits this result, as {kind: mermaid source}.
    Empty when the result isn't a label + number pair."""
    if len(columns) != 2 or not rows or not all(_is_number(r[1]) for r in rows):
        return {}

    labels = [_label(r[0]) for r in rows]
    values = [_num(r[1]) for r in rows]
    label_col, value_col = _label(columns[0]), _label(columns[1])
    options: dict[str, str] = {}

    if len(rows) <= _MAX_BARS:
        # Mermaid auto-ranges the axis to the data, which makes bars of
        # 2180 vs 2720 look like "nearly empty" vs "full". Bars must be
        # anchored at zero to be read honestly.
        lo, hi = min(0, min(values)), max(0, max(values))
        y_range = f" {lo} --> {hi}" if hi > lo else ""
        options["bar"] = _xy_chart("bar", f"{value_col} by {label_col}", value_col, labels, values, y_range)

    if len(rows) >= 3:
        ds_labels, ds_values = _downsample(labels, values, _MAX_LINE_POINTS)
        options["line"] = _xy_chart("line", f"{value_col} over {label_col}", value_col, ds_labels, ds_values)

    slices = [(l, v) for l, v in zip(labels, values) if v > 0]
    if 2 <= len(slices) <= _MAX_PIE_SLICES and len(slices) == len(rows):
        body = "\n".join(f'    "{l}" : {v}' for l, v in slices)
        options["pie"] = f"pie title {value_col} by {label_col}\n{body}"

    return options


def _sample_indices(n: int, m: int) -> list[int]:
    """`m` evenly spaced indices into a series of length `n`, always keeping
    the first and last (the forecast has to start from the real last point)."""
    if n <= m:
        return list(range(n))
    return sorted({round(i * (n - 1) / (m - 1)) for i in range(m)})


def forecast_chart(columns: list[str], rows: list[tuple[Any, ...]], fc: dict) -> str:
    """History plus the forecast as two lines over one axis. Mermaid can't draw
    dashes or gaps, so: the first line is history + forecast (starting on top
    of the real data so it connects), the second is the history alone, drawn
    over it. Only the forecast part of the first line stays visible; the page
    dashes it after rendering.

    Incomplete edge periods (see forecast()) are not drawn as history: a
    half-empty last month would show as a fake crash with the dashed line
    leaping up from it. The dashed line instead passes through the value the
    fit gives for that period.
    """
    head, tail = fc.get("head_partial", 0), fc.get("tail_partial", 0)
    kept = rows[head:len(rows) - tail]
    idx = _sample_indices(len(kept), max(_MAX_LINE_POINTS - len(fc["labels"]) - tail, 6))
    hist_labels = [_label(kept[i][0]) for i in idx]
    hist_values = [_num(kept[i][1]) for i in idx]
    future_labels = [_label(l) for l in fc["labels"]]
    value_col, label_col = _label(columns[1]), _label(columns[0])

    gap_labels = [_label(r[0]) for r in rows[len(rows) - tail:]] if tail else []
    gap_values = [_num(round(v, 2)) for v in fc.get("trailing_values", [])] if tail else []

    labels = ", ".join(f'"{l}"' for l in hist_labels + gap_labels + future_labels)
    with_forecast = ", ".join(str(v) for v in hist_values + gap_values + list(fc["values"]))
    history = ", ".join(str(v) for v in hist_values)
    return (
        "xychart-beta\n"
        f'    title "{value_col} over {label_col} (forecast to {future_labels[-1]})"\n'
        f"    x-axis [{labels}]\n"
        f'    y-axis "{value_col}"\n'
        f"    line [{with_forecast}]\n"
        f"    line [{history}]"
    )


_PIE_WORDS = re.compile(r"\b(pie|share|shares|percent|percentage|proportion|portion|split|composition)\b", re.I)
_LINE_WORDS = re.compile(r"\b(line chart|line graph|line plot|trend|trends|over time|timeline|time series)\b", re.I)
_BAR_WORDS = re.compile(r"\b(bar chart|bar graph|bars?|histogram)\b", re.I)


def pick_kind(question: str, options: dict[str, str]) -> str:
    """Which of `options` to show first. An explicitly named chart type wins;
    otherwise share-of-whole phrasing means pie, trend phrasing means line,
    and bar is the default comparison chart."""
    if not options:
        return ""
    if "forecast" in options:
        return "forecast"
    for words, kind in ((_PIE_WORDS, "pie"), (_LINE_WORDS, "line"), (_BAR_WORDS, "bar")):
        if kind in options and words.search(question):
            return kind
    return "bar" if "bar" in options else next(iter(options))


def build_chart(columns: list[str], rows: list[tuple[Any, ...]], kind: str | None = None) -> str:
    if not rows:
        return "_No rows returned._"

    if len(rows) == 1 and len(columns) == 1:
        return f"**{columns[0]}**: {rows[0][0]}"

    options = chart_options(columns, rows)
    if options:
        return options[kind] if kind in options else options["bar" if "bar" in options else "line"]

    # Fallback: markdown table (not a Mermaid diagram, but renders anywhere
    # Mermaid output gets shown, e.g. a doc or a simple web page).
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = "\n".join("| " + " | ".join(str(v) for v in row) + " |" for row in rows)
    return "\n".join([header, sep, body])


def is_mermaid_chart(chart: str) -> bool:
    return chart.startswith(("xychart-beta", "pie "))


def wrap_html(mermaid_or_markdown: str, is_mermaid: bool) -> str:
    """Wrap chart output in a minimal standalone HTML page for quick viewing."""
    if not is_mermaid:
        # naive markdown-table -> html table isn't worth a dependency here;
        # just show it preformatted.
        return f"<html><body><pre>{mermaid_or_markdown}</pre></body></html>"
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script></head>
<body>
<pre class="mermaid">
{mermaid_or_markdown}
</pre>
<script>mermaid.initialize({{ startOnLoad: true }});</script>
</body>
</html>"""
