---
id: PLAN-0091
title: Data Enrichment — Tier 1 / 2 / 3 Intelligence Features
prd: investigation-2026-05-22
status: draft
created: 2026-05-22
updated: 2026-05-22
---

# PLAN-0091 — Data Enrichment: Tier 1 / 2 / 3 Intelligence Features

## Overview

Source: Investigation report 2026-05-22 — "Is there any other information we could provide from backend that other platforms are offering and clients/markets are demanding?"

Three tiers of work:
- **Tier 1**: Backend endpoints already exist; only UI components missing
- **Tier 2**: Backend stores the data; S9 schema extensions + 1-2 new endpoints needed
- **Tier 3**: Data is derivable from existing sources; requires application logic + UI

> **No DB migrations needed.** All backend changes are S9 Pydantic schema extensions or new S9 composition endpoints.

Services affected: `services/api-gateway` (S9), `apps/worldview-web`

---

## Pre-flight Verification

| Check | Result |
|---|---|
| No unresolved BLOCKING OQs | PASS — investigation is the source; no OQ block |
| No active cross-plan conflicts on S9 routes | PASS — PLAN-0090 is frontend-only (no S9 route changes) |
| Architecture compliance | PASS — S9-only changes, no cross-service DB access |
| Alembic HEAD (intelligence-migrations) | `0041_add_financial_relation_types.py` |
| DB migrations needed | **NONE** — all changes are S9 Pydantic + frontend |

---

## Sub-Plans and Dependencies

```
Sub-Plan A (Backend S9 extensions)
    ↓
Sub-Plan C (Instrument page — news sentiment needs A)
Sub-Plan D (Intelligence tab — graph enrichment needs A)
    ↓ (B and E independent)
Sub-Plan B (Portfolio/Risk frontend — no backend deps)
Sub-Plan E (Backend Tier 3 logic)
    ↓
Sub-Plan F (Tier 3 frontend — depends on E)
```

| Sub-Plan | Description | Depends On | Waves | Est. Effort |
|---|---|---|---|---|
| A | Backend: S9 schema extensions + new endpoints | none | 2 | 3h |
| B | Frontend: Portfolio risk & concentration | none | 2 | 4h |
| C | Frontend: Instrument page enrichment | A | 2 | 4h |
| D | Frontend: Intelligence tab enrichment | A | 2 | 3h |
| E | Backend: Tier 3 application logic | none | 2 | 4h |
| F | Frontend: Tier 3 advanced features | E | 3 | 6h |

**Total**: 13 waves · ~48 tasks · ~24h estimated

---

## Sub-Plan A — Backend: S9 Schema Extensions

**Goal**: Forward fields that S6 and S7 already return but S9 filters out, and add two new composition endpoints.

### Wave A-1: News + Graph response enrichment

**Goal**: Extend two response schemas — add sentiment/impact_windows to news, add valid_from/valid_to + industry/market_cap to graph.
**Depends on**: none
**Estimated effort**: 1.5h
**Architecture layer**: API (S9 schemas + route transforms)

#### T-A-1-01: Extend `NewsTopResponse` with sentiment + impact fields

**Type**: impl
**depends_on**: none
**blocks**: [T-C-2-01]
**Target files**:
- `services/api-gateway/src/api_gateway/schemas/news.py`
- `services/api-gateway/src/api_gateway/routes/content.py`
- `services/api-gateway/tests/api/test_news.py`

**What to build**:
S6's `RankedArticleResponse` already returns `sentiment` (str | None), `impact_windows` (`{day_t0, day_t1, day_t2, day_t5}` | None), and `impact_score` (float | None). S9's `NewsTopResponse` currently omits these three fields when serializing the forwarded S6 response. Add them to the S9 `ArticleResponse` Pydantic model so they flow through to the frontend unchanged.

**Fields to add to `ArticleResponse` (in `schemas/news.py`)**:
- `sentiment: str | None = None` — one of `"positive"`, `"negative"`, `"neutral"`, `"mixed"`
- `impact_windows: dict[str, float | None] | None = None` — keys `day_t0`, `day_t1`, `day_t2`, `day_t5`
- `impact_score: float | None = None` — MAX(day_t0, day_t1) pre-computed by S6

**Logic**: No computation needed — just add the fields to the Pydantic model. The S6 response already includes them. The `content.py` route that maps S6 fields to S9 schema needs to copy these three fields.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_news_top_includes_sentiment` | response.articles[0].sentiment is not filtered out | unit |
| `test_news_top_includes_impact_windows` | response.articles[0].impact_windows contains day_t0..t5 | unit |
| `test_news_top_impact_score_nullable` | sentiment=None when S6 returns null (LIGHT-tier article) | unit |

**Acceptance criteria**:
- [ ] `GET /v1/news/top` response includes `sentiment`, `impact_windows`, `impact_score` fields
- [ ] Fields are nullable (not required — LIGHT-tier articles have no scores)
- [ ] Entity articles endpoint (`/v1/entities/{id}/articles`) also includes the new fields
- [ ] Existing news tests still pass

---

#### T-A-1-02: Extend graph edge response with `valid_from` + `valid_to`

**Type**: impl
**depends_on**: none
**blocks**: [T-D-2-02]
**Target files**:
- `services/api-gateway/src/api_gateway/routes/intelligence.py`
- `services/api-gateway/src/api_gateway/schemas/intelligence.py` (or inline schema in routes)
- `services/api-gateway/tests/api/test_intelligence.py`

**What to build**:
S7's `RelationResponse` already includes `valid_from: datetime | None` and `valid_to: datetime | None` when the `confidence_breakdown` query param is passed. The S9 `_transform_graph_response()` function (lines 30–155 of `routes/intelligence.py`) builds the edge dict but discards these fields. Pass `confidence_breakdown=true` to S7 and forward `valid_from`/`valid_to` on every edge.

**Fields to add to graph edge schema**:
- `valid_from: str | None = None` — ISO-8601 datetime string (serialized from S7 datetime)
- `valid_to: str | None = None` — ISO-8601 datetime string, null for ongoing relations
- `confidence_stale: bool = False` — flag when confidence score is >30 days old

**Logic change in `_transform_graph_response()`**:
1. Add `confidence_breakdown=true` to the S7 graph fetch call
2. In the edge-building loop, extract `valid_from`, `valid_to`, `confidence_stale` from each `RelationResponse`
3. Serialize datetimes to ISO strings before adding to the edge dict

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_graph_edges_include_valid_from` | edge response has valid_from field | unit |
| `test_graph_edges_valid_to_null_for_ongoing` | ongoing relations have valid_to=null | unit |
| `test_graph_confidence_breakdown_param_passed` | S7 call includes confidence_breakdown=true | unit |

**Acceptance criteria**:
- [ ] `GET /v1/entities/{id}/graph` edges include `valid_from`, `valid_to`, `confidence_stale`
- [ ] `valid_to: null` for ongoing relations (not ended)
- [ ] Existing graph tests still pass

---

#### T-A-1-03: Extend graph node response with `industry` + `market_cap`

**Type**: impl
**depends_on**: none
**blocks**: [T-D-2-02]
**Target files**:
- `services/api-gateway/src/api_gateway/routes/intelligence.py`
- `services/knowledge-graph/src/knowledge_graph/api/schemas/graph.py`

**What to build**:
S7's `EntitySummary` model (returned in `GraphNeighborhoodResponse.entities` dict) currently surfaces `ticker`, `exchange`, `isin`. The `canonical_entities.metadata` JSONB column stores `sector`, `industry`, `market_cap`. Extend S7's `EntitySummary` to include `industry: str | None` and `market_cap: float | None` extracted from the metadata JSONB, then forward these in S9's node-building loop.

