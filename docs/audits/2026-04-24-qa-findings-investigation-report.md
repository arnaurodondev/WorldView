# Investigation Report: QA Findings Deep Analysis & Production Readiness Decisions

**Date**: 2026-04-24
**Source**: `docs/audits/2026-04-23-qa-full-post-bugfix-report.md`
**Branch**: `feat/content-ingestion-wave-a1`
**Scope**: 11 findings (F-001, F-002, F-003, F-007, F-009, F-010, F-013, F-014, F-015, F-016, F-020)
**Method**: 5 parallel investigation agents (Security, Architecture, Data Contract, Reliability, Hygiene)

---

## 1. Executive Summary

The 28-finding QA report contains **2 blocking security gaps**, **1 critical architecture violation**, **1 critical data contract issue**, **2 major operational risks**, and **5 minor/NIT items**. None were introduced by recent commits — all are pre-existing on the branch.

**Key decisions required:**

| # | Decision | Recommendation | Priority |
|---|----------|---------------|----------|
| 1 | Tenant isolation strategy for nlp-pipeline | Partial enforcement now (watchlist check + skip_verification guard); full schema migration in next wave; ADR for platform-vs-tenant-scoped articles | P1 |
| 2 | Null volume semantic model | Change `CanonicalOHLCVBar.volume` to `int | None`; keep DB column NOT NULL with explicit coercion at storage boundary; document historical data caveat | P2 |
| 3 | `skip_verification` existence | Keep the flag but add `model_validator` in all 9 service configs that rejects `True` when `APP_ENV=production` | P1 |
| 4 | Architecture boundary violations | F-001: MetricsPort Protocol + adapter (matches content-ingestion pattern); F-013: delete dead import immediately, schedule use-case refactor | P2 |
| 5 | NIT issues | Fix F-015 + F-016 in one commit; **reject F-020** — `rounded-[2px]` is intentional and documented | P3 |

**Proposed timeline**: 3 implementation waves over 2 sprints, no ADR required for any finding except the platform-vs-tenant article scoping question (F-009).

---

## 2. Finding-by-Finding Deep Analysis

### F-009: Missing tenant_id filter in nlp-pipeline news queries — BLOCKING

**Severity**: BLOCKING | **Risk**: Security (OWASP A01) | **Blast radius**: Full cross-tenant data leakage

#### Confirmed behavior
- `get_top_news()` and `get_entity_articles()` in `news_query.py` query `document_source_metadata`, `article_impact_windows`, `routing_decisions`, and `entity_mentions` with **zero** `WHERE tenant_id` predicate
- The `InternalJWTMiddleware` extracts `tenant_id` from JWT and sets `request.state.tenant_id` — but the routes in `news.py` and `signals.py` never read it
- DB schema confirmed: **none of the four tables have a `tenant_id` column** (checked all Alembic migrations 0001–0009)
- `GET /api/v1/news/top` is proxied by S9 using a system JWT (nil-UUID tenant) — designed as a public/global endpoint

#### Time-horizon impact
| Horizon | Impact |
|---------|--------|
| 0–3 mo (thesis) | Zero — single tenant |
| 3–12 mo (early SaaS) | CRITICAL — first second tenant creates immediate data leakage |
| 12+ mo (scaled SaaS) | Regulator-level — financial intelligence data subject to MiFID II / SEC handling obligations |

#### Architectural insight
The correct tenant boundary is at the **watchlist/entity relationship level**, not at the article level. Articles are public-domain news ingested globally. What is tenant-sensitive is: (a) which entities a tenant watches, (b) the routing decisions and impact scores, and (c) RAG chat history. `entity_mentions` reveals watchlist composition — this is the table that needs tenant isolation first.

#### Recommendation
- **Now**: Add watchlist ownership check at the route level for `GET /entities/{entity_id}/articles` (see F-010)
- **Next wave**: Add nullable `tenant_id UUID` to `entity_mentions`; stamp from Kafka envelope; add query filter with `IS NULL` fallback for legacy rows
- **ADR required**: Whether `document_source_metadata`, `routing_decisions`, and `article_impact_windows` are platform-global or tenant-scoped
- **Leave `GET /news/top` as-is**: System JWT, platform-global feed — document the design decision

