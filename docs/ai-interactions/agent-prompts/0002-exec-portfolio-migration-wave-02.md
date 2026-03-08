# Execution Prompt 0002 — portfolio-migration wave 02

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
- `docs/ai-interactions/agent-planning/0002-portfolio-migration-detailed-plan-and-atomic-tasks.md`
- `docs/ai-interactions/agent-responses/0002-response-20260306-portfolio-migration-plan.md`

**Also verify Wave 01 is fully complete** before starting this wave. All outputs of TASK-001–013, TASK-023, TASK-026, TASK-045 must be importable and passing ruff/mypy.

## Objective

Build every layer of the Portfolio service from the domain package through to the deployed API, wiring together all components produced in Wave 01. This wave covers: domain package exports + domain unit tests, all application use cases, all infrastructure DB models/repositories/UoW, all API schemas/error-handling/routes with DI, the full messaging layer (Avro schemas, event mappers, outbox serialization, concrete dispatcher + main entry point, instrument consumer), and the Alembic initial migration. After this wave the service is feature-complete and runnable end-to-end against a local database.

## Task scope for this wave

### Parallel group(s)

**Level 1 — All start immediately (depend only on Wave 01 outputs):**

| Task | Title | Prerequisites |
|------|-------|--------------|
| TASK-014 | Domain package exports | TASK-009–013 (all Wave 01) |
| TASK-022 | SQLAlchemy ORM models | TASK-009 (Wave 01) |
| TASK-027 | Pydantic API schemas | TASK-009 (Wave 01) |
| TASK-030 | Avro schema files (.avsc) | TASK-012 (Wave 01) |
| TASK-031 | Topic routing + event mappers | TASK-012 (Wave 01) |

### Sequential group(s)

**Level 2 — Run in parallel, each after its listed Level-1 prerequisite:**

| Task | Title | Prerequisite(s) |
|------|-------|----------------|
| TASK-015 | Domain layer unit tests | TASK-014 |
| TASK-016 | Application ports (repo ABCs + UoW ABC) | TASK-014 |
| TASK-028 | API error handling | TASK-013 (W01) + TASK-027 |
| TASK-032 | Outbox serialization + OutboxDispatcher | TASK-004 (W01) + TASK-030 + TASK-031 |
| TASK-035 | Alembic: wire metadata + initial migration | TASK-022 |

**Level 3 — After Level-2 prerequisites satisfied:**

| Task | Title | Prerequisite(s) |
|------|-------|----------------|
| TASK-017 | Use cases: tenant | TASK-016 |
| TASK-021 | Use cases: read models + instrument | TASK-016 |
| TASK-024 | DB repositories (8 concrete) | TASK-016 + TASK-022 |
| TASK-033 | dispatcher_main entry point | TASK-032 |

**Level 4 — After Level-3:**

| Task | Title | Prerequisite(s) |
|------|-------|----------------|
| TASK-018 | Use cases: user | TASK-017 |
| TASK-025 | SqlAlchemyUnitOfWork | TASK-023 (W01) + TASK-024 |

**Level 5 — After Level-4:**

| Task | Title | Prerequisite(s) |
|------|-------|----------------|
| TASK-019 | Use cases: portfolio operations | TASK-018 |
| TASK-034 | InstrumentEventConsumer | TASK-001 (W01) + TASK-024 + TASK-025 |

**Level 6 — After Level-5:**

| Task | Title | Prerequisite(s) |
|------|-------|----------------|
| TASK-020 | Use cases: record transaction + idempotency | TASK-019 |

**Level 7 — After Level-6 (final task in this wave):**

| Task | Title | Prerequisite(s) |
|------|-------|----------------|
| TASK-029 | API routes + DI | TASK-025 + TASK-017–021 + TASK-027 + TASK-028 + TASK-020 |

## Why this chunk

All 20 tasks in this wave depend on at least one Wave 01 output and are prerequisites for Wave 03 tasks. The wave is structured as 7 progressive dependency levels that naturally pipeline: the domain package (Level 1) unlocks ports (Level 2) which unlock use cases (Levels 3–6) which unlock the API layer (Level 7). The three parallel tracks — application use cases, infrastructure DB, and messaging — have no inter-track dependencies until Level 7 where they converge at the API routes. Keeping all of them in one wave minimises cross-wave file churn (e.g., `app.py` and `conftest.py` in Wave 03 need everything assembled here) and allows an agent to verify the full service stack in a single context.

