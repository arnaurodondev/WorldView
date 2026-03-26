---
id: PLAN-0001-B-R1
prd: QA Review + Code Review findings from 2026-03-26
title: "S4 Content Ingestion — QA & Review Fixes: Runtime Bugs, Lock, Watermarks, Auth, Security, Tests, Infra"
status: in-progress
created: 2026-03-26
updated: 2026-03-26  # W3+W4 completed
plans: 1
waves: 7
tasks: 42
depends_on: "PLAN-0001-B Wave A-3 (S4 service fully implemented)"
---

# PLAN-0001-B-R1: S4 QA & Review Fixes

## Overview

**Source**: Code review (R-001–R-014) + Multi-agent QA audit (46 findings: 5 BLOCKING, 7 CRITICAL, 17 MAJOR) from 2026-03-26.
**Goal**: Fix all blocking runtime bugs, security vulnerabilities, architectural gaps, test coverage holes, and infrastructure setup issues discovered during the S4 QA pass. Update all documentation and review tooling to prevent recurrence.
**Total Scope**: 1 plan, 7 waves, 42 tasks

### QA Findings Mapped to Waves

| Wave | QA Findings Addressed |
|------|-----------------------|
| W0 | B-001 (Avro payload mismatch), B-002 (missing httpx client), B-004 (DLQ not populated), B-005 (NewsAPI constructor), C-002 (session rollback), C-005 (MinIO before dedup) |
| W1 | B-003 (hash() lock), C-001 (timing attack), M-016 (Valkey non-atomic quota) + token split |
| W2 | M-001 (lock during I/O), M-002 (watermarks unused), batch commit |
| W3 | M-003 (no backoff), M-017 (dispatcher supervision), M-010 (engine dispose), M-011 (settings in lifespan), M-012 (no exception handlers), source hot-add |
| W4 | M-004 (readiness info leak), M-005 (SSRF URL), M-006 (config dict), M-007 (unbounded pagination), M-008 (unsafe setattr), C-003/C-004 (port abstractions) |
| W5 | C-006 (client tests), C-007 (_run_fetch_cycle tests), M-013–M-015 (coverage gaps), docker compose hybrid |
| W6 | All documentation: BP-012–BP-015, HR-017–HR-018, checklist updates, service docs, .claude-context |

---

## Plan Dependency Graph

```
Wave 0: Emergency runtime fixes (service literally cannot run without these)
    │
    ├─→ Wave 1: Shared lib + Config foundation (advisory lock, tokens, Valkey atomic)
    │       │
    │       ├─→ Wave 2: Lock restructure + Watermarks + Batch commit
    │       │
    │       └─→ Wave 3: Robustness (backoff, supervision, dispose, exceptions, hot-add)
    │               │
    │               └─→ Wave 4: Security hardening + Port abstractions
    │                       │
    │                       └─→ Wave 5: Test coverage + Docker compose hybrid
    │                               │
    │                               └─→ Wave 6: Documentation + Bug patterns + Review tooling
```

---

## Design Decisions

### D1: Avro payload alignment (B-001)
The outbox payload must contain exactly the fields in `content.article.raw.v1.avsc`. The current code uses `url`, `url_hash`, `minio_key`, `fetched_at`, `byte_size` — none of which exist in the schema. We'll build a `build_raw_article_payload()` helper that maps domain fields to Avro field names, including envelope fields (`event_id`, `event_type`, `schema_version`, `occurred_at`).

### D2: httpx.AsyncClient lifecycle (B-002)
Create one shared `httpx.AsyncClient` in the lifespan, pass it to all adapter clients. Close it on shutdown. This is consistent with how `httpx` recommends client usage (connection pooling).

### D3: DLQ population (B-004)
`move_to_dead_letter` must INSERT into `dead_letter_queue` with the original payload serialized as JSONB (not Avro bytes, since the Avro serialization may have failed). Add `payload_json` column to DLQ model. `requeue` reads `payload_json` to rebuild the outbox event.

### D4: Advisory lock in shared lib with SHA-256 (B-003)
Same as original plan. `messaging.pg.advisory_lock` with deterministic hashing.

