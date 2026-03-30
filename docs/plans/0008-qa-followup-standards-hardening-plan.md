---
id: PLAN-0008
title: QA Follow-Up — Standards Enforcement, Architecture Hardening & Production Readiness
status: draft
created: 2026-03-30
updated: 2026-03-30
waves_done: 7
plans: 7
waves: 12
tasks: 48
source_qa: QA report 2026-03-30 on feat/content-ingestion-wave-a1 (PLAN-0001-E-R1)
---

# PLAN-0008: QA Follow-Up — Standards Enforcement, Architecture Hardening & Production Readiness

## Overview

**Source**: QA run 2026-03-30 on `feat/content-ingestion-wave-a1`, reviewing PLAN-0001-E-R1 (S1 + S2 + S3).
**Goal**: Fix all remaining findings from that QA pass, enforce architectural standards across all services,
and improve the documentation layer (RULES, STANDARDS, skills, review materials) so future waves are
self-enforcing.

### Decisions Applied from QA Review

| # | Finding | Decision |
|---|---------|----------|
| D-1 | F-DS-004 / F-ARCH-005 | Option B is the **cross-service UoW standard**: `__aexit__` never commits; every mutating use case MUST call `await uow.commit()` explicitly. Enforce in RULES + STANDARDS. Fix market-ingestion. |
| D-2 | F-DS-011 | Extract `InstrumentEventConsumer` from portfolio API process into a dedicated standalone container (matching `portfolio-dispatcher` pattern). |
| D-3 | F-DS-001/002 | Catch `sqlalchemy.exc.IntegrityError` on concurrent same-key commit → re-query existing transaction → return 409 if still missing. |
| D-4 | F-SEC-004 | Replace all `minioadmin` and similarly hardcoded default credentials in `docker.env.example` files with `<CHANGE_ME>` placeholders + deployment comment. |

---

## Sub-plan Dependency Graph

```
Sub-plan A (Docs + Standards)  ─────────────────────────────────────────────────────→ All other waves use updated docs
    │
    ├── Sub-plan B (UoW Enforcement — market-ingestion fix)                must read A
    │
    ├── Sub-plan C (S1 Portfolio — TOCTOU + consumer extraction)           must read A
    │       Wave C-1: TOCTOU IntegrityError → 409
    │       Wave C-2: Consumer architecture fixes
    │       Wave C-3: Consumer standalone process
    │
    ├── Sub-plan D (S2 market-ingestion layer cleanup)                     must read A,B
    │
    ├── Sub-plan E (S3 market-data reliability)                            must read A
    │
    ├── Sub-plan F (Production readiness)                                  independent
    │
    └── Sub-plan G (Test coverage gaps)                                    must read A,B,C-2,D
```

**Critical path**: A → B (D-1) → D → merge
**Parallelizable after A**: B ∥ C-1 ∥ E ∥ F ∥ G-1

---

## Sub-plan A: Cross-Cutting Documentation & Standards (1 wave)

**Goal**: Update the documentation layer (RULES, STANDARDS, HIGH_RISK_PATTERNS, REVIEW_CHECKLIST, skill
context) so the UoW explicit-commit standard and all other patterns identified in this QA round are
permanently encoded. Future `/implement` and `/review` agents will find these rules automatically.

### Wave A-1: Standards, Rules & Skill Context Update

**Goal**: Encode Option B UoW standard, production readiness gaps, and review improvements
into every doc layer that agents read at session start.
**Depends on**: none
**Estimated effort**: 45 min
**Architecture layer**: docs

#### T-A-1-01: Add R25 to RULES.md — Explicit UoW Commit

**Type**: docs
**depends_on**: none
**blocks**: [T-A-1-02, T-B-1-01]
**Target files**: `RULES.md`

**What to build**: Add rule R25 to the Architecture Rules section of `RULES.md`:

```markdown
### R25: UoW `__aexit__` MUST NOT commit — all commits must be explicit
**Why**: Auto-commit in `__aexit__` means silent writes on any code path that exits the
context manager without calling `commit()`. It also makes double-commit bugs undetectable
(sqlalchemy silently ignores the second commit). Discovered as a live bug in market-ingestion
(F-DS-004). Option B standard: `__aexit__` only rolls back on exception; every mutating use
case calls `await uow.commit()` explicitly.
**Enforcement**: REVIEW_CHECKLIST §UoW + IG-ARCH-001 architecture test. Any concrete
`UnitOfWork.__aexit__` that calls `commit()` in an `else` or unconditional branch is a
BLOCKING review violation.
```

Also update the summary table at the bottom of RULES.md to include R25.

**Acceptance criteria**:
- [ ] R25 added to RULES.md with a clear "why" explanation
- [ ] Summary table updated

---

#### T-A-1-02: Update STANDARDS.md — Add §17 UoW Explicit-Commit Pattern

**Type**: docs
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**: `docs/STANDARDS.md`

**What to build**: Add a new section **§17: Unit of Work — Explicit Commit Pattern** after §16
(Session Optimization). This section must define:

1. **Option B standard** (the cross-service standard):
   - `__aexit__` rolls back on exception, closes session in `finally`. Never commits.
   - Every mutating use case calls `await uow.commit()` explicitly before returning.
   - The abstract `UnitOfWork.__aexit__` ABC provides the default rollback-only behaviour.
2. **Anti-pattern** (auto-commit in `__aexit__`):

```python
# WRONG — Option A (auto-commit in __aexit__)
async def __aexit__(self, exc_type, exc_val, exc_tb):
    if exc_type is not None:
        await self.rollback()
    else:
        await self.commit()   # FORBIDDEN — R25 violation
    await self._session.close()

# CORRECT — Option B
async def __aexit__(self, exc_type, exc_val, exc_tb):
    try:
        if exc_type is not None:
            await self.rollback()
    except Exception:
        pass  # swallow rollback failure
    finally:
        await self._session.close()
```

3. **Dispatch UoW** (for outbox-only UoWs like content-ingestion/content-store): delegate to
   `session.__aexit__` on clean exit (closes without committing), explicit `rollback()` on
   exception. This is the correct pattern already in use.
4. **Audit checklist**: "Before merging any new service, grep for `else.*commit` in `__aexit__`"

Also update §11 (Anti-Patterns) to add this as an explicit forbidden pattern alongside a WRONG/CORRECT example.

Also update §12 (Platform Rules) summary table to include R25.

**Acceptance criteria**:
- [ ] §17 added with concrete code examples
- [ ] §11 updated with anti-pattern + correction
- [ ] §12 table updated

---

#### T-A-1-03: Update HIGH_RISK_PATTERNS.md — UoW Auto-Commit Signal

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**: `.claude/review/heuristics/HIGH_RISK_PATTERNS.md`

**What to build**: Add a new HIGH-severity risk pattern entry:

```
## HR-NEW: UoW `__aexit__` auto-commit (R25 violation)

Signal: `else:` branch in any `__aexit__` method that calls `await self.commit()` or
`await session.commit()`.

Risk: BLOCKING — silent double-commits, unexpectedly committed empty transactions,
post-commit side-effects running on every context exit (not just after explicit commits).

Grep pattern: `grep -n "else.*commit\|__aexit__.*commit" services/*/src/*/infrastructure/db/unit_of_work.py`

Fix: Remove the `else: await self.commit()` branch. Add explicit `await uow.commit()` to
every mutating use case. See STANDARDS.md §17.
```

**Acceptance criteria**:
- [ ] New HR entry added to HIGH_RISK_PATTERNS.md

---

#### T-A-1-04: Update REVIEW_CHECKLIST.md — UoW Commit + Session Cleanup Checks

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**: `.claude/review/checklists/REVIEW_CHECKLIST.md`

**What to build**: Add two new items to the relevant section of REVIEW_CHECKLIST.md:

