---
id: PLAN-0027-DESIGN
prd: PRD-0027
title: "Frontend MVP UI — Canvas Design Completion (6 Remaining Gaps)"
status: in-progress
created: 2026-04-14
updated: 2026-04-14
waves: 6
tasks: 28
---

# PLAN-0027-DESIGN: Canvas Design Completion

## Overview

**PRD Reference**: [PRD-0027](../specs/0027-frontend-mvp-ui-design.md)
**Canvas File**: `apps/frontend/designs/worldview-mvp_v1.pen`
**Design System**: `apps/frontend/designs/DESIGN.md`
**Goal**: Complete all 6 remaining canvas gaps identified in the 2026-04-14 gap audit. Every wave produces verified, screenshot-validated canvas output in `worldview-mvp_v1.pen`.

**Gap audit summary (2026-04-14)**:
| Gap | Frame | Priority | Status |
|-----|-------|----------|--------|
| GAP-4: State F — Candlestick + Drawing Tools + Amber | `sL0wd` | 1 | Built, 3 quality failures |
| GAP-3: State D — News Tab | `jZEVF` | 2 | Empty frame |
| GAP-1: State B — Fundamentals Tab | `VEVln` | 3 | Empty frame |
| GAP-2: State C — Intelligence Tab | `M1GXQ` | 4 | Empty frame |
| GAP-6: Portfolio Page | `57eKB` | 5 | Empty or incomplete |
| GAP-5: Intelligence/News Page | `tUPQd` | 6 | Empty or incomplete |

---

## Execution Order

All waves are **sequential** (each builds on or uses components from prior waves).

```
Wave 1 (State F fix) ──→ Wave 2 (State D) ──→ Wave 3 (State B)
                                                        │
                                               Wave 4 (State C)
                                                        │
                                               Wave 5 (Portfolio)
                                                        │
                                               Wave 6 (Intelligence/News)
```

---

## Pre-Read (agent must read before ANY wave)

1. `apps/frontend/designs/DESIGN.md` — complete design system, token hex values, component specs, canvas registry
2. `docs/specs/0027-frontend-mvp-ui-design.md` — PRD, section-by-section functional requirements
3. `docs/plans/0027-design-canvas-plan.md` — this file (current wave status)

**Critical pencil.dev invariants** (memorise before touching the canvas):
- `C("WoVQh", parent, {...})` MUST be used for all frame children — `I()` inherits `opacity:0.5` and `width:8` from WoVQh source
- `layout:"horizontal"` is NOT valid — horizontal is the default (omit `layout` for horizontal rows)
- `layout:"vertical"` IS valid — required to stack children top-to-bottom
- After inserting frames, apply the phantom offset fix: `U(frame, {padding:8})` then `U(frame, {padding:0})` in the NEXT batch
- When changing a frame's layout mode, recreate via `C()` + move children + `D(old)` — never use `U()` to switch layout type
- Explicit hex values required (e.g. `fill:"#10141c"` not `fill:"$card"`)

**Color tokens** (use these exact hex values, never Tailwind defaults):
```
#080A0E  background    #10141C  card/panel    #181D28  elevated
#232A36  border        #2E3847  border-strong
#D1D4DC  foreground    #787B86  muted-foreground  #4C5260  dim
#0EA5E9  primary       #0EA5E920 primary-dim
#26A69A  positive      #EF5350  negative      #F59E0B  warning
#F0C040  amber (AI only)        #F0C04018     amber-dim
```

---

## Wave 1: State F — Candlestick Rework + Drawing Tools Fix

**Goal**: Fix 3 quality failures in `sL0wd` (Full-Screen Graph tab): proper candlestick wick structure, visible drawing tools icons, verified amber MA50 + price label.
**Depends on**: none
**Frame**: `sL0wd` (inside `aTIbj`, y=4820)

### Context

The State F frame was built but has quality failures:
1. **Candlestick wicks missing**: bodies are plain filled rectangles. TradingView standard requires: wick line (2px wide) above body (high→open), rectangular body (open→close, 12px wide), wick line below body (close→low). Color by `close > open` = green, else red.
2. **Drawing tools sidebar (jayD2) icons possibly invisible**: built with `C()` but icon text nodes may have inherited `opacity:0` from WoVQh template. Must `batch_get` all children of jayD2 and `U()` any node with `opacity:0` or `opacity:0.5` back to `opacity:1`.
3. **Amber colors need screenshot verification**: MA50 line (fill:`#f0c040`) and price label (fill:`#f0c040`) should be visible. If they have opacity < 0.7 from WoVQh inheritance, update.

