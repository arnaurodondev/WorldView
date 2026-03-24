# Execution Prompt 0016 - Shared Libraries Standardization Single Wave

**Wave:** 01 of 01 (single-wave execution)
**Scope:** Repo-wide standardization for shared libraries adoption and architecture enforcement
**Date:** 2026-03-23
**Status:** Ready for execution

---

## 1. Wave Intent

This wave standardizes usage of `libs/common`, `libs/messaging`, `libs/storage`, `libs/observability`, and `libs/contracts` across all services, then enforces compliance through repo-level CI checks and architecture tests.

This is an enforcement wave, not a feature wave.

Primary outcomes:

1. Canonical service structure validation enforced in CI.
2. Import guard checks enforced in CI for all shared library anti-patterns.
3. Architecture tests added for structure, layer boundaries, shared-library contracts, outbox/dispatcher conventions, and storage conventions.
4. Existing drift captured and remediated within this same wave.

---

## 2. Mandatory Pre-Read

Read in this exact order before coding:

1. `AGENTS.md`
2. `CLAUDE.md`
3. `RULES.md`
4. `docs/STANDARDS.md`
5. `docs/libs/common.md`
6. `docs/libs/messaging.md`
7. `docs/libs/storage.md`
8. `docs/libs/observability.md`
9. `docs/libs/contracts.md`
10. `.github/workflows/ci.yml`
11. `scripts/lint.sh`
12. `scripts/ci-local.sh`
13. `pyproject.toml`
15. `STANDARDS.md`
14. Representative services:
1. `services/content-ingestion/src/content_ingestion/`
2. `services/market-ingestion/src/market_ingestion/`
3. `services/market-data/src/market_data/`
4. `services/portfolio/src/portfolio/`

---

## 3. Task-Scoped Write Paths

No edits outside these paths unless explicitly required by a failing check.

1. `.github/workflows/ci.yml`
2. `scripts/architecture/` (new)
3. `scripts/import_guards/` (new)
4. `scripts/structure_checks/` (new)
5. `scripts/ci-local.sh`
6. `scripts/lint.sh`
7. `tests/architecture/` (new)
8. `docs/ai-interactions/agent-prompts/0016-exec-shared-libraries-standardization-single-wave.md`
9. `docs/` for standards references if needed for synchronization
10. Service files only where violations are fixed:
1. `services/**/src/**/*.py`
2. `services/**/tests/**/*.py`
3. `services/**/pyproject.toml`

---

## 4. Enforcement Model For This Wave

Implement strict policy-as-code in one wave with the following rollout inside the same PR chain:

1. Introduce validators and architecture tests.
2. Run in report mode once to capture current violations.
3. Fix violations in services.
4. Switch gates to blocking mode before wave completion.

No deferred debt is allowed at wave handoff.

---

## 5. Work Packages

## WP-A - Repo-Level Canonical Service Structure Validator

### A1. Create structure validator CLI

Create script:

- `scripts/structure_checks/check_service_structure.py`

Responsibilities:

1. Discover all services under `services/*`.
2. Validate canonical required paths from `docs/STANDARDS.md` Section 1.
3. Emit machine-readable JSON report and human-readable summary.
4. Return non-zero exit code on violations when `--strict` is enabled.

Required checks:

1. `src/<package_name>/app.py` and `config.py` exist.
2. Layer folders exist: `domain`, `application`, `api`, `infrastructure`.
3. `infrastructure/messaging/schemas` exists for services producing/consuming Kafka.
4. `tests/unit`, `tests/integration`, `tests/contract` exist.
5. `alembic/versions` exists for DB-owning services.

Options:

1. `--strict`
2. `--report-json <path>`
3. `--services <csv>`
4. `--allow-exceptions-file <path>`

### A2. Add exceptions registry with expiry

Create file:

- `scripts/structure_checks/exceptions.yaml`

Fields per exception:

1. `service`
2. `rule_id`
3. `reason`
4. `owner`
5. `expires_on`

Validator must fail if exception is expired.

