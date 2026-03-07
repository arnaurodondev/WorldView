# Agent Response Review Checklist

Use this checklist before accepting any agent response artifact.

## Traceability

- [ ] Response filename follows: `<prompt-id>-response-<YYYYMMDD>-<short-scope>.md`
- [ ] Response references a valid prompt file under `agent-prompts/`
- [ ] Scope in response matches scope requested by prompt
- [ ] Response references a valid execution manifest under `execution-manifests/`
- [ ] Registry entry exists in `INTERACTIONS_REGISTRY.md`

## Implementation Quality

- [ ] Response states exactly what was implemented
- [ ] Response explains how implementation was performed
- [ ] Response explains why key decisions were made
- [ ] Response includes paths changed/inspected

## Testing Evidence

- [ ] Unit tests are listed with execution outcome
- [ ] Service/container tests are listed with execution outcome (or justified if N/A)
- [ ] Platform QA impact is described
- [ ] Failures (if any) include follow-up actions
- [ ] Required manifest-level test gates are satisfied

## Documentation Compliance

- [ ] Agent confirms docs were reviewed before execution
- [ ] Required docs updates are completed when behavior/API/events/config/schema changed
- [ ] Updated docs files are explicitly listed

## Safety and Architecture

- [ ] No cross-service DB access introduced
- [ ] Outbox/idempotency invariants preserved (if applicable)
- [ ] Contract/schema versioning rules respected (if applicable)

## Closure

- [ ] Residual risks are documented
- [ ] Open items are converted into clear next tasks
- [ ] Response is understandable independently (no hidden context required)
- [ ] Orchestrator accepted final state as `done`
