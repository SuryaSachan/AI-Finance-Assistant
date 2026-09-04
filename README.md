# AI Finance Assistant

A conversational assistant that answers plain-language questions about finance data — spend, vendor payouts and reconciliation — **from the data, never from the model's imagination**.

The design rule is simple: *the language model reads and writes English; SQL does the arithmetic; a verifier checks every digit before it reaches the user.*

```
"How much did we spend on vendor payouts last month?"
  -> plan (3B model, JSON)  -> validate  -> SQL (built in Python)  -> DuckDB
  -> computed result -> narration -> number verification -> answer + breakdown + audit trail
```

---

## Quick start

```powershell
git clone <repo> && cd AI-Finance-Assistant

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 1. build the dataset (seeded, reproducible)
.\.venv\Scripts\python.exe scripts\generate_data.py

# 2. run
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Open <http://127.0.0.1:8000>.

macOS / Linux: replace `.\.venv\Scripts\python.exe` with `.venv/bin/python`.

### Optional: enable the small LLM

The assistant runs **without any model** (deterministic rule parser, 100 % on the benchmark). To turn on natural-language understanding for freer phrasing:

```powershell
ollama pull qwen2.5:3b-instruct
ollama serve
copy .env.example .env      # defaults already point at this model
```

Any OpenAI-compatible endpoint works too — set `LLM_PROVIDER=openai`, `LLM_BASE_URL`, `LLM_API_KEY`.

### Verify it

```powershell
.\.venv\Scripts\python.exe evals\run_eval.py          # 20-question accuracy benchmark vs ground-truth SQL
.\.venv\Scripts\python.exe scripts\selftest.py        # anti-hallucination checks (stubs the model)
```

---

## What it does

| Requirement | How it is met |
| --- | --- |
| **Natural-language queries** | Free-form chat. Intent, filters, grouping and date ranges are extracted into a validated query plan. |
| **Grounded retrieval** | Every answer comes from SQL over the provided dataset. The model sees the schema and the computed result — never raw freedom to state a figure. |
| **Accurate computation** | Filtering, grouping and aggregation happen in DuckDB. The model is handed a finished number to describe. |
| **Verifiable answers** | Every reply ships with the breakdown table, a sample of the underlying records, the query plan and the exact SQL that produced it. |
| **Hallucination guardrails** | Numeric verification of the model's wording; explicit refusal on unknown entities, unsupported questions and empty result sets. |
| **Lightweight model** | 3 B parameters by default (cap is 20 B). Token and latency cost shown on every answer. See [docs/model-choice.md](docs/model-choice.md). |
| **Multi-turn** | The previous plan is carried forward, so *"how does that compare to the month before?"* works with no repetition. |
| **Explainability** | "How I got this answer" expands to interpretation, assumptions applied, plan corrections, the plan JSON, the SQL, guardrail status and sample records. |
| **CSV / Excel export** *(good to have)* | Download the full, untruncated breakdown from any answer. |
| **Confidence signalling** *(bonus)* | high / medium / low with the specific reasons that moved it. |
| **Anomaly call-outs** *(bonus)* | A vendor whose period total is ≥2.5σ above its own 12-month baseline is flagged alongside the answer. |

---

## How hallucination is actually prevented

Five independent mechanisms, each of which alone would stop a fabricated figure:

1. **The model cannot express a number.** Its only output is a fixed-shape JSON plan — dataset, filters, grouping, period. There is no field in which a figure can be written.
2. **The model cannot express a column.** Fields are validated against `app/schema_catalog.py`; anything invented is stripped before SQL is built, and the correction is shown to the user.
3. **The model cannot express an entity.** Vendor and enum values are fuzzy-matched against the real vendor table. No match above threshold → the assistant says the entity does not exist and names the closest real ones.
4. **The model cannot compute.** Dates are resolved in Python; filtering and aggregation happen in DuckDB over a read-only connection.
5. **The model's wording is verified.** Every numeric token in the generated sentence — including `$`, `,`, `%`, `k`/`M` forms — is traced back to a value in the result set within 0.5 %. One unverifiable digit and the sentence is discarded in favour of the deterministic answer, the UI says so, and confidence drops.

Plus: **zero rows → an explicit "there is no figure to report"**, never an estimate.

`scripts/selftest.py` demonstrates each of these against a stubbed model that deliberately misbehaves.

---

## Sample questions

```
How much did we spend on vendor payouts last month?
Which transactions are still unreconciled?
How does that compare to the month before?          <- follow-up, no context repeated
Top 5 vendors by spend this year
What did we pay Acme Software last quarter?
Show marketing spend by month year to date
How many payouts are still pending?
How much did we spend with Globex Corporation?      <- refused: not a real vendor
What will our spend be next quarter?                <- refused: not answerable from data
```

Full run with the assistant's actual answers and the ground-truth figures: [docs/sample-questions.md](docs/sample-questions.md).

---

## The data

`scripts/generate_data.py` builds a seeded, reproducible dataset for one fictitious company in a single currency (USD):

| Table | Default rows | Contents |
| --- | --- | --- |
| `transactions` | 250,000 | ledger entries with vendor, category, department, account, direction, status, reconciliation status |
| `vendor_payouts` | ~2,500 | payment runs derived from spend, with pending/failed/on-hold states |
| `bank_lines` | ~61,500 | bank feed, matched and unmatched |
| `vendors` | 40 | vendor master with category, country, terms |
| `chart_of_accounts` | 14 | account codes and types |
| `data_dictionary` | 38 | field-level documentation, generated from the schema catalog |

Scale up to the 20 M-record test limit and export CSVs:

```powershell
.\.venv\Scripts\python.exe scripts\generate_data.py --transactions 20000000 --csv
```

To swap in the organisers' dataset, load it into DuckDB as the same three views (`v_transactions`, `v_vendor_payouts`, `v_bank_lines`) and adjust `app/schema_catalog.py` to match — nothing else changes.

### Loading the provided dataset

```powershell
# 1. import the files and print every table and column you were given
.\.venv\Scripts\python.exe scripts\load_dataset.py --inspect --input path\to\dataset

