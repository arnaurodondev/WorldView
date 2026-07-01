---
id: PLAN-0117
title: Trustworthy LLM Cost Metering — Provider-Cost Capture, Unified Pricing, Auditable Ledger
prd: PRD-0117
status: in-progress
created: 2026-07-01
updated: 2026-07-01
---

# PLAN-0117 — Trustworthy LLM Cost Metering

## Overview

**PRD**: [PRD-0117](../specs/0117-llm-cost-metering.md)
**Services affected**: `libs/ml-clients` (linchpin), S6 nlp-pipeline, S7 knowledge-graph, S8 rag-chat, S9 api-gateway, intelligence-migrations
**Total waves**: 6 (W6 = LOW-priority follow-up)

### Goal

Make the `llm_usage_log` ledger trustworthy: capture DeepInfra's provider-returned `usage.estimated_cost` as the authoritative cost, collapse the two divergent cost systems (`cost.py` + `pricing.py`) into one, stop S6 hardcoding `$0`, add auditable `cost_source` + `user_id` columns to all three ledgers, track the gateway's untracked screener call, and add guardrails so a silent-zero regression can never recur.

### The linchpin dependency (drives all sequencing)

The cost logic lives in **`libs/ml-clients`** (`pricing.py`, `cost.py`, `usage_log.py`, `adapters/*`). Every behavioural change there forces a **rebuild + redeploy of ALL consumers**: nlp-pipeline (S6), knowledge-graph (S7), rag-chat (S8), api-gateway (S9). Therefore:
- **Shared-lib primitives (W1) ship first** — additive + backward-compatible (new fields default), so consumers keep compiling on the old behaviour until they opt in.
- **Schema (W2) ships early and independently** — nullable columns, safe against old images.
- **Service wiring (W3, W4)** consumes W1 + W2.
- **Rebuild/redeploy is an explicit late step** (embedded in W3/W4 validation gates + a consolidated §Rollout), because "compose build ships stale libs/prompts" has bitten this repo repeatedly (see Regression Guardrails).

### Sub-Plans

This is a single cohesive plan (one sub-plan **A — LLM Cost Metering**) because every wave threads through the same `libs/ml-clients` carrier objects; splitting by service would fragment the shared-lib contract. Task IDs: `T-A-<wave>-<seq>`.

### Dependency graph

```
W1 (shared-lib primitives) ──┬──> W3 (S6+S7 wiring) ──┐
                             │                        ├──> W5 (guardrails + docs) ──> W6 (backfill, LOW)
W2 (migrations) ─────────────┴──> W4 (S8 + S9 wiring) ─┘
```

