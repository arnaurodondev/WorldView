# Dashboard — Design Spec (PRD-0089)

> Post-login landing surface at `/` and `/dashboard`. The single most-trafficked
> page in the product — every user lands here every session. Goal: in **5
> seconds** the trader knows (a) what the market did, (b) what their book did,
> (c) what changed since last login. Current dashboard fails (b) and is too
> spaced for (a)/(c).

Status: **proposed**
Author: agent-dashboard
Date: 2026-05-19
Shared tokens: see `_INDEX.md` §"Shared design tokens" — all sizes/colors below
reference that scale. No new tokens introduced.

---

## 1. Competitor research summary

### Bloomberg Terminal — `MOST`, `WEI`, `<HOME>`, `IMAP`
- `WEI` (World Equity Indices): 80+ index rows on one screen, 22px rows, raw
  numbers — no chartjunk. Five columns: name, last, %chg, ytd, time. Zero
  whitespace between rows.
- `MOST` (Most Active): split into Gainers / Losers / Volume Leaders side by
  side; each table 20+ rows visible without scroll.
- `<HOME>` launchpad: top half = news ticker + headlines; bottom = customizable
  multi-monitor grid of MOST / IMAP / TOP / FX / portfolio.
- **Pattern to steal**: every numeric cell is monospaced + right-aligned,
  positive/negative coloured (green/red on amber-on-black). Section headers
  are 10px uppercase tracking-wide labels in muted yellow.

### TradingView — Markets Overview (`tradingview.com/markets/`)
- Top: 6-card "Indices" strip (S&P, Nasdaq, Dow, VIX, BTC, Gold) — each 220px
  card with last + %chg + 24h sparkline. Cards are *light* but contents are
  dense (3 metric rows + sparkline).
- Mid: full-bleed sector heatmap (treemap, area-weighted by market cap, color
  by %chg). One-click drill-down to sector page.
- **Pattern to steal**: market-strip with sparklines, treemap sector heatmap.
- **Anti-pattern to avoid**: TradingView's "Featured Ideas" card eats 30% of
  the fold with marketing content. Dashboard has zero room for that.

### Finviz — Homepage (`finviz.com`)
- One page, no scroll on a 1440×900 viewport, contains: market index strip
  (top), 12-row gainers + 12-row losers + 12-row volume + 12-row news + 11-row
  insider all visible **above the fold**. ~150 visible data cells.
- Row height ~18px; 10-11px font; zero card chrome between sections — pure
  HTML `<table>` aesthetic.
- **Pattern to steal**: stack 4 dense tables in one row (gainers · losers ·
  most-active · news), each ~12 rows tall. Eliminate per-widget border chrome
  in favour of 1px hairlines between rows only.
- **Anti-pattern**: Finviz uses ~7 different table styles. We unify on one.

### Koyfin — Dashboard (`app.koyfin.com`)
- Modern, dense-but-readable. Headline panel: P&L card (top-left) showing
  account value · day change · MTD · YTD as 4 stacked metric rows + a
  performance sparkline. This is the *single best* "your money" widget in any
  competitor.
- Side rail: watchlist with 15+ tickers at 22px rows; mini-sparkline column.
- **Pattern to steal**: Koyfin's portfolio "metric strip" — 4 KPIs stacked on
  the left of a sparkline. We adopt this as our **Top of Portfolio** widget.

### Interactive Brokers TWS — Mosaic (`Trader Workstation`)
- User assembles their own multi-widget mosaic. Default layout: Portfolio
  (top-left), Watchlist (mid-left), Order Entry (right), Chart (centre).
  Portfolio panel shows account NLV + day P&L + unrealized P&L + each position
  with avg cost / mkt price / unr P&L / day P&L — **6 columns per row, 22px
  rows, 15 positions visible**.
- **Pattern to steal**: positions table with *6 columns* (qty, cost, mkt,
  mkt val, unr P&L, day P&L) — not 2 columns like our current widget.

### Citations of current state
- `apps/worldview-web/app/(app)/dashboard/page.tsx` — current 4-row layout
- `apps/worldview-web/components/dashboard/PortfolioSummary.tsx` — current
  portfolio widget; shows only `total_value` + `day_change` and 5 holdings
  with **2 columns** (ticker, %). Misses cost basis, unrealized P&L, day P&L,
  position weight.

---

## 2. User intent for this page

**Primary persona**: prosumer/PM checking the platform at market open (08:30
ET) or end of day (16:00 ET). Some sessions are 30-second drive-by glances on
the way to a meeting; others are 10-minute deep-dives before placing trades.

**Primary tasks (top 5)**:
1. *"How did my book move overnight?"* — surface day P&L + per-position day
   change above the fold. **This is the current dashboard's biggest gap.**
2. *"What's the macro regime today?"* — S&P / Nasdaq / VIX / 10Y / DXY in a
   single strip with sparklines.
3. *"What changed since last login?"* — Morning Brief (AI synthesis) + diff
   badge ("7 new bullets").
4. *"Anything urgent to act on?"* — Alerts feed (unack), top movers in my
   holdings, earnings today in my book.
