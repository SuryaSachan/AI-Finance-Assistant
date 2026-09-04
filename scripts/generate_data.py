"""Generate a realistic synthetic finance dataset into DuckDB.

Usage:
    python scripts/generate_data.py                     # ~250k transactions
    python scripts/generate_data.py --transactions 5000000 --csv

The generator is seeded, so the dataset is reproducible.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.schema_catalog import (  # noqa: E402
    CATEGORIES,
    DATASETS,
    DEPARTMENTS,
    PAYMENT_METHODS,
)

SEED = 42

VENDOR_STEMS = [
    "Acme", "Northgate", "Bluepeak", "Corewave", "Delta Ridge", "Everline", "Fathom",
    "Granite", "Helios", "Ironclad", "Juniper", "Kestrel", "Lumen", "Meridian",
    "Nimbus", "Orchid", "Pinnacle", "Quantum", "Redstone", "Summit", "Tessera",
    "Umbra", "Vertex", "Waypoint", "Xenon", "Yardley", "Zephyr", "Atlas",
    "Beacon", "Cobalt", "Dovetail", "Emberly", "Foxglove", "Glasshouse",
    "Harborview", "Inkwell", "Jetstream", "Kilnwood", "Larkspur", "Marlow",
]
VENDOR_SUFFIX = {
    "Software & SaaS": ["Software", "Systems", "Labs"],
    "Cloud & Hosting": ["Cloud", "Hosting", "Infra"],
    "Professional Services": ["Consulting", "Advisory", "Partners"],
    "Marketing": ["Media", "Creative", "Agency"],
    "Travel": ["Travel", "Voyages", "Mobility"],
    "Facilities": ["Facilities", "Estates", "Services"],
    "Logistics": ["Logistics", "Freight", "Supply Co"],
    "Hardware": ["Hardware", "Devices", "Electronics"],
    "Payroll Services": ["Payroll", "People Ops", "HRSolutions"],
    "Utilities": ["Utilities", "Power", "Energy"],
}

ACCOUNTS = [
    ("4000", "Product Revenue", "Revenue", None),
    ("4100", "Services Revenue", "Revenue", None),
    ("5000", "Software & Subscriptions", "Expense", "Software & SaaS"),
    ("5010", "Cloud Infrastructure", "Expense", "Cloud & Hosting"),
    ("5020", "Professional Fees", "Expense", "Professional Services"),
    ("5030", "Marketing & Advertising", "Expense", "Marketing"),
    ("5040", "Travel & Entertainment", "Expense", "Travel"),
    ("5050", "Rent & Facilities", "Expense", "Facilities"),
    ("5060", "Freight & Logistics", "Expense", "Logistics"),
    ("5070", "IT Hardware", "Expense", "Hardware"),
    ("5080", "Payroll Processing", "Expense", "Payroll Services"),
    ("5090", "Utilities", "Expense", "Utilities"),
    ("1000", "Operating Bank Account", "Asset", None),
    ("2000", "Accounts Payable", "Liability", None),
]


def month_starts(start: date, end: date) -> list[date]:
    out, cur = [], date(start.year, start.month, 1)
    while cur <= end:
        out.append(cur)
        cur = date(cur.year + (cur.month == 12), (cur.month % 12) + 1, 1)
    return out


def build_vendors(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for i, stem in enumerate(VENDOR_STEMS):
        cat = CATEGORIES[i % len(CATEGORIES)]
        suffix = VENDOR_SUFFIX[cat][i % len(VENDOR_SUFFIX[cat])]
        rows.append(
            {
                "vendor_id": f"V{1000 + i}",
                "vendor_name": f"{stem} {suffix}",
                "category": cat,
                "country": rng.choice(["US", "US", "US", "UK", "DE", "IN", "SG"]),
                "status": "active" if i % 13 else "inactive",
                "payment_terms": int(rng.choice([15, 30, 30, 45, 60])),
                "onboarded_date": date(2021, 1, 1) + timedelta(days=int(rng.integers(0, 1200))),
                # spend tier drives how big this vendor's transactions are
                "tier": int(rng.choice([1, 1, 1, 2, 2, 3], p=[0.25, 0.2, 0.2, 0.15, 0.12, 0.08])),
            }
        )
    return pd.DataFrame(rows)


def build_transactions(rng, vendors: pd.DataFrame, accounts: pd.DataFrame, n: int, start: date, end: date):
    months = month_starts(start, end)
    n_months = len(months)

    # gentle growth + seasonality so month-over-month comparisons are meaningful
    trend = np.linspace(0.8, 1.35, n_months)
    seasonality = 1 + 0.18 * np.sin(np.arange(n_months) / 12 * 2 * np.pi)
    weights = trend * seasonality
    weights = weights / weights.sum()

    m_idx = rng.choice(n_months, size=n, p=weights)
    month_start_ord = np.array([d.toordinal() for d in months])
    month_len = np.array(
        [
            (
                date(d.year + (d.month == 12), (d.month % 12) + 1, 1) - timedelta(days=1)
            ).day
            for d in months
        ]
    )
    day_off = (rng.random(n) * month_len[m_idx]).astype(int)
    ordinals = np.clip(month_start_ord[m_idx] + day_off, start.toordinal(), end.toordinal())
    txn_dates = pd.to_datetime([date.fromordinal(int(o)) for o in ordinals])

    # 8% of rows are revenue (no vendor); the rest are vendor spend
    is_revenue = rng.random(n) < 0.08

    v_weights = vendors["tier"].to_numpy(dtype=float) ** 2
    v_weights = v_weights / v_weights.sum()
    v_idx = rng.choice(len(vendors), size=n, p=v_weights)
    vendor_id = vendors["vendor_id"].to_numpy()[v_idx]
    vendor_cat = vendors["category"].to_numpy()[v_idx]
    tier = vendors["tier"].to_numpy()[v_idx]

    exp_accounts = accounts[accounts["account_type"] == "Expense"].set_index("category")
    acc_code = np.array([exp_accounts.loc[c, "account_code"] for c in vendor_cat])
    rev_codes = accounts[accounts["account_type"] == "Revenue"]["account_code"].to_numpy()

    category = vendor_cat.copy()
    vendor_id = vendor_id.astype(object)
    acc_code = acc_code.astype(object)
    vendor_id[is_revenue] = None
    category[is_revenue] = "Revenue"
    acc_code[is_revenue] = rng.choice(rev_codes, size=int(is_revenue.sum()))

    base = np.exp(rng.normal(6.1, 1.0, size=n)) * (tier ** 1.6)
    base = base * (1 + 0.35 * (m_idx / max(n_months - 1, 1)))
    amount = np.round(np.where(is_revenue, base * 3.2, base), 2)

    direction = np.where(is_revenue, "credit", "debit")
    refund = (~is_revenue) & (rng.random(n) < 0.03)
    direction[refund] = "credit"
    amount[refund] = -np.round(amount[refund] * 0.4, 2)

    status = rng.choice(["posted", "pending", "void"], size=n, p=[0.93, 0.055, 0.015])

    # unreconciled skews heavily toward the most recent 45 days (realistic backlog)
    recent = (end.toordinal() - ordinals) <= 45
    p_unrec = np.where(recent, 0.42, 0.07)
    unrec_roll = rng.random(n)
    recon = np.where(unrec_roll < p_unrec, "unreconciled", "reconciled")
    recon[(unrec_roll >= p_unrec) & (unrec_roll < p_unrec + 0.02)] = "disputed"
    recon[status == "void"] = "unreconciled"

    reconciled_ord = ordinals + rng.integers(1, 12, size=n)
    reconciled_date = np.where(
        recon == "reconciled",
        pd.to_datetime([date.fromordinal(int(min(o, end.toordinal()))) for o in reconciled_ord]),
        np.datetime64("NaT"),
    )

    dept = rng.choice(DEPARTMENTS, size=n)
    df = pd.DataFrame(
        {
            "txn_id": [f"T{i:09d}" for i in range(1, n + 1)],
            "txn_date": txn_dates,
            "posted_date": pd.to_datetime(
                [date.fromordinal(int(min(o + int(d), end.toordinal()))) for o, d in zip(ordinals, rng.integers(0, 4, n))]
            ),
            "vendor_id": vendor_id,
            "category": category,
            "department": dept,
            "cost_center": [f"CC-{d[:3].upper()}-{i%7+1:02d}" for i, d in enumerate(dept)],
            "account_code": acc_code,
            "description": None,
            "invoice_id": [f"INV-{i:08d}" for i in range(1, n + 1)],
            "amount": amount,
            "direction": direction,
            "payment_method": rng.choice(PAYMENT_METHODS, size=n, p=[0.45, 0.15, 0.2, 0.05, 0.15]),
            "status": status,
            "reconciliation_status": recon,
            "reconciled_date": reconciled_date,
            "currency": "USD",
        }
    )
    vname = vendors.set_index("vendor_id")["vendor_name"]
    df["description"] = [
        (f"{vname[v]} invoice settlement" if v else "Customer receipt")
        for v in df["vendor_id"]
    ]
    return df


def build_payouts(rng, vendors: pd.DataFrame, txns: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Vendor payment runs, derived from spend so totals stay coherent."""
    spend = txns[(txns["direction"] == "debit") & txns["vendor_id"].notna()].copy()
    spend["period"] = spend["txn_date"].dt.to_period("M")
    grp = spend.groupby(["vendor_id", "period"], observed=True).agg(
        total=("amount", "sum"), invoices=("txn_id", "count")
    ).reset_index()

    # split each vendor-month into 1-3 payout runs
    splits = rng.integers(1, 4, size=len(grp))
    rows = []
    pid = 1
    for (vid, period, total, inv), k in zip(grp.itertuples(index=False, name=None), splits):
        parts = rng.dirichlet(np.ones(k))
        for j in range(k):
            pdate = period.to_timestamp().date() + timedelta(days=int(rng.integers(2, 27)))
            if pdate > end:
                pdate = end
            rows.append(
                {
                    "payout_id": f"P{pid:08d}",
                    "payout_date": pdate,
                    "vendor_id": vid,
                    "amount": round(float(total * parts[j]), 2),
                    "invoice_count": max(1, int(inv * parts[j])),
                    "method": None,
                    "status": None,
                    "reference": f"PAY-{pid:08d}",
                    "reconciliation_status": None,
                }
            )
            pid += 1

    df = pd.DataFrame(rows)
    n = len(df)
    df["method"] = rng.choice(PAYMENT_METHODS, size=n, p=[0.5, 0.2, 0.1, 0.05, 0.15])
    df["payout_date"] = pd.to_datetime(df["payout_date"])
    recent = (pd.Timestamp(end) - df["payout_date"]).dt.days <= 30
    df["status"] = np.where(
        recent & (rng.random(n) < 0.35),
        rng.choice(["pending", "on_hold"], size=n, p=[0.8, 0.2]),
        rng.choice(["paid", "paid", "paid", "failed"], size=n, p=[0.34, 0.33, 0.31, 0.02]),
    )
    df["reconciliation_status"] = np.where(
        df["status"] != "paid",
        "unreconciled",
        rng.choice(["reconciled", "unreconciled", "disputed"], size=n, p=[0.9, 0.08, 0.02]),
    )
    df["currency"] = "USD"

    # --- inject a handful of genuine anomalies for the anomaly-callout feature ---
    if n > 50:
        anomaly_rows = rng.choice(n, size=min(6, n // 500 + 4), replace=False)
        df.loc[anomaly_rows, "amount"] = (df.loc[anomaly_rows, "amount"] * rng.uniform(6, 11, len(anomaly_rows))).round(2)
    return df


def build_bank_lines(rng, txns: pd.DataFrame, end: date) -> pd.DataFrame:
    matched = txns[txns["reconciliation_status"] == "reconciled"].sample(
        n=min(len(txns) // 3, 60000), random_state=SEED
    )
    m = pd.DataFrame(
        {
            "bank_line_id": [f"B{i:09d}" for i in range(1, len(matched) + 1)],
            "value_date": matched["txn_date"].to_numpy(),
            "bank_account": rng.choice(["OPERATING-1001", "PAYROLL-2002", "FX-3003"], size=len(matched), p=[0.75, 0.2, 0.05]),
            "description": matched["description"].to_numpy(),
            "amount": matched["amount"].to_numpy(),
            "direction": matched["direction"].to_numpy(),
            "matched_txn_id": matched["txn_id"].to_numpy(),
            "match_status": "matched",
        }
    )
    k = max(200, len(matched) // 40)
    start_ord = end.toordinal() - 120
    u = pd.DataFrame(
        {
            "bank_line_id": [f"B{i:09d}" for i in range(len(matched) + 1, len(matched) + k + 1)],
            "value_date": pd.to_datetime([date.fromordinal(int(o)) for o in rng.integers(start_ord, end.toordinal() + 1, k)]),
            "bank_account": rng.choice(["OPERATING-1001", "PAYROLL-2002", "FX-3003"], size=k),
            "description": rng.choice(
                ["BANK FEE", "FX ADJUSTMENT", "UNIDENTIFIED CREDIT", "CHARGEBACK", "INTEREST CREDIT"], size=k
            ),
            "amount": np.round(rng.normal(0, 4000, k), 2),
            "direction": rng.choice(["debit", "credit"], size=k),
            "matched_txn_id": None,
            "match_status": "unmatched",
        }
    )
    out = pd.concat([m, u], ignore_index=True)
    out["currency"] = "USD"
    return out


def data_dictionary() -> pd.DataFrame:
    rows = []
    for ds in DATASETS.values():
        for f in ds.fields:
            rows.append(
                {
                    "dataset": ds.key,
                    "view": ds.view,
                    "field": f.name,
                    "type": f.kind,
                    "description": f.desc,
                    "allowed_values": ", ".join(f.values) if f.values else None,
                }
            )
    return pd.DataFrame(rows)


VIEWS_SQL = """
CREATE OR REPLACE VIEW v_transactions AS
SELECT t.txn_id, CAST(t.txn_date AS DATE) AS txn_date, CAST(t.posted_date AS DATE) AS posted_date,
       t.vendor_id,
       COALESCE(v.vendor_name, 'Unassigned / Internal') AS vendor_name,
       t.category, t.department, t.cost_center,
       t.account_code, a.account_name, a.account_type,
       t.description, t.invoice_id, t.amount, t.direction, t.payment_method,
       t.status, t.reconciliation_status, CAST(t.reconciled_date AS DATE) AS reconciled_date, t.currency
FROM transactions t
LEFT JOIN vendors v USING (vendor_id)
LEFT JOIN chart_of_accounts a USING (account_code);

CREATE OR REPLACE VIEW v_vendor_payouts AS
SELECT p.payout_id, CAST(p.payout_date AS DATE) AS payout_date, p.vendor_id, v.vendor_name, v.category,
       p.amount, p.status, p.method, p.invoice_count, p.reference,
       p.reconciliation_status, p.currency
FROM vendor_payouts p
LEFT JOIN vendors v USING (vendor_id);

CREATE OR REPLACE VIEW v_bank_lines AS
SELECT bank_line_id, CAST(value_date AS DATE) AS value_date, bank_account, description, amount, direction,
       matched_txn_id, match_status, currency
FROM bank_lines;
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transactions", type=int, default=250_000)
    ap.add_argument("--months", type=int, default=30)
    ap.add_argument("--end", type=str, default=date.today().isoformat())
    ap.add_argument("--db", type=str, default=str(ROOT / "data" / "finance.duckdb"))
    ap.add_argument("--csv", action="store_true", help="also export CSV extracts")
    args = ap.parse_args()

    end = date.fromisoformat(args.end)
    start = date(end.year, end.month, 1) - timedelta(days=31 * (args.months - 1))
    start = date(start.year, start.month, 1)
    rng = np.random.default_rng(SEED)

    print(f"Generating {args.transactions:,} transactions from {start} to {end} ...")
    vendors = build_vendors(rng)
    accounts = pd.DataFrame(ACCOUNTS, columns=["account_code", "account_name", "account_type", "category"])
    txns = build_transactions(rng, vendors, accounts, args.transactions, start, end)
    payouts = build_payouts(rng, vendors, txns, start, end)
    bank = build_bank_lines(rng, txns, end)
    ddict = data_dictionary()

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    con = duckdb.connect(str(db_path))
    for name, df in [
        ("vendors", vendors.drop(columns=["tier"])),
        ("chart_of_accounts", accounts),
        ("transactions", txns),
        ("vendor_payouts", payouts),
        ("bank_lines", bank),
        ("data_dictionary", ddict),
    ]:
        con.register("tmp_df", df)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM tmp_df")
        con.unregister("tmp_df")
        print(f"  {name:<20} {len(df):>10,} rows")

    con.execute("CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(txn_date)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_txn_vendor ON transactions(vendor_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_payout_date ON vendor_payouts(payout_date)")
    con.execute(VIEWS_SQL)
    con.close()

    if args.csv:
        out = db_path.parent / "csv"
        out.mkdir(exist_ok=True)
        vendors.drop(columns=["tier"]).to_csv(out / "vendors.csv", index=False)
        accounts.to_csv(out / "chart_of_accounts.csv", index=False)
        ddict.to_csv(out / "data_dictionary.csv", index=False)
        txns.to_csv(out / "transactions.csv", index=False)
        payouts.to_csv(out / "vendor_payouts.csv", index=False)
        bank.to_csv(out / "bank_lines.csv", index=False)
        print(f"CSV extracts written to {out}")

    print(f"\nDone -> {db_path}")


if __name__ == "__main__":
    main()
