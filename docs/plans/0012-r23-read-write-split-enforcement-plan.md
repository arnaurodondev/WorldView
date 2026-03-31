# PLAN-0012: R23 Read/Write Database Session Split — Tests & Enforcement

**PRD**: N/A (Standards enforcement — R23, STANDARDS.md §15)
**Status**: in-progress
**Created**: 2026-03-31
**Updated**: 2026-03-31
**Author**: Claude (plan generation)

---

## Overview

Rule R23 requires every database-owning service to support dual database URLs
(`db_url` for writes, `db_url_read` for reads with automatic fallback). Only **2 of 8**
services are fully compliant:

| Service | Config | Dual Factory | Pool Tuning | Status |
|---------|:------:|:------------:|:-----------:|--------|
| S1 Portfolio | No | No | No | **Non-compliant** |
| S2 Market Ingestion | Yes | Yes | Yes | Compliant (R23) |
| S3 Market Data | Yes | Yes | Yes | **Compliant** |
| S4 Content Ingestion | Yes | Yes | Yes | **Compliant** |
| S5 Content Store | No | No | No | **Non-compliant** |
| S6 NLP Pipeline | No | No | No | **Non-compliant** |
| S7 Knowledge Graph | No (config) | Yes (code) | Yes | **Partial** |
| S10 Alert | No | No | No | **Non-compliant** |

**Reference implementation**: S4 Content Ingestion
(`services/content-ingestion/src/content_ingestion/infrastructure/db/session.py`)

### What R23 Compliance Requires

Per STANDARDS.md §15, every service with a database MUST:

1. **Config** — Settings class has:
   - `db_url: str` (write, required)
   - `db_url_read: str = ""` (read, optional — falls back to `db_url` when empty)
   - Pool sizing fields: `db_pool_size`, `db_max_overflow`, `db_pool_size_read`, `db_max_overflow_read`

2. **Session factory** — `_build_factories(settings)` returns `(engine, write_factory, read_factory)`:
   - Write engine: `pool_size=10, max_overflow=20, pool_pre_ping=True`
   - Read engine: `pool_size=20, max_overflow=30, pool_pre_ping=True` (higher for read-heavy)
   - When `db_url_read` is empty → `read_factory = write_factory` (zero-cost fallback)

3. **Wiring** — Both factories are passed to UoW / consumers / workers:
   - API routes: write factory for mutations, read factory for queries
   - Consumers: write factory (they mutate state)
   - Workers: write factory (they mutate state)
   - Dispatcher: write factory (polls outbox)

### Out of Scope

- **R27 (ReadOnlyUnitOfWork)** — A separate enhancement that builds on R23. S2 is R23-compliant
  but lacks ReadOnlyUoW. This plan does NOT add ReadOnlyUoW to any service.
- **R26 (Explicit commit in UoW)** — Covered separately; not tested here.
- **Field naming standardization** — Existing compliant services use different field names
  (`db_url` vs `database_url` vs `read_replica_url`). This plan standardizes on `db_url` /
  `db_url_read` for new implementations but does NOT rename existing compliant fields.

---

## Dependency Graph

```
Sub-Plan A (Architecture Tests)
  Wave A-1 (test_database_session_patterns.py) ──┐
                                                  │
Sub-Plan B (Service Fixes)                        │
  Wave B-1 (S1 Portfolio)      ← depends on A-1 ─┤
  Wave B-2 (S5 + S10)         ← depends on A-1 ─┤  ← all independent
  Wave B-3 (S6 + S7)          ← depends on A-1 ─┘
```

**Critical path**: A-1 → B-1 (S1 Portfolio is the most complex fix)
**Parallelizable**: B-1, B-2, B-3 are fully independent after A-1

---

## Task Tracking

