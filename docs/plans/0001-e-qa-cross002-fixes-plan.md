---
id: PLAN-0001-E
prd: QA Review (QA-CROSS-002)
title: "S1+S2+S3 Deep QA Fixes: Idempotency, Atomicity, Security Hardening, Architecture Consistency"
status: in-progress
created: 2026-03-27
updated: 2026-03-28
plans: 4
<!-- Wave E1-4 completed 2026-03-27 -->
<!-- Waves E2-1 + E2-2 completed 2026-03-27 -->
<!-- Wave E2-3 completed 2026-03-28 -->
<!-- Waves E3-1 + E3-2 completed 2026-03-28 -->
<!-- Waves E3-3 + E3-4 completed 2026-03-28 -->
waves: 14
tasks: 62
supersedes: QA-CROSS-002
---

# PLAN-0001-E: Deep QA Fixes (S1 + S2 + S3)

## Overview

**Triggered by**: QA-CROSS-002 multi-agent deep review (2026-03-27) — 87 findings across portfolio (S1), market-ingestion (S2), market-data (S3).
**Goal**: Fix all BLOCKING, CRITICAL, and MAJOR issues identified in the deep QA pass. Covers idempotency gaps, distributed-system atomicity failures, security hardening, architecture consistency, and test coverage.
**Total Scope**: 4 sub-plans, 14 waves, 62 tasks

---

## Decisions Made

The following design decisions are made here so `/implement` waves need no additional decisions:

| ID | Question | Decision | Rationale |
|----|----------|----------|-----------|
| D-001 | Tenant endpoints auth | Make `POST /tenants` and `GET /tenants/{id}` internal-only with `X-Internal-Token` header (same pattern as `/internal/v1/` endpoints) | Consistent with existing portfolio internal endpoint pattern; S9 gateway is the only legitimate tenant creator |
| D-002 | `result_ref`/`completed_at` persistence | Add `result_ref_bucket`, `result_ref_key`, `result_ref_sha256`, `result_ref_mime_type`, `completed_at` columns to `ingestion_tasks` DB model + migration | Needed for observability, debugging, and resume-from-checkpoint semantics |
| D-003 | Portfolio Avro schema format | Flatten to top-level fields (matching market services pattern) — remove `payload: string` wrapper | Enables field-level schema evolution and Avro compatibility checking; aligns with all other services |
| D-004 | Quote NULL vs zero | Use `Decimal | None` in `Quote` domain entity for bid/ask/last; add `volume: int | None` | Preserves data fidelity: NULL = "no data", 0 = "zero trading activity" |
| D-005 | Internal events (IngestionTaskCompleted, IngestionTaskScheduled) | Route to in-memory event bus only — do NOT add to outbox | Internal state transitions, not cross-service events; adding Avro schemas adds friction with no benefit |
| D-006 | Polygon/AlphaVantage stubs | Remove from provider registry until implemented | Stub in registry creates confusing error paths; re-add when implementation begins |
| D-007 | Idempotency key parse failure | Fail-fast: return HTTP 422 Unprocessable Entity if `idempotency_key` is present but cannot be parsed as UUID | Clearer contract than silent degradation; clients should always send valid UUIDs |
| D-008 | Orphaned MinIO objects | Check object existence before writing on retry (`object_exists()` before `put_object()`) — no periodic GC job | Simpler than GC; idempotent writes handle retries gracefully |
| D-009 | Event envelope standard | Standardize on **strings** for `event_id` (UUIDv7 hex string) and `occurred_at` (ISO-8601 UTC `Z` suffix) across all services | Avro portability — `string` type is universally supported; avoids Avro `bytes`/`fixed` for UUID |

---

## Sub-Plan Index

| Sub-Plan | Service | Waves | Tasks | Focus |
|----------|---------|-------|-------|-------|
| E-1 | S2 Market-Ingestion | 4 | 18 | Blocking atomicity, result_ref, watermark, serializers, tests |
| E-2 | S3 Market-Data | 3 | 14 | Mark_processed, dedup race, Quote NULL, assert, consistency |
| E-3 | S1 Portfolio | 4 | 20 | Idempotency, Avro schema, tenant auth, security, tests |
| E-4 | Cross-Cutting | 3 | 10 | Config security, docs, architecture consistency |

---

## Dependency Graph

```
E-2 W1 (mark_processed)  ──────────────────────────┐
E-1 W1 (result_ref + atomicity)  ──────────────────→│
E-3 W1 (Avro schema + idempotency) ────────────────→│
E-4 W1 (config security) ──────────────────────────→│
                                                     │
E-1 W2 (ABCs + status alignment) ← E-1 W1          │
E-2 W2 (architecture fixes) ← E-2 W1               │
E-3 W2 (tenant auth + security) ← E-3 W1           │
E-4 W2 (docs) ← E-4 W1                             │
                                                     │
E-1 W3 (data consistency) ← E-1 W2                 │
E-2 W3 (tests) ← E-2 W2                            │
E-3 W3 (major consistency) ← E-3 W2                │
E-4 W3 (context + tracking) ← E-4 W2              │
                                                     │
E-1 W4 (tests) ← E-1 W3                            │
E-3 W4 (architecture) ← E-3 W3                     │
                                                     ▼
                      All waves complete → QA re-run
```

**Critical path**: E-1 W1 → E-1 W2 → E-1 W3 → E-1 W4
**Parallelizable at start**: E-1 W1 ∥ E-2 W1 ∥ E-3 W1 ∥ E-4 W1

---

## Pre-Read (agent must read before any wave)

- `RULES.md` — hard rules (R7, R8, R9, R10, R11)
- `docs/ai-interactions/BUG_PATTERNS.md` — BP-028, BP-034, BP-035, BP-036, BP-037, BP-038, BP-039, BP-040
- `services/<service>/.claude-context.md` for each service being worked on
- `docs/ai-interactions/audits/2026-03-27-deep-cross-service-qa-report.md` — full findings

---

## Sub-Plan E-1: Market-Ingestion (S2) Fixes

### Wave E1-1: BLOCKING — Atomicity + result_ref + Serializers ✅

**Goal**: Fix all BLOCKING issues in market-ingestion: token bucket atomicity, result_ref persistence, watermark commit atomicity, task lease timing, and serializer completeness.
**Depends on**: none
**Estimated effort**: 60–90 minutes
**Status**: **DONE** — 2026-03-27 · 301 unit tests pass · ruff + format clean
**Architecture layer**: domain + infrastructure + application

#### Pre-read
- `services/market-ingestion/src/market_ingestion/domain/entities/provider_budget.py`
- `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/task_repository.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/db/models/ingestion_task.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/messaging/serialization.py`
- `services/market-ingestion/alembic/versions/0001_initial_schema.py`

#### Tasks

##### T-E1-1-01: Add `result_ref` + `completed_at` columns to ingestion_tasks (schema + ORM)

**Type**: schema
**depends_on**: none
**blocks**: [T-E1-1-02]
**Target files**:
- `services/market-ingestion/alembic/versions/0001_initial_schema.py` (add columns)
- `services/market-ingestion/src/market_ingestion/infrastructure/db/models/ingestion_task.py`

**What to build**:
Add 5 columns to the `ingestion_tasks` table and ORM model to persist the result of a successful task execution. These columns are set when `task.succeed(result_ref)` is called.

**DDL additions** (all nullable, forward-compatible):
```sql
result_ref_bucket    TEXT,
result_ref_key       TEXT,
result_ref_sha256    TEXT,
result_ref_mime_type TEXT,
completed_at         TIMESTAMPTZ
```

**ORM additions** (`IngestionTaskModel`):
```python
result_ref_bucket:    Mapped[str | None] = mapped_column(Text, nullable=True)
result_ref_key:       Mapped[str | None] = mapped_column(Text, nullable=True)
result_ref_sha256:    Mapped[str | None] = mapped_column(Text, nullable=True)
result_ref_mime_type: Mapped[str | None] = mapped_column(Text, nullable=True)
completed_at:         Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
```

**Acceptance criteria**:
- [ ] Migration DDL matches ORM model columns
- [ ] All 5 columns are nullable (forward-compatible — existing rows unaffected)
- [ ] ruff + mypy pass

---

##### T-E1-1-02: Wire `result_ref`/`completed_at` through repository `_to_domain` and `save`

**Type**: impl
**depends_on**: [T-E1-1-01]
**blocks**: []
**Target files**:
- `services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/task_repository.py`

**What to build**:
Update `_to_domain()` and `save()` in `SqlAlchemyTaskRepository` to round-trip the new columns.

**`_to_domain()` change**: Populate `result_ref` from the 4 column values when non-null:
```python
result_ref = None
if row.result_ref_bucket and row.result_ref_key:
    result_ref = ObjectRef(
        bucket=row.result_ref_bucket,
        key=row.result_ref_key,
        sha256=row.result_ref_sha256 or "",
        mime_type=row.result_ref_mime_type or "",
    )
```

**`save()` change**: Add the 5 new columns to the UPDATE statement:
```python
result_ref_bucket=task.result_ref.bucket if task.result_ref else None,
result_ref_key=task.result_ref.key if task.result_ref else None,
result_ref_sha256=task.result_ref.sha256 if task.result_ref else None,
result_ref_mime_type=task.result_ref.mime_type if task.result_ref else None,
completed_at=task.completed_at,
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_save_persists_result_ref_on_success` | After `task.succeed(ref)`, repository save + reload returns ref intact | unit |
| `test_save_completed_at_set_on_success` | `completed_at` is UTC-aware datetime after task.succeed() | unit |
| `test_save_result_ref_none_on_pending_task` | Pending task has null result_ref columns | unit |

**Acceptance criteria**:
- [ ] `result_ref` round-trips through DB correctly
- [ ] `completed_at` round-trips as UTC-aware datetime
- [ ] 3 new unit tests pass

---

##### T-E1-1-03: Fix token bucket `try_consume()` — load with SELECT-FOR-UPDATE

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/budget_repository.py`
- `services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py`

**What to build**:
Replace the current load-mutate-save pattern with a SELECT-FOR-UPDATE to prevent concurrent workers from over-consuming the token bucket (BP-036).

**`budget_repository.py` — new method `get_for_update()`**:
```python
async def get_for_update(self, provider: Provider) -> ProviderBudget | None:
    """Load budget row with a row-level lock. Must be called inside an open transaction."""
    stmt = (
        select(ProviderBudgetModel)
        .where(ProviderBudgetModel.provider == provider.value)
        .with_for_update()
    )
    result = await self._session.execute(stmt)
    row = result.scalar_one_or_none()
    return self._to_domain(row) if row else None