**Fields to add to S7 `EntitySummary`** (in `knowledge_graph/api/schemas/graph.py`):
- `industry: str | None = None` — from `metadata.get("industry")`
- `market_cap: float | None = None` — from `metadata.get("market_cap")`

**Fields to add to S9 graph node schema**:
- `industry: str | None = None`
- `market_cap: float | None = None`

**Logic**: In the `_transform_graph_response()` node-building loop, extract `industry` and `market_cap` from the entity dict and include in each node.

**Tests**:
- `test_graph_nodes_include_industry` — node has industry field when entity has metadata
- `test_graph_nodes_market_cap_nullable` — null when entity has no market_cap in metadata

**Acceptance criteria**:
- [ ] Graph nodes include `industry`, `market_cap` fields
- [ ] Fields are null for entities without market data (people, organizations without ticker)

---

#### Validation Gate — Wave A-1
- [ ] ruff + mypy pass on S9 and S7 routes
- [ ] `GET /v1/news/top` returns `sentiment`, `impact_windows`, `impact_score`
- [ ] `GET /v1/entities/{id}/graph` edges return `valid_from`, `valid_to`; nodes return `industry`, `market_cap`
- [ ] All existing API tests pass (no regressions)
- [ ] R25: no concrete infrastructure imports in use cases
- [ ] R27: GET endpoints use ReadUoWDep (graph route is read-only)

**Break Impact**:
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `services/api-gateway/tests/api/test_news.py` | ArticleResponse has new fields | Add nullable field assertions; ensure no `assert len(article.keys()) == N` type checks |
| `services/api-gateway/tests/api/test_intelligence.py` | Edge response has new fields | Add assertions for `valid_from`, `valid_to` fields |

**Regression Guardrails**:
- BP-064 (FastAPI 204): these are GET routes with 200 responses, no 204 risk
- BP-405: verified all class/method names above via pre-flight (`_transform_graph_response` confirmed in routes/intelligence.py)

---

### Wave A-2: New S9 composition endpoints

**Goal**: Add three new S9 endpoints: article impact history, sentiment timeseries, portfolio sector attribution.
**Depends on**: Wave A-1 (shares intelligence route context)
**Estimated effort**: 2h
**Architecture layer**: API (S9 new routes)

#### T-A-2-01: `GET /v1/articles/{article_id}/impact-history` (NEW endpoint)

**Type**: impl
**depends_on**: none
**blocks**: [T-C-2-02]
**Target files**:
- `services/api-gateway/src/api_gateway/routes/content.py`
- `services/api-gateway/src/api_gateway/schemas/news.py`

**What to build**:
New S9 endpoint that fetches the multi-window price impact for a single article from S6. S6 has `article_impact_windows` table with `day_t0`, `day_t1`, `day_t2`, `day_t5` price delta percentages. S6 must expose a new internal endpoint, or S9 calls the existing entity articles endpoint with filters. Check if S6 has a `/api/v1/articles/{doc_id}/impact-windows` endpoint; if not, this task adds it.

**Response schema** (`ArticleImpactHistoryResponse` — NEW):
```python
class ImpactWindow(BaseModel):
    window: str          # "t0", "t1", "t2", "t5"
    delta_pct: float | None
    high_pct: float | None
    low_pct: float | None
    volume: int | None
    impact_score: float | None
    data_quality: str | None  # "intraday" | "daily_proxy"

class ArticleImpactHistoryResponse(BaseModel):
    article_id: str
    entity_id: str | None
    windows: list[ImpactWindow]
```

**Logic**: S9 calls S6 `GET /api/v1/articles/{doc_id}/impact-windows` (add this endpoint to S6 if not present). Returns all 4 windows sorted by window label.

**Read-only**: YES → ReadUoWDep (S9 level)

**Acceptance criteria**:
- [ ] `GET /v1/articles/{article_id}/impact-history` returns 4 windows (t0, t1, t2, t5)
- [ ] Returns 404 when article_id not found
- [ ] `data_quality` field distinguishes estimated vs measured impact

---

#### T-A-2-02: `GET /v1/entities/{id}/sentiment-timeseries` (NEW endpoint)

**Type**: impl
**depends_on**: none
**blocks**: [T-F-2-02]
**Target files**:
- `services/api-gateway/src/api_gateway/routes/intelligence.py`
- `services/api-gateway/src/api_gateway/schemas/intelligence.py`
- `services/nlp-pipeline/src/nlp_pipeline/api/routers/` (new internal route)

**What to build**:
New S9 endpoint that returns daily aggregated sentiment and article volume for an entity over the last N days. Used to render the sentiment trend overlay on the price chart (Tier 3 frontend feature). S6 must expose a new aggregation endpoint — `GET /api/v1/entities/{entity_id}/sentiment-timeseries?days=90&granularity=1d`.

**S6 internal aggregation query** (new use case in nlp-pipeline):
```sql
SELECT
    date_trunc('day', published_at) AS day,
    COUNT(*) AS article_count,
    AVG(llm_relevance_score) AS avg_relevance,
    SUM(CASE WHEN sentiment = 'positive' THEN 1 ELSE 0 END)::float / COUNT(*) AS positive_ratio,
    SUM(CASE WHEN sentiment = 'negative' THEN 1 ELSE 0 END)::float / COUNT(*) AS negative_ratio,
    AVG(impact_score) AS avg_impact_score
FROM document_source_metadata dsm
JOIN entity_mentions em ON em.doc_id = dsm.doc_id
WHERE em.resolved_entity_id = :entity_id
  AND dsm.published_at >= NOW() - INTERVAL ':days days'
  AND dsm.llm_relevance_score IS NOT NULL
GROUP BY 1
ORDER BY 1
```

**S9 response schema** (`EntitySentimentTimeseriesResponse` — NEW):
```python
class SentimentDataPoint(BaseModel):
    date: str           # YYYY-MM-DD
    article_count: int
    avg_relevance: float | None
    positive_ratio: float | None  # 0–1
    negative_ratio: float | None  # 0–1
    avg_impact_score: float | None

class EntitySentimentTimeseriesResponse(BaseModel):
    entity_id: str
    days: int
    points: list[SentimentDataPoint]
```

**Read-only**: YES → ReadOnlyUnitOfWork + ReadUoWDep in S6

**Acceptance criteria**:
- [ ] `GET /v1/entities/{id}/sentiment-timeseries?days=90` returns daily sentiment points
- [ ] Returns empty `points: []` when no articles exist (not 404)
- [ ] `days` param defaults to 90, max 365

---

#### T-A-2-03: `GET /v1/portfolios/{id}/sector-attribution` (NEW endpoint)

**Type**: impl
**depends_on**: none
**blocks**: [T-F-3-01]
**Target files**:
- `services/api-gateway/src/api_gateway/routes/portfolio.py` (or new `attribution.py`)
- `services/api-gateway/src/api_gateway/schemas/portfolio.py`

**What to build**:
New S9 composition endpoint that derives portfolio sector attribution from existing data: holdings + live quotes + instrument sector. All three sources are already in S9's reach (S1 for holdings, S3 for quotes and sector).

**Algorithm**:
1. Fetch holdings from S1 (`GET /v1/holdings/{portfolio_id}`)
2. Fetch batch quotes from S3 for all instrument IDs
3. Fetch instrument overviews for sector/industry from S3 (or use company overview cache)
4. Compute: `sector_value = Σ(holding.quantity × quote.price)` per sector
5. Compute: `sector_weight = sector_value / total_portfolio_value`
6. Compute: `sector_day_pnl = Σ(holding.quantity × quote.day_change)` per sector

