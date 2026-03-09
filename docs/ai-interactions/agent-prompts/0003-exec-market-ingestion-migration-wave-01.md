# Execution Prompt 0003 — market-ingestion-migration wave 01

## Context (read first)

- **Planning prompt**: `docs/ai-interactions/agent-planning/0003-market-ingestion-migration-detailed-plan-and-atomic-tasks.md`
- **Planning response (authoritative)**: `docs/ai-interactions/agent-responses/0003-response-20260306-market-ingestion-migration-plan.md`

---

## Assigned agent profile(s)

- `.claude/agents/data-platform-engineer.md`
- `.claude/agents/architecture-decision-lead.md`

---

## Mandatory pre-read

Read **all** of these before writing a single line of code:

1. `AGENTS.md` — coding standards, naming conventions, architecture pattern
2. `CLAUDE.md` — Claude-specific workflow, diff discipline, logging rules
3. `docs/services/market-ingestion.md` — target service specification
4. `docs/libs/contracts.md` — canonical model spec (T-LIB-01, T-LIB-02 scope)
5. `docs/libs/storage.md` — ObjectStorage interface spec (T-LIB-03 scope)
6. `docs/libs/messaging.md` — Kafka producer + outbox spec (T-LIB-04, T-LIB-05 scope)
7. `docs/libs/observability.md` — metrics + tracing spec (T-LIB-06, T-LIB-07 scope)
8. `docs/ai-interactions/agent-planning/0003-market-ingestion-migration-detailed-plan-and-atomic-tasks.md`
9. `docs/ai-interactions/agent-responses/0003-response-20260306-market-ingestion-migration-plan.md` — §4 task backlog, Milestone 0 and Milestone 1 sections

---

## Objective

Complete **Milestone 0 (Library Prerequisites)** and **Milestone 1 (Domain Layer)** of the Market Ingestion migration.

This wave lays the foundational shared-library capabilities (canonical models, object storage, Kafka producer, outbox, metrics, tracing) that all subsequent waves depend on, and simultaneously establishes the complete framework-free domain layer of the `market-ingestion` service (enums, value objects, errors, entities, events).

At the end of this wave:
- All 7 shared library gaps are closed or have implementations ready for use.
- The entire `market_ingestion/domain/` package is populated, tested, and lint-clean.
- No service code outside `domain/` is written yet.

---

## Task scope for this wave

**Total tasks: 15**

### Parallel group A — no external dependencies (start simultaneously)

| Task ID | Short title | Target paths |
|---------|-------------|--------------|
| T-LIB-01 | CanonicalQuote dataclass | `libs/contracts/src/contracts/canonical/quotes.py`, tests |
| T-LIB-02 | CanonicalFundamentals dataclass | `libs/contracts/src/contracts/canonical/fundamentals.py`, tests |
| T-LIB-03 | S3ObjectStorage + health + exceptions | `libs/storage/src/storage/object_storage.py`, `exceptions.py`, `health.py`, tests |
| T-LIB-04 | KafkaProducerConfig + build_serializing_producer | `libs/messaging/src/messaging/producer.py`, tests |
| T-LIB-06 | Prometheus ServiceMetrics + middleware | `libs/observability/src/observability/metrics.py`, tests |
| T-LIB-07 | configure_tracing + get_tracer + OTel middleware | `libs/observability/src/observability/tracing.py`, tests |
| T-MI-01 | Domain enums | `services/market-ingestion/src/market_ingestion/domain/enums.py`, tests |
| T-MI-03 | Domain errors + RetryableError/FatalError classification | `services/market-ingestion/src/market_ingestion/domain/errors.py`, tests |

### Sequential group B — after parallel group A completes

| Task ID | Unlocked by | Short title |
|---------|-------------|-------------|
| T-LIB-05 | T-LIB-04 done | BaseOutboxDispatcher with lease-based dispatch |
| T-MI-02 | T-MI-01 done | Domain value objects |

### Parallel group C — after group B completes

