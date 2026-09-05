import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.plan_models import QueryPlan, Metric, Filter, Period
from app.sql_builder import build, inline

def test():
    plan = QueryPlan(
        intent="aggregate",
        dataset="transactions",
        metrics=[Metric(agg="sum", field="amount")],
        group_by=["counterparty"],
        filters=[Filter(field="transaction_type", op="eq", value="debit")],
        period=Period(kind="this_month")
    )

    from datetime import date
    sql, params = build(plan, date(2026, 5, 1), date(2026, 5, 31))
    print("Aggregate intent:")
    print(inline(sql, params))

    plan2 = QueryPlan(
        intent="trend",
        dataset="transactions",
        metrics=[Metric(agg="sum", field="amount")],
        group_by=[],
        filters=[],
        period=Period(kind="this_year")
    )
    sql, params = build(plan2, date(2026, 1, 1), date(2026, 12, 31))
    print("\nTrend intent:")
    print(inline(sql, params))

    print("\nList intent:")
    plan3 = plan.model_copy()
    plan3.intent = "list"
    sql, params = build(plan3, date(2026, 1, 1), date(2026, 12, 31))
    print(inline(sql, params))

if __name__ == "__main__":
    test()
