"""FastAPI app: speak (or type) a request, get SQL + results + a chart.

Run with:
    uvicorn app.main:app --reload

Endpoints:
    GET  /                    a small web UI: type or speak a query, see results
    GET  /health          liveness check
    GET  /schema           current DB schema (debugging aid)
    POST /query             {"text": "..."} -> SQL + results + mermaid chart
    POST /transcribe          upload an audio recording (e.g. from the browser's
                              mic) -> {"text": "..."} via faster-whisper
    POST /voice-query        records RECORD_SECONDS from the server's own mic,
                              transcribes it, then behaves like /query
    GET  /chart               last chart rendered as a standalone HTML page
"""
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.db import execute_sql, get_schema, load_sales_data
from app.nl2sql import OllamaUnavailable, parse
from app.viz import build_chart, wrap_html

app = FastAPI(title="Voice-to-SQL")

_INDEX_HTML = (Path(__file__).parent / "static" / "index.html").read_text()

# very small in-memory cache of the last chart so /chart has something to show
_last_chart: dict[str, str] = {"mermaid": "", "is_mermaid": False}


class QueryIn(BaseModel):
    text: str
    confirm: bool = False  # must be true to actually run a DELETE


class QueryOut(BaseModel):
    text: str
    sql: str
    source: str  # "rule" or "ollama"
    columns: list[str]
    rows: list[list]
    chart: str
    is_mermaid: bool
    requires_confirmation: bool = False


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


def _run_query(text: str, confirm: bool) -> QueryOut:
    try:
        parsed = parse(text)
    except OllamaUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc))

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

    is_mermaid = len(columns) == 2 and len(rows) > 1
    chart = build_chart(columns, rows)
    _last_chart["mermaid"] = chart
    _last_chart["is_mermaid"] = is_mermaid

    return QueryOut(
        text=text,
        sql=parsed.sql,
        source=parsed.source,
        columns=columns,
        rows=[list(r) for r in rows],
        chart=chart,
        is_mermaid=is_mermaid,
    )


@app.post("/query", response_model=QueryOut)
def query(payload: QueryIn) -> QueryOut:
    return _run_query(payload.text, payload.confirm)


@app.post("/voice-query", response_model=QueryOut)
def voice_query() -> QueryOut:
    from app.stt import record_and_transcribe

    text = record_and_transcribe()
    if not text:
        raise HTTPException(status_code=400, detail="Didn't catch any speech.")
    return _run_query(text, confirm=False)


@app.post("/transcribe")
async def transcribe(file: UploadFile) -> dict:
    """Transcribe an uploaded audio recording (e.g. from the browser's mic)."""
    from app.stt import transcribe_file

    suffix = Path(file.filename or "").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        text = transcribe_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    if not text:
        raise HTTPException(status_code=400, detail="Didn't catch any speech.")
    return {"text": text}


@app.get("/chart", response_class=HTMLResponse)
def chart() -> str:
    if not _last_chart["mermaid"]:
        return "<html><body>No query run yet. POST to /query first.</body></html>"
    return wrap_html(_last_chart["mermaid"], _last_chart["is_mermaid"])
