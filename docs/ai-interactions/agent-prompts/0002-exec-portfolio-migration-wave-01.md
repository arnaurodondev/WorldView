> **STATUS: IMPLEMENTED** — All tasks in this wave have been completed and merged. See git history for implementation evidence.

# Execution Prompt 0002 — portfolio-migration wave 01

## Context (read first)

- Planning prompt: `docs/ai-interactions/agent-planning/0002-portfolio-migration-detailed-plan-and-atomic-tasks.md`
- Response (authoritative backlog): `docs/ai-interactions/agent-responses/0002-response-20260306-portfolio-migration-plan.md`

## Assigned agent profile(s)

- `./claude/agents/backend-engineer.md`
- `./claude/agents/architecture-decision-lead.md`

## Mandatory pre-read

- `AGENTS.md`
- `CLAUDE.md`
- `docs/services/portfolio.md`
- `docs/libs/messaging.md`
- `docs/libs/observability.md`
- `docs/libs/common.md`
- `docs/ai-interactions/agent-planning/0002-portfolio-migration-detailed-plan-and-atomic-tasks.md`
- `docs/ai-interactions/agent-responses/0002-response-20260306-portfolio-migration-plan.md`

## Objective

Establish all shared-library and portfolio domain foundations required by every subsequent wave. This wave builds the full `libs/messaging` stack (consumer error hierarchy, serializer, producer, outbox dispatcher base, Valkey client), the `libs/observability` metrics and tracing modules, fills missing `libs/common` tests, and implements the portfolio domain layer's zero-dependency components (enums, value objects, entities, events, errors) plus the DB session factory and portfolio settings — giving Wave 02 a complete, tested base to build application, infrastructure, and API layers on top of.

## Task scope for this wave

### Parallel group(s)

**Group A — Independent library foundations (all have zero prerequisites):**

| Task | Title | Layer |
|------|-------|-------|
| TASK-045 | Update pyproject.toml dependencies | infra |
| TASK-001 | BaseKafkaConsumer + consumer error hierarchy | libs/messaging |
| TASK-002 | SchemaRegistryClient + Avro serializer builder | libs/messaging |
| TASK-005 | ValkeyClient async Redis wrapper | libs/messaging |
| TASK-006 | Prometheus metrics + FastAPI middleware | libs/observability |
| TASK-007 | OpenTelemetry tracing setup | libs/observability |
| TASK-008 | Unit tests for libs/common ids + types | libs/common |
| TASK-009 | Portfolio domain enums | domain |
| TASK-010 | Money, InstrumentKey, Quantity value objects | domain |
| TASK-013 | Domain error hierarchy | domain |
| TASK-023 | Async DB session factory | infrastructure |
| TASK-026 | Complete portfolio settings | infrastructure |

### Sequential group(s)

**Group B — Depends on Group A within this wave:**

- `TASK-003` (Kafka producer factory) → after `TASK-002`
- `TASK-004` (BaseOutboxDispatcher) → after `TASK-003`
- `TASK-011` (Domain entities) → after `TASK-009` AND `TASK-010`
- `TASK-012` (DomainEvent base + 9 concrete events + InstrumentRefCreated) → after `TASK-009`

Execution order within Group B:
1. Start `TASK-003` as soon as `TASK-002` is complete.
2. Start `TASK-004` as soon as `TASK-003` is complete.
3. Start `TASK-011` as soon as `TASK-009` and `TASK-010` are both complete.
4. Start `TASK-012` as soon as `TASK-009` is complete (`TASK-011` not required as pre-condition).

## Why this chunk

All 16 tasks in this wave have either zero external prerequisites or depend only on other tasks within the same wave. The wave is split into two coherent tracks that can proceed in parallel:

- **Track A (libs)**: `TASK-045` → `TASK-001` / `TASK-002` → `TASK-003` → `TASK-004` / `TASK-005` / `TASK-006` / `TASK-007` / `TASK-008` form the complete shared-library foundation.
- **Track B (domain + infra scaffolding)**: `TASK-009` / `TASK-010` / `TASK-013` → `TASK-011` / `TASK-012` / `TASK-023` / `TASK-026` lay down the pure domain layer and DB session with no framework coupling.

No downstream tasks from Wave 02 or Wave 03 can start until both tracks complete, so front-loading them maximises parallelism in subsequent waves.

## Implementation instructions

Execute **only** the task IDs listed in this wave. Follow the detailed steps in the response file for each task; what follows is a concise per-task reference.

### TASK-045 — pyproject.toml dependencies

