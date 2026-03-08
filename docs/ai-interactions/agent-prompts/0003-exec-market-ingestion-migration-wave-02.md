# Execution Prompt 0003 — market-ingestion-migration wave 02

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
3. `docs/services/market-ingestion.md` — complete target service specification
4. `docs/libs/contracts.md` — canonical models (T-MI-20 uses `CanonicalOHLCVBar`, `CanonicalQuote`, `CanonicalFundamentals`)
5. `docs/libs/storage.md` — ObjectStorage interface (T-MI-18 wraps it)
6. `docs/libs/messaging.md` — KafkaProducerConfig, AvroSerializer, topic names (T-MI-21)
7. `docs/libs/observability.md` — `get_logger()` usage (all infra modules)
8. `docs/libs/common.md` — `utc_now()`, UUIDv7 (T-MI-09 ports)
9. `docs/ai-interactions/agent-planning/0003-market-ingestion-migration-detailed-plan-and-atomic-tasks.md`
10. `docs/ai-interactions/agent-responses/0003-response-20260306-market-ingestion-migration-plan.md` — §4 Milestone 2 and Milestone 3 (partial) sections

**Pre-conditions**: Wave 01 is complete. All wave-01 tasks (T-LIB-01..07, T-MI-01..08) passed tests, lint, and mypy. Libraries are available as editable installs.

---

## Objective

Complete **Milestone 2 (Application Layer)** and a substantial portion of **Milestone 3 (Infrastructure Layer)** of the Market Ingestion migration, excluding the repository/UoW tier (which depends on a complete Alembic migration and is assigned to wave 03).

Specifically:
- Port all application port interfaces and all 5 use cases.
- Create all 5 SQLAlchemy 2.0 DB models and generate the initial Alembic migration.
- Port the object store adapter, EODHD provider adapter (+ stubs), canonical serializer, and Kafka serialization + Avro schema.

At the end of this wave:
- `market_ingestion/application/` is fully populated with ports and use cases, tested with mocked ports.
- `market_ingestion/infrastructure/db/models/` and `alembic/` contain the complete schema.
- `market_ingestion/infrastructure/adapters/` contains the object store adapter, provider adapters, canonical serializer.
- `market_ingestion/infrastructure/messaging/kafka/` contains the Avro mapper, serialization factory, and the Avro schema is in `infra/kafka/schemas/`.

---

## Task scope for this wave

**Total tasks: 12**

### Parallel group A — prerequisites satisfied from wave 01 (start simultaneously)

| Task ID | Short title | Key prerequisite |
|---------|-------------|-----------------|
| T-MI-09 | Port application port interfaces | M1 domain layer complete (wave 01) |
| T-MI-15 | SQLAlchemy 2.0 DB models + session factory | T-MI-01 enums (wave 01) |
| T-MI-18 | S3ObjectStoreAdapter | T-LIB-03 storage lib (wave 01), T-MI-02 ObjectRef (wave 01) |
| T-MI-21 | Kafka serialization + Avro schema relocation | T-LIB-04 Kafka producer (wave 01), T-MI-08 domain events (wave 01) |

### Parallel group B — after group A completes

| Task ID | Unlocked by | Short title |
|---------|-------------|-------------|
| T-MI-10 | T-MI-09 | Port ScheduleDueTasksUseCase |
| T-MI-11 | T-MI-09 | Port ClaimTasksUseCase |
| T-MI-12 | T-MI-09 + T-MI-08 (wave 01) | Port ExecuteTaskUseCase |
| T-MI-13 | T-MI-09 | Port TriggerIngestionUseCase |
| T-MI-14 | T-MI-09 | Port BackfillUseCase |
| T-MI-16 | T-MI-15 | Generate initial Alembic migration |
| T-MI-19 | T-MI-09 + T-MI-03 (wave 01) | Port EODHD provider adapter + stubs |
| T-MI-20 | T-LIB-01, T-LIB-02 (wave 01) + T-MI-09 | Port DefaultCanonicalSerializer |

---

## Why this chunk

**Coherence**: This wave spans two logical layers (application + most of infrastructure), but the split is mandated by dependency ordering. T-MI-09 (ports) must precede all use cases; T-MI-15 + T-MI-16 must precede T-MI-17 (repositories) which is wave 03 because repositories require both models and a validated migration. T-MI-18, T-MI-19, T-MI-20, T-MI-21 are infrastructure adapters that do NOT depend on repositories — they only depend on wave-01 items, making them coherent with this wave.

