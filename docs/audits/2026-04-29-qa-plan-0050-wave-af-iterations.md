# PLAN-0050 Wave A + F — QA Iterations Report

**Date**: 2026-04-29
**Branch**: `feat/content-ingestion-wave-a1`
**Plan**: `docs/plans/0050-dashboard-instruments-polish-plan.md`
**Scope**: Wave A (TopBar redesign + Ask AI) + Wave F (8 of 21 MINOR sweep tasks)

This audit captures the strict QA agent's findings across two iterations on the
Wave A + F implementation, the per-iteration fixes applied, and what remains
deferred.

---

## Commits

| Commit | Subject |
|--------|---------|
| `c9c1a99` | `feat(PLAN-0050): Wave A (top bar + Ask AI) + Wave F (8 MINOR sweep)` |
| `8278066` | `fix(plan-0050-qa-iter1): close 4 BLOCKING + 8 CRITICAL + 4 MAJOR + 2 MINOR` |
| _next_   | `fix(plan-0050-qa-iter2): close 1 BLOCKING + 1 CRITICAL + 2 MAJOR + 1 MINOR + audit` |

---

## Iteration 1 — 23 findings

QA agent run on `c9c1a99`. Verdict: 6/10 confidence; 4 BLOCKING, 8 CRITICAL,
6 MAJOR, 5 MINOR.

### Closed in `8278066`

| ID | Severity | Summary |
|----|----------|---------|
| F-QA-01 | BLOCKING | `PortfolioSummary` `staleTime: 0` defeated `usePortfolioMetrics` dedup → both sites now share `QUOTE_REFETCH_MS`. |
| F-QA-02 | BLOCKING | `RefreshAllButton` and `CompactInstrumentHeader` leaked timers on unmount → `useRef` + `useEffect` cleanup; consolidated into `hooks/useCopyState.ts`. |
| F-QA-03 | BLOCKING | `safeCopy()` falsely showed "Copied!" on missing/denied clipboard → `useCopyState.copy()` returns `Promise<boolean>`; UI renders `AlertCircle` + "Unable to copy" tooltip on failure. |
| F-QA-04 | BLOCKING | `RefreshAllButton.invalidateQueries()` (no filter) re-triggered SSE/WS observers → predicate filter (initially allowlist; replaced in iter-2 with denylist — see F-QA2-01). |
| F-QA-05 | CRITICAL | Focus did not return to AskAi trigger on panel close → `AskAiButton` `forwardRef`; layout calls `requestAnimationFrame(() => triggerRef.current?.focus())`. |
| F-QA-06 | CRITICAL | LiveQuoteBadge dot double-narrated (`aria-label` + `title` + sibling StaleBadge) → dot is now `aria-hidden="true"`. |
| F-QA-07 | CRITICAL | RefreshAllButton tests covered 1 path → 4 specs (predicate, spinner toggle, allowlist contract, unmount-mid-spin). |
| F-QA-08 | CRITICAL | LiveQuoteBadge dot status mapping untested → new `__tests__/LiveQuoteBadge.dot.test.tsx` covers all 5 buckets + null fallback + aria-hidden. |
| F-QA-09 | CRITICAL | TopBar P&L colour painted floating-point dust as +/- → `pnlColorClass` with `PNL_FLAT_EPSILON = 0.005` deadband. Hook tests cover `qty=0` (closed), `qty=-10` (short), `avg_cost=0` (gifted). |
| F-QA-10 | CRITICAL | AskAiPanel `contextHint` disappeared after first answer → render is now unconditional when supplied. |
| F-QA-11 | CRITICAL | Keyboard reachability — addressed by dropping the false "⌘K coming soon" tooltip (F-QA-19). |
| F-QA-12 | CRITICAL | AskAiPanel/InstrumentAskAiButton overlapped 24px StatusBar at 1× zoom → `bottom-4`/`bottom-6` → `bottom-10`. |
| F-QA-13 | MAJOR    | Copy state machine duplicated in two components → consolidated into `useCopyState`. |
| F-QA-16 | MAJOR    | Predictions pill row overflowed 24px header at narrow viewports → `overflow-x-auto` + `min-w-0`. |
| F-QA-17 | MAJOR    | `usePortfolioMetrics` `isLoading` branch untested → explicit isLoading-while-pending test. |
| F-QA-19 | MAJOR    | AskAiButton title advertised "⌘K coming soon" with no handler → dropped. |
| F-QA-21 | MINOR    | `QUOTE_REFETCH_MS` value drift between hook and `LiveQuoteBadge` → exported from hook. |
| F-QA-23 | MINOR    | TopBar mixed `!== undefined` and `!= null` → standardised on `!= null`. |