---

### F-010: No entity ownership check in entity articles endpoint — BLOCKING

**Severity**: BLOCKING | **Risk**: Security (OWASP A01) | **Blast radius**: Cross-tenant entity intelligence enumeration

#### Confirmed behavior
- `GET /api/v1/entities/{entity_id}/articles` accepts arbitrary UUID, passes directly to query with no tenant check
- UUIDs are UUIDv7 (time-ordered, partially predictable) — enumeration is feasible
- Combined with F-009, any authenticated user can access all entities and all articles for those entities across the entire platform

#### Recommendation: Watchlist membership check (immediate)
```python
watchlist_cache: WatchlistCache = request.app.state.watchlist_cache
tenant_id = request.state.tenant_id
if tenant_id and not await watchlist_cache.is_watched(tenant_id, entity_id):
    raise HTTPException(status_code=404, detail="Entity not found")
```
- Uses existing `WatchlistCache` in `app.state` (populated from Kafka events)
- Fail-open if Valkey unavailable (log for ops visibility) — authoritative store is S1
- Additive, reversible, no schema migration

**Decision type**: Immediate bugfix

---

### F-007: `skip_verification` has no production safety guard — MAJOR

**Severity**: MAJOR | **Risk**: Security (OWASP A07) | **Blast radius**: All 9 backend services

#### Confirmed behavior
- `internal_jwt_skip_verification: bool = False` exists in **all 9 service configs** (alert, rag-chat, market-data, content-ingestion, market-ingestion, portfolio, nlp-pipeline, content-store, knowledge-graph)
- When `True` AND `public_key is None`, `jwt.decode()` runs with `verify_signature=False` — accepts any token regardless of signature, issuer, or expiry
- No `model_validator` or environment check prevents enabling in production
- The flag only activates when JWKS also fails to load — but during degraded state (S9 unreachable), an operator setting this flag disables auth entirely

#### Recommendation: Environment-aware validator (Option A)
```python
@model_validator(mode="after")
def _guard_skip_verification(self) -> Settings:
    import os
    env = os.getenv("APP_ENV", "").lower()
    if self.internal_jwt_skip_verification and env == "production":
        raise ValueError(
            "internal_jwt_skip_verification MUST NOT be enabled in production. "
            "Set APP_ENV != 'production' or remove the flag."
        )
    return self
```
- 3-line change per service config (9 files)
- Zero breaking changes — only fails at startup in production
- Tests use `Settings(internal_jwt_skip_verification=True)` directly (no APP_ENV set) — unaffected

**Decision type**: Immediate bugfix

---

### F-001: rag-chat application layer imports infrastructure prometheus — CRITICAL

**Severity**: CRITICAL | **Risk**: Architecture debt | **Blast radius**: Architecture test gate red (2 tests)

#### Confirmed behavior
- `chat_orchestrator.py` imports 6 Prometheus metrics from `rag_chat.infrastructure.metrics.prometheus` (lines 24–31)
- `create_thread.py` imports `rag_thread_count` gauge (line 12)
- Both are top-level runtime imports violating `LAYER-APP-ISOLATION`
- Mid-pipeline metrics (per-retrieval-item histograms, per-contradiction labels) cannot be moved to the route layer — they require access to intermediate generator state

#### Recommendation: MetricsPort Protocol + PrometheusRagMetrics adapter (Option A)
- Create `application/ports/metrics.py` with `RagMetricsPort(Protocol)` — 7 abstract methods
- Create `infrastructure/metrics/adapter.py` with `PrometheusRagMetrics` wrapping existing singletons
- Inject via `ChatOrchestrator.__init__(metrics: RagMetricsPort)` and DI factory
- Pattern already established by `content-ingestion/application/ports/metrics.py`
- Architecture gate goes green; existing prometheus.py singletons untouched

**Why not Option B** (move metrics to route layer): Mid-pipeline metrics in `chat_orchestrator` (step 5A–5I per-item histograms, step 9 contradiction labels) cannot be derived from the final return value — they require access to per-item data inside the streaming generator.

