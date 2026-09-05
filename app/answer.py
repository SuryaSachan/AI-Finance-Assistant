"""Answer construction: deterministic first, LLM only as a narrator.

The number-verification guardrail is the core of the anti-hallucination
design. A deterministic answer is always built from the SQL result. The LLM is
then given only those computed facts and asked to phrase them. Every numeric
token it produces is checked back against the computed values; if a single one
is unaccounted for, the LLM output is discarded and the deterministic answer is
returned instead.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from . import config
from .executor import Execution
from .llm import Usage, llm
from .planner import PlanResult
from .schema_catalog import DATASETS

NUM_RE = re.compile(r"[-+]?[₹$€]?\s?\d[\d,]*(?:\.\d+)?\s?(?:%|k|K|m|M|bn|B)?")

NARRATOR_SYSTEM = """You are a finance analyst assistant. You are given a QUESTION and FACTS
that were already computed from the company's database.

Rules:
- ALWAYS format money amounts with the currency symbol ₹ and Indian comma grouping (e.g. ₹7,04,41,50,133.60). Use the pre-formatted values in totals_formatted.
- Never output raw unformatted numbers like 7044150133.6 for money.
- Never calculate, estimate or round to an ungrounded number.
- 2-3 short sentences. Plain language. No markdown tables, no bullet lists, no preamble.
- State the period and what was filtered.
- If FACTS say no records were found, say clearly that there is no matching data.
"""


@dataclass
class Answer:
    text: str
    source: str  # "llm" | "deterministic"
    guardrail_triggered: bool
    rejected_numbers: list[str]


# ------------------------------------------------------------------ formatting
def money(v: float | int | None) -> str:
    if v is None:
        return "n/a"
    s = f"{abs(v):.2f}"
    parts = s.split(".")
    int_part, dec_part = parts[0], parts[1]
    if len(int_part) <= 3:
        fmt_int = int_part
    else:
        last3 = int_part[-3:]
        rest = int_part[:-3]
        groups = []
        while len(rest) > 2:
            groups.append(rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.append(rest)
        fmt_int = ",".join(reversed(groups)) + "," + last3
    sign = "-" if v < 0 else ""
    return f"{sign}{config.CURRENCY_SYMBOL}{fmt_int}.{dec_part}"


def describe_filters(plan) -> str:
    ds = DATASETS[plan.dataset]
    parts = []
    label = {
        "transaction_type": {"debit": "money out", "credit": "money in"},
    }
    for f in plan.filters:
        if f.op == "is_null":
            parts.append(f"{f.field} is empty")
        elif f.op == "not_null":
            parts.append(f"{f.field} is set")
        elif f.op == "neq":
            parts.append(f"{f.field} is not {f.value}")
        elif f.op in ("in", "not_in"):
            parts.append(f"{f.field} in {f.value}")
        else:
            pretty = label.get(f.field, {}).get(str(f.value), str(f.value))
            parts.append(f"{f.field.replace('_', ' ')} = {pretty}")
    _ = ds
    return ", ".join(parts)


def metric_label(plan) -> str:
    m = plan.metrics[0]
    field = m.field.replace("_", " ")
    return {
        "sum": f"total {field}",
        "count": "number of records",
        "avg": f"average {field}",
        "min": f"smallest {field}",
        "max": f"largest {field}",
        "count_distinct": f"distinct {field}",
    }.get(m.agg, m.agg)


# --------------------------------------------------------- deterministic answer
def deterministic_answer(ex: Execution, pr: PlanResult) -> str:
    plan = ex.plan
    ds = DATASETS[plan.dataset]
    where = describe_filters(plan)
    where_txt = f" where {where}" if where else ""
    # a dateless dataset (accounts) has no meaningful period to name
    period = ex.period_label if ds.date_field else ""
    n = ex.total_records
    primary = plan.metrics[0]
    total = ex.totals.get(primary.name)

    if n == 0:
        return (
            f"I found no {ds.label} {('for ' + period) if period else ''}{where_txt}. ".replace("  ", " ")
            + "There is no figure to report for that query, so I am not going to estimate one."
        )

    if plan.intent == "compare" and ex.comparison:
        c = ex.comparison
        direction = "up" if c["absolute_change"] > 0 else "down" if c["absolute_change"] < 0 else "flat"
        pct = f" ({c['percent_change']:+.1f}%)" if c["percent_change"] is not None else ""
        return (
            f"{c['current_period']}: {money(c['current_value'])} across {c['current_records']:,} records"
            f"{where_txt}. {c['previous_period']}: {money(c['previous_value'])} across "
            f"{c['previous_records']:,} records. That is {direction} by "
            f"{money(abs(c['absolute_change']))}{pct}."
        )

    if plan.intent == "trend" and ex.rows:
        first, last = ex.rows[0], ex.rows[-1]
        key = primary.name if primary.name in first else "record_count"
        peak = max(ex.rows, key=lambda r: r.get(key) or 0)
        return (
            f"{metric_label(plan).capitalize()} by month for {period}{where_txt}, across "
            f"{n:,} records totalling {money(total)}. It ran from {money(first.get(key))} in "
            f"{first.get('period')} to {money(last.get(key))} in {last.get('period')}, peaking at "
            f"{money(peak.get(key))} in {peak.get('period')}."
        )

    if plan.intent == "list":
        shown = len(ex.rows)
        more = f" The {shown} most significant are in the table below." if ex.truncated else ""
        return (
            f"There are {n:,} {ds.label}{(' for ' + period) if period else ''}{where_txt}, "
            f"totalling {money(ex.totals.get('sum_' + ds.amount_field, total))}.{more}"
        )

    if plan.group_by and ex.rows:
        g = plan.group_by[0]
        key = primary.name if primary.name in ex.rows[0] else "record_count"
        top = ex.rows[: min(3, len(ex.rows))]
        listed = "; ".join(f"{r.get(g)} {money(r.get(key))}" for r in top)
        return (
            f"{('For ' + period) if period else 'Across the whole dataset'}{where_txt},"
            f" {metric_label(plan)} was {money(total)} across {n:,} records. "
            f"Broken down by {g.replace('_', ' ')}, the top entries are: {listed}."
        )

    if primary.agg == "count":
        return f"There are {int(total or n):,} {ds.label}{(' for ' + period) if period else ''}{where_txt}."

    return (
        f"{('For ' + period) if period else 'Across the whole dataset'}{where_txt},"
        f" {metric_label(plan)} was {money(total)}, computed over {n:,} matching records."
    )


# ---------------------------------------------------------------- guardrails
def _parse_number(token: str) -> float | None:
    t = token.strip().replace("₹", "").replace("$", "").replace("€", "").replace(",", "").replace(" ", "")
    mult = 1.0
    if t.endswith("%"):
        t = t[:-1]
    elif t[-1:] in ("k", "K"):
        t, mult = t[:-1], 1_000
    elif t[-1:] in ("m", "M"):
        t, mult = t[:-1], 1_000_000
    elif t.endswith(("bn", "B")):
        t, mult = t.rstrip("bnB"), 1_000_000_000
    try:
        return float(t) * mult
    except ValueError:
        return None


def allowed_numbers(ex: Execution, question: str) -> set[float]:
    allowed: set[float] = set()

    def add(v):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            f = float(v)
            for cand in (f, round(f), round(f, 1), round(f, 2), f / 1_000, f / 1_000_000, abs(f)):
                allowed.add(float(cand))

    for row in ex.rows + ex.supporting_rows:
        for v in row.values():
            add(v)
    for v in ex.totals.values():
        add(v)
    add(ex.total_records)
    add(len(ex.rows))
    if ex.comparison:
        for v in ex.comparison.values():
            add(v)
    if ex.start and ex.end:
        add(ex.start.year)
        add(ex.end.year)
        add((ex.end - ex.start).days + 1)
    for tok in NUM_RE.findall(question):  # user's own numbers, e.g. "top 5"
        v = _parse_number(tok)
        if v is not None:
            add(v)
    return allowed


def verify_numbers(text: str, allowed: set[float]) -> list[str]:
    """Return the numeric tokens in `text` that are not backed by computed data."""
    bad: list[str] = []
    for token in NUM_RE.findall(text):
        value = _parse_number(token)
        if value is None:
            continue
        ok = any(abs(value - a) <= max(0.02, abs(a) * 0.005) for a in allowed)
        if not ok:
            bad.append(token.strip())
    return bad


def facts_payload(ex: Execution, pr: PlanResult, anomalies: list[dict]) -> dict:
    plan = ex.plan
    payload = {
        "dataset": DATASETS[plan.dataset].label,
        "period": ex.period_label,
        "filters_applied": describe_filters(plan) or "none",
        "metric": metric_label(plan),
        "matching_record_count": ex.total_records,
        "totals": {k: v for k, v in ex.totals.items()},
        "totals_formatted": {k: money(v) for k, v in ex.totals.items()},
        "currency_symbol": config.CURRENCY_SYMBOL,
    }
    if ex.rows:
        payload["breakdown_rows"] = ex.rows[: config.LLM_ROW_BUDGET]
    if ex.comparison:
        payload["comparison"] = ex.comparison
    if anomalies:
        payload["anomalies"] = anomalies[:2]
    if pr.notes:
        payload["assumptions"] = pr.notes
    return payload


def narrate(question: str, ex: Execution, pr: PlanResult, anomalies: list[dict], usage: Usage) -> Answer:
    fallback = deterministic_answer(ex, pr)
    # For simple count/aggregate questions, deterministic_answer is instant (0.001s) and perfectly accurate
    if not llm.health() or ex.total_records == 0 or ex.plan.intent in ("aggregate", "list"):
        return Answer(fallback, "deterministic", False, [])

    facts = json.dumps(facts_payload(ex, pr, anomalies), default=str)[:4000]
    res = llm.chat(
        NARRATOR_SYSTEM,
        f"QUESTION: {question}\n\nFACTS:\n{facts}\n\nAnswer:",
        max_tokens=220,
    )
    usage.add("narrator", res)
    text = (res.text or "").strip()
    if not text or res.error:
        return Answer(fallback, "deterministic", False, [])

    bad = verify_numbers(text, allowed_numbers(ex, question))
    if bad:
        return Answer(fallback, "deterministic", True, bad)

    # Uniformity guarantee: if the narrator emitted raw floats for totals without the currency symbol, format them
    for k, val in ex.totals.items():
        if isinstance(val, (int, float)) and val > 0:
            formatted_val = money(val)
            for r in [f"{val:.1f}", f"{val:.2f}", f"{val:.0f}", str(val)]:
                pattern = rf"(?<![₹$€\d]){re.escape(r)}(?!\d)"
                if re.search(pattern, text):
                    text = re.sub(pattern, formatted_val, text)

    return Answer(text, "llm", False, [])


# ---------------------------------------------------------------- confidence
def confidence(ex: Execution, pr: PlanResult, answer: Answer) -> dict:
    score = 1.0
    reasons: list[str] = []

    if pr.source == "rules":
        score -= 0.10
        reasons.append("Interpreted with the deterministic rule parser rather than the model.")
    elif pr.source == "llm_repaired":
        score -= 0.10
        reasons.append("The model's first plan needed one repair round.")
    if pr.issues:
        score -= 0.10
        reasons.append(f"{len(pr.issues)} schema issue(s) were corrected in the query plan.")
    if pr.entity_score < 100:
        score -= (100 - pr.entity_score) / 200
        reasons.append(f"Entity name matched at {pr.entity_score:.0f}% rather than exactly.")
    if answer.guardrail_triggered:
        score -= 0.25
        reasons.append("The model's wording contained an unverifiable number, so it was replaced with the computed answer.")
    if ex.total_records == 0:
        score = min(score, 0.55)
        reasons.append("No records matched, so there is no figure to report.")
    elif ex.total_records < 5:
        score -= 0.10
        reasons.append(f"Only {ex.total_records} record(s) matched, so the result is thin.")
    if ex.plan.period is None or (ex.plan.period and ex.plan.period.kind == "all"):
        reasons.append("No time filter was applied - this covers the full dataset.")

    score = max(0.0, min(1.0, score))
    level = "high" if score >= 0.85 else "medium" if score >= 0.6 else "low"
    if not reasons:
        reasons.append("Plan validated cleanly, entities matched exactly, and every number came from SQL.")
    return {"level": level, "score": round(score, 2), "reasons": reasons}