**Dependency fit**: All 12 tasks have their prerequisites satisfied either in wave 01 or within this wave's group A. No task in this wave depends on wave 03 outputs.

**Size**: 12 tasks — within the [10, 20] bound.

**Why T-MI-17 is deferred**: Repositories + UoW depend on `alembic upgrade head` being validated (T-MI-16) and require integration tests against a live Postgres. Keeping repositories in wave 03 together with the wire-up tasks (T-MI-22, T-MI-23, T-MI-24) gives a coherent "integration and wiring" wave.

---

## Implementation instructions

### T-MI-09 — Application Port Interfaces

1. Read:
   - `platform_repo/apps/backend-market-ingestion/src/app/application/ports/adapters.py`
   - `platform_repo/apps/backend-market-ingestion/src/app/application/ports/repositories.py`
   - `platform_repo/apps/backend-market-ingestion/src/app/application/ports/unit_of_work.py`
   - `worldview/libs/storage/src/storage/object_storage.py` (ObjectStorage ABC — completed in wave 01)
   - `worldview/libs/messaging/src/messaging/` (AvroDictable interface — completed in wave 01)
2. Create package structure:
   - `worldview/services/market-ingestion/src/market_ingestion/application/__init__.py`
   - `worldview/services/market-ingestion/src/market_ingestion/application/ports/__init__.py`
3. Create `application/ports/adapters.py`:
   - `ProviderAdapter(ABC)`: `async fetch_quotes(...)`, `async fetch_ohlcv(...)`, `async fetch_fundamentals(...)`, `async health_check() -> bool`.
   - `ObjectStoreAdapter(ABC)`: `async put(bucket, key, data, content_type) -> ObjectRef`, `async get(bucket, key) -> bytes`, `async exists(bucket, key) -> bool`, `async ensure_bucket(bucket)`.
   - `CanonicalSerializer(ABC)`: `serialize_quotes(data) -> bytes`, `serialize_ohlcv(data) -> bytes`, `serialize_fundamentals(data) -> bytes`. Returns JSONL bytes, MIME = `application/x-ndjson`.
   - Adapter imports reference worldview domain types (`ObjectRef`, `CanonicalQuote`, etc.).
   - `ObjectStoreAdapter` interface aligns with `libs/storage.ObjectStorage` ABC signatures.
4. Create `application/ports/repositories.py`:
   - `TaskRepository(ABC)`: `get`, `add`, `add_many`, `save`, `claim_batch`, `has_active_task`, `list_by_status`, `count_by_status`.
   - `WatermarkRepository(ABC)`: `get`, `get_or_create`, `save`, `list_by_provider`.
   - `PollingPolicyRepository(ABC)`: `list_enabled`, `find_matching`, `add`, `save`.
   - `ProviderBudgetRepository(ABC)`: `get`, `get_or_create`, `save`, `list_all`.
   - `OutboxRepository(ABC)`: `add`, `claim_batch`, `mark_published`, `mark_failed`.
   - All methods are `async`.
5. Create `application/ports/unit_of_work.py`:
   - `UnitOfWork(ABC)`: `async __aenter__`, `async __aexit__`, `async commit()`, `async rollback()`, properties for each repository, `on_commit(callback)`.
6. No tests required for ABCs (tested through implementations). Run `mypy` against these files only.
7. Run: `cd services/market-ingestion && make lint`.

**DoD**: All 9 port interfaces defined as Python ABCs, imports reference worldview types, mypy clean.

---

### T-MI-15 — DB Models + Session Factory

1. Read all model files in `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/db/models/`.
2. Read `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/db/session.py`.
3. Read `worldview/services/market-ingestion/src/market_ingestion/config.py` (current skeleton Settings).
4. Create:
   - `infrastructure/__init__.py`
   - `infrastructure/db/__init__.py`
   - `infrastructure/db/models/__init__.py` — define `class Base(DeclarativeBase): pass`; import all model classes so `Base.metadata` aggregates all tables.
