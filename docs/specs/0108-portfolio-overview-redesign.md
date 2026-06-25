# PRD-0108 — Portfolio Overview Redesign + Transaction Type Fix

> **Status**: draft
> **Author**: agent-prd
> **Date**: 2026-06-08
> **Services affected**: S1 (portfolio), S9 (api-gateway), worldview-web
> **Related**: PRD-0089 FR-3 (portfolio density target), PLAN-0089 Wave K (chat polish, shipped)

---

## 1. Problem Statement

The portfolio overview page has three classes of active pain:

1. **Hard crash on manual position entry.** `POST /api/v1/transactions` returns HTTP 500 whenever a user submits the "Add Position" dialog. The frontend sends `transaction_type: "TRADE"` but the backend `TransactionType` enum has no `TRADE` member; the unguarded `TransactionType(body.transaction_type)` call at `routes/transaction.py:64` raises `ValueError` and falls through to a 500. A second failure on the same line converts `direction: "BUY"` against `TransactionDirection(INFLOW|OUTFLOW)`, which also has no `BUY` member. The Pydantic schema accepts `transaction_type` and `direction` as bare `str`, so neither validation failure is caught as 422.

2. **Holdings are not scannable in the first five seconds.** The overview page opens on a 12-column AG Grid that occupies less than half the viewport below the fold. There is no fast read on total value, today's P&L, sector exposure, or which positions are doing the work. The tab labelled "Holdings" is rendered in `text-[10px] font-mono` with no visual affordance, so many users do not realise their positions are behind a click.

3. **Charts are not self-explanatory.** `EquityCurveChart` has no axis labels; `PositionBarHeat` has no y-axis scale ruler (the bar heights are meaningless without knowing the range); `ExposureBreakdown` lacks inline segment percentages. Users cannot read the charts without prior context.

This PRD implements the full PRD-0089 FR-3 density target (281 cells above the fold at 1440×900) and resolves all three classes of pain in a single delivery.

---

## 2. Users and Journeys

**Primary persona**: Active retail trader or quant analyst managing a book of 5–40 positions. Opens the portfolio page 6–15 times per day as the first screen after login.

**Primary journeys this PRD serves**:

| # | Journey | Current pain | After this PRD |
|---|---------|-------------|----------------|
| J-PORT-1 | Snapshot the book (total value, day P&L, unrealised P&L) | Requires scrolling past charts to read KPI strip | KPI strip is first visible row (h-7), 8 cells, always above fold |
| J-PORT-2 | Find today's movers | No movers surface; must mentally scan the table | Contributors/Detractors strip (bottom) + Day Δ$ / Day Δ% columns colour-coded |
| J-PORT-3 | Validate sizing (concentration, sector, cash) | Sector data only in Holdings tab; concentration behind a drill-down | Exposure strip + Concentration strip + Sector allocation bar all visible before the table |
| J-PORT-4 | Add a manual position | Returns 500; user sees a generic error toast | Fix lands in W1; dialog completes correctly |
| J-PORT-5 | Read a performance chart | Axes unlabelled; no benchmark | New PerformanceChartPanel: labelled axes, SPY overlay, collapsible |

---

## 3. Functional Requirements

### 3.1 Must-have (v1, this PRD)

| ID | Requirement |
|----|-------------|
| FR-1 | `TransactionType` enum gains a `TRADE` value. |
| FR-2 | A new `TradeSide` enum (BUY \| SELL) is added to the domain. |
| FR-3 | `Transaction` entity and `transactions` DB table gain a nullable `trade_side` column. |
| FR-4 | `RecordTransactionRequest.transaction_type` is validated against the enum at schema level (422 on invalid value, not 500). |
| FR-5 | `RecordTransactionRequest.trade_side` is an optional new field (required when `transaction_type == TRADE`). |
| FR-6 | The route handler maps TRADE+BUY → direction=INFLOW, TRADE+SELL → direction=OUTFLOW. |
| FR-7 | The frontend `addPosition()` API client sends `transaction_type: "TRADE", trade_side: "BUY"` (not `direction: "BUY"`). |
| FR-8 | `GET /v1/market/sparklines` S9 endpoint returns 14-day closing-price arrays keyed by instrument_id. |
| FR-9 | The Holdings tab overview is redesigned to the "Anchored table" layout (§6.6). |
| FR-10 | `PortfolioKPIStrip` is extended from 7 to 8 cells (add Cash and Buying Power). |
| FR-11 | `ExposureCurrencyStrip` (new, 22 px) displays invested %, cash $, leverage, β-adj, and top-2 currency exposures. |
| FR-12 | `ConcentrationSectorTeaseStrip` (new, 22 px) displays HHI classification, top-3 concentration %, name count, and top-3 sector weights. |
| FR-13 | `PerformanceChartPanel` (new, 120 px, collapsible) replaces `EquityCurveChart` on the Holdings overview; shows portfolio + SPY benchmark; has labelled axes. |
| FR-14 | `SectorAllocationBar` (new, 22 px) renders a single-row stacked horizontal bar with inline sector labels. |
| FR-15 | `HoldingsTableChrome` (new, 22 px) renders "POSITIONS — N · sort · filter" chrome above the table. |
| FR-16 | `SemanticHoldingsTable` gains a SPARK column (60×16 inline SVG, 14-day) and an ASSET column (single-letter chip). |
| FR-17 | `SparklineCellRenderer` (new) renders the SPARK column from `useHoldingsSeries` data; degrades to `—` when series unavailable. |
| FR-18 | `AssetTypeCellRenderer` (new) renders the ASSET column chip (E/F/B/C). |
| FR-19 | `BottomStripCluster` (new, 96 px) renders three equal-width cells: top-4 contributors, top-4 detractors, last-8 activity. |
| FR-20 | `useTopMovers` hook (new) derives contributors/detractors client-side from enriched holdings without additional API calls. |
| FR-21 | `useHoldingsSeries` hook (new) fetches sparklines via `GET /v1/market/sparklines` with 15-min stale time. |
| FR-22 | `AddPositionDialog` button in `PortfolioPageHeader` is increased to `text-[11px]`; disabled state for ROOT shows inline explanatory text. |
| FR-23 | `EquityCurveChart` (kept in Analytics tab) gains axis labels: "Value ($)" on y-axis, dates on x-axis. |