### A3. Add CI job

In `.github/workflows/ci.yml`, add job:

1. `validate-service-structure`
2. Runs before long-running tests.
3. Executes structure validator in strict mode.
4. Uploads JSON report as artifact.

### A4. Add local entrypoint

Update `scripts/ci-local.sh` and `scripts/lint.sh` to invoke:

1. `python scripts/structure_checks/check_service_structure.py --strict`

Acceptance criteria for WP-A:

1. CI fails on any missing canonical path or expired exception.
2. Local scripts run structure checks by default.
3. JSON artifact is generated in CI.

---

## WP-B - Import Guard Framework For Shared Libraries

### B1. Create import guard engine

Create script:

- `scripts/import_guards/check_import_guards.py`

Implementation requirements:

1. Parse Python files with AST (not regex-only).
2. Report file path, line number, rule ID, and remediation guidance.
3. Support baseline file for temporary existing violations.
4. Support `--strict`, `--baseline`, `--update-baseline`.

### B2. Define rule catalog

Create rule file:

- `scripts/import_guards/rules.yaml`

Rules to include at minimum:

1. `IG-COMMON-001`: forbid `uuid.uuid4()` in service code, require `common.ids.*`.
2. `IG-COMMON-002`: forbid naive datetime creation (`datetime.now`, `utcnow`) outside shared libs.
3. `IG-MSG-001`: forbid direct `aiokafka` imports.
4. `IG-MSG-002`: forbid direct `redis.asyncio`/`aioredis` imports where `messaging.valkey` must be used.
5. `IG-STORAGE-001`: forbid direct `minio` client usage in services.
6. `IG-STORAGE-002`: forbid direct `boto3` usage in services except approved adapters.
7. `IG-OBS-001`: forbid direct stdlib logging or direct `structlog` where observability wrapper is required.
8. `IG-LAYER-001`: forbid cross-layer imports violating domain/application/api/infrastructure direction.

### B3. Allowlist and boundary exceptions

Create allowlist file:

- `scripts/import_guards/allowlist.yaml`

Allowlist examples:

1. Alembic migrations.
2. Explicit adapter boundary files.
3. Test fixtures where mocking requires temporary direct imports.

### B4. Baseline management

Create baseline file:

- `scripts/import_guards/baseline.json`

Policy:

1. Existing violations are allowed only if present in baseline.
2. Net-new violations fail CI immediately.
3. Wave completion requires baseline size to be zero.

### B5. Add CI job

In `.github/workflows/ci.yml`, add job:

1. `import-guards`
2. Runs in strict mode with baseline support.
3. Publishes full violation report artifact.

### B6. Local integration

Update:

1. `scripts/ci-local.sh`
2. `scripts/lint.sh`

to run import guard checks in local pipelines.

Acceptance criteria for WP-B:

1. CI blocks net-new anti-pattern imports.
2. Rule IDs and remediation messages are clear.
3. Baseline reaches zero by wave end.

---

## WP-C - Architecture Test Suite

### C1. Create test package skeleton

Create directory:

- `tests/architecture/`

Create modules:

1. `tests/architecture/test_service_structure.py`
2. `tests/architecture/test_layer_boundaries.py`
3. `tests/architecture/test_shared_lib_usage_common.py`
4. `tests/architecture/test_shared_lib_usage_messaging.py`
5. `tests/architecture/test_shared_lib_usage_storage.py`
6. `tests/architecture/test_shared_lib_usage_observability.py`
7. `tests/architecture/test_outbox_dispatcher_contracts.py`
8. `tests/architecture/test_config_patterns.py`

### C2. Add architecture test utilities

Create helper module:

- `tests/architecture/_utils.py`

Helpers:

1. service discovery
2. AST import scanning
3. package path normalization
4. rule assertion wrappers with rich failure messages

### C3. Structure architecture tests

`test_service_structure.py` verifies:

1. canonical folder presence
2. required entry files
3. messaging schema folders where needed

### C4. Layer boundary architecture tests

`test_layer_boundaries.py` verifies:

1. domain imports do not reference infrastructure/api/application
2. application only depends on domain + ports
3. api does not import infrastructure internals directly

### C5. Shared library usage tests

Common usage tests verify:

1. id generation functions from `common.ids`
2. UTC/time helper usage from `common.time`

Messaging usage tests verify:

1. outbox dispatcher inheritance from base pattern where applicable
2. no custom ad-hoc dispatcher loops in mature services

Storage usage tests verify:

1. object storage usage through storage interface/factory
2. no service-local direct MinIO/boto3 unless explicitly allowed adapter

Observability tests verify:

1. logging wrapper usage
2. service lifespan includes observability setup for mature services

### C6. Outbox/dispatcher contract tests

`test_outbox_dispatcher_contracts.py` validates:

1. canonical outbox status values
2. repository protocol method presence
3. lease fields and claim semantics for dispatcher compatibility

### C7. Config pattern tests

`test_config_patterns.py` validates:

1. `Settings` patterns consistent with standards
2. no module-level runtime `Settings()` instantiation in services
3. required observability config fields

### C8. CI integration for architecture tests

Add CI job:

1. `architecture-tests`
2. run `pytest tests/architecture -v --tb=short`
3. place in fast path before heavy integration matrix

Acceptance criteria for WP-C:

1. Architecture tests run in under 2 minutes on CI target.
2. Failures include actionable service/file/rule context.
3. Architecture suite is mandatory in CI.

---

## WP-D - Service Remediation To Pass New Gates

This wave includes fixing all currently detected violations.

### D1. Run validators in report mode

Commands:

1. `python scripts/structure_checks/check_service_structure.py --report-json .tmp/structure.json`
2. `python scripts/import_guards/check_import_guards.py --baseline scripts/import_guards/baseline.json --report-json .tmp/import-guards.json`
3. `pytest tests/architecture -q`

### D2. Prioritized remediation order

Fix services in this order:

1. `content-ingestion`
2. `market-ingestion`
3. `market-data`
4. `portfolio`
5. `alert`
6. `api-gateway`
7. remaining scaffolded services

### D3. Remediation categories

1. structure mismatches
2. forbidden imports
3. outbox/dispatcher deviations
4. storage adapter deviations
5. observability setup deviations
6. config pattern deviations

### D4. Zero-baseline requirement

Before wave close:

1. `scripts/import_guards/baseline.json` must be empty or deleted.
2. `scripts/structure_checks/exceptions.yaml` must contain only approved non-expired exceptions with owners.

Acceptance criteria for WP-D:

1. All validators and architecture tests pass in strict mode.
2. No unmanaged exceptions remain.

---

## WP-E - CI Workflow Updates

### E1. Add or update jobs in `.github/workflows/ci.yml`

Required jobs:

1. `validate-service-structure`
2. `import-guards`
3. `architecture-tests`

### E2. Dependency graph placement

1. New jobs run in fast path alongside lint/validate-schemas.
2. `test-services`, `test-integration`, and `test-e2e` depend on new fast-path jobs.

### E3. Artifact strategy

Each new job uploads:

1. violation JSON report
2. summary text report

### E4. Fail policy

1. strict mode enabled in this wave
2. net-new drift blocked immediately

Acceptance criteria for WP-E:

1. CI graph includes all new jobs.
2. No long-running test jobs start if architecture gates fail.

---

## WP-F - Documentation Synchronization

### F1. Standards references

Ensure scripts and tests reference canonical rules from:

1. `docs/STANDARDS.md`
2. `docs/libs/*.md`

### F2. Developer guide update

Add short section to internal workflow docs indicating:

1. how to run structure checks
2. how to run import guards
3. how to run architecture tests

Acceptance criteria for WP-F:

1. Contributors can run all new gates locally without CI.

---

## 6. Detailed Task List (Execution IDs)

### EPIC-001 - Structure Validation