- W1 and W2 are independent → **parallelizable** (different files, different services).
- W3 depends on W1 (unified cost path) + W2 (cost_source/user_id columns exist).
- W4 depends on W1 + W2.
- W3 and W4 are independent of each other → parallelizable, but BOTH require the W1 lib rebuild.
- W5 depends on W1 (is_priceable) + W3 + W4 (all call sites emit cost_source).
- W6 depends on everything live (backfill re-prices only rows FR-1..FR-7 didn't fix).

### Wave summary

| Wave | Title | FRs | Size | Depends on |
|------|-------|-----|------|-----------|
| W1 | Shared-lib core: adapter cost capture + carrier fields + pricing matrix + `cost.py`→`pricing.py` delegation + `is_priceable` | FR-1, FR-5, FR-4a | M | none |
| W2 | Migrations: `cost_source` + `user_id` × 3 `llm_usage_log` tables | FR-2, FR-3 | S | none |
| W3 | S6 + S7 wiring: kill hardcoded `$0`, thread real cost + `cost_source`/`user_id` | FR-4b | M | W1, W2 |
| W4 | S8 chat-capability costing + `user_id`; S8 internal `/internal/v1/llm-usage`; S9 gateway screener capture→log | FR-6, FR-3, FR-4 | M | W1, W2 |
| W5 | Guardrails: CI/startup priceability check + silent-zero metric/alert; docs | FR-7 | S | W1, W3, W4 |
| W6 | (LOW, follow-up) approximate historical backfill | FR-8 | S | W1–W5 live |

---

## Codebase State Verification (read from code — authoritative)

| PRD Reference | Type | Service | Actual Current State (from code) | PRD Expected State | Delta |
|--------------|------|---------|----------------------------------|--------------------|-------|
| `LlmCallUsage` | dataclass | libs/ml-clients | `usage_log.py:80-109`, frozen; fields end at `error_code`; **no** `provider_cost_usd`/`cost_source` | +`provider_cost_usd: Decimal \| None = None`, +`cost_source: str = "pricematrix"` | add-with-default |
| `LlmUsageLogProtocol.log` | Protocol | libs/ml-clients | `usage_log.py:41-77`; kw-only; has `estimated_cost_usd: float = 0.0`, `**context` | +`cost_source: str \| None = None`, +`user_id: UUID \| None = None` (via defaults or `**context`) | add-with-default |
| `MODEL_PRICING` | dict | libs/ml-clients | `pricing.py:110-207`; has DeepSeek-V4-Flash, Llama-3.1-8B(+Turbo), Qwen3-235B, Qwen3-32B, r1-distill-32b, bge-large, rerank-v3, gemini-3.1-flash-lite; **no** `gpt-oss-*`, **no** `Qwen3.5-9B` | +`openai/gpt-oss-120b`, +`openai/gpt-oss-20b`, +`Qwen/Qwen3.5-9B` | new entries |
| `compute_cost(model_id, tin, tout)` | fn | libs/ml-clients | `pricing.py:210-277`; Decimal, warns on unknown | unchanged (delegate target) | none |
| `cost.py` `PRICING` / `estimate_cost` | module | libs/ml-clients | `cost.py:25-80`; float, keyed provider+model_id; independent map | `estimate_cost` delegates to `compute_cost`; `PRICING` retired | rewrite body |
| `is_priceable`, `LOCAL_FREE_MODELS` | fn/const | libs/ml-clients | **absent** | new in `pricing.py` | new |
| `deepinfra_description.py` | adapter | libs/ml-clients | reads `response.usage.prompt_tokens/completion_tokens` (l.308-310); discards `estimated_cost` | +capture `usage.estimated_cost` → `provider_cost_usd` | modify |
| `deepinfra_embedding.py` | adapter | libs/ml-clients | **does NOT parse `response.usage`** — derives tokens by word-count and computes `cost = token_count * 0.000000013` feeding `ml_api_estimated_cost_usd_total` (l.192-194) | +actually parse response body `usage.estimated_cost` (endpoint may not return it → matrix fallback `BAAI/bge-large` which is already priced) | modify (larger than the other two adapters) |
| `deepseek_extraction.py` | adapter | libs/ml-clients | `response.usage.prompt_tokens/completion_tokens` (l.532-534); feeds metric (l.638) | +capture `usage.estimated_cost` | modify |
| `llm_usage_log` (rag_db) | table | S8 | head migration `0009_add_estimated_cost_usd_to_chat_threads`; no `cost_source`/`user_id` | +2 nullable cols | migration `0010` |
| `llm_usage_log` (nlp_db) | table | **S6 nlp-pipeline (owns its OWN alembic — `env.py`: "S6 ONLY manages nlp_db")** | nlp-pipeline head `0022_add_fallback_reason_to_llm_usage_log`; created by nlp-pipeline `0008`; no `cost_source`/`user_id` | +2 nullable cols | **nlp-pipeline migration `0023`** (NOT intel-migrations) |
| `llm_usage_log` (intelligence_db) | table | S7 (DDL via intel-migrations; S7 has no own alembic) | intel-migrations head `0063_create_graph_edges`; no `cost_source`/`user_id` | +2 nullable cols | intel-migrations migration `0064` |
| S6 hardcoded `estimated_cost_usd=0.0` | call sites | S6 | `relevance_cascade.py:195`, `deep_extraction.py:303`, `article_relevance_scoring_worker.py:491`, `unresolved_resolution_worker.py:695,718,811,834` (7 sites) | replaced with computed cost + `cost_source` | rewrite |
| `SessionScopedNlpUsageLogger.log` | class | S6 | `infrastructure/nlp_db/usage_log_factory.py:35-87`; default `estimated_cost_usd=0.0` | accept + persist `cost_source`/`user_id` | modify |
| S7 usage-log write path | class | S7 | `infrastructure/intelligence_db/usage_log_factory.py`, `repositories/llm_usage_log.py` | persist `cost_source`/`user_id`; unified cost | modify |
| `chat_with_tools` / `tool_loop_iter` / `synthesis` | capabilities | S8 | `provider_chain.py:367` (`capability="chat_with_tools"`), `openrouter_adapter.py:248,324` (`call_site`), `deepinfra_adapter.py:281`; deepinfra_adapter parses usage (l.169) but tool-loop leaf cost path logs $0 | cost each leaf once via provider cost | modify |
| `CostRecorder` | Protocol/impl | S8 | port `application/ports/cost_recorder.py:28`; impl `infrastructure/llm/cost_recorder.py` (uses `compute_cost`) | extend to carry provider cost + user_id | modify |
| `POST /internal/v1/llm-usage` | endpoint | S8 | **absent**; the chosen path matches the sibling `internal_costs.py` (`APIRouter(prefix="/internal/v1")` → `GET /internal/v1/llm-costs`) — follow THAT file's prefix, not `internal.py` which uses the divergent `/v1/internal`. Also see `internal_ai_brief_flag.py`, `briefings.py` (both `/internal/v1`). | new internal route + use case | new (NEW — created in this plan) |
| S9 screener DeepInfra call | route | S9 | `routes/market.py` (`_DEEPINFRA_CHAT_URL`, `POST /v1/screener/nl-translate`); no usage capture/log | capture `usage.estimated_cost` → POST to S8 | modify |

### Name verification (BP-405 pass)

- **Existing** (verified ≥1 hit): `LlmCallUsage`, `LlmUsageLogProtocol.log`, `MODEL_PRICING`, `compute_cost`, `estimate_cost`, `PRICING`, `SessionScopedNlpUsageLogger`, `CostRecorder`, `deepinfra_description.py`, `deepinfra_embedding.py`, `deepseek_extraction.py`, `deepinfra_adapter.py`, `provider_chain.py`, `openrouter_adapter.py`, `routes/market.py`, `_DEEPINFRA_CHAT_URL`, `api/routes/internal.py`, `internal_costs.py`, `usage_log_factory.py` (S6 + S7).
- **NEW — created in this plan**: `is_priceable`, `LOCAL_FREE_MODELS`, `provider_cost_usd` field, `cost_source` field, `POST /internal/v1/llm-usage` route + its use case, migrations `0010` (rag_db) / `0023` (nlp_db) / `0064` (intelligence_db), metric `llm_usage_silent_zero_cost_total`, `MODEL_PRICING` entries `openai/gpt-oss-120b`/`openai/gpt-oss-20b`/`Qwen/Qwen3.5-9B`.

---

## Wave 1: Shared-lib core — provider-cost capture, unified calculator, matrix completion ✅

**Status**: **DONE** — 2026-07-01 · 217 ml-clients unit tests pass (16 new for W1) · ruff@0.4.0 + mypy clean · only pre-existing live-Ollama integration tests deselected.

**Goal**: Make `libs/ml-clients` capture DeepInfra's `usage.estimated_cost`, carry it on `LlmCallUsage`, complete `MODEL_PRICING`, collapse `cost.py` into `pricing.py`, and add the priceability primitives — all backward-compatible so consumers still compile on the old behaviour.
**Depends on**: none
**Estimated effort**: 60–90 min
**Architecture layer**: shared library (infrastructure adapters + value objects)

#### Tasks

#### T-A-1-01: Extend the usage carrier + protocol
**Type**: impl
**depends_on**: none
**blocks**: [T-A-1-02, T-A-1-04, T-A-3-01, T-A-4-01]
**Target files**: `libs/ml-clients/src/ml_clients/usage_log.py`
**PRD reference**: §6.5

**What to build**: Add two defaulted fields to `LlmCallUsage` and two optional kw params to `LlmUsageLogProtocol.log`, so provider cost and provenance can flow from adapter → usage-log write without breaking any existing construction.

**Entities / Components**:
- **`LlmCallUsage`** (frozen dataclass) gains:
  - `provider_cost_usd: Decimal | None = None` — verbatim `usage.estimated_cost` when provider reports it; else `None`.
  - `cost_source: str = "pricematrix"` — one of `provider` | `pricematrix` | `local`.
  - **Invariants**: `cost_source == 'provider'` ⇒ `provider_cost_usd is not None`; `cost_source == 'local'` ⇒ `estimated_cost_usd == 0` (Decimal or float `0`).
  - Import `Decimal` and `UUID` (for the protocol) at module top.
- **`LlmUsageLogProtocol.log`** gains kw-only `cost_source: str | None = None` and `user_id: UUID | None = None`, threaded to persistence. Defaults preserve every existing call site.

**Logic & Behavior**: Pure add-with-default; no behavioural change until a caller sets the new fields.

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_llmcallusage_defaults_backward_compat | Constructing `LlmCallUsage` without new fields still works; `cost_source=="pricematrix"`, `provider_cost_usd is None` | unit |
| test_llmcallusage_invariants | `provider` ⇒ provider_cost set; `local` ⇒ cost 0 (helper/validator or documented assertion) | unit |
- Minimum test count: 2

**Downstream test impact**: existing `libs/ml-clients/tests/` constructing `LlmCallUsage` positionally — verify none rely on field order after `error_code` (new fields appended after, defaulted, so keyword construction is safe; positional constructions that stop at `error_code` are unaffected).

**Acceptance criteria**:
- [x] `LlmCallUsage` has both new fields with defaults; frozen preserved.
- [x] `LlmUsageLogProtocol.log` signature has both new optional kw params.
- [x] mypy clean; all existing ml-clients tests pass unchanged.

#### T-A-1-02: Capture `usage.estimated_cost` in the three DeepInfra adapters
**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-A-3-01, T-A-4-01]
**Target files**: `libs/ml-clients/src/ml_clients/adapters/deepinfra_description.py`, `adapters/deepinfra_embedding.py`, `adapters/deepseek_extraction.py`
**PRD reference**: FR-1, §6.6

**What to build**: Where each adapter already reads `response.usage.prompt_tokens/completion_tokens`, additionally read `response.usage.estimated_cost` (float USD), convert via `Decimal(str(value))` to avoid binary-float artifacts on values like `4.1e-07`, and surface it as `provider_cost_usd` with `cost_source='provider'` on the emitted `LlmCallUsage` (and thread into the usage-log `log(...)` call + the `ml_api_estimated_cost_usd_total` metric which currently receives matrix/zero cost).

**Logic & Behavior**:
- Read cost with `getattr(response.usage, "estimated_cost", None)`.
- If present & parseable: `provider_cost_usd = Decimal(str(estimated_cost))`, `cost_source='provider'`, persist verbatim as `estimated_cost_usd`.
- If absent/malformed: fall back to `compute_cost(model_id, tokens_in, tokens_out)` → `cost_source='pricematrix'`. **Never** silently write `0.0` for a paid model.
- **Best-effort (NFR-1)**: wrap cost parse in try/except → structlog warning + continue; must never raise into the request path.

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_deepinfra_adapter_captures_estimated_cost | `usage.estimated_cost` → `provider_cost_usd`, `cost_source='provider'` | unit |
| test_deepinfra_cost_scientific_notation_to_decimal | `4.1e-07` → `Decimal("0.00000041")`, no float drift | unit |
| test_deepinfra_missing_cost_falls_back_to_matrix | absent cost → `compute_cost` path, `cost_source='pricematrix'` | unit |
| test_adapter_never_raises_on_cost_parse_error | malformed usage → warning + continue, result unaffected | unit |
- Minimum test count: 4 (parametrize across the 3 adapters where structure allows)
- Edge cases: `estimated_cost` `None`, `0`, scientific-notation, string.