**UoW / Transaction section**:
```
- [ ] UoW `__aexit__`: no `else: await self.commit()` — only rollback on exception (R25)
- [ ] Every mutating use case calls `await uow.commit()` explicitly (not relying on __aexit__)
- [ ] Rollback is wrapped in try/finally with session close in the `finally` block (prevents session leak when rollback raises)
- [ ] Post-commit hooks run OUTSIDE `commit()` with independent try/except (hook failure must not dead-letter successfully-committed messages)
```

**Acceptance criteria**:
- [ ] Checklist updated

---

#### T-A-1-05: Update Skill Context Files — Mandate STANDARDS.md Pre-read

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**: `.claude/skills/implement/SKILL.md`, `.claude/skills/plan/SKILL.md`, `.claude/skills/qa/SKILL.md`, `.claude/skills/review/SKILL.md`

**What to build**: Verify that each skill's Phase 0 / Context Loading section explicitly lists
`docs/STANDARDS.md` as a **mandatory pre-read** (not optional). If any skill only mentions
`RULES.md` and `AGENTS.md` but not `STANDARDS.md`, add it.

Specifically verify that:
- `/implement` Phase 0 reads: `RULES.md`, `AGENTS.md`, `docs/STANDARDS.md`
- `/plan` Phase 0 reads: `RULES.md`, `AGENTS.md`, `docs/STANDARDS.md`
- `/qa` Phase 1 context loads: `RULES.md`, `AGENTS.md`, `docs/STANDARDS.md`
- `/review` materials include: `docs/STANDARDS.md`

Also update `CLAUDE.md` context loading section (step 3 in "For deeper context") to reference `STANDARDS.md` explicitly alongside `RULES.md`.

**Acceptance criteria**:
- [ ] All 4 skills reference `docs/STANDARDS.md` in their context loading section
- [ ] CLAUDE.md updated

---

#### T-A-1-06: Update PRODUCTION_READINESS.md — New Gaps Identified

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**: `docs/PRODUCTION_READINESS.md`

**What to build**: Add new checklist items to PRODUCTION_READINESS.md under the appropriate
categories:

**Category: Secrets & Configuration (P0)**:
```
- [ ] P0: Replace all `minioadmin` defaults in `docker.env.example` files with
       `<CHANGE_ME>` — use Docker secrets or Vault for production injection
       (Ref: F-SEC-004, PLAN-0008 Sub-plan F)
- [ ] P0: Replace all `internal_service_token = ""` defaults with a mandatory
       non-empty secret injected at deploy time for each service that uses X-Internal-Token
       (portfolio, market-ingestion)
- [ ] P0: Switch `warnings.warn` for missing secrets to `structlog` WARNING so alerts
       appear in the structured log pipeline (F-SEC-001)
```

**Category: Network Security (P1)**:
```
- [ ] P1: Bind `/metrics` Prometheus endpoint to internal interface only (not 0.0.0.0)
       or add network-level access controls — metrics expose operational intelligence
       (F-SEC-010)
- [ ] P1: Add `max_length=200` to `BatchQuoteRequest.instrument_ids` and all unbounded
       list query parameters in market-data to prevent DoS amplification (F-SEC-006/007)
```

**Category: Architecture / Kafka Migration (P1)**:
```
- [ ] P1: Before any non-fresh deployment, drain `market.events.v1` topic to zero consumer
       lag before deploying Wave 5 topic alignment — or add one-time bridge consumer
       (F-DS-014 migration gap)
```

**Category: Monitoring (P1)**:
```
- [ ] P1: Add dedicated `portfolio-instrument-consumer` container to production deployment
       manifest (not in-process with API) for independent lifecycle and Kafka offset safety
       (F-DS-011, PLAN-0008 Wave C-3)
```

**Acceptance criteria**:
- [ ] All new items added under correct priority categories in PRODUCTION_READINESS.md

---

#### Validation Gate (Wave A-1)

- [ ] No new ruff/mypy errors introduced
- [ ] All doc files are valid Markdown
- [ ] Grep for `docs/STANDARDS.md` in all 4 skill files returns a match

---

---

## Sub-plan B: UoW Explicit-Commit Enforcement (1 wave)

**Goal**: Fix the one remaining concrete UoW that auto-commits on clean exit (market-ingestion),
fix the dispatcher that bypasses `get_unit_of_work()`, and fix deprecated `asyncio.get_event_loop()`
calls.

### Wave B-1: Fix market-ingestion UoW + Dispatcher

**Goal**: Make market-ingestion conform to the Option B UoW standard. All use cases already
have explicit `await uow.commit()` calls — no use case changes needed.
**Depends on**: Wave A-1 (R25 now in RULES.md)
**Estimated effort**: 30 min
**Architecture layer**: infrastructure

#### T-B-1-01: Remove Auto-Commit from S2 `SqlaUnitOfWork.__aexit__`

**Type**: impl
**depends_on**: none
**blocks**: [T-B-1-05]
**Target files**: `services/market-ingestion/src/market_ingestion/infrastructure/db/unit_of_work.py`

**What to build**: Remove `else: await self.commit()` from `SqlaUnitOfWork.__aexit__`.
Also wrap the rollback call in try/finally to prevent session leak (matching S1 portfolio pattern):

```python
# BEFORE (auto-commits — R25 violation)
async def __aexit__(self, exc: ...) -> None:
    try:
        if exc is not None:
            await self.rollback()
        else:
            await self.commit()   # REMOVE THIS
    except Exception:
        ...
    finally:
        await self._write_session.close()
        ...

# AFTER (Option B — rollback-only)
async def __aexit__(self, exc_type: ...) -> None:
    try:
        if exc_type is not None:
            await self.rollback()
    except Exception:
        pass
    finally:
        if self._write_session is not None:
            await self._write_session.close()
            self._write_session = None
        if self._read_session is not None:
            await self._read_session.close()
            self._read_session = None
```

Also update the abstract `UnitOfWork.__aexit__` docstring in
`services/market-ingestion/src/market_ingestion/application/ports/unit_of_work.py`
to document Option B explicitly: "Never auto-commits. Caller MUST call `await uow.commit()` explicitly."

**Acceptance criteria**:
- [ ] `else: await self.commit()` removed
- [ ] Session closed in `finally` block (both write and read)
- [ ] Abstract UoW docstring updated
- [ ] mypy clean

---

#### T-B-1-02: Verify All S2 Use Cases Have Explicit `await uow.commit()`

**Type**: impl
**depends_on**: [T-B-1-01]
**blocks**: [T-B-1-05]
**Target files**: `services/market-ingestion/src/market_ingestion/application/use_cases/*.py`

**What to build**: Audit all mutating use cases in market-ingestion. The audit (from QA prep)
shows these already have explicit commits:
- `claim_tasks.py`: line 48 ✓
- `trigger_ingestion.py`: line 85 ✓
- `execute_task.py`: lines 195, 394, 400 ✓
- `backfill.py`: line 91 ✓
- `schedule_tasks.py`: lines 66, 103 ✓

