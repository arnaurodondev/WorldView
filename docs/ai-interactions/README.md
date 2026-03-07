# AI Interactions

This directory is the canonical location for AI-driven execution artifacts.

## Structure

- `agent-prompts/`: reusable prompts for AI agents
- `agent-responses/`: execution responses linked to a prompt ID
- `execution-manifests/`: machine-operable task plans for orchestrator + workers
- `INTERACTIONS_REGISTRY.md`: audit log of prompt/response executions

## Required Workflow

1. Select a prompt in `agent-prompts/`.
2. Execute it with an AI agent.
3. Store outputs in code/docs as needed.
4. Add a response report in `agent-responses/` with the same prompt ID prefix.
5. Register the run in `INTERACTIONS_REGISTRY.md`.
6. Validate the response using `agent-responses/0001-review-checklist.md`.
7. Attach or link an execution manifest for atomic task execution.

## Orchestration Model

- Topology: **1 orchestrator + N workers**
- Worker scope: one atomic task at a time
- Orchestrator scope: assignment, dependency control, quality gates, final acceptance

Reference docs:

- `ORCHESTRATOR_RUNBOOK.md`
- `EXECUTION_STATE_MODEL.md`
- `execution-manifests/README.md`

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

- Generic prompt template: `agent-prompts/0005-generic-implementation-plan-and-task-breakdown-template.md`
- Response template: `agent-responses/0000-response-template.md`
- Review checklist: `agent-responses/0001-review-checklist.md`
- Evidence add-on template: `agent-responses/0002-response-evidence-addon-template.md`
- Execution manifest template: `execution-manifests/0000-execution-manifest-template.yaml`
