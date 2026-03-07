# Prompt 0002 — Portfolio migration detailed plan + atomic tasks

Act as both the Backend Engineer (.claude/agents/backend-engineer.md) and Architecture Decision Lead (.claude/agents/architecture-decision-lead.md).

## Goal

Generate a highly detailed migration/completion plan (NO code) for Portfolio in worldview, then break it into single, independent, execution-ready tasks including tests.

## Directories to scan (mandatory)

### Legacy

- `platform_repo/apps/backend-portfolio/**`
- `platform_repo/libs/**` (shared dependency usage only)

### Target

- `worldview/services/portfolio/**`
- `worldview/libs/common/**`
- `worldview/libs/contracts/**`
- `worldview/libs/messaging/**`
- `worldview/libs/storage/**`
- `worldview/libs/observability/**`
- `worldview/docs/services/portfolio.md`
- `worldview/docs/migration/REUSE_FROM_ORIGINAL_THESIS.md`
- `worldview/docs/architecture/**`
- `worldview/docs/libs/**`

## Plan coverage (mandatory)

- Bounded context and ownership validation
- Module-by-module migration map:
  - domain
  - application/use_cases
  - api/routes/schemas
  - infrastructure/db
  - infrastructure/messaging
  - consumers
  - outbox dispatcher
- Missing feature gap list vs target spec
- DB/Alembic regeneration strategy
- Event contracts/topic mapping and compatibility checks
- Idempotency + outbox invariants
- DI/configuration/settings migration
- Observability integration
- Security and tenant isolation checks
- Local/dev/prod readiness
- Rollout + rollback plan

## Testing requirements (must be task-level)

- Unit tests (domain/use-cases)
- Service container tests (API + DB + messaging integration)
- Platform QA scenarios involving Portfolio cross-service flows

## Output format (strict)

1. Current-state inventory
2. Target-state checklist from docs
3. Gap matrix with severity and dependency
4. Atomic task backlog (independent tickets), each with:
   - ID, title, objective
   - Search paths and expected touched paths
   - Prerequisites/dependencies
   - Exact implementation steps
   - Tests required (unit/container/platform)
   - DoD
   - Risks and rollback notes
   - Effort (S/M/L)
5. Suggested execution sequence + critical path
6. Release readiness criteria
