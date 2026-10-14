"""Sanity-check the benchmark before trusting it: every gold query must run,
return something, and — for ORDER BY ... LIMIT n — not tie at the cutoff (a tie
would make "the" correct answer arbitrary).

    NLP_DB_PATH=eval/eval.db python -m eval.validate
"""
import os
import re

os.environ.setdefault("NLP_DB_PATH", "eval/eval.db")

from app.db import execute_sql  # noqa: E402
from eval.benchmark import all_questions  # noqa: E402
from eval.heldout import heldout_questions  # noqa: E402

ORDER_LIMIT = re.compile(r"^(?P<head>SELECT .*?) (?P<from>FROM .*) ORDER BY (?P<expr>.+?) (?P<dir>DESC|ASC) LIMIT (?P<n>\d+)$")


def tie_at_cutoff(sql: str) -> str | None:
    m = ORDER_LIMIT.match(sql)
    if not m:
        return None
    n = int(m["n"])
    if re.fullmatch(r"\w+", m["expr"]) and f" AS {m['expr']}" in m["head"]:
        # sorting by a select-list alias: that alias is already the key (the last column)
        probe = f"{m['head']} {m['from']} ORDER BY {m['expr']} {m['dir']} LIMIT {n + 1}"
    else:
        probe = f"{m['head']}, {m['expr']} AS _k {m['from']} ORDER BY {m['expr']} {m['dir']} LIMIT {n + 1}"
    _, rows = execute_sql(probe, read_only=True)
    if len(rows) <= n:
        return None
    return f"TIE at cutoff (key {rows[n - 1][-1]!r} == {rows[n][-1]!r})" if rows[n - 1][-1] == rows[n][-1] else None


def main() -> int:
    problems = 0
    ids = set()
    for q in all_questions() + heldout_questions():
        assert q["id"] not in ids, f"duplicate id {q['id']}"
        ids.add(q["id"])
        try:
            cols, rows = execute_sql(q["gold_sql"], read_only=True)
        except Exception as exc:  # noqa: BLE001
            print(f"{q['id']}: ERROR {exc}")
            problems += 1
            continue
        flags = []
        if not rows:
            flags.append("EMPTY RESULT")
        elif len(rows) == 1 and all(v is None for v in rows[0]):
            flags.append("NULL RESULT")
        tie = tie_at_cutoff(q["gold_sql"])
        if tie:
            flags.append(tie)
        shown = rows[:3] if len(rows) > 3 else rows
        print(f"{q['id']:4} {len(rows):4} rows {'  <-- ' + '; '.join(flags) if flags else ''}  {shown if len(str(shown)) < 110 else str(shown)[:110] + '...'}")
        problems += bool(flags)
    print(f"\n{len(ids)} questions, {problems} with problems")
    return problems


if __name__ == "__main__":
    raise SystemExit(main())
