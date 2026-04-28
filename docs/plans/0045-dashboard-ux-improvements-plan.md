---
id: PLAN-0045
title: Dashboard & Portfolio UX Improvements — Brief Context, Alerts, Holdings Enrichment, Layout
prd: investigation-2026-04-28
status: draft
created: 2026-04-28
updated: 2026-04-28
---

# PLAN-0045 — Dashboard & Portfolio UX Improvements

> **Source**: Investigation report `docs/audits/2026-04-28-investigation-dashboard-ux-report.md`
> **Priority**: HIGH — Morning brief non-functional; portfolio holdings missing ticker/name; alerts visually broken

## Pre-Read List

Before implementing, read:
- `docs/audits/2026-04-28-investigation-dashboard-ux-report.md` — full root cause analysis
- `services/rag-query/.claude-context.md` (Wave A)
- `apps/worldview-web/components/dashboard/MorningBriefCard.tsx` (Wave A)
- `apps/worldview-web/components/shell/AlarmsPanel.tsx` (Wave B)
- `services/alert/src/alert/domain/enums.py` (Wave B)
- `apps/worldview-web/contexts/AlertStreamContext.tsx` (Wave B)
- `services/portfolio/src/portfolio/api/routes/holdings.py` (Wave C)
- `apps/worldview-web/lib/gateway.ts` — getHoldings, getPortfolios (Wave C)
- `apps/worldview-web/app/(app)/dashboard/page.tsx` (Wave D)
- `apps/worldview-web/components/dashboard/SectorHeatmapWidget.tsx` (Wave D)
- `apps/worldview-web/components/dashboard/PredictionMarketsWidget.tsx` (Wave D)
- `apps/worldview-web/components/shell/TopBar.tsx` (Wave E)

---

## Wave A: Morning Brief — Context Fix + Format Redesign

**Estimated effort**: 3h | **Depends on**: nothing

### Task A-1: Lower S8 min_display_score Threshold

**Problem**: S8's `BriefingContextGatherer` uses `min_display_score=0.3`. All 93 current articles score 0.23–0.26 → 0 articles → 465-char context → LLM outputs "Not available in retrieved context" for every section.

**Target file**: `services/rag-query/src/rag_query/application/use_cases/briefing_context_gatherer.py` (or wherever `min_display_score` is configured)

**Changes**:
1. Find where `min_display_score=0.3` is set in BriefingContextGatherer
2. Change to `min_display_score=0.15` (or make it configurable via `Settings`)
3. If in config, add `BRIEFING_MIN_DISPLAY_SCORE: float = 0.15` to rag-query Settings with env var `RAG_BRIEFING_MIN_DISPLAY_SCORE`
4. Update `services/rag-query/configs/dev.local.env.example` if env var added

**Acceptance criteria**:
- Morning brief narrative is non-empty and contains at least 3 paragraphs
- S8 logs show `chars: >1000` (not 465)
- Live container test: `curl .../v1/briefings/morning` shows populated sections

**Tests**:
- Unit test: BriefingContextGatherer returns articles when score ≥ 0.15
- Unit test: BriefingContextGatherer returns empty when all scores < 0.15

---

### Task A-2: Redesign MorningBriefCard for Bloomberg-Grade Presentation

**Problem**: 200-char preview cuts mid-sentence; no prominent headline; sections unrecognizable at glance; H2 headers at 10px look like body text.

**Target file**: `apps/worldview-web/components/dashboard/MorningBriefCard.tsx`

**Changes**:
1. **Headline extraction**: Parse the narrative for the first `## ` H2 heading or first sentence of the first paragraph. Display as a single prominently weighted line (`text-[12px] font-semibold text-foreground`) at the top of the content area.
2. **Three visible lines**: Show first 3 full lines of content (not 200 chars). Use `line-clamp-3` CSS or compute natural line breaks. These 3 lines are always visible without interaction.
3. **"Read more" button**: Appears below the 3 lines when the narrative is longer than those 3 lines. Expands to full markdown rendering (existing `ReactMarkdown` path).
4. **Section labels**: When expanded, keep H2 headers styled as uppercase 9px tracking-wide labels (like other section headers in the terminal) not prose headers.
5. **PREVIEW_CHARS removal**: Remove `PREVIEW_CHARS = 200` and the raw text slice. Replace with proper 3-line CSS clamp.

