# PRD-0031 — Worldview Terminal UI v3: Ground-Up Redesign

**Date**: 2026-04-25
**Status**: DRAFT
**Author**: Arnau Rodon
**Type**: Full redesign PRD
**Replaces**: PLAN-0037 (partial terminal redesign — superseded)
**Scope**: Complete replacement of `apps/worldview-web` layout, workspace, navigation, and component architecture
**Prerequisite fixes first**: PRD-0031 implementation MUST be preceded by the P0 fixes from QA audit `2026-04-25-qa-terminal-redesign-report.md` (TypeScript, workspace placeholders, screenshots)

---

## 1. Why This PRD Exists

### The honest diagnosis

The current Worldview frontend is an incremental dark-mode improvement of a generic dashboard app. It does not compete against Bloomberg, tastytrade, or Interactive Brokers TWS at the level of information density, workspace flexibility, or visual authority that professional traders require.

The QA audit (`2026-04-25`) found the Wave A/B/C terminal redesign corrected style violations (radius, padding, empty states) but did not address the structural problems:
- The workspace can only hold 4 fixed panels with no resize capability
- Workspaces cannot be saved, named, or switched
- No symbol linking between panels
- Navigation is sidebar-first (text labels, not icon rail) — wastes horizontal screen space on a trading monitor
- Row height is 32px (h-8) — Bloomberg and tastytrade use 18-24px
- Data font size is 12px minimum — professional terminals use 10-11px
- No persistent watchlist strip visible at all times
- Screener shows 7 columns — Finviz shows 14+

The conclusion is not that Wave A/B/C was wasted effort — the primitives and radius/padding sweep remain valid. The conclusion is that the structural layout decisions require a deeper redesign that cannot be achieved with incremental patch waves.

### Competitive benchmark

| Feature | Bloomberg | tastytrade | TWS Mosaic | Finviz | Worldview v2 | Worldview v3 target |
|---|---|---|---|---|---|---|
| Panel resize | Drag | Fixed | Drag | N/A | None | Drag |
| Named workspaces | Tabs | Fixed | Save/load | N/A | None | Named workspaces |
| Symbol linking | None | N/A | Window groups | N/A | None | Group colors |
| Data row height | 18px | 20px | 18px | 22px | 32px | **22px** |
| Data font size | 10px | 11px | 10px | 11px | 12px | **11px** |
| Visible columns (screener) | 12+ | 8-10 | 12+ | 14+ | 7 | **12+** |
| Persistent watchlist | Always visible | Always visible | Always visible | Yes | No | **Always visible** |
| Nav width (icons-only) | N/A | 48px | 48px | N/A | 240px sidebar | **48px rail** |
| Max panels per workspace | Unlimited | N/A | Unlimited | N/A | 4 | **16** |

---

## 2. Target Users

**Primary**: Active retail traders who monitor 10-50 positions, trade daily, and want institutional-grade tools without paying $2,000/month for Bloomberg.

**Secondary**: Quantitative researchers at hedge funds who need a self-hosted alternative to expensive data terminals.

**What they need (not "view data"):**
1. **Scan**: Immediately identify what moved and why (screener, alerts, news)
2. **Drill**: Go deep on a specific security in seconds (chart, fundamentals, intelligence, news)
3. **Monitor**: Watch 10-50 positions and their P&L in real time
4. **React**: Place context around price moves (alerts → news → fundamentals)
5. **Research**: Cross-reference entity graph, news intelligence, and AI briefing

**What they expect** (because Bloomberg trained them):
- Information density: 40-60 rows visible at once without scrolling
- No animation delays: switching panels is instant, no fade-ins
- Keyboard-first: Tab through tables, Enter to drill, Escape to go back
- Workspace memory: their layout survives a browser refresh
- Everything above the fold: no hidden key metrics behind scroll

---

## 3. Design Principles

### P1 — Data is the chrome

Every pixel of shell UI (navigation, headers, borders) must be minimal and invisible. When a trader looks at a screen, they should see data — not containers, labels, or decorative elements.

- Navigation: 48px icon rail, no text
- Panel headers: 24px height maximum (not 32px current)
- Panel titles: 10px uppercase label, never competing with data
- Borders: 1px `#232A36` — structural, not decorative

### P2 — Density without chaos

The Bloomberg Terminal is not cluttered — it is organized. Density comes from:
- Consistent row heights (22px)
- Monospace alignment (numbers right-aligned, tickers left-aligned)
- Semantic color coding (green/red/amber) — eye finds outliers without reading
- 1px dividers between rows, not per-card rounded borders
- Headers are 10px ALL CAPS, not competing with data

### P3 — Workspace respects the trader

Traders spend hours configuring their workspace. That configuration:
- MUST survive a browser refresh (localStorage persistence)
- MUST be switchable between named workspaces in one click
- MUST allow panel resize by drag (not by menu)
- MUST allow symbol linking between panels (one symbol change updates all linked panels)

### P4 — Instant interaction

No fade-in animations on panel load. No slide-in transitions for search results. Data appears or skeletons appear — never decorative delays. The only acceptable transitions:
- Skeleton → data: crossfade, 100ms
- Panel open: none (instant)
- Panel close: none (instant)
- Row hover: none (background-color change only)

---

## 4. Layout Architecture

### 4.1 Shell Structure (always visible, all routes)

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│  TOPBAR (36px) — logo | breadcrumb/symbol | search [⌘K] | clock | market | alerts │
├────┬───────────────────────────────────────────────────────────────────────────────┤
│    │                                                                                │
│ L  │                     MAIN CONTENT AREA                                         │
│ E  │              (route-specific content fills this)                              │
│ F  │                                                                                │
│ T  │              On /workspace: multi-panel grid                                  │
│    │              On /screener: full-width results table                           │
│ R  │              On /instruments/[id]: tabbed detail                              │
│ A  │              On /portfolio: holdings + KPI strip                              │
│ I  │              On /alerts: full-width feed                                      │
│ L  │              On /chat: SSE chat interface                                     │
│    │              On /dashboard: widget grid                                       │
│ 48 │                                                                                │
│ px │                                                                                │
└────┴───────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 TopBar (36px)

```
[W]   WORLDVIEW  │  Workspace: "Day Trading" ▼  │  [⌘K] Search...  │  14:32:07 UTC  │  ● OPEN  │  🔔 3  │  [avatar]
```

- Logo: 24px `W` glyph in `#FFD60A`
- Workspace selector: shows current workspace name + chevron (only on /workspace route)
- Global search: cmd+K trigger, 280px input
- UTC clock: live, `font-mono text-xs`
- Market status pill: `● OPEN (NYSE)` in green / `● CLOSED` in muted
- Alert bell: badge count, navigates to /alerts on click
- Avatar: click opens user menu (settings, sign out)

### 4.3 Left Rail — Collapsible Sidebar (48px collapsed / 220px expanded)

The left rail is **not** a pure icon bar. It is a collapsible sidebar that collapses to 48px (icons only) and expands to 220px (icons + names + embedded watchlist + alarms). State persists to `localStorage['worldview-sidebar-expanded']`.

#### Collapsed state (48px):

```
[W]  ← logo
───
[⊞]  ← Workspace        (g+w)
[⬜]  ← Dashboard         (g+d)
[⚡]  ← Screener          (g+s)
[⊕]  ← Portfolio          (g+p)
[🔔]  ← Alerts             (g+a)
[💬]  ← Chat               (g+c)
───
[👁]  ← Watchlist (collapsed icon)
[🔔]  ← Alarms (collapsed icon)
───
[⚙]  ← Settings + [⟶ Expand]
```

#### Expanded state (220px):

```
[W]  WORLDVIEW
─────────────────────────────
[⊞]  Workspace
[⬜]  Dashboard
[⚡]  Screener
[⊕]  Portfolio
[🔔]  Alerts
[💬]  Chat
─────────────────────────────
WATCHLIST  [Tech Stocks ▾]
─────────────────────────────
AAPL   172.34  +0.72% ▲
MSFT   425.12  +1.23% ▲
GOOGL  178.45  -0.34% ▼
TSLA   241.67  +2.11% ▲
NVDA   875.21  -0.89% ▼
─────────────────────────────
ALARMS  ● 2
■ AAPL > $175.00
■ TSLA Vol spike
─────────────────────────────
[⚙]  Settings  [⟵ Collapse]
```

#### Navigation section (top):

- Active nav item: `bg-primary/15 text-primary` left border `2px solid --primary`
- Hover: `hover:bg-muted/60`
- Icon size: 18px, label: 12px IBM Plex Sans
- Collapsed: icon only + tooltip on hover
- Expanded: icon + label inline

#### Watchlist section (middle):

- Header: `WATCHLIST` (10px uppercase, `--muted-foreground`) + watchlist name button (`[Tech Stocks ▾]`)
- Watchlist switcher: pressing the name button shows a popover listing all saved watchlists with a `[+ New Watchlist]` option
- Watchlist items: ticker (IBM Plex Mono, 40px), price (right-aligned, mono), change% (colored + ▲/▼)
- Row height: 22px; font: 11px IBM Plex Mono
- Click item: navigate to `/instruments/[entityId]`
- Data source: `GET /v1/quotes/batch` with watchlist tickers; refresh every 30 seconds
- Empty state: `No symbols — add via Portfolio watchlist` (11px muted, no full-page empty state)
- In collapsed mode: watchlist icon shows symbol count badge

#### Alarms section (below watchlist):

