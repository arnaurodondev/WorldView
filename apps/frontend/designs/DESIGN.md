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

## 10. Designed Pages (Critique Cycle 2, 2026-04-13)

Canvas: `apps/frontend/designs/worldview-mvp.pen`
Exported PNGs: `apps/frontend/designs/images/`

### Page 1 — Landing Page (`/`)

Node: `QTjSz` | Export: `images/QTjSz.png`

Sections (top→bottom):
1. **Navbar** — logo + nav links + "Sign In" ghost + "Start Free" primary CTA
2. **Market Ticker Strip** — `MARKET OPEN` badge + 6 live indices (SPY · QQQ · DIA · VIX · BTCUSD · EURUSD)
3. **Hero** — eyebrow + H1 "The Research Platform That Thinks With You" + subtitle + CTAs + AI dashboard mockup (TSLA chart + news + market tables)
4. **Stats Bar** — 10M+ data points · 500K+ articles · 18 intelligence models · <5s latency
5. **Features Grid** — 6 feature cards: Real-Time Intelligence, AI-Powered Research, Prediction Markets, Advanced Screener, Flash Alerts, Portfolio Analytics
6. **Comparison** — Traditional Tools (✗ list) vs Worldview ✦ (✓ list) — two-card layout
7. **How It Works** — 3 numbered steps: Connect → Research → Act
8. **Pricing** — $0 · $49 · $99 tiers with feature lists
9. **CTA** — "Bloomberg-Grade Research. Without the Bloomberg Bill." + dual CTA buttons
10. **Footer** — links + legal

Key route: public (no auth). Zitadel login initiated from "Sign In" / "Start Free" buttons.

---

### Page 2 — Dashboard (`/app/dashboard`)

Node: `ujopW` | Export: `images/ujopW.png`

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
    HeatMap (sector/market-cap grid, 7-step HeatCell)
    WatchlistTable (CompactTable: ticker · last · chg% · vol · signal)
    NewsPane (ranked articles, relevance badges, source + time)
    AlertsPane (CRITICAL/HIGH/MEDIUM severity badges)
```

Data sources: portfolio/summary · market/screener · watchlist (WS) · news/top · alerts (WS)
Real-time: watchlist prices via WebSocket; alert stream via WebSocket

---

### Page 3 — Company Detail (`/app/company/[entityId]`)

Node: `xB3MZ` | Export: `images/xB3MZ.png`

Component tree:
```
CompanyDetailLayout
  AppSidebar (reuse)
  MainArea
    CompanyHeader
      Ticker (AAPL) · CompanyName (Apple Inc.) · ExchangeBadge · SectorTag
      PriceDisplay ($173.42 · +$2.34 · +1.37%) ← ADR-F-12: entityId ≠ ticker
      ActionButtons: "+ Add Alert" · "Open in Workspace"
    TabBar: Overview · Fundamentals · Intelligence · Prediction Markets · AI Chat
    [Overview Tab]
      OHLCVChart (TradingView Lightweight, full-width, h-72)
      TechnicalSnapshot (Beta · MA50 · MA200 · RSI · Short%)
      FundamentalsGrid (2-col CompactTable: P/E · EPS · Rev · EBITDA · Mkt Cap · D/E · FCF · Div Yield)
      AIBrief (Card: analyst summary, key risks, model attribution "DeepSeek R1 · 1.4s")
    [Intelligence Tab]
      NewsPane (entity-specific articles, impact window badges, relevance scores)
    [Prediction Markets Tab]
      PredictionList (Polymarket probabilities as Progress bars with yes/no %)
    [AI Chat Tab]
      ChatInterface (SSE stream, source attribution, suggested query chips)
```

Data sources: entities/{id} · market/ohlcv/{ticker} · entities/{id}/fundamentals · entities/{id}/articles · entities/{id}/predictions · entities/{id}/ai-brief · chat (SSE)

---

### Page 4 — Workspace (`/app/workspace`)

Node: `OOfmd` | Export: `images/OOfmd.png`

Component tree:
```
WorkspaceLayout (full-viewport, no max-width, CSS grid named areas)
  AppSidebar (icon-only collapsed, 48px)
  TopBar
    TickerSearch (typeahead) · TimeframeSelector · DrawingTools
    SaveLayout · ExportChart · ThemeToggle (dark-only)
  ResizablePanelGroup
    PrimaryPanel (chart, ~60% width)
      OHLCVChart (TradingView, full height, no border-radius)
      VolumeHistogram (bottom strip)
    SecondaryColumn (right, ~40%)
      NewsPane (entity news + global, scrollable)
      AlertsPane (live WebSocket alerts, CRITICAL dismissable)
    BottomRow (optional, collapsed by default)
      AIChat (SSE stream, full-width, h-200px)
```

Layout: CSS grid named areas; panel sizes persisted to user preferences via S9.
Real-time: OHLCV updates via WebSocket; alerts via WebSocket; AI chat via SSE.

---

### Implementation priority order

1. `AppSidebar` + `TopBar` + `DashboardLayout` shell (shared across all app pages)
2. Dashboard page (validates all gateway client patterns)
3. Company Detail page (TradingView chart + tab pattern)
4. Workspace page (ResizablePanel + AI chat SSE)
5. Landing page (static-heavy, implement last)

### Top 3 deferred patterns (highest credibility-to-effort)

1. `font-variant-numeric: tabular-nums` on all numeric cells — CSS only, 1 line per component
2. P&L as `$173.42 · +$2.34 · +1.37%` — both absolute + percentage in every P&L display
3. `LivePriceBadge` freshness dots per data block — green pulse / amber / red retry
