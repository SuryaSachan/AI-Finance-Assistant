"""Natural language -> QueryPlan.

Three tiers, in order:
  1. small LLM in JSON mode (the primary path),
  2. one repair round-trip with the validator's complaints,
  3. a deterministic rule-based parser (also the offline / no-LLM mode).

Whatever comes out is validated against the schema catalog, and every literal
that refers to a real-world entity (vendor, category, status) is resolved
against the database before it is allowed into a filter.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date

from pydantic import ValidationError
from rapidfuzz import fuzz, process

from . import db
from .llm import Usage, llm
from .plan_models import Filter, Metric, Period, QueryPlan, Sort
from .schema_catalog import CATEGORIES, DATASETS, schema_prompt

SPEND_WORDS = re.compile(r"\b(spend|spent|spending|expense|expenses|cost|costs|paid|pay|payout|outflow|burn)\b", re.I)
INCOME_WORDS = re.compile(r"\b(revenue|income|receipts|inflow|earned|collected)\b", re.I)
LIST_WORDS = re.compile(r"\b(list|show|which|what are|give me|display|find|see)\b", re.I)
TREND_WORDS = re.compile(r"\b(trend|over time|by month|monthly|month by month|each month|per month)\b", re.I)
COMPARE_WORDS = re.compile(r"\b(compare|versus|vs\.?|compared to|against|previous period|month before|prior period)\b", re.I)
ANOMALY_WORDS = re.compile(r"\b(anomal|unusual|spike|outlier|weird|abnormal|suspicious)\w*\b", re.I)
COUNT_WORDS = re.compile(r"\b(how many|number of|count)\b", re.I)
AVG_WORDS = re.compile(r"\b(average|avg|mean|typical)\b", re.I)
TOP_WORDS = re.compile(r"\b(top|largest|biggest|highest|most)\b", re.I)
BOTTOM_WORDS = re.compile(r"\b(smallest|lowest|least)\b", re.I)
FUTURE_WORDS = re.compile(
    r"\b(will|forecast|predict|projection|project(ed)?|next (month|quarter|year|week)|expect to|budget for)\b", re.I
)
VENDOR_PHRASE = re.compile(r"\b(?:with|to|from|vendor|for)\s+((?:[A-Z][\w&.\-']*\s?){1,3})")
PHRASE_STOPWORDS = {"i", "we", "the", "last", "this", "next", "q1", "q2", "q3", "q4", "january", "february",
                    "march", "april", "may", "june", "july", "august", "september", "october",
                    "november", "december"}

GROUP_HINTS = {
    "vendor_name": r"\b(by vendor|per vendor|each vendor|vendor[- ]wise|which vendors?|top\s+\d*\s*vendors?)\b",
    "category": r"\b(by category|per category|category[- ]wise|which categor)\b",
    "department": r"\b(by department|per department|department[- ]wise|which department|by team)\b",
    "account_name": r"\b(by account|per account|account[- ]wise)\b",
    "payment_method": r"\b(by (payment )?method|per method)\b",
    "status": r"\b(by status|per status)\b",
    "reconciliation_status": r"\b(by reconciliation status)\b",
}

SYSTEM_PROMPT = """You translate finance questions into a JSON query plan.
You NEVER calculate numbers and NEVER invent data. You only emit JSON.

DATASETS
{schema}

OUTPUT JSON SHAPE
{{"intent":"aggregate|list|trend|compare|anomaly|clarify|unsupported",
 "dataset":"transactions|vendor_payouts|bank_lines",
 "metrics":[{{"agg":"sum|count|avg|min|max|count_distinct","field":"amount"}}],
 "group_by":["<field>"],
 "filters":[{{"field":"<field>","op":"eq|neq|in|gt|gte|lt|lte|between|contains|is_null|not_null","value":<v>}}],
 "period":{{"kind":"all|this_month|last_month|month|quarter|last_quarter|this_quarter|year|last_year|ytd|last_n_days|last_n_months|custom","n":null,"value":null,"start":null,"end":null}},
 "compare_to_previous":false,
 "sort":{{"field":"<metric alias or field>","dir":"desc"}},
 "limit":20,
 "clarification":null}}

