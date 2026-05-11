# Instrument Overview Page — Redesign Audit

**Date**: 2026-05-09
**Author**: Senior product engineer (Overview redesign agent)
**Scope**: `apps/worldview-web/app/(app)/instruments/[entityId]/` Overview tab
**Method**: Static read of every Overview-related component (page.tsx, OverviewLayout, OHLCVChart, EntityGraph(Panel), InstrumentTopNews, OverviewSidebar, key metrics, sidebar panels) + live API probes against the running stack on `:8000` + competitor research on Yahoo Finance, Finviz, TradingView via WebFetch.
**Container state at probe time**: `worldview-web :3001` 200, S9 gateway `:8000` healthy, dev-login JWT issued.

---

## 1. Reproduction notes per reported issue

### 1.1 "Chart auto-scrolls into the past" — STATUS: FIXED, no regression

The `hasScrolledToRealTime` ref + `pendingScrollToRealTime` ref guards from PLAN-0053 are still in place at `OHLCVChart.tsx:280, 285, 299-302, 880-897`. The data-update effect calls `scrollToRealTime()` (NOT `fitContent()` — `fitContent` was the original cause of zooming-to-1985). Both refs reset on instrumentId/timeframe change.

Cross-confirmed with the existing `2026-05-09-qa-beta-frontend.md` audit (CHART-003). **No new code change needed for this**.

### 1.2 "Black empty component" — STATUS: ROOT CAUSE FOUND

**File**: `OverviewLayout.tsx:293`
```tsx
<div className="h-[400px] bg-card/20">
  <EntityGraphPanel entityId={entityId} centerLabel={centerLabel} />
</div>
```

**File**: `EntityGraphPanel.tsx:188-189` — the SVG inside is fixed at `WIDTH=320, HEIGHT=280` and the empty / loading states return `h-[280px]` divs.

The outer container is 400px tall; the inner SVG is 280px tall. The bottom 120px is a black void with only the outer `bg-card/20` (12% opacity over `--background #09090B` → effectively pure black) showing through. To the user, this looks like a "black empty component" stuck below the graph.

Also reinforces user complaint about "graph extremely simple" — the SVG is 320×280px and uses static radial layout, no zoom, no pan, no force layout (the rich sigma.js graph is reserved for the Intelligence tab).

### 1.3 "News component empty" — STATUS: BACKEND, mostly verified by audit

`GET /v1/news/entity/11111111-…?limit=4` returns `{ items: [], total: null }`. The InstrumentTopNews component correctly renders the empty state ("No recent news.") — this is correct behaviour for genuinely empty data. The seed DB simply has zero linked articles for AAPL despite 93 articles being ingested overall (memory: 2026-04-26 brief). This is a backend/data-seeding issue: articles exist but `entity_article_links` are not populated.

**Frontend fix**: render a richer empty-state with a deep-link to `/news?entity=AAPL` so the user has somewhere to go.

### 1.4 "Graph only shows 3 seeded relations" — STATUS: BACKEND DATA SPARSITY

```
GET /v1/entities/11111111-…/graph?depth=2 → { nodes: 4, edges: 3 }
```

Edges returned: `competes_with` (w=0.85), `exposed_to_theme` (w=0.80), `supplier_of` (w=0.75). This is exactly what the seed migrations + the QA-iter1 KG state from memory (2026-04-30) inject. It is **not** a query-limit and **not** a graph-traversal-depth issue (depth=2 is requested) — it's data-sparseness. Fix is upstream (PLAN-0064 W6 / extraction pipeline), not frontend.

**Frontend fix**: add a fallback panel that, when `edges.length < 5`, surfaces the *available* extracted relations from `relations`/`evidence` as a textual list — analysts get something useful even when the graph is sparse.

### 1.5 "Overview is reportedly useless / poor information density" — CONFIRMED

The current Overview tab uses only **6 zones**:
1. CompactInstrumentHeader (good)
2. AISubheader strip (good)
3. OHLCVChart + SessionStatsStrip (good)
4. Right sidebar (12 metric rows + 2 sparklines) — fine
5. InstrumentTopNews (4 rows of headlines, **empty** for AAPL)
6. EntityGraphPanel (svg with 3 edges → looks empty)

It IGNORES the following components that already exist in `components/instrument/` and live in the **Fundamentals** tab:

| Component | What it shows | Endpoint |
|---|---|---|
| `EarningsHistoryChart` | EPS actual vs estimate, 8 quarters | `/v1/fundamentals/{id}/earnings-annual-trend` |
| `TechnicalSnapshot` | 50/200 MA, 52w hi/lo, beta, short ratio | `/v1/fundamentals/{id}/technicals` |
| `MarketPositionPanel` | Sector/industry rank, market-cap tier | derived from CompanyOverview |
| `AnalystConsensusStrip` | Forward EPS estimate, growth | derived from `fundamentals` |
| `OwnershipSnapshotPanel` | Insider %, institutional %, float | `/v1/fundamentals/{id}/share-statistics` |
| `InsiderTransactionsTable` | Recent insider buys/sells | `/v1/fundamentals/{id}/insider-transactions` |
| `RevenueTrendSparklines` | Revenue/margin sparks | `/v1/fundamentals/{id}` |

That is the redesign opportunity: not "build new", but "compose existing density into the Overview".

### 1.6 Side-finding — page-bundle returns NULL price + 0 bars (BACKEND BUG D-F1-007)

```
GET /v1/instruments/01900000-0000-7000-8000-000000001001/page-bundle
→ overview.quote = null
→ ohlcv.bars = []
```

But the standalone `/v1/quotes/{id}` returns price=213.86, +0.71%, and `/v1/companies/{eid}/overview` returns `bars: 63`. The page-bundle composer in S9 has a bug. **Frontend mitigation**: when bundle.quote is null, fire a fallback `useQuery(['quote', id])`. This is the F-UX-002 mitigation already noted in the existing audit.

---

## 2. Competitor-mirror map

For each Overview panel I propose, here is the competitor it is informed by.

| Proposed panel | Competitor reference | What we mirror |
|---|---|---|
| **Compact header (price/Δ/MktCap/PE/52w)** | Bloomberg DES, TradingView header, Yahoo header | Single row of identity + price + 4-6 KPIs |
| **AI brief subheader** | (Worldview-original — competitive moat) | – |
| **Performance bar (1D/5D/1M/6M/YTD/1Y/5Y/10Y)** | TradingView "Performance" strip, Finviz "Performance" row | 8 timeframe % chips, color-coded |
| **OHLCV candlestick chart** | TradingView, Bloomberg GIP, Finviz | Candlesticks + volume + MA50/MA200 + indicator overlay |
| **Session OHLV strip + crosshair HUD** | Bloomberg crosshair, TradingView crosshair | Live O/H/L/V + pointer-driven OHLC |
| **Key metrics rail (right, dense)** | Finviz metric matrix, Bloomberg DES side, Koyfin facts | 12-row stat block with color-coded P/E + 52w bar |
| **Forward earnings + analyst consensus** | TradingView "Forecasts", Finviz "Target Price" + "Recom" | Forward EPS estimate, est revenue, # analysts, growth |
| **Earnings history mini-chart** | Yahoo "Earnings", Koyfin earnings panel | 8-quarter EPS actual vs estimate bars |
| **Technical snapshot (50/200 MA, RSI, ATR, Short ratio, Beta)** | Finviz technicals row | 6-cell stat card with color-coded position vs MA |
| **Top news pulse** | Yahoo summary news, Bloomberg DES news, Finviz news box | Top 4 headlines with tier pill + relative time + empty-state CTA |
| **Insider activity strip** | Finviz "Insider Trading", Yahoo "Insider Transactions" | 5 most recent insider buys/sells |
| **Ownership snapshot** | Yahoo "Holders", Finviz "Insider Own / Inst Own" | Insider%/Institutional%/Float + pie or bar |
| **Entity graph + key relations list** | (Worldview-original moat — KG) | 460px sigma graph + textual relations list as fallback |
| **Splits & dividends panel** | Yahoo "Dividends & Splits", Finviz | DivYield/PayoutRatio/ExDate/LastSplit |

We deliberately keep the AI Brief + KG graph as our differentiators; the rest copies the table-stakes from the leading terminals.

---

## 3. Wireframe text representation

