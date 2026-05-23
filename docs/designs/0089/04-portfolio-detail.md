# Portfolio Detail (Holding Drilldown / Transactions / Analytics) — Design Spec (PRD-0089)

> **Scope split with `03-portfolio-overview.md`**: the overview agent owns the
> top-level summary (KPI strip, day P&L distribution, sector treemap, recent
> activity, equity-curve glance). This doc owns the three **drill-down surfaces**:
>
> 1. **Holding Detail panel** — opens when a row in the holdings table is
>    expanded; shows per-lot, cost-basis history, instrument-scoped tx, P&L
>    contribution chart, news for that holding
> 2. **Transactions ledger** — full filterable/exportable journal, 20px rows,
>    30+ rows visible above the fold at 1440×900
> 3. **Analytics tab** — TWR vs benchmark, risk metrics, attribution (sector /
>    asset-class / holding), drawdown chart
>
> The overview's `KPI strip` and `equity curve` are NOT redesigned here — this
> doc starts at the **Holdings table row click** and the **Analytics tab**.
> A new third top-level tab `Analytics` is proposed alongside `Holdings` and
> `Transactions` (the current `Watchlist` tab moves into the global shell rail
> watchlist, per `01-global-shell.md`).

---

## 1. Competitor research summary

### Bloomberg PORT (`{ticker} <Equity> PORT <Go>`)
- **Risk screen**: vertical strip with VaR, Tracking Error, Beta, Active Risk,
  Sharpe, Sortino, Information Ratio — every metric annotated with **lookback
  window** and **vs benchmark** in 8pt grey under the number. Steal: explicit
  lookback labels (e.g. `90D` / `vs SPY`) inline with the value, not in a
  legend below.
- **Attribution screen**: tabular Brinson decomposition (Allocation / Selection
  / Interaction effects), one row per sector. Total-effect column on the
  right colour-coded green/red. Steal: a single attribution table with
  **contribution-to-return** in basis points, sortable by `|contribution|`.
- **Drawdown chart**: underwater chart (always-negative line filled to zero
  with red gradient) below the equity curve, sharing the same x-axis.
- **Per-holding drill**: a side panel anchored to the right (not a modal),
  shows the security's contribution-to-portfolio-return over the same
  window, plus the holding's own micro equity curve. Critically: **does
  not navigate away** from PORT.

### TradingView — Paper Trading / Portfolio
- Time-period selector pill row (`1D 1W 1M 3M YTD 1Y 3Y 5Y All Custom`) is the
  reference pattern; we will mirror this exactly. Position-specific charts
  open in a slide-over panel from the right, not a route change.

### Interactive Brokers Portfolio Analyst (gold standard for retail-pro)
- **Performance section**: header strip with `Current Period Return`,
  `Cumulative Return`, `Benchmark Return`, `Excess Return`, `Beta`, `Alpha`,
  `Sharpe`, `Sortino`, `Information Ratio`, `Treynor` — all in one row of
  ~10 tiles. We will adopt the **10-tile risk row** at 11px text, splitting
  to two rows of 5 below `md` breakpoint.
- **Time Period Analyzer**: bar-chart per period (MTD / QTD / YTD / 1Y / 3Y /
  5Y / ITD) showing `Portfolio` vs `Benchmark` side-by-side. Steal — but
  use it inside the Analytics tab, not the overview.
- **Contribution to Return** table: top contributors and detractors, two-column
  layout `Best 10` / `Worst 10` with bps contribution and % weight. Steal
  exactly — most useful single attribution view.
- **Allocation drift** chart (current vs target weights). Out of scope for
  v1 (no target weights yet) but flag as deferred.

### Schwab Performance reporting
- "Performance by Account / Period / Asset Class" matrix view. Pattern we
  will not directly copy (multi-account is post-MVP) but the matrix-style
  cross-tab of period × asset-class is a candidate for v2.

### Public.com / Wealthfront — modern attribution
- Public's "Performance" tab is the inspiration for the **simple period bar
  chart** (TWR per period). Wealthfront's "Time-weighted return" disclosure
  inline next to the figure is the right pattern: ratings + tooltips
  explaining TWR vs MWR right where the user reads it, not in a help modal.

### IBKR transaction journal (reference for the ledger)
- Single scrollable table at 20-22px row height, 8-10 columns visible,
  sticky filter bar at the top, totals row at the bottom that updates with
  the filter. We already implement this — the redesign tightens density,
  adds running-balance and FX columns, and replaces the "search" textbox
  with a real `Cmd-F` overlay.

---

## 2. User intent for this page

### Primary persona
Active retail-to-pro investor managing a single-digit-millions portfolio
across 5–60 positions and 2–4 brokerage connections. Reviews the book
several times a week; checks transactions after each fill; runs a quarterly
performance review.

### Primary tasks (top 3)
1. **"Why did my portfolio move today?"** — open a single holding, see its
   intraday contribution, recent transactions, and any news that explains
   the move
2. **"Verify my realised P&L for Q1 tax filing"** — filter transactions by
   date and type=SELL, export CSV, cross-check the FIFO realised total
3. **"Did I outperform SPY YTD on a risk-adjusted basis?"** — open Analytics,
   read Sharpe / Sortino / Beta over YTD vs benchmark

### Secondary tasks
- Find every dividend received in 2026 → ledger filter
- Spot the worst drawdown of the last year and the trade that caused it →
  drawdown chart + contribution-to-return table
- Drill into AAPL's tax lots before a partial sale → Holding Detail panel
- Audit a missing transaction after a brokerage resync

### Anti-patterns (things this page must NOT become)
- A "stat museum" — every metric must be explained by lookback + benchmark
  next to it
- A graveyard of empty charts when the user has 7 days of history
- A modal-heavy UX — drilldowns are slide-overs/panels, not full-route
  navigations away from the ledger
- Mixed authority numbers — the client-side approximate realised P&L is
  banned from this page; we render the FIFO endpoint only

---

## 3. Backend data available

References `00-backend-data-inventory.md` (forthcoming) and the existing
`docs/services/portfolio.md` (S1) + `docs/services/api-gateway.md` (S9).

