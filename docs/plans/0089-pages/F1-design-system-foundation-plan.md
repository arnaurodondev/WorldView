---
id: PRD-0089-F1
title: Design System Foundation
prd: PRD-0089
order: F1 (foundation — runs before any per-page wave)
status: ready-to-execute
created: 2026-05-20
platform_state: pre-production (no_backfill: true)
goal: lock the Bloomberg-grade visual contract every subsequent page consumes
---

# F1 — Design System Foundation (PRD-0089)

> **One sentence.** Replace every soft, rounded, generously-spaced surface
> with sharp-cornered, dense, terminal-grade primitives so that a hedge-fund
> PM dropped onto any Worldview page is muscle-memory-equivalent to
> Bloomberg, Finviz, Refinitiv, IBKR TWS, or Koyfin.

## 1. Bloomberg-grade visual checklist (acceptance signals)

Every primitive and every page that consumes F1 must satisfy:

| Test | How to verify |
|------|---------------|
| **Sharp corners everywhere** | `grep -r "rounded-" apps/worldview-web/{components,app,features,contexts}` returns ≤ 5 matches, all `rounded-full` (dots/avatars only) |
| **Numbers are mono + tabular** | Every `<span>` containing a price/qty/%/timestamp has `font-mono tabular-nums` (architecture test extension) |
| **Body 11px, tables 10.5px** | No `text-sm` (14px) or `text-base` (16px) appears in any rendered data row. Hero/page-primary numbers = 14px only |
| **Row height 20px (18px hyper-dense)** | `data-table-grid` containers honour `[--row-h:20px]` or `[18px]` — never `h-9` (36px) or `py-3` (24px) |
| **Cell padding 6px** | `px-2` (8px) banned inside `data-table-grid`; replace with `px-1.5` (6px) |
| **Zero shadows** | `grep -r "shadow-" apps/worldview-web/components/` returns 0 — Tailwind shadow utilities removed from config |
| **Borders visible at panel + cell level** | Two new tokens: `--border-strong` (#37373B) for cell grids, `--border-subtle` (#1E1E22) for row dividers |
| **Trend-tinted sparklines** | Sparkline colour = `text-positive` / `text-negative` / `text-muted-foreground` per data direction, NOT primary yellow |
| **Focus ring is 3-tier** | T1 hairline inset for table rows, T2 ring-1 for inputs, T3 ring-2 ring-offset-2 for chrome CTAs |
| **Animation lives only in 4 places** | Spinners + skeleton + chat-token-stream + popover-mount (≤200ms). No layout-shifting transitions |
| **Density floor enforced** | Playwright spec: each page surfaces ≥ its tier floor (Header 40 / Quote 100 / Intelligence 100 / Financials 150 / Dashboard 200 / Portfolio 250 / Screener 240) |

If any row above fails post-merge, the F1 wave is incomplete.

## 2. Token specification — every CSS variable + Tailwind utility

### 2.1 Color tokens (globals.css — diff from current)

The Terminal Dark palette is **kept**; only two **additions** for cell-grid
contrast, and one removal for shadow-related artefacts.

| Var | Current | F1 | Reason |
|-----|---------|-----|--------|
| `--background` | `240 10% 4%` (#09090B) | unchanged | Canvas |
| `--card` | `270 2% 7%` (#111113) | unchanged | Panel surface |
| `--muted` | `240 4% 11%` (#18181B) | unchanged | Hover background |
| `--popover` | `240 10% 4%` | unchanged | Same as bg |
| `--accent` | `240 4% 11%` | unchanged | Subtle hover |
| `--surface-2` | `240 4% 11%` | unchanged | Alias |
| `--surface-3` | `240 4% 16%` (#27272A) | unchanged | 3rd elevation |
| `--foreground` | `240 5% 90%` (#E4E4E7) | unchanged | Primary text |
| `--muted-foreground` | `240 4% 55%` (#83838A) | unchanged | Secondary text |
| `--primary` | `48 100% 52%` (#FFD60A) | unchanged | Bloomberg yellow |
| `--primary-foreground` | `0 0% 0%` (#000) | unchanged | Yellow CTA text |
| `--border` | `240 4% 16%` (#27272A) | unchanged | Panel borders |
| `--input` | `240 4% 16%` | unchanged | Input borders |
| `--ring` | `48 100% 52%` (yellow) | unchanged | Focus rings |
| `--destructive` | `0 84% 60%` (#EF4444) | unchanged | Delete action |
| `--positive` | (existing) #00D26A | unchanged | Price up / gain |
| `--negative` | (existing) #FF3B5C | unchanged | Price down / loss |
| `--warning` | (existing) #FFB000 | unchanged | Caution / amber |
| `--accent-ai` | (existing) #A855F7 | unchanged | AI-content rail (per DISCUSS-12 brief left-rail; renamed `--accent-amber` in some FU docs — confirm reference is `--accent-ai`) |
| **`--border-strong`** | — | `240 4% 22%` (#37373B) | **NEW** — cell-grid lines inside `data-table-grid` |
| **`--border-subtle`** | — | `240 4% 13%` (#1E1E22) | **NEW** — row dividers inside `data-table-grid` |
| `--radius` | `0.125rem` (2px) | **`0`** | Sharp corners globally |
| `--row-h` | — | **`20px`** (default), **`18px`** (hyper-dense) | **NEW** — table row-height token |
| `--cell-px` | — | **`6px`** | **NEW** — cell horizontal padding token |

CSS additions (full block — append after existing `:root.dark` declarations,
before `@media` queries):

```css
@layer base {
  :root.dark, :root {
    /* PRD-0089 F1 additions */
    --border-strong: 240 4% 22%;       /* #37373B — for data-table-grid cell lines */
    --border-subtle: 240 4% 13%;       /* #1E1E22 — for row dividers inside grids */
    --row-h: 20px;                     /* default tabular row height */
    --row-h-dense: 18px;               /* hyper-dense (transactions, screener results) */
    --cell-px: 6px;                    /* horizontal cell padding */
  }

  /* WHY override: terminal aesthetic = sharp corners. Bloomberg HELP overlays,
     IBKR TWS modal frames, Eikon panels — all 0px radius. The previous 2px
     micro-radius was a holdover from the consumer fintech pattern. */
  :root, :root.dark { --radius: 0; }

  /* Opt-in dense-grid wrapper (FU-5.5).
     Apply via `<div data-table-grid>` on the 7 v1 surfaces:
     Screener, Holdings, Tx Ledger, Financials FlatMetricsGrid, Watchlist,
     Workspace data panels, Peer Comparison. */
  [data-table-grid] {
    --row-h: 20px;
    --cell-px: 6px;
  }
  [data-table-grid="dense"] { --row-h: 18px; }
  [data-table-grid] [role="row"] {
    height: var(--row-h);
    border-bottom: 1px solid hsl(var(--border-subtle));
  }
  [data-table-grid] [role="cell"], [data-table-grid] [role="columnheader"] {
    padding-left: var(--cell-px);
    padding-right: var(--cell-px);
    border-right: 1px solid hsl(var(--border-subtle));
  }
  [data-table-grid] [role="row"]:last-child { border-bottom: none; }
  [data-table-grid] [role="cell"]:last-child,
  [data-table-grid] [role="columnheader"]:last-child { border-right: none; }
}
```

### 2.2 Tailwind utility tokens (tailwind.config.ts diff)

```diff
@@ borderRadius @@
- borderRadius: {
-   lg: "var(--radius)",   /* was 2px */
-   md: "var(--radius)",
-   sm: "var(--radius)",
- },
+ borderRadius: {
+   /* PRD-0089 F1: only 0 (default) and full (dots/avatars) survive.
+      Any rounded-md/lg/xl/sm/2xl class is an architectural error and
+      blocked by the extended no-off-palette-colors test. */
+   none: "0",
+   full: "9999px",
+ },

@@ colors @@ (within extend.colors)
  border: "hsl(var(--border))",
+ "border-strong": "hsl(var(--border-strong))",
+ "border-subtle": "hsl(var(--border-subtle))",

@@ boxShadow @@
+ /* PRD-0089 F1: zero shadows on Terminal Dark.
+    Map every Tailwind shadow alias to `none` so `shadow-sm`, `shadow-md`,
+    `shadow-lg`, `shadow-xl`, `shadow-2xl`, `shadow-inner` all render no-op.
+    Components still pass type-check (the class compiles) but produce no
+    visible elevation. Eliminates the dead-code documentation lie of
+    "shadows are reset in globals.css". */
+ boxShadow: {
+   none: "none",
+   sm: "none",
+   DEFAULT: "none",
+   md: "none",
+   lg: "none",
+   xl: "none",
+   "2xl": "none",
+   inner: "none",
+ },

@@ animation @@ (existing)
  /* Keep — these are Tier-3 indicators per DISCUSS-4: */
  "accordion-down": "accordion-down 0.2s ease-out",
  "accordion-up": "accordion-up 0.2s ease-out",
  "flash-in": "flash-in 0.15s ease-out",
  "skeleton-pulse": "skeleton-pulse 2s ease-in-out infinite",
+ /* PRD-0089 F1: Tier-1 affordance transitions (≤100ms, color-only).
+    Used by row-hover, button-hover, focus-ring intro. */
+ "color-fast": "150ms",
+ "color-slow": "200ms",

@@ transitionProperty (NEW — currently relies on Tailwind defaults) @@
+ transitionProperty: {
+   /* PRD-0089 F1 NFR-6 enforcement:
+      Components MUST use these named tokens, not `transition-all`
+      (banned by arch-test). Tier-1 = color/border-color only. */
+   "color-only": "color, background-color, border-color, fill, stroke",
+   "color-and-opacity": "color, background-color, border-color, opacity",
+ },
+ transitionDuration: {
+   "75": "75ms",
+   "100": "100ms",   /* Tier-1 ceiling */
+   "150": "150ms",
+   "200": "200ms",   /* Tier-2 ceiling */
+ },
```

### 2.3 Typography scale (frozen — confirmed by FU-5.1)

| Token | px | Use | Examples |
|-------|---:|-----|----------|
| `text-[9px]` | 9 | Tertiary — sub-cell labels, dot legends | "POL", "MA50" indicator chips |
| `text-[10px]` | 10 | Column / group headers (uppercase, tracking-wide) | "STATISTICS", "VALUATION" |
| `text-[10.5px]` | 10.5 | **Body inside `data-table-grid`** | Holdings rows, screener rows, MetricsTable cells |
| `text-[11px]` | 11 | **Body default — narrative + UI** | Article headlines, brief bullets, panel descriptions |
| `text-[12px]` | 12 | Section titles, mid-emphasis labels | "Income Statement", "Top Movers" |
| `text-[13px]` | 13 | Page chrome — ticker, primary price, tab labels | "AAPL", "$297.66" in header |
| `text-[14px]` | 14 | **Hero / page-primary numbers ONLY** | Portfolio total value, NLV, AUM |

Banned: `text-base` (16px), `text-sm` (14px) inside `data-table-grid`,
`text-lg` / `text-xl` / `text-2xl` everywhere (page primaries are 14px,
even hero — Bloomberg has no consumer-app heroes).

### 2.4 Spacing scale (frozen)

| Token | px | Use |
|-------|---:|-----|
| `gap-0` / `p-0` | 0 | Adjacent panels (1px hairline divider via `border-r`/`border-b`) |
| `gap-1` / `p-1` | 4 | Inside dense table rows (between mini-bar segments) |
| `gap-1.5` / `p-1.5` | **6** | **Cell padding** (replaces `px-2`) |
| `gap-2` / `p-2` | 8 | Between section blocks |
| `gap-3` / `p-3` | 12 | Horizontal tab-content edges, panel inner padding |
| `gap-4` / `p-4` | 16 | **Maximum** allowed inside a panel; banned for table cells |

Banned: `gap-6` / `gap-8` / `p-6` / `p-8` — too generous; rejected.

### 2.5 Row-height scale (new — table primitive)

| Token | px | Use |
|-------|---:|-----|
| `h-[16px]` | 16 | Mini sub-row (e.g. sentiment dot strip inside an article row) |
| `h-[18px]` | 18 | Hyper-dense (transactions ledger, screener results) |
| `h-[20px]` | **20** | **Default `data-table-grid` row** |
| `h-[22px]` | 22 | Legacy (some PLAN-0090 rows; flip to 20 in PR-F) |
| `h-[28px]` | 28 | Section headers inside tables |
| `h-[32px]` | 32 | TopBar height |
| `h-[36px]` | 36 | InstrumentHeader (sticky) |

Banned: `h-[40px]`, `h-9` (36 — replace with explicit `h-[36px]`), `h-10`, `h-12`.

### 2.6 Animation tier policy (DISCUSS-4 codified)

| Tier | Use | Allowed properties | Max duration |
|------|-----|-------------------|---------------|
| **T0 — Data** | Numeric values, chart bars, sparkline data, table row positions, layout-shift props (width/height/max-h) | **none** | **0ms** |
| **T1 — Affordance** | Hover / focus on rows, buttons, links | `color`, `background-color`, `border-color`, `fill`, `stroke` | **100ms** |
| **T2 — Chrome state** | Popovers, dropdowns, accordions, modals open/close | `opacity`, `transform: translate/scale`, `clip-path` | **200ms** |
| **T3 — Indicator** | Spinners, skeleton-pulse, chat-token-stream, brief-generate-progress, flash-in alerts | any | unbounded |

Enforced by arch-test extension `tests/architecture/animation-policy.test.ts`.

### 2.7 Z-index scale (clarified — currently ad-hoc)

| Token | Value | Use |
|-------|------:|-----|
| `z-0` | 0 | Default |
| `z-10` | 10 | Sticky headers (InstrumentHeader, tab bar) |
| `z-20` | 20 | Sidebar / global shell |
| `z-30` | 30 | TopBar |
| `z-40` | 40 | Popovers, tooltips, dropdowns |
| `z-50` | 50 | Modals, command palette |
| `z-60` | 60 | Toasts (Sonner) |
| `z-[100]` | 100 | Emergency overlays (auth re-prompt) |

Add as documentation in DESIGN_SYSTEM.md; no Tailwind config change needed.

## 3. Shared primitive specification

### 3.1 Existing — PROMOTE and harmonise

These already live under `apps/worldview-web/components/instrument/shared/`
from PLAN-0090. Move to `apps/worldview-web/components/primitives/` (new
folder) so they're discoverable cross-page, and update every import site.

| Current path | New path | LOC change |
|--------------|----------|-----------:|
| `components/instrument/shared/MetricLabel.tsx` | `components/primitives/MetricLabel.tsx` | path only |
| `components/instrument/shared/MetricValue.tsx` | `components/primitives/MetricValue.tsx` | path only |
| `components/instrument/shared/SectionDivider.tsx` | `components/primitives/SectionDivider.tsx` | path + use `border-border-subtle` instead of `border-border` |
| `components/instrument/shared/DataTimestamp.tsx` | `components/primitives/DataTimestamp.tsx` | path only |

Affected imports: ~25 sites (grep `from "@/components/instrument/shared/`).
Mechanical rewrite via `sed`.

### 3.2 New primitives — CREATE

| Component | Path | Props | Behaviour | Line budget |
|-----------|------|-------|-----------|------------:|
| `TableRow` | `components/primitives/TableRow.tsx` | `height?: "default" \| "dense"` (maps to 20/18), `selected?: boolean`, `interactive?: boolean`, children | Wraps `<div role="row">`; reads `--row-h` from data-table-grid; applies hover (Tier-1) only when `interactive` | 40 |
| `MetricCell` | `components/primitives/MetricCell.tsx` | `label`, `value`, `color?`, `align?: "left" \| "right"`, `mono?: boolean` (default `true`) | Renders a single label+value pair, `font-mono tabular-nums` on value | 50 |
| `Sparkline` | `components/primitives/Sparkline.tsx` | `data: number[]`, `width=40`, `height=16`, `trend?: "auto" \| "positive" \| "negative" \| "flat"` | Single-path SVG (perf). `trend: "auto"` derives from first vs last value: ≥+0.1% positive, ≤−0.1% negative, else flat. Colour from theme token via `currentColor`. | 60 |
| `SeverityCharBadge` | `components/primitives/SeverityCharBadge.tsx` | `severity: "critical" \| "high" \| "med" \| "low"` | Renders `!` / `*` / `·` / ` ` (space) with colour mapping per palette. 1-char wide. | 30 |
| `BulkActionToolbar` | `components/primitives/BulkActionToolbar.tsx` | `selectedCount`, `actions: { label, hotkey?, onAction }[]`, `onClear` | 22px row above tables; appears when ≥1 row selected | 80 |
| `DenseArticleRow` | `components/primitives/DenseArticleRow.tsx` | `article: RankedArticle`, `density: "terminal" \| "compact"`, `withTicker?`, `withRoutingTier?`, `withCluster?` | 18px row, left-edge sentiment stripe (2px), inline time/source/headline/score. Single canonical news row across Intelligence/Quote/Dashboard/News | 100 |
| `InlineCitationAnchor` | `components/primitives/InlineCitationAnchor.tsx` | `kind: "SEC" \| "EARN" \| "NEWS" \| "KG" \| "BRF"`, `id: string`, `density: "terminal" \| "compact" \| "brief-footer"` | `[c1]` style anchor with HoverCard preview (250ms delay). Single primitive across chat / brief / AskAiPanel — replaces ~310 LOC duplicated parsing | 80 |
| `FreshnessDot` | `components/primitives/FreshnessDot.tsx` | `status: "live" \| "stale" \| "closed" \| "after-hours"` | 6px round dot, colour per status; reads `freshness_status` directly from `/v1/quotes/batch` (no client timers) | 30 |
| `DataFreshnessPill` | `components/primitives/DataFreshnessPill.tsx` | `lastUpdated: Date`, `format?: "relative" \| "absolute"` | Hybrid display per FU-3.6: relative on banners + `title=` absolute UTC | 40 |
| `EmptyState` | `components/primitives/EmptyState.tsx` | `condition: "loading" \| "empty-cold-start" \| "empty-no-data" \| "error" \| "permission" \| "coming-soon"`, `copyKey: string` (read from `lib/copy/empty-states.ts`), `cta?: ReactNode` | Single primitive for all 5 conditions per FU-10.10 / D-10.11 | 60 |
| `LoadingSkeleton` | `components/primitives/LoadingSkeleton.tsx` | `variant: "table-row" \| "cell" \| "chart-block" \| "sparkline-dotted"`, `count?: number` | Per FU loading policy: skeleton row for tables, em-dash for cells, gray-block for charts, dotted line for sparklines | 50 |
| `DemoBadge` | `components/primitives/DemoBadge.tsx` | (none) | Tiny "DEMO" chip rendered in PortfolioSwitcher + page header per FU-1.5 | 25 |
| `AiContentRail` | `components/primitives/AiContentRail.tsx` | children | Wrapper applying `border-l-2 border-[hsl(var(--accent-ai))]` to brief surfaces per DISCUSS-12 | 25 |
| `FocusRing` | `components/primitives/FocusRing.tsx` | `tier: 1 \| 2 \| 3` (defaults to 1 for table contexts, 2 for inputs, 3 for chrome) | CSS-only utility; not a real component — exports a constant string. T1: `outline-1 outline-primary outline-offset-[-1px]`. T2: `ring-1 ring-primary`. T3: `ring-2 ring-primary ring-offset-2`. | 20 |

Total new LOC budget: ~690.

### 3.3 Reuse-tracking matrix (which primitive lands which page)

For the per-page agents that come after F1, this matrix is the contract:

| Primitive | Global Shell | Dashboard | Portfolio Ov | Portfolio Dt | Quote | Financials | Intelligence | Screener | Workspace | Chat |
|-----------|:------------:|:---------:|:------------:|:------------:|:-----:|:----------:|:------------:|:--------:|:---------:|:----:|
| MetricLabel/Value | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| TableRow / MetricCell | — | ✓ | ✓ | ✓ | ✓ | ✓ | — | ✓ | ✓ | — |
| Sparkline | ✓ (watchlist) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (sentiment) | ✓ | ✓ | — |
| SeverityCharBadge | — | ✓ (alerts) | — | — | — | — | ✓ | — | — | — |
| BulkActionToolbar | — | — | — | ✓ (tx) | — | — | — | ✓ | — | — |
| DenseArticleRow | — | ✓ | — | — | ✓ | — | ✓ | — | — | — |
| InlineCitationAnchor | — | — | — | — | ✓ (brief) | ✓ (brief) | ✓ (brief) | — | — | ✓ |
| FreshnessDot | ✓ (watchlist) | ✓ | ✓ | ✓ | ✓ | — | — | ✓ | ✓ | — |
| DataFreshnessPill | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | — | ✓ |
| EmptyState | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| LoadingSkeleton | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| DemoBadge | — | ✓ | ✓ | — | — | — | — | — | — | — |
| AiContentRail | — | ✓ (brief) | — | — | ✓ (brief) | ✓ (brief) | ✓ (brief) | — | — | — |

## 4. Architecture-test extensions

Extend `apps/worldview-web/__tests__/architecture/no-off-palette-colors.test.ts`
to also fail on these 8 new patterns. Each is a single regex line.

| # | Forbidden pattern | Why |
|---|-------------------|-----|
| 1 | `\brounded-(?:none\|full)\b` → ALLOWED; everything else (`rounded-sm/md/lg/xl/2xl/3xl`) FORBIDDEN | Sharp corners contract |
| 2 | `\brounded-\[[0-9]+px\]` (anything explicit > 0) | Same |
| 3 | `\btext-(?:sm\|base\|lg\|xl\|2xl\|3xl\|4xl\|5xl\|6xl\|7xl)\b` outside the typography-source files | Body 11px max in narrative; 14px in hero only |
| 4 | `\bshadow-(?:sm\|md\|lg\|xl\|2xl\|inner)\b` | Zero shadows |
| 5 | `\bring-2 [^"]*role="row"` (ring-2 on a table row) | Focus ring tier mismatch |
| 6 | `\btransition-(?:all\|transform\|shadow)\b` | Tier-0 violation potential — must use named tokens `transition-color-only` |
| 7 | `\bduration-(?:300\|500\|700\|1000)\b` | Tier-2 ceiling 200ms |
| 8 | `\bgap-(?:6\|8\|10\|12)\b` | Spacing ceiling 16px (`gap-4`) |

Plus three new dedicated tests:

- `tests/architecture/animation-policy.test.ts` — scans for `transition-*` declarations and verifies they map to the 4-tier scale
- `tests/architecture/empty-copy-dictionary.test.ts` — verifies every `<EmptyState copyKey="X">` resolves to a key in `lib/copy/empty-states.ts`
- `tests/architecture/data-table-grid-scope.test.ts` — verifies `data-table-grid` is only applied to the 7 whitelisted surfaces in FU-5.5

## 5. globals.css full diff summary

```diff
@@ Add @@
+ CSS variables: --border-strong, --border-subtle, --row-h, --row-h-dense, --cell-px (5 lines)
+ Override: --radius: 0 (in :root.dark and :root) (1 line)
+ Block: [data-table-grid] rules (~25 lines)
@@ Remove @@
- ::-webkit-scrollbar shadow declarations if any survived
- Any `box-shadow` declarations in component-scoped layers
```

Net: +30 lines, -0 to -3 lines (depending on what dead shadow code exists).

## 6. tailwind.config.ts full diff summary

```diff
@@ Modify @@
~ borderRadius: keep only `none: "0"` + `full: "9999px"`
~ Add `border-strong` + `border-subtle` to extend.colors
+ boxShadow: every alias maps to "none"
+ transitionProperty: add "color-only" + "color-and-opacity" named tokens
+ transitionDuration: explicit "75" "100" "150" "200" ms entries
```

Net: ~25 lines of config diff. No behaviour change for components that don't
use the banned utilities; immediate visual change for the ones that do.

## 7. Migration PRs — 7 mechanical passes (one agent, sequential)

The agent runs these in order, committing between each so any single PR can
be reverted without rolling back the foundation. Each PR has a tight regex
+ a `pnpm tsc --noEmit && pnpm test` gate.

| PR | Scope | Regex (or change) | Estimated sites | Risk |
|----|-------|-------------------|----------------:|------|
| **A — Tokens** | `globals.css` + `tailwind.config.ts` + `__tests__/architecture/no-off-palette-colors.test.ts` extension | Manual file edits per §5 + §6 + §4 | 3 files | low |
| **B — Primitives promotion** | Move 4 primitives `instrument/shared/` → `primitives/`; create 11 new primitives; rewrite ~25 import sites | `sed` rename + new file creation | 4 moved + 11 new + 25 imports | low |
| **C — UI components radius** | `apps/worldview-web/components/ui/` — strip `rounded-{sm,md,lg,xl,2xl}` (Tailwind default rules already collapsed; just deletion of the class string for cleanliness) | `s/\brounded-(sm\|md\|lg\|xl\|2xl)\b//g` | ~80 sites | low — Tailwind defaults already collapse |
| **D — App routes radius** | `apps/worldview-web/app/(app)/**/*.tsx` — same purge | same regex | ~76 sites | low |
| **E — Instrument components radius** | `apps/worldview-web/components/instrument/**/*.tsx` — same purge | same regex | ~64 sites | medium — touch PLAN-0090 components |
| **F — Alerts + Portfolio radius** | `apps/worldview-web/components/{alerts,portfolio}/**/*.tsx` — same purge + flip `h-[22px]` → `h-[20px]` in table rows | regex + height swap | ~115 sites | medium |
| **G — Focus + hover + animation cleanup** | Replace `ring-2 ring-primary/40` → 3-tier `FocusRing` constants; replace ad-hoc `transition-all duration-200` with named tokens; remove `shadow-*` usage; flip remaining `h-9` to `h-[36px]`; flip `px-2` → `px-1.5` inside `data-table-grid` ancestors | regex bundle | ~120 sites | medium |

Total: ~500 mechanical edits, ~120 files. Bundle-size delta: -2-4KB gzipped
(losing rounded utilities + shadow utilities outweighs ~2KB added by named
transition tokens).

## 8. DESIGN_SYSTEM.md update

Append new §15 documenting:
1. The tiered density floor (replaces previous single-40 NFR-1)
2. The 4-tier animation taxonomy
3. The 7-surface `data-table-grid` opt-in scope (FU-5.5)
4. The new primitives catalogue (with import paths and reuse matrix)
5. The new architecture-test guardrails (§4 above)
6. Pointer to `_DECISIONS.md` §H for the locked variants

Existing §8c (PLAN-0090 / PRD-0088) stays — F1 supersedes by reference, not deletion.

## 9. Acceptance criteria

| # | Gate | Verification |
|---|------|--------------|
| 1 | `pnpm --filter worldview-web typecheck` | 0 errors |
| 2 | `pnpm --filter worldview-web test --run` | All pre-F1 tests still green |
| 3 | New architecture tests | `__tests__/architecture/{no-off-palette-colors,animation-policy,empty-copy-dictionary,data-table-grid-scope}.test.ts` all pass with the new regexes |
| 4 | `grep -rE "rounded-(sm\|md\|lg\|xl\|2xl)" apps/worldview-web/{components,app,features,contexts}` | 0 results |
| 5 | `grep -rE "shadow-(sm\|md\|lg\|xl\|2xl)" apps/worldview-web/{components,app,features,contexts}` | 0 results |
| 6 | `grep -rE "text-(sm\|base\|lg\|xl)" apps/worldview-web/{components,app,features,contexts}` in non-typography files | < 10 results (allowlist if any survive intentionally; document why) |
| 7 | Tailwind bundle size | Net delta ≤ +1KB gzipped vs pre-F1 baseline (likely -2-4KB) |
| 8 | `pnpm --filter worldview-web build` | Production build succeeds |
| 9 | Visual smoke on `pnpm dev` | Open Dashboard, Portfolio, Instrument Quote, Financials, Intelligence, Screener — confirm sharp corners everywhere, no shadow elevation visible, watchlist sparkline appears trend-tinted |
| 10 | Density canary | One Playwright spec `tests/e2e/density-screener.spec.ts` opens Screener and counts visible cells ≥ 240 |
| 11 | Architecture-test docs | DESIGN_SYSTEM.md updated with §15 reflecting all locks |
| 12 | TRACKING.md | F1 status moved to "done"; PRD-0089 next-wave field updated |

## 10. Risk register

| Risk | Mitigation |
|------|------------|
| Tailwind utility collapse breaks shadcn components (Dialog, Sheet, etc) that rely on `rounded-md` defaults | shadcn components reference the **CSS variables** for radius — collapsing `--radius` to 0 cascades automatically. PR-C smoke-test by opening one Dialog and one Sheet. If any visual breakage, fall back to per-component `[&_*]:rounded-none` wrapper on the parent rather than reverting `--radius`. |
| `rounded-md` removal makes some Dropdown / Popover frames invisible (no boundary) | Mitigation built into FU-5.4: `--border-strong` (#37373B) gives a stronger 1px hairline. PRs C+D explicitly add `border border-border` where they remove rounding to retain the boundary affordance. |
| Mechanical `h-[22px]` → `h-[20px]` flip breaks PLAN-0090 components with hardcoded geometry | Audit PR-F for any sibling element with `top-[22px]` or absolute positioning that depends on the old height. Use `sed` with `--dry-run` first, manually inspect 5-10 hits, then apply. |
| `data-table-grid` opt-in not wired to existing tables | F1 ships the primitive + globals.css rules. Per-page agents apply the `data-table-grid` attribute when they refactor each surface — F1 does NOT touch existing pages. |
| Architecture test false-positives on legitimate `text-sm` (e.g. in `markdown-content.tsx` for actual prose) | Test scans only `app/`, `components/`, `lib/`, `hooks/`, `features/`, `contexts/`. Markdown content is allowlisted via the existing `ALLOWED_FILES` pattern. |
| Bundle-size regression from named transition tokens | Net should be negative (-2KB) due to rounded + shadow utility loss. Measure with `pnpm build` before/after; revert §6.transitionProperty if needed. |

## 11. Files touched (consolidated)

```
EDIT:
  apps/worldview-web/tailwind.config.ts                              (~25 LOC diff)
  apps/worldview-web/app/globals.css                                  (~30 LOC added)
  apps/worldview-web/__tests__/architecture/no-off-palette-colors.test.ts  (+8 regexes)
  docs/ui/DESIGN_SYSTEM.md                                            (+ §15)
  docs/plans/TRACKING.md                                              (F1 done line)

CREATE:
  apps/worldview-web/components/primitives/TableRow.tsx               (40 LOC)
  apps/worldview-web/components/primitives/MetricCell.tsx             (50)
  apps/worldview-web/components/primitives/Sparkline.tsx              (60)
  apps/worldview-web/components/primitives/SeverityCharBadge.tsx      (30)
  apps/worldview-web/components/primitives/BulkActionToolbar.tsx      (80)
  apps/worldview-web/components/primitives/DenseArticleRow.tsx        (100)
  apps/worldview-web/components/primitives/InlineCitationAnchor.tsx   (80)
  apps/worldview-web/components/primitives/FreshnessDot.tsx           (30)
  apps/worldview-web/components/primitives/DataFreshnessPill.tsx      (40)
  apps/worldview-web/components/primitives/EmptyState.tsx             (60)
  apps/worldview-web/components/primitives/LoadingSkeleton.tsx        (50)
  apps/worldview-web/components/primitives/DemoBadge.tsx              (25)
  apps/worldview-web/components/primitives/AiContentRail.tsx          (25)
  apps/worldview-web/components/primitives/FocusRing.tsx              (20)
  apps/worldview-web/components/primitives/index.ts                   (re-exports)
  apps/worldview-web/lib/copy/empty-states.ts                         (~80 LOC dictionary)
  apps/worldview-web/__tests__/architecture/animation-policy.test.ts        (~100 LOC)
  apps/worldview-web/__tests__/architecture/empty-copy-dictionary.test.ts   (~60)
  apps/worldview-web/__tests__/architecture/data-table-grid-scope.test.ts   (~80)
  apps/worldview-web/__tests__/primitives/*.test.tsx                  (1 test per primitive — 14 files)
  apps/worldview-web/tests/e2e/density-screener.spec.ts               (~50 LOC Playwright canary)

MOVE:
  apps/worldview-web/components/instrument/shared/MetricLabel.tsx     → components/primitives/MetricLabel.tsx
  apps/worldview-web/components/instrument/shared/MetricValue.tsx     → components/primitives/MetricValue.tsx
  apps/worldview-web/components/instrument/shared/SectionDivider.tsx  → components/primitives/SectionDivider.tsx
  apps/worldview-web/components/instrument/shared/DataTimestamp.tsx   → components/primitives/DataTimestamp.tsx

BULK REGEX (PRs C/D/E/F/G):
  ~120 component files, ~500 individual edits
```

## 12. Estimation

| Phase | Effort |
|-------|-------:|
| PR-A tokens + arch-test | 0.5d |
| PR-B primitive promotion + create new primitives + unit tests | 1.5d |
| PRs C–F mechanical rounded/height purges | 1d (parallel-able if needed) |
| PR-G focus/hover/animation cleanup | 0.5d |
| DESIGN_SYSTEM.md §15 + TRACKING.md | 0.25d |
| Density canary Playwright spec | 0.25d |
| **Single agent serial** | **~4 days** |

## 13. Rollback plan

Every PR (A–G) commits independently. If any PR breaks something we can't
patch within the same agent session:

- Revert that PR's commit (one-liner `git revert`)
- F1 remains usable up to the prior PR boundary
- Per-page work can still consume the primitives that landed in PR-B and the
  tokens that landed in PR-A

Worst case: revert all of F1 by resetting to its parent commit. No data
migration involved (no_backfill), so revert is purely cosmetic.

## 14. Out of scope for F1 (clarify)

F1 builds the **foundation**. It does NOT:
- Rewrite any page's layout (those are F2 / 1 / 2 / 3 / ... waves)
- Apply `data-table-grid` to existing tables (per-page agents do this when they refactor)
- Backfill any data or migrate any DB (no_backfill)
- Touch backend services (S1-S10) — purely frontend
- Change navigation routing (entity-ID unification is F2)
- Implement the watchlist sidebar widget (Page 1: Global Shell)
- Restore the AI brief banner behaviour (Page 5: Quote)

If a per-page review wants to amend F1 (new primitive, new token), it
amends via a Wave-F1.1 amendment PR — never inline.

## 15. Definition of done

- All 12 acceptance criteria in §9 pass
- F1 wave commit lands on `feat/plan-0089` branch
- `docs/specs/0089-platform-page-redesign.md` updated to note F1 complete
- `docs/plans/TRACKING.md` shows PRD-0089 wave count incremented
- Page 1 (Global Shell) is unblocked