### Tasks

| ID | Task | Acceptance Criteria |
|----|------|---------------------|
| T-1-01 | `batch_get(["sL0wd"])` + `get_screenshot()` — audit current state | Screenshot captured, identify candle, wick, and sidebar nodes |
| T-1-02 | Fix candlestick wicks: for each candle, add upper wick (2×N px frame `fill:"#26a69a"` or `fill:"#ef5350"`, x=body_center, y above body to high) and lower wick (same, below body to low) | Each candle has 3 nodes: upper wick + body + lower wick |
| T-1-03 | Fix drawing tools sidebar: `batch_get(["jayD2"])` → find all icon nodes → `U()` any with opacity<1 to `{opacity:1}` | All 6 icon buttons visible at opacity:1 |
| T-1-04 | Verify amber: `batch_get` MA50 line node + price label node → confirm `fill:"#f0c040"`, `opacity:0.7–1.0` | MA50 amber line visible on screenshot |
| T-1-05 | `get_screenshot()` final validation | Screenshot shows proper TradingView-style candles with wicks, visible toolbar icons, amber MA50 |

### Validation Gate
- [ ] Screenshot shows candles with distinct upper wick, body, lower wick (3-part structure)
- [ ] Drawing tools sidebar shows 6 visible icons
- [ ] MA50 line is amber (`#f0c040`), clearly distinguishable from price bars
- [ ] Price label `$875.40` is amber and readable
- [ ] No `opacity:0` or `opacity:0.5` nodes remaining in chartBody or jayD2

### Candle Anatomy Reference (implement for ALL 40 candles in chartBody)
```
For each candle at x=40+i*32 (12px body, centered: body_x = x+10, body_cx = x+16):
  Upper wick: width:2, x:body_cx-1, y:high_y,        height:open_y-high_y,  fill:<color>
  Body:       width:12, x:body_cx-6, y:min(open,close), height:abs(close-open), fill:<color>, cornerRadius:1
  Lower wick: width:2, x:body_cx-1, y:max(open,close), height:low_y-max(open,close), fill:<color>
  Color rule: close > open → #26a69a (green); close <= open → #ef5350 (red)
```

---

## Wave 2: State D — News Tab Assembly

**Goal**: Build the complete News Tab frame (`jZEVF`) inside the Company Detail canvas (`aTIbj`).
**Depends on**: Wave 1 (stable canvas state)
**Frame**: `jZEVF` (inside `aTIbj`, y≈2930, 1440×900)

### Context

The `jZEVF` frame is currently empty. The component specs exist in DESIGN.md (State D section, "News Article Row" + "News Filter Bar"). The canonical article row clone source is `jJ9GD`. The filter bar spec uses node `Y7cr5`.

Per DESIGN.md, the completed State D layout is:
```
TopNav (oahZK pattern, y=0, h=44)
Sidebar (D4pfu, x=0, y=44, w=200, h=856)
Tab bar (copy from State A wE7LT, 5 tabs, "News" active, y=44, x=200, h=36)
Filter bar (40px, y=80, x=200, w=1040): [By Relevance ●] [By Date] | [From:] date input [>] date input | [spacer] | [DEEP●] [MED●] [LIGHT●]
Article list: 5 article rows × 88px (y=120–560, x=200, w=1040)
Pagination footer (40px, y=560, x=200, w=1040)
```

### Tasks