**Acceptance criteria**:
- Headline is visible without reading the body
- First 3 content lines visible on load without any interaction
- "Read more" expand/collapse works for long briefs
- Abbreviated and full view look Bloomberg-grade (no sentence cuts)

**Tests**:
- Vitest: renders headline from H2 header
- Vitest: 3-line content always visible
- Vitest: "Read more" button visible for long content; not visible for short content

---

### Wave A Validation Gate
```bash
cd apps/worldview-web && pnpm typecheck
cd apps/worldview-web && pnpm test
# Live container:
curl http://localhost:8000/api/v1/briefings/morning | python3 -m json.tool | grep '"narrative"'
```
All must pass.

---

## Wave B: Alerts — Severity Case Fix + Badge Alignment

**Estimated effort**: 2h | **Depends on**: nothing

### Task B-1: Fix Alert Severity Case Mismatch

**Problem**: S10 `AlertSeverity` StrEnum returns lowercase (`"low"`, `"medium"`, `"high"`, `"critical"`). Frontend `Alert.severity` TypeScript type is `"LOW" | "MEDIUM" | "HIGH" | "CRITICAL"`. `AlarmsPanel.severityDotClass()` switch has uppercase cases → no match → all severity dots are invisible (no CSS class).

**Target files**:
- `apps/worldview-web/components/shell/AlarmsPanel.tsx`
- `apps/worldview-web/components/dashboard/RecentAlerts.tsx` (already normalises via `.toUpperCase()` — verify)
- `apps/worldview-web/lib/utils.ts` — `severityColor()` function

**Changes in `AlarmsPanel.tsx`**:
1. In `severityDotClass(severity)`, normalise input: `const norm = severity.toUpperCase() as Alert["severity"];` and switch on `norm`
2. Add `retry: 2` (remove `retry: false`) with `retryDelay: 2000` so transient failures don't silently show empty
3. Add `refetchOnMount: true` to ensure fresh data when sidebar opens

**Changes in `utils.ts`** (if `severityColor()` has same issue):
- Verify `severityColor()` used in `RecentAlerts.tsx` also handles lowercase; if not, normalise there too

**Acceptance criteria**:
- CRITICAL alerts show red dot, HIGH show orange, MEDIUM show amber, LOW show grey
- Alerts panel shows data after page refresh (not silently empty on first load)
- `RecentAlerts` still works correctly (verify `.toUpperCase()` path is preserved)

**Tests**:
- Vitest: `severityDotClass("critical")` returns `"bg-destructive"` (lowercase input)
- Vitest: `severityDotClass("CRITICAL")` returns `"bg-destructive"` (uppercase input)
- Vitest: AlarmsPanel renders alert rows when `getPendingAlerts` returns data

---

### Task B-2: Fix TopBar Badge to Reflect REST Pending Count

**Problem**: TopBar bell badge shows `unreadCount = recentAlerts.length` (WebSocket session events). This count resets to 0 on page refresh and has no relation to the actual pending alerts in the DB. Users see "9+" in the TopBar but "No pending alerts" in the AlarmsPanel — a confusing disconnect.

**Target files**:
- `apps/worldview-web/app/(app)/layout.tsx`
- `apps/worldview-web/contexts/AlertStreamContext.tsx`
- `apps/worldview-web/components/shell/TopBar.tsx`

**Changes**:
1. In `layout.tsx`, add a `useQuery` for `getPendingAlerts({ limit: 1 })` to get just the `total` count
2. Pass `restPendingCount` to `TopBar` as the primary badge count
3. Keep `unreadCount` from WebSocket for the real-time increment (add new WS alerts on top of the REST baseline)
4. Badge formula: `Math.max(restPendingCount, unreadCount + restPendingCount)` or simply `restPendingCount` refreshed every 30s

**Alternative (simpler)**: Change `TopBar` badge to use a separate `useQuery` for just the total count, decoupled from the WebSocket session count.

**Acceptance criteria**:
- After page refresh, TopBar badge shows the same count as AlarmsPanel's badge
- Badge stays consistent between sessions

**Tests**:
- Vitest: TopBar receives correct `unreadAlerts` value matching REST total