### 3.2 Explicit out-of-scope (v1)

- Per-position beta column and `GET /v1/instruments/{id}/risk` endpoint (post-PRD-0108)
- `PositionBarHeat` replacement with full y-axis ruler (component retired from overview; y-axis ruler on remaining charts is FR-23)
- Holdings detail sub-page (`04-portfolio-detail.md` spec)
- Keyboard shortcut for Add Position dialog
- Drag-and-drop column reordering on the holdings table

---

## 4. Non-Functional Requirements

| ID | NFR |
|----|-----|
| NFR-1 | Holdings tab initial paint (KPI strip + table skeleton) ≤ 400 ms p95 on localhost (already satisfied by bundle endpoint; no regression). |
| NFR-2 | Sparkline batch endpoint: cold path ≤ 800 ms p95 (parallel S3 calls, Valkey cache 15 min). |
| NFR-3 | PerformanceChartPanel must render within the 120 px height at 1440×900; no content overflow. |
| NFR-4 | Holdings table: 22 px row height, ≥ 16 rows visible above fold at 1440×900 with all strips rendered. |
| NFR-5 | All new frontend components pass Vitest unit tests; AddPositionDialog integration test passes. |
| NFR-6 | DB migration 0021 is backward-compatible: `trade_side` column is nullable with no server_default; all existing rows remain valid. |

---

## 5. Out of Scope

- Changes to the Transactions tab, Analytics tab, or Watchlist tab layout
- Any change to `GET /api/v1/transactions` response shape (existing consumers unaffected)
- Mobile/responsive breakpoints (desktop-first; mobile polish is a follow-up)
- Dark/light theme toggle (already locked to Terminal Dark by design system)
- PLAN-0105 (frontend slim reads) — latency work is parallel; no dependency
- Assumes PLAN-0105 (Frontend Slim Reads) waves A–E1 have NOT merged. If PLAN-0105 merges first, data-fetching hooks may need updating.

---

## 6. Technical Design

### 6.1 Affected Services

| Service | What changes |
|---------|-------------|
| S1 (portfolio) | `TransactionType` enum, `TradeSide` enum, `Transaction` entity, `TransactionModel`, `RecordTransactionRequest` schema, route handler, `RecordTransactionCommand`, use case, Alembic migration 0021 |
| S9 (api-gateway) | New `GET /v1/market/sparklines` route + handler |
| worldview-web | 13 new components, 3 extended components, 2 new hooks, 1 updated API client function, 1 updated page layout |

### 6.2 API Changes

#### POST /api/v1/transactions (S1) — modified

- **Purpose**: Record a manually-entered or brokerage-imported transaction.
- **Auth**: InternalJWTMiddleware (RS256, X-Internal-JWT header from S9)
- **Change summary**: `transaction_type` is now validated as a `Literal` enum at schema level; new optional `trade_side` field is required when `transaction_type == "TRADE"`.

**Request body** (changes only; all other fields unchanged):

| Field | Type | Required | Default | Validation | Description |
|-------|------|----------|---------|------------|-------------|
| transaction_type | `Literal["BUY","SELL","DIVIDEND","DEPOSIT","WITHDRAWAL","FEE","INTEREST","TRADE"]` | yes | — | Must be one of 8 values; 422 if not | Transaction semantic type |
| direction | `Literal["INFLOW","OUTFLOW"]` | yes | — | Must be INFLOW or OUTFLOW; 422 if not | Cash-flow accounting direction |
| trade_side | `Literal["BUY","SELL"] \| None` | conditional | `null` | Required when transaction_type == "TRADE"; 422 if missing | Human-readable side for TRADE type |

**Route handler logic** (new):
```python
if body.transaction_type == "TRADE":
    if body.trade_side is None:
        raise HTTPException(422, "trade_side is required for TRADE transactions")
    direction = TransactionDirection.INFLOW if body.trade_side == "BUY" else TransactionDirection.OUTFLOW
else:
    direction = TransactionDirection(body.direction)
```

**Error responses**:
- 401 — Missing/invalid JWT
- 404 — portfolio_id not found or not owned by requesting user
- 409 — Idempotency-Key already processed (returns original response)
- 422 — Invalid enum value, missing trade_side for TRADE, quantity ≤ 0, price ≤ 0

#### GET /v1/market/sparklines (S9) — new

- **Purpose**: Return 14-day daily closing-price arrays for a batch of instruments. Used by `useHoldingsSeries` to populate the SPARK column in the holdings table.
- **Auth**: JWT (standard OIDCAuthMiddleware)
- **Query parameters**:

| Param | Type | Required | Default | Validation | Description |
|-------|------|----------|---------|------------|-------------|
| instrument_ids | `string` | yes | — | Comma-separated UUIDs; max 50 | Instrument IDs to fetch series for |
| days | `integer` | no | `14` | 1–90 | Number of trailing calendar days |