| Task ID | Title | Wave | Status | Depends On |
|---------|-------|------|--------|------------|
| T-A-1-01 | Create `test_database_session_patterns.py` — R23 config checks | A-1 | done | none |
| T-A-1-02 | Create `test_database_session_patterns.py` — dual factory checks | A-1 | done | none |
| T-A-1-03 | Create `test_database_session_patterns.py` — pool sizing checks | A-1 | done | none |
| T-A-1-04 | Add baseline for non-compliant services | A-1 | done | T-A-1-01 |
| T-B-1-01 | S1: add `db_url_read` + pool fields to config.py | B-1 | done | T-A-1-01 |
| T-B-1-02 | S1: rewrite session.py with dual factory | B-1 | done | T-B-1-01 |
| T-B-1-03 | S1: update app.py wiring to pass both factories | B-1 | done | T-B-1-02 |
| T-B-1-04 | S1: update consumer + dispatcher to accept both factories | B-1 | done | T-B-1-02 |
| T-B-1-05 | S1: ruff + mypy + unit tests | B-1 | done | T-B-1-03, T-B-1-04 |
| T-B-2-01 | S5: add `db_url_read` + pool fields to config.py | B-2 | pending | T-A-1-01 |
| T-B-2-02 | S5: rewrite session.py with dual factory | B-2 | pending | T-B-2-01 |
| T-B-2-03 | S5: update app.py wiring | B-2 | pending | T-B-2-02 |
| T-B-2-04 | S10: add `db_url_read` + pool fields to config.py | B-2 | pending | T-A-1-01 |
| T-B-2-05 | S10: rewrite session.py with dual factory | B-2 | pending | T-B-2-04 |
| T-B-2-06 | S10: update app.py wiring | B-2 | pending | T-B-2-05 |
| T-B-2-07 | S5 + S10: ruff + mypy + unit tests | B-2 | pending | T-B-2-03, T-B-2-06 |
| T-B-3-01 | S7: add `db_url_read` to config.py | B-3 | pending | T-A-1-01 |
| T-B-3-02 | S7: wire config-driven read URL into existing dual factory | B-3 | pending | T-B-3-01 |
| T-B-3-03 | S6: add `db_url_read` + pool fields to config.py | B-3 | pending | T-A-1-01 |
| T-B-3-04 | S6: rewrite session factories with dual pattern (both DBs) | B-3 | pending | T-B-3-03 |
| T-B-3-05 | S6: update app.py wiring | B-3 | pending | T-B-3-04 |
| T-B-3-06 | S6 + S7: ruff + mypy + unit tests | B-3 | pending | T-B-3-02, T-B-3-05 |

---

## Sub-Plan A: Architecture Tests for R23

### Wave A-1: `test_database_session_patterns.py` ✅

**Goal**: Create an architecture test module that enforces R23 compliance across all services
with database access. Uses AST scanning of `config.py` and `session.py` to verify the dual
factory pattern.
**Depends on**: none
**Estimated effort**: 45–60 min
**Status**: **DONE** — 2026-03-31 · 11 tests pass · ruff + mypy clean
**Architecture layer**: test

#### T-A-1-01: R23 config field checks

**Type**: test
**depends_on**: none
**blocks**: [T-A-1-04, T-B-1-01, T-B-2-01, T-B-2-04, T-B-3-01, T-B-3-03]
**Target files**: `tests/architecture/test_database_session_patterns.py`
**PRD reference**: STANDARDS.md §15, RULES.md R23

**What to build**:
Test class `TestR23ConfigFields` that verifies every database-owning service's Settings class
contains both a write URL field and an optional read URL field.

**Logic & Behavior**:
- Determine which services have a database: check for `infrastructure/db/` directory
- For each DB-owning service, parse `config.py` with AST
- Find the `Settings` class definition
- Scan its body for field assignments
- Check for a read-URL field: any field whose name contains `read` AND (`url` or `replica` or `dsn`)
  - Accepts: `db_url_read`, `database_url_read`, `read_replica_url`
- Check the read-URL field has a default value (empty string or None) — it must be optional
- Check for pool sizing fields: at least `pool_size` and `max_overflow` fields (or pattern matches)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_settings_has_write_db_url | Every DB-owning service Settings has a database URL field | unit |
| test_settings_has_read_db_url | Every DB-owning service Settings has an optional read-replica URL field | unit |
| test_read_url_has_default | The read-replica URL field has a default (empty or None) | unit |
| test_settings_has_pool_size_fields | Settings has pool sizing configuration fields | unit |

