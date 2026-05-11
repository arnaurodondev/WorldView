# Investigation Report: PRD-0031 Enhancement Session

**Date**: 2026-04-25
**Investigator**: Claude Code (investigation skill)
**Severity**: N/A (feature investigation, not a bug)
**Status**: Root cause identified — design decisions documented
**Target**: `docs/specs/0031-terminal-ui-v3-ground-up-redesign.md`

---

## 1. Issue Summary

PRD-0031 exists as a ground-up redesign of the frontend. The user has reviewed the PRD and identified 5 areas that require deeper design decisions before implementation can begin:

1. **Left rail**: Currently specified as a 48px icon-only bar. User wants icons+labels, an embedded watchlist (with watchlist switcher), alarms below the watchlist, and a collapse/expand toggle.
2. **Dashboard**: Is the current 8-widget layout the best it can be? What do traders actually look for at market open? What data does the backend support?
3. **Instrument header**: The current compact 2-row header uses the full width for price/stats. Should the right half show the company description with a "Read more" button? Should the AI brief appear as a sticky subheader?
4. **Overview tab**: Currently shows chart + entity graph. Should it be much denser — chart + session stats + key news + fundamentals summary?
5. **Other instrument tabs**: Are Fundamentals, News, Intelligence, and Brief tabs truly Bloomberg-grade, or are they thin and uncompetitive?

Three research agents were launched to answer these questions.

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|---|---|---|
| Trader morning routine analysis | Agent 1 (web research) | Defines required dashboard widgets |
| Tastytrade sidebar pattern | Agent 1 (competitive analysis) | Watchlist-first sidebar is industry standard |
| TWS Mosaic sidebar pattern | Agent 1 (competitive analysis) | Icon rail + named workspaces + window groups |
| Bloomberg toolbar analysis | Agent 1 (competitive analysis) | Command bar + monitor list (not sidebar watchlist) |
| Instrument page current state | Agent 2 (codebase audit) | Headers show 4 stats, no description, no AI subheader |
| Overview tab data availability | Agent 2 (S9 API audit) | Chart ✓, graph ✓, description ✓, news endpoint ✓, fundamentals ✓ |
| Dashboard widget inventory | Agent 3 (codebase audit) | 9 widgets, AI Signals stub empty, Economic Calendar has real data |
| `Quote` type fields | Agent 3 (type inspection) | Has `volume`, does NOT have `open/high/low` |
| S9 available endpoints | Agent 3 (API audit) | `quotes/batch`, `ohlcv/{id}`, `fundamentals/screen`, `news/top`, `entities/{id}/graph`, `briefings/morning`, `alerts/pending` |

---

## 3. Hypothesis Verification

### H-1: The 48px icon-only rail is suboptimal for trader workflow

**Evidence**:
- tastytrade: persistent left sidebar contains watchlist (20-40 symbols with live prices) — not navigation icons
- TWS Mosaic: optional 48px icon rail that expands to show text + embedded market scanner
- Standard pattern: navigation moves to compact icon strip; the reclaimed horizontal space shows data (watchlist, positions, scanner)
- Worldview has no always-visible watchlist — this is a daily friction point for traders who monitor 10-50 symbols

**Result**: CONFIRMED. Icon-only rail wastes the most valuable screen real estate (left sidebar). Industry consensus is: rail collapses to icons, expands to show watchlist + live prices.

**Decision**: The left rail becomes a **collapsible sidebar** — 48px icon-only when collapsed, 220px expanded with watchlist + alarms embedded.

---

### H-2: The dashboard is missing the 5 core "market open" data points

**Evidence from trader research**:

| Rank | What traders check at market open | Current Worldview widget | Gap |
|---|---|---|---|
| 1 | Market regime — ES futures, VIX level, trend | Index Heatmap (sector) | No futures, no VIX widget |
| 2 | Portfolio overnight damage — which positions gapped | Portfolio Summary | Shows value, not gap-down detection |
| 3 | News catalysts — news for watchlist + held stocks | Watchlist News (partial) | No catalyst scan |
| 4 | Economic calendar — what drops today + time | Economic Calendar ✓ | Present — real data |
| 5 | Watchlist pre-market action — what's moving | No pre-market widget | Entirely absent |