| Task ID | Unlocked by | Short title |
|---------|-------------|-------------|
| T-MI-04 | T-MI-01, T-MI-02, T-MI-03 | IngestionTask entity + state machine |
| T-MI-05 | T-MI-01, T-MI-02 | PollingPolicy entity |
| T-MI-06 | T-MI-01 | ProviderBudget entity |
| T-MI-07 | T-MI-01, T-MI-02 | Watermark entity |
| T-MI-08 | T-MI-02 | Domain events + envelope standard |

---

## Why this chunk

**Coherence**: Groups A and B establish shared library foundations (no service dependencies) and the domain layer (no library dependencies), which are completely orthogonal subsystems that can be developed simultaneously. Domain layer code is pure Python with zero lib imports, so it can run in parallel with lib tasks without any risk of import conflicts.

**Dependency fit**: Every M2 (application), M3 (infrastructure), M4 (entrypoints) task requires at least one of: a lib from M0 or an entity from M1. Grouping all of M0+M1 in wave 01 clears the critical path for wave 02.

**Size**: 15 tasks — within the [10, 20] bound.

**Parallelism**: 8 tasks can start concurrently; group B requires a single prior step each; group C unlocks 5 tasks in batch.

---

## Implementation instructions

### T-LIB-01 — CanonicalQuote

1. Read `platform_repo/libs/contracts/src/contracts/canonical/quotes.py` (legacy reference).
2. Read `worldview/libs/contracts/src/contracts/canonical/ohlcv.py` for the frozen-dataclass pattern.
3. Create `worldview/libs/contracts/src/contracts/canonical/quotes.py`:
   - Frozen dataclass `CanonicalQuote`.
   - Do NOT carry `tenant_id` or `currency` from legacy.
   - Include `schema_version` as a frozen non-init field equal to `QUOTE_SCHEMA_VERSION` constant.
   - Implement `from_dict(d: dict) -> CanonicalQuote` and `to_dict() -> dict`.
4. Re-export `CanonicalQuote` and `QUOTE_SCHEMA_VERSION` from `canonical/__init__.py`.
5. Create `worldview/libs/contracts/tests/test_quotes.py`: construction, `to_dict()`/`from_dict()` roundtrip, `schema_version` is frozen, None optional fields.
6. Update `libs/contracts/IMPLEMENTATION.md`: check the `CanonicalQuote` item.
7. Run: `cd libs/contracts && make test && make lint`.

**DoD**: `CanonicalQuote` frozen dataclass with `from_dict()`/`to_dict()`, `schema_version` matches constant, all tests pass, IMPLEMENTATION.md updated.

---

### T-LIB-02 — CanonicalFundamentals

1. Read `platform_repo/libs/contracts/src/contracts/canonical/fundamentals.py`.
2. Create `worldview/libs/contracts/src/contracts/canonical/fundamentals.py`:
   - Frozen dataclass `CanonicalFundamentals` following `ohlcv.py` pattern.
   - Keep `payload: dict` field (thin passthrough — legacy pattern).
   - Include `schema_version` = `FUNDAMENTAL_SCHEMA_VERSION`.
   - Implement `from_dict()` / `to_dict()`.
3. Re-export from `canonical/__init__.py`.
4. Create `worldview/libs/contracts/tests/test_fundamentals.py`: construction, serialization, variant handling.
5. Update `libs/contracts/IMPLEMENTATION.md`.
6. Run: `cd libs/contracts && make test && make lint`.

**DoD**: `CanonicalFundamentals` frozen dataclass, `schema_version` matched, tests pass, IMPLEMENTATION.md updated.

---

### T-LIB-03 — S3ObjectStorage

1. Read `platform_repo/libs/storage/src/storage/object_storage.py`.
2. Read `worldview/libs/storage/src/storage/key_builder.py`, `settings.py`, `IMPLEMENTATION.md`.
3. Create `worldview/libs/storage/src/storage/exceptions.py`:
   - `StorageError` (base), `ObjectNotFoundError`, `BucketNotFoundError`, `StoragePermissionError`, `StorageUnavailableError`.
