"""Natural language -> QueryPlan.

Three tiers, in order:
  1. small LLM in JSON mode (the primary path),
  2. one repair round-trip with the validator's complaints,
  3. a deterministic rule-based parser (also the offline / no-LLM mode).

Whatever comes out is validated against the schema catalog, and every literal
that refers to a real-world entity (counterparty, bank, channel) is resolved
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
from .schema_catalog import BANK_CODES, DATASETS, schema_prompt

SPEND_WORDS = re.compile(
    r"\b(spend|spent|spending|expense|expenses|cost|costs|paid|pay|payment|payout|payouts|"
    r"outflow|debit|debits|withdraw\w*|disburse\w*|transfer(red)? out)\b", re.I
)
INCOME_WORDS = re.compile(
    r"\b(revenue|income|receipt|receipts|receiv\w*|inflow|collect\w*|credit|credits|deposit\w*|settle\w*)\b", re.I
)
LIST_WORDS = re.compile(r"\b(list|show|which|what are|give me|display|find|see)\b", re.I)
TREND_WORDS = re.compile(r"\b(trend|over time|by month|monthly|month by month|each month|per month)\b", re.I)
COMPARE_WORDS = re.compile(r"\b(compare|versus|vs\.?|compared to|against|previous period|month before|prior period)\b", re.I)
ANOMALY_WORDS = re.compile(r"\b(anomal|unusual|spike|outlier|weird|abnormal|suspicious)\w*\b", re.I)
COUNT_WORDS = re.compile(r"\b(how many|number of|count)\b", re.I)
AVG_WORDS = re.compile(r"\b(average|avg|mean|typical)\b", re.I)
TOP_WORDS = re.compile(r"\b(top|largest|biggest|highest|most)\b", re.I)
BOTTOM_WORDS = re.compile(r"\b(smallest|lowest|least)\b", re.I)
BALANCE_WORDS = re.compile(r"\b(balance|balances|available funds|how much (do we|is) (have|held|sitting))\b", re.I)
FUTURE_WORDS = re.compile(
    r"\b(will|forecast|predict|projection|project(ed)?|next (month|quarter|year|week)|expect to|budget for)\b", re.I
)

CHANNEL_WORDS = {
    "UPI": r"\bupi\b",
    "NEFT": r"\bneft\b",
    "IMPS": r"\bimps\b",
    "RTGS": r"\brtgs\b",
    "CHEQUE": r"\bcheque|check\b",
    "ACH": r"\b(ach|nach)\b",
    "ATM": r"\batm\b",
    "CHARGES": r"\b(bank )?(charges?|fees?)\b",
}

GROUP_HINTS = {
    "counterparty": r"\b(by (vendor|counterpart\w+|payee|merchant|beneficiar\w+)|per (vendor|counterpart\w+|merchant)|"
                    r"which (vendors?|counterpart\w+|merchants?|payees?)|top\s+\d*\s*(vendors?|counterpart\w+|merchants?|payees?))\b",
    "bank_name": r"\b(by bank|per bank|each bank|which banks?|bank[- ]wise)\b",
    "channel": r"\b(by (channel|mode|rail|payment method)|per (channel|mode)|which (channel|mode))\b",
    "transaction_type": r"\b(by (transaction )?type|credit vs debit|debit vs credit)\b",
    "program_id": r"\b(by program|per program|program[- ]wise)\b",
    "entity_id": r"\b(by entity|per entity|entity[- ]wise)\b",
    "account_number_masked": r"\b(by account|per account|each account|which accounts?|account[- ]wise)\b",
}

ENTITY_PHRASE = re.compile(r"\b(?:with|to|from|for|vendor|counterparty|payee|merchant)\s+((?:[A-Z][\w&.\-']*\s?){1,4})")
PHRASE_STOPWORDS = {
    "i", "we", "us", "our", "the", "a", "an", "last", "this", "next", "each", "every", "all",
    "q1", "q2", "q3", "q4", "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december", "bank", "banks", "account",
    "accounts", "how", "much", "many", "did", "do", "does", "was", "were", "what", "which",
    "who", "when", "show", "list", "give", "total", "spend", "spent", "pay", "paid", "payment",
    "payments", "payout", "payouts", "receive", "received", "top", "most", "least", "by", "per",
    "to", "from", "with", "for", "in", "on", "of", "and", "or", "is", "are", "be", "month",
    "months", "year", "years", "quarter", "day", "days", "week", "transaction", "transactions",
    "money", "amount", "value", "over", "across", "still", "break", "down", "compare", "average",
}

SYSTEM_PROMPT = """You translate finance questions into a JSON query plan.
You NEVER calculate numbers and NEVER invent data. You only emit JSON.

