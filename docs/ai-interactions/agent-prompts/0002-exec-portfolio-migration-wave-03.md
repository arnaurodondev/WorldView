# Execution Prompt 0002 — portfolio-migration wave 03

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
- `docs/migration/REUSE_FROM_ORIGINAL_THESIS.md`
- `docs/ai-interactions/agent-planning/0002-portfolio-migration-detailed-plan-and-atomic-tasks.md`
- `docs/ai-interactions/agent-responses/0002-response-20260306-portfolio-migration-plan.md`

**Verify Wave 01 and Wave 02 are fully complete** before starting this wave. All service layers (domain, application, infrastructure, API, messaging) must be implemented and passing ruff/mypy.

## Objective

Complete the Portfolio service migration by wiring the FastAPI app factory (lifespan, readyz probe, observability), writing all test suites (contract, integration, use-case unit tests), validating tenant isolation, producing a working Docker Compose definition, running platform-level QA scenarios end-to-end, and performing a final documentation sweep. After this wave the service is production-ready for the thesis demo stack.

## Task scope for this wave

### Parallel group(s)

**Level 1 — All start immediately after Wave 02 (no intra-wave dependencies):**

| Task | Title | Prerequisites (all Wave 01/02) |
|------|-------|-------------------------------|
| TASK-036 | App factory wiring + readyz + observability | TASK-006 W01, TASK-023 W01, TASK-025 W02, TASK-028 W02, TASK-029 W02, TASK-032 W02, TASK-034 W02 |
| TASK-037 | Avro contract tests | TASK-030 W02, TASK-031 W02 |
| TASK-038 | Integration test infrastructure | TASK-025 W02, TASK-035 W02 |
| TASK-040 | Use-case unit tests | TASK-017–021 W02 |
| TASK-046 | Security + tenant isolation audit | TASK-024 W02, TASK-029 W02 |

### Sequential group(s)

**Level 2 — Each task after its Level-1 prerequisite:**

| Task | Title | Prerequisite(s) in this wave |
|------|-------|------------------------------|
| TASK-039 | Integration tests — all API endpoints | TASK-038 (Level 1) |
| TASK-041 | Docker Compose + Dockerfile | TASK-036 (Level 1) |

**Level 3 — After Level-2:**

| Task | Title | Prerequisite(s) |
|------|-------|----------------|
| TASK-042 | QA — instrument sync cross-service | TASK-041 (Level 2), TASK-034 (W02) |
| TASK-043 | QA — full transaction flow | TASK-039 (Level 2), TASK-041 (Level 2) |

**Level 4 — Final task (after all others):**

| Task | Title | Prerequisite(s) |
|------|-------|----------------|
| TASK-044 | Documentation sweep | All TASK-001–043, TASK-046 |

## Why this chunk

All 10 tasks in this wave depend on outputs from Wave 01 or Wave 02 (or both) and have no dependencies among themselves at Level 1, enabling broad parallelism on startup. The wave closes the loop between code and confidence: TASK-038 + TASK-039 verify the API↔DB round-trip; TASK-037 verifies Avro schema contracts; TASK-040 validates use-case isolation; TASK-046 audits tenant scoping; TASK-036 completes the runnable FastAPI app; TASK-041 packages it for Docker; TASK-042/043 confirm the cross-service story works end-to-end; and TASK-044 ensures documentation matches the final implementation. Since TASK-043 is the last functional task and TASK-044 the last doc task, this wave is the natural scope boundary.

## Implementation instructions

Execute **only** the task IDs listed in this wave. Follow the detailed steps in the response file for each task; what follows is a concise per-task reference.

### TASK-036 — App factory wiring + readyz + observability

