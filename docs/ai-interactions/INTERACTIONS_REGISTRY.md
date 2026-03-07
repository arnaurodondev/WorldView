# AI Interactions Registry

Track executed prompt/response pairs for auditability and handoff.

| Date | Prompt ID | Prompt File | Response File | Scope | Status | Orchestrator | Reviewer |
|------|-----------|-------------|---------------|-------|--------|--------------|----------|
| 2026-03-07 | 0001 | `agent-planning/0001-shared-libs-migration-detailed-plan-and-atomic-tasks.md` | `agent-responses/0001-response-20260306-shared-libs-migration-plan.md` | shared libs full backlog + exec prompt `agent-prompts/0001-exec-shared-libs-wave-01.md` | planned | unassigned | unassigned |
| 2026-03-07 | 0002 | `agent-planning/0002-portfolio-migration-detailed-plan-and-atomic-tasks.md` | `agent-responses/0002-response-20260306-portfolio-migration-plan.md` | portfolio migration full backlog + exec prompt `agent-prompts/0002-exec-portfolio-wave-01.md` | planned | unassigned | unassigned |
| 2026-03-07 | 0003 | `agent-planning/0003-market-ingestion-migration-detailed-plan-and-atomic-tasks.md` | `agent-responses/0003-response-20260306-market-ingestion-migration-plan.md` | market-ingestion full backlog + exec prompt `agent-prompts/0003-exec-market-ingestion-wave-01.md` | planned | unassigned | unassigned |
| 2026-03-07 | 0004 | `agent-planning/0004-market-data-migration-detailed-plan-and-atomic-tasks.md` | `agent-responses/0004-response-20260306-market-data-migration-plan.md` | market-data full backlog + exec prompt `agent-prompts/0004-exec-market-data-wave-01.md` | planned | unassigned | unassigned |
| YYYY-MM-DD | 0001 | `agent-planning/0001-...md` | `agent-responses/0001-response-YYYYMMDD-...md` | short scope | planned | name | name |

## Usage

1. Add an entry when a prompt execution starts.
2. Add execution prompt file(s) before assigning worker tasks.
3. Update status as execution progresses.
4. Link final response artifact and reviewer when completed.

## Status taxonomy

- `planned`
- `ready`
- `in-progress`
- `review`
- `blocked`
- `done`
- `cancelled`
