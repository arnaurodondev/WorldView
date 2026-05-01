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
| `TopBar` | `components/shell/TopBar.tsx` | Logo + GlobalSearch + IndexTicker + alerts badge + avatar |
| `GlobalSearch` | `components/shell/GlobalSearch.tsx` | ⌘K command palette overlay (cmdk) |
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

  if (isLoading) return <DataPanelSkeleton />           // skeleton shimmer
  if (error)    return <ErrorCard message="..." onRetry={refetch} /> // error + retry
  if (!data)    return <EmptyState message="..." />     // empty with guidance

  return <DataPanelContent data={data} />
}
```

**Never render a blank panel.** Every state must communicate something to the user.

### 6.2 Skeleton Pattern

Skeletons must match the shape of the loaded content:
```tsx
// Use shadcn Skeleton — same layout as content, grey shimmer
function DataTableSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 5 }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full rounded" />
      ))}
    </div>
  )
}
```

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

```tsx
function LivePriceBadge({ price, updatedAt }: { price: string; updatedAt: Date }) {
  const ageMs = Date.now() - updatedAt.getTime()
  const dotColor = ageMs < 30_000 ? 'bg-green-500 animate-pulse'
                 : ageMs < 300_000 ? 'bg-amber-500'
                 : 'bg-red-500'
  return (
    <span className="flex items-center gap-1.5">
      <span className={cn('inline-block w-1.5 h-1.5 rounded-full', dotColor)} />
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

### 6.12 Keyboard Navigation (NEW)

Global shortcut registration via `react-hotkeys-hook` in root layout:

| Shortcut | Action | Notes |
|----------|--------|-------|
| `g d` | Navigate /dashboard | Sequence: press g, then d within 500ms |
| `g w` | Navigate /workspace | |
| `g c` | Navigate /companies | |
| `g p` | Navigate /portfolio | |
| `g n` | Navigate /news | |
| `g s` | Navigate /screener | |
| `g h` | Navigate /chat | |
| `Cmd+K` / `Ctrl+K` | Open CommandPalette | |
| `Escape` | Close active modal/overlay | |

Display in AppSidebar bottom strip: `g+d Dashboard  g+w Workspace  ⌘K Search` (text-[10px] muted).

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

## 9. TanStack Query Conventions

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