1. Update `services/portfolio/src/portfolio/app.py`:
   - **Startup (lifespan `__aenter__`)**:
     1. `configure_logging(log_level=settings.log_level, log_format=settings.log_format)`.
     2. `configure_tracing(service_name=settings.service_name, otlp_endpoint=settings.otlp_endpoint)`.
     3. `engine, sessionmaker = create_session_factory(settings.database_url)`.
     4. Store `engine` and `sessionmaker` in `app.state`.
     5. Create `OutboxDispatcher` via `create_dispatcher(settings, sessionmaker)` — store in `app.state`.
     6. Create `InstrumentEventConsumer` — store in `app.state`, start in background task.
   - **Shutdown (lifespan `__aexit__`)**:
     1. Signal consumer to stop; await clean shutdown.
     2. Stop dispatcher; await pending tasks.
     3. Dispose engine.
   - **Middleware + routes**:
     1. Register exception handlers: `domain_error_handler`, `unhandled_exception_handler`.
     2. `add_prometheus_middleware(app, create_metrics(settings.service_name))`.
     3. `add_otel_middleware(app)`.
     4. Include all API routers from `api/routes/`.
     5. Add `/metrics` GET endpoint returning `prometheus_client.generate_latest()`.
   - **`/readyz` probe update**: perform `SELECT 1` against the DB engine; return `{"status": "ok"}` on success, HTTP 503 `{"status": "unavailable", "reason": "db"}` on failure. Use `asyncio.wait_for` with 2-second timeout.
2. Update `services/portfolio/tests/test_health.py` — add `test_readyz_ok` (mock DB up) and `test_readyz_db_down` (mock DB connection raises).
3. Run `ruff check` and `mypy`.

### TASK-037 — Contract tests for Avro schemas

1. Create `services/portfolio/tests/contract/__init__.py`.
2. Port existing legacy contract tests: `test_transaction_recorded_contract.py`, `test_tenant_created_contract.py`, `test_user_created_contract.py`.
3. Add new contract tests for: `test_portfolio_created_contract.py`, `test_portfolio_renamed_contract.py`, `test_portfolio_archived_contract.py`, `test_holding_changed_contract.py`, `test_instrument_ref_created_contract.py`.
4. Each test: construct a realistic event instance → call the event's mapper function → call `fastavro.validate(dict_output, parsed_schema)` → assert no exception raised.
5. Run `cd services/portfolio && python -m pytest tests/contract/ -v`.

### TASK-038 — Integration test infrastructure

1. Update `services/portfolio/tests/conftest.py`:
   - Add `postgres_container` fixture (`scope="session"`) using `testcontainers.postgres.PostgresContainer`. Start container, run `alembic upgrade head`, yield connection URL, stop on teardown.
   - Add `db_session` fixture (`scope="function"`) — creates a real SQLAlchemy async session, wraps it in a savepoint (`SAVEPOINT sp`), yields, rolls back to savepoint after each test.
   - Add `test_session_factory` fixture returning a sessionmaker bound to the test engine.
   - Add `test_uow` fixture using `SqlAlchemyUnitOfWork` with test session factory.
   - Add `test_client` fixture: creates `TestClient(app)` with overridden `uow_dep` pointing to `test_uow`.
2. Create `services/portfolio/tests/integration/__init__.py`.
3. Create `services/portfolio/tests/integration/helpers.py`:
   - `OutboxAssertions.assert_event_type_in_outbox(session, event_type)`.
   - `make_tenant(client)`, `make_user(client, tenant_id)`, `make_portfolio(client, tenant_id, user_id)` factory helpers.
4. Ensure `testcontainers[postgres]` is in dev dependencies (set in TASK-045 Wave 01).
5. Verify container starts correctly and migrations apply cleanly.

### TASK-040 — Use-case unit tests

1. Create fake implementations of `UnitOfWork` and all repository ports (in-memory dicts) — put in `tests/unit/fakes.py`.
2. `test_use_cases_tenant.py` — happy path (tenant created, `TenantCreated` in outbox), duplicate tenant raises `EntityAlreadyExistsError`.
3. `test_use_cases_user.py` — happy path, inactive tenant raises `BusinessRuleViolationError`, duplicate email raises `EntityAlreadyExistsError`.
4. `test_use_cases_portfolio.py` — create happy path, archive, rename, list, ownership violation raises `AuthorizationError`.
5. `test_use_cases_transaction.py` — BUY happy path (holding created), SELL partial (holding updated), SELL > holding quantity raises `BusinessRuleViolationError`, currency mismatch raises `ValidationError`, idempotency replay returns same result without duplicate outbox event.
6. `test_use_cases_read_models.py` — ownership validated for holdings and transactions, empty-list case.
7. Run `cd services/portfolio && python -m pytest tests/unit/ -v --cov=portfolio.application`; target >90% application-layer coverage.

### TASK-046 — Security + tenant isolation audit