**Response schema** (`PortfolioSectorAttributionResponse` — NEW):
```python
class SectorBucket(BaseModel):
    sector: str
    weight_pct: float       # 0–100
    market_value: float
    day_pnl: float
    day_pnl_pct: float | None
    positions_count: int

class PortfolioSectorAttributionResponse(BaseModel):
    portfolio_id: str
    total_value: float
    sectors: list[SectorBucket]  # sorted by weight_pct desc
    prices_stale: bool
    as_of: str  # ISO-8601
```

**Read-only**: YES — pure composition, no writes.

**Acceptance criteria**:
- [ ] `GET /v1/portfolios/{id}/sector-attribution` returns sector buckets summing to ~100%
- [ ] `prices_stale: true` when any quote is from prior close
- [ ] Returns empty `sectors: []` for empty portfolio

---

#### T-A-2-04: `GET /v1/market/yield-curve` (NEW endpoint)

**Type**: impl
**depends_on**: none
**blocks**: [T-F-4-01]
**Target files**:
- `services/api-gateway/src/api_gateway/routes/market.py`
- `services/api-gateway/src/api_gateway/schemas/market.py`

**What to build**:
New S9 endpoint that fetches Treasury yield data for 2Y, 5Y, 10Y, 30Y maturities (using EODHD economic events or batch quotes for ETF proxies: SHY/IEF/TLT/TLT), computes the 2s10s spread, and returns a structured yield curve object.

**Strategy**: Use `POST /v1/quotes/batch` for known Treasury ETF proxies — the maturities map as:
- 2Y → SHY (yield ≈ price-implied, or use TNX-2 from EODHD macro)
- 5Y → IEI
- 10Y → TNX (already in market strip)
- 30Y → TLT (yield ≈ 3.5% when price ~$92)

The cleanest approach: expose the EODHD macro timeseries for yields via S3's economic calendar endpoint. Check if S3 stores treasury yields as `TemporalEvent` rows; if so, query them directly. Otherwise use ETF proxy.

**Response schema** (`YieldCurveResponse` — NEW):
```python
class YieldPoint(BaseModel):
    maturity: str   # "2Y", "5Y", "10Y", "30Y"
    yield_pct: float
    change_1d: float | None

class YieldCurveResponse(BaseModel):
    points: list[YieldPoint]  # sorted by maturity
    spread_2s10s: float | None  # 10Y yield - 2Y yield (in bps when multiplied by 100)
    spread_2s10s_inverted: bool
    as_of: str  # ISO-8601
```

**Acceptance criteria**:
- [ ] `GET /v1/market/yield-curve` returns 4 maturity points
- [ ] `spread_2s10s_inverted: true` when 2s10s spread < 0
- [ ] Returns 503 gracefully when yield data unavailable

---

#### Validation Gate — Wave A-2
- [ ] ruff + mypy pass on all new routes
- [ ] 4 new endpoints all return 200 with correct schemas against a test payload
- [ ] ReadOnly use cases use `ReadUoWDep` (R27)
- [ ] No concrete infra imports in new composition logic (R25)
- [ ] All 4 new routes registered in S9 app router

**Regression Guardrails**:
- BP-235 (httpx timeout shadowing): all new S9→S6/S1/S3 calls must use `httpx.Timeout(N)` not `asyncio.wait_for`
- BP-064: all new routes return 200 + dict, not 204 + None

---

## Sub-Plan B — Frontend: Portfolio Risk & Concentration

**Goal**: Surface the 4 risk/portfolio endpoints already live in S9 (risk-metrics, concentration, FIFO lots, watchlist insights) via new UI components on the Portfolio Overview and Dashboard pages.

### Wave B-1: Risk metrics + concentration UI

**Goal**: Add `RiskMetricsPanel` and `ConcentrationWidget` to the portfolio/dashboard view.
**Depends on**: none (endpoints already exist)
**Estimated effort**: 2h
**Architecture layer**: Frontend components

#### T-B-1-01: `RiskMetricsPanel` component (NEW)

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/components/portfolio/RiskMetricsPanel.tsx` (NEW)
- `apps/worldview-web/lib/gateway.ts` — `getRiskMetrics()` already exists; add TanStack Query hook
- `apps/worldview-web/lib/query/keys.ts` — add `qk.riskMetrics(id)`

**What to build**:
Dense metrics panel showing portfolio risk statistics. Calls `GET /v1/portfolios/{id}/risk-metrics`.

**Visual spec** (Bloomberg PORT-style):
```
RISK METRICS (90D)                        [90D · 180D · 1Y ▾]
SHARPE    SORTINO   BETA vs SPY   VOLATILITY (ann.)   MAX DRAWDOWN
  1.24      1.87       0.82           18.4%              -12.3%
CURRENT DRAWDOWN    DATA QUALITY    AS OF
     -4.1%             OK          2026-05-22
```

Layout: 6 monospaced metric cells in 2 rows × 3 cols at 22px row height. Lookback period chip strip (90D/180D/1Y). Empty state: "Insufficient data (min 10 trading days required)".

**Props**: `portfolioId: string`
**Query key**: `qk.riskMetrics(portfolioId)` → `["portfolio","risk-metrics",portfolioId]` (NEW in keys.ts)
**staleTime**: 5 min | **refetchInterval**: none (daily data)

**Acceptance criteria**:
- [ ] Renders all 6 risk metrics with correct positive/negative colouring
- [ ] Loading skeleton at correct panel height (no layout shift)
- [ ] `data_quality: "insufficient_data"` shows empty state instead of zeroes
- [ ] Lookback chip updates query param correctly

---

#### T-B-1-02: `ConcentrationWidget` component (NEW)

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/components/portfolio/ConcentrationWidget.tsx` (NEW)
- `apps/worldview-web/lib/query/keys.ts` — add `qk.concentration(id)`

**What to build**:
Portfolio concentration panel. Calls `GET /v1/portfolios/{id}/concentration`.

**Visual spec**:
```
CONCENTRATION                              HHI: 1,240  MODERATE
TOP 3 WEIGHT    POSITIONS    LABEL
    42.3%           12       ▓▓▓▓▓░░░░░░ moderate
```

Plus a compact bar chart showing top-5 position weights (from `top_positions`).

**Query key**: `qk.concentration(portfolioId)` → `["portfolio","concentration",portfolioId]` (NEW)
**staleTime**: 30s

**HHI label mapping**: `< 1000 = "diversified"`, `1000–2500 = "moderate"`, `> 2500 = "concentrated"`, text-muted / text-warning / text-negative respectively.

**Acceptance criteria**:
- [ ] HHI displayed with label + colour coding
- [ ] Top-5 positions shown as weight bars
- [ ] Empty state: "No positions"

---

#### T-B-1-03: `SectorAttributionWidget` component (NEW — depends on A-2)

**Type**: impl
**depends_on**: [T-A-2-03]
**blocks**: none
**Target files**:
- `apps/worldview-web/components/portfolio/SectorAttributionWidget.tsx` (NEW)
- `apps/worldview-web/lib/gateway.ts` — add `getPortfolioSectorAttribution()` method (NEW)
- `apps/worldview-web/lib/query/keys.ts` — add `qk.sectorAttribution(id)`

**What to build**:
Horizontal bar chart showing portfolio weight by sector. Each row: `SECTOR_NAME [████░░░░] 32.4% +$1,240`. Sorted by weight descending. Calls the new `GET /v1/portfolios/{id}/sector-attribution` endpoint.

**Props**: `portfolioId: string`
**Query key**: `qk.sectorAttribution(portfolioId)` → `["portfolio","sector-attribution",portfolioId]`
**staleTime**: 30s

**Acceptance criteria**:
- [ ] Sector rows sorted by weight descending
- [ ] Day P&L shown in positive/negative colour per row
- [ ] Loading: 5 ghost rows at 22px
- [ ] Empty: "No sector data available"

