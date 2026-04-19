# Worldview Frontend — Design Agent Brief
## PRD-0027 Resolution: Cold Amber Visual Identity System
**Issued:** 2026-04-13
**Status:** APPROVED — Ready for canvas execution
**Resolves:** OQ-14 (Direction: E4 Cold Amber) · OQ-15 (Fonts: Inter + JetBrains Mono)

---

## 1. Design Direction: Cold Amber (E4)

Direction E4 was selected. It combines a deep navy background with a restrained, muted amber accent and semantic red reserved exclusively for risk/alert states. It reads as the most institutional of the hybrid explorations — closer to Koyfin's precision than Bloomberg's aggression, while carrying genuine warmth that separates it from the cold TradingView clone.

**Design character:** Dense, authoritative, warm. Every pixel earns its place. No decoration. No empty states. No gradients. If a space is empty, fill it with data.

---

## 2. Finalized Token System

### 2.1 Color Tokens

```
/* Surfaces */
--bg-base:        #0B0F1A   /* page background — deep navy */
--bg-surface:     #111827   /* cards, panels, sidebars */
--bg-elevated:    #1a2236   /* modals, tooltips, dropdowns */
--bg-hover:       #1f2d47   /* row hovers, button hovers */
--bg-selected:    #243352   /* active nav, selected rows */

/* Borders */
--border-subtle:  rgba(255,255,255,0.06)   /* panel separators */
--border-default: rgba(255,255,255,0.10)   /* card outlines */
--border-strong:  rgba(255,255,255,0.18)   /* focused inputs */
--border-amber:   rgba(217,119,6,0.35)     /* amber accent borders */

/* Accent — Amber */
--amber:          #D97706   /* primary accent — nav active, links, highlights */
--amber-muted:    #92510A   /* secondary amber — subtitles, inactive */
--amber-dim:      rgba(217,119,6,0.12)     /* amber fill backgrounds */
--amber-glow:     rgba(217,119,6,0.08)     /* very faint amber wash */

/* Data — Positive */
--pos:            #10B981   /* gains, positive delta */
--pos-muted:      rgba(16,185,129,0.15)    /* positive background fill */

/* Data — Negative */
--neg:            #E55050   /* losses, negative delta */
--neg-muted:      rgba(229,80,80,0.15)     /* negative background fill */

/* Risk / Alert (red is ONLY used here — never decorative) */
--risk:           #C0392B   /* regime shift, drawdown alerts, critical flags */
--risk-muted:     rgba(192,57,43,0.15)     /* risk indicator backgrounds */

/* Text */
--text-primary:   #E8ECF4   /* main labels, prices */
--text-secondary: #8A96B0   /* subtitles, metadata */
--text-tertiary:  #4A5568   /* timestamps, footnotes, placeholders */
--text-amber:     #D97706   /* ticker symbols, active labels */
--text-disabled:  #2D3748   /* inactive states */
```

### 2.2 Typography

```
/* Load via Google Fonts — add to <head> */
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">

/* Rules */
--font-ui:    'Inter', system-ui, sans-serif          /* ALL UI chrome */
--font-data:  'JetBrains Mono', 'Courier New', mono   /* ALL numeric data */

/* Scale */
--text-xs:    11px / 1.4   /* timestamps, footnotes, axis labels */
--text-sm:    12px / 1.5   /* table cells, badges, secondary labels */
--text-base:  13px / 1.6   /* body, sidebar items, form fields */
--text-md:    15px / 1.5   /* section headings, card titles */
--text-lg:    18px / 1.4   /* page titles, major metrics */
--text-xl:    24px / 1.2   /* hero numbers, KPI values */
--text-2xl:   32px / 1.1   /* landing headline */

/* Data-specific */
Prices, returns, percentages, counts → JetBrains Mono, always
Ticker symbols → JetBrains Mono 500, --text-amber
Labels, nav, headings → Inter
```

### 2.3 Spacing & Layout

```
--radius-sm:  3px    /* badges, tags, small chips */
--radius-md:  5px    /* cards, inputs, dropdowns */
--radius-lg:  8px    /* modals, large panels */

--panel-gap:  1px    /* gap between panels (creates dark seam) */
--cell-h:     32px   /* standard table row height */
--header-h:   48px   /* global top nav height */
--sidebar-w:  220px  /* left nav collapsed width */
--sidebar-x:  56px   /* left nav icon-only width */
```

---

