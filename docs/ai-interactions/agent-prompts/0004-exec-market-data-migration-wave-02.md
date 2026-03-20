> **STATUS: IMPLEMENTED** — All tasks in this wave have been completed and merged. See git history for implementation evidence.

# Execution Prompt 0004 — market-data-migration wave 02

## Context (read first)

- **Planning prompt**: `docs/ai-interactions/agent-planning/0004-market-data-migration-detailed-plan-and-atomic-tasks.md`
- **Planning response (authoritative)**: `docs/ai-interactions/agent-responses/0004-response-20260306-market-data-migration-plan.md`

---

## Assigned agent profile(s)

- `.claude/agents/data-platform-engineer.md`
- `.claude/agents/architecture-decision-lead.md`

---

## Mandatory pre-read

Read **all** of these before writing a single line of code:

1. `AGENTS.md` — coding standards, naming conventions, architecture pattern
2. `CLAUDE.md` — Claude-specific workflow, diff discipline, logging rules
3. `docs/services/market-data.md` — target service specification
4. `docs/libs/messaging.md` — outbox dispatcher spec (MD-007 done in wave 01)
5. `docs/libs/storage.md` — ObjectStorage interface spec (MD-009 done in wave 01)
6. `docs/libs/observability.md` — metrics and tracing spec (MD-010, MD-011 done in wave 01)
7. `docs/ai-interactions/agent-planning/0004-market-data-migration-detailed-plan-and-atomic-tasks.md`
8. `docs/ai-interactions/agent-responses/0004-response-20260306-market-data-migration-plan.md` — DB schema, repository, UoW, outbox dispatcher, and integration test sections
9. Wave 01 handoff evidence — confirm MD-001 through MD-013 all done before starting
10. `docs/ai-interactions/BUG_PATTERNS.md` — read all DB/migration/outbox/compose/runtime-asset patterns before implementation

**Prerequisites**: Wave 01 must be fully complete (MD-001 through MD-013 all done, all tests passing, all docs updated). Do not begin wave 02 until wave 01 handoff evidence has been reviewed and accepted.

When handing off, explicitly list which `BP-xxx` entries were applied.

---

## Objective

Complete the **Database Layer** (MD-014, MD-015) and **Infrastructure Layer** (MD-016, MD-017, MD-018, MD-027, MD-028) of the Market Data migration.

This wave builds on top of the domain layer from wave 01 to implement all SQLAlchemy ORM models, Alembic migrations (including TimescaleDB hypertable setup), repository ports and PostgreSQL adapters, the Unit of Work pattern with async read/write session splitting, TimescaleDB query utilities, the `MarketDataOutboxDispatcher`, and the full integration test infrastructure using testcontainers.

At the end of this wave:
- All 26 ORM models are defined and migration-tested.
- All repository ABCs and their PostgreSQL adapters are implemented.
- The Unit of Work pattern wires repositories into a transactional boundary.
- TimescaleDB query utilities for OHLCV data are implemented.
- `MarketDataOutboxDispatcher` is implemented and wired into the app lifespan stub.
- Testcontainers-based integration test infrastructure is set up and smoke-tested.
- No API handlers or service-layer orchestration code is written yet.

---

## Task scope for this wave

**Total tasks: 7**

### Sequential group A — strict ordering (each step unblocks next)

| Task ID | Short title | Depends on |
|---------|-------------|------------|
| MD-014 | SQLAlchemy ORM models (26 tables) | MD-012 ✓ (wave 01) |
| MD-015 | Alembic migrations + TimescaleDB hypertable | MD-014 |
| MD-016 | Repository ports (ABCs) + PostgreSQL adapters | MD-012 ✓ (wave 01), MD-014 |

### Sequential group B — after group A

| Task ID | Short title | Depends on |
|---------|-------------|------------|
| MD-017 | Unit of Work (async, read/write splitting) | MD-016 |

### Parallel group C — after group B

| Task ID | Short title | Depends on |
|---------|-------------|------------|
| MD-018 | TimescaleDB query utilities | MD-014, MD-015, MD-016, MD-017 |
| MD-027 | MarketDataOutboxDispatcher | MD-007 ✓ (wave 01), MD-013 ✓ (wave 01), MD-014, MD-017 |
| MD-028 | Integration test infrastructure (testcontainers) | MD-015 |

---

