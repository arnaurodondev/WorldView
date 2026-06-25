# PLAN-0108 — Portfolio Overview Redesign + Transaction Type Fix

> **PRD**: [docs/specs/0108-portfolio-overview-redesign.md](../specs/0108-portfolio-overview-redesign.md)
> **Status**: pending
> **Author**: agent-plan
> **Date**: 2026-06-08
> **Branch**: `feat/plan-0108-portfolio-redesign` (create from `main`)
> **Services**: S1 (portfolio), S9 (api-gateway), worldview-web
> **Total waves**: 5 | **Total tasks**: 28 | **Estimated effort**: ~6 developer-days

---

## Overview

This plan resolves three active pain classes on the portfolio page:

1. **Hard 500 crash on Add Position** (Wave 1) — `TransactionType` enum is missing `TRADE`; the
   frontend sends `transaction_type: "TRADE"` and S1 raises `ValueError` before any DB write.
2. **No sparkline data for the SPARK column** (Wave 2) — a new `GET /v1/market/sparklines` S9
   batch endpoint fans out to S3 OHLCV per-ticker endpoints, Valkey-cached 15 min.
3. **Holdings tab has no above-fold density** (Waves 3–5) — new strips, a redesigned Holdings tab
   layout, new hooks, sparkline + asset-type columns in the table, and UX polish.

**Dependency order**: W1 is self-contained; W2 requires nothing from W1; W3 depends on W2 (hook
imports the sparklines client); W4 depends on W3 (table chrome must exist before adding columns);
W5 depends on W4 (button size change is in the same header that already wires the dialog).

**Critical path**: W1 → (parallel: W2) → W3 → W4 → W5

---

## Pre-flight Context

| Item | Value |
|------|-------|
| Current Alembic head (portfolio) | `0020_add_transaction_description.py` |
| Next migration | `0021_add_transaction_trade_side.py` |
| Next plan ID | PLAN-0108 (confirmed from TRACKING.md) |
| `TransactionType` current members | BUY, SELL, DIVIDEND, DEPOSIT, WITHDRAWAL, FEE, INTEREST |
| Existing SPARK cell renderer | `components/portfolio/cells/SparklineCellRenderer.tsx` — **exists (53 LOC, stub)** |
| Existing ASSET cell renderer | `components/portfolio/cells/AssetTypeCellRenderer.tsx` — **exists (132 LOC, full)** |
| `useTopMovers` hook | `features/portfolio/hooks/useTopMovers.ts` — **exists** |
| `useHoldingsSeries` hook | **does NOT exist** — must be created in W3 |
| `BottomStripCluster` | **does NOT exist** — must be created in W4 |
| `GET /v1/market/sparklines` | **does NOT exist** — must be created in W2 |
| `ExposureCurrencyStrip` | `components/portfolio/ExposureCurrencyStrip.tsx` — **exists (121 LOC)** |
| `ConcentrationSectorTeaseStrip` | `components/portfolio/ConcentrationSectorTeaseStrip.tsx` — **exists (105 LOC)** |
| `PerformanceChartPanel` | `components/portfolio/PerformanceChartPanel.tsx` — **exists (386 LOC)** |
| `SectorAllocationBar` | `components/portfolio/SectorAllocationBar.tsx` — **exists (70 LOC)** |
| `HoldingsTableChrome` | `components/portfolio/HoldingsTableChrome.tsx` — **exists (110 LOC)** |
| `ContributorsStrip` | `components/portfolio/ContributorsStrip.tsx` — **exists (182 LOC)** |
| `RecentActivityStrip` | `components/portfolio/RecentActivityStrip.tsx` — **exists (201 LOC)** |
| `PortfolioPageHeader` | already uses `text-[11px]` — confirm ROOT inline text and hover states |

> **Implementation note**: several components the PRD marks as NEW already exist in the codebase
> from prior PLAN-0089 work. Each task in Waves 3–5 must audit the existing component against the
> PRD spec before choosing between (a) adopt as-is, (b) extend/fix, or (c) replace. Do NOT
> re-implement a component that already satisfies the PRD spec.

---

## Architecture Compliance Requirements

All waves must satisfy:

| Rule | What it means for this plan |
|------|-----------------------------|
| R25 | API router in S1 must not import from `infrastructure/`; new route logic goes through `RecordTransactionUseCase` |
| R27 | `ListTransactionsUseCase` already uses `ReadUoWDep`; any new read use case must too |
| R10 | `Transaction.id` already uses `new_uuid()` (UUIDv7) — do not change |
| R11 | All timestamps UTC; `executed_at` keeps `DateTime(timezone=True)` in migration |
| R1  | Every behavior change needs unit + integration tests in the same commit |
| R3  | Update `docs/services/portfolio.md` and `docs/services/api-gateway.md` on W1+W2 completion |
| NFR-6 | Migration 0021 must be nullable, no server_default, backward-compatible |

---

## Wave 1 — S1 Backend: TRADE Enum + Migration + Route Fix

**Goal**: Fix the 500 crash on Add Position. No frontend changes in this wave.
**Effort**: 0.5 dev-day | **Depends on**: nothing | **Blocks**: W5 (AddPositionDialog client fix)

### Task T-1-01 — Add `TRADE` to `TransactionType` and create `TradeSide` enum

| Attribute | Value |
|-----------|-------|
| Type | domain change |
| Depends on | — |
| Blocks | T-1-02, T-1-03, T-1-04 |
| Target files | `services/portfolio/src/portfolio/domain/enums.py` |
| PRD ref | FR-1, FR-2, §6.5 |

**What to build**:
- Add `TRADE = "TRADE"` to `TransactionType` StrEnum (after `INTEREST`).
- Add new `TradeSide` StrEnum with `BUY = "BUY"` and `SELL = "SELL"`.

**Tests to write**:
- `tests/unit/domain/test_enums.py`:
  - `test_transaction_type_trade_valid`: `TransactionType("TRADE") == TransactionType.TRADE`
  - `test_trade_side_enum_values`: `TradeSide("BUY")` and `TradeSide("SELL")` round-trip correctly
  - `test_trade_side_rejects_invalid`: `TradeSide("HOLD")` raises `ValueError`

**Acceptance criteria**:
- [ ] `TransactionType.TRADE` resolves without error
- [ ] `TradeSide.BUY` and `TradeSide.SELL` resolve
- [ ] No existing enum tests broken

---

### Task T-1-02 — Add `trade_side` to `Transaction` entity with invariant

| Attribute | Value |
|-----------|-------|
| Type | domain change |
| Depends on | T-1-01 |
| Blocks | T-1-05 |
| Target files | `services/portfolio/src/portfolio/domain/entities/transaction.py` |
| PRD ref | FR-3, §6.5 |

