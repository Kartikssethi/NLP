"""FastAPI app: speak (or type) a request, get SQL + results + a chart.

Run with:
    uvicorn app.main:app --reload

Endpoints:
    GET  /                    a small web UI: type or speak a query, see results
    GET  /health          liveness check
    GET  /schema           current DB schema (debugging aid)
    POST /query             {"text": "..."} -> SQL + results + mermaid charts
                              + a one-sentence answer
    POST /summarize           LLM answer line for result shapes /query can't
                              summarize itself
    POST /suggest-questions   starter questions for the selected tables
    POST /transcribe          upload an audio recording (e.g. from the browser's
                              mic) -> {"text": "..."} via faster-whisper
    POST /voice-query        records RECORD_SECONDS from the server's own mic,
                              transcribes it, then behaves like /query
    POST /upload-dataset      upload a CSV or Excel file -> its own table (one
                              per sheet for a workbook); any number can be
                              loaded, then joined in a query
    GET  /datasets            the uploaded tables (name, columns, row count)
    DELETE /datasets/{table}  remove an uploaded table
    GET  /chart               last chart rendered as a standalone HTML page
"""
import re
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.clean import CleanError, CleanPlan, message as clean_message, plan_clean_command
from app.db import (
    describe_uploaded_tables,
    drop_uploaded_table,
    execute_sql,
    get_schema,
    import_uploaded_file,
    list_tables,
    list_uploaded_tables,
    load_sales_data,
)
from app.nl2sql import (
    TABLE,
    OllamaUnavailable,
    UnsafeSQL,
    explain_sql,
    generate_diagram,
    parse,
    suggest_questions,
    summarize_with_llm,
    translate_question,
    wants_diagram,
)
from app.forecast import forecast, forecast_summary, periods_requested, wants_forecast
from app.insights import insights
from app.profile import build_er_diagram, profile_table
from app.summary import summarize
from app.viz import build_chart, chart_options, forecast_chart, is_mermaid_chart, pick_kind, wrap_html

app = FastAPI(title="Voice-to-SQL")

_INDEX_HTML = (Path(__file__).parent / "static" / "index.html").read_text()

# very small in-memory cache of the last chart so /chart has something to show
_last_chart: dict[str, str] = {"mermaid": "", "is_mermaid": False}


class HistoryTurn(BaseModel):
    text: str
    sql: str


class DrillIn(BaseModel):
    column: str  # the label column of the chart that was clicked
    value: str   # the bar/slice label


class QueryIn(BaseModel):
    text: str
    confirm: bool = False  # must be true to actually run a DELETE
    # Prior turns in this conversation (most recent last), so a follow-up
    # like "now break that down by region" can be resolved against what was
    # already asked/run. Only used by the Ollama fallback — see nl2sql.py.
    history: list[HistoryTurn] = []
    # Which tables to query — ["sales"] (default), or one or more uploaded
    # tables (optionally with "sales"); more than one means a join/merge.
    tables: list[str] = [TABLE]
    # Set when the user clicked one bar/slice of the previous chart.
    drill: DrillIn | None = None


class RunSqlIn(BaseModel):
    sql: str
    text: str = "Edited SQL"
    tables: list[str] = [TABLE]


class ExplainIn(BaseModel):
    sql: str
    text: str = ""
    tables: list[str] = [TABLE]


class SummarizeIn(BaseModel):
    text: str
    columns: list[str]
    rows: list[list]


class SuggestIn(BaseModel):
    tables: list[str] = [TABLE]