## 3. Canvas Execution Rules

### 3.1 Frame Layout (MANDATORY)

Every frame in pencil.dev must follow this structure:

```
┌─────────────────────────────────────────────────────────────────┐
│  PAGE NAME — [default state]                    1440 × 900px    │
│  [HORIZONTAL FULL-WIDTH DESIGN — PRIMARY STATE]                 │
├─────────────────────────────────────────────────────────────────┤
│  STATE B: [description]                         1440 × 900px    │
│  [HORIZONTAL FULL-WIDTH DESIGN — SECOND STATE]                  │
├─────────────────────────────────────────────────────────────────┤
│  STATE C: [description]                         1440 × 900px    │
│  [HORIZONTAL FULL-WIDTH DESIGN — THIRD STATE]                   │
└─────────────────────────────────────────────────────────────────┘
```

- All frames: **1440px wide × 900px tall**, horizontal landscape
- States stack **vertically** in the canvas, separated by a 48px gap with a state label
- Each state is a fully realized, pixel-complete design — not a wireframe
- A "Toggle State" button must be visible in the design itself, showing which state is active
- Every page must be **at minimum 70% filled with real data** — no placeholder lorem ipsum, no empty panels

### 3.2 Data Realism Requirement

Use realistic financial data throughout. Reference these real instruments:
- Equities: AAPL $189.42 (+2.14%), TSLA $241.08 (−1.33%), NVDA $875.40 (+4.82%), MSFT $415.60 (+0.87%), AMZN $192.80 (−0.44%)
- Indices: S&P 500 5,248.32 (+0.29%), NDX 18,421.10 (+0.51%), VIX 14.82 (−0.93%)
- News: Use plausible financial headlines with realistic timestamps (e.g. "Fed signals pause as inflation cools", "NVIDIA raises FY2026 guidance on datacenter demand")
- Entity scores, sentiment values, momentum signals: use precise decimal values (e.g. Momentum Score 0.742, Regime Confidence 87.3%)

### 3.3 Component Anatomy

Every page must include these standard shell components:

**Global Nav (top, 48px):**
- Left: Worldview wordmark in Inter 600 + amber dot
- Center: Global search bar (JetBrains Mono placeholder)
- Right: Market status indicator (OPEN/CLOSED with dot), notification bell, user avatar

**Left Sidebar (220px, collapsible to 56px icon-only):**
- Nav items: Dashboard · Markets · Intelligence · Screener · Portfolio · Graph · Settings
- Active item: amber left-border accent + amber text + `--bg-selected` fill
- Bottom: API status dot (green = healthy), latency (JetBrains Mono)

**Status Bar (bottom, 24px):**
- Scrolling market tape: ticker + price + delta, separator `|`, continuous
- Right: Last updated timestamp, data source tag

---

## 4. Page-by-Page Specification

---

### PAGE 1 — Landing / Marketing

**Purpose:** First impression for prospective users. Must communicate institutional-grade credibility immediately.
**Competitive benchmark:** No other financial platform uses gradient hero text → we use none. Study Koyfin's landing for density-without-noise.

#### State A: Hero (Default)
- Full-bleed `--bg-base` background
- Top nav: logo left, "Sign In" + "Request Access" buttons right (amber outline + amber fill)
- Hero left column (55% width):
  - Eyebrow: `FINANCIAL INTELLIGENCE PLATFORM` in Inter 500 11px `--text-amber` spaced 0.15em
  - Headline: 48px Inter 600 `--text-primary` — "Every signal. Every market. One graph."
  - Subhead: 16px Inter 400 `--text-secondary` — two lines max, describe the 10-service architecture
  - Two CTAs: "Request Early Access" (amber filled) + "View Live Demo" (ghost amber border)
  - Below CTAs: three trust signals in a row — "10 Data Services" · "Real-Time Kafka Streams" · "Graph-Native Intelligence"
- Hero right column (45% width):
  - Faux terminal window: `--bg-surface` panel with macOS-style title bar in `--bg-elevated`
  - Title bar label: `worldview://intelligence/stream` in JetBrains Mono 11px `--text-tertiary`
  - Inside: live-looking event stream — timestamped lines of financial events in JetBrains Mono 12px, amber for entity names, green for positive signals, red for risk flags
  - Subtle amber border on the terminal window left edge: 2px `--border-amber`
- Below fold: three feature columns with icon + title + 2-line description (no screenshots)

