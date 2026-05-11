# PLAN-0043 — Dashboard UX Refinement

**Created**: 2026-04-27
**Revised**: 2026-04-27 (revise-prd: wire 1D/1W/1M buttons; add AI Signals widget; add S3 period endpoints)
**Status**: draft
**PRD**: User-reported dashboard issues (2026-04-27 session)
**Tracking**: `docs/plans/TRACKING.md`

---

## Problem Statement

The dashboard has 6 classes of issues discovered through use, plus one new component opportunity:

1. **AI Brief layout** — metadata lines (stale indicator, generated timestamp, read-more) dominate the brief row, leaving little space for text. Font too large. Generated info should be at the top.
2. **Component borders** — `gap-px` hairline approach is too subtle; panels appear borderless on many displays.
3. **Period buttons (1D/1W/1M)** — present in SectorHeatmap, TopMovers, and PortfolioSummary widgets but not wired to any API call. Must be wired to real aggregated data (not removed).
4. **Prediction Markets** — Y/N probabilities may be 0 if Gamma API changed; clicking a row opens `about:blank`; no economics filter.
5. **Portfolio 5D/5W buttons** — not wired; remove them (unlike 1D/1W/1M which must be kept and wired).
6. **Row 2 size** — MarketSnapshot + SectorHeatmap take too much vertical space.
7. **[NEW] AI Signals widget** — `AiSignalsResponse` (label/score/ticker) is already defined in the gateway and S9 exposes `GET /v1/signals/ai`. Not displayed anywhere on the dashboard despite Row 3 having available space in a restructured 4+4+2+2 layout.

---

## Codebase State (verified against source)

