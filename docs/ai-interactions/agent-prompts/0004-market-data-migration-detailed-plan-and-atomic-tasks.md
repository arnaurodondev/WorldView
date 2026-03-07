# Prompt 0004 — Market Data migration detailed plan + atomic tasks

Act as both the Data Platform Engineer (.claude/agents/data-platform-engineer.md) and Architecture Decision Lead (.claude/agents/architecture-decision-lead.md).

## Goal

Create a highly detailed migration/completion plan (NO code) for Market Data in worldview, then break it into independent implementation tasks including all test layers.

## Directories to scan (mandatory)

### Legacy

- `platform_repo/apps/backend-market-data/**`
- `platform_repo/libs/**` (dependency usage only)

### Target

- `worldview/services/market-data/**`
- `worldview/libs/common/**`
- `worldview/libs/contracts/**`
- `worldview/libs/messaging/**`
- `worldview/libs/storage/**`
- `worldview/libs/observability/**`
- `worldview/docs/services/market-data.md`
- `worldview/docs/migration/REUSE_FROM_ORIGINAL_THESIS.md`
- `worldview/docs/architecture/**`
- `worldview/docs/libs/**`
- `worldview/AGENTS.md`
- `worldview/CLAUDE.md`

## Mandatory documentation behavior

- Read relevant documentation before producing the plan.
- Add documentation update tasks for all behavior/API/event/config/schema changes.
- Include doc acceptance criteria in task DoD where applicable.

## Plan coverage (mandatory)

- Consumer-by-consumer migration:
  - OHLCV materializer
  - quotes consumer
  - fundamentals consumer
- TimescaleDB schema + hypertable migration tasks
- Claim-check materialization/parsing flow
- API parity and gap analysis
- Caching strategy and invalidation tasks
- Instrument lifecycle event emission
- Idempotency and failed-task recovery
- Query-layer refactor plan
- Observability requirements
- Performance validation plan
- Contract/versioning checks
- Staged rollout and rollback

## Testing requirements (must be task-level)

- Unit tests (parsing/mapping/domain logic)
- Service container tests (consumer/API + TimescaleDB + Kafka + object store)
- Platform QA scenarios (ingestion -> market-data APIs -> downstream consumers)

## Output format (strict)

1. Legacy capability inventory
2. Target capability checklist
3. Gap + risk matrix (with severity)
4. Atomic independent ticket backlog, each with:
   - ID, title, objective
   - Paths to inspect and paths to modify
   - Dependencies/prerequisites
   - Implementation steps
   - Tests by layer (unit/container/platform)
   - Documentation updates required
   - DoD/acceptance criteria
   - Effort estimate + risk controls
5. Milestone-based execution plan and critical path
6. Release gate checklist and rollback triggers

## Response artifact required

After execution, create a response report in:

- `worldview/docs/ai-interactions/agent-responses/`

Using filename:

- `0004-response-<YYYYMMDD>-<short-scope>.md`

The response must include: what was implemented, how it was implemented, and why decisions were made.

Also create or update:

- `worldview/docs/ai-interactions/execution-manifests/<manifest-id>.yaml`

The manifest must include atomic task states, dependencies, allowed parallelism, required test commands, and evidence requirements.