#### State B: Logged-in redirect / Dashboard preview
- Same nav but user avatar shown
- Hero replaced with a 3-panel preview strip showing Dashboard, Intelligence, and Graph pages at 30% opacity as teasers
- CTA changes to "Open Dashboard →"

#### State C: Mobile / 375px responsive
- Single column stack
- Terminal hidden
- Headline reduced to 32px
- Show design intent only (annotate as "375px breakpoint")

---

### PAGE 2 — Dashboard (Main)

**Purpose:** Primary home screen after login. Command center. Every key metric visible at a glance.
**Competitive benchmark:** Bloomberg packs 80%+ viewport. TradingView has zero breathing room on the watchlist. Match that density.

#### State A: Default (Market Open)
Layout: Left sidebar (220px) · Main content area (fluid) · Right panel (320px)

**Main content — top row (KPI strip, 72px tall):**
Six metric cards in a row, each showing:
- Label: `S&P 500` / `NDX` / `VIX` / `Portfolio Value` / `Day P&L` / `Signal Count`
- Value: JetBrains Mono 20px `--text-primary`
- Delta: JetBrains Mono 12px `--pos` or `--neg`
- Micro sparkline: 60px wide, 20px tall inline SVG

**Main content — center (two-column split):**
Left 60%: Watchlist table
- Columns: Ticker · Name · Price · Chg% · Volume · Mkt Cap · Momentum Score · Regime · Actions
- Row height 32px, alternating `--bg-surface` / `--bg-base`
- Momentum Score: inline bar (0–1 scale, amber fill)
- Regime column: pill badge (`BULL` green-fill / `BEAR` red-fill / `NEUTRAL` gray-fill)
- Minimum 12 rows visible

Right 40%: Intelligence feed
- Each item: amber left-border accent (2px) + headline (Inter 13px) + source tag + timestamp
- Sentiment badge: `+0.82` in green or `−0.41` in red (JetBrains Mono)
- Minimum 10 items visible, scrollable

**Right panel (320px):**
- Top: Mini chart (selected ticker) — OHLC or area, amber fill below line
- Below chart: Key stats grid (2-col): P/E · EPS · Beta · 52w Hi/Lo · Avg Vol · Market Cap
- Below stats: Entity relationships — "Related: NVDA → TSMC → ASML" as inline tags
- Bottom: Active alerts list — 3 most recent with risk-level icons

#### State B: Market Closed (After-hours view)
- Market status indicator flips to `CLOSED` (gray dot)
- Prices show AH price + AH delta in parentheses
- Intelligence feed highlights: "After-Hours Movers" section pinned at top
- Chart shows after-hours extension in dashed line style

#### State C: Collapsed sidebar (icon-only, 56px)
- Main content + right panel expand to fill
- Watchlist gains 3 more columns
- Sidebar shows only amber icons, no labels

---

### PAGE 3 — Company Intelligence Detail

**Purpose:** Deep-dive single entity view. The Bloomberg Terminal company page equivalent.
**Competitive benchmark:** Bloomberg Terminal F9 company view. Every datapoint visible, tabbed sub-sections, zero whitespace.

#### State A: Equity (e.g. NVDA)
Layout: Full width, no right panel. Content in sections.

**Header strip (72px):**
- Left: Ticker `NVDA` (JetBrains Mono 28px `--text-amber`) + full name (Inter 16px) + exchange badge + sector badge
- Center: Price `$875.40` (JetBrains Mono 32px) + delta `+4.82%` (20px `--pos`) + dollar change
- Right: Action buttons: `+ Watchlist` · `⚑ Alert` · `Share` · `Export`
- Below: stat strip — Market Cap · P/E · EPS · Beta · Volume · 52w Hi · 52w Lo — all in JetBrains Mono 12px, 7 columns

**Main area — two-thirds left:**
- Price chart: full OHLCV chart, amber line/candles, volume bars below (teal positive, red negative)
- Chart toolbar: 1D · 1W · 1M · 3M · YTD · 1Y · 5Y timeframe buttons + indicator dropdown
- Below chart: tabbed content — `Overview` · `Financials` · `Transcripts` · `Filings` · `Graph`
- Overview tab active: two-column grid of fundamental metrics, fully populated

**Right one-third:**
- Intelligence stream: filtered to NVDA only, same format as dashboard but narrower
- Entity graph mini-view: NVDA at center, connected nodes (TSMC, AMD, Microsoft, Jensen Huang) as a force-directed mini-graph
- Analyst consensus: Buy/Hold/Sell bar with count numbers