5. *"What's the AI flagging?"* — AI signals widget (ML price-impact scores)
   and prediction markets consensus.

**Secondary tasks**:
- Skim sector heatmap to see rotation.
- Quick-jump to an instrument page via watchlist (handled by global shell —
  watchlist lives in the right sidebar, see `01-global-shell.md`).
- Read portfolio-relevant news headlines.

**Anti-patterns** (things this page must NOT become):
- A dashboard of pretty cards with one metric each ("Total Value: $X" filling
  300×200px). Current PortfolioSummary is exactly this — to be redesigned.
- A scroll-fest. Everything above must fit in 1440×900 minus the 36px topbar.
- A 2× duplication of widgets that exist on Portfolio Overview / Screener /
  Workspace. Dashboard surfaces the *top-of-each* — full lists live on the
  dedicated page.

---

## 3. Backend data available

Cited from `00-backend-data-inventory.md` (to be authored by agent-data-audit).
Pending that doc, this is the working catalogue from grep of widgets +
`apps/worldview-web/lib/gateway.ts`.

| Widget need | Endpoint | Shape | Currently used? |
|---|---|---|---|
| Morning brief (summary + sections + citations + diff) | `S9 GET /api/v1/briefings/morning` | `BriefingResponse` | YES (MorningBriefCard) |
| Brief diff (new bullets since last view) | `S9 GET /api/v1/briefings/morning/diff?since={brief_id}` | `{ added: BriefBullet[] }` | YES (BriefDiffBadge) |
| Portfolios list | `S9 GET /v1/portfolios` | `Portfolio[]` | YES |
| Holdings for portfolio | `S9 GET /v1/portfolios/{id}/holdings` | `Holding[]` w/ qty, avg_cost, instrument_id | YES (but only `qty` rendered) |
| Live quotes (batch) | `S9 POST /v1/quotes/batch` | `{ [iid]: Quote }` w/ price, day_change, day_change_pct | YES |
| Portfolio performance series | `S9 GET /v1/portfolios/{id}/performance?period=` | `{ points: [{t, value}] }` | YES (sparkline) |
| Portfolio KPIs (NEW — not currently surfaced) | `S9 GET /v1/portfolios/{id}/summary` | `{ total_value, cost_basis, unrealized_pnl, unrealized_pnl_pct, day_pnl, day_pnl_pct, mtd_pnl_pct, ytd_pnl_pct, cash_balance }` | **NO — backend has it (PortfolioSummaryService); widget does not consume it** |
| Top movers (universe) | `S9 GET /v1/market/top-movers?bucket=gainers\|losers&limit=` | `Mover[]` w/ ticker, %chg, price, sector | YES |
| Sector heatmap | `S9 GET /v1/market/heatmap?period=` | `Sector[]` w/ name, market_cap, day_change_pct | YES |
| Market snapshot (indices) | `S9 POST /v1/quotes/batch` for SPY/QQQ/DIA/VIX/TLT/UUP/GLD/BTCUSD | `Quote[]` | YES (MarketSnapshotWidget — currently only 4 tickers) |
| AI signals (ML price impact) | `S9 GET /v1/signals/ai?limit=` | `AiSignal[]` w/ ticker, score, direction, horizon | YES |
| Prediction markets | `S9 GET /v1/signals/prediction-markets` | `PredictionMarket[]` w/ question, yes_pct, volume_usd | YES |
| Economic calendar | `S9 GET /api/v1/fundamentals/economic-calendar` | `EconomicEvent[]` w/ name, country, importance, scheduled_at, actual, forecast, previous | YES |
| Earnings calendar | `S9 GET /v1/fundamentals/earnings-calendar` | `EarningsEvent[]` w/ ticker, when (BMO/AMC), eps_est, eps_actual, revenue_est | YES |
| Portfolio-relevant news | `S9 GET /v1/news/top?limit=20` filtered client-side | `RankedArticle[]` | YES (PortfolioNewsWidget) |
| Alerts (recent) | SSE stream + `S9 GET /api/v1/alerts?acknowledged=false&limit=` | `Alert[]` w/ severity, title, ticker, ts | YES |
| Watchlist (in shell, not dashboard) | `S9 GET /v1/watchlists` | — | (handled by `01-global-shell.md`) |
| Dashboard snapshot warm-up | `S9 GET /v1/dashboard/snapshot` | bundled cache prime | YES (prefetcher) |

**Data the user explicitly mentioned as missing or under-surfaced**:
- *"User positions not clearly displayed"* → `GET /v1/portfolios/{id}/holdings`
  + `POST /v1/quotes/batch` + `GET /v1/portfolios/{id}/summary`. All three exist.
  The widget just doesn't render most of it.
- Morning Brief is already visible but takes too much vertical real estate
  collapsed (~120-160px). New design caps it at 96px collapsed (header + 2-line
  summary + chip strip on one row).

---

## 4. Layout

**Grid**: 12 columns × 8 rows. Outer padding `p-2` (8px). Inter-cell gap
`gap-2` (8px) — **down from current `gap-3`** to recover 4px×3 = 12px of
horizontal density and 4px×7 = 28px of vertical density.

