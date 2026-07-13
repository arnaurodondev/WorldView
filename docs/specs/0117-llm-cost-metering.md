---
id: PRD-0117
title: "Trustworthy LLM Cost Metering — Provider-Cost Capture, Unified Pricing, Auditable Ledger"
status: draft
created: 2026-07-01
updated: 2026-07-01
author: "human + claude"
services: [S6 (nlp-pipeline), S7 (knowledge-graph), S8 (rag-chat), S9 (api-gateway), intelligence-migrations, libs/ml-clients]
priority: P1
estimated-waves: 5
depends-on: []
enables: ["Future PRD — AI endpoint rate limiting & per-user/per-tenant cost quotas"]
---

# PRD-0117: Trustworthy LLM Cost Metering

## 1. Overview & Motivation

### 1.1 Background

Every paid AI operation in worldview — chat tool-loops (S8), news extraction and relevance scoring (S6), knowledge-graph enrichment (S7), and the gateway's NL→screener translation (S9) — routes through DeepInfra (paid), with a small sliver on Gemini and free local Ollama/GLiNER. Each call is meant to be recorded in a per-DB `llm_usage_log` ledger (tokens in/out, latency, success, and an `estimated_cost_usd` figure) so the platform can build cost dashboards and, eventually, cost-based rate limiting.

The ledger is not trustworthy today. It is the single source of truth for a feature that does not yet exist (cost quotas) and for dashboards that already mislead operators.

### 1.2 Problem Statement

The investigation `docs/audits/2026-07-01-llm-cost-tracking-investigation.md` established (root-caused, severity HIGH) that across **~315k logged LLM calls / ~403M tokens** (S8 rag-chat 161M, S6 nlp-pipeline 106M, S7 knowledge-graph 136M), only **$29.58 total** is recorded — the largest, most expensive operations record **$0**. Four root causes:

| # | Root cause | Evidence | Blast |
|---|------------|----------|-------|
| RC-1 | **S6 hardcodes `estimated_cost_usd=0.0`** at every usage-log call site; the cost calculator is never invoked. | `services/nlp-pipeline/.../application/blocks/relevance_cascade.py:195`, `.../blocks/deep_extraction.py:303`, `.../infrastructure/workers/article_relevance_scoring_worker.py:491`, `.../workers/unresolved_resolution_worker.py:695,718,811,834`; `.../infrastructure/nlp_db/usage_log_factory.py` persists whatever it is given (default `0.0`). | **100%** of S6 rows are $0, including 26.7M-token `gpt-oss-120b` extraction and 7.1M-token `Qwen3-235B` runs. |
| RC-2 | **Two divergent cost systems.** `libs/ml-clients/pricing.py` (canonical: `Decimal`, keyed on `model_id`, `compute_cost(model_id, tokens_in, tokens_out) -> Decimal`) is used **only** by rag-chat's `CostRecorder`. Legacy `libs/ml-clients/cost.py` (`float`, keyed `provider`+`model_id`, `estimate_cost(...)`) is what S6/S7 were meant to use — and its `PRICING` map contains only `Qwen3-235B`, `Qwen3-32B`, `DeepSeek-V4-Flash` (deepinfra) + gemini/ollama/openrouter. Unknown model → `0.0`. | `cost.py:25` `PRICING`; `pricing.py` docstring promises unification "never done". | Any S6/S7 model outside that tiny map costs $0. |
| RC-3 | **S8 prices some capabilities but not the highest-volume ones.** `chat_with_tools` / `tool_loop_iter` / `synthesis` (the priciest tool-calling turns) log $0; other capabilities are priced via `CostRecorder`. `gpt-oss-120b/20b` also absent from `pricing.py`. | Audit §3; `pricing.py` MODEL_PRICING has no `gpt-oss-*`. | Only **~31%** of chat rows are costed; true chat spend understated by a large multiple. |
| RC-4 | **Gateway's direct DeepInfra call is untracked.** `POST /v1/screener/nl-translate` calls DeepInfra directly from the gateway (`services/api-gateway/.../routes/market.py`, `_DEEPINFRA_CHAT_URL`). The gateway has no `llm_usage_log`. | Audit §4. | That spend is recorded **nowhere**. |

Additional facts from the audit that shape the design:
- There are **three** `llm_usage_log` tables in three DBs: `rag_db` (S8), `nlp_db` (S6), `intelligence_db` (S7). **None has a `user_id` column** (S8 has only tenant/session/thread).
- S7 is mostly correct ($23.34): it prices DeepInfra and correctly records **$0 for local Ollama** (legitimate).
- Token counts are broadly captured (one separate token-capture gap: some Llama-3.1-8B extraction rows in S6 show 0 tokens — out of scope here, noted as a follow-up).

### 1.3 The Key Enabling Fact (verified live)

**DeepInfra returns the exact per-call USD cost in every response's `usage` object as `usage.estimated_cost`.** Verified live:

```json
{"prompt_tokens": 16, "completion_tokens": 3, "estimated_cost": 4.1e-07}
```

Because DeepInfra is essentially **all** paid volume (S6/S7/S8/S9 route through it; Ollama/GLiNER are local/free; Gemini is a small sliver), capturing this value makes the dominant cost path **authoritative and self-updating** — there is no DeepInfra price map to maintain, and it stays correct when DeepInfra changes prices (which it has done repeatedly in 2025–2026). Our `libs/ml-clients` DeepInfra adapters currently read only `usage.prompt_tokens` / `usage.completion_tokens` and **discard** `usage.estimated_cost`.

### 1.4 Business Value