#### State B: Macro Entity (e.g. "Federal Reserve")
- No price header — replaced with entity type badge `INSTITUTION`
- Chart replaced with: influence timeline (horizontal bar chart of policy events)
- Intel stream shows Fed-related events, rate decisions, speeches
- Graph view shows Fed → connected banks, markets, officials

#### State C: Person Entity (e.g. "Jensen Huang")
- Photo placeholder circle (initials `JH`) + name + title + affiliation
- "Mentions" timeline replaces price chart
- Connected entities: NVDA, Softbank, Taiwan, TSMC, AI/ML sector
- Recent statements feed with date + sentiment score

---

### PAGE 4 — Markets Overview (Heatmap + Macro)

**Purpose:** Bird's-eye global markets view. Visual signal scanning.
**Competitive benchmark:** Finviz treemap density. TradingView's market overview. Every sector represented.

#### State A: Equity Heatmap (S&P 500)
- Full-bleed treemap filling main content area (no right panel)
- Tiles sized by market cap, colored by 1-day return:
  - Strong positive (>+3%): `--pos` at 90% opacity
  - Positive (+0 to +3%): `--pos` at 30–60% opacity scaled
  - Negative (0 to −3%): `--neg` at 30–60% opacity
  - Strong negative (<−3%): `--neg` at 90% opacity
- Each tile: Ticker (JetBrains Mono 12px 500 white) + Return% (JetBrains Mono 11px)
- Sector grouping: labeled with Inter 11px `--text-tertiary` dividers
- Top toolbar: `S&P 500` · `NASDAQ` · `Russell 2000` · `Global` toggle buttons
- Metric selector: `1D Return` · `1W` · `1M` · `Volume vs Avg` · `Momentum Score`

#### State B: Macro Dashboard
- Four quadrant layout:
  - TL: Yield curve (US 2Y, 5Y, 10Y, 30Y) — line chart
  - TR: FX rates grid (EUR/USD, GBP/USD, USD/JPY, DXY) — table with mini sparklines
  - BL: Commodity heatmap (Oil, Gold, Silver, Copper, Wheat) — simple tile grid
  - BR: Global indices table (SPX, DAX, FTSE, Nikkei, HSI, ASX) — JetBrains Mono table
- Each quadrant has a `--border-default` border, `--bg-surface` background

#### State C: Regime Map
- World map SVG (filled regions) — region colored by detected market regime:
  - Bull: `--pos` tint
  - Bear: `--neg` tint
  - Neutral: `--bg-elevated`
  - Crisis: `--risk` tint
- Right sidebar panel: regime legend + top 5 regime-shift signals (amber alerts)
- Below map: timeline of regime changes for selected region (last 12 months)

---

### PAGE 5 — Intelligence Feed

**Purpose:** Real-time financial news + AI-processed event stream. Core differentiator.
**Competitive benchmark:** Bloomberg News terminal + Refinitiv Eikon news feed. Every item has metadata.

#### State A: Full Feed (All Sources)
Layout: Left filter panel (240px) · Center feed (fluid) · Right entity spotlight (300px)

**Left filter panel:**
- Source filters: checkboxes for `SEC Filings` · `Earnings Calls` · `News Wire` · `Analyst Reports` · `Social Signals`
- Entity type filters: `Equity` · `Person` · `Institution` · `Macro Event`
- Sentiment filter: slider −1.0 → +1.0
- Date range picker
- Watchlist-only toggle (amber toggle switch)

**Center feed:**
Each item (52px height, `--border-subtle` bottom border):
- Col 1 (52px): Source icon placeholder + timestamp (JetBrains Mono 10px `--text-tertiary`)
- Col 2 (fluid): Headline (Inter 13px 500 `--text-primary`) + 1-line excerpt (Inter 12px `--text-secondary`)
- Col 3 (80px): Sentiment badge (JetBrains Mono 12px — e.g. `+0.82` in `--pos`)
- Col 4 (100px): Entity tags (amber pill chips — e.g. `NVDA` `TSMC`)
- Col 5 (32px): Bookmark icon
- Hover state: full row `--bg-hover`, left amber 2px border appears

**Right entity spotlight:**
- Auto-updates when item is hovered/selected
- Shows: entity name + type + current price (if equity) + 5 most recent items about this entity + related entities