# 2. point config\dataset_mapping.yml at those real column names
#    (each entry is a SQL expression, so CAST / COALESCE / CASE are available
#     for type and vocabulary normalisation)

# 3. import, build the views, and validate them against the schema catalog
.\.venv\Scripts\python.exe scripts\load_dataset.py --input path\to\dataset
```

Accepts CSV, TSV, Parquet, JSON, Excel or an existing `.duckdb` file. Raw files land as `raw_<filename>` tables; the mapping projects them into the four objects the app depends on (`v_transactions`, `v_vendor_payouts`, `v_bank_lines`, `vendors`).

The validator reports missing fields, empty views, date coverage, and any enum value that is not declared in `app/schema_catalog.py` — so mismatched vocabulary (`OPEN` vs `unreconciled`) is caught before it reaches an answer rather than after. Then update the expected figures in `evals/questions.yaml` and re-run `evals\run_eval.py`.

---

## API

| Endpoint | Purpose |
| --- | --- |
| `POST /api/ask` | `{question, session_id?}` → answer, breakdown, confidence, explain payload, token usage |
| `GET /api/export?session_id=…&fmt=csv\|xlsx` | full breakdown for the last answer |
| `GET /api/health` | dataset stats, model, and whether the LLM is reachable |
| `GET /api/schema` | datasets, fields and the vendor list |
| `POST /api/reset` | clear conversation state |

---

## Docs

- [Architecture + diagrams](docs/architecture.md)
- [Model choice and efficiency](docs/model-choice.md)
- [Sample questions and answers](docs/sample-questions.md)
- [Demo script](docs/demo-script.md)

## Out of scope

Live banking/ERP integration, authentication, roles and multi-tenancy — deliberately excluded per the brief.
