# AI Agent Prompt Library (Canonical)

This directory stores reusable prompts for AI agents.

## Naming Convention

`<id>-<short-purpose>.md`

- `id` is a 4-digit sequence (`0000`, `0001`, ...)
- filenames should be descriptive and scoped
- prompts must be self-contained and include required search paths

## Mandatory Prompt Rule

Every prompt must instruct the agent to:

1. Read relevant documentation before coding/planning.
2. Update docs when any implementation changes behavior, API, events, config, or schema.
3. Produce a response report in `docs/ai-interactions/agent-responses/` using the prompt ID.
4. Produce or update an execution manifest in `docs/ai-interactions/execution-manifests/`.

## Execution Standard

- Use orchestration model: 1 orchestrator + N workers.
- Enforce task state transitions per `../EXECUTION_STATE_MODEL.md`.
- Require manifest evidence and checklist pass before task closure.

## Current Prompt Set

| ID | Prompt | Purpose |
|----|--------|---------|
| 0001 | `0001-shared-libs-migration-detailed-plan-and-atomic-tasks.md` | Shared libraries migration planning |
| 0002 | `0002-portfolio-migration-detailed-plan-and-atomic-tasks.md` | Portfolio migration planning |
| 0003 | `0003-market-ingestion-migration-detailed-plan-and-atomic-tasks.md` | Market Ingestion migration planning |
| 0004 | `0004-market-data-migration-detailed-plan-and-atomic-tasks.md` | Market Data migration planning |
| 0005 | `0005-generic-implementation-plan-and-task-breakdown-template.md` | Generic execution-ready planning prompt |

## Notes

- This library is not limited to migration prompts.
- Add future prompts with the next ID and clear scope in filename/title.