#### State B: Filing Mode (SEC focus)
- Filter panel pre-selected to `SEC Filings` only
- Center feed columns change: Form Type (10-K/10-Q/8-K) · Filed Date · Filer · Key Extracted Items
- AI-extracted highlights shown inline under each filing row (collapsible, max 3 lines)

#### State C: Expanded Article View
- Left panel remains
- Center becomes single-article reader: headline + full extracted text (Inter 14px 1.7 line-height) + entity annotations highlighted in amber
- Right panel: same entity spotlight + "Related Articles" list below

---

### PAGE 6 — Graph / Knowledge View

**Purpose:** The core platform differentiator. Entity relationship network explorer.
**Competitive benchmark:** No direct comp exists at consumer scale. Reference: Bloomberg Industry Classification, Palantir Gotham network graph.

#### State A: Default Graph (NVDA neighborhood, depth 2)
- Full-bleed canvas (no sidebar panels, only floating controls)
- Force-directed graph:
  - NVDA: large amber node, center
  - Depth-1 neighbors (8 nodes): medium white nodes — TSMC, AMD, Microsoft, Softbank, Jensen Huang, CUDA ecosystem, Datacenter, AI/ML Sector
  - Depth-2 neighbors (20+ nodes): small gray nodes — individual chips, companies, people
  - Edges: 0.5px lines in `--border-default`, thickness scaled by relationship strength
  - Amber edges: direct causal relationships (thicker, `--border-amber`)
- Floating top bar: search box (JetBrains Mono) + depth selector (1/2/3) + layout selector (Force/Radial/Tree) + filter icon
- Floating bottom-left legend: node type key (Equity / Person / Institution / Concept / Event)
- Floating right mini-panel (240px): selected node detail — price if equity, key facts, last 3 intel items

#### State B: Timeline Mode
- Graph collapses to left 40% (static, no physics)
- Right 60%: horizontal timeline of events for selected node — each event is a dot on the timeline with a label, color-coded by type
- Scrubber at bottom controls time range
- Graph edges animate to show which connections were active at the selected time

#### State C: Comparison Mode (Two entities)
- Canvas splits vertically: left graph centered on NVDA, right graph centered on AMD
- Common shared nodes highlighted in amber on both sides
- Bottom strip: side-by-side stat comparison table — JetBrains Mono, 3-column (Metric | NVDA | AMD)

---

### PAGE 7 — Screener

**Purpose:** Multi-factor stock/entity filtering and ranking tool.
**Competitive benchmark:** Finviz screener density. Koyfin screener UX. Every filter visible, no hidden options.

#### State A: Default (All Equities, sorted by Momentum Score)
Layout: Top filter bar (64px) · Results table (full remaining height)

**Filter bar:**
- Horizontal row of filter chips: `Market Cap: All ▾` · `Sector: All ▾` · `P/E: Any ▾` · `Momentum: Any ▾` · `Regime: Any ▾` · `Volume: Any ▾` · `+ Add Filter`
- Active filters shown as amber-filled chips with × close button
- Right side: `Columns ▾` · `Export CSV` · Results count (`4,892 results`)

**Results table:**
Columns (all sortable, JetBrains Mono data, Inter headers):
`#` · `Ticker` · `Name` · `Price` · `Chg%` · `Mkt Cap` · `P/E` · `EPS` · `Volume` · `Rel Vol` · `Momentum` · `Beta` · `Regime` · `Signal`

- Row height 28px (maximum density)
- Minimum 25 rows visible
- Momentum column: inline amber bar (0–1)
- Signal column: colored badge (`LONG SETUP` / `SHORT SIGNAL` / `WATCH`)
- Sticky header + alternating row backgrounds

#### State B: Filter Panel Open
- Right side: slide-in 320px filter panel overlaying results
- Panel sections: Fundamental · Technical · Worldview Scores · Geography
- Each section has range sliders, multi-select checkboxes
- Results count updates in real-time as filters change (show "Filtering..." state)

#### State C: Saved Screener / Alert Mode
- Top dropdown shows saved screener name: `Momentum Regime Bull >0.7`
- Alert toggle: "Alert me when new matches appear" (amber toggle)
- Last run timestamp visible in JetBrains Mono
- Historical matches section below table: sparkline showing match count over time

---

### PAGE 8 — Portfolio

**Purpose:** Personal/tracked portfolio performance and risk analytics.
**Competitive benchmark:** Koyfin portfolio analytics. Interactive Brokers risk dashboard.