4. Create `worldview/libs/storage/src/storage/object_storage.py`:
   - `ObjectStorage` ABC with methods: `put(bucket, key, data, content_type) -> str` (returns etag/SHA-256), `get(bucket, key) -> bytes`, `delete(bucket, key)`, `exists(bucket, key) -> bool`, `list_keys(bucket, prefix) -> list[str]`, `ensure_bucket(bucket)`, `put_json(bucket, key, obj) -> str`, `get_json(bucket, key) -> dict`.
   - `S3ObjectStorage(ObjectStorage)`: async boto3/aiobotocore implementation. SHA-256 computed on `put()`. Raises typed exceptions (not raw botocore errors).
5. Create `worldview/libs/storage/src/storage/health.py`:
   - `check_storage_health(storage: ObjectStorage, bucket: str) -> bool`.
6. Create `build_object_storage(settings: StorageSettings) -> S3ObjectStorage` factory.
7. Re-export all public symbols from `__init__.py`.
8. Create `worldview/libs/storage/tests/test_object_storage.py` (mock boto3 for unit tests; mark real-MinIO tests with `@pytest.mark.integration`).
9. Update `libs/storage/IMPLEMENTATION.md`.
10. Run: `cd libs/storage && make test && make lint`.

**DoD**: `ObjectStorage` ABC + `S3ObjectStorage` + exceptions + health + factory. Unit tests pass. IMPLEMENTATION.md updated.

---

### T-LIB-04 — Kafka Producer

1. Read `platform_repo/libs/messaging/src/messaging/producer.py` and `serialization.py`.
2. Read `worldview/libs/messaging/src/messaging/schemas.py`, `topics.py`.
3. Create `worldview/libs/messaging/src/messaging/producer.py`:
   - `KafkaProducerConfig` (Pydantic BaseSettings): `bootstrap_servers`, `schema_registry_url`, `acks="all"`, `enable_idempotence=True`, `linger_ms=5`, `auto_register_schemas=False`.
   - `build_serializing_producer(config) -> SerializingProducer` factory.
   - `AvroSerializerConfig` and `build_avro_serializer(schema_str, config) -> AvroSerializer`.
   - `topic_event_type_subject_name_strategy(ctx, record) -> str` naming strategy (`{topic}-{event_type}`).
   - `OutboxKafkaValue` dataclass and `OutboxEventValueSerializer` from legacy.
4. Re-export from `__init__.py`.
5. Create `worldview/libs/messaging/tests/test_producer.py`: config construction, serializer building, subject name strategy; mark integration tests for real Kafka.
6. Update `libs/messaging/IMPLEMENTATION.md`.
7. Run: `cd libs/messaging && make test && make lint`.

**DoD**: `KafkaProducerConfig`, `build_serializing_producer()`, `build_avro_serializer()`, subject naming strategy all implemented and tested. IMPLEMENTATION.md updated.

---

### T-LIB-05 — BaseOutboxDispatcher (after T-LIB-04)

1. Read `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/messaging/dispatcher.py`.
2. Read `worldview/docs/libs/messaging.md` for spec requirements.
3. Create `worldview/libs/messaging/src/messaging/outbox.py`:
   - `BaseOutboxDispatcher` (generic, not Market Ingestion-specific):
     - Abstract methods: `_create_uow()`, `_serialize_event(event) -> tuple[topic, key, avro_dict]`
     - Concrete logic: hybrid dispatch (immediate + poll), lease-based claim, 3-phase commit (claim → produce with ack → finalize), dead-letter after max attempts, exponential backoff with jitter.
     - Worker ID: `f"{socket.gethostname()}-{os.getpid()}"`.
     - `start()` / `stop()` async lifecycle.
   - Use `get_logger(__name__)` from `libs/observability`.
4. Re-export from `__init__.py`.
5. Create `worldview/libs/messaging/tests/test_outbox.py`: happy path, produce failure → retry, dead-letter after max attempts, backoff calculation, worker ID format.
6. Update `libs/messaging/IMPLEMENTATION.md`.
7. Run: `cd libs/messaging && make test && make lint`.