**Decision type**: Planned refactor (~80 lines new code, 2 test patch targets updated)

---

### F-013: Portfolio API imports SqlAlchemyUnitOfWork — MAJOR

**Severity**: MAJOR | **Risk**: Architecture debt | **Blast radius**: Latent ImportError risk; gate NOT currently failing

#### Confirmed behavior
- `brokerage_connections.py:226` imports `SqlAlchemyUnitOfWork` inside a `try:` block (lazy import)
- Line 262: `_ = SqlAlchemyUnitOfWork` — unused assignment to suppress linter warning
- **The import is dead code** — `SqlAlchemyUnitOfWork` is never used functionally; the worker receives `session_factory` from `app.state` and constructs its own UoW internally
- The architecture gate does NOT catch this because the test only checks module-level imports (not function-body lazy imports)

#### Recommendation: Two phases
- **Phase 1 (immediate)**: Delete lines 226 and 262 — pure dead code removal, zero risk, zero test changes
- **Phase 2 (planned refactor)**: Extract `_run_single_sync` logic into a `TriggerBrokerageSync` use case; make `worker._sync_connection` a public method `worker.sync_one()`

**Decision type**: Phase 1 = immediate bugfix; Phase 2 = planned refactor

---

### F-002: Null volume coercion breaks contract round-trip — CRITICAL

**Severity**: CRITICAL | **Risk**: Data correctness | **Blast radius**: All OHLCV bars with null volume (off-hours, settlement, closed-market days)

#### Confirmed behavior
- `CanonicalOHLCVBar.from_dict()` at `ohlcv.py:57`: `volume = int(raw_volume) if raw_volume is not None else 0`
- `to_dict()` serializes `"volume": 0` — null signal permanently lost
- DB column `ohlcv_bars.volume` is `NUMERIC(24,8) NOT NULL server_default="0"`
- Sibling model `CanonicalQuote` correctly uses `volume: int | None` — internal inconsistency
- `MarketDataClient` in nlp-pipeline already declares `volume: int | None` — prepared for null
- `PriceImpactLabellingWorker` receives `volume=0` instead of `None` for null-volume bars

#### Data flow trace
```
EODHD (volume: null)
  → CanonicalOHLCVBar.from_dict()  ← COERCION: null → 0
  → S3 canonical bucket (JSONL: "volume": 0)
  → OHLCVConsumer → ohlcv_bars table (volume: 0, NOT NULL)
  → OHLCVBarResponse API (volume: 0)
  → Frontend chart (zero-height bar)
  → PriceImpactLabellingWorker (volume: Decimal(0) not None)
  [null signal permanently lost at step 1]
```

#### Analytics impact
- Average daily volume calculations deflated by false zero-volume bars
- Abnormal volume signals contaminated (PRD-0020 Block 5 price_impact)
- Backtesting across international ETFs with data gaps produces statistically significant bias
- No recovery path for already-coerced historical data without re-ingesting from bronze

#### Recommendation: Scoped Option B — `volume: int | None` in contract, NOT NULL preserved in DB

1. Change `CanonicalOHLCVBar.volume` to `int | None`; `from_dict` returns `None` for null
2. **Keep** DB column `NOT NULL server_default="0"` — avoid high-risk hypertable migration
3. Map `None → 0` explicitly at `PgOHLCVRepository.bulk_upsert_with_priority` (localized coercion)
4. Expose `OHLCVBarResponse.volume: int | None` to API surface
5. `MarketDataClient` already handles `int | None` — no change needed
6. Bump `OHLCV_SCHEMA_VERSION` to 2
7. Document historical data caveat in BUG_PATTERNS.md under BP-182

**Why not Option A** (`volume_reported: bool`): Redundant — `int | None` already encodes the signal in one field. The boolean doubles the cognitive load without adding information. `CanonicalQuote` already uses `int | None` for the same concept.

**Why not full Option B** (nullable DB column): TimescaleDB hypertable ALTER COLUMN NOT NULL → NULLABLE requires careful locking analysis. Historical `volume=0` rows are permanently ambiguous regardless. Risk:benefit ratio is poor.

**Decision type**: Planned refactor (1 wave, ~6 files)

