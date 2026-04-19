---
id: PLAN-0027-CANVAS-V2
prd: PRD-0027
title: "Frontend MVP — Canvas Design Plan v2 (Living Document)"
status: approved
created: 2026-04-14
updated: 2026-04-14
canvas_file: apps/frontend/designs/worldview-mvp_v1.pen
design_docs:
  - apps/frontend/designs/DESIGN.md
  - apps/frontend/designs/REDESIGN_PLAN.md
  - docs/specs/0027-frontend-mvp-ui-design.md
sessions_total: 9
sessions_done: 9
---

# PLAN-0027-CANVAS-V2: Canvas Design — Living Plan

> **Purpose**: Single authoritative plan for all pencil.dev canvas work on `worldview-mvp_v1.pen`.
> All sessions are sequential (same file — only one agent can work on it at a time).
> **Living document**: new sessions can be appended to the backlog when issues are discovered.
> Supersedes the canvas sections of `docs/plans/0027-design-canvas-plan.md` and `docs/plans/0027-ui-v2-plan.md`.

---

## How to Use This Plan

1. **Starting a session**: read this file + `DESIGN.md` + `REDESIGN_PLAN.md` before touching the canvas.
2. **After each session**: update the status table below and the REDESIGN_PLAN.md relevant section.
3. **Discovered a new issue**: append a new session to the **Backlog** section at the bottom. Do not create a separate plan file.
4. **Marking done**: change status from `pending` → `in-progress` → `done`, add completion date.

---

## Pre-Session Invariants (memorise before every canvas session)

```
• C("WoVQh", parent, {...}) for ALL frame children — I() inherits opacity:0.5 + width:8 from source
• layout:"vertical" stacks children; omit layout for horizontal (default)
• Phantom offset fix after new vertical containers: U(frame, {padding:8}) then U(frame, {padding:0}) in next batch
• Explicit hex values required — use fill:"#10141c" not fill:"$card"
• After every significant change: get_screenshot() to verify
• opacity:1 must be set explicitly on every C() call to override WoVQh default
```

---

## Color Quick Reference

```
#080A0E  background    #10141C  card/panel    #181D28  elevated
#232A36  border        #2E3847  border-strong
#D1D4DC  foreground    #787B86  muted-fg      #4C5260  dim
#0EA5E9  primary       #0EA5E920 primary-dim
#26A69A  positive      #EF5350  negative      #F59E0B  warning
#F0C040  amber (AI)    #F0C04018 amber-dim
```

Fonts: `IBM Plex Sans` (UI chrome) · `IBM Plex Mono` (ALL numbers, tickers, timestamps)

---

## Session Status Overview

| # | ID | Title | Priority | Status | Audit Finding(s) | Est. |
|---|----|-------|----------|--------|-----------------|------|
| 1 | Fix-A | Dashboard states placement | P0-BLOCKING | done ✅ 2026-04-14 | F-006 | 20 min |
| 2 | C-1 | State F — Candlestick quality fix | P0-BLOCKING | done ✅ 2026-04-14 | F-010 | 30–45 min |
| 3 | Fix-B | State A — Chart candlestick + AI Brief in header | P0-BLOCKING | done ✅ 2026-04-14 | F-010, F-011 | 45–60 min |
| 4 | C-2 | State D — News Tab (build from empty) | P1-CRITICAL | done ✅ 2026-04-14 | F-013 | 45–60 min |
| 5 | C-3 | State B — Fundamentals Tab (build from empty) | P1-CRITICAL | done ✅ 2026-04-14 | — | 45–60 min |
| 6 | C-4 | State C — Intelligence Tab (build from empty) | P1-CRITICAL | done ✅ 2026-04-14 | F-012 | 60–90 min |
| 7 | C-5 | Portfolio Page (build/replace old design) | P0-BLOCKING | done ✅ 2026-04-14 | F-027/028 | 45–60 min |
| 8 | C-6 | Intelligence/News Page (build from empty) | P1-CRITICAL | done ✅ 2026-04-14 | F-019 | 45–60 min |
| 9 | Fix-C+D | Screener nav + Settings completeness | P2-MAJOR | done ✅ 2026-04-14 | F-023, F-029 | 30–40 min |

---

## Sessions

---

### Session 1 — Fix-A: Dashboard States Placement

**Audit finding**: F-006 (BLOCKING)
**Problem**: Dashboard state frames `fBOiy` (State A), `UbwGX` (State B), `NZEgU` (State C) are at x=1540 — outside the main design column (x=0). Invisible in any vertical-scroll presentation. The parent frame `vsdgH` wraps only the initial view.
**Status**: done ✅ 2026-04-14