**What to build**:
- Add `trade_side: TradeSide | None = None` field to `Transaction` dataclass (after `settlement_date`).
- Add `__post_init__` method with two invariant assertions:
  ```python
  def __post_init__(self) -> None:
      if self.transaction_type == TransactionType.TRADE and self.trade_side is None:
          raise ValueError("trade_side must be set for TRADE transactions")
      if self.transaction_type != TransactionType.TRADE and self.trade_side is not None:
          raise ValueError("trade_side must be None for non-TRADE transactions")
  ```
- Import `TradeSide` from `portfolio.domain.enums`.

**Tests to write**:
- `tests/unit/domain/test_transaction_entity.py`:
  - `test_transaction_entity_trade_buy_valid`: TRADE + TradeSide.BUY builds without error
  - `test_transaction_entity_trade_sell_valid`: TRADE + TradeSide.SELL builds without error
  - `test_transaction_entity_trade_side_invariant`: TRADE + `trade_side=None` raises `ValueError`
  - `test_transaction_entity_non_trade_side_invariant`: BUY type + `trade_side=TradeSide.BUY` raises `ValueError`
  - `test_transaction_entity_non_trade_no_side`: BUY type + `trade_side=None` builds without error

**Acceptance criteria**:
- [ ] TRADE + trade_side builds; TRADE without trade_side raises; non-TRADE with trade_side raises
- [ ] All existing `Transaction` construction sites in tests still pass (trade_side defaults to None)

---

### Task T-1-03 — Add `trade_side` to `RecordTransactionCommand` and `RecordTransactionRequest`

| Attribute | Value |
|-----------|-------|
| Type | application + schema change |
| Depends on | T-1-01 |
| Blocks | T-1-05 |
| Target files | `services/portfolio/src/portfolio/application/use_cases/record_transaction.py`, `services/portfolio/src/portfolio/api/schemas.py` |
| PRD ref | FR-4, FR-5, §6.5 |

**What to build**:

*`RecordTransactionCommand`*:
- Add `trade_side: TradeSide | None = None` field (after `settlement_date`).

*`RecordTransactionRequest`* (schema changes):
- Change `transaction_type: str` → `transaction_type: Literal["BUY","SELL","DIVIDEND","DEPOSIT","WITHDRAWAL","FEE","INTEREST","TRADE"]`
- Change `direction: str` → `direction: Literal["INFLOW","OUTFLOW"]`
- Add `trade_side: Literal["BUY","SELL"] | None = None`
- Add `@model_validator(mode="after")`:
  ```python
  @model_validator(mode="after")
  def validate_trade_side(self) -> "RecordTransactionRequest":
      if self.transaction_type == "TRADE" and self.trade_side is None:
          raise ValueError("trade_side is required when transaction_type is TRADE")
      return self
  ```

*`RecordTransactionResponse`*:
- Add `trade_side: str | None = None` field.

**Tests to write**:
- `tests/unit/api/test_schemas.py`:
  - `test_record_transaction_request_trade_requires_side`: Pydantic raises `ValidationError` (422) when `transaction_type=TRADE` and `trade_side` absent
  - `test_record_transaction_request_invalid_type`: `transaction_type="UNKNOWN"` raises `ValidationError`
  - `test_record_transaction_request_invalid_direction`: `direction="BUY"` (not INFLOW/OUTFLOW) raises `ValidationError`
  - `test_record_transaction_request_trade_buy_valid`: TRADE + BUY validates successfully
  - `test_record_transaction_request_non_trade_no_side_valid`: BUY + no trade_side + direction=INFLOW validates

**Acceptance criteria**:
- [ ] `transaction_type="UNKNOWN"` → 422 (not 500)
- [ ] `transaction_type="TRADE"` + missing `trade_side` → 422
- [ ] `direction="BUY"` → 422
- [ ] `RecordTransactionResponse` includes `trade_side` field

---

### Task T-1-04 — Add `trade_side` column to `TransactionModel` ORM

| Attribute | Value |
|-----------|-------|
| Type | infrastructure change |
| Depends on | T-1-01 |
| Blocks | T-1-06 |
| Target files | `services/portfolio/src/portfolio/infrastructure/db/models/transaction.py` |
| PRD ref | §6.5 ORM Model |

**What to build**:
- Add to `TransactionModel`:
  ```python
  trade_side: Mapped[str | None] = mapped_column(
      String(4), nullable=True, default=None,
      comment="BUY or SELL for TRADE-type rows; NULL for all others",
  )
  ```
- Add `String` to the SQLAlchemy imports.

**Tests to write**:
- No new unit tests needed here (ORM model is integration-tested via T-1-07).

**Acceptance criteria**:
- [ ] `TransactionModel` has `trade_side` mapped column
- [ ] `nullable=True`, no `server_default`

---

### Task T-1-05 — Update route handler to map TRADE+side → direction

| Attribute | Value |
|-----------|-------|
| Type | API route change |
| Depends on | T-1-02, T-1-03 |
| Blocks | — |
| Target files | `services/portfolio/src/portfolio/api/routes/transaction.py` |
| PRD ref | FR-6, §6.5 Route handler |

**What to build**:
- Replace `record_transaction` route handler body (lines 54–75) with the new logic:
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
          tenant_id=x_tenant_id,
          portfolio_id=body.portfolio_id,
          owner_id=x_owner_id,
          instrument_id=body.instrument_id,
          transaction_type=TransactionType(body.transaction_type),
          direction=direction,
          trade_side=trade_side,
          quantity=body.quantity,
          price=body.price,
          fees=body.fees,
          currency=body.currency,
          executed_at=body.executed_at,
          external_ref=body.external_ref,
          idempotency_key=idempotency_key,
      ),
      uow,
  )
  ```
- Update `RecordTransactionResponse(...)` call to include `trade_side=str(t.trade_side) if t.trade_side else None`.
- Move the `from portfolio.domain.enums import ...` to the module top level (remove the local import).

**Architecture compliance**: The route handler only calls `RecordTransactionUseCase` — no direct infrastructure imports (R25).

**Tests to write**:
- `tests/unit/api/test_transaction_routes.py`:
  - `test_route_trade_buy_maps_to_inflow`: mock use case; POST with TRADE+BUY; assert `direction=INFLOW` in command
  - `test_route_trade_sell_maps_to_outflow`: POST with TRADE+SELL; assert `direction=OUTFLOW`
  - `test_route_non_trade_uses_body_direction`: POST with DEPOSIT+INFLOW; assert body direction forwarded
  - `test_route_returns_trade_side_in_response`: response body includes `trade_side: "BUY"`

**Acceptance criteria**:
- [ ] TRADE+BUY → `direction=INFLOW` forwarded to use case
- [ ] TRADE+SELL → `direction=OUTFLOW` forwarded to use case
- [ ] `trade_side` appears in response
- [ ] No infrastructure imports in the route file (R25)

---

### Task T-1-06 — Alembic migration 0021: add `trade_side` column

| Attribute | Value |
|-----------|-------|
| Type | DB migration |
| Depends on | T-1-04 |
| Blocks | T-1-07 |
| Target files | `services/portfolio/alembic/versions/0021_add_transaction_trade_side.py` |
| PRD ref | NFR-6, §6.4 |

**What to build**:
```python
"""Add trade_side column to transactions table.

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-08
"""

