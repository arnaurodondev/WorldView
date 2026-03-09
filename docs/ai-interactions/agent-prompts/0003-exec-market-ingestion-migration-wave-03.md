# Execution Prompt 0003 — market-ingestion-migration wave 03

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
2. `CLAUDE.md` — workflow, error handling, logging, migration discipline
3. `docs/services/market-ingestion.md` — complete target service specification (API surface, SLIs, config)
4. `docs/libs/messaging.md` — `BaseOutboxDispatcher` interface (T-MI-22 wiring)
5. `docs/libs/observability.md` — `configure_logging()`, `add_prometheus_middleware()`, `add_otel_middleware()` (T-MI-23, T-MI-24)
6. `docs/libs/storage.md` — storage health check (T-MI-23 readyz)
7. `docs/libs/common.md` — `utc_now()` (T-MI-17 repo time helpers)
8. All architecture ADRs in `docs/architecture/decisions/` — especially ADR-0001 (hexagonal arch), ADR-0004 (Valkey), ADR-0005 (error classification)
9. `docs/ai-interactions/agent-planning/0003-market-ingestion-migration-detailed-plan-and-atomic-tasks.md`
10. `docs/ai-interactions/agent-responses/0003-response-20260306-market-ingestion-migration-plan.md` — §4 Milestones 3 (T-MI-17, T-MI-22), 4, 5, 6; §5 roadmap; §6 go-live checklist

**Pre-conditions**: Waves 01 and 02 are complete. All prior tasks pass tests, lint, and mypy. `alembic upgrade head` has been validated on a clean database. All lib dependencies are installed.

---

## Objective

This is the **final wave** of the market-ingestion migration scope. It completes:

- **Milestone 3 (remaining)**: Repositories + UoW (T-MI-17) and outbox dispatcher wiring (T-MI-22).
- **Milestone 4 (Entrypoints & Configuration)**: FastAPI API routes + DI (T-MI-23), scheduler + worker processes (T-MI-24), finalized Settings (T-MI-25).
- **Milestone 5 (Testing & Quality)**: Service container integration tests (T-MI-26), platform QA scenarios (T-MI-27).
- **Milestone 6 (Deployment & Operations)**: Docker Compose (T-MI-28), Alembic seed migration (T-MI-29), operational runbook + go-live checklist validation (T-MI-30).

At the end of this wave, the Market Ingestion service is fully migrated, deployable, and validated end-to-end.

---

## Task scope for this wave

**Total tasks: 10**

### Parallel group A — prerequisites from wave 02 satisfied (start simultaneously)

| Task ID | Short title | Key prerequisite |
|---------|-------------|-----------------|
| T-MI-17 | DB repositories + UoW | T-MI-15 models (wave 02), T-MI-16 Alembic migration validated (wave 02) |
| T-MI-29 | Alembic seed migration for default policies | T-MI-16 initial migration (wave 02) |

### Parallel group B — after group A completes

| Task ID | Unlocked by | Short title |
|---------|-------------|-------------|
| T-MI-22 | T-MI-17 + T-LIB-05 (wave 01) + T-MI-21 (wave 02) | Wire service-specific outbox dispatcher |
| T-MI-23 | T-MI-17 + T-MI-10..T-MI-14 (wave 02) + T-MI-18..T-MI-20 (wave 02) | FastAPI routes + DI wiring |

### Sequential group C — after group B completes

| Task ID | Unlocked by | Short title |
|---------|-------------|-------------|
| T-MI-24 | T-MI-22 + T-MI-10..T-MI-12 (wave 02) | Scheduler + Worker + Dispatcher entrypoints |

### Sequential group D — after group C completes

| Task ID | Unlocked by | Short title |
|---------|-------------|-------------|
| T-MI-25 | T-MI-23 + T-MI-24 | Finalize Settings + env example files |

### Parallel group E — after group D completes

| Task ID | Unlocked by | Short title |
|---------|-------------|-------------|
| T-MI-26 | T-MI-25 (all implementation complete) | Service container integration tests |
| T-MI-28 | T-MI-25 | Docker Compose + Dockerfile |

### Sequential group F — after group E completes

| Task ID | Unlocked by | Short title |
|---------|-------------|-------------|
| T-MI-27 | T-MI-26 | Platform QA scenarios (with Market Data stub) |

### Sequential group G — after group F completes

| Task ID | Unlocked by | Short title |
|---------|-------------|-------------|
| T-MI-30 | All other wave-03 tasks | Operational runbook + go-live checklist |

---

## Why this chunk

**Coherence**: This wave wires together all previously built pieces into a running service. It groups the repository tier (requires validated migration), the entrypoint processes (require both repositories and use cases), integration tests (require everything to be runnable), and operational artifacts (require tested, configured service). This is a coherent "integration and go-live" wave.

**Dependency fit**: T-MI-17 must follow T-MI-16 (wave 02). T-MI-22 must follow T-MI-17. T-MI-23/24 must follow both use cases (wave 02) and adapters/repos (this wave). T-MI-26 must follow all implementation.

**Size**: 10 tasks — within the [10, 20] bound. The lower count (vs 15 in wave 01) reflects the higher implementation density per task here (T-MI-17 is L effort, T-MI-23 is L effort, T-MI-26 is L effort). Three L-effort tasks in one wave is deliberate; two can be parallelized.

**T-MI-27 soft external dependency**: The Market Data service may not exist yet. T-MI-27 is included in this wave (not deferred) because the planning response explicitly allows stubbing the downstream consumer. Implement a stub Kafka consumer that reads `market.dataset.fetched`, validates the event envelope, and fetches the canonical MinIO object.

---

## Implementation instructions

### T-MI-17 — DB Repositories + UoW

1. Read:
   - `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/db/repositories/` (all 5 repo files + UoW).
   - `worldview/services/market-ingestion/src/market_ingestion/infrastructure/db/models/` (wave-02 output).
   - `worldview/services/market-ingestion/src/market_ingestion/application/ports/repositories.py` (wave-02 output).