---

### F-003: JWKS startup failure creates zombie pods — MAJOR

**Severity**: MAJOR | **Risk**: Operational reliability | **Blast radius**: All 9 services with InternalJWTMiddleware

#### Confirmed behavior
- `InternalJWTMiddleware.startup()` retries 3x then logs ERROR and **returns without raising**
- `_public_key` remains `None`; service starts; readiness probes pass (health routes skip JWT)
- All authenticated requests return 503 — service appears healthy but is non-functional
- **All 9 backend services are vulnerable** (confirmed identical startup code in each)
- No service's `/readyz` checks `_internal_jwt_public_key` state

| Service | Zombie risk? |
|---------|-------------|
| alert (S10) | YES |
| rag-chat (S8) | YES |
| market-data (S3) | YES |
| content-ingestion (S4) | YES |
| market-ingestion (S2) | YES |
| portfolio (S1) | YES |
| nlp-pipeline (S6) | YES |
| content-store (S5) | YES |
| knowledge-graph (S7) | YES |

#### Recommendation: Hard crash at startup (Option A)
```python
# In startup(), after all retries exhausted:
raise RuntimeError(
    f"JWKS startup failed after 3 attempts — cannot start without public key ({self._jwks_url})"
)
```
- 1-line change in `startup()` across 9 services
- Docker Compose: add `depends_on: api-gateway: condition: service_healthy` to all 9 services
- For future K8s: add `/readyz` JWKS check on top (Option C) to enable graceful pod drain

**Why hard crash over readyz-only**: In Docker Compose there is no readiness-gated traffic routing. A readyz-only fix provides zero protection. A crash triggers Docker's restart policy and surfaces the failure clearly.

**Decision type**: Immediate bugfix

**Cross-cutting observation**: `InternalJWTMiddleware` is copy-pasted across all 9 services. Every fix must be applied 9 times. Long-term: extract to `libs/auth-middleware` shared library (separate refactor ADR).

---

### F-014: Whitespace-only `read_url` bypass — MINOR

**Severity**: MINOR | **Risk**: Operational reliability | **Blast radius**: rag-chat startup

#### Confirmed behavior
- `SecretStr("  ")` is truthy → falls through to `create_async_engine("  ")` → `ArgumentError` at startup
- Current failure mode is a hard crash (actually better than silent misbehavior)
- Same `SecretStr | None` pattern exists in several other services' session factories

#### Recommendation: Pydantic field validator on `database_url_read` (Option B)
```python
@field_validator("database_url_read", mode="before")
@classmethod
def _coerce_empty_read_url(cls, v: object) -> object:
    if isinstance(v, str) and not v.strip():
        return None
    return v
```
- Enforces invariant at settings/validation layer — correct architectural placement
- Apply to all services with `database_url_read: SecretStr | None`

**Decision type**: Planned refactor (not urgent; current failure mode is a startup crash, not silent misbehavior)

---

### F-017: Missing unit tests for session factory BP-179 paths — MINOR

**Severity**: MINOR | **Risk**: Correctness / regression coverage | **Blast radius**: rag-chat

#### Confirmed behavior
- No `test_session_factory.py` exists — zero coverage of `create_rag_session_factory`
- BP-179 was a production bugfix with no regression test (violates R1)

#### Minimal test set required (6 tests)

| Test | Input | Expected |
|------|-------|----------|
| TC-1 | `database_url_read=None` | `read_engine is write_engine` |
| TC-2 | `database_url_read=SecretStr("")` | `read_engine is write_engine` (BP-179 regression) |
| TC-3 | `database_url_read=SecretStr("  ")` | `read_engine is write_engine` (F-014 regression) |
| TC-4 | Same host/port/db | `read_engine is write_engine` |
| TC-5 | Distinct host | `read_engine is not write_engine` |
| TC-6 | Trailing slash normalization | `_same_db_endpoint` returns True |

All pure unit tests — mock `create_async_engine`, no DB connection needed.

**Decision type**: Immediate bugfix (R1 compliance)

---

### F-015: Stale Bloomberg Dark comment — NIT