**Response** (200):

| Field | Type | Description |
|-------|------|-------------|
| data | `Record<string, number[]>` | Keyed by instrument_id UUID (string); value is array of closing prices, oldest-first, length ≤ days |
| meta.days_requested | `integer` | Echo of `days` param |
| meta.fetched_at | `string` | ISO-8601 UTC timestamp |
| meta.missing | `string[]` | instrument_ids for which S3 returned no data (absent from `data` map) |

**Implementation**:
1. Parse and deduplicate `instrument_ids`.
2. Look up tickers from S3 instrument lookup (or via S9 internal instrument map).
3. Fan out `asyncio.gather` calls to S3 `GET /api/v1/ohlcv/{ticker}?timeframe=1d&days={days}`.
4. Each sub-call is wrapped in try/except; failures go to `meta.missing`.
5. Cache full response in Valkey at key `sparklines:{sorted(instrument_ids)}:{days}` with TTL 900s (15 min).
6. Respond with `data` map + `meta`.

**Error responses**:
- 400 — `instrument_ids` empty or > 50 items
- 401 — Missing/invalid JWT
- 422 — Non-UUID value in instrument_ids

**Rate limit**: 60 req/min per user (same as other market data routes).

### 6.3 Event Changes

None. This PRD introduces no new Kafka events. `RecordTransactionUseCase` already publishes `portfolio.transaction.recorded.v1` via the outbox; the new `trade_side` field is not added to that event schema (it is internal to S1 and not consumed downstream).

---

### 6.4 Database Changes

#### Table: transactions (portfolio_db)

**Current Alembic head**: `0020_add_transaction_description.py`

**New migration**: `0021_add_transaction_trade_side.py`

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| trade_side | VARCHAR(4) | yes | NULL | CHECK (trade_side IN ('BUY','SELL') OR trade_side IS NULL) | Non-null only for TRADE-type rows |

**Alembic migration**:
```python
def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("trade_side", sa.String(4), nullable=True,
                  comment="BUY or SELL for TRADE-type transactions; NULL for all other types"),
    )
    op.create_check_constraint(
        "ck_transactions_trade_side", "transactions",
        "trade_side IN ('BUY', 'SELL') OR trade_side IS NULL",
    )

def downgrade() -> None:
    op.drop_constraint("ck_transactions_trade_side", "transactions")
    op.drop_column("transactions", "trade_side")
```

**Backfill**: None. Historical rows (`trade_side = NULL`) are correct — their `direction` column (INFLOW/OUTFLOW) is the accounting truth.

**No other DDL changes.** `TransactionType` is stored as VARCHAR (`Mapped[str]`), so adding a new StrEnum value requires no migration.

---

### 6.5 Domain Model Changes

#### Enum: TransactionType (S1) — extended

**File**: `services/portfolio/src/portfolio/domain/enums.py`

Add `TRADE = "TRADE"`.

| Value | Meaning | direction mapping |
|-------|---------|-------------------|
| BUY | Legacy broker-imported buy | INFLOW |
| SELL | Legacy broker-imported sell | OUTFLOW |
| DIVIDEND | Cash dividend | INFLOW |
| DEPOSIT | Cash deposit | INFLOW |
| WITHDRAWAL | Cash withdrawal | OUTFLOW |
| FEE | Brokerage fee | OUTFLOW |
| INTEREST | Interest payment | INFLOW |
| **TRADE** | **Manual equity trade; side = trade_side** | INFLOW (BUY) / OUTFLOW (SELL) |

#### Enum: TradeSide (S1) — new

**File**: `services/portfolio/src/portfolio/domain/enums.py`

```python
class TradeSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
```

**Invariant**: `trade_side is not None ↔ transaction_type == TransactionType.TRADE`

#### Entity: Transaction (S1) — extended

**File**: `services/portfolio/src/portfolio/domain/entities/transaction.py`

New field:

| Attribute | Type | Required | Default | Validation | Notes |
|-----------|------|----------|---------|------------|-------|
| trade_side | `TradeSide \| None` | no | `None` | Non-null iff type == TRADE | Human-readable side |

Invariant (domain-level assertion in `__post_init__`):
```python
if self.transaction_type == TransactionType.TRADE and self.trade_side is None:
    raise ValueError("trade_side must be set for TRADE transactions")
if self.transaction_type != TransactionType.TRADE and self.trade_side is not None:
    raise ValueError("trade_side must be None for non-TRADE transactions")
```

#### Command: RecordTransactionCommand (S1) — extended

**File**: `services/portfolio/src/portfolio/application/use_cases/record_transaction.py`

Add `trade_side: TradeSide | None = None` to the dataclass.

#### Schema: RecordTransactionRequest (S1) — tightened

**File**: `services/portfolio/src/portfolio/api/schemas.py`

| Field | Before | After |
|-------|--------|-------|
| transaction_type | `str` | `Literal["BUY","SELL","DIVIDEND","DEPOSIT","WITHDRAWAL","FEE","INTEREST","TRADE"]` |
| direction | `str` | `Literal["INFLOW","OUTFLOW"]` |
| trade_side | absent | `Literal["BUY","SELL"] \| None = None` |

Add `@model_validator(mode="after")`:
```python
if self.transaction_type == "TRADE" and self.trade_side is None:
    raise ValueError("trade_side is required when transaction_type is TRADE")
```

`RecordTransactionResponse` gains `trade_side: str | None` field.

#### ORM Model: TransactionModel (S1) — extended

