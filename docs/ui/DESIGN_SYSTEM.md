# Worldview Design System

> **Single source of truth** for all frontend design decisions: tokens, components, patterns, and UX conventions.
> **Last updated**: 2026-04-23 (v2.3 — Terminal Dark palette overhaul: #09090B bg + Bloomberg yellow (#FFD60A) + zinc text)
>
> Referenced by: `/design-ui` skill, `/scaffold-frontend` skill, `ux-ui-designer` agent, `frontend-engineer` agent.
>
> **CONFIRMED**: "Terminal Dark" direction — `#09090B` neutral near-black bg + IBM Plex + Bloomberg trading yellow (#FFD60A) + teal-green positive.
> Prior "Bloomberg Dark" palette (#0A0E14 bg + #E8A317 amber) retired 2026-04-23: blue-tinted bg read as "fintech app"; warm amber read as "notification". See `docs/ui/competitive-design-research.md` for full competitor analysis.

---

## 1. Stack

| Layer | Choice | Notes |
|-------|--------|-------|
| Framework | Next.js 15 (App Router) | Node SSR; no `output: 'export'` (ADR-F-01) |
| UI library | shadcn/ui **only** | Radix UI primitives + Tailwind CSS; no other component library |
| Data grid | AG Grid (Community) | Whitelisted institutional data-grid primitive — used for screener and portfolio tables where shadcn/ui's `data-table` is insufficient (virtualization, column groups, server-side sort/filter). No other table library is allowed. |
| Styling | Tailwind CSS v3 + CSS variables | Dark theme enforced; no hardcoded hex colors |
| Theme | **Dark only** | `class="dark"` set permanently on `<html>` (ADR-F-04) |
| **Font (UI)** | **IBM Plex Sans** | Loaded via `next/font/google`. Weights: 300/400/500/600/700. Variable: `--font-sans` |
| **Font (Data/Mono)** | **IBM Plex Mono** | Loaded via `next/font/google`. Weights: 400/500/600. Variable: `--font-mono`. Used for ALL numbers, prices, tickers, percentages |
| Icons | lucide-react | Consistent icon set used everywhere |
| Charts | lightweight-charts 4 | TradingView Lightweight Charts for OHLCV |
| Portfolio charts | recharts | Donut/bar charts for portfolio analytics (code-split, `/portfolio` only) |
| Keyboard shortcuts | react-hotkeys-hook | Global navigation shortcuts (g+d, g+w, etc.) |
| Package manager | pnpm (exact versions, no `^`) | `pnpm audit` must show 0 CVEs before commit |

**Font Rule (ADR-F-15)**: ALL numeric values (prices, percentages, quantities, dates in tables)
MUST use `font-mono` (IBM Plex Mono). This is the single highest-impact change for professional appearance.
Never mix number display between font-sans and font-mono — tabular-nums requires consistent monospace.

**Rule**: The frontend talks **only** to S9 API Gateway at `/api/*`. Never construct direct backend service URLs.

---

## 2. Color Palette (Dark Theme — "Terminal Dark")

> **Terminal Dark confirmed. Do NOT revert to Bloomberg Dark (#0A0E14 + #E8A317) or slate-950/blue-500 defaults.**
> See `app/globals.css` for authoritative token definitions. This section mirrors those values.
> Reference: `docs/ui/competitive-design-research.md`

All colors are expressed as CSS custom properties. **Never use hardcoded hex values in components.**
**Never reference the old Bloomberg Dark palette (#0A0E14, #E8A317, #E0DDD4, #6B7585, #111820, #1A2030, #243040).**

### 2.1 CSS Variables (`app/globals.css`) — Terminal Dark

```css
:root {
  /* ── Backgrounds — elevation hierarchy, neutral (zero hue) ───────── */
  --background:        240 10% 4%;       /* #09090B — neutral near-black, no blue tint */
  --card:              270 2% 7%;        /* #111113 — panel/card backgrounds, neutral */
  --muted:             240 4% 11%;       /* #18181B — elevated surfaces, hover states */
  --popover:           240 10% 4%;       /* #09090B — same as --background */
  --surface-2:         240 4% 11%;       /* #18181B — alias for muted */
  --surface-3:         240 4% 16%;       /* #27272A — third elevation level, borders */

  /* ── Text ──────────────────────────────────────────────────────────── */
  --foreground:        240 5% 90%;       /* #E4E4E7 — zinc-200 off-white */
  --card-foreground:   240 5% 90%;       /* #E4E4E7 */
  --muted-foreground:  240 4% 46%;       /* #71717A — zinc-500 neutral grey */

  /* ── Interactive ───────────────────────────────────────────────────── */
  --primary:           48 100% 52%;      /* #FFD60A — Bloomberg-signature trading yellow */
  --primary-foreground: 0 0% 0%;         /* #000000 — pure black text on yellow CTA */

  /* ── Structural ────────────────────────────────────────────────────── */
  --border:            240 4% 16%;       /* #27272A — visible panel edges */
  --input:             240 4% 16%;       /* #27272A */
  --ring:              48 100% 52%;      /* #FFD60A — focus rings match primary */
  --accent:            240 4% 11%;       /* #18181B */
  --destructive:       0 63% 62%;        /* #EF5350 — destructive actions */
  --destructive-foreground: 240 5% 90%;  /* #E4E4E7 */

  /* ── Financial domain ──────────────────────────────────────────────── */
  --positive:          174 42% 40%;      /* #26A69A — teal-green (price up) */
  --negative:          0 63% 62%;        /* #EF5350 — muted red (price down) */
  --warning:           38 92% 50%;       /* #F59E0B — amber-500 alerts/warnings */

  /* ── Structural density ────────────────────────────────────────────── */
  --radius: 0.125rem;                    /* 2px — near-zero, terminal-sharp corners */
  --panel-header-height: 24px;           /* PRD-0031: 24px (was 32px) — compact panel chrome */
  --topbar-height: 36px;                 /* PRD-0031: 36px (was 44px) — dense top chrome */
  --data-row-height: 22px;              /* PRD-0031: 22px data rows (was 32px/h-8) */
  --sidebar-collapsed-width: 48px;      /* PRD-0031: icon-only collapsed sidebar */
  --sidebar-expanded-width: 220px;      /* PRD-0031: expanded sidebar with watchlist */
}
```

### 2.1a Hex Quick-Reference (for pencil.dev canvas and design tools)

| Token | Hex | Description |
|-------|-----|-------------|
| Page background | `#09090B` | Terminal neutral near-black (zero hue) |
| Card/panel | `#111113` | Panel/card backgrounds |
| Elevated/hover (surface-2) | `#18181B` | Elevated surfaces, hover states |
| Surface-3 / border | `#27272A` | Third elevation level, dividers |
| Primary text | `#E4E4E7` | zinc-200 off-white |
| Secondary text | `#71717A` | zinc-500 neutral grey (labels, axis) |
| Accent (yellow) | `#FFD60A` | Bloomberg-signature trading yellow |
| Accent on yellow (fg) | `#000000` | Pure black text on yellow buttons |
| Positive (teal) | `#26A69A` | Price up, portfolio gain |
| Negative (red) | `#EF5350` | Price down, loss |
| Warning (amber) | `#F59E0B` | Medium severity alerts |

### 2.2 Semantic Usage

| Context | Variable | Example | Hex (Terminal Dark) |
|---------|----------|---------|---------------------|
| Page background | `bg-background` | `<body>`, `<main>` | `#09090B` |
| Card / panel | `bg-card` | shadcn `<Card>`, sidebar panels | `#111113` |
| Elevated panel | `bg-muted` | nested cards, hover states | `#18181B` |
| Primary headings | `text-foreground` | page titles, values | `#E4E4E7` |
| Labels, captions | `text-muted-foreground` | "P/E Ratio", timestamps | `#71717A` |
| Price up | `text-positive` | `+2.34%` | `#26A69A` (teal) |
| Price down | `text-negative` | `-1.12%` | `#EF5350` |
| CTA buttons | `bg-primary text-primary-foreground` | "Buy", "Confirm" | `#FFD60A` bg + `#000` text |
| Borders | `border-border` | `<Separator>`, table borders | `#27272A` |
| Active nav item | `bg-primary/10 text-primary` | sidebar active link | yellow tint |
| Ticker badge | `bg-primary/20 text-primary font-mono` | "AAPL" badge | yellow tint |

### 2.3 Background Elevation Hierarchy

```
Page (--background / #09090B)
  └── Sidebar, panels (--card / #111113)
        └── Nested cards, hover rows (--muted, --surface-2 / #18181B)
              └── Input fields, tooltips, borders (--surface-3 / #27272A)
```

### 2.4 Core Token Contrast Ratios (Round-4 hardening audit, 2026-06-10)

WCAG 2.1 contrast ratios computed from the **live HSL tokens** in
`app/globals.css` (not the approximate hex comments next to them). The
platform's text-size floor is **10px** (§3.2 lists the narrow 9px exceptions);
WCAG's relaxed "large text" threshold (3:1) only applies at ≥24px / ≥18.66px
bold — nothing at our densities qualifies, so **4.5:1 (AA normal text) is the
bar for every text size we ship**.

| Foreground token | On `--background` #09090B | On `--card` #111113 | AA (4.5:1) | Approved down to |
|---|---|---|---|---|
| `--foreground` (240 5% 90%, ≈#E4E4E7) | **15.7 : 1** | **14.9 : 1** | PASS | 9px (the §3.2 exception floor) |
| `--primary` (48 100% 52%, ≈#FFD60A) | **13.3 : 1** | **12.6 : 1** | PASS | 9px |
| `--muted-foreground` (240 4% 55%, ≈#888891) | **5.7 : 1** | **5.4 : 1** | PASS | 10px floor (and the 9px §3.2 label exceptions) |

Notes:

- **`--muted-foreground` passes AA only because of the F-VISUAL-NEW-M sync**
  that lifted `.dark --muted-foreground` from 46% → 55% lightness. The old
  46% value (zinc-500 #71717A) measures **4.1:1 on background / 3.9:1 on
  card — an AA FAILURE for normal text**. Do not "restore" 46% for aesthetic
  dimming: if a surface needs dimmer-than-muted text, it must be
  non-essential/decorative content (e.g. `text-muted-foreground/50` digest
  lines, watermarks) that carries no information a user must read.
- Opacity modifiers (`text-muted-foreground/60` etc.) drop below AA by
  construction — reserve them for decorative/redundant text only.
- Methodology: WCAG 2.1 relative-luminance formula over the HSL→sRGB
  conversion of each token; ratios rounded to one decimal.

---

## 3. Typography — IBM Plex Sans + IBM Plex Mono (ADR-F-15)

> **CHANGED from v2.0**: No longer "system font stack." IBM Plex fonts are mandatory.
> See PRD-0027 §1.4.4 and ADR-F-15 for rationale.

**Font loading** (root `layout.tsx`):
```tsx
import { IBM_Plex_Sans, IBM_Plex_Mono } from 'next/font/google'

const ibmPlexSans = IBM_Plex_Sans({
  subsets: ['latin'],
  weight: ['300', '400', '500', '600', '700'],
  variable: '--font-sans',
  display: 'swap',
})
const ibmPlexMono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-mono',
  display: 'swap',
})

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`dark ${ibmPlexSans.variable} ${ibmPlexMono.variable}`}>
      <body className="font-sans antialiased">{children}</body>
    </html>
  )
}
```

### 3.1 Type Scale

| Use case | Font | Tailwind class | Size/weight |
|----------|------|---------------|-------------|
| Page title | IBM Plex Sans | `text-2xl font-semibold tracking-tight text-foreground` | 24px/600 |
| Section heading | IBM Plex Sans | `text-base font-semibold tracking-tight text-foreground` | 16px/600 |
| Card title | IBM Plex Sans | `text-sm font-medium text-foreground` | 14px/500 |
| Body text | IBM Plex Sans | `text-sm text-foreground` | 14px/400 |
| Label / caption | IBM Plex Sans | `text-xs text-muted-foreground` | 12px/400 |
| **Ticker symbol** | **IBM Plex Mono** | `font-mono text-sm font-semibold uppercase tracking-widest` | 14px/600 |
| **Price (header)** | **IBM Plex Mono** | `font-mono text-4xl font-semibold tabular-nums` | 36px/600 |
| **Numeric value (large)** | **IBM Plex Mono** | `font-mono text-xl font-semibold tabular-nums` | 20px/600 |
| **Numeric value (table)** | **IBM Plex Mono** | `font-mono text-[11px] tabular-nums text-right` | **11px/400** (PRD-0031: was 12px) |
| **Percentage change** | **IBM Plex Mono** | `font-mono text-sm tabular-nums` | 14px/400 |
| **Terminal/chat text** | **IBM Plex Mono** | `font-mono text-xs leading-relaxed` | 12px/400 |

**Critical rule (ADR-F-15)**: Every number displayed to the user — prices, percentages, quantities,
EPS values, volumes, dates in data tables — MUST use `font-mono tabular-nums`. This is non-negotiable.
Mixing sans and mono within a number column is a typography error.

**tracking-tight** on headings: IBM Plex Sans is slightly wider than Inter. The `-tight` tracking
compensates and prevents headings from appearing loose at small sizes.

### 3.2 Font Size Exception: `text-[9px]` for Chart Axis and Ultra-Dense Labels

The design minimum is `text-[10px]`. However, `text-[9px]` is permitted in the following specific
contexts where information density requires it:

| Context | Example components |
|---------|-------------------|
| Chart axis tick labels (x/y) | `OHLCVChart`, `RevenueTrendSparklines`, `EarningsHistoryChart` |
| Ultra-dense table column headers (all-caps) | `InsiderTransactionsTable`, `PeerComparisonPanel` |
| Chart legend labels | `RevenueTrendSparklines`, `EarningsHistoryChart` |
| Secondary badges and timestamps in compact list items | `InstrumentTopNews`, `FundamentalsTopNews` |
| Graph legend and control hints | `EntityGraph`, `EntityGraphPanel` |

**Never** use `text-[9px]` for body text, primary data values, section headings, or anywhere text
needs to be readable in isolation. Chart axis labels are scanned, not read — their 9px size is
acceptable in that context.

---

## 4. Spacing & Layout

| Pattern | Tailwind class | Usage |
|---------|---------------|-------|
| Page padding | `px-4 sm:px-6 lg:px-8` | Main content area |
| Card padding | `p-4` (compact) / `p-6` (standard) | shadcn `<Card>` |
| Section gap | `space-y-4` or `space-y-6` | Between panels |
| Grid columns | `grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3` | Metric grids |
| Max content width | `max-w-7xl mx-auto` | Constrained page layouts |
| Sidebar width | `w-[220px]` | Fixed, not resizable |

---

## 5. Component Catalogue

### 5.1 shadcn/ui Components (approved for use)

These are the **only** pre-built components allowed. Install via `pnpm dlx shadcn@latest add <name>`.

| Component | Use case |
|-----------|----------|
| `Button` | All clickable actions |
| `Card`, `CardHeader`, `CardContent` | Data panels, metric cards |
| `Table`, `TableHeader`, `TableRow`, `TableCell` | All tabular data |
| `Badge` | Status labels, severity indicators, tickers |
| `Select`, `SelectTrigger`, `SelectContent` | Single-option dropdowns |
| `Tabs`, `TabsList`, `TabsTrigger`, `TabsContent` | Section switching |
| `Sheet` | Side panels, mobile nav |
| `Dialog` | Confirmation modals, detail views |
| `Skeleton` | Loading states for all data panels |
| `Separator` | Visual dividers |
| `Input` | Search, form fields |
| `Tooltip` | Value explanations, truncated text |
| `ScrollArea` | Bounded-height scrollable regions |
| `Alert` | Non-critical notifications, warnings |
| `Avatar` | User avatar in TopBar |
| `Command`, `CommandDialog`, `CommandInput`, `CommandList`, `CommandGroup`, `CommandItem` | cmdk keyboard-navigable search/palette surfaces (GlobalSearch inline, CommandPalette dialog — see §6.15) |

### 5.2 Custom Domain Components

Purpose-built components for financial data. Implement these consistently:

| Component | File path | Description |
|-----------|-----------|-------------|
| `OHLCVChart` | `components/instrument/OHLCVChart.tsx` | lightweight-charts candlestick chart; theme synced to Terminal Dark palette |
| `ImpactSparkline` | `components/news/ImpactSparkline.tsx` | Multi-window price impact mini chart |
| `RelevanceBadge` | `components/news/RelevanceBadge.tsx` | 0–100 score badge with color gradient |
| `SeverityBadge` | `components/alerts/SeverityBadge.tsx` | LOW/MEDIUM/HIGH/CRITICAL colored badge |
| `FlashOverlay` | `components/alerts/FlashOverlay.tsx` | Full-screen critical alert, 12s auto-dismiss |
| `FundamentalsBar` | `components/instrument/FundamentalsBar.tsx` | 6-metric fundamentals strip (localStorage) |
| `PriceChange` | `components/instrument/PriceChange.tsx` | `+2.3% ▲` / `-1.1% ▼` with semantic color |
| `EntityNewsPanel` | `components/instrument/EntityNewsPanel.tsx` | Chart-range-linked news articles |
| `HeatCell` | `components/data/HeatCell.tsx` | Table cell with 7-step heat background (PRD-0027 ADR-F-14) |
| `Sparkline` | `components/data/Sparkline.tsx` | 20px inline SVG mini-chart for trend lines |
| `LivePriceBadge` | `components/data/LivePriceBadge.tsx` | Price with freshness dot (green/yellow/red) |
| `CompactTable` | `components/data/CompactTable.tsx` | Dense financial table (text-xs, h-8 rows, mono numbers) |
| `HeatmapGrid` | `components/market/HeatmapGrid.tsx` | Sector heat map tile grid (Finviz-style) |
| `MarketComparisonTable` | `components/landing/ComparisonTable.tsx` | Landing page platform comparison matrix |
| `FeedbackWidget` | `components/feedback/FeedbackWidget.tsx` | Fixed bottom-right feedback button + dialog |
| `FeedbackDialog` | `components/feedback/FeedbackDialog.tsx` | Category + description form, POST /v1/feedback |
| `52WeekRangeBar` | `components/instrument/52WeekRangeBar.tsx` | Visual slider showing current price vs 52w range; exported as `WeekRangeBar`; `showLabels` prop hides low/high labels for compact header use |
| `FundamentalSparkline` | `components/instrument/FundamentalSparkline.tsx` | SVG mini trend-line for any fundamentals metric; fetches timeseries data via S9 public endpoint; trend-colors positive/negative/flat |
| `ChartToolbar` | `components/instrument/ChartToolbar.tsx` | h-7 strip with MA50/MA200 toggles + VOL submenu (Base/MA20/Profile/VWAP Line) + IND dropdown (RSI/MACD/BB/ATR/STOCH/OBV/VWAP) + Fullscreen; parent-controlled state via `indicators: Record<IndicatorId, IndicatorConfig>` (PLAN-0050 Wave C) |
| `DrawingPalette` | `components/instrument/DrawingPalette.tsx` | Left-side 28px vertical palette with 7 drawing tools (Trend Line, Horizontal Level, Rectangle, Arrow, Fib Retracement, Parallel Channel, Text) + CURSOR (exit mode); click-to-arm model; `aria-pressed` state; renders absolutely inside OHLCVChart chart wrapper |
| `DrawingCanvas` | `components/instrument/DrawingCanvas.tsx` | Absolutely-positioned SVG overlay covering the chart canvas (right of palette); renders persisted `Annotation[]` as SVG shapes; handles multi-click tool-arm → point-capture → commit workflow; right-click to delete; `pointer-events:none` when no tool armed |
| `VolumeProfileOverlay` | `components/instrument/VolumeProfileOverlay.tsx` | Right-side 60px SVG histogram overlay showing volume-per-price-level; Point of Control (highest volume bucket) highlighted in brand yellow; only renders when `showVolProfile=true` |
| `OverviewSidebarMetrics` | `components/instrument/InstrumentKeyMetrics.tsx` | 12-row sidebar metrics panel (Wave C-1); exported as `OverviewSidebarMetrics`; WeekRangeBar row for 52W range; placeholder rows for EPS/BETA/AVG-VOL (Wave D-3) |
| `TechnicalSnapshot` | `components/instrument/TechnicalSnapshot.tsx` | Strip: Beta, MA50↑↓, MA200↑↓, RSI, Short Interest |

### 5.3 Layout Components

| Component | File path | Notes |
|-----------|-----------|-------|
| `Sidebar` | `components/shell/Sidebar.tsx` | 56px icon-only nav rail, watchlist prices, keyboard hint strip |
| `TopBar` | `components/shell/TopBar.tsx` | Logo + GlobalSearch + ⌘K hint chip + IndexTicker + alerts badge + avatar |
| `GlobalSearch` | `components/shell/GlobalSearch.tsx` | Inline instrument search dropdown (cmdk); click/focus-driven — ⌘K now opens CommandPalette |
| `CommandPalette` | `components/shell/CommandPalette.tsx` | Global ⌘K dialog: Navigate / Instruments / Recent Conversations (§6.15) |
| `UtcClock` | `components/shell/UtcClock.tsx` | Live UTC clock display |
| `IndexTicker` | `components/shell/IndexTicker.tsx` | Center-bar market index prices |
| `MarketStatusPill` | `components/shell/MarketStatusPill.tsx` | OPEN/CLOSED/PRE status badge |

---

## 6. UX Patterns

### 6.1 Data Loading Pattern (Required)

Every component that fetches data MUST implement all three states:

```tsx
function DataPanel({ id }: { id: string }) {
  const { data, isLoading, error, refetch } = useMyData(id)

  if (isLoading) return <DataPanelSkeleton />           // static skeleton (see §6.2)
  if (error)    return <ErrorCard message="..." onRetry={refetch} /> // error + retry
  if (!data)    return <EmptyState message="..." />     // empty with guidance

  return <DataPanelContent data={data} />
}
```

**Never render a blank panel.** Every state must communicate something to the user.

### 6.2 Skeleton Pattern

> **Updated 2026-06-10 (Round-3 polish)** — codified the no-animation rule and the
> shape-matching convention.

**Animation rule — skeletons are STATIC by default.** `components/ui/skeleton.tsx`
renders a static `bg-muted` block with NO `animate-pulse` — Bloomberg-style terminals
use static loading bars; finance users read animation as "something is happening"
(streaming, thinking), so an animated skeleton reads as broken streaming. Two tiers:

| Tier | Class | When |
|------|-------|------|
| Default | `<Skeleton />` (static `bg-muted`, no animation) | All loading states |
| Opt-in | `animate-skeleton-pulse` (slow 2s opacity 1→0.4 fade, `tailwind.config.ts`) | Long loads (>2s expected, e.g. AI generation) where "still working" feedback matters |
| **Banned** | Tailwind's raw `animate-pulse` | Never for skeletons — fast consumer-app pulse, and it bypasses the reduced-motion override in `globals.css` semantics we maintain |

**Shape-matching convention.** A skeleton must pre-allocate the same geometry the
loaded content will occupy — same heights, widths, column structure, and count —
so hydration causes zero layout shift and the user's eye already knows where the
data will land.

```tsx
// DO — mirror the loaded layout: 5 rows × row height, table rhythm preserved
function DataTableSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 5 }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full rounded-[2px]" />
      ))}
    </div>
  )
}

// DO — match exact cell dimensions when the real content has fixed geometry
// (e.g. IndexStrip pre-allocates ten 22×60px cells so the TopBar never shifts)
<div className="h-[22px] w-[60px] shrink-0 rounded-[2px] bg-muted/30" aria-hidden />

// DON'T — one amorphous blob where a table will appear (layout shifts on load,
// user can't anticipate the structure)
<Skeleton className="h-64 w-full" />

// DON'T — animate-pulse (banned), rounded/rounded-md (violates 2px-radius rule)
<Skeleton className="h-10 w-full rounded-md animate-pulse" />
```

Rules of thumb:
- **Count matches reality**: if the panel shows ~10 rows, render ~10 skeleton rows (cap at one viewport's worth — never render 200 skeleton rows).
- **Text skeletons are shorter than their container**: `w-3/4` / `w-1/2` varied widths read as "text loading"; full-width bars read as "table loading".
- **`rounded-[2px]` always** (Terminal Sharp radius rule, §13.3).
- **`aria-hidden` on decorative cells + `aria-busy="true"` on the container** so screen readers announce one loading state, not N divs.

### 6.3 Financial Number Formatting

```tsx
// Price: always 2 decimal places, right-aligned, tabular font
<td className="text-right font-mono tabular-nums text-sm">$150.23</td>

// Percentage change: sign prefix, semantic color
function PriceChange({ value }: { value: number }) {
  const isUp = value >= 0
  return (
    <span className={isUp ? 'text-[hsl(var(--positive))]' : 'text-[hsl(var(--negative))]'}>
      {isUp ? '+' : ''}{value.toFixed(2)}%
    </span>
  )
}

// Large numbers: use Intl.NumberFormat
const fmt = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })
fmt.format(1_230_000_000) // "1.2B"
```

### 6.4 Timestamp Display

| Context | Format | Example |
|---------|--------|---------|
| Article card, event list | Relative time | "2h ago", "yesterday" |
| Table row | Short absolute | "Apr 12, 14:32" |
| Detail view header | Full absolute | "April 12, 2026, 14:32 UTC" |
| Chart axis | Compact | "Apr 12", "14:32" |

### 6.5 Table Conventions

- Column headers: `text-muted-foreground text-xs uppercase tracking-wider`
- Sortable columns: chevron icon right of label; active sort: filled icon + `text-foreground`
- Numeric columns: right-aligned, `font-mono tabular-nums`
- Text columns: left-aligned
- Row hover: `hover:bg-muted/50`
- Click-to-drill-down rows: `cursor-pointer` + navigate on row click

**Professional density mode** (use for data-heavy financial tables — Holdings, Fundamentals, Screener results):
- Row height: `h-8 min-h-[2rem]` (vs default `h-10`)
- Font size: `text-xs` for data cells (headers remain `text-[10px]`)
- Cell padding: `px-2 py-1` (vs default `px-4 py-3`)
- Use `CompactTable` wrapper component

### 6.5a Filter Bar Pattern (PLAN-0051 Wave A)

For data-heavy tables with multiple discrete filters (Transactions, Screener results, Alerts history). Pinned to a single row above the table; wraps to 2 rows on narrow panels via `flex-wrap`.

**Layout invariants**:
- Wrapper: `flex flex-wrap h-auto items-center gap-1 gap-y-1 border-b border-border px-2 py-1 shrink-0`
- All inputs share the same chrome via a single `INPUT_CLS` constant: `h-6 px-2 text-[11px] font-mono bg-card border border-border rounded-[2px] focus:border-primary focus:ring-1 focus:ring-primary/30`
- Native `<input type="date">` for date pickers (no custom Combobox), `<datalist>` for ticker autocomplete (zero JS, native a11y), `<select>` for enum filters (≤ 5 options).
- Min/Max amount: two `<input type="number" inputMode="decimal">` side by side.
- Free-text search: 200 ms debounce.
- "Clear filters" pill (10 px ALL CAPS) only visible when at least one filter is active.
- Row count `{filtered.length} / {transactions.length}` always pushed to the right with `ml-auto`.

**Reference component**: `apps/worldview-web/components/portfolio/TransactionsTable.tsx`

### 6.5b Inline Export Button

Single-format export (CSV today; XLSX/PDF dropdown is screener-only — see PLAN-0051 T-B-2-07). Same chrome as the Clear filters pill: `h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border border-border rounded-[2px] text-muted-foreground hover:text-foreground hover:border-foreground`. Implementation: `lib/csv-export.ts` (papaparse + Blob download with UTF-8 BOM for Excel compatibility).

### 6.5c Multi-Format Export Dropdown (PLAN-0051 T-B-2-07)

When a surface needs more than CSV: wrap a `Download` icon trigger with shadcn `DropdownMenu`. Items use lucide icons (`FileText` / `FileSpreadsheet` / `FileImage`) and 11px font. Filename pattern is always `<base>-YYYYMMDD-HHmm.<ext>` (sortable in any file manager, local-time stamp). Reference: `components/screener/ExportMenu.tsx`.

| Format | Library | Pinned version | CVE status |
|--------|---------|----------------|-----------|
| CSV | papaparse | 5.5.3 | clean |
| Excel (.xlsx) | write-excel-file (`/browser`) | 4.0.4 | clean — replaces SheetJS (CVEs) |
| PDF | jspdf + jspdf-autotable | 4.2.1 + 5.0.7 | clean — 2.x and 3.x had FreeText / HTML injection CVEs |

### 6.5d Column Settings Popover (PLAN-0051 T-B-2-06)

⚙ icon button (`Settings2` from lucide, h-7 w-7) anchors a 16rem popover with a checkbox-per-column list and HTML5 native drag-reorder (no extra lib). Each row uses `cursor-move` + `GripVertical` icon. Reset button restores `DEFAULT_COLUMNS` and clears localStorage. Persistence: `lib/screener-columns.ts` (key `worldview:screenerColumns:v1`, stores only `{key, visible}` so code-side label/align changes always win). Reference: `components/screener/ColumnSettingsPopover.tsx`.

### 6.5e Inline Sparkline (PLAN-0051 T-B-2-09)

Pure SVG, 18px tall, full column width via `preserveAspectRatio="none"`. No chart library — Lightweight Charts (~150KB) and Recharts (heavy React tree) are overkill for a 30-point line. Stroke colour: `var(--positive)` if last close > first close, `var(--negative)` if less, `var(--muted-foreground)` if equal. Empty state: dashed grey center line so row height stays stable. Data fetched in batch via `POST /v1/quotes/bars/batch` with 5-min `staleTime` (daily bars update at most once per trading day). Reference: `components/screener/MiniChart.tsx` + `hooks/useScreenerSparklines.ts`.

### 6.5f Saved Configurations Dialog (PLAN-0051 T-B-2-05)

shadcn `Dialog` with `Tabs` for Save/Load. Save tab: text input + Save button (disabled when empty). Load tab: scrollable list of `<DataTimestamp>`-stamped rows with Load + Trash buttons; Trash always passes through `window.confirm` because localStorage deletes are unrecoverable. Persistence: `lib/saved-screens.ts` (key `worldview:savedScreens:v1`, UUIDv4 client-side ids via `crypto.randomUUID()`). Reference: `components/screener/SavedScreensDialog.tsx`.

### 6.5c Totals Row

Render OUTSIDE the table when virtualisation may be active (FixedSizeList rejects `<tr>` children with `position: absolute`). Pattern: a 28 px tall flex row with `border-t-2 border-border bg-card`, label "Totals" in 10 px ALL CAPS muted, then per-bucket `<span>label <span className="text-foreground">value</span></span>` pairs. Each value carries a `data-testid` for unit testing.

### 6.9 Heat Map / HeatCell Pattern (NEW — ADR-F-14)

For percentage-change values in tables and sector heat tiles:

```tsx
function HeatCell({ value, children }: { value: number; children: React.ReactNode }) {
  function heatClass(v: number): string {
    if (v < -3)   return 'bg-red-900/80 text-red-100'
    if (v < -1.5) return 'bg-red-700/60 text-red-200'
    if (v < -0.5) return 'bg-red-500/40 text-red-300'
    if (v < 0.5)  return 'bg-slate-700/30 text-muted-foreground'
    if (v < 1.5)  return 'bg-green-500/40 text-green-300'
    if (v < 3)    return 'bg-green-700/60 text-green-200'
    return 'bg-green-500/80 text-green-100'
  }
  return (
    <td className={cn('text-right font-mono tabular-nums text-xs px-2 py-1', heatClass(value))}>
      {children}
    </td>
  )
}
```

**Rule**: Use HeatCell for: Holdings daily % change, Portfolio unrealized % change, Screener metric deviations, Sector heat map tiles.

### 6.10 Sparkline Pattern (NEW)

20px tall inline SVG mini-chart for trend context in compact spaces:

```tsx
function Sparkline({ data, color = 'neutral' }: { data: number[]; color?: 'positive' | 'negative' | 'neutral' }) {
  // Normalize data to [0, 20] y-range, compute SVG polyline points
  // Width: 60px, Height: 20px, no axes, no labels
  const colorClass = { positive: 'stroke-green-500', negative: 'stroke-red-500', neutral: 'stroke-slate-400' }[color]
  return <svg width={60} height={20} className="inline-block">{/* polyline */}</svg>
}
```

Use in: StrategyCards (5-day portfolio trend), Holdings rows (5-day price), Top Movers widget.

### 6.11 LivePriceBadge Pattern (NEW)

> **Sample corrected (Round-4 hardening, 2026-06-10)**: the original snippet
> used `animate-pulse` on the freshness dot and raw `bg-green-500`-style
> classes. Both are banned: status dots are STATIC (Bloomberg terminal
> convention — see `components/shell/MarketStatusPill.tsx`, the canonical
> implementation), and raw Tailwind palette colors violate the semantic-token
> rule (§15.11 + the `.eslintrc.json` lint ban). Freshness is encoded by
> COLOR alone, never by motion.

```tsx
function LivePriceBadge({ price, updatedAt }: { price: string; updatedAt: Date }) {
  const ageMs = Date.now() - updatedAt.getTime()
  // Static dot — color encodes freshness; no animation (status dots never pulse).
  const dotColor = ageMs < 30_000 ? 'bg-positive'
                 : ageMs < 300_000 ? 'bg-warning'
                 : 'bg-negative'
  return (
    <span className="flex items-center gap-1.5">
      <span className={cn('inline-block w-1.5 h-1.5 rounded-full', dotColor)} aria-hidden />
      <span className="font-mono tabular-nums">{price}</span>
    </span>
  )
}
```

### 6.13 Symbol Linking Color Dot (PLAN-0051 Wave C)

Workspace panels use a 5-color symbol-linking system inspired by Bloomberg's group
links. Every workspace panel header renders a tiny color dot (8-px circle inside a
12-px hit area) on the far left:

| Color | Hex | Notes |
|-------|-----|-------|
| `red` | `#EF5350` | Reuses `--negative` |
| `green` | `#26A69A` | Reuses `--positive` |
| `blue` | `#3B82F6` | Standard blue |
| `yellow` | `#FFD60A` | Reuses `--primary` |
| `purple` | `#A855F7` | Violet accent |
| `none` | (border-only outline) | Panel does not participate in any group |

Behaviour:

- Clicking the dot opens a Popover with all 6 options (one row each).
- Picking a color persists to `worldview:symbolLinks:v1` in localStorage; survives
  reload. Active symbols are NOT persisted — only the color choices.
- When a panel changes its active symbol, the new symbol is broadcast to every
  other panel sharing the same color. Panels with `color: "none"` stay independent.

Implementation:

- Picker component: `apps/worldview-web/components/workspace/SymbolLinkColorPicker.tsx`
- Context: `apps/worldview-web/contexts/SymbolLinkingContext.tsx`
  - Hook `useSymbolLink(panelId)` returns `{ symbol, instrumentId, isLinked }`.
  - Hook `useSymbolLinking()` exposes the full API (`links`, `setLinkColor`,
    `setActiveSymbol`, `getSymbolForPanel`).

### 6.14 Citation Confidence Bar Pattern (PLAN-0051 Wave E)

A compact horizontal strip visualising per-citation relevance scores below
RAG/Chat assistant messages. One segment per citation, coloured by score
band:

| Score band | Token | Visual |
|------------|-------|--------|
| `>= 0.7` | `bg-positive/70` | Green — high confidence |
| `0.4 – 0.7` | `bg-warning/70` | Amber — medium confidence |
| `< 0.4` | `bg-negative/70` | Red — low confidence |

Rules:

- Hover/focus a segment surfaces a tooltip via the native `title=` attribute
  (`[N] Title — Source — score% (band)`); screen readers get the same info
  via an `sr-only` span inside each segment.
- Each segment is an `<a href="#prefix-N">` linking to the matching `[N]`
  marker in the message body. Clicking smooth-scrolls the marker into view
  via `Element.scrollIntoView({behavior: "smooth", block: "nearest"})`.
- Component lives at `apps/worldview-web/components/chat/CitationBar.tsx`.
  Helper `scoreBand(score)` returns `"high" | "medium" | "low"` for tests.
- Pair the bar with the existing pill-style `CitationList` for click-through
  source links — the bar gives at-a-glance gestalt, the pills give
  navigation. Both rendered inside the assistant message bubble (PLAN-0051
  T-E-5-04).

### 6.11b Colour-blind Safe Encoding (PLAN-0051 Wave F)

Any visual that distinguishes categories purely by **colour** must add a redundant non-colour cue. The repo standard is:

1. **Pattern overlay** — apply a `repeating-linear-gradient` over the lower-priority segment so it reads as "striped" regardless of hue.
2. **Aria label** — `role="img"` + `aria-label="<name>: <value>"` so screen readers announce the proportion.
3. **Explicit text label** — render the category name + value next to the visual; never assume the swatch alone is enough.

```tsx
{/* Solid fill = primary (high-attention) segment */}
<div className="h-full bg-primary/60" style={{ width: `${pct}%` }} />

{/* Diagonal-stripe overlay = secondary segment — distinguishable by pattern */}
<div
  className="h-full bg-muted-foreground/30"
  style={{
    width: `${100 - pct}%`,
    backgroundImage:
      "repeating-linear-gradient(45deg, transparent 0px, transparent 2px, rgba(255,255,255,0.10) 2px, rgba(255,255,255,0.10) 3px)",
  }}
/>
```

Live examples:
- `components/portfolio/ExposureBreakdown.tsx` — Cash (striped) vs Invested (solid).
- `components/portfolio/SectorAllocationPanel.tsx` — sector bars carry both an `aria-label` and a faint diagonal pattern over the primary fill so the bar reads as "data marker" even in greyscale.

WHY this matters: ~8% of male users have a form of colour-vision deficiency (deuteranopia / protanopia / achromatopsia). A finance terminal that hides positions behind colour alone is hostile to those users. The pattern + label approach is also robust against future theme switches and printing (greyscale).

### 6.12 Keyboard Navigation

> **Updated 2026-06-10** — table synced to the actual `GlobalHotkeyBindings` registrations.
> Chords are registered in `lib/hotkey-registry.ts` (custom scope-stack registry, NOT
> react-hotkeys-hook) and dispatched by `hooks/useChordHotkeys`. The StatusBar and the
> `?` cheat sheet render hints FROM the registry, so they cannot advertise an unwired chord.

| Shortcut | Action | Notes |
|----------|--------|-------|
| `g d` | Navigate /dashboard | Sequence: press g, then the letter |
| `g s` | Navigate /screener | |
| `g i` | Navigate /instruments | |
| `g p` | Navigate /portfolio | |
| `g w` | Navigate /workspace | |
| `g a` | Navigate /alerts | |
| `g n` | Navigate /news | |
| `g c` | Navigate /chat | |
| `g ,` | Navigate /settings | |
| `g h` | Open keyboard cheat sheet | Alias for `?` |
| `⌘B` / `Ctrl+B` | Toggle sidebar | |
| `⌘K` / `Ctrl+K` | Toggle CommandPalette | Registered as `shell.command.palette` (Round-3, 2026-06-10) — see §6.15 |
| `/` | Focus global search | Registered only when the layout supplies the handler |
| `?` | Toggle cheat-sheet overlay | Registered by `HotkeyCheatSheet` |
| `Escape` | Close active modal/overlay | |

**Spec conformance (Round-3 audit, 2026-06-10)**: the product-spec chords
`G→D /dashboard`, `G→S /screener`, `G→P /portfolio`, `G→C /chat` were all already
registered — no remaps were needed; the table above is the live registration list
(pinned by `__tests__/global-hotkey-bindings.test.tsx`).

**Input suspension rule**: modifier-less chords (`g d`, `?`, `/`) are suspended while
focus is in an `<input>`, `<textarea>`, or `[contenteditable]` — typing a literal `?`
never opens the cheat sheet. Modifier-bearing chords (`⌘K`, `⌘B`) bypass suspension and
fire even mid-typing (e.g. ⌘K from the chat composer). Both behaviors are pinned in
`__tests__/use-chord-hotkeys.test.tsx` and `__tests__/hotkey-cheat-sheet.test.tsx`.

**`?` cheat-sheet overlay** (`components/shell/HotkeyCheatSheet.tsx`, mounted once in
`app/(app)/layout.tsx`): renders `registry.all()` verbatim, grouped by the binding's
`group` field (Navigation → Symbol → Action → View → Editing) with a filter input.
Esc, `?` again, `g h`, or backdrop click closes. Page-scoped bindings (e.g. instrument
D/F/N/I mnemonics) are shown only on their route. Because the rendered list IS the
binding list, it is structurally impossible for the overlay to advertise an unwired
shortcut (the no-lying invariant). Known gap: the chat tool-trace debug chord
(`features/chat/hooks/useToolTraceChord`) still uses a raw document listener and is
therefore invisible to the overlay — migrating it into the registry is chat-surface
work (Round-4).

### 6.15 Command Palette Pattern (NEW — 2026-06-10)

**Component**: `components/shell/CommandPalette.tsx`, mounted ONCE in `app/(app)/layout.tsx`
(available on every authenticated route). Built on the shadcn `CommandDialog`
(`components/ui/command.tsx`, cmdk under the hood).

**Trigger** (three paths, one open state):
1. `⌘K` / `Ctrl+K` — registered in `lib/hotkey-registry` as `shell.command.palette`
   (group `Symbol`) by the palette itself; dispatched by the single `useChordHotkeys`
   document listener. **Round-3 change (2026-06-10)**: the previous raw document
   listener was removed — its "registry suspends chords in inputs" rationale was wrong
   (only modifier-LESS chords are suspended; `mod+k` always passes through). Registry
   routing makes ⌘K appear in the `?` cheat sheet automatically and keeps exactly one
   keydown listener dispatching every chord. Toggle goes through `handleOpenChange`
   so closing via ⌘K resets the query like Escape does.
2. `worldview:open-command-palette` CustomEvent — dispatched by the TopBar "⌘K" hint chip
   (exported constant `OPEN_COMMAND_PALETTE_EVENT`). Same decoupling pattern as
   `worldview:open-ai-panel`.
3. `Escape` / overlay click closes (Radix Dialog); closing resets the query.

**Groups** (in render order):

| Group | Source | Behaviour |
|-------|--------|-----------|
| Navigate | static `NAV_ITEMS` (enumerated from `app/(app)/`) | substring filter on label + keywords; chord hints rendered via `formatChordForDisplay` (no-lying invariant) |
| Recent Instruments | `lib/recent-instruments.ts` localStorage stack | shown only while the query is empty (Bloomberg "last 5 visited") |
| Instruments | S9 `GET /v1/search/instruments` (debounced 250ms, shared `["instrument-search", q]` cache key with GlobalSearch) | shown only while a query is typed |
| Recent Conversations | S9 `GET /v1/threads` via `qk.chat.threads()` (read-only, shared cache with /chat) | top-5 newest by `updated_at`; title substring filter |

**Ranking** (pure functions in `lib/command-palette.ts`, unit-tested):
exact ticker match → ticker-prefix match → server order; recently-visited instruments
float within each tier. Conversations sort newest-first.

**Styling tokens** (Terminal Dark):
- `CommandDialog` props: `contentClassName="top-[20%] max-w-xl translate-y-0 rounded-[2px] …"`
  (top-anchored so the list grows downward; 2px radius rule; built-in X button hidden via
  `[&>button]:hidden` — Escape is the close affordance)
- `commandClassName` overrides cmdk's consumer-scale defaults to terminal density:
  36px input @ 12px, `py-1.5` items, 14px icons, 10px uppercase group headings
- Rows: 11px primary text, 10px muted secondary, `font-mono tabular-nums` tickers,
  `ml-auto` muted hints (chord / exchange / "recent")
- Footer hint strip: `↑↓ Navigate · ↵ Open · ⎋ Close` at 9px (same as GlobalSearch dropdown)

**Selection**: every `CommandItem` wires BOTH `onSelect` (keyboard Enter) and `onClick`
(mouse) — the SEARCH-001 dual-handler rule. Instrument selection persists to the shared
recents stack (`saveRecentInstrument`) before `router.push(/instruments/<entity_id>)`
(ADR-F-12: route by entity_id). Conversations push `/chat?thread=<id>` — the chat page
does not consume the param yet (forward-compatible contract; chat surface wires it).

**A11y**: sr-only `DialogTitle`/`DialogDescription` (Radix requirement), sr-only
`aria-live` region announcing instrument result counts, `aria-hidden` icons.

**Reuse rule**: any future palette-like surface MUST use `CommandDialog` with
`shouldFilter={false}` when it performs its own filtering — cmdk's built-in fuzzy filter
matches against item `value` strings (namespaced ids like `inst:<uuid>`) and silently
hides everything otherwise.

### 6.16 Toast Pattern (Round-3 polish — 2026-06-10)

**One library, one mount, one config.** All transient notifications use **sonner**
(`import { toast } from "sonner"`). The single `<Toaster>` is mounted in
`app/providers.tsx` — never mount a second one (every toast would render twice).
Pinned by the source-contract test `__tests__/toast-config.test.ts`.

**Locked configuration** (set once on the Toaster, NOT per call):

| Setting | Value | Why |
|---------|-------|-----|
| `position` | `top-right` | FU-10.3 locked decision; above shell chrome (z-60), below FlashOverlay |
| `visibleToasts` | `3` | More overlapped the TopBar content row on 768px laptops; older toasts collapse into the stack |
| `duration` | `4000` ms | Auto-dismiss 4s — explicit, so a sonner upgrade can't silently change UX |
| `theme` / styling | `dark`, `richColors`, `font-mono text-[11px] tabular-nums` | Terminal Dark density — toasts match StatusBar/row rhythm |
| `closeButton` + `expand` | on | Manual dismiss affordance; hover expands the stack |

**Call-site rules**:
- Use the semantic helpers: `toast.success(msg)` / `toast.error(msg)` / `toast.info(msg)` /
  bare `toast(msg)` for neutral notices. Optional `{ description }` for a second line,
  `{ action: { label, onClick } }` for one inline action.
- **Never** pass `duration`, `position`, `className`, or style overrides at the call
  site — behavior is centralized on the provider. Sole sanctioned exception:
  `hooks/useConfirmable.tsx` sets `duration: undoWindowMs` because the toast lifetime
  IS the undo window (a functional timer, not styling).
- Errors that block a workflow belong in inline `<ErrorCard>` / form errors, not toasts;
  toasts are for fire-and-forget outcomes (saved, queued, dismissed, undone).

### 6.6 Empty State Pattern

```tsx
function EmptyState({ message, action }: { message: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <p className="text-muted-foreground text-sm">{message}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
```

### 6.7 Error State Pattern

```tsx
function ErrorCard({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <Card className="border-destructive/50">
      <CardContent className="flex items-center justify-between p-4">
        <span className="text-sm text-destructive">{message}</span>
        <Button variant="outline" size="sm" onClick={onRetry}>Retry</Button>
      </CardContent>
    </Card>
  )
}
```

#### 6.7.1 Route Error Boundaries (`error.tsx`) — Round-4 hardening, 2026-06-10

The ErrorCard above handles **query-level** failures (a panel's fetch failed).
**Render-level** failures (a component threw during render) are handled by the
App Router `error.tsx` boundary chain. Nearest boundary wins:

```
per-route error.tsx (e.g. app/(app)/news/error.tsx)
  → app/(app)/error.tsx          # group fallback — keeps the shell chrome
    → app/error.tsx              # root — renders OUTSIDE the shell
      → app/global-error.tsx     # last resort — replaces <html>/<body> itself
        → Sentry.ErrorBoundary   # app/providers.tsx (also reports to Sentry)
```

**The shared body is `components/primitives/RouteErrorFallback.tsx`.** Every
NEW per-route `error.tsx` must be a thin wrapper around it (don't hand-roll a
variant — that's how the pre-Round-4 drift happened):

```tsx
"use client";                                   // mandatory for error.tsx
import { RouteErrorFallback } from "@/components/primitives/RouteErrorFallback";

export default function NewsError({ error, reset }: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <RouteErrorFallback error={error} reset={reset} routeLabel="News" />;
}
```

The primitive's contract (pinned by
`components/primitives/__tests__/RouteErrorFallback.test.tsx`):

1. **Named state** — `routeLabel` renders as the uppercase mono micro-label so
   the broken surface is identifiable in a screenshot.
2. **Icon** — `AlertTriangle` in warning tone (route errors are recoverable;
   the red `XCircle` is reserved for the fatal `app/error.tsx` /
   `global-error.tsx` tiers).
3. **"Try again"** — `<button>` wired to the Next.js `reset()` callback
   (segment re-render, NOT navigation).
4. **Digest, small** — `error.digest` in 9px mono at 50% opacity when present
   (debug correlation handle); **`error.message` is never rendered** —
   generic copy only, real error goes to `console.error` (Sentry capture
   happens upstream in `Sentry.ErrorBoundary`; don't double-report).
5. **Escape hatch** — "Back to dashboard" link for the reset-keeps-failing case.

`app/global-error.tsx` intentionally does NOT use the primitive: the
last-resort path keeps its dependency graph minimal (plain elements, inline
SVG, `<a href>` full reload) because the crash may have come from a shared
module — importing one back would crash the boundary too.

### 6.8 Real-Time UI Patterns

**WebSocket (alert stream)**:
- Connection status visible in TopBar (subtle dot indicator)
- New items slide in at top of list (not replace-all)
- CRITICAL alerts trigger `FlashOverlay` via `AlertStreamContext`
- Exponential backoff reconnect: 1s → 2s → 4s → ... → 30s cap

**SSE (chat streaming)**:
- State machine: `idle → sending → streaming → reconciling → settled`
- Show cursor blinking indicator during `streaming` state
- `AbortController` per request — cancel button visible during streaming
- Scroll to bottom on new tokens; stop auto-scroll if user scrolls up

---

## 7. Navigation Structure

```
AppSidebar (220px fixed)
├── [Logo + "Worldview"]
├── Dashboard          /dashboard
├── Workspace          /workspace   ← NEW (drag-and-drop terminal)
├── Companies          /companies
├── Portfolio          /portfolio
├── News               /news (tabs: Feed | Top Today)
├── Screener           /screener
├── Chat               /chat
├── Map                /map
└── [divider]
    ├── [keyboard hint strip: g+d g+w g+c ⌘K]
    └── User avatar + email + Logout (bottom)
```

Active nav item: `bg-primary/10 text-primary font-medium`
Inactive nav item: `text-muted-foreground hover:text-foreground hover:bg-muted/50`

---

## 8. Component File Conventions

| Rule | Detail |
|------|--------|
| Component > 80 lines | Its own file |
| All imports | `@/` alias (never relative `../../`) |
| No `any` types | Find or create the typed interface |
| Interfaces | For object shapes |
| Types | For unions / intersections |
| Error boundary | Per page section (use `react-error-boundary`) |
| `"use client"` | Only when needed (DOM, hooks, event handlers) |

---

## 8b. Chart-Toolbar Pattern (PLAN-0050 Wave C)

> **Added**: 2026-04-29. Documents the TradingView-style chart toolbar added in Wave C.
> The chart now has 4 layers: timeframe tabs | ChartToolbar | DrawingPalette | DrawingCanvas SVG overlay.

### 8b.1 Toolbar Layout

```
[5M] [1H] [1D] [1W] [1M]    [MA50] [MA200] [VOL N▾] [IND N▾] [⛶]
^— timeframe tabs (left)                     ^— ChartToolbar (ml-auto, right)
```

- `h-7` (28px) total toolbar height — Bloomberg terminal density
- No label text, only compact abbreviations + Unicode glyphs
- Active state: `bg-primary/20 text-primary` (brand yellow fill)
- Inactive state: `text-muted-foreground hover:text-foreground`

### 8b.2 Indicators Dropdown (IND N)

Uses `shadcn/ui DropdownMenu` with `DropdownMenuCheckboxItem` per indicator.

```
IND 3  ← trigger button; shows count of active indicators
├─ [✓] RSI    Relative Strength Index (14)
├─ [✓] MACD   MACD (12, 26, 9)
├─ [✓] BB     Bollinger Bands (20, 2σ)
├─ [ ] ATR    Average True Range (14)
├─ [ ] STOCH  Stochastic Oscillator (14, 3, 3)
├─ [ ] OBV    On-Balance Volume
└─ [ ] VWAP   Volume Weighted Avg Price
```

**State**: `indicators: Record<IndicatorId, IndicatorConfig>` in OHLCVChart state.
**Persistence**: `localStorage` key `worldview:chart:indicators:v1` (JSON). Merges with defaults on load.
**Computation**: All 7 indicators computed client-side in `lib/instrument-context.ts` — no new API endpoints.

**Sub-pane indicators** (render below main chart on their own Y scale):
- RSI → `priceScaleId: "rsi"` — amber (#F59E0B), scaleMargins top:0.85
- MACD → `priceScaleId: "macd"` — line=purple, signal=amber, histogram=teal/red
- ATR → `priceScaleId: "atr"` — emerald (#10B981), scaleMargins top:0.80
- Stochastic → `priceScaleId: "stoch"` — %K=teal, %D=red, scaleMargins top:0.80

**Main-pane indicators** (overlay on main candlestick Y scale):
- Bollinger Bands → `priceScaleId: "right"` — indigo (#6366F1), dashed lines (lineStyle:2)
- OBV → `priceScaleId: "obv"` — sky (#38BDF8), separate volume scale
- VWAP → `priceScaleId: "right"` — pink (#EC4899), dotted line (lineStyle:1)

### 8b.3 Volume Submenu (VOL N)

```
VOL 2  ← trigger; count of active volume sub-indicators
├─ [✓] Base Volume      (histogram, existing)
├─ [ ] Volume MA20      (lime line on volume scale, period 20)
├─ [✓] Volume Profile   (right-side SVG overlay, 60px wide)
└─ [ ] VWAP Line        (pink dotted on price scale, anchored daily)
```

Volume Profile renders as `VolumeProfileOverlay.tsx` — an absolutely-positioned SVG, NOT a lightweight-charts series (no native horizontal histogram support in v4). The Point of Control (highest volume bucket) is highlighted in brand yellow (#FFD60A).

### 8b.4 Drawing Palette + Canvas

**Left-side 28px palette** (`DrawingPalette.tsx`):
- Absolutely positioned `inset-y-0 left-0`, `w-7 z-10`
- Tools: ✕ CURSOR, ╱ Trend Line, ─ Horizontal Level, □ Rectangle, ↗ Arrow, φ Fib Retracement, ≡ Parallel Channel, T Text
- Active tool: `bg-primary/20 text-primary` + `aria-pressed="true"`
- Click-to-arm; click again to disarm; CURSOR always disarms
- `data-testid="drawing-tool-{tool-id-kebab}"` on each button

**SVG annotation overlay** (`DrawingCanvas.tsx`):
- Sibling of chart container (not child), absolutely positioned `left: 28px`, `width: calc(100% - 28px)`, same height as chart
- `pointer-events: all` when tool armed; `pointer-events: none` (pass-through) when in cursor mode
- Multi-click model: click → capture point; when required points collected → commit annotation
- Annotation shapes: TrendLine (line), HorizontalLevel (full-width dashed + price label), Rectangle (stroke + 10% fill), Arrow (line + marker), FibRetracement (7 horizontal levels at 0/23.6/38.2/50/61.8/78.6/100%), ParallelChannel (2 lines + fill polygon), Text (anchor circle + label)
- Right-click any annotation → context menu → delete

**Persistence** (`lib/instrument-context.ts`):
- Annotations → IndexedDB (`worldview-chart-annotations`, store: `annotations`, key: `instrumentId`)
- Per-annotation record: `{ id, tool, createdAt, color, ...tool-specific fields }`
- Load on mount: `loadAnnotationsFromIDB(instrumentId)` (async, returns `[]` on any failure)
- Save on add/delete: `saveAnnotationsToIDB(instrumentId, annotations[])` (fire-and-forget)

### 8b.5 Coordinate System

```
lightweight-charts            SVG overlay
─────────────────────         ─────────────────────
chart.timeScale()             x: timeToCoordinate(unixSeconds) → pixel X
  .timeToCoordinate(time)     (null when off-screen → -9999 for SVG)
  .coordinateToTime(x)

series.priceToCoordinate(p)   y: priceToCoordinate(price) → pixel Y
series.coordinateToPrice(y)   (null when off-screen → -9999 for SVG)
```

Both converters are stored in `converters: CoordinateConverter | null` state. The SVG renders stale coordinates when the user pans the chart (no "viewport changed" event in v4 — see PLAN-0053 deferred).

---

## 8c. Instrument Detail Page (PRD-0088 / PLAN-0090) — 2026-05-19

> **Added**: 2026-05-19 in PLAN-0090 T-E-04. Documents the ground-up redesign of
> `/instruments/[entityId]` shipped across waves A–E.
> **Spec**: `docs/specs/0088-instrument-detail-page-ground-up-redesign.md`
> **Plan**: `docs/plans/0090-instrument-detail-page-redesign-plan.md`
> **Supersedes**: the 9-section card pattern from PLAN-0041 (Fundamentals tab) and
> the 4-tab layout from PLAN-0071 phase 6.5+. The legacy
> `OverviewLayout` / `FundamentalsTab` / `IntelligenceTab` (old) /
> `NewsTab` (old) components and 36 sibling files under `components/instrument/`
> were **deleted in T-E-01** (40-file sweep) — verify with
> `git log --diff-filter=D --name-only --since=2026-05-17 -- components/instrument/`
> before re-introducing any of those names.

### 8c.1 Why the Redesign Exists

The previous instrument page hit ~30px effective row height (despite claiming
22px), spent ~50% of the Fundamentals tab on section-card chrome, and split
News + Intelligence into two tabs even though they answer the same question
("what does the market think of this name right now?"). The redesign restores
Bloomberg-grade density (≥40 data points above the fold on Quote tab) and
collapses News into the Intelligence tab so the entity graph, the brief, and
the news headlines render in one viewport.

**Hard rules in this surface**:

1. Every numeric value is `font-mono tabular-nums` (ADR-F-15). Null values
   render as `—` (em-dash) in the same monospace face so columns never jitter.
2. No off-palette colour utilities — `text-warning` (NOT `text-amber-400`).
   Enforced by the no-off-palette-colors Vitest (Wave E gate; T-E-02).
3. Cautionary state (e.g. P/E > 30) uses the semantic `text-warning` token,
   which resolves to `#F59E0B` via `--warning`. Negative danger states use
   `text-negative` (`#EF5350`).
4. Every component file ≤ 200 lines (orchestrators ≤ 300). If you need more,
   split into a hook + a sub-component.

### 8c.2 Page Shell — Header + Brief + Tabs (Wave A)

The page client (`InstrumentPageClient.tsx`, T-A-05) renders three sticky-stacked
chrome rows above the active tab body:

| Component | File | Height | Source task |
|-----------|------|--------|-------------|
| `InstrumentHeader` | `components/instrument/header/InstrumentHeader.tsx` | 36px sticky | T-A-04 |
| `WeekRangeMini` | `components/instrument/header/WeekRangeMini.tsx` | 60×6px inline | T-A-04 |
| `AiBriefBanner` | `components/instrument/brief/AiBriefBanner.tsx` | 24px collapsed / auto expanded | T-A-04 |
| `InstrumentTabs` | `components/instrument/tabs/InstrumentTabs.tsx` | 32px | T-A-04 |

**`InstrumentHeader`** — single 36px row, `position: sticky; top: 0; z-30;
bg-background border-b border-border`. Left cluster: back chevron + ticker
(13px mono semibold) + exchange badge + truncated company name. Right cluster:
price + signed change + signed change% (colour by sign via `priceChangeClass`),
then `CAP` / `VOL` / `P/E` label-value pairs (10px sans label + 11px mono
value), then a `WeekRangeMini`, then a `LiveQuoteBadge` (freshness dot only —
no second price). Props: `{ instrument, quote, fundamentals }`. Every sub
value is rendered through the `formatPrice` / `formatPercentDirect` /
`formatMarketCap` / `formatVolume` / `formatRatio` helpers in `lib/utils.ts`
so the null-handling stays consistent.

**`WeekRangeMini`** — 60px wide × 6px tall `bg-muted` track with a `bg-primary`
(`#FFD60A`) fill positioned at `(price − low) / (high − low) × 100%`, clamped
to `[0, 100]`. Used both inline in the header (without labels) and standalone
in the Quote-tab MetricsTable row 19. The label-less variant is the canonical
Bloomberg-style inline range indicator — no axis ticks, no numbers, the bar
itself communicates position because the surrounding row already labels it
"52W RANGE".

**`AiBriefBanner`** — single-line collapsible banner between the tabbar and the
tab body. Collapse state is persisted per session in `sessionStorage` under
the key `wv:brief-collapsed:{entityId}`. Why `sessionStorage` (not `localStorage`):
the choice is per-browser-tab/window, not per-user; opening a second
instrument in a new tab should not inherit your collapse state. Banner is
hidden entirely (return `null`) when the brief endpoint returns 404 or empty —
**never** render an "unavailable" placeholder for the brief because that wastes
the same vertical real estate the banner exists to economise on.

**`InstrumentTabs`** — 3-tab underline control (QUOTE / FINANCIALS / INTELLIGENCE).
Active tab carries a 2px `border-primary` bottom edge and `text-foreground`;
inactive tabs use `text-muted-foreground`. Mounts a `HotkeyScope` that binds
`Q` / `F` / `I` to the three tabs respectively. The scope auto-suspends inside
text inputs (search, filters) so the chord set never collides with typing.

### 8c.3 Shared Primitives (Wave A — T-A-01..03)

Two primitives form the typographic backbone of every metric on the page:

| Component | File | Purpose |
|-----------|------|---------|
| `MetricLabel` | `components/instrument/shared/MetricLabel.tsx` | 10px uppercase muted label (`text-[10px] uppercase tracking-wide text-muted-foreground`) |
| `MetricValue` | `components/instrument/shared/MetricValue.tsx` | 11px IBM Plex Mono tabular-nums value with `color` prop |

**`MetricValue` colour prop** maps to Tailwind utilities (not raw hex):

| `color` value | Class | When to use |
|---------------|-------|-------------|
| `"positive"` | `text-positive` | Gains, ROE > 15%, margin in the green |
| `"negative"` | `text-negative` | Losses, P/E > 50, ROE < 0 |
| `"amber"` | `text-warning` | Cautionary thresholds (P/E 30–50, D/E 1.5–3) |
| `"muted"` | `text-muted-foreground` | De-emphasised / inactive values |
| `"default"` | `text-foreground` | Neutral body value (default) |

Null / undefined `children` resolve to `—` in the same monospace face. This is
the "absent data" placeholder — **not** a loading state (use shadcn `Skeleton`
for loading). All Quote/Financials/Intelligence cells are built on these two
primitives so the typography token is impossible to drift.

Secondary primitives: `SectionDivider` (1px `bg-border/30` separator with
optional label) and `DataTimestamp` ("Data as of {date}" footer, 10px muted).

### 8c.4 Quote Tab (Wave B — T-B-01..05)

`QuoteTab.tsx` (T-B-04) is a thin orchestrator that wires `useMetricsTableData`
into two children:

| Component | File | Source task |
|-----------|------|-------------|
| `OHLCVChart` | `components/instrument/chart/OHLCVChart.tsx` | T-B-01 — refactored to <180 lines; the `hasScrolledToRealTime` race that caused the chart to scroll back to 1985 on load was excised here |
| `TimeframeToolbar` | `components/instrument/chart/TimeframeToolbar.tsx` | T-B-01 — 1D/1W/1M/6M/1Y/5Y |
| `ChartToolbar` | `components/instrument/ChartToolbar.tsx` | KEEP (minor cleanup) |
| `SessionStatsStrip` | `components/instrument/SessionStatsStrip.tsx` | T-B-01 — `O H L C VOL` strip in 22px row |
| `MetricsTable` | `components/instrument/quote/metrics/MetricsTable.tsx` | T-B-03 |
| `MetricRow` | `components/instrument/quote/metrics/MetricRow.tsx` | T-B-02 |
| `MetricGroupDivider` | `components/instrument/quote/metrics/MetricGroupDivider.tsx` | T-B-02 |
| `WeekRangeBar` | `components/instrument/quote/metrics/WeekRangeBar.tsx` | T-B-02 |
| `AnalystMiniBar` | `components/instrument/quote/metrics/AnalystMiniBar.tsx` | T-B-02 |

**`MetricsTable`** is the canonical right-sidebar data pattern for the instrument
detail surface and **replaces the legacy 9-section card pattern** that
PLAN-0041 shipped. It renders **26 data rows + 7 group dividers** in a fixed
40%-width column on the Quote tab. Layout invariants per row:

- Wrapper: `flex items-center justify-between h-[22px] px-3`
- Label: 10px ALL CAPS muted (`MetricLabel`, `flex-1 truncate`)
- Value: 11px mono via `MetricValue` with a colour token (see threshold rules
  in PRD-0088 §6.4 / FR-10)

Group dividers use `MetricGroupDivider` (a 1px `bg-border/30` rule with
`mx-3 my-0.5`). Row 19 swaps the value cell for a `WeekRangeBar`; row 26 swaps
it for an `AnalystMiniBar` (a 3-segment `[buy / hold / sell]` proportional bar
plus a `28B · 10H · 2S` caption in 10px mono).

**Colour thresholds (FR-10)** are encoded once in `useMetricsTableData.ts`
and consumed by every row — never inline a threshold in JSX. Examples baked
into the hook: P/E > 30 → `amber`, P/E > 50 → `negative`; D/E > 1.5 → `amber`,
D/E > 3 → `negative`; Net Margin < 0 → `negative`, > 15% → `positive`.

### 8c.5 Financials Tab (Wave C — T-C-01..04)

`FinancialsTab.tsx` (T-C-03) orchestrates the four panels:

| Component | File | Source task |
|-----------|------|-------------|
| `FlatMetricsGrid` | `components/instrument/financials/FlatMetricsGrid.tsx` | T-C-01 |
| `MetricCell` | `components/instrument/financials/MetricCell.tsx` | T-C-01 |
| `IncomeStatementTable` | `components/instrument/financials/IncomeStatementTable.tsx` | T-C-02 |
| `EarningsBarChart` | `components/instrument/financials/EarningsBarChart.tsx` | T-C-02 |
| `AnalystSidebar` | `components/instrument/financials/AnalystSidebar.tsx` | T-C-03 |

**`FlatMetricsGrid`** — the redesign's most important density win. A `<dl>`
laid out as `grid-cols-3 gap-x-6 gap-y-0` showing **45 metrics across 8 group
headers** (VALUATION / PROFITABILITY / GROWTH / BALANCE SHEET / CASH FLOW /
DIVIDENDS / OWNERSHIP / TECHNICALS). No section cards, no card borders, no
section padding — just label/value pairs separated by a 1px divider with a
10px ALL CAPS group label. Each cell is a `MetricCell` of 36px total height
(14px label + 22px value, gap=0). This is the **3-col flat pattern** that
replaces the old 9-section card layout; reuse it for any new "show N
fundamentals" surface elsewhere in the app.

`MetricCell` itself is a 2-line `<dt>/<dd>` pair that wraps `MetricLabel` + `MetricValue`
so the typography stays locked. Threshold colouring uses the same `color`
mapping as the Quote-tab MetricsTable.

**`IncomeStatementTable`** — 4-year FY table (Revenue, Gross Profit, EBIT,
Net Income, EPS), 22px rows, right-aligned `font-mono tabular-nums` cells.
**`EarningsBarChart`** — 6–8 bars (actual EPS solid, estimate outlined; beat =
`bg-positive`, miss = `bg-negative`), 80px tall, fiscal-year labels on the
x-axis.

**`AnalystSidebar`** (280px right column, sticky) — consensus block
(stacked Buy/Hold/Sell mini bar with `28B · 10H · 2S` caption), target price
(13px mono semibold) with high/low range, "Based on N analysts" tag, and a
`DataTimestamp` footer. The 280px width is fixed across the whole page so the
sidebar lines up visually with the right-edge containers on other tabs.

### 8c.6 Intelligence Tab (Wave D — T-D-01..04)

`IntelligenceTab.tsx` (T-D-04) is a 3-column flex layout that unifies news,
graph, and entity context in a single viewport — replacing the old
News+Intelligence two-tab split.

| Column | Component | File | Source task |
|--------|-----------|------|-------------|
| Left (30%) | `NewsColumn` + `NewsFilters` + `CompactArticleRow` | `components/instrument/intelligence/news/` | T-D-02 |
| Centre (45%) | `GraphColumn` + `GraphToolbar` + `EntityGraph` | `components/instrument/intelligence/graph/` + `components/instrument/EntityGraph.tsx` | T-D-01 + T-D-04 |
| Right (25%) | `ContextPanel` + `NodeDetailCard` + `RelationsList` | `components/instrument/intelligence/context/` | T-D-03 |

**`NewsColumn`** uses `useEntityNewsInfinite` (a `useInfiniteQuery` wrapper around
`GET /v1/news/entity/{entityId}?limit=20&offset=N`). Each article renders as a
28px `CompactArticleRow`:
`[sentiment dot 6px] [relative time 10px mono] [source 10px truncate] [headline 11px truncate flex-1] [impact 10px mono muted]`.
Sentiment dot colour follows FR-10 (`bg-positive` / `bg-negative` /
`bg-muted-foreground`). Infinite scroll loads the next 20 on scroll-to-bottom.

**`GraphColumn`** stacks an always-expanded AI brief card, a `GraphToolbar`
(depth slider 1–3 + relationship-type multi-select + fullscreen), and the
`EntityGraph` (Cytoscape/sigma.js). Depth-3 is wrapped in a **2000ms client
timeout** (T-D-01) — if S9 stalls, the component shows a "Network timeout —
try a lower depth" message instead of a blocking spinner. This was a frequent
user-facing failure with the legacy graph.

**`ContextPanel`** flips between two states based on the locally-held
`selectedNodeId`:

- **No node selected** → entity overview (description, health score, evidence
  quality bars, contradictions cards when count > 0).
- **Node selected** → `NodeDetailCard` (name, type badge, confidence score,
  back button to deselect) + `RelationsList` (per-edge rows with type badge,
  target name, italic evidence snippet truncated to 2 lines).

Contradiction cards (`ContradictionCard.tsx`, kept from the legacy code with
polish) anchor to the bottom of the column when `contradictions.length > 0`,
using `bg-negative/5 border border-negative/20`.

### 8c.7 Density Reference

The redesign establishes two canonical data-row heights:

| Pattern | Height | Used in |
|---------|--------|---------|
| `MetricRow` | **22px** | `MetricsTable` (Quote tab right column), threshold-coloured numeric rows on any future panel |
| `CompactArticleRow` | **28px** | `NewsColumn` (Intelligence tab), any future article-list surface |

Anywhere on the instrument detail surface that needs a new dense row should
reuse one of these two heights — picking arbitrary intermediate values
(24, 26, 30) reintroduces the jitter that the redesign eliminated.

### 8c.8 Deleted Legacy Components

The 40 files removed in T-E-01 (verify via
`git show 58cbeec1 --stat | grep "^ apps/worldview-web/components/instrument"`):
`InstrumentAISubheader`, `AnalystRail`, `PerformanceBar`, `OverviewLayout`,
`OverviewSidebar`, `FundamentalsTab`, `FundamentalsMetricsGrid`,
`InstrumentKeyMetrics`, `NewsTab`, `IntelligenceTab` (legacy),
`InstrumentTopNews`, `OverviewInsiderStrip`, `FundamentalSparkline`,
`InsiderTransactionsTable`, `AnalystConsensusStrip`, `RevenueTrendSparklines`,
`IncomeStatementFY`, `AnalystTargetSparkline`, `MarketPositionPanel`,
`PeerComparisonPanel`, `ShortInterestRow`, `FundamentalsTopNews`,
`InstrumentBriefSection`, `IntelligenceSummarySection`, `IntelligenceFilters`,
`GraphDetailSidebar`, `TechnicalSnapshot`, `OwnershipSnapshotPanel`,
`SplitsDividendsPanel`, `EarningsHistoryChart`, `52WeekRangeBar`,
`CompactInstrumentHeader`, `DrawingPalette`, `DrawingCanvas`, `CrosshairHUD`
+ supporting test files. Do not re-introduce any of those names — the
redesign uses distinct file names on purpose so old grep paths fail loudly.

### 8c.9 Wave E Gates (T-E-01..04)

The Wave E validation gate enforces the architectural invariants documented
above:

| Gate | Task | Tool |
|------|------|------|
| Zero references to deleted component files | T-E-01 | `grep -r` sweep |
| No off-palette utility classes (`text-amber-NNN`, `text-red-NNN`, etc.) | T-E-02 | Vitest: `__tests__/no-off-palette-colors.test.ts` |
| All 29+ unit tests pass + 7 Playwright E2E tests pass | T-E-03 | `pnpm test` + `pnpm test:e2e` |
| `pnpm tsc --noEmit` returns 0 errors | T-E-04 | `pnpm typecheck` |
| `pnpm build` succeeds (catches missing `"use client"`, server-component violations `tsc` misses) | T-E-04 | `pnpm build` |
| DESIGN_SYSTEM.md updated with the new component catalogue | T-E-04 | this section |

**WHY a dedicated no-off-palette-colors test**: when a junior dev reaches for
`text-amber-400` because it's the muscle-memory Tailwind colour, the value
resolves to a hex that drifts from `--warning` (#F59E0B today but mutable).
The test grep-fails the build the moment any off-palette utility lands.
The sanctioned cautionary colour is **`text-warning`** — period.

---

## 9. TanStack Query Conventions

### Global QueryClient Defaults (Round-4 hardening, 2026-06-10)

The platform-wide cache policy lives in `makeQueryClient()` in
`app/providers.tsx` and is pinned by `__tests__/query-client-defaults.test.ts`
(source-contract test — see the file docstring for why it greps instead of
importing the provider tree):

| Option | Value | Why |
|---|---|---|
| `queries.staleTime` | `30_000` | No refetch storm on every mount; per-hook overrides below handle hot/cold data |
| `queries.retry` | `1` | Fail fast — TanStack's default 3 exponential retries hides an outage for 3+ seconds, unacceptable for a terminal |
| `queries.refetchOnWindowFocus` | `true` | Prices refresh when the user returns to the tab |
| `queries.gcTime` | library default (5 min, deliberate) | Unmounted data survives tab-switching; don't raise globally (quote-data memory footprint) |
| `mutations.retry` | `0` (explicit) | **Writes are never auto-retried** — a retried mutation that partially succeeded can duplicate orders/alerts/watchlist entries. Pinned explicitly so a library default change can't silently introduce write retries. Per-call override allowed only for provably idempotent mutations |

All data fetching MUST go through TanStack Query (`lib/api/*` + hooks).
Sanctioned raw-`fetch()` exceptions: SSE/streaming consumers
(`features/chat/hooks/useChatStream.ts`, `components/shell/AskAiPanel.tsx`),
the pre-auth login POST (`app/login/page.tsx`), server-side route handlers
(`app/(public)/status/api/uptime/route.ts`), and the deploy-detection poll
(`components/shell/ForceUpdateBanner.tsx`, `cache: "no-store"` by design).
Anything else bypassing the cache is a defect.

### staleTime Per Data Type (set at hook level, not globally)

| Data type | staleTime | Rationale |
|-----------|-----------|-----------|
| Company overview / fundamentals | `300_000` (5 min) | Changes infrequently |
| OHLCV chart data | `60_000` (1 min) | Market hours update every minute |
| Live quotes (single) | `5_000` (5 sec) | Matches S3 Valkey cache TTL |
| Batch quotes (portfolio, heatmap) | `30_000` (30 sec) | Reduce S9 load |
| InstrumentContext | `3_600_000` (1 hr) | Sector/entity_id rarely changes |
| News articles list | `30_000` (30 sec) | New articles arrive frequently |
| Screener results | `60_000` (1 min) | Filters change per session |
| Prediction markets | `15_000` (15 sec) | High volatility, real-time feel |
| Temporal events (macro) | `300_000` (5 min) | Macro events update slowly |
| Chat threads | `30_000` (30 sec) | User-specific, low churn |

### HydrationBoundary (required for data-heavy pages)

All data-heavy pages (CompanyDetail, Portfolio, Screener) use Server Component prefetch + `HydrationBoundary` to eliminate the initial loading spinner flash:

```typescript
// page.tsx (Server Component) — prefetch on server
import { dehydrate, HydrationBoundary, QueryClient } from '@tanstack/react-query'

export default async function Page({ params }) {
  const queryClient = new QueryClient()
  await queryClient.prefetchQuery({ queryKey: ['data', params.id], queryFn: ... })
  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <PageClient entityId={params.id} />
    </HydrationBoundary>
  )
}
```

The client component's `useQuery` finds the prefetched data in cache → renders immediately.

---

## 10. Design-to-Code Workflow

```
/design-ui <feature>
  └── Creates apps/frontend/designs/<feature>.pen
  └── Produces component breakdown + S9 endpoint list

/scaffold-frontend <feature>
  └── Reads the .pen canvas design
  └── Implements in Next.js + shadcn/ui
  └── Wires TanStack Query hooks
  └── Implements loading/error/empty states
  └── Writes Vitest + Playwright tests
```

For design-only work (wireframing, UX review, spec creation), use `/design-ui`.
For full implementation from a design, use `/scaffold-frontend`.

---

## 10. Accessibility Checklist

- [ ] Color contrast ≥ 4.5:1 for normal text, ≥ 3:1 for large text
- [ ] All interactive elements reachable via keyboard (Tab, Enter, Space, Escape)
- [ ] Focus ring visible on all focusable elements (`ring-2 ring-ring ring-offset-2`)
- [ ] Images have `alt` text; decorative images have `alt=""`
- [ ] Form inputs have associated `<label>` elements (shadcn handles this via Radix)
- [ ] Error messages announced to screen readers (use `role="alert"` or `aria-live="polite"`)
- [ ] Loading states communicated (`aria-busy="true"`, `aria-label` on spinners)

**Focus-ring audit (Round-3, 2026-06-10)** — all `components/ui/` interactive primitives
show the `--ring` (yellow) focus indicator: Button, Tabs (trigger + content), Checkbox,
Switch, Input (`ring-1`), Slider thumb (`ring-1`), Select trigger (`focus:ring-1`),
Dialog close button (`focus:ring-2`). Intentional exceptions (do NOT "fix" these):
- `command.tsx` input (`outline-none`) — inside `CommandDialog` the input is the only
  focusable element and is always focused; the dialog border is the focus indicator
  (cmdk/Linear/Raycast convention). List items are highlighted via `aria-selected`,
  not DOM focus.
- `popover.tsx` / `select.tsx` content panels (`outline-none`) — non-interactive
  containers; the interactive children inside carry their own rings.

---

## 11. Open Design Decisions (Track Here)

| # | Decision | Status | Choice |
|---|----------|--------|--------|
| OQ-1 | Default "Top News" time window | Resolved | 48h |
| OQ-2 | "Top News" nav placement | Resolved | Tab within `/news` |
| OQ-3 | Impact score display | Resolved | `RelevanceBadge` + `ImpactSparkline` |
| OQ-4 | Fundamentals default metrics | Resolved | P/E, EPS, Revenue, Market Cap, Div Yield, D/E |
| OQ-5 | Fundamentals persistence | Resolved | localStorage |
| OQ-6 | LIGHT tier articles | Resolved | Show with opacity 0.6, italic source |
| OQ-7 | ImpactSparkline threshold | Resolved | ≥2 windows |
| OQ-8 | Professional table density | Resolved | `CompactTable` (text-xs, h-8 rows) for Holdings, Fundamentals, Screener; standard table for non-financial pages |
| OQ-9 | entity_id vs instrument_id | Resolved | Distinct UUIDs. `GET /v1/instruments/{id}/context` S9 composition resolves both. See ADR-F-12 in PRD-0027. |
| OQ-10 | Portfolio chart library | Resolved | recharts (donut + horizontal bar); code-split to `/portfolio` route only |
| OQ-11 | Sector heat map data | Resolved | Batch quotes for 11 SPDR sector ETFs (XLK…XLC) via `POST /v1/quotes/batch` |
| OQ-12 | Landing page hero copy | Resolved | "Bloomberg-Grade Research. Without the Bloomberg Bill." (see PRD-0027 §3 F-01) |


---

## 12. PLAN-0059 Wave F + H Primitives

### 12.1 `<DataTable>` — universal table primitive (Wave F-1)

**Path**: `components/ui/data-table/`

**Purpose**: institutional-terminal table grammar — density-aware rows, virtualization, multi-column sort, multi-select with bulk-action toolbar, sticky header, column resize, copy-as-TSV (⌘C scoped to the table), CSV export, integrated context menu.

**API**:
```tsx
<DataTable<TRow>
  columns={cols}
  data={rows}
  getRowId={(r) => r.id}                 // REQUIRED — selection state
  density="compact"                      // 22px rows, 11px text (default)
  selectable                             // adds checkbox col + bulk toolbar
  bulkActions={[{ id, label, onClick, destructive }]}
  contextMenu={[{ id, label, shortcut, onClick }]}
  onRowClick={(r) => router.push(...)}
  /* Optional CONTROLLED-mode escape hatches — pass when parent owns state
     (URL state, saved views, multi-table coordination). When omitted,
     internal state is used. */
  sorting={sorting}  onSortingChange={setSorting}
  rowSelection={selection}  onRowSelectionChange={setSelection}
  columnVisibility={visibility}  onColumnVisibilityChange={setVisibility}
/>
```

**Density tokens**: `compact` (22px row, 11px) / `default` (32px row, xs) / `comfortable` (40px row, sm).

**a11y**: `role="table"` with `aria-rowcount` + `aria-colcount`; `role="rowgroup"` wrappers around header and body; per-row `aria-rowindex`; per-cell `aria-colindex`; bulk toolbar uses `role="region"` + `role="status"` + `aria-live="polite"` so SR users hear "N selected" when appearing.

**Selection treatment**: 2px primary left-border accent + faint tint (`bg-primary/[0.04] shadow-[inset_2px_0_0_hsl(var(--primary))]`). Reads as "marked", NOT "highlighted/warning".

**Security**: TSV/CSV serialisation in `lib/format/csv-tsv.ts` defangs CWE-1236 spreadsheet formula injection. Defended in test `__tests__/data-table-utils.test.ts`. See BP-304.

**Deferred** (follow-up wave): inline edit, group-by + sticky-footer totals, saved views, frozen rows/cols, PDF/Excel exports, virtualised columns.

### 12.2 `<NumberInput>` — TradingView-style shorthand parser (Wave F-2)

**Path**: `components/ui/number-input.tsx` + `lib/format/parse-shorthand.ts`

**Shorthand grammar** (case-insensitive; round-trips through `formatShorthand`):

| Input | Parsed value |
|-------|:---:|
| `1.5m` / `2.3b` / `850k` / `1.2t` | SI multipliers (1e6 / 1e9 / 1e3 / 1e12) |
| `+2%` / `-15%` | fractional (`0.02` / `-0.15`) when `percent=true` (default) |
| `25bps` / `25bp` | fractional (`0.0025`) when `bps=true` (default) |
| `$1.5m` / `€2.3b` / `£100` / `¥50000` / `₿1` | currency-stripped |
| `(500)` / `($1.5m)` / `(-100)` | accounting parens → negative |
| `1,234.56` / `1 234.56` / `1'234'567` | locale thousands separators |
| `1e-7` / `-2.3E+5` | scientific notation (lossless round-trip) |
| `abc` / `$$$` / `1m2b` | invalid → `null` |

**Sign rule**: parens override inner sign. `(-100)` is `-100`, not `+100`. See BP-307.

**Visual feedback**: live parse-preview ghost (`≈ 1.5M`) shown to the right while focused — user sees what the parser interprets BEFORE blur. Invalid input wires `aria-invalid` + destructive border ring.

**Density**: defaults to `compact` (matches institutional 22px rows).

### 12.3 `<MultiCombobox>` — multi-select picker (Wave F-2)

**Path**: `components/ui/multi-combobox.tsx`

**Purpose**: type-ahead search + checkbox multi-select with grouped items, "+N more" trigger collapse, footer "Clear all", X-clear button.

**API**: `<MultiCombobox items={[{id, label, hint?, group?}]} selectedIds onChange placeholder ... />`

**a11y**: trigger uses `aria-haspopup="dialog"` (popover contains a search input — listbox semantics misrepresent). Clear-X is a SIBLING button (not nested inside the trigger) so the trigger remains a single tab stop.

**Performance**: items list is in-memory; cap at ~500 items per call site. For >500, use the `loadItems` async escape hatch (planned, not yet implemented).

### 12.4 `<ContextMenu>` — Radix wrapper (Wave F-3)

**Path**: `components/ui/context-menu.tsx`

**Purpose**: shadcn-style Radix wrapper for row-level right-click actions. Supports nested submenus, checkbox/radio items, shortcut display in `tabular-nums`, destructive variant.

**Density**: items at `text-[11px]` to match terminal density. `font-mono` for the entire menu so shortcut tracking aligns.

### 12.5 `<DestructiveButton>` — 3-tier confirm ladder (Wave F-4)

**Path**: `components/ui/destructive-button.tsx`

| Tier | Use for | Mechanism |
|------|---------|-----------|
| `t1` | low-risk dismiss / archive / mark-read | inline two-step (button flips to "Confirm?" with destructive ring; 4-second auto-revert) |
| `t2` | medium-risk delete row / cancel order | modal AlertDialog with Cancel / Delete |
| `t3` | high-risk delete portfolio / wipe workspace | modal with **type-to-confirm** (NFC-normalised exact string match) |

**a11y**: T1 button has `aria-live="polite"` so the label flip announces. T3 has a sr-only `role="status"` `aria-live` region announcing match/no-match.

### 12.6 `<SquarifiedTreemap>` — Bruls/Huijsen/van Wijk treemap (Wave H-3)

**Path**: `components/ui/squarified-treemap.tsx` + `lib/treemap.ts`

**Algorithm**: Bruls/Huijsen/van Wijk (2000) — packs rectangles so each cell's aspect ratio is as close to 1 as possible. O(n log n). Guarantees full-rect coverage with no gaps.

**API**:
```tsx
<SquarifiedTreemap<MyPayload>
  items={[{ id, weight, payload }]}
  renderTile={(cell) => <MyTile data={cell.item.payload} cellWidth={cell.width} />}
  gap={2}
  minWidth={48}    /* hide below this width */
  minHeight={28}   /* hide below this height */
  onTileClick={(item) => router.push(...)}        /* makes tiles focusable + keyboard-actionable */
  getTileAriaLabel={(item) => "..."}              /* SR announcement on focus */
/>
```

**Used by**: `MarketHeatmap` (sector treemap; weight = `instrument_count` until S9 returns `market_cap_weight`).

### 12.7 `<CrosshairHUD>` — chart OHLCV overlay (Wave H-2)

**Path**: `components/instrument/CrosshairHUD.tsx`

**Purpose**: Bloomberg/TradingView-style HUD — shows Date · ±change-pill · O H L C V (volume) at the hovered chart bar. Subscribes to `chart.subscribeCrosshairMove`.

**Position**: top-left of chart (`left-9 top-2`). `pointer-events-none` so the chart's own crosshair tracking is never blocked. Backdrop-blur + `bg-card/90` for legibility on dark candlesticks.

**Typography**: 11px body (institutional readability floor), 10px timestamp for hierarchy. font-mono + tabular-nums.

### 12.8 lightweight-charts v5 (Wave H-1)

**Migration** (4.x → 5.x): series creation no longer uses dedicated methods. Use the factory:

```ts
// v4 (old)
chart.addCandlestickSeries(opts)
chart.addLineSeries(opts)
chart.addHistogramSeries(opts)

// v5 (current)
import { CandlestickSeries, LineSeries, HistogramSeries } from "lightweight-charts";
chart.addSeries(CandlestickSeries, opts)
chart.addSeries(LineSeries, opts)
chart.addSeries(HistogramSeries, opts)
```

Test mocks must export the SeriesDefinition string sentinels and an `addSeries: vi.fn()` per chart instance. `subscribeCrosshairMove` / `unsubscribeCrosshairMove` are also required for the HUD subscription.

### 12.9 Density variants (Wave F-5)

**Affected**: `<Button>` and `<Input>` now accept a `density` cva variant.

| density | Button | Input |
|---------|--------|-------|
| `compact` | h-7 px-3 text-[11px] · svg size-3 | h-7 px-2 text-[11px] |
| `default` (legacy default) | h-9 px-4 py-2 | h-9 px-3 text-sm |
| `comfortable` | h-10 px-5 text-sm | h-10 px-3 text-sm |

Default kept on `default` to preserve all existing call sites; new code opts into `compact` for institutional 22px-row contexts.

---


## 13. Tailwind Config Reference

The Tailwind configuration (`tailwind.config.ts`) maps the CSS variables from `app/globals.css`
into Tailwind utility classes. Additional tokens added beyond the shadcn/ui defaults:

### 13.1 Financial Domain Tokens

These tokens have no equivalent in standard Tailwind. They are defined in `globals.css` and
consumed as Tailwind utilities:

| Utility | CSS Variable | Purpose |
|---------|-------------|---------|
| `text-positive` / `bg-positive` | `--positive` | Price up, portfolio gains (#26A69A teal) |
| `text-negative` / `bg-negative` | `--negative` | Price down, losses (#EF5350 muted red) |
| `text-warning` / `bg-warning` | `--warning` | Medium severity alerts (#F59E0B amber) |
| `bg-surface-2` | `--surface-2` | Third elevation level (alias for `--muted`, #18181B) |
| `bg-surface-3` | `--surface-3` | Fourth elevation level, borders (#27272A) |

### 13.2 Custom Animations

Defined in `tailwind.config.ts` `keyframes` / `animation` blocks:

| Class | Duration | Use |
|-------|---------|-----|
| `animate-flash-in` | 150ms ease-out | FlashOverlay entrance (urgent CRITICAL alerts) |
| `animate-skeleton-pulse` | 2s infinite | Loading skeleton shimmer (slower than Tailwind default — less distracting for finance users) |
| `animate-accordion-down` | 200ms | shadcn/ui Accordion expand |
| `animate-accordion-up` | 200ms | shadcn/ui Accordion collapse |

### 13.3 Border Radius — Terminal Sharp

All three Tailwind radius levels (`rounded-lg`, `rounded-md`, `rounded-sm`) map to the same
`--radius` value (2px). This is intentional: terminal/finance UIs use uniformly sharp corners.
The shadcn/ui default 6px / 4px / 2px consumer-app scale does not apply here.

---

## 14. Package-Level Policy

### 14.1 Whitelisted Third-Party Libraries

These are the only third-party UI/utility libraries approved for use. Any addition requires
an ADR and `pnpm audit` showing 0 CVEs:

| Library | Purpose | CVE policy |
|---------|---------|-----------|
| shadcn/ui (Radix UI primitives) | All UI components | clean |
| AG Grid Community | Data-heavy screener/portfolio tables only | clean |
| sigma.js + graphology | Knowledge graph visualisation only | clean |
| lightweight-charts | OHLCV candlestick charts | clean |
| recharts | Portfolio donut/bar charts (code-split) | clean |
| write-excel-file | Excel export (replaces SheetJS — CVEs) | clean |
| jspdf + jspdf-autotable | PDF export | clean (4.x+ only; 2.x/3.x had CVEs) |
| papaparse | CSV parsing/generation | clean |

### 14.2 Banned Patterns

| Pattern | Reason | Alternative |
|---------|--------|------------|
| `localStorage` for auth tokens | XSS risk | React state (AuthContext) |
| `sessionStorage` for auth tokens | XSS risk | React state (AuthContext) |
| Direct backend URL construction | Bypasses S9 gateway | `/api/*` rewrites |
| `Math.random()` for security values | Not cryptographically secure | `crypto.getRandomValues()` |
| Hardcoded hex colors | Breaks theme tokens | Tailwind CSS variables |
| Tailwind `slate-950` or `blue-500` | Wrong palette | Terminal Dark tokens |
| `any` TypeScript type | Loses type safety | Proper interface/type |
| `useState+useEffect` for API calls | Bypasses TanStack Query | `useQuery` / `useMutation` |
| Importing `infrastructure/` in domain | Architecture violation | Use cases / ports |

## 15. Shared Primitives (W0 — Frontend Platform Hardening)

> Added: 2026-05-19 (W0 of frontend platform hardening PRD).
> These primitives are the single canonical implementation for concerns
> that were previously scattered across 3–20+ ad-hoc call sites.

### 15.1 `<FormattedNumber>` — universal numeric display

**Path**: `components/ui/FormattedNumber.tsx`

**Purpose**: Enforces `font-mono tabular-nums slashed-zero` on every number rendered
to the user. Replaces 20+ inline numeric renders that forgot these classes.

**Props**:
| Prop | Type | Description |
|------|------|-------------|
| `value` | `number \| null \| undefined` | The value to render |
| `format` | `"currency" \| "percent" \| "ratio" \| "volume" \| "compact" \| "integer"` | Formatting mode |
| `decimals?` | `number` | Override decimal places (percent/ratio only) |
| `color?` | `"positive" \| "negative" \| "amber" \| "muted" \| "default"` | Semantic color |

**Null/undefined behaviour**: renders `—` in `text-muted-foreground/50` so missing values
are visually distinct from zero without breaking column alignment.

**Usage**:
```tsx
// Always font-mono + tabular-nums — ADR-F-15 enforced
<FormattedNumber value={price} format="currency" />
<FormattedNumber value={change} format="percent" color="positive" />
<FormattedNumber value={null} format="volume" />   {/* → "—" */}
```

**When to use vs raw number**: always use `<FormattedNumber>` for values
rendered to the user in table cells, card metrics, and badges. Raw format
functions from `lib/format.ts` are appropriate when you need a string for
an `aria-label` or `title` attribute.

### 15.2 `<SignalBadge>` — market sentiment indicator

**Path**: `components/ui/SignalBadge.tsx`

**Purpose**: Renders icon + text label for sentiment signals. Replaces icon-only
renders that failed color-blind accessibility (WCAG 1.4.1).

**Props**:
| Prop | Type | Description |
|------|------|-------------|
| `sentiment` | `"bullish" \| "bearish" \| "neutral" \| null \| undefined` | Signal direction |
| `className?` | `string` | Extra classes on the container |

**Sentiment values and rendering**:
| Sentiment | Icon | Label | Color |
|-----------|------|-------|-------|
| `bullish` | `TrendingUp` | `BULLISH` | `text-positive` |
| `bearish` | `TrendingDown` | `BEARISH` | `text-negative` |
| `neutral` | `Minus` | `NEUTRAL` | `text-muted-foreground` |
| `null` | — | nothing | — |

**Usage**:
```tsx
<SignalBadge sentiment="bullish" />   // → green TrendingUp + "BULLISH"
<SignalBadge sentiment={null} />      // → renders nothing (no DOM node)
```

**Used by**: `ArticleCard`, news page article rows, S6 signals panel.
**Replaces**: inline icon renders at `news/page.tsx:256-263` and `ArticleCard.tsx:102-110`.

### 15.3 Hooks

#### `useCopyToClipboard`

**Path**: `lib/hooks/useCopyToClipboard.ts`

Returns `{ copy: (text: string) => Promise<void>; copied: boolean }`.

Prefers the Clipboard API; falls back to `execCommand("copy")` for older WebKit
and in-app browsers. `copied` stays `true` for 2000ms after a successful write.

**Replaces**: duplicate clipboard logic in `AliasPill`, `MarkdownContent`, `DataTable`.

#### `useKeyboardShortcuts`

**Path**: `lib/hooks/useKeyboardShortcuts.ts`

```ts
useKeyboardShortcuts({
  "ctrl+k": () => openSearch(),
  "cmd+k":  () => openSearch(),  // both platform variants
  "escape": () => closeModal(),
});
```

Key format: `"modifier+key"` (lowercase). Modifiers: `ctrl`, `cmd`, `shift`, `alt`.
Does NOT fire inside `input`, `textarea`, `select`, or `contenteditable` elements.
Does NOT handle sequence chords (g+d) — use `react-hotkeys-hook` for those.

**Replaces**: inline `keydown` listeners in `GlobalSearch`, `QuickEditPopover`, `FlashOverlay`.

#### `useFormattedTimestamp`

**Path**: `lib/hooks/useFormattedTimestamp.ts`

```ts
const label = useFormattedTimestamp("2026-05-19T14:32:00Z", "relative"); // "2h ago"
const label = useFormattedTimestamp(someDate, "absolute"); // "May 19, 2026, 14:32"
const label = useFormattedTimestamp(null, "short"); // "—"
```

Format modes (per DESIGN_SYSTEM §6.4):
- `"relative"` — "just now", "Nm ago", "Nh ago", "Nd ago", "Mon DD" (default)
- `"absolute"` — "May 19, 2026, 14:32" (detail view headers)
- `"short"` — "May 19, 2026" (table rows)

Returns `"—"` for null/undefined/invalid input.

### 15.4 `lib/sse-parser.ts` — SSE line parser

**Path**: `lib/sse-parser.ts`

Shared parser for `text/event-stream` line-by-line parsing. Extracted to prevent
protocol drift between `useChatStream` and `ActionConfirmModal` (MED-013).

```ts
import { parseSSELine } from "@/lib/sse-parser";
import type { SSEEvent } from "@/lib/sse-parser";

const event = parseSSELine("event: tool_call");
// → { type: "tool_call", data: "tool_call" }

const event = parseSSELine("data: {\"text\": \"hello\"}");
// → { type: "message", data: "{\"text\": \"hello\"}" }

parseSSELine("")          // → null (blank line — event block terminator)
parseSSELine(": ping")    // → null (keep-alive comment)
parseSSELine("no-colon")  // → null (bare field name, ignored)
```

### 15.5 `DEFAULT_STALE` — canonical staleTime map

**Path**: `lib/api/_client.ts` (exported alongside `apiFetch`)

Single source of truth for per-domain TanStack Query staleTime values (HIGH-018, FR-8.4).
Import from `@/lib/api/_client` and use in `useQuery` calls.

| Key | Value (ms) | Rationale |
|-----|-----------|-----------|
| `news` | 300,000 (5 min) | Articles update frequently, not per-second |
| `fundamentals` | 3,600,000 (1 hr) | Quarterly data; rarely changes intra-day |
| `entityGraph` | 60,000 (1 min) | KG enrichment runs continuously |
| `quotes` | 15,000 (15 sec) | Matches S3 Valkey quote cache TTL |
| `screener` | 30,000 (30 sec) | Filter results shift as prices move |
| `screenerFields` | 21,600,000 (6 hr) | Field definitions almost never change |
| `portfolio` | 60,000 (1 min) | Updated on every transaction |
| `alerts` | 15,000 (15 sec) | Alert status must be nearly real-time |

```ts
import { DEFAULT_STALE } from "@/lib/api/_client";
useQuery({ queryKey: qk.news.top(), queryFn: ..., staleTime: DEFAULT_STALE.news });
```

### 15.6 `--topbar-height` CSS variable

Defined in `app/globals.css` as `--topbar-height: 44px` (`:root` and `.dark`).

Reference via Tailwind arbitrary value: `h-[var(--topbar-height)]` or in plain CSS:
```css
height: var(--topbar-height);
```

Used by the `(app)/layout.tsx` shell to size the top chrome. Components that
position content relative to the topbar (e.g. `calc(100vh - 36px)` in dashboard
page) should use this variable instead of a hardcoded pixel value (MED-002).

### 15.7 Entity-graph node type tokens

Defined in `app/globals.css` (`:root` and `.dark`). Reference as:
```js
`hsl(var(--entity-type-person-fill))`   // deep teal — person nodes
`hsl(var(--entity-type-event-fill))`    // deep amber — event nodes
`hsl(var(--entity-type-topic-fill))`    // deep blue — topic nodes
`hsl(var(--entity-type-default-fill))`  // neutral grey — unknown/default
// Stroke variants: --entity-type-{person,event,topic,default}-stroke
```

Replaces hardcoded hex constants in `EntityGraphPanel.tsx:11-14` (MED-018, DS-004).

### 15.8 `DENSITY_CLASSES` — visual density reference

**Path**: `lib/ui-constants.ts`

Canonical Tailwind class strings for every UI surface density level (DS-012, FR-10.6).

| Surface | Class string | Height |
|---------|-------------|--------|
| `tableRow` | `h-[22px] px-2 py-0.5 text-[11px]` | 22px |
| `articleRow` | `px-3 py-1.5 text-[11px]` | 28px (py-1.5) |
| `tabBar` | `h-8 px-3 text-[11px]` | 32px |
| `headerTopbar` | `px-3 text-[12px]` | via `--topbar-height` |
| `banner` | `h-6 px-2 text-[10px] rounded-[2px]` | 24px |
| `sidebarItem` | `px-2 py-1.5 text-[11px] rounded-[2px]` | 28px |
| `cardDefault` | `p-3 text-[12px] rounded-[2px]` | n/a |
| `buttonDefault` | `h-9 px-3 text-[12px] rounded-[2px]` | 36px |
| `buttonCompact` | `h-7 px-2 text-[11px] rounded-[2px]` | 28px |
| `badge` | `px-1.5 py-0.5 text-[10px] rounded-full` | n/a |

### 15.9 Typography exception: `text-[9px]`

> **Amended ADR-F-15** (OQ-003 resolution, 2026-05-19):

`text-[9px]` is permitted **ONLY** for non-data secondary metadata labels such as:
- Timestamps in ultra-compact list items
- Counts (e.g. "3 results")
- Category labels in chart legends and graph control hints

**Financial data values** (prices, percentages, ratios, volumes) **MUST** use
`text-[10px]` minimum. Using 9px for a price or P&L percentage is a typography
error — even in the most compact contexts.

Chart axis tick labels (x/y) were already permitted at 9px (§3.2 exception table
added 2026-04-23). This amendment extends the exception to the categories listed
above while reaffirming that financial data values are excluded.

> **Note on `--topbar-height` in globals.css vs DESIGN_SYSTEM.md §2.1**:
> The CSS file currently has `44px` (from an earlier wave) while DESIGN_SYSTEM.md §2.1
> states `36px` (PRD-0031). This discrepancy should be resolved in W3 (Dashboard fixes).
> W0 adds the chart/entity tokens without touching the topbar value to avoid
> unintended layout breakage.

### 15.10 AG Grid 22px row-height adoption path (Round-2 enhancement sprint)

**Path**: `components/ui/ag-grid/AgGridBase.tsx`

`AgGridBase` accepts optional `rowHeight` / `headerHeight` props (both default
**28** — the previously hardcoded value), so grids can adopt the
`--data-row-height: 22px` token (§2.1, PRD-0031) per surface:

```tsx
<AgGridBase rowData={rows} columnDefs={cols} rowHeight={22} headerHeight={22} />
```

Rules of adoption:

1. **Opt-in per call site** — the default stays 28, so no grid reflows until
   its owning surface adopts deliberately. Audit row content first: cell
   renderers with sparklines, badges, or 2-line layouts may clip at 22px.
2. **Numbers, not the CSS var** — AG Grid virtualises rows with JS math and
   needs a concrete px value at construction; it cannot read
   `var(--data-row-height)`. The token's value (22) is mirrored in the prop.
   If PRD-0031 ever changes the token, grep `rowHeight={22}` call sites.
3. **Header matches rows** — pass `headerHeight={22}` together with
   `rowHeight={22}` (Bloomberg keeps them equal; a 28px header over 22px rows
   reads as misalignment).

Prop passthrough + defaults are pinned by
`components/ui/ag-grid/__tests__/AgGridBase.test.tsx`.

> **Round-4 note — reconciling the screener's 20px exception with this 22px
> path.** The screener grid runs `rowHeight={20}` / `headerHeight={20}` —
> tighter than the `--data-row-height: 22px` token — as a deliberate
> PRD-0089 Wave I-A density decision, **locked by the T-IA-14 architecture
> guard** (`__tests__/architecture/screener-row-height.test.ts` +
> `__tests__/screener-density.test.tsx`; the skeleton pitch is pinned in
> `components/screener/__tests__/ScreenerTableSkeleton.test.tsx`). Its cell
> renderers are tuned to that pitch (18px HeatCell pills, RowHoverToolbar
> sizing), so "migrating the screener to 22" is a regression, not a cleanup —
> the guard tests will fail any such attempt by design. Precedence when
> adopting density on a grid: **(1)** a surface-specific guarded value
> (screener 20px) wins; **(2)** otherwise adopt the 22px token via the rules
> above; **(3)** the 28px default remains for grids whose row content hasn't
> been audited for clipping. The 22px token is the generic adoption target;
> T-IA-14 is the only sanctioned tighter exception — adding another requires
> its own architecture guard + an entry here.

### 15.11 Sentiment color tokens — canonical consumption (Round-2 decision)

**Decision (Round-2 enhancement sprint)**: the platform does **NOT** define
`--color-positive` / `--color-negative` / `--color-warning` CSS variables, and
they must never be referenced. That `--color-*` prefix is Tailwind **v4**'s
`@theme` convention; we are on Tailwind v3 with HSL-triplet tokens
(`--positive: 150 100% 41%`) consumed through `tailwind.config.ts` mappings.
Referencing an undefined variable (`text-[color:var(--color-positive)]`)
compiles silently and **paints nothing** — the no-paint bug class that hit the
portfolio sparkline (R1 sprint) and the instrument AI-brief chips/peer table
(fixed Round 2). Option (b) — fix usages — was chosen over option (a) —
aliasing — to avoid a second, parallel full-color token convention.

Canonical consumption per context:

| Context | Use | Example |
|---------|-----|---------|
| Text / background / border in JSX | Semantic Tailwind utilities | `text-positive`, `text-negative`, `text-warning`, `bg-positive/10` |
| Canvas / SVG / chart JS constants | `hsl(var(--chart-*))` | `hsl(var(--chart-positive))` (sparklines, OHLCV) |
| Raw CSS files | `hsl(var(--positive))` | ag-grid-theme.css overrides |

A naming-guard comment now sits next to the financial-domain tokens in
`app/globals.css`. The lint rule banning raw `text-green-*`-style classes
(`.eslintrc.json`, PLAN-0071 P1-4) already points at the same utilities.

### 15.12 `EmptyState` primitive API (Round-2 enhancement sprint)

**Path**: `components/primitives/EmptyState.tsx`
**Copy registry**: `lib/copy/empty-states.ts`

```tsx
<EmptyState
  condition="empty-no-data"          // loading | empty-cold-start | empty-no-data | error | permission | coming-soon
  copyKey="instrument.no-articles"   // resolves via lib/copy/empty-states.ts; falls back to generic.<condition>
  icon={Newspaper}                   // NEW (optional) — lucide COMPONENT, rendered muted 16px above the title
  action={<Button onClick={retry}>Retry</Button>}  // NEW (optional) — interactive CTA slot
/>
```

- **`icon`** — pass the lucide component (not an element); the primitive owns
  size/color (`size-4 text-muted-foreground/60`, strokeWidth 1.5, aria-hidden)
  so every surface renders identically. Matches the treatment of
  `components/instrument/shared/EmptyState.tsx`, which becomes a thin wrapper
  (or is deleted) in the Round-3 consolidation.
- **`action`** — ReactNode CTA slot below the body; supports real onClick
  buttons (retry/regenerate), not just href Links. Supersedes the legacy
  `cta` prop (kept, `@deprecated`); when both are passed, `action` wins —
  single-slot invariant, never two stacked CTAs.
- **Copy keys** — Round 2 reserved the `instrument.*` keys
  (`no-articles`, `no-contradictions`, `graph-timeout`,
  `graph-no-filter-matches`, `no-connections`, `no-entity-context`) mirroring
  the strings hardcoded in the instrument intelligence tab, so the Round-3
  call-site migration is a mechanical swap.
- **Round-3 deferrals**: (1) migrate `components/instrument/shared/EmptyState.tsx`
  call sites (NewsColumn, GraphColumn, ContextPanel, ContradictionsBlock) onto
  this primitive; (2) `components/ui/dashboard-empty-state.tsx`
  (DashboardEmptyState) consolidation — skipped in Round 2 because
  `components/dashboard` was owned by the dashboard surface agent.

API contracts pinned by `components/primitives/__tests__/EmptyState.test.tsx`.