5. Create DB models (SQLAlchemy 2.0 `Mapped[]` column style, all TIMESTAMPTZ, UUID columns):
   - `infrastructure/db/models/ingestion_task.py`: `IngestionTaskModel` mapping to `ingestion_tasks`. Preserve all legacy columns and ALL indexes: `ix_ingestion_tasks_claimable` (partial on status/lease), `uq_ingestion_tasks_dedupe_key`, `ix_ingestion_tasks_active_check` (8-column).
   - `infrastructure/db/models/watermark.py`: `WatermarkModel` mapping to `ingestion_watermarks`. Preserve `uq_ingestion_watermarks_natural_key` (6-column).
   - `infrastructure/db/models/polling_policy.py`: `PollingPolicyModel` mapping to `polling_policies`. Preserve `ix_polling_policies_enabled` partial index and 6-column matching index.
   - `infrastructure/db/models/provider_budget.py`: `ProviderBudgetModel` mapping to `provider_budgets`. Unique on `provider`.
   - `infrastructure/db/models/outbox_event.py`: `OutboxEventModel` mapping to `outbox_events`. Preserve `ix_outbox_events_claimable` and `ix_outbox_events_retry` indexes.
6. Create `infrastructure/db/session.py`:
   - Async engine factory using `MARKET_INGESTION_DATABASE_URL` (asyncpg driver).
   - Optional read replica via `MARKET_INGESTION_DATABASE_URL_READ`.
   - `async_session_factory()` returns `async_sessionmaker`.
   - `get_write_session()` and `get_read_session()` async context managers.
7. Run: `cd services/market-ingestion && make lint`.

**DoD**: 5 SQLAlchemy 2.0 models, all indexes preserved, `Base.metadata` aggregates all tables, dual session factory, lint clean.

---

### T-MI-16 — Generate Alembic Migration (after T-MI-15)

1. Read `worldview/services/market-ingestion/alembic/env.py` (existing scaffold).
2. Read `worldview/services/market-ingestion/alembic.ini`.
3. Update `alembic/env.py`:
   - Import `Base` from `market_ingestion.infrastructure.db.models`.
   - Set `target_metadata = Base.metadata`.
   - Configure `MARKET_INGESTION_DATABASE_URL` loading for the migration context.
4. Run:
   ```bash
   cd services/market-ingestion
   alembic revision --autogenerate -m "initial_schema"
   ```
5. Review generated migration file:
   - Verify all 5 tables are created.
   - Verify all indexes match legacy (verify by name + column set).
   - Verify all unique constraints are present.
   - Manually fix any auto-generate inaccuracies (e.g., partial indexes, conditional expressions).
6. Test the migration against a clean database:
   ```bash
   alembic upgrade head
   alembic downgrade base
   alembic upgrade head   # verify idempotent
   ```

**DoD**: `env.py` wired to `Base.metadata`, migration file creates all 5 tables with correct indexes, upgrade + downgrade roundtrip succeeds.

---

### T-MI-18 — S3ObjectStoreAdapter (parallel with T-MI-09, T-MI-15, T-MI-21)

1. Read `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/adapters/object_store.py`.
2. Read `worldview/libs/storage/src/storage/key_builder.py` and `object_storage.py` (wave-01 output).
3. Create `infrastructure/adapters/__init__.py`.
4. Create `infrastructure/adapters/object_store.py`:
   - `S3ObjectStoreAdapter(ObjectStoreAdapter)` wrapping `libs/storage.ObjectStorage`.
   - `put(bucket, key, data, content_type) -> ObjectRef`: calls `storage.put()`, computes SHA-256, constructs and returns `ObjectRef`.
   - `get()`, `exists()`, `ensure_bucket()`: delegate directly to `storage`.
   - Key convention: use `libs/storage.KeyBuilder` with pattern `market-ingestion/{domain}/{resource_id}/{artifact}/{version}.{ext}`.
   - Bronze path convention: `market-ingestion/raw/{provider}/{dataset_type}/{symbol}/{date}.{ext}`.
   - Canonical path convention: `market-ingestion/canonical/{provider}/{dataset_type}/{symbol}/{date}.jsonl`.
