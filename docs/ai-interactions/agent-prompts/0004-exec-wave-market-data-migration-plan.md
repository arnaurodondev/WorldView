Act as an execution-orchestration planner (./claude/agents/agent-orchestrator.md).

## Goal

Given one planning prompt and one planning response, generate multiple execution prompt files (wave-based) that optimize output quality by reducing context size while minimizing context switching.

## Inputs

- Scope name: `market-data-migration`
- Prompt ID: `0004`
- Planning prompt file: `docs/ai-interactions/agent-planning/0004-market-data-migration-detailed-plan-and-atomic-tasks.md`
- Planning response file: `docs/ai-interactions/agent-responses/0004-response-20260306-market-data-migration-plan.md`
- Execution worker agent profile(s): `./claude/agents/data-platform-engineer.md`, `./claude/agents/architecture-decision-lead.md`
- Coverage mode: `full` (mandatory)
- Tasks per wave bounds: `min_tasks_per_wave=1`, `max_tasks_per_wave=20`

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
11. Every generated wave filename must start with `0004-` (same ID as planning/response pair).
12. Minimize the number of waves while preserving dependency correctness and context coherence.
13. Every generated wave prompt must explicitly require documentation updates for any behavior/API/event/config/schema/test-surface changes and must require listing exact docs files changed. Documentation must conform to the **Documentation quality standard** below.
14. Every generated wave prompt must require a post-wave commit message proposal: commit title + 1-2 sentences describing what was implemented and validated.
15. Every generated wave prompt must require a highly detailed PR description only for the final wave of the scope.

## Documentation quality standard

All documentation written or updated in any wave must meet the following criteria.
The agent must verify each criterion and report a quality checklist in handoff evidence.

1. **Accuracy** — every documented endpoint, field, event type, config var, and
   data model must match the final implementation exactly.
2. **Diagrams for non-trivial flows** — any flow with ≥3 components or ≥4 steps
   needs a Mermaid diagram (sequence, flowchart, or ER as appropriate).
3. **Realistic code examples** — every new public class/function needs a working
   usage example (no stubs, no `pass`, no `# TODO`).
4. **Abstract methods documented** — for any ABC, provide a table: method → when
   called → what to do → what to return.
5. **Common pitfalls section** — `docs/services/market-data.md` and any updated
   lib docs must include a `## Common Pitfalls` section with ≥3 concrete entries.
6. **Lib docs updated** — if the wave touches any `libs/` file, update the
   corresponding `docs/libs/<lib>.md` in the same wave.
7. **Service doc reflects final state** — `docs/services/market-data.md` must match
   the final implementation: endpoints, events, consumed topics, DB schema, env vars.
8. **No orphan documentation** — do not document unimplemented code; remove docs
   for deleted or renamed symbols.

In handoff evidence, provide a **Documentation quality checklist** table with one
row per criterion (✓ or N/A + justification).

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

Let `T` be total discovered tasks and `MAX=20`.

- Compute `W_min = ceil(T / 20)`.
- Target wave count should be as close as possible to `W_min`.
- Fill waves near 20 tasks when dependency/coherence allows.
- If generated waves are more than `W_min + 1`, add explicit justification per extra wave.

## Output files to create

Create one file per wave in:

- `docs/ai-interactions/agent-prompts/`

Naming convention:

- `0004-exec-market-data-migration-wave-<nn>.md`

## Required structure for each generated wave file

Each generated file must contain exactly these sections:

1. `# Execution Prompt <id> — <scope> wave <nn>`
2. `## Context (read first)`
   - planning prompt path
   - response path
3. `## Assigned agent profile(s)`
   - include exact agent files listed above
4. `## Mandatory pre-read`
   - `AGENTS.md`, `CLAUDE.md`, `docs/services/market-data.md`, relevant `docs/libs/*.md`, planning prompt, response file
5. `## Objective`
6. `## Task scope for this wave`
   - `### Parallel group(s)`
   - `### Sequential group(s)`
7. `## Why this chunk`
   - short explanation of coherence and dependency fit
8. `## Implementation instructions`
   - concrete per-task implementation steps for the listed task IDs
9. `## Constraints`
   - explicit “do not implement outside listed task IDs”
10. `## Required tests`
   - exact commands if available in source; otherwise explicit placeholders
   - pass criteria
11. `## Documentation requirements`
   - files likely impacted + update conditions
   - mandatory instruction: update docs in same wave for any implementation change affecting behavior/contracts/config/schema/API/tests
   - **mandatory**: verify all 8 criteria from the Documentation quality standard above; include the quality checklist table in handoff evidence
12. `## Required handoff evidence`
   - changed files, tests run/results, docs changed (exact files + summary), unresolved blockers
   - commit message proposal (title + 1-2 sentence body)
   - final wave only: highly detailed PR description covering scope summary, task IDs, grouped changed files, test/lint/type evidence, docs/ADR updates, compatibility notes, risks, rollback, and follow-ups
13. `## Definition of done`
   - includes documentation updates completed and quality-standard checklist verified (or explicit N/A per criterion)
   - includes commit message proposal for every wave and final-wave PR description when applicable
   - **documentation quality gate**: all 8 quality criteria must be confirmed ✓ or explicitly N/A before the wave is done

## Quality checks before finalizing

For each generated wave prompt, validate:

- all tasks have prerequisites satisfied within prior waves or completed dependencies
- no duplicated task IDs across waves
- no orphan tasks (every in-scope task assigned)
- wave size within configured bounds
- docs/test obligations explicitly listed
- each wave includes mandatory documentation update rule and evidence requirement
- **each wave includes reference to the Documentation quality standard and requires the quality checklist in handoff evidence**
- each wave includes commit-message requirement and final-wave-only PR-description requirement

Global validation (mandatory):

- `discovered_task_ids == assigned_task_ids` (exact set equality)
- each task appears in one and only one wave
- blocked/deferred tasks are still assigned to a wave
- unassigned task list is empty
- all generated files match `0004-exec-market-data-migration-wave-<nn>.md`

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