2. Create `infrastructure/db/repositories/__init__.py`.
3. Create `infrastructure/db/repositories/task_repository.py`:
   - `SqlaTaskRepository(TaskRepository)`.
   - `get(task_id)`, `add(task)`, `add_many(tasks)` (with `ON CONFLICT DO NOTHING` on `dedupe_key`), `save(task)`, `list_by_status(status)`, `count_by_status()`, `has_active_task(dedupe_key)`.
   - `claim_batch(worker_id, batch_size, lease_seconds)`: `SELECT ... FROM ingestion_tasks WHERE status='PENDING' AND (locked_until IS NULL OR locked_until < now()) ORDER BY priority DESC FOR UPDATE SKIP LOCKED LIMIT :batch_size`. Update claimed tasks: `status='RUNNING'`, `locked_by=worker_id`, `locked_until=now()+lease`.
   - Route reads to read session, writes to write session.
4. Create `infrastructure/db/repositories/watermark_repository.py`:
   - `SqlaWatermarkRepository(WatermarkRepository)`: `get(natural_key_tuple)`, `get_or_create(...)` (INSERT … ON CONFLICT DO NOTHING + SELECT), `save(watermark)`, `list_by_provider(provider)`.
5. Create `infrastructure/db/repositories/policy_repository.py`:
   - `SqlaPollingPolicyRepository(PollingPolicyRepository)`: `list_enabled()` (uses `ix_polling_policies_enabled`), `find_matching(provider, dataset_type, symbol)`, `add(policy)`, `save(policy)`.
6. Create `infrastructure/db/repositories/budget_repository.py`:
   - `SqlaProviderBudgetRepository(ProviderBudgetRepository)`: `get(provider)`, `get_or_create(provider, defaults)`, `save(budget)`, `list_all()`.
7. Create `infrastructure/db/repositories/outbox_repository.py`:
   - `SqlaOutboxRepository(OutboxRepository)`: `add(events)` (serialize event to JSON, insert into `outbox_events`), `claim_batch(worker_id, batch_size, lease_seconds)` (`FOR UPDATE SKIP LOCKED`), `mark_published(event_ids)`, `mark_failed(event_ids)`.
   - Event serialization: JSON dump of `event.to_dict()` into `payload` column; `topic` from `messaging.topics`.
8. Create `infrastructure/db/unit_of_work.py`:
   - `SqlaUnitOfWork(UnitOfWork)` with `async __aenter__`/`__aexit__`, `commit()`, `rollback()`.
   - Aggregates all 5 repos as properties.
   - `on_commit(callback)`: register a coroutine to run after commit (used to notify dispatcher of new outbox events).
   - `mark_outbox_events_added()` flag to trigger immediate dispatch after short transaction.
9. Create `tests/infrastructure/test_repositories.py`:
   - Unit (mocked SQLA session): mapper correctness, outbox event serialization.
   - Integration tests (marked `@pytest.mark.integration`, require PostgreSQL):
     - Task add + claim roundtrip.
     - Idempotent task enqueue (same `dedupe_key` → no error, no duplicate row).
     - Concurrent claim: 2 async workers claiming simultaneously → no double-claim (use `asyncio.gather`).
     - Watermark `get_or_create` race safety.
     - Outbox `claim_batch` with lease + `mark_published` + verify status.
     - Policy `list_enabled` filtering.
     - UoW commit + rollback: write then rollback → no row persisted.
10. Run:
    ```bash
    cd services/market-ingestion
    pytest tests/infrastructure/test_repositories.py -v -m "not integration"
    pytest tests/infrastructure/test_repositories.py -v -m "integration"  # requires Postgres
    make lint
    ```

**DoD**: 5 repositories + UoW, `FOR UPDATE SKIP LOCKED` claiming, `ON CONFLICT DO NOTHING` enqueue, UoW with `on_commit`, integration tests pass against real Postgres, lint + mypy clean.

---

### T-MI-29 — Alembic Seed Migration (parallel with T-MI-17)

1. Read `platform_repo/apps/backend-market-ingestion/alembic/versions/*_seed_default_policies.py`.
2. Read `platform_repo/apps/backend-market-ingestion/alembic/versions/*_seed_backfill_for_demo_symbols.py`.
3. Create a new data migration: `alembic revision -m "seed_default_policies_and_demo_backfill"`.
4. Implement `upgrade()`:
   - `op.bulk_insert(polling_policies_table, [...])` with default policies:
     - EODHD daily OHLCV for all symbols (`symbol=None`).
     - EODHD intraday quotes for demo symbols.
     - EODHD fundamentals quarterly.
   - Backfill demo policies for symbols from the legacy seed (preserve same test symbols).
   - Generate UUIDv7 IDs for each seeded row.
   - All `created_at` / `updated_at` via `now()` SQL function.
5. Implement `downgrade()`:
   - `op.execute("DELETE FROM polling_policies WHERE <seed condition>")` — identify seeded rows by a marker or by ID range.
6. Test:
   ```bash
   alembic upgrade head  # applies initial schema + seed migration
   # verify rows present:
   # SELECT count(*) FROM polling_policies  -- expect N > 0
   alembic downgrade -1   # removes seed
   alembic upgrade head   # re-applies both
   ```

**DoD**: Seed migration applied correctly, policies queryable, upgrade + downgrade idempotent.

---

### T-MI-22 — Service-Specific Outbox Dispatcher Wiring (after T-MI-17)

1. Read:
   - `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/messaging/dispatcher.py`
   - `worldview/libs/messaging/src/messaging/outbox.py` (`BaseOutboxDispatcher` — wave-01 output)
   - `worldview/services/market-ingestion/src/market_ingestion/infrastructure/messaging/kafka/serialization.py` (wave-02 output)
2. Create `infrastructure/messaging/dispatcher.py`:
   - `MarketIngestionOutboxDispatcher(BaseOutboxDispatcher)`:
     - Override `_create_uow() -> UnitOfWork`: instantiate `SqlaUnitOfWork` using the write session factory from `Settings`.
     - Override `_serialize_event(event_row) -> tuple[str, str, dict]`: deserialize event payload from JSON, identify event type, apply `MarketDatasetFetchedMapper.to_avro_dict()`, return `(topic, kafka_key, avro_dict)`.
   - `build_market_ingestion_dispatcher(settings: Settings, producer) -> MarketIngestionOutboxDispatcher` factory function.
   - Configurable from `settings`: `dispatcher_poll_interval_seconds`, `dispatcher_lease_seconds`, `dispatcher_max_attempts`.
3. Create `tests/infrastructure/test_dispatcher.py`:
   - Unit (mocked UoW + producer): claim → serialize → produce → finalize happy path.
   - Produce failure → outbox event retry.
   - Max attempts exceeded → event marked dead-letter.
   - Integration test (`@pytest.mark.integration`, DB + Kafka): insert event into `outbox_events` → run dispatcher iteration → verify Kafka message Avro-deserializes with correct `event_type` and `bronze_ref_bucket`.