## Implementation instructions

Execute **only** the task IDs listed in this wave. Follow the detailed steps in the response file for each task; what follows is a concise per-task reference.

### TASK-014 — Domain package exports

1. `services/portfolio/src/portfolio/domain/__init__.py` — module docstring only; do not pollute namespace.
2. `services/portfolio/src/portfolio/domain/entities/__init__.py` — re-export all 6 entities: `Tenant`, `User`, `Portfolio`, `Transaction`, `Holding`, `InstrumentRef`.
3. Verify: `from portfolio.domain.entities import Tenant, User, Portfolio, Transaction, Holding, InstrumentRef` imports without error.
4. Run `ruff check` and `mypy`.

### TASK-015 — Domain layer unit tests

1. Create `services/portfolio/tests/unit/__init__.py`.
2. `test_domain_entities.py` — port from legacy; adapt `owner_id` field name; test `is_active()`, `rename()`, `archive()`, `apply_delta()`, `gross_amount()`, `net_amount()`, `source_event_id`.
3. `test_value_objects.py` — `Money` arithmetic, currency-mismatch raises, `zero()`, `from_string()`; `InstrumentKey.full_symbol()`; `Quantity` arithmetic, sign checks.
4. `test_domain_events.py` — creation, correct `aggregate_id`, `schema_version`, frozen constraint, `InstrumentRefCreated` fields, `PortfolioCreated` enabled.
5. `test_domain_errors.py` — `isinstance` checks across hierarchy, `error_code` values.
6. Run `cd services/portfolio && python -m pytest tests/unit/ -v`; target >90% coverage on `domain/`.

### TASK-016 — Application ports

1. Create `services/portfolio/src/portfolio/application/__init__.py`.
2. Create `services/portfolio/src/portfolio/application/ports/__init__.py`.
3. `application/ports/repositories.py` — 8 repository ABCs: `TenantRepository`, `UserRepository`, `PortfolioRepository`, `InstrumentRepository`, `TransactionRepository`, `HoldingRepository`, `OutboxRepository`, `IdempotencyRepository`. Include DTOs `OutboxRecord`, `IdempotencyRecord`. Adapt field names to target schema (`owner_id`, simplified idempotency).
4. `application/ports/unit_of_work.py` — `UnitOfWork` ABC: all 8 repo properties, `async commit()`, `async rollback()`, `async __aenter__` / `async __aexit__`.
5. Run `ruff check` and `mypy`.

### TASK-022 — SQLAlchemy ORM models

1. Create `services/portfolio/src/portfolio/infrastructure/db/models/__init__.py` with `Base = declarative_base()`.
2. Create one model file per table: `tenant.py`, `user.py`, `portfolio.py`, `transaction.py`, `holding.py`, `instrument.py`, `outbox.py`, `idempotency.py`.
3. Key target-spec differences from legacy:
   - `Portfolio`: `owner_id` (not `user_id + created_by_user_id`); unique constraint `(owner_id, name)`.
   - Numeric precision: `NUMERIC(18, 8)` everywhere (not `20,8`).
   - `outbox_events.payload`: `JSONB` (not `LargeBinary`).
   - `idempotency` table: simplified to `(event_id UUID PK, processed_at TIMESTAMPTZ)` for consumer idempotency.
   - Add `created_at` / `updated_at` with server defaults.
4. Add indexes per `docs/services/portfolio.md` schema section.
5. Re-export `Base` and all model classes from `models/__init__.py`.
6. Run `ruff check` and `mypy`.

### TASK-027 — Pydantic API schemas