**DoD**: `BaseOutboxDispatcher` with hybrid dispatch, lease claiming, dead-letter, backoff. Tests pass. IMPLEMENTATION.md updated.

---

### T-LIB-06 — Prometheus Metrics

1. Read `worldview/libs/observability/src/observability/logging.py` and `docs/libs/observability.md`.
2. Create `worldview/libs/observability/src/observability/metrics.py`:
   - `ServiceMetrics` dataclass: `http_requests_total` (Counter), `http_request_duration_seconds` (Histogram), `kafka_events_produced_total` (Counter), `kafka_events_consumed_total` (Counter), `outbox_dispatched_total` (Counter), `outbox_errors_total` (Counter).
   - `create_metrics(service_name: str) -> ServiceMetrics` factory — registers with prometheus_client.
   - `add_prometheus_middleware(app: FastAPI, metrics: ServiceMetrics)` — instruments all routes, mounts `/metrics` endpoint.
3. Re-export from `__init__.py`.
4. Create `worldview/libs/observability/tests/test_metrics.py`: metric registration, counter increments, histogram observations, middleware attachment.
5. Update `libs/observability/IMPLEMENTATION.md`.
6. Run: `cd libs/observability && make test && make lint`.

**DoD**: `create_metrics()`, `ServiceMetrics`, `add_prometheus_middleware()` implemented and tested. IMPLEMENTATION.md updated.

---

### T-LIB-07 — OpenTelemetry Tracing

1. Read `worldview/libs/observability/src/observability/logging.py` and `docs/libs/observability.md`.
2. Create `worldview/libs/observability/src/observability/tracing.py`:
   - `configure_tracing(service_name: str, otlp_endpoint: str | None = None)` — sets up OTel SDK with OTLP gRPC exporter (no-op if endpoint is None).
   - `get_tracer(name: str) -> trace.Tracer` — returns OTel tracer.
   - `add_otel_middleware(app: FastAPI)` — instruments FastAPI with `OpenTelemetryMiddleware`.
   - Auto-inject `trace_id` and `span_id` into structlog context processors.
3. Re-export from `__init__.py`.
4. Create `worldview/libs/observability/tests/test_tracing.py`: tracer configuration, middleware attachment, context propagation stubs, no-op mode (no endpoint).
5. Update `libs/observability/IMPLEMENTATION.md`.
6. Run: `cd libs/observability && make test && make lint`.

**DoD**: `configure_tracing()`, `get_tracer()`, `add_otel_middleware()` implemented and tested. IMPLEMENTATION.md updated.

---

### T-MI-01 — Domain Enums

1. Read `platform_repo/apps/backend-market-ingestion/src/app/domain/enums.py`.
2. Create `worldview/services/market-ingestion/src/market_ingestion/domain/__init__.py` (empty package marker).
3. Create `worldview/services/market-ingestion/src/market_ingestion/domain/enums.py`:
   - Copy `Provider`, `DatasetType`, `FundamentalsVariant`, `IngestionTaskStatus`, `OutboxStatus` as `StrEnum` (Python 3.11+).
   - Verify all string values match source-of-truth in `docs/services/market-ingestion.md`.
4. Create `worldview/services/market-ingestion/tests/domain/__init__.py` (empty).
5. Create `worldview/services/market-ingestion/tests/domain/test_enums.py`: all enum values accessible, string conversion, iteration, exhaustive membership.
6. Run: `cd services/market-ingestion && make test -- tests/domain/test_enums.py && make lint`.

**DoD**: 5 enums defined, all `StrEnum`, tests pass, lint clean.

---

### T-MI-03 — Domain Errors

1. Read `platform_repo/apps/backend-market-ingestion/src/app/domain/errors.py`.
2. Read `CLAUDE.md` §Error Handling for `RetryableError` / `FatalError` classification.
3. Create `worldview/services/market-ingestion/src/market_ingestion/domain/errors.py`:
   - `DomainError(Exception)` base with `is_retryable: bool` property.
   - Retryable: `ProviderRateLimited`, `ProviderUnavailable`, `StorageUnavailable`, `TaskLeaseLost`.
   - Fatal: `ProviderAuthError`, `ProviderDataError`, `InvalidStateTransition`, `WatermarkViolation`, `DuplicateTask`.
