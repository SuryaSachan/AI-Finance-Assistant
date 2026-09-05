"""Single source of truth for what the assistant is allowed to query.

Everything downstream (prompting, plan validation, SQL generation) reads from
here.  A field that is not listed here can never reach the database, which is
what makes the SQL layer injection-proof and the answers schema-grounded.

Mapped to the provided schema: `bank` -> `account` -> `transaction`.
Fields marked DERIVED are computed in `app/derivations.py`, not raw columns.
Sensitive columns (`account_number`, `utr_number`) are deliberately absent:
only a masked account number is exposed, and the UTR never leaves the database.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .derivations import CHANNELS

FieldKind = Literal["date", "number", "text", "enum", "id"]


@dataclass(frozen=True)
class Field:
    name: str
    kind: FieldKind
    desc: str
    values: tuple[str, ...] = ()
    groupable: bool = True


@dataclass(frozen=True)
class Dataset:
    key: str
    view: str
    label: str
    desc: str
    date_field: str | None
    amount_field: str
    fields: tuple[Field, ...]
    default_columns: tuple[str, ...] = ()
    entity_field: str | None = None  # what anomaly detection groups by

    @property
    def field_map(self) -> dict[str, Field]:
        return {f.name: f for f in self.fields}


TXN_TYPES = ("credit", "debit")
RECON_STATUS = ("reconciled", "unreconciled")
BANK_CODES = ("HDFC", "ICIC", "SBIN", "UTIB", "KKBK", "CNRB", "UBIN", "AUBL", "TMBL", "RATN")

TRANSACTIONS = Dataset(
    key="transactions",
    view="v_transactions",
    label="transactions",
    desc=(
        "Every credit and debit across all accounts. Use for spend, payouts, receipts, "
        "counterparty questions and reconciliation."
    ),
    date_field="transaction_date",
    amount_field="amount",
    entity_field="counterparty",
    default_columns=(
        "transaction_id",
        "transaction_date",
        "counterparty",
        "transaction_type",
        "amount",
        "channel",
        "bank_name",
        "account_number_masked",
        "reconciliation_status",
        "description",
    ),
    fields=(
        Field("transaction_id", "id", "Unique transaction id", groupable=False),
        Field("transaction_date", "date", "Date the transaction posted"),
        Field("transaction_type", "enum", "debit = money out, credit = money in", TXN_TYPES),
        Field("amount", "number", "Transaction amount in INR, always positive", groupable=False),
        Field("counterparty", "text", "DERIVED: payee/payer name parsed out of the description"),
        Field("channel", "enum", "DERIVED: payment rail parsed from the description", CHANNELS),
        Field("description", "text", "Raw bank narration", groupable=False),
        Field(
            "reconciliation_status",
            "enum",
            "DERIVED: reconciled = has a bank reference or UTR; unreconciled = has neither",
            RECON_STATUS,
        ),
        Field("reference_id", "id", "Bank reference / receipt number (plaintext)", groupable=False),
        Field("account_id", "id", "Account the transaction belongs to"),
        Field("account_number_masked", "text", "Account number, last 4 digits only"),
        Field("entity_id", "id", "Customer entity that owns the account"),
        Field("program_id", "number", "Product/program the account belongs to"),
        Field("bank_code", "enum", "Bank IFSC prefix", BANK_CODES),
        Field("bank_name", "text", "Full bank name"),
    ),
)

ACCOUNTS = Dataset(
    key="accounts",
    view="v_accounts",
    label="accounts",
    desc="One row per account with its current balance. Use for balance questions and account count questions, not for spend.",
    date_field=None,
    amount_field="available_balance",
    default_columns=(
        "account_id",
        "account_number_masked",
        "bank_name",
        "program_id",
        "available_balance",
        "entity_id",
    ),
    fields=(
        Field("account_id", "id", "Unique account id"),
        Field("account_number_masked", "text", "Account number, last 4 digits only"),
        Field("entity_id", "id", "Customer entity that owns the account"),
        Field("program_id", "number", "Product/program the account belongs to"),
        Field("available_balance", "number", "Current available balance in INR", groupable=False),
        Field("bank_code", "enum", "Bank IFSC prefix", BANK_CODES),
        Field("bank_name", "text", "Full bank name"),
    ),
)

DATASETS: dict[str, Dataset] = {d.key: d for d in (TRANSACTIONS, ACCOUNTS)}

AGGREGATIONS = ("sum", "count", "avg", "min", "max", "count_distinct")
OPERATORS = ("eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "between", "contains", "is_null", "not_null")
INTENTS = ("aggregate", "list", "trend", "compare", "anomaly", "clarify", "unsupported")


def schema_prompt() -> str:
    """Compact schema description injected into the planner prompt.

    Kept deliberately terse: small models degrade fast with long prompts.
    """
    out: list[str] = []
    for ds in DATASETS.values():
        cols = []
        for f in ds.fields:
            if f.kind == "enum" and f.values:
                cols.append(f"{f.name}[{'|'.join(f.values)}]")
            else:
                cols.append(f"{f.name}:{f.kind}")
        out.append(f"- {ds.key} ({ds.desc})\n  fields: {', '.join(cols)}")
    return "\n".join(out)
