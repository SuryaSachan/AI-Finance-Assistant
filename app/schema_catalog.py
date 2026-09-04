"""Single source of truth for what the assistant is allowed to query.

Everything downstream (prompting, plan validation, SQL generation) reads from
here.  A field that is not listed here can never reach the database, which is
what makes the SQL layer injection-proof and the answers schema-grounded.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

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
    date_field: str
    amount_field: str
    fields: tuple[Field, ...]
    default_columns: tuple[str, ...] = ()

    @property
    def field_map(self) -> dict[str, Field]:
        return {f.name: f for f in self.fields}


TXN_STATUS = ("posted", "pending", "void")
RECON_STATUS = ("reconciled", "unreconciled", "disputed")
PAYOUT_STATUS = ("paid", "pending", "failed", "on_hold")
DIRECTION = ("debit", "credit")
CATEGORIES = (
    "Software & SaaS",
    "Cloud & Hosting",
    "Professional Services",
    "Marketing",
    "Travel",
    "Facilities",
    "Logistics",
    "Hardware",
    "Payroll Services",
    "Utilities",
)
# revenue rows carry no vendor, so they get their own category value
TXN_CATEGORIES = CATEGORIES + ("Revenue",)
DEPARTMENTS = ("Engineering", "Sales", "Marketing", "Finance", "Operations", "HR", "Support")
PAYMENT_METHODS = ("ACH", "Wire", "Card", "Cheque", "UPI")

TRANSACTIONS = Dataset(
    key="transactions",
    view="v_transactions",
    label="Transactions (general ledger)",
    desc="Every posted/pending ledger entry: spend, revenue, refunds. Use for 'spend', 'expenses', 'transactions', 'reconciliation'.",
    date_field="txn_date",
    amount_field="amount",
    default_columns=(
        "txn_id",
        "txn_date",
        "vendor_name",
        "category",
        "department",
        "account_name",
        "amount",
        "status",
        "reconciliation_status",
    ),
    fields=(
        Field("txn_id", "id", "Unique transaction id", groupable=False),
        Field("txn_date", "date", "Date the transaction occurred"),
        Field("posted_date", "date", "Date it hit the ledger"),
        Field("vendor_id", "id", "Vendor id"),
        Field("vendor_name", "text", "Vendor / counterparty name"),
        Field("category", "enum", "Spend category", TXN_CATEGORIES),
        Field("department", "enum", "Owning department", DEPARTMENTS),
        Field("cost_center", "text", "Cost centre code"),
        Field("account_code", "text", "Chart-of-accounts code"),
        Field("account_name", "text", "Chart-of-accounts name"),
        Field("account_type", "enum", "Account type", ("Expense", "Revenue", "Asset", "Liability")),
        Field("description", "text", "Free-text memo", groupable=False),
        Field("invoice_id", "id", "Linked invoice reference", groupable=False),
        Field("amount", "number", "Signed amount in USD (negative = credit/refund)", groupable=False),
        Field("direction", "enum", "debit = money out, credit = money in", DIRECTION),
        Field("payment_method", "enum", "How it was paid", PAYMENT_METHODS),
        Field("status", "enum", "Ledger status", TXN_STATUS),
        Field("reconciliation_status", "enum", "Bank reconciliation state", RECON_STATUS),
        Field("reconciled_date", "date", "Date it was reconciled (null if not)"),
    ),
)

VENDOR_PAYOUTS = Dataset(
    key="vendor_payouts",
    view="v_vendor_payouts",
    label="Vendor payouts",
    desc="Money actually disbursed to vendors (payment runs). Use for 'payouts', 'paid to vendor', 'pending payments'.",
    date_field="payout_date",
    amount_field="amount",
    default_columns=(
        "payout_id",
        "payout_date",
        "vendor_name",
        "category",
        "amount",
        "status",
        "method",
        "reconciliation_status",
    ),
    fields=(
        Field("payout_id", "id", "Unique payout id", groupable=False),
        Field("payout_date", "date", "Date the payout was initiated"),
        Field("vendor_id", "id", "Vendor id"),
        Field("vendor_name", "text", "Vendor receiving the payout"),
        Field("category", "enum", "Vendor category", CATEGORIES),
        Field("amount", "number", "Payout amount in USD", groupable=False),
        Field("status", "enum", "Payout status", PAYOUT_STATUS),
        Field("method", "enum", "Disbursement rail", PAYMENT_METHODS),
        Field("invoice_count", "number", "Number of invoices settled", groupable=False),
        Field("reference", "text", "Bank reference", groupable=False),
        Field("reconciliation_status", "enum", "Bank reconciliation state", RECON_STATUS),
    ),
)

BANK_LINES = Dataset(
    key="bank_lines",
    view="v_bank_lines",
    label="Bank statement lines",
    desc="Raw bank feed lines. Use only for questions about unmatched bank entries / statement vs ledger.",
    date_field="value_date",
    amount_field="amount",
    default_columns=(
        "bank_line_id",
        "value_date",
        "bank_account",
        "description",
        "amount",
        "match_status",
        "matched_txn_id",
    ),
    fields=(
        Field("bank_line_id", "id", "Bank line id", groupable=False),
        Field("value_date", "date", "Bank value date"),
        Field("bank_account", "enum", "Bank account", ("OPERATING-1001", "PAYROLL-2002", "FX-3003")),
        Field("description", "text", "Bank narration", groupable=False),
        Field("amount", "number", "Signed bank amount in USD", groupable=False),
        Field("direction", "enum", "debit = money out, credit = money in", DIRECTION),
        Field("matched_txn_id", "id", "Ledger transaction it matched to (null if unmatched)", groupable=False),
        Field("match_status", "enum", "Matching state", ("matched", "unmatched")),
    ),
)

DATASETS: dict[str, Dataset] = {
    d.key: d for d in (TRANSACTIONS, VENDOR_PAYOUTS, BANK_LINES)
}

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