1. **Repository audit**: for each of the 8 concrete repositories, verify every `SELECT`, `UPDATE`, `DELETE` filters by `tenant_id`. Document any gaps found and fix them immediately.
2. **Route audit**: for each of the 14 route handlers, verify `tenant_id` is extracted from the request (header `X-Tenant-Id` or path parameter per spec), passed to the use case command, and that the use case forwards it to the repository.
3. **Ownership audit**: verify all holdings, transactions, and portfolios routes validate `owner_id` ownership before returning data.
4. **UTC audit**: grep for `datetime.now()` without `tz=timezone.utc` — replace any occurrences.
5. **ID audit**: grep for `uuid4()` — replace with `new_uuid()`.
6. Add cross-tenant negative tests to `tests/integration/helpers.py` and call them from at least one integration test file: attempt to GET another tenant's portfolio → expect 403.
7. Document all findings (fixes applied or "no issues found") in handoff evidence.

### TASK-039 — Integration tests for all API endpoints (after TASK-038)

1. `tests/integration/test_tenant_api.py` — `POST /api/v1/tenants` creates record in DB; `OutboxAssertions` confirms `tenant.created` event in outbox; `GET /api/v1/tenants/{id}` returns correct response; duplicate name returns 409.
2. `tests/integration/test_user_api.py` — create user; get user; inactive tenant → 422/409; duplicate email → 409.
3. `tests/integration/test_portfolio_api.py` — create; list (verify scoping); get; rename (PUT); archive (DELETE → 204); ownership violation → 403.
4. `tests/integration/test_transaction_api.py` — BUY transaction; verify `TransactionRecorded` + `HoldingChanged` in outbox; idempotency replay (same `Idempotency-Key` → same response, no duplicate outbox events); list transactions.
5. `tests/integration/test_holding_api.py` — after BUY transaction → GET holdings returns updated quantity and avg_cost.
6. `tests/integration/test_instrument_api.py` — list instruments; verify returns empty list when none exist.
7. Run `cd services/portfolio && python -m pytest tests/integration/ -v`; all tests must pass against testcontainer.

### TASK-041 — Docker Compose + Dockerfile (after TASK-036)

1. Create `services/portfolio/Dockerfile`:
   - Multi-stage build: `builder` (install deps, compile) + `runtime` (Python 3.12-slim, copy installed packages).
   - `CMD ["python", "-m", "uvicorn", "portfolio.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]`.
   - Add `HEALTHCHECK` calling `curl -f http://localhost:8000/healthz`.
2. Add `portfolio` service to `infra/compose/docker-compose.yml`:
   - `image: portfolio:latest` (or build context).
   - `ports: ["8000:8000"]`.
   - `depends_on: [postgres, kafka, schema-registry]`.
   - `healthcheck` via `/healthz`.
   - All env vars mapped from `configs/dev.local.env.example`.
   - `POSTGRES_URL` pointing to compose Postgres service.
3. Update `docs/services/portfolio.md` — Local Run section: `docker compose up portfolio`.

### TASK-042 — QA: instrument sync cross-service (after TASK-041)

1. Create `services/portfolio/tests/e2e/test_instrument_sync.py`.
2. Design test (can be pytest-based with testcontainers-compose or documented as a manual scenario):
   - Produce a `market.instrument.created` Avro event to `market.instrument.created` topic.
   - Wait for consumer to process (poll with retry up to 10s).
   - Query Portfolio DB `instruments` table — verify row exists with correct `symbol` and `exchange`.
   - Produce `market.instrument.updated` → verify update applied.
   - Produce duplicate `market.instrument.created` (same `event_id`) → verify no duplicate row (idempotent).
3. If Kafka is not available in CI, mark test with `pytest.mark.e2e` and skip in unit/integration runs.
4. Document the scenario in `docs/services/portfolio.md` QA section.

### TASK-043 — QA: full transaction flow (after TASK-039 + TASK-041)

