# Backend Implementation Plan

**Source**: `.claude/backend-audit/BACKEND-AUDIT-REPORT.md`
**Generated**: 2026-05-19
**Format**: Dependency-ordered waves. Subagents should be dispatched wave-by-wave; tasks within a wave can be parallelized unless `Blocks` says otherwise.

---

## Wave 0 — Required Changes (Unblocks Frontend)

### TASK-W0-01: Implement Notification Preferences (REQ-001)
**Type**: impl + migration
**Service**: S1 portfolio
**Files**:
- `services/portfolio/src/portfolio/domain/notification_preferences.py` (new)
- `services/portfolio/src/portfolio/application/use_cases/notification_preferences.py` (new — Get + Update)
- `services/portfolio/src/portfolio/infrastructure/repositories/notification_preferences_repo.py` (new)
- `services/portfolio/src/portfolio/api/routes/users.py` (extend, or new file)
- `services/portfolio/alembic/versions/0018_notification_preferences.py` (new)
- `services/api-gateway/src/api_gateway/routes/portfolio.py` (proxy paths)
- `services/portfolio/tests/{unit,integration}/test_notification_preferences*.py`

**Description**: Add `notification_preferences` table keyed by `(tenant_id, user_id, alert_type, channel)` with `enabled` and `frequency` columns. Implement `GetNotificationPreferencesUseCase` and `UpdateNotificationPreferencesUseCase` (R25 — use cases only, never `infrastructure/` from API layer). Add routes `GET /v1/users/me/notification-preferences` and `PATCH /v1/users/me/notification-preferences/{alert_type}`. Proxy through S9.

**Acceptance criteria**:
- [ ] Alembic up/down validated; FK to users with ON DELETE CASCADE
- [ ] Use cases depend on `ReadOnlyUnitOfWork` (Get) and `UnitOfWork` (Update) per R27
- [ ] S9 proxy routes return 200/404 correctly
- [ ] Response shape matches what frontend `types/api.ts` expects (verify before finalizing)
- [ ] Unit + integration tests pass; pre-commit clean

**Effort**: M
**Blocks**: none

### TASK-W0-02: Mutation idempotency — POST /v1/portfolios (REQ-002a)
**Type**: impl
**Service**: S1 portfolio
**Files**:
- `services/portfolio/src/portfolio/application/use_cases/create_portfolio.py`
- `services/portfolio/src/portfolio/api/routes/portfolios.py`
- `services/portfolio/tests/.../test_create_portfolio.py`

**Description**: Port the idempotency pattern from `record_transaction.py:86` (atomic `create_if_not_exists` against `idempotency` table). Accept `Idempotency-Key` header → command param. On replay return the original portfolio with 200, not 201.

**Acceptance criteria**:
- [ ] Same header + same body → identical portfolio_id, no duplicate row
- [ ] Same header + different body → 409 Conflict
- [ ] Missing header → existing non-idempotent behavior (preserve back-compat for older clients)
- [ ] Integration test covers retry-after-network-error scenario

**Effort**: S
**Blocks**: none

### TASK-W0-03: Mutation idempotency — POST /v1/watchlists/{id}/members (REQ-002b)
**Type**: impl
**Service**: S1 portfolio
**Files**:
- `services/portfolio/src/portfolio/application/use_cases/watchlist.py` (`AddWatchlistMemberUseCase`)
- `services/portfolio/src/portfolio/api/routes/watchlists.py`
- tests

**Description**: Wire `Idempotency-Key` to `AddWatchlistMemberUseCase` (currently L229-369). On duplicate add (same entity_id) return 200 with existing member, not 409 — this is naturally-idempotent semantics.

**Acceptance criteria**:
- [ ] Duplicate entity_id without idempotency-key → 200 (current behavior is 409 - confirm with product before changing; if must stay 409 then idempotency-key is the only retry-safe path)
- [ ] Same idempotency-key replay returns original 200 response

**Effort**: S
**Blocks**: none

### TASK-W0-04: Mutation idempotency — POST /v1/brokerage-connections/{id}/sync (REQ-002c)
**Type**: impl
**Service**: S1 portfolio
**Files**:
- `services/portfolio/src/portfolio/api/routes/brokerage.py`
- `services/portfolio/src/portfolio/application/use_cases/trigger_brokerage_sync.py`
- tests

