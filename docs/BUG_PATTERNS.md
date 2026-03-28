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
| [BP-015](#bp-015) | Python `hash()` for cross-process coordination | Advisory lock IDs differ between processes — concurrent fetches not locked | Any service using `pg_try_advisory_lock` with Python `hash()` |
| [BP-016](#bp-016) | Advisory lock spanning external I/O | DB connection held during multi-second HTTP fetch — pool exhaustion | Any service holding advisory lock during adapter.fetch() |
| [BP-017](#bp-017) | Outbox payload fields mismatch Avro schema | `SerializationError` or silent field drops at dispatcher time | Any service writing outbox events that feed an Avro-serialized Kafka topic |
| [BP-018](#bp-018) | Client constructor mismatch in wiring code | `TypeError: __init__() got an unexpected keyword argument` at runtime | Any service building adapter clients in a factory or lifespan function |
| [BP-019](#bp-019) | Migration DDL vs ORM column mismatch | `UndefinedColumnError` or `ProgrammingError` at runtime — migration DDL defines different columns than ORM model | Any service where migration DDL is hand-written separately from ORM |
| [BP-020](#bp-020) | DLQ `move_to_dead_letter` only updates status | Dead-lettered events cannot be inspected or requeued — DLQ table has no row, only outbox status changed | Any service with outbox + DLQ pattern |
| [BP-021](#bp-021) | SQLAlchemy ORM `metadata` column name collision | `Cannot override class variable (previously declared on base class "DeclarativeBase") with instance variable` — mypy error, and incorrect table binding | Any ORM model with a column named `metadata` |
| [BP-022](#bp-022) | NMS IoU boundary ambiguity | Overlapping spans with IoU exactly = threshold are NOT suppressed — must be **strictly greater** | Any NER/span deduplication implementation using IoU-based NMS |
| [BP-023](#bp-023) | pre-commit ruff-format stash conflict loop | Commit fails in loop: ruff-format reformats a staged file, stash restore conflicts, hook rolls back, commit never succeeds | Any service where the service venv's ruff version differs from the pre-commit hook's ruff version |
| [BP-024](#bp-024) | DLQ requeue corrupts aggregate_id | DLQ `requeue()` creates outbox event with outbox PK as `aggregate_id` instead of the original doc UUID — silent data corruption, downstream consumers get wrong entity references | Any service with outbox + DLQ pattern |
| [BP-025](#bp-025) | Blocking DNS in async context | `socket.getaddrinfo()` called on event loop — freezes entire async service under slow/failing DNS | Any service doing SSRF validation or DNS lookups in async handlers |
| [BP-026](#bp-026) | SSRF missing IPv4-mapped IPv6 | `::ffff:127.0.0.1` bypasses manual IP blocklist — private IPv4 addresses reachable via IPv4-mapped IPv6 notation | Any service with URL/SSRF validation |
| [BP-027](#bp-027) | DNS rebinding TOCTOU | DNS resolves to public IP at validation time, rebinds to private IP at connection time — validation passes but SSRF succeeds | Any service fetching user-supplied URLs |
| [BP-028](#bp-028) | AsyncMock used for sync method — unawaited coroutine warning | `RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited` — test passes but has contract mismatch | Any test using `mock_uow = AsyncMock()` where the UoW has sync methods (e.g., `collect_event`) |
| [BP-029](#bp-029) | Content-hash dedup event_type mismatch | Dedup check always misses — `exists_by_content_hash(sha256, _DATASET_TYPE)` never finds rows stored with `event_type=_TOPIC` | Any Kafka consumer using content-hash dedup in market-data |
| [BP-030](#bp-030) | Token-bucket domain entity missing `last_refill_at` | Tokens consumed but never replenished — bucket drains under sustained load until restart | Any service with a token-bucket rate limiter that persists `last_refill_at` in DB |
| [BP-031](#bp-031) | Backfill flag flipped before budget/cap check | Backfill enters incremental mode even if zero tasks were actually enqueued (all blocked by budget/cap) | Any scheduler with a one-shot backfill mode that modifies policy state during candidate task construction |
| [BP-032](#bp-032) | Repository `upsert()` missing `.returning()` | Caller cannot determine the stable DB identity of the upserted row — local entity ID is transient, differs from DB on conflict | Any repository with `ON CONFLICT DO UPDATE` that must return the persisted entity |
| [BP-033](#bp-033) | Concurrent flag updates use read-modify-write | One consumer's `has_quotes=True` update overwrites another's `has_ohlcv=True` — flags silently cleared | Any repo that updates a flags struct with a plain `UPDATE SET ... WHERE id=` under concurrent consumers |
| [BP-034](#bp-034) | Content-hash dedup early return skips `mark_processed` | Same Kafka message replayed passes dedup check again — event_id never recorded when skipping unchanged data | Kafka consumers that do content-hash dedup before event-id dedup |
| [BP-035](#bp-035) | `is_duplicate()` check-then-insert race under concurrent consumers | Two consumers both pass `is_duplicate()` before either writes to the dedup table — duplicate processing despite `ON CONFLICT DO NOTHING` | Any consumer with check-then-insert idempotency pattern |
| [BP-036](#bp-036) | Token bucket `try_consume()` non-atomic with DB | Two workers both pass `tokens >= n` check before either persists the decrement — tokens over-consumed under concurrent load | Any in-memory token bucket that persists state to DB |
| [BP-037](#bp-037) | `UnitOfWork.__aexit__` exception masking | Rollback failure during `__aexit__` suppresses the original exception — root cause invisible in logs | All services using async UnitOfWork context managers |
| [BP-038](#bp-038) | `assert` used for production error handling | `python -O` strips assertions — critical guards silently disabled, `AssertionError` raises without context | Any service using `assert x is not None` in non-test code |
| [BP-039](#bp-039) | `EVENT_TOPIC_MAP.get(event_type, event_type)` silently routes to wrong topic | Missing entry in topic map uses event_type string as topic name — creates spurious topics, messages lost | Any service resolving Kafka topic from an in-memory dict at outbox read time |
| [BP-040](#bp-040) | Idempotency `INSERT` missing `ON CONFLICT DO NOTHING` | Duplicate event replay raises `IntegrityError` instead of being silently ignored — consumer crashes | Any service with a dedicated idempotency/processed-events table using plain INSERT |
| [BP-041](#bp-041) | ruff `TCH003`→`TC003` noqa code rename breaks pre-commit | Pre-commit ruff v0.4.0 reports `TCH003`; newer local ruff auto-converts `# noqa: TCH003` → `# noqa: TC003`; hook then re-flags the violation → infinite loop | All SQLAlchemy ORM models with `Mapped[datetime]` imports |
| [BP-042](#bp-042) | `FailureInfo[None]` has no `value`/`key`/`headers` fields | `AttributeError: 'FailureInfo' object has no attribute 'value'` — only `event_id`, `topic`, `partition`, `offset`, `attempt`, `last_error`, `record` exist | Any `dead_letter` / `process_message_from_failure` implementation on `BaseKafkaConsumer[None]` |
| [BP-043](#bp-043) | Pydantic V2 `Field(strip_whitespace=True)` is deprecated | `PydanticDeprecatedSince20` warning — `strip_whitespace` is not a valid V2 `Field` kwarg; use `StringConstraints(strip_whitespace=True)` via `Annotated` instead | API request schemas using `Field(...)` |

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

## BP-015 — Python `hash()` for cross-process coordination

**Date discovered**: 2026-03-26
**Service affected**: `content-ingestion` (found during QA review)

### Symptom

Advisory lock IDs differ between Python processes. Multiple replicas acquire the "same" lock simultaneously because `hash("s4:fetch:eodhd")` returns different values per process (randomized by PYTHONHASHSEED).

### Root cause

Python's `hash()` is randomized per process (PEP 456). Using it for PostgreSQL advisory lock IDs produces different lock IDs in different pods/containers.

### Correct implementation pattern

```python
import hashlib
def advisory_lock_id(key: str) -> int:
    digest = hashlib.sha256(key.encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)
```

Use `hashlib.sha256` for deterministic cross-process IDs. The shared `messaging.pg.advisory_lock` module does this correctly.

### Test to add (prevents regression)

```python
def test_advisory_lock_id_deterministic():
    assert advisory_lock_id("key") == advisory_lock_id("key")
```

---

## BP-016 — Advisory lock spanning external I/O

**Date discovered**: 2026-03-26
**Service affected**: `content-ingestion` (found during QA review)

### Symptom

DB connection pool exhaustion under load. Advisory lock held for 10–30 seconds while adapter fetches from external API.

### Root cause

The advisory lock was acquired before the HTTP fetch, keeping a DB connection checked out during the entire external I/O. With 3 sources × 30s fetch × multiple replicas, the pool depletes.

### Correct implementation pattern

```python
# Fetch OUTSIDE the lock
results = await adapter.fetch(source)

# Write INSIDE the lock (short, bounded duration)
async with pg_advisory_lock(session, key) as acquired:
    if acquired:
        await use_case.write(results)
```

### Test to add (prevents regression)

Verify that the session factory is called separately for the read (watermark) + fetch phase and the write phase.

---

## BP-017 — Outbox payload fields mismatch Avro schema

**Date discovered**: 2026-03-26
**Service affected**: `content-ingestion` (found during QA review)

### Symptom

`SerializationError` at dispatcher time, or fields silently dropped. The outbox payload used field names like `url`, `minio_key` while the Avro schema expected `source_url`, `minio_bronze_key`.

### Root cause

Outbox payload was built with domain field names instead of Avro schema field names. No compile-time or test-time validation of the payload structure.

### Correct implementation pattern

Build payloads using a dedicated helper that maps to Avro field names:

```python
def build_raw_article_payload(*, doc_id, source_type, source_url, minio_bronze_key, ...):
    return {"event_id": ..., "source_url": source_url, "minio_bronze_key": minio_bronze_key, ...}
```

Add a test that asserts payload keys match the Avro schema fields.

---

## BP-018 — Client constructor mismatch in wiring code

**Date discovered**: 2026-03-26
**Service affected**: `content-ingestion` (found during QA review)

### Symptom

`TypeError: __init__() got an unexpected keyword argument 'rate_limiter'` when constructing adapter clients. Or: `http_client` not passed because generic `adapter_cls(**kwargs)` was used.

### Root cause

Each client has a different constructor signature (EODHD/Finnhub need `api_key`, SEC EDGAR needs `user_agent`, NewsAPI needs `valkey`). Generic wiring code doesn't handle these differences.

### Correct implementation pattern

Use explicit per-source-type wiring with type-checked constructors:

```python
if source_type == "eodhd":
    client = EODHDClient(http_client=http_client, api_key=settings.eodhd_api_key)
elif source_type == "newsapi":
    client = NewsAPIClient(http_client=http_client, api_key=settings.newsapi_key, valkey=valkey)
```

### Test to add (prevents regression)

HTTP client tests using `httpx.MockTransport` that verify each client can be constructed and called.

---

## BP-019 — Migration DDL vs ORM column mismatch

**Date discovered**: 2026-03-28
**Services affected**: `content-store`, `content-ingestion` (found during multi-agent QA review)
**Prompts updated**: `PLAN-0001-B-R2` tasks T-R2-1-01, T-R2-1-02, T-R2-1-05

### Symptom

`UndefinedColumnError` or `ProgrammingError` at runtime when Alembic migration creates a table with different columns than the SQLAlchemy ORM model expects. Integration tests that use `Base.metadata.create_all()` bypass Alembic and won't catch this.

Example: `outbox_events` migration DDL had `event_id`, `partition_key`, `payload_avro BYTEA` columns, but the ORM model had `id`, `aggregate_type`, `payload JSONB`.

### Root cause

Migration DDL was written manually at an early stage of development, then the ORM model evolved. Since no automated check existed, the two diverged silently. Integration tests use `Base.metadata.create_all()` which generates DDL from the ORM — not from Alembic — so they always pass.

### Correct implementation pattern

1. Always generate initial DDL from ORM column inspection, or copy the exact column definitions from the ORM model.
2. Add DDL-vs-ORM alignment tests that parse migration SQL and compare column names against `Model.__table__.columns`:

```python
def test_ddl_matches_orm():
    migration_text = Path("alembic/versions/0001_*.py").read_text()
    orm_columns = {c.name for c in MyModel.__table__.columns}
    # Parse CREATE TABLE from migration and extract column names
    for col in orm_columns:
        assert col in migration_text, f"ORM column '{col}' missing from migration DDL"
```

3. Never use `gen_random_uuid()` defaults on UUID PKs — all IDs must be app-generated UUIDv7.

### Test to add (prevents regression)

DDL-vs-ORM alignment tests (see `services/content-store/tests/unit/infrastructure/test_ddl_alignment.py` and `services/content-ingestion/tests/unit/infrastructure/test_ddl_alignment.py`).

### Files changed in fix

| File | Change |
|------|--------|
| `services/content-store/alembic/versions/0001_create_content_store_schema.py` | Rewrote `outbox_events` and `dead_letter_queue` DDL to match ORM |
| `services/content-ingestion/alembic/versions/0001_initial_s4_schema.py` | Added `payload_json JSONB` to `dead_letter_queue` DDL |
| `services/content-store/tests/unit/infrastructure/test_ddl_alignment.py` | New — DDL alignment tests for S5 |
| `services/content-ingestion/tests/unit/infrastructure/test_ddl_alignment.py` | New — DDL alignment tests for S4 |

---

## BP-020 — DLQ `move_to_dead_letter` only updates status without copying payload

**Date discovered**: 2026-03-28
**Services affected**: `content-store` (found during multi-agent QA review)
**Prompts updated**: `PLAN-0001-B-R2` tasks T-R2-1-03, T-R2-1-04, T-R2-1-06

### Symptom

Dead-lettered events are invisible to the `/admin/dlq` API and cannot be requeued. The `move_to_dead_letter` method updates the outbox `status` column to `dead_letter` but does not INSERT a row into the `dead_letter_queue` table. Additionally, `requeue()` creates a new outbox event with `payload={}` (empty) instead of the original payload.

### Root cause

1. `move_to_dead_letter` was implemented as a simple status update (one SQL UPDATE) instead of the S4 pattern which also INSERTs a DLQ row with the original payload.
2. `DeadLetterQueueModel` was missing the `payload_json` column, so even if a DLQ row existed, there was no place to store the payload for requeue.
3. `requeue()` hardcoded `payload={}` instead of reading `entry.payload_json`.

### Correct implementation pattern

```python
async def move_to_dead_letter(self, record_id: UUID, error_detail: str = "") -> None:
    # 1. Fetch the outbox record
    record = await self._get_outbox_record(record_id)
    if not record:
        return
    # 2. INSERT a DLQ row with the original payload
    dlq = DeadLetterQueueModel(
        dlq_id=new_uuid7(),
        original_event_id=record.id,
        topic=record.topic,
        payload_json=record.payload,  # preserve original payload
        error_detail=error_detail,
    )
    self._session.add(dlq)
    # 3. Update outbox status
    record.status = OutboxStatus.DEAD_LETTER
```

For `requeue()`:
```python
async def requeue(self, dlq_id: UUID) -> None:
    entry = await self._get(dlq_id)
    # Use original payload, not empty dict
    await outbox_repo.append(..., payload=entry.payload_json or {})
```

### Test to add (prevents regression)

See `services/content-store/tests/unit/infrastructure/test_dlq_repo.py` — tests verify DLQ row creation and non-empty payload on requeue.

### Files changed in fix

| File | Change |
|------|--------|
| `services/content-store/src/content_store/infrastructure/db/repositories/outbox.py` | Fixed `move_to_dead_letter` to INSERT DLQ row |
| `services/content-store/src/content_store/infrastructure/db/repositories/dlq.py` | Fixed `requeue` to use `entry.payload_json` |
| `services/content-store/src/content_store/infrastructure/db/models.py` | Added `payload_json` column to `DeadLetterQueueModel` |
| `services/content-store/tests/unit/infrastructure/test_dlq_repo.py` | New — DLQ copy + requeue tests |

---

## BP-021 — SQLAlchemy ORM `metadata` column name collision

**Date discovered**: 2026-03-27
**Service affected**: `nlp-pipeline` (found during mypy check of nlp_db ORM models)
**Prompts updated**: N/A

### Symptom

```
error: Cannot override class variable (previously declared on base class "DeclarativeBase") with instance variable  [misc]
error: Incompatible types in assignment (expression has type "Mapped[dict[str, Any] | None]", base class "DeclarativeBase" defined the type as "MetaData")  [assignment]
```

### Root cause

`DeclarativeBase` (SQLAlchemy 2.x) defines a class-level `metadata: MetaData` attribute. Any ORM model that names a column `metadata` will shadow it, causing a mypy type conflict and potentially incorrect ORM behavior.

### Correct implementation pattern

Rename the Python attribute, preserving the DB column name via an explicit column name argument:

```python
# WRONG
metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

# CORRECT — rename attribute, keep DB column as "metadata"
resolution_metadata: Mapped[dict[str, Any] | None] = mapped_column(
    "metadata", JSONB, nullable=True
)
```

Update all repositories that set this field to use the new attribute name.

### Test to add (prevents regression)

```python
def test_mention_resolution_model_has_no_metadata_attr_collision():
    from nlp_pipeline.infrastructure.nlp_db.models import MentionResolutionModel
    # Python attr is resolution_metadata, not metadata
    assert hasattr(MentionResolutionModel, "resolution_metadata")
    assert not hasattr(MentionResolutionModel.__table__.columns, "resolution_metadata")
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py` | Renamed `metadata` → `resolution_metadata` with explicit column name `"metadata"` |
| `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/mention_resolution.py` | Updated `metadata=` to `resolution_metadata=` |

---

## BP-022 — NMS IoU boundary: strictly-greater vs greater-or-equal

**Date discovered**: 2026-03-27
**Service affected**: `nlp-pipeline` Block 4 NER (test failures during Wave C-2)
**Prompts updated**: N/A

### Symptom

NMS unit test `test_keeps_higher_confidence_when_overlapping` passes when IoU < threshold but fails when IoU = threshold (0.5 exactly). Spans that should be suppressed are kept, or vice versa.

### Root cause

The PRD says "IoU > 0.5" — strictly greater than. If the implementation uses `>=`, spans with IoU = 0.5 are incorrectly suppressed. Test fixtures using exact boundary values (e.g., spans (0,10) and (0,5) → IoU = 0.5 exactly) will fail because 0.5 is NOT > 0.5.

### Correct implementation pattern

```python
NMS_IOU_THRESHOLD = 0.5

def _nms(mentions):
    ...
    if _iou(a.char_start, a.char_end, b.char_start, b.char_end) > NMS_IOU_THRESHOLD:
        # suppress b (strictly greater than threshold)
```

Test fixtures must use spans with IoU **strictly greater than** 0.5, e.g., (0,10) and (1,9) → IoU = 8/10 = 0.8.

### Test to add (prevents regression)

```python
def test_nms_boundary_iou_exactly_half_not_suppressed():
    # spans (0,10) and (0,5): intersection=5, union=10, IoU=0.5 — NOT suppressed
    m1 = EntityMention(..., char_start=0, char_end=10, confidence=0.9, ...)
    m2 = EntityMention(..., char_start=0, char_end=5, confidence=0.7, ...)
    result = _nms([m1, m2])
    assert len(result) == 2  # neither suppressed at boundary
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/nlp-pipeline/tests/unit/application/blocks/test_ner.py` | Updated test fixtures to use spans with IoU > 0.5 (not exactly 0.5) |

---

## BP-023 — pre-commit ruff-format stash conflict loop

**Date discovered**: 2026-03-27
**Service affected**: `nlp-pipeline` (pre-commit hook during Wave C-2 commit)
**Prompts updated**: N/A

### Symptom

`git commit` enters an infinite failure loop:
```
ruff-format...Failed — 1 file reformatted
Stashed changes conflicted with hook auto-fixes... Rolling back fixes
```

The same file is reformatted every attempt; the commit never succeeds.

### Root cause

Two conditions must both be true to trigger this:
1. A staged file has a **different version in the working tree** (`AM` or `MM` git status)
2. The pre-commit hook's ruff version formats the file differently than the local venv's ruff

The hook stashes the working tree, formats the staged content, then tries to restore the stash. The stash's working tree version conflicts with the formatted index version, causing rollback.

### Correct implementation pattern

Before committing, ensure ALL staged Python files have `A ` or `M ` status (no working tree delta):

```bash
# Find partially-staged Python files
git diff --name-only | grep "\.py$"

# For each file listed, check if it's also staged
git status --short <file>  # AM or MM = problem

# Fix: restore working tree from index (use hook's formatted version)
git checkout -- <file>

# OR: format file with system ruff (pre-commit hook version) and re-stage
uvx ruff format <file>
git add <file>
```

**Always use `uvx ruff format` (system/pre-commit ruff), not the service venv's ruff**, since the venv may be pinned to an older version.

### Test to add (prevents regression)

N/A — this is a workflow issue, not a code bug. Add to commit checklist: verify no `AM`/`MM` Python files before committing.

### Files changed in fix

| File | Change |
|------|--------|
| `services/nlp-pipeline/src/nlp_pipeline/application/blocks/routing.py` | Reformatted assert statement to match pre-commit hook's ruff version |

---

## BP-024 — DLQ requeue corrupts aggregate_id

**Date discovered**: 2026-03-27
**Service affected**: `content-store` (found during PLAN-0001-B-R4 QA review)
**Prompts updated**: `docs/plans/0001-b-r4-qa-review-fixes-plan.md` W1

### Symptom

Downstream consumers receive `content.article.stored.v1` events where `aggregate_id` is the outbox primary key UUID instead of the canonical document UUID. Lookups by document ID silently fail — no error, wrong entity referenced.

### Root cause

`DLQRepository.requeue()` created the new outbox event using `entry.original_event_id` (the outbox PK) as `aggregate_id` instead of the actual document UUID stored in `entry.aggregate_id`. Similarly, `event_type` was hardcoded instead of read from the DLQ row.

### Correct implementation pattern

```python
# WRONG — uses outbox PK as aggregate_id
self._session.add(OutboxEventModel(
    aggregate_id=entry.original_event_id,  # ← outbox PK, not doc UUID!
    event_type="content.article.stored.v1",  # ← hardcoded
    ...
))

# CORRECT — use stored metadata with fallback for pre-existing rows
self._session.add(OutboxEventModel(
    aggregate_id=entry.aggregate_id or entry.original_event_id,
    aggregate_type=entry.aggregate_type or "document",
    event_type=entry.event_type or entry.payload_json.get("event_type", "content.article.stored.v1"),
    ...
))
```

Also: `move_to_dead_letter` must store `aggregate_type`, `aggregate_id`, and `event_type` from the source outbox record into the DLQ row when creating it.

### Test to add (prevents regression)

```python
async def test_requeue_uses_stored_aggregate_id():
    entry = make_dlq_entry()
    entry.aggregate_id = UUID("doc-uuid-here")
    entry.original_event_id = UUID("outbox-pk-here")
    ...
    outbox_model = session.add.call_args.args[0]
    assert outbox_model.aggregate_id == entry.aggregate_id  # doc UUID, not outbox PK
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/content-store/src/content_store/infrastructure/db/repositories/dlq.py` | Use `entry.aggregate_id` with fallback |
| `services/content-store/src/content_store/infrastructure/db/repositories/outbox.py` | Store metadata fields in DLQ row |
| `services/content-store/alembic/versions/0001_create_content_store_schema.py` | Add `aggregate_type`, `aggregate_id`, `event_type` columns to `dead_letter_queue` |

---

## BP-025 — Blocking DNS resolution in async context

**Date discovered**: 2026-03-27
**Service affected**: `content-ingestion` (found during PLAN-0001-B-R4 QA review)

### Symptom

Under slow or failing DNS, the entire FastAPI service freezes. Requests time out across all endpoints because a single blocked `socket.getaddrinfo()` call holds the event loop.

### Root cause

`socket.getaddrinfo()` is a blocking synchronous call. When called directly inside a Pydantic `field_validator` (which runs synchronously during request validation in an async handler), it blocks the asyncio event loop for the duration of the DNS lookup.

### Correct implementation pattern

```python
# WRONG — blocks the event loop
@field_validator("url")
def validate_url(cls, v: str) -> str:
    addrs = socket.getaddrinfo(hostname, None)  # blocks!
    ...

# CORRECT — move DNS to async handler with timeout
async def check_url_ssrf_async(url: str) -> None:
    try:
        addr_infos = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, hostname, None),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        raise ValueError(f"DNS timeout for {hostname}")
```

The Pydantic validator should only check scheme (http/https) and reject literal private IPs. DNS resolution moves to the async route handler.

### Test to add (prevents regression)

```python
async def test_async_dns_timeout():
    with patch("socket.getaddrinfo", side_effect=lambda *a, **kw: time.sleep(10)):
        with pytest.raises(ValueError, match="Could not resolve"):
            await check_url_ssrf_async("http://slow.example.com/article")
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/content-ingestion/src/content_ingestion/api/schemas.py` | Removed DNS from validator; added `check_url_ssrf_async` |
| `services/content-ingestion/src/content_ingestion/api/routes/internal.py` | Call `check_url_ssrf_async` in handler |

---

## BP-026 — SSRF missing IPv4-mapped IPv6 bypass

**Date discovered**: 2026-03-27
**Service affected**: `content-ingestion` (found during PLAN-0001-B-R4 QA review)

### Symptom

A URL like `http://[::ffff:127.0.0.1]/internal` passes SSRF validation even though it routes to localhost. Manual IP range checks for `127.0.0.0/8` don't cover the IPv4-mapped IPv6 form.

### Root cause

Manual `_PRIVATE_NETWORKS` lists check `127.0.0.0/8`, `10.0.0.0/8`, etc. These only apply to `IPv4Address` objects. An `IPv6Address` like `::ffff:127.0.0.1` is technically in the `::ffff:0:0/96` range and has `ipv4_mapped = IPv4Address('127.0.0.1')`, but won't match any IPv4 range check unless you first extract the mapped address.

### Correct implementation pattern

```python
# WRONG — misses IPv4-mapped IPv6
def _is_private_ip(addr):
    return any(addr in network for network in _PRIVATE_NETWORKS)

# CORRECT — use Python builtins + handle IPv4-mapped IPv6
def _is_private_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped  # unwrap ::ffff:x.x.x.x → IPv4
    return addr.is_private or addr.is_reserved or addr.is_loopback or addr.is_multicast or addr.is_link_local
```

Python's built-in `is_private`, `is_reserved`, `is_loopback` properties cover all RFC-defined ranges including CGNAT (100.64.0.0/10), multicast, and future additions.

### Test to add (prevents regression)

```python
@pytest.mark.parametrize("url", [
    "http://[::ffff:127.0.0.1]/",
    "http://[::ffff:10.0.0.1]/",
    "http://100.64.0.1/",  # CGNAT
    "http://224.0.0.1/",   # multicast
])
def test_rejects_private_ip_variants(url):
    with pytest.raises(ValueError):
        IngestRequest(url=url, ...)
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/content-ingestion/src/content_ingestion/api/schemas.py` | Replaced manual network lists with `is_private` builtins + IPv4-mapped unwrap |

---

## BP-027 — DNS rebinding TOCTOU in SSRF validation

**Date discovered**: 2026-03-27
**Service affected**: `content-ingestion` (found during PLAN-0001-B-R4 QA review)

### Symptom

URL passes SSRF validation (DNS resolves to public IP), but by the time the HTTP client connects, DNS has been rebounded to a private IP. The request reaches an internal service despite validation passing.

### Root cause

DNS validation and HTTP connection are two separate operations with a time gap. An attacker controls a DNS server that returns a public IP on the first query (validation) and a private IP on the second query (connection). This is a classic TOCTOU (Time Of Check, Time Of Use) race.

### Correct implementation pattern

```python
class SSRFSafeTransport(httpx.AsyncBaseTransport):
    """Validates resolved IPs at connection time, not just at validation time."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        hostname = request.url.host
        if hostname:
            addr_infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None)
            for _family, _type, _proto, _canonname, sockaddr in addr_infos:
                addr = ipaddress.ip_address(sockaddr[0])
                if _is_private_ip(addr):
                    raise httpx.ConnectError(f"SSRF blocked: {hostname} → {addr}")
        return await self._inner.handle_async_request(request)
```

Wire this transport when constructing `httpx.AsyncClient` in the app lifespan.

### Test to add (prevents regression)

```python
async def test_transport_blocks_dns_rebinding():
    transport = SSRFSafeTransport()
    request = httpx.Request("GET", "http://rebind.example.com/")
    with patch("socket.getaddrinfo", return_value=[(..., ..., ..., "", ("127.0.0.1", 0))]):
        with pytest.raises(httpx.ConnectError, match="SSRF blocked"):
            await transport.handle_async_request(request)
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/content-ingestion/src/content_ingestion/infrastructure/http/ssrf_transport.py` | New — `SSRFSafeTransport` implementation |
| `services/content-ingestion/src/content_ingestion/app.py` | Wire `SSRFSafeTransport` into `httpx.AsyncClient` |

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

---

## BP-028 — AsyncMock used for sync method generates unawaited coroutine warnings

**Date discovered**: 2026-03-27
**Service affected**: `market-data` (ohlcv, quotes, fundamentals consumers)

### Symptom

Tests pass but emit `RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited` for calls like `uow.collect_event(...)`. The call is sync in production but the test's `AsyncMock()` wraps every attribute as an async mock.

### Root cause

`mock_uow = AsyncMock()` makes ALL attributes `AsyncMock` instances by default. When production code calls a **sync** method (`collect_event`) without `await`, the `AsyncMock` runs but the resulting coroutine is never consumed — generating the warning.

### Fix

Explicitly override sync methods after creating the `AsyncMock`:
```python
mock_uow = AsyncMock()
mock_uow.collect_event = MagicMock()  # sync — must not be AsyncMock
```

### Prevention

After `mock_uow = AsyncMock()`, check the real UoW for sync methods and override them with `MagicMock()`.

---

## BP-029 — Content-hash dedup event_type key mismatch — dedup never fires

**Date discovered**: 2026-03-27
**Service affected**: `market-data` (ohlcv, quotes, fundamentals consumers)

### Symptom

Content-hash dedup never fires — identical canonical objects are re-downloaded and re-materialized on every tick.

### Root cause

`mark_processed()` stored `event_type=_TOPIC` (e.g., `"market.dataset.fetched"`) while `exists_by_content_hash()` queried with `event_type=_DATASET_TYPE` (e.g., `"ohlcv"`). The lookup always missed.

### Fix

Use the same value (`_DATASET_TYPE`) in both `mark_processed()` and `exists_by_content_hash()`.

---

## BP-030 — Token-bucket `last_refill_at` not wired — tokens never replenished

**Date discovered**: 2026-03-27
**Service affected**: `market-ingestion` (ProviderBudget / ScheduleDueTasksUseCase)

### Symptom

Provider budget drains to 0 tokens under sustained load and never recovers until service restart.

### Root cause

`ProviderBudget` entity had no `last_refill_at` field. `_to_domain()` ignored the DB `last_refill_at` column. `refill()` was never called in `_apply_budgets()`.

### Fix

1. Add `last_refill_at: datetime` to `ProviderBudget` (default `utc_now()`).
2. `refill()` sets `self.last_refill_at`.
3. `_to_domain()` maps `row.last_refill_at`.
4. `save()` persists `last_refill_at`.
5. `_apply_budgets()` calls `budget.refill(elapsed)` before consuming.

---

## BP-031 — Backfill flag flipped before budget/cap filtering

**Date discovered**: 2026-03-27
**Service affected**: `market-ingestion` (ScheduleDueTasksUseCase)

### Symptom

Backfill enters incremental mode even when budget was exhausted and zero backfill tasks were actually enqueued.

### Root cause

`_build_tasks_for_policy()` set `policy.backfill_enabled = False` during Phase 2 (candidate construction), before Phase 3 applied the budget/cap filter.

### Fix

Collect backfill policies in a list during Phase 2. After Phase 3 produces `final_tasks`, only flip `backfill_enabled=False` for policies with at least one task in `final_tasks`.

---

## BP-032 — `upsert()` missing `.returning()` — transient entity ID

**Date discovered**: 2026-03-27
**Service affected**: `portfolio` (InstrumentRepository)

### Symptom

After upsert, caller's in-memory entity ID is a transient UUID that may not match the DB row (on conflict, the DB keeps the original row ID).

### Root cause

`pg_insert(...).on_conflict_do_update(...)` executed without `.returning(InstrumentModel)`. Repo returned `None`.

### Fix

Add `.returning(InstrumentModel)`, fetch `scalar_one()`, and return the mapped entity.

---

## BP-033 — Concurrent flag updates — read-modify-write race clears flags

**Date discovered**: 2026-03-27
**Service affected**: `market-data` (InstrumentRepository.update_flags)

### Symptom

Under concurrent consumers, a consumer setting `has_quotes=True` overwrites another consumer's concurrent `has_ohlcv=True` update.

### Root cause

`UPDATE instruments SET has_ohlcv=:v, has_quotes=:v, has_fundamentals=:v WHERE id=:id` overwrites all columns from a pre-read snapshot.

### Fix

Use atomic OR-merge so only `True` values propagate — flags can never be cleared by concurrent writers:
```python
has_ohlcv=case((flags.has_ohlcv, True), else_=InstrumentModel.has_ohlcv),
```

---

## BP-034 — Content-hash dedup early return skips `mark_processed`

**Date discovered**: 2026-03-27
**Service affected**: `market-data` (ohlcv_consumer, quotes_consumer, fundamentals_consumer)

### Symptom

The same Kafka message is re-processed on replay even though the data was unchanged. The content-hash dedup path returns early without recording the event_id.

### Root cause

When `exists_by_content_hash(sha256, event_type)` returns `True`, the consumer returns early. But the `event_id` is never written to the `ingestion_events` table. On next replay the `is_duplicate()` check returns `False` (event_id not found) and the consumer re-processes.

### Fix

Call `await self.mark_processed(event_id)` before the early return so the event_id is always recorded:
```python
if sha256 and await uow.ingestion_events.exists_by_content_hash(sha256, _DATASET_TYPE):
    await self.mark_processed(event_id)   # ← ADD THIS
    return
```

---

## BP-035 — `is_duplicate()` check-then-insert race under concurrent consumers

**Date discovered**: 2026-03-27
**Service affected**: `market-data` (all three consumers)

### Symptom

Under rebalance or concurrent consumer scenarios, the same message is processed twice even though `ON CONFLICT DO NOTHING` exists on the dedup table.

### Root cause

The `is_duplicate()` SELECT and the `create()` INSERT happen in separate transactions. Two consumers can both pass the `is_duplicate()` check before either has committed the insert. The `ON CONFLICT DO NOTHING` prevents a duplicate row but does not prevent duplicate processing.

### Fix

Use a database-level lock or move the dedup INSERT to be the first operation inside the processing transaction. If the INSERT is rejected by the unique constraint, treat the event as a duplicate and skip processing.

---

## BP-036 — Token bucket `try_consume()` non-atomic with DB persist

**Date discovered**: 2026-03-27
**Service affected**: `market-ingestion` (ProviderBudget)

### Symptom

Under multi-worker load, the budget allows more requests than the configured limit — tokens are over-consumed.

### Root cause

`try_consume()` checks and decrements `self.tokens` in-memory before the DB write. Two workers loading the same budget row both see `tokens >= n`, both decrement in-memory, and both write back — one decrement is lost.

### Fix

Load the budget row with `SELECT ... FOR UPDATE` within the consuming transaction so only one worker can check-and-decrement at a time.

---

## BP-037 — `UnitOfWork.__aexit__` rollback failure masks original exception

**Date discovered**: 2026-03-27
**Service affected**: All services with async UnitOfWork

### Symptom

After a use-case failure, the log shows a rollback error instead of the original business exception — root cause is invisible.

### Root cause

`__aexit__` calls `await self.rollback()` inside a bare `try` block. If rollback itself raises (DB connection lost), the new exception replaces the original via Python's implicit exception chaining.

### Fix

Use explicit exception chaining and structured logging:
```python
async def __aexit__(self, exc_type, exc_val, exc_tb):
    try:
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()
    except Exception as cleanup_err:
        logger.error("uow_cleanup_failed", error=str(cleanup_err), original=str(exc_val))
    finally:
        await self._session.close()
```

---

## BP-038 — `assert` used for production error handling

**Date discovered**: 2026-03-27
**Service affected**: `market-data` (ohlcv_consumer, quotes_consumer, fundamentals_consumer)

### Symptom

With `python -O`, the assertion is stripped and the guard becomes a no-op. Under normal execution, `AssertionError` is raised with no context message.

### Root cause

```python
assert self._current_uow is not None  # Stripped by python -O
```

### Fix

Replace with explicit guard:
```python
if self._current_uow is None:
    raise RuntimeError("mark_processed called outside processing context")
```

---

## BP-039 — `EVENT_TOPIC_MAP.get(event_type, event_type)` silently routes to wrong topic

**Date discovered**: 2026-03-27
**Service affected**: `portfolio` (OutboxRepository)

### Symptom

Outbox events for a newly-added event type are published to a Kafka topic literally named after the event type string (e.g., `portfolio.holding.changed`), not the canonical topic name.

### Root cause

`claim_batch()` resolves topic as `EVENT_TOPIC_MAP.get(row.event_type, row.event_type)`. If the event type is missing from the map, the fallback is the event_type string itself — a spurious topic is created silently.

### Fix

Fail explicitly on missing entries:
```python
topic = EVENT_TOPIC_MAP.get(row.event_type)
if topic is None:
    raise ValueError(f"Unknown event_type for outbox routing: {row.event_type!r}")
```

---

## BP-040 — Idempotency `INSERT` missing `ON CONFLICT DO NOTHING`

**Date discovered**: 2026-03-27
**Service affected**: `portfolio` (IdempotencyRepository), `market-data` (IngestionEventRepository)

### Symptom

On Kafka message replay, the consumer crashes with `IntegrityError: duplicate key value violates unique constraint` instead of silently skipping the duplicate.

### Root cause

The idempotency record INSERT uses a plain `INSERT INTO` without `ON CONFLICT DO NOTHING`. The table has a unique constraint on `event_id`, so a replay raises instead of being ignored.

### Fix

```python
stmt = (
    insert(IdempotencyModel)
    .values(event_id=event_id)
    .on_conflict_do_nothing(constraint="pk_idempotency")
)
```

---

## BP-041 — ruff TCH003→TC003 noqa rename breaks pre-commit hook

**Affects**: All SQLAlchemy ORM models using `Mapped[datetime]` (or other stdlib types only used in annotations)

### Symptom

Pre-commit hook fails with:

```
ruff.....................................................................Failed
services/.../models.py:9:22: TCH003 Move standard library import `datetime.datetime` into a type-checking block
Found 2 errors (1 fixed, 1 remaining).
```

After the hook auto-fixes the import (moves it to `TYPE_CHECKING`), SQLAlchemy raises at runtime:

```
sqlalchemy.exc.ArgumentError: Could not resolve all types within mapped annotation: "Mapped[datetime]"
```

### Root cause

- The pre-commit hook pins ruff at `v0.4.0`, which uses rule code `TCH003`.
- Newer local ruff (≥v0.6.0) renames it to `TC003` and auto-converts `# noqa: TCH003` → `# noqa: TC003` in staged files.
- The hook's ruff v0.4.0 doesn't recognize `# noqa: TC003` as suppressing `TCH003` → auto-fixes the import → breaks SQLAlchemy → circular failure.

### Fix

Add the models path glob to `ruff.toml`'s `[lint.per-file-ignores]` to suppress the rule globally (no noqa comment needed):

```toml
# SQLAlchemy calls get_type_hints() at runtime — datetime must be importable
"services/*/src/*/infrastructure/db/models/*.py" = ["TCH003"]
"services/*/src/*/infrastructure/*/models.py" = ["TCH003"]   # non-standard subdirs (e.g. nlp_db/)
```

Do NOT use `# noqa: TCH003` or `# noqa: TC003` — they are unstable across ruff versions. The `per-file-ignores` approach is version-agnostic.

---

## BP-042 — FailureInfo[None] missing value/key/headers fields

**Affects**: `BaseKafkaConsumer[None]` implementations — `dead_letter()` and `process_message_from_failure()`

### Symptom

```
AttributeError: 'FailureInfo' object has no attribute 'value'
mypy: "FailureInfo[None]" has no attribute "value"
```

### Root cause

`FailureInfo[TFailure]` stores the original message in typed form. When `TFailure = None`, the consumer never parses the raw Kafka message into a domain object, so `FailureInfo[None]` has **no** `value`, `key`, or `headers` fields — only:

- `event_id: str`
- `topic: str`
- `partition: int`
- `offset: int`
- `attempt: int`
- `last_error: str`
- `record: Any` (the raw Kafka ConsumerRecord)

### Fix

In `dead_letter()`: use `failure.event_id` for identification, not `failure.value`.
In `process_message_from_failure()`: the original payload is not recoverable — log a warning and return without reprocessing.

```python
def dead_letter(self, failure: FailureInfo[None]) -> None:
    # failure.value does NOT exist — use event_id for the DLQ entry
    asyncio.create_task(self._write_dlq(event_id=failure.event_id, ...))

async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
    # Original payload is not recoverable for TFailure=None consumers
    logger.warning("cannot_reprocess_failure", event_id=failure.event_id)
```

## BP-043 — Pydantic V2 `Field(strip_whitespace=True)` deprecated

**Affects**: API request schemas using `Field(strip_whitespace=True)` — `TenantCreateRequest`, `PortfolioCreateRequest`, etc.

### Symptom

```
PydanticDeprecatedSince20: Using extra keyword arguments on `Field` is deprecated and will be removed.
Use `json_schema_extra` instead. (Extra keys: 'strip_whitespace')
```

### Root cause

Pydantic V2 removed non-standard kwargs from `Field()`. `strip_whitespace` was a Pydantic V1 feature. In V2, string constraints (including `strip_whitespace`, `min_length`, `max_length`) must be applied via `StringConstraints` in an `Annotated` type.

### Fix

```python
from typing import Annotated
from pydantic import StringConstraints

TrimmedStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]

class TenantCreateRequest(BaseModel):
    name: TrimmedStr
```

Or drop `strip_whitespace` and rely on `min_length`/`max_length` in `Field(...)` only (the length constraints are the primary security fix):

```python
name: str = Field(min_length=1, max_length=255)
```
