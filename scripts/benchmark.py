"""Measure query latency at scale. Point it at any database file.

    python scripts/benchmark.py --db data/scale20m.duckdb
"""
from __future__ import annotations

import argparse
import os
import time

import duckdb

QUERIES = {
    "total spend, one month": """
        SELECT sum(amount), count(*) FROM v_transactions
        WHERE transaction_type = 'debit'
          AND transaction_date BETWEEN DATE '2026-08-01' AND DATE '2026-08-31'""",
    "top counterparties, YTD": """
        SELECT counterparty, sum(amount) t FROM v_transactions
        WHERE transaction_type = 'debit' AND transaction_date >= DATE '2026-01-01'
        GROUP BY 1 ORDER BY t DESC LIMIT 5""",
    "unreconciled, all time": """
        SELECT count(*), sum(amount) FROM v_transactions
        WHERE reconciliation_status = 'unreconciled'""",
    "monthly trend, full history": """
        SELECT strftime(transaction_date, '%Y-%m') m, sum(amount) FROM v_transactions
        WHERE transaction_type = 'debit' GROUP BY 1 ORDER BY 1""",
    "one counterparty, one month": """
        SELECT sum(amount) FROM v_transactions
        WHERE counterparty = 'TATA CAPITAL LIMITED'
          AND transaction_date BETWEEN DATE '2026-08-01' AND DATE '2026-08-31'""",
    "bank x channel, full history": """
        SELECT bank_name, channel, sum(amount) FROM v_transactions
        WHERE transaction_type = 'debit' GROUP BY 1, 2""",
    "list 25 largest unreconciled": """
        SELECT transaction_id, transaction_date, counterparty, amount FROM v_transactions
        WHERE reconciliation_status = 'unreconciled' ORDER BY amount DESC LIMIT 25""",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/finance.duckdb")
    ap.add_argument("--repeat", type=int, default=3)
    args = ap.parse_args()

    print(f"{args.db}  ({os.path.getsize(args.db) / 1e9:.2f} GB on disk)")
    con = duckdb.connect(args.db, read_only=True)
    rows = con.execute("SELECT count(*) FROM v_transactions").fetchone()[0]
    print(f"{rows:,} transactions\n")

    for name, sql in QUERIES.items():
        con.execute(sql).fetchall()  # warm the cache
        times = []
        for _ in range(args.repeat):
            t = time.perf_counter()
            con.execute(sql).fetchall()
            times.append((time.perf_counter() - t) * 1000)
        print(f"  {name:<30} {min(times):7.0f} ms  (best of {args.repeat})")
    con.close()


if __name__ == "__main__":
    main()
