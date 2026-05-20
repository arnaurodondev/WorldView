---
id: PRD-0089-DESIGN-09
title: Workspace + Predictions + Alerts — Design Spec
status: draft
created: 2026-05-19
parent: docs/designs/0089/_INDEX.md
agent: agent-secondary-pages
covers:
  - /workspace
  - /prediction-markets
  - /alerts
---

# Secondary Pages — Design Spec (PRD-0089)

> **Bundled doc.** This file covers three navigationally-secondary surfaces
> that share the same density philosophy but differ in interaction model.
> Each section below is self-contained and follows the per-page skeleton
> mandated by `_INDEX.md`.

---

## PAGE A — Workspace (`/workspace`)

### A.1 Competitor research summary

**Bloomberg Terminal — multi-monitor layouts.**
The Bloomberg user opens a workspace by typing a command (`HELP HELP`, `LAUN`)
that fills the screen with up to 8 simultaneous functions. Each function
("monitor") draws ~22-28px row heights, uppercase 10–11px chrome, no rounded
corners. Workspaces are saved by name (`FAVO`) and restored across sessions.
Critically: **a single Security input at the top of the workspace broadcasts the
chosen ticker into every function below it**. Worldview already mirrors this via
`WorkspaceSymbolBar`. What we will steal further:
- Top-right "panel chrome cluster" — every Bloomberg function shows its
  function code (DES, GP, CN, FA) in the corner so the trader knows what they
  are looking at without reading the data. Worldview should render the panel
  type code (CHRT, NEWS, FUND, ALRT, SCRN) the same way.
- 1-pixel hairline dividers between every panel; **no shadows, no rounded
  panel edges**.
- Status footer per panel: data freshness ("RT 09:32:14"), source
  ("EODHD"), refresh button.

**Interactive Brokers Mosaic.**
The Mosaic workspace is the closest direct analogue to what `/workspace` aims
to be: a configurable grid of "panels" where each panel is an independent
widget bound to a symbol/portfolio context. Mosaic's strengths:
- **Tab-stacked panels** — a single panel slot can hold N tabs (Chart 1m,
  Chart 5m, Chart 1d). Worldview today binds one widget per panel; we should
  add tab-stacking so traders can flip between time frames without
  reconfiguring the layout.
- **Panel toolbar with 18px icons** — symbol input, time-range, indicator,
  pop-out, settings, close. Always present in the panel header, never inside
  a hamburger menu.
- **"Tear-off" pop-out** — every panel can be popped into a separate browser
  window so traders with 3+ monitors can distribute them. Out of scope for
  PRD-0089 v1 (requires window.open + BroadcastChannel), but the design
  must reserve a corner slot for the icon.

**TradingView multi-chart layouts.**
TradingView's "Layout" picker offers 1, 2, 4, 6, 8 sub-charts per page with
synchronized crosshair, time range, and (optionally) symbol. Steal:
- **Sync-crosshair across panels** — when the user hovers a candle in the
  top-left chart, every other chart panel in the same workspace draws the
  vertical crosshair at the matching time. Optional via a workspace-level
  toggle.
- **Layout presets** — 1up, 2-up (horizontal), 2-up (vertical), 2×2, 1+2,
  3+1. Worldview's templates today are content-based (Day Trader, Research);
  we add geometry-based presets too.
- **Synchronized time-range** — selecting "1D" in the master chart updates
  every chart panel in the workspace to 1D.

**Where Worldview diverges from competitors.**
Worldview's Workspace is the only one of the three with built-in AI surfaces
(Brief, Chat). Those need first-class placement in the panel catalogue, not
hidden in a "More" menu.

---

### A.2 User intent for this page

**Primary persona — Power user / institutional trader.**
A hedge-fund PM or sell-side analyst who has been using the platform for
weeks. They've configured 2–4 named workspaces, each tuned for one workflow
(morning brief, intraday trading, M&A research, portfolio review). They land
on `/workspace` first thing in the morning and stay here all day.

**Primary tasks (top 3).**
1. **Switch context in <1 second** — flip between "Morning Brief" and "Day
   Trading" workspaces via the tab strip or `Ctrl+1..Ctrl+9` hotkeys.
2. **Broadcast a symbol to every panel** — type `AAPL` in the workspace
   symbol bar, hit Enter, every chart/fundamentals/news panel reloads
   against AAPL.
3. **Resize panels in-place** — drag the splitter between Chart and News so
   Chart takes 70% of the row width during active trading; revert later.

**Secondary tasks.**
- Add/remove/rename workspaces.
- Add a new panel mid-session via the "Add panel" tray.
- Share a workspace config with a colleague via the Share dialog (URL
  encoding round-trip).
- Create a workspace from a 6-template starter set (Day Trader, Research,
  Swing Trader, News Junkie, Investor, Quad View).
- Pop a panel out into a separate window. (Reserved corner slot only — not
  shipped in v1.)

**Anti-patterns.**
- Centered hero illustrations or "Welcome to your workspace" callouts. The
  page is for daily users, not first-timers.
- Modal dialogs for workspace switching. The tab strip is the entire
  affordance.
- Loading spinners that block the whole grid. Each panel loads
  independently.
- Visible scrollbars on the grid itself. Only individual panels scroll.

---

### A.3 Backend data available

The Workspace page does **not call S9 directly**. It is a composition shell
whose panels are independent widgets, each of which makes its own S9 calls.
The page itself reads only from `localStorage` (via `WorkspaceContext`).

**Per-panel data sources (see `00-backend-data-inventory.md`).**

| Panel type | Primary S9 endpoint | Cache key | Comment |
|------------|---------------------|-----------|---------|
| `chart` | `/v1/ohlcv/{instrument_id}` | `qk.ohlcv_bars` | + `/v1/quotes/{id}` for live last price |
| `watchlist` | `/v1/watchlists/{id}/members` + `/v1/quotes/batch` | `qk.watchlist_members`, batched quote dedup | Refreshes on every quote tick |
| `screener` | `/v1/fundamentals/screen` | `qk.screener_results` | POST with full filter payload |
| `alerts` | `/v1/alerts/pending` | `qk.alerts_pending` | Same source as `/alerts` page |
| `fundamentals` | `/v1/instruments/{id}/page-bundle` | `qk.instrument_bundle` | Bundle covers overview + technicals |
| `news` | `/v1/news/relevant` or `/v1/news/entity/{id}` | `qk.news_relevant`, `qk.entity_news` | Falls back to relevant when no symbol bound |
| `graph` | `/v1/entities/{id}/graph` | `qk.entity_graph` | Cytoscape.js + COSE-Bilkent |
| `portfolio` | `/v1/portfolios/{id}/snapshot` | `qk.portfolio_snapshot` | Reuses Dashboard portfolio card data |
| `brief` | `/v1/briefings/morning` | `qk.brief_morning` | Same source as Dashboard |
| `chat` | `POST /v1/chat/threads`, SSE `/v1/chat/threads/{id}/stream` | `qk.chat_threads` | Real-time stream |

**Currently-displayed vs missing data.**

| Field | Currently rendered? | Plan |
|-------|---------------------|------|
| `WorkspaceConfig.name`, `rowSizes`, `panels[]` | YES (tabs + grid) | Keep |
| `WorkspaceSymbolContext.broadcastSymbol` | YES (symbol bar) | Keep |
| Per-panel data freshness timestamp | NO | **ADD** — panel footer 9px "RT 09:32:14 EODHD" line |
| Per-panel "linked color group" | YES (SymbolLinkColorPicker) | Keep |
| Sync-crosshair across chart panels | NO | **ADD** — emits via SymbolLinkingContext, opt-in workspace toggle |
| Synchronized time-range across chart panels | NO | **ADD** (deferred, v1.1) |
| Panel tear-off into new window | NO | Corner-slot reservation only |
| Tab-stacked panels (Mosaic-style) | NO | **DEFERRED** — design proposes the architecture (RowConfig may carry a TabbedPanelGroup); implementation v1.1 |

---

### A.4 Layout

**ASCII wireframe at 1440×900 — 2×2 Quad View template (default for new users).**

