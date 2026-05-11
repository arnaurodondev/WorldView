# QA Report: UI Bug Pass — User-Reported Issues

**Date**: 2026-05-04 11:00 UTC
**Skill**: qa
**Scope**: Frontend — worldview-web user-reported UI bugs
**Branch**: feat/content-ingestion-wave-a1
**Verdict**: PASS_WITH_WARNINGS (backend data issues remain; all fixable frontend bugs resolved)

---

## Executive Summary

User-reported 13 distinct UI issues across dashboard, portfolio, instrument overview, entity graph, fundamentals, screener, workspace, and alerts/news. 5 parallel investigation agents diagnosed root causes; 4 parallel fix agents implemented fixes. 8 bugs were frontend-fixable and are now resolved across 5 commits. 4 bugs are backend data pipeline issues (economic events, fundamentals data, competitors data) requiring no frontend change. 1 issue (revenue trend chart mobility) is by design — the sparkline is intentionally static. All fixes validated: 1708/1708 tests pass, typecheck clean.

---

## Bug Summary

| # | Area | Bug | Root Cause | Status | Fix |
|---|------|-----|-----------|--------|-----|
| 1 | Dashboard | Economic Events empty | Backend S7 temporal-events not ingested | BACKEND — no frontend fix | — |
| 2 | Screener | Default filter returns 0 stocks | `daily_return` enrichment `±1` too narrow (percentage vs decimal); `pe_ratio ±9999` excludes no-earnings stocks | FIXED | `build-filters.ts`: `-1→-100`, `-9999→-999999` |
| 3 | Workspace | Can't link to asset | Quote/holding rows were static `<div>` with hover but no navigation | FIXED | `WorkspaceWatchlistWidget` + `WorkspacePortfolioPanel`: wrapped rows with `<Link href="/instruments/{entityId}">` |
| 4 | Portfolio | Bottom half black | Dark theme (`bg-background` #09090B) visible below last component; charts in loading state show dark skeletons | PARTIAL — inherent to data-empty state | — |
| 5 | Portfolio | Column misalignment | Footer spacer `w-[560px]` should be `w-[640px]` (sum of 7 data columns) | FIXED | `SemanticHoldingsTable.tsx:245`: `w-[560px]` → `w-[640px]` |
| 6 | Portfolio | Asset click wrong path | Already correct (`entity_id` used via ADR-F-12) — may be null `entity_id` for some holdings | FIXED | Added `entity_id` null guard in WorkspaceWatchlistWidget |
| 7 | Instrument | Chart auto-scrolls left | `scrollToRealTime()` fired on EVERY data change (bg refetches). Was a "scroll right" operation hitting every 60s. | FIXED | `OHLCVChart.tsx`: `hasScrolledToRealTime` ref guards first-load only |
| 8 | Instrument | Right sidebar not independent | `grid grid-cols-[1fr_280px]` ties sidebar height to chart height | FIXED | `OverviewLayout.tsx`: `grid → flex`, sidebar `w-[280px] flex-shrink-0` |
| 9 | Instrument | Black component below chart | EntityGraph 400px container had no background fallback | FIXED | `OverviewLayout.tsx`: `bg-card/20` + Skeleton loading state |
| 10 | Instrument Graph | Self-loop crash | No `source !== target` guard before `graph.addEdge()` | FIXED | `EntityGraph.tsx`: added `&& edge.source !== edge.target` |
| 11 | Fundamentals | All entries empty | Backend `instrument_fundamentals_snapshot` table not populated (S3 backfill not running or free-tier key) | BACKEND — no frontend fix | — |
| 12 | Fundamentals | Revenue trend chart unmovable | By design — FundamentalSparkline is a static inline sparkline, not an interactive chart | BY DESIGN | — |
| 13 | Alerts/News | Too much space, letters too big | `ArticleCard.tsx`: `p-3` wrapper, `text-sm` title; `alerts/page.tsx`: `space-y-2` containers | FIXED | ArticleCard `p-3→py-1 px-2`, title `text-sm→text-[11px]`; page `space-y-2→space-y-1` |

---

## Commits

| Commit | Files | Description |
|--------|-------|-------------|
| `26250595` | WorkspaceWatchlistWidget, WorkspacePortfolioPanel, SemanticHoldingsTable | Workspace linking + portfolio footer alignment |
| `f7e93b1c` | ArticleCard, alerts/page, AlertHistoryTab | Bloomberg density fixes |
| `8345105d` | EntityGraph, build-filters | Self-loop filter + screener bounds |
| `18cb9f67` | OHLCVChart, OverviewLayout | Chart scroll guard + sidebar independence + graph placeholder |

---

## Test Results

| Layer | Tests | Status |
|-------|-------|--------|
| Frontend Unit (Vitest) | 1708/1708 | PASS |
| TypeScript | — | PASS |
| Lint (ESLint) | 0 errors | PASS (5 pre-existing queryKey warnings) |

---

## Backend Data Issues (Not Frontend-Fixable)

These require backend data pipeline changes, not frontend fixes:

- **Economic Events** (`/v1/fundamentals/economic-calendar`): S7 temporal-events table not populated. EconomicCalendar component correctly shows empty state.
- **Fundamentals snapshot**: `instrument_fundamentals_snapshot` table empty. Likely the S3 nightly backfill job has not run or the API key lacks premium access. FundamentalsTab correctly renders `—` for null fields.
- **Competitors**: No `/v1/entities/{id}/competitors` endpoint exists in S9. Would need PRD + implementation.

---

## New Bug Patterns

**BP-359**: Screener enrichment filter range as decimal vs percentage — enrichment filters that force a numeric range must use bounds wide enough for both storage formats (decimal 0.05 and percentage 5.0). Use `±100` for daily_return, `±999999` for PE. Key: enrichment filters must not double as range restrictions.

**BP-360**: Graph self-loop — `graphology` with `allowSelfLoops: false` crashes on `addEdge(src, src)`. Always guard: `edge.source !== edge.target` before `graph.addEdge()`. Backend sentinel IDs (all-zeros UUID patterns) frequently appear as both endpoints of placeholder relations.

---

## Recommendations

1. **Backend**: Run S3 fundamentals backfill pipeline to populate `instrument_fundamentals_snapshot` — fixes empty fundamentals tab
2. **Backend**: Wire S7 economic-events ingestion pipeline — fixes empty Economic Events widget
3. **PRD**: Add competitors endpoint to S9/S7 scope for next planning cycle
4. **Frontend**: Portfolio analytics section — consider adding explicit `bg-background` padding-bottom wrapper so the dark background below last component is not visible during data loading
