# Subagent 1A — Dashboard / Home Route Audit
**Quality Score: 7/10**

## Files Read
- `app/(app)/dashboard/page.tsx` (239 lines)
- `app/page.tsx` (244 lines)
- `lib/api/dashboard.ts` (290 lines)
- `components/dashboard/MorningBriefCard.tsx` (648 lines)
- `components/dashboard/DashboardSnapshotPrefetcher.tsx` (35 lines)
- `components/dashboard/MarketSnapshotWidget.tsx` (317 lines)
- `components/dashboard/SectorHeatmapWidget.tsx` (510 lines)
- `components/dashboard/AiSignalsWidget.tsx` (247 lines)
- `components/dashboard/MoversWidgetTabs.tsx` (131 lines)
- `components/dashboard/PortfolioSummary.tsx` (474 lines)
- `components/dashboard/RecentAlerts.tsx` (235 lines)
- `components/dashboard/EconomicCalendar.tsx` (189 lines)
- `components/dashboard/PredictionMarketsWidget.tsx` (579 lines)

## Layout Issues
1. MorningBriefCard header wastes vertical space (h-6 + 12+12px padding for single-line header)
2. Dashboard grid responsive layout is fragile at tablet (md:grid-cols-6 doesn't reflow asymmetric 3+4+5 row cleanly) — should be md:grid-cols-2
3. Row 4 cells (Economic Cal / Earnings / Portfolio News / Alerts) fragment at tablet
4. MorningBriefCard spans full 12 cols with no max-width on text → narrative reads full-width article instead of compact signal

## Component Issues
1. MorningBriefCard staleTime=30min vs "generated once per day" → user opens at 10:05 sees 2h-old brief
2. DashboardSnapshotPrefetcher: silent failure, no error logging
3. MarketSnapshotWidget: 2-step waterfall (search → overview) for 9 tickers → 300-500ms idle, >1s under load
4. PortfolioSummary: 3-step waterfall (portfolios → holdings → quotes) → no skeleton for quotes step, UI flickers
5. RecentAlerts: uses both WebSocket + 30s polling → max 30s delay if WS drops
6. EconomicCalendar parseDesc() regex fragile (assumes [\d.-]+, breaks on N/A, $1.2B, 1,234.5)
7. Multiple widgets >200 lines but justified (MorningBriefCard 648, PredictionMarkets 579, PortfolioSummary 474, SectorHeatmap 510)

## Design Violations (file:line)
1. `components/dashboard/MorningBriefCard.tsx:569` — bare `rounded` instead of `rounded-[2px]`
2. `components/dashboard/PredictionMarketsWidget.tsx:134, 155, 156` — bare `rounded`
3. `components/dashboard/PreMarketMoversWidget.tsx:266` — bare `rounded` on period selector
4. `components/dashboard/WatchlistMoversWidget.tsx:281` — bare `rounded` on period selector
5. `components/dashboard/MorningBriefCard.tsx:348, 353` — `text-[9px]` outside approved range [10-13px]
6. `text-[9px]` system-wide in PreMarketMoversWidget and PredictionMarketsWidget (multiple lines)

## Functional Bugs
1. `app/(app)/dashboard/page.tsx:122` — `height: "calc(100vh - 36px)"` hardcodes topbar height; breaks on mobile
2. `MarketSnapshotWidget.tsx:170-171` — LIVE badge hides if ANY ticker search fails (should show if at least 1 resolves)
3. `PortfolioSummary.tsx:32` — QUOTE_REFETCH_MS imported but staleTime not visible locally (hidden dependency)
4. `RecentAlerts.tsx:49-60` — merged alerts ordered live-first, not by severity (HIGH alert after LOW poll → appears lower)
5. `lib/api/dashboard.ts:191-192` — Economic event impact defaults MEDIUM if confidence missing; Fed events misclassified
6. `MorningBriefCard.tsx:280-285` — entity linkification silent when entity_mentions=[]
7. `DashboardSnapshotPrefetcher` — prefetched cache wasted if widget queryKeys differ from snapshot structure
8. `SectorHeatmapWidget.tsx:22` — H-56px assumes exactly 11 sectors; breaks on 12+ sector returns

## API Calls
| Endpoint | staleTime | Refetch |
|----------|-----------|---------|
| /v1/briefings/morning | 30min | retry 2x |
| /v1/market/heatmap | **0 (!)**  | none |
| /v1/market/top-movers | 2min | 2min |
| /v1/search/instruments | 30min | — |
| /v1/companies/{id}/overview | 5min | 60s |
| /v1/portfolios | 60s | — |
| /v1/holdings/{pid} | 30s | — |
| /v1/quotes/batch | QUOTE_REFETCH_MS (hidden) | same |
| /v1/dashboard/snapshot | unspecified | — |
| /v1/fundamentals/economic-calendar | 10min | 10min |
| /v1/signals/ai | 2min | 2min |
| /v1/signals/prediction-markets | unspecified | — |
| /v1/alerts?acknowledged=false | 15s | 30s |

## Priority Issues
1. **Design system: 4 components use bare `rounded` (4px) not `rounded-[2px]`** — MorningBriefCard:569, PredictionMarkets:134, PreMarketMovers:266, WatchlistMovers:281
2. **Dashboard grid broken at tablet** — `md:grid-cols-6` cannot reflow asymmetric Row 2; iPad users see fragmented dashboard
3. **MorningBriefCard staleTime conflicts with daily generation** — user sees stale brief mid-morning
4. **LIVE badge hides if any ticker fails** — partial resolution looks like total failure
5. **Hardcoded `calc(100vh - 36px)` topbar height** — breaks responsive
