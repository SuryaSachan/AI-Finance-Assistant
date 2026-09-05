"""MySQL access layer via SQLAlchemy + PyMySQL.

Connects directly to the MySQL database specified by MYSQL_URI.
On first connection, creates MySQL views for enriched data access.
"""
from __future__ import annotations

import logging
import threading
from datetime import date
from functools import lru_cache

import pandas as pd
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from . import config

logger = logging.getLogger("app.db")

_lock = threading.Lock()
_engine: Engine | None = None


class DatabaseMissing(RuntimeError):
    pass


def _init_engine() -> Engine:
    """Create the SQLAlchemy engine and initialise MySQL views."""
    if not config.MYSQL_URI:
        raise DatabaseMissing(
            "MYSQL_URI is not configured. Set MYSQL_URI in .env "
            "(e.g. mysql+pymysql://user:pass@host:3306/db)"
        )

    uri = config.MYSQL_URI
    if uri.startswith("mysql://"):
        uri = uri.replace("mysql://", "mysql+pymysql://", 1)

    logger.info("Connecting to MySQL: %s", uri.split("@")[-1])
    engine = create_engine(uri, pool_recycle=3600, pool_pre_ping=True)

    @event.listens_for(engine, "connect")
    def _set_ansi_quotes(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute(
            "SET SESSION sql_mode = CONCAT(@@SESSION.sql_mode, ',ANSI_QUOTES')"
        )
        cursor.close()

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    logger.info("MySQL connection verified.")

    try:
        from . import views
        views.build(engine)
    except Exception:
        logger.warning("Could not create MySQL views", exc_info=True)

    return engine


def get_engine() -> Engine:
    global _engine
    with _lock:
        if _engine is None:
            _engine = _init_engine()
    return _engine


def query(sql: str, params: list | None = None) -> pd.DataFrame:
    """Execute a read query and return the result as a DataFrame.

    Positional ``?`` placeholders are converted to ``:_pN`` named parameters.
    """
    engine = get_engine()

    converted_sql = sql
    param_dict: dict = {}
    if params:
        for i, val in enumerate(params):
            pname = f"_p{i}"
            param_dict[pname] = val
            converted_sql = converted_sql.replace("?", f":{pname}", 1)

    with engine.connect() as conn:
        result = conn.execute(text(converted_sql), param_dict)
        if result.returns_rows:
            columns = list(result.keys())
            rows = result.fetchall()
            return pd.DataFrame(rows, columns=columns)
        return pd.DataFrame()


@lru_cache(maxsize=1)
def anchor_date() -> date:
    """The 'today' the assistant reasons against."""
    if config.ANCHOR_DATE:
        return date.fromisoformat(config.ANCHOR_DATE)
    df = query("SELECT max(transaction_date) AS d FROM transaction_base")
    return pd.Timestamp(df.iloc[0]["d"]).date()


@lru_cache(maxsize=1)
def counterparty_names() -> tuple[str, ...]:
    """Known counterparties for entity resolution."""
    df = query("SELECT counterparty FROM counterparties ORDER BY txn_count DESC LIMIT 20000")
    return tuple(df["counterparty"].tolist())


@lru_cache(maxsize=1)
def data_span() -> tuple[date, date]:
    df = query("SELECT min(transaction_date) AS a, max(transaction_date) AS b FROM transaction_base")
    return pd.Timestamp(df.iloc[0]["a"]).date(), pd.Timestamp(df.iloc[0]["b"]).date()


@lru_cache(maxsize=1)
def stats() -> dict:
    df = query(
        "SELECT (SELECT count(*) FROM transaction_base) AS transactions,"
        " (SELECT count(*) FROM account_base) AS accounts,"
        " (SELECT count(DISTINCT entity_id) FROM account_base) AS entities,"
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
