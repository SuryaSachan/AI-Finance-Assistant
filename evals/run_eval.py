"""Accuracy benchmark.

Runs every question in questions.yaml through the full assistant and compares
the number it reports against ground-truth SQL executed directly on DuckDB.

    python evals/run_eval.py                  # use whatever LLM_PROVIDER is configured
    python evals/run_eval.py --no-llm         # deterministic rule-parser baseline
    python evals/run_eval.py --write-samples  # also refresh docs/sample-questions.md
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TOLERANCE = 0.005  # 0.5%


def placeholders() -> dict:
    from app import db

    anchor = db.anchor_date()
    lm_end = date(anchor.year, anchor.month, 1) - pd.Timedelta(days=1).to_pytimedelta()
    lm_start = date(lm_end.year, lm_end.month, 1)
    pm_end = lm_start - pd.Timedelta(days=1).to_pytimedelta()
    pm_start = date(pm_end.year, pm_end.month, 1)
    return {
        "anchor": anchor.isoformat(),
        "lm_start": lm_start.isoformat(),
        "lm_end": lm_end.isoformat(),
        "pm_start": pm_start.isoformat(),
        "pm_end": pm_end.isoformat(),
        "ytd_start": date(anchor.year, 1, 1).isoformat(),
        "year": anchor.year,
    }


def truth(sql: str, ph: dict) -> float | None:
    from app import db

    df = db.query(sql.format(**ph))
    v = df.iloc[0, 0]
    return None if pd.isna(v) else float(v)


def reported(case: dict, resp: dict) -> float | None:
    check = case.get("check", "value")
    if check == "count":
        return float(resp["explain"]["matching_records"])
    if check == "comparison_previous":
        c = resp.get("comparison")
        return None if not c else float(c["previous_value"])
    totals = resp.get("totals") or {}
    for key in totals:
        if key.startswith(("sum_", "avg_", "min_", "max_")):
            return None if totals[key] is None else float(totals[key])
    return float(resp["explain"]["matching_records"])


def close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a == b
    return abs(a - b) <= max(0.01, abs(b) * TOLERANCE)


def structural(case: dict, resp: dict) -> list[str]:
    problems = []
    plan = (resp.get("explain") or {}).get("plan") or {}
    if "dataset" in case and plan.get("dataset") != case["dataset"]:
        problems.append(f"dataset={plan.get('dataset')} expected {case['dataset']}")
    if "intent" in case and plan.get("intent") != case["intent"]:
        problems.append(f"intent={plan.get('intent')} expected {case['intent']}")
    if "group_by" in case and plan.get("group_by") != case["group_by"]:
        problems.append(f"group_by={plan.get('group_by')} expected {case['group_by']}")
    for want in case.get("must_filter", []):
        fieldname, value = want.split("=", 1)
        got = [f for f in plan.get("filters", []) if f.get("field") == fieldname and str(f.get("value")) == value]
        if not got:
            problems.append(f"missing filter {want}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--write-samples", action="store_true")
    ap.add_argument("--file", default=str(ROOT / "evals" / "questions.yaml"))
    args = ap.parse_args()

    if args.no_llm:
        os.environ["LLM_PROVIDER"] = "none"

    from app import config, db  # noqa: F401
    from app.engine import ask
    from app.llm import llm

    cases = yaml.safe_load(Path(args.file).read_text(encoding="utf-8"))
    ph = placeholders()
    sessions: dict[str, str] = {}

    rows = []
    passed = 0
    for case in cases:
        sess_key = case.get("session")
        session_id = sessions.get(sess_key) if sess_key else None
        resp = ask(case["question"], session_id)
        if sess_key:
            sessions[sess_key] = resp["session_id"]

        notes: list[str] = []
        if case.get("expect_refusal"):
            ok = resp["status"] in ("no_data", "unsupported", "clarify")
            if not ok:
                notes.append(f"answered instead of refusing (status={resp['status']})")
            expected = got = None
        else:
            expected = truth(case["expect_sql"], ph)
            got = reported(case, resp)
            notes = structural(case, resp)
            ok = close(got, expected) and not notes
            if not close(got, expected):
                notes.insert(0, f"value {got} != truth {expected}")

        passed += ok
        rows.append(
            {
                "id": case["id"],
                "question": case["question"],
                "pass": "PASS" if ok else "FAIL",
                "expected": expected,
                "reported": got,
                "confidence": resp["confidence"]["level"],
                "plan_source": (resp.get("explain") or {}).get("plan_source"),
                "tokens": (resp.get("usage") or {}).get("total_tokens", 0),
                "ms": (resp.get("usage") or {}).get("total_ms", 0),
                "notes": "; ".join(notes),
                "answer": resp["answer"],
            }
        )

    df = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 46)
    print(df[["id", "question", "pass", "expected", "reported", "confidence", "plan_source", "tokens", "ms"]].to_string(index=False))
    print()
    for r in rows:
        if r["pass"] == "FAIL":
            print(f"  FAIL {r['id']}: {r['notes']}")
    accuracy = passed / len(rows) * 100
    print(
        f"\nAccuracy: {passed}/{len(rows)} = {accuracy:.1f}%   "
        f"model={config.LLM_MODEL if llm.health() else 'none (rule parser)'}   "
        f"avg tokens/question={df['tokens'].mean():.0f}   avg latency={df['ms'].mean():.0f} ms"
    )

    out = ROOT / "evals" / "results.csv"
    df.to_csv(out, index=False)
    print(f"Detailed results -> {out}")

    if args.write_samples:
        write_samples(rows, accuracy)
    return 0 if passed == len(rows) else 1


def write_samples(rows: list[dict], accuracy: float) -> None:
    from app import config, db
    from app.llm import llm

    lines = [
        "# Sample questions and answers",
        "",
        f"Generated by `python evals/run_eval.py --write-samples` on the seeded dataset "
        f"(anchor date **{db.anchor_date()}**, {db.stats()['transactions']:,} transactions).",
        "",
        f"Mode: **{config.LLM_MODEL if llm.health() else 'rule parser (no LLM)'}** · "
        f"Accuracy on this set: **{accuracy:.1f}%**",
        "",
    ]
    for r in rows:
        lines += [
            f"### {r['id']}. {r['question']}",
            "",
            f"> {r['answer']}",
            "",
            f"- Result: **{r['pass']}** · confidence `{r['confidence']}` · plan source `{r['plan_source']}`"
            + (f" · ground truth `{r['expected']:,.2f}`" if isinstance(r["expected"], float) else ""),
            "",
        ]
    path = ROOT / "docs" / "sample-questions.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Samples -> {path}")


if __name__ == "__main__":
    raise SystemExit(main())