```

**`schedule_tasks.py` — replace `uow.budgets.get(provider)` with `uow.budgets.get_for_update(provider)`** inside the transaction context where budget is consumed.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_try_consume_with_lock_prevents_double_consume` | Two concurrent calls with same budget — only one succeeds | unit (mock) |
| `test_get_for_update_called_inside_transaction` | `get_for_update()` invoked within UoW transaction context | unit |

**Acceptance criteria**:
- [ ] `get_for_update()` method added to budget repository
- [ ] `schedule_tasks.py` calls `get_for_update` instead of `get`
- [ ] 2 new unit tests pass

---

##### T-E1-1-04: Fix watermark + task state atomicity in `execute_task.py`

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py`

**What to build**:
Three changes to prevent watermark/task state inconsistency (B-004 root cause, C-005, C-006):

1. **Load watermark with FOR UPDATE** inside the DB transaction: Add `with_for_update=True` parameter to `uow.watermarks.get_or_create(...)` call (or add a `get_for_update()` method to the watermark repo). This prevents two workers from racing on the same watermark row.

2. **Defer lease-clear until post-commit** in `_persist_retry()` and `_persist_fail()`: Currently `task.retry()` clears `lease_owner/expires` which makes the task immediately re-claimable. Move the mutation inside the transaction and ensure commit happens atomically.

3. **Check MinIO object existence before writing** on retry path (D-008 decision): Before `await self._store_bronze(task, fetch_result)`, check `await self._object_store.object_exists(bucket, key)`. If exists and task already has a `result_ref`, skip the store step and use existing ref.

**Logic change for `_persist_retry`**:
```python
async def _persist_retry(self, task: IngestionTask, exc: Exception) -> None:
    task.retry(exc)  # Sets next_attempt_at, increments attempt
    # NOTE: task.lease_owner is NOT cleared here — cleared atomically in commit
    async with self._uow:
        await self._uow.tasks.save(task)
        await self._uow.commit()
    # Post-commit: lease is already cleared inside save() via DB UPDATE
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_persist_retry_clears_lease_atomically` | After retry(), task is re-claimable only after DB commit | unit |
| `test_watermark_select_for_update_on_execution` | Watermark loaded with lock inside transaction | unit |
| `test_object_exists_skips_write_on_retry` | If MinIO object exists, store_bronze not called again | unit |

**Acceptance criteria**:
- [ ] Watermark loaded with FOR UPDATE in execute_task
- [ ] Lease clear is atomic with DB commit
- [ ] Skip-if-exists on MinIO write on retry path
- [ ] 3 new tests pass

---

##### T-E1-1-05: Remove Polygon/AlphaVantage stubs from registry (D-006)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/registry.py` (or equivalent)
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/__init__.py`

**What to build**:
Remove `polygon` and `alpha_vantage` from the provider registry so they cannot be instantiated. They can be re-added when the adapter is implemented. Add a comment noting they are removed until implemented.

If the registry is a dict like `{"polygon": PolygonAdapter, ...}`, remove those entries. Add unit test confirming requesting `Provider.POLYGON` raises `ProviderUnavailable` at the registry level.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_registry_polygon_not_registered` | `registry.get_adapter(Provider.POLYGON)` raises `ProviderUnavailable` | unit |
| `test_registry_alpha_vantage_not_registered` | Same for Alpha Vantage | unit |
| `test_registry_eodhd_still_registered` | EODHD remains available | unit |

**Acceptance criteria**:
- [ ] Polygon and AlphaVantage removed from registry
- [ ] EODHD + Yahoo remain registered
- [ ] 3 new unit tests pass

---

##### T-E1-1-06: Fix `build_market_ingestion_serializers` — remove internal events from outbox (D-005)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-ingestion/src/market_ingestion/infrastructure/messaging/serialization.py`
- `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py` (if IngestionTaskCompleted/Scheduled are currently added to outbox)

**What to build**:
Ensure only `MarketDatasetFetched` is registered in the outbox serializer map (D-005 decision: internal events go to in-memory bus, not outbox).