- **Cost dashboards become real.** Today ~$30 is recorded against a true spend likely 1–2 orders of magnitude higher.
- **Unblocks the next PRD.** Cost/token-based rate limiting and per-user/per-tenant cost quotas (a production ask) cannot be built on a ledger that reads ~$0. This PRD is the prerequisite; it does not build quotas itself.
- **Auditability.** Every ledger row becomes *self-describing* about how its cost was derived (`cost_source`), so operators can trust — or challenge — any figure.

---

## 2. Goals and Non-Goals

### 2.1 In Scope (Goals)

1. **Capture provider-returned cost** (`usage.estimated_cost`) in the shared DeepInfra adapters and thread it through to the usage-log write, as the authoritative cost for those calls (FR-1).
2. **Add an auditable `cost_source` column** (`provider` | `pricematrix` | `local`) to all three `llm_usage_log` tables (FR-2).
3. **Add a nullable `user_id` column** to `llm_usage_log` (at least `rag_db`; assess `nlp_db`/`intelligence_db`) for future per-user cost accounting (FR-3).
4. **Fix S6 and S7** — stop hardcoding `0.0`; route both through the unified cost path (provider cost primary, price-matrix fallback). Retire/redirect legacy `cost.py` so there is **one** calculator (FR-4).
5. **Complete the `pricing.py` matrix** — add every in-use model missing from it (FR-5).
6. **Track the gateway's direct DeepInfra screener call** — capture its `usage.estimated_cost` and log it (FR-6).
7. **Guardrails** — a CI/startup check that every seen `model_id` is priceable, plus a runtime alert/metric for `tokens > 0 & cost == 0 & paid provider` (FR-7).
8. **(Lower priority, follow-up wave)** Approximate backfill of historical $0 rows via tokens × current price, documented as approximate (FR-8).

### 2.2 Cost-Source Priority (LOCKED — the core design)

Every call resolves its persisted cost by this ordered rule; the winning rule is stamped in `cost_source`:

| Priority | Rule | `cost_source` | Applies to |
|----------|------|---------------|------------|
| 1 | **Provider-returned cost.** If the provider response carries `usage.estimated_cost`, persist that value **verbatim** (converted to `Decimal`). Authoritative; self-updating; no price map needed. | `provider` | DeepInfra (all paid volume) |
| 2 | **Price-matrix fallback.** If the provider does **not** return a cost, compute `tokens_in × rate_in + tokens_out × rate_out` from the canonical `libs/ml-clients/pricing.py` matrix. | `pricematrix` | Gemini and any other cost-silent provider |
| 3 | **Local / free.** Ollama, GLiNER, and other locally-hosted models cost `$0` legitimately. | `local` | Ollama, GLiNER |

The `llm_usage_log` ledger **snapshots the cost per row at write time**, so historical figures are immutable regardless of future price changes — the row's `cost_source` tells the reader whether that snapshot came from the provider or our matrix.

### 2.3 Out of Scope (Non-Goals)

- **AI endpoint rate limiting / per-user & per-tenant token or cost quotas.** That is a **future PRD that depends on this one.** This PRD only makes cost data trustworthy and adds the `user_id` column that quotas will need. (Named here as motivation and next step, not delivered here.)
- **An effective-dated DB pricing table.** YAGNI now: the fallback set (rule 2) is tiny and slow-moving; a shared pricing table would violate R9 (no cross-service DB), and the **git history of `pricing.py` is itself the dated price history**. Revisit only if any of: (a) multiple cost-silent providers appear, (b) prices must change at runtime without a deploy, or (c) accurate historical re-pricing (not approximate backfill) becomes a requirement.
- **The S6 token-capture gap** (some Llama-3.1-8B extraction rows show 0 tokens) — separate defect, tracked as a follow-up, not fixed here.
- **New cost dashboards / UI.** Making the data correct is in scope; visualising it is not.
- **Migrating away from DeepInfra or changing model selection.** No model routing changes.

---

## 3. User Stories

### Persona A — Platform Operator (Nadia)
| ID | Story | Priority |
|----|-------|----------|
| US-A1 | As an operator, I want each `llm_usage_log` row to record the real USD cost of the call, so my cost dashboard reflects true spend rather than ~$0. | must-have |
| US-A2 | As an operator, I want each row to tell me *how* its cost was derived (`provider` vs `pricematrix` vs `local`), so I can trust or challenge any figure. | must-have |
| US-A3 | As an operator, I want an alert when a paid model logs non-zero tokens but $0 cost, so a regression like this never silently recurs. | must-have |

### Persona B — Platform Engineer (Marc)
| ID | Story | Priority |
|----|-------|----------|
| US-B1 | As an engineer, I want exactly one cost calculator across all services, so I don't have to reason about two divergent price maps. | must-have |
| US-B2 | As an engineer, I want CI to fail if a model appears in usage without a pricing path, so an unpriced model is caught before it ships. | must-have |
| US-B3 | As an engineer, I want the DeepInfra adapter to surface the provider's own cost, so I never maintain DeepInfra prices by hand. | must-have |

### Persona C — Product (future quota work)
| ID | Story | Priority |
|----|-------|----------|
| US-C1 | As the team building cost quotas next, I want a `user_id` on the chat usage ledger, so per-user cost accounting has a column to aggregate on. | should-have |
| US-C2 | As the team building cost quotas next, I want historical $0 rows approximately re-priced, so the first quota baselines aren't zero. | nice-to-have |

---

## 4. Functional Requirements

### FR-1 (CRITICAL): Capture provider-returned cost in the DeepInfra adapters

