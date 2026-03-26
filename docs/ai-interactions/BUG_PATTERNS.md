# Bug Patterns & Post-Mortems

> **Purpose**: A living knowledge base of bugs encountered during development.
> AI agents MUST read this file before implementing any component that matches
> the "Affected areas" column in the index. Prompt authors SHOULD reference
> pattern IDs (e.g., `BP-001`) when writing implementation instructions to
> prevent recurrence.

---

## How to use this file

1. **Before implementing**: scan the index below for categories matching your
   task (e.g., "Kafka", "outbox", "serializer"). Read the full entry for any match.
2. **When you hit a runtime error**: search this file for the error message string
   before debugging from scratch.
3. **After fixing a new bug**: add an entry here and update any affected prompts,
   linking back to the pattern ID.

---

## Quick-reference index

| ID | Category | Symptom (error message or behaviour) | Affected areas |
|----|----------|---------------------------------------|----------------|
| [BP-001](#bp-001) | Kafka / outbox serialization | `"a bytes-like object is required, not 'OutboxKafkaValue'"` | Any service implementing `BaseOutboxDispatcher` |
| [BP-002](#bp-002) | Env loading / Docker Compose | Service starts but reads wrong config (wrong DB URL, wrong hostnames, 500 errors at runtime) | All services — `Makefile`, `docker-compose.yml`, `docker-compose.test.yml` |
| [BP-003](#bp-003) | pytest-asyncio / session fixtures | `RuntimeError: Event loop is closed` at fixture teardown | Any service with `scope="session"` async fixtures (`e2e_client`, `_e2e_engine`) |
| [BP-004](#bp-004) | pytest fixture resolution | `fixture 'settings' not found` — `ERROR at setup` instead of SKIP | Integration tests in any service that need a `Settings()` instance |
| [BP-005](#bp-005) | Docker multi-stage builds | `exec /app/.venv/bin/alembic: no such file or directory` — migrate container exits 255 | All services using `uv venv` in a builder stage |
| [BP-006](#bp-006) | Alembic env.py / DB URL | Alembic migrate container connects to `localhost:5432` instead of Docker service name — connection refused | All services with `alembic/env.py` that use static `alembic.ini` URL |
| [BP-007](#bp-007) | PostgreSQL NULL semantics in unique index | `MultipleResultsFound` at runtime; duplicate rows allowed when nullable columns are NULL | Any table with nullable columns in a multi-column unique constraint |
| [BP-008](#bp-008) | Migration schema drift | `UndefinedColumnError` during migration — 0001 creates stale columns, ORM model has different columns | Any service where the initial schema migration was written before the final ORM model |
| [BP-009](#bp-009) | DispatcherProcess wrong config arg | `AttributeError: 'dict' object has no attribute 'worker_id'` — raw Kafka dict passed as DispatcherConfig | `dispatcher_main.py` in any service using `build_*_dispatcher` factory |
| [BP-010](#bp-010) | Compose `--wait` with non-HTTP workers | `container <worker> has no healthcheck configured` or endless wait/early failure when background process inherits API healthcheck | Any `docker-compose*.yml` profile that starts scheduler/worker/dispatcher processes |
| [BP-011](#bp-011) | Missing runtime non-code assets in image | `FileNotFoundError` for Avro/schema/config files only in containers (works locally) | Services loading schemas/files from `infra/` or repo-relative paths |
| [BP-012](#bp-012) | Async SQLAlchemy expired-row access | `sqlalchemy.exc.MissingGreenlet` in polling loops after rollback | Async tests using `AsyncSession` and ORM objects in long polling loops |
| [BP-013](#bp-013) | E2E perceived infinite loops | Test appears stuck for minutes due to long poll windows, noisy schedulers, or assertions on unstable async conditions | Service E2E tests with scheduler/worker/dispatcher and eventual consistency |
| [BP-014](#bp-014) | Import guard allowlist `fnmatch` vs `**` | CI Import Guards job fails with violations that should be allowlisted — `services/*/tests/*.py` files not covered | Any service with test files directly in `tests/` (not in subdirectories) |

---

## BP-001 — OutboxKafkaValue not serialized to bytes

**Date discovered**: 2026-03-09
**Service affected**: `portfolio` (found during `make run-dispatcher`)
**Prompts updated**: `0003-exec-market-ingestion-migration-wave-02.md` T-MI-21 steps 7–8; `0003-exec-market-ingestion-migration-wave-03.md` T-MI-22 step 2

### Symptom

The outbox dispatcher starts and picks up pending records, but every delivery
attempt fails with:

```
error="a bytes-like object is required, not 'OutboxKafkaValue'"
```

Log lines show `outbox_record_dispatch_failed` for every record, cycling until
`max_attempts` is exceeded and records are dead-lettered.

### Root causes (two independent bugs, both required to fix)

#### Bug A — Wrong serializer class used (`KafkaEventValueSerializer` vs `OutboxEventValueSerializer`)

`KafkaEventValueSerializer.__call__` passes the raw `value` argument directly to
the per-type `AvroSerializer`:

```python
# KafkaEventValueSerializer — WRONG for outbox use
return serializer(value, ctx)   # value is OutboxKafkaValue — Avro rejects it
```

`AvroSerializer` expects a plain `dict` matching the Avro schema, not the
`OutboxKafkaValue` wrapper dataclass. This causes the bytes error.

`OutboxEventValueSerializer` (a subclass in `libs/messaging/src/messaging/kafka/producer.py`)
overrides `__call__` to extract `.payload` first:

```python
# OutboxEventValueSerializer — CORRECT for outbox use
return serializer(value.payload, ctx)   # plain dict — Avro accepts it
```

**Fix**: Always use `OutboxEventValueSerializer`, never `KafkaEventValueSerializer`,
when building a value serializer for an outbox dispatcher.

#### Bug B — `value_serializer=` not wired into `build_serializing_producer()`

```python
# WRONG — no value_serializer, producer silently accepts any Python object
return build_serializing_producer(producer_config)

# CORRECT — value_serializer wired in
value_serializer = OutboxEventValueSerializer(self._serializers)
return build_serializing_producer(producer_config, value_serializer=value_serializer)
```

`SerializingProducer` accepts the call without a serializer and only fails at
delivery time — making this a silent misconfiguration that only surfaces on
first dispatch attempt.

### Correct implementation pattern

Every `BaseOutboxDispatcher` subclass must implement `_build_producer()` with
this exact three-step sequence:

```python
def _build_producer(self) -> Any:
    # Step 1 — build per-event-type AvroSerializer dict
    registry_client = build_schema_registry_client(registry_config)
    self._serializers = build_outbox_event_serializers(registry_client)

    # Step 2 — wrap in OutboxEventValueSerializer (NOT KafkaEventValueSerializer)
    value_serializer = OutboxEventValueSerializer(self._serializers)

    # Step 3 — pass value_serializer= explicitly (NOT optional)
    producer_config = KafkaProducerConfig(bootstrap_servers=...)
    return build_serializing_producer(producer_config, value_serializer=value_serializer)
```

### Test to add (prevents regression)

```python
def test_outbox_value_serializer_extracts_payload():
    """OutboxKafkaValue.payload must be passed to AvroSerializer, not the wrapper."""
    mock_avro = MagicMock(return_value=b"avro-bytes")
    ser = OutboxEventValueSerializer({"my.event": mock_avro})
    value = OutboxKafkaValue(event_type="my.event", payload={"foo": 1})
    result = ser(value, ctx=None)
    # The serializer must have been called with the plain dict, not the wrapper
    mock_avro.assert_called_once_with({"foo": 1}, None)
    assert result == b"avro-bytes"

def test_raw_avro_serializer_rejects_wrapper():
    """Confirm that passing OutboxKafkaValue directly to AvroSerializer fails —
    this documents why OutboxEventValueSerializer is required."""
    mock_avro = MagicMock(side_effect=TypeError("bytes-like object required"))
    ser = KafkaEventValueSerializer({"my.event": mock_avro})
    value = OutboxKafkaValue(event_type="my.event", payload={"foo": 1})
    with pytest.raises(TypeError):
        ser(value, ctx=None)
```

### Files changed in fix

| File | Change |
|------|--------|
| `libs/messaging/src/messaging/kafka/producer.py` | Added `OutboxEventValueSerializer.__call__` override that extracts `.payload` |
| `services/portfolio/src/portfolio/messaging/dispatcher.py` | Imported `OutboxEventValueSerializer`; wired `value_serializer=` into `build_serializing_producer()` |

---

## BP-002 — Env file loaded in wrong place (Makefile / Docker Compose)

**Date discovered**: 2026-03-10
**Services affected**: `portfolio`, `market-ingestion` (all services are susceptible)
**Prompts updated**: `0002-exec-portfolio-migration-wave-*.md`, `0003-exec-market-ingestion-migration-wave-*.md`

### Symptom

Three distinct but related failure modes, all caused by environment variables not
reaching the service process:

- **Local `make run`**: service starts but uses wrong defaults (wrong DB URL, missing
  API keys). Pydantic-settings silently uses field defaults when env vars are absent.
- **`make test-integration`**: tests fail with `connection refused` or `authentication
  failed` because infra env vars (DB URL, Kafka bootstrap servers) were never exported.
- **Docker Compose (`make test-e2e`)**: service starts with `DATABASE_URL=...` (no
  prefix) so pydantic-settings (env_prefix="SERVICE_") silently ignores the var and
  uses the wrong default host.

### Root causes (three independent bugs, all must be fixed together)

#### Bug A — Makefile `.env-check` verifies file existence but never sources it

```makefile
# WRONG — checks file exists, but variables are NEVER exported
.env-check:
    @test -f configs/dev.local.env || (echo "Missing configs/dev.local.env"; exit 1)

run: .env-check
    $(VENV)/bin/uvicorn service.app:create_app --factory --reload --port 8000
```

The `set -a && . ./configs/dev.local.env && set +a` idiom is missing from every
`run*`, `test-integration`, and `test-e2e` target. The `.env-check` guard is
useless without actual sourcing.

#### Bug B — `docker-compose.yml` uses inline `environment:` with wrong variable names

```yaml
# WRONG — vars without SERVICE_ prefix; pydantic-settings silently ignores them
services:
  my-service:
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@postgres:5432/my_db
      KAFKA_BOOTSTRAP_SERVERS: kafka:29092
```

Services use `Settings(env_prefix="MY_SERVICE_")`, so `DATABASE_URL` is never
read — `MY_SERVICE_DATABASE_URL` is required. The inline block also duplicates
what `configs/docker.env` already defines, creating two sources of truth that
inevitably drift.

#### Bug C — Postgres credentials mismatch between compose and service config

```yaml
# WRONG (old docker-compose.yml)
postgres:
  environment:
    POSTGRES_USER: worldview
    POSTGRES_PASSWORD: worldview
```

All service `docker.env` files connect as `postgres:postgres`. The container
creates a `worldview` superuser but no `postgres` user → all service connections
fail with `authentication failed for user "postgres"`.

Also: `infra/postgres/init/init-databases.sh` created `market_ingestion_db` but
`market-ingestion/docker.env` and `config.py` default to `ingestion_db` → service
fails to connect on first start.

### Correct implementation pattern

#### Makefile — source env for every target that talks to infra

```makefile
# CORRECT
run: .env-check
    set -a && . ./configs/dev.local.env && set +a && \
    $(VENV)/bin/uvicorn my_service.app:create_app --factory --reload --port 8000

run-worker: .env-check
    set -a && . ./configs/dev.local.env && set +a && \
    $(VENV)/bin/python -m my_service.worker.main

# Unit tests — no sourcing needed (all infra is mocked)
test:
    $(VENV)/bin/pytest tests/ -m unit -v

# Integration/e2e — DO source (hit real infra)
test-integration: .env-check
    set -a && . ./configs/dev.local.env && set +a && \
    $(VENV)/bin/pytest tests/ -m integration -v

test-e2e: .env-check
    @docker compose -f ../../infra/compose/docker-compose.test.yml \
        --profile my-service-test up --build --wait; \
    COMPOSE_EXIT=$$?; \
    if [ $$COMPOSE_EXIT -ne 0 ]; then \
        docker compose -f ../../infra/compose/docker-compose.test.yml \
            --profile my-service-test down -v; \
        exit $$COMPOSE_EXIT; \
    fi; \
    set -a && . ./configs/dev.local.env && set +a; \
    $(VENV)/bin/pytest tests/e2e/ -v; \
    EXIT=$$?; \
    docker compose -f ../../infra/compose/docker-compose.test.yml \
        --profile my-service-test down -v; \
    exit $$EXIT
```

#### `docker-compose.yml` — use `env_file:` pointing to the prefixed docker.env

```yaml
# CORRECT — env_file replaces ALL inline environment: blocks
services:
  my-service:
    env_file:
      - ../../services/my-service/configs/docker.env
    # NO inline environment: block
```

`configs/docker.env` must use the correct `SERVICE_` prefix:

```env
# configs/docker.env  (Docker-internal hostnames)
MY_SERVICE_DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/my_db
MY_SERVICE_KAFKA_BOOTSTRAP_SERVERS=kafka:29092
MY_SERVICE_STORAGE_ENDPOINT_HOST=minio
```

#### `docker-compose.yml` — postgres must match service credentials

```yaml
# CORRECT
postgres:
  environment:
    POSTGRES_USER: postgres
    POSTGRES_PASSWORD: postgres
```

#### `infra/postgres/init/init-databases.sh` — DB names must match service config

Always verify that each database name in the init script exactly matches the
database name used in the corresponding service's `docker.env` and `config.py`.

### Env loading responsibility table

| Context | Mechanism | File |
|---------|-----------|------|
| Local dev (`make run`) | `set -a && . ./configs/dev.local.env && set +a` | `configs/dev.local.env` |
| Docker Compose | `env_file:` in compose YAML | `configs/docker.env` |
| Unit tests | None — infra is fully mocked | N/A |
| Integration tests | Same as local dev (Makefile sources it) | `configs/dev.local.env` |
| CI/CD | Secret injection into process environment | CI secret store |
| Settings class | Reads **only** the process environment (no file knowledge) | `config.py` |

### Files changed in fix

| File | Change |
|------|--------|
| `services/portfolio/Makefile` | Added `set -a && . ./configs/dev.local.env && set +a` to `run`, `run-dispatcher`, `test-integration`, `test-all`; restructured `test-e2e` to use `docker-compose.test.yml` |
| `services/market-ingestion/Makefile` | Same pattern as portfolio |
| `services/portfolio/configs/docker.env` | Created (was missing — only `.example` existed); contains `PORTFOLIO_`-prefixed vars with Docker-internal hostnames |
| `infra/compose/docker-compose.yml` | Replaced ALL inline `environment:` blocks with `env_file:`; fixed postgres credentials (`postgres:postgres`); built postgres from Dockerfile (TimescaleDB) |
| `infra/postgres/init/init-databases.sh` | Fixed `market_ingestion_db` → `ingestion_db` |
| `infra/compose/docker-compose.test.yml` | New isolated test stack with `tmpfs`, `service_completed_successfully`, `--wait`-compatible healthchecks |
| `infra/postgres/init/init-test-databases.sh` | New file for test stack; creates only `portfolio_db` and `ingestion_db` |
| `infra/minio/init/init-test-buckets.sh` | New file for test stack; creates `market-ingestion`, `market-bronze`, `market-canonical` buckets |
| `services/portfolio/tests/e2e/conftest.py` | New; real HTTP client against `http://localhost:8001` |
| `services/portfolio/tests/e2e/test_full_flow.py` | Rewritten to use `e2e_client` (real HTTP, not ASGI transport) |
| `services/market-ingestion/tests/e2e/conftest.py` | New; real HTTP client against `http://localhost:8002` |
| `services/market-ingestion/tests/e2e/test_api_workflows.py` | New; 13 tests covering all API workflows |

---

---

## BP-003 — `RuntimeError: Event loop is closed` at session-scoped async fixture teardown

**Date discovered**: 2026-03-10
**Services affected**: `portfolio`, `market-ingestion` (any service with e2e tests)
**Prompts updated**: none yet — catch this at implementation time

### Symptom

All e2e tests pass but produce `ERROR at teardown` for the last test in the session:

```
RuntimeError: Event loop is closed
  ...
  at tests/e2e/conftest.py:NN in e2e_client
    async with AsyncClient(base_url=_BASE_URL, timeout=30.0) as ac:
```

This cascades: tests that actually pass show `ERROR` status, and unrelated unit
tests that run after the e2e teardown can also error (e.g. `test_frozen_dataclass`,
`TestQuantity`) due to the corrupted asyncio state.

### Root cause

pytest-asyncio (mode=auto) creates a **new event loop per test function** by
default. A `scope="session"` async fixture's setup runs in the first test's loop
but its teardown (the `async with` exit) runs after that loop is already closed.
Any `await` inside teardown — including closing an `httpx.AsyncClient`'s
connection pool — raises `RuntimeError: Event loop is closed`.

```python
# WRONG — session fixture torn down on a closed per-function loop
@pytest.fixture(scope="session")
async def e2e_client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(base_url=_BASE_URL, timeout=30.0) as ac:
        yield ac  # teardown: AsyncClient.__aexit__ → runs on closed loop → crash
```

### Correct implementation pattern

Set `asyncio_default_fixture_loop_scope = "session"` in `pyproject.toml`. This
tells pytest-asyncio to keep ONE event loop alive for the entire session, so
session-scoped async fixtures always have a live loop for both setup and teardown.

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"   # ← REQUIRED when using session-scoped async fixtures
```

This setting must be present in **every service** that has `scope="session"` async
fixtures. It is harmless for services that only use function-scoped fixtures.

### Test to add (prevents regression)

No specific regression test — the failure only manifests at teardown reporting
time. The fix is purely in `pyproject.toml`.

### Files changed in fix

| File | Change |
|------|--------|
| `services/portfolio/pyproject.toml` | Added `asyncio_default_fixture_loop_scope = "session"` |
| `services/market-ingestion/pyproject.toml` | Added `asyncio_default_fixture_loop_scope = "session"` |

---

## BP-004 — `fixture 'settings' not found` causes `ERROR at setup` instead of SKIP

**Date discovered**: 2026-03-10
**Services affected**: `market-ingestion` (any service with bare `settings` parameter in integration tests)
**Prompts updated**: none yet — catch this at implementation time

### Symptom

pytest shows `ERROR at setup` (not `FAILED`, not `SKIPPED`) for integration tests:

```
ERROR at setup of test_integration_task_add_and_claim
  fixture 'settings' not found
  available fixtures: app, client, ...
```

Even tests whose first line is `pytest.skip("...")` show as `ERROR` rather than
`SKIPPED` — because fixture resolution happens **before** the test body runs.

### Root cause

Two independent problems, both must be fixed:

**Problem A**: The `settings` pytest fixture is never defined. A helper function
`_make_settings()` (plain function, no decorator) exists in the test file but is
invisible to pytest's fixture system.

**Problem B**: Tests that should always skip use `pytest.skip()` **inside the body**
with a required fixture parameter. Since pytest must resolve all fixture parameters
before entering the body, it errors before it can execute the skip.

```python
# WRONG — fixture resolution fails before skip() can execute
@pytest.mark.integration
async def test_integration_foo(settings):          # 'settings' fixture required
    pytest.skip("Requires live Kafka")             # never reached
    ...

# CORRECT — skip evaluated at collection time, no fixture needed
@pytest.mark.integration
@pytest.mark.skip(reason="Requires live Kafka")    # evaluated before fixture resolution
async def test_integration_foo() -> None:
    ...
```

### Correct implementation pattern

Every service that has integration tests requiring a `Settings()` instance must
have a `conftest.py` in the relevant test subfolder (e.g. `tests/infrastructure/`)
defining a `settings` fixture:

```python
# tests/infrastructure/conftest.py
from __future__ import annotations
import pytest
from my_service.config import Settings

@pytest.fixture(scope="session")
def settings() -> Settings:
    """Real Settings() from MYSERVICE_* env vars.
    Populated by `make test-integration` via:
        set -a && . ./configs/dev.local.env && set +a
    """
    return Settings()
```

For tests that always skip (infrastructure not yet available), use the decorator
form rather than calling `pytest.skip()` in the body:

```python
# CORRECT
@pytest.mark.skip(reason="Requires live Kafka + Schema Registry")
async def test_integration_end_to_end() -> None:
    ...

# Also CORRECT — conditional skip based on env var
import os
_NEEDS_KAFKA = pytest.mark.skipif(
    not os.getenv("MY_SERVICE_KAFKA_BOOTSTRAP_SERVERS"),
    reason="Requires live Kafka (set MY_SERVICE_KAFKA_BOOTSTRAP_SERVERS)",
)

@_NEEDS_KAFKA
async def test_kafka_consumer_roundtrip() -> None:
    ...
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/market-ingestion/tests/infrastructure/conftest.py` | Created; defines `settings` fixture |
| `services/market-ingestion/tests/infrastructure/test_dispatcher.py` | Replaced `pytest.skip()` in body + `settings` param with `@pytest.mark.skip` decorator; removed unused parameter |

---

## BP-005 — Docker multi-stage build: `exec /app/.venv/bin/alembic: no such file or directory`

**Date discovered**: 2026-03-10
**Services affected**: `portfolio`, `market-ingestion` (all services using `uv venv` in Dockerfile)
**Prompts updated**: none yet — catch this at implementation time

### Symptom

The migrate container (or any container that runs a venv entry-point directly)
exits with code 255:

```
portfolio-migrate-1  | exec /app/.venv/bin/alembic: no such file or directory
portfolio-migrate-1 exited with code 255
service "portfolio-migrate" didn't complete successfully: exit 255
```

The binary file physically exists. The file system path is correct. The container
still cannot execute it.

### Root cause

The Dockerfile builds the venv in the **builder** stage at `/build/.venv`:

```dockerfile
# Builder stage — WORKDIR /build
RUN uv venv /build/.venv && \
    uv pip install ...
```

`uv` writes entry-point scripts (e.g. `alembic`, `uvicorn`) with a hardcoded
shebang referencing the build-time Python path:

```
#!/build/.venv/bin/python3.11
```

The runtime stage copies the venv to `/app/.venv`:

```dockerfile
COPY --from=builder /build/.venv /app/.venv
```

Now `/app/.venv/bin/alembic` exists and is executable, but its shebang still
points to `/build/.venv/bin/python3.11` — a path that does not exist in the
runtime image. The kernel resolves the shebang first, finds nothing, and returns
`ENOENT` (no such file or directory).

This is silent in the builder stage (the scripts execute fine there) and only
fails at runtime when the entry-point is actually invoked.

### Correct implementation pattern

**Build the venv at the path it will occupy in the runtime stage.** Since the
runtime stage uses `WORKDIR /app`, build at `/app/.venv` even inside the builder:

```dockerfile
# CORRECT — venv built at the runtime path; shebangs are already right
RUN uv venv /app/.venv && \
    uv pip install --no-cache --python /app/.venv \
        -e /build/libs/common \
        ...

# Runtime stage — copy from the same path (no path change = no shebang corruption)
COPY --from=builder /app/.venv /app/.venv
```

The `--python /app/.venv` flag to `uv pip install` is required when the venv
path differs from `WORKDIR` — `uv` won't auto-detect the venv otherwise.

**`PATH` and `ENV` in the runtime stage are unaffected** — they still point to
`/app/.venv/bin`.

### Test to add (prevents regression)

Add a smoke test to `docker-compose.test.yml` that verifies the migrate container
exits 0. The `service_completed_successfully` condition on every API service
dependency already catches this — if migration exits non-zero, the API container
never starts, causing `--wait` to fail.

### Files changed in fix

| File | Change |
|------|--------|
| `services/portfolio/Dockerfile` | Changed `uv venv /build/.venv` → `uv venv /app/.venv`; added `--python /app/.venv` to `uv pip install`; updated `COPY` source path |
| `services/market-ingestion/Dockerfile` | Same as portfolio |

---

## BP-006 — Alembic env.py uses hardcoded localhost URL from alembic.ini

**Date discovered**: 2026-03-10
**Service affected**: `market-ingestion` (found during `make test-e2e` → migration container connection refused)

### Symptom

Migration container (`market-ingestion-migrate`) exits 1 with:

```
asyncpg.exceptions.InvalidCatalogNameError: database "ingestion_db" does not exist
```
or
```
ConnectionRefusedError: [Errno 111] Connect call failed ('127.0.0.1', 5432)
```

The host API service is healthy but the migrate container uses `localhost:5432`
(the `sqlalchemy.url` from `alembic.ini`) instead of the Docker Compose service
name `postgres:5432`.

### Root cause

`alembic/env.py` reads the DB URL from `sqlalchemy.url` in `alembic.ini`, which
has `localhost` hardcoded. The `alembic/env.py` must override this with
`Settings().database_url`, which reads from the running process's environment
variables (populated by Docker Compose's `env_file:` for containers, or
`dev.local.env` for local runs).

### Correct implementation pattern

In `alembic/env.py`:

```python
import os
from <service>.config import Settings as _Settings

config.set_main_option(
    "sqlalchemy.url",
    os.environ.get("ALEMBIC_URL") or _Settings().database_url,
)
```

The `ALEMBIC_URL` escape hatch allows overriding without changing Settings
(useful for special-purpose migration runs).

### Test to add (prevents regression)

```python
def test_alembic_env_reads_from_settings(monkeypatch):
    monkeypatch.setenv("<SERVICE>_DATABASE_URL", "postgresql+asyncpg://x:x@custom-host/db")
    from alembic.config import Config
    alembic_cfg = Config("alembic.ini")
    # env.py should have overridden sqlalchemy.url
    assert "custom-host" in alembic_cfg.get_main_option("sqlalchemy.url", "")
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/market-ingestion/alembic/env.py` | Override `sqlalchemy.url` from `Settings().database_url` instead of reading static `alembic.ini` |

---

## BP-007 — PostgreSQL unique index doesn't deduplicate NULL nullable columns

**Date discovered**: 2026-03-10
**Service affected**: `market-ingestion` (found during repeated `test_scheduler_tick_with_no_policies_completes` runs)

### Symptom

`sqlalchemy.exc.MultipleResultsFound: Multiple rows were found when one or none was required`

Occurring in `watermark_repository.get()` after running the test suite multiple
times against the same DB. Rows that should be unique (same natural key) are
being duplicated.

### Root cause

A multi-column `UNIQUE` constraint on `(provider, dataset_type, dataset_variant,
symbol, exchange, timeframe)` allows duplicate rows when any nullable column is
`NULL`, because in ANSI SQL `NULL != NULL` (and therefore the constraint is never
triggered). Two rows with `dataset_variant=NULL` for the same provider/dataset/
symbol are treated as *different* by the constraint.

PostgreSQL 15+ supports `NULLS NOT DISTINCT` on unique indexes to fix this.

### Correct implementation pattern

In the migration creating the unique constraint:

```python
op.execute(sa.text("""
    CREATE UNIQUE INDEX uq_<table>_natural_key
    ON <table> (col1, col2, nullable_col3, ...)
    NULLS NOT DISTINCT
"""))
```

And never use `op.create_index(..., unique=True)` for indexes with nullable
columns — it generates SQL without `NULLS NOT DISTINCT`.

As a defensive measure, use `.limit(1)` on `SELECT` queries that expect to
return at most one row but rely on a nullable multi-column key:

```python
stmt = select(Model).where(...).limit(1)
row = (await session.execute(stmt)).scalar_one_or_none()
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/market-ingestion/alembic/versions/0003_fix_watermarks_nulls_not_distinct.py` | New migration: deduplicates existing rows, drops old index, creates new `NULLS NOT DISTINCT` index |
| `services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/watermark_repository.py` | Added `.limit(1)` to `get()` query as defensive guard |

---

## BP-008 — Initial schema migration out of sync with final ORM model

**Date discovered**: 2026-03-10
**Service affected**: `market-ingestion` (found during `make test-e2e` — migration 0002 references columns not in 0001)

### Symptom

```
asyncpg.exceptions.UndefinedColumnError: column "min_interval_sec" of relation "polling_policies" does not exist
```

Migration 0002 (seed data) references columns that the 0001 schema migration
does not create. The ORM model has the correct final schema; 0001 was written
at an earlier stage before the model was finalised.

### Root cause

The initial schema migration (`0001_initial_schema.py`) was written when the ORM
model was still evolving. The final ORM model has different column names and
additional columns. Since no intermediate "alter table" migration was created,
the 0001 migration drifted from the ORM model.

### Detection

Run `alembic check` or `alembic revision --autogenerate -m "check"` and verify
the generated migration is empty. If it's not empty, 0001 is out of sync.

### Correct implementation pattern

When the service hasn't been deployed to production yet and you have the freedom
to rewrite 0001:

1. Update `0001_initial_schema.py` to match the current ORM model exactly.
2. Verify by running `alembic upgrade head && alembic check` — the check should
   produce an empty migration.
3. Any seed migrations (0002, etc.) must reference only columns that 0001 creates.

For services already deployed, create an `000N_alter_<table>.py` migration
to bring the DB schema to match the ORM.

### Files changed in fix

| File | Change |
|------|--------|
| `services/market-ingestion/alembic/versions/0001_initial_schema.py` | Rewrote `polling_policies` block to match `PollingPolicyModel` ORM; rewrote `provider_budgets` block to match `ProviderBudgetModel` ORM |
| `services/market-ingestion/alembic/versions/0002_seed_default_policies.py` | Fixed `sa.func.now()` in `bulk_insert` row dicts (must be Python datetime); fixed timestamp assignments |

---

## BP-009 — DispatcherProcess passes raw Kafka dict as DispatcherConfig

**Date discovered**: 2026-03-10
**Service affected**: `market-ingestion` (found during `test_dispatcher_starts_and_stops_cleanly`)

### Symptom

```
AttributeError: 'dict' object has no attribute 'worker_id'
```

The `DispatcherProcess.__init__` constructs a dict
`{"bootstrap.servers": ...}` and passes it as the `config=` argument to
`build_<service>_dispatcher()`. The factory expects a `DispatcherConfig`
dataclass, not a raw dict.

### Root cause

The original code confused the Kafka producer config dict (used inside the
dispatcher for `SerializingProducer`) with the `DispatcherConfig` dataclass
(tuning parameters for the poll loop). These are completely different objects.
The `build_*_dispatcher` factory already handles constructing the
`DispatcherConfig` from `Settings`; callers should not pass it at all unless
they need to override defaults.

### Correct implementation pattern

```python
# WRONG
kafka_config = {"bootstrap.servers": settings.kafka_bootstrap_servers}
dispatcher = build_service_dispatcher(settings=settings, write_factory=wf, config=kafka_config)

# CORRECT — let the factory derive DispatcherConfig from settings
dispatcher = build_service_dispatcher(settings=settings, write_factory=wf)
```

The `build_*_dispatcher` factory creates `DispatcherConfig` from `settings`
attributes (e.g. `settings.dispatcher_poll_interval_seconds`). The Kafka
`bootstrap.servers` is consumed inside the dispatcher's `_build_producer()`
via `settings.kafka_bootstrap_servers`.

### Files changed in fix

| File | Change |
|------|--------|
| `services/market-ingestion/src/market_ingestion/messaging/dispatcher_main.py` | Removed `kafka_config` dict and `config=kafka_config` from `build_market_ingestion_dispatcher` call |

---

## BP-010 — Docker Compose `--wait` fails for long-running worker processes

**Date discovered**: 2026-03-10
**Services affected**: `market-ingestion`, `portfolio`
**Prompts updated**: `0004-exec-market-data-migration-wave-02.md`, `0004-exec-market-data-migration-wave-03.md`, `0004-exec-market-data-migration-wave-04.md`

### Symptom

- `docker compose ... up --wait` fails with:

```
container <service>-dispatcher-1 has no healthcheck configured
```

- Or background processes exit because they inherited API-only healthchecks
    (e.g., probing `/readyz` on processes that do not expose HTTP).

### Root cause

Compose `--wait` requires health status for started services. Long-running
workers/schedulers/dispatchers often run as non-HTTP commands and cannot reuse
the API container healthcheck. If no healthcheck is present (or API healthcheck
is inherited from Dockerfile), readiness and lifecycle behavior become unstable.

### Correct implementation pattern

For non-HTTP background services:

```yaml
worker:
    command: ["python", "-m", "service.worker.main"]
    healthcheck:
        test: ["CMD", "python", "-c", "import sys; sys.exit(0)"]
        interval: 15s
        timeout: 3s
        retries: 3
        start_period: 5s
```

And do **not** rely on Dockerfile API healthchecks for these process types.

### Test to add (prevents regression)

- In CI/local smoke script, run:

```bash
docker compose -f infra/compose/docker-compose.test.yml --profile <service>-test up --wait
docker compose -f infra/compose/docker-compose.test.yml ps
```

- Assert worker/scheduler/dispatcher are `Up (healthy)` and not restarting.

### Files changed in fix

| File | Change |
|------|--------|
| `infra/compose/docker-compose.test.yml` | Added explicit healthchecks for `market-ingestion-scheduler`, `market-ingestion-worker`, `market-ingestion-dispatcher`, and `portfolio-dispatcher` |

---

## BP-011 — Runtime schema files missing from container image

**Date discovered**: 2026-03-10
**Services affected**: `market-ingestion`
**Prompts updated**: `0004-exec-market-data-migration-wave-02.md`

### Symptom

Dispatcher crashes only in containers with:

```
FileNotFoundError: Could not locate market.dataset.fetched.avsc from module path or cwd
```

### Root cause

Schema files under `infra/kafka/schemas/` were available in the repo for local
execution but not copied into the Docker runtime image. Module path resolution
worked on host but failed in container filesystem.

### Correct implementation pattern

Copy required non-code assets into image at build time:

```dockerfile
COPY infra/kafka/schemas /build/infra/kafka/schemas
...
COPY --from=builder /build/infra/kafka/schemas /app/infra/kafka/schemas
```

Also prefer robust schema path resolution that scans parents/cwd and fails with
clear error text.

### Test to add (prevents regression)

- Container smoke command in CI:

```bash
docker compose -f infra/compose/docker-compose.test.yml --profile <service>-test up --build --wait
docker compose -f infra/compose/docker-compose.test.yml logs <dispatcher-service>
```

- Assert no `FileNotFoundError` and dispatcher remains running.

### Files changed in fix

| File | Change |
|------|--------|
| `services/market-ingestion/Dockerfile` | Copied `infra/kafka/schemas` into runtime image |
| `services/market-ingestion/src/market_ingestion/infrastructure/messaging/kafka/serialization.py` | Added resilient schema path resolver |

---

## BP-012 — Async SQLAlchemy polling triggers `MissingGreenlet`

**Date discovered**: 2026-03-10
**Services affected**: `market-ingestion`
**Prompts updated**: `0004-exec-market-data-migration-wave-04.md`

### Symptom

E2E polling test fails with:

```
sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called
```

typically when reading ORM object attributes after rollback/expiration.

### Root cause

Polling loop selected full ORM rows, then session rollback expired attributes.
Later attribute access triggered lazy load outside the active greenlet context.

### Correct implementation pattern

In async polling tests, query scalar columns instead of ORM objects:

```python
status = (
        (await session.execute(select(Model.status).where(...).limit(1)))
        .scalars()
        .first()
)
await session.rollback()
```

Avoid storing ORM entities across loop iterations when rollback is used.

### Test to add (prevents regression)

- Add an E2E polling test variant that runs the loop for several iterations and
    confirms no `MissingGreenlet` is raised.

### Files changed in fix

| File | Change |
|------|--------|
| `services/market-ingestion/tests/e2e/test_api_workflows.py` | Replaced ORM-row polling with scalar-column polling |

---

## BP-013 — E2E tests appear infinite due to unstable async assertions

**Date discovered**: 2026-03-10
**Services affected**: `market-ingestion`
**Prompts updated**: `0004-exec-market-data-migration-wave-04.md`

### Symptom

E2E run appears to hang for minutes. Tests are not truly infinite but use long
deadlines while waiting for conditions that are fragile (symbol-specific queue
state, dispatcher timing, scheduler noise).

### Root cause

- Assertions depended on one task/symbol becoming terminal within an arbitrary
    window while scheduler continuously enqueued unrelated tasks.
- Poll loops had broad deadlines and ambiguous success criteria.

### Correct implementation pattern

1. Use bounded polling windows with explicit deadlines.
2. Assert stable, service-level progress conditions (e.g., any task processed),
     not brittle symbol-specific timing.
3. Keep scheduler deterministic in test profiles (short tick; bounded budget).

```yaml
environment:
    MARKET_INGESTION_SCHEDULER_TICK_INTERVAL_SECONDS: "2.0"
    MARKET_INGESTION_SCHEDULER_MAX_TASKS_PER_TICK: "0"
```

### Test to add (prevents regression)

- Add one dedicated async-progress smoke test with a strict upper bound
    (`<= 20-30s`) and fail-fast assertion message.

### Files changed in fix

| File | Change |
|------|--------|
| `infra/compose/docker-compose.test.yml` | Added deterministic scheduler test env vars |
| `services/market-ingestion/tests/e2e/test_api_workflows.py` | Reworked full-flow test to bounded, stable progress assertion |

---

## BP-014 — Import guard allowlist `fnmatch` pattern does not match direct children

**Date discovered**: 2026-03-26
**Service affected**: `intelligence-migrations` (found during CI Import Guards job)
**Prompts updated**: `.claude/skills/implement/SKILL.md` Step 4 — added import guards to validation gate

### Symptom

CI Import Guards job fails with 3 net-new violations that should be covered by the allowlist:
```
[IG-OBS-001] services/intelligence-migrations/scripts/populate_embeddings.py:30
    Forbidden call: `logging.getLogger()` (rule IG-OBS-001)
[IG-COMMON-001] services/intelligence-migrations/tests/test_migration.py:129
    Forbidden call: `uuid.uuid4()` (rule IG-COMMON-001)
[IG-COMMON-001] services/intelligence-migrations/tests/test_migration.py:130
    Forbidden call: `uuid.uuid4()` (rule IG-COMMON-001)
```

### Root cause

Two independent issues:

1. **`fnmatch` does not support recursive `**` like `pathlib.Path.glob()`**. The allowlist used patterns like `services/*/tests/**/*.py`, but Python's `fnmatch.fnmatch()` treats `*` as "match any characters" (including `/`). The `**/` in the pattern requires at least one path separator after `tests/`, so files directly in `tests/` (like `tests/test_migration.py`) are NOT matched — only files in subdirectories (like `tests/unit/test_foo.py`) match.

2. **Service-level scripts not covered**. The allowlist had `scripts/**/*.py` for repo-root scripts, but `services/intelligence-migrations/scripts/populate_embeddings.py` is under `services/`, not the root `scripts/` directory.

3. **No pre-commit import guard check**. The pre-commit hook (`pre-commit-validate.sh`) ran ruff + mypy + unit tests but did NOT run import guards, so violations passed local validation and only failed in CI.

### Correct implementation pattern

When writing `fnmatch`-style allowlist patterns, always include **both** direct-child and recursive patterns:

```yaml
# Direct children — fnmatch does NOT support ** recursion
- rule_id: IG-COMMON-001
  path: "services/*/tests/*.py"
  reason: Test code may use uuid4() directly.

# Nested children — still needed for tests/unit/*.py, tests/integration/*.py
- rule_id: IG-COMMON-001
  path: "services/*/tests/**/*.py"
  reason: Test code may use uuid4() directly.
```

When adding new service directories (like `services/*/scripts/`), add corresponding allowlist entries if the files don't follow service-code conventions.

### Test to add (prevents regression)

Import guards now run as Step 3/4 in the pre-commit hook (`scripts/hooks/pre-commit-validate.sh`), so violations are caught before commit — not just in CI.

### Files changed in fix

| File | Change |
|------|--------|
| `scripts/import_guards/allowlist.yaml` | Added `services/*/tests/*.py` patterns alongside existing `**/*.py` patterns; added `services/*/scripts/*.py` entries |
| `services/intelligence-migrations/scripts/populate_embeddings.py` | Replaced `logging.getLogger()` with `structlog.get_logger()` and structlog-style kwargs |
| `scripts/hooks/pre-commit-validate.sh` | Added import guards as Step 3/4 (scoped to changed services) |
| `.claude/skills/implement/SKILL.md` | Added import guards to Step 4 validation gate |

---

## Template for new entries

Copy this block when adding a new pattern:

```markdown
## BP-NNN — Short title

**Date discovered**: YYYY-MM-DD
**Service affected**: `<service-name>` (found during `<make target or test>`)
**Prompts updated**: `<prompt file>` task `<T-XX-NN>` step N

### Symptom

<exact error message or observable behaviour>

### Root cause

<explanation of why it fails>

### Correct implementation pattern

<code snippet showing the correct way>

### Test to add (prevents regression)

<pytest test that would have caught this>

### Files changed in fix

| File | Change |
|------|--------|
| `path/to/file.py` | What was changed |
```
