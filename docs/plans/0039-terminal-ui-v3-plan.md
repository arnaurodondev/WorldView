# PLAN-0039 — Terminal UI v3 Ground-Up Redesign

**PRD**: PRD-0031 (`docs/specs/0031-terminal-ui-v3-ground-up-redesign.md`)
**Status**: draft
**Created**: 2026-04-25
**Author**: Claude (plan skill)
**Scope**: `apps/worldview-web/` — complete layout, workspace, navigation, and component redesign
**Implementation skill**: `/implement-ui`

---

## Pre-Flight Gate — Phase 0.5

| Check | Result | Notes |
|-------|--------|-------|
| Blocking open questions in PRD §14+ | PASS | No unresolved OQs; all D-1..D-17 decisions resolved in investigation sessions |
| Cross-plan conflicts | PASS | Only plan touching `apps/worldview-web/` — PLAN-0037 superseded |
| PRD recency | PASS | PRD written 2026-04-25 (today) |
| Architecture compliance | PASS | Frontend only; all data through S9 gateway |

---

## Codebase State Verification

| Component | Current State | v3 Target | Delta |
|---|---|---|---|
| `Sidebar.tsx` | Fixed 240px text sidebar, no collapse | 48px collapsed / 220px expanded, watchlist + alarms panels | Full rewrite → `CollapsibleSidebar.tsx` |
| `TopBar.tsx` | 44px height, search + alerts | 36px height, UTC clock, workspace selector | Height + clock + selector |
| `workspace/page.tsx` | MAX_PANELS=4, no resize, no named workspaces, 2 placeholder panels (screener/chat) | 16 panels, react-resizable-panels, named workspaces, symbol linking, 10 panel types | Full rewrite |
| `screener/page.tsx` | 7-8 columns, no filter collapse, no virtual scroll | 12 columns, collapsible filter bar, virtual scroll | Column expansion + filter |
| `portfolio/page.tsx` | Existing holdings list | 4 tabs + KPI strip + 9-col table + sector allocation | Major redesign |
| `instruments/[entityId]/page.tsx` | Brief tab exists, 4-zone overview | Brief tab removed → InstrumentAISubheader, 5-zone overview | Subheader + overview redesign |
| `dashboard/page.tsx` | Generic widget grid | 4-row trader morning routine layout | Full layout restructure |
| `alerts/page.tsx` | Flat list | Severity-grouped + ACK/snooze + rule builder + news enhancements | Major redesign |
| `chat/page.tsx` | Basic chat interface | Starter questions + entity context + citation badges + thread rename | Enhancements |
| Data row height | 32px (`h-8`) | 22px (`h-[22px]`) | Global typography sweep |
| Data font | 12px `text-xs` | 11px `text-[11px]` | Global typography sweep |

---

## §0 — Terminal CLI Quality Standard (Applies to All Waves)

> **This section is MANDATORY for every task in every wave.**
> An agent implementing any wave MUST read this section in full before writing a single line of JSX.
> Quality failures caught in Wave 8 require re-opening completed waves — enforce these rules at write-time.

The target aesthetic is the intersection of:
- **Bloomberg Terminal**: maximum data per pixel, monospace numbers, 1px hairline borders, semantic color only
- **Claude Code CLI**: structured panel chrome, ALL CAPS section labels, thin dividers, zero decorative whitespace

### §0.1 — Typography Precision Rules

```
LABELS (section headers, column headers, KPI labels):
  font-size:    10px  (text-[10px])
  font-family:  IBM Plex Sans
  font-weight:  400–500
  text-transform: uppercase
  letter-spacing: 0.08em  (tracking-[0.08em] — NOT Tailwind's tracking-widest which is 0.1em)
  color:        text-muted-foreground (#71717A)
  NEVER use text-foreground for labels — only for data values

DATA VALUES (prices, percentages, quantities, dates, IDs):
  font-size:    11px  (text-[11px])
  font-family:  IBM Plex Mono  (font-mono)
  font-variant: tabular-nums
  font-weight:  400 (normal), 500 for emphasis — NEVER 600/700 on raw financial data
  EVERY numeric value must have: font-mono tabular-nums
  No exceptions — mixing sans-serif numbers with mono columns breaks column alignment

BODY TEXT (descriptions, narrative, chat messages):
  font-size:    13px  (text-[13px])
  font-family:  IBM Plex Sans
  font-weight:  400

PAGE / SECTION HEADINGS:
  font-size:    12px  (text-xs)
  font-family:  IBM Plex Sans
  font-weight:  600
  NEVER used inside data panels — only as page-level title above panel chrome
```

### §0.2 — Layout Density Rules

```
Data table rows:      h-[22px]      ← DO NOT use h-8 (32px) or h-6 (24px) or h-10 (40px)
Panel headers:        h-6           ← 24px. The ONE exception: instrument header is h-7 (28px) per row
TopBar:               h-9           ← 36px
Sidebar expanded:     w-[220px]
Sidebar collapsed:    w-[48px]
Nav item height:      h-9           ← 36px
Section header row:   h-6           ← 24px (label + optional action button)
Filter bar height:    h-9           ← 36px when visible
Workspace panel seam: gap-px        ← 1px gap (background shows through = hairline border)

Cell padding in data rows:
  Horizontal:  px-2  (8px each side)
  Vertical:    py-0  (ZERO — row height controls vertical space entirely)
  This gives: 8px left gutter + data + 8px right gutter within each 22px row

Panel container padding:
  p-0           ← NO padding on panel containers; cells carry their own px-2
  Exception: non-tabular content (chat bubbles, description text) may use p-3

Between panels in workspace:
  gap-px        ← The 1px seam IS the border. Do not add border to panel containers.
  The background color (#09090B) showing through gap-px is the divider.
```

### §0.3 — Border & Line Rules (CRITICAL)

```
ALL borders are 1px. Zero exceptions.
NEVER: border-2, border-4, or any width > 1px
ALLOWED: border-l-2 ONLY for the AI brief accent (InstrumentAISubheader + WorkspaceBriefWidget)

Standard border color: border-border (#27272A)
Strong border (after section headers): border-border
Subtle divider (between rows): divide-border or divide-border/30

Row dividers: divide-y divide-border/30 (0.3 opacity = hairline)
Section dividers: border-b border-border (full opacity = structural)
Panel outer border: border border-border (when not in gap-px workspace)

DO NOT use:
  border-t-2, border-b-2 (except total row in holdings table)
  rounded-md, rounded-lg, rounded-xl, rounded-2xl, rounded-full ON DATA SURFACES
  rounded-[2px] is the ONLY allowed border-radius (badges, buttons, inputs, chips)
  shadow-*, drop-shadow-*, ring-shadow-* — ZERO shadows anywhere
```

### §0.4 — Color Discipline Rules

```
#FFD60A (--primary): ONLY for interactive elements (active nav, CTA buttons, links, active tab border)
  NEVER: financial data values, P&L numbers, prices, percentages

#26A69A (--positive): ONLY for price up / portfolio gain / positive delta
  NEVER: general "success" states (use text-foreground or a neutral badge instead)

#EF5350 (--negative): ONLY for price down / portfolio loss / negative delta
  NEVER: general "error" states (use text-destructive for non-financial errors)

#F59E0B (--warning): ONLY for MEDIUM severity alerts, stale data badges
  NEVER: decorative use

#FFD60A/10 (amber fill): ONLY for AI-generated content panels (Brief, InstrumentAISubheader)

text-foreground (#E4E4E7): primary data (prices, values, tickers, company names)
text-muted-foreground (#71717A): labels, timestamps, column headers, section titles
text-muted-foreground/60: placeholder text, tertiary labels, empty state text

Background elevation:
  bg-background (#09090B): page background
  bg-card (#111113): panels, sidebar, popovers
  bg-muted (#18181B): hover rows, elevated panels, selected states
```

### §0.5 — Anti-Pattern Hard Ban List

These patterns are FORBIDDEN in PLAN-0039 implementation. If found in existing code, they MUST be removed.

```
SHADOWS (any form):
  ✗ shadow-sm, shadow, shadow-md, shadow-lg, shadow-xl, shadow-2xl, shadow-inner
  ✗ drop-shadow-*
  ✗ ring-shadow-* (different from focus rings — which ARE allowed)
  Why: Shadows are decorative elevation. Terminal UIs use borders for structure.

ROUNDED CORNERS beyond 2px on data surfaces:
  ✗ rounded (4px), rounded-md (6px), rounded-lg (8px), rounded-xl (12px), rounded-full
  ✓ ONLY: rounded-[2px] for badges, buttons, inputs, color chips, small tags
  Why: Rounded cards communicate "consumer app". Sharp edges = terminal authority.

GRADIENTS:
  ✗ bg-gradient-*, from-*, via-*, to-* on any surface
  ✓ ONLY: linear-gradient INSIDE HeatCell score bars (pure data visualization, not decoration)
  Why: Gradients are decorative. Terminal palettes are flat.

EXCESS PADDING on data panels:
  ✗ p-4, p-6, p-8, p-12 inside panel content areas
  ✓ px-2 py-0 on row cells; p-3 on narrative/non-tabular content
  Why: Padding kills density. Bloomberg shows 40+ rows. We show 30+.

CARDS INSIDE PANELS:
  ✗ <Card> or <CardContent> inside a panel that already has a border
  ✓ dividers (divide-y) replace nested cards for tabular content
  Why: Cards-in-panels = nesting that doubles chrome without adding meaning.

ANIMATIONS beyond these approved cases:
  ✓ Sidebar width: transition-[width] duration-200 ease-out
  ✓ Filter bar collapse: grid-template-rows 0fr→1fr, duration-200 ease-out
  ✓ AI subheader expand: grid-template-rows, duration-150 ease-out
  ✗ Everything else: no fade-in, no slide-in, no bounce, no scale
  ✗ Animating: width, height, margin, padding directly (causes reflow)
  Why: Animation delays read as "app", not "terminal". Data appears instantly.

LARGE EMPTY STATES:
  ✗ Centered icon + heading + body text + button (the "consumer app" empty state)
  ✓ <InlineEmptyState>: single line of text-[11px] text-muted-foreground, left-aligned
  ✓ Example: "No holdings yet." or "Add symbols via Portfolio → Watchlists"
  Why: Empty states in Bloomberg are 1 line of text in the data area. Not a marketing page.
```

### §0.6 — Scrollbar Styling (apply globally)

Add to `app/globals.css` (Wave 1):

```css
/* Terminal-grade minimal scrollbar — matches Claude Code aesthetic */
::-webkit-scrollbar {
  width: 4px;
  height: 4px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: var(--border); /* #27272A */
  border-radius: 0;          /* sharp, no rounded scrollbar thumb */
}
::-webkit-scrollbar-thumb:hover {
  background: var(--muted-foreground); /* slightly lighter on hover */
}
/* Firefox */
* {
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
```

### §0.7 — Focus & Interaction Precision

```
Focus rings:
  ring-1 ring-primary ring-offset-1 ring-offset-background
  NOT ring-2 (too thick for terminal aesthetic)
  Applied to: buttons, inputs, interactive rows (keyboard nav)

Hover rows:
  hover:bg-muted/40   ← very subtle (0.4 opacity muted = barely visible tint)
  NOT hover:bg-muted  (too bright — makes data unreadable)

Input styling (search, filter inputs):
  bg-background border border-border rounded-[2px]
  h-7 (28px) for compact inputs inside filter bars
  h-9 (36px) for prominent inputs (chat input, search bar)
  text-[11px] font-mono for data-entry inputs
  text-[13px] font-sans for prose inputs (chat messages)
  placeholder:text-muted-foreground/60
  focus-visible:ring-1 focus-visible:ring-primary focus-visible:ring-offset-0

Dropdown / Select / Popover:
  bg-card border border-border rounded-[2px]
  shadow-none  (explicitly override shadcn defaults)
  py-0 on items, h-[22px] on option rows
```

### §0.8 — Column Header Contract

Every column header MUST mirror the data alignment of its column:

```
Text/ticker columns:   text-left  (both header and data)
Number/price columns:  text-right (both header and data)
Score/badge columns:   text-center or text-right (both header and data)
```

ALL column headers use: `text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-sans`
Sortable headers add: `cursor-pointer select-none hover:text-foreground` + sort icon `↑`/`↓` (12px)

### §0.9 — Section Header Pattern

Every data section (in Fundamentals, Portfolio, Dashboard widgets) uses this pattern:

```tsx
// Terminal CLI section header — mirrors Claude Code panel headers
<div className="flex items-center justify-between border-b border-border px-2 h-6">
  <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-sans">
    SECTION TITLE
  </span>
  {/* Optional: action button on right */}
  <button className="text-[10px] text-muted-foreground hover:text-foreground">Action</button>
</div>
```

This is the ONLY acceptable section header pattern. NO "Card header" with large fonts.

### §0.10 — Bloomberg Calibration Benchmarks

Before completing any wave, verify these terminal quality benchmarks:

| Benchmark | Target | How to Verify |
|-----------|--------|---------------|
| Data rows visible without scroll at 1080p | ≥30 rows | DevTools → count visible rows in viewport |
| Panel chrome overhead (header + padding) | ≤24px per panel | `h-6` header + `p-0` content = 24px overhead |
| Pixel density score (data per 100px²) | Match Finviz screener | Side-by-side visual comparison screenshot |
| Number column alignment uniformity | 100% right-aligned | Grep for `text-left` in number contexts |
| Shadow count in changed files | 0 | `grep -rn "shadow-" apps/worldview-web/components/` |
| Rounded corner violations | 0 | `grep -rn "rounded-lg\|rounded-xl\|rounded-md\|rounded-2xl" apps/worldview-web/components/` |
| Scrollbar visible thickness | 4px | DevTools inspect scrollbar width |
| Gradient count | 0 (except HeatCell) | `grep -rn "bg-gradient\|from-\|via-" apps/worldview-web/components/` |

---

## Plan Dependency Graph

```
Wave 0 (P0 fixes — TypeScript, workspace placeholders, screenshots)
    ↓
Wave 1 (Shell — CollapsibleSidebar, TopBar, WatchlistPanel, AlarmsPanel)
    ↓
Wave 2 (Workspace — react-resizable-panels, named workspaces, 10 panel types, symbol linking)
    ↓ (can run in parallel with Wave 3)
Wave 3 (Screener — 12 cols, virtual scroll, collapsible filter bar)
    ↓ (can run in parallel with Wave 4)
Wave 4 (Portfolio — 4 tabs, 9-col holdings, sector allocation, KPI strip, gateway DIVIDEND fix)
    ↓ (can run in parallel with Wave 5)
Wave 5 (Instrument Detail — header, AI subheader, 5-zone overview, Fundamentals 9 sections, News/Intel filters)
    ↓ (can run in parallel with Wave 6)
Wave 6 (Row Height + Typography Global Sweep — all data surfaces)
    ↓
Wave 7 (Dashboard + Chat + Alerts redesign)
    ↓
Wave 8 (QA — Playwright, screenshots, console error validation)
```

**Note**: Waves 2–5 can proceed in parallel worktrees after Wave 1 is complete.
**Critical path**: Wave 0 → Wave 1 → Wave 7 → Wave 8.

---

## ✅ Wave 0 — P0 Blockers (Prerequisite)

**Goal**: Unblock TypeScript compilation and replace workspace placeholder panels.
**Depends on**: none
**Estimated effort**: 2-4 hours
**Architecture layer**: API / application
**Status**: **DONE** — 2026-04-25 · 341 tests pass · lint + typecheck clean

### Tasks

#### T-39-W0-01: Fix TypeScript Typecheck Errors

**Type**: impl
**depends_on**: none
**blocks**: all subsequent waves
**Target files**:
- `apps/worldview-web/components/dashboard/MorningBriefCard.tsx`
- `apps/worldview-web/lib/gateway.ts`

**What to build**:
Fix 5 TypeScript errors found in QA audit `2026-04-25-qa-terminal-redesign-report.md`. These block `pnpm run typecheck` from exiting 0.

