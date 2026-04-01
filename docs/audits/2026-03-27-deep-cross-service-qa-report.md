# Deep Cross-Service QA Report

**Date**: 2026-03-27
**Scope**: services/portfolio, services/market-ingestion, services/market-data (ALL flows)
**Branch**: feat/content-ingestion-wave-a1
**Agents**: QA/Test, Security, Data Platform, Distributed Systems, Architecture
**Verdict**: FAIL (9 BLOCKING/CRITICAL issues require remediation before production)

---

## Executive Summary

This is a deeper QA pass than QA-CROSS-001 (2026-03-27). The prior pass fixed 16 high-severity items but was scoped to known issues. This pass covered ALL flows across all three services using 5 parallel specialist agents.

**87 total findings** (after cross-agent dedup):
- 6 BLOCKING
- 18 CRITICAL
- 35 MAJOR
- 16 MINOR/NIT
- 12 requires-decision items

**Newly added bug patterns**: BP-034 through BP-040

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR |
|-------|---------------|----------|----------|----------|-------|-------|
| QA/Test | ~60 | 10 | 0 | 3 | 6 | 1 |
| Security | ~40 | 22 | 0 | 6 | 5 | 11 |
| Data Platform | ~50 | 15 | 3 | 4 | 7 | 1 |
| Distributed Systems | ~45 | 20 | 3 | 9 | 8 | 0 |
| Architecture | ~60 | 20 | 0 | 4 | 8 | 8 |
| **Total (deduped)** | — | **87** | **6** | **18** | **35** | **16** |

---

## BLOCKING Issues (must fix before production)

### B-001 — Consumer dedup early return skips `mark_processed` (BP-034)
- **Services**: market-data (ohlcv_consumer, quotes_consumer, fundamentals_consumer)
- **File**: `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py:143-146`
- **Issue**: Content-hash dedup path returns early without recording event_id. Same message replayed passes dedup check again.
- **Fix**: Call `await self.mark_processed(event_id)` before the early `return` in all 3 consumers.

### B-002 — Token bucket `try_consume()` non-atomic with DB (BP-036)
- **Service**: market-ingestion (ProviderBudget)
- **File**: `services/market-ingestion/src/market_ingestion/domain/entities/provider_budget.py:33-44`
- **Issue**: Two workers both pass `tokens >= n` check before either persists decrement — over-consumption under concurrent load.
- **Fix**: Load budget row with `SELECT ... FOR UPDATE` inside the consuming transaction.

### B-003 — Idempotency check race in `record_transaction` (BP-035)
- **Service**: portfolio
- **File**: `services/portfolio/src/portfolio/application/use_cases/record_transaction.py:66-77`
- **Issue**: Idempotency key parsing error is silently suppressed (`except (ValueError, AttributeError): pass`), causing the request to proceed without any idempotency guarantee.
- **Fix**: Fail fast on unparseable idempotency key (400) or explicitly document the "no idempotency" fallback.

### B-004 — IngestionTask `result_ref`/`completed_at` not persisted to DB (BP-034 deferred)
- **Service**: market-ingestion
- **File**: `services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/task_repository.py:149-162`
- **Issue**: `task.succeed(canonical_ref)` sets in-memory state but `save()` omits `result_ref` columns. The ORM model has no such columns.
- **Fix**: Add DB columns + migration + populate in `save()`. Or emit result via Kafka only (no persistence needed on task).
- **Requires decision**: YES

### B-005 — `EVENT_TOPIC_MAP` fallback silently routes to wrong Kafka topic (BP-039)
- **Service**: portfolio
- **File**: `services/portfolio/src/portfolio/infrastructure/db/repositories/outbox.py:33`
- **Issue**: `EVENT_TOPIC_MAP.get(row.event_type, row.event_type)` creates spurious topics for unregistered event types.
- **Fix**: Raise explicitly on missing event_type in map.

### B-006 — Concurrent outbox dispatcher re-claim (lease duration)
- **Services**: all
- **Issue**: If lease duration is too short relative to dispatch latency, multiple dispatcher instances can claim the same outbox batch. Need metric to track re-claims.
- **Fix**: Verify lease duration > 99th-percentile dispatch time. Add `outbox_record_reclaimed` metric.