---

#### Validation Gate — Wave B-1
- [ ] 3 new components render without TypeScript errors
- [ ] TanStack Query hooks defined with correct keys and staleTime
- [ ] All 3 new query keys added to `lib/query/keys.ts`
- [ ] Gateway client method for sector-attribution added
- [ ] Vitest snapshot/unit tests: ≥ 3 per component (loading, data, empty states)

---

### Wave B-2: FIFO lots + watchlist insights

**Goal**: Add FIFO lot drill-down to Holdings table and a WatchlistInsightsPanel.
**Depends on**: none
**Estimated effort**: 2h

#### T-B-2-01: FIFO lot drill-down in Holdings table

**Type**: impl
**depends_on**: none
**Target files**:
- `apps/worldview-web/components/portfolio/HoldingLotsDrawer.tsx` (NEW)
- `apps/worldview-web/lib/query/keys.ts` — add `qk.holdingLots(portfolioId, instrumentId)`
- Existing holdings table component — add row expand affordance

**What to build**:
Expandable row in the holdings table that shows FIFO lot detail. Clicking a holdings row fetches `GET /v1/portfolios/{id}/holdings/{instrument_id}/lots` and renders:
```
LOT DATE    QTY     COST/SH    DAYS HELD    L/S-TERM    UNR P&L
2024-01-15  50      $398.20      492d         LT        +$1,402
2024-08-03  130     $420.10      261d         ST        -$2,840
TOTAL       180     $412.10
```
`L/S-TERM` = long-term (>365d) shown in text-positive, short-term in text-muted.

**Props**: `portfolioId: string`, `instrumentId: string`, `open: boolean`, `onClose: () => void`
**Query key**: `qk.holdingLots(portfolioId, instrumentId)` → `["holding","lots",portfolioId,instrumentId]`
**staleTime**: 5min (lots change only on new transactions)

**Acceptance criteria**:
- [ ] Lot rows sorted by open_date ascending
- [ ] Long-term lots (>365d) highlighted
- [ ] Total row shows weighted avg cost
- [ ] Closes cleanly, no stale data shown

---

#### T-B-2-02: `WatchlistInsightsPanel` component (NEW)

**Type**: impl
**depends_on**: none
**Target files**:
- `apps/worldview-web/components/watchlist/WatchlistInsightsPanel.tsx` (NEW)
- `apps/worldview-web/lib/query/keys.ts` — add `qk.watchlistInsights(id)`

**What to build**:
Compact panel showing watchlist aggregate stats. Calls `GET /v1/watchlists/{id}/insights`.

**Visual spec**:
```
WATCHLIST: Tech Growth (12 members)         1D: +0.42%
BIGGEST MOVER: SMCI +18.4%  BIGGEST NEWS: "TSMC Cuts…" (AAPL)
SECTORS: TECH 42% · SEMI 28% · COMM 15% · OTHER 15%
```

**Query key**: `qk.watchlistInsights(watchlistId)` → `["watchlist","insights",watchlistId]`
**staleTime**: 60s | **refetchInterval**: 60s

**Acceptance criteria**:
- [ ] 1D weighted return shown with positive/negative colour
- [ ] Biggest mover ticker links to instrument page
- [ ] Sector pills rendered as proportional chips
- [ ] Empty: "Add instruments to see insights"

---

#### Validation Gate — Wave B-2
- [ ] TypeScript compiles on all new components
- [ ] `getHoldingLots()` gateway method exists and is typed
- [ ] Vitest tests: loading, data, empty state for each component

---

## Sub-Plan C — Frontend: Instrument Page Enrichment

**Goal**: Add insider transactions, fundamentals timeseries, and enriched news sentiment on the Instrument page.

### Wave C-1: Insider transactions + fundamentals timeseries

**Goal**: Add insider transactions section to the Quote tab and a historical fundamentals timeseries chart to the Financials tab.
**Depends on**: none (endpoints already exist)
**Estimated effort**: 2h

#### T-C-1-01: `InsiderTransactionsTable` component (NEW)

**Type**: impl
**depends_on**: none
**Target files**:
- `apps/worldview-web/components/instrument/quote/InsiderTransactionsTable.tsx` (NEW)
- `apps/worldview-web/lib/query/keys.ts` — add `qk.insiderTransactions(id)`

**What to build**:
Dense table of recent insider trades. Calls `GET /v1/fundamentals/{id}/insider-transactions`. The EODHD response is a JSONB blob — parse the `InsiderTransactions.transactions` array from the `data` field.

**Expected EODHD shape** (from `data` JSONB in `FundamentalsRecordResponse`):
```
transactions: [{
  date, ownerName, ownerRelationship, transactionCode,
  transactionAmount, transactionPrice, transactionAcquiredDisposed,
  postTransactionAmount, secLink
}]
```

**Visual spec** (22px rows, monospace):
```
INSIDER TRANSACTIONS                             [30D · 90D · 1Y ▾]
DATE         INSIDER              ROLE         TX    SHARES    PRICE
2026-05-10   Tim Cook             CEO          BUY   10,000   $182.40
2026-04-28   Luca Maestri         CFO          SELL   5,000   $178.90
2026-03-15   Arthur D. Levinson   Director     BUY    2,500   $175.20
```

Colour: BUY = text-positive, SELL = text-negative. `secLink` opens SEC filing in new tab.

**Props**: `instrumentId: string`
**Query key**: `qk.insiderTransactions(instrumentId)` → `["fundamentals","insider-transactions",instrumentId]`
**staleTime**: 1h

**Acceptance criteria**:
- [ ] Table renders recent insider transactions from EODHD data
- [ ] BUY/SELL colour coding applied
- [ ] SEC link opens in new tab
- [ ] Empty state: "No recent insider transactions"
- [ ] JSONB parsing handles missing keys gracefully (optional chaining, no crashes)

---

#### T-C-1-02: `FundamentalsTimeseriesChart` component (NEW)

**Type**: impl
**depends_on**: none
**Target files**:
- `apps/worldview-web/components/instrument/financials/FundamentalsTimeseriesChart.tsx` (NEW)
- `apps/worldview-web/lib/query/keys.ts` — add `qk.fundamentalsTimeseries(id, metric)`

**What to build**:
Line chart showing a single fundamental metric over time (e.g. P/E ratio, EV/EBITDA, revenue). Calls `GET /v1/fundamentals/timeseries?instrument_id={id}&section=Valuation&metric=pe_ratio`. User can switch metric via a dropdown chip.

**Available metrics** (from `data` JSONB of fundamentals records):
- Valuation: `pe_ratio`, `pb_ratio`, `ps_ratio`, `ev_ebitda`
- Growth: `revenue_growth_yoy`, `eps_growth_yoy`
- Profitability: `net_margin`, `operating_margin`, `roe`

**Visual spec**: 280×80px line chart (same dimensions as PerformanceChartPanel). Period chips: `1Y · 3Y · 5Y`. Metric selector dropdown. Value label on last point.

**Props**: `instrumentId: string`, `defaultMetric?: string`
**Query key**: `qk.fundamentalsTimeseries(instrumentId, metric)` → `["fundamentals","timeseries",instrumentId,metric]`
**staleTime**: 1h

**Acceptance criteria**:
- [ ] Chart renders historical metric values as a line
- [ ] Metric dropdown switches data without full re-mount
- [ ] Period chips filter x-axis range
- [ ] Empty: "Historical data unavailable"

---

#### T-C-1-03: Add to Financials tab layout

**Type**: impl
**depends_on**: [T-C-1-01, T-C-1-02]
**Target files**:
- `apps/worldview-web/components/instrument/intelligence/IntelligenceTab.tsx` — NO
- `apps/worldview-web/components/instrument/FinancialsTab.tsx` (or wherever the Financials tab renders)
- `apps/worldview-web/components/instrument/QuoteTab.tsx` (or equivalent)

