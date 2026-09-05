"""Self-test for the anti-hallucination machinery and the derived columns.

Runs without a live LLM by stubbing the model client, so it can be executed
anywhere:

    python scripts/selftest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import duckdb  # noqa: E402

from app import answer as answer_mod  # noqa: E402
from app import engine, llm as llm_mod, planner, views  # noqa: E402
from app.llm import LLMResult  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((PASS if ok else FAIL, name, detail))


class StubLLM:
    """Pretends to be a model. `plan_json` drives the planner, `narration` the writer."""

    def __init__(self, plan_json: str, narration: str):
        self.plan_json = plan_json
        self.narration = narration
        self.model = "stub-model"
        self.fallback_model = None

    def health(self, refresh: bool = False) -> bool:
        return True

    def chat(self, system, user, *, json_mode=False, model=None, max_tokens=512):
        text = self.plan_json if json_mode else self.narration
        return LLMResult(text=text, model=self.model, latency_ms=5, prompt_tokens=300, completion_tokens=60)

    def chat_json(self, system, user, *, model=None, max_tokens=512):
        res = self.chat(system, user, json_mode=True, model=model)
        return llm_mod.extract_json(res.text), res


def install(stub) -> None:
    for module in (llm_mod, planner, answer_mod, engine):
        module.llm = stub


PLAN = (
    '{"intent":"aggregate","dataset":"transactions","metrics":[{"agg":"sum","field":"amount"}],'
    '"group_by":[],"filters":[{"field":"transaction_type","op":"eq","value":"debit"}],'
    '"period":{"kind":"last_month"},"compare_to_previous":false,"limit":20}'
)
QUESTION = "How much did we pay out last month?"


def main() -> int:
    # 1. Honest narration passes the guardrail.
    engine.sessions.reset("t1")
    install(StubLLM(PLAN, "Last month's outgoing payments came to the amount shown in the breakdown."))
    r = engine.ask(QUESTION, "t1")
    check("valid plan from model is executed", r["explain"]["plan_source"].startswith("llm"), r["explain"]["plan_source"])
    check("clean narration is kept", r["answer_source"] == "llm", r["answer"])

    # 2. A fabricated figure is caught and the computed answer is substituted.
    engine.sessions.reset("t2")
    install(StubLLM(PLAN, "We paid out exactly Rs 42,000,000.00 last month."))
    r = engine.ask(QUESTION, "t2")
    g = r["explain"]["guardrail"]
    check("hallucinated number is rejected", g["triggered"] and r["answer_source"] == "deterministic", str(g["rejected_numbers"]))
    check("confidence is downgraded after a rejection", r["confidence"]["level"] != "high", r["confidence"]["level"])

    # 3. Malformed model output falls back to the rule parser rather than failing.
    engine.sessions.reset("t3")
    install(StubLLM("I think you want the payouts, boss.", "..."))
    r = engine.ask(QUESTION, "t3")
    check("unparseable model output falls back to rules", r["explain"]["plan_source"] == "rules", r["explain"]["plan_source"])

    # 4. A model that invents a column cannot reach the database.
    engine.sessions.reset("t4")
    bad = PLAN.replace('"group_by":[]', '"group_by":["secret_margin"]')
    install(StubLLM(bad, "..."))
    r = engine.ask(QUESTION, "t4")
    check("unknown column is stripped, not queried", "secret_margin" not in (r["explain"]["sql"] or ""), r["explain"]["sql"])

    # 5. Sensitive columns are unreachable even if the model asks for them.
    engine.sessions.reset("t4b")
    leak = PLAN.replace('"group_by":[]', '"group_by":["utr_number"]')
    install(StubLLM(leak, "..."))
    r = engine.ask(QUESTION, "t4b")
    check("utr_number cannot be selected", "utr" not in (r["explain"]["sql"] or "").lower(), r["explain"]["sql"])

    # 6. Unknown counterparty => explicit refusal, no number.
    engine.sessions.reset("t5")
    install(type("Off", (), {"health": lambda *a, **k: False, "model": "off"})())
    r = engine.ask("How much did we spend with Globex Corporation last month?", "t5")
    check("unknown counterparty refuses instead of guessing", r["status"] == "no_data", r["answer"])

    # 7. Number verification unit checks.
    allowed = {1000.0, 25.5}
    check("verifier accepts grounded numbers", not answer_mod.verify_numbers("Total was 1,000 across 25.5 units", allowed))
    check("verifier flags invented numbers", bool(answer_mod.verify_numbers("Total was 1,700", allowed)))

    # 8. Derived columns, against the real sample rows in the schema document.
    check_derivations()

    width = max(len(n) for _, n, _ in results)
    for status, name, detail in results:
        print(f"{status}  {name.ljust(width)}  {detail[:90]}")
    failed = sum(1 for s, _, _ in results if s == FAIL)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


def check_derivations() -> None:
    """Parse the sample INSERTs out of the schema doc and verify what we derive."""
    import load_dataset

    doc = ROOT / "TBX - Database Schema.md"
    if not doc.exists():
        check("schema doc sample rows load", False, f"{doc.name} not found")
        return

    con = duckdb.connect(":memory:")
    load_dataset.import_file(con, doc)
    views.build(con)
    rows = con.execute(
        "SELECT description, counterparty, channel, reconciliation_status FROM v_transactions"
    ).fetchall()

    check("schema doc sample rows load", len(rows) == 10, f"{len(rows)} rows")
    check(
        "every sample narration yields a counterparty",
        all(r[1] and r[1] != "UNIDENTIFIED" for r in rows),
        ", ".join(sorted({r[1] for r in rows}))[:90],
    )

    by_fragment = {r[0][:24]: r for r in rows}
    expected = {
        "FT -  95842568 -  5020": ("SELECTION ELECTRONICS", "FT"),
        "UPI-NAVYUG SELECTION-XX": ("NAVYUG SELECTION", "UPI"),
        "NEFT/000483399203/ICIC/": ("PARESH VIKRANT GHASE", "NEFT"),
        "IMPS OW/507614422198/Ga": ("GAUTAM SINGH", "IMPS"),
    }
    wrong = []
    for fragment, (name, channel) in expected.items():
        row = next((r for k, r in by_fragment.items() if k.startswith(fragment[:20])), None)
        if not row or row[1] != name or row[2] != channel:
            wrong.append(f"{fragment[:16]}->{row[1] if row else 'missing'}/{row[2] if row else '-'}")
    check("counterparty and channel parsed from real narrations", not wrong, "; ".join(wrong))

    no_ref = [r for r in rows if "IMPS OW/507614422198" in r[0]]
    check(
        "row with no reference and no UTR is unreconciled",
        bool(no_ref) and no_ref[0][3] == "unreconciled",
        no_ref[0][3] if no_ref else "row missing",
    )
    con.close()


if __name__ == "__main__":
    raise SystemExit(main())
