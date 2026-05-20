# Backend Audit Report

**Generated**: 2026-05-19
**Services audited**: S1 portfolio, S2 market-ingestion, S3 market-data, S4 content-ingestion, S5 content-store, S6 nlp-pipeline, S7 knowledge-graph, S8 rag-chat, S9 api-gateway, S10 alert; libs/{common,contracts,messaging,ml-clients,observability,prompts,storage,tools}; infra/kafka/schemas
**Scope**: Read-only — no code was modified.

---

## Critical Findings (Top of Report)

The following issues must be addressed before any further frontend feature work. They are reproduced in full in the detailed sections.

### [DATA INTEGRITY RISK] BUG-001 — S6 SUPPRESS articles emit enriched events to S7
SUPPRESS-tier articles correctly skip extraction (HALT at `article_consumer.py:562`) but `_enqueue_enriched()` still emits `nlp.article.enriched.v1` regardless of `ml.final_path` (`article_consumer.py:649-666`). S7 receives empty enriched documents, pollutes the KG with dead-weight, and degrades graph query performance.

### [DATA INTEGRITY RISK] BUG-002 — S6 price-impact worker ignores routing_tier
`get_articles_needing_windows()` (`nlp-pipeline/infrastructure/nlp_db/repositories/impact_window.py:95-143`) selects ALL articles with resolved financial-instrument mentions, including SUPPRESS-tier. Price-impact scores for low-quality articles bias the composite routing score for future articles citing the same instruments — a feedback loop that propagates noise.

### [DATA INTEGRITY RISK] BUG-003 — S1 concurrent SnapTrade sync can double-count holdings
`brokerage_sync_worker.sync_cycle()` (`services/portfolio/src/portfolio/workers/brokerage_sync_worker.py:170-246`) loads active connections then iterates without per-connection locking. Two worker replicas can claim the same `BrokerageConnection` concurrently and replay transactions twice before the canonical snapshot upsert at L254-260 stabilizes. Brief double-counting window (5-60s) visible to user; if snapshot upsert fails, drift persists.

### [CRITICAL] BUG-004 — S9 rate limit bypass via middleware ordering
`RateLimitMiddleware` (`services/api-gateway/src/api_gateway/middleware.py:355-465`) runs after `OIDCAuthMiddleware`. The check `if user and user.get("user_id")` (L401) fails silently when `request.state.user` is never set by the auth middleware (some failure paths), falling through to unauthenticated IP-based bucket (L412). Combined with shared NAT/proxy buckets, this allows unauthenticated brute-force at 20 req/min per IP regardless of user count.

### [HIGH] BUG-005 — S9 JWKS rotation has no invalidation path
S9 builds its public JWKS once at startup (`services/api-gateway/src/api_gateway/app.py:137-145`) and serves it from `app.state.internal_jwks`. Backends cache S9's public key on their own startup. If S9's private key is rotated mid-life, backends continue accepting JWTs signed with the OLD key for the rest of their container lifetime. Note: the per-agent finding (L63-78 oidc.py) shows S9 backends DO have a single refresh-on-miss mechanism, which partially mitigates but does not solve forced rotation.

### [HIGH] LIB-001 — `processed_events` table grows unbounded
`processed_events` (created in e.g. `services/content-store/alembic/versions/0003_add_processed_events.py:17-23`) is the idempotency table used by every Kafka consumer via `BaseKafkaConsumer.is_duplicate()`. There is no TTL, no scheduled cleanup, and the `processed_at` index is never used by a DELETE job. At ~1M events/day this table grows by ~30M rows/month per database with no upper bound — disk pressure, btree degradation, and slow consumer startup over time.

---

## Required Changes (Frontend Waiting)

