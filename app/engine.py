"""Orchestration: question in, grounded + explainable answer out."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from rapidfuzz import process

from . import anomalies as anomaly_mod
from . import answer as answer_mod
from . import db, executor, periods
from .llm import Usage, llm
from .plan_models import QueryPlan
from .planner import make_plan
from .schema_catalog import DATASETS
from .sql_builder import PlanError

MAX_HISTORY = 8


@dataclass
class Session:
    id: str
    history: list[dict] = field(default_factory=list)
    last_plan: QueryPlan | None = None
    last_answer_plan: QueryPlan | None = None


class SessionStore:
    def __init__(self) -> None:
        self._data: dict[str, Session] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str | None) -> Session:
        with self._lock:
            if not session_id or session_id not in self._data:
                session_id = session_id or uuid.uuid4().hex[:12]
                self._data[session_id] = Session(id=session_id)
            return self._data[session_id]

    def reset(self, session_id: str) -> None:
        with self._lock:
            self._data.pop(session_id, None)


sessions = SessionStore()

CAPABILITIES = (
    "I can answer questions about spend and transactions, vendor payouts, and reconciliation "
    "status - filtered by vendor, category, department, account, payment method, status or date range."
)


def _refusal(session: Session, question: str, text: str, status: str, usage: Usage, reasons: list[str]) -> dict:
    return {
        "session_id": session.id,
        "question": question,
        "status": status,
        "answer": text,
        "answer_source": "deterministic",
        "confidence": {"level": "low", "score": 0.3, "reasons": reasons},
        "table": {"columns": [], "rows": []},
        "supporting": {"columns": [], "rows": []},
        "comparison": None,
        "anomalies": [],
        "explain": {"plan": None, "sql": None, "assumptions": [], "issues": reasons, "plan_source": None},
        "usage": usage.summary(),
        "can_export": False,
    }


def ask(question: str, session_id: str | None = None) -> dict:
    t0 = time.perf_counter()
    session = sessions.get(session_id)
    usage = Usage()
    question = (question or "").strip()
    if not question:
        return _refusal(session, question, "Ask me something about the finance data. " + CAPABILITIES,
                        "clarify", usage, ["Empty question."])

    pr = make_plan(question, history=session.history, previous_plan=session.last_plan, usage=usage)
    plan = pr.plan

    if pr.unknown_entity:
        suggestions = [m[0] for m in process.extract(pr.unknown_entity, db.vendor_names(), limit=3)]
        text = (
            f'I could not find "{pr.unknown_entity}" anywhere in the finance data, so I have nothing to '
            f"report for it and I will not guess a number. Closest names on file: "
            f"{', '.join(suggestions)}."
        )
        return _refusal(session, question, text, "no_data", usage,
                        [f'"{pr.unknown_entity}" does not exist in the dataset.'])

    if plan.intent == "clarify":
        text = plan.clarification or "Could you narrow that down - which vendor, period or category do you mean?"
        return _refusal(session, question, text, "clarify", usage, ["The question was ambiguous."])

    if plan.intent == "unsupported":
        text = f"That is outside what this dataset can answer. {CAPABILITIES}"
        return _refusal(session, question, text, "unsupported", usage,
                        ["The question cannot be answered from the available schema."])

    try:
        ex = executor.run(plan)
    except (PlanError, periods.PeriodError) as exc:
        return _refusal(session, question, f"I could not turn that into a safe query: {exc}. {CAPABILITIES}",
                        "unsupported", usage, [str(exc)])

    found_anomalies: list[dict] = []
    if ex.total_records and ex.start and ex.end and (ex.end - ex.start).days <= 45:
        found_anomalies = anomaly_mod.detect(plan, ex.start, ex.end, limit=3)

    ans = answer_mod.narrate(question, ex, pr, found_anomalies, usage)
    conf = answer_mod.confidence(ex, pr, ans)

    session.history.append({"role": "user", "content": question})
    session.history.append({"role": "assistant", "content": ans.text})
    session.history[:] = session.history[-MAX_HISTORY:]
    session.last_plan = plan
    session.last_answer_plan = plan

    return {
        "session_id": session.id,
        "question": question,
        "status": "ok" if ex.total_records else "no_data",
        "answer": ans.text,
        "answer_source": ans.source,
        "confidence": conf,
        "period": ex.period_label,
        "date_range": [ex.start.isoformat() if ex.start else None, ex.end.isoformat() if ex.end else None],
        "totals": ex.totals,
        "table": {"columns": ex.columns, "rows": ex.rows, "truncated": ex.truncated},
        "supporting": {"columns": ex.supporting_columns, "rows": ex.supporting_rows},
        "comparison": ex.comparison,
        "anomalies": found_anomalies,
        "explain": {
            "plan": plan.model_dump(exclude_none=True),
            "plan_source": pr.source,
            "raw_model_output": pr.raw,
            "sql": ex.sql_display,
            "assumptions": pr.notes,
            "issues": pr.issues,
            "dataset": DATASETS[plan.dataset].label,
            "matching_records": ex.total_records,
            "query_ms": ex.elapsed_ms,
            "guardrail": {
                "triggered": ans.guardrail_triggered,
                "rejected_numbers": ans.rejected_numbers,
                "policy": "Every number in the reply is checked against the SQL result before it is shown.",
            },
        },
        "usage": usage.summary() | {"llm_available": llm.health(), "total_ms": int((time.perf_counter() - t0) * 1000)},
        "can_export": bool(ex.total_records),
    }