**What to build**:
Wire `InsiderTransactionsTable` into the Quote tab (below analyst sidebar) and `FundamentalsTimeseriesChart` into the Financials tab (in the analyst sidebar or as a new section).

**Acceptance criteria**:
- [ ] InsiderTransactionsTable visible on Quote tab
- [ ] FundamentalsTimeseriesChart visible on Financials tab
- [ ] No layout shift when data loads

---

#### Validation Gate — Wave C-1
- [ ] TypeScript compiles on all new and modified components
- [ ] JSONB parsing tested for null/missing keys (unit test)
- [ ] Visual: no layout shifts, correct empty states

---

### Wave C-2: Enriched news sentiment + impact on Instrument page

**Goal**: Surface sentiment badges, impact scores, and article impact history on the news list.
**Depends on**: Wave A-1 (news now includes sentiment + impact_windows)
**Estimated effort**: 2h

#### T-C-2-01: Sentiment badge + impact score on news rows

**Type**: impl
**depends_on**: [T-A-1-01]
**Target files**:
- `apps/worldview-web/components/instrument/intelligence/NewsColumn.tsx` (or `NewsItem.tsx`)
- `apps/worldview-web/components/ui/sentiment-badge.tsx` (NEW shared primitive)

**What to build**:
Add two visual affordances to each news row:
1. **Sentiment badge**: pill showing `POSITIVE` / `NEGATIVE` / `NEUTRAL` / `MIXED` with colour coding (positive=text-positive, negative=text-negative, neutral=text-muted)
2. **Impact score bar**: inline 40×6px bar showing article's `impact_score` (0–1 scale) if non-null

**`SentimentBadge` component** (in `components/ui/`):
```tsx
<SentimentBadge sentiment="positive" /> // → green pill "POS"
```
Props: `sentiment: "positive" | "negative" | "neutral" | "mixed" | null`

**Acceptance criteria**:
- [ ] Sentiment badge renders on every news row where `sentiment` is non-null
- [ ] LIGHT-tier articles (null sentiment) show no badge (no "null" text)
- [ ] Impact score bar renders when `impact_score` non-null
- [ ] Badge is 9px text, uppercase, pill shape (matches design system)

---

#### T-C-2-02: Article impact history drawer

**Type**: impl
**depends_on**: [T-A-2-01]
**Target files**:
- `apps/worldview-web/components/instrument/intelligence/ArticleImpactDrawer.tsx` (NEW)
- `apps/worldview-web/lib/gateway.ts` — add `getArticleImpactHistory()` method (NEW)
- `apps/worldview-web/lib/query/keys.ts` — add `qk.articleImpactHistory(articleId)`

**What to build**:
Clicking a news row's impact bar opens a small popover/drawer showing the 4-window impact history (t0, t1, t2, t5). Calls `GET /v1/articles/{article_id}/impact-history`.

**Visual spec** (180×120px popover below news row):
```
PRICE IMPACT AFTER ARTICLE
T+0 DAY   T+1 DAY   T+2 DAYS   T+5 DAYS
 +0.8%     +1.4%      +2.3%      +1.9%
 ▓▓▓▓      ▓▓▓▓▓▓    ▓▓▓▓▓▓▓▓   ▓▓▓▓▓▓▓
Data quality: intraday
```

Bars coloured text-positive for positive delta, text-negative for negative.

**Props**: `articleId: string`, `open: boolean`, `onClose: () => void`

**Acceptance criteria**:
- [ ] 4 impact windows displayed as bar chart
- [ ] `data_quality` note shown when `"daily_proxy"` (estimated)
- [ ] Popover closes on click-outside

---

#### Validation Gate — Wave C-2
- [ ] News rows show sentiment badges + impact bars without layout shifts
- [ ] SentimentBadge renders null sentiment as nothing (not "null" text)
- [ ] ArticleImpactDrawer fetches correctly
- [ ] TypeScript strict mode: no implicit any

---

## Sub-Plan D — Frontend: Intelligence Tab Enrichment

**Goal**: Add opportunity paths visualization and entity similarity, plus graph edge validity display.

### Wave D-1: Opportunity paths panel

**Goal**: Add `OpportunityPathsPanel` to the Intelligence tab right rail.
**Depends on**: none (endpoint exists)
**Estimated effort**: 1.5h

#### T-D-1-01: `OpportunityPathsPanel` component (NEW)

**Type**: impl
**depends_on**: none
**Target files**:
- `apps/worldview-web/components/instrument/intelligence/OpportunityPathsPanel.tsx` (NEW)
- `apps/worldview-web/lib/gateway.ts` — `getEntityPaths()` method may not exist; verify (NEW if absent)
- `apps/worldview-web/lib/query/keys.ts` — add `qk.entityPaths(entityId)`

**What to build**:
Panel showing top 5 multi-hop opportunity paths for an entity. Calls `GET /v1/entities/{id}/paths?limit=5&min_score=0.4`.

**Visual spec** (22px rows in right rail):
```
OPPORTUNITY PATHS                                  [5 paths]
NVDA → SUPPLIES → TSMC → MANUFACTURES → ASML   score: 0.84
NVDA → COMPETES WITH → AMD → PARTNER → MSFT    score: 0.71
NVDA → PARENT → Nvidia Corp → LISTED ON → NYSE  score: 0.65
...
[Hover for LLM explanation]
```

Each path: entity nodes in `text-foreground` + relation labels in `text-primary/70` (9px mono uppercase). Score shown right-aligned. Hover tooltip shows `llm_explanation` (if non-null) or "explanation pending".

**Props**: `entityId: string`
**Query key**: `qk.entityPaths(entityId)` → `["entity","paths",entityId]`
**staleTime**: 10min (paths are expensive to compute)

**Acceptance criteria**:
- [ ] Top 5 paths rendered with hop nodes + relation types
- [ ] LLM explanation shown on hover
- [ ] `explanation_pending: true` → tooltip shows "Analysis in progress"
- [ ] Empty: "No opportunity paths found" (min_score threshold)
- [ ] Paths link: clicking an intermediate entity navigates to that instrument page

---

#### T-D-1-02: Wire OpportunityPathsPanel into IntelligenceTab

**Type**: impl
**depends_on**: [T-D-1-01]
**Target files**:
- `apps/worldview-web/components/instrument/intelligence/IntelligenceTab.tsx`

**What to build**:
Add `OpportunityPathsPanel` to the right rail (`ContextPanel` region) below the entity overview section. The `entityId` prop is derived from the `bundle.entity_id` already available in `IntelligenceTab`.

**Acceptance criteria**:
- [ ] Panel visible in right rail below entity overview
- [ ] Only renders when `entityId` is non-null (instrument has KG entity)

---

#### Validation Gate — Wave D-1
- [ ] TypeScript compiles; no unused imports
- [ ] Panel renders correctly for entity with paths and entity without paths
- [ ] Query key defined in keys.ts

---

### Wave D-2: Graph edge validity + enriched tooltips

**Goal**: Surface `valid_from`/`valid_to` and `industry`/`market_cap` from enhanced graph response.
**Depends on**: Wave A-1 (graph now includes validity fields)
**Estimated effort**: 1.5h

#### T-D-2-01: Entity similarity section (NEW)

**Type**: impl
**depends_on**: none
**Target files**:
- `apps/worldview-web/components/instrument/intelligence/EntitySimilarityPanel.tsx` (NEW)
- `apps/worldview-web/lib/gateway.ts` — add `getSimilarEntities()` method (NEW)
- `apps/worldview-web/lib/query/keys.ts` — add `qk.similarEntities(entityId)`