5. Create `tests/infrastructure/__init__.py`.
6. Create `tests/infrastructure/test_object_store.py`:
   - Unit (mocked `ObjectStorage`): `put()` computes and returns correct SHA-256, `ObjectRef` fields populated, key built via `KeyBuilder`, `get()` returns bytes, `exists()` delegates.
   - Integration tests marked `@pytest.mark.integration`: real put/get/exists roundtrip against MinIO.
7. Run: `cd services/market-ingestion && make test -- tests/infrastructure/test_object_store.py && make lint`.

**DoD**: `S3ObjectStoreAdapter` wrapping `libs/storage`, SHA-256 in `ObjectRef`, key format correct, unit tests pass.

---

### T-MI-21 — Kafka Serialization + Avro Schema (parallel with T-MI-09, T-MI-15, T-MI-18)

1. Read entire `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/messaging/kafka/` directory.
2. Read `worldview/libs/messaging/src/messaging/topics.py` (verify `MARKET_DATASET_FETCHED` topic constant exists; add it if missing).
3. Read `worldview/AGENTS.md` — Avro schema location convention (`infra/kafka/schemas/`).
4. Relocate Avro schema:
   - Create `worldview/infra/kafka/schemas/market.dataset.fetched.avsc`.
   - Copy the `.avsc` content from legacy, preserving all 27 fields exactly.
   - Verify the schema includes envelope fields: `event_id`, `event_type`, `schema_version`, `occurred_at`, `correlation_id`, `causation_id`, plus all data fields + `bronze_ref_*` and `canonical_ref_*` claim-check fields.
5. Create `infrastructure/messaging/__init__.py` and `infrastructure/messaging/kafka/__init__.py`.
6. Create `infrastructure/messaging/kafka/mapper.py`:
   - `MarketDatasetFetchedMapper` with `to_avro_dict(event: MarketDatasetFetched) -> dict`:
     - Maps all event fields to Avro dict.
     - Flattens `bronze_ref: ObjectRef` → `bronze_ref_bucket`, `bronze_ref_key`, `bronze_ref_sha256`, `bronze_ref_byte_length`, `bronze_ref_mime_type`.
     - Same flattening for `canonical_ref`.
     - All 27 fields present.
   - `to_kafka_key(event: MarketDatasetFetched) -> str`: returns `f"{event.provider}:{event.symbol}"`.
7. Create `infrastructure/messaging/kafka/serialization.py`:
   - Factory that builds `AvroSerializer` for `MarketDatasetFetched` using `libs/messaging.build_avro_serializer()`.
   - Loads schema from `infra/kafka/schemas/market.dataset.fetched.avsc` (relative path from service root or embedded string).
   - References `messaging.topics.MARKET_DATASET_FETCHED` for topic name (no hardcoded strings).
8. Create `tests/infrastructure/test_kafka_serialization.py`:
   - Unit: mapper produces correct dict structure, ObjectRef flattened correctly, all 27 fields present, kafka key format.
   - Contract: Avro serialize → deserialize roundtrip using the `.avsc` schema; schema forward-compatibility test (add an optional field, re-parse old message).
9. Run: `cd services/market-ingestion && make test -- tests/infrastructure/test_kafka_serialization.py && make lint`.

**DoD**: `market.dataset.fetched.avsc` in `infra/kafka/schemas/`, mapper + serializer factory, roundtrip test passes, forward-compatibility test passes.

---

### T-MI-10 — ScheduleDueTasksUseCase (after T-MI-09)

1. Read `platform_repo/apps/backend-market-ingestion/src/app/application/use_cases/schedule_tasks.py`.
2. Create `application/use_cases/__init__.py`.
3. Create `application/use_cases/schedule_tasks.py`:
   - `ScheduleDueTasksUseCase(uow: UnitOfWork, max_tasks_per_tick: int = 1000)`.
   - Three-phase tick:
     1. Load enabled policies via `PollingPolicyRepository.list_enabled()`.
     2. For each policy: if backfill, generate chunked `IngestionTask` objects; if incremental, determine if due via `is_due(watermark.last_bar_ts)`.
     3. Apply budgets: filter tasks against `ProviderBudgetRepository`, consume budget tokens.
     4. Idempotent enqueue: `TaskRepository.add_many()` with `ON CONFLICT DO NOTHING`.
   - Use `get_logger(__name__)` from `observability`.