- Minimum test count: 4
- Edge cases: S6 with two databases (nlp_db + intelligence_db), services without DB (S8, S9)

**Acceptance criteria**:
- [ ] 4 tests in `TestR23ConfigFields`
- [ ] Compliant services (S2, S3, S4) pass all checks
- [ ] Non-compliant services flagged with clear violation messages
- [ ] S6 checked for BOTH database URLs having read variants

---

#### T-A-1-02: Dual factory function checks

**Type**: test
**depends_on**: none
**blocks**: [T-A-1-04]
**Target files**: `tests/architecture/test_database_session_patterns.py`
**PRD reference**: STANDARDS.md §15.1

**What to build**:
Test class `TestR23DualFactory` that verifies every DB-owning service's session module
creates two session factories (write + read).

**Logic & Behavior**:
- For each DB-owning service, find `infrastructure/db/session.py`
- Parse with AST and look for:
  1. A function that returns a tuple containing multiple `async_sessionmaker` instances
     (detect by return annotation or by counting `async_sessionmaker(...)` calls)
  2. Conditional logic comparing read URL to write URL (the fallback pattern):
     `if read_url == settings.db_url: read_factory = write_factory`
  3. At least two `create_async_engine(...)` calls (or conditional for fallback)
- Alternative detection: count `create_async_engine` calls — compliant services have ≥2
  (one write, one read), or 1 with conditional fallback logic

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_session_module_exists | Every DB-owning service has `infrastructure/db/session.py` | unit |
| test_dual_engine_creation | session.py calls `create_async_engine` at least twice (or has fallback logic) | unit |
| test_factory_function_returns_dual | Factory function signature/body suggests dual factory return | unit |

- Minimum test count: 3

**Acceptance criteria**:
- [ ] 3 tests in `TestR23DualFactory`
- [ ] Compliant services pass
- [ ] Non-compliant services flagged

---

#### T-A-1-03: Pool sizing checks

**Type**: test
**depends_on**: none
**blocks**: [T-A-1-04]
**Target files**: `tests/architecture/test_database_session_patterns.py`
**PRD reference**: STANDARDS.md §15, §16

**What to build**:
Test class `TestR23PoolSizing` that verifies session factory functions use `pool_pre_ping=True`
and configure explicit `pool_size` / `max_overflow` values.

**Logic & Behavior**:
- For each DB-owning service, parse `infrastructure/db/session.py`
- Find all `create_async_engine(...)` calls
- For each call, check keyword arguments include:
  - `pool_pre_ping=True` (required for connection health)
  - `pool_size=<any_int>` (required — no default reliance)
  - `max_overflow=<any_int>` (required)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_pool_pre_ping_enabled | Every `create_async_engine` call has `pool_pre_ping=True` | unit |
| test_explicit_pool_size | Every `create_async_engine` call specifies `pool_size` | unit |
| test_explicit_max_overflow | Every `create_async_engine` call specifies `max_overflow` | unit |

- Minimum test count: 3

**Acceptance criteria**:
- [ ] 3 tests in `TestR23PoolSizing`
- [ ] Non-compliant services flagged for missing pool parameters

---

#### T-A-1-04: Baseline for non-compliant services

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**: `tests/architecture/test_database_session_patterns.py`
**PRD reference**: N/A

**What to build**:
A `R23_BASELINE` constant that lists known non-compliant services so the tests pass while
services are being fixed in Sub-Plan B. Same pattern as PLAN-0011's `TOPOLOGY_BASELINE`.

```python
R23_BASELINE: dict[tuple[str, str], str] = {
    ("portfolio", "R23-CONFIG-READ-URL"): "Fix in PLAN-0012 Wave B-1",
    ("portfolio", "R23-DUAL-FACTORY"): "Fix in PLAN-0012 Wave B-1",
    ("portfolio", "R23-POOL-SIZING"): "Fix in PLAN-0012 Wave B-1",
    ("content-store", "R23-CONFIG-READ-URL"): "Fix in PLAN-0012 Wave B-2",
    # ... etc for S5, S6, S7, S10
}
```