**What to build**:
Small panel showing top 5 similar entities (ANN similarity search). Calls `POST /v1/entities/similar` with `{ entity_id, limit: 5 }`.

**Visual spec** (compact list):
```
SIMILAR ENTITIES
MSFT   Microsoft Corp      TECH  score: 0.94
GOOGL  Alphabet Inc        TECH  score: 0.91
META   Meta Platforms      TECH  score: 0.88
AMZN   Amazon.com          TECH  score: 0.85
TSLA   Tesla Inc           AUTO  score: 0.72
```

Each row links to `/instruments/{instrument_id}`.

**Acceptance criteria**:
- [ ] Top 5 similar entities listed with similarity score
- [ ] Sector chip uses `AssetTypeBadge`-style colour coding
- [ ] Clicking a row navigates to that instrument

---

#### T-D-2-02: Graph edge validity tooltip + node industry colouring

**Type**: impl
**depends_on**: [T-A-1-02, T-A-1-03]
**Target files**:
- `apps/worldview-web/components/instrument/graph/SigmaInternalComponents.tsx`
- `apps/worldview-web/components/instrument/intelligence/InlineSelectionPanel.tsx`

**What to build**:
Two enhancements to the entity graph:
1. **Edge tooltip**: When an edge is selected in `InlineSelectionPanel`, show `valid_from` / `valid_to` if present. Label: "Active since: 2023-Q1" or "Ended: 2025-Q3 2025".
2. **Node colour by industry**: Extend the `nodeReducer` in `SigmaInternalComponents.tsx` to tint nodes by `industry` field (now available from enriched graph response). Use a fixed colour map: TECH=blue, FINANCE=green, ENERGY=orange, HEALTH=red, OTHER=default.

**Node industry colour map** (added to `SigmaInternalComponents.tsx`):
```typescript
const INDUSTRY_COLORS: Record<string, string> = {
  "Technology": "#3B82F6",
  "Financial Services": "#10B981",
  "Energy": "#F97316",
  "Healthcare": "#EF4444",
  "Consumer Cyclical": "#8B5CF6",
};
```

**Acceptance criteria**:
- [ ] Selected edge shows `valid_from`/`valid_to` in InlineSelectionPanel
- [ ] Graph nodes tinted by industry (fallback to default grey when industry null)
- [ ] `confidence_stale: true` edges shown with dashed styling (opacity 0.4)

---

#### Validation Gate — Wave D-2
- [ ] TypeScript compiles on SigmaInternalComponents.tsx and InlineSelectionPanel.tsx
- [ ] Graph renders without console errors when industry is null
- [ ] EdgeDetailCard shows valid_from/valid_to when available

---

## Sub-Plan E — Backend: Tier 3 Application Logic

**Goal**: Build the S8 NL→screener translation layer and S6 sentiment endpoint.

### Wave E-1: NL screener translation

**Goal**: Add an LLM-powered query translation endpoint that converts natural language to screener filters.
**Depends on**: none
**Estimated effort**: 2h

#### T-E-1-01: S8 NL→screener prompt + endpoint (NEW)

**Type**: impl
**depends_on**: none
**blocks**: [T-F-1-01]
**Target files**:
- `services/api-gateway/src/api_gateway/routes/screener.py` (new route in existing file)
- `services/api-gateway/src/api_gateway/schemas/screener.py` (new request/response schemas)

**What to build**:
New S9 endpoint `POST /v1/screener/nl-translate` that:
1. Accepts `{ query: str }` (natural language screener query)
2. Calls S8 via `POST /v1/chat` with a structured prompt
3. S8 response contains a JSON screener filter payload
4. S9 validates the payload against the screener schema
5. Returns the structured filter ready for `POST /v1/fundamentals/screen`

**S8 prompt template** (system prompt for NL translation):
```
You are a financial screener query translator. Convert the user's natural language query into a structured JSON filter for a stock screener.

Available fields and their types:
{screener_fields_schema}  ← injected from GET /v1/fundamentals/screen/fields

Return ONLY valid JSON matching this schema:
{
  "filters": [{"field": str, "operator": "gt"|"lt"|"gte"|"lte"|"eq"|"in", "value": number|string|list}],
  "sort_by": str | null,
  "sort_order": "asc"|"desc",
  "limit": int (max 100)
}

If you cannot translate the query, return {"error": "reason"}.
```

**Request schema**:
```python
class NLScreenerRequest(BaseModel):
    query: str = Field(..., min_length=5, max_length=500)

class NLScreenerResponse(BaseModel):
    original_query: str
    filters: list[dict]
    sort_by: str | None = None
    sort_order: str = "desc"
    limit: int = 25
    explanation: str  # LLM's explanation of what it searched for
```

**Security**: Validate all returned field names against the known screener fields list to prevent injection of arbitrary DB column names.

**Read-only**: YES (no writes)

**Acceptance criteria**:
- [ ] `POST /v1/screener/nl-translate` returns structured filter JSON
- [ ] Field names validated against known screener fields (no SQL injection path)
- [ ] Returns 422 when LLM cannot parse the query
- [ ] `explanation` field summarises what the filter does in plain English

---

#### T-E-1-02: S6 sentiment timeseries internal route

**Type**: impl
**depends_on**: none
**blocks**: [T-A-2-02]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/api/routers/analytics.py` (NEW router file)
- `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/get_entity_sentiment_timeseries.py` (NEW)
- `services/nlp-pipeline/src/nlp_pipeline/application/ports/repositories.py` (extend with new port method)

**What to build**:
New internal S6 endpoint `GET /api/v1/entities/{entity_id}/sentiment-timeseries` that runs the aggregation SQL from T-A-2-02, using the `ReadOnlyUnitOfWork`.

**Port interface** (add to existing `repositories.py`):
```python
class IDocumentRepository(ABC):
    ...
    @abstractmethod
    async def get_entity_sentiment_timeseries(
        self,
        entity_id: UUID,
        days: int,
        session: AsyncSession,
    ) -> list[SentimentDataPoint]: ...