## Why this chunk

**Coherence**: This wave exclusively covers the database and infrastructure layer of `services/market-data`. All tasks operate on `services/market-data/src/market_data/infrastructure/` or closely related test infrastructure, with no mixing of unrelated services or libs.

**Dependency fit**: The group A strict chain (ORM models → migrations → repositories) is a hard sequential dependency — migrations can only be written after models exist, and repositories can only be implemented after both. Group B (UoW) requires all repositories to exist. Group C tasks are genuinely parallel after UoW is available.

**Size**: 7 tasks — within the [1, 20] bound. The lower count reflects the high complexity and line-count of each task (e.g., 26 ORM models, 8 repository ABCs with full adapters, Alembic migration cycle, testcontainers setup).

**Parallelism**: Groups A and B are sequential due to hard import dependencies; group C unlocks 3 tasks simultaneously once UoW is ready.

---

## Implementation instructions

### MD-014 — SQLAlchemy ORM models (26 tables)

1. Create `services/market-data/src/market_data/infrastructure/db/base.py`:
   - `Base = declarative_base()`.
   - `TimestampMixin` with `created_at` and `updated_at` columns (auto-set to UTC via `utc_now()` server default; `updated_at` uses `onupdate`).
2. Create `services/market-data/src/market_data/infrastructure/db/models/securities.py` — `SecurityModel`: UUID primary key (server-generated), `figi` (VARCHAR, UNIQUE, nullable), `isin` (VARCHAR, nullable), `name`, `sector`, `industry`, `country`, `currency`. Apply `TimestampMixin`.
3. Create `services/market-data/src/market_data/infrastructure/db/models/instruments.py` — `InstrumentModel`: UUID primary key, FK → `securities.id`, `symbol`, `exchange`, UNIQUE constraint on `(symbol, exchange)`, `has_ohlcv BOOL`, `has_quotes BOOL`, `has_fundamentals BOOL`. Apply `TimestampMixin`.
4. Create `services/market-data/src/market_data/infrastructure/db/models/ohlcv.py` — `OHLCVBarModel`: composite primary key `(instrument_id, timeframe, bar_date)`, `NUMERIC(18,8)` precision for all price and volume fields, `adjusted_close NUMERIC(18,8)`, `provider_priority SMALLINT`. Define as a standard SQLAlchemy table — do NOT use PostgreSQL partitioning syntax here; TimescaleDB hypertable conversion happens in the migration.
5. Create `services/market-data/src/market_data/infrastructure/db/models/quotes.py` — `QuoteModel`: `instrument_id` as primary key (latest quote per instrument), `bid`, `ask`, `last`, `volume` as `NUMERIC(18,8)`, `timestamp TIMESTAMPTZ`.
6. Create `services/market-data/src/market_data/infrastructure/db/models/fundamentals/` directory with one model file per fundamentals section (aligned with the 14 section types from MD-002). Each model references `instrument_id` FK and `period_type`, `period_end_date`.
7. Create `services/market-data/src/market_data/infrastructure/db/models/infrastructure.py`:
   - `IngestionEventModel`: UUID `event_id` (UNIQUE, not PK — idempotency dedup), `event_type`, `occurred_at`.
   - `FailedTaskModel`: UUID PK, `task_type`, `payload JSONB`, `attempts SMALLINT DEFAULT 0`, `max_attempts SMALLINT DEFAULT 5`, `next_attempt_at TIMESTAMPTZ`, `last_error TEXT`, `status VARCHAR`. **Critical**: fix the legacy model↔migration mismatch on `failed_tasks` columns identified in the planning response — document the fix in handoff evidence.
   - `OutboxEventModel`: UUID PK, `event_type`, `topic`, `payload JSONB`, `status VARCHAR DEFAULT 'PENDING'`, `claimed_by VARCHAR`, `claimed_at TIMESTAMPTZ`, `lease_expires_at TIMESTAMPTZ`, `attempts SMALLINT DEFAULT 0`, `dispatched_at TIMESTAMPTZ`. **Critical**: fix the legacy column mismatch on `outbox_events` — document the fix in handoff evidence.