1. `T-STR-001` Implement `check_service_structure.py` CLI.
2. `T-STR-002` Define canonical rule set and rule IDs.
3. `T-STR-003` Add `exceptions.yaml` with expiry enforcement.
4. `T-STR-004` Add CI job and artifacts.
5. `T-STR-005` Integrate in `ci-local.sh` and `lint.sh`.

### EPIC-002 - Import Guards

1. `T-IG-001` Implement AST scanner engine.
2. `T-IG-002` Create rules.yaml with mandatory anti-pattern rules.
3. `T-IG-003` Implement allowlist mechanism.
4. `T-IG-004` Implement baseline mechanism and diff checks.
5. `T-IG-005` Add CI job and artifacts.
6. `T-IG-006` Integrate local execution command.

### EPIC-003 - Architecture Tests

1. `T-ARCH-001` Create `tests/architecture` skeleton.
2. `T-ARCH-002` Add structure tests.
3. `T-ARCH-003` Add layer boundary tests.
4. `T-ARCH-004` Add common/messaging/storage/observability usage tests.
5. `T-ARCH-005` Add outbox/dispatcher contract tests.
6. `T-ARCH-006` Add settings/config pattern tests.
7. `T-ARCH-007` Add architecture-test CI job.

### EPIC-004 - Service Remediation

1. `T-REM-001` Capture initial violation reports.
2. `T-REM-002` Fix content-ingestion violations.
3. `T-REM-003` Fix market-ingestion violations.
4. `T-REM-004` Fix market-data violations.
5. `T-REM-005` Fix portfolio violations.
6. `T-REM-006` Fix alert and api-gateway violations.
7. `T-REM-007` Fix remaining scaffolded-service violations or add expiring exceptions.
8. `T-REM-008` Reduce baseline to zero.

### EPIC-005 - CI Hardening

1. `T-CI-001` Wire job dependencies to fail fast.
2. `T-CI-002` Validate artifact retention and naming.
3. `T-CI-003` Confirm strict mode enforced by default.

### EPIC-006 - Documentation

1. `T-DOC-001` Align references in docs if rule wording changed.
2. `T-DOC-002` Add local execution instructions for new gates.

---

## 7. Validation Commands (Wave Gates)

Run in this order at least once before completion:

1. `python scripts/structure_checks/check_service_structure.py --strict`
2. `python scripts/import_guards/check_import_guards.py --strict --baseline scripts/import_guards/baseline.json`
3. `pytest tests/architecture -v --tb=short`
4. `./scripts/lint.sh`
5. `./scripts/test-libs.sh`
6. `./scripts/test.sh` (targeted where feasible by changed services)

Wave is not complete until all commands are green.

---

## 8. Definition Of Done (Single-Wave Completion)

All conditions are mandatory:

1. New repo-level structure validator exists, is wired in CI, and runs locally.
2. Import guard system exists, is wired in CI, and runs locally.
3. Architecture test suite exists and is blocking in CI.
4. All existing services either comply or have explicit, non-expired, owned exceptions.
5. Baseline for import violations is zero.
6. CI passes end-to-end on main PR.
7. No deferred TODOs for core enforcement paths.

---

## 9. Risks And Mitigations

1. **Risk:** High initial violation volume.
1. **Mitigation:** baseline file + net-new blocking + same-wave remediation.

2. **Risk:** False positives from AST rules.
1. **Mitigation:** allowlist file and precise adapter-boundary exceptions.

3. **Risk:** CI duration increase.
1. **Mitigation:** keep architecture suite lightweight and in fast path.

4. **Risk:** Standards drift after wave.
1. **Mitigation:** strict blocking gates remain permanent.

---

## 10. Ownership And Execution Notes

1. Assign one owner per epic.
2. Keep commits small and grouped by epic.
3. Run task-scoped checks after each logical change.
4. Do not merge partial enforcement; this wave is atomic by design.

---

## 11. Final Handoff Checklist

1. CI jobs added and passing.
2. Scripts documented and executable.
3. Architecture tests passing.
4. Shared library anti-pattern imports removed.
5. Structure exceptions reviewed and signed off.
6. This wave document retained as the execution source of truth.