4. Create `tests/application/__init__.py`.
5. Create `tests/application/test_schedule_tasks.py`:
   - Policy evaluation filters disabled policies.
   - Backfill task creation (chunked).
   - Incremental task creation.
   - Wildcard symbol matching (`symbol=None` → matches all).
   - Budget application (tasks trimmed when budget exhausted to 0).
   - Idempotent enqueue (no error on duplicate `dedupe_key`).
   - `max_tasks_per_tick` cap respected.
   - Empty policies edge case (no tasks created).
   - All-budgets-exhausted edge case (no tasks created despite valid policies).
   - At least 10 test functions, all using mocked `UnitOfWork` and repos.
6. Run: `cd services/market-ingestion && make test -- tests/application/test_schedule_tasks.py && make lint`.

**DoD**: Three-phase tick implemented, ≥10 unit tests with all specified edge cases, lint + mypy clean.

---

### T-MI-11 — ClaimTasksUseCase (after T-MI-09)

1. Read `platform_repo/apps/backend-market-ingestion/src/app/application/use_cases/claim_tasks.py`.
2. Create `application/use_cases/claim_tasks.py`:
   - `ClaimTasksUseCase(uow: UnitOfWork)`.
   - `execute(worker_id: str, batch_size: int, lease_seconds: int) -> list[IngestionTask]`.
   - Delegates to `TaskRepository.claim_batch(worker_id, batch_size, lease_seconds)` inside UoW.
3. Create `tests/application/test_claim_tasks.py`:
   - Returns tasks when available.
   - Returns empty list when none available.
   - `worker_id` propagated to repo call.
   - `batch_size` respected.
4. Run: `cd services/market-ingestion && make test -- tests/application/test_claim_tasks.py && make lint`.

**DoD**: Single-delegation use case, mocked repo tests pass, lint clean.

---

### T-MI-12 — ExecuteTaskUseCase (after T-MI-09 + T-MI-08 done in wave 01)

1. Read `platform_repo/apps/backend-market-ingestion/src/app/application/use_cases/execute_task.py` carefully — this is the critical pipeline.
2. Create `application/use_cases/execute_task.py`:
   - `ExecuteTaskUseCase(uow, provider_registry, object_store, serializer)`.
   - `execute(task: IngestionTask) -> None` implements the **exact** 5-step pipeline order:
     1. Fetch from provider (outside any transaction).
     2. Store bronze object in MinIO (outside any transaction).
     3. Canonicalize (outside any transaction).
     4. Store canonical object in MinIO (outside any transaction).
     5. **Short transaction**: `advance_watermark()` + `add_outbox_event()` + `task.succeed()` + commit.
   - Error handling:
     - `ProviderRateLimited`, `ProviderUnavailable`, `StorageUnavailable`, `TaskLeaseLost` → call `task.retry(error)`, persist, re-raise as retryable.
     - `ProviderAuthError`, `ProviderDataError`, `InvalidStateTransition` → call `task.fail(error)`, persist, re-raise as fatal.
   - SHA-256 dedup: if `watermark.has_changed(new_sha256) == False` → skip outbox event (data unchanged).
   - Watermark advancement: `watermark.advance_bar_ts(new_ts)` inside the final transaction.
   - Use `get_logger(__name__)` with contextual fields: `task_id`, `provider`, `symbol`.
3. Create `tests/application/test_execute_task.py`:
   - Happy path end-to-end (all mocked): fetch → bronze → canonical → watermark → outbox → succeed.
   - `ProviderRateLimited` → task retried.
   - `ProviderUnavailable` → task retried.
   - `ProviderAuthError` → task failed.
   - `ProviderDataError` → task failed.
   - `StorageUnavailable` → task retried.
   - Unchanged SHA-256 → outbox NOT added.
   - Changed SHA-256 → outbox added.
   - Watermark monotonically advanced (only forward).
   - `WatermarkViolation` from non-monotonic advance → fatal error.
   - Dataset types: QUOTES, OHLCV, FUNDAMENTALS each use correct serializer method.
   - At least 12 test functions.
4. Run: `cd services/market-ingestion && make test -- tests/application/test_execute_task.py && make lint`.

**DoD**: 5-step pipeline in exact order, correct error → retry/fail mapping, SHA dedup gates outbox, ≥12 unit tests, lint + mypy clean.

