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
    df = query("SELECT max(transaction_date) AS d FROM txn_enriched")
    return pd.Timestamp(df.iloc[0]["d"]).date()


@lru_cache(maxsize=1)
def counterparty_names() -> tuple[str, ...]:
    """Known counterparties, used for entity resolution and for refusing unknown names."""
    df = query("SELECT counterparty FROM counterparties ORDER BY txn_count DESC LIMIT 20000")
    return tuple(df["counterparty"].tolist())


@lru_cache(maxsize=1)
def data_span() -> tuple[date, date]:
    df = query("SELECT min(transaction_date) a, max(transaction_date) b FROM txn_enriched")
    return pd.Timestamp(df.iloc[0]["a"]).date(), pd.Timestamp(df.iloc[0]["b"]).date()


@lru_cache(maxsize=1)
def stats() -> dict:
    df = query(
        "SELECT (SELECT count(*) FROM txn_enriched) AS transactions,"
        " (SELECT count(*) FROM v_accounts) AS accounts,"
        " (SELECT count(DISTINCT entity_id) FROM v_accounts) AS entities,"
        " (SELECT count(*) FROM counterparties) AS counterparties"
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