1. Create `services/portfolio/tests/e2e/test_full_flow.py`.
2. Full happy path (can be integration-test-level with testcontainer):
   1. `POST /api/v1/tenants` → capture `tenant_id`.
   2. `POST /api/v1/users` → capture `user_id`.
   3. `POST /api/v1/portfolios` → capture `portfolio_id`; verify `PortfolioCreated` in outbox.
   4. `POST /api/v1/transactions` (BUY 10 shares AAPL @ 150.00) → verify `TransactionRecorded` + `HoldingChanged` in outbox.
   5. `GET /api/v1/holdings/{portfolio_id}` → verify quantity=10, avg_cost=150.00.
   6. `POST /api/v1/transactions` (SELL 5 shares AAPL @ 160.00) → verify holding updated.
   7. `GET /api/v1/holdings/{portfolio_id}` → verify quantity=5.
   8. `GET /api/v1/transactions` → verify 2 transactions returned.
3. Mark with `pytest.mark.e2e` for selective execution.
4. Document the QA scenario in `docs/services/portfolio.md`.

### TASK-044 — Documentation sweep (after all other tasks)

1. **`docs/services/portfolio.md`**:
   - Verify all 14 endpoint definitions match final implementation (method, path, request/response fields, HTTP status codes).
   - Verify event produced table matches all 10 event types (including `PortfolioCreated` enabled, `InstrumentRefCreated` new).
   - Verify consumed-topics table: `market.instrument.created` + `market.instrument.updated`, group `portfolio-instrument-sync`.
   - Verify DB schema section matches final 8-table layout (NUMERIC(18,8), JSONB outbox, simplified idempotency).
   - Update Local Run, Testing, and QA sections.
2. **`docs/migration/REUSE_FROM_ORIGINAL_THESIS.md`** — mark Portfolio section as `✅ MIGRATED` with migration date and key deltas (UUIDv7, owner_id, /api/v1/ prefix, new events).
3. **`docs/libs/messaging.md`** — if any sections remain marked as "planned" after Wave 01, mark them as implemented.
4. **`docs/libs/observability.md`** — if any sections remain marked as "planned" after Wave 01, mark them as implemented.
5. **`services/portfolio/configs/dev.local.env.example`** — verify all settings fields from `config.py` have example values.
6. **`services/portfolio/configs/prod.env.example`** — same.
7. Grep for any stale references to `user_id + created_by_user_id`, `uuid4`, `UpsertInstrument`, legacy `/api/` prefix — fix or note as intentional.

## Constraints

- Do not implement any task outside those listed in this wave (TASK-036–046, excluding TASK-045 which is in Wave 01).
- Do not start TASK-039 before TASK-038 is complete and fixtures verified.
- Do not start TASK-041 before TASK-036 app factory is complete and health probe tested.
- Do not start TASK-042 or TASK-043 before TASK-041 Docker Compose is functional.
- Do not mark TASK-044 complete until all other tasks in this wave are done.
- All repository fixes from TASK-046 audit must be applied in the same wave — do not defer to follow-up.
- Integration tests must use savepoint-based isolation (not DROP/CREATE schemas between tests).
- E2E tests (TASK-042, TASK-043) must be skippable in CI without Docker/Kafka via `pytest.mark.e2e`.
- Use `structlog` exclusively — no `print()` or stdlib `logging`.
- All UTC timestamps, UUIDv7 IDs — verify in audit.

## Required tests

```bash
# Unit tests — full suite
cd services/portfolio && python -m pytest tests/unit/ -v --cov=portfolio --cov-report=term-missing

# Contract tests
cd services/portfolio && python -m pytest tests/contract/ -v

# Integration tests (requires Docker)
cd services/portfolio && python -m pytest tests/integration/ -v

# Health probe update
cd services/portfolio && python -m pytest tests/test_health.py -v

# E2E tests (optional — requires full infra)
cd services/portfolio && python -m pytest tests/e2e/ -v -m e2e

# Lint + type check — full service
ruff check services/portfolio/src
mypy services/portfolio/src

# Full lint sweep across all touched packages
./scripts/lint.sh
```

**Pass criteria:**
- All unit tests pass; application-layer coverage >90%.
- All contract tests pass (8 event types validated against their Avro schemas).
- All integration tests pass (14 endpoints, outbox events, idempotency, cross-tenant 403).
- `ruff check` and `mypy` exit 0 for all touched code.
- `./scripts/lint.sh` exits 0 (no errors anywhere in the repo).
- `docker compose up portfolio` starts and `/healthz` + `/readyz` both return 200.

## Documentation requirements

**Impacted files — all must be verified and updated in this wave:**