The shared DeepInfra adapters in `libs/ml-clients/src/ml_clients/adapters/` currently parse `response.usage.prompt_tokens` / `.completion_tokens` and discard `response.usage.estimated_cost`. Capture `usage.estimated_cost` (a float USD value; DeepInfra always includes it) and thread it through to the usage-log write and to the `ml_api_estimated_cost_usd_total` metric.

**Affected adapters** (all DeepInfra-backed call paths): `deepinfra_description.py`, `deepinfra_embedding.py`, `deepseek_extraction.py`, and any other adapter that posts to a DeepInfra endpoint and receives an OpenAI-shaped `usage` object. (`chatgpt_extraction.py` / `anthropic_extraction.py` / `gemini_*` are non-DeepInfra and follow FR-5's matrix path; `ollama_*` and `gliner_*` are `local`.)

> **Adapter-parity caveat (verified in code):** `deepinfra_description.py` (l.309-310) and `deepseek_extraction.py` (l.533-534) already read `response.usage.prompt_tokens/completion_tokens`, so adding an `estimated_cost` read there is a one-line addition next to existing usage parsing. **`deepinfra_embedding.py` does NOT parse `response.usage` at all** — it derives tokens from a word-count approximation and computes cost as `token_count * 0.000000013` (l.192-194). Capturing the provider cost there requires actually parsing the response body's `usage` object (and DeepInfra's *embedding* endpoint may or may not return `estimated_cost` — unverified live). If it does not, the embedding path stays on the matrix (`cost_source='pricematrix'`, `BAAI/bge-large-en-v1.5` already priced) and the best-effort/never-raise rule still holds. The S8 chat path (`rag-chat/infrastructure/llm/deepinfra_adapter.py` l.168-176) reads `usage.prompt_tokens/completion_tokens` and its `CostRecorder.record` takes tokens only — it likewise discards `estimated_cost` today.

**Acceptance criteria**:
- When a DeepInfra response includes `usage.estimated_cost`, the adapter surfaces it (e.g. via the existing `LlmCallUsage` dataclass gaining an optional `provider_cost_usd: Decimal | None` and a `cost_source` field, or an equivalent typed carrier) and the value is persisted **verbatim** as `estimated_cost_usd` with `cost_source='provider'`.
- The value is converted to `Decimal` for persistence into the `Numeric(12,6)` cost column without float-rounding drift.
- If `usage.estimated_cost` is absent or malformed, the adapter falls back to FR-5's matrix path (`cost_source='pricematrix'`) — it must **never** silently write `0.0` for a paid model.
- Cost capture remains **best-effort**: a failure to parse cost must log a structured warning and must **never** raise into the main request path.

### FR-2 (HIGH): `cost_source` column on all three `llm_usage_log` tables

Add a `cost_source` column so every row is auditable.

- Type: `VARCHAR(16)`, **nullable**, with an application-level convention of `provider` | `pricematrix` | `local` (enum-like text, not a DB enum, to keep migrations forward-compatible — R11).
- Added to `rag_db`, `nlp_db`, and `intelligence_db` `llm_usage_log`.
- Nullable + no server backfill required (existing rows read `NULL` = "unknown provenance / pre-PRD-0117"). New writes always set it.

### FR-3 (MEDIUM): `user_id` column on `llm_usage_log`

Add a **nullable** `user_id UUID` column for future per-user cost quotas.

- **S8 `rag_db`: required.** The chat path knows the authenticated user; wire it through at write time where available (many rows may still be `NULL` for system/background calls — that is acceptable).
- **S6 `nlp_db` / S7 `intelligence_db`: add the column** (nullable, forward-compatible) but population is best-effort — these are largely system/background pipelines with no end-user; leaving `user_id` `NULL` there is expected and legitimate. Adding the column now avoids a second migration when quotas arrive.

### FR-4 (CRITICAL): One calculator — fix S6, route S6+S7 through the unified path

- Remove every hardcoded `estimated_cost_usd=0.0` at the S6 call sites (RC-1 list) and in `usage_log_factory.py`'s default behaviour.
- Route S6 and S7 usage-log writes through the cost-source priority (§2.2): provider cost if present (FR-1), else `pricing.py` matrix (FR-5), else `local`.
- **Retire/redirect `libs/ml-clients/cost.py`.** Preferred: make `cost.py.estimate_cost(provider, model_id, tokens_in, tokens_out)` **delegate** to `pricing.py.compute_cost(model_id, tokens_in, tokens_out)` (dropping the `provider` key, since a model_id uniquely determines pricing) so existing S6/S7 call sites keep compiling while there is now **one** price source. Long-term: remove `cost.py` once no caller remains. Either way, `pricing.py` is the single source of truth after this PRD.
- Ollama/GLiNER paths in S6/S7 continue to write `$0` with `cost_source='local'` (unchanged, legitimate).

**Acceptance criteria**:
- Zero S6 rows written with a hardcoded `0.0` for a DeepInfra model after deploy.
- `grep` for `estimated_cost_usd=0.0` returns no results at S6 paid call sites (Ollama/local sites may legitimately pass `0.0` with `cost_source='local'`).
- `cost.py` no longer holds an independent `PRICING` map (delegates or deleted).

### FR-5 (HIGH): Complete the `pricing.py` matrix

`pricing.py.MODEL_PRICING` already contains `deepseek-ai/DeepSeek-V4-Flash`, `meta-llama/Meta-Llama-3.1-8B-Instruct`, `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo`, `Qwen/Qwen3-235B-A22B-Instruct-2507`, `Qwen/Qwen3-32B`, `deepseek-r1-distill-qwen-32b`, `BAAI/bge-large-en-v1.5`, `rerank-english-v3.0`, `gemini-3.1-flash-lite`.

