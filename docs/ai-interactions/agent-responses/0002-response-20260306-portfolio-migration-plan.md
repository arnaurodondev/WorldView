# 0002 — Portfolio Migration Detailed Plan & Atomic Task Backlog

## Metadata

- **Prompt ID**: 0002
- **Prompt file**: `docs/ai-interactions/agent-planning/0002-portfolio-migration-detailed-plan-and-atomic-tasks.md`
- **Execution date**: 2026-03-06
- **Agent role(s)**: Backend Engineer + Architecture Decision Lead
- **Scope**: Complete migration/completion plan for Portfolio service from `platform_repo/apps/backend-portfolio` → `worldview/services/portfolio`, including shared library gaps

---

## Summary

- **Requested**: A detailed, NO-code migration plan with atomic executable task backlog for the Portfolio service in `worldview/`, covering all layers from domain to deployment.
- **Delivered**: Full current-state inventory, target-state checklist, gap matrix with severity, 38 atomic tasks with execution details, suggested sequence, and release readiness criteria.
- **Final status**: Plan complete — ready for sequential execution.

---

# 1. Current-State Inventory

## 1.1 Legacy (`platform_repo/apps/backend-portfolio`)

| Layer | Components | Lines (approx) | Status |
|-------|-----------|-----------------|--------|
| **Domain entities** | `Tenant`, `User`, `Portfolio`, `Transaction`, `Holding`, `InstrumentRef` | ~600 | Complete |
| **Domain enums** | `TenantStatus`, `UserStatus`, `PortfolioStatus`, `TransactionType`, `TransactionDirection`, `OutboxStatus`, `IdempotencyState` | ~80 | Complete |
| **Domain value objects** | `Money`, `InstrumentKey`, `Quantity` | ~340 | Complete |
| **Domain events** | 9 event types (`TenantCreated`, `UserCreated`, `PortfolioCreated`, `PortfolioRenamed`, `PortfolioArchived`, `TransactionRecorded`, `HoldingChanged`, `TenantStatusChanged`, `UserStatusChanged`) | ~260 | Complete |
| **Domain errors** | 15+ error classes with hierarchy (`DomainError` base) | ~540 | Complete |
| **Application ports** | 8 repository ABCs + `UnitOfWork` ABC + DTOs (`OutboxRecord`, `IdempotencyRecord`) | ~475 | Complete |
| **Use cases** | 12 use cases (tenant CRUD, user CRUD, portfolio ops, record transaction, read models, instrument ops) | ~700 | Complete |
| **API routes** | 12 endpoints across 5 routers (tenants, users, portfolios, transactions, holdings, instruments) + health | ~500 | Complete |
| **API schemas** | 10+ Pydantic request/response models | ~200 | Complete |
| **API error handling** | Exception handlers + error mapping + error schema | ~200 | Complete |
| **API DI/lifespan** | `dependencies.py` + `lifespan.py` | ~100 | Complete |
| **DB models** | 8 SQLAlchemy models (tenants, users, portfolios, transactions, holdings, instruments, outbox_events, idempotency_keys) | ~400 | Complete |
| **DB repositories** | 8 concrete SQLAlchemy repositories | ~800 | Complete |
| **DB session/UoW** | `create_session_factory()`, `SqlAlchemyUnitOfWork` | ~200 | Complete |
| **Messaging: topics** | 1 outbound topic, routing table | ~50 | Complete |
| **Messaging: mappers** | Event-to-dict mappers (envelope, transaction, user, tenant) | ~150 | Complete |
| **Messaging: serialization** | Avro serializer builders for outbox | ~60 | Complete |
| **Messaging: dispatcher** | `OutboxDispatcher` extending `BaseOutboxDispatcher` | ~500 | Complete |
| **Messaging: Avro schemas** | 3 `.avsc` files (transaction.recorded, user.created, tenant.created) | ~100 | Complete |
| **Consumers** | `InstrumentEventConsumer` (market.instrument.created/updated) | ~150 | Complete |
| **Config/settings** | `Settings(BaseSettings)` with 17+ config vars | ~80 | Complete |
| **Alembic migrations** | 3 migration files (initial, outbox lease, instrument fields) | ~300 | Complete |
| **Tests: unit** | 4 test files (entities, holding utils, user outbox, API errors) | ~500 | Complete |
| **Tests: contract** | 3 files (transaction recorded, tenant created, user created) | ~200 | Complete |
| **Tests: integration** | 3 files (tenant API, user API, portfolio API) + helpers/conftest | ~1200 | Complete |
| **K8s deploy** | deployment, service, configmap, secret | ~200 | Complete |

**Total: ~60 Python files, ~8,000+ LOC**

## 1.2 Target (`worldview/services/portfolio`)

| Layer | Components | Lines (approx) | Status |
|-------|-----------|-----------------|--------|
| **App factory** | `app.py` — FastAPI with lifespan, `/healthz`, `/readyz` | ~35 | Scaffold |
| **Config** | `config.py` — `Settings(BaseSettings)` with DB, Kafka, S3, Valkey URLs | ~20 | Scaffold |
| **Alembic** | `env.py` (async, `target_metadata = None`), `versions/.gitkeep` | ~25 | Scaffold |
| **Tests** | `test_health.py` — 2 health endpoint tests | ~15 | Scaffold |
| **Makefile** | run, test, lint, migrate targets | ~15 | Done |
| **Config files** | `dev.local.env.example`, `prod.env.example` | ~20 | Done |

**Total: 6 files, ~130 LOC — scaffold only**

## 1.3 Shared Libraries Status

| Library | Legacy | worldview | Gap Summary |
|---------|--------|-----------|-------------|
| **common** | `time.py` (functional), `ids.py` (empty), `types.py` (empty) | `time.py` ✅, `ids.py` ✅ (new), `types.py` ✅ (new) | Missing tests for `ids.py` and `types.py` |
| **contracts** | `ohlcv.py`, `quotes.py`, `fundamentals.py`, `parsing.py`, `versions.py` | `ohlcv.py` ✅, `versions.py` ✅ (extended) | Missing `quotes.py`, `fundamentals.py`, `parsing.py` |
| **messaging** | Full stack: consumer, producer, dispatcher, serializer, schema registry, valkey, ~1,600 LOC | `schemas.py` ✅ (new), `topics.py` ✅ (new) | Missing consumer base, producer, outbox dispatcher, valkey, serializer, schema registry — ~1,500 LOC gap |
| **storage** | Full: interface, s3_adapter, factory, health, exceptions, settings, keys, ~1,450 LOC | `settings.py` ✅, `key_builder.py` ✅ | Missing interface ABC, S3 adapter, factory, health, exceptions — ~900 LOC gap |
| **observability** | N/A (inline in services) | `logging.py` ✅ (new) | Missing metrics, tracing — ~300 LOC gap |

---

# 2. Target-State Checklist (from docs)

Source: `docs/services/portfolio.md`, `docs/migration/REUSE_FROM_ORIGINAL_THESIS.md`, `AGENTS.md`, `CLAUDE.md`, `docs/architecture/decisions/0001-initial-architecture.md`, `docs/libs/*.md`

## 2.1 Service Architecture

- [ ] Clean/Hexagonal layout: `domain/` → `application/` → `infrastructure/` → `api/`
- [ ] Pure domain layer with no framework dependencies
- [ ] Port interfaces in `application/ports/`
- [ ] Use cases in `application/use_cases/`
- [ ] SQLAlchemy async adapters in `infrastructure/db/`
- [ ] Kafka messaging in `infrastructure/messaging/`
- [ ] FastAPI routes in `api/routes/`

## 2.2 API Surface (from `docs/services/portfolio.md`)

- [ ] `POST /api/v1/tenants` — Create tenant
- [ ] `GET /api/v1/tenants/{id}` — Get tenant
- [ ] `POST /api/v1/users` — Create user
- [ ] `GET /api/v1/users/{id}` — Get user
- [ ] `POST /api/v1/portfolios` — Create portfolio
- [ ] `GET /api/v1/portfolios` — List portfolios
- [ ] `GET /api/v1/portfolios/{id}` — Get portfolio
- [ ] `PUT /api/v1/portfolios/{id}` — Rename portfolio
- [ ] `DELETE /api/v1/portfolios/{id}` — Archive portfolio
- [ ] `POST /api/v1/transactions` — Record transaction
- [ ] `GET /api/v1/transactions` — List transactions
- [ ] `GET /api/v1/holdings/{portfolio_id}` — Get holdings
- [ ] `GET /api/v1/instruments` — List local instrument refs
- [ ] `GET /healthz`, `GET /readyz`, `GET /metrics`

## 2.3 Events (produced to `portfolio.events.v1`)

- [ ] `tenant.created`
- [ ] `user.created`
- [ ] `portfolio.created`
- [ ] `portfolio.renamed`
- [ ] `portfolio.archived`
- [ ] `transaction.recorded`
- [ ] `holding.changed`
- [ ] `instrument_ref.created` (new — in docs but not in legacy)

## 2.4 Events Consumed

- [ ] `market.instrument.created` → `portfolio-instrument-sync` consumer group
- [ ] `market.instrument.updated` → `portfolio-instrument-sync` consumer group

## 2.5 Database (portfolio_db)

- [ ] `tenants` table
- [ ] `users` table
- [ ] `portfolios` table
- [ ] `transactions` table
- [ ] `holdings` table
- [ ] `instruments` table
- [ ] `outbox_events` table
- [ ] `idempotency` table

## 2.6 Observability

- [ ] Structured logging via `libs/observability` (`structlog`)
- [ ] Prometheus metrics via `/metrics` endpoint
- [ ] OpenTelemetry tracing (FastAPI + SQLAlchemy auto-instrumented)
- [ ] Contextual log fields: `service`, `tenant_id`, `correlation_id`, `portfolio_id`

## 2.7 Invariants

- [ ] Transactional outbox for all domain events
- [ ] Lease-based outbox dispatch (SELECT FOR UPDATE SKIP LOCKED)
- [ ] Idempotent API via `Idempotency-Key` header
- [ ] Idempotent consumers via `event_id` dedup
- [ ] UUIDv7 for all entity IDs
- [ ] UTC-only timestamps
- [ ] Multi-tenant scoping (tenant_id on every query)
- [ ] No cross-service DB access

## 2.8 Testing

- [ ] Unit tests: domain entities, value objects, use cases (with mocks)
- [ ] Contract tests: Avro schema validation via fastavro
- [ ] Integration tests: API → DB round-trip with testcontainers + savepoint isolation
- [ ] Makefile targets: `make test`, `make test-integration`, `make lint`

## 2.9 Deployment

- [ ] Alembic migrations (regenerated fresh)
- [ ] `configs/dev.local.env.example` with all config vars
- [ ] `configs/prod.env.example` with all config vars
- [ ] Docker Compose service definition
- [ ] K8s manifests (optional for thesis)

---

# 3. Gap Matrix

## 3.1 Shared Library Gaps (Portfolio depends on these)

| ID | Gap | Severity | Blocking? | Dependency |
|----|-----|----------|-----------|------------|
| L-01 | `libs/messaging`: Missing `BaseKafkaConsumer` | **CRITICAL** | Yes — blocks consumer | None |
| L-02 | `libs/messaging`: Missing `KafkaProducerConfig` + producer factory | **CRITICAL** | Yes — blocks dispatcher | None |
| L-03 | `libs/messaging`: Missing `BaseOutboxDispatcher` | **CRITICAL** | Yes — blocks outbox dispatch | L-02 |
| L-04 | `libs/messaging`: Missing `SchemaRegistryClient` wrapper | **HIGH** | Yes — blocks Avro serialization | None |
| L-05 | `libs/messaging`: Missing `AvroSerializer` / serializer builder | **HIGH** | Yes — blocks producer/dispatcher | L-04 |
| L-06 | `libs/messaging`: Missing `serialization_utils` (load_schema, helpers) | **HIGH** | Yes — blocks serialization | None |
| L-07 | `libs/messaging`: Missing `ValkeyClient` | **MEDIUM** | No — portfolio can defer cache | None |
| L-08 | `libs/messaging`: Missing consumer error hierarchy | **HIGH** | Yes — blocks consumer | None |
| L-09 | `libs/storage`: Missing `ObjectStorage` ABC | **LOW** | No — portfolio doesn't use S3 directly | None |
| L-10 | `libs/storage`: Missing `S3ObjectStorage` adapter | **LOW** | No | L-09 |
| L-11 | `libs/storage`: Missing storage exceptions | **LOW** | No | None |
| L-12 | `libs/storage`: Missing factory + health check | **LOW** | No | L-09, L-10 |
| L-13 | `libs/observability`: Missing `create_metrics()` / `ServiceMetrics` | **HIGH** | Yes — blocks `/metrics` | None |
| L-14 | `libs/observability`: Missing `configure_tracing()` | **MEDIUM** | No — can defer tracing | None |
| L-15 | `libs/observability`: Missing `add_prometheus_middleware()` | **HIGH** | Yes — blocks metrics | L-13 |
| L-16 | `libs/common`: Missing tests for `ids.py` and `types.py` | **LOW** | No | None |
| L-17 | `libs/contracts`: Missing `CanonicalQuote`, `CanonicalFundamentals` | **LOW** | No — portfolio doesn't use these | None |
| L-18 | `libs/contracts`: Missing `parsing.py` | **LOW** | No | None |

