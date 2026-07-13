---
id: PRD-0118
title: "AI-Endpoint Rate Limiting & Per-User/Per-Tenant LLM Usage Quotas"
status: draft
created: 2026-06-30
updated: 2026-06-30
author: "human + claude"
services: [S9 (api-gateway), S8 (rag-chat), libs/messaging]
priority: P0
estimated-waves: 5
depends-on: ["PRD-0117"]
enables: []
---

# PRD-0118: AI-Endpoint Rate Limiting & Per-User/Per-Tenant LLM Usage Quotas

## 1. Overview & Motivation

### 1.1 Background

The platform is weeks from production. Every user-facing AI operation — chat (buffered + SSE),
entity-context chat, agentic proposal confirmation, morning/instrument briefings, natural-language
screener translation, and entity-narrative generation — routes through DeepInfra (paid, per-token).
None of these paths has a cost ceiling, a per-user request cap, a per-tenant aggregate ceiling, or a
concurrent-stream limit. They fall into the gateway's **general authenticated bucket** (`rl:v1:user:{user_id}`,
default **2000 requests / 60 s** — `API_GATEWAY_RATE_LIMIT_REQUESTS`), which counts *requests* with no notion
of tokens or dollars. A single authenticated user can therefore fire ~2000 chat requests/min, each an
arbitrarily large streamed LLM generation, at real per-token cost, and hold many concurrent SSE streams
(each pinning an upstream httpx connection + an LLM slot for up to 120 s) with **zero** concurrency accounting.

### 1.2 Problem Statement

There is no spend-shaped or token-shaped protection anywhere on the AI surface. Concretely (verified in
code this session):

| Gap | Evidence |
|-----|----------|
| **AI requests are not carved out.** Chat/briefings/screener/narrative all land in the general 2000/60 s per-user request bucket. | `services/api-gateway/src/api_gateway/middleware.py` `RateLimitMiddleware` (l.443) matches only export / financial-mutation / public-feedback tiers; everything else → `rl:v1:user:{user_id}`. |
| **No token or cost ceiling anywhere.** All cost accounting is post-hoc (a `llm_usage_log` ledger + Prometheus). Nothing *reads* a running total to gate a request. | `services/rag-chat/.../infrastructure/llm/cost_recorder.py` `PrometheusAndDbCostRecorder.record()` writes cost after the call; it never blocks. |
| **No concurrent-stream cap.** SSE requests are counted once by INCR at request start, then the stream holds a slot for minutes with no open/close accounting. | Gateway `routes/chat.py` `chat_stream`/`chat_entity_context_stream`/`confirm_proposal` are `async with client.stream(...)` passthroughs; middleware INCRs before `call_next` and never decrements. |
| **rag-chat's only inner limiter is coarse.** A per-**tenant** sliding window (`rag:v1:rl:{tenant_id}`, default 10/min) with no per-user and no cost/token dimension. | `services/rag-chat/.../application/caching/rate_limiter.py` `RateLimiter.check_and_increment`. |
| **LLM outages have shipped with no ceiling alert before** (EODHD monthly-quota exhaustion, DeepInfra key revocation — both silent until the panel went empty). A runaway spend/quota alert is a production prerequisite. | Session memory: `project_news_momentum_investigation_2026_06_28`, `project_earnings_empty_quota_2026_06_29`. |

### 1.3 The Key Enabling Fact — PRD-0117 (dependency)

**This PRD's cost-quota portion is only feasible because PRD-0117 made the ledger trustworthy.** Before
PRD-0117 the largest, most expensive calls recorded `$0` (S6 hardcoded `0.0`; two divergent price maps;
S8 tool-loop turns uncosted). Any cost quota built on that ledger would have read ~$0 and never fired.

PRD-0117 (branch `feat/llm-cost-metering`) delivered exactly the substrate this PRD needs:

- **`resolve_cost(model_id, *, provider, tokens_in, tokens_out, provider_estimated_cost) -> (Decimal, str)`**
  in `libs/ml-clients/src/ml_clients/pricing.py` (l.458) — the single cost-source-priority calculator:
  provider-returned cost (`cost_source='provider'`) → local free (`'local'`) → price-matrix (`'pricematrix'`).
- **`CostRecorder.record(..., provider_estimated_cost=None, user_id=None)`** — a single per-call choke-point
  (`cost_recorder.py:71`) that already resolves real cost and already receives `user_id`. This is the natural
  hook to *also* bump a Valkey cost counter.
- **`cost_source='aggregate'`** — PRD-0117's leaf-costing marker for the `chat_with_tools` wrapper row
  (tokens>0, $0) whose real cost lives in the separately-recorded leaf rows. Excluding `aggregate` rows from
  the quota counter is how we meter streaming cost **exactly once** (no double-count).
- **`llm_usage_log.user_id` + `.cost_source`** columns on all three ledgers (rag_db/nlp_db/intelligence_db).

Because PRD-0117 already added `user_id`/`cost_source` and shipped `resolve_cost`, **this PRD needs no DB
migration** — it is entirely Valkey counters + a pre-flight read + gateway middleware. That is the whole
reason it is small enough to land before launch.

### 1.4 Business Value

- **Bounded blast radius on abuse or a bug.** A stuck client loop, a compromised token, or a runaway agent
  can no longer burn unbounded DeepInfra spend or exhaust concurrent capacity.
- **Per-tenant cost governance.** Aggregate monthly ceilings + 80 % approach alerting — the alert that was
  missing when EODHD/DeepInfra silently died — so operators learn *before* the bill, not after.
- **Fair multi-tenant sharing.** Per-user + per-tenant caps stop one user/tenant starving others of the
  shared LLM budget and connection pool.

---

## 2. Goals and Non-Goals

### 2.1 In Scope (Goals)

**MVP (before launch) — gateway-only, no schema migration, Valkey-only:**
1. **A — Dedicated AI request tier** in `RateLimitMiddleware`, keyed **per-user AND per-tenant**, matched by
   path prefix for every user-facing LLM endpoint (FR-A).
2. **B — Concurrent-stream cap per user** on the three gateway SSE handlers: acquire a slot on open, release
   on close, reject over the cap with 429 (FR-B).
3. **C — Config/env** following the existing `API_GATEWAY_RATE_LIMIT_*` naming, wired via the middleware
   constructor, added to worldview-gitops `env/dev` (FR-C).

**Fast-follow (first weeks post-launch):**
4. **D — Token/cost daily + monthly quotas metered in rag-chat**, where real token/cost is known: a new
   `LlmQuotaService` (mirroring `EodhdQuotaService`) bumped from `CostRecorder`, plus a **pre-flight budget
   check** pipeline step that raises a distinct `QUOTA_EXCEEDED` (FR-D).
5. **E — Screener/narrative parity**: fold `/v1/screener/nl-translate` and
   `/v1/entities/{id}/narratives/generate` into the AI request tier (already covered by FR-A path matching)
   and into the cost meter where the ledger is reachable (FR-E).

**Later / hardening:**
6. **F — Per-tenant hard monthly cost ceiling + 80 % approach alerting**; `X-RateLimit-*` and cost-remaining
   response headers so the UI can warn before a 429; a distinct quota-vs-rate error code end to end (FR-F).

