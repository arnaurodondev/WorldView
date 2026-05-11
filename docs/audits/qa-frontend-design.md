# Worldview Frontend — Complete Terminal Redesign Plan

**Date**: 2026-04-24 (v2 — strict enforcement edition)
**Scope**: Full frontend audit — all routes, all components, design system, interactions, data density
**Basis**: Direct source code inspection of all pages + components + prior investigation report
**Output file**: `docs/audits/qa-frontend-design.md`
**Verdict**: `READY_FOR_IMPLEMENTATION` — Wave A starts immediately

---

## 1. Executive Summary

### Blunt Diagnosis

The Worldview frontend has a correctly specified Terminal Dark design system: `#09090B` neutral black, `#FFD60A` Bloomberg yellow, 2px radius, IBM Plex fonts, `--panel-header-height: 32px`, `gap-px` workspace seams. These are institutional-grade decisions.

The problem is not the design system. The problem is **systematic execution failure** at the component level:

1. `rounded-lg` (8px) used throughout ArticleCard and AlertRow instead of `rounded-[2px]` — every card-based component breaks the radius rule.
2. The screener has only 6 columns, one of which **permanently shows "—"** for every row (Price column has no data source). This means 1/6 columns is decorative noise.
3. The alerts page is constrained to `max-w-4xl` centered width — the exact opposite of a full-width terminal.
4. The workspace placeholder panels render `py-12` "coming soon" text for screener and chat — explicit acknowledgment that a third of the workspace catalogue is unusable stubs.
5. Chart height is hardcoded to `280` in a JavaScript `createChart()` call — not fixable by CSS.
6. Portfolio uses `p-6` outer padding on a page that should be edge-to-edge like the workspace.
7. News articles are wrapped in an extra `px-4 py-3` div outside the ArticleCard — doubling the effective padding.
8. Empty states use `p-8` and `py-24` — centered large voids.
9. Fundamentals grid uses `gap-6` column separation — 24px gaps between data groups.
10. Instrument header back-nav is hardcoded to `/dashboard` — breaks browser history.

None of these require architecture changes. All are fixable in focused implementation passes.

### Why Current UI Is Not Acceptable

A platform claiming Bloomberg-grade intelligence cannot have:
- A screener table with a column that always shows "—"
- Alert rows with `rounded-lg border` card styling instead of compact table rows
- News feeds capped at 4-column max-width with centered content
- Workspace panels that say "Compact workspace layout coming in a future wave"
- Charts that cannot be made taller without editing JavaScript
- Portfolio pages with 48px of outer padding on all four sides

These are not polish issues. They are the difference between a data terminal and a dark-themed consumer app.

### Target Terminal Direction

Every page must feel like a Bloomberg DES/TOP page: data fills to the edges, no decorative whitespace, numbers right-aligned in monospace, rows are 28–32px, panels have 8–12px padding, empty states are 1-line inline messages, disabled placeholder buttons are removed.

### Top Redesign Priorities

1. **P0** — Replace `rounded-lg` with `rounded-[2px]` in all card-based alert/article components
2. **P0** — Remove "Price" column from screener (always "—"); add P/E, Beta, Revenue TTM
3. **P0** — Remove `max-w-4xl` from alerts page; full-width terminal layout
4. **P0** — Remove workspace "coming soon" placeholder panels OR implement compact screener/chat widgets
5. **P0** — Fix chart height to 360px minimum (requires JS change in `createChart()`)
6. **P0** — Remove extra `px-4 py-3` wrapper around ArticleCards in news tab
7. **P1** — Portfolio `p-6` → `p-3`; remove disabled "Add Position" stub
8. **P1** — Fundamentals `gap-6` → `gap-2`; `p-4` → `p-3`
9. **P1** — Screener filter panel collapsible + add 3 columns (P/E, Beta, Revenue)
10. **P1** — Instrument header: `py-4` → `py-2`; add volume/open/session stats; fix back nav

### Main Implementation Risks

- **Chart height**: changing `height: 280` in the JS `createChart()` call requires ensuring ResizeObserver still handles it correctly
- **Screener columns**: adding P/E requires verifying it's in ScreenerResult API type; Beta and Revenue may need backend/S9 changes
- **Workspace screener panel**: replacing placeholder with a real compact screener requires a new component
- **Sector allocation in portfolio**: requires new S9 composition or client-side fan-out

---

## 2. Prior Report Evaluation

### Prior Report: `docs/audits/qa-frontend-design.md` v1 (2026-04-24)

**Useful findings (keep):**
- Instrument header `py-4` → `py-2` ✓
- News article wrapper `px-4 py-3` → `px-3 py-1.5` ✓
- Chart height 280px → 360px ✓
- Screener columns insufficient ✓
- Portfolio sector allocation missing ✓
- Fundamentals `gap-6` too wide ✓
- `InstrumentBriefPanel` default-expanded — actually WRONG, code shows `useState(false)` (already collapsed)

**Findings that were too soft:**
- Report says "ArticleCard py-2 per suggestion row" for GlobalSearch — GlobalSearch doesn't use ArticleCard; this is about CommandItem height
- Report missed `rounded-lg` rule violation in ArticleCard and AlertRow — critical
- Report missed `max-w-4xl` constraint on alerts page
- Report called workspace "best-designed page" but missed that 2/8 panel types render "coming soon" placeholders
- Report called InstrumentBriefPanel always-expanded as an issue — code shows it's already collapsed
- Report did not verify actual screener column count — "likely 5-6" when it's exactly 6 (including a useless Price column)
- Report said screener "likely uses card stacks" for alerts — AlertsList actually uses `rounded-lg border bg-card` buttons (card-style but not full card)

**Missing in prior report:**
- `rounded-[2px]` radius rule violations (AlertRow, ArticleCard use `rounded-lg`)
- Instrument page back-nav hardcoded to `/dashboard`
- Workspace hardcoded `demoEntityId = "entity-aapl"` for chart/fundamentals panels — may not work with real data
- AlertsList empty state uses `p-8`
- AlertRow's "alert_type" label is often a long machine string, not human-readable
- OHLCVChart height is in JS, not CSS — cannot be fixed with Tailwind alone
- Screener "Price" column always "—"
- Alerts page `max-w-4xl` constraint

**Recommendations to keep:**
- Wave A/B/C/D wave structure
- Data-density plan tables
- Quick stats strip expansion for instrument header
- Fundamentals two-column bloomberg-DES layout

**Recommendations to override:**
- Prior report says "READY_FOR_REDESIGN_IMPLEMENTATION" with a soft summary of "mostly good." This is too soft. The `rounded-lg` violations, the permanently-empty screener column, and the workspace stub panels make the UI look unfinished at a terminal-grade standard.

---

## 3. Route and Component Coverage Map

| Route/Component | Inspected | Severity | Main Issue | Redesign Required |
|---|---|---|---|---|
| `app/(app)/layout.tsx` | No | Unknown | Gap | ✓ (check sidebar) |
| `app/(app)/dashboard/page.tsx` | **Yes** | Low | gap-px/p-1 correct; CardContent pb-3 acceptable | Minor |
| `app/(app)/workspace/page.tsx` | **Yes** | **High** | WorkspacePlaceholder py-12 "coming soon"; hardcoded entity IDs | **Yes** |
| `app/(app)/instruments/[entityId]/page.tsx` | **Yes** | **High** | py-4 header; px-4 py-3 article wrappers; hardcoded back-nav; 4-metric quick stats | **Yes** |
| `app/(app)/portfolio/page.tsx` | **Yes** | **High** | p-6 outer; disabled stub button; CSS grid not table; missing sector exposure | **Yes** |
| `app/(app)/screener/page.tsx` | **Yes** | **High** | 6 cols (1 useless); no collapse; 3 filters only | **Yes** |
| `app/(app)/alerts/page.tsx` | **Yes** | **High** | max-w-4xl; p-6; card-style alert rows | **Yes** |
| `app/(app)/chat/page.tsx` | No | Unknown | Gap | ✓ (check) |
| `app/(app)/settings/page.tsx` | No | Unknown | Gap | ✓ (check) |
| `app/(app)/instruments/page.tsx` | No | Unknown | Gap — instrument list/screener redirect? | ✓ |
| `app/(app)/portfolio/brokerage/callback/page.tsx` | No | Unknown | Gap | Minor |
| `components/instrument/FundamentalsTab.tsx` | **Yes** | Medium | gap-6 between columns; p-4 outer | **Yes** |
| `components/instrument/OHLCVChart.tsx` | **Yes** | **High** | height: 280 hardcoded in JS | **Yes** |
| `components/instrument/InstrumentBriefPanel.tsx` | **Yes** | Low | Already collapsed correctly; px-4 outer padding acceptable | Minor |
| `components/instrument/EntityGraphPanel.tsx` | No | Unknown | Gap | ✓ |
| `components/instrument/IntelligenceTab.tsx` | No | Unknown | Gap | ✓ |
| `components/news/ArticleCard.tsx` | **Yes** | **High** | rounded-lg violates 2px rule; card layout not compact row | **Yes** |
| `components/alerts/AlertsList.tsx` | **Yes** | High | rounded-lg AlertRow; p-8 empty state; card-style rows | **Yes** |
| `components/alerts/SeverityBadge.tsx` | No | Unknown | Gap | ✓ |
| `components/dashboard/MorningBriefCard.tsx` | No | Unknown | Gap — markdown heading sizes suspected | ✓ |
| `components/dashboard/PortfolioSummary.tsx` | No | Unknown | Gap — text-2xl KPI values suspected | ✓ |
| `components/dashboard/TopMovers.tsx` | No | Unknown | Gap | ✓ |
| `components/dashboard/WatchlistNews.tsx` | No | Unknown | Gap — likely uses ArticleCard cards | ✓ |
| `components/dashboard/MarketHeatmap.tsx` | No | Unknown | Gap | ✓ |
| `components/dashboard/EconomicCalendar.tsx` | No | Unknown | Gap | ✓ |
| `components/dashboard/RecentAlerts.tsx` | No | Unknown | Gap — likely card rows | ✓ |
| `components/dashboard/AiSignals.tsx` | No | Unknown | Gap | ✓ |
| `components/dashboard/TopBets.tsx` | No | Unknown | Gap | ✓ |
| `components/shell/GlobalSearch.tsx` | **Yes** | Medium | No recent instruments; no keyboard hint; CommandItem padding unknown | **Yes** |
| `components/shell/TopBar.tsx` | No | Unknown | Gap | ✓ |
| `components/shell/IndexTicker.tsx` | No | Unknown | Gap — gap-4 spacing suspected | ✓ |
| `components/shell/Sidebar.tsx` | No | Unknown | Gap | ✓ |
| `components/shell/AskAiPanel.tsx` | No | Unknown | Gap | ✓ |
| `components/brokerage/ConnectedBrokeragesList.tsx` | No | Unknown | Gap | Minor |
| `components/screener/HeatCell.tsx` | No | Unknown | Gap | Minor |