| ID | Item | Service | Effort | Blocking Frontend Feature |
|----|------|---------|--------|--------------------------|
| REQ-001 | Notification Preferences (channel + frequency per alert type) | S1 portfolio OR S10 alert | M | Settings page channel selection |
| REQ-002a | Mutation idempotency — POST /v1/portfolios | S1 | S | Frontend retry config (FR-8.1) |
| REQ-002b | Mutation idempotency — POST /v1/watchlists/{id}/members | S1 | S | Same |
| REQ-002c | Mutation idempotency — POST /v1/brokerage-connections/{id}/sync trigger | S1 | S | Same |
| REQ-002d | Mutation idempotency — POST /v1/feedback | S1 or S9 | S | Same |
| REQ-003 | Entity refresh trigger `POST /v1/entities/{entity_id}/refresh` | S7 (publishes to S6) | M | Manual re-enrich UI (MISS-007) |
| REQ-004 | `/v1/price/batch` partial-result schema | S3 market-data | S | Batch quote display consistency |

### REQ-001 — Notification Preferences (MISSING)
- No `NotificationPreferences` entity in S1 domain layer.
- No Alembic migration; closest existing is S1 migration 0004 `alert_preferences` table (enabled/disabled per alert type, NOT channel selection) and S10's `email_preferences` (digest scheduling only).
- No use cases, routes, or S9 proxy entries.
- **Gap**: distinguish "which alert types" (exists) from "how to receive them" (missing — in-app vs email vs push, per alert type, with frequency).
- **Recommended shape**:
  - Entity: `NotificationPreferences(user_id, alert_type, channel, enabled, frequency)`
  - `GET /v1/users/me/notification-preferences`
  - `PATCH /v1/users/me/notification-preferences/{alert_type}`
  - Owner: S1 (sits next to existing `alert_preferences`).

### REQ-002 — Mutation Idempotency

| Endpoint | Idempotent? | Mechanism | Risk |
|----------|-------------|-----------|------|
| POST /v1/portfolios | NO | none | HIGH |
| POST /v1/transactions | YES | `RecordTransactionUseCase` uses `idempotency` table + `create_if_not_exists` (`record_transaction.py:77-101`, L86, L232-244) | OK |
| POST /v1/watchlists/{id}/members | NO | entity_id-uniqueness only (`watchlist.py:229-369`) | HIGH |
| POST /v1/brokerage-connections/{id}/sync | PARTIAL | worker is idempotent via external_ref (`brokerage_sync_worker.py:359`); HTTP trigger lacks key | MED |
| POST /v1/feedback | NO | unconditional insert | MED |

Pattern is already proven in `RecordTransactionUseCase` — port it.

### REQ-003 — Entity Refresh
- S7 narrative trigger exists: `POST /api/v1/entities/{entity_id}/narratives/generate` (`knowledge_graph/api/narratives.py:111`), 1/hour rate limit.
- S6 article reprocess exists: `POST /reprocess/{article_id}` (`nlp_pipeline/api/routes/signals.py:243-244`).
- **Missing**: entity-level refresh that triggers re-embedding (S6) + re-description (S7) + unresolved-resolution.
- Recommended: `POST /v1/entities/{entity_id}/refresh` body `{ "refresh_type": "description"|"narrative"|"all" }`, publishes new `entity.refresh.v1` topic, 1/hour/user rate limit, returns 202 + job id.

### REQ-004 — Batch 404 Behavior
- `POST /v1/quotes/batch` (`market_data/api/routers/quotes.py:98-115`): returns dict `{instrument_id: QuoteResponse|None}` — clients can detect misses. **OK.**
- `GET /ohlcv/bulk` (`market_data/api/routers/ohlcv.py:144-168`): preserves input order, empty arrays for misses. **OK.**
- `POST /v1/price/batch` (`market_data/api/routers/price_snapshot.py:176-196`): returns `list[PriceSnapshotResponse]`, silently filters out missing instruments at L190-194. **GAP** — caller cannot tell which instruments are missing.

---

## Bugs Found

