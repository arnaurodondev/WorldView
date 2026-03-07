# 0003 — Market Ingestion Migration: Detailed Plan & Atomic Task Backlog

## Metadata

- **Prompt ID**: 0003
- **Prompt file**: `agent-planning/0003-market-ingestion-migration-detailed-plan-and-atomic-tasks.md`
- **Execution date**: 2026-03-06
- **Agent role(s)**: Data Platform Engineer + Architecture Decision Lead
- **Scope**: Full migration plan for Market Ingestion service from `platform_repo` to `worldview`, decomposed into independent atomic tasks

## Summary

- **Requested**: Detailed migration and completion plan (no code) for Market Ingestion, decomposed into independent atomic tasks with full testing requirements.
- **Delivered**: Six-section plan: (1) current-state architecture map, (2) target-state requirements matrix, (3) delta analysis & risk table, (4) 25 atomic tickets, (5) sequenced roadmap by milestones, (6) operational go-live checklist.
- **Final status**: Plan complete. Ready for ticket-by-ticket implementation.

---

## Docs reviewed before planning

| Document | Path | Relevance |
|----------|------|-----------|
| Market Ingestion service spec | `docs/services/market-ingestion.md` | Target service definition |
| Migration reuse guide | `docs/migration/REUSE_FROM_ORIGINAL_THESIS.md` | Copy-adapt-delete strategy |
| Architecture ADR-0001 | `docs/architecture/decisions/0001-initial-architecture.md` | Monorepo + Clean Arch + Hatch |
| Architecture diagrams | `docs/architecture/diagrams.md` | Data flow, component diagram |
| Storage lib docs | `docs/libs/storage.md` | ObjectStorage interface |
| Messaging lib docs | `docs/libs/messaging.md` | Kafka producer, outbox, Avro |
| Contracts lib docs | `docs/libs/contracts.md` | Canonical models |
| Common lib docs | `docs/libs/common.md` | Time, IDs, types |
| Observability lib docs | `docs/libs/observability.md` | Logging, metrics, tracing |
| AGENTS.md | `AGENTS.md` | All coding/naming conventions |
| CLAUDE.md | `CLAUDE.md` | Workflow preferences |
| RULES.md | `RULES.md` | 18 mandatory rules |

---

# §1 — Current-State Architecture Map

## 1.1 Legacy Service Overview

**Location**: `platform_repo/apps/backend-market-ingestion/`

The legacy Market Ingestion service follows Clean / Hexagonal Architecture with four layers and three (optionally four) independent runtime processes.

### 1.1.1 Layer Structure

| Layer | Directory | Responsibility |
|-------|-----------|----------------|
| Domain | `src/app/domain/` | Entities, value objects, enums, events, errors — framework-free |
| Application | `src/app/application/` | Use cases, port interfaces (adapters, repositories, UoW) |
| Infrastructure | `src/app/infrastructure/` | SQLAlchemy repos, provider adapters, Kafka messaging, object storage, config |
| API / Entrypoints | `src/app/api/`, `src/app/scheduler/`, `src/app/worker/`, `src/app/messaging/` | FastAPI, scheduler loop, worker loop, standalone outbox dispatcher |

### 1.1.2 Runtime Processes

| Process | Entry | Scalability | Purpose |
|---------|-------|-------------|---------|
| API Server | `python -m app.api.main` | Horizontal (stateless) | Manual trigger & backfill endpoints, health probes |
| Scheduler | `python -m app.scheduler.main` | Single instance | Evaluates polling policies, enqueues tasks at tick intervals |
| Worker | `python -m app.worker.main` | Horizontal (`FOR UPDATE SKIP LOCKED`) | Claims & executes ingestion tasks |
| Outbox Dispatcher | `python -m app.messaging.dispatcher_main` | Single instance (or embedded) | Publishes outbox events to Kafka with delivery acks |

### 1.1.3 Domain Entities

| Entity | Key Behaviors |
|--------|---------------|
| `IngestionTask` | State machine (PENDING→RUNNING→SUCCEEDED/RETRY/FAILED). Lease-based locking. Exponential backoff with jitter (base=30s, max=1h, ±20%). Max 5 attempts. Dedupe key for idempotent enqueue. |
| `PollingPolicy` | Per-stream scheduling rules. Adaptive interval formula: `base / (1 + k × hotness)`. Priority ordering. Backfill support (chunk-based). Wildcard symbol matching. |
| `ProviderBudget` | Token-bucket rate limiter per provider. Provider-specific defaults (e.g. EODHD: 1000 burst / 10/s). |
| `Watermark` | Progress tracker. Natural key: `(provider, dataset_type, variant, symbol, exchange, timeframe)`. SHA-256 dedup. Monotonic bar-timestamp advancement. Backfill phase tracking (PENDING→IN_PROGRESS→COMPLETED). |

### 1.1.4 Value Objects & Enums

- **`ObjectRef`**: claim-check pointer (bucket, key, sha256, byte_length, mime_type)
- **`Timeframe`**: validated string (1m..1y)
- **`InstrumentKey`**: symbol + optional exchange
- **`DateRange`**: validated start/end datetimes
- **Enums**: `Provider` (eodhd, finnhub, openfigi, polygon, alpha_vantage, yahoo), `DatasetType` (instruments, quotes, ohlcv, corporate_actions, fundamentals), `FundamentalsVariant` (7 sub-types), `IngestionTaskStatus` (5 states), `OutboxStatus` (5 states)

### 1.1.5 Domain Events

| Event | Kafka Topic | Purpose |
|-------|-------------|---------|
| `MarketDatasetFetched` | `market.dataset.fetched` | **Pointer event** (claim-check). Carries `bronze_ref` + `canonical_ref` (ObjectRef). Avro-serialized, 27 fields. |
| `IngestionTaskCompleted` | — (internal only) | Metrics / observability |
| `IngestionTaskScheduled` | — (internal only) | Metrics / observability |

### 1.1.6 Application Ports

| Port | Key Methods |
|------|-------------|
| `ProviderAdapter` | `fetch_quotes()`, `fetch_ohlcv()`, `fetch_fundamentals()`, `health_check()` |
| `ObjectStoreAdapter` | `put()`, `get()`, `exists()`, `ensure_bucket()` |
| `CanonicalSerializer` | `serialize_quotes()`, `serialize_ohlcv()`, `serialize_fundamentals()` |
| `TaskRepository` | `get()`, `add()`, `add_many()`, `save()`, `claim_batch()`, `has_active_task()`, `list_by_status()`, `count_by_status()` |
| `WatermarkRepository` | `get()`, `get_or_create()`, `save()`, `list_by_provider()` |
| `PollingPolicyRepository` | `list_enabled()`, `find_matching()`, `add()`, `save()` |
| `ProviderBudgetRepository` | `get()`, `get_or_create()`, `save()`, `list_all()` |
| `OutboxRepository` | `add(events)`, `claim_batch()`, `mark_published()`, `mark_failed()` |
| `UnitOfWork` | `commit()`, `rollback()`, aggregated repos, `on_commit` callback |

### 1.1.7 Use Cases

| Use Case | Description |
|----------|-------------|
| `ScheduleDueTasksUseCase` | Three-phase tick: evaluate policies → resolve backfill/incremental → apply budgets & idempotent enqueue |
| `ClaimTasksUseCase` | `SELECT ... FOR UPDATE SKIP LOCKED` batch claim |
| `ExecuteTaskUseCase` | Fetch provider → store bronze → canonicalize → store canonical → short tx (watermark + outbox + succeed) |
| `TriggerIngestionUseCase` | Manual API trigger, idempotent via dedupe_key |
| `BackfillUseCase` | Date-range chunked OHLCV backfill (30-day slices, max 100 chunks) |

### 1.1.8 Infrastructure Adapters

| Component | Status | Details |
|-----------|--------|---------|
| EODHD provider | **Fully implemented** (626 LOC) | httpx.AsyncClient, symbol format `{SYMBOL}.{EXCHANGE}`, handles 429/401/5xx |
| Polygon provider | Stub | Returns empty data |
| Yahoo provider | Stub | Returns stub data |
| Alpha Vantage provider | Stub | Returns empty data |
| Canonical serializer | Implemented | Produces JSONL (application/x-ndjson) for all types |
| Object store adapter | Implemented | Wraps `libs/storage`, SHA-256 on put, canonical key builder |
| Outbox dispatcher | Implemented | Hybrid dispatch (immediate + poll), lease-based, 3-phase commit, dead-letter |

### 1.1.9 Database (5 tables, SQLAlchemy 2.0)

| Table | Key Design Features |
|-------|---------------------|
| `ingestion_tasks` | Composite indexes for claiming, unique constraint on `(provider, dedupe_key)`, 8-column active-check index |
| `ingestion_watermarks` | 6-column natural key unique constraint |
| `polling_policies` | Partial index on `enabled=true`, 6-column matching index |
| `provider_budgets` | Unique on `provider` |
| `outbox_events` | Indexes on `(status, locked_until)`, `(status, next_attempt_at)` |

**Alembic migrations**: 5 versioned migrations (initial → seed policies → composite index → backfill support → seed backfill demo).

### 1.1.10 Shared Library Usage

| Library | Usage in Market Ingestion |
|---------|---------------------------|
| `libs/storage` | `S3ObjectStorage`, `StorageSettings`, `KeyBuilder`, `build_object_storage()`, `check_storage_health()` |
| `libs/messaging` | `KafkaProducerConfig`, `build_serializing_producer()`, `OutboxKafkaValue`, `AvroSerializerConfig`, `build_avro_serializer()`, `SchemaRegistryConfig` |
| `libs/contracts` | `CanonicalOHLCVBar`, `CanonicalQuote`, `CanonicalFundamentals`, version constants, `parse_canonical_data()` |
| `libs/common` | `utc_now()`, `ensure_utc()`, `to_iso8601()`, `from_iso8601()`, `parse_bar_date()` |

### 1.1.11 Configuration (Pydantic Settings)

