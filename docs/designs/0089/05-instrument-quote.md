# Instrument Detail — Quote Tab — Design Spec (PRD-0089)

> **Status:** in-discovery — iter-2 (2026-05-22): PLAN-0091 F-1 TAOverlayPanel + F-2 SentimentOverlay added.
> **Agent:** agent-instr-quote
> **Reads:** `docs/designs/0089/_INDEX.md` (shared tokens), `docs/specs/0088-instrument-detail-page-ground-up-redesign.md` (current PRD), `docs/designs/0089/00-backend-data-inventory.md` (when published).
> **Baseline being iterated:** `apps/worldview-web/components/instrument/quote/QuoteTab.tsx` + `MetricsTable.tsx` + `OHLCVChart.tsx` + `SessionStatsStrip.tsx` + `InstrumentHeader.tsx` + `AiBriefBanner.tsx`.

## 0. Why a v2 design (user feedback, 2026-05-19)

After live testing the PLAN-0090 Quote tab the user surfaced six concrete defects:

| # | Quote from user | Translation |
|---|----------------|-------------|
| 1 | "look unprofessional" | Density too low; surface looks like a demo, not a terminal. |
| 2 | "too many gaps" | Empty vertical bands between header / chart / strip / metrics. |
| 3 | "too much padding" | `p-3` / `gap-4` inside rows; tab content edges over-inset. |
| 4 | "AI brief of the company has been deleted" | `AiBriefBanner` is still wired in `InstrumentPageClient.tsx:157` but returns `null` for any instrument without a cached brief — invisible 95% of the time. |
| 5 | "no description, sector" | `instrument.description` + `gics_sector` + `gics_industry` exist on the bundle but are never rendered anywhere on the Quote tab. |
| 6 | "sidebar looks empty" | The 40% right rail is a single 26-row `MetricsTable` followed by ~600px of dead canvas at 1440×900. |

Target after this redesign: **52+ data cells above the fold at 1440×900** vs. the current ~28.

## 1. Competitor research summary

### Bloomberg Terminal (DES + GP equity)

- DES screen: top half is a 3-column block of `Company Description`, `Industry Group / GICS / SIC`, `Key Personnel`, `Address / Phone / Website`. Everything is on one screen, no scroll.
- GP screen: candlestick chart left ~70%, right rail is **dense** — Last/Net Chg/% Chg/Volume/52W H-L bar/EPS/P/E/Div Yld/Beta/Mkt Cap, then below the chart a horizontal strip of intraday stats (VWAP, ATR, day high/low, prev close).
- **Density signal:** Bloomberg DES typically shows ~70 distinct data atoms above the fold at 1280×800; we are at ~28. The gap is the entire problem.
- **Steal:** the DES-style "company narrative card" with sector/industry/employees/HQ printed in 11px and a 3-line clamp of description.

### TradingView symbol page

- Chart-dominant (~75% of viewport), but the right rail packs: Key stats card (Mkt cap / P/E / EPS / Div Yld / Beta), Earnings card (next date + last surprise %), Analyst rating bar, Income statement summary, About card (description 4-line clamp + sector + industry + founded + employees + website).
- **Steal:** the right-rail card stack pattern (5–6 small cards rather than one mega-table). Each card has a 24px header and ≤6 rows.

### Finviz quote page

- Truly the density benchmark: ONE page, all fundamentals, peer comparison table, news feed, and chart at top. No scroll on a 1440×900.
- Metrics table is 13 columns × 6 rows = 78 visible cells in a single grid.
- Chart band underneath is 5 timeframes side-by-side.
- **Steal:** the 13×6 dense metric grid pattern for the right-rail core (we currently waste vertical space with 1-cell-per-row).

### Stockanalysis.com / Yahoo Finance Pro

- Stockanalysis.com hits a great middle ground: chart top, then a 5-column "Quick Stats" strip (Mkt Cap / P/E / EPS / Div / 52W Range bar), then a "Quote Statistics" + "Profile" + "Analyst Estimates" + "Recent News" grid below — each tile ~280px wide.
- Yahoo Finance Pro shows the same content but adds a "What's moving the stock" hand-curated three-tile band at the bottom (article + sentiment + price impact %).
- **Steal:** the "what's moving" band — perfect for our `RankedNewsResponse` data we already fetch.

### Koyfin equity

- Cleanest of the bunch — chart left, modular cards right; below chart a "Snapshot" 6-column horizontal stat strip (PRICE / 1D / 5D / 1M / 3M / 1Y returns) and a "Description" tile.
- **Steal:** the multi-period return strip as our "below-chart stat band".

### Synthesis — what we copy

1. Bloomberg DES-style company card (narrative + sector + HQ).
2. Finviz dense metric grid (multi-column, not single-column rows).
3. TradingView right-rail card stack (5 small cards beats 1 mega-table).
4. Yahoo "what's moving" 3-tile bottom band.
5. Koyfin multi-period returns strip below the chart.

## 2. User intent for this page

**Primary persona:** active retail trader / junior buy-side analyst doing a 30-second instrument triage before deciding to deep-dive.

**Primary tasks (top 3):**
1. "Where is the price vs. its 52W range and recent technicals?" → chart + session strip + MA50/MA200/RSI/BB.
2. "What is the company, what does it do, in what sector?" → company description card (the missing piece today).
3. "What is the market currently pricing in (analyst target, peer multiples, recent EPS surprise)?" → metrics + earnings + peers.

**Secondary tasks:**
- Spot recent insider activity at a glance.
- Read the latest 3 high-impact news headlines.
- Check support/resistance levels from technicals.
- Compare to peers without leaving the page.

**Anti-patterns (banned):**
- Multi-screen scroll just to read the company name + sector.
- Empty right rail / chart deadspace at 1440×900.
- Hero numbers (`text-2xl`, `text-3xl`) — banned across the redesign.
- Animated transitions on data refresh.
- Card shadows / rounded-xl decoration that wastes pixels.

## 3. Backend data available (cite `00-backend-data-inventory.md`)

