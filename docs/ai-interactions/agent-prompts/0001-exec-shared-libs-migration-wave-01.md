# Execution Prompt 0001 — shared-libs-migration wave 01

## Context (read first)
- Planning prompt: `docs/ai-interactions/agent-planning/0001-shared-libs-migration-detailed-plan-and-atomic-tasks.md`
- Response (authoritative backlog): `docs/ai-interactions/agent-responses/0001-response-20260306-shared-libs-migration-plan.md`

## Assigned agent profile(s)
- `./claude/agents/data-platform-engineer.md`
- `./claude/agents/architecture-decision-lead.md`

## Mandatory pre-read
- `AGENTS.md`
- `CLAUDE.md`
- `docs/libs/common.md`
- `docs/libs/contracts.md`
- `docs/ai-interactions/agent-planning/0001-shared-libs-migration-detailed-plan-and-atomic-tasks.md`
- `docs/ai-interactions/agent-responses/0001-response-20260306-shared-libs-migration-plan.md`

## Objective
Complete the `common` and `contracts` library migrations end-to-end, including canonical model parity, parsing utilities, contract alignment checks, full test coverage for this scope, and implementation status updates.

## Task scope for this wave
### Parallel group(s)
- Group A (`common` foundations): `T-001`, `T-004`
- Group B (`contracts` foundations): `T-006`, `T-007`, `T-008`, `T-009`

### Sequential group(s)
- Group C (`common` follow-up): `T-002`, `T-003` (after `T-001`), then `T-005` (after `T-001`..`T-004`)
- Group D (`contracts` completion): `T-010`, `T-011`, `T-012` (after `T-006`), `T-013` (after `T-007`), `T-039` (after `T-007`..`T-012`), then `T-014` (after `T-006`..`T-013`)

## Why this chunk
This chunk keeps context tightly focused on foundational data models and utility contracts, resolves all prerequisites internal to `common`/`contracts`, and front-loads schema/model validation (`T-039`) before downstream libs depend on these contracts.

## Implementation instructions
Execute only these task IDs: `T-001`..`T-014`, `T-039`.

1. `common` API + tests + completion
   - `T-001`: Wire `ids` and `types` exports in `libs/common/src/common/__init__.py` and `__all__`.
   - `T-002`: Create `libs/common/tests/test_ids.py` with UUID/ULID behavior and ordering checks.
   - `T-003`: Create `libs/common/tests/test_types.py` validating all `NewType` aliases and `JsonDict` usage patterns.
   - `T-004`: Expand `libs/common/tests/test_time.py` to close legacy edge-case coverage gap.
   - `T-005`: Mark `libs/common/IMPLEMENTATION.md` complete after code/tests pass.

2. `contracts` versions + canonical models + parsing
   - `T-006`: Add and re-export `MARKET_DATASET_FETCHED_SCHEMA_VERSION` in versions and package init.
   - `T-007`: Reconcile `CanonicalOHLCVBar` field parity (`provider`, `timeframe`, `fetched_at`) while keeping `float`; update tests.
   - `T-008`: Implement/export/test `CanonicalQuote`.
   - `T-009`: Implement/export/test `CanonicalFundamentals`.
   - `T-010`: Implement/export/test new `CanonicalArticle` aligned with Avro.
   - `T-011`: Implement/export/test new `CanonicalEntity`.
   - `T-012`: Implement/export/test new `CanonicalSentiment`.
   - `T-013`: Implement/export/test `contracts/parsing.py` (JSONL/JSON/Parquet) with current logging conventions.
   - `T-039`: Add `libs/contracts/tests/test_avro_alignment.py` validating canonical model `to_dict()` outputs against Avro schemas.
   - `T-014`: Mark `libs/contracts/IMPLEMENTATION.md` complete after all contract tasks/tests pass.

3. Dependency/order enforcement
   - Do not start `T-002`/`T-003` before `T-001`.
   - Do not start `T-010`/`T-011`/`T-012` before `T-006`.
   - Do not start `T-013` before `T-007`.
   - Do not mark `T-005`/`T-014` complete until all respective prerequisite tasks are complete and verified.

## Constraints
- Do not implement outside listed task IDs.
- Maintain backward compatibility unless the task explicitly changes behavior.
- Keep Avro compatibility additive; do not rename/remove schema fields.
- Preserve package public API conventions (`__init__` re-exports + `__all__`).
- Include a post-wave commit message proposal with a title and 1-2 sentences summarizing implementation and validation.

## Required tests
- `cd libs/common && python -m pytest tests/test_ids.py -v`
- `cd libs/common && python -m pytest tests/test_types.py -v`
- `cd libs/common && python -m pytest tests/test_time.py -v`
- `cd libs/contracts && python -m pytest tests/test_ohlcv.py tests/test_quotes.py tests/test_fundamentals.py tests/test_article.py tests/test_entity.py tests/test_sentiment.py tests/test_parsing.py tests/test_avro_alignment.py -v`
- `ruff check libs/common libs/contracts`
- `mypy libs/common/src libs/contracts/src`

Pass criteria:
- All listed test commands pass.
- No lint/type errors in touched modules.
- `T-005` and `T-014` reflect completion state accurately.

## Documentation requirements
- Likely impacted files:
  - `libs/common/IMPLEMENTATION.md`
  - `libs/contracts/IMPLEMENTATION.md`
  - `docs/libs/common.md` (if public API/export behavior changed)
  - `docs/libs/contracts.md` (OHLCV parity note, parsing/API updates)
- Mandatory rule: in this same wave, update docs for any behavior/contract/config/schema/API/test-surface change, and list exact files changed in handoff.

## Required handoff evidence
- Exact task IDs completed in this wave.
- Full changed-file list.
- Test commands executed with pass/fail outcomes.
- Docs changed: exact file paths + concise summary of each update.
- Commit message proposal: title + 1-2 sentence body.
- Any unresolved blockers/assumptions.

## Definition of done
- Every task in this wave (`T-001`..`T-014`, `T-039`) is complete and validated.
- Tests/lint/type checks pass for this scope.
- Documentation updates are completed in-wave for all relevant changes, or each non-update is explicitly justified as N/A.
- A commit message proposal (title + 1-2 sentence body) is included in the handoff.