class QueryOut(BaseModel):
    text: str
    sql: str
    source: str  # "rule" or "ollama"
    columns: list[str]
    rows: list[list]
    chart: str
    is_mermaid: bool
    # Every chart type that suits this result ({"bar": mermaid, "line": ...,
    # "pie": ...}), so the UI can offer a switcher; `chart` is the one picked
    # as the best first view for the question, named by `chart_kind`.
    charts: dict[str, str] = {}
    chart_kind: str = ""
    # One-sentence plain-English answer computed from the rows; empty when the
    # result shape isn't covered (the UI then asks /summarize).
    summary: str = ""
    # Notable things found by arithmetic ("Units fell 38% in 2024-04 ..."), each
    # {"kind": "up" | "down" | "info", "text": ...}.
    insights: list[dict] = []
    # {"periods", "labels", "values", "r2", ...} when a forecast was asked for
    # and the result was a date series; the chart is then in charts["forecast"].
    forecast: dict | None = None
    requires_confirmation: bool = False
    # Replaces the generic "affects N rows" prompt for cleaning commands.
    confirm_message: str = ""
    # A plain statement instead of a table ("Removed 2 duplicate rows ...").
    notice: str = ""
    # True for an explanatory diagram (flowchart/ER/sequence diagram
    # describing the dataset's structure) rather than a data query result —
    # `sql`/`columns`/`rows` are meaningless in that case.
    is_diagram: bool = False


@app.on_event("startup")
def _startup() -> None:
    load_sales_data()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX_HTML


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/schema")
def schema() -> dict:
    return {"schema": get_schema()}


def _validated_tables(tables: list[str]) -> list[str]:
    """Table names come straight from the client and end up in SQL/PRAGMA
    statements, so only accept names that actually exist in the database."""
    available = set(list_tables())
    unknown = [t for t in tables if t not in available]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown dataset(s): {', '.join(unknown)}")
    return list(dict.fromkeys(tables)) or [TABLE]


def _build_result(
    text: str, sql: str, source: str, columns: list[str], rows: list[tuple], want_forecast: bool = False
) -> QueryOut:
    """Everything the UI shows for a result set: charts, the answer sentence,
    insights and (if asked) a forecast. Shared by questions, drill-downs and
    hand-edited SQL so they all look the same."""
    charts = chart_options(columns, rows)
    summary = summarize(columns, rows, sql) or ""
    fc = None
    if want_forecast:
        fc = forecast(columns, rows, periods_requested(text))
        if fc:
            charts["forecast"] = forecast_chart(columns, rows, fc)
            summary = forecast_summary(columns, rows, fc)
        else:
            summary = (
                "I couldn't forecast this: it needs a result with a date column (like month) and "
                "one number per date, with at least 4 dates."
            )

    chart_kind = pick_kind(text, charts)
    chart = charts[chart_kind] if chart_kind else build_chart(columns, rows)
    is_mermaid = is_mermaid_chart(chart)
    _last_chart["mermaid"] = chart
    _last_chart["is_mermaid"] = is_mermaid

    return QueryOut(
        text=text,
        sql=sql,
        source=source,
        columns=columns,
        rows=[list(r) for r in rows],
        chart=chart,
        is_mermaid=is_mermaid,
        charts=charts,
        chart_kind=chart_kind,
        summary=summary,
        insights=insights(columns, rows, sql),
        forecast=fc,
    )


def _run_clean(plan: CleanPlan, text: str, confirm: bool) -> QueryOut:
    """A cleaning command: nothing to do, or preview + confirm, or run it."""
    base = dict(text=text, source="clean", columns=[], rows=[], chart="", is_mermaid=False)
    if plan.nothing:
        return QueryOut(sql="", notice=plan.nothing, **base)
    if not confirm:
        columns, rows = execute_sql(plan.preview_sql) if plan.preview_sql else ([], [])
        return QueryOut(**{**base, "columns": columns, "rows": [list(r) for r in rows]},
                        sql=plan.sql, requires_confirmation=True,
                        confirm_message=clean_message(plan.ask, plan.count))
    columns, rows = execute_sql(plan.sql)
    changed = rows[0][0] if columns == ["rows_affected"] and rows[0][0] >= 0 else plan.count
    return QueryOut(sql=plan.sql, notice=clean_message(plan.done, changed), **base)