4. Run:
   ```bash
   cd services/market-ingestion
   pytest tests/infrastructure/test_dispatcher.py -v -m "not integration"
   make lint
   ```

**DoD**: `MarketIngestionOutboxDispatcher` wired to Market Ingestion infrastructure, configurable from `Settings`, unit tests pass, integration test passes (with Kafka).

---

### T-MI-23 — FastAPI Routes + Dependency Injection (after T-MI-17)

1. Read:
   - `platform_repo/apps/backend-market-ingestion/src/app/api/` (all route files, schemas, dependencies).
   - `worldview/services/market-ingestion/src/market_ingestion/app.py` (existing scaffold).
   - `worldview/services/market-ingestion/src/market_ingestion/config.py` (current Settings skeleton).
   - `worldview/docs/services/market-ingestion.md` — API endpoints section.
2. Create `api/__init__.py`.
3. Create `api/schemas.py`:
   - **Request models**: `TriggerRequest(BaseModel)`: `provider`, `symbols: list[str]`, `dataset_type`, `timeframe`. `BackfillRequest(BaseModel)`: `provider`, `symbol`, `start_date: date`, `end_date: date`, `timeframe`, `chunk_days: int = 30`.
   - **Response models**: `TriggerResponse`, `BackfillResponse`, `TaskStatusResponse`, `PolicyListResponse`.
4. Create `api/dependencies.py`:
   - `get_settings() -> Settings` (cached singleton).
   - `get_uow(settings: Settings) -> UnitOfWork` (new `SqlaUnitOfWork` per request).
   - `get_object_store(settings: Settings) -> ObjectStoreAdapter`.
   - `get_provider_registry(settings: Settings) -> ProviderRegistry`.
   - `get_canonical_serializer() -> CanonicalSerializer`.
5. Create `api/routes.py`:
   - `POST /api/v1/ingest/trigger` → `TriggerIngestionUseCase.execute()` → 202 Accepted + `TriggerResponse`.
   - `POST /api/v1/ingest/backfill` → `BackfillUseCase.execute()` → 202 Accepted + `BackfillResponse`.
   - `GET /api/v1/ingest/status` → `TaskRepository.count_by_status()` → 200 + `TaskStatusResponse`.
   - `GET /api/v1/policies` → `PollingPolicyRepository.list_enabled()` → 200 + `PolicyListResponse`.
   - `GET /healthz` → 200 always (liveness probe — no dependencies checked).
   - `GET /readyz` → check DB connection + MinIO `exists()` call + Kafka producer ping → 200 if all pass, 503 if any fail. Log failures with `get_logger()`.
   - `GET /metrics` → Prometheus text exposition (handled by `add_prometheus_middleware`).
6. Update `app.py`:
   - `lifespan(app)` context manager:
     - **Startup**: init async DB engine, validate DB connection, ensure MinIO bucket (`market-ingestion`), register providers in registry, attach metrics, OTel tracing (if `MARKET_INGESTION_OTLP_ENDPOINT` set).
     - **Shutdown**: dispose DB engine, close httpx clients.
   - Register routes from `api/routes.py`.
   - Add request-ID middleware: generate `X-Request-ID` header if absent, bind to structlog context.
   - Add Prometheus middleware via `add_prometheus_middleware(app, metrics)`.
   - Add OTel middleware via `add_otel_middleware(app)`.
7. Create `tests/api/__init__.py`.
8. Create `tests/api/test_routes.py` (using `httpx.AsyncClient` with `ASGITransport`, override DI with `app.dependency_overrides`):
   - `POST /api/v1/ingest/trigger` valid payload → 202 + task count in response.
   - `POST /api/v1/ingest/trigger` missing field → 422.
   - `POST /api/v1/ingest/backfill` valid → 202.
   - `GET /api/v1/ingest/status` → 200 with counts dict.
   - `GET /api/v1/policies` → 200 with list.
   - `GET /healthz` → 200.
   - `GET /readyz` with mocked healthy depencencies → 200.
   - `GET /readyz` with mocked failing DB → 503.
   - `GET /metrics` → 200, content-type `text/plain`.
9. Update documentation:
   - `docs/services/market-ingestion.md` — verify each API endpoint description matches implementation.
   - `services/market-ingestion/configs/dev.local.env.example` — update with any new env vars discovered.
10. Run:
    ```bash
    cd services/market-ingestion
    pytest tests/api/ -v
    make lint
    ```

**DoD**: 7 API endpoints, health probes, DI wiring, lifespan, Prometheus + OTel middleware, all API tests pass, service doc updated.

---

### T-MI-24 — Scheduler + Worker + Dispatcher Entrypoints (after T-MI-22)

1. Read:
   - `platform_repo/apps/backend-market-ingestion/src/app/scheduler/main.py`
   - `platform_repo/apps/backend-market-ingestion/src/app/worker/main.py`
   - `platform_repo/apps/backend-market-ingestion/src/app/messaging/dispatcher_main.py`
2. Create `scheduler/__init__.py`.
3. Create `scheduler/main.py`:
   - `SchedulerProcess`:
     - Reads `Settings` from env.
     - Calls `configure_logging(service="market-ingestion-scheduler")` at startup.
     - Builds: `SqlaUnitOfWork`, `ScheduleDueTasksUseCase`, `MarketIngestionOutboxDispatcher` (embedded).
     - Async tick loop: `asyncio.Event` with `asyncio.wait_for(stop_event.wait(), timeout=tick_interval)`.
     - Each tick: call `ScheduleDueTasksUseCase.execute()`, log structured tick summary (policies evaluated, tasks enqueued).
     - `dispatcher.start()` embedded (background task).
     - Signal handling: `SIGTERM` + `SIGINT` → set `stop_event`, `await dispatcher.stop()`, graceful exit.
   - `if __name__ == "__main__": asyncio.run(SchedulerProcess().run())`.
4. Create `worker/__init__.py`.
5. Create `worker/main.py`:
   - `WorkerProcess`:
     - Worker ID: `f"{socket.gethostname()}-{os.getpid()}"`.
     - Calls `configure_logging(service="market-ingestion-worker", worker_id=worker_id)` at startup.
     - Builds: `SqlaUnitOfWork`, `ClaimTasksUseCase`, `ExecuteTaskUseCase`, `MarketIngestionOutboxDispatcher` (embedded).
     - Claim/execute loop: claim batch → execute each task → sleep `poll_interval_seconds` if nothing claimed.
     - `dispatcher.start()` embedded.
     - SIGTERM/SIGINT graceful shutdown: finish current task batch, stop dispatcher.
   - `if __name__ == "__main__": asyncio.run(WorkerProcess().run())`.