**Uninspected pages/components (must be read before Wave A):**
- `app/(app)/chat/page.tsx`
- `app/(app)/settings/page.tsx`
- `components/dashboard/MorningBriefCard.tsx`
- `components/dashboard/PortfolioSummary.tsx`
- `components/shell/TopBar.tsx`
- `components/shell/Sidebar.tsx`
- `components/instrument/IntelligenceTab.tsx`
- `components/instrument/EntityGraphPanel.tsx`

---

## 4. Global Design-System Plan

### 4.1 Typography Scale (Confirmed — enforce violations)

The scale is correct in `DESIGN_SYSTEM.md`. Violations to fix:

| Violation | Location | Fix |
|---|---|---|
| `text-sm font-medium leading-snug` on article titles | ArticleCard | `text-xs font-medium leading-snug` in compact mode |
| `text-xl font-semibold` for instrument ticker in header | page.tsx line 134 | Acceptable — keep for header only |
| Any `text-2xl` in data panels | PortfolioSummary (uninspected) | Reduce to `text-xl` |

### 4.2 Spacing Scale (Enforce)

**Violations found:**

| Token | Found | Location | Fix |
|---|---|---|---|
| `p-6` outer padding | portfolio/page.tsx, alerts/page.tsx | `p-3` (12px) or `p-0` edge-to-edge |
| `p-4` fundamentals outer | FundamentalsTab.tsx | `p-3` |
| `p-4` chart container | instrument page | `p-0` or `p-2` |
| `gap-6` fundamentals columns | FundamentalsTab.tsx | `gap-2` |
| `py-12` workspace placeholder | workspace/page.tsx WorkspacePlaceholder | `p-3 text-xs inline` |
| `py-24` empty workspace | workspace/page.tsx EmptyWorkspace | `py-6` max |
| `px-4 py-3` article wrappers | instrument news tab | `px-3 py-1` |
| `p-8` empty states | AlertsList.tsx, alerts/page.tsx | `p-3 text-xs` |
| `p-3` alert rows | AlertsList.tsx AlertRow | Acceptable — keep |

### 4.3 Border Radius Policy (Enforce)

**Rule**: ALL components use `rounded-[2px]` (2px). Never `rounded-md` (6px) or `rounded-lg` (8px) on data panels/rows.

**Violations:**
- `ArticleCard`: `rounded-lg border border-border/50 bg-card` → `rounded-[2px]`
- `AlertRow button`: `rounded-lg border border-border/50 bg-card` → `rounded-[2px]`
- `AlertsList empty state`: `rounded-lg border border-border/50 p-8` → inline text, no rounded container
- Error states in `NewsFeedTab/TopTodayTab`: `rounded-lg border border-destructive/30 bg-destructive/10` → `rounded-[2px]`
- News empty states: `rounded-lg border border-border/50 p-8` → compact inline

### 4.4 Panel/Surface Model (Confirmed)

Three elevation levels — correct. New enforcement rules:
- Every panel with data **MUST** have a panel header: 28–32px, border-b, ALL CAPS 10px muted label
- Panel content padding: `p-3` (12px) for text content; `p-0` for edge-to-edge charts/tables
- Panel inner content padding for table rows: `px-2 py-1` (CompactTable pattern)

### 4.5 Table System (Enforce)

**CompactTable standard** (already documented in DESIGN_SYSTEM.md):
```
Row height: h-8 (32px)
Cell padding: px-2 py-1
Font: text-xs (12px)
Numbers: font-mono tabular-nums text-right
Headers: text-[10px] uppercase tracking-wider text-muted-foreground
Hover: hover:bg-muted/50 transition-colors
Border: divide-y divide-border/30 (not rounded-lg border per-row)
```

Any list of instruments, alerts, news articles, or financial data must use this — never `rounded-lg border per-row` cards.

**Exception**: ArticleCard card layout is acceptable when the viewport allows full-width article reading (e.g., standalone news page). In instrument news tab and workspace: compact row layout required.

### 4.6 Empty/Loading/Error State Rules

| State | Required Format | Max Height |
|---|---|---|
| Loading | Skeleton rows matching content shape | Same as loaded content |
| Empty (no data) | `<p className="p-3 text-xs text-muted-foreground">No data</p>` | 32px |
| Empty (no results) | Same + filter hint inline | 32px |
| Error | `<p className="p-3 text-xs text-destructive">Error · <button>Retry</button></p>` | 32px |
| Workspace empty | Max `py-6` centered — no icons, no decorative copy | 64px |

**Never**: `p-8`, `py-12`, `py-24` for empty/error states. Never a bordered card for an empty state.

### 4.7 Radius Policy Exceptions

None. `rounded-[2px]` everywhere. The only exception is shadcn Dialog/Sheet which uses the base radius token — ensure `components.json` has `"radius": 0.125`.

### 4.8 Color Usage Rules

- `rounded-[2px] bg-primary/15 text-primary` for HIGH-tier badge — already correct in ArticleCard
- `text-positive` / `text-negative` for financial values — already used consistently
- `hover:bg-muted/50` for interactive rows — confirmed in screener ✓
- `bg-primary/10 text-primary font-medium` for active nav item — confirmed in DESIGN_SYSTEM

### 4.9 Reusable Primitives Required

These must be created in Wave A before any page changes:

| Primitive | File | Purpose | Replaces |
|---|---|---|---|
| `CompactRow` | `components/data/CompactRow.tsx` | 32px h-8 clickable row with hover + keyboard | Per-page grid divs, rounded-lg button rows |
| `InlineEmptyState` | `components/data/InlineEmptyState.tsx` | `p-3 text-xs text-muted-foreground` one-liner | All p-8/py-12 empty states |
| `InlineErrorState` | `components/data/InlineErrorState.tsx` | Inline destructive bar with Retry | Rounded-lg error cards |
| `PanelHeader` | `components/data/PanelHeader.tsx` | 32px border-b, ALL CAPS 10px, with optional controls | Inconsistent CardHeader usage |
| `SessionStatsStrip` | `components/instrument/SessionStatsStrip.tsx` | Compact OHLCV session data strip (Open/High/Low/Vol/1D%) | Chart title placeholder |

---

## 5. Page-by-Page Redesign Plan

### 5.1 Shell / TopBar / GlobalSearch

**Files**: `components/shell/TopBar.tsx`, `components/shell/GlobalSearch.tsx`, `components/shell/IndexTicker.tsx`

**Current Problems** (confirmed + suspected):
- GlobalSearch: `CommandItem` uses shadcn defaults which may have `py-2` per row — needs `py-1.5`
- GlobalSearch: no "recent instruments" when query empty (localStorage-based recent visits)
- GlobalSearch: no keyboard navigation hint strip (↑↓ Navigate ↵ Select ⎋ Close)
- IndexTicker: suspected `gap-4` spacing between prices (needs confirmation)
- TopBar: uninspected — confirm 44px height and no layout issues

**Target Layout**:
```
[WORLDVIEW logo] | [GlobalSearch w-72 h-8] | [IndexTicker gap-2] | [Market status] | [AlertBell] | [⌘K] | [Avatar]
```

**Required Changes**:
1. GlobalSearch: add `EmptyState` section below CommandInput when query empty — show last 5 visited instruments from `localStorage['recent-instruments']` as CompactRows
2. GlobalSearch: add keyboard hint bar at bottom of results: `↑↓ Navigate  ↵ Open  ⎋ Close` in `text-[9px] text-muted-foreground`
3. GlobalSearch: ensure CommandItem has `py-1.5` not `py-2`
4. IndexTicker: `gap-4` → `gap-2` (after confirming)
5. TopBar: verify height ≤44px, no wasted space

**Backend/API**: None — recent instruments from localStorage only

**Acceptance Criteria**:
- [ ] GlobalSearch shows recent instruments when query is empty
- [ ] Keyboard hint visible below results
- [ ] TopBar total height ≤44px
- [ ] IndexTicker spacing ≤8px between tickers

---

### 5.2 Workspace / Dashboard

**Files**: `app/(app)/workspace/page.tsx`, `app/(app)/dashboard/page.tsx`

**Current Problems (Workspace)**:
1. `WorkspacePlaceholder`: `py-12 flex-col items-center justify-center` + "coming soon" text for screener and chat — 2/8 panel types are explicit stubs
2. `EmptyWorkspace`: `py-24` giant empty state
3. Hardcoded `demoEntityId = "entity-aapl"` and `demoInstrumentId = "ins-aapl"` for chart/fundamentals/graph panels — real seeded data may not match
4. CardContent `p-2` wrapping chart panels — acceptable (8px)