4. Create `worldview/services/market-ingestion/tests/domain/test_errors.py`: construction, message, `is_retryable` property for every class.
5. Run: `cd services/market-ingestion && make test -- tests/domain/test_errors.py && make lint`.

**DoD**: Full error hierarchy, correct `is_retryable` on every class, tests cover all error types, lint clean.

---

### T-MI-02 — Domain Value Objects (after T-MI-01)

1. Read `platform_repo/apps/backend-market-ingestion/src/app/domain/value_objects.py`.
2. Read `worldview/libs/common/src/common/time.py` for `utc_now()`, `ensure_utc()`.
3. Create `worldview/services/market-ingestion/src/market_ingestion/domain/value_objects.py`:
   - `Timeframe`: validated string VO; valid set = `{1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 1mo, 1y}`; raises `ValueError` on unknown string.
   - `ObjectRef`: frozen dataclass with `bucket: str`, `key: str`, `sha256: str`, `byte_length: int`, `mime_type: str`.
   - `InstrumentKey`: frozen dataclass with `symbol: str`, `exchange: str | None`.
   - `DateRange`: frozen dataclass with `start: datetime`, `end: datetime`; validates `start < end`, both UTC.
4. Create `worldview/services/market-ingestion/tests/domain/test_value_objects.py`: Timeframe valid/invalid, ObjectRef field access, DateRange boundary checks, InstrumentKey optional exchange.
5. Run: `cd services/market-ingestion && make test -- tests/domain/ && make lint`.

**DoD**: 4 VOs, Timeframe validates, DateRange rejects invalid, ObjectRef immutable, tests pass.

---

### T-MI-04 — IngestionTask Entity (after T-MI-01, T-MI-02, T-MI-03)

1. Read `platform_repo/apps/backend-market-ingestion/src/app/domain/entities/ingestion_task.py`.
2. Read `worldview/libs/common/src/common/ids.py` for UUIDv7 generation.
3. Create `worldview/services/market-ingestion/src/market_ingestion/domain/entities/__init__.py`.
4. Create `worldview/services/market-ingestion/src/market_ingestion/domain/entities/ingestion_task.py`:
   - Copy entity, replacing UUID v4 with `uuid7()` (or `common.ids.new_uuid7()`).
   - Preserve: state machine (PENDING→RUNNING→SUCCEEDED/RETRY/FAILED), `claim(worker_id, lease_seconds)`, `succeed(result_ref)`, `retry(error)`, `fail(error)`, `is_lease_expired()`.
   - Backoff: `base_backoff_seconds * 2^(attempts - 1)` capped at `max_backoff_seconds=3600`, ±20% jitter.
   - Max 5 attempts. `next_attempt_at` set on retry.
   - `dedupe_key` factory: `f"{provider}:{dataset_type}:{symbol}:{timeframe}:{date_range_hash}"`.
   - Factory class methods: `create_quote_task()`, `create_ohlcv_task()`, `create_fundamentals_task()`.
   - All timestamps via `utc_now()`.
5. Create `worldview/services/market-ingestion/tests/domain/test_ingestion_task.py`:
   - State transitions: PENDING→RUNNING, RUNNING→SUCCEEDED, RUNNING→RETRY, RUNNING→FAILED.
   - Invalid transitions raise `InvalidStateTransition`.
   - Lease expiration: `is_lease_expired()` returns True when past `locked_until`.
   - Backoff: verify formula for attempts 1–5, jitter within ±20%, cap at 3600s.
   - Dedupe key determinism.
   - Factory methods set correct fields.
   - Max attempts: 6th retry raises `DomainError`.
   - At least 15 test functions.
6. Run: `cd services/market-ingestion && make test -- tests/domain/ && make lint`.

**DoD**: Full state machine, UUIDv7 IDs, exponential backoff, ≥15 unit tests, lint clean.

---