1. Create `services/portfolio/src/portfolio/api/__init__.py`.
2. Create `services/portfolio/src/portfolio/api/schemas.py` with: `TenantCreateRequest`, `TenantResponse`, `UserCreateRequest`, `UserResponse`, `PortfolioCreateRequest`, `PortfolioResponse`, `PortfolioRenameRequest`, `RecordTransactionRequest`, `RecordTransactionResponse`, `HoldingResponse`, `TransactionListItem`, `InstrumentResponse`, `ErrorResponse`.
3. Use target-spec field names (`owner_user_id`, etc. per `docs/services/portfolio.md`).
4. Add Pydantic validators: currency codes uppercase 3-char, `quantity > 0`, `price > 0`.
5. Create `services/portfolio/tests/unit/test_api_schemas.py` — test invalid currency, negative quantity, missing required fields raise `ValidationError`.
6. Run `ruff check` and `mypy`.

### TASK-030 — Avro schema files

1. Create `services/portfolio/src/portfolio/messaging/schemas/` directory.
2. Port existing `.avsc` files from legacy: `transaction.recorded.avsc`, `user.created.avsc`, `tenant.created.avsc`.
3. Create new schemas (use namespace `portfolio.events`; include all envelope fields per AGENTS.md §9): `portfolio.created.avsc`, `portfolio.renamed.avsc`, `portfolio.archived.avsc`, `holding.changed.avsc`, `instrument_ref.created.avsc`.
4. Validate all 8 files are valid JSON parseable by `fastavro.parse_schema`.
5. Ensure all schemas are forward-compatible: new fields have defaults; no removals or renames.

### TASK-031 — Topic routing + event mappers

1. Create `services/portfolio/src/portfolio/messaging/__init__.py`.
2. `messaging/topics.py` — single outbound topic `PORTFOLIO_EVENTS_V1 = "portfolio.events.v1"` + routing dict mapping all 10 event `EVENT_TYPE` strings to topic.
3. `messaging/mapper.py` — implement `event_to_envelope_dict()` + per-event serialization mappers: `transaction_recorded_to_dict()`, `user_created_to_dict()`, `tenant_created_to_dict()`, `portfolio_created_to_dict()`, `portfolio_renamed_to_dict()`, `portfolio_archived_to_dict()`, `holding_changed_to_dict()`, `instrument_ref_created_to_dict()`.
4. Create `services/portfolio/tests/unit/test_mappers.py` — test each mapper produces expected dict keys and correct `event_type` value.
5. Run `ruff check` and `mypy`.

### TASK-028 — API error handling (after TASK-027)

1. `api/error_mapping.py` — map domain error classes to HTTP status: `EntityNotFoundError→404`, `AuthorizationError→403`, `ValidationError→422`, `BusinessRuleViolationError→409`, `IdempotencyKeyConflictError→409`, `ConcurrencyError→409`, fallback→500.
2. `api/exception_handlers.py` — `domain_error_handler(request, exc: DomainError)` returns `JSONResponse(status_code, ErrorResponse)`; `unhandled_exception_handler` returns 500 with structured log at ERROR level using `get_logger()`.
3. Create `services/portfolio/tests/unit/test_api_error_handlers.py` — test each domain error subclass maps to correct HTTP status code.
4. Run `ruff check` and `mypy`.

### TASK-032 — Outbox serialization + concrete OutboxDispatcher (after TASK-004 W01 + TASK-030 + TASK-031)

1. `messaging/serialization.py` — `build_outbox_event_serializers()` → `dict[str, AvroSerializer]` mapping `event_type` → Avro serializer; `headers_for_event(event_type)` → Kafka headers list.
2. `messaging/outbox_mapper.py` — identity mapper for pre-serialized payloads.
3. `messaging/dispatcher.py` — `OutboxDispatcher(BaseOutboxDispatcher)`: implement `_build_producer()` using `build_serializing_producer()` and settings; implement `_produce_record(record, producer)` using route lookup + serializer + headers. Factory function `create_dispatcher(settings, session_factory)`.
4. Create `services/portfolio/tests/unit/test_serialization.py` — test `headers_for_event` returns correct content-type; test identity outbox mapper.
5. Run `ruff check` and `mypy`.

### TASK-035 — Alembic: wire metadata + initial migration (after TASK-022)