1. `libs/messaging/pyproject.toml` — add: `confluent-kafka`, `fastavro`, `redis[hiredis]`, `pydantic-settings`.
2. `libs/observability/pyproject.toml` — add: `prometheus-client`, `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-grpc`, `opentelemetry-instrumentation-fastapi`, `structlog` (if not already present).
3. `services/portfolio/pyproject.toml` — add path deps for all five libs (`common`, `contracts`, `messaging`, `observability`, `storage`). Add `testcontainers[postgres]` to `[project.optional-dependencies] dev`.
4. Verify `uv pip install -e .` succeeds for each affected package.

### TASK-001 — BaseKafkaConsumer + consumer error hierarchy

1. Create `libs/messaging/src/messaging/consumer/__init__.py`.
2. Create `libs/messaging/src/messaging/consumer/errors.py` — port `RetryableError`, `FatalError`, `DeserializationError`, `SchemaValidationError`, `ProcessingError`, `FailureInfo`. Replace `logging` import with `from observability import get_logger`.
3. Create `libs/messaging/src/messaging/consumer/base.py` — port `ConsumerConfig` (plain dataclass), `BaseKafkaConsumer` abstract class. Replace all `logging.getLogger` calls with `get_logger()`.
4. Export from `libs/messaging/src/messaging/__init__.py`.
5. Create `libs/messaging/tests/test_consumer_errors.py` — test `ConsumerConfig` defaults, error hierarchy `isinstance` checks, error `__str__` formatting.
6. Run `ruff check` and `mypy` on the new files.

### TASK-002 — SchemaRegistryClient + Avro serializer builder

1. Create `libs/messaging/src/messaging/schema_registry.py` — port `SchemaRegistryConfig`, `build_schema_registry_client()`.
2. Create `libs/messaging/src/messaging/serializer.py` — port `AvroDictable` protocol (reconcile with any definition already in `schemas.py` — keep one canonical definition, re-export from the other), `AvroSerializerConfig`, `build_avro_serializer()`, `topic_event_type_subject_name_strategy()`.
3. Create `libs/messaging/src/messaging/serialization_utils.py` — port `load_schema()` (reconcile with `schemas.py`), `serializer_for_schema()`, `iso_datetime()`, `decimal_to_str()`.
4. Create `libs/messaging/tests/test_serialization_utils.py` — test `iso_datetime` (UTC output), `decimal_to_str` (string result), `load_schema` with a fixture `.avsc` file.
5. Run `ruff check` and `mypy`.

### TASK-003 — Kafka producer factory (sequential after TASK-002)

1. Create `libs/messaging/src/messaging/producer.py` — port `KafkaProducerConfig` (plain dataclass), `build_serializing_producer()`, `OutboxKafkaValue`, `KafkaEventValueSerializer`, `OutboxEventValueSerializer`.
2. Keep `acks=all`, `enable_idempotence=True`.
3. Create `libs/messaging/tests/test_producer.py` — test `KafkaProducerConfig` defaults, `OutboxKafkaValue` construction.
4. Run `ruff check` and `mypy`.

### TASK-004 — BaseOutboxDispatcher (sequential after TASK-003)

1. Create `libs/messaging/src/messaging/dispatcher/__init__.py`.
2. Create `libs/messaging/src/messaging/dispatcher/base.py` — port `OutboxRecordProtocol`, `OutboxRepositoryProtocol`, `UnitOfWorkWithOutboxProtocol`, `DispatcherConfig`, `BaseOutboxDispatcher`, `run_dispatcher()`. Replace `logging` with `get_logger()`.
3. Create `libs/messaging/tests/test_dispatcher_config.py` — test `DispatcherConfig` defaults, worker-ID uniqueness.
4. Run `ruff check` and `mypy`.

### TASK-005 — ValkeyClient async Redis wrapper

1. Create `libs/messaging/src/messaging/valkey/__init__.py`.
2. Create `libs/messaging/src/messaging/valkey/client.py` — port `ValkeyConfig`, `ValkeyClient`, `create_valkey_client()`. Replace `logging` with `get_logger()`.
3. Create `libs/messaging/tests/test_valkey_config.py` — test config construction, URL format.
4. Run `ruff check` and `mypy`.

### TASK-006 — Prometheus metrics + FastAPI middleware