| Component | File | Current State | Change Required |
|-----------|------|--------------|-----------------|
| MorningBriefCard | `components/dashboard/MorningBriefCard.tsx` | Stale → text → read-more → timestamp (bottom) | Compact header row (stale + timestamp top), text dominant, font text-[10px] |
| Dashboard page grid | `app/(app)/dashboard/page.tsx` | `gap-px bg-background` only | Add `border border-border/40` to each cell; restructure Row 3 to 4+4+2+2 |
| SectorHeatmapWidget period | `components/dashboard/SectorHeatmapWidget.tsx` | Local `period` state not passed to API | Wire to new S9 `GET /v1/market/heatmap?period=1W` endpoint |
| PreMarketMoversWidget period | `components/dashboard/PreMarketMoversWidget.tsx` | Local `period` state not passed to API | Wire to new S9 `GET /v1/market/top-movers?period=1W` endpoint |
| PortfolioSummary 5D/5W | `components/dashboard/PortfolioSummary.tsx` | `TimeRange = "5D" \| "5W"` + `1D/1W/1M`, local state | Remove 5D/5W only; remove 1D/1W/1M from portfolio (portfolio doesn't aggregate by period the same way) |
| PredictionMarketsWidget URL | `components/dashboard/PredictionMarketsWidget.tsx` | `market.url ?? "https://polymarket.com/"` — always empty | Wire market_slug from gateway; search URL fallback |
| gateway.ts prediction URL | `lib/gateway.ts:1271` | `url: ""` hardcoded | Read `m.market_slug` from S3 response; construct URL |
| `PredictionMarketFetchResult` | `content-ingestion/.../domain/entities.py:265` | No `market_slug` field | Add `market_slug: str = ""`; populate from `raw.get("slug")` |
| `PredictionMarketModel` | `market-data/.../db/models/prediction_markets.py:21` | No `market_slug` column | Add nullable column + migration 007 |
| `PredictionMarketSummaryResponse` | `market-data/.../api/schemas/prediction_markets.py:18` | No `market_slug` field | Add `market_slug: str \| None = None` |
| Avro `market.prediction.v1.avsc` | `infra/kafka/schemas/` | No `market_slug` field | Add optional field with `"default": null` |
| S9 `get_market_heatmap` | `api-gateway/.../clients.py:386` | No period param; always uses `daily_return` | Add `period: str = "1D"` param; for 1W/1M call new S3 sector-returns endpoint |
| S9 `get_top_movers` | `api-gateway/.../clients.py:437` | No period param; always uses `daily_return` | Add `period: str = "1D"` param; for 1W/1M call new S3 period-movers endpoint |
| S3 sector heatmap | `market-data/.../routers/` | No period-aware endpoint | New `GET /api/v1/market/sector-returns?period=1W&sector=<name>` endpoint |
| S3 period movers | `market-data/.../routers/` | No period-aware movers endpoint | New `GET /api/v1/market/period-movers?period=1W&type=gainers&limit=N` endpoint |
| AI Signals widget | (does not exist) | Not on dashboard | New `AiSignalsWidget` component; restructure Row 3 to 4+4+2+2 |
| OHLCV bars | `market-data/.../models/ohlcv.py` | `timeframe` column (String 5), has 1d/1w/1M bars, `is_derived`, `is_partial` flags | No change — query existing bars by timeframe |

---

## Sub-Plans

### Sub-plan A — Frontend (apps/worldview-web)
Waves A-1, A-2, A-3, A-4, A-5

### Sub-plan B — Backend: Polymarket URL + Period Aggregation
Waves B-1, B-2, B-3, B-4

**Dependency graph**:
```
A-1 (brief layout)      ──► independent
A-2 (borders+size)      ──► independent
A-5 (AI Signals widget) ──► independent (gateway method already exists)
B-1 (S4 Polymarket slug)──► B-2 (S3+S9 URL passthrough) ──► A-4 (frontend URL)
B-3 (S3 period returns) ──► B-4 (S9 period wiring) ──► A-3 (frontend wire 1D/1W/1M)
PortfolioSummary 5D/5W removal is part of A-3, independent of B-3/B-4
```

---

## Sub-plan A — Frontend Waves

---

### Wave A-1: MorningBriefCard Compact Redesign

**Goal**: Reorganize brief layout — metadata compact at top, text dominant, font smaller.
**Depends on**: none
**Estimated effort**: 30 min
**Architecture layer**: UI component

#### Pre-read
- `apps/worldview-web/components/dashboard/MorningBriefCard.tsx`

#### Tasks

##### T-A-1-01: Reorganize MorningBriefCard layout

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/dashboard/MorningBriefCard.tsx`

**What to build**:
The current structure:
```
[stale indicator row — mb-2]
[text area / skeleton / error]
[read more / show less toggle button]
[Generated timestamp — bottom]
```

New structure:
```
[header row h-5 shrink-0: "Generated YYYY-MM-DD HH:MM UTC" (left) | stale badge + refresh icon (right)]
[flex-1 overflow-auto text area: ReactMarkdown or plain preview]
[inline "… more" link at end of preview text (not a separate row)]
```

**Specific changes**:
- Move `generatedAt` display to top: `<span className="font-mono text-[9px] text-muted-foreground/60">Generated {ts} UTC</span>`
- Stale badge: right side of header, `text-[9px] text-amber-400`, only when `isStale`
- Refresh icon: in header row right side (same `<RefreshCw>` but `h-3 w-3`, no extra row)
- Remove the standalone `<p className="mt-2 font-mono text-[10px]...">Generated...</p>` at bottom
- Remove the `mb-2 flex items-center justify-between` stale indicator block
- Remove `<button>Read more / Show less</button>` as a standalone row; inline "…more" as a span after the preview text + a small expand link below
- All text: change to `text-[10px]` (from mix of `text-xs` [12px] and `text-sm` [14px])
- ReactMarkdown element overrides: `[&_h1]:text-[11px]`, `[&_h2]:text-[10px]`, `[&_h2]:mt-1`, `[&_h3]:text-[10px]`, `[&_p]:mt-0.5`, `[&_ul]:mt-0.5`
- Wrap entire component in `flex flex-col h-full` so text area fills Row 1

**Loading state**: show 5-line skeleton inside a `flex-1` div (existing skeleton, just re-wrapped)

**Error state**: compact single-line error in `flex-1` area (same logic, just no second row for stale indicator)

**Acceptance criteria**:
- [ ] Top row: "Generated …" timestamp + optional stale badge + refresh icon — all on one h-5 line
- [ ] No "Generated" line at bottom
- [ ] All text is text-[10px] or smaller (including headings, lists, paragraphs)
- [ ] Component is `flex flex-col h-full`; text area is `flex-1 overflow-auto`
- [ ] `pnpm tsc --noEmit` passes

---

### Wave A-2: Dashboard Grid Borders + Row 2 Size Reduction

**Goal**: Visible panel borders; Row 2 constrained to 130px.
**Depends on**: none
**Estimated effort**: 20 min
**Architecture layer**: UI layout

#### Pre-read
- `apps/worldview-web/app/(app)/dashboard/page.tsx`

#### Tasks

##### T-A-2-01: Add explicit border to each grid cell

**Type**: impl
**depends_on**: none
**Target files**: `apps/worldview-web/app/(app)/dashboard/page.tsx`

**What to build**:
Add `border border-border/40` to every widget wrapper div in Rows 2, 3, 4. Row 1 already has `border-primary/60` — keep that.

Also add `grid-rows-[auto_130px_auto_auto]` via inline style to cap Row 2 at 130px while keeping other rows auto-sized:

```tsx
<div
  className="grid grid-cols-12 gap-px overflow-auto bg-background"
  style={{ height: "calc(100vh - 36px)", gridTemplateRows: "auto 130px auto auto" }}
>
```

Each inner wrapper (currently `className="col-span-4 h-full"`) becomes `className="col-span-4 h-full border border-border/40"`.

**Note**: Row 3 is restructured in Wave A-5. Only add borders here; do not change col-span values yet.

**Acceptance criteria**:
- [ ] All 9 widget cells (Rows 2/3/4) have `border border-border/40`
- [ ] Row 1 retains `border-primary/60`
- [ ] Row 2 height is ~130px (MarketSnapshot and SectorHeatmap visible and not clipped)

##### T-A-2-02: Tighten MarketSnapshot + SectorHeatmap internal padding

**Type**: impl
**depends_on**: T-A-2-01
**Target files**:
- `apps/worldview-web/components/dashboard/MarketSnapshotWidget.tsx`
- `apps/worldview-web/components/dashboard/SectorHeatmapWidget.tsx`

**What to build**:
In both files: reduce section header from `h-6` to `h-5`. Reduce data row padding from `py-1` to `py-0.5`. This allows more rows to be visible within the 130px row height.

**Acceptance criteria**:
- [ ] Both widgets show section header + data rows at 130px without overflow
- [ ] No visual clipping of content

---

### Wave A-3: Period Buttons Wired (1D/1W/1M) + Portfolio 5D/5W Removal

**Goal**: Wire 1D/1W/1M buttons to real aggregated data for SectorHeatmap and TopMovers; remove non-functional 5D/5W from Portfolio.
**Depends on**: Wave B-4 (S9 period endpoints must exist before frontend can call them)
**Estimated effort**: 40 min
**Architecture layer**: UI component + gateway client

#### Pre-read
- `apps/worldview-web/components/dashboard/SectorHeatmapWidget.tsx`
- `apps/worldview-web/components/dashboard/PreMarketMoversWidget.tsx`
- `apps/worldview-web/components/dashboard/PortfolioSummary.tsx`
- `apps/worldview-web/lib/gateway.ts` (getMarketHeatmap, getTopMovers)

#### Tasks

##### T-A-3-01: Wire 1D/1W/1M to SectorHeatmapWidget

**Type**: impl
**depends_on**: none (can be written before B-4 merges; just won't work end-to-end until B-4)
**Target files**:
- `apps/worldview-web/components/dashboard/SectorHeatmapWidget.tsx`
- `apps/worldview-web/lib/gateway.ts`

**What to build**:

In `gateway.ts`, update `getMarketHeatmap()` to accept a `period` param:
```typescript
getMarketHeatmap(period: "1D" | "1W" | "1M" = "1D"): Promise<MarketHeatmapResponse> {
  return apiFetch<MarketHeatmapResponse>(
    `/v1/market/heatmap?period=${period}`,
    { token: t },
  );
}
```

In `SectorHeatmapWidget.tsx`:
- Pass `period` to the query function: `queryFn: () => createGateway(accessToken).getMarketHeatmap(period)`
- Include `period` in the query key: `queryKey: ["sector-heatmap-widget", period]` so TanStack Query refetches on period change
- Keep existing `period` state and button group — they are now functional

**Note**: For 1D, S9 continues to use the existing `daily_return` screener approach. For 1W/1M, S9 calls the new S3 endpoints added in Wave B-3. The frontend API shape (`MarketHeatmapResponse`) is identical across all three periods — just the values differ.

**Acceptance criteria**:
- [ ] Clicking 1W or 1M in SectorHeatmap triggers a new API call (visible in browser network tab)
- [ ] `queryKey` includes `period` so cache is per-period
- [ ] `pnpm tsc --noEmit` passes

##### T-A-3-02: Wire 1D/1W/1M to PreMarketMoversWidget

**Type**: impl
**depends_on**: none
**Target files**:
- `apps/worldview-web/components/dashboard/PreMarketMoversWidget.tsx`
- `apps/worldview-web/lib/gateway.ts`

**What to build**:

In `gateway.ts`, update `getTopMovers()` to accept a `period` param:
```typescript
getTopMovers(
  type: "gainers" | "losers" = "gainers",
  limit: number = 10,
  period: "1D" | "1W" | "1M" = "1D",
): Promise<TopMoversResponse> {
  return apiFetch<TopMoversResponse>(
    `/v1/market/top-movers?type=${type}&limit=${limit}&period=${period}`,
    { token: t },
  );
}
```

In `PreMarketMoversWidget.tsx`:
- Pass `period` to both gainers and losers queries
- Include `period` in both query keys
- Keep the existing period state and button group (now functional)

**Acceptance criteria**:
- [ ] 1D/1W/1M buttons on TopMovers widget trigger new API calls
- [ ] `queryKey` includes `period`
- [ ] `pnpm tsc --noEmit` passes

##### T-A-3-03: Remove 5D/5W from PortfolioSummary

**Type**: impl
**depends_on**: none
**Target files**: `apps/worldview-web/components/dashboard/PortfolioSummary.tsx`

**What to build**:
Remove `TimeRange = "5D" | "5W"` type, `range` state, and the 5D/5W button group. The portfolio 1D/1W/1M buttons are also removed (portfolio P&L is a snapshot based on current prices vs cost basis — not a period-aggregated view). Portfolio header becomes just the section label "PORTFOLIO" with the name sub-label.

**Acceptance criteria**:
- [ ] No 5D/5W buttons
- [ ] No 1D/1W/1M buttons in portfolio header
- [ ] Total value, P&L, and holdings still render correctly
- [ ] `pnpm tsc --noEmit` passes

---

### Wave A-4: Prediction Markets Frontend Fixes

**Goal**: Fix click-to-Polymarket link; add economics filter; wire market_slug URL.
**Depends on**: Wave B-2 (S9 must return `market_slug`)
**Estimated effort**: 30 min
**Architecture layer**: UI component + gateway client

#### Pre-read
- `apps/worldview-web/components/dashboard/PredictionMarketsWidget.tsx`
- `apps/worldview-web/lib/gateway.ts` (lines 1210–1280)
- `apps/worldview-web/types/api.ts` (PredictionMarket type)

#### Tasks

##### T-A-4-01: Add market_slug to frontend types and gateway transform

**Type**: impl
**depends_on**: none
**Target files**: `apps/worldview-web/types/api.ts`, `apps/worldview-web/lib/gateway.ts`

**What to build**:

In `types/api.ts`, add `market_slug: string | null` to `PredictionMarket` interface.

In `gateway.ts` transform (line ~1256), read `m.market_slug` and construct URL:
```typescript
market_slug: m.market_slug ?? null,
url: m.market_slug
  ? `https://polymarket.com/event/${m.market_slug}`
  : "",  // empty until B-2 populates slug in S3
```

**Acceptance criteria**:
- [ ] `PredictionMarket` interface has `market_slug: string | null`
- [ ] Gateway reads `m.market_slug` from S3 response

##### T-A-4-02: Add economics filter + fix URL click in PredictionMarketsWidget

**Type**: impl
**depends_on**: none
**Target files**: `apps/worldview-web/components/dashboard/PredictionMarketsWidget.tsx`

**What to build**:

**Economics keywords** (client-side filter):
```typescript
const ECON_KEYWORDS = [
  "gdp", "inflation", "fed", "federal reserve", "interest rate", "cpi",
  "unemployment", "recession", "rate cut", "rate hike", "fomc", "payroll",
  "pce", "treasury", "yield", "deficit", "tariff", "trade war", "economic",
  "fiscal", "monetary", "pmi", "ism"
];
const isEconomics = (title: string) =>
  ECON_KEYWORDS.some((kw) => title.toLowerCase().includes(kw));
```

Add `useState<boolean>(false)` for `econOnly`. Add "ECON" toggle button in header (right side, same style as period selector). Filter `topMarkets` when `econOnly`.

**URL click fix**: fallback to Polymarket search URL:
```typescript
const dest = market.url
  || `https://polymarket.com/markets?q=${encodeURIComponent(market.title)}`;
window.open(dest, "_blank", "noopener,noreferrer");
```

**Acceptance criteria**:
- [ ] "ECON" toggle in header filters markets by keyword
- [ ] Clicking any market row opens a real URL (not `about:blank`)

---

### Wave A-5: AI Signals Widget + Row 3 Restructure

**Goal**: Add an `AiSignalsWidget` component using the existing `GET /v1/signals/ai` endpoint; restructure Row 3 from 4+5+3 to 4+4+2+2.
**Depends on**: none (gateway method `getAiSignals()` already exists)
**Estimated effort**: 45 min
**Architecture layer**: UI component + layout

#### Pre-read
- `apps/worldview-web/types/api.ts` (lines 740–756: `AiSignal`, `AiSignalsResponse`)
- `apps/worldview-web/lib/gateway.ts` (line 1400: `getAiSignals`)
- `apps/worldview-web/components/dashboard/PredictionMarketsWidget.tsx` (styling reference)
- `apps/worldview-web/app/(app)/dashboard/page.tsx` (Row 3 grid)

#### Tasks

##### T-A-5-01: Create AiSignalsWidget component

**Type**: impl
**depends_on**: none
**Target files**: `apps/worldview-web/components/dashboard/AiSignalsWidget.tsx` (new)

**What to build**:
New compact dashboard widget showing top 6 AI price-impact signals.

**`AiSignal` type** (already in `types/api.ts`):
- `signal_id: string`
- `entity_id: string`
- `ticker: string | null`
- `label: "POSITIVE" | "NEGATIVE" | "NEUTRAL"`
- `score: number` (0.0–1.0)
- `article_title: string | null`
- `created_at: string`

**Component structure** (follows §0 Terminal Quality standard):
```tsx
<div className="flex h-full flex-col border border-border/40 bg-background">
  {/* Header h-5 */}
  <div className="flex h-5 shrink-0 items-center border-b border-border px-2">
    <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">AI SIGNALS</span>
  </div>
  {/* Rows: one per signal, h-[22px] */}
  <div className="flex-1 divide-y divide-border/30 overflow-auto">
    {signals.map(signal => (
      <div key={signal.signal_id} className="flex h-[22px] items-center gap-1.5 px-2">
        {/* Ticker or entity_id prefix */}
        <span className="w-[36px] shrink-0 font-mono text-[10px] font-medium tabular-nums text-foreground truncate">
          {signal.ticker ?? signal.entity_id.slice(0, 4)}
        </span>
        {/* Score bar — proportional fill */}
        <div className="relative h-[4px] flex-1 rounded-none bg-muted/30">
          <div
            className={`absolute inset-y-0 left-0 ${signal.label === "POSITIVE" ? "bg-positive" : signal.label === "NEGATIVE" ? "bg-negative" : "bg-muted-foreground/50"}`}
            style={{ width: `${Math.round(signal.score * 100)}%` }}
          />
        </div>
        {/* Score pct */}
        <span className={`w-[28px] shrink-0 text-right font-mono text-[9px] tabular-nums ${
          signal.label === "POSITIVE" ? "text-positive" : signal.label === "NEGATIVE" ? "text-negative" : "text-muted-foreground"
        }`}>
          {Math.round(signal.score * 100)}%
        </span>
      </div>
    ))}
  </div>
</div>
```

**Data fetch**:
```typescript
const { data, isLoading, isError } = useQuery({
  queryKey: ["dashboard-ai-signals"],
  queryFn: () => createGateway(accessToken).getAiSignals(6),
  enabled: !!accessToken,
  staleTime: 120_000,   // 2 min: signals update as new articles arrive
  refetchInterval: 120_000,
});
const signals = data?.signals ?? [];
```

**Row click**: navigate to `/instruments/${signal.entity_id}` via `useRouter().push()`.

**Empty state**: `<InlineEmptyState message="No signals yet — processing articles…" />`

**Acceptance criteria**:
- [ ] Widget renders in its own file at `components/dashboard/AiSignalsWidget.tsx`
- [ ] Shows up to 6 signals with ticker, colored score bar, score %
- [ ] POSITIVE = text-positive (teal), NEGATIVE = text-negative (red), NEUTRAL = muted
- [ ] Row click navigates to `/instruments/{entity_id}`
- [ ] Loading skeleton: 6 rows with Skeleton components
- [ ] `pnpm tsc --noEmit` passes

##### T-A-5-02: Restructure Row 3 in dashboard page

**Type**: impl
**depends_on**: T-A-5-01
**Target files**: `apps/worldview-web/app/(app)/dashboard/page.tsx`

**What to build**:
Change Row 3 from 4+5+3 (Portfolio + Movers + Predictions) to 4+4+2+2 (Portfolio + Movers + Predictions + AI Signals):

```tsx
{/* ── Row 3: Portfolio (4) + Top Movers (4) + Prediction (2) + AI Signals (2) ─ */}
<div className="col-span-4 h-full border border-border/40">
  <PortfolioSummary />
</div>
<div className="col-span-4 h-full border border-border/40">
  <PreMarketMoversWidget />
</div>
<div className="col-span-2 h-full border border-border/40">
  <PredictionMarketsWidget />
</div>
<div className="col-span-2 h-full border border-border/40">
  <AiSignalsWidget />
</div>
```

The `PreMarketMoversWidget` in its narrower col-span-4 slot still renders the 2-column gainers/losers layout correctly (it uses `grid grid-cols-2` internally — verify the min-width doesn't break it). If the 2-column layout breaks at col-span-4, change to a single stacked list (5 gainers + 5 losers stacked) in a separate variant.

**Acceptance criteria**:
- [ ] Row 3 is 4+4+2+2 = 12 columns
- [ ] All 4 widgets render without horizontal overflow
- [ ] `AiSignalsWidget` imported and rendered
- [ ] `pnpm tsc --noEmit` passes

---

## Sub-plan B — Backend Waves

---

### Wave B-1: S4 content-ingestion — Add market_slug to PredictionMarketFetchResult

**Goal**: Extract Polymarket event `slug` from Gamma API response; propagate through ingestion pipeline.
**Depends on**: none
**Estimated effort**: 30 min
**Architecture layer**: domain entity + Avro schema

#### Pre-read
- `services/content-ingestion/src/content_ingestion/domain/entities.py` (lines 265–380)
- `infra/kafka/schemas/market.prediction.v1.avsc`
- `services/content-ingestion/tests/unit/test_domain_entities.py`

#### Tasks

##### T-B-1-01: Add market_slug to PredictionMarketFetchResult + from_gamma_response

**Type**: impl
**depends_on**: none
**Target files**: `services/content-ingestion/src/content_ingestion/domain/entities.py`

**What to build**:
Add `market_slug: str = ""` field to the `PredictionMarketFetchResult` dataclass.

In `from_gamma_response`, add:
```python
market_slug = raw.get("slug") or raw.get("market_slug") or raw.get("groupItemSlug") or ""
```
Add `market_slug=market_slug` to the `cls(...)` return.

Update test fixtures in `tests/unit/test_domain_entities.py` to include `"slug": "test-event-slug"` in mock raw dicts and assert `result.market_slug == "test-event-slug"`.

**Acceptance criteria**:
- [ ] Field exists with default `""`
- [ ] `from_gamma_response` populates from `raw.get("slug") or ...`
- [ ] Unit tests updated and pass

##### T-B-1-02: Add market_slug to market.prediction.v1 Avro schema + content-ingestion serializer

**Type**: schema
**depends_on**: T-B-1-01
**Target files**: `infra/kafka/schemas/market.prediction.v1.avsc`; serializer file in `services/content-ingestion/`

**What to build**:
Add to the Avro schema after `resolved_answer`:
```json
{
  "name": "market_slug",
  "type": ["null", "string"],
  "default": null,
  "doc": "Polymarket event slug for URL construction"
}
```

Update the Avro serializer to include `"market_slug": result.market_slug or None`.

**Downstream test impact**:
- `services/market-data/tests/unit/test_prediction_market_consumer.py` — mock messages need `market_slug: None`

**Acceptance criteria**:
- [ ] Avro schema validates with fastavro
- [ ] Serializer includes `market_slug` in payload
- [ ] `python -m pytest tests/ -v` passes in content-ingestion

---

### Wave B-2: S3 market-data + S9 — Expose market_slug

**Goal**: Store `market_slug` in DB; return it from S3 API; pass through S9.
**Depends on**: Wave B-1
**Estimated effort**: 35 min
**Architecture layer**: infrastructure (DB migration) + API schema

#### Pre-read
- `services/market-data/src/market_data/infrastructure/db/models/prediction_markets.py`
- `services/market-data/alembic/versions/006_prediction_markets_pk_fix.py` (current head)
- `services/market-data/src/market_data/api/schemas/prediction_markets.py`
- `services/market-data/src/market_data/infrastructure/messaging/consumers/prediction_market_consumer.py`
- `services/api-gateway/src/api_gateway/clients.py` (line ~1249: getPredictionMarkets transform)

#### Tasks

##### T-B-2-01: Alembic migration 007 — add market_slug

**Type**: schema
**Target files**: `services/market-data/alembic/versions/007_prediction_markets_add_slug.py` (new)

```python
"""add market_slug to prediction_markets

Revision ID: 007
Revises: 006
"""
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.add_column("prediction_markets", sa.Column("market_slug", sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column("prediction_markets", "market_slug")
```

**Acceptance criteria**:
- [ ] `alembic upgrade head` runs clean
- [ ] `alembic downgrade -1` works

##### T-B-2-02: ORM model + consumer + API schema + S9 passthrough

**Type**: impl
**depends_on**: T-B-2-01
**Target files**:
- `services/market-data/.../db/models/prediction_markets.py` — add `market_slug: Mapped[str | None]`
- `services/market-data/.../consumers/prediction_market_consumer.py` — write `market_slug` on upsert
- `services/market-data/.../api/schemas/prediction_markets.py` — add `market_slug: str | None = None` to `PredictionMarketSummaryResponse`
- `services/api-gateway/.../clients.py` — add `"market_slug": m.get("market_slug")` to S9 transform

**Downstream test impact**:
- `services/market-data/tests/unit/test_prediction_markets_api.py` — add `market_slug=None` to response assertions
- `services/market-data/tests/unit/test_prediction_market_consumer.py` — add mock Avro field
- `services/api-gateway/tests/test_s9_wave3_proxy.py` — update expected response shape

**Acceptance criteria**:
- [ ] `python -m pytest tests/ -v` passes in market-data and api-gateway

---

### Wave B-3: S3 market-data — Period Return Endpoints

**Goal**: Add two new S3 endpoints for period-based sector returns and top movers from OHLCV bars.
**Depends on**: none (OHLCV bars for 1w/1M timeframes already exist in the DB)
**Estimated effort**: 50 min
**Architecture layer**: API (S3 FastAPI) + application use case

#### Pre-read
- `services/market-data/src/market_data/infrastructure/db/models/ohlcv.py`
- `services/market-data/src/market_data/api/routers/` (existing router files for patterns)
- `services/market-data/src/market_data/infrastructure/db/` (repository patterns)
- `services/market-data/src/market_data/application/use_cases/` (use case patterns)
- `docs/services/market-data.md` (current API surface)

#### Tasks

##### T-B-3-01: Add sector-returns use case and repository method

**Type**: impl
**depends_on**: none
**Target files**:
- `services/market-data/src/market_data/application/use_cases/get_sector_returns.py` (new)
- `services/market-data/src/market_data/infrastructure/db/repositories/ohlcv_repository.py` (add method)
- `services/market-data/tests/unit/test_sector_returns.py` (new)

**What to build**:

**Repository method** `get_sector_period_returns(period: str) -> list[dict]`:
```sql
-- For period "1W": timeframe = '1w', for "1M": timeframe = '1M'
-- Returns: one row per sector with the average period return across instruments
SELECT
    i.sector,
    AVG(
        (latest.close - prev.close) / NULLIF(prev.close, 0)
    ) * 100 AS change_pct,
    COUNT(DISTINCT i.id) AS instrument_count
FROM instruments i
JOIN LATERAL (
    SELECT close FROM ohlcv_bars
    WHERE instrument_id = i.id AND timeframe = :timeframe
    ORDER BY bar_date DESC LIMIT 1
) latest ON true
JOIN LATERAL (
    SELECT close FROM ohlcv_bars
    WHERE instrument_id = i.id AND timeframe = :timeframe
    ORDER BY bar_date DESC LIMIT 1 OFFSET 1
) prev ON true
WHERE i.sector IS NOT NULL
  AND i.asset_type = 'equity'
GROUP BY i.sector
```

Map `timeframe`: `"1D"` → `"1d"`, `"1W"` → `"1w"`, `"1M"` → `"1M"`.

**Use case** `GetSectorReturns` (read-only, inherits `ReadOnlyUnitOfWork` per R27):
- Accepts `period: str` ("1D" | "1W" | "1M")
- For "1D": calls existing screener-based logic (delegates to the existing heatmap composition)
- For "1W" / "1M": calls the new repository method
- Returns: `list[{name: str, change_pct: float | None, instrument_count: int}]`

**Tests** (unit, mock repository):
| Test Name | What It Verifies |
|-----------|-----------------|
| test_sector_returns_1w_computes_average | For 1W, returns average of latest minus prev close |
| test_sector_returns_empty_sector | Sector with no OHLCV bars returns None change_pct |
| test_sector_returns_maps_timeframe | "1D" → "1d", "1W" → "1w", "1M" → "1M" |

**Acceptance criteria**:
- [ ] Use case class exists with `ReadOnlyUnitOfWork` dependency (R27)
- [ ] Repository method executes the lateral join query
- [ ] Unit tests pass

##### T-B-3-02: Add period-movers use case and router

**Type**: impl
**depends_on**: none
**Target files**:
- `services/market-data/src/market_data/application/use_cases/get_period_movers.py` (new)
- `services/market-data/src/market_data/api/routers/market.py` (add endpoints here or new file)
- `services/market-data/tests/unit/test_period_movers.py` (new)

**What to build**:

**Use case** `GetPeriodMovers(period, mover_type, limit)`:
- For "1D": reuse existing screener logic (sort by `daily_return`)
- For "1W" / "1M": repository query:
```sql
SELECT
    i.id AS instrument_id,
    i.symbol AS ticker,
    i.name,
    (latest.close - prev.close) / NULLIF(prev.close, 0) * 100 AS period_return_pct
FROM instruments i
JOIN LATERAL (
    SELECT close FROM ohlcv_bars
    WHERE instrument_id = i.id AND timeframe = :timeframe
    ORDER BY bar_date DESC LIMIT 1
) latest ON true
JOIN LATERAL (
    SELECT close FROM ohlcv_bars
    WHERE instrument_id = i.id AND timeframe = :timeframe
    ORDER BY bar_date DESC LIMIT 1 OFFSET 1
) prev ON true
WHERE i.asset_type = 'equity'
ORDER BY period_return_pct DESC  -- or ASC for losers
LIMIT :limit
```

**New S3 endpoints** (add to market router):
- `GET /api/v1/market/sector-returns?period=1W` → `{sectors: [{name, change_pct, instrument_count}]}`
- `GET /api/v1/market/period-movers?period=1W&type=gainers&limit=10` → `{results: [{instrument_id, ticker, name, period_return_pct}], type}`

Both endpoints use `ReadUoWDep` (R27 — read-only use cases use read replica).

**Tests**:
| Test Name | What It Verifies |
|-----------|-----------------|
| test_period_movers_gainers_sorted_desc | Top movers sorted by period_return_pct DESC |
| test_period_movers_losers_sorted_asc | Losers sorted ASC |
| test_period_movers_missing_ohlcv | Instruments with only 1 bar excluded (need 2 bars for return) |
| test_sector_returns_endpoint_200 | GET /market/sector-returns returns 200 with valid shape |

**Acceptance criteria**:
- [ ] Both endpoints exist and return correct response shapes
- [ ] "1D" path reuses existing screener (no regression)
- [ ] `python -m pytest tests/ -v` passes in market-data

---

### Wave B-4: S9 api-gateway — Wire Period to Heatmap + Movers

**Goal**: Add `period` parameter to S9 `get_market_heatmap` and `get_top_movers`; route 1W/1M requests to the new S3 endpoints.
**Depends on**: Wave B-3
**Estimated effort**: 30 min
**Architecture layer**: API proxy (S9)

#### Pre-read
- `services/api-gateway/src/api_gateway/clients.py` (lines 386–480)
- `services/api-gateway/tests/test_s9_wave3_proxy.py`

#### Tasks

##### T-B-4-01: Add period routing to get_market_heatmap and get_top_movers

**Type**: impl
**depends_on**: T-B-3-02
**Target files**: `services/api-gateway/src/api_gateway/clients.py`

**What to build**:

Update `get_market_heatmap` signature: `async def get_market_heatmap(clients, *, period: str = "1D", headers, make_headers)`.

- When `period == "1D"`: existing behavior (11 parallel screener calls per sector)
- When `period in ("1W", "1M")`: call `GET /api/v1/market/sector-returns?period={period}` on S3; map response to existing `{sectors: [...]}` shape

Update `get_top_movers` signature: add `period: str = "1D"`.

- When `period == "1D"`: existing behavior (screener with `daily_return`)
- When `period in ("1W", "1M")`: call `GET /api/v1/market/period-movers?period={period}&type={mover_type}&limit={limit}` on S3; transform response to existing `{movers: [...], type}` shape (map `period_return_pct` → `change_pct` as needed by frontend)

Add S9 route query params `period` to the FastAPI route handlers that call these functions.

Update tests in `test_s9_wave3_proxy.py` to add coverage for `period=1W` calls.

**Acceptance criteria**:
- [ ] `GET /v1/market/heatmap?period=1W` routes to S3 sector-returns endpoint
- [ ] `GET /v1/market/top-movers?type=gainers&period=1W` routes to S3 period-movers
- [ ] `period=1D` still uses original screener path (no regression)
- [ ] `python -m pytest tests/ -v` passes in api-gateway

---

## Cross-Cutting Concerns

### Schema changes
- `market.prediction.v1.avsc`: add `market_slug` (forward-compatible, `"default": null`)
- `prediction_markets` table: add `market_slug` nullable column (migration 007)
- `PredictionMarketSummaryResponse`: add `market_slug: str | None = None`

### New S3 endpoints
- `GET /api/v1/market/sector-returns?period=1W|1M`
- `GET /api/v1/market/period-movers?period=1W|1M&type=gainers|losers&limit=N`

### Documentation updates needed (after implementation)
- `docs/services/market-data.md`: add new endpoints to API surface table
- `docs/services/api-gateway.md`: add `period` param to heatmap/movers routes

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| 1W/1M OHLCV bars may be sparse (few instruments have weekly/monthly bars populated) | Medium | Period endpoints return null change_pct for sectors with < 2 bars; frontend shows "–" for null |
| LATERAL JOIN performance on large ohlcv_bars table | Medium | Index `(instrument_id, timeframe, bar_date)` already exists — should be fast; add EXPLAIN ANALYZE in test |
| Gamma API `slug` field absent for some markets | Low | Default `""` → search URL fallback |
| Row 3 restructure from 4+5+3 to 4+4+2+2 breaks Movers 2-column layout | Low | If col-span-4 is too narrow for 2-col movers, switch to single stacked list |

**Critical path**: B-3 → B-4 → A-3 (period wiring). A-1/A-2/A-5 are fully independent.

---

## Regression Guardrails

- **BP-023/BP-127** (ruff format): `git diff --name-only --cached | grep ".py$" | xargs uvx ruff format --check`
- **BP-065** (stash conflict): fix ruff before `git add`
- **BP-126** (Alembic nullable column): migration adds nullable column — correct, no `server_default` needed
- **BP-011** (forward-compat Avro): `"default": null` as first union type — correct pattern
- **BP-180** (asyncpg CAST for nullable params): if repository method uses nullable parameters in WHERE clause, use `CAST(:param AS TEXT) IS NULL` pattern not bare `IS NULL`
- **R27** (ReadOnlyUoW for reads): new use cases in B-3 must use `ReadOnlyUnitOfWork`/`ReadUoWDep` — do not use `UoWDep`
- **R25** (API layer isolation): new S3 routers must import use cases only, no infrastructure imports

---

## Validation Gates

### Wave A-1
- [ ] `pnpm tsc --noEmit` — 0 errors
- [ ] Visual: brief header compact, text fills Row 1, font ≤ 10px

### Wave A-2
- [ ] `pnpm tsc --noEmit` — 0 errors
- [ ] Visual: panel borders visible, Row 2 ≈ 130px

### Wave A-3
- [ ] `pnpm tsc --noEmit` — 0 errors
- [ ] `pnpm test` passes
- [ ] Network tab: 1D/1W/1M clicks trigger distinct API calls with `period` param
- [ ] No 5D/5W or portfolio period buttons visible

### Wave A-4
- [ ] `pnpm tsc --noEmit` — 0 errors
- [ ] Clicking prediction market row opens real URL

### Wave A-5
- [ ] `pnpm tsc --noEmit` — 0 errors
- [ ] `AiSignalsWidget` renders in Row 3 col-span-2 slot
- [ ] Score bars colored correctly per label

### Wave B-1
- [ ] `python -m pytest tests/unit/ -v` passes (content-ingestion)
- [ ] Avro schema validates

### Wave B-2
- [ ] `python -m pytest tests/ -v` passes (market-data + api-gateway)
- [ ] `alembic upgrade head` clean

### Wave B-3
- [ ] `python -m pytest tests/ -v` passes (market-data)
- [ ] `GET /api/v1/market/sector-returns?period=1W` returns `{sectors: [...]}`
- [ ] `GET /api/v1/market/period-movers?period=1W&type=gainers&limit=5` returns results

### Wave B-4
- [ ] `python -m pytest tests/ -v` passes (api-gateway)
- [ ] `GET /v1/market/heatmap?period=1W` returns different data from `period=1D`

---

## Execution Order (Recommended)

```
Parallel sprint A: A-1 → A-2 → A-5 (independent, ship immediately)
Parallel sprint B: B-1 → B-2 (Polymarket URL)
                   B-3 → B-4 → A-3 (period wiring)
After B-2: A-4 (Polymarket frontend with real URLs)
```

Fastest path to user-visible improvement: **A-1, A-2, A-5** — all independent of backend.

---

## Compounding Check

No new bug patterns. No STANDARDS.md updates needed. The LATERAL JOIN pattern for OHLCV period returns is worth noting in `docs/services/market-data.md` once implemented.

**Total waves**: 9 (A-1/A-2/A-3/A-4/A-5 + B-1/B-2/B-3/B-4)