**Logic & Behavior**:
1. `MorningBriefCard.tsx:118` — `.reduce()` callback parameters `'text'` and `'mention'` need explicit types. The `reduce` likely processes an array of mention strings. Add `: string` type annotation to both.
2. `MorningBriefCard.tsx:129` — `.reduce()` callback parameters `'part'` and `'i'` (likely `string` and `number`). Add explicit type annotations.
3. `gateway.ts:60` — `MorningBrief` type was removed in working tree but the module `"@/types/api"` no longer exports it. The working-tree fix already uses `BriefingResponse` — verify the import line references the correct type.

**Acceptance criteria**:
- [ ] `pnpm run typecheck` exits 0 (no TypeScript errors)
- [ ] `pnpm test` still passes (≥285 tests)
- [ ] `pnpm run lint` clean

---

#### T-39-W0-02: WorkspaceScreenerWidget — Replace Placeholder

**Type**: impl
**depends_on**: none
**blocks**: T-39-W2-03
**Target files**:
- `apps/worldview-web/components/workspace/WorkspaceScreenerWidget.tsx` (new)
- `apps/worldview-web/app/(app)/workspace/page.tsx` (update import)

**What to build**:
A compact screener widget for the workspace `screener` panel type. Replaces the `WorkspacePlaceholder` component for screener.

**Entities / Components**:
- **Name**: `WorkspaceScreenerWidget`
- **Purpose**: Show top 20 instruments by `market_impact_score` in a compact 5-column table
- **Key attributes**:
  - Columns: Ticker | Name | Change% | Mkt Cap | Score (5 columns)
  - Row height: `h-[22px]`
  - Font: `text-[11px] font-mono tabular-nums` for numbers, `text-[11px]` sans for text
  - Data source: `POST /v1/fundamentals/screen` with `limit: 20, sort_by: "market_impact_score" desc`
  - No filter panel — workspace panels are filter-free (full screener has filters)
  - Row click: `router.push('/instruments/' + entityId)`
  - Stale time: `60_000` (1 minute)

**Logic & Behavior**:
1. Fetch `gatewayClient.screenEntities({ limit: 20, offset: 0 })` on mount
2. Render sticky header row: `TICKER | NAME | CHG% | CAP | SCORE`
3. Render data rows with `divide-y divide-border/30` — no rounded borders
4. `HeatCell` for Change% column (existing component at `components/screener/HeatCell.tsx`)
5. Score: horizontal `div` bar from 0–100 using `bg-primary/30` fill, `4px height`
6. Footer: `[View full screener →]` link

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `renders-top-20-rows` | Table shows up to 20 rows when data available | unit |
| `shows-loading-skeleton` | Skeleton shown while query loading | unit |
| `row-click-navigates` | Clicking row calls router.push with entityId | unit |

**Acceptance criteria**:
- [ ] `screener` workspace panel type renders `WorkspaceScreenerWidget` (not placeholder)
- [ ] Shows 20 rows when data available
- [ ] No console errors
- [ ] Unit tests pass

---

#### T-39-W0-03: WorkspaceChatWidget — Replace Placeholder

**Type**: impl
**depends_on**: none
**blocks**: T-39-W2-03
**Target files**:
- `apps/worldview-web/components/workspace/WorkspaceChatWidget.tsx` (new)
- `apps/worldview-web/app/(app)/workspace/page.tsx` (update import)

**What to build**:
A minimal streaming chat widget for the workspace `chat` panel type. Replaces the `WorkspacePlaceholder` for chat.

**Entities / Components**:
- **Name**: `WorkspaceChatWidget`
- **Purpose**: Embedded SSE chat with 36px input + message history, 11px sans text
- **Key attributes**:
  - Input: 36px height, full width, `Enter` to send
  - Messages: 11px `text-[11px]`, user messages right-aligned (`bg-primary/15`), AI messages left-aligned (`bg-muted/30`)
  - Streaming: uses SSE via `POST /v1/chat/stream` (same as chat page)
  - No thread list — single ephemeral thread per panel instance
  - Max 10 messages visible; scroll oldest out
  - Panel min-height already enforced by workspace grid (320px min)

**Logic & Behavior**:
1. `useState` for messages array + current input
2. `onSubmit`: POST to `/api/chat/stream` with `{ message, conversation_id: localId }`
3. SSE reader: append streamed tokens to last AI message
4. Auto-scroll to bottom on new message
5. "Loading…" indicator while streaming (TypingIndicator component if available, else inline dots)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `renders-input` | Input field is rendered | unit |
| `shows-empty-state` | Shows "Ask me anything…" placeholder text | unit |
| `sends-message` | Enter key calls submit handler | unit |

**Acceptance criteria**:
- [ ] `chat` workspace panel type renders `WorkspaceChatWidget` (not placeholder)
- [ ] Input is focused-able, Enter sends message
- [ ] No console errors

---

#### T-39-W0-04: Screener Filter Collapse + Screenshots

**Type**: impl
**depends_on**: T-39-W0-01
**blocks**: T-39-W3-01
**Target files**:
- `apps/worldview-web/app/(app)/screener/page.tsx`
- `docs/screenshots/v3/` (new directory, PNG files)

**What to build**:
1. Add collapsible filter bar to existing screener page (grid-template-rows animation)
2. Capture initial browser screenshots via Playwright for all major routes

**Logic & Behavior — Filter collapse**:
1. Add `[Filters ▾]` toggle button above the screener table
2. Filter bar wrapper: `grid grid-rows-[0fr] transition-all duration-200 ease-out` when collapsed, `grid-rows-[1fr]` when expanded
3. Inner div: `overflow-hidden` (required for grid-rows collapse trick)
4. Toggle state: `useState<boolean>(false)` — default collapsed
5. Button label: `Filters ▾` / `Filters ▴` based on state

**Logic & Behavior — Screenshots**:
1. Run dev server: `pnpm dev`
2. Use Playwright `page.screenshot()` to capture: `/dashboard`, `/screener`, `/workspace`, `/portfolio`, `/alerts`, `/chat`, `/instruments/[demo-entity]` (fundamentals, news, intelligence tabs)
3. Save to `docs/screenshots/v3/` as `dashboard.png`, `screener.png`, etc.

**Acceptance criteria**:
- [ ] Screener filter bar collapses/expands with smooth animation
- [ ] Default state: collapsed
- [ ] ≥6 screenshots committed to `docs/screenshots/v3/`

---

#### T-39-W0-05: SessionStatsStrip Component

**Type**: impl
**depends_on**: none
**blocks**: T-39-W5-01
**Target files**:
- `apps/worldview-web/components/instrument/SessionStatsStrip.tsx` (new)

**What to build**:
A new 20px height component displaying O/H/L/V/VWAP from the last OHLCV bar.

**Entities / Components**:
- **Name**: `SessionStatsStrip`
- **Purpose**: Shows session OHLCV stats below the chart. Uses last bar data (NOT Quote type — Quote lacks open/high/low).
- **Props**:
  ```typescript
  interface SessionStatsStripProps {
    // Last OHLCV bar data — passed from parent who owns ohlcv data
    open: number | null;
    high: number | null;
    low: number | null;
    volume: number | null;
    vwap?: number | null;
  }
  ```
- **Layout**: `flex gap-4 px-3 py-0.5 bg-card border-b border-border`
- **Per stat**: `O: 171.12` — label in `text-[10px] text-muted-foreground`, value in `text-[10px] font-mono tabular-nums text-foreground`
- **Separator**: `│` character between stats, `text-border`
- **Height**: 20px (`h-5`)

**Logic & Behavior**:
- Render 5 stats: O (open), H (high, `text-positive`), L (low, `text-negative`), V (volume — abbreviated), VWAP
- If value is null: show `—` in `text-muted-foreground`
- Volume abbreviated: `43.2M` format using `formatMarketCap` utility

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `renders-all-stats` | All 5 labels + values shown | unit |
| `renders-null-as-dash` | Null values show `—` | unit |
| `high-is-positive-colored` | High value has `text-positive` class | unit |

**Acceptance criteria**:
- [ ] Component renders without errors
- [ ] High value colored positive, Low colored negative
- [ ] Null values show `—` (not `0` or `undefined`)
- [ ] Unit tests pass

---

#### T-39-W0-06: Global CSS Terminal Quality Baseline

**Type**: config
**depends_on**: none
**blocks**: none (additive)
**Target files**:
- `apps/worldview-web/app/globals.css`

**What to build**:
Add terminal CLI quality baseline CSS to `globals.css`: minimal scrollbar styling, shadow reset, and precision custom properties.

**Changes**:
1. Add scrollbar CSS from §0.6 of this plan (4px width, transparent track, border-color thumb, no border-radius on thumb)
2. Add global `box-shadow: none` reset on all shadcn card/popover/dropdown defaults:
   ```css
   /* Terminal: all shadows are structural (borders), never decorative */
   .shadow-sm, .shadow, .shadow-md, .shadow-lg, .shadow-xl, .shadow-2xl {
     box-shadow: none !important;
   }
   /* Override shadcn popover/dropdown shadows */
   [data-radix-popper-content-wrapper] > * {
     box-shadow: none !important;
     border: 1px solid hsl(var(--border)) !important;
   }
   ```
3. Add CSS custom property `--cell-px: 8px` for consistent horizontal cell padding

**Acceptance criteria**:
- [ ] Scrollbar is 4px wide with no border-radius
- [ ] No shadcn popovers/dropdowns show box-shadow
- [ ] `pnpm run lint` clean

---

### Wave 0 Validation Gate
- [ ] `pnpm run typecheck` exits 0
- [ ] `pnpm run lint` exits 0
- [ ] `pnpm test` — all ≥285 existing tests pass + new unit tests
- [ ] Workspace `screener` panel shows table (not placeholder text)
- [ ] Workspace `chat` panel shows input (not placeholder text)
- [ ] ≥6 screenshots in `docs/screenshots/v3/`
- [ ] **Terminal quality**: `grep -rn "shadow-" apps/worldview-web/components/` returns 0 matches
- [ ] **Terminal quality**: scrollbar is 4px in DevTools Elements panel

### Wave 0 Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `__tests__/workspace.test.tsx` | WorkspacePlaceholder removed for `screener` and `chat` types | Update test to assert WorkspaceScreenerWidget / WorkspaceChatWidget renders |
| `__tests__/instrument-detail.test.tsx` | If any test imports `SessionStatsStrip` before it exists | No break (additive component) |

### Wave 0 Regression Guardrails
- **General**: Do not delete or skip any existing test; only fix behavior or add new tests per R19
- **TypeScript**: Use `// @ts-expect-error` ONLY with a comment explaining why; never `// @ts-ignore`

---

## ✅ Wave 1 — New Shell (CollapsibleSidebar + TopBar)

**Status**: **DONE** — 2026-04-25 · 365 tests pass · lint + typecheck clean

**Goal**: Replace the text sidebar with a collapsible icon rail containing watchlist and alarms panels. Update TopBar to 36px with UTC clock.
**Depends on**: Wave 0
**Estimated effort**: 4-6 hours
**Architecture layer**: UI shell

### Pre-read (agent must read before starting)
- `apps/worldview-web/components/shell/Sidebar.tsx` — current implementation to understand navigation items
- `apps/worldview-web/components/shell/TopBar.tsx` — current TopBar to understand existing features
- `apps/worldview-web/app/(app)/layout.tsx` — shell wiring
- `docs/specs/0031-terminal-ui-v3-ground-up-redesign.md` §4.2, §4.3 — exact specs

### Tasks

#### T-39-W1-01: CollapsibleSidebar Component

**Type**: impl
**depends_on**: none
**blocks**: T-39-W1-04
**Target files**:
- `apps/worldview-web/components/shell/CollapsibleSidebar.tsx` (new)
- `apps/worldview-web/components/shell/WatchlistPanel.tsx` (new)
- `apps/worldview-web/components/shell/AlarmsPanel.tsx` (new)

**What to build**:
Full-featured collapsible sidebar per PRD §4.3.

**Entities / Components**:

**CollapsibleSidebar**:
- **Props**: `{ expanded: boolean; onToggle: () => void }`
- **Layout**: `flex flex-col bg-card border-r border-border transition-[width] duration-200 ease-out`
- **Width**: `w-[48px]` when collapsed, `w-[220px]` when expanded
- **Sections** (top-to-bottom):
  1. Logo / brand (28px height): `[W]` glyph when collapsed, `[W] WORLDVIEW` when expanded
  2. Divider `border-b border-border`
  3. Navigation items (see nav spec below)
  4. Divider `border-b border-border`
  5. WatchlistPanel (expanded only — hidden with `overflow-hidden` when collapsed)
  6. AlarmsPanel (both states — icon + badge when collapsed, rows when expanded)
  7. Divider `border-b border-border`
  8. Settings + collapse toggle (bottom, sticky)

**Navigation items** (6 items):
- `[⊞] Workspace` → `/workspace` (shortcut: `g+w`)
- `[⊟] Dashboard` → `/dashboard` (shortcut: `g+d`)
- `[⚡] Screener` → `/screener` (shortcut: `g+s`)
- `[⊕] Portfolio` → `/portfolio` (shortcut: `g+p`)
- `[🔔] Alerts` → `/alerts` (shortcut: `g+a`)
- `[💬] Chat` → `/chat` (shortcut: `g+c`)

**Nav item styling**:
- Active: `bg-primary/15 text-primary border-l-2 border-primary` (when expanded), or `bg-primary/15 text-primary` (when collapsed)
- Inactive: `text-muted-foreground hover:bg-muted/60 hover:text-foreground`
- Use Next.js `usePathname()` to detect active route
- Row height: 36px (`h-9`)
- Icon: 18px, centered when collapsed; `gap-2` with label when expanded
- Label: `text-xs font-medium` — visible only when expanded; hide with `opacity-0 w-0` when collapsed

**Collapse/expand toggle** (bottom):
- Collapsed: `[⟶]` icon button at bottom center, tooltip "Expand sidebar"
- Expanded: `[Settings ⚙] [⟵ Collapse]` in a flex row

**WatchlistPanel** (separate component):
- Data: `GET /v1/watchlists` → first watchlist members → `GET /v1/quotes/batch` with tickers
- Refresh: `staleTime: 30_000` (30s)
- Header: `WATCHLIST [CurrentName ▾]` (10px uppercase label + popover switcher button)
- Watchlist switcher popover: lists all watchlists, `[+ New Watchlist]` option (navigates to `/portfolio?tab=watchlists`)
- Rows: ticker (40px, `font-mono text-[11px]`) | price (right-aligned, mono) | change% (colored + ▲/▼)
- Row height: 22px
- Click row: `router.push('/instruments/' + entityId)`
- Empty state: `<InlineEmptyState message="Add symbols in Portfolio → Watchlists" />`
- Max rows: 10; if more → show first 10 with `[+N more]` link to `/portfolio?tab=watchlists`

**AlarmsPanel** (separate component):
- Data: `GET /v1/alerts/pending` — filtered client-side to alerts where `ticker` is in portfolio holdings OR watchlist symbols
- Header: `ALARMS ● N` (N = count, red badge)
- Max 5 rows; `[+N more →]` link to `/alerts`
- Row: severity dot (6px) + message truncated to 1 line + time ago; 22px height
- Empty state: short inline text — no large centered cards
- Click row: `router.push('/alerts')`

**Logic & Behavior**:
- Collapse state: `localStorage['worldview-sidebar-expanded']` → `true` by default
- Auto-collapse below 1280px viewport: `useEffect` with `ResizeObserver` on body
- Do NOT animate `width` directly — use `grid-template-columns` on the shell parent layout or CSS `var(--sidebar-width)` approach; OR simply use conditional `w-[48px]`/`w-[220px]` classes with `transition-[width]`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `renders-nav-items` | All 6 nav items present | unit |
| `active-item-highlighted` | Current route gets active styling | unit |
| `collapsed-shows-icons-only` | Labels hidden when collapsed | unit |
| `toggle-persists-to-localStorage` | Click toggle → localStorage updated | unit |
| `watchlist-panel-shows-empty-state` | Empty state when no watchlist symbols | unit |
| `alarms-panel-filters-to-portfolio` | Only shows alerts for portfolio/watchlist tickers | unit |