| ID | Task | Acceptance Criteria |
|----|------|---------------------|
| T-2-01 | `batch_get(["jZEVF", "jJ9GD", "Y7cr5"])` — audit frame and component states | Confirm jZEVF is empty; jJ9GD is article row clone source |
| T-2-02 | Add TopNav: `C("oahZK", "jZEVF", {x:0, y:0, width:1440})` | Nav bar visible at top of frame |
| T-2-03 | Add Sidebar: `C("D4pfu", "jZEVF", {x:0, y:44, height:856})` with Intelligence nav item active | Sidebar visible, left column |
| T-2-04 | Add Tab bar: copy from State A's tab bar; update active tab to "News" | 5 tabs: [Overview] [Fundamentals] [Intelligence] [News●] [Chat] |
| T-2-05 | Build filter bar (40px, y=80, x=200, w=1040): sort chips [By Relevance●][By Date], date range inputs, tier toggles [DEEP●][MED][LIGHT] | Filter bar matches DESIGN.md spec; active chips use `$primary-dim` fill + `$primary` stroke |
| T-2-06 | Clone 5 article rows from `jJ9GD`: `C("jJ9GD", "jZEVF", {y:120+i*88, x:200, width:1040})` for i=0..4 with varied content | 5 88px article rows visible with score chip, tier badge, impact chip, headline, excerpt, entity chips |
| T-2-07 | Add pagination footer (40px, y=560, x=200, w=1040): "Load 20 more >" centered button | Footer visible at bottom of list |
| T-2-08 | Apply phantom offset fix to jZEVF and any new vertical containers | Children render at correct y positions |
| T-2-09 | `get_screenshot()` final validation | Full State D tab visible: filter bar + article feed + footer |

### Validation Gate
- [ ] Frame `jZEVF` has TopNav, Sidebar, tab bar, filter bar, 5 article rows, pagination footer
- [ ] "News" tab is active (2px `$border-strong` bottom indicator)
- [ ] At least 3 article rows show all 4 elements: score chip + tier badge + impact chip + headline
- [ ] Filter bar shows DEEP/MED/LIGHT tier toggles (all active state by default)
- [ ] Screenshot confirms layout, no phantom offset, correct colors

### Article Row Content for 5 Rows
```
Row 0: score:0.91, tier:DEEP, impact:⬆+1.8%, src:"Reuters · 2h", headline:"Apple Reports Record iPhone 15 Sales in Q4, Beats Analyst Estimates"
Row 1: score:0.74, tier:MED,  impact:–,      src:"Bloomberg · 4h", headline:"Fed Chair Powell Signals Further Rate Cuts Possible in 2026"
Row 2: score:0.82, tier:DEEP, impact:⬆+2.1%, src:"WSJ · 6h",       headline:"NVIDIA H100 Supply Constraints Expected Through Q2, Says CEO"
Row 3: score:0.61, tier:MED,  impact:⬇-0.9%, src:"FT · 8h",        headline:"Berkshire Hathaway Reduces Apple Position by 12% in Q3"
Row 4: score:0.48, tier:LIGHT,impact:–,      src:"Seeking Alpha · 1d", headline:"Technical Analysis: AAPL Support at $165 Key Level"
```

---

## Wave 3: State B — Fundamentals Tab Build

**Goal**: Build the complete Fundamentals Tab frame (`VEVln`) inside the Company Detail canvas (`aTIbj`).
**Depends on**: Wave 2 (stable canvas state with established patterns)
**Frame**: `VEVln` (inside `aTIbj`, y≈1010, 1440×900)

### Context

`VEVln` is currently empty. The Fundamentals tab shows financial data in 5 accordion groups. Per DESIGN.md and PRD-0027 §F-05 Fundamentals Tab:

```
TopNav (y=0, h=44)
Sidebar (x=0, y=44, w=200, h=856) — with "Company Detail" active
Tab bar (y=44, x=200, h=36) — "Fundamentals" active
Compact chart (y=80, x=200, w=1240, h=200): OHLCV chart at 200px height
Period selector row (y=280, x=200, h=36): [Annual●] [Quarterly] [TTM] ghost button group
Accordion group 1 (Income & Growth — EXPANDED, y=316, w=1240)
Accordion groups 2-5 (COLLAPSED, each h=36)
```

### Tasks

