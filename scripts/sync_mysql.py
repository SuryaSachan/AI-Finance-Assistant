"""Sync data from the live external MySQL database to local DuckDB.

This script fetches data, securely decrypts specified columns using the 
configured MYSQL_AES_KEY and MYSQL_AES_MODE, and saves it into the target DuckDB.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import pandas as pd
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config
from app import views
from app.mysql_plugin import decrypt_series

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=str, default=str(ROOT / "data" / "finance.duckdb"))
    args = ap.parse_args()

    if not config.MYSQL_URI:
        print("Please configure MYSQL_URI in .env (e.g. mysql+pymysql://user:pass@localhost:3306/db)")
        return

    print(f"Connecting to MySQL: {config.MYSQL_URI}")
    engine = create_engine(config.MYSQL_URI)
    
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    
    tables_to_sync = ["bank", "account", "transaction"]
    
    for table_name in tables_to_sync:
        print(f"Syncing table: {table_name}...")
        try:
            df = pd.read_sql(f"SELECT * FROM {table_name}", engine)
            
            if table_name == "account" and "account_number" in df.columns:
                print("  -> Decrypting heavily secured account_number column")
                df["account_number"] = decrypt_series(df["account_number"])
                
            if table_name == "transaction" and "utr_number" in df.columns:
                print("  -> Decrypting utr_number column")
                df["utr_number"] = decrypt_series(df["utr_number"])
                
            con.register("tmp_df", df)
            con.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM tmp_df")
            con.unregister("tmp_df")
            print(f"  Saved {len(df)} rows for {table_name} to DuckDB")
        except Exception as e:
            print(f"Failed to sync {table_name}: {e}")
            
    print("Deriving counterparties / channels and building analytics views...")
    views.build(con)
    
    con.close()
    print(f"Sync complete. Target: {db_path}")

if __name__ == "__main__":
    main()