### T-MI-05 — PollingPolicy Entity (after T-MI-01, T-MI-02)

1. Read `platform_repo/apps/backend-market-ingestion/src/app/domain/entities/polling_policy.py`.
2. Create `worldview/services/market-ingestion/src/market_ingestion/domain/entities/polling_policy.py`:
   - Replace UUID v4 with `uuid7()`.
   - Preserve: adaptive interval `base_interval / (1 + k * hotness)`, priority ordering (`__lt__` / comparable), wildcard symbol (`symbol=None` matches all), backfill config fields, `is_due(last_run_at)` checking.
3. Create `worldview/services/market-ingestion/tests/domain/test_polling_policy.py`: adaptive interval, priority ordering, wildcard match, backfill fields, `is_due()`.
4. Run: `cd services/market-ingestion && make test -- tests/domain/ && make lint`.

**DoD**: PollingPolicy with adaptive scheduling, tests pass.

---

### T-MI-06 — ProviderBudget Entity (after T-MI-01)

1. Read `platform_repo/apps/backend-market-ingestion/src/app/domain/entities/provider_budget.py`.
2. Create `worldview/services/market-ingestion/src/market_ingestion/domain/entities/provider_budget.py`:
   - Replace UUID v4 with `uuid7()`.
   - Token-bucket: `consume(n=1)`, `try_consume(n=1) -> bool`, `refill(elapsed_seconds)`, `time_until_available() -> float`.
   - Provider defaults factory method: EODHD (burst=1000, refill=10/s), Alpha Vantage (burst=5, refill=0.083/s).
3. Create `worldview/services/market-ingestion/tests/domain/test_provider_budget.py`: consumption, refill, burst limit, `try_consume()` failure, `time_until_available()`, provider defaults.
4. Run: `cd services/market-ingestion && make test -- tests/domain/ && make lint`.

**DoD**: Token-bucket logic with provider defaults, tests pass.

---

### T-MI-07 — Watermark Entity (after T-MI-01, T-MI-02)

1. Read `platform_repo/apps/backend-market-ingestion/src/app/domain/entities/watermark.py`.
2. Create `worldview/services/market-ingestion/src/market_ingestion/domain/entities/watermark.py`:
   - Replace UUID v4 with `uuid7()`.
   - Natural key: `(provider, dataset_type, variant, symbol, exchange, timeframe)` — 6-tuple.
   - `advance_bar_ts(new_ts)`: monotonic — raises `WatermarkViolation` if `new_ts <= current_bar_ts`.
   - SHA-256 dedup: `content_hash` field; `has_changed(new_hash: str) -> bool`.
   - Backfill phase state machine: `PENDING→IN_PROGRESS→COMPLETED`; `start_backfill()`, `complete_backfill()`.
3. Create `worldview/services/market-ingestion/tests/domain/test_watermark.py`: natural key, monotonic advancement, monotonicity violation, SHA comparison, backfill transitions, invalid backfill transition raises error.
4. Run: `cd services/market-ingestion && make test -- tests/domain/ && make lint`.

**DoD**: 6-part natural key, monotonic bar-ts, SHA-256 dedup, backfill state machine, tests pass.

---

### T-MI-08 — Domain Events (after T-MI-02)

1. Read `platform_repo/apps/backend-market-ingestion/src/app/domain/events.py`.
2. Read `AGENTS.md` §9 Event Envelope Standard.
3. Create `worldview/services/market-ingestion/src/market_ingestion/domain/events.py`:
   - `DomainEvent` frozen dataclass base with envelope fields: `event_id: str` (UUIDv7, auto-generated), `event_type: str`, `schema_version: int`, `occurred_at: str` (ISO-8601 UTC, auto-generated via `utc_now()`), `correlation_id: str | None = None`, `causation_id: str | None = None`.
   - `MarketDatasetFetched(DomainEvent)`: `provider`, `dataset_type`, `symbol`, `exchange`, `timeframe`, `bronze_ref: ObjectRef`, `canonical_ref: ObjectRef` + all other legacy fields. `event_type = "market.dataset.fetched"`, `schema_version = 1`.
   - `IngestionTaskCompleted(DomainEvent)`: internal event, `event_type = "market.task.completed"`.
   - `IngestionTaskScheduled(DomainEvent)`: internal event, `event_type = "market.task.scheduled"`.
   - Implement `AvroDictable` protocol on `MarketDatasetFetched`: `to_dict() -> dict` (flattens `ObjectRef` fields), `from_dict(d: dict) -> MarketDatasetFetched`.