> Until `00-backend-data-inventory.md` lands, this section enumerates the
> endpoints/fields the Quote tab v2 will consume. The inventory doc must
> reconcile these names to S9 route paths and DB sources before
> implementation.

### Already on the page-bundle (`GET /v1/instruments/{id}/page-bundle`)

| Resource | Field | Currently rendered? | Notes |
|----------|-------|---------------------|-------|
| `bundle.overview.instrument` | `ticker`, `name`, `exchange`, `currency` | yes (header) | |
| `bundle.overview.instrument` | `gics_sector`, `gics_industry`, `country`, `isin` | **NO** | user-flagged gap |
| `bundle.overview.instrument` | `description` | **NO** | user-flagged gap (the EODHD "General.Description") |
| `bundle.overview.quote` | `price`, `change`, `change_pct`, `volume`, `freshness_status`, `data_as_of` | yes (header) | |
| `bundle.overview.fundamentals` | 26 fundamentals fields | yes (MetricsTable) | |
| `bundle.overview.ohlcv` | last 30d 1D bars | yes (chart) | |
| `bundle.top_news` | `RankedNewsResponse` (5 articles) | yes (currently only used on Intelligence tab) | repurposed for "What's moving this stock" v2 band |
| `bundle.insider` | `FundamentalsSectionResponse` records | yes (Financials tab only) | repurposed for INSIDER ACTIVITY mini-card |

### Already fetched by separate hooks (already wired)

| Endpoint | Field group | Currently rendered? |
|----------|-------------|---------------------|
| `GET /v1/fundamentals/{id}` (full Fundamentals) | margins, ROE, leverage, analyst counts/target | yes |
| `GET /v1/fundamentals/{id}/technicals` | Beta / 50DayMA / 200DayMA / ShortPercent | yes (rows 24/25/short%) |
| `GET /v1/fundamentals/{id}/share-statistics` | PercentInsiders, PercentInstitutions | yes |
| `GET /v1/fundamentals/{id}/snapshot` | eps_ttm, beta, avg_volume_30d, fcf, interest_coverage, net_debt_to_ebitda, credit_rating | partial (eps/beta/avgvol only) |
| `GET /v1/fundamentals/{id}/earnings-history` | last N quarters EPS actual/estimate/surprise | **NO** (used only on Financials tab) |
| `GET /v1/fundamentals/{id}/insider-transactions` | recent insider buy/sell records | **NO** (used only on Financials tab) |
| `GET /v1/briefings/instrument/{entityId}` | AI brief narrative + summary + citations | currently rendered by `AiBriefBanner` but returns `null` 95% of the time → invisible |

### Backend additions REQUIRED before implementation (open backend tasks)

> These are the only true backend gaps; everything else is already
> available. Inventory doc must confirm scope.

| # | Endpoint | Purpose | Owning service | Estimate |
|---|----------|---------|----------------|----------|
| **B-Q-1** | `GET /v1/instruments/{id}/peers?limit=5` | 5 peer instruments by GICS industry + market-cap bucket. Returns `[{instrument_id, ticker, name, market_cap, pe_ratio, return_1y, change_pct}]`. | S9 + S3 | M (1 wave) |
| **B-Q-2** | `GET /v1/fundamentals/{id}/intraday-stats` | VWAP, ATR(14), day gap %, prev close, premarket high/low (when available), short-interest delta vs prior month. Aggregated server-side from existing OHLCV + technicals sections. | S9 wrapper | S (sub-wave) |
| **B-Q-3** | `GET /v1/fundamentals/{id}/multi-period-returns` | %returns at 1D / 5D / 1M / 3M / 6M / YTD / 1Y / 5Y. Pre-computed from OHLCV. | S9 wrapper | S (sub-wave) |
| **B-Q-4** | `GET /v1/fundamentals/{id}/price-levels` | Auto-derived support/resistance from technicals: pivot, R1/R2/R3, S1/S2/S3 (classic floor pivots), 50/200 DMA, 52W H/L. Pure computation; no new persistence. | S9 wrapper | S (sub-wave) |
| **B-Q-5** | `GET /v1/briefings/instrument/{entityId}?lazy=true` | Variant that triggers generation on first call (queues an S8 job and returns `{status:"queued"}`) so the brief banner can show a "Generating…" pill instead of being silently absent. | S8 + S9 | M (1 wave) |

User explicitly flagged items 4, 5, 6 of §0 — items B-Q-1..B-Q-5 directly close those gaps.

## 4. Layout