**Current Problems (Dashboard)**:
- Dashboard uses `gap-px p-1` which is correct ✓
- CardContent `pb-3` — minor, acceptable
- Individual widget internals (MorningBriefCard, PortfolioSummary, etc.) need inspection (flagged as gaps)

**Target Layout (Workspace)**:
- Replace `WorkspacePlaceholder` for screener: render a `CompactScreenerWidget` — pre-filtered screener with 5 rows, no filter panel, showing top market-cap results
- Replace `WorkspacePlaceholder` for chat: render a minimal `CompactChatWidget` — basic SSE chat input + response area without the full page chrome
- `EmptyWorkspace`: reduce from `py-24` to `py-8 text-xs`; remove decorative icon
- Hardcoded entity IDs: use the first result from `getTopMovers()` or configurable per-panel entity picker (deferred to Wave D)

**Required Changes**:
1. Create `WorkspaceScreenerWidget` — calls `runScreener()` with empty filters, shows top 10 by market_impact_score in CompactTable rows (no filter panel)
2. Create `WorkspaceScreenerPanel` → remove placeholder text and render the widget
3. `EmptyWorkspace`: reduce vertical padding, remove large icon, use inline text

**Acceptance Criteria**:
- [ ] All 8 workspace panel types render real or placeholder data (no "coming soon" copy)
- [ ] Empty workspace uses `py-8` max height
- [ ] Default 3 panels (Chart, News, Alerts) render without console errors

---

### 5.3 Instrument Header (Shared across all tabs)

**Files**: `app/(app)/instruments/[entityId]/page.tsx` (lines 127–205)

**Current Problems**:
1. `py-4` on header div → 64px+ header height (line 128)
2. Only 4 metrics in quick stats: Mkt Cap, 52W, P/E, 1D Ret (line 169)
3. `gap-4` between metrics (too wide)
4. Back nav hardcoded to `/dashboard` (line 120) — breaks browser history
5. "Price Chart" label (line 238) is redundant — replace with session stats
6. Chart container `p-4` (line 235) — wastes 32px of chart space

**Target Header Layout** (compact, ≤56px):
```
← [back]  AAPL [NASDAQ] [Technology]          $172.34 ▲ +1.23 (+0.72%) [● LIVE · 14:32]
Apple Inc. — maker of iPhone...
─────────────────────────────────────────────────────────────────────────────────────────
Mkt Cap 2.87T │ P/E 28.4 │ 52W 124–199 │ Vol 43.2M │ Open 171.12 │ Hi 173.01 │ Lo 170.88
```

**Required Changes**:
1. `py-4` → `py-2` on header div
2. Back nav: `<Link href="/dashboard">` → `<button onClick={() => router.back()}>` (use `useRouter`)
3. Quick stats: add `Volume`, `Open`, `Session High`, `Session Low` from `overview.quote` — with fallback "—"
4. Quick stats: `gap-4` → `gap-2 divide-x divide-border/40` — same-line separators
5. Replace "Price Chart" `<h2>` with `<SessionStatsStrip>` component showing OHLC bar
6. Chart container: `p-4` → `p-0` on the left side; chart fills to border

**API Data Needed**:
- `overview.quote.volume` — verify field exists in S9 CompanyOverview response
- `overview.quote.open` — verify
- `overview.quote.high` — verify
- `overview.quote.low` — verify

**Acceptance Criteria**:
- [ ] Instrument header ≤56px total height (from back nav to tabs)
- [ ] Quick stats shows ≥6 metrics (Mkt Cap, P/E, 52W, Vol, Open, 1D%)
- [ ] Back nav uses `router.back()` not hardcoded `/dashboard`
- [ ] Session stats replace "Price Chart" label above chart

---

### 5.4 Instrument Overview (Chart + Graph)

**Files**: `app/(app)/instruments/[entityId]/page.tsx` (TabsContent overview), `components/instrument/OHLCVChart.tsx`

**Current Problems**:
1. Chart `height: 280` hardcoded in `createChart()` call (OHLCVChart.tsx line 138)
2. Chart container: `border-b border-border/40 p-4 lg:border-b-0 lg:border-r` — p-4 wastes 32px
3. Entity graph right panel `320px` fixed — shows "Related Entities" in 320px but graph is often sparse
4. "Related Entities" label `mb-2` → `mb-1`

**Target Layout**:
```
[OHLCV Chart — full width, edge-to-edge, 360px min height]
[Session stats strip below chart: O: 171.12 | H: 173.01 | L: 170.88 | V: 43.2M | VWAP: 171.89]
───────────────────────────────────────────────────────────────────────────────────────────────
[Entity Relationship Graph — collapsible right panel, default 280px]
```

**Required Changes**:
1. `OHLCVChart.tsx`: change `height: 280` → `height: 360` in `createChart()` call
2. Chart container: `p-4` → `p-0` — chart fills to edge
3. Add `<SessionStatsStrip>` component below chart timeframe buttons (shows Open/High/Low/Vol from last OHLCV bar)
4. Right graph panel: reduce from `320px` to `280px`

**Acceptance Criteria**:
- [ ] Chart renders at ≥360px height
- [ ] Chart content fills panel edge-to-edge (no 16px gap around canvas)
- [ ] Session stats strip visible below timeframe buttons

---

### 5.5 Instrument Fundamentals Tab

**Files**: `components/instrument/FundamentalsTab.tsx`

**Current Problems**:
1. `grid grid-cols-2 gap-6 p-4` — `gap-6` (24px column gap), `p-4` (16px outer padding)
2. Section content is already good (`divide-y divide-border/40` with `py-1` rows) ✓
3. Loading skeleton uses `p-4` outer — consistent violation

**Target Layout**:
```
VALUATION                    PROFITABILITY              GROWTH (YoY)
─────────────────────────    ────────────────────────    ─────────────────
Market Cap    2.87T          Gross Margin  44.1% [●]    Revenue Growth 8.3%
P/E Ratio     28.4x [●]     Operating M.  26.8% [●]    Earnings Growth 6.1%
[...]
```

**Required Changes**:
1. `gap-6` → `gap-2` in the grid (reduces column gap from 24px to 8px)
2. `p-4` → `p-3` outer padding
3. Loading skeleton: `p-4` → `p-3`

**Acceptance Criteria**:
- [ ] All 20+ metric rows visible without scroll at 1080p
- [ ] Column gap ≤8px
- [ ] Outer padding ≤12px

---

### 5.6 Instrument News Tab

**Files**: `app/(app)/instruments/[entityId]/page.tsx` (TabsContent news section, lines 267–302)

**Current Problems**:
1. Each article wrapped: `<div key={article.article_id} className="px-4 py-3">` — adds 24px vertical + 32px horizontal per article
2. `ArticleCard` internally has `p-3 rounded-lg` — doubling the padding issue
3. "Load more articles" is `<button className="text-xs text-muted-foreground">` — not visible as a button
4. News empty state: `<p className="p-6 text-sm text-muted-foreground">` — p-6 empty state

**Target Layout**:
```
[Toggle: Card / List]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[HIGH] Reuters · 2h ago    Score 94          Apple Beats Q1 — Services ↗
[STD] Bloomberg · 4h ago   Score 71          Tim Cook Comments on AI → WWDC ↗
[LOW] PRN · 1d ago         Score 31          New Retail Store Shanghai         ↗
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Load more (20 / 87) → outlined button]
```

**Required Changes**:
1. Remove `<div className="px-4 py-3">` wrapper — articles in `divide-y divide-border/30` directly
2. Add compact list mode: `<CompactNewsRow>` (h-8 row: tier badge, source, time, score, title, link)
3. Add list/card toggle button in tab header area
4. "Load more": replace plain `<button>` with `<Button variant="outline" size="sm">Load more ({count} remaining)</Button>`
5. Empty state: `p-6 text-sm` → `<InlineEmptyState message="No news articles for this entity." />`

**Acceptance Criteria**:
- [ ] 20 articles visible without scroll at 1080p in compact list mode
- [ ] Compact list row height h-8 (32px)
- [ ] Load more button clearly styled as outlined button
- [ ] Empty state ≤32px height

---

### 5.7 Instrument Intelligence Tab

**Files**: `components/instrument/IntelligenceTab.tsx` (uninspected — must read before Wave C)

**Known issues from DESIGN_SYSTEM.md and architecture knowledge**:
- EntityGraph in Intelligence tab may load full depth-2 graph on mount (performance concern)
- Brief panel duplicates instrument-level brief
- No severity count strip

**Planned Required Changes**:
1. Add severity count strip: `HIGH 2 │ MEDIUM 5 │ LOW 12` in 28px panel header
2. Lazy-load EntityGraph: show only on tab activate (`useEffect` with intersection observer or tab state)
3. In Intelligence tab: collapse the brief section (instrument-level brief is already shown above tabs)

---

### 5.8 Screener

**Files**: `app/(app)/screener/page.tsx`

**Current Problems (confirmed from code)**:
1. Only 6 columns: Ticker, Name, Price (always "—"), Change%, Mkt Cap, Score
2. "Price" column has no data source (`<td>—</td>` hardcoded) — waste of column space
3. Filter panel: `w-64 shrink-0 flex-col gap-4 border-r bg-card p-4 overflow-y-auto` — always visible, no collapse, `p-4` inner padding
4. Only 3 filters: search, sector, cap tier — no P/E range, no market cap range, no beta
5. `COLUMNS` array only defines 6 columns
6. Filter panel Apply/Reset buttons use `mt-auto` (pushed to bottom of panel) — good UX but wastes space