---

### Wave B Validation Gate
```bash
cd apps/worldview-web && pnpm typecheck
cd apps/worldview-web && pnpm test
# Live: open sidebar alarms panel — all rows should show colored dots
```

---

## Wave C: Portfolio Holdings Enrichment

**Estimated effort**: 4h | **Depends on**: nothing

### Task C-1: Add Ticker, Name, Entity_Id to S1 Holdings Endpoint

**Problem**: `GET /v1/holdings/{portfolio_id}` in S1 returns only `{id, portfolio_id, instrument_id, quantity, average_cost, currency}`. The `instruments` table in S1 has `ticker`, `name` (via EODHD sync). Frontend `getHoldings()` explicitly sets `ticker: ""`, `name: ""`, `entity_id: ""`.

**Target files**:
- `services/portfolio/src/portfolio/api/routes/holdings.py` (or wherever `GET /v1/holdings/{portfolio_id}` is implemented)
- `services/portfolio/src/portfolio/api/schemas/holdings.py` (response schema)
- `services/portfolio/src/portfolio/application/use_cases/holdings.py` (use case query)
- `apps/worldview-web/lib/gateway.ts` — `getHoldings` method (remove empty defaults once S1 returns data)

**Changes in S1**:
1. In the holdings query, LEFT JOIN with `instruments` table on `instrument_id`
2. Include `instruments.ticker`, `instruments.name`, `instruments.entity_id` in the response
3. Update `HoldingResponse` Pydantic schema to include `ticker: str | None`, `name: str | None`, `entity_id: str | None`
4. Update `GetHoldingsUseCase.execute()` to populate these fields (or use a read-only UoW for the join query)

**Changes in frontend `gateway.ts`**:
1. Map the new fields: `ticker: h.ticker ?? ""`, `name: h.name ?? ""`, `entity_id: h.entity_id ?? ""`
2. Remove the comment "S1 does not return entity_id, ticker, or name"

**Acceptance criteria**:
- `PortfolioSummary` shows "AAPL   Apple Inc." (ticker + name) on each holding row
- `PortfolioPage` holdings table shows ticker column populated
- Holdings with no instrument record (edge case) degrade gracefully to empty string

**Tests**:
- Unit test: `GetHoldingsUseCase` returns ticker/name/entity_id from instrument join
- Integration test: `GET /v1/holdings/{portfolio_id}` response includes ticker and name
- Vitest: `PortfolioSummary` renders ticker and name when holdings have them

---

### Task C-2: Portfolio Page — Add 1D/1W/1M Period Selector with Performance Chart

**Problem**: Portfolio page has no time-period performance chart or period toggle. Users cannot see if their portfolio is up/down over a week or month.

**Target files**:
- `apps/worldview-web/app/(app)/portfolio/page.tsx`
- `apps/worldview-web/lib/gateway.ts` — add `getPortfolioPerformance()` method
- S9 gateway: add `/v1/portfolios/{id}/performance?period=1D|1W|1M` → S1 (or compute from transactions + quotes)

**Changes**:
1. Add `GET /v1/portfolios/{portfolio_id}/performance` to S9 proxy → S1 portfolio performance endpoint
2. S1: add `GetPortfolioPerformanceUseCase` that computes portfolio value at start/end of period using historical quotes from S3
3. Frontend: add period selector `[1D] [1W] [1M]` buttons to portfolio page header
4. Render a simple sparkline or value comparison (start value, end value, Δ, Δ%)

**Note**: If S3 OHLCV historical data is not available for all holdings, degrade gracefully with available data.

**Acceptance criteria**:
- Portfolio page shows `1D/1W/1M` toggle
- Each period shows portfolio value change over that window
- Graceful degradation if price history is limited

**Tests**:
- Unit: `GetPortfolioPerformanceUseCase` computes correct returns from mock holdings + OHLCV data
- Vitest: period selector buttons render and are clickable; state updates on click

---

### Wave C Validation Gate
```bash
cd services/portfolio && python -m pytest tests/ -m "unit" -v
cd services/portfolio && python -m pytest tests/ -m "integration" -v
cd apps/worldview-web && pnpm typecheck
cd apps/worldview-web && pnpm test
# Live: portfolio widget shows ticker + name + quantity
```

---