```
┌─ Workspace symbol bar — 28px ──────────────────────────────────────────────┐
│ SYMBOL [ AAPL    ▽][×]  Press Enter to broadcast to all panels    [LINK ●]│
├─ Workspace tab strip — 28px ───────────────────────────────────────────────┤
│ [Day Trading][Research][Portfolio][Morning Brief][+]            [Δ Share ⚙]│
├─ Utility row — 24px ───────────────────────────────────────────────────────┤
│                                            [⊕ Add panel][⊞ Template][🗗 Pop]│
├────────────────────────────────────────────────────────────────────────────┤
│ ┌── CHRT  AAPL · 1D ────────────────┬── NEWS  AAPL · 50 articles ────────┐ │
│ │ ╔══ Toolbar: [1D][5D][1M][3M][1Y] ║                                   │ │
│ │ ║ Indicators▽ Pop-out⤢ Pin● ×    ║ 09:31 Tim Cook: "We're investing  │ │
│ │ ╚══════════════════════════════════╝ deeply in generative…"            │ │
│ │  $234.12 +1.42 (+0.61%)              09:24 Goldman raises AAPL PT $260│ │
│ │  ┌─Candle area ~280px tall──────┐    09:18 Apple supplier Foxconn…    │ │
│ │  │                              │    09:12 Bloomberg: Vision Pro 2…   │ │
│ │  │                              │    08:55 Reuters: India iPhone…    │ │
│ │  │  /\        /\  /             │    08:41 Bloomberg: TSMC chip…     │ │
│ │  │ /  \  /\  /  \/              │    08:30 EU regulator opens…       │ │
│ │  │/    \/  \/                   │    08:17 Citi reiterates Buy…      │ │
│ │  └──────────────────────────────┘    08:02 Morning brief: Apple…     │ │
│ │  VOL ████ ▌▌▌▌ ▌▌▌▌                  07:48 BoA: AAPL Services beat…  │ │
│ │  ┌─ MA(50): 230.4   MA(200): 215.1   07:35 Bloomberg: Apple India…   │ │
│ │  └  RSI(14): 58.2   ATR(14): 3.21    07:21 WSJ: Apple TV+ to…        │ │
│ │  ════════════════════════════════    [▾ 40 more]                     │ │
│ │  RT 09:32:14  EODHD                                                  │ │
│ ├── SCRN  Tech mid-caps ───────────┼── ALRT  AAPL · 3 active ──────────┤ │
│ │  TICKER PX     %CHG MCAP  P/E      ● HIGH SIGNAL  Guidance raise     │ │
│ │  NVDA   882.40 +1.8 2.18T 71.2   ● HIGH GRAPH   Supplier change      │ │
│ │  AMD    167.21 -0.4 270B  44.1   ○ MED  CONTRA  PT disagreement       │ │
│ │  AVGO   1320.5 +2.1 614B  39.7      ────────────────────────────────  │ │
│ │  QCOM   164.40 +0.8 184B  18.6      MSFT alerts (2)                  │ │
│ │  TXN    178.12 +0.2 162B  31.0     ● HIGH SIGNAL  Earnings beat       │ │
│ │  KLAC   774.55 +1.4 103B  31.2     ○ LOW  USER   PT breach $440      │ │
│ │  LRCX   942.10 +0.7  99B  27.4      ────────────────────────────────  │ │
│ │  MU      99.32 -1.1 110B  17.3      GOOGL alerts (1)                 │ │
│ │  …                                  ● HIGH GRAPH   New competitor    │ │
│ │  ┌─ 12 results · row 1-8 of 12      ──────────────────────────────── │ │
│ │  └ Sort: MCAP↓  ⟳ 60s               [ACK selected] [Clear]            │ │
│ └─────────────────────────────────────┴──────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────┘
```

**Grid description.**
- Vertical structure: `Symbol bar (28) + Tab strip (28) + Utility row (24) +
  PanelGroup (rest)`. Total chrome above grid = **80px** in v1 (was 84px;
  one-off cleanup reduced utility row from 28 → 24).
- The PanelGroup is a `react-resizable-panels` v4 vertical Group containing
  row Groups. Each row is a horizontal Group containing Panels.
- Separators are **2px** (was 4px in legacy code) and use `bg-border` with
  no hover-glow. They show a `cursor-row-resize` / `cursor-col-resize`
  cursor and a 1px primary-yellow line on hover.
- Panel headers are 22px (matches data-row height). Panel content fills the
  remainder.
- Panel footer (data freshness line) is 18px, optional, rendered only when
  the panel widget exposes a `lastUpdatedAt` prop.

**Density target.**
At 1440×900 the Quad View template at default ratios shows:
- Chart panel: ~360 OHLC bars + last-price strip + indicator strip ≈ **45
  data cells visible**
- News panel: 12 article rows × 4 cells (time + source + title + entity
  badge) ≈ **48 cells**
- Screener panel: 8 rows × 6 columns ≈ **48 cells**
- Alerts panel: ~16 alert rows × 5 cells (sev dot + ticker + type + body +
  time) ≈ **80 cells**

**Total visible data cells above fold: ~220** in the default 2×2 layout.
Configurable layouts (1+2, 1+3, 2+2 wide chart) can push this past **300**.

---

### A.5 Component breakdown

| Component | File | Line budget | Props | Renders |
|-----------|------|-------------|-------|---------|
| `WorkspacePage` | `app/(app)/workspace/page.tsx` | ~80 | — | URL `?config=` import + page-level providers |
| `WorkspaceSymbolBar` | same file (extract → `components/workspace/WorkspaceSymbolBar.tsx`) | ~60 | — | Symbol input + clear + hint |
| `WorkspaceTabs` | `components/workspace/WorkspaceTabs.tsx` | existing | — | Tab strip + Add/Rename/Delete |
| `WorkspaceUtilityRow` | **NEW** `components/workspace/WorkspaceUtilityRow.tsx` | ~80 | `{ workspace: WorkspaceConfig, onShare, onTemplate, onAddPanel }` | Right-aligned cluster: Add panel, Template, Share, Pop-out (disabled), Sync-crosshair toggle |
| `WorkspaceGrid` | `components/workspace/WorkspaceGrid.tsx` | existing | `{ workspace }` | Vertical Group of row Groups |
| `WorkspacePanelContainer` | existing | — | `{ panel, onRemove, lastUpdatedAt? }` | Panel chrome: header (icon, type code, symbol, ×) + body + footer |
| `WorkspaceChartWidget` etc. (10 widgets) | `components/workspace/Workspace*Widget.tsx` | existing | type-specific | Per-panel content |
| `AddPanelTray` | existing inside `WorkspaceGrid.tsx` | — | `{ isOpen, onClose }` | HTML5 drag-source for 10 panel types |
| `ShareWorkspaceDialog`, `NewFromTemplateDialog` | existing | — | type-specific | Modals |
| `CrosshairSyncToggle` | **NEW** in `WorkspaceUtilityRow.tsx` | ~20 | `{ enabled, onToggle }` | Toggles a workspace-level boolean stored in `WorkspaceConfig.syncCrosshair` (additive field) |

**Reusable primitives.**
- All panel widgets reuse `TableRow22` (proposed shared row container with
  `h-[22px]`), `MetricCell11` (11px tabular-nums numeric), `SeverityDot`,
  `SourceTag`. These live in `components/data/` and are shared with
  `/dashboard`, `/screener`, `/alerts`.

**Additive changes to `WorkspaceConfig` type.**

```ts
export interface WorkspaceConfig {
  id: string;
  name: string;
  rows: WorkspaceRow[];
  rowSizes?: number[][];
  /** A.4 chart-sync. Default false. */
  syncCrosshair?: boolean;
  /** A.4 chart-sync. Default false. */
  syncTimeRange?: boolean;
}
```

These fields are **optional** and default-false, so v1 configs continue to
deserialize without migration. No new localStorage version bump.

---

### A.6 Visual spec (numerical)

**Heights.**
- Workspace symbol bar: `h-7` (28px)
- Tab strip: `h-7` (28px)
- Utility row: `h-6` (24px)
- Panel header: `h-[22px]`
- Panel footer (freshness line): `h-[18px]`, optional
- Separator (resize handle): 2px

**Padding.**
- Symbol bar, tab strip, utility row: `px-2` (8px)
- Panel content area: `p-1` (4px) for table-style widgets; `p-2` (8px) for
  card-style widgets (Brief, Chat). NEVER `p-4`.

**Typography.**
- Symbol bar label "SYMBOL" — `text-[10px] uppercase tracking-wider text-muted-foreground`
- Symbol bar input — `text-[11px] font-mono uppercase`
- Tab label — `text-[11px]`
- Utility row buttons — `text-[10px] uppercase`
- Panel header type code (CHRT, NEWS, FUND, ALRT, SCRN, GRPH, PORT, BRF,
  CHAT, WTCH) — `text-[10px] font-mono uppercase tracking-[0.08em] text-primary`
- Panel header symbol/secondary text — `text-[11px] text-foreground`
- Panel footer freshness — `text-[9px] font-mono tabular-nums text-muted-foreground`

**Colors.**
- Background canvas — `bg-background`
- Panel surface — `bg-card`
- Separator — `bg-border` idle, `bg-primary/40` hover, `bg-primary` active drag
- Active tab — bottom-border `border-primary` 2px, label `text-primary`
- Inactive tab — `text-muted-foreground`
- Linked-symbol color dot — uses existing 8-color SymbolLinking palette

**Animation.**
- Separator hover/drag color change: instant (no transition — terminal feel).
- Tab switch: no animation (panels appear immediately on tab change).
- Tray slide-in: `transition-transform duration-150 ease-out` (150ms — the
  one place a transition is OK because the tray is a chrome surface, not
  data).

---

### A.7 Interaction model

**Page-level hotkeys.**

| Key | Action | Notes |
|-----|--------|-------|
| `Ctrl+1` … `Ctrl+9` | Activate workspace at position N | Wraps via `WorkspaceContext.setActiveWorkspace` |
| `Ctrl+T` | New workspace | Opens `NewFromTemplateDialog` |
| `Ctrl+W` | Close active workspace | Confirm dialog if it's the last one (forbidden) |
| `Ctrl+Shift+T` | Reopen last-closed workspace | Reads a session-local "recent close" stack |
| `Ctrl+/` | Focus the workspace symbol bar | Mirrors Bloomberg's `?` security input |
| `Esc` (with focus in symbol bar) | Clear broadcast symbol | Existing behaviour, keep |

**Symbol bar interactions.**
- Type → uppercase as you go.
- Enter → commit broadcast.
- Esc → clear input + clear broadcast symbol.
- Click `×` → clear broadcast symbol (no input change).
- Down-arrow on input → reserved for future autocomplete (out of scope v1).

**Panel interactions.**
- Click panel header → focuses that panel (keyboard navigation enters it).
- Click `×` on header → removes the panel from the row; if it was the
  last panel in the row, removes the row.
- Drag separator → live resize (debounced 300ms to localStorage).
- Drag panel header → reorder within row (NEW — v1.1, out of scope v1).