**Target Layout**:
```
[≡ Filters] [Search...] [Sector ▼] [Cap ▼]    [Apply] [Reset]     847 instruments
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TICKER NAME                 CHANGE%  MKT CAP   P/E      REVENUE   BETA   SCORE
AAPL   Apple Inc.          +0.72%   2.87T     28.4x    94.6B     1.23   [■■■■ 87]
MSFT   Microsoft Corp.     -0.12%   3.12T     35.1x    87.3B     0.89   [■■■░ 72]
[...]
[Load more (40 / 847) ▼]
```

**Required Changes**:
1. Remove "Price" column from `COLUMNS` array
2. Add columns: `P/E Ratio` (sortKey: `pe_ratio`), `Revenue TTM` (sortKey: `revenue_ttm`), `Beta` (sortKey: `beta`)
3. Verify `pe_ratio`, `revenue_ttm`, `beta` exist in `ScreenerResult` type — if not, extend API response
4. Replace always-visible left panel with top filter bar (collapsible to icon row via toggle)
5. Filter panel toggle: `[≡ Filters]` button toggles `showFilters` state → sliding filter row
6. Filter bar: inline filters (Search | Sector select | Cap tier buttons | P/E range | Apply | Reset)
7. Results count in header bar right-aligned

**API Dependencies**:
- `pe_ratio` in ScreenerResult — verify in `types/api.ts` and S9 response
- `beta` in ScreenerResult — check if in fundamentals response; may need S9 backend change
- `revenue_ttm` in ScreenerResult — check `revenue_growth_yoy` vs `revenue_ttm` field names

**Acceptance Criteria**:
- [ ] Screener table has ≥8 columns, none permanently showing "—"
- [ ] Filter panel collapsible via toggle
- [ ] Row click navigates to instrument detail
- [ ] HeatCell applied to Change%, Score columns

---

### 5.9 Portfolio

**Files**: `app/(app)/portfolio/page.tsx`

**Current Problems (confirmed from code)**:
1. Main container: `space-y-4 p-6` (line 722) — 24px outer padding all sides
2. Disabled "Add Position" button: `<Button size="sm" disabled title="Coming soon..." className="gap-1 opacity-60">` (line 764) — placeholder button in primary action area
3. HoldingsTable: CSS grid div (not semantic `<table>`) — confirmed (line 184–293)
4. Empty state in HoldingsTable: `<div className="flex h-24 items-center justify-center">` — 96px empty state
5. Same h-24 in TransactionsTable (line 309) and WatchlistTable (line 411)
6. No sector exposure panel — entire missing feature
7. No realized P&L — only unrealised shown (line 83 PnlSummaryRowProps)
8. KPI tiles have `hover:bg-muted/50 transition-colors` but are not interactive (lines 101, 111, 126, 141)
9. KPI values use `text-base font-semibold` — actually acceptable (not text-2xl as previous report claimed about PortfolioSummary widget; this is the main portfolio page)

**Target Layout**:
```
Portfolio [My Portfolio ▼]                                     [Connect Brokerage]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total Value  Today P&L    Unrealised P&L  Realized P&L
$124,328     +$234 +0.2%  +$8,234 +7.1%  +$2,100
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Holdings] [Transactions] [Watchlist] [Brokerages]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TICKER  NAME          QTY    AVG COST  CURRENT   VALUE     P&L       P&L%
AAPL    Apple Inc.    100    $150.00   $172.34   $17,234   +$2,234  +14.9%
[table rows h-8, divide-y]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ALLOCATION BY SECTOR
Technology    42% ████████░░
Healthcare    18% ████░░░░░░
[compact horizontal bars]
```

**Required Changes**:
1. `space-y-4 p-6` → `space-y-3 p-3` on main container
2. Remove disabled "Add Position" button — hidden until implemented
3. KPI tiles: remove `hover:bg-muted/50 transition-colors` (non-interactive tiles should not have hover state)
4. Add "Realized P&L" as 4th KPI (compute from transactions: sum SELL total - avg_cost × qty for closed positions)
5. HoldingsTable: convert div grid → semantic `<table>` with `CompactTable` pattern (h-8 rows, px-2 py-1)
6. Empty states: `flex h-24 items-center justify-center` → `<InlineEmptyState>` (32px)
7. Add sector exposure panel below holdings table (fan-out from holdings + fundamentals)
8. Holdings tab Card: remove Card wrapper, use borderless full-width table

**Backend/API Dependencies**:
- Realized P&L: computable client-side from transactions (`getTransactions()` already fetched)
- Sector exposure: each holding has `h.ticker` → can use screener fan-out to get `gics_sector` per holding, then group. OR add `sector` field to `Holding` type from S9.

**Acceptance Criteria**:
- [ ] Portfolio page outer padding ≤12px
- [ ] No disabled stub buttons visible
- [ ] KPI tiles not interactive (no hover state)
- [ ] Holdings is semantic `<table>` with h-8 rows
- [ ] Empty states ≤32px
- [ ] Sector exposure panel visible above fold for portfolios with ≥5 holdings

---

### 5.10 Alerts & News

**Files**: `app/(app)/alerts/page.tsx`, `components/alerts/AlertsList.tsx`, `components/news/ArticleCard.tsx`

**Current Problems (confirmed)**:
1. Page: `mx-auto max-w-4xl space-y-4 p-6` — constrained to 896px centered, NOT full-width
2. Tab header: `grid w-full grid-cols-3` TabsList with `mb-4` — 16px below tabs
3. `AlertsList` empty state: `rounded-lg border border-border/50 p-8 text-center` — p-8 large empty state
4. `AlertRow button`: `rounded-lg border border-border/50 bg-card p-3` — card-style with rounded-lg
5. News tab uses `space-y-2` of `ArticleCard` — card layout not compact table
6. News empty states: `rounded-lg border border-border/50 p-8 text-center` — large
7. Error states: `rounded-lg border border-destructive/30 bg-destructive/10 p-6 text-center` — large cards

**Target Layout**:
```
ALERTS & NEWS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[🔔 Alerts] [📰 News Feed] [📈 Top Today]          [ALL ▼ severity]

SEV   TICKER  TYPE                MESSAGE                         TIME
■ CRIT AAPL   PRICE_SPIKE         AAPL up 8.2% in 15 min          2m ago
■ HIGH MSFT   EARNINGS_BEAT       MSFT Q1 EPS $2.94 vs $2.81 est  1h ago
■ MED  GOOGL  ANALYST_DOWNGRADE   Goldman cuts GOOGL to Neutral    3h ago
[no rounded borders per row; divide-y; h-8 rows]
```

**Required Changes**:
1. Remove `max-w-4xl mx-auto` — full-width layout
2. `p-6` → `p-3` outer padding
3. `AlertRow`: `rounded-lg border border-border/50 bg-card p-3` → `flex items-center gap-3 px-3 py-1.5 hover:bg-muted/40 border-b border-border/30` (no rounded border per row)
4. AlertsList: wrap rows in `<div className="divide-y divide-border/30">` not `<ul className="space-y-1.5">`
5. AlertsList empty state: `rounded-lg p-8` → `<InlineEmptyState message="No pending alerts — all caught up." />`
6. News tabs: replace `space-y-2` ArticleCard stacks with compact news rows (same as instrument news compact mode)
7. Error states: compact inline bar, not rounded-lg card with p-6
8. `mb-4` below TabsList → `mb-0` or `mb-1`

**Acceptance Criteria**:
- [ ] Alerts page is full-width (no max-w constraint)
- [ ] Alert rows are `h-8` compact table rows with divide-y, not rounded-lg cards
- [ ] Empty state ≤32px
- [ ] News feed tabs show compact rows, not card stacks

---

### 5.11 AI Chat

**Files**: `app/(app)/chat/page.tsx`, `components/shell/AskAiPanel.tsx` (uninspected)

**Known state (from DESIGN_SYSTEM.md and architecture)**:
- SSE streaming with blinking cursor — correct
- Amber AI styling — correct
- Enter to submit, Shift+Enter newline — correct

**Suspected issues (must verify on inspection)**:
- Chat message text size may be `text-sm` (14px) — should be `text-xs` (12px) for terminal density
- Chat container may have `p-4` or `p-6` padding
- No "clear conversation" or "copy" buttons visible

**Wave E action**: Inspect and audit chat/settings pages.

---

### 5.12 Settings / Profile

**File**: `app/(app)/settings/page.tsx` (uninspected — Wave E)

Gap — must inspect before claiming coverage.

---

### 5.13 Morning Brief (Dashboard)

**File**: `components/dashboard/MorningBriefCard.tsx` (uninspected)

**Suspected issues**:
- Markdown H2 headings at 14-16px look like article, not terminal briefing
- Default state: likely expanded full markdown
- Large markdown body with prose-scale typography

**Planned fix** (pending inspection):
- Apply `[&_h2]:text-[10px] [&_h2]:uppercase [&_h2]:tracking-wider [&_h2]:text-muted-foreground`
- Apply `[&_p]:text-xs [&_p]:leading-relaxed`
- Default collapsed to preview + "Read full brief" expand

---

### 5.14 Loading/Error/Stale States (Global)

All loading states must use **skeleton rows matching content shape**:

```tsx
// For table loading:
Array.from({ length: 5 }).map((_, i) => (
  <div key={i} className="flex h-8 items-center gap-2 px-2">
    <Skeleton className="h-3 w-12" />
    <Skeleton className="h-3 flex-1" />
    <Skeleton className="h-3 w-16" />
  </div>
))
```

All error states must use the inline bar pattern:
```tsx
<div className="flex items-center gap-2 px-3 py-1.5 text-xs">
  <span className="text-destructive">Failed to load.</span>
  <button onClick={onRetry} className="text-muted-foreground hover:text-foreground underline">Retry</button>
</div>
```

---

## 6. Data-Density Plan

### Instrument Header Strip