**File**: `services/portfolio/src/portfolio/infrastructure/db/models/transaction.py`

Add:
```python
trade_side: Mapped[str | None] = mapped_column(String(4), nullable=True, default=None,
    comment="BUY or SELL for TRADE-type rows; NULL for all others")
```

#### Route handler: record_transaction (S1) — updated

**File**: `services/portfolio/src/portfolio/api/routes/transaction.py`

Replace lines 58–68 with:
```python
from portfolio.domain.enums import TransactionDirection, TransactionType, TradeSide

if body.transaction_type == "TRADE":
    direction = (
        TransactionDirection.INFLOW if body.trade_side == "BUY"
        else TransactionDirection.OUTFLOW
    )
    trade_side = TradeSide(body.trade_side)
else:
    direction = TransactionDirection(body.direction)
    trade_side = None

result = await uc.execute(
    RecordTransactionCommand(
        ...
        transaction_type=TransactionType(body.transaction_type),
        direction=direction,
        trade_side=trade_side,
        ...
    ),
    uow,
)
```

#### Frontend API client — updated

**File**: `apps/worldview-web/lib/api/portfolios.ts`

`addPosition()` function: change `direction: "BUY"` → `trade_side: "BUY"`, remove the `direction` field from the request body for TRADE calls.

---

### 6.6 Frontend Changes

#### Page layout — `app/(app)/portfolio/page.tsx`

The top-level 4-tab structure **is preserved**: HOLDINGS | TRANSACTIONS | ANALYTICS | WATCHLIST.

The Holdings tab layout is replaced with the "Anchored table" design. The tab shell renders:

```
flex flex-col h-full bg-background
├── PortfolioPageHeader            (h-9, existing, modified — button size + ROOT text)
├── PortfolioKPIStrip [extended]   (h-7, 8 cells)
├── ExposureCurrencyStrip [new]    (h-[22px])
├── ConcentrationSectorTeaseStrip [new]  (h-[22px])
├── PerformanceChartPanel [new]    (h-[120px], collapsible)
├── SectorAllocationBar [new]      (h-[22px])
├── HoldingsTableChrome [new]      (h-[22px])
├── SemanticHoldingsTable [ext]    (flex-1 min-h-0, 14 cols: +SPARK +ASSET)
└── BottomStripCluster [new]       (h-24, 3 equal-width cells)
```

Components **removed from the Holdings tab** (moved to Analytics tab or retired):

| Component | Disposition |
|-----------|-------------|
| `PositionBarHeat` | Retired from Holdings overview; replaced by inline SPARK column |
| `EquityCurveChart` | Stays in Analytics tab; axis-label fix applied there |
| `ExposureBreakdown` | Stays in Analytics tab |
| `ConcentrationStrip` (old) | Replaced by `ConcentrationSectorTeaseStrip` |

#### New and modified components

> NOTE: All components listed below already exist in the codebase as of 2026-06-08. Statuses reflect actual current state vs. PRD requirements.

| Component | File | Status | Budget | Purpose |
|-----------|------|--------|--------|---------|
| `PortfolioPageHeader` | `features/portfolio/components/PortfolioPageHeader.tsx` | MODIFY | — | Button `text-[11px]`; ROOT disabled state inline text |
| `PortfolioKPIStrip` | `components/portfolio/PortfolioKPIStrip.tsx` | DONE (no change needed) | — | Already 8 cells: Total Value, Day P&L, Unrealised P&L, Realized P&L, Cash, Buying Pwr, Top Gain, Top Lose — all props present (cash, buyingPower) |
| `ExposureCurrencyStrip` | `components/portfolio/ExposureCurrencyStrip.tsx` | DONE (no change needed) | — | Fully implements h-[22px] strip with INV, CASH, LEV, and optional top-2 CCY chips; wired in HoldingsTab |
| `ConcentrationSectorTeaseStrip` | `components/portfolio/ConcentrationSectorTeaseStrip.tsx` | EXTEND — missing: name count cell (PRD says "14 names" display); HHI thresholds use 1500/2500 not 1000/2500 as PRD specifies | — | Exists and wired; HHI badge + top-3 sectors rendered |
| `PerformanceChartPanel` | `components/portfolio/PerformanceChartPanel.tsx` | DONE (no change needed) | — | 120px collapsible chart, SPY overlay (normalised), period buttons (1W/1M/3M/6M/1Y/All), collapse toggle — fully implemented and wired in HoldingsTab |
| `SectorAllocationBar` | `components/portfolio/SectorAllocationBar.tsx` | DONE (no change needed) | — | Single-row stacked horizontal bar with top-3 inline labels; wired in HoldingsTab |
| `HoldingsTableChrome` | `components/portfolio/HoldingsTableChrome.tsx` | EXTEND — component exists and is complete (position count, filter bar, Ctrl+F handler) but is NOT wired into HoldingsTab; SemanticHoldingsTable is rendered without it | — | Component fully implemented; missing: integration into HoldingsTab above SemanticHoldingsTable |
| `SemanticHoldingsTable` | `components/portfolio/SemanticHoldingsTable.tsx` | EXTEND — SPARK and ASSET columns are not present in ag-holdings-columns.tsx (12 cols, no spark/asset); SparklineCellRenderer and AssetTypeCellRenderer exist but are not registered in holdingsAgColumns; holdingsSeries and assetClasses not passed via AG Grid context | +40 LOC | Add SPARK col (SparklineCellRenderer) and ASSET col (AssetTypeCellRenderer) — still required |
| `SparklineCellRenderer` | `components/portfolio/cells/SparklineCellRenderer.tsx` | DONE (no change needed) | — | 60×16 inline SVG via F1 Sparkline primitive; "—" on missing/short series; keyed by ticker from AG Grid context |
| `AssetTypeCellRenderer` | `components/portfolio/cells/AssetTypeCellRenderer.tsx` | DONE (no change needed) | — | 3-char chips (EQ/ETF/OPT/FUT/BND/CRY) with colour badges; keyed by instrument_id from AG Grid context (note: uses 3-char not single-letter as PRD suggested — intentional, documented in file) |
| `ContributorsStrip` | `components/portfolio/ContributorsStrip.tsx` | DONE (no change needed) | — | Combined contributors + detractors in one column (4+4 rows); wired in HoldingsTab bottom grid |
| `RecentActivityStrip` | `components/portfolio/RecentActivityStrip.tsx` | EXTEND — shows last 5 (not 8 as PRD §6.6 spec says); component comment acknowledges this | — | Otherwise fully implemented and wired in HoldingsTab bottom grid |
| `BottomStripCluster` | `components/portfolio/BottomStripCluster.tsx` | NEW — file does not exist; the cluster is currently inlined as a 2-col grid div directly in HoldingsTab.tsx (not a reusable component) | 60 LOC | 3-cell flex row: ContributorsStrip · DetractorsStrip · RecentActivityStrip |
| `EquityCurveChart` | `components/portfolio/EquityCurveChart.tsx` | MODIFY (axis fix) | +30 LOC | Add "Value ($)" y-axis label + date x-axis label overlay |

