# Prompt 0003 — Market Ingestion migration detailed plan + atomic tasks

Act as both the Data Platform Engineer (.claude/agents/data-platform-engineer.md) and Architecture Decision Lead (.claude/agents/architecture-decision-lead.md).

## Goal

Produce a highly detailed migration and completion plan (NO code) for Market Ingestion, then decompose it into independent atomic tasks with full testing requirements.

## Directories to scan (mandatory)

### Legacy

- `platform_repo/apps/backend-market-ingestion/**`
- `platform_repo/libs/**` (dependency usage only)

### Target

- `worldview/services/market-ingestion/**`
- `worldview/libs/common/**`
- `worldview/libs/contracts/**`
- `worldview/libs/messaging/**`
- `worldview/libs/storage/**`
- `worldview/libs/observability/**`
- `worldview/docs/services/market-ingestion.md`
- `worldview/docs/migration/REUSE_FROM_ORIGINAL_THESIS.md`
- `worldview/docs/architecture/**`
- `worldview/docs/libs/**`

## Plan coverage (mandatory)

- Scheduler/worker/outbox process mapping
- Provider adapter migration strategy
- Canonicalization and claim-check pipeline
- MinIO bronze/silver conventions
- Task lifecycle, leasing/claiming semantics
- Retry/backoff/error taxonomy
- Policy/budget/watermark migration
- Kafka pointer-event production + schema compatibility
- DB/Alembic regeneration
- SLIs/SLOs + observability hooks
- Replay/backfill strategy
- Deployment cutover/rollback

## Testing requirements (must be task-level)

- Unit tests (domain/use-cases/transformers)
- Service container tests (worker + DB + MinIO + Kafka)
- Platform QA scenarios (ingestion to downstream materialization path)

## Output format (strict)

1. Current-state architecture map
2. Target-state requirements matrix
3. Delta analysis and risk table
4. Atomic independent ticket backlog, each with:
   - ID, title, objective
   - Paths to read/paths to change
   - Dependencies
   - Step-by-step actions
   - Tests (unit/container/platform)
   - Acceptance criteria / DoD
   - Effort and risk mitigation
5. Sequenced roadmap by milestones
6. Operational go-live checklist