### D5: Batch commit (25 articles, configurable)
Same as original plan. On IntegrityError (unique constraint on url_hash), catch specifically, count as `skipped`, and call `session.rollback()` before continuing.

### D6: Docker compose — hybrid approach
- **Centralized** (`infra/compose/docker-compose.test.yml`): Add `content-ingestion-test` profile. Used by `scripts/test-full.sh` and CI.
- **Per-service** (`services/content-ingestion/tests/docker-compose.test.yml`): Keep as standalone fallback. Used by `make test-integration` locally.
- **Makefile**: Update `test-integration` target to accept `COMPOSE_MODE=standalone|centralized` flag.

### D7: Port abstractions
Define 4 port protocols in `application/ports/`: `SourceAdapterPort`, `FetchLogPort`, `OutboxPort`, `BronzeStoragePort`. Move `SourceAdapter` ABC from `infrastructure/adapters/base.py` to `application/ports/source_adapter.py`. Use case depends only on ports.

### D8: Session error handling (C-002)
In the article processing loop, catch `IntegrityError` specifically for unique constraint → count as `skipped` + `session.rollback()`. Catch other DB errors → `session.rollback()` + count as `failed`. This prevents cascading session invalidation.

---

## Wave 0: Emergency Runtime Fixes ✅

**Goal**: Fix the 5 issues that prevent S4 from running at all. After this wave, the service can start and process articles.
**Depends on**: none
**Estimated effort**: 45-60 minutes
**Status**: **DONE** — 2026-03-26 · 127 S4 tests pass · ruff + mypy clean
**Architecture layer**: infrastructure + application + API

### Tasks

#### T-R1-0-01: Fix Avro payload field alignment

**Type**: impl
**Target files**:
- `services/content-ingestion/src/content_ingestion/application/use_cases/fetch_and_write.py`
- `services/content-ingestion/src/content_ingestion/api/routes/internal.py`

**What to build**:
Create a `_build_outbox_payload()` helper function that maps domain fields to the exact Avro schema field names. Both the use-case and internal endpoint must produce payloads matching the 14 fields in `content.article.raw.v1.avsc`.

**Logic & Behavior**:
Map these fields:
- `event_id` → `str(common.ids.new_uuid7())`
- `event_type` → `"content.article.raw"`
- `schema_version` → `1`
- `occurred_at` → `ct.to_iso8601(ct.utc_now())`
- `doc_id` → `str(result.source_id)` or generated UUID
- `source_type` → `str(source.source_type)`
- `source_url` → `result.url` (renamed from `url`)
- `minio_bronze_key` → `minio_key` (renamed from `minio_key`)
- `content_hash` → `hashlib.sha256(result.raw_bytes).hexdigest()`
- `fetch_id` → `str(fetch_log_row_id)`
- `title` → `None` (extracted downstream by S6)
- `published_at` → ISO-8601 or None
- `is_backfill` → `result.is_backfill`
- `correlation_id` → `None`

**Acceptance criteria**:
- [ ] Outbox payload contains exactly the 14 Avro schema fields
- [ ] Both use-case and internal endpoint produce identical payload structure
- [ ] Existing Avro roundtrip tests pass with the new payload

---

#### T-R1-0-02: Add `httpx.AsyncClient` to lifespan and fix client construction

**Type**: impl
**Target files**:
- `services/content-ingestion/src/content_ingestion/app.py`

**What to build**:
Create a shared `httpx.AsyncClient` in the lifespan. Update `_run_fetch_cycle` to pass it to each client constructor. Close it on shutdown.

**Logic & Behavior**:
```python
# In lifespan:
http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
app.state.http_client = http_client

# In _run_fetch_cycle:
client = EODHDClient(http_client=http_client, api_key=settings.eodhd_api_key)

# On shutdown:
await http_client.aclose()
```

Handle per-adapter constructor differences explicitly (not generic `adapter_cls(**kwargs)`).

**Acceptance criteria**:
- [ ] All 4 client constructors receive `http_client` as first argument
- [ ] `httpx.AsyncClient` created in lifespan, stored on `app.state`
- [ ] Client closed on shutdown (no resource leak)
- [ ] Per-adapter wiring handles constructor differences (NewsAPI has no `rate_limiter`)

---

#### T-R1-0-03: Fix DLQ population — `move_to_dead_letter` must INSERT into DLQ table