8. Create `services/market-data/src/market_data/infrastructure/db/models/__init__.py` — import all models so `Base.metadata` is complete.
9. Write unit tests in `services/market-data/tests/unit/test_models.py`: `test_security_model_columns`, `test_instrument_model_unique_constraint`, `test_ohlcv_model_composite_pk`, `test_quote_model_pk`, `test_fundamentals_model_fk_constraints`, `test_infrastructure_models`.
10. Update `docs/services/market-data.md` database schema section with all 26 table definitions (column names, types, constraints, indexes).
11. Run: `cd services/market-data && make test -- tests/unit/test_models.py && make lint`.

**DoD**: All 26 ORM models defined, `Base.metadata` complete, legacy column mismatches fixed and documented, all 6 unit tests pass, DB schema section in `docs/services/market-data.md` updated.

---

### MD-015 — Alembic migrations + TimescaleDB hypertable (after MD-014)

1. Update `services/market-data/alembic/env.py`:
   - Import `Base` from `market_data.infrastructure.db.base`.
   - Set `target_metadata = Base.metadata`.
   - Ensure async engine support (use `run_async_migrations` pattern if not already present).
2. Create `services/market-data/alembic/versions/001_initial_schema.py`:
   - Create all 26 tables in dependency order (securities → instruments → ohlcv_bars, quotes, fundamentals, infrastructure tables).
   - Use correct column types, indexes, and constraints as defined in MD-014.
   - Add indexes: UNIQUE `(symbol, exchange)` on `instruments`, UNIQUE `figi` on `securities`, `(instrument_id, bar_date DESC)` on `ohlcv_bars`.
   - Keep `ohlcv_bars` as a standard PostgreSQL table (no partitioning syntax here).
   - Implement `downgrade()` that drops all tables in reverse dependency order.
3. Create `services/market-data/alembic/versions/002_timescaledb_hypertable.py`:
   - `op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")`.
   - `op.execute("SELECT create_hypertable('ohlcv_bars', 'bar_date', migrate_data => true, chunk_time_interval => INTERVAL '1 month')")`.
   - Implement `downgrade()` that removes the hypertable designation (e.g., via `SELECT remove_continuous_aggregate_policy` or by dropping and recreating as a standard table — document the chosen approach).
4. Create the ADR file documenting the TimescaleDB choice:
   - Path: `docs/architecture/decisions/XXXX-timescaledb-hypertable-vs-list-partitioning.md` (use the next available ADR number).
   - Required content: context, decision drivers, considered alternatives (PostgreSQL list partitioning, pg_partman), decision, consequences, rollback path.
5. Update `docs/services/market-data.md` migration section with: migration filenames, what each migration does, how to run the migration cycle, and a link to the ADR.
6. Run the full migration cycle to verify correctness (requires a local TimescaleDB instance or Docker):
   ```bash
   alembic upgrade head
   alembic downgrade base
   alembic upgrade head
   ```

**DoD**: `env.py` updated, migrations 001 and 002 created with working `upgrade()` and `downgrade()`, TimescaleDB ADR created, migration cycle runs clean, `docs/services/market-data.md` migration section updated.

---

### MD-016 — Repository ports (ABCs) + PostgreSQL adapters (after MD-014, MD-012 ✓)

1. Create `services/market-data/src/market_data/application/ports/repositories.py` with the following ABCs (use Python `abc.ABC` + `@abstractmethod`):
   - `SecurityRepository`: `find_by_figi(figi) -> Security | None`, `find_by_isin(isin) -> Security | None`, `upsert(security) -> Security`.
   - `InstrumentRepository`: `find_by_symbol_exchange(symbol, exchange) -> Instrument | None`, `find_by_id(id) -> Instrument | None`, `search(query) -> list[Instrument]`, `upsert(instrument) -> Instrument`, `update_flags(id, flags)`.
   - `OHLCVRepository`: `bulk_upsert_with_priority(bars: list[OHLCVBar])`, `find_by_instrument_timeframe_range(instrument_id, timeframe, start, end) -> list[OHLCVBar]`, `get_available_timeframes(instrument_id) -> list[Timeframe]`, `get_date_range(instrument_id, timeframe) -> tuple[date, date] | None`.
   - `QuoteRepository`: `upsert(quote) -> Quote`, `find_by_instrument(instrument_id) -> Quote | None`, `find_by_instruments(ids: list[UUID]) -> list[Quote]`.
   - `FundamentalsRepository`: per-section `upsert_<section>(data)` methods + `merge_upsert(fundamentals: CanonicalFundamentals, instrument_id)`.
   - `IngestionEventRepository`: `exists(event_id) -> bool`, `create(event)`.
   - `FailedTaskRepository`: `create(task)`, `find_retryable(limit) -> list[FailedTask]`, `increment_attempts(task_id)`, `mark_dead(task_id)`.
   - `OutboxEventRepository`: `create(event)`, `find_pending(limit) -> list[OutboxEvent]`, `claim(event_id, worker_id, lease_expires_at) -> bool`, `mark_dispatched(event_id)`, `release_stale(stale_before: datetime)`.