revision = "0021"
down_revision = "0020"

def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column(
            "trade_side",
            sa.String(4),
            nullable=True,
            comment="BUY or SELL for TRADE-type transactions; NULL for all other types",
        ),
    )
    op.create_check_constraint(
        "ck_transactions_trade_side",
        "transactions",
        "trade_side IN ('BUY', 'SELL') OR trade_side IS NULL",
    )

def downgrade() -> None:
    op.drop_constraint("ck_transactions_trade_side", "transactions", type_="check")
    op.drop_column("transactions", "trade_side")
```

**Tests to write**:
- `tests/integration/test_migration_0021.py`:
  - `test_migration_0021_nullable_column`: apply migration; assert `trade_side` column exists with `nullable=True`
  - `test_migration_0021_existing_rows_valid`: seed a row pre-migration; apply; assert row has `trade_side=NULL`
  - `test_migration_0021_check_constraint`: attempt to insert `trade_side='HOLD'`; assert `IntegrityError`
  - `test_migration_0021_downgrade`: apply then downgrade; assert column is gone

**Acceptance criteria**:
- [ ] Migration head advances from 0020 → 0021
- [ ] Column is nullable, no server_default
- [ ] Check constraint enforces BUY|SELL|NULL
- [ ] Downgrade drops column and constraint cleanly

---

### Task T-1-07 — Integration test: POST /api/v1/transactions with TRADE type

| Attribute | Value |
|-----------|-------|
| Type | integration test |
| Depends on | T-1-05, T-1-06 |
| Blocks | — |
| Target files | `services/portfolio/tests/integration/test_record_transaction_trade.py` |
| PRD ref | §11 Integration tests — S1 |

**What to build**: Full integration test suite against a Postgres test DB:
- `test_post_transaction_trade_buy`: POST TRADE+BUY; assert 201 + `trade_side="BUY"` + `direction="INFLOW"` in response; assert DB row has `trade_side='BUY'`
- `test_post_transaction_trade_sell`: POST TRADE+SELL; assert 201 + `direction="OUTFLOW"` in response
- `test_post_transaction_invalid_type_returns_422`: POST with `transaction_type="UNKNOWN"` → 422, not 500
- `test_post_transaction_trade_missing_side_returns_422`: POST TRADE + no `trade_side` → 422

**Acceptance criteria**:
- [ ] All 4 integration tests pass with Postgres running
- [ ] Pre-existing integration tests unbroken

---

### Wave 1 Validation Gate

```bash
cd services/portfolio
python -m pytest tests/unit/ -m unit -v              # all unit tests pass
python -m pytest tests/integration/ -m integration -v  # DB integration tests pass
uvx ruff check src/ tests/
uvx mypy src/ --strict
alembic upgrade head  # migration applies cleanly
alembic downgrade 0020 && alembic upgrade 0021  # round-trip clean
```

**Architecture compliance checklist**:
- [ ] No `from portfolio.infrastructure` in `api/routes/transaction.py` (R25)
- [ ] Migration column is nullable, no server_default (NFR-6, BP-126)
- [ ] All new IDs use `new_uuid()` (R10) — no new IDs in this wave
- [ ] All new datetimes use `DateTime(timezone=True)` (R11) — no new timestamps in this wave
- [ ] `structlog` used, not `logging` (R10)

**Break impact**:
| Component | Impact if W1 broken |
|-----------|---------------------|
| Existing BUY/SELL/DIVIDEND transactions | `direction` field still works (non-TRADE code path unchanged) |
| Frontend Add Position | Remains broken until W5 (currently also broken before W1) |
| SnapTrade brokerage sync | Unaffected — uses different code path (direct `RecordTransactionCommand`) |

**Regression guardrails**:
- Run `python -m pytest tests/ -x` before committing; 0 failures required.
- All existing `TransactionType("BUY")` usages still resolve (TRADE is additive).

---

## Wave 2 — S9 API Gateway: `GET /v1/market/sparklines` Endpoint

**Goal**: New batch OHLCV sparkline endpoint. Fans out to S3, Valkey-cached 15 min.
**Effort**: 1 dev-day | **Depends on**: nothing (parallel with W1) | **Blocks**: W3

### Task T-2-01 — Implement `GET /v1/market/sparklines` route handler

| Attribute | Value |
|-----------|-------|
| Type | new S9 API endpoint |
| Depends on | — |
| Blocks | T-2-02, T-2-03 |
| Target files | `services/api-gateway/src/api_gateway/routes/market.py` |
| PRD ref | FR-8, §6.2, ADR-0108-3 |

**What to build**:

Add to `services/api-gateway/src/api_gateway/routes/market.py`:

```python
_SPARKLINES_CACHE_TTL_S = 900  # 15 min — NFR-2
_SPARKLINES_MAX_IDS = 50


@router.get("/market/sparklines")
async def get_market_sparklines(
    request: Request,
    instrument_ids: str = Query(..., description="Comma-separated UUID instrument IDs (max 50)"),
    days: int = Query(default=14, ge=1, le=90),
) -> Response:
    """Batch 14-day closing-price arrays for the SPARK column.

    WHY THIS EXISTS: SemanticHoldingsTable needs a 14-day sparkline per holding.
    A per-row fetch would issue N individual OHLCV requests. This endpoint fans
    out to S3 in parallel (asyncio.gather with return_exceptions=True) and caches
    the full batch at the gateway so the second user with the same holdings gets
    a cache hit.

    WHY Valkey TTL 900s: closing prices change once per trading day. A 15-min
    cache eliminates redundant fan-outs while remaining fresh for intraday users.

    WHY max 50: prevents gateway fan-out abuse; aligns with frontend max holding
    count for this PRD's scope.
    """
    ...
