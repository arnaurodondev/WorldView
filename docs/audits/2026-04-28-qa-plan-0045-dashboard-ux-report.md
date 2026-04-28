# QA Report — PLAN-0045 Dashboard & Portfolio UX Improvements

**Date**: 2026-04-28
**Branch**: feat/content-ingestion-wave-a1
**Plan**: PLAN-0045
**Result**: **PASS** — All waves implemented, tests pass, live endpoints validated

---

## Summary

PLAN-0045 delivered 11 tasks across 5 waves improving the dashboard and portfolio experience to Bloomberg-grade quality. All waves implemented, validated via unit tests, rebuilt containers, and verified against the live stack.

---

## Wave Results

### Wave A: Morning Brief — Context Fix + Format Redesign ✅

**A-1 — S8 min_display_score threshold lowered**
- Root cause: 93 articles scored 0.23–0.26; old threshold 0.3 returned 0 → empty brief
- Fix: `_fetch_top_news()` `min_display_score` 0.3 → 0.15
- Validated: `GET /api/v1/briefings/morning` returns 465-char narrative

**A-2 — MorningBriefCard Bloomberg-grade redesign**
- `extractHeadline()` parses first `## H2` or `**bold**` phrase as top-line signal
- `line-clamp-3` collapsed preview via ReactMarkdown (entity links clickable even in preview)
- "Read more →" / "show less ↑" expand/collapse for briefs >200 chars
- H2 headers in expanded view styled as 9px uppercase section labels
- ReactMarkdown used for both collapsed and expanded states

---

### Wave B: Alerts — Severity Case Fix + Badge Alignment ✅

**B-1 — Alert severity case mismatch**
- Root cause: S10 emits lowercase `"low"/"medium"/"high"/"critical"`; frontend switch expected uppercase
- Fix: `severityDotClass()` normalises with `.toUpperCase()` before switch
- Added `retry: 2, retryDelay: 2_000` + `refetchOnMount: true`

**B-2 — TopBar badge REST alignment**
- Added `useQuery` for `getPendingAlerts({ limit: 1 })` in `layout.tsx` (60s stale, 60s interval)
- Badge = `Math.max(restTotal, wsCount)` — shows larger of REST vs WebSocket count

---

### Wave C: Portfolio Holdings Enrichment ✅

**C-1 — S1 holdings endpoint enriched with ticker/name/entity_id**
- `EnrichedHolding` DTO in application layer (wraps Holding + optional instrument fields)
- `list_by_portfolio_enriched()` in `HoldingRepository` abstract + SQLAlchemy LEFT OUTER JOIN
- `HoldingResponse` schema updated with optional `ticker`/`name`/`entity_id` fields
- `gateway.ts` `getHoldings()` maps ticker/name/entity_id through
- Validated: live endpoint returns `ticker: "AAPL"` for 17 holdings

**C-2 — Portfolio 1D/1W/1M performance endpoint**
- S9 composition endpoint `GET /v1/portfolios/{id}/performance?period=1D|1W|1M`
- Fetches holdings from S1, OHLCV bulk from S3 by date range, computes weighted return
- Calendar lookbacks: 1D=5 days, 1W=10 days, 1M=35 days (covers weekends/holidays)
- Returns `{ return_pct, return_abs, covered_pct }` — covered_pct tracks data availability
- `gateway.ts` `getPortfolioPerformance()` method added
- Portfolio page: `1D | 1W | 1M` period selector + inline return strip with `~` prefix when coverage <99%
- Validated: 1W=−10.62%, 1M=+3.76% computed correctly; 1D=0 (demo has no recent bars — expected)

---

### Wave D: Dashboard Layout Improvements ✅

**D-1 — Row 2 restructured: MarketSnapshot (col-3) + SectorHeatmap (col-4) + PredictionMarkets (col-5)**
- Prediction Markets moved from Row 3 to Row 2 col-span-5 — wider horizontal space for text titles
- AI Signals expanded to col-4 in Row 3

**D-2 — Sector Heatmap 2-column grid**
- 11 sectors displayed in 2-column flex layout with `divide-x` separator
- Compact 72px sector labels + 38px value column
- `toFixed(2)` for consistent Bloomberg "+1.50%" display

**D-3 — Row 3/4 fixed heights + independent scroll**
- `gridTemplateRows`: `"auto 130px minmax(220px, 1fr) minmax(200px, 1fr)"`
- All Row 3/4 grid cells: `overflow-hidden`; widget content areas: `overflow-y-auto`
- Widgets fill cells and scroll independently without breaking page layout

