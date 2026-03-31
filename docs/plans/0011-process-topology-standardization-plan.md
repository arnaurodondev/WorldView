# PLAN-0011: Process Topology Standardization & Architecture Test Enforcement

**PRD**: N/A (Standards enforcement initiative)
**Status**: in-progress
**Created**: 2026-03-31
**Updated**: 2026-03-31
**Author**: Claude (plan generation)

---

## Overview

Two concerns drive this plan:

1. **Architecture test gaps** — R22 (process separation) and STANDARDS.md §14 (process topology) are
   documented but have **no automated enforcement**. The existing `test_outbox_dispatcher_contracts.py`
   checks dispatcher class inheritance and `dispatcher_main.py` existence, but does not verify:
   - Directory naming conventions (singular vs plural)
   - Consumer standalone entry points
   - Scheduler/worker entry point conventions
   - No-background-tasks-in-lifespan rule
   - Docker Compose ↔ entry point alignment

2. **Cross-service inconsistencies** — Directory naming, entry point filenames, and process embedding
   vary across services:

   | Issue | Services Affected |
   |-------|-------------------|
   | `schedulers/` (plural) vs `scheduler/` (singular) | S2 vs S4, S7 |
   | `scheduler_process.py` vs `scheduler.py` naming | S4 vs S2 |
   | Dispatcher embedded in `app.py` lifespan (violates R22) | S5, S6, S7, S10 |
   | Consumers embedded in `app.py` lifespan (violates R22) | S5, S6, S7 |
   | Scheduler embedded in `app.py` lifespan (violates R22) | S7 |
   | Stale `infrastructure/outbox/` dir (alongside correct `messaging/outbox/`) | S4 |
   | `docker-compose.yml` has stale module paths | S1, S2 |
   | No compose containers for background processes | S5, S6, S7, S10 |

### Canonical Convention (to be enforced)

Per STANDARDS.md §1.1 and §14, extended by this plan:

```
infrastructure/
├── messaging/                  # ALL Kafka concerns
│   ├── outbox/
│   │   ├── dispatcher.py       # Class (extends BaseOutboxDispatcher)
│   │   └── dispatcher_main.py  # Standalone entry point
│   ├── consumers/              # Plural (multiple consumer classes per service)
│   │   ├── <type>_consumer.py  # Class (extends BaseKafkaConsumer)
│   │   └── <type>_consumer_main.py  # Standalone entry point
│   └── schemas/                # .avsc files only
├── scheduler/                  # Singular
│   ├── scheduler.py            # Class
│   └── scheduler_main.py      # Standalone entry point
└── workers/                    # Plural (horizontally scalable)
    ├── worker.py               # Class
    └── worker_main.py          # Standalone entry point
```

**Key rules**:
- `messaging/outbox/` — singular (one outbox per service)
- `messaging/consumers/` — plural (multiple consumer classes)
- `scheduler/` — singular (one scheduling concern)
- `workers/` — plural (scalable work pool)
- Every `*_main.py` gets its own Docker Compose container
- `app.py` lifespan MUST NOT start background loops (R22)

---

## Dependency Graph

```
Sub-Plan A (Tests & Standards)
  Wave A-1 (Standards docs) ─→ Wave A-2 (test_process_topology.py)
                               │
                               └─→ Wave A-3 (test_compose_alignment.py + enhance existing)

Sub-Plan B (Mature Services S1-S4) — can start after A-1
  Wave B-1 (S2 + S4 dir renames) ─→ Wave B-2 (docker-compose fixes + S1 cleanup)

Sub-Plan C (Scaffolded Services) — can start after A-2 + B-1
  Wave C-1 (S5 Content Store)
  Wave C-2 (S6 NLP Pipeline)        ← all independent of each other
  Wave C-3 (S7 Knowledge Graph)
  Wave C-4 (S10 Alert)
```

**Critical path**: A-1 → A-2 → B-1 → B-2 (mature services green)
**Parallelizable**: C-1 through C-4 are fully independent

---

## Task Tracking

| Task ID | Title | Wave | Status | Depends On |
|---------|-------|------|--------|------------|
| T-A-1-01 | Update STANDARDS.md §1.1 canonical layout | A-1 | done | none |
| T-A-1-02 | Update STANDARDS.md §14 entry point table | A-1 | done | none |
| T-A-1-03 | Add process topology helpers to `_utils.py` | A-1 | done | none |
| T-A-2-01 | Create `test_process_topology.py` — entry point conventions | A-2 | pending | T-A-1-03 |
| T-A-2-02 | Create `test_process_topology.py` — no-lifespan-embedding | A-2 | pending | T-A-1-03 |
| T-A-2-03 | Create `test_process_topology.py` — directory naming | A-2 | pending | T-A-1-03 |
| T-A-2-04 | Add baseline mechanism for scaffolded service violations | A-2 | pending | T-A-2-01 |
| T-A-3-01 | Create `test_compose_alignment.py` — entry points ↔ compose | A-3 | pending | T-A-2-01 |
| T-A-3-02 | Enhance `test_outbox_dispatcher_contracts.py` — canonical path check | A-3 | pending | T-A-1-01 |
| T-A-3-03 | Add `make test-arch` target to Makefile | A-3 | pending | none |
| T-B-1-01 | S2: rename `schedulers/` → `scheduler/`, update imports | B-1 | pending | T-A-1-01 |
| T-B-1-02 | S4: rename `scheduler_process.py` → `scheduler_main.py`, update imports | B-1 | pending | T-A-1-01 |
| T-B-1-03 | S4: remove stale `infrastructure/outbox/` directory | B-1 | pending | none |
| T-B-1-04 | S2 + S4: run ruff + mypy + unit tests | B-1 | pending | T-B-1-01, T-B-1-02 |
| T-B-2-01 | Fix `docker-compose.yml` stale module paths (S1, S2) | B-2 | pending | T-B-1-01 |
| T-B-2-02 | Add missing S4 scheduler + worker containers to `docker-compose.test.yml` | B-2 | pending | T-B-1-02 |
| T-B-2-03 | Verify all S1-S4 arch tests pass | B-2 | pending | T-B-2-01, T-B-2-02 |
| T-C-1-01 | S5: create `messaging/outbox/dispatcher_main.py` entry point | C-1 | pending | T-A-2-01 |
| T-C-1-02 | S5: create `messaging/consumers/article_consumer_main.py` entry point | C-1 | pending | T-A-2-01 |
| T-C-1-03 | S5: remove background tasks from `app.py` lifespan | C-1 | pending | T-C-1-01, T-C-1-02 |
| T-C-1-04 | S5: add compose containers + validate | C-1 | pending | T-C-1-03 |
| T-C-2-01 | S6: create `messaging/outbox/dispatcher_main.py` entry point | C-2 | pending | T-A-2-01 |
| T-C-2-02 | S6: create `messaging/consumers/{article,watchlist}_consumer_main.py` | C-2 | pending | T-A-2-01 |
| T-C-2-03 | S6: remove background tasks from `app.py` lifespan | C-2 | pending | T-C-2-01, T-C-2-02 |
| T-C-2-04 | S6: add compose containers + validate | C-2 | pending | T-C-2-03 |
| T-C-3-01 | S7: create `messaging/outbox/dispatcher_main.py` entry point | C-3 | pending | T-A-2-01 |
| T-C-3-02 | S7: create `messaging/consumers/*_consumer_main.py` entry points | C-3 | pending | T-A-2-01 |
| T-C-3-03 | S7: create `scheduler/scheduler_main.py` entry point | C-3 | pending | T-A-2-01 |
| T-C-3-04 | S7: remove background tasks from `app.py` lifespan | C-3 | pending | T-C-3-01, T-C-3-02, T-C-3-03 |
| T-C-3-05 | S7: add compose containers + validate | C-3 | pending | T-C-3-04 |
| T-C-4-01 | S10: create `messaging/outbox/dispatcher_main.py` entry point | C-4 | pending | T-A-2-01 |
| T-C-4-02 | S10: create `messaging/consumers/*_consumer_main.py` entry points | C-4 | pending | T-A-2-01 |
| T-C-4-03 | S10: remove background tasks from `app.py` lifespan | C-4 | pending | T-C-4-01, T-C-4-02 |
| T-C-4-04 | S10: add compose containers + validate | C-4 | pending | T-C-4-03 |