## 3.2 Portfolio Service Gaps

| ID | Gap | Severity | Blocking? | Depends On |
|----|-----|----------|-----------|------------|
| P-01 | Domain entities (6 entities) | **CRITICAL** | Yes — everything depends on domain | None |
| P-02 | Domain enums | **CRITICAL** | Yes — entities need enums | None |
| P-03 | Domain value objects (`Money`, `InstrumentKey`, `Quantity`) | **CRITICAL** | Yes — entities/use cases need VOs | None |
| P-04 | Domain events (9 event types) | **CRITICAL** | Yes — outbox needs events | P-01, P-02 |
| P-05 | Domain errors (15+ error classes) | **CRITICAL** | Yes — use cases/API need errors | None |
| P-06 | Application ports (8 repo ABCs + UoW) | **CRITICAL** | Yes — use cases need ports | P-01 |
| P-07 | Use cases: tenant (create, get) | **HIGH** | Yes | P-01, P-04, P-05, P-06 |
| P-08 | Use cases: user (create, get) | **HIGH** | Yes | P-07 (tenant check) |
| P-09 | Use cases: portfolio (create, get, list, archive, rename) | **HIGH** | Yes | P-07, P-08 |
| P-10 | Use cases: record_transaction | **HIGH** | Yes | P-09, P-03 |
| P-11 | Use cases: read_models (holdings, transactions) | **HIGH** | Yes | P-09 |
| P-12 | Use cases: instrument (get, get_by_id) | **MEDIUM** | Yes | P-06 |
| P-13 | DB models (8 SQLAlchemy models) | **CRITICAL** | Yes — repos need models | P-01, P-02 |
| P-14 | DB session factory | **CRITICAL** | Yes — UoW needs session | None |
| P-15 | DB repositories (8 concrete repos) | **CRITICAL** | Yes — use cases need repos | P-06, P-13 |
| P-16 | DB UnitOfWork (concrete) | **CRITICAL** | Yes — routes need UoW | P-14, P-15 |
| P-17 | Outbox repository | **HIGH** | Yes — events need outbox | P-13, L-03 |
| P-18 | Idempotency repository | **HIGH** | Yes — transactions need idemp | P-13 |
| P-19 | API schemas (Pydantic request/response) | **HIGH** | Yes — routes need schemas | P-01, P-02 |
| P-20 | API error handling (mapping + handlers) | **HIGH** | Yes — routes need error handling | P-05 |
| P-21 | API dependencies (DI) | **HIGH** | Yes — routes need DI | P-16 |
| P-22 | API routes: tenants | **HIGH** | Yes | P-07, P-19, P-20, P-21 |
| P-23 | API routes: users | **HIGH** | Yes | P-08, P-22 dependencies |
| P-24 | API routes: portfolios | **HIGH** | Yes | P-09, P-22 dependencies |
| P-25 | API routes: transactions | **HIGH** | Yes | P-10, P-24 dependencies |
| P-26 | API routes: holdings | **HIGH** | Yes | P-11, P-24 dependencies |
| P-27 | API routes: instruments | **MEDIUM** | Yes | P-12, P-21 |
| P-28 | Messaging: topic routing + mappers | **HIGH** | Yes — outbox dispatch needs these | P-04, L-06 |
| P-29 | Messaging: Avro schemas (.avsc files) | **HIGH** | Yes — serialization needs schemas | None |
| P-30 | Messaging: serialization + outbox mapper | **HIGH** | Yes | P-28, P-29, L-05 |
| P-31 | Messaging: OutboxDispatcher (concrete) | **HIGH** | Yes — events must publish | P-30, L-03 |
| P-32 | Messaging: dispatcher_main entry point | **MEDIUM** | Yes for deployment | P-31 |
| P-33 | Consumers: InstrumentEventConsumer | **HIGH** | Yes — instrument sync | L-01, L-08, P-15 |
| P-34 | Alembic: wire `target_metadata` + generate initial migration | **CRITICAL** | Yes — DB setup | P-13 |
| P-35 | Config/settings: complete settings | **HIGH** | Yes | None |
| P-36 | App lifespan: DB init + dispatcher + consumer | **HIGH** | Yes | P-14, P-31, P-33 |
| P-37 | `readyz` probe: DB + Kafka health checks | **MEDIUM** | Yes for production | P-14 |
| P-38 | Observability integration | **HIGH** | Yes — per AGENTS.md | L-13, L-15 |

## 3.3 Differences Between Legacy and Target Spec

| Aspect | Legacy | Target (docs) | Delta |
|--------|--------|---------------|-------|
| **API prefix** | `/api/` | `/api/v1/` | **New versioned prefix** |
| **PUT rename** | Not in legacy API | `PUT /api/v1/portfolios/{id}` | **New endpoint** |
| **DELETE archive** | Use case exists, no route | `DELETE /api/v1/portfolios/{id}` | **New route** |
| **GET users** | Not in legacy | `GET /api/v1/users/{id}` | **New endpoint** |
| **GET instruments list** | Not in legacy | `GET /api/v1/instruments` | **New endpoint** |
| **PortfolioCreated event** | Commented out in legacy | Required by target | **Must enable** |
| **instrument_ref.created event** | Not in legacy | In target docs | **New event** |
| **Metrics endpoint** | Not in legacy | `GET /metrics` required | **New (observability lib)** |
| **Numeric precision** | `(20,8)` in legacy | `(18,8)` in target docs | **Use target docs spec** |
| **Entity IDs** | UUIDv4 in legacy | UUIDv7 in target | **Upgrade to UUIDv7** |
| **Portfolio FK** | `user_id` + `created_by_user_id` | `owner_id` | **Simplify to single field** |
| **Portfolio unique** | `(tenant_id, user_id, name)` | `(owner_id, name)` | **Simplified** |
| **Outbox schema** | Binary key/payload | JSONB payload | **Target uses JSONB** |
| **Idempotency table** | Full table with response body | Simple `(event_id, processed_at)` | **Simplified consumer idemp + separate API idemp** |
| **Logging** | stdlib logging | `structlog` via `libs/observability` | **Migration** |

---

# 4. Atomic Task Backlog

> Each task is independent and execution-ready. Prerequisites are explicit.
> Effort: **S** = < 1h, **M** = 1–3h, **L** = 3–8h

---

## Phase 0 — Shared Library Prerequisites

### TASK-001: Implement `libs/messaging` consumer base + error hierarchy

| Field | Detail |
|-------|--------|
| **ID** | TASK-001 |
| **Title** | Implement BaseKafkaConsumer and consumer error hierarchy in libs/messaging |
| **Objective** | Port the `BaseKafkaConsumer`, `ConsumerConfig`, error classes (`RetryableError`, `FatalError` + subclasses), and `FailureInfo` from `platform_repo/libs/messaging/src/messaging/kafka/consumer/` into `worldview/libs/messaging/src/messaging/consumer/`. Adapt to use `structlog` from `libs/observability`. |
| **Search paths** | `platform_repo/libs/messaging/src/messaging/kafka/consumer/base.py`, `platform_repo/libs/messaging/src/messaging/kafka/consumer/errors.py`, `platform_repo/libs/messaging/src/messaging/kafka/consumer/__init__.py` |
| **Touched paths** | `worldview/libs/messaging/src/messaging/consumer/__init__.py`, `worldview/libs/messaging/src/messaging/consumer/base.py`, `worldview/libs/messaging/src/messaging/consumer/errors.py` |
| **Prerequisites** | None |
| **Implementation steps** | 1. Create `consumer/` package under `libs/messaging/src/messaging/`. 2. Copy `errors.py` — adapt import paths (no changes needed to hierarchy). 3. Copy `base.py` — replace `logging` with `from observability import get_logger`, replace `logging.getLogger` with `get_logger()`. 4. Update `ConsumerConfig` to use `pydantic-settings` style if needed (legacy uses plain dataclass — keep dataclass). 5. Keep all abstract methods unchanged. 6. Keep Avro deserialization via Schema Registry. 7. Update `libs/messaging/src/messaging/__init__.py` to export consumer classes. 8. Format with ruff. |
| **Tests required** | **Unit**: Test `ConsumerConfig` defaults, error hierarchy isinstance checks, error string formatting. Create `worldview/libs/messaging/tests/test_consumer_errors.py`. |
| **Documentation updates** | Update `docs/libs/messaging.md` — mark consumer section as implemented. |
| **DoD** | `BaseKafkaConsumer` importable from `messaging.consumer`, all abstract methods match legacy signatures, error hierarchy complete, unit tests pass, ruff + mypy clean. |
| **Risks** | Confluent Kafka Python is a C extension — ensure it's in `pyproject.toml` deps. |
| **Rollback** | Delete `consumer/` directory. |
| **Effort** | **L** |

---

### TASK-002: Implement `libs/messaging` schema registry + serializer

| Field | Detail |
|-------|--------|
| **ID** | TASK-002 |
| **Title** | Implement SchemaRegistryClient wrapper and Avro serializer builder |
| **Objective** | Port `schema_registry.py`, `serializer.py`, and `serialization_utils.py` from platform_repo into worldview. |
| **Search paths** | `platform_repo/libs/messaging/src/messaging/kafka/schema_registry.py`, `platform_repo/libs/messaging/src/messaging/kafka/serializer.py`, `platform_repo/libs/messaging/src/messaging/kafka/serialization_utils.py` |
| **Touched paths** | `worldview/libs/messaging/src/messaging/schema_registry.py`, `worldview/libs/messaging/src/messaging/serializer.py`, `worldview/libs/messaging/src/messaging/serialization_utils.py` |
| **Prerequisites** | None |
| **Implementation steps** | 1. Copy `schema_registry.py` — `SchemaRegistryConfig` + `build_schema_registry_client()`. 2. Copy `serializer.py` — `AvroDictable` protocol (already exists in `schemas.py` — reconcile: keep one definition, re-export from both), `AvroSerializerConfig`, `build_avro_serializer()`, `topic_event_type_subject_name_strategy()`. 3. Copy `serialization_utils.py` — `load_schema()` (already exists in `schemas.py` — reconcile), `serializer_for_schema()`, `iso_datetime()`, `decimal_to_str()`. 4. Ensure `AvroDictable` has a single canonical definition in `schemas.py` with re-exports. 5. Format with ruff. |
| **Tests required** | **Unit**: `test_serialization_utils.py` — test `iso_datetime`, `decimal_to_str`, `load_schema` with fixture `.avsc`. |
| **Documentation updates** | Update `docs/libs/messaging.md` — mark serializer section as implemented. |
| **DoD** | `SchemaRegistryConfig`, `build_schema_registry_client`, `build_avro_serializer`, `topic_event_type_subject_name_strategy`, `serializer_for_schema`, `iso_datetime`, `decimal_to_str` all importable. Tests pass. |
| **Risks** | `AvroDictable` already defined in `schemas.py` — must reconcile to avoid duplication. |
| **Rollback** | Delete the 3 new files. |
| **Effort** | **M** |

---

### TASK-003: Implement `libs/messaging` producer