```

Implementation steps inside the handler:
1. Parse `instrument_ids.split(",")` → deduplicate → validate each as UUID (raise 400 if empty; raise 400 if > 50; raise 422 if non-UUID).
2. Build Valkey cache key: `f"sparklines:v1:{':'.join(sorted(ids))}:{days}"`.
3. Attempt Valkey read (fail-open on exception).
4. On cache miss: look up tickers from `request.app.state.clients.market_data` via `GET /api/v1/instruments/batch` or use instrument_id-to-ticker resolution (check existing pattern in `routes/instruments.py`).
5. Fan out: `asyncio.gather(*[fetch_ohlcv(ticker, days) for ticker in tickers], return_exceptions=True)`.
6. Each sub-call wraps `GET /api/v1/ohlcv/{ticker}?timeframe=1d&days={days}`; extract `close` prices oldest-first; on exception add `instrument_id` to `missing` list.
7. Build response: `{"data": {instrument_id: [closes...]}, "meta": {"days_requested": days, "fetched_at": utc_now().isoformat(), "missing": [...]}}`.
8. Serialize to JSON; attempt Valkey write (fail-open).
9. Return `Response(content=json_bytes, media_type="application/json")`.

Add observability:
- `logger.info("sparklines_cache_hit", n_ids=len(ids), days=days)` on hit
- `logger.warning("sparkline_fetch_failed", instrument_id=..., error=...)` per failure
- Prometheus counter: `api_gateway.sparklines.cache_hit` and `cache_miss` (use existing metrics pattern)

**Acceptance criteria**:
- [ ] Route registered at `GET /v1/market/sparklines`
- [ ] Requires JWT auth (standard `OIDCAuthMiddleware` path)
- [ ] Returns `{data: {uuid: [float]}, meta: {days_requested, fetched_at, missing: [uuid]}}`
- [ ] 400 on empty or >50 instrument_ids
- [ ] 422 on non-UUID values
- [ ] Fail-open on Valkey unavailability

---

### Task T-2-02 — Register sparklines route in S9 router

| Attribute | Value |
|-----------|-------|
| Type | wiring |
| Depends on | T-2-01 |
| Blocks | T-2-03 |
| Target files | `services/api-gateway/src/api_gateway/app.py` (or wherever `market` router is included) |
| PRD ref | §6.2 |

**What to build**:
- Confirm `market.router` is already included in the main app (it is — existing screener routes use it).
- No additional wiring needed if route is added to the existing `market.py` module.
- Add `GET /v1/market/sparklines` to the S9 endpoint list in `docs/services/api-gateway.md`.

**Acceptance criteria**:
- [ ] `GET /v1/market/sparklines` appears in S9 OpenAPI docs (`/docs`)
- [ ] `docs/services/api-gateway.md` updated

---

### Task T-2-03 — Unit tests for sparklines endpoint

| Attribute | Value |
|-----------|-------|
| Type | unit tests |
| Depends on | T-2-01 |
| Blocks | — |
| Target files | `services/api-gateway/tests/unit/routes/test_sparklines.py` |
| PRD ref | §11 Unit tests — S9 |

**Tests to write**:
- `test_sparklines_returns_data_map`: mock S3 OHLCV per-ticker; assert response `data` keyed by instrument_id with list of floats
- `test_sparklines_missing_instrument_in_meta`: one S3 sub-call raises; that instrument_id appears in `meta.missing`
- `test_sparklines_max_50_instruments`: 51 comma-separated UUIDs → 400
- `test_sparklines_empty_instrument_ids`: empty `instrument_ids` param → 400
- `test_sparklines_invalid_uuid_returns_422`: non-UUID value → 422
- `test_sparklines_valkey_cache_hit`: prime mock Valkey → assert S3 not called on second request
- `test_sparklines_valkey_unavailable_graceful`: `valkey.get()` raises → cold path proceeds, S3 called normally

**Acceptance criteria**:
- [ ] All 7 tests pass
- [ ] Mocks S3 client at `request.app.state.clients.market_data.get`
- [ ] No real network calls in unit tests

---

### Wave 2 Validation Gate

```bash
cd services/api-gateway
python -m pytest tests/unit/ -v
uvx ruff check src/ tests/
uvx mypy src/ --strict
```

**Architecture compliance checklist**:
- [ ] Route is protected by `OIDCAuthMiddleware` (JWT required)
- [ ] Valkey failure is fail-open (no raised exception propagates to user)
- [ ] `asyncio.gather(..., return_exceptions=True)` used (not bare gather — BP-114)
- [ ] `structlog` logging only (R10)
- [ ] No direct DB access in S9 (stateless — R7)

**Break impact**:
| Component | Impact if W2 broken |
|-----------|---------------------|
| W3 `useHoldingsSeries` hook | Hook returns empty; SPARK column degrades to `—` (graceful) |
| Existing market routes | None — new route only |

**Regression guardrails**:
- Existing api-gateway test suite must pass unchanged.
- Rate limit: 60 req/min per user (confirm in existing `RateLimitMiddleware` config).

---

## Wave 3 — Frontend: New Hooks + Holdings Tab Layout

**Goal**: Wire `useHoldingsSeries`, confirm/fix existing strip components, assemble the Holdings tab layout.
**Effort**: 1.5 dev-days | **Depends on**: W2 (sparklines endpoint) | **Blocks**: W4

### Task T-3-01 — Create `useHoldingsSeries` hook

| Attribute | Value |
|-----------|-------|
| Type | new hook |
| Depends on | W2 (endpoint must exist) |
| Blocks | T-3-04, T-4-01 |
| Target files | `apps/worldview-web/features/portfolio/hooks/useHoldingsSeries.ts` |
| PRD ref | FR-21, §6.6 New hooks |

**What to build** (~100 LOC):
```typescript
/**
 * useHoldingsSeries — fetches 14-day sparkline series for all holdings.
 *
 * WHY THIS EXISTS: SemanticHoldingsTable SPARK column needs 14-day close arrays
 * per instrument. A per-row fetch would cause N individual network calls; this
 * hook issues one batch request and returns a Record keyed by instrument_id.
 *
 * WHY staleTime 15min: sparkline prices change once per trading day. A 15-min
 * cache avoids redundant re-fetches when the user tabs away and back.
 *
 * GRACEFUL DEGRADATION: on error or partial miss, SparklineCellRenderer
 * renders "—" for any instrument_id absent from the returned Record.
 */