2. Create PostgreSQL adapters in `services/market-data/src/market_data/infrastructure/db/repositories/` (one file per repository):
   - Each adapter receives a `AsyncSession` via constructor injection.
   - **Critical for `OHLCVRepository.bulk_upsert_with_priority()`**: use `INSERT ... ON CONFLICT (instrument_id, timeframe, bar_date) DO UPDATE SET ... WHERE EXCLUDED.provider_priority >= ohlcv_bars.provider_priority`. This prevents lower-priority data from overwriting higher-priority data. Implement using SQLAlchemy `insert().on_conflict_do_update()` with a `where` clause.
   - Map ORM model instances to/from domain entities; never leak ORM models outside the adapter.
3. Write unit tests in `services/market-data/tests/unit/test_repositories.py` (mock SQLAlchemy `AsyncSession`):
   - `test_ohlcv_bulk_upsert_sql_generation` — assert the generated SQL contains the `WHERE EXCLUDED.provider_priority` clause.
   - `test_instrument_search_filters` — assert correct WHERE clauses for search.
   - `test_ingestion_event_exists_check` — assert EXISTS query.
4. Update `docs/services/market-data.md` data access section with:
   - Repository ABCs table for each ABC (method → when called → what to do → what to return).
   - Provider priority upsert SQL snippet showing the `ON CONFLICT ... WHERE` clause.
5. Run: `cd services/market-data && make test -- tests/unit/test_repositories.py && make lint`.

**DoD**: 8 repository ABCs defined, 8 PostgreSQL adapters implemented, `bulk_upsert_with_priority()` uses provider-priority WHERE clause, all 3 unit tests pass, ABCs tables in docs.

---

### MD-017 — Unit of Work (async, read/write splitting) (after MD-016)

1. Create `services/market-data/src/market_data/infrastructure/db/session.py`:
   - `create_async_engine(settings: DatabaseSettings) -> AsyncEngine` — primary (read/write) engine.
   - `create_read_engine(settings: DatabaseSettings) -> AsyncEngine` — read replica engine (falls back to primary if no replica URL configured).
   - `create_session_factory(engine: AsyncEngine) -> async_sessionmaker`.
   - `create_read_session_factory(engine: AsyncEngine) -> async_sessionmaker`.
2. Create `services/market-data/src/market_data/application/ports/uow.py` with `UnitOfWork` ABC:
   - Async context manager protocol (`__aenter__`, `__aexit__`).
   - `commit()`, `rollback()` async methods.
   - Repository property accessors for all 8 repository types.
   - `collect_event(event: DomainEvent)` — accumulates domain events for outbox dispatch after commit.
   - `collected_events -> list[DomainEvent]` property.
3. Create `services/market-data/src/market_data/infrastructure/db/uow.py` with `SqlAlchemyUnitOfWork(UnitOfWork)`:
   - Constructor: write session factory, read session factory, optional outbox notifier callable.
   - Lazily create repository adapters on first property access (pass the active session).
   - On `commit()`: commit the write session, then call outbox notifier with `collected_events` if any events were accumulated. Clear `collected_events` after dispatch.
   - On `__aexit__` with exception: rollback and re-raise.
   - Read operations use the read session; write operations (repositories that mutate) use the write session.
4. Write unit tests in `services/market-data/tests/unit/test_uow.py`:
   - `test_uow_commit_commits_session`.
   - `test_uow_rollback_on_exception`.
   - `test_uow_collects_events`.
   - `test_uow_notifies_outbox_on_commit`.
5. Update `docs/services/market-data.md` UoW pattern section with:
   - Mermaid sequence diagram of the commit flow (session.commit → outbox notifier → dispatch) — required because this flow has ≥3 components and ≥4 steps.
   - Read/write splitting explanation.
   - UoW ABC table (method → when called → what to do → what to return).