### 2.2 Design Principles (LOCKED)

| # | Principle | Consequence |
|---|-----------|-------------|
| P-1 | **Two enforcement layers, two shapes.** The **gateway** enforces *request-rate* and *concurrency* (it sees only opaque SSE bytes — it cannot know tokens). **rag-chat** enforces *token/cost* (it is where real token/cost is resolved via PRD-0117's `resolve_cost`). | A never tries to count tokens; D never tries to count requests at the edge. |
| P-2 | **Reuse, don't reinvent.** Gateway AI tier reuses the existing INCR+conditional-EXPIRE + 429/`Retry-After`/`X-RateLimit-*` machinery. Cost quotas reuse the `EodhdQuotaService` soft/hard + daily/monthly + best-effort-vs-enforcing shape. Concurrency reuses the rag-chat sorted-set sliding-window pattern. | Minimal new surface; battle-tested semantics. |
| P-3 | **Meter cost exactly once.** Quota counters increment from the same `CostRecorder.record()` choke-point that PRD-0117 made authoritative, and **skip `cost_source='aggregate'`** wrapper rows (leaf-costing). | No double counting of streamed tool-loop turns. |
| P-4 | **Fail-open bias for *cost*, existing policy for *rate*.** A Valkey outage must not block paying users on a *cost* ceiling → cost quotas **fail-open** (allow + warn + metric). The gateway *request* tier keeps the existing middleware policy (transient→fail-open, unconfigured/non-transient→fail-closed 503). | Availability over strictness for spend; the hard monthly ceiling + alert (FR-F) is the backstop. |
| P-5 | **Distinct error semantics.** Ordinary throttle → `RATE_LIMIT_EXCEEDED` (429). Budget/quota exhaustion → `QUOTA_EXCEEDED` (429, distinct code + `Retry-After` to the next window boundary). | UI can tell "slow down" from "you're out of budget". |
| P-6 | **No new DB, no migration.** Everything is Valkey + PRD-0117's existing columns. | Small enough to ship pre-launch. |

### 2.3 Out of Scope (Non-Goals)

- **Billing / invoicing / paid plans.** Quotas are *protective ceilings*, not a metered billing product. Tier
  values are operator-set env config, not per-customer plan entitlements (a future PRD may add plan-driven limits).
- **Backend-service-to-backend LLM quotas** (S6 news extraction, S7 KG enrichment). Those are system pipelines
  with no end user; they are governed by their own worker concurrency, not user quotas. `nlp_db`/`intelligence_db`
  `user_id` stays NULL there (PRD-0117 already noted this).
- **Narrative-generation *cost*-quota parity in the same ledger.** Narrative generation runs in S7
  (knowledge-graph) and writes `intelligence_db.llm_usage_log`, not `rag_db`. Its **request** cap is covered by
  FR-A (gateway AI tier) + the existing 1/hr `set_nx` lock; wiring its *cost* into the rag-chat quota counter
  would require a cross-service call and is deferred to FR-F/later.
- **A quota-management admin UI.** Operators set env vars and read Grafana/alerts; no CRUD UI in this PRD.
- **DB-persisted quota ledgers or effective-dated limit tables.** Valkey counters with TTL rollups are
  sufficient (matches `EodhdQuotaService`); a durable audit trail of quota events is a later concern.

---

## 3. User Stories

### Persona A — Authenticated end user (Alex)
| ID | Story | Priority |
|----|-------|----------|
| US-A1 | As a user, when I send too many chat requests too fast I get a clear 429 with a `Retry-After`, not a silent hang or an opaque 500. | must-have |
| US-A2 | As a user, when I hit my daily/monthly LLM budget I get a distinct, understandable "quota exceeded" message (not confused with rate limiting) telling me when it resets. | should-have |
| US-A3 | As a user, I can't accidentally (or a buggy client can't) open dozens of simultaneous streams and wedge my own session. | must-have |

### Persona B — Platform Operator / cost owner (Nadia)
| ID | Story | Priority |
|----|-------|----------|
| US-B1 | As the cost owner, I can set a hard per-tenant monthly USD ceiling so no single tenant can run away with the DeepInfra bill. | must-have |
| US-B2 | As the cost owner, I get an alert when a tenant crosses 80 % of its monthly ceiling, *before* it is exhausted — the alert that was missing in the EODHD/DeepInfra outages. | must-have |
| US-B3 | As the cost owner, I can tune per-user and per-tenant request rates, concurrent-stream caps, and cost/token ceilings via env config without a code change or migration. | must-have |
| US-B4 | As the cost owner, a Valkey outage never blocks paying users on a cost ceiling; I accept temporary over-spend over an outage-induced denial, and I have a metric that tells me it happened. | must-have |

### Persona C — Platform Engineer (Marc)
| ID | Story | Priority |
|----|-------|----------|
| US-C1 | As an engineer, every user-facing LLM endpoint is provably in the AI tier (a test enumerates them), so a new AI route can't silently escape the caps. | must-have |
| US-C2 | As an engineer, streamed cost is metered exactly once (leaf-costing, `aggregate` excluded), so the quota counter matches the ledger. | must-have |
| US-C3 | As an engineer, I reuse `EodhdQuotaService`'s proven soft/hard + daily/monthly key shape rather than inventing a new one. | should-have |

---

## 4. Functional Requirements

### FR-A (MVP, CRITICAL): Dedicated AI request tier at the gateway

Add an **AI tier** to `RateLimitMiddleware` (`services/api-gateway/src/api_gateway/middleware.py`) that is
checked for requests whose path matches a user-facing LLM endpoint, keyed on **both** the user and the tenant.

**Matched paths** (`_AI_PATH_MATCHERS` — prefix/predicate, mirroring the existing `_FINANCIAL_MUTATION_PREFIXES`):
- `POST /v1/chat`, `POST /v1/chat/stream`
- `POST /v1/chat/entity-context`, `POST /v1/chat/entity-context/stream`
- `POST /v1/chat/proposals/{id}/confirm`
- `GET /v1/briefings/morning`, `GET /v1/briefings/instrument/{id}`, `POST /v1/briefings/morning/generate`,
  `POST /v1/briefings/chat/discuss` (the LLM-invoking briefings; read-only history/diff/feedback endpoints are
  *not* AI-tiered — they perform no generation)
- `POST /v1/screener/nl-translate`
- `POST /v1/entities/{id}/narratives/generate`

**Behaviour**: for an authenticated request matching the AI tier, check **two** buckets before allowing
(`call_next`). Reject with 429 if *either* is exceeded:

| Key | Limit (default) | Window |
|-----|-----------------|--------|
| `rl:v1:ai:user:{user_id}` | 20 | 60 s (`API_GATEWAY_RATE_LIMIT_AI_WINDOW_SECONDS`) |
| `rl:v1:ai:tenant:{tenant_id}` | 60 | 60 s |

- `user_id` and `tenant_id` both come from `request.state.user` (a dict `{sub,email,user_id,tenant_id,role}`
  populated by `OIDCAuthMiddleware` from the validated Zitadel token / `auth:user:{sub}` Valkey profile).
  **The middleware already reads `user["user_id"]`; this adds a read of `user["tenant_id"]`.**