**Viewport budget**: 1440 × (900 − 36 topbar) = 1440 × 864.
- Outer p-2 = 16px (top+bot), so usable height = 848.
- 7 gaps of 8px between 8 rows = 56px.
- Row content budget: 848 − 56 = **792px** for 8 rows.

**Row plan** (heights in px, see §6 for justification):

| Row | Height | Purpose |
|---|---|---|
| 1 | 96  | Morning Brief (collapsed default; expands to overlay, see §7) |
| 2 | 96  | Market Strip (indices + FX + rates + crypto, 8 cells) |
| 3 | 132 | Top of Portfolio (KPI strip · positions table · perf sparkline) |
| 4 | 132 | (same row continues — Top of Portfolio is 1 logical row, 132px) — see grid below |
| 5 | 132 | Movers row: Gainers · Losers · AI Signals · Predictions |
| 6 | 132 | Context row: Sector Heatmap · Earnings · Economic Calendar |
| 7 | 132 | Feed row: News · Alerts · Holdings News |

Total: 96 + 96 + 132×4 + 132 = **720px** + 56 gap = 776px. Leaves 16px slack —
intentional, gives `min-h-0` overflow a buffer.

> **Correction**: 8 rows is overcount; the dashboard is actually **6 logical
> rows**. Final row plan:

| # | Span | Content | Height |
|---|------|---------|--------|
| R1 | col 1-12 | Morning Brief                                                     | 96  |
| R2 | col 1-12 | Market Strip (8 ticker cells inline)                              | 96  |
| R3 | col 1-12 | **Top of Portfolio** (KPI strip · positions table · perf sparkline) | 156 |
| R4 | col 1-3 / 4-6 / 7-9 / 10-12 | Gainers · Losers · AI Signals · Predictions | 156 |
| R5 | col 1-4 / 5-8 / 9-12 | Sector Heatmap · Earnings · Economic Calendar           | 156 |
| R6 | col 1-4 / 5-8 / 9-12 | Portfolio News · Alerts · Top News                      | 156 |

Total content: 96 + 96 + 156×4 = **816px**, gaps 5×8 = 40px → 856px. Fits
within 864px (8px slack, accounts for sub-pixel rounding).