#### New hooks

**`features/portfolio/hooks/useTopMovers.ts`** — DONE (exists, ~60 LOC)

Derives top-4 contributors and bottom-4 detractors from `enrichedHoldings` + `quotes` already loaded by `usePortfolioData`. No additional API call.

Returns:
```ts
{
  todayWinners: Mover[]   // sorted by dayChangeDollar desc
  todayLosers:  Mover[]   // sorted by dayChangeDollar asc
}

type Mover = {
  ticker: string
  name: string
  dayChangeDollar: number
  dayChangePct: number
}
```

**`features/portfolio/hooks/useHoldingsSeries.ts`** — NEW (does not exist yet), ~100 LOC

Calls `GET /v1/market/sparklines?instrument_ids=…&days=14`.

Returns `Record<string, number[]>` keyed by instrument_id.

TanStack Query config: `staleTime: 15 * 60 * 1000`, `gcTime: 30 * 60 * 1000`, `retry: 1`.

Graceful degradation: on error or missing key, `SparklineCellRenderer` renders `—`.

#### Holdings table column spec (14 columns)

| Col | Width | Align | Source |
|-----|-------|-------|--------|
| Ticker | 76 | left | holdings.ticker |
| Name | 168 | left | holdings.name (truncated) |
| Qty | 78 | right | holdings.quantity |
| Avg Cost | 86 | right | holdings.average_cost |
| Last | 86 | right | quotes[id].price + freshness dot |
| Day Δ$ | 82 | right | quotes[id].change × qty |
| Day Δ% | 70 | right | quotes[id].change_pct |
| Spark | 76 | center | series[id][-14:] via useHoldingsSeries |
| Mkt Value | 96 | right | qty × price |
| Unreal $ | 90 | right | (price − avg) × qty |
| Unreal % | 70 | right | (price − avg) / avg × 100 |
| Weight | 70 | right | value / totalValue |
| Sector | 80 | left | overviews[id].sector |
| Asset | 44 | center | overviews[id].asset_type chip |

Total width: 1152 px (fits 1280 px+ viewport with sidebar).

#### PerformanceChartPanel visual spec

| Property | Value |
|----------|-------|
| Height (expanded) | 120 px |
| Height (collapsed) | 22 px (shows label + toggle button only) |
| Default state | expanded |
| Chart library | lightweight-charts (existing dep) |
| Series 1 | Portfolio equity curve (area, `var(--color-primary)` fill) |
| Series 2 | SPY benchmark (line, `var(--color-muted-foreground)`, dashed) |
| Y-axis label | "Value ($)" — 9 px, `var(--muted-foreground)`, absolute positioned top-left inside panel |
| X-axis label | Not needed (dates shown on tick marks; period buttons are the affordance) |
| Period buttons | 1W · 1M · 3M (default) · 6M · 1Y · All — URL-backed via nuqs |
| Collapse toggle | "▼ collapse / ▲ expand" text button at top-right of panel header |
| Benchmark source | `GET /v1/portfolios/{id}/value-history` includes SPY benchmark series (already exists via risk_metrics route) |

#### PortfolioPageHeader changes

| Element | Before | After |
|---------|--------|-------|
| Add Position button font | `text-[10px]` | `text-[11px]` |
| Add Position button hover | `hover:border-primary/60` only | Add `hover:bg-primary/5` |
| ROOT disabled state | Tooltip on hover only | Add `<p className="text-[10px] text-muted-foreground mt-0.5">Select a portfolio to add positions. ALL is read-only.</p>` below portfolio selector |

#### ExposureCurrencyStrip data binding

Reads from `usePortfolioData().exposure` (already loaded):

| Cell | Value | Format |
|------|-------|--------|
| INV | `exposure.invested_pct` | `99.6%` |
| CASH | `exposure.cash` | `$1,402` |
| LEV | `exposure.leverage` | `1.00×` |
| β-ADJ | computed from holdings (client-side) | `1.12` |
| CCY 1 | top currency by value | `USD 92%` |
| CCY 2 | second currency by value | `EUR 8%` |