- Header: `ALARMS` (10px uppercase) + active count badge (red, 11px)
- Content: alerts from `GET /v1/alerts/pending` **filtered client-side** to show only alerts where `ticker` matches held positions or watchlist symbols
- Max 5 rows; if more: `[+N more →]` link to `/alerts`
- Row: `●` severity dot (color-coded) + message truncated, 22px height
- Click row: navigate to `/alerts` with that alert highlighted
- In collapsed mode: alarms icon shows count badge (orange dot if any active)

#### Collapse/expand:

- Toggle: `[⟵ Collapse]` button in bottom section when expanded; `[⟶]` icon button when collapsed
- Breakpoint: viewport `< 1280px` → auto-collapse (no toggle needed — controlled by CSS)
- Animation: `transition-[width] duration-200 ease-out` on sidebar container; `transition-[opacity] duration-150` on text labels
- Do NOT animate `width` as a layout property if using flex — instead use `grid-template-columns: Npx 1fr` on the parent shell and animate that

#### Token values:

- Sidebar background: `#10141C` (`--card`)
- Right border: 1px `#232A36` (`--border`)
- Section dividers: 1px `#232A36` (`--border`)

### 4.4 Routes that do NOT use left rail

None — left rail is always visible. Routes adjust only the main content area.

---

## 5. Workspace — Full Redesign

### 5.1 Workspace Tabs Bar (below TopBar when on /workspace)

```
[+ New]  [Day Trading] ✕  [Research] ✕  [Swing] ✕  [+ Add Workspace]
```

- Tabs show workspace names: `text-xs font-medium`
- Active tab: `border-b-2 border-primary text-foreground`
- Inactive: `text-muted-foreground hover:text-foreground`
- `✕` closes workspace (prompts confirm if >1 panel open)
- `+ Add Workspace` creates a new empty workspace and opens rename dialog
- Workspaces persist to `localStorage['worldview-workspaces']`

### 5.2 Panel Grid

- Default layout: 2 columns × 2 rows (4 panels)
- Maximum: 16 panels (4 columns × 4 rows)
- Panels fill remaining height after TopBar + tabs bar
- Panel resize: drag the border between panels (1px border becomes 3px blue on hover)
- Panel sizes stored as percentage ratios per workspace

### 5.3 Panel Anatomy

```
┌─────────────────────────────────────────────────────────────────┐
│ ● ■ CHART [AAPL ▼]                       [1D] [1W] [1M]  ✕  ⊞ │  ← 24px header
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│                    [panel content]                                │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

Header (24px):
- Left: color chip (6px circle, group color — for symbol linking), panel type icon (14px), panel type label (10px uppercase), symbol selector (inline `[AAPL ▼]`)
- Right: panel-specific controls (timeframe buttons for chart), fullscreen `⊞`, close `✕`

Group color system (TWS-inspired):
- 5 color groups: Red, Green, Blue, Yellow, Purple
- Panels in the same group share symbol context
- Changing symbol in any grouped panel updates all panels with same color group
- Unlinked panels: empty color chip (gray)

### 5.4 Panel Types (10 types, all implemented)

| Type | Icon | Description | Data source |
|---|---|---|---|
| Chart | 📈 | OHLCV candlestick + indicators | `ohlcv/{id}` + `quotes/{id}` |
| News | 📰 | Top news ranked by relevance | `news/top` + `news/entity/{id}` |
| Screener | ⚡ | Compact screener table (no filter panel) | `fundamentals/screen` |
| Alerts | 🔔 | Live alert feed | WebSocket S10 + `alerts/pending` |
| Chat | 💬 | Streaming AI chat | `chat/stream` SSE |
| Fundamentals | 📊 | Key fundamentals strip | `fundamentals/{id}` |
| Graph | 🕸 | Entity relationship graph | `entities/{id}/graph` |
| Portfolio | 💼 | Holdings table | `portfolios` + `holdings/{id}` |
| Watchlist | 👁 | Symbol list + live prices | `quotes/batch` |
| Brief | 🤖 | AI morning/instrument brief | `briefings/morning` |

**Panel specifications** (all 10 — investigation session 3):

| Panel | Min size | Content spec |
|---|---|---|
| Chart | 300×250px | Candlestick OHLCV + MA20/50/200 (default on) + Volume bars; RSI/BB as header toggles `[MA][BB][RSI][Vol]` |
| Screener | 400×200px | 5 cols: Ticker/Name/Change%/MktCap/Score; top 20 by `market_impact_score`; no filter panel; row click → instrument |
| News | 280×200px | Tier badge + title truncated + time + impact dot; 22px rows; click → full news tab |
| Alerts | 280×200px | Grouped by severity; 22px rows; colored left border (CRIT=red, HIGH=amber, MED=yellow); click → alerts page |
| Chat | 280×320px | 36px input + scrollable message history; 11px sans; uses `/chat/stream` SSE |
| Fundamentals | 220×200px | 6 metrics only: MktCap / P/E / EPS / DivYld / 52W Hi-Lo / Beta; 22px rows, 10px labels |
| Graph | 280×240px | 180px graph + scrollable entity table; click node → instrument page |
| Portfolio | 320×200px | 5 cols: Ticker/Qty/AvgCost/Current/P&L; 12 holdings max; link to `/portfolio` in footer |
| Watchlist | 220×200px | 4 cols: Ticker/Price/Change%/MktCap; 22px rows; live refresh 30s; click → instrument |
| Brief | 280×150px | Morning brief; amber `#F0C04018` background; 2px amber left border; collapsed 1 line; expand on click |

### 5.5 Default Workspace Presets (4 presets ship with platform)

```
"Day Trading"          "Research"             "Portfolio Monitor"    "Morning Brief"
┌──────┬──────┐        ┌──────┬──────┐        ┌──────┬──────┐        ┌────────────────┐
│Chart │Watch │        │Chart │News  │        │Port  │Chart │        │Brief           │
│1D    │list  │        │1W    │(rnkd)│        │folio │      │        │(full width)    │
├──────┼──────┤        ├──────┼──────┤        ├──────┼──────┤        ├──────┬─────────┤
│Scrn  │Alerts│        │Fndm  │Graph │        │Watch │News  │        │Scrnr │Alerts   │
│top20 │live  │        │6 KPIs│rel.  │        │list  │(my)  │        │top20 │live     │
└──────┴──────┘        └──────┴──────┘        └──────┴──────┘        └──────┴─────────┘
```

Presets seeded on first load from `localStorage['worldview-workspaces']`. User can rename/delete presets. "Reset to defaults" option in workspace tab right-click context menu.

### 5.6 Add Panel Selector

Click `[+ Add Panel]` button in panel grid (or keyboard shortcut):
```
┌──────────────────────────────────────────────────┐
│  ADD PANEL                                         │
│  ──────────────────────────────────────────────── │
│  📈 Chart        📰 News         ⚡ Screener      │
│  🔔 Alerts       💬 Chat         📊 Fundamentals  │
│  🕸 Graph        💼 Portfolio    👁 Watchlist     │
│  🤖 Brief                                         │
│  ──────────────────────────────────────────────── │
│  [ Cancel ]                                        │
└──────────────────────────────────────────────────┘
```

Simple grid of panel type cards. Click one to add. Dropdown, not full-page modal.

### 5.6 Panel Resize Implementation

**Library**: `react-resizable-panels` (5.4kb gzip, actively maintained).

- Drag handle: 1px `border-border` seam → `3px border-primary/60` on hover; cursor changes to `col-resize` or `row-resize`
- Drag behavior: **immediate, no animation** (Bloomberg style — instant response)
- Snap: to 5% increments (prevents slivers smaller than 80px)
- Min panel size: 15% of workspace dimension (prevents panels from becoming invisible)
- Persistence: panel size ratios stored per workspace as `{panelId: percentage}` in localStorage

### 5.7 Symbol Linking (Group Colors)

Context: `SymbolLinkingContext` (React context, scoped per workspace). Stores `Map<color, currentSymbol>`.

- Panel header: 6px circle chip (left of type icon). Click → popover with 5 colors + "Unlink"
- Colors: Red `#EF5350` | Green `#26A69A` | Blue `#3B82F6` | Yellow `#FFD60A` | Purple `#A855F7`
- `onSymbolChange(symbol, color)`: broadcasts to all panels in the same workspace with matching color
- Only symbol-aware panels receive updates: Chart, Fundamentals, Graph, Brief (instrument), News (entity-filtered)
- Unlinked panels: gray chip, do not receive broadcasts

### 5.8 Workspace Persistence Schema

```typescript
// localStorage key: 'worldview-workspaces'
interface WorkspacePersistence {
  activeWorkspaceId: string;
  workspaces: WorkspaceConfig[];
}

interface WorkspaceConfig {
  id: string;
  name: string;
  panels: PanelConfig[];
  layout: PanelLayout; // percentage-based column/row ratios
}

interface PanelConfig {
  id: string;
  type: PanelType;
  symbol?: string; // current symbol for symbol-aware panels
  groupColor?: 'red' | 'green' | 'blue' | 'yellow' | 'purple' | null;
  params?: Record<string, unknown>; // panel-specific params
}
```

---

## 6. Typography System (v3)

### 6.1 Font scale changes from v2

| Use | v2 | v3 |
|---|---|---|
| Data table rows | 12px `text-xs` | **11px `text-[11px]`** |
| Panel headers/labels | 10px `text-[10px]` uppercase | 10px (unchanged) |
| Section headings | 13px `text-sm` | 12px `text-xs` |
| Primary body text | 14px `text-sm` | 13px `text-[13px]` |
| Instrument price (large) | 20px `text-xl` | 18px `text-lg` |
| Topbar/navigation | 12px `text-xs` | 11px `text-[11px]` |

