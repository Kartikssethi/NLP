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
    POST /upload-dataset      upload a CSV -> load it as the active dataset
    POST /use-sample-dataset   switch back to the built-in sales data
    GET  /chart               last chart rendered as a standalone HTML page
"""
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.db import execute_sql, get_schema, import_uploaded_csv, load_sales_data
from app.nl2sql import TABLE, OllamaUnavailable, parse
from app.viz import build_chart, wrap_html

app = FastAPI(title="Voice-to-SQL")

_INDEX_HTML = (Path(__file__).parent / "static" / "index.html").read_text()

# very small in-memory cache of the last chart so /chart has something to show
_last_chart: dict[str, str] = {"mermaid": "", "is_mermaid": False}


class HistoryTurn(BaseModel):
    text: str
    sql: str


class QueryIn(BaseModel):
    text: str
    confirm: bool = False  # must be true to actually run a DELETE
    # Prior turns in this conversation (most recent last), so a follow-up
    # like "now break that down by region" can be resolved against what was
    # already asked/run. Only used by the Ollama fallback — see nl2sql.py.
    history: list[HistoryTurn] = []
    # Which table to query — "sales" (default) or "user_data" after a CSV
    # upload. See app/db.py::UPLOADED_TABLE.
    table: str = TABLE


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


def _run_query(
    text: str, confirm: bool, history: list[HistoryTurn] | None = None, table: str = TABLE
) -> QueryOut:
    history_dicts = [h.model_dump() for h in history] if history else None
    try:
        parsed = parse(text, history=history_dicts, table=table)
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

    chart = build_chart(columns, rows)
    is_mermaid = chart.startswith("xychart-beta")
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
    return _run_query(payload.text, payload.confirm, payload.history, payload.table)


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


@app.post("/upload-dataset")
async def upload_dataset(file: UploadFile) -> dict:
    """Load a user-provided CSV as the active dataset (replaces any
    previously uploaded one). Queries against it always go through the
    Ollama fallback — see nl2sql.parse()'s `table` handling."""
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file.")

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        info = import_uploaded_csv(tmp_path, file.filename or "dataset.csv")
    except Exception as exc:  # noqa: BLE001 - surface a clean message to the caller
        raise HTTPException(status_code=400, detail=f"Couldn't load that CSV: {exc}")
    finally:
        tmp_path.unlink(missing_ok=True)

    return info


@app.post("/use-sample-dataset")
def use_sample_dataset() -> dict:
    """No-op marker endpoint: the frontend just needs to know the default
    table name to switch back to. Kept as a real endpoint (rather than a
    frontend-only constant) so schema/health checks can hit it too."""
    return {"table": TABLE}


@app.get("/chart", response_class=HTMLResponse)
def chart() -> str:
    if not _last_chart["mermaid"]:
        return "<html><body>No query run yet. POST to /query first.</body></html>"
    return wrap_html(_last_chart["mermaid"], _last_chart["is_mermaid"])
