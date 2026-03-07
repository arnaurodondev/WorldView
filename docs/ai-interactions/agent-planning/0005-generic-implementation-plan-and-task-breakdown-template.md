# Prompt 0005 — Generic implementation plan + independent task breakdown (template)

Act as the relevant specialist agent(s) for the target scope.

## Goal

Produce a highly detailed implementation plan (NO code unless explicitly requested), then decompose it into independent, executable tasks with testing and documentation requirements.

## Required pre-read

- `worldview/AGENTS.md`
- `worldview/CLAUDE.md`
- `worldview/RULES.md`
- Relevant docs in `worldview/docs/services/**`, `worldview/docs/libs/**`, `worldview/docs/architecture/**`

## Input placeholders (fill before execution)

- Domain/feature:
- Legacy paths to inspect:
- Target paths to inspect:
- Constraints:
- Out of scope:

## Mandatory requirements

- Include gap analysis between current and target state.
- Produce atomic tasks that are independently executable.
- Include test tasks (unit + container/service + platform QA impact).
- Include explicit documentation update tasks for behavior/API/event/config/schema changes.
- Include acceptance criteria, risks, dependencies, and effort per task.
- Include execution-ready metadata per task: status, depends_on, can_run_with, scope paths, required commands, pass criteria.

## Output format (strict)

1. Executive summary
2. Current state vs target state matrix
3. Dependency graph / critical path
4. Atomic task backlog (ticket style), each with:
   - ID, title, objective
   - Paths to inspect / expected paths to modify
   - Prerequisites/dependencies
   - Implementation steps
   - Tests required and expected evidence
   - Documentation updates required
   - Definition of Done
   - Risks + mitigation
   - Effort estimate
5. Milestones and release gates
6. Open questions and assumptions
7. Draft first execution-wave prompt excerpt for first 5 tasks

## Response artifact required

After execution, create:

- `worldview/docs/ai-interactions/agent-responses/<prompt-id>-response-<YYYYMMDD>-<short-scope>.md`

Include: what was implemented, how, why, tests run/results, docs updated.

Also create implementation prompt files in:

- `worldview/docs/ai-interactions/agent-prompts/`

Each implementation prompt must include:

- source references to the planning prompt and response
- exact task IDs for the current execution wave
- explicit parallelizable group and sequential group
- required test commands and documentation update requirements
- completion evidence requirements for handoff