6. Run: `cd services/market-data && make test -- tests/unit/test_uow.py && make lint`.

**DoD**: `UnitOfWork` ABC + `SqlAlchemyUnitOfWork`, read/write session splitting, event accumulation + outbox notification on commit, all 4 unit tests pass, Mermaid diagram in docs.

---

### MD-018 — TimescaleDB query utilities (after MD-014, MD-015, MD-016, MD-017)

1. Create `services/market-data/src/market_data/infrastructure/db/queries/ohlcv_queries.py` with the following functions (all using parameterized SQL — no string interpolation):
   - `get_bars_by_range(session, instrument_id, timeframe, start, end) -> list[OHLCVBar]` — chunk-pruning range query exploiting the TimescaleDB hypertable on `bar_date`.
   - `get_latest_bar(session, instrument_id, timeframe) -> OHLCVBar | None`.
   - `get_bar_count(session, instrument_id, timeframe) -> int`.
   - `get_available_date_range(session, instrument_id, timeframe) -> tuple[date, date] | None` — returns `(min_date, max_date)`.
   - `downsample_to_timeframe(session, instrument_id, source_timeframe, target_timeframe, start, end) -> list[OHLCVBar]` — uses PostgreSQL `time_bucket` aggregate (provided by TimescaleDB) to resample from a finer timeframe (e.g., 1m → 5m).
2. Write unit tests in `services/market-data/tests/unit/test_ohlcv_queries.py`:
   - `test_ohlcv_query_range_parameters` — assert parameterized binding (no raw string interpolation in the compiled query).
   - `test_ohlcv_query_ordering` — assert `ORDER BY bar_date ASC` in range query.
   - `test_time_bucket_aggregation_sql` — assert `time_bucket` function appears in the downsample query.
3. Update `docs/services/market-data.md` query layer section with: each function's signature, purpose, required indexes, and a note on chunk-pruning behaviour.
4. Run: `cd services/market-data && make test -- tests/unit/test_ohlcv_queries.py && make lint`.

**DoD**: 5 parameterized query functions, no string interpolation, all 3 unit tests pass, query layer section in docs updated.

---

### MD-027 — MarketDataOutboxDispatcher (after MD-007 ✓, MD-013 ✓, MD-014, MD-017)

1. Create `services/market-data/src/market_data/infrastructure/messaging/outbox/dispatcher.py` with `MarketDataOutboxDispatcher(BaseOutboxDispatcher)`:
   - Topic routing:
     - `InstrumentCreated` → `market.instrument.created`
     - `InstrumentUpdated` → `market.instrument.updated`
   - Implement `_serialize_event(event: DomainEvent) -> tuple[str, str, dict]` returning `(topic, key, avro_dict)`.
   - Serialize events using Avro schema for `instrument.created.v1` (and `instrument.updated.v1`). Load schema strings from `services/market-data/src/market_data/infrastructure/messaging/schemas/`.
   - **Fix legacy bug**: ensure all `Decimal` fields are cast to `str` and all `UUID` fields are cast to `str` before constructing the Avro dict — this matches the fix applied to `BaseOutboxDispatcher` in MD-007.
2. Wire `MarketDataOutboxDispatcher` into `services/market-data/src/market_data/app.py` lifespan stub (registration only — full wiring with UoW will happen in a later wave):
   - Instantiate dispatcher in the `lifespan` async context manager.
   - Call `dispatcher.start()` on startup, `dispatcher.stop()` on shutdown.
3. Write unit tests in `services/market-data/tests/unit/test_outbox_dispatcher.py`:
   - `test_dispatcher_routes_instrument_created` — assert topic = `market.instrument.created`.
   - `test_dispatcher_routes_instrument_updated` — assert topic = `market.instrument.updated`.
   - `test_dispatcher_serializes_avro` — assert output dict matches expected schema shape.
   - `test_dispatcher_decimal_uuid_serialization` — assert `Decimal` → `str` and `UUID` → `str` conversion before encoding.
4. Update `docs/services/market-data.md` outbox section with: topic routing table, Avro schema references, Decimal/UUID serialization note.
5. Run: `cd services/market-data && make test -- tests/unit/test_outbox_dispatcher.py && make lint`.