**Description**: HTTP trigger currently lacks an idempotency key (worker is already idempotent via external_ref dedup at `brokerage_sync_worker.py:359`). Add `Idempotency-Key` so retried POSTs from frontend don't enqueue duplicate sync tasks.

**Effort**: S
**Blocks**: none

### TASK-W0-05: Mutation idempotency — POST /v1/feedback (REQ-002d)
**Type**: impl
**Service**: S1 portfolio (or S9 if route is gateway-owned)
**Files**: route + use case (locate via `grep -rn "feedback" services/portfolio services/api-gateway --include="*.py"`)

**Description**: Accept `Idempotency-Key`, store on `feedback.idempotency_key UNIQUE` column (add migration if needed), de-dup on replay.

**Effort**: S
**Blocks**: none

### TASK-W0-06: Entity refresh trigger (REQ-003)
**Type**: impl + schema
**Service**: S7 knowledge-graph (publisher) + S6 nlp-pipeline (consumer)
**Files**:
- `services/knowledge-graph/src/knowledge_graph/api/entities.py` (add route)
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/trigger_entity_refresh.py` (new)
- `infra/kafka/schemas/entity.refresh.v1.avsc` (new)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/entity_refresh_consumer.py` (new)
- `services/api-gateway/src/api_gateway/routes/entities.py` (proxy)
- tests both sides + Avro forward-compat check

**Description**: `POST /v1/entities/{entity_id}/refresh` with body `{"refresh_type": "description"|"narrative"|"all"}`. Publishes `entity.refresh.v1` event. S6 re-embeds if needed; S7 `DefinitionRefreshWorker` re-fetches Gemini description; existing narrative trigger logic for narratives. 1/hour/(entity+tenant+user) rate limit via Valkey, same pattern as `narratives.py:111`. Returns 202 + job_id.

**Acceptance criteria**:
- [ ] Avro schema is forward-compat (all fields have defaults)
- [ ] Rate limit enforced; second request within 1h returns 429
- [ ] End-to-end test: trigger refresh → S6 consumer fires → entity_embedding_state updated

**Effort**: M
**Blocks**: none

### TASK-W0-07: `/v1/price/batch` partial-result schema (REQ-004)
**Type**: impl
**Service**: S3 market-data
**Files**:
- `services/market-data/src/market_data/api/routers/price_snapshot.py:176-196`
- `services/market-data/src/market_data/api/schemas/price.py`
- tests

**Description**: Change response from `list[PriceSnapshotResponse]` to `dict[instrument_id, PriceSnapshotResponse | None]` (mirrors `/v1/quotes/batch` shape). Verify frontend consumes the new shape before merging — coordinate via PR review.

**Effort**: S
**Blocks**: none

---

## Wave 1 — Critical & High Bugs (Data Integrity / Security)

### TASK-W1-01: Fix SUPPRESS path emitting enriched events (BUG-001)
**Type**: impl + test
**Service**: S6 nlp-pipeline
**Files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:649-666` (`_enqueue_enriched`)
- new regression test in `services/nlp-pipeline/tests/integration/`

**Description**: `_enqueue_enriched()` must early-return when `ml.final_path == ProcessingPath.HALT`. Add the gate; do NOT delete the emission for non-HALT paths.

**Acceptance criteria**:
- [ ] Test asserts: article with SUPPRESS tier → no `nlp.article.enriched.v1` event emitted
- [ ] Test asserts: ROUTINE/PRIORITY tier articles still emit (non-regression)
- [ ] Existing 286 unit + 7 integration tests pass

**Effort**: S
**Blocks**: TASK-W1-02

### TASK-W1-02: Price-impact worker must filter by routing_tier (BUG-002)
**Type**: impl + test
**Service**: S6 nlp-pipeline
**Files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/impact_window.py:95-143` (`get_articles_needing_windows`)
- regression test

**Description**: Add `AND routing_tier != 'suppress'` (or equivalent enum value) to the SELECT. Verify the column exists on the joined table; if not, JOIN with `routing_decisions` (per CLAUDE.md, routing_score lives in `routing_decisions.composite_score`).

**Acceptance criteria**:
- [ ] Test: SUPPRESS articles never get impact windows computed
- [ ] Test: existing ROUTINE/PRIORITY behavior preserved
- [ ] Backfill consideration: existing wrong rows — discuss whether to delete or leave (data ages out via the multi-window TTL)

**Effort**: S
**Blocks**: depends on W1-01 being merged first (same code area)