| Field | Detail |
|-------|--------|
| **ID** | TASK-003 |
| **Title** | Implement Kafka producer config and factory in libs/messaging |
| **Objective** | Port `KafkaProducerConfig`, `build_serializing_producer`, `OutboxKafkaValue`, `KafkaEventValueSerializer`, `OutboxEventValueSerializer` from platform_repo. |
| **Search paths** | `platform_repo/libs/messaging/src/messaging/kafka/producer.py` |
| **Touched paths** | `worldview/libs/messaging/src/messaging/producer.py` |
| **Prerequisites** | TASK-002 (serializer) |
| **Implementation steps** | 1. Copy `producer.py` — update imports to worldview paths. 2. Adapt `KafkaProducerConfig` to use same pattern as legacy (plain dataclass). 3. Keep `acks=all`, `enable_idempotence=True`. 4. Ensure `OutboxKafkaValue` dataclass is available. 5. Ensure `OutboxEventValueSerializer` wraps `AvroSerializer` correctly. 6. Format with ruff. |
| **Tests required** | **Unit**: `test_producer.py` — test `KafkaProducerConfig` defaults, `OutboxKafkaValue` construction. |
| **Documentation updates** | Update `docs/libs/messaging.md` — mark producer section as implemented. |
| **DoD** | `KafkaProducerConfig`, `build_serializing_producer`, `OutboxKafkaValue` importable. Tests pass. |
| **Risks** | Confluent Kafka C library dependency. |
| **Rollback** | Delete `producer.py`. |
| **Effort** | **M** |

---

### TASK-004: Implement `libs/messaging` outbox dispatcher base

| Field | Detail |
|-------|--------|
| **ID** | TASK-004 |
| **Title** | Implement BaseOutboxDispatcher in libs/messaging |
| **Objective** | Port the lease-based outbox dispatcher from platform_repo. Hybrid model: immediate notify + background poll. |
| **Search paths** | `platform_repo/libs/messaging/src/messaging/kafka/dispatcher/base.py`, `platform_repo/libs/messaging/src/messaging/kafka/dispatcher/__init__.py` |
| **Touched paths** | `worldview/libs/messaging/src/messaging/dispatcher/__init__.py`, `worldview/libs/messaging/src/messaging/dispatcher/base.py` |
| **Prerequisites** | TASK-003 (producer) |
| **Implementation steps** | 1. Create `dispatcher/` package. 2. Copy `base.py` — replace `logging` with `get_logger()` from observability. 3. Keep all abstract methods: `_build_producer()`, `_produce_record()`. 4. Keep protocols: `OutboxRecordProtocol`, `OutboxRepositoryProtocol`, `UnitOfWorkWithOutboxProtocol`. 5. Keep `DispatcherConfig` dataclass. 6. Keep `run_dispatcher()` entry point. 7. Keep backpressure, delivery ack, dead-letter logic. 8. Format with ruff. |
| **Tests required** | **Unit**: `test_dispatcher_config.py` — config defaults, worker ID generation. |
| **Documentation updates** | Update `docs/libs/messaging.md` — mark outbox dispatcher section as implemented. |
| **DoD** | `BaseOutboxDispatcher`, `DispatcherConfig`, `run_dispatcher` importable. Protocols defined. Tests pass. |
| **Risks** | Large file (~536 lines) — careful copy to maintain all edge cases. |
| **Rollback** | Delete `dispatcher/` directory. |
| **Effort** | **L** |

---

### TASK-005: Implement `libs/messaging` Valkey client

| Field | Detail |
|-------|--------|
| **ID** | TASK-005 |
| **Title** | Implement ValkeyClient async Redis wrapper in libs/messaging |
| **Objective** | Port `ValkeyClient`, `ValkeyConfig`, `create_valkey_client` from platform_repo. |
| **Search paths** | `platform_repo/libs/messaging/src/messaging/valkey/client.py` |
| **Touched paths** | `worldview/libs/messaging/src/messaging/valkey/__init__.py`, `worldview/libs/messaging/src/messaging/valkey/client.py` |
| **Prerequisites** | None |
| **Implementation steps** | 1. Create `valkey/` package. 2. Copy `client.py` — replace logging with `get_logger()`. 3. Keep connection pooling, JSON get/set, TTL, batch, hash operations. 4. Format with ruff. |
| **Tests required** | **Unit**: `test_valkey_config.py` — config construction, URL parsing. |
| **Documentation updates** | Update `docs/libs/messaging.md` — mark Valkey section as implemented. |
| **DoD** | `ValkeyClient`, `ValkeyConfig`, `create_valkey_client` importable. Tests pass. |
| **Risks** | `redis.asyncio` dependency. |
| **Rollback** | Delete `valkey/` directory. |
| **Effort** | **M** |

---

### TASK-006: Implement `libs/observability` metrics module

| Field | Detail |
|-------|--------|
| **ID** | TASK-006 |
| **Title** | Implement Prometheus metrics + FastAPI middleware in libs/observability |
| **Objective** | Create `create_metrics()`, `ServiceMetrics`, and `add_prometheus_middleware()` per `docs/libs/observability.md` spec. |
| **Search paths** | `worldview/docs/libs/observability.md` (spec), `platform_repo/` (no direct equivalent — build fresh) |
| **Touched paths** | `worldview/libs/observability/src/observability/metrics.py`, `worldview/libs/observability/src/observability/__init__.py` |
| **Prerequisites** | None |
| **Implementation steps** | 1. Create `metrics.py`. 2. Define `ServiceMetrics` frozen dataclass with: `requests_total` (Counter), `request_duration_seconds` (Histogram), `kafka_messages_consumed_total` (Counter), `kafka_messages_produced_total` (Counter), `outbox_dispatched_total` (Counter), `outbox_dispatch_errors_total` (Counter). 3. `create_metrics(service_name)` factory. 4. `add_prometheus_middleware(app, metrics)` — Starlette `BaseHTTPMiddleware` that records request count + duration. 5. Add `/metrics` route handler via `prometheus_client.generate_latest`. 6. Update `__init__.py` to export new symbols. 7. Format with ruff. |
| **Tests required** | **Unit**: `test_metrics.py` — metrics creation, label validation, middleware records request count on mock app. |
| **Documentation updates** | Update `docs/libs/observability.md` — mark metrics section as implemented. |
| **DoD** | `create_metrics`, `ServiceMetrics`, `add_prometheus_middleware` importable. Middleware records HTTP metrics. `/metrics` endpoint returns Prometheus text. Tests pass. |
| **Risks** | `prometheus-client` must be added to `pyproject.toml`. |
| **Rollback** | Delete `metrics.py`, revert `__init__.py`. |
| **Effort** | **M** |

---

### TASK-007: Implement `libs/observability` tracing module

| Field | Detail |
|-------|--------|
| **ID** | TASK-007 |
| **Title** | Implement OpenTelemetry tracing setup in libs/observability |
| **Objective** | Create `configure_tracing()`, `get_tracer()`, `add_otel_middleware()` per `docs/libs/observability.md` spec. |
| **Search paths** | `worldview/docs/libs/observability.md` |
| **Touched paths** | `worldview/libs/observability/src/observability/tracing.py`, `worldview/libs/observability/src/observability/__init__.py` |
| **Prerequisites** | None |
| **Implementation steps** | 1. Create `tracing.py`. 2. `configure_tracing(service_name, otlp_endpoint=None)` — sets up `TracerProvider`, OTLP exporter if endpoint provided, no-op if not. 3. `get_tracer(name)` — returns `opentelemetry.trace.get_tracer(name)`. 4. `add_otel_middleware(app)` — integrates `FastAPIInstrumentor`. 5. Inject trace_id/span_id into structlog context. 6. Export from `__init__.py`. 7. Format with ruff. |
| **Tests required** | **Unit**: `test_tracing.py` — configure_tracing with no endpoint (no-op mode), get_tracer returns valid tracer. |
| **Documentation updates** | Update `docs/libs/observability.md` — mark tracing section as implemented. |
| **DoD** | `configure_tracing`, `get_tracer`, `add_otel_middleware` importable. Tests pass. |
| **Risks** | OTel SDK has many sub-packages — ensure correct ones in pyproject.toml. |
| **Rollback** | Delete `tracing.py`, revert `__init__.py`. |
| **Effort** | **M** |

---

### TASK-008: Add missing tests for `libs/common` ids + types

| Field | Detail |
|-------|--------|
| **ID** | TASK-008 |
| **Title** | Add unit tests for common.ids and common.types |
| **Objective** | Cover `new_uuid()`, `new_uuid_str()`, `new_ulid()` and all `NewType` aliases. |
| **Search paths** | `worldview/libs/common/src/common/ids.py`, `worldview/libs/common/src/common/types.py` |
| **Touched paths** | `worldview/libs/common/tests/test_ids.py`, `worldview/libs/common/tests/test_types.py` |
| **Prerequisites** | None |
| **Implementation steps** | 1. Create `test_ids.py` — test `new_uuid` returns UUID, `new_uuid_str` returns string, `new_ulid` returns string and is time-sortable (sequential calls are ordered). 2. Create `test_types.py` — test each `NewType` can wrap its base type and is accepted by type checkers. 3. Format with ruff. |
| **Tests required** | Self — this IS the testing task. |
| **Documentation updates** | None. |
| **DoD** | All tests pass, coverage for ids.py and types.py at 100%. |
| **Risks** | None — trivial. |
| **Rollback** | Delete test files. |
| **Effort** | **S** |

---

## Phase 1 — Portfolio Domain Layer

### TASK-009: Implement domain enums

| Field | Detail |
|-------|--------|
| **ID** | TASK-009 |
| **Title** | Implement Portfolio domain enums |
| **Objective** | Create all enum types needed by the Portfolio domain. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/model/domain/enums.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/domain/enums.py` |
| **Prerequisites** | None |
| **Implementation steps** | 1. Create `domain/` package with `__init__.py`. 2. Create `enums.py` with: `TenantStatus`, `UserStatus`, `PortfolioStatus`, `TransactionType`, `TransactionDirection`, `OutboxStatus`, `IdempotencyState`. 3. Match values from legacy. 4. Format with ruff. |
| **Tests required** | **Unit**: Enum membership, string conversion — include in TASK-015. |
| **Documentation updates** | None (covered by portfolio.md). |
| **DoD** | All 7 enums importable from `portfolio.domain.enums`. |
| **Risks** | None. |
| **Rollback** | Delete file. |
| **Effort** | **S** |

---

### TASK-010: Implement domain value objects

| Field | Detail |
|-------|--------|
| **ID** | TASK-010 |
| **Title** | Implement Money, InstrumentKey, Quantity value objects |
| **Objective** | Port immutable value objects with arithmetic operations. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/model/domain/value_objects.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/domain/value_objects.py` |
| **Prerequisites** | None |
| **Implementation steps** | 1. Copy `value_objects.py`. 2. `Money`: frozen dataclass with `amount: Decimal`, `currency: str`, arithmetic ops, `zero()`, `from_string()`. 3. `InstrumentKey`: `symbol: str`, `exchange: str`, `full_symbol()`. 4. `Quantity`: `value: Decimal`, arithmetic ops, sign checks. 5. Format with ruff. |
| **Tests required** | **Unit**: Covered in TASK-015. Test arithmetic, zero, negation, currency mismatch raises. |
| **Documentation updates** | None. |
| **DoD** | `Money`, `InstrumentKey`, `Quantity` importable and frozen. |
| **Risks** | Decimal precision must match DB precision `(18,8)`. |
| **Rollback** | Delete file. |
| **Effort** | **M** |

---

### TASK-011: Implement domain entities

| Field | Detail |
|-------|--------|
| **ID** | TASK-011 |
| **Title** | Implement Tenant, User, Portfolio, Transaction, Holding, InstrumentRef entities |
| **Objective** | Port all 6 domain entities. Use UUIDv7 (via `common.ids`) instead of legacy UUIDv4. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/model/domain/entities/` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/domain/entities/__init__.py`, `tenant.py`, `user.py`, `portfolio.py`, `transaction.py`, `holding.py`, `instrument.py` |
| **Prerequisites** | TASK-009 (enums), TASK-010 (value objects) |
| **Implementation steps** | 1. Create `entities/` package. 2. Port each entity from legacy — adapt: replace `user_id` + `created_by_user_id` with `owner_id` in Portfolio (per target docs), use `Decimal` directly for quantities/prices. 3. Keep method signatures: `Tenant.is_active()`, `Portfolio.rename()`, `Portfolio.archive()`, `Holding.apply_delta()`, `Transaction.gross_amount()`, `Transaction.net_amount()`. 4. `InstrumentRef` — keep `source_event_id` for idempotent consumer updates. 5. Use frozen dataclasses for immutable entities, mutable for Portfolio and Holding. 6. Format with ruff. |
| **Tests required** | **Unit**: Covered in TASK-015. |
| **Documentation updates** | None. |
| **DoD** | All 6 entities importable, methods functional, type-checked. |
| **Risks** | `owner_id` change vs legacy `user_id` + `created_by_user_id` — ensure all downstream references updated. |
| **Rollback** | Delete `entities/` directory. |
| **Effort** | **M** |

---

### TASK-012: Implement domain events

