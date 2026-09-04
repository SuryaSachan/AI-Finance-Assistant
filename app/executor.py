"""Execute a QueryPlan against DuckDB and return a fully explainable result."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime

import numpy as np
import pandas as pd

from . import config, db, periods, sql_builder
from .plan_models import Metric, QueryPlan
from .schema_catalog import DATASETS


def jsonable(v):
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        return None if math.isnan(f) else round(f, 2)
    if isinstance(v, float):
        return None if math.isnan(v) else round(v, 2)
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if v is pd.NaT:
        return None
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def frame_to_rows(df: pd.DataFrame) -> list[dict]:
    return [{k: jsonable(v) for k, v in row.items()} for row in df.to_dict("records")]


@dataclass
class Execution:
    plan: QueryPlan
    start: date | None
    end: date | None
    period_label: str
    columns: list[str]
    rows: list[dict]
    totals: dict
    total_records: int
    sql: str
    sql_display: str
    supporting_columns: list[str] = field(default_factory=list)
    supporting_rows: list[dict] = field(default_factory=list)
    comparison: dict | None = None
    truncated: bool = False
    elapsed_ms: int = 0


def _grand_totals(plan: QueryPlan, start: date | None, end: date | None) -> tuple[dict, int]:
    ds = DATASETS[plan.dataset]
    flat = plan.model_copy(deep=True)
    flat.intent = "aggregate"
    flat.group_by = []
    flat.sort = None
    metrics = [m for m in plan.metrics] or [Metric(agg="sum", field=ds.amount_field)]
    if not any(m.agg == "sum" for m in metrics):
        metrics = metrics + [Metric(agg="sum", field=ds.amount_field)]
    flat.metrics = metrics
    sql, params = sql_builder.build(flat, start, end)
    df = db.query(sql, params)
    if df.empty:
        return {m.name: 0 for m in metrics} | {"record_count": 0}, 0
    row = {k: jsonable(v) for k, v in df.iloc[0].items()}
    return row, int(row.get("record_count") or 0)


def run(plan: QueryPlan) -> Execution:
    anchor = db.anchor_date()
    start, end, label = periods.resolve(plan.period.model_dump() if plan.period else None, anchor)

    t0 = pd.Timestamp.utcnow()
    sql, params = sql_builder.build(plan, start, end)
    df = db.query(sql, params)
    elapsed = int((pd.Timestamp.utcnow() - t0).total_seconds() * 1000)

    totals, total_records = _grand_totals(plan, start, end)

    ex = Execution(
        plan=plan,
        start=start,
        end=end,
        period_label=label,
        columns=list(df.columns),
        rows=frame_to_rows(df.head(config.MAX_ROWS)),
        totals=totals,
        total_records=total_records,
        sql=sql,
        sql_display=sql_builder.inline(sql, params),
        truncated=len(df) > config.MAX_ROWS or total_records > len(df),
        elapsed_ms=elapsed,
    )

    if plan.intent != "list" and total_records:
        s_sql, s_params = sql_builder.build_supporting_records(plan, start, end, limit=10)
        s_df = db.query(s_sql, s_params)
        ex.supporting_columns = list(s_df.columns)
        ex.supporting_rows = frame_to_rows(s_df)

    if plan.compare_to_previous and start and end:
        p_start, p_end = periods.previous_period(start, end)
        p_totals, p_records = _grand_totals(plan, p_start, p_end)
        metric_key = _primary_metric_key(plan, totals)
        cur = float(totals.get(metric_key) or 0)
        prev = float(p_totals.get(metric_key) or 0)
        ex.comparison = {
            "metric": metric_key,
            "current_period": periods.label_for(start, end),
            "previous_period": periods.label_for(p_start, p_end),
            "current_value": round(cur, 2),
            "previous_value": round(prev, 2),
            "absolute_change": round(cur - prev, 2),
            "percent_change": round((cur - prev) / abs(prev) * 100, 1) if prev else None,
            "current_records": total_records,
            "previous_records": p_records,
        }
    return ex


def _primary_metric_key(plan: QueryPlan, totals: dict) -> str:
    for m in plan.metrics:
        if m.name in totals:
            return m.name
    return "record_count"


def export_frame(plan: QueryPlan) -> pd.DataFrame:
    """Full (untruncated) result set for CSV/Excel export."""
    anchor = db.anchor_date()
    start, end, _ = periods.resolve(plan.period.model_dump() if plan.period else None, anchor)
    export_plan = plan.model_copy(deep=True)
    export_plan.limit = 100_000
    sql, params = sql_builder.build(export_plan, start, end)
    return db.query(sql, params)
