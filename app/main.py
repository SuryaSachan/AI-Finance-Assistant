"""FastAPI application: chat API + static chat UI."""
# Reloaded with live MySQL dataset
from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, engine, executor
from .llm import llm
from .schema_catalog import DATASETS

app = FastAPI(title="Finance Assistant", version="1.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

SAMPLE_QUESTIONS = [
    "How much did we pay out last month?",
    "Which transactions are still unreconciled?",
    "How does that compare to the month before?",
    "Top 5 counterparties by spend this year",
    "How much did we pay Tata Capital Limited last quarter?",
    "Show UPI spend by month year to date",
    "What is the total balance across HDFC accounts?",
    "Any unusually large payments last month?",
]


class AskRequest(BaseModel):
    question: str
    session_id: str | None = None


@app.get("/api/health")
def health() -> dict:
    try:
        stats = db.stats()
        db_ok = True
    except Exception as exc:  # noqa: BLE001
        stats, db_ok = {"error": str(exc)}, False
    return {
        "status": "ok" if db_ok else "degraded",
        "database": stats,
        "llm": {
            "provider": config.LLM_PROVIDER,
            "model": config.LLM_MODEL,
            "fallback_model": config.LLM_MODEL_FALLBACK or None,
            "reachable": llm.health(),
            "mode": "llm" if llm.health() else "deterministic rule parser (no LLM reachable)",
        },
    }


@app.get("/api/schema")
def schema() -> dict:
    return {
        "datasets": [
            {
                "key": ds.key,
                "label": ds.label,
                "description": ds.desc,
                "fields": [
                    {"name": f.name, "type": f.kind, "description": f.desc, "values": list(f.values)}
                    for f in ds.fields
                ],
            }
            for ds in DATASETS.values()
        ],
        "counterparties": list(db.counterparty_names())[:500],
    }


@app.get("/api/samples")
def samples() -> dict:
    return {"questions": SAMPLE_QUESTIONS}


@app.post("/api/ask")
def ask(req: AskRequest) -> dict:
    try:
        return engine.ask(req.question, req.session_id)
    except db.DatabaseMissing as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/reset")
def reset(req: AskRequest) -> dict:
    if req.session_id:
        engine.sessions.reset(req.session_id)
    return {"ok": True}


@app.get("/api/records")
def records(session_id: str, limit: int = 10) -> dict:
    """Sample of the raw rows behind the last answer, fetched on demand."""
    session = engine.sessions.get(session_id)
    if not session.last_answer_plan:
        raise HTTPException(status_code=404, detail="Nothing to show yet for this session.")
    columns, rows = executor.supporting_records(session.last_answer_plan, limit=limit)
    return {"columns": columns, "rows": rows}


@app.get("/api/export")
def export(session_id: str, fmt: str = "csv"):
    session = engine.sessions.get(session_id)
    if not session.last_answer_plan:
        raise HTTPException(status_code=404, detail="Nothing to export yet for this session.")
    df = executor.export_frame(session.last_answer_plan)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if fmt == "xlsx":
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="breakdown")
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="finance-breakdown-{stamp}.xlsx"'},
        )
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="finance-breakdown-{stamp}.csv"'},
    )


if config.WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(config.WEB_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(config.WEB_DIR / "index.html"))
