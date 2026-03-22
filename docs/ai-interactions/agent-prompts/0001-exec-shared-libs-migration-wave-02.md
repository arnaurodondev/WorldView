> **STATUS: IMPLEMENTED** — All tasks in this wave have been completed and merged. See git history for implementation evidence.

# Execution Prompt 0001 — shared-libs-migration wave 02

## Context (read first)
- Planning prompt: `docs/ai-interactions/agent-planning/0001-shared-libs-migration-detailed-plan-and-atomic-tasks.md`
- Response (authoritative backlog): `docs/ai-interactions/agent-responses/0001-response-20260306-shared-libs-migration-plan.md`

## Assigned agent profile(s)
- `./claude/agents/data-platform-engineer.md`
- `./claude/agents/architecture-decision-lead.md`

## Mandatory pre-read
- `AGENTS.md`
- `CLAUDE.md`
- `docs/libs/observability.md`
- `docs/libs/storage.md`
- `docs/developer-guide/` (relevant testing workflow docs)
- `docs/ai-interactions/agent-planning/0001-shared-libs-migration-detailed-plan-and-atomic-tasks.md`
- `docs/ai-interactions/agent-responses/0001-response-20260306-shared-libs-migration-plan.md`

## Objective
Complete `observability` and `storage` migrations with full module/test coverage, add the observability ADR, and establish the shared infra scaffold for library integration testing.

## Task scope for this wave
### Parallel group(s)
- Group A (`observability` foundations): `T-015`, `T-016`, `T-017`
- Group B (`storage` foundations): `T-022`, `T-025`
- Group C (integration scaffolding): `T-040`

### Sequential group(s)
- Group D (`observability` completion): `T-018` (after `T-015`), `T-019` (after `T-016`), `T-020` (after `T-015`,`T-016`), then `T-021` (after `T-015`..`T-020`)
- Group E (`storage` completion): `T-023` (after `T-022`), `T-024` (after `T-022`,`T-023`), `T-026` (after `T-022`), `T-027` (after `T-024`,`T-025`), `T-028` (after `T-022`..`T-027`), then `T-029` (after `T-022`..`T-028`)

## Why this chunk
This wave groups cross-cutting runtime foundations (telemetry, object storage, and infra test harness) that have high internal file overlap and minimal dependency on messaging implementation, reducing churn before the final messaging wave.

## Implementation instructions
Execute only these task IDs: `T-015`..`T-029`, `T-040`.

1. `observability` build-out
   - `T-015`: Implement/export metrics module (`ServiceMetrics`, factory, middleware).
   - `T-016`: Implement/export tracing module (`configure_tracing`, tracer access, middleware).
   - `T-017`: Add tests for existing logging module behavior.
   - `T-018`: Add metrics tests (registry isolation, middleware behavior).
   - `T-019`: Add tracing tests (export path + context propagation).
   - `T-020`: Author ADR for observability stack decision.
   - `T-021`: Mark `libs/observability/IMPLEMENTATION.md` complete.

2. `storage` build-out
   - `T-022`: Implement unified storage exception hierarchy and migrate key-builder exception usage.
   - `T-023`: Implement `ObjectStorage` ABC.
   - `T-024`: Implement `S3ObjectStorage` adapter with error mapping and structured logging.
   - `T-025`: Expand `StorageSettings` to full model + computed properties.
   - `T-026`: Expand `KeyBuilder` to parity (`KeyComponents`, parsing, prefixes, validations).
   - `T-027`: Implement factory and health-check modules.
   - `T-028`: Wire storage package exports and add comprehensive tests.
   - `T-029`: Mark `libs/storage/IMPLEMENTATION.md` complete.

3. Integration scaffold
   - `T-040`: Add/confirm compose profile for lib-level integration infra and create `scripts/test-libs.sh` workflow.

4. Dependency/order enforcement
   - Do not execute `T-018` before `T-015`; do not execute `T-019` before `T-016`.
   - Do not execute `T-024` before `T-022` and `T-023`.
   - Do not execute `T-027` before `T-024` and `T-025`.
   - Do not mark `T-021`/`T-029` complete until all prerequisite implementation + tests pass.

## Constraints
- Do not implement outside listed task IDs.
- Keep storage and observability APIs consistent with current docs unless task explicitly modifies them.
- Use structured logging (`structlog`) across new modules.
- Keep integration scaffold additive; do not break existing compose profiles.
- Include a post-wave commit message proposal with a title and 1-2 sentences summarizing implementation and validation.

## Required tests
- `cd libs/observability && python -m pytest tests/test_logging.py tests/test_metrics.py tests/test_tracing.py -v`
- `cd libs/storage && python -m pytest tests/test_exceptions.py tests/test_interface.py tests/test_s3_adapter.py tests/test_settings.py tests/test_keys.py tests/test_health.py -v`
- `ruff check libs/observability libs/storage`
- `mypy libs/observability/src libs/storage/src`
- `bash scripts/test-libs.sh` (or explicit placeholder command sequence if script is first introduced and needs one bootstrap run)

Pass criteria:
- All listed tests pass.
- ADR file is present and complete.
- Integration scaffold command executes with deterministic success/failure output.

## Documentation requirements
- Likely impacted files:
  - `libs/observability/IMPLEMENTATION.md`
  - `libs/storage/IMPLEMENTATION.md`
  - `docs/libs/observability.md`
  - `docs/libs/storage.md`
  - `docs/architecture/decisions/0003-observability-stack.md`
  - `docs/developer-guide/*` or `README.md` for `test-libs` workflow
- Mandatory rule: in this same wave, update docs for any behavior/contract/config/schema/API/test-surface change, and list exact files changed in handoff.

## Required handoff evidence
- Exact task IDs completed in this wave.
- Full changed-file list.
- Test commands executed with pass/fail outcomes.
- Docs changed: exact file paths + concise summary of each update.
- Commit message proposal: title + 1-2 sentence body.
- Any unresolved blockers/assumptions.

## Definition of done
- Every task in this wave (`T-015`..`T-029`, `T-040`) is complete and validated.
- Required tests/lint/type checks pass for touched modules.
- Documentation updates are completed in-wave for all relevant changes, or each non-update is explicitly justified as N/A.
- A commit message proposal (title + 1-2 sentence body) is included in the handoff.