#### State A: Performance View
Layout: Top KPI strip · Two-column below

**KPI strip (80px):**
`Total Value` $284,420.00 · `Day P&L` +$4,821.30 (+1.72%) · `Total Return` +$41,820 (+17.24%) · `Sharpe Ratio` 1.42 · `Max Drawdown` −8.32% · `Beta` 0.87

All values: JetBrains Mono, sized appropriately. P&L in `--pos`, Max Drawdown in `--neg`.

**Left 55%:**
- Portfolio value chart (area, amber line, subtle amber fill below)
- Time selector: 1D · 1W · 1M · 3M · YTD · 1Y · All
- Below chart: Holdings table — Position · Shares · Avg Cost · Current · Mkt Value · Gain/Loss · Weight%

**Right 45%:**
- Asset allocation donut (sector breakdown) — segments in amber gradient shades
- Below: Regime exposure bar — % of portfolio in Bull/Bear/Neutral/Risk-Off regimes
- Risk metrics panel: VaR 95% · Correlation to SPX · Portfolio Beta · Drawdown chart (small, 3-month)

#### State B: Transaction History
- Full-width table replacing chart: Date · Type · Ticker · Shares · Price · Total · Notes
- Filter by date range, type (Buy/Sell/Dividend)
- Running balance column (JetBrains Mono)

#### State C: Risk Mode
- Full-width risk dashboard
- Top: Correlation matrix heatmap (holdings vs each other + SPX, AGG, GLD) — amber/red color scale
- Bottom left: Factor exposure bars (Value / Momentum / Quality / Size / Volatility)
- Bottom right: Scenario analysis table — "What if SPX −10%?" → portfolio impact in `--neg`

---

### PAGE 9 — Settings + System

**Purpose:** API configuration, data source management, alert settings.
**Competitive benchmark:** Developer-grade settings. Reference Supabase dashboard settings, Vercel project settings.

#### State A: General Settings
Layout: Left settings nav (200px) · Right content (fluid)

**Left nav items:**
Profile · API Keys · Data Sources · Alerts · Notifications · Appearance · Billing · System Status

**Right content (API Keys section active):**
- Section header: "API Configuration" + descriptive subtitle
- API key row: key name + partial key `wv_live_••••••••3f9a` (JetBrains Mono) + Created date + Last used + Revoke button
- "Generate New Key" button (amber outline)
- Permissions matrix below: table of key × permission (read/write/admin) as checkboxes

#### State B: System Status
- Grid of 10 service health cards (one per microservice):
  - Service name (Inter 13px 500)
  - Status badge: `HEALTHY` (green) / `DEGRADED` (amber) / `DOWN` (red)
  - Latency: JetBrains Mono `12ms` in `--pos` or elevated value in `--neg`
  - Uptime %: JetBrains Mono
  - Mini latency sparkline (last 60 minutes)
- Bottom: Kafka topic lag table — topic name + consumer group + lag count + trend arrow

#### State C: Appearance / Design Tokens
- Live token editor: left column shows token name, right shows color swatch + hex input
- Preview panel on right: mini dashboard widget that updates live as tokens change
- Preset themes: Cold Amber (selected, amber border) · Midnight Pro · Amber Terminal — each as a small preview card

---

### PAGE 10 — Onboarding / Empty State

**Purpose:** First-time user experience. Must not feel like a dead app.

#### State A: Welcome / Connect Data
- Center-aligned content within the main area (sidebar shown, main area has welcome content)
- Large amber icon (abstract graph/node symbol, SVG) centered
- Headline: "Connect your first data source" (Inter 24px 600)
- Three connection cards in a row: `Interactive Brokers API` · `Alpaca Markets` · `Manual Import`
- Each card: `--bg-surface` + amber left border + name + description + "Connect →" button

#### State B: Watchlist Empty State
- Watchlist panel shows: centered icon + "No symbols tracked yet" (Inter 13px `--text-secondary`) + "Add from Screener" button (amber)
- Rest of dashboard shows sample/demo data with a banner: `Showing demo data — add to watchlist to see live data`
- Demo data has subtle `--bg-elevated` tint to distinguish from live

#### State C: Graph Empty State (no entity selected)
- Full-bleed graph canvas but empty — just the floating controls visible
- Center: large faint node circle (stroke-only, `--border-default`) + text "Search for an entity to begin" in JetBrains Mono `--text-tertiary`
- Below: suggested starting points as amber pill buttons — `NVDA` · `Federal Reserve` · `S&P 500` · `Jensen Huang`