DATASETS
{schema}

OUTPUT JSON SHAPE
{{"intent":"aggregate|list|trend|compare|anomaly|clarify|unsupported",
 "dataset":"transactions|accounts",
 "metrics":[{{"agg":"sum|count|avg|min|max|count_distinct","field":"amount"}}],
 "group_by":["<field>"],
 "filters":[{{"field":"<field>","op":"eq|neq|in|gt|gte|lt|lte|between|contains|is_null|not_null","value":<v>}}],
 "period":{{"kind":"all|this_month|last_month|month|quarter|last_quarter|this_quarter|year|last_year|ytd|last_n_days|last_n_months|custom","n":null,"value":null,"start":null,"end":null}},
 "compare_to_previous":false,
 "sort":{{"field":"<metric alias or field>","dir":"desc"}},
 "limit":20,
 "clarification":null}}

RULES
- Money OUT (spend, paid, payouts, expenses) => filter {{"field":"transaction_type","op":"eq","value":"debit"}}.
- Money IN (received, credits, collections, receipts) => transaction_type = credit.
- "unreconciled"/"not reconciled"/"unmatched" => filter reconciliation_status = unreconciled.
- A named company or person is a counterparty: filter {{"field":"counterparty","op":"eq","value":"<NAME>"}}.
- Balance questions => dataset "accounts" with metric sum of available_balance. Accounts have no dates.
- Questions asking WHICH/LIST records => intent "list".
- "by vendor", "top payees", "breakdown by X" => intent aggregate with group_by.
- "monthly", "over time", "trend" => intent "trend".
- "compare to", "vs last month", "how does that compare" => compare_to_previous true.
- Use period.kind "month" with period.value "YYYY-MM" for a named month.
- If the question needs a field that is not listed, use intent "unsupported".
- If it is genuinely ambiguous, use intent "clarify" and put the question in "clarification".
- A follow-up question inherits filters/period from previous_plan unless it overrides them.
- Output ONLY the JSON object.