- **Tier precedence** (authenticated): export → financial-mutation → **AI** → general. AI paths are never
  export/financial, so the AI check simply runs before the general fallback. On an AI match the general
  `rl:v1:user:{user_id}` bucket is **not** additionally charged (the AI tier replaces it for these paths).
- **Both-bucket INCR semantics**: INCR each key; set EXPIRE only when the returned value `== 1` (the existing
  anti-TTL-reset rule). To avoid charging the user bucket when the tenant bucket is what trips (and vice
  versa), evaluate **both** counters, then reject if either exceeds its limit. (One request may increment both
  even when it is ultimately rejected — acceptable; matches the existing single-bucket behaviour and the
  accepted EODHD TOCTOU stance.)
- **Anonymous / unauthenticated AI calls**: all gateway AI routes already `raise HTTPException(401)` when
  `request.state.user` is absent, so an unauthenticated AI request is denied at the route regardless. For
  defense-in-depth the middleware routes an unauthenticated AI request through the **existing unauthenticated
  IP tier** (`rl:v1:ip:{ip_hash}`, default 20/min) — no separate AI-IP bucket is introduced. (Rationale in §7.)
- **429 body/headers**: unchanged from the existing tier — `{"detail":"Rate limit exceeded"}`, `Retry-After`,
  `X-RateLimit-Limit`, `X-RateLimit-Remaining: 0`. The limit/`Retry-After` reflect the bucket that tripped;
  a header `X-RateLimit-Scope: ai-user|ai-tenant` is added so the UI can distinguish which dimension was hit.

**Acceptance criteria**:
- Every path in the matched-paths list resolves to the AI tier (asserted by an enumeration test, FR-C/§11).
- A user exceeding 20 AI requests in 60 s gets 429; a *second* user in the same tenant is unaffected until the
  tenant aggregate (60) trips.
- Non-AI paths are unchanged (still general/financial/export/public-feedback).

### FR-B (MVP, CRITICAL): Per-user concurrent-stream cap on the gateway SSE handlers

The gateway owns the SSE lifetime (`async with clients.rag_chat.stream(...)`), so it is the correct place to
account concurrency. Add a **slot acquire/release** around the three streaming handlers in
`services/api-gateway/src/api_gateway/routes/chat.py`: `chat_stream`, `chat_entity_context_stream`,
`confirm_proposal`.

- **Slot store**: a Valkey **sorted set per user** `rl:v1:ai:streams:{user_id}`, member = a unique stream id
  (`f"{open_ts:.6f}:{token_hex(4)}"`), score = open timestamp — **the same self-healing sorted-set pattern as
  rag-chat's `RateLimiter`**, chosen over a bare INCR/DECR counter precisely because a plain counter leaks a
  slot forever if the process crashes between acquire and the `finally` release.
- **Acquire (on open, before opening the upstream stream)**: `ZADD` self, `ZREMRANGEBYSCORE(key, 0, now - slot_ttl)`
  (evict slots older than the max stream lifetime — leaked-slot self-heal), `ZCARD`. If `ZCARD > cap`
  (`API_GATEWAY_AI_MAX_CONCURRENT_STREAMS`, default 3): `ZREM` self and return **429**
  `{"detail":"Too many concurrent AI streams"}` with `Retry-After: <slot_ttl>` and
  `X-RateLimit-Scope: ai-concurrency`.
- **Release (in a `finally` wrapping the stream generator)**: `ZREM` self. Release must run on normal
  completion, client disconnect, and upstream error.
- **`slot_ttl`** = `API_GATEWAY_AI_STREAM_SLOT_TTL_SECONDS`, default **130 s** (just above the 120 s rag-chat
  httpx client timeout, so a genuinely-active stream is never evicted mid-flight, but a leaked slot from a
  crash clears within ~130 s).
- **Fail policy**: transient Valkey error on acquire → **fail-open** (allow the stream, log warning, metric) —
  a streaming user should not be denied by a blip; unconfigured/non-transient → fail-closed 503, matching the
  middleware policy. Release errors are swallowed (best-effort; the eviction window is the backstop).

**Acceptance criteria**:
- A 4th concurrent stream for the same user (cap 3) is rejected with 429 `ai-concurrency` while the first three
  are live; after one closes, a new stream is admitted.
- A killed gateway leaves no permanent slot leak: slots clear within `slot_ttl`.
- Buffered (non-SSE) chat endpoints are **not** subject to the concurrency cap (they are request-rate-limited by FR-A).

### FR-C (MVP, HIGH): Configuration & env wiring

Add to `services/api-gateway/src/api_gateway/config.py` (`env_prefix="API_GATEWAY_"`) and thread through the
`RateLimitMiddleware` constructor (values wired from `Settings` in `app.py` lifespan, matching the existing
pattern; constructor defaults are the test contract):

| Setting | Env var | Default |
|---------|---------|---------|
| `rate_limit_ai_user_requests` | `API_GATEWAY_RATE_LIMIT_AI_USER_REQUESTS` | `20` |
| `rate_limit_ai_tenant_requests` | `API_GATEWAY_RATE_LIMIT_AI_TENANT_REQUESTS` | `60` |
| `rate_limit_ai_window_seconds` | `API_GATEWAY_RATE_LIMIT_AI_WINDOW_SECONDS` | `60` |
| `ai_max_concurrent_streams` | `API_GATEWAY_AI_MAX_CONCURRENT_STREAMS` | `3` |
| `ai_stream_slot_ttl_seconds` | `API_GATEWAY_AI_STREAM_SLOT_TTL_SECONDS` | `130` |

- Added to the `worldview-gitops` `env/dev` overlay (source of truth for deployed env — session memory
  `feedback_desc_grounding_and_key_rotation`).
- Setting any request limit to `0` disables that dimension (bucket check skipped) — an explicit escape hatch
  for load tests / incident response.

### FR-D (Fast-follow, HIGH): Token/cost daily + monthly quotas metered in rag-chat

This is where real token/cost is known (the gateway sees only opaque SSE bytes). Two parts: a **meter**
(increment counters from the authoritative choke-point) and an **enforcer** (a pre-flight budget check step).

**D-1 — `LlmQuotaService`** (new, `libs/messaging/src/messaging/llm_quota/quota_service.py`, mirroring
`EodhdQuotaService`). Valkey keys (namespaced `llm:v1`), reusing the EODHD daily/monthly + soft/hard shape:

| Key | Semantics | TTL |
|-----|-----------|-----|
| `llm:v1:cost:{YYYY-MM-DD}:user:{user_id}` | cumulative USD spend for the UTC day, per user | ~25 h (`90_000 s`) |
| `llm:v1:cost:{YYYY-MM-DD}:tenant:{tenant_id}` | cumulative USD spend for the UTC day, per tenant | ~25 h |
| `llm:v1:cost:{YYYY-MM}:tenant:{tenant_id}` | cumulative USD spend for the UTC month, per tenant | ~32 d (`32*86_400 s`) |
| `llm:v1:tokens:{YYYY-MM-DD}:user:{user_id}` | cumulative (in+out) tokens for the UTC day, per user | ~25 h |

