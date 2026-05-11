# PLAN-0041: Instrument Page Redesign — Bloomberg-Grade Overview + Fundamentals

**PRD**: Investigation report `docs/audits/2026-04-27-investigation-instrument-page-redesign.md`
**Status**: completed
**Created**: 2026-04-27
**Updated**: 2026-04-27 (Wave D-3 done — all 7 waves complete)
**Depends on**: None (all prerequisite backend data exists in S3)

---

## Executive Summary

Redesign the instrument detail page (Overview + Fundamentals tabs) to match Bloomberg Terminal / TradingView quality. The backend already has the data (S3 has 18 fundamentals section endpoints + timeseries); the work is primarily:
1. Proxy 6 missing S3 section endpoints through S9
2. Add frontend gateway methods + types for new data
3. Restructure Overview tab (chart + right sidebar layout)
4. Overhaul Fundamentals tab (section cards, sparklines, right sidebar with competitors/ownership/news)
5. Build new components (52WeekRangeBar, TechnicalSnapshot, EarningsHistory, InsiderTransactions, PeerComparison)

---

## Codebase State Verification

| PRD Reference | Type | Service | Current State (from code) | Target State | Delta |
|--------------|------|---------|--------------------------|--------------|-------|
| Technicals section | S3 endpoint | S3 → S9 | S3 has `GET /api/v1/fundamentals/{id}/technicals-snapshot` → NOT proxied by S9 | Proxy through S9 | New S9 route |
| Share statistics | S3 endpoint | S3 → S9 | S3 has `GET /api/v1/fundamentals/{id}/share-statistics` → NOT proxied by S9 | Proxy through S9 | New S9 route |
| Insider transactions | S3 endpoint | S3 → S9 | S3 has `GET /api/v1/fundamentals/{id}/insider-transactions-snapshot` → NOT proxied by S9 | Proxy through S9 | New S9 route |
| Earnings trend | S3 endpoint | S3 → S9 | S3 has `GET /api/v1/fundamentals/{id}/earnings-trend` → NOT proxied by S9 | Proxy through S9 | New S9 route |
| Splits/dividends | S3 endpoint | S3 → S9 | S3 has `GET /api/v1/fundamentals/{id}/splits-dividends` → NOT proxied by S9 | Proxy through S9 | New S9 route |
| Earnings annual trend | S3 endpoint | S3 → S9 | S3 has `GET /api/v1/fundamentals/{id}/earnings-annual-trend` → NOT proxied by S9 | Proxy through S9 | New S9 route |
| Fundamentals timeseries | Frontend gateway | Frontend | S9 proxies `GET /v1/fundamentals/timeseries` — NO gateway method in `gateway.ts` | Add `getFundamentalsTimeseries()` | New gateway method |
| Fundamentals type | Frontend type | Frontend | `api.ts:112` — 22 flat fields (valuation/profitability/growth/dividends/balance/52w/daily) | Expand OR add section-specific types | Type expansion |
| OverviewLayout | Component | Frontend | `OverviewLayout.tsx:118 lines` — chart full-width + 3-column bottom grid `[3fr_3fr_4fr]` | Chart + right sidebar (70/30 split) + bottom 2-column | Layout restructure |
| FundamentalsTab | Component | Frontend | `FundamentalsTab.tsx:508 lines` — `grid-cols-2 lg:grid-cols-3` with border-b dividers, no sparklines | Left content + sticky right sidebar, bg-card sections, sparklines | Layout overhaul |
| CompactInstrumentHeader | Component | Frontend | `CompactInstrumentHeader.tsx:228 lines` — VOL always N/A, no overflow protection, no 52W range bar | Fix overflow, replace VOL, add range bar | Component fix |
| InstrumentKeyMetrics | Component | Frontend | `InstrumentKeyMetrics.tsx:135 lines` — 6 rows only (Mkt Cap, P/E, Div Yield, 52W Hi/Lo, Beta) | 12+ rows with expanded metrics | Component expansion |
| 52WeekRangeBar | Component | Frontend | Listed in DESIGN_SYSTEM.md but file does NOT exist | Build new component | New file |
| TechnicalSnapshot | Component | Frontend | Listed in DESIGN_SYSTEM.md but file does NOT exist | Build new component | New file |

---

## Sub-Plan Structure

| Sub-Plan | Scope | Waves | Depends On |
|----------|-------|-------|------------|
| **A — S9 Backend** | 6 new proxy routes + tests | 1 wave | None |
| **B — Frontend Foundation** | Types + gateway methods + shared components | 1 wave | A (for new endpoints) |
| **C — Overview Tab Redesign** | Right sidebar layout, chart toolbar, expanded metrics | 2 waves | B |
| **D — Fundamentals Tab Overhaul** | Section cards, sparklines, right sidebar, new data components | 3 waves | B |

**Dependency graph:**
```
A (S9 proxy) ──→ B (types + gateway) ──→ C-1 (overview layout)
                                     ├──→ C-2 (chart toolbar)
                                     ├──→ D-1 (section cards + trend chart)
                                     ├──→ D-2 (right sidebar)
                                     └──→ D-3 (earnings + insider + technical)
```

C-1/C-2 and D-1/D-2/D-3 can run in parallel after B completes.

**Total: 7 waves, ~35 tasks**

---

## Sub-Plan A — S9 Backend: Proxy Missing S3 Section Endpoints

### Wave A-1: Add S9 Proxy Routes for 6 S3 Fundamentals Sections ✅

**Goal**: Expose 6 existing S3 section endpoints through S9 so the frontend can access technicals, share statistics, insider transactions, earnings trend/annual, and splits/dividends data.

**Status**: **DONE** — 2026-04-27 · 203 S9 tests pass + 13 S3 tests pass · ruff + mypy clean · live endpoints validated (HTTP 200, real data)

**Depends on**: None
**Estimated effort**: 30-45 min
**Architecture layer**: API (S9 gateway proxy)

#### Pre-read
- `services/api-gateway/src/api_gateway/routes/proxy.py` (current proxy routes)
- `services/api-gateway/tests/test_routes.py` (test patterns for proxy routes)
- `services/market-data/src/market_data/api/routers/fundamentals.py` (S3 endpoint signatures)

#### Tasks

##### T-A-1-01: Add 6 fundamentals section proxy routes to S9

**Type**: impl
**depends_on**: none
**blocks**: [T-A-1-02]
**Target files**: `services/api-gateway/src/api_gateway/routes/proxy.py`
**PRD reference**: Investigation §4 (Existing Data Not Surfaced)

**What to build**:
Add 6 new GET proxy routes that forward requests to S3 Market Data's fundamentals section endpoints. Each follows the exact same pattern as the existing `get_fundamentals` proxy (lines 934-950): authenticate, forward `X-Internal-JWT`, proxy to S3, return verbatim.

**Routes to add**:

| S9 Route | S3 Target | Auth Required |
|----------|-----------|---------------|
| `GET /v1/fundamentals/{instrument_id}/technicals` | `GET /api/v1/fundamentals/{instrument_id}/technicals-snapshot` | Yes |
| `GET /v1/fundamentals/{instrument_id}/share-statistics` | `GET /api/v1/fundamentals/{instrument_id}/share-statistics` | Yes |
| `GET /v1/fundamentals/{instrument_id}/insider-transactions` | `GET /api/v1/fundamentals/{instrument_id}/insider-transactions-snapshot` | Yes |
| `GET /v1/fundamentals/{instrument_id}/earnings-trend` | `GET /api/v1/fundamentals/{instrument_id}/earnings-trend` | Yes |
| `GET /v1/fundamentals/{instrument_id}/earnings-annual-trend` | `GET /api/v1/fundamentals/{instrument_id}/earnings-annual-trend` | Yes |
| `GET /v1/fundamentals/{instrument_id}/splits-dividends` | `GET /api/v1/fundamentals/{instrument_id}/splits-dividends` | Yes |

**Logic**: Each route function:
1. Get `_clients(request)` for httpx client
2. Call `clients.market_data.get(f"/api/v1/fundamentals/{instrument_id}/<section>", headers=_auth_headers(request))`
3. Return `Response(content=resp.content, status_code=resp.status_code, media_type="application/json")`

**CRITICAL**: These routes MUST be registered AFTER the existing `get_fundamentals` route to avoid path collisions. The `{instrument_id}` pattern in `GET /fundamentals/{instrument_id}` must not match these sub-paths. FastAPI matches in registration order, and `/fundamentals/{id}/technicals` is more specific than `/fundamentals/{id}`, so register the section routes FIRST or use explicit path ordering.

**Acceptance criteria**:
- [ ] 6 new proxy routes accessible via S9
- [ ] Each forwards X-Internal-JWT header
- [ ] Each requires authentication (user JWT)
- [ ] ruff + mypy pass on `proxy.py`

##### T-A-1-02: Add tests for 6 new fundamentals section proxy routes

**Type**: test
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**: `services/api-gateway/tests/test_routes.py`
**PRD reference**: Investigation §4

**What to build**:
6 test functions following the existing pattern in `test_get_fundamentals_timeseries_proxies_to_market_data` (line 312). Each test:
1. Mocks `mock_clients.market_data.get` with a 200 response
2. Calls the S9 route via test client
3. Asserts the correct S3 path was proxied to
4. Asserts the `X-Internal-JWT` header is present

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_get_technicals_proxies_to_market_data` | GET /v1/fundamentals/{id}/technicals → S3 technicals-snapshot | unit |
| `test_get_share_statistics_proxies_to_market_data` | GET /v1/fundamentals/{id}/share-statistics → S3 share-statistics | unit |
| `test_get_insider_transactions_proxies_to_market_data` | GET /v1/fundamentals/{id}/insider-transactions → S3 insider-transactions-snapshot | unit |
| `test_get_earnings_trend_proxies_to_market_data` | GET /v1/fundamentals/{id}/earnings-trend → S3 earnings-trend | unit |
| `test_get_earnings_annual_trend_proxies_to_market_data` | GET /v1/fundamentals/{id}/earnings-annual-trend → S3 earnings-annual-trend | unit |
| `test_get_splits_dividends_proxies_to_market_data` | GET /v1/fundamentals/{id}/splits-dividends → S3 splits-dividends | unit |

**Acceptance criteria**:
- [ ] All 6 tests pass
- [ ] Tests verify S3 path AND auth header forwarding

##### T-A-1-03: Update S9 API Gateway documentation

**Type**: docs
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**: `docs/services/api-gateway.md`

**What to build**:
Add 6 new rows to the "Market Data Endpoints" table in `docs/services/api-gateway.md`. Each row documents the new route path, HTTP method, description, and auth requirement.

**Acceptance criteria**:
- [ ] All 6 new endpoints documented in api-gateway.md
- [ ] Table formatting consistent with existing entries

#### Validation Gate
- [x] ruff check passes on `services/api-gateway/`
- [x] mypy passes on `services/api-gateway/`
- [x] All existing S9 tests still pass (203/203)
- [x] 6 new proxy tests pass + 1 auth test pass
- [x] 5 new S3 endpoint tests pass (13/13 in test_fundamentals_api.py)
- [x] `docs/services/api-gateway.md` updated
- [x] Live validation: all 6 endpoints return HTTP 200 with real AAPL data

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| None | New routes only — no existing behavior changed | N/A |

#### Regression Guardrails
- BP-064: FastAPI 204 status_code — these return 200 + JSON (not 204), so safe
- BP-134: Ensure test conftest has JWT fixture if these routes require auth

---

## Sub-Plan B — Frontend Foundation: Types + Gateway Methods + Shared Components

### Wave B-1: Expand Frontend Types, Gateway Methods, and Build Shared Components ✅

**Goal**: Add TypeScript types for S3 section responses, add gateway methods for timeseries + section endpoints, and build reusable components (`52WeekRangeBar`, `FundamentalSparkline`) that later waves depend on.

**Status**: **DONE** — 2026-04-27 · 418 Vitest tests pass · tsc --noEmit clean · 7 new gateway tests pass

**Depends on**: Wave A-1 (new S9 proxy routes)
**Estimated effort**: 45-60 min
**Architecture layer**: Frontend types + gateway + components

#### Pre-read
- `apps/worldview-web/types/api.ts` (current types, 714 lines)
- `apps/worldview-web/lib/gateway.ts` (current methods, 1487 lines)
- `docs/ui/DESIGN_SYSTEM.md` (component patterns)
- `apps/worldview-web/components/instrument/InstrumentKeyMetrics.tsx` (MetricRow pattern)

#### Tasks

##### T-B-1-01: Add TypeScript types for S3 section responses

**Type**: impl
**depends_on**: none
**blocks**: [T-B-1-02, T-B-1-03]
**Target files**: `apps/worldview-web/types/api.ts`

**What to build**:
Add types for the S3 `FundamentalsResponse` format (records with section-specific `data` fields) and specific interfaces for the data shapes of each section we'll display.

**Types to add**:

```typescript
// ── Fundamentals Section Records (S3 raw format) ───────────────────────
export interface FundamentalsRecord {
  id: string;
  security_id: string;
  section: string;
  period_end: string;
  period_type: "ANNUAL" | "QUARTERLY" | "SNAPSHOT";
  data: Record<string, unknown>;
  source: string;
  ingested_at: string;
}

export interface FundamentalsSectionResponse {
  security_id: string;
  records: FundamentalsRecord[];
}

// ── Fundamentals Timeseries ───────────────────────────────────────────
export interface TimeseriesDataPoint {
  as_of_date: string;
  value_numeric: number | null;
  value_text: string | null;
  period_type: string;
}

export interface FundamentalsTimeseriesResponse {
  instrument_id: string;
  metric: string;
  data: TimeseriesDataPoint[];
}

// ── Typed section data shapes (extracted from S3 records.data) ────────
export interface TechnicalsData {
  beta: number | null;
  "52_week_high": number | null;
  "52_week_low": number | null;
  "50_day_ma": number | null;
  "200_day_ma": number | null;
  shares_short: number | null;
  short_ratio: number | null;
  short_percent: number | null;
}

export interface ShareStatisticsData {
  shares_outstanding: number | null;
  shares_float: number | null;
  percent_insiders: number | null;
  percent_institutions: number | null;
}

export interface InsiderTransaction {
  date: string;
  owner_name: string;
  transaction_type: string;
  shares: number | null;
  value: number | null;
}

