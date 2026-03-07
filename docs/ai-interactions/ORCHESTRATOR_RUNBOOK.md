# Orchestrator Runbook (1 Orchestrator + N Workers)

## Recommended topology

- 1 orchestrator agent controls planning, assignment, and gates.
- N worker agents execute one atomic task each.
- Start with `N=2..4` and scale only when conflict/flake rate is low.

## Lifecycle

1. Select prompt + response pair.
2. Normalize tasks to atomic units from the response backlog.
3. Create execution wave prompt(s).
4. Mark executable tasks `ready`.
5. Assign each ready task to a worker and branch.
6. Workers execute, test, and submit evidence.
7. Orchestrator validates checklist + gates.
8. Merge in dependency order.

## Task state machine

`planned -> ready -> in-progress -> review -> done`

`planned/ready/in-progress -> blocked`

`blocked -> ready` (when blocker resolved)

`planned/ready/blocked -> cancelled`

## Assignment rules

- One worker, one task, one branch.
- Worker edits only paths required by the assigned task scope.
- No nested execution delegation.
- Read-only subagents are allowed for analysis.

## Parallel execution rules

Run tasks in parallel only when:

- no dependency edge between tasks
- `write_paths` do not overlap
- both tasks are in `ready`

## Evidence required before review

- changed file list
- required test commands + outcomes
- docs updated (or explicit N/A)
- response artifact section update

## Quality gates before done

- required tests pass
- docs updated when behavior/API/schema/config changes
- response checklist passed
- no unresolved blocker

## Retry and escalation

- Max worker retries per task: 2
- On third failure: set `blocked`, attach error context, escalate to orchestrator

## Suggested branch naming

- `agent/<task-id>-<short-slug>`

## Suggested PR title format

- `[<task-id>] <short title>`

## Merge policy

- Merge only after orchestrator confirms checklist and task Definition of Done.
- Merge dependent tasks in topological order.