| ID | Task | Acceptance Criteria |
|----|------|---------------------|
| T-3-01 | `batch_get(["VEVln"])` — confirm empty, note y-offset | Frame confirmed empty |
| T-3-02 | Add TopNav + Sidebar (copy from State A/D pattern) + Tab bar with "Fundamentals" active | Nav + sidebar + tab bar visible |
| T-3-03 | Add compact chart area (y=80, x=200, w=1240, h=200): `fill:"#10141c"`, border-bottom `$border` 1px. Inside: horizontal grid lines (5 × 1px `fill:"#232a36"`), timeframe bar (32px, top), simple line chart (y=96 after timeframe), y-axis labels (IBM Plex Mono 11px `$dim`, right side) | Compact chart placeholder visible at 200px height |
| T-3-04 | Add period selector row (y=280, x=200, w=1240, h=36): `fill:"#181d28"`, border-bottom `$border` 1px. Left: "Annual" active ghost-button + "Quarterly" + "TTM" (each h:28, cornerRadius:4). Left label "PERIOD:" IBM Plex Sans 10px `$muted-foreground` | Period selector visible with 3 toggle buttons |
| T-3-05 | Build expanded Income & Growth accordion (y=316, x=200, w=1240): header row 36px `fill:"#181d28"` + "▼ INCOME & GROWTH" IBM Plex Sans 13px 500 `$foreground` + chevron down. Column header row (32px): METRIC \| Q1 2026 \| Q4 2025 \| Q3 2025. 5 data rows (32px each, alt `$card`/`$background`): Revenue, Gross Profit, Operating Income, Net Income, EPS | Accordion section with 5 data rows + column headers visible |
| T-3-06 | Add 4 collapsed accordion sections below (each 36px): "▶ BALANCE SHEET", "▶ CASH FLOW", "▶ VALUATION", "▶ COMPANY & OWNERSHIP" — all `fill:"#181d28"`, IBM Plex Sans 11px `$muted-foreground`, border-bottom `$border` 1px | 4 collapsed sections visible as clickable header rows |
| T-3-07 | Apply phantom offset fix; `get_screenshot()` | Full Fundamentals tab: compact chart + period selector + 1 expanded + 4 collapsed sections |

### Data for Income & Growth Table
```
Column headers: METRIC | Q1 2026 | Q4 2025 | Q3 2025 (IBM Plex Sans 10px UPPERCASE $muted-foreground)

Row 1: Revenue      | $119.6B | $124.3B | $121.8B  (right-aligned IBM Plex Mono 12px $foreground)
Row 2: Gross Profit | $55.3B  | $58.1B  | $56.7B
Row 3: Op. Income   | $31.2B  | $34.8B  | $33.1B
Row 4: Net Income   | $26.9B  | $29.4B  | $27.6B
Row 5: EPS          | $1.73   | $1.89   | $1.77   | + YoY% col: $positive if positive, $negative if neg (IBM Plex Mono 11px)
```

### Validation Gate
- [ ] Frame `VEVln` has all 7 layers: TopNav, Sidebar, tab bar, compact chart, period selector, expanded Income section, 4 collapsed sections
- [ ] "Fundamentals" tab is active (bottom indicator)
- [ ] Period selector has 3 toggle buttons: Annual (active), Quarterly, TTM
- [ ] Income & Growth has column headers + 5 data rows with monospace numbers
- [ ] 4 collapsed sections stacked below with chevron-right icon and muted text

---

## Wave 4: State C — Intelligence Tab Build

**Goal**: Build the complete Intelligence Tab frame (`M1GXQ`) inside the Company Detail canvas.
**Depends on**: Wave 3 (stable canvas, established component patterns)
**Frame**: `M1GXQ` (inside `aTIbj`, y≈1970, 1440×900)

### Context

`M1GXQ` is currently empty. Per DESIGN.md §"State C — Intelligence Tab" and PRD-0027 §F-05 Intelligence Tab:

```
TopNav (y=0, h=44)
Sidebar (x=0, y=44, w=200, h=856)
Tab bar (y=44, x=200, h=36) — "Intelligence" active
Content area (y=80, x=200, w=1240, h=820):
  Left column  (x=200, w=860, h=820): Entity Graph (304px) + Recent Claims (180px) + Temporal Events (168px) + overflow
  Right column (x=1060, w=380, h=820): Similar Instruments + Contradictions + Prediction Market Signals
```

### Tasks