**Type**: impl
**Target files**:
- `services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/outbox.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/dlq.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/db/models.py` (add `payload_json` column)
- `services/content-ingestion/alembic/versions/` (new migration)

**What to build**:
Update `move_to_dead_letter` to INSERT a row into `dead_letter_queue` with the outbox event's JSONB payload. Add `payload_json: Mapped[dict]` column to `DeadLetterQueueModel`. Update `DLQRepository.requeue()` to use `payload_json` for the new outbox event's payload (not empty dict).

**Acceptance criteria**:
- [ ] `move_to_dead_letter` creates a DLQ row with full payload
- [ ] `DLQRepository.requeue()` creates outbox event with the original payload
- [ ] `s4_dlq_total` gauge reports correct count
- [ ] New Alembic migration adds `payload_json` column

---

#### T-R1-0-04: Fix session error handling — rollback on failure, catch IntegrityError

**Type**: impl
**Target files**:
- `services/content-ingestion/src/content_ingestion/application/use_cases/fetch_and_write.py`

**What to build**:
In the article processing loop, catch `sqlalchemy.exc.IntegrityError` specifically (unique constraint on url_hash) → count as `skipped`, call `session.rollback()`. Catch other exceptions → `session.rollback()` + count as `failed`. Pass a rollback callable alongside commit_fn.

**Acceptance criteria**:
- [ ] `IntegrityError` on url_hash counted as `skipped` (not `failed`)
- [ ] Session rolled back after any DB error
- [ ] Subsequent articles process correctly after a mid-loop failure
- [ ] FetchSummary accurately reflects skipped vs failed counts

---

#### T-R1-0-05: Fix internal endpoint — dedup check before MinIO write

**Type**: impl
**Target files**:
- `services/content-ingestion/src/content_ingestion/api/routes/internal.py`

**What to build**:
Move `exists_by_url_hash()` check BEFORE the MinIO `put_object()` call. If duplicate, return early without writing to MinIO.

**Acceptance criteria**:
- [ ] Dedup check happens before MinIO write
- [ ] Duplicate URLs don't create orphaned MinIO objects
- [ ] Response returns `{"status": "duplicate"}` correctly

---

#### T-R1-0-06: Unit tests for Wave 0 fixes

**Type**: test
**Target files**:
- `services/content-ingestion/tests/unit/application/test_fetch_and_write.py` (update)
- `services/content-ingestion/tests/unit/api/test_internal.py` (new)
- `services/content-ingestion/tests/unit/test_dlq_repo.py` (update)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_payload_has_all_avro_fields | Outbox payload keys match Avro schema | unit |
| test_payload_content_hash_computed | SHA-256 of raw_bytes in payload | unit |
| test_integrity_error_counted_as_skipped | Unique constraint violation → skipped | unit |
| test_session_rollback_on_integrity_error | Session usable after IntegrityError | unit |
| test_subsequent_articles_after_failure | Articles after failure still process | unit |
| test_dlq_move_creates_dlq_row | move_to_dead_letter inserts DLQ entry | unit |
| test_dlq_requeue_uses_original_payload | Requeue creates outbox with payload | unit |
| test_internal_dedup_before_minio | Duplicate skips MinIO write | unit |
| test_internal_submit_success | Full write path works | unit |
| test_internal_submit_both_url_and_content | Returns 422 | unit |

**Acceptance criteria**:
- [ ] 10+ new tests pass
- [ ] All existing 126 tests still pass
- [ ] ruff + mypy clean

### Validation Gate
- [ ] ruff + mypy pass
- [ ] 136+ tests pass (126 existing + 10 new)
- [ ] Service can start and process a mock fetch cycle without crashing

### Regression Guardrails
- BP-001: Outbox serializer must be `OutboxEventValueSerializer`
- BP-014 (NEW): Outbox payload fields must match Avro schema exactly

---

## Wave 1: Shared Library + Config Foundation ✅

**Goal**: Add deterministic advisory lock utility to `libs/messaging`, split S4 auth tokens, fix timing vulnerability in S4 + S1, fix Valkey non-atomic quota.
**Depends on**: Wave 0
**Estimated effort**: 30-45 minutes
**Status**: **DONE** — 2026-03-26 · 127 S4 + 10 messaging tests pass · ruff + mypy clean