| Field | Detail |
|-------|--------|
| **ID** | TASK-012 |
| **Title** | Implement DomainEvent base + 9 concrete domain events |
| **Objective** | Port domain event classes. Add `InstrumentRefCreated` (new — per target spec). Enable `PortfolioCreated` (was commented out in legacy). |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/model/domain/events.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/domain/events.py` |
| **Prerequisites** | TASK-009 (enums) |
| **Implementation steps** | 1. Copy `events.py`. 2. Keep `DomainEvent` base with `EVENT_TYPE`, `AGGREGATE_TYPE`, `schema_version`, `event_id`, `occurred_at`, `correlation_id`, `causation_id`, `tenant_id`, abstract `aggregate_id`. 3. Port all 9 events. 4. Add `InstrumentRefCreated` with fields: `instrument_id`, `symbol`, `exchange`, `name`, `asset_class`, `currency`. 5. Use UUIDv7 for `event_id` default via `common.ids.new_uuid`. 6. Format with ruff. |
| **Tests required** | **Unit**: Covered in TASK-015 — event creation, aggregate_id correctness, frozen. |
| **Documentation updates** | None. |
| **DoD** | 10 event types importable (9 legacy + 1 new). |
| **Risks** | `InstrumentRefCreated` is new — needs Avro schema in TASK-029. |
| **Rollback** | Delete file. |
| **Effort** | **M** |

---

### TASK-013: Implement domain errors

| Field | Detail |
|-------|--------|
| **ID** | TASK-013 |
| **Title** | Implement domain error hierarchy |
| **Objective** | Port the complete error hierarchy from legacy. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/model/domain/errors.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/domain/errors.py` |
| **Prerequisites** | None |
| **Implementation steps** | 1. Copy `errors.py`. 2. Keep full hierarchy: `DomainError` → `EntityNotFoundError`, `EntityAlreadyExistsError`, `ValidationError`, `AuthorizationError`, `BusinessRuleViolationError`, `ConcurrencyError`, `IdempotencyKeyConflictError` + all subclasses. 3. Keep `error_code`, `message`, `details`, `tenant_id`, `user_id` on base. 4. Format with ruff. |
| **Tests required** | **Unit**: Covered in TASK-015 — isinstance checks, error_code values. |
| **Documentation updates** | None. |
| **DoD** | 15+ error classes importable with correct hierarchy. |
| **Risks** | None. |
| **Rollback** | Delete file. |
| **Effort** | **S** |

---

### TASK-014: Create domain package structure + `__init__.py` exports

| Field | Detail |
|-------|--------|
| **ID** | TASK-014 |
| **Title** | Wire domain package with proper exports |
| **Objective** | Create `__init__.py` files for `domain/`, `domain/entities/` with clean public API. |
| **Search paths** | N/A |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/domain/__init__.py`, `worldview/services/portfolio/src/portfolio/domain/entities/__init__.py` |
| **Prerequisites** | TASK-009 through TASK-013 |
| **Implementation steps** | 1. `domain/__init__.py` — docstring only (users import from submodules). 2. `domain/entities/__init__.py` — re-export all 6 entities. 3. Verify all imports resolve. |
| **Tests required** | **Unit**: Import smoke test in TASK-015. |
| **Documentation updates** | None. |
| **DoD** | `from portfolio.domain.entities import Tenant, User, Portfolio, Transaction, Holding, InstrumentRef` works. |
| **Risks** | None. |
| **Rollback** | Trivial. |
| **Effort** | **S** |

---

### TASK-015: Unit tests for domain layer

| Field | Detail |
|-------|--------|
| **ID** | TASK-015 |
| **Title** | Write comprehensive unit tests for all domain layer components |
| **Objective** | Cover entities, value objects, enums, events, errors with unit tests. |
| **Search paths** | `platform_repo/apps/backend-portfolio/tests/unit/test_domain_entities.py` |
| **Touched paths** | `worldview/services/portfolio/tests/unit/__init__.py`, `worldview/services/portfolio/tests/unit/test_domain_entities.py`, `worldview/services/portfolio/tests/unit/test_value_objects.py`, `worldview/services/portfolio/tests/unit/test_domain_events.py`, `worldview/services/portfolio/tests/unit/test_domain_errors.py` |
| **Prerequisites** | TASK-009 through TASK-014 |
| **Implementation steps** | 1. Port `test_domain_entities.py` from legacy — adapt to new field names (owner_id). 2. Add `test_value_objects.py` — Money arithmetic, InstrumentKey, Quantity. 3. Add `test_domain_events.py` — creation, aggregate_id, schema_version, frozen. 4. Add `test_domain_errors.py` — hierarchy isinstance, error codes. 5. Run `make test`. |
| **Tests required** | Self — this IS the testing task. |
| **Documentation updates** | None. |
| **DoD** | All tests pass. Coverage for domain/ > 90%. |
| **Risks** | None. |
| **Rollback** | Delete test files. |
| **Effort** | **M** |

---

## Phase 2 — Application Layer

### TASK-016: Implement application ports (repository ABCs + UoW)

| Field | Detail |
|-------|--------|
| **ID** | TASK-016 |
| **Title** | Implement repository port interfaces and UnitOfWork ABC |
| **Objective** | Define abstract contracts for all 8 repositories + UoW. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/application/ports/repositories.py`, `platform_repo/apps/backend-portfolio/src/portfolio/application/ports/unit_of_work.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/application/__init__.py`, `worldview/services/portfolio/src/portfolio/application/ports/__init__.py`, `worldview/services/portfolio/src/portfolio/application/ports/repositories.py`, `worldview/services/portfolio/src/portfolio/application/ports/unit_of_work.py` |
| **Prerequisites** | TASK-014 (domain layer complete) |
| **Implementation steps** | 1. Create `application/` and `application/ports/` packages. 2. Port `repositories.py` — 8 repository ABCs (`TenantRepository`, `UserRepository`, `PortfolioRepository`, `InstrumentRepository`, `TransactionRepository`, `HoldingRepository`, `OutboxRepository`, `IdempotencyRepository`). 3. Port DTOs: `OutboxRecord`, `IdempotencyRecord`. 4. Port `unit_of_work.py` — `UnitOfWork` ABC with all 8 repo properties + commit/rollback + context manager. 5. Adapt to target schema (owner_id, simplified idempotency). 6. Format with ruff. |
| **Tests required** | None directly — ABCs are tested via implementations. |
| **Documentation updates** | None. |
| **DoD** | All 8 ABCs + UoW importable with proper type hints. mypy clean. |
| **Risks** | Must align with domain entity signatures. |
| **Rollback** | Delete `application/` directory. |
| **Effort** | **M** |

---

### TASK-017: Implement use cases — tenant

| Field | Detail |
|-------|--------|
| **ID** | TASK-017 |
| **Title** | Implement CreateTenantUseCase and GetTenantUseCase |
| **Objective** | Port tenant use cases with outbox event publishing. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/application/use_cases/tenant.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/application/use_cases/__init__.py`, `worldview/services/portfolio/src/portfolio/application/use_cases/tenant.py` |
| **Prerequisites** | TASK-016 (ports) |
| **Implementation steps** | 1. Create `use_cases/` package. 2. Port `CreateTenantCommand` + `CreateTenantUseCase` — creates tenant, emits `TenantCreated` via outbox. 3. Port `GetTenantUseCase` — simple get. 4. Use `structlog` via `get_logger()`. 5. Use `new_uuid()` for tenant_id instead of `uuid4()`. 6. Format with ruff. |
| **Tests required** | **Unit**: `test_use_cases_tenant.py` — happy path with fake UoW/repos, verify outbox event emitted. |
| **Documentation updates** | None. |
| **DoD** | Both use cases work with UoW port. Outbox event emitted. Tests pass. |
| **Risks** | None. |
| **Rollback** | Delete file. |
| **Effort** | **S** |

---

### TASK-018: Implement use cases — user

| Field | Detail |
|-------|--------|
| **ID** | TASK-018 |
| **Title** | Implement CreateUserUseCase and GetUserUseCase |
| **Objective** | Port user use cases with tenant validation and outbox. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/application/use_cases/user.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/application/use_cases/user.py` |
| **Prerequisites** | TASK-017 (tenant use case pattern) |
| **Implementation steps** | 1. Port `CreateUserCommand` + `CreateUserUseCase` — validate tenant active, email unique, emit `UserCreated` outbox event. 2. Add `GetUserUseCase`. 3. Use `get_logger()`. 4. Format with ruff. |
| **Tests required** | **Unit**: `test_use_cases_user.py` — happy path, inactive tenant raises, duplicate email raises. |
| **Documentation updates** | None. |
| **DoD** | Use cases work. Validation correct. Tests pass. |
| **Risks** | None. |
| **Rollback** | Delete file. |
| **Effort** | **S** |

---

### TASK-019: Implement use cases — portfolio operations

| Field | Detail |
|-------|--------|
| **ID** | TASK-019 |
| **Title** | Implement CreatePortfolio, GetPortfolio, ListPortfolios, RenamePortfolio, ArchivePortfolio |
| **Objective** | Port all portfolio CRUD use cases. Enable `PortfolioCreated` event (was commented out in legacy). Add `RenamePortfolio` use case (new). |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/application/use_cases/create_portfolio.py`, `platform_repo/apps/backend-portfolio/src/portfolio/application/use_cases/portfolio_ops.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/application/use_cases/create_portfolio.py`, `worldview/services/portfolio/src/portfolio/application/use_cases/portfolio_ops.py` |
| **Prerequisites** | TASK-018 (user use case) |
| **Implementation steps** | 1. Port `CreatePortfolioCommand` + `CreatePortfolioUseCase` — validate tenant + user active, create portfolio with `owner_id`, emit `PortfolioCreated` outbox event (ENABLE — was commented out). 2. Port `GetPortfolioUseCase` with ownership check. 3. Port `ListPortfoliosUseCase`. 4. Port `ArchivePortfolioUseCase` with `PortfolioArchived` event. 5. Add `RenamePortfolioCommand` + `RenamePortfolioUseCase` — ownership check, rename, emit `PortfolioRenamed` event. 6. Format with ruff. |
| **Tests required** | **Unit**: `test_use_cases_portfolio.py` — create happy path, archive happy path, rename happy path, ownership errors, inactive tenant/user errors. |
| **Documentation updates** | None. |
| **DoD** | All 5 portfolio use cases work. `PortfolioCreated` event emitted. Tests pass. |
| **Risks** | `RenamePortfolio` is new — no legacy reference. Design from domain entity `rename()` method. |
| **Rollback** | Delete files. |
| **Effort** | **M** |

---

### TASK-020: Implement use cases — record transaction

| Field | Detail |
|-------|--------|
| **ID** | TASK-020 |
| **Title** | Implement RecordTransactionUseCase with holding update + idempotency |
| **Objective** | Port the most complex use case — transaction recording with holding recalculation, idempotency, and dual outbox events. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/application/use_cases/record_transaction.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/application/use_cases/record_transaction.py` |
| **Prerequisites** | TASK-019 (portfolio ops) |
| **Implementation steps** | 1. Port `RecordTransactionCommand` — adapt field names per target schema. 2. Port `RecordTransactionUseCase` — full flow: idempotency check → portfolio/user validation → currency match → instrument resolution → holding update via `apply_delta()` → emit `TransactionRecorded` + `HoldingChanged` outbox events → idempotency result storage. 3. Maintain transactional atomicity (single UoW commit). 4. Use `get_logger()` with correlation_id. 5. Format with ruff. |
| **Tests required** | **Unit**: `test_use_cases_transaction.py` — happy path (BUY), happy path (SELL), insufficient holdings, currency mismatch, idempotency replay, instrument not found. |
| **Documentation updates** | None. |
| **DoD** | RecordTransactionUseCase emits both events in single transaction. Idempotency works. Tests pass. |
| **Risks** | Most complex use case — holding calculation must be exact. Verify Decimal precision. |
| **Rollback** | Delete file. |
| **Effort** | **L** |

---

### TASK-021: Implement use cases — read models + instrument