1. Verify `IngestionTaskCompleted` and `IngestionTaskScheduled` are NOT added to `uow.outbox.add(...)` calls.
2. If they are, remove those outbox calls and replace with in-memory event collection (or simply don't publish them at all if no consumer exists yet).
3. The `build_market_ingestion_serializers()` function already only has `MarketDatasetFetched` — verify this is intentional and add a comment.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_execute_task_only_market_dataset_fetched_in_outbox` | After execute_task.execute(), only MarketDatasetFetched in outbox (not task events) | unit |

**Acceptance criteria**:
- [ ] No `IngestionTaskCompleted`/`IngestionTaskScheduled` events written to outbox
- [ ] Comment documents this decision
- [ ] 1 new unit test pass

#### Validation Gate (Wave E1-1)
- [x] `ruff check services/market-ingestion/` clean
- [x] `ruff format --check services/market-ingestion/` clean
- [x] `python -m pytest services/market-ingestion/tests -m unit -v` — 301 pass (+16 new tests)
- [x] Migration DDL matches ORM for new columns (5 nullable columns added)
- [x] No architecture violations (no domain importing from infrastructure)

#### Regression Guardrails
- BP-019: Verify migration DDL exactly matches ORM model for new columns
- BP-036: Token bucket get_for_update must be called inside an open transaction

---

### Wave E1-2: CRITICAL — Repository ABCs + Outbox Status Alignment ✅

**Goal**: Add repository port ABCs to market-ingestion (hexagonal architecture requirement), align outbox status enum to libs/messaging standard, fix UoW asymmetric session cleanup.
**Depends on**: Wave E1-1
**Estimated effort**: 45–60 minutes
**Status**: **DONE** — 2026-03-27 · 341 unit tests pass · ruff + mypy clean
**Architecture layer**: application + infrastructure

#### Pre-read
- `services/portfolio/src/portfolio/application/ports/repositories.py` (reference ABCs)
- `services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/`
- `services/market-ingestion/src/market_ingestion/infrastructure/db/unit_of_work.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/outbox_repository.py`

#### Tasks

##### T-E1-2-01: Add repository port ABCs (C-011)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-ingestion/src/market_ingestion/application/ports/repositories.py`

**What to build**:
Define abstract port interfaces for all 5 repositories used by market-ingestion: TaskRepository, WatermarkRepository, BudgetRepository, PolicyRepository, OutboxRepository.

Pattern to follow: `services/portfolio/src/portfolio/application/ports/repositories.py`.

Each ABC must declare all methods used by use cases with abstract signatures. Concrete repos inherit from these ABCs.

```python
from abc import ABC, abstractmethod
from uuid import UUID
from market_ingestion.domain.entities.ingestion_task import IngestionTask
from market_ingestion.domain.entities.watermark import Watermark
from market_ingestion.domain.entities.provider_budget import ProviderBudget
from market_ingestion.domain.entities.polling_policy import PollingPolicy
from market_ingestion.domain.enums import Provider

class AbstractTaskRepository(ABC):
    @abstractmethod
    async def get(self, task_id: UUID) -> IngestionTask | None: ...
    @abstractmethod
    async def save(self, task: IngestionTask) -> None: ...
    @abstractmethod
    async def claim_batch(self, limit: int) -> list[IngestionTask]: ...

class AbstractWatermarkRepository(ABC):
    @abstractmethod
    async def get_or_create(self, provider: Provider, symbol: str, ...) -> Watermark: ...
    @abstractmethod
    async def save(self, watermark: Watermark) -> None: ...

# ... similarly for Budget, Policy, Outbox
```

Update each concrete SqlAlchemy*Repository to inherit from its ABC.

**Acceptance criteria**:
- [ ] 5 ABCs defined in `application/ports/repositories.py`
- [ ] All 5 concrete repos inherit from their ABCs
- [ ] mypy strict passes (no type errors from ABC inheritance)
- [ ] All existing tests still pass

---

##### T-E1-2-02: Align outbox status values to libs/messaging standard (C-014)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/outbox_repository.py`
- `services/market-ingestion/alembic/versions/0001_initial_schema.py`

**What to build**:
Market-ingestion outbox likely already uses `"pending"` / `"in_flight"` / `"published"` — verify this is correct and matches `libs/messaging`. If any status value differs (e.g., `"processing"` instead of `"in_flight"`), update it.

For **portfolio** (C-014 is a portfolio issue — but coordinate here to not conflict with E-3 W1):
- This task is for market-ingestion only.
- Verify market-ingestion uses `"pending"` → `"in_flight"` → `"published"` / `"failed"`.
- Add a comment in the repo documenting the status state machine.

**Acceptance criteria**:
- [ ] Market-ingestion outbox uses standard status values from libs/messaging
- [ ] Outbox status state machine documented in code comment
- [ ] All existing tests pass

---

##### T-E1-2-03: Fix UoW `__aexit__` session cleanup (M-008)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-ingestion/src/market_ingestion/infrastructure/db/unit_of_work.py`

**What to build**:
Fix the asymmetric session cleanup in `__aexit__` (BP-037 variant). Ensure `_close_sessions()` always executes even if `rollback()` raises, and that the original exception is preserved:

```python
async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
    try:
        if exc_val is not None:
            await self.rollback()
        else:
            await self.commit()
    except Exception as cleanup_err:
        logger.error("uow_cleanup_error", error=str(cleanup_err), original=repr(exc_val))
    finally:
        await self._close_sessions()
```

Apply the same fix to the read/write session asymmetry: ensure both sessions are closed in `finally`.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_uow_close_sessions_always_called_on_rollback_failure` | `_close_sessions()` runs even if `rollback()` raises | unit |
| `test_uow_original_exception_logged_on_rollback_failure` | Original exception info preserved in log | unit |

**Acceptance criteria**:
- [ ] `_close_sessions()` always runs in `finally`
- [ ] Original exception preserved when rollback fails
- [ ] 2 new unit tests pass

---

##### T-E1-2-04: Fix `EVENT_TOPIC_MAP` fallback in outbox routing (B-005 — market-ingestion side)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/outbox_repository.py`

**What to build**:
Verify market-ingestion outbox does NOT use the dangerous `EVENT_TOPIC_MAP.get(event_type, event_type)` pattern. If it does, replace with explicit raise (BP-039). Confirm topic is stored in outbox rows as a dedicated column, not resolved at read time.

If topic is stored in a dedicated column (correct), add a guard:
```python
if not row.topic:
    raise ValueError(f"Outbox record {row.id} has no topic — cannot dispatch")
```

**Acceptance criteria**:
- [ ] No silent fallback to event_type as topic
- [ ] Guard raises explicitly on missing topic
- [ ] Existing tests pass

#### Validation Gate (Wave E1-2)
- [x] `ruff check services/market-ingestion/` clean
- [x] `mypy services/market-ingestion/src/` clean (2 pre-existing confluent_kafka stubs errors)
- [x] All unit tests pass (341 pass, +6 new tests)

---

### Wave E1-3: MAJOR — Data Consistency + claim_batch Isolation ✅

**Goal**: Fix SELECT-FOR-UPDATE isolation issue in `claim_batch`, fix non-atomic `increment_attempts`, fix Avro `row_count` 0-vs-None, fix watermark `utc_now()` regression risk.
**Depends on**: Wave E1-2
**Estimated effort**: 45–60 minutes
**Status**: **DONE** — 2026-03-27 · 348 unit tests pass · ruff + mypy clean
**Architecture layer**: infrastructure + domain

#### Pre-read
- `services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/task_repository.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/outbox_repository.py`
- `services/market-ingestion/src/market_ingestion/domain/events.py`
- `services/market-ingestion/src/market_ingestion/domain/entities/watermark.py`

#### Tasks

##### T-E1-3-01: Fix `claim_batch` SELECT+UPDATE separation (M-006)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/task_repository.py`

**What to build**:
Replace the two-step SELECT-then-UPDATE with a single atomic `UPDATE ... WHERE ... RETURNING` statement. Use CTE to select candidate IDs and update in one SQL operation:

```sql
WITH candidates AS (
  SELECT id FROM ingestion_tasks
  WHERE status IN ('pending', 'retry')
    AND (locked_until IS NULL OR locked_until < NOW())
  ORDER BY created_at ASC
  LIMIT :limit
  FOR UPDATE SKIP LOCKED
)
UPDATE ingestion_tasks
SET status = 'running', locked_by = :worker_id, locked_until = :expires
WHERE id IN (SELECT id FROM candidates)
RETURNING *
```

In SQLAlchemy:
```python
cte = (
    select(IngestionTaskModel.id)
    .where(...)
    .order_by(IngestionTaskModel.created_at)
    .limit(limit)
    .with_for_update(skip_locked=True)
    .cte("candidates")
)
stmt = (
    update(IngestionTaskModel)
    .where(IngestionTaskModel.id.in_(select(cte.c.id)))
    .values(status="running", locked_by=worker_id, locked_until=expires)
    .returning(IngestionTaskModel)
)
```

**Acceptance criteria**:
- [ ] Single atomic SQL operation (no SELECT then UPDATE gap)
- [ ] All existing claim_batch tests pass with new implementation
- [ ] New test: `test_claim_batch_atomic_no_race_window` (two calls, distinct tasks returned)

---

##### T-E1-3-02: Fix non-atomic `increment_attempts` in outbox (M-011)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/outbox_repository.py`

**What to build**:
Replace the read-modify-write `increment_attempts` with an atomic SQL UPDATE:

```python
async def increment_attempts(self, record_id: UUID) -> None:
    stmt = (
        update(OutboxEventModel)
        .where(OutboxEventModel.id == record_id)
        .values(
            attempt_count=OutboxEventModel.attempt_count + 1,
            status="pending",
        )
    )
    await self._session.execute(stmt)
```

Do the same fix for portfolio's outbox (coordinate with E-3 W1 T-E3-1-05).

**Acceptance criteria**:
- [ ] `increment_attempts` uses `column + 1` SQL expression (atomic)
- [ ] No read-modify-write pattern remains

---

##### T-E1-3-03: Fix `row_count` Avro schema 0-vs-None ambiguity (M-024)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-ingestion/src/market_ingestion/domain/events.py`

**What to build**:
Fix the `to_dict()` method in `MarketDatasetFetched` to correctly serialize `row_count`:
- If `row_count is None` → serialize as `None` (no rows counted)
- If `row_count == 0` → serialize as `0` (zero rows, still valid data)
- Current bug: `"row_count": self.row_count if self.row_count else None` → coerces 0 to None

Fix:
```python
"row_count": self.row_count,  # None stays None, 0 stays 0
```

Update `from_dict()` to handle both `None` and `int` from Avro.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_market_dataset_fetched_row_count_zero_serializes_as_zero` | `row_count=0` → `to_dict()["row_count"] == 0` (not None) | unit |
| `test_market_dataset_fetched_row_count_none_serializes_as_none` | `row_count=None` → `to_dict()["row_count"] is None` | unit |

**Acceptance criteria**:
- [ ] `row_count=0` serializes as `0`
- [ ] `row_count=None` serializes as `None`
- [ ] 2 new tests pass

---

##### T-E1-3-04: Fix watermark regression via `utc_now()` for tasks without `range_end` (M-029)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py`
- `services/market-ingestion/src/market_ingestion/domain/entities/watermark.py`

**What to build**:
Replace `utc_now()` fallback for `range_end` with `task.created_at` to provide a stable, monotonic ordering reference:

```python
# Before (racy):
new_ts = task.range_end if task.range_end is not None else utc_now()

# After (stable):
new_ts = task.range_end if task.range_end is not None else task.created_at
```

This ensures that two concurrent tasks without `range_end` always produce a deterministic ordering via their creation timestamps.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_watermark_uses_created_at_when_range_end_none` | When `range_end=None`, watermark advanced by `task.created_at` | unit |
| `test_watermark_no_regression_out_of_order_tasks` | Earlier-created task with same conditions does not regress watermark | unit |

**Acceptance criteria**:
- [ ] `utc_now()` fallback replaced with `task.created_at`
- [ ] 2 new tests pass

#### Validation Gate (Wave E1-3)
- [x] `ruff check services/market-ingestion/` clean
- [x] `mypy services/market-ingestion/src/` clean
- [x] All unit tests pass (348 pass, +7 new tests)
- [x] Avro `row_count` serialization tests pass

---

### Wave E1-4: Tests — Yahoo Provider + ExecuteTask State-Consistency ✅

**Goal**: Add comprehensive unit tests for Yahoo provider adapter and ExecuteTask state-consistency error paths. Add semaphore acquisition timeout.
**Depends on**: Wave E1-3
**Estimated effort**: 45–60 minutes
**Status**: **DONE** — 2026-03-27 · 365 unit tests pass (+17 new) · ruff + mypy clean
**Architecture layer**: tests

#### Pre-read
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/yahoo.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/eodhd.py` (reference test structure)
- `services/market-ingestion/tests/infrastructure/test_eodhd.py` (reference test patterns)
- `services/market-ingestion/src/market_ingestion/infrastructure/workers/worker.py`
- `services/market-ingestion/tests/application/test_execute_task.py`

#### Tasks

##### T-E1-4-01: Add Yahoo provider adapter unit tests (C-016)

**Type**: test
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-ingestion/tests/infrastructure/test_yahoo.py` (new file)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_yahoo_fetch_ohlcv_success` | Happy path: correct OHLCV bars returned | unit |
| `test_yahoo_fetch_ohlcv_symbol_not_found` | 404 → `ProviderDataNotFound` | unit |
| `test_yahoo_fetch_ohlcv_rate_limited` | 429 → `ProviderRateLimited` | unit |
| `test_yahoo_fetch_ohlcv_server_error` | 500 → `ProviderUnavailable` (retryable) | unit |
| `test_yahoo_fetch_ohlcv_malformed_response` | Missing fields → `ProviderError` | unit |
| `test_yahoo_fetch_quotes_success` | Quote returned with correct fields | unit |
| `test_yahoo_fetch_quotes_missing_price` | None price handled gracefully | unit |
| `test_yahoo_fetch_fundamentals_not_supported` | `ProviderUnavailable("not supported")` | unit |
| `test_yahoo_timeframe_mapping` | `1d` → correct Yahoo API parameter | unit |
| `test_yahoo_date_range_passed_correctly` | start/end dates passed to API | unit |

Minimum: 10 tests using `unittest.mock.patch` for HTTP calls (no real network).

**Acceptance criteria**:
- [x] `tests/infrastructure/test_yahoo.py` created with ≥10 tests
- [x] All tests marked `@pytest.mark.unit`
- [x] All tests pass without network access

---

##### T-E1-4-02: Add ExecuteTask state-consistency error path tests (M-020)

**Type**: test
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-ingestion/tests/application/test_execute_task.py`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_watermark_not_mutated_on_outbox_failure` | If `outbox.add()` fails, watermark `advance_bar_ts` not persisted | unit |
| `test_task_status_reverts_on_commit_failure` | If UoW commit fails, task stays in prior DB status | unit |
| `test_minio_write_skipped_on_retry_if_object_exists` | If bronze object already exists, `store_bronze` not called | unit |
| `test_execute_task_idempotent_on_replay` | Replaying same task returns existing result without re-fetching | unit |

**Acceptance criteria**:
- [x] 4 new tests added to `test_execute_task.py`
- [x] All marked `@pytest.mark.unit`
- [x] All pass

---

##### T-E1-4-03: Add semaphore acquisition timeout to worker (M-033)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-ingestion/src/market_ingestion/infrastructure/workers/worker.py`

**What to build**:
Wrap `async with self._semaphore:` with `asyncio.timeout(60.0)` to prevent indefinite blocking if all permits are held:

```python
async def _execute_with_semaphore(self, task: IngestionTask) -> None:
    try:
        async with asyncio.timeout(60.0):
            async with self._semaphore:
                await self._execute_task(task)
    except TimeoutError:
        logger.warning("worker.semaphore_timeout", task_id=str(task.id))
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_worker_semaphore_timeout_logs_warning` | TimeoutError from semaphore logs warning and continues | unit |
| `test_worker_continues_other_tasks_after_timeout` | One task timeout does not block other tasks | unit |

**Acceptance criteria**:
- [x] 60-second timeout on semaphore acquisition
- [x] Timeout logs `worker.semaphore_timeout` warning
- [x] 2 new tests pass

#### Validation Gate (Wave E1-4)
- [x] `ruff check services/market-ingestion/` clean
- [x] `mypy services/market-ingestion/src/` clean
- [x] All unit tests pass (365 pass, +17 new tests)

---

## Sub-Plan E-2: Market-Data (S3) Fixes

### Wave E2-1: BLOCKING + CRITICAL — mark_processed, dedup race, Quote NULL, assert, ON CONFLICT ✅

**Goal**: Fix all BLOCKING and CRITICAL issues in market-data: content-hash dedup missing mark_processed, dedup check-then-insert race, Quote NULL→zero mapping, assert for production errors, idempotency ON CONFLICT.
**Depends on**: none
**Estimated effort**: 60–75 minutes
**Status**: **DONE** — 2026-03-27 · 271 tests pass · ruff + mypy clean
**Architecture layer**: infrastructure + domain

#### Pre-read
- `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py`
- `services/market-data/src/market_data/infrastructure/messaging/consumers/quotes_consumer.py`
- `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py`
- `services/market-data/src/market_data/infrastructure/db/repositories/quote_repo.py`
- `services/market-data/src/market_data/infrastructure/db/repositories/ingestion_event_repo.py`
- `services/market-data/src/market_data/domain/entities/quote.py`

#### Tasks

##### T-E2-1-01: Fix content-hash dedup early return — add `mark_processed` before return (B-001)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py`
- `services/market-data/src/market_data/infrastructure/messaging/consumers/quotes_consumer.py`
- `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py`

**What to build**:
In all three consumers, find the content-hash dedup early return path and add `await self.mark_processed(event_id)` before the `return` (BP-034):

```python
# Before (broken):
if sha256 and await uow.ingestion_events.exists_by_content_hash(sha256, _DATASET_TYPE):
    logger.debug("consumer.skip_unchanged", sha256_prefix=sha256[:8])
    return  # BUG: event_id never recorded

# After (fixed):
if sha256 and await uow.ingestion_events.exists_by_content_hash(sha256, _DATASET_TYPE):
    logger.debug("consumer.skip_unchanged", sha256_prefix=sha256[:8])
    await self.mark_processed(event_id)  # ← ADD
    return
```

Apply to all 3 consumers identically.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_ohlcv_consumer_content_hash_dedup_marks_processed` | Unchanged content → event_id recorded despite early return | unit |
| `test_quotes_consumer_content_hash_dedup_marks_processed` | Same for quotes consumer | unit |
| `test_fundamentals_consumer_content_hash_dedup_marks_processed` | Same for fundamentals consumer | unit |
| `test_replay_after_content_hash_skip_is_deduped` | Second delivery after hash-dedup skip is correctly deduplicated | unit |

**Acceptance criteria**:
- [ ] All 3 consumers call `mark_processed()` before content-hash early return
- [ ] 4 new tests pass

---

##### T-E2-1-02: Fix consumer dedup check-then-insert race (C-003)

**Type**: impl
**depends_on**: [T-E2-1-01]
**blocks**: []
**Target files**:
- `services/market-data/src/market_data/infrastructure/db/repositories/ingestion_event_repo.py`
- `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py`
- `services/market-data/src/market_data/infrastructure/messaging/consumers/quotes_consumer.py`
- `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py`

**What to build**:
Replace the check-before-insert pattern with insert-and-catch-conflict (BP-035):

In `ingestion_event_repo.py` — modify `create()` to catch unique constraint violations and return a bool indicating whether the insert was new:

```python
async def create_if_not_exists(
    self, event_id: str, event_type: str, content_sha256: str | None = None
) -> bool:
    """Returns True if newly created, False if already existed (duplicate)."""
    stmt = (
        insert(IngestionEventModel)
        .values(event_id=event_id, event_type=event_type, content_sha256=content_sha256)
        .on_conflict_do_nothing(constraint="uq_ingestion_events_event_id")
        .returning(IngestionEventModel.id)
    )
    result = await self._session.execute(stmt)
    return result.scalar_one_or_none() is not None
```

In each consumer's `process_message` — replace `is_duplicate()` check + `mark_processed()` with a single `create_if_not_exists()`:

```python
is_new = await uow.ingestion_events.create_if_not_exists(event_id, _DATASET_TYPE, sha256)
if not is_new:
    logger.debug("consumer.duplicate_event", event_id=event_id[:8])
    return
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_create_if_not_exists_returns_true_on_first_insert` | New event_id → True | unit |
| `test_create_if_not_exists_returns_false_on_duplicate` | Duplicate event_id → False (no raise) | unit |
| `test_consumer_skips_processing_on_duplicate_insert` | Second delivery → early return, no data written | unit |

**Acceptance criteria**:
- [ ] `create_if_not_exists()` replaces `is_duplicate()` + `mark_processed()` in all consumers
- [ ] No race window between check and insert
- [ ] 3 new tests pass

---

##### T-E2-1-03: Fix `Quote` domain entity NULL fields — use `Decimal | None` (C-004 — D-004)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-data/src/market_data/domain/entities/quote.py`
- `services/market-data/src/market_data/infrastructure/db/repositories/quote_repo.py`
- `services/market-data/src/market_data/api/schemas.py` (Quote response schema)

**What to build**:
Change `Quote` domain entity fields to use `Decimal | None` and `int | None`:

```python
@dataclass(frozen=True)
class Quote:
    instrument_id: UUID
    bid: Decimal | None
    ask: Decimal | None
    last: Decimal | None
    volume: int | None
    fetched_at: datetime
```

Update `quote_repo._to_domain()` to pass values as-is (no NULL→zero coercion):
```python
bid=row.bid,  # Not Decimal("0") — leave as None if NULL
ask=row.ask,
last=row.last,
volume=row.volume,
```

Update `QuoteResponse` Pydantic schema to use `Decimal | None` for these fields (nullable in JSON response).

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_quote_repo_null_bid_mapped_to_none` | NULL bid in DB → `None` in domain entity | unit |
| `test_quote_repo_zero_volume_preserved` | `volume=0` in DB → `0` in domain (not None) | unit |
| `test_quote_api_response_nullable_fields` | API response includes `null` for missing quotes | unit |

**Acceptance criteria**:
- [ ] No NULL→zero coercion in quote_repo
- [ ] `Quote` entity uses `Decimal | None` for bid/ask/last
- [ ] API response schema updated
- [ ] 3 new tests pass

---

##### T-E2-1-04: Replace `assert` with explicit guards; fix `period_end` type (C-008, C-010)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py`
- `services/market-data/src/market_data/infrastructure/messaging/consumers/quotes_consumer.py`
- `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py`

**What to build**:

**C-010 — Replace `assert` with explicit RuntimeError** (BP-038):
```python
# Before:
assert self._current_uow is not None

# After:
if self._current_uow is None:
    raise RuntimeError("mark_processed called outside of processing context — this is a programming error")
```
Apply to all 3 consumers (search for `assert self._current_uow`).

**C-008 — Fix `period_end` type coercion** in fundamentals consumer:
```python
# Before (duck-type — breaks on string):
as_of_date=record.period_end.date() if hasattr(record.period_end, "date") else record.period_end

# After (explicit parse):
from common.time import parse_utc  # or datetime.fromisoformat
as_of_date = (
    record.period_end.date()
    if isinstance(record.period_end, datetime)
    else date.fromisoformat(str(record.period_end))
)
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_mark_processed_raises_runtime_error_when_no_uow` | `mark_processed` raises RuntimeError if called outside context | unit |
| `test_fundamentals_period_end_parsed_from_string` | String `period_end` correctly parsed to date | unit |
| `test_fundamentals_period_end_from_datetime_works` | datetime `period_end` correctly converted to date | unit |

**Acceptance criteria**:
- [ ] All `assert self._current_uow is not None` replaced with explicit RuntimeError
- [ ] `period_end` always parsed to `date` regardless of input type
- [ ] 3 new tests pass

---

##### T-E2-1-05: Add `ON CONFLICT DO NOTHING` to `IngestionEventRepository.create()` (C-017 — market-data side)

**Type**: impl
**depends_on**: [T-E2-1-02]
**blocks**: []
**Target files**:
- `services/market-data/src/market_data/infrastructure/db/repositories/ingestion_event_repo.py`

**What to build**:
This is partially addressed by T-E2-1-02 (which adds `create_if_not_exists()`). Ensure the original `create()` method (if still used) also has `ON CONFLICT DO NOTHING` to prevent crash on replay (BP-040).

If `create()` is fully replaced by `create_if_not_exists()`, remove it or mark as deprecated.

**Acceptance criteria**:
- [ ] No bare `INSERT INTO ingestion_events` without conflict handling
- [ ] Replay safety verified by test in T-E2-1-02

#### Validation Gate (Wave E2-1)
- [x] `ruff check services/market-data/` clean
- [x] `mypy services/market-data/src/` clean
- [x] `python -m pytest services/market-data/tests -m unit -v` — all pass (≥260 expected + 13 new)

#### Regression Guardrails
- BP-034: All 3 consumers must call `mark_processed` before any early return
- BP-035: No check-before-insert pattern — use insert-and-catch
- BP-038: No `assert` in production code — always `if ... raise`

---

### Wave E2-2: Architecture + LIKE escape ✅

**Goal**: Fix LIKE pattern injection in instrument search, replace `event_type` instance defaults with ClassVar, rename `security_id` → `instrument_id` in fundamentals endpoints.
**Depends on**: Wave E2-1
**Estimated effort**: 30–45 minutes
**Status**: **DONE** — 2026-03-27 · 271 tests pass · ruff + mypy clean
**Architecture layer**: infrastructure + API

#### Tasks

##### T-E2-2-01: Escape LIKE metacharacters in instrument search (M-002)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-data/src/market_data/infrastructure/db/repositories/instrument_repo.py`

**What to build**:
Escape `%` and `_` in user-supplied search query before constructing LIKE pattern:

```python
def _escape_like(self, value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

# In search query construction:
escaped = self._escape_like(query)
pattern = f"%{escaped}%"
conditions.append(
    or_(
        InstrumentModel.symbol.ilike(pattern, escape="\\"),
        InstrumentModel.exchange.ilike(pattern, escape="\\"),
    )
)
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_instrument_search_escapes_percent` | Query `%` matches literally, not wildcard | unit |
| `test_instrument_search_escapes_underscore` | Query `_` matches literally | unit |
| `test_instrument_search_normal_query_works` | Normal symbol search still returns results | unit |

**Acceptance criteria**:
- [ ] LIKE metacharacters escaped
- [ ] 3 new tests pass

---

##### T-E2-2-02: Replace `event_type` instance default with ClassVar in domain events (M-015)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-data/src/market_data/domain/events.py`

**What to build**:
Change `event_type: str = "market.instrument.created"` (instance default) to `event_type: ClassVar[str] = "market.instrument.created"` for all event subclasses. This matches the portfolio pattern and makes it explicit that `event_type` is a class-level constant, not an instance field that could vary.

```python
from typing import ClassVar

@dataclass(frozen=True)
class InstrumentCreated(DomainEvent):
    event_type: ClassVar[str] = "market.instrument.created"
    schema_version: ClassVar[int] = 1
    # ... instance fields
```

Update `DomainEvent` base to remove `event_type: str = ""` from instance fields.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_instrument_created_event_type_is_class_var` | `InstrumentCreated.event_type == "market.instrument.created"` | unit |
| `test_instrument_created_event_type_not_in_init` | Cannot set `event_type` via constructor | unit |

**Acceptance criteria**:
- [ ] All event `event_type` fields are `ClassVar[str]`
- [ ] mypy strict passes (no ClassVar vs instance confusion)
- [ ] 2 new tests pass

---

##### T-E2-2-03: Rename `security_id` path param to `instrument_id` in fundamentals routers (M-016)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-data/src/market_data/api/routers/fundamentals.py`
- `services/market-data/tests/unit/test_fundamentals_api.py` (update parameter names)
- `docs/services/market-data.md`

**What to build**:
Find all route definitions with `security_id: UUID` path parameter and rename to `instrument_id: UUID`. Update all callers and tests.

```python
# Before:
@router.get("/{security_id}/income-statement")
async def get_income_statement(security_id: UUID, ...) -> ...:

# After:
@router.get("/{instrument_id}/income-statement")
async def get_income_statement(instrument_id: UUID, ...) -> ...:
```

Update docs to reflect the rename.

**Acceptance criteria**:
- [ ] All fundamentals routes use `instrument_id` parameter
- [ ] Tests updated to use new parameter name
- [ ] Docs updated
- [ ] No broken references

#### Validation Gate (Wave E2-2)
- [x] `ruff check services/market-data/` clean
- [x] `mypy services/market-data/src/` clean
- [x] All unit tests pass (≥270 expected)
- [x] Docs updated for fundamentals endpoints

---

### Wave E2-3: Tests — consumer coverage + API edge cases ✅

**Goal**: Expand test coverage for consumers (malformed events, error paths) and instrument API (pagination, error responses).
**Depends on**: Wave E2-2
**Estimated effort**: 30–45 minutes
**Architecture layer**: tests
**Status**: **DONE** — 2026-03-28 · 281 unit tests pass · ruff + mypy clean

#### Tasks

##### T-E2-3-01: Add consumer error path tests and market-data integration test coverage

**Type**: test
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-data/tests/unit/test_ohlcv_consumer.py`
- `services/market-data/tests/unit/test_quotes_consumer.py`
- `services/market-data/tests/unit/test_fundamentals_consumer.py`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_ohlcv_consumer_missing_event_id_raises_fatal` | Missing `event_id` → FatalError | unit |
| `test_ohlcv_consumer_invalid_uuid_event_id` | Malformed UUID in event_id → FatalError | unit |
| `test_ohlcv_consumer_minio_unavailable_retryable` | MinIO fetch fails → RetryableError | unit |
| `test_quotes_consumer_null_bid_ask_handled` | NULL bid/ask in payload → `None` in Quote entity | unit |
| `test_fundamentals_consumer_period_end_string_parsed` | String period_end parsed correctly (from T-E2-1-04) | unit |
| `test_fundamentals_consumer_missing_period_end_uses_fallback` | None period_end → uses ingested_at | unit |

**Acceptance criteria**:
- [x] 6 new tests across 3 consumer test files (5 added this wave + 1 from E2-1)
- [x] All marked `@pytest.mark.unit`

#### Validation Gate (Wave E2-3)
- [x] All unit tests pass (≥278 expected) — 281 passing

---

## Sub-Plan E-3: Portfolio (S1) Fixes

### Wave E3-1: BLOCKING + CRITICAL — Idempotency, Avro Schema, Outbox Status, ON CONFLICT ✅

**Goal**: Fix record_transaction idempotency swallow bug, flatten Portfolio Avro schema, align outbox status, add ON CONFLICT to idempotency repo.
**Depends on**: none
**Estimated effort**: 60–75 minutes
**Status**: **DONE** — 2026-03-28 · 287 unit tests pass · ruff + format clean
**Architecture layer**: application + infrastructure + schema

#### Pre-read
- `services/portfolio/src/portfolio/application/use_cases/record_transaction.py`
- `services/portfolio/src/portfolio/infrastructure/db/repositories/outbox.py`
- `services/portfolio/src/portfolio/infrastructure/db/repositories/idempotency.py`
- `infra/kafka/schemas/portfolio.events.v1.avsc`
- `services/portfolio/src/portfolio/infrastructure/messaging/outbox/mapper.py`
- `services/portfolio/src/portfolio/infrastructure/messaging/outbox/dispatcher.py`
- `libs/messaging/src/messaging/kafka/dispatcher/base.py` (expected status values)

#### Tasks

##### T-E3-1-01: Fix idempotency key parse failure in `record_transaction` (B-003)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/portfolio/src/portfolio/application/use_cases/record_transaction.py`

**What to build**:
Replace the silent exception suppression with a fail-fast 422 response (D-007):

```python
# Before (broken — swallows parse errors):
try:
    idem_uuid = UUID(cmd.idempotency_key)
    already_done = await uow.idempotency.exists(idem_uuid)
    ...
except (ValueError, AttributeError):
    pass  # BUG: proceeds without idempotency

# After (fail-fast):
if cmd.idempotency_key is not None:
    try:
        idem_uuid = UUID(cmd.idempotency_key)
    except (ValueError, AttributeError) as exc:
        raise IdempotencyKeyInvalid(f"idempotency_key must be a valid UUID: {exc}") from exc
    already_done = await uow.idempotency.exists(idem_uuid)
    if already_done:
        ...
```

Add `IdempotencyKeyInvalid` to `domain/errors.py` and handle in API router as HTTP 422.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_record_transaction_invalid_idempotency_key_raises_422` | Malformed key → raises domain error → 422 | unit |
| `test_record_transaction_valid_idempotency_key_respected` | Valid key → dedup works | unit |
| `test_record_transaction_no_idempotency_key_proceeds` | Null key → no error | unit |

**Acceptance criteria**:
- [ ] Invalid `idempotency_key` raises `IdempotencyKeyInvalid` (not silently ignored)
- [ ] API router maps to 422
- [ ] 3 new tests pass

---

##### T-E3-1-02: Fix `EVENT_TOPIC_MAP` fallback — explicit raise on missing entry (B-005)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/portfolio/src/portfolio/infrastructure/db/repositories/outbox.py`

**What to build**:
Replace the silent fallback (BP-039) with an explicit raise:

```python
# Before:
topic = EVENT_TOPIC_MAP.get(row.event_type, row.event_type)  # BUG

# After:
topic = EVENT_TOPIC_MAP.get(row.event_type)
if topic is None:
    raise ValueError(
        f"No topic mapping for event_type={row.event_type!r}. "
        f"Add it to EVENT_TOPIC_MAP in outbox.py."
    )
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_claim_batch_raises_on_unknown_event_type` | Unregistered event_type → ValueError | unit |
| `test_claim_batch_known_event_types_route_correctly` | All registered event types map to correct topics | unit |

**Acceptance criteria**:
- [ ] No silent fallback to event_type as topic name
- [ ] 2 new tests pass

---

##### T-E3-1-03: Flatten Portfolio Avro schema — remove `payload: string` wrapper (C-009 — D-003)

**Type**: schema
**depends_on**: none
**blocks**: [T-E3-1-04]
**Target files**:
- `infra/kafka/schemas/portfolio.events.v1.avsc`
- `services/portfolio/src/portfolio/infrastructure/messaging/outbox/mapper.py`
- `services/portfolio/src/portfolio/infrastructure/messaging/outbox/dispatcher.py`

**What to build**:
Redesign the Avro schema to use top-level fields (D-003). The current schema has a `payload: string` field that wraps a JSON-encoded event. Replace with a proper union-type or polymorphic approach.

Given the variety of portfolio events (10 event types), use a **union schema approach**: one Avro schema per event type, each with its own top-level fields matching the domain event. This aligns with how market-data handles `InstrumentCreated`.

**New schema pattern** (one file per event type in `infra/kafka/schemas/`):
- `portfolio.portfolio.created.avsc` — `{event_id, event_type, schema_version, occurred_at, tenant_id, portfolio_id, owner_id, name}`
- `portfolio.transaction.recorded.avsc` — `{event_id, event_type, schema_version, occurred_at, tenant_id, portfolio_id, transaction_id, ...}`
- etc. (10 total)

Update `mapper.py` to produce flat dicts per event type rather than `{"payload": json.dumps(...)}`.

Update `dispatcher.py` to use per-event-type Avro serializers (like market-data dispatcher).

**Downstream test impact**:
- `libs/contracts/tests/test_avro_alignment.py` — may need new schema assertions
- Any tests mocking outbox mapper output

**Acceptance criteria**:
- [ ] No `payload: string` in any portfolio Avro schema
- [ ] All 10 event types have flat-field Avro schemas
- [ ] Mapper produces flat dicts (not JSON-encoded strings)
- [ ] Dispatcher uses per-event-type serializers
- [ ] Avro schemas validate with `fastavro.parse_schema`

---

##### T-E3-1-04: Update portfolio outbox mapper + serializer to use flat schemas (C-009 cont.)

**Type**: impl
**depends_on**: [T-E3-1-03]
**blocks**: []
**Target files**:
- `services/portfolio/src/portfolio/infrastructure/messaging/outbox/mapper.py`
- `services/portfolio/src/portfolio/infrastructure/messaging/serialization.py` (new file or existing)

**What to build**:
Create per-event-type serializer builders following the pattern in `market-ingestion/src/market_ingestion/infrastructure/messaging/serialization.py`:

```python
def build_portfolio_event_serializers(registry_client) -> dict[str, AvroSerializer]:
    return {
        "portfolio.portfolio.created":     _build_serializer(registry_client, "portfolio.portfolio.created"),
        "portfolio.transaction.recorded":  _build_serializer(registry_client, "portfolio.transaction.recorded"),
        # ... 10 event types
    }
```

Update `mapper.py` from identity mapper to proper per-event-type dict builders.

**Acceptance criteria**:
- [ ] `build_portfolio_event_serializers()` returns 10 serializers
- [ ] `mapper.py` produces flat dicts matching each event's Avro schema
- [ ] No `identity_mapper` / passthrough remaining in outbox flow

---

##### T-E3-1-05: Align outbox status to libs/messaging standard + fix `increment_attempts` (C-014, M-011)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/portfolio/src/portfolio/infrastructure/db/repositories/outbox.py`

**What to build**:

**C-014**: Change outbox status from `"processing"` to `"in_flight"` and `"delivered"` to `"published"` throughout portfolio outbox repo:
```python
# claim_batch: status="in_flight" (not "processing")
# mark_delivered: status="published" (not "delivered")
```

**M-011**: Replace read-modify-write `increment_attempts` with atomic SQL (same as T-E1-3-02):
```python
stmt = (
    update(OutboxEventModel)
    .where(OutboxEventModel.id == record_id)
    .values(attempt_count=OutboxEventModel.attempt_count + 1)
)
```

**Acceptance criteria**:
- [ ] Portfolio uses `"in_flight"` / `"published"` status values
- [ ] `increment_attempts` uses atomic SQL expression
- [ ] Existing tests updated to reflect status name changes
- [ ] All tests pass

---

##### T-E3-1-06: Add `ON CONFLICT DO NOTHING` to portfolio idempotency INSERT (C-017 — portfolio side)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/portfolio/src/portfolio/infrastructure/db/repositories/idempotency.py`

**What to build**:
Add `on_conflict_do_nothing` to the idempotency INSERT (BP-040):

```python
async def record(self, event_id: UUID) -> None:
    stmt = (
        insert(IdempotencyModel)
        .values(event_id=event_id)
        .on_conflict_do_nothing()
    )
    await self._session.execute(stmt)
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_idempotency_record_does_not_raise_on_duplicate` | Recording same event_id twice → no error | unit |

**Acceptance criteria**:
- [ ] `ON CONFLICT DO NOTHING` on idempotency INSERT
- [ ] 1 new test passes

#### Validation Gate (Wave E3-1)
- [x] `ruff check services/portfolio/` clean
- [x] `mypy services/portfolio/src/` clean (3 pre-existing redis async_timeout errors only)
- [x] All unit tests pass (287 passed)
- [x] Avro schemas validate (flat per-event schemas)
- [x] No outbox routing uses fallback

---

### Wave E3-2: CRITICAL — Tenant Auth + UoW Exception Masking ✅

**Goal**: Add X-Internal-Token auth to tenant endpoints, fix UoW __aexit__ exception masking, fix dual outbox partial failure.
**Depends on**: Wave E3-1
**Estimated effort**: 45–60 minutes
**Status**: **DONE** — 2026-03-28 · 287 unit tests pass · ruff + format clean
**Architecture layer**: API + infrastructure

#### Tasks

##### T-E3-2-01: Restrict tenant endpoints to X-Internal-Token auth (C-002 — D-001)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/portfolio/src/portfolio/api/routes/tenant.py`
- `services/portfolio/src/portfolio/api/dependencies.py`
- `services/portfolio/tests/unit/test_tenant_api.py`

**What to build**:
Add `Annotated[None, Depends(verify_internal_token)]` dependency to `create_tenant` and `get_tenant` endpoints (D-001 decision):

```python
from portfolio.api.dependencies import verify_internal_token, InternalTokenDep

@router.post("/tenants", response_model=TenantResponse, status_code=201)
async def create_tenant(
    body: TenantCreateRequest,
    uow: UoWDep,
    _auth: InternalTokenDep,   # ← ADD
) -> TenantResponse:
    ...
```

The `InternalTokenDep` is already defined for internal endpoints. Reuse it.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_create_tenant_without_token_returns_401` | Missing X-Internal-Token → 401 | unit |
| `test_create_tenant_wrong_token_returns_401` | Wrong token → 401 | unit |
| `test_create_tenant_valid_token_succeeds` | Correct token → 201 | unit |
| `test_get_tenant_without_token_returns_401` | GET without token → 401 | unit |

**Acceptance criteria**:
- [ ] Both tenant endpoints require valid X-Internal-Token
- [ ] 4 new tests pass
- [ ] `services/portfolio/.claude-context.md` updated to document tenant endpoint auth

---

##### T-E3-2-02: Fix UoW `__aexit__` exception masking (M-007)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/portfolio/src/portfolio/infrastructure/db/unit_of_work.py`

**What to build**:
Same fix as T-E1-2-03 (BP-037). Ensure rollback failures don't suppress the original exception:

```python
async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
    try:
        if exc_val is not None:
            await self.rollback()
        else:
            await self.commit()
    except Exception as cleanup_err:
        logger.error("uow_cleanup_error", error=str(cleanup_err), original=repr(exc_val))
    finally:
        await self._session.close()
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_uow_session_closed_even_if_rollback_fails` | Session close runs in finally even if rollback throws | unit |
| `test_uow_original_exception_preserved_on_rollback_failure` | Original exception is logged, not swallowed | unit |

**Acceptance criteria**:
- [ ] Session always closed in finally
- [ ] Original exception preserved when cleanup fails
- [ ] 2 new tests pass

---

##### T-E3-2-03: Fix dual outbox inserts partial failure in `record_transaction` (M-009)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/portfolio/src/portfolio/application/use_cases/record_transaction.py`

**What to build**:
Pre-validate both outbox event dicts before the first `uow.outbox.save()` call, so serialization failures happen before any DB writes:

```python
# Before transaction begins, validate both events can be serialized:
transaction_event_dict = mapper.to_dict(transaction_event)
holding_event_dict = mapper.to_dict(holding_event)

# Then within the UoW transaction:
await uow.transactions.save(transaction)
await uow.holdings.save(holding)
await uow.outbox.save(OutboxRecord.from_dict(transaction_event_dict))
await uow.outbox.save(OutboxRecord.from_dict(holding_event_dict))
await uow.idempotency.record(idem_uuid)
```

This ensures mapper failures (serialization errors) surface before any DB write, keeping the transaction atomic.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_record_transaction_mapper_failure_prevents_any_db_write` | Serialization error before save → no DB changes | unit |

**Acceptance criteria**:
- [ ] Outbox event dicts built before entering UoW context
- [ ] Any serialization error → no partial DB writes
- [ ] 1 new test passes

#### Validation Gate (Wave E3-2)
- [x] `ruff check services/portfolio/` clean
- [x] `mypy services/portfolio/src/` clean (3 pre-existing redis async_timeout errors only)
- [x] All unit tests pass (287 passed)

---

### Wave E3-3: MAJOR Security + Input Validation ✅

**Goal**: Add Field constraints to API request schemas, fix internal token default, fix cache invalidation ordering, fix watchlist uniqueness TOCTOU.
**Depends on**: Wave E3-2
**Estimated effort**: 45–60 minutes
**Architecture layer**: API + application
**Status**: **DONE** — 2026-03-28 · 289 tests pass · ruff + mypy clean

#### Tasks

##### T-E3-3-01: Add Pydantic Field constraints to portfolio API request schemas (M-001)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/portfolio/src/portfolio/api/schemas.py`

**What to build**:
Add `Field(...)` constraints to all unvalidated string fields in request models:

```python
from pydantic import Field, EmailStr

class TenantCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, strip_whitespace=True)

class UserCreateRequest(BaseModel):
    tenant_id: UUID
    email: EmailStr = Field(..., max_length=254)  # RFC 5321 max

class PortfolioCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, strip_whitespace=True)

class PortfolioRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, strip_whitespace=True)

class WatchlistCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, strip_whitespace=True)
```

Also add `pydantic[email]` to pyproject.toml dev dependencies if `EmailStr` is not already available.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_create_tenant_empty_name_returns_422` | `name=""` → 422 | unit |
| `test_create_tenant_too_long_name_returns_422` | 256-char name → 422 | unit |
| `test_create_user_invalid_email_returns_422` | `email="not-an-email"` → 422 | unit |
| `test_create_portfolio_empty_name_returns_422` | `name=""` → 422 | unit |

**Acceptance criteria**:
- [ ] All 5 request models have length constraints
- [ ] Email validated with EmailStr
- [ ] 4 new tests pass

---

##### T-E3-3-02: Fix internal service token empty-string default + cache invalidation ordering (M-035, M-005)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/portfolio/src/portfolio/config.py`
- `services/portfolio/src/portfolio/application/use_cases/watchlist.py`

**What to build**:

**M-035 — Token default**: Add startup validation that `internal_service_token` is non-empty when the service starts. Use a Pydantic validator:
```python
@model_validator(mode="after")
def _validate_internal_token(self) -> "Settings":
    if not self.internal_service_token:
        import warnings
        warnings.warn(
            "PORTFOLIO_INTERNAL_SERVICE_TOKEN is empty — internal endpoints are unprotected",
            stacklevel=2,
        )
    return self
```

**M-005 — Cache invalidation ordering**: In watchlist `add_member` and `remove_member` use cases, move cache invalidation inside the UoW context (before commit) or use an on_commit callback. The goal is to ensure cache is only invalidated if the DB write succeeds:

```python
# Inside UoW context, after DB writes, before commit:
async def _on_commit():
    await cache.invalidate_entity(entity_id)

uow.on_commit(_on_commit)  # Register callback
await uow.members.save(member)
# Commit triggers _on_commit callback
```

If `on_commit` callbacks aren't supported, at minimum catch the cache exception and log it (don't let a Valkey failure roll back the DB write):
```python
try:
    await cache.invalidate_entity(entity_id)
except Exception as e:
    logger.warning("watchlist_cache_invalidation_failed", entity_id=str(entity_id), error=str(e))
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_config_warns_on_empty_internal_token` | Empty token emits warning on startup | unit |
| `test_watchlist_db_write_succeeds_even_if_cache_fails` | Cache exception doesn't roll back DB write | unit |