- **Increment**: `INCRBYFLOAT` for the cost keys (real `Decimal`→float USD), `INCRBY` for the token keys, each
  with EXPIRE-on-first-hit (the EODHD `incr`+`expire` idiom). A `record_usage(...)` best-effort method swallows
  Valkey errors and logs `llm_quota_record_failed` (never breaks the chat path — matches `CostRecorder`'s
  never-raise contract and `EodhdQuotaService.record_usage`).
- **Read**: `get_cost(dimension, id, period)` / `get_tokens(...)` for the pre-flight check; `QuotaCheckResult`
  (`OK`/`SOFT_LIMIT_EXCEEDED`/`HARD_LIMIT_EXCEEDED`) reused from the EODHD shape with a `soft_limit_ratio`
  default `0.80`.

**D-2 — Meter from `CostRecorder`**: in `PrometheusAndDbCostRecorder.record()`
(`services/rag-chat/.../infrastructure/llm/cost_recorder.py`), after `resolve_cost(...)` yields
`(cost, cost_source)`, bump the counters via `LlmQuotaService.record_usage(...)` **iff
`cost_source != 'aggregate'`** (the leaf-costing exclusion — the `chat_with_tools` wrapper row is skipped so
streamed tool-loop turns are counted exactly once). `user_id` is already a parameter (PRD-0117);
`tenant_id` is threaded through from the request (already available on the call path). Increment is
best-effort and never raises.

**D-3 — Pre-flight budget check step** (the enforcer). Add a new step to `ChatPipeline`
(`services/rag-chat/.../application/pipeline/chat_pipeline.py`):
`async def check_budget(self, tenant_id: UUID, user_id: UUID) -> None`. It reads the running day/month totals
and raises a **new** `BudgetExceededError(RagError)` (`error_code="QUOTA_EXCEEDED"`) when a **hard** ceiling is
already met. Wire it in `ChatOrchestratorUseCase.execute_streaming`/`execute` immediately **after**
`check_rate_limit` (`chat_orchestrator.py:2247`, post-cache-miss, pre-retrieval, before any LLM spend).

- **Reserve-then-reconcile** (LOCKED): the check does **not** pre-estimate the request's cost. It blocks on
  request start **iff the already-recorded running total is at/over the ceiling**; a single request may overshoot
  by its own cost (one-request overshoot accepted, exactly the EODHD TOCTOU stance). The post-stream
  `CostRecorder` trues up the counter (D-2), so the *next* request sees the real total. This avoids having to
  predict streamed token counts up front.
- **Ceilings checked** (any hard breach → raise): daily user cost, monthly tenant cost, daily user tokens.
- **Fail-open** on Valkey error (P-4): log `llm_budget_check_unavailable`, emit metric, **allow** — never deny
  a paying user on an outage. The FR-F hard-ceiling alert is the backstop.
- **Error mapping**: `BudgetExceededError` → 429 with body `{"detail": <message>, "code": "QUOTA_EXCEEDED"}`
  and `Retry-After` to the next reset boundary (end of UTC day for daily, end of UTC month for monthly) for the
  buffered path (`chat.py:99/262`), and SSE `emitter.emit_error("QUOTA_EXCEEDED", <message>)` for the streaming
  path (`chat.py:170/318`) — a **distinct** code from `RATE_LIMIT_EXCEEDED`.

**D-4 — Config** (`services/rag-chat/src/rag_chat/config.py`, `env_prefix="RAG_CHAT_"`):

| Setting | Env var | Default | Meaning |
|---------|---------|---------|---------|
| `cost_daily_usd_per_user` | `RAG_CHAT_COST_DAILY_USD_PER_USER` | `2.00` | Hard per-user daily USD ceiling (`0` disables) |
| `cost_monthly_usd_per_tenant` | `RAG_CHAT_COST_MONTHLY_USD_PER_TENANT` | `50.00` | Hard per-tenant monthly USD ceiling (`0` disables) |
| `tokens_daily_per_user` | `RAG_CHAT_TOKENS_DAILY_PER_USER` | `2_000_000` | Hard per-user daily token ceiling (`0` disables) |
| `quota_soft_limit_ratio` | `RAG_CHAT_QUOTA_SOFT_LIMIT_RATIO` | `0.80` | Fraction at which a soft-limit metric/alert fires (FR-F) |
| `quota_enforcement_enabled` | `RAG_CHAT_QUOTA_ENFORCEMENT_ENABLED` | `false` | Master switch — ship metering (D-2) first, flip enforcement (D-3) on after baselining |

> **Rollout safety**: D-2 (metering) ships **enabled**; D-3 (enforcement) ships behind
> `quota_enforcement_enabled=false` so operators can observe real per-user/per-tenant spend distributions in
> Grafana for a few days and pick non-disruptive ceilings before turning enforcement on. Default USD ceilings
> above are conservative placeholders to be re-set from observed data (OQ-1).

### FR-E (Fast-follow, MEDIUM): Screener & narrative parity

- **Request-tier parity**: already delivered by FR-A (both `/v1/screener/nl-translate` and
  `/v1/entities/{id}/narratives/generate` are in the matched-paths list). No extra work beyond FR-A.
- **Cost-meter parity for the screener**: the gateway's direct DeepInfra screener call already POSTs a usage
  record to S8's `POST /internal/v1/llm-usage` (PRD-0117 FR-6). Extend that **S8 ingest handler** to also call
  `LlmQuotaService.record_usage(...)` (same exclusion + best-effort rules) so screener spend counts against the
  user/tenant cost quota. This keeps all gateway-adjacent LLM spend both in the ledger and in the meter without
  a new cross-service path.
- **Narrative cost-meter parity**: **out of scope here** (S7 writes `intelligence_db`, not `rag_db`); its
  *request* cap is FR-A + the existing 1/hr `set_nx` lock. Metering S7 narrative cost into the shared quota is
  deferred to FR-F/later.

### FR-F (Later / hardening): Hard tenant ceiling alerting, headers, distinct code end-to-end

- **Soft-limit approach alerting**: when a tenant crosses `quota_soft_limit_ratio` (80 %) of its monthly cost
  ceiling, increment `llm_quota_soft_limit_exceeded_total{dimension="tenant",kind="cost"}` and wire a Grafana/
  Alertmanager alert. **This is the alert whose absence made the EODHD/DeepInfra outages silent** (session
  memory) — it is a production prerequisite, not a nicety.
- **Cost-remaining response headers**: on AI responses, surface `X-LLM-Cost-Remaining-USD`,
  `X-LLM-Cost-Limit-USD`, `X-LLM-Cost-Reset` (and token equivalents) so the frontend can warn the user at ~80 %
  *before* a 429. Values are the user's own dimension only (no cross-tenant leakage).
- **Distinct code end-to-end in the UI**: the frontend renders `QUOTA_EXCEEDED` differently from
  `RATE_LIMIT_EXCEEDED` ("You've reached today's AI budget, resets in Xh" vs "Slow down, try again in Ns").
- **(Stretch) narrative cost parity**: S7 narrative generation calls the quota meter (cross-service), folding
  its spend into the tenant ceiling.