EXAMPLES
Q: How much did we pay out last month?
{{"intent":"aggregate","dataset":"transactions","metrics":[{{"agg":"sum","field":"amount"}}],"group_by":[],"filters":[{{"field":"transaction_type","op":"eq","value":"debit"}}],"period":{{"kind":"last_month"}},"compare_to_previous":false,"limit":20}}
Q: Which transactions are still unreconciled?
{{"intent":"list","dataset":"transactions","metrics":[{{"agg":"sum","field":"amount"}}],"group_by":[],"filters":[{{"field":"reconciliation_status","op":"eq","value":"unreconciled"}}],"period":{{"kind":"all"}},"compare_to_previous":false,"limit":25}}
Q: Top 5 payees by spend in Q2 2026
{{"intent":"aggregate","dataset":"transactions","metrics":[{{"agg":"sum","field":"amount"}}],"group_by":["counterparty"],"filters":[{{"field":"transaction_type","op":"eq","value":"debit"}}],"period":{{"kind":"quarter","value":"2026-Q2"}},"compare_to_previous":false,"sort":{{"field":"sum_amount","dir":"desc"}},"limit":5}}
Q: How does that compare to the month before?
{{"intent":"compare","dataset":"transactions","metrics":[{{"agg":"sum","field":"amount"}}],"group_by":[],"filters":[{{"field":"transaction_type","op":"eq","value":"debit"}}],"period":{{"kind":"last_month"}},"compare_to_previous":true,"limit":20}}
Q: What is the total balance across HDFC accounts?
{{"intent":"aggregate","dataset":"accounts","metrics":[{{"agg":"sum","field":"available_balance"}}],"group_by":[],"filters":[{{"field":"bank_code","op":"eq","value":"HDFC"}}],"period":{{"kind":"all"}},"compare_to_previous":false,"limit":20}}
Q: Show UPI spend by month this year
{{"intent":"trend","dataset":"transactions","metrics":[{{"agg":"sum","field":"amount"}}],"group_by":[],"filters":[{{"field":"transaction_type","op":"eq","value":"debit"}},{{"field":"channel","op":"eq","value":"UPI"}}],"period":{{"kind":"ytd"}},"compare_to_previous":false,"limit":24}}
"""


@dataclass
class PlanResult:
    plan: QueryPlan
    source: str  # llm | llm_repaired | rules
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
    known = db.counterparty_names()

    for f in plan.filters:
        if f.op in ("is_null", "not_null") or f.value is None:
            continue
        if f.field == "counterparty" and isinstance(f.value, str):
            match = process.extractOne(f.value.upper(), known, scorer=fuzz.WRatio)
            if match and match[1] >= 78:
                if match[0].upper() != f.value.upper():
                    notes.append(f'Matched "{f.value}" to counterparty "{match[0]}" ({match[1]:.0f}% match).')
                worst = min(worst, float(match[1]))
                f.value = match[0]
                f.op = "eq" if f.op == "contains" else f.op
            else:
                unknown = f.value
        elif f.field == "bank_name" and isinstance(f.value, str):
            banks = _bank_names()
            match = process.extractOne(f.value.upper(), banks, scorer=fuzz.WRatio)
            if match and match[1] >= 75:
                f.value = match[0]
                worst = min(worst, float(match[1]))
            else:
                unknown = f.value
        else:
            allowed = _enum_values(plan.dataset, f.field)
            if allowed and isinstance(f.value, str):
                match = process.extractOne(f.value, allowed, scorer=fuzz.WRatio)
                if match and match[1] >= 70:
                    if match[0] != f.value:
                        notes.append(f'Interpreted "{f.value}" as {f.field} = {match[0]}.')
                    f.value = match[0]
                    worst = min(worst, float(match[1]))
                else:
                    unknown = f"{f.field}={f.value}"
    return plan, notes, worst, unknown


def _bank_names() -> tuple[str, ...]:
    df = db.query("SELECT DISTINCT bank_name FROM v_accounts WHERE bank_name IS NOT NULL")
    return tuple(df["bank_name"].tolist())


# ------------------------------------------------------------------ validation
def validate(plan: QueryPlan) -> list[str]:
    issues: list[str] = []
    if plan.dataset not in DATASETS:
        issues.append(f"dataset '{plan.dataset}' does not exist; fell back to 'transactions'")
        plan.dataset = "transactions"
        plan.filters = []
        plan.group_by = []
        plan.metrics = [Metric(agg="sum", field=DATASETS["transactions"].amount_field)]
    ds = DATASETS[plan.dataset]
    fields = ds.field_map

    if ds.date_field is None and plan.period and plan.period.kind not in ("all", ""):
        issues.append(f"{ds.key} has no date column; the time filter was dropped")
        plan.period = Period(kind="all")
    if ds.date_field is None and plan.intent == "trend":
        issues.append(f"{ds.key} has no date column; cannot show a trend")
        plan.intent = "aggregate"

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

    if plan.dataset == "transactions" and "transaction_type" not in have:
        if SPEND_WORDS.search(question) and not INCOME_WORDS.search(question):
            plan.filters.append(Filter(field="transaction_type", op="eq", value="debit"))
            notes.append("Counted money-out entries only (transaction_type = debit).")
        elif INCOME_WORDS.search(question):
            plan.filters.append(Filter(field="transaction_type", op="eq", value="credit"))
            notes.append("Counted money-in entries only (transaction_type = credit).")

    if any(f.field == "reconciliation_status" for f in plan.filters):
        notes.append(
            "Reconciliation is derived: this schema has no reconciliation column, so a "
            "transaction counts as reconciled when it carries a bank reference or a UTR."
        )
    if any(f.field == "counterparty" for f in plan.filters) or "counterparty" in plan.group_by:
        notes.append("Counterparty names are parsed out of the free-text bank narration.")

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


def find_counterparty(question: str) -> tuple[str | None, float]:
    """Match phrases in the question against real counterparty names.

    Scored per n-gram rather than against the whole sentence: matching the whole
    sentence lets a single common word ('bank') latch onto a long name.
    """
    known = db.counterparty_names()
    words = re.findall(r"[A-Za-z][A-Za-z&.'-]*", question)
    best: tuple[str | None, float, int] = (None, 0.0, 0)

    for i, word in enumerate(words):
        if word.lower() in PHRASE_STOPWORDS:
            continue
        for size in range(1, 6):
            if i + size > len(words):
                break
            gram = " ".join(words[i : i + size])
            if len(gram) < 5:
                continue
            match = process.extractOne(gram.upper(), known, scorer=fuzz.WRatio)
            if not match:
                continue
            coverage = len(gram) / len(match[0])
            if match[1] >= 88 and 0.55 <= coverage <= 1.7:
                if (match[1], len(gram)) > (best[1], best[2]):
                    best = (match[0], float(match[1]), len(gram))
    return best[0], best[1]


def named_entity_phrase(question: str) -> str | None:
    """A proper-noun phrase that looks like a counterparty name.

    Used so that an unknown counterparty produces an explicit refusal instead of
    a silently broader answer.
    """
    for m in ENTITY_PHRASE.finditer(question):
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

    if BALANCE_WORDS.search(ql):
        dataset = "accounts"
    elif previous and not re.search(r"\btransaction|spend|spent|payment|payout|credit|debit", ql):
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
    elif TREND_WORDS.search(ql) and ds.date_field:
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

    m = re.search(r"\btop\s+(\d+)", ql)
    if m:
        plan.limit = int(m.group(1))
        plan.sort = Sort(field=plan.metrics[0].name, dir="desc")
    elif BOTTOM_WORDS.search(ql):
        plan.sort = Sort(field=plan.metrics[0].name, dir="asc")
    elif plan.group_by:
        plan.sort = Sort(field=plan.metrics[0].name, dir="desc")

    period = _detect_period(q)
    if period and ds.date_field:
        plan.period = period
    elif not previous or not ds.date_field:
        plan.period = Period(kind="all")

    # a follow-up keeps the previous direction framing unless it restates it
    restates_direction = bool(SPEND_WORDS.search(ql) or INCOME_WORDS.search(ql))
    plan.filters = [
        f
        for f in plan.filters
        if f.field in ds.field_map and not (restates_direction and f.field == "transaction_type")
    ]

    if "reconciliation_status" in ds.field_map:
        if re.search(r"\bunreconcil|not reconciled|unmatched|outstanding reconcil|no reference|missing reference", ql):
            plan.filters = [f for f in plan.filters if f.field != "reconciliation_status"]
            plan.filters.append(Filter(field="reconciliation_status", op="eq", value="unreconciled"))
        elif re.search(r"\breconciled\b|\bmatched\b", ql):
            plan.filters = [f for f in plan.filters if f.field != "reconciliation_status"]
            plan.filters.append(Filter(field="reconciliation_status", op="eq", value="reconciled"))

    counterparty, _score = find_counterparty(q)
    residual = ql
    if counterparty and "counterparty" in ds.field_map:
        plan.filters = [f for f in plan.filters if f.field != "counterparty"]
        plan.filters.append(Filter(field="counterparty", op="eq", value=counterparty))
        residual = ql.replace(counterparty.lower(), " ")
    elif "counterparty" in ds.field_map:
        phrase = named_entity_phrase(q)
        if phrase:
            # unresolved counterparty: keep it so entity resolution can refuse
            plan.filters = [f for f in plan.filters if f.field != "counterparty"]
            plan.filters.append(Filter(field="counterparty", op="eq", value=phrase))
            residual = ql.replace(phrase.lower(), " ")

    if "channel" in ds.field_map:
        for channel, pattern in CHANNEL_WORDS.items():
            if re.search(pattern, residual, re.I):
                plan.filters = [f for f in plan.filters if f.field != "channel"]
                plan.filters.append(Filter(field="channel", op="eq", value=channel))
                break

    for code in BANK_CODES:
        if re.search(rf"\b{code.lower()}\b", residual) and "bank_code" in ds.field_map:
            plan.filters = [f for f in plan.filters if f.field != "bank_code"]
            plan.filters.append(Filter(field="bank_code", op="eq", value=code))
            break

    m = re.search(r"\bprogram\s*(?:id\s*)?(\d+)\b", residual)
    if m and "program_id" in ds.field_map:
        plan.filters.append(Filter(field="program_id", op="eq", value=int(m.group(1))))

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