### Already exposed (verified in code)

| Field | Endpoint | Currently shown? | Where |
|------|---------|------------------|------|
| `total_realized` / `realized_long_term` / `realized_short_term` / `per_instrument` | `GET /v1/portfolios/{id}/realized-pnl` | Total only | KPI strip |
| Value-history points (date, value, cash) | `GET /v1/portfolios/{id}/value-history` | Partially (line chart only, no benchmark, no drawdown overlay) | Overview equity curve |
| `invested`, `cash`, `leverage`, `prices_stale`, `prices_as_of` | `GET /v1/portfolios/{id}/exposure` | Partially (single bar, no leverage / staleness pill) | Overview exposure cell |
| `drawdown_max`, `drawdown_current`, `volatility_annualized`, `sharpe`, `sortino`, `beta_vs_spy`, `data_quality.{status, n_returns, details}` | `GET /v1/portfolios/{id}/risk-metrics` | 5-tile strip only | Overview RiskMetricsStrip |
| FIFO lots (`open_date`, `qty`, `cost_per_share`, `days_held`, `is_long_term`, `unrealised_pnl`) | `GET /v1/portfolios/{id}/holdings/{instrument_id}/lots` | Yes (HoldingLotsPanel below table) | Overview Holdings tab |
| Transactions (date, type, asset_class, ticker, name, qty, price, fee, total, currency, amount; `description` not yet in response — see backend gap §3.7) | `GET /v1/transactions` (paginated, server-side filter via `X-Portfolio-ID`) | Yes — TransactionsTable | Transactions tab |
| Portfolio bundle (BFF) — portfolio + holdings + transactions + value_history in 1 round-trip | `GET /v1/portfolio/{id}/bundle` | Used to warm cache | Page mount |
| `concentration` (Top-N weights) | `GET /v1/portfolios/{id}/concentration` | Yes (overview ConcentrationStrip) | Overview |
| `performance` — `{return_pct, return_abs, covered_pct}` | `GET /v1/portfolios/{id}/performance` | **Not rendered yet** | — |

### Available but currently dropped / unused

| Field | Status | Proposed use in this design |
|-------|--------|----------------------------|
| `per_instrument` realised breakdown | Computed, returned, not displayed | Holding Detail panel — "Realised P&L (FIFO)" row + Analytics → Contribution table |
| `realized_long_term` / `_short_term` split | Computed, partly shown | Surface in Holding Detail panel header; surface ST/LT split inline in ledger summary row |
| `metadata.last_snapshot_at`, `metadata.next_scheduled_run_utc` | Available | Render as "as-of" pill on every analytics chart (data-freshness dot pattern) |
| `data_quality.details.zero_indices` (RiskMetricsStrip) | Available, only count shown | Show the dates with anomaly in a tooltip on the affected metric |
| `tx.amount` (broker-reported total) | Already used for DIV | Add `Cash Impact` column to ledger; lets the user see net cash flow including FX / fees independent of qty × price |
| `tx.description` (broker-reported notes, e.g. "Dividend Payment - AAPL") | **Not in `TransactionListItem` — must be threaded**: add `description: str \| None = None` to `services/portfolio/src/portfolio/api/schemas.py` `TransactionListItem` and `ListTransactionsUseCase` | Display as 9px subline under ticker when present |
| `tx.currency` (USD / EUR) | Filter only | Show currency chip in `Total` cell when ≠ portfolio currency |
| `tx.name` (instrument name) | **Already in `TransactionListItem`** as `name: str \| None` — frontend addition only | Add NAME column to ledger (frontend only, no backend change needed) |

### Data the user explicitly flagged as missing
None apply to drilldown surfaces — the AI-brief / company-narrative / sector
context concerns belong to `02-dashboard.md` and the instrument detail.

### Backend gaps surfaced by this design

These are **proposals** that may justify a new endpoint or a new field — flag
to the data-inventory agent for the master PRD.

1. **TWR per period** (`1D / 1W / 1M / 3M / YTD / 1Y / 3Y / 5Y / All / Custom`)
   — currently the frontend computes TWR client-side from value-history. We
   should expose `GET /v1/portfolios/{id}/twr?period=YTD&benchmark=SPY` so
   the API guarantees the TWR formula (Modified Dietz vs daily-weighted) is
   uniform across surfaces.
2. **Drawdown series** — `risk-metrics` returns `drawdown_max` / `drawdown_current`
   scalars but not the underwater series. Either compute client-side from
   value-history (acceptable for v1) or extend the endpoint with
   `?include=drawdown_series`.
3. **Attribution** — `Contribution to Return` per holding over a period is not
   yet exposed. Proposal: `GET /v1/portfolios/{id}/attribution?period=YTD`
   returning `{by_holding: [...], by_sector: [...], by_asset_class: [...]}`.
   For v1 we degrade gracefully: compute `weight × period_return` client-side
   from holdings + value-history.
4. **Per-holding value history** — needed for the holding detail panel's mini
   equity curve. Today we have only portfolio-level history. Proposal:
   `GET /v1/portfolios/{id}/holdings/{instrument_id}/value-history?days=90`.
   v1 fallback: synthesise from FIFO lots + S3 OHLCV.
5. **Running cash balance per transaction row** — useful for the ledger
   "Balance" column. Proposal: optional field on the transactions response
   when query param `?include=running_balance` is sent.
6. **`calmar`, `win_rate`, `alpha` for the Analytics risk sidebar** — the
   `/risk-metrics` endpoint currently returns: `drawdown_max`, `drawdown_current`,
   `volatility_annualized`, `sharpe`, `sortino`, `beta_vs_spy`. Three of the
   11 Analytics sidebar tiles (CALMAR, WIN RATE, ALPHA) have no backend source.
   These can all be computed server-side from data already fetched in the route:
   - `calmar` = `(mean(r) * 252) / abs(drawdown_max)` (annualised return ÷ abs(max DD))
   - `win_rate` = `count(r > 0) / count(r)` over the return series
   - `alpha` = `portfolio_annualised_return − spy_annualised_return` (aligned daily series)
   **This must be shipped as a backend pre-task before Wave G** to avoid rendering
   3 empty tiles in the sidebar on day one. The computation is ~30 lines in
   `services/api-gateway/src/api_gateway/routes/risk_metrics.py` using already-fetched data.
