# PLAN-0006: Process Architecture & Database Standardization

> **PRD**: N/A (architectural improvement — user-driven)
> **Status**: in-progress
> **Created**: 2026-03-28
> **Updated**: 2026-03-30

> **Owner**: Arnau Rodon

---

## 1. Context & Goal

The content-ingestion service (S4) currently runs API, scheduler, and outbox dispatcher
as a **single monolithic process** wired together in `app.py` lifespan. This violates the
separation-of-concerns principle already established by market-ingestion (S2), which runs
scheduler, workers, and dispatcher as **separate processes** that scale independently.

### Goals

1. **Decouple content-ingestion** into 4 independent processes: API, Scheduler, Worker, Dispatcher
2. **Adopt scheduler-worker pattern** (consistent with market-ingestion) for horizontal scaling
3. **Add read/write database session split** to content-ingestion (and enforce as project standard)
4. **Establish project-wide rules** for process separation, database session patterns, and session optimization
5. **Document database infrastructure decisions** (PgBouncer, connection pooling, managed service readiness)

### Non-Goals (deferred)

- Cross-service read/write split rollout (separate plan — each service incrementally)
- PgBouncer deployment (premature for thesis; documented as production recommendation)
- Separate PostgreSQL instances per service (current shared Postgres with per-service databases is correct)

---

## 2. Architecture Decisions

### AD-1: PgBouncer vs Separate Postgres Instances

**Decision**: Keep shared PostgreSQL container with per-service databases. Do NOT add PgBouncer now. Do NOT create separate Postgres instances.

**Rationale**:
- Current setup (one Postgres container, multiple databases) enforces data ownership at the schema level
- PgBouncer adds operational complexity without benefit in dev (single developer, limited load)
- Separate Postgres containers (10 instances!) would be overkill for a thesis project
- When moving to managed services, each service naturally gets its own RDS/Cloud SQL instance

**What to do instead**:
- **Tune pool sizes per process type** — this delivers 90% of PgBouncer's benefit without operational overhead
- **Document PgBouncer as production recommendation** in STANDARDS.md
- **Ensure all services support independent database URLs** (already the case via `db_url` settings)

**Pool size recommendations per process type**:

| Process Type | pool_size | max_overflow | pool_pre_ping | Rationale |
|-------------|-----------|-------------|---------------|-----------|
| API server | 10 | 20 | Yes | Concurrent HTTP requests |
| Scheduler | 3 | 5 | Yes | Low concurrency, periodic ticks |
| Worker | 5 | 10 | Yes | Bounded by semaphore concurrency |
| Dispatcher | 3 | 5 | Yes | Single-threaded poll loop |

### AD-2: Database Session Optimization

**Problem**: Holding a DB session (and its underlying connection) during external I/O wastes pool resources.

**Anti-pattern** (BP-016 already documents a specific case):
```python
async with session_factory() as session:
    data = await repo.get(id)              # uses connection
    result = await http_client.post(...)   # connection held idle!
    await repo.save(result)                # uses connection again
    await session.commit()
```

**Correct patterns**:

1. **Split read/IO/write phases** (already done in content-ingestion `_run_fetch_cycle`):
   ```python
   async with session_factory() as ro:
       data = await repo.get(id)           # read phase
   result = await http_client.post(...)    # IO phase (no session)
   async with session_factory() as rw:
       await repo.save(result)             # write phase
       await rw.commit()
   ```

2. **API routes**: Session-per-request via `Depends()` is acceptable — requests are short-lived.
   The connection is held for milliseconds during typical CRUD. Optimize only if profiling shows contention.

3. **Workers**: Each task creates a fresh UoW per phase. Claim → release → fetch → release → write → release.

4. **Scheduler**: One short UoW per tick (evaluate sources → insert tasks → commit).

**New rule (R22)**: Background processes (workers, schedulers, dispatchers) MUST NOT hold
database sessions across external I/O calls.

### AD-3: Read/Write Session Split — Known Pitfalls

**Read-after-write consistency**: When you write to primary and immediately read, the read replica
may return stale data due to replication lag.

**Rules for read routing**:

| Operation | Use Write Session | Use Read Session |
|-----------|:-:|:-:|
| SELECT before INSERT/UPDATE (dedup checks) | Yes | No — stale reads cause duplicates |
| Task claiming (SELECT FOR UPDATE SKIP LOCKED) | Yes | No — requires row locks |
| List/dashboard/analytics queries | No | Yes |
| Watermark reads before fetch cycle | Either | Yes (staleness acceptable; worst case = redundant fetch) |
| Health checks / status endpoints | No | Yes |
| Read immediately after write in same request | Yes | No — replication lag |

**Implementation**: When no read-replica URL is configured, the read factory falls back
to the write factory (zero-cost compatibility layer). This is how market-ingestion does it.

### AD-4: Scheduler Horizontal Scaling

**How market-ingestion solves it**: `INSERT ... ON CONFLICT DO NOTHING` on the task table.
Multiple scheduler instances can run concurrently — duplicate task creation is idempotent.

**For content-ingestion**: Same approach. The scheduler evaluates which sources are due and
inserts task rows. A unique constraint on `(source_id, window_start)` prevents duplicates.
Multiple schedulers running simultaneously are safe — they'll try to insert the same tasks,
and `ON CONFLICT DO NOTHING` deduplicates.

For additional safety, an advisory lock (`pg_advisory_lock(hash('s4:scheduler'))`) can
ensure only one scheduler runs the tick at a time. This is optional — the dedup constraint
is the primary safeguard.

---

## 3. Sub-Plan Overview

| Sub-Plan | Scope | Waves | Depends On |
|----------|-------|-------|-----------|
| **A** | Project-wide standards & rules | 1 | None |
| **B** | Content-Ingestion: scheduler-worker + decoupling + read/write split | 4 | A |

**Total**: 5 waves, ~24 tasks

**Dependency graph**:
```
Sub-Plan A (standards)
    ↓
Sub-Plan B Wave 1 (domain + config)
    ↓
Sub-Plan B Wave 2 (infrastructure: DB, repos, sessions)
    ↓
Sub-Plan B Wave 3 (application: use cases, scheduler, worker)
    ↓
Sub-Plan B Wave 4 (API cleanup, dispatcher extraction, Docker, tests)
```

---

## 4. Sub-Plan A: Standards & Rules

### Wave A-1: Project-Wide Standards for Process Architecture & Database Patterns ✅

**Goal**: Establish enforceable rules and documented patterns for process separation, read/write database access, and session optimization across the entire project.
**Depends on**: none
**Estimated effort**: 30-45 minutes
**Architecture layer**: docs
**Status**: **DONE** — 2026-03-29 · docs-only wave · ruff + mypy N/A

#### Tasks

---

#### T-A-1-01: Add Process Architecture Rules to RULES.md

**Type**: docs
**depends_on**: none
**blocks**: [T-A-1-02]
**Target files**: `RULES.md`

**What to build**:
Add three new hard rules to RULES.md that enforce process separation, read/write database
split, and session optimization across all services. These become the architectural foundation
for all subsequent decoupling work.

**Rules to add**:

- **R22 — Process separation**: Services with background processing (scheduling, workers, outbox dispatch) MUST run each concern as an independent process with its own entry point. The API process MUST NOT embed scheduler loops, worker loops, or outbox dispatcher loops in its lifespan. Each process type MUST have its own signal handling (SIGINT/SIGTERM) and connection pool sizing.

- **R23 — Read/write database split**: Every service MUST support dual database URLs (`DATABASE_URL` for writes, `DATABASE_URL_READ` for reads). When the read URL is not configured, the write URL MUST be used as fallback (zero-cost compatibility). Read-after-write operations and row-locking queries MUST use the write session. Session factories MUST set `expire_on_commit=False` and `pool_pre_ping=True`.

