# Agent Navigation Guide

Last updated: 2026-03-24

## Purpose

This guide helps implementation agents navigate the worldview monorepo and execute work in a spec-driven, auditable way.

## Read Order

1. `AGENTS.md`
2. `RULES.md`
3. `docs/MASTER_PLAN.md`
4. `docs/ai-interactions/BUG_PATTERNS.md`
5. relevant service docs in `docs/services/`

## Workflow: Plan to Completion

### 1) Planning

- define scope and write_paths
- define task-scoped validation commands
- identify affected contracts (Avro/OpenAPI)

Use:

- `docs/ai-interactions/agent-planning/PLANNING_TEMPLATE.md`
- `docs/ai-interactions/agent-planning/PLANNING_CHECKLIST.md`

### 2) Task Definition

- break plan into atomic tasks with clear preconditions/postconditions
- define measurable acceptance criteria

Use:

- `docs/ai-interactions/task-definition/TASK_TEMPLATE.md`
- `docs/ai-interactions/task-definition/TASK_CHECKLIST.md`

### 3) Implementation

- follow service architecture boundaries
- avoid cross-service DB access
- use outbox pattern for dual-write paths
- keep diffs focused and validate each logical change immediately

Use:

- `docs/ai-interactions/implementation/VALIDATION_CHECKLIST.md`

### 4) Validation

Run the smallest sufficient gate first:

1. directly affected tests
2. changed-path lint
3. changed-package type checks
4. wider suite as needed

### 5) Completion

- update docs for API/event/config changes
- record issues and fixes in debugging log
- archive plan/task summaries

## Navigation Pointers

Question | Primary location
--------|-------------------
Where are event schemas? | `infra/kafka/schemas/`
Where are compose test profiles? | `infra/compose/docker-compose.test.yml`
Where are service tests? | `services/<service>/tests/`
Where are shared lib tests? | `libs/<lib>/tests/`
How does CI run tests? | `.github/workflows/ci.yml`
Known recurring bugs? | `docs/ai-interactions/BUG_PATTERNS.md`

## Agent Anti-Patterns

- implementing before reading hard rules
- adding cross-service imports to bypass contracts
- skipping contract tests when touching APIs/events
- reporting completion without green task-scoped gates
