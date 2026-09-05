"""Generate a stand-in dataset in the *official* schema (bank / account / transaction).

Descriptions follow the narration formats in the provided sample data, so the
counterparty and channel derivations are exercised the same way they will be on
the real export.

    python scripts/generate_data.py                       # ~250k transactions
    python scripts/generate_data.py --transactions 20000000 --csv
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

from app import views  # noqa: E402

SEED = 42

BANKS = [
    ("HDFC", "HDFC BANK LIMITED"),
    ("ICIC", "ICICI BANK LIMITED"),
    ("SBIN", "STATE BANK OF INDIA"),
    ("UTIB", "AXIS BANK LIMITED"),
    ("KKBK", "KOTAK MAHINDRA BANK LIMITED"),
    ("CNRB", "CANARA BANK"),
    ("UBIN", "UNION BANK OF INDIA"),
    ("AUBL", "AU SMALL FINANCE BANK LIMITED"),
    ("TMBL", "TAMILNAD MERCANTILE BANK LIMITED"),
    ("RATN", "RBL BANK LIMITED"),
]

MERCHANTS = [
    "SELECTION ELECTRONICS", "SELECTRICITY TWO PRIVATE LIMITED", "NAVYUG SELECTION",
    "UMANG SELECTION", "SELECTION MOBILE", "SELECTIONMALIGAI", "RELIANCEDIGITAL RETAIL LTD",
    "BAJAJ FINANCE LIMITED", "TATA CAPITAL LIMITED", "VODAFONE IDEA LIMITED",
    "BHARTI AIRTEL LIMITED", "AMAZON SELLER SERVICES", "FLIPKART INTERNET PRIVATE",
    "SWIGGY BUNDL TECHNOLOGIES", "ZOMATO LIMITED", "INDIAN OIL CORPORATION",
    "ADANI ELECTRICITY MUMBAI", "TATA POWER COMPANY LIMITED", "MAHANAGAR GAS LIMITED",
    "GODREJ PROPERTIES LIMITED", "ASIAN PAINTS LIMITED", "PIDILITE INDUSTRIES LIMITED",
    "HAVELLS INDIA LIMITED", "VOLTAS LIMITED", "BLUE STAR LIMITED",
    "CROMPTON GREAVES CONSUMER", "SUPREME INDUSTRIES LIMITED", "FINOLEX CABLES LIMITED",
    "POLYCAB INDIA LIMITED", "KEI INDUSTRIES LIMITED", "ORIENT ELECTRIC LIMITED",
    "SYMPHONY LIMITED", "WHIRLPOOL OF INDIA LIMITED", "IFB INDUSTRIES LIMITED",
    "BATA INDIA LIMITED", "TRENT LIMITED", "SHOPPERS STOP LIMITED",
    "VISHAL MEGA MART PRIVATE", "METRO CASH AND CARRY", "SPENCERS RETAIL LIMITED",
    "MORE MEGASTORE PRIVATE", "DMART AVENUE SUPERMARTS", "STAR BAZAAR TRENT HYPERMARKET",
    "ARVIND FASHIONS LIMITED", "RAYMOND LIFESTYLE LIMITED", "PAGE INDUSTRIES LIMITED",
]

PEOPLE = [
    "PARESH VIKRANT GHASE", "GAUTAM SINGH", "RAMESH KUMAR SHARMA", "PRIYA NAIR MENON",
    "ANIL BABURAO PATIL", "SUNITA DEVI YADAV", "MOHAMMED IRFAN QURESHI", "DEEPAK RANJAN DAS",
    "KAVITA SURESH IYER", "RAJESH MOHAN PILLAI", "NEHA SANJAY KULKARNI", "VIKRAM ADITYA RAO",
]

AREAS = ["DAHISAR EAST", "SAKET DELHI", "KORAMANGALA BLR", "ANNA NAGAR CHN", "SALT LAKE KOL",
         "HITEC CITY HYD", "VASTRAPUR AHM", "KOTHRUD PUNE", "GOMTI NAGAR LKO", "RAJOURI GARDEN"]

CHARGE_NARRATIONS = [
    "IMPS charges", "NEFT Return Charges", "Cheque Deposits", "ATM WDL CHARGES",
    "SMS ALERT CHARGES", "MIN BALANCE CHARGES", "RTGS PROCESSING FEE", "ACH DEBIT RETURN CHARGES",
]


def build_banks() -> pd.DataFrame:
    return pd.DataFrame(BANKS, columns=["bank_code", "bank_name"])


def build_accounts(rng: np.random.Generator, n_accounts: int, n_entities: int) -> pd.DataFrame:
    codes = [b[0] for b in BANKS]
    rows = []
    for i in range(n_accounts):
        rows.append(
            {
                "account_id": f"{i:08x}-0000-4000-8000-{rng.integers(0, 16**12):012x}",
                "entity_id": f"e{i % n_entities:07x}-0000-4000-8000-{(i % n_entities):012x}",
                "account_number": str(rng.integers(10**13, 10**14)),
                "program_id": int(rng.choice([21, 4, 46], p=[0.5, 0.3, 0.2])),
                "available_balance": round(float(rng.normal(2.5e7, 6e7)), 2),
                "bank_code": codes[i % len(codes)],
            }
        )
    return pd.DataFrame(rows)


def _narrations(rng, n, merchant_idx, person_idx, kind, bank_codes, acct_numbers):
    """Build bank-style narration strings matching the provided sample formats."""
    merch = np.array(MERCHANTS)[merchant_idx]
    ppl = np.array(PEOPLE)[person_idx]
    area = rng.choice(AREAS, size=n)
    ifsc = np.array([f"{c}000{d:04d}" for c, d in zip(bank_codes, rng.integers(1000, 3000, n))])
    r1 = rng.integers(10**7, 10**8, n)
    r2 = rng.integers(10**11, 10**12, n)
    r3 = rng.integers(1000, 9999, n)

    out = np.empty(n, dtype=object)
    for i in range(n):
        k = kind[i]
        if k == 0:
            out[i] = f"FT -  {r1[i]} -  {acct_numbers[i]} - {merch[i]}   {area[i]}"
        elif k == 1:
            out[i] = f"UPI-{merch[i]}-XXXXXX{r3[i]}-{ifsc[i]}-{r2[i]}-{r2[i]}"
        elif k == 2:
            out[i] = f"NEFT  - {ifsc[i]} - {r1[i]} - {acct_numbers[i]} - {merch[i]}"
        elif k == 3:
            out[i] = f"NEFT/{r2[i]}/{bank_codes[i]}/{ppl[i]}"
        elif k == 4:
            out[i] = (
                f"IMPS/P2A/{r2[i]}/{bank_codes[i]}/{acct_numbers[i]}/00/INET/{r3[i]}/"
                f"{merch[i].replace(' ', '')}/ZBFLCTP{r3[i]}L2PBL{r1[i]}/INWD48"
            )
        elif k == 5:
            out[i] = f"IMPS OW/{r2[i]}/{ppl[i].title()}/{bank_codes[i]}/{acct_numbers[i]}"
        elif k == 6:
            ref = f"RATNR5{r2[i]}"
            out[i] = f"R/{ref}/ZBFLCTP{r3[i]}PBL{r1[i]}//{merch[i]}/{ref} /{merch[i]}"
        elif k == 7:
            out[i] = f"RTGS  - {ifsc[i]} - {r1[i]} - {merch[i]}"
        else:
            out[i] = CHARGE_NARRATIONS[i % len(CHARGE_NARRATIONS)]
    return out


def build_transactions(rng, accounts: pd.DataFrame, n: int, start: date, end: date) -> pd.DataFrame:
    n_months = (end.year - start.year) * 12 + (end.month - start.month) + 1
    months = [pd.Timestamp(start) + pd.DateOffset(months=i) for i in range(n_months)]
    trend = np.linspace(0.75, 1.4, n_months)
    seasonality = 1 + 0.2 * np.sin(np.arange(n_months) / 12 * 2 * np.pi)
    weights = trend * seasonality
    weights /= weights.sum()

    m_idx = rng.choice(n_months, size=n, p=weights)
    starts = np.array([m.date().toordinal() for m in months])
    lengths = np.array([m.days_in_month for m in months])
    ordinals = np.clip(starts[m_idx] + (rng.random(n) * lengths[m_idx]).astype(int),
                       start.toordinal(), end.toordinal())
    dates = pd.to_datetime([date.fromordinal(int(o)) for o in ordinals])
    seconds = rng.integers(0, 86400, n)
    timestamps = dates + pd.to_timedelta(seconds, unit="s")

    acct_idx = rng.choice(len(accounts), size=n, p=_account_weights(rng, len(accounts)))
    account_id = accounts["account_id"].to_numpy()[acct_idx]
    acct_numbers = accounts["account_number"].to_numpy()[acct_idx]
    bank_codes = accounts["bank_code"].to_numpy()[acct_idx]

    kind = rng.choice(9, size=n, p=[0.14, 0.20, 0.16, 0.09, 0.10, 0.08, 0.07, 0.06, 0.10])
    merchant_idx = rng.choice(len(MERCHANTS), size=n, p=_zipf(rng, len(MERCHANTS)))
    person_idx = rng.integers(0, len(PEOPLE), n)
    description = _narrations(rng, n, merchant_idx, person_idx, kind, bank_codes, acct_numbers)

    txn_type = np.where(rng.random(n) < 0.34, "credit", "debit")
    txn_type[kind == 8] = "debit"  # charges are always outflows

    scale = 1 + merchant_idx / len(MERCHANTS)
    amount = np.round(np.exp(rng.normal(9.6, 1.25, n)) * scale, 2)
    amount[txn_type == "credit"] = np.round(amount[txn_type == "credit"] * 2.4, 2)
    amount[kind == 8] = np.round(rng.uniform(11.8, 590, int((kind == 8).sum())), 2)

    # reference / UTR presence drives the derived reconciliation status
    recent = (end.toordinal() - ordinals) <= 45
    p_missing_ref = np.where(recent, 0.55, 0.18)
    has_ref = rng.random(n) > p_missing_ref
    has_utr = (rng.random(n) < 0.55) & (kind != 8)

    reference = np.where(
        has_ref,
        np.array([f"{c}H{v:011d}" if k in (0, 2, 7) else f"S{v}" for c, v, k in
                  zip(bank_codes, rng.integers(10**7, 10**8, n), kind)]),
        None,
    )
    utr = np.where(
        has_utr,
        np.array([f"jhI5nAdyb1qOEjmcB3Jv{a:08x}{b:08x}" for a, b in
                  zip(rng.integers(0, 2**31, n), rng.integers(0, 2**31, n))]),
        None,
    )

    df = pd.DataFrame(
        {
            "transaction_id": [f"{i:08x}-0000-4000-9000-{i:012x}" for i in range(1, n + 1)],
            "account_id": account_id,
            "transaction_date": timestamps,
            "transaction_type": txn_type,
            "description": description,
            "transaction_amount": amount,
            "transaction_reference_id": reference,
            "utr_number": utr,
        }
    )

    # a few genuine outliers so the anomaly call-out has something real to find
    if n > 500:
        picks = rng.choice(n, size=max(4, n // 40000), replace=False)
        df.loc[picks, "transaction_amount"] = (df.loc[picks, "transaction_amount"] * rng.uniform(25, 60, len(picks))).round(2)
    return df


def _account_weights(rng, k: int) -> np.ndarray:
    w = rng.gamma(2.0, 1.0, k)
    return w / w.sum()


def _zipf(rng, k: int) -> np.ndarray:
    w = 1 / (np.arange(1, k + 1) ** 0.7)
    rng.shuffle(w)
    return w / w.sum()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transactions", type=int, default=250_000)
    ap.add_argument("--accounts", type=int, default=40)
    ap.add_argument("--entities", type=int, default=25)
    ap.add_argument("--months", type=int, default=30)
    ap.add_argument("--end", type=str, default=date.today().isoformat())
    ap.add_argument("--db", type=str, default=str(ROOT / "data" / "finance.duckdb"))
    ap.add_argument("--csv", action="store_true")
    args = ap.parse_args()

    end = date.fromisoformat(args.end)
    first = pd.Timestamp(date(end.year, end.month, 1)) - pd.DateOffset(months=args.months - 1)
    start = first.date()
    rng = np.random.default_rng(SEED)

    print(f"Generating {args.transactions:,} transactions from {start} to {end} ...")
    banks = build_banks()
    accounts = build_accounts(rng, args.accounts, args.entities)
    txns = build_transactions(rng, accounts, args.transactions, start, end)

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    con = duckdb.connect(str(db_path))
    for name, df in [("bank", banks), ("account", accounts), ("transaction", txns)]:
        con.register("tmp_df", df)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM tmp_df")
        con.unregister("tmp_df")
        print(f"  {name:<14} {len(df):>12,} rows")

    print("Deriving counterparty / channel / reconciliation and building views ...")
    views.build(con)
    cp = con.execute("SELECT count(*) FROM counterparties").fetchone()[0]
    unknown = con.execute(
        "SELECT round(100.0 * sum(CASE WHEN counterparty = 'UNIDENTIFIED' THEN 1 ELSE 0 END) / count(*), 1) "
        "FROM txn_enriched"
    ).fetchone()[0]
    print(f"  counterparties {cp:>12,} distinct   ({unknown}% of rows unidentified)")

    if args.csv:
        out = db_path.parent / "csv"
        out.mkdir(exist_ok=True)
        banks.to_csv(out / "bank.csv", index=False)
        accounts.to_csv(out / "account.csv", index=False)
        txns.to_csv(out / "transaction.csv", index=False)
        print(f"CSV extracts written to {out}")

    con.close()
    print(f"\nDone -> {db_path}")


if __name__ == "__main__":
    main()