### Tasks

#### T-R1-1-01: Add `pg_advisory_lock` to `libs/messaging`

_(Same as original plan — `messaging.pg.advisory_lock` with SHA-256 hashing, 8+ tests)_

**Type**: impl
**Target files**: `libs/messaging/src/messaging/pg/__init__.py`, `libs/messaging/src/messaging/pg/advisory_lock.py`, `libs/messaging/tests/unit/test_advisory_lock.py`

**Acceptance criteria**:
- [ ] `advisory_lock_id()` uses `hashlib.sha256`, NOT `hash()`
- [ ] Deterministic across processes
- [ ] 8+ tests pass

---

#### T-R1-1-02: Split S4 auth tokens + timing-safe comparison

_(Same as original plan — separate `admin_token` and `internal_service_token`, `hmac.compare_digest`)_

**Type**: impl
**Target files**: `config.py`, `api/dependencies.py`, tests

**Acceptance criteria**:
- [ ] Two separate token settings
- [ ] `hmac.compare_digest()` used for both
- [ ] 5+ token tests pass

---

#### T-R1-1-03: Fix timing vulnerability in S1 (Portfolio)

_(Same as original plan — `hmac.compare_digest` in Portfolio)_

---

#### T-R1-1-04: Fix Valkey quota check — use atomic INCR

**Type**: impl
**Target files**:
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/newsapi/client.py`

**What to build**:
Replace the non-atomic get/set pattern with Redis `INCR` + `EXPIRE`. This prevents race conditions where concurrent replicas undercount quota usage.

**Logic**:
```python
current = await self._valkey.incr(key)
if current == 1:
    await self._valkey.expire(key, _QUOTA_TTL_SECONDS)
if current > self._daily_limit:
    raise QuotaExhaustedError(...)
```

**Acceptance criteria**:
- [ ] Quota check uses `INCR` (atomic)
- [ ] TTL set on first increment only
- [ ] Existing quota tests updated
- [ ] No race condition under concurrent access

---

#### T-R1-1-05: Update env example files for token layout

_(Same as original plan)_

### Validation Gate
- [ ] 8+ advisory lock tests pass
- [ ] 5+ token tests pass
- [ ] Existing S1 + S4 tests pass
- [ ] ruff + mypy clean on all changed packages

---

## Wave 2: Lock Restructure + Watermarks + Batch Commit

**Goal**: Lock held only during DB writes. Watermarks wired into fetch cycle. Batch commits (25/batch).
**Depends on**: Wave 1
**Estimated effort**: 45-60 minutes

### Tasks

#### T-R1-2-01: Restructure `_run_fetch_cycle` — lock only during writes
_(Same as original plan — fetch without lock, write with lock, use shared `messaging.pg.advisory_lock`)_

---

#### T-R1-2-02: Wire watermarks into fetch cycle
_(Same as original plan — read `source_adapter_state.last_watermark` before fetch, update after writes)_

---

#### T-R1-2-03: Update all 4 adapters to accept `from_date` parameter
_(Same as original plan)_

---

#### T-R1-2-04: Implement batch commit with IntegrityError handling

**Type**: impl
**Target files**: `application/use_cases/fetch_and_write.py`

**What to build**:
Replace per-article commit with batch commits every N articles (default 25). Catch `IntegrityError` per article (unique constraint) → `session.rollback()` + count as skipped. Commit remaining at end of loop.

**Acceptance criteria**:
- [ ] Commits every `batch_size` articles
- [ ] IntegrityError → skipped, session restored
- [ ] Final partial batch committed

---

#### T-R1-2-05: Unit tests for lock + watermarks + batch commit
_(Same as original plan — 10+ tests)_

### Validation Gate
- [ ] 10+ new tests
- [ ] Advisory lock NOT held during `adapter.fetch()`
- [ ] Uses `messaging.pg.advisory_lock`

---

## Wave 3: Robustness — Backoff, Supervision, Dispose, Exceptions ✅

**Goal**: Make the service resilient to persistent failures, fix resource leaks, add proper exception mapping.
**Depends on**: Wave 2
**Estimated effort**: 45-60 minutes
**Status**: **DONE** — 2026-03-26 · 165 S4 unit tests pass · ruff + mypy clean

### Tasks

#### T-R1-3-01: Exponential backoff in `_poll_loop`
_(Same as original plan — `min(interval * 2^failures, max_backoff)`, reset on success)_

---

#### T-R1-3-02: Add dispatcher supervision with restart-on-crash

**Type**: impl
**Target files**: `app.py`

**What to build**:
Wrap the outbox dispatcher task in a supervisor loop that restarts on crash with exponential backoff. Set a health flag when the dispatcher is dead to make `/readyz` report degraded.

**Logic**:
```python
async def _supervised_dispatcher(dispatcher, app):
    failures = 0
    while True:
        try:
            await dispatcher.run()
            break  # clean exit
        except Exception:
            failures += 1
            delay = min(5 * 2**failures, 300)
            logger.exception("dispatcher_crashed", restart_delay=delay)
            app.state.dispatcher_healthy = False
            await asyncio.sleep(delay)
            app.state.dispatcher_healthy = True