Verify no use case was missed (especially read-only queries — they don't need commit).
If any mutating use case is missing `await uow.commit()`, add it now.

**Acceptance criteria**:
- [ ] Every mutating use case path has `await uow.commit()` before returning
- [ ] No `async with uow:` block without a `commit()` in the non-exception path

---

#### T-B-1-03: Fix S2 Dispatcher — Use `get_unit_of_work()` + `asyncio.get_running_loop()`

**Type**: impl
**depends_on**: [T-B-1-01]
**blocks**: [T-B-1-05]
**Target files**: `services/market-ingestion/src/market_ingestion/infrastructure/messaging/dispatcher.py`

**What to build**:

1. **Replace direct instantiation** in `_dispatch_batch` (line 118):
   ```python
   # BEFORE
   uow = SqlaUnitOfWork(self._write_factory)
   # AFTER
   uow = await self.get_unit_of_work()
   ```
   Remove the `from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork`
   module-level import if it is only used here (check — it may still be needed for
   `get_unit_of_work()` return type annotation, but the return type annotation should use
   the abstract port `UnitOfWork`, not the concrete class).

2. **Replace `asyncio.get_event_loop()`** (line 155) with `asyncio.get_running_loop()`:
   ```python
   # BEFORE
   loop = asyncio.get_event_loop()
   # AFTER
   loop = asyncio.get_running_loop()
   ```

Also fix the same `get_event_loop()` → `get_running_loop()` in:
- `services/portfolio/src/portfolio/infrastructure/messaging/outbox/dispatcher_main.py` (line 39)

**Acceptance criteria**:
- [ ] `_dispatch_batch` uses `await self.get_unit_of_work()` not `SqlaUnitOfWork(...)` directly
- [ ] Both dispatcher files use `get_running_loop()`, not `get_event_loop()`
- [ ] No new mypy errors

---

#### T-B-1-04: Update S2 `__aexit__` docstring in abstract port

**Type**: docs
**depends_on**: [T-B-1-01]
**blocks**: none
**Target files**: `services/market-ingestion/src/market_ingestion/application/ports/unit_of_work.py`

**What to build**: Add a clear docstring to the abstract `UnitOfWork.__aexit__`:
```python
"""Exit the unit of work context.

**Option B standard (R25)**: This method NEVER commits.
On exception: rolls back the transaction.
On success: does nothing (session will be closed by concrete implementation).
Callers MUST call ``await uow.commit()`` explicitly before exiting the context.
"""
```

**Acceptance criteria**:
- [ ] Abstract UoW has clear Option B docstring referencing R25

---

#### T-B-1-05: Regression Tests — S2 UoW No-Auto-Commit

**Type**: test
**depends_on**: [T-B-1-01, T-B-1-02]
**blocks**: none
**Target files**: `services/market-ingestion/tests/` (new or existing test file)

**What to build**: Add a test that verifies `SqlaUnitOfWork.__aexit__` does NOT call
`session.commit()` on clean exit:

```python
async def test_sqla_uow_aexit_does_not_auto_commit():
    """Option B (R25): clean __aexit__ must not call commit."""
    mock_session = AsyncMock()
    mock_factory = MagicMock(return_value=mock_session)
    uow = SqlaUnitOfWork(mock_factory)
    async with uow:
        pass  # clean exit, no exception
    mock_session.commit.assert_not_called()
    mock_session.close.assert_called_once()

async def test_sqla_uow_aexit_rollbacks_on_exception():
    """On exception, __aexit__ must rollback."""
    mock_session = AsyncMock()
    mock_factory = MagicMock(return_value=mock_session)
    uow = SqlaUnitOfWork(mock_factory)
    with pytest.raises(ValueError):
        async with uow:
            raise ValueError("test error")
    mock_session.rollback.assert_called_once()
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_sqla_uow_aexit_does_not_auto_commit` | No commit on clean exit (R25) | unit |
| `test_sqla_uow_aexit_rollbacks_on_exception` | Rollback fires on exception | unit |
| `test_sqla_uow_session_closed_on_exception` | Session always closes even when rollback raises | unit |

**Acceptance criteria**:
- [ ] 3 new regression tests pass
- [ ] Tests assert `commit` not called on clean exit

---

#### Validation Gate (Wave B-1)

- [ ] `ruff check` clean on all changed files
- [ ] `mypy` clean on S2 service
- [ ] `pytest services/market-ingestion/tests/ -m unit` — 379+ tests pass
- [ ] No `else.*commit` in any `__aexit__` across services: `grep -rn "else.*await.*commit" services/*/src/*/infrastructure/*/unit_of_work.py` returns empty

---

---

## Sub-plan C: S1 Portfolio — TOCTOU Completion + Consumer Extraction (3 waves)

### Wave C-1: TOCTOU IntegrityError → 409 + Idempotency Conflict Handling

**Goal**: Complete BP-035 fix — concurrent same-key requests that both pass `create_if_not_exists`
before either commits now surface as a clean 409 instead of an unhandled `IntegrityError`.
**Depends on**: Wave A-1
**Estimated effort**: 45 min
**Architecture layer**: application + API

#### T-C-1-01: Add `IdempotencyConflictError` to Domain Errors

**Type**: impl
**depends_on**: none
**blocks**: [T-C-1-02]
**Target files**: `services/portfolio/src/portfolio/domain/errors.py`

**What to build**: Add a new domain error class:
```python
class IdempotencyConflictError(ConflictError):
    """Raised when concurrent requests with the same idempotency key both attempt to
    commit simultaneously. The losing request should be treated as a duplicate and
    the caller should re-query for the original result.
    """
```

**Acceptance criteria**:
- [ ] `IdempotencyConflictError` added, inherits from `ConflictError`

---

#### T-C-1-02: Catch `IntegrityError` in `RecordTransactionUseCase` → Re-query → Return or Raise

**Type**: impl
**depends_on**: [T-C-1-01]
**blocks**: [T-C-1-03, T-C-1-04]
**Target files**: `services/portfolio/src/portfolio/application/use_cases/record_transaction.py`

**What to build**: Wrap the `await uow.commit()` call in a try/except for
`sqlalchemy.exc.IntegrityError`. The IntegrityError means two concurrent same-key requests
both got `is_new=True` but one lost the race at commit time:

```python
from sqlalchemy.exc import IntegrityError

try:
    await uow.commit()
except IntegrityError:
    # Concurrent same-key commit: the row was inserted by the racing request.
    # Re-query to return the original transaction.
    await uow.rollback()
    existing = await uow.transactions.find_by_external_ref(
        portfolio_id=cmd.portfolio_id,
        tenant_id=cmd.tenant_id,
        external_ref=cmd.external_ref,
    )
    if existing is not None:
        return RecordTransactionResult(transaction=existing, created=False)
    raise IdempotencyConflictError(
        f"Concurrent idempotency conflict on key {cmd.idempotency_key!r}; "
        "retry the request."
    )
```

Also fix the `is_new=False` + `find_by_external_ref returns None` path (F-DS-002):
```python
if not is_new:
    existing = await uow.transactions.find_by_external_ref(...)
    if existing is not None:
        return RecordTransactionResult(transaction=existing, created=False)
    # Should never happen: idempotency key recorded but transaction missing
    raise IdempotencyConflictError(
        f"Idempotency key {cmd.idempotency_key!r} already recorded but "
        "original transaction not found; state is inconsistent."
    )
```

**Acceptance criteria**:
- [ ] `IntegrityError` caught, re-query performed, existing transaction returned or `IdempotencyConflictError` raised
- [ ] `is_new=False` + missing transaction raises `IdempotencyConflictError` (not falls through)
- [ ] mypy clean (import `IntegrityError` under `TYPE_CHECKING` or at module level as needed)

---

#### T-C-1-03: Map `IdempotencyConflictError` → HTTP 409 in API Exception Handler

**Type**: impl
**depends_on**: [T-C-1-01]
**blocks**: [T-C-1-04]
**Target files**: `services/portfolio/src/portfolio/app.py` or `services/portfolio/src/portfolio/api/exception_handlers.py`

**What to build**: Add `IdempotencyConflictError` → 409 mapping to the domain exception
handler (check where `ConflictError` is currently mapped — if it's already mapped to 409 and
`IdempotencyConflictError` inherits from it, no change needed; otherwise add explicitly).

Verify the handler covers `ConflictError` → 409. If so, document that `IdempotencyConflictError`
inherits this mapping. If not, add:
```python
@app.exception_handler(IdempotencyConflictError)
async def handle_idempotency_conflict(request, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})
```

**Acceptance criteria**:
- [ ] `IdempotencyConflictError` results in 409 response
- [ ] Existing error handler not broken

---

#### T-C-1-04: Tests for Concurrent Same-Key → 409

**Type**: test
**depends_on**: [T-C-1-02, T-C-1-03]
**blocks**: none
**Target files**: `services/portfolio/tests/unit/test_use_cases_transaction.py`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_integrity_error_on_commit_re_queries_existing` | IntegrityError → rollback → re-query → returns existing | unit |
| `test_integrity_error_missing_result_raises_conflict_error` | IntegrityError + no existing → IdempotencyConflictError | unit |
| `test_is_new_false_missing_transaction_raises_conflict_error` | is_new=False + no find result → IdempotencyConflictError | unit |
| `test_api_idempotency_conflict_returns_409` | API handler maps IdempotencyConflictError to 409 | unit |

**Acceptance criteria**:
- [ ] 4 new tests pass
- [ ] No existing tests broken

---

#### Validation Gate (Wave C-1)

- [ ] `pytest services/portfolio/tests/ -m unit` — 290+ tests pass
- [ ] `ruff check` + `mypy` clean
- [ ] All 4 new tests verify exact behaviour described above

---

### Wave C-2: Fix InstrumentEventConsumer Architecture

**Goal**: Fix the double-nested UoW pattern, missing-event_uid idempotency bypass, COALESCE
upsert for InstrumentUpdated, and asyncio event loop deprecation.
**Depends on**: Wave A-1
**Estimated effort**: 45 min
**Architecture layer**: infrastructure + domain

#### T-C-2-01: Fix Double Nested UoW in `InstrumentEventConsumer`

**Type**: impl
**depends_on**: none
**blocks**: [T-C-2-04]
**Target files**: `services/portfolio/src/portfolio/infrastructure/messaging/consumers/instrument_consumer.py`

**What to build**: Replace the inner `async with await self.get_unit_of_work() as uow:` block
inside `process_message` with the `_current_uow` pattern used by S3 consumers.

The base class `BaseKafkaConsumer._handle_message` already opens a UoW and stores it in
`self._current_uow` before calling `process_message`. The consumer should use this stored UoW
instead of opening a nested one.

Change `process_message` to use `self._current_uow` (which is set by the base class):
```python
async def process_message(self, key, value, headers):
    uow = self._current_uow  # set by BaseKafkaConsumer._handle_message
    if uow is None:
        raise RuntimeError("process_message called outside _handle_message context")
    # ... rest of method uses uow directly, no nested `async with`
    # DO NOT call await uow.commit() here — base class calls it after process_message returns
```

Also remove the `await uow.commit()` at the end of `process_message` (the base class handles it).

**Acceptance criteria**:
- [ ] No `async with await self.get_unit_of_work()` inside `process_message`
- [ ] Uses `self._current_uow` (or whatever the base class attribute is named — check `libs/messaging/src/messaging/kafka/consumer/base.py`)
- [ ] No `await uow.commit()` inside `process_message`
- [ ] mypy clean

---

#### T-C-2-02: Reject Messages with Missing `event_uid` as `MalformedDataError`

**Type**: impl
**depends_on**: none
**blocks**: [T-C-2-04]
**Target files**: `services/portfolio/src/portfolio/infrastructure/messaging/consumers/instrument_consumer.py`

**What to build**: Replace the `if event_uid is not None:` optional idempotency check with
a hard validation. When `event_id` is missing from the payload, raise `MalformedDataError`
so the base class handles it as a fatal error (dead-letter / reject):

```python
event_id_raw = value.get("event_id")
if not event_id_raw:
    raise MalformedDataError(
        "Missing or null event_id in instrument event — cannot perform idempotency check"
    )
event_uid = UUID(str(event_id_raw))
```

Import `MalformedDataError` from `messaging.kafka.consumer.errors`.

**Acceptance criteria**:
- [ ] Missing `event_id` raises `MalformedDataError`, not silently bypasses dedup
- [ ] Test covers the missing-event_id path

---

#### T-C-2-03: Fix `InstrumentUpdated` Upsert — COALESCE for Metadata Columns

**Type**: impl
**depends_on**: none
**blocks**: [T-C-2-04]
**Target files**: `services/portfolio/src/portfolio/infrastructure/db/repositories/instrument.py`

**What to build**: The current upsert ON CONFLICT clause overwrites `name`, `currency`, and
`asset_class` with `None` when an `InstrumentUpdated` event arrives (because those fields
are absent from that event type). Fix using SQLAlchemy's `func.coalesce`:

```python
from sqlalchemy import func

# In the upsert conflict resolution:
set_={
    "name": func.coalesce(instrument.name, InstrumentModel.name),
    "currency": func.coalesce(instrument.currency, InstrumentModel.currency),
    "asset_class": func.coalesce(instrument.asset_class, InstrumentModel.asset_class),
    # fields that InstrumentUpdated owns fully (always overwrite):
    "has_ohlcv": instrument.has_ohlcv,
    "has_quotes": instrument.has_quotes,
    "has_fundamentals": instrument.has_fundamentals,
    "updated_at": instrument.updated_at,
}
```

**Acceptance criteria**:
- [ ] COALESCE applied to `name`, `currency`, `asset_class` in conflict update
- [ ] InstrumentUpdated event no longer clears metadata columns

---

#### T-C-2-04: Tests for Wave C-2 Fixes

**Type**: test
**depends_on**: [T-C-2-01, T-C-2-02, T-C-2-03]
**blocks**: none
**Target files**: `services/portfolio/tests/unit/test_instrument_consumer.py`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_process_message_uses_current_uow_not_nested` | Uses base-class UoW, no nested context | unit |
| `test_missing_event_id_raises_malformed_data_error` | Missing event_id → MalformedDataError | unit |
| `test_instrument_updated_does_not_overwrite_name_with_none` | COALESCE: existing name preserved | unit |
| `test_instrument_updated_preserves_currency` | COALESCE: existing currency preserved | unit |

**Acceptance criteria**:
- [ ] 4 new tests pass

---

#### Validation Gate (Wave C-2)

- [ ] `pytest services/portfolio/tests/ -m unit` — 290+ pass
- [ ] `ruff check` + `mypy` clean

---

### Wave C-3: Extract InstrumentEventConsumer to Standalone Process

**Goal**: Move `InstrumentEventConsumer` out of the portfolio API lifespan into a dedicated
standalone `portfolio-instrument-consumer` process, matching the `portfolio-dispatcher` pattern.
**Depends on**: Wave C-2
**Estimated effort**: 45 min
**Architecture layer**: infrastructure + config

#### T-C-3-01: Create `instrument_consumer_main.py` Process Entrypoint

**Type**: impl
**depends_on**: none
**blocks**: [T-C-3-02, T-C-3-03]
**Target files**: `services/portfolio/src/portfolio/infrastructure/messaging/consumers/instrument_consumer_main.py`

**What to build**: Create a standalone entrypoint following the exact pattern of
`services/portfolio/src/portfolio/infrastructure/messaging/outbox/dispatcher_main.py`:

```python
"""Standalone entrypoint for the InstrumentEventConsumer process.

Run as: python -m portfolio.infrastructure.messaging.consumers.instrument_consumer_main
"""
import asyncio
import signal

import structlog

from portfolio.config import Settings
from portfolio.infrastructure.db.session import create_session_factory
from portfolio.infrastructure.messaging.consumers.instrument_consumer import InstrumentEventConsumer

logger = structlog.get_logger()

async def main() -> None:
    settings = Settings()
    # ... configure logging, engine, session factory, consumer
    # ... signal handling (SIGTERM → graceful stop)
    # ... run consumer with graceful shutdown (matching dispatcher_main pattern)

if __name__ == "__main__":
    asyncio.run(main())
```

**Acceptance criteria**:
- [ ] `instrument_consumer_main.py` created with proper signal handling
- [ ] Consumer gracefully shuts down on SIGTERM (return code 0)
- [ ] Logging configured before consumer starts

---

#### T-C-3-02: Remove Consumer from `app.py` Lifespan

**Type**: impl
**depends_on**: [T-C-3-01]
**blocks**: [T-C-3-03]
**Target files**: `services/portfolio/src/portfolio/app.py`

**What to build**: Remove the `InstrumentEventConsumer` startup/shutdown from the FastAPI
lifespan. The API process now only manages:
- DB engine + session factory
- Valkey client
- Outbox dispatcher

Remove the `consumer_task` creation and the 10-second shutdown wait. Remove the import of
`InstrumentEventConsumer` from `app.py`.

Add a comment explaining that the instrument consumer runs as a separate process (see
`instrument_consumer_main.py` and the docker-compose `portfolio-instrument-consumer` service).

**Acceptance criteria**:
- [ ] `app.py` no longer imports or instantiates `InstrumentEventConsumer`
- [ ] API lifespan is cleaner (no consumer task management)
- [ ] Tests for app lifespan still pass

---

#### T-C-3-03: Add `portfolio-instrument-consumer` to docker-compose + configs

**Type**: config
**depends_on**: [T-C-3-01, T-C-3-02]
**blocks**: none
**Target files**: `infra/compose/docker-compose.yml`, `services/portfolio/configs/docker.env.example`

**What to build**: Add a new service to `docker-compose.yml` following the
`portfolio-dispatcher` service definition as a template:

```yaml
portfolio-instrument-consumer:
  build:
    context: services/portfolio
    dockerfile: Dockerfile
  command: python -m portfolio.infrastructure.messaging.consumers.instrument_consumer_main
  depends_on:
    postgres:
      condition: service_healthy
    kafka:
      condition: service_healthy
    schema-registry:
      condition: service_healthy
    portfolio:
      condition: service_healthy
  env_file:
    - configs/docker.env
  profiles: [infra, all]
  restart: on-failure:5
```

**Acceptance criteria**:
- [ ] `portfolio-instrument-consumer` service in docker-compose.yml
- [ ] Correct dependencies (postgres, kafka, schema-registry, portfolio)
- [ ] Profile matches other portfolio services

---

#### T-C-3-04: Update Portfolio Service Docs + `.claude-context.md`

**Type**: docs
**depends_on**: [T-C-3-01]
**blocks**: none
**Target files**: `services/portfolio/.claude-context.md`, `docs/services/portfolio.md`

**What to build**: Update docs to reflect the new process topology:
- API process: `portfolio`
- Outbox dispatcher: `portfolio-dispatcher`
- Instrument consumer: `portfolio-instrument-consumer` (NEW)

Add to "Process Topology" section. Note that `InstrumentEventConsumer` no longer runs
in-process with the API.

**Acceptance criteria**:
- [ ] `.claude-context.md` updated with new process topology
- [ ] Service docs updated

---

#### Validation Gate (Wave C-3)

- [ ] `pytest services/portfolio/tests/ -m unit` pass
- [ ] `docker compose config` validates (no YAML errors)
- [ ] `ruff check` + `mypy` clean

---

---

## Sub-plan D: S2 Market-Ingestion — Layer Cleanup (2 waves)

### Wave D-1: Fix API Layer Violations in market-ingestion

**Goal**: Fix the architecture violations in `dependencies.py` and `routes.py` where the API
layer imports concrete infrastructure classes at module level (F-ARCH-002/003/004/007).
**Depends on**: Waves A-1, B-1
**Estimated effort**: 60 min
**Architecture layer**: API + config

#### T-D-1-01: Fix `dependencies.py` — Lazy Infra Imports + Unified Settings

**Type**: impl
**depends_on**: none
**blocks**: [T-D-1-04]
**Target files**: `services/market-ingestion/src/market_ingestion/api/dependencies.py`

**What to build**:

1. Move the three module-level infrastructure imports into the function bodies where used:
   ```python
   # WRONG (module-level, violates IG-LAYER-002):
   from market_ingestion.infrastructure.adapters.providers.registry import ProviderRegistry
   from market_ingestion.infrastructure.db.session import _build_factories
   from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

   # CORRECT: import inside function body (lazy, matches market-data pattern)
   async def get_uow(request: Request) -> AsyncGenerator[UnitOfWork, None]:
       from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
       uow = SqlaUnitOfWork(
           request.app.state.write_session_factory,
           request.app.state.read_session_factory,
       )
       async with uow:
           yield uow
   ```

2. Fix `get_uow` to read session factories from `app.state` (set during lifespan startup)
   instead of calling `_build_factories(settings)` per request (which creates a new engine):
   ```python
   async def get_uow(request: Request) -> AsyncGenerator[UnitOfWork, None]:
       from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
       uow = SqlaUnitOfWork(
           request.app.state.write_session_factory,
           request.app.state.read_session_factory,
       )
       async with uow:
           yield uow
   ```

3. Fix `verify_internal_token` to use `Depends(get_settings)` consistently
   (not `request.app.state.settings`):
   ```python
   async def verify_internal_token(
       x_internal_token: Annotated[str | None, Header()] = None,
       settings: Annotated[Settings, Depends(get_settings)] = ...,
   ) -> None:
       expected = settings.internal_service_token
       ...
   ```

**Acceptance criteria**:
- [ ] All 3 infra imports moved to function bodies
- [ ] `get_uow` reads from `app.state.write_session_factory`
- [ ] `verify_internal_token` uses `Depends(get_settings)` not `app.state.settings`
- [ ] No module-level infra imports remain in `dependencies.py`

---

#### T-D-1-02: Fix `routes.py` — Abstract Port Type for UoW

**Type**: impl
**depends_on**: none
**blocks**: [T-D-1-04]
**Target files**: `services/market-ingestion/src/market_ingestion/api/routes.py`

**What to build**: Replace the concrete `SqlaUnitOfWork` import and type annotation in
`routes.py` with the abstract `UnitOfWork` port:

```python
# WRONG
from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
async def trigger_ingestion(uow: Annotated[SqlaUnitOfWork, Depends(get_uow)]):

# CORRECT
from market_ingestion.application.ports.unit_of_work import UnitOfWork
async def trigger_ingestion(uow: Annotated[UnitOfWork, Depends(get_uow)]):
```

Ensure the import is under `TYPE_CHECKING` if only used for annotation.

**Acceptance criteria**:
- [ ] `SqlaUnitOfWork` import removed from `routes.py`
- [ ] Abstract `UnitOfWork` port used for type annotations

---

#### T-D-1-03: Update `app.py` Lifespan — Store Session Factories on `app.state`

**Type**: impl
**depends_on**: none
**blocks**: [T-D-1-01]
**Target files**: `services/market-ingestion/src/market_ingestion/app.py`

**What to build**: Store the session factories on `app.state` during lifespan startup
(matching the market-data and portfolio patterns):

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = Settings()
    # ... existing initialization ...
    from market_ingestion.infrastructure.db.session import create_session_factories
    write_factory, read_factory = create_session_factories(settings)
    app.state.write_session_factory = write_factory
    app.state.read_session_factory = read_factory
    app.state.settings = settings  # unified settings reference
    # ... existing initialization continues ...
    yield
    # ... cleanup ...
```

If `create_session_factories` doesn't exist as a public function, refactor `_build_factories`
to be public or create a wrapper.

**Acceptance criteria**:
- [ ] `app.state.write_session_factory` set in lifespan
- [ ] `app.state.read_session_factory` set in lifespan
- [ ] `app.state.settings` set in lifespan
- [ ] `_build_factories` no longer called per-request

---

#### T-D-1-04: Update Tests for S2 API Layer Changes

**Type**: test
**depends_on**: [T-D-1-01, T-D-1-02, T-D-1-03]
**blocks**: none
**Target files**: `services/market-ingestion/tests/api/test_routes.py`, `services/market-ingestion/tests/conftest.py`

**What to build**: Update test fixtures/conftest to set `app.state.write_session_factory`,
`app.state.read_session_factory`, and `app.state.settings` if tests create the app directly.
Verify existing 379+ unit tests still pass.

**Acceptance criteria**:
- [ ] `pytest services/market-ingestion/tests/ -m unit` — 379+ pass
- [ ] No tests fail due to missing `app.state` attributes

---

#### Validation Gate (Wave D-1)

- [ ] `pytest services/market-ingestion/tests/ -m unit` — 379+ pass
- [ ] `python scripts/import_guards/check_import_guards.py` — 0 net-new violations
- [ ] `ruff check` + `mypy` clean

---

### Wave D-2: Fix S2 Business Logic Bug — `InvalidStateTransition` Not Recorded

**Goal**: Fix `execute_task.py` — when `InvalidStateTransition` is raised in Step 5, the task
must be persisted as FAILED before re-raising (F-DS-005).
**Depends on**: Wave B-1
**Estimated effort**: 20 min
**Architecture layer**: application

#### T-D-2-01: Persist Task Failure on `InvalidStateTransition`

**Type**: impl
**depends_on**: none
**blocks**: [T-D-2-02]
**Target files**: `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py`

**What to build**: In the `except InvalidStateTransition` block of Step 5, call `task.fail(exc)`
and then `await self._persist_fail(task, exc)` before re-raising:

```python
except InvalidStateTransition as exc:
    logger.warning("execute_task.invalid_state_transition", task_id=str(task.id), error=str(exc))
    # Persist the failure so the task doesn't remain stuck in RUNNING state
    task.fail(exc)
    await self._persist_fail(task, exc)
    raise
```

If `_persist_fail` is a private method that also calls `uow.commit()`, ensure it is called
before re-raise and verify it handles the case where `task.fail()` was already called.

**Acceptance criteria**:
- [ ] `InvalidStateTransition` → `task.fail()` + `_persist_fail()` before re-raise
- [ ] Task transitions to FAILED state in DB when InvalidStateTransition is raised

---

#### T-D-2-02: Tests for InvalidStateTransition → FAILED Task State

**Type**: test
**depends_on**: [T-D-2-01]
**blocks**: none
**Target files**: `services/market-ingestion/tests/application/test_execute_task.py`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_invalid_state_transition_persists_failed_task` | InvalidStateTransition → task saved as FAILED | unit |
| `test_invalid_state_transition_reraises` | InvalidStateTransition still propagates after persistence | unit |

**Acceptance criteria**:
- [ ] 2 new tests pass

---

#### Validation Gate (Wave D-2)

- [ ] `pytest services/market-ingestion/tests/ -m unit` — 380+ pass

---

---

## Sub-plan E: S3 Market-Data — Reliability Fixes (2 waves)

### Wave E-1: Session Cleanup + Post-Commit Hook Isolation

**Goal**: Fix S3 UoW session leak (F-DS-006), post-commit cache hook failure dead-lettering (F-DS-015),
and remove vestigial `collect_event` path (F-DS-007).
**Depends on**: Wave A-1
**Estimated effort**: 45 min
**Architecture layer**: infrastructure

#### T-E-1-01: Wrap Rollback in try/finally in S3 `UoW.__aexit__`

**Type**: impl
**depends_on**: none
**blocks**: [T-E-1-04]
**Target files**: `services/market-data/src/market_data/infrastructure/db/uow.py`

**What to build**: Wrap `rollback()` in try/finally so sessions always close even when rollback
raises. Match the S1 portfolio pattern:

```python
async def __aexit__(self, exc_type, exc_val, exc_tb):
    try:
        if exc_type is not None:
            await self.rollback()
    except Exception:
        pass  # swallow rollback errors; close will still run
    finally:
        await self._close_sessions()
```

Where `_close_sessions` closes both write and read sessions safely.

**Acceptance criteria**:
- [ ] Sessions always closed even when `rollback()` raises
- [ ] Pattern matches S1 portfolio UoW

---

#### T-E-1-02: Move Post-Commit Hooks Outside `commit()` — Isolate Cache Hook Failures

**Type**: impl
**depends_on**: none
**blocks**: [T-E-1-04]
**Target files**: `services/market-data/src/market_data/infrastructure/db/uow.py`

**What to build**: Currently post-commit hooks run inside `commit()`. If a hook raises (e.g.,
cache invalidation fails), the exception propagates out of `commit()`, through the base class,
and the message is dead-lettered even though the DB commit succeeded.

Refactor to run hooks AFTER commit, outside the commit method, with independent error isolation:

```python
async def commit(self) -> None:
    """Commit DB transaction. Raises on DB failure (caller should re-raise/rollback)."""
    await self._write_session.commit()
    # Notify outbox dispatcher (synchronous, not a hook)
    if self._outbox_notifier and self._collected_events:
        await self._outbox_notifier(self._collected_events)
    self._collected_events.clear()
    # Post-commit hooks are run separately via run_post_commit_hooks()

async def run_post_commit_hooks(self) -> None:
    """Run post-commit side-effects (cache invalidation etc).
    Errors are caught and logged — hook failure MUST NOT propagate to the caller.
    """
    for hook in self._post_commit_hooks:
        try:
            await hook
        except Exception as exc:
            logger.warning("post_commit_hook_failed", error=str(exc))
    self._post_commit_hooks.clear()
```

Update `BaseKafkaConsumer._handle_message` (in `libs/messaging/`) to call
`uow.run_post_commit_hooks()` after `uow.commit()` if the method exists (duck-typing,
keep backward compatibility).

**Note**: If the base class change in `libs/messaging` is impractical in this wave, an
acceptable alternative is to call `run_post_commit_hooks()` from within the consumers'
`process_message` override after all writes are done. Document the chosen approach.

**Acceptance criteria**:
- [ ] Cache hook failure no longer propagates out of `commit()`
- [ ] Hook errors logged as warnings, not raised
- [ ] DB commit still raises on DB failure

---

#### T-E-1-03: Remove Vestigial `collect_event` / `_events` Path

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `services/market-data/src/market_data/infrastructure/db/uow.py`

**What to build**: The `collect_event` / `_collected_events` / `_outbox_notifier` path was
the old way of routing events to the outbox dispatcher. All three S3 consumers now use
`uow.outbox_events.create()` directly (DB-backed outbox). The in-memory path is vestigial.

Verify no consumer still calls `collect_event` (grep the codebase). If confirmed unused,
remove `collect_event()`, `collected_events` property, `_collected_events` list, and the
`outbox_notifier` callback from the UoW. Update the constructor accordingly.

If the notifier is still needed by the outbox dispatcher (for immediate dispatch signaling),
keep the notifier but have it triggered by the outbox repository write, not by `collect_event`.

**Acceptance criteria**:
- [ ] `collect_event` removed or clearly deprecated with a warning
- [ ] No consumer calls `collect_event`
- [ ] `outbox_notifier` either removed or clearly documented as "signal after outbox DB write"

---

#### T-E-1-04: Tests for Wave E-1 Fixes

**Type**: test
**depends_on**: [T-E-1-01, T-E-1-02]
**blocks**: none
**Target files**: `services/market-data/tests/unit/` (existing or new test file for UoW)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_uow_session_closed_when_rollback_raises` | Sessions closed in finally even if rollback raises | unit |
| `test_post_commit_hook_failure_does_not_propagate` | Hook exception logged, not raised | unit |
| `test_post_commit_hook_runs_after_successful_commit` | Hook called after DB commit succeeds | unit |

**Acceptance criteria**:
- [ ] 3 new tests pass
- [ ] `pytest services/market-data/tests/ -m unit` — 333+ pass

---

#### Validation Gate (Wave E-1)

- [ ] `pytest services/market-data/tests/ -m unit` — 333+ pass
- [ ] `ruff check` + `mypy` clean

---

### Wave E-2: Add `description` Field to `InstrumentCreated`

**Goal**: Populate the `description` field of `InstrumentCreated` so S7's definition-embedding
step actually fires (F-DP-004). The canonical Avro schema already has the field; the Python
dataclass is missing it.
**Depends on**: Wave A-1
**Estimated effort**: 30 min
**Architecture layer**: domain + infrastructure

#### T-E-2-01: Add `description: str | None = None` to `InstrumentCreated`

**Type**: impl
**depends_on**: none
**blocks**: [T-E-2-02, T-E-2-03]
**Target files**: `services/market-data/src/market_data/domain/events.py`

**What to build**: Add the optional `description` field to the `InstrumentCreated` frozen
dataclass. The canonical Avro schema already declares it as `["null", "string"], default null`:

```python
@dataclass(frozen=True)
class InstrumentCreated:
    ...
    description: str | None = None   # NEW — for S7 entity definition embedding
```

Also add `field_name: "description"` to the `to_dict` / `event_to_outbox_payload` method
if one exists (ensure it is included in the serialized payload).

**Acceptance criteria**:
- [ ] `description: str | None = None` field added
- [ ] Field included in serialized payload (Avro dict)

---

#### T-E-2-02: Populate `description` from `FundamentalsConsumer`

**Type**: impl
**depends_on**: [T-E-2-01]
**blocks**: [T-E-2-03]
**Target files**: `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py`

**What to build**: In `FundamentalsConsumer`, when constructing an `InstrumentCreated` event
(after parsing the EODHD fundamentals payload), extract the company `Description` field and
pass it to the event:

```python
# When building InstrumentCreated from EODHD General section:
description = general_section.get("Description") or None
instrument_created = InstrumentCreated(
    ...
    description=description,
)
```

**Acceptance criteria**:
- [ ] `description` populated from fundamentals when available
- [ ] `None` when description is absent (no fallback to empty string)

---

#### T-E-2-03: Tests for `description` Field

**Type**: test
**depends_on**: [T-E-2-01, T-E-2-02]
**blocks**: none
**Target files**: `services/market-data/tests/unit/test_domain_events.py`, `services/market-data/tests/unit/test_fundamentals_consumer.py`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_instrument_created_has_description_field` | Description field present in dataclass + defaults to None | unit |
| `test_instrument_created_description_in_avro_dict` | description included in serialized payload | unit |
| `test_fundamentals_consumer_populates_description` | EODHD Description → InstrumentCreated.description | unit |
| `test_fundamentals_consumer_description_none_when_absent` | Missing Description → None (not empty string) | unit |

**Acceptance criteria**:
- [ ] 4 new tests pass

---

#### Validation Gate (Wave E-2)

- [ ] `pytest services/market-data/tests/ -m unit` — 335+ pass
- [ ] `ruff check` + `mypy` clean
- [ ] Avro schema field `description` already present in `infra/kafka/schemas/market.instrument.created.avsc` (verify, no schema change needed)

---

---

## Sub-plan F: Production Readiness (1 wave)

### Wave F-1: Credential Placeholders + Structured Warnings + Request Bounds

**Goal**: Replace hardcoded default credentials with `<CHANGE_ME>` placeholders across all
service env example files, add structlog warnings for missing secrets, and add input bounds.
**Depends on**: none (independent)
**Estimated effort**: 45 min
**Architecture layer**: config

#### T-F-1-01: Replace Hardcoded Default Credentials in All `docker.env.example` Files

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**: All `services/*/configs/docker.env.example` and `services/*/configs/dev.local.env.example`

**What to build**: Across all services, find every `.env.example` file that contains
hardcoded default credentials and replace with `<CHANGE_ME>` placeholders + production comment.

Credentials to replace:
- MinIO: `STORAGE_ACCESS_KEY=minioadmin` → `STORAGE_ACCESS_KEY=<CHANGE_ME>`
- MinIO: `STORAGE_SECRET_KEY=minioadmin` → `STORAGE_SECRET_KEY=<CHANGE_ME>`
- Internal tokens: `INTERNAL_SERVICE_TOKEN=` → add comment: `# Required in production — generate with: openssl rand -hex 32`
- Any other hardcoded credentials

Add a header comment to each affected file:
```
# PRODUCTION DEPLOYMENT NOTE:
# All <CHANGE_ME> values must be replaced with secrets from your secret manager
# (Docker Secrets, Vault, AWS SSM, etc.) before deploying to any non-local environment.
# Never commit real credentials to version control.
```

Dev local env examples may keep usable defaults (minioadmin is acceptable for local dev
only — but add a comment clarifying this is dev-only).

**Acceptance criteria**:
- [ ] All `docker.env.example` files: no `minioadmin` without a "dev only" comment or `<CHANGE_ME>`
- [ ] All services with `INTERNAL_SERVICE_TOKEN` have guidance comment
- [ ] Header comment added to each docker.env.example

---

#### T-F-1-02: Add `structlog` Warning for Missing Secrets in Config Validators

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `services/market-ingestion/src/market_ingestion/config.py`, `services/portfolio/src/portfolio/config.py`

**What to build**: In the pydantic-settings validator methods that currently call
`warnings.warn()` for missing secrets, also emit a structlog `warning`:

```python
import structlog as _structlog

@field_validator("internal_service_token")
@classmethod
def _warn_missing_internal_token(cls, v: str) -> str:
    if not v:
        import warnings
        warnings.warn(
            "INTERNAL_SERVICE_TOKEN is not set — all mutating API endpoints will return 401.",
            stacklevel=2,
        )
        # Also emit via structlog for visibility in structured log pipelines:
        _structlog.get_logger().warning(
            "internal_service_token_missing",
            impact="All mutating API endpoints will return 401 until token is configured",
        )
    return v
```

Apply same pattern to `eodhd_api_key = "demo"` validator in market-ingestion.

**Acceptance criteria**:
- [ ] structlog warning emitted alongside `warnings.warn` for missing tokens
- [ ] structlog warning emitted for demo EODHD key

---

#### T-F-1-03: Add `max_length` Bounds to Batch Endpoints in market-data

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `services/market-data/src/market_data/api/schemas/quotes.py`, `services/market-data/src/market_data/api/routers/quotes.py`, `services/market-data/src/market_data/api/routers/ohlcv.py`

**What to build**: Add cardinality bounds to prevent DoS amplification on batch list inputs:

```python
# schemas/quotes.py
class BatchQuoteRequest(BaseModel):
    instrument_ids: list[str] = Field(..., max_length=200, description="Max 200 instrument IDs per request")

# routers/quotes.py — GET /quotes/latest
instrument_ids: Annotated[list[str], Query(max_length=200)] = []

# routers/ohlcv.py — GET /ohlcv/bulk
instrument_ids: Annotated[list[str], Query(max_length=200)] = []
```

Add test for 201-item list → 422 validation error.

**Acceptance criteria**:
- [ ] All three batch endpoints enforce `max_length=200`
- [ ] 422 returned for lists exceeding the limit

---

#### T-F-1-04: Update PRODUCTION_READINESS.md (consolidate)

**Type**: docs
**depends_on**: [T-F-1-01, T-F-1-02, T-F-1-03]
**blocks**: none
**Target files**: `docs/PRODUCTION_READINESS.md`

**What to build**: Mark as completed the items added in Wave A-1 T-A-1-06 that are now
actually fixed by this wave (credential placeholders, structlog warnings, batch bounds).
Update "Last Updated" date.

**Acceptance criteria**:
- [ ] Fixed items marked done in PRODUCTION_READINESS.md
- [ ] New gaps (from QA report) remain as open items

---

#### Validation Gate (Wave F-1)

- [ ] `pytest services/market-data/tests/ -m unit` — 335+ pass (after F-1-03 test)
- [ ] `ruff check` + `mypy` clean on all changed services
- [ ] `grep -r "minioadmin" services/*/configs/docker.env.example` → returns only dev.local files with "dev only" comment

---

---

## Sub-plan G: Test Coverage Gaps (2 waves)

### Wave G-1: S1 Portfolio Test Coverage Gaps

**Goal**: Close the test gaps identified in F-QA-001 (no commit tracking), F-QA-002
(incomplete idempotency assertions), F-QA-003 (missing error path tests).
**Depends on**: Waves A-1, C-1, C-2
**Estimated effort**: 45 min
**Architecture layer**: tests

#### T-G-1-01: Fix `FakeUoW.commit()` in Transaction Tests to Track Calls

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**: `services/portfolio/tests/unit/test_use_cases_transaction.py`

**What to build**: The local `FakeUoW.commit()` in this test file is a no-op. Add
`commit_count` tracking and assert it was called exactly once per successful transaction:

```python
class FakeUoW:
    def __init__(self):
        ...
        self.commit_count = 0

    async def commit(self):
        self.commit_count += 1

# In test:
result = await use_case.execute(cmd)
assert uow.commit_count == 1
```

Or alternatively, switch to using the canonical `FakeUnitOfWork` from `fakes.py` which
already tracks `commit_count`.

**Acceptance criteria**:
- [ ] `commit_count` tracked in `FakeUoW`
- [ ] At least one test asserts `commit_count == 1`

---

#### T-G-1-02: Strengthen Idempotency Test Assertions

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**: `services/portfolio/tests/unit/test_use_cases_transaction.py`

**What to build**: Add outbox count and holdings-unchanged assertions to
`test_idempotency_same_key_twice_returns_first`:

```python
# After second (duplicate) call:
assert len(uow._outbox.saved) == 2  # only from first call, not doubled
assert holdings[0].quantity == first_call_quantity  # unchanged by duplicate
```

Also fix `FakeTransactionRepo.find_by_external_ref` to include `tenant_id` filter
(matching the canonical `fakes.py` implementation), preventing false-positive cross-tenant finds.

**Acceptance criteria**:
- [ ] Outbox count assertion added
- [ ] Holdings unchanged assertion added
- [ ] `tenant_id` filter added to local `find_by_external_ref`

---

#### T-G-1-03: Add Error Path Tests for `RecordTransactionUseCase`

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**: `services/portfolio/tests/unit/test_use_cases_transaction.py`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_inactive_tenant_raises_domain_error` | TenantInactiveError raised | unit |
| `test_inactive_user_raises_domain_error` | UserInactiveError raised | unit |
| `test_portfolio_not_found_raises_domain_error` | PortfolioNotFoundError raised | unit |
| `test_wrong_owner_raises_authorization_error` | AuthorizationError raised | unit |

**Acceptance criteria**:
- [ ] 4 new error path tests pass

---

#### T-G-1-04: Broaden S3 Domain Independence Guard in `test_domain_errors.py`

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**: `services/market-data/tests/unit/test_domain_errors.py`

**What to build**: Broaden `test_parse_error_is_pure_domain` to check against ALL
infrastructure modules, not just `"messaging"`:

```python
def test_parse_error_is_pure_domain():
    mro_modules = {cls.__module__ for cls in ParseError.__mro__}
    forbidden_prefixes = ("market_data.infrastructure", "messaging", "kafka", "confluent")
    for module in mro_modules:
        assert not any(module.startswith(p) for p in forbidden_prefixes), (
            f"ParseError inherits from infrastructure module: {module}"
        )
```

**Acceptance criteria**:
- [ ] Guard checks against all infrastructure prefixes

---

#### Validation Gate (Wave G-1)

- [ ] `pytest services/portfolio/tests/ -m unit` — 295+ pass
- [ ] `pytest services/market-data/tests/ -m unit` — 335+ pass

---

### Wave G-2: S2 Auth Test Coverage Gaps

**Goal**: Close the missing auth test coverage identified in F-QA-005/006/007/011/014.
**Depends on**: Wave D-1 (layer cleanup may affect test fixtures)
**Estimated effort**: 30 min
**Architecture layer**: tests

#### T-G-2-01: Add Missing Auth Tests for market-ingestion

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**: `services/market-ingestion/tests/api/test_routes.py`, `services/market-ingestion/tests/test_settings.py`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_policies_does_not_require_token` | GET /policies → 200 without token | unit |
| `test_metrics_does_not_require_token` | GET /metrics → 200 without token | unit |
| `test_trigger_empty_configured_token_returns_401` | Empty settings token → 401 regardless of header | unit |
| `test_trigger_with_empty_token_header_returns_401` | `X-Internal-Token: ""` → 401 | unit |
| `test_readyz_returns_503_when_storage_fails` | Storage check fails → 503 | unit |
| `test_settings_warns_on_empty_internal_token` | `pytest.warns(UserWarning)` for empty token | unit |

**Acceptance criteria**:
- [ ] All 6 new tests pass
- [ ] `pytest services/market-ingestion/tests/ -m unit` — 385+ pass

---

#### Validation Gate (Wave G-2)

- [ ] `pytest services/market-ingestion/tests/ -m unit` — 385+ pass
- [ ] `ruff check` clean

---

---

## Cross-Cutting Concerns

### Contract Changes
- `InstrumentCreated` dataclass gains `description: str | None = None` (additive, backward-compatible)
- Avro schema `market.instrument.created.avsc` already has `description` field — no schema change

### Migration Needs
- None (no new DB tables or columns)

### Event Flow Changes
- `InstrumentCreated` now optionally carries `description` — S7 consumers will start receiving it
- No topic name changes

### Configuration Changes
- New env var: `app.state.read_session_factory` / `write_session_factory` for market-ingestion lifespan
- All docker.env.example files updated with `<CHANGE_ME>` placeholders

### Documentation Updates
- `RULES.md`: R25 added
- `STANDARDS.md`: §17 added, §11 updated
- `HIGH_RISK_PATTERNS.md`: new HR entry
- `REVIEW_CHECKLIST.md`: new UoW checks
- `PRODUCTION_READINESS.md`: new gaps added
- All 4 skill files: STANDARDS.md pre-read added
- `services/portfolio/.claude-context.md`: new process topology
- `docs/services/portfolio.md`: instrument consumer extraction noted

---

## Risk Assessment

**Critical path**: A-1 → B-1 → D-1 (architecture changes in S2 touch `app.py` and `dependencies.py`)
**Highest risk**: Wave D-1 (S2 API layer refactoring — session factory setup in lifespan + lazy imports — risk of breaking existing tests)
**Rollback strategy**: Each wave is a focused commit. If D-1 breaks S2 tests, revert the `get_uow` change and keep the type annotation fix independently.
**Testing gaps**: Integration tests skipped (no infra). Wave D-1 and C-3 benefit most from E2E validation.

---

## Plan Summary

| Sub-plan | Waves | Tasks | Service(s) | Parallelizable after A-1 |
|----------|-------|-------|-----------|--------------------------|
| A: Documentation | 1 | 6 | Cross-cutting | — (runs first) |
| B: UoW Enforcement | 1 | 5 | S2 | Yes (with C, E, F, G) |
| C: Portfolio Fixes | 3 | 13 | S1 | C-1 ∥ B; C-2 ∥ B; C-3 after C-2 |
| D: market-ingestion Layer | 2 | 6 | S2 | After B-1 |
| E: market-data Reliability | 2 | 9 | S3 | Yes |
| F: Production Readiness | 1 | 4 | All | Yes |
| G: Test Coverage | 2 | 5 | S1/S2/S3 | After C-2, D-1 |
| **Total** | **12** | **48** | | |