**Loading state — per panel.**
Each panel renders its own skeleton (`Skeleton h-[22px]` × N). The grid
itself never blocks.

**Error state — per panel.**
Panel content area renders `<InlineError onRetry={refetch} />` — same
component used across `/dashboard`. The header chrome stays intact.

**Empty state.**
- **No workspaces at all**: render the inline string "No workspace
  active. Add a workspace via the tab strip." (Already implemented.)
- **Workspace with empty rows**: render a centered ghost button "Drop a
  panel here from the tray" — visible only when the tray is open.

---

### A.8 Data fetching

The Workspace page itself fetches nothing. Each panel widget owns its
TanStack Query usage. Key dedup across panels is critical:
- Two `chart` panels for the same symbol share `qk.ohlcv_bars(symbol,
  range)` — single in-flight request.
- Two `news` panels for the same entity_id share `qk.entity_news(id)`.
- Watchlist + portfolio panels both call `qk.quotes_batch(symbols)` — TanStack
  Query's structural sharing means a single network call.

**Proposed new query key.**

```ts
// lib/query/keys.ts — additive
workspace: {
  config: () => ["workspace", "config"] as const, // local-only, no fetch
},
```

`workspace.config` is a sentinel key used by tests to validate that no
network request was made to a `/v1/workspace` endpoint (the page is
localStorage-only by design).

**staleTime per panel widget.** (existing — not changed)
- chart: 30s (60s if range >= 1Y)
- watchlist: 5s
- screener: 60s
- alerts: 0 (always re-fetch on focus)
- fundamentals: 5 min
- news: 60s
- graph: 5 min
- portfolio: 30s
- brief: 5 min
- chat: streaming (no staleTime concept)

---

### A.9 Tradeoffs & decisions

**Decision 1: Add cross-panel chart sync as an opt-in toggle, not a default.**

*Alternatives considered.*
- (a) Always-on sync — the simplest mental model; matches TradingView.
- (b) Per-panel checkbox — every chart panel has its own "link to others"
  flag.
- (c) **Workspace-level toggle** (recommended).

*Why (c) wins.* Option (a) breaks workflows where a trader wants two charts
of different symbols at different time ranges visible simultaneously
(e.g. SPY 5m vs. AAPL 1D for relative strength). Option (b) introduces
per-panel UI clutter that is rarely used. The workspace-level toggle
matches the "all panels follow the broadcast symbol" mental model that
WorkspaceSymbolBar already established — sync is a workspace property, not
a panel property.

**Decision 2: Defer tab-stacked panels (Mosaic-style) to v1.1.**

*Alternatives considered.*
- (a) Ship now — Mosaic users will want this from day 1.
- (b) **Defer to v1.1** (recommended).

*Why (b) wins.* Tab-stacking requires changes to `WorkspaceRow.panels`
(must become `panels: WorkspacePanel | TabbedPanelGroup`) and to the URL
share token format. Both are forward-incompatible. PRD-0089's scope is
density + missing-data restoration, not new layout primitives.

**Decision 3: Keep the workspace storage local-only.**

*Alternatives considered.*
- (a) Persist to S1 for cross-device sync.
- (b) **Keep local** (recommended).

*Why (b) wins.* Workspace config is a deeply personal, high-frequency
write surface (every resize drag). Pushing to S1 introduces network
latency on every resize and a new schema (`user_workspaces` table) for
arguably-private layout data. Share-via-URL already covers the "I want to
recreate this on another device" case.

---

### A.10 Open questions

1. **Sync-crosshair scope** — should the crosshair sync extend to news/event
   timestamps inside the news panel (highlight news rows within ±5min of the
   crosshair)? Recommendation: yes, but as a v1.1 follow-on.
2. **Panel "pin" affordance** — Bloomberg lets you pin one panel so it
   doesn't change when the workspace symbol changes. Worth shipping in v1?
3. **Max workspace count** — currently unlimited. Tab strip overflow handling
   (horizontal scroll? `[…]` dropdown?) needs a decision when N > 8.

---

## PAGE B — Prediction Markets (`/prediction-markets`)

### B.1 Competitor research summary

**Polymarket — the canonical UI.**
The Polymarket homepage is itself the design reference. Key patterns:
- **Card grid (not table) for top markets**. Each card shows: question
  title (max 2 lines), YES probability as a large %, a sparkline of the
  YES probability over the last 7 days, total volume, days to resolution,
  and the top 4 outcome bars (for multi-outcome markets).
- **Category pills above the grid** — Politics, Crypto, Sports, Economy,
  Tech, Climate, Pop Culture. Each shows a count badge.
- **Search bar with autocomplete** — symbol-like instant filter.
- **Volume tier badges** — markets with $1M+ volume get a "Top" badge.
- **"Resolves in" countdown** — `2d 14h` styled as a clock.

Worldview today shows a 4-column table with title + probability bar +
24h volume + days-to-close. Density is reasonable (28px rows). What we
will steal beyond the current state:
- **Sparkline of YES probability over the last 7 days** — inline 60×16px
  sparkline in the probability column. This is the single largest gap vs
  Polymarket.
- **NO probability column** — currently shown as `100 - YES`, but for
  multi-outcome markets (and even binary ones), explicitly showing both
  prices makes the row more scannable.
- **Bid/ask spread strip** — Polymarket exposes `best_bid` / `best_ask` /
  `liquidity`. Worldview's `PredictionMarket` type today exposes
  `volume_usd` but not the order-book values. **This is a backend gap** —
  the design proposes adding `best_bid`, `best_ask`, `bid_size`,
  `ask_size`, and `last_trade_price` to the gateway response. (Backed by
  the existing `market.prediction.snapshot` Avro schema — see Open
  Questions.)

**Kalshi.**
Kalshi's interface differs from Polymarket in two ways:
- **Two-column outcome layout** ("Yes 67¢" / "No 33¢" as side-by-side
  buttons that double as buy CTAs). Worldview is read-only, so we adapt
  this into two-column **price chips** with hover-to-show
  best-bid/best-ask.
- **Category iconography** — Kalshi uses 16px sector icons next to each
  pill (a Capitol dome for politics, a Bitcoin glyph for crypto). Pull
  these into Worldview from Lucide.

**PredictIt and Augur.**
- PredictIt's history chart on each market detail view is informative:
  a 30-day intraday line of YES price. Worldview already exposes
  `/v1/signals/prediction-markets/{id}/history` but **does not render
  the chart anywhere**. Section B.4 puts it in the right-side detail
  drawer.
- Augur (legacy decentralized) influenced Polymarket's resolution-source
  disclosure. We add a "Source" line per market: `Polymarket · Resolution:
  AP Race Call` so the user knows who decides the outcome.

**TradingView Economic Calendar (similar density pattern).**
The TradingView Economic Calendar packs 40+ rows in a single viewport using
22px row heights, country flag icons, color-coded impact dots, and
inline `actual / forecast / previous` columns. We mirror this row pattern
for prediction markets — same row height, same 11px mono numerics.

---

### B.2 User intent for this page

**Primary persona — macro discretionary trader / event-driven analyst.**
A buy-side analyst who treats Polymarket prices as an alternative signal
("what does the crowd price for a Fed cut in March?") and cross-references
them against their cash-equity positions. They are not trading prediction
markets directly (Worldview is read-only); they're using the prices as a
probability oracle.

**Primary tasks (top 3).**
1. **Scan 30+ active markets at once** to see where the crowd has shifted
   probability since yesterday (sparklines).
2. **Filter to a category** (Macro, Crypto, Politics) and search by free
   text ("Fed rate", "BTC 100k").
3. **Drill into a single market** to see the 30-day probability history
   and the resolution criteria.

**Secondary tasks.**
- Pin markets to a workspace alerts panel (USER_RULE on the underlying
  question: "alert me if `Fed-cuts-March-2026` crosses 50%").
- Open the market on Polymarket.com to read details (out-of-app link).
- See the source — Polymarket vs Kalshi.

**Anti-patterns.**
- Big card grid that fits 8 markets per viewport. Polymarket's hero grid
  is great for first-time users but wasteful for daily analyst use.
- Modal pop-ups for market detail. Use a right-side drawer so the list
  stays visible.
- "Trade now" CTAs. Worldview is read-only; the row title-click goes to
  Polymarket.

---

### B.3 Backend data available

From `00-backend-data-inventory.md` section 1.10:

| Endpoint | Returns | UI usage |
|----------|---------|----------|
| `GET /v1/signals/prediction-markets?status=open&limit=200&category=...` | `{markets: [...], total}` | Main list |
| `GET /v1/signals/prediction-markets/{id}` | Single market detail | Drawer header |
| `GET /v1/signals/prediction-markets/{id}/history` | `{history: [{timestamp, yes_price, no_price, volume}]}` | Drawer chart |
| `GET /v1/signals/prediction-markets/categories` | `{categories: [{name, count}]}` | Category pills with badges |

**`PredictionMarket` fields exposed (frontend type).**

| Field | Currently rendered? | New plan |
|-------|---------------------|----------|
| `market_id` | NO (key only) | Keep as key |
| `title` | YES (truncated 1 line) | Keep, but allow 2-line wrap on detail drawer |
| `description` | NO | **ADD** to drawer (full markdown-stripped text) |
| `yes_probability` | YES (bar + %) | Keep + add sparkline |
| `no_probability` | NO (derived) | **ADD** explicit chip |
| `volume_usd` | YES | Keep |
| `status` | NO (always open in query) | **ADD** badge in drawer header |
| `resolution_date` | YES (days-to-close) | Keep + add full date in drawer |
| `entity_ids` | NO | **ADD** entity-link chips in drawer ("Linked to: AAPL, NVDA") |
| `tickers` | NO | **ADD** ticker badges inline in row when ≤ 2 tickers |
| `source` (polymarket/kalshi) | NO | **ADD** as 16×16 source icon prefix on row |
| `url` / `market_slug` | YES (row click) | Keep |
| `category` | YES (pill filter + row text) | Keep |
| `updated_at` | NO | **ADD** to drawer as `Last priced 14:32 EDT` |

