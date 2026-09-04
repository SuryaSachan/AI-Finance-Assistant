"""Self-test for the anti-hallucination machinery.

Runs without a live LLM by stubbing the model client, so it can be executed
anywhere:

    python scripts/selftest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import answer as answer_mod  # noqa: E402
from app import engine, llm as llm_mod, planner  # noqa: E402
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
    '{"intent":"aggregate","dataset":"vendor_payouts","metrics":[{"agg":"sum","field":"amount"}],'
    '"group_by":[],"filters":[],"period":{"kind":"last_month"},"compare_to_previous":false,"limit":20}'
)


def main() -> int:
    # 1. Honest narration passes the guardrail.
    engine.sessions.reset("t1")
    install(StubLLM(PLAN, "Last month vendor payouts came to the amount shown in the breakdown."))
    r = engine.ask("How much did we spend on vendor payouts last month?", "t1")
    check("valid plan from model is executed", r["explain"]["plan_source"].startswith("llm"), r["explain"]["plan_source"])
    check("clean narration is kept", r["answer_source"] == "llm", r["answer"])

    # 2. A fabricated figure is caught and the computed answer is substituted.
    engine.sessions.reset("t2")
    install(StubLLM(PLAN, "We spent exactly $42,000,000.00 on vendor payouts last month."))
    r = engine.ask("How much did we spend on vendor payouts last month?", "t2")
    g = r["explain"]["guardrail"]
    check("hallucinated number is rejected", g["triggered"] and r["answer_source"] == "deterministic", str(g["rejected_numbers"]))
    check("confidence is downgraded after a rejection", r["confidence"]["level"] != "high", r["confidence"]["level"])

    # 3. Malformed model output falls back to the rule parser rather than failing.
    engine.sessions.reset("t3")
    install(StubLLM("I think you want the payouts, boss.", "..."))
    r = engine.ask("How much did we spend on vendor payouts last month?", "t3")
    check("unparseable model output falls back to rules", r["explain"]["plan_source"] == "rules", r["explain"]["plan_source"])

    # 4. A model that invents a column cannot reach the database.
    engine.sessions.reset("t4")
    bad = PLAN.replace('"filters":[]', '"filters":[{"field":"secret_margin","op":"eq","value":9}]')
    install(StubLLM(bad, "..."))
    r = engine.ask("How much did we spend on vendor payouts last month?", "t4")
    check("unknown column is stripped, not queried", "secret_margin" not in (r["explain"]["sql"] or ""), r["explain"]["sql"])

    # 5. Unknown vendor => explicit refusal, no number.
    engine.sessions.reset("t5")
    install(type("Off", (), {"health": lambda *a, **k: False, "model": "off"})())
    r = engine.ask("How much did we spend with Globex Corporation last month?", "t5")
    check("unknown vendor refuses instead of guessing", r["status"] == "no_data" and "$" not in r["answer"], r["answer"])

    # 6. Number verification unit checks.
    allowed = {1000.0, 25.5}
    check("verifier accepts grounded numbers", not answer_mod.verify_numbers("Total was $1,000 across 25.5 units", allowed))
    check("verifier flags invented numbers", bool(answer_mod.verify_numbers("Total was $1,700", allowed)))

    width = max(len(n) for _, n, _ in results)
    for status, name, detail in results:
        print(f"{status}  {name.ljust(width)}  {detail[:90]}")
    failed = sum(1 for s, _, _ in results if s == FAIL)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