| Field | Detail |
|-------|--------|
| **ID** | TASK-021 |
| **Title** | Implement GetHoldings, ListTransactions, GetInstrument, GetInstrumentById |
| **Objective** | Port read-only query use cases. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/application/use_cases/read_models.py`, `platform_repo/apps/backend-portfolio/src/portfolio/application/use_cases/instrument.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/application/use_cases/read_models.py`, `worldview/services/portfolio/src/portfolio/application/use_cases/instrument.py` |
| **Prerequisites** | TASK-016 (ports) |
| **Implementation steps** | 1. Port `GetHoldingsUseCase` — ownership check, return holdings. 2. Port `ListTransactionsUseCase` — ownership check, return transactions. 3. Port `GetInstrumentUseCase` (by symbol+exchange). 4. Port `GetInstrumentByIdUseCase`. 5. Deprecate `UpsertInstrumentUseCase` (instruments come from Kafka only). 6. Format with ruff. |
| **Tests required** | **Unit**: `test_use_cases_read_models.py` — ownership validation, empty results. |
| **Documentation updates** | None. |
| **DoD** | 4 read use cases work. Tests pass. |
| **Risks** | None. |
| **Rollback** | Delete files. |
| **Effort** | **S** |

---

## Phase 3 — Infrastructure Layer

### TASK-022: Implement DB models (SQLAlchemy ORM)

| Field | Detail |
|-------|--------|
| **ID** | TASK-022 |
| **Title** | Implement 8 SQLAlchemy ORM models for portfolio_db |
| **Objective** | Create ORM models matching the target DB schema from `docs/services/portfolio.md`. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/infrastructure/db/models/`, `worldview/docs/services/portfolio.md` (SQL schema section) |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/infrastructure/__init__.py`, `worldview/services/portfolio/src/portfolio/infrastructure/db/__init__.py`, `worldview/services/portfolio/src/portfolio/infrastructure/db/models/__init__.py`, `worldview/services/portfolio/src/portfolio/infrastructure/db/models/tenant.py`, `user.py`, `portfolio.py`, `transaction.py`, `holding.py`, `instrument.py`, `outbox.py`, `idempotency.py` |
| **Prerequisites** | TASK-009 (enums for status columns) |
| **Implementation steps** | 1. Create `infrastructure/db/models/` package with `Base = declarative_base()`. 2. Create models per target schema — key differences from legacy: use `owner_id` instead of `user_id + created_by_user_id`, numeric precision `(18,8)`, outbox payload is `JSONB` (not LargeBinary), idempotency table simplified to `(event_id PK, processed_at)`. 3. Add proper indexes per target spec. 4. Add `created_at`/`updated_at` server defaults. 5. Format with ruff. |
| **Tests required** | None directly — tested via repository integration tests. |
| **Documentation updates** | None. |
| **DoD** | All 8 models importable, `Base.metadata` contains all tables, mypy clean. |
| **Risks** | Schema differences from legacy must be carefully applied. |
| **Rollback** | Delete `models/` directory. |
| **Effort** | **M** |

---

### TASK-023: Implement DB session factory

| Field | Detail |
|-------|--------|
| **ID** | TASK-023 |
| **Title** | Implement async session factory |
| **Objective** | Create `create_session_factory()` returning async engine + sessionmaker. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/infrastructure/db/session.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/infrastructure/db/session.py` |
| **Prerequisites** | None |
| **Implementation steps** | 1. Port `session.py` — `create_async_engine(url)`, `async_sessionmaker(bind=engine)`. 2. Return both engine and sessionmaker for lifecycle management. 3. Format with ruff. |
| **Tests required** | None directly — tested via integration. |
| **Documentation updates** | None. |
| **DoD** | `create_session_factory(url)` returns engine + sessionmaker. |
| **Risks** | None. |
| **Rollback** | Delete file. |
| **Effort** | **S** |

---

### TASK-024: Implement DB repositories (8 concrete)

| Field | Detail |
|-------|--------|
| **ID** | TASK-024 |
| **Title** | Implement all 8 SQLAlchemy repository implementations |
| **Objective** | Port concrete repositories with model⟷domain mappers. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/infrastructure/db/repositories/` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/infrastructure/db/repositories/__init__.py`, `tenant.py`, `user.py`, `portfolio.py`, `transaction.py`, `holding.py`, `instrument.py`, `outbox.py`, `idempotency.py` |
| **Prerequisites** | TASK-016 (ports), TASK-022 (models) |
| **Implementation steps** | 1. Create `repositories/` package. 2. Port each repo — adapt domain⟷model mappers to new field names (owner_id). 3. `HoldingRepository.upsert_many` — keep `uuid5` deterministic PK. 4. `InstrumentRepository.upsert` — keep ON CONFLICT DO UPDATE. 5. `OutboxRepository` — adapt to JSONB payload (not LargeBinary). Use event mappers for serialization. Keep claim_batch with `SELECT FOR UPDATE SKIP LOCKED`. 6. `IdempotencyRepository` — simplify to `exists(event_id)` + `record(event_id)` for consumer idempotency. Keep full API idempotency as separate concern. 7. All queries must filter by `tenant_id`. 8. Format with ruff. |
| **Tests required** | **Integration**: Covered in TASK-035 (integration tests). |
| **Documentation updates** | None. |
| **DoD** | All 8 repos implement their port ABCs. mypy clean. |
| **Risks** | JSONB outbox payload is a change from legacy (LargeBinary) — ensure outbox mapper handles this. |
| **Rollback** | Delete `repositories/` directory. |
| **Effort** | **L** |

---

### TASK-025: Implement SqlAlchemyUnitOfWork

| Field | Detail |
|-------|--------|
| **ID** | TASK-025 |
| **Title** | Implement concrete UnitOfWork with outbox dispatch hook |
| **Objective** | Port `SqlAlchemyUnitOfWork` — wires all 8 repos, tracks outbox events, calls dispatcher on commit. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/infrastructure/db/unit_of_work.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/infrastructure/db/unit_of_work.py` |
| **Prerequisites** | TASK-023 (session), TASK-024 (repos) |
| **Implementation steps** | 1. Port `SqlAlchemyUnitOfWork` — async context manager, creates all 8 repos in `__aenter__`. 2. `on_commit` callback for outbox notification. 3. `commit()` calls `session.commit()` then `on_commit()` if outbox events added. 4. `rollback()` calls `session.rollback()`. 5. Format with ruff. |
| **Tests required** | **Unit**: `test_unit_of_work.py` — commit calls on_commit when outbox has events, rollback doesn't. |
| **Documentation updates** | None. |
| **DoD** | `SqlAlchemyUnitOfWork` implements `UnitOfWork` port. on_commit hook works. Tests pass. |
| **Risks** | None. |
| **Rollback** | Delete file. |
| **Effort** | **M** |

---

### TASK-026: Implement complete settings

| Field | Detail |
|-------|--------|
| **ID** | TASK-026 |
| **Title** | Complete Portfolio settings with all config vars |
| **Objective** | Extend the existing `config.py` scaffold to include all settings needed: DB, Kafka, Schema Registry, dispatcher tuning, consumer group, topic names. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/infrastructure/config/settings.py`, `worldview/services/portfolio/src/portfolio/config.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/config.py`, `worldview/services/portfolio/configs/dev.local.env.example`, `worldview/services/portfolio/configs/prod.env.example` |
| **Prerequisites** | None |
| **Implementation steps** | 1. Extend `Settings` class — add: `service_name`, `kafka_schema_registry_basic_auth`, `kafka_auto_register_schemas`, `dispatcher_immediate_batch_size`, `dispatcher_poll_interval`, `dispatcher_lease_seconds`, `dispatcher_max_attempts`, `dispatcher_backoff_base_seconds`, `topic_instrument_created`, `topic_instrument_updated`, `consumer_group_instrument`, `log_level`, `log_format`. 2. Set sensible defaults matching legacy. 3. Update `dev.local.env.example` with all vars. 4. Update `prod.env.example`. 5. Format with ruff. |
| **Tests required** | **Unit**: `test_config.py` — defaults, env override. |
| **Documentation updates** | Env vars documented in example files. |
| **DoD** | All config vars from legacy + observability available. Example files complete. Tests pass. |
| **Risks** | None. |
| **Rollback** | Revert file. |
| **Effort** | **S** |

---

## Phase 4 — API Layer

### TASK-027: Implement API schemas (Pydantic request/response)

| Field | Detail |
|-------|--------|
| **ID** | TASK-027 |
| **Title** | Implement Pydantic request/response models |
| **Objective** | Create all API schemas per `docs/services/portfolio.md`. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/api/schemas.py`, `worldview/docs/services/portfolio.md` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/api/__init__.py`, `worldview/services/portfolio/src/portfolio/api/schemas.py` |
| **Prerequisites** | TASK-009 (enums) |
| **Implementation steps** | 1. Create `api/` package. 2. Create `schemas.py` with: `TenantCreateRequest/Response`, `UserCreateRequest/Response`, `PortfolioCreateRequest/Response`, `PortfolioRenameRequest`, `RecordTransactionRequest/Response`, `HoldingResponse`, `TransactionListItem`, `InstrumentResponse`, `ErrorResponse`. 3. Use target spec field names (`owner_user_id`, etc.). 4. Add Pydantic validators where needed (currency format, positive quantities). 5. Format with ruff. |
| **Tests required** | **Unit**: `test_api_schemas.py` — validation (invalid currency, negative quantity, missing fields). |
| **Documentation updates** | None. |
| **DoD** | All schemas importable. Validation works. Tests pass. |
| **Risks** | None. |
| **Rollback** | Delete file. |
| **Effort** | **M** |

---

### TASK-028: Implement API error handling

| Field | Detail |
|-------|--------|
| **ID** | TASK-028 |
| **Title** | Implement exception handlers + error mapping + error schema |
| **Objective** | Port error handling: `DomainError → HTTP status` mapping, structured error responses. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/api/error_mapping.py`, `exception_handlers.py`, `error_schema.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/api/error_mapping.py`, `worldview/services/portfolio/src/portfolio/api/exception_handlers.py` |
| **Prerequisites** | TASK-013 (domain errors), TASK-027 (ErrorResponse schema) |
| **Implementation steps** | 1. Port `error_mapping.py` — map: `EntityNotFound→404`, `Auth→403`, `Validation→422`, `Business/Idempotency/Concurrency→409`, default→500. 2. Port `exception_handlers.py` — `domain_error_handler(request, exc)` returns JSONResponse with ErrorResponse body. `unhandled_exception_handler` returns 500 with structured logging. 3. Use `get_logger()` for error logging. 4. Format with ruff. |
| **Tests required** | **Unit**: `test_api_error_handlers.py` — each DomainError subclass maps to correct HTTP status. |
| **Documentation updates** | None. |
| **DoD** | Exception handlers registered on FastAPI app. Error mapping complete. Tests pass. |
| **Risks** | None. |
| **Rollback** | Delete files. |
| **Effort** | **S** |

---

### TASK-029: Implement API routes + dependencies

| Field | Detail |
|-------|--------|
| **ID** | TASK-029 |
| **Title** | Implement all API routes with DI |
| **Objective** | Create all 14 endpoints per `docs/services/portfolio.md` plus DI setup. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/api/routes/`, `platform_repo/apps/backend-portfolio/src/portfolio/api/dependencies.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/api/dependencies.py`, `worldview/services/portfolio/src/portfolio/api/routes/__init__.py`, `tenant.py`, `user.py`, `portfolio.py`, `transaction.py`, `holding.py`, `instrument.py` |
| **Prerequisites** | TASK-025 (UoW), TASK-017–TASK-021 (use cases), TASK-027 (schemas), TASK-028 (error handling) |
| **Implementation steps** | 1. Create `dependencies.py` — `uow_dep()` using `Depends`, session factory from app state, `on_commit` from dispatcher. 2. Create `routes/` package. 3. Port tenant routes: `POST /api/v1/tenants`, `GET /api/v1/tenants/{id}`. 4. Port user routes: `POST /api/v1/users`, `GET /api/v1/users/{id}`. 5. Port portfolio routes: `POST`, `GET` (list), `GET /{id}`, `PUT /{id}` (rename — new), `DELETE /{id}` (archive — new route). 6. Port transaction routes: `POST /api/v1/transactions` (with `Idempotency-Key` header), `GET /api/v1/transactions`. 7. Port holding routes: `GET /api/v1/holdings/{portfolio_id}`. 8. Port instrument routes: `GET /api/v1/instruments` (new — list), legacy `GET /{id}`. 9. Register all routers on app. 10. Format with ruff. |
| **Tests required** | **Unit**: Route registration smoke test. **Integration**: Covered in TASK-036. |
| **Documentation updates** | Verify `docs/services/portfolio.md` endpoint table matches implementation. |
| **DoD** | All 14 endpoints registered. DI wired. Tenant_id/user_id propagated correctly. |
| **Risks** | New endpoints (PUT rename, DELETE archive, GET users, GET instruments list) have no legacy reference — implement from use case logic. |
| **Rollback** | Delete `routes/` directory + dependencies.py. |
| **Effort** | **L** |