6. Create `messaging/__init__.py`.
7. Create `messaging/dispatcher_main.py`:
   - Standalone dispatcher variant: no scheduler/worker logic. Runs only `MarketIngestionOutboxDispatcher` poll loop.
   - For deployments that dedicate a separate process to outbox dispatch.
   - `if __name__ == "__main__": asyncio.run(run_standalone_dispatcher())`.
8. Create `tests/entrypoints/__init__.py` (if dir used) or place tests in `tests/`:
   - `tests/test_scheduler.py`: scheduler tick invokes `ScheduleDueTasksUseCase.execute()` (mocked), SIGTERM sets stop event, loop terminates cleanly.
   - `tests/test_worker.py`: worker claims tasks (mocked), executes each (mocked), empty claim → loop pauses, SIGTERM → clean exit.
   - Integration test (`@pytest.mark.integration`): full scheduler → worker cycle with test DB + MinIO + Kafka: insert policy → run scheduler tick → verify task created → worker claims and executes (mocked EODHD HTTP) → verify outbox event published to Kafka.
9. Update documentation: verify `docs/services/market-ingestion.md` entrypoint module paths match implementation.
10. Run:
    ```bash
    cd services/market-ingestion
    pytest tests/test_scheduler.py tests/test_worker.py -v
    make lint
    ```

**DoD**: 3 runtime processes (scheduler, worker, standalone dispatcher), signal handling, embedded dispatcher, integration test, lint clean.

---

### T-MI-25 — Finalize Settings + Env Configs (after T-MI-23 + T-MI-24)

1. Read `platform_repo/apps/backend-market-ingestion/src/app/infrastructure/config/settings.py`.
2. Read current `worldview/services/market-ingestion/src/market_ingestion/config.py` (skeleton).
3. Update `config.py` — add all missing `Settings` fields with `MARKET_INGESTION_` prefix:

   | Field | Env var | Default |
   |-------|---------|---------|
   | `api_port` | `MARKET_INGESTION_API_PORT` | `8001` |
   | `scheduler_tick_interval_seconds` | `MARKET_INGESTION_SCHEDULER_TICK_INTERVAL_SECONDS` | `30` |
   | `scheduler_max_tasks_per_tick` | `MARKET_INGESTION_SCHEDULER_MAX_TASKS_PER_TICK` | `1000` |
   | `worker_batch_size` | `MARKET_INGESTION_WORKER_BATCH_SIZE` | `10` |
   | `worker_lease_seconds` | `MARKET_INGESTION_WORKER_LEASE_SECONDS` | `300` |
   | `worker_poll_interval_seconds` | `MARKET_INGESTION_WORKER_POLL_INTERVAL_SECONDS` | `5` |
   | `dispatcher_poll_interval_seconds` | `MARKET_INGESTION_DISPATCHER_POLL_INTERVAL_SECONDS` | `10` |
   | `dispatcher_lease_seconds` | `MARKET_INGESTION_DISPATCHER_LEASE_SECONDS` | `60` |
   | `dispatcher_max_attempts` | `MARKET_INGESTION_DISPATCHER_MAX_ATTEMPTS` | `5` |
   | `eodhd_api_key` | `MARKET_INGESTION_EODHD_API_KEY` | — (required) |
   | `finnhub_api_key` | `MARKET_INGESTION_FINNHUB_API_KEY` | `None` (optional) |
   | `polygon_api_key` | `MARKET_INGESTION_POLYGON_API_KEY` | `None` |
   | `alpha_vantage_api_key` | `MARKET_INGESTION_ALPHA_VANTAGE_API_KEY` | `None` |
   | `otlp_endpoint` | `MARKET_INGESTION_OTLP_ENDPOINT` | `None` |

4. Reconcile port: `api_port` default = `8001` (production per spec); dev profile uses `8002`. Document this in both example files.
5. Update `configs/dev.local.env.example` with ALL `MARKET_INGESTION_*` variables and dev defaults (use `MARKET_INGESTION_EODHD_API_KEY=demo` for dev).
6. Update `configs/prod.env.example` with all variables and `<REQUIRED>` / `<OPTIONAL>` placeholder notes.
7. Write `tests/test_settings.py`:
   - Default values load correctly.
   - Env var overrides work.
   - `eodhd_api_key` validation: empty string raises `ValidationError`.
   - All prefixes are `MARKET_INGESTION_`.
8. Run:
   ```bash
   cd services/market-ingestion
   pytest tests/test_settings.py -v
   make lint
   ```

**DoD**: All env vars declared with `MARKET_INGESTION_` prefix, example files complete and accurate, port reconciled, Settings test passes.

---

### T-MI-26 — Service Container Integration Tests (after T-MI-25)

1. Read `worldview/services/market-ingestion/tests/conftest.py`.
2. Read `worldview/pytest.ini` — verify `integration` and `platform` markers are registered.
3. Update `tests/conftest.py` with async fixtures:
   - `postgres_url` fixture: start Postgres via `testcontainers` or connect to local `MARKET_INGESTION_DATABASE_URL`; run `alembic upgrade head`; yield URL; `alembic downgrade base` after test.
   - `minio_client` fixture: start MinIO via testcontainers or local; create `market-ingestion` bucket; yield.
   - `kafka_bootstrap` fixture: start Kafka via testcontainers or local; yield bootstrap servers.
   - `settings` fixture: build `Settings` object wired to test infra URLs.
   - `event_loop` fixture: `asyncio_mode = auto` via `pytest.ini`.