| Currently Visible | Add | Source | Availability | Fallback |
|---|---|---|---|---|
| Ticker, exchange, sector | — | existing | ✓ | — |
| Live price + change | — | LiveQuoteBadge | ✓ | — |
| Mkt Cap, 52W, P/E, 1D% | Volume | `overview.quote.volume` | verify S9 response | "—" |
| — | Session Open | `overview.quote.open` | verify S9 response | last OHLCV bar open |
| — | Session High | `overview.quote.high` | verify S9 response | last OHLCV bar high |
| — | Session Low | `overview.quote.low` | verify S9 response | last OHLCV bar low |

### Screener Results

| Currently Visible | Add | Source | Availability | Fallback |
|---|---|---|---|---|
| Ticker, Name | — | ScreenerResult | ✓ | — |
| Price (always "—") | **Remove this column** | — | — | — |
| Change%, Mkt Cap, Score | P/E Ratio | `ScreenerResult.pe_ratio` | check type | "—" |
| — | Revenue TTM | `ScreenerResult.revenue_ttm` | check type | "—" |
| — | Beta | `ScreenerResult.beta` | check type; may need backend | "—" |

### Portfolio

| Currently Visible | Add | Source | Availability | Fallback |
|---|---|---|---|---|
| Total Value, Today P&L, Unrealised P&L | Realized P&L | compute from transactions | client-side (existing query) | "—" |
| Holdings (8 cols) | Sector col | `fundamentals.gics_sector` per holding | requires per-holding fetch or S9 | "—" |
| — | Sector exposure strip | group by GICS from fundamentals fan-out | requires per-holding fundamentals | hide panel |

### News / Articles

| Currently Visible | Add | Source | Availability | Fallback |
|---|---|---|---|---|
| Title, source, time | Compact list mode (36px rows) | layout change only | ✓ | — |
| Relevance score badge | Tier badge inline (TOP/STD/LOW) | `article.routing_tier` | ✓ | "STD" |
| — | Impact window summary | `article.impact_windows` | API field | hide |

---

## 7. Interaction Plan

| Surface | Current | Issue | Required Fix |
|---|---|---|---|
| Instrument back nav | `<Link href="/dashboard">` | Breaks back-stack, always goes to dashboard | `router.back()` or breadcrumb |
| GlobalSearch | Type → suggestions | No recent instruments when empty; no keyboard hint | Add recent section + hint strip |
| Instrument tabs | Click only | No keyboard shortcut to switch tabs | `useHotkeys('1/2/3/4')` when page focused |
| Chart timeframe | Click | No keyboard shortcut | Add keyboard hints in button tooltip |
| News "Load more" | Plain `<button>` | Not recognizable as button | `<Button variant="outline" size="sm">` |
| Screener rows | Click navigates | Correct ✓ | Keep |
| Portfolio holdings | Click navigates | Already implemented with `onRowClick` ✓ | Keep |
| AlertRow | Click navigates | Already implemented ✓ | Keep |
| InstrumentBriefPanel | Already collapsed ✓ | None | Keep |
| Graph node click | Unknown | Should navigate to entity | Inspect EntityGraphPanel |
| Workspace placeholder | Renders "coming soon" | Dead panel | Implement or remove |
| Article card | Opens external link | Correct ✓ | Keep |
| GlobalSearch ⌘K | Opens search | Correct ✓ | Keep |

---

## 8. Implementation Waves

### Wave A — Terminal Foundation & Radius/Padding Enforcement

**Goal**: Enforce 2px radius, compact padding, and terminal-grade empty states across all existing components. Zero backend work.

**Depends on**: None

**Files affected**:
- `components/news/ArticleCard.tsx`
- `components/alerts/AlertsList.tsx`
- `app/(app)/alerts/page.tsx`
- `app/(app)/portfolio/page.tsx`
- `app/(app)/instruments/[entityId]/page.tsx`
- `components/instrument/FundamentalsTab.tsx`
- `components/instrument/OHLCVChart.tsx`
- `components/dashboard/MorningBriefCard.tsx` (inspect first)
- `components/dashboard/PortfolioSummary.tsx` (inspect first)
- `components/shell/GlobalSearch.tsx`
- `components/shell/IndexTicker.tsx` (inspect first)

**Tasks**:

#### T-A-1-01: Primitives — InlineEmptyState, InlineErrorState, PanelHeader
**Type**: impl
**Target files**: `components/data/InlineEmptyState.tsx`, `components/data/InlineErrorState.tsx`, `components/data/PanelHeader.tsx`
**What to build**: Three primitive components. InlineEmptyState: `<p className="px-3 py-1.5 text-xs text-muted-foreground">`. InlineErrorState: inline destructive bar with Retry button. PanelHeader: 32px `border-b border-border/40` with ALL CAPS 10px title + optional right-side controls slot.
**Tests**: Vitest render tests for all three — verify className output and text rendering.
**AC**: All three render correctly; no props cause crashes; accessible labels.

#### T-A-1-02: ArticleCard — Fix rounded-lg → rounded-[2px] + compact layout
**Type**: impl
**depends_on**: T-A-1-01
**Target files**: `components/news/ArticleCard.tsx`
**What to build**:
1. Replace `rounded-lg border border-border/50 bg-card` → `rounded-[2px] border border-border/40 bg-card`
2. Keep existing layout (card mode still needed for standalone news pages)
3. Add `compact?: boolean` prop — when true, renders h-9 compact row: `[tier] source · time  title  score ↗`
**Tests**: Vitest: renders card mode by default; compact mode renders h-9 row; LIGHT tier opacity-60 in both modes.
**AC**: No rounded-lg classes in component. Compact mode row height h-9.

#### T-A-1-03: AlertRow — Fix rounded-lg → compact table row
**Type**: impl
**depends_on**: T-A-1-01
**Target files**: `components/alerts/AlertsList.tsx`
**What to build**:
1. AlertRow: replace `rounded-lg border border-border/50 bg-card p-3` → `flex items-center gap-3 px-3 py-1.5 hover:bg-muted/40 cursor-pointer`
2. AlertsList: replace `<ul className="space-y-1.5">` → `<div className="divide-y divide-border/30">`
3. Empty state: replace `rounded-lg border p-8` → `<InlineEmptyState message="No pending alerts." />`
4. Loading skeleton: replace `rounded-lg border p-3` skeletons → flat `h-8 px-3 py-1.5` skeletons
**Tests**: RTL: renders correct number of rows; clicking a row calls onNavigate; empty state renders inline.
**AC**: No rounded-lg; alert rows are divide-y; empty state ≤32px.

#### T-A-1-04: Alerts page — Remove max-w-4xl, reduce padding
**Type**: impl
**depends_on**: T-A-1-03
**Target files**: `app/(app)/alerts/page.tsx`
**What to build**:
1. Remove `mx-auto max-w-4xl` from page container
2. `space-y-4 p-6` → `space-y-2 p-3`
3. News tabs: pass `compact={true}` to ArticleCard (after T-A-1-02)
4. Error states in NewsFeedTab/TopTodayTab: replace `rounded-lg p-6` → `<InlineErrorState>`
5. News empty states: replace `rounded-lg p-8` → `<InlineEmptyState>`
6. `mb-4` below TabsList → `mb-2`
**Tests**: Vitest: page renders without max-w class; compact article cards in news tabs.
**AC**: Full-width page, outer padding ≤12px, no rounded-lg card empty states.

#### T-A-1-05: Portfolio page — Remove p-6, remove disabled stub button, fix empty states
**Type**: impl
**depends_on**: T-A-1-01
**Target files**: `app/(app)/portfolio/page.tsx`
**What to build**:
1. `space-y-4 p-6` → `space-y-3 p-3` on main container
2. Remove disabled "Add Position" button completely (and its `title` and `Plus` import if unused)
3. Remove `hover:bg-muted/50 transition-colors` from PnlSummaryRow tiles (non-interactive)
4. HoldingsTable empty state: `flex h-24 items-center justify-center` → `<InlineEmptyState message="No holdings." />`
5. TransactionsTable empty state: same
6. WatchlistTable empty state: same
7. Loading skeleton: `space-y-4 p-6` → `space-y-3 p-3`
**Tests**: RTL: empty state uses InlineEmptyState; PnlSummaryRow tiles have no hover class; disabled button absent.
**AC**: No p-6; no disabled stub buttons; KPI tiles have no hover state; empty states ≤32px.

#### T-A-1-06: Instrument page — Fix header py-4, back nav, chart padding
**Type**: impl
**Target files**: `app/(app)/instruments/[entityId]/page.tsx`
**What to build**:
1. Header div `py-4` → `py-2`
2. Back nav: `<Link href="/dashboard">` → `<button onClick={() => router.back()}>` (add `useRouter` import)
3. Quick stats: `gap-4` → `gap-2`
4. Chart container: `p-4` → `p-0` on left panel
5. News tab: remove `<div className="px-4 py-3">` wrapper around each ArticleCard
6. News tab: add compact/card toggle button in tab header area; default to compact
7. News empty state: `p-6 text-sm` → `<InlineEmptyState>`
8. "Load more": plain `<button>` → `<Button variant="outline" size="sm">Load more ({count} remaining)</Button>`
**Tests**: RTL: back nav calls router.back(); news tab has no px-4 py-3 wrapper; load more is a Button.
**AC**: Header ≤56px; news articles have no outer padding wrapper; back nav non-hardcoded.

#### T-A-1-07: OHLCVChart — Increase height from 280 to 360
**Type**: impl
**Target files**: `components/instrument/OHLCVChart.tsx`
**What to build**:
1. In `createChart()` call: `height: 280` → `height: 360`
2. Skeleton height: `h-[280px]` → `h-[360px]`
3. Error fallback div: `h-[280px]` → `h-[360px]`
**Tests**: Vitest: chart container has correct height in skeleton and error fallback.
**AC**: Chart renders at 360px minimum height; skeleton matches.