### 4.1. 1440 × 900 ASCII wireframe

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ◀ AAPL  NASDAQ  Apple Inc.                                            217.34  +1.42 (+0.66%)  │ CAP 3.34T  VOL 43.2M  P/E 32.1│  ← STICKY HEADER 36px (existing InstrumentHeader)
│                                                                                                  └─ 52W bar ─┘    [LIVE ●]     │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ▶ BRIEF  Apple posted Q1 EPS of $2.40 vs $2.10 estimate; iPhone 16 launch drove +12% revenue growth, services hit record    [3h ago]│  ← BRIEF banner 24px (v2 always-visible, never null)
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [QUOTE]  Financials   Intelligence                                                                                            │  ← TABS 28px (existing InstrumentTabs)
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ┌────────────────────────────────────────────────────────────────┬───────────────────────────────────────────────────────┐  │
│ │ 5m 1H 1D 1W 1M 1Y 5Y · LOG · VOL MA50 MA200 RSI MACD BB · ⛶  │  STATISTICS                                            │  │  ← chart toolbar 22px / metrics header 22px
│ │ ┌──────────────────────────────────────────────────────────┐ │ ┌─────────────┬─────────────┬─────────────┬─────────┐ │  │
│ │ │                                                          │ │ │ MARKET CAP  │ P/E         │ FWD P/E     │ P/S     │ │  │  ← Metric GRID 4-col, 22px rows
│ │ │           ╱╲  ╱╲                              ╱╲         │ │ │ 3.34T       │ 32.1        │ 28.4        │ 8.2     │ │  │     (Finviz-style — 8 metrics per 4 rows = 32 cells)
│ │ │      ╲╱      ╲╱   ╲╱╲╱╲╱╲╱╲╱  ╲╱╲╱  ╲╱  ╲╱     ╲╲      │ │ │ EPS TTM     │ P/B         │ EV/EBITDA   │ DIV     │ │  │
│ │ │                                                          │ │ │ 6.78        │ 47.2        │ 24.1        │ 0.51%   │ │  │
│ │ │                            (OHLCV candles)               │ │ │ GROSS MARGIN│ OPER MARGIN │ NET MARGIN  │ ROE     │ │  │
│ │ │                            CHART (h ≈ 360px)             │ │ │ 46.2%       │ 30.7%       │ 25.3%       │ 156%    │ │  │
│ │ │                                                          │ │ │ DEBT/EQ     │ CURR RATIO  │ BETA        │ SHORT % │ │  │
│ │ │                                                          │ │ │ 1.94        │ 0.99        │ 1.27        │ 0.82%   │ │  │
│ │ │                                                          │ │ ├─────────────┴─────────────┴─────────────┴─────────┤ │  │
│ │ │      ▁▁ ▁  ▁▁ ▁▁▁▁ ▁ ▁ ▁▁▁ ▁ ▁▁ ▁ ▁▁ ▁ ▁▁▁ ▁ ▁ ▁ ▁▁     │ │ │ 52W: 164.08 ─────●─────────────────── 237.49      │ │  │  ← 52W bar
│ │ │           (volume sub-pane)                              │ │ ├─────────────────────────────────────────────────────┤ │  │
│ │ └──────────────────────────────────────────────────────────┘ │ │ ANALYST    ▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆ STRONG BUY  47 / 23/8/2/0│ │  │  ← AnalystMiniBar (existing)
│ │  O 215.92  │  H 218.40  │  L 214.10  │  V 43.2M  │ VWAP 216.7│ │ TARGET    $241.10  (+10.9%)                         │ │  │  ← SessionStatsStrip 22px
│ ├────────────────────────────────────────────────────────────────┤ ├─────────────────────────────────────────────────────┤ │  │
│ │ 1D +0.66%  5D +2.41%  1M -1.84%  3M +5.92%  YTD +14.3%  1Y +31.7%  5Y +189% │ INSIDER ACTIVITY                  ↻         │ │  │  ← multi-period returns strip 22px (B-Q-3)
│ ├────────────────────────────────────────────────────────────────┤ │ 2026-05-15  J.Williams   SALE   -$3.2M          │ │  │  ← INSIDER mini-card (last 5, 18px rows)
│ │ VWAP 216.71  ATR(14) 3.84  RSI(14) 58.2  GAP +0.21%  PREM 217.95/215.40  SI Δ +1.2%│  2026-05-12  K.Adams      BUY    +$1.1M  │ │  │  ← intraday stats band 22px (B-Q-2)
│ ├────────────────────────────────────────────────────────────────┤ │ 2026-05-08  T.Cook        SALE   -$32.4M       │ │  │
│ │ ABOUT  Sector: Technology · Industry: Consumer Electronics  ┃ │ 2026-04-30  L.Maestri     SALE   -$2.8M           │ │  │  ← ABOUT card 110px (sector + industry + HQ + emp)
│ │        HQ: Cupertino, CA · Founded: 1976 · Employees: 161k   ┃ │ 2026-04-22  J.Williams   SALE   -$0.9M           │ │  │
│ │        Apple designs, manufactures, and markets smartphones, ┃ ├─────────────────────────────────────────────────────┤ │  │  ← (description 3-line clamp) … "more"
│ │        personal computers, tablets, wearables, …      [more] ┃ │ RECENT EARNINGS                                     │ │  │  ← EARNINGS mini-card (last 4 quarters)
│ ├────────────────────────────────────────────────────────────────┤ │ Q1'26  EPS 2.40  est 2.10  +14.3% ▲              │ │  │
│ │  VS PEERS         │ PRICE LEVELS         │ WHAT'S MOVING ↗   │ │ Q4'25  EPS 2.15  est 2.18  -1.4% ▼              │ │  │
│ │  MSFT  44.2x +18% │ R3  225.40           │ ● Apple unveils… │ │ Q3'25  EPS 1.95  est 1.92  +1.6% ▲              │ │  │
│ │  GOOGL 26.1x +9%  │ R2  221.10           │   3h ago   +pos  │ │ Q2'25  EPS 1.78  est 1.74  +2.3% ▲              │ │  │
│ │  AMZN  61.8x +24% │ R1  218.85           │ ● Buffett trims… │ ├─────────────────────────────────────────────────────┤ │  │
│ │  META  30.0x +37% │ PIVOT 216.40         │   6h ago   -neg  │ │ RELATED HEADLINES                                   │ │  │
│ │  NVDA  78.4x +52% │ S1  214.15           │ ● iPhone 16 sees…│ │ ● Apple unveils Vision Pro 2 …          3h ago  + │ │  │  ← top 5 entity-tagged news (18px rows)
│ │                   │ S2  211.90           │   9h ago   +pos  │ │ ● Buffett trims AAPL position …         6h ago  - │ │  │
│ │                   │ S3  208.65           │                  │ │ ● iPhone 16 launch sees record …        9h ago  + │ │  │
│ │                   │ MA50 218.10 ↑        │                  │ │ ● Apple to expand India manuf …        11h ago  + │ │  │
│ │                   │ MA200 198.40 ↑       │                  │ │ ● Analysts: AAPL fair value $245 …     14h ago  + │ │  │
│ └────────────────────────────────────────────────────────────────┴───────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
   ↑ TAB CONTENT EDGE 0px (no horizontal inset; only inner panels are inset)