**Genuinely missing** (found in live `llm_usage_log.model_id` per the audit): `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `Qwen/Qwen3.5-9B` (and any other model_id surfaced by the FR-7 audit query). Add each with dated `notes` and `input_per_million` / `output_per_million`.

> **Precision note (corrects the audit wording):** `cost.py` is missing `Meta-Llama-3.1-8B-Instruct-Turbo`; `pricing.py` already has it. The models genuinely absent from the **canonical** `pricing.py` are the `gpt-oss-*` pair and `Qwen3.5-9B`. Because the matrix is now a **fallback** for cost-silent providers only (DeepInfra self-reports), the `gpt-oss-*` entries chiefly serve the guardrail (FR-7) and any non-DeepInfra route.

**Acceptance criteria**:
- Every distinct `model_id` present in any `llm_usage_log` today either has a `MODEL_PRICING` entry, or is provider-cost-covered (DeepInfra), or is a known `local` model — verified by the FR-7 check.
- Prices carry an "as of 2026-07" `notes` tag.

### FR-6 (MEDIUM): Track the gateway's direct DeepInfra screener call

`POST /v1/screener/nl-translate` (`services/api-gateway/.../routes/market.py`, `_DEEPINFRA_CHAT_URL`) is untracked. Capture its `usage.estimated_cost` from that call path and record it.

**Storage decision (LOCKED):** do **NOT** add a new gateway-owned `llm_usage_log` DB (R9 — the gateway has no such DB and should not grow one). Instead, **route the usage record to the existing S8 `rag_db` ledger** via a lightweight internal call: the gateway POSTs a usage record to a small **internal-only** S8 endpoint `POST /internal/v1/llm-usage` which persists into `rag_db.llm_usage_log` (with `capability='screener_nl_translate'`, `cost_source='provider'`). This keeps all "gateway-adjacent" LLM spend in one ledger and honours "frontend/gateway → S9→services" boundaries via an internal service call rather than cross-service DB access.

- The internal endpoint is best-effort: gateway logs a warning on failure and **never** fails the user's screener request because usage-logging failed.
- Rationale over the alternative ("gateway proxies the call through S8's chat path"): the NL-translate call is a distinct, gateway-owned capability; proxying it through the chat service would entangle two unrelated code paths. A thin usage-ingest endpoint is the smaller change.

### FR-7 (HIGH): Guardrails — CI/startup check + runtime alert

**(a) Priceability check (CI + service startup).** A check that asserts every `model_id` the platform can emit is *priceable*: it appears in `pricing.py.MODEL_PRICING`, OR is a known DeepInfra model (provider-cost path), OR is on an explicit `LOCAL_FREE_MODELS` allow-list. Two enforcement points:
- **CI test** (in `libs/ml-clients` and/or `intelligence-migrations` arch tests) that fails if a configured model id (from service settings / model registry) has no pricing path.
- **Startup log** in each consumer: on boot, log a structured warning listing any configured model with no pricing path.

**(b) Runtime silent-zero alert.** A metric/alert firing when a row is written with `tokens_in + tokens_out > 0` **and** `estimated_cost_usd == 0` **and** provider is a **paid** provider (i.e. `cost_source != 'local'`). Emit a counter (e.g. `llm_usage_silent_zero_cost_total{service,model_id}`) and wire an alert. This class of check would have caught the entire RC-1/RC-2/RC-3 failure.

### FR-8 (LOW, follow-up wave): Approximate historical backfill

Re-price historical `estimated_cost_usd = 0` rows by `tokens × current pricing.py rate`, written into the same column with `cost_source='pricematrix'` and a clear marker that these are **approximate** (current prices applied to old traffic; DeepInfra prices have fallen over time, so this is an upper-ish estimate, not the true historical charge).

- Ships as its own wave, lower priority, after FR-1..FR-7 are live.
- Documented as approximate in the migration/one-off script and in `docs/services/*` cost sections.
- Rows already carrying a real `provider` cost are **not** touched.

---

## 5. Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | **Best-effort logging.** Cost capture/logging must never raise into or slow down the main request path (existing pattern). All failures → structured warning + continue. |
| NFR-2 | **Decimal precision.** Costs persisted as `Numeric(12,6)`; computed via `Decimal` to avoid float drift (matches `pricing.py`). Provider floats converted to `Decimal` on ingest. |
| NFR-3 | **Forward-compatible schema (R11).** New columns are nullable, no rename/removal of existing columns, no non-defaulted NOT NULL. |
| NFR-4 | **Observability.** New metrics: `llm_usage_silent_zero_cost_total`; existing `ml_api_estimated_cost_usd_total` now fed real values. Dashboards read `cost_source` for provenance breakdown. |
| NFR-5 | **No latency regression.** Provider-cost capture is a field read from an already-parsed response — O(1), no extra network calls. Matrix fallback is a dict lookup. |

---

## 6. Technical Design

### 6.1 Affected Services & Files

| Service / lib | Change | Key files |
|---|---|---|
| `libs/ml-clients` | Capture `usage.estimated_cost` in DeepInfra adapters; add `cost_source` + optional `provider_cost_usd` to the usage carrier; make `cost.py` delegate to `pricing.py`; complete `MODEL_PRICING`; add `LOCAL_FREE_MODELS` + priceability check. | `adapters/deepinfra_description.py`, `adapters/deepinfra_embedding.py`, `adapters/deepseek_extraction.py`, `pricing.py`, `cost.py`, `usage_log.py` (`LlmCallUsage`, `LlmUsageLogProtocol.log`) |
| S6 nlp-pipeline | Remove hardcoded `0.0`; route writes through unified cost path; write `cost_source` (+ `user_id` where available). | `application/blocks/relevance_cascade.py:195`, `application/blocks/deep_extraction.py:303`, `infrastructure/workers/article_relevance_scoring_worker.py:491`, `infrastructure/workers/unresolved_resolution_worker.py:695,718,811,834`, `infrastructure/nlp_db/usage_log_factory.py` |
| S7 knowledge-graph | Ensure enrichment writes go through unified path; write `cost_source`; keep Ollama `local`. | knowledge-graph usage-log write path (mirrors S6 factory) |
| S8 rag-chat | Cost `chat_with_tools`/`tool_loop_iter`/`synthesis` leaf calls exactly once via provider cost; write `cost_source` + `user_id`; add internal `POST /internal/v1/llm-usage` ingest endpoint (FR-6). | `CostRecorder` / chat usage-log write path; new internal route + use case |
| S9 api-gateway | Capture `usage.estimated_cost` from the direct DeepInfra screener call; POST usage to S8 internal endpoint. | `.../routes/market.py` (`_DEEPINFRA_CHAT_URL`, `POST /v1/screener/nl-translate`) |
| S6 nlp-pipeline alembic | Migration adding `cost_source` + `user_id` to **`nlp_db`** `llm_usage_log`. **nlp_db DDL is owned by nlp-pipeline itself** (`alembic/env.py`: "S6 ONLY manages nlp_db"; `ALEMBIC_ENABLED=false` applies only to its *intelligence_db* adapter connection, not nlp_db). | `services/nlp-pipeline/alembic/versions/0023_*` (next after head `0022_add_fallback_reason_to_llm_usage_log`) |
| intelligence-migrations | Migration adding `cost_source` + `user_id` to **`intelligence_db`** `llm_usage_log` only. | `alembic/versions/0064_*` (next after head `0063_create_graph_edges`) |
| rag-chat alembic | Migration adding `cost_source` + `user_id` to `rag_db` `llm_usage_log`. | `alembic/versions/0010_*` (next after head `0009_add_estimated_cost_usd_to_chat_threads`) |

### 6.2 API Changes

#### POST /internal/v1/llm-usage  (S8 rag-chat, internal-only)
- **Purpose**: Ingest a single LLM usage record (from the gateway's direct DeepInfra call, FR-6) into `rag_db.llm_usage_log`. Not exposed to the frontend; service-to-service only.
- **Auth**: internal-only (S9→S8 internal JWT / service auth, same pattern as other `/internal/*` routes).
- **Request body**:

  | Field | Type | Required | Default | Validation | Description |
  |-------|------|----------|---------|------------|-------------|
  | model_id | string | yes | — | 1–200 chars | DeepInfra model used |
  | provider | string | yes | — | e.g. `deepinfra` | Transport provider |
  | capability | string | yes | — | e.g. `screener_nl_translate` | Call role |
  | tokens_in | int | yes | 0 | ≥0 | Prompt tokens |
  | tokens_out | int | yes | 0 | ≥0 | Completion tokens |
  | estimated_cost_usd | number(Decimal) | yes | — | ≥0 | From `usage.estimated_cost` |
  | cost_source | string | yes | — | `provider`\|`pricematrix`\|`local` | Provenance |
  | latency_ms | int | no | 0 | ≥0 | Round-trip latency |
  | success | bool | no | true | — | Call outcome |
  | error_code | string | no | null | ≤50 chars | On failure |
  | tenant_id | UUID | no | null | UUIDv7 | Caller tenant |
  | user_id | UUID | no | null | UUIDv7 | Caller user (FR-3) |

- **Response (200)**: `{ "recorded": true }` (200 + dict, never 204 — BP-064).
- **Error responses**: 401 (not internal), 422 (validation). On any S8-side persistence failure the endpoint still returns 200 with `{"recorded": false}` so the gateway's best-effort call never surfaces an error to the user path (NFR-1).
- **Rate limit**: none (internal, low volume — one call per screener NL translate).

> No public/frontend API shape changes. `/v1/screener/nl-translate` request/response are unchanged (only its internal side-effect logging is added).

### 6.3 Event Changes

**None.** No Kafka topics are added or modified. Usage logging is a synchronous best-effort DB write (existing pattern); FR-6 uses a REST internal call, not an event.

### 6.4 Database Changes

Two new columns × three tables. All nullable, no backfill needed for the schema step (FR-8 backfill is a later data-only wave). Migration **ownership** per repo reality (verified in code — corrects an earlier assumption):
- **`nlp_db` DDL is owned by S6 nlp-pipeline itself.** `services/nlp-pipeline/alembic/env.py` states "S6 ONLY manages nlp_db"; its usage-log table was created by nlp-pipeline migration `0008` and last touched by `0022`. `ALEMBIC_ENABLED=false` on S6 applies **only** to its *intelligence_db* adapter connection, not to nlp_db. → nlp_db migration lives in **nlp-pipeline's own alembic** (`0023`).
- **`intelligence_db` DDL is owned by intelligence-migrations** (`env.py` uses `INTELLIGENCE_DB_URL`; head `0063`). S7 knowledge-graph runs `ALEMBIC_ENABLED=false` (it has no own alembic dir). → intelligence_db migration is intelligence-migrations `0064`.
- **`rag_db` DDL is owned by rag-chat** (head `0009`). → rag-chat `0010`.

There is **no** intelligence-migrations `0065`; the nlp_db and intelligence_db `llm_usage_log` tables live in **different services' alembic lineages**, not one shared lineage (this resolves OQ-2).

#### Table: llm_usage_log (rag_db) — owned by rag-chat, migration `0010`
| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| cost_source | VARCHAR(16) | yes | NULL | `provider`\|`pricematrix`\|`local`; NULL = pre-0117 |
| user_id | UUID | yes | NULL | Future per-user cost quotas (FR-3) |
- Current head: `0009_add_estimated_cost_usd_to_chat_threads`. New: `0010_add_cost_source_and_user_id_to_llm_usage_log`.
- Optional index: none required now (aggregation is offline/dashboard). A future quota PRD may add `(user_id, created_at)`.

#### Table: llm_usage_log (nlp_db) — owned by **nlp-pipeline (S6)**, migration `0023`
| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| cost_source | VARCHAR(16) | yes | NULL | as above |
| user_id | UUID | yes | NULL | added for parity; population best-effort/NULL for system pipelines |
- Current nlp-pipeline head: `0022_add_fallback_reason_to_llm_usage_log`. New: `0023_add_cost_source_and_user_id_to_llm_usage_log`. `down_revision='0022'`.

#### Table: llm_usage_log (intelligence_db) — owned by intelligence-migrations, migration `0064`
| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| cost_source | VARCHAR(16) | yes | NULL | as above |
| user_id | UUID | yes | NULL | added for parity; population best-effort/NULL |

- Current intelligence-migrations head: `0063_create_graph_edges`. New: `0064_*` (intelligence_db only). `down_revision='0063'`. The nlp_db columns are NOT added here — they ship via nlp-pipeline's own `0023` (different lineage).

### 6.5 Domain / Carrier Model Changes

#### `LlmCallUsage` (libs/ml-clients/usage_log.py)
- Add `provider_cost_usd: Decimal | None = None` — verbatim `usage.estimated_cost` when the provider reports it; `None` otherwise.
- Add `cost_source: str = "pricematrix"` — one of `provider` | `pricematrix` | `local`; resolved by the priority rule at write time.
- **Invariant**: if `cost_source == 'provider'` then `provider_cost_usd is not None`; if `cost_source == 'local'` then `estimated_cost_usd == Decimal("0")`.
- Backward compatible: both new fields default, so existing constructions and tests keep compiling (add-with-default pattern).

#### `LlmUsageLogProtocol.log(...)`
- Add optional keyword params `cost_source: str | None = None` and `user_id: UUID | None = None`, threaded to persistence. Defaults preserve existing call sites.

#### `pricing.py`
- `MODEL_PRICING` gains `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `Qwen/Qwen3.5-9B` (+ any other id surfaced by FR-7).
- New `LOCAL_FREE_MODELS: frozenset[str]` allow-list (Ollama/GLiNER ids) used by the priceability check.
- New helper `is_priceable(model_id, *, provider) -> bool` used by the CI/startup guardrail.

### 6.6 Data Flow

**Paid DeepInfra call (dominant path):** service → `libs/ml-clients` DeepInfra adapter → HTTP POST → response parsed → read `usage.prompt_tokens/completion_tokens` **and** `usage.estimated_cost` → build `LlmCallUsage(provider_cost_usd=Decimal(estimated_cost), cost_source='provider')` → `LlmUsageLogProtocol.log(...)` writes row with real cost.

**Cost-silent provider (Gemini):** adapter has no `usage.estimated_cost` → `compute_cost(model_id, tokens_in, tokens_out)` from matrix → `cost_source='pricematrix'`.

**Local (Ollama/GLiNER):** `estimated_cost_usd=0`, `cost_source='local'`.

**Gateway screener (FR-6):** user → S9 `/v1/screener/nl-translate` → direct DeepInfra POST → parse `usage.estimated_cost` → best-effort `POST /internal/v1/llm-usage` to S8 → `rag_db.llm_usage_log` row (`cost_source='provider'`).

### 6.7 Frontend Changes

**None.** No UI is added in this PRD (dashboards are out of scope per §2.3).

---

## 7. Architecture Decisions & Trade-offs

| Decision | Chosen | Rejected alternative | Why |
|---|---|---|---|
| DeepInfra cost source | Trust provider's `usage.estimated_cost` verbatim | Maintain DeepInfra prices in `pricing.py` | Self-updating, exact, zero maintenance; DeepInfra cuts prices often. |
| Fallback pricing store | `pricing.py` (git-versioned matrix) | Effective-dated DB pricing table | YAGNI; DB table violates R9; git history = dated price history; per-row snapshot already immutable. |
| One calculator | `cost.py` delegates to `pricing.py`, then retire | Keep both, sync by hand | Two maps already drifted into this bug (RC-2). |
| Gateway usage storage | Internal `POST /internal/v1/llm-usage` → `rag_db` | New gateway-owned `llm_usage_log` DB | No new DB for the gateway (R9); one ledger for gateway-adjacent LLM spend. |
| `cost_source` type | `VARCHAR(16)` text convention | Postgres ENUM | Forward-compatible (R11); adding a value later needs no migration. |

### 7.1 Architecture Compliance Gate

| Rule | Applies? | Design decision | Compliant? |
|------|----------|-----------------|-----------|
| R9 — No cross-service DB access | yes | Gateway writes via S8 internal REST, not direct DB; no shared pricing table | PASS |
| R11 — Forward-compatible schema | yes | Only nullable columns added, no rename/removal, text (not enum) `cost_source` | PASS |
| R6 — UUIDv7 | yes | `user_id` is a UUID (UUIDv7 where minted); no new id generation here | PASS |
| R7 — UTC timestamps | yes | No new timestamp columns; existing `created_at` is UTC | PASS |
| R13 — Use shared libs | yes | Single calculator in `libs/ml-clients`; all services consume it | PASS |
| R14 — Frontend → S9 only | yes | No frontend change; FR-6 is S9→S8 internal | PASS |
| R15 — Update docs | yes | §12 lists doc updates | PASS |
| Migration ownership | yes | `nlp_db` DDL via **nlp-pipeline** (`0023`); `intelligence_db` DDL via **intelligence-migrations** (`0064`); `rag_db` via **rag-chat** (`0010`) — each lineage owned by its own service (verified in `alembic/env.py` files) | PASS |

No FAIL rows.

---

## 8. Security Analysis

- **No new untrusted input surface** except `POST /internal/v1/llm-usage` — internal-only, authenticated as a service call; validate all fields (Pydantic), reject non-internal callers (401).
- **No secrets added.** DeepInfra keys already present via pydantic-settings (R8). Cost values are not sensitive.
- **PII**: `user_id` is an internal UUID, not PII; stored only for aggregation. Multi-tenant reads of the ledger (future dashboards/quotas) must filter by `tenant_id` — noted for the downstream PRD, not built here.
- **Log safety**: never log full prompts/responses when capturing cost; only tokens + cost + model_id (existing structlog pattern).

---

## 9. Failure Modes

| Failure | Behaviour | Recovery |
|---|---|---|
| DeepInfra omits/garbles `usage.estimated_cost` | Adapter falls back to matrix (`cost_source='pricematrix'`); if model also unpriced → warning + `0.0` **but** FR-7 silent-zero alert fires | FR-5 add the model; alert makes it visible |
| S8 internal usage endpoint down (FR-6) | Gateway logs warning, screener request still succeeds | Row lost (best-effort); acceptable — low volume, alertable via absence |
| `pricing.py` missing a new model_id | FR-7 CI test fails before ship; startup logs warning | Add entry |
| Migration applied but old service image still writes without `cost_source` | Column nullable → writes succeed with `cost_source=NULL` | Rollout order (§10) rebuilds consumers after migration |
| Provider float → Decimal conversion edge (e.g. `4.1e-07`) | Convert via `Decimal(str(value))` to avoid binary-float artifacts | Unit test covers scientific-notation values |

Cross-ref BUG_PATTERNS: this whole PRD closes the "audit value returned but not persisted / silent-zero" family (RC-1) and the "input-form vs lookup-form mismatch / two lists that must agree but don't" family (RC-2, two price maps).

---

## 10. Rollout

**Order matters** (forward-compatible columns make it safe):
1. Apply migrations: rag-chat `0010` (rag_db); nlp-pipeline `0023` (nlp_db); intelligence-migrations `0064` (intelligence_db). Columns nullable → old images keep working.
2. Rebuild + redeploy `libs/ml-clients` consumers that changed behaviour: **nlp-pipeline (S6), knowledge-graph (S7), rag-chat (S8), api-gateway (S9)**. (Follow the "compose build ships stale prompts/libs" caution: verify the new `pricing.py`/adapter code is actually in each container before smoke-testing.)
3. Smoke: trigger one paid call per service; confirm a `llm_usage_log` row with `estimated_cost_usd > 0` and `cost_source='provider'`; confirm an Ollama call writes `cost_source='local'`, `0`.
4. Enable FR-7 alert; run FR-7 CI check in the pipeline.
5. (Later wave) FR-8 backfill.

**Rollback**: redeploy prior images (columns remain, harmlessly NULL for new rows). Migrations are additive; a down-migration dropping the two columns exists but is not needed for rollback.

---

## 11. Test Strategy

### Unit Tests
| Test | Verifies | Priority |
|------|----------|----------|
| test_deepinfra_adapter_captures_estimated_cost | Adapter surfaces `usage.estimated_cost` as `provider_cost_usd`, `cost_source='provider'` | HIGH |
| test_deepinfra_cost_scientific_notation_to_decimal | `4.1e-07` → `Decimal("0.00000041")`, no float drift | HIGH |
| test_deepinfra_missing_cost_falls_back_to_matrix | Absent `usage.estimated_cost` → `compute_cost` path, `cost_source='pricematrix'` | HIGH |
| test_adapter_never_raises_on_cost_parse_error | Malformed usage → warning + continue, main result unaffected | HIGH |
| test_pricing_has_gpt_oss_and_qwen35_9b | New MODEL_PRICING entries present with non-negative rates | HIGH |
| test_cost_py_delegates_to_pricing | `estimate_cost(provider, model_id, ...)` == `compute_cost(model_id, ...)` | HIGH |
| test_local_model_is_zero_local | Ollama/GLiNER id → `0`, `cost_source='local'` | MEDIUM |
| test_llmcallusage_invariants | `provider` ⇒ provider_cost set; `local` ⇒ cost 0 | MEDIUM |
| test_is_priceable_allowlist | `is_priceable` true for matrix/DeepInfra/local, false otherwise | HIGH |
| test_s6_call_sites_no_hardcoded_zero | Each fixed S6 site passes computed cost + `cost_source`, not literal `0.0` | HIGH |

### Integration Tests (testcontainers Postgres)
| Test | Infra | Verifies |
|------|-------|----------|
| test_rag_migration_0010_adds_columns | Postgres | `cost_source`,`user_id` exist, nullable; existing rows read NULL |
| test_nlp_0023_and_intel_0064_add_columns | Postgres | Same on nlp_db + intelligence_db tables |
| test_s6_extraction_writes_real_cost | Postgres | A simulated DeepInfra extraction → row with cost>0, `cost_source='provider'` |
| test_internal_llm_usage_endpoint_persists | Postgres + S8 app | `POST /internal/v1/llm-usage` writes a `rag_db` row |
| test_internal_llm_usage_endpoint_best_effort | S8 app | Persistence error → 200 `{"recorded": false}`, no raise |
| test_gateway_screener_logs_usage | S9 + S8 stub | NL-translate triggers one usage POST with `cost_source='provider'` |

### Guardrail / Arch Tests
| Test | Verifies |
|------|----------|
| test_all_configured_models_priceable | Every model id in service settings has a pricing path (FR-7a) — CI gate |
| test_silent_zero_cost_metric_increments | Writing tokens>0 & cost 0 & non-local → `llm_usage_silent_zero_cost_total` increments (FR-7b) |

### Data Test (FR-8 wave)
| Test | Verifies |
|------|----------|
| test_backfill_marks_pricematrix_and_skips_provider_rows | Backfill re-prices only `0.0` rows, stamps `cost_source='pricematrix'`, leaves provider-costed rows untouched |

---

## 12. Documentation Updates (mandatory)

- `docs/services/nlp-pipeline.md`, `docs/services/knowledge-graph.md`, `docs/services/rag-chat.md`, `docs/services/api-gateway.md` — cost-metering sections: provider-cost priority, `cost_source`, `user_id`.
- `services/{nlp-pipeline,knowledge-graph,rag-chat,api-gateway}/.claude-context.md` — pitfall: "never hardcode `estimated_cost_usd=0.0` for paid models; use the unified cost path; `pricing.py` is the single calculator."
- `libs/ml-clients` docs / `pricing.py` docstring — mark unification **done**; document DeepInfra provider-cost-first rule and `cost_source` semantics; note `cost.py` retired/delegating.
- `docs/BUG_PATTERNS.md` — add the "silent-zero LLM cost / two divergent price maps" pattern (RC-1/RC-2) with the FR-7 guardrail as prevention.
- `.claude/review/checklists/REVIEW_CHECKLIST.md` — add "any new LLM call site records real cost via the unified path + `cost_source`".
- `docs/plans/TRACKING.md` — register PRD-0117.

---

## 13. Observability

- New metric `llm_usage_silent_zero_cost_total{service,model_id}` + alert (FR-7b).
- `ml_api_estimated_cost_usd_total{model_id}` now fed real provider costs (was frequently `.inc(0.0)`).
- Dashboards can group cost by `cost_source` to show provider-vs-matrix-vs-local provenance and spot matrix-only (approximate) spend.

---

## 14. Open Questions

All core design decisions are LOCKED (§2.2, FR-1..FR-8, §6). Remaining items are **DEFERRED** (implementation can proceed with the stated assumption); none are BLOCKING.

| # | Question | Classification | Assumption to proceed |
|---|----------|----------------|-----------------------|
| OQ-1 | Exact per-1M rates for `gpt-oss-120b/20b` and `Qwen3.5-9B` at the moment of implementation. | DEFERRED | Use DeepInfra's published 2026-07 prices; since DeepInfra self-reports cost these entries mainly serve the FR-7 guardrail. Confirm at implementation time. |
| OQ-2 | Do `nlp_db` and `intelligence_db` `llm_usage_log` share one Alembic lineage or two? | **RESOLVED** (verified in code) | **Two separate service lineages, not one.** `nlp_db` is owned by nlp-pipeline (migration `0023`, next after `0022`); `intelligence_db` is owned by intelligence-migrations (migration `0064`, next after `0063`). They cannot be collapsed. `ALEMBIC_ENABLED=false` on S6 refers only to its intelligence_db adapter, not its own nlp_db. |
| OQ-3 | For S8, are `chat_with_tools`/`tool_loop_iter`/`synthesis` rows leaf calls or aggregates? Cost the leaf exactly once to avoid double counting. | DEFERRED | Cost each real DeepInfra round-trip once at the adapter boundary (provider cost); ensure aggregate/summary rows that don't hit the provider are `cost_source='local'`-style $0 or omitted. Verify against live rows during FR-4. |
| OQ-4 | Should `user_id` be populated for S6/S7 at all, or always NULL? | DEFERRED | Add the column; populate only where a genuine end-user triggered the call (rare in pipelines); NULL otherwise. |

---

## 15. Estimation

| Wave | Scope | Size |
|------|-------|------|
| W1 | `libs/ml-clients`: capture provider cost in DeepInfra adapters, `LlmCallUsage`/protocol fields, complete `MODEL_PRICING`, `cost.py` delegates, `is_priceable`/`LOCAL_FREE_MODELS` (FR-1, FR-5, part FR-4) | M |
| W2 | Migrations (rag-chat `0010`, nlp-pipeline `0023`, intelligence-migrations `0064`) — `cost_source` + `user_id` × 3 tables, 3 separate service lineages (FR-2, FR-3) | S |
| W3 | S6 + S7 fixes: remove hardcoded `0.0`, route through unified path, write `cost_source`/`user_id` (FR-4) | M |
| W4 | S8 internal `/internal/v1/llm-usage` + cost the tool-loop capabilities + user_id; S9 gateway screener capture→log (FR-6, part FR-3/FR-4) | M |
| W5 | Guardrails: CI priceability test + startup check + silent-zero metric/alert (FR-7); docs | S |
| W6 (follow-up) | Approximate historical backfill (FR-8) | S |

Rollout requires rebuild+redeploy of `libs/ml-clients` consumers (nlp-pipeline, knowledge-graph, rag-chat, api-gateway) plus running the three migrations (§10).
