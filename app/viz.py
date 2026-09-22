"""Turn a SQL result set into a Mermaid chart definition.

We keep this dead simple: no chart is *the* right answer for arbitrary
query results, so we use a small heuristic and always return valid
Mermaid source text that can be dropped straight into a markdown file,
a web page (via the mermaid.js CDN), or rendered with mermaid-py.

Heuristic:
- 1 row, 1 column            -> no chart, just the scalar value
- 2 columns, 2nd is numeric   -> bar chart (xychart-beta), 1st col = labels
- otherwise                  -> a markdown table (Mermaid has no generic
                                 table diagram, so we fall back to markdown)
"""
from typing import Any


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def build_chart(columns: list[str], rows: list[tuple[Any, ...]]) -> str:
    if not rows:
        return "_No rows returned._"

    if len(rows) == 1 and len(columns) == 1:
        return f"**{columns[0]}**: {rows[0][0]}"

    if len(columns) == 2 and all(_is_number(r[1]) for r in rows) and len(rows) <= 25:
        labels = [str(r[0]) for r in rows]
        values = [r[1] for r in rows]
        label_list = ", ".join(f'"{l}"' for l in labels)
        value_list = ", ".join(str(v) for v in values)
        return (
            "xychart-beta\n"
            f'    title "{columns[1]} by {columns[0]}"\n'
            f"    x-axis [{label_list}]\n"
            f'    y-axis "{columns[1]}"\n'
            f"    bar [{value_list}]"
        )

    # Fallback: markdown table (not a Mermaid diagram, but renders anywhere
    # Mermaid output gets shown, e.g. a doc or a simple web page).
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = "\n".join("| " + " | ".join(str(v) for v in row) + " |" for row in rows)
    return "\n".join([header, sep, body])


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
