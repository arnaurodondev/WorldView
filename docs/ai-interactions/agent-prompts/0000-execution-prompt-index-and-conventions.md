# AI Execution Prompt Library (Canonical)

This directory stores implementation prompts for execution agents.

## Naming Convention

`<id>-exec-<scope>-wave-<nn>.md`

- `id` is 4-digit (`0001`, `0002`, ...)
- `scope` is the initiative (shared-libs, portfolio, market-ingestion, market-data)
- `wave` identifies the execution batch order

## Mandatory Prompt Requirements

Every execution prompt must include:

1. Source planning context links:
   - `agent-planning/<id>-...md`
   - `agent-responses/<id>-response-...md`
2. Exact task IDs to implement in this wave.
3. Parallel group vs sequential group.
4. Required tests and pass criteria.
5. Documentation updates required (mandatory for any behavior/API/event/config/schema/test-surface change).
6. Handoff evidence required in response artifacts.

## Mandatory documentation rule

Each execution prompt must explicitly state:

- update documentation in the same wave when implementation changes behavior/contracts/config/schema/API/tests
- list exact documentation files updated in handoff evidence
- if no docs are changed, include explicit `N/A` justification

## Current Execution Prompt Set

| ID | File | Purpose |
|----|------|---------|
| 0000 | `0000-exec-wave-generation-template.md` | Generic template to generate full-coverage wave prompts |
| 0001 | `0001-exec-wave-shared-libs-migration-plan.md` | Wave-generation prompt for shared libs response |
| 0002 | `0002-exec-wave-portfolio-migration-plan.md` | Wave-generation prompt for portfolio response |
| 0003 | `0003-exec-wave-market-ingestion-migration-plan.md` | Wave-generation prompt for market-ingestion response |
| 0004 | `0004-exec-wave-market-data-migration-plan.md` | Wave-generation prompt for market-data response |