---

### T-MI-13 — TriggerIngestionUseCase (after T-MI-09)

1. Read `platform_repo/apps/backend-market-ingestion/src/app/application/use_cases/trigger_ingestion.py`.
2. Create `application/use_cases/trigger_ingestion.py`:
   - `TriggerIngestionUseCase(uow: UnitOfWork)`.
   - `execute(provider, dataset_type, symbols: list[str], timeframe, exchange=None) -> list[IngestionTask]`.
   - Creates an `IngestionTask` per symbol, idempotent via `dedupe_key`, uses `TaskRepository.add_many()` with `ON CONFLICT DO NOTHING`.
3. Create `tests/application/test_trigger_ingestion.py`:
   - Single symbol trigger creates one task.
   - Multi-symbol trigger creates N tasks.
   - Duplicate `dedupe_key` → no error (idempotent).
   - Task fields match inputs.
4. Run: `cd services/market-ingestion && make test -- tests/application/test_trigger_ingestion.py && make lint`.

**DoD**: Idempotent task creation, tests pass.

---

### T-MI-14 — BackfillUseCase (after T-MI-09)

1. Read `platform_repo/apps/backend-market-ingestion/src/app/application/use_cases/backfill.py`.
2. Create `application/use_cases/backfill.py`:
   - `BackfillUseCase(uow: UnitOfWork)`.
   - `execute(provider, symbol, start_date, end_date, timeframe, chunk_days=30) -> list[IngestionTask]`.
   - Splits `DateRange(start_date, end_date)` into chunks of `chunk_days` days.
   - Enforces max 100 chunks; raises `ValueError` if exceeded.
   - Each chunk → one `IngestionTask.create_ohlcv_task()` with the chunk's `DateRange`.
   - Idempotent via dedupe key.
3. Create `tests/application/test_backfill.py`:
   - 90-day range → 3 chunks of 30 days.
   - Single-day range → 1 chunk.
   - Range spanning year boundary → correct chunk boundaries.
   - Max 100 chunks enforced (101st raises `ValueError`).
   - Idempotent: same date range → same dedupe keys.
4. Run: `cd services/market-ingestion && make test -- tests/application/test_backfill.py && make lint`.

**DoD**: Date-range chunking, max-100 enforcement, idempotent, tests pass.

---

### T-MI-19 — EODHD Provider Adapter + Stubs (after T-MI-09 + T-MI-03 done in wave 01)

1. Read `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/adapters/providers/eodhd.py` (626 lines).
2. Read `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/adapters/providers/__init__.py` (registry pattern).
3. Create `infrastructure/adapters/providers/__init__.py`:
   - `ProviderRegistry`: `register(provider: Provider, adapter: ProviderAdapter)`, `get(provider: Provider) -> ProviderAdapter`, `get_all() -> dict`.
   - `build_provider_registry(settings: Settings) -> ProviderRegistry` factory.
4. Create `infrastructure/adapters/providers/eodhd.py`:
   - Copy full `EODHDProviderAdapter` (626 lines).
   - Adapt imports: use `get_logger(__name__)` from `observability`; domain errors from `market_ingestion.domain.errors`.
   - Preserve: `httpx.AsyncClient`, symbol format `{SYMBOL}.{EXCHANGE}`, error mapping:
     - HTTP 429 → `ProviderRateLimited`
     - HTTP 401/403 → `ProviderAuthError`
     - HTTP 5xx → `ProviderUnavailable`
     - JSON decode failure → `ProviderDataError`
   - Preserve demo-key detection, all 3 fetch methods, response normalization.
5. Create stub adapters (`infrastructure/adapters/providers/polygon.py`, `yahoo.py`, `alpha_vantage.py`): implement `ProviderAdapter` ABC, all methods return empty data with `get_logger()` warning log.
6. Create `tests/infrastructure/test_eodhd.py` using `httpx.MockTransport` or `respx`:
   - Successful quotes fetch → returns normalized data.
   - Successful OHLCV fetch → returns bars list.
   - Successful fundamentals fetch → returns dict payload.
   - HTTP 429 → raises `ProviderRateLimited`.
   - HTTP 401 → raises `ProviderAuthError`.
   - HTTP 500 → raises `ProviderUnavailable`.
   - Malformed JSON → raises `ProviderDataError`.
   - Symbol format construction: `AAPL.US` format.
   - Response normalization: verify key field mappings.
   - At least 10 test functions.