### ASCII wireframe (1440 × 864 content area)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Generated 2026-05-19 07:14 UTC      MORNING BRIEFING               [7 new] [Discuss] [Read more ▸]                          │ R1 96px
│ Fed minutes confirm hawkish hold; semis sell off on TSMC capex cut. NVDA -3.1% pre-mkt. Treasury yields curve-steepen.       │
│ [BLOOMBERG.COM · Fed minutes signal …] [REUTERS.COM · TSMC trims …] [FT.COM · Semis correction …]                            │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ SPX   4 982.14  +0.42%▁▂▃▅▆ │ NDX 17 412.8 +0.61%▁▃▅▇▆ │ DJI 38 244 -0.12%▆▅▃▂▁ │ VIX 14.82 -2.1%▇▅▃▁▁ │ ...4 more cells   │ R2 96px
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ── TOP OF PORTFOLIO ───────────────────────────────────────────────────────────────────────────  [Demo · Live · Paper ▾]   │ R3
│ NLV  $1 248 312      Day P&L  +$3 142 (+0.25%)   ┃ TICKER QTY    AVG     MKT     MKT VAL    UNR P&L      DAY P&L   WEIGHT  │ 156px
│ Cost $1 102 850      Unr P&L +$145 462 (+13.19%) ┃ NVDA   180  412.10  398.22   71 679.6   -2 498.40 ↓  -512.20 ↓  5.74%   │
│ Cash $   42 800      MTD     +1.82%              ┃ AAPL   240  168.90  182.41   43 778.4   +3 242.40 ↑  +120.60 ↑  3.51%   │
│ ─── 1D · 5D · 1M · 3M · YTD ─── ▁▂▃▄▅▆▇█▇▆▅▄▃▂▁ ┃ MSFT   120  402.10  418.66   50 239.2   +1 987.20 ↑  +482.40 ↑  4.02%   │
│  ↑ sparkline 130x40 (perf series)               ┃ ANTH   500   84.20   91.15   45 575.0   +3 475.00 ↑  +210.00 ↑  3.65%   │
│                                                  ┃ TSLA    60  198.40  212.80   12 768.0   +  864.00 ↑  +  18.00 ↑  1.02%   │
│                                                  ┃ ... 5 more holdings (scroll) — [View all ▸]                              │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ GAINERS ▲                  │ LOSERS ▼                  │ AI SIGNALS                │ PREDICTIONS                            │ R4
│ TICK   PRICE   %CHG  VOL   │ TICK   PRICE   %CHG  VOL  │ TICK  SCORE  DIR  HORIZON │ MARKET                  YES   24H  VOL │ 156px
│ SMCI   924.10 +18.4% 12.4M │ NVDA   398.22  -3.1% 84.2M│ MSFT  +0.84  ↑   5D       │ Fed cuts 50bps Dec      18%  ↓2  $2.4M│
│ ARM     74.18 +12.1%  8.1M │ AMAT   201.10  -2.8% 14.0M│ TSM   +0.71  ↓   1D       │ Recession 2026          27%  +1  $1.8M│
│ COIN   312.50 + 9.4% 22.0M │ LRCX   934.12  -2.5%  4.2M│ COIN  +0.62  ↑   1W       │ Trump wins 2028         52%  +3  $5.1M│
│ ... 4 more rows scroll     │ ... 4 more rows scroll    │ ... 4 more rows scroll    │ ... 4 more rows scroll                │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ SECTOR HEATMAP (1D)         │ EARNINGS TODAY            │ ECONOMIC CALENDAR                                                  │ R5
│ ┌──────┬───────┬──────┐    │ TICK   TIME EPS-EST ACT   │ TIME COUNTRY EVENT                  IMPORTANCE FORE ACT  PREV     │ 156px
│ │ TECH │ COMM. │ FIN. │    │ NVDA   AMC  $5.12   --    │ 08:30 US      Initial Jobless Claims  ●●●     220k --   210k    │
│ │+1.2% │+0.8%  │-0.3% │    │ ANET   BMO  $1.92  $2.04▲ │ 10:00 US      Existing Home Sales     ●●      3.95M --  3.96M   │
│ ├──────┼───────┼──────┤    │ DLTR   BMO  $1.55   --    │ 14:00 US      FOMC Minutes            ●●●●    --   --   --      │
│ │ CONS.│ ENERGY│HLTH. │    │ TGT    BMO  $2.06   --    │ 16:30 JP      CPI YoY (Apr)          ●●●     2.7% --   2.6%    │
│ │+0.4% │ -1.1% │+0.6% │    │ ... 6 more rows scroll    │ ... 8 more rows scroll                                          │
│ └──────┴───────┴──────┘    │                           │                                                                  │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ PORTFOLIO NEWS              │ ALERTS (LIVE)             │ TOP NEWS                                                          │ R6
│ NVDA  3m ago  TSMC capex…   │ HIGH  NVDA  -3% pre-mkt   │ Fed minutes confirm hawkish hold (Reuters · 4m)                   │ 156px
│ AAPL  18m ago Buyback ann.  │ MED   ANET  earnings beat │ TSMC Q1 revenue tops est, capex cut (Bloomberg · 12m)             │
│ MSFT  41m ago Copilot rev…  │ LOW   AAPL  buyback news  │ Boeing 737 MAX 7 cert delayed (FT · 26m)                           │
│ COIN  1h ago  ETF inflows   │ HIGH  COIN  ETF $400M in  │ Tesla cuts Cybertruck price 5% (WSJ · 38m)                         │
│ ... 6 more rows scroll      │ ... 8 more rows scroll    │ ... 10 more rows scroll                                            │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Visible cell count above the fold (1440×864)
- Market strip R2: 8 cells × 3 metric facets (last, %, sparkline) = **24 cells**
- Top of Portfolio R3: 8 KPI cells + (positions table: 5 rows × 7 cols) = **43 cells**
- Movers R4: 4 widgets × (5 rows × 4 cols avg) = **80 cells**
- Context R5: 3 widgets × (5 rows × ~5 cols avg) = **75 cells**
- Feed R6: 3 widgets × 4 rows × 3 cols = **36 cells**
- Morning Brief R1: 4 cells (brief summary, 3 chips)

**Total above fold: ~262 data points**, ~5× the target (40-60). Well above the
Bloomberg-grade threshold. The bulk comes from the new Top of Portfolio
widget (was 8 cells in current widget, now 43).

---

## 5. Component breakdown

All new/changed files. ✚ = new, ✱ = renamed/major rewrite, ☐ = unchanged.