1. Update `services/portfolio/alembic/env.py` — import `Base` from `portfolio.infrastructure.db.models`, set `target_metadata = Base.metadata`. Ensure async engine usage (`run_async_migrations`).
2. Run: `cd services/portfolio && alembic revision --autogenerate -m "initial_schema"`.
3. Review generated file in `alembic/versions/` — verify all 8 tables, correct numeric precision `(18, 8)`, JSONB outbox payload, simplified idempotency table, correct indexes.
4. Fix any autogenerate gaps manually (e.g., CHECK constraints, partial indexes, JSONB type declarations).
5. Test: `alembic upgrade head` on a clean Postgres instance (testcontainers or local Docker).
6. Test: `alembic downgrade base` succeeds.

### TASK-017 — Use cases: tenant (after TASK-016)

1. Create `services/portfolio/src/portfolio/application/use_cases/__init__.py`.
2. `use_cases/tenant.py` — `CreateTenantCommand` (dataclass), `CreateTenantUseCase.execute(cmd, uow)`: create `Tenant`, emit `TenantCreated` to outbox via UoW, return tenant. `GetTenantUseCase.execute(tenant_id, uow)`: get or raise `EntityNotFoundError`.
3. Replace any `uuid4()` usage with `new_uuid()` from `common.ids`.
4. Use `get_logger()` with `tenant_id` bind.
5. Run `ruff check` and `mypy`.

### TASK-021 — Use cases: read models + instrument (after TASK-016)

1. `use_cases/read_models.py` — `GetHoldingsUseCase`, `ListTransactionsUseCase` — both perform ownership check; return list or raise `AuthorizationError`.
2. `use_cases/instrument.py` — `GetInstrumentUseCase(symbol, exchange)`, `GetInstrumentByIdUseCase(instrument_id)`. Remove `UpsertInstrumentUseCase` (instruments only come from Kafka).
3. Run `ruff check` and `mypy`.

### TASK-024 — DB repositories (after TASK-016 + TASK-022)

1. Create `services/portfolio/src/portfolio/infrastructure/db/repositories/__init__.py`.
2. Implement all 8 concrete repositories (one file each): `SqlAlchemyTenantRepository`, `SqlAlchemyUserRepository`, `SqlAlchemyPortfolioRepository`, `SqlAlchemyTransactionRepository`, `SqlAlchemyHoldingRepository`, `SqlAlchemyInstrumentRepository`, `SqlAlchemyOutboxRepository`, `SqlAlchemyIdempotencyRepository`.
3. Key implementation notes:
   - All SELECT/UPDATE/DELETE queries must filter by `tenant_id`.
   - `HoldingRepository.upsert_many` — use `uuid5` deterministic PK.
   - `InstrumentRepository.upsert` — `INSERT ... ON CONFLICT DO UPDATE`.
   - `OutboxRepository.claim_batch` — `SELECT ... FOR UPDATE SKIP LOCKED LIMIT n`; returns list of unclaimed `OutboxRecord`s. Payload is stored as JSONB.
   - `IdempotencyRepository` — `exists(event_id: UUID) -> bool`; `record(event_id, processed_at)`.
4. Each repo implements its ABC from `application/ports/repositories.py`.
5. Run `ruff check` and `mypy`.

### TASK-033 — dispatcher_main entry point (after TASK-032)

1. `messaging/dispatcher_main.py` — `asyncio.run(main())` with SIGTERM/SIGINT signal handlers, graceful shutdown via `asyncio.Event`. Load settings via `Settings()`, call `configure_logging()` from observability, create `OutboxDispatcher` via `create_dispatcher()`, call `run_dispatcher(dispatcher, stop_event)`.
2. Verify `python -m portfolio.messaging.dispatcher_main` exits cleanly (within ~2s) when no Kafka is available (handles connection error gracefully without stack trace).
3. Update `docs/services/portfolio.md` background-jobs table with dispatcher entry point.
4. Run `ruff check` and `mypy`.

### TASK-018 — Use cases: user (after TASK-017)

1. `use_cases/user.py` — `CreateUserCommand`, `CreateUserUseCase.execute`: validate tenant active (raise `BusinessRuleViolationError` if not), check email unique (raise `EntityAlreadyExistsError` if not), create `User`, emit `UserCreated` outbox event. `GetUserUseCase.execute`: get or raise `EntityNotFoundError`.
2. Run `ruff check` and `mypy`.

