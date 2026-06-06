# PRD-0089 Wave 1 — Pre-flight Verification

**Date**: 2026-05-20
**Branch**: `feat/plan-0089-w1` (off `main` @ 79a29e6c)
**Plan**: `docs/plans/0089-pages/W1-global-shell-plan.md`

## Pre-flight check results

| # | Check | Result |
|---|-------|--------|
| 1 | F1 commits present | ✅ 7 step commits + F1.1 close-out: `03751641` (PR-A tokens) → `1c6cc703` (F1.1 close-out) |
| 2 | F2 commits present | ✅ 14 step commits: `1dbf6d74` (schema) → `5e7e0488` (tests); plus `bf344b51` QA fix + `c40d2349` followups |
| 3 | F1 primitive catalogue at `apps/worldview-web/components/primitives/` | ✅ All 19 expected files present: TableRow, MetricCell, Sparkline, SeverityCharBadge, BulkActionToolbar, DenseArticleRow, InlineCitationAnchor, FreshnessDot, DataFreshnessPill, EmptyState, LoadingSkeleton, DemoBadge, AiContentRail, FocusRing, MetricLabel, MetricValue, SectionDivider, DataTimestamp, InstrumentNotFound |
| 4 | `/instruments/{ticker}` route exists | ✅ `apps/worldview-web/app/(app)/instruments/[ticker]/page.tsx` present |
| 5 | ADR-F-XX for entity-id unification | ✅ `docs/architecture/decisions/ADR-F-16-instrument-entity-id-unification.md` exists |

## Baseline commit hashes (locked at branch root)

- F1 final: `1c6cc703` — feat(plan-0089-f1.1): close QA gaps
- F2 final: `5e7e0488` — feat(plan-0089-f2/tests): fixture rewrite + M-017 integration invariant
- F2 QA: `bf344b51` — fix(plan-0089-f2/qa): resolve all 4 QA findings
- F2 followups: `c40d2349` — fix(plan-0089-f2-followups): 3 concrete defects
- main HEAD at branch: `79a29e6c` — fix(post-audit): 6 follow-up fixes

## Notes

- `InstrumentNotFound` exists on disk but is **not** re-exported from
  `components/primitives/index.ts`. W1 components that need it will import
  directly from `@/components/primitives/InstrumentNotFound` to avoid
  modifying F1 primitives during this wave.
- W1 will create `qk.shell.*` namespace and add `qk.instruments.ohlcvBatch`
  to `lib/query/keys.ts`. No collision with existing keys.

## Gate

Pre-flight: **PASS** — proceed with W1 dispatch.
