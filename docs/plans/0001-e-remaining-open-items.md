---
id: PLAN-0001-E-R1
prd: QA-CROSS-002
title: "S1+S2+S3 Remaining Open Items — Architecture + Security + Consistency Decisions"
status: in-progress
created: 2026-03-28
updated: 2026-03-29
waves_done: 5
plans: 1
waves: 6
tasks: 18
---

# PLAN-0001-E-R1: Remaining Open Items from QA Cross-Service Review

## Overview

**Source**: QA run 2026-03-28 on `feat/content-ingestion-wave-a1` (PLAN-0001-E)
**Goal**: Resolve 6 open issues that were deferred from PLAN-0001-E because they required architectural decisions, cross-service coordination, or scope agreement.
**Total Scope**: 1 plan, 6 waves (one per open item), 18 tasks.
**Decision required before implementation**: Waves 4–6 need owner direction (see decision tables).

---

## Summary of Open Items

| ID | Severity | Service | Issue | Decision Needed |
|----|----------|---------|-------|----------------|
| QA-006 | MAJOR | portfolio | UoW double-commit in watchlist use cases | Which commit pattern to standardize? |
| QA-012 | MAJOR | portfolio | `record_transaction` TOCTOU idempotency race | Apply BP-035 or add SELECT-FOR-UPDATE? |
| QA-013 | MAJOR | market-data | API routers directly import infrastructure layer | Refactoring scope |
| QA-016 | MAJOR | portfolio ↔ market-data | Topic name mismatch: S3 publishes to wrong topic | Coordination needed |
| QA-017 | MAJOR | market-ingestion | `ParseError` inherits from messaging lib in domain layer | Architecture boundary |
| QA-018 | MAJOR | market-ingestion | Mutating API endpoints have no authentication | Security policy decision |

---

## Wave 1: QA-012 — `record_transaction` TOCTOU Idempotency Race (portfolio) ✅

**Priority**: HIGH — correctness bug, financial data
**Decision required**: None — BP-035 is the canonical fix
**Status**: **DONE** — 2026-03-28 · 280 unit tests pass · ruff + mypy clean

### Context

`RecordTransactionUseCase.execute()` uses a 2-step idempotency check:

```python
# Current code (simplified)
async def execute(self, cmd):
    async with uow:
        if await uow.idempotency.exists(cmd.idempotency_key):
            return existing_transaction         # step 1: check
        # ... business logic ...
        await uow.idempotency.record(cmd.idempotency_key)   # step 3: record
        await uow.commit()
```

Race window: two concurrent POST requests with the same `idempotency_key` both pass `exists()` before either `record()` completes, resulting in two transactions being created.

### Fix (BP-035)

Replace the check/record pair with atomic `create_if_not_exists` at the start of the same UoW:

```python
async def execute(self, cmd):
    async with uow:
        is_new = await uow.idempotency.create_if_not_exists(cmd.idempotency_key)
        if not is_new:
            return await uow.transactions.get_by_idempotency_key(cmd.idempotency_key)
        # ... business logic ...
        await uow.commit()
```

The `IdempotencyRepository.create_if_not_exists(key)` method is already implemented (added in PLAN-0001-E for `InstrumentEventConsumer`).

### Tasks

| # | Task | File | Type |
|---|------|------|------|
| T01 | ✅ Add `create_if_not_exists` to `IdempotencyRepository` ABC — already present (UUID form); str overload not needed since UUID is validated before call | `application/ports/repositories.py` | Extend port |
| T02 | ✅ Implement `create_if_not_exists` in `SqlAlchemyIdempotencyRepository` — already implemented with RETURNING clause | `infrastructure/db/repositories/idempotency.py` | Implement |
| T03 | ✅ Update `RecordTransactionUseCase` to use atomic dedup | `application/use_cases/record_transaction.py` | Fix |
| T04 | ✅ Add BP-035 regression test: spy verifies `exists()`/`record()` are never called | `tests/unit/test_use_cases_transaction.py` | Test |

---

## Wave 2: QA-006 — UoW Double-Commit in Watchlist Use Cases (portfolio) ✅

**Priority**: MEDIUM — latent issue, silent in SQLAlchemy but fragile
**Decision required**: Choose between Option A and Option B (see below)
**Status**: **DONE** — 2026-03-29 · 281 unit tests pass · ruff + mypy clean

### Context

`WatchlistUseCase` variants call `await uow.commit()` explicitly inside `async with uow:`:

```python
async def execute(self, cmd):
    async with uow:                     # __aexit__ will call commit() on clean exit
        ...
        await uow.outbox.save(event)
        await uow.commit()              # EXPLICIT commit — already done
    # __aexit__ with no exception → calls uow.commit() AGAIN
```

SQLAlchemy `AsyncSession.commit()` on an already-committed session is a no-op, so this doesn't crash. But it's semantically wrong, and any future side-effects in `commit()` (e.g., outbox notifier, post-commit hooks) will be called twice.

### Options

**Option A — Remove explicit `await uow.commit()` from all use cases**
- Rely entirely on `UnitOfWork.__aexit__` to commit on clean exit
- Consistent with the context-manager pattern
- Risk: explicit `commit()` provides a clear "write boundary" — removing it makes the commit implicit/hidden
- Scope: affects ALL use cases that call explicit commit (need to audit all)

**Option B — Remove auto-commit from `UnitOfWork.__aexit__`**
- `__aexit__` only rolls back on exception; it never auto-commits
- Requires every use case to have explicit `await uow.commit()`
- More explicit/readable, consistent with explicit transaction management
- Risk: any use case missing `await uow.commit()` silently discards writes

**Option C — Make `commit()` idempotent**
- Track a `_committed` flag; second call is a no-op including side-effects
- Minimal change, preserves existing patterns
- Risk: masks the underlying design inconsistency

### Recommendation

**Option B** is most explicit and least surprising. Explicit `commit()` means no implicit side effects on `__aexit__`. All use cases already call `commit()` explicitly — just need to remove the auto-commit from `__aexit__`.

### Tasks

| # | Task | File | Type |
|---|------|------|------|
| T05 | ✅ Decision: **Option B** — remove auto-commit from `__aexit__` | Architecture | Decision |
| T06 | ✅ Implement Option B in `UnitOfWork.__aexit__` (both abstract + concrete); added `await uow.commit()` to all 11 mutating use cases + `InstrumentEventConsumer.process_message()` | `application/ports/unit_of_work.py`, `infrastructure/db/unit_of_work.py`, all use case files, consumer | Implement |
| T07 | ✅ Audited all use cases: 11 missing explicit commit fixed; `Add/RemoveWatchlistMemberUseCase` already had correct explicit commits | `application/use_cases/*.py` | Audit |
| T08 | ✅ Added QA-006 regression guard `test_aexit_does_not_auto_commit_on_clean_exit`; updated `test_commit_calls_on_commit_hook` assertion `>= 1` → `== 1`; added `commit_count` to `FakeUnitOfWork` | `tests/unit/test_unit_of_work.py`, `tests/unit/fakes.py` | Test |

---

## Wave 3: QA-013 — market-data API Routers Import Infrastructure Directly (market-data) ✅

**Priority**: MEDIUM — architecture violation, not runtime bug
**Decision required**: Scope of refactoring
**Status**: **DONE** — 2026-03-29 · 312 unit tests pass · ruff + mypy clean

### Context

Several `market-data` API routers access repositories or sessions directly from the infrastructure layer, bypassing the UoW and application-layer ports:

```python
# WRONG — direct infrastructure import in API layer
from market_data.infrastructure.db.repositories.quote_repo import PgQuoteRepository
from market_data.infrastructure.db.session import get_read_session

@router.get("/quotes/{instrument_id}")
async def get_quotes(..., session = Depends(get_read_session)):
    repo = PgQuoteRepository(session)
    return await repo.get(instrument_id)
```

This violates the hexagonal architecture: API → Application → Domain ← Infrastructure. The API layer should only call use cases or UoW, never import from `infrastructure/`.

### Options

**Option A — Minimal fix: route through UoW only**
- Replace `PgQuoteRepository(session)` with `uow.quotes_read`
- Keep session dependency injection but wrap in UoW
- Lower effort, maintains read/write split

**Option B — Full use case refactoring**
- Create explicit `QueryXxxUseCase` classes for each read operation
- API layer only calls use cases
- Higher effort, cleaner architecture

### Impacted Routers

Audit needed to identify all routers with direct infra imports. Key suspects:
- `api/routers/quotes.py`
- `api/routers/ohlcv.py`
- `api/routers/fundamentals.py`
- `api/routers/fundamental_metrics.py`

### Tasks