### TASK-025 — SqlAlchemyUnitOfWork (after TASK-023 W01 + TASK-024)

1. `infrastructure/db/unit_of_work.py` — `SqlAlchemyUnitOfWork(UnitOfWork)`: `__aenter__` creates session + instantiates all 8 repos; `commit()` calls `session.commit()` then fires `on_commit()` callback if outbox events were added; `rollback()` calls `session.rollback()`; `__aexit__` handles commit/rollback based on exception.
2. Create `services/portfolio/tests/unit/test_unit_of_work.py` — test `on_commit` called when outbox has events; test `on_commit` not called after rollback.
3. Run `ruff check` and `mypy`.

### TASK-019 — Use cases: portfolio operations (after TASK-018)

1. `use_cases/create_portfolio.py` — `CreatePortfolioCommand`, `CreatePortfolioUseCase`: validate tenant + user active, create `Portfolio` with `owner_id`, **emit `PortfolioCreated` outbox event** (this was commented out in legacy — must be enabled).
2. `use_cases/portfolio_ops.py` — `GetPortfolioUseCase` (ownership check), `ListPortfoliosUseCase`, `ArchivePortfolioUseCase` (emit `PortfolioArchived`), `RenamePortfolioCommand` + `RenamePortfolioUseCase` (ownership check, call `portfolio.rename()`, emit `PortfolioRenamed`). `RenamePortfolio` is new — no legacy reference; derive from `Portfolio.rename()` method.
3. Run `ruff check` and `mypy`.

### TASK-034 — InstrumentEventConsumer (after TASK-001 W01 + TASK-024 + TASK-025)

1. Create `services/portfolio/src/portfolio/consumers/__init__.py`.
2. `consumers/instrument_consumer.py` — `InstrumentEventConsumer(BaseKafkaConsumer)`:
   - Consumer group: `portfolio-instrument-sync`.
   - Topics: `market.instrument.created`, `market.instrument.updated`.
   - Implements `create_uow()` → creates `SqlAlchemyUnitOfWork` with session from app state.
   - Implements `process_message(msg, uow)` → upsert `InstrumentRef` via `InstrumentRepository.upsert`.
   - Implements `is_duplicate(event_id, uow)` → checks `IdempotencyRepository.exists(event_id)`.
   - Implements `mark_processed(event_id, uow)` → calls `IdempotencyRepository.record(event_id)`.
   - Uses `get_logger()` with `topic`, `event_id`, `symbol` fields bound.
3. Create `services/portfolio/tests/unit/test_instrument_consumer.py` — test `process_message` creates instrument via fake UoW; test duplicate detection returns early without upsert.
4. Verify `docs/services/portfolio.md` consumed-topics table matches `market.instrument.created` and `market.instrument.updated` with consumer group `portfolio-instrument-sync`.
5. Run `ruff check` and `mypy`.

### TASK-020 — Use cases: record transaction (after TASK-019)

1. `use_cases/record_transaction.py` — `RecordTransactionCommand` (dataclass with all fields per target spec), `RecordTransactionUseCase.execute(cmd, uow)`:
   - Idempotency check: if key already processed, return stored result.
   - Validate portfolio ownership + user active + tenant active.
   - Validate currency matches portfolio base currency.
   - Resolve instrument by `InstrumentKey`.
   - Create `Transaction`.
   - Update `Holding` via `apply_delta()` (create if not exists).
   - Emit `TransactionRecorded` + `HoldingChanged` outbox events in single `uow.commit()`.
   - Store idempotency result.
   - All in one atomic UoW block.
2. Use `get_logger()` with `correlation_id`, `portfolio_id`, `tenant_id`.
3. Verify Decimal precision `(18, 8)` throughout.
4. Run `ruff check` and `mypy`.

### TASK-029 — API routes + DI (after TASK-025 + TASK-017–021 + TASK-027 + TASK-028 + TASK-020)

