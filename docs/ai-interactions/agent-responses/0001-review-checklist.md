# Response Review Checklist

Use this checklist to accept/reject any implementation response artifact.

## 1) Scope control

- [ ] All implemented work maps to listed task IDs.
- [ ] No out-of-scope files were changed without explicit justification.
- [ ] Response includes declared `write_paths` and confirms adherence.

## 2) Validation completeness

- [ ] Per-task targeted tests were executed and reported.
- [ ] Per-task changed-path `ruff check` was executed and reported.
- [ ] Per-task changed-package/module `mypy` was executed and reported.
- [ ] No deferred lint/type/test failures remain.

## 3) Quality gates

- [ ] Required tests in prompt passed.
- [ ] Lint/type checks required by prompt passed.
- [ ] Definition of done criteria are explicitly satisfied.

## 4) Documentation quality

- [ ] All required docs were updated (or explicit `N/A` with justification).
- [ ] Doc content matches final implementation (API/events/schema/config/tests).
- [ ] Any non-trivial flow includes required diagrams/examples.
- [ ] No stale/TODO/orphan docs remain for touched scope.

## 5) Evidence quality

- [ ] Changed files list is complete.
- [ ] Validation ledger includes command, scope, and result/exit code.
- [ ] Blockers/risks are explicitly listed (or `none`).
- [ ] Commit message proposal is present.
- [ ] Final-wave response includes PR description (if required by prompt).

## 6) Final verdict

- [ ] PASS — response is acceptable for merge/review handoff.
- [ ] FAIL — response needs rework (list exact gaps below).

### Rework notes

-