**Acceptance criteria**:
- [ ] Warning emitted when token is empty
- [ ] Cache failure doesn't roll back watchlist DB writes
- [ ] 2 new tests pass

---

##### T-E3-3-03: Fix TOCTOU watchlist name uniqueness + lazy infrastructure import (M-010, M-012)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/portfolio/src/portfolio/application/use_cases/watchlist.py`
- `services/portfolio/src/portfolio/api/dependencies.py`

**What to build**:

**M-010 — TOCTOU watchlist**: Add a docstring comment to the watchlist create use case noting that the DB unique constraint is the authoritative guard, and the application-level check is only for UX (fail fast with readable error). Verify the unique constraint `(tenant_id, user_id, name)` exists in the migration:
```python
# NOTE: The DB has a unique constraint on (tenant_id, user_id, name, status='active').
# This in-memory check provides a fast 409 before the DB write; the constraint is the
# authoritative guard against concurrent creates.
```

**M-012 — Lazy import**: Move the `from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork` import in `dependencies.py` inside the function body:

```python
# Before (module-level import):
from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

async def get_uow(...) -> AsyncIterator[UnitOfWork]:
    async with SqlAlchemyUnitOfWork(...) as uow:
        yield uow

# After (lazy import inside function):
async def get_uow(...) -> AsyncIterator[UnitOfWork]:
    from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork  # lazy
    async with SqlAlchemyUnitOfWork(...) as uow:
        yield uow
```

