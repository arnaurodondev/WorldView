---
id: PLAN-0027-V2
prd: PRD-0027
title: "Frontend MVP UI — Complete Implementation v2 (Canvas + Code + Security)"
status: in-progress
created: 2026-04-14
updated: 2026-04-14
supersedes:
  - docs/plans/0027-design-canvas-plan.md (deleted — superseded)
  - docs/plans/0027-design-completion-plan.md (deleted — superseded)
canvas_file: apps/frontend/designs/worldview-mvp_v1.pen
waves:
  canvas: 6
  backend: 1
  frontend_code: 11
  total: 18
---

# PLAN-0027-V2: Frontend MVP — Complete UI Implementation

> **Supersedes**: PLAN-0027-DESIGN and PLAN-0027-B (both deleted — consolidated here).
> Those plans were correct but fragmented. This plan consolidates them, maximises parallelism,
> and adds precise dependency metadata so agent scheduling tools can claim waves independently.

---

## Current State (2026-04-14 audit baseline)

### Canvas (`worldview-mvp_v1.pen`)

| Frame | State | Status |
|-------|-------|--------|
| `wE7LT` | State A — Overview | ✅ Done |
| `RnKhf` | State E — Chat | ✅ Done |
| `sL0wd` | State F — Full-Screen Graph | ⚠️ Built but 3 quality failures (no candle wicks, invisible drawing tools icons, amber needs check) |
| `jZEVF` | State D — News Tab | ❌ Empty frame |
| `VEVln` | State B — Fundamentals Tab | ❌ Empty frame |
| `M1GXQ` | State C — Intelligence Tab | ❌ Empty frame |
| `57eKB` | Portfolio Page | ❌ Empty/incomplete |
| `tUPQd` | Intelligence/News Page | ❌ Empty/incomplete |

### Frontend Code (`apps/frontend/`)

| Area | Status |
|------|--------|
| CSS tokens (`index.css`) | ❌ Wrong — uses legacy `--bg-secondary`, `--accent` (wrong colors). BLOCKS all UI work. |
| `Layout.tsx` | ❌ Stub — no TopNavBar, no sidebar watchlist, uses wrong CSS vars |
| `CompanyDetailPage.tsx` | ❌ 40-line stub — no tab bar, no header rows, no states |
| `DashboardPage.tsx` | ❌ 36-line stub — only shows Recent Alerts |
| `PortfolioPage.tsx` | ❌ Stub — old design, no strategy cards |
| `ScreenerPage.tsx` | ❌ Exists but unstyled |
| `NewsPage.tsx` | ❌ Exists but no tier badges, no filter bar |
| Landing/Settings/Onboarding | ❌ Not built |
| Workspace | ❌ Not built |
| Gateway client | ❌ Missing 6 methods |

### Backend Security (portfolio service)

| Issue | Severity | Status |
|-------|----------|--------|
| InternalJWTMiddleware fail-open (F-SEC-001) | CRITICAL | Unresolved |
| Brokerage routes read raw headers not JWT claims (F-SEC-009) | CRITICAL | Unresolved |
| Hardcoded issuer string (F-SEC-002) | MAJOR | Unresolved |
| RateLimitMiddleware silent fail-open (F-SEC-007) | MAJOR | Unresolved |
| SnapTrade credentials plain str (F-SEC-010) | MAJOR | Unresolved |

---

## Parallel Execution Model

**Three independent tracks** can run concurrently:

```
Track A (Canvas, pencil.dev MCP required — SEQUENTIAL within track):
  C-1 → C-2 → C-3 → C-4 → C-5 → C-6

Track B (Backend Security — FULLY INDEPENDENT):
  S-1 (no dependencies)

Track C (Frontend Code):
  F-1 (CSS) → F-2 (Layout) ─┬─→ F-3 (CompanyDetail) ─┬─→ F-4 (State A+E)
                             │                          ├─→ F-5 (State D News)
                             ├─→ F-9 (Dashboard)        ├─→ F-6 (State B Fund.)
                             ├─→ F-10 (Portfolio)        ├─→ F-7 (State C Intel.)
                             └─→ F-11 (Landing/Settings) └─→ F-8 (State F+Gateway)
                             └─→ F-12 (Workspace, after F-9)
  All F-waves → T-1 (Tests)
```

### Scheduling Groups (what can execute in parallel)

| Group | Waves | Prerequisite |
|-------|-------|-------------|
| 0 | **C-1, F-1, S-1** | None — start all 3 immediately |
| 1 | **C-2, F-2** | C-1 done; F-1 done |
| 2 | **C-3, F-3, F-9, F-10, F-11** | C-2 done; F-2 done |
| 3 | **C-4, F-4, F-5, F-6, F-7, F-8** | C-3 done; F-3 done |
| 4 | **C-5, F-12** | C-4 done; F-9 done |
| 5 | **C-6** | C-5 done |
| 6 | **T-1** | All F-waves done; S-1 done |

---

## Pre-Read (agent must load before starting any wave)

1. `apps/frontend/designs/DESIGN.md` — color tokens, typography rules, component specs (hex values authoritative)
2. `docs/specs/0027-frontend-mvp-ui-design.md` — full PRD
3. `apps/frontend/designs/REDESIGN_PLAN.md` — page-level design decisions and completed sections

For backend waves, additionally:
- `services/portfolio/.claude-context.md`
- `docs/audits/2026-04-14-qa-plan-0027-impl-review.md` — exact findings F-SEC-001/002/007/009/010

---

## Color Tokens Quick Reference

```
#080A0E  --background    #10141C  --card           #181D28  --elevated/--muted
#232A36  --border        #2E3847  --border-strong
#D1D4DC  --foreground    #787B86  --muted-foreground  #4C5260  --dim
#0EA5E9  --primary       rgba(14,165,233,0.12)  --primary-dim
#26A69A  --positive      #EF5350  --negative       #F59E0B  --warning
#F0C040  --amber         rgba(240,192,64,0.10)   --amber-dim
```

Fonts: `IBM Plex Sans` (UI chrome) | `IBM Plex Mono` (ALL numbers, tickers, timestamps)

---

## TRACK A — Canvas Design Waves (pencil.dev MCP required)

> All canvas waves are **sequential** — they operate on the same `.pen` file.
> Each wave must be verified with `get_screenshot()` before marking done.
> Critical invariants (memorise before touching canvas):
> - `C("WoVQh", parent, {...})` for ALL frame children — `I()` inherits opacity:0.5
> - `layout:"vertical"` IS valid for vertical stacks; omit `layout` for horizontal (default)
> - Apply phantom offset fix after new vertical containers: `U(frame, {padding:8})` then `U(frame, {padding:0})`
> - Explicit hex values required (never `$token` in function calls — use `fill:"#10141c"`)

---

### Wave C-1: State F — Candlestick Quality Fix

**Track**: Canvas (pencil.dev MCP)
**Depends on**: none ← START IMMEDIATELY
**Blocks**: C-2, C-3, C-4, C-5, C-6
**Frame**: `sL0wd` (inside `aTIbj`, y≈4820, 1440×900)
**Estimated effort**: 30–45 min

**Goal**: Fix 3 quality failures in the existing Full-Screen Graph frame: proper 3-part candlestick structure (upper wick + body + lower wick), visible drawing tools icons, verified amber MA50 + price label.

#### Tasks

| ID | Task | Target Nodes |
|----|------|--------------|
| T-C1-01 | `batch_get(["sL0wd", "lZp51", "jayD2"])` + `get_screenshot()` — audit current state | sL0wd, lZp51, jayD2 |
| T-C1-02 | Delete existing plain rectangle candles in `lZp51`; rebuild 40 candles as 3-node groups (upper wick + body + lower wick). Green: `#26a69a`; Red: `#ef5350`. Upper wick: `width:2, x:candle_cx-1, y:high_y, height:open_y-high_y`. Body: `width:12, x:candle_cx-6, y:min(open,close), height:abs(close-open), cornerRadius:1`. Lower wick: `width:2, x:candle_cx-1, y:max(open,close), height:low_y-max(open,close)`. Candle pitch: 34px. | lZp51 children |
| T-C1-03 | Fix drawing tools sidebar `jayD2`: `batch_get(["jayD2"])` → find all icon nodes → `U(id, {opacity:1})` for any node with opacity<1 | jayD2 children |
| T-C1-04 | Verify amber: `batch_get` MA50 line node `TBEvu` + price label → confirm `fill:"#f0c040"` and opacity 0.7–1.0; update if needed | TBEvu, price label |
| T-C1-05 | `get_screenshot()` final — confirm 3-part candle structure, visible toolbar, amber MA50 | — |

**Acceptance criteria**:
- [ ] Each candle has 3 distinct parts (upper wick, body, lower wick) visible in screenshot
- [ ] Drawing tools sidebar shows 6 visible icon buttons
- [ ] MA50 line is amber (`#f0c040`), clearly distinguishable from price bars
- [ ] Price label `$875.40` amber and readable
- [ ] No `opacity:0` or `opacity:0.5` nodes remaining in chartBody or jayD2

**Documents to update**: `REDESIGN_PLAN.md` State F → ✅ QUALITY FIXED; `DESIGN.md` header: State F ✅

---

### Wave C-2: State D — News Tab Assembly

**Track**: Canvas (pencil.dev MCP)
**Depends on**: C-1
**Blocks**: C-3
**Frame**: `jZEVF` (inside `aTIbj`, y≈2930, 1440×900)
**Estimated effort**: 45–60 min

**Goal**: Build the complete News Tab frame from scratch. Currently empty.