RULES
- Money OUT (spend, expenses, paid, cost) on transactions => add filter {{"field":"direction","op":"eq","value":"debit"}}.
- Money IN (revenue, income, receipts) => filter direction = credit.
- "payouts"/"paid to vendors"/"payment runs" => dataset vendor_payouts.
- "unreconciled"/"not reconciled" => filter reconciliation_status = unreconciled.
- Questions asking WHICH/LIST records => intent "list".
- "by vendor", "top vendors", "breakdown by X" => intent aggregate with group_by.
- "monthly", "over time", "trend" => intent "trend".
- "compare to", "vs last month", "how does that compare" => compare_to_previous true.
- Use period.kind "month" with period.value "YYYY-MM" for a named month.
- If the question cannot be answered from these fields, use intent "unsupported".
- If it is genuinely ambiguous, use intent "clarify" and put the question in "clarification".
- A follow-up question inherits filters/period from previous_plan unless it overrides them.
- Output ONLY the JSON object.

EXAMPLES
Q: How much did we spend on vendor payouts last month?
{{"intent":"aggregate","dataset":"vendor_payouts","metrics":[{{"agg":"sum","field":"amount"}}],"group_by":[],"filters":[],"period":{{"kind":"last_month"}},"compare_to_previous":false,"limit":20}}
Q: Which transactions are still unreconciled?
{{"intent":"list","dataset":"transactions","metrics":[{{"agg":"sum","field":"amount"}}],"group_by":[],"filters":[{{"field":"reconciliation_status","op":"eq","value":"unreconciled"}}],"period":{{"kind":"all"}},"compare_to_previous":false,"limit":25}}
Q: Top 5 vendors by spend in Q2 2025
{{"intent":"aggregate","dataset":"transactions","metrics":[{{"agg":"sum","field":"amount"}}],"group_by":["vendor_name"],"filters":[{{"field":"direction","op":"eq","value":"debit"}}],"period":{{"kind":"quarter","value":"2025-Q2"}},"compare_to_previous":false,"sort":{{"field":"sum_amount","dir":"desc"}},"limit":5}}
Q: How does that compare to the month before?
{{"intent":"compare","dataset":"transactions","metrics":[{{"agg":"sum","field":"amount"}}],"group_by":[],"filters":[{{"field":"direction","op":"eq","value":"debit"}}],"period":{{"kind":"last_month"}},"compare_to_previous":true,"limit":20}}
Q: Show marketing spend by month this year
{{"intent":"trend","dataset":"transactions","metrics":[{{"agg":"sum","field":"amount"}}],"group_by":[],"filters":[{{"field":"direction","op":"eq","value":"debit"}},{{"field":"category","op":"eq","value":"Marketing"}}],"period":{{"kind":"ytd"}},"compare_to_previous":false,"limit":24}}
"""


@dataclass
class PlanResult:
    plan: QueryPlan
    source: str  # llm | llm_repaired | llm_fallback_model | rules
    issues: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    entity_score: float = 100.0
    unknown_entity: str | None = None
    raw: dict | None = None


# --------------------------------------------------------------------- entity
def _enum_values(dataset: str, fieldname: str) -> tuple[str, ...]:
    f = DATASETS[dataset].field_map.get(fieldname)
    return f.values if f else ()


def resolve_entities(plan: QueryPlan) -> tuple[QueryPlan, list[str], float, str | None]:
    """Snap filter literals onto values that actually exist in the data."""
    notes: list[str] = []
    worst = 100.0
    unknown: str | None = None
    vendors = db.vendor_names()

    for f in plan.filters:
        if f.op in ("is_null", "not_null") or f.value is None:
            continue
        if f.field == "vendor_name" and isinstance(f.value, str):
            match = process.extractOne(f.value, vendors, scorer=fuzz.WRatio)
            if match and match[1] >= 75:
                if match[0].lower() != f.value.lower():
                    notes.append(f"Matched \"{f.value}\" to vendor \"{match[0]}\" ({match[1]:.0f}% match).")
                worst = min(worst, float(match[1]))
                f.value = match[0]
                f.op = "eq" if f.op == "contains" else f.op
            else:
                unknown = f.value
        else:
            allowed = _enum_values(plan.dataset, f.field)
            if allowed and isinstance(f.value, str):
                match = process.extractOne(f.value, allowed, scorer=fuzz.WRatio)
                if match and match[1] >= 70:
                    if match[0] != f.value:
                        notes.append(f"Interpreted \"{f.value}\" as {f.field} = {match[0]}.")
                    f.value = match[0]
                    worst = min(worst, float(match[1]))
                else:
                    unknown = f"{f.field}={f.value}"
    return plan, notes, worst, unknown


# ------------------------------------------------------------------ validation
def validate(plan: QueryPlan) -> list[str]:
    issues: list[str] = []
    if plan.dataset not in DATASETS:
        issues.append(f"dataset '{plan.dataset}' does not exist; use one of {list(DATASETS)}")
        return issues
    ds = DATASETS[plan.dataset]
    fields = ds.field_map

    plan.group_by = [g for g in plan.group_by if g]
    for g in list(plan.group_by):
        if g not in fields:
            issues.append(f"group_by field '{g}' does not exist in {ds.key}")
            plan.group_by.remove(g)
    for f in list(plan.filters):
        if f.field not in fields:
            issues.append(f"filter field '{f.field}' does not exist in {ds.key}")
            plan.filters.remove(f)
    for m in list(plan.metrics):
        if m.agg != "count" and m.field not in fields:
            issues.append(f"metric field '{m.field}' does not exist in {ds.key}")
            plan.metrics.remove(m)
    if not plan.metrics:
        plan.metrics = [Metric(agg="sum", field=ds.amount_field)]
    return issues


def apply_business_defaults(plan: QueryPlan, question: str) -> list[str]:
    """Assumptions we apply explicitly (and always surface to the user)."""
    notes: list[str] = []
    ds = DATASETS[plan.dataset]
    have = {f.field for f in plan.filters}

    if plan.dataset == "transactions":
        if "direction" not in have:
            if SPEND_WORDS.search(question) and not INCOME_WORDS.search(question):
                plan.filters.append(Filter(field="direction", op="eq", value="debit"))
                notes.append("Counted money-out entries only (direction = debit).")
            elif INCOME_WORDS.search(question):
                plan.filters.append(Filter(field="direction", op="eq", value="credit"))
                notes.append("Counted money-in entries only (direction = credit).")
        if "status" not in have and plan.intent in ("aggregate", "trend", "compare", "anomaly"):
            plan.filters.append(Filter(field="status", op="neq", value="void"))
            notes.append("Excluded voided transactions.")

    for m in plan.metrics:
        if m.agg != "count" and m.field not in ds.field_map:
            m.field = ds.amount_field
    return notes


# ------------------------------------------------------------- rule-based tier
def _detect_period(q: str) -> Period | None:
    ql = q.lower()
    if re.search(r"\blast month\b|\bprevious month\b|\bprior month\b", ql):
        return Period(kind="last_month")
    if re.search(r"\bthis month\b|\bcurrent month\b|\bmonth to date\b|\bmtd\b", ql):
        return Period(kind="this_month")
    if re.search(r"\blast quarter\b|\bprevious quarter\b", ql):
        return Period(kind="last_quarter")
    if re.search(r"\bthis quarter\b|\bqtd\b", ql):
        return Period(kind="this_quarter")
    if re.search(r"\b(ytd|year to date|this year)\b", ql):
        return Period(kind="ytd")
    if re.search(r"\blast year\b|\bprevious year\b", ql):
        return Period(kind="last_year")
    m = re.search(r"\blast (\d+)\s*days?\b", ql)
    if m:
        return Period(kind="last_n_days", n=int(m.group(1)))
    m = re.search(r"\blast (\d+)\s*months?\b", ql)
    if m:
        return Period(kind="last_n_months", n=int(m.group(1)))
    m = re.search(r"\b(q[1-4])\s*(\d{4})?\b", ql)
    if m:
        return Period(kind="quarter", value=f"{m.group(2) or ''}-{m.group(1)}".strip("-").upper())
    m = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december"
        r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b\.?\s*(\d{4})?",
        ql,
    )
    if m:
        return Period(kind="month", value=f"{m.group(1)} {m.group(2) or ''}".strip())
    m = re.search(r"\b(20\d{2})\b", ql)
    if m:
        return Period(kind="year", value=m.group(1))
    return None


def find_vendor(question: str) -> tuple[str | None, float]:
    vendors = db.vendor_names()
    match = process.extractOne(question, vendors, scorer=fuzz.partial_token_set_ratio)
    if not match or match[1] < 90:
        return None, 0.0
    head = match[0].split()[0].lower()
    words = re.findall(r"[a-z]+", question.lower())
    if any(fuzz.ratio(head, w) >= 85 for w in words):
        return match[0], float(match[1])
    return None, 0.0


def named_entity_phrase(question: str) -> str | None:
    """A proper-noun phrase that looks like a counterparty name.

    Used so that an unknown vendor produces an explicit refusal instead of a
    silently broader answer.
    """
    for m in VENDOR_PHRASE.finditer(question):
        phrase = m.group(1).strip(" .,?")
        words = [w for w in phrase.split() if w.lower() not in PHRASE_STOPWORDS]
        if words:
            return " ".join(words)
    return None


def rule_plan(question: str, previous: QueryPlan | None = None) -> QueryPlan:
    q = question
    ql = q.lower()
    plan = previous.model_copy(deep=True) if previous else QueryPlan()
    if previous:
        plan.compare_to_previous = False
        plan.clarification = None

    if FUTURE_WORDS.search(ql):
        plan.intent = "unsupported"
        return plan

    if re.search(r"\bpayout|payment run|disburse|paid to (the )?vendor", ql):
        dataset = "vendor_payouts"
    elif re.search(r"\bbank (statement|line|feed)|unmatched (bank )?(line|entr)", ql):
        dataset = "bank_lines"
    elif previous and not re.search(r"\btransaction|ledger|spend|spent|expense", ql):
        dataset = plan.dataset
    else:
        dataset = "transactions"
    if dataset != plan.dataset:
        plan.dataset = dataset
        plan.filters = []
        plan.group_by = []
    ds = DATASETS[plan.dataset]

    if ANOMALY_WORDS.search(ql):
        plan.intent = "anomaly"
    elif TREND_WORDS.search(ql):
        plan.intent = "trend"
    elif COMPARE_WORDS.search(ql):
        plan.intent = "compare"
        plan.compare_to_previous = True
    elif LIST_WORDS.search(ql) and not TOP_WORDS.search(ql) and not COUNT_WORDS.search(ql):
        plan.intent = "list"
    else:
        plan.intent = "aggregate"

    if COUNT_WORDS.search(ql):
        plan.metrics = [Metric(agg="count", field=ds.amount_field)]
    elif AVG_WORDS.search(ql):
        plan.metrics = [Metric(agg="avg", field=ds.amount_field)]
    else:
        plan.metrics = [Metric(agg="sum", field=ds.amount_field)]

    groups = [f for f, pat in GROUP_HINTS.items() if f in ds.field_map and re.search(pat, ql)]
    if groups:
        plan.group_by = groups
        if plan.intent == "list":
            plan.intent = "aggregate"
    elif not previous or re.search(r"\btotal\b|\boverall\b", ql):
        plan.group_by = [] if not groups else plan.group_by

    m = re.search(r"\btop\s+(\d+)", ql)
    if m:
        plan.limit = int(m.group(1))
        plan.sort = Sort(field=plan.metrics[0].name, dir="desc")
    elif BOTTOM_WORDS.search(ql):
        plan.sort = Sort(field=plan.metrics[0].name, dir="asc")
    elif plan.group_by:
        plan.sort = Sort(field=plan.metrics[0].name, dir="desc")

    period = _detect_period(q)
    if period:
        plan.period = period
    elif not previous:
        plan.period = Period(kind="all")

    # a follow-up keeps the previous direction/status framing unless it restates it
    restates_direction = bool(SPEND_WORDS.search(ql) or INCOME_WORDS.search(ql))
    plan.filters = [
        f
        for f in plan.filters
        if f.field in ds.field_map and not (restates_direction and f.field in ("direction", "status"))
    ]

    if re.search(r"\bunreconcil|not reconciled|outstanding reconcil|still (open|unmatched)", ql):
        plan.filters = [f for f in plan.filters if f.field != "reconciliation_status"]
        plan.filters.append(Filter(field="reconciliation_status", op="eq", value="unreconciled"))
    elif re.search(r"\bdisputed\b", ql):
        plan.filters.append(Filter(field="reconciliation_status", op="eq", value="disputed"))
    elif re.search(r"\breconciled\b", ql):
        plan.filters.append(Filter(field="reconciliation_status", op="eq", value="reconciled"))

    if plan.dataset == "vendor_payouts":
        for word, value in (("pending", "pending"), ("failed", "failed"), ("on hold", "on_hold")):
            if re.search(rf"\b{word}\b", ql):
                plan.filters = [f for f in plan.filters if f.field != "status"]
                plan.filters.append(Filter(field="status", op="eq", value=value))
                break
    if plan.dataset == "bank_lines" and re.search(r"\bunmatch", ql):
        plan.filters.append(Filter(field="match_status", op="eq", value="unmatched"))

    vendor, _score = find_vendor(q)
    residual = ql
    if vendor:
        plan.filters = [f for f in plan.filters if f.field != "vendor_name"]
        plan.filters.append(Filter(field="vendor_name", op="eq", value=vendor))
        residual = ql.replace(vendor.lower(), " ")
    else:
        phrase = named_entity_phrase(q)
        if phrase and "vendor_name" in ds.field_map:
            # unresolved counterparty: keep it so entity resolution can refuse
            plan.filters = [f for f in plan.filters if f.field != "vendor_name"]
            plan.filters.append(Filter(field="vendor_name", op="eq", value=phrase))
            residual = ql.replace(phrase.lower(), " ")

    matched_category = None
    for cat in CATEGORIES:
        if cat.split(" ")[0].lower() in residual and "category" in ds.field_map:
            plan.filters = [f for f in plan.filters if f.field != "category"]
            plan.filters.append(Filter(field="category", op="eq", value=cat))
            matched_category = cat.split(" ")[0].lower()
            break
    for dept in DATASETS["transactions"].field_map["department"].values:
        if dept.lower() == matched_category:  # "marketing" is both a category and a department
            continue
        if re.search(rf"\b{dept.lower()}\b", residual) and "department" in ds.field_map:
            plan.filters.append(Filter(field="department", op="eq", value=dept))
            break

    if plan.intent == "list":
        plan.limit = max(plan.limit, 25)
    return plan


# ---------------------------------------------------------------- entry point
def make_plan(
    question: str,
    history: list[dict] | None = None,
    previous_plan: QueryPlan | None = None,
    usage: Usage | None = None,
) -> PlanResult:
    usage = usage or Usage()
    plan: QueryPlan | None = None
    source = "rules"
    issues: list[str] = []
    raw: dict | None = None

    if llm.health():
        system = SYSTEM_PROMPT.format(schema=schema_prompt())
        user = _user_prompt(question, history, previous_plan)
        for attempt, model in enumerate([llm.model, llm.fallback_model or llm.model]):
            data, res = llm.chat_json(system, user, model=model, max_tokens=400)
            usage.add(f"planner:attempt{attempt + 1}", res)
            if data is None:
                issues.append("model did not return valid JSON")
                continue
            raw = data
            try:
                candidate = QueryPlan.model_validate(data)
            except ValidationError as exc:
                issues.append(f"plan failed schema validation: {exc.errors()[0].get('msg', '')}")
                user = _user_prompt(question, history, previous_plan, repair=issues[-3:])
                continue
            problems = validate(candidate)
            if problems and attempt == 0:
                issues.extend(problems)
                user = _user_prompt(question, history, previous_plan, repair=problems)
                continue
            issues.extend(problems)
            plan = candidate
            source = "llm" if attempt == 0 and not problems else "llm_repaired"
            break

    if plan is None:
        plan = rule_plan(question, previous_plan)
        validate(plan)
        source = "rules"

    if plan.intent == "compare":
        plan.compare_to_previous = True
    if plan.compare_to_previous and plan.intent == "aggregate":
        plan.intent = "compare"

    notes = apply_business_defaults(plan, question)
    plan, ent_notes, ent_score, unknown = resolve_entities(plan)
    return PlanResult(
        plan=plan,
        source=source,
        issues=issues,
        notes=notes + ent_notes,
        entity_score=ent_score,
        unknown_entity=unknown,
        raw=raw,
    )


def _user_prompt(
    question: str,
    history: list[dict] | None,
    previous_plan: QueryPlan | None,
    repair: list[str] | None = None,
) -> str:
    anchor: date = db.anchor_date()
    lo, hi = db.data_span()
    parts = [
        f"today: {anchor.isoformat()}",
        f"data available: {lo.isoformat()} to {hi.isoformat()}",
    ]
    if history:
        convo = " | ".join(f"{h['role']}: {h['content'][:160]}" for h in history[-4:])
        parts.append(f"conversation so far: {convo}")
    if previous_plan:
        parts.append("previous_plan: " + json.dumps(previous_plan.model_dump(exclude_none=True), default=str))
    if repair:
        parts.append("Your previous JSON was rejected: " + "; ".join(repair) + ". Fix it.")
    parts.append(f"question: {question}")
    return "\n".join(parts)