1. `api/dependencies.py` — `uow_dep()`: `Depends` factory that creates `SqlAlchemyUnitOfWork` from `request.app.state.session_factory`; stores dispatcher `on_commit` hook.
2. Create `api/routes/__init__.py`.
3. Implement route files (one per resource), all under `/api/v1/` prefix:
   - `api/routes/tenant.py` — `POST /api/v1/tenants`, `GET /api/v1/tenants/{tenant_id}`.
   - `api/routes/user.py` — `POST /api/v1/users`, `GET /api/v1/users/{user_id}`.
   - `api/routes/portfolio.py` — `POST /api/v1/portfolios`, `GET /api/v1/portfolios` (list), `GET /api/v1/portfolios/{portfolio_id}`, `PUT /api/v1/portfolios/{portfolio_id}` (rename — new), `DELETE /api/v1/portfolios/{portfolio_id}` (archive — new route).
   - `api/routes/transaction.py` — `POST /api/v1/transactions` (read `Idempotency-Key` header), `GET /api/v1/transactions`.
   - `api/routes/holding.py` — `GET /api/v1/holdings/{portfolio_id}`.
   - `api/routes/instrument.py` — `GET /api/v1/instruments` (list — new endpoint), `GET /api/v1/instruments/{instrument_id}`.
4. Each route handler: extracts `tenant_id` from header or path, passes to use case via command, returns appropriate HTTP status (201 for creates, 200 for reads, 204 for archive).
5. Register all 6 routers in `api/routes/__init__.py` with prefix `/api/v1`.
6. Run `ruff check` and `mypy`.

## Constraints

- Do not implement any task outside those listed in this wave (TASK-014–TASK-035, excluding TASK-023 which is in Wave 01).
- Strictly follow the level ordering: never start a level-N task until all its prerequisite tasks from lower levels in this wave are complete.
- `PortfolioCreated` event **must** be enabled — not commented out as in legacy.
- All DB queries **must** include `tenant_id` filter — no exceptions.
- Use `NUMERIC(18, 8)` — not `(20, 8)` as in legacy.
- `outbox_events.payload` must be `JSONB`, not `LargeBinary`.
- Use `structlog` exclusively via `observability.get_logger()`.
- All entity IDs use `new_uuid()` (UUIDv7).
- All timestamps are UTC.
- Do not add `UpsertInstrumentUseCase` — instruments come from Kafka only.
- `RenamePortfolioUseCase` is new (no legacy reference) — derive behaviour from `Portfolio.rename()` entity method.

## Required tests

```bash
# Domain unit tests
cd services/portfolio && python -m pytest tests/unit/test_domain_entities.py tests/unit/test_value_objects.py tests/unit/test_domain_events.py tests/unit/test_domain_errors.py -v

# Application unit tests
cd services/portfolio && python -m pytest tests/unit/test_use_cases_tenant.py tests/unit/test_use_cases_user.py tests/unit/test_use_cases_portfolio.py tests/unit/test_use_cases_transaction.py tests/unit/test_use_cases_read_models.py -v

# Infrastructure unit tests
cd services/portfolio && python -m pytest tests/unit/test_unit_of_work.py -v

# API unit tests
cd services/portfolio && python -m pytest tests/unit/test_api_schemas.py tests/unit/test_api_error_handlers.py -v

# Messaging unit tests
cd services/portfolio && python -m pytest tests/unit/test_mappers.py tests/unit/test_serialization.py tests/unit/test_instrument_consumer.py -v

# Lint + type check
ruff check services/portfolio/src
mypy services/portfolio/src

# Verify dispatcher_main exits cleanly
cd services/portfolio && timeout 5 python -m portfolio.messaging.dispatcher_main || true

# Alembic smoke test (requires local or testcontainer Postgres)
cd services/portfolio && alembic upgrade head && alembic downgrade base
```

**Pass criteria:**
- All test files pass with 0 failures.
- `ruff check` exits 0 for `services/portfolio/src`.
- `mypy` exits 0 (strict) for `services/portfolio/src`.
- Alembic `upgrade head` creates 8 tables; `downgrade base` removes them cleanly.
- `dispatcher_main` exits without unhandled exception.

## Documentation requirements

**Likely impacted files:**