**Acceptance criteria**:
- [ ] Sidebar collapses to 48px, expands to 220px
- [ ] Collapse state persists to localStorage
- [ ] WatchlistPanel shows live prices (or empty state)
- [ ] AlarmsPanel shows filtered alerts (or empty state)
- [ ] Nav item for current route is highlighted
- [ ] Unit tests pass

---

#### T-39-W1-02: Updated TopBar (36px, UTC clock, workspace selector)

**Type**: impl
**depends_on**: none
**blocks**: T-39-W1-04
**Target files**:
- `apps/worldview-web/components/shell/TopBar.tsx` (modify)
- `apps/worldview-web/components/shell/UtcClock.tsx` (already exists — integrate)

**What to build**:
Update TopBar height from 44px to 36px, add UTC clock, add workspace selector (visible only on `/workspace`).

**Logic & Behavior**:
- Height: change `h-11` (44px) → `h-9` (36px)
- UTC clock: use existing `UtcClock.tsx` component — render between search and market status
- Workspace selector: `usePathname()` — if route is `/workspace`, show `[Workspace: "Day Trading" ▼]` dropdown button; clicking opens workspace rename popover (tie into Wave 2 `useWorkspace` context)
- Logo: if sidebar is expanded (from context), hide logo in TopBar (shown in sidebar); if collapsed, show `W` in TopBar
- Compact all spacing: `px-3` instead of `px-4`, `gap-2` instead of `gap-3`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `renders-utc-clock` | UtcClock component is present | unit |
| `topbar-height-36px` | Root element has h-9 class | unit |
| `workspace-selector-only-on-workspace-route` | Selector absent on /dashboard | unit |

**Acceptance criteria**:
- [ ] TopBar height is 36px
- [ ] UTC clock is visible
- [ ] Workspace selector visible on `/workspace` route only

---

#### T-39-W1-03: WorkspaceTabs Component

**Type**: impl
**depends_on**: none
**blocks**: T-39-W2-01
**Target files**:
- `apps/worldview-web/components/workspace/WorkspaceTabs.tsx` (new)
- `apps/worldview-web/contexts/WorkspaceContext.tsx` (new)

**What to build**:
Named workspace tab bar and React context for workspace state management.

**Entities / Components**:

**WorkspaceContext**:
- Provides: `activeWorkspaceId`, `workspaces`, `setActiveWorkspace`, `addWorkspace`, `removeWorkspace`, `renameWorkspace`
- Persistence: `localStorage['worldview-workspaces']` — full `WorkspacePersistence` schema from PRD §5.8
- Initial state: 4 default presets (Day Trading, Research, Portfolio Monitor, Morning Brief) from PRD §5.5
- Default preset panel configs (from PRD §5.5):
  - "Day Trading": chart + watchlist (top row), screener + alerts (bottom row)
  - "Research": chart + news (top row), fundamentals + graph (bottom row)
  - "Portfolio Monitor": portfolio + chart (top row), watchlist + news (bottom row)
  - "Morning Brief": brief (full row 1), screener + alerts (row 2)

**WorkspaceTabs**:
- Layout: `flex items-end gap-0 border-b border-border h-8 px-2 bg-background`
- Tab: `px-3 text-xs font-medium border-b-2 cursor-pointer`; active: `border-primary text-foreground`, inactive: `border-transparent text-muted-foreground hover:text-foreground`
- `✕` close button: appears on hover; confirm dialog if >1 panel in workspace (use `window.confirm` for MVP)
- `[+ Add Workspace]` button at right: text `text-xs text-muted-foreground` with `+` icon
- Rename: double-click on tab → inline `<input>` edit → Enter to confirm

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `shows-default-workspaces` | 4 presets visible on first load | unit |
| `active-workspace-highlighted` | Active tab has border-primary | unit |
| `add-workspace` | Clicking Add creates new workspace | unit |
| `rename-workspace` | Double-click → input → Enter renames | unit |
| `persistence` | Workspaces saved to localStorage | unit |

**Acceptance criteria**:
- [ ] 4 default workspace presets on first load
- [ ] Tab switching changes active workspace
- [ ] Rename on double-click works
- [ ] Persistence to localStorage verified

---

#### T-39-W1-04: Wire Shell Together

**Type**: impl
**depends_on**: T-39-W1-01, T-39-W1-02, T-39-W1-03
**blocks**: T-39-W2-01
**Target files**:
- `apps/worldview-web/app/(app)/layout.tsx` (modify)

**What to build**:
Replace `<Sidebar />` with `<CollapsibleSidebar />` in the app layout, wire `WorkspaceContext` provider, update layout grid to use CSS var for sidebar width.

**Logic & Behavior**:
- Replace `import { Sidebar }` → `import { CollapsibleSidebar }`
- Add `WorkspaceContext` provider wrapping the entire layout
- Sidebar expanded state: `useState` initialized from `localStorage['worldview-sidebar-expanded']`
- Pass `expanded` and `onToggle` props to `CollapsibleSidebar`
- Layout grid: use `grid grid-cols-[var(--sidebar-width,48px)_1fr]` for the sidebar/main split; `--sidebar-width` is set to `48px` or `220px` via inline style based on expanded state
- Keep `FlashOverlay` and `AskAiPanel` as before
- Remove `AskAiPanel` from layout — it is being replaced by the dedicated `/chat` page in v3 (PRD says use dedicated Chat page, not a floating panel)

**Acceptance criteria**:
- [ ] CollapsibleSidebar renders in layout
- [ ] AskAiPanel removed from layout
- [ ] WorkspaceContext provider wraps app
- [ ] Sidebar toggle persists state

---

### Wave 1 Terminal Quality Additions

**CollapsibleSidebar — exact styling spec**:

```tsx
// Sidebar container
<aside className={cn(
  "flex flex-col h-full bg-card border-r border-border",
  "transition-[width] duration-200 ease-out overflow-hidden",
  expanded ? "w-[220px]" : "w-[48px]"
)}>
  {/* Logo row — 36px height, matches TopBar */}
  <div className="flex h-9 items-center border-b border-border px-3 shrink-0">
    <span className="text-[13px] font-semibold text-primary font-mono">W</span>
    {expanded && (
      <span className="ml-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        WORLDVIEW
      </span>
    )}
  </div>

  {/* Nav items */}
  {NAV_ITEMS.map(item => (
    <Link key={item.href} href={item.href}
      className={cn(
        "flex h-9 items-center px-3 gap-2",
        "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
        "transition-colors duration-0",  // NO transition — instant
        isActive && "bg-primary/10 text-primary border-l-2 border-primary"
      )}
    >
      <item.icon className="h-[18px] w-[18px] shrink-0" />
      {expanded && (
        <span className="text-xs font-medium truncate">{item.label}</span>
      )}
    </Link>
  ))}

  {/* Watchlist section header */}
  <div className="flex items-center justify-between border-b border-border border-t border-t-border px-2 h-6 mt-1 shrink-0">
    <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
      WATCHLIST
    </span>
    {/* Watchlist switcher button */}
    <button className="text-[10px] text-muted-foreground hover:text-foreground font-mono">
      {currentWatchlistName} ▾
    </button>
  </div>

  {/* Watchlist rows */}
  <div className="flex-none overflow-y-auto divide-y divide-border/30">
    {items.map(item => (
      <div key={item.id}
        className="flex items-center h-[22px] px-2 gap-0 hover:bg-muted/40 cursor-pointer"
      >
        <span className="w-[40px] shrink-0 font-mono text-[11px] tabular-nums text-foreground">
          {item.ticker}
        </span>
        <span className="flex-1 text-right font-mono text-[11px] tabular-nums text-foreground">
          {item.price}
        </span>
        <span className={cn(
          "w-[52px] text-right font-mono text-[11px] tabular-nums",
          item.change >= 0 ? "text-positive" : "text-negative"
        )}>
          {item.change >= 0 ? "▲" : "▼"}{Math.abs(item.change).toFixed(2)}%
        </span>
      </div>
    ))}
  </div>
</aside>
```

**Alarms section — exact styling spec**:
```tsx
<div className="flex items-center border-b border-border border-t border-t-border px-2 h-6 shrink-0">
  <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground flex-1">
    ALARMS
  </span>
  {alarmCount > 0 && (
    <span className="font-mono text-[10px] tabular-nums text-negative">● {alarmCount}</span>
  )}
</div>
{alarms.slice(0, 5).map(alarm => (
  <div key={alarm.id}
    className="flex items-center h-[22px] px-2 gap-1.5 hover:bg-muted/40 cursor-pointer"
  >
    <span className={cn("h-1.5 w-1.5 rounded-full shrink-0",
      alarm.severity === 'CRITICAL' ? "bg-negative" :
      alarm.severity === 'HIGH' ? "bg-warning" : "bg-muted-foreground"
    )} />
    <span className="text-[11px] text-foreground truncate flex-1">{alarm.message}</span>
    <span className="text-[10px] text-muted-foreground shrink-0 font-mono tabular-nums">
      {alarm.timeAgo}
    </span>
  </div>
))}
```

### Wave 1 Validation Gate
- [ ] `pnpm run typecheck` exits 0
- [ ] `pnpm run lint` exits 0
- [ ] `pnpm test` — all tests pass (including updated layout tests)
- [ ] Visual: sidebar collapses/expands at 48/220px
- [ ] Visual: TopBar is 36px height with UTC clock visible
- [ ] **Terminal quality**: `grep -rn "shadow-" apps/worldview-web/components/shell/` returns 0
- [ ] **Terminal quality**: `grep -rn "rounded-lg\|rounded-xl\|rounded-md" apps/worldview-web/components/shell/` returns 0
- [ ] **Terminal quality**: Watchlist rows are exactly 22px (DevTools height check)
- [ ] **Terminal quality**: Nav item hover is `bg-muted/40` (barely visible, not full muted)

### Wave 1 Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `__tests__/app-layout.test.tsx` | Imports `Sidebar` (old), tests `AskAiPanel` presence | Update to expect `CollapsibleSidebar`; remove AskAiPanel assertion |
| `__tests__/AskAiPanel.test.tsx` | AskAiPanel no longer in layout | Keep component tests; update layout test to not expect AskAiPanel in layout DOM |
| Any test that checks TopBar height | TopBar now 36px | Update height assertions |

### Wave 1 Regression Guardrails
- **R19**: Do not delete existing Sidebar tests — add new CollapsibleSidebar tests alongside
- **Auth pattern**: CollapsibleSidebar should not require auth directly; it reads from `useAuth()` if needed for watchlist data, and `WatchlistPanel` must check `enabled: !!accessToken` in queries

---

## Wave 2 ✅ — Workspace Full Redesign

**Status**: **DONE** — 2026-04-25 · 359 tests pass · lint + typecheck clean

**Goal**: Implement react-resizable-panels, named workspaces, 10 panel types, and symbol linking.
**Depends on**: Wave 1
**Estimated effort**: 6-8 hours
**Architecture layer**: UI application

### Pre-read (agent must read before starting)
- `apps/worldview-web/app/(app)/workspace/page.tsx` — current implementation (full read)
- `apps/worldview-web/contexts/WorkspaceContext.tsx` (from Wave 1)
- `docs/specs/0031-terminal-ui-v3-ground-up-redesign.md` §5 — full workspace spec
- Check `pnpm list react-resizable-panels` — if not installed, add to `package.json` with exact version

### Tasks

#### T-39-W2-01: Install Dependencies + SymbolLinkingContext

**Type**: impl
**depends_on**: T-39-W1-04
**blocks**: T-39-W2-02, T-39-W2-03
**Target files**:
- `apps/worldview-web/package.json`
- `apps/worldview-web/contexts/SymbolLinkingContext.tsx` (new)

**What to build**:
1. Install `react-resizable-panels` (latest exact version, no `^`)
2. Install `@tanstack/react-virtual` if not already present
3. Create `SymbolLinkingContext` for workspace panel symbol linking

**SymbolLinkingContext**:
- Scoped per workspace (created inside workspace page, not in layout)
- State: `Map<GroupColor, string>` — each color → current symbol for that group
- `GroupColor`: `'red' | 'green' | 'blue' | 'yellow' | 'purple' | null`
- Provides:
  - `getSymbol(color: GroupColor): string | undefined`
  - `setSymbol(color: GroupColor, symbol: string): void`
  - Broadcasts: when `setSymbol` called, all panels subscribed to same color re-render via context

**Acceptance criteria**:
- [ ] `react-resizable-panels` in package.json (exact version, no `^`)
- [ ] `pnpm install` succeeds, lockfile updated
- [ ] SymbolLinkingContext exports `useSymbolLinking` hook

---

#### T-39-W2-02: WorkspaceGrid with react-resizable-panels

**Type**: impl
**depends_on**: T-39-W2-01
**blocks**: T-39-W2-04
**Target files**:
- `apps/worldview-web/components/workspace/WorkspaceGrid.tsx` (new)
- `apps/worldview-web/components/workspace/WorkspacePanel.tsx` (new — distinct from old page-level component)

**What to build**:
The resizable panel grid and individual panel wrapper using `react-resizable-panels`.

**WorkspaceGrid**:
- Uses `PanelGroup` from `react-resizable-panels` with `direction="horizontal"` for columns
- Layout: 2-column default (2 `Panel` components side by side)
- Each column: `PanelGroup` with `direction="vertical"` for rows within that column
- Drag handle: `PanelResizeHandle` — style as `w-1 bg-border hover:bg-primary/60 cursor-col-resize transition-colors`
- Min size: 15% (prevents invisible panels)
- Persistence: `onLayout` callback saves sizes per workspace to `WorkspaceContext`
- Max panels: 16 (4 columns × 4 rows)
- Add panel: `[+ Add Panel]` button appears in empty slots in the grid; clicking opens `AddPanelModal`
- Empty slot: `flex items-center justify-center text-[11px] text-muted-foreground border border-dashed border-border/40`

**WorkspacePanel** (individual panel container):
- Header (24px `h-6`):
  - Left: 6px color chip (`PanelGroupSelector`) | 14px type icon | 10px uppercase type label | inline `SymbolSelector`
  - Right: fullscreen button `⊞` | close `✕`
- Content: overflow-auto, flex-1
- Border: `border border-border`
- Background: `bg-card`

**PanelGroupSelector** (color chip component):
- 6px circle, colored per group (`bg-[#EF5350]` red, `bg-[#26A69A]` green, `bg-[#3B82F6]` blue, `bg-[#FFD60A]` yellow, `bg-[#A855F7]` purple, `bg-border` unlinked)
- Click → `Popover` with 5 color options + "Unlink" row
- Select color → calls `symbolLinking.setSymbol(color, currentSymbol)` and saves color to panel config

**AddPanelModal** (dialog):
- Simple `Dialog` from shadcn
- Grid of 10 panel type cards: icon + label
- Click to add panel to workspace

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `renders-panel-group` | PanelGroup present in DOM | unit |
| `add-panel-via-modal` | Modal opens, click adds panel | unit |
| `close-panel` | Close button removes panel | unit |
| `group-color-chip-updates` | Color change broadcasts to context | unit |

**Acceptance criteria**:
- [ ] Panels are resizable by dragging the handle
- [ ] Resize handle is visible on hover (blue tint)
- [ ] Add panel modal opens and adds panel
- [ ] Panel close `✕` removes panel from grid
- [ ] Min panel size enforced (no invisible panels)

---

#### T-39-W2-03: All 10 Panel Type Widgets

**Type**: impl
**depends_on**: T-39-W2-01, T-39-W0-02, T-39-W0-03
**blocks**: T-39-W2-04
**Target files**:
- `apps/worldview-web/components/workspace/WorkspaceWatchlistWidget.tsx` (new)
- `apps/worldview-web/components/workspace/WorkspaceBriefWidget.tsx` (new)
- `apps/worldview-web/app/(app)/workspace/page.tsx` (full rewrite using new components)

**What to build**:
Complete all 10 panel type widgets. 6 already exist (Chart, Fundamentals, Graph, Alerts, News, Portfolio). Need 4 new: Screener (Wave 0), Chat (Wave 0), Watchlist, Brief.