---

## Sub-Plan A: Standards Documentation + Architecture Tests

### Wave A-1: Standards Documentation & Test Utilities ✅

**Goal**: Update STANDARDS.md to codify the canonical entry point convention, and add helper
functions to `tests/architecture/_utils.py` that subsequent test waves depend on.
**Depends on**: none
**Estimated effort**: 30–45 min
**Status**: **DONE** — 2026-03-31 · 29 new tests pass (64 total arch) · ruff + mypy clean
**Architecture layer**: docs + test utilities

#### T-A-1-01: Update STANDARDS.md §1.1 canonical layout

**Type**: docs
**depends_on**: none
**blocks**: [T-A-2-01, T-A-2-03, T-A-3-02, T-B-1-01, T-B-1-02]
**Target files**: `docs/STANDARDS.md`
**PRD reference**: N/A — standards codification

**What to build**:
Extend the §1.1 canonical service directory layout to include `scheduler/`, `workers/`,
and clarify that `messaging/consumers/` uses plural naming while `messaging/outbox/` uses singular.
Currently §1.1 shows `messaging/outbox/dispatcher.py` but omits `dispatcher_main.py`,
`scheduler/`, and `workers/` entirely. Add them with the convention from this plan's overview.

**Acceptance criteria**:
- [x] §1.1 layout tree includes `scheduler/scheduler.py`, `scheduler/scheduler_main.py`
- [x] §1.1 layout tree includes `workers/worker.py`, `workers/worker_main.py`
- [x] §1.1 layout tree includes `messaging/outbox/dispatcher_main.py`
- [x] §1.1 layout tree includes `messaging/consumers/<type>_consumer_main.py`
- [x] Comments in the tree clarify singular/plural convention and "standalone entry point" purpose

---

#### T-A-1-02: Update STANDARDS.md §14 entry point table

**Type**: docs
**depends_on**: none
**blocks**: [T-A-2-01]
**Target files**: `docs/STANDARDS.md`
**PRD reference**: N/A — standards codification

**What to build**:
Fix the §14.1 entry point table to match the canonical directory convention. Current §14 says
`python -m <pkg>.infrastructure.schedulers.scheduler` (plural) and
`python -m <pkg>.infrastructure.messaging.dispatcher` (flat, no `/outbox/` subdir).
Update to:
- Scheduler: `python -m <pkg>.infrastructure.scheduler.scheduler_main`
- Worker: `python -m <pkg>.infrastructure.workers.worker_main`
- Dispatcher: `python -m <pkg>.infrastructure.messaging.outbox.dispatcher_main`
- Consumer: `python -m <pkg>.infrastructure.messaging.consumers.<type>_consumer_main`

Also update §14.3 Docker Compose pattern to use correct module paths.

**Acceptance criteria**:
- [x] §14.1 table uses `scheduler.scheduler_main` (singular dir, `_main` suffix)
- [x] §14.1 table uses `messaging.outbox.dispatcher_main` (with `outbox/` subdir)
- [x] §14.3 Docker Compose example uses matching module paths
- [x] No stale references to `schedulers` (plural) remain in §14

---

#### T-A-1-03: Add process topology helpers to `_utils.py`

**Type**: impl
**depends_on**: none
**blocks**: [T-A-2-01, T-A-2-02, T-A-2-03]
**Target files**: `tests/architecture/_utils.py`
**PRD reference**: N/A

**What to build**:
Add utility functions that the new `test_process_topology.py` will use:

- **Components / Functions**:
  - `ProcessType` — Enum with values: `DISPATCHER`, `CONSUMER`, `SCHEDULER`, `WORKER`
  - `ProcessEntryPoint` — Dataclass: `service: str, process_type: ProcessType, class_file: Path | None, main_file: Path | None, dir_path: Path`
  - `discover_process_entry_points(svc: ServiceInfo) -> list[ProcessEntryPoint]` — Scans the service's
    `infrastructure/` directory for known process patterns:
    - Dispatchers: look in `messaging/outbox/dispatcher*.py`
    - Consumers: look in `messaging/consumers/*_consumer*.py` and legacy `consumer/`
    - Schedulers: look in `scheduler/` and `schedulers/`
    - Workers: look in `workers/`
  - `has_background_tasks_in_lifespan(app_py: Path) -> list[tuple[int, str]]` — AST scan of `app.py`
    looking for `asyncio.create_task()` calls inside functions named `lifespan` or `_lifespan` or
    decorated with `@asynccontextmanager`. Returns list of `(line_number, task_name_or_description)`.
  - `CANONICAL_PATHS` — Dict mapping `ProcessType` to expected relative directory paths:
    ```python
    {
        ProcessType.DISPATCHER: "infrastructure/messaging/outbox",
        ProcessType.CONSUMER: "infrastructure/messaging/consumers",
        ProcessType.SCHEDULER: "infrastructure/scheduler",
        ProcessType.WORKER: "infrastructure/workers",
    }
    ```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_discover_finds_dispatcher | discovery locates dispatcher_main.py | unit |
| test_discover_finds_consumers | discovery locates *_consumer_main.py | unit |
| test_lifespan_detection_positive | AST scanner detects create_task in lifespan | unit |
| test_lifespan_detection_negative | AST scanner returns empty for clean app.py | unit |

- Minimum test count: 4
- Edge cases: service with no infrastructure dir, dispatcher class without _main.py

**Acceptance criteria**:
- [x] `ProcessType` enum with 4 values
- [x] `discover_process_entry_points()` returns correct entries for S2 (scheduler + worker + dispatcher)
- [x] `has_background_tasks_in_lifespan()` detects `asyncio.create_task()` in S5's `app.py`
- [x] All 4 utility tests pass (29 tests written, all passing)
- [x] ruff + mypy clean on `tests/architecture/`

#### Validation Gate
- [x] ruff check passes on `tests/architecture/_utils.py`
- [x] mypy passes on `tests/architecture/`
- [x] 4 new utility tests pass (29 written)
- [x] Existing 11 architecture test modules still pass (no regression)

#### Regression Guardrails
- BP-023: Ensure `uvx ruff format` sync before committing

---

### Wave A-2: Architecture Test — `test_process_topology.py`

**Goal**: Create the main architecture test module that enforces R22 process topology conventions
across all services. Uses a baseline mechanism to allow scaffolded services time to comply.
**Depends on**: Wave A-1
**Estimated effort**: 45–60 min
**Architecture layer**: test