1. Create `libs/observability/src/observability/metrics.py`.
2. Define `ServiceMetrics` frozen dataclass: `requests_total` (Counter), `request_duration_seconds` (Histogram), `kafka_messages_consumed_total` (Counter), `kafka_messages_produced_total` (Counter), `outbox_dispatched_total` (Counter), `outbox_dispatch_errors_total` (Counter).
3. Implement `create_metrics(service_name: str) -> ServiceMetrics`.
4. Implement `add_prometheus_middleware(app, metrics)` using Starlette `BaseHTTPMiddleware`.
5. Expose `/metrics` route handler via `prometheus_client.generate_latest`.
6. Export all symbols from `libs/observability/src/observability/__init__.py`.
7. Create `libs/observability/tests/test_metrics.py` — test metrics creation, label validation, middleware increments request count on mock ASGI app.
8. Run `ruff check` and `mypy`.

### TASK-007 — OpenTelemetry tracing setup

1. Create `libs/observability/src/observability/tracing.py`.
2. Implement `configure_tracing(service_name: str, otlp_endpoint: str | None = None)` — `TracerProvider` setup; OTLP exporter only if `otlp_endpoint` provided; otherwise no-op.
3. Implement `get_tracer(name: str)` — wraps `opentelemetry.trace.get_tracer`.
4. Implement `add_otel_middleware(app)` — integrates `FastAPIInstrumentor`.
5. Inject `trace_id`/`span_id` into structlog context where available.
6. Export from `__init__.py`.
7. Create `libs/observability/tests/test_tracing.py` — test `configure_tracing` with no endpoint (no-op mode), `get_tracer` returns non-None tracer.
8. Run `ruff check` and `mypy`.

### TASK-008 — Unit tests for libs/common ids + types

1. Create `libs/common/tests/test_ids.py` — test `new_uuid` returns `UUID`, `new_uuid_str` returns string matching UUID regex, `new_ulid` returns string, sequential `new_ulid` calls produce lexicographically ordered strings.
2. Create `libs/common/tests/test_types.py` — test each `NewType` alias wraps its base type, `JsonDict` accepted as `dict[str, Any]`.
3. Run `cd libs/common && python -m pytest tests/test_ids.py tests/test_types.py -v`.

### TASK-009 — Domain enums

1. Create `services/portfolio/src/portfolio/domain/__init__.py` (empty with docstring).
2. Create `services/portfolio/src/portfolio/domain/enums.py` — implement `TenantStatus`, `UserStatus`, `PortfolioStatus`, `TransactionType`, `TransactionDirection`, `OutboxStatus`, `IdempotencyState` matching legacy values.
3. Run `ruff check` and `mypy` on the file.

### TASK-010 — Value objects (parallel with TASK-009)

1. Create `services/portfolio/src/portfolio/domain/value_objects.py`.
2. `Money`: frozen dataclass `(amount: Decimal, currency: str)`, arithmetic ops, currency mismatch guard, `zero(currency)`, `from_string()`.
3. `InstrumentKey`: frozen dataclass `(symbol: str, exchange: str)`, `full_symbol()`.
4. `Quantity`: frozen dataclass `(value: Decimal)`, arithmetic ops, sign checks.
5. Ensure numeric precision aligns with target spec `(18,8)`.
6. Run `ruff check` and `mypy`.

### TASK-013 — Domain error hierarchy (parallel with TASK-009/010)

1. Create `services/portfolio/src/portfolio/domain/errors.py` — port full hierarchy: `DomainError` base → `EntityNotFoundError`, `EntityAlreadyExistsError`, `ValidationError`, `AuthorizationError`, `BusinessRuleViolationError`, `ConcurrencyError`, `IdempotencyKeyConflictError`, and all subclasses. Keep `error_code`, `message`, `details`, `tenant_id`, `user_id` on base.
2. Run `ruff check` and `mypy`.

### TASK-011 — Domain entities (sequential after TASK-009 + TASK-010)

1. Create `services/portfolio/src/portfolio/domain/entities/__init__.py`.
2. Create one file per entity: `tenant.py`, `user.py`, `portfolio.py`, `transaction.py`, `holding.py`, `instrument.py`.
3. Key adaptations from legacy:
   - Use `new_uuid()` from `common.ids` (UUIDv7) instead of `uuid4()`.
   - `Portfolio`: replace `user_id + created_by_user_id` with single `owner_id`.
   - `Portfolio` unique constraint: `(owner_id, name)`.
   - Use `Decimal` directly for quantities/prices; precision `(18,8)`.
   - Keep methods: `Tenant.is_active()`, `Portfolio.rename()`, `Portfolio.archive()`, `Holding.apply_delta()`, `Transaction.gross_amount()`, `Transaction.net_amount()`.
   - `InstrumentRef`: keep `source_event_id` for idempotent consumer.