- Baselined violations print as warnings, not failures
- When a service is fixed and removed from baseline, stale entries warn about cleanup

**Acceptance criteria**:
- [ ] All non-compliant services baselined
- [ ] `pytest tests/architecture/test_database_session_patterns.py -v` — all green
- [ ] Warnings printed for baselined violations

#### Pre-read (agent must read before starting)
- `tests/architecture/_utils.py` — helper functions
- `tests/architecture/test_config_patterns.py` — existing config test patterns
- `services/content-ingestion/src/content_ingestion/infrastructure/db/session.py` — reference
- `services/content-ingestion/src/content_ingestion/config.py` — reference config
- `services/portfolio/src/portfolio/infrastructure/db/session.py` — non-compliant example
- `services/portfolio/src/portfolio/config.py` — non-compliant example

#### Validation Gate
- [x] ruff check passes on new test file
- [x] mypy passes on `tests/architecture/`
- [x] All 10+ new tests pass (4 + 3 + 3 + baseline verification)
- [x] All existing architecture tests still pass
- [x] Compliant services (S2, S3, S4) pass all checks without baseline

#### Regression Guardrails
- BP-023: Ensure `uvx ruff format` sync before committing

---

## Sub-Plan B: Service Standardization

### Wave B-1: S1 Portfolio — Full R23 Compliance ✅

**Goal**: Add read/write split support to Portfolio, the most mature non-compliant service.
This service has the most complex wiring (UoW, repositories, consumers, dispatcher).
**Depends on**: Wave A-1
**Estimated effort**: 45–60 min
**Status**: **DONE** — 2026-03-31 · 290 unit tests pass · ruff + mypy clean · S1 removed from R23 baseline
**Architecture layer**: infrastructure + config

#### T-B-1-01: S1 config.py — add read URL + pool fields

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-B-1-02]
**Target files**: `services/portfolio/src/portfolio/config.py`
**PRD reference**: STANDARDS.md §15.2

**What to build**:
Add R23 configuration fields to the Portfolio Settings class. Follow the content-ingestion
reference pattern. The `env_prefix` for portfolio is `PORTFOLIO_`.

**Entities / Components**:
New fields to add to `Settings`:
- `db_url_read: str = ""` — optional read-replica URL, falls back to `database_url` when empty
- `db_pool_size: int = 10` — write pool size
- `db_max_overflow: int = 20` — write pool overflow
- `db_pool_size_read: int = 20` — read pool size (higher for read-heavy)
- `db_max_overflow_read: int = 30` — read pool overflow

**Important**: Portfolio currently uses `database_url` as the field name (not `db_url`).
Add the new field as `database_url_read: str = ""` to maintain naming consistency within
the service. The architecture test accepts any field containing "read" + "url/replica".

**Acceptance criteria**:
- [ ] `database_url_read` field with empty string default
- [ ] Pool sizing fields present
- [ ] Existing `database_url` field unchanged
- [ ] ruff + mypy clean

---

#### T-B-1-02: S1 session.py — dual factory

**Type**: impl
**depends_on**: [T-B-1-01]
**blocks**: [T-B-1-03, T-B-1-04]
**Target files**: `services/portfolio/src/portfolio/infrastructure/db/session.py`
**PRD reference**: STANDARDS.md §15.1

**What to build**:
Rewrite the session factory to support dual engines. Current implementation takes a raw URL
string and returns `(engine, factory)`. New implementation should take `Settings` and return
`(engine, write_factory, read_factory)`.

**Logic & Behavior**:
Follow the S4 reference pattern:
```python
def _build_factories(
    settings: Settings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession], async_sessionmaker[AsyncSession]]:
    write_engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    write_factory = async_sessionmaker(write_engine, expire_on_commit=False)

    read_url = settings.database_url_read or settings.database_url
    if read_url == settings.database_url:
        read_factory = write_factory
    else:
        read_engine = create_async_engine(
            read_url,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size_read,
            max_overflow=settings.db_max_overflow_read,
        )
        read_factory = async_sessionmaker(read_engine, expire_on_commit=False)

    return write_engine, write_factory, read_factory
```