**Backend gaps proposed.**
- `best_bid`, `best_ask`, `bid_size`, `ask_size`, `last_trade_price` — already
  present in `market.prediction.snapshot.v1` Avro schema (S4 → S3) but not
  surfaced through the S9 gateway. Section B.10 logs this as the only true
  blocker for the design.

---

### B.4 Layout

**ASCII wireframe at 1440×900 — list + drawer (drawer closed, list view).**

```
┌─ Page header — 36px ───────────────────────────────────────────────────────┐
│ 📈 PREDICTION MARKETS                                  ▢ 287 open  ⟳ 30s  │
│ [All 287][Politics 92][Macro 64][Crypto 41][Sports 38][Tech 27][Other 25]  │
│                                                  🔍 [ Search markets…    ] │
├─ Column header — 20px ─────────────────────────────────────────────────────┤
│ S  QUESTION                                  YES%   SPARK 7D    NO%  VOL  CLOSES │
├─ Row 1 — 22px ─────────────────────────────────────────────────────────────┤
│ ▣ Will Fed cut rates by 25bp in March 2026?    67%  ▁▂▃▅▆▇▇▆   33%  $4.2M  14d │
│ ▣ Will BTC reach $100K by EOY 2026?            42%  ▆▅▄▃▂▁▂▃   58%  $2.1M  221d│
│ ◇ Will AAPL exceed $300 by Dec 2026?           28%  ▂▂▃▃▂▂▃▃   72%  $890K  221d│
│ ▣ Will NVDA hit $1500 by Jun 2026?             19%  ▅▄▃▂▂▁▁    81%  $1.4M  53d │
│ ▣ Will SPX close above 6000 in 2026?           61%  ▃▄▅▆▆▇▇    39%  $3.7M  221d│
│ ▣ Will FOMC cut in May 2026?                   54%  ▄▅▅▄▄▃▄    46%  $1.8M  72d │
│ ▣ Will US recession in 2026?                   31%  ▆▅▄▃▃▂▂    69%  $5.6M  221d│
│ ▣ Will CPI YoY > 3% in Apr 2026?               24%  ▅▄▃▂▂▁▁    76%  $620K  43d │
│ ▣ Will Powell still be Chair on Dec 31?        93%  ▇▇▇▇▇▇▇     7%  $410K  221d│
│ ▣ Will EUR/USD < 1.05 by EOY?                  56%  ▃▄▅▅▆▆▆    44%  $1.1M  221d│
│ ▣ Will GDP Q1 print > 2.0%?                    48%  ▄▄▅▅▄▄▄    52%  $720K  37d │
│ ▣ Will UNRATE > 4.5% by Mar 2026?              35%  ▅▄▃▃▂▂▂    65%  $890K  35d │
│ ▣ Will Saudi cut oil output further in Apr?    41%  ▄▄▅▅▄▃▃    59%  $1.3M  61d │
│ ▣ Will ECB cut in Mar 2026?                    72%  ▃▄▅▆▆▇▇    28%  $980K  18d │
│ ▣ Will Trump pardon Hunter Biden?              19%  ▅▄▃▂▂▂▁    81%  $2.4M  221d│
│ ▣ Will Tesla deliver >2M cars in 2026?         44%  ▄▄▄▃▃▄▄    56%  $1.6M  221d│
│ ▣ Will Apple announce car program revival?      8%  ▂▁▁▁▁▁▁    92%  $230K  221d│
│ ▣ Will OPEN.AI IPO by EOY 2026?                23%  ▄▃▃▂▂▂▂    77%  $1.9M  221d│
│ ▣ Will Ethereum surpass $5K by EOY?            38%  ▅▄▄▃▃▂▃    62%  $1.7M  221d│
│ ▣ Will any FAANG split stock in 2026?          17%  ▂▂▃▂▂▂▂    83%  $290K  221d│
│ ▣ Will the next iPhone be foldable?             6%  ▁▁▁▁▂▂▁    94%  $180K  365d│
│ ▣ Will US enter recession before Jul?          22%  ▄▃▃▂▂▂▂    78%  $1.5M  158d│
│ ▣ Will Russia-Ukraine ceasefire by Jun?        34%  ▃▄▄▅▅▄▄    66%  $2.7M  150d│
│ ▣ Will an AI model surpass GPT-5 by Q2?        29%  ▄▄▃▃▃▂▃    71%  $510K  120d│
│ ▣ Will the Super Bowl winner be NFC?           54%  ━━━━━━━    46%  $4.1M  20d │
│ ▣ Will Trump visit China in 2026?              31%  ▃▃▄▄▄▃▃    69%  $390K  221d│
│ ▣ Will any G7 leader resign in Q1?             19%  ▂▂▃▃▂▂▁    81%  $280K  43d │
│ ▣ Will gold hit $3000/oz in 2026?              26%  ▃▃▄▄▃▃▃    74%  $670K  221d│
│ ▣ Will US 10Y yield > 5% in 2026?              33%  ▄▅▅▄▄▃▃    67%  $480K  221d│
│ ▣ Will Fed unwind QT before EOY?               46%  ▃▄▅▆▆▅▄    54%  $560K  221d│
│ ▣ … 257 more  [Scroll to load]                                                 │
├─ Footer — 22px ─────────────────────────────────────────────────────────────┤
│ Showing 30 of 287 · Source: Polymarket Gamma API · Last sync 14:32:08 EDT     │
└────────────────────────────────────────────────────────────────────────────┘
```

**ASCII wireframe — row clicked, right-side drawer open (40% width).**

```
┌─ Page header (unchanged) ──────────────────────────────────────────────────┐
├─ Column header (unchanged) ────────────────────────────────────────────────┤
│ S  QUESTION                                  YES%   SPARK 7D    NO%  VOL   │
│ ▣ Will Fed cut rates by 25bp in March 2026?    67%  ▁▂▃▅▆▇▇▆   33%  $4.2M  │
│ ▣ Will BTC reach $100K by EOY 2026?     ◀ SELECTED — drawer open ▶          │
│ ◇ Will AAPL exceed $300 by Dec 2026?            28%  ▂▂▃▃▂▂▃▃   72%  $890K │
│ ▣ Will NVDA hit $1500 by Jun 2026?              19%  ▅▄▃▂▂▁▁    81%  $1.4M │
│ … (list continues, narrower)              │ DRAWER 576px wide               │
│                                           │ ┌───────────────────────────┐ │
│                                           │ │ WILL BTC REACH $100K…    × │ │
│                                           │ │ Polymarket · Open · 221d   │ │
│                                           │ ├───────────────────────────┤ │
│                                           │ │ YES  42¢                  │ │
│                                           │ │ NO   58¢                  │ │
│                                           │ │ Bid 41 / Ask 43 · Liq $2M │ │
│                                           │ ├─ 30-day history ──────────┤ │
│                                           │ │  ╱╲                        │ │
│                                           │ │ ╱  ╲    ╱╲                 │ │
│                                           │ │     ╲__╱  ╲___             │ │
│                                           │ │                            │ │
│                                           │ ├─ Linked entities ─────────┤ │
│                                           │ │ ▣ BTC  ▣ MSTR  ▣ COIN     │ │
│                                           │ ├─ Resolution ──────────────┤ │
│                                           │ │ Resolves Dec 31 2026.     │ │
│                                           │ │ Source: CoinGecko BTC USD │ │
│                                           │ │ daily close ≥ $100,000.    │ │
│                                           │ ├─ Description ─────────────┤ │
│                                           │ │ A market on the price of  │ │
│                                           │ │ bitcoin… (truncated 4 ln) │ │
│                                           │ ├───────────────────────────┤ │
│                                           │ │ [⇗ View on Polymarket]    │ │
│                                           │ │ [🔔 Alert me at 50%]       │ │
│                                           │ └───────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────┘
```

**Grid description.**
- 7-column layout when no drawer:
  `[source 20px][question 1fr][YES% 60px][spark 80px][NO% 60px][vol 80px][closes 60px]`
- When drawer open: list reflows to the left ~860px; drawer is 576px fixed.
- Sticky header (column row + category pills) at viewport top.
- Infinite scroll: load 30 rows at a time; the row 30 has a sentinel that
  triggers the next 30.

**Density target.**
- Default list view: **30 markets visible above 900px fold**, each row is
  22px = 660px of rows, +56px chrome (header+columns) = 716px. Headroom for
  the page footer.
- Each row has 7 cells. **210 data cells per viewport** in the default
  layout, before counting the sparkline (which is itself 7 data points).
- With drawer open: 18 list rows + the full drawer (≈ 25 metric cells in the
  drawer). Still ~150 cells visible.

---

### B.5 Component breakdown