| ID | Task | Acceptance Criteria |
|----|------|---------------------|
| T-4-01 | `batch_get(["M1GXQ"])` — confirm empty frame | Empty confirmed |
| T-4-02 | Add TopNav + Sidebar (copy from prior state) + Tab bar with "Intelligence" active | Nav + sidebar + "Intelligence" tab active |
| T-4-03 | Build left column container (x=200, y=80, w=860, h=820, `fill:"#10141c"`, border-right `$border` 1px) | Left column frame |
| T-4-04 | Build Entity Graph section in left column (top 304px): graph panel header "ENTITY GRAPH" (28px elevated), controls row (36px: hop-depth chips [2●][3], min-confidence, filter chips [Companies✓][People✓][Funds✓]), graph canvas (240px, layout:none) with 6 entity nodes + connector lines + legend | Graph panel with 6 nodes: central AAPL (48px `$primary`), Tim Cook (32px `$positive`), Berkshire (32px `$amber`), TSMC (28px `$primary`), MSFT (28px `$primary`), Foxconn (24px `$elevated`) |
| T-4-05 | Build Recent Claims section in left column (y=304, h=180): header "▼ RECENT CLAIMS (10)" (36px elevated) + 3 claim rows (48px each): POSITIVE/NEUTRAL/NEGATIVE badge + claim text + 60px confidence bar | 3 claim rows with colored sentiment badges |
| T-4-06 | Build Temporal Events section in left column (y=484, h=168): header "▼ TEMPORAL EVENTS (8)" (36px elevated) + 3 event rows (44px each): event type badge (earnings/product/executive) + event text + right-aligned date | 3 event rows visible |
| T-4-07 | Build right column container (x=1060, y=80, w=380, h=820, `fill:"#10141c"`) | Right column frame |
| T-4-08 | Build Similar Instruments panel in right column (y=0, h=233): label "SIMILAR INSTRUMENTS" + column header row + 3 data rows (Ticker IBM Plex Mono `$primary` | Name fill_container | Score right) + footer "« Compare in Screener →" | 3 similar instrument rows + compare footer |
| T-4-09 | Build Contradictions panel (y=233, h=134): label "CONTRADICTIONS" `$negative` + [STRONG] badge + 2-line contradiction text | Contradictions panel with red label + badge + text |
| T-4-10 | Build Prediction Market Signals panel (y=367, h=186): label "PREDICTION MARKET SIGNALS" + 2 probability rows (question + 120px progress bar + %) + footer "Source: Polymarket · updated 4m ago" | 2 probability bars with sky-blue fill |
| T-4-11 | Apply phantom offset fix; `get_screenshot()` | Full Intelligence tab: entity graph with nodes + both columns populated |

### Entity Graph Node Positions (within 1360×240px graph canvas)
```
AAPL central:  x:506, y:100, 48×48px, fill:"#0ea5e9", label:"AAPL" IBM Plex Mono 10px
Tim Cook:      x:724, y:30,  32×32px, fill:"#26a69a", label:"Tim Cook"
Berkshire:     x:290, y:20,  32×32px, fill:"#f0c040", label:"Berkshire"
TSMC:          x:250, y:170, 28×28px, fill:"#0ea5e9", label:"TSMC"
MSFT:          x:766, y:155, 28×28px, fill:"#0ea5e9", label:"MSFT"
Foxconn:       x:518, y:195, 24×24px, fill:"#181d28", stroke:"#232a36" 1px, label:"Foxconn"
Legend (bottom-left, y=220): 6px circles in $primary/$positive/$amber + IBM Plex Sans 10px $muted-foreground labels
```

### Validation Gate
- [ ] "Intelligence" tab is active
- [ ] Entity graph shows 6 nodes in correct colors (blue=company, green=person, amber=fund)
- [ ] Recent Claims section has 3 rows with POSITIVE (dark-green bg), NEUTRAL, NEGATIVE badges
- [ ] Temporal Events section has 3 rows with type badges (earnings=primary, product=elevated, executive=warning)
- [ ] Right column has all 3 panels: Similar Instruments + Contradictions + Prediction Markets
- [ ] Screenshot confirms two-column layout, no overlap, correct colors

---

## Wave 5: Portfolio Page Build

**Goal**: Verify and build the complete Portfolio page (`57eKB`).
**Depends on**: Wave 4
**Frame**: `57eKB` (standalone page canvas, 1440×900)

### Context