**Downstream test impact**: adapter tests asserting the metric was called with matrix cost may now see provider cost — update expected values.

**Acceptance criteria**:
- [x] Each of the 3 adapters surfaces the provider cost when the response carries `estimated_cost` (extraction/embedding → `ml_api_estimated_cost_usd_total`; description → `cost_source='provider'` on the usage-log write).
- [x] Fallback + never-raise behaviour covered by tests.
- [x] `Decimal(str(x))` conversion path (`provider_cost_to_decimal`) is the only float→Decimal bridge.

#### T-A-1-03: Complete `MODEL_PRICING` + add `is_priceable`/`LOCAL_FREE_MODELS`
**Type**: impl
**depends_on**: none
**blocks**: [T-A-5-01]
**Target files**: `libs/ml-clients/src/ml_clients/pricing.py`
**PRD reference**: FR-5, §6.5, OQ-1

**What to build**: Add the genuinely-missing model entries and the priceability primitives used by the FR-7 guardrail.

**Entities / Components**:
- New `MODEL_PRICING` entries (rates = DeepInfra published 2026-07; `notes="as of 2026-07"`; confirm exact per-1M at implementation, OQ-1):
  - `openai/gpt-oss-120b`
  - `openai/gpt-oss-20b`
  - `Qwen/Qwen3.5-9B`
  - (+ any other id surfaced by the FR-7 audit query — see T-A-5-01)
- `LOCAL_FREE_MODELS: frozenset[str]` — Ollama/GLiNER model ids that legitimately cost `$0` (`cost_source='local'`). Populate from actual configured local model ids (grep `ollama_*`/`gliner_*` adapters + service settings).
- `is_priceable(model_id: str, *, provider: str) -> bool` — `True` if `model_id` in `MODEL_PRICING` (non-UNKNOWN), OR provider is a DeepInfra provider (provider-cost path), OR `model_id in LOCAL_FREE_MODELS`.

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_pricing_has_gpt_oss_and_qwen35_9b | new entries present, non-negative rates | unit |
| test_is_priceable_allowlist | true for matrix/DeepInfra/local, false otherwise | unit |
| test_local_free_models_nonempty | `LOCAL_FREE_MODELS` populated | unit |
- Minimum test count: 3

**Acceptance criteria**:
- [x] Three new priced entries with 2026-07 `notes`.
- [x] `is_priceable` + `LOCAL_FREE_MODELS` exported in `__all__` (both `pricing.__all__` and package `ml_clients.__all__`).

#### T-A-1-04: Make `cost.py` delegate to `pricing.py` (retire the second map)
**Type**: impl
**depends_on**: [T-A-1-03]
**blocks**: [T-A-3-01]
**Target files**: `libs/ml-clients/src/ml_clients/cost.py`
**PRD reference**: FR-4 (unification), §7

**What to build**: Rewrite `estimate_cost(provider, model_id, tokens_in, tokens_out)` to **delegate** to `pricing.compute_cost(model_id, tokens_in, tokens_out)` (dropping the `provider` key — a model_id uniquely determines pricing), returning `float(compute_cost(...))` for signature compatibility. Delete the independent `PRICING` map (or leave a thin deprecation shim that raises on direct access). Preserve `estimate_tokens_from_text` (used for Ollama word-count).

**Logic & Behavior**:
- Ollama/local: `compute_cost` returns `Decimal("0")` for unknown/local → `0.0`; callers stamp `cost_source='local'` at the call site (not inferred here).
- Keep `from __future__ import annotations`; add import of `compute_cost` (accept the new stdlib+ml-clients internal dependency — `pricing.py` has no heavy imports beyond `structlog`, already a dependency).

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_cost_py_delegates_to_pricing | `estimate_cost("deepinfra", m, a, b)` == `float(compute_cost(m, a, b))` | unit |
| test_cost_py_no_independent_pricing_map | `cost.PRICING` removed or shim raises | unit |
- Minimum test count: 2

**Downstream test impact**: any S6/S7 test asserting `cost.PRICING` contents will break — those tests move to assert delegation (list in Break Impact).

**Acceptance criteria**:
- [x] `cost.py` holds no independent `PRICING` map (FR-4 acceptance).
- [x] `estimate_cost` returns the same value `compute_cost` would (as float).
- [x] `pricing.py` docstring updated: "unification DONE; single source of truth".

#### Pre-read
- `libs/ml-clients/src/ml_clients/usage_log.py`, `pricing.py`, `cost.py`
- `libs/ml-clients/src/ml_clients/adapters/deepinfra_description.py` (l.300-320), `deepinfra_embedding.py` (l.180-200), `deepseek_extraction.py` (l.520-640)
- `libs/ml-clients/tests/` (adapter + pricing tests)

#### Validation Gate
- [x] `ruff check` passes on changed files
- [x] `mypy` passes on `libs/ml-clients`
- [x] Unit tests pass — minimum **11** new tests (16 delivered)
- [x] `pricing.py` docstring marks unification done
- [x] No adapter can raise from cost parsing (test-proven: `test_extraction_never_raises_on_malformed_cost`, `test_provider_cost_to_decimal_edge_cases`)

#### Architecture Compliance
- [ ] R11 — `Decimal` via `Decimal(str(x))`; `Numeric(12,6)`-safe, no float drift
- [ ] R12 — structlog warnings only (no `print`/stdlib logging) on cost-parse failure
- [ ] R13 — single calculator now lives in `libs/ml-clients`
- [ ] R25/R27 — N/A (shared lib, no use cases/UoW here)

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `libs/ml-clients/tests/test_cost*.py` (any asserting `cost.PRICING`) | map removed | rewrite to assert delegation to `compute_cost` |
| adapter tests asserting `ml_api_estimated_cost_usd_total` matrix value | metric now fed provider cost | update expected metric arg |
| any positional `LlmCallUsage(...)` construction past `error_code` | new fields appended | none if keyword; audit for positional over-construction |

#### Regression Guardrails
- **BP-337** (Qwen `reasoning_content` bleed): not touched here but confirm cost-capture reads `usage`, not `content`.
- **Compounding "silent-zero" family (RC-1/RC-2)**: the whole point — never write `0.0` for a paid model; fallback path must be matrix, not zero.
- **Compose ships stale libs** (feedback): W1 alone is inert until consumers rebuild — do NOT smoke-test cost changes against un-rebuilt containers; real verification happens in W3/W4 gates after rebuild.

---

## Wave 2: Migrations — `cost_source` + `user_id` on all three `llm_usage_log` tables ✅

**Status**: **DONE** — 2026-07-01 · 3 migrations created (rag-chat `0010`, nlp-pipeline `0023`, intel-migrations `0064`) · all verified apply→nullable→legacy-NULL→clean-rollback against a real Postgres 16 container · single head per lineage confirmed · ruff@0.4.0 clean · mypy N/A (root `mypy.ini` excludes `alembic/` + `tests/`).

> **Implementation note (ORM models)**: The plan's Break Impact anticipated updating rag-chat + nlp-pipeline `llm_usage_log` ORM models. In reality **none of the three services has a declarative ORM model for `llm_usage_log`** — all writes go through raw-SQL `text()` INSERTs (`RagChatUsageLogRepository`, `NlpUsageLogRepository`, KG `LlmUsageLogRepository`). The rag-chat DDL-alignment test only covers `threads`/`messages`. So there is nothing to update for reads/writes to *see* the columns — once the migration runs the columns simply exist. **Actually threading `cost_source`/`user_id` into the INSERT statements is W3 (T-A-3-02, S6/S7) and W4 (T-A-4-01, S8) work, not W2.**

