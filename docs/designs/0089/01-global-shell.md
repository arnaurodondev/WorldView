# Global Shell (TopBar / Sidebar / Watchlist / Hotkeys / Status) — Design Spec (PRD-0089)

> Surface: persistent chrome wrapped around every authenticated route by
> `app/(app)/layout.tsx`. Owns the 32px TopBar, 200px collapsible sidebar
> (with sticky Watchlist surface), 22px StatusBar, and the global chord
> hotkey infrastructure.

## 1. Competitor research summary

### Bloomberg Terminal (the reference)
- Top "Function Bar" is ~24-28px tall and packs **the FNZX index strip
  (Dow/Nasdaq/SPX), VIX, FX cross, 10Y yield, gold, oil, BTC, time + market
  status**, with the four-character function command line at the very top
  edge. A single horizontal row carries 10-14 data cells at 9-11px mono
  text — no consumer-style brand block, no oversized avatar.
- Left rail is a vertical **monitor panel**: 9-12 watchlist tickers per
  screen at row height ~18-22px, each row = ticker + last + chg + chg%,
  occasionally with a 30-50px-wide sparkline column. Section dividers are
  1-pixel hairlines, never empty bands of padding.
- Status / command bar at the bottom shows the current function code
  (e.g. `EQUITY GO`), connection status, and a tiny live clock.
- **What to steal**: density of the top row (8+ data cells, no whitespace),
  uppercase 9px section labels, hairline-only dividers, sparkline column on
  the watchlist, function-code label in the StatusBar.

### TradingView
- Global search palette is **Cmd+K**, opens an overlay with fuzzy ticker
  search, type-ahead categories (Stock / Crypto / Forex / Index), and recent
  symbols pinned at the top.
- Watchlist sidebar is multi-column: ticker, last, chg%, **plus a 40-50px
  inline sparkline** colored green/red by trailing trend. Row height ~24px.
- Light-on-dark color discipline: greens at ~#26A69A, reds at ~#EF5350.
- **What to steal**: Cmd+K palette pattern, sparkline column at 40×16px,
  recent-tickers pinned strip.

### Finviz
- Top "Market Performance" strip is the densest reference on the web: each
  cell is 1 metric in 10-11px text (SPY, QQQ, DIA, VIX, sectors, FX, crypto,
  bond yields). No empty space — every pixel is a number.
- **What to steal**: the principle that *if the TopBar has spare horizontal
  space, add another data cell* — never leave a gap.

### Interactive Brokers TWS
- "Quote Monitor" rows are 20-22px tall with: ticker (mono 11px), bid/ask/
  last/chg/chg% (mono right-aligned), and an optional 32px mini-spark.
- Multi-watchlist tabs at the top of the monitor panel (we copy this via the
  watchlist-name dropdown switcher already present).
- **What to steal**: multi-row dense layout with optional micro-sparklines,
  tab/dropdown switcher.

### Koyfin / Stockanalysis.com
- Modern dark themes with slightly more breathing room than Bloomberg
  (24-26px rows). Useful as a *minimum-density floor* — if a surface is less
  dense than Koyfin we have gone too consumer.
- **What to steal**: column-header treatment (10px uppercase, tracking-wide,
  muted-foreground) — already in our codebase as `text-[10px] uppercase
  tracking-[0.08em] text-muted-foreground`.

## 2. User intent for this surface

- **Primary persona**: hedge-fund PM / quant analyst running the platform
  full-screen during market hours. Has muscle memory for `g d`, `g p`, etc.
  Expects watchlist + portfolio P&L visible at all times without navigating
  away from the current research page.
- **Primary tasks**:
  1. Glance at portfolio NAV, Day P&L, and 4-6 watchlist tickers without
     leaving the current page.
  2. Jump to any of the 11 nav destinations in <300ms (icon click OR chord).
  3. Open command palette (Cmd+K) to search a ticker, screen, or news entity.
- **Secondary tasks**: read system status (market open/closed, data
  freshness, live WS connection), check unread alert count, open the AI
  chat panel from any page.
- **Anti-patterns** this shell must NOT become:
  - "Consumer-app dashboard" with hero brand block + oversized avatar.
  - Watchlist surface that says "Add symbols in Portfolio →" forever — once
    a watchlist exists the panel must render data, not instructions.
  - Bottom mnemonic hint bar that *advertises unwired chords* (the
    PLAN-0059 W1 fix: StatusBar MUST read from the live registry).