7. **`tx.description` threading** — the `Transaction` domain entity has
   `description: str | None` (broker-supplied notes) but it is absent from
   `TransactionListItem` in `services/portfolio/src/portfolio/api/schemas.py`.
   Backend pre-task: add `description` to the response schema and thread through
   `ListTransactionsUseCase` so the 9px note subline can render in the ledger.

---

## 4. Layout

### 4.1 Holding Detail panel (slide-over from right when row expanded)

```
PORTFOLIO ▸ HOLDINGS                         [Holdings] [Transactions] [Analytics]
─────────────────────────────────────────────────────────────────────────────────
┌────────────────────────────────────────────────────────────┬──────────────────┐
│ HOLDINGS TABLE (existing, kept) — 22px rows                │  AAPL  ✕         │
│ ─────────────────────────────────────────────────          │  Apple Inc.      │
│ ▾ AAPL    Apple Inc.    245    $187.32   +1.2% +$543.21    │  ────────────────│
│   MSFT    Microsoft     120    $412.05    -0.8%  ...       │  POS $45,894.40  │
│   NVDA    NVIDIA         80    $895.12   +2.1%  ...        │  COST $38,250.00 │
│   ...                                                       │  P&L  +$7,644.40 │
│   (≤22 rows visible above the fold)                         │       (+19.99%) │
│                                                             │  DAY  +$543.21   │
│                                                             │       (+1.20%)   │
│                                                             │                  │
│                                                             │  REALISED (FIFO) │
│                                                             │  ST  $1,250.00   │
│                                                             │  LT  $0.00       │
│                                                             │  ──────────────  │
│                                                             │  CONTRIB TO PORT │
│                                                             │  YTD  +124 bps   │
│                                                             │       (2.3% wt)  │
│                                                             │  ──────────────  │
│                                                             │  CONTRIB CHART   │
│                                                             │  ┌────────────┐  │
│                                                             │  │ mini line  │  │
│                                                             │  │ 90D, $-line│  │
│                                                             │  │ benchmark↓ │  │
│                                                             │  └────────────┘  │
│                                                             │  ──────────────  │
│                                                             │  TAX LOTS (FIFO) │
│                                                             │  OPEN  QTY  CST  │
│                                                             │  04-12  100 168  │
│                                                             │  06-18   80 192  │
│                                                             │  09-04   65 205  │
│                                                             │  ──────────────  │
│                                                             │  RECENT TX (8)   │
│                                                             │  06-18 BUY 80 …  │
│                                                             │  04-12 BUY 100…  │
│                                                             │  03-22 DIV $24…  │
│                                                             │  ──────────────  │
│                                                             │  NEWS (top 5)    │
│                                                             │  • Apple Vision..│
│                                                             │  • Q2 earnings.. │
│                                                             │  • ...           │
│                                                             │                  │
│                                                             │ [Open Instrument]│
└────────────────────────────────────────────────────────────┴──────────────────┘
KPI bar (overview owns)                                              prices_as_of
```

- Table region: **940px**; slide-over: **440px**; gutter: **8px**
- Slide-over is anchored to the right of the **page content area** (not the
  global rail). It overlays the table at z=20 but does NOT modal-trap focus
  — the user can keep scrolling the table.
- Closing the panel: click `✕`, press `Esc`, or click any other row.
- Cells visible above fold inside the slide-over (1440×900): **~32**
  (position header 6, realised block 3, contrib block 3, chart 0, lots
  6×4=24 cells, tx 8×3=24, news 5).
  Whole panel is independently scrollable.

### 4.2 Transactions ledger

```
PORTFOLIO ▸ TRANSACTIONS                     [Holdings] [Transactions·] [Analytics]
──────────────────────────────────────────────────────────────────────────────────
Filter row (h=28px):
[All][BUY][SELL][DIV][SPLIT][TRSF] From[YYYY-MM-DD]To[YYYY-MM-DD] Ticker[___] $Min[__] $Max[__] Currency[All▾] Search[Cmd-F]  Export CSV  Reset   413 / 1,287
──────────────────────────────────────────────────────────────────────────────────
DATE      TIME  TYPE  CLS  TICKER NAME              QTY      PRICE       TOTAL       FEE     FX     CASH IMPACT  BAL
─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
2026-05-19 14:32 BUY  EQT  AAPL   Apple Inc.        100   $187.32   $18,732.00    $0.99  1.0000   -$18,732.99   $124,3
2026-05-19 09:01 DIV  EQT  MSFT   Microsoft          —       —         $98.00     —     1.0000      +$98.00    $143,0
2026-05-18 15:45 SELL EQT  NVDA   NVIDIA              30   $895.12   $26,853.60    $0.99  1.0000   +$26,852.61   $142,9
2026-05-18 10:12 BUY  ETF  SPY    SPDR S&P 500       50   $521.40   $26,070.00    $0.99  1.0000   -$26,070.99   $116,0
2026-05-17 13:38 BUY  EQT  GOOGL  Alphabet            20   $172.50    $3,450.00    $0.99  1.0000    -$3,450.99   $142,1
...                                                                                                          (30+ rows)
─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
TOTALS (filtered)   BUY COST  $124,300.00   SELL PROCEEDS  $86,420.00   DIV INCOME  $1,240.00   FEES  $42.18   NET  -$36,681.82
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
Brokerage status (collapsible, 22px when collapsed):
▸ Brokerages: TastyTrade ✓ synced 2m ago · IBKR ✓ synced 6m ago · Robinhood — disconnected   [Connect]
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
```

- Row height: **20px** (down from 22 — drops one cell of vertical to fit
  more rows; `text-[11px]` body, `text-[10px]` headers).