**Why 11px for data**: Bloomberg Terminal data rows are 10-11px. At 11px with IBM Plex Mono, financial values are readable from 18-24 inches. This is the standard for professional tools.

### 6.2 Row height changes from v2

| Surface | v2 | v3 |
|---|---|---|
| Data table rows | 32px `h-8` | **22px `h-[22px]`** |
| Panel header | 32px `h-8` | 24px `h-6` |
| TopBar | 44px | 36px `h-9` |
| Left rail icons | 40px | 36px |
| Alert rows | 32px → compact done in Wave A | **22px** |

**Why 22px**: tastytrade uses 20px. Bloomberg uses 18px. 22px is the sweet spot — readable without squinting, dense enough to show 30+ rows on a 1080p screen.

---

## 7. Screener — New Architecture

### 7.1 Column system (target: 12 visible columns at 1440px)

| Column | Width | Format | Source |
|---|---|---|---|
| Ticker | 70px | `font-mono text-left` | `ticker` |
| Name | 160px | `truncate text-left` | `name` |
| Sector | 100px | `truncate text-left` | `gics_sector` |
| Price | 80px | `font-mono text-right` | quote (live if available, `—` if not) |
| Change% | 70px | `font-mono text-right` + HeatCell | `daily_return` |
| Mkt Cap | 80px | `font-mono text-right` abbreviated | `market_cap` |
| P/E | 60px | `font-mono text-right` | `pe_ratio` |
| Revenue | 80px | `font-mono text-right` | `revenue_ttm` (backend) |
| Beta | 55px | `font-mono text-right` | `beta` (backend) |
| Score | 70px | Progress bar | `market_impact_score` |
| 52W Range | 100px | Mini range bar | from fundamentals |
| Volume | 80px | `font-mono text-right` | from quote |

**Note on backend dependencies**: Revenue TTM and Beta require S9 screener endpoint to include these fields. If not available, those columns show "—" with a tooltip "Requires data update". Document as P1 backend item, not a blocker for frontend implementation.

### 7.2 Filter bar (always inline, not in a left panel)

```
[⚡ SCREENER] [847 results]                                [Filters ▾] [Reset] [Export ↓]
──────────────────────────────────────────────────────────────────────────────────────────
TICKER  NAME       SECTOR    PRICE  CHG%  MKT CAP    P/E   REVENUE   BETA  SCORE  52W%
```

When `[Filters ▾]` is clicked:
```
[Search ticker/name...] | [Sector ▼ All] | [Cap ▼ All] | [P/E < 30] | [Score > 70] | [Apply]
```

Filter bar: 36px height, collapses/expands with animation (`grid-template-rows: 0fr → 1fr`).

### 7.3 Table behavior

- Row height: 22px
- Font: 11px IBM Plex Mono for numbers, 11px IBM Plex Sans for text
- Sort: click header → ascending → descending → unsorted cycle
- Row click: navigate to `/instruments/[entityId]`
- Hover: `hover:bg-muted/40` (very subtle)
- Sticky header row
- Virtual scroll for 1000+ results (react-virtual)

---

## 8. Portfolio — Full Architecture

### 8.1 Layout

```
PORTFOLIO                                              [+ Manual Entry]
────────────────────────────────────────────────────────────────────────────────────────────
Total Value  │  Day P&L      │  Unrealised P&L  │  Top Gainer    │  Top Loser    │  Positions
$124,328     │  +$234 +0.19% │  +$8,234 +7.1%   │  MSFT +51.8%  │  GOOGL -3.2% │  8
────────────────────────────────────────────────────────────────────────────────────────────
[Holdings] [Transactions] [Watchlists] [Brokerages]
```

### 8.2 KPI strip rules

**6 KPI tiles** (revised from original spec — Realized P&L/Beta/Sharpe require backend features not yet built):
- Total Value: `SUM(current_price × qty)` — computed from live quotes
- Day P&L: `SUM(quote.change × qty)` — `text-positive` / `text-negative` based on sign
- Unrealised P&L: `total_value - total_cost`; same color coding
- Top Gainer: ticker + P&L% of the holding with highest unrealised P&L% — always `text-positive`
- Top Loser: ticker + P&L% of holding with lowest unrealised P&L% — always `text-negative`
- # Positions: count of holdings

KPI tile: flex-1 equal widths. Value: 16px `text-base font-mono`. Label: 10px uppercase muted.
**Rule**: `text-primary` (`#FFD60A`) NEVER appears in KPI values. Only `text-positive`, `text-negative`, or `text-foreground`.

### 8.3 Holdings tab

```
HOLDINGS                                                    [⬇ Export CSV]  [Sort ▾]
──────────────────────────────────────────────────────────────────────────────────────
TICKER  NAME          QTY    AVG COST   CURRENT   P&L        P&L%     VALUE    WEIGHT  SECTOR
AAPL    Apple Inc.    100    150.00     172.34   +2,234    +14.9%    17,234   13.9%   Technology
MSFT    Microsoft     50     280.00     425.12   +7,256    +51.8%    21,256   17.1%   Technology
──────────────────────────────────────────────────────────────────────────────────────
TOTAL                                             +9,490     +8.8%   124,328
```

- `<table>` element (semantic, required)
- Row height: 22px; font: 11px IBM Plex Mono (numbers), 11px IBM Plex Sans (text)
- **9 columns**: Ticker | Name | Qty | Avg Cost | Current | P&L$ | P&L% | Value | Weight | Sector
- Sector: fetched via `getFundamentals(instrument_id)` per holding (mount-time, cached in `sessionStorage`). Show `—` skeleton then real value.
- Weight: `(value / totalValue) × 100` computed client-side
- P&L$: `(current - avg_cost) × qty` — `text-positive` if positive, `text-negative` if negative
- Sort: click column header — default by P&L% descending (biggest winners first)
- Row click: navigate to `/instruments/[entityId]`
- Stale current price: `~` prefix + `StaleDataBadge` in column header
- Total row: sticky at bottom, `border-t-2 border-border font-semibold`

**Sector Allocation Panel** (below holdings, above tab bar):

```
ALLOCATION BY SECTOR                              ALLOCATION BY TYPE
Technology  54% ████████████░░░                  Equity  87% ██████████████░░
Healthcare  18% ████░░░░░░░░░                    Cash     8% ████░░░░░░░░░░░░
Finance     13% ███░░░░░░░░░░░                   Options  5% ██░░░░░░░░░░░░░░
```

- Two side-by-side horizontal bar charts: By Sector + By Asset Type
- Bar fill: `bg-positive/30` (teal at 30% opacity)
- Sector data: from fundamentals `gics_sector` per holding
- If all null: `<InlineEmptyState message="Sector data unavailable — fundamentals loading." />`

### 8.4 Transactions tab

```
TRANSACTIONS  [All types ▾]  [All time ▾]  [All tickers ▾]          [⬇ Export CSV]
──────────────────────────────────────────────────────────────────────────────────
DATE                TYPE   TICKER   QTY     PRICE       TOTAL       FEE
2026-04-22 14:32    BUY    AAPL     50      $168.40     $8,420.00   $0.65
2026-04-18 09:31    SELL   TSLA     25      $241.00     $6,025.00   $0.48
2026-04-15 09:30    DIV    AAPL     —       —           $23.75      —
```

**Filters** (inline filter bar, collapsible):
- Type: `[All] [BUY] [SELL] [DIVIDEND]` segmented control
- Date: `[All time] [Today] [1W] [1M] [3M] [1Y]` dropdown
- Ticker: dropdown of unique tickers

**Columns**: Date (ISO absolute) | Type (badge) | Ticker | Qty | Price | Total | Fee
Row height: 22px. Newest-first sort. Pagination: "Load more (100 at a time)" at bottom.
Type badge colors: BUY = `bg-positive/20 text-positive`, SELL = `bg-negative/20 text-negative`, DIV = `bg-primary/20 text-primary`

**Backend gap**: gateway.ts currently filters to BUY/SELL only. Must add DIVIDEND type mapping: `if (s1Tx.type === 'DIVIDEND') return { ...mapped, type: 'DIVIDEND', qty: null, price: null }`.

Footer note: `"Dividend records sync from connected brokerages. Manual dividend entry coming soon."`

### 8.5 Watchlists tab

```
[Tech Stocks]  [Earnings Watch]  [Macro Plays]  [+ New Watchlist]        [Edit ✎]
──────────────────────────────────────────────────────────────────────────────────
  🔍 Search to add symbol...
──────────────────────────────────────────────────────────────────────────────────
TICKER  NAME          PRICE       CHG%         MKT CAP    52W RANGE         ADDED
AAPL    Apple Inc.    172.34  ▲  +0.72%       2.87T      124.00 ─ 199.62  Apr 1
MSFT    Microsoft     425.12  ▲  +1.23%       3.16T      311.00 ─ 468.35  Mar 15
NVDA    NVIDIA        875.21  ▼  -0.89%       2.15T      434.00 ─ 974.00  Mar 20
```

**Tabs**: One tab per watchlist. Max 5 visible; overflow → dropdown `[▾ N more]`.
`[+ New Watchlist]` → name dialog → create → switch to new tab.
`[Edit ✎]` → inline mode: rename watchlist name | `[Delete watchlist]` button.

**Search bar** (inline, 36px): Type to search via `GET /v1/search?q=X` → dropdown results → click to add to current watchlist (`POST /v1/watchlists/{id}/members`).

**Per-row `×` remove button**: appears on hover → removes member (`DELETE /v1/watchlists/{id}/members/{entity_id}`).