| File | Update condition |
|------|-----------------|
| `docs/services/portfolio.md` | Full review: endpoints, events, DB schema, consumed topics, background jobs, local run, testing, QA scenarios. |
| `docs/migration/REUSE_FROM_ORIGINAL_THESIS.md` | Mark Portfolio as ✅ MIGRATED. |
| `docs/libs/messaging.md` | Mark all implemented sections final (if any remain from Wave 01). |
| `docs/libs/observability.md` | Mark all implemented sections final (if any remain from Wave 01). |
| `services/portfolio/configs/dev.local.env.example` | All settings fields have example values. |
| `services/portfolio/configs/prod.env.example` | All settings fields have prod-safe placeholder values. |

**Mandatory rule**: In this same wave, update every doc listed above for any behavior/contract/config/schema/API/test-surface change. List the exact file paths updated in your handoff evidence. Documentation must satisfy the quality standard defined below.

## Documentation quality standard

Every task in this wave must produce documentation to the following standard. The executing agent must include a **Documentation quality checklist** in its handoff evidence, with one row per criterion.

| # | Criterion | Requirement |
|---|-----------|-------------|
| 1 | **Accurate** | Every public API, endpoint, event, and config var in the code has a matching entry in the relevant `docs/` file. |
| 2 | **Complete** | No "TODO", "TBD", or placeholder text remains in any documentation file touched by this wave. |
| 3 | **Consistent** | Naming in docs matches naming in code (event types, topic names, field names, HTTP paths). |
| 4 | **Exemplified** | Each public API or library surface has at least one usage example in the doc. |
| 5 | **Diagrammed** | Any non-trivial flow (outbox dispatch, consumer lifecycle, request path, entity state machine) has a Mermaid or ASCII diagram in the relevant doc. |
| 6 | **Tested** | Doc changes are verified against the running code — no doc describes behavior that is not covered by at least one test. |
| 7 | **Linked** | Cross-references between service docs, lib docs, and ADRs are present and valid. |
| 8 | **Versioned** | If a schema, topic, or API contract changed, the version bump is reflected in both code and docs. |

## Required handoff evidence

1. **Completed task IDs** — all 10 task IDs confirmed done.
2. **Changed files** — full list of created or modified files with brief description.
3. **Test results** — summarised output for each test command (pass count, coverage %, any skips).
4. **Security audit findings** — list of any gaps found + fixes applied (or "no issues found per audit").
5. **Docker verification** — confirm `docker compose up portfolio` + `/healthz` + `/readyz` pass.
6. **Docs changed** — exact file paths + one-sentence summary of each update.
6. **Documentation quality checklist** — complete the following table in your handoff:

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

7. **Unresolved blockers** — any deferred items or assumptions.
8. **Commit message proposal:**

```
feat(portfolio): app wiring, test suites, Docker Compose, QA scenarios, docs sweep (wave-03)

Complete the portfolio service: FastAPI app factory with lifespan/readyz/observability,
contract + integration + use-case unit tests (113+ total), Docker Compose definition,
cross-service instrument-sync and full-transaction-flow QA scenarios, tenant-isolation
security audit, and final documentation sweep. All tests pass; ruff/mypy strict clean;
docs/services/portfolio.md and migration registry updated.
```

9. **Highly detailed PR description** (final wave — required):

---

### PR Description

**Title**: `feat(portfolio): complete Portfolio service migration from platform_repo (waves 01–03)`

---

#### Scope summary

This PR completes the full migration of the Portfolio service from `platform_repo/apps/backend-portfolio` into `worldview/services/portfolio`, implementing all layers from domain through API, messaging, testing, and deployment. The migration also fills shared-library gaps in `libs/messaging` and `libs/observability` that are required by the Portfolio service and will be reused by subsequent service migrations.

---

#### Task IDs included (all 46)

| Wave | Task IDs |
|------|---------|
| Wave 01 | TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007, TASK-008, TASK-009, TASK-010, TASK-011, TASK-012, TASK-013, TASK-023, TASK-026, TASK-045 |
| Wave 02 | TASK-014, TASK-015, TASK-016, TASK-017, TASK-018, TASK-019, TASK-020, TASK-021, TASK-022, TASK-024, TASK-025, TASK-027, TASK-028, TASK-029, TASK-030, TASK-031, TASK-032, TASK-033, TASK-034, TASK-035 |
| Wave 03 | TASK-036, TASK-037, TASK-038, TASK-039, TASK-040, TASK-041, TASK-042, TASK-043, TASK-044, TASK-046 |