```

### 4.2. Grid description

The Quote tab is a CSS Grid (NOT flex) with two columns:

- **Left column** = `minmax(0, 1fr)` (was 60%); takes whatever's left after the right rail.
- **Right column** = `380px` fixed (was 40%, i.e. 576px on 1440 — too wide; the v2 fixed 380px frees 196px for chart density). Vertical scroll inside the right column only.

Left column is a CSS Grid with 6 row tracks (top to bottom):

| Row | Track height | Component |
|-----|--------------|-----------|
| L1 | 22px | Chart toolbar (timeframe + log + indicators) |
| L2 | `1fr` (≥320px reserved) | OHLCVChart canvas |
| L3 | 22px | SessionStatsStrip (O/H/L/V/VWAP) |
| L4 | 22px | MultiPeriodReturnsStrip (1D/5D/1M/3M/YTD/1Y/5Y) |
| L5 | 22px | IntradayStatsBand (VWAP/ATR/RSI/GAP/PREM/SI) |
| L6 | 110px | CompanyAboutCard (sector/industry/HQ/employees/description) |
| L7 | 132px | BottomTripleStrip (`Peers | PriceLevels | What's Moving`) |

Right column is a vertical stack (no inner grid; cards flow):

| Row | Track height | Component |
|-----|--------------|-----------|
| R1 | 22px | Section header "STATISTICS" |
| R2 | 88px (4 rows × 22) | MetricGrid4Col — block 1 (Valuation: 8 cells) |
| R3 | 88px | MetricGrid4Col — block 2 (Margins: 8 cells) |
| R4 | 88px | MetricGrid4Col — block 3 (Leverage/Yield: 8 cells) |
| R5 | 22px | WeekRangeBar (full-width) |
| R6 | 22px | AnalystMiniBar |
| R7 | 22px | Target row |
| R8 | 22px | "INSIDER ACTIVITY" header |
| R9 | 90px (5 rows × 18) | InsiderActivityList |
| R10 | 22px | "RECENT EARNINGS" header |
| R11 | 72px (4 rows × 18) | EarningsMiniList |
| R12 | 22px | "RELATED HEADLINES" header |
| R13 | 90px (5 rows × 18) | RelatedHeadlinesList |

### 4.3. Density target

**At 1440×900, above the fold (visible without scroll):**

| Region | Cell count |
|--------|------------|
| Header (3 metric cells: CAP/VOL/P/E + price + change + 52W bar) | 6 |
| Brief banner (preview + timestamp) | 2 |
| Session strip (O/H/L/V/VWAP) | 5 |
| Multi-period returns strip (7 periods) | 7 |
| Intraday stats band (VWAP/ATR/RSI/GAP/PREM/SI) | 6 |
| About card (sector/industry/HQ/founded/employees + description) | 5 |
| Bottom triple (5 peers × 3 metrics + 7 levels + 3 news) | 15 + 7 + 3 = 25 |
| Statistics grid (4×3 = 12 valuation+margins+leverage cells visible) | 12 |
| 52W bar + analyst bar + target row | 3 |
| Insider activity (top 3 of 5 visible) | 3 × 4 = 12 |
| Recent earnings (top 2 of 4 visible) | 2 × 4 = 8 |
| Related headlines (top 2 of 5 visible) | 2 × 2 = 4 |
| **Total** | **≈ 113 cells** |

This exceeds the 50+ target by 2.2×. Within Bloomberg DES range.

## 5. Component breakdown

### 5.1. Existing components to MODIFY

| Component | File | Change |
|-----------|------|--------|
| `QuoteTab` | `apps/worldview-web/components/instrument/quote/QuoteTab.tsx` | Rewrite layout: grid (not flex), 7-row left column, fixed 380px right rail. Pass new props through. Line budget: hard cap 240 (orchestrator exemption). |
| `MetricsTable` | `apps/worldview-web/components/instrument/quote/metrics/MetricsTable.tsx` | **Split** — convert the first 14 rows (valuation + margins + leverage + yield) into a `MetricGrid4Col` 4-column grid (8 cells × 3 blocks). Keep 52W bar, analyst bar, target row, ownership rows unchanged. Add `InsiderActivityList`, `EarningsMiniList`, `RelatedHeadlinesList` below. Line budget: ≤ 260 (was 198). |
| `AiBriefBanner` | `apps/worldview-web/components/instrument/brief/AiBriefBanner.tsx` | When brief is null/404, render a `Generating…` state instead of `null` — calls `B-Q-5 ?lazy=true` once. Polls every 30s for up to 5 minutes. After timeout: collapse to `BRIEF unavailable` muted state (still visible). Line budget: ≤ 180 (was 119). |
| `SessionStatsStrip` | `apps/worldview-web/components/instrument/SessionStatsStrip.tsx` | Unchanged behaviourally; only verify it sits at 22px tight (already does). |
| `InstrumentHeader` | `apps/worldview-web/components/instrument/header/InstrumentHeader.tsx` | Add `gics_sector` micro-pill next to the company name (between name and right cluster). 1 line change. |

### 5.2. NEW components

> File paths follow the established directory layout under
> `apps/worldview-web/components/instrument/quote/`.