**Goal**: Add two nullable columns to `rag_db`, `nlp_db`, and `intelligence_db` `llm_usage_log`, via the correct migration owners, forward-compatible (R11).
**Depends on**: none (parallel with W1)
**Estimated effort**: 30–45 min
**Architecture layer**: schema

> **Migration ownership (hard constraint — corrected from the assumption; verified in each `alembic/env.py`)**: three **separate** service lineages, not one.
> - **`nlp_db` DDL is owned by S6 nlp-pipeline itself** (`services/nlp-pipeline/alembic/env.py`: "S6 ONLY manages nlp_db"; table created by nlp-pipeline `0008`, last touched `0022`). `ALEMBIC_ENABLED=false` on S6 gates only its *intelligence_db* adapter connection — NOT nlp_db. → nlp_db migration lives in **nlp-pipeline's alembic** (`0023`).
> - **`intelligence_db` DDL is owned by intelligence-migrations** (`env.py` → `INTELLIGENCE_DB_URL`); S7 knowledge-graph has no own alembic dir and runs `ALEMBIC_ENABLED=false`. → intelligence_db migration is intelligence-migrations `0064`.
> - **`rag_db` DDL is owned by rag-chat**.
> Verified heads: rag-chat `0009_add_estimated_cost_usd_to_chat_threads` → `0010`; nlp-pipeline `0022_add_fallback_reason_to_llm_usage_log` → `0023`; intelligence-migrations `0063_create_graph_edges` → `0064`. (Note: the migration head-check is governed by **R32**, not R24 — R24 in this repo is "no DB sessions across external I/O".)

#### Tasks

#### T-A-2-01: rag_db migration `0010`
**Type**: schema
**depends_on**: none
**blocks**: [T-A-4-01, T-A-4-02]
**Target files**: `services/rag-chat/alembic/versions/0010_add_cost_source_and_user_id_to_llm_usage_log.py` (NEW), rag-chat `llm_usage_log` ORM model file
**PRD reference**: FR-2, FR-3, §6.4

**What to build**: Add to `rag_db.llm_usage_log`: `cost_source VARCHAR(16) NULL`, `user_id UUID NULL`. Down-migration drops both. `down_revision='0009_add_estimated_cost_usd_to_chat_threads'`. Update the SQLAlchemy model to match (nullable columns) so ORM reads/writes see them.

**Logic & Behavior**: Additive only; no server_default backfill (existing rows read NULL = pre-0117). No index now.

**Downstream test impact**: rag-chat migration-chain test (`test_migration*`), any model-shape assertion tests.

**Acceptance criteria**:
- [x] Migration applies + rolls back cleanly on a testcontainers Postgres. (verified: 0009→0010→0009)
- [x] Both columns nullable; existing rows read NULL.
- [x] ORM model updated; mypy clean. (N/A — no declarative ORM model for `llm_usage_log`; raw-SQL repo. mypy excludes `alembic/`.)

#### T-A-2-02: nlp-pipeline `0023` (nlp_db) + intelligence-migrations `0064` (intelligence_db)
**Type**: schema
**depends_on**: none
**blocks**: [T-A-3-01, T-A-3-02, T-A-3-03]
**Target files**: `services/nlp-pipeline/alembic/versions/0023_add_cost_source_and_user_id_to_llm_usage_log.py` (NEW), `services/intelligence-migrations/alembic/versions/0064_add_cost_source_user_id_intelligence_llm_usage_log.py` (NEW)
**PRD reference**: FR-2, FR-3, §6.4, OQ-2 (RESOLVED)

**What to build**: **Two migrations in two DIFFERENT service lineages** (OQ-2 resolved — they do NOT share a lineage). Each adds `cost_source VARCHAR(16) NULL` + `user_id UUID NULL` to its `llm_usage_log`:
- **nlp-pipeline `0023`** → `nlp_db.llm_usage_log`; `down_revision='0022'`. Follow the pattern in nlp-pipeline's own `0022_add_fallback_reason_to_llm_usage_log.py`.
- **intelligence-migrations `0064`** → `intelligence_db.llm_usage_log`; `down_revision='0063_create_graph_edges'`. Follow `0058_add_fallback_reason_to_llm_usage_log.py`.

**Logic & Behavior**: Each service's `alembic/env.py` binds to exactly one DB (nlp-pipeline → `NLP_PIPELINE_DATABASE_URL`; intelligence-migrations → `INTELLIGENCE_DB_URL`), so each migration targets the correct physical `llm_usage_log` automatically — do NOT put the nlp_db column change in intelligence-migrations (it would run against the wrong DB).

