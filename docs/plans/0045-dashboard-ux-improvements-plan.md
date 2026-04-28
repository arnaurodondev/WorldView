---
id: PLAN-0045
title: Dashboard & Portfolio UX Improvements — Brief Context, Alerts, Holdings Enrichment, Layout
prd: investigation-2026-04-28
status: completed
created: 2026-04-28
updated: 2026-04-28
---

# PLAN-0045 — Dashboard & Portfolio UX Improvements ✅

> **Source**: Investigation report `docs/audits/2026-04-28-investigation-dashboard-ux-report.md`
> **Priority**: HIGH — Morning brief non-functional; portfolio holdings missing ticker/name; alerts visually broken

**Status**: **DONE** — 2026-04-28 · 497 portfolio tests + 459 rag-chat tests + 418 frontend tests pass · ruff + typecheck clean

## Pre-Read List

Before implementing, read:
- `docs/audits/2026-04-28-investigation-dashboard-ux-report.md` — full root cause analysis
- `services/rag-query/.claude-context.md` (Wave A)
- `apps/worldview-web/components/dashboard/MorningBriefCard.tsx` (Wave A)
- `apps/worldview-web/components/shell/AlarmsPanel.tsx` (Wave B)
- `services/alert/src/alert/domain/enums.py` (Wave B)
- `apps/worldview-web/contexts/AlertStreamContext.tsx` (Wave B)
- `services/portfolio/src/portfolio/api/routes/holdings.py` (Wave C)
- `apps/worldview-web/lib/gateway.ts` — getHoldings, getPortfolios (Wave C)
- `apps/worldview-web/app/(app)/dashboard/page.tsx` (Wave D)
- `apps/worldview-web/components/dashboard/SectorHeatmapWidget.tsx` (Wave D)
- `apps/worldview-web/components/dashboard/PredictionMarketsWidget.tsx` (Wave D)
- `apps/worldview-web/components/shell/TopBar.tsx` (Wave E)

---

## Wave A: Morning Brief — Context Fix + Format Redesign ✅

**Status**: **DONE** — 2026-04-28

### Task A-1: Lower S8 min_display_score Threshold ✅

**Target file**: `services/rag-chat/src/rag_chat/application/use_cases/briefing_context.py`

**Changes**:
- Changed `min_display_score` from `0.3` to `0.15` in `_fetch_top_news()`
- Root cause: all 93 articles score 0.23–0.26 → threshold 0.3 returned 0 articles → empty brief

**Validation**: `curl .../v1/briefings/morning` returns 465 chars narrative ✅

---

### Task A-2: Redesign MorningBriefCard for Bloomberg-Grade Presentation ✅

**Target file**: `apps/worldview-web/components/dashboard/MorningBriefCard.tsx`

**Changes**:
1. `extractHeadline()` — parses ## H2 or first **bold** phrase as headline
2. `line-clamp-3` ReactMarkdown preview — always shows 3 visible lines
3. "Read more →" / "show less ↑" expand/collapse for long briefs (>200 chars)
4. H2 headers in expanded view styled as uppercase 9px section labels
5. Entity mentions render as clickable links even in collapsed preview (uses ReactMarkdown throughout)
6. Removed `PREVIEW_CHARS = 200` string slice

**Validation gate**: [x] pnpm typecheck [x] pnpm test (418 pass)

---

### Wave A Validation Gate ✅
- [x] `pnpm typecheck` — 0 errors
- [x] `pnpm test` — 418/418 pass
- [x] Live: `curl .../v1/briefings/morning` returns populated narrative

---

## Wave B: Alerts — Severity Case Fix + Badge Alignment ✅

**Status**: **DONE** — 2026-04-28

### Task B-1: Fix Alert Severity Case Mismatch ✅

**Target file**: `apps/worldview-web/components/shell/AlarmsPanel.tsx`

**Changes**:
1. `severityDotClass()` normalises to uppercase before switch (`severity?.toUpperCase()`)
2. Changed `retry: false` → `retry: 2, retryDelay: 2_000` with `refetchOnMount: true`

---

### Task B-2: Fix TopBar Badge to Reflect REST Pending Count ✅

**Target files**: `apps/worldview-web/app/(app)/layout.tsx`, `apps/worldview-web/components/shell/TopBar.tsx`

**Changes**:
1. Added `useQuery` for `getPendingAlerts({ limit: 1 })` in `layout.tsx` (60s stale, 60s interval)
2. Badge = `Math.max(restTotal, wsCount)` — shows larger of REST vs WebSocket count
3. `TopBar` receives `unreadAlerts` prop carrying the aligned count

---

### Wave B Validation Gate ✅
- [x] `pnpm typecheck` — 0 errors
- [x] `pnpm test` — 418/418 pass
- [x] Live: alerts panel total=10, badge matches

---

## Wave C: Portfolio Holdings Enrichment ✅

**Status**: **DONE** — 2026-04-28

### Task C-1: Add Ticker, Name, Entity_Id to S1 Holdings Endpoint ✅