```

**Acceptance criteria**:
- [ ] Dispatcher restarts after crash
- [ ] Exponential backoff between restarts
- [ ] `/readyz` reports degraded when dispatcher is down

---

#### T-R1-3-03: Fix engine dispose + Settings in create_app

**Type**: impl
**Target files**: `app.py`, `infrastructure/db/session.py`

**What to build**:
- Return `(engine, session_factory)` from `create_session_factory`
- Move `Settings()` to `create_app()` (consistent with portfolio)
- Call `await engine.dispose()` on shutdown
- Store engine on `app.state`

**Acceptance criteria**:
- [ ] Engine disposed on shutdown
- [ ] Settings created in `create_app()`, not `lifespan()`
- [ ] No leaked DB connections

---

#### T-R1-3-04: Add domain exception handlers to FastAPI app

**Type**: impl
**Target files**: `app.py`

**What to build**:
Register exception handlers that map domain errors to HTTP status codes:
- `AdapterError` → 502
- `QuotaExhaustedError` → 429
- `ConfigurationError` → 500 with structured body
- `StorageError` → 503
- Unhandled `Exception` → 500 with generic body (no internal details)

**Acceptance criteria**:
- [ ] Domain exceptions produce correct HTTP status codes
- [ ] Error responses don't leak internal details

---

#### T-R1-3-05: `add_source` / `remove_source` on scheduler + wire to admin API
_(Same as original plan)_

---

#### T-R1-3-06: Remove local advisory_lock module
_(Same as original plan — delete, replace imports)_

---

#### T-R1-3-07: Unit tests for Wave 3

**Tests to write** (9+ tests):
- Backoff: first failure, third failure, reset on success, cap at max
- `add_source`: starts polling, rejects duplicate, rejects disabled
- `remove_source`: cancels task, not found returns False
- Dispatcher supervision: restart on crash (mock)

### Validation Gate
- [x] 9+ new tests
- [x] Local `advisory_lock.py` deleted
- [x] Engine disposed on shutdown

---

## Wave 4: Security Hardening + Port Abstractions ✅

**Goal**: Fix input validation, info leak, architecture layer violations.
**Depends on**: Wave 3
**Estimated effort**: 45-60 minutes
**Status**: **DONE** — 2026-03-26 · 165 S4 unit tests pass · ruff + mypy clean

### Tasks

#### T-R1-4-01: Fix readiness endpoint — no exception details in response

**Type**: impl
**Target files**: `api/routes/health.py`

**What to build**:
Replace `f"error: {exc}"` with generic `"error"` in HTTP response. Log full exception server-side.

---

#### T-R1-4-02: Add URL validation on internal ingest endpoint

**Type**: impl
**Target files**: `api/schemas.py`

**What to build**:
Add Pydantic `field_validator` on `IngestSubmitRequest.url` to enforce `http://` or `https://` scheme. Reject private IP ranges (169.254.x.x, 10.x.x.x, 127.x.x.x, 192.168.x.x) to prevent SSRF.

---

#### T-R1-4-03: Constrain source config dict + DLQ pagination bounds

**Type**: impl
**Target files**: `api/schemas.py`, `api/routes/dlq.py`