**Context to load**: `batch_get(["jZEVF", "wE7LT", "D4pfu", "oahZK", "jJ9GD"])`
- `jZEVF` = State D frame (empty)
- `wE7LT` = State A (copy TopNav + Sidebar + Tab bar from here)
- `jJ9GD` = article row clone source

#### Tasks

| ID | Task | Acceptance |
|----|------|------------|
| T-C2-01 | Confirm `jZEVF` is empty; note y-offset | Empty confirmed |
| T-C2-02 | `C("oahZK", "jZEVF", {x:0, y:0, width:1440})` — add TopNav | Nav bar at top |
| T-C2-03 | `C("D4pfu", "jZEVF", {x:0, y:44, height:856})` — add Sidebar (Intelligence nav active) | Sidebar visible, left column |
| T-C2-04 | Copy tab bar from State A into `jZEVF`; update active tab to "News" (2px `#2e3847` bottom indicator) | 5 tabs: Overview/Fundamentals/Intelligence/News●/Chat |
| T-C2-05 | Build filter bar (40px, y=80, x=200, w=1040, fill:`#181d28`, border-bottom:`#232a36` 1px): [By Relevance ▼] chip + [By Date] chip + date range "Jan 1 → Apr 14, 2026" in `#787b86` + [DEEP✓] chip (bg:`#0ea5e920` border:`#0ea5e9` text:`#0ea5e9`) + [MED✓] chip (bg:`#f59e0b20`) + [LIGHT✓] chip (bg:`#181d28` border:`#232a36` text:`#4c5260`) | Filter bar with 5 controls |
| T-C2-06 | Clone 5 article rows from `jJ9GD` into `jZEVF` at y=120+i*88, x=200, w=1040 for i=0..4. Row 0: score:0.91 DEEP ⬆+1.8% Reuters "Apple Reports Record iPhone 15 Sales...". Row 1: score:0.74 MED – Bloomberg "Fed Chair Powell Signals...". Row 2: score:0.82 DEEP ⬆+2.1% WSJ "NVIDIA H100 Supply Constraints...". Row 3: score:0.61 MED ⬇-0.9% FT "Berkshire Hathaway Reduces Apple...". Row 4: score:0.48 LIGHT – Seeking Alpha "Technical Analysis: AAPL Support..." | 5×88px article rows visible |
| T-C2-07 | Add pagination footer (40px, y=560, x=200, w=1040, fill:`#181d28`, border-top:`#232a36`): "Load 20 more >" centered, IBM Plex Sans 12px `#0ea5e9` | Footer at bottom of list |
| T-C2-08 | Apply phantom offset fix to `jZEVF` and any vertical containers | Children at correct y positions |
| T-C2-09 | `get_screenshot()` | Full State D: filter bar + 5 article rows + footer |

**Acceptance criteria**:
- [ ] `jZEVF` has all layers: TopNav, Sidebar, tab bar, filter bar, 5 article rows, pagination
- [ ] "News" tab active with 2px bottom indicator
- [ ] At least 3 article rows show score chip + tier badge + impact chip + headline
- [ ] Filter bar shows DEEP/MED/LIGHT toggles with correct tier colors

**Documents to update**: `REDESIGN_PLAN.md` State D → ✅ DONE; `DESIGN.md` header

---

### Wave C-3: State B — Fundamentals Tab Build

**Track**: Canvas (pencil.dev MCP)
**Depends on**: C-2
**Blocks**: C-4
**Frame**: `VEVln` (inside `aTIbj`, y≈1010, 1440×900)
**Estimated effort**: 45–60 min

**Goal**: Build the Fundamentals Tab. Currently empty.

**Context to load**: `batch_get(["VEVln", "wE7LT"])`

#### Tasks

| ID | Task | Acceptance |
|----|------|------------|
| T-C3-01 | Confirm `VEVln` empty; note y-offset | Empty confirmed |
| T-C3-02 | Copy TopNav + Sidebar + Tab bar from State A; set "Fundamentals" tab active | Nav + sidebar + "Fundamentals●" |
| T-C3-03 | Add compact chart area (y=80, x=200, w=1240, h=200, fill:`#10141c`, border-bottom:`#232a36`): 5 horizontal grid lines (1px `#232a36`), 6-bar revenue chart (bars `#0ea5e9`, varying heights 40–140px), timeframe bar top (32px), y-axis labels right IBM Plex Mono 11px `#4c5260` | 200px chart placeholder |
| T-C3-04 | Add period selector row (y=280, x=200, w=1240, h=36, fill:`#181d28`, border-bottom:`#232a36`): label "PERIOD:" 10px CAPS `#787b86` + [Annual●] chip (bg:`#0ea5e920` border:`#0ea5e9`) + [Quarterly] chip (bg:`#181d28` border:`#232a36`) + [TTM] chip | Period selector with 3 toggle buttons |
| T-C3-05 | Build expanded "INCOME & GROWTH" accordion (y=316, x=200, w=1240): 36px header row (fill:`#181d28`, "▼ INCOME & GROWTH" 13px 500 `#d1d4dc`, border-bottom:`#232a36`). Column header row (32px, fill:`#181d28`): METRIC / Q1 2026 / Q4 2025 / Q3 2025 (10px CAPS `#787b86`). 5 data rows (32px, alt `#10141c`/`#080a0e`): Revenue $119.6B/$124.3B/$121.8B | Expanded section with 5 data rows |
| T-C3-06 | Add 4 collapsed accordion sections (36px each): "▶ BALANCE SHEET" / "▶ CASH FLOW" / "▶ VALUATION" / "▶ COMPANY & OWNERSHIP" — each fill:`#181d28`, IBM Plex Sans 11px `#787b86`, border-bottom:`#232a36` | 4 collapsed header rows |
| T-C3-07 | Apply phantom offset fix; `get_screenshot()` | Compact chart + period selector + 1 expanded + 4 collapsed |

**Acceptance criteria**:
- [ ] "Fundamentals" tab active
- [ ] Period selector with Annual (active), Quarterly, TTM
- [ ] Income & Growth: column headers + 5 data rows in IBM Plex Mono
- [ ] 4 collapsed sections stacked below with ▶ chevrons

**Documents to update**: `REDESIGN_PLAN.md` State B → ✅ DONE; `DESIGN.md` header

---

### Wave C-4: State C — Intelligence Tab Build

**Track**: Canvas (pencil.dev MCP)
**Depends on**: C-3
**Blocks**: C-5
**Frame**: `M1GXQ` (inside `aTIbj`, y≈1970, 1440×900)
**Estimated effort**: 60–90 min (most complex canvas wave)

**Goal**: Build the Intelligence Tab — entity graph + 2-column right panels + bottom accordions.

**Context to load**: `batch_get(["M1GXQ", "wE7LT"])`

#### Tasks

| ID | Task | Acceptance |
|----|------|------------|
| T-C4-01 | Confirm `M1GXQ` empty; note y-offset | Empty confirmed |
| T-C4-02 | Copy TopNav + Sidebar + Tab bar; set "Intelligence" tab active | Nav + sidebar + "Intelligence●" |
| T-C4-03 | Build left column container (x=200, y=80, w=860, h=820, fill:`#10141c`, border-right:`#232a36` 1px) | Left column frame |
| T-C4-04 | Build Entity Graph section (top 304px of left column): panel header "ENTITY GRAPH" (28px elevated) + controls row (36px: hop-depth chips [2●][3], min-confidence chip "≥75%", filter chips [Companies✓][People✓][Funds✓]) + graph canvas (240px, layout:none). Nodes: AAPL center (48×48px fill:`#0ea5e9`), Tim Cook (32×32 fill:`#26a69a`), Berkshire (32×32 fill:`#f0c040`), TSMC (28×28 fill:`#0ea5e9`), MSFT (28×28 fill:`#0ea5e9`), Foxconn (24×24 fill:`#181d28` stroke:`#232a36`). Positions: AAPL x:506 y:100, Tim Cook x:724 y:30, Berkshire x:290 y:20, TSMC x:250 y:170, MSFT x:766 y:155, Foxconn x:518 y:195. Legend: 3 × 6px colored circles + IBM Plex Sans 10px `#787b86` labels | Entity graph with 6 colored nodes |
| T-C4-05 | Build Recent Claims section (y=304, h=180): header "▼ RECENT CLAIMS (10)" (36px elevated) + 3 claim rows (48px): [POSITIVE] badge (bg:`#26a69a20` text:`#26a69a`) / [NEUTRAL] (bg:`#232a36`) / [NEGATIVE] (bg:`#ef535020` text:`#ef5350`) + claim text + 60px confidence bar | 3 claim rows with colored badges |
| T-C4-06 | Build Temporal Events section (y=484, h=168): header "▼ TEMPORAL EVENTS (8)" (36px elevated) + 3 event rows (44px): event type badge (earnings=`#0ea5e9`, product=`#181d28`, executive=`#f59e0b`) + text + right-aligned date | 3 event rows |
| T-C4-07 | Build right column container (x=1060, y=80, w=380, h=820, fill:`#10141c`) | Right column frame |
| T-C4-08 | Build Similar Instruments panel (y=0, h=233): "SIMILAR INSTRUMENTS" label (11px CAPS `#787b86`) + column headers + 3 rows: IBM (0.94), GOOGL (0.89), META (0.83) in IBM Plex Mono 12px + "« Compare in Screener →" footer `#0ea5e9` | 3 rows + footer |
| T-C4-09 | Build Contradictions panel (y=233, h=134): "CONTRADICTIONS" label `#ef5350` + [STRONG] badge + 2-line contradiction text `#787b86` | Contradictions panel with red label |
| T-C4-10 | Build Prediction Market Signals panel (y=367, h=186): "PREDICTION MARKET SIGNALS" label + 2 probability rows (question + 120px progress bar fill:`#0ea5e9` + %) + "Source: Polymarket · updated 4m ago" footer | 2 probability bars |
| T-C4-11 | Apply phantom offset fix; `get_screenshot()` | Full Intelligence tab: graph + both columns populated |

