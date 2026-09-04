"""Deterministic resolution of natural-language time expressions.

Dates are never left to the LLM to compute: the planner emits a symbolic period
(e.g. `last_month`) and this module turns it into a concrete [start, end] range
anchored on the dataset's "today".
"""
from __future__ import annotations

import calendar
import re
from datetime import date

import pandas as pd

QUARTER_MONTHS = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}
MONTH_NAMES = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTH_NAMES.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})


class PeriodError(ValueError):
    pass


def _eom(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _shift_months(d: date, n: int) -> date:
    ts = pd.Timestamp(d) + pd.DateOffset(months=n)
    return ts.date()


def month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), _eom(date(year, month, 1))


def resolve(period: dict | None, anchor: date) -> tuple[date | None, date | None, str]:
    """Return (start, end, human_label). (None, None) means 'all time'."""
    if not period:
        return None, None, "all time"
    kind = (period.get("kind") or "all").strip().lower()
    n = period.get("n")
    value = (period.get("value") or "").strip()

    if kind in ("all", "alltime", "all_time", ""):
        return None, None, "all time"

    if kind == "custom":
        try:
            s = date.fromisoformat(period["start"])
            e = date.fromisoformat(period["end"])
        except Exception as exc:  # noqa: BLE001
            raise PeriodError("custom period needs valid start and end dates") from exc
        return s, e, f"{s.isoformat()} to {e.isoformat()}"

    if kind == "this_month":
        s, e = month_range(anchor.year, anchor.month)
        return s, min(e, anchor), f"{s.strftime('%B %Y')} (month to date)"

    if kind == "last_month":
        prev = _shift_months(date(anchor.year, anchor.month, 1), -1)
        s, e = month_range(prev.year, prev.month)
        return s, e, s.strftime("%B %Y")

    if kind in ("last_n_days", "last_days"):
        days = int(n or 30)
        return anchor - pd.Timedelta(days=days - 1).to_pytimedelta(), anchor, f"the last {days} days"

    if kind in ("last_n_months", "last_months"):
        months = int(n or 3)
        first = _shift_months(date(anchor.year, anchor.month, 1), -(months - 1))
        return first, anchor, f"the last {months} months"

    if kind == "this_quarter":
        q = (anchor.month - 1) // 3 + 1
        a, b = QUARTER_MONTHS[q]
        return date(anchor.year, a, 1), min(_eom(date(anchor.year, b, 1)), anchor), f"Q{q} {anchor.year} (quarter to date)"

    if kind == "last_quarter":
        q = (anchor.month - 1) // 3 + 1
        year, q = (anchor.year - 1, 4) if q == 1 else (anchor.year, q - 1)
        a, b = QUARTER_MONTHS[q]
        return date(year, a, 1), _eom(date(year, b, 1)), f"Q{q} {year}"

    if kind in ("this_year", "ytd", "year_to_date"):
        return date(anchor.year, 1, 1), anchor, f"{anchor.year} year to date"

    if kind == "last_year":
        return date(anchor.year - 1, 1, 1), date(anchor.year - 1, 12, 31), str(anchor.year - 1)

    if kind == "month":
        y, m = _parse_month(value, anchor)
        s, e = month_range(y, m)
        return s, min(e, anchor), s.strftime("%B %Y")

    if kind == "quarter":
        mt = re.match(r"(?:(\d{4})[-\s]?)?Q([1-4])", value, re.I)
        if not mt:
            raise PeriodError(f"could not understand quarter '{value}'")
        year = int(mt.group(1) or anchor.year)
        q = int(mt.group(2))
        a, b = QUARTER_MONTHS[q]
        return date(year, a, 1), min(_eom(date(year, b, 1)), anchor), f"Q{q} {year}"

    if kind == "year":
        mt = re.search(r"(\d{4})", value)
        if not mt:
            raise PeriodError(f"could not understand year '{value}'")
        y = int(mt.group(1))
        return date(y, 1, 1), min(date(y, 12, 31), anchor), str(y)

    raise PeriodError(f"unsupported period '{kind}'")


def _parse_month(value: str, anchor: date) -> tuple[int, int]:
    mt = re.match(r"^(\d{4})-(\d{1,2})$", value)
    if mt:
        return int(mt.group(1)), int(mt.group(2))
    tokens = re.split(r"[\s,]+", value.lower().strip())
    month = year = None
    for tok in tokens:
        if tok in MONTH_NAMES:
            month = MONTH_NAMES[tok]
        elif re.fullmatch(r"\d{4}", tok):
            year = int(tok)
    if month is None:
        raise PeriodError(f"could not understand month '{value}'")
    return year or anchor.year, month


def previous_period(start: date, end: date) -> tuple[date, date]:
    """The immediately preceding, equal-length period.

    Whole calendar months shift by month so 'the month before' is exact.
    """
    is_full_month = start.day == 1 and end == _eom(end) and (start.year, start.month) == (end.year, end.month)
    if is_full_month:
        prev = _shift_months(start, -1)
        return month_range(prev.year, prev.month)
    span = (end - start).days + 1
    new_end = start - pd.Timedelta(days=1).to_pytimedelta()
    return new_end - pd.Timedelta(days=span - 1).to_pytimedelta(), new_end


def label_for(start: date | None, end: date | None) -> str:
    if not start or not end:
        return "all time"
    if start.day == 1 and end == _eom(end) and (start.year, start.month) == (end.year, end.month):
        return start.strftime("%B %Y")
    return f"{start.isoformat()} to {end.isoformat()}"