The canvas registry in DESIGN.md claims `57eKB` was completed (S14 ✅ 2026-04-14), but the 2026-04-14 gap audit confirms it is NOT BUILT (P6 Portfolio ⬜ in header). This wave must first inspect the actual state and then build whatever is missing.

Per DESIGN.md §"Portfolio Summary Row" and §"StrategyCard" + PRD-0027 §F-07:
```
TopNav (y=0, h=44)
Sidebar (x=0, y=44, w=200) — Portfolio nav item active
Portfolio Summary Row (y=44, x=200, w=1240, h=56): 5 metric cells
StrategyCard row (y=124, x=216): 3 cards × 240×120px at gap:16
Tab bar (y=260, x=200, w=1240, h=36): [Holdings●][Transactions][Analytics][Watchlists][Settings]
Holdings table (y=296, x=200, w=1240): column headers + 3 rows (AAPL/NVDA/TSLA) + subtotal row
```

### Tasks

| ID | Task | Acceptance Criteria |
|----|------|---------------------|
| T-5-01 | `batch_get(["57eKB"])` + `get_screenshot()` — audit current state | Determine what exists vs what is missing |
| T-5-02 | Add or verify TopNav + Sidebar with Portfolio nav item active | TopNav + Portfolio-active sidebar |
| T-5-03 | Build Portfolio Summary Row (y=44, x=200, w=1240, h=56): 5 cells separated by vertical `$border` 1px dividers: Total Value ($47,320.50 Mono 20px) | Today P&L (+$1,243.18 16px $positive + +2.69% 11px) | Unrealized P&L (+$8,450.23 + +21.7%) | IRR (+18.7%) | Positions (12) | 5-cell summary row at correct height |
| T-5-04 | Build 3 StrategyCards (y=124, x=216/472/728, w=240, h=120): active card `$primary-dim` fill + `$primary` 1px stroke; inactive `$card` + `$border`. Each: strategy name (9px CAPS), total value (Mono 18px), daily P&L (Mono 12px), position count (11px $dim), sparkline frame (80×20px top-right) | 3 strategy cards: 1 active (primary), 2 inactive |
| T-5-05 | Build tab bar (y=260, x=200, w=1240, h=36): [Holdings●][Transactions][Analytics][Watchlists][Settings] — Holdings active | Holdings tab active with 2px bottom indicator |
| T-5-06 | Build Holdings table (y=296, x=200, w=1240): column header row (32px elevated): ★ \| TICKER \| COMPANY \| SECTOR \| QTY \| AVG COST \| CURRENT \| UNREAL.$ \| UNREAL.% \| DAILY% \| WEIGHT% \| ACTIONS. Then 3 data rows (AAPL/NVDA/TSLA) + subtotal footer row | Holdings table with column headers + 3 data rows + subtotal |
| T-5-07 | Apply phantom offset fix; `get_screenshot()` validation | Full Portfolio page: summary row + 3 strategy cards + tab bar + holdings table |

### Portfolio Data for 3 Holdings Rows
```
Row 1 AAPL: ★ | AAPL | Apple Inc. | Tech | 50 | $168.30 | $173.42 | +$256.00 | +3.04% | +0.58% | 28.3% | [+ − ✕]
Row 2 NVDA: ★ | NVDA | NVIDIA Corp. | Tech | 10 | $752.80 | $875.40 | +$1,226.00 | +16.3% | +1.23% | 21.4%
Row 3 TSLA:   | TSLA | Tesla Inc.   | Auto |  8 | $183.00 | $177.20 | -$46.40    | -3.17% | -0.81% | 8.7%
Subtotal row: fill:$elevated, "Portfolio Total" fill_container | | | | | | | +$3,580.40 | +8.16% | +0.44%
```

### Validation Gate
- [ ] TopNav + Portfolio-active sidebar present
- [ ] 5-metric summary row at y=44 with correct monospace values and P&L in `$positive`
- [ ] 3 strategy cards at y=124, active card highlighted in `$primary` border
- [ ] Holdings tab active with 5 tabs visible
- [ ] Holdings table has column headers + 3 data rows + subtotal (AAPL green, TSLA red)
- [ ] Weight % column values visible

---

## Wave 6: Intelligence/News Page Build