| Category | Key Variables |
|----------|---------------|
| Database | `DATABASE_URL` (asyncpg), `DATABASE_URL_READ` (optional replica) |
| Object Storage | `STORAGE_BUCKET`, `STORAGE_ENDPOINT`, `STORAGE_REGION`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY` |
| Kafka | `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_SCHEMA_REGISTRY_URL`, `KAFKA_AUTO_REGISTER_SCHEMAS` |
| Scheduler | `SCHEDULER_TICK_INTERVAL_SECONDS` (30), `SCHEDULER_MAX_TASKS_PER_TICK` (1000) |
| Worker | `WORKER_BATCH_SIZE` (10), `WORKER_LEASE_SECONDS` (300), `WORKER_POLL_INTERVAL_SECONDS` (5) |
| Dispatcher | `DISPATCHER_POLL_INTERVAL_SECONDS` (10), `DISPATCHER_LEASE_SECONDS` (60), `DISPATCHER_MAX_ATTEMPTS` (5) |
| Provider Keys | `EODHD_API_KEY`, `FINNHUB_API_KEY`, `POLYGON_API_KEY`, `ALPHA_VANTAGE_API_KEY` |

---

# §2 — Target-State Requirements Matrix

Source: `docs/services/market-ingestion.md`, `AGENTS.md`, `RULES.md`, `CLAUDE.md`, architecture docs, lib docs.

## 2.1 Structural Requirements

| Req ID | Requirement | Source Rule | Notes |
|--------|-------------|-------------|-------|
| T-ARCH-01 | Clean/Hexagonal Architecture: `domain/` → `application/` → `infrastructure/` → `api/` | AGENTS.md, ADR-0001 | Same pattern as legacy — preserve layer boundaries |
| T-ARCH-02 | 4 runtime processes: API, Scheduler, Worker, Outbox Dispatcher | `docs/services/market-ingestion.md` | Identical to legacy |
| T-ARCH-03 | Hatch packaging with `pyproject.toml` (PEP 621) | ADR-0001 | Replace Poetry/setuptools |
| T-ARCH-04 | Relative path dependencies to `libs/` | ADR-0001 | e.g. `common = {path = "../../libs/common"}` |
| T-ARCH-05 | Module name `market_ingestion` (underscore) | Target skeleton | Package under `src/market_ingestion/` |
| T-ARCH-06 | Port 8001 (production), 8002 (dev local) |  `docs/services/market-ingestion.md`, skeleton config | Reconcile: spec says 8001, skeleton defaults to 8002 |

## 2.2 Domain Requirements

| Req ID | Requirement | Source Rule | Notes |
|--------|-------------|-------------|-------|
| T-DOM-01 | All entity IDs use UUIDv7 | R10 | Legacy uses UUID v4 — must migrate ID generation to UUIDv7 |
| T-DOM-02 | All timestamps UTC-only with `TIMESTAMPTZ` | R11 | Already enforced in legacy domain |
| T-DOM-03 | Domain entities framework-free (no SQLAlchemy, no Pydantic) | AGENTS.md | Already enforced in legacy |
| T-DOM-04 | `IngestionTask`, `PollingPolicy`, `ProviderBudget`, `Watermark` entities | Legacy domain | Copy as-is per migration guide, adapt ID generation |
| T-DOM-05 | `MarketDatasetFetched` event with envelope standard | AGENTS.md event envelope | Must include `event_id` (UUIDv7), `event_type`, `schema_version`, `occurred_at`, `correlation_id`, `causation_id` |
| T-DOM-06 | Error taxonomy: `RetryableError` vs `FatalError` | CLAUDE.md | Map legacy domain errors to this classification |

## 2.3 Application Requirements

| Req ID | Requirement | Source Rule | Notes |
|--------|-------------|-------------|-------|
| T-APP-01 | Port interfaces for all adapters and repositories | Clean Arch | Same as legacy ports |
| T-APP-02 | 5 use cases: Schedule, Claim, Execute, Trigger, Backfill | Service spec | Same as legacy |
| T-APP-03 | Transactional outbox pattern (no dual writes) | R8 | Same as legacy |
| T-APP-04 | Idempotent task enqueue via `ON CONFLICT DO NOTHING` | Service spec | Same as legacy |
| T-APP-05 | Claim-check pattern for large payloads | R12 | Same as legacy |

## 2.4 Infrastructure Requirements

| Req ID | Requirement | Source Rule | Notes |
|--------|-------------|-------------|-------|
| T-INF-01 | Use `libs/storage` `ObjectStorage` interface (never direct boto3) | Storage lib docs | Legacy wraps storage lib — keep pattern |
| T-INF-02 | Use `libs/messaging` producer & outbox interfaces | Messaging lib docs | Depends on messaging lib completion |
| T-INF-03 | Use `libs/contracts` canonical models | Contracts lib docs | Depends on contracts lib completion |
| T-INF-04 | Use `libs/common` for time, IDs, types | Common lib docs | Already available |
| T-INF-05 | Use `libs/observability` for logging, metrics, tracing | Observability lib docs | Depends on observability lib completion |
| T-INF-06 | Kafka topic: `market.dataset.fetched` from `messaging.topics` | Messaging lib | Centralized, not hardcoded |
| T-INF-07 | MinIO key format via `storage.KeyBuilder` | Storage lib | `{service}/{domain}/{resource_id}/{artifact}/{version}.{ext}` |
| T-INF-08 | Avro schema in `infra/kafka/schemas/` (not in service) | AGENTS.md | Move Avro schema to central location |
| T-INF-09 | SQLAlchemy 2.0 + asyncpg, dual session routing | Legacy pattern | Preserve read/write replica support |
| T-INF-10 | Alembic migrations regenerated fresh | Migration guide | Do NOT copy legacy migration files |
| T-INF-11 | `pydantic-settings` with `MARKET_INGESTION_` env prefix | Target skeleton | Change from legacy flat env vars |

## 2.5 Observability Requirements

| Req ID | Requirement | Source Rule | Notes |
|--------|-------------|-------------|-------|
| T-OBS-01 | `structlog` exclusively via `get_logger(__name__)` | CLAUDE.md | Never `print()` or stdlib `logging` |
| T-OBS-02 | `/metrics` endpoint (Prometheus) | Service spec | NEW — legacy did not expose this |
| T-OBS-03 | SLIs: task_execution_duration, task_success_rate, outbox_dispatch_latency, provider_error_rate | Service spec | NEW metrics to define |
| T-OBS-04 | SLOs: p99 execution < 30s, success_rate > 99.5%, outbox_latency p99 < 5s | Service spec | NEW — must instrument |
| T-OBS-05 | OpenTelemetry tracing integration | AGENTS.md, Observability lib | NEW — legacy had basic OTel |
| T-OBS-06 | Contextual log fields: `service`, `correlation_id`, `task_id`, `provider`, `symbol` | CLAUDE.md | Enrich logs beyond legacy |

## 2.6 Testing Requirements

| Req ID | Requirement | Source Rule | Notes |
|--------|-------------|-------------|-------|
| T-TEST-01 | Unit tests for all domain entities | R1 | Domain logic, state machines, validation |
| T-TEST-02 | Unit tests for all use cases (with mocked ports) | R1 | Schedule, Claim, Execute, Trigger, Backfill |
| T-TEST-03 | Unit tests for canonical transformers | R1 | JSONL output correctness |
| T-TEST-04 | Service container tests (Worker + DB + MinIO + Kafka) | R1 | Integration with testcontainers or compose |
| T-TEST-05 | Contract tests for Avro schema compatibility | R5 | Forward compatibility validation |
| T-TEST-06 | Platform QA: ingestion → materialization path | Prompt spec | End-to-end pipeline verification |
| T-TEST-07 | Coverage ≥ 60% with branch coverage | pyproject.toml | Configured in root |

## 2.7 Documentation Requirements

| Req ID | Requirement | Source Rule | Notes |
|--------|-------------|-------------|-------|
| T-DOC-01 | Update `docs/services/market-ingestion.md` on any API/event/config change | R3 | Must stay current |
| T-DOC-02 | ADR required for any major architectural deviation | R4, R16 | If deviating from plan |
| T-DOC-03 | Update env example files on config changes | CLAUDE.md | `configs/dev.local.env.example`, `configs/prod.env.example` |
| T-DOC-04 | Library IMPLEMENTATION.md checklists updated as prereqs complete | Convention | Track lib readiness |

---

# §3 — Delta Analysis & Risk Table

## 3.1 Component-Level Delta

| Component | Legacy Status | Target Status | Gap | Migration Action |
|-----------|---------------|---------------|-----|------------------|
| **Domain entities** | ✅ Complete (4 entities) | ❌ Missing | Full gap | Copy → adapt IDs to UUIDv7 |
| **Domain enums** | ✅ Complete | ❌ Missing | Full gap | Copy as-is |
| **Domain events** | ✅ Complete (3 events) | ❌ Missing | Full gap | Copy → adapt envelope to new standard |
| **Domain errors** | ✅ Complete (hierarchy) | ❌ Missing | Full gap | Copy → map to RetryableError/FatalError |
| **Domain value objects** | ✅ Complete (4 VOs) | ❌ Missing | Full gap | Copy as-is |
| **Application ports** | ✅ Complete (9 interfaces) | ❌ Missing | Full gap | Copy → adapt imports to worldview libs |
| **Application use cases** | ✅ Complete (5 UCs) | ❌ Missing | Full gap | Copy → adapt to new lib interfaces |
| **Provider: EODHD** | ✅ Fully implemented | ❌ Missing | Full gap | Copy → adapt to new port interface |
| **Provider: Polygon** | 🔲 Stub | ❌ Missing | Stub gap | Copy stub → plan for later |
| **Provider: Yahoo** | 🔲 Stub | ❌ Missing | Stub gap | Copy stub → plan for later |
| **Provider: Alpha Vantage** | 🔲 Stub | ❌ Missing | Stub gap | Copy stub → plan for later |
| **Canonical serializer** | ✅ Implemented | ❌ Missing | Full gap | Copy → adapt to contracts lib models |
| **Object store adapter** | ✅ Implemented | ❌ Missing | Full gap | Depends on `libs/storage` completion |
| **DB models** | ✅ 5 tables | ❌ Missing | Full gap | Copy → adapt to SA 2.0 conventions |
| **DB repositories** | ✅ 5 repos | ❌ Missing | Full gap | Copy → adapt imports |
| **Unit of Work** | ✅ Implemented | ❌ Missing | Full gap | Copy → adapt |
| **DB session factory** | ✅ Implemented | ❌ Missing | Full gap | Copy → adapt env prefix |
| **Alembic migrations** | ✅ 5 migrations | ❌ Empty dir | Full gap | Regenerate fresh (do NOT copy) |
| **Outbox dispatcher** | ✅ Implemented | ❌ Missing | Full gap | Depends on `libs/messaging` completion |
| **Kafka serialization** | ✅ Implemented | ❌ Missing | Full gap | Copy mapper → adapt to libs/messaging |
| **Avro schema** | ✅ In service | ❌ Missing | Full gap | Move to `infra/kafka/schemas/` |
| **API routes** | ✅ trigger + backfill | 🟡 Health only | Partial gap | Copy → adapt |
| **API dependencies/DI** | ✅ Implemented | ❌ Missing | Full gap | Copy → adapt |
| **Scheduler loop** | ✅ Implemented | ❌ Missing | Full gap | Copy → adapt |
| **Worker loop** | ✅ Implemented | ❌ Missing | Full gap | Copy → adapt |
| **Config (Settings)** | ✅ Flat env vars | 🟡 Skeleton (prefixed) | Env prefix change | Adapt all env var names |
| **Health probes** | ✅ 3 endpoints | 🟡 2 endpoints (stubs) | Probe gap | Enrich with real DB/Storage/Kafka checks |
| **Observability: logging** | ❌ Basic structlog | 🟡 `libs/observability` logging | Upgrade | Switch to `get_logger()` from observability lib |
| **Observability: metrics** | ❌ None | ❌ Lib not implemented | Double gap | Blocked on `libs/observability` metrics |
| **Observability: tracing** | ❌ Basic OTel | ❌ Lib not implemented | Double gap | Blocked on `libs/observability` tracing |
| **Tests** | ❓ Unknown coverage | 🟡 2 health tests | Major gap | Must write full unit + integration |

## 3.2 Library Dependency Readiness

| Library | Needed By Service | Current State | Blocking Tickets |
|---------|-------------------|---------------|------------------|
| `libs/common` | IDs, time, types | ✅ 95% complete | None — ready to use |
| `libs/contracts` | Canonical models | 🟡 30% — missing `CanonicalQuote`, `CanonicalFundamentals`, `parsing.py` | T-LIB-01, T-LIB-02 |
| `libs/messaging` | Kafka producer, outbox, Avro | 🟡 20% — missing producer, outbox, consumer | T-LIB-03, T-LIB-04, T-LIB-05 |
| `libs/storage` | S3 object storage client | 🟡 25% — missing `ObjectStorage` impl, health, exceptions | T-LIB-06, T-LIB-07 |
| `libs/observability` | Metrics, tracing | 🟡 30% — missing metrics, tracing | T-LIB-08, T-LIB-09 |

## 3.3 Risk Table

| Risk ID | Risk | Likelihood | Impact | Mitigation |
|---------|------|------------|--------|------------|
| R-01 | Library gaps block service migration (messaging, storage) | **High** | **Critical** | Complete lib tickets first. Service can stub libs temporarily for unit tests. |
| R-02 | UUIDv7 migration breaks legacy data interop | Medium | Medium | Use `uuid7` library. Legacy data won't be read by new service. Fresh DB. |
| R-03 | Env prefix change (`MARKET_INGESTION_` vs flat) may cause config drift | Medium | Low | Document all env changes. Update compose/k8s manifests. |
| R-04 | Avro schema relocation (service → `infra/`) breaks schema registry subjects | Medium | High | Keep same subject name strategy. Run schema compat check before deploy. |
| R-05 | Alembic regeneration may produce different index/constraint names | Low | Low | Review generated migration against legacy schema. Ensure functional equivalence. |
| R-06 | Observability lib incomplete — metrics/tracing may be deferred | High | Medium | Implement logging first. Add metrics/tracing stubs that can be wired later. |
| R-07 | Single scheduler instance becomes SPOF | Low | Medium | Document failover. Add health probe. Future: leader election via Valkey. |
| R-08 | Backfill chunk logic edge cases (DST, market holidays) | Medium | Medium | Port existing backfill tests. Add edge case tests for date boundaries. |
| R-09 | `FOR UPDATE SKIP LOCKED` behavior differences during claim under high concurrency | Low | Medium | Container test with multiple concurrent workers. |
| R-10 | Large Avro event (27 fields) may have serialization edge cases | Low | Medium | Contract test: serialize → deserialize roundtrip. Schema compat test. |

---

# §4 — Atomic Task Backlog

> Each task is designed to be independently implementable and testable. Dependencies are explicitly listed. All tasks assume the developer has read: `AGENTS.md`, `RULES.md`, `CLAUDE.md`, and `docs/services/market-ingestion.md`.

---

## Milestone 0 — Library Prerequisites

> These tasks complete shared library gaps that block Market Ingestion. They may already be tracked elsewhere (Prompt 0001); included here for dependency clarity.

---

### T-LIB-01: Implement `CanonicalQuote` in contracts lib

- **ID**: T-LIB-01
- **Title**: Add CanonicalQuote frozen dataclass to contracts lib
- **Objective**: Provide the `CanonicalQuote` canonical model needed by Market Ingestion's canonical serializer.

**Paths to read**:
- `platform_repo/libs/contracts/src/contracts/canonical/quotes.py` (legacy)
- `worldview/libs/contracts/src/contracts/canonical/ohlcv.py` (pattern reference)
- `worldview/libs/contracts/IMPLEMENTATION.md`
- `worldview/docs/libs/contracts.md`

**Paths to change**:
- `worldview/libs/contracts/src/contracts/canonical/quotes.py` (create)
- `worldview/libs/contracts/src/contracts/canonical/__init__.py` (re-export)
- `worldview/libs/contracts/tests/test_quotes.py` (create)
- `worldview/libs/contracts/IMPLEMENTATION.md` (check item)

**Dependencies**: None

**Step-by-step actions**:
1. Read legacy `CanonicalQuote` dataclass definition.
2. Create `quotes.py` following `ohlcv.py` pattern: frozen dataclass, `from_dict()`, `to_dict()`, `schema_version` as frozen non-init field.
3. Omit legacy `tenant_id` and `currency` fields (per worldview conventions).
4. Re-export from `canonical/__init__.py`.
5. Write tests: construction, `to_dict()` roundtrip, `from_dict()` with missing optional fields.
6. Run `cd libs/contracts && make test && make lint`.
7. Update IMPLEMENTATION.md checklist.

**Tests**:
- Unit: Construction, serialization roundtrip, schema_version frozen field, edge cases (None optional fields)
- Container: N/A
- Platform: N/A

**Documentation updates**: `libs/contracts/IMPLEMENTATION.md` checklist

**Acceptance criteria / DoD**:
- [ ] `CanonicalQuote` frozen dataclass with `from_dict()`/`to_dict()`
- [ ] `schema_version` matches `QUOTE_SCHEMA_VERSION` constant
- [ ] Tests pass, lint clean, mypy clean
- [ ] IMPLEMENTATION.md updated

**Effort**: XS (1–2 hours)
**Risk**: None

---

### T-LIB-02: Implement `CanonicalFundamentals` in contracts lib

- **ID**: T-LIB-02
- **Title**: Add CanonicalFundamentals frozen dataclass to contracts lib
- **Objective**: Provide the `CanonicalFundamentals` canonical model needed by Market Ingestion.

**Paths to read**:
- `platform_repo/libs/contracts/src/contracts/canonical/fundamentals.py` (legacy)
- `worldview/libs/contracts/src/contracts/canonical/ohlcv.py` (pattern)
- `worldview/docs/libs/contracts.md`

**Paths to change**:
- `worldview/libs/contracts/src/contracts/canonical/fundamentals.py` (create)
- `worldview/libs/contracts/src/contracts/canonical/__init__.py` (re-export)
- `worldview/libs/contracts/tests/test_fundamentals.py` (create)
- `worldview/libs/contracts/IMPLEMENTATION.md` (check item)

**Dependencies**: None

**Step-by-step actions**:
1. Read legacy `CanonicalFundamentals` dataclass.
2. Create `fundamentals.py` following `ohlcv.py` pattern. Keep flexible `dict` payload (legacy pattern: thin passthrough).
3. Write tests.
4. Re-export, lint, type-check.

**Tests**:
- Unit: Construction, serialization, variant handling (profile, income_statement, etc.)
- Container: N/A
- Platform: N/A

**Documentation updates**: `libs/contracts/IMPLEMENTATION.md`

**Acceptance criteria / DoD**:
- [ ] `CanonicalFundamentals` frozen dataclass with `from_dict()`/`to_dict()`
- [ ] `schema_version` matches `FUNDAMENTAL_SCHEMA_VERSION`
- [ ] Tests pass, lint clean
- [ ] IMPLEMENTATION.md updated

**Effort**: XS (1–2 hours)
**Risk**: None

---

### T-LIB-03: Implement `ObjectStorage` ABC + `S3ObjectStorage` in storage lib

- **ID**: T-LIB-03
- **Title**: Implement S3ObjectStorage client in storage lib
- **Objective**: Provide the MinIO/S3 client that Market Ingestion uses for bronze/canonical object storage.

**Paths to read**:
- `platform_repo/libs/storage/src/storage/object_storage.py` (legacy)
- `worldview/libs/storage/src/storage/key_builder.py` (existing)
- `worldview/libs/storage/src/storage/settings.py` (existing)
- `worldview/libs/storage/IMPLEMENTATION.md`
- `worldview/docs/libs/storage.md`

**Paths to change**:
- `worldview/libs/storage/src/storage/object_storage.py` (create)
- `worldview/libs/storage/src/storage/exceptions.py` (create)
- `worldview/libs/storage/src/storage/health.py` (create)
- `worldview/libs/storage/src/storage/__init__.py` (re-export)
- `worldview/libs/storage/tests/test_object_storage.py` (create)
- `worldview/libs/storage/IMPLEMENTATION.md` (check items)

**Dependencies**: None

**Step-by-step actions**:
1. Copy legacy `ObjectStorage` ABC and `S3ObjectStorage`.
2. Adapt: add `put_json()`/`get_json()` methods per spec.
3. Create exception hierarchy: `ObjectNotFoundError`, `BucketNotFoundError`, `StoragePermissionError`, `StorageUnavailableError`.
4. Create `health.py` with `check_storage_health()`.
5. Create `build_object_storage()` factory.
6. Write unit tests (mock boto3), integration test marker for real MinIO.
7. Re-export from `__init__.py`.

**Tests**:
- Unit: Mock boto3 — put/get/delete/exists/list_keys/put_json/get_json
- Container: MinIO test (marker: `integration`) — real put/get roundtrip
- Platform: N/A

**Documentation updates**: `libs/storage/IMPLEMENTATION.md`

**Acceptance criteria / DoD**:
- [ ] `ObjectStorage` ABC with all methods from spec
- [ ] `S3ObjectStorage` with boto3 implementation + retries + SHA-256
- [ ] Exception hierarchy complete
- [ ] `check_storage_health()` implemented
- [ ] `build_object_storage()` factory from settings
- [ ] Unit tests pass, lint clean

**Effort**: M (4–6 hours)
**Risk**: Low — straightforward port

---

### T-LIB-04: Implement Kafka producer in messaging lib

- **ID**: T-LIB-04
- **Title**: Implement KafkaProducerConfig + build_serializing_producer in messaging lib
- **Objective**: Provide the Kafka producer infrastructure used by Market Ingestion's outbox dispatcher.

**Paths to read**:
- `platform_repo/libs/messaging/src/messaging/producer.py` (legacy)
- `platform_repo/libs/messaging/src/messaging/serialization.py` (legacy)
- `worldview/libs/messaging/src/messaging/schemas.py` (existing)
- `worldview/libs/messaging/src/messaging/topics.py` (existing)
- `worldview/docs/libs/messaging.md`

**Paths to change**:
- `worldview/libs/messaging/src/messaging/producer.py` (create)
- `worldview/libs/messaging/src/messaging/__init__.py` (re-export)
- `worldview/libs/messaging/tests/test_producer.py` (create)
- `worldview/libs/messaging/IMPLEMENTATION.md` (check items)

**Dependencies**: None

**Step-by-step actions**:
1. Copy legacy producer module.
2. Adapt: use `confluent-kafka` SerializingProducer, acks=all, idempotence=True, linger_ms=5.
3. Implement `build_serializing_producer()`, `build_avro_serializer()`.
4. Implement subject name strategy: `topic_event_type_subject_name_strategy()`.
5. Adapt `OutboxKafkaValue` and `OutboxEventValueSerializer` from legacy.
6. Write unit tests with mocked Kafka producer.

**Tests**:
- Unit: Config construction, serializer building, subject name strategy
- Container: Kafka test (marker: `integration`) — produce + consume roundtrip
- Platform: N/A

**Documentation updates**: `libs/messaging/IMPLEMENTATION.md`

**Acceptance criteria / DoD**:
- [ ] `KafkaProducerConfig` with sane production defaults
- [ ] `build_serializing_producer()` returns configured producer
- [ ] `build_avro_serializer()` with schema registry
- [ ] Subject naming: `{topic}-{event_type}`
- [ ] Tests pass, lint clean

**Effort**: M (4–6 hours)
**Risk**: Low

---

### T-LIB-05: Implement BaseOutboxDispatcher in messaging lib

- **ID**: T-LIB-05
- **Title**: Implement BaseOutboxDispatcher with lease-based dispatch in messaging lib
- **Objective**: Provide the reusable outbox dispatcher that Market Ingestion (and other services) embed.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/messaging/dispatcher.py` (legacy)
- `worldview/docs/libs/messaging.md` (spec)