**Acceptance criteria**:
- [ ] "Intelligence" tab active
- [ ] Entity graph: 6 nodes in correct colors (blue=company, green=person, amber=fund)
- [ ] Recent Claims: 3 rows with POSITIVE/NEUTRAL/NEGATIVE sentiment badges
- [ ] Right column: all 3 panels (Similar Instruments + Contradictions + Prediction Markets)
- [ ] Two-column layout with correct proportions in screenshot

**Documents to update**: `REDESIGN_PLAN.md` State C → ✅ DONE; `DESIGN.md` header

---

### Wave C-5: Portfolio Page Build

**Track**: Canvas (pencil.dev MCP)
**Depends on**: C-4
**Blocks**: C-6
**Frame**: `57eKB` (standalone, 1440×900)
**Estimated effort**: 45–60 min

**Goal**: Build or complete the Portfolio page. Audit reveals it's empty/incomplete despite TRACKING claims.

**Context to load**: `batch_get(["57eKB"])` + `get_screenshot()` — determine current state first.

#### Tasks

| ID | Task | Acceptance |
|----|------|------------|
| T-C5-01 | `batch_get(["57eKB"])` + `get_screenshot()` — audit what exists | Determine gap |
| T-C5-02 | Add/verify TopNav + Sidebar (Portfolio nav item active) | TopNav + Portfolio-active sidebar |
| T-C5-03 | Build Portfolio Summary Row (y=44, x=200, w=1240, h=56, fill:`#10141c`, border-bottom:`#232a36`): 5 metric cells separated by 1px vertical `#232a36` dividers: Total Value ($47,320.50 Mono 20px 600) / Today P&L (+$1,243.18 Mono 16px `#26a69a` + +2.69% 11px) / Unrealized P&L (+$8,450.23 +21.7%) / IRR (+18.7%) / Positions (12) | 5-cell summary row |
| T-C5-04 | Build 3 StrategyCards (y=124, x=216/472/728, w=240, h=120): active card (fill:`#0ea5e920` stroke:`#0ea5e9` 1px) / inactive (fill:`#10141c` stroke:`#232a36`). Each: strategy name 9px CAPS + total value Mono 18px + daily P&L Mono 12px + position count 11px `#4c5260` + sparkline frame 80×20px top-right | 3 strategy cards; 1 active |
| T-C5-05 | Build tab bar (y=260, x=200, w=1240, h=36): [Holdings●][Transactions][Analytics][Watchlists][Settings] — Holdings active with 2px bottom indicator | 5-tab bar |
| T-C5-06 | Build Holdings table (y=296, x=200, w=1240): column header row (32px fill:`#181d28`): ★/TICKER/COMPANY/SECTOR/QTY/AVG COST/CURRENT/UNREAL.$/UNREAL.%/DAILY%/WEIGHT%/ACTIONS. Row 1 AAPL ★: +$256 +3.04% +0.58% 28.3%. Row 2 NVDA ★: +$1,226 +16.3% +1.23% 21.4%. Row 3 TSLA: -$46.40 -3.17% -0.81% 8.7%. Subtotal row fill:`#181d28` | Holdings table: 3 rows + subtotal |
| T-C5-07 | Apply phantom offset fix; `get_screenshot()` validation | Full portfolio page |

**Acceptance criteria**:
- [ ] 5-metric summary row with Mono values and P&L in `$positive`
- [ ] 3 strategy cards; active card in sky-blue border
- [ ] Holdings tab active, table with 3 data rows + subtotal
- [ ] AAPL/NVDA rows in `$positive`, TSLA in `$negative`

**Documents to update**: `REDESIGN_PLAN.md` P6 Portfolio → ✅ DONE; `DESIGN.md` header; `TRACKING.md`

---

### Wave C-6: Intelligence/News Page Build

**Track**: Canvas (pencil.dev MCP)
**Depends on**: C-5
**Blocks**: none
**Frame**: `tUPQd` (standalone, 1440×900)
**Estimated effort**: 45–60 min

**Goal**: Build or complete the Intelligence/News page. Currently empty/incomplete.

**Context to load**: `batch_get(["tUPQd"])` + `get_screenshot()` — determine current state first.

#### Tasks

| ID | Task | Acceptance |
|----|------|------------|
| T-C6-01 | `batch_get(["tUPQd"])` + `get_screenshot()` — audit what exists | Determine gap |
| T-C6-02 | Add/verify TopNav + Sidebar (Intelligence nav item active) | TopNav + Intelligence-active sidebar |
| T-C6-03 | Build 3-tab strip (y=44, x=200, w=1240, h=36, border-bottom:`#232a36`): [Top Today●] active (2px `#2e3847` bottom indicator + 6px `#0ea5e9` dot + 12px 500 `#d1d4dc`) / [By Entity] / [By Impact] (12px `#787b86`) | 3-tab strip |
| T-C6-04 | Build 5 enriched Intelligence Feed article rows (y=80–520, x=200, w=1000, h=88 each). Row 0: score:0.91 DEEP ⬆+1.8% Reuters "Apple Faces Regulatory Scrutiny in EU…" chips:[AAPL][antitrust][EU]. Row 1: score:0.84 DEEP ⬆+2.1% Bloomberg "NVIDIA H100 Demand Surge…" chips:[NVDA][AI]. Row 2: score:0.71 MED – FT "Fed Minutes Show Officials Divided…". Row 3: score:0.63 MED ⬇-0.9% WSJ "Tesla Q2 Deliveries Miss Estimates…". Row 4: score:0.47 LIGHT – Seeking Alpha "Microsoft Azure Growth Decelerates…" | 5 enriched 88px article rows |
| T-C6-05 | Build TRENDING ENTITIES sidebar (x=1200, y=80, w=240, fill:`#10141c`, border-left:`#232a36` 1px): header "TRENDING ENTITIES" (36px fill:`#181d28`) + 5 entity rows (32px): AAPL 23 articles ⬆+1.4% / NVDA 18 ⬆+3.1% / FOMC 14 – / MSFT 11 ⬆+0.8% / TSLA 9 ⬇-1.2% | Right sidebar with 5 entity rows |
| T-C6-06 | Apply phantom offset fix; `get_screenshot()` | Full Intelligence/News page |

**Acceptance criteria**:
- [ ] 3-tab strip: "Top Today" active with dot + bottom indicator
- [ ] 5 enriched article rows at 88px height
- [ ] Each row: score chip + tier badge + impact chip + 2-line headline + entity chips
- [ ] TRENDING ENTITIES sidebar at x=1200 with 5 rows + impact chips

**Documents to update**: `REDESIGN_PLAN.md` P6 Intelligence/News → ✅ DONE; `DESIGN.md` header; `TRACKING.md`

---

## TRACK B — Backend Security Wave (Independent)

---

### Wave S-1: Backend Security Fixes ✅

**Track**: Backend (Python)
**Depends on**: none ← START IMMEDIATELY
**Blocks**: none (independent)
**Service**: `services/portfolio/`
**Estimated effort**: 30–45 min
**Status**: **DONE** — 2026-04-14 · portfolio 476 unit tests pass · api-gateway 76 unit tests pass · ruff + mypy clean

**Goal**: Fix 5 security findings from F-SEC-001/002/007/009/010 identified in the 2026-04-14 audit.

#### Tasks