**Goal**: Verify and build the complete Intelligence/News page (`tUPQd`).
**Depends on**: Wave 5
**Frame**: `tUPQd` (standalone page canvas, 1440×900)

### Context

The canvas registry claims `tUPQd` was completed (S12 ✅ 2026-04-14), but the gap audit confirms it is NOT BUILT (P6 Intelligence/News ⬜ in header). Inspect and build all missing content.

Per DESIGN.md §"Intelligence Tab Strip" and §"Intelligence Feed Items" + §"TRENDING ENTITIES Sidebar":
```
TopNav (y=0, h=44)
Sidebar (x=0, y=44, w=200) — Intelligence nav item active
3-tab strip (y=44, x=200, w=1240, h=36): [Top Today●][By Entity][By Impact] — $border-strong bottom 2px on active
Article feed (y=80, x=200, w=1000): 5× 88px enriched article cards
TRENDING ENTITIES sidebar (x=1200, y=80, w=240, h=820): border-left $border 1px
```

### Tasks

| ID | Task | Acceptance Criteria |
|----|------|---------------------|
| T-6-01 | `batch_get(["tUPQd"])` + `get_screenshot()` — audit current state | Determine existing vs missing content |
| T-6-02 | Add or verify TopNav + Sidebar with Intelligence nav item active | TopNav + Intelligence-active sidebar |
| T-6-03 | Build 3-tab strip (y=44, x=200, w=1240, h=36): active "Top Today" with 2px `$border-strong` bottom indicator + 6px `$primary` dot + IBM Plex Sans 12px 500 `$foreground`; inactive "By Entity" + "By Impact" IBM Plex Sans 12px `$muted-foreground` | 3-tab strip with "Top Today" active |
| T-6-04 | Build 5 enriched Intelligence Feed article rows (y=80..520, x=200, w=1000, h=88 each): score chip (IBM Plex Mono 11px 600, DEEP=`$primary`, MED=`$warning`, LIGHT=`$dim`) + tier badge chip (40×20px, cornerRadius:3) + impact chip + source+time + headline (IBM Plex Sans 12px 500 `$foreground`, 2 lines) + excerpt (IBM Plex Sans 11px `$muted-foreground`) + entity chips | 5 enriched 88px article cards with all 4 score/badge/chip/headline elements |
| T-6-05 | Build TRENDING ENTITIES sidebar (x=1200, y=80, w=240, fill:`#10141c`, border-left `$border` 1px): header "TRENDING ENTITIES" (36px elevated) + 5 entity rows (32px each): Name fill_container + article count `$dim` + impact chip (48×20px ⬆+X.X% / ⬇-X.X% / –) | Right sidebar with 5 entity rows + impact chips |
| T-6-06 | Apply phantom offset fix; `get_screenshot()` validation | Full Intelligence/News page: 3-tab strip + article feed + trending sidebar |

### Intelligence Feed Row Content for 5 Rows
```
Row 0: score:0.91 DEEP, impact:⬆+1.8%, src:"Reuters · 30m",  headline:"Apple Faces Regulatory Scrutiny in EU Over App Store Practices", excerpt:"European Commission launched formal investigation...", chips:[AAPL][antitrust][EU]
Row 1: score:0.84 DEEP, impact:⬆+2.1%, src:"Bloomberg · 1h",  headline:"NVIDIA H100 Demand Surge Continues as AI Investment Accelerates", excerpt:"Data center revenue expected to exceed $18B...", chips:[NVDA][AI][data-center]
Row 2: score:0.71 MED,  impact:–,       src:"FT · 2h",         headline:"Fed Minutes Show Officials Divided on Pace of Rate Cuts", excerpt:"FOMC meeting notes reveal three dissenters...", chips:[FOMC][rates][monetary-policy]
Row 3: score:0.63 MED,  impact:⬇-0.9%, src:"WSJ · 4h",        headline:"Tesla Q2 Deliveries Miss Estimates as Competition Intensifies", excerpt:"Electric vehicle maker delivered 387,000 units...", chips:[TSLA][EV][deliveries]
Row 4: score:0.47 LIGHT,impact:–,       src:"Seeking Alpha · 6h",headline:"Microsoft Azure Growth Decelerates as Enterprise Spending Slows", excerpt:"Cloud segment grew 21% vs 28% prior quarter...", chips:[MSFT][cloud][Azure]
```

