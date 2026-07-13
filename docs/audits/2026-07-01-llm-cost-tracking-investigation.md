# Investigation Report: LLM Cost Tracking Is Broken

**Date**: 2026-07-01
**Investigator**: Claude (investigate skill)
**Severity**: HIGH — blocks any cost-based rate limiting / budgeting; cost dashboards are unreliable
**Status**: Root-caused

## Question
Are we correctly computing/tracking the USD cost of each AI operation? **No — largely not.**
Across ~315k logged LLM calls consuming **~403 million tokens** (S8 161M, S6 106M, S7 136M),
only **$29.58 total** is recorded. The biggest, most expensive operations are logged at **$0**.

| Service | tokens_in | tokens_out | recorded cost |
|---|---|---|---|
| S8 rag-chat | 157,510,997 | 3,440,222 | $6.24 |
| S6 nlp-pipeline | 98,808,693 | 7,451,330 | **$0.00** |
| S7 knowledge-graph | 134,619,160 | 1,562,709 | $23.34 |

## Evidence (Postgres `llm_usage_log`, three DBs)

| Service (DB) | Rows | Zero-cost rows | Recorded $ | Verdict |
|---|---|---|---|---|
| S8 rag-chat (`rag_db`) | 16,823 | 11,621 (69%) | **$6.24** | Partially broken |
| S6 nlp-pipeline (`nlp_db`) | 105,931 | **105,931 (100%)** | **$0.00** | Fully broken |
| S7 knowledge-graph (`intelligence_db`) | 192,078 | 92,792 (48%) | $23.34 | Mostly OK |

Zero-cost rows are **not** empty calls — they carry huge token counts:
- S6 extraction: `gpt-oss-120b` 26.7M input tokens → **$0**; `Qwen3-235B` 7.1M → **$0**; `deepseek-V4` → $0.
- S8 chat: `chat_with_tools`/`tool_loop_iter` on DeepSeek-V4 (35.5M in), Qwen3-235B (22.3M in),
  gpt-oss-120b (24M in) — **all $0**. These are the main tool-calling turns (the priciest path).

## Root causes

### 1. S6 (nlp-pipeline) hardcodes cost to zero — the worst offender
Every S6 usage-log call site passes a literal `estimated_cost_usd=0.0`; the cost calculator is
never invoked:
- `application/blocks/relevance_cascade.py:195`
- `application/blocks/deep_extraction.py:303`
- `infrastructure/workers/article_relevance_scoring_worker.py:491`
- `infrastructure/workers/unresolved_resolution_worker.py:695,718,811,834`

`infrastructure/nlp_db/usage_log_factory.py` just persists whatever it's given (default `0.0`).
Result: 100% of S6 rows are $0, including paid DeepInfra models. This is the "audit value not
persisted / silent-zero" pattern.

### 2. Two divergent cost systems; the legacy one has a stale, incomplete price map
- `libs/ml-clients/pricing.py` — **new canonical** (Decimal, keyed on `model_id`), used **only** by
  rag-chat's `CostRecorder` (`compute_cost`).
- `libs/ml-clients/cost.py` — **legacy** (float, keyed on `provider`+`model_id`), the one S6/S7 were
  meant to use. Its `PRICING` map only contains `Qwen3-235B`, `Qwen3-32B`, `DeepSeek-V4-Flash`
  (deepinfra), plus openrouter/gemini/ollama. It is **missing every other in-use model**:
  `gpt-oss-120b`, `gpt-oss-20b`, `Meta-Llama-3.1-8B-Instruct-Turbo`, `Qwen3.5-9B`. Unknown model →
  `0.0`. The migration to unify on `pricing.py` (promised in its docstring) was never done.

### 3. S8 (rag-chat) prices some capabilities but not the highest-volume ones
Same model is priced on some rows, $0 on others: the `chat_with_tools` / `tool_loop_iter` /
`synthesis` capabilities (the biggest token consumers) log $0, while other capabilities are priced
via `CostRecorder`. Plus `gpt-oss-120b`/`gpt-oss-20b` aren't in `pricing.py` either. Net: only
~31% of chat rows are costed; true chat spend is understated by a large multiple.

### 4. Gateway direct-to-DeepInfra call is entirely untracked
`POST /v1/screener/nl-translate` calls DeepInfra **directly from the api-gateway**
(`routes/market.py`, `_DEEPINFRA_CHAT_URL`). The gateway has no `llm_usage_log` → that spend is
recorded nowhere.

## What is actually correct
- S7 (knowledge-graph) prices its DeepInfra calls ($23.34) and correctly records **$0 for
  local Ollama** models (no API cost) — that zero is legitimate.
- Token counts are broadly captured (except Llama-3.1-8B extraction rows in S6 show 0 tokens — a
  separate token-capture gap worth a follow-up).
- `llm_usage_log` schema is decent (tokens in/out, latency, success, prompt-cache tokens in S8).

## Implications
- **Any cost dashboard today is meaningless** (~$30 recorded vs. true spend likely 1–2 orders of
  magnitude higher given the token volumes).
- **Cost/token-based rate limiting (the production ask) cannot be built on this** until metering is
  fixed — you'd be budgeting against numbers that are ~0. This is a prerequisite for the AI
  rate-limiting "cost quota" work (subagent plan item D).
- `llm_usage_log` also has **no `user_id`** in S8 (only tenant/session/thread) — per-user cost
  quotas need a schema add.

## Recommended fixes (ranked)
1. **S6: compute real cost at every call site** (stop hardcoding 0). Route all three services
   through one calculator. *(M)*
2. **Unify on `pricing.py` and complete the price map** — add `gpt-oss-120b/20b`,
   `Llama-3.1-8B-Instruct-Turbo`, `Qwen3.5-9B`, and any other in-use model; delete/retire
   `cost.py`. Add a CI check that every `model_id` seen in `llm_usage_log` has a pricing entry. *(M)*
3. **S8: cost the `chat_with_tools`/`tool_loop_iter`/`synthesis` paths** (or confirm they're
   intentional aggregates and cost the leaf calls exactly once — avoid double count). *(M)*
4. **Track the gateway's direct DeepInfra screener call** (log usage, or route via S8). *(S)*
5. **Add `user_id` to `llm_usage_log`** for per-user cost accounting (forward-compatible column). *(S)*
6. **Backfill** historical cost by replaying token counts × corrected price map (approximate). *(S)*
7. **Alert** on model_ids that price to $0 with non-zero tokens (would have caught all of this). *(S)*