Beta-adjusted exposure is derived client-side: `Σ(position_value × beta) / total_value`. Beta defaults to 1.0 when unavailable.

#### ConcentrationSectorTeaseStrip data binding

Reads from `usePortfolioData().concentration`:

| Cell | Value |
|------|-------|
| HHI | badge: `low` (<1000) / `moderate` (1000–2500) / `high` (>2500) |
| Top-3 | `47.2%` |
| Names | `14 names` |
| Top sector | `TECH 38.1%` |
| 2nd sector | `FIN 17.4%` |
| 3rd sector | `HC 12.0%` |

---

### 6.7 Data Flow

#### Flow 1: Add Position (post-fix)

```
User fills AddPositionDialog → submits
  frontend: addPosition(portfolioId, { instrument_id, qty, price, executed_at })
  ↓ lib/api/portfolios.ts
  POST /v1/transactions
    body: { transaction_type: "TRADE", trade_side: "BUY", direction: "INFLOW",
            quantity, price, portfolio_id, instrument_id, currency: "USD",
            executed_at }
  ↓ S9 proxies with _auth_headers(request)
  POST /api/v1/transactions (S1)
  ↓ RecordTransactionRequest validates:
      - transaction_type ∈ {"TRADE", ...} ✓
      - trade_side == "BUY" ✓
      - model_validator: TRADE + trade_side present ✓
  ↓ route handler maps: direction = INFLOW, trade_side = TradeSide.BUY
  ↓ RecordTransactionUseCase.execute(RecordTransactionCommand(...))
  ↓ Transaction created in DB with trade_side="BUY"
  ↓ Outbox event portfolio.transaction.recorded.v1 enqueued
  → 201 RecordTransactionResponse { id, ..., trade_side: "BUY" }
  ↓ frontend invalidates holdings + transactions queries
  ↓ frontend also invalidates sparklines cache: queryClient.invalidateQueries({ queryKey: ['sparklines'] })
  ↓ SemanticHoldingsTable refetches and shows updated holding
```

#### Flow 2: Holdings tab initial load (redesigned)

```
User navigates to /portfolio (Holdings tab, default)
  ↓
usePortfolioBundle() → GET /v1/portfolio/{id}/bundle
  returns: { portfolio, holdings, transactions[0:8], value_history }
  staleTime: 30s (warm cache)

Parallel (TanStack Query):
  usePortfolioData().concentration → GET /v1/portfolios/{id}/concentration
  usePortfolioData().exposure      → GET /v1/portfolios/{id}/exposure
  usePortfolioData().quotes        → GET /v1/market/quote/batch (instrument_ids)
  usePortfolioData().overviews     → GET /v1/market/overview-bulk (instrument_ids)
  useHoldingsSeries()              → GET /v1/market/sparklines?instrument_ids=...&days=14

Renders (in order, progressive):
  1. PortfolioKPIStrip — renders immediately from bundle.portfolio + quotes
  2. ExposureCurrencyStrip — renders when exposure resolves (~50ms cache hit)
  3. ConcentrationSectorTeaseStrip — renders when concentration resolves (~50ms)
  4. PerformanceChartPanel — renders when bundle.value_history resolves
  5. SectorAllocationBar — renders when concentration + overviews resolve
  6. SemanticHoldingsTable — renders when bundle.holdings + quotes resolve
     (SPARK column renders progressively as useHoldingsSeries resolves)
  7. BottomStripCluster — renders when quotes + transactions resolve
     ContributorsStrip: purely client-side from enrichedHoldings (no extra call)
     RecentActivityStrip: from bundle.transactions[0:8]
```

#### Flow 3: Sparkline batch (cold path)

```
useHoldingsSeries(instrument_ids=[...14 ids...])
  ↓
GET /v1/market/sparklines?instrument_ids=abc,def,...&days=14
  ↓ S9 route handler
  Check Valkey: sparklines:{sorted_ids}:14 → MISS
  ↓
  asyncio.gather(*[
    S3.get(f"/api/v1/ohlcv/{ticker}?timeframe=1d&days=14")
    for ticker in tickers
  ])
  ↓ each result: {ticker, items: [{bar_date, close}, ...]}
  ↓ transform to {instrument_id: [close1, close2, ...]} (oldest first)
  ↓ Valkey.set(key, value, ex=900)
  ↓
  Response: { data: {...}, meta: { days_requested: 14, missing: [] } }
  ↓ TanStack Query caches for 15min
  ↓ SparklineCellRenderer draws 60×16 SVG per row
```

---

## 7. Architecture Decisions

### ADR-0108-1: TRADE type + TradeSide over frontend fix

**Decision**: Add `TRADE` to `TransactionType` and a `TradeSide` enum rather than fixing the frontend to send `"BUY"` directly.

**Rationale**: The frontend design correctly separates "what type of activity is this" (a trade) from "which side" (buy or sell). This is how institutional systems model transactions — a single TRADE type with a side field. Fixing the frontend to send `"BUY"` directly would conflate legacy BUY records (from SnapTrade imports) with manually-entered trades, making it impossible to distinguish them in analytics or display.

**Trade-off**: Requires a DB migration (0021) and more code change than the minimal fix, but produces a cleaner data model.

### ADR-0108-2: Client-side top-movers derivation

**Decision**: `useTopMovers` derives contributors/detractors from the already-loaded `enrichedHoldings + quotes` with no additional API call.