### Trending Entities Data
```
Entity 1: AAPL  — 23 articles — ⬆+1.4%  ($positive)
Entity 2: NVDA  — 18 articles — ⬆+3.1%  ($positive)
Entity 3: FOMC  — 14 articles — –        ($dim)
Entity 4: MSFT  — 11 articles — ⬆+0.8%  ($positive)
Entity 5: TSLA  —  9 articles — ⬇-1.2%  ($negative)
```

### Validation Gate
- [ ] TopNav + Intelligence-active sidebar present
- [ ] 3-tab strip at y=44: "Top Today" active with bottom indicator + dot
- [ ] 5 enriched article rows at 88px height each (y=80 to y=520)
- [ ] Each row has score chip + tier badge + impact chip + 2-line headline + entity chips
- [ ] TRENDING ENTITIES sidebar at x=1200 with 5 entity rows + impact chips
- [ ] Screenshot confirms layout, no phantom offset, article feed + sidebar side by side

---

## Post-Completion: DESIGN.md + TRACKING.md Updates

After each wave completes, update:

1. **DESIGN.md header** — change the relevant state from ⬜ to ✅ with date
2. **DESIGN.md Canvas Registry** — add ✅ date to the relevant row
3. **TRACKING.md** — update PLAN-0027 row with new wave count and corrected state list

### Final DESIGN.md Header Target (after all 6 waves):
```
P4 Instrument Detail: State A ✅ (Overview), State B ✅ (Fundamentals), State C ✅ (Intelligence),
  State D ✅ (News), State E ✅ (Chat), State F ✅ (Full-Screen Graph — candlesticks fixed)
P6 Supporting Pages: Markets ✅, Screener ✅, Intelligence/News ✅, Portfolio ✅
```

---

## Tracking

### Wave Status
| Wave | Priority | Gap | Frame | Status | Tasks Done | Tasks Total |
|------|----------|-----|-------|--------|-----------|-------------|
| Wave 1 | P1 | State F Candlestick Rework | `sL0wd` | pending | 0 | 5 |
| Wave 2 | P2 | State D News Tab | `jZEVF` | pending | 0 | 9 |
| Wave 3 | P3 | State B Fundamentals Tab | `VEVln` | pending | 0 | 7 |
| Wave 4 | P4 | State C Intelligence Tab | `M1GXQ` | pending | 0 | 11 |
| Wave 5 | P5 | Portfolio Page | `57eKB` | complete | 7 | 7 |
| Wave 6 | P6 | Intelligence/News Page | `tUPQd` | complete | 6 | 6 |

### Session Boundaries
Each wave is designed to be **completed by a single agent in a single session**:
- Wave 1 (~30 min): small scoped fix on existing frame
- Wave 2 (~45 min): assemble 5 article rows + filter bar + footer in empty frame
- Wave 3 (~45 min): build compact chart + accordion groups in empty frame
- Wave 4 (~60 min): most complex — entity graph nodes + 2 columns + 6 sub-panels
- Wave 5 (~45 min): build or fill portfolio summary + strategy cards + holdings table
- Wave 6 (~45 min): build or fill 3-tab + article feed + trending entities sidebar

---

## Risk Assessment

### Critical Path
Wave 4 (State C Intelligence Tab) is the highest risk — entity graph nodes with absolute positions are the most complex pencil.dev work in this plan. If time-constrained, Wave 4 can be split: entity graph nodes in session A, right column panels in session B.

### Known Risks
| Risk | Mitigation |
|------|-----------|
| Pencil MCP disconnect mid-session | Save progress in batches; re-open file from last known node IDs |
| `opacity:0` inheritance from WoVQh | Always check `batch_get` first; add `opacity:1` to every C() call |
| Phantom padding offset | Apply padding toggle (8→0) after every new vertical container |
| Frame already partially built (Portfolio/Intelligence pages) | Wave starts with `batch_get` + `get_screenshot` audit; only build missing nodes |
| Entity graph connector lines | Lines between nodes: use 2px wide rectangles rotated via transform; or omit connectors and rely on node proximity to imply connections |
