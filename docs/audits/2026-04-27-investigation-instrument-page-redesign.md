# Investigation Report: Instrument Detail Page & Fundamentals Redesign

**Date**: 2026-04-27
**Investigator**: Claude (investigation skill)
**Severity**: MEDIUM (UX quality gap, not a functional bug)
**Status**: Root cause identified — missing data surfacing + layout issues

---

## 1. Issue Summary

The instrument detail page (Overview + Fundamentals tabs) falls significantly below the quality standard of professional financial platforms (Bloomberg Terminal, TradingView, Yahoo Finance, Koyfin). Specific problems: top bar value overflow and irrelevant data (VOL N/A, stale UTC timestamps), chart lacks interactive tools, fundamentals tab is flat/monochrome with no trend visualisation, and critical data categories (insider transactions, institutional holdings, earnings estimates, peer comparison, technical indicators) are absent from the UI despite some being available in the backend.

---

## 2. Evidence Collected

| Evidence | Source | Key Finding |
|----------|--------|-------------|
| Competitor feature matrix | Bloomberg, TradingView, Yahoo, Finviz, Koyfin, Morningstar, Seeking Alpha, Simply Wall St, TastyTrade | 7/10 show financial statements; 6/10 show earnings estimates, ownership, price targets |
| S3 Market Data endpoints | `services/market-data/src/market_data/api/routers/` | **18 fundamentals section endpoints** exist — only the flat summary is proxied through S9 |
| S9 proxy routes | `services/api-gateway/src/api_gateway/routes/proxy.py` | 6 section endpoints NOT proxied: technicals-snapshot, share-statistics, splits-dividends, earnings-trend, earnings-annual-trend, outstanding-shares |
| Frontend Fundamentals type | `apps/worldview-web/types/api.ts:112` | Only 22 fields — no technicals, no insider data, no earnings history, no cash flow details |
| Fundamentals timeseries | `GET /v1/fundamentals/timeseries` | **Exists and works** but frontend never calls it — biggest missed opportunity |
| Frontend dashboard audit | All route files in `apps/worldview-web/app/(app)/` | 10 pages built; Earnings Calendar is placeholder; AI Signals component exists but never rendered |
| Entity graph edges | S7 `GraphEdge.label` | `COMPETES_WITH` relationship type exists — can power competitor discovery |

---

## 3. Gap Analysis: What Competitors Have That We Don't

### HIGH PRIORITY (most platforms have it, users expect it)

| # | Gap | Platforms | Backend Data Available? | Effort |
|---|-----|-----------|------------------------|--------|
| G-1 | **Financial statements** (income, balance sheet, cash flow — multi-year tabular) | Bloomberg, TradingView, Yahoo, Koyfin, Seeking Alpha, Simply Wall St, Morningstar | YES — S3 has `/fundamentals/{id}/income-statement`, `/balance-sheet`, `/cash-flow` | S9 proxy + frontend component |
| G-2 | **Earnings estimates & EPS history** (actual vs estimate, surprise %) | Bloomberg, TradingView, Yahoo, Koyfin, Seeking Alpha, Morningstar | PARTIAL — S3 has `/fundamentals/{id}/earnings` and `/earnings-trend` | S9 proxy + chart component |
| G-3 | **Institutional & insider ownership breakdown** | Bloomberg, Yahoo, Finviz, Koyfin, Seeking Alpha, Simply Wall St, Morningstar | YES — S3 has `/fundamentals/{id}/institutional-holders`, `/fund-holders`, `/insider-transactions-snapshot` | S9 proxy + frontend component |
| G-4 | **Analyst price targets** (range visualisation + history) | Bloomberg, TradingView, Koyfin, Seeking Alpha, Simply Wall St, Morningstar | PARTIAL — S3 has `/fundamentals/{id}/analyst-consensus` (proxied in composite) | Frontend component |
| G-5 | **Peer/comparable company table** (side-by-side metrics) | Bloomberg, Finviz, Koyfin, Seeking Alpha, Morningstar | YES — `POST /v1/fundamentals/screen` with sector filter + `COMPETES_WITH` edges from S7 | Frontend composition |
| G-6 | **Fundamentals timeseries charts** (P/E, revenue, margins over time) | TradingView, Koyfin, Morningstar, Simply Wall St | YES — `GET /v1/fundamentals/timeseries` already proxied and working | **Frontend-only** — just add gateway method + components |
| G-7 | **Technical indicators summary** (Beta, SMA 20/50/200, RSI, buy/sell gauge) | TradingView, Finviz | PARTIAL — S3 has `/fundamentals/{id}/technicals-snapshot` (NOT proxied) | S9 proxy + component |

