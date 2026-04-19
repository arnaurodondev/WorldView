# PLAN-0027-B: Frontend MVP — Design Completion + Code Implementation

> **Parent**: PLAN-0027 (Frontend MVP UI — Professional Design v2.0)
> **Date**: 2026-04-14
> **QA baseline**: docs/audits/2026-04-14-qa-plan-0027-impl-review.md
> **Status**: approved
> **Total waves**: 14
>
> Each wave is executable in a single Claude Code session.
> Canvas waves (C1–C4) require pencil.dev MCP server connected.
> Code waves (W1–W14) run normally without MCP.

---

## Canvas Design Waves (pencil.dev MCP required)

### Wave C1: State F — Candlestick Quality Fix

**Session type**: pencil.dev design session
**Duration estimate**: 45–60 min
**Prerequisite**: pencil.dev MCP server active (`/mcp` shows `pencil`)

**Context to load**:
```
open_document("apps/frontend/designs/worldview-mvp_v1.pen")
get_editor_state()
batch_get ["sL0wd", "C3YUf", "lZp51"]   ← State F, chart area, chart body
```

**Tasks**:
1. batch_get `lZp51` to list all child node IDs (the 40 existing rectangle candles)
2. Delete all existing candle rectangles (`batch_design` with delete operations)
3. Rebuild 40 candles. Each candle = 3-node group within `lZp51`:
   - **Upper wick**: `C("WoVQh", "lZp51", {width:2, height:<wick_top_height>, x:<candle_x>, y:<wick_y>, fill:<color>, opacity:1, cornerRadius:0})`
   - **Body**: `C("WoVQh", "lZp51", {width:12, height:<body_height>, x:<candle_x - 5>, y:<body_y>, fill:<color>, opacity:1, cornerRadius:0})`
   - **Lower wick**: `C("WoVQh", "lZp51", {width:2, height:<wick_bottom_height>, x:<candle_x>, y:<lower_wick_y>, fill:<color>, opacity:1, cornerRadius:0})`
   - Green (close > open): `fill:#26a69a` on all 3 nodes
   - Red (close < open): `fill:#ef5350` on all 3 nodes
   - Candle x-positions: 0, 34, 68, 102, ... (34px pitch, 40 candles across 1360px)
   - Last 8 candles: clear uptrend (progressively higher bodies)
4. Verify drawing tools sidebar (`jayD2`): batch_get each tool icon node, U() any with opacity < 1 to opacity:1
5. Verify amber MA50 line (`TBEvu`): U() to confirm `stroke:{fill:"#f0c040",thickness:2}`
6. Verify amber price label text: U() if fill != "#f0c040"
7. `get_screenshot()` after each major step