#### T-A-2-01: Entry point convention tests

**Type**: test
**depends_on**: [T-A-1-03]
**blocks**: [T-A-3-01, T-C-1-01, T-C-2-01, T-C-3-01, T-C-4-01]
**Target files**: `tests/architecture/test_process_topology.py`
**PRD reference**: STANDARDS.md §14, RULES.md R22

**What to build**:
Test class `TestEntryPointConventions` with the following tests:

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_dispatcher_has_main_entry_point | Every service with `dispatcher.py` also has `dispatcher_main.py` sibling | unit |
| test_consumer_has_main_entry_point | Every `*_consumer.py` class file has a sibling `*_consumer_main.py` (mature services) | unit |
| test_scheduler_has_main_entry_point | Every service with `scheduler.py` has `scheduler_main.py` sibling | unit |
| test_worker_has_main_entry_point | Every service with `worker.py` has `worker_main.py` sibling | unit |
| test_entry_points_have_main_guard | Every `*_main.py` file has `if __name__ == "__main__":` block | unit |
| test_entry_points_have_signal_handling | Every `*_main.py` imports `signal` module (R22 §14.5) | unit |

- Minimum test count: 6
- Edge cases: service with no background processes (S8, S9 — should produce zero violations)
- Error paths: missing _main.py when class file exists

**Logic & Behavior**:
- For each service, call `discover_process_entry_points(svc)`
- For each entry point where `class_file` exists but `main_file` is None → violation
- Use `PROCESS_TOPOLOGY_BASELINE` dict to skip known violations in scaffolded services
- Baseline entries have format: `{(service_name, ProcessType): "reason"}`

**Acceptance criteria**:
- [ ] 6 tests exist in `TestEntryPointConventions`
- [ ] Tests pass for mature services (S1–S4) — they already have `_main.py` files
- [ ] Tests report baselined violations for scaffolded services (S5–S10) as warnings, not failures
- [ ] ruff + mypy clean

---

#### T-A-2-02: No-lifespan-embedding test

**Type**: test
**depends_on**: [T-A-1-03]
**blocks**: [T-C-1-03, T-C-2-03, T-C-3-04, T-C-4-03]
**Target files**: `tests/architecture/test_process_topology.py`
**PRD reference**: RULES.md R22

**What to build**:
Test class `TestNoLifespanEmbedding` — verifies that `app.py` does NOT start background
processing loops (dispatchers, consumers, schedulers, workers) via `asyncio.create_task()`.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_app_lifespan_has_no_background_tasks | No `asyncio.create_task()` in `app.py` lifespan (mature services) | unit |
| test_app_lifespan_no_dispatcher_in_process | app.py doesn't instantiate dispatcher and call `.run()` | unit |

- Minimum test count: 2
- Edge cases: `create_task` used for non-background purposes (e.g., cleanup tasks at shutdown — should not trigger)

**Logic & Behavior**:
- Call `has_background_tasks_in_lifespan(svc.pkg_dir / "app.py")` for each mature service
- Any result → violation
- Scaffolded services are baselined (expected to fail until Sub-Plan C completes)

**Acceptance criteria**:
- [ ] 2 tests exist in `TestNoLifespanEmbedding`
- [ ] Mature services (S1–S4) pass — their `app.py` files don't embed background tasks
- [ ] Scaffolded violations are baselined with clear message

---

#### T-A-2-03: Directory naming convention tests

**Type**: test
**depends_on**: [T-A-1-03]
**blocks**: [T-B-1-01]
**Target files**: `tests/architecture/test_process_topology.py`
**PRD reference**: STANDARDS.md §1.1

**What to build**:
Test class `TestDirectoryNamingConventions` — verifies that process-related directories
use the canonical naming:

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_scheduler_dir_is_singular | `infrastructure/scheduler/` not `schedulers/` | unit |
| test_workers_dir_is_plural | `infrastructure/workers/` not `worker/` | unit |
| test_consumers_dir_under_messaging | `infrastructure/messaging/consumers/` not `infrastructure/consumer/` | unit |
| test_outbox_dir_under_messaging | `infrastructure/messaging/outbox/` not `infrastructure/outbox/` | unit |
| test_no_stale_outbox_outside_messaging | No `infrastructure/outbox/` when `messaging/outbox/` exists | unit |

- Minimum test count: 5

**Logic & Behavior**:
- For each service, check if non-canonical directory names exist
- `schedulers/` (plural) → violation, expect `scheduler/`
- `consumer/` (singular, outside messaging) → violation, expect `messaging/consumers/`
- `infrastructure/outbox/` (outside messaging) → violation, expect `messaging/outbox/`
- Scaffolded services baselined

**Acceptance criteria**:
- [ ] 5 directory naming tests exist
- [ ] S2 `schedulers/` flagged (will be fixed in Wave B-1)
- [ ] S4 stale `outbox/` flagged (will be fixed in Wave B-1)
- [ ] S5–S10 `consumer/` and `outbox/` outside messaging baselined

---

#### T-A-2-04: Baseline mechanism for scaffolded service violations

**Type**: impl
**depends_on**: [T-A-2-01]
**blocks**: none
**Target files**: `tests/architecture/test_process_topology.py`
**PRD reference**: N/A

**What to build**:
A `TOPOLOGY_BASELINE` constant at the top of the test module that lists known violations
in scaffolded services. Tests use this to downgrade violations from failures to warnings.

**Entities / Components**:
- **Name**: `TOPOLOGY_BASELINE`
- **Purpose**: Allow new tests to pass while scaffolded services are being migrated
- **Key attributes**: `dict[tuple[str, str], str]` mapping `(service_name, rule_id)` to reason string
- **Invariants**: Baseline entries MUST have a comment with the plan wave that will fix them

**Logic & Behavior**:
```python
TOPOLOGY_BASELINE: dict[tuple[str, str], str] = {
    ("content-store", "TOPO-MAIN-DISPATCHER"): "Fix in PLAN-0011 Wave C-1",
    ("content-store", "TOPO-MAIN-CONSUMER"): "Fix in PLAN-0011 Wave C-1",
    ("content-store", "TOPO-LIFESPAN"): "Fix in PLAN-0011 Wave C-1",
    ("nlp-pipeline", "TOPO-MAIN-DISPATCHER"): "Fix in PLAN-0011 Wave C-2",
    # ... etc for S6, S7, S10
}
```
- When a violation matches a baseline entry, it's printed as a warning but doesn't fail the test
- When a baseline entry has no matching violation (i.e., it was fixed), it warns about stale baseline

**Acceptance criteria**:
- [ ] All scaffolded service violations are baselined
- [ ] `pytest tests/architecture/test_process_topology.py -v` passes (all green)
- [ ] Warnings printed for baselined violations (visible in verbose output)

#### Pre-read (agent must read before starting)
- `tests/architecture/_utils.py` — helper functions added in A-1
- `tests/architecture/test_outbox_dispatcher_contracts.py` — existing outbox test patterns
- `tests/architecture/test_consumer_enforcement.py` — existing consumer test patterns
- `services/market-ingestion/src/market_ingestion/infrastructure/` — reference mature service
- `services/content-store/src/content_store/app.py` — lifespan embedding example

#### Validation Gate
- [ ] ruff check passes on `tests/architecture/test_process_topology.py`
- [ ] mypy passes on `tests/architecture/`
- [ ] All new tests pass — minimum 15 new tests (6 + 2 + 5 + baseline verification)
- [ ] All existing architecture tests still pass
- [ ] No mature service (S1–S4) has failing violations