export interface InstitutionalHolder {
  name: string;
  shares: number | null;
  value: number | null;
  percent_held: number | null;
  change_percent: number | null;
}

export interface EarningsRecord {
  date: string;
  eps_actual: number | null;
  eps_estimate: number | null;
  revenue_actual: number | null;
  revenue_estimate: number | null;
  surprise_percent: number | null;
}

export interface AnalystConsensusData {
  buy: number | null;
  hold: number | null;
  sell: number | null;
  strong_buy: number | null;
  strong_sell: number | null;
  target_price: number | null;
  target_price_high: number | null;
  target_price_low: number | null;
  target_price_median: number | null;
  number_of_analysts: number | null;
}
```

**Acceptance criteria**:
- [ ] All types added to `api.ts`
- [ ] TypeScript compilation passes (`pnpm tsc --noEmit`)

##### T-B-1-02: Add gateway methods for timeseries + section endpoints

**Type**: impl
**depends_on**: [T-B-1-01]
**blocks**: [T-B-1-04]
**Target files**: `apps/worldview-web/lib/gateway.ts`

**What to build**:
Add 7 new gateway methods to `createGateway()`. Each follows the existing `getFundamentals()` pattern — typed `apiFetch` call with auth token.

**Methods to add**:

```typescript
// In the "Instruments / Market Data" section of createGateway():

getFundamentalsTimeseries(
  instrumentId: string,
  metric: string,
  params?: { start_date?: string; end_date?: string; period_type?: string; limit?: number },
): Promise<FundamentalsTimeseriesResponse> {
  const qs = new URLSearchParams({
    instrument_id: instrumentId,
    metric,
    ...(params?.start_date ? { start_date: params.start_date } : {}),
    ...(params?.end_date ? { end_date: params.end_date } : {}),
    ...(params?.period_type ? { period_type: params.period_type } : {}),
    ...(params?.limit ? { limit: String(params.limit) } : {}),
  });
  return apiFetch<FundamentalsTimeseriesResponse>(
    `/v1/fundamentals/timeseries?${qs.toString()}`,
    {},  // no auth — public endpoint
  );
},

getTechnicals(instrumentId: string): Promise<FundamentalsSectionResponse> {
  return apiFetch<FundamentalsSectionResponse>(
    `/v1/fundamentals/${encodeURIComponent(instrumentId)}/technicals`,
    { token: t },
  );
},

getShareStatistics(instrumentId: string): Promise<FundamentalsSectionResponse> {
  return apiFetch<FundamentalsSectionResponse>(
    `/v1/fundamentals/${encodeURIComponent(instrumentId)}/share-statistics`,
    { token: t },
  );
},

getInsiderTransactions(instrumentId: string): Promise<FundamentalsSectionResponse> {
  return apiFetch<FundamentalsSectionResponse>(
    `/v1/fundamentals/${encodeURIComponent(instrumentId)}/insider-transactions`,
    { token: t },
  );
},

getEarningsHistory(instrumentId: string): Promise<FundamentalsSectionResponse> {
  return apiFetch<FundamentalsSectionResponse>(
    `/v1/fundamentals/${encodeURIComponent(instrumentId)}/earnings-trend`,
    { token: t },
  );
},

getSplitsDividends(instrumentId: string): Promise<FundamentalsSectionResponse> {
  return apiFetch<FundamentalsSectionResponse>(
    `/v1/fundamentals/${encodeURIComponent(instrumentId)}/splits-dividends`,
    { token: t },
  );
},
```

**Acceptance criteria**:
- [ ] 6 new gateway methods added
- [ ] TypeScript compilation passes
- [ ] Each method has WHY comments explaining the data source

##### T-B-1-03: Build `52WeekRangeBar` component

**Type**: impl
**depends_on**: [T-B-1-01]
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/52WeekRangeBar.tsx`

**What to build**:
A visual horizontal bar showing where the current price sits between the 52-week low and high. Used in: CompactInstrumentHeader (row 2) and FundamentalsTab (52-Week Range section).

**Component spec**:
```
Props: { low: number; high: number; current: number; className?: string }

Visual: [LOW ─────●────── HIGH]
        $192.41    ↑      $288.35
              current price marker

- Bar: h-1 bg-muted rounded-full, full width
- Marker: w-1.5 h-3 bg-primary rounded-full, positioned at (current-low)/(high-low) %
- Labels: font-mono text-[10px] text-muted-foreground at each end
- Edge case: if low >= high, render flat bar
- Edge case: if current < low or current > high, clamp marker to 0% or 100%
```

**Acceptance criteria**:
- [ ] Component renders correctly for AAPL-like values (low=192, high=288, current=210)
- [ ] Edge cases handled (equal values, out-of-range current)
- [ ] Uses design system tokens (--muted, --primary, font-mono)
- [ ] TypeScript clean

##### T-B-1-04: Build `FundamentalSparkline` component

**Type**: impl
**depends_on**: [T-B-1-02]
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/FundamentalSparkline.tsx`

**What to build**:
A reusable mini-chart that fetches timeseries data for a given metric and renders an SVG sparkline. Used in: Overview right sidebar (switchable metric), Fundamentals sections (inline trend).

**Component spec**:
```
Props: {
  instrumentId: string;
  metric: string;        // e.g., "pe_ratio", "revenue", "gross_margin"
  height?: number;       // default 48
  width?: number;        // default "100%" (responsive)
  showAxis?: boolean;    // default false
  className?: string;
}

Data: useQuery(["fundamentals-ts", instrumentId, metric], getFundamentalsTimeseries(...))
  - staleTime: 300_000 (5 min, fundamentals change slowly)
  - limit: 20 data points (sufficient for sparkline)