**What to build**:
- Constrain `SourceCreateRequest.config` to `dict[str, str | int | bool]`
- Add `Query(ge=1, le=1000)` on DLQ `limit`, `Query(ge=0)` on `offset`

---

#### T-R1-4-04: Add allowlist to `SourceRepository.update`

**Type**: impl
**Target files**: `infrastructure/db/repositories/source.py`

**What to build**:
Add `_MUTABLE_FIELDS = {"name", "enabled", "config"}` allowlist. Reject any key not in the set.

---

#### T-R1-4-05: Define port abstractions in application layer

**Type**: impl
**Target files**:
- `application/ports/__init__.py`
- `application/ports/source_adapter.py` (move ABC from `infrastructure/adapters/base.py`)
- `application/ports/repositories.py` (Protocol classes)
- `application/use_cases/fetch_and_write.py` (update imports)

**What to build**:
Define 4 port interfaces: `SourceAdapterPort` (ABC, moved from infra), `FetchLogPort` (Protocol), `OutboxPort` (Protocol), `BronzeStoragePort` (Protocol). Update use case to import only from ports.

**Acceptance criteria**:
- [ ] Application layer has zero infrastructure imports
- [ ] Use case typed against port interfaces
- [ ] Infrastructure classes implement ports

---

#### T-R1-4-06: Unit tests for security + ports (8+ tests)

**Tests**: URL validation (scheme, private IP), config dict constraint, DLQ limit bounds, setattr allowlist, port interface compliance.

### Validation Gate
- [x] 8+ new tests
- [x] Application layer has no infrastructure imports
- [x] ruff + mypy clean

---

## Wave 5: Test Coverage + Docker Compose Hybrid

**Goal**: Fill critical test coverage gaps. Set up hybrid docker-compose for centralized + standalone testing.
**Depends on**: Wave 4
**Estimated effort**: 60-90 minutes

### Tasks

#### T-R1-5-01: HTTP client tests for all 4 adapters

**Type**: test
**Target files**:
- `tests/unit/infrastructure/adapters/test_eodhd_client.py` (new)
- `tests/unit/infrastructure/adapters/test_sec_edgar_client.py` (new)
- `tests/unit/infrastructure/adapters/test_finnhub_client.py` (new)
- `tests/unit/infrastructure/adapters/test_newsapi_client.py` (new)

**What to build**:
Use `httpx.MockTransport` to test each client's HTTP integration: parameter assembly, pagination, 429 handling, error mapping, header injection.

**Tests per client** (5 each, 20 total):
- EODHD: params, 429, 500, non-list response, pagination stop
- SEC EDGAR: User-Agent header, semaphore, 429, hits.hits extraction, document fetch
- Finnhub: params, 429 sleep calculation, non-list response, transcript parsing
- NewsAPI: X-Api-Key header, pagination until totalResults, quota halt, 429

**Acceptance criteria**:
- [ ] 20+ new client-level tests
- [ ] Each client's HTTP behavior verified independently

---

#### T-R1-5-02: Tests for `_run_fetch_cycle` + `_metrics_poller`

**Type**: test
**Target files**:
- `tests/unit/test_app_fetch_cycle.py` (new)
- `tests/unit/test_app_metrics_poller.py` (new)

**Tests** (8 total):
- Lock not acquired → returns early
- Unknown source type → returns early
- EODHD path constructs correct client with httpx
- Metrics recorded after fetch
- Metrics poller updates gauges
- Metrics poller handles DB error gracefully

---

#### T-R1-5-03: Tests for internal endpoint + Finnhub transcripts + Pydantic schemas

**Type**: test
**Target files**:
- `tests/unit/api/test_internal.py` (new/expand)
- `tests/unit/infrastructure/adapters/test_finnhub.py` (expand)
- `tests/unit/api/test_schemas.py` (new)

**Tests** (12 total):
- Internal: submit with url, submit with raw_content, both → 422, neither → 422, invalid source_type → 400, duplicate → "duplicate"
- Finnhub: transcript list with entries, transcript fetch failure skipped, transcript dedup, RateLimitError during transcripts
- Schemas: empty name rejected, name too long, raw_content at 5MB boundary

---