#### Regression Guardrails
- BP-023: Ensure `uvx ruff format` sync before committing
- BP-065: Fix ruff BEFORE git add to avoid stash conflict

---

### Wave A-3: Compose Alignment Test + Existing Test Enhancements

**Goal**: Add a test that verifies Docker Compose containers exist for every standalone entry point,
enhance the existing outbox test, and add a `make test-arch` convenience target.
**Depends on**: Wave A-2
**Estimated effort**: 30–45 min
**Architecture layer**: test + config

#### T-A-3-01: Create `test_compose_alignment.py`

**Type**: test
**depends_on**: [T-A-2-01]
**blocks**: [T-B-2-01, T-B-2-02]
**Target files**: `tests/architecture/test_compose_alignment.py`
**PRD reference**: STANDARDS.md §14.3

**What to build**:
A new architecture test module that parses `docker-compose.test.yml` and verifies:
1. Every `*_main.py` entry point in a mature service has a corresponding compose container
2. Every compose container's `command` module path resolves to an existing Python file
3. No orphaned compose containers (container defined but entry point file missing)

**Entities / Components**:
- **Name**: `_parse_compose_services`
- **Purpose**: Extract service entries from docker-compose YAML
- **Key methods**: Returns list of `(service_name, command_module_path)` tuples
- **Depends on**: `PyYAML` (already available in test deps)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_every_entry_point_has_compose_container | Each `*_main.py` maps to a compose service with matching module path | unit |
| test_compose_commands_resolve_to_files | Every `python -m <module>` in compose resolves to an existing `.py` file | unit |
| test_no_stale_compose_module_paths | No compose `command` references modules that don't exist | unit |

- Minimum test count: 3
- Edge cases: compose services that aren't Python processes (postgres, kafka, etc.)

**Logic & Behavior**:
- Parse `infra/compose/docker-compose.test.yml` with PyYAML
- Filter to services with `command: ["python", "-m", ...]`
- Convert module path to filesystem path: `<module>.replace(".", "/") + ".py"` relative to the service's `src/` dir
- Cross-reference with `discover_process_entry_points()` results
- Baseline scaffolded services (missing compose containers expected until Sub-Plan C)

**Acceptance criteria**:
- [ ] 3 tests in `TestComposeAlignment`
- [ ] Stale `docker-compose.yml` paths flagged (will be fixed in Wave B-2)
- [ ] Mature service entry points all have compose containers in test compose

---

#### T-A-3-02: Enhance `test_outbox_dispatcher_contracts.py`

**Type**: test
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**: `tests/architecture/test_outbox_dispatcher_contracts.py`
**PRD reference**: STANDARDS.md §1.1

**What to build**:
Add a test to the existing outbox test module that verifies dispatcher files are in the
canonical path (`infrastructure/messaging/outbox/`) not legacy locations.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_dispatcher_at_canonical_path | dispatcher.py lives under `infrastructure/messaging/outbox/`, not `infrastructure/outbox/` or root `messaging/` | unit |

- Minimum test count: 1

**Acceptance criteria**:
- [ ] New test added to existing `TestDispatcherContracts` class
- [ ] S5–S10 `infrastructure/outbox/dispatcher.py` flagged (baselined)
- [ ] S1–S4 pass (already at canonical path)

---

#### T-A-3-03: Add `make test-arch` target to Makefile

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**: `Makefile`
**PRD reference**: N/A

**What to build**:
Add a dedicated `test-arch` make target that runs only the architecture tests.
This makes it easy to validate standards compliance without running the full test suite.

```makefile
test-arch:
	python -m pytest tests/architecture/ -v --tb=short
```

Also update the `help` target to include this new command and add `test-arch` to the `.PHONY` list.

**Acceptance criteria**:
- [ ] `make test-arch` runs all architecture tests successfully
- [ ] `make help` lists the new target
- [ ] `.PHONY` includes `test-arch`

#### Pre-read (agent must read before starting)
- `infra/compose/docker-compose.test.yml` — compose services to parse
- `infra/compose/docker-compose.yml` — stale paths to detect
- `tests/architecture/test_outbox_dispatcher_contracts.py` — enhance this file
- `Makefile` — add new target

#### Validation Gate
- [ ] ruff check passes on new and modified test files
- [ ] mypy passes on `tests/architecture/`
- [ ] All new tests pass — minimum 4 new tests
- [ ] `make test-arch` succeeds
- [ ] All existing architecture tests still pass

#### Regression Guardrails
- BP-023: Ensure `uvx ruff format` sync before committing

---

## Sub-Plan B: Mature Service Standardization (S1–S4)

### Wave B-1: Directory Renames & Entry Point Fixes (S2 + S4)

**Goal**: Fix the two directory naming inconsistencies in mature services: S2's `schedulers/` → `scheduler/`
and S4's `scheduler_process.py` → `scheduler_main.py`. Clean up S4's stale `infrastructure/outbox/` dir.
**Depends on**: Wave A-1 (standards documented)
**Estimated effort**: 30–45 min
**Architecture layer**: infrastructure

#### T-B-1-01: S2 market-ingestion — rename `schedulers/` → `scheduler/`

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-B-1-04, T-B-2-01]
**Target files**:
- `services/market-ingestion/src/market_ingestion/infrastructure/schedulers/` → rename to `scheduler/`
- All files importing from `market_ingestion.infrastructure.schedulers`
- `services/market-ingestion/tests/` — update any test imports

**What to build**:
Rename the directory from `schedulers/` to `scheduler/` (singular) to match the canonical convention
from STANDARDS.md §1.1. Update all import paths across the service.

**Logic & Behavior**:
1. `git mv services/market-ingestion/src/market_ingestion/infrastructure/schedulers/ services/market-ingestion/src/market_ingestion/infrastructure/scheduler/`
2. Grep for all occurrences of `infrastructure.schedulers` in the market-ingestion service
3. Replace with `infrastructure.scheduler` (singular)
4. Check `__init__.py` re-exports, `config.py` references, and test imports

**Downstream test impact**:
- `services/market-ingestion/tests/application/test_schedule_tasks.py` — likely imports scheduler
- `tests/architecture/test_process_topology.py` — new test from Wave A-2 will check this
- `infra/compose/docker-compose.test.yml` line 329 — module path reference

**Acceptance criteria**:
- [ ] `infrastructure/schedulers/` no longer exists
- [ ] `infrastructure/scheduler/` exists with same files
- [ ] All imports updated (`infrastructure.schedulers` → `infrastructure.scheduler`)
- [ ] No broken imports (ruff + mypy clean)

---

#### T-B-1-02: S4 content-ingestion — rename `scheduler_process.py` → `scheduler_main.py`

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-B-1-04, T-B-2-02]
**Target files**:
- `services/content-ingestion/src/content_ingestion/infrastructure/scheduler/scheduler_process.py` → rename
- All files importing `scheduler_process`
- Docker Compose files referencing the module path

**What to build**:
Rename the entry point file to match the `*_main.py` convention. The scheduler directory is already
singular (`scheduler/`) which is correct. Only the filename needs changing.

**Logic & Behavior**:
1. `git mv .../scheduler/scheduler_process.py .../scheduler/scheduler_main.py`
2. Grep for `scheduler_process` across the codebase
3. Replace with `scheduler_main`
4. Update docker-compose `command` entries

