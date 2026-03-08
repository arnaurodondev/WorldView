# Execution Prompt 0001 — shared-libs-migration wave 03

## Context (read first)
- Planning prompt: `docs/ai-interactions/agent-planning/0001-shared-libs-migration-detailed-plan-and-atomic-tasks.md`
- Response (authoritative backlog): `docs/ai-interactions/agent-responses/0001-response-20260306-shared-libs-migration-plan.md`

## Assigned agent profile(s)
- `./claude/agents/data-platform-engineer.md`
- `./claude/agents/architecture-decision-lead.md`

## Mandatory pre-read
- `AGENTS.md`
- `CLAUDE.md`
- `docs/libs/messaging.md`
- `docs/libs/observability.md`
- `docs/architecture/decisions/` (current ADR index + template)
- `docs/ai-interactions/agent-planning/0001-shared-libs-migration-detailed-plan-and-atomic-tasks.md`
- `docs/ai-interactions/agent-responses/0001-response-20260306-shared-libs-migration-plan.md`

## Objective
Complete `messaging` migration (consumer/producer/dispatcher/valkey + package API + tests), finalize two messaging ADRs, and close implementation tracking.

## Task scope for this wave
### Parallel group(s)
- Group A (core independent modules): `T-030`, `T-032`, `T-034`

### Sequential group(s)
- Group B (consumer path): `T-031` (after `T-030` and prior-wave `T-015`)
- Group C (dispatcher path): `T-033` (after `T-032` and prior-wave `T-015`)
- Group D (architecture decisions): `T-035` (after `T-034`), `T-036` (after `T-030`)
- Group E (package completion): `T-037` (after `T-030`..`T-034`), then `T-038` (after `T-030`..`T-037`)

## Why this chunk
This final wave isolates the highest-complexity library (`messaging`) after upstream contract and observability dependencies are already stable, minimizing rework and cross-wave file churn in `libs/messaging`.

## Implementation instructions
Execute only these task IDs: `T-030`..`T-038`.

1. Messaging core modules
   - `T-030`: Implement Kafka consumer error hierarchy and package exports.
   - `T-031`: Implement `BaseKafkaConsumer` and refactor to observability logging/metrics integration.
   - `T-032`: Implement producer, schema registry, serializer, and serialization utilities; reconcile `AvroDictable` protocol conflicts.
   - `T-033`: Implement `BaseOutboxDispatcher` and protocols with observability integration.
   - `T-034`: Implement `ValkeyClient` + config + factories.

2. Messaging architecture docs
   - `T-035`: Author ADR for Valkey key taxonomy + TTL/invalidation conventions.
   - `T-036`: Author ADR for messaging retryable/fatal error classification and operational implications.

3. Messaging package completion
   - `T-037`: Wire root `messaging.__init__` exports and add comprehensive module tests.
   - `T-038`: Mark `libs/messaging/IMPLEMENTATION.md` complete.

4. Dependency/order enforcement
   - Do not execute `T-031` before `T-030`.
   - Do not execute `T-033` before `T-032`.
   - Do not execute `T-035` before `T-034`.
   - Do not execute `T-037` before `T-030`..`T-034`.
   - Do not mark `T-038` complete until all prior messaging tasks and tests are complete.

## Constraints
- Do not implement outside listed task IDs.
- Preserve event/schema compatibility and topic naming conventions.
- Do not introduce duplicate/competing `AvroDictable` protocol definitions.
- Keep `messaging` hard dependency on observability only as specified by task backlog decisions.
- Include a post-wave commit message proposal with a title and 1-2 sentences summarizing implementation and validation.
- Because this is the final wave for scope `0001`, include a highly detailed PR description in the handoff.

## Required tests
- `cd libs/messaging && python -m pytest tests/test_errors.py tests/test_producer.py tests/test_schemas.py tests/test_serializer.py tests/test_valkey.py tests/test_topics.py -v`
- `ruff check libs/messaging`
- `mypy libs/messaging/src`
- Placeholder integration command (if available from prior wave): `bash scripts/test-libs.sh`

Pass criteria:
- All listed tests pass for messaging.
- Public exports are importable from `messaging` root package.
- ADR files are present and complete.

## Documentation requirements
- Likely impacted files:
  - `libs/messaging/IMPLEMENTATION.md`
  - `docs/libs/messaging.md`
  - `docs/architecture/decisions/0004-valkey-key-taxonomy.md`
  - `docs/architecture/decisions/0005-messaging-error-classification.md`
- Mandatory rule: in this same wave, update docs for any behavior/contract/config/schema/API/test-surface change, and list exact files changed in handoff.

## Required handoff evidence
- Exact task IDs completed in this wave.
- Full changed-file list.
- Test commands executed with pass/fail outcomes.
- Docs changed: exact file paths + concise summary of each update.
- Commit message proposal: title + 1-2 sentence body.
- Highly detailed PR description covering scope summary, completed task IDs, grouped changed files, test/lint/type evidence, docs/ADR updates, compatibility/migration notes, risks, rollback guidance, and follow-up items.
- Any unresolved blockers/assumptions.

## Definition of done
- Every task in this wave (`T-030`..`T-038`) is complete and validated.
- Required tests/lint/type checks pass for touched modules.
- Documentation updates are completed in-wave for all relevant changes, or each non-update is explicitly justified as N/A.
- A commit message proposal (title + 1-2 sentence body) is included in the handoff.
- A highly detailed final PR description is included in the handoff.