4. Run `ruff check` and `mypy`.

### TASK-012 — DomainEvent base + concrete events (sequential after TASK-009)

1. Create `services/portfolio/src/portfolio/domain/events.py`.
2. Port `DomainEvent` ABC with envelope fields: `EVENT_TYPE`, `AGGREGATE_TYPE`, `schema_version`, `event_id` (default `new_uuid()`), `occurred_at` (UTC default), `correlation_id`, `causation_id`, `tenant_id`, abstract `aggregate_id`.
3. Port all 9 legacy events: `TenantCreated`, `UserCreated`, `PortfolioCreated` (**enable — was commented out in legacy**), `PortfolioRenamed`, `PortfolioArchived`, `TransactionRecorded`, `HoldingChanged`, `TenantStatusChanged`, `UserStatusChanged`.
4. Add new event: `InstrumentRefCreated` with fields `instrument_id`, `symbol`, `exchange`, `name`, `asset_class`, `currency`.
5. Run `ruff check` and `mypy`.

### TASK-023 — Async DB session factory (parallel with domain tasks)

1. Create `services/portfolio/src/portfolio/infrastructure/__init__.py`.
2. Create `services/portfolio/src/portfolio/infrastructure/db/__init__.py`.
3. Create `services/portfolio/src/portfolio/infrastructure/db/session.py` — implement `create_session_factory(url: str)` returning `(AsyncEngine, async_sessionmaker)`.
4. Run `ruff check` and `mypy`.

### TASK-026 — Complete portfolio settings (parallel with domain tasks)

1. Extend `services/portfolio/src/portfolio/config.py` — add all fields from legacy plus new ones: `service_name`, `kafka_schema_registry_url`, `kafka_schema_registry_basic_auth`, `kafka_auto_register_schemas`, `dispatcher_immediate_batch_size`, `dispatcher_poll_interval_seconds`, `dispatcher_lease_seconds`, `dispatcher_max_attempts`, `dispatcher_backoff_base_seconds`, `topic_portfolio_events`, `topic_instrument_created`, `topic_instrument_updated`, `consumer_group_instrument`, `log_level`, `log_format`, `otlp_endpoint`.
2. Update `services/portfolio/configs/dev.local.env.example` with all new vars and example values.
3. Update `services/portfolio/configs/prod.env.example`.
4. Create `services/portfolio/tests/unit/test_config.py` — test defaults and env override behavior.
5. Run `ruff check` and `mypy`.

## Constraints

- Do not implement any task outside those listed in this wave (TASK-001–TASK-013, TASK-023, TASK-026, TASK-045).
- Do not start TASK-003 before TASK-002 is complete and validated.
- Do not start TASK-004 before TASK-003 is complete and validated.
- Do not start TASK-011 before TASK-009 and TASK-010 are both complete.
- Do not start TASK-012 before TASK-009 is complete.
- `AvroDictable` must have exactly one canonical definition after TASK-002 — reconcile with any existing `schemas.py` content.
- Use `structlog` exclusively via `observability.get_logger()` — never `print()` or stdlib `logging`.
- All entity IDs use UUIDv7 via `common.ids.new_uuid()`.
- All timestamps are UTC via `common.time` helpers.

## Scope & token budget (mandatory)

- `write_paths` are limited to this wave's declared task scope and target paths.
- If a required edit falls outside scope, stop and record a `Scope Exception` in handoff evidence before continuing.
- Maximum exploration pass before first edit: 8 files.
- Reuse already-read context in the same wave; avoid re-reading unchanged docs/files.

## Incremental quality gates (mandatory)

For each task ID, before moving to the next task, run and pass:

1. Targeted test command(s) for the task's changed behavior.
2. `ruff check` on changed paths only.
3. `mypy` on changed package/module only.

- No deferred fixes: do not carry ruff/mypy/test failures into later tasks.
- If the same failure repeats twice, capture root cause + remediation in handoff evidence.

## Required tests

```bash
# libs/messaging
cd libs/messaging && python -m pytest tests/test_consumer_errors.py tests/test_serialization_utils.py tests/test_producer.py tests/test_dispatcher_config.py tests/test_valkey_config.py -v
ruff check libs/messaging/src
mypy libs/messaging/src

# libs/observability
cd libs/observability && python -m pytest tests/test_metrics.py tests/test_tracing.py -v
ruff check libs/observability/src
mypy libs/observability/src

# libs/common
cd libs/common && python -m pytest tests/test_ids.py tests/test_types.py -v
ruff check libs/common/src
mypy libs/common/src

# services/portfolio (domain + config)
cd services/portfolio && python -m pytest tests/unit/test_config.py -v
ruff check services/portfolio/src
mypy services/portfolio/src
```

