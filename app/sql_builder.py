"""Turn a validated QueryPlan into parameterised DuckDB SQL.

Only identifiers that exist in `schema_catalog` can ever reach the query
string; every literal is bound as a parameter. That makes this layer both
injection-proof and the guarantee that answers are schema-grounded.
"""
from __future__ import annotations

from datetime import date

from .plan_models import Filter, Metric, QueryPlan
from .schema_catalog import Dataset, DATASETS

AGG_SQL = {
    "sum": "sum({col})",
    "count": "count(*)",
    "avg": "avg({col})",
    "min": "min({col})",
    "max": "max({col})",
    "count_distinct": "count(DISTINCT {col})",
}

def _can_use_rollup(plan: QueryPlan, ds: Dataset) -> bool:
    if plan.dataset != "transactions":
        return False
    if plan.intent not in ("aggregate", "trend"):
        return False
    if plan.period and plan.period.kind in ("last_n_days", "custom"):
        return False
    
    # Check if any filters or groupings use cols not in the rollup
    rollup_cols = {
        "account_id", "txn_month", "transaction_type", "counterparty", 
        "account_number_masked", "entity_id", "program_id", "bank_code", "bank_name"
    }
    
    for g in plan.group_by:
        if g not in rollup_cols:
            return False
            
    for f in plan.filters:
        if f.field not in rollup_cols:
            return False
            
    # count_distinct is impossible without raw rows or HLL
    if plan.metrics:
        for m in plan.metrics:
            if m.agg == "count_distinct":
                return False
                
    return True



class PlanError(ValueError):
    """Raised when a plan references something outside the schema."""


def _col(ds: Dataset, name: str) -> str:
    if name not in ds.field_map:
        raise PlanError(f"'{name}' is not a field of {ds.key}")
    return f'"{name}"'


def _metric_expr(ds: Dataset, m: Metric, use_rollup: bool = False) -> str:
    if m.agg not in AGG_SQL:
        raise PlanError(f"unsupported aggregation '{m.agg}'")
    col = "*" if m.agg == "count" else _col(ds, m.field)
    
    if use_rollup:
        if m.agg == "sum":
            expr = "sum(sum_amount)"
        elif m.agg == "count":
            expr = "sum(record_count)"
        elif m.agg == "min":
            expr = "min(min_amount)"
        elif m.agg == "max":
            expr = "max(max_amount)"
        elif m.agg == "avg":
            expr = "(sum(sum_amount) / sum(record_count))"
        else:
            raise PlanError(f"unsupported rollup aggregation '{m.agg}'")
        return f'{expr} AS "{m.name}"'
        
    return f'{AGG_SQL[m.agg].format(col=col)} AS "{m.name}"'


