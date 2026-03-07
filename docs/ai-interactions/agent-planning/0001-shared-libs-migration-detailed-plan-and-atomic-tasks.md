# Prompt 0001 — Shared libs migration detailed plan + atomic tasks

Act as both the Data Platform Engineer (.claude/agents/data-platform-engineer.md) and Architecture Decision Lead (.claude/agents/architecture-decision-lead.md).

## Goal

Produce a highly detailed migration execution plan (NO code) for shared libraries, then decompose it into single, independent, implementation-ready tasks.

## Scope order (mandatory)

1. `common`
2. `contracts`
3. `observability` (new)
4. `storage` (S3/MinIO)
5. `messaging` (Kafka + Valkey/Redis)

## Directories to scan (mandatory)

### Legacy

- `platform_repo/libs/common/**`
- `platform_repo/libs/contracts/**`
- `platform_repo/libs/storage/**`
- `platform_repo/libs/messaging/**`
- `platform_repo/apps/**` (only to discover library usage patterns)

### Target

- `worldview/libs/common/**`
- `worldview/libs/contracts/**`
- `worldview/libs/observability/**`
- `worldview/libs/storage/**`
- `worldview/libs/messaging/**`
- `worldview/docs/libs/**`
- `worldview/docs/architecture/**`
- `worldview/docs/migration/REUSE_FROM_ORIGINAL_THESIS.md`
- `worldview/AGENTS.md`
- `worldview/CLAUDE.md`
- `worldview/.claude/agents/architecture-decision-lead.md`
- `worldview/.claude/agents/data-platform-engineer.md`

## Mandatory documentation behavior

- Read relevant documentation before producing the plan.
- If implementation tasks would alter behavior/contracts/config/schema/API, include explicit documentation update tasks.
- Include documentation acceptance criteria in each relevant ticket.

## What the plan MUST include

- Reuse-vs-rewrite inventory per module/file
- Target package/API structure and compatibility rules
- Kafka topic/schema/versioning tasks (Avro forward-compatibility)
- MinIO keying + claim-check standards
- Valkey key taxonomy, TTL conventions, invalidation strategy
- Observability design tasks: structlog + Prometheus + Grafana/Loki integration path
- ADR requirements and decision checkpoints
- Sequencing with dependency graph and critical path
- Rollout/rollback/backfill strategy
- Risk register + assumptions + unknowns

## Testing requirements (must be embedded in tasks)

- Unit tests
- Service/container-level integration tests for libs consumers
- Platform QA implications and verification hooks

## Output format (strict)

1. Executive summary (max 12 bullets)
2. Gap analysis table: legacy vs target vs delta
3. Dependency graph (text form)
4. Task backlog of atomic tickets (independent where possible), each ticket with:
   - ID
   - Title
   - Objective
   - Why now
   - Exact directories/files touched
   - Prerequisites
   - Step-by-step implementation actions
   - Tests: unit + container/integration + platform QA impact
   - Documentation updates required
   - Definition of Done
   - Risks/mitigations
   - Effort estimate (S/M/L) and owner profile
5. Milestones and release gates
6. Open questions requiring human decision

## Response artifact required

After execution, create a response report in:

- `worldview/docs/ai-interactions/agent-responses/`

Using filename:

- `0001-response-<YYYYMMDD>-<short-scope>.md`

The response must include: what was implemented, how it was implemented, and why decisions were made.

Also generate implementation prompt files in:

- `worldview/docs/ai-interactions/agent-prompts/`

Each generated implementation prompt must:

- reference the response file as authoritative context
- specify exact task IDs to execute
- separate tasks into parallelizable and sequential groups
- include required test commands, docs update requirements, and evidence to report