**Downstream test impact**:
- `infra/compose/docker-compose.yml` line 518 — references `scheduler_process`
- `infra/compose/docker-compose.test.yml` — if S4 scheduler container exists
- `services/content-ingestion/tests/` — any test importing `scheduler_process`

**Acceptance criteria**:
- [ ] `scheduler_process.py` no longer exists
- [ ] `scheduler_main.py` exists with same content
- [ ] All references updated
- [ ] Docker Compose uses `content_ingestion.infrastructure.scheduler.scheduler_main`

---

#### T-B-1-03: S4 content-ingestion — remove stale `infrastructure/outbox/` directory

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `services/content-ingestion/src/content_ingestion/infrastructure/outbox/`

**What to build**:
The `infrastructure/outbox/` directory contains only `__pycache__/` — it's a stale remnant.
The actual outbox dispatcher is correctly placed at `infrastructure/messaging/outbox/`.
Remove the stale directory.

**Logic & Behavior**:
1. Verify `infrastructure/outbox/` contains no source files (only `__pycache__`)
2. `rm -rf` the stale directory
3. Verify no imports reference `content_ingestion.infrastructure.outbox`

**Acceptance criteria**:
- [ ] `infrastructure/outbox/` directory removed
- [ ] No broken imports
- [ ] `infrastructure/messaging/outbox/` still exists and is untouched

---

#### T-B-1-04: S2 + S4 validation gate

**Type**: test
**depends_on**: [T-B-1-01, T-B-1-02]
**blocks**: [T-B-2-01, T-B-2-02]
**Target files**: none (validation only)

**What to build**:
Run ruff, mypy, and unit tests for both services to confirm the renames didn't break anything.

**Acceptance criteria**:
- [ ] `uvx ruff check services/market-ingestion/src/ services/market-ingestion/tests/` — clean
- [ ] `uvx ruff check services/content-ingestion/src/ services/content-ingestion/tests/` — clean
- [ ] `mypy services/market-ingestion/src/ --config-file services/market-ingestion/mypy.ini` — clean
- [ ] `mypy services/content-ingestion/src/ --config-file services/content-ingestion/mypy.ini` — clean
- [ ] `python -m pytest services/market-ingestion/tests/unit/ -v` — all pass
- [ ] `python -m pytest services/content-ingestion/tests/unit/ -v` — all pass

#### Pre-read (agent must read before starting)
- `services/market-ingestion/src/market_ingestion/infrastructure/schedulers/scheduler.py` — file to rename
- `services/content-ingestion/src/content_ingestion/infrastructure/scheduler/scheduler_process.py` — file to rename
- `services/content-ingestion/src/content_ingestion/infrastructure/outbox/` — verify stale

#### Validation Gate
- [ ] ruff + mypy clean for both S2 and S4
- [ ] Unit tests pass for both services
- [ ] `make test-arch` passes (new topology tests pass for S2 + S4)
- [ ] No regression in existing tests

#### Regression Guardrails
- BP-023: Ensure `uvx ruff format` sync before committing
- BP-065: Fix ruff BEFORE git add

---

### Wave B-2: Docker Compose Fixes & Final Mature Service Cleanup

**Goal**: Fix stale module paths in `docker-compose.yml`, add missing S4 containers to
`docker-compose.test.yml`, and verify all S1–S4 services pass the new architecture tests.
**Depends on**: Wave B-1
**Estimated effort**: 20–30 min
**Architecture layer**: config

#### T-B-2-01: Fix `docker-compose.yml` stale module paths

**Type**: config
**depends_on**: [T-B-1-01]
**blocks**: [T-B-2-03]
**Target files**: `infra/compose/docker-compose.yml`
**PRD reference**: STANDARDS.md §14.3

**What to build**:
Fix the following stale module paths in the main docker-compose file:

| Container | Current (stale) | Correct |
|-----------|----------------|---------|
| `portfolio-dispatcher` | `portfolio.messaging.dispatcher_main` | `portfolio.infrastructure.messaging.outbox.dispatcher_main` |
| `market-ingestion-scheduler` | `market_ingestion.scheduler.main` | `market_ingestion.infrastructure.scheduler.scheduler_main` |
| `market-ingestion-worker` | `market_ingestion.worker.main` | `market_ingestion.infrastructure.workers.worker_main` |
| `market-ingestion-dispatcher` | `market_ingestion.messaging.dispatcher_main` | `market_ingestion.infrastructure.messaging.outbox.dispatcher_main` |
| `content-ingestion-scheduler` | `content_ingestion.infrastructure.scheduler.scheduler_process` | `content_ingestion.infrastructure.scheduler.scheduler_main` |

**Acceptance criteria**:
- [ ] All 5 stale paths corrected
- [ ] Module paths match `docker-compose.test.yml` patterns (which are already correct for S1, S3)

---

#### T-B-2-02: Add missing S4 containers to `docker-compose.test.yml`

**Type**: config
**depends_on**: [T-B-1-02]
**blocks**: [T-B-2-03]
**Target files**: `infra/compose/docker-compose.test.yml`
**PRD reference**: STANDARDS.md §14.3

**What to build**:
The test compose file is missing `content-ingestion-scheduler` and `content-ingestion-worker`
containers. Add them following the pattern used by S2 (market-ingestion).