**WorkspaceWatchlistWidget** (4 cols: Ticker/Price/Change%/MktCap, 22px rows, 30s refresh):
- Data: `GET /v1/watchlists` → first watchlist tickers → `GET /v1/quotes/batch`
- Columns: Ticker | Price | Chg% | Mkt Cap
- Row height: `h-[22px]`, font `text-[11px]`
- Click row → navigate to `/instruments/{entityId}`
- `staleTime: 30_000`

**WorkspaceBriefWidget** (morning brief, amber styling):
- Data: `GET /v1/briefings/morning`
- Background: `bg-[#F0C04018]`
- Left border: `border-l-2 border-[#FFD60A]`
- Collapsed: 1 line + `[▾]` expand button
- Expanded: full text
- If no data: `<InlineEmptyState message="Morning brief not yet generated" />`

**Workspace page rewrite** (`page.tsx`):
- Remove old single-file implementation
- Compose: `WorkspaceContext` (from Wave 1) + `SymbolLinkingContext` + `WorkspaceTabs` + `WorkspaceGrid`
- `WorkspaceGrid` receives current workspace's `panels` array from context
- Pass `panels` config to WorkspaceGrid which renders appropriate widget per panel type

**Panel type → Widget mapping** (in WorkspaceGrid `PanelContent` switch):
| type | component |
|------|-----------|
| chart | `OHLCVChart` (with `instrumentId` from symbol or demo) |
| screener | `WorkspaceScreenerWidget` |
| news | `WorkspaceNewsPanel` |
| alerts | `AlertsList` |
| chat | `WorkspaceChatWidget` |
| fundamentals | `FundamentalsTab` |
| graph | `EntityGraphPanel` |
| portfolio | `WorkspacePortfolioPanel` |
| watchlist | `WorkspaceWatchlistWidget` |
| brief | `WorkspaceBriefWidget` |

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `watchlist-widget-renders-rows` | Shows symbols when data available | unit |
| `brief-widget-amber-styling` | Has amber left border class | unit |
| `all-10-panel-types-render` | Each of 10 panel types renders without crash | unit |

**Acceptance criteria**:
- [ ] All 10 panel types render their correct widget (no placeholders)
- [ ] Watchlist widget shows live prices
- [ ] Brief widget has amber styling

---

#### T-39-W2-04: Workspace Persistence + Symbol Linking Integration

**Type**: impl
**depends_on**: T-39-W2-02, T-39-W2-03
**blocks**: Wave 3
**Target files**:
- `apps/worldview-web/contexts/WorkspaceContext.tsx` (extend from Wave 1)

**What to build**:
Complete workspace persistence including panel sizes and symbol linking state.

**Logic & Behavior**:
1. On `PanelGroup` `onLayout(sizes: number[])` callback — save sizes array to `WorkspaceContext` under `workspace.layout`
2. On mount — restore sizes from `WorkspaceContext.layout` via `PanelGroup` `defaultSize` props
3. Symbol linking: when symbol-aware panel changes symbol (via `SymbolSelector` in panel header), call `symbolLinking.setSymbol(panelColor, newSymbol)` — all panels with same color auto-update
4. Persist symbol linking map per workspace in localStorage

**Acceptance criteria**:
- [ ] Panel sizes survive browser refresh
- [ ] Named workspaces switch correctly (panels change, sizes restore)
- [ ] Symbol change in one panel propagates to same-color panels
- [ ] localStorage stores full `WorkspacePersistence` schema

---

### Wave 2 Terminal Quality Additions

**WorkspacePanel exact styling** (panel container):

```tsx
// Panel container — in gap-px grid, NO border needed (gap-px is the border)
// If rendered standalone (not in workspace grid), use border border-border
<div className="flex flex-col min-h-0 bg-card">
  {/* Panel header — 24px, ALL CAPS label, minimal chrome */}
  <div className="flex h-6 items-center border-b border-border px-2 shrink-0 gap-1.5">
    {/* Symbol linking color chip */}
    <button
      className="h-1.5 w-1.5 rounded-full shrink-0 cursor-pointer"
      style={{ backgroundColor: groupColor ?? 'hsl(var(--border))' }}
      aria-label="Set symbol group color"
    />
    {/* Panel type icon */}
    <PanelIcon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
    {/* Panel type label — 10px ALL CAPS */}
    <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
      {panelType}
    </span>
    {/* Symbol selector — inline, minimal */}
    {hasSymbol && (
      <span className="font-mono text-[11px] text-foreground ml-1 cursor-pointer hover:text-primary">
        [{currentSymbol} ▾]
      </span>
    )}
    {/* Spacer + right controls */}
    <div className="ml-auto flex items-center gap-0.5">
      <button className="h-5 w-5 flex items-center justify-center text-muted-foreground hover:text-foreground">
        <Maximize2 className="h-3 w-3" />
      </button>
      <button
        className="h-5 w-5 flex items-center justify-center text-muted-foreground hover:text-foreground"
        onClick={() => onClose(id)}
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  </div>
  {/* Content — p-0, content carries own padding */}
  <div className="flex-1 min-h-0 overflow-auto">
    <PanelContent type={type} id={id} />
  </div>
</div>
```

**WorkspaceTabs exact styling**:
```tsx
<div className="flex h-8 items-end border-b border-border bg-background px-2 gap-0 shrink-0">
  {workspaces.map(ws => (
    <button key={ws.id}
      className={cn(
        "flex items-center h-full px-3 gap-1.5 text-xs border-b-2",
        "transition-colors duration-0",
        ws.id === activeId
          ? "border-primary text-foreground"
          : "border-transparent text-muted-foreground hover:text-foreground"
      )}
      onDoubleClick={() => startRename(ws.id)}
    >
      {ws.id === renamingId
        ? <input autoFocus className="bg-transparent text-xs w-[80px] outline-none border-b border-primary" />
        : <span>{ws.name}</span>
      }
      <X className="h-3 w-3 text-muted-foreground/60 hover:text-muted-foreground ml-0.5" onClick={...} />
    </button>
  ))}
  <button className="flex items-center h-full px-2 text-[10px] text-muted-foreground hover:text-foreground gap-0.5">
    <Plus className="h-3 w-3" />
    <span className="uppercase tracking-[0.08em]">WORKSPACE</span>
  </button>
</div>
```

**Drag resize handle** (PanelResizeHandle):
```tsx
<PanelResizeHandle className={cn(
  "w-px bg-border relative",
  "after:absolute after:inset-y-0 after:-left-1 after:-right-1 after:content-['']",
  "hover:bg-primary/60 hover:w-px",
  "data-[resize-handle-active]:bg-primary/80",
  "transition-colors duration-0"  // instant, not animated
)} />
```

### Wave 2 Validation Gate
- [x] `pnpm run typecheck` exits 0
- [x] `pnpm run lint` exits 0
- [x] `pnpm test` — all tests pass (359)
- [ ] Visual: 4 default workspace presets visible in tabs
- [ ] Visual: panel drag-to-resize works (handle turns primary on hover)
- [ ] Visual: all 10 panel types render correct content
- [ ] **Terminal quality**: Panel headers are exactly 24px (h-6)
- [ ] **Terminal quality**: Panel type labels are 10px ALL CAPS
- [ ] **Terminal quality**: workspace grid uses `gap-px` — 1px seam visible between panels
- [ ] **Terminal quality**: `grep -rn "shadow-\|rounded-lg\|rounded-xl" apps/worldview-web/components/workspace/` returns 0

### Wave 2 Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `__tests__/workspace.test.tsx` | Full page rewrite — old test structure invalid | Rewrite tests against new WorkspaceGrid + WorkspaceTabs structure |

---

## Wave 3 ✅ — Screener Full Redesign

**Status**: **DONE** — 2026-04-25 · 367 tests pass · lint + typecheck clean

**Goal**: 12-column screener with virtual scroll and collapsible filter bar.
**Depends on**: Wave 1 (parallel with Wave 2+)
**Estimated effort**: 3-5 hours
**Architecture layer**: UI application

### Pre-read (agent must read before starting)
- `apps/worldview-web/app/(app)/screener/page.tsx` — current screener
- `apps/worldview-web/components/screener/HeatCell.tsx` — existing change% cell

### Tasks

#### T-39-W3-01: 12-Column ScreenerTable with Virtual Scroll

**Type**: impl
**depends_on**: T-39-W0-04
**blocks**: none
**Target files**:
- `apps/worldview-web/components/screener/ScreenerTable.tsx` (new)
- `apps/worldview-web/components/screener/ScreenerFilterBar.tsx` (new)
- `apps/worldview-web/app/(app)/screener/page.tsx` (rewrite)

**What to build**:
New 12-column screener table per PRD §7.

**Columns** (from PRD §7.1):
| Column | Width | Format |
|--------|-------|--------|
| Ticker | 70px | `font-mono text-left` |
| Name | 160px | `truncate text-left` |
| Sector | 100px | `truncate text-left` |
| Price | 80px | `font-mono text-right` |
| Change% | 70px | HeatCell |
| Mkt Cap | 80px | `font-mono text-right` abbreviated |
| P/E | 60px | `font-mono text-right` |
| Revenue | 80px | `font-mono text-right` (show `—` if missing) |
| Beta | 55px | `font-mono text-right` (show `—` if missing) |
| Score | 70px | Progress bar |
| 52W Range | 100px | Mini range bar (CSS only — `div` with fill position) |
| Volume | 80px | `font-mono text-right` |

**Virtual scroll**: Use `@tanstack/react-virtual` — `useVirtualizer` with `count: results.length, estimateSize: () => 22, overscan: 10`

**ScreenerFilterBar** (collapsible per T-39-W0-04 pattern):
- Filters: ticker search | Sector dropdown | Cap dropdown | Score range | Apply
- Default: collapsed
- Animation: `grid-template-rows: 0fr → 1fr`
- Filter state → applied to query params of `screenEntities` call

**Page layout**:
```
[⚡ SCREENER] [N results]           [Filters ▾] [Reset] [Export ↓]
─────────────────────────────────────────────────────────
[filter bar — collapsible]
─────────────────────────────────────────────────────────
[table header row — sticky]
[virtual-scrolled rows]
```

**Row height**: 22px (`estimateSize: () => 22`)
**Header alignment**: MUST match data alignment (e.g., Price column header `text-right`)
**Sort**: click column header → cycle ascending/descending/none; active sort: `↑`/`↓` icon in header

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `renders-12-column-headers` | All 12 column headers present | unit |
| `sort-by-change-pct` | Click Change% header toggles sort | unit |
| `filter-bar-toggle` | Filter bar collapses on button click | unit |
| `missing-fields-show-dash` | Revenue/Beta null → `—` | unit |
| `row-click-navigates` | Row click → router.push with entityId | unit |

**Acceptance criteria**:
- [ ] 12 column headers visible at 1440px width
- [ ] Row height 22px
- [ ] Virtual scroll renders large result sets without freeze
- [ ] Filter bar collapses/expands
- [ ] Revenue/Beta show `—` when missing (with tooltip "Backend pending")
- [ ] Sort by any column works

---

### Wave 3 Terminal Quality Additions

**ScreenerTable exact styling spec**:

```tsx
// Table container — NO card/shadow, flush to content area
<div className="flex flex-col min-h-0 overflow-hidden">
  {/* Section header — filter toggle row */}
  <div className="flex h-9 items-center justify-between border-b border-border px-2 shrink-0">
    <div className="flex items-center gap-2">
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        SCREENER
      </span>
      <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
        {totalResults} results
      </span>
    </div>
    <div className="flex items-center gap-1">
      <button className="text-[10px] text-muted-foreground hover:text-foreground font-mono">
        {filtersOpen ? "Filters ▴" : "Filters ▾"}
      </button>
      <button className="text-[10px] text-muted-foreground hover:text-foreground">Reset</button>
      <button className="text-[10px] text-muted-foreground hover:text-foreground">Export ↓</button>
    </div>
  </div>

  {/* Collapsible filter bar */}
  <div className="grid overflow-hidden border-b border-border transition-[grid-template-rows] duration-200 ease-out"
       style={{ gridTemplateRows: filtersOpen ? '1fr' : '0fr' }}>
    <div className="overflow-hidden min-h-0">
      <div className="flex h-9 items-center gap-2 px-2 bg-background">
        {/* filter inputs — h-7, text-[11px], rounded-[2px], border border-border */}
        <input placeholder="Ticker/name..." className="h-7 px-2 text-[11px] font-mono bg-background border border-border rounded-[2px] text-foreground placeholder:text-muted-foreground/60 focus-visible:ring-1 focus-visible:ring-primary focus-visible:ring-offset-0 w-32" />
        {/* sector, cap, score selects */}
      </div>
    </div>
  </div>

  {/* Sticky column headers — ALL CAPS, alignment mirrors data */}
  <div className="flex items-center h-[22px] border-b border-border bg-card sticky top-0 z-10 px-0">
    <span className="w-[70px] px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left shrink-0">TICKER</span>
    <span className="w-[160px] px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left shrink-0">NAME</span>
    <span className="w-[100px] px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left shrink-0">SECTOR</span>
    <span className="w-[80px] px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right shrink-0">PRICE</span>
    <span className="w-[70px] px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right shrink-0">CHG%</span>
    <span className="w-[80px] px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right shrink-0">MKT CAP</span>
    <span className="w-[60px] px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right shrink-0">P/E</span>
    <span className="w-[80px] px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right shrink-0">REVENUE</span>
    <span className="w-[55px] px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right shrink-0">BETA</span>
    <span className="w-[70px] px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right shrink-0">SCORE</span>
    <span className="w-[100px] px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-center shrink-0">52W RANGE</span>
    <span className="w-[80px] px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right shrink-0">VOLUME</span>
  </div>

  {/* Virtual rows — 22px each */}
  <div ref={parentRef} className="flex-1 overflow-auto">
    <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative' }}>
      {rowVirtualizer.getVirtualItems().map(vRow => {
        const row = rows[vRow.index];
        return (
          <div key={vRow.index}
            style={{ position: 'absolute', top: vRow.start, width: '100%', height: 22 }}
            className="flex items-center border-b border-border/30 hover:bg-muted/40 cursor-pointer"
            onClick={() => router.push(`/instruments/${row.entity_id}`)}
          >
            <span className="w-[70px] px-2 font-mono text-[11px] tabular-nums text-primary shrink-0">{row.ticker}</span>
            <span className="w-[160px] px-2 text-[11px] text-foreground truncate shrink-0">{row.name}</span>
            <span className="w-[100px] px-2 text-[11px] text-muted-foreground truncate shrink-0">{row.sector ?? '—'}</span>
            <span className="w-[80px] px-2 font-mono text-[11px] tabular-nums text-foreground text-right shrink-0">{row.price ?? '—'}</span>
            {/* HeatCell for change% */}
            <div className="w-[70px] px-2 shrink-0"><HeatCell value={row.daily_return} /></div>
            <span className="w-[80px] px-2 font-mono text-[11px] tabular-nums text-foreground text-right shrink-0">{fmtCap(row.market_cap)}</span>
            <span className="w-[60px] px-2 font-mono text-[11px] tabular-nums text-foreground text-right shrink-0">{row.pe_ratio?.toFixed(1) ?? '—'}</span>
            <span className="w-[80px] px-2 font-mono text-[11px] tabular-nums text-muted-foreground text-right shrink-0" title="Backend pending">—</span>
            <span className="w-[55px] px-2 font-mono text-[11px] tabular-nums text-muted-foreground text-right shrink-0" title="Backend pending">—</span>
            {/* Score bar */}
            <div className="w-[70px] px-2 shrink-0">
              <div className="h-1 bg-border rounded-none overflow-hidden">
                <div className="h-full bg-primary/40" style={{ width: `${row.score}%` }} />
              </div>
            </div>
            {/* 52W range bar */}
            <div className="w-[100px] px-2 shrink-0">...</div>
            <span className="w-[80px] px-2 font-mono text-[11px] tabular-nums text-foreground text-right shrink-0">{fmtVol(row.volume)}</span>
          </div>
        );
      })}
    </div>
  </div>
</div>
```