**Confirmed**: `select.tsx:154-155` references `#0A0E14 (Bloomberg Dark)` — retired palette. Active is `#09090B (Terminal Dark)`.

**Recommendation**: Fix immediately — 1-line edit, zero risk.

---

### F-016: Redundant `@pytest.mark.asyncio` markers — MINOR

**Confirmed**: `asyncio_mode=auto` in `pyproject.toml` makes the markers redundant. `--strict-markers` is set but `asyncio` is registered by the plugin itself.

**Recommendation**: Fix immediately — replace with `@pytest.mark.unit` (2-line edit, zero risk).

---

### F-020: `rounded-[2px]` vs `rounded-lg` — MINOR

**Investigation result: Finding is INCORRECT. Do NOT apply the suggested fix.**

- `globals.css` sets `--radius: 0.125rem` (2px). Currently `rounded-lg` = `rounded-[2px]` = 2px
- BUT `card.tsx:13-16` contains an explicit comment: `"rounded-[2px] is an explicit override to bypass Tailwind's radius scale lookup"` — design intent is immunity to `--radius` changes
- 50+ components use `rounded-[2px]` uniformly — `rounded-lg` would introduce coupling to `--radius` and create inconsistency if the token is ever updated
- The codebase deliberately chose the explicit form

**Recommendation**: Close as "wontfix / by design". Reference `card.tsx` rationale.

---

## 3. Option Analysis Matrix

| Finding | Option A | Option B | Option C | Recommended |
|---------|----------|----------|----------|-------------|
| **F-009** (tenant filter) | RLS policies (high effort, high isolation) | App-layer `tenant_id` column (medium effort, adequate) | Schema-per-tenant (very high, rejected) | **B** (now) → A (long-term) |
| **F-010** (entity ownership) | Watchlist membership check (low effort, precise) | Tenant-scoped `entity_mentions` (medium, subsumes F-009) | Obscurity (rejected — UUIDv7 enumerable) | **A** (now) + B (follow-on) |
| **F-007** (skip_verification) | Config validator per service (low effort) | Middleware constructor check (low, weaker placement) | Remove flag entirely (medium, cleanest) | **A** (now) → C (later) |
| **F-001** (rag-chat metrics) | MetricsPort Protocol + adapter (medium) | Move metrics to route layer (blocked by mid-pipeline metrics) | Allowlist exception (trivial, weakens gate) | **A** |
| **F-013** (portfolio import) | Delete dead import (trivial) | Extract use case (medium) | — | **A** (now) + **B** (later) |
| **F-002** (null volume) | `volume_reported: bool` flag (medium, redundant) | `int \| None` with DB NOT NULL preserved (medium, correct) | Document and do nothing (zero effort, accumulates debt) | **B** (scoped) |
| **F-003** (zombie pod) | Hard crash at startup (low) | Crash + readyz check (medium, better for K8s) | Readyz-only (low, useless in Docker Compose) | **A** (now) + B (K8s migration) |
| **F-014** (whitespace URL) | Strip in session factory (trivial) | Pydantic validator (low, correct layer) | — | **B** |
| **F-017** (missing tests) | 6 unit tests (low) | — | — | **A** |

---

## 4. Recommended Decision Set

### P0 — Before next merge to main

| # | Finding | Action | Effort | Files |
|---|---------|--------|--------|-------|
| 1 | F-007 | Add `model_validator` to all 9 service configs | Low | 9 `config.py` files |
| 2 | F-010 | Add watchlist ownership check in `signals.py` | Low | 1 route file + dependency |
| 3 | F-003 | Hard crash on JWKS failure in `startup()` | Low | 9 `internal_jwt.py` files + docker-compose |
| 4 | F-013 Phase 1 | Delete dead `SqlAlchemyUnitOfWork` import | Trivial | 1 file, 2 lines |

### P1 — Within current sprint

| # | Finding | Action | Effort | Files |
|---|---------|--------|--------|-------|
| 5 | F-001 | MetricsPort Protocol + PrometheusRagMetrics adapter | Medium | 4 new/modified files |
| 6 | F-017 | Add 6 session factory unit tests | Low | 1 new test file |
| 7 | F-014 | Add pydantic field validator for whitespace URL | Low | N service configs |
| 8 | F-015 + F-016 | Fix stale comment + redundant markers | Trivial | 2 files |

