"""Build MySQL views for enriched data access.

Creates views on the MySQL server that the assistant queries.
Derivation logic (counterparty extraction, channel detection, reconciliation
status) is expressed in MySQL-compatible SQL (MySQL 8.0+).
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from .derivations import channel_sql, counterparty_sql, masked_account_sql, reconciliation_sql

logger = logging.getLogger("app.views")

DEFAULT_COLUMNS: dict[str, dict[str, str]] = {
    "transaction": {
        "table": "transaction",
        "transaction_id": "transaction_id",
        "account_id": "account_id",
        "transaction_date": "transaction_date",
        "transaction_type": "transaction_type",
        "description": "description",
        "transaction_amount": "transaction_amount",
        "transaction_reference_id": "transaction_reference_id",
        "utr_number": "utr_number",
    },
    "account": {
        "table": "account",
        "account_id": "account_id",
        "entity_id": "entity_id",
        "account_number": "account_number",
        "program_id": "program_id",
        "available_balance": "available_balance",
        "bank_code": "bank_code",
    },
    "bank": {
        "table": "bank",
        "bank_code": "bank_code",
        "bank_name": "bank_name",
    },
}


def merge_columns(overrides: dict | None) -> dict[str, dict[str, str]]:
    merged = {k: dict(v) for k, v in DEFAULT_COLUMNS.items()}
    for table, cols in (overrides or {}).items():
        if table in merged and cols:
            merged[table].update(cols)
    return merged


def build(engine, overrides: dict | None = None) -> None:
    """Create MySQL views for the enriched analytics layer."""
    c = merge_columns(overrides)
    t, a, b = c["transaction"], c["account"], c["bank"]

    recon_expr = reconciliation_sql(t["transaction_reference_id"], t["utr_number"])
    mask_expr = masked_account_sql(a["account_number"])

    with engine.connect() as conn:
        # ── 0. Base views ──
        conn.execute(text(
            f"CREATE OR REPLACE VIEW transaction_base AS SELECT * FROM `{t['table']}`"
        ))
        conn.execute(text(
            f"CREATE OR REPLACE VIEW account_base AS SELECT * FROM `{a['table']}`"
        ))

        # ── 1. Enriched transaction view ──
        conn.execute(text(f"""
            CREATE OR REPLACE VIEW txn_raw AS
            SELECT
                {t['transaction_id']}                              AS transaction_id,
                {t['account_id']}                                  AS account_id,
                CAST({t['transaction_date']} AS DATE)              AS transaction_date,
                LOWER(CAST({t['transaction_type']} AS CHAR))       AS transaction_type,
                CAST({t['description']} AS CHAR(2000))             AS description,
                CAST({t['transaction_amount']} AS DECIMAL(20,4))   AS amount,
                CAST({t['transaction_reference_id']} AS CHAR(200)) AS reference_id,
                {counterparty_sql(t['description'])}               AS counterparty_raw,
                {channel_sql(t['description'])}                    AS channel,
                {recon_expr}                                       AS reconciliation_status
            FROM `{t['table']}`
        """))

        conn.execute(text("""
            CREATE OR REPLACE VIEW txn_enriched AS
            SELECT
                e.transaction_id, e.account_id, e.transaction_date,
                e.transaction_type, e.description, e.amount,
                e.reference_id, e.channel, e.reconciliation_status,
                CASE WHEN e.channel = 'CHARGES' THEN 'BANK CHARGES'
                     ELSE e.counterparty_raw END AS counterparty
            FROM txn_raw e
        """))

        # ── 2. Masked-account view ──
        conn.execute(text(f"""
            CREATE OR REPLACE VIEW account_masked AS
            SELECT
                {a['account_id']}                                  AS account_id,
                {mask_expr}                                        AS account_number_masked,
                {a['entity_id']}                                   AS entity_id,
                {a['program_id']}                                  AS program_id,
                CAST({a['available_balance']} AS DECIMAL(20,4))    AS available_balance,
                {a['bank_code']}                                   AS bank_code
            FROM `{a['table']}`
        """))

        # ── 3. Main query views ──
        conn.execute(text(f"""
            CREATE OR REPLACE VIEW v_transactions AS
            SELECT
                e.transaction_id, e.transaction_date, e.transaction_type,
                e.amount, e.counterparty, e.channel, e.description,
                e.reconciliation_status, e.reference_id, e.account_id,
                am.account_number_masked, am.entity_id,
                am.program_id, am.bank_code,
                bk.{b['bank_name']}   AS bank_name
            FROM txn_enriched e
            LEFT JOIN account_masked am ON e.account_id = am.account_id
            LEFT JOIN `{b['table']}` bk ON am.bank_code = bk.{b['bank_code']}
        """))

        conn.execute(text(f"""
            CREATE OR REPLACE VIEW v_accounts AS
            SELECT
                am.account_id, am.account_number_masked, am.entity_id,
                am.program_id, am.available_balance, am.bank_code,
                bk.{b['bank_name']}   AS bank_name
            FROM account_masked am
            LEFT JOIN `{b['table']}` bk ON am.bank_code = bk.{b['bank_code']}
        """))

        # ── 4. Monthly rollup views ──
        conn.execute(text("""
            CREATE OR REPLACE VIEW rollup_monthly AS
            SELECT
                account_id,
                DATE_FORMAT(transaction_date, '%Y-%m') AS txn_month,
                transaction_type, counterparty,
                SUM(amount)  AS sum_amount,
                COUNT(*)     AS record_count,
                MIN(amount)  AS min_amount,
                MAX(amount)  AS max_amount
            FROM txn_enriched
            GROUP BY account_id, DATE_FORMAT(transaction_date, '%Y-%m'),
                     transaction_type, counterparty
        """))

        conn.execute(text(f"""
            CREATE OR REPLACE VIEW v_rollup_monthly AS
            SELECT
                r.account_id, r.txn_month, r.transaction_type,
                r.counterparty, r.sum_amount, r.record_count,
                r.min_amount, r.max_amount,
                am.account_number_masked, am.entity_id,
                am.program_id, am.bank_code,
                bk.{b['bank_name']}   AS bank_name
            FROM rollup_monthly r
            LEFT JOIN account_masked am ON r.account_id = am.account_id
            LEFT JOIN `{b['table']}` bk ON am.bank_code = bk.{b['bank_code']}
        """))

        # ── 5. Counterparty summary view ──
        conn.execute(text("""
            CREATE OR REPLACE VIEW counterparties AS
            SELECT counterparty, COUNT(*) AS txn_count, SUM(amount) AS total_amount
            FROM txn_enriched
            WHERE counterparty <> 'UNIDENTIFIED'
            GROUP BY counterparty
        """))

        conn.commit()

    logger.info("MySQL views created/updated successfully.")