**Paths to change**:
- `worldview/libs/messaging/src/messaging/outbox.py` (create)
- `worldview/libs/messaging/src/messaging/__init__.py` (re-export)
- `worldview/libs/messaging/tests/test_outbox.py` (create)
- `worldview/libs/messaging/IMPLEMENTATION.md` (check items)

**Dependencies**: T-LIB-04 (producer)

**Step-by-step actions**:
1. Extract reusable outbox dispatcher from legacy service implementation.
2. Make it generic (not Market Ingestion-specific): parameterize UoW creation, event serialization.
3. Implement: hybrid dispatch (immediate + poll), lease-based claiming, 3-phase commit, dead-letter, exponential backoff.
4. Use `get_logger()` from observability lib.
5. Write unit tests with mocked UoW and producer.

**Tests**:
- Unit: Claim → produce → finalize happy path; retry on produce failure; dead-letter after max attempts; backoff calculation
- Container: DB + Kafka integration test
- Platform: N/A

**Documentation updates**: `libs/messaging/IMPLEMENTATION.md`

**Acceptance criteria / DoD**:
- [ ] `BaseOutboxDispatcher` with hybrid dispatch mode
- [ ] Lease-based claiming with configurable lease duration
- [ ] Dead-letter handling after N attempts
- [ ] Exponential backoff with jitter
- [ ] Stable worker ID (`{hostname}-{pid}`)
- [ ] Tests pass, lint clean

**Effort**: L (6–10 hours)
**Risk**: Medium — complex concurrency logic; needs careful testing

---

### T-LIB-06: Implement Prometheus metrics in observability lib

- **ID**: T-LIB-06
- **Title**: Add create_metrics, ServiceMetrics, and Prometheus middleware to observability lib
- **Objective**: Enable `/metrics` endpoint for Market Ingestion.

**Paths to read**:
- `worldview/libs/observability/src/observability/logging.py` (existing)
- `worldview/docs/libs/observability.md` (spec)

**Paths to change**:
- `worldview/libs/observability/src/observability/metrics.py` (create)
- `worldview/libs/observability/src/observability/__init__.py` (re-export)
- `worldview/libs/observability/tests/test_metrics.py` (create)
- `worldview/libs/observability/IMPLEMENTATION.md` (check items)

**Dependencies**: None

**Step-by-step actions**:
1. Create `metrics.py` with `create_metrics(service_name)` → `ServiceMetrics`.
2. `ServiceMetrics` dataclass with standard counters/histograms: HTTP requests, Kafka events produced/consumed, outbox dispatched/errors.
3. `add_prometheus_middleware(app, metrics)` integrates with FastAPI.
4. Write unit tests.

**Tests**:
- Unit: Metric registration, counter increments, histogram observations
- Container: N/A
- Platform: N/A

**Documentation updates**: `libs/observability/IMPLEMENTATION.md`

**Acceptance criteria / DoD**:
- [ ] `create_metrics()` returns `ServiceMetrics` with standard counters/histograms
- [ ] `add_prometheus_middleware()` instruments FastAPI routes
- [ ] Tests pass, lint clean

**Effort**: S (2–4 hours)
**Risk**: None

---

### T-LIB-07: Implement OpenTelemetry tracing in observability lib

- **ID**: T-LIB-07
- **Title**: Add configure_tracing, get_tracer, and OTel middleware to observability lib
- **Objective**: Enable distributed tracing for Market Ingestion.

**Paths to read**:
- `worldview/libs/observability/src/observability/logging.py` (existing)
- `worldview/docs/libs/observability.md` (spec)

**Paths to change**:
- `worldview/libs/observability/src/observability/tracing.py` (create)
- `worldview/libs/observability/src/observability/__init__.py` (re-export)
- `worldview/libs/observability/tests/test_tracing.py` (create)
- `worldview/libs/observability/IMPLEMENTATION.md` (check items)

**Dependencies**: None

**Step-by-step actions**:
1. Create `tracing.py` with `configure_tracing(service_name, otlp_endpoint)` → sets up OTel SDK.
2. `get_tracer(name)` → returns OTel tracer.
3. `add_otel_middleware(app)` → instruments FastAPI with OpenTelemetry.
4. Auto-inject trace context into structlog (cross-module).
5. Write unit tests.

**Tests**:
- Unit: Tracer configuration, middleware attachment, context propagation stubs
- Container: N/A
- Platform: N/A

**Documentation updates**: `libs/observability/IMPLEMENTATION.md`