**What was done**: Dashboard states were already at x=0 (F-006 x=1540 issue resolved in prior session). States were buried in the Landing page y-range (y=3676/4636/5596 within lm5XH y=0–6000). Moved to y=6040/6980/7920 (40px gaps, after Landing ends at y=6000). Added 3 annotation text labels (IBM Plex Mono 10px #787B86) above each state. No overlapping between the 3 states. Snapshot confirms no layout problems.

**Context to load**:
```
batch_get(["vsdgH", "fBOiy", "UbwGX", "NZEgU"])
```

**Tasks**:
1. `batch_get(["vsdgH", "fBOiy", "UbwGX", "NZEgU"])` — confirm current x positions of all 4 nodes
2. `get_screenshot()` of the full dashboard area at x=0 and x=1540 to see actual state
3. If states are at x=1540: use `U()` to move them:
   - `U("fBOiy", {x:0, y:<stacked_y>})` — State A goes first (y based on vsdgH height or just below it)
   - `U("UbwGX", {x:0, y:<fBOiy_y + fBOiy_height + 40>})` — State B stacked below
   - `U("NZEgU", {x:0, y:<UbwGX_y + UbwGX_height + 40>})` — State C stacked below
4. Alternatively if x=1540 is intentional (side-by-side layout): add a clear annotation node above each state: "STATE A: Market Open", "STATE B: Sidebar Collapsed", "STATE C: Quick Ask" so they are visually labelled for handoff
5. `get_screenshot()` to verify all 3 states are visible in a single scroll

**Acceptance criteria**:
- [ ] All 3 dashboard states visible when scrolling down from y=0
- [ ] State B (sidebar collapsed) and State C (quick-ask overlay) clearly labelled
- [ ] No overlapping frames

**Documents to update**: `REDESIGN_PLAN.md` P3 → note dashboard states placement resolved

---

### Session 2 — C-1: State F Candlestick Quality Fix

**Audit finding**: F-010 (BLOCKING)
**Problem**: State F full-screen graph (`sL0wd`) shows plain colored rectangles — no OHLCV wick structure. Drawing tools sidebar may have invisible icons. Amber MA50 color needs verification.
**Status**: pending

**Context to load**:
```
batch_get(["sL0wd", "lZp51", "jayD2", "TBEvu"])
```
- `lZp51` = chart body containing candle nodes
- `jayD2` = drawing tools sidebar
- `TBEvu` = MA50 line node

**Tasks**:
1. `batch_get(["sL0wd"])` + `get_screenshot()` — audit current state
2. `batch_get(["lZp51"])` — list all child IDs (the existing plain rectangle candles)
3. Delete all existing candle children from `lZp51` using batch_design delete operations
4. Rebuild 40 candles. Each candle = 3 nodes inside `lZp51`. Pitch: 34px. Candle cx = 40 + i×34 + 6.
   - **Upper wick**: `C("WoVQh", "lZp51", {width:2, x:cx-1, y:high_y, height:open_y-high_y, fill:<color>, opacity:1, cornerRadius:0})`
   - **Body**: `C("WoVQh", "lZp51", {width:12, x:cx-6, y:min(open,close), height:abs(close-open), fill:<color>, opacity:1, cornerRadius:1})`
   - **Lower wick**: `C("WoVQh", "lZp51", {width:2, x:cx-1, y:max(open,close), height:low_y-max(open,close), fill:<color>, opacity:1, cornerRadius:0})`
   - Green (close > open): `fill:"#26a69a"` · Red (close ≤ open): `fill:"#ef5350"`
   - Last 8 candles: clear uptrend (progressively higher highs and lows)
5. `batch_get(["jayD2"])` — find all icon nodes; `U(id, {opacity:1})` any node with opacity < 1
6. `batch_get(["TBEvu"])` — confirm `stroke.fill:"#f0c040"` and `stroke.thickness:2`; fix if not
7. `get_screenshot()` — confirm 3-part candle structure, visible sidebar, amber MA50

**Acceptance criteria**:
- [ ] Each candle has 3 visible parts (upper wick, body, lower wick) in screenshot
- [ ] Drawing tools sidebar shows 6 visible icon buttons
- [ ] MA50 line is amber (#f0c040)
- [ ] No opacity:0 or opacity:0.5 remaining in chartBody or jayD2

**Documents to update**: `REDESIGN_PLAN.md` State F → ✅ QUALITY FIXED; `DESIGN.md` header

---

### Session 3 — Fix-B: State A Chart Candlestick + AI Brief Integration

**Audit findings**: F-010 (BLOCKING), F-011 (CRITICAL)
**Problem 1**: State A (`wE7LT`) — the default landing tab — also shows the same bar-chart problem as State F. The chart was built before the candlestick spec was established.
**Problem 2**: The AI Brief is in a right-side panel. PRD-0027 and the audit specify it should be integrated as a collapsible row below the 52W range bar (Row 3), directly in the header.
**Status**: done ✅ 2026-04-14

**What was done**:
- Part 1 (Chart): State A already had 28 proper 3-part candlesticks (c1w1/c1bd/c1w2 pattern) from prior session work. MA50 (`TgZZn`) and MA200 (`Q4yVV`) opacity fixed 0.5→1. Chart nodes: GhLsW (ChartColumn), b3Cxw (chartBg), amCuQ (pLine amber), TgZZn (MA50 amber), Q4yVV (MA200 sky).
- Part 2 (AI Brief): Deleted `KWCfj` (InstrumentBrief) from `rVFri` (RightPanelInner). Inserted `B9spk` (AIBriefRow, 1240×56) at y:124 in `6n0PG` (Header). Row has amber-dim bg (#f0c04018), amber bottom border. Content: amber dot (tdHQe) + "AI BRIEF" mono label (VBJsE) + "· DeepSeek R1 · 08:45 ET" (qvxm4) + collapse chip (LTtso) + amber 2px border bar (bftuL) + brief text (Fxsvf) + [GS][MS][NVDA] citation chips (CR7vP/igM3q/VvEoQ). Structural: header 6n0PG grown 160→216px, fjjdy (actions) moved y:124→y:180, body h6wEY moved y:160→y:216 and shrunk h:696→h:640.

**Context to load**:
```
batch_get(["wE7LT"])
```
Then identify chart body node and right panel brief node from result.

**Tasks (Part 1 — Chart)**:
1. `batch_get(["wE7LT"])` + `get_screenshot()` — identify: (a) chart area node ID, (b) existing candle/bar nodes inside chart, (c) right panel node IDs
2. Find the chart body container (similar to `lZp51` in State F) — likely a child of the OHLCV chart area
3. Delete existing bar nodes from chart body
4. Rebuild 28 candles using same 3-node structure as Session 2. Pitch: 40px across ~1120px chart area.
   - Include MA50 amber dashed overlay line and MA200 sky dashed overlay line
   - Include current price amber horizontal dotted line with price label on right Y-axis
   - Keep volume panel (20% height below chart) with green/red volume bars

**Tasks (Part 2 — AI Brief row)**:
5. Find the AI Brief node in the right panel (currently shows amber-bordered brief text)
6. Insert a new Row 4b between Row 3 (52W range) and Row 4 (action buttons) in the header:
   - Height: 56px, `fill:"#f0c04018"` (amber-dim bg), border-bottom: `fill:"#f0c040"` 1px
   - Left: amber `◉` dot + "AI BRIEF" label (IBM Plex Mono 11px `#f0c040`) + "· DeepSeek R1 · 08:45 ET" (IBM Plex Sans 10px `#4c5260`)
   - Right: `[▼ collapse]` chip
   - Below label: 2-line brief text (IBM Plex Sans 12px `#d1d4dc`, `#f0c040` border-left 2px)
   - Citation chips: `[cite1]` `[cite2]` `[cite3]` in `#0ea5e9` 10px
7. Remove the AI Brief card from the right panel; right panel now shows: KEY METRICS (3×3) + ANALYST CONSENSUS only
8. `get_screenshot()` — verify both changes

**Acceptance criteria**:
- [ ] State A chart shows proper candlesticks with wicks (same quality as Session 2)
- [ ] MA50 amber dashed + MA200 sky dashed overlays visible
- [ ] AI Brief row appears between 52W range row and action buttons row
- [ ] AI Brief has amber-dim background + amber left-border + amber dot label
- [ ] Right panel no longer contains the brief card

**Documents to update**: `REDESIGN_PLAN.md` State A → annotate chart + AI Brief changes; `DESIGN.md` header State A note

---

### Session 4 — C-2: State D News Tab (Build from Empty)

**Audit finding**: F-013 (CRITICAL)
**Problem**: Frame `jZEVF` is empty. News tab state not designed.
**Status**: done ✅ 2026-04-14

**Context to load**:
```
batch_get(["aTIbj", "jZEVF", "wE7LT", "D4pfu", "oahZK"])
```
- `jZEVF` = State D frame (empty)
- `wE7LT` = State A (copy TopNav + Sidebar + Tab bar from here)
- `D4pfu` = sidebar source
- `oahZK` = top nav source

**Tasks**:
1. `batch_get(["jZEVF"])` — confirm empty; note y-offset inside `aTIbj`
2. `C("oahZK", "jZEVF", {x:0, y:0, width:1440, opacity:1})` — add TopNav
3. `C("D4pfu", "jZEVF", {x:0, y:44, height:856, opacity:1})` — add Sidebar (Intelligence nav active)
4. Copy tab bar from State A `wE7LT`; set "News" tab active (2px `#2e3847` bottom indicator); set others inactive
5. Build filter bar (y=80, x=200, w=1040, h=40, fill:`#181d28`, border-bottom:`#232a36`):
   - [By Relevance ▼] chip + [By Date] chip + date range label + [DEEP✓] chip (sky) + [MED✓] chip (warning) + [LIGHT✓] chip (dim)
6. Build 5 article rows (88px each, y=120+i×88, x=200, w=1040):
   - Row 0: score 0.91 DEEP ⬆+1.8% Reuters "Apple Reports Record iPhone 15 Sales..."
   - Row 1: score 0.74 MED – Bloomberg "Fed Chair Powell Signals Further Rate Cuts..."
   - Row 2: score 0.82 DEEP ⬆+2.1% WSJ "NVIDIA H100 Supply Constraints Expected..."
   - Row 3: score 0.61 MED ⬇-0.9% FT "Berkshire Hathaway Reduces Apple Position..."
   - Row 4: score 0.48 LIGHT – Seeking Alpha "Technical Analysis: AAPL Support at $165..."
   - Each row: score (Mono 11px tier-colored) + tier badge (40px) + impact chip + source·time (10px dim) + headline (12px 500) + excerpt (11px muted, 2-line) + entity chips (10px elevated)
7. Add pagination footer (y=560, x=200, w=1040, h=40, fill:`#181d28`, border-top:`#232a36`): "Load 20 more >" centered, `#0ea5e9` Mono 12px
8. Apply phantom offset fix; `get_screenshot()`

**What was done** (2026-04-14):
State D was already partially constructed (chrome + 5 article rows + filter bar + footer). Session C-2 audited, diagnosed, and fixed 3 critical bugs:
1. **Text width=0 bug**: All 10 headline/excerpt text nodes had `width:0` with `textGrowth:"fixed-width"` → completely invisible. Fixed to `width:"fill_container"` on all 10 nodes (GgXXj, pc7Eu, yjsMd, lXBpa, BGj31, sfcYn, xs8tT, 2CfFM, gxYDy, soyqO).
2. **Chips layout**: 5 `chips` containers (cBtrj/8vFAh/wfCA6/MRlbD/9myZh) missing `layout:"horizontal"` → entity chips were absolutely positioned at 0,0. Fixed.
3. **State D/E frame overlap**: State E (RnKhf) was at y=3840, overlapping State D (y=3780..4680) by 840px. Fixed: State E → y=4720, State F (sL0wd) → y=5660, aTIbj height → 6700.
4. **Art3 badge tier**: Art3 had MED badge but should be DEEP (NVDA AI chip story). Fixed: ZwcUo fill/stroke → sky, text → "DEEP".

Node structure: TopNav `9i2le` + Sidebar `Eax8m` + Main `RnV0U` (Header `yNVTq` 160px + Body `Gx1E9` 696px containing TabBar `6xua5` + FilterBar `Y7cr5` + NewsList `OS9qE` with 5 article rows + Footer `iRip4`).

**Acceptance criteria**:
- [x] TopNav + Sidebar + 5-tab bar with "News●" active
- [x] Filter bar with DEEP/MED/LIGHT tier toggles
- [x] 5 article rows at 88px each with score + badge + impact + headline + entity chips
- [x] Pagination footer visible

**Documents to update**: `REDESIGN_PLAN.md` State D → ✅ DONE; `DESIGN.md` header

---

### Session 5 — C-3: State B Fundamentals Tab (Build from Empty)

**Problem**: Frame `VEVln` is empty.
**Status**: done ✅ 2026-04-14

**What was done**:
- VEVln already had a skeleton (TopNav R6829 + Sidebar 1oIJw + Main 62Ro7) from prior work. Content was substantially built — compact chart, period selector, accordion — just needed polish fixes.
- Fix 1: CompactChart (`iYOc6`) bars changed from `$positive`/`$negative` (price-chart colors) to all `#0EA5E9` (revenue chart blue). Label updated to "Q1'26 ▲".
- Fix 2: Added TTM chip to period selector (`fa0YU`). Now shows: Period: [Annual●] [Quarterly] [TTM].
- Fix 3: Added 5th data row Q1 2025 ($14.4B, +262%, $0.21 EPS, +8.2%, $5.7B NI) to IncomeTable (`b8K9O`). Updated table height 184→216. Footer "Show 8 rows ▼" repositioned.
- Structural note: Accordion bar chart (`cFIgE`) already used correct `#0EA5E9` bars with Q1'24–Q1'26 quarterly labels. IncomeTable had 6-column layout (Quarter/Revenue/YoY%/EPS/vs Est/NET INCOME) — richer than spec's 3-column but more useful.
- All 4 collapsed sections already present: BALANCE SHEET & CAPITAL STRUCTURE / CASH FLOW / VALUATION & ANALYST ESTIMATES / COMPANY & OWNERSHIP.

**Context to load**:
```
batch_get(["aTIbj", "VEVln", "wE7LT"])
```

**Tasks**:
1. Confirm `VEVln` empty; note y-offset
2. Copy TopNav + Sidebar + Tab bar from State A; set "Fundamentals●" tab active
3. Compact chart area (y=80, x=200, w=1240, h=200, fill:`#10141c`, border-bottom:`#232a36`):
   - 5 horizontal grid lines (1px `#232a36`)
   - 6-bar revenue chart: bars `#0ea5e9`, varying heights 40–140px, x-labels IBM Plex Mono 10px `#4c5260`
   - Timeframe bar top (32px)
4. Period selector row (y=280, x=200, w=1240, h=36, fill:`#181d28`, border-bottom:`#232a36`):
   - "PERIOD:" 10px CAPS `#787b86` + [Annual●] chip (`#0ea5e920` bg + `#0ea5e9` border) + [Quarterly] + [TTM]
5. Expanded accordion — INCOME & GROWTH (y=316, x=200, w=1240):
   - 36px header (fill:`#181d28`): "▼ INCOME & GROWTH" 13px 500 `#d1d4dc`, border-bottom:`#232a36`
   - Column header row (32px): METRIC / Q1 2026 / Q4 2025 / Q3 2025 (10px CAPS `#787b86`)
   - 5 data rows (32px, alt `#10141c`/`#080a0e`): Revenue $119.6B / Gross Profit $55.3B / Op. Income $31.2B / Net Income $26.9B / EPS $1.73 — IBM Plex Mono 12px right-aligned
6. 4 collapsed sections (36px each, fill:`#181d28`, border-bottom:`#232a36`):
   - "▶ BALANCE SHEET" / "▶ CASH FLOW" / "▶ VALUATION" / "▶ COMPANY & OWNERSHIP" — `#787b86` 11px
7. Apply phantom offset fix; `get_screenshot()`

**Acceptance criteria**:
- [ ] "Fundamentals●" tab active
- [ ] Compact chart (200px) + period selector visible
- [ ] Income & Growth expanded with 5 data rows in Mono
- [ ] 4 collapsed sections stacked below

**Documents to update**: `REDESIGN_PLAN.md` State B → ✅ DONE; `DESIGN.md` header

---

### Session 6 — C-4: State C Intelligence Tab (Build from Empty)

**Audit finding**: F-012 (CRITICAL — entity graph must have edges, node types, labels)
**Problem**: Frame `M1GXQ` is empty.
**Status**: done ✅ 2026-04-14

**What was done**:
- `M1GXQ` already had a skeleton (TopNav `UY2bo`, Sidebar `aSBF7` with Intelligence active, Main `2KoFh`) from a prior incomplete session, plus `XMYnT` (Header with company info) and `vlN6E` (Body with TabBar `cqTjE` and two-column split: EntityGraph `JWVrw` / RightIntel `NiBCW`).
- EntityGraph (`JWVrw`) already contained: panel header, controls row (hop-depth chips, confidence filter, type filters), GraphCanvas (`WxTbM`) with 6 ellipse nodes (AAPL center `iqi7J`, Tim Cook `ONSkl`, Berkshire `D2lDL`, TSMC `W1hYN`, MSFT `rRnOY`, Foxconn `rWkTC`) + legend, Recent Claims (3 rows with POSITIVE/NEUTRAL/NEGATIVE badges), Temporal Events (3 rows with earnings/product/executive badges).
- RightIntel (`NiBCW`) already contained: SimilarCompanies (MSFT 0.94, GOOGL 0.89, META 0.83), Contradictions (STRONG badge + analysis text), PredictionMarkets (2 probability rows: AAPL >$180 62%, AAPL Q2 EPS 79%).
- **Fixes applied**: Removed `opacity:0.5` from 12 nodes (section headers + claim rows + event rows + confidence track bars). Fixed Berkshire node stroke from purple `#A855F7` → `#2E3847`. Fixed event badge widths from hardcoded 8px → `fit_content(56)`.
- **Connector lines added**: 4 `type:"line"` nodes (ln1–ln4) + 1 vertical rectangle (ln5) connecting all 6 nodes to AAPL center, using `stroke:{fill:"#787B86", thickness:1}`. Edge labels inserted: "CEO of" (Tim Cook), "investor" (Berkshire), "supplier of" (TSMC), "peer" (MSFT), "assembler" (Foxconn).
- **Note**: `type:"line"` strokes are invisible when screenshotting the child frame directly (cache issue) — verified via parent `JWVrw` screenshot which shows all lines correctly.

**Context to load**:
```
batch_get(["aTIbj", "M1GXQ", "wE7LT"])
```

**Tasks**:
1. Confirm `M1GXQ` empty; note y-offset
2. Copy TopNav + Sidebar + Tab bar; set "Intelligence●" active
3. Left column (x=200, y=80, w=860, h=820, fill:`#10141c`, border-right:`#232a36` 1px)
4. Entity Graph section (top 304px of left column):
   - Panel header "ENTITY GRAPH" (28px fill:`#181d28`)
   - Controls row (36px): hop-depth chips [2●][3], min-confidence chip "≥75%", type filters [Companies✓][People✓][Funds✓][ETFs✓]
   - Graph canvas (240px, layout:none): 6 nodes + connector lines
     - AAPL center: 48×48px fill:`#0ea5e9`, x:506 y:100, label "AAPL" IBM Plex Mono 10px 600
     - Tim Cook: 32×32px fill:`#26a69a`, x:724 y:30, label "Tim Cook"
     - Berkshire: 32×32px fill:`#f0c040`, x:290 y:20, label "Berkshire"
     - TSMC: 28×28px fill:`#0ea5e9`, x:250 y:170, label "TSMC"
     - MSFT: 28×28px fill:`#0ea5e9`, x:766 y:155, label "MSFT"
     - Foxconn: 24×24px fill:`#181d28` stroke:`#232a36`, x:518 y:195, label "Foxconn"
     - Connector lines between nodes: 2px wide fill:`#2e3847` (use thin rectangles rotated, or rely on proximity)
     - Edge labels (10px `#4c5260`): "CEO of" near Tim Cook edge, "supplier of" near TSMC/Foxconn edges
   - Legend row (y=220): 3×6px circles in `#0ea5e9`/`#26a69a`/`#f0c040` + IBM Plex Sans 10px labels
5. Recent Claims section (y=304, h=180): header "▼ RECENT CLAIMS (10)" + 3 claim rows (48px each)
   - [POSITIVE] badge `#26a69a20` bg + 3-line text + 60px confidence bar
   - [NEUTRAL] badge `#232a36` bg
   - [NEGATIVE] badge `#ef535020` bg
6. Temporal Events section (y=484, h=168): header "▼ TEMPORAL EVENTS (8)" + 3 event rows (44px)
   - Event type badge (earnings=`#0ea5e9` / product=`#181d28` / executive=`#f59e0b`) + text + right-aligned date
7. Right column (x=1060, y=80, w=380, h=820, fill:`#10141c`)
8. Similar Instruments panel (h=233): "SIMILAR INSTRUMENTS" 11px CAPS + 3 rows (IBM/GOOGL/META scores) + "Compare in Screener →" footer `#0ea5e9`
9. Contradictions panel (h=134): "CONTRADICTIONS" label `#ef5350` + [STRONG] badge + 2-line text
10. Prediction Market Signals panel (h=186): 2 probability rows (question + 120px progress bar `#0ea5e9` + %) + "Source: Polymarket" footer
11. Apply phantom offset fix; `get_screenshot()`

**Acceptance criteria**:
- [ ] "Intelligence●" tab active
- [ ] Entity graph: 6 nodes in correct colors, edge lines visible between connected nodes, edge labels present
- [ ] Recent Claims: POSITIVE (teal) / NEUTRAL / NEGATIVE (red) badge variants
- [ ] Right column: all 3 panels with correct styling
- [ ] Left/right two-column split clearly visible in screenshot

**Documents to update**: `REDESIGN_PLAN.md` State C → ✅ DONE; `DESIGN.md` header

---

### Session 7 — C-5: Portfolio Page (Build/Replace Old Design)

**Audit findings**: F-027, F-028 (BLOCKING — old design active, must be replaced)
**Problem**: Frame `57eKB` contains the pre-redesign portfolio (bar chart + basic holdings). Must be replaced with strategy-centric design.
**Status**: done ✅ 2026-04-14

**What was done**:
- Found `Dwod8` (State A: Performance View) inside `57eKB` was already rebuilt in a prior incomplete session with all correct structure but every node at `opacity:0.5` — causing the entire page to appear dimmed/invisible.
- Fixed opacity to 1 on all 22 content nodes: KzIrC (SummaryRow) + 5 cells (NKiDy/zf8is/cDCGB/SvKS5/MGnlD) + 3 strategy cards (Hqxvf/vsybO/VpMl1) + sparklines (ty55S/D5yDn/Qquhl) + detail_tabs (pKTm8) + 5 tab frames (wSDqu/NwpVC/HrjZm/e88Bs/9WF0N) + tbl_header (Zjw7n) + 3 data rows (7ykXK/ryFdy/1XTKK) + subtotal (XcNwx) + 6 weight bars (SHUGN/OX3av/N6nQb/ioF7R/1KOZG/Qornp).
- Fixed active Holdings tab indicator: `wSDqu` stroke color `$border-strong` → `#0EA5E9` (primary sky-blue).
- Extended frame height: `Dwod8` 480px → 900px; sidebar `4tfJu` 436px → 856px.
- Final state: TopNav ✅, Sidebar with Portfolio active ✅, SummaryRow 5 cells ✅, 3 StrategyCards (Growth active/Income/Speculative) ✅, Holdings tab active ✅, AAPL/NVDA (teal) + TSLA (red) ✅, Subtotal row ✅.

**Context to load**:
```
batch_get(["57eKB"])
get_screenshot()
```
Audit first — determine what exists and what to delete.

**Tasks**:
1. `batch_get(["57eKB"])` + `get_screenshot()` — identify existing nodes to delete
2. Delete all existing content nodes from `57eKB` (performance bar chart, donut chart, old holdings table)
3. Add TopNav + Sidebar (Portfolio nav item active, same pattern as prior sessions)
4. Portfolio Summary Row (y=44, x=200, w=1240, h=56, fill:`#10141c`, border-bottom:`#232a36`):
   - 5 metric cells with 1px `#232a36` vertical dividers:
   - Total Value: $47,320.50 (IBM Plex Mono 20px 600 `#d1d4dc`)
   - Today P&L: +$1,243.18 (Mono 16px `#26a69a`) + +2.69% (11px)
   - Unrealized P&L: +$8,450.23 +21.7%
   - IRR: +18.7%
   - Positions: 12
5. 3 StrategyCards (y=124, x=216/472/728, w=240, h=120):
   - Active card: fill:`#0ea5e920`, stroke:`#0ea5e9` 1px
   - Inactive cards: fill:`#10141c`, stroke:`#232a36` 1px
   - Each: strategy name 9px CAPS `#787b86` + total value Mono 18px + daily P&L Mono 12px colored + position count 11px `#4c5260` + sparkline frame 80×20px top-right
6. Tab bar (y=260, x=200, w=1240, h=36): [Holdings●][Transactions][Analytics][Watchlists][Settings] — Holdings active with 2px bottom indicator
7. Column header row (y=296, h=32, fill:`#181d28`): ★/TICKER/COMPANY/SECTOR/QTY/AVG COST/CURRENT/UNREAL.$/UNREAL.%/DAILY%/WEIGHT%/ACTIONS
8. 3 data rows (32px each, alt `#10141c`/`#080a0e`):
   - AAPL ★: 50 $168.30 $173.42 +$256 +3.04% +0.58% 28.3%
   - NVDA ★: 10 $752.80 $875.40 +$1,226 +16.3% +1.23% 21.4%
   - TSLA:  8  $183.00 $177.20 -$46.40 -3.17% -0.81% 8.7%
9. Subtotal footer row (fill:`#181d28`): "Portfolio Total" + aggregated values right-aligned
10. Apply phantom offset fix; `get_screenshot()`

**Acceptance criteria**:
- [ ] Old bar chart + donut chart completely removed
- [ ] Summary row: 5 metric cells with Mono values
- [ ] 3 strategy cards: active one in sky-blue border
- [ ] Holdings tab: 3 rows with AAPL/NVDA positive (teal), TSLA negative (red)
- [ ] Subtotal row visible

**Documents to update**: `REDESIGN_PLAN.md` P6 Portfolio → ✅ DONE; `DESIGN.md` header; `TRACKING.md`

---

### Session 8 — C-6: Intelligence/News Page (Build from Empty/Incomplete)

**Audit finding**: F-019 (BLOCKING — missing nav)
**Problem**: Frame `tUPQd` is empty or incomplete. Missing nav, no tier badges on articles.
**Status**: done ✅ 2026-04-14

**What was done**:
- `SL9kb` (State A: Full Feed) already contained the complete page from a prior session. Verified via screenshot.
- TopNav + Intelligence-active sidebar ✅. 3-tab strip ([Top Today●] active). 14 article rows (FI1-FI14) with: DEEP/MED/LIGHT tier badges (sky/warning/dim), impact chips (⬆+%/⬇-%), source+time, headline, 2-line excerpt, entity chips.
- TRENDING ENTITIES sidebar (x=1200, w=240): header + 5 entity rows (AAPL/NVDA/FOMC/MSFT/TSLA) with mention counts and impact chips.
- **Morning Brief card** added to State A at y=80, x=200, w=1000, h=84: $amber-dim bg (#F0C04018), amber accent bar, amber dot + "AI MORNING BRIEF" Mono label + model/time + 2-line brief text. FeedArea/sidebar pushed to y=164.
- **State B — Signal Board** (`mFKf3`, y=1484, h=900): Built from scratch. Entity signal matrix (5 rows: NVDA/AAPL/FOMC/TSLA/MSFT) with SIGNAL SCORE track bars + article counts + prediction market probabilities + graph activity + alert ellipses. Right panel: entity propagation cascade diagram + PREDICTION MOVERS table (3 movers with direction arrows).
- **State C — Impact Board** (`pKH88`, y=2432, h=920): Built from scratch for PRD-0026 multi-window data. Filter bar [All●][Sustained][Fading][Spike] + time window toggles [t0▼][t1][t2][t5]. 4 article rows (72px each) with 2-row structure: top row (ticker chip + tier + SUSTAINED/FADING/SPIKE trend label + headline), bottom row (IMPACT: label + t+0/t+1/t+2/t+5 chips colored by direction). Right panel "TOP SUSTAINED IMPACT" with NVDA/AAPL entries. "10 more articles below" placeholder. Annotation label at y=3360.
- Page structure: `tUPQd` (05-Intelligence, h extended to 3500) → `SL9kb` (h=1444) | `mFKf3` (h=900) | `pKH88` (h=920).
- Canvas file used: `worldview-mvp_v2.pen` (NOT v1.pen as specified in this plan's frontmatter — v2 is the active file).

**Context to load**:
```
batch_get(["tUPQd"])
get_screenshot()
```
Audit first — determine actual current state.

**Tasks**:
1. `batch_get(["tUPQd"])` + `get_screenshot()` — determine what exists vs what is missing
2. Add/verify TopNav + Sidebar (Intelligence nav item active)
3. Build 3-tab strip (y=44, x=200, w=1240, h=36, border-bottom:`#232a36`):
   - [Top Today●] active: 2px `#2e3847` bottom indicator + 6px `#0ea5e9` dot + 12px 500 `#d1d4dc`
   - [By Entity] + [By Impact]: 12px `#787b86`
4. Build 5 enriched article rows (y=80–520, x=200, w=1000, h=88 each):
   - Row 0: 0.91 DEEP ⬆+1.8% Reuters "Apple Faces Regulatory Scrutiny in EU..." chips:[AAPL][antitrust][EU]
   - Row 1: 0.84 DEEP ⬆+2.1% Bloomberg "NVIDIA H100 Demand Surge..." chips:[NVDA][AI][data-center]
   - Row 2: 0.71 MED – FT "Fed Minutes Show Officials Divided..." chips:[FOMC][rates]
   - Row 3: 0.63 MED ⬇-0.9% WSJ "Tesla Q2 Deliveries Miss Estimates..." chips:[TSLA][EV]
   - Row 4: 0.47 LIGHT – Seeking Alpha "Microsoft Azure Growth Decelerates..." chips:[MSFT][cloud]
5. Build TRENDING ENTITIES sidebar (x=1200, y=80, w=240, fill:`#10141c`, border-left:`#232a36` 1px):
   - Header "TRENDING ENTITIES" (36px fill:`#181d28`, 11px CAPS `#787b86`)
   - 5 entity rows (32px each): AAPL 23 ⬆+1.4% / NVDA 18 ⬆+3.1% / FOMC 14 – / MSFT 11 ⬆+0.8% / TSLA 9 ⬇-1.2%
   - Impact chips: 48×20px, `#26a69a`/`#ef5350`/`#4c5260` colored
6. Apply phantom offset fix; `get_screenshot()`

**Acceptance criteria**:
- [ ] TopNav + Intelligence-active sidebar present
- [ ] 3-tab strip with "Top Today●" active
- [ ] 5 article rows at 88px: score + tier badge + impact chip + headline + entity chips
- [ ] TRENDING ENTITIES sidebar with 5 rows + impact chips

**Documents to update**: `REDESIGN_PLAN.md` P6 Intelligence/News → ✅ DONE; `DESIGN.md` header; `TRACKING.md`

---

### Session 9 — Fix-C+D: Screener Nav + Settings Completeness

**Audit findings**: F-023 (BLOCKING — Screener missing nav), F-029 (MAJOR — Settings incomplete)
**Status**: done ✅ 2026-04-14

**What was done**:
- **Fix-C (Screener)**: `ec1Mg` (State A: Screener Default) already had complete structure from prior session — F-023 was already resolved. Verified: TopNav (`MHi8V`), Sidebar (`zvuEI`), FilterBar (`xKxO5`), ScreenerTable (`pl5Od`) with 32px header + 22 data rows. Header columns (TICKER/COMPANY/SECTOR/MKT CAP/PRICE/DAILY%/P/E/SCORE▼) use IBM Plex Sans 11px 600 `$muted-foreground`; SCORE column is `$primary` (active sort). Data values use IBM Plex Mono 12px; SCORE column shows 40px progress bar + value. StatusBar at bottom. No changes needed.
- **Fix-D (Settings)**: `5B1Zd` (Settings Main) had correct 3-panel layout — TopNav (`oxI4o`), Sidebar (`Q7g5j`), SettingsNavRail (`TOdu1`) with 6 items (Profile/Notifications/Appearance/Keyboard Shortcuts/Subscription/Data & Privacy), SettingsContent (`nr6f8`) with 3 content sections — but ALL nodes had `opacity:0.5`. Fixed 48 nodes in 2 batch_design calls: TOdu1 + 12 nav-rail children; nr6f8 + 37 content descendants (ProfileSection: Avatar+NameGroup+EmailGroup+RoleGroup+SaveBtn; NotifSection: SeverityChips×4+ChannelRow×3+AlertRule1+AlertRule2; AppearSection: DensityChips×3+ThemeChips×2). Result: full Settings page visible at 100% opacity with Profile form active (name/email/role fields + Save Changes button visible).

**Context to load**:
```
batch_get(["<screener_frame_id>", "<settings_frame_id>"])
get_screenshot()
```
Need to identify frame IDs first.

**Tasks (Part 1 — Screener)**:
1. `get_editor_state()` to find Screener page frame ID (likely `07-Screener` or similar)
2. `batch_get(["<screener_frame>"])` + `get_screenshot()` — verify if top nav and sidebar are present
3. If missing: add TopNav + Sidebar (Screener nav item active) using same C() pattern
4. Verify table header row uses `#181d28` bg + 10px CAPS `#787b86` column labels
5. Verify data rows are 32px height with Mono numerics and SCORE bar column

**Tasks (Part 2 — Settings)**:
1. Find Settings page frame ID
2. `batch_get(["<settings_frame>"])` + `get_screenshot()` — identify what section panels exist
3. Add missing section items to the settings left nav rail:
   - Profile (currently missing or empty)
   - Notifications (add if missing)
   - Display (add: theme + density + chart type options)
   - Keyboard Shortcuts (add: command list table, IBM Plex Mono)
   - Account / Subscription (add: tier display)
4. For each missing section: add a placeholder content area with section title + 2–3 key fields shown
5. `get_screenshot()` — verify 5+ section items visible in nav rail

**Acceptance criteria**:
- [ ] Screener page has top nav + sidebar with same structure as Dashboard/Portfolio
- [ ] Settings nav rail shows ≥5 section items
- [ ] Settings content area shows Profile form fields when Profile is active
- [ ] No "API Keys only" limitation visible

**Documents to update**: `REDESIGN_PLAN.md` P6 Screener + P9 Settings notes; `DESIGN.md` header

---

## Backlog — Future Issues

> Append new sessions here when design issues are discovered. Follow the session template above.
> Each entry needs: finding ID, problem statement, frame ID, estimated effort, priority.

| # | Issue | Source | Frame | Est. | Priority |
|---|-------|--------|-------|------|---------|
| B-01 | Onboarding flow redesign — brokerage-first is wrong for research users; should start with watchlist + Morning Brief (F-031) | 2026-04-13 audit | onboarding frame | 45 min | P2 |
| B-02 | Markets/Intelligence page merge consideration — show news alongside heatmap (F-016) | 2026-04-13 audit | kmbLQ + tUPQd | 60 min | P3 |
| B-03 | Screener condition builder — add multi-condition criteria builder UI (F-024) | 2026-04-13 audit | screener frame | 45 min | P3 |
| B-04 | Status bar expansion — add DXY, WTI, BTC to index strip (F-009) | 2026-04-13 audit | all navbars | 15 min | P3 |
| B-05 | Screener pre-built templates — add `[Load Screen]` dropdown with 6 templates (F-025) | 2026-04-13 audit | screener frame | 30 min | P3 |
| B-06 | Alerts page — create alert conditions too limited; need condition builder (F-033) | 2026-04-13 audit | alerts frame | 45 min | P2 |
| B-07 | Portfolio Analytics tab — add P&L curve chart + risk metrics row (Sharpe/Beta/Drawdown) | PRD-0027 §F-07 | 57eKB | 30 min | P2 |

---

## Completion Tracking

Update after each session:

| Session | Done | Date | Notes |
|---------|------|------|-------|
| Fix-A | ✅ | 2026-04-14 | States moved to y=6040/6980/7920 (after Landing y=6000); 3 annotation labels added |
| C-1 | ✅ | 2026-04-14 | 40 plain bodies → 120 wick+body+wick nodes; MA50 opacity fixed to 1.0; sidebar 6 icons confirmed |
| Fix-B | ✅ | 2026-04-14 | Chart candlesticks already present; MA50/MA200 opacity 0.5→1; AIBriefRow (B9spk) added at y:124 in header (6n0PG 160→216px); InstrumentBrief (KWCfj) deleted from RightPanel; actions row (fjjdy) moved y:124→180 |
| C-2 | ✅ | 2026-04-14 | State D News Tab: text width=0 bug fixed (10 nodes), chips layout fixed, State E overlap fixed, Art3 badge tier corrected |
| C-3 | ✅ | 2026-04-14 | State B Fundamentals: chart bars → #0EA5E9, TTM chip added, 5th data row Q1 2025 added, table height 184→216 |
| C-4 | ✅ | 2026-04-14 | State C Intelligence: 12 opacity:0 nodes fixed, Berkshire node stroke #A855F7→#2E3847, 4 connector lines + edge labels added |
| C-5 | ✅ | 2026-04-14 | Portfolio: 22 opacity:0.5→1 nodes, Holdings tab indicator #0EA5E9, Dwod8 height 480→900px |
| C-6 | ✅ | 2026-04-14 | Intelligence/News SL9kb: 14 articles (FI1-FI14) with DEEP/MED/LIGHT badges, impact chips, TRENDING ENTITIES sidebar (5 rows) |
| Fix-C+D | ✅ | 2026-04-14 | Fix-C: Screener ec1Mg already complete (TopNav+Sidebar+FilterBar+Table+StatusBar). Fix-D: Settings 5B1Zd — fixed opacity:0.5 on 48 nodes across TOdu1 (6-item nav rail) + nr6f8 (Profile/Notifications/Appearance sections) |
| C-6-EXT | ✅ | 2026-04-15 | Intelligence page full redesign (worldview-mvp_v2.pen): Morning Brief amber card added to SL9kb; State B Signal Board (mFKf3) built — entity matrix 5 rows with score track bars + prediction probabilities + propagation diagram; State C Impact Board (pKH88) built — PRD-0026 multi-window chips (t0/t1/t2/t5) + SUSTAINED/FADING/SPIKE trend labels + filter bar. tUPQd h=2796→3500. DESIGN.md + TRACKING.md updated. |
| C-4-V2 | ✅ | 2026-04-16 | State C (M1GXQ) Intelligence Tab full revision (worldview-mvp_v2.pen): (1) Topbar UY2bo rebuilt — WORLDVIEW + search input + 4 index chips (SPY/QQQ/DIA/VIX) + market status + bell + AR avatar; (2) Right panel NiBCW rebuilt — Similar Instruments (MSFT/GOOGL/META + score bars), Contradictions (STRONG badge + green/red tinted items), Prediction Markets (3 items 64%/82%/47% with bars); (3) Entity graph WxTbM rebuilt — NVDA center pill (#0F3D3A/#14B8A6) with pulse rings, 6 type-colored pill nodes (TSMC/MSFT blue, Jensen purple, AMD red, Samsung blue, Blackstone amber) + type badges, color-coded edges (teal supplier, blue partner, purple has_executive, red competes, amber owns_stake), tooltip card offset to bottom-middle (NOT overlapping NVDA center) with connector line to NVDA→TSMC midpoint; (4) Recent Claims rebuilt — 3 rows with POSITIVE(green)/NEUTRAL(gray)/NEGATIVE(red) 58px badges + 72px confidence bars + left accent borders + tinted backgrounds; (5) Temporal Events rebuilt — continuous vertical timeline (x:20) with amber/blue/purple colored dots + 64px earnings/product/executive badges + dates. |

**v2 design complete**: ALL sessions done ✅ Intelligence page fully designed (3 states) + State C Intelligence tab revised (2026-04-16). Canvas ready for /scaffold-frontend implementation waves F-1..F-12.
