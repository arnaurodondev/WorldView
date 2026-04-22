# Worldview Design System

> **Single source of truth** for all frontend design decisions: tokens, components, patterns, and UX conventions.
> **Last updated**: 2026-04-19 (v2.2 — Bloomberg Dark palette overhaul: #0A0E14 bg + amber/gold accent + warm parchment text)
>
> Referenced by: `/design-ui` skill, `/scaffold-frontend` skill, `ux-ui-designer` agent, `frontend-engineer` agent.
>
> **CONFIRMED**: "Bloomberg Dark" direction — `#0A0E14` bg + IBM Plex + amber/gold accent (#E8A317) + teal-green positive.
> See `docs/ui/competitive-design-research.md` for full competitor analysis.

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

## 2. Color Palette (Dark Theme — "Bloomberg Dark")

> **Bloomberg Dark confirmed. Do NOT revert to slate-950/blue-500 defaults.**
> See PRD-0027 §1.4 for prior direction history and rationale.
> Reference: `docs/ui/competitive-design-research.md`

All colors are expressed as CSS custom properties. **Never use hardcoded hex values in components.**

### 2.1 CSS Variables (`app/globals.css`) — Bloomberg Dark

```css
:root.dark {
  /* ── Backgrounds ──────────────────────────────────────────────────── */
  --background:        210 38% 6%;       /* #0A0E14 — Bloomberg-style deep background */
  --card:              212 31% 9%;       /* #111820 — panel/card backgrounds */
  --muted:             215 26% 14%;      /* #1A2030 — elevated surfaces, hover states */
  --popover:           210 38% 6%;       /* #0A0E14 — same as --background */
  --surface-2:         215 26% 14%;      /* #1A2030 — alias for muted (explicit surface step) */
  --surface-3:         210 22% 19%;      /* #243040 — third elevation level */

  /* ── Text ──────────────────────────────────────────────────────────── */
  --foreground:        36 14% 85%;       /* #E0DDD4 — Bloomberg warm-white text */
  --card-foreground:   36 14% 85%;       /* #E0DDD4 */
  --muted-foreground:  215 8% 47%;       /* #6B7585 — labels, timestamps, axis captions */

  /* ── Interactive ───────────────────────────────────────────────────── */
  --primary:           40 83% 50%;       /* #E8A317 — amber/gold accent */
  --primary-foreground: 210 38% 6%;      /* #0A0E14 — dark text on gold button */

  /* ── Structural ────────────────────────────────────────────────────── */
  --border:            210 22% 19%;      /* #243040 — dividers */
  --input:             210 22% 19%;      /* #243040 */
  --ring:              40 83% 50%;       /* #E8A317 — focus rings match accent */
  --accent:            215 26% 14%;      /* #1A2030 */
  --destructive:       0 63% 62%;        /* #EF5350 — destructive actions */
  --destructive-foreground: 36 14% 85%;  /* #E0DDD4 */

  /* ── Financial domain ──────────────────────────────────────────────── */
  --positive:          174 42% 40%;      /* #26A69A — teal-green (price up) */
  --negative:          0 63% 62%;        /* #EF5350 — muted red (price down) */
  --warning:           38 92% 50%;       /* #F59E0B — amber-500 alerts/warnings */
}
```

### 2.1a Hex Quick-Reference (for pencil.dev canvas and design tools)

| Token | Hex | Description |
|-------|-----|-------------|
| Page background | `#0A0E14` | Bloomberg-style deep background |
| Card/panel | `#111820` | Panel/card backgrounds |
| Elevated/hover (surface-2) | `#1A2030` | Elevated surfaces, hover states |
| Surface-3 | `#243040` | Third elevation level, borders |
| Border | `#243040` | Dividers, table borders |
| Primary text | `#E0DDD4` | Warm parchment white |
| Secondary text | `#6B7585` | Labels, timestamps, axis captions |
| Accent (gold) | `#E8A317` | Bloomberg amber/gold accent |
| Positive (teal) | `#26A69A` | Price up, portfolio gain |
| Negative (red) | `#EF5350` | Price down, loss |
| Warning (amber) | `#F59E0B` | Medium severity alerts |
| Positive bg (heat) | `#0A2420` | Dark teal tint for HeatCell positive |
| Negative bg (heat) | `#300E12` | Dark red tint for HeatCell negative |

### 2.2 Semantic Usage

| Context | Variable | Example | Hex (Bloomberg Dark) |
|---------|----------|---------|----------------------|
| Page background | `bg-background` | `<body>`, `<main>` | `#0A0E14` |
| Card / panel | `bg-card` | shadcn `<Card>`, sidebar panels | `#111820` |
| Elevated panel | `bg-muted` | nested cards, hover states | `#1A2030` |
| Primary headings | `text-foreground` | page titles, values | `#E0DDD4` |
| Labels, captions | `text-muted-foreground` | "P/E Ratio", timestamps | `#6B7585` |
| Price up | `text-positive` | `+2.34%` | `#26A69A` (teal) |
| Price down | `text-negative` | `-1.12%` | `#EF5350` |
| CTA buttons | `bg-primary text-primary-foreground` | "Buy", "Confirm" | `#E8A317` bg |
| Borders | `border-border` | `<Separator>`, table borders | `#243040` |
| Active nav item | `bg-primary/10 text-primary` | sidebar active link | amber/gold tint |
| Ticker badge | `bg-primary/20 text-primary font-mono` | "AAPL" badge | amber/gold tint |

### 2.3 Background Elevation Hierarchy

```
Page (--background / #0A0E14)
  └── Sidebar, panels (--card / #111820)
        └── Nested cards, hover rows (--muted, --surface-2 / #1A2030)
              └── Input fields, tooltips, borders (--surface-3 / #243040)
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
| **Numeric value (table)** | **IBM Plex Mono** | `font-mono text-xs tabular-nums text-right` | 12px/400 |
| **Percentage change** | **IBM Plex Mono** | `font-mono text-sm tabular-nums` | 14px/400 |
| **Terminal/chat text** | **IBM Plex Mono** | `font-mono text-xs leading-relaxed` | 12px/400 |

**Critical rule (ADR-F-15)**: Every number displayed to the user — prices, percentages, quantities,
EPS values, volumes, dates in data tables — MUST use `font-mono tabular-nums`. This is non-negotiable.
Mixing sans and mono within a number column is a typography error.

**tracking-tight** on headings: IBM Plex Sans is slightly wider than Inter. The `-tight` tracking
compensates and prevents headings from appearing loose at small sizes.

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
| `OHLCVChart` | `components/charts/OHLCVChart.tsx` | lightweight-charts candlestick/line chart with MA50/MA200/Volume overlays |
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
| `52WeekRangeBar` | `components/instrument/52WeekRangeBar.tsx` | Visual slider showing current price vs 52w range |
| `TechnicalSnapshot` | `components/instrument/TechnicalSnapshot.tsx` | Strip: Beta, MA50↑↓, MA200↑↓, RSI, Short Interest |

### 5.3 Layout Components

| Component | File path | Notes |
|-----------|-----------|-------|
| `AppSidebar` | `components/layout/AppSidebar.tsx` | 220px fixed sidebar, nav links + keyboard hint strip |
| `TopBar` | `components/layout/TopBar.tsx` | Page title + ⌘K hint + WS status dot + alerts badge + avatar |

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
