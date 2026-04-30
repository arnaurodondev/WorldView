---
id: PLAN-0047
title: Dashboard UX Phase 2 — Watchlist Movers, Sector Treemap, Volume Fix, Alert Enrichment
prd: qa-follow-up-2026-04-28
status: draft
created: 2026-04-28
updated: 2026-04-28
---

# PLAN-0047 — Dashboard UX Phase 2

> **Source**: QA follow-up report `docs/audits/2026-04-28-qa-plan-0045-follow-up-report.md`
> **Priority**: HIGH — PreMarketMovers shows $0.00 prices; sector heatmap visually weak; prediction volume always missing

**Status**: **SUPERSEDED by PLAN-0048** (2026-04-28) — All 5 waves absorbed into `docs/plans/0048-dashboard-ux-phase3-plan.md` waves D/E/F. Implement PLAN-0048 instead.

**Already fixed in parent QA commit (not part of this plan)**:
- Prediction volume null-guard ($0 → hidden) ✅
- Alert rows now clickable to /alerts ✅
- TopBar labels "D"→"Daily", "U"→"Unrlzd" ✅
- Morning Brief single-line header (date | title | CTA) ✅
- TOP MOVERS price $0.00 → "—" ✅

---

## Pre-Read List

Before implementing, read:
- `docs/audits/2026-04-28-qa-plan-0045-follow-up-report.md` — root cause analysis for each wave
- `apps/worldview-web/components/dashboard/PreMarketMoversWidget.tsx` (Wave A)
- `apps/worldview-web/lib/gateway.ts` — getWatchlistMembers, getTopMovers (Wave A)
- `apps/worldview-web/components/dashboard/SectorHeatmapWidget.tsx` (Wave B)
- `services/market-data/src/market_data/api/routers/prediction_markets.py` (Wave C)
- `services/market-data/src/market_data/infrastructure/db/repositories/prediction_market_repo.py` (Wave C)
- `services/alert/src/alert/` (Wave D)

---

## Wave A: Replace PreMarketMoversWidget with Watchlist Movers

**Status**: PENDING

### Context

`PreMarketMoversWidget` fetches market-wide top gainers/losers but has two problems:
1. The screener endpoint returns no price data → all prices show "$0.00" → visually broken
2. Market-wide movers are less actionable for investors than their own watchlist

### Task A-1: WatchlistMoversWidget Component

**Target file**: `apps/worldview-web/components/dashboard/WatchlistMoversWidget.tsx` (new)

**Implementation**:
1. Fetch user's first watchlist via `getWatchlists()` → pick first watchlist ID
2. Fetch `getWatchlistMembers(watchlistId)` to get instrument IDs
3. Fetch `getBatchQuotes(instrumentIds)` to get live prices + daily change
4. Show instruments sorted by `|change_pct|` descending (biggest absolute movers first)
5. Two columns: gainers (change_pct > 0) | losers (change_pct < 0)
6. If no watchlist: show empty state "Add instruments to your watchlist to see daily movers here"
7. Period selector (1D/1W/1M) — where 1W/1M use the OHLCV endpoint if available

**Widget layout** (col-span-4, Row 3):
```
WATCHLIST MOVERS                          [1D] [1W] [1M]
GAINERS              | LOSERS
AAPL  $192.50 +2.3%  | NVDA $209.53 -3.5%
AMZN  $261.76 +1.8%  | MSFT $419.77 -2.9%
...                  | ...
```

**Validation**:
- [ ] pnpm typecheck — 0 errors
- [ ] pnpm test — all pass
- [ ] Dashboard: column 3 shows watchlist-specific movers

### Task A-2: Replace PreMarketMoversWidget in dashboard layout

**Target file**: `apps/worldview-web/app/(app)/dashboard/page.tsx`

**Changes**:
1. Replace `<PreMarketMoversWidget />` with `<WatchlistMoversWidget />`
2. Update import

**Validation gate**:
- [ ] pnpm typecheck — 0 errors
- [ ] pnpm test — all pass

---

## Wave B: Sector Heatmap Treemap Visualization

**Status**: PENDING

### Context

The current 2-column table in `SectorHeatmapWidget` is functional but not visually compelling. Users want a treemap where sector size reflects market cap (or equal-weighted) and color reflects performance. This gives an immediate visual scan of which sectors dominate and which are declining.

### Task B-1: Treemap Sector Heatmap

**Target file**: `apps/worldview-web/components/dashboard/SectorHeatmapWidget.tsx`

**Implementation**:
1. Keep the existing data fetching (sector performance from `getMarketHeatmap()`)
2. Replace the 2-column list with a CSS-grid treemap or use `recharts` TreeMap component
3. Each sector is a colored rectangle: width proportional to weight (or equal), fill color = green/red based on % change
4. Text: sector abbreviation + % change inside each rectangle
5. Tooltip on hover: full sector name + % change