### TASK-W1-03: SnapTrade sync per-connection lock (BUG-003)
**Type**: impl + test
**Service**: S1 portfolio
**Files**:
- `services/portfolio/src/portfolio/workers/brokerage_sync_worker.py:170-246`
- new integration test simulating two workers

**Description**: Add Postgres advisory lock or `SELECT ... FOR UPDATE SKIP LOCKED` on the `BrokerageConnection` row at sync claim time. Either (a) Postgres advisory lock keyed by `hash(connection_id)`, or (b) row-level FOR UPDATE inside the transaction. Workers that fail to claim should skip silently — next cycle picks them up.

**Acceptance criteria**:
- [ ] Two concurrent sync calls for the same connection → exactly one executes; the other returns immediately
- [ ] Different connections in parallel still proceed concurrently
- [ ] Integration test uses two async tasks in the same test to simulate

**Effort**: M
**Blocks**: none

### TASK-W1-04: S9 rate-limit bypass fix (BUG-004) — CRITICAL
**Type**: impl + test (security)
**Service**: S9 api-gateway
**Files**:
- `services/api-gateway/src/api_gateway/middleware.py:355-465` (RateLimitMiddleware)
- `services/api-gateway/src/api_gateway/middleware.py` (OIDCAuthMiddleware) — ensure `request.state.user = None` is ALWAYS set, never absent
- security regression test

**Description**: Two complementary fixes:
1. In `OIDCAuthMiddleware`, set `request.state.user = None` unconditionally at the top of `dispatch()` so the attribute always exists.
2. In `RateLimitMiddleware`, replace `if user and user.get("user_id")` with `getattr(request.state, "user", None)` and a strict check; in `except AttributeError`, fall back to the unauthenticated path AND log a warning (this should now be impossible after fix 1, but defense-in-depth).
3. Strengthen unauthenticated path: lower per-IP bucket OR combine with a global token bucket (per route).

**Acceptance criteria**:
- [ ] Test: request with no Auth header → unauthenticated bucket applied
- [ ] Test: request with malformed JWT → user attr is None, unauthenticated bucket applied (not bypassed)
- [ ] Test: request with valid JWT → user_id bucket applied
- [ ] No AttributeError reachable from middleware path

**Effort**: S
**Blocks**: none — but tag as security-priority for accelerated review

### TASK-W1-05: S9 JWKS rotation mechanism (BUG-005)
**Type**: impl + test
**Service**: S9 api-gateway (publisher) + all backends (consumers)
**Files**:
- `services/api-gateway/src/api_gateway/app.py:137-145`
- `services/api-gateway/src/api_gateway/api/internal_jwks.py` (or wherever the `/internal/jwks` route is)
- All backends’ `InternalJWTMiddleware` (9 services — see REF-001)

**Description**:
1. S9: include `kid` (key id) in JWT header at issue time; expose `/internal/jwks` with array of public keys (current + N previous for grace period). Add a `JWT_KEY_VERSION` env var or sentinel file the server watches.
2. Backends: cache JWKS but re-fetch when an incoming JWT has a `kid` not in cache (refresh-on-miss is partially present in `oidc.py:63-78` — confirm and align everywhere). Bound max refresh rate (1/min/process) to prevent JWKS DoS.

**Acceptance criteria**:
- [ ] Old + new public keys served during overlap window
- [ ] Backends correctly validate against either
- [ ] Refresh-on-kid-miss tested
- [ ] No silent acceptance of unknown kid after grace window

**Effort**: M
**Blocks**: REF-001 (do W1-05 first while local — then REF-001 extracts the shared middleware including this logic)

### TASK-W1-06: `processed_events` retention (LIB-001)
**Type**: migration + impl
**Service**: every service that uses `BaseKafkaConsumer` (libs/messaging)
**Files**:
- `libs/messaging/src/messaging/kafka/consumer/base.py` (add optional retention config)
- One Alembic migration per service that already has `processed_events`: add a partial index `(service_name, processed_at)` and a scheduled `pg_cron` (or worker) DELETE older_than 30 days
- OR: introduce a `processed_events_cleanup_worker` in libs/messaging registered by each service

**Description**: Default retention 30 days (configurable). Worker runs daily, deletes `WHERE processed_at < now() - interval '30 days'` in batches of 10k. Document the retention guarantee in `docs/libs/messaging.md`.