4. Create `tests/integration/__init__.py`.
5. Create `tests/integration/test_worker_pipeline.py` (`@pytest.mark.integration`):
   - **Full pipeline test**:
     - Seed: 1 `PollingPolicy` (EODHD OHLCV daily, `symbol=None`), 1 seeded `IngestionTask` (PENDING).
     - Run `ClaimTasksUseCase.execute(worker_id="test-worker", batch_size=1, lease_seconds=60)`.
     - Run `ExecuteTaskUseCase.execute(task)` with mocked EODHD via `respx` (returns sample OHLCV JSON).
     - After execute: verify bronze object in MinIO at expected key.
     - Verify canonical object in MinIO at expected key.
     - Verify `outbox_events` table has 1 PENDING row.
     - Run one `MarketIngestionOutboxDispatcher` dispatch iteration.
     - Verify Kafka consumer receives `market.dataset.fetched` message; Avro-deserialize; validate `event_type`, `provider`, `bronze_ref_bucket`, `canonical_ref_key`.
   - **Task → SUCCEEDED state**: task status = `SUCCEEDED` after execute.
   - **Retry path**: mocked EODHD returns 429 → task status = `RETRY`, `attempt_count` incremented, `next_attempt_at` set.
6. Create `tests/integration/test_scheduler_worker.py` (`@pytest.mark.integration`):
   - Seed policy → run `ScheduleDueTasksUseCase.execute()` → verify task created in DB with status `PENDING`.
   - Run `ClaimTasksUseCase.execute()` → verify task status = `RUNNING`, `locked_by` = worker_id.
   - Concurrent claim: 2 workers via `asyncio.gather()` → each gets distinct tasks, no duplication.
7. Create `tests/integration/test_outbox_dispatch.py` (`@pytest.mark.integration`):
   - Insert raw `OutboxEventModel` row directly → run dispatcher → verify Kafka message published → Avro-deserialize → check all envelope fields present.
   - Simulate produce failure (mock producer raises) → verify outbox event retried (attempt_count + 1).
   - Simulate max attempts exceeded → verify event marked `DEAD_LETTER`.
8. Run:
   ```bash
   cd services/market-ingestion
   pytest tests/integration/ -v -m integration --tb=short
   make lint
   ```

**DoD**: Worker pipeline end-to-end validates Kafka Avro message, scheduler → worker cycle verified, concurrent claiming verified, outbox retry and dead-letter verified, all integration tests pass (with real infra).

---

### T-MI-28 — Docker Compose Update (parallel with T-MI-26)

1. Read `worldview/docker-compose.yml` (root level compose file, existing).
2. Read `worldview/services/market-ingestion/Makefile` (existing targets).
3. Create `worldview/services/market-ingestion/Dockerfile` (multi-stage):

   ```dockerfile
   # Stage 1: Build
   FROM python:3.12-slim AS builder
   RUN pip install hatch
   WORKDIR /app
   COPY pyproject.toml .
   COPY src/ src/
   RUN hatch build --target wheel

   # Stage 2: Runtime
   FROM python:3.12-slim AS runtime
   WORKDIR /app
   COPY --from=builder /app/dist/*.whl .
   # install libs as wheels too (path deps resolved at build time)
   RUN pip install *.whl
   ENV PYTHONUNBUFFERED=1
   ```

   Adjust for actual Hatch build process (may need `pip install -e .` pattern with mounted libs). Match the pattern used by other services in the monorepo.
4. Update `worldview/docker-compose.yml` — add or update market-ingestion services:
   - `market-ingestion-api`: `command: python -m market_ingestion.api.main`, port `8001:8001`, env from `services/market-ingestion/configs/dev.local.env.example`.
   - `market-ingestion-scheduler`: `command: python -m market_ingestion.scheduler.main`.
   - `market-ingestion-worker`: `command: python -m market_ingestion.worker.main`.
   - All depend on: `postgres`, `minio`, `kafka`, `schema-registry`.
   - Add health check to `market-ingestion-api`: `GET /healthz`.
5. Update `services/market-ingestion/README.md`:
   - Docker quick-start instructions.
   - How to run each process locally.
   - Link to `docs/services/market-ingestion.md`.
6. Validate:
   ```bash
   docker build -t market-ingestion:test -f services/market-ingestion/Dockerfile .
   # Optionally: docker compose up market-ingestion-api --no-deps
   ```

**DoD**: Dockerfile builds successfully, Compose entries for 3 processes, health check configured, README updated.

---

### T-MI-27 — Platform QA Scenarios (after T-MI-26, soft dependency on Market Data)

1. Read `docs/architecture/diagrams.md` — event flow sequence for market ingestion → Kafka → market data.
2. Read `docs/services/market-ingestion.md` — `market.dataset.fetched` event structure.
3. Acknowledge: Market Data service may not exist. Create a **stub downstream consumer** within this test file.
4. Create `tests/platform/__init__.py`.
5. Create `tests/platform/test_ingestion_to_materialization.py` (`@pytest.mark.platform`):

   **Scenario 1 — End-to-end data flow**:
   - Trigger manual ingestion via `TriggerIngestionUseCase`.
   - Execute task (mocked EODHD HTTP via `respx`).
   - Dispatcher publishes to Kafka.
   - **Stub consumer** subscribes to `market.dataset.fetched`, Avro-deserializes the message, and:
     - Validates all envelope fields (`event_id` UUIDv7 format, `event_type == "market.dataset.fetched"`, `schema_version == 1`, `occurred_at` valid ISO-8601 UTC).
     - Validates claim-check fields: `bronze_ref_bucket` = `"market-ingestion"`, `bronze_ref_key` non-empty, `canonical_ref_key` non-empty.
     - Fetches canonical object from MinIO using the `canonical_ref_bucket` + `canonical_ref_key`.
     - Parses JSONL — verifies at least 1 `CanonicalOHLCVBar` can be deserialized.
   - Assert: consumed message count == 1, all validations pass.

   **Scenario 2 — Event replay safety**:
   - Publish the same `MarketDatasetFetched` event twice to Kafka (simulate redelivery).
   - Stub consumer processes both: verify idempotent handling doesn't fail (claim-check resolves to same MinIO object).

   **Scenario 3 — Schema forward compatibility**:
   - Deserialize a `market.dataset.fetched` Avro message with a simulated "future" schema (extra optional field added).
   - Verify existing consumer code still deserializes successfully without error.

6. Mark tests: `@pytest.mark.platform` — NOT run in CI by default (require full infra); can be run manually via `pytest -m platform`.
7. Update `pytest.ini` (or `pyproject.toml` `[tool.pytest.ini_options]`) to register the `platform` marker if not already registered.

**DoD**: Platform tests demonstrate end-to-end data flow, event envelope validated, claim-check resolves to real MinIO objects, canonical data parseable, tests marked `platform`.

---

### T-MI-30 — Operational Runbook + Go-Live Checklist Validation (after all other wave-03 tasks)