Keep the old `create_session_factory()` as a backward-compatible wrapper that calls
`_build_factories()` and returns only `(engine, write_factory)`, to minimize downstream breakage.

**Acceptance criteria**:
- [ ] `_build_factories(settings)` returns `(engine, write_factory, read_factory)`
- [ ] `create_session_factory()` still works (backward compat)
- [ ] `pool_pre_ping=True` on all engines
- [ ] Explicit `pool_size` and `max_overflow` on all engines
- [ ] Fallback logic: when `database_url_read` empty, `read_factory = write_factory`

---

#### T-B-1-03: S1 app.py — wire both factories

**Type**: impl
**depends_on**: [T-B-1-02]
**blocks**: [T-B-1-05]
**Target files**: `services/portfolio/src/portfolio/app.py`
**PRD reference**: STANDARDS.md §15

**What to build**:
Update the app lifespan to call `_build_factories()` instead of `create_session_factory()`.
Store both `write_factory` and `read_factory` on `app.state`. Update FastAPI dependency
injection to provide both.

**Logic & Behavior**:
1. In lifespan: `engine, write_factory, read_factory = _build_factories(settings)`
2. Store on app.state: `app.state.write_factory = write_factory; app.state.read_factory = read_factory`
3. Update any `Depends()` that provide sessions to API routes
4. Existing code that uses `session_factory` should now use `write_factory`

**Acceptance criteria**:
- [ ] Both factories stored on `app.state`
- [ ] Engine disposed on shutdown
- [ ] API routes continue to work (using write_factory for now)
- [ ] ruff + mypy clean

---

#### T-B-1-04: S1 consumer + dispatcher — accept both factories

**Type**: impl
**depends_on**: [T-B-1-02]
**blocks**: [T-B-1-05]
**Target files**:
- `services/portfolio/src/portfolio/infrastructure/messaging/consumers/instrument_consumer_main.py`
- `services/portfolio/src/portfolio/infrastructure/messaging/outbox/dispatcher_main.py`

**What to build**:
Update the standalone entry points to call `_build_factories(settings)` and pass the
write factory to the consumer/dispatcher (both mutate state, so they use write factory).

**Logic & Behavior**:
- Consumer `_main.py`: `_, write_factory, _ = _build_factories(settings)` → pass `write_factory`
- Dispatcher `_main.py`: `_, write_factory, _ = _build_factories(settings)` → pass `write_factory`
- The `read_factory` is available for future read-only optimizations but not required now

**Acceptance criteria**:
- [ ] Both entry points use `_build_factories()`
- [ ] Write factory passed to consumer/dispatcher
- [ ] No functional change in behavior

---

#### T-B-1-05: S1 validation

**Type**: test
**depends_on**: [T-B-1-03, T-B-1-04]
**blocks**: none
**Target files**: none (validation only)

**What to build**:
Run full validation suite for Portfolio service.

**Acceptance criteria**:
- [ ] `uvx ruff check services/portfolio/src/ services/portfolio/tests/` — clean
- [ ] `mypy services/portfolio/src/ --config-file services/portfolio/mypy.ini` — clean
- [ ] `python -m pytest services/portfolio/tests/unit/ -v` — all pass
- [ ] `make test-arch` — S1 removed from R23 baseline

#### Pre-read (agent must read before starting)
- `services/portfolio/src/portfolio/config.py` — current config
- `services/portfolio/src/portfolio/infrastructure/db/session.py` — current session factory
- `services/portfolio/src/portfolio/app.py` — current wiring
- `services/portfolio/src/portfolio/infrastructure/messaging/outbox/dispatcher_main.py` — entry point
- `services/portfolio/src/portfolio/infrastructure/messaging/consumers/instrument_consumer_main.py` — entry point
- `services/content-ingestion/src/content_ingestion/infrastructure/db/session.py` — REFERENCE

#### Validation Gate
- [x] ruff + mypy clean for S1
- [x] Unit tests pass (290 tests)
- [x] `make test-arch` — S1 R23 violations cleared
- [x] Backward compatibility: `create_session_factory()` still callable