**Design constraints**:
- Row 2 height = 130px fixed — the treemap must fit in ~100px (accounting for header)
- Sector abbreviations: "Info Tech", "Hlth Care", "Financials", etc. (10 chars max)
- Color: `text-positive` (green) for positive, `text-negative` (red) for negative, gray for 0%
- No external dependencies beyond recharts (already in the project? check first)

**Library decision**:
- If recharts is already installed: use `recharts/TreeMap`
- If not: implement a pure CSS flex-based treemap (simpler, no dependency)
- Pure CSS approach: flex-wrap layout with percentage widths proportional to abs(change_pct) + min-size

**Validation gate**:
- [ ] pnpm typecheck — 0 errors
- [ ] pnpm test — all pass
- [ ] Dashboard Row 2: visual treemap visible with colored rectangles

---

## Wave C: S3 Prediction Markets Volume JOIN Fix

**Status**: PENDING

### Context

S3's prediction market list endpoint always returns `volume_24h=None` because volume is stored in snapshots, not on the market entity. The frontend null-guard (applied in Wave A of PLAN-0045 follow-up) prevents "$0 vol" from showing, but doesn't provide real data.

### Task C-1: Add volume from latest snapshot to list endpoint

**Target files**:
- `services/market-data/src/market_data/infrastructure/db/repositories/prediction_market_repo.py`
- `services/market-data/src/market_data/api/routers/prediction_markets.py`

**Implementation**:
1. In `PgPredictionMarketRepository.list_markets()`, add a sub-query to fetch the latest `volume_24h` for each market from `prediction_market_snapshots`:
   ```sql
   LEFT JOIN (
     SELECT DISTINCT ON (market_id) market_id, volume_24h
     FROM prediction_market_snapshots
     ORDER BY market_id, snapshot_at DESC
   ) latest_snap ON pm.market_id = latest_snap.market_id
   ```
2. Pass `volume_24h` from the join result back through the domain entity to the API response
3. Remove the `volume_24h=None` hardcoded value in the router

**Validation gate**:
- [ ] python -m pytest tests/ -m "unit" — all pass
- [ ] Live: `GET /v1/signals/prediction-markets?status=open` returns non-null volume_24h for markets that have snapshots

---

## Wave D: SIGNAL Alert Payload Enrichment

**Status**: PENDING

### Context

S10 SIGNAL alerts sent by the signal scoring worker lack `signal_label`, `entity_name`, `ticker` in the payload. The frontend fallback produces "LOW SIGNAL alert" instead of actionable context like "AAPL: Bearish momentum signal".

### Task D-1: Inject entity context into signal alert payloads

**Target files**:
- `services/alert/src/alert/application/workers/` (signal alert worker)
- `services/alert/src/alert/domain/` (alert creation)

**Changes**:
1. In the signal alert creation path, include these fields in the `payload` dict:
   - `signal_label`: human-readable signal type (e.g., "Bearish Momentum", "Volume Spike")
   - `entity_name`: company name from the knowledge graph
   - `ticker`: instrument ticker symbol
2. If entity data is not available at alert creation time, include at minimum the `instrument_id`

**Validation gate**:
- [ ] python -m pytest tests/ -m "unit" — all pass
- [ ] Live: SIGNAL alerts in Recent Alerts show ticker/signal context instead of "LOW SIGNAL alert"

---

## Wave E: Top Movers Sector Filter Buttons

**Status**: PENDING

### Context

The user wants the top movers widget to have buttons to filter by sector (Overall, Technology, Financials, etc.). This makes it easy to see which sector's movers drove the day's performance.

### Task E-1: Sector filter in WatchlistMoversWidget

**Target file**: `apps/worldview-web/components/dashboard/WatchlistMoversWidget.tsx`

**Implementation**:
1. Fetch sector data alongside quotes (use existing `getMarketHeatmap()` for sector names)
2. Map instrument → sector using company overview data (`getSectorForInstrument()`)
3. Add a horizontal scrolling pill row with sector filter buttons: "All" + each sector
4. Filter displayed movers client-side by selected sector
5. Default: "All"

**Note**: This requires knowing which sector each instrument belongs to. Use company overview `sector` field if available.

---

## Validation Gates Summary

| Gate | Wave |
|------|------|
| pnpm typecheck | A, B, E |
| pnpm test (418 pass) | A, B, E |
| market-data unit tests | C |
| alert unit tests | D |
| Live: watchlist movers display | A |
| Live: sector treemap visible | B |
| Live: prediction volume non-null | C |
| Live: SIGNAL alerts show ticker context | D |

---

## Task Status

| Task | Status |
|------|--------|
| A-1: WatchlistMoversWidget | pending |
| A-2: Replace PreMarketMovers in dashboard | pending |
| B-1: Sector heatmap treemap | pending |
| C-1: S3 prediction volume JOIN | pending |
| D-1: Signal alert payload enrichment | pending |
| E-1: Sector filter in movers widget | pending |
