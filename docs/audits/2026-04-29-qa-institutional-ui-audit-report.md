# Institutional UI Audit — Worldview Frontend

**Date:** 2026-04-29 18:44 UTC
**Skill:** `/qa` (UI/UX redesign scope)
**Audit benchmark:** Bloomberg Terminal · BlackRock Aladdin · Refinitiv Eikon
**Stakeholder:** BlackRock presentation
**Scope:** `apps/worldview-web/` — full frontend + design system + data visualization
**Branch:** `feat/content-ingestion-wave-a1`
**Auditors (parallel agents):** Layout/IA · Visual Design · Components · Data Viz · Codebase Architecture
**Verdict:** **PASS_WITH_WARNINGS** — production-credible visual chrome; falls short of institutional bar in five well-defined areas (real-time, keyboard workflow, table interactions, contract types, god-files). Closing the **Top 12 priorities** below moves the product to BlackRock-credible.

---

## Executive Summary

Worldview ships a frontend that is unusually well-considered for a thesis project. The **chrome economy is competitive with Bloomberg/Aladdin** (60px chrome on 1080p, IBM Plex Mono numerics, 22px row rhythm, 2px corner radius, dark-only tokens, `tabular-nums` discipline, drag-resizable workspace with persistence). Foundational decisions are correct: auth token in React state only, OIDC PKCE, gateway abstraction, virtualized screener, structured CSP/HSTS/X-Frame-Options. The team understands the *vocabulary* of an institutional terminal.

The platform falls short of institutional bar in five systemic ways:

1. **Workflow grammar is missing.** StatusBar advertises six keyboard shortcuts that are not actually wired. There is no command palette beyond symbol search, no Bloomberg-style mnemonic chords, no global symbol input. A terminal that *promises* shortcuts and ignores them is worse than one that has none.
2. **Real-time is fake.** The entire app is 15s polling. There is no WebSocket quote stream, no tick-flash animation, no per-cell freshness indicator. Bloomberg/Aladdin price cells flash green/red on every tick — the single most recognizable trader-UI primitive is absent.
3. **Tables are pre-MVP.** No right-click context menu anywhere. No multi-sort. No column resize/reorder/freeze on the flagship holdings table (ScreenerTable has reorder but no resize). No multi-select / bulk actions. No inline editing.
4. **Defaults betray the density story.** `components/ui/{button,input,select,tabs,dialog}.tsx` ship at consumer SaaS sizes (h-9 = 36px, text-sm = 14px, p-6 = 24px). Feature components heroically work around these with bespoke `h-6 px-2 text-[11px]` overrides — two parallel design systems collide on every screen.
5. **Architecture is prototype-grade scaffolding scaled past its limit.** `lib/gateway.ts` is 2,415 LOC. `types/api.ts` is 1,214 LOC of hand-written shapes that drift from S9. `app/(app)/portfolio/page.tsx` is 1,704 LOC. Three chart libraries coexist. Three dead npm dependencies ship to lockfile. No URL state for filters/tabs (Bloomberg parity broken). Zero `React.memo`.

The **good news**: none of this is architectural — it is bounded surface-level work. A focused 3-week wave closes the gap.

---

## Maturity Scorecard

| Dimension | Score (0–10) | Bloomberg = 10 | Notes |
|-----------|:------------:|----------------|-------|
| Layout & Information Architecture | **6.5** | Strong chrome, weak workflow grammar. No multi-monitor, no symbol-first input, IA fragmentation (4 watchlist surfaces). |
| Visual Design System | **7.2** | Best-in-class category. Wrong positive green (TradingView teal vs phosphor green), Material Red 400 too pink, heat scale references retired palette. |
| Components & Interactions | **6.4** | Good detail work; system-level drift. UI primitives at consumer defaults, no context menus, no multi-sort, no tick flash. |
| Data Visualization | **6.2** | OHLCVChart competent first draft. No HUD legend, no log scale, no compare overlay, no annotations, three chart libs, sparklines limited to screener. |
| Codebase Architecture | **4.5** | God-files, no URL state, hand-typed APIs, scattered query keys, dead deps. Foundations sound but shape doesn't scale. |
| Navigation & Workflow Speed | **5.0** | StatusBar shortcuts are dead. No command palette superset. No mnemonic functions. 5+ clicks for "load symbol → 4 views" vs 2 keystrokes on Bloomberg. |
| **Composite** | **6.0 / 10** | "Polished consumer fintech" — ahead of Robinhood/Public. Below Bloomberg/Aladdin/Refinitiv. |

---

## Cross-Agent HIGH-Confidence Signals

Issues flagged independently by 2+ specialist agents are automatically promoted to HIGH confidence. These are the highest-trust findings in the audit.

| Signal | Severity | Flagged by | Evidence |
|--------|----------|------------|----------|
| **No tick-flash on price changes (real-time UX)** | CRITICAL | Components, Data Viz | `LiveQuoteBadge.tsx:57`, `IndexTicker.tsx:14`, `SemanticHoldingsTable.tsx:374-415`, `ScreenerTable.tsx:137-166` |
| **StatusBar advertises 6 keyboard shortcuts that are not wired** | CRITICAL | Layout, Components | `StatusBar.tsx:28-35`, `Sidebar.tsx:207-237`. No `useHotkeys` listener exists outside `⌘K`. |
| **UI primitives default to consumer SaaS sizes (h-9, p-6)** | MAJOR | Visual, Components | `components/ui/button.tsx:54-58`, `input.tsx:23`, `dialog.tsx:46-47`, `tabs.tsx:29` |
| **Hand-written `types/api.ts` drift risk** | CRITICAL | Codebase, (echoed by Components on Insider codes) | `types/api.ts` 1,214 LOC; gateway has runtime transforms hiding shape mismatches |
| **No URL state for filters/tabs/periods** | CRITICAL | Codebase, (implicit in Layout F-001) | `portfolio/page.tsx`, `screener/page.tsx`, `workspace/page.tsx` |
| **`#26A69A` is TradingView teal, not Bloomberg green** | CRITICAL | Visual, Data Viz | `globals.css:81`, `lib/utils.ts:259-265`, used everywhere |
| **Heat scale uses retired Bloomberg Dark palette colors** | CRITICAL | Visual, Data Viz | `lib/utils.ts:248-265` returns `#1A2030` etc., explicitly forbidden by `globals.css:11` |
| **Two heatmap implementations drift** | MAJOR | Data Viz, Visual | `MarketHeatmap.tsx` (7-step) vs `SectorHeatmapWidget.tsx` (4-step opacity) |
| **No right-click context menu (table interactions)** | CRITICAL | Components | All tables — single-flag but broad reach |
| **God-page `portfolio/page.tsx` (1,704 LOC) with re-render storms** | CRITICAL | Codebase, (echoed by Layout F-010) | One file, 12 useQuery hooks, 17 useState, all 4 tabs |
| **Decimal/compaction inconsistency (3 implementations of B/M/T)** | MAJOR | Data Viz, Codebase | `lib/utils.ts:55,127,138`, `screener/ScreenerTable.tsx:69`, `FundamentalSparkline.tsx:101-115` |