#### Regression Guardrails
- BP-023: Ensure `uvx ruff format` sync before committing
- BP-064: FastAPI 204 status code — don't change any API response codes during wiring

---

### Wave B-2: S5 Content Store + S10 Alert — R23 Compliance

**Goal**: Add read/write split support to two scaffolded services that share a similar
simple structure (single DB, no scheduler/worker, similar session patterns).
**Depends on**: Wave A-1
**Estimated effort**: 30–45 min
**Architecture layer**: infrastructure + config

#### T-B-2-01: S5 config.py — add read URL + pool fields

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-B-2-02]
**Target files**: `services/content-store/src/content_store/config.py`

**What to build**:
Add R23 fields. S5 uses `database_url` as field name. Add `database_url_read: str = ""`
and pool sizing fields.

**Acceptance criteria**:
- [ ] `database_url_read: str = ""` added
- [ ] Pool sizing fields added: `db_pool_size: int = 10`, `db_max_overflow: int = 20`,
      `db_pool_size_read: int = 20`, `db_max_overflow_read: int = 30`

---

#### T-B-2-02: S5 session.py — dual factory

**Type**: impl
**depends_on**: [T-B-2-01]
**blocks**: [T-B-2-03]
**Target files**: `services/content-store/src/content_store/infrastructure/db/session.py`

**What to build**:
Rewrite to `_build_factories(settings) -> (engine, write_factory, read_factory)` pattern.
S5's current factory has no `pool_pre_ping`, no pool sizing — add all of these.

Keep backward-compatible `create_session_factory()` wrapper.

**Acceptance criteria**:
- [ ] Dual factory with fallback logic
- [ ] `pool_pre_ping=True`, explicit `pool_size`/`max_overflow` on all engines
- [ ] Backward-compatible wrapper preserved

---

#### T-B-2-03: S5 app.py — wire both factories

**Type**: impl
**depends_on**: [T-B-2-02]
**blocks**: [T-B-2-07]
**Target files**: `services/content-store/src/content_store/app.py`

**What to build**:
Update lifespan to use `_build_factories()`. Store both factories on `app.state`.
The consumer currently receives `session_factory` — update to receive `write_factory`
(consumer mutates state via processed_events table and outbox writes).

**Acceptance criteria**:
- [ ] Both factories on `app.state`
- [ ] Consumer receives write_factory
- [ ] App starts and serves health endpoints

---

#### T-B-2-04: S10 config.py — add read URL + pool fields

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-B-2-05]
**Target files**: `services/alert/src/alert/config.py`

**What to build**:
Same pattern as T-B-2-01. S10 uses `database_url`. Add `database_url_read` and pool fields.

**Acceptance criteria**:
- [ ] `database_url_read: str = ""` added
- [ ] Pool sizing fields added

---

#### T-B-2-05: S10 session.py — dual factory

**Type**: impl
**depends_on**: [T-B-2-04]
**blocks**: [T-B-2-06]
**Target files**: `services/alert/src/alert/infrastructure/db/session.py`

**What to build**:
Same as T-B-2-02. Rewrite to dual factory pattern with pool tuning.

**Acceptance criteria**:
- [ ] Dual factory with fallback, pool_pre_ping, explicit pool sizing

---

#### T-B-2-06: S10 app.py — wire both factories

**Type**: impl
**depends_on**: [T-B-2-05]
**blocks**: [T-B-2-07]
**Target files**: `services/alert/src/alert/app.py`

**What to build**:
Update lifespan to use `_build_factories()`. Store both factories on `app.state`.

**Acceptance criteria**:
- [ ] Both factories on `app.state`
- [ ] App starts and serves health endpoints

---

#### T-B-2-07: S5 + S10 validation

**Type**: test
**depends_on**: [T-B-2-03, T-B-2-06]
**blocks**: none

**Acceptance criteria**:
- [ ] ruff + mypy clean for both S5 and S10
- [ ] Unit tests pass for both services
- [ ] `make test-arch` — S5 and S10 removed from R23 baseline

