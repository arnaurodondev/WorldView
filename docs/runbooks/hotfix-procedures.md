# Hotfix Procedures

## Scope

Emergency production or demo-critical fixes requiring minimal-risk intervention.

## Procedure

1. Capture symptom and impact.
2. Define minimal write_paths.
3. Implement smallest viable patch.
4. Run targeted regression tests.
5. Validate contract compatibility (if API/event touched).
6. Deploy using approved release path.
7. Backfill full test/documentation updates immediately after stabilization.

## Required Artifacts

- issue summary in `docs/BUG_PATTERNS.md` (if new failure pattern)
- regression test reference
- rollback plan

## Guardrails

- no schema breaking changes in hotfix
- no cross-service boundary violations
- no skipped critical tests without explicit rationale