### Wave 3 Validation Gate
- [x] `pnpm run typecheck` exits 0
- [x] `pnpm run lint` exits 0
- [x] `pnpm test` — all screener tests pass (367 total)
- [ ] Visual: 12 columns visible in browser at 1440px
- [ ] Visual: rows are exactly 22px high (verify with DevTools)
- [ ] **Terminal quality**: ALL column headers are 10px uppercase
- [ ] **Terminal quality**: ALL number columns header alignment = text-right (matching data)
- [ ] **Terminal quality**: Ticker column uses `text-primary` (not text-foreground) — tickers are interactive
- [ ] **Terminal quality**: Revenue and Beta columns show `—` with muted color + tooltip
- [ ] **Terminal quality**: `grep -rn "shadow-\|rounded-lg\|rounded-xl\|rounded-md\|p-4\|p-6" apps/worldview-web/app/\(app\)/screener/` returns 0

### Wave 3 Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `__tests__/screener.test.tsx` | Column count changed from 7 to 12 | Update column count assertion; add new column tests |

---

## Wave 4 ✅ — Portfolio Full Redesign

**Status**: **DONE** — 2026-04-25 · 367 tests pass · lint + typecheck clean

**Goal**: 4-tab portfolio with 9-col holdings table, sector allocation, transactions (+ DIVIDEND), watchlists (multi-tab), and brokerages.
**Depends on**: Wave 1 (parallel with Waves 2, 3, 5)
**Estimated effort**: 6-8 hours
**Architecture layer**: UI application + gateway fix

### Pre-read (agent must read before starting)
- `apps/worldview-web/app/(app)/portfolio/page.tsx` — current portfolio
- `apps/worldview-web/lib/gateway.ts` — transaction mapping (find DIVIDEND gap)
- `docs/specs/0031-terminal-ui-v3-ground-up-redesign.md` §8 — full portfolio spec

### Tasks

#### T-39-W4-01: KPI Strip + Holdings Tab (SemanticHoldingsTable + SectorAllocation)

**Type**: impl
**depends_on**: none
**blocks**: T-39-W4-04
**Target files**:
- `apps/worldview-web/components/portfolio/PortfolioKPIStrip.tsx` (new)
- `apps/worldview-web/components/portfolio/SemanticHoldingsTable.tsx` (new)
- `apps/worldview-web/components/portfolio/SectorAllocationPanel.tsx` (new)

**What to build**:
KPI strip (6 tiles) + semantic holdings table (`<table>`) + dual sector allocation bar chart.

**PortfolioKPIStrip** (6 tiles):
- Tiles: Total Value | Day P&L | Unrealised P&L | Top Gainer | Top Loser | # Positions
- Layout: `flex divide-x divide-border`
- Each tile: `flex-1 flex flex-col px-4 py-2`
- Value: `text-base font-mono tabular-nums` (16px)
- Label: `text-[10px] uppercase text-muted-foreground`
- P&L values: `text-positive` if positive, `text-negative` if negative — NEVER `text-primary`
- Top Gainer: ticker + P&L% (highest unrealised P&L%) — always `text-positive`
- Top Loser: ticker + P&L% (lowest unrealised P&L%) — always `text-negative`
- Computed from holdings data + live quotes

**SemanticHoldingsTable** (9 columns):
- Element: `<table>` (NOT divs — semantic HTML required)
- Columns: Ticker | Name | Qty | Avg Cost | Current | P&L$ | P&L% | Value | Sector
- **Missing 10th column for Weight**: add as 10th: Weight (computed client-side: `value / totalValue × 100`)
- Row height: 22px (`h-[22px]`)
- Font: `text-[11px] font-mono tabular-nums` for numbers, `text-[11px]` for text
- Sector column: fetch `fundamentals/{instrumentId}` per holding (mount-time, `sessionStorage` cache)
- P&L$: `(current - avg_cost) × qty` colored positive/negative
- Sort: default by P&L% descending; click header to resort
- Sticky total row at bottom: `border-t-2 border-border font-semibold`
- Row click: navigate to `/instruments/{entityId}`
- `Export CSV` button: generates and downloads CSV of all 10 columns

**SectorAllocationPanel** (dual bar chart):
- Two horizontal bar charts side-by-side: By GICS Sector + By Asset Type
- Each bar: `bg-positive/30` fill for positive sectors; sector name + percentage label
- Computed from SemanticHoldingsTable data: group by `gics_sector`, sum `value` per sector, divide by total
- By Type: equity/cash/options (use holding type from portfolio data)
- Empty: `<InlineEmptyState message="Sector data loading from fundamentals..." />`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `kpi-strip-shows-6-tiles` | 6 KPI tiles present | unit |
| `pnl-color-not-primary` | P&L value does NOT have text-primary class | unit |
| `holdings-table-is-table-element` | Root is `<table>` not `<div>` | unit |
| `holdings-10-columns` | All 10 column headers present | unit |
| `sector-bar-computed` | Sector allocation from holdings data | unit |

**Acceptance criteria**:
- [ ] 6 KPI tiles with correct labels
- [ ] P&L values never use `text-primary`
- [ ] Holdings uses `<table>` element
- [ ] Sector allocation renders bars
- [ ] Row height 22px verified in tests

---

#### T-39-W4-02: Transactions Tab (+ DIVIDEND gateway fix)

**Type**: impl
**depends_on**: none
**blocks**: T-39-W4-04
**Target files**:
- `apps/worldview-web/components/portfolio/TransactionsTable.tsx` (new)
- `apps/worldview-web/lib/gateway.ts` (add DIVIDEND mapping)

**What to build**:
Transactions table with BUY/SELL/DIVIDEND filter, date range, and gateway DIVIDEND fix.

**Gateway fix** (`gateway.ts` — transaction type mapping):
```typescript
// In the transaction mapping function:
if (s1Tx.type === 'DIVIDEND') {
  return { ...mapped, type: 'DIVIDEND' as const, qty: null, price: null };
}
```
Find the function that maps S1 transactions → frontend transactions and add this branch.

**TransactionsTable**:
- Columns: Date | Type badge | Ticker | Qty | Price | Total | Fee (7 columns)
- Row height: 22px
- Filter bar: `[All] [BUY] [SELL] [DIVIDEND]` segmented control + date dropdown + ticker dropdown
- Type badge colors: BUY = `bg-positive/20 text-positive`, SELL = `bg-negative/20 text-negative`, DIV = `bg-primary/20 text-primary`
- DIVIDEND rows: Qty and Price show `—`
- Pagination: "Load 100 more" button at bottom (not full virtual scroll — transactions are bounded by brokerage data)
- Sort: newest-first default

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `shows-dividend-type` | DIVIDEND transaction shows DIV badge | unit |
| `dividend-qty-is-dash` | DIVIDEND row Qty column shows `—` | unit |
| `filter-buy-only` | BUY filter hides SELL and DIVIDEND rows | unit |
| `gateway-maps-dividend` | Gateway function maps DIVIDEND type | unit |

**Acceptance criteria**:
- [ ] DIVIDEND transactions visible in table
- [ ] Gateway maps DIVIDEND type without crashing
- [ ] Type filter works for all 3 types
- [ ] `pnpm run typecheck` exits 0 after gateway change

---

#### T-39-W4-03: Watchlists + Brokerages Tabs

**Type**: impl
**depends_on**: none
**blocks**: T-39-W4-04
**Target files**:
- `apps/worldview-web/components/portfolio/WatchlistsTabPanel.tsx` (new)
- `apps/worldview-web/components/portfolio/BrokerageConnectionCard.tsx` (new)

**What to build**:
Multi-watchlist tab panel and brokerage connection cards per PRD §8.5, §8.6.

**WatchlistsTabPanel**:
- Tab per watchlist: `[Tech Stocks] [Earnings Watch] [+ New Watchlist]`
- `[+ New Watchlist]`: opens name dialog → POST `/v1/watchlists` → add tab
- Search bar (36px): type to search via `GET /v1/search?q=X` → dropdown → click to add member
- Per-row `×` remove button (appears on hover)
- Columns: Ticker | Name | Price | Change% | Mkt Cap | 52W Range | Date Added
- 52W Range: mini horizontal bar — position of current price within 52w range
- Live prices: `GET /v1/quotes/batch` with tab's tickers, `staleTime: 30_000`
- Mkt Cap + 52W from `fundamentals/{id}`, cached in `sessionStorage`
- Edit mode (`[Edit ✎]`): rename watchlist inline + `[Delete watchlist]` button
- Empty: `<InlineEmptyState message="Search above to add your first symbol." />`

**BrokerageConnectionCard**:
- Status badges: `● ACTIVE` (positive), `● PENDING` (warning), `● ERROR` (negative), `● DISCONNECTED` (muted)
- Actions: `[Sync Now]` → POST + spinner; `[Sync Errors (N)]` → inline expand; `[Disconnect]` → confirm + DELETE
- Error expansion: inline list of `error_type + error_detail` per sync error
- Stats footer: "Holdings: N | Transactions: N | Connected: [date]"
- Empty state (no connections): `<InlineEmptyState>` + `[+ Connect Brokerage]` CTA
- Reuse existing `ConnectBrokerageModal` component for the connect flow

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `watchlists-tab-per-watchlist` | One tab per watchlist | unit |
| `add-watchlist` | New watchlist button creates tab | unit |
| `brokerage-status-active` | Active status shows positive color | unit |
| `sync-errors-expand` | Click errors → inline list visible | unit |

**Acceptance criteria**:
- [ ] Multi-tab watchlists with search-to-add
- [ ] Brokerage cards show status badges
- [ ] Sync errors expand inline
- [ ] Empty states are inline (no full-page empties)

---

#### T-39-W4-04: Portfolio Page Assembly

**Type**: impl
**depends_on**: T-39-W4-01, T-39-W4-02, T-39-W4-03
**blocks**: Wave 6
**Target files**:
- `apps/worldview-web/app/(app)/portfolio/page.tsx` (rewrite)

**What to build**:
Assemble the 4-tab portfolio page with KPI strip.

**Layout**:
```
Page title: PORTFOLIO + [+ Manual Entry] button
─────────────────────────────────────────────
PortfolioKPIStrip (6 tiles)
─────────────────────────────────────────────
Tab bar: [Holdings] [Transactions] [Watchlists] [Brokerages]
─────────────────────────────────────────────
Tab content area
```

Use shadcn `Tabs` component with `TabsList` + `TabsTrigger` + `TabsContent`.

**Acceptance criteria**:
- [ ] All 4 tabs switch correctly
- [ ] KPI strip always visible above tabs
- [ ] `pnpm test` portfolio tests pass

---

### Wave 4 Terminal Quality Additions

**PortfolioKPIStrip exact styling**:
```tsx
// 6 KPI tiles — divide-x creates 1px vertical separators between tiles
<div className="flex divide-x divide-border border-b border-border">
  {KPI_TILES.map(tile => (
    <div key={tile.id} className="flex flex-col px-3 py-1.5 flex-1 min-w-0">
      {/* Label: 10px ALL CAPS muted */}
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground truncate">
        {tile.label}
      </span>
      {/* Value: 14px mono (NOT 16px — reduces strip height impact) */}
      <span className={cn(
        "font-mono text-[14px] tabular-nums font-medium",
        tile.isPositive ? "text-positive" : tile.isNegative ? "text-negative" : "text-foreground"
      )}>
        {tile.value}
      </span>
    </div>
  ))}
</div>
```

**SemanticHoldingsTable exact styling**:
```tsx
// MUST be a real <table> element — not divs
<table className="w-full border-collapse text-[11px]">
  <thead className="sticky top-0 bg-card z-10">
    <tr className="h-[22px] border-b border-border">
      {/* ALL CAPS column headers, alignment mirrors data */}
      <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">TICKER</th>
      <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">NAME</th>
      <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">QTY</th>
      <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">AVG COST</th>
      <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">CURRENT</th>
      <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">P&L $</th>
      <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">P&L %</th>
      <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">VALUE</th>
      <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">WEIGHT</th>
      <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">SECTOR</th>
    </tr>
  </thead>
  <tbody className="divide-y divide-border/30">
    {holdings.map(h => (
      <tr key={h.holding_id}
        className="h-[22px] hover:bg-muted/40 cursor-pointer"
        onClick={() => router.push(`/instruments/${h.entity_id}`)}
      >
        <td className="px-2 font-mono text-[11px] tabular-nums text-primary">{h.ticker}</td>
        <td className="px-2 text-[11px] text-foreground max-w-[120px] truncate">{h.name}</td>
        <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">{h.quantity}</td>
        <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">{fmtPrice(h.avg_cost)}</td>
        <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">{fmtPrice(h.current_price)}</td>
        <td className={cn("px-2 font-mono text-[11px] tabular-nums text-right",
          pnl >= 0 ? "text-positive" : "text-negative")}>{fmtPnl(pnl)}</td>
        <td className={cn("px-2 font-mono text-[11px] tabular-nums text-right",
          pnlPct >= 0 ? "text-positive" : "text-negative")}>{fmtPct(pnlPct)}</td>
        <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">{fmtPrice(value)}</td>
        <td className="px-2 font-mono text-[11px] tabular-nums text-muted-foreground text-right">{fmtPct(weight)}</td>
        <td className="px-2 text-[11px] text-muted-foreground">{h.sector ?? '—'}</td>
      </tr>
    ))}
  </tbody>
  {/* Total row — structural border-t-2 is the one allowed exception */}
  <tfoot>
    <tr className="h-[22px] border-t-2 border-border">
      <td colSpan={5} className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground">TOTAL</td>
      <td className={cn("px-2 font-mono text-[11px] tabular-nums text-right font-semibold",
        totalPnl >= 0 ? "text-positive" : "text-negative")}>{fmtPnl(totalPnl)}</td>
      <td className={cn("px-2 font-mono text-[11px] tabular-nums text-right font-semibold",
        totalPnlPct >= 0 ? "text-positive" : "text-negative")}>{fmtPct(totalPnlPct)}</td>
      <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right font-semibold">{fmtPrice(totalValue)}</td>
      <td colSpan={2} />
    </tr>
  </tfoot>
</table>
```

### Wave 4 Validation Gate
- [ ] `pnpm run typecheck` exits 0
- [ ] `pnpm run lint` exits 0
- [ ] `pnpm test` — all portfolio tests pass
- [ ] Visual: 4 tabs visible; KPI strip shows 6 tiles
- [ ] Visual: Holdings tab shows `<table>` with 10 columns (10th = Sector)
- [ ] **Terminal quality**: KPI strip values use `text-[14px] font-mono tabular-nums`
- [ ] **Terminal quality**: `text-primary` does NOT appear in KPI value spans (only in ticker column)
- [ ] **Terminal quality**: Holdings `<table>` uses `border-collapse`, not divs
- [ ] **Terminal quality**: Holdings `<thead>` is sticky, background is `bg-card`
- [ ] **Terminal quality**: All `<th>` elements use `text-[10px] uppercase tracking-[0.08em] font-normal`
- [ ] **Terminal quality**: `grep -rn "shadow-\|rounded-lg\|rounded-xl\|rounded-md" apps/worldview-web/components/portfolio/` returns 0

### Wave 4 Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `__tests__/portfolio.test.tsx` | Holdings table structure changed | Update column count assertions; add SemanticHoldingsTable tests |
| `__tests__/portfolio-stale.test.tsx` | If portfolio page structure changes | Review and update selector queries |
| `__tests__/brokerage.test.tsx` | BrokerageConnectionCard is new component | Update to test new card structure |
| `apps/worldview-web/__tests__/portfolio-stale-indicator.test.tsx` | May rely on old structure | Review and update |

---

## Wave 5 — Instrument Detail Refinement

**Goal**: 56px split header with description, InstrumentAISubheader (replaces Brief tab), 5-zone overview, Fundamentals 9 sections, News/Intelligence enhancements.
**Depends on**: Wave 1 (parallel with Waves 2, 3, 4)
**Estimated effort**: 8-10 hours
**Architecture layer**: UI application
**Status**: DONE — 2026-04-25 · 376 tests pass (29 in instrument-detail.test.tsx including 10 new Wave 5 tests)