| Component | File | Props | Purpose | Line budget |
|-----------|------|-------|---------|-------------|
| `MultiPeriodReturnsStrip` | `quote/strips/MultiPeriodReturnsStrip.tsx` | `{ instrumentId: string }` (fetches `B-Q-3`) | 7-period return strip (1D/5D/1M/3M/YTD/1Y/5Y) — coloured ±. | 110 |
| `IntradayStatsBand` | `quote/strips/IntradayStatsBand.tsx` | `{ instrumentId: string }` (fetches `B-Q-2`) | 6-stat band (VWAP/ATR/RSI/GAP/PREM/SI). | 130 |
| `CompanyAboutCard` | `quote/about/CompanyAboutCard.tsx` | `{ instrument: Instrument \| null }` | Sector + industry + HQ + founded + employees + 3-line description + "more". | 160 |
| `MetricGrid4Col` | `quote/metrics/MetricGrid4Col.tsx` | `{ cells: Array<{label, value, color}> }` (8 cells) | Generic 4×2 grid for any 8-cell block. Replaces the single-column `MetricRow`. | 90 |
| `InsiderActivityList` | `quote/insider/InsiderActivityList.tsx` | `{ instrumentId: string }` | Top 5 insider transactions, 18px rows, font-mono 9px secondary. | 140 |
| `EarningsMiniList` | `quote/earnings/EarningsMiniList.tsx` | `{ instrumentId: string }` | Last 4 quarters EPS actual vs est + surprise % colour. | 130 |
| `RelatedHeadlinesList` | `quote/news/RelatedHeadlinesList.tsx` | `{ entityId: string }` | Top 5 entity-scoped news, 18px rows with sentiment dot + age. | 150 |
| `PeersStrip` | `quote/bottom/PeersStrip.tsx` | `{ instrumentId: string }` (fetches `B-Q-1`) | 5 peer instruments × {P/E, mkt cap, 1Y return}. Clickable → routes to `/instruments/{peer.entity_id}`. | 150 |
| `PriceLevelsStrip` | `quote/bottom/PriceLevelsStrip.tsx` | `{ instrumentId: string }` (fetches `B-Q-4`) | R3/R2/R1/PIVOT/S1/S2/S3 + MA50/MA200 with arrow vs current price. | 130 |
| `WhatsMovingStrip` | `quote/bottom/WhatsMovingStrip.tsx` | `{ entityId: string }` (reuses `bundle.top_news`) | Top 3 news with sentiment dot + age + 1-line title clamp. | 110 |
| `BottomTripleStrip` | `quote/bottom/BottomTripleStrip.tsx` | `{ instrumentId, entityId }` | Pure layout: 3 columns × 132px each. Renders the 3 above. | 60 |

### 5.3. Re-use map

| New component | Reuses |
|---------------|--------|
| `MetricGrid4Col` | `MetricRow` (just a 4-column flex of pre-existing `MetricValue` cells) |
| `InsiderActivityList` | existing `getInsiderTransactions` API + `formatMarketCap` + `priceChangeClass` |
| `EarningsMiniList` | existing `getEarningsHistory` API + `signColor` from MetricsTable |
| `RelatedHeadlinesList` | existing `getEntityNews` API; sentiment colour helper from `lib/sentiment.ts` (already exists) |
| `WhatsMovingStrip` | reads from `bundle.top_news` (already prefetched on initial page load — zero extra round-trip) |

### 5.4. Deletions

None. The current `MetricsTable.tsx` is refactored, not removed — preserving the 198-line component until the new `MetricGrid4Col` ships under a feature flag would be safer. Once the grid version is verified, the single-column row variant is deleted (deferred to plan W4).

## 6. Visual spec (numerical)

### 6.1. Spacing (TIGHT — from `_INDEX.md`)

- Tab content edge inset: `0` (was `p-3`). Each panel handles its own inset.
- Inside any panel: `px-3 py-1` for header rows; `px-2 py-0` for data rows.
- Between section headers and first data row: `0px` (no margin — let the border act as separator).
- Between cards in the right rail: `0px` (border-bottom on each card; no `gap-*`).
- Inside `MetricGrid4Col`: 8 cells × `22px` height, dividers between columns are 1px `border-r border-border/30`; no padding.

### 6.2. Typography (from shared scale)

| Region | Token | Color |
|--------|-------|-------|
| Section header (STATISTICS, INSIDER ACTIVITY, etc.) | `text-[10px] uppercase tracking-wide` | `text-muted-foreground` |
| MetricGrid label | `text-[9px] uppercase` | `text-muted-foreground` |
| MetricGrid value | `text-[11px] font-mono tabular-nums` | `text-foreground` (or `text-positive` / `text-negative` / `text-warning` per FR-10) |
| Brief preview / about narrative | `text-[11px] leading-[1.5]` | `text-foreground/80` |
| Brief sector pill in header | `text-[10px] uppercase` | `text-muted-foreground` |
| Insider/news row primary | `text-[11px] font-mono tabular-nums` | `text-foreground` |
| Insider/news row secondary (date, source) | `text-[9px]` | `text-muted-foreground` |
| Multi-period return values | `text-[11px] font-mono tabular-nums` | semantic colour |
| Multi-period return labels | `text-[9px] uppercase` | `text-muted-foreground` |

### 6.3. Colors — strictly from `_INDEX.md` palette

- Positive deltas / "BUY" / margin > threshold: `text-positive`.
- Negative deltas / "SELL" / margin < 0: `text-negative`.
- Caution thresholds (P/E > 30, Beta > 1.5, D/E > 1): `text-warning`.
- All borders: `border-border` or `border-border/50` for subtler section breaks.
- No new colour tokens. `text-amber-N` etc. forbidden (architecture test enforces).

### 6.4. Row + column dimensions

| Element | Dimension |
|---------|-----------|
| Right rail width | 380px fixed |
| Chart minimum height | 320px (down from current ~440px — frees 120px for the new bands below) |
| Each strip (returns / intraday / session) | 22px |
| About card | 110px |
| Bottom triple strip | 132px |
| MetricGrid4Col cell | 90px × 22px = 1980 px² (was 380px × 22px = 8360 px²; 4.2× denser) |
| Insider / earnings / news row | 18px (smaller than `22px` metrics row — these are list rows, not metric cells) |

### 6.5. Borders / radii / animations

- All borders: 1px hairline `border-border`. No radii on panels (already `rounded-[2px]` max — keep). No shadows.
- Animations: NONE. No `transition`, no `animate-*`. (User specifically called out "animation removal" in the W6 chat polish session.)

## 7. Interaction model

### 7.1. Hotkeys scoped to Quote tab

Inherits page-level hotkeys from `InstrumentTabs` (`Q` = quote / `F` = financials / `I` = intelligence). Adds:

| Key | Action |
|-----|--------|
| `B` | Toggle brief banner expand/collapse |
| `D` | Toggle company about description expanded (3-line ↔ full) |
| `P` | Focus the Peers strip (arrow keys cycle peers; Enter navigates) |
| `1`/`5`/`30` | Switch chart timeframe to 1D/5D/30D (already exists) |
| `Shift+R` | Refetch all Quote tab data (invalidate `qk.instruments.detail(id)`) |

### 7.2. Hover behaviour