---

#### Grouped changed files

**`libs/messaging/`**
- `src/messaging/consumer/`: `BaseKafkaConsumer`, `ConsumerConfig`, `RetryableError`, `FatalError` + subclasses (TASK-001).
- `src/messaging/schema_registry.py`, `serializer.py`, `serialization_utils.py`: `SchemaRegistryClient`, `build_avro_serializer`, `AvroDictable`, `load_schema`, `iso_datetime`, `decimal_to_str` (TASK-002).
- `src/messaging/producer.py`: `KafkaProducerConfig`, `build_serializing_producer`, `OutboxKafkaValue` (TASK-003).
- `src/messaging/dispatcher/`: `BaseOutboxDispatcher`, `DispatcherConfig`, `run_dispatcher`, outbox protocols (TASK-004).
- `src/messaging/valkey/`: `ValkeyClient`, `ValkeyConfig`, `create_valkey_client` (TASK-005).
- `tests/`: unit tests for all above modules.
- `pyproject.toml`: new deps `confluent-kafka`, `fastavro`, `redis[hiredis]`, `pydantic-settings` (TASK-045).

**`libs/observability/`**
- `src/observability/metrics.py`: `ServiceMetrics`, `create_metrics`, `add_prometheus_middleware` (TASK-006).
- `src/observability/tracing.py`: `configure_tracing`, `get_tracer`, `add_otel_middleware` (TASK-007).
- `src/observability/__init__.py`: re-exports updated.
- `tests/test_metrics.py`, `tests/test_tracing.py`: new unit tests.
- `pyproject.toml`: new deps `prometheus-client`, opentelemetry stack (TASK-045).

**`libs/common/`**
- `tests/test_ids.py`, `tests/test_types.py`: new unit tests for `ids.py` and `types.py` (TASK-008).

**`services/portfolio/src/portfolio/`**
- `domain/enums.py`: 7 enum types (TASK-009).
- `domain/value_objects.py`: `Money`, `InstrumentKey`, `Quantity` (TASK-010).
- `domain/entities/`: 6 entity files — `owner_id` replacing `user_id+created_by_user_id`, UUIDv7 IDs (TASK-011).
- `domain/events.py`: 10 event types — `PortfolioCreated` enabled, `InstrumentRefCreated` added (TASK-012).
- `domain/errors.py`: 15+ error classes (TASK-013).
- `domain/__init__.py`, `domain/entities/__init__.py`: exports (TASK-014).
- `application/ports/repositories.py`: 8 repo ABCs + `OutboxRecord`, `IdempotencyRecord` DTOs (TASK-016).
- `application/ports/unit_of_work.py`: `UnitOfWork` ABC (TASK-016).
- `application/use_cases/tenant.py`, `user.py`, `create_portfolio.py`, `portfolio_ops.py`, `record_transaction.py`, `read_models.py`, `instrument.py`: all 12 use cases (TASK-017–021).
- `infrastructure/db/models/`: 8 ORM model files + `Base` — NUMERIC(18,8), JSONB outbox, simplified idempotency (TASK-022).
- `infrastructure/db/session.py`: async session factory (TASK-023).
- `infrastructure/db/repositories/`: 8 concrete repositories — all queries tenant-scoped (TASK-024).
- `infrastructure/db/unit_of_work.py`: `SqlAlchemyUnitOfWork` (TASK-025).
- `config.py`: all 17+ settings fields (TASK-026).
- `api/schemas.py`: 12 Pydantic request/response models (TASK-027).
- `api/error_mapping.py`, `api/exception_handlers.py`: domain→HTTP mapping (TASK-028).
- `api/dependencies.py`: `uow_dep` DI factory (TASK-029).
- `api/routes/`: 6 route files, 14 endpoints under `/api/v1/` (TASK-029).
- `messaging/schemas/`: 8 `.avsc` files (TASK-030).
- `messaging/topics.py`, `messaging/mapper.py`: routing + 8 event mappers (TASK-031).
- `messaging/serialization.py`, `messaging/outbox_mapper.py`, `messaging/dispatcher.py`: serialization + `OutboxDispatcher` (TASK-032).
- `messaging/dispatcher_main.py`: standalone dispatcher entry point (TASK-033).
- `consumers/instrument_consumer.py`: `InstrumentEventConsumer` (TASK-034).
- `app.py`: full lifespan, observability, all routers, `/metrics`, `/readyz` (TASK-036).
- `alembic/env.py`, `alembic/versions/0001_initial_schema.py`: Alembic wiring + migration (TASK-035).