- **R24 — Session optimization**: Background processes (workers, schedulers, dispatchers) MUST NOT hold database sessions/connections across external I/O calls (HTTP requests, MinIO operations, Kafka publishes). API routes using FastAPI `Depends()` session-per-request are exempt (short-lived). Each process type MUST configure pool sizes appropriate to its concurrency profile (see STANDARDS.md §14).

**Acceptance criteria**:
- [ ] Rules R22, R23, R24 added to RULES.md with MUST/MUST NOT language
- [ ] Each rule references the relevant STANDARDS.md section for implementation details
- [ ] Existing rule numbering preserved (append after R21)

---

#### T-A-1-02: Add Process Topology & Database Patterns to STANDARDS.md

**Type**: docs
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**: `docs/STANDARDS.md`

**What to build**:
Add three new sections to STANDARDS.md documenting the implementation patterns for
R22/R23/R24. These sections provide code examples, pool size tables, and anti-patterns
that agents follow during implementation.

**Sections to add**:

- **§14 Process Topology Standard**:
  - Service processes: API (uvicorn), Scheduler (asyncio loop), Worker (claim-execute loop), Dispatcher (extends BaseOutboxDispatcher)
  - Each process: own `main()`, own Settings instantiation, own session factories, signal handlers
  - Docker Compose: same Dockerfile, different `command` overrides
  - Entry point pattern: `python -m <service>.infrastructure.<component>.<module>`
  - Reference implementation: `services/market-ingestion/`
  - Pool size table per process type (from AD-1)

- **§15 Read/Write Database Session Pattern**:
  - Dual factory function: `_build_factories(settings) -> (write_factory, read_factory)`
  - Config: `db_url` (write, required), `db_url_read` (read, optional, falls back to db_url)
  - Read/write routing table (from AD-3)
  - Anti-pattern: reading from replica immediately after write
  - Reference implementation: `services/market-ingestion/infrastructure/db/session.py`

- **§16 Session Optimization**:
  - Anti-pattern: holding session across external I/O (with code example)
  - Correct pattern: split read/IO/write phases
  - API routes: session-per-request is acceptable (short-lived)
  - Workers: fresh UoW per phase (claim → release → execute → release)
  - Scheduler: one UoW per tick
  - PgBouncer: recommended for production, not required for development
  - Managed database readiness: all services MUST support independent database URLs

**Acceptance criteria**:
- [ ] Sections §14, §15, §16 added to STANDARDS.md
- [ ] Code examples included for each pattern
- [ ] Pool size table included
- [ ] Read/write routing table included
- [ ] Anti-patterns documented with code examples
- [ ] References to market-ingestion as reference implementation

---

#### T-A-1-03: Add Session-Held-Across-IO Bug Pattern to BUG_PATTERNS.md

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**: `docs/BUG_PATTERNS.md`

**What to build**:
Document a new bug pattern for holding database sessions across external I/O calls.
This codifies BP-016's lesson (advisory lock spanning external I/O) into a broader
pattern that applies to all services.

**Pattern to add**:

- **BP-045: Database session held across external I/O**
  - **Symptom**: Connection pool exhaustion under load; `TimeoutError` on `pool.acquire()`
  - **Cause**: Session opened before HTTP/MinIO/Kafka call, held idle during I/O, released after
  - **Fix**: Split into read → release → I/O → acquire → write phases
  - **Detection**: Grep for `session_factory()` context managers that span `http_client`, `storage`, or `producer` calls
  - **Related**: BP-016 (advisory lock across I/O)

**Acceptance criteria**:
- [ ] BP-045 added to BUG_PATTERNS.md with symptom, cause, fix, detection sections
- [ ] Cross-reference to BP-016

---

#### Pre-read (agent must read before starting)
- `RULES.md`
- `docs/STANDARDS.md`
- `docs/BUG_PATTERNS.md`
- `services/market-ingestion/src/market_ingestion/infrastructure/db/session.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/schedulers/scheduler.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/workers/worker.py`

#### Validation Gate
- [x] ruff check passes on changed files (markdown only — N/A)
- [x] Documentation updated
- [x] Rule numbers sequential (R22, R23, R24)
- [x] Standards sections sequential (§14, §15, §16)
- [x] BP number sequential (BP-057 — BP-045 was already taken)

---

## 5. Sub-Plan B: Content-Ingestion Decoupling

### Wave B-1: Domain Layer — Task Entity, Enums, Config ✅

**Goal**: Define the `ContentIngestionTask` domain entity with state machine, new enums, and config additions that the scheduler-worker pattern requires.
**Depends on**: Wave A-1
**Estimated effort**: 30-45 minutes
**Architecture layer**: domain + config
**Status**: **DONE** — 2026-03-29 · 26 new tests (317 total unit) · ruff + mypy clean

#### Tasks

---

#### T-B-1-01: Add IngestionTaskStatus Enum ✅

**Type**: impl
**depends_on**: none
**blocks**: [T-B-1-02]
**Target files**: `libs/contracts/src/contracts/enums.py` (standardized in shared lib instead of service-local)

**What was built**:
Standardized `IngestionTaskStatus` StrEnum in `contracts.enums` (shared library) instead of
adding it only to content-ingestion. Market-ingestion's local copy was replaced with a
re-export from `contracts.enums`. Content-ingestion re-exports from the same shared location.

**Entities / Components**:
- **Name**: `IngestionTaskStatus`
- **Purpose**: State machine states for ingestion tasks (shared across S2 + S4)
- **Values**: PENDING, CLAIMED, RUNNING, SUCCEEDED, RETRY, FAILED
- **Invariants**:
  - Only `PENDING` and `RETRY` tasks can be claimed
  - `CLAIMED` → `RUNNING` → `SUCCEEDED` | `FAILED` | `RETRY`
  - `FAILED` is a terminal state
  - `CLAIMED` is optional — S2 skips it (PENDING → RUNNING directly)

**Tests written**: 7 in `libs/contracts/tests/test_enums.py` (TestIngestionTaskStatus class)
**Market-ingestion tests updated**: exhaustive membership tests now include `claimed`

**Acceptance criteria**:
- [x] `IngestionTaskStatus` StrEnum with 6 values in `contracts.enums`
- [x] Consistent with market-ingestion's status model
- [x] Market-ingestion re-exports from contracts (backward compat preserved)
- [x] Content-ingestion re-exports from contracts
- [x] 7 new tests passing in contracts, 48 market-ingestion domain tests passing

---

#### T-B-1-02: Add ContentIngestionTask Entity with State Machine ✅

**Type**: impl
**depends_on**: [T-B-1-01]
**blocks**: [T-B-2-01, T-B-2-02, T-B-2-03]
**Target files**: `services/content-ingestion/src/content_ingestion/domain/entities.py`

**What to build**:
Add the `ContentIngestionTask` frozen dataclass to the domain layer. This entity represents
a unit of work for the worker to execute — one fetch cycle for one source.

**Entities / Components**:
- **Name**: `ContentIngestionTask`
- **Purpose**: A unit of work representing a single fetch cycle for one content source
- **Key attributes**:
  - `id: UUID` — UUIDv7, default from `common.ids.new_uuid7()`
  - `source_id: UUID` — FK to the `sources` table
  - `source_name: str` — Denormalized for logging/metrics (avoids read-after-write to sources)
  - `source_type: SourceType` — Enum (eodhd, sec_edgar, finnhub, newsapi)
  - `status: IngestionTaskStatus` — Default `PENDING`
  - `worker_id: str | None` — ULID of the claiming worker, None until claimed
  - `leased_at: datetime | None` — When the worker claimed the task
  - `lease_expires: datetime | None` — When the lease expires
  - `attempt_count: int` — Default 0, incremented on each attempt
  - `max_attempts: int` — Default 5
  - `error_detail: str | None` — Last error message
  - `is_backfill: bool` — Default False
  - `window_start: datetime | None` — For dedup (unique with source_id)
  - `created_at: datetime` — Default from `common.time.utc_now()`
  - `updated_at: datetime` — Default from `common.time.utc_now()`