| # | Task | File | Type |
|---|------|------|------|
| T09 | ✅ Audit all routers for direct infrastructure imports | `api/routers/*.py` | Audit |
| T10 | ✅ Decision: Option B (full use cases) chosen by user | Architecture | Decision |
| T11 | ✅ All 6 routers refactored; 12 use case classes created; all router tests updated; 28 new use case unit tests | `api/routers/*.py`, `application/use_cases/` | Refactor |
| T12 | ✅ Added IG-LAYER-002 rule + QuoteCache allowlist exception | `scripts/import_guards/` | Enforce |

---

## Wave 4: QA-017 — `ParseError` Inherits from `messaging` Lib in Domain Layer (market-data) ✅

**Priority**: MEDIUM — architecture violation (R12: domain layer independence)
**Decision required**: None — fix is unambiguous, but needs verification of all usages
**Status**: **DONE** — 2026-03-28 · 276 unit tests pass · ruff + mypy (errors.py) clean
**Note**: Violation was in `market-data` (S3), not `market-ingestion` as stated in the summary table. The existing consumers already use `MalformedDataError` directly, so T14 (consumer mapping) was a no-op.

### Context

`market-ingestion/domain/errors.py` imports `FatalError` from `messaging.kafka.consumer.errors`:

```python
# WRONG — infrastructure lib imported in domain layer
from messaging.kafka.consumer.errors import FatalError  # type: ignore[import-untyped]

class ParseError(FatalError):
    """Raised when a fetched data file cannot be parsed."""
```

This violates R12: the domain layer must have zero infrastructure imports. The `messaging` lib is infrastructure.

### Fix

Define `ParseError` as a pure domain exception. Use composition/annotation in the consumer layer to map it to `FatalError` for the base consumer's error classification:

```python
# domain/errors.py — pure domain exception, no imports from infra libs
class ParseError(DomainError):
    """Raised when a fetched data file cannot be parsed."""
```

```python
# infrastructure/messaging/consumers/xxx_consumer.py — mapping in infra layer
from messaging.kafka.consumer.errors import FatalError
from market_ingestion.domain.errors import ParseError

try:
    ...
except ParseError as exc:
    raise FatalError(str(exc)) from exc
```

### Tasks

| # | Task | File | Type |
|---|------|------|------|
| T13 | ✅ Remove `FatalError` import from `domain/errors.py`; make `ParseError` inherit from `MarketDataError` | `domain/errors.py` | Fix |
| T14 | ✅ No consumer mapping needed — existing consumers raise `MalformedDataError` directly (N/A) | `infrastructure/messaging/consumers/*.py` | Fix |
| T15 | ✅ Updated tests: removed `FatalError` assertions, added `test_parse_error_is_pure_domain` (R12 guard) | `tests/unit/test_domain_errors.py` | Test |

---

## Wave 5: QA-016 — Topic Name Mismatch Between market-data (S3) and portfolio (S1) ✅

**Priority**: HIGH — potential silent message loss if consumers subscribe to wrong topic
**Decision required**: Verify actual topic names in use; align if mismatched
**Status**: **DONE** — 2026-03-29 · 333 market-data + 281 portfolio unit tests pass · ruff + mypy clean

### Context

**Claim from QA review**: market-data (`S3`) publishes instrument events to topic `market.events.v1`, but portfolio (`S1`) subscribes to `market.instrument.created` and `market.instrument.updated`.

If both sides use different topic names, portfolio never receives instrument sync events and its `InstrumentRef` cache is never populated.

### Investigation Required

Before implementing any fix, verify:

1. **What topic does market-data actually publish to?**
   - Check `services/market-data/src/market_data/infrastructure/messaging/` for outbox topic configuration
   - Check Avro schemas and outbox event configurations
   - Check `services/market-data/src/market_data/domain/events.py` `DomainEvent` subclasses

2. **What topics does portfolio subscribe to?**
   - Check `services/portfolio/src/portfolio/config.py`: `topic_instrument_created`, `topic_instrument_updated`
   - Check `InstrumentEventConsumer` config: `_TOPICS = [...]`

3. **Do the topic names match?**

### Fix (if mismatch confirmed)

**Option A** — Align market-data to publish to `market.instrument.created` and `market.instrument.updated`
**Option B** — Align portfolio to subscribe to `market.events.v1` and filter by event type
**Option C** — Add a bridge/router topic (not recommended — adds complexity)

### Tasks