**`services/portfolio/tests/`**
- `test_health.py`: updated with readyz tests (TASK-036).
- `unit/test_domain_entities.py`, `test_value_objects.py`, `test_domain_events.py`, `test_domain_errors.py`: domain tests (TASK-015).
- `unit/test_api_schemas.py`, `test_api_error_handlers.py`: API layer tests (TASK-027, TASK-028).
- `unit/test_config.py`, `test_unit_of_work.py`, `test_mappers.py`, `test_serialization.py`, `test_instrument_consumer.py`: infra + messaging tests (various tasks).
- `unit/test_use_cases_*.py` (5 files): use-case tests with fake repos (TASK-040).
- `contract/test_*_contract.py` (8 files): Avro schema contract tests (TASK-037).
- `conftest.py`, `integration/helpers.py`: testcontainer + savepoint fixtures (TASK-038).
- `integration/test_*_api.py` (6 files): full API→DB round-trip tests (TASK-039).
- `e2e/test_instrument_sync.py`, `e2e/test_full_flow.py`: QA scenarios (TASK-042, TASK-043).
- `unit/fakes.py`: in-memory repository fakes (TASK-040).

**`infra/`**
- `compose/docker-compose.yml`: `portfolio` service added (TASK-041).

**`services/portfolio/`**
- `Dockerfile`: multi-stage build (TASK-041).
- `configs/dev.local.env.example`, `configs/prod.env.example`: all vars documented (TASK-026).
- `pyproject.toml`: path deps for all 5 libs + testcontainers dev dep (TASK-045).

---

#### Test / lint / type evidence

| Check | Result |
|-------|--------|
| `python -m pytest tests/unit/` | ✅ pass (target: ~80 tests) |
| `python -m pytest tests/contract/` | ✅ pass (8 schema types) |
| `python -m pytest tests/integration/` | ✅ pass (14 endpoints) |
| `python -m pytest tests/test_health.py` | ✅ pass |
| `ruff check services/portfolio/src` | ✅ 0 errors |
| `mypy services/portfolio/src` | ✅ 0 errors (strict) |
| `ruff check libs/messaging/src libs/observability/src libs/common/src` | ✅ 0 errors |
| `mypy libs/messaging/src libs/observability/src libs/common/src` | ✅ 0 errors |
| `./scripts/lint.sh` | ✅ 0 errors |
| `alembic upgrade head && alembic downgrade base` | ✅ verified |
| `docker compose up portfolio` + `/healthz` + `/readyz` | ✅ 200 OK |

---

#### Docs / ADR updates

| Document | Change |
|----------|--------|
| `docs/services/portfolio.md` | Full review; endpoint table finalised; events table updated (PortfolioCreated, InstrumentRefCreated); DB schema matches implementation; consumed-topics verified; Local Run + Testing + QA sections added. |
| `docs/migration/REUSE_FROM_ORIGINAL_THESIS.md` | Portfolio section marked ✅ MIGRATED. |
| `docs/libs/messaging.md` | All sections marked implemented. |
| `docs/libs/observability.md` | Metrics + tracing sections marked implemented. |
| `services/portfolio/configs/dev.local.env.example` | All 17+ config vars with example values. |
| `services/portfolio/configs/prod.env.example` | All vars with prod-safe placeholders. |

---

#### API compatibility notes

- **New versioned prefix**: all endpoints moved from `/api/` → `/api/v1/`. Breaking change vs legacy — intentional per target spec.
- **New endpoints**: `PUT /api/v1/portfolios/{id}` (rename), `DELETE /api/v1/portfolios/{id}` (archive), `GET /api/v1/users/{id}`, `GET /api/v1/instruments`.
- **Avro schemas**: forward-compatible with new fields defaulting to `null`. Schema versions bumped for new event types.
- **Portfolio.owner_id**: replaces `user_id + created_by_user_id` — schema is fresh (no existing consumers) so no backward-compat concern.

