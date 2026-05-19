# PRD-0088 — Instrument Detail Page: Ground-Up Visual Redesign

**Date**: 2026-05-19
**Status**: APPROVED
**Author**: Arnau Rodon
**Type**: Frontend visual redesign — frontend only (no new backend endpoints)
**Supersedes**: PLAN-0041 (instrument page redesign — completed but insufficient quality), PLAN-0071 Phase 6.5+ (density sprint — suspended, subsumed here)
**Depends on**: PRD-0025 (auth), PRD-0026 (news intelligence), PRD-0031 (Terminal UI v3 design system)
**Scope**: `apps/worldview-web/app/(app)/instruments/[entityId]/` and all `components/instrument/` files

---

## 1. Problem Statement

The current instrument detail page (`/instruments/[entityId]`) was redesigned in PLAN-0041 (completed 2026-04-27) but remains significantly below the quality bar required to present to institutional investors. Specific failure points:

1. **Density too low**: Despite claiming 22px data rows, effective visual density is ~30px due to `py-1.5` padding inside rows, heavy section card headers, and excessive whitespace in the 3-column lower grid.
2. **Fundamentals tab uses section cards, not a professional flat table**: Nine section cards with individual headers take 50% of vertical space for borders and labels. Bloomberg and Finviz show 60+ metrics in a flat 3-column grid — the same data density in 40% of the height.
3. **Structural components consuming screen real estate with low signal-to-noise**: `InstrumentAISubheader` (yellow strip), `AnalystRail` (mod+/ docked panel), `PerformanceBar` (dedicated 32px row for data that fits in 2 metric table cells), and the 3-equal-column lower grid with headers taller than their content.
4. **Real bugs blocking professionalism**: Chart scrolls to 1985 on load (race condition in `useChartSeries`), entity graph black void below panel, entity graph node detail panel never populates (S9 drops edge fields).
5. **News and Intelligence are separate tabs**: For a thesis demonstrating AI-powered market intelligence, these should be unified — an investor should see the graph, the news, and the entity context in one integrated view.
6. **Component monoliths**: `NewsTab.tsx` (835 lines), `OHLCVChart.tsx` (367+ lines with drawing inline). These block iteration. Every new component in this PRD must be a single-responsibility unit.

**Target quality**: Finviz (data density, metrics table approach), Bloomberg Terminal (information hierarchy, no decoration), Interactive Brokers TWS Mosaic (workspace discipline, labeled density).

---

## 2. Target Users

**Primary**: Thesis committee reviewers and potential institutional investors evaluating the platform's data quality and analytical depth. They will compare Worldview against Bloomberg and Refinitiv. The current UI immediately signals "hobby project." The redesigned page must signal "institutional-grade terminal."

**Secondary**: Active retail investors who monitor 10–50 positions, require fast drill-down from screener → instrument detail → news/intelligence context.

**What they need (not negotiable)**:
- ≥40 data points visible above the fold on the Quote tab without scrolling
- Chart visible immediately, no waterfall loading
- Analyst consensus, 52W range, beta, and margin data visible without clicking into Financials
- News headlines visible without switching to a separate tab
- Entity graph accessible in the same view as news context

---

## 3. Functional Requirements

### FR-1: Three-tab architecture
The page MUST have exactly 3 tabs: **QUOTE** | **FINANCIALS** | **INTELLIGENCE**.

### FR-2: Persistent compact header
A 36px header MUST be visible on all tabs and on scroll. It shows: ticker, exchange, company name, live price, change $, change %, market cap, daily volume, P/E ratio, and 52W range mini bar.

### FR-3: AI Brief Banner (redesigned)
The AI brief (from `GET /v1/briefings/instrument/{entityId}`) MUST be displayed as a single-line collapsible banner immediately below the tab bar, visible on all 3 tabs. It replaces the current `InstrumentAISubheader` (yellow strip). No yellow border. Collapses to 24px showing first 120 characters. Expands on click to show full brief text. Collapse state persisted per session in sessionStorage. Loading and unavailable states handled gracefully.

### FR-4: Quote tab — Chart + Dense Metrics
**Left (60% width)**: Full-width OHLCV chart with lightweight-charts. Timeframe toolbar (1D / 1W / 1M / 6M / 1Y / 5Y). Indicator toolbar (MA50 / MA200 / Volume / RSI / MACD — indicators apply inline overlays, not separate panels). Session stats strip below chart: O H L C Vol in compact 22px row.

**Right (40% width)**: Dense metrics table (MetricsTable) showing ≥26 metric rows at 22px each, organized into labeled groups with 1px blank-row separators. No section cards. No section headers taking full rows. Group labels are inline using 10px ALL CAPS muted text on the first row of each group. Full spec in §6.4.

### FR-5: Financials tab — Flat metrics grid + sidebar
**Main content (calc(100% - 280px))**: Flat 3-column metrics grid (`FlatMetricsGrid`) showing ≥45 metrics across 8 groups (Valuation, Profitability, Growth, Balance Sheet, Cash Flow, Dividends, Ownership, Technicals). No section cards. Groups separated by 1px divider with 10px ALL CAPS group label. Below the grid: 4-year income statement table (`IncomeStatementTable`), earnings history bar chart (`EarningsBarChart`).

**Right sidebar (280px)**: Analyst consensus section (Buy/Hold/Sell counts as a micro bar chart, median target, high/low range), peer comparison mini table (3–4 peers from entity graph neighbors, if available), data timestamp footer.

### FR-6: Intelligence tab — 3-column unified view
**Left column (30%)**: Compact news column (`NewsColumn`) showing entity-scoped articles as single-row compact items at 28px each. Filters: time range (All / Today / 3d / 1w), sentiment toggle. No tabs. Infinite scroll (load-20 per page). Article row format: `[sentiment dot] [time] [source] [headline truncated] [impact score]`.

**Center column (45%)**: AI Brief full-text card at top (always expanded on Intelligence tab). Entity graph below (Cytoscape/sigma.js, fixed bugs — depth timeout, node panel). Graph toolbar: depth slider 1–3, relationship type filter. Fullscreen button.

**Right column (25%)**: Context panel that adapts based on graph selection state. When no node selected: entity overview (name, type, description, health score). When node selected: selected entity detail (name, type, description, confidence score, last updated), outgoing/incoming relations list (edge type, target name, confidence, evidence snippet). Contradictions cards at bottom (when count > 0).

### FR-7: Single-responsibility components
Every new component MUST be ≤200 lines. Orchestrator files (`QuoteTab.tsx`, `FinancialsTab.tsx`, `IntelligenceTab.tsx`) are exempt (max 300 lines). No inline hooks that also return JSX. Logic extracted to `use*.ts` hook files. Data fetching in dedicated hooks only, never inline in components.