## Wave D: Layout Improvements — Prediction Markets Placement, Sector 2-Col, Scroll/Fill

**Estimated effort**: 3h | **Depends on**: nothing

### Task D-1: Restructure Row 2 — Prediction Markets to Col-Span-5

**Problem**: Prediction Markets at `col-span-2` (~200px) truncates 40-80 char titles. Row 2 has unused width in `SectorHeatmapWidget`'s col-span-8.

**Target files**:
- `apps/worldview-web/app/(app)/dashboard/page.tsx`

**Changes** (Row 2 restructure — Option A):
```
Before: col-span-4 (MarketSnapshot) + col-span-8 (SectorHeatmap)
After:  col-span-3 (MarketSnapshot) + col-span-4 (SectorHeatmap) + col-span-5 (PredictionMarkets)
```

Row 3 also changes:
```
Before: col-span-4 (Portfolio) + col-span-4 (Movers) + col-span-2 (Prediction) + col-span-2 (AI Signals)
After:  col-span-4 (Portfolio) + col-span-4 (Movers) + col-span-4 (AI Signals expanded)
```
OR keep Row 3 layout but just move PredictionMarketsWidget to Row 2.

**Acceptance criteria**:
- Prediction market titles are fully readable (no truncation for titles up to 60 chars)
- MarketSnapshot 3-column still shows all 6 tickers
- SectorHeatmap 4-column is wide enough for bars + labels + values
- Row 2 still fits at 130px height

---

### Task D-2: Sector Heatmap — 2-Column Grid Layout

**Problem**: 11 sectors in a single column; only 5 visible in 130px height.

**Target file**: `apps/worldview-web/components/dashboard/SectorHeatmapWidget.tsx`

**Changes**:
1. Replace `<div className="flex-1 divide-y divide-border/30 overflow-auto">` with a 2-column grid container
2. Use `grid grid-cols-2 gap-px` to split sectors into 2 columns
3. Each column has its own sector rows
4. With 11 sectors in 2 columns: 6 on left, 5 on right → 6 rows × 22px = 132px (fits the 130px row)
5. Remove `overflow-auto` from the outer container (all sectors now visible without scrolling)

**Acceptance criteria**:
- All 11 sectors visible simultaneously in Row 2 without scrolling
- Layout correct at 1280px and 1440px viewport widths

---

### Task D-3: Fix Row 3/4 Height — Component Independent Scroll

**Problem**: `gridTemplateRows: "auto 130px auto auto"` → rows 3/4 are unbounded. Short widget content leaves dead space; tall content overflows the page.

**Target file**: `apps/worldview-web/app/(app)/dashboard/page.tsx`

**Changes**:
1. Update `gridTemplateRows` to: `"auto 130px minmax(220px, 1fr) minmax(200px, 1fr)"`
   - Row 3 minimum 220px, grows to fill remaining viewport
   - Row 4 minimum 200px, shares remaining space with Row 3
2. Ensure all Row 3/4 widgets have `h-full` + `overflow-hidden` on their outer div
3. Widget content areas must have `flex-1 overflow-y-auto` to scroll within bounds

**Acceptance criteria**:
- All Row 3/4 widgets fill their grid cell height
- News/Alerts/Calendar/Economic each scroll independently
- No page-level scrollbar from widget overflow

---

### Wave D Validation Gate
```bash
cd apps/worldview-web && pnpm typecheck
cd apps/worldview-web && pnpm test
# Visual: open dashboard, verify all 11 sectors visible, prediction markets titles readable,
# components scroll independently when list is long
```

---

## Wave E: TopBar Portfolio Value + Watchlist Quantity Display

**Estimated effort**: 2h | **Depends on**: Wave C (C-1 holdings data needed for accurate value)

### Task E-1: Add Portfolio Total Value to TopBar

**Problem**: TopBar shows SPY/QQQ/VIX/BTC tickers but no user account value. Bloomberg Terminal and all institutional platforms show NAV in the top rail.

**Target files**:
- `apps/worldview-web/app/(app)/layout.tsx`
- `apps/worldview-web/components/shell/TopBar.tsx`

