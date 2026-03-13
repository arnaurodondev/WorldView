# Prompt 0000 — Generate execution wave prompts from planning + response

Act as an execution-orchestration planner (./claude/agents/agent-orchestrator.md).

## Goal

Given one planning prompt and one planning response, generate multiple execution prompt files (wave-based) that optimize output quality by reducing context size while minimizing context switching.

## Inputs (fill before execution)

- Scope name: `<scope>`
- Prompt ID: `<000X>`
- Planning prompt file: `docs/ai-interactions/agent-planning/<file>.md`
- Planning response file: `docs/ai-interactions/agent-responses/<file>.md`
- Execution worker agent profile(s): `<agent-file(s)>` (e.g., `./claude/agents/data-platform-engineer.md`)
- Coverage mode: `full` (mandatory)
- Tasks per wave bounds: `min_tasks_per_wave=<a>`, `max_tasks_per_wave=<b>` (recommended: 1–20)
- Max estimated effort per wave target: `<hours>` (recommended: 6–14)

## Hard constraints

1. Use only task IDs present in the source response.
2. Keep each wave coherent by bounded context or layer (domain, application, infra, api, tests/docs).
3. Avoid mixing unrelated subsystems in one wave unless there is a strict dependency.
4. Every wave must be independently executable with clear done criteria.
5. Never include tasks with unmet prerequisites in a wave.
6. Include required documentation updates for each wave.
7. Keep total prompt size small enough for focused execution (no full backlog dump).
8. **Full coverage is mandatory**: every task ID found in the response backlog must appear in exactly one generated wave prompt.
9. Do not stop at wave 01; generate as many waves as needed until all tasks are assigned.
10. If a task is blocked by unresolved external dependency, place it in a dedicated blocked/deferred wave instead of omitting it.
11. Use the same planning `Prompt ID` as the execution prompt filename prefix for all waves in that run.
12. Minimize the number of waves while respecting dependency order, coherence, and tasks-per-wave bounds.
13. Every generated wave prompt must explicitly require documentation updates for any behavior/API/event/config/schema/test-surface change and list exact docs files updated. Documentation must conform to the **Documentation quality standard** defined below.
14. Every generated wave prompt must require a post-wave commit message proposal: a concise commit title plus 1-2 sentences describing what was implemented and validated.
15. Every generated wave prompt must require a highly detailed PR description only for the final wave of that scope.
16. Every generated wave prompt must enforce a **task-scoped fail-fast gate**: targeted tests + changed-path `ruff check` + changed-package `mypy` before the next task starts.
17. Every generated wave prompt must include an explicit **No Deferred Fixes** rule: no carrying ruff/mypy/test failures into later tasks.
18. Every generated wave prompt must include a **Scope & Token Budget** section with bounded `write_paths` and a maximum exploration pass before first edit.

## Documentation quality standard

All documentation written or updated in any wave must meet the following criteria.
Agents must verify each criterion before marking documentation as done.

### Quality criteria

1. **Accuracy** — every documented API, parameter, config var, event type, or
   data field must match the final implementation exactly. No stubs, no
   "TBD", no copy-paste from earlier drafts that diverged.

2. **Diagrams for non-trivial flows** — any control flow, data flow, or
   interaction involving 3 or more components or 4 or more steps must include
   a Mermaid diagram (sequence, flowchart, or ER as appropriate). Examples:
   - Outbox publish lifecycle → sequence diagram
   - Consumer retry/dead-letter flow → flowchart
   - Service data model relationships → ER diagram
   - Cross-service event chains → sequence diagram

3. **Realistic code examples** — every new public class or function must have
   at least one working usage example. Examples must be:
   - Complete enough to copy-paste and run
   - Not stubs (`pass`, `...`, `# TODO`)
   - Showing realistic argument values, not `"foo"` / `None` everywhere

4. **All abstract methods documented** — for any abstract base class, provide
   a table mapping each abstract method to: when it is called, what it must do,
   and what it must return.

5. **Common pitfalls section** — every lib doc and every service doc must
   include a `## Common Pitfalls` section listing at least 3 concrete mistakes
   developers make and their consequences. Not generic advice — specific to
   the component being documented.

6. **Lib docs updated when lib surface changes** — if a wave touches any file
   inside `libs/`, the corresponding `docs/libs/<lib>.md` must be updated in
   the same wave. If no surface change occurred, state explicitly `N/A: no
   public API surface changed`.

7. **Service docs reflect final state** — `docs/services/<service>.md` must
   match the final implementation: endpoint paths/methods, request/response
   fields, HTTP status codes, outbox events, consumed topics, DB schema, and
   env vars. The service doc is the contract reference; it must not lag behind
   the code.

8. **No orphan documentation** — do not create documentation for code that is
   not yet implemented. Do not leave documentation for code that was deleted
   or renamed without updating it.

### Documentation evidence requirement

In the `## Required handoff evidence` section of each wave response, the agent
must provide a **Documentation quality checklist** with one row per criterion:

| Criterion | Status | Notes |
|-----------|--------|-------|
| Accuracy verified | ✓ / N/A | |
| Diagrams added for non-trivial flows | ✓ / N/A | List diagram titles |
| Realistic code examples | ✓ / N/A | |
| Abstract methods documented | ✓ / N/A | |
| Common pitfalls section present | ✓ / N/A | |
| Lib docs updated | ✓ / N/A | List files |
| Service docs reflect final state | ✓ / N/A | List files |
| No orphan documentation | ✓ | |

## Chunking heuristic (mandatory)

When creating waves, optimize this objective in order:

1. Dependency correctness (no invalid ordering)
2. Context coherence (same folder/layer/domain)
3. Meaningful work size per wave (not too small, not too large)
4. Parallelism opportunities inside wave
5. Low cross-wave churn on the same files

If conflicts exist, prioritize smaller coherent waves over maximal parallelism.

## Task extraction and normalization (mandatory)

Before creating waves:

1. Extract the complete canonical task list from the response file.
2. Normalize task IDs (trim spaces, preserve original case/prefix).
3. Build a dependency map for all extracted tasks.
4. If duplicate task IDs exist in the source response, report them explicitly and stop to request clarification.

Do not generate partial waves from a subset.

## Wave-count optimization (mandatory)

Let:

- `T` = total discovered tasks
- `MAX` = `max_tasks_per_wave`

Compute theoretical minimum waves:

- `W_min = ceil(T / MAX)`

Generation rules:

1. Aim for `actual_waves` as close to `W_min` as possible.
2. Prefer filling waves near the upper bound (`MAX`) unless this violates dependency/coherence constraints.
3. If `actual_waves > W_min + 1`, provide an explicit justification section listing the exact dependency/coherence reason per extra wave.

## Output files to create

Create one file per wave in:

- `docs/ai-interactions/agent-prompts/`

Naming convention:

- `<prompt-id>-exec-<scope>-wave-<nn>.md`

Example (for prompt ID `0001`):

- `0001-exec-shared-libs-migration-wave-01.md`
- `0001-exec-shared-libs-migration-wave-02.md`
- `0001-exec-shared-libs-migration-wave-03.md`

## Required structure for each generated wave file

Each generated file must contain exactly these sections:

1. `# Execution Prompt <id> — <scope> wave <nn>`
2. `## Context (read first)`
   - planning prompt path
   - response path
3. `## Assigned agent profile(s)`
   - exact agent file(s) to use
4. `## Mandatory pre-read`
   - `AGENTS.md`, `CLAUDE.md`, relevant service/lib docs, and source planning/response files
5. `## Objective`
6. `## Task scope for this wave`
   - `### Parallel group(s)`
   - `### Sequential group(s)`
7. `## Why this chunk`
   - short explanation of coherence and dependency fit
8. `## Implementation instructions`
   - concrete implementation steps for each task ID in this wave
9. `## Constraints`
   - explicit “do not implement outside listed task IDs”
10. `## Scope & token budget`
   - task `write_paths`
   - exploration bound (e.g., max files to inspect before editing)
   - stop condition if scope is still ambiguous
11. `## Required tests`
   - exact commands if available in source; otherwise explicit placeholders
   - pass criteria
12. `## Incremental quality gates (mandatory)`
   - per-task command sequence (targeted pytest, changed-path ruff, changed-package mypy)
   - mandatory immediate fix rule before continuing
13. `## Documentation requirements`
   - files likely impacted + update conditions
   - mandatory instruction: if implementation changes behavior/contracts/config/schema/API/tests, update docs in the same wave
   - **mandatory**: explicitly reference the Documentation quality standard from this template — accuracy, diagrams, realistic examples, pitfalls section, lib and service doc updates
   - list exact documentation files updated (or `N/A` with justification)
14. `## Required handoff evidence`
   - changed files, tests run/results, docs changed (exact files + summary), unresolved blockers
   - validation ledger (command, scope, exit code, result)
   - commit message proposal (title + 1-2 sentence body)
   - final wave only: highly detailed PR description covering scope summary, task IDs, changed files grouped by area, tests/lint/typecheck evidence, docs/ADR updates, migration/compatibility notes, risks, and rollback/next steps
15. `## Definition of done`
   - includes documentation updates completed and quality-standard checklist verified (or explicit N/A justification per criterion)
   - includes incremental quality gates passed for each task (no deferred failures)
   - includes commit message proposal for every wave and final-wave PR description when applicable
   - **documentation quality gate**: all 8 quality criteria from the Documentation quality standard must be confirmed ✓ or explicitly N/A before the wave is considered done

## Quality checks before finalizing

For each generated wave prompt, validate:

- all tasks have prerequisites satisfied within prior waves or completed dependencies
- no duplicated task IDs across waves
- no orphan tasks (every in-scope task assigned)
- wave size within configured bounds
- docs/test obligations explicitly listed
- each wave includes mandatory documentation update rule and evidence requirement
- **each wave includes a reference to the Documentation quality standard and requires the quality checklist in handoff evidence**
- each wave includes incremental fail-fast validation commands and no-deferred-fixes rule
- each wave includes commit-message requirement and only the final wave includes a highly detailed PR-description requirement

Global validation (mandatory):

- `discovered_task_ids == assigned_task_ids` (exact set equality)
- each task appears in one and only one wave
- blocked/deferred tasks are still assigned to a wave
- unassigned task list is empty
- all generated files use the same `<prompt-id>` prefix

## Required summary artifact

Also produce a short summary section at the end of your response:

- total number of tasks discovered
- total number of waves generated
- theoretical minimum waves (`W_min`) and actual waves
- wave-by-wave task IDs
- dependency rationale for wave ordering
- coverage check: `assigned/discovered` counts and whether exact-set match passed
- explicit `unassigned tasks` list (must be `none`)

## Required coverage ledger

Include a final table named `Coverage Ledger` with one row per discovered task:

- `task_id`
- `assigned_wave`
- `status` (`scheduled` or `deferred/blocked`)
- `dependency_note`

This ledger is mandatory and is the acceptance artifact proving full task coverage.