- Columns visible: **13** (Date, Time, Type, Class, Ticker, Name, Qty,
  Price, Total, Fee, FX, Cash Impact, Bal). On `< xl` the `Name` and `Bal`
  columns collapse first; below `lg` the `FX` column drops; below `md`
  reverts to the existing 8-column form.
- Above-fold cell count at 1440×900: **header(1) + filter(1) + 32 rows × 13
  cols + totals(1) + brokerage(1) ≈ 420 cells**. Surpasses the 30-row
  target with room for the totals + brokerage status bar.
- Sticky regions: filter row (top), header row (below filter), totals row
  (bottom of the scroll area), brokerage status row (below totals).
- All numeric columns right-aligned with `font-mono tabular-nums`. Negative
  values get `text-negative`. The `Cash Impact` column is the canonical
  signed-cashflow column — never compute it from `Total`.

### 4.3 Analytics tab (new third tab)

```
PORTFOLIO ▸ ANALYTICS                        [Holdings] [Transactions] [Analytics·]
──────────────────────────────────────────────────────────────────────────────────
Period selector row (h=28px):  [1D] [1W] [1M] [3M] [YTD·] [1Y] [3Y] [5Y] [All] [Custom▾]   Benchmark [SPY▾]  as of 2026-05-19 16:00:00 UTC
──────────────────────────────────────────────────────────────────────────────────
PERFORMANCE (h=180px)                                                        Risk
┌─────────────────────────────────────────────────────────────────┐  ┌───────────┐
│  $128k                                                          │  │ TWR YTD   │
│        ↗ Portfolio                                              │  │ +12.84%   │
│       ╱                                                         │  │ SPY YTD   │
│      ╱  --- Benchmark (SPY)                                     │  │ +10.21%   │
│     ╱                                                           │  │ ALPHA     │
│    ╱_________________________________________________________   │  │ +2.63%    │
│   Jan        Feb        Mar        Apr        May (5 ticks)     │  │ BETA·SPY  │
└─────────────────────────────────────────────────────────────────┘  │ 1.08      │
DRAWDOWN (h=100px, shares x-axis)                                    │ SHARPE    │
┌─────────────────────────────────────────────────────────────────┐  │ 1.42      │
│ 0%─                                                              │ │ SORTINO   │
│   ▼─▼──▼─▼──▼──▼──▼──▼──▼──▼──▼──▼──▼──▼──▼──▼──▼──▼──▼─▼     │ │ 2.11      │
│         ▼▼   ▼  ▼          ▼      ▼     ▼          ▼          │  │ VOL ANN   │
│-5%─       ▼▼▼               ▼▼▼▼▼                              │  │ 18.4%     │
│             ▼▼  -8.2% peak DD                                  │  │ MAX DD    │
│-10%─                                                            │  │ -8.2%     │
└─────────────────────────────────────────────────────────────────┘  │ CALMAR    │
                                                                     │ 1.57      │
                                                                     │ WIN RATE  │
                                                                     │ 58%       │
                                                                     └───────────┘
──────────────────────────────────────────────────────────────────────────────────
PERIOD RETURNS                                       ATTRIBUTION (top contributors)
┌─────────────────────────────────────────────────┐  ┌──────────────────────────────┐
│       Port   Bench  Excess                      │  │ TICKER  WEIGHT  RET    CONTRIB│
│ 1D   +0.42% +0.31%  +0.11                       │  │ NVDA     12.4% +28.4% +335bps │
│ 1W   +1.12% +0.84%  +0.28                       │  │ AAPL     14.1% +14.2% +198bps │
│ 1M   +3.45% +2.18%  +1.27                       │  │ MSFT     11.0%  +9.1% +100bps │
│ 3M   +6.40% +5.10%  +1.30                       │  │ ...                          │
│ YTD +12.84%+10.21%  +2.63                       │  │ DETRACTORS                   │
│ 1Y  +24.10%+18.40%  +5.70                       │  │ TSLA      3.2% -18.4%  -58bps │
│ 3Y  +52.30%+41.10% +11.20                       │  │ ...                          │
│ ITD +91.40%+72.80% +18.60                       │  │                              │
└─────────────────────────────────────────────────┘  └──────────────────────────────┘
──────────────────────────────────────────────────────────────────────────────────
ATTRIBUTION BY SECTOR (h=140px)                  ATTRIBUTION BY ASSET CLASS (h=140px)
┌─────────────────────────────────────────────┐  ┌──────────────────────────────────┐
│ SECTOR             WT     RET    CONTRIB    │  │ CLASS    WT     RET    CONTRIB   │
│ Information Tech  42%   +18.4%  +772bps     │  │ Equity   88%  +14.1%  +1240bps   │
│ Consumer Disc     14%   +12.0%  +168bps     │  │ ETF       8%   +9.8%    +78bps   │
│ Communication     11%    +9.2%  +101bps     │  │ Cash      4%   +0.4%     +2bps   │
│ Health Care        9%    -2.4%   -22bps     │  │                                  │
│ Financials         7%    +4.1%   +29bps     │  │                                  │
│ ...                                         │  │                                  │
└─────────────────────────────────────────────┘  └──────────────────────────────────┘
```

- Grid: **12-col**; performance chart `col-span-9`, risk sidebar `col-span-3`,
  period-returns / attribution row `col-span-6 + col-span-6`, sector /
  asset-class row `col-span-6 + col-span-6`
- Above-fold cell count at 1440×900: **risk sidebar 11 tiles, performance + drawdown chart 1 each, period table 9 rows × 4 cols = 36, top contrib 10 rows × 4 cols = 40, attribution-by-sector 8 × 4 = 32, asset-class 4 × 4 = 16 ≈ 137 cells.** Heavily exceeds 40-60 density target.
- Density target overall (with overview): **130+** cells above fold; meets
  the §_INDEX "Bloomberg density" bar.

---

## 5. Component breakdown

All new components live under `apps/worldview-web/components/portfolio/` and
`apps/worldview-web/features/portfolio/components/`. File paths are absolute
relative to the repo root.

### 5.1 Holding Detail panel