| ID | Severity | Service | Description | Risk | File:Line |
|----|----------|---------|-------------|------|-----------|
| BUG-001 | HIGH | S6 | SUPPRESS articles still emit enriched events | data-corruption | nlp-pipeline/.../article_consumer.py:649-666 |
| BUG-002 | HIGH | S6 | Price-impact worker ignores routing_tier | feedback-loop noise | nlp-pipeline/.../impact_window.py:95-143 |
| BUG-003 | HIGH | S1 | Concurrent SnapTrade sync race | data-corruption | portfolio/.../brokerage_sync_worker.py:170-246 |
| BUG-004 | CRITICAL | S9 | Rate-limit bypass via middleware order edge case | security | api-gateway/.../middleware.py:355-465 |
| BUG-005 | HIGH | S9 | JWKS rotation lacks invalidation | security | api-gateway/.../app.py:137-145 |
| BUG-006 | MED | S5 | URL tracking-param strip list incomplete (`_ga`, `igshid`, `_hsenc`, `_hsmi`) | dedup false-neg | content-store/.../stage_b_normalized.py:23-39 |
| BUG-007 | MED | S10 | WebSocket session ignores mid-stream token expiry | crash / silent disconnect | alert/.../routes.py:495-502, 510-537 |
| BUG-008 | LOW | S4 | All 4 source adapters share interval; no stagger/jitter | thundering herd | content-ingestion/.../scheduler.py:57-93 |
| BUG-009 | LOW | S2 | `is_backfill` flag not serialized in `MarketDatasetFetched` event | downstream alert noise | market-ingestion/.../events.py:56-88 |

### Verified OK (recorded so we don't re-check)
- **S6 routing weight sum**: module-level `assert sum(weights)≈1.0` at `routing.py:31-33`.
- **S8 HyDE isolation**: hypothesis text used only for query embedding, not in answer LLM context (`hyde_expander.py:100`).
- **S10 WebSocket scope**: `alerts:stream` scope enforced at `routes.py:481-488`.
- **S9 JWKS refresh-on-miss**: single refresh in `oidc.py:63-78` (partial mitigation for BUG-005).
- **S1 transaction idempotency**: full atomic dedup in `record_transaction.py:86`.
- **S1 cascade deletes**: FKs default to RESTRICT — no accidental orphan cascades (also means deletes need explicit cleanup; not a bug, but a behavior to remember).
- **S3 screener SQL injection**: `sort_by` whitelisted at L159-164; no dynamic field names from user input.
- **S5 MinHash config**: 4 bands × 32 rows × 128 perms ≈ 85% Jaccard threshold — well-tuned.
- **libs/messaging is_duplicate ordering**: duplicate check correctly precedes UoW + process (`base.py:440-479`) — BP-407 fix is in place.
- **libs/messaging outbox lease atomicity**: lease + publish are atomic (`base.py:418-437`); no dual-write violation.
- **libs/common UUIDv7**: time-sortable + monotonic within ms (`common/ids.py:33-45`).
- **libs/common UTC**: zero naked `datetime.now()` in libs or services (grep-verified).

---

## Shared Library Findings

| ID | Severity | Library | Description | File:Line |
|----|----------|---------|-------------|-----------|
| LIB-001 | HIGH | messaging | `processed_events` grows unbounded — no TTL/cleanup | services/content-store/alembic/versions/0003_add_processed_events.py:17-23 |
| LIB-002 | MED | messaging | Dead-letter publishing delegated to abstract `_dead_letter_impl()` — subclasses may persist only to Postgres, never emit to `*.dead-letter.v1` topic | libs/messaging/.../consumer/base.py:285-309 |
| LIB-003 | MED | messaging | OutboxDispatcher pure 5s polling, no LISTEN/NOTIFY — ~17k idle queries/day per dispatcher | libs/messaging/.../dispatcher/base.py:197, 451-470 |
| LIB-004 | MED | ml-clients | Fallback (DeepInfra→Ollama) not wired in adapter; each service implements its own | libs/ml-clients/.../deepinfra_embedding.py:72; deepseek_extraction.py:42 |
| LIB-005 | LOW | ml-clients | 429 classified as fatal, not retryable — consumer crashes on burst rate-limit | libs/ml-clients/.../deepinfra_embedding.py:123-130; deepinfra_description.py:284 |
| LIB-006 | LOW | storage | `put_bytes()` / `get_bytes()` accept arbitrary bucket names — no enum guard | libs/storage/.../s3_adapter.py:103-137 |
| LIB-007 | LOW | storage | ETag returned by S3 is discarded — claim-check consumers cannot verify integrity | libs/storage/.../s3_adapter.py:103-129 |