**Target files**:
- `services/portfolio/src/portfolio/application/use_cases/read_models.py` — `EnrichedHolding` DTO, `GetHoldingsUseCase`
- `services/portfolio/src/portfolio/application/ports/repositories.py` — `list_by_portfolio_enriched` abstract
- `services/portfolio/src/portfolio/infrastructure/db/repositories/holding.py` — SQLAlchemy LEFT OUTER JOIN
- `services/portfolio/src/portfolio/api/schemas.py` — `HoldingResponse` + optional enrichment fields
- `services/portfolio/src/portfolio/api/routes/holding.py` — route maps EnrichedHolding
- `apps/worldview-web/lib/gateway.ts` — `getHoldings()` maps ticker/name/entity_id

**Validation**: Live holdings endpoint returns `ticker: "AAPL"` ✅

---

### Task C-2: Portfolio Page — Add 1D/1W/1M Period Selector with Performance ✅

**Target files**:
- `services/api-gateway/src/api_gateway/routes/proxy.py` — `GET /v1/portfolios/{id}/performance` composition endpoint
- `apps/worldview-web/lib/gateway.ts` — `getPortfolioPerformance()`
- `apps/worldview-web/app/(app)/portfolio/page.tsx` — period selector + performance strip

**Implementation**:
- S9 composition: fetches holdings from S1 + OHLCV bulk from S3 by date range, computes weighted return
- Period lookback: 1D=5 days, 1W=10 days, 1M=35 days calendar (covers weekends/holidays)
- Returns `{ return_pct, return_abs, covered_pct }` — covered_pct shows data availability
- UI: `1D | 1W | 1M` buttons + inline return display in portfolio page header

**Validation**: 1W=-10.62%, 1M=+3.76% computed correctly ✅ (1D=0 because demo seed has no April 23-27 bars)

---

### Wave C Validation Gate ✅
- [x] `python -m pytest tests/ -m "unit"` — 497 passed
- [x] `pnpm typecheck` — 0 errors
- [x] `pnpm test` — 418/418 pass
- [x] Live: holdings returns 17 items with ticker=AAPL
- [x] Live: performance endpoint returns returns for 1W/1M

---

## Wave D: Layout Improvements ✅

**Status**: **DONE** — 2026-04-28

### Task D-1: Row 2 — Prediction Markets to Col-Span-5 ✅

Restructured Row 2: MarketSnapshot (col-3) + SectorHeatmap (col-4) + PredictionMarkets (col-5). Removed PredictionMarkets from Row 3, expanded AI Signals to col-4.

### Task D-2: Sector Heatmap — 2-Column Grid Layout ✅

Split 11 sectors into 2 columns using flex+divide-x. Compact mode uses 72px sector labels and 38px value column. `toFixed(2)` format for consistent Bloomberg display.

### Task D-3: Row 3/4 Fixed Heights + Independent Scroll ✅

Updated `gridTemplateRows` to `"auto 130px minmax(220px, 1fr) minmax(200px, 1fr)"`. All Row 3/4 grid cells have `overflow-hidden`; widget content areas have `overflow-y-auto`.

---

### Wave D Validation Gate ✅
- [x] `pnpm typecheck` — 0 errors
- [x] `pnpm test` — 418/418 pass

---

## Wave E: TopBar Portfolio Value + Holdings Quantity Display ✅

**Status**: **DONE** — 2026-04-28

### Task E-1: Add Portfolio Total Value to TopBar ✅

Added portfolio NAV computation to `layout.tsx` using TanStack Query with same queryKeys as `PortfolioSummary` (zero extra HTTP calls via deduplication). TopBar shows `PORT $X.XM` between MarketStatusPill and bell icon.

### Task E-2: Portfolio Holdings — Show Quantity Alongside Value ✅

`PortfolioSummary` holdings row: `TICKER | name | qty× | value | P&L%` using h-[22px] terminal rows.

---

### Wave E Validation Gate ✅
- [x] `pnpm typecheck` — 0 errors
- [x] `pnpm test` — 418/418 pass

---

## Validation Gates Summary

| Gate | Result |
|------|--------|
| rag-chat unit tests | ✅ 459 passed |
| portfolio unit tests | ✅ 497 passed |
| Frontend typecheck | ✅ 0 errors |
| Frontend unit tests | ✅ 418/418 pass |
| Live brief narrative | ✅ 465 chars returned |
| Live holdings enriched | ✅ ticker=AAPL, 17 holdings |
| Live alerts total | ✅ total=10 |
| Live performance 1W | ✅ -10.62% |
| Live performance 1M | ✅ +3.76% |
| Live prediction markets | ✅ 10 markets |

---

## Task Status

| Task | Status |
|------|--------|
| A-1: S8 min_display_score threshold | ✅ DONE |
| A-2: MorningBriefCard redesign | ✅ DONE |
| B-1: Alert severity case fix | ✅ DONE |
| B-2: TopBar badge REST alignment | ✅ DONE |
| C-1: S1 holdings enrichment (ticker/name) | ✅ DONE |
| C-2: Portfolio 1D/1W/1M performance | ✅ DONE |
| D-1: Row 2 restructure (Prediction Markets) | ✅ DONE |
| D-2: Sector 2-column grid | ✅ DONE |
| D-3: Row 3/4 fixed heights + independent scroll | ✅ DONE |
| E-1: TopBar portfolio value | ✅ DONE |
| E-2: Holdings quantity display | ✅ DONE |