### MEDIUM PRIORITY (differentiating features)

| # | Gap | Platforms | Notes |
|---|-----|-----------|-------|
| G-8 | **Dividend history chart & yield timeline** | Koyfin, Seeking Alpha, Simply Wall St, Morningstar | S3 has `/splits-dividends` (not proxied) |
| G-9 | **Revenue breakdown by segment/geography** | Bloomberg, Koyfin, Simply Wall St | EODHD Revenue_Segment field doesn't exist (PRD-0018 confirmed). Would need alternate data source. |
| G-10 | **ESG / Sustainability scores** | Yahoo, Morningstar, Aladdin | No data source. Increasingly expected by institutional users. |
| G-11 | **SEC filings browser** | Yahoo, Koyfin, Seeking Alpha, Morningstar | S4 ingests news but not SEC filings directly. Low effort if EDGAR RSS added. |
| G-12 | **Factor grades** (value/growth/momentum/quality composite scores) | Seeking Alpha (Quant), Simply Wall St (Snowflake) | Computable from existing fundamentals data — no new data needed |
| G-13 | **Intrinsic value / DCF estimate** | Morningstar (Fair Value), Simply Wall St (waterfall) | Computable from cash flow + growth projections. Strong differentiator. |

### LOW PRIORITY (nice to have)

| # | Gap | Notes |
|---|-----|-------|
| G-14 | Options chain | Requires new data source (not in EODHD) |
| G-15 | Social/community sentiment | Partially covered by AI brief + contradiction detection |
| G-16 | Credit ratings | Relevant for fixed income; low priority for equity focus |
| G-17 | Risk metrics (VaR, factor decomposition) | Institutional-grade; beyond thesis scope |

---

## 4. Existing Data Not Surfaced (Backend → Frontend Gap)

These S3 section endpoints exist but are **NOT proxied through S9**:

| S3 Endpoint | Data Available | S9 Status |
|-------------|----------------|-----------|
| `GET /api/v1/fundamentals/{id}/technicals-snapshot` | Beta, SMA20/50/200, RSI, 52W range, avg volume | **NOT PROXIED** |
| `GET /api/v1/fundamentals/{id}/share-statistics` | Shares outstanding, float, short interest, % held by insiders/institutions | **NOT PROXIED** |
| `GET /api/v1/fundamentals/{id}/splits-dividends` | Dividend history (dates, amounts, frequency), stock splits | **NOT PROXIED** |
| `GET /api/v1/fundamentals/{id}/earnings-trend` | Future EPS estimates by quarter/year | **NOT PROXIED** |
| `GET /api/v1/fundamentals/{id}/earnings-annual-trend` | Annual earnings projections | **NOT PROXIED** |
| `GET /api/v1/fundamentals/{id}/outstanding-shares` | Historical shares outstanding | **NOT PROXIED** |
| `GET /api/v1/fundamentals/metrics/{id}` | Available metric names for timeseries queries | **NOT PROXIED** |

These are **already proxied** (via composite `/v1/fundamentals/{id}`) but the frontend `Fundamentals` type doesn't include their fields:

| S3 Section | Data Available | Frontend Status |
|------------|----------------|-----------------|
| `institutional-holders` | Top holders, % ownership | **Type missing, not displayed** |
| `fund-holders` | Top fund holders, % ownership | **Type missing, not displayed** |
| `insider-transactions-snapshot` | Recent insider buys/sells | **Type missing, not displayed** |
| `analyst-consensus` | Buy/hold/sell counts, price targets | **Placeholder component, no data** |
| `earnings` | Historical EPS, actual vs estimate | **Type missing, not displayed** |

---

## 5. Specific UI Issues

### 5.1 Top Bar (CompactInstrumentHeader)