| # | Task | File | Type |
|---|------|------|------|
| T16 | ✅ Investigated: market-data EVENT_TOPIC_MAP routed both events to `market.events.v1`; portfolio subscribed to `market.instrument.created/updated` | Code audit | Audit |
| T17 | ✅ Decision: Option A — align market-data to publish to `market.instrument.created` and `market.instrument.updated` | Architecture | Decision |
| T18 | ✅ Fixed EVENT_TOPIC_MAP; added event_to_outbox_payload() (entity_id, tuple→list); replaced collect_event with atomic outbox writes in all 3 consumers; added InstrumentUpdated on flag changes; updated canonical Avro schemas; updated portfolio consumer to Avro deserialization; added 15+ new unit tests | Both services | Fix |

---

## Wave 6: QA-018 — market-ingestion Mutating Endpoints Have No Authentication

**Priority**: HIGH — any process on the internal network can trigger ingestion tasks
**Decision required**: Auth mechanism (X-Internal-Token vs API key vs service mesh)

### Context

`market-ingestion` exposes unauthenticated mutating endpoints:
- `POST /api/v1/tasks` — trigger a new ingestion task
- `POST /api/v1/backfills` — trigger a backfill for a symbol/date range
- `POST /api/v1/admin/...` — admin operations

Any service (or attacker with internal network access) can arbitrarily schedule ingestion tasks or drain provider API budgets.

### Options

**Option A — X-Internal-Token (same pattern as portfolio S1)**
- Simple header-based auth with shared secret
- Add `MARKET_INGESTION_INTERNAL_SERVICE_TOKEN` env var
- Add `InternalAuthDep = Depends(verify_internal_token)` to mutating routes
- Matches existing portfolio pattern exactly

**Option B — mTLS via service mesh**
- More secure, no shared secrets to rotate
- Requires infrastructure changes (Istio/Linkerd)
- Out of scope for current phase

**Option C — No auth (intentional, document decision)**
- Acceptable if market-ingestion only accepts connections from within the cluster
- Must document explicitly as accepted risk

### Recommendation

**Option A** is the minimum viable security improvement. Consistent with portfolio S1. Implement now; migrate to mTLS later if infrastructure supports it.

### Tasks

| # | Task | File | Type |
|---|------|------|------|
| T19 | Add `MARKET_INGESTION_INTERNAL_SERVICE_TOKEN` to `config.py` with startup warning if unset | `src/market_ingestion/config.py` | Config |
| T20 | Add `verify_internal_token` dependency and `InternalAuthDep` alias | `src/market_ingestion/api/deps.py` | Auth |
| T21 | Apply `InternalAuthDep` to `POST /tasks`, `POST /backfills`, `POST /admin/*` | `src/market_ingestion/api/routes.py` | Security |
| T22 | Add unit tests for authenticated + unauthenticated requests | `tests/unit/api/` | Test |
| T23 | Add `MARKET_INGESTION_INTERNAL_SERVICE_TOKEN` to `.env.example` and docker-compose | `infra/` | Config |

---

## Decision Summary

Before `/implement` is invoked on any wave, the following decisions must be made:

| Wave | Question | Options | Recommendation |
|------|----------|---------|----------------|
| Wave 2 (QA-006) | UoW commit pattern | A: no explicit commit, B: no auto-commit in `__aexit__`, C: idempotent commit | **Option B** |
| Wave 3 (QA-013) | Router refactoring scope | A: route via UoW, B: full use cases | **Option B** (full use cases, chosen by user) ✅ |
| Wave 5 (QA-016) | Topic alignment direction | A: market-data → `market.instrument.*`, B: portfolio → `market.events.v1` | Investigate first |
| Wave 6 (QA-018) | Auth mechanism | A: X-Internal-Token, B: mTLS, C: no auth | **Option A** |

---

## Dependency Order

```
Wave 1 (QA-012) — independent, no blockers → implement now
Wave 2 (QA-006) — needs decision → then implement
Wave 3 (QA-013) — needs decision → then implement
Wave 4 (QA-017) — independent, fix is clear → implement now
Wave 5 (QA-016) — needs investigation first → investigate, then decide, then implement
Wave 6 (QA-018) — independent once decision made → implement once Option A confirmed
```

Waves 1 and 4 can be implemented immediately without further decisions.

---

## Validation Gates

Each wave must pass before marking complete:

1. `pytest tests/ -m "unit"` — all services pass
2. `ruff check` and `mypy` — zero errors
3. No new architecture violations (`python scripts/import_guards/check_import_guards.py`)
4. Update `TRACKING.md` QA column after wave completion