These 11 HIGH-confidence signals are the spine of the BlackRock-readiness roadmap.

---

# Section 1 — Layout & Information Architecture

**Maturity:** 6.5/10 · **Findings:** 35 · **CRITICAL:** 5 · **MAJOR:** 13 · **MINOR:** 13 · **NIT:** 4

### Strengths
- Chrome economy ~5.5% of viewport (beats Aladdin's 8% target).
- IBM Plex Mono + tabular-nums + min-w pre-allocated slots prevent jitter on refetch.
- Drag-resizable sidebar with localStorage persistence (`CollapsibleSidebar.tsx:136-157`).
- Workspace tabs with double-click inline rename (`WorkspaceTabs.tsx:107`).
- Symbol-linking architecture exists (`SymbolLinkingContext.tsx`) — 5 colors mirror Bloomberg group-link colors.

### CRITICAL Findings

**F-LAYOUT-001 — Dead keyboard shortcuts (StatusBar lies)**
`StatusBar.tsx:28-35` renders chord hints `G+D, G+S, G+W, G+P, G+A, ⌘K`. Grep shows zero `useHotkeys` implementation outside `⌘K`. Sidebar even shows a separate, conflicting `g+c` hint. **Fix:** Implement global `useChordHotkeys` hook with 1.2s reset window; wire all six chords + `?` cheat-sheet + `⌘B` toggle sidebar + `⌘.` toggle StatusBar.

**F-LAYOUT-002 — Dual sidebar implementations**
`Sidebar.tsx` (legacy 56px) and `CollapsibleSidebar.tsx` (current) coexist with diverging nav labels (`"Alerts & News"` vs `"Alerts"`). **Fix:** Delete legacy. Add CI grep guard.

**F-LAYOUT-003 — Watchlist exists in 4 surfaces, no canonical home**
Sidebar rail · Dashboard `WatchlistMoversWidget` · Workspace `WorkspaceWatchlistWidget` · Portfolio "Watchlists" tab · `/watchlists` 307-redirects to `/workspace`. **Fix:** Promote `/watchlists` to a real 2-column hub (lists left, symbol grid + bulk ops right). Remove tab from `/portfolio`.

**F-LAYOUT-004 — No 4-panel quad-symbol pattern (the Bloomberg signature)**
WorkspaceGrid has no template where 4 panels share a top symbol input. "Add Panel" requires modal click → cell pick (3-step). **Fix:** Add quad-symbol template; replace modal with right-edge drag-tray + chord splits (`Cmd+\`, `Cmd+-`); add top-of-grid linked symbol input.

**F-LAYOUT-026 — No global command palette superset**
`⌘K` opens symbol search only. No actions, settings, recent items, or saved screens. **Fix:** Layer command-mode in GlobalSearch (typing `>` switches to action mode), or `⇧⌘P` dedicated palette indexing ~30 commands.

### MAJOR Highlights
- **F-LAYOUT-007** Dashboard fixed `gridTemplateRows: "auto 130px ..."` wastes vertical space on 4K. Use `minmax(120px, 14vh)`.
- **F-LAYOUT-008** TopBar right cluster eats ~470px. Drop "Day P&L"/"Total P&L" labels, compress UtcClock to `HH:MM`, move AskAi/RefreshAll to StatusBar.
- **F-LAYOUT-013** Maximize button is `onClick={() => {}}` — **no multi-monitor pop-out** (disqualifying for institutional). Wire to viewport-fill toggle + `window.open` detached panel route.
- **F-LAYOUT-014** Screener filter bar collapses behind a button. Convert to always-visible chips (Aladdin pattern).
- **F-LAYOUT-022** MorningBrief col-span-12 above-fold steals 12% of vertical. Move to col-span-6 + P&L attribution panel.
- **F-LAYOUT-028** `/news` and `/watchlists` are 307 stub redirects — broken IA.
- **F-LAYOUT-033** No global symbol input — function-first then symbol is opposite Bloomberg muscle memory.

### Top 5 Layout Redesigns
1. Wire real keyboard shortcuts + global symbol input + command palette superset (F-001 / F-026 / F-033).
2. Promote `/watchlists` to real hub; remove `/portfolio` watchlists tab (F-003 / F-028).
3. Implement panel pop-out / multi-monitor (F-013).
4. Reclaim TopBar density (F-008 / F-017 / F-019); user-customizable IndexTicker (F-006).
5. Replace Workspace "Add Panel" modal with drag-tray + chord splits + quad template (F-004 / F-009 / F-023).

### Benchmark Gap Matrix
| Capability | Worldview | Bloomberg | Aladdin |
|---|---|---|---|
| Density (data points / 1080p) | ~120 | ~220 | ~180 |
| Workflow speed (clicks: load symbol → 4 views) | 5+ | 2 keystrokes | 3 + drag |
| Panel system (split/pop-out) | resize ✓ / no pop-out / no split | full multi-monitor | full + tear-off |
| Hotkeys (working) | **0** | F1-F12 + chords | full chord set |
| Search (symbol+commands+actions) | symbol only | unified | unified |
| Chrome footprint | **5.5% (wins)** | 7% | 8% |

---

# Section 2 — Visual Design System

**Maturity:** 7.2/10 · **Findings:** 43 · **CRITICAL:** 3 · **MAJOR:** 11 · **MINOR:** 19 · **NIT:** 10

### Strengths
- 4-step background hierarchy is mathematically sound (4% / 7% / 11% / 16% lightness).
- `tabular-nums` applied globally on `<body>` (`globals.css:148`).
- `2px` radius consistently applied via `rounded-[2px]` overrides.
- Trading yellow `#FFD60A` at 100% saturation — correct Bloomberg signature.
- Pure-black foreground on yellow CTAs — correct contrast inversion.
- Shadow reset on dark theme.
- WCAG AAA on primary CTA (14.21:1) and body text (15.94:1).

### CRITICAL Findings

**F-VISUAL-001 — Positive color is TradingView teal, not institutional green**
`--positive: 174 42% 40%` resolves to `#26A69A`. On near-black, reads as data-viz accent, not "price up". Bloomberg uses `#80FF80` phosphor green; Refinitiv `#00C853`; Aladdin `#00B050`. Contrast ratio: current 4.51:1 (FAILS AA at body sizes for 11-14px text).
**Fix:**
```css
--positive: 150 100% 41%;  /* #00D26A — institutional green, AAA contrast */
```

**F-VISUAL-002 — Negative red is Material Red 400 (too pink, consumer-app)**
`#EF5350` reused as both `--negative` and `--destructive` — should be split. Bloomberg `#FF6464`/`#FF3366`; Refinitiv `#FF1744`.
**Fix:**
```css
--negative: 350 100% 62%;     /* #FF3B5C — urgent institutional red */
--destructive: 0 84% 60%;     /* #EF4444 — keep delete-red distinct */
```

**F-VISUAL-003 — Heat-cell colors reference retired Bloomberg Dark palette**
`heatCellColor()` returns hardcoded blue-tinted hexes (`#1A2030`, `#0A2E28`, `#0A2420`, `#251218`, `#300E12`, `#3D0A0E`) — explicitly forbidden by `app/globals.css:11`. Sector heatmap reads as "stickers from a different app".
**Fix:** Rewrite using zero-hue base shifted toward 134°(green)/350°(red) — see proposal table in §6 below.

### MAJOR Findings (selected)

- **F-VISUAL-004** Button `default: h-9` (36px). Documented density target is 22-26px. **Fix:** `default: h-7 px-3 text-xs` (28px).
- **F-VISUAL-005** Input `h-9 px-3 text-sm` — `TransactionsTable` already shadows with bespoke `h-6 px-2 text-[11px]` constants because the canonical version is unusable. **Fix:** Add `density: compact|default|comfortable` cva variant.
- **F-VISUAL-006** `TabsList h-9 rounded-[2px] bg-muted p-1` — pill-on-muted is consumer SaaS. **Fix:** Bare flex with 2px primary-color underline on active.
- **F-VISUAL-008** Color blindness: deuteranope luminance for `#26A69A` (140) ≈ `#EF5350` (140). Positive vs negative collapses to two near-identical greys. Already partially mitigated by ▲▼ glyphs in `PriceChange` — **enforce globally**.
- **F-VISUAL-011** 10 type sizes in active use (`text-[9px]` through `text-4xl`). Bloomberg uses 4. **Fix:** Lock to 6: 10/11/12/14/18/24px. Ban `text-base`, `text-2xl`, `text-4xl`.
- **F-VISUAL-013** Icon stroke-widths `0.75 / 1 / 1.5 / 2 / 2.5` mixed. **Fix:** Wrap lucide in `lib/icons.tsx` shim enforcing `strokeWidth={1.5}`.
- **F-VISUAL-022** AskAI panel uses Tailwind defaults (`bg-amber-500/20`) — bypasses tokens. **Fix:** Add `--accent-ai: 280 60% 60%` (violet — universal AI color).
- **F-VISUAL-027** `disabled:opacity-50` on all components renders disabled UI ~2:1 contrast (FAILS AA). **Fix:** Explicit disabled tokens (desaturate, don't vanish).
- **F-VISUAL-037** Hero price `text-4xl` (36px) is Robinhood-grade. **Fix:** 22-24px max with bold weight.
- **F-VISUAL-039** GlobalSearch input `h-12` inside cmdk wrapper — 2× the rest of the system.

### Color Palette Redesign (definitive)

| Token | Current | Proposed | Rationale |
|-------|---------|----------|-----------|
| `--background` | `#09090B` | unchanged | Perfect — keep |
| `--card` | `#111113` | `#0F0F11` | Slight darken → bigger gap to surface-2 |
| `--surface-2` | `#18181B` | `#15151A` | True intermediate (currently aliased to muted) |
| `--muted` | `#18181B` | `#1D1D23` | Hover/selected rows |
| `--surface-3` | `#27272A` | `#2D2D32` | Inputs, divider strong |
| `--border` | `#27272A` | `#222226` | Subtle row dividers |
| `--divider-strong` | (new) | `#34343A` | Panel boundaries |
| `--muted-foreground` | `#71717A` | `#8B8B95` | Bump to 5.6:1 (was 4.65:1) |
| `--positive` | `#26A69A` | **`#00D26A`** | **Institutional green** |
| `--negative` | `#EF5350` | **`#FF3B5C`** | **Urgent institutional red** |
| `--destructive` | `#EF5350` | `#EF4444` | Split from negative |
| `--warning` | `#F59E0B` | `#FFB000` | Bloomberg amber |
| `--accent-ai` | (new) | `#A855F7` | AI-assistant elements |
| `--primary` | `#FFD60A` | unchanged | Bloomberg yellow — keep |

### Typography Lock-in

| Token | Size | Weight | Use |
|-------|------|--------|-----|
| `text-key` | 10px | 500 | Column headers, axis labels, key hints (uppercase, tracking 0.08em) |
| `text-data` | 11px | 400 | Data values, KPI rail values, ticker text (font-mono tabular-nums) |
| `text-base` | 12px | 400 | Body text, card descriptions |
| `text-title` | 14px | 500 | Card titles, section headings, primary buttons |
| `text-h2` | 18px | 600 | Page section headings (max 1-2 per page) |
| `text-hero` | 24px | 700 | Hero KPIs, instrument hero price |

**Ban:** `text-[9px]` (illegible), `text-base` (consumer 16px), `text-2xl`, `text-xl`, `text-4xl`.

### Iconography Lock-in
- **lucide-react** wrapped with `strokeWidth={1.5}` enforcement.
- **Three sizes only:** 12px (data rows) · 16px (toolbars/nav default) · 20px (dialog/empty-states).
- Color: `currentColor` always; never `text-amber-*`/`text-blue-*` Tailwind defaults.

---

# Section 3 — Components & Interactions

**Maturity:** 6.4/10 · **Findings:** 50 · **CRITICAL:** 6 · **MAJOR:** 17 · **MINOR:** 20 · **NIT:** 7

### Strengths
- Row density correct (22px) in nearly all data tables.
- `OHLCVChart` is genuinely strong: 7 indicators, volume profile, drawing palette, fullscreen, dynamic-import fallback.
- `TransactionsTable` filter bar is comprehensive (date range, ticker autocomplete, currency, debounced search, CSV export, virtualization at >200 rows).
- `ScreenerFilterBar` uses approved §0.5 grid-rows animation pattern.
- Sticky header `bg-card` on `<tr>` (workaround for Chromium/Safari border-collapse paint quirk) — a real institutional bug fixed.

### CRITICAL Findings

**F-COMP-001 — No tick-up/tick-down cell-flash anywhere**
Quote prices update silently. Most recognizable trader-UI primitive (Bloomberg/Aladdin/IBKR/TradingView all flash cells on tick) is absent. **Fix:** `useTickFlash(value)` hook + `bg-positive/30` / `bg-negative/30` 450ms transition on every live price/change cell. Pair with WS stream from F-DATAVIZ-001.

**F-COMP-002 — No right-click context menu anywhere in the app**
Right-clicking a row in any table does nothing. `ContextMenu` primitive does not exist. **Fix:** Install `@radix-ui/react-context-menu`, add `components/ui/context-menu.tsx`, wrap every row with: Open Instrument · Add to Watchlist · Open in Workspace · Create Alert · Copy Ticker · Export Row.

**F-COMP-003 — `SemanticHoldingsTable` has no column visibility/order/resize**
12 hard-coded columns. `ScreenerTable` already has `ColumnSettingsPopover`. **Fix:** Lift to shared `components/data/ColumnSettings.tsx`, define `PortfolioColumn` registry, persist to localStorage `worldview-portfolio-columns`. Add column resize via `useResizableColumns` hook.

**F-COMP-004 — No multi-sort on any table**
Single-column only. **Fix:** `sortStack: SortKey[]`; shift-click appends; render small superscript order on column headers (`P&L¹ DAY%²`).

**F-COMP-005 — GlobalSearch has no symbol disambiguation**
AAPL on NASDAQ/MEXI/BVMF returns flat list, no exchange grouping, no ISIN/CUSIP search. **Fix:** Group by exchange in CommandGroup (Primary/Secondary/Other); add ISIN/CUSIP search; country flag glyph.

**F-COMP-006 — GlobalSearch limited to instruments — no actions/articles/settings**
`cmdk` strength wasted. **Fix:** Three CommandGroups: Symbols / Actions / Recent. Actions registry in `lib/command-actions.ts` (~30 entries: refresh, create-alert, open-screen, settings, sign-out).

### MAJOR Findings (selected)

- **F-COMP-007** Default Input `h-9` — 50% too tall. Add `density` cva variant.
- **F-COMP-008** Default Button `h-9` / `sm: h-8`; no `xs` variant. Add `xs: h-6 px-2 text-[10px]`.
- **F-COMP-009** Tabs are pill-on-muted. Use flat with primary underline.
- **F-COMP-010** Dialog `max-w-lg p-6 gap-4` is consumer-app generous. Standardize on `p-4 gap-2`, three size variants.
- **F-COMP-013** TransactionsTable virtualization uses per-row mini-tables — fragile. Migrate to `@tanstack/react-virtual` (already a dep) over CSS Grid (matches ScreenerTable pattern).
- **F-COMP-015** No inline editing on portfolio holdings (cost basis, qty, sector). Aladdin double-click pattern.
- **F-COMP-016** No keyboard hotkey scheme beyond `⌘K`. (Cross-ref Layout F-001.)
- **F-COMP-017** Period selector vs candle-frequency selector are conflated. Bloomberg/TradingView separate them (1m/5m/15m/1h/1d vs 1D/5D/1M/3M/6M/YTD/1Y/5Y/MAX).
- **F-COMP-018** OHLCVChart has no compare overlay — cannot index AAPL vs SPY.
- **F-COMP-019** Chart state not saved per symbol (indicator selection, timeframe, range, compare).
- **F-COMP-020** Focus rings 2px+offset 2px = 4px halo. Use 1px outline.
- **F-COMP-021** No freeze panes / sticky-left column for wide tables (Aladdin signature).
- **F-COMP-022** ScreenerTable row click navigates instead of selects — no multi-select / bulk actions.
- **F-COMP-026** AlertRuleBuilder freeform `<input>` for "price > 150" — typos = silent dead rules. **Fix:** Structured Field/Operator/Value builder.

### Proposed Bloomberg-Inspired Hotkey Scheme

Implement via `hooks/useGlobalHotkeys.ts` mounted in `app/(app)/layout.tsx`. Chord prefixes have a 1.2s reset window; `Esc` clears.

| Combo | Action | Combo | Action |
|---|---|---|---|
| `⌘K` / `Ctrl+K` | Command palette | `⌘E` | Export current table CSV |
| `/` | Focus GlobalSearch | `⌘⇧E` | Export current table PDF |
| `g` `d` | Go Dashboard | `⌘D` | Add to default watchlist |
| `g` `s` | Go Screener | `⌘⇧D` | Add to specific watchlist |
| `g` `w` | Go Workspace | `⌘\` | Toggle sidebar |
| `g` `p` | Go Portfolio | `⌘.` | Toggle full-width |
| `g` `a` | Go Alerts | `?` | Cheat-sheet overlay |
| `g` `c` | Go Chat | `Esc` | Close topmost overlay |
| `g` `i` | Go Instruments | `j` / `k` | Row down/up (in tables) |
| `g` `,` | Go Settings | `Space` | Toggle row selection |
| `⌘R` / `F5` | Refresh page data | `Shift+Space` | Range select |

**Bloomberg-style mnemonics** (when on `/instruments/[id]`, no input focused): `D`=DES · `G`=GP chart · `F`=FA fundamentals · `N`=CN news · `H`=HCP holdings · `R`=RV peer comp · `E`=EE earnings · `O`=OWN insider.

---

# Section 4 — Data Visualization

**Maturity:** 6.2/10 · **Findings:** 45 · **CRITICAL:** 8 · **MAJOR:** 17 · **MINOR:** 14 · **NIT:** 6

### Strengths
- Color tokens correct (after F-VISUAL-001/002 fix).
- HeatCell 7-step diverging scale algorithm is Bloomberg-canonical.
- WebGL knowledge graph (ForceAtlas2, 3-tier sizing, type-color encoding) is better than 80% of competitor terminals.
- 22px row density + 11px data text + 10px label uppercase coherent.
- `StaleBadge` + `LiveQuoteBadge` freshness dot pattern is correctly implemented (just under-used).
- `MiniChart` SVG sparkline (screener) — pure SVG, virtualized, first/last close color.
- Approximate-value `~` prefix in `PortfolioSummary` when any quote is stale (rare outside Bloomberg PORT).

### CRITICAL Findings

**F-DATAVIZ-001 — No real-time tick visualization (entire app is 15s polling)**
No WebSocket/SSE quote stream, no per-cell flash, no tick highlighting. Polling at 15s makes the screener look frozen during market open. **Single largest credibility leak.** Pair with F-COMP-001.

**Backend gap:** `S9 /v1/quotes/stream` WebSocket endpoint does not exist yet. **#1 backend ask** for BlackRock-readiness.

**F-DATAVIZ-002 — OHLCV chart has no crosshair HUD**
`crosshair: { mode: 0 }` enabled but no legend overlay. Bloomberg/TradingView's #1 most-used chart feature.
**Fix:** `chart.subscribeCrosshairMove(param => ...)` → render `O 192.41 · H 195.30 · L 191.20 · C 194.80 +1.24% · V 56.42M` overlay top-left, font-mono 11px.

**F-DATAVIZ-003 — No log scale toggle on price chart**
`rightPriceScale.mode` never set. Long-horizon (5Y, 10Y) charts on linear scale are misleading. **Fix:** Add `L`/`$` toggle in ChartToolbar; auto-default to log for timeframe ∈ {1Y, 5Y, ALL}.

**F-DATAVIZ-004 — Three different B/M/T compact-number implementations**
`formatVolume` (`1.23M`, no `$`), `formatMarketCap` (`$2.45T`), `formatCap` screener (`2.3T`, no `$`), `formatYAxisLabel` (toPrecision 3). User comparing screener `2.3T` against dashboard `$2.45T` thinks they are different numbers. **Fix:** Single canonical `formatCompactCurrency(v, opts?)` in new `lib/format.ts`. See §6 Number Formatting Standard below.

**F-DATAVIZ-005 — Sparklines limited to screener only**
Portfolio top holdings, top movers, pre-market movers, peer comparison, watchlist drawer, alerts — none have sparklines. Bloomberg `MOV<GO>` and PORT show one per row. Without it, +2.4% on a breakout looks identical to +2.4% on a parabolic top.
**Fix:** Add `<MiniChart>` (existing) as rightmost cell on PortfolioSummary, TopMovers, WatchlistPanel rows, PeerComparisonPanel rows. Reuse `getBatchOhlcvBars`.

**F-DATAVIZ-006 — No comparison overlay / relative-return mode**
Cannot overlay SPY vs AAPL. **Fix:** "vs" button in ChartToolbar opens ticker picker; rebase both series at index 0 to 100; right axis switches to "%" mode. Comparator = sky-500 dashed.

**F-DATAVIZ-007 — No annotations (earnings/news/alert markers) on chart**
Lightweight-charts `series.setMarkers()` is exactly for this. **Fix:** "Markers" submenu with toggles (earnings ⬇ "E" / dividends "D" / splits / news / my-alerts); sources already exist.

**F-DATAVIZ-008 — Knowledge graph has no filters or layout controls**
At depth=2 on AAPL, 80-120 nodes with no narrowing. **Fix:** Top-left toolbar h-6: filter pills (Companies/People/Events/Topics), edge-strength slider (0.3 default), search input, layout switcher (Force/Radial/Grid).

### MAJOR Findings (selected)

- **F-DATAVIZ-009** No drag-to-zoom range selector under time axis.
- **F-DATAVIZ-010** Multi-pane indicator layout missing — 5 oscillators stack on one canvas. Bloomberg/TradingView use separate vertical panes per oscillator.
- **F-DATAVIZ-011** Sector heatmap is flex-treemap not squarified. **Fix:** d3-treemap or rename honestly to `SectorBarStrip`.
- **F-DATAVIZ-012** Heatmap drill-down popover queries gainers always — clicking a red sector shows weak gainers, not actual losers dragging the sector down.
- **F-DATAVIZ-014** WorkspaceChartWidget falls back to candlesticks for 1Y+. At 1px wide, candles are illegible. **Fix:** Auto-switch to area when bars/width < 3.
- **F-DATAVIZ-015** ScreenerTable change pills `bg-positive/10` over alternating row stripes = muddy chord. **Fix:** Drop pill background; text-only color + ▲▼ glyph.
- **F-DATAVIZ-016** No data-quality icon on stale/estimated cells in tables. `StaleBadge` used in 5 files only. **Fix:** 4px right-edge color dot per row.
- **F-DATAVIZ-017** **Three chart engines:** lightweight-charts + recharts + raw SVG + sigma. ~280KB gz combined; visual style drift. **Fix:** Migrate `RevenueTrendSparklines`, `EarningsHistoryChart` to lightweight-charts. Drop recharts (~80KB gz).
- **F-DATAVIZ-018** Heatmap uses 4 opacity steps vs 7 in HeatCell — opacity-blended (browser color-management drift) instead of 7 explicit hexes. **Fix:** Replace `colorClassFor` with `heatCellColor()`.
- **F-DATAVIZ-020** Two heatmaps drift: `MarketHeatmap` (7-step) vs `SectorHeatmapWidget` (4-step). **Fix:** Delete legacy; one component using `heatCellColor()`.
- **F-DATAVIZ-021** Chart resize storms — ResizeObserver fires 60 Hz × 4 panels = 240 layout passes/s. **Fix:** rAF-batch.
- **F-DATAVIZ-024** No brush/zoom on EquityCurveChart. **Fix:** recharts `<Brush>` height 20.

### Number Formatting Standard (definitive)

Single canonical module `apps/worldview-web/lib/format.ts`. **Delete** the four other implementations.

```ts
formatCompactCurrency(v): "$1.23T" | "$450B" | "$87.4M" | "$45.6K" | "$234"
  v ≥ 1e12: 2dp; v ≥ 1e9: 0dp if int, 1dp; v ≥ 1e6: 1dp; v ≥ 1e3: 1dp; else 0dp

formatPrice(v):     "$1,234.56" (≥1000) | "$192.41" (≥1) | "$0.0234" (≥0.01) | "$0.000123" (<0.01)
formatPercent(v):   "+2.34%" signed default; absolute via opts; null → "—"
formatVolume(v):    "1.23M" / "456.7K" / "234"  (no $)
formatShares(v):    "100 sh" / "1.23K sh"  (always "sh")
formatRatio(v):     "24.57x" (2dp)
formatBeta(v):      "1.234" (3dp, no suffix)
formatBasisPoints:  "+23 bps"

formatDate(iso):     "Apr 17, 2026"        (UTC, en-US, hardcoded month names)
formatDateUTC:       "2026-04-17"          (sortable)
formatTime:          "14:32:18 UTC"        (no locale, no "just now")
```

**Hard rules:**
- Sign always before glyph: `+$100.00`, `-5.00%`. Never `$+100`.
- Right-align all numeric columns. `tabular-nums font-mono text-right` always.
- `en-US` locale only; never bare `toLocaleString()`.
- Negative convention: hyphen `-$1,234.50` (Bloomberg). Document at `docs/ui/DESIGN_SYSTEM.md §3.4`.
- Drop `×` suffix on share counts (it's for ratios) — use `100 sh` or `100`.

### Real-Time Architecture (recommended)

```
S2/S3 ─[Kafka]→ S9 ─[WebSocket /v1/quotes/stream]→ Frontend
                                  │
                                  ├─→ TanStack Query cache (queryClient.setQueryData)
                                  └─→ FlashBus event (per-cell direction)
```

`useQuoteStream(ids)` mounted at portfolio/screener pages; `useTickFlash(id)` consumed by every price/change cell. Backpressure: rAF-batch when >30 ticks/s. Stale handling: WS disconnect → set freshness=stale; reconnect with backoff (already in `AlertStreamContext` — generalize). StatusBar 3px dot: teal=connected, amber=reconnecting, red=disconnected.

---

# Section 5 — Search & Navigation

**Maturity:** 5.0/10 · Cross-cuts Layout, Components, Codebase

### Strengths
- `cmdk` library installed with debounce + recent items.
- Click-outside via mousedown post-SEARCH-001 fix.
- Keyboard hints strip in dropdown.

### CRITICAL Findings (consolidated from Layout F-001/026/033, Components F-005/006)

1. **Dead chord shortcuts** — six advertised, zero implemented. (Layout F-001)
2. **No command palette superset** — `⌘K` is symbol-only, no actions/articles/recents. (Layout F-026, Components F-006)
3. **No global symbol input / Bloomberg-style "ticker first then function"** — to analyze TSLA, user types ticker → clicks result → switches to workspace tab → re-types TSLA in chart panel → re-types TSLA in fundamentals panel. (Layout F-033)
4. **No symbol disambiguation** — multiple AAPLs across exchanges return flat list, no MIC grouping, no ISIN/CUSIP support. (Components F-005)

### Recommended Search Architecture

```
GlobalSearch (existing, expanded)
├─ "/" focuses
├─ "ticker..."           → Symbols group (grouped by Primary/Secondary/Other exchange)
├─ ">action..."          → Actions group (refresh, create-alert, open-screen, settings, sign-out)
├─ "?"                   → Help / cheat-sheet
├─ Empty state           → Recent symbols + Recent actions
└─ Cmd+Enter on result   → Open in new workspace panel (Bloomberg <GO>)

Plus: Global symbol input pinned in StatusBar left edge
├─ Tab key adds modifier (AAPL Tab CN → chart+news pair)
├─ Persists last 10 symbols in pill row
└─ Drives active linked-color group
```

---

# Section 6 — Codebase Architecture

**Maturity:** 4.5/10 · **Findings:** 47 · **CRITICAL:** 10 · **MAJOR:** 17 · **MINOR:** 13 · **NIT:** 7

### Strengths
- Comment density exceptionally high — onboarding-friendly.
- Auth security correct: token in React state only, OIDC PKCE, JWT exp pre-check (ADR-F-18).
- CSP / X-Frame-Options / HSTS / Referrer-Policy configured (`next.config.ts` SEC-001 fix).
- Server/client split correct in Next.js 15 App Router.
- Heavy widgets dynamically imported (EntityGraph via `next/dynamic ssr:false`; pdf/xlsx-export lazy callbacks).
- `react-resizable-panels` debounced persistence with v1→v2 migration framework.

### CRITICAL Findings

**F-CODE-001 — `lib/gateway.ts` is 2,415 LOC**
100+ methods on one closure, mixed with response transformers (e.g., raw OHLCV → typed bars), per-method retry, 404-fallback. Untestable as a unit.
**Fix:** Split into domain modules (`lib/api/instruments.ts`, `portfolios.ts`, `alerts.ts`, etc.). Better: codegen from S9 OpenAPI via `openapi-typescript-fetch` or `orval` — drift-free.

**F-CODE-002 — Hand-written `types/api.ts` is 1,214 LOC, no codegen**
Comments betray drift cost: "*WHY transform: S3 returns OHLCVListResponse with `items` (not `bars`)*". A rename in any of 10 backends silently breaks the UI.
**Fix:** Add `openapi-typescript` to S9 CI, commit `types/generated/api.ts`, contract test in S9 fails build on shape change. Replace with `import type { components } from '@/types/generated/api'`.

**F-CODE-003 — `app/(app)/portfolio/page.tsx` is 1,704 LOC**
2 dialog components inline + 12 useQuery hooks + 17 useState + 50-LOC kpi memo + 45-LOC sector/type breakdown + tab JSX. **The page a BlackRock PM lands on.**
**Fix:** Split into `<PortfolioPage>` (orchestrator <100 LOC), `<PortfolioHeader>`, `<HoldingsTab>`, `<TransactionsTab>`, `<WatchlistsTab>`, `<BrokeragesTab>`, dialog components. Co-locate queries inside tabs.

**F-CODE-004 — `app/(app)/chat/page.tsx` is 1,242 LOC**
SSE streaming + thread list + thread search + slash-command parsing + citation rendering + history + inline rename + markdown export — all in one component.
**Fix:** Hoist SSE into `useChatStream(threadId)`. Split sidebar / conversation / composer.

**F-CODE-005 — No URL state for filters/tabs/periods**
Active tab, screener filter, equity-curve period, transaction filter, active portfolio, active workspace are all `useState` only. None survive refresh, none can be shared via link. **Bloomberg analysts share views via URLs constantly.**
**Fix:** `nuqs` or `useSearchParams` adapter. Every filter and tab → URL.

**F-CODE-006 — TanStack Query keys are scattered string literals**
`["watchlists"]` vs `["watchlists-sidebar"]` vs `["watchlist-members", id]` vs `["watchlist-active-quotes", id, ids]` — same logical resource, multiple key prefixes. After mutations, code invalidates `["watchlists"]` and hopes everything refetches.
**Fix:** Central key factory with hierarchical keys (TanStack official pattern):
```ts
export const qk = {
  portfolios: () => ["portfolios"] as const,
  portfolio: (id) => [...qk.portfolios(), id] as const,
  holdings: (id) => [...qk.portfolio(id), "holdings"] as const,
  ...
};
```

**F-CODE-007 — 12+ useQuery on one page with sequential `enabled` waterfalls**
Q1 portfolios → Q2 holdings → Q3 quotes → Q7.5 overviews → Q4 transactions → ... 5-deep waterfall before KPI computes. Critical render path 2-3s.
**Fix:** Server-side compose endpoint `GET /v1/portfolios/{id}/page-bundle` returning portfolio+holdings+overviews+transactions in one round-trip.

**F-CODE-008 — Direct WebSocket to S10 violates "frontend → S9 only" (Rule 14)**
`new WebSocket(${wsBase}/api/v1/alerts/stream?token=...)` connects directly to S10:8010. Token in URL → server logs.
**Fix:** Add WebSocket proxying in S9 (FastAPI 0.110 supports WS routes). Frontend connects to `wss://gateway.example.com/v1/alerts/stream`; S9 forwards to S10 internal.

**F-CODE-009 — Three chart libraries ship to all clients**
lightweight-charts + recharts + sigma + graphology + raw SVG. ~400KB gz combined.
**Fix:** Drop recharts (~80KB gz) — migrate sparklines + equity curve to lightweight-charts (line mode) or pure SVG. Keep sigma for graph (no real alternative).

**F-CODE-010 — Three dead npm dependencies**
`react-grid-layout` (zero imports), `react-resizable` (replaced by `react-resizable-panels`), `@radix-ui/react-toast` (no toast provider mounted). ~80KB gz dead weight.
**Fix:** Remove all three. Install + mount `sonner`; standardize errors on `toast.error()`.

### MAJOR Findings (selected)

- **F-CODE-011** `WatchlistMoversWidget` is 800 LOC.
- **F-CODE-012** `ScreenerFilterBar` is 986 LOC; consider `react-hook-form + zod`.
- **F-CODE-013** OHLCVChart has 14 separate useEffect for indicator visibility — bundle into `INDICATOR_DEFS` registry map.
- **F-CODE-014** No toast primitive (38 sites with inline error strings).
- **F-CODE-016** `createGateway(accessToken)` recreated on every render in 112 sites. Memoize once via `useGateway()` provider.
- **F-CODE-018** Zero `React.memo` despite 130 client components and 15s polling. Combined with inline closures (38 files), child components never bail out.
- **F-CODE-019** `holdingInstrumentIds` array recomputed every render → query key changes → REFETCH STORM. (`useScreenerSparklines` does it correctly via `stableIds.join(",")` — copy that.)
- **F-CODE-020** Two virtualization libs (`@tanstack/react-virtual` + `react-window`) — standardize on tanstack.
- **F-CODE-021** localStorage state bypasses React (53 files write directly). Wrap in `lib/storage.ts` with zod schema validation + migration framework.
- **F-CODE-022** `tsconfig.json`: `noUncheckedIndexedAccess` is OFF. Enable; expect ~300 errors most of which are real bugs.
- **F-CODE-025** `@typescript-eslint/no-explicit-any` set to `warn` not `error`. 27 files use `any`/`as any`. Bump to `error`.

### Architecture Redesign (proposed structure)

```
apps/worldview-web/
├── app/(app)/                       ← Next.js routes (thin orchestrators <100 LOC each)
├── features/                        ← domain-by-folder (NEW)
│   ├── portfolio/
│   │   ├── components/{PortfolioPage,HoldingsTab,TransactionsTab,...}.tsx
│   │   ├── hooks/{usePortfolioKPI,useEnrichedHoldings}.ts
│   │   ├── queries/keys.ts
│   │   └── lib/kpi.ts               ← pure functions (testable)
│   ├── screener/  alerts/  chat/  instruments/  workspace/  auth/
├── components/ui/                   ← shadcn primitives only (cross-feature)
│   ├── data/{HeatCell,MiniChart,DataTimestamp}.tsx
│   ├── EmptyState.tsx               ← consolidated from 3 variants
│   └── Toaster.tsx                  ← NEW (sonner)
├── lib/
│   ├── api/{client,instruments,portfolios,alerts,...}.ts
│   ├── format/{price,percent,datetime}.ts   ← split lib/utils.ts
│   ├── query/{keys,useAuthedQuery}.ts
│   ├── storage/{safe-storage,migrators}.ts
│   └── icons.tsx                    ← lucide stroke-1.5 shim
├── types/
│   ├── generated/api.ts             ← from S9 OpenAPI (CI-enforced)
│   └── domain.ts                    ← branded domain types
└── shell/{TopBar,Sidebar,StatusBar}/
```

### State Management Strategy

| State kind | Owner | Pattern |
|---|---|---|
| Server data (quotes, holdings, news, alerts) | TanStack Query | Hierarchical key factory; `useAuthedQuery` wrapper; per-resource staleTime |
| Real-time WS data | React Context | `AlertStreamProvider`; consider Zustand for `criticalQueue` |
| Auth | React Context | `AuthProvider` — already correct |
| **URL state (filter/period/tab/active)** | **`nuqs` / `useSearchParams`** | **EVERY filter and tab** |
| Local UI (dialog, hover, sort dir) | `useState` | local-only |
| Cross-feature UI (theme, density, layout) | Zustand persist | Replace 4 hand-rolled localStorage contexts |
| User preferences (sidebar width, workspaces, link colors) | Zustand persist middleware | Shared migration framework |
| Form state (>3 fields) | `react-hook-form + zod` | screener filter, dialog forms |

### Performance Budget (proposed CI gate)

| Metric | Target |
|---|---|
| LCP (Dashboard, Portfolio, Screener) | < 1.8s |
| TTI (any page) | < 2.5s |
| First-load JS / route | < 220KB gz (excludes lightweight-charts lazy) |
| Total JS for `/portfolio` | < 380KB gz |
| Re-render count per 15s tick | < 30 components |
| Long task per interaction | < 50ms |
| Prod deps count | <= 35 (currently 47) |

---

# Top 12 Priorities — BlackRock-Readiness Roadmap

Impact-ordered. **Closing items 1–6 alone shifts perception from "polished consumer fintech" to "credible institutional terminal."** Estimated 3-week focused effort.

| # | Priority | Sections | Effort | Impact |
|---|----------|----------|--------|--------|
| **1** | **WebSocket quote stream + tick-flash on every price/change cell** | Data Viz F-001, Components F-001 | 5d (incl. S9 backend) | 10/10 — single largest credibility leak |
| **2** | **Wire real keyboard shortcuts + global symbol input + command palette superset** | Layout F-001/026/033, Components F-016 | 3d | 10/10 — terminals are keyboard-driven |
| **3** | **OHLCV chart upgrade: HUD + log scale + compare overlay + earnings/news markers + multi-pane indicators** | Data Viz F-002/003/006/007/010 | 4d | 9/10 — chart is the demo's centerpiece |
| **4** | **Color tokens: `--positive` `#26A69A` → `#00D26A`; `--negative` `#EF5350` → `#FF3B5C`; rewrite `heatCellColor()` zero-hue base; collapse `MarketHeatmap`/`SectorHeatmapWidget` to one** | Visual F-001/002/003, Data Viz F-018/020 | 1d | 9/10 — three-line CSS change with massive perceptual lift |
| **5** | **Generate `types/api.ts` from S9 OpenAPI; split `lib/gateway.ts` into domain modules** | Codebase F-001/002 | 4d | 9/10 — unblocks every other refactor |
| **6** | **Promote `/watchlists` to real hub; remove `/portfolio` watchlists tab; fix all redirect-stub routes** | Layout F-003/028 | 2d | 8/10 — IA correctness |
| **7** | **Decompose `portfolio/page.tsx` (1,704→<100 LOC orchestrator) and `chat/page.tsx`; add URL state for all filters/tabs/periods** | Codebase F-003/004/005, Layout F-010/011 | 4d | 8/10 — demo-page correctness |
| **8** | **Tables: add `ContextMenu` primitive; multi-sort; column resize/reorder/freeze on `SemanticHoldingsTable`; multi-select + bulk actions; sparklines on every list** | Components F-002/003/004/021/022, Data Viz F-005 | 5d | 8/10 — table interactions are the bar |
| **9** | **Add `density` cva variants to `Button`/`Input`/`Select`/`Tabs`/`Dialog`; reduce defaults to h-7 / h-6; lock 6-size type scale; lucide stroke-1.5 shim; ban `text-base|2xl|4xl|rounded-md`** | Visual F-004/005/006/011/013/014 | 2d | 7/10 — kills the consumer-app drift |
| **10** | **Add toast (sonner); remove dead deps (`react-grid-layout`, `react-resizable`, `@radix-ui/react-toast`, `recharts`); standardize on one virtualization lib** | Codebase F-009/010/014/020 | 2d | 7/10 — bundle hygiene |
| **11** | **Stabilize derived arrays (`useStableArray`); add `React.memo` to row/cell leaf components; memoize gateway via `useGateway()`; add `useAuthedQuery` wrapper** | Codebase F-016/018/019, F-015 | 2d | 7/10 — fixes polling-perf storm |
| **12** | **Multi-monitor pop-out (panel `Maximize2` button is no-op today); workspace quad-symbol template + drag-tray + chord splits; user-customizable IndexTicker** | Layout F-013/004/006 | 5d | 7/10 — disqualifying gap closed |

**Stretch (post-roadmap):**
- F-CODE-022 enable `noUncheckedIndexedAccess`
- F-CODE-038 nonce-based CSP middleware (replace `'unsafe-inline'`)
- F-CODE-008 WebSocket proxying via S9
- Storybook 8 + Chromatic for visual regression
- `noEmoji` lint rule + accessibility AAA pass on all data text

---

# Files of Note (absolute paths)

**Largest god-files (refactor candidates):**
- `lib/gateway.ts` — 2,415 LOC
- `app/(app)/portfolio/page.tsx` — 1,704 LOC
- `app/(app)/chat/page.tsx` — 1,242 LOC
- `types/api.ts` — 1,214 LOC
- `components/instrument/OHLCVChart.tsx` — 1,003 LOC
- `components/screener/ScreenerFilterBar.tsx` — 986 LOC
- `components/dashboard/WatchlistMoversWidget.tsx` — 800 LOC

**Color/typography source of truth:**
- `app/globals.css` (CSS variables)
- `tailwind.config.ts`
- `lib/utils.ts:248-265` — `heatCellColor()`
- `docs/ui/DESIGN_SYSTEM.md`

**UI primitives needing density variants:**
- `components/ui/{button,input,select,dialog,tabs,dropdown-menu}.tsx`

**Tables (consolidate into shared `DataTable`):**
- `components/portfolio/SemanticHoldingsTable.tsx`
- `components/portfolio/TransactionsTable.tsx`
- `components/screener/ScreenerTable.tsx`
- `components/instrument/InsiderTransactionsTable.tsx`

**Chart system:**
- `components/instrument/OHLCVChart.tsx`
- `components/workspace/WorkspaceChartWidget.tsx`
- `components/instrument/{FundamentalSparkline,RevenueTrendSparklines,EarningsHistoryChart,52WeekRangeBar}.tsx`
- `components/portfolio/EquityCurveChart.tsx`
- `components/screener/{HeatCell,MiniChart}.tsx`
- `components/dashboard/{MarketHeatmap,SectorHeatmapWidget}.tsx` (consolidate to one)

**Real-time:**
- `components/instrument/LiveQuoteBadge.tsx`
- `components/ui/StaleBadge.tsx`
- `contexts/AlertStreamContext.tsx`

**Shell / navigation:**
- `components/shell/{TopBar,Sidebar,CollapsibleSidebar,StatusBar,GlobalSearch,IndexTicker,WatchlistPanel,AlarmsPanel,FlashOverlay}.tsx`

**Workspace:**
- `app/(app)/workspace/page.tsx`
- `components/workspace/{WorkspaceGrid,WorkspaceTabs,WorkspacePanelContainer,SymbolLinkColorPicker,*Widget}.tsx`
- `contexts/{WorkspaceContext,SymbolLinkingContext}.tsx`

---

# Compounding — Patterns to Add

1. **`docs/BUG_PATTERNS.md`** — add BP entries:
   - BP-NEW-A: "Hand-typed API response interfaces drift silently from backend OpenAPI; always codegen."
   - BP-NEW-B: "Recomputed-array query keys cause refetch storms; stabilize via `useStableArray` or `.join(',')` key normalization."
   - BP-NEW-C: "Advertising chord shortcuts in StatusBar without wiring a global hotkey listener teaches users their muscle memory will fail."
   - BP-NEW-D: "Polling-only quote UIs read as 'frozen' to institutional users within 30s of demo; tick-flash is the recognizable primitive."

2. **`.claude/review/heuristics/HIGH_RISK_PATTERNS.md`** — add HR entries:
   - HR-NEW-1: "UI primitive `default` size at consumer SaaS scale (h-9, p-6) when feature components shadow with bespoke compact constants — drift signal."
   - HR-NEW-2: "Multiple chart libraries in `package.json` (recharts + lightweight-charts + sigma) — bundle bloat + visual style drift."
   - HR-NEW-3: "Hardcoded hex values in `lib/utils.ts` formatters that bypass CSS variable tokens."

3. **`docs/ui/DESIGN_SYSTEM.md`** — sections to add/update:
   - §3.4 Negative number convention (hyphen, not parens) — explicit decision
   - §4.x Chart engine policy: lightweight-charts for time series; raw SVG for sparklines; sigma for graph; **no recharts**
   - §6.x Density cva variant convention on all UI primitives
   - §7.x Hotkey scheme + chord conventions
   - §8.x Number formatting standard (single canonical `lib/format.ts`)
   - §9.x Real-time tick-flash + freshness dot pattern

4. **CI gates to add:**
   - `pnpm exec depcheck` — fail on dead deps
   - Lighthouse CI — performance budget per route
   - `eslint-plugin-tailwindcss` — ban `text-base|2xl|4xl|rounded-md|amber-*|blue-*` outside marketing pages
   - `openapi-typescript` regen check — fails build if `types/generated/api.ts` is out of sync with S9

---

**Report file:** `docs/audits/2026-04-29-qa-institutional-ui-audit-report.md`
**Total findings:** 220 across 5 specialist agents · 32 CRITICAL · 75 MAJOR · 79 MINOR · 34 NIT
**Verdict:** PASS_WITH_WARNINGS — production-credible chrome; close Top 12 priorities for BlackRock-grade.