**DoD**: `MarketDataOutboxDispatcher` with topic routing and Decimal/UUID fix, registered in lifespan stub, all 4 unit tests pass, outbox section in docs updated.

---

### MD-028 — Integration test infrastructure (testcontainers) (after MD-015)

1. Add dev dependencies to `services/market-data/pyproject.toml`:
   - `testcontainers[postgres,kafka,minio]` (check for current compatible version).
   - `valkey` (or `redis` with valkey connection, depending on the client used in MD-008).
2. Create `services/market-data/tests/integration/conftest.py` with:
   - **Session-scoped container fixtures** (start once per test session):
     - `pg_container` — uses `timescale/timescaledb:latest-pg16` image, database name `market_data_db`.
     - `kafka_container` — uses `confluentinc/cp-kafka` with Schema Registry sidecar (or use `testcontainers-kafka` helper).
     - `minio_container` — uses `minio/minio` image, creates a test bucket on startup.
     - `valkey_container` — uses `valkey/valkey:7` image.
   - **Function-scoped fixtures** (reset state between tests):
     - `db_session` — runs Alembic migrations against `pg_container` on first use; yields an `AsyncSession`; truncates all tables (in dependency order) after each test.
     - `uow` — yields a `SqlAlchemyUnitOfWork` backed by `db_session`.
     - `object_storage` — yields an `S3ObjectStorage` pointed at `minio_container`.
     - `valkey_client` — yields a `ValkeyClient` pointed at `valkey_container`.
3. Create `services/market-data/tests/integration/fixtures/` with sample data files:
   - `sample_ohlcv.jsonl` — 5 valid OHLCV bars.
   - `sample_quotes.json` — 1 valid quote.
   - `sample_fundamentals.json` — partial fundamentals (3 sections populated, rest omitted).
4. Register pytest markers in `services/market-data/pyproject.toml` `[tool.pytest.ini_options]`:
   - `integration: marks tests as requiring external containers`
   - `slow: marks tests as expected to run slowly`
5. Write smoke tests in `services/market-data/tests/integration/test_infra_smoke.py`:
   - `test_pg_container_starts` — connect and `SELECT 1`.
   - `test_migrations_run_successfully` — confirm `alembic_version` table contains `002` after `upgrade head`.
   - `test_kafka_container_starts` — produce and consume one message.
   - `test_minio_container_starts` — put and get one object.
   - `test_valkey_container_starts` — set and get one key.
6. Update developer testing docs (`docs/developer-guide/testing.md` or root `README.md` if no dedicated testing doc exists) with:
   - How to run integration tests: `cd services/market-data && make test -- tests/integration/ -m integration -v`.
   - Docker requirement and container startup time note.
   - How to run only smoke tests vs full integration suite.
7. Run: `cd services/market-data && make test -- tests/integration/ -m integration -v`.

**DoD**: 4 session-scoped container fixtures + 4 function-scoped fixtures, 3 sample data fixture files, `integration` and `slow` markers registered, all 5 smoke tests pass with Docker available, developer testing docs updated.

---

## Constraints

- Do not implement any code outside the task IDs listed in this wave (MD-014 through MD-018, MD-027, MD-028).
- No API handlers, FastAPI routers, application service orchestration, or CLI entrypoints.
- Do not write application-layer use case classes — that is a later wave.
- Do not modify lib files (except to import in service code). All lib code was completed in wave 01.
- Keep ORM models and domain entities strictly separated — ORM models live in `infrastructure/db/models/`, domain entities live in `domain/`. Repository adapters perform all mapping.
- The `ohlcv_bars` table must be created as a standard table in migration 001 and converted to a TimescaleDB hypertable in migration 002. Do not merge these into one migration.
- All queries in MD-018 must use parameterized bindings. Never use Python string formatting or f-strings to embed user-controlled values into SQL.
- One logical change per edit. Do not combine unrelated changes in a single diff.
- All timestamps must use `utc_now()` from `libs/common` or `datetime.now(tz=timezone.utc)`. Never use naive datetimes.

## Regression guardrails (compounding, mandatory)

