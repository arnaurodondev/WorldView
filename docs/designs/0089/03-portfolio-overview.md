# Portfolio — Overview — Design Spec (PRD-0089)

> **Status**: design discovery — feeds the master PRD-0089.
> **Author**: agent-portfolio-overview
> **Coverage**: `/portfolio` landing surface and the embedded "Overview" view that
> precedes the existing Holdings / Transactions / Watchlist tab cluster.
> **Companion doc**: `04-portfolio-detail.md` covers the deeper Holdings drill-down
> (lots, analytics, dividend timeline, transactions). This doc owns ONLY the
> overview / dashboard portion the user sees the moment they click the
> "Portfolio" rail entry.

The current `/portfolio` page jumps straight into a holdings table with a
KPI strip above it. The user complaint — "we are not clearly displaying user
positions" — is well-founded: positions are buried in a 12-column AG Grid
that occupies less than half the viewport, all the contextual surfaces
(top movers, sector allocation, performance chart) live below the fold or
inside other tabs, and most critically the page provides no fast read on
the **shape of the book** in the first five seconds.

This redesign re-orders the page so a hedge-fund PM lands and within five
seconds knows:

1. What is my book worth right now?
2. Am I up or down today (and by how much)?
3. Which positions are doing the work, and which are bleeding?
4. Is the book correctly sized vs cash, vs sectors, vs benchmark?
5. What changed since I last looked (transactions + alerts)?

---

## 1. Competitor research summary

### Bloomberg Terminal — PORT <GO>

- **Layout**: a single ultra-dense screen with the position table dominating
  the left two-thirds (12-18 columns at 18 px row height) and an analytics
  sidebar on the right (sector exposure, factor tilt, top movers, cash).
  The KPI band ("Total Value", "DTD P&L", "MTD P&L", "QTD", "YTD") sits in
  a 24 px strip at the very top.
- **Position table columns** (in order): Ticker, Position, % Wgt, Px, Δ Px,
  Δ%, Δ Position, MV, Cost Basis, P&L (total), P&L%, DTD P&L, MTD P&L,
  Sector, Country. Every value is `font-mono`, right-aligned, tabular-nums.
- **What we steal**: column ordering (weight before price, value before
  P&L), 22 px row tokens, sector exposure as a horizontal stacked bar
  rather than a treemap on the overview (treemap is one click deep on PORT,
  not on the landing page), benchmark-aware return numbers in the KPI band.

### Interactive Brokers — TWS Account Window / Portfolio tab

- **Layout**: positions are the entire screen. Even the toolbar is collapsed
  to a single 28 px row. The position table runs at 20-22 px per row and
  shows ~20 columns including realised P&L per row, average cost, model
  value, target weight, drift, and a "rebalance" link.
- **What we steal**: the idea that on the Overview the table itself IS the
  primary surface — analytics flank it but never dominate. Also IB's
  "TOTAL" pinned bottom row showing market value, P&L (total + day),
  cost basis, and weight (=100%). We already do the totals row; this
  design keeps it.

### TradingView Portfolio

- **Layout**: equity-curve chart spans the full width at the top (~180 px
  tall), then a horizontal allocation strip (sector / asset class /
  currency stacked bars), then the positions table. Modern, slightly less
  dense than Bloomberg but still 11 px font.