**Acceptance criteria**:
- [ ] Migration applies + rolls back cleanly per service
- [ ] Worker is idempotent and bounded (no runaway delete)
- [ ] After deletion of processed_event, no message is mistakenly reprocessed if delivered (rely on consumer offset, which is the primary safety; processed_events is belt-and-suspenders against operator offset rewinds within retention window)

**Effort**: M
**Blocks**: none

---

## Wave 2 — Medium Bugs + High-Value Refactor

### TASK-W2-01: URL tracking-param strip list (BUG-006)
**Type**: impl + test
**Service**: S5 content-store
**Files**:
- `services/content-store/src/content_store/application/deduplication/stage_b_normalized.py:23-39`
- existing dedup tests

**Description**: Extend `_TRACKING_PARAMS` to include `_ga`, `igshid`, `_hsenc`, `_hsmi`, `mc_cid`, `mc_eid` (verify mc_eid is already there per agent finding), `oly_anon_id`, `oly_enc_id`. Cross-check against a maintained list (e.g., `clear-urls`/`uBlock` rules) and document the source.

**Effort**: S
**Blocks**: none

### TASK-W2-02: WebSocket mid-stream token expiry (BUG-007)
**Type**: impl + test
**Service**: S10 alert
**Files**:
- `services/alert/src/alert/api/routes.py:495-537`

**Description**: Track token expiry in connection state; on each Valkey pub/sub message dispatch, check `now() < token_exp`. If expired, send `{"type":"auth_expired"}` JSON event then close with code 4401. Frontend can prompt re-auth or refresh token. Replace the bare `except Exception: pass` at L537 with a structlog warning so silent disconnects are observable.

**Effort**: S
**Blocks**: none

### TASK-W2-03: S4 adapter schedule jitter (BUG-008)
**Type**: impl + test
**Service**: S4 content-ingestion
**Files**:
- `services/content-ingestion/src/content_ingestion/infrastructure/scheduler/scheduler.py:57-93`

**Description**: Inject a small per-source random offset (e.g., 0..interval/4) when starting each source loop so 4 adapters don’t fire at the same wall clock instant. Seed offset by source name hash for stability across restarts.

**Effort**: S
**Blocks**: none

### TASK-W2-04: Add `is_backfill` to MarketDatasetFetched event (BUG-009)
**Type**: schema + impl
**Service**: S2 market-ingestion
**Files**:
- `services/market-ingestion/src/market_ingestion/domain/events.py:56-88`
- `infra/kafka/schemas/market.dataset.fetched.avsc`
- consumers (S10 alert; check S3)

**Description**: Add `is_backfill: boolean = false` (forward-compat default). Producer sets it from task. S10 consumer reads it and suppresses fan-out when true. Schema must be forward-compat (default false).

**Effort**: S
**Blocks**: none

### TASK-W2-05: REF-001 — extract InternalJWTMiddleware to shared lib
**Type**: refactor + test
**Service**: libs/observability (or new libs/auth)
**Files**:
- new: `libs/observability/src/observability/internal_jwt.py` (or `libs/auth/`)
- delete: `services/{alert,rag-chat,market-data,nlp-pipeline,knowledge-graph,content-store,content-ingestion,market-ingestion,portfolio}/src/.../internal_jwt.py`
- each service `app.py` import update

**Description**: Single shared `InternalJWTMiddleware(skip_paths: list[str], jwks_endpoint: str)` factory. Must include the JWKS refresh-on-kid-miss logic from TASK-W1-05. Keep behavior identical to current copies; do not introduce new auth semantics.

**Acceptance criteria**:
- [ ] All 9 services pass their existing test suites unchanged
- [ ] `git diff` shows ~2400 lines deleted, ~250 lines added
- [ ] Cross-service integration test: malformed/expired/valid internal JWT scenarios pass on representative sample of 3 services

**Effort**: M
**Blocks**: TASK-W1-05 (must merge first so the shared lib bakes in rotation support)

### TASK-W2-06: LIB-002 — ensure dead-letter topic publishing in base class
**Type**: refactor
**Service**: libs/messaging
**Files**: `libs/messaging/src/messaging/kafka/consumer/base.py:285-309`

**Description**: Provide a default `_dead_letter_impl()` that publishes to `<topic>.dead-letter.v1` via the existing outbox. Subclasses can override to add DB persistence on top; they should not need to override to get DLQ topic publishing.