---

## Phase 5 — Messaging Layer

### TASK-030: Implement Avro schemas (.avsc files)

| Field | Detail |
|-------|--------|
| **ID** | TASK-030 |
| **Title** | Create Avro schema files for portfolio events |
| **Objective** | Port 3 existing schemas + create 1 new schema (`instrument_ref.created`). |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/messaging/schemas/` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/messaging/schemas/transaction.recorded.avsc`, `user.created.avsc`, `tenant.created.avsc`, `portfolio.created.avsc`, `portfolio.renamed.avsc`, `portfolio.archived.avsc`, `holding.changed.avsc`, `instrument_ref.created.avsc` |
| **Prerequisites** | TASK-012 (domain events) |
| **Implementation steps** | 1. Create `messaging/schemas/` directory. 2. Copy existing `.avsc` files from legacy. 3. Add new schemas for events that need them: `portfolio.created`, `portfolio.renamed`, `portfolio.archived`, `holding.changed`, `instrument_ref.created`. 4. Ensure all schemas have envelope fields (event_id, event_type, occurred_at, etc.). 5. Use namespace `portfolio.events`. |
| **Tests required** | **Contract**: Covered in TASK-037. |
| **Documentation updates** | None. |
| **DoD** | All 8 `.avsc` files valid JSON, parseable by fastavro. |
| **Risks** | New schemas must be forward-compatible with any future changes. |
| **Rollback** | Delete `.avsc` files. |
| **Effort** | **M** |

---

### TASK-031: Implement topic routing + event mappers

| Field | Detail |
|-------|--------|
| **ID** | TASK-031 |
| **Title** | Implement topic routing table and event-to-dict mappers |
| **Objective** | Port routing (all events → `portfolio.events.v1`) and event serialization mappers. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/messaging/topics.py`, `platform_repo/apps/backend-portfolio/src/portfolio/messaging/mapper.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/messaging/__init__.py`, `worldview/services/portfolio/src/portfolio/messaging/topics.py`, `worldview/services/portfolio/src/portfolio/messaging/mapper.py` |
| **Prerequisites** | TASK-012 (domain events) |
| **Implementation steps** | 1. Create `messaging/` package. 2. Port `topics.py` — single outbound topic `portfolio.events.v1`, routing table for all 10 event types. 3. Port `mapper.py` — `event_to_envelope_dict()`, `transaction_recorded_to_dict()`, `user_created_to_dict()`, `tenant_created_to_dict()`. 4. Add mappers for new events: `portfolio_created_to_dict()`, `portfolio_renamed_to_dict()`, `portfolio_archived_to_dict()`, `holding_changed_to_dict()`, `instrument_ref_created_to_dict()`. 5. Format with ruff. |
| **Tests required** | **Unit**: Mapper output matches expected dict structure. |
| **Documentation updates** | None. |
| **DoD** | All 10 event types have mappers and routing entries. |
| **Risks** | New mappers for events that weren't in legacy — design from event fields. |
| **Rollback** | Delete files. |
| **Effort** | **M** |

---

### TASK-032: Implement outbox serialization + OutboxDispatcher

| Field | Detail |
|-------|--------|
| **ID** | TASK-032 |
| **Title** | Implement serialization layer and concrete OutboxDispatcher |
| **Objective** | Port `serialization.py`, `outbox_mapper.py`, and `OutboxDispatcher` (concrete). |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/messaging/serialization.py`, `outbox_mapper.py`, `dispatcher.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/messaging/serialization.py`, `worldview/services/portfolio/src/portfolio/messaging/outbox_mapper.py`, `worldview/services/portfolio/src/portfolio/messaging/dispatcher.py` |
| **Prerequisites** | TASK-004 (BaseOutboxDispatcher), TASK-030 (Avro schemas), TASK-031 (mappers) |
| **Implementation steps** | 1. Port `serialization.py` — `build_outbox_event_serializers()` mapping event_type → Avro serializer, `headers_for_event()`. 2. Port `outbox_mapper.py` — identity mapper for pre-serialized payloads. 3. Port `OutboxDispatcher` extending `BaseOutboxDispatcher` — implement `_build_producer()` and `_produce_record()`. 4. Port `DispatcherConfig` from settings. 5. Use `get_logger()`. 6. Format with ruff. |
| **Tests required** | **Unit**: `test_serialization.py` — headers generation, outbox mapper identity. |
| **Documentation updates** | None. |
| **DoD** | `OutboxDispatcher` can be instantiated with config. Serialization chain complete. Tests pass. |
| **Risks** | Avro serializer configuration must match `.avsc` schemas exactly. |
| **Rollback** | Delete files. |
| **Effort** | **M** |

---

### TASK-033: Implement dispatcher_main entry point