| Issue | Root Cause | Fix |
|-------|------------|-----|
| Numbers overflow bar width | No `truncate`/`overflow-hidden` on stat value spans | Add overflow protection + responsive truncation |
| "VOL N/A" always shows | `volume` field not in `CompanyOverview` response | Replace with useful metric (Daily Return % or Div Yield) |
| "00:00:00 UTC" timestamp | `LiveQuoteBadge` renders `updatedAt` even when stale/midnight | Suppress timestamp when market closed; show "Market Closed" badge instead |
| 52W range is just numbers | Raw `192.41–288.35` without visual context | Add `52WeekRangeBar` component (position indicator) |
| P/E not color-coded | Color logic exists in FundamentalsTab but not applied in header | Apply `getMetricClass()` to header stat values |

### 5.2 Overview Tab

| Issue | Root Cause | Fix |
|-------|------------|-----|
| Chart has no tools | `OHLCVChart.tsx` only renders timeframe pills | Add toolbar: volume bars, MA50/MA200 toggles, crosshair mode, fullscreen |
| Bottom 3-column grid is sparse | Each column gets ≈33% width for minimal content (6 metrics, 4 articles, small graph) | Switch to chart + right sidebar layout (Bloomberg pattern); expand metrics to 12+ rows |
| No fundamental mini-charts | Timeseries endpoint exists but frontend doesn't call it | Add 1-2 switchable sparkline panels in right sidebar using `getFundamentalsTimeseries()` |
| Key metrics only 6 items | Hard-coded 6 rows in `InstrumentKeyMetrics.tsx` | Expand to 12+ metrics including EPS, Beta, ROE, D/E, Avg Volume |

### 5.3 Fundamentals Tab

| Issue | Root Cause | Fix |
|-------|------------|-----|
| Flat, spreadsheet appearance | Sections use `border-b` dividers, no card elevation | Wrap each section in `bg-card border border-border rounded-sm p-3` |
| No trend charts | Frontend never calls `/v1/fundamentals/timeseries` | Add revenue/earnings bar chart (full width) + per-section sparklines |
| Revenue Trend shows "pending" | `RevenueTrendSparklines` is hardcoded placeholder | Wire to timeseries endpoint for revenue + EPS metrics |
| Analyst Consensus all "—" | Data may not be in the flat `Fundamentals` type; needs section-specific endpoint | Expand type or add dedicated endpoint call |
| No peer comparison | No component exists | Add right sidebar column with peer comparison table (screener endpoint + sector filter) |
| No visual 52W range | Just shows numbers (high, low, daily return) | Add `52WeekRangeBar` position indicator |
| Cash flow section all "—" | Fields (operating_cf, capex, fcf, fcf_margin) not in `Fundamentals` type | Expand type to include cash flow fields from S3 response |
| No technical snapshot | Component listed in DESIGN_SYSTEM.md but never built | Build `TechnicalSnapshot` component; proxy `/technicals-snapshot` through S9 |

---

## 6. Proposed Architecture: Instrument Page v2

### Overview Tab — New Layout

```
┌────────────────────────────────────────┬────────────────────────┐
│ CHART TOOLBAR                          │ KEY METRICS (12+ rows) │
│ [5M][1H][1D][1W][1M] [Vol][MA50][⛶]  │ Mkt Cap  $4.02T       │
├────────────────────────────────────────┤ P/E      34.62x       │
│                                        │ Fwd P/E  31.2x        │
│ OHLCV CANDLESTICK CHART               │ EPS      $6.42        │
│ (280px + 60px volume subplot)          │ Div Yield 0.44%       │
│                                        │ Beta     1.21         │
│                                        │ ROE      156.1%       │
├────────────────────────────────────────┤ D/E      6.12         │
│ SESSION STATS: O H L V VWAP           │ 52W [===●======]      │
│                                        │ Avg Vol  62.3M        │
│                                        │ Sector   Technology   │
│                                        ├────────────────────────┤
│                                        │ MINI CHART (switchable)│
│                                        │ [P/E ▾] timeseries    │
│                                        │ ~~sparkline~~~~~~~~~  │
│                                        ├────────────────────────┤
│                                        │ MINI CHART 2           │
│                                        │ [Revenue ▾] trend     │
│                                        │ ~~sparkline~~~~~~~~~  │
├────────────────────────────┬───────────┴────────────────────────┤
│ TOP NEWS (6 articles)      │ ENTITY GRAPH (depth=1)             │
│ wider allocation           │ wider allocation                   │
└────────────────────────────┴────────────────────────────────────┘
```

### Fundamentals Tab — New Layout