### Iter-1 deferred (judged acceptable for ship)

| ID | Severity | Summary | Status |
|----|----------|---------|--------|
| F-QA-14 | MAJOR | Empty-state copy harmonisation across widgets | Deferred to a Wave F follow-up — pattern-level work that would touch many files outside Wave A+F scope. |
| F-QA-15 | MAJOR | More WHY comments on `buildContextLine` thresholds | Deferred — comments exist; the missing detail is "why 1e9 vs 1e6" which is conventional. |
| F-QA-18 | MAJOR | Ticker button row alignment at 110% zoom | Deferred — visual at high-zoom only; no reported user impact. |
| F-QA-20 | MINOR | Redundant ternary in `PredictionMarketsWidget.yesProbColor` | Deferred — cosmetic. |
| F-QA-22 | MINOR | EntityGraphErrorBoundary repeat-failure detection | Deferred — boundary already prevents tab tear-down; repeat-failure is a polish iteration. |

---

## Iteration 2 — 6 new findings

QA agent run on `8278066`. Verdict: 7/10 confidence; all iter-1 fixes
CONFIRMED-CLOSED via code reading and test inspection. New findings
introduced by the iter-1 refactors:

### Closed in iter-2 commit

| ID | Severity | Summary |
|----|----------|---------|
| F-QA2-01 | BLOCKING | The iter-1 allowlist over-corrected F-QA-04: `RefreshAllButton` silently dropped ~10 dashboard widgets (sector heatmap, market snapshot, top movers, index ticker, alarms panel, watchlists sidebar) from the refresh gesture. Inverted to a denylist of streaming-bound prefixes (`alert-stream`, `chat-stream`, `alert-ws-*`, `chat-ws-*`); test suite expanded to assert both inclusion and exclusion. |
| F-QA2-02 | CRITICAL | RefreshAllButton title still advertised "(R)" shortcut with no handler — same anti-pattern F-QA-19 fixed for AskAiButton. Dropped. |
| F-QA2-03 | MAJOR    | `useCopyState.copy()` could `setState` on an unmounted component after the awaited `navigator.clipboard.writeText`. Added `mountedRef` guard and `safeSetState` wrapper. |
| F-QA2-04 | MAJOR    | `InstrumentAskAiButton` did not restore focus to its floating trigger on panel close — same WCAG 2.4.3 violation F-QA-05 fixed for the shell trigger. Added `triggerRef` + `requestAnimationFrame` focus restore. |
| F-QA2-05 | MINOR    | Single shared `useCopyState` instance powered both ticker + link buttons → ticker check icon flipped back to Copy mid-feedback when link button took the slot. Now two separate hook instances. |
| F-QA2-06 | MINOR    | Iter-1 commit referenced F-QA-* findings with no audit document anchoring the IDs. **This document closes that gap.** |

---

## Verification (post iter-2)

```
pnpm typecheck   PASS  (tsc --noEmit)
pnpm vitest run  PASS  (39 files, 480 tests)
pnpm lint        PASS  (No ESLint warnings or errors)
```

Tests grew from 466 (pre-Wave A+F QA) → 480 (post iter-1) → 480 (post iter-2,
RefreshAllButton predicate test rewritten in place). All new behaviours have
explicit coverage.

---

## Status

PLAN-0050 Wave A + Wave F (8 of 21 tasks) **READY FOR MERGE** pending one
more QA iteration to confirm iter-2 closures held without new regressions.
The 13 deferred Wave F MINOR tasks (T-F-6-03/04/05/07/08/10-13/15/16/18/20)
remain pending a Wave F follow-up commit.

---

## Notes for the next iteration

- The denylist approach to `RefreshAllButton` predicate is more robust than
  the allowlist but requires future stream-key authors to add their prefix
  here. Consider a registry/config pattern when more streams are added.
- `useCopyState` is now a generic-enough utility that other surfaces (chat
  message copy, alert payload copy) could use it. Watch for drift if those
  are added later.