**Columns**: Ticker | Name | Price | Change% | Mkt Cap | 52W Range | Date Added
Live prices: `GET /v1/quotes/batch` refresh every 30s.
Mkt Cap + 52W: from `fundamentals/{id}` per member (cached in sessionStorage).
Row click → `/instruments/[entityId]`.
Row height: 22px.

**Empty watchlist**: `<InlineEmptyState message="Search above to add your first symbol." />` — no large centered card.

### 8.6 Brokerages tab

```
CONNECTED BROKERAGES                                          [+ Connect Brokerage]
──────────────────────────────────────────────────────────────────────────────────
┌─────────────────────────────────────────────────────────────────────────────────┐
│  ● Interactive Brokers     STATUS: ● ACTIVE     Last sync: Apr 25, 09:14 UTC   │
│                            [Sync Now]  [Sync Errors (0)]  [Disconnect]          │
│  Holdings: 12  │  Transactions: 847  │  Connected: Mar 8, 2026                  │
└─────────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────────┐
│  ● Robinhood               STATUS: ● ERROR      Last sync: Apr 24, 22:01 UTC   │
│                            [Retry Sync]  [Sync Errors (3 ▾)]  [Disconnect]     │
│  ⚠ 3 sync errors (expand to view)                                               │
│  ── unknown_instrument: "NVDL" not found in instruments table (2026-04-24)     │
│  ── unsupported_type: "options" transaction skipped (2026-04-23)               │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Per connection card**:
- Status badge: `● ACTIVE` (positive teal) | `● PENDING` (yellow) | `● ERROR` (red) | `● DISCONNECTED` (muted)
- `[Sync Now]` → POST `/{id}/sync` → spinner → success/error toast
- `[Sync Errors (N)]` → expands inline error list (error_type + error_detail per item)
- `[Disconnect]` → confirm dialog → DELETE `/{id}` → card removed
- Stats: "Holdings: N | Transactions: N | Connected: [date]"

**Empty state**: If no connections: `<InlineEmptyState message="Connect a brokerage to auto-sync your portfolio." />` with single `[Connect Brokerage]` CTA.

**`[+ Connect Brokerage]`** → opens existing `ConnectBrokerageModal` (SnapTrade OAuth flow).

---

## 9. Instrument Detail — New Architecture

### 9.1 Instrument Header (compact — max 56px total)

**Investigation decision**: The right half of the second row displays the company description (not empty space), and the AI brief appears as a sticky amber subheader below the header — not as a tab.

```
← [AAPL]  NASDAQ  •  Technology                    $172.34 ▲ +1.23 (+0.72%)  ● LIVE 14:32
─────────────────────────────────────────────────────────────────────────────────────────────
MKT CAP 2.87T │ P/E 28.4 │ EPS 6.11 │ 52W 124–199 │ VOL 43.2M  │  Apple Inc. designs and sells
                                                                     consumer electronics and ...  Read more →
```

Row 1 (28px): back nav, ticker, exchange badge, sector badge, live price + change, live badge
Row 2 (28px): two-column split —
- **Left ~60%**: stats strip (MKT CAP │ P/E │ EPS │ 52W │ VOL) in 10px uppercase monospace with `│` separators
- **Right ~40%**: company description truncated to 1 line (max 120 chars) + `Read more →` button in `text-primary`

"Read more →" behavior: clicking expands a third row inline (not a modal) showing the full description in 11px text with `[Close ▴]` button. Source: `GET /v1/entities/{entity_id}` → `description` field.

### 9.2 AI Brief Subheader (sticky, amber, below header)

**Investigation decision**: The "Brief" tab is removed. The AI brief appears as a sticky collapsed subheader between the instrument header and the tabs bar. This ensures AI context is always visible without requiring a tab click.

```
─────────────────────────────────────────────────────────────────────────────────────────────
🤖  Apple (AAPL) is showing strong momentum with earnings outperformance. Key risk: China    [▾]
─────────────────────────────────────────────────────────────────────────────────────────────
```

Expanded:
```
─────────────────────────────────────────────────────────────────────────────────────────────
🤖  Apple (AAPL) is showing strong momentum with earnings outperformance. Key risk: China    [▴]
    revenue exposure and regulatory headwinds for App Store. The market treats this name as
    a defensive tech hold with AI optionality priced in. Next catalyst: WWDC 2026 (June 9).
─────────────────────────────────────────────────────────────────────────────────────────────
```

- Component: `InstrumentAISubheader`
- Background: `#F0C04018` (amber-dim, `--amber/10`)
- Left border: `2px solid #FFD60A` (amber — the ONLY acceptable use of left-border accent in Worldview)
- Icon: amber `🤖` (16px)
- Collapsed height: 36px (1 line + padding)
- Expanded height: auto (3-5 lines)
- Toggle: `[▾]` / `[▴]` chevron button at right edge
- State: persisted per entity in `sessionStorage` (resets on page close)
- Data source: instrument-specific brief if available; fallback to morning brief entity mention

### 9.3 Tabs (4 tabs — Brief removed)

```
[Overview] [Fundamentals] [News] [Intelligence]
```

Tab content starts immediately below the AI subheader — no additional gap, no extra padding.

### 9.4 Overview tab — 5-Zone Dense Layout

**Investigation decision**: Overview expands from 2 zones (chart + graph) to 5 zones including news and key metrics. All zones use current S9 API data.

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                           │
│                         OHLCV CHART  (full width, 300px min height)                      │
│                                                                                           │
├───────────────────────────────────────────────────────────────────────────────────────────┤
│  O: 171.12  H: 173.01  L: 170.88  V: 43.2M  VWAP: 171.89                                │  ← SessionStatsStrip (20px)
├───────────────────────────────────────────────────────────────────────────────────────────┤
│  [1D] [5D] [1M] [3M] [6M] [1Y] [2Y] [5Y]                                                │  ← timeframe bar (28px)
├──────────────────────────────┬────────────────────────────────┬──────────────────────────┤
│  KEY METRICS (3 cols)        │  TOP NEWS (3 cols)             │  ENTITY GRAPH (4 cols)   │
│  ──────────────────────────  │  ─────────────────────────     │                          │
│  Market Cap   2.87T          │  [H] Apple Beats Q1...  2h    │   [graph component]      │
│  P/E Ratio    28.4x          │  [M] Tim Cook on AI...  4h    │   180px fixed height     │
│  EPS (TTM)    $6.11          │  [L] App Store...       1d    │                          │
│  Dividend     0.94%          │  [L] China suppliers... 2d    │  RELATED ENTITIES        │
│  52W Hi/Lo    124–199        │  → More news                   │  [table below graph]     │
│  Beta         0.89           │                                │                          │
└──────────────────────────────┴────────────────────────────────┴──────────────────────────┘
```

**Zone 1 — OHLCV Chart**: full width, 300px min height. Source: `ohlcv/{id}`. 11px axis labels. No padding around chart — edge-to-edge.

**Zone 2 — SessionStatsStrip** (new component): full width, 20px height. O/H/L/V/VWAP from the **last OHLCV bar** (not from Quote type — Quote does not have open/high/low). Separator: `│`. Font: 10px IBM Plex Mono `--muted-foreground`. Background: `--card`.

**Zone 3 — Timeframe bar**: full width, 28px. Buttons: `1D | 5D | 1M | 3M | 6M | 1Y | 2Y | 5Y`. Font: `text-[11px]`. Active: `bg-primary/15 text-primary`. Inactive: `text-muted-foreground hover:text-foreground`.

**Zone 4 — Key Metrics** (3 of 10 grid columns): Top 6 fundamentals from `fundamentals/{id}`. Row height 22px. 11px IBM Plex Mono values, 10px IBM Plex Sans labels. Values right-aligned. Show `—` for missing fields.

**Zone 5 — Top News** (3 of 10 grid columns): Top 4 articles from `news/entity/{id}` sorted by `market_impact_score` desc. Row height 22px. Format: `[TIER] Title truncated  time`. Tier badge: 3-char `rounded-[2px]`. `→ More news` link navigates to News tab.

**Zone 6 — Entity Graph** (4 of 10 grid columns): `entities/{id}/graph`. Fixed 180px height for graph, scrollable entity table below. Click node navigates to that instrument.

### 9.5 Fundamentals tab

**Investigation session 3 decision**: 4 new sections required for institutional/BlackRock-grade quality.

Section order (top to bottom): Analyst Consensus → Revenue Trend → Valuation → Profitability → Growth → Dividends → Balance Sheet → Debt & Credit → Cash Flow

```
ANALYST CONSENSUS  ─────────────────────────────────────────────────────────────────
Consensus      [████████████░░░░] BUY    Buy: 18 │ Hold: 9 │ Sell: 3    32 analysts
Price Target   $210.00              High: $240  │  Median: $210  │  Low: $162
EPS (FY2026E)  $6.84  ↑            [↑ raised from $6.52, 90d ago]
Revenue (2026E) $396B  ↑           [↑ raised from $389B]
Updated: Apr 22, 2026

REVENUE TREND (QUARTERLY)  ──────────────────────────────────────────────────────────
Q3'24    Q4'24    Q1'25    Q2'25(E)
$89.5B  $119.6B  $95.4B   $85.8B     QoQ: -10.1% ▼     YoY: +4.9% ▲

