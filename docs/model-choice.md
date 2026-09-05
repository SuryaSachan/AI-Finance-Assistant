# Model choice

**Constraint:** lowest possible model, highest possible accuracy. Upper limit 20 B parameters.

**Our answer:** the default is **Qwen2.5-3B-Instruct** (3 B parameters, ~6× under the cap), and the system is designed so that even a 3 B model cannot get a number wrong.

## Why we could go this small

The usual reason a finance chatbot needs a frontier model is that the model is being asked to do three hard things at once: understand the question, write correct SQL, and do arithmetic. We removed two of them.

| Task | Handled by | Model size needed |
| --- | --- | --- |
| Understand intent, filters, dates, follow-ups | LLM | small |
| Emit a **fixed 10-key JSON plan** (not SQL) | LLM in JSON mode | small |
| Turn the plan into SQL | Python whitelist builder | none |
| Filter / group / aggregate | DuckDB | none |
| Explain the computed result in a sentence | LLM | small |
| Guarantee the numbers | Verification guardrail | none |

A 3 B instruct model with constrained JSON decoding is reliable at slot-filling over a 2-view, ~20-field schema. It is not reliable at multi-join SQL or arithmetic — so we never ask it to do either.

## The tiers

| Tier | What runs | When |
| --- | --- | --- |
| 1 | Qwen2.5-3B-Instruct, `format: json`, temperature 0, ~400 output tokens | every question |
| 2 | Same model, one repair round with the validator's exact complaints | plan fails schema validation |
| 3 | Deterministic rule parser (regex intent/period/entity extraction) | model unreachable, or still invalid |

Tier 3 is not a stub. It scores **20/20 on the benchmark on its own**, which is the honest way to demonstrate how little of the accuracy is actually coming from model scale. Tier 1 exists to widen the range of phrasings the system understands, not to produce the numbers.

`LLM_MODEL_FALLBACK` can name a second, larger model for tier 2, but it is empty by default — escalation is opt-in, not the norm.

## Alternatives considered

| Model | Params | Verdict |
| --- | --- | --- |
| **Qwen2.5-3B-Instruct** | 3 B | **Chosen.** Strong JSON adherence for its size, 2 GB at Q4, runs on a laptop CPU. |
| Qwen2.5-7B-Instruct | 7 B | Marginally better on unusual phrasings; 2–3× the latency and memory for no accuracy gain on the benchmark. Drop-in via `LLM_MODEL`. |
| Llama-3.2-3B-Instruct | 3 B | Comparable; slightly weaker at staying inside a JSON schema in our spot checks. |
| Phi-3.5-mini | 3.8 B | Good reasoning, chattier — needed more prompt scaffolding to stop it explaining its JSON. |
| GPT-4-class frontier model | ≫20 B | Disallowed by the constraint, and unnecessary: it would be doing the same slot-filling. |
| No model at all | 0 | Already 100 % on the benchmark, but brittle to phrasing. Kept as the safety net. |

## Efficiency numbers

Measured per question on the shipped benchmark:

| Metric | Tier 1 (3 B) | Tier 3 (no LLM) |
| --- | --- | --- |
| LLM calls | 2 (plan + narrate) | 0 |
| Tokens | ≈ 550 prompt + 120 completion | 0 |
| DuckDB query time | 3–65 ms over 250 k rows | 3–65 ms |
| Benchmark accuracy | 20/20 | 20/20 |

The UI shows tokens and latency on every answer, so the efficiency claim is visible during the demo rather than asserted in a slide.

Prompt cost is kept low deliberately: the schema is rendered compactly (~350 tokens), only the last 4 conversation turns are included, and the narrator receives at most 25 result rows (`LLM_ROW_BUDGET`).

## Accuracy against the sample set

`python evals/run_eval.py` runs 20 questions end to end and compares the reported figure against ground-truth SQL executed directly on DuckDB (0.5 % tolerance), plus structural checks on dataset, intent, grouping and filters. Two of the twenty are adversarial and must be **refused**: an unknown counterparty and a forward-looking forecast question.

Current results are in [sample-questions.md](sample-questions.md) and `evals/results.csv`.

## Swapping the model

```bash
ollama pull qwen2.5:3b-instruct        # default
# .env
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:3b-instruct
```

Any OpenAI-compatible endpoint (vLLM, Groq, Together, OpenRouter) works by setting `LLM_PROVIDER=openai`, `LLM_BASE_URL` and `LLM_API_KEY`. Re-run `python evals/run_eval.py` after switching — that is the number to quote, not a vendor benchmark.