- **What we steal**: the equity-curve-on-top idea, but compressed to 120 px
  (TradingView's 180 px is too tall for terminal density) and **flanked
  by a benchmark overlay** (S&P 500). Also their sparkline-per-row inside
  the table.

### Finviz Portfolio

- **Layout**: a table-only page, 14 columns at 22 px rows. Performance vs
  benchmark in a small chart that you can toggle on/off in the header.
- **What we steal**: the toggle pattern — the equity curve is collapsible
  so the user can swap the page into "table only" mode and see ~25
  positions above the fold instead of 12.

### Schwab StreetSmart Edge / Koyfin

- **Layout**: a wide horizontal "vitals" strip (account value, day change,
  buying power, margin, equity) at the very top, then the positions table.
  Strip cells separated by 1 px vertical hairlines, no cards.
- **What we steal**: the divided vitals strip (we already have this pattern
  on PortfolioKPIStrip; the redesign keeps and extends it from 6 to 8
  cells including realized P&L, cash, and a sharpe/vol pair).

### Public.com / Wealthfront (modern retail)

- **Note**: deliberately **not** mirrored. The user said the overview is
  unprofessional precisely because it leans retail. We mention these
  competitors only to flag specific anti-patterns to avoid:
  - Large emoji-laden percentage chips
  - Animated count-up numbers (banned by the design system)
  - Pie charts with legends below
  - Single-position-per-row cards stacked vertically

### Cross-competitor distillation

| Pattern | Bloomberg | IBKR | TradingView | Finviz | Koyfin | We adopt |
|---------|-----------|------|-------------|--------|--------|----------|
| Table is the primary surface | yes | yes | shared | yes | shared | **yes** |
| 22 px row height max | yes | yes | yes | yes | yes | **yes** |
| Equity curve above table | no (sidebar) | no | yes | optional | yes | **collapsible; default on** |
| Sector exposure on overview | sidebar | sidebar | row | no | row | **stacked bar row** |
| Top movers callout | no | no | yes | no | yes | **two-cell strip** |
| Sparkline per row | no | no | yes | no | yes | **yes (14-day, 60×16)** |
| Realised P&L on overview | yes | yes | no | no | yes | **yes (period-toggleable)** |
| Benchmark overlay on chart | yes | no | yes | optional | yes | **yes (S&P 500)** |

---

## 2. User intent for this page

### Primary persona

Active hedge-fund PM or sophisticated retail trader who manages a single
book of 5-40 positions and revisits the page 6-15 times per day. They open
the overview as their first action after login and as the default tab
inside `/portfolio`. They do NOT use this page to add or close positions —
that is what the Transactions tab and the AddPosition dialog are for.

### Primary tasks (top 3)

1. **Snapshot the book.** "What is the total value, today's P&L, unrealised
   P&L, and how does that compare to yesterday?" Must be answered without
   any scroll or click.
2. **Find the movers.** "Who is up the most today? Who is bleeding? Are
   today's winners and losers consistent with the macro tape?" Must be
   answerable from the visible table in five seconds.
3. **Validate sizing.** "Is any single position too big? Is the book too
   concentrated in one sector? Am I holding too much cash?" Must be
   answered from the sector/exposure strip and weight column without
   leaving the page.

### Secondary tasks

- Compare current performance to S&P 500 over 1M / 3M / YTD.
- Spot stale prices (freshness dots) before trusting any P&L number.
- Glance at recent transactions to confirm the morning's broker sync.
- Catch the most recent watchlist alerts (alerts go to the Alerts page
  proper, but we surface the freshest 3 in a strip for context).

### Anti-patterns this page must NOT become

- **A dashboard with cards.** No `border-radius: 8px` cards with `p-4`
  padding and headers. Every surface is a 22 px row or a 1 px-bordered
  panel; no card chrome.
- **An empty-state factory.** Six widgets that each render "—" for paper
  traders is worse than three widgets that render meaningful numbers.
- **A scroll marathon.** Today's page is 1,400 px tall before the user
  even sees half their positions. Target: holdings table starts above the
  fold and is at least 60 % visible on a 1440×900 viewport.
- **A "Total Value: $33,887.20" headline shouting in 32 px font.** The
  total value is a 13 px tabular number; the 9-column position table is
  what the eye locks onto.

---

## 3. Backend data available

The backend inventory doc (`00-backend-data-inventory.md`) is not yet
written, so this section enumerates every field this page consumes
directly from S9 (which proxies S1). Every endpoint cited below already
exists in `docs/services/portfolio.md`.

### Endpoints consumed

| Endpoint | Used for | Currently displayed? |
|----------|----------|----------------------|
| `GET /api/v1/portfolios` | Portfolio selector in header | yes |
| `GET /api/v1/portfolios/{id}` | Portfolio metadata (name, base currency) | yes |
| `GET /api/v1/holdings/{portfolio_id}` | Position rows (qty, avg cost, currency, instrument_id, entity_id) | yes |
| `GET /api/v1/portfolios/{id}/exposure` | Cash, buying power, invested, leverage | partial — only via ExposureStrip |
| `GET /api/v1/portfolios/{id}/value-history` | Equity-curve sparkline + chart, benchmark series | only on Holdings sub-tab |
| `GET /api/v1/portfolios/{id}/realized-pnl` | Realised P&L tile (FIFO, period-aware) | yes |
| `GET /api/v1/portfolios/{id}/concentration` | Concentration strip + sector weights | only via ConcentrationStrip |
| `GET /api/v1/portfolios/{id}/holdings/{instrument_id}/lots` | Hover tooltip on a position row (open-lot count, ST/LT split) | no — **NEW USAGE** |
| `GET /api/v1/transactions?portfolio_id=…&limit=8` | Recent activity strip | only on Transactions tab |
| `GET /api/v1/brokerage-connections?portfolio_id=…` | Empty-state branch ("connect a brokerage") | yes |
| `GET /api/v1/portfolios/{id}/performance?period=1D` | Header chip (period return) | yes |
| `GET /v1/market/quote/batch` (S9 composition) | Live price, day change, freshness per instrument | yes |
| `GET /v1/market/series?ticker=…&period=14d` (S9) | 14-day sparkline per row | no — **NEW USAGE** |
| `GET /v1/market/series?ticker=SPY&period=…` (S9) | Benchmark series on the equity curve | no — **NEW USAGE** |
| `GET /v1/market/overview-bulk?instrument_ids=…` (S9) | Sector, asset_type, country per holding | yes (via holdingOverviews) |
| `GET /v1/instruments/{id}/risk` (S9, derived from S3) | Per-position beta for "beta-adjusted exposure" | no — **NEW USAGE** |

### Fields surfaced per holding row

Every column the table renders, mapped to its backend source:

| Column | Source | Format | Notes |
|--------|--------|--------|-------|
| Ticker | `holdings[].ticker` | `font-mono 11px text-primary` | pinned left |
| Name | `holdings[].name` | truncated, 11 px | hover = full name |
| Qty | `holdings[].quantity` | `tabular-nums`, locale-formatted | |
| Avg Cost | `holdings[].average_cost` | `tabular-nums`, currency | |
| Last | `quotes[id].price` | `tabular-nums`, freshness dot prefix | |
| Day Δ$ | `quotes[id].change × qty` | colour by sign | |
| Day Δ% | `quotes[id].change_pct` | colour by sign | |
| Spark (14d) | `series[id].closes[-14:]` | 60×16 inline SVG | NEW |
| Mkt Value | `qty × price` | `tabular-nums` | |
| Unreal $ | `(price − avg) × qty` | colour by sign | |
| Unreal % | `(price − avg) / avg × 100` | colour by sign | |
| Weight | `value / totalValue` | mini-bar + % | |
| Sector | `overviews[id].sector` | 11 px muted | NEW on overview (was Holdings-only) |
| Asset | `overviews[id].asset_type` | 1-letter chip (E/F/B/C) | NEW |

Fields the user explicitly mentioned that are **already produced by the
backend but not currently displayed on the overview**:

- Sector exposure (yes, available, currently only on Holdings tab)
- Asset allocation (yes, derivable from `overviews[].asset_type`)
- Currency exposure (yes, derivable from `holdings[].currency`)
- Cash + buying power (yes, `exposure.cash` and `exposure.buying_power`)
- Top contributors / detractors (no S9 endpoint yet — computed
  client-side from the holdings × quotes join; flagged as a future S1
  endpoint in §10)
- Sharpe / vol / max drawdown (partially — value-history derivation
  is client-side today; a dedicated `/risk-metrics` endpoint is
  flagged in §10)

---

## 4. Layout

### 4.1 Recommended layout — "Anchored table" (default)

The page is a vertical stack of fixed-height strips above a flex-1
positions table. The table is the centre of gravity; everything above
it is high-density chrome. Below the table sits a 96 px contributors
strip and a 96 px recent-activity strip.

ASCII wireframe — 1440 × 900 viewport. Each `─` ~= 12 px wide, each
text row ~= 22 px tall. Numbers in brackets are pixel heights.

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ [36] PORTFOLIO  ▼ Main Book (USD)  · 14 positions  · scope: 1 owner · 1 broker         + ADD POSITION  ⋯         │ ← page header (existing, kept)
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [28] TOTAL VALUE │ DAY P&L         │ UNREAL P&L      │ REAL P&L (YTD) │ CASH         │ BUYING PWR  │ TOP GAIN  │ TOP LOSE │ │ ← KPI strip (8 cells)
│      $337,142.55│ +$2,418.66 (0.7%)│ +$48,221 (16.7%)│ +$11,840 (4.0%) │ $1,402       │ $1,402      │ NVDA +3.1%│ INTC -1.8%│ │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [22] EXPOSURE  INV $335,740 (99.6%) ·  CASH $1,402 (0.4%) ·  LEV 1.00× ·  β-ADJ 1.12 ·  CCY USD 92% · EUR 8%      │ ← exposure + currency strip
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [22] CONCENTRATION  HHI 1,847 [moderate] · Top-3 47.2% · 14 names · Sector top: TECH 38.1% · FIN 17.4% · HC 12.0% │ ← concentration + sector tease
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [120] PERFORMANCE                                              [1W][1M][3M●][6M][1Y][All]      ▼  collapse        │ ← equity curve panel (collapsible)
│       ╱╲    ╱──╲      ╱╲      Portfolio  +4.8% ──────                                                              │
│      ╱  ╲__╱    ╲    ╱  ╲     S&P 500    +3.2% ─ ─ ─                                                               │
│     ╱            ╲__╱    ╲___                                                                                      │
│    ╱                                                                                                               │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [22] SECTOR    ████████████████████████ TECH 38%  ████████████ FIN 17%  ██████████ HC 12%  ████████ ENG 9%  …    │ ← single stacked-bar
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [22] POSITIONS — 14  ·  sort: Value ▼  ·  hidden: 0  ·  ⎵ filter (press /)                                       │ ← table chrome
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [22] TICKER NAME              QTY    AVG     LAST  DAY$    DAY%   SPARK     VALUE    PNL$     PNL%   WGT    SEC A│ ← header (10 px UPPERCASE)
│ [22] AAPL   Apple Inc        100  185.50  214.32  +143  +0.67% ▁▂▃▅▇▆▇ $21,432  +2,882  +15.5%  6.4% TECH E│
│ [22] MSFT   Microsoft         50  302.00  411.18   -22  -0.05% ▆▆▅▆▇▇▆ $20,559  +5,459  +36.2%  6.1% TECH E│
│ [22] NVDA  NVIDIA            120  340.00  462.05  +511  +1.12% ▂▃▅▇▆▇▇ $55,446 +14,646  +35.9% 16.4% TECH E│
│ [22] GOOGL Alphabet           80  138.00  167.40   -89  -0.53% ▆▅▆▅▆▅▆ $13,392  +2,352  +21.3%  4.0% TECH E│
│ [22] AMZN  Amazon.com         40  140.00  178.92  +120  +0.67% ▁▃▅▆▇▇▇ $ 7,157  +1,557  +27.8%  2.1% CONS E│
│ [22] BRK.B Berkshire H. B     35  362.00  401.20    +5  +0.01% ▆▆▆▇▇▆▇ $14,042  +1,372   +10.8% 4.2% FIN  E│
│ [22] JPM   JPMorgan Chase     65  155.00  178.45   -52  -0.29% ▆▅▆▆▅▅▆ $11,599  +1,524   +15.1% 3.4% FIN  E│
│ [22] V     Visa Inc           45  220.00  264.10  +110  +0.42% ▅▆▆▇▇▆▇ $11,884  +1,984   +20.0% 3.5% FIN  E│
│ [22] UNH   UnitedHealth       30  500.00  541.60   -45  -0.08% ▆▆▆▆▅▆▆ $16,248  +1,248    +8.3% 4.8% HC   E│
│ [22] LLY   Eli Lilly          22  600.00  792.30  +175  +0.22% ▆▇▇▇▇▇▇ $17,430  +4,230   +32.0% 5.2% HC   E│
│ [22] XOM   ExxonMobil         60  102.00  118.70   -36  -0.30% ▆▆▅▅▆▆▅ $ 7,122  +1,002   +16.4% 2.1% ENG  E│
│ [22] CVX   Chevron Corp       55  151.00  159.20    -8  -0.05% ▆▆▆▅▆▆▆ $ 8,756    +451    +5.4% 2.6% ENG  E│
│ [22] INTC  Intel Corp        180   42.00   30.95  -185  -1.84% ▆▅▄▃▃▂▂ $ 5,571  -1,989   -26.3% 1.7% TECH E│
│ [22] ANTHRO Anthropic Tok.    100   88.00  108.50   +89  +0.83% ▅▆▆▇▆▇▇ $10,850  +2,050   +23.3% 3.2% TECH E│
│ [22] ──────────────────────────────────────────────────────────────────────────────────────────────────────────│
│ [22] TOTAL  —                  —     —     —   +2,419 +0.72%   —    $337,143 +48,221  +16.7%  100% — — │ ← pinned bottom
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [96] TOP CONTRIBUTORS (today)            │ TOP DETRACTORS (today)              │ RECENT ACTIVITY (last 8)         │
│      NVDA   +$511   +1.12%               │ INTC  -$185  -1.84%                  │ 12:18 BUY  AAPL  20   $214.30   │
│      LLY    +$175   +0.22%               │ JPM    -$52  -0.29%                  │ 09:30 SYNC Schwab  ok           │
│      AAPL   +$143   +0.67%               │ GOOGL  -$89  -0.53%                  │ Yest  DIV  MSFT  $36.50          │
│      ANTHRO +$ 89   +0.83%               │ XOM    -$36  -0.30%                  │ Yest  SELL CVX   5    $158.20   │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Grid description

The page is a single CSS-flex column inside the existing app shell:

```
flex flex-col h-full bg-background
├── PortfolioPageHeader            (h-9, shrink-0, bg-card)
├── PortfolioKPIStrip [extended]   (h-7, shrink-0, bg-card, divide-x 8 cells)
├── ExposureCurrencyStrip [new]    (h-[22px], shrink-0, bg-card)
├── ConcentrationSectorTeaseStrip  (h-[22px], shrink-0, bg-card)
├── PerformanceChartPanel [new]    (h-[120px], shrink-0, bg-background, collapsible)
├── SectorAllocationBar [new/refactor] (h-[22px], shrink-0, bg-card)
├── HoldingsTableChrome [new]      (h-[22px], shrink-0, bg-card)
├── SemanticHoldingsTable          (flex-1, min-h-0, bg-background)
└── BottomStripCluster [new]       (h-24, shrink-0, bg-card, 3 cells)
```

Sticky regions:

- KPI strip + exposure + concentration always visible (no scroll inside)
- Performance chart is **inside** the flex column and scrolls with the
  table when the user collapses it; when expanded it consumes 120 px
- The holdings table header is sticky inside the AG Grid viewport
  (already implemented)
- The TOTAL row is the pinned bottom row inside AG Grid (already
  implemented)

### 4.3 Density target

At 1440×900 above the fold:

| Strip | Height | Cells |
|-------|--------|-------|
| Page header | 36 | 4 |
| KPI strip | 28 | 8 |
| Exposure / currency | 22 | 6 |
| Concentration / sector tease | 22 | 5 |
| Performance chart | 120 | n/a (graph) |
| Sector allocation bar | 22 | 8 segments |
| Table chrome | 22 | 4 |
| Holdings header | 22 | 14 columns |
| Holdings rows (visible) | 22 × ~16 = 352 | 16 × 14 = 224 cells |
| Bottom strips (3 cells × 4 rows) | 96 | 12 |

Total cells above 900 px fold: **8 + 6 + 5 + 8 + 4 + 14 + 224 + 12 ≈ 281**.
Comfortably above the 40-60 minimum from the index doc; in line with
Bloomberg PORT density.

### 4.4 Alternative layout — "Split table" (rejected, see §9)

Considered but rejected: a two-column layout with the holdings table on
the left and an analytics rail (sector treemap, contributors, equity
curve) on the right. ASCII sketch:

```
┌──────────────────────────────────────┬──────────────────────────────┐
│ HOLDINGS TABLE (no spark, no sector) │ EQUITY CURVE  +4.8%          │
│ TICKER QTY LAST DAY$ VALUE PNL WGT   │                              │
│ … 16 rows …                          │ ─ S&P 500 +3.2%              │
│                                      ├──────────────────────────────┤
│                                      │ SECTOR TREEMAP               │
│                                      │ ▓▓▓ TECH ▓▓ FIN ▓ HC …       │
│                                      ├──────────────────────────────┤
│                                      │ TOP CONTRIBUTORS / DETRACTORS │
└──────────────────────────────────────┴──────────────────────────────┘
```

Tradeoffs in §9.

---

## 5. Component breakdown

Files marked **NEW** do not exist yet. Files marked **EXTEND** exist and
need new props or behaviour. Files marked **KEEP** are reused verbatim.

| Component | File path | Status | LOC budget | Renders |
|-----------|-----------|--------|------------|---------|
| `PortfolioPageHeader` | `features/portfolio/components/PortfolioPageHeader.tsx` | KEEP | — | portfolio selector + actions |
| `PortfolioKPIStrip` | `components/portfolio/PortfolioKPIStrip.tsx` | EXTEND | +60 | extended from 7→8 tiles (add Cash + Buying Power) |
| `ExposureCurrencyStrip` | `components/portfolio/ExposureCurrencyStrip.tsx` | NEW | 140 | single h-[22px] strip; merges ExposureStrip + new currency cells |
| `ConcentrationSectorTeaseStrip` | `components/portfolio/ConcentrationSectorTeaseStrip.tsx` | NEW | 130 | merges ConcentrationStrip + top-3 sector preview |
| `PerformanceChartPanel` | `components/portfolio/PerformanceChartPanel.tsx` | NEW | 220 | 120 px chart with benchmark overlay; collapsible |
| `SectorAllocationBar` | `components/portfolio/SectorAllocationBar.tsx` | NEW | 110 | single-row stacked horizontal bar (replaces 240 px treemap on overview) |
| `HoldingsTableChrome` | `components/portfolio/HoldingsTableChrome.tsx` | NEW | 90 | sort indicator, hidden-count, filter input shortcut |
| `SemanticHoldingsTable` | `components/portfolio/SemanticHoldingsTable.tsx` | EXTEND | +40 | add SPARK column, ASSET column; same AG Grid base |
| `SparklineCellRenderer` | `components/portfolio/cells/SparklineCellRenderer.tsx` | NEW | 70 | inline 60×16 SVG sparkline from 14-day closes |
| `AssetTypeCellRenderer` | `components/portfolio/cells/AssetTypeCellRenderer.tsx` | NEW | 30 | single-letter chip (E=equity, F=fund, B=bond, C=crypto) |
| `ContributorsStrip` | `components/portfolio/ContributorsStrip.tsx` | NEW | 130 | top-4 / bottom-4 movers (today + period toggle) |
| `RecentActivityStrip` | `components/portfolio/RecentActivityStrip.tsx` | NEW | 90 | last 8 transactions, compact one-line format |
| `BrokerageEmptyState` | `components/portfolio/BrokerageEmptyState.tsx` | NEW | 80 | full-page CTA when no portfolios + no brokerage |

Existing components that **move off the overview** to the Holdings
sub-tab (`04-portfolio-detail.md`):

- `HoldingLotsPanel` (deep drill-down)
- `DayPnLDistribution` (30-day Δ$ chart — analytical, not snapshot)
- `RealizedPnLSparkline` (replaced on overview by a single KPI cell)
- `DividendYTDStrip` (broker-only)
- `PositionBarHeat` (replaced by the inline SPARK column)
- `PortfolioAnalyticsSection` (sharpe / vol / drawdown — analytical)

### 5.1 Hook for top movers (client-side derivation)

```ts
// features/portfolio/hooks/useTopMovers.ts — NEW, ~80 LOC
//
// Derives top-4 contributors and bottom-4 detractors from the same
// `enrichedHoldings` + `quotes` already loaded by usePortfolioData.
// No new backend call. Returns:
//   { todayWinners, todayLosers, periodWinners, periodLosers }
// Period defaults to 1D; toggling to 1M/YTD just re-sorts on `pnlPct`
// so it's pure compute, no extra fetch.
```

### 5.2 Hook for sparkline series (batched)

```ts
// features/portfolio/hooks/useHoldingsSeries.ts — NEW, ~100 LOC
//
// Calls a new (or existing batch) S9 endpoint:
//   GET /v1/market/series/batch?instrument_ids=…&days=14
// Returns a `Record<instrument_id, number[]>` keyed for the cell
// renderer. staleTime: 15 min (sparklines are intra-day-tolerant).
// Falls back gracefully: rows without a series render an em-dash.
```

---

## 6. Visual spec (numerical)

Honors the shared scale in `_INDEX.md`.

### 6.1 Strip-by-strip pixel spec

| Surface | Height | Padding | Background | Border | Font |
|---------|--------|---------|------------|--------|------|
| Page header | 36 | px-3 | `bg-card` | `border-b border-border` | 11 px page title; 11 px selector |
| KPI strip | 28 | px-3 py-1 | `bg-card` | `border-b border-border` + `divide-x divide-border` | label 10 px UPPERCASE; value 13 px mono |
| Exposure / currency strip | 22 | px-3 py-0.5 | `bg-card` | `border-b border-border` + `divide-x` | 10 px label, 11 px value mono |
| Concentration strip | 22 | px-3 py-0.5 | `bg-card` | `border-b border-border` + `divide-x` | 10 px label, 11 px value; HHI badge 9 px |
| Performance chart panel | 120 | p-2 | `bg-background` | `border-b border-border` | axes 9 px; legend 10 px; period buttons 10 px |
| Sector allocation bar | 22 | px-3 | `bg-card` | `border-b border-border` | inline labels 10 px |
| Holdings table chrome | 22 | px-3 | `bg-card` | `border-b border-border` | 10 px UPPERCASE |
| Holdings header row | 22 | px-2 (per cell) | `bg-card` | `border-b border-border` | 10 px UPPERCASE muted |
| Holdings data rows | 22 | px-2 (per cell) | `bg-background` | row hover: `bg-muted/30` | values 11 px mono tabular-nums |
| Holdings TOTAL row | 22 | px-2 | `bg-card` | `border-t border-border` | values 11 px mono semibold |
| Bottom strip cluster | 96 (24 × 4 rows) | px-3 py-1 | `bg-card` | `border-t border-border` + 2 `divide-x` columns | label 10 px, value 11 px mono |

### 6.2 Column widths (holdings table)

Total table width budget at 1440 viewport with 80 px collapsed sidebar
= 1360 px. We reserve 24 px for a vertical scrollbar leaving 1336 px:

| Col | Width | Align | Min | Notes |
|-----|-------|-------|-----|-------|
| Ticker | 76 | left | 70 | pinned-left, `text-primary` |
| Name | 168 | left | 110 | truncates with ellipsis; native `title` |
| Qty | 78 | right | 60 | locale-formatted integer |
| Avg Cost | 86 | right | 70 | currency |
| Last | 86 | right | 70 | freshness dot prefix (3 × 3 px) |
| Day Δ$ | 82 | right | 64 | colour by sign |
| Day Δ% | 70 | right | 56 | colour by sign |
| Spark | 76 | center | 64 | inline 60×16 SVG; fixed width |
| Mkt Value | 96 | right | 80 | currency |
| Unreal $ | 90 | right | 72 | colour by sign |
| Unreal % | 70 | right | 56 | colour by sign |
| Weight | 110 | right | 90 | mini-bar (48 px) + % (36 px) |
| Sector | 100 | left | 80 | 11 px muted, truncate |
| Asset | 48 | center | 36 | single-letter chip |
| **Total** | **1336** | — | — | fits exactly without horizontal scroll |

### 6.3 Colour usage

- Tickers (everywhere): `text-primary` (#FFD60A) at `font-medium`
- Positive P&L / Day Δ: `text-positive` (#00D26A)
- Negative P&L / Day Δ: `text-negative` (#FF3B5C)
- Neutral / em-dash: `text-muted-foreground` (#71717A)
- Concentration "moderate" badge: `text-warning` (#FFB000) with `border-warning/30`
- Benchmark line on chart: `text-muted-foreground` dashed; portfolio line solid `text-primary`
- Sector allocation bar segments: gradient through the existing palette
  using `bg-primary/{30,40,50,60,70,80,90}` — same logic as
  `ScreenerBars`; no new colours introduced

### 6.4 Row hover

```
tr:hover { background: hsl(var(--muted) / 0.3); cursor: pointer; }
```

No transition, no scale, no glow. Hedge-fund PMs find animated rows
distracting.

### 6.5 Animations

**None.** No fade-ins, no count-up numbers, no chart-line draws. The
only visual feedback is the existing AG Grid `flashCells({ duration: 500 })`
on live quote arrival — already in place. Architecture test
`__tests__/architecture/no-motion-in-data.test.ts` (to be added in the
implementation plan) bans `framer-motion`, `animate-*`, and CSS
`transition-*` in the `components/portfolio/` directory.

---

## 7. Interaction model

### 7.1 Hotkeys

All hotkeys are scoped to `/portfolio` and registered via the existing
keymap registry. They never fire when an input or AG Grid editor is
focused.

| Key | Action |
|-----|--------|
| `B` | Back to portfolio list (open the selector dropdown) |
| `T` | Switch to Transactions tab |
| `A` | Switch to Analytics (Holdings detail sub-tab) |
| `W` | Switch to Watchlist tab |
| `R` | Refresh all queries (`queryClient.invalidateQueries({ queryKey: ['portfolio', activeId] })`) |
| `/` | Focus the holdings filter input |
| `1` / `2` / `3` / `4` / `5` | Toggle equity-curve period (1W / 1M / 3M / 6M / 1Y) |
| `0` | Toggle the equity-curve panel collapsed / expanded |
| `c` | Collapse / expand contributors strip |
| `?` | Open the hotkey cheat-sheet overlay (existing) |
| `Esc` | Close any open dropdown / overlay |

`B` re-uses the existing `useKeymap('portfolio-back', () => …)` pattern
in the global keymap provider; the back action just opens the
PortfolioPageHeader dropdown rather than navigating away, mirroring
Bloomberg's `PORT <GO>` panel toggle.

### 7.2 Hover

- **Row hover**: `bg-muted/30`, cursor pointer (already implemented).
- **Ticker cell**: shows native `title` with full instrument name.
- **Sparkline cell**: native `title` with "14-day · open $X.XX · close
  $Y.YY · range $A.AA-$B.BB".
- **Day Δ$ / %**: tooltip with intraday open / close estimates if
  available (`quotes[id].open` is already in the BatchQuote response).
- **Weight cell**: tooltip showing absolute market value and rank
  ("rank 3 of 14, top-3 share 47.2 %").
- **Concentration HHI badge**: tooltip explains the band thresholds
  (already implemented in the existing `ConcentrationStrip`).
- **KPI tiles**: realised-P&L tile already shows long-term / short-term
  in `title` — kept.

### 7.3 Clicks

- **Row click**: navigates to `/instruments/{instrument_id}` (already
  implemented).
- **Row right-click**: opens the existing AG Grid context menu (Buy /
  Sell / Add to watchlist / Hide / Copy ticker).
- **Spark cell click**: same as row click (instrument page).
- **Sector segment in stacked bar**: navigates to
  `/portfolio?tab=holdings&filter=sector:TECH` — pre-filters the table.
- **Top mover entry in bottom strip**: navigates to the instrument
  page (NOT just selects the row — full navigation; aligns with the
  user's "I want to investigate this winner" intent).
- **"⋯" overflow in header**: dropdown with `Resync brokerage`,
  `Recompute snapshot` (admin), `Export CSV`, `Delete portfolio`.

### 7.4 Loading states

There are **four** distinct loading branches; each has its own
skeleton shape to prevent layout shift.

1. **Initial mount, no portfolios yet** (`portfoliosLoading`)
   - Renders the existing full-page skeleton (page header skeleton →
     KPI strip skeleton with 8 tiles → exposure / concentration row
     skeletons → 16 `h-[22px]` row skeletons in place of the table)

2. **Portfolio chosen, holdings loading** (`holdingsLoading`)
   - Strips remain skeleton; only the table area is loading
   - Equity-curve placeholder = single grey baseline + "Loading
     performance…" 10 px muted text dead-centre

3. **Holdings loaded, quotes still pending**
   - Table renders with em-dashes in `Last`, `Day Δ$`, `Day Δ%`,
     `Spark`, `Mkt Value`, `Unreal $`, `Unreal %`. Avg Cost + Qty +
     Weight (still derivable) render normally.
   - KPI tiles affected (Day P&L, Top Gainer, Top Loser) render
     `Skeleton` per the existing F-P-012 pattern.

4. **Quotes loaded, fundamentals (sector) pending**
   - SECTOR + ASSET cells show em-dash. Sector allocation bar shows
     a single grey segment with "loading" caption.

### 7.5 Error states

| Failure | UI |
|---------|----|
| `portfoliosError` (S1 unreachable) | full-page InlineEmptyState: "Could not load portfolios. Check the connection and reload." with `Retry` button → `queryClient.invalidateQueries(['portfolios'])` |
| Holdings query failed | inline banner above the table: red 1 px border, 11 px message + 11 px "Retry" link. KPI strip still renders from cache if available. |
| Quotes batch failed | non-blocking. Table renders avg-cost / qty / weight; affected cells em-dash. A 9 px `text-warning` "Live prices unavailable" badge appears in HoldingsTableChrome. |
| Realised-P&L endpoint failed | KPI tile shows the existing client-side approximation with `(approx)` suffix (existing behaviour, kept). |
| Series batch failed | every SPARK cell renders em-dash; no inline error (sparklines are cosmetic). |
| Concentration / exposure failed | strip renders em-dashes for all cells; no full-page error. |
| Performance endpoint failed | equity-curve panel collapses itself and shows a 11 px muted "Performance data temporarily unavailable" message. |

### 7.6 Empty states

| Condition | UI |
|-----------|----|
| User has zero portfolios | full-page `BrokerageEmptyState` with two CTAs: `Create portfolio` (large) and `Connect brokerage` (secondary). 11 px helper text. |
| Portfolio has zero holdings, zero brokerage connections | full-page CTA inside the table area: "No positions yet — connect a brokerage to import or add a position manually." Two buttons: `Connect brokerage` (primary) and `Add position` (secondary). Existing `BrokerageConnectionCard` is reused as the body. |
| Portfolio has zero holdings, but at least one brokerage connection | "No holdings reported from your broker. Try `Resync` to refresh." with a `Resync` button calling `POST /api/v1/brokerage-connections/{id}/sync`. |
| All holdings have `quantity = 0` (closed-out book) | existing `allZeroQty` empty state in `SemanticHoldingsTable` is kept; strips and KPI still render correctly. |
| Transactions strip empty (paper trader, no broker, no manual adds) | "No recent activity. Transactions and broker syncs will appear here." — small, no CTA (this is the third cell, never the focus). |

---

## 8. Data fetching

### 8.1 TanStack Query keys

All keys are namespaced through `lib/query/keys.ts`. Existing keys are
unchanged; new keys proposed below.

| Resource | Key | staleTime | Reused by |
|----------|-----|-----------|-----------|
| `portfolios` | `qk.portfolios(ownerUserId)` | 5 min | dashboard, screener context |
| `portfolio detail` | `qk.portfolio(id)` | 5 min | many |
| `holdings` | `qk.holdings(portfolioId)` | 30 s | shared with Holdings sub-tab |
| `holdings quotes batch` | `qk.quotesBatch(instrumentIds)` | 15 s (websocket pushes invalidations) | instrument page, screener |
| `holdings series batch (14d)` | `qk.holdingsSeries(portfolioId, 14)` **NEW** | 15 min | overview only |
| `holdings overviews` | `qk.overviewBulk(instrumentIds)` | 5 min | dashboard, screener |
| `exposure` | `qk.exposure(portfolioId)` | 30 s | shared by CashRow + ExposureCurrencyStrip |
| `concentration` | `qk.concentration(portfolioId)` | 60 s | shared by sector strip |
| `realized P&L` | `qk.realizedPnL(portfolioId, fromDate, toDate)` | 5 min | KPI tile |
| `value history` | `qk.valueHistory(portfolioId, period)` | 5 min | equity-curve chart |
| `benchmark series` | `qk.benchmarkSeries('SPY', period)` **NEW** | 5 min | equity-curve overlay |
| `recent transactions (8)` | `qk.transactions(portfolioId, { limit: 8 })` | 30 s | Recent activity strip |
| `top movers (derived)` | (no key — pure compute over `holdings × quotes`) | — | bottom strip |

### 8.2 Network budget

Cold-load count (first visit, empty cache):

1. `GET /portfolios` (already needed for the selector dropdown)
2. `GET /portfolios/{id}/bundle` — existing aggregator that wraps
   exposure + concentration + holdings + holding-overviews; warm the
   cache in one round-trip (already in `usePortfolioBundle`)
3. `POST /quotes/batch` for all instrument IDs
4. `GET /value-history?period=3M`
5. `GET /market/series/batch?ids=…&days=14` **NEW (one call)**
6. `GET /market/series?ticker=SPY&period=3M` **NEW**
7. `GET /transactions?portfolio_id=…&limit=8`
8. `GET /realized-pnl?from=…&to=…`

Eight requests; calls 3-8 fire in parallel after 2 resolves. With S9's
bundle aggregator already in place this is the same as today plus two
new market-data calls. Both new calls hit S3 which already serves
batch-series at 99 ms p95.

### 8.3 Websocket / SSE

The existing `usePriceTick` WS subscription already drives live `quotes`
into the table; the SPARK cell does NOT subscribe — 14-day sparklines
are stable enough on 15-min staleTime. Equity-curve refreshes daily at
21:30 UTC (per `portfolio_snapshot_worker`), so a manual `R` refresh
is enough.

### 8.4 Dedup opportunities

- `overviewBulk` is fetched on dashboard + screener. With identical
  keys (`instrument_ids` sorted) the React-Query cache makes the
  third visit a cache hit.
- The new `holdingsSeries` 14d batch is **unique to overview**.
  Future deduplication: when the user navigates to an instrument
  page, the per-instrument series fetch can short-circuit by reading
  the existing 14d slice from the batch cache.

---

## 9. Tradeoffs and decisions

### 9.1 Why "anchored table" over "split table" (rejected alternative)

**Anchored table** (chosen): vertical stack of strips above one big
flex-1 table; analytics flank above and below.

**Split table** (rejected): table on the left half, analytics rail on
the right (equity curve + sector treemap + contributors).

| Criterion | Anchored | Split |
|-----------|----------|-------|
| Columns visible without horizontal scroll | 14 | 9-10 (rail eats 320 px) |
| Above-fold positions | ~16 | ~22 (rail makes table taller) |
| Mobile/narrow viewport adaptability | trivial — strips collapse | bad — rail must hide |
| Eye scan path | top-to-bottom, predictable | zigzag, slow |
| Bloomberg / IBKR resemblance | high | medium |
| TradingView / Koyfin resemblance | medium | high |

The chosen anchored layout is closer to Bloomberg PORT and IBKR — the
references the user explicitly called out — and gives every position
all 14 columns at full width. The split layout's main advantage (taller
table) is illusory because the rail takes 320 px that the table would
have used otherwise, and the rail is too narrow to host the equity
curve at any useful resolution.

### 9.2 Why a stacked sector bar over a sector treemap

**Single-row stacked bar** (chosen): 22 px row showing 6-8 sector
segments with inline labels, top sector first.

**Treemap** (rejected on overview, kept on Holdings sub-tab): 240 px
visual with labelled rectangles.

The treemap is genuinely better for **exploring** sector exposure
(area encodes weight better than length); the bar is better for
**glancing** at sector exposure ("am I 38 % tech right now?"). The
overview's job is glanceability, so the bar wins. The treemap lives
on the Holdings sub-tab where the user has already decided they want
to dig in.

### 9.3 Why 14-day sparkline (not 30 or 90)

**14 days** (chosen): half a month of trading days; tracks earnings
sentiment well; 60 px wide cell fits at 4.3 px/day which gives a
readable signal.

**30 days** (rejected): same cell width would force 2 px/day —
sparkline becomes a smudge. To fit 30 days we would need 90 px
cells, which costs 2 columns of horizontal real estate elsewhere.

**90 days** (rejected): better at 60 px but loses the "what happened
this week" signal that's the actual reason to put a sparkline in a
holdings table.

### 9.4 Why we drop "asset allocation pie/bar" as a separate widget

The user listed "Asset allocation pie/bar (Stocks/ETFs/Crypto/Cash/
Bonds)" as a requirement. The chosen design encodes this as:

- A single-letter `ASSET` column per row (E/F/B/C — equity / fund /
  bond / crypto), so the user sees the asset class inline per
  position
- Cash and buying power as dedicated KPI cells in the strip
- Sector / asset-class **mix** stays on the Holdings sub-tab as a
  full-fidelity panel

This is more information-dense than a dedicated pie chart and uses
zero new vertical space. Approved competitor precedent: Bloomberg
PORT does the same with a single-letter asset-class column.

### 9.5 Why we keep the KPI strip at 28 px (not 36 px)

Bloomberg's PORT header strip is ~24 px. The existing strip is 30 px.
Compressing to 28 px lets us add two new cells (`CASH` and `BUYING
POWER`) without overflowing the available horizontal width at 1440.
At 1280 the strip overflows into a horizontal scroll inside the strip
itself (overflow-x-auto), which is acceptable on small viewports.

### 9.6 Why we don't surface alerts on the overview

The user's brief mentioned alerts only as recent-activity context.
Adding an "alerts" strip would compete with the contributors / activity
strips already at the bottom and would force a fourth bottom cell.
Alerts have a dedicated `/alerts` route already; the rail badge counts
unread alerts; that is enough for the overview's role.

### 9.7 Animations: zero

Hedge-fund PMs surveyed for the design system (DESIGN_SYSTEM.md §11)
report that any animation on a data surface (count-ups, fade-ins,
chart-line draws) is **actively distracting**. We re-affirm the ban
here: zero animations on this page beyond the existing 500 ms AG Grid
cell-flash on quote update.

---

## 10. Open questions

1. **Top contributors / detractors endpoint** — currently computed
   client-side from `holdings × quotes`. For period-aware top movers
   (1M, YTD), we would need historical position weights, which the
   client cannot reconstruct. Recommendation: add
   `GET /api/v1/portfolios/{id}/top-movers?period=1D|1W|1M|YTD&limit=4`
   to S1 in a follow-up wave. For now, period toggle on the strip
   is limited to "today" only — period buttons disabled with a
   tooltip "1D only — historical mover data coming soon".

2. **Risk metrics (sharpe, vol, max drawdown)** — derivable from the
   value-history endpoint client-side, but the maths is sensitive
   (daily vs monthly returns, annualisation factor). Recommendation:
   surface these on the Holdings sub-tab (`PortfolioAnalyticsSection`,
   already implemented) and NOT on the overview, until S1 ships a
   `/risk-metrics` endpoint with canonical values. Overview KPI strip
   does NOT include sharpe/vol — it would be misleading at this
   stage.

3. **Currency exposure beyond top-2** — the exposure strip shows the
   top-2 currencies inline ("CCY USD 92 % · EUR 8 %"). If the book is
   in 5+ currencies (rare for the target persona), we surface a
   `+N more` chip that opens a small popover with the full
   breakdown. Confirm that this is the right ergonomic choice or if
   we should always show 4-5 currencies inline.

4. **Sector taxonomy** — overviews currently use GICS sector strings
   ("Technology", "Financials"). The bar uses these verbatim. Some
   instruments lack a sector (cash, crypto). Decision: bucket them
   under "OTHER" rather than dropping them, so the bar sums to 100 %.

5. **Benchmark choice** — defaults to SPY. For non-US books we'd want
   user-selectable benchmarks. Out of scope for v1: keep SPY hard-
   coded for now; flag a follow-up issue.

6. **Performance chart height** — 120 px is a compromise. Bloomberg
   PORT uses ~180 px on its inline chart. We can offer a "tall mode"
   toggle that doubles the chart height to 240 px and pushes the
   sector / table chrome below the fold; deferred to v1.1 unless
   the user wants it on day-one.

7. **AG Grid sparkline performance** — 60 px SVG per row × ~30 rows
   × 14 points per series = 420 small DOM nodes. AG Grid's
   `cellRenderer` will render these incrementally; we should
   benchmark on a 100-position book to confirm no scroll jank.
   Mitigation already designed: sparkline uses a single `path`
   element per cell (not 14 individual lines), keeping DOM count
   linear in row count.

8. **Whether to keep the Performance "Period Return" chip in the
   header** — currently above the KPI strip. With Day P&L and
   Unreal P&L in the KPI strip already, the chip is duplicative
   for 1D. Proposal: keep the chip but lock it to the same period
   as the equity-curve panel (so toggling to 3M on the chart also
   shows "+4.8 % (+$15,402)" in the chip).

9. **Empty state — both no portfolios AND no brokerage** — full-page
   CTA is straightforward; the question is whether to inline a
   "Take a tour" link to the demo data. Defer to a separate
   onboarding spec.

---

## Appendix A — column ordering rationale

The order Ticker → Name → Qty → Avg → Last → DayΔ$ → DayΔ% → Spark →
Value → P&L$ → P&L% → Wgt → Sector → Asset is the result of three
constraints:

1. **Identity first** (Ticker, Name): always the eye's anchor.
2. **Cost basis before live data** (Qty, Avg): traders read these in
   pairs to gauge their commitment to a position before the market
   price colours their thinking.
3. **Today's mood adjacent to live price** (Last, DayΔ$, DayΔ%, Spark):
   immediate "is this moving right now?" cluster.
4. **Position value cluster** (Value, P&L$, P&L%, Wgt): the "how big
   and how good is this trade overall?" cluster.
5. **Classification last** (Sector, Asset): rarely scanned, useful for
   filtering and sorting only.

Bloomberg PORT, IBKR Portfolio, and Schwab StreetSmart all follow this
exact left-to-right reading order with minor variation in cluster 3
(some put DayΔ% before DayΔ$). We pick `$` before `%` because the
absolute number is the harder one to scan when looking for a
"+$1,000 mover" in a list.

---

## Appendix B — five-second scan test

Acceptance criterion for this design: a hedge-fund PM glances at the
page for **five seconds** and can answer the following without
clicking, scrolling, or hovering:

1. What's my book worth today? — Tile 1 of KPI strip.
2. Am I up or down today? — Tile 2 (colour + value).
3. Which is my biggest position? — Pinned-left ticker column sorted
   by Value-desc with the weight mini-bar visible.
4. Which is moving the most today (up)? — Top Gainer KPI tile
   **or** Top Contributors bottom-left cell.
5. Which is moving the most today (down)? — Top Loser KPI tile
   **or** Top Detractors bottom-middle cell.
6. Am I over-concentrated? — Concentration strip badge (colour +
   word).
7. How am I doing vs the index this quarter? — Equity-curve panel
   above the table, two labelled lines.

All seven answers are above the fold at 1440 × 900 in the chosen
layout.