VALUATION             vs Sector    PROFITABILITY          GROWTH
────────────────────              ───────────────────    ───────────────────
Market Cap   2.87T               Gross Margin  44.1%    Rev Growth    8.3%
P/E Ratio    28.4×   22.1× ↑    Oper. Margin  26.8%    Est. Rev (E)  7.2%
Forward P/E  26.2×   20.5× ↑    Net Margin    21.3%    EPS Growth   12.1%
EV/EBITDA    18.9×   15.2× ↑    FCF Margin    28.7%    Est. EPS (E)  9.8%
PEG Ratio    2.3×               ROCE          28.4%

BALANCE SHEET              DIVIDENDS
───────────────────────    ────────────────────
Total Assets   352.6B      Annual Dividend  $0.96/sh
Total Equity    62.1B      Dividend Yield   0.56%
Total Debt      97.8B      Payout Ratio    15.7%
Cash           61.2B       Ex-Div Date     Feb 7

DEBT & CREDIT  ──────────────────────────────────────────────────────────────────────
Interest Coverage  45.2×    [EBIT/Interest — > 5× = healthy (green)]
Net Debt/EBITDA    -0.7×    [negative = net cash]
Debt Due < 1Y      $2.3B
Debt Due 1–3Y      $8.4B
Credit Rating      AA+      [S&P, Dec 2025]

CASH FLOW (TTM)  ────────────────────────────────────────────────────────────────────
Operating CF       $122.2B  [+12.4% YoY]
Capital Expenditure $11.8B
Free Cash Flow     $110.4B  [OpCF − CapEx]
FCF Margin          28.7%   [FCF / Revenue]
Cash Conversion     90.5%   [OpCF / Net Income]
```

**Section rules**:
- Analyst Consensus: rating bar = proportional horizontal pill (green/grey/red). Revision arrow: `↑` `text-positive`, `↓` `text-negative`. Show `N/A` if no consensus data. Source badge: "32 analysts"
- Valuation "vs Sector": `text-muted-foreground text-[10px]` inline after each metric — premium/discount context
- Estimate rows: `bg-muted/30` row background to visually distinguish forward estimates from trailing actuals
- Debt & Credit color: interest coverage > 5× = `text-positive`, 2.5–5× = `text-warning`, < 2.5× = `text-negative`
- Cash Flow: FCF Margin > 20% = `text-positive`
- `StaleDataBadge` if fundamentals data > 7 days old
- Footer: "Data: EODHD · Estimates: N analysts · Updated [date] UTC"

### 9.6 News tab

Default: compact list mode. Date range and sentiment filters above the table.

```
[All time ▾]  [All sentiment ▾]         SCORE ▾               [List ☑] [Card]
──────────────────────────────────────────────────────────────────────────────────────────
[HI] Reuters   2h    94   Apple Beats Q1 — Services Revenue Surges 12%             ↗
[MED] Bloomberg  4h   71   Tim Cook Comments on AI Strategy Ahead of WWDC           ↗
[LO] PRN        1d   31   Apple Opens New Retail Store in Shanghai                  ↗
```

- Date filter (dropdown): `All time | Today | Past Week | Past Month`
- Sentiment filter (dropdown): `All | 📈 Positive (score > 0.65) | 📉 Negative (score < 0.35) | ◼ Neutral`
- Filters apply client-side on fetched news data
- Row height: 22px. Tier badge: `HI/MED/LO` rounded-[2px]. Source + time left. Score right-aligned. Title truncated. External link arrow.

### 9.7 Intelligence tab

```
HIGH  2  │  MEDIUM  5  │  LOW  12          [ALL] [HIGH] [MEDIUM] [LOW]     [30d ▾]
──────────────────────────────────────────────────────────────────────────────────────────
SEV   SIGNAL                  SOURCES     WEIGHT   DATE
[H]   Management change       SEC, WSJ     0.87    2d ago    [▾ Expand]
[M]   Supply chain risk       Reuters      0.61    5d ago    [▾ Expand]
[L]   New product patent      USPTO        0.34    3w ago    [▾ Expand]

CONTRADICTIONS  ─────────────────────────────────────────────────────────────────────────
↑ Reuters: positive earnings outlook         ↓ Goldman: margin pressure (Mar 2026)
```

**Investigation session 3 decision**: Add signal quality depth indicators.

Severity count strip: `HIGH N │ MEDIUM N │ LOW N` — clickable, filters signal list below.
`[ALL] [HIGH] [MEDIUM] [LOW]` segmented control syncs with strip.
Date range: `[30d] [90d] [180d] [All]`.

**Signal row format** (per row):
```
[H]   Management change       [▓▓▓▓▓▓▓▓░░]  87    [DEEP][NEW]   2d ago   [▾]
```
- Impact bar: 10-segment proportional to `market_impact_score`
- Processing tier badge: `[DEEP]` green | `[MED]` yellow | `[LIGHT]` grey
- Novelty badge: `[NEW]` primary/yellow (novelty > 0.85) | `[DUP]` red (novelty < 0.40)

**Expanded row** (click `[▾]`):
- Full claim text (wraps, no truncation)
- Source: document type badge (SEC 8-K / News / Earnings Call) + title + date
- Confidence: `98% [Stage 1 — Direct alias match]`
- Novelty score: `0.94 — Novel claim (no prior similar claims detected)`
- `[View source ↗]` link

**Temporal histogram** (above signal list):
- 30px height, weekly buckets over selected date range
- Bar fill: proportional to signal count that week
- Hover bar → filters signal list to that week
- Shows spike periods clearly (e.g., "signals clustered around earnings date")

**Data fields required** from NLP pipeline (S6/S7):
`market_impact_score`, `routing_tier`, `novelty_score`, `resolution_confidence`, `resolution_stage`, `source_type`

---

## 10. Dashboard — Trader Morning Routine Layout

**Investigation decision**: The dashboard is redesigned around the 5 core "market open" questions that traders ask every morning. Previous layout was generic widget grid; new layout is task-oriented.

### 10.1 Five core morning questions (priority order)

1. **Market regime** — is the market up/down, volatile or calm? (ES futures, VIX, yield curve)
2. **Portfolio overnight damage** — which positions gapped against me?
3. **News catalysts** — what news broke that affects my holdings?
4. **Economic calendar** — what macro data drops today?
5. **Watchlist pre-market action** — which watchlist stocks are moving?

### 10.2 Layout

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│  MORNING BRIEF (full width, collapsible — amber left accent border)               │
├──────────────────────────────┬────────────────────────────────────────────────────┤
│  MARKET SNAPSHOT  (4 cols)   │  SECTOR HEATMAP  (8 cols)      ← row 2             │
│  ES:  5,234  +0.8%  (—)      │  Technology  +1.2%  ████████████                  │
│  VIX: 14.2   LOW ▼  (—)      │  Energy      +2.1%  ████████████████              │
│  NQ:  18,421 +1.1%  (—)      │  Finance     +0.1%  █                             │
│  2Y:  4.82%  10Y: 4.51%      │  Healthcare  -0.4%  ░░░░░ (negative = lighter)    │
│  Spread: -0.31% (inverted)   │  Real Estate -1.2%  ░░░░░░░░                      │
├──────────────────────────────┼──────────────────────────┬─────────────────────────┤
│  PORTFOLIO SUMMARY  (4 cols) │  PRE-MARKET MOVERS (5col)│  PREDICTION MKTS (3col)│
│  $124,328  +$234 +0.19%      │  TOP GAINERS  TOP LOSERS │  Fed cuts Jun  62%     │
│  Unrealised: +$8,234 +7.1%   │  RCAT  +18%   NVDA -4%  │  BTC > 100k   44%      │
│  3 pos at day high           │  COIN   +9%   META -2%  │  AAPL ER beat  71%     │
│  1 pos at day low            │  SMCI   +7%   TSLA -2%  │  [View all →]           │
├──────────┬───────────────────┴──────────────────────────┴─────────────────────────┤
│  ECON    │  EARNINGS         │  PORTFOLIO NEWS            │  RECENT ALERTS         │
│  CALENDAR│  (next 5 days)    │  (held stock news)         │  (HIGH + CRITICAL)     │
│  (3 cols)│  (3 cols)         │  (3 cols)                  │  (3 cols)              │
└──────────┴───────────────────┴────────────────────────────┴────────────────────────┘
```

### 10.3 Widget specifications

**Morning Brief** (full width, rows=1):
- Collapsible to 1 line (28px) + expand to full text
- Left border: `2px solid #FFD60A` (amber — AI content marker)
- Background: `#F0C04018` (amber-dim)
- Source: `GET /v1/briefings/morning`

**Market Snapshot** (4 cols) — Row 2, left:
- Shows: ES futures, VIX, NQ, 2Y yield, 10Y yield, yield spread (inverted flag if negative)
- Backend status: **not yet available** — all fields show `—` with 10px muted footnote `[futures data — EODHD macro integration pending]`
- Do NOT show a blank panel — show the labels with `—` values so the layout slot is claimed
- Yields (2Y/10Y/spread): available from EODHD — PLAN-0038 or later
- Source: EODHD macro data endpoint (future integration)

**Sector Heatmap** (8 cols) — Row 2, right (moved up from row 3):
- Horizontal bar chart: sector name + avg change% for that sector + colored fill bar
- Positive sectors: `bg-positive/30` (teal at 30%); negative sectors: `bg-negative/20` (red at 20%)
- Uses screener data: `POST /v1/fundamentals/screen` all results, grouped by `gics_sector`, avg `daily_return` per sector
- Computed client-side; 8-10 GICS sectors shown
- Row height: 22px