- Metric cell hover: show source tooltip ("From `/v1/fundamentals/{id}` · updated 12 min ago"). Reuses existing `<DataFreshnessTooltip>` from `components/instrument/DataFreshnessTooltip.tsx`.
- Insider row hover: tooltip shows full `transaction_type` (e.g. "Option Exercise" — truncated to "EXEC" in row).
- Headline row hover: shows full title (truncated to 1 line) and source URL.
- Peer row hover: pre-fetches peer's `page-bundle` (`qc.prefetchQuery`) so click navigates instantly.

### 7.3. Click handlers

- Click peer ticker → `router.push("/instruments/" + peer.entity_id)`.
- Click headline → opens `ArticleDetailModal` (existing component) with article id.
- Click brief preview → expands banner (same as `B` hotkey).
- Click "more" in about card → expands description.

### 7.4. Loading / error / empty states (per surface)

All three states REQUIRED per `_INDEX.md` §111.

#### Brief banner (`AiBriefBanner` v2)

- **Loading (lazy generation):** show `BRIEF · Generating…` with a 9px ⟳ spinner; poll every 30s; max 5 min then fall through to unavailable.
- **Error (5xx):** show `BRIEF · unavailable` muted (text-muted-foreground); link reads "Try again" to manual retry.
- **Empty (instrument has no entity_id or no documents):** show `BRIEF · no news in last 90 days` muted.
- **Success (collapsed):** show preview text (140 chars) + `[3h ago]` timestamp.
- **Success (expanded):** full narrative (max-h `120px overflow-y-auto`) + citations chip strip.

#### CompanyAboutCard

- **Loading:** Skeleton row × 5 lines (44px total height). Sector pill placeholder.
- **Error:** silent fallback to "—" for each field.
- **Empty (description == null, no sector):** show only `name` + `exchange` + `Description not available` muted line — never collapse the card (keeps layout stable).

#### MetricGrid4Col

- **Loading:** each of 8 cells renders `—` (no spinner; spinners cause page jitter). The hook has `placeholderData: bundle.overview.fundamentals` so first paint shows the bundle values.
- **Error:** silent `—` fallback per cell.
- **Empty (instrument has no fundamentals):** all `—`; an inline `Not available for this instrument type` muted message above the grid (one row, 18px).

#### InsiderActivityList

- **Loading:** 5 × 18px skeleton rows.
- **Error:** single muted row "Failed to load insider activity. [retry]".
- **Empty (no records):** single muted row "No insider activity in last 12 months."

#### EarningsMiniList

- **Loading:** 4 × 18px skeleton rows.
- **Error:** muted row "Failed to load earnings history."
- **Empty (no records, e.g. ETF):** muted row "No earnings history (ETF / fund)."

#### RelatedHeadlinesList

- **Loading:** 5 × 18px skeleton rows.
- **Error:** muted row "Failed to load related headlines."
- **Empty (no entity_id, or no articles in 30d):** muted row "No related news in last 30 days."

#### MultiPeriodReturnsStrip

- **Loading:** 7 × 56px skeleton cells.
- **Error:** silent `—` for each period.
- **Empty (insufficient history, e.g. IPO this week):** show only available periods; missing periods print `—`.

#### IntradayStatsBand

- **Loading:** all 6 cells `—`.
- **Error:** silent `—`.
- **Empty (after-hours, no premarket):** PREM cell hides; rest renders.

#### PeersStrip

- **Loading:** 5 × 22px skeleton rows.
- **Error:** muted row "Peers unavailable."
- **Empty (instrument with no GICS classification):** muted row "No peers (sector unclassified)."

#### PriceLevelsStrip

- **Loading:** 7 × 18px skeleton rows.
- **Error:** muted "Levels unavailable."
- **Empty (insufficient OHLCV history):** muted "Insufficient history for pivots (need ≥ 20 sessions)."

#### WhatsMovingStrip

- **Loading:** 3 × 30px skeleton rows.
- **Error:** muted "Headlines unavailable."
- **Empty:** muted "No news catalysts in last 24 h."

## 8. Data fetching

### 8.1. TanStack Query keys (propose new keys here)

Add the following keys under `qk.instruments.*` in `apps/worldview-web/lib/query/keys.ts`:

```ts
peers: (instrumentId: string) =>
  ["instruments", "detail", instrumentId, "peers"] as const,
intradayStats: (instrumentId: string) =>
  ["instruments", "detail", instrumentId, "intraday-stats"] as const,
multiPeriodReturns: (instrumentId: string) =>
  ["instruments", "detail", instrumentId, "multi-period-returns"] as const,
priceLevels: (instrumentId: string) =>
  ["instruments", "detail", instrumentId, "price-levels"] as const,
```

These nest under `instruments.detail.<id>` so the existing
`qc.invalidateQueries({ queryKey: qk.instruments.detail(id) })` cascade
already invalidates them in one shot — zero changes needed elsewhere.

### 8.2. staleTime per resource

| Resource | staleTime | Reason |
|----------|-----------|--------|
| `peers` | 24 h | Peer set rarely changes; expensive backend computation. |
| `intradayStats` | 60 s | VWAP/ATR drift intra-day. |
| `multiPeriodReturns` | 5 min | Anchored to daily close; minute-level precision unnecessary. |
| `priceLevels` | 5 min | Pivots derived from daily close; static intra-day. |
| `instrumentBrief` | 10 min | LLM-cached upstream (matches existing). |
| `earningsHistory` | 24 h | Quarterly cadence — daily is plenty. |
| `insiderTransactions` | 30 min | T+2 SEC filing latency. |
| `entityNews` | 5 min | Streaming source; medium freshness. |

### 8.3. Dedup opportunities (reused across pages)

| Resource | Also used by |
|----------|--------------|
| `peers` | Future Screener "similar to" filter; Intelligence tab graph seeding. |
| `multiPeriodReturns` | Portfolio Holdings row (column shows 1Y return). |
| `priceLevels` | Workspace chart widget alert-rule helpers. |
| `instrumentBrief` | Intelligence tab (already shared via `qk.instruments.brief`). |
| `earningsHistory` | Financials tab table (same key — single fetch). |
| `insiderTransactions` | Financials tab table (same key — single fetch). |
| `entityNews` | Intelligence tab news column; dashboard "for-you" widget. |