#### T-A-1-08: FundamentalsTab — Reduce gap and padding
**Type**: impl
**Target files**: `components/instrument/FundamentalsTab.tsx`
**What to build**:
1. `grid grid-cols-2 gap-6 p-4` → `grid grid-cols-2 gap-2 p-3`
2. `lg:grid-cols-3` kept — correct at large screens
3. Loading skeleton: `p-4` → `p-3`
**Tests**: Vitest: fundamentals renders with gap-2 and p-3 classes.
**AC**: Column gap ≤8px; outer padding ≤12px.

#### T-A-1-09: GlobalSearch — Add recent instruments and keyboard hint
**Type**: impl
**Target files**: `components/shell/GlobalSearch.tsx`
**What to build**:
1. When `query === ""` and `open`, show last 5 instruments from `localStorage['recent-instruments']` as CompactRow items
2. When navigateTo fires, append entity to localStorage['recent-instruments'] (max 5, deduplicated)
3. Add hint bar at bottom of results list: `<div className="border-t border-border/40 px-3 py-1 text-[9px] text-muted-foreground">↑↓ Navigate · ↵ Open · ⎋ Close</div>`
4. Ensure CommandItem uses `py-1.5` not default
**Tests**: RTL: hint bar renders; localStorage instruments appear when query empty.
**AC**: Recent instruments show on empty query; keyboard hint visible; navigateTo writes to localStorage.

**Validation Gate (Wave A)**:
- [ ] ruff + mypy: N/A (TypeScript; run `pnpm run lint` and `pnpm run type-check`)
- [ ] Vitest: all existing tests pass + new tests added in this wave
- [ ] No `rounded-lg` in updated component files
- [ ] No `p-6`, `p-8`, `py-12`, `py-24` in updated component files
- [ ] No `max-w-4xl` in alerts page
- [ ] No disabled stub buttons visible

**Regression guardrails**:
- Article card tests (`__tests__/`) that assert on rounded-lg class will need updating → change to rounded-[2px]
- AlertsList tests asserting on space-y-1.5 → change to divide-y
- Portfolio page tests asserting on Add Position button presence → remove assertions

**Screenshots to capture (Wave A)**:
- `/alerts` before + after
- `/portfolio` before + after
- `/instruments/[any-seeded-id]` news tab before + after
- `/instruments/[any-seeded-id]` overview tab (chart height) before + after

---

### Wave B — Screener Redesign + Instrument Header Data Density

**Goal**: Professional screener with useful columns; instrument header with session stats. May require minor S9 API verification.

**Depends on**: Wave A

**Files affected**:
- `app/(app)/screener/page.tsx`
- `types/api.ts`
- `app/(app)/instruments/[entityId]/page.tsx`
- `components/instrument/SessionStatsStrip.tsx` (new)
- `lib/gateway.ts`

**Tasks**:

#### T-B-2-01: Verify ScreenerResult type fields
**Type**: impl (type verification)
**Target files**: `apps/worldview-web/types/api.ts`, `apps/worldview-web/lib/gateway.ts`
**What to build**: Read `ScreenerResult` type definition and S9 screener response. Determine which of these fields exist: `pe_ratio`, `beta`, `revenue_ttm`. Document gaps. If fields exist in API but not in type: add to type. If fields don't exist in API: mark as BACKEND_REQUIRED.
**AC**: Fields documented as present or backend-required.

#### T-B-2-02: Screener — Remove Price column, add P/E + 2 additional columns
**Type**: impl
**depends_on**: T-B-2-01
**Target files**: `app/(app)/screener/page.tsx`
**What to build**:
1. Remove `{ header: "Price", sortKey: null, align: "right" }` from COLUMNS
2. Add `{ header: "P/E", sortKey: "pe_ratio", align: "right" }` (if T-B-2-01 confirms field exists)
3. Add `{ header: "Revenue", sortKey: "revenue_ttm", align: "right" }` (if confirmed)
4. Add `{ header: "Beta", sortKey: "beta", align: "right" }` (if confirmed)
5. In ScreenerRow: render `pe_ratio` with `formatRatio()`; `revenue_ttm` with `formatMarketCap()`; `beta` with `toFixed(2)`
6. Apply HeatCell to `daily_return` column (via `<HeatCell score={result.daily_return * 10}>`—scaled to -100/+100 range)
**Tests**: RTL: ScreenerRow renders pe_ratio; no Price column; HeatCell present on change% column.
**AC**: Table has ≥8 columns; no column shows "—" for all rows when data available.

#### T-B-2-03: Screener — Collapsible filter panel → top filter bar
**Type**: impl
**Target files**: `app/(app)/screener/page.tsx`
**What to build**:
1. Add `showFilters` state (default: false — collapsed)
2. Add filter toggle button in results header bar: `<Button variant="ghost" size="sm" onClick={...}><SlidersHorizontal /></Button>`
3. Move filters from left panel to collapsible horizontal bar below header:
   - When `showFilters=false`: bar hidden
   - When `showFilters=true`: show inline filter row (Search input | Sector select | Cap tier buttons | Apply | Reset)
4. Remove the entire `<aside className="w-64...">` left panel
5. Update layout: `flex h-full overflow-hidden` → `flex flex-col h-full` (no more left panel)
**Tests**: RTL: filter toggle shows/hides filter bar; filters still apply correctly.
**AC**: No left panel; full-width table; filter toggle button in header; filters work correctly.

#### T-B-2-04: SessionStatsStrip component + instrument header
**Type**: impl
**Target files**: `components/instrument/SessionStatsStrip.tsx` (new), `app/(app)/instruments/[entityId]/page.tsx`
**What to build**:

SessionStatsStrip:
```tsx
// Props: { open, high, low, volume, vwap } (all number | null)
// Layout: O: 171.12 · H: 173.01 · L: 170.88 · V: 43.2M
// className: flex gap-3 px-4 py-1.5 border-b border-border/40 bg-card/50 text-[10px] font-mono tabular-nums
```

Instrument page:
1. Replace `<h2 className="mb-2 text-xs..."}>Price Chart</h2>` with `<SessionStatsStrip>` passing `overview.quote` fields
2. Add quick stats: Volume, Open, Session High, Session Low (from `overview.quote` — fallback "—")
3. Quick stats: use `divide-x divide-border/40` separator style instead of `gap-4`

**Tests**: Vitest: SessionStatsStrip renders with all fields; shows "—" for null fields.
**AC**: "Price Chart" label gone; session stats strip visible below timeframe buttons; quick stats has ≥6 metrics.

**Validation Gate (Wave B)**:
- [ ] Screener table has ≥8 columns
- [ ] No Price column showing all "—"
- [ ] Filter panel collapsible
- [ ] Session stats strip visible on instrument overview
- [ ] All existing screener and instrument tests pass

---

### Wave C — Portfolio Data Density + News Compact Mode

**Goal**: Portfolio sector exposure, realized P&L, semantic holdings table. Full compact news implementation.

**Depends on**: Wave A, Wave B

**Files affected**:
- `app/(app)/portfolio/page.tsx`
- `components/dashboard/PortfolioSummary.tsx` (after inspection)
- `components/news/ArticleCard.tsx` (compact mode already added in Wave A)
- `components/instrument/IntelligenceTab.tsx` (inspect + severity count strip)
- `app/(app)/instruments/[entityId]/page.tsx` (news compact default)

**Tasks**:

#### T-C-3-01: Portfolio — Semantic holdings table + realized P&L
**Type**: impl
**Target files**: `app/(app)/portfolio/page.tsx`
**What to build**:
1. Replace `HoldingsTable` CSS grid div → semantic `<table>` with shadcn `Table`, `TableHeader`, `TableRow`, `TableCell`
2. Row height: `h-8 min-h-[2rem]` on each `<TableRow>`
3. Cell padding: `px-2 py-1` on each `<TableCell>`
4. Add "Realized P&L" to `PnlSummaryRowProps` and compute from transactions:
   ```ts
   // Sum of: (sell price - avg_cost) * qty for each completed SELL transaction
   // Grouped by ticker; match BUY avg_cost from holdings
   ```
5. Add Realized P&L tile as 5th KPI (or replace unrealised P&L%) — choose based on screen space
**Tests**: RTL: `<table>` element present in DOM for holdings; realized P&L renders as number.
**AC**: Holdings table passes axe accessibility; h-8 rows; realized P&L visible.

#### T-C-3-02: Portfolio — Sector exposure panel
**Type**: impl
**depends_on**: T-C-3-01
**Target files**: `app/(app)/portfolio/page.tsx`
**What to build**:
1. Create `SectorAllocationPanel` sub-component
2. Fetch fundamentals for each holding instrument: `Promise.all(holdings.map(h => getFundamentals(h.instrument_id)))`
3. Group by `gics_sector`; compute allocation % as (sector_value / total_value)
4. Render compact horizontal bars: `Technology 42% ████████░░`
5. Show below PnlSummaryRow, above tabs — always visible
6. When no fundamentals data: render `<InlineEmptyState message="Sector data unavailable." />`
**Tests**: RTL: renders sector bars; handles all-null sectors; accessible labels.
**AC**: Sector allocation visible above holdings tab; shows ≥ 1 sector for seeded portfolio.

#### T-C-3-03: Intelligence tab — Severity count strip + lazy graph
**Type**: impl
**Target files**: `components/instrument/IntelligenceTab.tsx`
**What to build** (after inspecting the file):
1. Add severity count strip: `HIGH n │ MEDIUM n │ LOW n` in a 28px bar above contradictions panel
2. Ensure EntityGraph is lazy-loaded (already uses next/dynamic — verify SSR:false is set)
**Tests**: RTL: severity count renders correctly.
**AC**: Count strip shows correct counts; graph doesn't load until tab is active.