| ID | Task | File | Fix |
|----|------|------|-----|
| T-S1-01 | **F-SEC-001**: Remove unverified JWT decode path. In `InternalJWTMiddleware.dispatch()`, when `self.public_key is None`, return `JSONResponse({"detail": "Service not ready"}, status_code=503)` immediately. Delete the `options={"verify_signature": False}` branch entirely. | `services/portfolio/src/portfolio/infrastructure/middleware/internal_jwt.py` | Remove lines with `verify_signature: False` |
| T-S1-02 | **F-SEC-002**: Move hardcoded `"worldview-gateway"` issuer to settings. Add `internal_jwt_issuer: str = Field(default="worldview-gateway")` to `PortfolioSettings`. In `InternalJWTMiddleware.__init__`, accept `issuer: str` param. In middleware factory, pass `settings.internal_jwt_issuer`. | `services/portfolio/src/portfolio/config.py`, `middleware/internal_jwt.py` | Externalize issuer |
| T-S1-03 | **F-SEC-009**: In `_require_user_headers()` (brokerage_connections.py), replace `request.headers.get("X-User-Id")` → `getattr(request.state, "user_id", None)` and `request.headers.get("X-Tenant-Id")` → `getattr(request.state, "tenant_id", None)`. Return 401 if either is None. | `services/portfolio/src/portfolio/api/routes/brokerage_connections.py:37-42` | Use validated JWT claims |
| T-S1-04 | **F-SEC-010**: Change `snaptrade_client_id: str` → `SecretStr` and `snaptrade_consumer_key: str` → `SecretStr` in PortfolioSettings. Update callers in SnapTradeAdapter to use `.get_secret_value()`. | `services/portfolio/src/portfolio/config.py`, `infrastructure/snaptrade_adapter.py` | SecretStr for credentials |
| T-S1-05 | **F-SEC-007**: In `RateLimitMiddleware`, when `self.valkey_client is None`, add `logger.debug("rate_limiting_disabled", path=str(request.url.path))` and continue (don't change behavior — just add observability). | `services/portfolio/src/portfolio/infrastructure/middleware/rate_limit.py` | Add debug logging |
| T-S1-06 | Fix portfolio test warning: remove `@pytest.mark.asyncio` from 2 non-async test functions in `test_brokerage_connections.py:350` | `services/portfolio/tests/unit/api/test_brokerage_connections.py:350` | Remove marker |
| T-S1-07 | Run `python -m pytest tests/ -m "unit" -v --tb=short` from `services/portfolio/` — must pass with 0 warnings | portfolio unit tests | Validation |

**Acceptance criteria**:
- [x] All portfolio unit tests pass (0 warnings about asyncio mark)
- [x] No `verify_signature: False` in any middleware
- [x] Brokerage routes read `request.state.user_id` not raw headers
- [x] SnapTrade credentials are `SecretStr`
- [x] RateLimitMiddleware logs when disabled (api-gateway middleware.py)

**Break impact**:
| File | Why | Fix |
|------|-----|-----|
| `services/portfolio/tests/unit/api/test_brokerage_connections.py` | Tests that mock middleware state must set `request.state.user_id` instead of headers | Update test fixtures to set `request.state.user_id = "test-user"` |

---

## TRACK C — Frontend Code Waves

---

### Wave F-1: CSS Foundation + Design Token Fix

**Track**: Frontend Code
**Depends on**: none ← START IMMEDIATELY
**Blocks**: ALL other F-waves (F-2 through T-1)
**Estimated effort**: 30–45 min

**Goal**: Replace legacy CSS variables with Midnight Pro tokens; add IBM Plex font imports; fix all color token mismatches in existing components. This is the single highest-priority code wave — everything else renders wrong without it.

**Findings fixed**: F-FE-001, F-FE-002, F-FE-004, F-FE-005, F-FE-006, F-FE-007, F-FE-009, F-FE-010, F-FE-018, F-FE-019, F-DESIGN-022

#### Tasks

| ID | Task | Target File |
|----|------|-------------|
| T-F1-01 | Replace `apps/frontend/src/index.css` root variables with full Midnight Pro palette (see spec below). Add IBM Plex Sans + Mono @import. Add `body { font-family: "IBM Plex Sans", system-ui, sans-serif; }` and `.mono { font-family: "IBM Plex Mono", monospace; font-variant-numeric: tabular-nums; }` | `apps/frontend/src/index.css` |
| T-F1-02 | Update `Layout.tsx`: `var(--bg-secondary)` → `var(--card)`, `var(--text-secondary)` → `var(--muted-foreground)`, `var(--text-primary)` → `var(--foreground)` | `apps/frontend/src/components/Layout.tsx` |
| T-F1-03 | Update `FlashOverlay.tsx`: `#dc2626` → `var(--negative)`, `var(--bg-secondary)` → `var(--card)`, `#16a34a` → `var(--positive)` | `apps/frontend/src/components/alerts/FlashOverlay.tsx` |
| T-F1-04 | Update `PredictionMarketsPanel.tsx`: `#22c55e` → `var(--positive)`, `#ef4444` → `var(--negative)`, `var(--text-secondary)` → `var(--muted-foreground)`. Add `fontFamily: "IBM Plex Mono"` + `fontVariantNumeric: "tabular-nums"` to ALL numeric elements (probability %, returns) | `apps/frontend/src/components/PredictionMarketsPanel.tsx` |
| T-F1-05 | Update `SimilarCompaniesPanel.tsx`: `var(--accent)` → `var(--primary)`, `var(--bg-secondary)` → `var(--card)`, `var(--text-secondary)` → `var(--muted-foreground)`. Add IBM Plex Mono to score and percentage elements | `apps/frontend/src/components/SimilarCompaniesPanel.tsx` |
| T-F1-06 | Update `OHLCVChart.tsx`: `upColor: "#22c55e"` → `"#26A69A"`, `downColor: "#ef4444"` → `"#EF5350"` | `apps/frontend/src/components/OHLCVChart.tsx` |
| T-F1-07 | Update `SeverityBadge.tsx`: replace Tailwind `bg-gray-*`/`text-gray-*` classes with inline CSS using `var(--card)`, `var(--foreground)`, `var(--warning)`, `var(--negative)`, `var(--primary)` | `apps/frontend/src/components/alerts/SeverityBadge.tsx` |
| T-F1-08 | Run `pnpm typecheck && pnpm test --run` from `apps/frontend/` — must pass | Validation |

**New `index.css` root block (exact replacement)**:
```css
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {
  --background: #080A0E;
  --card: #10141C;
  --elevated: #181D28;
  --muted: #181D28;
  --border: #232A36;
  --border-strong: #2E3847;
  --foreground: #D1D4DC;
  --muted-foreground: #787B86;
  --dim: #4C5260;
  --primary: #0EA5E9;
  --primary-dim: rgba(14, 165, 233, 0.12);
  --positive: #26A69A;
  --negative: #EF5350;
  --warning: #F59E0B;
  --amber: #F0C040;
  --amber-dim: rgba(240, 192, 64, 0.10);
  --radius: 4px;
}
```

**Acceptance criteria**:
- [ ] No `--bg-primary`, `--bg-secondary`, `--accent`, `--text-secondary` anywhere in `src/`
- [ ] `pnpm typecheck` passes (0 errors)
- [ ] `pnpm test --run` passes (36 tests)
- [ ] IBM Plex fonts imported in `index.css`

---

### Wave F-2: Layout — TopNavBar + Sidebar Redesign

**Track**: Frontend Code
**Depends on**: F-1
**Blocks**: F-3, F-9, F-10, F-11
**Estimated effort**: 60–90 min

**Goal**: Build the full-width TopNavBar and the redesigned sidebar with watchlist + alerts sections. Update `Layout.tsx` to wire both. All pages automatically get the new layout.

**Findings fixed**: F-DESIGN-015, F-DESIGN-016, F-DESIGN-021, F-FE-017

#### Tasks

| ID | Task | Target File |
|----|------|-------------|
| T-F2-01 | Create `TopNavBar.tsx` (44px height, `bg: var(--card)`, `borderBottom: 1px solid var(--border)`): — Left: `◉ WORLDVIEW` logo (IBM Plex Mono 13px 600, amber dot `var(--amber)`) — Center: `GlobalSearchBar` component (300px, `var(--elevated)` bg, `var(--border)` stroke, placeholder "Search ticker, company, entity...  ⌘K" in IBM Plex Mono 12px `var(--dim)`, expands to 400px on focus, `var(--primary)` border on focus) — Right: ticker strip (SPY/QQQ/VIX in IBM Plex Mono 11px), market status dot (green if open, gray if closed), notification bell with badge count, user avatar initials | `apps/frontend/src/components/TopNavBar.tsx` |
| T-F2-02 | Add `GlobalSearchBar.tsx` with results dropdown (320×280px, `var(--card)` bg, `var(--border)` border, `border-radius: var(--radius)`): sections INSTRUMENTS / ENTITIES / NEWS, each with label row (11px CAPS `var(--muted-foreground)`) + result rows. Wire `onSelect` prop: instruments → navigate to `/companies/:id`, entities → navigate to intelligence tab | `apps/frontend/src/components/GlobalSearchBar.tsx` |
| T-F2-03 | Update `Layout.tsx` completely: — Top: `<TopNavBar>` (sticky, z-index: 10) — Left sidebar (200px expanded, collapsible to 52px via toggle): nav items with icons (Dashboard/Companies/Screener/Portfolio/Intelligence/Chat), divider, **Watchlist** section (4 ticker rows: AAPL $173.42 ▲0.42% / NVDA $875.40 ▲1.23% / TSLA $177.20 ▼0.81% / MSFT $422.10 ▲0.33% — IBM Plex Mono 12px for prices), divider, **Recent Alerts** (2 rows with SeverityBadge + truncated message), bottom: Settings + Help icon links — Main: `<Outlet>` in remaining space | `apps/frontend/src/components/Layout.tsx` |
| T-F2-04 | Add `useMarketStatus` hook returning `{ isOpen: boolean, label: string }` based on current time (EST M-F 9:30–16:00) | `apps/frontend/src/hooks/useMarketStatus.ts` |
| T-F2-05 | Add gateway method: `searchGlobal: (query: string) => request<SearchResults>('/v1/search?q=' + encodeURIComponent(query))` to gateway-client.ts | `apps/frontend/src/lib/gateway-client.ts` |
| T-F2-06 | Run `pnpm typecheck && pnpm test --run` | Validation |

**Acceptance criteria**:
- [ ] Top nav visible on all pages with logo + search + ticker strip + market status
- [ ] Sidebar shows nav items + watchlist 4 rows + recent alerts
- [ ] Sidebar collapses to 52px icon-only state on toggle
- [ ] All existing routes still work (`/`, `/companies`, etc.)
- [ ] Tests pass

---

### Wave F-3: CompanyDetailPage — Header Rows + Tab Bar

**Track**: Frontend Code
**Depends on**: F-2
**Blocks**: F-4, F-5, F-6, F-7, F-8
**Estimated effort**: 60 min

**Goal**: Build the 4-row instrument header and 5-tab bar for CompanyDetailPage. This is the foundation for all 5 tab states (F-4 through F-8).

**Findings fixed**: F-FE-003, F-DESIGN-006, F-DESIGN-007

#### Tasks

| ID | Task | Target File |
|----|------|-------------|
| T-F3-01 | Create `InstrumentHeader.tsx` with 4 rows: **Row 1** (40px, `var(--card)` bg): logo + company name (IBM Plex Sans 14px 600 `var(--foreground)`) + ticker chip (`var(--primary)` bg, IBM Plex Mono 12px 600 white) + exchange badge + sector + subsector (12px `var(--muted-foreground)`). **Row 2** (44px, border-bottom `var(--border)`): price (IBM Plex Mono 28px 600 `var(--foreground)`) + delta amount + delta% (colored `var(--positive)`/`var(--negative)`) + vertical divider + 6 metric chips (P/E / P/B / P/S / FwdP/E / Mkt Cap / Volume — 11px `var(--muted-foreground)` label + 12px Mono value). **Row 3** (40px, border-bottom): "52W RANGE" label + min price + SVG range bar (full width minus labels, `var(--border)` bg, `var(--primary)` fill at current%, dot at position) + max price + current. **Row 4** (36px, `var(--card)` bg, border-bottom `var(--border)`): `[★ Watchlist]` `[Workspace]` `[🔔 Set Alert]` `[⤴ Share]` buttons (`var(--primary-dim)` bg, `var(--primary)` text, `border-radius: var(--radius)`, 12px Mono) | `apps/frontend/src/components/instrument/InstrumentHeader.tsx` |
| T-F3-02 | Create `InstrumentTabs.tsx`: 5 tabs [Overview/Fundamentals/Intelligence/News/Chat]. Active tab: `var(--foreground)` 13px 500 + 2px bottom border `var(--border-strong)`. Inactive: `var(--muted-foreground)` 12px 400. Container: 36px height, `var(--card)` bg, border-bottom `var(--border)`. `onTabChange` prop. | `apps/frontend/src/components/instrument/InstrumentTabs.tsx` |
| T-F3-03 | Refactor `CompanyDetailPage.tsx`: add `activeTab` state (default: "overview"). Render `<InstrumentHeader instrument={...}>` + `<InstrumentTabs activeTab={activeTab} onChange={setActiveTab}>` above content area. Add `useTanstackQuery` hook for instrument data (`gateway.getInstrumentQuote(id)`). Render placeholder `<div>Content: {activeTab}</div>` in content area (actual content built in F-4 through F-8). | `apps/frontend/src/pages/CompanyDetailPage.tsx` |
| T-F3-04 | Run `pnpm typecheck && pnpm test --run` | Validation |

**Acceptance criteria**:
- [ ] CompanyDetailPage shows 4-row header + 5-tab bar
- [ ] Clicking tabs updates content area label
- [ ] Row 2 price in IBM Plex Mono 28px
- [ ] Range bar in Row 3 is SVG with proportional fill
- [ ] Tests pass

---

### Wave F-4: P4 State A Right Panel + State E Chat Tab

**Track**: Frontend Code
**Depends on**: F-3
**Blocks**: T-1
**Estimated effort**: 60 min

**Goal**: Complete State A (Overview) with the right panel (Key Metrics + Analyst Consensus + Next Earnings) and implement the State E Chat tab.

**Findings fixed**: F-DESIGN-005

#### Tasks

| ID | Task | Target File |
|----|------|-------------|
| T-F4-01 | Create `KeyMetricsPanel.tsx` (380px width, `var(--card)` bg): **KEY METRICS** section (11px CAPS label `var(--muted-foreground)`, border-bottom `var(--border)`): 3×3 grid of metric cells (P/E 45.4 / P/B 12.8 / P/S 28.2 / FwdP/E 38.2 / EV/EBITDA 38.7 / PEG 2.1 / ROE 87.3% / Div 0.02% / Beta 1.87) — label 10px `var(--muted-foreground)` + value IBM Plex Mono 12px 600 `var(--foreground)`. **ANALYST CONSENSUS** section: price range SVG bar (min $720 / mean $890 dot / max $1,050) + counts "22 Buy  8 Hold  2 Sell" + "Upside: +1.7%" in `var(--positive)`. **NEXT EARNINGS** section: "Q3 2026 · July 24 (23 days)" + "EPS est: $0.64" in Mono. | `apps/frontend/src/components/instrument/KeyMetricsPanel.tsx` |
| T-F4-02 | Update `CompanyDetailPage.tsx` State A layout: 2-column (main chart area 860px + right panel 380px). Render `<KeyMetricsPanel>` in right column. Existing `<OHLCVChart>` goes in left column. | `apps/frontend/src/pages/CompanyDetailPage.tsx` |
| T-F4-03 | Create `ChatTab.tsx` (State E): **Context bar** (36px, `var(--amber-dim)` bg, `var(--amber)` 1px border-bottom): "◉ Analyzing:" label + instrument name chip. **Conversation thread** (scrollable, `var(--background)` bg): user message bubbles (`var(--elevated)` bg, 12px Sans) + AI response bubbles (`var(--card)` bg, `var(--border)` 1px border, citations as `var(--primary)` inline links). Contradiction warning row: `var(--amber-dim)` bg + amber text. **Input bar** (44px pinned bottom, `var(--card)` bg, border-top `var(--border)`): text input + Send button (`var(--primary)` bg). Wire to existing `ChatUI` or replicate with `gateway.sendChatMessage()`. | `apps/frontend/src/components/instrument/ChatTab.tsx` |
| T-F4-04 | Wire `ChatTab` into `CompanyDetailPage`: when `activeTab === "chat"`, render `<ChatTab instrumentId={id} instrumentName={...}>` | `apps/frontend/src/pages/CompanyDetailPage.tsx` |
| T-F4-05 | Run `pnpm typecheck && pnpm test --run` | Validation |

**Acceptance criteria**:
- [ ] State A shows 2-column layout: OHLCV chart left + metrics panel right
- [ ] Key Metrics: 9 metrics in 3×3 grid with Mono values
- [ ] State E (Chat tab): context bar with amber border, message thread, input bar

---

### Wave F-5: P4 State D — News Tab Implementation

**Track**: Frontend Code
**Depends on**: F-3 ← can run in parallel with F-4, F-6, F-7, F-8
**Blocks**: T-1
**Estimated effort**: 45–60 min

**Goal**: Build the News tab for CompanyDetailPage — filter bar + article cards with tier badges + relevance scores.

**Findings fixed**: F-DESIGN-004, F-DESIGN-014

#### Tasks

| ID | Task | Target File |
|----|------|-------------|
| T-F5-01 | Enhance `NewsList.tsx` to accept `showScores?: boolean` and `showFilters?: boolean` props. When `showScores=true`, render each article card as 88px row: score chip (IBM Plex Mono 11px 600, DEEP=`var(--primary)` / MED=`var(--warning)` / LIGHT=`var(--dim)`) + tier badge (40×20px chip with colored border matching score color) + impact chip (⬆% in `var(--positive)` / ⬇% in `var(--negative)` / – in `var(--muted-foreground)`) + source+time (10px `var(--dim)`) + headline (IBM Plex Sans 12px 500 `var(--foreground)`, 2-line clamp) + excerpt (11px `var(--muted-foreground)`, 2-line `-webkit-line-clamp`) + entity chips (10px bg:`var(--elevated)` `var(--dim)` text, 3px corner-radius) | `apps/frontend/src/components/NewsList.tsx` |
| T-F5-02 | Create `NewsTab.tsx`: **Filter bar** (40px, `var(--card)` bg, border-bottom `var(--border)`): [By Relevance ▼] ghost chip + [By Date] chip + vertical divider + date range display + [DEEP] [MED] [LIGHT] tier toggles. Toggle state: active chip has `var(--primary-dim)` bg + `var(--primary)` 1px border (DEEP), warning variants for MED, `var(--elevated)` for LIGHT. Render `<NewsList showScores showFilters>`. "Load 20 more" button at bottom. | `apps/frontend/src/components/instrument/NewsTab.tsx` |
| T-F5-03 | Wire `NewsTab` into `CompanyDetailPage`: when `activeTab === "news"`, render `<NewsTab entityId={entityId}>`. Call `gateway.getEntityNews(entityId, { sort, tiers })` (add method to gateway-client.ts if missing). | `apps/frontend/src/pages/CompanyDetailPage.tsx`, `apps/frontend/src/lib/gateway-client.ts` |
| T-F5-04 | Run `pnpm typecheck && pnpm test --run` | Validation |

**Acceptance criteria**:
- [ ] News tab shows filter bar with tier toggles
- [ ] Article cards are 88px with score + tier badge + impact chip + headline + entity chips
- [ ] Tier badges use correct colors (DEEP=sky, MED=warning, LIGHT=dim)
- [ ] Tests pass

---

### Wave F-6: P4 State B — Fundamentals Tab Implementation

**Track**: Frontend Code
**Depends on**: F-3 ← can run in parallel with F-4, F-5, F-7, F-8
**Blocks**: T-1
**Estimated effort**: 60–75 min

**Goal**: Build the Fundamentals tab — compact chart, period selector, accordion with financial data tables.

**Findings fixed**: F-DESIGN-002

#### Tasks

| ID | Task | Target File |
|----|------|-------------|
| T-F6-01 | Create `RevenueBarChart.tsx` using SVG (no D3): 8 bars in `var(--primary)` fill, proportional heights, x-axis quarter labels (IBM Plex Mono 10px `var(--muted-foreground)`). No y-axis (space saving). Tooltip on hover: quarter + revenue value. Props: `data: {quarter: string, value: number}[]`, `height?: number`. | `apps/frontend/src/components/charts/RevenueBarChart.tsx` |
| T-F6-02 | Create `AccordionSection.tsx`: generic accordion with `title: string`, `rowCount?: number` display in header, `isOpen: boolean`, `onToggle` prop. Open: `▼` chevron, content visible. Closed: `▶` chevron, 36px header only. Header: 36px `var(--elevated)` bg, IBM Plex Sans 11px CAPS 500 `var(--muted-foreground)`, border-bottom `var(--border)`. | `apps/frontend/src/components/AccordionSection.tsx` |
| T-F6-03 | Create `FundamentalsTab.tsx`: **Period selector** (36px, top): [Annual] [Quarterly] chips — active chip `var(--primary-dim)` bg + `var(--primary)` border; inactive `var(--elevated)`. **Compact chart** (260px): `<RevenueBarChart>` with period context. **Accordion sections**: INCOME & GROWTH (open by default) — financial table with columns Quarter/Revenue/GrossProfit/NetIncome/EPS/YoY%; 4 data rows in IBM Plex Mono 12px right-aligned, alternating `var(--card)`/`var(--background)` bg; positive EPS beat `var(--positive)`, miss `var(--negative)`. Then 4 collapsed sections: BALANCE SHEET / CASH FLOW / VALUATION / COMPANY & OWNERSHIP. | `apps/frontend/src/components/instrument/FundamentalsTab.tsx` |
| T-F6-04 | Wire into `CompanyDetailPage`: `activeTab === "fundamentals"` → `<FundamentalsTab instrumentId={...}>`. Add `gateway.getFinancialFundamentals(id, period)` to gateway-client if missing. | `apps/frontend/src/pages/CompanyDetailPage.tsx`, `apps/frontend/src/lib/gateway-client.ts` |
| T-F6-05 | Run `pnpm typecheck && pnpm test --run` | Validation |

**Acceptance criteria**:
- [ ] Period selector chips toggle between Annual/Quarterly
- [ ] Revenue bar chart renders proportional SVG bars
- [ ] Income & Growth open: table with Mono 12px right-aligned values
- [ ] 4 collapsed sections stack below with chevron indicators

---

### Wave F-7: P4 State C — Intelligence Tab Implementation

**Track**: Frontend Code
**Depends on**: F-3 ← can run in parallel with F-4, F-5, F-6, F-8
**Blocks**: T-1
**Estimated effort**: 75–90 min (most complex code wave)

**Goal**: Build the Intelligence tab — entity graph (SVG-based), similar instruments, contradictions, prediction signals panels, and bottom accordions.

**Findings fixed**: F-DESIGN-003

#### Tasks

| ID | Task | Target File |
|----|------|-------------|
| T-F7-01 | Create `EntityGraph.tsx` using SVG (no D3 dependency): render entity nodes as colored circles (company=`var(--primary)`, person=`var(--positive)`, fund=`var(--amber)`) with text labels in IBM Plex Mono 10px. Render relationship edges as SVG `<line>` elements (stroke=`var(--border-strong)`, strokeWidth proportional to confidence 1–3px). Filter row above graph: hop depth chips + confidence display + entity type checkboxes. Legend: 3 colored dots with labels. Props: `data: EntityGraphData` (nodes + edges). Static positions (no force layout in V1). | `apps/frontend/src/components/EntityGraph.tsx` |
| T-F7-02 | Create `IntelligenceTab.tsx` with 2-column layout (left 860px + right 380px): **Left column**: full-height `<EntityGraph>` (304px) + Recent Claims accordion (180px, 3 rows: POSITIVE/NEUTRAL/NEGATIVE badge + text + confidence bar 60px `var(--primary)` fill) + Temporal Events accordion (168px, 3 rows: type badge + text + right-aligned date). **Right column**: Similar Instruments panel (section header + 3 ticker rows in Mono 12px + "Compare in Screener" footer link `var(--primary)`) + Contradictions panel (red label `var(--negative)` + [STRONG] badge + contradiction text) + Prediction Market Signals panel (2 probability rows: question text + progress bar 120px `var(--primary)` fill + % label + "Source: Polymarket" footer). | `apps/frontend/src/components/instrument/IntelligenceTab.tsx` |
| T-F7-03 | Wire into `CompanyDetailPage`: `activeTab === "intelligence"` → `<IntelligenceTab entityId={...}>`. Add gateway methods: `gateway.getEntityGraph(entityId, hopDepth?)` and `gateway.getEntityInsight(entityId)` to gateway-client.ts. | `apps/frontend/src/pages/CompanyDetailPage.tsx`, `apps/frontend/src/lib/gateway-client.ts` |
| T-F7-04 | Run `pnpm typecheck && pnpm test --run` | Validation |

**Acceptance criteria**:
- [ ] Entity graph renders 6+ nodes as colored SVG circles with labels
- [ ] Edges connect related nodes with proportional stroke width
- [ ] Recent Claims: POSITIVE (teal badge), NEUTRAL, NEGATIVE (red badge) variants
- [ ] Right column has all 3 panels stacked
- [ ] Prediction bars have proportional sky-blue fill

---

### Wave F-8: P4 State F — Full-Screen Chart + Gateway Client Completion

**Track**: Frontend Code
**Depends on**: F-3 ← can run in parallel with F-4, F-5, F-6, F-7
**Blocks**: T-1
**Estimated effort**: 60 min

**Goal**: Build the full-screen chart view (accessible via "Expand Chart" button) and complete all missing gateway client methods.

**Findings fixed**: F-DESIGN-023, F-DESIGN-010

#### Tasks

| ID | Task | Target File |
|----|------|-------------|
| T-F8-01 | Add all missing gateway client methods to `gateway-client.ts`: `getEntityGraph(entityId, hopDepth?)`, `getEntityPredictions(entityId)`, `getFinancialFundamentals(instrumentId, period)`, `getAnalystConsensus(instrumentId)`, `getEntityInsight(entityId)`, `getEntityNews(entityId, opts?)`, `getInstrumentQuote(instrumentId)`. Use same `request<T>` pattern as existing methods. | `apps/frontend/src/lib/gateway-client.ts` |
| T-F8-02 | Create `FullScreenChart.tsx`: **Top toolbar** (36px, `var(--card)` bg, border-bottom `var(--border)`): timeframe chips [1D/1W/1M/3M/6M/1Y/5Y/All] (active: `var(--primary-dim)` bg + `var(--primary)` border) + vertical divider + overlay chips [MA20/MA50/MA200/BB/VWAP] (toggle). **Drawing tools sidebar** (32px wide, left side, `var(--card)` bg): 6 icon-only tools (cursor/line/rect/fib/text/delete). **Main chart**: full-width `<OHLCVChart>` with passed timeframe + overlays. **Volume panel** (80px below): volume bars in `var(--muted-foreground)`. **Indicator panels**: RSI panel (80px, `var(--negative)` line) + MACD panel (80px, histogram) when their overlays are active. | `apps/frontend/src/components/instrument/FullScreenChart.tsx` |
| T-F8-03 | In `InstrumentHeader.tsx` Row 4, add expand chart button that navigates to `?view=graph` query param | `apps/frontend/src/components/instrument/InstrumentHeader.tsx` |
| T-F8-04 | In `CompanyDetailPage.tsx`: detect `?view=graph` URL param → render `<FullScreenChart>` full-width in place of tab content | `apps/frontend/src/pages/CompanyDetailPage.tsx` |
| T-F8-05 | Run `pnpm typecheck && pnpm test --run` | Validation |

**Acceptance criteria**:
- [ ] Expand chart button routes to `?view=graph`
- [ ] Full-screen chart shows: timeframe toolbar + drawing tools sidebar + OHLCV chart + volume panel
- [ ] All 7 missing gateway methods added with correct type signatures
- [ ] Tests pass

---

### Wave F-9: Dashboard Page Redesign

**Track**: Frontend Code
**Depends on**: F-2 ← can run in parallel with F-3, F-10, F-11
**Blocks**: F-12, T-1
**Estimated effort**: 90 min (large page)

**Goal**: Rebuild `DashboardPage.tsx` from the current 36-line stub into the full 8-section professional financial terminal dashboard.

**Findings fixed**: F-DESIGN-008

#### Tasks

| ID | Task | Target File |
|----|------|-------------|
| T-F9-01 | Create `MorningBrief.tsx` (card, `var(--card)` bg, `var(--amber)` 1px border, top-left `var(--amber-dim)` gradient fade): **Header**: "◉ MORNING BRIEF" label (IBM Plex Mono 11px `var(--amber)`) + "AI — 06:32 ET" timestamp right. **Body**: 2–3 sentence briefing text (IBM Plex Sans 13px `var(--foreground)`). **Topic chips** (8 chips): entity names in `var(--elevated)` bg + `var(--muted-foreground)` text. Props: `brief: MorningBriefData`, `loading?: boolean`. Use TanStack Query with `staleTime: 5 * 60 * 1000`. | `apps/frontend/src/components/dashboard/MorningBrief.tsx` |
| T-F9-02 | Create `MarketHeatmap.tsx`: 28 sector tiles in a 7×4 grid (or proportional). Each tile: ticker (IBM Plex Mono 10px 600) + sector abbrev + performance % (Mono 11px). Tile background: 7-step color scale from `var(--negative)` (−3%+) through neutral `var(--elevated)` (≈0%) to `var(--positive)` (+3%+). Tile size: proportional to market cap. Props: `sectors: HeatmapTile[]`. | `apps/frontend/src/components/dashboard/MarketHeatmap.tsx` |
| T-F9-03 | Create `TopMovers.tsx`: table with 5 columns TICKER/NAME/PRICE/DAILY%/SIGNAL (5 rows). DAILY%: `var(--positive)` if positive, `var(--negative)` if negative. SIGNAL: DEEP/MED/LIGHT tier chip. IBM Plex Mono 12px for numbers. Header row 32px `var(--elevated)` bg. Data rows 32px alternating `var(--card)`/`var(--background)`. | `apps/frontend/src/components/dashboard/TopMovers.tsx` |
| T-F9-04 | Create `EconomicCalendar.tsx`: table with upcoming economic events. Columns: DATE (Mono, `var(--muted-foreground)`) / RELEASE (Sans 12px) / PRIOR (Mono) / EXPECTED (Mono `var(--warning)`) / IMPACT (chip: HIGH/MED/LOW). 6 rows. Header 32px `var(--elevated)`. | `apps/frontend/src/components/dashboard/EconomicCalendar.tsx` |
| T-F9-05 | Rebuild `DashboardPage.tsx` with 2-column grid layout (sidebar 200px already provided by Layout.tsx, so main content area ~1040px): **Row 1** (2-col): `<MorningBrief>` | `<PortfolioSummary>` (4 KPIs: Total Value Mono 20px / Today P&L / IRR / Positions). **Row 2** (2-col): `<MarketHeatmap>` | `<TopMovers>`. **Row 3** (full width): Intelligence Stream (`<NewsList showScores>` for top articles, 3 visible) | Watchlist News (5 latest for watchlist entities). **Row 4** (2-col): `<EconomicCalendar>` | `<AlertCard>` list (last 5 from `AlertStreamContext`). All sections use TanStack Query with appropriate staleTime. | `apps/frontend/src/pages/DashboardPage.tsx` |
| T-F9-06 | Add `PortfolioSummary.tsx` (card, 4 KPI cells): Total Value Mono 20px 600 / Today P&L colored Mono 14px / IRR Mono 14px / Positions count Mono 18px | `apps/frontend/src/components/dashboard/PortfolioSummary.tsx` |
| T-F9-07 | Run `pnpm typecheck && pnpm test --run` | Validation |

**Acceptance criteria**:
- [ ] Dashboard shows all 8 sections in 4-row grid
- [ ] Morning Brief has amber left border and topic chips
- [ ] Market Heatmap shows 20+ sector tiles with color scale
- [ ] Top Movers table has 5 rows with Mono prices and tier badges
- [ ] Economic Calendar shows 6+ upcoming releases
- [ ] Recent Alerts from `AlertStreamContext` visible

---

### Wave F-10: Portfolio Page + Screener Styling

**Track**: Frontend Code
**Depends on**: F-2 ← can run in parallel with F-3, F-9, F-11
**Blocks**: T-1
**Estimated effort**: 60–75 min

**Goal**: Rebuild `PortfolioPage.tsx` with strategy cards + holdings table. Restyle `ScreenerPage.tsx` to match design system.

**Findings fixed**: F-DESIGN-011, F-DESIGN-018

#### Tasks

| ID | Task | Target File |
|----|------|-------------|
| T-F10-01 | Create `StrategyCard.tsx`: card (240×120px, `var(--card)` bg, `var(--border)` stroke, `var(--radius)` corner). Active state: `var(--primary-dim)` bg + `var(--primary)` 1px border. Header: strategy name 9px CAPS `var(--muted-foreground)`. Body: total value IBM Plex Mono 18px 600 + daily P&L Mono 12px colored + position count 11px `var(--dim)`. Top-right: sparkline SVG `<path>` 80×20px (simple stroke-only line chart in `var(--primary)`). Props: `strategy: Strategy`, `isActive: boolean`. | `apps/frontend/src/components/portfolio/StrategyCard.tsx` |
| T-F10-02 | Create `HoldingsTable.tsx`: column headers (32px `var(--elevated)` bg): ★/TICKER/COMPANY/SECTOR/QTY/AVG COST/CURRENT/UNREAL.$/UNREAL.%/DAILY%/WEIGHT%/ACTIONS. All numeric columns: IBM Plex Mono 12px right-aligned. UNREAL.$, UNREAL.%, DAILY%: `var(--positive)` if positive, `var(--negative)` if negative. Row height 32px, alternating `var(--card)`/`var(--background)`. WEIGHT% column: 40×6px mini bar `var(--primary)` fill. Subtotal footer row `var(--elevated)` bg. | `apps/frontend/src/components/portfolio/HoldingsTable.tsx` |
| T-F10-03 | Rebuild `PortfolioPage.tsx`: **Summary row** (56px, `var(--card)` bg, border-bottom `var(--border)`): 5 metric cells with vertical dividers — Total Value Mono 20px 600 / Today P&L `var(--positive)` / Unrealized P&L / IRR / Positions. **Strategy cards** (124px y-offset): 3 `<StrategyCard>` side-by-side at 16px gap. **Tabs** (36px): [Holdings●/Transactions/Analytics/Watchlists/Settings]. **Holdings table**: `<HoldingsTable>` for active holdings. Wire to `gateway.getPortfolioSummary()` and `gateway.getPortfolioHoldings()`. | `apps/frontend/src/pages/PortfolioPage.tsx` |
| T-F10-04 | Restyle `ScreenerPage.tsx` table: header row 32px `var(--elevated)` bg + border-bottom `var(--border)`. Data rows 32px alternating `var(--card)`/`var(--background)`. SCORE column: 40×6px bar `var(--primary)` fill. All numeric cells Mono 12px. Ticker cells Mono 600 `var(--primary)`. Column header labels 10px CAPS `var(--muted-foreground)`. | `apps/frontend/src/pages/ScreenerPage.tsx` |
| T-F10-05 | Add missing gateway methods if not already added by F-8: `getPortfolioSummary()`, `getPortfolioHoldings()`, `getPortfolioStrategies()` | `apps/frontend/src/lib/gateway-client.ts` |
| T-F10-06 | Run `pnpm typecheck && pnpm test --run` | Validation |

**Acceptance criteria**:
- [ ] Portfolio: summary row + 3 strategy cards + holdings table with Mono numerics
- [ ] Holdings rows: P&L colored correctly (positive=teal, negative=red)
- [ ] Screener: table matches terminal density (32px rows, Mono numbers, score bar)
- [ ] Tests pass

---

### Wave F-11: Landing Page + Settings + Onboarding

**Track**: Frontend Code
**Depends on**: F-2 ← can run in parallel with F-3, F-9, F-10
**Blocks**: T-1
**Estimated effort**: 90 min (three pages)

**Goal**: Build the landing page (10 sections), settings page (6-section nav rail), and onboarding flow (6-step).

**Findings fixed**: F-DESIGN-013, F-DESIGN-019, F-DESIGN-020

#### Tasks

| ID | Task | Target File |
|----|------|-------------|
| T-F11-01 | Create `LandingPage.tsx` — outside `<Layout>` (no sidebar on landing page). 10 sections: **(1) NavBar** (44px, transparent, sticky): amber `◉ WORLDVIEW` + nav links + amber "Get Started →" CTA button. **(2) Hero**: H1 52px 700 "Professional Market Intelligence" + amber subheading "Without the Bloomberg Bill." + 2 CTAs + product screenshot. **(3) Stats Bar**: 4 metrics (10M+ data points / 18 integrated sources / 500K+ entities / <5s latency). **(4) Features Spotlight**: annotated screenshot + 6-item checkmark list. **(5) Features Grid**: 6 cards (Entity Graph / Prediction Markets / AI Research / Multi-source / Flash Alerts / Portfolio). **(6) Comparison Table**: 6 competitors, Worldview column highlighted `var(--primary-dim)` with `var(--primary)` border. **(7) How It Works**: 3-step horizontal flow with numbered circles `var(--primary)`. **(8) Pricing**: 3 cards (Free / PRO / Enterprise), PRO card highlighted. **(9) FAQ**: 4 accordion items. **(10) CTA Banner + Footer**. All section backgrounds alternating `var(--background)` / `var(--card)`. | `apps/frontend/src/pages/LandingPage.tsx` |
| T-F11-02 | Create `SettingsPage.tsx` (inside `<Layout>`): 6-section nav rail (Profile / Notifications / Appearance / Keyboard Shortcuts / Subscription / Data & Privacy). Active section: `var(--primary-dim)` bg, `var(--primary)` left border 2px. Each section is a `<div>` with heading + form fields appropriate to the section. Profile: name/email/avatar. Notifications: toggle switches for email/push/alert thresholds. Appearance: theme toggle (dark-only in MVP) + density (compact/normal). | `apps/frontend/src/pages/SettingsPage.tsx` |
| T-F11-03 | Create `OnboardingPage.tsx` (outside `<Layout>`, centered): 6-step flow with progress dots at top. Steps: Welcome (product logo + tagline + Get Started) → Role (4 options: Trader/Analyst/PM/Other) → Markets (checkboxes: US Equities/ETFs/Crypto/Futures) → Watchlist (type tickers to add, 3 minimum) → Layout (3 preset options: Focused/Research/Trading) → Complete (checkmark + "Go to Dashboard" CTA). Progress: active dot `var(--primary)`, completed `var(--positive)`, pending `var(--elevated)`. | `apps/frontend/src/pages/OnboardingPage.tsx` |
| T-F11-04 | Update `App.tsx`: add routes `/landing` (LandingPage, no Layout), `/settings` (SettingsPage, inside Layout), `/onboarding` (OnboardingPage, no Layout). Update `/` route: show LandingPage if `!isAuthenticated`, Dashboard if authenticated. Add `useAuth` hook (stub returns `false` in V1). | `apps/frontend/src/App.tsx` |
| T-F11-05 | Run `pnpm typecheck && pnpm test --run` | Validation |

**Acceptance criteria**:
- [ ] Landing page renders all 10 sections without Layout sidebar
- [ ] Comparison table has Worldview column highlighted in sky-blue
- [ ] Settings page: 6-section nav rail, active section highlighted
- [ ] Onboarding: 6-step flow with progress dots, step transitions work
- [ ] All existing routes unaffected

---

### Wave F-12: Workspace Page

**Track**: Frontend Code
**Depends on**: F-9 (reuses Dashboard components as panels)
**Blocks**: T-1
**Estimated effort**: 90–120 min

**Goal**: Build the configurable research terminal Workspace page with draggable/resizable panels.

**Findings fixed**: F-DESIGN-012

#### Tasks

| ID | Task | Target File |
|----|------|-------------|
| T-F12-01 | Add `@dnd-kit/core` and `@dnd-kit/sortable` to `apps/frontend/package.json` (exact versions, pnpm). These are needed for drag-and-drop panels. | `apps/frontend/package.json` |
| T-F12-02 | Create `PanelContainer.tsx`: standard panel wrapper (flex column, `var(--card)` bg, `var(--border)` 1px border, `var(--radius)`). **Header** (28px, `var(--elevated)` bg, border-bottom `var(--border)`): drag handle dots + panel title (11px CAPS `var(--muted-foreground)`) + ticker selector input + ⚙ settings icon + × close button. **Content**: `{children}`. Props: `panelId`, `title`, `onClose`. | `apps/frontend/src/components/workspace/PanelContainer.tsx` |
| T-F12-03 | Create 6 panel components (each wraps an existing feature component inside `<PanelContainer>`): `ChartPanel.tsx` (wraps OHLCVChart), `WatchlistPanel.tsx` (wraps watchlist list), `NewsFeedPanel.tsx` (wraps NewsList), `AIChatPanel.tsx` (wraps ChatUI), `ScreenerPanel.tsx` (wraps ScreenerPage table), `AlertFeedPanel.tsx` (wraps Alert list from AlertStreamContext). All in `apps/frontend/src/components/workspace/panels/`. | `apps/frontend/src/components/workspace/panels/*.tsx` |
| T-F12-04 | Create `PanelPicker.tsx`: modal (640×480px, `var(--card)` bg, `var(--border)` border, centered overlay). Title "Add Panel". Grid of 6 panel cards (each: icon + name + description). Click to dispatch `addPanel(panelId)` and close modal. | `apps/frontend/src/components/workspace/PanelPicker.tsx` |
| T-F12-05 | Create `WorkspacePage.tsx`: **Top bar** (44px, `var(--card)` bg, border-bottom `var(--border)`): amber `◉ WORLDVIEW` + editable layout name (click to edit inline, IBM Plex Mono 12px `var(--foreground)`) + [+ Add Panel] button + [Save] button + [Layouts ▾] dropdown. **Panel grid**: CSS Grid with minimum cell 400×300px, drag-to-reorder via `@dnd-kit/sortable`. Default workspace: 2 panels (ChartPanel AAPL + NewsFeedPanel). Persist layouts to `localStorage` under key `worldview-workspace`. | `apps/frontend/src/pages/WorkspacePage.tsx` |
| T-F12-06 | Add `/workspace` route to `App.tsx` (inside Layout) and sidebar nav item to `Layout.tsx`. | `apps/frontend/src/App.tsx`, `apps/frontend/src/components/Layout.tsx` |
| T-F12-07 | Run `pnpm typecheck && pnpm test --run` | Validation |

**Acceptance criteria**:
- [ ] Workspace page renders with 2 default panels
- [ ] "Add Panel" opens PanelPicker modal with 6 panel options
- [ ] Panels can be closed (×) and re-added
- [ ] Layout persists to localStorage on Save
- [ ] Panel grid reorders when panels are dragged

---

### Wave T-1: Frontend Test Coverage

**Track**: Frontend Tests
**Depends on**: F-4, F-5, F-6, F-7, F-8, F-9, F-10, F-11, F-12, S-1
**Blocks**: none (final wave)
**Estimated effort**: 60–90 min

**Goal**: Add 7 new test files covering all newly built components and pages. Increase test count from 36 to 70+.

**Findings fixed**: F-FE-012, F-FE-013, F-FE-014, F-FE-015, F-FE-016

#### Tasks

| ID | Task | Target File | Tests |
|----|------|-------------|-------|
| T-T1-01 | `Layout.test.tsx`: TopNavBar present, sidebar shows nav items, sidebar collapse toggle, Outlet renders child, watchlist section present | `apps/frontend/tests/Layout.test.tsx` | 6 tests |
| T-T1-02 | `CompanyDetailPage.test.tsx`: InstrumentHeader renders 4 rows, InstrumentTabs renders 5 tabs, tab click changes active tab, OHLCVChart present in overview, State A right panel renders, loading state shows skeleton | `apps/frontend/tests/CompanyDetailPage.test.tsx` | 8 tests |
| T-T1-03 | `DashboardPage.test.tsx`: MorningBrief renders with amber border, MarketHeatmap renders tiles, TopMovers renders 5 rows, Recent Alerts from context present, EconomicCalendar renders events | `apps/frontend/tests/DashboardPage.test.tsx` | 7 tests |
| T-T1-04 | `ScreenerPage.test.tsx`: table header renders, data rows render, score bars visible, Mono font class applied to numeric cells | `apps/frontend/tests/ScreenerPage.test.tsx` | 4 tests |
| T-T1-05 | `InstrumentHeader.test.tsx`: all 4 rows present, price in Mono class, range bar SVG present, action buttons present | `apps/frontend/tests/InstrumentHeader.test.tsx` | 5 tests |
| T-T1-06 | `InstrumentTabs.test.tsx`: 5 tabs render, active tab has correct aria-selected, click triggers onTabChange | `apps/frontend/tests/InstrumentTabs.test.tsx` | 3 tests |
| T-T1-07 | `NewsTab.test.tsx`: filter bar renders with 3 tier toggles, NewsList receives showScores prop, article rows are 88px height | `apps/frontend/tests/NewsTab.test.tsx` | 4 tests |
| T-T1-08 | Run `pnpm test --run` — all tests pass. Minimum total: 70+ tests | Validation | — |

**Acceptance criteria**:
- [ ] 7 new test files, all passing
- [ ] Total vitest count ≥ 70
- [ ] `pnpm typecheck` passes (0 errors)
- [ ] No test uses `any` type cast

---

## Wave Tracking Summary

| Wave | Track | Status | Depends On | Can Run With |
|------|-------|--------|-----------|--------------|
| C-1 | Canvas | pending | — | F-1, S-1 |
| C-2 | Canvas | pending | C-1 | F-2 |
| C-3 | Canvas | pending | C-2 | F-3, F-9, F-10, F-11 |
| C-4 | Canvas | pending | C-3 | F-4..F-8 |
| C-5 | Canvas | pending | C-4 | F-12 |
| C-6 | Canvas | pending | C-5 | T-1 |
| S-1 | Backend | pending | — | C-1, F-1 |
| F-1 | Frontend | pending | — | C-1, S-1 |
| F-2 | Frontend | pending | F-1 | C-2 |
| F-3 | Frontend | pending | F-2 | C-3, F-9, F-10, F-11 |
| F-4 | Frontend | pending | F-3 | F-5, F-6, F-7, F-8, C-4 |
| F-5 | Frontend | pending | F-3 | F-4, F-6, F-7, F-8, C-4 |
| F-6 | Frontend | pending | F-3 | F-4, F-5, F-7, F-8, C-4 |
| F-7 | Frontend | pending | F-3 | F-4, F-5, F-6, F-8, C-4 |
| F-8 | Frontend | pending | F-3 | F-4, F-5, F-6, F-7, C-4 |
| F-9 | Frontend | pending | F-2 | F-3, F-10, F-11, C-3 |
| F-10 | Frontend | pending | F-2 | F-3, F-9, F-11, C-3 |
| F-11 | Frontend | pending | F-2 | F-3, F-9, F-10, C-3 |
| F-12 | Frontend | pending | F-9 | C-5 |
| T-1 | Tests | pending | F-4..F-12, S-1 | C-6 |

---

## Validation Gate (per wave)

Every wave must pass before marking done:
- [ ] `pnpm typecheck` passes (frontend waves)
- [ ] `pnpm test --run` passes (frontend waves)
- [ ] `python -m pytest tests/ -m "unit"` passes (backend waves)
- [ ] `get_screenshot()` validates output (canvas waves)
- [ ] Relevant `REDESIGN_PLAN.md` status updated
- [ ] `DESIGN.md` header status updated
- [ ] `TRACKING.md` wave count updated

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Pencil.dev MCP disconnects mid-canvas session | Medium | High | Save progress in batches; document last-known node IDs; each canvas wave is self-contained |
| C() opacity:0 inheritance from WoVQh | High (known pattern) | Medium | Always `batch_get` before building; add `opacity:1` to every `C()` call explicitly |
| F-1 CSS changes break existing tests | Low | Medium | Run `pnpm test --run` after every file change; test expectations don't assert CSS vars directly |
| Gateway methods not yet implemented in S9 | Medium | Low (frontend shows loading/empty states gracefully) | Use TanStack Query with fallback to empty arrays; gateway stubs are OK for V1 display |
| dnd-kit peer deps conflict | Low | Medium | Use exact versions from pnpm catalog; run `pnpm audit` |

**Critical path**: F-1 → F-2 → F-3 → F-4..F-8 (longest frontend chain, 4 sequential hops)
**Most complex wave**: C-4 (Intelligence tab entity graph) and F-12 (Workspace with dnd)
**Highest risk**: S-1 (F-SEC-001 auth bypass — fix immediately to prevent production vulnerability)

---

## Success Milestones

| Milestone | Waves Complete |
|-----------|---------------|
| CSS baseline ✓ | F-1 |
| Layout + nav ✓ | F-2 |
| CompanyDetail shell ✓ | F-3 |
| All 5 CompanyDetail tabs ✓ | F-4, F-5, F-6, F-7, F-8 |
| Dashboard complete ✓ | F-9 |
| Portfolio + Screener ✓ | F-10 |
| All pages built ✓ | F-11, F-12 |
| Security hardened ✓ | S-1 |
| All canvas frames ✓ | C-1 through C-6 |
| **First version of UI complete** | All 18 waves |