```
┌──────────────────────────────────────────────────┬──────────────────────────┐
│ LEFT COLUMN (scrollable)                          │ RIGHT SIDEBAR (sticky)   │
│                                                    │                          │
│ ┌────────────────────────────────────────────┐    │ MARKET POSITION          │
│ │ REVENUE & EARNINGS TREND (bar+line chart)  │    │ ┌──────────────────────┐│
│ │ via /fundamentals/timeseries               │    │ │ Sector: Technology   ││
│ └────────────────────────────────────────────┘    │ │ Industry: Consumer   ││
│                                                    │ │ Electronics          ││
│ ┌──────────────┬──────────────┬──────────────┐    │ │ Mkt Cap Rank: #1     ││
│ │ VALUATION    │ PROFITABILITY│ GROWTH (YoY) │    │ │ Sector Rank: #1/42   ││
│ │ [bg-card]    │ [bg-card]    │ [bg-card]    │    │ └──────────────────────┘│
│ │ P/E 34.62x   │ Gross 45.6%  │ Rev +8.2%    │    │                          │
│ │ Fwd PE 31.2x │ Op M 30.1%   │ Earn +12.1%  │    │ COMPETITORS              │
│ │ P/B 52.3x    │ Net 25.3%    │              │    │ ┌──────────────────────┐│
│ │ P/S 10.1x    │ ROE 156.1%   │ [sparkline]  │    │ │ vs MSFT GOOGL AMZN  ││
│ │ EV/EB 27.8x  │ ROA 28.3%    │              │    │ │ P/E comparison table ││
│ │              │              │              │    │ │ Mkt Cap comparison   ││
│ │ [P/E spark]  │ [margin spk] │              │    │ │ Growth comparison    ││
│ └──────────────┴──────────────┴──────────────┘    │ └──────────────────────┘│
│                                                    │                          │
│ ┌──────────────┬──────────────┬──────────────┐    │ OWNERSHIP SNAPSHOT        │
│ │ DIVIDENDS    │ BALANCE SHEET│ 52W RANGE    │    │ ┌──────────────────────┐│
│ │ [bg-card]    │ [bg-card]    │ [bg-card]    │    │ │ Institutional: 60.2% ││
│ │ Yield 0.44%  │ D/E 6.12     │ [range bar]  │    │ │ Insider: 0.07%       ││
│ │ Payout 15.2% │ Current 1.04 │ Hi $288.35   │    │ │ Mutual Fund: 39.7%   ││
│ │              │ Quick 0.93   │ Lo $192.41   │    │ └──────────────────────┘│
│ └──────────────┴──────────────┴──────────────┘    │                          │
│                                                    │ TOP NEWS (3 articles)    │
│ ┌──────────────┬──────────────┬──────────────┐    │ ┌──────────────────────┐│
│ │ DEBT/CREDIT  │ CASH FLOW    │ TECHNICAL    │    │ │ compact article rows ││
│ │ [bg-card]    │ [bg-card]    │ [bg-card]    │    │ │ → More news link     ││
│ │ Int Cov —    │ Op CF $120B  │ Beta 1.21    │    │ └──────────────────────┘│
│ │ Net D/EB —   │ CapEx -$11B  │ MA50↑ MA200↑ │    │                          │
│ │ D/E 6.12     │ FCF $109B    │ RSI 58.3     │    │                          │
│ │ Rating —     │ FCF M 28.8%  │ Short 0.7%   │    │                          │
│ └──────────────┴──────────────┴──────────────┘    │                          │
│                                                    │                          │
│ ┌────────────────────────────────────────────┐    │                          │
│ │ EARNINGS HISTORY (EPS actual vs estimate)  │    │                          │
│ │ [chart: bars with beat/miss coloring]      │    │                          │
│ └────────────────────────────────────────────┘    │                          │
│                                                    │                          │
│ ┌────────────────────────────────────────────┐    │                          │
│ │ INSIDER TRANSACTIONS (recent buys/sells)   │    │                          │
│ │ [compact table: date, name, type, amount]  │    │                          │
│ └────────────────────────────────────────────┘    │                          │
└──────────────────────────────────────────────────┴──────────────────────────┘
```

---

## 7. What Worldview Already Does Well (Differentiators to Preserve)