## 3. Backend data available (cite the inventory doc)

Cross-referenced against `00-backend-data-inventory.md`:

| Field | Source | Currently displayed | Notes |
|-------|--------|---------------------|-------|
| Portfolio total value (NAV) | S9 `GET /v1/portfolios/{id}/metrics` via `usePortfolioMetrics` | YES (TopBar PORT slot) | already wired |
| Day P&L (sum of qty × per-share daily change) | same hook | YES (TopBar Day P&L) | already wired |
| Unrealised P&L (mark-to-market vs cost basis) | same hook | YES (TopBar Total P&L) | already wired |
| 10-ticker marquee (SPY, QQQ, IWM, DIA, VIX, TLT, DXY, GLD, USO, BTC-USD) | S9 `POST /v1/quotes/batch` via `TopBarMarquee` | YES (animated scroll) | replace with **static index strip** — see §6 |
| Watchlist members + names | S9 `GET /v1/watchlists` | YES (sidebar) | already wired |
| Watchlist live quotes | S9 `POST /v1/quotes/batch` (30s refetch) | YES (price + chg%) | **add 1D sparkline column** — needs new route |
| Watchlist 1D intraday sparkline (5-min bars × 78) | S9 `GET /v1/instruments/{id}/intraday?interval=5m&period=1d` — **already exists** per inventory | NO | sparkline column requires this |
| Pending alert count | S9 `GET /v1/alerts/pending?limit=1` (60s poll) | YES (bell badge) | already wired |
| Alarms list (recent N severity-ranked) | S9 `GET /v1/alerts/pending` | YES (AlarmsPanel sidebar) | already wired |
| Market session status per exchange | S9 `GET /v1/market/status` via `MarketStatusPill` | YES (TopBar pill) | already wired |
| WS connection status | `useAlertStream().connected` | NO | **NEW** — surface in StatusBar |
| Data freshness (last quote tick age) | per-quote `received_at` | NO | **NEW** — staleness dot in StatusBar |
| UTC clock | local | YES (TopBar) | already wired |
| Sector heat (S&P 11 GICS) | S9 `GET /v1/market/sectors` (per inventory) | NO | **OPTIONAL** — see §6 wireframe note |
| User-explicit "AI brief / company description / sector breakdown" | (page-level — out of scope here, see `02-dashboard.md` / `07-instrument-intelligence.md`) | — | not a shell concern |

**Gaps the shell exposes**: 1D sparkline in watchlist (needs the intraday
endpoint above — confirmed available); WS connection dot + freshness dot in
the StatusBar.

## 4. Layout

### 4.1 ASCII wireframe — 1440×900, sidebar expanded

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐  ╳
│ Worldview │ Cmd+K Search… │ SPY 5824.12 +0.42% │ QQQ 511.66 -0.18% │ DIA 433.91 +0.21% │ VIX 14.32 -1.10% │ DXY 105.40 +0.05% │ TLT 88.20 -0.30% │ GLD 245.18 +0.41% │ USO 76.40 -0.62% │ BTC 99K -1.4% │ 13:42:18 UTC │ ● Open │ ┌PORT 1.24M │ Day +$12.4K │ Tot +$48.7K┐ │ AI │ ↻ │ ⚐3 │ AR │  ╳ 32px TopBar
├──────────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ▣ Dashboard          │                                                                                                                                     │
│ □ Portfolio          │                                                                                                                                     │
│ ↗ Instruments        │                                                                                                                                     │
│ ▦ Screener           │                                                                                                                                     │
│ ▤ Workspace          │                                                                                                                                     │
│ ⌁ Predictions        │                                                                                                                                     │
│ ⚐ Alerts             │                              MAIN CONTENT AREA — overflow-y-auto, scrolls independently                                              │
│ ⌨ Chat               │                              (page renders here — Dashboard / Instrument / Screener / etc.)                                          │
│ ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄│                                                                                                                                     │
│ WATCHLIST  Tech ▾    │                                                                                                                                     │
│ AAPL  234.56  +0.84% ▁▂▃▅▇                                                                                                                                 │
│ MSFT  428.12  +0.31% ▂▂▃▃▄                                                                                                                                 │
│ NVDA  142.80  -1.20% ▇▆▅▃▂                                                                                                                                 │
│ TSLA  267.40  +2.10% ▁▃▅▆▇                                                                                                                                 │
│ AMZN  198.65  +0.42% ▃▄▄▅▆                                                                                                                                 │
│ META  563.20  -0.18% ▅▅▄▄▃                                                                                                                                 │
│ GOOGL 175.10  +0.05% ▄▄▄▅▅                                                                                                                                 │
│ ASML  712.30  -0.65% ▆▅▄▃▂                                                                                                                                 │
│ +2 more →            │                                                                                                                                     │
│ ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄│                                                                                                                                     │
│ ALARMS         3     │                                                                                                                                     │
│ ● AAPL earn beat 09:31│                                                                                                                                    │
│ ● NVDA halt    08:55 │                                                                                                                                     │
│ ● SPY gap up   09:30 │                                                                                                                                     │
│ ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄│                                                                                                                                     │
│ ⚙ Settings           │                                                                                                                                     │
│ ‹ Collapse           │                                                                                                                                     │
├──────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ G D Dashboard · G P Portfolio · G S Screener · G W Workspace · G A Alerts · G C Chat · ⌘K Search · ?Help              │ INSTRUMENT │ ● WS Live · ● Quotes 3s│  ╳ 22px StatusBar
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
  ↑ 200px sidebar      ↑ 1240px main content                                                                                                                  ↑