#### T-R1-5-04: Add `content-ingestion-test` profile to centralized docker-compose

**Type**: config
**Target files**:
- `infra/compose/docker-compose.test.yml`

**What to build**:
Add `content-ingestion-test` profile following the existing portfolio-test/market-ingestion-test patterns. Services needed: postgres (shared), kafka, schema-registry, minio, valkey. Add S4-specific Alembic migration init container.

**Acceptance criteria**:
- [ ] `docker compose -f infra/compose/docker-compose.test.yml --profile content-ingestion-test up` starts all S4 dependencies
- [ ] Uses same ports as other centralized profiles (no conflicts)
- [ ] Alembic migration runs as init container before tests

---

#### T-R1-5-05: Update S4 Makefile for hybrid compose mode

**Type**: config
**Target files**:
- `services/content-ingestion/Makefile`

**What to build**:
Update `test-integration` target to support both modes:
```makefile
# Default: standalone (uses per-service compose with offset ports)
test-integration:
	@$(VENV)/bin/pytest tests/ -m integration -v

# Centralized: uses infra compose (call from repo root)
test-integration-centralized:
	cd ../.. && docker compose -f infra/compose/docker-compose.test.yml \
		--profile content-ingestion-test up -d --wait
	$(VENV)/bin/pytest tests/ -m integration -v
```

Also add `test-all` target that runs unit + integration.

**Acceptance criteria**:
- [ ] `make test` runs unit tests
- [ ] `make test-integration` runs integration with standalone compose
- [ ] `make test-integration-centralized` runs with infra compose
- [ ] `make test-all` runs both unit and integration

---

#### T-R1-5-06: Update `scripts/test-full.sh` to include S4

**Type**: config
**Target files**:
- `scripts/test-full.sh`

**What to build**:
Add `content-ingestion` to the service list for the full test suite. Ensure the `content-ingestion-test` profile is started alongside other service profiles.

**Acceptance criteria**:
- [ ] `scripts/test-full.sh` includes content-ingestion in its test sweep
- [ ] S4 integration tests run when `--profile all` or `--profile content-ingestion-test` is used

### Validation Gate
- [ ] 40+ new tests in this wave
- [ ] All 166+ total tests pass (126 original + 40 new)
- [ ] Docker compose profiles work (both standalone and centralized)
- [ ] ruff + mypy clean

---

## Wave 6: Documentation + Bug Patterns + Review Tooling

**Goal**: Update all documentation to reflect changes. Add new bug patterns, risk patterns, and review checklist items to prevent recurrence of all discovered issues.
**Depends on**: Wave 5
**Estimated effort**: 30-45 minutes

### Tasks

#### T-R1-6-01: Add BP-012 through BP-015 to BUG_PATTERNS.md

**Type**: docs
**Target files**: `docs/ai-interactions/BUG_PATTERNS.md`

**New patterns**:
- **BP-012**: Python `hash()` for cross-process coordination — use `hashlib.sha256`
- **BP-013**: Advisory lock spanning external I/O — lock only during DB writes
- **BP-014**: Outbox payload fields must match Avro schema field names exactly
- **BP-015**: Client constructor signatures must match wiring code — verify with a test

---

#### T-R1-6-02: Add HR-017, HR-018 to HIGH_RISK_PATTERNS.md

**Type**: docs
**Target files**: `.claude/review/heuristics/HIGH_RISK_PATTERNS.md`

**New patterns**:
- **HR-017** (RED): Python `hash()` for distributed coordination
- **HR-018** (ORANGE): `setattr` with user-controlled keys without allowlist

---

#### T-R1-6-03: Update REVIEW_CHECKLIST.md

**Type**: docs
**Target files**: `.claude/review/checklists/REVIEW_CHECKLIST.md`

**New items**:
- §1 Resource Management: "Advisory/distributed locks do not span external I/O"
- §1 Resource Management: "Lock duration is bounded and predictable (ms, not seconds)"
- §3 Storage Atomicity: "Outbox payload field names match Avro schema exactly"
- §4 Idempotency: "Outbox payload includes all required Avro envelope fields"
- §6 Security: "Token comparisons use `hmac.compare_digest()`"
- §6 Security: "Query pagination has upper bound (max limit)"
- §6 Security: "URL inputs validate scheme and reject private IP ranges"
- §7 Architecture: "`setattr` uses field allowlist, never user-controlled keys"