- **Key methods**:
  - `claim(worker_id: str, lease_seconds: int) -> None` — Transition PENDING/RETRY → CLAIMED, set worker_id + lease
  - `start() -> None` — Transition CLAIMED → RUNNING
  - `succeed() -> None` — Transition RUNNING → SUCCEEDED
  - `fail(error: str) -> None` — Transition RUNNING → FAILED (if attempt_count >= max_attempts) or RETRY
  - `is_claimable: bool` — Property: status in (PENDING, RETRY)
  - `is_lease_expired(now: datetime) -> bool` — True if lease_expires < now

- **Invariants**:
  - State transitions enforced (raise `DomainError` on invalid transition)
  - `claim()` only valid from PENDING or RETRY
  - `start()` only valid from CLAIMED
  - `succeed()` / `fail()` only valid from RUNNING
  - `fail()` with attempt_count < max_attempts → RETRY (increments attempt_count)
  - `fail()` with attempt_count >= max_attempts → FAILED (terminal)

- **Factory method**:
  - `create_for_source(source: Source, is_backfill: bool = False, window_start: datetime | None = None) -> ContentIngestionTask`

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_create_for_source | Factory creates task with correct fields from Source | unit |
| test_claim_from_pending | PENDING → CLAIMED sets worker_id + lease | unit |
| test_claim_from_retry | RETRY → CLAIMED works | unit |
| test_claim_invalid_state | claim() from RUNNING/SUCCEEDED/FAILED raises DomainError | unit |
| test_start_from_claimed | CLAIMED → RUNNING | unit |
| test_start_invalid_state | start() from non-CLAIMED raises DomainError | unit |
| test_succeed | RUNNING → SUCCEEDED | unit |
| test_fail_with_retries_left | RUNNING → RETRY when attempt_count < max_attempts | unit |
| test_fail_exhausted | RUNNING → FAILED when attempt_count >= max_attempts | unit |
| test_is_claimable | True for PENDING/RETRY, False for others | unit |
| test_is_lease_expired | True when now > lease_expires | unit |

- Minimum test count: 11
- Edge cases: claim with 0 lease_seconds, fail at exactly max_attempts boundary
- Error paths: every invalid state transition

**Acceptance criteria**:
- [x] `ContentIngestionTask` dataclass in `domain/entities.py`
- [x] All state transitions enforced with `InvalidStateTransition` (subclass of `DomainError`)
- [x] Factory method `create_for_source`
- [x] 23 unit tests passing (exceeds 11 minimum)

---

#### T-B-1-03: Add Scheduler/Worker Config to Settings ✅

**Type**: impl
**depends_on**: none
**blocks**: [T-B-2-01, T-B-3-01, T-B-3-04]
**Target files**: `services/content-ingestion/src/content_ingestion/config.py`

**What to build**:
Add scheduler-worker and read/write database configuration fields to the existing
`Settings` class, following market-ingestion's pattern.

**Fields to add**:

```python
# ── Read replica ───────────────────────────────────────────────────
db_url_read: str = ""  # Falls back to db_url if empty

# ── Scheduler (process) ───────────────────────────────────────────
scheduler_tick_interval_seconds: float = 60.0
scheduler_max_tasks_per_tick: int = 100

# ── Worker (process) ──────────────────────────────────────────────
worker_batch_size: int = 5
worker_lease_seconds: int = 300
worker_idle_sleep_seconds: float = 5.0
worker_concurrency: int = 2
worker_task_timeout_seconds: float = 120.0
```