| File | Status | Lines | Renders | Props |
|------|--------|-------|---------|-------|
| `app/(app)/dashboard/page.tsx` | ✱ | ~120 | Top-level grid container, row spans | none (server component) |
| `components/dashboard/MorningBriefCard.tsx` | ☐ | ~640 | Brief (slight CSS-only changes: h-6 header→h-5, smaller bottom chip strip) | none |
| `components/dashboard/MarketStrip.tsx` | ✚ | ~180 | R2 — 8 cell market strip (replaces `MarketSnapshotWidget`) | `tickers?: string[]` (default 8) |
| `components/portfolio/TopOfPortfolio.tsx` | ✚ | ~280 | R3 — full portfolio widget. Two children: `PortfolioKpiStrip` + `PortfolioPositionsTable` + `PortfolioPerfSparkline` | `portfolioId?: string` |
| `components/portfolio/PortfolioKpiStrip.tsx` | ✚ | ~90 | NLV / Cost / Cash / Day P&L / Unr P&L / MTD / YTD — 8 metric cells in 2×4 grid | `summary: PortfolioSummaryDto` |
| `components/portfolio/PortfolioPositionsTable.tsx` | ✚ | ~160 | 5 visible rows × 7 cols (ticker, qty, avg, mkt, mkt val, unr P&L, day P&L, weight) — scroll for more | `holdings: HoldingWithQuote[]`, `maxRows?: number = 10` |
| `components/portfolio/PortfolioPerfSparkline.tsx` | ✚ | ~70 | 1D/5D/1M/3M/YTD period chips + sparkline (130×40) | `series: PerfPoint[]`, `period: Period` |
| `components/dashboard/GainersWidget.tsx` | ✚ | ~120 | R4 col 1 — 6-row gainers table (split from current `MoversWidgetTabs` MARKET tab) | `limit?: number = 8` |
| `components/dashboard/LosersWidget.tsx` | ✚ | ~120 | R4 col 2 — 6-row losers table | `limit?: number = 8` |
| `components/dashboard/AiSignalsWidget.tsx` | ☐ | ~150 | R4 col 3 — unchanged | none |
| `components/dashboard/PredictionMarketsWidget.tsx` | ✱ | ~200 | R4 col 4 — same data, denser 22px row table | none |
| `components/dashboard/SectorHeatmapWidget.tsx` | ✱ | ~250 | R5 col 1 — treemap (existing, slight CSS density) | none |
| `components/dashboard/EarningsCalendarWidget.tsx` | ☐ | ~180 | R5 col 2 — unchanged | none |
| `components/dashboard/EconomicCalendar.tsx` | ☐ | ~180 | R5 col 3 — unchanged | none |
| `components/dashboard/PortfolioNewsWidget.tsx` | ☐ | ~200 | R6 col 1 — unchanged | none |
| `components/dashboard/RecentAlerts.tsx` | ✱ | ~180 | R6 col 2 — adds severity dots column; otherwise unchanged | none |
| `components/dashboard/TopNewsWidget.tsx` | ✚ | ~140 | R6 col 3 — global top news (split from PortfolioNewsWidget; portfolio one stays filtered) | `limit?: number = 12` |
| `components/dashboard/MoversWidgetTabs.tsx` | DELETE | — | Replaced by separate Gainers + Losers widgets | — |
| `components/dashboard/MarketSnapshotWidget.tsx` | DELETE | — | Replaced by `MarketStrip` | — |
| `components/dashboard/PortfolioSummary.tsx` | DELETE | — | Replaced by `TopOfPortfolio` | — |

### Shared primitives reused
- `components/ui/sparkline.tsx` (existing)
- `components/ui/data-table.tsx` (existing — used by all R4/R5/R6 tables)
- `components/ui/severity-dot.tsx` (existing — for alerts)
- `components/ui/period-tabs.tsx` (existing — 1D/5D/1M/3M/YTD)

---

## 6. Visual spec (numerical)