| Component | File | Line budget | Props | Renders |
|-----------|------|-------------|-------|---------|
| `PredictionMarketsPage` | `app/(app)/prediction-markets/page.tsx` | ~80 (slimmer than today's 300) | — | Layout + provider |
| `PredictionMarketsHeader` | **NEW** `components/predictions/PredictionMarketsHeader.tsx` | ~80 | `{ total, categories, activeCategory, onCategoryChange, search, onSearchChange }` | Title + pill row + search input |
| `PredictionMarketsTable` | **NEW** `components/predictions/PredictionMarketsTable.tsx` | ~120 | `{ markets, selectedId, onSelect, isLoading }` | Sticky column header + virtualised rows |
| `MarketRow` | **NEW** `components/predictions/MarketRow.tsx` | ~80 | `{ market, selected, onSelect }` | 22px row with 7 cells |
| `ProbabilitySparkline` | **NEW** `components/predictions/ProbabilitySparkline.tsx` | ~50 | `{ data: number[], width=60, height=14 }` | Inline SVG sparkline of YES probability |
| `PredictionMarketDrawer` | **NEW** `components/predictions/PredictionMarketDrawer.tsx` | ~150 | `{ marketId, open, onClose }` | Right-side sheet, fetches `/v1/signals/prediction-markets/{id}` + `/history` |
| `MarketHistoryChart` | **NEW** `components/predictions/MarketHistoryChart.tsx` | ~100 | `{ history }` | 30-day YES price line using existing recharts utility |
| `MarketEntityChips` | **NEW** `components/predictions/MarketEntityChips.tsx` | ~30 | `{ tickers, entityIds }` | Linked-entity badges, click → `/instruments/{id}` |
| `SourceIcon` | reusable `components/data/SourceIcon.tsx` | ~20 | `{ source: "polymarket"\|"kalshi" }` | 16×16 brand glyph |

**Reusable primitives leveraged.**
- `TableRow22`, `MetricCell11`, `Sparkline` (proposed shared in PRD-0089
  per the global doc) — shared with screener / dashboard.

**Sparkline data sourcing.**
- Per-row sparkline requires the last 7 days of `yes_price`. The list
  endpoint does not expose history. **Three options:**
  1. Add `recent_yes_history: number[7]` to the list response (best;
     cheap server-side join).
  2. Fetch `/history?days=7` per market on intersection-observer
     (bad — 200 requests).
  3. Add a batched `POST /v1/signals/prediction-markets/history-batch`
     endpoint accepting up to 200 market_ids.

   **Recommendation:** (1) on the list endpoint with a 7-element float array.
   Section B.10 logs this as a small backend ask.

---

### B.6 Visual spec (numerical)

**Heights.**
- Page header: 36px (24 title + 12 padding)
- Category pill row: 22px, integrated into header — `h-6`
- Column header row: 20px
- Market row: 22px
- Drawer header: 36px
- Drawer section headers: 18px

**Padding.**
- Header `px-2 py-1.5`
- Row `px-2`
- Drawer body `px-3`

**Typography.**
- Page title — `text-[11px] font-medium uppercase tracking-[0.1em]`
- Category pill — `text-[10px] uppercase` (was `text-[9px]`; bumped for
  legibility per the global density tokens)
- Column header — `text-[9px] uppercase tracking-wider text-muted-foreground`
- Row question — `text-[11px] text-foreground` (1-line truncate)
- Row numerics (YES%, NO%, VOL, CLOSES) — `text-[11px] font-mono tabular-nums`
- Sparkline — no text, SVG line stroke 1px
- Drawer YES/NO chips — `text-[14px] font-mono tabular-nums` (hero numbers)
- Drawer body description — `text-[11px] text-muted-foreground leading-snug`

**Colors.**
- Source icon background — none (icon glyph only)
- YES% color — `text-positive` when ≥ 65%, `text-warning` 35–64%, `text-negative` < 35%
- NO% color — symmetric inverse of YES color
- Sparkline stroke — `stroke-primary/70`
- Selected row — `bg-primary/5` and a 2px left border `border-l-primary`
- Drawer overlay — none (drawer is solid `bg-card`, sits beside list)

**Sparkline.**
- 60×14px SVG.
- 7 line segments connecting 7 data points.
- Y-axis auto-scaled to the row's `[min(yes_history) - 5pp, max + 5pp]`.
- No axes, no labels.

---

### B.7 Interaction model

**Hotkeys.**

| Key | Action |
|-----|--------|
| `/` | Focus search input |
| `1`..`7` | Activate category pill at position N |
| `Esc` (with drawer open) | Close drawer |
| `↓` / `↑` (with row focused) | Navigate rows |
| `Enter` (with row focused) | Open drawer for that row |
| `o` (with row focused) | Open the market URL in a new tab |

**Hover behaviour.**
- Row hover → `bg-card/60`.
- Sparkline hover → no tooltip (intentional; the drawer is the place for
  precise values).
- Source icon hover → tooltip `Polymarket` / `Kalshi`.

**Click handlers.**
- Click row → open drawer (replaces today's "open Polymarket in new tab" —
  matches user intent of "drill in").
- Click external-link icon on row → keep the old behaviour: open
  `polymarket.com/event/{slug}` (or fallback search URL).
- Click drawer's "View on Polymarket" → external link.
- Click drawer's "Alert me at 50%" → opens `AlertRuleBuilder` pre-populated
  with `market_id` and threshold 0.5.

**Loading state.**
- List skeleton — 14 rows of `Skeleton h-[22px] w-full`.
- Drawer skeleton — `Skeleton`s for title, two big chips, chart area, and
  description.

**Error state.**
- List error — full-page inline card `Failed to load prediction markets`
  with retry button. Mirrors existing behaviour.
- Drawer error — drawer body shows inline error; the list stays usable.

**Empty state.**
- No markets at all — `No prediction markets available. Run \`make seed\`
  to populate Polymarket data.` (existing copy, keep).
- Filtered empty — `No markets match your filters` (existing, keep).

---

### B.8 Data fetching

**Proposed new query keys.**

```ts
// lib/query/keys.ts — additive
predictions: {
  list: (params?: { category?: string; limit?: number; status?: string }) =>
    params
      ? (["predictions", "list", params] as const)
      : (["predictions", "list"] as const),
  detail: (id: string) => ["predictions", "detail", id] as const,
  history: (id: string, days: number) =>
    ["predictions", "history", id, days] as const,
  categories: () => ["predictions", "categories"] as const,
},
```

These replace the current flat `["prediction-markets-page"]` key and the
existing `qk.dashboard.predictionMarkets` (which the Dashboard widget uses).

**staleTime.**
- `predictions.list`: 60s (prices move, but the table view tolerates 1-min lag)
- `predictions.detail`: 15s (drawer is the "active research" surface)
- `predictions.history`: 5 min (history is stable)
- `predictions.categories`: 60s (rarely changes)

**Dedup opportunities.**
- The dashboard widget (`qk.dashboard.predictionMarkets`) and this page's
  `predictions.list` query the same endpoint with different `limit`. If the
  dashboard uses `limit=10` and this page uses `limit=200`, they cannot
  share cache. Recommendation: dashboard switches to a `select` on the
  larger list (TanStack Query's `select` slices the cached array without
  re-fetching).

---

### B.9 Tradeoffs & decisions

**Decision 1: Right-side drawer (not full-page detail route).**

*Alternatives considered.*
- (a) Push to `/prediction-markets/[id]` — gives a deep-link URL.
- (b) **Right-side drawer with `?selected={id}` in URL** (recommended).
- (c) Modal dialog.

*Why (b) wins.* Maintains the list context. Mirrors the Alerts page
pattern (PLAN-0048 Wave B-3 `?selected={id}`). Drawer is dismissible with
Esc and keyboard-navigable. Deep-linkable via the URL param.

**Decision 2: Sparkline embedded inline, not on hover.**

*Alternatives considered.*
- (a) Always-visible inline sparkline (recommended).
- (b) Hover-to-show sparkline.

*Why (a) wins.* The whole reason an analyst lands here is to scan for
"who moved today". A hover sparkline forces 30 mouse-hovers per scan — a
20× density loss. The 60px-wide inline sparkline costs 60 columns but
pays back the moment the user spots an interesting line shape.

**Decision 3: Read-only (no trade CTAs).**

*Alternatives considered.*
- (a) Embed buy/sell buttons that deep-link to Polymarket order entry.
- (b) **Pure read-only with external link out** (recommended).

*Why (b) wins.* Worldview is a data and intelligence platform, not a
brokerage. Embedding Polymarket order-entry CTAs (a) blurs the boundary
and (b) introduces regulatory exposure (US prediction-market access
restrictions). The external link discharges that concern.

---

### B.10 Open questions

1. **Backend additions to the list response.**
   - Add `best_bid`, `best_ask`, `bid_size`, `ask_size`, `last_trade_price`
     (already in the `market.prediction.snapshot` topic; not exposed in
     S9). Required for the drawer's bid/ask chip — current design degrades
     gracefully without it (hides the chip).
   - Add `recent_yes_history: float[7]` per row for the inline sparkline.
     Without it, the design must either omit sparklines (degraded) or
     fire 30 history requests on render (unacceptable). **Recommended:
     ship this in the same wave as the page.**
2. **Multi-outcome market support.** Currently every market in the system
   is binary (YES/NO). Polymarket also has multi-outcome (e.g. "Which
   party wins Senate?"). The schema has room (`outcomes: List[Outcome]`)
   but adapter today flattens to YES/NO. Out of scope for PRD-0089 v1.
3. **Kalshi adapter status.** `source` enum already lists Kalshi but no
   adapter is shipped. Design assumes Kalshi rows render identically when
   they arrive.

---

## PAGE C — Alerts (`/alerts`)

### C.1 Competitor research summary

**Bloomberg ALRT — the institutional gold standard.**
Bloomberg's `ALRT` function ("Alert Manager") packs the maximum number of
unacknowledged signals into a single screen:
- **No tabs at the top level.** Every alert — pending, acked, snoozed — is
  in one table; status is a single character column (`P`, `A`, `S`).
- **Row height: 18-20px.** Bloomberg's row is even tighter than Worldview's
  current 22px.
- **8-9 columns per row**: severity, time (HH:MM:SS), security ticker,
  alert code, condition text, current value vs trigger, channel
  (popup/email/SMS), ack/snooze buttons.
- **Severity by character + color**: `!` red for critical, `*` yellow for
  high, no glyph for medium/low; the leading character is uppercase mono.
- **Inline "current value"**: e.g. `AAPL last 234.12 vs trigger 230.00`.
  This is the single biggest missing element in Worldview's current
  alerts list.
- **`AAA` shortcut**: acknowledge all alerts of the highest active
  severity. Worldview today has "ACK ALL" per severity group — we keep
  that and add `Shift+A` for ack-all-critical.

**TradingView alerts panel.**
TradingView's alerts panel is more consumer-friendly than Bloomberg's but
still designed for traders:
- Filterable by status (Active / Triggered / Stopped) — Worldview's
  Active / Snoozed / Acknowledged / History maps 1:1.
- Sortable columns — time, ticker, condition.
- **"Trigger value" history line**: when an alert fires, the table shows
  `AAPL crossed 234.12 → 230.00` so the user sees what changed. Steal.
- **Audio cues per severity** — out of scope for v1 (no audio system).

**IBKR alerts.**
IBKR's alerts table has one striking pattern: **double-row alerts** where
the second sub-row shows the alert's payload (e.g. `Earnings beat: actual
$2.18 vs est $2.05, surprise +6.3%`). The second row is rendered at 50%
opacity and 9px text. Worldview's `payload` field is rich but unused on
the list — we adopt this pattern as an opt-in "Expand all" toggle.

**Where Worldview already wins.**
- Severity grouping with sticky group headers (Bloomberg flattens; we group).
- Bulk-select toolbar with `ACK Selected` (Gmail-style; Bloomberg has
  `ACK ALL` per group but not arbitrary selection).
- Categorised History tab with full filter UI (`AlertHistoryTab`).

---

### C.2 User intent for this page

**Primary persona — Trader on the trigger.**
A trader who has signals running on 20+ securities + 5+ user rules. They
get pings throughout the day (WebSocket → toast → AlertBell badge). When
something significant happens, they click the bell and land here. They
need to triage 50 alerts in under 60 seconds.

**Primary tasks (top 3).**
1. **Scan 50+ pending alerts at once** to find the 2-3 that matter today.
2. **Acknowledge the noise** (low-severity / already-known) via bulk-select
   in seconds.
3. **Drill into the survivors** — open the AlertDetailSheet, read the
   payload, decide whether to act.

**Secondary tasks.**
- Snooze an alert until end-of-day, 4h, custom datetime.
- Create a new alert rule via `AlertRuleBuilder`.
- Manage existing rules (Rule Manager).
- Filter History by date range, severity, entity.
- Toggle the News Feed / Top Today tabs to get context for ongoing alerts.

**Anti-patterns.**
- Toast-spam: the page is the calmly-organised home; toasts are for the
  3-second peripheral notification.
- Hiding payload behind multiple clicks. The detail sheet must reveal the
  full payload immediately.
- "Mark all as read" — Worldview's domain is signals, not email; ack is
  a deliberate action per alert (or per severity group), not a casual
  mass-bin.

---

### C.3 Backend data available

From `00-backend-data-inventory.md` section 1.8 + the alert service doc:

| Endpoint | Returns | UI usage |
|----------|---------|----------|
| `GET /v1/alerts/pending?limit=200&min_severity=low` | `{alerts: [...], total, limit, offset}` | Active list |
| `GET /v1/alerts/history?status=...&from=&to=&severity=...` | Same shape + `has_more` | Snoozed / Ack'd / History tabs |
| `PATCH /v1/alerts/{id}/acknowledge` | (200) | ACK button |
| `DELETE /v1/alerts/{id}/ack` | (204) | Per-user dismiss |
| `PATCH /v1/alerts/{id}/snooze` body `{until}` | (200) | Snooze button |
| `WS /api/v1/alerts/stream` | `{alert_id, entity_id, alert_type, severity, created_at}` | Live push (already wired via `AlertBell`) |
| `GET /v1/email/preferences` / `PUT` | `{enabled, send_day_of_week, send_hour_utc, timezone}` | `NotificationPreferencesDialog` |

**Alert fields exposed.**

| Field | Currently rendered? | New plan |
|-------|---------------------|----------|
| `alert_id` | NO (key only) | Keep as key |
| `entity_id` | NO | **ADD** entity link in detail sheet |
| `ticker` | YES (40px col) | Keep, bump to 56px for `XXXX.US` longer tickers |
| `alert_type` | YES (text) | Keep but use a 4-char code: `SIGN`, `GRPH`, `CONT`, `USER` |
| `severity` | YES (dot) | Keep dot + add character code `!`, `*` |
| `title` | YES (body fallback) | Use as primary text when present |
| `body` | YES (fallback) | Keep |
| `entity_name` | NO | **ADD** secondary text below ticker (e.g. `AAPL` over `Apple Inc.`) |
| `signal_label` | YES (fallback) | Keep |
| `payload` | YES (in detail sheet only) | **ADD** inline payload row (collapsible "Expand all" toggle, IBKR-style) |
| `metadata` | NO | Detail sheet only |
| `created_at` | YES (relative time) | Keep + show absolute time on hover |
| `acknowledged_at` | NO | **ADD** to detail sheet |
| `snooze_until` | NO | **ADD** as inline label on row when present (`Snoozed → 16:00`) |
| `ack_note` | NO | **ADD** to detail sheet (text input on ACK) |

**Trigger value (proposed addition — see C.10).**
Bloomberg's killer feature is the `current vs trigger` value on the row.
For `USER_RULE` alerts this is straightforward (`payload.trigger_value` +
`payload.current_value`). For `SIGNAL` alerts, the trigger is implicit
(the signal label). Recommend the backend add `display_trigger: {label,
current_value, threshold_value}` to the alert payload — graceful render
when absent.

---

### C.4 Layout

**ASCII wireframe at 1440×900 — Active tab, default 50 alerts visible.**

```
┌─ Page header — 28px ───────────────────────────────────────────────────────┐
│ 🔔 ALERTS & NEWS                  [⚙ Prefs][⊞ Rules (12)][＋ Create Rule] │
├─ Tab strip — 32px ─────────────────────────────────────────────────────────┤
│ [Alerts][News Feed][Top Today]                                              │
├─ Sub-tab strip — 28px ─────────────────────────────────────────────────────┤
│ [Active 47][Snoozed 4][Acknowledged][History]                               │
├─ Bulk toolbar — 28px (only when N≥1 selected) ─────────────────────────────┤
│ ☑ 3 selected     [ACK Selected]  [Snooze 1h ▾]  [Clear]                    │
├─ Severity group header — 24px ─────────────────────────────────────────────┤
│ ● CRITICAL (4)                                              ACK ALL         │
├─ Alert row — 22px ─────────────────────────────────────────────────────────┤
│ ☐ ! AAPL  Apple Inc.    SIGN  Guidance raise — Q1 EPS to $2.50 vs $2.10    14:32  [ACK ▾]│
│ ☐ ! NVDA  NVIDIA Corp.  GRPH  Major customer signed: Oracle $40B            14:18  [ACK ▾]│
│ ☐ ! TSLA  Tesla Inc.    SIGN  Production halt — Berlin gigafactory          13:54  [ACK ▾]│
│ ☐ ! MSFT  Microsoft     CONT  Analyst disagreement on Azure margin          12:30  [ACK ▾]│
├─ Severity group header — 24px ─────────────────────────────────────────────┤
│ ● HIGH (15)                                                 ACK ALL         │
├─ Alert rows — 22px each ───────────────────────────────────────────────────┤
│ ☐ * GOOG  Alphabet      SIGN  EPS beat +7% — $2.35 vs $2.20                 14:12  [ACK ▾]│
│ ☐ * AMZN  Amazon        SIGN  AWS reaccel +18% QoQ                          13:55  [ACK ▾]│
│ ☐ * META  Meta          GRPH  Apple acquired competitor                     13:41  [ACK ▾]│
│ ☐ * SPY   S&P 500 ETF   SIGN  Volume spike +180% vs ADV                     13:28  [ACK ▾]│
│ ☐ * NFLX  Netflix       SIGN  Subscriber count +8M vs +5M est               13:14  [ACK ▾]│
│ ☐ * SHOP  Shopify       GRPH  Major partnership — Stripe expand             12:55  [ACK ▾]│
│ ☐ * ORCL  Oracle        SIGN  $40B 5-yr contract signed with OpenAI         12:30  [ACK ▾]│
│ ☐ * AVGO  Broadcom      SIGN  Guidance raise — Q2 rev $14.2B vs $13.5B      12:11  [ACK ▾]│
│ ☐ * ASML  ASML          SIGN  Major orders from TSMC — €12B                 11:48  [ACK ▾]│
│ ☐ * COST  Costco        USER  P/E breached 50× — rule "high-PE"             11:31  [ACK ▾]│
│ ☐ * UNH   UnitedHealth  CONT  Analyst PT disagreement                       11:14  [ACK ▾]│
│ ☐ * NVDA  NVIDIA        SIGN  Insider sell — Huang $300M                    10:55  [ACK ▾]│
│ ☐ * JPM   JPMorgan      SIGN  NIM guidance cut                              10:31  [ACK ▾]│
│ ☐ * V     Visa          SIGN  Transaction vol -3% YoY                       10:12  [ACK ▾]│
│ ☐ * MA    Mastercard    SIGN  Same as V (correlation note)                  10:11  [ACK ▾]│
├─ Severity group header — 24px ─────────────────────────────────────────────┤
│ ● MEDIUM (18)                                              ACK ALL          │
├─ Alert rows ───────────────────────────────────────────────────────────────┤
│ ☐ · AAPL  Apple         SIGN  Volume +40% vs 5d avg                         10:08  [ACK ▾]│
│ ☐ · MSFT  Microsoft     USER  PT breached $440 — rule "MSFT-440"            10:02  [ACK ▾]│
│ ☐ · GOOG  Alphabet      SIGN  Sentiment shift — neutral→positive            09:55  [ACK ▾]│
│ … (15 more)                                                                  │
├─ Severity group header — 24px ─────────────────────────────────────────────┤
│ ● LOW (10)                                                  ACK ALL         │
├─ Alert rows ───────────────────────────────────────────────────────────────┤
│ … (10 rows)                                                                  │
├─ Acknowledged collapse — 24px ─────────────────────────────────────────────┤
│ ▸ Acknowledged (143)                                                         │
└────────────────────────────────────────────────────────────────────────────┘
```

**Grid description.**
- 7-cell row: `[☐ checkbox 16][char-sev 16][ticker 56][entity-name 120][code 40][body 1fr][time 56][ACK▾ 56]`
- Sticky severity group headers at viewport top.
- Sub-tab strip sticky below the page header.
- Right-side AlertDetailSheet (existing) opens on row body click via
  `?selected={id}`.

**Density target.**
At 1440×900 above-fold:
- Page header 28 + tabs 32 + sub-tabs 28 = 88px of chrome.
- 50 active alerts at 22px = 1100px (≈ 37 visible at once before scroll).
- Plus 3 severity group headers @ 24px = 72px.
- **Visible above fold: ~33 alert rows + 3 group headers + chrome ≈ 37 rows
  of data + 8 cells per row = ~296 data cells.**
- With the bulk toolbar visible (extra 28px) we lose 1 row but the toolbar
  itself adds visible state.

**The 50-alerts target is exceeded by design: a typical viewport shows 33
above fold; the user scrolls to reach the rest.** The page is designed for
the limit to be screen real estate, not API limit.

---

### C.5 Component breakdown

| Component | File | Line budget | Props | Renders |
|-----------|------|-------------|-------|---------|
| `AlertsPage` | `app/(app)/alerts/page.tsx` | existing (~300) — reduced to ~200 | — | Page chrome + Tabs + tab content |
| `AlertsList` | `components/alerts/AlertsList.tsx` | existing (~700) — minor tweaks | `{ selectedId, expandPayloads? }` | Severity-grouped rows |
| `AlertRow` | inside `AlertsList.tsx` (or extract) | ~120 | `{ alert, selected, onSelect, onAck, onSnooze, onToggleSelected, expandPayload?, localOnly?, dimmed? }` | One 22px row + optional 18px payload sub-row |
| `AlertHistoryTab` | existing | — | `{ fixedStatus }` | Sub-tab content |
| `AlertDetailSheet` | existing | — | `{ alert, open, onClose, onAck, onSnooze }` | Right-side sheet |
| `AlertRuleBuilder` | existing | — | `{ onRuleSaved, prefill? }` | Rule create dialog |
| `RuleManagerDialog` | existing | — | `{ onRulesChanged, trigger }` | Rule list + edit |
| `NotificationPreferencesDialog` | existing | — | — | Quiet hours + min severity |
| `BulkActionToolbar` | **EXTRACT NEW** `components/alerts/BulkActionToolbar.tsx` | ~80 | `{ count, onAckSelected, onSnoozeSelected(minutes), onClear }` | Currently inline in `AlertsList.tsx`; extract for testability and to add Snooze-selected (new) |
| `SeverityCharBadge` | **NEW** `components/alerts/SeverityCharBadge.tsx` | ~20 | `{ severity }` | `!`/`*`/`·` glyph at fixed 16px width |
| `AlertCodeBadge` | **NEW** `components/alerts/AlertCodeBadge.tsx` | ~30 | `{ alert_type }` | `SIGN`/`GRPH`/`CONT`/`USER` 4-char code |
| `AlertPayloadRow` | **NEW** `components/alerts/AlertPayloadRow.tsx` | ~50 | `{ alert }` | Optional second row showing condensed payload (IBKR-style) |

**Reusable primitives.**
- `TableRow22`, `SeverityDot` (existing), `RelativeTime` (existing).

**Inline payload rendering.**
A new `AlertPayloadRow` shows up to 60 characters of formatted payload data
beneath the main row at 50% opacity. Examples:
- `SIGNAL`: `Earnings beat: $2.18 vs est $2.05 (+6.3%) · vol +180% vs ADV`
- `GRAPH_CHANGE`: `New edge: NVDA → ORCL (supplier) · evidence: 3 articles`
- `CONTRADICTION`: `Disagreement: 8 analysts Buy vs 4 Sell · spread 30%`
- `USER_RULE`: `Current $234.12 vs trigger $230.00 (breached above by $4.12)`

Toggle: a header-row checkbox `Expand payloads` (default off) renders
every alert's `AlertPayloadRow`. Persisted to localStorage so the user's
preference survives.

---

### C.6 Visual spec (numerical)

**Heights.**
- Page header: `h-7` (28px)
- Main tab strip: `h-8` (32px)
- Sub-tab strip: `h-7` (28px)
- Bulk toolbar: `h-7` (28px)
- Severity group header: `h-6` (24px)
- Alert row: `h-[22px]` (mandatory token; do NOT change)
- Payload sub-row: `h-[18px]`
- Acknowledged collapse: `h-6` (24px)

**Padding.**
- Page header `px-3`
- Sub-tab strip `px-0` (matches existing)
- Alert row `px-2`
- Severity group `px-2`
- Payload sub-row `px-2 pl-10` (indented under the checkbox + char glyph)

**Typography.**
- Page title — `text-[11px] font-mono uppercase tracking-[0.08em]`
- Tab labels — `text-[11px]`
- Sub-tab labels — `text-[11px]`
- Bulk toolbar count — `text-[11px] font-mono tabular-nums`
- Bulk toolbar buttons — `text-[10px] uppercase tracking-[0.06em]`
- Severity group header — `text-[10px] uppercase tracking-[0.08em]`
- Severity char glyph — `text-[12px] font-mono` (slightly bumped for legibility)
- Ticker — `text-[10px] font-mono tabular-nums`
- Entity name — `text-[10px] text-muted-foreground` (truncated 1 line)
- Alert code — `text-[10px] font-mono`
- Alert body — `text-[11px] text-foreground` (truncated 1 line)
- Time — `text-[10px] font-mono tabular-nums text-muted-foreground`
- Payload sub-row — `text-[9px] text-muted-foreground/70 leading-tight`
- ACK button — `text-[10px]`

**Colors.**
- CRITICAL row dot/char — `text-negative` / `bg-negative`
- HIGH row dot/char — `text-warning` / `bg-warning`
- MEDIUM — `text-primary` (yellow) / `bg-primary`
- LOW — `text-muted-foreground` / `bg-muted-foreground`
- Selected row tint — `bg-primary/5`
- Snoozed row (in detail) — `opacity-60`
- Ack'd row (in collapsed section) — `opacity-50`
- localOnly badge — bordered `border-border/40 text-muted-foreground/80`

**Severity character glyphs.**

| Severity | Glyph | Why |
|----------|-------|-----|
| CRITICAL | `!` | Universal "alert" — Bloomberg standard |
| HIGH | `*` | Asterisk = "attention" — Bloomberg standard |
| MEDIUM | `·` | Mid-dot = "minor" |
| LOW | `·` (muted) | Same glyph, lower opacity |

---

### C.7 Interaction model

**Hotkeys.**

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate rows |
| `Enter` (with row focused) | Open `AlertDetailSheet` |
| `a` (with row focused) | ACK row |
| `s` (with row focused) | Open snooze submenu |
| `x` (with row focused) | Toggle selected (bulk) |
| `Shift+A` | ACK ALL CRITICAL (new — matches Bloomberg `AAA`) |
| `Shift+S` | Open snooze submenu for all selected |
| `Esc` (with sheet open) | Close detail sheet |
| `/` | Focus search input (when added — v1.1) |
| `g a` (chord) | Go to Active tab |
| `g n` | Go to News Feed tab |
| `g t` | Go to Top Today tab |
| `g h` | Go to History sub-tab |

**Hover behaviour.**
- Row hover → `bg-muted/40`.
- Relative time hover → tooltip shows absolute time + acknowledged-at if set.
- ACK button hover → no change (the dropdown opens on click).

**Click handlers.**
- Click row body → open `AlertDetailSheet` (already wired).
- Click checkbox → toggle bulk-select (already wired).
- Click `ACK ▾` → open snooze submenu.
- Click `ACK ALL` in group header → bulk-ack group.
- Click `Acknowledged (N)` header → expand/collapse.

**Loading state.**
- Per-tab `Skeleton h-[22px]` × 8 (already wired).

**Error state.**
- Per-tab inline error card + retry (already wired).

**Empty state.**
- All-clear: `No pending alerts — you're all caught up.` (already wired).
- Filtered empty (History tab): `No alerts match the filters`.

**Real-time updates.**
- New alerts flow in via `WS /api/v1/alerts/stream`. On receive:
  - Optimistic prepend to the relevant severity group (existing
    `useAlertActions` hook handles cache invalidation).
  - The AlertBell badge increments.
  - **No animation** — alerts appear instantly. Animations would draw the
    eye away from the row the user is currently reading.

**Acknowledgment semantics.**
- Local ACK (existing) — instant UI + fire-and-forget backend PATCH; falls
  back to localStorage-only on 404 with a `(local only)` badge.
- Backend ACK (existing) — `PATCH /v1/alerts/{id}/acknowledge`.
- Per-user dismiss vs tenant-level ack — frontend exposes only the
  per-user model (`PATCH /acknowledge`); tenant-level `DELETE /ack` is
  admin-only and stays out of this page.

---

### C.8 Data fetching

**Existing query keys (keep).**

```ts
qk.alerts.list({ limit: 50 })       // pending alerts
qk.alerts.history({ status, ... })  // history with filters
qk.alerts.rules()                   // user-rule list (localStorage today)
```

**Refresh strategy.**
- `qk.alerts.list`: `staleTime: 0`, `refetchOnWindowFocus: true`.
  Real-time updates come via the WebSocket; the query is mostly the
  reload-fallback.
- `qk.alerts.history`: `staleTime: 60s` (history doesn't change retroactively).

**Dedup opportunities.**
- The `AlertBell` in the TopBar uses `qk.alerts.list({ limit: 5 })`. This
  page uses `qk.alerts.list({ limit: 50 })`. They share the `["alerts",
  "list"]` prefix but cache under different sub-keys. TanStack Query's
  `select` could let the bell read from the larger query — but that
  couples the bell to the bigger fetch. Recommendation: keep separate.
  The badge count is fetched separately (`qk.alerts.list({ limit: 1 })`
  is cheap).

**WebSocket integration.**
- Existing `useAlertStream` hook in `AlertBell.tsx` handles the WS
  connection. This page does NOT open a second WS — when an alert arrives,
  the hook calls `queryClient.invalidateQueries(qk.alerts.list.all)` and
  the page re-fetches.

---

### C.9 Tradeoffs & decisions

**Decision 1: Keep severity-grouped layout (not Bloomberg's flat chronological).**

*Alternatives considered.*
- (a) Flat chronological list, severity as a column (Bloomberg-style).
- (b) **Severity-grouped with sticky headers** (existing, recommended).

*Why (b) wins.* The single most-cited problem with alert systems is "I
missed the critical one in the noise". Grouping by severity at the top
level enforces "critical at the top, always", with the trade-off that
within a severity you sort by time. Bloomberg's flat list works because
power users learn to scan; our user base includes researchers who don't.

**Decision 2: Inline payload row toggle (off by default).**

*Alternatives considered.*
- (a) Always show payload sub-row (~12 fewer alerts visible per page).
- (b) Payload only in detail sheet (current state).
- (c) **Opt-in inline payload row, persisted via localStorage** (recommended).

*Why (c) wins.* Lets the power user double their information density
when they want, without forcing the cost on first-timers. Persistence
means the choice survives sessions.

**Decision 3: 4-character alert codes vs full words.**

*Alternatives considered.*
- (a) `SIGNAL` / `GRAPH_CHANGE` / `CONTRADICTION` / `USER_RULE` (current).
- (b) **`SIGN` / `GRPH` / `CONT` / `USER`** (recommended).

*Why (b) wins.* The current full words steal 50-90px of row width and
push the body text right. 4-char monospace codes are at the Bloomberg
density target and remain unambiguous (no two start with the same prefix
within the available characters).

**Decision 4: Hotkey chords (`g a`, `g n`, `g h`).**

*Alternatives considered.*
- (a) Single keys (`a`, `n`, `h`) — conflicts with the row-level shortcuts.
- (b) **Two-key chords prefixed by `g`** (recommended).
- (c) Cmd+1/2/3.

*Why (b) wins.* Chord shortcuts are the GitHub/Linear/Superhuman
convention. They don't conflict with row-level `a` (ack) or `s` (snooze)
because the chord prefix is `g` (for "go").

---

### C.10 Open questions

1. **Backend `display_trigger` field.** Should the alert service compute
   and return a unified `display_trigger: {label, current_value,
   threshold_value, comparator}` so the row can render Bloomberg-style
   `AAPL last 234.12 vs trigger 230.00` for USER_RULE and a synthetic
   equivalent for SIGNAL?
2. **WebSocket reconnection UX.** When the WS disconnects (token expired,
   network blip), should the page show a "Reconnecting…" banner? Or trust
   the polled query to compensate within 30s on focus?
3. **Bulk snooze.** Adding `Snooze Selected` to the bulk toolbar — should
   the time-window submenu match the per-row dropdown (15m/1h/4h/EOD/24h/
   custom)? Recommendation: yes, identical UX.
4. **Audio cues.** Bloomberg & TradingView both ping audibly on CRITICAL.
   We have no audio system. Out of scope v1; flag as a follow-on.
5. **History tab "View as: severity / time"** — currently History is
   time-ordered. Should a toggle let users see History grouped by
   severity? Recommendation: defer — most history use cases are
   "what fired between dates X and Y", which is naturally time-ordered.

---

## Cross-page concerns

### Shared primitives proposed in `components/data/`

These three pages all benefit from a small set of new shared primitives.
Each is a candidate for a "shared with multiple sections" entry in the
master PRD.

| Primitive | Used by | Notes |
|-----------|---------|-------|
| `TableRow22` | Workspace panels, Predictions list, Alerts list, Screener, Dashboard | `h-[22px]` enforced; ARIA `role="row"`; supports `selected`, `dimmed`, `tinted` modes |
| `MetricCell11` | All numeric cells across all pages | `text-[11px] font-mono tabular-nums`; right-aligned by default |
| `SeverityDot` | Alerts, Workspace alerts panel | 1.5×1.5px dot with severity color |
| `SeverityCharBadge` | Alerts (new for this page) | 16px-wide mono char (!, *, ·) |
| `Sparkline` | Predictions sparkline column, Dashboard movers | SVG line chart; props `{data, width, height, stroke}` |
| `SourceIcon` | Predictions list rows | 16×16 brand glyph for `polymarket`/`kalshi` |
| `RelativeTime` (existing) | Alerts, News, Predictions footer | Tooltip with absolute time |
| `BulkActionToolbar` | Alerts (extract from `AlertsList`) | Generic count + actions slot |

### Hotkey consistency

| Chord | Page | Action |
|-------|------|--------|
| `Ctrl+1..9` | Workspace | Switch workspace tab |
| `g w` | Global | Go to /workspace |
| `g p` | Global | Go to /prediction-markets |
| `g a` | Alerts | Active sub-tab (chord-prefixed) |
| `g n` | Alerts | News Feed sub-tab |
| `g t` | Alerts | Top Today sub-tab |
| `g h` | Alerts | History sub-tab |
| `/` | Predictions, Alerts (future) | Focus search |
| `Esc` | All | Close drawer / sheet |

The global `g`-prefixed chord system (à la GitHub) needs to be defined
once at the shell level (see `01-global-shell.md`). This file assumes
that system exists and adds these specific bindings.

### Empty/loading/error parity

All three pages use the same family of components:
- `Skeleton` for loading (height matches eventual row height to avoid
  layout shift).
- `InlineError` for error state with `onRetry`.
- `InlineEmptyState` for "all caught up" / "no markets" / "no panels"
  cases (no large hero illustrations).

---

## Implementation order (recommendation for PLAN-NN follow-on)

1. **Wave 1 — Alerts polish.** Extract `BulkActionToolbar`, add
   `SeverityCharBadge` and 4-char `AlertCodeBadge`, add `AlertPayloadRow`
   behind an opt-in toggle. No backend changes. Smallest diff, largest
   density win.
2. **Wave 2 — Predictions redesign.** New page composition, drawer,
   inline sparkline. Requires backend additions (`recent_yes_history`,
   `best_bid/ask`) — issue a small PR against S3/S9 first.
3. **Wave 3 — Workspace polish.** Extract `WorkspaceUtilityRow`, add
   freshness footer, opt-in cross-panel crosshair sync. No backend
   changes; entirely additive.
4. **Wave 4 — (deferred)** Tab-stacked panels in Workspace; multi-outcome
   markets in Predictions; bulk-snooze in Alerts.

---

## Acceptance criteria for this design

- [ ] Workspace section §A.4 wireframe renders at 1440×900 with ≥ 200
      visible data cells in the default Quad View template.
- [ ] Predictions section §B.4 wireframe shows ≥ 30 markets above the fold
      with a sparkline per row.
- [ ] Alerts section §C.4 wireframe shows ≥ 33 alert rows + group headers
      above the fold with the 4-char code system applied.
- [ ] Every numeric token in §§A.6 / B.6 / C.6 maps to a row in the global
      typography/spacing scale (§Shared design tokens in `_INDEX.md`).
- [ ] Every backend field listed under §§A.3 / B.3 / C.3 maps to a UI
      element in the corresponding §§A.5 / B.5 / C.5 (or is explicitly
      marked DEFERRED / OUT-OF-SCOPE).
- [ ] No new color tokens introduced; every color call-out resolves to
      `bg-card / bg-background / border-border / text-foreground /
      text-muted-foreground / text-primary / text-positive / text-negative
      / text-warning`.
- [ ] Tradeoff sections (§§A.9 / B.9 / C.9) each list ≥ 2 alternatives.
- [ ] Open questions sections (§§A.10 / B.10 / C.10) each list ≥ 2 items.