**Logic & Behavior**:
- `db_url_read` defaults to empty string; session factory falls back to `db_url`
- `scheduler_tick_interval_seconds` controls how often the scheduler evaluates sources (60s default, vs 300s for the old poll interval)
- `worker_batch_size` controls how many tasks a worker claims per iteration (5 for content, vs 10 for market — content tasks are heavier)
- `worker_lease_seconds` = 300 (5 min) — same as market-ingestion
- `worker_concurrency` = 2 — semaphore permits (lower than market-ingestion's 4 because content fetches are slower)

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_settings_defaults | New fields have correct defaults | unit |
| test_db_url_read_fallback | Empty db_url_read is valid (fallback handled by session factory) | unit |

**Acceptance criteria**:
- [x] All new config fields added to `Settings`
- [x] Defaults match documented values
- [x] Env prefix `CONTENT_INGESTION_` applies to all new fields
- [x] 3 tests passing (defaults, fallback, env overrides)

---

#### Pre-read (agent must read before starting)
- `services/content-ingestion/src/content_ingestion/domain/entities.py`
- `services/content-ingestion/src/content_ingestion/domain/exceptions.py`
- `services/content-ingestion/src/content_ingestion/config.py`
- `services/market-ingestion/src/market_ingestion/domain/entities/ingestion_task.py`
- `services/market-ingestion/src/market_ingestion/config.py`

#### Validation Gate
- [x] ruff check passes on changed files
- [x] mypy passes on `content_ingestion`
- [x] Unit tests pass — 26 new tests (exceeds 15 minimum)
- [x] Domain layer has no infrastructure imports

#### Regression Guardrails
- BP-016: Do not add any session management to domain layer
- BP-035: State machine must enforce valid transitions atomically

---

### Wave B-2: Infrastructure — DB Migration, Repositories, Dual Session Factory ✅

**Goal**: Create the database schema for `content_ingestion_tasks`, ORM model, task repository with `SELECT FOR UPDATE SKIP LOCKED` claiming, and the read/write dual session factory.
**Depends on**: Wave B-1
**Estimated effort**: 45-60 minutes
**Architecture layer**: infrastructure
**Status**: **DONE** — 2026-03-29 · 341 tests pass · ruff + mypy clean

#### Tasks

---

#### T-B-2-01: Implement Read/Write Dual Session Factory

**Type**: impl
**depends_on**: [T-B-1-03]
**blocks**: [T-B-2-04, T-B-3-01, T-B-3-04]
**Target files**: `services/content-ingestion/src/content_ingestion/infrastructure/db/session.py`

**What to build**:
Replace the single-factory `create_session_factory()` with a dual `_build_factories()`
function that returns separate write and read session factories. Mirrors
`services/market-ingestion/src/market_ingestion/infrastructure/db/session.py` exactly.

**Entities / Components**:
- **Name**: `_build_factories(settings) -> (write_factory, read_factory)`
- **Purpose**: Create dual session factories with per-process-type pool sizing
- **Key behavior**:
  - Write engine: `pool_size=10, max_overflow=20, pool_pre_ping=True, expire_on_commit=False`
  - Read URL: `settings.db_url_read or settings.db_url` (fallback)
  - If read URL == write URL: reuse write factory (no wasted connections)
  - If different: separate engine with `pool_size=20, max_overflow=30`
  - Keep `create_session_factory()` as thin wrapper returning `(engine, write_factory)` for backward compat during transition
- **Depends on**: `Settings.db_url_read` from T-B-1-03

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_build_factories_single_url | When db_url_read is empty, read_factory == write_factory | unit |
| test_build_factories_dual_url | When db_url_read differs, two separate factories | unit |
| test_write_factory_pool_config | Write engine has pool_size=10, expire_on_commit=False | unit |

**Acceptance criteria**:
- [ ] `_build_factories()` returns `(write_factory, read_factory)`
- [ ] Fallback to write URL when read URL is empty
- [ ] `expire_on_commit=False` on both factories
- [ ] `pool_pre_ping=True` on both engines
- [ ] Backward-compatible `create_session_factory()` still works
- [ ] 3+ tests passing

---

#### T-B-2-02: Alembic Migration + ORM Model for content_ingestion_tasks

**Type**: schema
**depends_on**: [T-B-1-02]
**blocks**: [T-B-2-03]
**Target files**:
- `services/content-ingestion/alembic/versions/<timestamp>_add_content_ingestion_tasks.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/db/models.py`

**What to build**:
Create the Alembic migration and SQLAlchemy ORM model for the `content_ingestion_tasks`
table. This stores the task queue that the scheduler writes to and workers claim from.

**Table schema** (`content_ingestion_tasks`):

| Column | Type | Constraints | Notes |
|--------|------|------------|-------|
| `id` | `UUID` | PK | UUIDv7 |
| `source_id` | `UUID` | NOT NULL, FK → `sources.id` | |
| `source_name` | `VARCHAR(255)` | NOT NULL | Denormalized for logging |
| `source_type` | `VARCHAR(50)` | NOT NULL | SourceType enum value |
| `status` | `VARCHAR(20)` | NOT NULL, DEFAULT 'pending' | IngestionTaskStatus |
| `worker_id` | `VARCHAR(64)` | NULL | ULID of claiming worker |
| `leased_at` | `TIMESTAMPTZ` | NULL | When claimed |
| `lease_expires` | `TIMESTAMPTZ` | NULL | When lease expires |
| `attempt_count` | `INTEGER` | NOT NULL, DEFAULT 0 | |
| `max_attempts` | `INTEGER` | NOT NULL, DEFAULT 5 | |
| `error_detail` | `TEXT` | NULL | Last error message |
| `is_backfill` | `BOOLEAN` | NOT NULL, DEFAULT FALSE | |
| `window_start` | `TIMESTAMPTZ` | NULL | Dedup anchor |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT NOW() | |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT NOW() | |

**Indexes**:
- `ix_cit_status_created` on `(status, created_at)` — worker claim queries
- `ix_cit_source_window` UNIQUE on `(source_id, window_start)` WHERE `window_start IS NOT NULL` — scheduler dedup
- `ix_cit_worker_lease` on `(worker_id, lease_expires)` — lease expiry scans

**ORM Model** (`ContentIngestionTaskModel`):
- Maps 1:1 to table columns
- Relationship to `SourceModel` (many-to-one)
- `__tablename__ = "content_ingestion_tasks"`

**Downstream test impact**:
- Existing Alembic migration tests may need to be updated
- No Avro schema changes

**Acceptance criteria**:
- [ ] Alembic migration creates table with all columns and indexes
- [ ] ORM model maps all columns with correct SQLAlchemy types
- [ ] Migration is reversible (downgrade drops table)
- [ ] All TIMESTAMP columns are TIMESTAMPTZ
- [ ] Unique partial index on (source_id, window_start) prevents duplicate tasks

---

#### T-B-2-03: Implement TaskRepository with Claim-Batch

**Type**: impl
**depends_on**: [T-B-2-02]
**blocks**: [T-B-3-01, T-B-3-02, T-B-3-03]
**Target files**: `services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/task.py`

**What to build**:
Implement the `TaskRepository` that provides task CRUD and the critical `claim_batch()`
method using `SELECT ... FOR UPDATE SKIP LOCKED` for concurrent worker safety.

**Entities / Components**:
- **Name**: `TaskRepository`
- **Purpose**: Database operations for `content_ingestion_tasks` table
- **Key methods**:
  - `add(task: ContentIngestionTask) -> None` — Insert a new task
  - `add_many_idempotent(tasks: list[ContentIngestionTask]) -> int` — Bulk insert with `ON CONFLICT DO NOTHING`, returns inserted count
  - `claim_batch(worker_id: str, limit: int, lease_seconds: int) -> list[ContentIngestionTask]` — Atomically claim PENDING/RETRY tasks using `SELECT ... FOR UPDATE SKIP LOCKED`
  - `update_status(task_id: UUID, status: str, error_detail: str | None = None) -> None` — Update task status and error
  - `has_active_task(source_id: UUID) -> bool` — Check if source has PENDING/CLAIMED/RUNNING task
  - `count_by_status() -> dict[str, int]` — For metrics

- **claim_batch SQL pattern** (from market-ingestion):
  ```sql
  WITH candidates AS (
      SELECT id FROM content_ingestion_tasks
      WHERE status IN ('pending', 'retry')
      ORDER BY created_at ASC
      LIMIT :limit
      FOR UPDATE SKIP LOCKED
  )
  UPDATE content_ingestion_tasks
  SET status = 'claimed',
      worker_id = :worker_id,
      leased_at = :now,
      lease_expires = :now + interval ':lease_seconds seconds',
      updated_at = :now
  WHERE id IN (SELECT id FROM candidates)
  RETURNING *
  ```

- **Invariants**:
  - `claim_batch` MUST use `FOR UPDATE SKIP LOCKED` (not `FOR UPDATE`) to prevent worker contention
  - `add_many_idempotent` MUST use `ON CONFLICT (source_id, window_start) DO NOTHING`
  - All timestamps MUST be UTC

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_add_task | Inserts task, read back matches | unit |
| test_add_many_idempotent_no_conflict | All tasks inserted when no conflicts | unit |
| test_add_many_idempotent_with_conflict | Duplicates skipped, count correct | unit |
| test_claim_batch_empty | Returns empty list when no claimable tasks | unit |
| test_claim_batch_claims_pending | Claims PENDING tasks, sets worker_id + lease | unit |
| test_claim_batch_claims_retry | Claims RETRY tasks | unit |
| test_claim_batch_skips_running | Does not claim RUNNING/SUCCEEDED/FAILED | unit |
| test_claim_batch_respects_limit | Claims at most `limit` tasks | unit |
| test_has_active_task | True when source has PENDING/CLAIMED/RUNNING task | unit |
| test_update_status | Updates status + error_detail + updated_at | unit |
| test_count_by_status | Returns correct counts per status | unit |

- Minimum test count: 11
- Edge cases: empty table, all tasks already claimed, concurrent claims (integration test)

**Acceptance criteria**:
- [ ] `TaskRepository` with all 6 methods
- [ ] `claim_batch` uses `FOR UPDATE SKIP LOCKED`
- [ ] `add_many_idempotent` uses `ON CONFLICT DO NOTHING`
- [ ] 11+ tests passing
- [ ] No raw SQL injection risks (use bound parameters)

---

#### T-B-2-04: Update Unit of Work for Dual Session Factories

**Type**: impl
**depends_on**: [T-B-2-01, T-B-2-03]
**blocks**: [T-B-3-01, T-B-3-02]
**Target files**:
- `services/content-ingestion/src/content_ingestion/infrastructure/db/unit_of_work.py` (create if needed)
- `services/content-ingestion/src/content_ingestion/application/ports/unit_of_work.py` (create if needed)

**What to build**:
Create a `UnitOfWork` port (ABC) and `SqlaUnitOfWork` adapter that manage write/read
sessions and expose repositories. This replaces direct session passing in routes/use cases.

**Entities / Components**:
- **Name**: `UnitOfWork` (port, ABC)
- **Purpose**: Abstract transaction boundary for use cases
- **Key properties**:
  - `tasks: TaskRepository` — Task repository (write session)
  - `sources: SourceRepository` — Source repository (read session for queries, write for mutations)
  - `fetch_logs: FetchLogRepository` — Fetch log repository (write session)
  - `outbox: OutboxRepository` — Outbox repository (write session)
  - `adapter_state: AdapterStateRepository` — Adapter state (write session)
- **Key methods**:
  - `async __aenter__() -> Self`
  - `async __aexit__() -> None`
  - `async commit() -> None`
  - `async rollback() -> None`

- **Name**: `SqlaUnitOfWork` (adapter)
- **Purpose**: SQLAlchemy implementation of UnitOfWork with dual sessions
- **Constructor**: `__init__(write_factory, read_factory=None)`
- **Behavior**:
  - `__aenter__`: Creates write session, optionally read session
  - `__aexit__`: Rolls back on exception, closes sessions
  - All mutating repos use write session
  - Pure-read repos use read session (falls back to write if no read factory)

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_uow_commit | commit() persists changes | unit |
| test_uow_rollback_on_exception | Exception in context triggers rollback | unit |
| test_uow_exposes_repositories | All 5 repos accessible as properties | unit |
| test_uow_read_fallback | When read_factory is None, uses write_factory | unit |

**Acceptance criteria**:
- [ ] `UnitOfWork` ABC in `application/ports/unit_of_work.py`
- [ ] `SqlaUnitOfWork` in `infrastructure/db/unit_of_work.py`
- [ ] All 5 repository properties exposed
- [ ] Dual session support with fallback
- [ ] 4+ tests passing

---

#### T-B-2-05: Update API Dependencies for Dual Sessions

**Type**: impl
**depends_on**: [T-B-2-01]
**blocks**: [T-B-4-01]
**Target files**: `services/content-ingestion/src/content_ingestion/api/dependencies.py`

**What to build**:
Update the FastAPI dependency injection to use the dual session factory. API routes use
the write session (short-lived CRUD operations don't benefit from read/write split).
Store both factories on `app.state` during lifespan.

**Logic & Behavior**:
- `get_db_session()` continues to yield a write session (API routes do CRUD)
- Add `get_read_session()` dependency for future read-only endpoints
- Store `app.state.write_factory` and `app.state.read_factory` in lifespan
- Keep backward-compatible `app.state.session_factory` as alias to `write_factory`

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_get_db_session_yields_session | Dependency yields a valid AsyncSession | unit |
| test_get_read_session_yields_session | Read dependency yields from read factory | unit |

**Acceptance criteria**:
- [ ] `get_db_session()` uses write factory
- [ ] `get_read_session()` uses read factory (new dependency)
- [ ] `app.state.session_factory` alias preserved for backward compat
- [ ] 2+ tests passing

---

#### Pre-read (agent must read before starting)
- `services/content-ingestion/src/content_ingestion/infrastructure/db/session.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/db/models.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/`
- `services/content-ingestion/src/content_ingestion/api/dependencies.py`
- `services/content-ingestion/alembic/`
- `services/market-ingestion/src/market_ingestion/infrastructure/db/session.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/db/unit_of_work.py`

#### Validation Gate
- [x] ruff check passes on changed files
- [x] mypy passes on `content_ingestion`
- [x] Unit tests pass — 341 total (23 new from B-2 tasks)
- [x] Alembic migration generates clean DDL
- [x] No cross-service DB access

#### Regression Guardrails
- BP-006: Alembic migration must NOT hardcode localhost URL
- BP-007: Unique partial index handles NULL correctly
- BP-012: expire_on_commit=False prevents expired-row access in async
- BP-019: Migration DDL must match ORM model exactly
- BP-021: No column named `metadata` (SQLAlchemy collision)

---

### Wave B-3: Application — Use Cases, Scheduler Process, Worker Process ✅

**Goal**: Create the use cases for task scheduling and execution, plus standalone scheduler and worker processes with signal handling and entry points.
**Depends on**: Wave B-2
**Estimated effort**: 60-90 minutes
**Architecture layer**: application + infrastructure (processes)
**Status**: **DONE** — 2026-03-30 · 25 new tests (366 total unit) · ruff + mypy clean

#### Tasks

---

#### T-B-3-01: Implement ScheduleDueSourcesUseCase + SchedulerProcess

**Type**: impl
**depends_on**: [T-B-2-03, T-B-2-04]
**blocks**: [T-B-4-01]
**Target files**:
- `services/content-ingestion/src/content_ingestion/application/use_cases/schedule_sources.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/scheduler/scheduler_process.py`

**What to build**:
Create the use case that evaluates which sources are due for fetching and inserts task rows,
plus the standalone `SchedulerProcess` class with tick-based loop and signal handling.

**Entities / Components**:

- **Name**: `ScheduleDueSourcesUseCase`
- **Purpose**: Evaluate enabled sources, check watermarks, create tasks for due sources
- **Constructor**: `__init__(uow: UnitOfWork, max_tasks_per_tick: int = 100)`
- **Key methods**:
  - `execute() -> SchedulerTickResult`
- **Logic**:
  1. Open UoW
  2. Load all enabled sources (via `uow.sources.list_enabled()`)
  3. For each source:
     a. Check if source has an active task (`uow.tasks.has_active_task(source.id)`) — skip if yes
     b. Read watermark from `uow.adapter_state.get(source.id)` — determine if source is due based on interval
     c. Create `ContentIngestionTask.create_for_source(source, window_start=now)`
  4. Bulk insert tasks idempotently (`uow.tasks.add_many_idempotent(tasks)`)
  5. Commit
  6. Return `SchedulerTickResult(tasks_enqueued, sources_evaluated)`
- **Idempotency**: `ON CONFLICT (source_id, window_start) DO NOTHING` — safe for multiple scheduler instances

- **Name**: `SchedulerProcess`
- **Purpose**: Standalone process that calls ScheduleDueSourcesUseCase on a tick interval
- **Pattern**: Mirrors `services/market-ingestion/infrastructure/schedulers/scheduler.py` exactly
- **Constructor**: `__init__(settings: Settings, tick_interval_seconds: float | None = None, max_tasks_per_tick: int = 100)`
- **Key methods**:
  - `run() -> None` — Loop: tick → sleep → repeat until stop_event
  - `stop() -> None` — Set stop_event
  - `_tick() -> None` — Create UoW, call use case, log result
- **Entry point**: `_run_scheduler()` async function + `main()` sync wrapper + `if __name__ == "__main__"`
- **Signal handling**: `SIGINT` and `SIGTERM` → `process.stop()`

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_schedule_no_sources | Returns 0 tasks when no enabled sources | unit |
| test_schedule_creates_tasks | Creates tasks for due sources | unit |
| test_schedule_skips_active_task | Skips source with existing active task | unit |
| test_schedule_skips_not_due | Skips source that was recently fetched | unit |
| test_schedule_idempotent | Second call with same window creates no duplicates | unit |
| test_scheduler_process_tick | _tick() calls use case and logs | unit |
| test_scheduler_process_stop | stop() causes run() to exit | unit |

- Minimum test count: 7

**Acceptance criteria**:
- [ ] `ScheduleDueSourcesUseCase` in `application/use_cases/schedule_sources.py`
- [ ] `SchedulerProcess` in `infrastructure/scheduler/scheduler_process.py`
- [ ] Entry point: `python -m content_ingestion.infrastructure.scheduler.scheduler_process`
- [ ] Signal handling for SIGINT/SIGTERM
- [ ] Idempotent task creation via ON CONFLICT
- [ ] 7+ tests passing

---

#### T-B-3-02: Implement ClaimTasksUseCase

**Type**: impl
**depends_on**: [T-B-2-03, T-B-2-04]
**blocks**: [T-B-3-04]
**Target files**: `services/content-ingestion/src/content_ingestion/application/use_cases/claim_tasks.py`

**What to build**:
Create the use case that atomically claims a batch of tasks for a worker.
Mirrors `services/market-ingestion/application/use_cases/claim_tasks.py`.

**Entities / Components**:
- **Name**: `ClaimTasksUseCase`
- **Purpose**: Claim PENDING/RETRY tasks atomically for a worker
- **Constructor**: `__init__(uow: UnitOfWork)`
- **Key methods**:
  - `execute(worker_id: str, batch_size: int, lease_seconds: int = 300) -> list[ContentIngestionTask]`
- **Logic**:
  1. Open UoW
  2. Call `uow.tasks.claim_batch(worker_id, batch_size, lease_seconds)`
  3. Commit
  4. Return claimed tasks
  5. Log: `tasks_claimed(worker_id, count, requested)`

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_claim_returns_tasks | Claims available tasks | unit |
| test_claim_empty_queue | Returns empty list when no tasks | unit |
| test_claim_commits | UoW.commit() called after claim | unit |

- Minimum test count: 3

**Acceptance criteria**:
- [ ] `ClaimTasksUseCase` in `application/use_cases/claim_tasks.py`
- [ ] Delegates to `TaskRepository.claim_batch()`
- [ ] Commits after claiming
- [ ] 3+ tests passing

---

#### T-B-3-03: Implement ExecuteContentTaskUseCase

**Type**: impl
**depends_on**: [T-B-2-03, T-B-2-04]
**blocks**: [T-B-3-04]
**Target files**: `services/content-ingestion/src/content_ingestion/application/use_cases/execute_task.py`

**What to build**:
Refactor the logic from `_run_fetch_cycle()` in `app.py` into a proper use case.
This is the core fetch-and-write pipeline that the worker executes per task.

**Entities / Components**:
- **Name**: `ExecuteContentTaskUseCase`
- **Purpose**: Execute one content ingestion task: fetch from source API → write to MinIO → write to DB + outbox
- **Constructor**:
  ```python
  __init__(
      uow: UnitOfWork,
      http_client: httpx.AsyncClient,
      storage: ObjectStorage,
      valkey: ValkeyClient,
      settings: Settings,
  )
  ```
- **Key methods**:
  - `execute(task: ContentIngestionTask) -> FetchSummary`
- **Logic** (refactored from `_run_fetch_cycle`):
  1. Mark task RUNNING: `task.start()` + `uow.tasks.update_status()`
  2. Commit status update (release session)
  3. Read watermark (read session via separate UoW) — BP-016: no session held during step 4
  4. Build adapter + fetch from external API (no session held — session optimization)
  5. If no results: mark SUCCEEDED, return
  6. Write results (new write UoW):
     a. Advisory lock (`pg_advisory_lock(session, f"s4:fetch:{source_name}")`)
     b. `FetchAndWriteUseCase.execute()` (existing logic, unchanged)
     c. Update watermark
     d. Commit
  7. Mark task SUCCEEDED (or RETRY/FAILED on error)

**Important**: The existing `FetchAndWriteUseCase` (batch commits, MinIO GC) is **reused unchanged**.
This new use case wraps it with task lifecycle management.

**Error handling**:
- Any exception during fetch or write: `task.fail(str(error))`
- Retryable errors (network, timeout): task → RETRY (if attempts remain)
- Fatal errors (config, auth): task → FAILED immediately (set attempt_count = max_attempts)

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_execute_happy_path | Task transitions RUNNING → SUCCEEDED, returns FetchSummary | unit |
| test_execute_no_results | Task SUCCEEDED when adapter returns empty | unit |
| test_execute_fetch_error_retry | Network error → task RETRY | unit |
| test_execute_fetch_error_fatal | Auth error → task FAILED | unit |
| test_execute_releases_session_during_fetch | No session held during HTTP call (verify UoW exit before fetch) | unit |
| test_execute_updates_watermark | Watermark updated after successful write | unit |

- Minimum test count: 6
- Edge cases: adapter returns partial results (some succeed, some fail)

**Acceptance criteria**:
- [ ] `ExecuteContentTaskUseCase` in `application/use_cases/execute_task.py`
- [ ] Reuses existing `FetchAndWriteUseCase` (no duplication)
- [ ] Session optimization: no session held during external API calls (R24)
- [ ] Task state transitions: RUNNING → SUCCEEDED/RETRY/FAILED
- [ ] 6+ tests passing

---

#### T-B-3-04: Implement WorkerProcess + Entry Point

**Type**: impl
**depends_on**: [T-B-3-02, T-B-3-03, T-B-2-01]
**blocks**: [T-B-4-01]
**Target files**: `services/content-ingestion/src/content_ingestion/infrastructure/workers/worker.py`

**What to build**:
Implement the standalone `WorkerProcess` class with claim-execute loop, semaphore-gated
concurrency, and signal handling. Mirrors `services/market-ingestion/infrastructure/workers/worker.py`.

**Entities / Components**:
- **Name**: `WorkerProcess`
- **Purpose**: Long-running process that claims and executes content ingestion tasks
- **Constructor**:
  ```python
  __init__(
      settings: Settings,
      worker_id: str | None = None,  # ULID auto-generated
      batch_size: int | None = None,
      lease_seconds: int | None = None,
      idle_sleep_seconds: float | None = None,
  )
  ```
- **Key methods**:
  - `run() -> None` — Main loop: claim → execute → sleep if idle → repeat
  - `stop() -> None` — Set stop_event for graceful shutdown
  - `_claim_batch() -> list[ContentIngestionTask]` — ClaimTasksUseCase
  - `_execute_with_semaphore(task) -> None` — Acquire semaphore, execute with timeout
  - `_execute_task(task) -> None` — ExecuteContentTaskUseCase
- **Concurrency**: `asyncio.Semaphore(worker_concurrency)` — default 2
- **Task timeout**: `asyncio.timeout(worker_task_timeout_seconds)` — default 120s
- **Back-pressure**: Sleep `idle_sleep_seconds` (5s) when no tasks claimed
- **Infrastructure**: Builds own session factories, HTTP client, storage, valkey (like market-ingestion worker)
- **Entry point**: `_run_worker()` + `main()` + `if __name__ == "__main__"`
- **Signal handling**: SIGINT/SIGTERM → `process.stop()`

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_worker_stop | stop() causes run() to exit cleanly | unit |
| test_worker_claim_empty | Worker sleeps when no tasks available | unit |
| test_worker_execute_task | Worker claims and executes a task | unit |
| test_worker_semaphore_timeout | Logs warning when semaphore acquisition times out | unit |
| test_worker_claim_error | Worker handles claim errors gracefully | unit |

- Minimum test count: 5

**Acceptance criteria**:
- [ ] `WorkerProcess` in `infrastructure/workers/worker.py`
- [ ] Entry point: `python -m content_ingestion.infrastructure.workers.worker`
- [ ] Semaphore-gated concurrency (default 2)
- [ ] Task timeout (120s default)
- [ ] Signal handling SIGINT/SIGTERM
- [ ] Back-pressure on empty queue (5s sleep)
- [ ] Own session factories (not shared with API process)
- [ ] 5+ tests passing

---

#### Pre-read (agent must read before starting)
- `services/content-ingestion/src/content_ingestion/app.py` (the `_run_fetch_cycle` to refactor)
- `services/content-ingestion/src/content_ingestion/application/use_cases/fetch_and_write.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/scheduler/scheduler.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/schedulers/scheduler.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/workers/worker.py`
- `services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py`
- `services/market-ingestion/src/market_ingestion/application/use_cases/claim_tasks.py`

#### Validation Gate
- [x] ruff check passes on changed files
- [x] mypy passes on `content_ingestion`
- [x] Unit tests pass — 25 new tests (366 total, exceeds 21 minimum)
- [x] Entry points work: `python -m content_ingestion.infrastructure.scheduler.scheduler_process` imports cleanly
- [x] Entry points work: `python -m content_ingestion.infrastructure.workers.worker` imports cleanly
- [x] No architecture violations (schedule_sources + claim_tasks import domain only, not infrastructure)

#### Regression Guardrails
- BP-016: ExecuteContentTaskUseCase MUST NOT hold session during external API calls ✅
- BP-015: Advisory lock hash uses `hashlib.sha256`, not Python `hash()` ✅ (uses string key)
- BP-001: Outbox serialization uses OutboxEventValueSerializer ✅ (reuses FetchAndWriteUseCase)
- BP-035: Task claiming uses SELECT FOR UPDATE SKIP LOCKED (not SELECT then UPDATE) ✅ (via ClaimTasksUseCase → TaskRepository)

---

### Wave B-4: API Cleanup, Dispatcher Extraction, Docker Compose

**Goal**: Remove scheduler and dispatcher from the API process lifespan, update trigger endpoint, verify standalone dispatcher, add Docker Compose service definitions, update documentation.
**Depends on**: Wave B-3
**Estimated effort**: 45-60 minutes
**Architecture layer**: API + infrastructure + config + docs

#### Tasks

---

#### T-B-4-01: Refactor app.py Lifespan — Remove Scheduler + Dispatcher

**Type**: impl
**depends_on**: [T-B-3-01, T-B-3-04]
**blocks**: [T-B-4-02, T-B-4-04]
**Target files**: `services/content-ingestion/src/content_ingestion/app.py`

**What to build**:
Strip the scheduler and dispatcher from the API process lifespan. The API process should
only set up: logging, tracing, DB factories, Valkey, MinIO, HTTP client, metrics poller,
middleware, and routes. No background processing.

**Changes**:
- **Remove** from lifespan:
  - `IngestionScheduler` instantiation and `scheduler.start()`
  - `ContentIngestionOutboxDispatcher` instantiation
  - `_supervised_dispatcher()` task
  - `_run_fetch_cycle()` function (moved to worker)
  - `run_fn` callback and `app.state.trigger_fn`
  - `app.state.scheduler` and `app.state.dispatcher`
- **Keep** in lifespan:
  - Logging + tracing setup
  - DB dual session factories (`_build_factories`)
  - Valkey, MinIO, HTTP client
  - Metrics poller (lightweight, OK in API process)
  - All middleware (RequestIdMiddleware, Prometheus, OTel)
  - All routes
  - Exception handlers
- **Store on app.state**:
  - `app.state.write_factory` and `app.state.read_factory`
  - `app.state.session_factory` as alias for write_factory (backward compat)
- **Shutdown**: Remove scheduler.stop(), dispatcher task cancel

**Important**: Keep `_run_fetch_cycle()` in the codebase temporarily (or delete if fully
replaced by `ExecuteContentTaskUseCase`). The admin `/trigger` endpoint will be updated
in T-B-4-02 to create a task row instead.

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_lifespan_no_scheduler | app.state has no scheduler attribute | unit |
| test_lifespan_no_dispatcher | app.state has no dispatcher attribute | unit |
| test_lifespan_has_dual_factories | app.state.write_factory and read_factory exist | unit |

**Acceptance criteria**:
- [ ] Scheduler code removed from lifespan
- [ ] Dispatcher code removed from lifespan
- [ ] API starts cleanly without scheduler/dispatcher
- [ ] Dual session factories stored on app.state
- [ ] Metrics poller still runs
- [ ] All existing API tests still pass
- [ ] 3+ new tests

---

#### T-B-4-02: Update POST /trigger to Create Task Row

**Type**: impl
**depends_on**: [T-B-4-01, T-B-2-03]
**blocks**: none
**Target files**: `services/content-ingestion/src/content_ingestion/api/routes/admin.py`

**What to build**:
Update the `POST /api/v1/sources/{id}/trigger` endpoint to create a task row in the
database instead of calling the scheduler directly. Workers will pick up the task.

**Current behavior**:
```python
scheduler = getattr(request.app.state, "scheduler", None)
if scheduler:
    asyncio.create_task(run_fn(source))  # fire-and-forget
```

**New behavior**:
```python
session = ...  # from DbSessionDep
task = ContentIngestionTask.create_for_source(source, window_start=utc_now())
task_repo = TaskRepository(session)
await task_repo.add(task)
await session.commit()
return {"task_id": str(task.id), "status": "queued"}
```

**Also update**: `POST /api/v1/sources` — remove hot-add to scheduler.
**Also update**: `PUT /api/v1/sources/{id}` — remove hot-add/remove from scheduler.

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_trigger_creates_task | POST /trigger creates ContentIngestionTask in DB | unit |
| test_trigger_returns_task_id | Response includes task_id and status=queued | unit |
| test_create_source_no_scheduler | POST /sources no longer references scheduler | unit |

**Acceptance criteria**:
- [ ] `/trigger` creates task row (not fire-and-forget)
- [ ] Response includes `task_id`
- [ ] No references to `app.state.scheduler` in admin routes
- [ ] 3+ tests passing

---

#### T-B-4-03: Verify + Harden Standalone Dispatcher

**Type**: impl
**depends_on**: [T-B-2-01]
**blocks**: [T-B-4-04]
**Target files**: `services/content-ingestion/src/content_ingestion/infrastructure/messaging/outbox/dispatcher_main.py`

**What to build**:
Verify that `dispatcher_main.py` works as a fully standalone process with dual session
factories, proper pool sizing, and signal handling. Update to use `_build_factories()`.

**Changes**:
- Use `_build_factories(settings)` instead of `create_session_factory(settings)`
- Pass write_factory to dispatcher (dispatcher only needs write — it reads + updates outbox in same transaction)
- Add signal handling (SIGINT/SIGTERM) if not already present
- Add structlog logging for startup/shutdown
- Configure smaller pool size for dispatcher (pool_size=3, max_overflow=5)

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_dispatcher_main_imports | Module imports without error | unit |
| test_dispatcher_uses_write_factory | Dispatcher receives write session factory | unit |

**Acceptance criteria**:
- [ ] `dispatcher_main.py` runs standalone: `python -m content_ingestion.infrastructure.messaging.outbox.dispatcher_main`
- [ ] Uses `_build_factories()` for session management
- [ ] Signal handling for graceful shutdown
- [ ] 2+ tests

---

#### T-B-4-04: Docker Compose Service Definitions

**Type**: config
**depends_on**: [T-B-4-01, T-B-4-03]
**blocks**: [T-B-4-05]
**Target files**: `infra/compose/docker-compose.yml`

**What to build**:
Add Docker Compose service definitions for the 4 content-ingestion processes: API, Scheduler,
Worker, Dispatcher. Same Dockerfile, different `command` overrides.

**Services to add**:

```yaml
content-ingestion:
  # API server
  command: ["uvicorn", "content_ingestion.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
  ports: ["8004:8000"]
  healthcheck: /healthz
  depends_on: [postgres, kafka, schema-registry, minio, valkey]

content-ingestion-scheduler:
  command: ["python", "-m", "content_ingestion.infrastructure.scheduler.scheduler_process"]
  depends_on: [content-ingestion]  # wait for API health (ensures DB migration ran)
  restart: unless-stopped
  # No ports — headless process

content-ingestion-worker:
  command: ["python", "-m", "content_ingestion.infrastructure.workers.worker"]
  depends_on: [content-ingestion, minio]
  restart: unless-stopped
  # No ports — headless process
  # Scale: docker compose up --scale content-ingestion-worker=3

content-ingestion-dispatcher:
  command: ["python", "-m", "content_ingestion.infrastructure.messaging.outbox.dispatcher_main"]
  depends_on: [content-ingestion, kafka]
  restart: on-failure
  # No ports — headless process
```

**All 4 services share**: same Dockerfile, same env_file, same image. Only `command` differs.

**Downstream test impact**:
- Existing E2E tests may need to start additional containers
- Integration test docker-compose.test.yml may need updating

**Acceptance criteria**:
- [ ] 4 service definitions in docker-compose.yml
- [ ] Same Dockerfile/image, different commands
- [ ] Correct depends_on chain
- [ ] Health check on API only
- [ ] Headless processes (no ports) for scheduler/worker/dispatcher

---

#### T-B-4-05: Update Documentation + .claude-context.md

**Type**: docs
**depends_on**: [T-B-4-04]
**blocks**: none
**Target files**:
- `services/content-ingestion/.claude-context.md`
- `docs/services/content-ingestion.md`
- `docs/MASTER_PLAN.md` (architecture section)

**What to build**:
Update all documentation to reflect the new 4-process architecture.

**Changes**:
- `.claude-context.md`: Update process topology, entry points, configuration, pitfalls
- `content-ingestion.md`: Update architecture diagram, process descriptions, scaling guidance
- `MASTER_PLAN.md`: Update S4 section to reflect scheduler-worker pattern

**Acceptance criteria**:
- [ ] .claude-context.md reflects 4 separate processes
- [ ] Service doc describes scheduler-worker pattern
- [ ] MASTER_PLAN.md updated
- [ ] Entry points documented

---

#### Pre-read (agent must read before starting)
- `services/content-ingestion/src/content_ingestion/app.py` (full file)
- `services/content-ingestion/src/content_ingestion/api/routes/admin.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/messaging/outbox/dispatcher_main.py`
- `services/content-ingestion/.claude-context.md`
- `docs/services/content-ingestion.md`
- `infra/compose/docker-compose.yml`

#### Validation Gate
- [ ] ruff check passes on changed files
- [ ] mypy passes on `content_ingestion`
- [ ] All existing unit + integration tests pass (no regressions)
- [ ] New tests pass — minimum 8 new
- [ ] API starts without scheduler/dispatcher
- [ ] Documentation updated

#### Regression Guardrails
- BP-002: Docker Compose env_file path must be correct
- BP-006: No hardcoded localhost in Alembic or compose
- BP-010: Headless processes need health checks via different mechanism (TCP or file-based, not HTTP)

---

## 6. Cross-Cutting Concerns

### Contract Changes
- **None** — No Avro schema or API contract changes. The task table is internal to content-ingestion.

### Migration Needs
- **content-ingestion**: One new Alembic migration (`content_ingestion_tasks` table) in Wave B-2.

### Event Flow Changes
- **None** — The outbox topic (`content.article.raw.v1`) and event structure are unchanged.
  The dispatcher is extracted to a separate process but publishes the same events.

### Configuration Changes
New env vars (all prefixed `CONTENT_INGESTION_`):
- `CONTENT_INGESTION_DB_URL_READ` — Read replica URL (optional)
- `CONTENT_INGESTION_SCHEDULER_TICK_INTERVAL_SECONDS` — Default 60
- `CONTENT_INGESTION_SCHEDULER_MAX_TASKS_PER_TICK` — Default 100
- `CONTENT_INGESTION_WORKER_BATCH_SIZE` — Default 5
- `CONTENT_INGESTION_WORKER_LEASE_SECONDS` — Default 300
- `CONTENT_INGESTION_WORKER_IDLE_SLEEP_SECONDS` — Default 5.0
- `CONTENT_INGESTION_WORKER_CONCURRENCY` — Default 2
- `CONTENT_INGESTION_WORKER_TASK_TIMEOUT_SECONDS` — Default 120

### Documentation Updates
- `RULES.md`: R22, R23, R24
- `docs/STANDARDS.md`: §14, §15, §16
- `docs/BUG_PATTERNS.md`: BP-045
- `services/content-ingestion/.claude-context.md`
- `docs/services/content-ingestion.md`
- `docs/MASTER_PLAN.md`

---

## 7. Risk Assessment

### Critical Path
```
A-1 (standards) → B-1 (domain) → B-2 (infra) → B-3 (processes) → B-4 (cleanup)
```
Everything is sequential. Wave B-2 (migration + repository) is the foundation that
everything else depends on.

### Highest Risk
**Wave B-3** — Refactoring `_run_fetch_cycle()` into `ExecuteContentTaskUseCase` while
maintaining all existing behavior (MinIO GC, advisory locks, watermarks, batch commits).
Mitigation: Reuse `FetchAndWriteUseCase` unchanged; only wrap it with task lifecycle.

### Rollback Strategy
- Each wave is independently committable
- If B-2 migration causes issues: `alembic downgrade -1` drops the new table
- If B-4 breaks the API: revert app.py to include scheduler/dispatcher (git revert)
- The old code paths can coexist during transition

### Testing Gaps
- **Concurrent workers**: Integration tests should verify that two workers don't claim
  the same task. This requires a real PostgreSQL instance (not SQLite).
- **Process lifecycle**: Testing signal handling requires spawning subprocesses.
  Recommend testing the classes directly (unit tests) rather than process integration.

---

## 8. Future Work (Out of Scope)

| Item | Description | Suggested Plan |
|------|-------------|---------------|
| Cross-service read/write split | Apply R23 to portfolio, market-data, content-store, NLP, KG, alert | PLAN-0007 |
| PgBouncer deployment | Add PgBouncer to Docker Compose for production readiness | PLAN-0008 |
| Horizontal scheduler scaling | Run N scheduler instances with advisory lock leader election | Enhancement to this plan |
| Process health monitoring | Health endpoints for headless processes (scheduler/worker/dispatcher) | Enhancement |
| Lease expiry recovery | Cron job to reset expired leases (CLAIMED → RETRY) | Enhancement |

---

## 9. Task Tracking

| Task ID | Title | Wave | Status | Notes |
|---------|-------|------|--------|-------|
| T-A-1-01 | Add process architecture rules to RULES.md | A-1 | done | |
| T-A-1-02 | Add process topology & DB patterns to STANDARDS.md | A-1 | done | |
| T-A-1-03 | Add session-held-across-IO bug pattern | A-1 | done | |
| T-B-1-01 | Add IngestionTaskStatus enum | B-1 | done | 7 tests in contracts |
| T-B-1-02 | Add ContentIngestionTask entity | B-1 | done | 23 unit tests |
| T-B-1-03 | Add scheduler/worker config to Settings | B-1 | done | 3 unit tests |
| T-B-2-01 | Implement read/write dual session factory | B-2 | done | |
| T-B-2-02 | Alembic migration + ORM model for tasks | B-2 | done | |
| T-B-2-03 | Implement TaskRepository with claim_batch | B-2 | done | |
| T-B-2-04 | Update Unit of Work for dual sessions | B-2 | done | |
| T-B-2-05 | Update API dependencies for dual sessions | B-2 | done | |
| T-B-3-01 | ScheduleDueSourcesUseCase + SchedulerProcess | B-3 | done | 8 use case + 3 process tests |
| T-B-3-02 | ClaimTasksUseCase | B-3 | done | 3 tests |
| T-B-3-03 | ExecuteContentTaskUseCase | B-3 | done | 6 tests |
| T-B-3-04 | WorkerProcess + entry point | B-3 | done | 5 tests |
| T-B-4-01 | Refactor app.py lifespan | B-4 | pending | |
| T-B-4-02 | Update POST /trigger to create task | B-4 | pending | |
| T-B-4-03 | Verify + harden standalone dispatcher | B-4 | pending | |
| T-B-4-04 | Docker Compose service definitions | B-4 | pending | |
| T-B-4-05 | Update documentation | B-4 | pending | |