Target widescreen layout (≥1280px). All text dimensions in px. `[#]` is zone number for cross-reference.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ [1] CompactInstrumentHeader  56px  (back · TICK · exch · sector · price · Δ · 52W)│
├──────────────────────────────────────────────────────────────────────────────────┤
│ [2] AISubheader  20–80px  (single-line AI summary; expand for full brief)        │
├──────────────────────────────────────────────────────────────────────────────────┤
│ [3] PerformanceBar  22px  1D +0.71% │ 5D +2.1% │ 1M +5.4% │ ... │ 10Y +987%      │
├──────────────────────────────────────────────────────┬───────────────────────────┤
│  LEFT COL (flex-1)                                   │  RIGHT COL (w=300px)      │
│  ┌────────────────────────────────────────────────┐  │  ┌─────────────────────┐  │
│  │ [4] OHLCVChart  360px height                   │  │  │ [9] Key Metrics     │  │
│  │   candles + volume + MA50/MA200 + indicators   │  │  │   12 rows · 22px ea │  │
│  │   crosshair HUD overlay                        │  │  │   MKT CAP …         │  │
│  │   timeframe toolbar                            │  │  │   P/E   …           │  │
│  │   ChartToolbar (top)                           │  │  │   DIV   …           │  │
│  └────────────────────────────────────────────────┘  │  │   52W bar           │  │
│  [5] SessionStatsStrip 22px  O/H/L/V + crosshair OHLC │ │   …                 │  │
│  ┌────────────────────────────────────────────────┐  │  ├─────────────────────┤  │
│  │ [6] EarningsHistoryChart   140px               │  │  │ [10] Tech Snapshot  │  │
│  │   8q actual vs estimate bars                   │  │  │  50MA / 200MA pos   │  │
│  │   header: Q3'27 EPS est 9.62 (+9.3% YoY)       │  │  │  Beta · RSI · ATR   │  │
│  └────────────────────────────────────────────────┘  │  │  ShortRatio · Short%│  │
│  ┌────────────────────────────────────────────────┐  │  ├─────────────────────┤  │
│  │ [7] TopNews + InsiderActivityStrip  side-by-side│  │  │ [11] Ownership      │  │
│  │  [7a] Top news 4 rows · 22px each              │  │  │  Insider% Inst% Flt │  │
│  │  [7b] Insider 5 rows · 22px (date·who·side·$)  │  │  ├─────────────────────┤  │
│  └────────────────────────────────────────────────┘  │  │ [12] Splits & Div   │  │
│  ┌────────────────────────────────────────────────┐  │  │  Yield · Payout     │  │
│  │ [8] EntityGraph (sigma)  460px                 │  │  │  Ex-date · Last spl │  │
│  │   filter pills + strength slider + search      │  │  └─────────────────────┘  │
│  │   fallback: Top relations LIST below if <5 edges│ │                            │
│  └────────────────────────────────────────────────┘  │                            │
└──────────────────────────────────────────────────────┴───────────────────────────┘
```

Below 1280px the right column collapses below the left, becoming full-width.

Total visible content: **~1100px tall** (vs current ~720px), so the page needs `overflow-auto` (it already has it via `<TabsContent overflow-auto>`).

Information-density delta vs current:

| Metric | Current | Proposed | Δ |
|---|---|---|---|
| Distinct data panels | 6 | 12 | +6 |
| Datapoints visible | ~30 | ~80 | ~+50 |
| Empty-state-prone | 2 | 2 | – (but with deep-link CTAs) |
| Backend endpoints used | 2 | 6 | +4 |

---

## 4. Implementation diff summary

### 4.1 Top-5 highest-leverage panels — IMPLEMENTED in this session

I scoped the implementation to changes that fix the user-reported issues directly (chart blank, "black empty component", graph density, news empty, density) while reusing existing components. Five surgical edits:

1. **F-CHART-001 — Empty-bars empty-state** in `OHLCVChart.tsx`
   - When `data.bars.length === 0` and not loading, render a 360px-tall message panel ("No price data for this timeframe — try 1D or 1W") instead of a blank black canvas.
   - Closes the live-blocking case for AAPL on 5M / 1W timeframes.

2. **"Black empty component" fix** in `OverviewLayout.tsx`
   - Replace the orphan `<div className="h-[400px] bg-card/20"><EntityGraphPanel/></div>` with a flex-grow layout where the panel fills its host container, eliminating the 120px black void.
   - Make EntityGraphPanel SVG responsive: viewBox preserved, `width="100%" height="100%"` (was `width=320 height=280`).

3. **Top-relations fallback list** in `EntityGraphPanel.tsx`
   - When `edges.length < 5`, render the relations as a textual list below the SVG ("Apple Inc. → competes_with → Microsoft Corp · 0.85"). Analysts who land on a sparse graph still see useful info instead of staring at 3 lonely circles.

4. **Insider Activity strip** added to OverviewLayout
   - New `OverviewInsiderStrip` component placed alongside InstrumentTopNews. Pulls from `/v1/fundamentals/{id}/insider-transactions` (already returns 5+ records for AAPL). Renders 5 most recent rows.
   - Doubles the bottom-zone density: news (often empty) + insider (rich).

5. **Performance bar** in OverviewLayout (top of tab)
   - 8 timeframe chips (1D / 5D / 1M / 3M / 6M / YTD / 1Y / 5Y) — derived client-side from existing OHLCV bars (no new endpoint). Color-coded and tabular-nums.

### 4.2 Files touched

- `apps/worldview-web/components/instrument/OHLCVChart.tsx` (empty-state guard)
- `apps/worldview-web/components/instrument/OverviewLayout.tsx` (insider strip, performance bar, layout cleanup)
- `apps/worldview-web/components/instrument/EntityGraphPanel.tsx` (responsive SVG + fallback relations list)
- `apps/worldview-web/components/instrument/PerformanceBar.tsx` (NEW — 90 lines)
- `apps/worldview-web/components/instrument/OverviewInsiderStrip.tsx` (NEW — 130 lines)

### 4.3 Out-of-scope deferred work

The full 12-zone wireframe in §3 requires also moving `EarningsHistoryChart`, `TechnicalSnapshot`, `OwnershipSnapshotPanel`, and a new `SplitsDividendsPanel` from the Fundamentals tab into the Overview right sidebar. This is a 1-2 day refactor (must coordinate with FundamentalsTab to avoid duplication) and is out of scope for this 3h session. Recommended next wave: F-OV-2 (sidebar densification).

Also deferred (backend defects):
- D-F1-007 — page-bundle returns null quote + 0 bars (S9 composer bug)
- KG sparsity — only 3 edges for AAPL (PLAN-0064 / extraction pipeline)
- News-entity-link sparsity — 0 articles linked to AAPL despite 93 ingested

---

## 5. Files inspected

Primary read in full:
- `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx` (485 lines)
- `apps/worldview-web/components/instrument/OverviewLayout.tsx` (417 lines)
- `apps/worldview-web/components/instrument/OHLCVChart.tsx` (1282 lines, partial — focused on auto-scroll guards + data effect + empty-state)
- `apps/worldview-web/components/instrument/EntityGraph.tsx` (787 lines — full sigma version, used in Intelligence tab)
- `apps/worldview-web/components/instrument/EntityGraphPanel.tsx` (435 lines — Overview compact SVG version)
- `apps/worldview-web/components/instrument/InstrumentTopNews.tsx` (180 lines)
- `apps/worldview-web/components/instrument/CompactInstrumentHeader.tsx` (357 lines)
- `apps/worldview-web/components/instrument/InstrumentKeyMetrics.tsx` (partial)
- `docs/audits/2026-05-09-qa-beta-frontend.md` (full)

Live container probes:
- `POST /v1/auth/dev-login` — 200 OK
- `GET /v1/instruments/01900000-…/page-bundle` — quote=null, bars=0 (BACKEND BUG)
- `GET /v1/companies/11111111-…/overview` — bars=63 (works)
- `GET /v1/quotes/01900000-…` — 213.86 (works)
- `GET /v1/ohlcv/01900000-…?timeframe=1d` — populated; `=5m`/`=1w` empty
- `GET /v1/entities/11111111-…/graph?depth=2` — 4 nodes / 3 edges (data-sparse)
- `GET /v1/news/entity/11111111-…?limit=5` — 0 items (entity-link gap)
- `GET /v1/news/top` — 0 items (top-news source list empty)
- `GET /v1/fundamentals/01900000-…/insider-transactions` — populated (5+ records)
- `GET /v1/fundamentals/01900000-…/technicals` — populated (50MA, 200MA, beta, short)
- `GET /v1/fundamentals/01900000-…/earnings-trend` — populated (forward EPS estimates)
- `GET /v1/fundamentals/01900000-…/earnings-annual-trend` — populated
- `GET /v1/fundamentals/01900000-…/share-statistics` — populated (insider%, inst%)
- `GET /v1/fundamentals/01900000-…/splits-dividends` — populated (PayoutRatio, dates)
- `GET /v1/briefings/instrument/11111111-…` — populated (multi-paragraph LEAD)

Competitor research via WebFetch:
- Yahoo Finance AAPL quote summary
- Finviz AAPL quote (best density reference)
- TradingView NASDAQ-AAPL symbol (best timeframe-strip reference)

---

**End of audit.**