### P2 — Next sprint (planned refactor wave)

| # | Finding | Action | Effort | Files |
|---|---------|--------|--------|-------|
| 9 | F-002 | `CanonicalOHLCVBar.volume: int \| None` + storage boundary coercion | Medium | ~6 files |
| 10 | F-009 | Add nullable `tenant_id` to `entity_mentions` + query filter | Medium | migration + consumer + repo |
| 11 | F-013 Phase 2 | Extract `TriggerBrokerageSync` use case | Medium | 3 files |

### Rejected

| Finding | Why |
|---------|-----|
| F-020 | `rounded-[2px]` is intentional and documented — wontfix |

---

## 5. Proposed Implementation Waves

### Wave 1: Security Hardening (P0, ~1 day)

**Scope**: F-007 + F-010 + F-003 + F-013 Phase 1

| Task | Detail |
|------|--------|
| F-007 | Add `_guard_skip_verification` model_validator to 9 service configs |
| F-010 | Add `WatchlistCache.is_watched()` check in `signals.py` entity articles route |
| F-003 | Change `startup()` from log-and-return to `raise RuntimeError` in 9 services |
| F-003 | Add `depends_on: api-gateway: condition: service_healthy` in docker-compose |
| F-013 | Delete dead import lines 226 + 262 in `brokerage_connections.py` |
| Tests | Unit test for skip_verification validator; test for watchlist check 404; test for startup RuntimeError; verify portfolio tests still pass |

**Validation gate**: All 4,206 backend tests pass; ruff + mypy clean; docker-compose cold-start succeeds.

### Wave 2: Architecture & Quality (P1, ~1 day)

**Scope**: F-001 + F-017 + F-014 + F-015 + F-016

| Task | Detail |
|------|--------|
| F-001 | Create `application/ports/metrics.py` with `RagMetricsPort(Protocol)` |
| F-001 | Create `infrastructure/metrics/adapter.py` with `PrometheusRagMetrics` |
| F-001 | Inject port into `ChatOrchestrator.__init__` and `CreateThreadUseCase` |
| F-001 | Update 2 test patch targets to use mock port |
| F-017 | Create `tests/unit/infrastructure/test_session_factory.py` with 6 tests |
| F-014 | Add `@field_validator("database_url_read")` to rag-chat + other service configs |
| F-015 | Update stale Bloomberg Dark comment → Terminal Dark in select.tsx |
| F-016 | Replace `@pytest.mark.asyncio` with `@pytest.mark.unit` at lines 719, 744 |

**Validation gate**: Architecture test gate passes (2 previously-red tests go green); all tests pass; ruff + mypy clean.

### Wave 3: Data Contract & Tenant Schema (P2, ~2 days)

**Scope**: F-002 + F-009 + F-013 Phase 2

| Task | Detail |
|------|--------|
| F-002 | Change `CanonicalOHLCVBar.volume` to `int \| None` |
| F-002 | Update `from_dict` to return `None` for null volume |
| F-002 | Map `None → 0` at `PgOHLCVRepository.bulk_upsert_with_priority` |
| F-002 | Expose `OHLCVBarResponse.volume: int \| None` |
| F-002 | Bump `OHLCV_SCHEMA_VERSION` to 2; update BUG_PATTERNS.md |
| F-009 | Write ADR for platform-global vs tenant-scoped articles |
| F-009 | Alembic migration: add nullable `tenant_id UUID` to `entity_mentions` |
| F-009 | Update article consumer to stamp `tenant_id` from Kafka envelope |
| F-009 | Add `AND (em.tenant_id IS NULL OR em.tenant_id = :tenant_id)` to SQL |
| F-009 | Add index `(tenant_id, resolved_entity_id)` on `entity_mentions` |
| F-013 | Extract `TriggerBrokerageSync` use case; make `sync_one()` public |

**Validation gate**: All tests pass; schema compatibility check passes; volume-null round-trip test added; tenant filter integration test added.

---

## 6. Required ADR List

