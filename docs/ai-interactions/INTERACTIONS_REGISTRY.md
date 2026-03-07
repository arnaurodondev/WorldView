# AI Interactions Registry

Track executed prompt/response pairs for auditability and handoff.

| Date | Prompt ID | Prompt File | Response File | Manifest File | Scope | Status | Orchestrator | Reviewer |
|------|-----------|-------------|---------------|---------------|-------|--------|--------------|----------|
| 2026-03-07 | 0001 | `agent-prompts/0001-shared-libs-migration-detailed-plan-and-atomic-tasks.md` | `agent-responses/0001-response-20260306-shared-libs-migration-plan.md` | `execution-manifests/M-0001-shared-libs-full.yaml` | shared libs full backlog (M1 common already extracted) | planned | unassigned | unassigned |
| 2026-03-07 | 0002 | `agent-prompts/0002-portfolio-migration-detailed-plan-and-atomic-tasks.md` | `agent-responses/0002-response-20260306-portfolio-migration-plan.md` | `execution-manifests/M-0002-portfolio-full.yaml` | portfolio migration full backlog | planned | unassigned | unassigned |
| 2026-03-07 | 0003 | `agent-prompts/0003-market-ingestion-migration-detailed-plan-and-atomic-tasks.md` | `agent-responses/0003-response-20260306-market-ingestion-migration-plan.md` | `execution-manifests/M-0003-market-ingestion-full.yaml` | market-ingestion migration full backlog | planned | unassigned | unassigned |
| 2026-03-07 | 0004 | `agent-prompts/0004-market-data-migration-detailed-plan-and-atomic-tasks.md` | `agent-responses/0004-response-20260306-market-data-migration-plan.md` | `execution-manifests/M-0004-market-data-full.yaml` | market-data migration full backlog | planned | unassigned | unassigned |
| YYYY-MM-DD | 0001 | `agent-prompts/0001-...md` | `agent-responses/0001-response-YYYYMMDD-...md` | `execution-manifests/M-0001-...yaml` | short scope | planned | name | name |

## Usage

1. Add an entry when a prompt execution starts.
2. Add a manifest file before assigning worker tasks.
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