---

## CRITICAL Issues

### C-001 — Hardcoded MinIO credentials in all 3 services + shared lib (BP-013 variant)
- **Files**: `services/portfolio/src/portfolio/config.py:50-51`, `services/market-ingestion/...config.py:33-34`, `services/market-data/...config.py:35-36`, `libs/storage/src/storage/settings.py:29-33`
- **Issue**: `storage_access_key: str = "minioadmin"` — production deployment with unset env vars exposes all object storage.
- **Fix**: Remove defaults. Require env vars at startup.

### C-002 — Tenant creation/retrieval endpoints unauthenticated (SEC-005 confirmed)
- **Files**: `services/portfolio/src/portfolio/api/routes/tenant.py:16-37`
- **Issue**: POST `/tenants` and GET `/tenants/{id}` have no auth checks. Any client can create/enumerate tenants.
- **Requires decision**: YES — make internal-only (X-Internal-Token) or add gateway auth.

### C-003 — Consumer dedup check-then-insert race (BP-035)
- **Files**: `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py:84-95`
- **Issue**: `is_duplicate()` SELECT and `create()` INSERT are in separate transactions — two concurrent consumers can both pass the check.
- **Fix**: Move dedup INSERT to be first operation in processing transaction; treat unique constraint violation as "duplicate, skip".

### C-004 — Quote NULL→zero mapping loses information (BP-004 variant)
- **File**: `services/market-data/src/market_data/infrastructure/db/repositories/quote_repo.py:27-36`
- **Issue**: NULL quote fields silently become `Decimal("0")`. Zero quotes are indistinguishable from "no data".
- **Requires decision**: YES — use `Decimal | None` in domain entity or add `quote_available: bool` flag.

### C-005 — Watermark state mutation not atomic with task DB commit
- **File**: `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py:125-178`
- **Issue**: Watermark is mutated in-memory then saved; if commit fails after `task.succeed()` call, task re-claims but in-memory state is already SUCCEEDED.
- **Fix**: Perform state mutations inside `async with self._uow:` block; use SELECT-FOR-UPDATE on task and watermark rows.

### C-006 — Task lease cleared before outbox event guaranteed sent
- **File**: `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py:350-361`
- **Issue**: `task.retry()` clears `lease_owner/expires`, making task re-claimable. If commit fails, another worker immediately re-executes the same task.
- **Fix**: Clear lease only in post-commit callback via `uow.on_commit()`.

### C-007 — Kafka offset committed before idempotency record fully committed
- **File**: `libs/messaging/src/messaging/kafka/consumer/base.py:486-489`
- **Issue**: Offset committed after `_handle_message()` returns, but idempotency INSERT could race. If idempotency fails, message is lost (offset past it).
- **Requires decision**: YES — ordering strategy needed.

### C-008 — Fundamentals consumer `period_end` type uncertainty
- **File**: `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py:112-127`
- **Issue**: `hasattr(record.period_end, "date")` duck-type check — if `period_end` is a string from EODHD, `.date()` fails with `AttributeError`.
- **Fix**: Parse `period_end` to UTC-aware datetime in entity constructor.

### C-009 — Portfolio Avro schema `payload: string` vs mapper flat dict mismatch (F-ARCH-009)
- **File**: `infra/kafka/schemas/portfolio.events.v1.avsc:12`
- **Issue**: Schema expects `{"payload": "<json-string>"}` but portfolio mappers produce flat dicts. Serialization will fail at runtime.
- **Requires decision**: YES — flatten schema or nest in mapper.

### C-010 — `assert self._current_uow is not None` in production code
- **File**: `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py:91`
- **Issue**: `python -O` strips assertions. Same pattern likely in quotes/fundamentals consumers.
- **Fix**: Replace with `if ... is None: raise RuntimeError(...)`.

### C-011 — Missing repository port ABCs in market-ingestion (F-ARCH-014)
- **File**: `services/market-ingestion/src/market_ingestion/application/ports/repositories.py`
- **Issue**: No abstract interfaces for repositories — violates hexagonal architecture, impossible to mock ports in tests.
- **Fix**: Define abstract repository ABCs; update concrete implementations to inherit.