**Acceptance criteria / DoD**:
- [ ] `configure_tracing()` sets up OTel with OTLP gRPC exporter
- [ ] `get_tracer()` returns scoped tracer
- [ ] `add_otel_middleware()` instruments FastAPI
- [ ] Tests pass, lint clean

**Effort**: S (2–4 hours)
**Risk**: Low

---

## Milestone 1 — Domain Layer

---

### T-MI-01: Port domain enums

- **ID**: T-MI-01
- **Title**: Port domain enums to worldview market-ingestion
- **Objective**: Establish the foundational enum types used throughout the service.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/domain/enums.py`
- `worldview/AGENTS.md` (naming conventions)

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/domain/__init__.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/domain/enums.py` (create)
- `worldview/services/market-ingestion/tests/domain/__init__.py` (create)
- `worldview/services/market-ingestion/tests/domain/test_enums.py` (create)

**Dependencies**: None

**Step-by-step actions**:
1. Create `domain/` package.
2. Copy `enums.py` from legacy.
3. Verify all `StrEnum` members match service spec.
4. Write tests: membership, string conversion, exhaustive coverage of values.
5. Lint + type-check.

**Tests**:
- Unit: All enum values accessible, string conversion, iteration
- Container: N/A
- Platform: N/A

**Documentation updates**: None (enums already documented in service spec)

**Acceptance criteria / DoD**:
- [ ] `Provider`, `DatasetType`, `FundamentalsVariant`, `IngestionTaskStatus`, `OutboxStatus` enums defined
- [ ] All `StrEnum` with lowercase string values
- [ ] Tests pass, lint clean

**Effort**: XS (< 1 hour)
**Risk**: None

---

### T-MI-02: Port domain value objects

- **ID**: T-MI-02
- **Title**: Port domain value objects to worldview market-ingestion
- **Objective**: Establish value objects used by entities and use cases.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/domain/value_objects.py`
- `worldview/libs/common/src/common/types.py` (NewType aliases)

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/domain/value_objects.py` (create)
- `worldview/services/market-ingestion/tests/domain/test_value_objects.py` (create)

**Dependencies**: T-MI-01

**Step-by-step actions**:
1. Copy legacy value objects: `Timeframe`, `ObjectRef`, `InstrumentKey`, `DateRange`.
2. Adapt imports to use `common.time` functions.
3. Remove legacy `tenant_id` references if any.
4. Write tests: validation (valid/invalid timeframes), `ObjectRef` construction, `DateRange` boundary checks.

**Tests**:
- Unit: Timeframe validation (valid/invalid strings), ObjectRef field access, DateRange start < end validation, InstrumentKey construction
- Container: N/A
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] `Timeframe`, `ObjectRef`, `InstrumentKey`, `DateRange` defined
- [ ] Timeframe validates against known set
- [ ] DateRange rejects invalid ranges
- [ ] ObjectRef immutable with all claim-check fields
- [ ] Tests pass, lint clean

**Effort**: XS (1–2 hours)
**Risk**: None

---

### T-MI-03: Port domain errors

- **ID**: T-MI-03
- **Title**: Port domain error hierarchy to worldview market-ingestion
- **Objective**: Establish the error taxonomy, mapping to RetryableError / FatalError classification.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/domain/errors.py`
- `worldview/CLAUDE.md` (RetryableError vs FatalError classification)

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/domain/errors.py` (create)
- `worldview/services/market-ingestion/tests/domain/test_errors.py` (create)

**Dependencies**: None

**Step-by-step actions**:
1. Copy legacy error hierarchy.
2. Add `is_retryable` property to base `DomainError`.
3. Classify: `ProviderRateLimited`, `ProviderUnavailable`, `StorageUnavailable` → retryable. `ProviderAuthError`, `ProviderDataError`, `InvalidStateTransition`, `WatermarkViolation` → fatal.
4. Write tests for each error class: construction, message, `is_retryable` property.

**Tests**:
- Unit: Each error class constructable, correct `is_retryable` classification, error message formatting
- Container: N/A
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] Full error hierarchy ported
- [ ] Each error classified as retryable or fatal
- [ ] Tests cover all error types
- [ ] Lint + type-check clean

**Effort**: XS (1–2 hours)
**Risk**: None

---

### T-MI-04: Port domain entity — IngestionTask

- **ID**: T-MI-04
- **Title**: Port IngestionTask entity with state machine and retry logic
- **Objective**: Establish the core work-unit entity with lease-based locking and exponential backoff.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/domain/entities/ingestion_task.py`
- `worldview/libs/common/src/common/ids.py` (ID generation)
- `worldview/RULES.md` R10 (UUIDv7)

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/domain/entities/__init__.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/domain/entities/ingestion_task.py` (create)
- `worldview/services/market-ingestion/tests/domain/test_ingestion_task.py` (create)

**Dependencies**: T-MI-01, T-MI-02, T-MI-03

**Step-by-step actions**:
1. Copy legacy `IngestionTask` entity.
2. Replace UUID v4 generation with UUIDv7 (use `uuid7` library or `common.ids`).
3. Preserve: state machine transitions, lease logic, exponential backoff with jitter, dedupe key factory methods.
4. Use `common.time.utc_now()` for all timestamps.
5. Write comprehensive tests.

**Tests**:
- Unit: State transitions (PENDING→RUNNING, RUNNING→SUCCEEDED, RUNNING→RETRY, RUNNING→FAILED), invalid transitions (FAILED→RUNNING), lease expiration logic, backoff calculation (base=30s, max=1h, ±20% jitter), dedupe key generation, factory methods (QUOTES, OHLCV, FUNDAMENTALS), max attempts enforcement
- Container: N/A
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] `IngestionTask` entity with full state machine
- [ ] UUIDv7 for IDs
- [ ] Exponential backoff: `base * 2^(attempt-1)` capped at 1h with ±20% jitter
- [ ] Max 5 attempts
- [ ] Lease-based locking (`locked_by`, `locked_until`)
- [ ] Factory methods for each dataset type
- [ ] Dedupe key for idempotent enqueue
- [ ] ≥15 unit tests covering state machine + backoff + edge cases

**Effort**: S (2–4 hours)
**Risk**: Low — well-defined logic

---

### T-MI-05: Port domain entity — PollingPolicy

- **ID**: T-MI-05
- **Title**: Port PollingPolicy entity with adaptive scheduling
- **Objective**: Establish polling policy entity with interval calculation, priority ordering, and backfill support.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/domain/entities/polling_policy.py`

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/domain/entities/polling_policy.py` (create)
- `worldview/services/market-ingestion/tests/domain/test_polling_policy.py` (create)

**Dependencies**: T-MI-01, T-MI-02

**Step-by-step actions**:
1. Copy legacy `PollingPolicy`.
2. Replace UUID v4 with UUIDv7.
3. Preserve: adaptive interval formula, priority ordering, wildcard matching, backfill config.
4. Write tests.

**Tests**:
- Unit: Adaptive interval calculation (`base / (1 + k * hotness)`), priority ordering comparisons, wildcard matching (NULL symbol matches all), backfill config fields, base interval validation, enabled/disabled toggling
- Container: N/A
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] `PollingPolicy` with adaptive scheduling
- [ ] Backfill support fields
- [ ] Priority-based ordering
- [ ] Wildcard symbol matching
- [ ] Tests pass

**Effort**: S (2–3 hours)
**Risk**: None

---

### T-MI-06: Port domain entity — ProviderBudget

- **ID**: T-MI-06
- **Title**: Port ProviderBudget entity with token-bucket rate limiting
- **Objective**: Establish provider budget entity preventing API rate-limit violations.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/domain/entities/provider_budget.py`

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/domain/entities/provider_budget.py` (create)
- `worldview/services/market-ingestion/tests/domain/test_provider_budget.py` (create)

**Dependencies**: T-MI-01

**Step-by-step actions**:
1. Copy legacy `ProviderBudget`.
2. Replace UUID v4 with UUIDv7.
3. Preserve: token-bucket logic (`consume()`, `try_consume()`, `refill()`, `time_until_available()`), provider defaults (EODHD: 1000 burst / 10 refill/s, Alpha Vantage: 5/0.083).
4. Write tests.

**Tests**:
- Unit: Token consumption, refill over time, burst limit, `try_consume()` failure when empty, `time_until_available()` accuracy, provider-specific defaults
- Container: N/A
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] Token bucket with burst + refill rate
- [ ] Provider-specific factory defaults
- [ ] `consume()`, `try_consume()`, `refill()`, `time_until_available()`
- [ ] Tests pass

**Effort**: S (2–3 hours)
**Risk**: None

---

### T-MI-07: Port domain entity — Watermark

- **ID**: T-MI-07
- **Title**: Port Watermark entity with monotonic advancement and backfill phase tracking
- **Objective**: Establish the progress-tracking entity with SHA-256 dedup and backfill state machine.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/domain/entities/watermark.py`

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/domain/entities/watermark.py` (create)
- `worldview/services/market-ingestion/tests/domain/test_watermark.py` (create)

**Dependencies**: T-MI-01, T-MI-02

**Step-by-step actions**:
1. Copy legacy `Watermark`.
2. Replace UUID v4 with UUIDv7.
3. Preserve: natural key tuple, `advance_bar_ts()` monotonic behavior, SHA-256 dedup, backfill phase state machine (PENDING→IN_PROGRESS→COMPLETED).
4. Write tests.

**Tests**:
- Unit: Natural key construction, `advance_bar_ts()` only moves forward, SHA-256 comparison gates publishing, backfill phase transitions (valid + invalid), monotonicity violation raises error
- Container: N/A
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] 6-part natural key
- [ ] Monotonic bar-timestamp advancement
- [ ] SHA-256 dedup comparison
- [ ] Backfill phase state machine
- [ ] Tests pass

**Effort**: S (2–3 hours)
**Risk**: None

---

### T-MI-08: Port domain events

- **ID**: T-MI-08
- **Title**: Port domain events with worldview envelope standard
- **Objective**: Establish domain events conforming to the new event envelope standard (UUIDv7, schema_version, correlation/causation).

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/domain/events.py`
- `worldview/AGENTS.md` (event envelope standard)

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/domain/events.py` (create)
- `worldview/services/market-ingestion/tests/domain/test_events.py` (create)

**Dependencies**: T-MI-02 (ObjectRef value object)

**Step-by-step actions**:
1. Copy legacy domain events.
2. Adapt `DomainEvent` base to match worldview envelope: `event_id` (UUIDv7), `event_type` (string), `schema_version` (int), `occurred_at` (ISO-8601 UTC), `correlation_id`, `causation_id`.
3. Ensure `MarketDatasetFetched` carries `bronze_ref` + `canonical_ref` as `ObjectRef`.
4. Implement `AvroDictable` protocol (`to_dict()`, `from_dict()`).
5. Write tests.

**Tests**:
- Unit: Event construction, `to_dict()` serialization, `from_dict()` deserialization roundtrip, envelope fields auto-populated, UUIDv7 format validation, `AvroDictable` protocol check
- Container: N/A
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] `DomainEvent` base with envelope fields
- [ ] `MarketDatasetFetched` with claim-check ObjectRefs
- [ ] `AvroDictable` protocol compliance
- [ ] `IngestionTaskCompleted`, `IngestionTaskScheduled` internal events
- [ ] Tests pass

**Effort**: S (2–3 hours)
**Risk**: Low

---

## Milestone 2 — Application Layer

---

### T-MI-09: Port application ports (interfaces)

- **ID**: T-MI-09
- **Title**: Port all application port interfaces
- **Objective**: Establish the abstract interface layer (adapter ports, repository ports, UoW) using worldview lib types.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/application/ports/adapters.py`
- `platform_repo/apps/backend-market-ingestion/src/app/application/ports/repositories.py`
- `platform_repo/apps/backend-market-ingestion/src/app/application/ports/unit_of_work.py`
- `worldview/libs/storage/src/storage/` (ObjectStorage interface)
- `worldview/libs/messaging/src/messaging/` (AvroDictable)

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/application/__init__.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/application/ports/__init__.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/application/ports/adapters.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/application/ports/repositories.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/application/ports/unit_of_work.py` (create)

**Dependencies**: T-MI-01 through T-MI-08 (domain layer complete)

**Step-by-step actions**:
1. Copy legacy port interfaces.
2. Adapt imports to reference worldview domain types and lib types.
3. Ensure `ObjectStoreAdapter` interface aligns with `libs/storage.ObjectStorage` ABC.
4. Ensure `CanonicalSerializer` uses `libs/contracts` canonical models.
5. Verify all async method signatures.
6. No tests needed for ABCs directly (tested via implementations).

**Tests**:
- Unit: N/A (abstract interfaces, tested through implementations)
- Container: N/A
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] All 9 port interfaces defined as Python ABCs / Protocols
- [ ] Imports reference worldview domain types
- [ ] Adapter ports compatible with worldview lib interfaces
- [ ] Type-check clean (`mypy`)