| ADR | Finding | Question | Decision needed by |
|-----|---------|----------|--------------------|
| ADR-TENANT-001 | F-009 | Are `document_source_metadata`, `routing_decisions`, and `article_impact_windows` platform-global or tenant-scoped? | Before Wave 3 |

**Recommendation for ADR-TENANT-001**: Articles are platform-global (public-domain news, ingested globally). `entity_mentions` and downstream derived intelligence should be tenant-scoped (reveals watchlist composition). `routing_decisions` and `article_impact_windows` are platform-level NLP processing — not tenant-specific. Tenant boundary at the watchlist/entity relationship level.

**No ADR required for**:
- F-002 (aligns to existing `CanonicalQuote` pattern)
- F-001 (follows established `content-ingestion` MetricsPort pattern)
- F-003, F-007, F-013, F-014 (standard bugfixes / refactors)

**Future ADR (not blocking)**:
- Extract `InternalJWTMiddleware` from 9 copy-pasted files into `libs/auth-middleware` shared library

---

## 7. Test and Validation Plan

### New tests required

| Finding | Test | Type | Location |
|---------|------|------|----------|
| F-007 | `test_skip_verification_blocked_in_production` | Unit | Each service's `test_config.py` |
| F-010 | `test_entity_articles_returns_404_for_unwatched_entity` | Unit | `nlp-pipeline/tests/unit/api/` |
| F-010 | `test_entity_articles_succeeds_for_watched_entity` | Unit | Same |
| F-003 | `test_startup_raises_on_jwks_failure` | Unit | Each service's `test_internal_jwt.py` |
| F-001 | Update 2 existing tests to inject mock `RagMetricsPort` | Unit | `rag-chat/tests/unit/` |
| F-017 | 6 session factory path tests (TC-1..TC-6) | Unit | `rag-chat/tests/unit/infrastructure/test_session_factory.py` |
| F-002 | `test_ohlcv_bar_null_volume_preserved_in_canonical` | Unit | `libs/contracts/tests/` |
| F-002 | `test_ohlcv_bar_null_volume_coerced_at_storage_boundary` | Unit | `market-data/tests/unit/` |
| F-009 | `test_entity_articles_filtered_by_tenant` | Integration | `nlp-pipeline/tests/integration/` |

### Regression checks per wave

| Wave | Gate |
|------|------|
| Wave 1 | `pytest` all 10 services + 6 libs (4,206+); ruff; mypy; docker-compose cold-start |
| Wave 2 | Same + architecture tests all green (0 failures, currently 2) |
| Wave 3 | Same + Avro schema compatibility; Alembic upgrade/downgrade round-trip |

---

## 8. Go-Forward Roadmap

```
Week 1 (current sprint)
├── Wave 1: Security Hardening [P0]
│   ├── F-007: skip_verification guard (9 files)
│   ├── F-010: watchlist ownership check (1 route)
│   ├── F-003: JWKS hard crash (9 files + docker-compose)
│   └── F-013 Phase 1: dead import removal (2 lines)
│
├── Wave 2: Architecture & Quality [P1]
│   ├── F-001: MetricsPort + adapter
│   ├── F-017: session factory tests
│   ├── F-014: whitespace URL validator
│   └── F-015 + F-016: comment + marker fix
│
Week 2 (next sprint)
├── ADR-TENANT-001: Article scoping decision
├── Wave 3: Data Contract & Tenant Schema [P2]
│   ├── F-002: volume int|None
│   ├── F-009: entity_mentions tenant_id
│   └── F-013 Phase 2: use case extraction
│
Future (not blocking)
├── ADR: Extract InternalJWTMiddleware to libs/auth-middleware
├── F-009 Option A follow-on: PostgreSQL RLS if scaling to 100+ tenants
└── F-020: Closed — wontfix (by design)
```

### Success criteria for "production-ready" on these findings
- [ ] All 9 services reject `skip_verification=True` when `APP_ENV=production`
- [ ] Entity articles endpoint returns 404 for unwatched entities
- [ ] All 9 services crash on JWKS failure instead of starting as zombies
- [ ] Architecture test gate: 0 failures (currently 2)
- [ ] `CanonicalOHLCVBar.volume` is `int | None` with historical data caveat documented
- [ ] `entity_mentions` has `tenant_id` column with query-level filtering
- [ ] Session factory has 6 regression tests covering BP-179 paths
- [ ] ADR-TENANT-001 resolves platform-global vs tenant-scoped articles

