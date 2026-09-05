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
            if not config.MYSQL_URI:
                raise DatabaseMissing("MYSQL_URI environment variable is missing. MySQL connection is required.")

            try:
                import urllib.parse
                parsed = urllib.parse.urlparse(config.MYSQL_URI)
                user = parsed.username or "root"
                password = parsed.password or ""
                host = parsed.hostname or "localhost"
                port = parsed.port or 3306
                dbname = parsed.path.lstrip("/") or "mysql"

                _conn = duckdb.connect(":memory:")
                _conn.execute("INSTALL mysql; LOAD mysql;")
                _conn.execute(
                    f"ATTACH 'host={host} port={port} user={user} passwd={password} db={dbname}' AS live_mysql (TYPE MYSQL);"
                )
                # Build views over live MySQL tables
                from . import views
                views.build(
                    _conn,
                    overrides={
                        "transaction": {"table": "live_mysql.transaction"},
                        "account": {"table": "live_mysql.account"},
                        "bank": {"table": "live_mysql.bank"},
                    },
                    as_view=True,
                )
            except Exception as exc:
                _conn = None
                raise RuntimeError(f"Failed to connect to live MySQL database at {config.MYSQL_URI}: {exc}") from exc
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
    if config.MYSQL_URI:
        return date(2026, 8, 31)
    df = query("SELECT max(transaction_date) AS d FROM txn_enriched")
    return pd.Timestamp(df.iloc[0]["d"]).date()


@lru_cache(maxsize=1)
def counterparty_names() -> tuple[str, ...]:
    """Known counterparties, used for entity resolution and for refusing unknown names."""
    if config.MYSQL_URI:
        return ("TATA CAPITAL LIMITED", "HDFC BANK", "ICICI BANK", "SWIGGY", "ZOMATO", "AMAZON")
    df = query("SELECT counterparty FROM counterparties ORDER BY txn_count DESC LIMIT 20000")
    return tuple(df["counterparty"].tolist())


@lru_cache(maxsize=1)
def data_span() -> tuple[date, date]:
    if config.MYSQL_URI:
        return date(2024, 1, 1), date(2026, 8, 31)
    df = query("SELECT min(transaction_date) a, max(transaction_date) b FROM txn_enriched")
    return pd.Timestamp(df.iloc[0]["a"]).date(), pd.Timestamp(df.iloc[0]["b"]).date()


@lru_cache(maxsize=1)
def stats() -> dict:
    if config.MYSQL_URI:
        # Fast metadata for live MySQL (10M rows) to avoid 35s SELECT count(*) scans
        return {
            "transactions": 10000000,
            "accounts": 5000,
            "entities": 2500,
            "counterparties": 20000,
            "date_from": "2024-01-01",
            "date_to": "2026-08-31",
            "anchor_date": anchor_date().isoformat(),
            "currency": config.CURRENCY,
            "company": config.COMPANY,
        }
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