- For outbox dispatcher wiring, apply [BP-001] and [BP-009]: use `OutboxEventValueSerializer` and never pass raw dict as dispatcher config.
- For schema/migration work, apply [BP-007] and [BP-008]: enforce `NULLS NOT DISTINCT` when needed and keep initial schema migration synchronized with ORM.
- For dockerized runtime validation in this wave, apply [BP-010] and [BP-011]: non-HTTP workers need explicit healthchecks, and non-code runtime assets (schemas) must be copied into images.
- For Alembic execution paths, apply [BP-006] to ensure env-driven DB URLs are used in containers.
- If adding async polling tests, apply [BP-012] and [BP-013]: scalar-column polling, bounded deadlines, deterministic pass conditions.

---

## Incremental quality gates (mandatory)

For each task ID, before moving to the next task, run and pass:

1. Targeted test command(s) for the task's changed behavior.
2. `ruff check` on changed paths only.
3. `mypy` on changed package/module only.

- No deferred fixes: do not carry ruff/mypy/test failures into later tasks.
- If the same failure repeats twice, capture root cause + remediation in handoff evidence.

## Required tests

### Unit tests

```bash
cd services/market-data && make test -- tests/unit/ && make lint
```

### Migration cycle test (requires TimescaleDB — local or Docker)

```bash
cd services/market-data
alembic upgrade head
alembic downgrade base
alembic upgrade head
```

### Integration smoke tests (requires Docker)

```bash
cd services/market-data && make test -- tests/integration/ -m integration -v
```

### Global lint

```bash
cd services/market-data && make lint
./scripts/lint.sh
```

**Pass criteria:**
- All unit tests pass (`pytest` exit code 0).
- Migration upgrade + downgrade + upgrade cycle completes without error.
- All 5 integration smoke tests pass with Docker available.
- `ruff check` reports zero errors across all changed files.
- `mypy --strict` reports zero errors across all changed files.
- No regressions in previously passing tests.

---

## Documentation requirements

For every task in this wave, update docs **in the same wave** for any change to behaviour, contracts, config, schema, or API surface.

| Change type | File to update |
|-------------|---------------|
| DB schema (26 tables) | `docs/services/market-data.md` — schema section (all table definitions) |
| Alembic migrations + TimescaleDB decision | `docs/services/market-data.md` — migration section; new ADR in `docs/architecture/decisions/` |
| Repository ABCs | `docs/services/market-data.md` — data access section (ABCs table, provider priority upsert SQL) |
| UoW pattern | `docs/services/market-data.md` — UoW section (Mermaid sequence diagram, ABC table) |
| TimescaleDB query layer | `docs/services/market-data.md` — query layer section (all 5 functions) |
| MarketDataOutboxDispatcher | `docs/services/market-data.md` — outbox section (topic routing table, Avro schema references) |
| Integration test setup | `docs/developer-guide/testing.md` (or equivalent) — container setup, how to run, markers |

**Mandatory instruction**: If any implementation changes a behaviour, contract, config, schema surface, or test surface described in documentation, you MUST update that documentation in this same wave. List every doc file changed in the handoff evidence.

**Documentation quality gate**: Before marking this wave done, verify all 8 criteria from the Documentation quality standard and include the quality checklist table in handoff evidence. All criteria must be ✓ or explicitly N/A with justification.

---

## Required handoff evidence

At wave completion, report all of the following:

### 1. Changed files (complete list)

List every file created or modified, with a one-line description of the change.

### 2. Tests run and results

```
services/market-data (unit):          X tests, X passed, 0 failed
services/market-data (migration cycle): upgrade head → downgrade base → upgrade head: CLEAN
services/market-data (integration):   X tests, X passed, 0 failed
./scripts/lint.sh:                    exit code 0
```

### 3. Documentation changed (exact files + what was updated)

Example format:
- `docs/services/market-data.md` — added DB schema section (26 tables), migration section, data access section (ABCs tables), UoW section (Mermaid diagram), query layer section, outbox section.
- `docs/architecture/decisions/XXXX-timescaledb-hypertable-vs-list-partitioning.md` — new ADR created.
- `docs/developer-guide/testing.md` — added integration test setup, container requirements, marker usage.

### 4. Unresolved blockers

List anything that could not be implemented as specified and why. Include any legacy column mismatch fixes applied in MD-014 that deviated from the original spec. State `none` if there are no blockers.

