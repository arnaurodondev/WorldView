# AI Interactions

This directory is the canonical location for AI-driven execution artifacts.

## Structure

- `agent-planning/`: planning prompts that produce detailed plans/task backlogs
- `agent-responses/`: planning responses linked to a prompt ID
- `agent-prompts/`: execution prompts for implementation agents (derived from plans)
- `INTERACTIONS_REGISTRY.md`: audit log of prompt/response executions

## Required Workflow

1. Select or create a planning prompt in `agent-planning/`.
2. Execute the planning prompt with an AI agent.
3. Store the planning output as an agent response in `agent-responses/`.
4. Generate execution prompts in `agent-prompts/` using that planning response as source context.
5. Execute implementation prompts with AI agent(s).
6. Append implementation evidence/results to the corresponding response artifact in `agent-responses/`.
7. Register the run in `INTERACTIONS_REGISTRY.md`.
8. Validate the final response using `agent-responses/0001-review-checklist.md`.

## Orchestration Model

- Topology: **1 orchestrator + N workers**
- Worker scope: one atomic task at a time
- Orchestrator scope: assignment, dependency control, quality gates, final acceptance

Reference docs:

- `ORCHESTRATOR_RUNBOOK.md`

## Response Naming Rule

Use:

`<prompt-id>-response-<YYYYMMDD>-<short-scope>.md`

Example:

`0002-response-20260306-portfolio-domain-migration.md`

## Documentation Consistency Rule

All agents must:

- read relevant docs before implementation (`AGENTS.md`, `CLAUDE.md`, service/lib docs)
- update documentation when behavior/contracts/config/schema/API changes
- include doc updates in the response report

## Useful Templates

- Generic planning template: `agent-planning/0005-generic-implementation-plan-and-task-breakdown-template.md`
- Execution prompt index: `agent-prompts/0000-execution-prompt-index-and-conventions.md`
- Response template: `agent-responses/0000-response-template.md`
- Review checklist: `agent-responses/0001-review-checklist.md`
- Evidence add-on template: `agent-responses/0002-response-evidence-addon-template.md`