**Effort**: S (2–3 hours)
**Risk**: None

---

### T-MI-10: Port use case — ScheduleDueTasks

- **ID**: T-MI-10
- **Title**: Port ScheduleDueTasksUseCase with three-phase tick logic
- **Objective**: Implement the scheduler's core logic: evaluate policies → handle backfill/incremental → apply budgets and enqueue.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/application/use_cases/schedule_tasks.py`

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/application/use_cases/__init__.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py` (create)
- `worldview/services/market-ingestion/tests/application/__init__.py` (create)
- `worldview/services/market-ingestion/tests/application/test_schedule_tasks.py` (create)

**Dependencies**: T-MI-09 (ports)

**Step-by-step actions**:
1. Copy legacy `ScheduleDueTasksUseCase`.
2. Adapt to worldview domain types and port interfaces.
3. Use `get_logger(__name__)` from observability.
4. Write unit tests with mocked UoW, repos, and budget tracker.

**Tests**:
- Unit: Policy evaluation (enabled only), backfill task creation (chunked), incremental task creation, wildcard matching, budget application (tasks trimmed when budget exhausted), idempotent enqueue (dedupe key), max_tasks_per_tick cap, empty policies edge case, all-budgets-exhausted edge case
- Container: N/A
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] Three-phase tick implemented
- [ ] Backfill state machine integration
- [ ] Budget-aware task trimming
- [ ] Idempotent enqueue via dedupe key
- [ ] ≥10 unit tests
- [ ] Lint + type-check clean

**Effort**: M (4–6 hours)
**Risk**: Medium — complex logic with interleaved backfill/incremental paths

---

### T-MI-11: Port use case — ClaimTasks

- **ID**: T-MI-11
- **Title**: Port ClaimTasksUseCase
- **Objective**: Implement worker claim logic (delegate to repository's `claim_batch`).

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/application/use_cases/claim_tasks.py`

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/application/use_cases/claim_tasks.py` (create)
- `worldview/services/market-ingestion/tests/application/test_claim_tasks.py` (create)

**Dependencies**: T-MI-09

**Step-by-step actions**:
1. Copy legacy `ClaimTasksUseCase` (simple UoW wrapper).
2. Adapt imports.
3. Write tests with mocked repository.

**Tests**:
- Unit: Claim returns tasks, empty result when none available, worker_id propagation, batch size respected
- Container: N/A (real claiming tested in T-MI-17)
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] Delegates to `TaskRepository.claim_batch()`
- [ ] Sets `worker_id` on claimed tasks
- [ ] Tests pass

**Effort**: XS (< 1 hour)
**Risk**: None

---

### T-MI-12: Port use case — ExecuteTask

- **ID**: T-MI-12
- **Title**: Port ExecuteTaskUseCase with provider fetch + bronze/canonical + outbox pipeline
- **Objective**: Implement the critical data pipeline: fetch → store bronze → canonicalize → store canonical → short tx (watermark + outbox + succeed).

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/application/use_cases/execute_task.py`

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py` (create)
- `worldview/services/market-ingestion/tests/application/test_execute_task.py` (create)

**Dependencies**: T-MI-09, T-MI-08 (domain events)

**Step-by-step actions**:
1. Copy legacy `ExecuteTaskUseCase`.
2. Preserve the critical workflow ordering: fetch outside tx → store bronze outside tx → canonicalize outside tx → store canonical outside tx → short tx.
3. Adapt error handling: `ProviderRateLimited`/`ProviderUnavailable` → retry; `ProviderAuthError`/`ProviderDataError` → fail.
4. Ensure watermark advancement is monotonic.
5. Ensure SHA-256 comparison gates outbox event creation (no publish if data unchanged).
6. Write extensive tests.

**Tests**:
- Unit (mocked ports): Happy path end-to-end (fetch→bronze→canonical→watermark→outbox→succeed), provider rate-limited → retry with backoff, provider unavailable → retry, provider auth error → fail, provider data error → fail, storage unavailable → retry, unchanged data (same SHA) → skip outbox, watermark monotonic advancement, different dataset types (QUOTES, OHLCV, FUNDAMENTALS)
- Container: N/A (integration in T-MI-23)
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] 5-step pipeline implemented in correct order
- [ ] Error classification maps to retry/fail correctly
- [ ] SHA-256 dedup gates event publishing
- [ ] Watermark monotonically advanced
- [ ] Short DB transaction for final commit
- [ ] ≥12 unit tests covering happy + error + edge paths

**Effort**: L (6–8 hours)
**Risk**: Medium — critical path; must preserve exact same transactional semantics

---

### T-MI-13: Port use case — TriggerIngestion

- **ID**: T-MI-13
- **Title**: Port TriggerIngestionUseCase for manual API triggers
- **Objective**: Enable manual ingestion triggers with idempotent task creation.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/application/use_cases/trigger_ingestion.py`

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/application/use_cases/trigger_ingestion.py` (create)
- `worldview/services/market-ingestion/tests/application/test_trigger_ingestion.py` (create)

**Dependencies**: T-MI-09

**Step-by-step actions**:
1. Copy legacy `TriggerIngestionUseCase`.
2. Adapt to worldview types.
3. Ensure idempotency via dedupe_key.
4. Write tests.

**Tests**:
- Unit: Single symbol trigger, multi-symbol trigger, idempotent behavior (same dedupe key), task creation with correct dataset type and provider
- Container: N/A
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] Creates tasks for given symbols
- [ ] Idempotent via dedupe_key
- [ ] Tests pass

**Effort**: XS (1–2 hours)
**Risk**: None

---

### T-MI-14: Port use case — Backfill

- **ID**: T-MI-14
- **Title**: Port BackfillUseCase with date-range chunking
- **Objective**: Enable chunked OHLCV backfill task creation.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/application/use_cases/backfill.py`

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/application/use_cases/backfill.py` (create)
- `worldview/services/market-ingestion/tests/application/test_backfill.py` (create)

**Dependencies**: T-MI-09

**Step-by-step actions**:
1. Copy legacy `BackfillUseCase`.
2. Preserve: 30-day default chunk size, max 100 chunks, date range splitting.
3. Write tests.

**Tests**:
- Unit: Date range split into 30-day chunks, max 100 chunks limit, single-day range, range spanning year boundary, idempotent via dedupe key
- Container: N/A
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] Splits date range into N-day chunks
- [ ] Max 100 chunks enforced
- [ ] Each chunk becomes one `IngestionTask`
- [ ] Tests pass

**Effort**: XS (1–2 hours)
**Risk**: Low — edge cases around date boundaries (DST, market holidays)

---

## Milestone 3 — Infrastructure Layer

---

### T-MI-15: Implement DB models + session factory

- **ID**: T-MI-15
- **Title**: Create SQLAlchemy 2.0 DB models and async session factory
- **Objective**: Define the 5 database tables and session management for the migrated service.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/db/models/` (all model files)
- `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/db/session.py`
- `worldview/services/market-ingestion/src/market_ingestion/config.py` (Settings)

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/__init__.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/db/__init__.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/db/models/__init__.py` (create, with `Base`)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/db/models/ingestion_task.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/db/models/watermark.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/db/models/polling_policy.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/db/models/provider_budget.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/db/models/outbox_event.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/db/session.py` (create)

**Dependencies**: T-MI-01 (enums)

**Step-by-step actions**:
1. Copy legacy SQLAlchemy models.
2. Adapt: use `Mapped[]` column declarations (SA 2.0 style), TIMESTAMPTZ for all dates, UUID columns for IDs.
3. Preserve all indexes: `ix_ingestion_tasks_claimable`, `uq_ingestion_tasks_dedupe_key`, `ix_ingestion_tasks_active_check`, `uq_ingestion_watermarks_natural_key`, `ix_polling_policies_enabled`, `ix_outbox_events_*`.
4. Create `Base = DeclarativeBase()` in `models/__init__.py`.
5. Session factory: adapt to read DB URL from `MARKET_INGESTION_DATABASE_URL` (new prefix).
6. Dual session support (write + read).

**Tests**:
- Unit: Model instantiation, column type validation
- Container: DB migration test (see T-MI-16)
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] 5 SQLAlchemy 2.0 models defined
- [ ] All indexes preserved from legacy
- [ ] `Base.metadata` correctly aggregates all tables
- [ ] Dual session factory (write + read)
- [ ] Lint + type-check clean

**Effort**: M (4–6 hours)
**Risk**: Low — mechanical port with index preservation

---

### T-MI-16: Generate Alembic migration

- **ID**: T-MI-16
- **Title**: Wire Alembic to Base.metadata and generate initial migration
- **Objective**: Generate the initial Alembic migration from the SQLAlchemy models, creating all 5 tables with indexes.

**Paths to read**:
- `worldview/services/market-ingestion/alembic/env.py` (existing scaffold with TODO)
- `worldview/services/market-ingestion/alembic.ini`

**Paths to change**:
- `worldview/services/market-ingestion/alembic/env.py` (update: import Base.metadata)
- `worldview/services/market-ingestion/alembic/versions/` (auto-generated migration)

**Dependencies**: T-MI-15

**Step-by-step actions**:
1. Update `env.py`: import `Base.metadata` from `market_ingestion.infrastructure.db.models`, set `target_metadata = Base.metadata`.
2. Run `alembic revision --autogenerate -m "initial_schema"`.
3. Review generated migration: verify all 5 tables, all indexes, all constraints match legacy schema.
4. Manually verify functional equivalence with legacy schema (same columns, same index definitions).
5. Test: `alembic upgrade head` against a clean database.

**Tests**:
- Unit: N/A
- Container: `alembic upgrade head` + `alembic downgrade base` roundtrip on empty Postgres
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] `env.py` wired to `Base.metadata`
- [ ] Initial migration auto-generated
- [ ] Migration creates all 5 tables with correct columns and indexes
- [ ] Upgrade + downgrade roundtrip succeeds
- [ ] No runtime warnings

**Effort**: S (2–3 hours)
**Risk**: Low — auto-generated; risk is in index naming differences

---

### T-MI-17: Port DB repositories

- **ID**: T-MI-17
- **Title**: Port all 5 SQLAlchemy repositories and UnitOfWork
- **Objective**: Implement the repository layer with `FOR UPDATE SKIP LOCKED` claiming and ON CONFLICT dedup.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/db/repositories/` (all repo files)
- `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/db/unit_of_work.py`

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/__init__.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/task_repository.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/watermark_repository.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/policy_repository.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/budget_repository.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/outbox_repository.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/db/unit_of_work.py` (create)
- `worldview/services/market-ingestion/tests/infrastructure/__init__.py` (create)
- `worldview/services/market-ingestion/tests/infrastructure/test_repositories.py` (create)

**Dependencies**: T-MI-15, T-MI-16

**Step-by-step actions**:
1. Copy all 5 legacy repository implementations.
2. Adapt dual-session routing to new session factory.
3. Preserve `claim_batch()` with `FOR UPDATE SKIP LOCKED`.
4. Preserve `ON CONFLICT DO NOTHING` for idempotent enqueue.
5. Outbox repo: preserve event serialization, topic routing, lease-based claiming.
6. Copy `SqlAlchemyUnitOfWork` with `on_commit` callback and `mark_outbox_events_added()` flag.
7. Write integration tests (require running Postgres).

**Tests**:
- Unit (with in-memory or mocked session): Mapper logic, event serialization in outbox repo
- Container (marker: `integration`, Postgres required): Task add + claim roundtrip, idempotent enqueue (duplicate dedupe_key), watermark get_or_create race safety, outbox claim + mark_published, policy list_enabled filtering, UoW commit + rollback behavior, concurrent claim (2 workers, no double-claim)
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] 5 repositories implementing port interfaces
- [ ] `claim_batch()` uses `FOR UPDATE SKIP LOCKED`
- [ ] `add()`/`add_many()` use `ON CONFLICT DO NOTHING`
- [ ] UoW aggregates all repos with commit/rollback
- [ ] `on_commit` callback triggers dispatcher notification
- [ ] Integration tests pass against real Postgres

**Effort**: L (8–12 hours)
**Risk**: Medium — concurrency semantics, dual-session wiring

---

### T-MI-18: Port object store adapter

- **ID**: T-MI-18
- **Title**: Port S3ObjectStoreAdapter for bronze/canonical storage
- **Objective**: Implement the MinIO adapter wrapping `libs/storage.ObjectStorage`, with SHA-256 computation and key building.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/adapters/object_store.py`
- `worldview/libs/storage/src/storage/key_builder.py`
- `worldview/libs/storage/src/storage/` (ObjectStorage, when available)

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/adapters/__init__.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/adapters/object_store.py` (create)
- `worldview/services/market-ingestion/tests/infrastructure/test_object_store.py` (create)

**Dependencies**: T-LIB-03 (storage lib), T-MI-02 (ObjectRef)

