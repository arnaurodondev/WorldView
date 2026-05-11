# Workspace Panel Catalogue Audit — 2026-04-29

**Plan**: PLAN-0051 Wave C Part 1 (T-C-3-02)
**Decision rule**: Per Risk D-5 — REMOVE entries that are stubs or missing; do NOT
ship "Coming Soon" tiles.

## Scope

Every entry in `PANEL_CATALOGUE` (declared in `apps/worldview-web/components/workspace/WorkspaceGrid.tsx`)
plus every dispatch case in `PanelContent` (in `WorkspacePanelContainer.tsx`) was
verified by:

1. Locating the component file referenced for the panel type.
2. Reading the component's render output to confirm it produces real UI (not a
   placeholder, not "Coming Soon", not a permanent skeleton).
3. Checking the rendered shape against the PRD-0031 §5.4 panel-widget spec
   (22-px row height, 11-px tabular-nums data text, real S9 calls where
   applicable).

## Audit Result

| panel_type | component_path | status | notes |
|------------|----------------|--------|-------|
| `chart` | `apps/worldview-web/components/workspace/WorkspaceChartWidget.tsx` | READY | Lightweight-charts v4 candlestick + 5 timeframe pills (1D/1W/1M/3M/1Y). Empty state when no symbol linked. Live S9 calls via `getOHLCV`. |
| `watchlist` | `apps/worldview-web/components/workspace/WorkspaceWatchlistWidget.tsx` | READY | 4-column compact table (ticker / price / chg%) with 30-second `refetchInterval` against `getBatchQuotes`. |
| `screener` | `apps/worldview-web/components/workspace/WorkspaceScreenerWidget.tsx` | READY | Top-20 by `market_impact_score` with always-visible column header. Real `runScreener` call, error state, click→navigate to instrument. |
| `alerts` | `apps/worldview-web/components/alerts/AlertsList.tsx` | READY | Reused from full Alerts page; severity-grouped pending alerts via `getPendingAlerts`. |
| `fundamentals` | `apps/worldview-web/components/workspace/WorkspaceFundamentalsWidget.tsx` | READY | 6-metric compact vertical table (Mkt Cap, P/E, P/B, Div Yield, ROE, Beta). Renders empty state when no symbol linked. |
| `news` | `apps/worldview-web/components/workspace/WorkspaceNewsPanel.tsx` | READY | Top-15 news from `getTopNews` with relative timestamps + composite-score badge. |
| `graph` | `apps/worldview-web/components/instrument/EntityGraphPanel.tsx` | READY | SVG depth-1 entity graph (reused from Overview sidebar). Falls back to demo AAPL when no symbol linked. |
| `portfolio` | `apps/worldview-web/components/workspace/WorkspacePortfolioPanel.tsx` | READY | First-portfolio holdings via `getHoldings`. 22-px rows, P&L color semantics. |
| `brief` | `apps/worldview-web/components/workspace/WorkspaceBriefWidget.tsx` | READY | Collapsible morning-brief panel with primary-yellow AI accent. Real `getMorningBrief` call. |
| `chat` | `apps/worldview-web/components/workspace/WorkspaceChatWidget.tsx` | READY | SSE streaming chat with starter questions, `streamChat` integration, ephemeral session. |

### Tally

- **READY**: 10
- **STUB**: 0
- **MISSING**: 0
- **REMOVED**: 0

## Decision

All 10 panel types map to real, S9-backed components that pass the §5.4 panel-widget
spec. No catalogue entries were removed in this Part 1 sweep.

`WorkspaceChartWidget` and `WorkspaceFundamentalsWidget` are the panel-sized
analogues of the heavier `OHLCVChart` / `FundamentalsTab` components used on the
Instrument Detail page; they were created in parallel with this audit and are
already wired into `WorkspacePanelContainer`'s dispatch table.

## Out of scope (Part 2 territory)

The PLAN-0051 Wave C Part 2 will:

- Build the planned 5 named templates (`Day Trader`, `Research`, `Swing Trader`,
  `News Junkie`, `Investor`) in `NewFromTemplateDialog.tsx` (file already
  scaffolded but template list deferred).
- Deliver share-via-URL (base64-encoded WorkspaceConfig in URL param).
- Iterate on `WorkspaceChartWidget` indicators / drawing if PRD demand surfaces.

These items are tracked under T-C-3-06, T-C-3-07, and follow-on T-C-3-03 work
respectively.

## Re-audit cadence

Re-run this audit when:

- A new `PanelType` is added to the `WorkspaceContext` union.
- A widget gets re-purposed (e.g. point at a different S9 endpoint).
- Risk D-5 is revisited at a future milestone.