---

## 5. Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | **Never raise into the request path.** Every quota increment/check is best-effort — a failure logs a structured warning and continues (matches `CostRecorder` never-raise + `EodhdQuotaService.record_usage`). |
| NFR-2 | **Sub-millisecond overhead.** The AI tier adds 2 Valkey INCRs; the budget check adds ≤3 Valkey GETs; the stream cap adds one ZADD/ZREM pair. No new network calls to backends, no DB reads. |
| NFR-3 | **No DB migration, forward-compatible.** Uses only Valkey + PRD-0117's existing `user_id`/`cost_source` columns. |
| NFR-4 | **Decimal precision for cost.** Counters store USD as float via `INCRBYFLOAT`; the *ceiling comparison* is done in `Decimal` against the config value to avoid float drift on the boundary. |
| NFR-5 | **UTC-aligned windows.** Daily keys use `datetime.now(tz=UTC).date().isoformat()`, monthly `%Y-%m` (matches `EodhdQuotaService` and the briefing 100/day limiter). |
| NFR-6 | **Observability.** New metrics per §13; every reject path increments a labelled counter so 429 causes are attributable (rate vs concurrency vs quota, user vs tenant). |

---

## 6. Technical Design

### 6.1 Affected Services & Files

| Service / lib | Change | Key files |
|---|---|---|
| **S9 api-gateway** | AI request tier (2 buckets) in `RateLimitMiddleware`; read `tenant_id` from `request.state.user`; `X-RateLimit-Scope` header; new config fields wired via constructor. | `src/api_gateway/middleware.py` (`RateLimitMiddleware`, l.443-651), `src/api_gateway/config.py` (l.68-85), `src/api_gateway/app.py` (lifespan wiring) |
| **S9 api-gateway** | Per-user concurrent-stream acquire/release (sorted set) on the 3 SSE handlers. | `src/api_gateway/routes/chat.py` (`chat_stream` l.64, `chat_entity_context_stream` l.183, `confirm_proposal` l.255) |
| **libs/messaging** | New `LlmQuotaService` mirroring `EodhdQuotaService` (daily/monthly cost + token keys, soft/hard, best-effort `record_usage`). | `src/messaging/llm_quota/quota_service.py` (new), `src/messaging/llm_quota/__init__.py` |
| **S8 rag-chat** | Meter from `CostRecorder` (skip `aggregate`); new `check_budget` pipeline step + `BudgetExceededError`; wire in orchestrator; screener-ingest meter parity; config. | `infrastructure/llm/cost_recorder.py`, `application/pipeline/chat_pipeline.py`, `application/use_cases/chat_orchestrator.py` (l.2247), `domain/errors.py`, `api/routes/chat.py` (429/SSE mapping), `api/routes/internal.py` (`/internal/v1/llm-usage` handler), `config.py` |
| **worldview-gitops** | New `API_GATEWAY_RATE_LIMIT_AI_*`, `API_GATEWAY_AI_*`, `RAG_CHAT_COST_*`, `RAG_CHAT_TOKENS_*`, `RAG_CHAT_QUOTA_*` env vars. | `env/dev` overlay |

### 6.2 API Changes

**No new endpoints; no request/response *schema* changes.** The change surface is (a) new **429 responses** on
existing AI endpoints and (b) new **response headers**.

New/changed error responses on existing AI endpoints:

| Endpoint(s) | New status | Body | Headers |
|-------------|-----------|------|---------|
| All AI-tier endpoints (FR-A) | `429` | `{"detail":"Rate limit exceeded"}` | `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining: 0`, `X-RateLimit-Scope: ai-user\|ai-tenant` |
| 3 SSE handlers (FR-B) | `429` | `{"detail":"Too many concurrent AI streams"}` | `Retry-After`, `X-RateLimit-Scope: ai-concurrency` |
| Chat buffered (D-3) | `429` | `{"detail":<msg>,"code":"QUOTA_EXCEEDED"}` | `Retry-After` (to reset boundary) |
| Chat SSE (D-3) | SSE `event: error` | `{"code":"QUOTA_EXCEEDED","message":<msg>}` via `SSEEmitter.emit_error` | — |
| AI responses (FR-F) | (success) | unchanged | `X-LLM-Cost-Remaining-USD`, `X-LLM-Cost-Limit-USD`, `X-LLM-Cost-Reset` (+ token equivalents) |

The existing internal endpoint **`POST /internal/v1/llm-usage`** (S8) gains a side-effect only (calls
`LlmQuotaService.record_usage`); its request/response shape is unchanged (FR-E).

### 6.3 Event Changes

**None.** No Kafka topics added or modified. All enforcement is synchronous Valkey read/increment.

### 6.4 Database Changes

**None.** PRD-0117 already added `llm_usage_log.user_id` and `.cost_source` on all three ledgers, and shipped
`resolve_cost`. This PRD introduces **no migration** — the quota state lives entirely in Valkey with TTL rollups.
(This is the direct payoff of depending on PRD-0117.)

### 6.5 Domain / Carrier Model Changes

**`BudgetExceededError`** — `services/rag-chat/src/rag_chat/domain/errors.py`, new subclass of `RagError`
(itself `DomainError → RagError`), `error_code = "QUOTA_EXCEEDED"`. Carries `message` + `details`
(`{"dimension": "user"|"tenant", "kind": "cost"|"tokens", "period": "day"|"month", "reset_at": <iso>}`).
Add-with-default; no existing construction breaks.

**`LlmQuotaService`** (libs/messaging) — new, structurally mirrors `EodhdQuotaService`:
`QuotaCheckResult(StrEnum){OK, SOFT_LIMIT_EXCEEDED, HARD_LIMIT_EXCEEDED}`; constructor
`(valkey, *, soft_limit_ratio=0.80)`; methods `record_cost(user_id, tenant_id, cost_usd)` (best-effort
`INCRBYFLOAT` + EXPIRE across the four keys), `record_tokens(user_id, tokens)`, `get_cost(dimension, id, period)`,
`get_tokens(user_id)`, `check(...) -> QuotaCheckResult`. Never raises from the `record_*` path.

### 6.6 Data Flow

**Gateway AI request (FR-A):** client → `OIDCAuthMiddleware` sets `request.state.user{user_id,tenant_id}` →
`RateLimitMiddleware`: path matches AI tier → `INCR rl:v1:ai:user:{user_id}` (+EXPIRE if 1),
`INCR rl:v1:ai:tenant:{tenant_id}` (+EXPIRE if 1) → either over limit ⇒ 429; else `call_next` → proxy to S8.

**Gateway SSE concurrency (FR-B):** `chat_stream` handler → acquire: `ZADD rl:v1:ai:streams:{user_id}` +
`ZREMRANGEBYSCORE`(evict stale) + `ZCARD` → over cap ⇒ `ZREM` self + 429; else open
`clients.rag_chat.stream(...)`, yield chunks; `finally: ZREM` self.