**Pass criteria:**
- All test commands exit 0.
- `ruff check` reports 0 errors for all touched packages.
- `mypy` reports 0 errors in strict mode for all touched packages.
- `uv pip install -e .` succeeds for `libs/messaging`, `libs/observability`, `services/portfolio`.
- All 16 tasks marked complete.

## Documentation requirements

**Likely impacted files:**

| File | Update condition |
|------|-----------------|
| `docs/libs/messaging.md` | Mark consumer, serializer, producer, dispatcher, Valkey sections as implemented; update public API table. |
| `docs/libs/observability.md` | Mark metrics and tracing sections as implemented; add `ServiceMetrics` fields reference. |
| `docs/libs/common.md` | Update test coverage status for `ids.py` and `types.py`. |
| `services/portfolio/configs/dev.local.env.example` | Updated by TASK-026 with all new vars. |
| `services/portfolio/configs/prod.env.example` | Updated by TASK-026 with all new vars. |

**Mandatory rule**: In this same wave, update every doc listed above for any behavior/contract/config/schema/API/test-surface change. List the exact file paths changed in your handoff evidence.

## Required handoff evidence

Provide the following before closing this wave:

1. **Completed task IDs** — list of all 16 task IDs confirmed done.
2. **Changed files** — full list of created or modified files with brief description.
3. **Test results** — paste (or summarise) the output of each test command with pass/fail status.
4. **Docs changed** — exact file paths + one-sentence summary of each update made.
5. **Unresolved blockers** — any assumptions made, conflicts found, or items deferred.
6. **Commit message proposal:**

```
feat(libs+portfolio): messaging stack, observability modules, domain foundations (wave-01)

Implement BaseKafkaConsumer, producer, BaseOutboxDispatcher, ValkeyClient, Prometheus metrics,
OpenTelemetry tracing, and the full portfolio domain layer (enums, value objects, entities,
events, errors); add missing common lib tests and complete portfolio settings.
All unit tests pass; ruff and mypy strict clean across libs/messaging, libs/observability,
libs/common, and services/portfolio domain.
```

## Definition of done

- [ ] TASK-001: `BaseKafkaConsumer` and error hierarchy importable from `messaging.consumer`; unit tests pass.
- [ ] TASK-002: `SchemaRegistryClient`, `build_avro_serializer`, serialization utils importable; unit tests pass.
- [ ] TASK-003: `KafkaProducerConfig`, `build_serializing_producer`, `OutboxKafkaValue` importable; unit tests pass.
- [ ] TASK-004: `BaseOutboxDispatcher`, `DispatcherConfig`, `run_dispatcher` importable; unit tests pass.
- [ ] TASK-005: `ValkeyClient`, `ValkeyConfig`, `create_valkey_client` importable; unit tests pass.
- [ ] TASK-006: `create_metrics`, `ServiceMetrics`, `add_prometheus_middleware` importable; middleware records HTTP metrics; unit tests pass.
- [ ] TASK-007: `configure_tracing`, `get_tracer`, `add_otel_middleware` importable; tests pass.
- [ ] TASK-008: `test_ids.py` and `test_types.py` both pass; 100% coverage on `ids.py` and `types.py`.
- [ ] TASK-009: All 7 enums importable from `portfolio.domain.enums`.
- [ ] TASK-010: `Money`, `InstrumentKey`, `Quantity` importable; frozen and passing ruff/mypy.
- [ ] TASK-011: All 6 entities importable from `portfolio.domain.entities`; `owner_id` used; UUIDv7 IDs.
- [ ] TASK-012: 10 event types importable (`PortfolioCreated` enabled; `InstrumentRefCreated` added).
- [ ] TASK-013: 15+ error classes importable with correct hierarchy.
- [ ] TASK-023: `create_session_factory(url)` returns engine + sessionmaker; ruff/mypy clean.
- [ ] TASK-026: All settings fields present; example config files updated; `test_config.py` passes.
- [ ] TASK-045: All affected `pyproject.toml` files updated; `uv pip install -e .` succeeds.
- [ ] Documentation updates completed for all impacted files listed above (or explicit N/A with justification).
- [ ] Commit message proposal included in handoff.