| Component | File path | Line budget | Props | Renders |
|-----------|-----------|-------------|-------|---------|
| `HoldingDetailPanel` | `apps/worldview-web/features/portfolio/components/HoldingDetailPanel.tsx` | 240 | `{ portfolioId, holding, onClose, period }` | Slide-over chrome (header, close button, 440px width, escape handler), then composes the 7 sub-blocks below |
| `HoldingPositionHeader` | same file (private) | 60 | `{ holding, quote, holdingOverview }` | 6-row label/value block (POS / COST / P&L total / P&L %% / DAY / DAY %) |
| `HoldingRealizedRow` | `apps/worldview-web/components/portfolio/HoldingRealizedRow.tsx` | 80 | `{ portfolioId, instrumentId, period }` | Pulls `qk.portfolios.realizedPnl(portfolioId, period)`, filters to `per_instrument[instrumentId]`; shows ST/LT split |
| `HoldingContributionStat` | `apps/worldview-web/components/portfolio/HoldingContributionStat.tsx` | 80 | `{ portfolioId, instrumentId, period }` | Reads value-history + holdings; computes `(weight × period_return)` until backend attribution endpoint exists |
| `HoldingMiniContributionChart` | `apps/worldview-web/components/portfolio/HoldingMiniContributionChart.tsx` | 140 | `{ portfolioId, instrumentId, period }` | Recharts `LineChart` 120×60 baseline-zero, two lines (position, benchmark). Reuses recharts primitives from `EquityCurveChart` |
| `HoldingLotsPanel` (existing) | `apps/worldview-web/components/portfolio/HoldingLotsPanel.tsx` | (unchanged, +20 for narrower variant) | `{ portfolioId, holdings, quotes, variant?: "wide" \| "narrow" }` | Add `variant="narrow"` for 440px panel (drops Days col, condenses to 5 cols) |
| `HoldingInstrumentTxList` | `apps/worldview-web/components/portfolio/HoldingInstrumentTxList.tsx` | 100 | `{ portfolioId, instrumentId, limit=8 }` | 3-col compact list (date, type-badge, amount); links each row to the `Cmd-F`-filtered ledger |
| `HoldingNewsList` | `apps/worldview-web/components/portfolio/HoldingNewsList.tsx` | 80 | `{ instrumentId, limit=5 }` | Existing S9 `/v1/news/entity/{entity_id}` shaped to 5 rows; opens article in the chat-news drawer per `10-chat-ai.md` |

### 5.2 Transactions ledger (revised)

| Component | File path | Line budget | Props | Renders |
|-----------|-----------|-------------|-------|---------|
| `TransactionsTable` (revise existing) | `apps/worldview-web/components/portfolio/TransactionsTable.tsx` | (currently 735, target 600 after refactor) | unchanged + `enableCashImpact?: boolean`, `enableFxColumn?: boolean`, `enableRunningBalance?: boolean` | Adds 5 columns (Time, Class already present, Name, FX, Cash Impact, Bal), 20px rows. Splits column-config into `transaction-columns.tsx` per existing pattern |
| `TransactionsFilterBar` | `apps/worldview-web/components/portfolio/TransactionsFilterBar.tsx` | 220 | `{ value, onChange, tickerOptions }` | Extracts the inline filter block — kept as a sibling so the ledger body stays under the 600-line cap |
| `TransactionsTotalsRow` | `apps/worldview-web/components/portfolio/TransactionsTotalsRow.tsx` | 80 | `{ filtered }` | BUY / SELL / DIV / Fees / Net, single sticky bottom row, identical to existing visual treatment |
| `TransactionsBrokerageStatusBar` | `apps/worldview-web/components/portfolio/TransactionsBrokerageStatusBar.tsx` | 120 | `{ portfolioId }` | Pulls `/v1/brokerages/{user}` (existing), renders 22px collapsed row "▸ Brokerages: TastyTrade ✓ 2m ago · IBKR ✓ 6m ago". Expanded view opens existing `BrokerageConnectionCard` |
| `useTransactionsFilterState` | `apps/worldview-web/features/portfolio/hooks/useTransactionsFilterState.ts` | 80 | hook | Owns the 8 filter slots + `nuqs` URL state sync (round-trippable filter view per the existing tab pattern) |

### 5.3 Analytics tab (route stub exists — fleshing out `apps/worldview-web/app/(app)/portfolio/analytics/`)

| Component | File path | Line budget | Props | Renders |
|-----------|-----------|-------------|-------|---------|
| `AnalyticsTab` | `apps/worldview-web/features/portfolio/components/AnalyticsTab.tsx` | 200 | `{ portfolioId, period, benchmark, onPeriodChange, onBenchmarkChange }` | Composes the 6 sections; owns no data fetching beyond the period selector |
| `AnalyticsPeriodSelector` | `apps/worldview-web/components/portfolio/AnalyticsPeriodSelector.tsx` | 100 | `{ period, onChange, benchmark, onBenchmarkChange }` | TradingView-style pill row + benchmark dropdown + freshness pill |
| `AnalyticsPerformanceChart` | `apps/worldview-web/components/portfolio/AnalyticsPerformanceChart.tsx` | 220 | `{ portfolioId, period, benchmark }` | Recharts line, portfolio + benchmark series, 5 x-ticks max, value-history + S3 SPY OHLCV. Reuses `EquityCurveChart`'s tooltip primitives |
| `AnalyticsDrawdownChart` | `apps/worldview-web/components/portfolio/AnalyticsDrawdownChart.tsx` | 160 | `{ portfolioId, period }` | Recharts area baseline-zero, computed client-side from value-history (until backend endpoint); shares x-scale with the performance chart |
| `AnalyticsRiskSidebar` | `apps/worldview-web/components/portfolio/AnalyticsRiskSidebar.tsx` | 180 | `{ portfolioId, period, benchmark }` | 11-tile vertical strip — TWR, BenchTWR, Alpha, Beta, Sharpe, Sortino, Vol, MaxDD, Calmar, WinRate. Data source: `/risk-metrics` (drawdown/vol/sharpe/sortino/beta/calmar/win_rate/alpha added in backend gap §3.6) + `/value-history` (for client-side TWR). `/performance` is NOT used here (too coarse). |
| `AnalyticsPeriodReturnsTable` | `apps/worldview-web/components/portfolio/AnalyticsPeriodReturnsTable.tsx` | 140 | `{ portfolioId, benchmark }` | 9 rows × 4 cols (period × {portfolio, bench, excess}); client-side compute until backend `/twr` endpoint |
| `AnalyticsAttributionTable` | `apps/worldview-web/components/portfolio/AnalyticsAttributionTable.tsx` | 200 | `{ portfolioId, period, dimension: "holding" \| "sector" \| "asset_class" }` | Reusable shell; renders 10 rows of top contributors + 5 detractors when `dimension="holding"`, full breakdown for the other dimensions |