4. Create `worldview/services/market-ingestion/tests/domain/test_events.py`:
   - Construction with auto-populated envelope fields.
   - `to_dict()` produces all expected keys (verify against all 27 schema fields from planning response).
   - `from_dict()` roundtrip.
   - UUIDv7 format validation on `event_id`.
   - `AvroDictable` protocol check (`isinstance` check or duck-type).
5. Run: `cd services/market-ingestion && make test -- tests/domain/ && make lint`.

**DoD**: `DomainEvent` base with envelope, `MarketDatasetFetched` with `AvroDictable`, 3 event types, tests pass.

---

## Constraints

- **Do not implement any code outside the task IDs listed in this wave** (T-LIB-01 through T-LIB-07, T-MI-01 through T-MI-08).
- No application layer, no infrastructure layer, no API, no entrypoints.
- Do not modify existing files in `libs/` unless required for re-exports and IMPLEMENTATION.md checklist updates.
- Do not copy Alembic migrations — that is a wave 02 task (T-MI-16).
- Do not write service-level DB models — that is T-MI-15 in wave 02.
- One logical change per edit. Keep lib tasks isolated from service tasks.

---

## Required tests

### Lib tests (run from each lib's directory)

```bash
cd libs/contracts && make test && make lint
cd libs/storage && make test && make lint
cd libs/messaging && make test && make lint
cd libs/observability && make test && make lint
```

### Service domain tests

```bash
cd services/market-ingestion && make test -- tests/domain/ -v
cd services/market-ingestion && make lint
```

### Full lib test suite (validate no regressions)

```bash
./scripts/test-libs.sh
./scripts/lint.sh
```

**Pass criteria:**
- All unit tests pass (`pytest` exit code 0).
- `ruff check` reports zero errors across all changed files.
- `mypy --strict` reports zero errors across all changed files.
- `IMPLEMENTATION.md` checklist items for each lib are updated.
- No regressions in previously passing tests.

---

## Documentation requirements

For every task in this wave, update docs **in the same wave** if any of the following change:

| Change type | File to update |
|-------------|---------------|
| New public API in a lib (`__init__.py` re-export) | `docs/libs/<lib>.md` — add to "Public API" surface table |
| IMPLEMENTATION.md checklist item completed | `libs/<lib>/IMPLEMENTATION.md` — check the relevant item |
| New canonical model added | `docs/libs/contracts.md` — document `CanonicalQuote`, `CanonicalFundamentals` |
| New storage exceptions hierarchy | `docs/libs/storage.md` — document exception taxonomy |
| New metrics / tracing public API | `docs/libs/observability.md` — document `create_metrics()`, `configure_tracing()` |
| Domain error taxonomy | `docs/services/market-ingestion.md` — update domain errors section if it differs from spec |

**Mandatory instruction**: If any implementation changes a behavior, contract, config, schema surface, or test surface described in documentation, you MUST update that documentation in this same wave. List every doc file changed in the handoff evidence.

---

## Required handoff evidence

At wave completion, report all of the following:

### 1. Changed files (complete list)

List every file created or modified, with a one-line description of the change.

### 2. Tests run and results

```
libs/contracts:   X tests, X passed, 0 failed
libs/storage:     X tests, X passed, 0 failed
libs/messaging:   X tests, X passed, 0 failed
libs/observability: X tests, X passed, 0 failed
services/market-ingestion (domain): X tests, X passed, 0 failed
./scripts/lint.sh: exit code 0
```

### 3. Documentation changed (exact files + what was updated)