1. Create `worldview/docs/runbooks/market-ingestion-operations.md`:

   **Sections required**:
   - **Service overview**: 4 processes, their roles, ports, module paths.
   - **Startup sequence**: infra order (Postgres → MinIO → Kafka → Schema Registry → service processes).
   - **Health checks**: `GET /healthz` (always 200), `GET /readyz` (checks DB + storage + Kafka), expected responses.
   - **Common failure modes**:
     - `readyz` returns 503: check Postgres connection string, MinIO bucket existence, Kafka bootstrap reachability.
     - Tasks stuck in `RUNNING` with expired lease: run `UPDATE ingestion_tasks SET status='PENDING', locked_by=NULL, locked_until=NULL WHERE status='RUNNING' AND locked_until < now()`.
     - Outbox events stuck: check Schema Registry connectivity, verify `market.dataset.fetched` topic exists.
     - EODHD rate limit: `ProviderBudget.try_consume()` will gate tasks; monitor `provider_error_rate` metric.
   - **Recovery procedures**: lease reset SQL, outbox dead-letter re-queue procedure.
   - **Scaling guidance**: worker is horizontally scalable (`FOR UPDATE SKIP LOCKED`); scheduler must be single-instance.
   - **Monitoring dashboards**: SLI metric names (`task_execution_duration_seconds_p99`, `task_success_rate`, `outbox_dispatch_latency_seconds_p99`, `provider_error_rate`), SLO thresholds.
   - **Rollback procedure**: `docker rollout` to previous image + `alembic downgrade -1` if schema-level.

2. Final review + update of `docs/services/market-ingestion.md`:
   - Verify all API endpoint descriptions match implementation.
   - Verify configuration section matches `config.py` (all `MARKET_INGESTION_*` vars).
   - Verify SLI/SLO section matches what is actually instrumented.
   - Verify runtime process module paths match actual `scheduler/main.py`, `worker/main.py`, `messaging/dispatcher_main.py`.

3. Walk through `§6 — Operational Go-Live Checklist` from the planning response. For each checklist item:
   - Mark it `✅` if satisfied by this wave's implementation.
   - Mark it `⚠️ deferred` with explanation if blocked (e.g., Grafana dashboard setup is infra-team responsibility).

4. Append the completed checklist to `docs/runbooks/market-ingestion-operations.md` as a `## Go-Live Checklist` section.

**DoD**: Runbook created with all required sections, `docs/services/market-ingestion.md` final-reviewed and accurate, go-live checklist populated, at least 80% of checklist items `✅`.

---

## Constraints

- **Do not implement any code outside the task IDs listed in this wave** (T-MI-17, T-MI-22 through T-MI-30).
- Do not re-implement application use cases or domain entities — those are complete from waves 01/02.
- No backwards-incompatible changes to the Avro schema — only additive changes are allowed; `schema_version` must remain `1` unless a new field is added with a default.
- Do not copy legacy Alembic migration files for seed data — write fresh `op.bulk_insert()` migrations.
- Integration tests must be runnable: either use `testcontainers` or explicitly document the infra pre-conditions.
- T-MI-27 platform tests are marked `@pytest.mark.platform` and must NOT run in CI by default.

---

## Required tests

### Standard test suite (must pass)

```bash
# Unit + non-integration tests
cd services/market-ingestion && make test

# With integration tests (requires running Postgres, MinIO, Kafka)
cd services/market-ingestion && pytest tests/ -v -m "not platform"

# Lint + type check
cd services/market-ingestion && make lint
./scripts/lint.sh
./scripts/test-libs.sh  # ensure no lib regressions
```

### Integration tests (require infra)

```bash
docker compose -f infra/compose/docker-compose.yml --profile infra up -d
cd services/market-ingestion
pytest tests/integration/ -v -m integration --tb=short --timeout=60
```

### Platform tests (manual, not CI)

```bash
pytest tests/platform/ -v -m platform --tb=short
```

**Pass criteria:**
- All unit tests pass.
- All integration tests pass against real infra.
- `ruff check` zero errors.
- `mypy --strict` zero errors.
- `alembic upgrade head` (base → schema → seed) succeeds on clean database.
- `docker build` succeeds.
- `GET /healthz` + `GET /readyz` return 200 with running service.
- No regressions in waves 01 or 02 (full suite from root).

---

## Documentation requirements

For every task in this wave, update docs **in the same wave** if any of the following change:

| Change type | File to update |
|-------------|---------------|
| New API endpoints or changed response shapes | `docs/services/market-ingestion.md` — API section |
| New or updated env vars | `services/market-ingestion/configs/dev.local.env.example`, `configs/prod.env.example` |
| New entrypoint module paths | `docs/services/market-ingestion.md` — Processes section |
| New runtime command in Makefile | `services/market-ingestion/README.md` |
| New Avro schema registered | `docs/services/market-ingestion.md` — Events section |
| SLI metrics instrumented | `docs/services/market-ingestion.md` — Observability section |
| Operational procedures | `docs/runbooks/market-ingestion-operations.md` (create) |
| Go-live checklist — any item validated | `docs/runbooks/market-ingestion-operations.md` — Go-Live Checklist section |

**Mandatory instruction**: If any implementation changes a behavior, contract, config, schema surface, API surface, or test surface described in documentation, you MUST update that documentation in this same wave. List every doc file changed in the handoff evidence. Documentation must satisfy the quality standard defined below.

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

---

## Required handoff evidence

At wave completion, report all of the following:

### 1. Changed files (complete list)

List every file created or modified, with a one-line description.

### 2. Tests run and results

```
services/market-ingestion (all unit):        X passed, 0 failed
services/market-ingestion (integration):     X passed, 0 failed  [infra required]
services/market-ingestion (platform):        X passed, 0 failed  [infra required, manual]

Alembic migrations:
  upgrade (base → schema → seed):  SUCCESS
  downgrade (head → base):         SUCCESS

Docker:
  docker build:   SUCCESS

API smoke:
  GET /healthz:   200 OK
  GET /readyz:    200 OK
  GET /metrics:   200 text/plain

Ruff:   0 errors
Mypy:   0 errors
./scripts/lint.sh:   exit 0
./scripts/test-libs.sh:  exit 0  (no regressions)
```

### 3. Documentation changed (exact files + summary of each change)