**Step-by-step actions**:
1. Copy legacy adapter.
2. Adapt to use `libs/storage.ObjectStorage` and `libs/storage.KeyBuilder` instead of direct boto3.
3. Preserve SHA-256 computation on put.
4. Return `ObjectRef` value objects.
5. Write tests.

**Tests**:
- Unit (mocked ObjectStorage): Put computes SHA-256, key built via KeyBuilder with correct pattern, get returns bytes, ObjectRef construction
- Container (marker: `integration`, MinIO): Real put/get/exists roundtrip, bucket creation
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] Wraps `libs/storage.ObjectStorage`
- [ ] SHA-256 computed and stored in ObjectRef
- [ ] Key format: `market-ingestion/{domain}/{resource_id}/{artifact}/{version}.{ext}`
- [ ] Tests pass

**Effort**: S (2–3 hours)
**Risk**: Low — depends on T-LIB-03 completion

---

### T-MI-19: Port EODHD provider adapter

- **ID**: T-MI-19
- **Title**: Port EODHD provider adapter with full API integration
- **Objective**: Migrate the only fully-implemented provider adapter (EODHD) with HTTP error handling and response normalization.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/adapters/providers/eodhd.py` (626 lines)
- `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/adapters/providers/__init__.py` (registry)

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/__init__.py` (create — registry)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/eodhd.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/polygon.py` (create — stub)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/yahoo.py` (create — stub)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/alpha_vantage.py` (create — stub)
- `worldview/services/market-ingestion/tests/infrastructure/test_eodhd.py` (create)

**Dependencies**: T-MI-09 (ProviderAdapter port), T-MI-03 (domain errors)

**Step-by-step actions**:
1. Copy EODHD adapter (626 lines).
2. Adapt: use `get_logger(__name__)` from observability, import domain errors from new paths.
3. Preserve: httpx.AsyncClient, symbol format `{SYMBOL}.{EXCHANGE}`, 429 → ProviderRateLimited, 401/403 → ProviderAuthError, 5xx → ProviderUnavailable.
4. Copy stub adapters for Polygon, Yahoo, Alpha Vantage.
5. Copy provider registry with `get_provider_adapter()` / `register_provider_adapter()`.
6. Write tests with `httpx.MockTransport` or `respx`.

**Tests**:
- Unit (mocked HTTP): Successful quotes fetch, successful OHLCV fetch, successful fundamentals fetch, 429 → ProviderRateLimited, 401 → ProviderAuthError, 500 → ProviderUnavailable, malformed JSON → ProviderDataError, demo key handling, symbol format construction, response normalization (all field mappings)
- Container: N/A (real API calls only in e2e)
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] Full EODHD adapter ported with all 3 fetch methods
- [ ] HTTP error → domain error mapping preserved
- [ ] Stub adapters for Polygon, Yahoo, Alpha Vantage
- [ ] Provider registry implemented
- [ ] ≥10 unit tests with mocked HTTP
- [ ] Lint + type-check clean

**Effort**: M (4–6 hours)
**Risk**: Low — well-tested legacy code

---

### T-MI-20: Port canonical serializer

- **ID**: T-MI-20
- **Title**: Port DefaultCanonicalSerializer for JSONL output
- **Objective**: Implement transformation from raw provider data to canonical JSONL format using `libs/contracts` models.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/adapters/canonical.py`
- `worldview/libs/contracts/src/contracts/canonical/` (all models)

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/adapters/canonical.py` (create)
- `worldview/services/market-ingestion/tests/infrastructure/test_canonical.py` (create)

**Dependencies**: T-LIB-01 (CanonicalQuote), T-LIB-02 (CanonicalFundamentals), T-MI-09 (CanonicalSerializer port)

**Step-by-step actions**:
1. Copy legacy `DefaultCanonicalSerializer`.
2. Adapt to use `libs/contracts` canonical models (`CanonicalOHLCVBar`, `CanonicalQuote`, `CanonicalFundamentals`).
3. Output format: JSONL (application/x-ndjson) for all types.
4. Write tests with sample data.

**Tests**:
- Unit: OHLCV serialization (multiple bars → JSONL), Quote serialization (single record), Fundamentals serialization (passthrough), schema_version embedded in output, empty data handling, malformed input handling
- Container: N/A
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] Serializes quotes, OHLCV, fundamentals to JSONL
- [ ] Uses `libs/contracts` canonical models
- [ ] MIME type: `application/x-ndjson`
- [ ] Schema version in each line
- [ ] Tests pass

**Effort**: S (2–3 hours)
**Risk**: None

---

### T-MI-21: Port Kafka serialization + Avro schema

- **ID**: T-MI-21
- **Title**: Port Kafka event serialization and relocate Avro schema
- **Objective**: Implement domain-event-to-Avro mapping and relocate the `market.dataset.fetched` Avro schema to `infra/kafka/schemas/`.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/messaging/kafka/` (all files)
- `worldview/libs/messaging/src/messaging/schemas.py`
- `worldview/libs/messaging/src/messaging/topics.py`
- `worldview/AGENTS.md` (Avro schema location convention)

**Paths to change**:
- `worldview/infra/kafka/schemas/market.dataset.fetched.avsc` (create — relocated)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/messaging/__init__.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/messaging/kafka/__init__.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/messaging/kafka/mapper.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/messaging/kafka/serialization.py` (create)
- `worldview/services/market-ingestion/tests/infrastructure/test_kafka_serialization.py` (create)

**Dependencies**: T-LIB-04 (Kafka producer), T-MI-08 (domain events)

**Step-by-step actions**:
1. Copy Avro schema `.avsc` file to `infra/kafka/schemas/`.
2. Verify schema has all 27 fields including claim-check refs.
3. Copy event mapper (`domain event → Avro dict`), adapting ObjectRef flattening.
4. Copy serialization factory (builds `AvroSerializer` per event type).
5. Reference `messaging.topics.MARKET_DATASET_FETCHED` instead of hardcoded string.
6. Write contract test: serialize → deserialize roundtrip.

**Tests**:
- Unit: Mapper produces correct dict from `MarketDatasetFetched` event, ObjectRef fields flattened correctly, all 27 schema fields present
- Contract: Avro serialize + deserialize roundtrip, schema forward compatibility check (add optional field, re-parse), schema validation against `.avsc` file
- Platform: N/A

**Documentation updates**: None (schema location is convention-driven)

**Acceptance criteria / DoD**:
- [ ] Avro schema at `infra/kafka/schemas/market.dataset.fetched.avsc`
- [ ] Mapper flattens ObjectRef to bucket/key/etag fields
- [ ] References centralized topic name from `messaging.topics`
- [ ] Serialize/deserialize roundtrip succeeds
- [ ] Forward compatibility test passes

**Effort**: M (4–5 hours)
**Risk**: Medium — schema registry subject naming must align with legacy to avoid breaking downstream consumers

---

### T-MI-22: Port outbox dispatcher (service-specific wiring)

- **ID**: T-MI-22
- **Title**: Wire service-specific outbox dispatcher using libs/messaging BaseOutboxDispatcher
- **Objective**: Connect the reusable `BaseOutboxDispatcher` from `libs/messaging` to Market Ingestion's UoW and Kafka serialization.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/messaging/dispatcher.py`
- `worldview/libs/messaging/` (BaseOutboxDispatcher, when available)

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/infrastructure/messaging/dispatcher.py` (create)
- `worldview/services/market-ingestion/tests/infrastructure/test_dispatcher.py` (create)

**Dependencies**: T-LIB-05 (BaseOutboxDispatcher), T-MI-17 (repos/UoW), T-MI-21 (Kafka serialization)

**Step-by-step actions**:
1. Create service-specific dispatcher subclass or factory that wires `BaseOutboxDispatcher` with: Market Ingestion's UoW factory, outbox repository, Kafka producer + Avro serializer.
2. Configure: poll interval, lease duration, max attempts, backpressure from Settings.
3. Write tests.

**Tests**:
- Unit (mocked deps): Outbox claim → produce → finalize happy path, produce failure → retry, dead-letter after max attempts
- Container (marker: `integration`): DB + Kafka round trip: insert outbox record → dispatcher publishes → verify Kafka message
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] Dispatcher wired to Market Ingestion infrastructure
- [ ] Configurable via `Settings`
- [ ] Hybrid dispatch mode (immediate + poll)
- [ ] Tests pass

**Effort**: S (2–4 hours)
**Risk**: Low — mostly wiring; complex logic in `libs/messaging`

---

## Milestone 4 — Entrypoints & Configuration

---

### T-MI-23: Implement API routes + dependency injection

- **ID**: T-MI-23
- **Title**: Implement FastAPI routes (trigger, backfill, status, policies) and DI wiring
- **Objective**: Complete the API layer with all endpoints from the service spec, wiring use cases via dependency injection.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/api/` (all files)
- `worldview/services/market-ingestion/src/market_ingestion/app.py` (existing scaffold)
- `worldview/services/market-ingestion/src/market_ingestion/config.py`

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/api/__init__.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/api/routes.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/api/schemas.py` (create — Pydantic request/response models)
- `worldview/services/market-ingestion/src/market_ingestion/api/dependencies.py` (create — DI factories)
- `worldview/services/market-ingestion/src/market_ingestion/app.py` (update — wire routes + lifespan)
- `worldview/services/market-ingestion/tests/api/__init__.py` (create)
- `worldview/services/market-ingestion/tests/api/test_routes.py` (create)

**Dependencies**: T-MI-10 through T-MI-14 (use cases), T-MI-17 (repos), T-MI-18 (object store), T-MI-19 (providers)

**Step-by-step actions**:
1. Create Pydantic request/response schemas for trigger, backfill, status, policies endpoints.
2. Create DI dependencies: get_uow, get_settings, get_object_store, get_provider_registry.
3. Create routes: `POST /api/v1/ingest/trigger`, `POST /api/v1/ingest/backfill`, `GET /api/v1/ingest/status`, `GET /api/v1/policies`.
4. Upgrade health probes: `/healthz` (always OK), `/readyz` (check DB + storage + Kafka), `/metrics` (Prometheus exposition).
5. Wire request-ID middleware for correlation tracking.
6. Update `app.py` lifespan: initialize DB engine, ensure storage bucket, register providers on startup; close connections on shutdown.
7. Add Prometheus middleware via `observability.add_prometheus_middleware()`.
8. Add OTel middleware via `observability.add_otel_middleware()`.
9. Write tests.

**Tests**:
- Unit (HTTPX async client, mocked DI): trigger endpoint accepts valid payload → 202, trigger with invalid payload → 422, backfill endpoint → 202, status endpoint returns counts, policies endpoint lists enabled, healthz → 200, readyz with mocked checks → 200, metrics endpoint returns text
- Container: N/A (full integration in T-MI-25)
- Platform: N/A

**Documentation updates**:
- `docs/services/market-ingestion.md` — verify API surface matches
- `configs/dev.local.env.example` — update any new env vars
- `configs/prod.env.example` — update any new env vars

**Acceptance criteria / DoD**:
- [ ] 6 API endpoints implemented per spec
- [ ] Health probes enriched with real checks
- [ ] `/metrics` Prometheus endpoint
- [ ] Request-ID middleware for correlation
- [ ] DI wiring for all infrastructure
- [ ] Lifespan init/shutdown
- [ ] Tests pass

**Effort**: L (6–10 hours)
**Risk**: Medium — DI wiring complexity; lifespan ordering

---

### T-MI-24: Implement scheduler + worker entrypoints

- **ID**: T-MI-24
- **Title**: Implement scheduler loop, worker loop, and standalone dispatcher process
- **Objective**: Implement the 3 non-API runtime processes.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/scheduler/main.py`
- `platform_repo/apps/backend-market-ingestion/src/app/worker/main.py`
- `platform_repo/apps/backend-market-ingestion/src/app/messaging/dispatcher_main.py`

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/scheduler/__init__.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/scheduler/main.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/worker/__init__.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/worker/main.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/messaging/__init__.py` (create)
- `worldview/services/market-ingestion/src/market_ingestion/messaging/dispatcher_main.py` (create)

**Dependencies**: T-MI-10 (ScheduleDueTasks), T-MI-11 (ClaimTasks), T-MI-12 (ExecuteTask), T-MI-22 (dispatcher wiring)

**Step-by-step actions**:
1. **Scheduler**: async loop with `asyncio.Event` + tick interval timeout; embeds outbox dispatcher; signal handling (SIGTERM/SIGINT); calls `ScheduleDueTasksUseCase` each tick.
2. **Worker**: claim/execute loop; worker ID = `{hostname}-{pid}`; embeds outbox dispatcher; configurable batch size and poll interval; horizontally scalable.
3. **Dispatcher**: standalone variant that only runs outbox polling (for deployments that don't embed dispatcher in scheduler/worker).
4. All use `configure_logging()` from observability at startup.
5. All read settings from `Settings` with `MARKET_INGESTION_` prefix.

**Tests**:
- Unit: Scheduler tick invokes use case, worker claims and executes, graceful shutdown signal handling (mock asyncio.Event)
- Container (marker: `integration`): Full scheduler → worker cycle with test DB + MinIO + Kafka — insert policy → scheduler creates task → worker claims and executes → outbox event published
- Platform: N/A

**Documentation updates**: Update `docs/services/market-ingestion.md` if entrypoint module paths change

**Acceptance criteria / DoD**:
- [ ] 3 runtime processes implemented
- [ ] Signal handling for graceful shutdown
- [ ] Embedded dispatcher in scheduler and worker
- [ ] Standalone dispatcher variant
- [ ] `configure_logging()` at startup
- [ ] Tests pass

**Effort**: M (4–6 hours)
**Risk**: Medium — async event loop coordination, signal handling edge cases

---

### T-MI-25: Update Settings + environment configs

- **ID**: T-MI-25
- **Title**: Finalize Settings class with all env vars and update example configs
- **Objective**: Ensure all configuration is declared, prefixed, and documented in example files.

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/config/settings.py` (legacy)
- `worldview/services/market-ingestion/src/market_ingestion/config.py` (current skeleton)
- `worldview/services/market-ingestion/configs/dev.local.env.example`
- `worldview/services/market-ingestion/configs/prod.env.example`