This dedup means the Quote tab's `RelatedHeadlinesList`, `InsiderActivityList`, and `EarningsMiniList` cost **zero extra round-trips** when the user has visited Financials or Intelligence first. On a cold cache, they fire 3 parallel fetches in the background after the page-bundle resolves — adding ~150ms to "fully populated" but 0ms to "first meaningful paint" because every list starts in its loading state without blocking the chart.

### 8.4. Suggested page-bundle expansion (B-Q-6, optional)

To collapse the cold-cache cost further, propose extending
`GET /v1/instruments/{id}/page-bundle` to optionally include:

```
?include=peers,intraday_stats,multi_period_returns,price_levels
```

…with each leg failing independently (same pattern as the existing
bundle). This is **NOT required** for the redesign to ship — the
per-resource hooks are sufficient — but it would drop the cold-load
network cost from 11 round-trips to 1. Defer to a follow-up wave.

## 9. Tradeoffs & decisions

### 9.1. Right rail: fixed 380px vs 40%

| Alternative | Pros | Cons |
|-------------|------|------|
| **Recommended: fixed 380px** | Predictable density; the metric grid is always 4 cells × 90px = 360 + 20px padding = exact fit. At 1440px viewport, frees 1060px for the chart vs 864px today. | Slightly less responsive at 1280px viewport (chart shrinks below comfortable threshold — needs media query to drop to 320px rail). |
| Keep 40% (576px on 1440) | Existing behaviour; less code churn. | Chart canvas waste; right rail becomes "wall of metric rows" — what user already called "empty sidebar". |
| 50% (toggle) | Power-user flexibility. | Adds state + storage; complexity for no clear win — competitors all use fixed rails. |

**Decision:** fixed 380px, with a 1280px breakpoint that drops to 320px and 1920px breakpoint that holds at 380px (extra space goes to chart).

### 9.2. Single mega-table vs split mini-cards

| Alternative | Pros | Cons |
|-------------|------|------|
| **Recommended: 4-column metric GRID + 3 mini-cards (insider/earnings/news)** | Hits 50+ density target; mirrors Finviz + TradingView. Each mini-card has its own loading state — partial failures degrade gracefully. | More components to test (10 new vs 0). |
| Keep 26-row single column | Already shipped. | Wastes 1×N pixels; can't recover the 600px sidebar gap that prompted this redesign. |
| Two columns, no mini-cards | Halfway compromise. | Still leaves ~400px of empty rail since only 13 rows are visible. |

**Decision:** split into 3 four-column grid blocks + 3 mini-cards.

### 9.3. AI brief: lazy generation vs preserve null state

| Alternative | Pros | Cons |
|-------------|------|------|
| **Recommended: lazy-generation + "Generating…" pill (B-Q-5)** | Brief always visible — user no longer "sees it deleted". | New S8 endpoint + frontend polling (~60 LoC). |
| Keep null hiding | No backend work. | The whole reason this redesign exists. |
| Show static "Description" from `instrument.description` as the brief | Free — already in bundle. | Conflates two surfaces; the description card already shows it. |

**Decision:** ship B-Q-5 + lazy-loaded banner. Until B-Q-5 lands, the banner shows `BRIEF · queue empty` muted state instead of null so the user sees the chrome.

### 9.4. Description card placement: left below chart vs right rail

| Alternative | Pros | Cons |
|-------------|------|------|
| **Recommended: left column under the strips (L6)** | Wide enough for 3-line clamp at 11px; sits next to chart (Bloomberg DES convention). | Steals 110px of chart real-estate. |
| Right rail top | Doesn't disturb chart. | Right rail already has 6 cards — adding a 7th forces a scroll inside the rail. |
| Header pill only (`sector + industry`) | Most compact. | Loses the description; user explicitly asked for the full narrative. |

**Decision:** left column under the strips. Add `gics_sector` pill in the header as a teaser (1 extra atom, no real cost).

### 9.5. Peers / Levels / WhatsMoving: 3-column strip vs separate rows

| Alternative | Pros | Cons |
|-------------|------|------|
| **Recommended: 3-column strip at L7 (132px tall)** | Tight; matches Finviz "Quick Stats" pattern; all three surfaces visible above the fold. | Some peers tickers may truncate. |
| 3 stacked rows | More room per surface. | Pushes mini-cards on the right below the fold. |
| One tile per tab (deferred to Intelligence) | Keeps Quote pure price-action. | User explicitly asked for "peers" + "what's moving" on Quote. |

**Decision:** 3-column strip at L7.

## 10. Open questions

1. **Sentiment dot source.** `WhatsMovingStrip` colours each headline by sentiment; the inventory doc must confirm whether `RankedArticle` carries a `sentiment_score` field or if we need a per-article fetch. Worst case: omit sentiment, just show timestamp.
2. **Peer ranking criteria for B-Q-1.** Is "5 closest by market-cap bucket within same GICS industry" the right heuristic, or should we use the S6 cosine-similarity over embedded company descriptions? Need product call.
3. **Price-level definitions for B-Q-4.** Classic floor pivots use `(H + L + C) / 3`. Should we instead expose Camarilla pivots (popular among retail traders)? Default to classic; add Camarilla as a future toggle.
4. **Multi-period return baseline.** `5Y` for a stock IPO'd 18 months ago — render `—` or render `since IPO`? Recommendation: `—` (consistent with other empty cells); add a tooltip "Insufficient history".
5. **Brief banner generation cost.** B-Q-5 lazy generation triggers an LLM call per first-visit instrument. Is rate-limiting (e.g. max 60 cold generations/hour per user) needed, or is the S8 LLM budget enough? Need data-platform call.
6. **Sticky position for the multi-period + intraday strips.** Should L4/L5 stay sticky when the chart scrolls? Currently the entire left column scrolls together; recommendation: keep non-sticky (avoids overlap with metric grid scrolling on smaller screens), revisit after live testing.
7. **Mobile / tablet behaviour.** The current QuoteTab is desktop-only (1024px+). v2 inherits that — does the redesign need a phone-friendly stacked variant in this wave or in a later one? Recommendation: defer; PRD-0089 is desktop-grade Bloomberg parity.

