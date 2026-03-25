# Implementation Validation Checklist

Use this checklist before marking a task complete.

## Code Quality

- [ ] follows `STANDARDS.md` and `RULES.md`
- [ ] no hardcoded secrets or environment-specific values
- [ ] structured logging used where needed
- [ ] errors are categorized and handled
- [ ] type hints are complete for new Python code

## Testing

- [ ] unit tests added/updated for behavior changes
- [ ] contract tests added/updated for API/event changes
- [ ] integration tests added/updated for cross-service effects
- [ ] task-scoped tests pass locally
- [ ] no unrelated test regressions introduced

## Contract and Spec Compliance

- [ ] Avro schemas remain compatible (additive evolution)
- [ ] OpenAPI behavior matches endpoint contract expectations
- [ ] envelope fields present for emitted events

## Architecture Compliance

- [ ] no cross-service DB access
- [ ] outbox pattern preserved for dual-write paths
- [ ] idempotency considered for consumers
- [ ] architecture/import-guard tests still pass

## Documentation

- [ ] relevant service docs updated
- [ ] testing docs updated if execution behavior changed
- [ ] debugging log updated for new issues and fixes
- [ ] planning/task archives updated for completed work

## Final Gate

- [ ] `scripts/test-quick.sh` passed
- [ ] `scripts/test-full.sh` passed (or justified partial run)
- [ ] lint/type checks green for changed scope
