"""Derived columns.

The provided schema is three raw tables. Two things users constantly ask about
are not columns in it:

* **who the money went to** - only present inside the free-text `description`;
* **reconciliation state** - not present at all.

Both are derived here, with one SQL definition shared by the demo generator and
the real-dataset loader, so the derivation is identical whichever path built the
database. Every derived field is labelled DERIVED in the schema catalog and the
assistant states the definition whenever it filters on one.
"""
from __future__ import annotations

# Noise tokens that look like names but are rails, banks or bank jargon.
NOISE = (
    "NEFT", "IMPS", "RTGS", "INET", "INWD", "CHEQUE", "CHARGES", "DEPOSITS",
    "TRANSFER", "PAYMENT", "REVERSAL", "RETURN", "SALARY", "INTEREST",
)
_NOISE_SQL = ", ".join(f"'{n}'" for n in NOISE)

# Longest run of capitalised words in the narration = the counterparty.
# Written as list expressions (not a correlated subquery) so it stays vectorised.
def counterparty_sql(description: str = "description") -> str:
    return f"""
    COALESCE(
      substr(
        list_sort(
          list_transform(
            list_filter(
              list_transform(
                regexp_extract_all(upper(COALESCE({description}, '')), '[A-Z][A-Z]+(?:[ .&][A-Z]+)*'),
                x -> trim(regexp_replace(x, '\\s+', ' ', 'g'))
              ),
              x -> length(x) >= 6 AND x NOT IN ({_NOISE_SQL})
            ),
            x -> lpad(CAST(length(x) AS VARCHAR), 3, '0') || x
          ),
          'DESC'
        )[1],
        4
      ),
      'UNIDENTIFIED'
    )"""


CHANNELS = ("UPI", "NEFT", "IMPS", "RTGS", "FT", "CHEQUE", "ACH", "ATM", "CHARGES", "OTHER")


def channel_sql(description: str = "description") -> str:
    d = f"upper(COALESCE({description}, ''))"
    return f"""
    CASE
      WHEN {d} LIKE '%CHARGE%' OR {d} LIKE '%FEE%'          THEN 'CHARGES'
      WHEN {d} LIKE 'UPI%'  OR {d} LIKE '%/UPI/%'           THEN 'UPI'
      WHEN {d} LIKE 'NEFT%' OR {d} LIKE '%NEFT/%'           THEN 'NEFT'
      WHEN {d} LIKE 'IMPS%' OR {d} LIKE '%IMPS/%'           THEN 'IMPS'
      WHEN {d} LIKE 'RTGS%' OR {d} LIKE '%RTGS/%'           THEN 'RTGS'
      WHEN {d} LIKE 'FT %'  OR {d} LIKE 'FT-%'              THEN 'FT'
      WHEN {d} LIKE '%CHEQUE%' OR {d} LIKE '%CHQ%'          THEN 'CHEQUE'
      WHEN {d} LIKE '%NACH%' OR {d} LIKE '%ACH %'           THEN 'ACH'
      WHEN {d} LIKE '%ATM%'                                 THEN 'ATM'
      ELSE 'OTHER'
    END"""


RECONCILIATION_DEFINITION = (
    "This dataset has no reconciliation column. A transaction is treated as "
    "reconciled when it carries a bank reference (transaction_reference_id) or a "
    "UTR, and unreconciled when it carries neither."
)


def reconciliation_sql(reference: str = "transaction_reference_id", utr: str = "utr_number") -> str:
    return f"""
    CASE
      WHEN {reference} IS NOT NULL AND trim(CAST({reference} AS VARCHAR)) <> '' THEN 'reconciled'
      WHEN {utr}       IS NOT NULL AND trim(CAST({utr} AS VARCHAR)) <> ''       THEN 'reconciled'
      ELSE 'unreconciled'
    END"""


def masked_account_sql(account_number: str = "account_number") -> str:
    """Account numbers are sensitive: only the last four digits ever leave the DB."""
    return f"'XXXXXX' || right(CAST({account_number} AS VARCHAR), 4)"
