"""Load the provided dataset into DuckDB and build the assistant's views.

    # 1. see what you were given
    python scripts/load_dataset.py --inspect --input path/to/dataset

    # 2. if table/column names differ, adjust config/dataset_mapping.yml

    # 3. import, derive, build views, validate
    python scripts/load_dataset.py --input path/to/dataset

Accepts .csv, .tsv, .parquet, .json, .xlsx, a .sql dump of INSERT statements,
or an existing .duckdb file. Files are imported under their own name, so a file
called `transaction.csv` becomes the `transaction` table.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import duckdb
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import views  # noqa: E402
from app.derivations import RECONCILIATION_DEFINITION  # noqa: E402
from app.schema_catalog import DATASETS  # noqa: E402
from app.encryption import encrypt, enabled as enc_enabled  # noqa: E402

READERS = {
    ".csv": "read_csv_auto('{p}', sample_size=-1)",
    ".tsv": "read_csv_auto('{p}', delim='\\t', sample_size=-1)",
    ".txt": "read_csv_auto('{p}', sample_size=-1)",
    ".parquet": "read_parquet('{p}')",
    ".json": "read_json_auto('{p}')",
    ".ndjson": "read_json_auto('{p}')",
}


def table_name(path: Path) -> str:
    return re.sub(r"[^0-9a-zA-Z_]+", "_", path.stem).strip("_").lower()


def run_sql_script(con: duckdb.DuckDBPyConnection, script: str, label: str) -> None:
    """Execute a DDL/INSERT dump, stripping MySQL-only syntax DuckDB rejects."""
    script = re.sub(r"ENGINE=\w+[^;]*", "", script, flags=re.I)
    script = re.sub(r"\bENUM\s*\([^)]*\)", "VARCHAR", script, flags=re.I)
    script = re.sub(r"\bTIMESTAMP\(\d\)", "TIMESTAMP", script, flags=re.I)
    script = re.sub(r"\bAUTO_INCREMENT\b", "", script, flags=re.I)
    script = re.sub(r"DEFAULT CHARSET=\S+", "", script, flags=re.I)
    for statement in [s.strip() for s in script.split(";") if s.strip()]:
        try:
            con.execute(statement)
        except Exception as exc:  # noqa: BLE001
            print(f"    skipped statement in {label}: {str(exc).splitlines()[0]}")


def import_file(con: duckdb.DuckDBPyConnection, path: Path) -> list[str]:
    suffix = path.suffix.lower()
    name = table_name(path)
    posix = path.as_posix().replace("'", "''")
    imported: list[str] = []

    if suffix in READERS:
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM {READERS[suffix].format(p=posix)}")
        imported.append(name)
    elif suffix in (".xlsx", ".xls"):
        import pandas as pd

        sheets = pd.read_excel(path, sheet_name=None)
        for sheet, df in sheets.items():
            sheet_name = re.sub(r"[^0-9a-zA-Z_]+", "_", sheet).strip("_").lower()
            full = name if len(sheets) == 1 else f"{name}_{sheet_name}"
            con.register("tmp_df", df)
            con.execute(f"CREATE OR REPLACE TABLE {full} AS SELECT * FROM tmp_df")
            con.unregister("tmp_df")
            imported.append(full)
    elif suffix == ".sql":
        run_sql_script(con, path.read_text(encoding="utf-8", errors="replace"), path.name)
        imported.extend(r[0] for r in con.execute("SHOW TABLES").fetchall())
    elif suffix in (".md", ".markdown"):
        # the schema document carries the DDL and the sample INSERTs in ```sql fences
        text = path.read_text(encoding="utf-8", errors="replace")
        blocks = re.findall(r"```sql\s*\n(.*?)```", text, re.S | re.I)
        if not blocks:
            print(f"    no ```sql blocks found in {path.name}")
        for block in blocks:
            run_sql_script(con, block, path.name)
        imported.extend(r[0] for r in con.execute("SHOW TABLES").fetchall())
    return imported


def import_files(con: duckdb.DuckDBPyConnection, source: Path) -> list[str]:
    paths = [source] if source.is_file() else [p for p in sorted(source.rglob("*")) if p.is_file()]
    imported: list[str] = []
    for path in paths:
        imported.extend(import_file(con, path))
    return sorted(set(imported))


def describe(con: duckdb.DuckDBPyConnection, tables: list[str]) -> None:
    for t in tables:
        cols = con.execute(f"DESCRIBE {t}").fetchall()
        rows = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"\n{t}  ({rows:,} rows)")
        for name, dtype, *_ in cols:
            print(f"    {name:<32} {dtype}")


def validate(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Check the views satisfy everything schema_catalog promises the model."""
    problems: list[str] = []
    for ds in DATASETS.values():
        try:
            present = {r[0] for r in con.execute(f"DESCRIBE {ds.view}").fetchall()}
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{ds.view} does not exist ({str(exc).splitlines()[0]})")
            continue

        missing = [f.name for f in ds.fields if f.name not in present]
        if missing:
            problems.append(f"{ds.view} is missing fields: {', '.join(missing)}")

        rows = con.execute(f"SELECT count(*) FROM {ds.view}").fetchone()[0]
        if ds.date_field:
            span = con.execute(
                f'SELECT min("{ds.date_field}"), max("{ds.date_field}") FROM {ds.view}'
            ).fetchone()
            print(f"\n{ds.view}: {rows:,} rows, {ds.date_field} {span[0]} .. {span[1]}")
        else:
            print(f"\n{ds.view}: {rows:,} rows")
        if rows == 0:
            problems.append(f"{ds.view} is empty")

        for f in ds.fields:
            if f.kind != "enum" or f.name not in present:
                continue
            actual = [
                r[0] for r in con.execute(
                    f'SELECT DISTINCT "{f.name}" FROM {ds.view} WHERE "{f.name}" IS NOT NULL LIMIT 60'
                ).fetchall()
            ]
            unexpected = [v for v in actual if v not in f.values]
            print(f"    {f.name:<24} {sorted(actual)[:8]}")
            if unexpected:
                problems.append(
                    f"{ds.view}.{f.name} has values not in schema_catalog: {unexpected[:8]} "
                    f"-> normalise them in app/derivations.py or add them to app/schema_catalog.py"
                )

    cp = con.execute("SELECT count(*) FROM counterparties").fetchone()[0]
    unknown = con.execute(
        "SELECT round(100.0 * sum(CASE WHEN counterparty = 'UNIDENTIFIED' THEN 1 ELSE 0 END) / count(*), 1) "
        "FROM txn_enriched"
    ).fetchone()[0]
    print(f"\ncounterparties: {cp:,} distinct, {unknown}% of transactions unidentified")
    if cp == 0:
        problems.append("no counterparties were parsed out of the descriptions")
    if unknown is not None and unknown > 40:
        problems.append(
            f"{unknown}% of narrations produced no counterparty - the parsing rules in "
            f"app/derivations.py probably need a pattern for this export's format"
        )

    top = con.execute("SELECT counterparty, txn_count FROM counterparties LIMIT 8").fetchall()
    for name, n in top:
        print(f"    {name:<40} {n:>10,}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="data file, folder of data files, .sql/.md dump, or an existing .duckdb")
    ap.add_argument("--db", default=str(ROOT / "data" / "finance.duckdb"))
    ap.add_argument("--mapping", default=str(ROOT / "config" / "dataset_mapping.yml"))
    ap.add_argument("--inspect", action="store_true", help="import and print schemas, do not build views")
    args = ap.parse_args()

    source = Path(args.input)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if source.suffix == ".duckdb":
        print(f"Using existing database {source}")
        con = duckdb.connect(str(source))
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    else:
        if not source.exists():
            print(f"{source} does not exist")
            return 2
        con = duckdb.connect(str(db_path))
        print(f"Importing {source} -> {db_path}")
        tables = import_files(con, source)
        if not tables:
            print("No readable data found (.csv/.tsv/.parquet/.json/.xlsx/.sql/.md)")
            return 2
        print(f"Imported {len(tables)} table(s): {', '.join(tables)}")

    describe(con, tables)

    if args.inspect:
        print(f"\nInspect only. If these names differ from the schema doc, edit:\n  {args.mapping}")
        con.close()
        return 0

    overrides = yaml.safe_load(Path(args.mapping).read_text(encoding="utf-8")) or {}

    # ── Encrypt sensitive columns at rest ──────────────────────────
    if enc_enabled():
        import duckdb as _duckdb
        con.create_function("encrypt_field", encrypt, [_duckdb.typing.VARCHAR], _duckdb.typing.VARCHAR)
        for tbl, col in [("account", "account_number"), ("transaction", "utr_number")]:
            try:
                con.execute(f'UPDATE {tbl} SET {col} = encrypt_field(CAST({col} AS VARCHAR)) WHERE {col} IS NOT NULL')
                print(f"  Encrypted {tbl}.{col} (AES-256-SIV)")
            except Exception as exc:  # noqa: BLE001
                print(f"  Could not encrypt {tbl}.{col}: {str(exc).splitlines()[0]}")
    else:
        print("  Encryption disabled (no ENCRYPTION_KEY in .env)")

    print("\nDeriving counterparty / channel / reconciliation and building views ...")
    print(f"  reconciliation rule: {RECONCILIATION_DEFINITION}")
    try:
        views.build(con, overrides)
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAILED to build views: {str(exc).splitlines()[0]}")
        print(f"Check the table/column names in {args.mapping}")
        con.close()
        return 1

    print("\nValidating against schema_catalog:")
    problems = validate(con)
    con.close()

    if problems:
        print("\nISSUES TO FIX:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("\nDataset is ready. Next:")
    print("  python evals/run_eval.py --no-llm    # update questions.yaml for the real data first")
    print("  python -m uvicorn app.main:app --reload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