**Entities / Components**:
- `content-ingestion-scheduler` container:
  - Profile: `content-ingestion-test, all`
  - Depends on: `content-ingestion-migrate` (service_completed_successfully)
  - Command: `python -m content_ingestion.infrastructure.scheduler.scheduler_main`
  - Healthcheck: basic Python exit check (like S2's scheduler)
  - Restart: on-failure
- `content-ingestion-worker` container:
  - Profile: `content-ingestion-test, all`
  - Depends on: `content-ingestion-migrate`, `minio-init-test`
  - Command: `python -m content_ingestion.infrastructure.workers.worker_main`
  - Healthcheck: basic Python exit check
  - Restart: on-failure

**Acceptance criteria**:
- [ ] Both containers defined in `docker-compose.test.yml`
- [ ] Profiles match existing S4 containers
- [ ] Module paths reference correct renamed files from T-B-1-02

---

#### T-B-2-03: Verify all S1–S4 architecture tests pass

**Type**: test
**depends_on**: [T-B-2-01, T-B-2-02]
**blocks**: none
**Target files**: none (validation only)

**What to build**:
Run the full architecture test suite and verify zero failures for mature services.

**Acceptance criteria**:
- [ ] `make test-arch` — all green
- [ ] `test_process_topology.py` passes for S1, S2, S3, S4
- [ ] `test_compose_alignment.py` passes for S1, S2, S3, S4
- [ ] `test_outbox_dispatcher_contracts.py` passes with enhanced canonical path check
- [ ] Only baselined scaffolded-service violations remain

#### Pre-read (agent must read before starting)
- `infra/compose/docker-compose.yml` lines 228–360 — stale paths
- `infra/compose/docker-compose.test.yml` lines 488–550 — S4 section

#### Validation Gate
- [ ] `make test-arch` — all green
- [ ] `docker compose -f infra/compose/docker-compose.yml config --quiet` — YAML valid
- [ ] `docker compose -f infra/compose/docker-compose.test.yml config --quiet` — YAML valid

#### Regression Guardrails
- BP-023: Ensure `uvx ruff format` sync before committing

---

## Sub-Plan C: Scaffolded Service Process Extraction (S5, S6, S7, S10)

> **Note**: Each wave in Sub-Plan C is **independent** — they can be executed in any order
> or in parallel worktrees. Each wave extracts embedded background processes from a single
> service's `app.py` lifespan into standalone `*_main.py` entry points, following the
> reference pattern from S2 (market-ingestion) and S4 (content-ingestion).

### Common Pattern for All Sub-Plan C Waves

Every standalone entry point follows STANDARDS.md §14.2:

```python
# <pkg>/infrastructure/<component>/<name>_main.py

import asyncio
import signal
import structlog
from <pkg>.config import Settings

logger = structlog.get_logger()

async def _run() -> None:
    settings = Settings()
    # Build session factories with appropriate pool sizes (§14.4)
    # Instantiate the process class
    # Register signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, process.stop)
    await process.run()

def main() -> None:
    asyncio.run(_run())

if __name__ == "__main__":
    main()
```

For dispatcher entry points specifically, follow the pattern from
`services/market-ingestion/src/market_ingestion/infrastructure/messaging/outbox/dispatcher_main.py`.

---

### Wave C-1: S5 Content Store — Extract Dispatcher + Consumer

**Goal**: Extract `ContentStoreOutboxDispatcher` and `ArticleConsumer` from `app.py` lifespan
into standalone entry points. Move from `infrastructure/outbox/` and `infrastructure/consumer/`
to canonical `infrastructure/messaging/outbox/` and `infrastructure/messaging/consumers/` paths.
**Depends on**: Waves A-2, B-1
**Estimated effort**: 45–60 min
**Architecture layer**: infrastructure

#### T-C-1-01: Create `messaging/outbox/dispatcher_main.py` for S5

**Type**: impl
**depends_on**: [T-A-2-01]
**blocks**: [T-C-1-03]
**Target files**:
- Create: `services/content-store/src/content_store/infrastructure/messaging/outbox/dispatcher_main.py`
- Move: `services/content-store/src/content_store/infrastructure/outbox/dispatcher.py` →
  `services/content-store/src/content_store/infrastructure/messaging/outbox/dispatcher.py`
- Create: `services/content-store/src/content_store/infrastructure/messaging/__init__.py`
- Create: `services/content-store/src/content_store/infrastructure/messaging/outbox/__init__.py`

**What to build**:
1. Create `messaging/outbox/` directory structure under `infrastructure/`
2. Move the existing dispatcher class file to the canonical location
3. Create `dispatcher_main.py` following §14.2 entry point pattern
4. The entry point must:
   - Instantiate `Settings()`
   - Build session factories with dispatcher pool sizes (pool_size=3, max_overflow=5)
   - Create the `ContentStoreOutboxDispatcher` instance
   - Register SIGINT/SIGTERM handlers
   - Call `await dispatcher.run()` (or `run_forever()`)
5. Update all imports that reference the old location

**Acceptance criteria**:
- [ ] `infrastructure/messaging/outbox/dispatcher.py` exists with class
- [ ] `infrastructure/messaging/outbox/dispatcher_main.py` exists with entry point
- [ ] Entry point has `if __name__ == "__main__":` guard
- [ ] Entry point imports `signal` module
- [ ] Old `infrastructure/outbox/dispatcher.py` removed
- [ ] All imports updated

---

#### T-C-1-02: Create `messaging/consumers/article_consumer_main.py` for S5

**Type**: impl
**depends_on**: [T-A-2-01]
**blocks**: [T-C-1-03]
**Target files**:
- Move: `services/content-store/src/content_store/infrastructure/consumer/article_consumer.py` →
  `services/content-store/src/content_store/infrastructure/messaging/consumers/article_consumer.py`
- Create: `services/content-store/src/content_store/infrastructure/messaging/consumers/__init__.py`
- Create: `services/content-store/src/content_store/infrastructure/messaging/consumers/article_consumer_main.py`

**What to build**:
1. Create `messaging/consumers/` directory structure
2. Move the existing consumer class to canonical location
3. Create `article_consumer_main.py` following §14.2 pattern
4. The entry point must build its own Kafka consumer config, session factories, signal handlers

**Acceptance criteria**:
- [ ] `infrastructure/messaging/consumers/article_consumer.py` exists
- [ ] `infrastructure/messaging/consumers/article_consumer_main.py` exists
- [ ] Old `infrastructure/consumer/` directory removed
- [ ] All imports updated

---

#### T-C-1-03: Remove background tasks from S5 `app.py` lifespan

**Type**: impl
**depends_on**: [T-C-1-01, T-C-1-02]
**blocks**: [T-C-1-04]
**Target files**: `services/content-store/src/content_store/app.py`

**What to build**:
Remove the `asyncio.create_task()` calls that start the dispatcher, consumer, and metrics poller
from the lifespan. The `app.py` should only:
- Create the FastAPI app
- Set up middleware (prometheus, CORS, etc.)
- Configure lifespan for DB engine/session factory initialization and cleanup
- NOT start any long-running background tasks

**Logic & Behavior**:
1. Remove the `asyncio.create_task(consumer.run())` call
2. Remove the `asyncio.create_task(dispatcher.run())` call
3. Remove the `asyncio.create_task(_run_metrics())` call (metrics poller can stay or move to a separate concern)
4. Remove the shutdown cleanup code for those tasks
5. Keep lifespan setup for DB engine, session factory, and middleware

**Acceptance criteria**:
- [ ] No `asyncio.create_task()` calls in lifespan
- [ ] `has_background_tasks_in_lifespan()` returns empty for S5's app.py
- [ ] App still starts and serves HTTP requests (health check passes)
- [ ] ruff + mypy clean

---

#### T-C-1-04: Add S5 compose containers + validate

**Type**: config + test
**depends_on**: [T-C-1-03]
**blocks**: none
**Target files**:
- `infra/compose/docker-compose.test.yml` — add `content-store-dispatcher` and `content-store-article-consumer`
- `infra/compose/docker-compose.yml` — add same containers

**What to build**:
Add Docker Compose service entries for both standalone processes. Follow the pattern from S4.

**Acceptance criteria**:
- [ ] `content-store-dispatcher` container in both compose files
- [ ] `content-store-article-consumer` container in both compose files
- [ ] Module paths match actual file locations
- [ ] `make test-arch` passes — S5 removed from topology baseline
- [ ] ruff + mypy clean for S5
- [ ] Unit tests pass for S5

#### Pre-read (agent must read before starting)
- `services/content-store/src/content_store/app.py` — current lifespan with embedded tasks
- `services/content-store/src/content_store/infrastructure/outbox/dispatcher.py` — class to move
- `services/content-store/src/content_store/infrastructure/consumer/article_consumer.py` — class to move
- `services/market-ingestion/src/market_ingestion/infrastructure/messaging/outbox/dispatcher_main.py` — reference pattern

#### Validation Gate
- [ ] ruff + mypy clean for S5
- [ ] S5 unit tests pass
- [ ] `make test-arch` — S5 violations removed from baseline, all green
- [ ] Compose YAML validates

---

### Wave C-2: S6 NLP Pipeline — Extract Dispatcher + Consumers

**Goal**: Extract `NLPPipelineOutboxDispatcher`, `ArticleProcessingConsumer`, and
`WatchlistEventConsumer` from `app.py` lifespan. Move to canonical paths under `messaging/`.
**Depends on**: Waves A-2, B-1
**Estimated effort**: 45–60 min
**Architecture layer**: infrastructure

#### T-C-2-01: Create `messaging/outbox/dispatcher_main.py` for S6

**Type**: impl
**depends_on**: [T-A-2-01]
**blocks**: [T-C-2-03]
**Target files**:
- Move: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/outbox/dispatcher.py` →
  `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/outbox/dispatcher.py`
- Create: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/outbox/dispatcher_main.py`
- Create necessary `__init__.py` files

**What to build**:
Same pattern as T-C-1-01. The S6 dispatcher currently has supervised restart logic
(`_supervised_dispatcher()` in app.py with exponential backoff). This restart logic should be
**preserved in the entry point** — the `_main.py` wraps the dispatcher in a supervised loop.

**Logic & Behavior**:
The `dispatcher_main.py` should include the supervised restart pattern:
```python
async def _run() -> None:
    settings = Settings()
    # ... setup ...
    failures = 0
    while not stop_event.is_set():
        try:
            await dispatcher.run()
            break
        except asyncio.CancelledError:
            raise
        except Exception:
            failures += 1
            delay = min(5 * (2 ** failures), 300)
            logger.error("dispatcher_crashed", failures=failures, restart_delay=delay)
            await asyncio.sleep(delay)
```

**Acceptance criteria**:
- [ ] Dispatcher class at canonical path
- [ ] Entry point with supervised restart logic preserved
- [ ] Old `infrastructure/outbox/` removed
- [ ] Signal handling implemented

---

#### T-C-2-02: Create `messaging/consumers/{article,watchlist}_consumer_main.py` for S6

**Type**: impl
**depends_on**: [T-A-2-01]
**blocks**: [T-C-2-03]
**Target files**:
- Move: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/consumer/*.py` →
  `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/*.py`
- Create: two `*_consumer_main.py` entry points

**What to build**:
Move both consumer classes to canonical location and create standalone entry points.
Each consumer gets its own `_main.py` (they may run as separate containers or be
combined into one multi-topic consumer container — the entry points should be separate
to support both deployment models).

**Acceptance criteria**:
- [ ] `messaging/consumers/article_consumer.py` + `article_consumer_main.py`
- [ ] `messaging/consumers/watchlist_consumer.py` + `watchlist_consumer_main.py`
- [ ] Old `infrastructure/consumer/` removed
- [ ] Both entry points have signal handling

---

#### T-C-2-03: Remove background tasks from S6 `app.py` lifespan

**Type**: impl
**depends_on**: [T-C-2-01, T-C-2-02]
**blocks**: [T-C-2-04]
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/app.py`

**What to build**:
Remove all `asyncio.create_task()` calls from lifespan:
1. Remove `_supervised_dispatcher()` function and its task creation
2. Remove `article_consumer.run()` task creation
3. Remove `watchlist_consumer.run()` task creation
4. Remove `_metrics_poller()` task creation
5. Remove all shutdown cleanup code for those tasks
6. Keep: DB engine setup, middleware, healthcheck state

**Acceptance criteria**:
- [ ] No `asyncio.create_task()` in lifespan
- [ ] `_supervised_dispatcher()` function removed entirely
- [ ] App serves HTTP requests successfully
- [ ] ruff + mypy clean

---

#### T-C-2-04: Add S6 compose containers + validate

**Type**: config + test
**depends_on**: [T-C-2-03]
**blocks**: none
**Target files**: Both docker-compose files

**What to build**:
Add containers: `nlp-pipeline-dispatcher`, `nlp-pipeline-article-consumer`,
`nlp-pipeline-watchlist-consumer` (or a combined `nlp-pipeline-consumers` with multi-topic support).

**Acceptance criteria**:
- [ ] Compose containers defined for all 3 processes
- [ ] `make test-arch` — S6 removed from baseline
- [ ] ruff + mypy + unit tests pass for S6
- [ ] Compose YAML validates

#### Pre-read (agent must read before starting)
- `services/nlp-pipeline/src/nlp_pipeline/app.py` — lifespan with supervised dispatcher + consumers
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/outbox/dispatcher.py` — class to move
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/consumer/` — consumer classes to move

#### Validation Gate
- [ ] ruff + mypy clean for S6
- [ ] S6 unit tests pass
- [ ] `make test-arch` — S6 violations cleared

---

### Wave C-3: S7 Knowledge Graph — Extract Dispatcher + Scheduler + Consumers

**Goal**: Extract `OutboxDispatcher`, `KnowledgeGraphScheduler`, and all 4 consumers from
`app.py` lifespan. This is the most complex extraction — S7 has the most embedded processes.
**Depends on**: Waves A-2, B-1
**Estimated effort**: 60–90 min
**Architecture layer**: infrastructure

#### T-C-3-01: Create `messaging/outbox/dispatcher_main.py` for S7

**Type**: impl
**depends_on**: [T-A-2-01]
**blocks**: [T-C-3-04]
**Target files**:
- Move: `services/knowledge-graph/src/knowledge_graph/infrastructure/outbox/dispatcher.py` →
  `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/outbox/dispatcher.py`
- Create: `dispatcher_main.py` with supervised restart (same as S6 pattern)

**Acceptance criteria**:
- [ ] Dispatcher class at canonical path with supervised entry point
- [ ] Old `infrastructure/outbox/` removed
- [ ] Signal handling implemented

---

#### T-C-3-02: Create `messaging/consumers/*_consumer_main.py` for S7

**Type**: impl
**depends_on**: [T-A-2-01]
**blocks**: [T-C-3-04]
**Target files**:
- Move: `services/knowledge-graph/src/knowledge_graph/infrastructure/consumer/*.py` →
  `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/*.py`
- Create entry points for each consumer:
  - `enriched_consumer_main.py` (enriched article events from S6)
  - `entity_consumer_main.py` (entity events)
  - `fundamentals_consumer_main.py` (fundamentals data events)
  - `instrument_consumer_main.py` (instrument reference events)

**What to build**:
Move all 4 consumer classes and create standalone entry points. Consider whether some consumers
can share a single entry point (if they consume from related topics), but default to separate
entry points for maximum flexibility.

**Acceptance criteria**:
- [ ] 4 consumer classes at canonical path
- [ ] At least 1 entry point per consumer (may combine related ones)
- [ ] Old `infrastructure/consumer/` removed
- [ ] All entry points have signal handling

---

#### T-C-3-03: Create `scheduler/scheduler_main.py` for S7

**Type**: impl
**depends_on**: [T-A-2-01]
**blocks**: [T-C-3-04]
**Target files**:
- Keep: `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py`
  (already at canonical path)
- Create: `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler_main.py`

**What to build**:
S7's scheduler is currently an `APScheduler` instance that's started directly in the lifespan
with `await scheduler.start()`. Create a standalone entry point that:
1. Instantiates Settings and session factories
2. Creates the scheduler instance
3. Registers signal handlers
4. Runs the scheduler until shutdown

**Acceptance criteria**:
- [ ] `scheduler_main.py` exists with entry point
- [ ] Scheduler class remains at `scheduler/scheduler.py` (unchanged)
- [ ] Entry point has signal handling and graceful shutdown

---

#### T-C-3-04: Remove background tasks from S7 `app.py` lifespan

**Type**: impl
**depends_on**: [T-C-3-01, T-C-3-02, T-C-3-03]
**blocks**: [T-C-3-05]
**Target files**: `services/knowledge-graph/src/knowledge_graph/app.py`

**What to build**:
Remove all embedded processes:
1. Remove `_supervised_dispatcher()` function and task creation
2. Remove scheduler start/stop from lifespan
3. Remove consumer stub creation
4. Keep: DB engine, middleware, healthcheck

**Acceptance criteria**:
- [ ] No `asyncio.create_task()` in lifespan
- [ ] No `await scheduler.start()` in lifespan
- [ ] App serves HTTP requests
- [ ] ruff + mypy clean

---

#### T-C-3-05: Add S7 compose containers + validate

**Type**: config + test
**depends_on**: [T-C-3-04]
**blocks**: none
**Target files**: Both docker-compose files

**What to build**:
Add containers: `knowledge-graph-dispatcher`, `knowledge-graph-scheduler`,
and consumer containers (may group related consumers into fewer containers).

**Acceptance criteria**:
- [ ] Compose containers for dispatcher, scheduler, and consumers
- [ ] `make test-arch` — S7 removed from baseline
- [ ] ruff + mypy + unit tests pass for S7
- [ ] Compose YAML validates

#### Pre-read (agent must read before starting)
- `services/knowledge-graph/src/knowledge_graph/app.py` — lifespan with scheduler + dispatcher + consumer stub
- `services/knowledge-graph/src/knowledge_graph/infrastructure/outbox/dispatcher.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/consumer/*.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py`

#### Validation Gate
- [ ] ruff + mypy clean for S7
- [ ] S7 unit tests pass
- [ ] `make test-arch` — S7 violations cleared
- [ ] Compose YAML validates

---

### Wave C-4: S10 Alert — Extract Dispatcher + Consumers

**Goal**: Extract `AlertOutboxDispatcher` and consumer classes from S10. S10 is the simplest
extraction — its dispatcher is instantiated but not actively started as a background task.
**Depends on**: Waves A-2, B-1
**Estimated effort**: 30–45 min
**Architecture layer**: infrastructure

#### T-C-4-01: Create `messaging/outbox/dispatcher_main.py` for S10

**Type**: impl
**depends_on**: [T-A-2-01]
**blocks**: [T-C-4-03]
**Target files**:
- Move: `services/alert/src/alert/infrastructure/outbox/dispatcher.py` →
  `services/alert/src/alert/infrastructure/messaging/outbox/dispatcher.py`
- Create: `dispatcher_main.py` entry point

**What to build**:
S10's dispatcher is currently instantiated but NOT started as a background task (`.stop()`
is called on shutdown but no `.run()` is called). Investigate whether the dispatcher needs
to run as a continuous loop or if it's triggered on-demand. Create the entry point
regardless — it may be started when the service needs outbox functionality.

**Acceptance criteria**:
- [ ] Dispatcher class at canonical path
- [ ] Entry point created (even if service doesn't actively use it yet)
- [ ] Old `infrastructure/outbox/` removed

---

#### T-C-4-02: Create `messaging/consumers/*_consumer_main.py` for S10

**Type**: impl
**depends_on**: [T-A-2-01]
**blocks**: [T-C-4-03]
**Target files**:
- Move: `services/alert/src/alert/infrastructure/consumer/*.py` →
  `services/alert/src/alert/infrastructure/messaging/consumers/*.py`
- Create entry points for: `watchlist_consumer_main.py`, `intelligence_consumer_main.py`

**Acceptance criteria**:
- [ ] Consumer classes at canonical path
- [ ] Entry points with signal handling
- [ ] Old `infrastructure/consumer/` removed

---

#### T-C-4-03: Remove background tasks from S10 `app.py` lifespan

**Type**: impl
**depends_on**: [T-C-4-01, T-C-4-02]
**blocks**: [T-C-4-04]
**Target files**: `services/alert/src/alert/app.py`

**What to build**:
S10 currently has minimal lifespan embedding (dispatcher instantiated but not started).
Clean up any remaining references and ensure no `asyncio.create_task()` calls exist.

**Acceptance criteria**:
- [ ] No background task creation in lifespan
- [ ] App serves HTTP requests
- [ ] ruff + mypy clean

---

#### T-C-4-04: Add S10 compose containers + validate

**Type**: config + test
**depends_on**: [T-C-4-03]
**blocks**: none
**Target files**: Both docker-compose files

**What to build**:
Add containers: `alert-dispatcher`, `alert-watchlist-consumer`, `alert-intelligence-consumer`.

**Acceptance criteria**:
- [ ] Compose containers defined
- [ ] `make test-arch` — S10 removed from baseline
- [ ] ruff + mypy + unit tests pass for S10
- [ ] Compose YAML validates

#### Pre-read (agent must read before starting)
- `services/alert/src/alert/app.py` — minimal lifespan
- `services/alert/src/alert/infrastructure/outbox/dispatcher.py`
- `services/alert/src/alert/infrastructure/consumer/*.py`

#### Validation Gate
- [ ] ruff + mypy clean for S10
- [ ] S10 unit tests pass
- [ ] `make test-arch` — S10 violations cleared, baseline now empty
- [ ] Compose YAML validates

---

## Cross-Cutting Concerns

### Contract changes
- **None** — no Avro schemas, API contracts, or event semantics change in this plan
- All changes are structural (directory renames, file moves, compose config)

### Migration needs
- **None** — no database schema changes

### Event flow changes
- **None** — Kafka topics and event types remain the same
- Only the *process that publishes/consumes* changes deployment topology

### Configuration changes
- No new env vars needed
- Existing `Settings` classes are reused by new entry points

### Documentation updates
- STANDARDS.md §1.1 and §14 (Wave A-1)
- Per-service `.claude-context.md` files should be updated after each Sub-Plan C wave
  to reflect the new process topology

---

## Risk Assessment

### Critical path
**A-1 → A-2 → B-1 → B-2** — Mature service compliance is the critical path.
Sub-Plan C waves are independent and lower priority.

### Highest risk: Wave C-3 (S7 Knowledge Graph)
S7 has the most embedded processes (dispatcher + scheduler + 4 consumers + consumer stub).
The scheduler uses APScheduler which has its own lifecycle management that may not trivially
map to the §14.2 entry point pattern. Mitigation: read S7's scheduler code carefully before
extracting; preserve APScheduler's own signal handling if it exists.

### Rollback strategy
- **Sub-Plan A**: Tests are additive — can be reverted by removing files, no side effects
- **Sub-Plan B**: Directory renames are reversible via `git mv` back; compose changes are config-only
- **Sub-Plan C**: Each wave is self-contained per service. If extraction causes issues,
  revert the wave's commit and re-add the service to the baseline

### Testing gaps
- **E2E verification**: The standalone entry points can only be fully validated with Docker Compose
  integration tests (starting the containers). Unit tests verify the code structure and imports
  but not that the processes actually start and run correctly.
- **Mitigation**: Architecture tests verify structural compliance. Full E2E validation happens
  naturally when `make test-all` runs the compose stack.

### Effort estimate
| Sub-Plan | Waves | Estimated Effort |
|----------|-------|-----------------|
| A (Tests & Standards) | 3 | 2–3 hours |
| B (Mature Service Fixes) | 2 | 1–1.5 hours |
| C (Scaffolded Extraction) | 4 | 3–5 hours |
| **Total** | **9** | **6–9.5 hours** |