def _run_query(
    text: str,
    confirm: bool,
    history: list[HistoryTurn] | None = None,
    tables: list[str] | None = None,
    drill: DrillIn | None = None,
) -> QueryOut:
    tables = _validated_tables(tables or [TABLE])
    if wants_diagram(text):
        # A request like "explain this dataset with a flowchart" wants the
        # *structure* described, not a data value aggregated — never a SQL
        # question, so it skips parse()/execute_sql entirely.
        try:
            diagram = generate_diagram(text, tables=tables)
        except OllamaUnavailable as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        return QueryOut(
            text=text,
            sql="",
            source="ollama",
            columns=[],
            rows=[],
            chart=diagram,
            is_mermaid=True,
            is_diagram=True,
        )

    if not drill:
        # "remove duplicate rows", "fill empty price with the average", ...
        try:
            plan = plan_clean_command(text, tables)
        except CleanError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if plan:
            return _run_clean(plan, text, confirm)

    history_dicts = [h.model_dump() for h in history] if history else None
    try:
        parsed = parse(text, history=history_dicts, tables=tables, drill=drill.model_dump() if drill else None)
    except OllamaUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except UnsafeSQL as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if parsed.is_write and not confirm:
        # Don't execute the write yet — show what it would affect instead,
        # so the caller can resubmit with confirm=true once they've seen it.
        try:
            columns, rows = execute_sql(parsed.preview_sql)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"SQL error: {exc}\nSQL was: {parsed.preview_sql}")
        chart = build_chart(columns, rows)
        return QueryOut(
            text=text,
            sql=parsed.sql,
            source=parsed.source,
            columns=columns,
            rows=[list(r) for r in rows],
            chart=chart,
            is_mermaid=False,
            requires_confirmation=True,
        )

    try:
        columns, rows = execute_sql(parsed.sql)
    except Exception as exc:  # noqa: BLE001 - surface the DB error to the caller
        raise HTTPException(status_code=400, detail=f"SQL error: {exc}\nSQL was: {parsed.sql}")

    return _build_result(text, parsed.sql, parsed.source, columns, rows, want_forecast=wants_forecast(text))


@app.post("/query", response_model=QueryOut)
def query(payload: QueryIn) -> QueryOut:
    return _run_query(payload.text, payload.confirm, payload.history, payload.tables, payload.drill)


@app.post("/run-sql", response_model=QueryOut)
def run_sql(payload: RunSqlIn) -> QueryOut:
    """Run SQL the user edited by hand. Read-only twice over: it must be a
    SELECT/WITH, and the connection itself refuses writes."""
    sql = payload.sql.strip().rstrip(";").strip()
    if not re.match(r"(?is)(select|with)\b", sql):
        raise HTTPException(status_code=400, detail="Only SELECT queries can be run here.")
    try:
        columns, rows = execute_sql(sql, read_only=True)
    except Exception as exc:  # noqa: BLE001 - show the DB's own message so it can be fixed
        raise HTTPException(status_code=400, detail=f"SQL error: {exc}")
    return _build_result(payload.text, sql, "edited", columns, rows)


@app.get("/er-diagram")
def er_diagram(tables: str) -> dict:
    names = _validated_tables(tables.split(","))
    return {"diagram": build_er_diagram(names)}


@app.post("/summarize")
def summarize_result(payload: SummarizeIn) -> dict:
    if not payload.rows:
        return {"summary": "No rows matched."}
    try:
        return {"summary": summarize_with_llm(payload.text, payload.columns, payload.rows)}
    except OllamaUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# Suggestions only change when the tables' columns do, and they cost an LLM
# call, so remember them per schema.
_suggestion_cache: dict[str, list[str]] = {}