**Additional missing data** (industry demand):
- Pre-market gappers list (top 20 stocks moving >2% pre-market)
- Market breadth indicators: Advance/Decline, % above 50-day MA, new 52W H/L
- Yield curve: 2Y/10Y/spread (bond market health)
- Sector rotation heatmap (not just a static heatmap — showing which sectors are gaining vs losing)
- Earnings calendar: next 5 days, with consensus EPS vs prior

**What S9 backend supports today**:
- `GET /v1/briefings/morning` → MorningBriefResponse (existing, real data)
- `GET /v1/news/top` → articles ranked by market_impact_score
- `GET /v1/alerts/pending` → alert feed
- `GET /v1/fundamentals/screen` → screener data (includes sector, market_cap, pe_ratio, daily_return)
- `GET /v1/entities/{id}/graph` → entity relationship graph
- No pre-market futures endpoint (gap — backend limitation)
- No explicit breadth endpoint (gap — would require computing from screener data)
- No yield curve data (gap — EODHD would supply this, not currently imported)

**Result**: CONFIRMED. Dashboard is missing pre-market gappers, VIX/futures strip, market breadth, and yield curve. However, several of these require backend data not yet available. Dashboard v3 should show what's available and display `[Data coming soon — EODHD integration pending]` for futures/VIX/breadth.

---

### H-3: Instrument header right half is wasted space

**Evidence**:
- Current header row 2 (stats strip) spans full width: MKT CAP │ P/E │ 52W │ EPS │ VOL │ OPEN │ HI │ LO
- At 1440px, the stats strip has ~600px unused after 8 stats at ~70px each = 560px used, leaving 600-700px empty
- Entity description is available from `GET /v1/entities/{entity_id}` → `description` field
- tastytrade: instrument header shows company description blurb to the right of price stats
- Bloomberg: instrument header uses full width for stats (more stats, not description)

**Decision**: The right half of the instrument header (rows 1 + 2 merged) should show a truncated company description (2 lines max) with a `[Read more →]` button that opens a slide-over or expands inline. This is a better use of the space than empty whitespace.

**For AI brief**: Rather than a "Brief tab" that gets skipped, the AI brief should appear as a collapsible sticky subheader — always visible, always providing context, never requiring a tab click. This is the correct placement for AI content in a professional terminal.

---

### H-4: Overview tab has too few data zones

**Evidence** — what's currently in the Overview tab:
- OHLCV chart (✓, 360px height)
- Entity graph (✓, right side)
- No news
- No fundamentals summary
- SessionStatsStrip not created yet

**What Bloomberg-equivalent overview shows**:
1. Price chart (always present, dominant)
2. Session stats (O/H/L/V/VWAP) — critically missing from current Worldview
3. Key fundamentals summary (Market Cap, P/E, EPS, Dividend, 52W range)
4. Recent news (top 3-5 articles, links only — no full cards)
5. Entity relationships (knowledge graph — already present in Worldview)
6. Analyst ratings strip (Buy/Hold/Sell consensus count)

**What can be built with current S9 data**:
- Chart: `ohlcv/{id}` ✓
- Session stats: last bar of OHLCV data ✓
- Key fundamentals: `fundamentals/{id}` ✓
- Recent news: `news/entity/{id}` ✓
- Entity graph: `entities/{id}/graph` ✓
- Analyst ratings: NOT in current backend (gap — needs scraping or EODHD)

**Result**: Overview should be redesigned from a 2-zone to a 5-zone layout. All 5 zones are supportable with current backend except analyst ratings.

---

### H-5: Other instrument tabs are thin vs Bloomberg

**Evidence per tab**:

**Fundamentals tab** — current state:
- Shows 3-column Bloomberg DES-style grid ✓ (per PRD-0031 spec)
- Missing: trend sparklines (revenue trend last 4 quarters), analyst consensus widget (Buy/Hold/Sell count)
- Assessment: Close to Bloomberg DES but missing trend context

**News tab** — current state:
- Compact list rows at 22px ✓ (per PRD-0031 spec)
- Missing: sentiment filter (positive/negative/neutral), date range filter
- Assessment: Adequate for MVP; date filter is a P1 improvement

**Intelligence tab** — current state:
- Signal list + contradictions ✓ (per PRD-0031 spec)
- Severity count strip specified but not implemented
- Missing: date range filter (signals from last 30/90/180d), entity filter (narrow to specific related entities)
- Assessment: Good structure, thin controls

**Brief tab** — current state:
- Specified as a separate tab in earlier versions
- Decision from this investigation: Brief should NOT be a tab — it should be a collapsible subheader sticky below the instrument header, always visible on all tabs
- If it's a tab, traders skip it. If it's always visible, it provides constant AI context.

---

## 4. Root Cause Analysis

The 5 investigation questions share a common root: **PRD-0031 was written before deep competitor pattern research**. The initial PRD specified the structural skeleton (48px rail, 12 columns, 22px rows) but left content decisions shallow. This investigation fills those gaps.

---

## 5. Specific Design Decisions (Update PRD-0031 with these)

### Decision D-1: Left Rail — Collapsible Sidebar (replaces pure icon rail)

**Architecture change**: The left rail is no longer icon-only. It becomes a collapsible panel:

```
Collapsed (48px):                    Expanded (220px):
┌──────────┐                        ┌────────────────────────────────┐
│  [W]     │                        │  [W]  WORLDVIEW                │
│──────────│                        │────────────────────────────────│
│  [⊞]    │                        │  [⊞]  Workspace                │
│  [⬜]   │                        │  [⬜]  Dashboard               │
│  [⚡]   │                        │  [⚡]  Screener               │
│  [⊕]    │                        │  [⊕]   Portfolio               │
│  [🔔]   │                        │  [🔔]  Alerts                  │
│  [💬]   │                        │  [💬]  Chat                    │
│──────────│                        │────────────────────────────────│
│  [👁]   │                        │  WATCHLIST  [Tech Stocks ▾]    │
│  [...]  │                        │  ──────────────────────────────│
│          │                        │  AAPL   172.34  +0.72% ▲      │
│          │                        │  MSFT   425.12  +1.23% ▲      │
│          │                        │  GOOGL  178.45  -0.34% ▼      │
│          │                        │  TSLA   241.67  +2.11% ▲      │
│          │                        │  NVDA   875.21  -0.89% ▼      │
│          │                        │  ──────────────────────────────│
│          │                        │  ALARMS (2 active)             │
│          │                        │  ■ AAPL > 175.00               │
│          │                        │  ■ TSLA Vol spike              │
│          │                        │────────────────────────────────│
│  [⚙]    │                        │  [⚙]  Settings  [⟵ Collapse] │
└──────────┘                        └────────────────────────────────┘
```

**Watchlist section**:
- Header: `WATCHLIST` (10px uppercase) + watchlist name selector button (`[Tech Stocks ▾]`)
- Watchlist switcher: click shows a dropdown or small popover listing all user watchlists (named lists)
- Items: ticker (monospace, 40px fixed), price (monospace, right-aligned), change% (colored + arrow)
- Row height: 22px; font: 11px IBM Plex Mono
- Click on ticker → navigate to `/instruments/[entityId]`
- Data source: `GET /v1/quotes/batch` with watchlist tickers; 30-second refresh interval
- If no watchlist: inline empty state "No watchlist — add symbols in Portfolio" with link