def _filter_sql(ds: Dataset, f: Filter, params: list) -> str:
    col = _col(ds, f.field)
    kind = ds.field_map[f.field].kind
    op = f.op

    if op in ("is_null", "not_null"):
        return f"{col} IS {'NULL' if op == 'is_null' else 'NOT NULL'}"

    if op in ("in", "not_in"):
        values = f.value if isinstance(f.value, (list, tuple)) else [f.value]
        if not values:
            raise PlanError(f"empty value list for filter on {f.field}")
        params.extend(values)
        neg = "NOT " if op == "not_in" else ""
        if kind in ("text", "enum", "id"):
            placeholders = ", ".join("lower(?)" for _ in values)
            return f"lower({col}) {neg}IN ({placeholders})"
        placeholders = ", ".join("?" for _ in values)
        return f"{col} {neg}IN ({placeholders})"

    if op == "between":
        values = f.value if isinstance(f.value, (list, tuple)) else []
        if len(values) != 2:
            raise PlanError(f"'between' needs two values for {f.field}")
        params.extend(values)
        ph = "CAST(? AS DATE)" if kind == "date" else "?"
        return f"{col} BETWEEN {ph} AND {ph}"

    if op == "contains":
        params.append(f"%{f.value}%")
        return f"lower({col}) LIKE lower(?)"

    sym = {"eq": "=", "neq": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
    params.append(f.value)
    if kind == "date":
        return f"{col} {sym} CAST(? AS DATE)"
    if kind in ("text", "enum", "id") and op in ("eq", "neq"):
        return f"lower({col}) {sym} lower(?)"
    return f"{col} {sym} ?"


def _where(ds: Dataset, plan: QueryPlan, start: date | None, end: date | None, params: list, use_rollup: bool = False) -> str:
    clauses: list[str] = []
    if start and end and ds.date_field:
        if use_rollup:
            clauses.append(f'txn_month BETWEEN ? AND ?')
            params.extend([start.strftime('%Y-%m'), end.strftime('%Y-%m')])
        else:
            clauses.append(f'"{ds.date_field}" BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)')
            params.extend([start.isoformat(), end.isoformat()])
    for f in plan.filters:
        clauses.append(_filter_sql(ds, f, params))
    return " AND ".join(clauses) if clauses else "1=1"


def where_clause(plan: QueryPlan, start: date | None, end: date | None) -> tuple[str, list]:
    """Public accessor for the WHERE fragment (used by anomaly detection)."""
    params: list = []
    return _where(DATASETS[plan.dataset], plan, start, end, params), params


def build(plan: QueryPlan, start: date | None, end: date | None) -> tuple[str, list]:
    ds = DATASETS[plan.dataset]
    params: list = []
    use_rollup = False
    
    if plan.dataset == "transactions" and _can_use_rollup(plan, ds):
        use_rollup = True

    if plan.intent == "list":
        cols = ", ".join(f'"{c}"' for c in ds.default_columns)
        where = _where(ds, plan, start, end, params, use_rollup=use_rollup)
        default_order = ds.date_field or ds.amount_field
        order = plan.sort.field if plan.sort and plan.sort.field in ds.field_map else default_order
        direction = plan.sort.dir.upper() if plan.sort else "DESC"
        sql = (
            f"SELECT {cols} FROM {ds.view} WHERE {where} "
            f'ORDER BY "{order}" {direction} LIMIT {plan.limit}'
        )
        return sql, params

    group_exprs: list[str] = []
    select_parts: list[str] = []

    if plan.intent == "trend":
        if use_rollup:
            select_parts.append(f'txn_month AS "period"')
            group_exprs.append(f'txn_month')
        else:
            select_parts.append(f'strftime("{ds.date_field}", \'%Y-%m\') AS "period"')
            group_exprs.append(f'strftime("{ds.date_field}", \'%Y-%m\')')
    for g in plan.group_by:
        c = _col(ds, g)
        select_parts.append(f"{c} AS {c}")
        group_exprs.append(c)

    metrics = plan.metrics or [Metric()]
    select_parts.extend(_metric_expr(ds, m, use_rollup=use_rollup) for m in metrics)
    if use_rollup:
        select_parts.append('sum(record_count) AS "record_count"')
    else:
        select_parts.append('count(*) AS "record_count"')

    where = _where(ds, plan, start, end, params, use_rollup=use_rollup)
    view_name = "v_rollup_monthly" if use_rollup else ds.view
    sql = f"SELECT {', '.join(select_parts)} FROM {view_name} WHERE {where}"
    if group_exprs:
        sql += " GROUP BY " + ", ".join(group_exprs)
        if plan.intent == "trend":
            sql += ' ORDER BY "period" ASC'
        else:
            sort_field = plan.sort.field if plan.sort else metrics[0].name
            if sort_field not in {m.name for m in metrics} and sort_field not in plan.group_by:
                sort_field = metrics[0].name
            direction = plan.sort.dir.upper() if plan.sort else "DESC"
            sql += f' ORDER BY "{sort_field}" {direction}'
        sql += f" LIMIT {plan.limit}"
    return sql, params


def build_supporting_records(plan: QueryPlan, start: date | None, end: date | None, limit: int = 25) -> tuple[str, list]:
    """Sample of the raw rows behind an aggregate, so users can verify."""
    ds = DATASETS[plan.dataset]
    params: list = []
    where = _where(ds, plan, start, end, params)
    cols = ", ".join(f'"{c}"' for c in ds.default_columns)
    order_col = ds.amount_field if ds.amount_field in ds.field_map else (ds.date_field or ds.default_columns[0])
    return (
        f"SELECT {cols} FROM {ds.view} WHERE {where} "
        f'ORDER BY abs("{order_col}") DESC LIMIT {limit}',
        params,
    )


def inline(sql: str, params: list) -> str:
    """Human-readable SQL for the explainability panel (display only)."""
    out = sql
    for p in params:
        literal = "NULL" if p is None else (str(p) if isinstance(p, (int, float)) else "'" + str(p).replace("'", "''") + "'")
        out = out.replace("?", literal, 1)
    return out
