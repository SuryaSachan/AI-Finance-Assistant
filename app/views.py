"""Build the two views the assistant queries, from the three provided tables.

`bank` / `account` / `transaction` go in; `v_transactions` and `v_accounts`
come out. Derived columns are materialised once into `txn_enriched` so that
query time stays a plain scan.

Both the demo data generator and the real-dataset loader call `build()`, so the
derivations are guaranteed identical whichever path created the database.

When AES-256-SIV encryption is enabled, account_number and utr_number are
stored as ciphertext in the raw tables. Python UDFs registered here handle
transparent decryption when building the views.
"""
from __future__ import annotations

import duckdb

from .derivations import channel_sql, counterparty_sql, masked_account_sql, reconciliation_sql
from .encryption import decrypt, enabled as enc_enabled

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


def build(con: duckdb.DuckDBPyConnection, overrides: dict | None = None) -> None:
    c = merge_columns(overrides)
    t, a, b = c["transaction"], c["account"], c["bank"]

    # ── Register Python UDF for transparent decryption ──────────────
    if enc_enabled():
        con.create_function("decrypt_field", decrypt, [duckdb.typing.VARCHAR], duckdb.typing.VARCHAR)

        # When encrypted: decrypt utr_number before checking reconciliation status
        recon_expr = reconciliation_sql(
            t["transaction_reference_id"],
            f"decrypt_field({t['utr_number']})",
        )
        # When encrypted: decrypt account_number before masking
        mask_acct_expr = masked_account_sql(f"decrypt_field(ac.{a['account_number']})")
    else:
        recon_expr = reconciliation_sql(t["transaction_reference_id"], t["utr_number"])
        mask_acct_expr = masked_account_sql("ac." + a["account_number"])

    con.execute(
        f"""
        CREATE OR REPLACE TABLE txn_enriched AS
        SELECT
            {t['transaction_id']}                              AS transaction_id,
            {t['account_id']}                                  AS account_id,
            CAST({t['transaction_date']} AS DATE)              AS transaction_date,
            lower(CAST({t['transaction_type']} AS VARCHAR))    AS transaction_type,
            CAST({t['description']} AS VARCHAR)                AS description,
            CAST({t['transaction_amount']} AS DOUBLE)          AS amount,
            CAST({t['transaction_reference_id']} AS VARCHAR)   AS reference_id,
            {counterparty_sql(t['description'])}               AS counterparty_raw,
            {channel_sql(t['description'])}                    AS channel,
            {recon_expr}                                       AS reconciliation_status
        FROM {t['table']}
        """
    )

    # Real narrations spell the same counterparty with and without spaces
    # (SELECTION MOBILE vs SELECTIONMOBILE). Fold them onto one canonical name,
    # preferring the spaced spelling, so grouping does not split a merchant in two.
    con.execute(
        """
        CREATE OR REPLACE TABLE counterparty_map AS
        WITH variants AS (
            SELECT counterparty_raw AS cp,
                   replace(counterparty_raw, ' ', '') AS squashed,
                   count(*) AS n
            FROM txn_enriched
            GROUP BY 1, 2
        )
        SELECT squashed,
               arg_max(cp, n * CASE WHEN cp LIKE '% %' THEN 2 ELSE 1 END) AS canonical
        FROM variants
        GROUP BY 1
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE txn_enriched AS
        SELECT e.* EXCLUDE (counterparty_raw),
               CASE WHEN e.channel = 'CHARGES' THEN 'BANK CHARGES'
                    ELSE COALESCE(m.canonical, e.counterparty_raw) END AS counterparty
        FROM txn_enriched e
        LEFT JOIN counterparty_map m ON replace(e.counterparty_raw, ' ', '') = m.squashed
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_txn_date ON txn_enriched(transaction_date)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_txn_cp ON txn_enriched(counterparty)")

    con.execute(
        f"""
        CREATE OR REPLACE VIEW v_transactions AS
        SELECT
            e.transaction_id, e.transaction_date, e.transaction_type, e.amount,
            e.counterparty, e.channel, e.description, e.reconciliation_status, e.reference_id,
            e.account_id,
            {mask_acct_expr} AS account_number_masked,
            ac.{a['entity_id']}   AS entity_id,
            ac.{a['program_id']}  AS program_id,
            ac.{a['bank_code']}   AS bank_code,
            bk.{b['bank_name']}   AS bank_name
        FROM txn_enriched e
        LEFT JOIN {a['table']} ac ON e.account_id = ac.{a['account_id']}
        LEFT JOIN {b['table']} bk ON ac.{a['bank_code']} = bk.{b['bank_code']}
        """
    )

    con.execute(
        f"""
        CREATE OR REPLACE VIEW v_accounts AS
        SELECT
            ac.{a['account_id']} AS account_id,
            {mask_acct_expr} AS account_number_masked,
            ac.{a['entity_id']}          AS entity_id,
            ac.{a['program_id']}         AS program_id,
            CAST(ac.{a['available_balance']} AS DOUBLE) AS available_balance,
            ac.{a['bank_code']}          AS bank_code,
            bk.{b['bank_name']}          AS bank_name
        FROM {a['table']} ac
        LEFT JOIN {b['table']} bk ON ac.{a['bank_code']} = bk.{b['bank_code']}
        """
    )

    # Counterparty list used for entity resolution and for refusing unknown names.
    con.execute(
        """
        CREATE OR REPLACE TABLE counterparties AS
        SELECT counterparty, count(*) AS txn_count, sum(amount) AS total_amount
        FROM txn_enriched
        WHERE counterparty <> 'UNIDENTIFIED'
        GROUP BY 1
        ORDER BY txn_count DESC
        """
    )