**rag-chat streaming turn (D):** orchestrator Step 1 validate → **Step 2 `check_rate_limit`** →
**Step 2b `check_budget`** (GET day-user-cost / month-tenant-cost / day-user-tokens; hard breach ⇒
`BudgetExceededError` ⇒ SSE `QUOTA_EXCEEDED`) → retrieve → stream LLM → per leaf call
`CostRecorder.record(...)` resolves `(cost, cost_source)` → writes ledger row **and**, iff
`cost_source != 'aggregate'`, `LlmQuotaService.record_cost/record_tokens` bumps the counters (reconcile).
Next request's `check_budget` sees the updated total.

**Screener (FR-E):** gateway direct DeepInfra call → best-effort `POST /internal/v1/llm-usage` (S8) → handler
writes `rag_db.llm_usage_log` **and** `LlmQuotaService.record_cost(...)` for the caller's user/tenant.

### 6.7 Frontend Changes

- **MVP**: none required for correctness — the frontend already surfaces 429s. (Nice-to-have: read
  `X-RateLimit-Scope` to word the toast.)
- **FR-F**: render `QUOTA_EXCEEDED` distinctly from `RATE_LIMIT_EXCEEDED`; read cost-remaining headers to show
  an approaching-budget banner at ~80 %. (Frontend → S9 only; R14 preserved.)

---

## 7. Architecture Decisions & Trade-offs

| Decision | Chosen | Rejected alternative | Why |
|---|---|---|---|
| Where to enforce | **Two layers**: gateway = request-rate + concurrency; rag-chat = token/cost | Enforce everything at the gateway | The gateway sees only opaque SSE bytes — it cannot know tokens/cost. rag-chat is where `resolve_cost` runs (P-1). |
| AI request key(s) | **Both** `ai:user` and `ai:tenant` checked | Single per-user only | A tenant with many users could still overwhelm shared LLM capacity; the tenant aggregate is the real cost-blast bound. |
| Concurrency store | **Sorted set** with eviction window | Bare `INCR`/`DECR` counter | A counter leaks a slot forever on a crash between acquire and `finally`; the sorted-set eviction window self-heals (reuses the rag-chat `RateLimiter` pattern). |
| Cost enforcement model | **Reserve-then-reconcile** (block if running total ≥ ceiling; one-request overshoot OK) | Pre-estimate the request's token cost and pre-debit | Streamed token counts are unknown up front; pre-estimation is inaccurate and complex. Overshoot of one request is bounded and matches the accepted EODHD TOCTOU stance. |
| Meter source | **`CostRecorder.record()`**, skip `cost_source='aggregate'` | A separate quota-only counting path | One authoritative choke-point (PRD-0117) guarantees the counter equals the ledger; the `aggregate` exclusion prevents double-counting streamed tool loops (P-3). |
| Valkey outage — cost | **Fail-open** (allow + warn + metric) | Fail-closed (deny) | Never deny a paying user because a cache blipped; the hard monthly ceiling + 80 % alert (FR-F) is the backstop (P-4, US-B4). |
| Valkey outage — request tier | **Existing middleware policy** (transient→fail-open, unconfigured/non-transient→fail-closed 503) | Change the policy for AI | Consistency with every other tier; the request tier is abuse-protection, not spend, so a brief fail-open is low-risk. |
| Existing rag-chat 10/min per-tenant limiter | **Keep as defense-in-depth, raise default to align** | Retire it | It protects the *direct* S8 path (callers bypassing the gateway) and is a cheap inner bound. But at 10/tenant/min it would silently override the intended 60/tenant + 20/user edge granularity — so raise `RAG_CHAT_RATE_LIMIT_PER_TENANT` to `60` (match the gateway tenant tier) so the edge tier is primary and the inner limiter is a true safety net, not the effective cap. |
| Anonymous AI calls | **Denied at route (401) + existing unauth IP tier** | A dedicated `ai:ip` bucket | Routes already 401 without `request.state.user`; a separate AI-IP bucket adds surface for no gain — the standard unauth IP tier already caps pre-auth probing. |
| Storage | **Valkey counters, TTL rollups** | DB-persisted quota ledger | Matches `EodhdQuotaService`; no migration; no cross-service DB (R9); the ledger already provides the durable audit trail. |

### 7.1 Architecture Compliance Gate

| Rule | Applies? | Design decision | Compliant? |
|------|----------|-----------------|-----------|
| **R9 — No cross-service DB access** | yes | Quota state is Valkey (shared cache, namespaced keys) — the same shared-cache pattern `EodhdQuotaService` already uses across services; no service reads another's Postgres. Screener parity uses the existing S8 internal REST endpoint, not a DB. | PASS |
| **R14 — Frontend → S9 only** | yes | No frontend→backend direct calls; cost-remaining headers and error codes are surfaced via S9. | PASS |
| **R25 — API layer uses only use cases** | yes | The `check_budget` enforcement lives in the application/pipeline layer (`ChatPipeline` step invoked by the orchestrator use case), not in a router; the router only maps `BudgetExceededError`→429/SSE. Gateway edge enforcement is middleware, not a router importing infrastructure. | PASS |
| **R27 — Read-only use cases use read replica** | yes/NA | The budget check reads **Valkey**, not Postgres — no UoW involved; it introduces no DB read that would need `ReadOnlyUnitOfWork`. | PASS (NA) |
| **R11 — Forward-compatible schema** | no | No schema change (Valkey-only; PRD-0117 columns already exist). | PASS |
| **R6 — UUIDv7 / R7 — UTC** | partial | No new IDs minted; all window keys are UTC-derived (`date()`/`%Y-%m`). | PASS |
| **R13 — Use shared libs** | yes | `LlmQuotaService` lives in `libs/messaging` next to `EodhdQuotaService`; both gateway and rag-chat consume shared Valkey clients. | PASS |
| **R8 — No secrets in code** | yes | All ceilings via pydantic-settings env; no secrets added. | PASS |

No FAIL rows.

---

## 8. Security Analysis

| Threat | Vector | Mitigation |
|--------|--------|------------|
| **Quota bypass via unmatched path** | A new/renamed AI route not added to `_AI_PATH_MATCHERS` silently escapes the caps and falls into the 2000/min general bucket. | An **enumeration test** asserts every known LLM route matches the AI tier (§11); the matched-paths list is documented; a review-checklist item requires new AI routes to update it. |
| **Key/counter enumeration or spoofing** | Attacker crafts a key to read/inflate another user's counter. | Keys are built from `user_id`/`tenant_id` taken from the **validated JWT** (`request.state.user` at the gateway, `request.state.{tenant_id,user_id}` via `InternalJWTMiddleware` at rag-chat) — never from request-supplied values. Unauth uses `sha256(ip)[:16]`. No user-controlled key material. |
| **Cross-tenant spend / read** | User A charges or reads tenant B's budget. | `tenant_id` is JWT-derived and immutable per request; cost-remaining headers expose only the caller's own dimension. |
| **Concurrency-slot exhaustion / leak** | Attacker opens many streams; or crashes leak slots to lock a user out. | Per-user cap (3); acquire self-evicts stale slots (self-DoS bounded to own user); leaked slots clear within `slot_ttl` (130 s). |
| **Fail-open cost abuse during Valkey outage** | Spend proceeds uncapped while Valkey is down (P-4). | Bounded by: the request-rate tier still applies (fail-closed on config error); the hard monthly ceiling + 80 % alert (FR-F) surfaces runaway spend; a `llm_budget_check_unavailable_total` metric makes the fail-open window visible. Accepted residual risk (US-B4). |
| **Information leak in error** | `QUOTA_EXCEEDED` reveals internal budget figures. | Message states the *user's own* limit + reset time only; no tenant-aggregate or other-user data; internal ceilings are operator config, not sensitive. |
| **Log safety (R14)** | Logging user identifiers / prompt content. | Only `user_id`/`tenant_id` UUIDs, counts, and cost — never prompt/response bodies (existing structlog pattern). |

