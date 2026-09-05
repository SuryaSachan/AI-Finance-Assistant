# AI Finance Assistant

A conversational assistant that answers plain-language questions about finance data — spend, vendor payouts and reconciliation — **from the data, never from the model's imagination**.

The design rule is simple: *the language model reads and writes English; SQL does the arithmetic; a verifier checks every digit before it reaches the user.*

```
"How much did we pay out last month?"
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
| **Anomaly call-outs** *(bonus)* | A counterparty whose period total is ≥2.5σ above its own 12-month baseline is flagged alongside the answer. |
| **Sensitive data** | `account_number` is masked to its last 4 digits and `utr_number` is not exposed at all — neither column exists in the queryable catalog. |

---

## How hallucination is actually prevented

Five independent mechanisms, each of which alone would stop a fabricated figure:

1. **The model cannot express a number.** Its only output is a fixed-shape JSON plan — dataset, filters, grouping, period. There is no field in which a figure can be written.
2. **The model cannot express a column.** Fields are validated against `app/schema_catalog.py`; anything invented is stripped before SQL is built, and the correction is shown to the user.
3. **The model cannot express an entity.** Counterparty and enum values are fuzzy-matched against the names that actually occur in the data. No match above threshold → the assistant says the entity does not exist and names the closest real ones.
4. **The model cannot compute.** Dates are resolved in Python; filtering and aggregation happen in DuckDB over a read-only connection.
5. **The model's wording is verified.** Every numeric token in the generated sentence — including `₹`, `,`, `%`, `k`/`M` forms — is traced back to a value in the result set within 0.5 %. One unverifiable digit and the sentence is discarded in favour of the deterministic answer, the UI says so, and confidence drops.

Plus: **zero rows → an explicit "there is no figure to report"**, never an estimate.

`scripts/selftest.py` demonstrates each of these against a stubbed model that deliberately misbehaves.

---

## Sample questions

```
How much did we pay out last month?
Which transactions are still unreconciled?
How does that compare to the month before?          <- follow-up, no context repeated
Top 5 counterparties by spend this year
How much did we pay TATA CAPITAL LIMITED last month?
Show NEFT spend by month year to date
What is the total balance across HDFC accounts?
How much did we spend with Globex Corporation?      <- refused: no such counterparty
What will our spend be next quarter?                <- refused: not answerable from data
```

Full run with the assistant's actual answers and the ground-truth figures: [docs/sample-questions.md](docs/sample-questions.md).

---

## The data

The app is built directly against the provided schema — `bank`, `account`, `transaction` — and queries two flattened views:

| View | Built from | Rows (demo) |
| --- | --- | --- |
| `v_transactions` | `transaction` + `account` + `bank`, plus derived columns | 250,000 |
| `v_accounts` | `account` + `bank` | 40 |

### Derived fields, and why

The schema has no counterparty column and no reconciliation column, but both are central to the brief. Rather than invent data, each is derived from real columns with one shared, documented definition in [app/derivations.py](app/derivations.py), and the assistant states the definition in its answer whenever it uses one:

| Field | Definition |
| --- | --- |
| `counterparty` | Longest run of capitalised words in `description`, minus rail/bank noise tokens. Spelling variants (`SELECTION MOBILE` / `SELECTIONMOBILE`) are folded onto one canonical name. |
| `channel` | Rail detected from the narration: UPI / NEFT / IMPS / RTGS / FT / CHEQUE / ACH / ATM / CHARGES. |
| `reconciliation_status` | `reconciled` when the row carries a `transaction_reference_id` **or** a `utr_number`; `unreconciled` when it carries neither. |
| `account_number_masked` | `XXXXXX` + last 4 digits. |

On the reference-vs-UTR question the schema doc raises: a bare "reference number" resolves to `transaction_reference_id`, the plaintext searchable column. `utr_number` is used only to decide reconciliation state and is never exposed or queried.

### Demo data

Until the real export is loaded, `scripts/generate_data.py` builds a seeded stand-in **in the official schema**, with narrations that follow the formats in the sample data (`FT - … - SELECTION ELECTRONICS`, `UPI-…`, `NEFT/…/…`, `IMPS/P2A/…`), so the derivations are exercised exactly as they will be on the real thing.

```powershell
.\.venv\Scripts\python.exe scripts\generate_data.py --transactions 20000000 --csv
```

### Measured at the 20 M-record limit

| | 20,000,000 transactions |
| --- | --- |
| Database file | 3.89 GB |
| One-off build (generate + derive + index) | 409 s |
| Single-month aggregate | 46 ms |
| Top counterparties, YTD | 145 ms |
| Monthly trend, full history | 387 ms |
| **End-to-end, question to answer** | **401 ms average across the 20-question benchmark** |
| Accuracy | 20/20 — unchanged from 250 k |

Reproduce with `python scripts/benchmark.py --db data/scale20m.duckdb`. The derivations run once at load, not per query; the expensive top-N sample is lazy-loaded by the explain panel rather than sitting on the answer path.

### The 30 real sample rows

The schema document ships 10 rows per table of genuine production patterns. The loader reads SQL blocks straight out of the markdown, so they can be loaded without copy-paste:

```powershell
.\.venv\Scripts\python.exe scripts\load_dataset.py --input "TBX - Database Schema.md" --db data\sample.duckdb
```

All 10 narrations resolve to a counterparty and a channel, and the one row with neither a reference nor a UTR is correctly flagged unreconciled. `scripts/selftest.py` asserts this every run, so a change to the parsing rules cannot silently regress against the real formats.

### Loading the provided dataset

```powershell
# 1. import the files and print every table and column you were given
.\.venv\Scripts\python.exe scripts\load_dataset.py --inspect --input path\to\dataset

# 2. only if table/column names differ from the schema doc, edit config\dataset_mapping.yml

# 3. import, derive, build views, validate
.\.venv\Scripts\python.exe scripts\load_dataset.py --input path\to\dataset
```

Accepts a single file or a folder of them: CSV, TSV, Parquet, JSON, Excel, a `.sql` dump of `CREATE`/`INSERT` statements, a `.md` document with ` ```sql ` blocks, or an existing `.duckdb`.

The validator reports missing fields, empty views, date coverage, the share of narrations that produced no counterparty, and any enum value not declared in [app/schema_catalog.py](app/schema_catalog.py) — so a vocabulary mismatch is caught before it reaches an answer rather than after. Then update the expected figures in [evals/questions.yaml](evals/questions.yaml) and re-run the benchmark.

---

## API

| Endpoint | Purpose |
| --- | --- |
| `POST /api/ask` | `{question, session_id?}` → answer, breakdown, confidence, explain payload, token usage |
| `GET /api/export?session_id=…&fmt=csv\|xlsx` | full breakdown for the last answer |
| `GET /api/records?session_id=…&limit=10` | sample of the raw rows behind the last answer (lazy-loaded by the explain panel) |
| `GET /api/health` | dataset stats, model, and whether the LLM is reachable |
| `GET /api/schema` | datasets, fields and the known counterparty list |
| `POST /api/reset` | clear conversation state |

---

## Docs

- [Architecture + diagrams](docs/architecture.md)
- [Model choice and efficiency](docs/model-choice.md)
- [Sample questions and answers](docs/sample-questions.md)
- [Demo script](docs/demo-script.md)

## Out of scope

Live banking/ERP integration, authentication, roles and multi-tenancy — deliberately excluded per the brief.