7. Run: `cd services/market-ingestion && make test -- tests/infrastructure/test_eodhd.py && make lint`.

**DoD**: Full EODHD adapter ported, 3 stubs, provider registry, ≥10 unit tests with mocked HTTP, lint + mypy clean.

---

### T-MI-20 — DefaultCanonicalSerializer (after T-LIB-01, T-LIB-02 wave 01 + T-MI-09)

1. Read `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/adapters/canonical.py`.
2. Read `worldview/libs/contracts/src/contracts/canonical/` (all models — from wave 01).
3. Create `infrastructure/adapters/canonical.py`:
   - `DefaultCanonicalSerializer(CanonicalSerializer)`.
   - `serialize_quotes(data: list[dict]) -> bytes`:
     - Map each dict to `CanonicalQuote.from_dict(d)`.
     - JSONL output: one JSON line per quote, `to_dict()` serialization.
     - Returns UTF-8 bytes, MIME = `application/x-ndjson`.
   - `serialize_ohlcv(data: list[dict]) -> bytes`:
     - Map each dict to `CanonicalOHLCVBar.from_dict(d)`.
     - JSONL output.
   - `serialize_fundamentals(data: dict, variant: FundamentalsVariant) -> bytes`:
     - Map to `CanonicalFundamentals.from_dict({"variant": str(variant), "payload": data})`.
     - Single-line JSONL.
   - Each line must include `schema_version` from the canonical model.
4. Create `tests/infrastructure/test_canonical.py`:
   - OHLCV serialization: 3 bars → 3 JSONL lines, each with `schema_version`.
   - Quote serialization: single record → 1 JSONL line.
   - Fundamentals serialization: dict passthrough → 1 JSONL line.
   - Empty data → empty bytes.
   - Malformed dict (missing required field) raises expected error.
   - MIME type is `application/x-ndjson`.
5. Run: `cd services/market-ingestion && make test -- tests/infrastructure/test_canonical.py && make lint`.

**DoD**: JSONL output for quotes/OHLCV/fundamentals using `libs/contracts` models, `schema_version` embedded, tests pass.

---

## Constraints

- **Do not implement any code outside the task IDs listed in this wave** (T-MI-09 through T-MI-21, excluding T-MI-17 which is wave 03).
- Do not implement T-MI-17 (repositories/UoW) in this wave — repositories require T-MI-16 (Alembic migration) to be validated first, and are planned together with service wiring in wave 03.
- Do not implement T-MI-22 (outbox dispatcher wiring) — depends on T-MI-17 (wave 03).
- Do not implement API routes (T-MI-23), scheduler/worker (T-MI-24), or settings (T-MI-25) — those are wave 03.
- Do not copy legacy Alembic migration version files — run `alembic revision --autogenerate` fresh.
- Use `get_logger(__name__)` from `libs/observability` in all infrastructure modules.

---

## Required tests

### Per-task test runs

```bash
# After all group A tasks:
cd services/market-ingestion && make lint
cd services/market-ingestion && mypy src/

# Application layer (after T-MI-09 and group B)
cd services/market-ingestion && pytest tests/application/ -v
# Expected: ≥30 tests (ScheduleDueTasks ≥10, ExecuteTask ≥12, ClaimTasks/Trigger/Backfill ≤10 each)

# Infrastructure adapters
cd services/market-ingestion && pytest tests/infrastructure/ -v -m "not integration"

# Alembic migration
alembic upgrade head && alembic downgrade base && alembic upgrade head
```

### Full suite (validate no regressions)

```bash
cd services/market-ingestion && make test
./scripts/lint.sh
```

**Pass criteria:**
- All unit tests pass (`pytest` exit code 0).
- `ruff check` reports zero errors across all changed files.
- `mypy --strict` reports zero errors.
- Alembic upgrade + downgrade roundtrip succeeds on clean Postgres.
- No regressions in libs tests (all wave-01 tests still pass).

---

## Documentation requirements

For every task in this wave, update docs **in the same wave** if any of the following change:

| Change type | File to update |
|-------------|---------------|
| New API endpoint surface documented | `docs/services/market-ingestion.md` — update if any use case contract differs from spec |
| Avro schema relocated to `infra/kafka/schemas/` | Comment in `docs/services/market-ingestion.md` schema section and `docs/architecture/diagrams.md` if schema-registry flow is documented |
| New env var referenced in session.py | `services/market-ingestion/configs/dev.local.env.example`, `configs/prod.env.example` |
| Topic constant added to messaging lib | `docs/libs/messaging.md` — update topics table |
| Canonical serializer behavior documented | `docs/libs/contracts.md` — if serialization contract differs from spec |

**Mandatory instruction**: If any implementation changes a behavior, contract, config, schema surface, or test surface described in documentation, you MUST update that documentation in this same wave. List every doc file changed in the handoff evidence.

---

## Required handoff evidence

At wave completion, report all of the following:

### 1. Changed files (complete list)

List every file created or modified, with a one-line description.

### 2. Tests run and results

```
services/market-ingestion (application):
  tests/application/test_schedule_tasks.py:   X passed
  tests/application/test_claim_tasks.py:      X passed
  tests/application/test_execute_task.py:     X passed
  tests/application/test_trigger_ingestion.py: X passed
  tests/application/test_backfill.py:         X passed

services/market-ingestion (infrastructure):
  tests/infrastructure/test_object_store.py:  X passed (unit only)
  tests/infrastructure/test_eodhd.py:         X passed
  tests/infrastructure/test_canonical.py:     X passed
  tests/infrastructure/test_kafka_serialization.py: X passed

Alembic:
  alembic upgrade head:   success
  alembic downgrade base: success

Ruff:   0 errors
Mypy:   0 errors
```

### 3. Documentation changed (exact files + summary)

### 4. Unresolved blockers

### 5. Commit message proposal

```
feat(market-ingestion): application layer + infra adapters + DB schema (T-MI-09..21)

Port all 5 port interfaces, 5 use cases (schedule/claim/execute/trigger/backfill),
5 SQLAlchemy 2.0 models with full index set, initial Alembic migration, S3ObjectStoreAdapter,
EODHD provider adapter (626 LOC) with stub providers, canonical JSONL serializer, and
Kafka Avro mapper with schema relocated to infra/kafka/schemas/. 55+ unit tests;
alembic upgrade/downgrade roundtrip validated; ruff + mypy strict clean.
```

---

## Definition of done

- [ ] T-MI-09: All 9 port ABCs defined, imports reference worldview domain types, mypy clean.
- [ ] T-MI-10: `ScheduleDueTasksUseCase` three-phase tick, ≥10 unit tests, lint clean.
- [ ] T-MI-11: `ClaimTasksUseCase` delegating to repo, unit tests pass.
- [ ] T-MI-12: `ExecuteTaskUseCase` 5-step pipeline in exact order, SHA dedup, ≥12 unit tests, lint clean.
- [ ] T-MI-13: `TriggerIngestionUseCase` idempotent, unit tests pass.
- [ ] T-MI-14: `BackfillUseCase` date-range chunking with max-100 cap, unit tests pass.
- [ ] T-MI-15: 5 SQLAlchemy 2.0 models, all indexes preserved, dual session factory, lint clean.
- [ ] T-MI-16: Alembic `env.py` wired to `Base.metadata`, migration creates all 5 tables, upgrade + downgrade roundtrip validated.
- [ ] T-MI-18: `S3ObjectStoreAdapter` wrapping `libs/storage`, SHA-256 in `ObjectRef`, correct key format, unit tests pass.
- [ ] T-MI-19: Full EODHD adapter, 3 stub providers, provider registry, ≥10 unit tests with mocked HTTP, lint clean.
- [ ] T-MI-20: `DefaultCanonicalSerializer` for quotes/OHLCV/fundamentals, JSONL output, `schema_version` embedded, tests pass.
- [ ] T-MI-21: `market.dataset.fetched.avsc` in `infra/kafka/schemas/`, Avro mapper with flattened `ObjectRef`, serializer factory, roundtrip + forward-compat tests pass.
- [ ] Documentation updated for API, schema, env, and topic changes (exact files listed).
- [ ] `./scripts/lint.sh` passes with zero errors.
- [ ] Commit message proposal included.