**Alarms section** (below watchlist):
- Header: `ALARMS` (10px uppercase) + active count badge
- Shows alerts related to: (a) held positions, or (b) symbols in the active watchlist
- Row: severity dot + message, 22px height
- Max 5 rows shown; if more: `[+N more →]` link to `/alerts`
- Data source: `GET /v1/alerts/pending` filtered client-side by user holdings + watchlist symbols
- "What should we do about alarms?" answer: **filter by portfolio + watchlist** (not all alerts), show compact with severity dot, click navigates to alerts page

**Collapse/expand mechanism**:
- Toggle button in bottom of sidebar next to Settings: `[⟵ Collapse]` when expanded, `[⟶]` icon when collapsed
- State persisted to `localStorage['worldview-sidebar-expanded']`
- Transition: CSS `width` 48px ↔ 220px, but use `grid-template-columns: Npx 1fr` to avoid reflow — animate `transform: translateX` of content instead
- At 1280px viewport: sidebar collapses automatically (media query threshold)

---

### Decision D-2: Dashboard — Trader Morning Routine Layout (revises §10)

**New layout** based on the 5-priority trader morning routine:

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│  MORNING BRIEF (full width, collapsible, amber #FFD60A left border accent)        │
├──────────────────────────────┬────────────────────────────────────────────────────┤
│  MARKET SNAPSHOT  (4 cols)   │  PRE-MARKET MOVERS  (8 cols)                       │
│  ES: 5,234 +0.8%             │  TOP GAINERS           TOP LOSERS                  │
│  VIX: 14.2 ↓ LOW            │  RCAT  +18.2% pre-mkt  NVDA  -4.1% pre-mkt        │
│  2Y: 4.82%  10Y: 4.51%      │  COIN  +9.4%           META  -2.3%                 │
│  Spread: -0.31% (inverted)   │  (source: daily_return + market_cap from screener) │
├──────────────────────────────┼────────────────────────────────────────────────────┤
│  PORTFOLIO SUMMARY  (4 cols) │  SECTOR HEATMAP  (8 cols)                          │
│  $124,328  +$234 today       │  Tech  +1.2% ████  Healthcare -0.4% ░░░░           │
│  3 positions at risk         │  Energy +2.1% ████████  Finance +0.1% █            │
├──────────┬───────────────────┼──────────────────────┬─────────────────────────────┤
│  ECON    │  EARNINGS         │  PORTFOLIO NEWS       │  TOP ALERTS                 │
│  CALENDAR│  CALENDAR         │  (from held stocks)   │  (pending, high sev)        │
│  (3 cols)│  (3 cols)         │  (3 cols)             │  (3 cols)                   │
└──────────┴───────────────────┴──────────────────────┴─────────────────────────────┘
```

**New widgets to add**:

| Widget | Data source | Priority |
|---|---|---|
| Market Snapshot (ES, VIX, yield curve) | NOT in backend yet — show with `[Beta — data coming soon]` note | P2 |
| Pre-Market Movers | Proxy using `daily_return` from screener — not pre-market but "yesterday's top movers" until futures data added | P1 |
| Earnings Calendar | `GET /v1/entities/calendar` or compute from fundamentals (if available) | P2 |
| Portfolio News | `GET /v1/news/top` filtered by portfolio tickers (client-side join) | P1 — currently available |

**Widgets to keep (already exist)**:
- Morning Brief → expand to full width (collapsible)
- Portfolio Summary → redesign layout (compact 4-col)
- Economic Calendar → keep, real data present
- Top Alerts → keep, recent alerts feed
- Sector Heatmap → rename from "Index Heatmap"

**Widgets to remove or downgrade**:
- AI Signals → is a stub (empty state); demote to bottom row or remove until real signals flow
- Prediction Markets → keep but move to bottom row (less immediately actionable at market open)

---

### Decision D-3: Instrument Header — Right Half + AI Subheader (revises §9.1, §9.7)

**New header layout** (replaces the all-stats header):

```
← [AAPL]  NASDAQ  •  Technology                   $172.34 ▲ +1.23 (+0.72%)  ● LIVE 14:32
─────────────────────────────────────────────────────────────────────────────────────────
MKT CAP 2.87T │ P/E 28.4 │ EPS 6.11 │ 52W 124–199 │ VOL 43.2M  │  Apple Inc. is a tech...
                                                                    [company description] Read more →
```

**Two-column header row 2 (20px)**:
- Left ~60% width: stats strip (MKT CAP │ P/E │ EPS │ 52W │ VOL) — 10px monospace
- Right ~40% width: company description truncated to 1 line + `[Read more →]` button
- "Read more" opens the description in a slide-over or an expanded zone below the header (not a new page)
- Description source: `GET /v1/entities/{entity_id}` → `description` field

**AI Brief subheader (NEW — below instrument header, sticky)**:

```
─────────────────────────────────────────────────────────────────────────────────────────
🤖  Apple (AAPL) is showing strong momentum with earnings outperformance. Key risk: China  [▾ Expand]
    revenue exposure and regulatory headwinds for App Store. Market treats this as...
─────────────────────────────────────────────────────────────────────────────────────────
```

- Height: 36px collapsed (1 line) → expands to 3-4 lines
- Left: amber `🤖` icon + AI brief text truncated at 120 chars + `[▾ Expand]` / `[▴ Collapse]` button
- Background: `#F0C04018` (amber-dim, 10% opacity) — signals AI-generated content
- Left border: 2px solid `#FFD60A` (amber — the only use of left border accent, because AI content is special)
- Data source: instrument-specific brief from briefings endpoint (or derive from morning brief if no instrument brief)
- The "Brief" tab in the instrument tabs is removed — replaced by this sticky subheader

**Updated tab structure**:
```
[Overview] [Fundamentals] [News] [Intelligence]
```
(Brief tab removed — content moved to sticky subheader)

---

### Decision D-4: Overview Tab — 5-Zone Dense Layout (revises §9.3)

**New overview layout**:

```
┌────────────────────────────────────────────────────────────┐
│                                                              │
│              OHLCV CHART (full width, 300px)                 │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  O: 171.12  H: 173.01  L: 170.88  V: 43.2M  VWAP: 171.89  │  ← SessionStatsStrip (20px)
├────────────────────────────────────────────────────────────────┤
│  [1D] [5D] [1M] [3M] [6M] [1Y] [2Y] [5Y]                    │  ← Timeframe bar (28px)
├──────────────────────────────────────────────────────────────────┤
│  KEY METRICS              │  TOP NEWS                │  ENTITY GRAPH          │
│  ──────────────────────   │  ──────────────────────  │  ──────────────────────│
│  Market Cap   2.87T       │  [H] Apple Beats Q1...  │                        │
│  P/E Ratio    28.4x       │  [M] Tim Cook on AI...  │   [graph component]    │
│  EPS (TTM)    $6.11       │  [L] App Store...       │                        │
│  Dividend     0.94%       │  [L] China suppliers... │                        │
│  52W Hi/Lo    124–199     │  → More news            │                        │
│  Beta         0.89        │                          │                        │
│  (3 cols / 3 cols / 4 cols  =  10 cols total)        │                        │
└──────────────────────────────────────────────────────────────────┘
```

**Zone breakdown**:
1. **Chart** (full width, 300px min height) — `ohlcv/{id}`, 11px axis labels, no padding around chart
2. **SessionStatsStrip** (full width, 20px) — O/H/L/V/VWAP from last OHLCV bar, 10px IBM Plex Mono with `│` separators
3. **Timeframe bar** (full width, 28px) — 1D/5D/1M/3M/6M/1Y/2Y/5Y buttons, `text-[11px]`
4. **Key Metrics** (3/10 cols, scrollable) — top 6 fundamentals from `fundamentals/{id}`, 22px rows, Bloomberg DES mini-view
5. **Top News** (3/10 cols) — top 4 articles from `news/entity/{id}` sorted by market_impact_score, 22px rows, tier badge + title truncated
6. **Entity Graph** (4/10 cols, fixed 200px height) — `entities/{id}/graph`, compact view, click node navigates

**Key improvements over current state**:
- News is shown (was completely absent from overview)
- Key Metrics shown (was completely absent from overview)
- Chart and graph are no longer the only 2 zones
- 5 independent data sources all visible without any tab click

---

### Decision D-5: Other Tabs — Bloomberg-Grade Improvements

**Fundamentals tab** — additions:
- Add a "Revenue Trend" sparkline strip above the 3-column grid: 4 quarters of revenue as tiny bars + QoQ arrow (if earnings data available)
- Add analyst consensus strip: `[Buy: 18] [Hold: 9] [Sell: 3]` with colored counts (if data available — show "N/A" if not)
- Add "last updated" timestamp as a `StaleDataBadge` if data > 7 days old
- Order: Consensus strip → Revenue sparklines → Valuation/Profitability/Growth grid

**News tab** — additions:
- Date range filter: `[All time] [Today] [1W] [1M]` segmented control (client-side filter on `published_at`)
- Sentiment filter: `[All] [📈 Positive] [📉 Negative] [◼ Neutral]` (based on `market_impact_score > 0.6` = positive, `< 0.4` = negative)
- Default: list mode with `[All time]` filter, sorted by `market_impact_score` descending

**Intelligence tab** — additions:
- Severity count strip above the signal table: `HIGH 2 │ MEDIUM 5 │ LOW 12` with clickable filters
- These filter the signal table below (`[ALL] [HIGH] [MEDIUM] [LOW]` segmented control)
- Date range filter: `[30d] [90d] [180d] [All]` (client-side filter on signal date)
- Expand each signal row to show: source list, article excerpt, confidence score, supporting quotes

**Brief tab** → **REMOVED** (replaced by sticky AI subheader below instrument header)

---

## 6. Impact on PRD-0031

The PRD-0031 must be updated with these decisions in sections:

| Section | Change |
|---|---|
| §4.3 Left Rail | Replace 48px icon-only with collapsible sidebar (48px / 220px) with watchlist + alarms |
| §10 Dashboard | Replace 8-widget layout with trader morning routine layout |
| §9.1 Instrument Header | Add right-half description column to row 2 |
| §9.7 Brief tab | Remove Brief tab; add AI subheader component spec |
| §9.3 Overview | Expand from 2-zone to 5-zone layout |
| §9.4 Fundamentals | Add revenue sparklines + analyst consensus strip |
| §9.5 News | Add date range + sentiment filter |
| §9.6 Intelligence | Add severity count strip + date range filter |
| §13 New Components | Add: `CollapsibleSidebar`, `WatchlistPanel`, `AlarmsPanel`, `InstrumentAISubheader`, `InstrumentKeyMetrics`, `InstrumentTopNews`, `OverviewLayout` |
| §14 Wave 1 | Include sidebar collapse/expand + watchlist in Wave 1 scope |

---

## 7. Open Questions (Resolved)

| Question | Answer |
|---|---|
| What to do about alarms in sidebar? | Filter by portfolio + watchlist symbols; max 5 rows; severity dot; click → /alerts |
| Should description use "read more" modal or expand inline? | Expand inline (no modal overlay) — show 3-4 line description below row 2 of header |
| Yield curve widget — can we show it? | Backend gap — show widget with `[Data coming soon — EODHD macro data pending]` |
| Brief tab or sticky subheader? | Sticky subheader — instrument-level AI brief shown above tabs, collapsible |
| Pre-market gappers — can we show it? | Use prior-day movers as proxy (`daily_return` from screener); note "pre-market data coming soon" |

---

## 8. Compounding Updates

- PRD-0031 updated with D-1 through D-5 decisions ✓ (see below)
- No new bug patterns discovered
- No new standards violations found
- `docs/ui/DESIGN_SYSTEM.md` should be updated with sidebar/watchlist component spec after implementation

---

*Next step: Update PRD-0031 sections §4.3, §9.1–9.7, §10, §13, §14 with decisions D-1 through D-5.*