---

#### Migration deltas from legacy

| Aspect | Legacy | This implementation |
|--------|--------|---------------------|
| API prefix | `/api/` | `/api/v1/` |
| Entity IDs | UUIDv4 | UUIDv7 (time-sortable) |
| Portfolio FK | `user_id + created_by_user_id` | `owner_id` |
| DB numeric precision | `(20, 8)` | `(18, 8)` |
| Outbox payload | `LargeBinary` | `JSONB` |
| `PortfolioCreated` event | commented out | enabled |
| `InstrumentRefCreated` event | absent | added |
| Logging | stdlib `logging` | `structlog` via observability lib |
| ID generation | `uuid4()` | `new_uuid()` (UUIDv7) |

---

#### Security notes

- All 8 repositories filter by `tenant_id` on every query (audited TASK-046).
- Cross-tenant access returns HTTP 403 (integration test coverage added).
- No hardcoded secrets — all config via `pydantic-settings` with env vars.
- No naive datetimes — UTC enforced throughout.

---

#### Risks and known limitations

1. **Confluent Kafka C extension**: requires native libs; Docker build uses `confluent-kafka` wheel — may need platform-specific image if ARM.
2. **E2E tests require full infra**: TASK-042 (instrument sync) requires Kafka + Schema Registry running; marked `pytest.mark.e2e` and excluded from standard CI.
3. **Alembic downgrade is destructive**: `downgrade base` drops all tables — only safe for fresh deployments; add guard in prod CI.
4. **Optional Valkey**: `ValkeyClient` (TASK-005) is implemented but not wired into Portfolio service yet — reserved for future caching use cases.
5. **Optional K8s manifests**: not included in this migration (thesis scope); compose-based deployment is sufficient.

---

#### Rollback plan

1. **Service**: revert Docker image to previous tag (scaffold only — no functional changes rolled back).
2. **DB**: `alembic downgrade base` (drops all portfolio tables — only safe if no data).
3. **Kafka**: consumer group offsets auto-reset — no data loss on rollback.
4. **Outbox**: pending events remain in DB — will dispatch after redeploy.
5. **Shared libs**: `libs/messaging` and `libs/observability` additions are additive — existing callers unaffected.

---

#### Follow-up items (out of scope)

- K8s manifests for portfolio service.
- Valkey-based response caching for read endpoints.
- `libs/storage` completion (L-09 to L-12 gaps — needed by other services, not portfolio).
- API Gateway (S9) integration for frontend routing.
- Performance / load testing.

---

## Definition of done

- [ ] TASK-036: App factory fully wired; `/readyz` checks DB; `/metrics` returns Prometheus data; all routers registered; lifespan start/stop clean; tests pass.
- [ ] TASK-037: 8 Avro contract tests pass; all event mappers produce schema-valid output.
- [ ] TASK-038: Testcontainer starts; Alembic migrations apply; savepoint isolation verified; test fixtures functional.
- [ ] TASK-039: All 14 endpoint integration tests pass; outbox events confirmed; idempotency verified; cross-tenant 403 tested.
- [ ] TASK-040: All use-case unit tests pass; application-layer coverage >90%; fake repos in `tests/unit/fakes.py`.
- [ ] TASK-041: `Dockerfile` builds successfully; `docker compose up portfolio` starts; `/healthz` returns 200.
- [ ] TASK-042: Instrument sync QA scenario defined and passing (or skipped cleanly without Kafka); scenario documented in `docs/services/portfolio.md`.
- [ ] TASK-043: Full transaction flow QA scenario defined and passing (or skipped cleanly without full infra); scenario documented.
- [ ] TASK-044: All doc files listed in documentation requirements updated; no stale references; `REUSE_FROM_ORIGINAL_THESIS.md` marks Portfolio ✅ MIGRATED.
- [ ] TASK-046: Tenant isolation audit complete; all gaps fixed; cross-tenant negative tests added; findings in handoff evidence.
- [ ] `./scripts/lint.sh` exits 0.
- [ ] Documentation updates completed for all impacted files listed above.
- [ ] Commit message proposal included in handoff.
- [ ] **Highly detailed PR description** (this section above) completed and included in handoff.