---

## 9. Failure Modes

| Failure | Behaviour | Recovery |
|---|---|---|
| Valkey transient error, AI request tier | 1 retry (50 ms) then **fail-open** (allow) — existing middleware policy | Self-heals when Valkey returns |
| Valkey unconfigured / non-transient, request tier | **Fail-closed 503** — existing policy | Fix config; alert on `rate_limiting_unavailable_total{503_no_retry}` |
| Valkey error, **cost** budget check | **Fail-open** (allow) + `llm_budget_check_unavailable` warning + metric | Hard ceiling alert (FR-F) is the backstop |
| Valkey error, quota **increment** (D-2) | Best-effort swallow + `llm_quota_record_failed` warning | Counter under-counts (fail-open bias) until Valkey returns |
| Gateway crash mid-stream | Slot not `ZREM`'d, but evicted after `slot_ttl` (130 s) | Self-heals; no permanent leak |
| `aggregate` wrapper row double-count | Prevented — meter skips `cost_source='aggregate'` (P-3) | Regression test asserts the exclusion |
| One large request overshoots the ceiling | Accepted one-request overshoot (reserve-then-reconcile); next request blocked | Reconcile via post-stream `CostRecorder`; documented |
| Enforcement misconfigured too low | `quota_enforcement_enabled=false` default + generous placeholder ceilings; observe before enabling | Flip flag off instantly; set `*_USD=0` to disable a dimension |
| Clock skew across replicas at UTC boundary | Daily/monthly keys derived from `datetime.now(tz=UTC)`; a few boundary requests may hit the old/new bucket | Bounded, self-correcting at the next request; matches EODHD/briefing limiter behaviour |

Cross-ref BUG_PATTERNS: reuses the fail-open-vs-fail-closed policy split (do not fail-closed on transient
Valkey); reuses `set_nx`/`incr`+conditional-`expire` idioms (BP-200 — `set_nx` not `set(nx=True)`); avoids the
"counter leaks on crash" trap via the eviction-window sorted set; avoids the "audit value returned but not
persisted" family by incrementing at the authoritative `CostRecorder` choke-point.

---

## 10. Rollout

**MVP (A/B/C) — gateway-only, safe to ship independently:**
1. Add gateway config fields + gitops env (limits generous initially).
2. Deploy `RateLimitMiddleware` AI tier + SSE concurrency cap.
3. Smoke: exceed 20 AI/min for a user → 429 `ai-user`; a second same-tenant user unaffected until 60/min;
   open a 4th concurrent stream → 429 `ai-concurrency`; non-AI paths unchanged.

**Fast-follow (D/E) — meter first, enforce later:**
4. Ship `LlmQuotaService` + `CostRecorder` metering (D-2) with `quota_enforcement_enabled=false`. Observe real
   per-user/per-tenant spend in Grafana for several days.
5. Set data-driven ceilings (resolve OQ-1); flip `quota_enforcement_enabled=true` (D-3). Smoke: a user over the
   daily USD ceiling gets `QUOTA_EXCEEDED` (buffered 429 + SSE), distinct from `RATE_LIMIT_EXCEEDED`.
6. Extend the S8 `/internal/v1/llm-usage` handler to meter screener spend (E).

**Later (F):** wire the 80 % soft-limit alert, cost-remaining headers, and the UI code distinction.

**Rollback**: all limits are env-driven — set any dimension to `0` to disable it live; flip
`quota_enforcement_enabled=false` to disable cost enforcement instantly. No migration to reverse.

---

## 11. Test Strategy

### Unit Tests
| Test | Verifies | Priority |
|------|----------|----------|
| test_ai_tier_matches_all_llm_paths | Every path in the FR-A matched list resolves to the AI tier (guards against a new AI route escaping) | HIGH |
| test_ai_tier_checks_both_user_and_tenant | Both `rl:v1:ai:user` and `rl:v1:ai:tenant` are INCR'd; over-limit on either → 429 | HIGH |
| test_ai_tier_tenant_aggregate_trips_across_users | User1 under cap + User2 pushes tenant total over 60 → User2 429 `ai-tenant` | HIGH |
| test_ai_tier_non_ai_path_unchanged | A non-AI path still hits general/financial/export tier | HIGH |
| test_ai_tier_unauthenticated_uses_ip_tier | No `request.state.user` → unauth IP tier, not AI buckets | MEDIUM |
| test_stream_slot_acquire_release | ZADD on open, ZREM in finally; 4th concurrent → 429 `ai-concurrency` | HIGH |
| test_stream_slot_self_heals_after_ttl | Stale members evicted by `ZREMRANGEBYSCORE` beyond `slot_ttl` | HIGH |
| test_stream_slot_fail_open_on_transient_valkey | Transient error on acquire → stream allowed + metric | MEDIUM |
| test_llm_quota_keys_and_ttls | `LlmQuotaService` writes the 4 keys with correct UTC period + TTLs (~25 h / ~32 d) | HIGH |
| test_llm_quota_record_never_raises | Valkey error in `record_cost` → swallowed + warning | HIGH |
| test_cost_recorder_skips_aggregate | `cost_source='aggregate'` row does NOT bump the quota counter (leaf-costing) | HIGH |
| test_check_budget_hard_breach_raises_quota_exceeded | Running total ≥ ceiling → `BudgetExceededError(code=QUOTA_EXCEEDED)` | HIGH |
| test_check_budget_fail_open_on_valkey_error | Valkey error in check → allow + warning + metric | HIGH |
| test_budget_error_maps_429_and_sse | Buffered → 429 `{code:QUOTA_EXCEEDED}`; SSE → `emit_error("QUOTA_EXCEEDED",...)`; distinct from RATE_LIMIT_EXCEEDED | HIGH |
| test_decimal_boundary_no_float_drift | Ceiling comparison in `Decimal` (e.g. exactly-at-limit) is correct | MEDIUM |

### Integration Tests (testcontainers Valkey; + S8 app for the pipeline)
| Test | Infra | Verifies |
|------|-------|----------|
| test_gateway_ai_tier_end_to_end | Valkey + gateway app | 21st AI request in 60 s → 429; header `X-RateLimit-Scope: ai-user` |
| test_concurrent_stream_cap_end_to_end | Valkey + gateway app | 3 live SSE streams admitted, 4th 429'd, admitted again after one closes |
| test_reserve_then_reconcile | Valkey + S8 pipeline | A turn over the daily ceiling is admitted once (overshoot), the next is blocked after `CostRecorder` reconciles |
| test_screener_ingest_meters_quota | Valkey + S8 internal endpoint | `POST /internal/v1/llm-usage` bumps `llm:v1:cost:*` for the caller |
| test_enforcement_flag_off_never_blocks | Valkey + S8 pipeline | `quota_enforcement_enabled=false` meters but never raises |