### FR-8: Remove deprecated components
The following MUST be deleted as part of this PRD's implementation:
- `InstrumentAISubheader.tsx` (replaced by `AiBriefBanner`)
- `AnalystRail.tsx` (no replacement — data moved into MetricsTable)
- `PerformanceBar.tsx` (data moved into MetricsTable: 1D/5D/1M/3M/1Y rows)
- `OverviewLayout.tsx` (replaced by `QuoteTab.tsx`)
- `FundamentalsTab.tsx` (replaced by `FinancialsTab.tsx`)
- `InstrumentKeyMetrics.tsx` (replaced by `MetricsTable`)
- `NewsTab.tsx` (replaced by `NewsColumn` inside `IntelligenceTab`)
- All other existing `components/instrument/` files (see §6.7 for full list)

### FR-9: IBM Plex Mono on ALL numeric values
Every number, price, percentage, volume, ratio, and date displayed on the instrument detail page MUST use `font-mono tabular-nums`. This is ADR-F-15. No exceptions. Zero-state placeholder "—" MUST also use `font-mono`.

### FR-10: Color coding rules (consistent across the page)
- **Price/change positive**: `text-positive` (#26A69A teal)
- **Price/change negative**: `text-negative` (#EF5350 red)
- **P/E > 30**: `text-amber-400`; **> 50**: `text-negative`
- **ROE/ROA positive**: `text-positive`; **negative**: `text-negative`
- **Debt/Equity > 2**: `text-amber-400`; **> 4**: `text-negative`
- **Beta > 1.5**: `text-amber-400`; **> 2.5**: `text-negative`; **< 0.5**: `text-muted-foreground`
- **Sentiment positive**: dot `bg-positive`; **negative**: `bg-negative`; **neutral**: `bg-muted-foreground`
- **Analyst consensus**: Buy bars `bg-positive`, Hold bars `bg-amber-400`, Sell bars `bg-negative`

---

## 4. Non-Functional Requirements

| NFR | Target | Measurement |
|-----|--------|-------------|
| Initial page load (bundle) | < 1.5s TTI on fast 3G | Lighthouse |
| Chart render after data | < 200ms from data arrival | React DevTools |
| Tab switch latency | < 50ms (all data pre-fetched) | Navigation timing |
| OHLCV chart first paint | Skeleton → chart in < 300ms | Network tab |
| Bundle hit rate | ≥ 95% on page enter (5min stale) | TanStack Devtools |
| Type errors | 0 (strict TypeScript) | `tsc --noEmit` |
| Visual regressions | 0 (compared to spec) | Manual review |

---

## 5. Out of Scope

- No new backend API endpoints (all data already served by S9)
- No changes to S9, S3, S6, S7, or any backend service
- No changes to `/instruments/` screener page
- No changes to `/intelligence/[entityId]` page
- No changes to dashboard, portfolio, or news pages
- No real-time WebSocket price streaming (quote polls every 30s via TanStack Query)
- No drawing tools / chart annotations in this redesign (existing `useChartSeries` hook keeps annotation support but `DrawingPalette.tsx` and `DrawingCanvas.tsx` are deferred to a future wave)
- No dark/light mode toggle (always dark, per ADR)
- No mobile responsiveness optimization (desktop-first, min-width: 1280px)

---

## 6. Technical Design

### 6.1 Affected Services

| Service | Change | Why |
|---------|--------|-----|
| `apps/worldview-web` | Delete all `components/instrument/` files; rebuild from this spec | Visual redesign |
| No backend services | No change | All required data served by existing S9 endpoints |

**Break surface**: All existing Playwright E2E tests for `/instruments/[entityId]` will fail. They MUST be rewritten as part of implementation Wave E.

### 6.2 Page Structure and Routing

**Route**: `app/(app)/instruments/[entityId]/` (unchanged)
- `layout.tsx` — SSR metadata wrapper (keep as-is, just generates `<title>TICKER — Worldview</title>`)
- `page.tsx` — Server component boundary: validates `entityId`, renders `<InstrumentPageClient entityId={entityId} />`

`InstrumentPageClient.tsx` — the client component root (`"use client"`). Fetches the page bundle, seeds caches, renders header + tab bar + active tab.

### 6.3 Data Loading Strategy

**On page enter**: `GET /v1/instruments/{entityId}/page-bundle` (single request, 5min stale).

Returns:
```
bundle.overview.instrument  → seeds ["instrument", entityId]
bundle.overview.quote       → seeds ["quote", instrumentId]
bundle.overview.fundamentals→ NOT seeded (FundamentalsSection shape mismatch with Fundamentals type — BP-379)
bundle.overview.ohlcv       → seeds ["ohlcv", instrumentId, "1D"]
bundle.technicals           → seeds ["technicals", instrumentId]
bundle.insider              → seeds ["insider-transactions", instrumentId]
bundle.top_news             → NOT seeded (shape mismatch with news entity endpoint)
```

**Lazy per-tab**:
- Quote tab: `getFundamentalsSnapshot(instrumentId)` + `getShareStatistics(instrumentId)` + `getTechnicals(instrumentId)` — all deduped by TanStack Query if already fetched
- Financials tab: `getFundamentals(instrumentId)` + `getFundamentalsSnapshot(instrumentId)` + `getIncomeStatement(instrumentId)` + `getEarningsHistory(instrumentId)` + `getShareStatistics(instrumentId)`
- Intelligence tab: `getEntityGraph(entityId)` + `getEntityIntelligence(entityId)` + `getInstrumentBrief(entityId)` + `getEntityNews(entityId, {limit: 20})`

---

### 6.4 Header Specification

**File**: `components/instrument/header/InstrumentHeader.tsx`
**Height**: 36px (single row)
**Position**: sticky top-0, z-30, bg-background border-b border-border

**Left cluster** (flex row, gap-3):
- Back button `←` (`size-5` chevron-left, no text label)
- Ticker: `text-[13px] font-semibold font-mono tracking-wide` (e.g., "AAPL")
- Exchange badge: `text-[10px] text-muted-foreground bg-muted/30 px-1.5 rounded-[2px]` (e.g., "NASDAQ")
- Company name: `text-[11px] text-muted-foreground` (truncated with `truncate max-w-[200px]`)

**Right cluster** (flex row, gap-4, ml-auto):
- Price: `text-[13px] font-mono font-semibold tabular-nums`
- Change: `text-[12px] font-mono tabular-nums` colored by sign (e.g., "+$1.42 (+0.47%)")
- Separator `|` text-muted-foreground/30
- Market Cap: `text-[10px] text-muted-foreground` label + `text-[11px] font-mono` value (e.g., "CAP $3.07T")
- Volume: `text-[10px] text-muted-foreground` label + `text-[11px] font-mono` value (e.g., "VOL 42.3M")
- P/E: `text-[10px] text-muted-foreground` label + `text-[11px] font-mono` value (e.g., "P/E 36.0")
- 52W range mini bar (WeekRangeMini — 60px wide, 6px tall, yellow fill at position)
- LiveQuoteBadge (compact staleness indicator only — no second price display)

**Data sources**: All from bundle.overview (instrument + quote + fundamentals). Quote polls separately every 30s via LiveQuoteBadge.

---

### 6.5 AI Brief Banner Specification

**File**: `components/instrument/brief/AiBriefBanner.tsx`
**Position**: Below header, above tab bar. Visible on all 3 tabs.
**Data source**: `GET /v1/briefings/instrument/{entityId}` (staleTime: 10min)

**Collapsed state (24px height)**:
- Left: `▶` chevron icon (8px, rotates 90° when expanded)
- Label: `BRIEF` (10px, ALL CAPS, text-muted-foreground)
- Content: first 140 characters of brief text, `text-[11px] text-foreground/70 truncate`
- Right: entity health score badge (from entity intelligence if cached, else omit)
- Background: `bg-card` (subtle separation from header)
- Border-bottom: 1px border-border/50

**Expanded state**:
- Full brief text, `text-[11px] leading-[1.5]`, markdown NOT rendered (plain text)
- Max-height: 120px with overflow-y-auto
- Timestamp: `text-[10px] text-muted-foreground` "Updated {relative time}"
- Collapse on second click

**Loading state**: Single skeleton line, 60% width
**Unavailable state**: Show nothing (banner hidden entirely if brief returns 404 or is null)

**sessionStorage key**: `wv:brief-collapsed:{entityId}` → persists collapse preference

---

### 6.6 Tab Bar Specification

**File**: `components/instrument/tabs/InstrumentTabs.tsx`
**Height**: 32px
**Style**: Underline tab style (not card tabs). Active tab: 2px border-bottom `border-primary` + `text-foreground`. Inactive: `text-muted-foreground hover:text-foreground/70`. Font: `text-[11px] font-medium tracking-wide uppercase`.

**Tabs**:
1. `QUOTE` — default active
2. `FINANCIALS`
3. `INTELLIGENCE`

**Keyboard mnemonics** (scoped to instrument route via HotkeyScope):
- `Q` → switch to Quote tab
- `F` → switch to Financials tab
- `I` → switch to Intelligence tab

---

### 6.7 Tab 1: Quote

**File**: `components/instrument/quote/QuoteTab.tsx`
**Layout**: `flex gap-0` full-height (fills viewport height minus header + banner + tabbar)

#### 6.7.1 Left Panel — Chart (60% width)

**Chart container**: `flex-1 min-w-0 flex flex-col`
- `TimeframeToolbar.tsx` (28px): tabs 1D | 1W | 1M | 6M | 1Y | 5Y + Log scale toggle
- `ChartToolbar.tsx` (28px): MA50 toggle | MA200 toggle | VOL toggle | IND dropdown (RSI, MACD, BB) | Fullscreen button
- `OHLCVChart.tsx` (fills remaining height, min-height: 240px): lightweight-charts candlestick. **Bug fix required**: remove `hasScrolledToRealTime.current = true` from the `initChart()` pending path (OHLCVChart.tsx:529 in old code — find equivalent in new chart hook).
- `SessionStatsStrip.tsx` (22px): `O: {open} H: {high} L: {low} C: {close} Vol: {volume}` — all `font-mono tabular-nums text-[10px]`, colored H in `text-positive`, L in `text-negative`

**OHLCVChart refactor notes**:
- Keep the `useChartSeries.ts` hook (already extracted)
- `OHLCVChart.tsx` MUST only manage: chart container ref, resize observer, and render of `<TimeframeToolbar>` + `<ChartToolbar>` + chart canvas div. Max 180 lines.
- Drawing tools (DrawingPalette, DrawingCanvas) are excluded from this redesign (deferred)
- Compare overlay logic stays in `useChartSeries` (no UI for compare in this version — remove ComparePopover)

#### 6.7.2 Right Panel — MetricsTable (40% width)

**File**: `components/instrument/quote/MetricsTable.tsx`
**Style**: `w-[40%] flex-shrink-0 border-l border-border overflow-y-auto`
**Header**: `STATISTICS` (10px ALL CAPS, px-3 py-1.5, border-b border-border/50)

Each row is a `MetricRow` component: `flex items-center justify-between h-[22px] px-3`
- Label: `text-[10px] uppercase tracking-wide text-muted-foreground flex-1 truncate`
- Value: `text-[11px] font-mono tabular-nums` + color class

**Group separators**: A `MetricGroupDivider` component — `h-[1px] bg-border/30 mx-3 my-0.5`

**Complete MetricsTable field specification** (26 data rows + 5 dividers = 31 total rows):

| Row | Label | Value source | Field path | Color logic |
|-----|-------|-------------|------------|-------------|
| 1 | MARKET CAP | Fundamentals | `fundamentals.market_cap` | none |
| 2 | P/E | Fundamentals | `fundamentals.pe_ratio` | amber >30, red >50 |
| 3 | FWD P/E | Fundamentals | `fundamentals.forward_pe` | amber >25, red >40 |
| 4 | EPS TTM | FundamentalsSnapshot | `snapshot.eps_ttm` | positive/negative by sign |
| 5 | P/S | Fundamentals | `fundamentals.price_to_sales` | none |
| 6 | P/B | Fundamentals | `fundamentals.price_to_book` | none |
| 7 | EV/EBITDA | Fundamentals | `fundamentals.ev_to_ebitda` | none |
| — | [divider] | | | |
| 8 | GROSS MARGIN | Fundamentals | `fundamentals.gross_margin` | green >40%, amber 20–40% |
| 9 | OPER MARGIN | Fundamentals | `fundamentals.operating_margin` | green >20%, amber 10–20% |
| 10 | NET MARGIN | Fundamentals | `fundamentals.net_margin` | green >15%, amber 5–15%, red <0 |
| 11 | ROE | Fundamentals | `fundamentals.roe` | green >15%, red <0 |
| 12 | ROA | Fundamentals | `fundamentals.roa` | green >10%, red <0 |
| — | [divider] | | | |
| 13 | DEBT/EQUITY | Fundamentals | `fundamentals.debt_to_equity` | amber >1.5, red >3 |
| 14 | CURRENT RATIO | Fundamentals | `fundamentals.current_ratio` | red <1, amber 1–1.5 |
| — | [divider] | | | |
| 15 | DIV YIELD | Fundamentals | `fundamentals.dividend_yield` | green >3%, amber 1–3% |
| 16 | BETA | FundamentalsSnapshot | `snapshot.beta` | amber >1.5, red >2.5 |
| — | [divider] | | | |
| 17 | 52W HIGH | Fundamentals | `fundamentals.week_52_high` | none |
| 18 | 52W LOW | Fundamentals | `fundamentals.week_52_low` | none |
| 19 | [52W range bar] | computed | `(price − low) / (high − low)` | yellow fill `bg-primary` |
| — | [divider] | | | |
| 20 | AVG VOL (30D) | FundamentalsSnapshot | `snapshot.avg_volume_30d` | none |
| 21 | SHORT % | TechnicalsData | `technicals.short_percent` | amber >5%, red >10% |
| 22 | INST OWN | ShareStatisticsData | `shareStats.percent_institutions` | none |
| 23 | INSIDER OWN | ShareStatisticsData | `shareStats.percent_insiders` | none |
| — | [divider] | | | |
| 24 | MA 50 | TechnicalsData | `technicals["50_day_ma"]` | green if price > ma, red if below (arrow indicator) |
| 25 | MA 200 | TechnicalsData | `technicals["200_day_ma"]` | same |
| — | [divider] | | | |
| 26 | ANALYST | Fundamentals | `buy + hold + sell counts` | mini bar: green/amber/red segments |
| 27 | TARGET | Fundamentals | `fundamentals.analyst_target_price` | green if target > price |

Row 19 (range bar): full-width `h-[4px] bg-muted rounded-full` with `bg-primary` fill at computed position percent. Inline within a 22px MetricRow, replacing the value cell.

Row 26 (analyst): mini bar chart component — `flex gap-0.5` with 3 colored segments whose widths are proportional to buy/hold/sell counts. Below segments: `"28B · 10H · 2S"` in `text-[10px] font-mono`.

**Data fetching in QuoteTab**:
```typescript
const { data: bundle } = useInstrumentBundle(entityId)  // from page bundle
const { data: snapshot } = useFundamentalsSnapshot(instrumentId)  // 10min stale
const { data: shareStats } = useShareStatistics(instrumentId)  // 1hr stale
const { data: technicals } = useTechnicals(instrumentId)  // 5min stale
```
All 4 queries auto-deduped by TanStack Query if other components fetch the same key.

---

### 6.8 Tab 2: Financials

**File**: `components/instrument/financials/FinancialsTab.tsx`
**Layout**: `flex gap-0` full height

#### 6.8.1 Main Content (calc(100% - 280px))

**File**: `components/instrument/financials/FlatMetricsGrid.tsx`
**Style**: `flex-1 min-w-0 overflow-y-auto p-4`
**Structure**: A `<dl>` grid with `grid-cols-3 gap-x-6 gap-y-0`

Each metric cell (`MetricCell.tsx`):
```
<dt>  LABEL [10px, uppercase, muted]  </dt>
<dd>  VALUE [11px, mono, tabular-nums, colored]  </dd>
```
Height: 36px per cell (label 14px + value 22px with gap).

**Group separator**: Full-width `<div>` spanning 3 columns: `h-[1px] bg-border/30 col-span-3 my-3` + inline group label `text-[10px] uppercase tracking-widest text-muted-foreground/50`.

**Complete FlatMetricsGrid specification** (45 metrics across 8 groups):

**Group 1: VALUATION**
| Metric | Field | Source |
|--------|-------|--------|
| P/E Ratio | `fundamentals.pe_ratio` | Fundamentals |
| Forward P/E | `fundamentals.forward_pe` | Fundamentals |
| Price/Sales | `fundamentals.price_to_sales` | Fundamentals |
| Price/Book | `fundamentals.price_to_book` | Fundamentals |
| EV/EBITDA | `fundamentals.ev_to_ebitda` | Fundamentals |
| Market Cap | `fundamentals.market_cap` | Fundamentals |

**Group 2: PROFITABILITY**
| Metric | Field | Source |
|--------|-------|--------|
| Gross Margin | `fundamentals.gross_margin` | Fundamentals |
| Operating Margin | `fundamentals.operating_margin` | Fundamentals |
| Net Margin | `fundamentals.net_margin` | Fundamentals |
| ROE | `fundamentals.roe` | Fundamentals |
| ROA | `fundamentals.roa` | Fundamentals |
| FCF Margin | `snapshot.fcf_margin` | FundamentalsSnapshot |

**Group 3: GROWTH**
| Metric | Field | Source |
|--------|-------|--------|
| Revenue (YoY) | `fundamentals.revenue_growth_yoy` | Fundamentals |
| Earnings (YoY) | `fundamentals.earnings_growth_yoy` | Fundamentals |
| EPS TTM | `snapshot.eps_ttm` | FundamentalsSnapshot |

**Group 4: BALANCE SHEET**
| Metric | Field | Source |
|--------|-------|--------|
| Debt/Equity | `fundamentals.debt_to_equity` | Fundamentals |
| Current Ratio | `fundamentals.current_ratio` | Fundamentals |
| Quick Ratio | `fundamentals.quick_ratio` | Fundamentals |
| Interest Coverage | `snapshot.interest_coverage` | FundamentalsSnapshot |
| Net Debt/EBITDA | `snapshot.net_debt_to_ebitda` | FundamentalsSnapshot |

**Group 5: CASH FLOW**
| Metric | Field | Source |
|--------|-------|--------|
| Operating CF | `snapshot.operating_cash_flow` | FundamentalsSnapshot |
| CapEx | `snapshot.capex` | FundamentalsSnapshot |
| Free Cash Flow | `snapshot.free_cash_flow` | FundamentalsSnapshot |

**Group 6: DIVIDENDS**
| Metric | Field | Source |
|--------|-------|--------|
| Dividend Yield | `fundamentals.dividend_yield` | Fundamentals |
| Payout Ratio | `fundamentals.payout_ratio` | Fundamentals |

**Group 7: OWNERSHIP**
| Metric | Field | Source |
|--------|-------|--------|
| Shares Outstanding | `shareStats.shares_outstanding` | ShareStatisticsData |
| Float | `shareStats.shares_float` | ShareStatisticsData |
| Institutional Own% | `shareStats.percent_institutions` | ShareStatisticsData |
| Insider Own% | `shareStats.percent_insiders` | ShareStatisticsData |
| Short % | `technicals.short_percent` | TechnicalsData |
| Short Ratio | `technicals.short_ratio` | TechnicalsData |

**Group 8: TECHNICALS**
| Metric | Field | Source |
|--------|-------|--------|
| Beta | `snapshot.beta` | FundamentalsSnapshot |
| 52W High | `fundamentals.week_52_high` | Fundamentals |
| 52W Low | `fundamentals.week_52_low` | Fundamentals |
| MA 50 | `technicals["50_day_ma"]` | TechnicalsData |
| MA 200 | `technicals["200_day_ma"]` | TechnicalsData |
| RSI(14) | computed client-side | OHLCV bars (1D, last 14 periods) |
| ATR(14) | computed client-side | OHLCV bars (1D, last 14 periods) |

**Client-side RSI/ATR computation** (`lib/technicals.ts` — new utility file):
```typescript
// RSI(14): 100 - (100 / (1 + avgGain/avgLoss)) over last 14 periods
export function computeRSI(bars: OHLCVBar[], period = 14): number | null

// ATR(14): avg(max(H-L, |H-prevC|, |L-prevC|)) over last 14 periods
export function computeATR(bars: OHLCVBar[], period = 14): number | null
```
These computations use the 1D OHLCV bars already fetched for the chart. No additional API calls.

**Below the FlatMetricsGrid** (inside the same scrollable column):

`IncomeStatementTable.tsx` — 4-year annual table (`getIncomeStatement(instrumentId)`, staleTime: 24h):
- Columns: FY (year), Revenue, Gross Profit, EBIT, Net Income, EPS
- All values: `font-mono tabular-nums text-[11px]`, right-aligned
- Row height: 22px
- Column headers: 10px ALL CAPS

`EarningsBarChart.tsx` — EPS beat/miss history (`getEarningsHistory(instrumentId)`, staleTime: 24h):
- Compact bar chart: 6–8 bars, 80px height
- Each bar: actual EPS (solid), estimate EPS (outlined). Beat = `bg-positive`, miss = `bg-negative`
- X-axis labels: fiscal year short form (e.g., "FY23")

#### 6.8.2 Right Sidebar (280px, sticky)

**File**: `components/instrument/financials/AnalystSidebar.tsx`
**Style**: `w-[280px] flex-shrink-0 border-l border-border flex flex-col overflow-y-auto`

**Analyst Consensus section**:
- Header: `ANALYST CONSENSUS` (10px, px-3 py-1.5)
- Buy / Hold / Sell counts as stacked mini bar: `flex gap-0` with colored segments
- `"28 Buy · 10 Hold · 2 Sell"` text below in `text-[10px] font-mono`
- Target price: `$240.00` in `text-[13px] font-mono font-semibold`
- Target range: `$180.00 – $280.00` in `text-[10px] font-mono text-muted-foreground`
- Number of analysts: `"Based on 40 analysts"` in `text-[10px] text-muted-foreground`

**Data timestamp**:
- `text-[10px] text-muted-foreground px-3 py-2` bottom
- "Data as of {updated_at formatted as 'May 19, 2026'}"

**Data fetching in FinancialsTab**:
```typescript
const { data: fundamentals } = useFundamentals(instrumentId)    // 5min stale
const { data: snapshot }     = useFundamentalsSnapshot(instrumentId) // 10min stale
const { data: shareStats }   = useShareStatistics(instrumentId) // 1hr stale
const { data: technicals }   = useTechnicals(instrumentId)      // 5min stale
const { data: incomeStmt }   = useIncomeStatement(instrumentId) // 24hr stale
const { data: earningsHistory } = useEarningsHistory(instrumentId)  // 24hr stale
const ohlcvBars              = useOHLCVBars(instrumentId, "1D")  // from cache, for RSI/ATR
```

---

### 6.9 Tab 3: Intelligence

**File**: `components/instrument/intelligence/IntelligenceTab.tsx`
**Layout**: `flex h-full` — 3 fixed columns with dividers

#### 6.9.1 Left Column: News (30% width)

**File**: `components/instrument/intelligence/news/NewsColumn.tsx`
**Style**: `w-[30%] flex flex-col border-r border-border`

**Filter bar** (32px): `NewsFilters.tsx`
- Time filter tabs: ALL | TODAY | 3D | 1W — underline tab style, `text-[10px] uppercase`
- Sentiment toggle: POS / NEU / NEG pill group (same style as tab, right-aligned)

**Article list**: `overflow-y-auto flex-1`
- Each article: `CompactArticleRow.tsx` (28px height)
  - `[sentiment dot 6px circle] [relative time 10px mono] [source 10px truncate] [headline 11px truncate flex-1] [impact 10px mono text-muted]`
  - Sentiment dot: `rounded-full w-1.5 h-1.5 flex-shrink-0` colored per FR-10
  - Hover: `bg-muted/20 cursor-pointer`
  - Click: opens article URL in new tab

**Infinite scroll**: On scroll to bottom, load next page (offset += 20). Loading state: 3 skeleton rows.

**Empty state**: `text-[11px] text-muted-foreground text-center py-8` "No articles for this entity."

**Data fetching**:
```typescript
const { data: newsPages, fetchNextPage } = useEntityNewsInfinite(entityId, filters)
```
New hook `useEntityNewsInfinite` — wraps `GET /v1/news/entity/{entityId}` with `useInfiniteQuery`. Returns pages of 20 articles. Filters: `time_range: "all" | "day" | "3d" | "1w"`, `sentiment: string | null`.

#### 6.9.2 Center Column: AI Brief + Graph (45% width)

**File**: `components/instrument/intelligence/graph/GraphColumn.tsx`
**Style**: `flex-1 min-w-0 flex flex-col`

**AI Brief card** (always expanded on this tab):
- Background: `bg-card border border-border/50 rounded-[2px] mx-3 mt-3 p-3`
- Header row: `INTELLIGENCE BRIEF` (10px) + health score badge inline right (`rounded-[2px] text-[10px] font-mono px-1.5 py-0.5`)
  - Health score color: green >70, amber 40–70, red <40
- Brief text: `text-[11px] leading-[1.6] text-foreground/80` (plain text, no markdown)
- Timestamp: `text-[10px] text-muted-foreground mt-1`

**Graph toolbar** (`GraphToolbar.tsx`, 28px):
- `DEPTH` label + slider 1–3 (shadcn Slider)
- `TYPE` label + multi-select dropdown for relationship types (shadcn DropdownMenu with checkboxes)
- Fullscreen button (right-aligned)

**EntityGraph** (fills remaining height):
- **Bug fixes required** (from memory project_age_cypher_fix_2026_05_11.md and project_graph_bugs_2026_05_11.md):
  - Fix depth=3 504 timeout: implement query timeout of 2000ms on S9; render partial results if timeout
  - Fix black void: ensure graph container has `h-full w-full` (no fixed height)
  - Fix node panel: extract and pass edge fields through S9 → frontend (ensure `relation_summary` is forwarded)
- Depth slider change triggers refetch with new depth param
- Empty state: `text-[11px] text-muted-foreground text-center` "No entity relationships found."
- Loading state: spinner centered in graph area

**Data fetching**:
```typescript
const { data: brief } = useInstrumentBrief(entityId)           // 10min stale
const { data: intelligence } = useEntityIntelligence(entityId) // 5min stale
const { data: graph } = useEntityGraph(entityId, { depth, typeFilters }) // 5min stale
```

#### 6.9.3 Right Column: Context Panel (25% width)

**File**: `components/instrument/intelligence/context/ContextPanel.tsx`
**Style**: `w-[25%] flex-shrink-0 border-l border-border overflow-y-auto`

**State**: driven by `selectedNodeId: string | null` (local state in `IntelligenceTab`, passed down to graph and context panel)

**When no node selected — Entity Overview**:
- Header: `ENTITY OVERVIEW` (10px)
- Entity type badge: `text-[10px] bg-muted/40 px-1.5 rounded-[2px]` (e.g., "COMPANY")
- Description: `text-[11px] leading-[1.5] text-foreground/70` (first 3 sentences from intelligence.narrative)
- Health score row: `text-[10px] text-muted-foreground` "HEALTH" + score colored
- Evidence quality: 3 rows (High / Medium / Low) as labeled progress bars, `h-[4px]`
- Contradictions count: if > 0, show `ContradictionCard.tsx` for the most recent 2

**When node selected — `NodeDetailCard.tsx`**:
- Back button (← to deselect node)
- Entity name: `text-[12px] font-medium`
- Entity type badge
- Description: `text-[11px] leading-[1.5] text-foreground/70`
- Confidence: `text-[10px] font-mono` "CONFIDENCE 84%"
- Relations list: `RelationsList.tsx`
  - Each relation: `flex items-start gap-2 py-1.5 border-b border-border/30`
    - Relation type badge: `text-[9px] uppercase bg-muted/30 px-1 rounded-[2px]`
    - Target name: `text-[11px]`
    - Evidence snippet: `text-[10px] text-muted-foreground italic truncate-2-lines`

**Contradictions** (always at bottom, when count > 0):
- `ContradictionCard.tsx`: `bg-negative/5 border border-negative/20 rounded-[2px] p-2 text-[10px]`
- Shows claim A vs claim B + source attribution

---

### 6.10 Component Architecture — Full File Tree

```
apps/worldview-web/
├── app/(app)/instruments/[entityId]/
│   ├── layout.tsx                               KEEP (SSR metadata)
│   └── page.tsx                                 SIMPLIFY (→ <InstrumentPageClient>)
│
└── components/instrument/
    ├── InstrumentPageClient.tsx                 NEW: client root, bundle fetch, cache seeding
    │
    ├── header/
    │   ├── InstrumentHeader.tsx                 NEW: 36px sticky header
    │   ├── WeekRangeMini.tsx                    NEW: 60px range bar for header
    │   └── LiveQuoteBadge.tsx                   KEEP
    │
    ├── brief/
    │   └── AiBriefBanner.tsx                    NEW: replaces InstrumentAISubheader
    │
    ├── tabs/
    │   └── InstrumentTabs.tsx                   NEW: 3-tab bar with mnemonic keys
    │
    ├── quote/                                   Tab 1
    │   ├── QuoteTab.tsx                         NEW: orchestrator (max 250 lines)
    │   ├── chart/
    │   │   ├── OHLCVChart.tsx                   REFACTOR: reduce to <180 lines
    │   │   ├── ChartToolbar.tsx                 KEEP (minor cleanup)
    │   │   ├── TimeframeToolbar.tsx             KEEP
    │   │   ├── SessionStatsStrip.tsx            REFACTOR: enforce 22px density
    │   │   └── useChartSeries.ts               KEEP (fix scroll-to-1985 bug)
    │   └── metrics/
    │       ├── MetricsTable.tsx                 NEW: 26-row dense table
    │       ├── MetricRow.tsx                    NEW: single 22px row
    │       ├── MetricGroupDivider.tsx           NEW: 1px divider
    │       ├── WeekRangeBar.tsx                 NEW: inline range bar (row 19)
    │       └── AnalystMiniBar.tsx               NEW: buy/hold/sell segment bar (row 26)
    │
    ├── financials/                              Tab 2
    │   ├── FinancialsTab.tsx                    NEW: orchestrator (max 250 lines)
    │   ├── FlatMetricsGrid.tsx                  NEW: 45-metric 3-col grid
    │   ├── MetricCell.tsx                       NEW: single metric cell (label + value)
    │   ├── IncomeStatementTable.tsx             NEW: 4-year FY table
    │   ├── EarningsBarChart.tsx                 NEW: EPS beat/miss chart
    │   └── AnalystSidebar.tsx                   NEW: right sidebar (consensus + target)
    │
    ├── intelligence/                            Tab 3
    │   ├── IntelligenceTab.tsx                  NEW: orchestrator, 3-col layout
    │   ├── news/
    │   │   ├── NewsColumn.tsx                   NEW: left column container
    │   │   ├── NewsFilters.tsx                  NEW: time + sentiment filter bar
    │   │   └── CompactArticleRow.tsx            NEW: 28px single article row
    │   ├── graph/
    │   │   ├── GraphColumn.tsx                  NEW: center column (brief + toolbar + graph)
    │   │   ├── GraphToolbar.tsx                 NEW: depth slider + type filter
    │   │   └── EntityGraph.tsx                  REFACTOR: fix depth timeout + black void + node panel
    │   └── context/
    │       ├── ContextPanel.tsx                 NEW: right column (adapts to selection)
    │       ├── NodeDetailCard.tsx               NEW: selected node details
    │       ├── RelationsList.tsx                NEW: outgoing/incoming relations
    │       └── ContradictionCard.tsx            KEEP (minor polish)
    │
    ├── shared/
    │   ├── MetricLabel.tsx                      NEW: 10px uppercase muted label
    │   ├── MetricValue.tsx                      NEW: 11px mono value with color prop
    │   ├── SectionDivider.tsx                   NEW: 1px divider with optional label
    │   └── DataTimestamp.tsx                    NEW: "as of {date}" footer
    │
    └── hooks/
        ├── useInstrumentBundle.ts               NEW: page bundle query
        ├── useMetricsTableData.ts               NEW: aggregates snapshot+shareStats+technicals
        ├── useFinancialsTabData.ts              NEW: aggregates all Financials tab sources
        ├── useEntityNewsInfinite.ts             NEW: infinite query for news column
        └── useChartTechnicals.ts               NEW: RSI/ATR computation from OHLCV bars

lib/
└── technicals.ts                               NEW: computeRSI(), computeATR() pure functions

```

**Files to DELETE** (all from `components/instrument/`):
- `InstrumentAISubheader.tsx`
- `AnalystRail.tsx`
- `PerformanceBar.tsx`
- `OverviewLayout.tsx`
- `OverviewSidebar.tsx`
- `FundamentalsTab.tsx`
- `FundamentalsMetricsGrid.tsx`
- `InstrumentKeyMetrics.tsx`
- `NewsTab.tsx`
- `IntelligenceTab.tsx` (old version)
- `InstrumentTopNews.tsx`
- `OverviewInsiderStrip.tsx`
- `FundamentalSparkline.tsx`
- `EntityGraphPanel.tsx` (replaced by `EntityGraph.tsx` in new structure)
- `InsiderTransactionsTable.tsx`
- `AnalystConsensusStrip.tsx`
- `RevenueTrendSparklines.tsx`
- `IncomeStatementFY.tsx`
- `AnalystTargetSparkline.tsx`
- `MarketPositionPanel.tsx`
- `PeerComparisonPanel.tsx`
- `ShortInterestRow.tsx`
- `FundamentalsTopNews.tsx`
- `InstrumentBriefSection.tsx`
- `IntelligenceSummarySection.tsx`
- `IntelligenceFilters.tsx`
- `GraphDetailSidebar.tsx`
- `TechnicalSnapshot.tsx`
- `OwnershipSnapshotPanel.tsx`
- `SplitsDividendsPanel.tsx`
- `EarningsHistoryChart.tsx` (replaced by `EarningsBarChart.tsx`)
- `52WeekRangeBar.tsx` (replaced by `WeekRangeBar.tsx` + `WeekRangeMini.tsx`)
- `CompactInstrumentHeader.tsx` (replaced by `InstrumentHeader.tsx`)
- `DrawingPalette.tsx` (deferred)
- `DrawingCanvas.tsx` (deferred)
- `CrosshairHUD.tsx` (deferred)

---

### 6.11 Visual Design Specification

**Typography scale (ADR-F-15)**:

| Element | Size | Weight | Family | Class |
|---------|------|--------|--------|-------|
| Ticker | 13px | 600 | Mono | `text-[13px] font-semibold font-mono tracking-wide` |
| Price (header) | 13px | 600 | Mono | `text-[13px] font-semibold font-mono tabular-nums` |
| Section label | 10px | 500 | Sans | `text-[10px] font-medium uppercase tracking-widest text-muted-foreground` |
| Metric label | 10px | 400 | Sans | `text-[10px] uppercase tracking-wide text-muted-foreground` |
| Metric value | 11px | 400 | Mono | `text-[11px] font-mono tabular-nums` |
| Body text (brief) | 11px | 400 | Sans | `text-[11px] leading-[1.5]` |
| Article headline | 11px | 400 | Sans | `text-[11px] truncate` |
| Time/source | 10px | 400 | Mono | `text-[10px] font-mono text-muted-foreground` |
| Table header | 10px | 500 | Sans | `text-[10px] uppercase tracking-wide text-muted-foreground` |
| Table cell | 11px | 400 | Mono | `text-[11px] font-mono tabular-nums` |

**Layout constants**:
- Right sidebar width: `280px` (Financials tab, Quote tab metrics)
- Chart minimum height: `240px`
- Row height (data rows): `22px` (`h-[22px]`)
- Row height (article rows): `28px` (`h-[28px]`)
- Panel header height: `28px` (`h-7`)
- Tab bar height: `32px` (`h-8`)
- Header height: `36px` (`h-9`)
- Brief banner height (collapsed): `24px`
- Border radius: `2px` (`rounded-[2px]`) for all badges, chips, cards
- Standard padding: `px-3` horizontal, `py-1.5` for headers

**Colors (Terminal Dark — unchanged)**:
- Background: `bg-background` (#09090B)
- Card: `bg-card` (#111113)
- Muted: `bg-muted` (#18181B)
- Border: `border-border` (#27272A)
- Primary text: `text-foreground` (#E4E4E7)
- Muted text: `text-muted-foreground` (#71717A)
- Positive: `text-positive` / `bg-positive` (#26A69A)
- Negative: `text-negative` / `bg-negative` (#EF5350)
- Primary accent: `text-primary` / `bg-primary` (#FFD60A)

---

### 6.12 API Endpoints Used

All existing S9 endpoints. Zero new backend work required.

| Endpoint | Used By | staleTime | Notes |
|----------|---------|-----------|-------|
| `GET /v1/instruments/{id}/page-bundle` | Page entry | 5min | Primes 5 child caches |
| `GET /v1/ohlcv/{id}?timeframe=1D` | OHLCVChart | 1min | Also provides OHLCV for RSI/ATR |
| `GET /v1/quotes/{id}` | LiveQuoteBadge | 30s | Price freshness check |
| `GET /v1/fundamentals/{id}` | FinancialsTab | 5min | Main fundamentals (FlatMetricsGrid) |
| `GET /v1/fundamentals/{id}/snapshot` | QuoteTab + FinancialsTab | 10min | EPS TTM, Beta, FCF, interest coverage |
| `GET /v1/fundamentals/{id}/technicals` | QuoteTab + FinancialsTab | 5min | MA50, MA200, short %, short ratio |
| `GET /v1/fundamentals/{id}/share-statistics` | QuoteTab + FinancialsTab | 1hr | Float, shares outstanding, own% |
| `GET /v1/fundamentals/{id}/income-statement` | FinancialsTab | 24hr | 4-year income statement table |
| `GET /v1/fundamentals/{id}/earnings-annual-trend` | FinancialsTab | 24hr | EPS beat/miss history |
| `GET /v1/news/entity/{entityId}?limit=20&offset=N` | IntelligenceTab | 5min | Paginated entity news |
| `GET /v1/entities/{entityId}/graph?depth=N` | IntelligenceTab | 5min | Entity graph nodes + edges |
| `GET /v1/entities/{entityId}/intelligence` | IntelligenceTab | 5min | Health score, narrative |
| `GET /v1/entities/{entityId}/contradictions` | IntelligenceTab | 5min | Contradiction cards |
| `GET /v1/briefings/instrument/{entityId}` | AiBriefBanner + IntelligenceTab | 10min | AI brief text |

---

## 7. Architecture Compliance Gate

| Rule | Applies? | Design Decision | Status |
|------|----------|----------------|--------|
| R7 — No cross-service DB | YES | Frontend talks only to S9 via lib/api | PASS |
| R14 — Frontend → S9 only | YES | All API calls via `lib/api/*` → S9 at `/api/*` | PASS |
| F-ADR-15 — IBM Plex Mono + tabular-nums on all numbers | YES | Enforced in MetricRow, MetricCell, MetricValue, CompactArticleRow, all tables | PASS |
| R11 — UTC timestamps | YES | All `updated_at` / `timestamp` fields formatted via `formatRelativeTime` utility | PASS |
| shadcn/ui-only component policy | YES | No new component library imports | PASS |
| Single-responsibility components (≤200 lines) | YES | Enforced by component tree design | PASS (enforced in Wave implementations) |
| pnpm + exact versions | YES | No new dependencies; existing lockfile used | PASS |

---

## 8. Break-Surface Analysis

| Change | What Currently Exists | What Breaks | Migration Strategy |
|--------|----------------------|-------------|-------------------|
| Delete all `components/instrument/` files (except chart core) | 54 components | All instrument page rendering | Replace in implementation waves; page 404 acceptable during development |
| Keep `lib/api/instruments.ts` + `types/api.ts` | 26 API methods, full types | Nothing | No change |
| Delete `AnalystRail.tsx` | mod+/ hotkey binding in page.tsx | mod+/ does nothing | Remove hotkey binding from page |
| Delete `PerformanceBar.tsx` | 1D/5D/1M/3M/1Y chip row | No performance chips visible | Data moved into MetricsTable rows |
| Add `useEntityNewsInfinite` hook | `useEntityNews` (non-infinite) | Old hook still exists (no conflict) | New hook only, old one removed when NewsTab deleted |
| Rewrite `EntityGraph.tsx` | Graph has depth timeout + black void bugs | Old bugs fixed, any workarounds removed | Replace entirely in Wave D |
| Delete E2E Playwright tests for instrument route | Existing tests | Tests fail | Rewrite in Wave E |

---

## 9. Security Analysis

No new security surface. This is a frontend-only redesign.

- All API calls authenticated via existing JWT in Authorization header (from `useAuth`)
- No new user inputs beyond existing (search, filters — already sanitized at S9)
- No eval(), dangerouslySetInnerHTML, or dynamic script injection in new components
- Brief text displayed as plain text (not markdown rendered) — XSS not possible

---

## 10. Failure Modes

| Failure | Impact | Handling |
|---------|--------|----------|
| Bundle endpoint 503 | Page can't load | Show error state with retry button |
| Fundamentals null | MetricsTable shows "—" for all rows | Graceful; "—" in `font-mono` |
| FundamentalsSnapshot null | EPS TTM, Beta, FCF rows show "—" | Graceful |
| Entity graph 504 timeout (depth=3) | Graph doesn't render | Show partial graph if depth=1 or 2 succeeds; "Network timeout — try lower depth" message |
| Brief endpoint 404 | AiBriefBanner hidden | Banner omitted entirely (no error shown) |
| News empty | NewsColumn shows empty state | "No articles for this entity." centered |
| S9 drops edge `relation_summary` | Node detail panel shows "No summary available" | Graceful; fix in EntityGraph refactor (pass through from S9) |

---

## 11. Test Strategy

### Unit Tests

| Test | What It Verifies | Priority | File |
|------|-----------------|----------|------|
| `test_metric_row_formats_null_as_dash` | MetricRow renders "—" for null values | HIGH | `MetricRow.test.tsx` |
| `test_metric_row_applies_positive_color` | Positive change → `text-positive` class | HIGH | `MetricRow.test.tsx` |
| `test_week_range_bar_position_clamps_to_0_100` | Price < low → 0%; price > high → 100% | HIGH | `WeekRangeBar.test.tsx` |
| `test_compute_rsi_14_periods` | RSI with known bars produces correct value | HIGH | `technicals.test.ts` |
| `test_compute_atr_14_periods` | ATR with known bars produces correct value | HIGH | `technicals.test.ts` |
| `test_ai_brief_banner_hides_when_null` | Banner not rendered when brief is null/404 | MEDIUM | `AiBriefBanner.test.tsx` |
| `test_analyst_mini_bar_proportional_segments` | 28B/10H/2S → correct segment widths | MEDIUM | `AnalystMiniBar.test.tsx` |
| `test_compact_article_row_sentiment_dot_color` | Positive article → green dot | MEDIUM | `CompactArticleRow.test.tsx` |
| `test_flat_metrics_grid_renders_45_metrics` | FlatMetricsGrid renders all expected labels | MEDIUM | `FlatMetricsGrid.test.tsx` |
| `test_metrics_table_renders_26_rows` | MetricsTable has correct row count | MEDIUM | `MetricsTable.test.tsx` |

### Integration Tests (Playwright E2E)

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_instrument_page_loads_chart_on_first_visit` | Chart visible without scrolling; not at 1985 | HIGH |
| `test_instrument_header_shows_live_price` | Header price matches /v1/quotes response | HIGH |
| `test_quote_tab_metrics_table_not_empty` | At least 20 metric rows have non-dash values | HIGH |
| `test_financials_tab_flat_grid_shows_groups` | All 8 group labels visible after scroll | MEDIUM |
| `test_intelligence_tab_news_column_loads_articles` | ≥ 1 article row visible | MEDIUM |
| `test_intelligence_tab_graph_renders` | Cytoscape canvas visible, nodes > 0 | MEDIUM |
| `test_ai_brief_banner_collapses_and_expands` | Click expands, click again collapses | MEDIUM |
| `test_tab_switching_keyboard_mnemonics` | Press F → Financials tab active | LOW |

---

## 12. Migration Strategy

### Cutover approach
This is a direct replacement, not a parallel-route migration. During implementation waves, the page will be in an intermediate broken state. Development MUST happen on the `fix/instrument-page-redesign` branch.

### Wave sequence (see PLAN-0090 for details)
- **Wave A** — Shared infrastructure: `shared/` components, `lib/technicals.ts`, `hooks/`, header + banner + tab bar
- **Wave B** — Quote tab: MetricsTable + chart refactor + SessionStatsStrip
- **Wave C** — Financials tab: FlatMetricsGrid + IncomeStatementTable + EarningsBarChart + AnalystSidebar
- **Wave D** — Intelligence tab: EntityGraph (bug fixes) + NewsColumn + ContextPanel + GraphColumn
- **Wave E** — Cleanup + testing: delete deprecated files, rewrite E2E tests, full QA pass

### E2E test status during development
Existing Playwright tests for `/instruments/[entityId]` will fail from Wave A onward. This is expected. Do not attempt to maintain old tests — write new tests in Wave E only.

---

## 13. Open Questions

| # | Question | Classification | Default if unresolved |
|---|----------|---------------|----------------------|
| OQ-1 | Does S9 `/v1/entities/{entityId}/graph` forward `relation_summary` on edges, or does it get dropped in the proxy? Need to inspect proxy.py response handling. | DEFERRED | Show "No summary available" gracefully |
| OQ-2 | Does `GET /v1/fundamentals/{id}/technicals` return `short_percent` > 0 in practice for US equities? Or is this always null? | DEFERRED | Show "—" if null |
| OQ-3 | `AnalystConsensusData` has `target_price`, `target_price_high`, `target_price_low`, `target_price_median`. Are these always populated when `analyst_rating` is not null? | DEFERRED | Show median target only, "—" if null |
| OQ-4 | S9 entity graph: when `depth=3` causes 504 timeout, does S9 return a 504 error or a partial response? Understanding this determines whether we can show partial graph. | DEFERRED | Treat 504 as empty graph, suggest reducing depth |

No BLOCKING open questions. Implementation can proceed.

---

## 14. Estimation

| Wave | Scope | Estimated Effort |
|------|-------|-----------------|
| Wave A | Shared components + infrastructure | 1–2 days |
| Wave B | Quote tab (chart refactor + MetricsTable) | 2–3 days |
| Wave C | Financials tab (FlatMetricsGrid + sidebar) | 2–3 days |
| Wave D | Intelligence tab (graph fixes + news column + context) | 3–4 days |
| Wave E | Cleanup + E2E tests | 1–2 days |
| **Total** | | **9–14 days** |

---

## 15. Compounding Updates

**BUG_PATTERNS.md updates required**:
- BP-NEW: Entity graph `relation_summary` field dropped at S9 proxy layer — check proxy pass-through for nested object fields in graph edge responses
- BP-NEW: `short_percent` from EODHD TechnicalsData may be null for non-US equities and newly-listed stocks; always guard before display

**DESIGN_SYSTEM.md updates required**:
- Add: `AiBriefBanner` component to component catalogue
- Add: `CompactArticleRow` (28px) to component catalogue
- Update: density specifications — `MetricRow` (22px) and `CompactArticleRow` (28px) as the two canonical data row heights
- Add: `MetricsTable` as canonical right-sidebar data pattern (replaces 9-section card pattern)

**PLAN-0071 status**: Suspend Phase 6.5+ immediately. This PRD supersedes the density sprint for the instrument page.