```

### 4.2 Grid description

| Region | Dimensions | Position | Scroll |
|--------|-----------|----------|--------|
| TopBar | 1440 × 32 | sticky top, full width | none |
| Sidebar | 200 × (900 − 32 − 22 = 846) | sticky left below TopBar | inner watchlist + alarms scroll if overflow |
| Main content | (1440 − 200 = 1240) × 846 | right of sidebar, below TopBar | overflow-y-auto |
| StatusBar | 1440 × 22 | sticky bottom, full width | none |

### 4.3 Density target

- TopBar: **13 data cells minimum** visible at 1440px (10-ticker index strip
  + clock + market-status + 3-cell portfolio rail). Plus 4 action affordances
  (search, AI button, refresh, bell). Total: 17 distinct slots — no empty
  band between the brand wordmark and the right-edge avatar.
- Sidebar: **8 nav rows × 22px** + watchlist (8 tickers × 22px) + alarms
  (5 rows × 22px max) + 2 bottom-chrome rows = ~24 information rows in the
  200×846 column.

## 5. Component breakdown

| Component | File path | Line budget | What it renders | New vs existing |
|-----------|-----------|-------------|-----------------|------------------|
| TopBar | `apps/worldview-web/components/shell/TopBar.tsx` | ~250 | 32px header: wordmark + GlobalSearch trigger + IndexStrip + UtcClock + MarketStatusPill + PortfolioRail + AskAi + Refresh + Bell + Avatar | **modified** (drop marquee, add static IndexStrip) |
| IndexStrip | `apps/worldview-web/components/shell/IndexStrip.tsx` | ~120 | static 10-cell row of SPY/QQQ/DIA/VIX/DXY/TLT/GLD/USO/BTC + 10Y (each cell = ticker mono 11px, last mono 11px, chg% colored mono 10px) | **NEW** (replaces TopBarMarquee — see §9 tradeoff) |
| GlobalSearch | existing `components/shell/GlobalSearch.tsx` | unchanged | Cmd+K trigger button (collapses to icon at <1280px) | existing — verify it shows the inline `⌘K` kbd hint |
| MarketStatusPill | existing `components/shell/MarketStatusPill.tsx` | unchanged | tiny dot (h-1.5 w-1.5) + "Open"/"Closed" + per-session breakdown on hover | existing |
| UtcClock | existing `components/shell/UtcClock.tsx` | unchanged | "13:42:18 UTC" mono 11px | existing |
| AskAiButton | existing | unchanged | floating-panel trigger | existing |
| RefreshAllButton | existing | unchanged | re-fetch every TanStack query | existing |
| AlertBell | inline in TopBar | unchanged | bell icon + h-4 w-4 badge with `9+` overflow | existing |
| Avatar dropdown | inline in TopBar | unchanged | h-7 w-7 with text-[9px] initials | existing |
| CollapsibleSidebar | `components/shell/CollapsibleSidebar.tsx` | ~400 | rail 40px (collapsed) / 200px (expanded, was 220px); 8 nav rows; hosts WatchlistPanel + AlarmsPanel; drag-resize handle | **modified** (200px default, hairline dividers, see §6) |
| WatchlistPanel | `components/shell/WatchlistPanel.tsx` | ~280 | header row 24px (label + dropdown) + 8 ticker rows × 22px with **NEW sparkline column** + "+N more" link | **modified** (add WatchlistSparkline column) |
| WatchlistSparkline | `components/shell/WatchlistSparkline.tsx` | ~80 | 40×16px inline SVG path of 1D intraday closes, colored by sign of (last − open) | **NEW** |
| AlarmsPanel | existing | unchanged | header row + N alarm rows × 22px | existing |
| HotkeyCheatSheet | existing | unchanged | `?`/`g h` overlay enumerating registry | existing |
| GlobalHotkeyBindings | existing | unchanged | mounts useChordHotkeys + registers global chords | existing |
| StatusBar | `components/shell/StatusBar.tsx` | ~250 | 22px bottom bar: left = 6 chord hints from registry + Help; right = active page label + WS dot + freshness dot | **modified** (add freshness dot, page-scope hint group rotation) |

Notes:
- IndexStrip is the *single biggest change* — the current animated marquee
  consumes the entire 640px center slot. A static 10-cell row at 11/10px
  mono fits comfortably in ~640px and removes the WCAG-prefers-reduced-motion
  branch (always-static).
- WatchlistPanel keeps its dropdown watchlist-switcher (TradingView pattern),
  but the 22px row gains a 4th column at 40px width for the inline spark.

## 6. Visual spec (numerical)

### TopBar — `header.h-8` (32px)
- Height: **32px** (`h-8`). Border-bottom: 1px `border-border` (#1F1F23).
- Background: `bg-background` (#09090B). NO shadow / NO elevation.
- Horizontal padding: 12px (`px-3`). Inter-cell gap: 12px (`gap-3`).
- Wordmark: `font-mono font-bold text-[13px] tracking-tight`, color `text-foreground`. Button (router push to /dashboard).
- GlobalSearch trigger: 28×24px input-styled button, placeholder "⌘K Search…" in `text-[11px] text-muted-foreground`.
- **IndexStrip cell** (×10):
  - Width: `w-[60px]` per cell (60 × 10 = 600px) + 8px gap. Total = 680px max.
  - Ticker: `font-mono font-medium text-[11px] text-foreground`.
  - Price: `font-mono tabular-nums text-[11px] text-foreground` (e.g. `5824.12`). Compact-format > 10K: `99K`, `1.2M`.
  - Chg%: `font-mono tabular-nums text-[10px]` colored `text-positive` / `text-negative` / `text-muted-foreground` (deadband ±0.005%).
- UtcClock: `font-mono tabular-nums text-[11px] text-muted-foreground`, fixed 92px slot (`13:42:18 UTC`).
- MarketStatusPill: 1.5px green/amber/red dot + `text-[10px] uppercase tracking-[0.08em]` status word.
- PortfolioRail box: 1px border `border-border/30`, `bg-muted/20`, padding `px-2 py-0.5`, `rounded-[2px]`, 3 slots with hairline `bg-border/40 h-3 w-px` dividers.
- AskAi / Refresh / Bell icons: 16px stroke-1.5, `text-muted-foreground hover:text-foreground`.
- Alert bell badge: h-4 w-4, `bg-destructive`, `text-[10px] font-medium` (max "9+").
- Avatar: h-7 w-7 with `text-[9px]` initials fallback.

### Sidebar — `aside.w-[200px]` (expanded) / `aside.w-10` (40px collapsed)
- Default width: **200px** (was 220px). Min: 160px. Max: 340px.
- Background: `bg-background`. Hairline separator on the right edge via the
  drag handle's `w-px bg-border`.
- Nav rows: `h-7` (28px) `px-2.5 gap-1.5`. Icon h-[14px] w-[14px] stroke-1.5.
  Label `text-[10px] font-medium`. Active: `bg-primary/10 text-primary border-l-2 border-primary`.
- Section dividers: **1px hairline only**, no padding-band — replace any
  inter-section gap with `border-t border-border`. NEVER `mt-2` between sections.
- WatchlistPanel header: `h-6` (24px), `border-b border-t border-border`,
  `text-[10px] uppercase tracking-[0.08em] text-muted-foreground` label,
  dropdown chevron `text-[10px] font-mono`.
- Watchlist row: **22px (`h-[22px]`)** with `divide-y divide-border/30`. Columns:
  | Col | Width | Style |
  |-----|-------|-------|
  | Ticker | 44px | `font-mono text-[11px] text-foreground truncate` |
  | Price | flex-1 right-aligned | `font-mono tabular-nums text-[11px] text-foreground` |
  | Chg% | 44px right-aligned | `font-mono tabular-nums text-[11px]` colored by sign |
  | **Sparkline** | **40px × 16px** | inline SVG path, `stroke-positive` / `stroke-negative` 1px |
  - Row total: 44 + (flex) + 44 + 40 = ~192px content width (sidebar inner = 196px after px-2). Fits exactly.
- AlarmsPanel: same 22px row pattern, 6px dot + 11px message + 10px timestamp (existing).
- Bottom chrome: Settings + Collapse, same h-7 row pattern, `border-t border-border` between them and the watchlist/alarms cluster.

### StatusBar — `div.h-[22px]` (was h-6 24px)
- Height: **22px** (`h-[22px]` — propose new height; existing is 24px).
  *Justification for the change*: aligns visually with the 22px watchlist
  row standard from the shared tokens. 2px reclaim across the full viewport
  width is meaningful when the goal is "max data above fold".
- Background: `bg-background`. Top border: 1px `border-t border-white/[0.06]` (subtler than full `border-border` because it's the lowest-priority chrome).
- Left cluster — chord hints (registry-derived):
  - 6 chord hints at `text-[10px] text-muted-foreground/50` with `<kbd>` in `font-mono text-[9px] text-primary/70`.
  - Inter-hint gap: 12px (`gap-3`).
- Center — separator (optional `·` glyph).
- Right cluster — page label + status dots:
  - Active page label: `font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground/50`.
  - **WS connection dot**: 1.5×1.5 px (`h-1.5 w-1.5 rounded-full`). Color:
    - `bg-positive` when `useAlertStream().connected === true`
    - `bg-warning` while reconnecting
    - `bg-destructive` when disconnected > 5s
    - Label "WS Live" / "WS Reconnecting" / "WS Offline" `text-[10px] font-mono`.
  - **Freshness dot**: 1.5×1.5 px. Color:
    - `bg-positive` when last quote tick < 5s old
    - `bg-warning` when 5-30s old
    - `bg-muted-foreground` when > 30s (treated as stale)
    - Label `text-[10px] font-mono` showing e.g. "Quotes 3s" / "Stale 42s".

### Color palette compliance
- All colors come from §_INDEX.md shared tokens: `--background`, `--card`,
  `--border`, `--foreground`, `--muted-foreground`, `--primary`,
  `--positive`, `--negative`, `--warning`, `--destructive`.
- **No new tokens introduced.** The only new utility used is `border-border/30`
  and `bg-border/40` which are Tailwind opacity modifiers on existing tokens
  (already in use in this codebase per `WatchlistPanel.tsx:199`).

### Font-size compliance
- Every font size comes from the shared scale: 9 / 10 / 11 / 13 px. No 14px
  or larger except the existing 13px wordmark (already on the page chrome
  whitelist per §_INDEX Typography).

## 7. Interaction model

### 7.1 Hotkeys (already implemented — verified via `lib/hotkey-registry`)

#### Global scope (always active outside text inputs / modals)
| Chord | ID | Action |
|-------|----|----|
| `g d` | `nav.dashboard` | router push `/dashboard` |
| `g p` | `nav.portfolio` | router push `/portfolio` |
| `g i` | `nav.instruments` | router push `/instruments` |
| `g s` | `nav.screener` | router push `/screener` |
| `g w` | `nav.workspace` | router push `/workspace` |
| `g a` | `nav.alerts` | router push `/alerts` |
| `g n` | `nav.news` | router push `/news` |
| `g c` | `nav.chat` | router push `/chat` |
| `g ,` | `nav.settings` | router push `/settings` |
| `g h` | `nav.help.cheatsheet` | toggle cheat-sheet overlay |
| `mod+b` | `view.toggle.sidebar` | flip sidebar expanded/collapsed |
| `?` | `shell.help.cheatsheet` | toggle cheat-sheet overlay |
| `/` | `shell.search.focus` | focus GlobalSearch input |
| `mod+k` | (NOT registered — owned by cmdk's Dialog listener) | open command palette |

#### Scope rules (from `useChordHotkeys.ts` + `HotkeyContext.tsx`)
- Scope stack ordering (highest priority first):
  **modal > input > chart > table > page > global**.
- A binding registered with `scope: "modal"` overrides a global binding with
  the same chord *only when at least one modal is on the stack*.
- Scope counts are reference-counted via `pushScope` / `popScope`: nested
  modals each push "modal", the scope stays active until BOTH pop.
- A `<HotkeyScope scope="page">` component pushes "page" on mount and pops
  on unmount — automatic via useEffect cleanup.
- Page-scoped bindings (`scope: "page"`, with a `page: string | RegExp` matcher)
  are filtered against the current pathname by the cheat-sheet AND by the
  registry's `lookup()` — so e.g. the instrument-detail `q` / `f` / `i`
  tab-switch chords (registered in `app/(app)/instruments/[entityId]/`) only
  resolve when pathname starts with `/instruments/`.
- Suspension inside text inputs: `<input>` (text-like types only), `<textarea>`,
  `[contenteditable]` automatically suspend single-letter chords. Modifier-
  bearing chords (mod+k, mod+enter) pass through.
- IME composition (`e.isComposing`) is ignored.
- Chord reset window: **1.2s** (Linear / Notion use ~1s; we use a slightly
  longer window to tolerate jitter).
- Escape always clears the chord buffer AND falls through to fire an `Esc`
  binding if registered.

#### Scope contract for future agents
- **DO** wrap any modal you build in a `<HotkeyScope scope="modal">` so global
  chords like `g d` don't fire while the modal is open.
- **DO** register page-scoped chords with explicit `page: "/instruments/"`
  (trailing slash → startsWith match) so they don't leak to other routes.
- **DON'T** register a chord at module scope — register it inside a
  `useEffect` in the component that owns the behavior so unmount unregisters
  it (registry returns an `unsub` function — call it in cleanup).
- **DON'T** preventDefault for unmatched chords — `useChordHotkeys` only
  preventDefault's on successful match so unbound keys still reach focus.
- **DON'T** register `mod+k` — it's reserved for cmdk's Dialog listener.
- **DO** put new global navigation chords in `GlobalHotkeyBindings.tsx` so
  they appear in one auditable list.

### 7.2 Hover behavior
- IndexStrip cells: hover → `bg-muted/20` row tint, click → navigate to
  `/instruments/<resolved-entity-id>` (already wired for the marquee chips).
- Watchlist rows: hover → `bg-muted/40` row tint, click → navigate to
  `/instruments/<entity_id>`.
- Sidebar nav items: hover → `bg-muted/40 text-foreground`. `duration-0` —
  no animation, instant color change (Bloomberg convention).
- Sparkline: no hover state at 40×16px (too small for a tooltip; the chg%
  cell already carries the magnitude information).
- StatusBar chord hints: title-tooltip = full label ("Go to Dashboard")
  appears on hover via native `title` attr (no custom tooltip component).

### 7.3 Click handlers
- TopBar wordmark → `/dashboard`.
- IndexStrip cell → `/instruments/{entity_id}`.
- Watchlist row → `/instruments/{entity_id}`.
- "+N more →" link → `/portfolio?tab=watchlists`.
- AlertsBell → `/alerts`.
- Avatar → dropdown (Profile / Settings / Sign out).
- AskAi → opens floating panel (`setAskAiOpen(true)`).
- Refresh → invalidates all TanStack queries.
- Sidebar Collapse chevron → flips `sidebarExpanded`, persists to localStorage.
- StatusBar chord hints → no click handler (purely informational; chords are
  the interaction).

### 7.4 Loading / error / empty states (REQUIRED for every state)
- **TopBar IndexStrip — loading**: render 10 placeholder cells with `bg-muted/30` skeleton text "—" and the ticker label visible. Never collapse to zero — the strip must always occupy its width slot to prevent re-layout when data arrives.
- **TopBar IndexStrip — error**: keep the last-known values cached in TanStack with `staleTime: 60_000`. On hard error, leave the cells at their last-good values and surface a small `bg-warning` dot on the MarketStatusPill (already implemented).
- **TopBar IndexStrip — empty**: not possible (the manifest is static).
- **PortfolioRail — loading**: each slot shows `—` until value resolves. The wrapper renders only if at least one value is non-null (avoids a stub box on brand-new accounts).
- **PortfolioRail — empty (no portfolio)**: hide the entire box. The avatar and bell still anchor the right cluster.
- **Watchlist — loading**: skeleton rows. Show 5 skeleton rows at 22px so the sidebar height doesn't jump when data arrives.
- **Watchlist — empty (no symbols in active watchlist)**: render the existing inline text `Add symbols in Portfolio → Watchlists` at `text-[11px] text-muted-foreground` — but only when `watchlistsData.length === 0` OR `members.length === 0`. The instructional text must disappear the moment the first symbol is added.
- **Watchlist — error**: keep the last-cached members visible; show a 9px `text-warning` "stale" badge in the header row.
- **Sparkline — loading**: render an empty `<svg>` placeholder of the correct dimensions to prevent layout shift.
- **Sparkline — no intraday data (pre-market for a new instrument)**: render a flat `text-muted-foreground` 1px horizontal rule across the 40×16 box.
- **Alarms — empty**: existing inline text "No pending alarms" at `text-[11px] text-muted-foreground`.
- **StatusBar WS dot — disconnected**: red dot + "WS Offline" label. Tooltip says "Reconnecting…" if useAlertStream's retry timer is active.
- **StatusBar freshness dot — stale**: amber dot (5-30s old) → muted (>30s). Label updates every second.
- **HotkeyCheatSheet — empty filter result**: existing copy `No shortcuts match "<query>"`.

## 8. Data fetching

All TanStack Query keys use the `qk.*` factory from `lib/query/keys.ts`.
Proposed additions:

| Resource | Proposed key | staleTime | refetchInterval | Notes |
|----------|-------------|-----------|-----------------|-------|
| Index strip resolved entity IDs | `qk.shell.indexResolveIds()` | 30 min | none | static 10-ticker manifest → entity IDs; rarely changes |
| Index strip batch quotes | `qk.shell.indexQuotes()` | 0 | 15s | hot data; matches MarketStatusPill cadence |
| Watchlists list | `qk.watchlists.list()` (existing — currently inline as `["watchlists-sidebar"]`) | 30s | none | **promote inline key to factory** |
| Watchlist batch quotes | `qk.watchlists.quotes(memberIds)` (existing — currently inline) | 0 | 30s | **promote inline key to factory** |
| Watchlist intraday for sparkline | `qk.instruments.intraday(entityId, "5m", "1d")` (per inventory; may already exist) | 60s | 60s | **NEW dependent fetch** — one query per ticker, batched via `useQueries` |
| Pending alerts count | `qk.alerts.pendingCount()` (existing) | 60s | 60s | already wired |
| Pending alerts list | `qk.alerts.list()` (existing) | 30s | 30s | already wired |
| Market session status | `qk.market.status()` | 60s | 60s | already wired |
| Portfolio metrics | `qk.portfolios.metrics(portfolioId)` (via usePortfolioMetrics) | 15s | 15s | already wired |
| WS connection state | not a TanStack query — sourced from `useAlertStream().connected` | — | — | hook-driven |
| Freshness timestamp | derived from latest quote `received_at` in the index/watchlist caches | — | — | computed in StatusBar via `useQueryClient().getQueriesData(...)` |

**Dedup opportunities**:
- IndexStrip and TopBarMarquee currently both call `POST /v1/quotes/batch`
  for overlapping (but not identical) ticker sets — once IndexStrip
  replaces TopBarMarquee, this becomes a single key.
- Watchlist quotes and IndexStrip quotes can share the same `batch` endpoint
  but with different cache keys (the watchlist set is user-specific, the
  index set is global) — no actual cache dedup, but a single round trip per
  refetch tick if the gateway batches.
- The intraday sparkline query is the largest new cost: 8 watchlist members
  × 1 request every 60s = ~8 requests/min/user. Acceptable; can be reduced
  to one batched intraday endpoint as a follow-up if S9 adds it (not blocking).

## 9. Tradeoffs & decisions

### 9.1 Animated marquee vs static index strip
- **Option A (current)** — `TopBarMarquee`: 10-ticker CSS-animated scroll at
  60s/cycle. Pros: only ~640px wide regardless of how many tickers; "alive"
  feel. Cons: violates `prefers-reduced-motion` (must branch), only ~3
  tickers visible at any instant, scanning a specific ticker requires waiting
  for it to scroll into view, animation steals cognitive bandwidth.
- **Option B (recommended)** — `IndexStrip`: static 10-cell row, 60px per
  cell × 10 = 600px (fits the existing 640px center slot). All tickers
  always visible; no animation = no reduced-motion branch; Bloomberg/Finviz
  precedent. Trade-off: needs compact-format for price values >10K
  (`99K`, `1.2M`).
- **Option C** — 6-cell strip + sector heatmap (S&P 11 GICS as small colored
  blocks): more dense but adds a second concept (sectors) to the TopBar
  that the user hasn't asked for. Park as a `02-dashboard.md` feature.
- **Decision**: Option B. Eliminates motion, gains scan-ability, matches
  Bloomberg's FNZX strip exactly.

### 9.2 Sparkline column on watchlist
- **Option A** — no sparkline (current): 22px row with only ticker + price
  + chg%. Saves bandwidth (no intraday fetch) but the chg% number is the
  only trend signal.
- **Option B (recommended)** — 40×16px sparkline column: TradingView/IBKR/
  Stockanalysis precedent. Tiny enough that it doesn't break the 22px row
  budget (16px sparkline + 3px vertical padding fits inside 22px). Visual
  trend signal in addition to the chg% number — answers "is it falling or
  recovering?" without clicking through.
- **Option C** — 80px sparkline at the cost of dropping the chg% column:
  too aggressive — removes a key data point the user already relies on.
- **Decision**: Option B. The intraday endpoint already exists; one
  `useQueries` call covers all 8 visible rows; the visual trend value is
  worth the ~8 requests/min/user.

### 9.3 StatusBar height 22px vs 24px
- 24px is the current value and matches the watchlist row standard exactly.
- 22px (recommended) matches §_INDEX's row height token (`h-[22px]`) and
  reclaims 2px × full viewport width across the bottom — useful at the
  Bloomberg density target.
- **Decision**: 22px. The 9-10px label sizes fit at 22px (verified — the
  existing chord hints render at `text-[10px]` which is comfortable in a
  22px container).

### 9.4 Sidebar width 200px vs 220px (current)
- 220px is the current default; nav labels render comfortably.
- 200px reclaims 20px of horizontal main-content width — enough to fit one
  more table column at the screener density.
- 200px tested mentally: "Dashboard" (9 chars × ~6px mono = ~54px) + 14px
  icon + 12px padding + 10px gap-padding = ~90px. Well within 200px.
- **Decision**: 200px default. User can drag up to 340px if they want
  more breathing room — drag-resize already implemented.

### 9.5 Always-visible mnemonic cheat-sheet at sidebar bottom?
- The brief asks for "Hotkey mnemonic cheat-sheet always visible at bottom
  in 9px text". The current implementation puts this in the **StatusBar**
  (bottom of viewport, not sidebar). That's preferable because:
  - StatusBar already reads from the live registry (no risk of lying chords).
  - Putting the cheat in the sidebar duplicates information already in the
    StatusBar and wastes vertical sidebar space that the watchlist needs.
- **Decision**: keep cheat hints in StatusBar (left cluster); the sidebar
  bottom keeps only Settings + Collapse (existing). The `g h` / `?` cheat-
  sheet overlay handles the full discoverable list.

## 10. Open questions

1. **IndexStrip ticker set** — should the strip include the 10Y Treasury
   yield ticker (^TNX or similar)? Inventory says yields are available but
   the manifest currently lists USO as the 9th item. Recommend swapping USO
   → ^TNX so the strip carries one rates signal (Bloomberg precedent).
   *Needs user confirmation*.
2. **Watchlist sparkline data source** — confirm that `GET /v1/instruments/{id}/intraday?interval=5m&period=1d`
   exists in S9 (per `00-backend-data-inventory.md`). If only `period=5d`
   exists, fall back to the first 78 bars of the 5-day feed (still 1 day).
3. **Freshness dot — what defines "fresh"?** — proposed 5s / 30s thresholds
   are intuition-derived. If S9's batch-quote endpoint has a documented
   max-staleness SLA, use that as the boundary instead.
4. **Sidebar collapsed-state behavior on small viewports** — should the
   sidebar auto-collapse below 1280px? Current behavior is manual via
   `mod+b` only; auto-collapse would steal user control. Recommend keeping
   manual-only.
5. **Section-divider rendering** — the brief asks for "section dividers as
   1px hairlines, NOT spacing". This requires removing the `gap-2` /
   `space-y-*` between nav cluster ↔ watchlist ↔ alarms ↔ bottom-chrome
   and inserting `border-t border-border` instead. Confirm that's the
   desired visual (slightly tighter than today; harder dividing line). My
   recommendation is yes — matches Bloomberg.

---