### C-012 — Portfolio docs port 8000 vs actual port 8001 (F-ARCH-001)
- **File**: `docs/services/portfolio.md:3`
- **Fix**: Update to 8001.

### C-013 — Orphaned objects in MinIO on task execution failure
- **File**: `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py:98-120`
- **Issue**: Bronze/canonical writes happen OUTSIDE the DB transaction. On commit failure, orphaned objects accumulate in MinIO.
- **Fix**: Implement skip-if-exists on retry (idempotent write). Add periodic GC job.

### C-014 — Outbox status enum inconsistent across services (F-DATA-005)
- **Files**: `services/portfolio/...outbox.py:72` uses `"processing"`, market-ingestion uses `"in_flight"`, libs/messaging expects `"in_flight"`.
- **Fix**: Align to `"in_flight"` / `"published"` standard from libs/messaging.

### C-015 — Provider adapter stubs (Polygon, Alpha Vantage) registered but untested
- **Files**: `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/polygon.py`, `alpha_vantage.py`
- **Issue**: Stubs raise `ProviderUnavailable` but are reachable via registry — no tests validate this.
- **Requires decision**: YES — remove from registry or add stub tests.

### C-016 — Yahoo provider adapter has zero tests
- **File**: `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/yahoo.py`
- **Fix**: Create `tests/infrastructure/test_yahoo.py` covering success + error paths.

### C-017 — Idempotency INSERT missing `ON CONFLICT DO NOTHING` (BP-040)
- **Files**: `services/portfolio/src/portfolio/infrastructure/db/repositories/idempotency.py`, `services/market-data/.../ingestion_event_repo.py`
- **Issue**: Replay raises `IntegrityError` instead of silent skip.
- **Fix**: Add `.on_conflict_do_nothing()`.

### C-018 — `build_market_ingestion_serializers()` only registers `MarketDatasetFetched`
- **File**: `services/market-ingestion/src/market_ingestion/infrastructure/messaging/serialization.py:54-73`
- **Issue**: 3 event types defined but only 1 has an Avro serializer. `IngestionTaskCompleted`/`IngestionTaskScheduled` will fail dispatch.
- **Requires decision**: YES — add schemas for internal events, or keep them off the outbox.

---

## MAJOR Issues (35 total — abbreviated)