export function useHoldingsSeries(
  instrumentIds: string[],
  enabled = true,
): {
  series: Record<string, number[]>;
  isLoading: boolean;
  isError: boolean;
} { ... }
```

TanStack Query config: `staleTime: 15 * 60 * 1000`, `gcTime: 30 * 60 * 1000`, `retry: 1`, `enabled: enabled && instrumentIds.length > 0`.

Query key: `["holdings-series", sortedIds.join(",")]`.

API call: `GET /v1/market/sparklines?instrument_ids=${ids}&days=14` via existing gateway client.

**Tests to write** (`features/portfolio/hooks/__tests__/useHoldingsSeries.test.ts`):
- `useHoldingsSeries returns series keyed by instrument_id`: mock API → assert `series` populated
- `useHoldingsSeries returns empty on error`: mock 500 → assert `series = {}`, `isError = true`
- `useHoldingsSeries disabled when no ids`: `instrumentIds = []` → no query fired

**Acceptance criteria**:
- [ ] Hook exists and exports `{series, isLoading, isError}`
- [ ] Returns `Record<string, number[]>` from `/v1/market/sparklines`
- [ ] TanStack Query staleTime 15 min, retry 1

---

### Task T-3-02 — Audit and fix `ExposureCurrencyStrip`

| Attribute | Value |
|-----------|-------|
| Type | audit + fix |
| Depends on | — |
| Blocks | T-3-05 |
| Target files | `apps/worldview-web/components/portfolio/ExposureCurrencyStrip.tsx` |
| PRD ref | FR-11, §6.6 ExposureCurrencyStrip |

**What to build**:
- Read the existing 121 LOC component against PRD spec (INV % · CASH $ · LEV × · β-ADJ · CCY top-2).
- If the existing component satisfies the PRD spec (5 cells, correct labels, correct data binding from `usePortfolioData().exposure`), adopt as-is.
- If gaps exist (missing β-ADJ or CCY cells), extend to add them. β-ADJ is computed client-side: `Σ(position_value × beta) / total_value`, defaulting beta to 1.0.
- Height must be `h-[22px]`.

**Tests to write** (`components/portfolio/__tests__/ExposureCurrencyStrip.test.tsx`):
- `ExposureCurrencyStrip renders all 5 cells`: mock exposure data → assert INV, CASH, LEV, β-ADJ, CCY labels visible

**Acceptance criteria**:
- [ ] Component renders all 5 cells from PRD §6.6 ExposureCurrencyStrip data binding
- [ ] Height is `h-[22px]`

---

### Task T-3-03 — Audit and fix `ConcentrationSectorTeaseStrip`

| Attribute | Value |
|-----------|-------|
| Type | audit + fix |
| Depends on | — |
| Blocks | T-3-05 |
| Target files | `apps/worldview-web/components/portfolio/ConcentrationSectorTeaseStrip.tsx` |
| PRD ref | FR-12, §6.6 ConcentrationSectorTeaseStrip |

**What to build**:
- Read the existing 105 LOC component. Check: HHI badge (low/moderate/high), top-3 %, name count, top-3 sector weights.
- Extend if HHI badge classification or sector top-3 is missing.
- Thresholds: HHI < 1000 → "low", 1000–2500 → "moderate", > 2500 → "high".

**Tests to write**:
- `ConcentrationSectorTeaseStrip renders HHI badge`: HHI < 1000 → badge text "low"
- `ConcentrationSectorTeaseStrip renders moderate badge`: HHI 1500 → "moderate"
- `ConcentrationSectorTeaseStrip renders high badge`: HHI 3000 → "high"

**Acceptance criteria**:
- [ ] HHI badge renders correct classification
- [ ] Top-3 sector weights visible
- [ ] Height is `h-[22px]`

---

### Task T-3-04 — Audit `PerformanceChartPanel` against PRD spec

| Attribute | Value |
|-----------|-------|
| Type | audit + fix |
| Depends on | — |
| Blocks | T-3-05 |
| Target files | `apps/worldview-web/components/portfolio/PerformanceChartPanel.tsx` |
| PRD ref | FR-13, §6.6 PerformanceChartPanel visual spec |

**What to build**:
- Audit existing 386 LOC component: height 120px expanded / 22px collapsed; collapse toggle; SPY benchmark series; "Value ($)" y-axis label; period buttons 1W·1M·3M·6M·1Y·All.
- Fix any gaps. The SPY benchmark series source is `GET /v1/portfolios/{id}/value-history` (already exists).
- Confirm `lightweight-charts` is the chart library used.

**Tests to write**:
- `PerformanceChartPanel renders collapse toggle`: click toggle → assert collapsed state
- `PerformanceChartPanel renders at 120px when expanded`: assert height class present

**Acceptance criteria**:
- [ ] Panel height 120px expanded, 22px collapsed
- [ ] Collapse toggle works
- [ ] "Value ($)" y-axis label visible

---

### Task T-3-05 — Assemble Holdings tab layout in `page.tsx`

| Attribute | Value |
|-----------|-------|
| Type | layout assembly |
| Depends on | T-3-01, T-3-02, T-3-03, T-3-04 |
| Blocks | W4 |
| Target files | `apps/worldview-web/app/(app)/portfolio/page.tsx` |
| PRD ref | FR-9, §6.6 Page layout |

**What to build**:
Replace the Holdings tab content with the "Anchored table" layout:
```
flex flex-col h-full bg-background
├── PortfolioPageHeader            (h-9, existing)
├── PortfolioKPIStrip              (h-7, 8 cells — see T-3-06)
├── ExposureCurrencyStrip          (h-[22px])
├── ConcentrationSectorTeaseStrip  (h-[22px])
├── PerformanceChartPanel          (h-[120px] expanded, collapsible)
├── SectorAllocationBar            (h-[22px])
├── HoldingsTableChrome            (h-[22px])
├── SemanticHoldingsTable          (flex-1 min-h-0)
└── BottomStripCluster             (h-24) — placeholder div until W4
```

Remove `PositionBarHeat` from the Holdings tab (move to Analytics tab or retire).
Preserve Analytics tab contents unchanged.

**Tests to write**:
- `Holdings tab renders strip layout`: render page; assert all 6 strip/panel labels visible above table

**Acceptance criteria**:
- [ ] All 8 layout rows render in correct order
- [ ] `PositionBarHeat` removed from Holdings tab
- [ ] Analytics tab unchanged

---

### Task T-3-06 — Extend `PortfolioKPIStrip` to 8 cells

| Attribute | Value |
|-----------|-------|
| Type | component extension |
| Depends on | — |
| Blocks | T-3-05 |
| Target files | `apps/worldview-web/components/portfolio/PortfolioKPIStrip.tsx` |
| PRD ref | FR-10, §6.6 |

**What to build**:
- The existing `PortfolioKPIStrip.tsx` is 423 LOC. Check current cell count.
- Add cells 7 (Cash $) and 8 (Buying Power $) sourced from `usePortfolioData().exposure.cash` and `.buying_power`.
- Preserve existing 6 cells unchanged.

**Tests to write**:
- `PortfolioKPIStrip renders 8 cells`: mock data with cash + buying_power → assert both cell labels visible

**Acceptance criteria**:
- [ ] KPI strip has 8 cells
- [ ] Cell 7 = Cash value; cell 8 = Buying Power value
- [ ] Existing 6 cells unaffected

---

### Wave 3 Validation Gate

```bash
cd apps/worldview-web
pnpm vitest run                   # all tests pass
pnpm tsc --noEmit                 # type check clean
pnpm lint                         # ESLint clean
```

**Architecture compliance checklist**:
- [ ] `useHoldingsSeries` calls `GET /v1/market/sparklines` only (not direct S3)
- [ ] No `console.log` statements in committed code
- [ ] All new components use shadcn/ui primitives only (no custom CSS)
- [ ] `staleTime: 15 * 60 * 1000` in `useHoldingsSeries` TanStack Query config

**Break impact**:
| Component | Impact if W3 broken |
|-----------|---------------------|
| SPARK column (W4) | `useHoldingsSeries` missing → SparklineCellRenderer always shows `—` |
| Holdings tab layout | Falls back to previous layout (no crash) |

---

## Wave 4 — Frontend: Table Improvements + Bottom Strip Cluster

**Goal**: Add SPARK and ASSET columns to SemanticHoldingsTable; confirm/fix cell renderers; build BottomStripCluster; fix EquityCurveChart axis labels.
**Effort**: 2 dev-days | **Depends on**: W3 | **Blocks**: W5

### Task T-4-01 — Extend `SemanticHoldingsTable` with SPARK and ASSET columns

| Attribute | Value |
|-----------|-------|
| Type | component extension |
| Depends on | T-3-01 (useHoldingsSeries) |
| Blocks | T-4-02, T-4-03 |
| Target files | `apps/worldview-web/components/portfolio/SemanticHoldingsTable.tsx` |
| PRD ref | FR-16, §6.6 Holdings table column spec |

**What to build**:
- Import `useHoldingsSeries` in the component (or accept `series: Record<string, number[]>` as prop — prefer prop injection to keep the component testable).
- Add SPARK column definition (col 8, width 76, center): uses `SparklineCellRenderer`.
- Add ASSET column definition (col 14, width 44, center): uses `AssetTypeCellRenderer`.
- The full 14-column spec from PRD §6.6:
  Ticker(76) · Name(168) · Qty(78) · Avg Cost(86) · Last(86) · Day Δ$(82) · Day Δ%(70) · **Spark(76)** · Mkt Value(96) · Unreal$(90) · Unreal%(70) · Weight(70) · Sector(80) · **Asset(44)**.
- Total 1152px — verify against current column widths.
- Row height: 22px (already set).

**Tests to write**:
- `SemanticHoldingsTable renders SPARK column header`: render with mock columns → "SPARK" visible
- `SemanticHoldingsTable renders ASSET column header`: "ASSET" visible

**Acceptance criteria**:
- [ ] 14 columns in spec order
- [ ] SPARK column uses `SparklineCellRenderer`
- [ ] ASSET column uses `AssetTypeCellRenderer`
- [ ] Row height 22px preserved

---

### Task T-4-02 — Extend `SparklineCellRenderer` to consume series data

| Attribute | Value |
|-----------|-------|
| Type | component extension |
| Depends on | T-4-01 |
| Blocks | — |
| Target files | `apps/worldview-web/components/portfolio/cells/SparklineCellRenderer.tsx` |
| PRD ref | FR-17, §6.6 |

**What to build**:
- Existing renderer is 53 LOC (stub). Extend to:
  - Accept `data: number[]` prop (close prices array from `useHoldingsSeries`).
  - Render a 60×16 inline SVG path of the closing prices if `data.length >= 2`.
  - Render `—` in `text-muted-foreground` if `data` is empty or undefined.
  - Color: positive trend (last > first) → `var(--color-positive)`, negative → `var(--color-negative)`.

**Tests to write**:
- `SparklineCellRenderer renders SVG from array`: `data=[10,11,12]` → `<svg>` element present
- `SparklineCellRenderer renders dash on empty`: `data=[]` → text "—"
- `SparklineCellRenderer renders dash on undefined`: `data=undefined` → text "—"

**Acceptance criteria**:
- [ ] Non-empty array → SVG rendered (60×16)
- [ ] Empty/undefined → `—`
- [ ] Color-coded by trend direction

---

### Task T-4-03 — Audit `AssetTypeCellRenderer` against PRD spec

| Attribute | Value |
|-----------|-------|
| Type | audit + fix |
| Depends on | — |
| Blocks | T-4-01 |
| Target files | `apps/worldview-web/components/portfolio/cells/AssetTypeCellRenderer.tsx` |
| PRD ref | FR-18, §6.6 |

**What to build**:
- Existing renderer is 132 LOC. Audit: E (equity) / F (fund) / B (bond) / C (crypto) chips.
- Adopt as-is if spec-compliant; fix chip labels if not.

**Tests to write**:
- `AssetTypeCellRenderer renders E chip for equity`: prop `assetType="equity"` → chip text "E"
- `AssetTypeCellRenderer renders F chip for fund`: → "F"

**Acceptance criteria**:
- [ ] E/F/B/C chips render correctly for equity/fund/bond/crypto asset types

---

### Task T-4-04 — Build `BottomStripCluster` component

| Attribute | Value |
|-----------|-------|
| Type | new component |
| Depends on | — (ContributorsStrip and RecentActivityStrip already exist) |
| Blocks | T-4-05 |
| Target files | `apps/worldview-web/components/portfolio/BottomStripCluster.tsx` |
| PRD ref | FR-19, §6.6 |

**What to build** (~60 LOC):
```typescript
/**
 * BottomStripCluster — three equal-width bottom-strip cells.
 *
 * WHY THIS EXISTS: The Holdings tab bottom area is divided into three equal
 * columns: contributors (top movers up), detractors (top movers down), and
 * recent activity. This cluster is a thin flex wrapper that avoids duplicating
 * the layout in page.tsx.
 *
 * Layout: h-24 flex flex-row gap-0 divide-x divide-border
 * - Cell 1 (flex-1): ContributorsStrip (contributors only, winners)
 * - Cell 2 (flex-1): ContributorsStrip (detractors only, losers)
 * - Cell 3 (flex-1): RecentActivityStrip
 */