**Rationale**: The holdings + quotes data is already on the client (loaded by `usePortfolioBundle` + `usePortfolioData`). An S9 endpoint for "top movers" would duplicate computation already possible client-side. At ≤ 50 holdings, the client sort is < 1ms.

**Trade-off**: Client-side derivation cannot use server-side sorting/pagination. Acceptable at ≤ 50 holdings; a dedicated endpoint is flagged as a follow-up for large books.

### ADR-0108-3: Sparkline batch via S9 fanout, not a new S1 or S3 endpoint

**Decision**: `GET /v1/market/sparklines` lives in S9 and fans out to S3's existing per-ticker OHLCV endpoints.

**Rationale**: S3 already exposes `GET /api/v1/ohlcv/{ticker}` with a `days` param. Building a new S3 batch endpoint would duplicate the caching and aggregation logic that S9 is already responsible for (see sector-breakdown, risk-metrics). The fan-out pattern is consistent with the established S9 composition pattern.

**Trade-off**: Adds N sub-requests per sparkline call. Mitigated by Valkey TTL 900s and max 50 instruments.

### ADR-0108-4: Keep tabs, redesign Holdings tab contents only

**Decision**: Preserve the HOLDINGS | TRANSACTIONS | ANALYTICS | WATCHLIST tab bar; redesign the Holdings tab to the FR-3 "Anchored table" layout.

**Rationale**: Removing tabs would require moving Transactions, Analytics, and Watchlist content to separate routes, which is a larger navigation change outside the scope of this PRD. The user confirmed this is the right trade-off.

---

## 8. Security Analysis

| Threat | Mitigation |
|--------|-----------|
| Forged instrument_ids in sparkline batch | S9 validates each as UUID; non-UUIDs return 422; S3 ticker lookup will simply return no data for unknown IDs |
| Over-fetching sparklines (> 50 instruments) | 400 enforced at S9 before any S3 calls |
| TRADE transaction for another user's portfolio | `RecordTransactionUseCase` verifies `owner_id == portfolio.owner_user_id`; 403 on mismatch |
| trade_side bypassing direction accounting | Route handler overwrites `direction` from `trade_side`; the body `direction` field is ignored for TRADE type |

---

## 9. Failure Modes

| Failure | Impact | Mitigation |
|---------|--------|-----------|
| S3 OHLCV unavailable during sparkline batch | Some/all instrument_ids in `meta.missing`; SPARK column shows `—` | Graceful degradation in SparklineCellRenderer; no error toast |
| Valkey unavailable for sparkline cache | Cold path on every request; latency 200–800ms | Fail-open: route proceeds without cache; Valkey error logged but not surfaced to user |
| SPY data unavailable for PerformanceChartPanel | Benchmark series not rendered; portfolio series still shown | PerformanceChartPanel renders with portfolio only; SPY label hidden when series null |
| trade_side validation fails (schema) | 422 returned to frontend | AddPositionDialog catches 422 and shows field-level error via react-hook-form |
| DB migration 0021 fails mid-deploy | Transactions with TRADE type would fail at DB insert | Migration is additive-only (new nullable column); rollback via downgrade() is safe |

---

## 10. Scalability

| Concern | Estimate | Mitigation |
|---------|----------|-----------|
| Sparkline fan-out latency | 14 parallel S3 calls × 50ms each = ~50ms with gather | Valkey TTL 900s reduces cold-path rate to < 1/15min per user |
| Holdings table render at 40+ positions | AG Grid virtualises rows; SPARK SVGs are 60×16 inline strings | No change from current AG Grid usage |
| Concentration strip data at 40 positions | Computed by S1, cached in Valkey 300s | No change |

---

## 11. Test Strategy

### Unit tests — S1 (backend)

| Test | What it verifies | Priority |
|------|-----------------|----------|
| `test_transaction_type_trade_valid` | `TransactionType("TRADE")` resolves correctly | HIGH |
| `test_trade_side_enum_values` | `TradeSide("BUY")` and `TradeSide("SELL")` round-trip | HIGH |
| `test_transaction_entity_trade_side_invariant` | Entity raises ValueError when TRADE + trade_side=None | HIGH |
| `test_transaction_entity_non_trade_side_invariant` | Entity raises ValueError when BUY + trade_side="BUY" | HIGH |
| `test_record_transaction_request_trade_requires_side` | Schema raises 422 when transaction_type=TRADE and trade_side absent | HIGH |
| `test_record_transaction_request_invalid_type` | Schema raises 422 (not 500) for unknown transaction_type value | HIGH |
| `test_route_trade_buy_maps_to_inflow` | Route handler sets direction=INFLOW for TRADE+BUY | HIGH |
| `test_route_trade_sell_maps_to_outflow` | Route handler sets direction=OUTFLOW for TRADE+SELL | HIGH |

### Integration tests — S1

| Test | Infrastructure | What it verifies |
|------|---------------|-----------------|
| `test_post_transaction_trade_buy` | Postgres | TRADE+BUY persists with trade_side="BUY", direction="INFLOW" |
| `test_post_transaction_trade_buy_returns_201` | Postgres | End-to-end POST returns 201 with trade_side in response |
| `test_post_transaction_invalid_type_returns_422` | Postgres | Unknown type → 422, not 500 |
| `test_migration_0021_nullable_column` | Postgres | Old rows remain valid after migration; new column is NULL |

### Unit tests — S9 (api-gateway)