**Downstream test impact**: nlp-pipeline migration-chain test (new head `0023`); `services/intelligence-migrations/tests/test_migration.py`, `tests/integration/test_migration_apply.py` (new head `0064`); `tests/integration/test_r24_compliance.py` (asserts S6/S7 don't own *intelligence_db* DDL — safe: nlp_db change is nlp-pipeline's own, intelligence_db change is intel-migrations').

**Acceptance criteria**:
- [x] Both migrations apply + roll back on testcontainers Postgres. (verified: 0022→0023→0022; 0063→0064→0063)
- [x] nlp_db columns land via nlp-pipeline `0023`; intelligence_db columns via intel-migrations `0064`.
- [x] Each chain linear (nlp-pipeline 0022→0023; intel-migrations 0063→0064), no branch. (head-detection: single head per lineage)

#### T-A-2-03: Integration tests for all three migrations
**Type**: test
**depends_on**: [T-A-2-01, T-A-2-02]
**blocks**: none
**Target files**: `services/rag-chat/tests/integration/`, `services/intelligence-migrations/tests/integration/`
**PRD reference**: §11 Integration Tests

**Tests to write**:
| Test | Infra | Verifies |
|------|-------|----------|
| test_rag_migration_0010_adds_columns | Postgres | `cost_source`,`user_id` exist, nullable; pre-existing row reads NULL |
| test_nlp_0023_and_intel_0064_add_columns | Postgres | same on nlp_db + intelligence_db tables |
- Minimum test count: 2 (may be 3 if split per DB)

**Acceptance criteria**:
- [x] Both integration tests pass against testcontainers Postgres. (nlp `0023` test PASSED for real in-venv; rag `0010` + intel `0064` tests collect and skip-gracefully where testcontainers/live-DB absent, matching existing suite convention. All three migrations independently proven apply+rollback against a real PG16 container.)

#### Pre-read
- `services/rag-chat/alembic/versions/0009_add_estimated_cost_usd_to_chat_threads.py`
- `services/nlp-pipeline/alembic/versions/0022_add_fallback_reason_to_llm_usage_log.py`, `0008_create_llm_usage_log.py`, `services/nlp-pipeline/alembic/env.py` (confirms "S6 ONLY manages nlp_db")
- `services/intelligence-migrations/alembic/versions/0058_add_fallback_reason_to_llm_usage_log.py`, `0063_create_graph_edges.py`, `alembic/env.py`
- `services/intelligence-migrations/tests/integration/test_migration_apply.py`

#### Validation Gate
- [x] `ruff` + `mypy` on changed files (ruff@0.4.0 clean; mypy excludes `alembic/`+`tests/` per root `mypy.ini`)
- [x] 3 migrations apply + down cleanly (testcontainers) — verified manually against PG16 container
- [x] Minimum **2** new integration tests pass (3 written; nlp `0023` PASSED in-venv)
- [x] Migration chains linear per service (`/migrate-db` conventions)

#### Architecture Compliance
- [x] R11 — nullable, no server-default backfill, no rename/removal, text not enum (`VARCHAR(16)`, not enum)
- [x] Migration ownership — nlp_db DDL via **nlp-pipeline** (`ALEMBIC_URL`→nlp_db); intelligence_db DDL via **intelligence-migrations** (`INTELLIGENCE_DB_URL`); rag_db via **rag-chat** (each owns its own lineage; verified in `env.py`)
- [x] R32 — filenames from verified on-disk HEAD revision IDs (`0009`→`0010`; `0022`→`0023`; `0063`→`0064`; note: on-disk `revision` ids are bare numbers, not the long slugs)
- [x] R6 — `user_id` is UUID (no id minted here)

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| rag-chat migration-chain test | new head `0010` | update expected head revision |
| nlp-pipeline migration-chain test | new head `0023` | update expected head revision |
| intelligence-migrations `test_migration.py` | new head `0064` | update expected head + count |
| rag-chat + nlp-pipeline `llm_usage_log` ORM models | columns added | add `cost_source`/`user_id` nullable fields to both |

#### Regression Guardrails
- **BP-007 / BP-019 / BP-032** (DB/migration patterns): verify down-migration, no data loss, forward-compat.
- **Ownership collision**: the nlp_db columns go via **nlp-pipeline's OWN alembic** (`0023`) — S6 owns nlp_db DDL. The intelligence_db columns go via **intelligence-migrations** (`0064`) — S7 runs `ALEMBIC_ENABLED=false` for intelligence_db and must NOT own that DDL. Do not swap these.

---

## Wave 3: S6 + S7 wiring — kill hardcoded `$0`, thread real cost + provenance

**Goal**: Remove every hardcoded `estimated_cost_usd=0.0` at S6 paid call sites, route S6 and S7 usage-log writes through the unified cost path (provider cost → matrix → local), and persist `cost_source` (+ best-effort `user_id`).
**Depends on**: W1 (unified cost path + carrier), W2 (`cost_source`/`user_id` columns on nlp_db + intelligence_db)
**Estimated effort**: 60–90 min
**Architecture layer**: application + infrastructure (S6, S7)

#### Tasks

#### T-A-3-01: S6 — remove hardcoded `0.0` at the 7 call sites, thread computed cost + `cost_source`
**Type**: impl
**depends_on**: [T-A-1-02, T-A-1-04, T-A-2-02]
**blocks**: [T-A-5-02]
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/application/blocks/relevance_cascade.py:195`, `application/blocks/deep_extraction.py:303`, `infrastructure/workers/article_relevance_scoring_worker.py:491`, `infrastructure/workers/unresolved_resolution_worker.py:695,718,811,834`
**PRD reference**: FR-4, RC-1, §6.1

**What to build**: At each site, replace the literal `estimated_cost_usd=0.0` with the real cost resolved by the priority rule: use the adapter-returned `LlmCallUsage.provider_cost_usd` if present (`cost_source='provider'`); else `compute_cost(model_id, tokens_in, tokens_out)` (`cost_source='pricematrix'`); Ollama/local sites pass `0.0` **with `cost_source='local'`** (legitimate — keep, but tag provenance). Pass `cost_source` (and `user_id` where a genuine end-user exists — rare in S6 pipelines, NULL otherwise, OQ-4) to the usage logger.

**Port interfaces**: writes go through `SessionScopedNlpUsageLogger` (implements `LlmUsageLogProtocol`) — no new port. Confirm each block/worker already holds a usage-logger handle; if a site only has token counts (no `LlmCallUsage`), compute via `compute_cost` at the site.

**Read/Write classification**: Write (usage-log insert) — existing write path, no UoW change.

**Logic & Behavior**:
- The two `unresolved_resolution_worker` local/Ollama sites (verify which of 695/718/811/834 are Ollama) keep `0.0` but stamp `cost_source='local'`.
- Paid DeepInfra sites (extraction, relevance scoring) get real cost.
- **Never** leave a bare `0.0` on a paid model.

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_s6_call_sites_no_hardcoded_zero | each fixed site passes computed cost + `cost_source`, not literal `0.0` | unit |
| test_s6_local_site_is_local | Ollama site → `0.0` + `cost_source='local'` | unit |
- Minimum test count: 2 (+ per-site as feasible)

**Acceptance criteria**:
- [ ] `grep -rE "estimated_cost_usd\s*=\s*0\.0" services/nlp-pipeline/src` returns only legitimate `cost_source='local'` sites.
- [ ] Paid sites thread `provider_cost_usd`/`compute_cost` value.

#### T-A-3-02: S6 — `SessionScopedNlpUsageLogger` persists `cost_source`/`user_id`
**Type**: impl
**depends_on**: [T-A-2-02, T-A-1-01]
**blocks**: [T-A-3-01]
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/usage_log_factory.py`
**PRD reference**: FR-2, FR-3, FR-4

**What to build**: Extend `SessionScopedNlpUsageLogger.log(...)` to accept `cost_source: str | None = None` + `user_id: UUID | None = None` and write them into the `nlp_db.llm_usage_log` INSERT. Drop the implicit `estimated_cost_usd=0.0` default reliance — callers now always supply a resolved cost + source.

**Logic & Behavior**: Best-effort (NFR-1) — swallow + structlog warn on failure. `cost_source` defaults to NULL only if a legacy caller omits it (transitional).

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_nlp_logger_persists_cost_source_user_id | INSERT includes both columns | unit |
- Minimum test count: 1

**Acceptance criteria**:
- [ ] Logger writes `cost_source` + `user_id`; mypy clean.

#### T-A-3-03: S7 — route enrichment writes through unified path, persist `cost_source`
**Type**: impl
**depends_on**: [T-A-1-02, T-A-1-04, T-A-2-02]
**blocks**: [T-A-5-02]
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/usage_log_factory.py`, `infrastructure/intelligence_db/repositories/llm_usage_log.py`, `infrastructure/llm/fallback_chain.py` (cost resolution site)
**PRD reference**: FR-4, §6.1

**What to build**: S7 is mostly correct ($23.34) — ensure its DeepInfra writes now prefer `provider_cost_usd` (FR-1) over matrix, stamp `cost_source` (`provider` for DeepInfra, `pricematrix` for Gemini, `local` for Ollama), and persist `cost_source`/`user_id` in the `intelligence_db.llm_usage_log` write path. Ollama writes stay `$0`/`local` (unchanged, legitimate).

**Read/Write classification**: Write — existing path.

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_s7_deepinfra_uses_provider_cost | DeepInfra enrichment → `cost_source='provider'` when provider cost present | unit |
| test_s7_ollama_is_local | Ollama → `0` + `cost_source='local'` | unit |
- Minimum test count: 2

**Acceptance criteria**:
- [ ] S7 write path stamps `cost_source`; DeepInfra prefers provider cost; Ollama stays `local`.

#### T-A-3-04: S6/S7 integration test — real cost written end-to-end
**Type**: test
**depends_on**: [T-A-3-01, T-A-3-02, T-A-3-03]
**blocks**: none
**Target files**: `services/nlp-pipeline/tests/integration/`, `services/knowledge-graph/tests/integration/`
**PRD reference**: §11 Integration Tests

**Tests to write**:
| Test | Infra | Verifies |
|------|-------|----------|
| test_s6_extraction_writes_real_cost | Postgres | simulated DeepInfra extraction → row cost>0, `cost_source='provider'` |
| test_s7_enrichment_writes_cost_source | Postgres | enrichment row carries `cost_source` |
- Minimum test count: 2

**Acceptance criteria**:
- [ ] Both integration tests pass on testcontainers Postgres.

#### Pre-read
- The 4 S6 call-site files (lines noted above) + `usage_log_factory.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/usage_log_factory.py`, `repositories/llm_usage_log.py`, `infrastructure/llm/fallback_chain.py`
- `libs/ml-clients/src/ml_clients/pricing.py` (`compute_cost`), `usage_log.py`

#### Validation Gate
- [ ] `ruff` + `mypy` on S6 + S7 changed packages
- [ ] Unit tests pass — minimum **5** new
- [ ] Integration tests (testcontainers) pass — minimum **2**
- [ ] `grep` for hardcoded `estimated_cost_usd=0.0` at paid S6 sites returns none
- [ ] **Rebuild + redeploy** nlp-pipeline (S6) + knowledge-graph (S7) with new `libs/ml-clients`; **verify the new lib code is actually in the container** (direct `docker build -f services/<svc>/Dockerfile .` + retag per the "compose ships stale libs" caution) before smoke
- [ ] **Live smoke**: trigger one paid extraction (S6) + one enrichment (S7); confirm a `llm_usage_log` row with `estimated_cost_usd>0` + `cost_source='provider'`; confirm one Ollama call writes `cost_source='local'`, `0`

#### Architecture Compliance
- [ ] R11 — Decimal cost; nullable cols
- [ ] R12 — structlog on best-effort failure
- [ ] R13 — cost via `libs/ml-clients` only (no local price math)
- [ ] Migration ownership — S6 nlp_db columns came from **nlp-pipeline's own W2 migration `0023`**; S7 intelligence_db columns came from **intel-migrations `0064`** (S7 owns no DDL)
- [ ] R25/R27 — writes through existing logger; no new use case / no read-replica concern

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| S6 unit tests asserting `estimated_cost_usd==0.0` on extraction/relevance | now non-zero | update expected cost + assert `cost_source` |
| S6/S7 tests referencing old `cost.PRICING` | map delegated | update to `compute_cost` |
| S7 usage-log write tests | signature gained `cost_source`/`user_id` | pass new kwargs |

#### Regression Guardrails
- **RC-1 silent-zero family**: the core fix — every paid site now carries real cost + provenance.
- **Prompt input vs lookup mismatch (feedback)**: ensure `model_id` passed to `compute_cost` is the exact provider `model` string (casing/whitespace = silent zero — see `pricing.py` naming convention note).
- **Compose ships stale libs (feedback)**: verify container has new `pricing.py`/adapter BEFORE smoke; a `docker restart` alone won't pick up rebuilt libs.
- **BP-590 / R42 parallel sessions**: S6 and S7 sub-tasks touch different services — if run in parallel worktrees, one worktree per agent.

---

## Wave 4: S8 chat costing + internal usage endpoint; S9 gateway screener capture

**Goal**: Cost the high-volume S8 chat capabilities (`chat_with_tools`/`tool_loop_iter`/`synthesis`) exactly once via provider cost, add `user_id`, add the FR-6 internal ingest endpoint, and wire the S9 gateway screener call to capture + log its DeepInfra cost.
**Depends on**: W1 (provider-cost carrier + `CostRecorder` extension surface), W2 (rag_db columns)
**Estimated effort**: 75–100 min
**Architecture layer**: application + API (S8), API (S9)

#### Tasks

#### T-A-4-01: S8 — cost `chat_with_tools`/`tool_loop_iter`/`synthesis` leaf calls once; add `user_id`
**Type**: impl
**depends_on**: [T-A-1-02, T-A-2-01]
**blocks**: [T-A-5-02]
**Target files**: `services/rag-chat/src/rag_chat/infrastructure/llm/deepinfra_adapter.py`, `infrastructure/llm/provider_chain.py:367`, `infrastructure/llm/openrouter_adapter.py:248,324`, `infrastructure/llm/cost_recorder.py`, `application/ports/cost_recorder.py`
**PRD reference**: FR-4, FR-3, OQ-3, §6.1

**What to build**: The DeepInfra chat adapter already parses `usage` (`deepinfra_adapter.py:169`) — extend it to read `usage.estimated_cost`, and record the tool-loop leaf calls (currently logging `$0`) through `CostRecorder` with `cost_source='provider'`. **OQ-3 (verify against live rows)**: cost each real DeepInfra round-trip exactly once at the adapter boundary; ensure aggregate/summary rows that DON'T hit the provider are `$0`/omitted so there's no double count. Thread `user_id` (from the authenticated chat context) into the `CostRecorder`/`log` write.

**Port interfaces**: `CostRecorder` (Protocol, `application/ports/cost_recorder.py`) — extend to carry `provider_cost_usd`/`cost_source`/`user_id`; impl `infrastructure/llm/cost_recorder.py`.

**Read/Write classification**: Write (usage-log insert) — existing path.

**Logic & Behavior**:
- Provider cost primary; matrix fallback (Gemini/absent); local for Ollama.
- **Double-count guard (OQ-3)**: inspect live `rag_db.llm_usage_log` for `chat_with_tools`/`tool_loop_iter`/`synthesis` rows to confirm whether they're leaf or aggregate BEFORE choosing the record point; document the finding in the wave commit.

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_chat_leaf_cost_recorded_once | tool-loop leaf → one row, `cost_source='provider'`, cost>0 | unit |
| test_chat_user_id_threaded | authenticated chat → `user_id` set on row | unit |
| test_chat_no_double_count | aggregate/summary row is $0/omitted | unit |
- Minimum test count: 3

**Acceptance criteria**:
- [ ] `chat_with_tools`/`tool_loop_iter`/`synthesis` leaf calls record real cost once.
- [ ] `user_id` persisted where available; NULL for system/background.
- [ ] OQ-3 finding documented.

#### T-A-4-02: S8 — internal `POST /internal/v1/llm-usage` ingest endpoint + use case
**Type**: impl
**depends_on**: [T-A-2-01]
**blocks**: [T-A-4-03]
**Target files**: `services/rag-chat/src/rag_chat/api/routes/internal.py` (or new `internal_llm_usage.py`), new use case in `application/use_cases/`, request schema
**PRD reference**: FR-6, §6.2 (endpoint contract)

**What to build**: NEW internal-only endpoint `POST /internal/v1/llm-usage` (NEW — created in this plan) persisting one usage record into `rag_db.llm_usage_log`. Follow the existing `api/routes/internal.py` pattern (prefix `/v1/internal`, internal-JWT `AuthContextDep`). Request body per PRD §6.2 table (model_id, provider, capability, tokens_in/out, estimated_cost_usd Decimal, cost_source, latency_ms, success, error_code, tenant_id, user_id). Response `200 {"recorded": true}` (never 204 — BP-064). On persistence failure return `200 {"recorded": false}` (best-effort, NFR-1) so the gateway never sees an error. 401 for non-internal, 422 validation.

**Port interfaces**: new `RecordLlmUsageUseCase` depends on the existing `llm_usage_log` write repository (ABC port); no direct infra import in the router (R25 — router calls the use case).

**Read/Write classification**: Write → `UnitOfWork` + `UoWDep` (R27).

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_internal_llm_usage_persists | valid POST → `rag_db` row written, `{"recorded": true}` | integration |
| test_internal_llm_usage_best_effort | persistence error → 200 `{"recorded": false}`, no raise | integration |
| test_internal_llm_usage_rejects_non_internal | no/invalid internal JWT → 401 | unit |
| test_internal_llm_usage_validates_body | bad body → 422 | unit |
- Minimum test count: 4

**Acceptance criteria**:
- [ ] Endpoint persists via use case (R25 respected); internal-auth enforced.
- [ ] Best-effort 200/`recorded:false` on failure.

#### T-A-4-03: S9 — capture screener `usage.estimated_cost`, POST to S8 (best-effort)
**Type**: impl
**depends_on**: [T-A-4-02]
**blocks**: [T-A-5-02]
**Target files**: `services/api-gateway/src/api_gateway/routes/market.py` (`_DEEPINFRA_CHAT_URL`, `POST /v1/screener/nl-translate`)
**PRD reference**: FR-6, RC-4, §6.6

**What to build**: In the gateway's direct DeepInfra screener call, parse `usage.estimated_cost` from the response and fire a **best-effort** `POST /internal/v1/llm-usage` to S8 (`capability='screener_nl_translate'`, `cost_source='provider'`, tenant/user from the gateway auth context). On any failure: structlog warning + continue — the screener request must NEVER fail because usage-logging failed (NFR-1). No public API shape change to `/v1/screener/nl-translate`.

**Read/Write classification**: outbound REST call (S9→S8 internal) — R14/R9 compliant (internal service call, not cross-service DB).

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_gateway_screener_logs_usage | NL-translate → one usage POST, `cost_source='provider'` | integration (S8 stub) |
| test_gateway_screener_logging_best_effort | S8 endpoint down → warning, screener still 200 | unit |
- Minimum test count: 2

**Acceptance criteria**:
- [ ] Screener call captures provider cost + POSTs to S8; failure never surfaces to user.

#### Pre-read
- `services/rag-chat/src/rag_chat/infrastructure/llm/deepinfra_adapter.py` (l.130-200), `provider_chain.py` (l.319-380), `openrouter_adapter.py` (l.186-330), `infrastructure/llm/cost_recorder.py`, `application/ports/cost_recorder.py`
- `services/rag-chat/src/rag_chat/api/routes/internal.py`, `internal_costs.py`
- `services/api-gateway/src/api_gateway/routes/market.py`, `schemas/screener.py`, `config.py`

#### Validation Gate
- [ ] `ruff` + `mypy` on S8 + S9 changed packages
- [ ] Unit tests pass — minimum **7** new
- [ ] Integration tests (testcontainers + S8 app / S8 stub) pass — minimum **3**
- [ ] OQ-3 double-count finding recorded in commit message
- [ ] **Rebuild + redeploy** rag-chat (S8) + api-gateway (S9); verify new lib/route in container before smoke
- [ ] **Live smoke**: send one chat turn → confirm `chat_with_tools` row with cost>0 + `cost_source='provider'`; run one `/v1/screener/nl-translate` → confirm a `rag_db.llm_usage_log` row `capability='screener_nl_translate'`, `cost_source='provider'`

#### Architecture Compliance
- [ ] R9 — gateway writes via S8 internal REST, not cross-service DB
- [ ] R11 — Decimal cost; nullable `user_id`
- [ ] R14 — no frontend change; FR-6 is S9→S8 internal
- [ ] R25 — internal endpoint router calls a use case, not infra
- [ ] R27 — write use case uses `UnitOfWork`/`UoWDep`
- [ ] BP-064 — 200+dict, never 204

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| S8 `CostRecorder` port + impl tests | signature gains provider_cost/cost_source/user_id | update stubs + assertions |
| S8 chat pipeline tests asserting `$0` on tool-loop | now costed | update expected cost |
| S9 screener route tests | new best-effort POST side-effect | assert/mocked POST; response unchanged |
| S8 route registry test | new `/internal/v1/llm-usage` route | add to expected route list if enumerated |

#### Regression Guardrails
- **BP-064** — internal endpoint returns 200+dict, never 204.
- **RC-3 silent-zero** — chat leaf calls must not log $0 for paid models.
- **OQ-3 double-count** — verify leaf-vs-aggregate on LIVE rows before choosing record point (audit-returned-value-persistence feedback: don't infer from code alone).
- **NFR-1 best-effort** — neither the internal endpoint nor the gateway caller may raise into the user path.
- **Compose ships stale libs/prompts** — verify container has new adapter/route before smoke.

---

## Wave 5: Guardrails — CI/startup priceability check + silent-zero metric/alert; docs

**Goal**: Add the FR-7 guardrails that would have caught the entire RC-1/RC-2/RC-3 failure, and land the mandatory documentation updates.
**Depends on**: W1 (`is_priceable`/`LOCAL_FREE_MODELS`), W3 + W4 (all call sites now emit `cost_source`)
**Estimated effort**: 45–60 min
**Architecture layer**: cross-cutting (CI/arch tests, observability, docs)

#### Tasks

#### T-A-5-01: FR-7a — priceability CI test + startup log
**Type**: test
**depends_on**: [T-A-1-03]
**blocks**: none
**Target files**: `libs/ml-clients/tests/` (arch/priceability test), each consumer service startup (S6/S7/S8/S9 bootstrap logging), optional `services/intelligence-migrations/tests/` arch test
**PRD reference**: FR-7a, US-B2

**What to build**:
- **CI test** `test_all_configured_models_priceable`: collect every `model_id` the platform can emit (from service settings / model registry constants) and assert `is_priceable(model_id, provider=...)` is True, else fail. Include the FR-7 audit query (distinct `llm_usage_log.model_id`) documented for operators to re-run and surface new ids (feeds FR-5).
- **Startup log**: each consumer logs a structured warning on boot listing any configured model with no pricing path.

**Tests to write**:
| Test | Verifies |
|------|----------|
| test_all_configured_models_priceable | every configured model id has a pricing path (CI gate) |
| test_is_priceable_flags_unknown | an unpriced non-local, non-DeepInfra id → False |
- Minimum test count: 2

**Acceptance criteria**:
- [ ] CI fails if a configured model has no pricing path.
- [ ] Each consumer logs unpriced configured models at startup.

#### T-A-5-02: FR-7b — silent-zero metric + alert
**Type**: impl
**depends_on**: [T-A-3-01, T-A-3-03, T-A-4-01, T-A-4-03]
**blocks**: none
**Target files**: shared metric definition (each service's metrics module, e.g. `services/*/application/metrics/`), the usage-log write path (increment point), alert rules (`infra/` observability config)
**PRD reference**: FR-7b, NFR-4, §13

**What to build**: A counter `llm_usage_silent_zero_cost_total{service,model_id}` incremented whenever a row is written with `tokens_in + tokens_out > 0` AND `estimated_cost_usd == 0` AND `cost_source != 'local'` (paid provider). Wire an alert on the counter. This is the regression tripwire for RC-1/RC-2/RC-3.

**Logic & Behavior**: increment at the single usage-log write choke-point in each service (S6 `SessionScopedNlpUsageLogger`, S7 logger, S8 `CostRecorder`, S8 internal endpoint). Best-effort — metric emission never raises.

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_silent_zero_cost_metric_increments | tokens>0 & cost 0 & non-local → counter +1 | unit |
| test_silent_zero_not_incremented_for_local | local $0 row → counter unchanged | unit |
- Minimum test count: 2

**Acceptance criteria**:
- [ ] Counter increments only on paid silent-zero; alert rule present.

#### T-A-5-03: Documentation updates (mandatory, §12)
**Type**: docs
**depends_on**: [T-A-5-01, T-A-5-02]
**blocks**: none
**Target files**: `docs/services/{nlp-pipeline,knowledge-graph,rag-chat,api-gateway}.md`; `services/{nlp-pipeline,knowledge-graph,rag-chat,api-gateway}/.claude-context.md`; `libs/ml-clients` docs + `pricing.py` docstring; `docs/BUG_PATTERNS.md`; `.claude/review/checklists/REVIEW_CHECKLIST.md`
**PRD reference**: §12

**What to build**:
- Service docs: cost-metering sections (provider-cost priority, `cost_source`, `user_id`, new internal endpoint for S8/S9).
- `.claude-context.md` pitfall: "never hardcode `estimated_cost_usd=0.0` for paid models; use the unified cost path; `pricing.py` is the single calculator."
- `pricing.py` docstring: unification DONE; `cost.py` retired/delegating; DeepInfra provider-cost-first rule; `cost_source` semantics.
- `docs/BUG_PATTERNS.md`: new "silent-zero LLM cost / two divergent price maps" pattern (RC-1/RC-2) with FR-7 guardrail as prevention (assign next BP id).
- `REVIEW_CHECKLIST.md`: "any new LLM call site records real cost via the unified path + `cost_source`".

**Acceptance criteria**:
- [ ] All §12 docs updated; BP + checklist entries added.

#### Pre-read
- `libs/ml-clients/src/ml_clients/pricing.py` (`is_priceable`)
- one metrics module (e.g. `services/rag-chat/src/rag_chat/application/metrics/prometheus.py`) + existing alert-rule location under `infra/`
- `docs/BUG_PATTERNS.md`, `.claude/review/checklists/REVIEW_CHECKLIST.md`

#### Validation Gate
- [ ] `ruff` + `mypy` on changed files
- [ ] Unit/arch tests pass — minimum **4** new
- [ ] CI priceability gate wired into the pipeline
- [ ] Docs updated (all §12 targets)
- [ ] Alert rule validates (e.g. `make grafana-validate` / promtool if applicable)

#### Architecture Compliance
- [ ] R12 — structlog for startup warnings
- [ ] R13 — `is_priceable` from shared lib
- [ ] R15 — docs updated for the schema/endpoint/metric changes

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| any test enumerating registered metrics | new counter | add `llm_usage_silent_zero_cost_total` to expected set |
| service settings/model-registry tests | priceability test reads them | ensure model ids exposed to the test |

#### Regression Guardrails
- **Audit-returned-value-persistence (feedback)** — the metric is only useful if incremented at the real write choke-point; verify call sites, not just definition.
- **Ruff version pinning / pre-commit sync (feedback)** — CI ruff must match pre-commit exactly.
- **RC-1/RC-2/RC-3** — this wave is the permanent tripwire; the CI gate must actually fail on an unpriced model (prove with a negative test).

---

## Wave 6 (LOW, follow-up): Approximate historical backfill

**Goal**: Re-price historical `estimated_cost_usd = 0` rows by `tokens × current pricing.py rate`, stamped `cost_source='pricematrix'` and clearly marked approximate. Ships last, only after FR-1..FR-7 are live.
**Depends on**: W1–W5 live
**Estimated effort**: 30–45 min
**Architecture layer**: data (one-off script / data-only migration)

#### Tasks

#### T-A-6-01: Backfill script (approximate re-pricing)
**Type**: impl
**depends_on**: [T-A-5-02]
**blocks**: [T-A-6-02]
**Target files**: `scripts/` one-off backfill (per DB: rag_db, nlp_db, intelligence_db), or a data-only alembic revision owned by the correct service
**PRD reference**: FR-8, §2.3, US-C2

**What to build**: For each `llm_usage_log` row with `estimated_cost_usd = 0` AND `tokens_in + tokens_out > 0` AND `cost_source IS NULL` (i.e. pre-0117, not a legitimate `local` $0), compute `compute_cost(model_id, tokens_in, tokens_out)` and write it with `cost_source='pricematrix'`. **Do NOT touch** rows already carrying a real `provider` cost or `cost_source='local'`. Document as approximate (current prices applied to old traffic; DeepInfra prices fell over time → upper-ish estimate) in the script header and in `docs/services/*` cost sections.

**Logic & Behavior**: idempotent (re-run only touches `cost_source IS NULL` + zero-cost rows); batch in chunks; dry-run flag reporting row counts + total re-priced before applying.

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_backfill_marks_pricematrix_and_skips_provider_rows | re-prices only `0.0`/NULL-source rows, stamps `pricematrix`, leaves provider/local rows untouched | integration |
| test_backfill_idempotent | second run re-touches nothing | integration |
- Minimum test count: 2

**Acceptance criteria**:
- [ ] Only pre-0117 zero-cost rows re-priced; provider/local rows untouched; idempotent.

#### T-A-6-02: Run backfill + document
**Type**: docs/ops
**depends_on**: [T-A-6-01]
**blocks**: none
**Target files**: `docs/services/*` cost sections; run log
**PRD reference**: FR-8, §12

**What to build**: Execute the backfill (dry-run → apply) per DB; record before/after totals; add the "approximate" note to service cost docs.

**Acceptance criteria**:
- [ ] Backfill applied; totals recorded; docs note approximation.

#### Validation Gate
- [ ] `ruff` + `mypy`; **2** integration tests pass
- [ ] Dry-run reviewed before apply; idempotency verified
- [ ] Docs mark backfilled rows approximate

#### Architecture Compliance
- [ ] R24 — if a data-only migration is used for nlp_db/intelligence_db it must live in intelligence-migrations; rag_db in rag-chat; scripts may connect per-DB but respect ownership boundaries
- [ ] R11 — no schema change (data only)

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| dashboards reading `cost_source` provenance | matrix-only rows now appear | expected — document the provenance split |

#### Regression Guardrails
- **RC-1** — never overwrite a real `provider` cost with an approximate one.

---

## Cross-Cutting Concerns

- **Contract changes**: one new internal endpoint (`POST /internal/v1/llm-usage`, S8) — internal-only, no public/frontend shape change, no Avro/Kafka change (§6.3).
- **Migrations**: rag-chat `0010` (rag_db); nlp-pipeline `0023` (nlp_db); intelligence-migrations `0064` (intelligence_db) — three separate service lineages. Ordered before service wiring; nullable → safe against old images.
- **Event flow**: none. Usage logging is synchronous best-effort DB write; FR-6 is REST, not an event.
- **Config**: no new secrets (DeepInfra keys already via pydantic-settings). Possible new env toggle for the silent-zero alert threshold — optional.
- **Observability**: new metric `llm_usage_silent_zero_cost_total`; existing `ml_api_estimated_cost_usd_total` now fed real provider costs.
- **Docs**: §12 targets (W5-T-03).

## Risk Assessment

- **Critical path**: `W1 → (W3 ∥ W4) → W5`. W1 is the linchpin — every service change depends on the shared-lib carrier + unified calculator. W2 is off the critical path (parallel with W1) but must land before W3/W4 wiring writes the new columns.
- **Highest risk**: **W4** (S8 double-count — OQ-3). Costing `chat_with_tools`/`tool_loop_iter`/`synthesis` risks double-counting if a capability is an aggregate over leaf calls. Mitigation: inspect LIVE `rag_db.llm_usage_log` rows before choosing the record point; cost each DeepInfra round-trip once at the adapter boundary.
- **Second risk**: **rebuild/redeploy of 4 consumers** carrying the same lib. "Compose ships stale libs/prompts" has repeatedly landed `.py` changes without the lib actually in the container — every W3/W4 gate mandates verifying the new code is in the container before smoke, and prefers direct `docker build -f services/<svc>/Dockerfile .` + retag.
- **Rollback**: additive nullable columns + defaulted lib fields → redeploy prior images; new rows harmlessly write `cost_source=NULL`. Down-migrations exist but aren't needed for rollback.
- **Testing gaps**: live-only verification for double-count (OQ-3) and provider-cost values (can't fully unit-test DeepInfra's `estimated_cost` — use recorded fixtures + one live smoke per service).

## Final QA Gate (before marking PLAN-0117 complete)

- [ ] All 6 waves' validation gates green (W6 optional/LOW).
- [ ] Live smoke per service: S6 extraction, S7 enrichment, S8 chat turn, S9 screener each produce a `llm_usage_log` row with `estimated_cost_usd>0` + `cost_source='provider'`; one Ollama/local call writes `cost_source='local'`, `0`.
- [ ] `grep -rE "estimated_cost_usd\s*=\s*0\.0" services/` returns only legitimate `cost_source='local'` sites.
- [ ] FR-7 CI priceability gate passes and demonstrably fails on an injected unpriced model.
- [ ] `llm_usage_silent_zero_cost_total` stays at 0 during smoke across all four services.
- [ ] All §12 docs + BP + checklist updated.
- [ ] Consider a `/qa` multi-agent pass given the 4-service blast radius.

## Compounding check

New bug pattern to add in W5-T-03: **"silent-zero LLM cost / two divergent price maps"** (RC-1 audit-returned-value-not-persisted + RC-2 two-lists-that-must-agree) with the FR-7 guardrail as prevention. Review-checklist entry: "any new LLM call site records real cost via the unified path + `cost_source`." No RULES.md change needed (existing R11/R13/R24 cover the design).
