# Execution State Model

## States

- `planned`: task exists but not yet executable
- `ready`: task executable and assigned/assignable
- `in-progress`: worker actively implementing
- `review`: implementation complete, awaiting orchestrator validation
- `blocked`: task cannot proceed due to unresolved blocker
- `done`: accepted and merged (or accepted output delivered)
- `cancelled`: intentionally removed from run

## Allowed transitions

- `planned -> ready`
- `ready -> in-progress`
- `in-progress -> review`
- `review -> done`
- `planned -> blocked`
- `ready -> blocked`
- `in-progress -> blocked`
- `blocked -> ready`
- `planned -> cancelled`
- `ready -> cancelled`
- `blocked -> cancelled`

## Transition ownership

- Orchestrator: all transitions
- Worker: `ready -> in-progress`, `in-progress -> review`, `in-progress -> blocked`

## Blocked reason categories

- `missing-dependency`
- `failing-tests`
- `scope-conflict`
- `open-question`
- `tooling-issue`
- `external-constraint`

## Completion requirements

A task can move from `review` to `done` only if:

1. all required tests passed
2. docs updated if required
3. evidence attached
4. review checklist passed