**Acceptance criteria**:
- [ ] Watchlist TOCTOU documented with explanation
- [ ] `SqlAlchemyUnitOfWork` import moved to function body in `dependencies.py`
- [ ] Existing tests still pass

#### Validation Gate (Wave E3-3)
- [x] `ruff check services/portfolio/` clean
- [x] `mypy services/portfolio/src/` clean
- [x] All unit tests pass

---

### Wave E3-4: Tests + Architecture Cleanup ✅

**Goal**: Add missing test coverage for portfolio (instrument consumer, transactions, holdings), fix InstrumentConsumer UUID idempotency, standardize event envelope to strings.
**Depends on**: Wave E3-3
**Estimated effort**: 45–60 minutes
**Architecture layer**: tests + domain
**Status**: **DONE** — 2026-03-28 · 289 tests pass · ruff + mypy clean

#### Tasks

##### T-E3-4-01: Add InstrumentConsumer malformed event tests + fix UUID idempotency (M-017, M-018)

**Type**: impl+test
**depends_on**: none
**blocks**: []
**Target files**:
- `services/portfolio/src/portfolio/infrastructure/messaging/consumers/instrument_consumer.py`
- `services/portfolio/tests/unit/test_instrument_consumer.py`

**What to build**:

**M-017 — Fix UUID idempotency**: The consumer currently generates `new_uuid7()` on every message for `instrument.id`. On replay, a different UUID is generated, creating a duplicate. Fix by using the source event's `entity_id` (or a deterministic hash of `symbol+exchange`) as the stable ID:

```python
# Use entity_id from upstream event as stable instrument ID
entity_id = UUID(value["entity_id"]) if "entity_id" in value else None
instrument = InstrumentRef(
    id=entity_id or new_uuid7(),  # Prefer upstream entity_id for idempotency
    ...
)
```

**M-018 — Tests**: Add tests for malformed event handling:

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_process_message_uses_entity_id_as_stable_id` | Same event_id → same instrument ID on replay | unit |
| `test_process_message_missing_symbol_skips_upsert` | Empty symbol → no DB write | unit |
| `test_process_message_invalid_event_id_uses_fallback_uuid7` | Invalid UUID event_id → fallback to new_uuid7() | unit |
| `test_process_message_idempotent_on_replay` | Same event replayed twice → single instrument row | unit |
| `test_instrument_consumer_marked_unit` | Test file has `pytestmark = [pytest.mark.unit]` | unit |

**Acceptance criteria**:
- [ ] Instrument consumer uses `entity_id` as stable ID when available
- [ ] 5 new tests including idempotency test
- [ ] `pytestmark = [pytest.mark.unit]` added to test file (M-022 fix)

---

##### T-E3-4-02: Add portfolio test coverage gaps (M-019, M-021, M-023)

**Type**: test
**depends_on**: none
**blocks**: []
**Target files**:
- `services/portfolio/tests/unit/test_instrument_api.py`
- `services/portfolio/tests/integration/test_transaction_api.py`
- `services/portfolio/tests/unit/test_domain_entities.py`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_get_instrument_not_found_returns_404` | Non-existent instrument_id → 404 | unit |
| `test_get_instrument_invalid_uuid_returns_422` | Malformed UUID → 422 | unit |
| `test_list_instruments_pagination_large_offset` | Offset > total count → empty list, not error | unit |
| `test_list_transactions_exact_count_not_gte` | `data["total"] == 1` exact assertion (replaces `>= 1`) | integration |
| `test_list_transactions_scoped_to_portfolio` | Transactions from other portfolio not returned | integration |
| `test_holding_apply_delta_multi_leg_weighted_average` | buy 10@100, buy 5@200 → avg_cost = 133.33 | unit |
| `test_holding_apply_delta_fractional_quantity` | Decimal("0.001") quantities handled | unit |