**Validation Gate (Wave C)**:
- [ ] Holdings is `<table>` element with h-8 rows
- [ ] Sector allocation panel visible for seeded portfolio
- [ ] Realized P&L KPI visible
- [ ] All portfolio RTL tests pass

---

### Wave D — Workspace Overhaul + Dashboard Widget Audit

**Goal**: Remove workspace "coming soon" panels; audit and fix all dashboard widgets.

**Depends on**: Wave A

**Files affected**:
- `app/(app)/workspace/page.tsx`
- `components/dashboard/MorningBriefCard.tsx`
- `components/dashboard/PortfolioSummary.tsx`
- `components/dashboard/RecentAlerts.tsx`
- `components/dashboard/WatchlistNews.tsx`
- `components/dashboard/TopMovers.tsx`
- `components/dashboard/EconomicCalendar.tsx`

**Tasks**:

#### T-D-4-01: WorkspaceScreenerWidget — replace screener placeholder
**Type**: impl
**Target files**: `app/(app)/workspace/page.tsx`
**What to build**:
1. Create `WorkspaceScreenerWidget` — calls `runScreener()` with empty filters, limit 10
2. Renders a `CompactTable` (no filter panel): Ticker, Name, Mkt Cap, Score, Change%
3. Row click navigates to instrument detail
4. Replace `case "screener": return <WorkspacePlaceholder type="screener" />` with `return <WorkspaceScreenerWidget />`
**Tests**: RTL: WorkspaceScreenerWidget renders table; placeholder text absent.
**AC**: Screener panel shows real data; no "coming soon" text.

#### T-D-4-02: WorkspaceChatWidget — replace chat placeholder
**Type**: impl
**Target files**: `app/(app)/workspace/page.tsx`
**What to build**:
1. Create compact `WorkspaceChatWidget` — SSE-based mini-chat
2. Input at bottom (h-8 input + send button), response area above
3. No full chat history — just last 5 messages in compact `text-xs` display
4. Replace `case "chat": return <WorkspacePlaceholder type="chat" />` with `return <WorkspaceChatWidget />`
**Tests**: RTL: WorkspaceChatWidget renders input; no placeholder text.
**AC**: Chat panel shows usable input; no "coming soon" text.

#### T-D-4-03: EmptyWorkspace + workspace padding
**Type**: impl
**Target files**: `app/(app)/workspace/page.tsx`
**What to build**:
1. `EmptyWorkspace`: `py-24` → `py-8`; remove large icon; `text-sm` → `text-xs`
2. Any remaining `WorkspacePlaceholder` component: replace `py-12 flex-col items-center justify-center` → `<InlineEmptyState message="Panel content coming soon." />`
**Tests**: RTL: EmptyWorkspace renders; no py-24 class.
**AC**: Empty workspace ≤64px height.

#### T-D-4-04: Dashboard widgets — audit and fix
**Type**: impl
**Target files**: `components/dashboard/MorningBriefCard.tsx`, `components/dashboard/PortfolioSummary.tsx`, `components/dashboard/RecentAlerts.tsx`, `components/dashboard/WatchlistNews.tsx`
**What to build** (pending inspection):
1. MorningBriefCard: apply `[&_h2]:text-[10px] [&_h2]:uppercase [&_h2]:tracking-wider [&_h2]:text-muted-foreground [&_p]:text-xs`; add expand/collapse (max-height 200px collapsed)
2. PortfolioSummary: verify no `text-2xl` for KPI values — fix if found
3. RecentAlerts: convert from card rows to compact table rows (same pattern as T-A-1-03)
4. WatchlistNews: verify ArticleCard is compact mode; apply compact={true} prop
**Tests**: RTL: MorningBriefCard h2 has correct classes; PortfolioSummary no text-2xl; RecentAlerts compact rows.
**AC**: All dashboard widgets use compact patterns; MorningBriefCard h2 headers are 10px uppercase.

**Validation Gate (Wave D)**:
- [ ] No workspace panels show "coming soon" text
- [ ] Empty workspace ≤64px
- [ ] All dashboard widgets use compact patterns
- [ ] All workspace tests pass

---

### Wave E — QA, Screenshots, Responsive Polish, Gaps

**Goal**: Final visual QA, accessibility checks, responsive verification, audit uninspected components.

**Depends on**: Waves A–D complete

**Tasks**:

#### T-E-5-01: Inspect and fix uninspected components
**Type**: impl
**Target files**: `app/(app)/chat/page.tsx`, `app/(app)/settings/page.tsx`, `components/instrument/IntelligenceTab.tsx`, `components/instrument/EntityGraphPanel.tsx`, `components/shell/TopBar.tsx`, `components/shell/Sidebar.tsx`
**What to build**: Read each file; apply Wave A principles (radius, padding, empty states); fix any p-6, rounded-lg, max-w constraints found.

#### T-E-5-02: Screenshot validation
**Type**: test
**What to build**: Playwright screenshot tests for all major routes with seeded data:
- `/dashboard` — verify ≥3 data regions above fold
- `/workspace` — verify all panels show data
- `/instruments/[seeded-id]` — verify chart height, header compactness
- `/instruments/[seeded-id]/fundamentals` — verify no gaps between columns
- `/portfolio` — verify sector allocation visible
- `/screener` — verify table has ≥8 columns
- `/alerts` — verify full-width, compact rows

#### T-E-5-03: Accessibility check
**Type**: test
**What to build**: Run axe-core on portfolio (holdings table), screener (results table), alerts list. Fix any violations.

#### T-E-5-04: No console errors validation
**Type**: test
**What to build**: Playwright script opens each route with seeded data; asserts zero console errors. Focus on: workspace (demoEntityId hardcoded), screener (removed columns), portfolio (new table).

#### T-E-5-05: Responsive checks
**Type**: test
**What to build**: Playwright screenshot at 1920px, 1440px, 1280px, 768px for each major route. Confirm:
- No horizontal overflow
- Tables scroll horizontally correctly
- Screener filter bar usable at 1280px
- Portfolio table readable at 1280px

**Validation Gate (Wave E)**:
- [ ] Zero console errors on all seeded routes
- [ ] Portfolio holdings table passes axe accessibility
- [ ] All screener columns visible at 1440px
- [ ] Screenshots captured and committed to `docs/screenshots/redesign/`
- [ ] No py-12/py-24/p-8/rounded-lg in any component file

---

## 9. Detailed Implementation Backlog

| ID | Priority | Page/Component | Issue | Required Change | Files | Data Dep | Complexity | Risk | AC |
|---|---|---|---|---|---|---|---|---|---|
| B-001 | P0 | ArticleCard | rounded-lg violates 2px rule | Replace with rounded-[2px] | ArticleCard.tsx | None | Low | Low | No rounded-lg class |
| B-002 | P0 | AlertRow | rounded-lg + card-style | Replace with compact divide-y row | AlertsList.tsx | None | Low | Low | Compact rows |
| B-003 | P0 | Alerts page | max-w-4xl constraint | Remove; full-width | alerts/page.tsx | None | Low | Low | Full-width |
| B-004 | P0 | Screener | Price column always "—" | Remove Price column | screener/page.tsx | None | Low | Low | No all-"—" column |
| B-005 | P0 | OHLCVChart | height: 280 hardcoded JS | height: 360 in createChart() | OHLCVChart.tsx | None | Low | Low | 360px chart |
| B-006 | P0 | News tab | px-4 py-3 article wrappers | Remove outer div wrapper | instruments/page.tsx | None | Low | Low | No outer wrapper |
| B-007 | P0 | Workspace | "coming soon" placeholder panels | Implement screener+chat widgets | workspace/page.tsx | Screener API | Medium | Medium | No "coming soon" text |
| B-008 | P0 | Alerts empty state | p-8 large empty state | InlineEmptyState | AlertsList.tsx | None | Low | Low | ≤32px |
| B-009 | P1 | Portfolio | p-6 outer padding | p-3 | portfolio/page.tsx | None | Low | Low | ≤12px outer |
| B-010 | P1 | Portfolio | Disabled "Add Position" stub | Remove button | portfolio/page.tsx | None | Low | Low | Button absent |
| B-011 | P1 | Portfolio | Non-interactive KPI hover | Remove hover state | portfolio/page.tsx | None | Low | Low | No hover on KPI tiles |
| B-012 | P1 | Portfolio | CSS grid holdings (not table) | Semantic <table> | portfolio/page.tsx | None | Medium | Low | <table> in DOM |
| B-013 | P1 | Portfolio | Missing sector exposure | SectorAllocationPanel | portfolio/page.tsx | Fundamentals per holding | High | Medium | Panel visible |
| B-014 | P1 | Portfolio | Missing realized P&L | Compute from transactions | portfolio/page.tsx | Existing transactions query | Medium | Low | Realized P&L KPI |
| B-015 | P1 | FundamentalsTab | gap-6 column gap | gap-2 | FundamentalsTab.tsx | None | Low | Low | gap-2 |
| B-016 | P1 | FundamentalsTab | p-4 outer padding | p-3 | FundamentalsTab.tsx | None | Low | Low | p-3 |
| B-017 | P1 | Screener | No filter collapse | Top bar toggle | screener/page.tsx | None | Medium | Low | Filter toggle |
| B-018 | P1 | Screener | 6 columns (1 useless) | Add P/E, Revenue, Beta | screener/page.tsx | ScreenerResult fields | Medium | Medium | ≥8 columns |
| B-019 | P1 | Instrument header | py-4 too tall | py-2 | instruments/page.tsx | None | Low | Low | Header ≤56px |
| B-020 | P1 | Instrument header | Hardcoded back nav | router.back() | instruments/page.tsx | None | Low | Low | Uses router.back() |
| B-021 | P1 | Instrument header | 4 metrics only | Add volume/open/Hi/Lo | instruments/page.tsx | quote fields | Medium | Medium | ≥6 metrics |
| B-022 | P1 | Instrument overview | Chart container p-4 | p-0 | instruments/page.tsx | None | Low | Low | Edge-to-edge chart |
| B-023 | P1 | News "Load more" | Plain button not visible | Button variant="outline" | instruments/page.tsx | None | Low | Low | Styled button |
| B-024 | P2 | GlobalSearch | No recent instruments | localStorage history | GlobalSearch.tsx | None | Medium | Low | Recent list shows |
| B-025 | P2 | GlobalSearch | No keyboard hint | Add hint strip | GlobalSearch.tsx | None | Low | Low | Hint visible |
| B-026 | P2 | MorningBriefCard | Article-scale markdown | text-xs typography override | MorningBriefCard.tsx | None | Low | Low | h2 at 10px |
| B-027 | P2 | Dashboard widgets | Various card padding issues | Audit + fix per widget | dashboard/components | None | Medium | Low | Compact patterns |
| B-028 | P2 | Workspace EmptyWorkspace | py-24 giant empty state | py-8 | workspace/page.tsx | None | Low | Low | ≤64px |
| B-029 | P2 | Intelligence tab | No severity count strip | Add count bar | IntelligenceTab.tsx | None | Low | Low | Count strip visible |
| B-030 | P2 | SessionStatsStrip | Missing component | Create new component | SessionStatsStrip.tsx | quote fields | Medium | Low | Renders strip |
| B-031 | P3 | Portfolio h-24 empty states | h-24 oversized | InlineEmptyState | portfolio/page.tsx | None | Low | Low | ≤32px |
| B-032 | P3 | News compact mode | No list mode toggle | compact prop + toggle | ArticleCard.tsx, page.tsx | None | Medium | Low | Toggle works |
| B-033 | P3 | Instrument tabs | No keyboard shortcuts | useHotkeys 1/2/3/4 | instruments/page.tsx | None | Low | Low | Shortcuts work |
| B-034 | P3 | IndexTicker | Suspected gap-4 | gap-2 (after inspect) | IndexTicker.tsx | None | Low | Low | gap-2 |
| B-035 | P3 | Chat page | Unknown state | Inspect + fix per A rules | chat/page.tsx | None | Unknown | Low | Terminal patterns |
| B-036 | P3 | Settings page | Unknown state | Inspect + fix per A rules | settings/page.tsx | None | Unknown | Low | Terminal patterns |