Example:
- `docs/libs/contracts.md` — added `CanonicalQuote` and `CanonicalFundamentals` to public API surface table.
- `libs/contracts/IMPLEMENTATION.md` — checked T-LIB-01, T-LIB-02 items.

### 4. Unresolved blockers

List anything that could not be implemented as specified and why.

### 5. Documentation quality checklist

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 1 | Accurate | ✅ / ⚠️ / ❌ | |
| 2 | Complete | ✅ / ⚠️ / ❌ | |
| 3 | Consistent | ✅ / ⚠️ / ❌ | |
| 4 | Exemplified | ✅ / ⚠️ / ❌ | |
| 5 | Diagrammed | ✅ / ⚠️ / ❌ | |
| 6 | Tested | ✅ / ⚠️ / ❌ | |
| 7 | Linked | ✅ / ⚠️ / ❌ | |
| 8 | Versioned | ✅ / ⚠️ / ❌ | |

### 6. Commit message proposal

```
feat(libs+domain): complete contracts/storage/messaging/observability libs + market-ingestion domain layer (T-LIB-01..07, T-MI-01..08)

Add CanonicalQuote and CanonicalFundamentals to contracts lib; implement S3ObjectStorage,
BaseOutboxDispatcher, KafkaProducerConfig, ServiceMetrics, and OTel tracing to storage/messaging/
observability libs. Port complete market_ingestion domain layer: enums, value objects, errors,
all 4 entities (UUIDv7 IDs, correct backoff/state-machine logic), and domain events with
worldview envelope standard. 37+ unit tests added; ruff + mypy strict both clean.
```

---

## Definition of done

- [ ] T-LIB-01: `CanonicalQuote` frozen dataclass, tests pass, IMPLEMENTATION.md checked.
- [ ] T-LIB-02: `CanonicalFundamentals` frozen dataclass, tests pass, IMPLEMENTATION.md checked.
- [ ] T-LIB-03: `ObjectStorage` ABC + `S3ObjectStorage` + exceptions + health + factory, unit tests pass, IMPLEMENTATION.md checked.
- [ ] T-LIB-04: `KafkaProducerConfig`, `build_serializing_producer()`, `build_avro_serializer()`, subject strategy, tests pass, IMPLEMENTATION.md checked.
- [ ] T-LIB-05: `BaseOutboxDispatcher` with hybrid dispatch, lease claiming, dead-letter, backoff, tests pass, IMPLEMENTATION.md checked.
- [ ] T-LIB-06: `create_metrics()` + `ServiceMetrics` + Prometheus middleware, tests pass, IMPLEMENTATION.md checked.
- [ ] T-LIB-07: `configure_tracing()` + `get_tracer()` + OTel middleware, tests pass, IMPLEMENTATION.md checked.
- [ ] T-MI-01: 5 enums defined as `StrEnum`, tests pass, lint clean.
- [ ] T-MI-02: 4 value objects with validation, tests pass, lint clean.
- [ ] T-MI-03: Full error hierarchy with `is_retryable`, tests cover all types, lint clean.
- [ ] T-MI-04: `IngestionTask` with state machine + UUIDv7 + backoff, ≥15 unit tests, lint clean.
- [ ] T-MI-05: `PollingPolicy` with adaptive scheduling, tests pass, lint clean.
- [ ] T-MI-06: `ProviderBudget` with token-bucket logic, tests pass, lint clean.
- [ ] T-MI-07: `Watermark` with monotonic bar-ts, SHA-256, backfill state machine, tests pass, lint clean.
- [ ] T-MI-08: `DomainEvent` base + `MarketDatasetFetched` with `AvroDictable` + 2 internal events, tests pass, lint clean.
- [ ] All `IMPLEMENTATION.md` checklists updated for completed lib tasks.
- [ ] Documentation updated for any API/behavior/contract changes (exact files listed in handoff).
- [ ] Documentation quality checklist completed in handoff evidence — all 8 criteria assessed (✅ pass or ⚠️ with justification; no ❌ without a linked fix).
- [ ] `./scripts/lint.sh` passes with zero errors.
- [ ] Commit message proposal included.