```

**Use case**: `GetEntitySentimentTimeseriesUseCase` — read-only, takes `entity_id` + `days`, returns `list[SentimentDataPoint]`.

**Read-only**: YES → `ReadOnlyUnitOfWork` + `ReadUoWDep` (R27)

**Acceptance criteria**:
- [ ] `GET /api/v1/entities/{id}/sentiment-timeseries?days=90` returns daily points
- [ ] Uses ReadOnlyUnitOfWork (read replica)
- [ ] Returns empty list when no articles (not 404)
- [ ] Uses `structlog` for logging (R12)
- [ ] ABC port defined (R25)

---

#### Validation Gate — Wave E-1
- [ ] ruff + mypy pass on new S6 and S9 files
- [ ] R25: ABC port defined for new repository method
- [ ] R27: ReadOnlyUnitOfWork used in new S6 use case
- [ ] NL translation validates field names against allowlist (security check)
- [ ] Unit tests: ≥ 5 (3 for NL translate, 2 for sentiment timeseries)

---

### Wave E-2: Portfolio attribution + yield curve data

**Goal**: Wire the S6 sentiment timeseries into the S9 proxy endpoint, and add sector attribution + yield curve endpoints.
**Depends on**: Wave E-1, Wave A-2
**Estimated effort**: 1.5h

#### T-E-2-01: S6 sentiment timeseries S9 proxy wiring

**Type**: impl
**depends_on**: [T-E-1-02, T-A-2-02]
**Target files**:
- `services/api-gateway/src/api_gateway/routes/intelligence.py`

**What to build**:
Wire the S9 `GET /v1/entities/{id}/sentiment-timeseries` endpoint (created in T-A-2-02 as a stub) to call the new S6 internal route (T-E-1-02).

**Acceptance criteria**:
- [ ] `GET /v1/entities/{id}/sentiment-timeseries` proxies to S6 and returns correctly typed response
- [ ] 404 from S6 propagates as 404 to frontend

---

#### T-E-2-02: Yield curve data source investigation + wiring

**Type**: impl
**depends_on**: [T-A-2-04]
**Target files**:
- `services/api-gateway/src/api_gateway/routes/market.py`
- `services/market-data/src/market_data/api/routers/` — check if yield data accessible

**What to build**:
Complete the `GET /v1/market/yield-curve` endpoint. Strategy: use `POST /v1/quotes/batch` for these instruments if available: `{SHY: "2Y", IEI: "5Y", IEF: "7Y", TLT: "30Y"}` — if OHLCV history exists for these ETFs, use their yield-equivalent. Alternatively, check S3's `TemporalEvent` table for `event_type=macro_indicator` with `indicator_name` matching Treasury yield names from EODHD.

**Graceful degradation**: If yield data for a maturity is unavailable, return that point with `yield_pct: null` and `change_1d: null`. Always return the 4-point structure.

**Acceptance criteria**:
- [ ] Endpoint returns 200 even when some maturities are unavailable (graceful degradation)
- [ ] `spread_2s10s` computed when both 2Y and 10Y are available
- [ ] `spread_2s10s_inverted` set correctly

---

#### Validation Gate — Wave E-2
- [ ] All new S9 endpoints return 200 against local dev stack
- [ ] Sentiment timeseries wired end-to-end (S6 → S9 → frontend ready)
- [ ] Yield curve returns gracefully when data unavailable

---

## Sub-Plan F — Frontend: Tier 3 Advanced Features

**Goal**: Build TA overlay suite, NL screener UI, sentiment trend overlay, and yield curve panel.

### Wave F-1: TA overlay suite on price chart

**Goal**: Add user-selectable technical analysis indicators as overlays on the OHLCV chart.
**Depends on**: none (client-side computation only, no new backend endpoints)
**Estimated effort**: 2.5h

#### T-F-1-01: TA computation utilities + indicator overlays

**Type**: impl
**depends_on**: none
**Target files**:
- `apps/worldview-web/lib/ta/indicators.ts` (NEW — TA computation library)
- `apps/worldview-web/components/instrument/quote/TAOverlayPanel.tsx` (NEW)
- `apps/worldview-web/components/instrument/quote/OHLCVChart.tsx` — extend to accept overlay data

**What to build**:
Client-side TA computation from the OHLCV bars already fetched. No new API calls.

**`lib/ta/indicators.ts`** — compute from `OHLCVBar[]`:
```typescript
// EMA(n): exponential moving average
export function ema(bars: OHLCVBar[], period: number): number[]

// SMA(n): simple moving average
export function sma(bars: OHLCVBar[], period: number): number[]

// RSI(14): relative strength index
export function rsi(bars: OHLCVBar[], period = 14): number[]

// MACD(12,26,9): returns {macd, signal, histogram}
export function macd(bars: OHLCVBar[]): MACDResult[]

// Bollinger Bands(20,2): returns {upper, middle, lower}
export function bollingerBands(bars: OHLCVBar[], period = 20, std = 2): BBResult[]