**Changes**:
1. In `layout.tsx`, add `useQuery` for `getPortfolios()` to fetch portfolio list
2. Pass `portfolioValue: number | null` to `TopBar`
3. In `TopBar`, render `PORT $123,456` between the last index ticker and the bell icon
4. Format: `$` + compact notation (`$1.2M`, `$123K`, `$1,234`) using existing `formatPrice()` utility
5. Use muted foreground color (not primary) — this is secondary context, not a primary signal

**Acceptance criteria**:
- Portfolio value visible in TopBar at all times
- Updates when user navigates (30s stale time on portfolio query)
- Null/loading state shows `—` not an empty space

**Tests**:
- Vitest: TopBar renders portfolio value when prop is provided
- Vitest: TopBar renders `—` when portfolio value is null

---

### Task E-2: Portfolio Holdings — Show Quantity Alongside Value

**Problem**: Portfolio widget shows only the dollar value of each position (e.g., `$13,382`) without showing the number of shares or lots. Institutional traders always want to see quantity alongside value.

**Target file**: `apps/worldview-web/components/dashboard/PortfolioSummary.tsx`

**Changes**:
1. In the `topHoldings.map()` block, add quantity display: `{h.quantity.toLocaleString()} × ${livePrice.toFixed(2)}`
2. Layout: `ticker  name              qty×price    value   P&L%`
3. Compress P&L to just `%` in the summary widget (full absolute P&L on the portfolio page)
4. Use terminal row height h-[22px] per §0 standard

**Acceptance criteria**:
- Portfolio summary shows: `AAPL   Apple Inc.    100 × $175.20    $17,520   +2.3%`
- No layout overflow at standard dashboard width

---

### Wave E Validation Gate
```bash
cd apps/worldview-web && pnpm typecheck
cd apps/worldview-web && pnpm test
```

---

## Validation Gates Summary

| Gate | Command | Must Pass |
|------|---------|-----------|
| rag-query unit tests | `cd services/rag-query && python -m pytest tests/ -m "unit" -v` | All |
| portfolio unit tests | `cd services/portfolio && python -m pytest tests/ -m "unit" -v` | All |
| portfolio integration tests | `cd services/portfolio && python -m pytest tests/ -m "integration" -v` | All |
| Frontend typecheck | `cd apps/worldview-web && pnpm typecheck` | 0 errors |
| Frontend unit tests | `cd apps/worldview-web && pnpm test` | All pass |
| Live brief context | `curl .../v1/briefings/morning` narrative non-empty | Pass |
| Live holdings enriched | Portfolio widget shows ticker + name | Pass |
| Live alarms visible | AlarmsPanel shows colored dots on alert rows | Pass |

---

## Regression Guardrails

- **BP-252** (new): S10 AlertSeverity lowercase → normalise to uppercase before all switch/comparison in frontend
- **R25**: API routes must not import from infrastructure — all holdings join queries through use cases
- **R27**: Read-only queries use `ReadOnlyUnitOfWork` — `GetHoldingsUseCase` with join must remain read-only
- **BP-126**: Any new columns added to S1 holdings response Pydantic schema must have `server_default` in migration if NOT NULL

---

## Documentation to Update

| Document | Update |
|----------|--------|
| `services/portfolio/.claude-context.md` | Holdings endpoint now returns ticker/name/entity_id |
| `docs/services/portfolio.md` | Update holdings endpoint API documentation |
| `services/rag-query/.claude-context.md` | Add `BRIEFING_MIN_DISPLAY_SCORE` config entry |
| `docs/BUG_PATTERNS.md` | Add BP-252 (S10 severity lowercase mismatch) |

---

## Task Status

| Task | Status | Owner |
|------|--------|-------|
| A-1: S8 min_display_score threshold | pending | — |
| A-2: MorningBriefCard redesign | pending | — |
| B-1: Alert severity case fix | pending | — |
| B-2: TopBar badge REST alignment | pending | — |
| C-1: S1 holdings enrichment (ticker/name) | pending | — |
| C-2: Portfolio 1D/1W/1M performance chart | pending | — |
| D-1: Row 2 restructure (Prediction Markets) | pending | — |
| D-2: Sector 2-column grid | pending | — |
| D-3: Row 3/4 fixed heights + independent scroll | pending | — |
| E-1: TopBar portfolio value | pending | — |
| E-2: Holdings quantity display | pending | — |