### Pre-read (agent must read before starting)
- `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx` — full read (current instrument detail)
- `apps/worldview-web/components/instrument/FundamentalsTab.tsx` — current fundamentals
- `apps/worldview-web/components/instrument/IntelligenceTab.tsx` — current intelligence tab
- `docs/specs/0031-terminal-ui-v3-ground-up-redesign.md` §9 — full instrument spec

### Tasks

#### T-39-W5-01: CompactInstrumentHeader + InstrumentAISubheader

**Type**: impl
**depends_on**: T-39-W0-05
**blocks**: T-39-W5-03
**Target files**:
- `apps/worldview-web/components/instrument/CompactInstrumentHeader.tsx` (new)
- `apps/worldview-web/components/instrument/InstrumentAISubheader.tsx` (new)

**What to build**:
New 56px two-row instrument header (replacing the existing header) and sticky amber AI subheader.

**CompactInstrumentHeader** (56px total — 2×28px rows):
- Row 1 (28px): `[←] [AAPL] [NASDAQ] [Technology] — right side: [$172.34 ▲ +1.23 (+0.72%)] [● LIVE 14:32]`
- Row 2 (28px, split): Left ~60% = stats strip (MKT CAP │ P/E │ EPS │ 52W │ VOL); Right ~40% = description truncated + `Read more →`
- "Read more →": click expands third row inline (transition with `grid-rows`); `[Close ▴]` to collapse
- Description source: `GET /v1/entities/{entityId}` → `description` field
- Stats data: from `fundamentals/{instrumentId}` — formatted with abbreviation
- Stats separator: `│` (not a border — just a character)
- Back nav `[←]`: calls `router.back()`
- Exchange/sector badges: `rounded-[2px] bg-muted/40 text-[10px] font-mono`

**InstrumentAISubheader**:
- Component: sticky bar between header and tab bar; `position: sticky; top: 0` if header scrolls, or just positioned below header
- Background: `bg-[#F0C04018]`
- Left border: `border-l-2 border-[#FFD60A]`
- Collapsed: 36px height, 1-line preview with `[▾]` toggle
- Expanded: `auto` height, full brief text + `[▴]`
- State: `sessionStorage` keyed by `entityId` (resets on close)
- Data source: instrument-specific brief if available (`/v1/briefings/morning` entity mention), else morning brief fallback

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `header-two-rows` | Two rows in header DOM | unit |
| `description-read-more` | Click Read more → expands | unit |
| `ai-subheader-amber-border` | Has amber left border class | unit |
| `ai-subheader-toggle` | Click ▾ expands, click ▴ collapses | unit |
| `sessionStorage-persists-expanded` | State saved to sessionStorage | unit |

**Acceptance criteria**:
- [ ] Header is 56px total height
- [ ] Description visible in row 2 right column
- [ ] "Read more →" expands inline (no modal)
- [ ] InstrumentAISubheader is amber-styled and sticky

---

#### T-39-W5-02: Overview Tab — 5-Zone Layout + SessionStatsStrip

**Type**: impl
**depends_on**: T-39-W0-05
**blocks**: T-39-W5-03
**Target files**:
- `apps/worldview-web/components/instrument/OverviewLayout.tsx` (new)
- `apps/worldview-web/components/instrument/InstrumentKeyMetrics.tsx` (new)
- `apps/worldview-web/components/instrument/InstrumentTopNews.tsx` (new)

**What to build**:
5-zone Overview tab layout per PRD §9.4.

**OverviewLayout** (zones):
1. **Chart** (full width, 300px min height): existing `OHLCVChart` component — pass last OHLCV bar data to `SessionStatsStrip`
2. **SessionStatsStrip** (full width, 20px): `O | H | L | V | VWAP` from last OHLCV bar (component from T-39-W0-05)
3. **Timeframe bar** (full width, 28px): `[1D] [5D] [1M] [3M] [6M] [1Y] [2Y] [5Y]` — active: `bg-primary/15 text-primary`; inactive: `text-muted-foreground`
4. **3-column lower section** (grid: 3/10 + 3/10 + 4/10 columns):
   - Left 3 cols: `InstrumentKeyMetrics`
   - Center 3 cols: `InstrumentTopNews`
   - Right 4 cols: `EntityGraphPanel` (existing — reuse)

**InstrumentKeyMetrics** (6 metrics):
- Source: `GET /v1/fundamentals/{instrumentId}`
- Metrics: Market Cap | P/E Ratio | EPS (TTM) | Dividend Yield | 52W Hi/Lo | Beta
- Row height: 22px; label 10px uppercase `text-muted-foreground`, value 11px mono right-aligned
- Show `—` for missing fields

**InstrumentTopNews** (top 4 articles):
- Source: `GET /v1/news/entity/{entityId}` sorted by `market_impact_score` desc, limit 4
- Format: `[TIER] Title truncated  time`
- Tier badge: `HI/MED/LO` in `rounded-[2px]`
- Row height: 22px
- `→ More news` link navigates to News tab (use tab switching callback)
- `staleTime: 60_000`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `overview-5-zones` | Chart, session strip, timeframe bar, 3-col lower all present | unit |
| `timeframe-default-1d` | 1D button is active by default | unit |
| `key-metrics-6-items` | 6 metric rows in key metrics section | unit |
| `top-news-4-articles` | Max 4 articles shown | unit |
| `session-strip-from-ohlcv` | Strip receives last bar data (not quote) | unit |

**Acceptance criteria**:
- [ ] 5 zones visible in Overview tab
- [ ] SessionStatsStrip shows O/H/L/V/VWAP
- [ ] Timeframe bar updates chart on click
- [ ] 3-column lower section renders all 3 zones

---

#### T-39-W5-03: Remove Brief Tab + Enhanced Fundamentals/News/Intelligence

**Type**: impl
**depends_on**: T-39-W5-01, T-39-W5-02
**blocks**: Wave 6
**Target files**:
- `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx` (rewrite)
- `apps/worldview-web/components/instrument/FundamentalsTab.tsx` (major enhancement)
- `apps/worldview-web/components/instrument/IntelligenceTab.tsx` (enhancement)
- `apps/worldview-web/components/instrument/AnalystConsensusStrip.tsx` (new)
- `apps/worldview-web/components/instrument/RevenueTrendSparklines.tsx` (new)

**What to build**:

**Instrument page restructure**:
- Remove "Brief" tab from `TabsList`
- Tab order: `[Overview] [Fundamentals] [News] [Intelligence]`
- Insert `<InstrumentAISubheader>` between header and `<Tabs>` (sticky)
- Replace old header with `<CompactInstrumentHeader>`

**Enhanced FundamentalsTab** (9 sections per PRD §9.5):
Sections in order: Analyst Consensus → Revenue Trend → Valuation → Profitability → Growth → Dividends → Balance Sheet → Debt & Credit → Cash Flow

**AnalystConsensusStrip** (new component, shown at top of Fundamentals):
- Layout: consensus rating bar (proportional fill: green = Buy%, grey = Hold%, red = Sell%) + "N analysts"
- Price target: high / median / low
- EPS estimate: `$6.84 ↑` — revision arrows `↑` in `text-positive`, `↓` in `text-negative`
- Data: from `GET /v1/fundamentals/{instrumentId}` — use available fields; show `N/A` if missing
- `StaleDataBadge` if fundamentals > 7 days old

**RevenueTrendSparklines** (new component):
- 4 quarterly bars (Q3→Q4→Q1→Q2(E)) as mini horizontal bar chart
- Bar width proportional to revenue value
- QoQ change + YoY change displayed as text alongside bars
- Estimate quarter: `bg-muted/30` row background

**Valuation section enhancement** (existing section):
- Add "vs Sector" column: show sector average P/E etc. in `text-[10px] text-muted-foreground` inline after each metric
- Data: if sector peer data not available from S9, show `—` in "vs Sector" column with tooltip "Sector benchmarks in development"

**Debt & Credit section** (new):
- Interest Coverage ratio: > 5× = `text-positive`, 2.5–5× = `text-warning`, < 2.5× = `text-negative`
- Net Debt/EBITDA: negative = `text-positive` (net cash)
- Debt maturity (< 1Y, 1–3Y): from fundamentals if available, else `—`
- Credit Rating: if available from EODHD, else `—`

**Cash Flow section** (new):
- Operating CF, CapEx, FCF (= OpCF − CapEx), FCF Margin, Cash Conversion
- FCF Margin > 20% = `text-positive`

**News tab** (existing, enhanced):
- Add date range filter dropdown: `[All time] [Today] [Past Week] [Past Month]`
- Add sentiment filter dropdown: `[All] [Positive (>0.65)] [Negative (<0.35)] [Neutral]`
- Filters applied client-side on fetched articles
- Existing compact row format remains; ensure row height 22px

**Intelligence tab** (existing, enhanced):
- Add temporal histogram (30px height, weekly buckets): `div` bars proportional to signal count per week; hover → filters list to that week
- Add severity count strip: `HIGH N │ MEDIUM N │ LOW N` — clickable, filters below
- Add `[DEEP] [MED] [LIGHT]` processing tier badges per row (from `routing_tier` field)
- Add `[NEW] [DUP]` novelty badges per row (from `novelty_score`: > 0.85 = NEW, < 0.40 = DUP)
- Add expanded row detail (click `[▾]`): full claim text + source + confidence + novelty score + `[View source ↗]`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `no-brief-tab` | Brief TabsTrigger does NOT exist | unit |
| `4-tabs-remain` | Overview/Fundamentals/News/Intelligence present | unit |
| `analyst-consensus-strip` | AnalystConsensusStrip renders | unit |
| `debt-credit-section` | Debt & Credit section present in Fundamentals | unit |
| `cash-flow-section` | Cash Flow section present | unit |
| `news-filters` | Date and sentiment filters present | unit |
| `intelligence-severity-strip` | HIGH/MEDIUM/LOW count strip present | unit |

**Acceptance criteria**:
- [ ] Brief tab does NOT exist (verified by RTL test)
- [ ] InstrumentAISubheader visible between header and tabs
- [ ] Fundamentals has 9 sections (Analyst Consensus through Cash Flow)
- [ ] Intelligence has temporal histogram + severity strip + tier badges
- [ ] News has date + sentiment filter dropdowns

---

### Wave 5 Terminal Quality Additions

**CompactInstrumentHeader exact styling**:
```tsx
<header className="border-b border-border bg-card shrink-0">
  {/* Row 1 — 28px: nav + symbol + exchange + price */}
  <div className="flex items-center h-7 px-2 gap-2">
    <button className="text-muted-foreground hover:text-foreground" onClick={router.back}>
      <ChevronLeft className="h-4 w-4" />
    </button>
    <span className="font-mono text-[13px] font-semibold text-foreground">{ticker}</span>
    <span className="font-mono text-[10px] tabular-nums rounded-[2px] bg-muted/40 px-1 text-muted-foreground">{exchange}</span>
    <span className="text-[10px] text-muted-foreground">{sector}</span>
    {/* Push price to right */}
    <div className="ml-auto flex items-center gap-2">
      <span className="font-mono text-[14px] tabular-nums text-foreground font-medium">{price}</span>
      <span className={cn("font-mono text-[11px] tabular-nums",
        change >= 0 ? "text-positive" : "text-negative")}>
        {change >= 0 ? "▲" : "▼"} {Math.abs(change).toFixed(2)} ({Math.abs(changePct).toFixed(2)}%)
      </span>
      <LiveQuoteBadge />
    </div>
  </div>

  {/* Row 2 — 28px: stats strip LEFT + description RIGHT */}
  <div className="flex items-center h-7 px-2 gap-0 border-t border-border/50">
    {/* Left ~60%: stats strip — pipe-separated, 10px mono */}
    <div className="flex items-center gap-0 text-[10px] font-mono tabular-nums text-muted-foreground flex-shrink-0 mr-auto">
      <span className="px-0">MKT CAP <span className="text-foreground">{mktCap}</span></span>
      <span className="px-1.5 text-border">│</span>
      <span>P/E <span className="text-foreground">{pe}</span></span>
      <span className="px-1.5 text-border">│</span>
      <span>EPS <span className="text-foreground">{eps}</span></span>
      <span className="px-1.5 text-border">│</span>
      <span>52W <span className="text-foreground">{range}</span></span>
      <span className="px-1.5 text-border">│</span>
      <span>VOL <span className="text-foreground">{vol}</span></span>
    </div>
    {/* Right ~40%: description truncated to 1 line */}
    <div className="flex items-center gap-1 min-w-0 max-w-[40%]">
      <span className="text-[11px] text-muted-foreground truncate">{description}</span>
      <button className="text-[10px] text-primary shrink-0 hover:underline">Read more →</button>
    </div>
  </div>
</header>
```

**InstrumentAISubheader exact styling**:
```tsx
<div className="border-b border-border bg-[#F0C04018] border-l-2 border-l-[#FFD60A] shrink-0">
  <div className={cn(
    "grid overflow-hidden transition-[grid-template-rows] duration-150 ease-out",
    expanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
  )}>
    {/* Collapsed line always visible ABOVE the grid-rows expansion */}
  </div>
  {/* The collapsed preview is OUTSIDE the animation grid — always visible */}
  <div className="flex items-start gap-2 px-2 py-1">
    <span className="text-[13px] shrink-0">🤖</span>
    <span className="text-[11px] text-foreground line-clamp-1 flex-1">{brief.preview}</span>
    <button className="text-[10px] text-muted-foreground shrink-0" onClick={toggle}>
      {expanded ? "▴" : "▾"}
    </button>
  </div>
  {expanded && (
    <div className="px-2 pb-1.5">
      <p className="text-[11px] text-foreground leading-relaxed">{brief.fullText}</p>
    </div>
  )}
</div>
```

**SessionStatsStrip exact styling**:
```tsx
<div className="flex items-center h-5 px-2 border-b border-border bg-card gap-0">
  {[
    { label: 'O', value: open, color: 'text-foreground' },
    { label: 'H', value: high, color: 'text-positive' },
    { label: 'L', value: low, color: 'text-negative' },
    { label: 'V', value: fmtVol(volume), color: 'text-foreground' },
    { label: 'VWAP', value: vwap, color: 'text-foreground' },
  ].map((stat, i) => (
    <>
      {i > 0 && <span className="px-1.5 text-[10px] text-border">│</span>}
      <span key={stat.label} className="text-[10px] text-muted-foreground font-mono">
        {stat.label}:{' '}
        <span className={cn("font-mono tabular-nums", stat.color)}>
          {stat.value ?? '—'}
        </span>
      </span>
    </>
  ))}
</div>
```

### Wave 5 Validation Gate
- [ ] `pnpm run typecheck` exits 0
- [ ] `pnpm run lint` exits 0
- [ ] `pnpm test` — all instrument tests pass
- [ ] Visual: Brief tab absent (RTL test confirms no "Brief" TabsTrigger)
- [ ] Visual: InstrumentAISubheader amber band visible below header
- [ ] **Terminal quality**: Instrument header is exactly 56px (2 × 28px rows)
- [ ] **Terminal quality**: Stats strip uses pipe `│` separators (not vertical border dividers)
- [ ] **Terminal quality**: SessionStatsStrip is 20px height (`h-5`)
- [ ] **Terminal quality**: Description is on same line as stats (row 2 right split, not below)
- [ ] **Terminal quality**: Fundamentals sections use the §0.9 section header pattern (10px ALL CAPS, h-6)
- [ ] **Terminal quality**: `grep -rn "shadow-\|rounded-lg\|rounded-xl" apps/worldview-web/components/instrument/` returns 0

### Wave 5 Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `__tests__/instrument-detail.test.tsx` | Brief tab removal; header structure change | Remove Brief tab assertions; update header height assertions; update tab count |
| `__tests__/briefing.test.tsx` | InstrumentBriefPanel no longer in tab — may still exist as workspace panel | Keep component tests; remove instrument page Brief tab test |

---

## ✅ Wave 6 — Row Height + Typography Global Sweep

**Status**: **DONE** — 2026-04-25 · 376 tests pass · lint + typecheck clean

**Goal**: Apply 22px row height and 11px data font system-wide. Enforce all §0 terminal quality standards across every component file.
**Depends on**: Waves 2, 3, 4, 5 (run after all feature waves are done)
**Estimated effort**: 3-4 hours
**Architecture layer**: UI styles