#### Pre-read (agent must read before starting)
- `services/content-store/src/content_store/config.py`
- `services/content-store/src/content_store/infrastructure/db/session.py`
- `services/content-store/src/content_store/app.py`
- `services/alert/src/alert/config.py`
- `services/alert/src/alert/infrastructure/db/session.py`
- `services/alert/src/alert/app.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/db/session.py` — REFERENCE

#### Validation Gate
- [ ] ruff + mypy clean for S5 and S10
- [ ] Unit tests pass
- [ ] `make test-arch` — S5 + S10 R23 violations cleared

#### Regression Guardrails
- BP-023: Ensure `uvx ruff format` sync before committing

---

### Wave B-3: S6 NLP Pipeline + S7 Knowledge Graph — R23 Compliance

**Goal**: Add R23 support to the two intelligence-database services. S6 is the most complex
because it has TWO databases (nlp_db + intelligence_db). S7 already has dual factories in code
but needs the config field wired.
**Depends on**: Wave A-1
**Estimated effort**: 45–60 min
**Architecture layer**: infrastructure + config

#### T-B-3-01: S7 config.py — add `db_url_read`

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-B-3-02]
**Target files**: `services/knowledge-graph/src/knowledge_graph/config.py`

**What to build**:
S7 already has dual factory functions in session.py but the config has no `database_url_read`
field. Add it and wire it into the existing factory function. S7 uses `database_url` for
intelligence_db (it doesn't own its own DB — it uses intelligence_db owned by intelligence-migrations).

Add:
- `database_url_read: str = ""` — optional read-replica for intelligence_db
- Pool sizing fields if not already present

**Acceptance criteria**:
- [ ] `database_url_read: str = ""` added to Settings
- [ ] Pool fields present

---

#### T-B-3-02: S7 session.py — wire config-driven read URL

**Type**: impl
**depends_on**: [T-B-3-01]
**blocks**: [T-B-3-06]
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/session.py`

**What to build**:
S7 already has `create_intelligence_session_factory()` and `create_readonly_session_factory()`.
Update these to read the read-replica URL from config instead of using hardcoded dual factories.
Apply the standard fallback pattern: when `database_url_read` is empty, the readonly factory
falls back to the write engine.

Ensure `pool_pre_ping=True` and explicit pool sizing on all engines.

**Acceptance criteria**:
- [ ] Read factory uses `settings.database_url_read` with fallback
- [ ] `pool_pre_ping=True` on all engines
- [ ] Explicit pool sizing

---

#### T-B-3-03: S6 config.py — add read URLs for both databases

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-B-3-04]
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/config.py`

**What to build**:
S6 has TWO databases:
1. `database_url` — owned nlp_db (NLP processing state)
2. `intelligence_database_url` — foreign intelligence_db (shared with S7)

Add read-replica fields for BOTH:
- `database_url_read: str = ""` — read-replica for nlp_db
- `intelligence_database_url_read: str = ""` — read-replica for intelligence_db
- Pool sizing fields for each

**Acceptance criteria**:
- [ ] Both read-replica URL fields added with empty defaults
- [ ] Pool sizing fields for both databases

---

#### T-B-3-04: S6 session factories — dual pattern for both DBs

**Type**: impl
**depends_on**: [T-B-3-03]
**blocks**: [T-B-3-05]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/session.py` (if exists)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/session.py` (if exists)

**What to build**:
Apply the dual factory pattern to BOTH session factory modules. Each should accept Settings
and return `(engine, write_factory, read_factory)`.

For nlp_db: `_build_nlp_factories(settings)` → uses `database_url` / `database_url_read`
For intelligence_db: `_build_intelligence_factories(settings)` → uses `intelligence_database_url` / `intelligence_database_url_read`

Both follow the standard fallback pattern.

**Acceptance criteria**:
- [ ] Both session modules return dual factories
- [ ] Fallback logic for both
- [ ] `pool_pre_ping=True` and explicit pool sizing on all engines

---

#### T-B-3-05: S6 app.py — wire both factory pairs

**Type**: impl
**depends_on**: [T-B-3-04]
**blocks**: [T-B-3-06]
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/app.py`

**What to build**:
Update lifespan to use dual factories for both databases. Store all four factories on app.state:
- `nlp_write_factory`, `nlp_read_factory`
- `intel_write_factory`, `intel_read_factory`

Consumers currently receive single factories — update to receive write factories.

**Acceptance criteria**:
- [ ] Four factories on app.state
- [ ] Consumers receive write factories
- [ ] Both engines disposed on shutdown

---

#### T-B-3-06: S6 + S7 validation

**Type**: test
**depends_on**: [T-B-3-02, T-B-3-05]
**blocks**: none

**Acceptance criteria**:
- [ ] ruff + mypy clean for both S6 and S7
- [ ] Unit tests pass for both services
- [ ] `make test-arch` — S6 + S7 removed from R23 baseline, baseline is now empty

#### Pre-read (agent must read before starting)
- `services/knowledge-graph/src/knowledge_graph/config.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/session.py`
- `services/nlp-pipeline/src/nlp_pipeline/config.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/` (or wherever session factory lives)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/`
- `services/nlp-pipeline/src/nlp_pipeline/app.py`

#### Validation Gate
- [ ] ruff + mypy clean for S6 and S7
- [ ] Unit tests pass
- [ ] `make test-arch` — R23 baseline now **empty** (all services compliant)
- [ ] Architecture test `test_database_session_patterns.py` passes with NO baselines remaining

#### Regression Guardrails
- BP-023: Ensure `uvx ruff format` sync before committing
- S6 multi-database: ensure each database's engine is created and disposed independently

---

## Cross-Cutting Concerns

### Contract changes
- **None** — no Avro schemas, API contracts, or event semantics change

### Migration needs
- **None** — no database schema changes (only session factory code changes)

### Event flow changes
- **None** — Kafka topics and events are unaffected

### Configuration changes
- **New env vars** (all optional with defaults):
  - `PORTFOLIO_DATABASE_URL_READ`, `PORTFOLIO_DB_POOL_SIZE`, etc.
  - `CONTENT_STORE_DATABASE_URL_READ`, pool fields
  - `ALERT_DATABASE_URL_READ`, pool fields
  - `NLP_PIPELINE_DATABASE_URL_READ`, `NLP_PIPELINE_INTELLIGENCE_DATABASE_URL_READ`, pool fields
  - `KNOWLEDGE_GRAPH_DATABASE_URL_READ`, pool fields
- All have empty/zero defaults → zero-cost deployment (no config changes needed to deploy)
- `configs/dev.local.env.example` should be updated with commented-out examples

### Documentation updates
- Per-service `.claude-context.md` files should note R23 compliance after each wave
- No STANDARDS.md changes needed (§15 already documents the standard)

---

## Risk Assessment

### Critical path
**A-1 → any B wave** — The architecture test must exist before service fixes, so we can
verify compliance as we go.

### Highest risk: Wave B-3 (S6 NLP Pipeline)
S6 has TWO databases with separate session factory modules. Wiring four factories into
`app.py` is more complex than the single-DB pattern. Mitigation: read S6's current
`app.py` carefully to understand how it initializes both database connections.

### Rollback strategy
- All changes are additive (new config fields with defaults, new factory functions with
  backward-compatible wrappers)
- If a wave causes issues, reverting its commit restores the single-factory behavior
- The `create_session_factory()` backward-compat wrapper means existing tests don't break

### Testing gaps
- **Integration testing**: We cannot verify read-replica routing without a real Postgres
  replica. Unit tests can only verify that dual factories are created and the fallback
  logic works (when `db_url_read` is empty, read_factory == write_factory).
- **Mitigation**: The architecture tests verify structural compliance. Runtime behavior
  is tested via the fallback path (which is what dev/CI environments use).

### Effort estimate
| Sub-Plan | Waves | Estimated Effort |
|----------|-------|-----------------|
| A (Architecture Tests) | 1 | 45–60 min |
| B (Service Fixes) | 3 | 2–3 hours |
| **Total** | **4** | **~3–4 hours** |