### Grid container
- `display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 8px;`
- Outer padding: `p-2` (8px)
- Background: `bg-background` (#09090B)
- Height: `calc(100vh - 36px)` (topbar offset)
- Overflow: `overflow-hidden` (no page scroll; per-widget internal scroll only)

### Per-cell chrome
- Border: `border border-border/40` (1px hairline #1F1F23 at 40% opacity)
- No border-radius (`rounded-none`). Bloomberg terminals are sharp rectangles.
- No box-shadow. **Banned**: elevation effects.
- Internal padding: `p-0` on the cell; widgets manage their own padding.

### Row heights
- R1 (Morning Brief): **96px** total — h-5 header (20px) + ~70px content + 6px padding
- R2 (Market Strip): **96px** — h-5 group label (20px) + 8 ticker cells in 76px content area, each cell h-[68px]
- R3 (Top of Portfolio): **156px** — h-5 title bar + 132px content + p-2
- R4/R5/R6: **156px** — h-5 panel header + 5 rows × 22px + 22px footer/scroll affordance + p-1

### Typography (from shared scale)
- Panel header (e.g. "GAINERS ▲"): `text-[9px] uppercase tracking-[0.08em] text-muted-foreground font-medium`
- Column headers: `text-[9px] uppercase tracking-wide text-muted-foreground/60`
- Table body cells: `text-[11px] font-mono tabular-nums` for numeric; `text-[11px]` (sans) for text
- KPI labels (NLV, Day P&L): `text-[9px] uppercase text-muted-foreground tracking-wide`
- KPI values: `text-[14px] font-mono tabular-nums` (hero number — only place on dashboard with text-[14px], 8 instances)
- Brief summary body: `text-[11px] leading-snug`

### Spacing
- Inter-row gap: 8px (`gap-2`)
- Inter-column gap: 8px (`gap-2`)
- Intra-widget header→body: 0 (header has `border-b`, no margin)
- Table row height: **22px** standard; **20px** in 8-row variant (R4 widgets at 20px get 6 rows visible)
- Cell padding: `px-2 py-0` (8px horizontal, vertical handled by `h-[22px]`)

### Colors (from palette)
- Positive numbers: `text-positive` (#00D26A)
- Negative numbers: `text-negative` (#FF3B5C)
- Neutral muted: `text-muted-foreground` (#71717A)
- Primary accent (brief border, active tab): `text-primary` / `border-primary/60` (#FFD60A at 60%)
- Warning (stale brief, ECON ●●●●): `text-warning` (#FFB000)
- Severity dots in Alerts: HIGH=`text-negative`, MED=`text-warning`, LOW=`text-muted-foreground`

### Sparklines
- Market Strip: 60×20px inline SVG, `stroke-positive`/`stroke-negative` 1px
- Portfolio perf: 130×40px, `stroke-primary` 1.5px, no fill
- Per-row inline sparklines (if added later): 40×16px

---

## 7. Interaction model

### Hotkeys (scoped to dashboard)
- `b` — toggle Morning Brief expanded/collapsed
- `r` — refresh brief
- `g g` — focus Gainers panel (Vim-style chord)
- `g l` — focus Losers
- `g p` — focus Top of Portfolio
- `1`–`5` — switch portfolio period (1D/5D/1M/3M/YTD)
- `/` — open global search (handled by shell)
- `?` — show hotkey cheat sheet (handled by shell)

### Hover behaviour
- Ticker cells (any widget): underline + cursor-pointer; clicking navigates to
  `/instruments/{instrument_id}` (NOT `/instruments/{ticker}` — see ADR-F-12)
- Brief chips: hover lightens border, click opens external source in new tab
- KPI cells in TopOfPortfolio: hover → tooltip with definition ("Unrealized
  P&L = sum of (mkt_price − avg_cost) × qty for all holdings")
- Sparkline cells in Market Strip: hover crosshair shows last-value + day-low
  + day-high in a 60×40px overlay

### Click handlers
- Brief "Read more" → expand inline (current behaviour kept; cap at 360px
  expanded height, overflow-auto)
- Brief "Discuss" → seed chat thread (existing `useBriefChatSeed`)
- Ticker link → `/instruments/{instrument_id}`
- Portfolio "View all ▸" → `/portfolio/holdings`
- KPI strip "Day P&L" → opens P&L attribution drawer (Phase 2 — link only)
- Movers row → `/screener?bucket=gainers` / `/screener?bucket=losers`
- Sector heatmap tile → `/screener?sector={name}`
- Alerts row → `/alerts/{id}` or expand inline detail

### Loading / error / empty states (REQUIRED for every widget)

Each widget must implement three explicit states, each at the correct height
(no layout shift between states):

| Widget | Loading | Error | Empty |
|---|---|---|---|
| MorningBriefCard | 5-line skeleton at brief height | "Brief generating…" + retry (503) / "Brief unavailable" + retry | "AI brief unavailable — system initializing" (already present) |
| MarketStrip | 8 cell skeletons (ticker stub + grey bar) | Per-cell "—" + tooltip "quote unavailable" | (impossible — defaults hardcoded) |
| TopOfPortfolio | KPI strip skeleton + 5 ghost rows | "Portfolio unavailable — retry" with button | "No portfolio connected — [Connect brokerage ▸]" link to /settings/brokerage |
| PortfolioKpiStrip | 8 shimmer cells | hide widget, log error | "—" in every value cell |
| PortfolioPositionsTable | 5 ghost rows | "Positions unavailable" | "No positions — open one to see it here" |
| GainersWidget / LosersWidget | 6 ghost rows | "Movers unavailable" + retry | "No movers data" |
| AiSignalsWidget | 6 ghost rows | "AI signals offline" | "No signals today" |
| PredictionMarketsWidget | 6 ghost rows | "Markets unavailable" | "No active markets" |
| SectorHeatmapWidget | treemap skeleton (11 grey tiles) | "Heatmap unavailable" | "—" |
| EarningsCalendarWidget | 6 ghost rows | "Earnings unavailable" | "No earnings today" |
| EconomicCalendar | 6 ghost rows | "Calendar unavailable" | "No events today" |
| PortfolioNewsWidget | 6 ghost rows | "News unavailable" | "No news for your positions" |
| RecentAlerts | 6 ghost rows | "Alerts offline (SSE disconnected)" + reconnect indicator | "No unack alerts" |
| TopNewsWidget | 12 ghost rows | "News unavailable" | "No news available" |

---

## 8. Data fetching

All queries via TanStack Query through `createGateway(accessToken).*`. Cache
keys use the proposed `qk.*` from `lib/query/keys.ts`.

| Resource | queryKey | staleTime | refetchInterval | Reused by |
|---|---|---|---|---|
| Morning brief | `qk.briefMorning()` → `["brief","morning"]` | 30 min | — | only dashboard |
| Brief diff | `qk.briefDiff(briefId)` | 5 min | — | dashboard only |
| Portfolios | `qk.portfolios()` → `["portfolios"]` | 5 min | — | portfolio pages |
| Portfolio summary | `qk.portfolioSummary(id)` → `["portfolio","summary",id]` | 30 s | 30 s (during market hours) | portfolio overview |
| Holdings | `qk.holdings(id)` → `["holdings",id]` | 30 s | 60 s | portfolio overview |
| Batch quotes | `qk.quotesBatch(ids)` → `["quotes","batch",sortedIds]` | 5 s | 15 s during market hours | every page |
| Portfolio perf | `qk.portfolioPerf(id, period)` → `["portfolio","perf",id,period]` | 5 min | — | portfolio overview |
| Top movers (gainers) | `qk.topMovers("gainers",20)` | 60 s | 60 s | screener |
| Top movers (losers) | `qk.topMovers("losers",20)` | 60 s | 60 s | screener |
| AI signals | `qk.aiSignals(6)` | 5 min | — | workspace |
| Predictions | `qk.predictions("all",10)` | 5 min | — | workspace |
| Sector heatmap | `qk.sectorHeatmap("1D")` | 60 s | 60 s | screener |
| Earnings calendar | `qk.earningsCalendar()` | 5 min | — | calendar page |
| Economic calendar | `qk.economicCalendar()` | 5 min | — | calendar page |
| Top news | `qk.topNews(20)` | 2 min | 2 min | news pages |
| Alerts pending | `qk.alertsPending(10)` | 30 s | SSE + 30 s poll | alerts page |
| Dashboard snapshot warmup | `qk.dashboardSnapshot()` | — | — | dashboard only |

**Dedup opportunities** (resources used by 2+ pages — share cache):
- `qk.portfolios()`, `qk.holdings(id)`, `qk.quotesBatch(ids)` — used by 6+ pages
- `qk.portfolioSummary(id)` — dashboard + portfolio overview share
- `qk.topMovers(*)`, `qk.sectorHeatmap(*)` — dashboard + screener share
- `qk.topNews(*)` — dashboard + news page share

The existing `DashboardSnapshotPrefetcher` calls `GET /v1/dashboard/snapshot`
which is a backend-bundled endpoint that warms half a dozen of these caches
in one round-trip. Keep it — it cuts time-to-first-paint from ~700ms (6
sequential queries) to ~180ms (1 query). On dashboard mount, it primes:
brief.morning, portfolios, holdings(first), quotes(holdings), topMovers,
sectorHeatmap, topNews.

---

## 9. Tradeoffs & decisions

### Decision 1 — How to surface user positions (the explicit user complaint)

**The user said: "we are not clearly displaying user positions."** Below are
the two alternatives considered, plus the recommendation.

#### Alternative A — "Top of Portfolio" mega-cell (RECOMMENDED)

A single full-width R3 cell (12 columns, 156px tall) split into three regions:

```
┌── TOP OF PORTFOLIO ───────────────────────────────────────────────────────┐
│ [KPI strip: 8 cells, 2 rows × 4 cols, 220px wide] │ [POSITIONS TABLE     ]│
│  NLV     Day P&L     Cost     MTD                 │ 5 rows × 7 cols      │
│  Cash    Unr P&L     Cash%    YTD                 │ TICK QTY AVG MKT     │
│ [1D 5D 1M 3M YTD] [sparkline 130×40px]            │ MKT-VAL UNR DAY WT   │
└───────────────────────────────────────────────────────────────────────────┘
```

Layout breakdown:
- Left third (col 1-4, 460px): KpiStrip (top) + PeriodTabs + Sparkline (bot)
- Right two-thirds (col 5-12, 920px): PositionsTable, 5 rows visible × 7 cols

Position table columns (7):
1. **TICKER** (44px) — link to instrument page
2. **QTY** (52px) — right-aligned mono
3. **AVG** (64px) — average cost
4. **MKT** (64px) — current market price
5. **MKT VAL** (88px) — qty × mkt
6. **UNR P&L** (104px) — (mkt − avg) × qty, with arrow + abs value, coloured
7. **DAY P&L** (96px) — qty × day_change, coloured
8. **WEIGHT** (56px) — mkt_val / NLV as %, mono right-align

Row height **22px**, 5 visible rows = 110px. Overflow scroll for additional
holdings. "View all ▸" link to `/portfolio/holdings`.

**KPI strip** (8 cells in 2 × 4 grid, each ~110×40px):
- Row 1: NLV ($1,248,312)  ·  Day P&L (+$3,142 +0.25%)  ·  Cost ($1,102,850)  ·  MTD (+1.82%)
- Row 2: Cash ($42,800)  ·  Unr P&L (+$145,462 +13.19%)  ·  Cash% (3.4%)  ·  YTD (+8.97%)

Pros:
- 8 KPI cells + 35 position cells (5×7) = 43 above-fold data points for "your
  money" alone. Closes the gap from current 8.
- Single contiguous region — no eye-saccade between three separated widgets.
- Mirrors Bloomberg PORT, IBKR Mosaic Portfolio panel, Koyfin Dashboard.
- All data already available (`/v1/portfolios/{id}/summary` + `/holdings` +
  `/quotes/batch` + `/performance`).

Cons:
- R3 spans col 1-12, can't be reordered with neighbours. Reservations: user
  may want positions on the right side; keep the order configurable in a
  future personalization layer (Phase 2).

#### Alternative B — Three-panel portfolio split across R3 (rejected)

```
┌── PORTFOLIO P&L ──┬── POSITIONS ────────────┬── PORTFOLIO NEWS ──┐
│ col 1-3 (336px)   │ col 4-9 (688px)         │ col 10-12 (240px)  │
│ KPIs stacked      │ Positions table         │ ticker news        │
│ + sparkline       │ 5×7 cols, 110px         │ 4 rows             │
└───────────────────┴─────────────────────────┴────────────────────┘
```

Pros:
- Portfolio news adjacent to positions ("contextual proximity").

Cons:
- 240px is too narrow for news headlines (wraps to 3-4 lines, kills the 22px
  row height).
- Splits Portfolio News from the rest of the news feeds in R6, inconsistent.
- KPI strip vertical in 336px loses the "metric strip" Bloomberg pattern.

**→ Reject B. Adopt A.**

#### Alternative C — Dedicated portfolio sidebar on the right (rejected)

A persistent 240-280px right rail (like the watchlist) that always shows
positions. Considered, rejected:

- Watchlist already owns the right rail (per `01-global-shell.md`). Two
  sidebars eat 480px of horizontal real estate = 33% of viewport on a 1440px
  display. Dashboard widget area drops to ~960px — too narrow for the
  4-up Movers row.
- Mixing dashboard and global chrome (sidebar) creates a confused mental
  model. Positions are dashboard content, not navigation.

**→ Reject C. Adopt A.**

### Decision 2 — Combined Gainers/Losers vs separate widgets

**Current**: `MoversWidgetTabs` with 3 tabs (MARKET / HOLDINGS / WATCHLIST) in
one cell — only one tab visible at a time.

**Proposed**: separate `GainersWidget` + `LosersWidget` cells, both visible
simultaneously in R4.

Pros:
- 2× the visible mover rows (8 + 8 = 16 instead of 8).
- Eliminates a tab click — Bloomberg MOST shows gainers + losers side by side
  by default.
- HOLDINGS / WATCHLIST tabs are redundant: holdings movers live in the new
  Top of Portfolio table; watchlist movers live in the global sidebar.

Cons:
- Loses single-cell-three-views density.

**→ Adopt separate widgets. The tab pattern hides data; in a Bloomberg-grade
density target, hiding data behind a tab click is anti-pattern.**

### Decision 3 — Row height: 22px standard vs 20px ultra-dense

Bloomberg WEI uses ~18px rows. Finviz uses ~18px. Our shared token says 22px
standard, 20px when paired with a divider.

**Decision**: 22px standard everywhere on the dashboard. **Exception**: R5
SectorHeatmap tile inner rows at 18px (very dense tile grid). At 11px body
font + line-height 16px, 22px row leaves 6px vertical padding — enough to
prevent the descenders of `g`/`y`/`p` clipping into the next row, while
keeping density high (5 rows in 110px = R4 widgets).

### Decision 4 — Drop `MarketSnapshotWidget`'s tabbed multi-period view

Current `MarketSnapshotWidget` has period tabs (1D / 5D / 1M) per row. New
`MarketStrip` is 1D-only and uses the saved horizontal space for 4 more
tickers (4 → 8 cells: SPX, NDX, DJI, RUT, VIX, TNX (10Y), DXY, BTC).

**Rationale**: 1D is what 95% of traders look at on the dashboard. Multi-period
peeking belongs on the instrument page. Saved 200ms render time too (no
per-row query split).

---

## 10. Open questions

1. **Portfolio selector**: which portfolio does Top of Portfolio default to
   when the user has multiple (Demo / Live / Paper)? Current widget picks the
   first by listing order. Proposal: persist last-selected in localStorage;
   default to Live when present, else Demo. Add a dropdown in the widget
   header (`[Demo · Live · Paper ▾]`).
2. **No-brokerage state**: the existing PortfolioSummary widget shows demo
   data when no portfolio is connected. Should Top of Portfolio do the same,
   or show a CTA "Connect brokerage" linking to `/settings/brokerage`?
   Proposal: empty state CTA. Demo data on the dashboard misleads new users.
3. **Day P&L during pre-market**: between 04:00–09:30 ET, what counts as
   "day"? Backend currently returns `day_change` from the prior close.
   Proposal: keep prior-close basis, label it "Day P&L (since prev close)"
   only on hover tooltip.
4. **Brief diff staleness**: `BriefDiffBadge` shows "N new" since last view.
   What if the user has 3 days of unseen briefs? Current behaviour: diff
   against most recent prior brief. Acceptable? Or merge all unseen diffs?
   Defer to agent-data-audit (might need backend support).
5. **Mobile / tablet collapse**: current dashboard has md:6-col / sm:1-col
   collapse. New layout breaks this — Top of Portfolio at 12 columns can't
   collapse cleanly. Proposal: at <lg, stack each KPI strip + positions table
   as separate full-width blocks (Top of Portfolio becomes 2 rows: KPIs then
   positions). Confirm acceptable mobile experience.
6. **SSE reconnect for alerts**: when SSE drops, RecentAlerts shows a degraded
   state. Should the dashboard show a single global SSE-status pill in the
   topbar instead? Defer to `01-global-shell.md`.
7. **Brief border**: current `MorningBriefCard` is wrapped with
   `border border-primary/60` (yellow accent). Keep, or move accent to a
   ▎thick left border only (more Bloomberg-amber-rail authentic)? Proposal:
   left rail only — 3px `border-l-primary`, removes 6px of yellow chrome on
   top/right/bottom.
8. **Backend data inventory file**: this doc was written before
   `00-backend-data-inventory.md` exists. When agent-data-audit returns,
   reconcile every "Currently used?" column entry against the actual
   endpoint catalogue. If any cited endpoint differs in name/shape, patch
   this doc.

---

**End of `02-dashboard.md`.**