| File | Update condition |
|------|-----------------|
| `docs/services/portfolio.md` | Verify endpoint table (add PUT rename, DELETE archive, GET users, GET instruments list); verify event table (PortfolioCreated enabled; InstrumentRefCreated added); update consumed-topics table; update background-jobs table (dispatcher_main). |
| `docs/libs/messaging.md` | Mark `AvroDictable` canonical location; note reconciliation with `schemas.py`. |
| `services/portfolio/IMPLEMENTATION.md` (if exists) | Update with layer completion status. |

**Mandatory rule**: In this same wave, update every doc listed above for any behavior/contract/config/schema/API/test-surface change. List the exact file paths updated in your handoff evidence.

## Required handoff evidence

1. **Completed task IDs** — all 20 task IDs confirmed done.
2. **Changed files** — full list of created or modified files with brief description.
3. **Test results** — output summary for each test command (pass count, any skips).
4. **Alembic verification** — confirm `upgrade head` / `downgrade base` both succeeded.
5. **Docs changed** — exact file paths + one-sentence summary of each update.
6. **Unresolved blockers** — any assumptions made or deferred items.
7. **Commit message proposal:**

```
feat(portfolio): domain, application, infrastructure, API, messaging layers (wave-02)

Implement full portfolio service stack: domain package wiring + unit tests, all 12 use cases
(tenant/user/portfolio ops/record-transaction/read-models), 8 SQLAlchemy repositories + UoW,
all 14 API endpoints under /api/v1/, Avro schemas for 8 event types, OutboxDispatcher,
InstrumentEventConsumer, and Alembic initial-schema migration.
All unit tests pass; ruff and mypy strict clean; alembic upgrade/downgrade verified.
```

## Definition of done

- [ ] TASK-014: `from portfolio.domain.entities import *` resolves all 6 entities; ruff/mypy clean.
- [ ] TASK-015: Domain unit tests pass; coverage >90% for `portfolio/domain/`.
- [ ] TASK-016: All 8 repo ABCs + `UnitOfWork` ABC importable with correct signatures; mypy clean.
- [ ] TASK-017: `CreateTenantUseCase`, `GetTenantUseCase` — tests pass; `TenantCreated` emitted to outbox.
- [ ] TASK-018: `CreateUserUseCase`, `GetUserUseCase` — tests pass; inactive-tenant + duplicate-email errors validated.
- [ ] TASK-019: 5 portfolio use cases — tests pass; `PortfolioCreated` **enabled**; `RenamePortfolioUseCase` implemented.
- [ ] TASK-020: `RecordTransactionUseCase` — tests pass (BUY, SELL, idempotency, currency mismatch, insufficient holdings).
- [ ] TASK-021: 4 read-model use cases — tests pass; `UpsertInstrumentUseCase` absent.
- [ ] TASK-022: 8 ORM models with `NUMERIC(18,8)`, JSONB outbox, simplified idempotency, correct indexes; mypy clean.
- [ ] TASK-024: 8 concrete repos implementing their ABCs; all queries tenant-scoped; mypy clean.
- [ ] TASK-025: `SqlAlchemyUnitOfWork` — unit tests pass; `on_commit` hook wired.
- [ ] TASK-027: All 12 Pydantic schemas — validation tests pass.
- [ ] TASK-028: Error mapping complete; exception handler tests pass.
- [ ] TASK-029: All 14 API endpoints registered under `/api/v1/`; DI wired; ruff/mypy clean.
- [ ] TASK-030: 8 `.avsc` files valid JSON, parseable by fastavro.
- [ ] TASK-031: All 10 event types have mapper functions; routing table complete; mapper tests pass.
- [ ] TASK-032: `OutboxDispatcher` instantiable; serialization tests pass.
- [ ] TASK-033: `dispatcher_main` exits cleanly; background-jobs table in docs updated.
- [ ] TASK-034: `InstrumentEventConsumer` — unit tests pass; consumed-topics table in docs verified.
- [ ] TASK-035: Alembic `env.py` wired; initial migration creates all 8 tables; upgrade + downgrade both verified.
- [ ] Documentation updates completed for all impacted files listed above (or explicit N/A with justification).
- [ ] Commit message proposal included in handoff.