---

#### T-R1-6-04: Update S4 `.claude-context.md`

**Type**: docs
**Target files**: `services/content-ingestion/.claude-context.md`

**Updates**:
- Scheduler: advisory lock held only during writes (from `messaging.pg`)
- Watermarks: adapters use `source_adapter_state.last_watermark` for incremental polling
- Auth: `admin_token` (admin-only) vs `internal_service_token` (shared, `INTERNAL_SERVICE_TOKEN`)
- Pitfalls: add hash(), Avro payload alignment, httpx client lifecycle, DLQ population, session rollback after errors
- Docker compose: hybrid approach (centralized + standalone)

---

#### T-R1-6-05: Update `docs/services/content-ingestion.md`

**Type**: docs
**Target files**: `docs/services/content-ingestion.md`

**Updates**:
- Add 5 missing endpoints (DLQ + internal health)
- Auth section: two-token model
- Scheduler: lock-only-during-writes + watermarks
- Configuration: `INTERNAL_SERVICE_TOKEN` env var
- DLQ: how events reach DLQ and how requeue works
- Testing: hybrid docker-compose approach

---

#### T-R1-6-06: Update env example files

**Type**: config
**Target files**:
- `services/content-ingestion/configs/dev.local.env.example`

**Add**:
- `INTERNAL_SERVICE_TOKEN=dev-internal-token`
- Comment explaining admin vs internal token

### Validation Gate
- [ ] All doc files valid markdown
- [ ] BP-012 through BP-015 added
- [ ] HR-017, HR-018 added
- [ ] 8 new checklist items added
- [ ] `.claude-context.md` reflects all changes
- [ ] Service doc reflects all changes

---

## Cross-Cutting Concerns

### Contract Changes
- **Avro schema**: No schema change needed — the schema already has the correct fields. The code was emitting wrong field names.

### Migration Needs
- **New migration**: Add `payload_json` column to `dead_letter_queue` table (Wave 0)

### Configuration Changes
- **New env var**: `INTERNAL_SERVICE_TOKEN` (shared, no prefix)
- **Existing**: `CONTENT_INGESTION_ADMIN_TOKEN` (unchanged)

### Docker Infrastructure
- **New profile**: `content-ingestion-test` in `infra/compose/docker-compose.test.yml`
- **Updated**: S4 Makefile with hybrid compose targets
- **Updated**: `scripts/test-full.sh` to include S4

---

## Risk Assessment

### Critical Path
Wave 0 (runtime fixes) → everything else. The service cannot run without Wave 0.

### Highest Risk
**Wave 0 (T-R1-0-01)**: Avro payload alignment changes the hot path. Must verify serialization roundtrip with the actual Avro schema.
**Wave 2 (T-R1-2-01)**: Lock restructure changes the concurrency model. Need integration tests to validate.

### Rollback Strategy
Each wave produces a working state. Wave 0 is the minimum viable fix set. Waves 1-6 are incremental improvements.

### Testing Gaps
- Integration tests for concurrent replicas with advisory locks (deferred to PLAN-0001-B Wave A-4)
- E2E test for full pipeline: fetch → MinIO → outbox → Kafka → S5 (deferred to Wave A-4)

---

## Summary

| Wave | Tasks | Key Deliverables | Effort |
|------|-------|-----------------|--------|
| **W0** | 6 | Service can actually run: Avro fix, httpx, DLQ, session rollback | 45-60 min |
| **W1** | 5 | Shared advisory lock lib, token split, timing fix, atomic quota | 30-45 min |
| **W2** | 5 | Lock only during writes, watermarks, batch commit | 45-60 min |
| **W3** | 7 | Backoff, supervision, dispose, exception handlers, hot-add | 45-60 min |
| **W4** | 6 | Security hardening, port abstractions | 45-60 min |
| **W5** | 6 | 40+ new tests, docker compose hybrid | 60-90 min |
| **W6** | 6 | BP-012–015, HR-017–018, 8 checklist items, docs | 30-45 min |
| **Total** | **41** | | **~5-7 hours** |