**Acceptance criteria**:
- [ ] 7 new tests across 3 test files
- [ ] Exact assertion in `test_list_transactions` (M-021 fix)
- [ ] Multi-leg holding test covers weighted-average calculation

---

##### T-E3-4-03: Standardize portfolio event envelope to string types (M-013, M-014)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/portfolio/src/portfolio/domain/events.py`
- `services/portfolio/src/portfolio/infrastructure/messaging/outbox/mapper.py`

**What to build**:
Standardize portfolio domain events to use string types for `event_id` (UUIDv7 hex string) and `occurred_at` (ISO-8601 with `Z` suffix), matching market-ingestion and market-data (D-009 decision):

```python
# domain/events.py — change base:
@dataclass(frozen=True)
class DomainEvent:
    event_id: str = field(default_factory=lambda: str(new_uuid7()))
    occurred_at: str = field(default_factory=lambda: utc_now().isoformat().replace("+00:00", "Z"))

# mapper.py — no .isoformat() call needed (M-014 fix):
"event_id": event.event_id,      # Already a string
"occurred_at": event.occurred_at, # Already ISO-8601 with Z
```

Update any code that treats `event_id` as a UUID object to use `UUID(event.event_id)` for explicit conversion.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_domain_event_event_id_is_uuidv7_string` | `event_id` is a valid UUIDv7 hex string | unit |
| `test_domain_event_occurred_at_has_z_suffix` | `occurred_at` ends with `Z` | unit |

**Acceptance criteria**:
- [ ] All portfolio events use `str` for `event_id` and `occurred_at`
- [ ] No `.isoformat()` calls in mapper (M-014 fix)
- [ ] 2 new tests pass

#### Validation Gate (Wave E3-4)
- [x] `ruff check services/portfolio/` clean
- [x] `mypy services/portfolio/src/` clean
- [x] All unit tests pass
- [ ] Integration tests pass (or skipped with reason — require running containers)

---

## Sub-Plan E-4: Cross-Cutting Fixes

### Wave E4-1: Security Config Hardening

**Goal**: Remove hardcoded MinIO credentials from all services and shared storage lib, fix EODHD "demo" key default, fix DB connection string credential exposure, standardize config naming.
**Depends on**: none
**Estimated effort**: 45–60 minutes
**Architecture layer**: config

#### Pre-read
- `services/portfolio/src/portfolio/config.py`
- `services/market-ingestion/src/market_ingestion/config.py`
- `services/market-data/src/market_data/config.py`
- `libs/storage/src/storage/settings.py`
- `configs/dev.local.env.example` (if exists)

#### Tasks

##### T-E4-1-01: Remove hardcoded MinIO credentials from all services + shared lib (C-001)

**Type**: config
**depends_on**: none
**blocks**: []
**Target files**:
- `services/portfolio/src/portfolio/config.py`
- `services/market-ingestion/src/market_ingestion/config.py`
- `services/market-data/src/market_data/config.py`
- `libs/storage/src/storage/settings.py`

**What to build**:
Remove default values for `storage_access_key` and `storage_secret_key` in all 4 locations. Pydantic-settings will require these env vars at startup (no default = required):

```python
# Before:
storage_access_key: str = "minioadmin"
storage_secret_key: str = "minioadmin"  # noqa: S105

# After:
storage_access_key: str  # Required — set PORTFOLIO_STORAGE_ACCESS_KEY env var
storage_secret_key: str  # Required — set PORTFOLIO_STORAGE_SECRET_KEY env var
```

Update `configs/dev.local.env.example` (or equivalent) to document these env vars with the dev value `minioadmin`.

**Acceptance criteria**:
- [ ] No `minioadmin` defaults in config files
- [ ] Startup fails with clear `ValidationError` if env vars not set
- [ ] `dev.local.env.example` documents the dev defaults

---

##### T-E4-1-02: Fix EODHD API key default + standardize config names (M-004, M-027)

**Type**: config
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-ingestion/src/market_ingestion/config.py`
- All 3 services' config files (for M-027)

**What to build**:

**M-004**: Add validation warning for EODHD demo key:
```python
@model_validator(mode="after")
def _warn_demo_eodhd_key(self) -> "Settings":
    if self.eodhd_api_key == "demo":
        import warnings
        warnings.warn(
            "EODHD API key is 'demo' — limited to demo endpoints only. "
            "Set MARKET_INGESTION_EODHD_API_KEY for production use.",
            stacklevel=2,
        )
    return self
```

**M-027**: Standardize `kafka_schema_registry_url` → `schema_registry_url` across all 3 services (or vice versa — pick one standard). Since market-ingestion and market-data already use `schema_registry_url`, update portfolio to match. Update all env var references and docker-compose files.

**Acceptance criteria**:
- [ ] Warning emitted when EODHD key is "demo"
- [ ] All 3 services use `schema_registry_url` (same name)
- [ ] docker-compose env vars updated to match

---

##### T-E4-1-03: Verify outbox dispatcher lease duration is sufficient (B-006)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/portfolio/src/portfolio/infrastructure/messaging/outbox/dispatcher.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/messaging/outbox/dispatcher.py`
- `services/market-data/src/market_data/infrastructure/messaging/outbox/dispatcher.py`

**What to build**:
Review `DispatcherConfig` lease duration in each service. Recommended minimum: 30 seconds (typical Kafka publish is < 5s, 30s provides 6× safety margin). Add a metric `outbox_record_reclaimed_total` (counter) when a record's lease has expired and it's being re-claimed:

In the claim_batch query, if a record has `attempt_count > 0` and `locked_until IS NULL` (lease expired), log a warning:
```python
for row in claimed_rows:
    if row.attempt_count > 0:
        metrics.outbox_records_reclaimed.inc()
        logger.warning("outbox.record_reclaimed", record_id=str(row.id), attempts=row.attempt_count)
```

**Acceptance criteria**:
- [ ] Lease duration ≥ 30 seconds in all 3 dispatcher configs
- [ ] Re-claim warning logged when `attempt_count > 0`
- [ ] Comment documents the lease duration rationale

#### Validation Gate (Wave E4-1)
- [ ] `ruff check libs/ services/` clean
- [ ] `mypy libs/storage/src/ services/*/src/` clean on changed files
- [ ] `configs/dev.local.env.example` updated with all required env vars

---

### Wave E4-2: Documentation + Context Files

**Goal**: Fix portfolio docs port, update .claude-context.md files for all 3 services, update MASTER_PLAN if needed.
**Depends on**: Wave E4-1
**Estimated effort**: 30 minutes
**Architecture layer**: docs

#### Tasks

