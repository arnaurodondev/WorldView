# Worldview DESIGN.md

> **Purpose**: Plain-text design system document following the [Stitch DESIGN.md format](https://stitch.withgoogle.com/docs/design-md/format/).
> Any AI agent reads this file to generate consistent Worldview UI without needing the full design system docs.
> Maintained by `/design-ui` skill. Update after every design session.

---

## 1. Visual Theme & Atmosphere

**Product positioning**: Bloomberg-grade financial intelligence. Without the Bloomberg bill.

**Design philosophy**: Fast. Dense. Unimpressed. This is a terminal, not a dashboard app. Data takes absolute precedence over chrome. Every pixel of UI must earn its place by conveying information. The interface recedes — the data speaks.

**Mood board references**:
- Bloomberg Terminal: data density, monochrome surfaces, zero decorative elements
- TradingView: chart-first layout, clean dark surfaces, professional UX
- Finviz: CompactTable density, sector heat grids, screener layout

**Anti-references** (never look like these):
- Crypto exchanges: neon glows, yellow accents, ticker-tape excitement
- Fintech startups: purple-to-blue gradients, oversized hero metrics, Stripe-style landing pages
- Generic SaaS: glassmorphism, nested cards, rounded-everything, "AI dark mode" cyan-on-dark

**Target user context**: Desktop, dual-monitor, used at market open and during after-hours research. Dark environment. High-stakes, focused mental state.

---

## 2. Color Palette

All colors specified in OKLCH (perceptually uniform). All neutrals tinted toward brand hue 245 (blue).

### Surface Scale (3 elevation levels — depth via lightness, not shadows)

| Token | OKLCH | Hex | Role |
|-------|-------|-----|------|
| `--background` | `oklch(8% 0.01 245)` | `#0a0f1e` | Page background |
| `--card` | `oklch(13% 0.015 245)` | `#131929` | Card / sidebar background |
| `--popover` | `oklch(19% 0.02 245)` | `#1e293b` | Elevated card / hover surface |
| `--border` | `oklch(28% 0.02 245)` | `#334155` | Dividers, borders |

### Text Scale

| Token | OKLCH | Hex | Role |
|-------|-------|-----|------|
| `--foreground` | `oklch(95% 0.005 245)` | `#f1f5f9` | Primary text |
| `--muted-foreground` | `oklch(64% 0.01 245)` | `#94a3b8` | Secondary text, labels |

### Semantic Colors

| Token | OKLCH | Hex | Role |
|-------|-------|-----|------|
| `--primary` | `oklch(58% 0.18 245)` | `#3b82f6` | CTA buttons, active links, focus rings |
| `--positive` | `oklch(63% 0.17 145)` | `#22c55e` | Price up, positive % change, success |
| `--negative` | `oklch(55% 0.20 25)` | `#ef4444` | Price down, negative % change, error |
| `--warning` | `oklch(72% 0.17 85)` | `#f59e0b` | Alerts, warnings, amber signals |

### HeatCell Gradient (7 steps for % change columns)

| Range | Color | Hex |
|-------|-------|-----|
| > +3% | Bright green | `#16a34a` |
| +1% to +3% | Soft green | `#4ade80` at 30% opacity over `--card` |
| 0% to +1% | Slate tint | `#1e293b` at 20% brighter |
| Flat (0%) | Surface | `--card` (no tint) |
| -1% to 0% | Soft red | `#f87171` at 20% opacity over `--card` |
| -3% to -1% | Medium red | `#dc2626` at 35% opacity over `--card` |
| < -3% | Deep red | `#7f1d1d` |

### Color Rules

- **Never use pure black (#000) or pure white (#fff)** — always tint toward hue 245
- **Never put gray text on any colored background** — use a shade of the background color instead
- **Never use the AI dark mode palette**: cyan-on-dark, purple-to-blue gradients, neon glow borders
- **60-30-10 rule**: 60% neutral surfaces, 30% text/borders, 10% accent. Overuse of `--primary` destroys its power.

---

## 3. Typography Rules

### Font Families

**UI / Body text**: Geist Sans (preferred) or Neue Haas Grotesk — geometric sans with excellent tabular figures at small sizes.

**Financial data / Monospace**: Berkeley Mono or JetBrains Mono — for all price values, % changes, numeric table cells.

**Banned fonts**: Inter, DM Sans, Plus Jakarta Sans, Outfit, Space Grotesk, IBM Plex Mono, Space Mono, Fraunces, Playfair Display — these are AI monoculture defaults.

### Type Scale (Fixed rem — NOT fluid clamp for app UI)

| Step | Size | Weight | Use |
|------|------|--------|-----|
| `text-xs` | 0.75rem / 12px | 400 | CompactTable data, labels, badges |
| `text-sm` | 0.875rem / 14px | 400 | Default table cells, card body, inputs |
| `text-base` | 1rem / 16px | 400 | Panel body text |
| `text-lg` | 1.125rem / 18px | 600 | Section headings |
| `text-xl` | 1.25rem / 700 | 700 | Page title, primary price display |
| `text-2xl` | 1.5rem / 24px | 700 | Hero price on Company Detail |

**Scale rule**: At minimum a 1.25× ratio between adjacent steps. Flat hierarchies where sizes are 1.1× apart read as single-weight.

### Financial Data Rules

- **All numeric columns**: `font-mono tabular-nums` — mandatory, prevents magnitude-comparison jitter
- **Right-align all numbers** in tables — `text-right`
- **Consistent decimal places**: 2dp for prices, 2dp for percentages (+/-), 0dp for volumes
- **Sign prefix**: `+1.23%` for positive, `-1.23%` for negative (always explicit sign)
- **Light text on dark**: Add `leading-[1.65]` instead of default `leading-[1.5]` — light type reads as lighter weight and needs more air

---

## 4. Component Stylings

### CompactTable (financial data density)

```
Row height: h-8 (32px)
Padding: px-2 py-1
Font: text-xs, font-mono tabular-nums for numeric columns
Number alignment: text-right
Header: text-xs font-medium text-muted-foreground uppercase tracking-wide
Hover: bg-popover transition-colors duration-75
Border: border-border border-t
```

### Standard Table

```
Row height: h-10 (40px)
Padding: px-4 py-3
Font: text-sm
```

### Card

```
Background: bg-card
Border: border border-border rounded-md
Padding: p-4 (standard) | p-3 (compact)
Only use cards for: actionable, distinct, comparable content
NEVER nest cards inside cards
```

### Button

```
Primary: bg-primary text-white hover:bg-primary/90
Ghost: hover:bg-popover text-muted-foreground hover:text-foreground
Destructive: bg-negative text-white
All buttons: rounded-md, h-9 (standard) | h-7 text-xs (compact)
Focus ring: ring-2 ring-primary ring-offset-2 ring-offset-background
```

### Badge / Tag

```
Standard: bg-popover text-foreground border border-border rounded-sm px-1.5 py-0.5 text-xs
Positive: bg-positive/15 text-positive border-positive/30
Negative: bg-negative/15 text-negative border-negative/30
Warning: bg-warning/15 text-warning border-warning/30
Severity CRITICAL: bg-negative text-white (filled, not tinted)
```

### Input / Filter

```
Background: bg-card border border-border
Focus: border-primary ring-1 ring-primary
Font: text-sm
Height: h-9
```

### Skeleton (loading state)

```
Background: bg-popover animate-pulse rounded
Shape: match the element it replaces exactly (same height, width, border-radius)
Duration: animation-duration: 1.5s
```

### 52WeekRangeBar

```
Container: horizontal frame, gap-0, relative positioning
Track: h-1.5 (6px), rounded-full, fill #334155 (border color), flex-1
Fill: h-full, fill #3b82f6 (primary), width = ((current - low) / (high - low)) * 100%
Dot: 12px × 12px ellipse, fill #3b82f6, positioned at fill endpoint
Labels row above: "52wk Low $124.17" (muted) | "Current: $173.42" (foreground, center) | "High $198.23" (muted)
Font: JetBrains Mono, text-xs
```

### ArticleCard (News Intelligence)

```
Container: bg-card border border-border rounded-md p-3, vertical layout
Header row: source logo (16px) + source name (text-xs muted) + timestamp relative (text-xs muted right-aligned)
Headline: text-sm font-semibold, 2-line clamp
Excerpt: text-xs text-muted-foreground, 3-line clamp
Badge row: NLPTierBadge + RelevanceBadge + ImpactSparkline
NLPTierBadge: DEEP=bg-emerald-900 text-emerald-400 | MEDIUM=bg-amber-900 text-amber-400 | LIGHT=bg-slate-800 text-slate-400 opacity-60
RelevanceBadge: "0.91" text-xs font-mono, colored by threshold (≥0.7 green · ≥0.4 amber · <0.4 slate)
ImpactSparkline: 20px tall inline SVG, multi-window (day_t0/t1/t2/t5) — only show with real data
```

### PanelWrapper (Workspace panels)

```
Container: bg-card border border-border rounded-md, vertical layout, overflow-hidden
DragHandle: h-2 (8px), bg-popover border-b border-border, cursor-grab, horizontal layout
  Left: panel label (text-xs uppercase tracking-wide text-muted-foreground) + ticker chip
  Right: [Link⊙] + [−Minimize] + [×Close] icon buttons (ghost, h-6 w-6)
PanelContent: flex-1 overflow-hidden (chart / table / chat fills this area)
```

### MorningBriefCard (Dashboard hero)

```
Container: fill #0c1628 (deeper than --card), border-border, rounded-md, p-4, full-width
Header row: BrainCircuit icon (primary, 20px) + "AI Morning Brief" (uppercase tracking-widest text-xs muted) + spacer + MarketOpenBadge
MarketOpenBadge: green ellipse 8px + "MARKET OPEN" text-xs text-positive
Attribution: "DeepSeek R1 · Generated 06:45 ET" text-xs muted
Brief text: text-sm leading-relaxed, text-foreground, 5–8 sentences
DO NOT use border-left on this card — AI identity is communicated via background tint + icon
```

### LivePriceBadge (freshness indicator)

```
Fresh (<30s):  green dot with animate-ping
Aging (30–300s): amber dot, no animation
Stale (>300s): red dot, no animation
```

### HeatCell

```
Applies the 7-step gradient defined in §2 to a table cell background
Text always: text-foreground (never change text color for contrast)
Transition: transition-colors duration-300
```

---

## 5. Layout Principles

### Spacing System (4pt scale with semantic tokens)

| Token | Value | Use |
|-------|-------|-----|
| `--space-xs` | 4px | Icon gaps, tight label spacing |
| `--space-sm` | 8px | Between related elements |
| `--space-md` | 16px | Panel padding, card padding |
| `--space-lg` | 24px | Between sections |
| `--space-xl` | 48px | Major page divisions |

**Rule**: Vary spacing for hierarchy. A section heading with 24px above and 8px below reads as more important than one with 16px on both sides. Identical padding everywhere kills rhythm.

### Page Layout

```
AppSidebar: 220px fixed left, sticky full-height
TopBar: 48px sticky, full-width minus sidebar
MainArea: flex-1, overflow-y-auto, px-6 py-4
Max-width: max-w-7xl mx-auto for constrained content pages
Full-width: no max-width for data-dense pages (Screener, Workspace)
```

### Panel Hierarchy

Every page has exactly one **primary panel** (largest surface, most data, most prominent). Secondary panels support it. Tertiary panels are filters, metadata, auxiliary.

### Grid Patterns

```
2-column data layout: grid grid-cols-[1fr_340px] gap-4
3-column dashboard: grid grid-cols-3 gap-4
Responsive card grid: grid grid-cols-[repeat(auto-fit,minmax(280px,1fr))] gap-4
Workspace panels: CSS grid with named areas, drag-to-reorder
```

### Responsive Strategy

```
lg (≥1024px): Full layout, sidebar visible
md (768–1023px): Sidebar as Sheet overlay, main full-width
sm (<768px): Single column, charts collapse to sparklines
```

---

## 6. Depth & Elevation

Depth via **surface lightness**, not drop shadows. Shadows are weak on dark backgrounds.

| Elevation | Surface | When to use |
|-----------|---------|-------------|
| 0 — Page | `--background` | Canvas, page fill |
| 1 — Resting | `--card` | Cards, sidebar, panels |
| 2 — Raised | `--popover` | Hover states, modals, dropdowns, tooltips |

```
z-index scale (semantic):
  dropdown: 50
  sticky: 100
  modal-backdrop: 200
  modal: 300
  toast: 400
  tooltip: 500
```

Shadows only for interactive elements on hover:
```
shadow-sm: box-shadow: 0 1px 2px oklch(0% 0 0 / 0.3)
shadow-md: box-shadow: 0 4px 8px oklch(0% 0 0 / 0.4)
```

---

## 7. Do's and Don'ts

### Do

- Right-align all financial numbers in tables
- Use `font-mono tabular-nums` for every price, %, volume cell
- Design all 8 interactive states: default, hover, focus, active, disabled, loading, error, success
- Use HeatCell coloring on % change columns in Holdings, Screener, Top Movers
- Use CompactTable (h-8, text-xs) for Holdings, Fundamentals, Insider Transactions
- Use TanStack Query with context-appropriate `staleTime` (fundamentals 5min, OHLCV 1min, news 30s)
- Expose keyboard shortcuts: `g+d`, `g+w`, `g+c`, `g+p`, `g+n`, `g+s` in sidebar shortcut strip
- Apply `ring-2 ring-primary ring-offset-2 ring-offset-background` for all focus rings
- Use ease-out-expo `cubic-bezier(0.16, 1, 0.3, 1)` for all enter animations
- Animate only `transform` and `opacity`; use `grid-template-rows: 0fr → 1fr` for height

### Don't

- **NEVER** use `border-left: Npx solid <color>` (N > 1px) on cards, rows, or alerts — it's the #1 AI design tell. Use background tints instead.
- **NEVER** use gradient text (`background-clip: text`)
- **NEVER** use gray text on any colored background
- **NEVER** use pure black (#000) or pure white (#fff) for surfaces
- Do not use glassmorphism (backdrop-blur as decoration)
- Do not nest cards inside cards — flatten with dividers and spacing
- Do not use identical card grids (same card, same size, icon+heading+text repeated)
- Do not use the "hero metric" template: giant number + label + gradient accent — it reads as a Stripe dashboard, not a terminal
- Do not use bounce or elastic easing in animations
- Do not animate layout properties (width, height, margin, padding)
- Do not use `sparklines` with no data or no scale — they convey nothing at <40px without context
- Do not round table corners above 4px — terminals are sharp, not bubbly
- Do not use fonts from the monoculture list: Inter, DM Sans, Plus Jakarta Sans, Space Grotesk, IBM Plex Mono

---

## 8. Responsive Behavior

| Breakpoint | Layout change |
|------------|--------------|
| `lg` (≥1024px) | Full layout: sidebar + main area |
| `md` (768–1023px) | Sidebar becomes Sheet drawer; hamburger in TopBar |
| `sm` (<768px) | Single column; CompactTable collapses non-essential columns; charts → sparklines |

**Touch targets**: All interactive elements minimum `h-10` (40px touch target) even if visually compact. Use `::after` pseudo-elements to expand tap area on icon buttons.

**Container queries** for components that appear in both sidebar and main area — use `@container` so the component adapts to its parent width, not the viewport.

---

## 9. Agent Prompt Guide

### Quick color reference (copy-paste into any AI prompt)

```
Background: #0a0f1e | Card: #131929 | Elevated: #1e293b
Text: #f1f5f9 | Labels: #94a3b8 | Borders: #334155
Primary: #3b82f6 | Positive: #22c55e | Negative: #ef4444 | Warning: #f59e0b
```

### Standard prompts for common components

**Data table (financial)**:
> Build a CompactTable: `h-8` rows, `px-2 py-1`, `text-xs`, numeric columns `font-mono tabular-nums text-right`. Hover: `bg-popover`. % change columns use HeatCell 7-step gradient. Header: uppercase tracking-wide text-muted-foreground.

**Panel with real-time data**:
> Build a panel on `bg-card border border-border rounded-md p-4`. Data from TanStack Query with staleTime appropriate to data type. Loading state: skeleton shimmer matching content shape. Error state: red border + retry button. Show LivePriceBadge freshness dot.

**Dark page layout**:
> Full-height layout: `bg-background`. Left: `AppSidebar` 220px fixed with nav items and keyboard shortcut hints (`g+<key>`). Right: `flex flex-col flex-1`. Top: `TopBar` 48px with page title, ⌘K hint, WS status dot, alerts badge. Main: `px-6 py-4 overflow-y-auto`.

**Chart component**:
> TradingView Lightweight Charts (lightweight-charts 4) on `bg-card border border-border rounded-md`. Dark theme: background `#0a0f1e`, grid lines `#334155`, text `#94a3b8`, up candles `#22c55e`, down candles `#ef4444`. Include TechnicalSnapshot strip below: Beta · MA50↑↓ · MA200↑↓ · RSI · Short Interest.

---

## 10. Designed Pages (Full Redesign, 2026-04-13)

Canvas: `apps/frontend/designs/worldview-mvp.pen`
Exported PNGs: `apps/frontend/designs/images/`
Design data samples: `apps/frontend/designs/data-samples.md` — realistic populated data for all 9 pages (AAPL financials, portfolio holdings, alerts, news articles, economic calendar, knowledge graph nodes)

**Canvas frame map** (x-offset, 1440px wide each, horizontally tiled):

| Page | Frame ID | x-offset | URL |
|------|----------|----------|-----|
| Landing | `QTjSz` | 0 | `/` |
| Dashboard | `ujopW` | 1520 | `/app/dashboard` |
| Company Detail | `xB3MZ` | 3040 | `/app/company/[entityId]` |
| Workspace | `OOfmd` | 4560 | `/app/workspace` |
| Screener | `4FOIb` | 6080 | `/app/screener` |
| Portfolio | `3MDeP` | 7600 | `/app/portfolio` |
| News | `EgNBX` | 9120 | `/app/news` |
| Chat | `KZ6kq` | 10640 | `/app/chat` |
| Companies | `9jXmA` | 12160 | `/app/companies` |

---

### Page 1 — Landing Page (`/`)

Node: `QTjSz` | x: 0

Sections (top→bottom):
1. **Navbar** — logo + nav links + "Sign In" ghost + "Start Free" primary CTA
2. **Market Ticker Strip** — `MARKET OPEN` badge + 6 live indices (SPY · QQQ · DIA · VIX · BTCUSD · EURUSD)
3. **Hero (2-col)** — Left: eyebrow "The Bloomberg Alternative" + H1 "Bloomberg-Grade Research. Without the Bloomberg Bill." + $29/mo social proof + dual CTAs. Right: product screenshot carousel (Workspace + Company Detail)
4. **Stats Bar** — 10M+ OHLCV data · 18 fundamentals sections · 500K+ knowledge graph relations · <5s AI answer
5. **Feature Spotlight** — full-width annotated Workspace screenshot with callout arrows + 3 bullet features
6. **Features Grid** — 6 cards: AI Research Copilot, Knowledge Graph, Prediction Markets, News Intelligence, 11-Panel Workspace, AI Daily Briefs
7. **Competitive Comparison Table** — 7-col: Platform | Price | Charts | Deep Fundamentals | AI | Knowledge Graph | Prediction Markets. Competitors: Bloomberg ($32K) · Koyfin · Finviz · TradingView. Worldview row highlighted `bg-primary/10 border-primary`. Bloomberg ✗ on AI/KG. Worldview ✓ on everything.
8. **Pricing** — $0 · $29/mo · $99/mo with feature lists
9. **FAQ accordion** — 4 questions (expandable)
10. **CTA** — "Bloomberg-Grade Research. Without the Bloomberg Bill." + dual CTA buttons + footer

Key route: public (no auth). Zitadel login initiated from "Sign In" / "Start Free" buttons.

**Design decision (2026-04-13)**: Replaced two-card "Traditional vs Worldview" comparison with a proper 7-column comparison table. The table is a conversion tool — scannable at a glance, with Worldview row highlighted. Node `dVPZo`.

---

### Page 2 — Dashboard (`/app/dashboard`)

Node: `ujopW` | x: 1520

Component tree:
```
DashboardLayout
  AppSidebar (220px fixed)
    NavItems: Dashboard · Companies · News · Screener · Workspace · Chat
    KeyboardHints: g+d · g+c · g+n · g+s · g+w · g+p
    UserAvatar (bottom)
  MainArea
    TopBar (48px)
      MarketStatusBadge ("14:32:07 ET · Market Open")
      IndexStrip (S&P500 · NDX · DJI · VIX)
      AlertsBell
      UserMenu
    PortfolioSummary
      PortfolioValue ($47,320.50)
      PnLDisplay ($+1,243.18 · +2.69%) ← both absolute + %
      LiveBadge ("LIVE" dark-green bg, letter-spaced)
    MorningBriefCard (HERO — full width, height 240px, fill #0c1628)
      BrainCircuit icon + "AI Morning Brief" label (letter-spaced uppercase)
      "DeepSeek R1 · Generated 06:45 ET" attribution (muted)
      MarketOpenBadge (green dot + "MARKET OPEN")
      Brief text (5–8 sentences, text-sm leading-relaxed)
    [PortfolioSummaryCard 1/3] [MarketHeatmapCard 2/3]
      HeatmapCard: 11 sector tiles (XLK · XLF · XLE · XLV etc.), 4-col grid
      Each tile: abbreviation + sector name + % (JetBrains Mono), HeatCell bg
    [TopMoversCard 1/3] [TopSignalsCard 1/3] [WatchlistNewsCard 1/3]
      TopMoversCard: two sub-cols "▲ Gainers" | "▼ Losers", 5 rows each
    [EconomicCalendarCard 1/2] [QuickStatsBar 1/2]
    RecentAlertsCard (full width)
      SeverityBadge per row (CRITICAL=red filled, HIGH=red tint, MEDIUM=amber, LOW=slate)
```

Data sources: portfolio/summary · market/screener · news/top · alerts (WS) · ai/morning-brief

Real-time: watchlist prices via WebSocket; alert stream via WebSocket

**Design decision (2026-04-13)**: MorningBriefCard is the visual hero — most vertical space on the page. No `border-left` stripe — AI identity communicated via `#0c1628` dark tint background + BrainCircuit icon. Dashboard height expanded from 900 → 1100px to accommodate.

---

### Page 3 — Company Detail (`/app/company/[entityId]`)

Node: `xB3MZ` | x: 3040

Component tree:
```
CompanyDetailLayout
  AppSidebar (reuse)
  MainArea
    CompanyHeader (3 rows)
      Row 1: [40px logo] [Company Name text-2xl bold] [AAPL badge] [NASDAQ badge] [Sector] [Industry]
      Row 2: [Price $173.42 text-4xl font-mono] [+$2.34 +1.37% colored] [Volume] [Avg Vol] [Mkt Cap]
      Row 3: 52WeekRangeBar (track with positioned dot at 66.5% = current/range)
        Low $124.17 ←──[●]──────────→ High $198.23
        Dot: 12px circle at proportional position, primary fill
      ActionButtons: "★ Add to Watchlist" · "Open in Workspace ↗" · "Share"
    TabBar: Overview · News · Fundamentals · Intelligence · Chat (URL hash nav)
    [Overview Tab — 2-col layout]
      Left col:
        OHLCVChart (TradingView Lightweight, h-420px, dark theme, green/red candles)
        Timeframe: 1D | 1W | 1M | 3M | 1Y | All
        Overlays: MA50 | MA200 | Volume
        TechnicalSnapshotStrip (Beta · MA50↑↓ · MA200↑↓ · RSI · Short%)
        InstrumentBriefCard (AI brief, model attribution badge)
        AnalystConsensusCard (target range bar + consensus pills)
        KeyMetrics 3×3 grid (CompactTable): P/E · P/B · P/S · Forward P/E · EV/EBITDA · PEG · ROE · Div Yield · Beta
      Right col:
        Recent news article cards
        Prediction Markets panel (probability bars + sparklines)
    [Fundamentals Tab]
      Annual | Quarterly toggle
      5 accordion groups (collapsible): Income & Growth · Balance Sheet · Cash Flow · Valuation · Company & Ownership
      All tables: CompactTable, font-mono tabular-nums text-right
    [Intelligence Tab]
      EntityGraph 60% (sigma.js force-directed, 500px height)
        Node types: company=blue · person=green · event=amber
        Edge labels: "CEO of", "competes_with", "board_member"
        Confidence slider in header
      SidePanel 40%: SimilarCompanies · Contradictions · PredictionMarkets
      RecentClaimsPanel (full width, collapsible)
      TemporalEventsPanel (full width, collapsible)
    [Chat Tab]
      Full-height ChatUI (SSE stream, intent badges, citation cards, contradiction alerts)
```

Data sources: entities/{id} · market/ohlcv/{ticker} · entities/{id}/fundamentals · entities/{id}/articles · entities/{id}/predictions · entities/{id}/ai-brief · chat (SSE)

**Design decision (2026-04-13)**: 52WeekRangeBar added to header Row 3. Implementation: a 6px-height track frame + a 12px ellipse dot positioned at `(currentPrice - low) / (high - low) * 100%`. Current price label above dot. Replaces text-only "52wk: $124.17 – $198.23" display. Node `pAz0m`.

---

### Page 4 — Workspace (`/app/workspace`)

Node: `OOfmd` | x: 4560

Component tree:
```
WorkspaceLayout (full-viewport, no max-width, react-grid-layout 12-col)
  AppSidebar (icon-only collapsed, 48px — only in Workspace)
  TopBar
    TickerSearch (typeahead, global context setter) · TimeframeSelector
    [+ Add Panel] dropdown (11 panel types) · SaveLayout · ResetDefault · ExportChart
  PanelGrid (react-grid-layout)
    ChartPanel (6×6): OHLCVChart + timeframe + MA overlay toggles
    NewsFeedPanel (6×6): ArticleCards with RelevanceBadge + NLP tier badges
    AlertsPanel (6×5): SeverityBadge rows + acknowledge button per row
    ChatPanel (6×5): SSE streaming, citation cards, entity context
    PanelWrapper (each panel):
      DragHandle (8px, cursor-grab, bg-popover border-b) + label + ticker chip + [Link⊙] + [−] + [×]
```

**Panel types available** (all 11): Chart · News · Alerts · Chat · Watchlist · Screener · Portfolio · Entity Graph · Prediction Markets · Heatmap · Fundamentals

Layout: react-grid-layout 12-column grid; panel sizes/positions persisted to S9 user preferences.
Real-time: OHLCV updates via WebSocket; alerts via WebSocket; AI chat via SSE.

**Design decision (2026-04-13)**: Workspace sidebar collapsed to 48px icon-only (no text labels). Text nodes on nav items set to `enabled: false`. WorkspaceMain width = 1392px (1440 − 48). This prevents the sidebar from competing with panel content.

---

### Page 5 — Screener (`/app/screener`)

Node: `4FOIb` | x: 6080

Component tree:
```
ScreenerLayout
  AppSidebar (220px, Screener active)
  ScreenerMain
    TopBar ("Screener" + "12 results" count badge)
    FiltersArea
      FilterRows (each: [Metric dropdown] + [Operator ≥/≤/between] + [Value] + [Remove ×])
        Sample filters: Market Cap ≥ $10B · P/E Ratio ≤ 25 · Daily % Change ≥ 0.5%
      "+ Add Filter" button row
      "Run Screener" primary button (blue, right-aligned)
    ResultsTable (CompactTable h-8 rows)
      Columns: TICKER | COMPANY | EXCHANGE | SECTOR | MKT CAP | PRICE | DAILY % | P/E | 52WK
      HeatCell on DAILY % column
      "Open All in Workspace" button (top right)
    Pagination (← Prev · 1 · 2 · 3 · Next →) + "12 results" total
```

Data sources: /api/v1/instruments (with filter params)

**Design decision (2026-04-13)**: Screener uses CompactTable (h-8) for results to maximize information density. Filter builder uses a row-based UI (not a sidebar) to keep filters and results visible simultaneously. Metric dropdown has search input.

---

### Page 6 — Portfolio (`/app/portfolio`)

Node: `3MDeP` | x: 7600

Component tree:
```
PortfolioLayout
  AppSidebar (220px, Portfolio active)
  PortfolioMain
    TopBar ("My Strategies" + "+ Create Strategy" button)
    StrategyCards (3-col grid)
      StrategyCard: name + Total Value (mono) + Daily P&L (colored) + sparkline
      Active card: border-primary bg-primary/5
    StrategyDetail (below cards, visible when card selected)
      PerformanceHeader: Total Value (large mono) · Daily P&L · Total Return % · Unrealized/Realized P&L
      RiskMetricsStrip: Beta · Concentration · Sectors · Top Position %
      Tabs: Holdings | Transactions | Analytics | Watchlists | Settings
      [Holdings tab]
        HoldingsTable (CompactTable): ★ · TICKER · COMPANY · SECTOR · QTY · AVG COST · CURRENT · UNREAL $ · UNREAL % · DAILY % · WEIGHT % · Actions
        HeatCell on UNREAL % and DAILY % columns
      [Analytics tab]
        SectorAllocationChart (donut) + TopHoldingsChart (horizontal bar) + ConcentrationScore
```

Data sources: /api/v1/portfolios · /api/v1/holdings · /api/v1/transactions

**Design decision (2026-04-13)**: Portfolio redesigned as "My Strategies" to reflect the strategy-based model (PRD-0022). Each strategy card shows both P&L and a 5-day sparkline for trend context. StrategyCard with `border-primary` = active/selected state.

---

### Page 7 — News (`/app/news`)

Node: `EgNBX` | x: 9120

Component tree:
```
NewsLayout
  AppSidebar (220px, News active)
  NewsMain
    TopBar ("News Intelligence" + MarketStatusBadge + "Powered by NLP" badge)
    TabBar: "Top Today" (active) | "Feed"
    [Top Today tab]
      ArticleCards (ranked by display_relevance_score)
        ArticleCard:
          source logo (16px) + source name + timestamp relative
          Headline (bold, 2 lines max)
          Excerpt (3 lines, text-muted-foreground)
          RelevanceBadge: ≥0.7=green · ≥0.4=amber · <0.4=slate
          NLPTierBadge: DEEP (green) | MEDIUM (amber) | LIGHT (muted)
          ImpactSparkline (20px inline SVG, day_t0/t1/t2/t5 windows)
          LIGHT tier: opacity-60 italic source label
```

Data sources: /api/v1/news/top · /api/v1/articles (feed)

**Components introduced (2026-04-13)**:
- `NLPTierBadge`: text-xs badge, DEEP=green-800 bg / MEDIUM=amber-700 bg / LIGHT=slate (dimmed)
- `RelevanceBadge`: numeric score (e.g. "0.91"), colored by threshold
- `ImpactSparkline`: inline 20×16px SVG showing multi-window price impact. Only show when data exists — never as decoration.

---

### Page 8 — Chat (`/app/chat`)

Node: `KZ6kq` | x: 10640

Component tree:
```
ChatLayout
  AppSidebar (220px, Chat active)
  ChatMain (horizontal: thread sidebar + message area)
    ThreadSidebar (260px, fill #0c1628)
      ThreadsTop:
        "New Chat" primary button (blue, full width)
        ThreadSearch input (placeholder "Search conversations...")
      ThreadList:
        ThreadItem: badge (ACTIVE/date) + title (2-line truncated) + "Xh ago · N messages"
        Active thread: fill #0d1f3c (tinted highlight)
    MessageArea (fill_container)
      Messages (scrollable):
        UserMsg: right-aligned, bg-primary/20, rounded-2xl rounded-tr-sm, px-4 py-3
        AIMsg: left-aligned, bg-card border border-border, rounded-2xl rounded-tl-sm, px-4 py-3
          Body text (streaming cursor █ when live)
          AIBadgeRow: intent badge chip + provider badge + latency ("DeepSeek R1 · 1.4s")
          CitationInline: [1] [2] markers inline
          CitationCards (expandable): title + source + date + excerpt
          ContradictionAlert: amber border card "⚠ Conflicting sources detected"
      InputArea (sticky bottom, fill #0c1628):
        ContextPills: "Context:" label + entity pills (e.g. "AAPL")
        InputRow: Textarea (auto-grow, h-52) + SendBtn (blue, 40×40) + AbortBtn
```

Data sources: /v1/threads · /v1/chat/stream (SSE) · /v1/chat (buffered)

**Components introduced (2026-04-13)**:
- `ThreadSidebar`: 260px fixed left panel (separate from AppSidebar). Dark tinted bg.
- `ThreadItem`: vertical layout — badge row + title + metadata line
- `CitationCard`: expandable card below AI message (not a nested card — it's inline content within the message bubble)
- `ContradictionAlert`: amber-bordered frame with ⚠ icon (background tint, NOT border-left stripe)

---

### Page 9 — Companies (`/app/companies`)

Node: `9jXmA` | x: 12160

Component tree:
```
CompaniesLayout
  AppSidebar (220px, Companies active)
  CompaniesMain
    TopBar ("Companies" + "8,421 instruments" count)
    CoContent (px-20 py-20)
      SearchRow:
        SearchBox (full-width debounced input, magnifier icon)
        FilterChips: All (active=blue) | Stocks | ETFs | Has Fundamentals
      CoTable (CompactTable h-10, slightly less dense than h-8)
        Header: ★ · TICKER · COMPANY · EXCHANGE · SECTOR · MKT CAP · PRICE · DAILY %
        Rows: watchlist toggle · ticker (blue mono) · company · exchange · sector · metrics
        DAILY % column: HeatCell colored
        Watchlist ★ toggle: optimistic update
        Row click → Company Detail
      Pagination (50/page)
```

Data sources: /api/v1/instruments · /api/v1/securities

**Design decision (2026-04-13)**: Companies uses h-10 rows (not CompactTable h-8) — this is a navigation page, not an analysis page. Users need comfortable row height to scan and click. Screener uses h-8 because it's analytical/data-dense.

---

### Implementation priority order (updated 2026-04-13)

1. `AppSidebar` + `TopBar` + shared layout shell (all 9 app pages share this)
2. Dashboard page (validates gateway client patterns + MorningBriefCard pattern)
3. Company Detail page (TradingView chart + tab pattern + 52WeekRangeBar)
4. Workspace page (react-grid-layout + icon-only sidebar + SSE chat)
5. Companies page (navigation table, simplest data model)
6. Screener page (filter builder + CompactTable results)
7. News page (ArticleCard + NLPTierBadge + RelevanceBadge)
8. Chat page (ThreadSidebar + SSE streaming + CitationCard)
9. Portfolio page (StrategyCard + HoldingsTable + Analytics tab)
10. Landing page (static-heavy, conversion-focused, implement last)

### New components introduced (2026-04-13 session)

| Component | Page(s) | Key pattern |
|-----------|---------|-------------|
| `CompetitionTable` | Landing | 7-col table, Worldview row highlighted with `bg-primary/10 border-primary` |
| `52WeekRangeBar` | Company Detail | 6px track + 12px dot at proportional position; labels Low/Current/High in JetBrains Mono |
| `MorningBriefCard` | Dashboard | Full-width, `height: 240px`, `fill: #0c1628`, BrainCircuit icon, no border-left |
| `MarketHeatmapCard` | Dashboard | 11 sector tiles, 4-col grid, HeatCell 7-step by % change |
| `NLPTierBadge` | News, Company Detail | DEEP/MEDIUM/LIGHT routing tier (green/amber/slate) |
| `RelevanceBadge` | News, Company Detail | Numeric score colored by threshold (≥0.7 green, ≥0.4 amber, <0.4 slate) |
| `ThreadSidebar` | Chat | 260px panel left of MessageArea; separate from AppSidebar |
| `CitationCard` | Chat, Company Detail Chat | Expandable inline card below AI message; NOT nested card |
| `ContradictionAlert` | Chat | Amber-tinted frame with ⚠ icon; background tint, not border-left stripe |
| `StrategyCard` | Portfolio | Value + P&L + sparkline; active state: `border-primary bg-primary/5` |
| `PanelWrapper` | Workspace | DragHandle (8px, cursor-grab) + label + ticker chip + [Link⊙][−][×] icons |

### Top deferred patterns (highest credibility-to-effort)

1. `font-variant-numeric: tabular-nums` on all numeric cells — CSS only, 1 line per component
2. P&L as `$173.42 · +$2.34 · +1.37%` — both absolute + percentage in every P&L display
3. `LivePriceBadge` freshness dots per data block — green pulse / amber / red retry
4. ⌘K command palette — global navigation shortcut (shows all routes + search)
5. Data freshness dots on each panel header — shows when data was last updated