### Tasks

#### T-39-W6-01: Typography + Terminal Quality System-Wide Sweep

**Type**: impl
**depends_on**: T-39-W2-04, T-39-W3-01, T-39-W4-04, T-39-W5-03
**blocks**: Wave 7
**Target files**: All components with data table rows throughout `apps/worldview-web/components/`

**What to build**:
Full audit and fix pass enforcing ALL §0 Terminal CLI Quality Standard rules across every component file.

**Row height sweep** (Grep then fix):
- `h-8` in data rows → `h-[22px]`
- `h-10` in data rows → `h-[22px]`
- `h-9` on data rows (NOT nav items/TopBar — those are correct at h-9) → `h-[22px]`

**Font size sweep** (Grep then fix):
- `text-xs` on financial number spans → `text-[11px]`
- `text-sm` on table `<td>` content → `text-[11px]`
- `text-xs` on column headers → `text-[10px] uppercase tracking-[0.08em]`

**Anti-pattern sweep** (Grep and remove):
- `shadow-sm\|shadow-md\|shadow-lg\|shadow-xl` → remove (terminal has zero shadows)
- `rounded-lg\|rounded-xl\|rounded-md` on data surfaces → `rounded-[2px]` or `rounded-none`
- `p-4\|p-6\|p-8\|p-12` inside panel content areas → `px-2 py-0` or `p-3` for narrative content
- `font-bold` on financial data values → `font-medium` max (600 weight max, never 700)
- `bg-gradient\|from-\|via-\|to-` on surfaces → remove entirely
- Section headers using `font-semibold text-sm` → `text-[10px] uppercase tracking-[0.08em] text-muted-foreground`
- `hover:bg-muted` on rows → `hover:bg-muted/40` (subtler hover)

**Specific files to audit with checklist**:

| File | Key checks |
|------|-----------|
| `components/alerts/AlertsList.tsx` | Row h-[22px], severity dot 6px, no shadows |
| `components/dashboard/MorningBriefCard.tsx` | Amber border-l-2, bg-[#F0C04018], no shadow |
| `components/dashboard/RecentAlerts.tsx` | Row h-[22px], section header 10px ALL CAPS |
| `components/dashboard/EconomicCalendar.tsx` | Row h-[22px], mono dates |
| `components/dashboard/WatchlistNews.tsx` | Row h-[22px], tier badge rounded-[2px] |
| `components/dashboard/TopMovers.tsx` | Row h-[22px], mono prices |
| `components/news/ArticleCard.tsx` | If used in compact mode: h-[22px]; card mode: rounded-[2px] |
| `components/brokerage/ConnectedBrokeragesList.tsx` | Cards: border border-border, no shadow, rounded-[2px] |
| `components/instrument/OHLCVChart.tsx` | No shadow on chart container |
| `components/instrument/FundamentalsTab.tsx` | All section headers §0.9 pattern |
| `components/instrument/IntelligenceTab.tsx` | Row h-[22px], severity dots, no shadow |

**Acceptance criteria**:
- [ ] `grep -rn "h-8\b" apps/worldview-web/components/` → 0 results
- [ ] `grep -rn "text-xs" apps/worldview-web/components/` → only in approved exceptions (timestamp labels, NOT financial data)
- [ ] `grep -rn "shadow-sm\|shadow-md\|shadow-lg\|shadow-xl\|shadow-2xl" apps/worldview-web/components/` → 0 results
- [ ] `grep -rn "rounded-lg\|rounded-xl\|rounded-md\|rounded-2xl" apps/worldview-web/components/` → 0 results
- [ ] `grep -rn "bg-gradient\|from-slate\|from-zinc\|from-blue" apps/worldview-web/components/` → 0 results
- [ ] `pnpm run typecheck` exits 0
- [ ] `pnpm test` all tests pass

---

## Wave 7 — Dashboard + Chat + Alerts Redesign ✅

**Goal**: Trader morning routine dashboard layout, chat institutional enhancements, alerts severity grouping + rule builder.
**Status**: DONE 2026-04-25 — 411/411 tests pass; typecheck clean; terminal quality verified
**Depends on**: Wave 6
**Estimated effort**: 8-10 hours
**Architecture layer**: UI application

### Pre-read (agent must read before starting)
- `apps/worldview-web/app/(app)/dashboard/page.tsx` — current dashboard
- `apps/worldview-web/components/dashboard/*.tsx` — all dashboard widgets
- `apps/worldview-web/app/(app)/alerts/page.tsx` — current alerts
- `apps/worldview-web/app/(app)/chat/page.tsx` — current chat page
- `docs/specs/0031-terminal-ui-v3-ground-up-redesign.md` §10, §11, §12b — full specs

### Tasks

#### T-39-W7-01: Dashboard — Trader Morning Routine Layout

**Type**: impl
**depends_on**: none
**blocks**: T-39-W7-04
**Target files**:
- `apps/worldview-web/app/(app)/dashboard/page.tsx` (rewrite)
- `apps/worldview-web/components/dashboard/MarketSnapshotWidget.tsx` (new)
- `apps/worldview-web/components/dashboard/PreMarketMoversWidget.tsx` (new)
- `apps/worldview-web/components/dashboard/SectorHeatmapWidget.tsx` (enhance existing MarketHeatmap)
- `apps/worldview-web/components/dashboard/PortfolioNewsWidget.tsx` (new)
- `apps/worldview-web/components/dashboard/EarningsCalendarWidget.tsx` (new placeholder)
- `apps/worldview-web/components/dashboard/PredictionMarketsWidget.tsx` (new)

**What to build**:
4-row dashboard with trader morning routine layout per PRD §10.

**Dashboard layout** (CSS Grid 12-column):
```
Row 1: MorningBriefCard (col-span-12)
Row 2: MarketSnapshotWidget (col-span-4) | SectorHeatmapWidget (col-span-8)
Row 3: PortfolioSummary (col-span-4) | PreMarketMoversWidget (col-span-5) | PredictionMarketsWidget (col-span-3)
Row 4: EconomicCalendar (col-span-3) | EarningsCalendar (col-span-3) | PortfolioNewsWidget (col-span-3) | RecentAlerts (col-span-3)
```

**MarketSnapshotWidget** (placeholder panel):
- Shows: ES, VIX, NQ, 2Y yield, 10Y yield, spread
- All values: `—` with 10px muted footnote `futures data — EODHD macro integration pending`
- MUST show the labeled structure (not blank/hidden) — slot claimed
- PanelHeader: "MARKET SNAPSHOT"

**SectorHeatmapWidget** (enhance `MarketHeatmap.tsx`):
- Data: `POST /v1/fundamentals/screen` all results → group by `gics_sector` → avg `daily_return` per sector
- Horizontal bar: sector name | bar fill (positive: `bg-positive/30`, negative: `bg-negative/20`) | avg% value
- 8-10 GICS sectors
- Row height: 22px

**PreMarketMoversWidget**:
- Data: screener `daily_return` top 5 + bottom 5
- Two sub-columns: GAINERS | LOSERS — each shows Ticker + Change%
- Footer: `prior session data — pre-market streaming in development`
- Row height: 22px

**PredictionMarketsWidget** (new):
- Data: `GET /v1/predictions/top` (from PRD-0019 integration)
- Shows top 3 Polymarket predictions
- Probability color: >60% = `text-positive`, <40% = `text-negative`, else `text-muted-foreground`
- Footer: `[View all →]`
- If endpoint 404/empty: `<InlineEmptyState message="Prediction market data loading…" />` — do NOT hide widget

**PortfolioNewsWidget**:
- Data: `GET /v1/news/top` → client-side filter to articles mentioning held ticker names
- If no portfolio: show general news with label `[Top market news]`
- 4 rows max, 22px height

**EarningsCalendarWidget** (placeholder):
- Shows `EARNINGS CALENDAR` header + `(earnings data coming soon)` inline note
- Do NOT hide — slot must be claimed visually

**Remove**: `AiSignals` widget (stub endpoint, no data). Replace with empty slot or merge into another widget.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `dashboard-4-rows` | 4 grid row sections present | unit |
| `morning-brief-full-width` | MorningBriefCard spans 12 columns | unit |
| `market-snapshot-shows-dashes` | Shows `—` for all futures values | unit |
| `prediction-markets-widget-present` | PredictionMarketsWidget in DOM | unit |
| `sector-heatmap-row2` | SectorHeatmap in row 2 (not row 3) | unit |

**Acceptance criteria**:
- [ ] 4 rows laid out per spec
- [ ] Sector heatmap is row 2 (with Market Snapshot)
- [ ] PredictionMarketsWidget visible (with data or placeholder)
- [ ] No hidden/null widgets — all slots claimed

---

#### T-39-W7-02: Alerts Page — Severity Grouping + ACK/Snooze + Rule Builder

**Type**: impl
**depends_on**: none
**blocks**: T-39-W7-04
**Target files**:
- `apps/worldview-web/app/(app)/alerts/page.tsx` (rewrite)
- `apps/worldview-web/components/alerts/AlertsList.tsx` (rewrite for severity grouping)
- `apps/worldview-web/components/alerts/AlertRuleBuilder.tsx` (new slide-over)
- `apps/worldview-web/components/alerts/AlertRuleManager.tsx` (new slide-over)
- `apps/worldview-web/components/alerts/SystemRiskAlerts.tsx` (new — client-side computed)

**What to build**:
Alerts page per PRD §11.

**Severity-Grouped AlertsList**:
- Groups: CRITICAL → HIGH → MEDIUM → LOW → Acknowledged (collapsed)
- Group header: severity label + count + `[ACK ALL]` button
- Row: 22px, `divide-y divide-border/30`; SEV dot (6px) + `[SYS]` badge + ticker + type + message + time + `[ACK ▾]`
- `[ACK ▾]` dropdown: Acknowledge / Snooze 1h / Snooze 4h / Snooze until tomorrow / Dismiss permanently
- ACK state: moves row to Acknowledged section (`opacity-50`)
- Snooze state: hidden from main list (stored in `localStorage` with expiry timestamp)
- Dismissed: stored in `localStorage['worldview-alert-denylist']`
- Acknowledged section: collapsed by default, expand on click

**SystemRiskAlerts** (client-side computed, no backend):
- Computed from portfolio data + live quotes:
  - `CONCENTRATION`: any holding > 15% of total portfolio → CRITICAL
  - `SECTOR_CONCENTRATION`: any sector > 40% → HIGH
  - `DRAWDOWN_5`: portfolio day P&L < -5% → HIGH
  - `DRAWDOWN_10`: portfolio day P&L < -10% from 20-day high → CRITICAL
- Show with `[SYS]` badge in severity groups (appear above user-created alerts in same severity)
- Cannot be dismissed (only snooze)

**AlertRuleBuilder** (slide-over `<Sheet>` from shadcn):
- Trigger: `[+ Create Rule]` button
- Rule types: Price Threshold | Volume Spike | News Signal | Portfolio Risk (dropdown)
- Entity search: `GET /v1/search?q=X` inline
- Condition fields: conditional render based on rule type
- Notify via: `[✓ In-app] [☐ Email]` checkboxes
- Save: stores to `localStorage['worldview-alert-rules']`

**AlertRuleManager** (slide-over):
- Trigger: `[⚙ Manage Rules]` button
- Lists user rules: toggle on/off | edit | delete
- Lists system rules (read-only): CONCENTRATION / DRAWDOWN_5 / DRAWDOWN_10 / SECTOR_CONCENTRATION

**News Feed Tab** enhancements (within alerts page):
- Category filter rail: `[All] [Earnings] [M&A] [Regulatory] [Macro] [Analyst] [SEC Filings]`
- `[My Holdings]` 4th news tab: client-side filter to portfolio + watchlist entity_ids
- Read/unread: `IntersectionObserver` marks articles read on scroll-past; read = `opacity-60`
- Impact sort: `[RELEVANCE ▾] [IMPACT ▾] [NEWEST ▾]` options

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `severity-groups-present` | CRITICAL/HIGH/MEDIUM/LOW sections rendered | unit |
| `ack-moves-to-ack-section` | ACK moves alert to acknowledged group | unit |
| `sys-badge-on-system-alerts` | System alerts have [SYS] badge | unit |
| `rule-builder-opens` | Create Rule button opens slide-over | unit |
| `category-filter-rail` | 7 category chips present in News tab | unit |

**Acceptance criteria**:
- [ ] Alerts grouped by severity
- [ ] ACK/Snooze/Dismiss dropdown works
- [ ] System risk alerts computed and shown with [SYS] badge
- [ ] Rule builder opens and saves to localStorage
- [ ] News tab has category filter rail

---

#### T-39-W7-03: Chat Page — Institutional Enhancements

**Type**: impl
**depends_on**: none
**blocks**: T-39-W7-04
**Target files**:
- `apps/worldview-web/app/(app)/chat/page.tsx` (enhance)

**What to build**:
Chat enhancements per PRD §12b.

**Starter Questions** (empty state when no messages in thread):
- 6 cards in 2-column grid
- Card style: `rounded-[2px] border border-border hover:border-primary/40 p-3 cursor-pointer text-[12px]`
- Questions (hardcoded):
  1. "What are the key risks for [TICKER] next quarter?"
  2. "Compare MSFT and GOOGL cloud revenue growth over 4 quarters"
  3. "Summarize [TICKER]'s latest earnings call"
  4. "Recent insider transactions and what they signal"
  5. "What analyst consensus shows for [TICKER] in 2026?"
  6. "Search SEC filings for 'supply chain' risk exposure"
- Click: inject text into input (with `[TICKER]` replaced by entity ticker if context present)

**Entity Context Injection**:
- Read `?entity_id=X` URL param (or navigation state from instrument page)
- Show amber context badge: `[Context: AAPL — questions will focus on Apple Inc.]`
- Badge style: `bg-primary/10 text-primary text-[11px] font-mono px-2 py-0.5 rounded-[2px]`
- Pass `entity_id` in `/chat/stream` request body
- Replace `[TICKER]` in starter questions with entity ticker

**Citation Enhancement**:
- Current citations: `[1] Title`
- Enhanced: `[N] {type-icon} Source · Title · Date · score% match`
- Type icons: `📄` SEC, `📰` news, `📊` earnings call, `🕸` knowledge graph
- Source badge: SEC = `bg-primary/15`, news = `bg-muted`, earnings = `bg-positive/15`

**Thread Naming** (if thread sidebar exists):
- Double-click thread name → `contentEditable` span → Enter confirms
- Persist custom names in `localStorage` keyed by thread ID

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `starter-questions-on-empty` | 6 starter question cards visible when no messages | unit |
| `entity-context-badge` | Amber badge shown when entity_id param present | unit |
| `click-card-injects-text` | Clicking starter card fills input | unit |

**Acceptance criteria**:
- [ ] 6 starter questions visible on empty chat state
- [ ] Entity context badge shown when navigating from instrument page
- [ ] Starter question `[TICKER]` replaced when entity context present

---

#### T-39-W7-04: Dashboard Tests + Wave Assembly

**Type**: test
**depends_on**: T-39-W7-01, T-39-W7-02, T-39-W7-03
**blocks**: Wave 8
**Target files**:
- `apps/worldview-web/__tests__/dashboard.test.tsx` (update)
- `apps/worldview-web/__tests__/alerts-page.test.tsx` (update)
- `apps/worldview-web/__tests__/chat.test.tsx` (update)

**What to build**:
Update all affected tests to match new implementations.

**Acceptance criteria**:
- [ ] All 3 test files updated and passing
- [ ] `pnpm test` exits 0 with ≥315 tests passing

---

### Wave 7 Terminal Quality Additions

**Dashboard widget anatomy — ALL widgets follow this pattern**:
```tsx
// Every dashboard widget: PanelHeader (24px) + content (p-0)
<div className="bg-card border border-border flex flex-col">
  {/* Widget header — §0.9 section header pattern */}
  <div className="flex items-center justify-between border-b border-border px-2 h-6 shrink-0">
    <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
      WIDGET TITLE
    </span>
    {/* Optional: data freshness or action */}
    <span className="text-[10px] font-mono text-muted-foreground/60">live</span>
  </div>
  {/* Content — rows at h-[22px], px-2 py-0 */}
  <div className="flex-1 overflow-auto divide-y divide-border/30">
    {rows.map(row => (
      <div key={row.id} className="flex items-center h-[22px] px-2 gap-2 hover:bg-muted/40">
        ...
      </div>
    ))}
  </div>
</div>
```

**Dashboard 12-column grid specification**:
```tsx
<div className="grid grid-cols-12 gap-px bg-background h-[calc(100vh-var(--topbar-height))]">
  {/* Row 1: Morning Brief — full width */}
  <div className="col-span-12 bg-card border-b border-border">
    <MorningBriefCard />
  </div>
  {/* Row 2: Market Snapshot (4) + Sector Heatmap (8) */}
  <div className="col-span-4"><MarketSnapshotWidget /></div>
  <div className="col-span-8"><SectorHeatmapWidget /></div>
  {/* Row 3: Portfolio Summary (4) + Pre-Market Movers (5) + Prediction Markets (3) */}
  <div className="col-span-4"><PortfolioSummary /></div>
  <div className="col-span-5"><PreMarketMoversWidget /></div>
  <div className="col-span-3"><PredictionMarketsWidget /></div>
  {/* Row 4: Econ (3) + Earnings (3) + Portfolio News (3) + Alerts (3) */}
  <div className="col-span-3"><EconomicCalendar /></div>
  <div className="col-span-3"><EarningsCalendarWidget /></div>
  <div className="col-span-3"><PortfolioNewsWidget /></div>
  <div className="col-span-3"><RecentAlerts /></div>
</div>
```

Note: `gap-px` between cells means the `bg-background` (#09090B) shows through as 1px hairline borders between all dashboard widgets. This creates the Bloomberg-style panel grid without explicit borders on each widget.

**AlertsList severity section header**:
```tsx
{SEVERITIES.map(sev => (
  <section key={sev.level}>
    {/* Severity group header — no card chrome, just a labeled row */}
    <div className={cn(
      "flex items-center justify-between h-6 px-2 border-b border-border bg-background",
      "text-[10px] uppercase tracking-[0.08em]",
      sev.level === 'CRITICAL' ? "text-negative" :
      sev.level === 'HIGH' ? "text-warning" : "text-muted-foreground"
    )}>
      <span className="flex items-center gap-1.5">
        <span className="text-[8px]">●</span>
        {sev.level} ({sev.alerts.length})
      </span>
      <button className="text-[10px] text-muted-foreground hover:text-foreground normal-case tracking-normal">
        ACK ALL
      </button>
    </div>
    {/* Alert rows */}
    {sev.alerts.map(alert => (
      <div key={alert.id}
        className="flex items-center h-[22px] px-2 gap-1.5 border-b border-border/30 hover:bg-muted/40"
      >
        <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", sevColor[sev.level])} />
        {alert.source === 'SYSTEM' && (
          <span className="rounded-[2px] bg-muted/40 px-1 text-[9px] text-muted-foreground font-mono shrink-0">SYS</span>
        )}
        <span className="font-mono text-[10px] text-muted-foreground tabular-nums shrink-0">{alert.ticker}</span>
        <span className="text-[11px] text-foreground truncate flex-1">{alert.message}</span>
        <span className="font-mono text-[10px] text-muted-foreground tabular-nums shrink-0">{alert.timeAgo}</span>
        <button className="rounded-[2px] bg-muted/40 border border-border px-1.5 text-[10px] text-muted-foreground hover:text-foreground shrink-0">
          ACK ▾
        </button>
      </div>
    ))}
  </section>
))}
```

**Chat starter questions exact styling**:
```tsx
<div className="grid grid-cols-2 gap-2 p-3">
  {STARTER_QUESTIONS.map((q, i) => (
    <button key={i}
      className={cn(
        "rounded-[2px] border border-border bg-card",
        "hover:border-primary/40 hover:bg-muted/40",
        "p-3 text-left cursor-pointer",
        "text-[12px] text-foreground leading-relaxed",
        "transition-colors duration-0"  // instant, no animation
      )}
      onClick={() => setInput(q.replace('[TICKER]', entityTicker || '[TICKER]'))}
    >
      {q.replace('[TICKER]', entityTicker || '[TICKER]')}
    </button>
  ))}
</div>
```

### Wave 7 Validation Gate
- [ ] `pnpm run typecheck` exits 0
- [ ] `pnpm run lint` exits 0
- [ ] `pnpm test` — all tests pass (≥315)
- [ ] Visual: Dashboard has 4 rows with trader morning routine layout
- [ ] Visual: Alerts are severity-grouped with colored severity labels
- [ ] Visual: Chat shows starter questions on empty state
- [ ] **Terminal quality**: Dashboard uses `gap-px` between all widgets (background seam visible)
- [ ] **Terminal quality**: ALL widget headers are 24px (`h-6`) with 10px ALL CAPS label
- [ ] **Terminal quality**: Dashboard rows are 22px in all data-showing widgets
- [ ] **Terminal quality**: Alerts severity headers are 24px (`h-6`) with colored text, `bg-background`
- [ ] **Terminal quality**: Starter question cards use `border border-border rounded-[2px]` (no shadow, no rounding)
- [ ] **Terminal quality**: `grep -rn "shadow-\|rounded-lg\|rounded-xl\|rounded-md" apps/worldview-web/app/\(app\)/` returns 0

### Wave 7 Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `__tests__/dashboard.test.tsx` | Dashboard layout completely restructured | Rewrite for 4-row grid; update widget presence assertions |
| `__tests__/alerts-page.test.tsx` | Alerts grouped by severity; new components | Update to expect severity groups; add rule builder tests |
| `__tests__/chat.test.tsx` | Starter questions added | Add starter question assertions |

---

## Wave 8 — QA, Screenshots, Browser Validation

**Goal**: Playwright tests, screenshots for all routes, console error validation, responsive checks.
**Depends on**: Wave 7
**Estimated effort**: 3-4 hours
**Architecture layer**: testing

### Tasks

#### T-39-W8-01: Playwright Tests + Screenshots

**Type**: test
**depends_on**: all prior waves
**blocks**: none
**Target files**:
- `apps/worldview-web/e2e/terminal-v3.spec.ts` (new or extend existing)
- `docs/screenshots/v3/` (PNG files)

**What to build**:
E2E smoke tests and screenshot capture for all major routes.

**Playwright tests** (per route):
1. `/dashboard`: Verify 4 rows, morning brief visible, sector heatmap in row 2
2. `/screener`: Verify 12 column headers, filter bar toggle, 22px rows
3. `/workspace`: Verify 4 default workspace tabs, panel add/remove, resize handle visible
4. `/portfolio`: Verify 4 tabs, KPI strip, holdings `<table>` element
5. `/alerts`: Verify severity groups (CRITICAL/HIGH/MEDIUM/LOW sections)
6. `/chat`: Verify starter questions on empty state
7. `/instruments/[entityId]`: Verify no Brief tab, InstrumentAISubheader visible, Overview 5 zones
8. Sidebar: Verify collapsed width 48px, expanded width 220px using `getBoundingClientRect`
9. TopBar: Verify height 36px using `getBoundingClientRect`

**Screenshots** (capture after each route test):
- `docs/screenshots/v3/dashboard.png`
- `docs/screenshots/v3/screener.png`
- `docs/screenshots/v3/workspace.png`
- `docs/screenshots/v3/portfolio-holdings.png`
- `docs/screenshots/v3/portfolio-transactions.png`
- `docs/screenshots/v3/portfolio-watchlists.png`
- `docs/screenshots/v3/alerts.png`
- `docs/screenshots/v3/chat.png`
- `docs/screenshots/v3/instrument-overview.png`
- `docs/screenshots/v3/instrument-fundamentals.png`
- `docs/screenshots/v3/instrument-news.png`
- `docs/screenshots/v3/instrument-intelligence.png`

**Console error validation**:
```typescript
page.on('console', msg => {
  if (msg.type() === 'error') errors.push(msg.text());
});
// After page load: expect(errors).toHaveLength(0)
```

**Acceptance criteria**:
- [ ] All Playwright tests pass
- [ ] ≥12 screenshots committed to `docs/screenshots/v3/`
- [ ] Zero console errors on all major routes
- [ ] Sidebar 48px/220px dimensions verified via `getBoundingClientRect`

---

#### T-39-W8-02: Acceptance Criteria Verification

**Type**: test
**depends_on**: T-39-W8-01
**blocks**: none
**Target files**: none (verification only)

**What to verify** (from PRD §16 Acceptance Criteria table):

Run through every measurable criterion:
- `pnpm run typecheck` exit 0 ✓
- `pnpm test` ≥315 tests ✓
- Workspace panels ≤16 ✓
- Workspace resize: drag handle present ✓
- Named workspaces save/load/delete ✓
- Screener ≥12 columns at 1440px ✓
- Screener row height 22px ✓
- Portfolio `<table>` element ✓
- Portfolio 6 KPI tiles ✓
- Brief tab does NOT exist ✓
- Overview 5 zones ✓
- Sidebar 48px collapsed / 220px expanded ✓
- TopBar 36px ✓
- `text-primary` on P&L values does NOT appear ✓
- SessionStatsStrip below chart ✓
- InstrumentAISubheader below header above tabs ✓

Document results in `docs/audits/2026-04-25-plan-0039-wave8-acceptance-report.md`.

**Acceptance criteria**:
- [ ] All PRD §16 criteria verified and documented
- [ ] Audit report committed

---

### Wave 8 Terminal Quality Final Audit

Before declaring Wave 8 complete, run ALL §0.10 Bloomberg Calibration Benchmarks:

```bash
# Shadow violations — must be 0
grep -rn "shadow-sm\|shadow-md\|shadow-lg\|shadow-xl\|shadow-2xl\|shadow-inner" \
  apps/worldview-web/components/ apps/worldview-web/app/ | grep -v ".test." | wc -l
# Expected: 0

# Rounded corner violations — must be 0
grep -rn "rounded-lg\|rounded-xl\|rounded-md\|rounded-2xl\|rounded-full" \
  apps/worldview-web/components/ apps/worldview-web/app/ | grep -v ".test.\|node_modules" | wc -l
# Expected: 0 (rounded-[2px] and rounded-none are OK)

# Gradient violations — must be 0 (except HeatCell)
grep -rn "bg-gradient\|from-slate\|from-zinc\|from-blue\|from-gray" \
  apps/worldview-web/components/ | grep -v "HeatCell\|.test." | wc -l
# Expected: 0

# Large padding violations in data areas — must be 0
grep -rn "\bp-4\b\|\bp-6\b\|\bp-8\b\|\bpy-4\b\|\bpy-6\b\|\bpy-8\b\|\bpy-12\b" \
  apps/worldview-web/components/ | grep -v ".test." | wc -l
# Expected: 0 (p-3 and px-2 are OK for narrative areas)

# Old row height violations — must be 0
grep -rn "\bh-8\b" apps/worldview-web/components/ | grep -v ".test." | wc -l
# Expected: 0
```

**Visual density screenshot comparison checklist** (compare side-by-side with Finviz screener):
- [ ] Screener: ≥28 rows visible at 1080p without scrolling
- [ ] Portfolio holdings: ≥10 rows visible at 1080p without scrolling
- [ ] Dashboard: all 4 rows visible at 1080p without scrolling (each row ≤220px height)
- [ ] Sidebar: alarms + watchlist + nav all visible simultaneously when expanded
- [ ] Instrument overview: chart + stats strip + timeframe + 3-col lower all above fold at 1080p

### Wave 8 Validation Gate
- [ ] `pnpm run typecheck` exits 0
- [ ] `pnpm run lint` exits 0
- [ ] `pnpm test` — all tests pass
- [ ] All Playwright tests pass
- [ ] ≥12 screenshots committed to `docs/screenshots/v3/`
- [ ] Zero console errors on all major routes
- [ ] PRD §16 acceptance criteria report complete
- [ ] **Terminal quality**: All §0.10 Benchmark grep commands return 0
- [ ] **Terminal quality**: Visual density screenshot comparison done and documented in acceptance report
- [ ] **Terminal quality**: Screener shows ≥28 rows at 1080p without scrolling (screenshot evidence)
- [ ] **Terminal quality**: Dashboard all 4 rows visible at 1080p (screenshot evidence)

---

## Cross-Cutting Concerns

### Frontend Dependencies Added
- `react-resizable-panels` — exact version, no `^`; run `pnpm audit` to confirm 0 CVEs
- `@tanstack/react-virtual` — verify already installed; if not, add exact version

### localStorage Keys
- `worldview-sidebar-expanded`: `boolean` — sidebar collapsed state
- `worldview-workspaces`: `WorkspacePersistence` — named workspaces + panel configs + sizes
- `worldview-alert-rules`: `AlertRule[]` — user-created alert rules
- `worldview-alert-denylist`: `string[]` — permanently dismissed alert IDs
- `worldview-alert-snooze`: `Record<string, number>` — alertId → snooze expiry timestamp

### Key Color Rules (enforced in all waves)
- `text-primary` (`#FFD60A`): ONLY interactive elements (buttons, active nav, links). NEVER on prices/P&L
- `text-positive` / `text-negative`: ONLY for financial semantic data (price up/down, P&L)
- All numeric values: `font-mono tabular-nums` — no exceptions
- All panels: `border border-border` (1px `#232A36`) — no borderless panels
- Rounded corners: `rounded-[2px]` for badges only; NO `rounded-md`, `rounded-lg`, `rounded-xl` on data surfaces

### Documentation Updates (after Wave 8)
- `docs/services/api-gateway.md`: No changes required (all frontend-only)
- `docs/apps/worldview-web.md`: Update with new component structure, new routes behavior, new localStorage keys
- `docs/ui/DESIGN_SYSTEM.md`: Already updated with v3 tokens (done in investigation session)

---

## Risk Assessment

### Critical Path
Wave 0 → Wave 1 → Wave 7 → Wave 8

### Highest Risk Waves
1. **Wave 2** (Workspace) — `react-resizable-panels` integration complexity; panel resize state persistence
2. **Wave 5** (Instrument Detail) — 9 sections in Fundamentals tab; Brief tab removal breaking existing tests
3. **Wave 7** (Alerts) — System risk alert computation; rule builder localStorage schema

### Rollback Strategy
Each wave is committed separately. If a wave fails mid-way:
- Revert the wave's commits with `git revert`
- The prior wave's state is stable (each wave leaves codebase green)
- Waves 2–5 can be rolled back independently (they don't depend on each other)

### Testing Gaps
- `react-resizable-panels` resize behavior is hard to unit-test (requires mouse drag events) — use Playwright instead
- Symbol linking broadcasts are async state updates — use `act()` wrappers in RTL tests
- System risk alerts depend on live portfolio data — mock `getHoldings` + `getQuotes` in tests

---

## Execution Summary

| Wave | Goal | Files | Effort | Parallel With |
|------|------|-------|--------|---------------|
| Wave 0 | P0 fixes + TypeScript | MorningBriefCard, gateway.ts, workspace/page.tsx | 2-4h | — |
| Wave 1 | New shell | CollapsibleSidebar, TopBar, WorkspaceTabs | 4-6h | — |
| Wave 2 | Workspace | workspace/page.tsx + components/workspace/ | 6-8h | 3, 4, 5 |
| Wave 3 | Screener | screener/page.tsx, ScreenerTable | 3-5h | 2, 4, 5 |
| Wave 4 | Portfolio | portfolio/page.tsx + 5 new components | 6-8h | 2, 3, 5 |
| Wave 5 | Instrument | [entityId]/page.tsx + 6 new components | 8-10h | 2, 3, 4 |
| Wave 6 | Typography sweep | All data components | 2-3h | — |
| Wave 7 | Dashboard + Chat + Alerts | dashboard, chat, alerts pages | 8-10h | — |
| Wave 8 | QA + Screenshots | Playwright + acceptance report | 3-4h | — |

**Total estimated effort**: 42-58 hours of agent work
**Recommended execution**: Waves 0+1 serially; Waves 2-5 in parallel worktrees; Wave 6; Wave 7; Wave 8