// VWAP (daily reset): volume-weighted average price
// Note: OHLCV bars have volume; no intraday VWAP (daily VWAP only)
export function vwap(bars: OHLCVBar[]): number[]
```

**`TAOverlayPanel`** — chip strip for indicator selection:
```
OVERLAYS: [EMA 20] [EMA 50] [SMA 200] [MACD] [BOLL] [RSI] [VWAP]
```
Selected chips are highlighted. Each active indicator passes its computed series to OHLCVChart as an overlay prop.

**OHLCVChart extension**: Accept `overlays?: OverlaySeries[]` prop where each series has `{label, color, data: number[], type: "line"|"band"}`.

**Acceptance criteria**:
- [ ] EMA, SMA, RSI, MACD, Bollinger Bands, VWAP all compute correctly
- [ ] Indicators render as chart overlays without blocking main price line
- [ ] RSI rendered in a separate sub-chart (0–100 scale)
- [ ] MACD histogram rendered below RSI
- [ ] Selecting/deselecting indicators re-renders chart immediately (no flicker)
- [ ] TA computations are memoized (not recomputed on every render)
- [ ] Unit tests: `ema([...], 5)` produces known values against reference calculation

---

#### T-F-1-02: TA indicator wire-up in Quote tab

**Type**: impl
**depends_on**: [T-F-1-01]
**Target files**:
- `apps/worldview-web/components/instrument/quote/QuoteTab.tsx` (or equivalent)

**What to build**:
Wire `TAOverlayPanel` and overlay props into the Quote tab layout. Selected indicators are stored in local React state (not URL/localStorage — session-only preference). OHLCVChart receives the computed overlay data.

**Acceptance criteria**:
- [ ] TAOverlayPanel renders below or above the chart
- [ ] Selected indicators persist during the session (useState, not URL)
- [ ] Chart re-renders correctly when period (1D/5D/1M/3M/1Y) changes

---

#### Validation Gate — Wave F-1
- [ ] All 6 TA functions have unit tests with known reference values
- [ ] OHLCVChart TypeScript: `overlays` prop is optional (no breaking change)
- [ ] No perf regression: chart renders < 100ms with 5 overlays active

---

### Wave F-2: NL screener + sentiment trend overlay

**Goal**: Add natural language screener UI and sentiment timeseries chart overlay on instrument page.
**Depends on**: Wave E-1 (NL translate endpoint), Wave E-2 (sentiment timeseries endpoint)
**Estimated effort**: 2h

#### T-F-2-01: NL screener UI

**Type**: impl
**depends_on**: [T-E-1-01]
**Target files**:
- `apps/worldview-web/components/screener/NLScreenerInput.tsx` (NEW)
- `apps/worldview-web/lib/gateway.ts` — add `translateNLScreenerQuery()` method (NEW)
- Existing screener page — integrate NLScreenerInput

**What to build**:
A search-bar style input at the top of the screener page with placeholder text: `"e.g. profitable tech companies below 15x forward P/E with insider buying"`. On submit, calls `POST /v1/screener/nl-translate`, receives structured filters, and populates the existing screener filter UI.

**Visual spec**:
```
┌─────────────────────────────────────────────────────────────────┐
│ 🔍 Describe what you're looking for...                     [→]  │
└─────────────────────────────────────────────────────────────────┘
Interpreted as: P/E < 15 AND revenue_growth > 0 AND insider_buy_90d > 0
[TECH ×] [P/E < 15 ×] [REVENUE GROWTH > 0% ×] [INSIDER BUY ×]   Apply
```

The explanation line ("Interpreted as: ...") comes from the `explanation` field in the NL translate response.

**Acceptance criteria**:
- [ ] NL input submits on Enter or click of arrow button
- [ ] Loading state shown during translation (skeleton)
- [ ] Translation result populates screener filters visually
- [ ] Error state when LLM cannot parse query ("Could not translate — try being more specific")
- [ ] User can still edit filters after NL auto-population

---

#### T-F-2-02: Sentiment trend overlay on price chart

**Type**: impl
**depends_on**: [T-E-2-01]
**Target files**:
- `apps/worldview-web/components/instrument/quote/SentimentOverlay.tsx` (NEW)
- `apps/worldview-web/lib/query/keys.ts` — add `qk.entitySentimentTimeseries(entityId, days)`
- `apps/worldview-web/components/instrument/quote/OHLCVChart.tsx` — add sentiment overlay support

**What to build**:
Optional chart overlay that shows daily sentiment score (positive_ratio − negative_ratio) as a secondary line, coloured green above 0 and red below. Toggled by a chip in the TAOverlayPanel.

Add `[SENTI]` chip to `TAOverlayPanel`. When active:
1. Fetch `GET /v1/entities/{entityId}/sentiment-timeseries?days=365`
2. Compute `net_sentiment = positive_ratio - negative_ratio` per day
3. Render as a secondary line on the price chart (right Y-axis, −1 to +1 scale)

**Acceptance criteria**:
- [ ] Sentiment overlay renders only when entity has an entityId (stocks, not indices)
- [ ] Line uses right Y-axis (−1 to +1), not left (price) axis
- [ ] Days aligns with current chart period selection
- [ ] Empty points are interpolated (not rendered as gaps unless >7-day gap)

---

#### Validation Gate — Wave F-2
- [ ] NL screener roundtrip: input → translate → filters populated
- [ ] Sentiment overlay renders without obscuring price data
- [ ] Both components handle loading/error/empty states

---

### Wave F-3: Portfolio attribution view + yield curve strip

**Goal**: Add portfolio sector attribution chart to Portfolio page and yield curve to dashboard Market Strip.
**Depends on**: Wave E-2 (sector attribution + yield curve endpoints)
**Estimated effort**: 2h

#### T-F-3-01: Portfolio sector attribution chart integration

**Type**: impl
**depends_on**: [T-A-2-03, T-B-1-03]
**Target files**:
- `apps/worldview-web/components/portfolio/SectorAttributionWidget.tsx` — wire into Portfolio Overview page
- `apps/worldview-web/app/(app)/portfolio/page.tsx` (or the portfolio overview layout)

**What to build**:
Wire the `SectorAttributionWidget` (built in T-B-1-03) into the Portfolio Overview page layout. Add it as a new section below the holdings table. Include a `donut chart` variant that shows sector weights visually.

**Donut chart**: Use the same SVG approach as the existing sparklines (no external chart library). 6 sectors max; remainder as "OTHER".

**Acceptance criteria**:
- [ ] Donut chart renders with sector wedges coloured by sector
- [ ] Horizontal bar list below donut shows all sectors with day P&L
- [ ] Total weights sum to ~100%

---

#### T-F-3-02: Yield curve strip on dashboard Market Strip

**Type**: impl
**depends_on**: [T-A-2-04, T-E-2-02]
**Target files**:
- `apps/worldview-web/components/dashboard/MarketStrip.tsx` (to be created in W4)
- `apps/worldview-web/lib/gateway.ts` — add `getYieldCurve()` method (NEW)
- `apps/worldview-web/lib/query/keys.ts` — add `qk.yieldCurve()`

**What to build**:
Add a 9th "cell" to the Market Strip dashboard widget showing the yield curve state: 2Y yield, 10Y yield, and 2s10s spread. The spread inverted state shows in text-negative.

**Visual spec** (fits in one Market Strip cell):
```
YIELDS (2s10s: -14bps ▼)
2Y: 4.71%  10Y: 4.57%
```

OR expand to a mini yield curve chart (4 maturities as a small SVG line).

**Acceptance criteria**:
- [ ] Yield cell renders 2Y + 10Y yields
- [ ] 2s10s spread shown in text-negative when inverted
- [ ] Graceful degradation: shows "—" when yield data unavailable

---

#### T-F-3-03: Dashboard W4 integration — add risk/concentration to Top of Portfolio

**Type**: impl
**depends_on**: [T-B-1-01, T-B-1-02, T-B-1-03]
**Target files**:
- `apps/worldview-web/components/portfolio/TopOfPortfolio.tsx` (W4 component)
- `apps/worldview-web/app/(app)/dashboard/page.tsx`

**What to build**:
Wire `RiskMetricsPanel`, `ConcentrationWidget`, and `SectorAttributionWidget` into the W4 Dashboard layout. Add a second row below R3 (Top of Portfolio) or as tabs within the R3 cell:

```
[KPIs] [POSITIONS] [RISK METRICS] [CONCENTRATION] [SECTORS]  ← tab strip
```

Tab strip within the TopOfPortfolio mega-cell lets users switch the right side between positions table, risk metrics, concentration, and sector attribution.

**Acceptance criteria**:
- [ ] Tab strip switches right-panel content without layout shift
- [ ] Default tab: POSITIONS (existing behaviour)
- [ ] Risk/concentration/sectors tabs load data on first tab activation (lazy fetch)

---

#### Validation Gate — Wave F-3
- [ ] Portfolio page renders with sector attribution chart
- [ ] Dashboard Market Strip shows yield curve cell
- [ ] TopOfPortfolio tab strip works for all 4 tabs
- [ ] All Vitest tests pass; no TypeScript errors

---

## Cross-Cutting Concerns

### Contract changes
- S9 `NewsTopResponse` gains 3 new fields (`sentiment`, `impact_windows`, `impact_score`) — non-breaking (new optional fields with defaults)
- S9 graph edge response gains 3 new fields (`valid_from`, `valid_to`, `confidence_stale`) — non-breaking
- S9 graph node response gains 2 new fields (`industry`, `market_cap`) — non-breaking
- 5 new S9 endpoints — additive only, no existing endpoint modified except schema extension

### No DB migrations
All changes are S9 Pydantic schema additions and frontend UI. Zero Alembic migrations needed.

### New environment variables
None required — all new endpoints use existing S6/S7/S1/S3 HTTP connections already configured.

### Documentation to update after implementation
- `docs/services/api-gateway.md` — add 5 new endpoints
- `services/api-gateway/.claude-context.md` — add new endpoints + new S6 route
- `services/nlp-pipeline/.claude-context.md` — add new `analytics.py` router

---

## Risk Assessment

| Risk | Severity | Mitigation |
|---|---|---|
| EODHD insider transaction JSONB structure may vary by instrument | MEDIUM | Use optional chaining throughout; show empty state on missing keys |
| S8 LLM NL→screener may produce invalid filter fields | HIGH | Validate all returned field names against screener fields allowlist; return 422 on invalid |
| Yield curve data may not be available in EODHD macro events | MEDIUM | Graceful degradation to "—" cells; check S3 temporal events first |
| TA computations may be slow on large datasets (1Y daily = 250 bars) | LOW | Memoize via `useMemo`; 250 bars is trivial for client-side JS |
| S6 sentiment timeseries aggregation may be slow without index | MEDIUM | Add composite index on `(resolved_entity_id, published_at)` if query is slow |

---

## Execution Order Recommendation

1. **Wave A-1** (S9 schema extensions — 1.5h) → unblocks C-2 and D-2
2. **Wave B-1** (risk + concentration UI — 2h) → independent, high-value
3. **Wave E-1** (NL screener + S6 sentiment — 2h) → unblocks F-2
4. **Wave A-2** (new S9 endpoints — 2h) → completes backend
5. **Wave C-1** (insider + timeseries — 2h) → independent instrument page
6. **Wave B-2** (lots + watchlist — 2h) → independent
7. **Wave D-1** (opportunity paths — 1.5h) → independent
8. **Wave E-2** (wiring — 1.5h) → depends on E-1 + A-2
9. **Wave C-2** (sentiment news — 2h) → depends on A-1
10. **Wave D-2** (graph enrichment — 1.5h) → depends on A-1
11. **Wave F-1** (TA overlays — 2.5h) → independent
12. **Wave F-2** (NL screener + sentiment chart — 2h) → depends on E-1+E-2
13. **Wave F-3** (attribution + yield curve — 2h) → depends on A-2+E-2+B-1

**Critical path**: A-1 → C-2 → D-2 (fastest path to visible intelligence enrichment, ~5h)
**Highest ROI first**: B-1 (risk metrics — zero backend) + F-1 (TA overlays — zero backend) can run immediately in parallel.