##### T-E4-2-01: Fix portfolio docs port + update service docs (C-012, M-028)

**Type**: docs
**depends_on**: none
**blocks**: []
**Target files**:
- `docs/services/portfolio.md`
- `docs/services/market-ingestion.md`
- `docs/services/market-data.md`
- `services/portfolio/.claude-context.md`
- `services/market-ingestion/.claude-context.md`
- `services/market-data/.claude-context.md`

**What to build**:

**C-012**: Fix `docs/services/portfolio.md` line 3 from `Port: 8000` to `Port: 8001`.

**M-028**: Update `.claude-context.md` for market-ingestion and market-data to add:
- **Pitfalls** section (matching portfolio style)
- **Bug Patterns** section with relevant BP-XXX references
- Any new known issues discovered in this QA pass

Market-ingestion pitfalls to add:
- result_ref columns added in E1-1 — check migration applied
- Token bucket requires SELECT-FOR-UPDATE (BP-036)
- Watermark uses created_at (not utc_now) for tasks without range_end

Market-data pitfalls to add:
- Quote fields are `Decimal | None` — handle null in API responses
- mark_processed called before ANY early return (BP-034)
- assert replaced with RuntimeError — check all consumers

**Acceptance criteria**:
- [ ] Portfolio docs show correct port 8001
- [ ] All 3 `.claude-context.md` files have Pitfalls + Bug Patterns sections
- [ ] Changes consistent with implementations in this plan

---

##### T-E4-2-02: Update MASTER_PLAN + TRACKING.md for plan completion

**Type**: docs
**depends_on**: none
**blocks**: []
**Target files**:
- `docs/MASTER_PLAN.md` (minor: update service ports table if needed)
- `docs/plans/TRACKING.md` (move PLAN-0001-E from draft → in-progress)

**What to build**:
Minor updates to ensure MASTER_PLAN reflects:
- portfolio port confirmed as 8001
- Any architectural decisions from this plan (e.g., flat Avro schemas for portfolio)

Update TRACKING.md status for PLAN-0001-E from `draft` to `in-progress` when first wave begins.

**Acceptance criteria**:
- [ ] MASTER_PLAN.md port table correct
- [ ] TRACKING.md reflects current plan status

#### Validation Gate (Wave E4-2)
- [ ] No broken links in docs
- [ ] `.claude-context.md` format matches portfolio's structure

---

### Wave E4-3: Input Validation — Market-Ingestion + Market-Data

**Goal**: Add missing input validation to market-ingestion API schemas (symbol length, date range) and market-data instrument search.
**Depends on**: Wave E4-2
**Estimated effort**: 30–45 minutes
**Architecture layer**: API

#### Tasks

##### T-E4-3-01: Add input validation to market-ingestion API schemas (M-SEC-018, M-SEC-019)

**Type**: impl
**depends_on**: none
**blocks**: []
**Target files**:
- `services/market-ingestion/src/market_ingestion/api/schemas.py`

**What to build**:
Add validators to `TriggerRequest` and `BackfillRequest`:

```python
class TriggerRequest(BaseModel):
    provider: str = Field(..., min_length=1, max_length=50)
    symbols: list[str] = Field(..., min_length=1, max_length=1000)
    dataset_type: str = Field(..., min_length=1, max_length=50)
    timeframe: str = Field("1d", min_length=1, max_length=10)
    exchange: str | None = Field(None, max_length=20)

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, v: list[str]) -> list[str]:
        for s in v:
            if not (1 <= len(s) <= 20):
                raise ValueError(f"Symbol {s!r} must be 1-20 characters")
        return v

class BackfillRequest(BaseModel):
    ...
    chunk_days: int = Field(30, ge=1, le=365)

    @field_validator("end_date")
    @classmethod
    def validate_date_range_not_too_large(cls, v: date, info: Any) -> date:
        start = info.data.get("start_date")
        if start and (v - start).days > 10 * 365:
            raise ValueError("Date range must not exceed 10 years")
        return v
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_trigger_request_empty_symbol_rejected` | Empty symbol string → 422 | unit |
| `test_trigger_request_too_long_symbol_rejected` | 21-char symbol → 422 | unit |
| `test_backfill_request_chunk_days_zero_rejected` | chunk_days=0 → 422 | unit |
| `test_backfill_request_10_year_range_accepted` | 3650-day range → valid | unit |
| `test_backfill_request_exceeds_10_year_rejected` | 3651-day range → 422 | unit |

**Acceptance criteria**:
- [ ] Symbol length 1-20 chars enforced
- [ ] Backfill chunk_days 1-365 enforced
- [ ] Date range ≤ 10 years enforced
- [ ] 5 new tests pass

#### Validation Gate (Wave E4-3)
- [ ] `ruff check services/market-ingestion/` clean
- [ ] `mypy services/market-ingestion/src/` clean
- [ ] All unit tests pass

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Portfolio Avro schema flatten (E3-1 W1 T-E3-1-03) is large | HIGH | HIGH | Read existing market-data schema patterns first; allocate extra time |
| Portfolio pyproject.toml dep conflict prevents tests | MEDIUM | MEDIUM | Fix before starting E-3; run `uv pip install -e ".[dev]" --reinstall` |
| claim_batch CTE rewrite breaks existing tests | MEDIUM | MEDIUM | Run full test suite after T-E1-3-01; revert if needed |
| SELECT-FOR-UPDATE causes deadlock in tests | LOW | LOW | Use mock budget repo in unit tests; integration tests use serial execution |

**Critical path**: E-3 W1 (Avro schema) → E-3 W2 (mapper/dispatcher) → E-3 W3 (tests)

**Highest-risk single task**: T-E3-1-03 (Portfolio Avro schema flatten) — touches schema + mapper + dispatcher + downstream tests

---

## Findings Coverage Map

| Finding ID | Severity | Task | Wave |
|------------|----------|------|------|
| B-001 | BLOCKING | T-E2-1-01 | E2-1 |
| B-002 | BLOCKING | T-E1-1-03 | E1-1 |
| B-003 | BLOCKING | T-E3-1-01 | E3-1 |
| B-004 | BLOCKING | T-E1-1-01, T-E1-1-02 | E1-1 |
| B-005 | BLOCKING | T-E3-1-02 | E3-1 |
| B-006 | BLOCKING | T-E4-1-03 | E4-1 |
| C-001 | CRITICAL | T-E4-1-01 | E4-1 |
| C-002 | CRITICAL | T-E3-2-01 | E3-2 |
| C-003 | CRITICAL | T-E2-1-02 | E2-1 |
| C-004 | CRITICAL | T-E2-1-03 | E2-1 |
| C-005 | CRITICAL | T-E1-1-04 | E1-1 |
| C-006 | CRITICAL | T-E1-1-04 | E1-1 |
| C-007 | CRITICAL | Deferred — libs/messaging change; risk-assessed as low-frequency edge case in practice |
| C-008 | CRITICAL | T-E2-1-04 | E2-1 |
| C-009 | CRITICAL | T-E3-1-03, T-E3-1-04 | E3-1 |
| C-010 | CRITICAL | T-E2-1-04 | E2-1 |
| C-011 | CRITICAL | T-E1-2-01 | E1-2 |
| C-012 | CRITICAL | T-E4-2-01 | E4-2 |
| C-013 | CRITICAL | T-E1-1-04 | E1-1 |
| C-014 | CRITICAL | T-E3-1-05 | E3-1 |
| C-015 | CRITICAL | T-E1-1-05 | E1-1 |
| C-016 | CRITICAL | T-E1-4-01 | E1-4 |
| C-017 | CRITICAL | T-E2-1-05, T-E3-1-06 | E2-1, E3-1 |
| C-018 | CRITICAL | T-E1-1-06 | E1-1 |
| M-001 | MAJOR | T-E3-3-01 | E3-3 |
| M-002 | MAJOR | T-E2-2-01 | E2-2 |
| M-003 | MAJOR | T-E4-1-01 | E4-1 |
| M-004 | MAJOR | T-E4-1-02 | E4-1 |
| M-005 | MAJOR | T-E3-3-02 | E3-3 |
| M-006 | MAJOR | T-E1-3-01 | E1-3 |
| M-007 | MAJOR | T-E3-2-02 | E3-2 |
| M-008 | MAJOR | T-E1-2-03 | E1-2 |
| M-009 | MAJOR | T-E3-2-03 | E3-2 |
| M-010 | MAJOR | T-E3-3-03 | E3-3 |
| M-011 | MAJOR | T-E3-1-05 | E3-1 |
| M-012 | MAJOR | T-E3-3-03 | E3-3 |
| M-013 | MAJOR | T-E3-4-03 | E3-4 |
| M-014 | MAJOR | T-E3-4-03 | E3-4 |
| M-015 | MAJOR | T-E2-2-02 | E2-2 |
| M-016 | MAJOR | T-E2-2-03 | E2-2 |
| M-017 | MAJOR | T-E3-4-01 | E3-4 |
| M-018 | MAJOR | T-E3-4-01 | E3-4 |
| M-019 | MAJOR | T-E3-4-02 | E3-4 |
| M-020 | MAJOR | T-E1-4-02 | E1-4 |
| M-021 | MAJOR | T-E3-4-02 | E3-4 |
| M-022 | MAJOR | T-E3-4-01 | E3-4 |
| M-023 | MAJOR | T-E3-4-02 | E3-4 |
| M-024 | MAJOR | T-E1-3-03 | E1-3 |
| M-027 | MAJOR | T-E4-1-02 | E4-1 |
| M-028 | MAJOR | T-E4-2-01 | E4-2 |
| M-029 | MAJOR | T-E1-3-04 | E1-3 |
| M-031 | MAJOR | T-E1-2-04 | E1-2 |
| M-033 | MAJOR | T-E1-4-03 | E1-4 |
| M-035 | MAJOR | T-E3-3-02 | E3-3 |
| SEC-018/019 | MINOR | T-E4-3-01 | E4-3 |
| C-007 | CRITICAL | Deferred to libs/messaging wave | Future |

**Deferred (C-007)**: Kafka offset commit ordering fix requires libs/messaging refactor. Risk is low-frequency (only under specific failure conditions during rebalance) — deferred to a dedicated libs/messaging QA wave.

---

## Compounding Updates

- Added BP-034 through BP-040 to `docs/ai-interactions/BUG_PATTERNS.md` ✅ (already done in QA report step)
- Updated TRACKING.md with QA-CROSS-002 row ✅ (already done)
- Plan file created: `docs/plans/0001-e-qa-cross002-fixes-plan.md` ← this file