### 5.4 Reusable chart primitives

| Primitive | File path | Why share |
|-----------|-----------|-----------|
| `<TerminalLineChart>` | `apps/worldview-web/components/charts/TerminalLineChart.tsx` (new) | One config of recharts (axis colour, tooltip styles, font tokens) used by EquityCurve, AnalyticsPerformance, HoldingMiniContribution |
| `<TerminalAreaChart>` | same folder (new) | Drawdown + dashboard distribution |
| `<TerminalAxisTickFormatter>` | same folder (new) | Currency / percent / date tick formatters at `text-[9px]` mono |
| `<DataFreshnessPill>` | `apps/worldview-web/components/primitives/DataFreshnessPill.tsx` (existing — exported from `components/primitives/index.ts`) | Shared between every analytics surface — shows `as_of`, recency dot, click for source |

### 5.5 Density target verification

| Surface | Cells above fold (1440×900) | Target | Pass |
|---------|------------------------------|--------|------|
| Holdings tab + Detail panel | ~22 table rows × 10 cols + 32 panel cells ≈ 250 | 40+ | ✓ |
| Transactions ledger | 32 rows × 13 cols + totals 8 + brokerage 6 ≈ 430 | 40+ | ✓ |
| Analytics | 11 risk + 36 period + 40 contrib + 32 sector + 16 class + 2 charts ≈ 137 | 40+ | ✓ |

---

## 6. Visual spec

### Spacing (all values px)
- Slide-over panel width: **440**
- Slide-over inner padding: **8** (horizontal) / **6** (vertical)
- Block separator inside panel: 1px hairline `border-border`; **6px** vertical gap above/below
- Transactions row height: **20** (down from 22); header row **22**; filter row **28**; totals row **24**
- Transactions column gap: **8** between cells (px-2 each side)
- Analytics tab grid gap: **8** (matches existing portfolio analytics section)
- Analytics performance chart height: **180**; drawdown chart **100**; sidebar tile **40** each (11 tiles → ~440 stack)