**Paths to change**:
- `worldview/services/market-ingestion/src/market_ingestion/config.py` (update)
- `worldview/services/market-ingestion/configs/dev.local.env.example` (update)
- `worldview/services/market-ingestion/configs/prod.env.example` (update)

**Dependencies**: T-MI-23 (API), T-MI-24 (scheduler/worker)

**Step-by-step actions**:
1. Add all missing Settings fields: scheduler (tick_interval, max_tasks_per_tick), worker (batch_size, lease_seconds, poll_interval), dispatcher (poll_interval, lease_seconds, max_attempts), provider API keys, otel_endpoint.
2. Reconcile port (8001 per spec vs 8002 in skeleton — use 8001 for prod, 8002 for dev).
3. Update `dev.local.env.example` with all variables and dev defaults.
4. Update `prod.env.example` with all variables and placeholder values.
5. Write test: Settings loads from env vars correctly.

**Tests**:
- Unit: Default values, env override, validation of required fields
- Container: N/A
- Platform: N/A

**Documentation updates**:
- `configs/dev.local.env.example`
- `configs/prod.env.example`
- `docs/services/market-ingestion.md` (if config section needs updating)

**Acceptance criteria / DoD**:
- [ ] All env vars declared with `MARKET_INGESTION_` prefix
- [ ] Example env files complete and accurate
- [ ] Settings test passes
- [ ] Port reconciled (8001 prod, 8002 dev)

**Effort**: S (2–3 hours)
**Risk**: None

---

## Milestone 5 — Testing & Quality

---

### T-MI-26: Write service container tests (Worker + DB + MinIO + Kafka)

- **ID**: T-MI-26
- **Title**: Comprehensive service container integration tests
- **Objective**: Validate the full ingestion pipeline in an isolated container environment.

**Paths to read**:
- All service code (complete by this point)
- `worldview/services/market-ingestion/tests/conftest.py`

**Paths to change**:
- `worldview/services/market-ingestion/tests/conftest.py` (update — add DB, MinIO, Kafka fixtures)
- `worldview/services/market-ingestion/tests/integration/__init__.py` (create)
- `worldview/services/market-ingestion/tests/integration/test_worker_pipeline.py` (create)
- `worldview/services/market-ingestion/tests/integration/test_scheduler_worker.py` (create)
- `worldview/services/market-ingestion/tests/integration/test_outbox_dispatch.py` (create)

**Dependencies**: All T-MI-* tasks complete

**Step-by-step actions**:
1. Set up `conftest.py` with: async Postgres fixture (testcontainers or local), MinIO fixture, Kafka fixture, Alembic migration fixture.
2. **Worker pipeline test**: seed policy + watermark → create task → claim → execute (mocked EODHD HTTP) → verify bronze object in MinIO → verify canonical object in MinIO → verify outbox event → dispatch → verify Kafka message.
3. **Scheduler-worker test**: seed policy → run scheduler tick → verify task created → worker claims and executes → verify end state.
4. **Outbox dispatch test**: insert outbox event → run dispatcher → verify Kafka message content (Avro deserialize + field check).
5. **Concurrent worker test**: 2 workers claiming from same pool → no double-claim.

**Tests**:
- Unit: N/A
- Container: Full pipeline, scheduler-worker cycle, outbox dispatch, concurrent claiming
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] Worker pipeline test passes end-to-end
- [ ] Scheduler → worker cycle verified
- [ ] Outbox dispatch verified with Avro deserialization
- [ ] No double-claiming under concurrency
- [ ] All tests marked with `integration` marker

**Effort**: L (8–12 hours)
**Risk**: Medium — test infrastructure setup complexity (containers, fixtures)

---

### T-MI-27: Write platform QA scenarios

- **ID**: T-MI-27
- **Title**: Define and implement platform QA test scenarios
- **Objective**: Validate the ingestion-to-downstream-materialization path (Market Ingestion → Kafka → Market Data).

**Paths to read**:
- `worldview/docs/architecture/diagrams.md` (event flow sequence)
- `worldview/docs/services/market-ingestion.md`

**Paths to change**:
- `worldview/services/market-ingestion/tests/platform/__init__.py` (create)
- `worldview/services/market-ingestion/tests/platform/test_ingestion_to_materialization.py` (create)

**Dependencies**: T-MI-26, Market Data service existence (may need stubs)

**Step-by-step actions**:
1. Define scenario: Market Ingestion produces `market.dataset.fetched` → Kafka → downstream consumer reads + verifies claim-check payload.
2. If Market Data not yet implemented: create a stub consumer that validates the event structure, deserializes via Avro, and fetches the canonical object from MinIO.
3. Verify: event envelope fields, claim-check ObjectRef valid, canonical object retrievable and parseable.
4. Mark tests with `platform` marker (not run in CI by default).

**Tests**:
- Unit: N/A
- Container: N/A
- Platform: Full ingestion → Kafka → consumer → MinIO fetch → parse canonical data

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] Platform test demonstrates end-to-end data flow
- [ ] Event envelope validated
- [ ] Claim-check references resolve to real objects
- [ ] Canonical data parseable
- [ ] Marked with `platform` marker

**Effort**: M (4–6 hours)
**Risk**: Medium — depends on Market Data service availability (can stub)

---

## Milestone 6 — Deployment & Operations

---

### T-MI-28: Update Docker Compose for worldview Market Ingestion

- **ID**: T-MI-28
- **Title**: Update Docker Compose to run migrated Market Ingestion
- **Objective**: Ensure `docker-compose up` launches the migrated service with all dependencies.

**Paths to read**:
- `worldview/docker-compose.yml` (existing)
- `worldview/services/market-ingestion/Makefile`

**Paths to change**:
- `worldview/docker-compose.yml` (update — add/modify market-ingestion service)
- `worldview/services/market-ingestion/Dockerfile` (create if not exists)

**Dependencies**: T-MI-25 (config finalized)

**Step-by-step actions**:
1. Create multi-stage `Dockerfile` for market-ingestion.
2. Add/update `docker-compose.yml` service entries: `market-ingestion-api`, `market-ingestion-scheduler`, `market-ingestion-worker`.
3. Ensure compose includes all infra deps: Postgres, MinIO, Kafka, Schema Registry, Zookeeper.
4. Wire env vars to compose env file / environment section.
5. Verify `docker-compose up market-ingestion-api` starts successfully.

**Tests**:
- Unit: N/A
- Container: `docker-compose up --build` → health check passes
- Platform: N/A

**Documentation updates**: `worldview/services/market-ingestion/README.md` (docker instructions)

**Acceptance criteria / DoD**:
- [ ] Dockerfile builds successfully
- [ ] Compose starts all 3 processes
- [ ] Health checks pass
- [ ] README updated with docker instructions

**Effort**: S (2–4 hours)
**Risk**: Low

---

### T-MI-29: Alembic seed migration for default policies

- **ID**: T-MI-29
- **Title**: Create Alembic data migration to seed default polling policies
- **Objective**: Seed the initial polling policies that the scheduler evaluates (equivalent to legacy seed migrations).

**Paths to read**:
- `platform_repo/apps/backend-market-ingestion/alembic/versions/2026_01_20_*_seed_default_policies.py`
- `platform_repo/apps/backend-market-ingestion/alembic/versions/2026_01_26_*_seed_backfill_for_demo_symbols.py`

**Paths to change**:
- `worldview/services/market-ingestion/alembic/versions/` (new migration)

**Dependencies**: T-MI-16 (initial migration)

**Step-by-step actions**:
1. Create data migration seeding default polling policies (same as legacy: EODHD OHLCV daily, EODHD quotes, etc.).
2. Include backfill policies for demo symbols.
3. Use `op.bulk_insert()` for efficiency.
4. Include downgrade (`op.execute("DELETE FROM polling_policies WHERE ...")`) for reversibility.
5. Test: `alembic upgrade head` applies cleanly.

**Tests**:
- Unit: N/A
- Container: Migration applies, policies queryable, downgrade removes seeds
- Platform: N/A

**Documentation updates**: None

**Acceptance criteria / DoD**:
- [ ] Default policies seeded
- [ ] Backfill demo policies seeded
- [ ] Upgrade + downgrade idempotent
- [ ] Migration applies on clean database

**Effort**: XS (1–2 hours)
**Risk**: None

---

### T-MI-30: Operational go-live checklist implementation

- **ID**: T-MI-30
- **Title**: Create operational runbook and validate go-live checklist
- **Objective**: Document operational procedures and validate all go-live gates.

**Paths to read**:
- `worldview/docs/services/market-ingestion.md`
- All completed task outputs

**Paths to change**:
- `worldview/docs/runbooks/market-ingestion-operations.md` (create)
- `worldview/docs/services/market-ingestion.md` (final review + update)

**Dependencies**: All previous tasks

**Step-by-step actions**:
1. Create runbook covering: startup sequence, health checks, common failure modes, recovery procedures, scaling guidance, monitoring dashboards.
2. Validate go-live checklist (see §6 below).
3. Final review of `docs/services/market-ingestion.md` for accuracy.

**Tests**:
- Unit: N/A
- Container: N/A
- Platform: Checklist validation exercise

**Documentation updates**:
- `docs/runbooks/market-ingestion-operations.md` (create)
- `docs/services/market-ingestion.md` (final update)

**Acceptance criteria / DoD**:
- [ ] Runbook created with all operational procedures
- [ ] Go-live checklist fully validated
- [ ] Service doc accurate and current

**Effort**: S (2–4 hours)
**Risk**: None

---

# §5 — Sequenced Roadmap by Milestones

## Milestone Dependency Graph

```
M0 (Library Prerequisites)
 ├── T-LIB-01 CanonicalQuote
 ├── T-LIB-02 CanonicalFundamentals
 ├── T-LIB-03 ObjectStorage impl
 ├── T-LIB-04 Kafka producer
 ├── T-LIB-05 BaseOutboxDispatcher ──────── depends on T-LIB-04
 ├── T-LIB-06 Prometheus metrics
 └── T-LIB-07 OpenTelemetry tracing
              │
M1 (Domain Layer) ─── can start once T-LIB-01, T-LIB-02 exist OR in parallel (domain has no lib dep)
 ├── T-MI-01 Enums
 ├── T-MI-02 Value Objects ──────────────── depends on T-MI-01
 ├── T-MI-03 Errors
 ├── T-MI-04 IngestionTask ─────────────── depends on T-MI-01, T-MI-02, T-MI-03
 ├── T-MI-05 PollingPolicy ─────────────── depends on T-MI-01, T-MI-02
 ├── T-MI-06 ProviderBudget ────────────── depends on T-MI-01
 ├── T-MI-07 Watermark ────────────────── depends on T-MI-01, T-MI-02
 └── T-MI-08 Domain Events ────────────── depends on T-MI-02
              │
M2 (Application Layer) ─── requires M1 complete
 ├── T-MI-09 Ports ────────────────────── depends on M1
 ├── T-MI-10 ScheduleDueTasks ─────────── depends on T-MI-09
 ├── T-MI-11 ClaimTasks ───────────────── depends on T-MI-09
 ├── T-MI-12 ExecuteTask ──────────────── depends on T-MI-09, T-MI-08
 ├── T-MI-13 TriggerIngestion ─────────── depends on T-MI-09
 └── T-MI-14 Backfill ────────────────── depends on T-MI-09
              │
M3 (Infrastructure Layer) ─── requires M0 libs + M2 application
 ├── T-MI-15 DB Models ────────────────── depends on T-MI-01
 ├── T-MI-16 Alembic Migration ────────── depends on T-MI-15
 ├── T-MI-17 Repositories + UoW ───────── depends on T-MI-15, T-MI-16
 ├── T-MI-18 Object Store Adapter ─────── depends on T-LIB-03, T-MI-02
 ├── T-MI-19 EODHD Provider ───────────── depends on T-MI-09, T-MI-03
 ├── T-MI-20 Canonical Serializer ─────── depends on T-LIB-01, T-LIB-02, T-MI-09
 ├── T-MI-21 Kafka Serialization ──────── depends on T-LIB-04, T-MI-08
 └── T-MI-22 Outbox Dispatcher ────────── depends on T-LIB-05, T-MI-17, T-MI-21
              │
M4 (Entrypoints & Config) ─── requires M2 + M3
 ├── T-MI-23 API Routes + DI ─────────── depends on M2 use cases, M3 infra
 ├── T-MI-24 Scheduler + Worker ───────── depends on T-MI-10, T-MI-11, T-MI-12, T-MI-22
 └── T-MI-25 Settings + Config ────────── depends on T-MI-23, T-MI-24
              │
M5 (Testing & Quality) ─── requires M4
 ├── T-MI-26 Container Tests ──────────── depends on all T-MI-*
 └── T-MI-27 Platform QA ─────────────── depends on T-MI-26
              │
M6 (Deployment & Operations) ─── requires M5
 ├── T-MI-28 Docker Compose ───────────── depends on T-MI-25
 ├── T-MI-29 Seed Migration ───────────── depends on T-MI-16
 └── T-MI-30 Operational Checklist ────── depends on all
```