@app.post("/suggest-questions")
def suggestions(payload: SuggestIn) -> dict:
    tables = _validated_tables(payload.tables)
    key = get_schema(tables)
    if key not in _suggestion_cache:
        try:
            _suggestion_cache[key] = suggest_questions(tables)
        except OllamaUnavailable as exc:
            raise HTTPException(status_code=502, detail=str(exc))
    return {"questions": _suggestion_cache[key]}


@app.post("/explain-sql")
def explain(payload: ExplainIn) -> dict:
    try:
        explanation = explain_sql(payload.sql, payload.text, tables=_validated_tables(payload.tables))
    except OllamaUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"explanation": explanation}


@app.post("/voice-query", response_model=QueryOut)
def voice_query() -> QueryOut:
    from app.stt import record_and_transcribe

    text = record_and_transcribe()
    if not text:
        raise HTTPException(status_code=400, detail="Didn't catch any speech.")
    return _run_query(text, confirm=False)


@app.post("/transcribe")
async def transcribe(
    file: UploadFile, multilingual: bool = False, to_english: bool = False, tables: str = TABLE
) -> dict:
    """Transcribe an uploaded audio recording (e.g. from the browser's mic).

    `multilingual` transcribes Hindi/Hinglish (or anything) in the language
    spoken. `to_english` additionally has the LLM turn that transcript into an
    English question about `tables` (comma-separated) — done only for the final
    call, since the live captions during recording are re-run every few
    seconds. The response's `original` is what was actually heard.
    """
    from app.stt import transcribe_with_info

    suffix = Path(file.filename or "").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        original, language = transcribe_with_info(tmp_path, multilingual=multilingual)
    except Exception as exc:  # noqa: BLE001 - e.g. a truncated recording that can't be decoded
        raise HTTPException(status_code=400, detail=f"Couldn't read that recording: {exc}")
    finally:
        tmp_path.unlink(missing_ok=True)

    if not original:
        raise HTTPException(status_code=400, detail="Didn't catch any speech.")

    text = original
    if multilingual and to_english:
        try:
            text = translate_question(original, _validated_tables(tables.split(",")))
        except OllamaUnavailable:
            text = original  # still usable: the query step may cope, and the user sees what was heard
    return {"text": text, "original": original, "language": language}


@app.post("/upload-dataset")
async def upload_dataset(file: UploadFile) -> dict:
    """Load a CSV or Excel file as table(s) named after it: one table for a
    CSV, one per non-empty sheet for a workbook. Call once per file to load
    several side by side; they can then be joined in one question. Queries
    against uploaded tables always go through the Ollama fallback — see
    nl2sql.parse()'s `tables` handling."""
    filename = file.filename or "dataset.csv"
    suffix = Path(filename).suffix.lower()
    if suffix not in (".csv", ".xlsx", ".xlsm"):
        raise HTTPException(status_code=400, detail="Please upload a .csv or .xlsx file.")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        infos = import_uploaded_file(tmp_path, filename)
    except Exception as exc:  # noqa: BLE001 - surface a clean message to the caller
        raise HTTPException(status_code=400, detail=f"Couldn't load that file: {exc}")
    finally:
        tmp_path.unlink(missing_ok=True)

    for info in infos:
        info["profile"] = profile_table(info["table"])
    out: dict = {"datasets": infos}
    uploaded = list_uploaded_tables()
    if len(uploaded) > 1:
        # Everything uploaded so far, so the links between files are visible
        # the moment a second one arrives.
        out["er_diagram"] = build_er_diagram(uploaded)
    return out


@app.get("/datasets")
def datasets() -> dict:
    return {"datasets": describe_uploaded_tables()}


@app.delete("/datasets/{table}")
def delete_dataset(table: str) -> dict:
    try:
        drop_uploaded_table(table)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"deleted": table}


@app.get("/chart", response_class=HTMLResponse)
def chart() -> str:
    if not _last_chart["mermaid"]:
        return "<html><body>No query run yet. POST to /query first.</body></html>"
    return wrap_html(_last_chart["mermaid"], _last_chart["is_mermaid"])