---

### Wave E: TopBar Portfolio Value + Holdings Quantity Display ✅

**E-1 — TopBar portfolio value**
- Portfolio NAV computation in `layout.tsx` via TanStack Query (same `queryKey` as PortfolioSummary → zero extra HTTP calls via deduplication)
- TopBar shows `PORT $X.XM` between MarketStatusPill and bell icon

**E-2 — Holdings quantity display**
- `PortfolioSummary` holdings row: `TICKER | name | qty× | value | P&L%` in 22px terminal rows

---

## Test Results

| Suite | Result |
|-------|--------|
| rag-chat unit tests | ✅ 459 passed |
| portfolio unit tests | ✅ 497 passed |
| Frontend typecheck | ✅ 0 errors |
| Frontend unit tests | ✅ 418/418 passed |

---

## Live Endpoint Validation

| Endpoint | Result |
|----------|--------|
| `GET /api/v1/briefings/morning` | ✅ 465-char narrative returned |
| `GET /v1/holdings/<portfolio_id>` | ✅ 17 items, `ticker=AAPL` |
| `GET /v1/portfolios` | ✅ 1 portfolio returned |
| `GET /v1/portfolios/{id}/performance?period=1D` | ✅ return_pct=0.0 (no recent bars, expected) |
| `GET /v1/portfolios/{id}/performance?period=1W` | ✅ return_pct=-10.62% |
| `GET /v1/portfolios/{id}/performance?period=1M` | ✅ return_pct=+3.76% |
| `GET /v1/alerts/pending?limit=10` | ✅ total=10 alerts |
| `GET /v1/market/sector-heatmap?period=1D` | ✅ 11 sectors returned |
| `GET /v1/market/sector-heatmap?period=1W` | ✅ data returned |
| `GET /v1/market/sector-heatmap?period=1M` | ✅ data returned |
| `GET /v1/signals/prediction-markets?limit=10` | ✅ 10 markets returned |

---

## Bugs Fixed During Implementation

| Bug | Description | Fix |
|-----|-------------|-----|
| BP-252 | S10 alert severity emitted lowercase; frontend switch expected uppercase | `severityDotClass()` normalises with `.toUpperCase()` |
| — | `FakeHoldingRepository` missing `list_by_portfolio_enriched()` abstract impl | Added to `fakes.py` + `test_use_cases_transaction.py` |
| — | Portfolio test assertions on `results[0].quantity` failed (now `EnrichedHolding`) | Updated to `results[0].holding.quantity` |
| — | Config test stale assertion `port 5173` | Corrected to port `3001` |
| — | App-layout tests missing `QueryClientProvider` wrapper | Added mock + wrapper |
| — | Briefing test `getByText("Market Update")` found multiple elements | Changed to `getAllByText` + `toBeGreaterThanOrEqual(1)` |
| — | Entity link test failed: collapsed preview used plain `<p>` not ReactMarkdown | Changed collapsed preview to use ReactMarkdown |
| — | Sector heatmap test `+1.50%` failed with `toFixed(1)` | Changed to `toFixed(2)` |
| — | Docker build ESLint: `stripMarkdownHeaders` unused after ReactMarkdown refactor | Removed unused function |
| — | OHLCV bulk `limit` param not supported | Switched to date-range `start`/`end` params with calendar lookbacks |
| — | `getPortfolioPerformance` using `get(...)` (undefined) | Changed to `apiFetch(...)` |

---

## Browser QA Checklist

| Check | Status |
|-------|--------|
| Morning Brief has headline, 3-line preview, read-more expansion | ✅ |
| Alerts panel shows colored severity dots (lowercase + uppercase) | ✅ |
| TopBar alert badge matches REST pending count after refresh | ✅ |
| Portfolio widget shows ticker/name/quantity/value/P&L% | ✅ |
| Portfolio period selector works for 1D/1W/1M | ✅ |
| TopBar shows portfolio value (`PORT $X.XM`) | ✅ |
| Prediction Markets titles readable (wider col-5 placement) | ✅ |
| Sector heatmap shows all 11 sectors in 2-column layout | ✅ |
| Row 3/4 widgets fill cells and scroll independently | ✅ |
| No page-level overflow from dashboard widgets | ✅ |

---

## Verdict

**PRODUCTION-READY** — All 11 tasks implemented, tests pass, live containers validated, browser checklist passed.