---

## 11. PLAN-0091 Additions (2026-05-22)

These two features extend the chart toolbar on the Quote tab. Wave F-1 adds client-side TA indicator overlays with a formal `TAOverlayPanel` component; Wave F-2 adds a sentiment timeseries secondary line triggered by the `[SENTI]` chip.

### 11.1 Wave F-1 — TAOverlayPanel (TA indicator chip strip)

The existing wireframe (§4.1) shows `MA50 MA200 RSI MACD BB` in the chart toolbar row, but the spec does not define the `TAOverlayPanel` component. This wave formalises it.

#### Chip strip layout

```
OVERLAYS: [EMA 20] [EMA 50] [SMA 200] [MACD] [BOLL] [RSI] [VWAP] [SENTI]
```

Each chip is a toggle button. Row sits directly below the OHLCVChart canvas, above `SessionStatsStrip` (row L3 in §4.2).

| State | Style |
|-------|-------|
| Active chip | `bg-primary/20 text-primary` (same as active filter chips across the platform) |
| Inactive chip | `bg-muted/30 text-muted-foreground` |
| Chip height | 18px |
| Chip font | `text-[9px] uppercase tracking-wide font-mono` |

When `MACD` or `RSI` is active: a secondary sub-chart panel (40px fixed height) appears below the main chart, between L2 and L3, sharing the x-axis. When `SENTI` is active: the sentiment timeseries overlay appears on the main chart right Y-axis (see §11.2).

#### TA computations

All TA computed client-side from OHLCV bars already fetched — no new API calls for EMA/SMA/RSI/MACD/BOLL/VWAP. Computations memoized via `useMemo`.

**New file**: `lib/ta/indicators.ts`

```typescript
export function ema(bars: OHLCVBar[], period: number): number[]
export function sma(bars: OHLCVBar[], period: number): number[]
export function rsi(bars: OHLCVBar[], period?: number): number[]          // default period=14
export function macd(bars: OHLCVBar[]): MACDResult[]                      // (12,26,9)
export function bollingerBands(bars: OHLCVBar[], period?: number, std?: number): BBResult[]  // default period=20, std=2
export function vwap(bars: OHLCVBar[]): number[]
```

`OHLCVChart` accepts an optional `overlays?: OverlaySeries[]` prop — non-breaking addition. Each series: `{ label: string; color: string; data: number[]; type: "line" | "band" }`. Indicator selection stored in local `useState` only (session-local; no URL, no localStorage).

#### Component files

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| `TAOverlayPanel` | `components/instrument/quote/TAOverlayPanel.tsx` | NEW | Chip strip + active-indicator state |
| TA computation utils | `lib/ta/indicators.ts` | NEW | Pure functions; no React dependencies |
| `OHLCVChart` | `components/instrument/chart/OHLCVChart.tsx` | MODIFY | Correct path is `chart/`, not `quote/`; add optional `overlays` prop |

#### Loading / error / empty

| State | Behaviour |
|-------|-----------|
| Bars not yet fetched | Chips disabled with `opacity-50 pointer-events-none` |
| Bars fetch error | Chips remain disabled; main chart error state handles messaging |
| Fewer than 2 bars | Chips disabled; TA requires a minimum data window |

---

### 11.2 Wave F-2 — SentimentOverlay chip in TAOverlayPanel

**Depends on**: PLAN-0091 Wave A-2 (`GET /v1/entities/{entityId}/sentiment-timeseries` new endpoint)

The `[SENTI]` chip in `TAOverlayPanel` fetches a daily sentiment timeseries and renders `net_sentiment = positive_ratio − negative_ratio` as a secondary line overlaid on the price chart.

#### Behaviour

1. `[SENTI]` chip is enabled only when `entityId` is non-null (instruments with a KG entity). Instruments without a KG entity show the chip with `opacity-50 pointer-events-none` and `title="No KG entity for this instrument"`.
2. When activated, fetches `GET /v1/entities/{entityId}/sentiment-timeseries?days={N}` where `N` maps from the current chart period (1D → 7, 5D → 14, 1M → 30, 3M → 90, 1Y → 365, 5Y → 365 capped).
3. Computes `net_sentiment = positive_ratio − negative_ratio` per daily data point.
4. Renders as a secondary line on the price chart using the right Y-axis (scale −1 to +1). Left Y-axis (price) is unchanged.
5. Line colour: `text-positive` (#00D26A) where `net_sentiment > 0`; `text-negative` (#FF3B5C) where `net_sentiment < 0`. Two separate path segments per sign-change, or a CSS gradient on the SVG path.

#### Data fetching

| Resource | Key | staleTime | Endpoint |
|----------|-----|-----------|---------|
| Entity sentiment timeseries | `qk.entitySentimentTimeseries(entityId, days)` (NEW in keys.ts) | 1h | `GET /v1/entities/{entityId}/sentiment-timeseries?days={N}` |

#### Component files

| Component / File | Status | Notes |
|------------------|--------|-------|
| `TAOverlayPanel` | MODIFY | Add `[SENTI]` chip; disabled when `entityId` null |
| `OHLCVChart` | MODIFY | Add right Y-axis for sentiment overlay; accept optional `sentimentSeries?: SentimentDataPoint[]` prop |
| `lib/query/keys.ts` | MODIFY | Add `qk.entitySentimentTimeseries(entityId: string, days: number)` |

#### Loading / error / empty

| State | Behaviour |
|-------|-----------|
| Loading (fetching timeseries) | Chip shows a 9px spinner; chart renders without overlay until data resolves |
| Error | "Sentiment data unavailable" tooltip on chip; chip auto-deactivates |
| Empty (no data points in range) | "No sentiment data for this period" tooltip; chip deactivates |
