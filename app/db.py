"""DuckDB access layer.

The database is opened read-only: the assistant can never mutate finance data.
"""
from __future__ import annotations

import threading
from datetime import date
from functools import lru_cache

import duckdb
import pandas as pd

from . import config

_lock = threading.Lock()
_conn: duckdb.DuckDBPyConnection | None = None


class DatabaseMissing(RuntimeError):
    pass


def connection() -> duckdb.DuckDBPyConnection:
    global _conn
    with _lock:
        if _conn is None:
            if not config.DB_PATH.exists():
                raise DatabaseMissing(
                    f"{config.DB_PATH} not found. Run: python scripts/generate_data.py"
                )
            _conn = duckdb.connect(str(config.DB_PATH), read_only=True)
        return _conn


def query(sql: str, params: list | None = None) -> pd.DataFrame:
    cur = connection().cursor()
    try:
        return cur.execute(sql, params or []).fetch_df()
    finally:
        cur.close()


@lru_cache(maxsize=1)
def anchor_date() -> date:
    """The 'today' the assistant reasons against."""
    if config.ANCHOR_DATE:
        return date.fromisoformat(config.ANCHOR_DATE)
    df = query(
        "SELECT max(d) AS d FROM ("
        " SELECT max(txn_date) d FROM transactions"
        " UNION ALL SELECT max(payout_date) FROM vendor_payouts)"
    )
    value = df.iloc[0]["d"]
    return pd.Timestamp(value).date()


@lru_cache(maxsize=1)
def vendor_names() -> tuple[str, ...]:
    df = query("SELECT vendor_name FROM vendors ORDER BY vendor_name")
    return tuple(df["vendor_name"].tolist())


@lru_cache(maxsize=1)
def data_span() -> tuple[date, date]:
    df = query("SELECT min(txn_date) a, max(txn_date) b FROM transactions")
    return pd.Timestamp(df.iloc[0]["a"]).date(), pd.Timestamp(df.iloc[0]["b"]).date()


@lru_cache(maxsize=1)
def stats() -> dict:
    df = query(
        "SELECT (SELECT count(*) FROM transactions) AS transactions,"
        " (SELECT count(*) FROM vendor_payouts) AS vendor_payouts,"
        " (SELECT count(*) FROM bank_lines) AS bank_lines,"
        " (SELECT count(*) FROM vendors) AS vendors"
    )
    row = df.iloc[0].to_dict()
    lo, hi = data_span()
    return {
        **{k: int(v) for k, v in row.items()},
        "date_from": lo.isoformat(),
        "date_to": hi.isoformat(),
        "anchor_date": anchor_date().isoformat(),
        "currency": config.CURRENCY,
        "company": config.COMPANY,
    }
