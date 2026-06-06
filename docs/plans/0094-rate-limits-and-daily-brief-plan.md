---
id: PLAN-0094
title: Rate-Limit Env-ification + Daily Morning-Brief Pre-Generation
prd: inline (see §0)
status: draft
created: 2026-05-24
updated: 2026-05-24
---

# PLAN-0094 — Rate-Limit Env-ification + Daily Morning-Brief Pre-Generation

## §0 — Inline PRD

> No separate PRD doc — this plan captures the spec inline because the change is small (config + one new worker) and was driven by a focused investigation rather than a feature request.

### Problem statement

Two operator-facing pain points surfaced during the 2026-05-24 investigation:

1. **Rate-limit knobs are partly hard-coded.** The API-gateway middleware tightly couples the dashboard-bucket limit to `API_GATEWAY_RATE_LIMIT_REQUESTS`, but three sibling limits — `_FINANCIAL_MUTATION_LIMIT = 20`, the unauth-IP `20`, and the public-feedback `120` — are hard-coded literals. Operators cannot tune them via `worldview-gitops` env files. Default user bucket also needs raising from 1000 → 2000 to match expected production load.
2. **Morning brief cold-misses block the user.** The brief is cached in Valkey for 24 h; on expiry the next request blocks ~3–5 s while the LLM regenerates. There is no scheduled pre-generation and no fallback path — if the regeneration fails, the user gets a 503.

### Goals

1. Move all four rate-limit numbers (user, financial-mutation, unauth-IP, public-feedback) behind env vars with safe defaults in code; bump the user-bucket default to 2000.
2. Build an APScheduler-driven worker that pre-generates morning briefs for **active users** (defined as: at least one authenticated request in the last `K` days, default `7`) every `N` hours (default `24`).
3. Identify active users via a Valkey sorted-set `active_users` that S9's auth middleware populates with `ZADD active_users <unix_ts> <user_id>` on every successful internal-JWT validation (Option A in the investigation).
4. Persist a `briefing:morning:lastgood:{user_id}` key (no TTL within configurable window) so a failed regeneration leaves the user with the prior day's brief plus a `is_stale=true` + `generated_at=<date>` indicator instead of a 503.
5. Full observability: 6 Prometheus metrics + structured logs across run, per-user, and stale-serve paths.
6. Frontend renders "Previous day's brief — {date}" badge when `is_stale=true`.

### Non-goals

