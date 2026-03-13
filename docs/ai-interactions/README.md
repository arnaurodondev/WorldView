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

## Efficiency + Quality Gate Policy (Mandatory)

All implementation waves must enforce these defaults:

1. Validate each task incrementally (targeted tests, changed-path lint, changed-package type-check) before moving on.
2. Do not batch unresolved ruff/mypy failures into end-of-wave cleanup.
3. Keep execution prompts task-scoped; avoid full backlog/context dumps in worker prompts.
4. Include a bounded `write_paths` scope in each worker task.
5. Require a command/result ledger in response artifacts for every mandatory gate.
6. Run full-suite checks only at wave/final handoff unless explicitly required earlier.
7. Require `docs/ai-interactions/BUG_PATTERNS.md` scan in every execution prompt pre-read.
8. In every wave prompt, include a regression-guardrails subsection referencing relevant `BP-xxx` IDs for the task scope.

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
- scan `docs/ai-interactions/BUG_PATTERNS.md` and cite applicable pattern IDs in implementation handoff evidence
- update documentation when behavior/contracts/config/schema/API changes
- include doc updates in the response report

## Useful Templates

- Generic planning template: `agent-planning/0005-generic-implementation-plan-and-task-breakdown-template.md`
- Execution prompt index: `agent-prompts/0000-execution-prompt-index-and-conventions.md`
- Response template: `agent-responses/0000-response-template.md`
- Review checklist: `agent-responses/0001-review-checklist.md`
- Evidence add-on template: `agent-responses/0002-response-evidence-addon-template.md`