### Guardrail / Observability Tests
| Test | Verifies |
|------|----------|
| test_soft_limit_alert_metric_increments | Crossing 80 % of monthly tenant ceiling increments `llm_quota_soft_limit_exceeded_total` (FR-F) |
| test_reject_metrics_labelled | Each 429 path increments its labelled counter (rate/concurrency/quota × user/tenant) |

---

## 12. Documentation Updates (mandatory)

- `docs/services/api-gateway.md` — document the AI rate-limit tier (paths, keys, both-bucket semantics),
  the concurrent-stream cap, and the new `API_GATEWAY_RATE_LIMIT_AI_*` / `API_GATEWAY_AI_*` env vars.
- `docs/services/rag-chat.md` — document the cost/token quota, `LlmQuotaService` keys, the `check_budget`
  pipeline step, `QUOTA_EXCEEDED`, and the `RAG_CHAT_COST_*`/`TOKENS_*`/`QUOTA_*` env vars.
- `services/api-gateway/.claude-context.md` + `services/rag-chat/.claude-context.md` — pitfalls: "new AI route
  MUST be added to `_AI_PATH_MATCHERS`"; "meter cost from `CostRecorder` only, and skip `cost_source='aggregate'`";
  "cost quota fails OPEN, request tier keeps existing fail-open/closed split".
- `libs/messaging` docs — add `LlmQuotaService` next to `EodhdQuotaService` (same shape).
- `docs/BUG_PATTERNS.md` — "counter-based concurrency limiter leaks a slot on crash → use an eviction-window
  sorted set"; "AI route added without updating the rate-limit matcher escapes all caps".
- `.claude/review/checklists/REVIEW_CHECKLIST.md` — "any new user-facing LLM endpoint is added to the AI tier
  matcher and has an enumeration-test assertion".
- `docs/plans/TRACKING.md` — register PRD-0118 (depends-on PRD-0117).

---

## 13. Observability

New metrics:
- `ai_rate_limit_exceeded_total{scope="ai-user"|"ai-tenant"}` — AI request-tier rejections (gateway).
- `ai_concurrent_stream_rejected_total` — FR-B rejections (gateway).
- `llm_quota_exceeded_total{dimension="user"|"tenant",kind="cost"|"tokens",period="day"|"month"}` — hard breaches (rag-chat).
- `llm_quota_soft_limit_exceeded_total{dimension,kind}` — 80 % approach (FR-F) — **the alerting metric**.
- `llm_budget_check_unavailable_total` — cost-quota fail-open events (Valkey outage).
- `llm_quota_record_failed_total` — best-effort increment failures.
- Reuse existing `rate_limiting_unavailable_total{fallback_action}` for the AI tier's Valkey fallbacks.

Alerts (FR-F): tenant monthly cost ≥ 80 % (warning) and ≥ 100 % (critical); sustained `llm_budget_check_unavailable_total`
(cost enforcement is effectively off — Valkey down). Dashboards: per-tenant/per-user daily & monthly spend
(from counters), 429 breakdown by scope, concurrent-stream high-water mark.

---

## 14. Open Questions

All core design decisions are LOCKED (§2.2, FR-A..FR-F). Remaining items are **DEFERRED** (implementation can
proceed with the stated assumption); none are BLOCKING.

| # | Question | Classification | Assumption to proceed |
|---|----------|----------------|-----------------------|
| OQ-1 | Exact production values for the request rates and USD/token ceilings. | DEFERRED | Ship the placeholder defaults (20/60/min; $2/day-user, $50/mo-tenant, 2M tok/day-user) with **enforcement off**; observe real spend for several days (D-2 metering) and set data-driven ceilings before enabling (D-3). |
| OQ-2 | Should the gateway AI tier and rag-chat cost counters live in the same Valkey instance/DB? | DEFERRED | No — they are different concerns and each service uses its own Valkey (`API_GATEWAY_VALKEY_URL` vs rag-chat's). Keys are namespaced; no co-location needed. |
| OQ-3 | Should `check_budget` also block on the **tenant daily** cost (not just tenant monthly)? | DEFERRED | Start with per-user daily + per-tenant monthly + per-user daily tokens (the three most protective). Add tenant-daily only if data shows intra-day tenant spikes matter. |
| OQ-4 | Keep or retire the rag-chat 10/min per-tenant `RateLimiter` once the gateway AI tenant tier is live? | DEFERRED | Keep as defense-in-depth for direct-S8 callers; raise `RAG_CHAT_RATE_LIMIT_PER_TENANT` default to `60` to align with the gateway tenant tier so it is a safety net, not the effective cap. |
| OQ-5 | Fold S7 narrative-generation cost into the shared tenant ceiling? | DEFERRED | Not in MVP/fast-follow (request cap via FR-A + 1/hr `set_nx` suffices); revisit under FR-F if narrative spend becomes material. |

---

## 15. Estimation

| Wave | Scope | Cut line | Size |
|------|-------|----------|------|
| **W1** | **FR-A** gateway AI request tier (two buckets, path matcher, tenant_id read, `X-RateLimit-Scope`) + **FR-C** config/env | **MVP (pre-launch)** | M |
| **W2** | **FR-B** per-user concurrent-stream cap (sorted-set acquire/release on 3 SSE handlers) | **MVP (pre-launch)** | S |
| **W3** | **FR-D-1/D-2** `LlmQuotaService` (libs/messaging) + `CostRecorder` metering (skip `aggregate`) + config; enforcement OFF | Fast-follow | M |
| **W4** | **FR-D-3** `check_budget` pipeline step + `BudgetExceededError` + orchestrator wiring + 429/SSE `QUOTA_EXCEEDED`; **FR-E** screener-ingest meter parity; flip enforcement ON | Fast-follow | M |
| **W5** | **FR-F** 80 % soft-limit alert + cost-remaining headers + UI code distinction (+ stretch: narrative cost parity) | Later / hardening | S–M |

**MVP-vs-fast-follow cut line**: **W1 + W2 (A/B/C)** ship before launch — gateway-only, Valkey-only, **no schema
migration** — and deliver the hard protections (per-user + per-tenant request caps, concurrent-stream cap).
**W3 + W4 (D/E)** are the fast-follow cost/token quotas in rag-chat, shipped meter-first then enforce.
**W5 (F)** is later hardening (alerting, headers, UX polish).

**Dependency note**: the cost-quota portion (W3–W5) is only feasible because **PRD-0117** made the
`llm_usage_log` ledger and `resolve_cost` trustworthy (real per-call cost, `cost_source` provenance incl.
`aggregate` leaf-costing, and the `user_id` column). Built on the pre-0117 ledger, every cost counter would
have read ~$0 and no cost quota could fire. This PRD therefore lists `depends-on: PRD-0117` and sequences
W3–W5 **after** PRD-0117 is merged and deployed.