- Per-user timezone scheduling (single fixed UTC interval for v1; per-tz is a future enhancement requiring a prefs table).
- Pre-generation for instrument briefs (entity-scoped; deferred — instrument page already serves fast on miss).
- Multi-tenant rate-limit granularity (today's single-tenant model is preserved).

### Open questions

None — all design decisions resolved with the user 2026-05-24:
- Active-user signal → **Valkey sorted-set populated by S9 auth middleware (Option A)**.
- Eligibility window → **7 days, env-configurable (`RAG_CHAT_BRIEF_PREGEN_ACTIVE_WINDOW_DAYS`)**.
- Cadence → **24 h, env-configurable (`RAG_CHAT_BRIEF_PREGEN_INTERVAL_HOURS`)**.
- Failure behaviour → **serve last-known-good with stale indicator, surface previous day's date**.
- Logging depth → **6 Prom metrics + structlog events on run start/complete/fail + per-user attempt + stale-serve**.

---

## §1 — Overview

**PRD**: inline (above)
**Services affected**: S9 (api-gateway), S8 (rag-chat), `apps/worldview-web` (frontend)
**Total waves**: 3
**Total estimated effort**: ~4–5 hours
**Critical path**: W1 → W2 → W3 (linear)
**External dependency**: operator must add the 4 new rate-limit env vars + 7 new brief env vars to `worldview-gitops/env/{dev,prod}/api-gateway.env` and `.../rag-chat.env`. Checklist included in W3.

## §2 — Dependency Graph

```
W1 (S9: rate-limit env-ification + active-users ZADD)
        │
        ▼
W2 (rag-chat: brief pregeneration worker + handler fallback + metrics + tests)
        │
        ▼
W3 (frontend stale-badge + docs + worldview-gitops checklist)
```

W2 cannot start until W1 ships because the worker reads the `active_users` sorted-set that W1 populates. W3 cannot start until W2 ships the new response fields (`is_stale`, `generated_at`).

## §3 — Codebase State Verification

| Reference | Type | Service | Actual current state | Plan target | Delta |
|-----------|------|---------|----------------------|-------------|-------|
| `RateLimitMiddleware` | class | S9 | `middleware.py:409`; constructor takes `max_requests`, `window_seconds`; reads `_FINANCIAL_MUTATION_LIMIT=20` (line 406), hard-codes `20` (line 527) and `120` (line 524) | accept 3 new constructor args; remove hard-coded literals | code change |
| `Settings.rate_limit_requests` | field | S9 | `config.py:74`, default `1000` | bump default to `2000`; add 3 new fields | code change |
| `_FINANCIAL_MUTATION_LIMIT` | module constant | S9 | `middleware.py:406 = 20` | delete; replace with constructor arg | code change |
| `OIDCAuthMiddleware` / `InternalJWTMiddleware` | class | S9 | dispatches auth; sets `request.state.user` | add `ZADD active_users` after successful auth | code change (one site) |
| `active_users` | Valkey sorted-set | S9 + S8 share Valkey | does not exist | NEW key | new artifact |
| `briefing:morning:v2:{user_id}` | Valkey key | S8 | `public_briefings.py:153`, TTL 24h via `_CACHE_TTL` | TTL bumped to `RAG_CHAT_BRIEF_FRESH_TTL_HOURS` (default 30h, env-driven) | code change |
| `briefing:morning:lastgood:{user_id}` | Valkey key | S8 | does not exist | NEW key, written on every successful generation, TTL = `RAG_CHAT_BRIEF_LAST_GOOD_TTL_DAYS` × 86400 | new artifact |
| `PublicBriefingResponse` | Pydantic schema | S8 | `schemas/...` (must confirm exact path) — has `cached`, `generated_at`, `confidence`, etc. | add `is_stale: bool = False` | additive schema change |
| `MorningBriefPregenerationWorker` | class | S8 | does not exist | NEW — `application/workers/morning_brief_pregeneration_worker.py` | new file |
| `brief_scheduler_main.py` | entry-point | S8 | does not exist | NEW — `infrastructure/scheduling/brief_scheduler_main.py`; APScheduler IntervalTrigger | new file |
| `rag-chat-brief-scheduler` | compose service | infra | does not exist | NEW container; mirrors `alert-email-scheduler` at `infra/compose/docker-compose.yml:2064` | new compose entry |
| Prometheus metrics | metrics | S8 | `rag_no_tool_calls_first_turn`, etc. live in `application/metrics/prometheus.py` | add 6 new metrics (NEW) | new metrics |
| `MorningBriefCard` | component | frontend | `apps/worldview-web/src/components/...` (must confirm exact path; W3 will locate) | add stale-date badge when `is_stale=true` | UI change |

## §4 — Sub-Plans

### Wave W1 — S9 rate-limit env-ification + active-users tracking

**Goal**: Replace 3 hard-coded rate-limit literals in `RateLimitMiddleware` with env-driven config; bump user-bucket default 1000 → 2000; populate Valkey `active_users` sorted-set on every successful auth.

**Depends on**: none
**Estimated effort**: ~60 min
**Architecture layer**: API + config
**Branch**: `feat/plan-0094-w1`

#### Tasks

##### T-W1-01: Add 3 new rate-limit fields to S9 `Settings`

**Type**: config
**depends_on**: none
**blocks**: T-W1-02
**Target files**: `services/api-gateway/src/api_gateway/config.py`
**PRD reference**: §0 goal 1

**What to build**:
Add three new `Settings` fields driven by env vars, with safe defaults equal to today's hard-coded values. Bump `rate_limit_requests` default from `1000` → `2000`.

**Field additions**:
- `rate_limit_financial_mutation_requests: int = 20` — env `API_GATEWAY_RATE_LIMIT_FINANCIAL_MUTATION_REQUESTS`. Comment: "Tighter sub-tier for POST/PUT/DELETE on /v1/transactions, /v1/brokerage, /v1/portfolios."
- `rate_limit_unauthenticated_requests: int = 20` — env `API_GATEWAY_RATE_LIMIT_UNAUTHENTICATED_REQUESTS`. Comment: "Strict per-IP cap for unauthenticated traffic."
- `rate_limit_public_feedback_requests: int = 120` — env `API_GATEWAY_RATE_LIMIT_PUBLIC_FEEDBACK_REQUESTS`. Comment: "Generous per-IP cap for /v1/feedback/* (PLAN-0052 fix)."

Also change line 74: `rate_limit_requests: int = 1000` → `rate_limit_requests: int = 2000`. Update the surrounding comment block to reflect the new default + that the 3 sibling limits are now env-driven.

**Acceptance criteria**:
- [ ] All 3 new fields exist with type `int` and sensible defaults
- [ ] `rate_limit_requests` default is `2000`
- [ ] ruff + mypy pass on `config.py`

##### T-W1-02: Wire 3 new limits through `RateLimitMiddleware`

**Type**: impl
**depends_on**: [T-W1-01]
**blocks**: T-W1-03
**Target files**: `services/api-gateway/src/api_gateway/middleware.py`, `services/api-gateway/src/api_gateway/app.py`
**PRD reference**: §0 goal 1

**What to build**:
1. Extend `RateLimitMiddleware.__init__` to accept three new keyword args: `financial_mutation_limit`, `unauthenticated_limit`, `public_feedback_limit`, all `int`, no defaults (caller must pass).
2. Store on `self`; replace the hard-coded literals at lines 524 (`120`), 527 (`20`), and 512 (`_FINANCIAL_MUTATION_LIMIT`) with `self.public_feedback_limit`, `self.unauthenticated_limit`, `self.financial_mutation_limit` respectively.
3. Delete the module-level `_FINANCIAL_MUTATION_LIMIT = 20` constant at line 406 (the prefix tuple `_FINANCIAL_MUTATION_PREFIXES` stays).
4. In `app.py`, wherever `RateLimitMiddleware(...)` is instantiated, pass the three new settings values.

**Logic & behaviour**:
- Order of constructor args: `app, valkey_client, max_requests, window_seconds, financial_mutation_limit, unauthenticated_limit, public_feedback_limit`. All three new args are keyword-only (use `*,` separator) so misordered call sites fail loudly.
- All existing branches still set `limit = …` exactly as before; only the source of the integer changes.

**Tests to write**:
| Test name | What it verifies | Type |
|-----------|-----------------|------|
| `test_financial_mutation_limit_reads_from_constructor` | Constructing with `financial_mutation_limit=50`, posting 51 times to `/v1/transactions`, 51st request returns 429 | unit |
| `test_unauthenticated_limit_reads_from_constructor` | Same pattern with `unauthenticated_limit=5` against an unauthenticated path | unit |
| `test_public_feedback_limit_reads_from_constructor` | Same pattern with `public_feedback_limit=3` against `/v1/feedback/x` | unit |
| `test_default_user_bucket_is_2000` | A fresh `Settings()` has `rate_limit_requests == 2000` | unit |

**Downstream test impact**:
- `services/api-gateway/tests/unit/test_rate_limit_middleware.py` — any existing test that asserts on hard-coded `20`/`120` or constructs `RateLimitMiddleware(...)` without the new args will break. Update fixtures to pass all three; assertions on `20`/`120` keep working if defaults are used.

**Acceptance criteria**:
- [ ] `_FINANCIAL_MUTATION_LIMIT` constant is gone
- [ ] No hard-coded `20` or `120` rate-limit literals remain in `middleware.py` (grep -n)
- [ ] 4 new unit tests pass
- [ ] All existing `test_rate_limit_middleware.py` tests still pass
- [ ] ruff + mypy pass

##### T-W1-03: Populate `active_users` sorted-set on successful JWT auth

**Type**: impl
**depends_on**: [T-W1-02]
**blocks**: T-W2-02
**Target files**: `services/api-gateway/src/api_gateway/middleware.py` (likely `InternalJWTMiddleware` or `OIDCAuthMiddleware`)
**PRD reference**: §0 goal 3

**What to build**:
After the auth middleware successfully decodes a JWT and sets `request.state.user`, execute a fire-and-forget Valkey write:

```python
await valkey.zadd("active_users", {str(user_id): int(time.time())})
```

Wrap in try/except — Valkey errors must NOT block the request (auth path is hot; a Valkey hiccup must not 503 a successful user). Log warning on failure with `error=str(exc)`.

**Where to add it**: The exact middleware (`OIDCAuthMiddleware` vs `InternalJWTMiddleware`) depends on which one runs first and which one extracts `user_id`. Read `middleware.py` to find the first middleware that successfully resolves `user_id` from a JWT, and add the ZADD at the point where `request.state.user` is set. If both middlewares could set it, prefer the inner-most (so the ZADD only fires once per successful auth).

**Pruning**: The sorted-set grows unbounded if never pruned. Add a probabilistic prune (e.g., `if random.random() < 0.001: await valkey.zremrangebyscore("active_users", 0, int(time.time()) - 30*86400)`) so old entries (older than 30 days) get cleaned up roughly 1 in 1000 requests. 30 days is well above the maximum eligibility window (7 days default, configurable).

**Logic & behaviour**:
- Key name `active_users` is global (no tenant scoping needed — single-tenant deployment).
- Score = current Unix timestamp (seconds). Member = stringified user_id.
- ZADD with a member that already exists updates the score (sliding window — newest activity wins). This is the desired semantics.

**Tests to write**:
| Test name | What it verifies | Type |
|-----------|-----------------|------|
| `test_jwt_auth_writes_active_users_zadd` | After a successful auth, Valkey ZRANGEBYSCORE returns the user_id | unit |
| `test_jwt_auth_valkey_failure_does_not_503` | Mock valkey.zadd to raise; auth still returns 200 | unit |
| `test_jwt_auth_records_warning_on_valkey_failure` | structlog captures `active_users_zadd_failed` warning | unit |

**Acceptance criteria**:
- [ ] After any successful authenticated request, `ZSCORE active_users <user_id>` returns a recent unix timestamp
- [ ] Valkey ZADD failure does not affect the auth response
- [ ] 3 new unit tests pass
- [ ] ruff + mypy pass

##### T-W1-04: Update dev env files with new rate-limit vars

**Type**: config
**depends_on**: [T-W1-01]
**blocks**: none
**Target files**: `services/api-gateway/configs/docker.env`, `services/api-gateway/configs/docker.env.example`, `services/api-gateway/configs/dev.local.env.example` (if it exists)
**PRD reference**: §0 goal 1

**What to build**:
Add the 4 new vars to dev env files. Suggested dev values:
```
API_GATEWAY_RATE_LIMIT_REQUESTS=10000           # already present; verify still 10000 for dev
API_GATEWAY_RATE_LIMIT_FINANCIAL_MUTATION_REQUESTS=100
API_GATEWAY_RATE_LIMIT_UNAUTHENTICATED_REQUESTS=200
API_GATEWAY_RATE_LIMIT_PUBLIC_FEEDBACK_REQUESTS=500
```

Rationale: dev should be loose for testing; prod values come from worldview-gitops (operator decides — recommendations in W3 docs).

**Acceptance criteria**:
- [ ] All 4 vars present in `docker.env` and `docker.env.example`
- [ ] `make dev` still boots api-gateway cleanly

#### Pre-read

- `services/api-gateway/src/api_gateway/config.py` (full file)
- `services/api-gateway/src/api_gateway/middleware.py` (lines 380–640, plus auth middleware section above)
- `services/api-gateway/src/api_gateway/app.py` (middleware wiring)
- `services/api-gateway/tests/unit/test_rate_limit_middleware.py` (existing tests)

#### Validation gate

- [ ] ruff + mypy clean on api-gateway
- [ ] All existing api-gateway unit tests pass
- [ ] 7 new unit tests pass (4 for limit env + 3 for active-users ZADD)
- [ ] `docker compose up api-gateway` boots cleanly with new env vars
- [ ] Grep confirms no hard-coded `20`/`120` rate-limit literals remain in `middleware.py`

#### Architecture compliance

- [ ] **R12 — structlog**: new warning log uses `logger.warning(...)` from existing structlog `logger` in the file
- [ ] **R11 — UTC timestamps**: `int(time.time())` is fine (Unix epoch is timezone-agnostic)
- [ ] **R30 — secrets**: no secrets touched
- [ ] No new entities, no R25 / R27 implications

#### Break impact

| Broken file | Why it breaks | Fix |
|-------------|--------------|-----|
| `services/api-gateway/tests/unit/test_rate_limit_middleware.py` | Constructor signature gained 3 kwargs | Update all `RateLimitMiddleware(...)` constructions in tests to pass the 3 new args (or use a fixture helper) |
| `services/api-gateway/src/api_gateway/app.py` | Constructor signature changed | Pass settings through |

#### Regression guardrails

- **BP-144** — RateLimitMiddleware previously had a bug where `valkey_client=None` permanently disabled rate limiting. Verify the constructor still reads valkey from `app.state` at request time, not from the constructor arg.
- **BP-024 / BP-200** — Valkey API differences (ValkeyClient.set/zadd). Use the same client wrapper pattern already in `middleware.py` (`await valkey.zadd(...)`).
- **BP-549** — orphan downstream helpers after a constant deletion. After removing `_FINANCIAL_MUTATION_LIMIT`, grep the entire api-gateway tree for any other reference (tests, docs) and clean up.

---

### Wave W2 — rag-chat brief pre-generation worker + fallback + observability

**Goal**: Ship the daily morning-brief pre-generation worker and the handler fallback path that serves last-known-good with a stale indicator on regeneration failure.

**Depends on**: W1 (active-users ZADD must be live)
**Estimated effort**: ~3 hours
**Architecture layer**: application (worker + use case extension) + infrastructure (scheduler entry-point + Valkey) + API (handler refactor) + config + metrics
**Branch**: `feat/plan-0094-w2`

#### Tasks

##### T-W2-01: Add 7 new fields to rag-chat `Settings`

**Type**: config
**depends_on**: none
**blocks**: T-W2-03, T-W2-04
**Target files**: `services/rag-chat/src/rag_chat/config.py`
**PRD reference**: §0 goals 2, 3, 4

**What to build**:
Add a new "Brief pre-generation" section to `Settings`:

```python
# ── Brief pre-generation (PLAN-0094 W2) ───────────────────────────────────
brief_pregen_enabled: bool = True                    # RAG_CHAT_BRIEF_PREGEN_ENABLED
brief_pregen_interval_hours: int = Field(default=24, ge=1, le=168)
brief_pregen_active_window_days: int = Field(default=7, ge=1, le=90)
brief_pregen_batch_size: int = Field(default=50, ge=1, le=500)
brief_pregen_concurrency: int = Field(default=4, ge=1, le=20)
brief_fresh_ttl_hours: int = Field(default=30, ge=1, le=168)
brief_last_good_ttl_days: int = Field(default=7, ge=1, le=30)
```

`Field(...)` with `ge`/`le` constraints surfaces operator misconfiguration at startup (e.g., negative interval rejected before scheduler runs).

**Acceptance criteria**:
- [ ] All 7 fields present with constraints
- [ ] `Settings()` constructs with defaults in test
- [ ] Out-of-range value (e.g., `RAG_CHAT_BRIEF_PREGEN_INTERVAL_HOURS=0`) raises `ValidationError` at startup

##### T-W2-02: `ActiveUsersReader` — Valkey ZRANGEBYSCORE adapter

**Type**: impl
**depends_on**: [T-W1-03]
**blocks**: T-W2-04
**Target files**: `services/rag-chat/src/rag_chat/infrastructure/clients/active_users_reader.py` (NEW — created in this plan)
**PRD reference**: §0 goal 3

**What to build**:
A small infrastructure adapter that reads the `active_users` sorted-set populated by S9 (W1). Single responsibility: hand the worker a list of user_ids active in the last `K` days.

**Class shape**:
```python
class ActiveUsersReader:
    def __init__(self, valkey_client: redis.asyncio.Redis, window_days: int) -> None: ...
    async def list_active(self) -> list[UUID]: ...
```

`list_active()` calls `ZRANGEBYSCORE("active_users", now - window_days*86400, "+inf")`, decodes byte members, parses as UUID. Skips malformed entries with a warning log (don't fail the whole batch on one bad row).

**Port interfaces** (R25):
- `IActiveUsersPort` (ABC in `application/ports/active_users.py`, NEW) — `async def list_active() -> list[UUID]`
- Concrete `ActiveUsersReader` lives in infrastructure; the worker depends on the port

**Read/write classification**: read-only — no UoW needed (Valkey is its own session)

**Tests to write**:
| Test name | What it verifies | Type |
|-----------|-----------------|------|
| `test_list_active_returns_users_in_window` | Seed Valkey with 3 users at recent timestamps + 1 at 30d old; window=7d returns only the 3 recent | unit |
| `test_list_active_skips_malformed_members` | Seed with a non-UUID member; log warning, return the rest | unit |
| `test_list_active_empty_set_returns_empty_list` | No seed; returns `[]` cleanly | unit |

**Acceptance criteria**:
- [ ] ABC port exists; concrete impl is the only infra implementation
- [ ] 3 unit tests pass
- [ ] ruff + mypy clean

##### T-W2-03: 6 new Prometheus metrics + structlog event taxonomy

**Type**: impl
**depends_on**: [T-W2-01]
**blocks**: T-W2-04, T-W2-05
**Target files**: `services/rag-chat/src/rag_chat/application/metrics/prometheus.py`
**PRD reference**: §0 goal 5

**What to build**:
Append 6 new metrics to the existing `prometheus.py`:

```python
rag_brief_pregeneration_runs_total = Counter(
    "rag_brief_pregeneration_runs_total",
    "Pre-generation scheduler runs",
    labelnames=["status"],  # started | completed | failed
)
rag_brief_pregeneration_users_total = Counter(
    "rag_brief_pregeneration_users_total",
    "Per-user pre-generation outcomes",
    labelnames=["outcome"],  # success | generation_failed | skipped_stale_kept
)
rag_brief_pregeneration_run_duration_seconds = Histogram(
    "rag_brief_pregeneration_run_duration_seconds",
    "End-to-end pre-generation run latency",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1200, 1800),
)
rag_brief_pregeneration_user_duration_seconds = Histogram(
    "rag_brief_pregeneration_user_duration_seconds",
    "Per-user pre-generation latency",
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60),
)
rag_brief_pregeneration_eligible_users = Gauge(
    "rag_brief_pregeneration_eligible_users",
    "Number of active users found in the last run",
)
rag_brief_served_stale_total = Counter(
    "rag_brief_served_stale_total",
    "Times the handler served last-known-good brief instead of fresh",
)
```

Also add these structlog event names to the documented catalogue (in service docs in W3):
- `brief_pregeneration_run_started` / `_completed` / `_failed`
- `brief_pregeneration_user_started` / `_succeeded` / `_failed`
- `brief_served_stale` (handler fallback path)
- `brief_served_fresh` (handler happy path; OPTIONAL — only at DEBUG to avoid log noise)

**Tests to write**:
| Test | What it verifies | Type |
|------|-----------------|------|
| `test_all_brief_metrics_registered` | Each of the 6 metrics is importable and has expected labels | unit |

**Acceptance criteria**:
- [ ] All 6 metrics importable from `application.metrics.prometheus`
- [ ] Labels match spec
- [ ] Existing metrics unchanged

##### T-W2-04: `MorningBriefPregenerationWorker` — generation orchestrator

**Type**: impl
**depends_on**: [T-W2-01, T-W2-02, T-W2-03]
**blocks**: T-W2-05, T-W2-07
**Target files**: `services/rag-chat/src/rag_chat/application/workers/morning_brief_pregeneration_worker.py` (NEW)
**PRD reference**: §0 goals 2, 4, 5

**What to build**:
Worker class that orchestrates one full pre-generation run.

**Class shape**:
```python
class MorningBriefPregenerationWorker:
    def __init__(
        self,
        *,
        active_users: IActiveUsersPort,       # ABC port (R25)
        briefing_uc: GenerateBriefingUseCase,
        valkey_client: redis.asyncio.Redis,
        settings: Settings,
    ) -> None: ...

    async def run(self) -> None:
        """Execute one pre-generation pass. Idempotent; safe to re-fire."""
```

**Logic & behaviour**:
1. Emit `brief_pregeneration_run_started` log + increment `rag_brief_pregeneration_runs_total{status="started"}`.
2. Call `active_users.list_active()` → `users: list[UUID]`. Set `rag_brief_pregeneration_eligible_users` gauge to `len(users)`.
3. Chunk users into batches of `settings.brief_pregen_batch_size`. Within each batch, run up to `brief_pregen_concurrency` users in parallel via `asyncio.Semaphore`.
4. For each user: time the per-user attempt; call `_generate_for_user(user_id)`; record outcome metric + per-user duration.
5. On success: write **both** the fresh key (`briefing:morning:v2:{user_id}`, TTL `brief_fresh_ttl_hours * 3600`) **and** the last-known-good key (`briefing:morning:lastgood:{user_id}`, TTL `brief_last_good_ttl_days * 86400`). The last-known-good JSON adds `"generated_at": <ISO timestamp>` and `"is_stale": False` at the top level — these are the fields the handler reads when falling back.
6. On per-user failure: log `brief_pregeneration_user_failed` with `error_type`, `latency_ms`. Increment `rag_brief_pregeneration_users_total{outcome="generation_failed"}`. Do **not** overwrite the existing last-known-good key — the next handler call will serve it as stale.
7. On run completion: emit `brief_pregeneration_run_completed` log with counts, observe `rag_brief_pregeneration_run_duration_seconds`, increment `rag_brief_pregeneration_runs_total{status="completed"}`.
8. On run-level exception (e.g., Valkey hard-down): emit `_failed` log + metric. Never raise out of `run()` — the scheduler must keep firing.

**Port interfaces** (R25):
- `IActiveUsersPort` (created in T-W2-02)
- `GenerateBriefingUseCase` — already a use case (`application/use_cases/generate_briefing.py`); we depend on its existing `execute_public_morning(user_id, tenant_id, internal_jwt)` method
- `valkey_client` is infrastructure; the worker treats it as a port (acceptable — Valkey has no clean ABC abstraction in this repo; mirror the pattern used elsewhere)

**JWT considerations**: `execute_public_morning()` reads `internal_jwt` from the request context. The worker has no request context — it needs to mint or fetch a service JWT. **Implementation**: use the existing `service_account_token` pattern (S1 has `POST /internal/v1/service-token` returning an internal JWT). Inject a minted service JWT into the use case call. The worker's `__init__` should accept an `IJwtMinter` port (ABC); concrete impl calls S9's `/internal/v1/service-token` endpoint.

> **Open implementation detail**: confirm `execute_public_morning()` accepts a service JWT without erroring on missing user context. If it strictly requires a user-issued JWT, refactor to expose a `for_user_id(user_id)` overload that the worker can call directly. This is a 30-min sub-task; budget included.

**Tests to write**:
| Test | What it verifies | Type |
|------|-----------------|------|
| `test_run_processes_all_eligible_users` | 3 mocked users → 3 fresh + 3 lastgood Valkey writes | unit |
| `test_run_skips_user_on_generation_failure_keeps_lastgood` | Use case raises for user 2; user 2's lastgood is NOT overwritten; users 1 & 3 succeed | unit |
| `test_run_emits_metrics_for_started_completed` | After successful run, runs_total{started} == 1 and runs_total{completed} == 1 | unit |
| `test_run_continues_after_per_user_exception` | Per-user exception doesn't abort the batch | unit |
| `test_run_respects_concurrency_limit` | Concurrency=2, 5 users, never more than 2 concurrent calls observed | unit |
| `test_run_handles_empty_active_users_cleanly` | 0 users → run completes, gauge=0, no errors | unit |

**Downstream test impact**: none — this is all new code

**Acceptance criteria**:
- [ ] Worker class exists with the contract above
- [ ] All 6 unit tests pass
- [ ] Per-user failure isolation verified (test 2)
- [ ] ruff + mypy clean

##### T-W2-05: Handler fallback path — fresh → lastgood → on-demand

**Type**: impl
**depends_on**: [T-W2-03, T-W2-04]
**blocks**: T-W2-06
**Target files**: `services/rag-chat/src/rag_chat/api/routes/public_briefings.py`, `services/rag-chat/src/rag_chat/api/schemas/briefing.py` (or wherever `PublicBriefingResponse` lives — find via git grep)
**PRD reference**: §0 goals 4, 5, 6

**What to build**:
Refactor `GET /api/v1/briefings/morning` handler to follow this lookup chain:

1. Fresh cache (`briefing:morning:v2:{user_id}`): hit → return with `is_stale=False`, `generated_at=<from cache>`.
2. Else last-known-good (`briefing:morning:lastgood:{user_id}`): hit → return with `is_stale=True`, `generated_at=<from lastgood>`, increment `rag_brief_served_stale_total`, emit `brief_served_stale` log. Also fire-and-forget a background re-generation task (`asyncio.create_task(uc.execute_public_morning(...))`) so the next request can hit fresh — but **don't** wait for it.
3. Else (cold user, never had a brief): existing on-demand path — block while generating; on success, write both keys; on failure, 503.

**Schema additions to `PublicBriefingResponse`**:
- `is_stale: bool = False` — defaults false so existing callers don't break
- `generated_at` already exists; ensure it reflects the actual generation time, not the cache-read time

**Tests to write**:
| Test | What it verifies | Type |
|------|-----------------|------|
| `test_handler_returns_fresh_when_fresh_cache_hit` | Fresh hit → is_stale=False, no background regen | unit |
| `test_handler_returns_lastgood_with_stale_flag` | No fresh, lastgood present → is_stale=True, generated_at from lastgood, served_stale counter +1 | unit |
| `test_handler_falls_back_to_on_demand_when_no_cache` | No fresh, no lastgood → on-demand generate → returns is_stale=False | unit |
| `test_handler_does_not_blockingly_regenerate_when_stale_served` | When serving stale, response returns within X ms (no full LLM latency) | unit |
| `test_handler_503_when_on_demand_fails_for_cold_user` | Cold user + use case raises → 503 (current behaviour preserved) | unit |

**Downstream test impact**:
- `services/rag-chat/tests/integration/test_briefing_morning.py` (if exists) — must update expectations to handle the new `is_stale` field
- Frontend `MorningBriefCard` tests — handled in W3

**Architecture compliance** (R27): handler is read-mostly; cache reads are I/O; on-demand path writes to Valkey only (no DB writes here). No UoW dependency.

**Acceptance criteria**:
- [ ] Three-level fallback chain implemented
- [ ] `PublicBriefingResponse.is_stale` field present
- [ ] 5 new unit tests pass
- [ ] Existing handler tests still pass with updated expectations
- [ ] ruff + mypy clean

##### T-W2-06: `brief_scheduler_main.py` — APScheduler entry-point

**Type**: impl
**depends_on**: [T-W2-04]
**blocks**: T-W2-07
**Target files**: `services/rag-chat/src/rag_chat/infrastructure/scheduling/brief_scheduler_main.py` (NEW), `services/rag-chat/src/rag_chat/infrastructure/scheduling/__init__.py` (NEW if dir doesn't exist)
**PRD reference**: §0 goal 2

**What to build**:
Standalone async process entry-point that runs the `MorningBriefPregenerationWorker` on a configurable interval. Direct mirror of `services/alert/src/alert/infrastructure/email/scheduler_main.py` (template — read it first).

**Structure**:
```python
async def _run_loop(settings: Settings) -> None:
    configure_logging(service_name=settings.service_name, level=settings.log_level, json=settings.log_json)
    log = get_logger("rag_chat.brief_scheduler_main")

    if not settings.brief_pregen_enabled:
        log.info("brief_pregeneration_disabled_via_env")
        return  # exit cleanly

    # Build dependencies: Valkey client, JWT minter, ActiveUsersReader, GenerateBriefingUseCase, Worker
    valkey = redis.asyncio.from_url(settings.valkey_url)
    active_users = ActiveUsersReader(valkey, window_days=settings.brief_pregen_active_window_days)
    # ... GenerateBriefingUseCase deps (S1/S3/S5/S6/S7 clients) — mirror app.py wiring ...
    worker = MorningBriefPregenerationWorker(
        active_users=active_users,
        briefing_uc=briefing_uc,
        valkey_client=valkey,
        settings=settings,
    )

    ap_scheduler = AsyncIOScheduler()
    ap_scheduler.add_job(
        worker.run,
        IntervalTrigger(hours=settings.brief_pregen_interval_hours),
        id="brief_pregeneration",
        max_instances=1,        # prevent overlapping runs
        coalesce=True,          # skip missed runs on restart
        next_run_time=datetime.utcnow() + timedelta(seconds=30),  # fire first run 30s after startup
    )
    ap_scheduler.start()
    log.info("brief_scheduler_started", interval_hours=settings.brief_pregen_interval_hours)

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        ap_scheduler.shutdown(wait=False)
        await valkey.close()
        log.info("brief_scheduler_stopped")
```

**Tests to write**: none for the entry-point itself (it's a thin wiring shim); the worker's own tests cover behaviour. Add a smoke test:
| Test | What it verifies | Type |
|------|-----------------|------|
| `test_scheduler_main_exits_when_disabled` | `brief_pregen_enabled=False` → `_run_loop` returns immediately | unit |

**Acceptance criteria**:
- [ ] File runs via `python -m rag_chat.infrastructure.scheduling.brief_scheduler_main`
- [ ] Disabled-mode early-return works
- [ ] First run fires 30s after start (so it's observable without waiting 24h)
- [ ] ruff + mypy clean

##### T-W2-07: Docker Compose `rag-chat-brief-scheduler` container

**Type**: config
**depends_on**: [T-W2-06]
**blocks**: T-W2-08
**Target files**: `infra/compose/docker-compose.yml`
**PRD reference**: §0 goal 2

**What to build**:
Add a new compose service after the existing `rag-chat` block (after line 2129). Mirror `alert-email-scheduler` (lines 2064–2083).

```yaml
  rag-chat-brief-scheduler:
    build:
      context: ../..
      dockerfile: services/rag-chat/Dockerfile
    profiles: [infra, all]
    depends_on:
      rag-chat-migrate:
        condition: service_completed_successfully
      valkey:
        condition: service_healthy
      api-gateway:
        condition: service_healthy   # JWKS fetch + active_users source
    env_file:
      - ../../services/rag-chat/configs/docker.env
    command: ["python", "-m", "rag_chat.infrastructure.scheduling.brief_scheduler_main"]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import os; os.kill(1, 0)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
```

**Acceptance criteria**:
- [ ] Container starts via `docker compose up rag-chat-brief-scheduler`
- [ ] On boot it logs `brief_scheduler_started`
- [ ] 30s after boot it logs `brief_pregeneration_run_started` (first run)
- [ ] `docker compose down` exits cleanly

##### T-W2-08: Dev env file updates

**Type**: config
**depends_on**: [T-W2-01]
**blocks**: none
**Target files**: `services/rag-chat/configs/docker.env`, `services/rag-chat/configs/docker.env.example`
**PRD reference**: §0 goals 2, 4

Add the 7 new vars with their defaults. Set `RAG_CHAT_BRIEF_PREGEN_INTERVAL_HOURS=1` in dev for fast iteration (so you can see the worker fire within minutes during testing).

**Acceptance criteria**:
- [ ] 7 vars present in both files
- [ ] Dev override: `RAG_CHAT_BRIEF_PREGEN_INTERVAL_HOURS=1`

#### Pre-read

- `services/rag-chat/src/rag_chat/api/routes/public_briefings.py` (full)
- `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py` (full — to understand `execute_public_morning` contract)
- `services/alert/src/alert/infrastructure/email/scheduler_main.py` (template)
- `services/rag-chat/src/rag_chat/application/metrics/prometheus.py` (existing metrics style)
- `services/rag-chat/src/rag_chat/app.py` (DI wiring — copy for scheduler_main)

#### Validation gate

- [ ] ruff + mypy clean on rag-chat
- [ ] All existing rag-chat unit tests pass
- [ ] ≥15 new unit tests pass (3 reader + 6 worker + 5 handler + 1 scheduler-disabled + new metrics registration test)
- [ ] `docker compose up rag-chat-brief-scheduler` runs the first generation pass within 60s of boot
- [ ] After pre-gen runs, `valkey-cli GET briefing:morning:v2:<user_id>` returns the same JSON the handler would serve, with `is_stale=False`
- [ ] After pre-gen runs, `valkey-cli GET briefing:morning:lastgood:<user_id>` returns JSON with `is_stale=True`

#### Architecture compliance

- [ ] **R25 — ABC ports**: `IActiveUsersPort` defined as ABC; worker depends on the port not the concrete class
- [ ] **R27 — ReadOnlyUoW**: handler is read-only (no DB writes); no UoW needed (cache-only path)
- [ ] **R12 — structlog**: all new events use `structlog.get_logger(__name__)`
- [ ] **R10 / R11**: no new IDs or timestamps in entities (only Valkey scores and metric values)
- [ ] **R30**: no secrets touched

#### Break impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| `apps/worldview-web/.../MorningBriefCard.tsx` (or types) | Response gained `is_stale` field | W3 handles this; for now schema is additive with default `False`, so old clients don't break |
| `services/rag-chat/tests/integration/test_briefing_morning.py` (if exists) | Response shape changed | Update assertions to handle new field |
| Existing handler tests | Lookup chain changed | Update mocks to cover the 3-level chain |

#### Regression guardrails

- **BP-319** — `model_dump_json` not `json.dumps(default=str)` when caching Pydantic models (already in handler; preserve in worker)
- **BP-549** — orphan helpers; if any code (use case, port) becomes unused after the handler refactor, delete it
- **BP-235** — `httpx.AsyncClient` timeout: any new upstream calls in the scheduler must set explicit `httpx.Timeout(N)` (worker uses existing use case so likely inherited, but confirm)
- **BP-200** — Valkey API (`zadd`/`zrangebyscore`/`set ex=`): use the existing wrapper conventions
- **BP-407** — Kafka backpressure (N/A — this plan adds no Kafka)

---

### Wave W3 — Frontend stale-badge + docs + worldview-gitops checklist

**Goal**: Surface the "previous day" indicator in the UI; document the new env vars; produce a checklist for the operator to update `worldview-gitops`.

**Depends on**: W2
**Estimated effort**: ~60–90 min
**Architecture layer**: frontend + docs
**Branch**: `feat/plan-0094-w3`

#### Tasks

##### T-W3-01: Frontend `MorningBriefCard` stale-date badge

**Type**: impl
**depends_on**: [T-W2-05]
**blocks**: none
**Target files**: `apps/worldview-web/src/...` — locate the `MorningBriefCard` component via `git grep -l "MorningBriefCard"` at implement-time
**PRD reference**: §0 goal 6

**What to build**:
When `is_stale === true`, render a small subdued badge near the brief title: e.g., `Previous day's brief — May 23 2026`. Format the date with the user's locale (use the existing `useFormattedTimestamp` hook listed in MEMORY.md under Frontend Platform Hardening primitives). Use the existing `SignalBadge` component if it fits visually; otherwise inline a `<span className="text-muted-foreground text-xs">…</span>`.

When `is_stale === false`, no badge.

**Tests to write**:
| Test | What it verifies | Type |
|------|-----------------|------|
| `MorningBriefCard.test.tsx — renders stale badge when is_stale=true` | Badge text matches `Previous day's brief — <formatted date>` | unit (vitest) |
| `MorningBriefCard.test.tsx — does not render badge when is_stale=false` | No badge in DOM | unit |

**Acceptance criteria**:
- [ ] Badge renders correctly in both states
- [ ] 2 vitest tests pass
- [ ] No TS errors
- [ ] Visual check in `make dev` against a seeded stale response

##### T-W3-02: Service docs — rag-chat brief pre-generation

**Type**: docs
**depends_on**: [T-W2-05, T-W2-06]
**blocks**: none
**Target files**: `docs/services/rag-chat.md`, `services/rag-chat/.claude-context.md`
**PRD reference**: §0 (entire)

**What to build**:
Add a new section to `docs/services/rag-chat.md` titled **"Morning Brief — Daily Pre-Generation (PLAN-0094)"** documenting:
- The 3-level lookup chain (fresh → lastgood → on-demand)
- The 7 env vars + their semantics + safe ranges + recommended prod values
- The 6 new Prom metrics + their labels and intended use
- The structlog event taxonomy
- The active-users sorted-set contract (key name, score semantics, populated by S9 W1, read by S8 W2, 30-day pruning)
- Failure semantics (stale serve preserves UX, lastgood TTL is the maximum staleness ceiling)

Add a one-line cross-reference in `services/rag-chat/.claude-context.md` Pitfalls: "Morning brief uses lastgood fallback — never overwrite `briefing:morning:lastgood:*` on per-user failure (PLAN-0094 W2 T-W2-04 contract)."

##### T-W3-03: Service docs — api-gateway rate-limit env vars

**Type**: docs
**depends_on**: [T-W1-01, T-W1-03]
**blocks**: none
**Target files**: `docs/services/api-gateway.md`
**PRD reference**: §0 goal 1

**What to build**:
Update the rate-limit section to enumerate **all 4 vars** (the existing `API_GATEWAY_RATE_LIMIT_REQUESTS` + the 3 new ones) with: env name, default, what it gates, recommended prod range. Note the default user-bucket bump 1000 → 2000.

Document the `active_users` Valkey sorted-set as an outbound contract (S9 populates; S8 consumes) so it's discoverable.

##### T-W3-04: worldview-gitops checklist

**Type**: docs
**depends_on**: [T-W1-01, T-W2-01]
**blocks**: none
**Target files**: `docs/audits/2026-05-24-plan-0094-worldview-gitops-checklist.md` (NEW — created in this plan)
**PRD reference**: §0 goals 1, 2

**What to build**:
A short checklist the operator can follow when applying this plan in production. Contents:

```markdown
# PLAN-0094 — worldview-gitops Update Checklist

## env/prod/api-gateway.env — add 4 vars
- API_GATEWAY_RATE_LIMIT_REQUESTS=2000          # was 1000 (or whatever prod had); bump per ops decision
- API_GATEWAY_RATE_LIMIT_FINANCIAL_MUTATION_REQUESTS=20    # keep tight unless ops decides otherwise
- API_GATEWAY_RATE_LIMIT_UNAUTHENTICATED_REQUESTS=20       # keep tight
- API_GATEWAY_RATE_LIMIT_PUBLIC_FEEDBACK_REQUESTS=120      # keep current

## env/prod/rag-chat.env — add 7 vars
- RAG_CHAT_BRIEF_PREGEN_ENABLED=true
- RAG_CHAT_BRIEF_PREGEN_INTERVAL_HOURS=24
- RAG_CHAT_BRIEF_PREGEN_ACTIVE_WINDOW_DAYS=7
- RAG_CHAT_BRIEF_PREGEN_BATCH_SIZE=50
- RAG_CHAT_BRIEF_PREGEN_CONCURRENCY=4
- RAG_CHAT_BRIEF_FRESH_TTL_HOURS=30
- RAG_CHAT_BRIEF_LAST_GOOD_TTL_DAYS=7

## Verification after deploy
- [ ] api-gateway logs `rate_limit_settings_loaded` on boot with all 4 values
- [ ] rag-chat-brief-scheduler container reaches running state
- [ ] Within 30s of boot, scheduler emits `brief_pregeneration_run_started`
- [ ] Grafana shows `rag_brief_pregeneration_eligible_users` matching ZCARD active_users
- [ ] No 503s on /v1/briefings/morning during the first 24h post-deploy

## Rollback
- Disable pre-gen: set RAG_CHAT_BRIEF_PREGEN_ENABLED=false and restart rag-chat-brief-scheduler; handler keeps working (falls through to on-demand or lastgood).
- Revert rate limits: zero the 3 new env vars or remove them; code defaults (20/20/120/2000) take over.
```

#### Pre-read

- `apps/worldview-web/src/components/dashboard/` (or wherever `MorningBriefCard` lives)
- `docs/services/rag-chat.md` (existing structure)
- `docs/services/api-gateway.md` (existing structure)

#### Validation gate

- [ ] Frontend `vitest` passes; no TS errors
- [ ] Docs render correctly in MkDocs (if applicable) — basic markdown syntax check
- [ ] worldview-gitops checklist is complete and unambiguous

#### Architecture compliance

- [ ] **R15 — docs updated**: every API/event/schema change above is documented
- [ ] No new code rules engaged (pure docs + UI)

#### Break impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| `MorningBriefCard.test.tsx` if existing test asserted exact prop shape | New `is_stale` prop | Add prop to test fixtures with default `false` |

#### Regression guardrails

- **Frontend platform hardening primitives** — use `useFormattedTimestamp` for date formatting (consistent with rest of app per MEMORY.md)
- **Bloomberg UI density** — match existing `MorningBriefCard` typography; small subdued badge, not a banner

---

## §5 — Cross-Cutting Concerns

- **Contract changes**:
  - `PublicBriefingResponse` gains `is_stale: bool = False` (additive — backward compatible)
  - `RateLimitMiddleware.__init__` signature gains 3 keyword args (caller updated in same wave)
- **Migration needs**: none (no DB schema changes)
- **Event flow changes**: none (no new Kafka topics)
- **Configuration changes**:
  - S9: 3 new env vars (+ existing one re-defaulted)
  - S8: 7 new env vars
  - 1 new docker-compose service (`rag-chat-brief-scheduler`)
- **Documentation updates**: 3 files updated + 1 new checklist (W3 tasks 02/03/04)
- **New Valkey artifacts**:
  - `active_users` sorted-set (S9 writes, S8 reads; auto-pruned 1/1000)
  - `briefing:morning:lastgood:{user_id}` key (S8 writes, S8 reads)

## §6 — Risk Assessment

- **Critical path**: W1 unblocks W2; W2 unblocks W3. No parallel opportunities (all 3 waves are small enough that serial execution is fine).
- **Highest risk task**: T-W2-04 (the worker). It depends on `execute_public_morning()` accepting a service JWT cleanly. If the use case rejects service JWTs, a small refactor is needed (budgeted as a 30-min sub-task within T-W2-04).
- **Rollback strategy**:
  - W1: if rate-limit changes mis-fire, revert the commit; defaults in code are safe (20/20/120/2000).
  - W2: kill switch via `RAG_CHAT_BRIEF_PREGEN_ENABLED=false`; on-demand path still works (regression to pre-plan behaviour).
  - W3: pure UI/docs; no runtime risk.
- **Testing gaps**:
  - No end-to-end test that exercises S9 → Valkey ZADD → S8 worker → fresh+lastgood write → handler stale fallback. Add as a manual smoke test in W2 validation gate; full integration test deferred (would need a multi-service test harness).

## §7 — Compounding Step

- **BP-549** already covers the orphan-helper pattern that applies to T-W1-02 (deleting `_FINANCIAL_MUTATION_LIMIT`). No new bug pattern required.
- **REVIEW_CHECKLIST.md** already has the orphan-prune item added in PLAN-0093 QA-7 (commit 55fbc2ed). Sufficient.
- **No new rule**: this plan uses existing patterns (APScheduler from alert service, port/adapter pattern, Valkey caching). R32 (Alembic numbers) is N/A — no migrations.
- **Compounding check**: no updates needed.