---

---

## 9. Remediation Status

All 11 findings have been resolved. Implementation complete on branch `feat/content-ingestion-wave-a1`.

| Finding | Severity | Option | Status | Summary |
|---------|----------|--------|--------|---------|
| F-009 | BLOCKING | B | **FIXED** | Added nullable `tenant_id` column to `entity_mentions` + query filter with `IS NULL` fallback for legacy rows. ADR-TENANT-001 documents the platform-global vs tenant-scoped article scoping decision (`docs/adrs/ADR-TENANT-001-article-scoping.md`). BP-190. |
| F-010 | BLOCKING | A+B | **FIXED** | Added watchlist ownership guard (`WatchlistCache.is_watched()`) at the route level for `GET /entities/{id}/articles`. Returns 404 for unwatched entities. Tenant-scoped `entity_mentions` query filter added (subsumes F-009). BP-191. |
| F-007 | MAJOR | A | **FIXED** | Added `@model_validator(mode="after")` named `_guard_skip_verification` to all 9 service `config.py` files. Rejects `internal_jwt_skip_verification=True` when `APP_ENV=production`. BP-187. |
| F-003 | MAJOR | B | **FIXED** | `InternalJWTMiddleware.startup()` now raises `RuntimeError` after all retries exhausted (crashes the process). `/readyz` in all 9 services checks JWKS public key availability. BP-188. |
| F-014 | MINOR | B | **FIXED** | Added `@field_validator("database_url_read", mode="before")` to coerce whitespace-only strings to `None` at the settings validation layer. |
| F-001 | CRITICAL | A | **FIXED** | Created `RagMetricsPort` Protocol (`application/ports/metrics.py`) with 7 abstract methods. Created `PrometheusRagMetrics` adapter (`infrastructure/metrics/adapter.py`). Injected via `ChatOrchestrator.__init__` and `CreateThreadUseCase`. Architecture gate now passes. |
| F-013 | MAJOR | B | **FIXED** | Extracted `TriggerBrokerageSync` use case from API route layer. Removed dead `SqlAlchemyUnitOfWork` import. Made `worker.sync_one()` a public method. |
| F-002 | CRITICAL | B | **FIXED** | Changed `CanonicalOHLCVBar.volume` to `int | None`. `from_dict()` preserves null. `None -> 0` coercion localized to `PgOHLCVRepository.bulk_upsert_with_priority` (storage boundary). DB column remains NOT NULL. BP-189. |
| F-017 | MINOR | A | **FIXED** | Added 6 session factory unit tests (TC-1 through TC-6) covering `create_rag_session_factory` paths including BP-179 regression. |
| F-015 | NIT | fix | **FIXED** | Updated stale comment: `Bloomberg Dark` -> `Terminal Dark` in `select.tsx`. |
| F-016 | NIT | fix | **FIXED** | Removed redundant `@pytest.mark.asyncio` markers (already covered by `asyncio_mode=auto`). |
| F-020 | MINOR | wontfix | **WONTFIX (by design)** | `rounded-[2px]` is an intentional override to bypass Tailwind's radius scale lookup. Documented in `card.tsx:13-16`. 50+ components use this pattern uniformly. |

### New documentation artifacts

| Artifact | Path |
|----------|------|
| ADR-TENANT-001 | `docs/adrs/ADR-TENANT-001-article-scoping.md` |
| BP-187 through BP-191 | `docs/BUG_PATTERNS.md` (5 new entries) |
| NLP pipeline tenant isolation | `docs/services/nlp-pipeline.md` (new section) |
| Rag-chat RagMetricsPort + readyz | `docs/services/rag-chat.md` (updated architecture) |
| Portfolio TriggerBrokerageSync | `docs/services/portfolio.md` (new use case) |

---

*Report generated by 5 parallel investigation agents. All findings verified against source code, not assumed from QA report descriptions.*