---

## 5. Global Component Specs

### 5.1 Data Table (Universal)

```
Header row:    --bg-elevated, Inter 11px 500, --text-secondary, UPPERCASE, letter-spacing 0.06em
Data rows:     32px height, Inter/JetBrains Mono 12px, alternating --bg-base / --bg-surface
Hover:         --bg-hover, amber left border 2px appears
Selected:      --bg-selected, amber left border 2px permanent
Sort arrows:   amber when active, --text-tertiary when inactive
Pagination:    bottom right, Inter 12px, amber active page number
```

### 5.2 Chart Style

```
Background:    --bg-surface
Grid lines:    0.5px --border-subtle, horizontal only
Axis labels:   JetBrains Mono 11px --text-tertiary
Price line:    2px --amber, no glow
Area fill:     linear-gradient amber → transparent (10% → 0%), subtle
Candlestick:   --pos / --neg fill, 0.5px --border-default outline
Volume bars:   --pos-muted / --neg-muted
Crosshair:     1px dashed --border-strong
Tooltip:       --bg-elevated, --border-default 0.5px, JetBrains Mono values
```

### 5.3 Badge / Tag System

```
BULL / LONG SETUP:  --pos-muted bg + --pos text, --radius-sm
BEAR / SHORT:       --neg-muted bg + --neg text, --radius-sm
NEUTRAL / WATCH:    --bg-elevated bg + --text-secondary text
RISK / ALERT:       --risk-muted bg + --risk text (ONLY for actual risk)
Sector tags:        --amber-dim bg + --text-amber text
Entity tags:        --bg-elevated bg + --text-primary text, amber left 1px border
```

### 5.4 Input Fields

```
Background:    --bg-surface
Border:        0.5px --border-default, focus → --border-amber
Border-radius: --radius-md
Height:        34px
Font:          Inter 13px for text inputs, JetBrains Mono for numeric inputs
Placeholder:   --text-tertiary
Label:         Inter 11px 500 --text-secondary, uppercase, above field
```

---

## 6. What Must Not Appear (Anti-Patterns)

- **No gradient text** anywhere — not on headlines, not on numbers
- **No glows or shadows** — no `box-shadow`, no `text-shadow`, no blur
- **No red as decoration** — red (`--risk`) is reserved exclusively for risk/alert semantic meaning
- **No blue anywhere** — the design has no blue. None.
- **No empty panels** — if data is missing, show a skeleton loader row, not whitespace
- **No rounded corners > 8px** — this is a professional terminal, not a consumer app
- **No emojis** — use geometric SVG symbols for icons
- **No gradient fills on chart areas** — subtle transparent fade only, max 10% opacity at top
- **No Tailwind default colors** — every hex must come from the token system above

---

## 7. Execution Checklist (Per Page)

Before marking any page complete, verify:

- [ ] All surfaces use token system — no off-token hex values
- [ ] All numeric data uses JetBrains Mono
- [ ] All UI chrome uses Inter
- [ ] Amber used only as: accent, active state, ticker symbols
- [ ] Red used only as: losses, alerts, risk flags — never decorative
- [ ] Minimum 70% viewport filled with real data
- [ ] All three states designed, labeled, stacked vertically in canvas
- [ ] State toggle button visible within each design frame
- [ ] Header nav present on all app pages (not landing)
- [ ] Left sidebar present on all app pages, correct active state highlighted
- [ ] Bottom market tape present on all app pages
- [ ] No placeholder text — all copy is final or realistic sample data

---

## 8. Delivery Format

- **Tool:** pencil.dev at `apps/frontend/designs/worldview-mvp.pen`
- **Frame naming:** `01-Landing` · `02-Dashboard` · `03-Company-Detail` · `04-Markets` · `05-Intelligence` · `06-Graph` · `07-Screener` · `08-Portfolio` · `09-Settings` · `10-Onboarding`
- **Per frame:** Primary state first, then additional states stacked below with 48px gap + state label in Inter 12px `--text-tertiary`
- **After all 10 frames:** Create one final frame `00-Design-System` showing: color tokens, typography scale, component library (table row, badge, input, chart tooltip, nav item, status bar) — all on `--bg-base`

---

*End of brief. Questions? Raise a new OQ in PRD-0027 §14.*