export function BottomStripCluster({ portfolioId, contributors, detractors }: BottomStripClusterProps) { ... }
```

- Props: `portfolioId: string`, `contributors: Mover[]`, `detractors: Mover[]`
- The `ContributorsStrip` already supports `contributors` and `detractors` props (182 LOC).
- `RecentActivityStrip` already supports `portfolioId` prop.

**Tests to write**:
- `BottomStripCluster renders three cells`: assert three flex sections visible
- `BottomStripCluster passes contributors to ContributorsStrip`: mock contributors → names appear

**Acceptance criteria**:
- [ ] Three equal-width cells in a flex row
- [ ] Height `h-24` (96px)
- [ ] ContributorsStrip + RecentActivityStrip render within their cells

---

### Task T-4-05 — Wire `BottomStripCluster` into Holdings tab

| Attribute | Value |
|-----------|-------|
| Type | layout wiring |
| Depends on | T-4-04 |
| Blocks | — |
| Target files | `apps/worldview-web/app/(app)/portfolio/page.tsx` |
| PRD ref | FR-19, §6.6 |

**What to build**:
- Replace the placeholder `BottomStripCluster` div (from T-3-05) with the real component.
- Source `contributors` and `detractors` from `useTopMovers()` hook (already exists).
- Pass `portfolioId` from `usePortfolioData()`.

**Tests to write**: covered by T-4-04 tests.

**Acceptance criteria**:
- [ ] BottomStripCluster renders at bottom of Holdings tab
- [ ] Contributors/detractors populated from `useTopMovers()`

---

### Task T-4-06 — Fix `EquityCurveChart` axis labels (Analytics tab)

| Attribute | Value |
|-----------|-------|
| Type | component fix |
| Depends on | — |
| Blocks | — |
| Target files | `apps/worldview-web/components/portfolio/EquityCurveChart.tsx` |
| PRD ref | FR-23, §6.6 |

**What to build**:
- Existing component is kept in the Analytics tab (PRD §6.6, Disposition table).
- Add "Value ($)" y-axis label: 9px text, `text-muted-foreground`, absolute-positioned top-left inside chart container.
- Confirm x-axis dates render on tick marks (already provided by `lightweight-charts`).

**Tests to write**:
- `EquityCurveChart renders Value label`: render → "Value ($)" text present

**Acceptance criteria**:
- [ ] "Value ($)" label visible on y-axis
- [ ] Existing chart behavior unaffected (Analytics tab)

---

### Wave 4 Validation Gate

```bash
cd apps/worldview-web
pnpm vitest run
pnpm tsc --noEmit
pnpm lint
```

**Architecture compliance checklist**:
- [ ] `BottomStripCluster` uses only shadcn/ui + existing portfolio components
- [ ] `SparklineCellRenderer` uses inline SVG (no external chart lib for 60×16 spark)
- [ ] No `any` types in new TypeScript without explicit `// eslint-disable-next-line`
- [ ] `useTopMovers` is client-side derivation only — no additional API call (ADR-0108-2)