| ID | Service | Category | Issue |
|----|---------|----------|-------|
| M-001 | portfolio | security | Missing Field constraints on TenantCreateRequest.name, UserCreateRequest.email, PortfolioCreateRequest.name, PortfolioRenameRequest.name, WatchlistCreateRequest.name |
| M-002 | market-data | security | LIKE pattern not escaped in instrument search (symbol `%` → matches all) |
| M-003 | all | security | DB connection strings embed credentials in defaults |
| M-004 | market-ingestion | security | EODHD API key defaults to `"demo"` |
| M-005 | portfolio | ds | Cache invalidation not atomic with DB write (watchlist members) |
| M-006 | market-ingestion | ds | task `claim_batch` SELECT-FOR-UPDATE may race under READ COMMITTED isolation |
| M-007 | portfolio | ds | UoW `__aexit__` rollback failure masks original exception (BP-037) |
| M-008 | market-ingestion | ds | Market-ingestion UoW asymmetric session cleanup |
| M-009 | portfolio | ds | Dual outbox inserts for record_transaction can partially fail |
| M-010 | portfolio | ds | TOCTOU on watchlist name uniqueness |
| M-011 | market-ingestion | ds | Outbox dispatcher non-atomic `increment_attempts` (race on attempt count) |
| M-012 | portfolio | arch | API dependencies imports `SqlAlchemyUnitOfWork` at module level (not lazy) |
| M-013 | portfolio/market-data | arch | Event envelope types inconsistent: UUID objects vs strings |
| M-014 | portfolio | arch | Mapper uses `.isoformat()` instead of `common.time.to_iso8601()` |
| M-015 | market-data | arch | `event_type: str = ""` as instance default instead of ClassVar |
| M-016 | market-data | arch | Fundamentals path param named `security_id` but represents instrument UUID |
| M-017 | portfolio | arch | InstrumentConsumer generates new `new_uuid7()` on every message (non-idempotent) |
| M-018 | portfolio | test | InstrumentEventConsumer: no tests for malformed event payloads |
| M-019 | portfolio | test | Instrument API integration tests missing error paths and pagination edge cases |
| M-020 | market-ingestion | test | ExecuteTaskUseCase: no tests for state-consistency after outbox/watermark failure |
| M-021 | portfolio | test | `test_list_transactions`: `assert data["total"] >= 1` weak assertion |
| M-022 | portfolio | test | Missing pytest markers in `test_instrument_consumer.py` |
| M-023 | portfolio | test | Holding.apply_delta() missing multi-leg weighted-average and precision edge cases |
| M-024 | market-ingestion | data | `row_count=0` serialized as `None` in Avro schema (0 vs null ambiguity) |
| M-025 | market-ingestion | data | Watermark unique constraint NULLS NOT DISTINCT — PG15+ only, verify version |
| M-026 | market-data | data | TimescaleDB hypertable unique constraint cross-chunk enforcement |
| M-027 | all | arch | Config setting inconsistency: `kafka_schema_registry_url` vs `schema_registry_url` |
| M-028 | all | arch | `.claude-context.md` inconsistent structure (missing Pitfalls/Bug Patterns in market services) |
| M-029 | market-ingestion | ds | Watermark regression via `utc_now()` for tasks without `range_end` |
| M-030 | portfolio | arch | Route prefix pattern inconsistency (mixed absolute/relative paths) |
| M-031 | market-ingestion | data | Outbox event_type stored only in headers — fragile round-trip |
| M-032 | portfolio | arch | Untyped `_to_response()` parameters with `# type: ignore[no-untyped-def]` |
| M-033 | market-ingestion | test | Semaphore acquisition has no timeout → potential deadlock under sustained load |
| M-034 | market-ingestion | data | Portfolio outbox payload is `string` type (double-serialization, no field-level evolution) |
| M-035 | portfolio | security | Internal service token defaults to `""` (empty = no protection if env var unset) |

---

## Decisions Needed

| ID | Question | Context |
|----|----------|---------|
| D-001 | Should tenant CRUD endpoints be internal-only or require gateway auth? | C-002 — currently fully public |
| D-002 | `result_ref`/`completed_at`: persist to DB or emit only via Kafka? | B-004 |
| D-003 | Portfolio Avro schema: flatten to top-level fields (like market services) or keep `payload: string`? | C-009 |
| D-004 | Quote NULL: use `Decimal \| None` in domain, or add `quote_available: bool`? | C-004 |
| D-005 | Internal events (IngestionTaskCompleted/Scheduled): add Avro schemas + outbox, or route only to in-memory bus? | C-018 |
| D-006 | Polygon/Alpha Vantage stubs: remove from registry until implemented, or add guard tests? | C-015 |
| D-007 | Idempotency key parse failure: fail-fast 400 or proceed without idempotency? | B-003 |
| D-008 | Orphaned MinIO objects: implement periodic GC job or skip-if-exists on retry? | C-013 |
| D-009 | Event envelope standard: UUID objects (portfolio style) or strings (market services style)? | M-013 |

---

## Test Execution Results

Tests were not re-run in this pass (scope was deep code review only).
Previous run results from QA-CROSS-001:
- market-ingestion: 321 passed ✅
- market-data: 253 passed ✅
- portfolio: SKIP (dep conflict — see B-004)

---

## Compounding Updates Applied

- Added BP-034 through BP-040 to `docs/ai-interactions/BUG_PATTERNS.md`
- Added QA-CROSS-002 row to `docs/plans/TRACKING.md`
- Plan being generated: see `/plan` invocation below

---

## Next Steps

1. **Generate implementation plan** (`/plan`) with all findings → creates PLAN-0001-E (or similar)
2. **Fix BLOCKING issues first** (B-001 through B-006) — these are production-breaking
3. **Address CRITICAL security** (C-001 hardcoded creds, C-002 unauthenticated tenant endpoints)
4. **Portfolio tests**: Resolve dep conflict → run unit test suite
5. **MAJOR issues** can be addressed in parallel waves grouped by service
