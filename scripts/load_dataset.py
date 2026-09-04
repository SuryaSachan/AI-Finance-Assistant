"""Load the organisers' dataset into DuckDB and map it onto the assistant's views.

    # 1. see what you were given
    python scripts/load_dataset.py --inspect --input path/to/dataset

    # 2. edit config/dataset_mapping.yml to match those column names

    # 3. import + build views + validate
    python scripts/load_dataset.py --input path/to/dataset

Accepts .csv, .tsv, .parquet, .xlsx and .json files, plus an existing .duckdb
file. Raw files are imported as `raw_<filename>` tables; the mapping turns them
into `v_transactions`, `v_vendor_payouts`, `v_bank_lines` and `vendors`, which
is the only contract the application depends on.
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

from app.schema_catalog import DATASETS  # noqa: E402

READERS = {
    ".csv": "read_csv_auto('{p}', sample_size=-1, ignore_errors=false)",
    ".tsv": "read_csv_auto('{p}', delim='\\t', sample_size=-1)",
    ".txt": "read_csv_auto('{p}', sample_size=-1)",
    ".parquet": "read_parquet('{p}')",
    ".json": "read_json_auto('{p}')",
    ".ndjson": "read_json_auto('{p}')",
}


def table_name(path: Path) -> str:
    stem = re.sub(r"[^0-9a-zA-Z_]+", "_", path.stem).strip("_").lower()
    return f"raw_{stem}"


def import_files(con: duckdb.DuckDBPyConnection, folder: Path) -> list[str]:
    imported: list[str] = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        name = table_name(path)
        posix = path.as_posix().replace("'", "''")
        if suffix in READERS:
            con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM {READERS[suffix].format(p=posix)}")
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
            continue
        else:
            continue
        imported.append(name)
    return imported


def describe(con: duckdb.DuckDBPyConnection, tables: list[str]) -> None:
    for t in tables:
        cols = con.execute(f"DESCRIBE {t}").fetchall()
        rows = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"\n{t}  ({rows:,} rows)")
        for name, dtype, *_ in cols:
            print(f"    {name:<32} {dtype}")


def build_views(con: duckdb.DuckDBPyConnection, mapping: dict) -> list[str]:
    warnings: list[str] = []
    for view, spec in mapping.items():
        fields = spec.get("fields") or {}
        select = ", ".join(
            f'{expr if expr else "NULL"} AS "{name}"' for name, expr in fields.items()
        )
        sql = f"CREATE OR REPLACE VIEW {view} AS SELECT {select} FROM {spec['from']}"
        try:
            con.execute(sql)
            print(f"  built {view}")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{view}: {exc}")
            print(f"  FAILED {view}: {str(exc).splitlines()[0]}")
    return warnings


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
        span = con.execute(
            f'SELECT min("{ds.date_field}"), max("{ds.date_field}") FROM {ds.view}'
        ).fetchone()
        print(f"\n{ds.view}: {rows:,} rows, {ds.date_field} {span[0]} .. {span[1]}")
        if rows == 0:
            problems.append(f"{ds.view} is empty")

        for f in ds.fields:
            if f.kind != "enum" or f.name not in present:
                continue
            actual = [
                r[0] for r in con.execute(
                    f'SELECT DISTINCT "{f.name}" FROM {ds.view} WHERE "{f.name}" IS NOT NULL LIMIT 40'
                ).fetchall()
            ]
            unexpected = [v for v in actual if v not in f.values]
            print(f"    {f.name:<24} {sorted(actual)[:8]}")
            if unexpected:
                problems.append(
                    f"{ds.view}.{f.name} has values not in schema_catalog: {unexpected[:8]} "
                    f"-> either normalise them in the mapping or add them to schema_catalog.py"
                )

    try:
        vendors = con.execute("SELECT count(*) FROM vendors").fetchone()[0]
        print(f"\nvendors: {vendors:,} rows")
        if vendors == 0:
            problems.append("vendors is empty - entity resolution and refusals need it")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"vendors table/view missing ({str(exc).splitlines()[0]})")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="folder of data files, or an existing .duckdb")
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
        if not source.is_dir():
            print(f"{source} is not a folder or .duckdb file")
            return 2
        con = duckdb.connect(str(db_path))
        print(f"Importing {source} -> {db_path}")
        tables = import_files(con, source)
        if not tables:
            print("No readable data files found (.csv/.tsv/.parquet/.json/.xlsx)")
            return 2
        print(f"Imported {len(tables)} table(s): {', '.join(tables)}")

    describe(con, tables)

    if args.inspect:
        print("\nInspect only. Now edit the mapping to match these columns:")
        print(f"  {args.mapping}")
        con.close()
        return 0

    mapping = yaml.safe_load(Path(args.mapping).read_text(encoding="utf-8"))
    print("\nBuilding views:")
    build_views(con, mapping)

    print("\nValidating against schema_catalog:")
    problems = validate(con)
    con.close()

    if problems:
        print("\nISSUES TO FIX:")
        for p in problems:
            print(f"  - {p}")
        print("\nFix the mapping expressions (or schema_catalog.py enums) and re-run.")
        return 1

    print("\nDataset is ready. Next:")
    print("  python evals/run_eval.py --no-llm     # re-point questions.yaml at the real figures first")
    print("  python -m uvicorn app.main:app --reload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