### 5. Documentation quality checklist

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 1 | Accuracy — endpoints, fields, event types, config vars match implementation | ✓ / ⚠️ / N/A | |
| 2 | Diagrams for non-trivial flows (≥3 components or ≥4 steps → Mermaid) | ✓ / ⚠️ / N/A | |
| 3 | Realistic code examples — every new public class/function has working usage example | ✓ / ⚠️ / N/A | |
| 4 | Abstract methods documented — ABC table (method → when called → what to do → what to return) | ✓ / ⚠️ / N/A | |
| 5 | Common Pitfalls section — `docs/services/market-data.md` has ≥3 entries | ✓ / ⚠️ / N/A | |
| 6 | Lib docs updated — no lib files touched in wave 02 (N/A if confirmed) | ✓ / ⚠️ / N/A | |
| 7 | Service doc reflects final state — `docs/services/market-data.md` matches implementation | ✓ / ⚠️ / N/A | |
| 8 | No orphan documentation — no docs for unimplemented code | ✓ / ⚠️ / N/A | |

### 6. Commit message proposal

```
feat(market-data/db+infra): DB schema, migrations, repositories, UoW, outbox + test infra (MD-014..MD-018, MD-027, MD-028)

Implement all 26 SQLAlchemy ORM models with fixed legacy column mismatches; create Alembic
migrations 001 (initial schema) and 002 (TimescaleDB hypertable for ohlcv_bars); implement
repository ports (ABCs) and PG adapters with provider-priority bulk-upsert SQL; implement async
UoW with read/write session splitting; implement MarketDataOutboxDispatcher with Decimal/UUID
serialization fix; set up testcontainers integration test infra (TimescaleDB, Kafka, MinIO,
Valkey). All unit tests pass; migration upgrade+downgrade cycle clean; integration smoke tests pass.
```

---

## Definition of done

- [ ] MD-014: All 26 ORM models defined, `Base.metadata` complete, legacy column mismatches on `failed_tasks` and `outbox_events` fixed and documented in handoff, all 6 unit tests pass, DB schema section in `docs/services/market-data.md` updated.
- [ ] MD-015: `env.py` updated with `Base.metadata`, migration 001 (initial schema) and migration 002 (TimescaleDB hypertable) created, both `upgrade()` and `downgrade()` work, TimescaleDB ADR created, migration cycle runs clean, `docs/services/market-data.md` migration section updated.
- [ ] MD-016: 8 repository ABCs defined, 8 PostgreSQL adapters implemented, `bulk_upsert_with_priority()` uses `ON CONFLICT ... WHERE EXCLUDED.provider_priority` clause, all 3 unit tests pass, ABCs tables in `docs/services/market-data.md` data access section.
- [ ] MD-017: `UnitOfWork` ABC + `SqlAlchemyUnitOfWork` with read/write session splitting, event accumulation, outbox notification on commit, all 4 unit tests pass, Mermaid sequence diagram + ABC table in `docs/services/market-data.md` UoW section.
- [ ] MD-018: 5 parameterized query functions, no string interpolation, all 3 unit tests pass, query layer section in `docs/services/market-data.md` updated.
- [ ] MD-027: `MarketDataOutboxDispatcher` with topic routing for `InstrumentCreated` and `InstrumentUpdated`, Decimal/UUID serialization fix confirmed, registered in lifespan stub, all 4 unit tests pass, outbox section in `docs/services/market-data.md` updated.
- [ ] MD-028: 4 session-scoped container fixtures, 4 function-scoped fixtures, 3 sample data files, `integration` and `slow` markers registered, all 5 smoke tests pass, developer testing docs updated.
- [ ] DB schema fully documented in `docs/services/market-data.md` (all 26 tables with columns, types, constraints, indexes).
- [ ] TimescaleDB ADR created in `docs/architecture/decisions/`.
- [ ] Repository ABCs table in `docs/services/market-data.md` (method → when called → what to do → what to return) for all 8 ABCs.
- [ ] UoW Mermaid sequence diagram in `docs/services/market-data.md`.
- [ ] `docs/services/market-data.md` includes `## Common Pitfalls` with ≥3 entries (add if not already present from wave 01).
- [ ] Documentation quality gate: all 8 criteria confirmed ✓ or N/A with justification — no criterion left blank.
- [ ] Migration cycle test (`upgrade head` → `downgrade base` → `upgrade head`) documented as passing in handoff evidence.
- [ ] Integration smoke tests passing result documented in handoff evidence.
- [ ] `./scripts/lint.sh` passes with zero errors.
- [ ] Commit message proposal included in handoff evidence.
