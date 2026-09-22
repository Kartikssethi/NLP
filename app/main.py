"""FastAPI app: speak (or type) a request, get SQL + results + a chart.

Run with:
    uvicorn app.main:app --reload

Endpoints:
    GET  /health          liveness check
    GET  /schema           current DB schema (debugging aid)
    POST /query             {"text": "..."} -> SQL + results + mermaid chart
    POST /voice-query        records RECORD_SECONDS from the server's mic,
                              transcribes it, then behaves like /query
    GET  /chart               last chart rendered as a standalone HTML page
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.db import execute_sql, get_schema, seed_sample_db
from app.nl2sql import parse
from app.viz import build_chart, wrap_html

app = FastAPI(title="Voice-to-SQL")

# very small in-memory cache of the last chart so /chart has something to show
_last_chart: dict[str, str] = {"mermaid": "", "is_mermaid": False}


class QueryIn(BaseModel):
    text: str


class QueryOut(BaseModel):
    text: str
    sql: str
    source: str  # "rule" or "ollama"
    columns: list[str]
    rows: list[list]
    chart: str
    is_mermaid: bool


@app.on_event("startup")
def _startup() -> None:
    seed_sample_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/schema")
def schema() -> dict:
    return {"schema": get_schema()}


def _run_query(text: str) -> QueryOut:
    parsed = parse(text)
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
    return _run_query(payload.text)


@app.post("/voice-query", response_model=QueryOut)
def voice_query() -> QueryOut:
    from app.stt import record_and_transcribe

    text = record_and_transcribe()
    if not text:
        raise HTTPException(status_code=400, detail="Didn't catch any speech.")
    return _run_query(text)


@app.get("/chart", response_class=HTMLResponse)
def chart() -> str:
    if not _last_chart["mermaid"]:
        return "<html><body>No query run yet. POST to /query first.</body></html>"
    return wrap_html(_last_chart["mermaid"], _last_chart["is_mermaid"])