**Break impact**:
| Component | Impact if W4 broken |
|-----------|---------------------|
| SPARK column | Renders `—` (graceful degradation) |
| BottomStripCluster | Bottom of Holdings tab is empty |
| EquityCurveChart | Analytics tab chart lacks y-axis label (cosmetic) |

**Regression guardrails**:
- `SemanticHoldingsTable` existing tests must pass unchanged.
- `EquityCurveChart` Analytics tab render test must pass.

---

## Wave 5 — Frontend: UX Polish + E2E Tests

**Goal**: Button size fix in PortfolioPageHeader, ROOT inline text, AddPositionDialog sends `trade_side`, API client fix, E2E tests.
**Effort**: 1 dev-day | **Depends on**: W4 (layout complete) | **Blocks**: nothing

### Task T-5-01 — Audit and fix `PortfolioPageHeader` UX polish

| Attribute | Value |
|-----------|-------|
| Type | component fix |
| Depends on | — |
| Blocks | — |
| Target files | `apps/worldview-web/features/portfolio/components/PortfolioPageHeader.tsx` |
| PRD ref | FR-22, §6.6 PortfolioPageHeader changes |

**What to build**:
- The header already uses `text-[11px]` (confirmed in pre-flight). Check:
  - Add Position button: `hover:bg-primary/5` on hover (in addition to existing `hover:border-primary/60`).
  - ROOT disabled state: add `<p className="text-[10px] text-muted-foreground mt-0.5">Select a portfolio to add positions. ALL is read-only.</p>` below portfolio selector when `portfolio?.kind === "root"`.

**Tests to write**:
- `PortfolioPageHeader shows ROOT inline text when kind is root`: render with `portfolio.kind="root"` → "ALL is read-only" text visible
- `PortfolioPageHeader hides ROOT text for non-root portfolio`: `kind="manual"` → text absent

**Acceptance criteria**:
- [ ] `hover:bg-primary/5` on Add Position button
- [ ] ROOT inline text visible only when `kind === "root"`

---

### Task T-5-02 — Fix `addPosition()` in `lib/api/portfolios.ts` to send `trade_side`

| Attribute | Value |
|-----------|-------|
| Type | API client fix |
| Depends on | W1 (S1 now accepts `trade_side`) |
| Blocks | T-5-03 |
| Target files | `apps/worldview-web/lib/api/portfolios.ts` |
| PRD ref | FR-7, §6.5 Frontend API client |

**What to build**:
- In `addPosition()` (line ~543): change the request body from `direction: "BUY"` to `trade_side: "BUY"`.
- Remove the `direction` field from the TRADE request body.
- The `transaction_type: "TRADE"` field is already correct.
- Update inline comment to reflect the new field.

**Tests to write**:
- `addPosition sends trade_side not direction`: spy on `fetch`/HTTP client; assert request body contains `trade_side: "BUY"` and no `direction` field

**Acceptance criteria**:
- [ ] Request body has `trade_side: "BUY"` (not `direction: "BUY"`)
- [ ] `direction` field removed from TRADE body
- [ ] Existing `addTransaction()` function unchanged

---

### Task T-5-03 — `AddPositionDialog` handles 422 field error

| Attribute | Value |
|-----------|-------|
| Type | error handling |
| Depends on | T-5-02 |
| Blocks | — |
| Target files | `apps/worldview-web/features/portfolio/components/AddPositionDialog.tsx` |
| PRD ref | §9 Failure modes — trade_side validation fails |

**What to build**:
- Confirm `AddPositionDialog` catches 422 responses and shows field-level error via `react-hook-form`.
- If the existing `catch` block only shows a toast, add `form.setError("root", { message: detail })` to surface the server error in the form.