**Portfolio Summary** (4 cols) — Row 3, left:
- Total value, unrealised P&L, day P&L
- Count of positions at day high / day low (computed from quotes: `quote.price >= quote.high_52w * 0.98`)
- Click → navigate to `/portfolio`
- Source: `GET /v1/portfolios` + `GET /v1/portfolios/{id}/holdings` + `GET /v1/quotes/batch`

**Pre-Market Movers** (5 cols) — Row 3, center (moved down from row 2, narrowed):
- Shows top 5 gainers + top 5 losers by `daily_return` from screener (prior session proxy)
- Two sub-columns: GAINERS | LOSERS, each showing Ticker + Change%
- Label: `[Prior session — pre-market data coming soon]` in 10px muted text, right-aligned
- Source: `POST /v1/fundamentals/screen` sorted by `daily_return` desc/asc, top 5 each
- Row height: 22px

**Prediction Markets** (3 cols) — Row 3, right (NEW):
- Title: `PREDICTION MARKETS` (10px uppercase)
- Shows: top 3 Polymarket predictions ranked by: (a) volume, (b) entity match to portfolio/watchlist symbols
- Columns: Question (truncated, 11px) | Probability (mono, right-aligned, color: >60% positive teal, <40% negative red, else muted)
- Row height: 22px
- Source: `GET /v1/predictions/top` (from `market.prediction.v1` Kafka topic, PRD-0019 integration)
- Footer: `[View all →]` link to future `/predictions` page
- If no data: `[Prediction market data loading…]` inline empty state — do NOT hide the widget

**Economic Calendar** (3 cols):
- Today's economic events, time + name + prior/forecast
- Source: existing `GET /v1/entities/events` or similar — **has real data**

**Earnings Calendar** (3 cols):
- Next 5 trading days earnings releases, EPS estimate vs prior
- Backend status: **not yet available** — show `— (earnings calendar coming soon)`
- Source: EODHD corporate events (future integration)

**Portfolio News** (3 cols):
- Top 4 articles from `GET /v1/news/top` filtered client-side to show only articles mentioning held tickers
- Row height: 22px. Tier badge + title truncated + time ago
- If no portfolio: show general `GET /v1/news/top` with label `[Top market news]`

**Recent Alerts** (3 cols):
- Top 4 alerts from `GET /v1/alerts/pending` where severity is HIGH or CRITICAL
- Row height: 22px. Severity dot + message truncated + time
- Click: navigate to `/alerts`

### 10.4 Widgets removed from previous spec

- **AI Signals**: removed — endpoint returns empty array (stub, no data). Re-add when real signals flow.
- **Prediction Markets**: moved out of dashboard — available as a workspace panel type.
- **Watchlist News**: replaced by Portfolio News (more actionable — filtered to held stocks).

Row heights throughout dashboard: 22px. Each panel has a 24px `PanelHeader` with 10px uppercase title. No decorative whitespace.

---

## 11. Alerts — Full Redesign (BlackRock Grade)

**Investigation session 3 decision**: Add alert rule builder, severity grouping, ACK/snooze, portfolio risk system alerts.

### 11.1 Layout

```
ALERTS                [+ Create Rule]  [⚙ Manage Rules]    [UNREAD ONLY ☐]
────────────────────────────────────────────────────────────────────────────────────────────
[🔔 Alerts (3)] [📰 News Feed] [📈 Top Today] [👁 My Holdings]
────────────────────────────────────────────────────────────────────────────────────────────
● CRITICAL  (2)                                                         [ACK ALL]
  [SYS] AAPL   PRICE_SPIKE        AAPL up 8.2% in 15min — vol 3× avg     2m  [ACK ▾]
  [SYS] Risk   CONCENTRATION      AAPL position reached 16.2% of port     1m  [ACK ▾]

● HIGH  (4)
  MSFT   EARNINGS_BEAT      MSFT Q1 EPS $2.94 vs $2.81 est               1h  [ACK ▾]
  NVDA   ANALYST_UPGRADE    MS upgrades NVDA to Overweight, $1,200 PT     2h  [ACK ▾]

● MEDIUM  (7)
  GOOGL  ANALYST_DOWNGRADE  Goldman cuts GOOGL to Neutral                  3h  [ACK ▾]
  ...

── Acknowledged (3) ────────────────────────────────────────────────────────────────────
  [collapsed — click to expand]
```

### 11.2 Severity-Grouped Display

- Groups: `● CRITICAL` | `● HIGH` | `● MEDIUM` | `● LOW` — each a collapsible section
- Group header: `text-[10px] uppercase border-b border-border py-1 flex justify-between`
- CRITICAL header color: `text-negative`; HIGH: `text-warning`; MEDIUM/LOW: `text-muted-foreground`
- `[ACK ALL]` button per group: marks all in that group as acknowledged
- Alert row: 22px height, `divide-y divide-border/30`, no rounded borders
- SEV indicator: 6px colored circle left of message
- `[SYS]` badge: grey — system-generated portfolio risk alert (not user-created)
- Click row: expands inline (36px → auto) to show full message + related news articles if applicable

### 11.3 ACK / Snooze / Dismiss

`[ACK ▾]` button on each row opens dropdown:
```
Acknowledge now
Snooze 1 hour
Snooze 4 hours
Snooze until tomorrow
Dismiss permanently
```
- Acknowledged: moved to collapsed "Acknowledged (N)" section at bottom, `opacity-50`
- Snoozed: hidden from feed until snooze expires, reappears at same severity level
- Dismissed: removed from feed permanently (stored in localStorage denylist)

### 11.4 Alert Rule Builder (slide-over)