---

## 10. QA and Acceptance Plan

### Measurable Acceptance Criteria

| Metric | Target | How to Verify |
|---|---|---|
| TopBar height | ≤44px | Screenshot + `getBoundingClientRect()` |
| Instrument header height | ≤56px | Same |
| Panel header height | 28–32px | CSS class check |
| Financial table row height | h-8 = 32px | CSS class check |
| Outer panel padding | ≤12px (p-3) | grep for `p-6`, `p-8`, `p-12` |
| Card border radius | 2px only | grep for `rounded-lg`, `rounded-md` in updated files |
| Empty state max height | ≤32px for inline; ≤64px for page-level | Component test |
| Min useful regions above fold | ≥3 on every top-level page | Screenshot review |
| Disabled placeholder buttons | 0 | grep for `disabled` on visible buttons |
| Screener column count | ≥8 (none all-"—") | RTL test |
| Alerts page width | No `max-w-*` constraint | grep |
| Chart height | ≥360px | Vitest snapshot |

### Screenshot Coverage Plan

Capture before/after screenshots for all modified pages. Use Playwright's `page.screenshot()`:

```
docs/screenshots/redesign/
├── before/
│   ├── dashboard.png
│   ├── workspace.png
│   ├── instrument-overview.png
│   ├── instrument-fundamentals.png
│   ├── instrument-news.png
│   ├── screener.png
│   ├── portfolio.png
│   └── alerts.png
└── after/
    └── [same files]
```

### Component Test Coverage

| Component | Tests Required |
|---|---|
| `ArticleCard` | compact mode renders h-9; card mode renders rounded-[2px]; LIGHT tier opacity-60 |
| `AlertsList` | rows use divide-y not space-y; empty state ≤32px; clicking row calls navigate |
| `FundamentalsTab` | all 20+ metrics render; no gap-6 class; p-3 not p-4 |
| `OHLCVChart` | height 360 in skeleton and error; no height 280 |
| `SessionStatsStrip` | renders all OHLCV fields; "—" when null |
| `InlineEmptyState` | renders text in p-3 container; no border |
| `GlobalSearch` | recent instruments shown when empty; hint bar rendered |
| Portfolio holdings `<table>` | semantic table element in DOM; h-8 rows; accessible |
| `SectorAllocationPanel` | renders bars for ≥1 sector; inline empty when no data |
| `WorkspaceScreenerWidget` | renders table not placeholder text |

### Accessibility Checks

| Surface | Check |
|---|---|
| Portfolio holdings | `<table>` with proper `thead/tbody/th scope` |
| Screener results | `<table>` with `aria-sort`, `aria-label` |
| Alerts list | Rows have `aria-label` for screen readers |
| Empty states | Use `role="status"` and `aria-live="polite"` |
| Buttons | All buttons have accessible labels (no icon-only without aria-label) |
| Focus rings | Visible on all interactive elements (`ring-2 ring-ring`) |

### No Console Error Validation

Run Playwright script against all seeded routes:
```ts
page.on('console', msg => {
  if (msg.type() === 'error') errors.push(msg.text())
})
```
Assert `errors.length === 0` for each route.

---

## 11. Backend/API Dependency List

| Needed Data | Page | Current Availability | Required Change | Priority | Blocker |
|---|---|---|---|---|---|
| `quote.volume` | Instrument header | Unknown — verify S9 response schema | None if present; add to CompanyOverview if missing | P1 | Maybe |
| `quote.open` | Instrument header | Unknown — verify S9 response | Same as above | P1 | Maybe |
| `quote.high` | Instrument header | Unknown — verify S9 response | Same as above | P1 | Maybe |
| `quote.low` | Instrument header | Unknown — verify S9 response | Same as above | P1 | Maybe |
| `pe_ratio` in ScreenerResult | Screener | Unknown — check ScreenerResult type | Add field to S9 screener response if missing | P1 | Maybe |
| `beta` in ScreenerResult | Screener | Unknown | Add from fundamentals pipeline to S9 screener response | P2 | No |
| `revenue_ttm` in ScreenerResult | Screener | Unknown | Add from fundamentals to S9 screener response | P2 | No |
| `gics_sector` per holding | Portfolio sector allocation | Available via fundamentals endpoint per instrument | Fan-out from existing `getFundamentals()` per holding — no new endpoint needed | P1 | No |
| Realized P&L | Portfolio | Computable from existing `getTransactions()` | Client-side computation only — no backend needed | P1 | No |

**Note on quote fields**: The S9 `CompanyOverview` response is the key risk. If `quote.volume`, `quote.open`, `quote.high`, `quote.low` are not in the response schema, they need to be added to the S9 `GET /v1/companies/{id}/overview` composition. Check `apps/worldview-web/lib/gateway.ts` and `types/api.ts` immediately at Wave B start.

---

## 12. Final Recommendation

**`READY_FOR_IMPLEMENTATION`**

### First Wave to Implement
**Wave A** — all tasks are pure frontend-only changes. No backend API calls required. Maximum visible impact in a single session:
- `rounded-lg` → `rounded-[2px]` across ArticleCard and AlertRow
- Alerts page: full-width, compact rows
- Portfolio: remove p-6, remove disabled stub button
- Instrument news: remove outer padding wrapper
- Chart: 360px height
- FundamentalsTab: gap-2, p-3

### Highest-Risk Areas
1. **Screener column additions** (Wave B): `pe_ratio`, `beta`, `revenue_ttm` may not exist in `ScreenerResult`. If absent from API, backend S9 work required before Wave B can complete.
2. **Workspace screener widget** (Wave D): implementing a compact screener widget requires sufficient S9 response data without the full filter panel.
3. **Quote fields for instrument header** (Wave B): `overview.quote.volume/open/high/low` — verify before building SessionStatsStrip.
4. **Sector allocation** (Wave C): fan-out to fundamentals per holding may be slow for portfolios with >20 holdings.

### Minimum Scope to Stop UI Looking Toy-Like (Wave A Only)

Execute Wave A tasks T-A-1-01 through T-A-1-09. These 9 targeted changes collectively produce:
- `rounded-[2px]` terminal cards instead of `rounded-lg` friendly cards
- Full-width alerts page instead of centered column
- 360px chart
- Compact news list instead of padded card stack
- No disabled stub buttons
- Compact empty states
- Professional instrument header

**Wave A alone shifts the perception from "dark-themed consumer app" to "Bloomberg-grade terminal".**

### What Must Not Be Deferred
1. `rounded-lg` fix — every card-based component screams "consumer app" at this radius
2. `max-w-4xl` removal from alerts page — width constraint is architecturally wrong for a terminal
3. Screener Price column removal — a column that always shows "—" destroys credibility
4. Workspace "coming soon" placeholder text — explicit acknowledgment of incompleteness is unacceptable in a demo
5. Chart 280px → 360px — professional charting tools do not use sub-300px charts as their primary view

---

*Plan generated 2026-04-24 by direct source inspection of 15+ frontend files.*
*Agent: perform fresh reads of all uninspected components (chat, settings, TopBar, Sidebar, IntelligenceTab, EntityGraphPanel, MorningBriefCard, PortfolioSummary dashboard widget) at Wave A start before writing any code.*
