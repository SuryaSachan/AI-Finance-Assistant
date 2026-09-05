"""Statistical anomaly call-outs.

A counterparty's current-period total is compared against its own trailing monthly
history. Nothing here is LLM-generated: the flag, the z-score and the baseline
all come out of SQL.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from . import db
from .plan_models import QueryPlan
from .schema_catalog import DATASETS
from .sql_builder import where_clause

MIN_HISTORY_MONTHS = 6
Z_THRESHOLD = 2.5


def detect(plan: QueryPlan, start: date | None, end: date | None, limit: int = 5) -> list[dict]:
    ds = DATASETS[plan.dataset]
    entity = ds.entity_field
    if not entity or entity not in ds.field_map or not ds.date_field or not start or not end:
        return []

    where, params = where_clause(plan, None, None)
    history_start = (pd.Timestamp(start) - pd.DateOffset(months=13)).date()

    sql = f"""
    WITH monthly AS (
        SELECT "{entity}" AS entity,
               strftime("{ds.date_field}", '%Y-%m') AS ym,
               sum("{ds.amount_field}") AS total
        FROM {ds.view}
        WHERE ({where}) AND "{ds.date_field}" BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        GROUP BY 1, 2
    ),
    baseline AS (
        SELECT entity, avg(total) AS mu, stddev_samp(total) AS sd, count(*) AS months
        FROM monthly WHERE ym < ? GROUP BY 1
    ),
    current AS (
        SELECT "{entity}" AS entity, sum("{ds.amount_field}") AS total, count(*) AS records
        FROM {ds.view}
        WHERE ({where}) AND "{ds.date_field}" BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        GROUP BY 1
    )
    SELECT c.entity, c.total, c.records, b.mu AS baseline_avg, b.sd AS baseline_sd,
           b.months AS history_months,
           (c.total - b.mu) / nullif(b.sd, 0) AS z_score
    FROM current c JOIN baseline b USING (entity)
    WHERE b.months >= {MIN_HISTORY_MONTHS}
      AND b.sd > 0
      AND (c.total - b.mu) / nullif(b.sd, 0) >= {Z_THRESHOLD}
    ORDER BY z_score DESC
    LIMIT {limit}
    """
    args = (
        params
        + [history_start.isoformat(), (pd.Timestamp(start) - pd.Timedelta(days=1)).date().isoformat()]
        + [start.strftime("%Y-%m")]
        + params
        + [start.isoformat(), end.isoformat()]
    )
    try:
        df = db.query(sql, args)
    except Exception:  # noqa: BLE001 - anomaly detection is best-effort
        return []
    if df.empty:
        return []

    out = []
    for r in df.to_dict("records"):
        baseline = float(r["baseline_avg"] or 0)
        total = float(r["total"] or 0)
        out.append(
            {
                "entity": r["entity"],
                "entity_label": entity.replace("_", " "),
                "period_total": round(total, 2),
                "baseline_monthly_avg": round(baseline, 2),
                "times_baseline": round(total / baseline, 1) if baseline else None,
                "z_score": round(float(r["z_score"]), 1),
                "history_months": int(r["history_months"]),
                "records": int(r["records"]),
            }
        )
    return out
