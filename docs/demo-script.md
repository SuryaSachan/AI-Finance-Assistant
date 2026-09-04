# Demo script & deck outline

## Deck outline (8 slides)

| # | Slide | Point to land |
| --- | --- | --- |
| 1 | **The problem** | Finance ops answers the same lookup questions on repeat. Dashboards need you to know the report's vocabulary before you can ask a question. |
| 2 | **Why this is not a normal chatbot problem** | A wrong number here is a liability, not a bug. It corrupts reconciliation, audits and trust. So "mostly right" is a failing grade. |
| 3 | **Our thesis** | *The model reads and writes English. SQL does the arithmetic. A verifier checks every digit.* Ask the model to do only what models are good at. |
| 4 | **Architecture** | The flow diagram from `docs/architecture.md`. Emphasise: the model's only output is a 10-key JSON plan — there is no field in which it can write a number. |
| 5 | **Five guardrails** | Cannot express a number → cannot express a column → cannot express an entity → cannot compute → wording is number-verified. Each is independently sufficient. |
| 6 | **Model choice** | Qwen2.5-**3B** against a 20 B cap, and a 0-parameter rule tier that already scores 20/20. We got the accuracy from architecture, not from scale. Tokens/latency shown live on every answer. |
| 7 | **Live demo** | The five moments below. |
| 8 | **Impact & what's next** | Seconds instead of a ticket to finance ops; every answer is audit-traceable. Next: write-back-free approvals workflow, scheduled digests, more datasets behind the same plan schema. |

---

## Live demo — five moments, ~4 minutes

Start on a clean session with the sidebar visible (record count, coverage, model, mode).

### 1. The headline question (30 s)

> **How much did we spend on vendor payouts last month?**

Point at: the answer, the period badge, the source-record count, the token/latency badge.

Then open **"How I got this answer"** and scroll: assumptions applied, the plan JSON the model produced, the SQL that was built in code, guardrail status, and a sample of the real records.

> "The model produced the JSON on the left. It did not produce the number. The number came from that SQL."

### 2. The follow-up (30 s)

> **How does that compare to the month before?**

No vendor repeated, no period repeated. Show the two-row comparison table and the delta.

### 3. The operational question (30 s)

> **Which transactions are still unreconciled?**

Show the record list, then hit **Download Excel** — the finance user leaves with the working file, not a screenshot.

### 4. The refusals — the most important 60 seconds

> **How much did we spend with Globex Corporation last month?**

> "There is no vendor by that name, so there is no figure. Here are the closest real names."

> **What will our spend be next quarter?**

> "That is not in the data. I am not going to estimate it."

> "Most demos avoid these questions. This is the one we most want you to ask."

### 5. The guardrail, proven (60 s)

Drop to a terminal:

```powershell
.\.venv\Scripts\python.exe scripts\selftest.py
```

Walk the output. Check #2 stubs a model that says *"we spent exactly $42,000,000.00"* — a figure that is nowhere in the result set. The verifier catches it, the sentence is discarded, the computed answer ships instead, and confidence drops to medium.

Then:

```powershell
.\.venv\Scripts\python.exe evals\run_eval.py
```

20 natural-language questions, each compared against ground-truth SQL run directly on DuckDB, with two adversarial questions that must be refused.

---

## Backup plan

If the LLM host is unavailable mid-demo, nothing breaks: the sidebar flips to *"rule parser (no LLM)"* and every demo question above still answers correctly. Say so out loud — it is the strongest possible statement about where the accuracy actually lives.

## Questions judges will ask

**"What if the model picks the wrong filter?"** It is visible in the explain panel, and structural correctness (dataset, intent, grouping, filters) is asserted in the benchmark, not just the final number.

**"Does it scale to 20 M rows?"** DuckDB, columnar, date- and vendor-indexed; regenerate with `--transactions 20000000`. Queries are scans with a date predicate.

**"Why not just text-to-SQL?"** Free-form SQL from a small model is unvalidatable — you cannot prove the query means what the user asked. A fixed plan schema is checkable field by field, and it is what makes a 3 B model sufficient.

**"How would you handle a question you don't support?"** It refuses and states what it can answer. Broadening coverage means adding fields to `schema_catalog.py` — the prompt, the validator and the SQL builder all update from that one file.