### Typography (from shared scale)
- All numbers: `font-mono tabular-nums`
- Header column labels: `text-[10px] uppercase tracking-[0.08em] text-muted-foreground`
- Body cells: `text-[11px]`
- Panel section titles ("TAX LOTS", "RECENT TX"): `text-[10px] uppercase tracking-[0.06em]`
- Panel position headline (e.g. `$45,894.40`): `text-[14px]` — one-off hero allowed by §_INDEX
- Risk sidebar tile value: `text-[13px]` (one notch below the strip's 14 because we have 11 tiles vertically — tighter fit)
- Period-returns / attribution table cells: `text-[11px]`

### Colors (no new tokens)
- Positive deltas: `text-positive` (#00D26A)
- Negative deltas: `text-negative` (#FF3B5C)
- Neutral text: `text-foreground`
- Secondary labels: `text-muted-foreground`
- Active tab / active period pill border: `border-primary` + `text-primary`
- Drawdown chart fill: `text-negative` at 20% opacity (`bg-negative/20`)
- Performance benchmark line: 1.5px dashed `text-muted-foreground`
- Performance portfolio line: 1.5px solid `text-primary`

### Border / radius / animations
- Every panel: 1px `border-border`, `rounded-[2px]`
- No shadows, no elevation cards
- No animations on data changes; panel slide-over uses 120ms ease-out (only the panel, never the data)
- Tooltip on charts: 8px padding, `bg-card`, 1px `border-border`, `text-[11px]`

### Column widths (transactions ledger, when all columns shown)
- DATE 88, TIME 60, TYPE 48, CLASS 48, TICKER 64, NAME 180 (truncate), QTY 80, PRICE 80, TOTAL 100, FEE 60, FX 60, CASH IMPACT 110, BAL 100 → 1078px content; ledger gets a horizontal scroll on narrow viewports (acceptable for a finance tool)

---

## 7. Interaction model

### Hotkeys (scoped to portfolio detail)
- `Esc` — close the holding detail panel (when open)
- `/` — focus the transactions filter search
- `Cmd/Ctrl+F` — same as `/` (advisory overlay; ignored if browser captures)
- `1` / `2` / `3` — switch to Holdings / Transactions / Analytics tab (matches `01-global-shell.md` numeric-tab pattern)
- `j` / `k` — next / previous transaction row (when ledger has focus)
- `e` — open Export CSV dialog
- Period pills accept arrow keys when focused

### Hover behaviour
- Holdings row hover: `bg-muted/20`; click toggles the detail panel (row 1 implicit when panel mounts)
- Transactions row hover: `bg-muted/20` + a `+` button appears at the right edge to copy the row as JSON
- Charts hover: crosshair + tooltip; tooltip locks on `Shift+hover` (matches existing chart pattern)

### Click handlers
- Holding row click → toggle detail panel for that instrument (single-select; clicking the open row closes it)
- "Open Instrument" CTA at the bottom of the panel → `router.push(/instrument/{slug})`
- Transactions row click → no navigation (avoid surprise nav inside a ledger); two-finger / `Enter` to open the matching holding detail panel anchored to the related instrument
- Period pill click → updates `nuqs` URL state `?period=YTD`; benchmark dropdown → `?benchmark=SPY`
- Attribution table row click → opens the Holding detail panel for that ticker

### Loading, error, empty states

| Surface | Loading | Error | Empty |
|---------|---------|-------|-------|
| Holding Detail panel | 6 stacked skeleton blocks (header / lots / tx / news) at the same heights as data | "Couldn't load this holding. [Retry]" inline, panel stays open | `holdings.length === 0` → panel never opens; if a single block fails it falls back to "—" |
| Tax lots block | 4 × `h-[22px]` skeletons | "Lot history unavailable. (For SnapTrade-synced positions, lots are derived from the tx stream — fills before the first sync may be absent.)" | "No open lots — position fully closed or never opened via recorded transactions." |
| Recent tx block | 8 × 20px skeletons | "Couldn't load activity for this holding." | "No transactions recorded for this holding yet." |
| Holding news | 5 × 16px skeletons | "News feed temporarily unavailable." | "No news in the last 14 days." |
| Transactions ledger (no brokerage connected) | n/a | n/a | Full-bleed empty state: "No transactions yet. [Connect a brokerage] · [Add a position manually]" — CSV import removed (feature not scoped for v1; a dead CTA damages trust) |
| Transactions ledger (filters strip all rows) | n/a | n/a | "No transactions match the current filters. [Clear filters]" inline inside the table body |
| Analytics — TWR chart | full-height `h-[180px]` skeleton | "Couldn't load performance series." inline | "Performance metrics will appear after ~10 trading days of snapshots — currently N/10." (mirrors `RiskMetricsStrip` data-quality caption) |
| Analytics — Risk sidebar | 11 × tile skeleton | tile shows "—" with tooltip | sidebar still renders with all values as "—" so layout is stable |
| Analytics — Attribution | 10-row skeleton | inline error | "Attribution requires ≥30 days of history." |
| Analytics — Drawdown | 100px skeleton | inline error | "No drawdowns recorded yet." (rare — only for brand-new portfolios) |

### Accessibility
- Slide-over panel: `role="dialog"` `aria-modal="false"` (NON-modal — does not steal focus from the table)
- Each analytics tile: `aria-label` like `Sharpe ratio: 1.42` (matches existing RiskMetricsStrip F-211 pattern)
- Period pills: `role="tablist"` / `role="tab"`, arrow-key navigation
- All charts: `role="img"` + `aria-label` describing the series + period
- Transactions table: `<table>` with `<thead>`/`<tbody>`/`<tfoot>` so screen readers announce the totals row

---

## 8. Data fetching

### Existing query keys (re-use)
- `qk.portfolios.holdings(portfolioId)` — holdings table
- `qk.portfolios.holdingsQuotes(portfolioId)` — live prices
- `qk.portfolios.transactions(portfolioId, filters?)` — ledger
- `qk.portfolios.valueHistory(portfolioId, period)` — performance chart
- `qk.portfolios.exposure(portfolioId)` — overview (kept)
- `qk.portfolios.riskMetrics(portfolioId)` — risk sidebar
- `qk.portfolios.realizedPnl(portfolioId, period)` — KPI + per-instrument detail

### Existing query keys to reuse (already in `apps/worldview-web/lib/query/keys.ts`)
```ts
// Analytics sector attribution table — use existing endpoint + key:
qk.portfolios.sectorAttribution(portfolioId)   // → GET /v1/portfolios/{id}/sector-attribution
// Performance for the per-period returns table (existing, takes a period param):
qk.portfolios.performance(portfolioId, period) // → GET /v1/portfolios/{id}/performance (1D/1W/1M only)
```

### New query keys (propose adding to `apps/worldview-web/lib/query/keys.ts`)
```ts
holdingLots: (portfolioId, instrumentId, currentPrice?) =>
  ["portfolios", "detail", portfolioId, "holding-lots", instrumentId, currentPrice] as const,
holdingTx: (portfolioId, instrumentId) =>
  ["portfolios", "detail", portfolioId, "holding-tx", instrumentId] as const,
holdingValueHistory: (portfolioId, instrumentId, period) =>
  ["portfolios", "detail", portfolioId, "holding-value-history", instrumentId, period] as const,
// NOTE: sector attribution uses qk.portfolios.sectorAttribution (existing), not this key.
// "attribution" key below is only for the per-holding/asset-class breakdown (client-side v1):
attribution: (portfolioId, period, dimension) =>
  ["portfolios", "detail", portfolioId, "attribution", period, dimension] as const,
twr: (portfolioId, period, benchmark) =>
  ["portfolios", "detail", portfolioId, "twr", period, benchmark] as const,
brokerageStatus: (userId) =>
  ["brokerages", userId, "status"] as const,
```

### staleTime per resource
| Resource | staleTime | Reason |
|----------|----------|--------|
| `holdings`, `holdingsQuotes` | 30s | already live-refresh on overview |
| `transactions` | 60s | append-only outside of sync events |
| `value-history` | 60s | daily snapshots — intraday changes are noise |
| `risk-metrics` | 5min | recomputed once per snapshot (calmar/win_rate/alpha added to same endpoint) |
| `performance` (1D/1W/1M only — period returns table, not Analytics sidebar) | 5min | matches gateway `Cache-Control: max-age=300` |
| `realized-pnl` | 5min | matches gateway `Cache-Control: max-age=300` |
| `holding-lots` | 60s | derived from transactions; same cadence as tx |
| `holding-tx` | 60s | shares cache with `transactions` once we filter in-memory |
| `attribution`, `twr` | 5min | period-bucketed; not interactive |
| `holding-value-history` | 60s | mirrors portfolio-level cadence |
| `brokerages` | 60s | sync state heartbeat |
| `news/entity/{id}` | 5min | matches existing news cache |

### Dedup opportunities (cross-page reuse)
- `qk.portfolios.holdings(id)` already used by Dashboard PortfolioSummary widget — keep as canonical.
- `qk.portfolios.valueHistory(id, "3M")` is queried twice today (`PortfolioAnalyticsSection.tsx:78` and `EquityCurveChart.tsx`). The Analytics tab and the Drawdown chart will share the same cache entry — both call with identical `(portfolioId, period)`.
- New `holdingLots` key matches the existing endpoint key string used by `HoldingLotsPanel.tsx:77`; the panel's wide variant and the slide-over's narrow variant share one in-flight request.
- `news/entity/{id}` is already used on the instrument page; the holding-news block does not duplicate.

### Cross-mutation invalidations
- `addTransaction()` invalidates: `qk.portfolios.transactions`, `qk.portfolios.holdings`, `qk.portfolios.valueHistory`, `qk.portfolios.realizedPnl`, `qk.portfolios.riskMetrics`, plus all new `holdingLots/holdingTx/attribution/twr` for the affected portfolio.
- Tab switch alone is NOT a fetch trigger — cached entries serve the analytics tab instantly when navigating from Holdings.

---

## 9. Tradeoffs & decisions

### Decision 1: slide-over panel vs full-page route for holding detail
- **Alt A (chosen)**: 440px slide-over anchored to the right of the table
- **Alt B**: dedicated route `/portfolio/{id}/holdings/{instrument_id}`
- **Why A wins**: a position drill is a high-frequency, glance-level action.
  Pushing a route loses the table context, breaks the back-button on
  brokerage sync, and prevents quick scanning across holdings. The
  slide-over keeps both visible simultaneously, matches Bloomberg PORT's
  side-panel pattern, and avoids a double round-trip (route push +
  page-level data refetch).
- **Cost of A**: the panel state lives in `nuqs` URL (`?holding=AAPL`) so it
  round-trips deep links. Slightly more complex than a route, but already
  the pattern we use for `?tab=...&period=...`.

### Decision 2: client-side TWR vs new backend endpoint
- **Alt A (chosen for v1)**: compute TWR client-side from value-history
- **Alt B**: ship `GET /v1/portfolios/{id}/twr` first
- **Why A**: value-history is already loaded for the equity curve; reusing
  the data avoids a new round-trip and removes the "first-load empty TWR"
  flash. The formula (Modified Dietz over snapshot intervals) is well-known
  and small.
- **Cost of A**: the canonical TWR figure is owned by the frontend until
  backend ships. **Flag in PR**: file a follow-up to migrate once
  `/twr` endpoint exists so the same authority pattern as `/realized-pnl`
  applies (no client-side approximation when an authoritative endpoint
  exists).

### Decision 3: 20px transaction rows vs 22px
- **Alt A (chosen)**: 20px rows, 11px text, 10px headers
- **Alt B**: keep 22px rows (current)
- **Why A**: drops one row per page worth of vertical clutter. Bloomberg
  Terminal and Finviz both ship 18–20px rows for journal/screener
  surfaces. We've already validated 22px on holdings; transactions is a
  pure scan list (no rich content) and tolerates one notch tighter.
- **Cost of A**: hover targets shrink to 20px (still ≥ Apple's 16pt
  minimum guideline). Tested OK at 1440×900 + zoom 100%.

### Decision 4: 11-tile risk sidebar vs the existing 5-tile strip
- **Alt A (chosen)**: 11 vertical tiles in a 200px column
- **Alt B**: two stacked 5-tile horizontal strips
- **Why A**: lets the chart use the full 720px chart-area width while still
  showing every IBKR-equivalent metric. The vertical strip also reads
  scanning top-to-bottom (label / value / sub-label) without competing
  with the chart's left-to-right scan.
- **Cost of A**: under `md` we lose the chart width; the sidebar collapses
  beneath the chart as a 2-row × 5-tile strip plus a single Win-Rate tile
  on its own line.

### Decision 5: drawdown chart computed client-side vs server-side
- **Alt A (chosen)**: client-side from value-history
- **Alt B**: extend `/risk-metrics` with `?include=drawdown_series`
- **Why A**: zero new endpoint complexity; the series is `1 - value/maxToDate`
  rolled in O(n) over the already-cached value-history.
- **Cost of A**: ~50 lines of compute live on the frontend. Acceptable.

---

## 10. Open questions

1. ~~**Benchmark choice**~~ **RESOLVED (v1)**: Benchmark dropdown is SPY-only for
   v1; the `/risk-metrics` endpoint is hard-coded to SPY. Render the dropdown
   disabled with a "SPY" label and `title="Additional benchmarks in a future release"`.
   QQQ / IWM / custom ticker deferred to a future wave.
2. ~~**Per-period excess return colouring**~~ **RESOLVED**: Colour excess green/red
   (`text-positive` / `text-negative`). Bloomberg pattern; consistent with every
   other delta cell on the page.
3. ~~**Holding contribution chart series**~~ **RESOLVED**: Show
   *contribution-to-portfolio* (IBKR-style) — most useful in context; the user
   is looking at the holding's impact on the portfolio, not its absolute price.
4. ~~**Custom period picker**~~ **RESOLVED**: Use shadcn `<Popover>` + `<Calendar>`
   component (already used in the screener date filters). Avoid the plain
   `<input type="date">` pair — it has poor mobile support.
5. ~~**Running balance accuracy**~~ **RESOLVED**: Ship the BAL column with an
   inline tooltip: "Approximate — excludes FX revaluation and corporate actions
   until backend `/transactions?include=running_balance` support lands."
6. ~~**Attribution time aggregation**~~ **RESOLVED (v1)**: Client-side v1 uses
   simple `weight × period_return` (buy-and-hold attribution). Acceptable for
   v1. Flag in PR: migrate to TWR-weighted attribution once the backend
   `/attribution` endpoint lands so closed positions are handled correctly.
7. ~~**Empty-brokerage CSV import**~~ **RESOLVED**: Removed `[Import CSV]` CTA from
   the empty state — no importer exists and a dead CTA damages trust more than a
   shorter empty state. Out of scope for v1. See §7 loading/error/empty states.
8. ~~**Slide-over on `< lg` viewports**~~ **RESOLVED**: Full-screen modal below
   `lg` breakpoint (option a). Feels native on tablet/mobile; avoids the
   table-behind-panel usability problem on smaller screens.