---

## Refactor Opportunities

| ID | Class | Service/Lib | Description | Effort |
|----|-------|-------------|-------------|--------|
| REF-001 | SHOULD | 9 services | `InternalJWTMiddleware` duplicated 9× (~2408 LOC total). Extract to `libs/observability/` with configurable skip-list. | M |
| REF-002 | COULD | api-gateway | `clients.py` is 1496 lines — HTTP clients, retry logic, error handling mixed. Extract retry strategies to `libs/common/`. | M |
| REF-003 | COULD | multiple | Pagination scattered across repos; consider `libs/contracts/pagination.py` (PaginationParams + PaginatedResponse). Low urgency. | S |
| REF-004 | SKIP | all | Health endpoint duplication — framework-adequate boilerplate. | N/A |
| REF-005 | SKIP | multiple | Tenant_id filter helpers — context-tied to domain models; extracting obscures filtering. | N/A |

---

## Test Coverage Gaps

| Service | Unit | Integration | Class |
|---------|------|-------------|-------|
| alert | 60 | 8 | OK |
| api-gateway | 41 | 3 | MEDIUM — proxies 9 services with only 3 integration tests |
| content-ingestion | 183 | 11 | OK |
| content-store | 669 | 10 | OK |
| **intelligence-migrations** | **6** | **0** | **HIGH** — owns all DDL for S6+S7 shared DB |
| knowledge-graph | 217 | 12 | OK |
| market-data | 167 | 13 | OK |
| market-ingestion | 1320 | 6 | MEDIUM — heavy unit/mock, thin real-Kafka |
| nlp-pipeline | 286 | 7 | MEDIUM |
| portfolio | 90 | 12 | OK |
| rag-chat | 108 | 4 | MEDIUM |

**Critical gap**: `intelligence-migrations` has zero integration tests despite owning all DDL for the S6+S7 shared `intelligence_db`. A bad migration cannot be caught by any service-level test.

---

## Migration State

All services with their own DB have **linear, single-head Alembic chains** (no diverged forks). `api-gateway` (stateless) and `knowledge-graph` (shares intelligence_db) correctly have no alembic dir. No TODO/FIXME found in sampled latest migrations.

| Service | Latest rev |
|---------|-----------|
| alert | 0009 |
| content-ingestion | 0007 |
| content-store | 0006 |
| intelligence-migrations | 0038 |
| market-data | 016 |
| market-ingestion | 0013 |
| nlp-pipeline | 0019 (consumes intelligence_db) |
| portfolio | 0017 |
| rag-chat | 0007 |

---

## Schema Drift

Spot-checked `nlp.article.enriched.v1.avsc` and `entity.canonical.created.v1.avsc`:
- `nlp.article.enriched.v1`: producer (`nlp-pipeline/.../blocks/enriched_event.py:184-186`) and consumer (`knowledge-graph/.../enriched_consumer.py:199-213`) are aligned. Recent additions (`raw_relations_json`, `raw_events_json`, `source_name`, `tenant_id`) all have defaults. **NO DRIFT.**
- Forward-compat is maintained via the Schema Registry and Avro defaults.

**Recommendation**: maintain current discipline; no schema drift work needed in this pass.

---

## Environment Variable Hygiene
- **No crash-on-missing risks** found — all `os.environ` reads use `.get()` with default or are wrapped in try/except.
- Provider adapters (Finnhub L218, Polygon L223, Alpaca L475) carry explicit comments forbidding logging of URLs that contain API tokens. No accidental secret-logging found in scan.

---

## Plan

See `.claude/backend-audit/BACKEND-PLAN.md` for the dispatchable implementation plan.
