# Bug Patterns — Database & ORM

> **Category**: database-orm
> **Description**: SQLAlchemy ORM, asyncpg, Alembic migrations, PostgreSQL semantics, pgvector, advisory locks, session management, transaction handling
> **Count**: 42 patterns
> **Back to index**: [BUG_PATTERNS.md](../BUG_PATTERNS.md)

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

---

## BP-044 — f-string dynamic SQL for nullable filters triggers ruff S608

**Category**: SQL / Linting
**Services affected**: Any async service with optional filter params in repository queries
**First seen**: knowledge-graph S7 Wave D-4 (relation repository list_for_entity / list_filtered)

### Symptom

Repository method builds a dynamic WHERE clause using f-strings or string concatenation to handle optional filter parameters:

```python
# WRONG — triggers S608 (f-string in SQL) and is hard to audit
mode_filter = "AND r.semantic_mode = :semantic_mode" if semantic_mode else ""
query = text(f"SELECT ... FROM relations r WHERE ... {mode_filter}")
```

This approach:
1. Fires `S608: Possible SQL injection via string-based query construction` (even though it's not actually injectable here, ruff can't tell)
2. Requires `# noqa: S608` on every call site
3. Is structurally harder to audit for actual injection risks

### Root Cause

Using f-strings or `%` formatting in `text()` queries makes the SQL dynamic, even when the dynamic part is a safe literal (a clause name, not user data).

### Fix

Use PostgreSQL's `IS NULL OR column = :param` pattern to keep the SQL fully static while supporting optional filters:

```python
# CORRECT — fully static SQL, no f-strings, no S608
query = text("""
    SELECT ...
    FROM relations r
    WHERE (:semantic_mode IS NULL OR r.semantic_mode = :semantic_mode)
      AND (:min_confidence IS NULL OR r.confidence >= :min_confidence)
    ...
""")
result = await session.execute(query, {
    "semantic_mode": semantic_mode,          # None → clause passes for all rows
    "min_confidence": min_confidence,        # None → clause passes for all rows
})
```

### Why this works

PostgreSQL evaluates `:param IS NULL` first. When the parameter is `None` (bound as SQL NULL), the entire `IS NULL OR ...` disjunction short-circuits to `TRUE`, effectively removing the filter. When non-null, the actual column comparison is evaluated.

### Benefits

- Zero dynamic SQL → no S608, no `# noqa` suppressions
- Single static query → easier to read, audit, and plan/cache
- Works for all nullable parameters: strings, UUIDs, floats, datetimes

### Caution

- For very large tables with many optional filters, this can prevent index use on some filters even when non-null. Profile with `EXPLAIN ANALYZE` if performance is critical.
- Not applicable when the number of filters is dynamic (e.g., variable-length IN clauses) — those still need query building.

---

---

## BP-046 — Cache invalidation before `uow.commit()` creates stale-read-into-cache race

**Category**: Cache consistency / M-005 violation
**Services affected**: market-data `QuotesConsumer` (fixed 2026-03-28), any consumer that invalidates Valkey inside `process_message()`
**First seen**: PLAN-0001-E QA-004

### Symptom

After a cache invalidation a client reads the data, gets the DB's current (old) value, and caches it. Then the transaction commits the new value. The cache now holds the OLD value until TTL expiry. Stale data is served from cache.

### Root cause

```python
# WRONG — cache invalidation before commit
async def process_message(self, key, value, headers):
    await uow.quotes.upsert(quote)           # DB write (not yet committed)
    await self._quote_cache.invalidate(id)   # Cache invalidated NOW
    # ... base class calls uow.commit() later
```

After invalidation but before commit:
1. Client reads `GET /quotes/{id}` → cache miss → hits DB → gets **old value** (write not committed)
2. Client's response is cached in Valkey
3. `uow.commit()` persists the new value
4. Valkey now serves the **stale cached old value** until TTL

### Fix

Use `uow.schedule_post_commit(coro)` — a post-commit hook that drains after `write_session.commit()`:

```python
# CORRECT — cache invalidation after commit (M-005)
async def process_message(self, key, value, headers):
    await uow.quotes.upsert(quote)
    # Schedule cache invalidation to run AFTER the transaction commits
    if self._quote_cache is not None:
        uow.schedule_post_commit(self._quote_cache.invalidate(instrument.id))
```

The `schedule_post_commit` implementation in `SqlAlchemyUnitOfWork.commit()`:

```python
async def commit(self) -> None:
    await self._write_session.commit()           # DB write durable
    # ... outbox notifier ...
    hooks = self._post_commit_hooks[:]
    self._post_commit_hooks.clear()
    for hook in hooks:
        await hook                               # Cache invalidated after durability
```

### Test pattern

Test must verify the hook is **scheduled** (not yet awaited), then manually drain:

```python
captured_hooks = []
mock_uow.schedule_post_commit = MagicMock(side_effect=captured_hooks.append)
await consumer.process_message(...)
mock_cache.invalidate.assert_not_awaited()   # Not yet
await captured_hooks[0]                       # Simulate commit drain
mock_cache.invalidate.assert_awaited_once_with(instrument_id)
```

---

---

## BP-049 — `get_or_create` reads back via read session after INSERT on write session (read-your-own-write failure)

**Category**: DB session management / Read/write splitting
**Services affected**: market-ingestion `BudgetRepository`, `WatermarkRepository` (fixed 2026-03-28)
**First seen**: PLAN-0001-E QA-007, QA-008

### Symptom

`get_or_create()` inserts a row on the write session, then calls `self.get()` which uses the read session `self._r` — a potentially separate replica connection. The replica may not see the uncommitted or just-committed write (replication lag or different connection), so `get()` returns `None`. The caller then falls back to a transient domain object with a new auto-generated ID, breaking idempotency: subsequent `UPDATE WHERE id = new_id` matches 0 rows silently.

### Root cause

```python
# WRONG — reads back from the wrong session after INSERT
async def get_or_create(self, key) -> DomainObject:
    stmt = insert(Model).values(...).on_conflict_do_nothing()
    await self._w.execute(stmt)
    row = await self.get(key)  # self.get() uses self._r (read session) ← WRONG
    if row:
        return row
    return DomainObject(id=new_uuid7(), ...)  # fresh ID = broken idempotency
```

### Fix

Read back from the write session after INSERT to guarantee read-your-own-write:

```python
# CORRECT — read back from write session
async def get_or_create(self, key) -> DomainObject:
    stmt = insert(Model).values(...).on_conflict_do_nothing()
    await self._w.execute(stmt)
    select_stmt = select(Model).where(Model.key == key)
    row = (await self._w.execute(select_stmt)).scalar_one_or_none()
    if row:
        return _to_domain(row)
    return DomainObject(id=new_uuid7(), ...)  # only reached on genuine insert failure
```

---

---

## BP-057 — Database session held across external I/O

**Severity**: HIGH — pool exhaustion under load (R24)
**Service**: Any service with background processes (workers, schedulers, dispatchers)
**Related**: [BP-016](#bp-016) (advisory lock spanning external I/O)

### Symptom

- `TimeoutError` on `pool.acquire()` — all connections busy despite low query volume
- Connection pool exhaustion under moderate load
- Long-running "idle in transaction" connections visible in `pg_stat_activity`
- Intermittent `sqlalchemy.exc.TimeoutError: QueuePool limit of N overflow M reached`

### Cause

A database session (and its underlying connection) is opened before an external I/O call
(HTTP request, MinIO upload, Kafka publish) and held idle throughout. The connection sits
in the pool's "checked out" state doing nothing while the I/O completes, preventing other
coroutines from using it.

```python
# WRONG — connection held idle during HTTP call
async with session_factory() as session:
    data = await repo.get(id)              # uses connection
    result = await http_client.post(...)   # connection held idle for seconds!
    await repo.save(result)                # uses connection again
    await session.commit()
```

This is especially harmful in workers with semaphore-bounded concurrency — 4 concurrent
tasks each holding a connection during I/O can exhaust a `pool_size=5` pool.

### Fix

Split into read → release → I/O → acquire → write phases:

```python
# CORRECT — release connection before I/O
async with read_factory() as ro:
    data = await repo.get(id)              # read phase

result = await http_client.post(...)       # I/O phase (no session held)

async with write_factory() as rw:
    await repo.save(result)                # write phase
    await rw.commit()
```

### Detection

Grep for session context managers that span external I/O calls:

```bash
# Look for session_factory/uow usage that spans http_client, storage, or producer calls
grep -n "session_factory\|uow\|unit_of_work" services/*/src/**/*.py | \
  grep -v "test" | grep -v "__pycache__"
```

Then manually inspect each match for external I/O calls within the same context block.

### Prevention

- R24 enforces this rule project-wide (see RULES.md)
- STANDARDS.md §16 documents the correct session lifecycle per process type
- Code review checklist: "Does any session context span an external I/O call?"

---

---

## BP-069 — asyncpg AmbiguousParameterError when all optional filter params are None

**Category**: Database / asyncpg
**Services affected**: knowledge-graph (S7), any service using raw `text()` SQL with optional nullable parameters
**First seen**: knowledge-graph S7 `list_filtered` relation repository

### Symptom

`asyncpg.exceptions.AmbiguousParameterError: could not determine data type of parameter $1` at runtime when all optional filter parameters are None. The query uses the pattern `(:param IS NULL OR col = :param)` with asyncpg named params.

### Root Cause

PostgreSQL's prepared statement protocol requires each parameter to have a known type before execution. When all values are `None`, the parameter only appears in an `IS NULL` check, which doesn't constrain the type. PostgreSQL can't infer `uuid`, `text`, `float` etc. from `$1 IS NULL` alone.

### Fix

Build WHERE clauses conditionally — skip clauses entirely when the filter value is `None`:

```python
where_clauses = ["1=1"]
params: dict[str, object] = {"limit": limit, "offset": offset}
if subject_id is not None:
    where_clauses.append("r.subject_id = :subject_id")
    params["subject_id"] = str(subject_id)
where_sql = " AND ".join(where_clauses)
await session.execute(text(f"SELECT * FROM r WHERE {where_sql} LIMIT :limit"), params)  # noqa: S608
```

This avoids the type-inference problem entirely. Add `# noqa: S608` to suppress the false-positive SQL injection warning (these are static strings, not user input).

### Prevention

Avoid the `(:param IS NULL OR col = :param)` pattern with asyncpg. Always use conditional WHERE construction when parameters may be None.

---

## BP-070 — SQLAlchemy `func.cast()` and `func.Integer` do not exist

**Category**: SQLAlchemy / ORM
**Services affected**: nlp-pipeline (S6), any service using SQLAlchemy aggregate functions
**First seen**: nlp-pipeline S6 `signals_query.py` get_entity_detail

### Symptom

`AttributeError: Neither 'Function' object nor 'Comparator' object has an attribute '_isnull'` at runtime when a repository method uses `func.cast(expr, func.Integer)`.

### Root Cause

`func.cast` is not a standard SQLAlchemy function — it generates a SQL function call `CAST()` but the second argument `func.Integer` doesn't work because `func.Integer` creates a SQL function named "Integer" rather than a type. SQLAlchemy's `func.sum()` then tries to infer the type of the expression and fails.

### Fix

Use the top-level `cast()` and `Integer` from `sqlalchemy`:

```python
# WRONG
from sqlalchemy import func
func.sum(func.cast(expr, func.Integer))

# CORRECT
from sqlalchemy import Integer, cast, func
func.sum(cast(expr, Integer))
```

### Prevention

Never use `func.cast()` or `func.Integer`. Import `cast`, `Integer` (and other types) directly from `sqlalchemy`.

---

## BP-071 — FK constraint blocks manual/webhook submissions when source_id is NOT NULL

**Category**: Schema / Use Case
**Services affected**: content-ingestion (S4)
**First seen**: content-ingestion submit_content use case e2e testing

### Symptom

`sqlalchemy.dialects.postgresql.asyncpg.IntegrityError: ForeignKeyViolationError: insert or update on table "article_fetch_log" violates foreign key constraint` when the internal submit endpoint is called. The `SubmitContentUseCase` passed `doc_id` (the article UUID) as `source_id` into `article_fetch_log`, but `source_id` is a FK to `sources.id`.

### Root Cause

The `article_fetch_log.source_id` column was designed for scheduled polling sources. Manual/webhook submissions via the internal endpoint have no associated source, but the schema required a non-null source FK.

### Fix

1. Migrate `article_fetch_log.source_id` from `NOT NULL` to nullable.
2. Pass `source_id=None` in `SubmitContentUseCase.execute()`.
3. Update `FetchLogPort.create()` signature to `source_id: UUID | None`.

### Prevention

When designing tables that track both scheduled and manual events, make FK columns nullable from the start if the FK may not apply to all producers.

---

## BP-076 — asyncpg rejects PostgreSQL `::type` cast syntax in `text()` params

**Date discovered**: 2026-03-31
**Service affected**: `alert`, `nlp-pipeline`, `knowledge-graph`, `content-store` (E2E test seeds)

### Symptom

Raw SQL executed via SQLAlchemy `text()` with bound parameters fails at runtime or in tests with:

```
asyncpg.exceptions._base.UnknownPostgresError
```

or silently produces wrong results when parameters contain PostgreSQL cast notation like `:payload::jsonb` or `:id::uuid`.

### Root Cause

SQLAlchemy's `text()` constructs intentionally skip the `:name::type` pattern during parameter binding because `::` is the PostgreSQL cast operator. SQLAlchemy avoids mangling it. As a result, asyncpg receives the literal `:name::type` string instead of a positional `$N` placeholder, causing a syntax error or undefined-parameter error at the PostgreSQL driver level.

```python
# WRONG — asyncpg receives ":payload::jsonb" literally
await session.execute(
    text("INSERT INTO dlq (payload) VALUES (:payload::jsonb)"),
    {"payload": json.dumps(data)},
)

# CORRECT — use SQL standard CAST syntax
await session.execute(
    text("INSERT INTO dlq (payload) VALUES (CAST(:payload AS JSONB))"),
    {"payload": json.dumps(data)},
)
```

The same applies to `::uuid`, `::text`, `::integer`, and all other PostgreSQL cast suffixes.

### Fix

Replace all `:name::type` patterns in SQLAlchemy `text()` statements with `CAST(:name AS TYPE)`.

### Prevention

- Grep new SQL literals for `::` followed by a type name: `grep -rn '::\w\+' services/*/src/`
- Add a pre-commit check or test that rejects `text("...::\w")` patterns in source files
- Document this constraint in service `.claude-context.md` files for services with heavy raw SQL

---

---

## BP-077 — `ON CONFLICT DO NOTHING` missing `index_where=` for partial unique index

**Date discovered**: 2026-03-31
**Service affected**: `content-ingestion` (`IngestionTaskRepository.create_if_not_exists`)

### Symptom

A repository `upsert` or `insert_ignore` using SQLAlchemy's `on_conflict_do_nothing` fails at runtime with:

```
sqlalchemy.exc.ProgrammingError: (asyncpg.exceptions.InvalidColumnReferenceError)
there is no unique or exclusion constraint matching the ON CONFLICT specification
```

The failure only manifests when `window_start` (or another nullable column) is NOT NULL, because the partial index `WHERE window_start IS NOT NULL` only covers those rows.

### Root Cause

PostgreSQL `ON CONFLICT (col1, col2)` must reference a unique constraint or index **exactly**, including any `WHERE` clause for partial indexes. If the unique index is defined as:

```sql
CREATE UNIQUE INDEX ix_cit_source_window
    ON ingestion_tasks (source_id, window_start)
    WHERE window_start IS NOT NULL;
```

Then the SQLAlchemy dialect must match the predicate:

```python
# WRONG — no index_where, PostgreSQL cannot match the partial index
stmt.on_conflict_do_nothing(index_elements=["source_id", "window_start"])

# CORRECT
from sqlalchemy import text
stmt.on_conflict_do_nothing(
    index_elements=["source_id", "window_start"],
    index_where=text("window_start IS NOT NULL"),
)
```

### Fix

Add `index_where=text("<predicate>")` matching the partial index `WHERE` clause verbatim.

### Prevention

- Whenever a table has partial unique indexes, the corresponding repository `ON CONFLICT` clause must include `index_where=`
- Add `index_where` to the migration review checklist when `CREATE UNIQUE INDEX ... WHERE` appears

---

---

## BP-097 — Read Engine Connection Leak in Dual-Session Factory

**Pattern**: `_build_factories()` creates a separate `read_engine` when `database_url_read` differs from `database_url`, but only returns `write_engine` in the tuple. The `read_engine` is bound to `read_factory` via SQLAlchemy's internal reference, but is never explicitly disposed on shutdown.

**Symptom**: Graceful shutdown (e.g. Kubernetes SIGTERM) leaves read-replica TCP connections open until OS timeout. No data loss, but violates graceful shutdown contract and causes connection exhaustion under repeated rolling restarts.

**Cause**: Pattern `return write_engine, write_factory, read_factory` — only `write_engine` is tracked, so only `write_engine.dispose()` is called at shutdown.

**Fix**: Return both engines (or a named tuple) from `_build_factories()`:
```python
# WRONG — read_engine leaked on shutdown
return write_engine, write_factory, read_factory

# CORRECT — both engines tracked
return write_engine, read_engine_or_none, write_factory, read_factory
# OR store read_engine in app.state.read_engine for disposal in lifespan shutdown
app.state.read_engine = read_engine if read_url != write_url else None
```

**Only manifests when**: `database_url_read` is explicitly set to a different URL than `database_url`. All services default to empty (fallback), so this is a latent bug.

**Applies to**: All services implementing R23 dual-session (S1, S4, S5, S6, S7, S10, S8).

---

---

## BP-099 — DDL Alignment Test Misses ALTER TABLE ADD COLUMN Migrations

**Category**: DB / Testing
**Affected areas**: Any service whose `test_ddl_alignment.py` uses `_extract_ddl_columns()` with only `CREATE TABLE` parsing

**Symptom**: DDL alignment test reports `ORM columns missing from DDL: {'column_name'}` after adding a column via an `ALTER TABLE` migration — even though the migration is correct and the ORM is updated.

**Root cause**: The `_extract_ddl_columns` helper only parses `CREATE TABLE` blocks. When a column is added via a later `ALTER TABLE {table} ADD COLUMN` migration, it never appears in the CREATE TABLE DDL and the test falsely flags it as missing.

**Fix**: Extend `_extract_ddl_columns` to also scan for `ALTER TABLE {table_name} ADD COLUMN [IF NOT EXISTS] <col_name>` patterns using `re.finditer`:
```python
alter_pattern = rf"ALTER\s+TABLE\s+{table_name}\s+ADD\s+COLUMN(?:\s+IF\s+NOT\s+EXISTS)?\s+(\w+)"
for m in re.finditer(alter_pattern, migration_text, re.IGNORECASE):
    columns.add(m.group(1))
```

**First seen**: PLAN-0016 Wave A-2 — adding `context_valkey_key` + `summary_valkey_key` to `messages` table in rag-chat (migration 0002).

**Applies to**: Any service with incremental Alembic migrations that add columns to existing tables.

---

---

## BP-120 — Post-Commit Hook Failures Silently Suppressed (Cache Invalidation Lost)

**Date discovered**: 2026-04-07
**Category**: Distributed Systems / Cache Consistency · **Severity**: MAJOR
**Affected areas**: S3 market-data `UnitOfWork.commit()`, S1 portfolio watchlist use case

**Symptom**: After a successful DB write and Kafka offset commit, the Valkey cache contains stale data with no mechanism to detect or repair it. Logs show `post_commit_hook_failed` warning but execution continues normally.

**Root cause**: Post-commit hooks (cache invalidation coroutines) are executed in a `try/except Exception: logger.warning(...)` block inside `commit()`. If Valkey is unavailable during hook execution, the exception is suppressed, the Kafka offset is already committed, and the stale cache entry persists until the next TTL expiry or explicit write.

**Evidence**:
- `services/market-data/src/market_data/infrastructure/db/uow.py:131-137`
- `services/portfolio/src/portfolio/application/use_cases/watchlist.py:229-236`

**Distinguishing from BP-003/004**: This is not a test setup issue — it occurs in production when Valkey is down or slow.

**Mitigation options**:
1. **Option A** (strict): Re-raise hook exception → consumer retries the Kafka message → stale cache gap is bounded by retry backoff
2. **Option B** (async repair): Persist hook failure to a dead-letter table → background job replays failed invalidations
3. **Option C** (accept): Current behaviour — stale cache for up to TTL (5s for quotes, varies for watchlists). Only acceptable if downstream callers can tolerate stale reads.

**Prevention**: When writing new post-commit hooks, explicitly document the consistency model. If the hook is critical (cache invalidation for a real-time feed), use Option A. If it's best-effort, document it and monitor `post_commit_hook_failed` counter.

**First seen**: QA pass QA-S1S2S3-2026-04-07 (finding M-002/M-003).

---

---

## BP-125 — pgvector Cosine Distance Formula Off-By-Two

**Symptom**: ANN similarity scores can be negative; final_score returns < 0 to API caller despite `min_score=0.0` filter.

**Root cause**: pgvector `<=>` cosine distance range is `[0, 2]` (not `[0, 1]`). Using `similarity = 1.0 - distance` produces negative values when distance > 1.0. For L2-normalized embeddings cosine distance is always in `[0, 1]`, making the formula safe in practice — but without an explicit floor clamp, any unnormalized embedding produces negative scores.

**Fix**: Use `ann_similarity = max(0.0, 1.0 - ann.distance)` as a safety floor. If the team wants the mathematically correct formula for the full `[0, 2]` range: `ann_similarity = 1.0 - ann.distance / 2.0`.

**Affected areas**: Any service performing pgvector ANN search and converting distance to similarity: `entity_embedding_ann.py`, `relation_summary.py`, any future ANN use case.

**Prevention**: Always add `max(0.0, ...)` floor when converting pgvector distances to similarity scores.

**First seen**: PLAN-0017 QA pass 2026-04-08.

---

---

## BP-126 — Alembic Migration NOT NULL Column Missing server_default

**Symptom**: `psycopg.errors.NotNullViolation: null value in column "X"` when inserting from seed scripts, tools, or future workers that omit the column.

**Root cause**: SQLAlchemy ORM models can declare `server_default=text("now()")` on a column, but Alembic migrations do NOT inherit `server_default` from the ORM model. If the migration `sa.Column(...)` definition omits `server_default`, the DDL column has no server-side default even though the ORM model appears to.

**Fix**: Always explicitly set `server_default=sa.text("now()")` (or the appropriate literal) in the Alembic `op.create_table(...)` column definition when the ORM model has a `server_default`.

**Affected areas**: Every Alembic migration that adds a NOT NULL column with a `server_default` in the ORM model.

**Prevention**: In code review, always cross-check: if ORM model has `server_default`, migration must too. If ORM model has `nullable=False`, either migration has `server_default` or all code paths explicitly provide the column.

**First seen**: PLAN-0017 migration 004 QA pass 2026-04-08.

---

---

## BP-128 — AGE Extension Functions Fail on New Connections Due to Missing Session Setup

**Symptom**: `ERROR: function create_graph does not exist` or `ERROR: type "agtype" does not exist` when calling Apache AGE functions (e.g., `create_graph`, `cypher`, `create_vlabel`) inside a migration or worker. Works in one session but fails in a fresh connection.

**Root cause**: Apache AGE requires two session-level commands before any AGE function can be used:
```sql
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
```
These are **not persistent** — they must be re-executed at the start of every database connection. If not configured via `shared_preload_libraries = 'age'` in `postgresql.conf`, every session (Alembic migration, async SQLAlchemy connection, direct psql) must call them explicitly. Workers with connection pooling will silently fail on connections that were created before the session setup.

**Fix**:
1. Preferred: add `'age'` to `shared_preload_libraries` in `postgresql.conf` (Docker image config). This makes AGE available to every connection automatically.
2. Fallback: add session setup in every code path that issues AGE commands:
   ```python
   await session.execute(text("LOAD 'age'"))
   await session.execute(text("SET search_path = ag_catalog, public"))
   ```
3. For Alembic migrations: include `LOAD 'age'` and `SET search_path` in the migration script itself (before any `create_graph()` call).

**Prevention**: Add `_setup_age_session()` helper to `AgeSyncWorker` and call it at the start of every `run()`. Add connection event listener in the session factory that auto-issues these commands for AGE-enabled sessions.

**Affected areas**: `intelligence-migrations` migration 0004, `AgeSyncWorker` (Worker 13F), `CypherPathUseCase`, `CypherNeighborhoodUseCase`.

**First seen**: PRD-0018 audit, 2026-04-08.

---

## BP-129 — Watermark-Based Incremental Sync Fails When Target Table Lacks `updated_at`

**Symptom**: An incremental sync worker (watermark pattern: `WHERE updated_at > :watermark`) silently syncs zero rows or crashes with `column does not exist` for tables that only have `created_at` or `latest_evidence_at` but not `updated_at`.

**Root cause**: The `relations` table (and similar append-heavy tables) often track `created_at` and `latest_evidence_at` but not a generic `updated_at`. When a watermark-based sync worker queries `WHERE updated_at > :watermark`, it either: (a) fails with a column error, or (b) silently misses rows whose confidence was recomputed (which updates `confidence_last_computed_at` but not `updated_at`).

**Fix**: Before implementing a watermark sync worker, verify every source table has an `updated_at` column that is updated on ALL mutation paths (initial insert + subsequent updates). If missing, add it via a non-destructive migration:
```sql
ALTER TABLE relations ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE INDEX idx_relations_updated_at ON relations (updated_at DESC);
```
Also add an `ON UPDATE` trigger or ensure all application-layer update paths explicitly set `updated_at = utc_now()`.

**Prevention**: PRD §6.4 DB table definitions should always include `updated_at` for any table used as a sync source. Plan migrations should verify the column exists before implementing the worker.

**Affected areas**: `AgeSyncWorker` (Worker 13F) — `relations` table required migration 0004 to add `updated_at`.

**First seen**: PRD-0018 audit, 2026-04-08.

---

## BP-131 — NULL Values in Multi-Column Unique Index Allow Semantic Duplicates

**Symptom**: Two rows exist in a table that should have been deduplicated by an `ON CONFLICT` upsert. One or more of the unique index columns is NULL. The upsert succeeds without conflict and creates a duplicate row.

**Root cause**: PostgreSQL standard behavior — `NULL ≠ NULL` in unique indexes. Two rows where the nullable column is NULL and all other columns are identical do NOT conflict with each other. The `ON CONFLICT (col_a, col_b, nullable_col, col_c) DO UPDATE` clause never fires for these rows.

**Examples in this codebase**:
- `temporal_events.uidx_temporal_events_natural_key` on `(event_type, region, title, date_trunc('day', active_from))` — LOCAL events have `region=NULL`; two LOCAL events with the same type/title/date create two rows
- BP-007 is a related pattern

**Fix options** (pick one):
1. **PostgreSQL 15+**: `CREATE UNIQUE INDEX ... ON table (...) NULLS NOT DISTINCT` — treats NULL as a distinct value in the uniqueness check. Requires dropping and recreating the index.
2. **Partial index** (all PG versions): `CREATE UNIQUE INDEX ... ON table (col_a, col_b, col_c) WHERE nullable_col IS NULL` plus the original index for non-NULL values. Requires two `INSERT` branches (one per NULL/non-NULL case).
3. **Sentinel value**: Replace NULL with a sentinel string (e.g., `__NULL__`). Ugly but universally compatible.
4. **Accept it**: If a compensating dedup mechanism (Valkey event-id dedup, application-level guard) covers the most common re-delivery paths, accepting rare semantic duplicates may be the pragmatic choice.

**Prevention**: When designing tables with nullable columns in unique constraints, explicitly decide which option to use and document it in the migration DDL comment. Verify the PostgreSQL version supports NULLS NOT DISTINCT if that option is chosen (PG ≥ 15).

**Affected areas**: `temporal_events.uidx_temporal_events_natural_key` (LOCAL events with NULL region), any table with nullable columns in a multi-column unique constraint.

**First seen**: PRD-0018 investigation, 2026-04-09.

---

## BP-136 — Shared Session Poisoned After Exception — Missing Rollback in Per-Item Loop

**Symptom**: A use case iterates over a list and writes each item atomically (fetch_log + outbox + commit). If item N fails, the exception handler increments `failed` but does NOT rollback. The shared SQLAlchemy session is now in an aborted transaction state. All subsequent items in the loop fail immediately with `sqlalchemy.exc.InvalidRequestError: Can't reconnect until invalid transaction is rolled back`.

**Root cause**: Missing `await session.rollback()` (or equivalent) in the `except` block of the per-item loop.

**Fix**: Call `await self._rollback_fn()` in the `except` block before continuing to the next iteration. Pass `rollback_fn=session.rollback` from the worker when constructing the use case.

**Prevention**: Any use case that shares a session across multiple loop iterations MUST have a `rollback_fn` parameter. Review checklist: "Does the exception handler rollback before continuing the loop?"

**First seen**: QA pass PLAN-0019, 2026-04-09 (M-02). Fixed in `FetchAndWritePredictionMarketsUseCase.execute`.

---

## BP-141 — Repository-Level session.rollback() Poisons Shared Session Context

**Symptom**: After a `DuplicateAlertError` (or any IntegrityError caught in a repo `save()` method), subsequent writes in the same request fail silently or raise `InvalidRequestError: Can't operate on rolled-back transaction`.

**Root cause**: A repo method calls `await self._session.rollback()` inside an `except IntegrityError` block. This rolls back the shared session that was created by the outer `async with session_factory() as session:` context manager. The context manager's own rollback-on-exit path then has nothing to do, but any code that continues after catching `DuplicateAlertError` operates on a dead session.

**Fix**: Remove `await self._session.rollback()` from repo-level exception handlers. Let the exception propagate; the `async with session_factory()` context manager handles rollback via `__aexit__`. The use case catches `DuplicateAlertError` and returns early without committing, so the session exits cleanly.

**Prevention**: Repository `save()` methods must NEVER call `session.rollback()` directly. Only the use-case-level `async with session_factory()` context manager owns the rollback.

**First seen**: PLAN-0021 QA pass, 2026-04-10 (F-150 Distributed Systems finding).

---

---

## BP-178 — asyncpg Rejects Parameter Binding Inside `interval '...'` String Literals

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (platform cold-start validation) |
| **Severity** | HIGH — worker fails to start; all retry/recovery logic disabled |
| **Affected areas** | Any SQLAlchemy `text()` query with parameterized interval durations (asyncpg driver) |
| **Root cause** | asyncpg does not support parameters inside PostgreSQL `interval '...'` string literals. `interval ':minutes minutes'` becomes `interval '$1 minutes'` in the wire protocol, which asyncpg rejects with `IndeterminateDatatypeError: could not determine data type of parameter $1`. The pattern looks valid in psycopg2 or psql but fails with asyncpg's prepared-statement protocol. |
| **Symptom** | `sqlalchemy.exc.ProgrammingError: IndeterminateDatatypeError: could not determine data type of parameter $1` on queries containing `interval ':param ...'`. |
| **Fix** | Replace `interval ':minutes minutes'` with `make_interval(mins => :minutes)` and `interval ':days days'` with `make_interval(days => :days)`. PostgreSQL's `make_interval()` function accepts named integer parameters that asyncpg binds correctly. Affected file: `nlp-pipeline/infrastructure/nlp_db/repositories/entity_mention.py`. |

### Prevention

Any raw SQL with a parameterized duration must use `make_interval()`. Add to `.claude/review/checklists/REVIEW_CHECKLIST.md`: "asyncpg: no `interval ':param ...'` literals — use `make_interval(mins => :param)` instead."

---

---

## BP-180 — asyncpg `AmbiguousParameterError` for Nullable Params in `IS NULL` Checks

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (news/top endpoint 500 in nlp-pipeline) |
| **Severity** | HIGH — endpoint returns 500 for all calls when any optional filter param is None |
| **Affected areas** | SQLAlchemy `text()` queries with nullable filter parameters using `IS NULL` checks (asyncpg driver) |
| **Root cause** | asyncpg requires type information for all parameters before executing a prepared statement. When a nullable parameter appears ONLY in `:param IS NULL` (with no adjacent typed comparison that asyncpg can infer from), asyncpg raises `AmbiguousParameterError`. This happens even when the same param also appears in `= :param` alongside a typed column, if the type inference is inside a CTE subquery. |
| **Symptom** | `asyncpg.exceptions.AmbiguousParameterError: could not determine data type of parameter $N` for queries with patterns like `:param IS NULL OR column >= :param`. |
| **Fix** | Wrap the parameter in an explicit `CAST`: `CAST(:param AS TEXT) IS NULL OR column = CAST(:param AS TEXT)` and `CAST(:param AS DOUBLE PRECISION) IS NULL OR column >= CAST(:param AS DOUBLE PRECISION)`. This gives asyncpg unambiguous type info. |

### Prevention

In all `text()` SQL with optional filter params, always use `CAST(:param AS <type>) IS NULL` rather than bare `:param IS NULL`. Add to `.claude/review/checklists/REVIEW_CHECKLIST.md`: "asyncpg text() SQL: nullable params in `IS NULL` checks need explicit CAST for type resolution."

---

---

## BP-200 — ValkeyClient.set() ex=/nx= Kwargs Not Forwarded

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-24 (live-stack certification: jti_check_valkey_unavailable on all services) |
| **Severity** | HIGH — JTI replay protection silently disabled; consumer deduplication broken |
| **Affected areas** | `libs/messaging/src/messaging/valkey/client.py`, all `internal_jwt.py` middleware copies, all KG/alert/nlp consumer `mark_processed()` methods |
| **Root cause** | `ValkeyClient.set(key, value, ttl=None)` uses `ttl=` but callers passed `ex=` (Redis API convention) or `nx=True`. `TypeError` was caught by `except Exception` in JTI middleware → silently logged as `jti_check_valkey_unavailable`; consumer dedup called with `ex=86400` → crash → all messages retried without dedup. |
| **Symptom** | All services logging `jti_check_valkey_unavailable`; consumer dead-letters for ValkeyClient.set TypeError |
| **Fix** | Added `ValkeyClient.set_nx(key, value, ex)` method for atomic SET NX. Updated `ValkeyClient.set` to accept both `ttl=` and `ex=` kwargs. Updated all `internal_jwt.py` to call `set_nx`. Updated all `test_internal_jwt_middleware.py` to mock `set_nx`. |

### Prevention

- When implementing wrapper APIs over redis.asyncio, always map native Redis kwargs (`ex=`, `nx=`, `px=`) to named parameters — or expose them directly. Don't introduce a different parameter name (`ttl=`) without aliasing the native one.
- Before writing any `except Exception: log_warning("service_unavailable")` pattern, verify the code path does not silently swallow `TypeError`/`AttributeError` caused by a programming error (API mismatch), not a runtime failure.

---

---

## BP-225 — `contextlib.suppress` on DB Insert Leaves SQLAlchemy Session Aborted

| Field | Value |
|-------|-------|
| **Service** | knowledge-graph (S7) |
| **Severity** | BLOCKING |
| **Discovered** | 2026-04-26 live-infra QA |
| **Root cause** | `contextlib.suppress(Exception)` around `alias_repo.insert()` catches the Python exception from an `IntegrityError` but does NOT roll back the asyncpg transaction. SQLAlchemy/asyncpg requires an explicit rollback (or SAVEPOINT) to recover. Any subsequent SQL in the same session fails with `asyncpg.InFailedSQLTransactionError`. |
| **Symptom** | Entity created successfully, then `entity_embedding_state.ensure_rows_exist()` fails with `InFailedSQLTransactionError: current transaction is aborted, commands ignored until end of transaction block`. |
| **Fix** | Use `session.begin_nested()` (SAVEPOINT) instead of `contextlib.suppress`. The SAVEPOINT is automatically rolled back on exception, leaving the outer transaction intact: `try: async with session.begin_nested(): await repo.insert(...) except Exception: pass` |

### Prevention

Never use `contextlib.suppress` to absorb database errors within an active SQLAlchemy async session. Use SAVEPOINTs (`session.begin_nested()`) for best-effort inserts that may collide.

---

---

## BP-235 — httpx Default 5s Read Timeout Shadows asyncio.wait_for Deadline

| Field | Value |
|-------|-------|
| **Service** | nlp-pipeline (S6) — `unresolved_resolution_worker.py`; any service using httpx with `asyncio.wait_for` |
| **Severity** | HIGH (makes configurable LLM timeout completely ineffective) |
| **Discovered** | 2026-04-26 investigation into unresolved resolution worker timeouts |
| **Root cause** | `httpx.AsyncClient()` with no arguments has `Timeout(5.0)` applied to ALL components: connect, read, write, pool. When calling `asyncio.wait_for(client.post(...), timeout=10.0)`, the httpx read timeout fires at 5s — before asyncio's 10s outer deadline — raising `httpx.ReadTimeout`. The asyncio wrapper never fires. Any call to `asyncio.wait_for` with an httpx client that has a shorter internal timeout will always be dominated by httpx, making the asyncio deadline useless. |
| **Symptom** | LLM API calls reliably fail at 5s despite `asyncio.wait_for(timeout=10.0)`. Configuration changes to the timeout setting have no effect. |
| **Fix** | Always pass an explicit timeout to the AsyncClient constructor: `httpx.AsyncClient(timeout=httpx.Timeout(desired_timeout))`. The inner httpx timeout must be >= the outer asyncio deadline, or the asyncio deadline is meaningless. |

### Prevention

When wrapping httpx calls in `asyncio.wait_for`, ALWAYS set `httpx.AsyncClient(timeout=httpx.Timeout(N))` with N >= the asyncio deadline. Never rely on `asyncio.wait_for` to be the effective timeout boundary — httpx's default will fire first. Add to code review checklist: "any asyncio.wait_for wrapping an httpx call must set matching timeout on the client".

---

---

## BP-235 — prediction_market_snapshots ON CONFLICT ON CONSTRAINT Fails — Index vs. Constraint

| Field | Value |
|-------|-------|
| **Service** | market-data (S3) — `prediction_market_repo.py:insert_if_not_exists()` |
| **Severity** | HIGH (all Polymarket snapshots fail to insert — `UndefinedObjectError`) |
| **Discovered** | 2026-04-27 ingestion pipeline audit |
| **Root cause** | Migration `005_add_prediction_markets.py` creates `uq_pms_market_snapshot` as `CREATE UNIQUE INDEX` (not `ALTER TABLE … ADD CONSTRAINT`). SQLAlchemy model `UniqueConstraint("market_id", "snapshot_at", name="uq_pms_market_snapshot")` causes Alembic to think it is a named constraint. The repository uses `.on_conflict_do_nothing(constraint="uq_pms_market_snapshot")` which generates `ON CONFLICT ON CONSTRAINT uq_pms_market_snapshot` — PostgreSQL raises `UndefinedObjectError: constraint "uq_pms_market_snapshot" does not exist` because it is an index, not a constraint. |
| **Symptom** | `kafka_unexpected_error: UndefinedObjectError: constraint "uq_pms_market_snapshot" for table "prediction_market_snapshots" does not exist` on every Polymarket Kafka message. `prediction_markets` and `prediction_market_snapshots` stay at 0 rows. |
| **Fix** | Changed to `.on_conflict_do_nothing(index_elements=["market_id", "snapshot_at"])` which works with unique indexes (not just named constraints). |

### Prevention

PostgreSQL `ON CONFLICT ON CONSTRAINT name` ONLY works when the name refers to a constraint created via `ADD CONSTRAINT`, NOT a bare `CREATE UNIQUE INDEX`. Use `.on_conflict_do_nothing(index_elements=[...])` when the unique restriction is a plain index. Always verify with `\d tablename` that the index appears in both `\di` (indexes) and `\d` (constraints) sections before using the constraint form.

---

---

## BP-246 — SQLAlchemy Session Poisoning Leaves Content-Ingestion Tasks Stuck in CLAIMED

| Field | Value |
|-------|-------|
| **Service** | content-ingestion (S4) — `infrastructure/workers/worker.py` |
| **Severity** | HIGH (tasks permanently stuck in CLAIMED — never retried or failed) |
| **Discovered** | 2026-04-27 ingestion pipeline investigation |
| **Root cause** | When a DB connection drops mid-transaction (SQLAlchemy "Can't reconnect until invalid transaction is rolled back"), the outer session is "poisoned". The exception handler calls `session.rollback()` (which also fails) then tries `task_repo.update_status(RETRY)` via the same poisoned session — this write also fails. The task is left in CLAIMED status with no recovery path. The `recover_expired_leases()` mechanism in the scheduler will eventually reclaim it after lease expiry, but this adds unnecessary delay. |
| **Symptom** | Tasks stuck in `CLAIMED` status long after expected completion time. `content_ingestion_tasks` shows tasks with `status='claimed'` and `lease_expires` already in the past. |
| **Fix** | Added `_rescue_stuck_task()` method that opens a fresh DB connection (new session from `_write_factory()`) to write the terminal status, bypassing the poisoned session. The exception handler now catches rollback errors (swallows them) and always calls `_rescue_stuck_task()`. |

### Prevention

- Any worker that holds a task lease MUST have a fallback that uses a fresh connection to release the lease on failure.
- Pool pre-ping (`pool_pre_ping=True`) only validates connections at acquisition time — it does NOT prevent in-flight drops.
- Session scope should be as narrow as possible: mark RUNNING → release session → do I/O → new session for writes.

---

## BP-260 — `is_due(watermark.current_bar_ts)` Blocks Re-Polling When Task Range Extends into the Future

**Summary**: The scheduler's `is_due` check uses `watermark.current_bar_ts` (= `task.range_end`). When a task's `range_end` is in the future (e.g., day-truncated `today + 1 day`), elapsed time is negative and `is_due` always returns `False` for that calendar day.

**Symptoms**: Scheduler evaluates N policies but enqueues 0 tasks every tick. All tasks succeeded but watermarks show `current_bar_ts` = tomorrow midnight.

**Affected areas**: `schedule_tasks.py` incremental polling for same-day tasks; specifically any policy with `base_interval_sec < 86400` that runs at least once per day.

**Pattern**:
`_build_incremental_task` sets `range_end = today + 1 day` for dedup stability. `execute_task.py` advances `watermark.current_bar_ts = task.range_end = tomorrow midnight`. `policy.is_due(tomorrow_midnight)` computes `elapsed = now - tomorrow < 0` → always `False`.

**Root cause**:
`current_bar_ts` represents the *temporal extent of the fetched data* (the task's requested time window end), not the *wall-clock time of the last execution*. Using it as a scheduling gate assumes tasks only run for past time windows. When `range_end` is in the future, the gate breaks.

**Fix (per-consumer workaround)**:
Use `watermark.last_success_at` instead of `current_bar_ts` for `is_due`. `last_success_at` is the actual wall-clock time of last execution and always lies in the past. Note: with day-truncated dedup keys, re-polling still produces 0 inserted tasks (deduplicated), but at least the scheduler generates candidates.

**Fix (architectural)**:
For intraday polling with minute-granular ranges, use `range_start = last_success_bar_ts` and `range_end = now`. This gives non-deduped tasks that actually fetch only the delta since the last run, but requires storing `last_success_bar_ts` carefully.

**Current behavior** (acceptable for thesis):
Each symbol's 1m bars are fetched once per day. US equities fetch during market hours (first scheduler tick after 13:30 UTC). Crypto fetches any time. Derived timeframes are updated once per day per symbol.

**Prevention**:
- Clarify in `schedule_tasks.py` whether `is_due` should use `current_bar_ts` or `last_success_at`.
- Add a comment documenting that day-truncated `range_end` sets `current_bar_ts` to a future date.
- If true intraday re-polling is needed, switch to `last_success_at` and minute-granular ranges.

---

---

## BP-264 — Holdings Drift from Cumulative Activity Replay

**Category**: Integration / Data correctness
**Severity**: CRITICAL
**First seen**: 2026-04-28 (PLAN-0046 Wave 1)
**Services**: portfolio (S1)

**Symptoms**:
- `holdings.quantity` is inflated 8-10x relative to the broker UI (e.g. 800 shares stored vs <100 in TastyTrade).
- Inflation accumulates over many sync cycles; new portfolios appear correct initially.

**Root cause**:
`RecordTransactionUseCase` called `Holding.apply_delta` on every transaction, so holdings were a running sum derived from the activity feed. Two interacting feed flaws compounded this into permanent drift:
1. `SnapTradeClient.get_activities` falls back from a legacy endpoint to `_get_activities_per_account` on any error; the two endpoint families assign DIFFERENT activity IDs to the same trade. `transactions.external_ref` dedup never fires.
2. The per-account path concatenates results across linked sub-accounts with no in-memory dedup; joint/individual mirrors emit the same trade twice.

The SAME trade therefore lands in `transactions` multiple times with different IDs, and `apply_delta` adds the quantity each time.

**Fix**:
Snapshot is the only authoritative source of "what the user holds right now":
1. New port method `IBrokerageClient.get_account_positions(user, account_id)` + `SnapTradePosition` VO.
2. New `UpsertHoldingsFromSnapshotUseCase`: aggregates positions by `instrument_id`, upserts to broker truth, deletes holdings absent from the snapshot.
3. `BrokerageTransactionSyncWorker` calls the snapshot path AFTER the activity loop.
4. `RecordTransactionUseCase` no longer mutates holdings; transactions are history-only.
5. `HoldingChanged` event ownership moved to the snapshot use case so consumers see broker-truth quantities.
6. One-shot recovery script `services/portfolio/scripts/repair_holdings_after_replay_drift.py` zeroes affected holdings; the next sync repopulates them. `--dry-run` reports without mutating.

**Prevention**:
- Never derive cumulative state purely from a paginated/multi-endpoint third-party feed. Always reconcile against a snapshot.
- Activity feeds are append-only HISTORY; positions are CURRENT STATE. Treat them differently.
- New ground-truth comparison check in `/qa` for brokerage integrations.

**Regression test**: `services/portfolio/tests/unit/test_use_cases_upsert_holdings_from_snapshot.py`

---

---

## BP-273 — `op.drop_constraint()` Fails on Bare UNIQUE INDEX

**Category**: Alembic migrations / schema
**Severity**: BLOCKING (migration fails to apply)
**Affected areas**: Any Alembic migration that tries to drop a uniqueness constraint originally created with raw SQL `CREATE UNIQUE INDEX`
**First seen**: 2026-04-29 (PLAN-0055 / revise-prd audit)

**Symptoms**:
- `alembic upgrade head` raises: `ProgrammingError: constraint "uq_xxx" of relation "table" does not exist`
- The constraint name exists in the plan/code but not in the database

**Root Cause**:
`op.drop_constraint("name", table, type_="unique")` only works on named UNIQUE CONSTRAINTs created via `ADD CONSTRAINT`. A bare `CREATE UNIQUE INDEX idx_name ON table (cols)` creates an **index**, not a constraint. Postgres stores these differently: `pg_constraint` vs `pg_indexes`. Alembic's `drop_constraint` targets `pg_constraint`; a bare index is invisible to it.

Example: migration 0009 uses raw SQL `CREATE UNIQUE INDEX idx_article_impact_windows_unique ON article_impact_windows (article_id, entity_id, window_type)`. A later migration that does `op.drop_constraint("idx_article_impact_windows_unique", ...)` will fail.

**Fix**:
Use `op.drop_index("idx_article_impact_windows_unique", table_name="article_impact_windows")` to drop a bare unique index, then create the replacement using `op.create_unique_constraint(...)` (which creates a named `pg_constraint` entry).

**Prevention**:
- When creating a new UNIQUE in a migration, always prefer `op.create_unique_constraint("name", table, cols)` over raw `CREATE UNIQUE INDEX`. The former creates a named constraint droppable via `op.drop_constraint()`; the latter does not.
- Before writing `op.drop_constraint()`, run `SELECT conname FROM pg_constraint WHERE conrelid = 'table'::regclass AND contype = 'u'` to verify the constraint actually exists. If it doesn't appear, use `op.drop_index()` instead.

---

## BP-334 — Provisional Enrichment Alias Duplicate on Recovery Sweep

**Date discovered**: 2026-05-03
**Service affected**: `knowledge-graph` (ProvisionalEnrichmentWorker via `provisional_enrichment_core.py`)

### Symptom

After the stale-processing recovery sweep resets queue items back to `pending`, the enrichment batch fails entirely:

```
UniqueViolationError: duplicate key value violates unique constraint "uidx_entity_aliases_entity_norm_type"
DETAIL: Key (entity_id, normalized_alias_text, alias_type)=(a94efff0-..., aurora innovation, EXACT) already exists.
event: "provisional_enrichment_error"
enriched: 0, failed: 50
```

### Root cause

`provisional_enrichment_core.persist_enrichment()` calls two alias-insert paths for the canonical name:

1. `CanonicalEntityRepository.create()` — co-inserts an EXACT self-alias using `ON CONFLICT DO NOTHING` (safe, idempotent).
2. `EntityAliasRepository.insert()` — bare `INSERT` with no conflict handling for the same `(entity_id, 'aurora innovation', EXACT)` tuple.

On first run, step 1 inserts the alias. The session then fails at some later point (e.g. embedding write), `session.rollback()` undoes everything **except** step 1 if it was committed in a `begin_nested()` savepoint. The queue item stays in `processing`. On the next cycle, the recovery sweep resets it to `pending`. Step 2 re-runs with the same `entity_id` (from a previous partial run) and hits the pre-existing alias.

### Fix

Add `ON CONFLICT (entity_id, normalized_alias_text, alias_type) WHERE is_active = true DO NOTHING` to `EntityAliasRepository.insert()` and return `UUID | None` instead of `UUID`.

```python
# Before (entity_alias.py):
result = await self._session.execute(
    text("INSERT INTO entity_aliases ... RETURNING alias_id"),
    {...},
)
row = result.fetchone()
return UUID(str(row[0]))

# After:
result = await self._session.execute(
    text("""
INSERT INTO entity_aliases ...
ON CONFLICT (entity_id, normalized_alias_text, alias_type)
WHERE is_active = true
DO NOTHING
RETURNING alias_id
"""),
    {...},
)
row = result.fetchone()
return UUID(str(row[0])) if row else None
```

### Prevention

- Any repository `insert()` method for a table with a partial unique index must use `ON CONFLICT DO NOTHING` (or an explicit upsert) to be safe under retry/recovery patterns.
- The cascading rollback pattern in the Phase 3 loop (sequential items in a single session, each one rolling back on failure) means recovery always re-processes the same items — all inserts must be idempotent.

**Regression test**: `services/knowledge-graph/tests/unit/infrastructure/repositories/test_entity_alias_upsert.py`

---