Visual:
  - SVG with polyline stroke
  - Color: positive trend = text-positive (#26A69A), negative = text-negative (#EF5350), flat = text-muted-foreground
  - Trend direction determined by comparing first vs last data point
  - Loading: Skeleton matching dimensions
  - Empty/error: subtle "—" text

No axes, no labels (showAxis=false default). When showAxis=true, show first and last x-axis labels.
```

**Acceptance criteria**:
- [ ] Sparkline renders with real timeseries data shape
- [ ] Loading/empty/error states handled
- [ ] Trend color applied correctly (positive=green, negative=red)
- [ ] Responsive width when width not specified

##### T-B-1-05: Add tests for new gateway methods

**Type**: test
**depends_on**: [T-B-1-02]
**blocks**: none
**Target files**: `apps/worldview-web/__tests__/gateway.test.ts`

**What to build**:
Tests for the 6 new gateway methods following existing patterns in the test file.

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `getFundamentalsTimeseries returns timeseries data` | Correct URL construction with query params | unit |
| `getTechnicals proxies to correct S9 endpoint` | URL path includes /technicals | unit |
| `getShareStatistics proxies correctly` | URL path includes /share-statistics | unit |
| `getInsiderTransactions proxies correctly` | URL path includes /insider-transactions | unit |
| `getEarningsHistory proxies correctly` | URL path includes /earnings-trend | unit |
| `getSplitsDividends proxies correctly` | URL path includes /splits-dividends | unit |

**Acceptance criteria**:
- [ ] All 6 tests pass with `pnpm test`
- [ ] Tests mock fetch correctly (no real API calls)

#### Validation Gate
- [x] TypeScript compilation passes (`pnpm tsc --noEmit`)
- [x] All existing Vitest tests still pass (418/418)
- [x] 7 new gateway tests pass (6 section methods + 1 timeseries with optional-params test)
- [x] No lint errors

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| None | Additive changes only — new types and methods don't affect existing code | N/A |

#### Regression Guardrails
- BP-127: Ensure pnpm lock file committed with any new deps (none expected this wave)
- Verify gateway method signatures match S9 route paths exactly

---

## Sub-Plan C — Overview Tab Redesign

### Wave C-1: Restructure Overview to Chart + Right Sidebar Layout ✅

**Goal**: Replace the current full-width chart + 3-column bottom grid with a Bloomberg-style layout: chart shares horizontal space with a right data sidebar, bottom section widens to 2-column (news + graph).

**Status**: **DONE** — 2026-04-27 · 418 Vitest tests pass · tsc --noEmit clean · live container validated (HTTP 200, real AAPL data)

**Depends on**: Wave B-1
**Estimated effort**: 45-60 min
**Architecture layer**: Frontend components

#### Pre-read
- `apps/worldview-web/components/instrument/OverviewLayout.tsx` (118 lines, current layout)
- `apps/worldview-web/components/instrument/InstrumentKeyMetrics.tsx` (135 lines, 6 rows)
- `apps/worldview-web/components/instrument/OHLCVChart.tsx` (261 lines)
- `docs/ui/DESIGN_SYSTEM.md` §4 (Spacing & Layout)

#### Tasks

##### T-C-1-01: Restructure OverviewLayout to two-column (chart + sidebar)

**Type**: impl
**depends_on**: none
**blocks**: [T-C-1-02, T-C-1-03]
**Target files**: `apps/worldview-web/components/instrument/OverviewLayout.tsx`

**What to build**:
Replace the current layout:
```
[CHART full-width]
[STRIP full-width]
[Metrics 3fr | News 3fr | Graph 4fr]
```

With Bloomberg pattern:
```
[CHART ~70% ────────────────────][RIGHT SIDEBAR ~30%]
[STRIP ─────────────────────────][                   ]
[                                ][KEY METRICS (12+)  ]
[                                ][MINI CHART 1       ]
[                                ][MINI CHART 2       ]
[NEWS 50% ──────────────────────][GRAPH 50% ─────────]
```

**Layout implementation**:
```tsx
// Root: flex flex-col
<div className="flex flex-col min-h-0">
  {/* ── Upper: chart + right sidebar ── */}
  <div className="grid grid-cols-[1fr_280px] min-h-0 border-b border-border">
    {/* Left: chart + stats strip */}
    <div className="flex flex-col min-h-0 border-r border-border">
      <OHLCVChart ... />
      <SessionStatsStrip ... />
    </div>
    {/* Right: scrollable sidebar */}
    <div className="flex flex-col overflow-y-auto">
      <ExpandedKeyMetrics fundamentals={fundamentals} />
      <FundamentalSparkline instrumentId={instrumentId} metric="pe_ratio" />
      <FundamentalSparkline instrumentId={instrumentId} metric="revenue" />
    </div>
  </div>
  {/* ── Lower: news + graph (50/50) ── */}
  <div className="grid grid-cols-2 min-h-0">
    <div className="border-r border-border">
      <InstrumentTopNews entityId={entityId} limit={6} onViewAll={onViewAllNews} />
    </div>
    <EntityGraphPanel entityId={entityId} />
  </div>
</div>
```

**Key changes**:
- Right sidebar fixed at 280px (not percentage — prevents collapse)
- Chart takes remaining width via `1fr`
- Top news increased from 4 to 6 articles
- News and graph each get 50% (was 30%/30%/40%)
- Right sidebar scrolls independently

**Acceptance criteria**:
- [ ] Chart + right sidebar render side by side
- [ ] Right sidebar scrolls independently
- [ ] Bottom section shows news and graph at equal width
- [ ] No horizontal overflow on viewport ≥1024px

##### T-C-1-02: Expand InstrumentKeyMetrics to 12+ rows

**Type**: impl
**depends_on**: [T-C-1-01]
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/InstrumentKeyMetrics.tsx`

**What to build**:
Expand from 6 metrics to 12+ metrics. The component moves from the left column of a 3-column grid to the right sidebar (280px), so it needs to fill more vertical space.

**New metric rows** (in order):
1. MARKET CAP — `formatMarketCap(fundamentals.market_cap)` (existing)
2. P/E RATIO — `formatRatio(fundamentals.pe_ratio)` + color threshold (existing)
3. FWD P/E — `formatRatio(fundamentals.forward_pe)` + color threshold (NEW)
4. EPS — `formatPrice(fundamentals.eps)` (NEW — needs type expansion)
5. DIV YIELD — `formatPercent(fundamentals.dividend_yield)` + green >3% (existing)
6. BETA — from technicals data (placeholder until D-3)
7. ROE — `formatPercent(fundamentals.roe)` + color threshold (NEW placement)
8. DEBT/EQUITY — `formatRatio(fundamentals.debt_to_equity)` + color (NEW placement)
9. 52W RANGE — `52WeekRangeBar` component (NEW)
10. AVG VOLUME — from share statistics (placeholder until D-3)
11. SECTOR — text label from CompanyOverview.instrument.sector (NEW)
12. DAILY RETURN — `formatPercent(fundamentals.daily_return)` + green/red (NEW placement)

**Component changes**:
- Accept additional prop: `instrument?: Instrument` (for sector)
- Rename to `OverviewSidebarMetrics` (better describes its new role)
- Keep `MetricRow` internal sub-component unchanged
- Section header: "KEY METRICS" (uppercase, 10px, tracking-[0.08em])

**Acceptance criteria**:
- [ ] 12 metric rows render
- [ ] 52WeekRangeBar renders inline for 52W RANGE row
- [ ] Color thresholds applied to new metrics (FWD P/E, ROE, D/E)
- [ ] Fits within 280px sidebar width

##### T-C-1-03: Wire FundamentalSparkline panels in right sidebar

**Type**: impl
**depends_on**: [T-C-1-01]
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/OverviewLayout.tsx`

**What to build**:
Add two `FundamentalSparkline` panels below the key metrics in the right sidebar. Each panel has:
- A section header with a dropdown to switch metrics
- The sparkline chart

**Implementation**:
```tsx
// In the right sidebar section of OverviewLayout:
<div className="border-t border-border p-2">
  <div className="flex items-center justify-between px-1 h-6">
    <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
      TREND
    </span>
    <select className="bg-transparent text-[10px] text-muted-foreground border-none outline-none"
      value={metric1} onChange={e => setMetric1(e.target.value)}>
      <option value="pe_ratio">P/E Ratio</option>
      <option value="revenue">Revenue</option>
      <option value="gross_margin">Gross Margin</option>
      <option value="net_margin">Net Margin</option>
      <option value="roe">ROE</option>
      <option value="debt_to_equity">D/E Ratio</option>
    </select>
  </div>
  <FundamentalSparkline instrumentId={instrumentId} metric={metric1} height={48} />
</div>
```

Two independent sparkline panels, each with its own metric selector state.

**Acceptance criteria**:
- [ ] Two sparkline panels render in right sidebar
- [ ] Metric selectors switch the displayed metric
- [ ] Loading/empty states show correctly
- [ ] Panels don't overflow 280px sidebar

#### Validation Gate
- [x] TypeScript compilation passes
- [x] All existing Vitest tests pass (no regressions, 418/418)
- [x] Layout renders correctly at 1280px+ viewport
- [x] No horizontal overflow

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx` | OverviewLayout props may change (instrument prop for sidebar metrics) | Pass `instrument` from CompanyOverview to OverviewLayout |
| Existing Vitest snapshots (if any) for OverviewLayout | Layout structure changed | Update snapshots |

#### Regression Guardrails
- BP-182: Null-guard all optional metric values — render "—" for null, never crash
- Verify responsive: at viewport <1024px, consider stacking sidebar below chart (future enhancement, not required this wave)

---

### Wave C-2: Chart Toolbar — Volume, Moving Averages, Fullscreen ✅

**Goal**: Add a toolbar above the OHLCV chart with volume bars toggle, MA50/MA200 line overlays, and a fullscreen button. Matches TradingView chart UX.

**Status**: **DONE** — 2026-04-27 · 418 Vitest tests pass · tsc --noEmit clean · live container validated

**Depends on**: Wave B-1
**Estimated effort**: 30-45 min
**Architecture layer**: Frontend components

#### Pre-read
- `apps/worldview-web/components/instrument/OHLCVChart.tsx` (261 lines)
- lightweight-charts v4 API docs (volume histogram series, line series for MAs)

#### Tasks

##### T-C-2-01: Add ChartToolbar component

**Type**: impl
**depends_on**: none
**blocks**: [T-C-2-02]
**Target files**: `apps/worldview-web/components/instrument/ChartToolbar.tsx` (new file)

**What to build**:
A toolbar strip (h-7 = 28px) that sits above the chart inside OHLCVChart. Contains toggle buttons for:
- Volume bars (on/off, default: on)
- MA50 line (on/off, default: off)
- MA200 line (on/off, default: off)
- Fullscreen toggle (expands chart to fill viewport)

**Component spec**:
```tsx
interface ChartToolbarProps {
  showVolume: boolean;
  onToggleVolume: () => void;
  showMA50: boolean;
  onToggleMA50: () => void;
  showMA200: boolean;
  onToggleMA200: () => void;
  onFullscreen: () => void;
  isFullscreen: boolean;
}
```

**Visual**: Left-aligned toggle buttons with pill style:
```
[📊 Vol ✓] [MA50] [MA200] ─────────── [⛶]
```

Active toggles: `bg-primary/20 text-primary`
Inactive: `text-muted-foreground hover:text-foreground`

**Acceptance criteria**:
- [ ] Toolbar renders with 4 toggle buttons
- [ ] Active/inactive states visually distinct
- [ ] Callbacks fire on click

##### T-C-2-02: Add volume histogram and MA line series to OHLCVChart

**Type**: impl
**depends_on**: [T-C-2-01]
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/OHLCVChart.tsx`

**What to build**:
Extend OHLCVChart to support:

1. **Volume histogram** — `addHistogramSeries()` below the candlestick area. lightweight-charts v4 supports this as a secondary price scale.
   - Color: green if close > open, red otherwise
   - Height: ~60px (allocate via `priceScaleId: 'volume'` with `scaleMargins`)

2. **MA50 / MA200 lines** — `addLineSeries()` for each. Compute client-side from OHLCV bars:
   ```typescript
   function computeMA(bars: OHLCVBar[], period: number): { time: string; value: number }[] {
     return bars.slice(period - 1).map((_, i) => ({
       time: bars[i + period - 1].timestamp,
       value: bars.slice(i, i + period).reduce((s, b) => s + b.close, 0) / period,
     }));
   }
   ```
   - MA50: `color: '#FFD60A'` (primary yellow, 1px line)
   - MA200: `color: '#0EA5E9'` (sky-500, 1px line, dashed via `lineType: 2`)

3. **Fullscreen** — Toggle a CSS class that makes the chart `fixed inset-0 z-50 bg-background` with a close button.

4. **State management**: Add `showVolume`, `showMA50`, `showMA200`, `isFullscreen` to component state. Wire to `ChartToolbar` callbacks.

**Logic for series visibility**: On toggle:
- Volume: `volumeSeriesRef.current?.applyOptions({ visible: showVolume })`
- MA lines: `ma50SeriesRef.current?.applyOptions({ visible: showMA50 })`
- Use refs to hold series instances

**Acceptance criteria**:
- [ ] Volume bars render below candlesticks with correct green/red coloring
- [ ] MA50/MA200 lines compute and render correctly
- [ ] Toggles show/hide each series without re-creating the chart
- [ ] Fullscreen mode fills viewport and has close button
- [ ] Chart height reduced from 360px to 280px to accommodate volume subplot (60px)

#### Validation Gate
- [x] TypeScript compilation passes
- [x] Existing Vitest tests pass (418/418)
- [x] Chart renders without errors on all 5 timeframes

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| None | OHLCVChart API unchanged externally; toolbar is internal | N/A |

#### Regression Guardrails
- BP-182: Handle case where bars array is too short for MA200 (< 200 bars) — render MA50 only, or skip MA entirely (computeMA returns [] for insufficient bars — handled)
- Ensure ResizeObserver still works in fullscreen mode (ResizeObserver guarded with `!isFullscreen` check)

---

## Sub-Plan D — Fundamentals Tab Overhaul

### Wave D-1: Section Cards + Revenue/Earnings Trend Chart ✅

**Goal**: Elevate fundamentals sections from flat border-b dividers to bg-card panels, and add a full-width Revenue & Earnings trend chart at the top using the timeseries endpoint.

**Status**: **DONE** — 2026-04-27 · 418 Vitest tests pass · tsc --noEmit clean · container healthy · timeseries returns 8 AAPL quarterly revenue data points

**Depends on**: Wave B-1
**Estimated effort**: 45-60 min
**Architecture layer**: Frontend components

#### Pre-read
- `apps/worldview-web/components/instrument/FundamentalsTab.tsx` (508 lines)
- `apps/worldview-web/components/instrument/RevenueTrendSparklines.tsx` (placeholder)
- recharts API (BarChart, LineChart, ComposedChart)

#### Tasks

##### T-D-1-01: Replace flat sections with bg-card elevated panels

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/FundamentalsTab.tsx`

**What to build**:
Modify the `Section` sub-component to wrap each section in a card with elevation:

**Current** (in FundamentalsTab.tsx):
```tsx
function Section({ title, children }) {
  return (
    <div>
      <div className="border-b border-border/40 px-2 py-1">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">{title}</span>
      </div>
      <div className="divide-y divide-border/20">{children}</div>
    </div>
  );
}
```

**New**:
```tsx
function Section({ title, children }) {
  return (
    <div className="bg-card border border-border rounded-[2px] overflow-hidden">
      <div className="border-b border-border px-2 py-1 bg-muted/30">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-medium">
          {title}
        </span>
      </div>
      <div className="divide-y divide-border/20">{children}</div>
    </div>
  );
}
```

**Changes**:
- Add `bg-card border border-border rounded-[2px]` to section wrapper
- Section header gets `bg-muted/30` for subtle header differentiation
- Add `overflow-hidden` for rounded-[2px] clip
- Increase grid gap from `gap-2` to `gap-2` (keep same — cards provide visual separation now)

**Acceptance criteria**:
- [ ] All 9 sections render as distinct cards with visible borders
- [ ] Section headers have subtle background differentiation
- [ ] Visual hierarchy: sections are clearly grouped, not a flat spreadsheet

##### T-D-1-02: Replace RevenueTrendSparklines placeholder with real chart

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/RevenueTrendSparklines.tsx`

**What to build**:
Replace the "Quarterly revenue data pending" placeholder with a real chart that fetches from `GET /v1/fundamentals/timeseries`.

**Implementation**:
- Use recharts `ComposedChart` (already a dependency — used in portfolio charts)
- Fetch two timeseries: `revenue` (bar chart, blue fill) and `earnings_per_share` (line overlay, yellow)
- Two `useQuery` calls with `staleTime: 300_000` (5 min)

**Chart spec**:
```
Width: full-width (responsive)
Height: 120px
X-axis: as_of_date labels (formatted as "Q1'24", "Q2'24", etc.)
Y-axis left: Revenue ($B) — bars
Y-axis right: EPS ($) — line

Bar fill: hsl(var(--primary) / 0.3) with hsl(var(--primary)) stroke
Line: hsl(var(--positive)) stroke-2

Empty state: "Revenue trend data not available" (muted text, centered)
Loading: Skeleton h-[120px]
```

**Data handling**:
- Filter timeseries to `period_type === "QUARTERLY"` for quarterly bars
- If no quarterly data, fall back to `period_type === "ANNUAL"`
- Sort by `as_of_date` ascending
- Format axis: quarter labels for quarterly, year labels for annual

**Acceptance criteria**:
- [ ] Chart renders with revenue bars + EPS line when data available
- [ ] Loading skeleton while fetching
- [ ] Graceful empty state when no timeseries data exists
- [ ] Chart uses design system colors (not hardcoded hex)
- [ ] Responsive width

##### T-D-1-03: Add 52WeekRangeBar to fundamentals 52-Week Range section

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/FundamentalsTab.tsx`

**What to build**:
Replace the plain text "52W HIGH / 52W LOW" rows in the 52-Week Range section with:
1. A `52WeekRangeBar` visual at the top of the section
2. Keep the numeric values below as `MetricRow` entries

**Acceptance criteria**:
- [ ] 52WeekRangeBar renders in the 52-Week Range section
- [ ] Shows current price position relative to high/low
- [ ] Falls back gracefully when values are null

#### Validation Gate
- [x] TypeScript compilation passes
- [x] All existing Vitest tests pass (418/418)
- [x] Section cards visible with proper elevation
- [x] Revenue chart renders (live data confirmed: 8 quarterly revenue points for AAPL)
- [x] Docker build clean (no ESLint/compile errors)

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| Any Vitest snapshot tests for FundamentalsTab | Section wrapper classes changed | Update snapshots |
| `RevenueTrendSparklines.tsx` | Complete rewrite (was placeholder) | N/A — file is being rewritten |

#### Regression Guardrails
- BP-182: All metric values must handle null — render "—", never crash
- Ensure recharts is already in `package.json` (it is — used by portfolio page). If not, add with exact version pinning.

---

### Wave D-2: Fundamentals Right Sidebar — Market Position, Competitors, Ownership, News ✅

**Goal**: Add a sticky right sidebar to the Fundamentals tab containing: Market Position, Competitor Comparison, Ownership Snapshot, and Top News.

**Status**: **DONE** — 2026-04-27 · 418 Vitest tests pass · tsc --noEmit clean · container healthy · share-statistics 65.3% institutional confirmed live

**Depends on**: Wave B-1
**Estimated effort**: 60-75 min
**Architecture layer**: Frontend components

#### Pre-read
- `apps/worldview-web/components/instrument/FundamentalsTab.tsx` (after D-1 changes)
- `apps/worldview-web/components/instrument/InstrumentTopNews.tsx` (reuse pattern)
- `apps/worldview-web/lib/gateway.ts` (screener + entity graph + share-statistics methods)

#### Tasks

##### T-D-2-01: Restructure FundamentalsTab to left content + right sidebar

**Type**: impl
**depends_on**: none
**blocks**: [T-D-2-02, T-D-2-03, T-D-2-04, T-D-2-05]
**Target files**: `apps/worldview-web/components/instrument/FundamentalsTab.tsx`

**What to build**:
Wrap the existing fundamentals content in a two-column layout:

```tsx
// Root layout change:
<div className="grid grid-cols-[1fr_280px] min-h-0">
  {/* Left: existing content (scrollable) */}
  <div className="overflow-y-auto">
    <AnalystConsensusStrip />
    <RevenueTrendSparklines instrumentId={instrumentId} />
    <div className="grid grid-cols-2 gap-2 p-3 lg:grid-cols-3">
      {/* ... existing 9 sections ... */}
    </div>
    <EarningsHistoryChart instrumentId={instrumentId} />
    <InsiderTransactionsTable instrumentId={instrumentId} />
    {/* Footer */}
  </div>
  {/* Right: sticky sidebar */}
  <div className="border-l border-border overflow-y-auto">
    <MarketPositionPanel instrument={instrument} fundamentals={fundamentals} />
    <PeerComparisonPanel entityId={entityId} instrumentId={instrumentId} />
    <OwnershipSnapshotPanel instrumentId={instrumentId} />
    <FundamentalsTopNews entityId={entityId} />
  </div>
</div>
```

**Props changes**: FundamentalsTab needs additional props:
- `entityId: string` (for news + graph queries)
- `instrument?: Instrument` (for sector/name in market position)

**Acceptance criteria**:
- [ ] Two-column layout renders (content left, sidebar right)
- [ ] Sidebar is 280px fixed width
- [ ] Left content scrolls independently
- [ ] Right sidebar scrolls independently

##### T-D-2-02: Build MarketPositionPanel

**Type**: impl
**depends_on**: [T-D-2-01]
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/MarketPositionPanel.tsx` (new)

**What to build**:
A compact panel showing the instrument's market position:

```
MARKET POSITION (section header)
─────────────────────────
Sector       Technology
Industry     Consumer Electronics
Exchange     NASDAQ
Market Cap   $4.02T (Mega Cap)
```

**Data source**: Props passed from parent (`instrument.sector`, `instrument.exchange`, `fundamentals.market_cap`).

**Market Cap tier logic**:
- ≥ $200B → "Mega Cap"
- ≥ $10B → "Large Cap"
- ≥ $2B → "Mid Cap"
- ≥ $300M → "Small Cap"
- < $300M → "Micro Cap"

**Acceptance criteria**:
- [ ] Renders sector, industry, exchange, market cap tier
- [ ] Uses MetricRow pattern (22px rows, mono values)
- [ ] Handles null values gracefully

##### T-D-2-03: Build PeerComparisonPanel

**Type**: impl
**depends_on**: [T-D-2-01]
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/PeerComparisonPanel.tsx` (new)

**What to build**:
A panel showing 3-5 peer companies compared on key metrics. Data sources:
1. **Primary**: S7 `COMPETES_WITH` edges from `getEntityGraph(entityId, 1)` — extract competitor entity IDs
2. **Fallback**: `runScreener({ filters: [{ field: "sector", op: "eq", value: instrument.sector }], sort_by: "market_cap", sort_dir: "desc", limit: 5 })` — same-sector peers by market cap

**Display**:
```
COMPETITORS (section header)
─────────────────────────
         P/E    MKT CAP   YoY
AAPL    34.6x   $4.0T    +8%  ← current (highlighted bg-muted/30)
MSFT    36.2x   $3.1T    +12%
GOOGL   25.1x   $2.0T    +6%
AMZN    61.3x   $1.9T    +14%
```

**Implementation**:
1. Fetch entity graph → filter `COMPETES_WITH` edges → get competitor entity IDs
2. For each competitor, screener data provides P/E, market cap, revenue growth
3. If no `COMPETES_WITH` edges, fall back to sector screener
4. Show current instrument highlighted at top

**Acceptance criteria**:
- [ ] Shows 3-5 peer companies with P/E, Market Cap, Growth
- [ ] Current instrument highlighted
- [ ] Falls back to sector peers when no COMPETES_WITH edges
- [ ] Loading/empty states handled
- [ ] Compact table uses font-mono tabular-nums

##### T-D-2-04: Build OwnershipSnapshotPanel

**Type**: impl
**depends_on**: [T-D-2-01]
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/OwnershipSnapshotPanel.tsx` (new)

**What to build**:
A panel showing ownership breakdown. Data source: `getShareStatistics(instrumentId)` → extract `percent_insiders`, `percent_institutions` from the records.

**Display**:
```
OWNERSHIP (section header)
─────────────────────────
Institutional    60.2%
Insider           0.07%
Mutual Funds     39.7%
Shares Out       15.4B
Float            15.3B
Short Interest    0.7%
```

**Implementation**:
- Call `getShareStatistics(instrumentId)` via useQuery (staleTime: 5 min)
- Extract fields from `records[0].data` (cast to `ShareStatisticsData`)
- Show loading skeleton while fetching
- Show "Ownership data pending" if no records

**Acceptance criteria**:
- [ ] Renders ownership percentages and share counts
- [ ] Uses MetricRow pattern (22px rows)
- [ ] Loading/empty states handled
- [ ] Percentages formatted with 2 decimal places

##### T-D-2-05: Add FundamentalsTopNews (compact 3-article panel)

**Type**: impl
**depends_on**: [T-D-2-01]
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/FundamentalsTopNews.tsx` (new)

**What to build**:
A compact news panel for the fundamentals sidebar showing the 3 most relevant articles. Reuse the data fetching pattern from `InstrumentTopNews.tsx` but with a simpler display (just title + time, no tier badge).

**Display**:
```
TOP NEWS (section header)
─────────────────────────
Apple Reports Record Q4...   2h ago
AAPL Beats Estimates on...   5h ago
iPhone 17 Supply Chain...    1d ago
─────────────────────────
→ More news
```

**Implementation**:
- `getEntityNews(entityId, { limit: 3, order_by: "display_relevance_score" })` via useQuery
- Each article: title (truncated), relative time, clickable → opens News tab
- "More news" link triggers tab switch (callback prop)

**Acceptance criteria**:
- [ ] Shows 3 articles with title + relative time
- [ ] Titles truncate with ellipsis
- [ ] "More news" link calls onViewAllNews callback
- [ ] Loading/empty states

#### Validation Gate
- [x] TypeScript compilation passes
- [x] All existing Vitest tests pass (418/418; updated 1 assertion for duplicate market cap display)
- [x] Fundamentals tab renders with right sidebar
- [x] Each sidebar panel shows loading → content flow
- [x] No horizontal overflow at 1280px+
- [x] Share statistics: 65.3% institutional, 1.64% insider confirmed live
- [x] Note: S3 share-statistics uses PascalCase keys + direct percentage values (fixed in OwnershipSnapshotPanel)

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx` | FundamentalsTab gains new props (entityId, instrument) | Pass entityId and overview.instrument to FundamentalsTab |
| Vitest snapshots for FundamentalsTab | Layout structure changed | Update snapshots |

#### Regression Guardrails
- BP-182: All section data from S3 records is `dict[str, Any]` — TypeScript `as` casts needed, but guard every field access with null checks
- Ensure PeerComparisonPanel doesn't create N+1 queries — batch screener call, not per-peer

---

### Wave D-3: Earnings History, Insider Transactions, Technical Snapshot ✅

**Status**: **DONE** — 2026-04-27 · 418 tests pass · tsc + vitest clean · Docker build passes

**Goal**: Build three new data-display components that go in the left content column of the Fundamentals tab, using the S3 section data surfaced through S9.

**Depends on**: Wave B-1 + Wave D-1 (for FundamentalsTab layout context)
**Estimated effort**: 45-60 min
**Architecture layer**: Frontend components

#### Pre-read
- `apps/worldview-web/lib/gateway.ts` (getEarningsHistory, getInsiderTransactions, getTechnicals methods from B-1)
- `apps/worldview-web/types/api.ts` (EarningsRecord, InsiderTransaction, TechnicalsData from B-1)
- recharts API (BarChart for earnings)

#### Tasks

##### T-D-3-01: Build EarningsHistoryChart

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/EarningsHistoryChart.tsx` (new)

**What to build**:
A chart showing historical EPS (actual vs estimate) with beat/miss coloring. Positioned in the left content column of FundamentalsTab, below the metric grid.

**Component spec**:
```
Props: { instrumentId: string }
Data: getEarningsHistory(instrumentId) → records with section="earnings_history"
      Extract: date, eps_actual, eps_estimate, revenue_actual, revenue_estimate

Chart type: recharts BarChart (grouped bars)
Height: 140px
Width: full-width (responsive)

Bar pairs per quarter:
  - EPS Estimate: bg-muted/50 (grey bar)
  - EPS Actual: bg-positive (green) if beat, bg-negative (red) if miss
  - "Beat" label above bar if actual > estimate

X-axis: Quarter labels ("Q1'24", "Q2'24", ...)
Y-axis: EPS values ($)

Section header: "EARNINGS HISTORY" (uppercase, 10px)
Empty state: "Earnings history not available"
Loading: Skeleton h-[140px]
```

**Data extraction from S3 records**:
```typescript
const earnings = records
  .filter(r => r.section === "earnings_history")
  .map(r => ({
    date: r.period_end,
    eps_actual: r.data.epsActual as number | null,
    eps_estimate: r.data.epsEstimate as number | null,
    // ... other fields
  }))
  .sort((a, b) => a.date.localeCompare(b.date));
```

**Acceptance criteria**:
- [ ] Grouped bar chart renders with estimate vs actual
- [ ] Beat = green bar, miss = red bar
- [ ] Loading/empty states
- [ ] Design system colors, font-mono axis labels

##### T-D-3-02: Build InsiderTransactionsTable

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/InsiderTransactionsTable.tsx` (new)

**What to build**:
A compact table showing the 10 most recent insider transactions. Positioned in the left content column of FundamentalsTab.

**Component spec**:
```
Props: { instrumentId: string }
Data: getInsiderTransactions(instrumentId) → records with section="insider_transactions_snapshot"

Table columns:
  DATE       NAME              TYPE    SHARES     VALUE
  Apr 12     Tim Cook          Sale    100,000    $21.0M
  Mar 28     Jeff Williams     Buy      50,000    $10.2M

- DATE: font-mono text-[10px]
- NAME: truncate at 20 chars
- TYPE: Badge (BUY = text-positive, SALE = text-negative, OPTION = text-muted-foreground)
- SHARES/VALUE: font-mono tabular-nums text-right

Section header: "INSIDER TRANSACTIONS" (with bg-card panel wrapper)
Max rows: 10 (most recent)
Empty state: "No insider transactions available"
Loading: 5 Skeleton rows
```

**Acceptance criteria**:
- [ ] Table renders with DATE, NAME, TYPE, SHARES, VALUE columns
- [ ] BUY/SALE color-coded
- [ ] Compact density (22px rows)
- [ ] Loading/empty states

##### T-D-3-03: Build TechnicalSnapshot component

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/TechnicalSnapshot.tsx` (new)

**What to build**:
A section panel showing technical indicators. Replaces the "—" Beta placeholder in InstrumentKeyMetrics and adds MA/RSI/short interest data. Used as a section in the FundamentalsTab metric grid.

**Component spec**:
```
Props: { instrumentId: string }
Data: getTechnicals(instrumentId) → records with section="technicals_snapshot"

Metrics displayed (in MetricRow format):
  BETA           1.21
  50-DAY MA      $215.30  ↑ (green if price > MA50, red if below)
  200-DAY MA     $198.75  ↑
  SHORT INT      0.7%     (red if > 5%)
  SHORT RATIO    2.3

Section wrapper: bg-card border rounded-[2px] (matches D-1 section card style)
Section header: "TECHNICAL"
Loading: MetricRow skeletons
Empty: "Technical data pending"
```

**MA direction indicators**:
- Compare current price (from parent fundamentals prop) with MA value
- Price > MA → ↑ (text-positive)
- Price < MA → ↓ (text-negative)

**Acceptance criteria**:
- [ ] 5 technical metrics render
- [ ] MA direction arrows with semantic coloring
- [ ] Short interest highlighted when high (>5%)
- [ ] Loading/empty states
- [ ] Replaces the "BETA —" placeholder in the fundamentals grid

##### T-D-3-04: Wire new components into FundamentalsTab

**Type**: impl
**depends_on**: [T-D-3-01, T-D-3-02, T-D-3-03]
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/FundamentalsTab.tsx`

**What to build**:
Import and place the three new components into the FundamentalsTab left content column:

1. `EarningsHistoryChart` — below the metric grid, above footer
2. `InsiderTransactionsTable` — below earnings chart
3. `TechnicalSnapshot` — replaces the existing "Debt & Credit" or adds as new 10th section in the metric grid (replace the weak "Debt & Credit" section which has 3 "—" fields with TechnicalSnapshot)

**Layout order in left column**:
```
AnalystConsensusStrip
RevenueTrendSparklines (now real chart from D-1)
[3-column metric grid: Valuation | Profitability | Growth]
[3-column metric grid: Dividends | Balance Sheet | 52-Week Range]
[3-column metric grid: Debt & Credit | Cash Flow | TECHNICAL (new)]
EarningsHistoryChart (full-width)
InsiderTransactionsTable (full-width, bg-card wrapper)
Footer
```

**Acceptance criteria**:
- [ ] All three components render in the correct positions
- [ ] TechnicalSnapshot replaces or supplements existing grid section
- [ ] Page scrolls smoothly with all new content
- [ ] No layout breaks

#### Validation Gate
- [x] TypeScript compilation passes
- [x] All existing Vitest tests pass (418/418)
- [x] New components render loading → content states (confirmed via live containers)
- [x] No console errors
- [x] Docker production build passes
- [x] Live data confirmed: 33 EPS annual records, 4+ insider txns, Beta/MA/short data for AAPL
- **Fix note**: `getEarningsHistory` endpoint corrected from `/earnings-trend` (forward estimates)
  to `/earnings-annual-trend` (historical actuals) — gateway test updated accordingly

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| FundamentalsTab.tsx | Adding imports and component placements | Part of T-D-3-04 |

#### Regression Guardrails
- BP-182: S3 section records return `data: dict[str, Any]` — all field accesses must be null-guarded
- Earnings chart: Handle case where S3 returns 0 earnings records (stock has no earnings history)
- Insider transactions: Handle case where insider_transactions_snapshot has no records (many stocks lack this data)
- Technicals: Handle case where technicals_snapshot returns null for all fields (newly listed stocks)

---

## Top Bar Fixes (Integrated into Waves)

The CompactInstrumentHeader fixes are integrated across waves:

| Fix | Wave | Task |
|-----|------|------|
| Add overflow protection to stat values | C-1 | Part of T-C-1-02 (expanding metrics touches header) |
| Replace VOL N/A with Div Yield | C-1 | Modify CompactInstrumentHeader in same wave |
| Add 52WeekRangeBar to header row 2 | C-1 | Use component from B-1 |
| Suppress stale "00:00:00 UTC" timestamp | C-1 | Modify LiveQuoteBadge stale logic |
| Color-code P/E in header | C-1 | Apply getMetricClass() from FundamentalsTab |

These changes are added as sub-tasks within Wave C-1 since they modify the same page.

---

## Cross-Cutting Concerns

### Contract changes
- No Avro schema changes
- No Kafka topic changes
- Frontend types expanded (additive only)

### Migration needs
- No database migrations

### Configuration changes
- No new env vars

### Documentation updates
- `docs/services/api-gateway.md` — 6 new endpoint rows (Wave A-1)
- `docs/ui/DESIGN_SYSTEM.md` — Add 52WeekRangeBar, FundamentalSparkline, TechnicalSnapshot to §5.2 Custom Domain Components
- `apps/worldview-web/components/instrument/` — New component files documented inline

---

## Risk Assessment

### Critical path
Wave A-1 (S9 proxy) → Wave B-1 (types + gateway) → everything else in parallel

### Highest risk
- **Wave D-2 (PeerComparisonPanel)**: Depends on COMPETES_WITH edges existing in S7 graph data. If no edges exist for a given entity, the fallback sector screener must work correctly.
- **Wave D-1 (RevenueTrendSparklines)**: Depends on fundamentals timeseries having data. If S3's `fundamental_metrics` table is empty for an instrument, the chart shows empty state.

### Testing gaps
- No E2E tests for new components (Vitest unit tests only)
- S3 section endpoints return `data: dict[str, Any]` — TypeScript types are our best-effort interpretation of the data shape. Runtime mismatches possible.

### Rollback strategy
Each wave is independently committable. If any wave fails, previous waves still leave the codebase functional.

---

## Summary

| Metric | Value |
|--------|-------|
| Sub-Plans | 4 (A: backend, B: foundation, C: overview, D: fundamentals) |
| Waves | 7 |
| Tasks | 24 |
| New S9 endpoints | 6 |
| New frontend components | 10 |
| New gateway methods | 6 |
| Estimated total effort | 5-7 hours |
| Critical path | A-1 → B-1 → (C-1 ∥ C-2 ∥ D-1 ∥ D-2 ∥ D-3) |