**Tests to write**:
- `AddPositionDialog shows 422 field error`: mock API to return 422 with `detail="trade_side is required"`; assert error text visible in dialog
- `AddPositionDialog sends trade_side BUY on submit`: spy on `gw.addPosition`; assert called with `trade_side: "BUY"`

**Acceptance criteria**:
- [ ] 422 response surfaces error text in the dialog (not just a toast)
- [ ] Submit button calls `addPosition` with `trade_side: "BUY"`

---

### Task T-5-04 — E2E tests: add-position golden path + sparkline renders

| Attribute | Value |
|-----------|-------|
| Type | E2E tests |
| Depends on | T-5-02, T-5-03, W4 |
| Blocks | — |
| Target files | `apps/worldview-web/e2e/portfolio-add-position.spec.ts`, `apps/worldview-web/e2e/portfolio-sparklines.spec.ts` |
| PRD ref | NFR-5, §11 |

**What to build**:

`portfolio-add-position.spec.ts`:
- `add position golden path`: log in as seed user → navigate to /portfolio → click Add Position → fill instrument/qty/price/date → submit → assert success toast → assert new holding appears in table (or transaction count increments).
- `add position shows 422 error`: submit with missing required field → assert field error visible.

`portfolio-sparklines.spec.ts`:
- `holdings tab renders SPARK column`: navigate to /portfolio → wait for Holdings tab → assert SPARK column header visible → assert at least one SVG in SPARK cells (or `—` if no data).
- `sparkline degrades gracefully on API error`: mock `/v1/market/sparklines` to 500 → assert SPARK cells show `—` without error toast.

**Acceptance criteria**:
- [ ] Add position E2E passes against dev stack
- [ ] Sparkline column E2E verifies graceful degradation
- [ ] Tests use `page.route()` for mock-API cases

---

### Task T-5-05 — Update documentation

| Attribute | Value |
|-----------|-------|
| Type | docs update |
| Depends on | T-5-02 |
| Blocks | — |
| Target files | `docs/services/portfolio.md`, `docs/services/api-gateway.md` |
| PRD ref | R3 |

**What to build**:
- `docs/services/portfolio.md`: add `TRADE` to `TransactionType` enum table; document `trade_side` field and migration 0021.
- `docs/services/api-gateway.md`: add `GET /v1/market/sparklines` to endpoint table with params, response shape, and TTL.

**Acceptance criteria**:
- [ ] Both docs updated with the W1 and W2 changes
- [ ] Endpoint table in api-gateway.md has the sparklines entry

---

### Wave 5 Validation Gate

```bash
# Backend regression
cd services/portfolio && python -m pytest tests/ -v
cd services/api-gateway && python -m pytest tests/unit/ -v

# Frontend full suite
cd apps/worldview-web
pnpm vitest run
pnpm tsc --noEmit
pnpm lint

# E2E (requires dev stack running)
pnpm playwright test e2e/portfolio-add-position.spec.ts
pnpm playwright test e2e/portfolio-sparklines.spec.ts
```

**Architecture compliance checklist**:
- [ ] `lib/api/portfolios.ts` sends `trade_side` (not `direction`) for TRADE type (FR-7)
- [ ] `AddPositionDialog` handles 422 errors at field level
- [ ] E2E specs use `page.route()` for mock scenarios (not real API)
- [ ] Documentation updated (R3)

**Break impact**:
| Component | Impact if W5 broken |
|-----------|---------------------|
| Add Position flow | Users see old error if addPosition not fixed (W1 fixes server; W5 fixes client) |
| E2E suite | Missing coverage only (no regression) |

**Regression guardrails**:
- Full Vitest suite (≥ 2,000 tests) must pass.
- Existing E2E specs must not be broken by new test files.

---

## Summary Table

| Wave | Service | Tasks | Key Deliverables | Effort | Depends On |
|------|---------|-------|-----------------|--------|------------|
| W1 | S1 | 7 (T-1-01…T-1-07) | TRADE enum, TradeSide, entity invariant, schema tightening, migration 0021, route fix, integration tests | 0.5 day | — |
| W2 | S9 | 3 (T-2-01…T-2-03) | `GET /v1/market/sparklines`, Valkey cache, unit tests | 1 day | — |
| W3 | web | 6 (T-3-01…T-3-06) | `useHoldingsSeries`, strip component audits, Holdings tab layout, KPIStrip 8 cells | 1.5 days | W2 |
| W4 | web | 6 (T-4-01…T-4-06) | SemanticHoldingsTable +SPARK+ASSET, SparklineCellRenderer full impl, BottomStripCluster, EquityCurveChart axis fix | 2 days | W3 |
| W5 | web | 5 (T-5-01…T-5-05) | PortfolioPageHeader ROOT text, addPosition trade_side, AddPositionDialog 422 error, E2E tests, docs | 1 day | W4 |
| **Total** | | **27 tasks** | | **~6 days** | |

---

## Critical Path

```
W1 (0.5d)                     → W5 (1d)
          W2 (1d, parallel)
                    W3 (1.5d) → W4 (2d) → W5 (1d)
```

Minimum elapsed time: 1 + 1.5 + 2 + 1 = **5.5 days** (W1 and W2 run in parallel on day 1).

---

## Risk Register

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| S3 OHLCV endpoint shape differs from expected for sparklines | Medium | Low (graceful degradation) | Check actual S3 OHLCV response in T-2-01 before writing the transform |
| Existing strip components (ExposureCurrencyStrip, etc.) have bugs not caught in audit | Medium | Low (discoverable during W3) | Allocate 30 min per component for visual QA against dev stack |
| Migration 0021 fails on pre-existing rows with `trade_side` CHECK constraint | Low | High | Confirm constraint is `OR trade_side IS NULL` (existing rows have NULL) |
| `lightweight-charts` version incompatibility with PerformanceChartPanel | Low | Medium | Verify chart lib version in `package.json` during T-3-04 audit |
| `BottomStripCluster` and existing `ContributorsStrip` have incompatible props | Low | Low | Read ContributorsStrip props interface before writing BottomStripCluster |
| Frontend E2E flaky due to sparkline API timing | Medium | Low | Use `page.route()` mock in sparkline degradation test; live test only for golden path |

---

## Rollback Strategy

- **W1 rollback**: `alembic downgrade 0020` removes column; revert `enums.py` + `schemas.py` + route. Existing transactions are unaffected (NULL column).
- **W2 rollback**: Delete the new route from `market.py`. Frontend degrades gracefully (SPARK shows `—`).
- **W3–W5 rollback**: Frontend-only; previous deployment restores old layout. No backend state changed by frontend waves.