## Suggested Sprint Allocation

| Sprint | Milestone | Tasks | Estimated Days |
|--------|-----------|-------|----------------|
| Sprint 1 | M0 (libs) + M1 (domain) | T-LIB-01..07 + T-MI-01..08 | 5–7 days |
| Sprint 2 | M2 (application) + M3 (infra start) | T-MI-09..14 + T-MI-15..16 | 4–6 days |
| Sprint 3 | M3 (infra complete) + M4 (entrypoints) | T-MI-17..22 + T-MI-23..25 | 6–8 days |
| Sprint 4 | M5 (testing) + M6 (deployment) | T-MI-26..30 | 4–6 days |

**Total estimated effort**: 19–27 working days

## Parallelization Opportunities

Within each milestone, many tasks can be done in parallel:

- **M0**: T-LIB-01, T-LIB-02, T-LIB-03, T-LIB-04, T-LIB-06, T-LIB-07 are all independent (only T-LIB-05 depends on T-LIB-04)
- **M1**: T-MI-01, T-MI-03 are independent. T-MI-04..T-MI-08 can start once T-MI-01+T-MI-02 are done.
- **M3**: T-MI-15 + T-MI-19 can start early (depend only on M1). T-MI-18, T-MI-20, T-MI-21 are independent once their deps complete.

---

# §6 — Operational Go-Live Checklist

## Pre-deployment Gates

- [ ] **All unit tests pass** — `cd services/market-ingestion && make test`
- [ ] **All integration tests pass** — `make test-integration`
- [ ] **Lint clean** — `make lint` (ruff + mypy)
- [ ] **Coverage ≥ 60%** with branch coverage
- [ ] **Alembic upgrade succeeds** on clean database — `make migrate`
- [ ] **Alembic downgrade succeeds** — rollback path verified
- [ ] **Docker image builds** — `docker build -t market-ingestion .`
- [ ] **Health probes pass** — `/healthz` + `/readyz` return 200 OK
- [ ] **Metrics endpoint works** — `/metrics` returns Prometheus text format

## Infrastructure Readiness

- [ ] **PostgreSQL** — `market_ingestion_db` created, schema migrated, read replica configured (if applicable)
- [ ] **MinIO** — bucket `market-ingestion` created, credentials configured
- [ ] **Kafka** — topic `market.dataset.fetched` created with correct partitions (≥3) and retention
- [ ] **Schema Registry** — Avro schema registered, compatibility mode set (FORWARD)
- [ ] **Valkey** — instance reachable (if negative caching enabled)

## Configuration Validation

- [ ] **All required env vars set** — no missing `MARKET_INGESTION_*` variables
- [ ] **Provider API keys valid** — `MARKET_INGESTION_EODHD_API_KEY` tested against demo endpoint
- [ ] **DB URL correct** — asyncpg connection string verified
- [ ] **Storage URL correct** — MinIO endpoint reachable
- [ ] **Kafka bootstrap correct** — broker reachable

## Functional Validation

- [ ] **Manual trigger test** — `POST /api/v1/ingest/trigger` → task created → worker executes → event published
- [ ] **Backfill test** — `POST /api/v1/ingest/backfill` → chunked tasks created → all complete
- [ ] **Scheduler tick test** — scheduler creates tasks from seeded policies
- [ ] **Worker claiming test** — multiple workers claim without duplication
- [ ] **Outbox dispatch test** — events reach Kafka with correct Avro schema
- [ ] **Claim-check test** — downstream consumer can fetch MinIO objects referenced in events
- [ ] **Rate limit test** — provider budget prevents API overuse
- [ ] **Retry test** — simulated provider failure → task retried correctly
- [ ] **Dead-letter test** — max-attempts exceeded → task marked failed

## Observability Validation

- [ ] **Logs structured** — JSON format with `service`, `correlation_id`, `task_id` fields
- [ ] **Metrics scrape** — Prometheus can scrape `/metrics` endpoint
- [ ] **SLI metrics present** — `task_execution_duration`, `task_success_rate`, `outbox_dispatch_latency`, `provider_error_rate`
- [ ] **Tracing active** — spans visible in trace backend (Jaeger/Grafana Tempo)

## Rollback Plan

- [ ] **Alembic downgrade tested** — can revert to empty schema
- [ ] **Docker image tagged** — previous version tagged for quick rollback
- [ ] **Kafka consumer group offset** — downstream consumers can reset offset if needed
- [ ] **Feature flag** — ability to disable scheduler/worker without redeployment (env var)

## Documentation Complete

- [ ] `docs/services/market-ingestion.md` — accurate and current
- [ ] `docs/runbooks/market-ingestion-operations.md` — operational procedures documented
- [ ] `configs/dev.local.env.example` — all env vars listed
- [ ] `configs/prod.env.example` — all env vars listed
- [ ] `README.md` — getting started instructions verified

---

# Appendix A — Task Summary Table

| ID | Title | Milestone | Effort | Risk | Dependencies |
|----|-------|-----------|--------|------|--------------|
| T-LIB-01 | CanonicalQuote | M0 | XS | None | — |
| T-LIB-02 | CanonicalFundamentals | M0 | XS | None | — |
| T-LIB-03 | S3ObjectStorage | M0 | M | Low | — |
| T-LIB-04 | Kafka Producer | M0 | M | Low | — |
| T-LIB-05 | BaseOutboxDispatcher | M0 | L | Medium | T-LIB-04 |
| T-LIB-06 | Prometheus Metrics | M0 | S | None | — |
| T-LIB-07 | OTel Tracing | M0 | S | Low | — |
| T-MI-01 | Domain Enums | M1 | XS | None | — |
| T-MI-02 | Domain Value Objects | M1 | XS | None | T-MI-01 |
| T-MI-03 | Domain Errors | M1 | XS | None | — |
| T-MI-04 | IngestionTask Entity | M1 | S | Low | T-MI-01, 02, 03 |
| T-MI-05 | PollingPolicy Entity | M1 | S | None | T-MI-01, 02 |
| T-MI-06 | ProviderBudget Entity | M1 | S | None | T-MI-01 |
| T-MI-07 | Watermark Entity | M1 | S | None | T-MI-01, 02 |
| T-MI-08 | Domain Events | M1 | S | Low | T-MI-02 |
| T-MI-09 | Application Ports | M2 | S | None | M1 |
| T-MI-10 | ScheduleDueTasks UC | M2 | M | Medium | T-MI-09 |
| T-MI-11 | ClaimTasks UC | M2 | XS | None | T-MI-09 |
| T-MI-12 | ExecuteTask UC | M2 | L | Medium | T-MI-09, 08 |
| T-MI-13 | TriggerIngestion UC | M2 | XS | None | T-MI-09 |
| T-MI-14 | Backfill UC | M2 | XS | Low | T-MI-09 |
| T-MI-15 | DB Models | M3 | M | Low | T-MI-01 |
| T-MI-16 | Alembic Migration | M3 | S | Low | T-MI-15 |
| T-MI-17 | Repositories + UoW | M3 | L | Medium | T-MI-15, 16 |
| T-MI-18 | Object Store Adapter | M3 | S | Low | T-LIB-03, T-MI-02 |
| T-MI-19 | EODHD Provider | M3 | M | Low | T-MI-09, 03 |
| T-MI-20 | Canonical Serializer | M3 | S | None | T-LIB-01, 02, T-MI-09 |
| T-MI-21 | Kafka Serialization | M3 | M | Medium | T-LIB-04, T-MI-08 |
| T-MI-22 | Outbox Dispatcher | M3 | S | Low | T-LIB-05, T-MI-17, 21 |
| T-MI-23 | API Routes + DI | M4 | L | Medium | M2, M3 |
| T-MI-24 | Scheduler + Worker | M4 | M | Medium | T-MI-10, 11, 12, 22 |
| T-MI-25 | Settings + Config | M4 | S | None | T-MI-23, 24 |
| T-MI-26 | Container Tests | M5 | L | Medium | All T-MI-* |
| T-MI-27 | Platform QA | M5 | M | Medium | T-MI-26 |
| T-MI-28 | Docker Compose | M6 | S | Low | T-MI-25 |
| T-MI-29 | Seed Migration | M6 | XS | None | T-MI-16 |
| T-MI-30 | Operational Checklist | M6 | S | None | All |

---

# Appendix B — Effort Legend

| Size | Hours | Description |
|------|-------|-------------|
| XS | < 2h | Trivial copy/adapt, minimal testing |
| S | 2–4h | Small module, few tests |
| M | 4–6h | Medium complexity, multiple test scenarios |
| L | 6–12h | High complexity, extensive testing, integration concerns |

---

# Response Metadata

## Implemented (What)

- Complete 6-section migration plan for Market Ingestion service
- 30 atomic tasks (7 lib prerequisites + 23 service tasks) with full specifications
- Dependency graph and sequenced roadmap
- Go-live operational checklist

## Approach (How)

1. Scanned entire legacy `platform_repo/apps/backend-market-ingestion/` codebase (58+ files across 4 layers)
2. Scanned entire target `worldview/services/market-ingestion/` skeleton + all 5 shared libs
3. Read all relevant documentation (12 docs: service spec, migration guide, architecture ADRs, lib docs, AGENTS.md, CLAUDE.md, RULES.md)
4. Mapped legacy components → target requirements → delta analysis
5. Decomposed into atomic tasks following dependency order
6. Cross-referenced all 18 rules from RULES.md against task DoDs

## Rationale (Why)

- **Copy → Adapt strategy** chosen per `docs/migration/REUSE_FROM_ORIGINAL_THESIS.md` — faster than rewriting, preserves battle-tested logic
- **Library prerequisites (M0) separated** because multiple shared libs are incomplete and block service infrastructure
- **Domain layer first (M1)** because it has zero external dependencies and can be developed/tested in isolation
- **Alembic regeneration** (not copy) per migration guide — avoids carrying legacy migration chain
- **UUIDv7 migration** required by R10 despite adding complexity — consistency mandate across all services
- **Env prefix change** aligns with worldview convention for multi-service isolation
- **Avro schema relocation** to `infra/kafka/schemas/` per AGENTS.md convention for centralized schema management
- **Sprint allocation** (4 sprints) balances thoroughness against academic thesis timeline

## Testing

- No code was implemented (plan only) — no tests executed
- Testing requirements specified per-task covering unit, container, and platform levels
- Test infrastructure requirements documented (Postgres, MinIO, Kafka fixtures)

## Documentation Updates

- This response artifact created at `docs/ai-interactions/agent-responses/0003-response-20260306-market-ingestion-migration-plan.md`
- No other docs modified (plan only; docs will be updated during implementation per individual task DoDs)

## Risks / Follow-ups

1. **Library completion is the critical path** — M0 tasks (especially T-LIB-03, T-LIB-04, T-LIB-05) must complete before M3 infrastructure can proceed
2. **UUIDv7 library selection** — need to verify `uuid7` package compatibility with Python 3.12 and SQLAlchemy
3. **Port reconciliation** — service spec says 8001, skeleton says 8002; plan recommends 8001 for prod
4. **Schema registry subject alignment** — must ensure `market.dataset.fetched` Avro subject matches legacy to avoid downstream breakage
5. **Observability metrics/tracing libs** may not be ready for Sprint 1; service can proceed with logging-only and add metrics/tracing hooks later