| Test | What it verifies | Priority |
|------|-----------------|----------|
| `test_sparklines_returns_data_map` | Mock S3 → sparklines endpoint returns `{data: {...}, meta: {...}}` | HIGH |
| `test_sparklines_missing_instrument_in_meta` | S3 returns empty for one ID → appears in `meta.missing` | HIGH |
| `test_sparklines_max_50_instruments` | 51 instrument_ids → 400 | HIGH |
| `test_sparklines_valkey_cache_hit` | Second call returns cached response without S3 sub-calls | MEDIUM |
| `test_sparklines_valkey_unavailable_graceful` | Valkey failure → cold path proceeds | MEDIUM |

### Frontend unit tests — Vitest

| Test | What it verifies | Priority |
|------|-----------------|----------|
| `SparklineCellRenderer renders SVG from array` | Non-empty array → svg element | HIGH |
| `SparklineCellRenderer renders dash on empty` | Empty array → "—" | HIGH |
| `AssetTypeCellRenderer renders E chip` | equity asset type | HIGH |
| `useTopMovers derives winners and losers` | Correct sort order from mock holdings | HIGH |
| `PortfolioKPIStrip renders 8 cells` | Extension to 8 cells visible | MEDIUM |
| `ExposureCurrencyStrip renders all 5 cells` | All cell labels visible | MEDIUM |
| `ConcentrationSectorTeaseStrip renders HHI badge` | HHI < 1000 → "low" badge | MEDIUM |
| `PerformanceChartPanel renders collapse toggle` | Toggle click collapses panel | MEDIUM |
| `AddPositionDialog sends trade_side not direction` | API call includes trade_side: "BUY" | HIGH |
| `AddPositionDialog shows 422 field error` | Mock 422 → field error text shown | HIGH |

---

## 12. Migration Plan

### Phase 1 — Wave 1: Backend fix (unblocks add-position, no frontend changes)

1. Add `TRADE` to `TransactionType`, `TradeSide` enum, `trade_side` field to `Transaction` entity.
2. Update `TransactionModel`, `RecordTransactionCommand`, `RecordTransactionRequest` schema.
3. Alembic migration 0021.
4. Update route handler mapping.
5. Unit + integration tests.
6. Deploy S1.

### Phase 2 — Wave 2: Sparkline batch endpoint (S9)

1. Implement `GET /v1/market/sparklines` in S9.
2. Unit tests.
3. Deploy S9.

### Phase 3 — Wave 3: Holdings tab redesign (frontend)

1. New strips: ExposureCurrencyStrip, ConcentrationSectorTeaseStrip, SectorAllocationBar, HoldingsTableChrome.
2. KPIStrip extension (8 cells).
3. New hooks: useTopMovers, useHoldingsSeries.
4. Update page.tsx layout.

### Phase 4 — Wave 4: Table + chart improvements (frontend)

1. SemanticHoldingsTable: SPARK + ASSET columns, SparklineCellRenderer, AssetTypeCellRenderer.
2. PerformanceChartPanel (replaces EquityCurveChart on Holdings tab).
3. EquityCurveChart axis-label fix (Analytics tab).
4. BottomStripCluster + ContributorsStrip + RecentActivityStrip.

### Phase 5 — Wave 5: UX polish + frontend bug fixes

1. PortfolioPageHeader: button size + ROOT inline text.
2. AddPositionDialog: send `trade_side` not `direction`.
3. Update `lib/api/portfolios.ts` `addPosition()`.
4. E2E tests: add-position golden path, sparkline renders.

### Rollback strategy

- Migration 0021 is reversible (`downgrade()` drops column + constraint).
- Frontend waves are independent; a bad frontend deploy reverts to previous build without S1 impact.
- No Kafka schema changes; no event consumer breaks.

---

## 13. Observability

| Signal | What | Where |
|--------|------|-------|
| Counter | `portfolio.transaction.trade_type_used{type=TRADE}` | S1 route handler, on 201 |
| Counter | `api_gateway.sparklines.cache_hit` / `cache_miss` | S9 sparklines route |
| Histogram | `api_gateway.sparklines.duration_ms` | S9 sparklines route |
| Log (INFO) | `transaction_recorded trade_side=BUY portfolio_id=…` | S1 RecordTransactionUseCase |
| Log (WARN) | `sparkline_fetch_failed instrument_id=… error=…` | S9 per-instrument sub-call |

---

## 14. Open Questions

| # | Question | Classification | Resolution |
|---|----------|---------------|------------|
| OQ-001 | Add TRADE + TradeSide vs. fix frontend to send BUY | RESOLVED | Option C: add TRADE + TradeSide (§6.5) |
| OQ-002 | Redesign scope: targeted vs. full FR-3 | RESOLVED | Full FR-3 with tab bar preserved (§6.6) |
| OQ-003 | Tab structure: keep or remove | RESOLVED | Keep 4-tab bar; redesign Holdings tab only |
| OQ-004 | EquityCurveChart retirement | RESOLVED | Replaced on Holdings tab by PerformanceChartPanel; kept in Analytics tab with axis-label fix |
| OQ-005 | Sparkline batch in scope | RESOLVED | Yes, `GET /v1/market/sparklines` added to S9 (§6.2) |

No unresolved BLOCKING open questions.

---

## 15. Estimation

| Wave | Service | Complexity | Estimate |
|------|---------|------------|----------|
| W1 — Backend enum + migration | S1 | Low | 0.5 day |
| W2 — Sparkline batch endpoint | S9 | Low-Medium | 1 day |
| W3 — Holdings tab layout redesign | frontend | Medium | 1.5 days |
| W4 — Table + chart components | frontend | Medium | 2 days |
| W5 — UX polish + E2E tests | frontend | Low | 1 day |
| **Total** | | | **~6 developer-days** |
