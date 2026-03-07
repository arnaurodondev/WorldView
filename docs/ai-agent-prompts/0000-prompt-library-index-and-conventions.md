# AI Agent Prompt Library

> Moved: the canonical prompt/response workflow is now under
> `docs/ai-interactions/`.
> Use `docs/ai-interactions/agent-prompts/` and
> `docs/ai-interactions/agent-responses/`.

This directory stores reusable prompts for AI agents.

## Naming Convention

`<id>-<short-purpose>.md`

- `id` is a 4-digit sequence (`0000`, `0001`, ...)
- filenames should be descriptive and scoped
- prompts should be self-contained and include required search paths

## Current Prompt Set

| ID | Prompt | Purpose |
|----|--------|---------|
| 0001 | `0001-shared-libs-migration-detailed-plan-and-atomic-tasks.md` | Shared libraries migration planning |
| 0002 | `0002-portfolio-migration-detailed-plan-and-atomic-tasks.md` | Portfolio migration planning |
| 0003 | `0003-market-ingestion-migration-detailed-plan-and-atomic-tasks.md` | Market Ingestion migration planning |
| 0004 | `0004-market-data-migration-detailed-plan-and-atomic-tasks.md` | Market Data migration planning |

## Notes

- This library is not limited to migration prompts.
- Add future prompts with the next ID and clear scope in filename/title.