| Field | Detail |
|-------|--------|
| **ID** | TASK-033 |
| **Title** | Implement standalone dispatcher process entry point |
| **Objective** | Create `dispatcher_main.py` with signal handling for graceful shutdown. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/messaging/dispatcher_main.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/messaging/dispatcher_main.py` |
| **Prerequisites** | TASK-032 (OutboxDispatcher) |
| **Implementation steps** | 1. Port `dispatcher_main.py` — `asyncio.run(main())`, SIGTERM/SIGINT handlers, settings loading, dispatcher creation + `run_dispatcher()`. 2. Use `configure_logging()` from observability. 3. Format with ruff. |
| **Tests required** | **Unit**: None — tested via integration. |
| **Documentation updates** | Add entry point to `docs/services/portfolio.md` background jobs table. |
| **DoD** | `python -m portfolio.messaging.dispatcher_main` starts successfully (exits cleanly without Kafka). |
| **Risks** | Depends on Kafka being available in prod — must handle startup failures gracefully. |
| **Rollback** | Delete file. |
| **Effort** | **S** |

---

### TASK-034: Implement InstrumentEventConsumer

| Field | Detail |
|-------|--------|
| **ID** | TASK-034 |
| **Title** | Implement Kafka consumer for instrument sync from Market Data |
| **Objective** | Port `InstrumentEventConsumer` — subscribes to `market.instrument.created` and `market.instrument.updated`, upserts `InstrumentRef` in portfolio_db. |
| **Search paths** | `platform_repo/apps/backend-portfolio/src/portfolio/consumers/instrument_consumer.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/consumers/__init__.py`, `worldview/services/portfolio/src/portfolio/consumers/instrument_consumer.py` |
| **Prerequisites** | TASK-001 (BaseKafkaConsumer), TASK-024 (repos), TASK-025 (UoW) |
| **Implementation steps** | 1. Create `consumers/` package. 2. Port `InstrumentEventConsumer` extending `BaseKafkaConsumer`. 3. Implement all abstract methods: `create_uow()`, `process_message()` (upsert InstrumentRef), `is_duplicate()` (check by event_id), `mark_processed()`, `record_failure()`, etc. 4. Use consumer group `portfolio-instrument-sync`. 5. Use `get_logger()` with topic/event context. 6. Format with ruff. |
| **Tests required** | **Unit**: `test_instrument_consumer.py` — process_message creates instrument, duplicate detection. |
| **Documentation updates** | Verify `docs/services/portfolio.md` consumed topics table. |
| **DoD** | Consumer can process instrument events and upsert to DB. Tests pass. |
| **Risks** | Depends on Market Data service producing events in correct format. |
| **Rollback** | Delete `consumers/` directory. |
| **Effort** | **M** |

---

## Phase 6 — Database Migration + App Wiring

### TASK-035: Wire Alembic + generate initial migration

| Field | Detail |
|-------|--------|
| **ID** | TASK-035 |
| **Title** | Wire Alembic target_metadata and generate initial migration |
| **Objective** | Connect Alembic to SQLAlchemy `Base.metadata` and generate a clean initial migration. |
| **Search paths** | `worldview/services/portfolio/alembic/env.py`, `platform_repo/apps/backend-portfolio/alembic/` |
| **Touched paths** | `worldview/services/portfolio/alembic/env.py`, `worldview/services/portfolio/alembic/versions/0001_initial_schema.py` |
| **Prerequisites** | TASK-022 (DB models) |
| **Implementation steps** | 1. Update `alembic/env.py` — import `Base.metadata` from `portfolio.infrastructure.db.models`, set `target_metadata = Base.metadata`. 2. Run `alembic revision --autogenerate -m "initial_schema"`. 3. Review generated migration — verify all 8 tables, indexes, constraints. 4. Fix any autogenerate issues. 5. Test: `alembic upgrade head` on clean DB. |
| **Tests required** | **Integration**: Migration applies cleanly, `alembic downgrade base` works. |
| **Documentation updates** | None. |
| **DoD** | `alembic upgrade head` creates all 8 tables. Downgrade works. |
| **Risks** | Autogenerate may not capture all constraints (e.g., CHECK constraints, partial indexes). Manual review required. |
| **Rollback** | Delete migration file, revert env.py. |
| **Effort** | **M** |

---

### TASK-036: Wire app lifespan + readyz + observability

| Field | Detail |
|-------|--------|
| **ID** | TASK-036 |
| **Title** | Complete app factory with full lifespan, readyz probe, and observability |
| **Objective** | Wire the app factory to create DB engine, dispatcher, consumer, and observability on startup. |
| **Search paths** | `worldview/services/portfolio/src/portfolio/app.py`, `platform_repo/apps/backend-portfolio/src/portfolio/api/lifespan.py` |
| **Touched paths** | `worldview/services/portfolio/src/portfolio/app.py` |
| **Prerequisites** | TASK-023 (session), TASK-025 (UoW), TASK-028 (error handlers), TASK-029 (routes), TASK-032 (dispatcher), TASK-034 (consumer), TASK-006 (metrics), TASK-026 (settings) |
| **Implementation steps** | 1. Update `app.py` lifespan — on startup: `configure_logging()`, `configure_tracing()`, `create_session_factory()`, create `OutboxDispatcher`, store in `app.state`. 2. On shutdown: close engine, stop dispatcher. 3. Update `/readyz` — check DB connectivity (simple query), return 503 if unhealthy. 4. Register exception handlers from TASK-028. 5. Register all route routers. 6. Add `add_prometheus_middleware()`. 7. Add `/metrics` endpoint. 8. Format with ruff. |
| **Tests required** | **Unit**: Update existing health tests. Add readyz failure test (mock DB down). |
| **Documentation updates** | None. |
| **DoD** | App starts with all components wired. `/readyz` checks DB. `/metrics` returns Prometheus data. All routes registered. |
| **Risks** | Startup order matters — DB must be available before other components. |
| **Rollback** | Revert app.py. |
| **Effort** | **M** |

---

## Phase 7 — Testing

### TASK-037: Contract tests for Avro schemas

| Field | Detail |
|-------|--------|
| **ID** | TASK-037 |
| **Title** | Write contract tests validating mapper output against Avro schemas |
| **Objective** | Ensure all event mappers produce output compatible with their `.avsc` schemas. |
| **Search paths** | `platform_repo/apps/backend-portfolio/tests/contract/` |
| **Touched paths** | `worldview/services/portfolio/tests/contract/__init__.py`, `test_transaction_recorded_contract.py`, `test_tenant_created_contract.py`, `test_user_created_contract.py`, `test_portfolio_created_contract.py`, `test_holding_changed_contract.py` |
| **Prerequisites** | TASK-030 (Avro schemas), TASK-031 (mappers) |
| **Implementation steps** | 1. Create `tests/contract/` package. 2. Port 3 existing contract tests from legacy. 3. Add contract tests for new events: `portfolio.created`, `portfolio.renamed`, `portfolio.archived`, `holding.changed`, `instrument_ref.created`. 4. Use `fastavro.validate()` to check mapper output against parsed schema. 5. Run `make test`. |
| **Tests required** | Self — this IS the testing task. |
| **Documentation updates** | None. |
| **DoD** | All 8 event types have contract tests. All pass. |
| **Risks** | Schema evolution must be forward-compatible. |
| **Rollback** | Delete `contract/` directory. |
| **Effort** | **M** |

---

### TASK-038: Integration test infrastructure (conftest + testcontainers)

| Field | Detail |
|-------|--------|
| **ID** | TASK-038 |
| **Title** | Set up integration test infrastructure with testcontainers + savepoint isolation |
| **Objective** | Port the test infrastructure: PostgreSQL testcontainer, Alembic migration on startup, savepoint-based transaction isolation. |
| **Search paths** | `platform_repo/apps/backend-portfolio/tests/conftest.py`, `platform_repo/apps/backend-portfolio/tests/integration/helpers.py` |
| **Touched paths** | `worldview/services/portfolio/tests/conftest.py`, `worldview/services/portfolio/tests/integration/__init__.py`, `worldview/services/portfolio/tests/integration/helpers.py` |
| **Prerequisites** | TASK-035 (Alembic migration), TASK-025 (UoW) |
| **Implementation steps** | 1. Update `tests/conftest.py` — add PostgreSQL testcontainer fixture (session-scoped). 2. Run Alembic migrations on container startup. 3. Create savepoint-based `db_session` fixture (function-scoped). 4. Create `test_session_factory`, `test_uow`, `test_client` fixtures. 5. Add `tenant_factory`, `user_factory` helpers. 6. Port `helpers.py` — `OutboxAssertions`, contract models for event validation. 7. Ensure `testcontainers` is in dev dependencies. |
| **Tests required** | Self — fixtures tested by integration tests in TASK-039. |
| **Documentation updates** | None. |
| **DoD** | Integration test fixtures work. Testcontainer starts. Savepoint isolation verified. |
| **Risks** | Docker must be running. CI environment may need Docker-in-Docker. |
| **Rollback** | Revert conftest.py, delete helpers.py. |
| **Effort** | **L** |

---

### TASK-039: Integration tests for all API endpoints

| Field | Detail |
|-------|--------|
| **ID** | TASK-039 |
| **Title** | Write integration tests for all Portfolio API endpoints |
| **Objective** | Test full API → UoW → DB round-trip for all endpoints. |
| **Search paths** | `platform_repo/apps/backend-portfolio/tests/integration/` |
| **Touched paths** | `worldview/services/portfolio/tests/integration/test_tenant_api.py`, `test_user_api.py`, `test_portfolio_api.py`, `test_transaction_api.py`, `test_holding_api.py`, `test_instrument_api.py` |
| **Prerequisites** | TASK-038 (test infrastructure), TASK-029 (routes) |
| **Implementation steps** | 1. Port `test_tenant_api.py` — create tenant, verify DB, verify outbox event. 2. Port `test_user_api.py` — create user, email normalization, validation errors. 3. Port `test_portfolio_api.py` — create, list, get, rename (NEW), archive (NEW). 4. Add `test_transaction_api.py` — record transaction, verify holding update, verify outbox events, idempotency replay. 5. Add `test_holding_api.py` — get holdings after transaction. 6. Add `test_instrument_api.py` — list instruments. 7. Run `make test-integration`. |
| **Tests required** | Self — this IS the testing task. |
| **Documentation updates** | None. |
| **DoD** | All integration tests pass against testcontainer. Coverage for all endpoints. |
| **Risks** | Testcontainer startup time may be slow. |
| **Rollback** | Delete integration test files. |
| **Effort** | **L** |

---

### TASK-040: Unit tests for use cases (with mocked repos)

| Field | Detail |
|-------|--------|
| **ID** | TASK-040 |
| **Title** | Write unit tests for all use cases with fake/mocked repositories |
| **Objective** | Test use case logic in isolation from DB. |
| **Search paths** | `platform_repo/apps/backend-portfolio/tests/unit/test_user_created_outbox.py` |
| **Touched paths** | `worldview/services/portfolio/tests/unit/test_use_cases_tenant.py`, `test_use_cases_user.py`, `test_use_cases_portfolio.py`, `test_use_cases_transaction.py`, `test_use_cases_read_models.py` |
| **Prerequisites** | TASK-017–TASK-021 (use cases) |
| **Implementation steps** | 1. Create fake UoW + fake repos (in-memory dicts). 2. Test each use case: happy path, validation errors, domain errors, outbox event emission. 3. For `RecordTransactionUseCase`: test BUY, SELL, insufficient holdings, currency mismatch, idempotency. 4. Run `make test`. |
| **Tests required** | Self — this IS the testing task. |
| **Documentation updates** | None. |
| **DoD** | All use case tests pass. Coverage > 90% for application layer. |
| **Risks** | Fake repos must faithfully simulate port interfaces. |
| **Rollback** | Delete test files. |
| **Effort** | **M** |

---

## Phase 8 — Cross-Service + Deployment

### TASK-041: Docker Compose service definition

| Field | Detail |
|-------|--------|
| **ID** | TASK-041 |
| **Title** | Add Portfolio service to Docker Compose |
| **Objective** | Create Dockerfile + compose service definition for portfolio. |
| **Search paths** | `worldview/infra/compose/` (if exists), `worldview/docker-compose.yml` |
| **Touched paths** | `worldview/services/portfolio/Dockerfile`, `worldview/docker-compose.yml` (or `worldview/infra/compose/docker-compose.yml`) |
| **Prerequisites** | TASK-036 (app wiring) |
| **Implementation steps** | 1. Create `Dockerfile` — multi-stage build (builder + runtime), Python 3.12, install deps, copy src. 2. Add `portfolio` service to compose — depends_on postgres, kafka. 3. Add health check. 4. Map port 8000. 5. Add env vars from dev.local.env.example. |
| **Tests required** | **Manual**: `docker compose up portfolio` starts and `/healthz` returns 200. |
| **Documentation updates** | Update `docs/services/portfolio.md` Local Run section. |
| **DoD** | `docker compose up portfolio` starts successfully with DB + Kafka dependencies. |
| **Risks** | Compose file structure may vary — check existing convention. |
| **Rollback** | Delete Dockerfile, revert compose. |
| **Effort** | **M** |

---

### TASK-042: Platform QA — cross-service instrument sync flow

| Field | Detail |
|-------|--------|
| **ID** | TASK-042 |
| **Title** | QA test: Market Data → Kafka → Portfolio instrument sync |
| **Objective** | Validate the end-to-end instrument synchronization flow. |
| **Search paths** | N/A — new test |
| **Touched paths** | `worldview/services/portfolio/tests/e2e/test_instrument_sync.py` (or platform-level test) |
| **Prerequisites** | TASK-034 (consumer), TASK-041 (Docker Compose) |
| **Implementation steps** | 1. Design test scenario: produce `market.instrument.created` event to Kafka → verify Portfolio DB has instrument. 2. Produce `market.instrument.updated` event → verify Portfolio DB instrument updated. 3. Produce duplicate event → verify no error (idempotent). 4. Can be manual or automated with testcontainers-compose. |
| **Tests required** | Self — this IS the testing task. |
| **Documentation updates** | Document QA scenario in `docs/services/portfolio.md`. |
| **DoD** | Instrument sync works end-to-end. Idempotency verified. |
| **Risks** | Requires Kafka + Schema Registry running. |
| **Rollback** | Delete test file. |
| **Effort** | **M** |

---

### TASK-043: Platform QA — transaction recording full flow

| Field | Detail |
|-------|--------|
| **ID** | TASK-043 |
| **Title** | QA test: Full transaction flow (create tenant → create portfolio → record transaction → verify holding → verify Kafka event) |
| **Objective** | Validate the complete happy path including outbox dispatch to Kafka. |
| **Search paths** | N/A — new test |
| **Touched paths** | `worldview/services/portfolio/tests/e2e/test_full_flow.py` |
| **Prerequisites** | TASK-039 (integration tests), TASK-041 (Docker Compose) |
| **Implementation steps** | 1. Start Portfolio service + infra via compose. 2. POST tenant → POST user → POST portfolio → POST transaction (BUY). 3. GET holdings → verify quantity and avg_cost. 4. POST another transaction (SELL partial). 5. GET holdings → verify updated. 6. Consume from `portfolio.events.v1` → verify events received. 7. Can be manual or pytest-based. |
| **Tests required** | Self — this IS the testing task. |
| **Documentation updates** | Document QA scenario. |
| **DoD** | Full flow works. Events published to Kafka. Holdings correct. |
| **Risks** | Requires full infra stack running. |
| **Rollback** | Delete test file. |
| **Effort** | **M** |

---

### TASK-044: Documentation updates sweep

| Field | Detail |
|-------|--------|
| **ID** | TASK-044 |
| **Title** | Final documentation review and update sweep |
| **Objective** | Ensure all docs are consistent with implementation. |
| **Search paths** | `worldview/docs/services/portfolio.md`, `worldview/docs/migration/REUSE_FROM_ORIGINAL_THESIS.md`, `worldview/docs/libs/*.md` |
| **Touched paths** | All docs files listed above |
| **Prerequisites** | All TASK-001 through TASK-043 |
| **Implementation steps** | 1. Review `docs/services/portfolio.md` — verify all endpoints match implementation, update schema if needed, verify event types. 2. Update `docs/migration/REUSE_FROM_ORIGINAL_THESIS.md` — mark Portfolio section as ✅ MIGRATED. 3. Update `docs/libs/messaging.md` — mark implemented sections. 4. Update `docs/libs/observability.md` — mark metrics/tracing as implemented. 5. Update `docs/libs/storage.md` — no changes (portfolio doesn't use storage). 6. Verify `configs/dev.local.env.example` has all vars. |
| **Tests required** | None — documentation task. |
| **Documentation updates** | Self — this IS the documentation task. |
| **DoD** | All docs consistent with implementation. No stale references. |
| **Risks** | None. |
| **Rollback** | Git revert. |
| **Effort** | **M** |

---

### TASK-045: pyproject.toml dependencies update

| Field | Detail |
|-------|--------|
| **ID** | TASK-045 |
| **Title** | Update pyproject.toml with all required dependencies |
| **Objective** | Ensure portfolio service and all libs have correct dependencies declared. |
| **Search paths** | `worldview/services/portfolio/pyproject.toml`, `worldview/libs/messaging/pyproject.toml`, `worldview/libs/observability/pyproject.toml` |
| **Touched paths** | Same |
| **Prerequisites** | None — can be done early and updated incrementally |
| **Implementation steps** | 1. `libs/messaging/pyproject.toml` — add: `confluent-kafka`, `fastavro`, `redis`, `pydantic-settings`. 2. `libs/observability/pyproject.toml` — add: `prometheus-client`, `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-grpc`, `opentelemetry-instrumentation-fastapi`, `structlog`. 3. `services/portfolio/pyproject.toml` — add: `common @ ...`, `contracts @ ...`, `messaging @ ...`, `observability @ ...`, `storage @ ...` path deps. Add: `testcontainers[postgres]` to dev deps. 4. Verify `uv pip install -e .` works for each. |
| **Tests required** | `uv pip install -e .` succeeds for all affected packages. |
| **Documentation updates** | None. |
| **DoD** | All packages install cleanly. No missing deps at runtime. |
| **Risks** | Version conflicts across libs. |
| **Rollback** | Git revert pyproject.toml files. |
| **Effort** | **S** |

---

### TASK-046: Security + tenant isolation audit

| Field | Detail |
|-------|--------|
| **ID** | TASK-046 |
| **Title** | Audit all queries and routes for tenant isolation |
| **Objective** | Verify every DB query filters by `tenant_id`, every route extracts tenant context. |
| **Search paths** | `worldview/services/portfolio/src/portfolio/infrastructure/db/repositories/`, `worldview/services/portfolio/src/portfolio/api/routes/` |
| **Touched paths** | Any file needing fixes |
| **Prerequisites** | TASK-024 (repos), TASK-029 (routes) |
| **Implementation steps** | 1. Grep all repository methods — verify `tenant_id` filter on SELECT/UPDATE/DELETE. 2. Grep all route handlers — verify `tenant_id` parameter extracted and passed to use cases. 3. Verify portfolio/holding/transaction access checks include ownership validation. 4. Fix any gaps found. 5. Add negative test cases to integration tests (attempt cross-tenant access → 403). |
| **Tests required** | **Integration**: Cross-tenant access attempt returns 403 for portfolios, transactions, holdings. |
| **Documentation updates** | None. |
| **DoD** | All queries are tenant-scoped. Cross-tenant tests fail with 403. |
| **Risks** | Missing tenant filter = data leak. |
| **Rollback** | N/A — security fix. |
| **Effort** | **M** |

---

# 5. Suggested Execution Sequence & Critical Path

## Critical Path

```
TASK-045 (deps) ─┐
                 ├─→ TASK-001 (consumer) ──────────────────────────────→ TASK-034 (instrument consumer)
                 ├─→ TASK-002 (serializer) → TASK-003 (producer) → TASK-004 (dispatcher) ──→ TASK-032 (outbox) → TASK-033 (dispatcher main)
                 ├─→ TASK-006 (metrics) ──────────────────────────────→ TASK-036 (app wiring)
                 │
TASK-009 (enums) ───→ TASK-010 (VOs) ──→ TASK-011 (entities) ──→ TASK-012 (events) ──→ TASK-014 (pkg)
TASK-013 (errors)──────────────────↗                                        │
                                                                             ↓
                                                                     TASK-016 (ports) → TASK-017–021 (use cases)
                                                                             │                    │
                                                                     TASK-022 (models) → TASK-024 (repos) → TASK-025 (UoW)
                                                                             │                                    │
                                                                     TASK-035 (alembic)               TASK-029 (routes)
                                                                             │                            │
                                                                     TASK-038 (test infra) → TASK-039 (integration tests)
```

## Recommended Execution Order

### Sprint 0 — Foundations (parallel, ~2 days)
| Order | Task | Can Parallelize With |
|-------|------|---------------------|
| 0.1 | TASK-045: pyproject.toml deps | All others |
| 0.2 | TASK-008: common lib tests | All others |
| 0.3 | TASK-009: domain enums | TASK-010, TASK-013 |
| 0.4 | TASK-010: domain VOs | TASK-009, TASK-013 |
| 0.5 | TASK-013: domain errors | TASK-009, TASK-010 |

### Sprint 1 — Domain + Libs (parallel tracks, ~3 days)

**Track A — Domain:**
| Order | Task | Depends On |
|-------|------|-----------|
| 1.1 | TASK-011: domain entities | TASK-009, TASK-010 |
| 1.2 | TASK-012: domain events | TASK-009 |
| 1.3 | TASK-014: domain package | TASK-011, TASK-012 |
| 1.4 | TASK-015: domain tests | TASK-014 |

**Track B — Messaging Lib:**
| Order | Task | Depends On |
|-------|------|-----------|
| 1.5 | TASK-002: serializer | — |
| 1.6 | TASK-001: consumer base | — |
| 1.7 | TASK-003: producer | TASK-002 |
| 1.8 | TASK-004: dispatcher base | TASK-003 |
| 1.9 | TASK-005: Valkey client | — |

**Track C — Observability Lib:**
| Order | Task | Depends On |
|-------|------|-----------|
| 1.10 | TASK-006: metrics | — |
| 1.11 | TASK-007: tracing | — |

### Sprint 2 — Application + Infrastructure (~3 days)
| Order | Task | Depends On |
|-------|------|-----------|
| 2.1 | TASK-016: application ports | TASK-014 |
| 2.2 | TASK-022: DB models | TASK-009 |
| 2.3 | TASK-023: session factory | — |
| 2.4 | TASK-017: tenant use case | TASK-016 |
| 2.5 | TASK-018: user use case | TASK-017 |
| 2.6 | TASK-019: portfolio use cases | TASK-018 |
| 2.7 | TASK-020: record transaction | TASK-019 |
| 2.8 | TASK-021: read models | TASK-016 |
| 2.9 | TASK-024: DB repositories | TASK-016, TASK-022 |
| 2.10 | TASK-025: UoW | TASK-023, TASK-024 |
| 2.11 | TASK-026: settings | — |

### Sprint 3 — API + Messaging (~3 days)
| Order | Task | Depends On |
|-------|------|-----------|
| 3.1 | TASK-027: API schemas | TASK-009 |
| 3.2 | TASK-028: error handling | TASK-013, TASK-027 |
| 3.3 | TASK-029: API routes | TASK-025, TASK-017–021, TASK-027, TASK-028 |
| 3.4 | TASK-030: Avro schemas | TASK-012 |
| 3.5 | TASK-031: topic routing + mappers | TASK-012 |
| 3.6 | TASK-032: outbox serialization | TASK-004, TASK-030, TASK-031 |
| 3.7 | TASK-033: dispatcher main | TASK-032 |
| 3.8 | TASK-034: instrument consumer | TASK-001, TASK-024, TASK-025 |

### Sprint 4 — Wiring + Testing (~3 days)
| Order | Task | Depends On |
|-------|------|-----------|
| 4.1 | TASK-035: Alembic migration | TASK-022 |
| 4.2 | TASK-036: app wiring | TASK-023, TASK-025, TASK-028, TASK-029, TASK-032, TASK-034, TASK-006 |
| 4.3 | TASK-040: unit tests (use cases) | TASK-017–021 |
| 4.4 | TASK-037: contract tests | TASK-030, TASK-031 |
| 4.5 | TASK-038: integration test infra | TASK-035, TASK-025 |
| 4.6 | TASK-039: integration tests | TASK-038, TASK-029 |
| 4.7 | TASK-046: security audit | TASK-024, TASK-029 |

### Sprint 5 — Deployment + QA (~2 days)
| Order | Task | Depends On |
|-------|------|-----------|
| 5.1 | TASK-041: Docker Compose | TASK-036 |
| 5.2 | TASK-042: QA instrument sync | TASK-034, TASK-041 |
| 5.3 | TASK-043: QA full flow | TASK-039, TASK-041 |
| 5.4 | TASK-044: docs sweep | All |

---

# 6. Release Readiness Criteria

| Criterion | Verification Method | Status |
|-----------|-------------------|--------|
| All 14 API endpoints respond correctly | Integration tests (TASK-039) | ⬜ |
| All domain entities have >90% test coverage | `make test` + coverage report | ⬜ |
| All use cases have unit tests with mocked repos | TASK-040 | ⬜ |
| All 8+ event types have contract tests | TASK-037 | ⬜ |
| Outbox dispatcher publishes events to Kafka | TASK-043 QA | ⬜ |
| Instrument consumer syncs from Market Data | TASK-042 QA | ⬜ |
| Alembic migrations apply cleanly (up + down) | TASK-035 | ⬜ |
| `/healthz` returns 200 | Existing test | ⬜ |
| `/readyz` checks DB connectivity | TASK-036 | ⬜ |
| `/metrics` returns Prometheus data | TASK-036 | ⬜ |
| Tenant isolation: cross-tenant access blocked | TASK-046 | ⬜ |
| `ruff check` passes with zero errors | `make lint` | ⬜ |
| `mypy` passes with zero errors | `make lint` | ⬜ |
| `configs/dev.local.env.example` has all vars | TASK-026 | ⬜ |
| `docs/services/portfolio.md` matches implementation | TASK-044 | ⬜ |
| Docker Compose starts successfully | TASK-041 | ⬜ |
| No hardcoded secrets in code | Code review | ⬜ |
| All timestamps are UTC | Code review / TASK-046 | ⬜ |
| All entity IDs use UUIDv7 | Code review | ⬜ |
| `structlog` used exclusively (no print/logging) | `grep -r "print(" + grep -r "logging."` | ⬜ |

### Rollout Plan

1. **Dev**: Merge to `main` branch → CI runs all tests
2. **Local verification**: `docker compose up` → run QA scenarios manually
3. **Staging** (if applicable): Deploy to staging namespace → smoke test endpoints
4. **Production**: Deploy via K8s manifests → verify `/readyz` + `/metrics`

### Rollback Plan

1. **DB**: `alembic downgrade base` (destructive — only for fresh deployments)
2. **Service**: Revert Docker image to previous tag
3. **Kafka**: Consumer group offsets are committed per-message — no data loss on rollback
4. **Outbox**: Pending outbox events remain in DB — will be dispatched after redeploy

---

## Approach (How)

### Paths Analyzed
- `platform_repo/apps/backend-portfolio/` — complete recursive scan of all 60+ files
- `platform_repo/libs/common/`, `libs/messaging/`, `libs/contracts/`, `libs/storage/` — full scan
- `worldview/services/portfolio/` — complete scan (6 files, scaffold only)
- `worldview/libs/common/`, `libs/contracts/`, `libs/messaging/`, `libs/storage/`, `libs/observability/` — complete scan
- `worldview/docs/services/portfolio.md` — target spec (full read)
- `worldview/docs/migration/REUSE_FROM_ORIGINAL_THESIS.md` — migration guide (full read)
- `worldview/docs/architecture/decisions/0001-initial-architecture.md` — ADR (full read)
- `worldview/docs/libs/*.md` — all lib docs (full read)
- `worldview/AGENTS.md`, `worldview/CLAUDE.md` — agent operating guides (full read)
- `worldview/.claude/agents/backend-engineer.md`, `architecture-decision-lead.md` — role definitions (full read)

### Key Steps
1. Full inventory of legacy codebase (entities, routes, repos, events, tests, config)
2. Full inventory of target codebase (scaffold state)
3. Full read of target specifications in docs
4. Gap analysis between legacy implementation and target spec
5. Identification of shared library blockers
6. Task decomposition following dependency graph
7. Critical path analysis for execution ordering

## Rationale (Why)

### Architecture Decisions
- **Phase 0 (libs) before service tasks**: Shared libraries are blocking dependencies — messaging consumer/dispatcher/producer must exist before portfolio can use them.
- **Domain-first approach**: Domain layer has zero dependencies and all other layers depend on it — building it first enables parallel work on application and infrastructure.
- **Separate tracks for parallel execution**: Domain, messaging lib, and observability lib have no inter-dependencies — they can be built simultaneously.
- **JSONB outbox (target) over LargeBinary (legacy)**: Target spec uses JSONB payload which simplifies debugging and allows DB-level queries on event data.
- **Simplified idempotency table**: Target spec uses simple `(event_id, processed_at)` for consumer idempotency instead of the heavier API idempotency table in legacy — separation of concerns.
- **UUIDv7 upgrade**: Target docs mandate UUIDv7 for time-sortable IDs — this is implemented via `common.ids` (already using `python-ulid`).
- **`owner_id` simplification**: Target schema uses `owner_id` instead of legacy's `user_id` + `created_by_user_id` dual FK — reduces complexity.
- **API versioning (`/api/v1/`)**: Target spec adds version prefix for future-proofing — legacy used unversioned `/api/`.

### Alternatives Considered
- **Big-bang migration**: Migrate everything at once → Rejected: too risky, harder to test incrementally.
- **Incremental migration with adapter layer**: Run legacy and new side-by-side → Rejected: thesis scope doesn't warrant the complexity.
- **Skip shared lib migration, inline everything**: → Rejected: contradicts monorepo architecture and reuse goals.

## Testing Summary

| Test Type | Task(s) | Count |
|-----------|---------|-------|
| Unit — domain | TASK-015 | 4 test files, ~30 tests |
| Unit — use cases | TASK-040 | 5 test files, ~25 tests |
| Unit — API schemas | TASK-027 | 1 test file, ~10 tests |
| Unit — API errors | TASK-028 | 1 test file, ~8 tests |
| Contract — Avro | TASK-037 | 5 test files, ~10 tests |
| Integration — API | TASK-039 | 6 test files, ~30 tests |
| E2E — cross-service | TASK-042, TASK-043 | 2 test scenarios |
| **Total** | | **~113 tests estimated** |

## Documentation Updates Required

| Doc File | Update Task | Changes |
|----------|-------------|---------|
| `docs/services/portfolio.md` | TASK-044 | Verify endpoints, events, schema match final implementation |
| `docs/migration/REUSE_FROM_ORIGINAL_THESIS.md` | TASK-044 | Mark Portfolio section as ✅ MIGRATED |
| `docs/libs/messaging.md` | TASK-001–005 | Mark sections as implemented |
| `docs/libs/observability.md` | TASK-006, TASK-007 | Mark metrics + tracing as implemented |
| `configs/dev.local.env.example` | TASK-026 | Add all new config vars |
| `configs/prod.env.example` | TASK-026 | Add all new config vars |

## Risks / Follow-ups

### Risks
1. **Confluent Kafka C extension**: May have build issues on some environments — mitigate with Docker-based testing.
2. **Testcontainers Docker requirement**: CI must have Docker — verify CI configuration.
3. **Schema Registry dependency**: Avro serialization requires running Schema Registry — must be in Docker Compose.
4. **New event types without legacy reference**: `instrument_ref.created`, `portfolio.created`, `portfolio.renamed`, `holding.changed` need careful schema design.
5. **JSONB vs LargeBinary outbox change**: Outbox repository logic differs — must test thoroughly.

### Remaining Follow-ups
1. **K8s manifests**: Not in scope for thesis but listed as optional in TASK-041.
2. **Valkey cache integration**: Portfolio service doesn't need it immediately — TASK-005 builds the client for future use.
3. **Storage lib completion**: Portfolio doesn't use S3 directly — remaining gaps (L-09 to L-12) are for other services.
4. **Frontend integration**: Depends on API Gateway (S9) — out of scope for this plan.
5. **Performance testing**: Not included — consider adding after functional completeness.