`[+ Create Rule]` → slide-over panel (320px, right edge, doesn't obscure alerts):
```
CREATE ALERT RULE
──────────────────────────────────
Rule Type:   [Price Threshold ▾]
             [Volume Spike]
             [News Signal]
             [Portfolio Risk]

Entity:      [🔍 Search: AAPL...]

Condition:
  Price Threshold:
    Price [crosses ▾]  [$][150.00]  [Above / Below / Either]

  Volume Spike:
    Volume [>] [3][× 20-day avg]

  News Signal:
    Impact score [>] [80]

Notify via:  [✓ In-app]  [☐ Email]
Label:       [optional note...]

[Save Rule]  [Cancel]
```
- Saves to localStorage as `worldview-alert-rules` (future: `POST /v1/alerts/rules`)
- System rule creation is disabled (SYS rules are built-in)

### 11.5 Rule Management (slide-over)

`[⚙ Manage Rules]` → slide-over listing all user rules:
```
ACTIVE ALERT RULES (5)
──────────────────────────────────
AAPL > $180            ✓ on   [✎] [✕]
TSLA volume spike      ✓ on   [✎] [✕]
Portfolio risk > 15%   ✓ on   (system, read-only)

[+ Add Custom Rule]
──────────────────────────────────
SYSTEM RULES (4) — always active
  CONCENTRATION > 15%
  DRAWDOWN -5%
  DRAWDOWN -10%
  SECTOR_CONCENTRATION > 40%
```

### 11.6 System (Portfolio Risk) Alerts

Pre-built rules that fire based on live portfolio data — no backend required, computed client-side:
- `CONCENTRATION` — any position > 15% of total portfolio value
- `SECTOR_CONCENTRATION` — any GICS sector > 40% of portfolio
- `DRAWDOWN_5` — portfolio day P&L < -5%
- `DRAWDOWN_10` — portfolio day P&L < -10% from 20-day high water mark

All fire with `[SYS]` badge. Cannot be disabled (they are risk controls). User can snooze.

### 11.7 News Feed Tab Enhancements

Within the Alerts page News Feed tab (and instrument News tab):

**Category filter rail** (below tab bar):
```
[All] [Earnings] [M&A] [Regulatory] [Macro] [Analyst] [SEC Filings]
```
Active chip: `bg-primary/20 text-primary border border-primary/40`. Filters server-side via `?category=earnings`.

**My Holdings tab** (4th tab in Alerts page news):
- Queries news filtered client-side to user's portfolio + watchlist entity_ids
- Shows `[AAPL ▲]` holding badges per article (green/red based on current price direction)
- Empty state: "Connect a brokerage or add holdings to see your personalized news feed"

**Read/unread state**:
- IntersectionObserver marks articles as read on scroll-past
- Read articles: `opacity-60`
- Unread count badge on "News Feed" tab
- "Mark all read" button top-right

**Impact sort** option: `[RELEVANCE ▾] [IMPACT ▾] [NEWEST ▾]` — IMPACT uses `market_impact_score`

---

## 12. Color System (unchanged from v2, more rigorously applied)

The v2 Midnight Pro palette is correct. v3 applies it more strictly:

| Token | Hex | v2 application | v3 application |
|---|---|---|---|
| `--background` | `#09090B` | Page background | Same |
| `--card` | `#10141C` | Panels, sidebar | Same |
| `--muted` | `#18181B` | Hover rows, elevated | Same |
| `--border` | `#232A36` | All borders | Same + **required 1px visible border on every panel** |
| `--foreground` | `#D1D4DC` | Primary text | Same |
| `--muted-foreground` | `#787B86` | Labels, captions | Same |
| `--primary` | `#FFD60A` | CTA buttons, active nav | Same |
| `--positive` | `#26A69A` | Green gains | Same |
| `--negative` | `#EF5350` | Red losses | Same |
| `--warning` | `#F59E0B` | Amber alerts | Same |

**New v3 enforcement rules**:
- Every panel boundary MUST have `border border-border` (1px `#232A36`)
- The `gap-px` workspace seam IS the border (no additional border needed)
- Panel headers: `border-b border-border`
- Table rows: `divide-y divide-border/30` (not per-row rounded cards)
- NEVER: `rounded-lg`, `rounded-xl`, `rounded-md` on data surfaces
- OK: `rounded-[2px]` on badges, buttons, inputs

**New v3 color rules (from finance research)**:
- `text-primary` (`#FFD60A`) is for: interactive elements (buttons, active nav, links, CTA). **NEVER** for prices, P&L values, or financial data — those use `text-positive`/`text-negative`/`text-foreground` only
- `text-positive` and `text-negative` are **exclusively semantic** — price up/down, portfolio gain/loss. Not for generic success/error states (use `text-destructive` for errors).
- Bloomberg validated pattern: amber/yellow = labels/navigation; green/red = financial semantic data. Mixing these breaks financial legibility convention.
- Table header alignment: MUST match data alignment. If a price column is `text-right`, its column header is also `text-right`. Bloomberg treats misaligned headers as a first-tier credibility failure.
- ALL numeric values (prices, %, volumes, EPS, dates in tables) MUST use `font-mono tabular-nums`. Mixing sans-serif numbers in a mono-numeric column is a typography error (ADR-F-15).

---

## 12b. Chat Page — Institutional Enhancements

**Investigation session 3 decision**: Chat must not show a blank state to an institutional user. 4 enhancements required.

### Starter Questions (empty state)

When a conversation thread has no messages:
```
┌──────────────────────────────────────────────────────────────────────────┐
│  INTELLIGENCE CHAT                                                        │
│  Research-grade questions about companies, markets, and signals           │
│  ──────────────────────────────────────────────────────────────────────  │
│  ┌─────────────────────────────┐  ┌───────────────────────────────────┐  │
│  │ What are the key risks for  │  │ Compare MSFT and GOOGL cloud      │  │
│  │ [TICKER] next quarter?      │  │ revenue growth over 4 quarters    │  │
│  └─────────────────────────────┘  └───────────────────────────────────┘  │
│  ┌─────────────────────────────┐  ┌───────────────────────────────────┐  │
│  │ Summarize [TICKER]'s latest │  │ Recent insider transactions and   │  │
│  │ earnings call               │  │ what they signal                  │  │
│  └─────────────────────────────┘  └───────────────────────────────────┘  │
│  ┌─────────────────────────────┐  ┌───────────────────────────────────┐  │
│  │ What analyst consensus      │  │ Search SEC filings for            │  │
│  │ shows for [TICKER] in 2026? │  │ "supply chain" risk exposure      │  │
│  └─────────────────────────────┘  └───────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

- Card style: `rounded-[2px] border border-border hover:border-primary/40 p-3 cursor-pointer text-[12px]`
- Clicking a card: injects text into input (user can edit before sending)
- If `entity_id` context present (from URL param): `[TICKER]` is replaced with the entity ticker/name

### Entity Context Injection

When user navigates from `/instruments/[entityId]` to `/chat` (or `?entity_id=X` param):
- Show amber context badge above input: `[Context: AAPL — questions will focus on Apple Inc.]`
- Starter questions replace `[TICKER]` with "AAPL" (the entity name)
- Pass `entity_id` in the `/chat/stream` request body to bias RAG retrieval toward that entity's documents
- Badge style: `bg-primary/10 text-primary text-[11px] font-mono px-2 py-0.5 rounded-[2px]`

### Citation Enhancement

Current: `[1] Earnings Report — 87%`
Enhanced:
```
SOURCES
[1]  📄 SEC 10-Q · Apple Inc. (Oct 2024) · earnings · 87% match
[2]  📰 Reuters · "Apple supply chain concerns" · Nov 2024 · 92%
[3]  📊 Earnings Call · Q4 2024 Transcript · 78% match
```
- Source type icon: `📄` SEC filing, `📰` news, `📊` earnings call, `🕸` knowledge graph entity
- Source badge: SEC = `bg-primary/15`, news = `bg-muted`, earnings = `bg-positive/15`

### Thread Naming

Current: threads named from first message (truncated).
Enhanced:
- Double-click thread name in sidebar → `contentEditable` span, Enter to confirm
- Custom names persist in localStorage keyed by thread ID
- Renamed threads show a subtle `✎` icon at right edge of sidebar row

---

## 13. New Components Required

### 13.1 Shell components (new)
- `CollapsibleSidebar` — 48px collapsed / 220px expanded, persists to localStorage
- `WatchlistPanel` — live price list with watchlist switcher button + popover
- `AlarmsPanel` — compact alert rows filtered to portfolio + watchlist symbols
- `WorkspaceTabs` — workspace name tabs + add/close
- `WorkspacePanel` — resizable panel with header, type selector, group chip, controls
- `WorkspaceGrid` — CSS Grid with drag-to-resize (use `react-resizable-panels` or custom)
- `PanelGroupSelector` — colored chip dropdown for symbol linking
- `SymbolSelector` — inline symbol input in panel header (search + navigate)

### 13.2 Screener components (new)
- `ScreenerTable` — virtual-scroll table with 12 columns
- `ScreenerFilterBar` — collapsible inline filter row
- `ColumnPicker` — reorderable column selector dialog

### 13.3 Portfolio components (new)
- `SemanticHoldingsTable` — `<table>` element, 22px rows, 9 columns, sector enrichment from fundamentals
- `SectorAllocationPanel` — dual horizontal bar chart: by GICS sector + by asset type
- `TransactionsTable` — paginated list, type/date/ticker filters, DIVIDEND type support
- `WatchlistsTabPanel` — multi-watchlist tab bar with search-to-add and per-row remove
- `BrokerageConnectionCard` — status badge, sync actions, error expansion, disconnect
- `PredictionMarketsWidget` — top 3 Polymarket predictions with probability color coding

### 13.4 Instrument components (new)
- `SessionStatsStrip` — O/H/L/V/VWAP from last OHLCV bar (20px height)
- `CompactInstrumentHeader` — 56px two-row header (price row + split stats/description row)
- `InstrumentAISubheader` — amber sticky subheader with collapsible AI brief (replaces Brief tab)
- `CompactNewsRow` — 22px news row for list mode
- `InstrumentKeyMetrics` — 3-column key fundamentals strip for overview tab
- `InstrumentTopNews` — top 4 news rows for overview tab
- `OverviewLayout` — 5-zone grid: chart / session stats / timeframe bar / 3-col lower section
- `AnalystConsensusStrip` — Buy/Hold/Sell count bar for fundamentals tab
- `RevenueTrendSparklines` — 4-quarter mini bar chart for fundamentals tab

### 13.5 Workspace panel widgets (new — solves P0 blockers)
- `WorkspaceScreenerWidget` — screener top 20, no filter panel, 5 columns
- `WorkspaceChatWidget` — SSE chat input + history, 11px text
- `WorkspaceWatchlistWidget` — symbol list + live prices, 22px rows
- `WorkspaceBriefWidget` — morning brief collapsed to preview

### 13.6 Dashboard components (new/revised)
- `MarketSnapshotWidget` — futures + VIX + yield curve placeholder panel
- `PreMarketMoversWidget` — top gainers/losers from prior session screener data
- `SectorHeatmapWidget` — horizontal bar chart computed from screener sector data
- `PortfolioNewsWidget` — news filtered to held stock tickers
- `EarningsCalendarWidget` — placeholder with "coming soon" note

---

## 14. Implementation Waves

### Wave 0 — P0 Blockers (prerequisite before any PRD-0031 work)
1. Fix TypeScript typecheck errors (MorningBriefCard reduce types + gateway.ts MorningBrief)
2. Implement WorkspaceScreenerWidget + WorkspaceChatWidget (replace placeholders)
3. Capture browser screenshots, validate zero console errors
4. Fix screener filter collapse
5. Create SessionStatsStrip component

**Estimated effort**: 1-2 days. Must be committed as its own wave.

### Wave 1 — New Shell (collapsible sidebar + new TopBar)
Files: `app/(app)/layout.tsx`, `components/shell/TopBar.tsx`, `components/shell/CollapsibleSidebar.tsx` (new), `components/shell/WatchlistPanel.tsx` (new), `components/shell/AlarmsPanel.tsx` (new)
- Replace text sidebar with CollapsibleSidebar (48px collapsed / 220px expanded)
- Sidebar: nav items (icons + labels when expanded), watchlist section (live prices, switcher), alarms section (portfolio + watchlist filtered)
- TopBar: 36px height, UTC clock, workspace selector, compact search
- WorkspaceTabs component (visible only on /workspace)
- Collapse/expand toggle in sidebar footer; state to localStorage

### Wave 2 — Workspace Redesign (resizable panels + named workspaces)
Files: `app/(app)/workspace/page.tsx`, `components/workspace/` (new directory)
- WorkspaceGrid with react-resizable-panels or CSS resize
- Named workspace persistence to localStorage
- Workspace add/rename/delete
- Panel type selector (10 types)
- Symbol linking system
- WorkspaceScreenerWidget, WorkspaceChatWidget, WorkspaceWatchlistWidget

### Wave 3 — Screener Full Redesign
Files: `app/(app)/screener/page.tsx`, `components/screener/ScreenerTable.tsx`
- 12 columns (handle backend-missing fields gracefully)
- Virtual scroll (react-virtual)
- Collapsible inline filter bar
- Column picker

### Wave 4 — Portfolio Full Redesign
Files: `app/(app)/portfolio/page.tsx`, `components/portfolio/`
- Revised 6 KPI tiles: Total Value | Day P&L | Unrealised P&L | Top Gainer | Top Loser | # Positions
- SemanticHoldingsTable (`<table>` element, 22px rows, 9 cols with sector enrichment)
- SectorAllocationPanel (dual bar chart: by sector + by type)
- TransactionsTable (BUY/SELL/DIVIDEND filters + date range + pagination)
- WatchlistsTabPanel (multi-watchlist tabs + search-to-add + per-row remove)
- BrokerageConnectionCard (status + sync + error expansion)
- Backend fix: gateway.ts enable DIVIDEND transaction type mapping

### Wave 5 — Instrument Detail Refinement
Files: `app/(app)/instruments/[entityId]/page.tsx`, `components/instrument/`
- CompactInstrumentHeader (56px two-row with description in right half of row 2)
- InstrumentAISubheader (sticky amber brief below header — replaces Brief tab)
- Remove Brief tab from tab bar
- SessionStatsStrip below chart
- OverviewLayout (5-zone: chart + stats + timeframe + 3-col lower section)
- InstrumentKeyMetrics + InstrumentTopNews in overview lower section
- CompactNewsRow (22px list mode) for News tab
- News tab: date range + sentiment filter
- Intelligence tab severity count strip + date range filter
- Fundamentals tab: AnalystConsensusStrip + RevenueTrendSparklines above grid

### Wave 6 — Row Height + Typography Global Sweep
All data surface files — apply 22px rows and 11px text system-wide.

### Wave 7 — Dashboard Trader Morning Routine Layout
Files: `app/(app)/dashboard/page.tsx`, `components/dashboard/`
- CSS Grid 12-column layout following the 5-priority morning routine order
- MarketSnapshotWidget (placeholder with `—` values for futures data)
- PreMarketMoversWidget (proxy from screener `daily_return`)
- SectorHeatmapWidget (computed from screener sector groups)
- PortfolioNewsWidget (news filtered client-side to held tickers)
- EarningsCalendarWidget (placeholder — data coming soon)
- MorningBriefCard: full width, collapsible, amber left accent border
- All widgets: 22px row heights, 24px panel headers
- Remove AI Signals widget (stub — no data)
- Remove Prediction Markets from dashboard (workspace panel only)

### Wave 8 — QA, Screenshots, Browser Validation
- Playwright tests for all major routes
- Screenshots in `docs/screenshots/v3/`
- Console error validation
- Responsive checks at 1280/1440/1920px

---

## 15. Backend/API Dependencies

| Feature | Requirement | Priority | Blocker |
|---|---|---|---|
| Revenue TTM in screener | Add to `POST /v1/fundamentals/screen` response | P2 | No (show "—" initially) |
| Beta in screener | Add to screener response | P2 | No (show "—" initially) |
| `quote.open/high/low` | Currently not in Quote type — use last OHLCV bar instead | N/A | No |
| `quote.volume` | Already in Quote type ✓ | — | — |
| Watchlist panel | Need `GET /v1/portfolios/{id}/watchlist` or equivalent | P1 | No (use screener as fallback) |
| Portfolio Beta KPI | Compute client-side: Σ(holding_weight × instrument_beta) | — | Requires beta per holding from fundamentals |

---

## 16. Acceptance Criteria (measurable)

| Metric | Target | How to verify |
|---|---|---|
| Workspace panels | Up to 16 | UI test |
| Workspace resize | Drag border between panels | Playwright |
| Named workspaces | Save/load/delete by name | Playwright |
| Screener visible columns | ≥12 at 1440px | Screenshot |
| Screener row height | 22px | CSS class check |
| Screener row count visible | ≥30 rows at 1080p | Screenshot |
| Portfolio holdings | `<table>` element | axe/RTL test |
| Portfolio holdings row height | 22px | CSS class check |
| Portfolio KPI tiles | 6 tiles (Total/Day/Unrealised/TopGainer/TopLoser/Positions) | RTL test |
| Portfolio holdings sector column | Visible (or skeleton) | Screenshot |
| Portfolio sector allocation | Visible for seeded portfolio | Screenshot |
| Portfolio watchlists | Multi-tab, search-to-add working | Playwright |
| Portfolio transactions | DIVIDEND type visible if available | Playwright |
| Portfolio brokerages | Connection card with status badge | Screenshot |
| Dashboard sector heatmap | Row 2 position (above portfolio summary row) | Screenshot |
| Dashboard prediction markets | Visible widget (data or placeholder) | Screenshot |
| `text-primary` on P&L values | DOES NOT appear | CSS audit |
| Instrument header height | ≤56px total (2-row with description) | getBoundingClientRect |
| SessionStatsStrip | Visible below chart | Playwright |
| InstrumentAISubheader | Visible below header, above tabs | Playwright |
| Instrument description | Visible in header row 2 right half | Screenshot |
| Brief tab | Does NOT exist (replaced by subheader) | RTL test |
| Overview: 5 zones | Chart + Stats + Timeframe + Metrics + News + Graph | Screenshot |
| Sidebar collapsed width | 48px | getBoundingClientRect |
| Sidebar expanded width | 220px | getBoundingClientRect |
| Watchlist in sidebar | Shows live prices (≥1 item or empty state) | Playwright |
| Alarms in sidebar | Shows filtered alerts or empty state | Playwright |
| Dashboard morning brief | Full width, collapsible, amber accent | Screenshot |
| Dashboard pre-market panel | Visible (proxy or placeholder) | Screenshot |
| TopBar height | 36px | getBoundingClientRect |
| Left rail width | 48px (collapsed) / 220px (expanded) | getBoundingClientRect |
| TypeScript typecheck | Exit 0 | `pnpm run typecheck` |
| All unit tests pass | 315+ tests | `pnpm test` |
| Zero console errors (all routes) | 0 | Playwright |
| Screenshots committed | ≥8 routes | `docs/screenshots/v3/` |

---

## 17. Out of Scope for PRD-0031

- New S9 API endpoints (except what's needed for workspace widgets)
- Mobile/tablet responsive layout (desktop-first terminal, mobile is read-only)
- Light mode (terminal is dark-only; light mode deferred)
- Real-time price streaming via WebSocket for non-alert data
- Options chain panel
- Order entry panel (future PRD — execution is out of scope for Worldview v1)

---

## 18. Design Files

Canvas: `apps/worldview-web/designs/v3-terminal-redesign.pen` (to be created in design session)

Competitive reference collected in: `docs/ui/competitive-design-research.md`

---

---

## 19. Investigation Session (2026-04-25)

**Investigation report**: `docs/audits/2026-04-25-investigate-prd0031-enhancements.md`

Decisions made in the investigation session (D-1 through D-5) are incorporated into this PRD:

| Decision | Section updated | Summary |
|---|---|---|
| D-1 Left Rail | §4.3 | Collapsible sidebar (48px/220px) with embedded watchlist + alarms |
| D-2 Dashboard | §10 | Trader morning routine layout replacing generic widget grid |
| D-3 Instrument header | §9.1, §9.2 | Right half of header shows company description; AI brief as sticky subheader |
| D-4 Overview tab | §9.4 | 5-zone layout: chart + stats strip + timeframe + key metrics + news + graph |
| D-5 Other tabs | §9.5–9.7 | Fundamentals: analyst consensus + revenue trend; News: date/sentiment filter; Intelligence: severity strip + date filter; Brief tab removed |

**Investigation Session 2 (2026-04-25)** — `docs/audits/2026-04-25-investigate-prd0031-enhancements-2.md`:

| Decision | Section updated | Summary |
|---|---|---|
| D-6 News + Intelligence | §9.3 tabs | KEEP SEPARATE — different use cases, no article backlink in contradictions API |
| D-7 Dashboard swap | §10.2 | Sector Heatmap moves to row 2 (replaced Pre-Market Movers); Pre-Market Movers + Prediction Markets go to row 3 |
| D-8 Design system | §12 | Palette VALIDATED vs Bloomberg/TradingView; new rule: `text-primary` NEVER on P&L values; column header alignment must mirror data alignment |
| D-9 Portfolio full spec | §8 | Full 4-tab spec: Holdings 9-col + sector panel, Transactions + DIVIDEND type, Watchlists multi-tab, Brokerages cards; revised KPIs |
| D-10 KPI strip | §8.2 | Replaced Realized P&L/Beta/Sharpe with Top Gainer/Top Loser/# Positions (achievable with current backend) |

**Investigation Session 3 (2026-04-25)** — `docs/audits/2026-04-25-investigate-prd0031-enhancements-3.md`
Context: BlackRock executive presentation readiness.

| Decision | Section updated | Summary |
|---|---|---|
| D-11 Portfolio tabs | §8 (rationale) | KEEP TABS — Bloomberg PORT, Aladdin, tastytrade, IBKR, Fidelity ATP all use tabs; confirmed correct |
| D-12 Fundamentals | §9.5 | 4 new sections: Analyst Consensus, Revenue Trend, Debt & Credit, Cash Flow; Valuation gains "vs Sector" context |
| D-13 Chat | §12b (new) | Starter questions, entity context injection, citation type badges, thread renaming |
| D-14 Intelligence | §9.7 | market_impact_score bars, DEEP/MED/LIGHT badges, novelty indicators, temporal histogram |
| D-15 News | §11.7 | Category filter rail, My Holdings news tab, read/unread state, holdings mention badges |
| D-16 Alerts | §11 | Severity-grouped display, ACK/snooze/dismiss, Alert Rule Builder slide-over, System risk alerts, Rule Management panel |
| D-17 Workspace | §5 | All 10 panel type specs, 4 default presets, react-resizable-panels for resize, symbol linking context |

*PRD-0031 updated 2026-04-25. Begin with Wave 0 prerequisite fixes, then Wave 1 shell redesign.*