- **Entity knowledge graph** — only Bloomberg SPLC offers comparable; no retail platform does this
- **AI intelligence brief** — unique; Seeking Alpha has crowdsourced articles but not AI-synthesised briefs
- **Contradiction detection** — no competitor surfaces conflicting claims across news sources
- **Relevance-scored news** — ML-ranked by market impact, not just recency
- **Prediction markets integration** — only Bloomberg has comparable (via Polymarket adapter)

---

## 8. Recommended Changes (Prioritised)

### Wave 1: Backend — Surface Hidden Data (S9 + gateway.ts)
1. Add S9 proxy routes for 6 missing S3 section endpoints
2. Expand `Fundamentals` frontend type with all section fields
3. Add `getFundamentalsTimeseries()` to `gateway.ts`
4. Add `getTechnicals()`, `getInsiderTransactions()`, `getInstitutionalHolders()`, `getEarningsHistory()`, `getShareStatistics()`, `getSplitsDividends()` to `gateway.ts`

### Wave 2: Top Bar + Overview Layout
1. Fix top bar overflow, remove VOL, suppress stale timestamps
2. Build `52WeekRangeBar` component
3. Restructure overview to chart + right sidebar layout
4. Expand key metrics to 12+ rows
5. Add chart toolbar (volume bars, MA toggles, fullscreen)

### Wave 3: Fundamentals Tab Overhaul
1. Section card elevation (bg-card + border)
2. Revenue & Earnings trend chart (full width, recharts)
3. Per-section sparklines via timeseries endpoint
4. Build `TechnicalSnapshot` component
5. Add right sidebar: Market Position + Competitors + Ownership + Top News

### Wave 4: New Data Components
1. Earnings History chart (EPS actual vs estimate with beat/miss)
2. Insider Transactions table
3. Institutional/Fund Holders breakdown
4. Peer comparison table (via screener + COMPETES_WITH edges)
5. Dividend history timeline

### Wave 5: Dashboard Additions
1. Wire Earnings Calendar widget to real data
2. Enable AI Signals widget (component exists, just not rendered)
3. Consider: Insider Activity Feed widget

---

## 9. S9 Endpoints Needed (New)

| Endpoint | Source | Priority |
|----------|--------|----------|
| `GET /v1/fundamentals/{id}/technicals` | S3 technicals-snapshot | HIGH |
| `GET /v1/fundamentals/{id}/share-statistics` | S3 share-statistics | HIGH |
| `GET /v1/fundamentals/{id}/insider-transactions` | S3 insider-transactions-snapshot | HIGH |
| `GET /v1/fundamentals/{id}/earnings-trend` | S3 earnings-trend | HIGH |
| `GET /v1/fundamentals/{id}/earnings-annual-trend` | S3 earnings-annual-trend | MEDIUM |
| `GET /v1/fundamentals/{id}/splits-dividends` | S3 splits-dividends | MEDIUM |
| `GET /v1/fundamentals/{id}/outstanding-shares` | S3 outstanding-shares | LOW |
| `GET /v1/fundamentals/{id}/available-metrics` | S3 metrics/{id} | LOW |

---

## 10. Open Questions

1. **Peer comparison data source**: Use `POST /v1/fundamentals/screen` with sector filter, or build a dedicated endpoint? Screener works but returns the full universe filtered — may be slow for inline comparison.
2. **Financial statements format**: Show as multi-year table (Koyfin-style) or as charts (Simply Wall St-style)? Recommend: table with optional chart toggle.
3. **Technical indicators**: Compute client-side from OHLCV data (MA50/200, RSI) or trust S3's technicals-snapshot? Recommend: use S3 data (already computed, consistent).
4. **Insider transactions depth**: Show latest N transactions or full timeline? Recommend: latest 10 in compact table, "View all" link to dedicated section.
5. **Right sidebar stickiness**: Should the fundamentals right sidebar scroll with the page or remain sticky? Recommend: sticky (position: sticky, top: header-height).

---

## 11. Prevention / Compounding Recommendations

- **New design pattern**: "Right sidebar for contextual data" — document in DESIGN_SYSTEM.md as a layout pattern for detail pages
- **New convention**: Every S3 section endpoint should be proxied through S9 by default — prevents future "data exists but isn't surfaced" gaps
- **New component**: `FundamentalSparkline` — reusable mini-chart that fetches from timeseries endpoint, usable in fundamentals, overview, and screener
- **Type completeness**: Frontend `Fundamentals` type should mirror the full S3 response, not a subset