**Acceptance criteria**:
- Screenshot shows candles with visible upper wicks, colored bodies, lower wicks
- MA50 line visible as amber (#f0c040) dashed overlay
- Drawing tools sidebar shows 6 tool icons (not blank)

**Documents to update**:
- `REDESIGN_PLAN.md`: State F → ✅ QUALITY FIXED
- `DESIGN.md` header: State F ✅ (remove ⚠️)

---

### Wave C2: State D — News Tab

**Session type**: pencil.dev design session
**Duration estimate**: 60–75 min
**Prerequisite**: Wave C1 complete (State F verified)

**Context to load**:
```
batch_get ["aTIbj", "jZEVF", "wE7LT", "UbhWb"]
```
- `jZEVF` = State D frame (should be empty or stub)
- `wE7LT` = State A (to copy header + tab bar from)
- `UbhWb` = tab bar source node

**Tasks**:
1. If `jZEVF` is empty (confirm via batch_get), note its y-position and height
2. Copy header rows (Rows 1-4) from `wE7LT` into `jZEVF` using C()
3. Copy tab bar from `wE7LT`; update tab bar so [News] is active, [Overview] inactive
4. Build filter controls row (40px, y = header_bottom):
   - `[By Relevance ▼]` chip: bg=#181D28, border=#232A36, text=#D1D4DC, 12px Mono
   - `[By Date]` chip: same style inactive
   - Date range label: "Jan 1, 2026 → Apr 14, 2026" #787B86
   - `[DEEP ✓]` chip: bg=#0EA5E920, border=#0EA5E9, #0EA5E9 text
   - `[MED ✓]` chip: bg=#F59E0B20, border=#F59E0B, #F59E0B text
   - `[LIGHT ✓]` chip: bg=#181D28, border=#232A36, #4C5260 text
5. Build 3 article rows (88px each, border-bottom=#232A36):
   - Left score: "0.91" Mono 11px #0EA5E9 (DEEP tier color)
   - Tier badge: "DEEP" 40px chip bg=#0EA5E920 border=#0EA5E9
   - Impact chip: "⬆+1.4%" bg=#26A69A20 text=#26A69A
   - Headline: 13px 500 Sans #D1D4DC
   - Excerpt: 2 lines 11px #787B86
   - Entity chips: "AAPL" "earnings" "iPhone" — 10px bg=#181D28 #4C5260
   - Source/time: "Reuters · 2h ago" 10px #4C5260
6. `get_screenshot()` after filter row, after all 3 articles

**Acceptance criteria**: Full News tab visible matching REDESIGN_PLAN §P4 State D spec

**Documents to update**: `REDESIGN_PLAN.md` State D → ✅ DONE

---

### Wave C3: State B — Fundamentals Tab

**Session type**: pencil.dev design session
**Duration estimate**: 75–90 min

**Context to load**:
```
batch_get ["aTIbj", "VEVln", "wE7LT"]
```

**Tasks**:
1. Copy header rows (Rows 1-4) + tab bar from `wE7LT` into `VEVln`; set [Fundamentals] tab active
2. Build compact chart area (260px height, bg=#10141C, border=#232A36):
   - Period selector top-right: `[Annual ●]` `[Quarterly]` chips (bg=#181D28, active has border=#0EA5E9)
   - Simplified 6-bar revenue chart (bars in #0EA5E9, varying heights, x-labels below)
3. Build accordion sections (5 total):
   - **Open section — INCOME & GROWTH** (bg=#181D28 36px header + border-bottom):
     - Revenue bar chart (8 bars, #0EA5E9 fill, 120px tall, bg=#10141C, border=#232A36)
     - Table: columns [Quarter | Revenue | YoY% | EPS | vs Est | Net Income]
     - 4 data rows (Mono 12px, 32px height): Q1-Q4 2025/2026 data
     - Positive EPS beat: #26A69A, miss: #EF5350
   - **4 collapsed sections** (36px header, ▶ chevron): BALANCE SHEET, CASH FLOW, VALUATION, COMPANY & OWNERSHIP
4. `get_screenshot()` after chart + period selector, after open accordion section

**Acceptance criteria**: Fundamentals tab shows compact chart + 5 accordion sections, one open

**Documents to update**: `REDESIGN_PLAN.md` State B → ✅ DONE

---

### Wave C4: State C — Intelligence Tab

**Session type**: pencil.dev design session
**Duration estimate**: 90–120 min (most complex wave)

**Context to load**:
```
batch_get ["aTIbj", "M1GXQ", "wE7LT"]
```

**Tasks**:
1. Copy header rows + tab bar from `wE7LT`; set [Intelligence] tab active
2. Build left column entity graph (860px wide, remaining height):
   - Graph container: bg=#10141C, border=#232A36, cornerRadius:4
   - Filter row (36px): "Hop depth: [2●] [3○]" + "Min confidence: 75%" + "Filter: [Companies✓] [People✓] [Funds✓]"
   - Graph nodes (circles): AAPL ●●● center (largest), MSFT ●, GOOGL ●, Berkshire ●, Tim Cook ●, TSMC ●, Foxconn ●
     - Company nodes: #0EA5E9 fill (sky)
     - Person nodes: #26A69A fill (teal)
     - Fund nodes: #F0C040 fill (amber)
   - Edges: 1px lines #2E3847, thickness proportional to confidence
   - Legend: 3 color dots + labels (10px Sans #787B86)
3. Build right column (380px wide, 3 stacked panels):
   - **SIMILAR INSTRUMENTS** (border=#232A36): MSFT 0.94 / GOOGL 0.89 / META 0.83 rows (Mono 12px)
   - **CONTRADICTIONS** (border=#EF5350 1px left): 2 items with [STRONG] badge #EF5350
   - **PREDICTION MARKET SIGNALS** (border=#232A36): 2 questions with probability bars
4. Build full-width collapsible sections below (full 1240px width):
   - RECENT CLAIMS: 3 rows with [POSITIVE]/[NEUTRAL]/[NEGATIVE] badges + confidence bar
   - TEMPORAL EVENTS: 3 events with type badge + description + date
5. `get_screenshot()` after entity graph, after right panels, after bottom sections

**Acceptance criteria**: Intelligence tab shows entity graph with labeled nodes + 3 right panels + 2 bottom accordions

**Documents to update**: `REDESIGN_PLAN.md` State C → ✅ DONE

---

## Code Implementation Waves

### Wave W1: CSS Foundation Fix (Auto-fixable)

**Session type**: code
**Files**: `apps/frontend/src/index.css`, 6 component files
**Fixes findings**: F-FE-001, F-FE-002, F-FE-004, F-FE-005, F-FE-006, F-FE-007, F-FE-009, F-FE-010, F-FE-018, F-FE-019, F-DESIGN-022

**Tasks**:
1. Replace `apps/frontend/src/index.css` root variables:
   ```css
   @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

   :root {
     --background: #080A0E;
     --card: #10141C;
     --elevated: #181D28;
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
   }
   body { font-family: "IBM Plex Sans", system-ui, sans-serif; }
   .mono { font-family: "IBM Plex Mono", monospace; font-variant-numeric: tabular-nums; }
   ```
2. Update `Layout.tsx`: `var(--bg-secondary)` → `var(--card)`, `var(--text-secondary)` → `var(--muted-foreground)`
3. Update `FlashOverlay.tsx`: `#dc2626` → `var(--negative)`, `var(--bg-secondary)` → `var(--card)`
4. Update `PredictionMarketsPanel.tsx`: `#22c55e` → `var(--positive)`, `#ef4444` → `var(--negative)`, `var(--text-secondary)` → `var(--muted-foreground)`; add `fontFamily: "IBM Plex Mono"` to all number elements
5. Update `SimilarCompaniesPanel.tsx`: `var(--accent)` → `var(--primary)`, `var(--bg-secondary)` → `var(--card)`; add `fontFamily: "IBM Plex Mono"` to score/percentage elements
6. Update `OHLCVChart.tsx`: `upColor: "#22c55e"` → `"#26A69A"`, `downColor: "#ef4444"` → `"#EF5350"`
7. Update `SeverityBadge.tsx`: replace Tailwind `bg-gray-100` etc with CSS variable-based styles
8. Run `pnpm typecheck && pnpm test --run` — must pass

**Acceptance criteria**: All tests pass; no legacy CSS variable names remain

---

### Wave W2: Top Nav Bar + Sidebar Redesign

**Session type**: code
**New files**: `apps/frontend/src/components/TopNavBar.tsx`, `apps/frontend/src/components/WatchlistSidebar.tsx`
**Modified files**: `apps/frontend/src/components/Layout.tsx`
**Fixes findings**: F-DESIGN-015, F-DESIGN-016, F-DESIGN-021, F-FE-017

**Tasks**:
1. Build `TopNavBar.tsx` (44px, bg=`var(--card)`, border-bottom=`var(--border)`):
   - Left: `◉ WORLDVIEW` logo (IBM Plex Mono, `var(--amber)` dot)
   - Center: GlobalSearchBar component (300px default, expands to 400px on focus)
     - Placeholder: "Search ticker, company, entity... ⌘K"
     - Results dropdown (320×280px) with INSTRUMENTS / ENTITIES / NEWS sections
   - Right: Ticker strip (SPY/QQQ/VIX), market status dot, notification bell, user avatar
2. Update `Layout.tsx`:
   - Place TopNavBar above main content (sticky, z-10)
   - Sidebar: add Watchlist section (4 ticker rows with live prices), Recent Alerts (2 rows), Settings+Help footer
   - Add collapse toggle (52px icon-only state on click)
   - Sidebar width: 200px expanded, 52px collapsed
3. Wire GlobalSearchBar to S9: `gateway.searchGlobal(query)` (add method to gateway-client)
4. Add `useWatchlistPrices` hook: WebSocket subscription to S9 `/ws/quotes`

**Acceptance criteria**: Top nav renders with logo + search + ticker strip; sidebar shows watchlist rows with prices

---

### Wave W3: CompanyDetailPage — Header Rows + Tab Bar

**Session type**: code
**Modified files**: `apps/frontend/src/pages/CompanyDetailPage.tsx`
**New files**: `apps/frontend/src/components/instrument/InstrumentHeader.tsx`, `apps/frontend/src/components/instrument/InstrumentTabs.tsx`
**Fixes findings**: F-FE-003, F-DESIGN-006, F-DESIGN-007

**Tasks**:
1. Build `InstrumentHeader.tsx` (4 rows):
   - Row 1 (40px): Logo + name + ticker chip (`var(--primary)` bg) + exchange + sector + subsector
   - Row 2 (44px): Price in IBM Plex Mono 28px 600 + delta (colored) + 6 metric chips (P/E, P/B, etc.)
   - Row 3 (40px): "52W RANGE" label + min/max + range bar (SVG, `var(--primary)` fill %) + dot
   - Row 4 (36px): `[★ Watchlist]` `[Workspace]` `[🔔 Set Alert]` `[⤴ Share]` buttons with `var(--primary-dim)` bg
2. Build `InstrumentTabs.tsx`: 5 tabs (Overview / Fundamentals / Intelligence / News / Chat)
   - Active: `var(--foreground)` text + 2px bottom border `var(--border-strong)`
   - Inactive: `var(--muted-foreground)` text
   - Height: 36px, bg=`var(--card)`, border-bottom=`var(--border)`
3. Wire in `CompanyDetailPage.tsx`:
   - Add `activeTab` state (default: "overview")
   - Render `<InstrumentHeader>` + `<InstrumentTabs>` above existing content
   - Conditionally render tab content by `activeTab` value

**Acceptance criteria**: Instrument Detail page shows 4-row header + 5-tab bar; tab switching updates content area

---

### Wave W4: P4 State A Right Panel + State E Chat Tab

**Session type**: code
**New files**: `apps/frontend/src/components/instrument/KeyMetricsPanel.tsx`, `apps/frontend/src/components/instrument/ChatTab.tsx`
**Modified files**: `apps/frontend/src/pages/CompanyDetailPage.tsx`
**Fixes findings**: F-DESIGN-005

**Tasks**:
1. Build `KeyMetricsPanel.tsx` (right panel, 380px):
   - KEY METRICS section: P/E, P/B, P/S, FwdP/E, EV/EBITDA, PEG, ROE, Div, Beta (3×3 grid, Mono 12px)
   - ANALYST CONSENSUS section: analyst price range bar + Buy/Hold/Sell counts + upside %
   - NEXT EARNINGS section: quarter + date + EPS estimate
2. Update State A layout to 2-column (main chart 840px | right panel 380px)
3. Build `ChatTab.tsx` (State E):
   - Context bar (36px amber-dim bg, amber 1px border): "Analyzing: [AAPL] Apple Inc."
   - Conversation thread (scrollable): renders user messages + AI response bubbles
   - AI bubble: bg=`var(--card)`, border=`var(--border)`, citations in `var(--primary)` links
   - Contradiction warning: amber warning row
   - Input bar (44px pinned): placeholder "Ask about {instrumentName}..." + Send button
4. Wire State E to existing ChatUI component (or wrap it)

**Acceptance criteria**: State A shows right panel; State E tab shows chat interface

---

### Wave W5: P4 State D — News Tab Implementation

**Session type**: code
**New files**: `apps/frontend/src/components/instrument/NewsTab.tsx`
**Modified files**: `apps/frontend/src/components/NewsList.tsx`, `apps/frontend/src/pages/CompanyDetailPage.tsx`
**Fixes findings**: F-DESIGN-004, F-DESIGN-014

**Tasks**:
1. Enhance `NewsList.tsx` to accept `showScores?: boolean` prop:
   - Article card layout (88px row): score | tier badge | impact chip | headline | excerpt | entity chips
   - Tier badge colors: DEEP=`var(--primary)`, MED=`var(--warning)`, LIGHT=`var(--dim)`
   - Impact chip: up=`var(--positive)` / down=`var(--negative)`
   - Excerpt: 2-line clamp with `-webkit-line-clamp: 2`
   - Entity chips: 10px bg=`var(--elevated)` `var(--dim)` text
2. Build `NewsTab.tsx`:
   - Filter bar (40px): [By Relevance ▼] [By Date] | date range picker | [DEEP] [MED] [LIGHT] toggles
   - Render `<NewsList showScores />` for entity-filtered articles
   - "Load 20 more" button at bottom
3. Wire filter state to gateway: `gateway.getEntityNews(entityId, {sort, dateRange, tiers})`

**Acceptance criteria**: News tab shows filter bar + article cards with tier badges + relevance scores

---

### Wave W6: P4 State B — Fundamentals Tab Implementation

**Session type**: code
**New files**: `apps/frontend/src/components/instrument/FundamentalsTab.tsx`, `apps/frontend/src/components/charts/RevenueBarChart.tsx`
**Fixes findings**: F-DESIGN-002

**Tasks**:
1. Build `RevenueBarChart.tsx` (using SVG or Recharts):
   - 8 bars, `var(--primary)` fill, proportional heights
   - X-axis: quarter labels (Q1 2025 – Q1 2026)
   - No y-axis labels (space saving)
   - Tooltip on hover showing quarter + revenue
2. Build `FundamentalsTab.tsx`:
   - Period selector chips at top: [Annual] [Quarterly]
   - Compact 260px chart with period context
   - Accordion sections using `<details>/<summary>` or custom component:
     - INCOME & GROWTH (open): RevenueBarChart + financial table (Mono 12px, 32px rows, alternating bg)
     - BALANCE SHEET, CASH FLOW, VALUATION, COMPANY & OWNERSHIP (collapsed, 36px chevron headers)
   - Positive EPS beat: `var(--positive)`, miss: `var(--negative)`
3. Wire to gateway: `gateway.getFinancialFundamentals(instrumentId, period)`

**Acceptance criteria**: Fundamentals tab renders with interactive accordion + revenue chart; financial data rows use Mono font

---

### Wave W7: P4 State C — Intelligence Tab Implementation

**Session type**: code
**New files**: `apps/frontend/src/components/instrument/IntelligenceTab.tsx`, `apps/frontend/src/components/EntityGraph.tsx`
**Fixes findings**: F-DESIGN-003

**Tasks**:
1. Build simplified `EntityGraph.tsx` using SVG (no D3 dependency):
   - Render entity nodes as colored circles (company=primary, person=teal, fund=amber) with text labels
   - Render relationship edges as SVG lines with width proportional to confidence
   - Filter row: hop depth chips + confidence slider + entity type checkboxes
   - Legend: 3 color dots
   - Nodes at fixed positions (no force-directed layout in V1; static layout is fine)
2. Build `IntelligenceTab.tsx` (2-column layout):
   - Left 860px: EntityGraph with full height
   - Right 380px: SimilarInstruments panel + ContradictionsPanel + PredictionSignalsPanel
3. Build bottom collapsible sections (full 1240px):
   - RECENT CLAIMS: 3 rows with badge + claim text + confidence bar
   - TEMPORAL EVENTS: 3 events with type + description + date
4. Wire to gateway: `gateway.getEntityGraph(entityId)`, `gateway.getEntityInsight(entityId)`

**Acceptance criteria**: Intelligence tab shows entity graph + 3 right panels + 2 bottom accordions

---

### Wave W8: P4 State F — Full-Screen Graph + Gateway Client Completion

**Session type**: code
**New files**: `apps/frontend/src/components/instrument/FullScreenChart.tsx`
**Modified files**: `apps/frontend/src/lib/gateway-client.ts`
**Fixes findings**: F-DESIGN-023, F-DESIGN-010

**Tasks**:
1. Add missing gateway client methods:
   ```typescript
   getEntityGraph: (entityId: string, hopDepth?: number) => request<EntityGraph>(`/v1/entities/${entityId}/graph`)
   getEntityPredictions: (entityId: string) => request<PredictionSignal[]>(`/v1/entities/${entityId}/predictions`)
   getFinancialFundamentals: (instrumentId: string, period: string) => request<Fundamentals>(`/v1/instruments/${instrumentId}/fundamentals?period=${period}`)
   getAnalystConsensus: (instrumentId: string) => request<AnalystConsensus>(`/v1/instruments/${instrumentId}/consensus`)
   getEntityInsight: (entityId: string) => request<EntityInsight>(`/v1/entities/${entityId}/insight`)
   searchGlobal: (query: string) => request<SearchResults>(`/v1/search?q=${encodeURIComponent(query)}`)
   ```
2. Build `FullScreenChart.tsx`:
   - Timeframe chips (1D/1W/1M/3M/6M/1Y/5Y/All) with active/inactive states
   - Overlay chips (MA20/MA50/MA200/BB/VWAP) — toggle on click
   - Indicator chips (RSI/MACD)
   - Drawing tools sidebar (32px, 6 icon-only tools)
   - Full OHLCVChart (reuse existing, full width)
   - Volume panel (80px below chart)
   - RSI panel (80px) + MACD panel (80px) when indicators active
3. Add expand chart button to InstrumentHeader Row 4 that routes to `?view=graph`
4. In CompanyDetailPage: detect `?view=graph` param → render FullScreenChart over tab content

**Acceptance criteria**: Expand chart button shows full-screen graph with timeframe toolbar and indicator panels

---

### Wave W9: Dashboard Redesign (P3)

**Session type**: code
**Modified files**: `apps/frontend/src/pages/DashboardPage.tsx`
**New files**: `apps/frontend/src/components/dashboard/MorningBrief.tsx`, `apps/frontend/src/components/dashboard/MarketHeatmap.tsx`, `apps/frontend/src/components/dashboard/TopMovers.tsx`, `apps/frontend/src/components/dashboard/EconomicCalendar.tsx`
**Fixes findings**: F-DESIGN-008

**Tasks**:
1. Build Dashboard layout (2-column grid with sidebar at 200px + main 1040px):
   - **Row 1** (2-column): MorningBrief card (amber border, AI badge, briefing text + topic chips) | PortfolioSummary (4 KPIs: Total Value, Today P&L, IRR, Positions)
   - **Row 2** (2-column): MarketHeatmap (28 sector tiles, 7-step color scale from `$negative` to `$positive`, IBM Plex Mono ticker text) | TopMovers table (5 cols: TICKER | NAME | PRICE | DAILY% | SIGNAL)
   - **Row 3** (full width): IntelligenceStream (article feed with entity chips) and Watchlist News (5 latest watchlist articles)
   - **Row 4** (2-column): EconomicCalendar (upcoming events: date + release + prior + expected) | RecentAlerts (last 5 alerts, reuse AlertCard)
2. Use TanStack Query with appropriate staleTime:
   - Morning Brief: `staleTime: 5 * 60 * 1000` (5 min)
   - Heatmap: `staleTime: 60 * 1000` (1 min)
   - Alerts: live (AlertStreamContext)

**Acceptance criteria**: Dashboard shows all 8 sections with correct styling; Morning Brief has amber border

---

### Wave W10: Portfolio Page + ScreenerPage Styling

**Session type**: code
**Modified files**: `apps/frontend/src/pages/PortfolioPage.tsx`, `apps/frontend/src/pages/ScreenerPage.tsx`
**New files**: `apps/frontend/src/components/portfolio/StrategyCard.tsx`, `apps/frontend/src/components/portfolio/HoldingsTable.tsx`
**Fixes findings**: F-DESIGN-011, F-DESIGN-018

**Tasks**:
1. Build `PortfolioPage.tsx`:
   - Summary row (56px): Total Value (Mono 20px 600) | Today's P&L ($positive) | Unrealized P&L | IRR | Positions
   - Strategy Card Grid (3 cards, 240px each): value + daily P&L + position count + 5d sparkline (simple SVG path)
   - Detail tabs: [Holdings ●] [Transactions] [Analytics] [Watchlists] [Settings]
   - Holdings table (9 cols): Ticker | Name | Sector | Shares | Avg Cost | Mkt Value | Unrealized P&L | Daily% | Weight bar
   - Row height 36px, alternating bg ($card/$elevated), Mono 12px for all numerics
2. Restyle `ScreenerPage.tsx` table:
   - Header row 32px, bg=`var(--elevated)`, border-bottom=`var(--border)`
   - Data rows 32px, alternating bg, Mono 12px right-aligned for numerics
   - Score bar (40×6px, proportional `var(--primary)` fill)
   - SCORE column header in `var(--primary)` (active sort indicator)

**Acceptance criteria**: Portfolio page shows strategy cards + holdings table; Screener table matches REDESIGN_PLAN layout

---

### Wave W11: Backend Security Fixes

**Session type**: code (backend Python)
**Modified files**:
- `services/portfolio/src/portfolio/infrastructure/middleware/internal_jwt.py`
- `services/portfolio/src/portfolio/api/routes/brokerage_connections.py`
- `services/portfolio/src/portfolio/config.py`
- `services/api-gateway/src/api_gateway/middleware.py` (rate limit logging)
**Fixes findings**: F-SEC-001, F-SEC-002, F-SEC-007, F-SEC-008, F-SEC-009, F-SEC-010, F-SEC-012, F-SEC-013

**Tasks**:
1. **F-SEC-001**: Remove unverified JWT decode path from InternalJWTMiddleware. Instead, if `public_key is None`, return `JSONResponse({"detail": "Service not ready"}, status_code=503)`. Add startup health-check dependency.
2. **F-SEC-002/012**: Move hardcoded `"worldview-gateway"` to `Settings`: `internal_jwt_issuer: str = Field(default="worldview-gateway", ...)`. Pass `issuer=self.issuer` to `jwt.decode()`.
3. **F-SEC-009**: Replace `_require_user_headers()` to read from `request.state.user_id` and `request.state.tenant_id` (set by InternalJWTMiddleware) instead of raw headers.
4. **F-SEC-010**: Change `snaptrade_client_id: str` and `snaptrade_consumer_key: str` to `SecretStr`. Update callers to use `.get_secret_value()`.
5. **F-SEC-008**: Standardize to `X-Tenant-ID` (uppercase D) everywhere in portfolio service.
6. **F-SEC-007**: Add per-request debug log to RateLimitMiddleware when Valkey is None: `logger.debug("rate_limiting_disabled", path=str(request.url.path))`.
7. **F-SEC-013**: Broaden exception catch from `jwt.DecodeError` to `Exception`.
8. Fix portfolio test warning: remove `@pytest.mark.asyncio` from 2 non-async test functions in `test_brokerage_connections.py`
9. Run `python -m pytest tests/ -m "unit" --tb=short` from services/portfolio — must pass

**Acceptance criteria**: All portfolio unit tests pass (0 warnings about asyncio mark); security review items addressed

---

### Wave W12: Landing Page + Settings Page + Onboarding

**Session type**: code
**New files**: `apps/frontend/src/pages/LandingPage.tsx`, `apps/frontend/src/pages/SettingsPage.tsx`, `apps/frontend/src/pages/OnboardingPage.tsx`
**Modified files**: `apps/frontend/src/App.tsx`
**Fixes findings**: F-DESIGN-013, F-DESIGN-019, F-DESIGN-020

**Tasks**:
1. Build `LandingPage.tsx` (10 sections from REDESIGN_PLAN P5):
   - NavBar: amber ◉ WORLDVIEW logo + nav links + amber "Get Started →" CTA
   - Hero: 52px H1 + amber "Without the Bloomberg Bill." + product screenshot + CTAs
   - Stats Bar: 4 metrics (10M+/18/500K+/<5s)
   - Features Spotlight: annotated screenshot + checkmark list
   - Features Grid: 6 cards
   - Comparison Table: 6 competitors, Worldview highlighted in `var(--primary-dim)`
   - How It Works: 3 steps
   - Pricing Cards: 3 tiers, PRO highlighted
   - FAQ: 4 accordion items
   - CTA Banner + Footer
2. Build `SettingsPage.tsx` with 6-section nav rail (Profile, Notifications, Appearance, Keyboard Shortcuts, Subscription, Data & Privacy)
3. Build `OnboardingPage.tsx` with 6-step flow (Welcome → Role → Markets → Watchlist → Layout → Complete)
4. Update `App.tsx`:
   - `/` → LandingPage if unauthenticated, Dashboard if authenticated
   - `/settings` → SettingsPage
   - `/onboarding` → OnboardingPage
   - Redirect to `/onboarding` on first login

**Acceptance criteria**: Landing page renders all 10 sections; Settings nav rail works; Onboarding flows through 6 steps

---

### Wave W13: Workspace Page

**Session type**: code
**New files**: `apps/frontend/src/pages/WorkspacePage.tsx`, `apps/frontend/src/components/workspace/PanelGrid.tsx`, `apps/frontend/src/components/workspace/PanelPicker.tsx`, 11 panel component files
**Fixes findings**: F-DESIGN-012

**Tasks**:
1. Build `PanelGrid.tsx`: CSS Grid-based layout with draggable (via `@dnd-kit/core`) and resizable (resize handles) panels
2. Build `PanelPicker.tsx`: Modal with 11 panel card grid; click to add panel to workspace
3. Build 11 panel components (each has standard 28px header with drag handle, title, ticker selector, ⚙ / ×):
   - ChartPanel, WatchlistPanel, NewsFeedPanel, AIChatPanel, ScreenerPanel, PortfolioPanel, AlertFeedPanel, CalendarPanel, EntityGraphPanel, PredictionMarketsPanel (rename existing), MorningBriefPanel
4. Build `WorkspacePage.tsx` with top bar: Logo + layout name (editable) + [+ Add Panel] + [Save] + [Layouts ▾] + [⤴ Detach]
5. Persist layouts to localStorage (V1); wire to API in V2
6. Add `/workspace` route to App.tsx and sidebar nav item

**Acceptance criteria**: Workspace page renders with at least 3 panels (Chart, Watchlist, AI Chat); panels are draggable; panel picker opens and adds panels

---

### Wave W14: Test Coverage

**Session type**: code
**New files**:
- `apps/frontend/tests/Layout.test.tsx`
- `apps/frontend/tests/CompanyDetailPage.test.tsx`
- `apps/frontend/tests/DashboardPage.test.tsx`
- `apps/frontend/tests/ScreenerPage.test.tsx`
- `apps/frontend/tests/NewsPage.test.tsx`
- `apps/frontend/tests/InstrumentHeader.test.tsx`
- `apps/frontend/tests/InstrumentTabs.test.tsx`
**Fixes findings**: F-FE-012, F-FE-013, F-FE-014, F-FE-015, F-FE-016

**Tasks**:
1. `Layout.test.tsx`: NAV_ITEMS render, TopNavBar present, sidebar collapse toggle, Outlet renders
2. `CompanyDetailPage.test.tsx`: header rows render, tab bar renders, tab switching works, API data loads, error state shows
3. `DashboardPage.test.tsx`: Morning Brief renders, Heatmap renders, AlertStreamContext integration
4. `ScreenerPage.test.tsx`: filters add/remove, search submission, table rows render
5. `NewsPage.test.tsx`: tab strip renders, NewsList gets articles, tier badges show
6. `InstrumentHeader.test.tsx`: all 4 rows render, action buttons present
7. `InstrumentTabs.test.tsx`: 5 tabs render, active tab changes on click, border styling applied
8. Run `pnpm test --run` — all tests must pass

**Acceptance criteria**: 7 new test files all pass; total vitest count increases from 36 to 70+

---

## Execution Order

```
Backend security (W11) — no deps, fix ASAP
      ↓
W1 (CSS foundation) — must run before any other frontend wave
      ↓
W2 (TopNav + Sidebar) — shared layout; all pages depend on it
      ↓
W3 (CompanyDetail Header + Tabs) ─┐
W9 (Dashboard) ─────────────────  ├── can run in parallel after W2
W10 (Portfolio + Screener) ──────  ┘
      ↓
W4 (State A right panel + State E)
W5 (State D — News tab)             ← all run in parallel (after W3)
W6 (State B — Fundamentals tab)
      ↓
W7 (State C — Intelligence tab)     ← after W6 (shares accordion pattern)
W8 (State F + gateway client)       ← after W3
      ↓
W12 (Landing + Settings + Onboarding) — independent
W13 (Workspace) ─────────────────── ← most complex; after W9
      ↓
W14 (Tests) ─────────────── after all feature waves

Canvas waves (pencil.dev MCP required — parallel track):
C1 (State F quality) → C2 (State D) → C3 (State B) → C4 (State C)
```

---

## Success Criteria

| Milestone | Criteria |
|-----------|----------|
| CSS baseline (W1) | index.css uses Midnight Pro tokens; all tests pass |
| Layout (W2) | Top nav visible; sidebar shows watchlist rows |
| P4 foundation (W3) | CompanyDetail shows header + 5 tabs |
| P4 complete (W3–W8) | All 5 tab states + full-screen graph functional |
| Dashboard complete (W9) | All 8 dashboard sections visible |
| Portfolio + Screener (W10) | Portfolio shows holdings table; screener rows styled |
| Security clean (W11) | InternalJWT fail-closed; brokerage reads from request.state |
| Pages complete (W12–W13) | Landing + Settings + Onboarding + Workspace all accessible |
| Tests (W14) | Total frontend test count ≥ 70 |
| Canvas (C1–C4) | All 4 Instrument Detail tab states visible in canvas |

---

## Plan Tracking

Update `docs/plans/TRACKING.md` after each wave. Add this plan entry:

```
| PLAN-0027-B | PLAN-0027 Design Completion: W1-W14 code + C1-C4 canvas | PRD-0027 | approved | 0/18 | — | 2026-04-14 |
```