**Effort**: M
**Blocks**: none

---

## Wave 3 — Test Coverage

### TASK-W3-01: intelligence-migrations integration tests
**Type**: test
**Service**: services/intelligence-migrations
**Files**: `services/intelligence-migrations/tests/integration/`

**Description**: Add tests that (a) apply every migration top-down on a fresh DB and verify schema, (b) test rollback of last 3 migrations, (c) verify R24 (only intelligence-migrations writes DDL) by asserting no DDL in S6/S7 alembic.

**Effort**: M
**Blocks**: none

### TASK-W3-02: api-gateway integration test coverage
**Type**: test
**Service**: S9 api-gateway
**Description**: Contract tests for the 10 largest routers — verify path → backend mapping, header propagation (`X-Internal-JWT`), error translation.
**Effort**: M
**Blocks**: none

### TASK-W3-03: market-ingestion E2E adapter tests
**Type**: test
**Service**: S2 market-ingestion
**Description**: 5–10 E2E tests for EODHD, Finnhub, Alpaca with real Kafka + DB containers. Validates outbox path and rate-limit backoff.
**Effort**: L
**Blocks**: none

---

## Wave 4 — Low Priority / COULD

### TASK-W4-01: LIB-003 — LISTEN/NOTIFY for outbox dispatcher
**Type**: refactor
**Service**: libs/messaging
**Description**: Add Postgres `LISTEN/NOTIFY` wakeup so dispatcher polls only on signal or every 60s (idle). Eliminates ~17k idle queries/day per service.
**Effort**: M
**Blocks**: none

### TASK-W4-02: LIB-004 — wire DeepInfra→Ollama fallback in adapter
**Type**: refactor
**Service**: libs/ml-clients
**Description**: Move per-service fallback logic into the adapter layer. Add fallback for 429 and TimeoutException; expose `fallback_adapter` constructor param.
**Effort**: M
**Blocks**: none

### TASK-W4-03: LIB-005 — classify 429 as retryable
**Type**: impl
**Service**: libs/ml-clients
**Description**: Change `RateLimitError` classification in `deepinfra_*` adapters from fatal to retryable; consumer backoff handler then retries with exponential delay.
**Effort**: S
**Blocks**: LIB-004 (W4-02) ideally first

### TASK-W4-04: LIB-006 — bucket name enum
**Type**: refactor
**Service**: libs/storage
**Description**: Introduce `BucketTier` enum (BRONZE, SILVER, GOLD). `put_bytes()`/`get_bytes()` accept `BucketTier`; the adapter resolves to bucket name. Prevents typo writes to wrong tier.
**Effort**: S
**Blocks**: none

### TASK-W4-05: LIB-007 — expose ETag for claim-check integrity
**Type**: refactor
**Service**: libs/storage
**Description**: Return ETag from `put_bytes()`; accept optional `expected_etag` on `get_bytes()` and raise on mismatch. No mandatory caller changes — opt-in.
**Effort**: S
**Blocks**: none

### TASK-W4-06: REF-002 — split api-gateway/clients.py
**Type**: refactor
**Service**: S9 api-gateway
**Files**: `services/api-gateway/src/api_gateway/clients.py` (1496 lines)
**Description**: Extract retry strategies and error translation to `libs/common/retry.py`; split HTTP clients into one file per downstream service. Behavior-preserving.
**Effort**: M
**Blocks**: none

### TASK-W4-07: REF-003 — pagination contracts
**Type**: refactor
**Service**: libs/contracts
**Description**: Create `PaginationParams` and `PaginatedResponse[T]` in libs/contracts; migrate one repo per service incrementally.
**Effort**: S
**Blocks**: none

---

## Dispatch Notes for Subagents

- All implementation tasks must follow `/implement` skill pipeline: implement → test → ruff → mypy → service tests → security scan → review → docs update → commit.
- Migrations involving `intelligence_db` MUST land in `services/intelligence-migrations/` only (R24). S6/S7 ship with `ALEMBIC_ENABLED=false`.
- For schema additions (TASK-W0-06, TASK-W2-04), use forward-compatible Avro: add fields with defaults; never remove/rename.
- For security-sensitive tasks (W1-04, W1-05), require `/security-audit` review before merge.
- For each task: open a PR, run pre-commit + service-specific tests, update `docs/BUG_PATTERNS.md` if a new BP number is needed, and update `docs/plans/TRACKING.md`.