Example:
- `docs/services/market-ingestion.md` — updated Processes section with correct module paths; verified API surface; updated Observability section with SLI metric names.
- `docs/runbooks/market-ingestion-operations.md` — created with startup sequence, health checks, failure modes, recovery, go-live checklist.
- `services/market-ingestion/configs/dev.local.env.example` — added all `MARKET_INGESTION_SCHEDULER_*`, `MARKET_INGESTION_WORKER_*`, `MARKET_INGESTION_DISPATCHER_*`, and API key vars.
- `services/market-ingestion/configs/prod.env.example` — same vars with `<REQUIRED>` / `<OPTIONAL>` placeholders.
- `services/market-ingestion/README.md` — docker instructions, process run commands.

### 4. Unresolved blockers

List anything that could not be implemented as specified and why. Common expected items:
- T-MI-27: Market Data service absent → stub consumer used. Note that real end-to-end test with Market Data is a follow-up once Market Data migration is complete.
- T-MI-30: Grafana dashboard setup deferred to infra-team (out of scope for this PR).

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
feat(market-ingestion): repositories, entrypoints, tests, deployment — complete migration (T-MI-17, T-MI-22..T-MI-30)

Wire all 5 SQLAlchemy repos + UoW (FOR UPDATE SKIP LOCKED, ON CONFLICT DO NOTHING), service-specific
outbox dispatcher, FastAPI routes (trigger/backfill/status/policies/health/metrics), scheduler/worker
processes with signal handling, Settings finalization, seed migration for default policies, Docker
Compose integration, full container integration tests (worker pipeline end-to-end Kafka Avro validated),
and platform QA scenarios. Operational runbook and go-live checklist created. 90+ tests pass; ruff +
mypy strict clean; docker build succeeds; /healthz + /readyz validate green.
```

---

### Final-wave PR description (required — this is the last wave for scope `market-ingestion-migration`)

**Title**: `feat(market-ingestion): complete service migration from platform_repo to worldview`

---

#### Summary

This PR completes the full migration of the Market Ingestion service (`services/market-ingestion/`) from the legacy `platform_repo` monolith to the `worldview` monorepo. It also closes all library prerequisite gaps in `libs/contracts`, `libs/storage`, `libs/messaging`, and `libs/observability`. The service is production-ready: all 4 runtime processes, full test coverage, Docker Compose, and an operational runbook.

---

#### Scope of changes — all 37 task IDs

| Wave | Task IDs | Layer |
|------|----------|-------|
| 01 | T-LIB-01, T-LIB-02, T-LIB-03, T-LIB-04, T-LIB-05, T-LIB-06, T-LIB-07 | Shared libs (contracts, storage, messaging, observability) |
| 01 | T-MI-01, T-MI-02, T-MI-03, T-MI-04, T-MI-05, T-MI-06, T-MI-07, T-MI-08 | Domain layer |
| 02 | T-MI-09, T-MI-10, T-MI-11, T-MI-12, T-MI-13, T-MI-14 | Application layer |
| 02 | T-MI-15, T-MI-16, T-MI-18, T-MI-19, T-MI-20, T-MI-21 | Infrastructure (partial) |
| 03 | T-MI-17, T-MI-22, T-MI-23, T-MI-24, T-MI-25, T-MI-26, T-MI-27, T-MI-28, T-MI-29, T-MI-30 | Infrastructure (repos), entrypoints, tests, deployment |

---

#### Grouped changed files

**`libs/contracts/`**
- `src/contracts/canonical/quotes.py` — `CanonicalQuote` frozen dataclass
- `src/contracts/canonical/fundamentals.py` — `CanonicalFundamentals` frozen dataclass
- `tests/test_quotes.py`, `tests/test_fundamentals.py`
- `IMPLEMENTATION.md` — checked T-LIB-01, T-LIB-02

**`libs/storage/`**
- `src/storage/object_storage.py` — `ObjectStorage` ABC + `S3ObjectStorage`
- `src/storage/exceptions.py` — exception hierarchy
- `src/storage/health.py` — `check_storage_health()`
- `tests/test_object_storage.py`
- `IMPLEMENTATION.md` — checked T-LIB-03

**`libs/messaging/`**
- `src/messaging/producer.py` — `KafkaProducerConfig`, `build_serializing_producer()`, `OutboxKafkaValue`
- `src/messaging/outbox.py` — `BaseOutboxDispatcher` with hybrid dispatch
- `tests/test_producer.py`, `tests/test_outbox.py`
- `IMPLEMENTATION.md` — checked T-LIB-04, T-LIB-05

**`libs/observability/`**
- `src/observability/metrics.py` — `ServiceMetrics`, `create_metrics()`, Prometheus middleware
- `src/observability/tracing.py` — `configure_tracing()`, `get_tracer()`, OTel middleware
- `tests/test_metrics.py`, `tests/test_tracing.py`
- `IMPLEMENTATION.md` — checked T-LIB-06, T-LIB-07

**`services/market-ingestion/src/market_ingestion/`**
- `domain/` — enums, value_objects, errors, entities (x4), events (full domain layer)
- `application/ports/` — adapters.py, repositories.py, unit_of_work.py
- `application/use_cases/` — schedule_tasks.py, claim_tasks.py, execute_task.py, trigger_ingestion.py, backfill.py
- `infrastructure/db/models/` — 5 model files + Base
- `infrastructure/db/session.py` — dual session factory
- `infrastructure/db/repositories/` — 5 repository files + UoW
- `infrastructure/adapters/` — object_store.py, canonical.py, providers/ (eodhd + 3 stubs + registry)
- `infrastructure/messaging/kafka/` — mapper.py, serialization.py
- `infrastructure/messaging/dispatcher.py` — service-specific outbox dispatcher
- `api/` — schemas.py, dependencies.py, routes.py
- `app.py` — updated lifespan, middleware
- `config.py` — complete Settings
- `scheduler/main.py`, `worker/main.py`, `messaging/dispatcher_main.py`

**`services/market-ingestion/alembic/`**
- `env.py` — wired to `Base.metadata`
- `versions/<hash>_initial_schema.py` — 5 tables + all indexes
- `versions/<hash>_seed_default_policies_and_demo_backfill.py` — data seed

**`services/market-ingestion/configs/`**
- `dev.local.env.example` — all `MARKET_INGESTION_*` vars
- `prod.env.example` — all vars with placeholders

**`services/market-ingestion/tests/`**
- Unit tests across domain, application, infrastructure, api directories
- Integration tests in `tests/integration/`
- Platform QA in `tests/platform/`
- Updated `conftest.py`

**`services/market-ingestion/`**
- `Dockerfile` — multi-stage build
- `README.md` — updated docker + run instructions

**`infra/kafka/schemas/`**
- `market.dataset.fetched.avsc` — relocated from legacy service

**`docker-compose.yml`**
- Added `market-ingestion-api`, `market-ingestion-scheduler`, `market-ingestion-worker` services

**`docs/`**
- `docs/services/market-ingestion.md` — final review and update
- `docs/runbooks/market-ingestion-operations.md` — created
- `docs/libs/contracts.md`, `docs/libs/storage.md`, `docs/libs/messaging.md`, `docs/libs/observability.md` — updated public API surfaces
- `libs/*/IMPLEMENTATION.md` — checklists updated

---

#### Test / lint / type evidence

| Suite | Result |
|-------|--------|
| `libs/contracts make test` | ✅ all pass |
| `libs/storage make test` | ✅ all pass |
| `libs/messaging make test` | ✅ all pass |
| `libs/observability make test` | ✅ all pass |
| `services/market-ingestion make test` (unit) | ✅ all pass |
| `services/market-ingestion pytest -m integration` | ✅ all pass (with infra) |
| `services/market-ingestion pytest -m platform` | ✅ all pass (manual, with infra) |
| `./scripts/lint.sh` | ✅ exit 0 |
| `mypy --strict` (all changed libs + service) | ✅ 0 errors |
| `alembic upgrade head` | ✅ success |
| `alembic downgrade base` | ✅ success |
| `docker build` | ✅ success |
| `GET /healthz` | ✅ 200 OK |
| `GET /readyz` | ✅ 200 OK |
| `GET /metrics` | ✅ 200 text/plain |

---

#### Documentation / ADR updates

- `docs/services/market-ingestion.md` — current and accurate; all sections verified against implementation.
- `docs/runbooks/market-ingestion-operations.md` — created with full operational procedures and validated go-live checklist.
- `infra/kafka/schemas/market.dataset.fetched.avsc` — Avro schema centralized per AGENTS.md convention.
- All lib `IMPLEMENTATION.md` checklists updated.

No new ADRs required: all decisions follow existing ADR-0001 (hexagonal arch), ADR-0004 (Valkey key taxonomy), ADR-0005 (error classification), and the migration guide.

---

#### Compatibility notes

- **UUIDv7 entity IDs**: This service starts with a fresh database; no legacy UUID v4 IDs to reconcile.
- **Env prefix change**: Legacy used flat env vars (e.g., `DATABASE_URL`); worldview uses `MARKET_INGESTION_DATABASE_URL`. All compose files and example configs updated.
- **Avro schema relocation**: Schema subject name in Schema Registry is unchanged (`market.dataset.fetched-market.dataset.fetched` or per topic-event-type strategy). Forward compatibility maintained.
- **API port**: Production default is `8001` (per `docs/services/market-ingestion.md`); dev default is `8002` to avoid conflict with other services.

---

#### Risks

| Risk | Status |
|------|--------|
| R-01: Library gaps blocking service (T-LIB-03..05) | ✅ Resolved — all libs complete |
| R-02: UUIDv7 migration complexity | ✅ Mitigated — fresh DB, `uuid7` library verified |
| R-04: Avro schema relocation breaking subject names | ✅ Mitigated — subject name preserved |
| R-06: Observability lib metrics/tracing deferred | ✅ Resolved — T-LIB-06/07 complete |
| R-09: `FOR UPDATE SKIP LOCKED` under concurrency | ✅ Tested in integration suite |
| R-07: Single scheduler as SPOF | ⚠️ Documented in runbook; Valkey leader election deferred to future work |

---

#### Rollback plan

1. Stop `market-ingestion-api`, `market-ingestion-scheduler`, `market-ingestion-worker`.
2. Tag the pre-deployment image and restore via `docker tag`.
3. `alembic downgrade base` from inside the container if schema rollback needed (safe — no data existed before migration).
4. Downstream services (`market-data`) are not affected — they consume Kafka events that will simply stop arriving.

---

#### Follow-ups / known limitations

- T-MI-27: Full end-to-end test with real Market Data service pending Market Data migration.
- Polygon, Yahoo, Alpha Vantage providers are stubs — full implementation is a separate scope.
- Grafana dashboard creation deferred to infra-team.
- Valkey negative-caching for provider responses deferred to post-thesis hardening sprint.
- `MARKET_INGESTION_API_PORT` reconciliation: `8001` prod, `8002` dev — confirm with deployment manifests.

---

## Definition of done

- [ ] T-MI-17: 5 repositories + UoW, `FOR UPDATE SKIP LOCKED`, `ON CONFLICT DO NOTHING`, `on_commit` callback, integration tests pass.
- [ ] T-MI-22: `MarketIngestionOutboxDispatcher` wired to Market Ingestion infra, configurable from `Settings`, unit + integration tests pass.
- [ ] T-MI-23: 7 API endpoints, health probes, Prometheus + OTel middleware, DI wiring, lifespan, API tests pass, `docs/services/market-ingestion.md` updated.
- [ ] T-MI-24: 3 runtime processes (scheduler, worker, standalone dispatcher), signal handling, embedded dispatcher, integration test passes.
- [ ] T-MI-25: All `MARKET_INGESTION_*` vars declared, example env files complete and accurate, Settings test passes.
- [ ] T-MI-26: Worker pipeline, scheduler-worker cycle, concurrent claim, outbox retry/dead-letter — all integration tests pass against real infra.
- [ ] T-MI-27: Platform QA scenarios pass (with stub consumer), marked `@pytest.mark.platform`.
- [ ] T-MI-28: Dockerfile builds, Compose starts 3 processes, health checks pass, README updated.
- [ ] T-MI-29: Seed migration applies cleanly, policies queryable, upgrade + downgrade idempotent.
- [ ] T-MI-30: Operational runbook created, go-live checklist populated (≥80% `✅`), `docs/services/market-ingestion.md` final-reviewed.
- [ ] `./scripts/lint.sh` passes with zero errors.
- [ ] `./scripts/test-libs.sh` passes (no regressions in wave-01/02 libs).
- [ ] Documentation updated for all behavior/contract/config/API changes (exact files listed in handoff).
- [ ] Documentation quality checklist completed in handoff evidence — all 8 criteria assessed (✅ pass or ⚠️ with justification; no ❌ without a linked fix).
- [ ] Commit message proposal included.
- [ ] Final-wave PR description included (as specified above in this prompt).
