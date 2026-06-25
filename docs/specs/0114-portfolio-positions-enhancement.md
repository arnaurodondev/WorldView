---
id: PRD-0114
title: "Portfolio Positions Enhancement — Manual Holdings, Transaction Filtering, CSV Export & UX Clarity"
status: draft
created: 2026-06-20
updated: 2026-06-20
author: "human + claude"
services: [S1 (portfolio), S9 (api-gateway), worldview-web]
priority: P1
estimated-waves: 6
---

# PRD-0114: Portfolio Positions Enhancement

## 1. Overview & Motivation

### 1.1 Background

The portfolio module (S1) is the most user-facing part of the platform. Users manage three distinct portfolio types — MANUAL (self-entered trades), BROKERAGE (SnapTrade-synced), and ROOT (aggregate "All Accounts") — each with meaningful UX expectations borrowed from Bloomberg Terminal, Schwab, and Fidelity.

The current implementation ships a solid foundation: transaction recording, SnapTrade OAuth2 sync, concentration analytics, TWR computation, and a redesigned 14-column holdings table (PRD-0108). However, a cluster of design gaps — some **silent failures** visible only to attentive users — prevents the portfolio module from reaching Bloomberg-grade quality.

### 1.2 Problem Statement

Investigation (2026-06-20) uncovered six distinct gap clusters, enumerated below by severity:

| # | Gap | Severity | Root Cause |
|---|-----|----------|------------|
| G-1 | MANUAL portfolio Holdings tab is always empty — holdings are never populated from transactions | **CRITICAL** | `RecordTransactionUseCase` deliberately does not write to `holdings` (PLAN-0046 decision); no worker backfills from transaction history |
| G-2 | Transaction filtering is client-side only; `from_date`/`to_date`/`type`/`ticker` are absent from the API | **HIGH** | `ListTransactionsUseCase` only accepts `limit` + `offset`; frontend type-toggle filters the current page only |
| G-3 | No CSV export for tax reporting | **HIGH** | No export endpoint exists |
| G-4 | BROKERAGE portfolio shows no last-synced timestamp | **HIGH** | `brokerage_connections.last_synced_at` exists in DB but is not surfaced in any holdings response |
| G-5 | MANUAL portfolio empty state gives no explanation or CTA | **HIGH** | `HoldingsTab` renders a generic AG Grid empty state — no copy, no onboarding affordance |
| G-6 | No "Close Position" action in the holdings table context menu | **MEDIUM** | SemanticHoldingsTable AG Grid has no context menu item that records a SELL transaction |
| G-7 | Brokerage sync errors are hidden in a collapsible panel — no persistent visual indicator | **MEDIUM** | `brokerage_sync_errors` badge is not surfaced on the Holdings tab header |
| G-8 | After recording a manual transaction, no feedback explains holdings update timing | **MEDIUM** | `addPosition()` success toast is generic; user does not know when holdings will reflect the new trade |
| G-9 | ROOT portfolio "All Accounts" label has no explanation for first-time users | **MEDIUM** | `EnsureRootPortfolioUseCase` provisions "All Accounts" but the frontend treats it identically to user-named portfolios |
| G-10 | Transaction filter UI drives client-side filtering only — unusable at 2-year brokerage history scale | **LOW** | The BUY/SELL/DIVIDEND toggle in `TransactionsTab` only filters the current fetched page |
| G-11 | No cost-basis method selector per portfolio | **LOW** | Holdings cost basis is fixed FIFO; no domain concept for AVCO |

### 1.3 Business Value

- **Retail investors** managing manual portfolios are blocked at the first step: they record trades but see an empty holdings table. Fixing G-1 (FR-1) alone resolves the most visible failure mode.
- **Tax preparers** need filtered, date-bounded transaction exports — G-3 (FR-3) is a prerequisite for any real-world tax workflow.
- **Power users** with large brokerage histories are unable to navigate 2 years of transactions efficiently without backend filtering (G-2, G-10).
- Collectively, this PRD closes the gap between the current implementation and Bloomberg-grade portfolio management for the thesis demo and beyond.

---

## 2. Goals and Non-Goals

### 2.1 In Scope (Goals)

1. Compute and maintain holdings for MANUAL portfolios from transaction history (FR-1).
2. Add server-side transaction filtering: `from_date`, `to_date`, `transaction_type` (multi-value), `ticker` (FR-2).
3. CSV export endpoint for transaction history with P&L and cost-basis fields (FR-3).
4. Surface `last_synced_at` timestamp on Holdings tab for BROKERAGE portfolios (FR-4).
5. MANUAL portfolio empty state with explanation and CTA (FR-5).
6. "Close Position" context-menu action in AG Grid (FR-6).
7. Persistent badge when brokerage sync has errors (FR-7).
8. Post-transaction toast explaining holdings update timing (FR-8).
9. ROOT portfolio onboarding popover (FR-9).
10. Transaction filter UI hitting backend (FR-10).
11. Per-portfolio cost-basis method selector: FIFO (default) / AVCO (FR-11).
12. Annualised dividend yield per holding (FR-12).

### 2.2 Out of Scope (Non-Goals)

- Real-time WebSocket position updates (post-PRD, depends on S1 WebSocket infrastructure).
- Multi-broker support beyond SnapTrade (separate PRD).
- Intraday position tracking (platform uses daily OHLCV; intraday is a separate PRD).
- Portfolio-level tax lot optimisation (suggest specific lots to sell for tax minimisation).
- Bulk position import via CSV upload.
- Mobile/responsive layout changes (desktop-first; mobile is post-thesis).
- Per-position risk metrics (beta, VaR) — deferred to a dedicated risk PRD.

---

## 3. User Stories

### Persona A — Retail Investor (Maria)
Maria manages a 12-position portfolio manually (no brokerage connection). She records trades through the "Add Position" dialog.

| ID | Story | Priority |
|----|-------|----------|
| US-A1 | As Maria, I want my holdings to appear in the Holdings tab after I record a BUY transaction, so that I can track my positions without a brokerage account | must-have |
| US-A2 | As Maria, I want a clear explanation when my holdings tab is empty, with a button to record my first trade | must-have |
| US-A3 | As Maria, I want to close a position by right-clicking a holding and selecting "Close Position", pre-filled with the current quantity | should-have |
| US-A4 | As Maria, I want to know exactly when my holdings will update after I record a transaction | should-have |

### Persona B — Tax Preparer (David)
David prepares annual tax filings. He needs a complete, date-bounded history of transactions with cost-basis information.

| ID | Story | Priority |
|----|-------|----------|
| US-B1 | As David, I want to export all transactions for a given year as a CSV with purchase price, sale price, fees, and realized P&L per transaction, so that I can prepare tax documents without manual copying | must-have |
| US-B2 | As David, I want to filter transactions by date range (from/to) and by type (BUY, SELL, DIVIDEND) at the server level, so that I get accurate counts even with 2 years of brokerage history | must-have |
| US-B3 | As David, I want to filter transactions by ticker symbol, so that I can review the entire history of a specific stock | should-have |

### Persona C — Power User (Alex)
Alex has a SnapTrade-connected brokerage account and also manages a separate manual portfolio. He frequently checks data freshness.

| ID | Story | Priority |
|----|-------|----------|
| US-C1 | As Alex, I want to see "Last synced: 23 min ago" on my brokerage portfolio's Holdings tab, so that I know whether the data reflects today's trades | must-have |
| US-C2 | As Alex, I want a red badge on the Holdings tab header if my last brokerage sync produced errors, so that I notice sync failures without opening a collapsible panel | should-have |
| US-C3 | As Alex, I want to understand what "All Accounts" means the first time I see it, via a tooltip or popover | should-have |
| US-C4 | As Alex, I want to choose between FIFO and average-cost methods per portfolio, so that my P&L numbers match my broker's reporting | nice-to-have |
| US-C5 | As Alex, I want to see the annualized dividend yield for each holding inline in the table | nice-to-have |

---

## 4. Functional Requirements

### FR-1 (CRITICAL): ManualPortfolioHoldingsWorker

Compute and maintain the `holdings` table for MANUAL portfolios by replaying transaction history.

**Acceptance Criteria**:
- A new `ComputeManualHoldingsUseCase` applies transactions in chronological order using FIFO to produce a `{ticker → Holding}` snapshot.
- Holdings are written via `UpsertHoldingsUseCase` (reusing or extending the existing brokerage path).
- The worker is triggered in two ways:
  1. **Event-driven**: immediately after `RecordTransactionUseCase` succeeds, emit a `portfolio.holding.recompute_requested.v1` internal domain event; a new `ManualHoldingsRecomputeConsumer` processes it.
  2. **Scheduled**: nightly at 22:00 UTC via `ManualHoldingsWorker` (extends `BaseScheduledWorker`), runs for all MANUAL portfolios with at least one transaction.
- Zero-quantity holdings (net qty after all transactions = 0) are suppressed when `include_closed=false` (existing query param already respected by `GET /api/v1/portfolios/{id}/holdings`).
- FIFO cost basis: `cost_basis_per_unit` is the weighted average of open lots; `total_cost_basis` = `quantity × cost_basis_per_unit`.
- If FR-11 (AVCO) is enabled, use `portfolio.cost_basis_method` to select the algorithm.
- Alembic migration required if any new columns are added to `holdings`.
- Unit tests: cost-basis edge cases (partial fills, partial closes, wash-sale passthrough), zero-quantity suppression, nightly worker schedule wiring.
- Integration test: record 3 BUY + 1 partial SELL → assert holdings has 1 row with correct qty and cost basis.

**Key files**:
- `services/portfolio/src/portfolio/application/use_cases/compute_manual_holdings.py` (new)
- `services/portfolio/src/portfolio/workers/manual_holdings_worker.py` (new)
- `services/portfolio/src/portfolio/infrastructure/messaging/consumers/manual_holdings_consumer_main.py` (new)

---

### FR-2 (HIGH): Server-Side Transaction Filtering

Add query parameters to `GET /api/v1/portfolios/{id}/transactions` and `GET /api/v1/transactions`.

**New query parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `from_date` | `date` (ISO 8601, optional) | Inclusive lower bound on `executed_at` (date portion — the domain field is `executed_at: datetime`, not `transaction_date`) |
| `to_date` | `date` (ISO 8601, optional) | Inclusive upper bound on `executed_at` (date portion) |
| `transaction_type` | `str[]` (optional, repeated) | Filter by one or more `TransactionType` values |
| `ticker` | `str` (optional) | Case-insensitive prefix/exact match on `instrument.ticker` |

**Acceptance Criteria**:
- `ListTransactionsUseCase` accepts a `TransactionFilter` value object with the four new fields.
- Total count in paginated response reflects filtered set (not total unfiltered).
- All four filters may be combined; combining them uses AND semantics.
- API returns 422 (not 500) when `transaction_type` value is not a valid enum member.
- S9 proxy (`GET /v1/portfolio/transactions` and `GET /v1/portfolio/portfolios/{id}/transactions`) passes through the new query params.
- Unit tests: each filter independently; combined `from_date`+`to_date`+`transaction_type`; ticker case-insensitivity.

---

### FR-3 (HIGH): Transaction CSV Export

New endpoint: `GET /api/v1/portfolios/{id}/transactions/export`

**Query parameters**: same as FR-2 (`from_date`, `to_date`, `transaction_type`, `ticker`).

**Response**:
- `Content-Type: text/csv`
- `Content-Disposition: attachment; filename="transactions_{portfolio_id}_{from_date}_{to_date}.csv"`
- Streaming response (no OOM risk with large histories).

**CSV columns**:
| Column | Source | Notes |
|--------|--------|-------|
| `date` | `transaction.executed_at` (date portion) | ISO 8601 YYYY-MM-DD |
| `ticker` | `instrument.ticker` | |
| `type` | `transaction.transaction_type` | BUY/SELL/DIVIDEND/etc. |
| `trade_side` | `transaction.trade_side` | BUY/SELL/null |
| `quantity` | `transaction.quantity` | |
| `price` | `transaction.price` | Per-unit price (domain field name is `price`, not `price_per_unit`) |
| `fees` | `transaction.fees` | |
| `currency` | `transaction.currency` | |
| `total_value` | computed: `transaction.quantity × transaction.price` | No `total_value` field on entity — computed at export |
| `cost_basis_per_unit` | computed at export time (FIFO) | null for non-TRADE types |
| `realized_pnl` | computed at export time | null for open lots |
| `description` | `transaction.description` | Broker-supplied description (nullable) |

**Acceptance Criteria**:
- S9 proxy route added: `GET /v1/portfolio/portfolios/{id}/transactions/export`.
- Endpoint requires authenticated user who owns the portfolio (same auth guard as other portfolio endpoints).
- Empty result set returns a valid CSV with headers only.
- Integration test: seed 10 transactions, export, assert row count and column names.

---

### FR-4 (HIGH): Holdings Last-Synced Timestamp

Surface `brokerage_connections.last_synced_at` in the holdings response for BROKERAGE portfolios.

**Acceptance Criteria**:
- `GET /api/v1/portfolios/{id}/holdings` response gains an optional `brokerage_last_synced_at: datetime | null` field.
- Non-null only when the portfolio `kind == BROKERAGE` and at least one successful sync has occurred.
- `HoldingsTab` frontend renders `"Last synced: {relative time}"` in the tab header subtitle (e.g. "23 min ago", "2h ago", "yesterday").
- Uses `useFormattedTimestamp` shared hook already in the design system.
- No additional API call required — the field is joined from `brokerage_connections` at holdings query time.

---

### FR-5 (HIGH): MANUAL Portfolio Empty State

Replace the generic AG Grid empty state in `HoldingsTab` with an informative onboarding panel when the portfolio is MANUAL and has zero holdings.

**Acceptance Criteria**:
- Empty state shows:
  - Headline: "No positions yet"
  - Body: "Record your first transaction to populate your holdings. Holdings are computed from your transaction history and update within seconds of each trade."
  - Primary CTA button: "Record Transaction" (opens `AddPositionDialog`).
- Empty state is shown only when `portfolio.kind === "manual"` and the holdings array is empty. (Note: `PortfolioKind` enum values are lowercase: `"manual"`, `"brokerage"`, `"root"` — the API serialises them as-is.)
- For BROKERAGE portfolios with zero holdings, a different message is shown: "Awaiting first sync — check back in a few minutes."
- Unit tests: empty state renders for `kind="manual"`; does not render for `kind="brokerage"`.

---

### FR-6 (MEDIUM): Close Position Context Menu Action

Add a "Close Position" item to the AG Grid right-click context menu in `SemanticHoldingsTable`.

**Acceptance Criteria**:
- Context menu item appears only for holdings with `quantity > 0` and portfolio `kind !== "root"`. (Kind values are lowercase strings from the API.)
- Clicking "Close Position" opens a `ClosePositionDialog` pre-filled with:
  - Ticker (read-only)
  - Current quantity (read-only, from holding)
  - Price per unit (editable input, no default — user must enter)
  - Trade date (date picker, default = today)
- On confirm, calls `POST /api/v1/transactions` with `transaction_type=TRADE`, `trade_side=SELL`, `quantity` = holding quantity, and the user-provided price/date.
- On success: toast "Position closed. Holdings will update within seconds." and optimistic refetch of holdings.
- On error: toast with error message.
- Unit tests: dialog renders with correct pre-fills; confirm dispatches correct payload; error state renders.

---

### FR-7 (MEDIUM): Sync Error Badge

Add a persistent visual indicator on the Holdings tab header when the brokerage account has unresolved sync errors.

**Acceptance Criteria**:
- `GET /api/v1/portfolios/{id}/holdings` response gains `brokerage_sync_error_count: int` (0 when no errors or non-BROKERAGE portfolio).
- `HoldingsTab` renders a red `●` dot badge next to the "Holdings" tab label when `brokerage_sync_error_count > 0`.
- Clicking the badge scrolls to or expands the existing sync error collapsible panel.
- Badge clears when `brokerage_sync_error_count` returns to 0 on next refetch.
- Unit test: badge renders when count > 0; does not render when count = 0.

---

### FR-8 (MEDIUM): Manual Transaction Feedback Toast

After a successful `POST /api/v1/transactions` for a MANUAL portfolio, show an informative toast.

**Acceptance Criteria**:
- Existing generic success toast is replaced with: "Transaction recorded. Holdings will reflect this trade within seconds."
- This copy applies only when `portfolio.kind === "manual"`. For brokerage portfolios (if manual transactions are ever allowed in future), the existing generic copy is retained.
- Toast auto-dismisses after 5 seconds.
- No backend changes required — this is a frontend-only change in `AddPositionDialog` or `useTransactionMutations`.
- Unit test: toast message matches expected copy.

---

### FR-9 (MEDIUM): ROOT Portfolio Onboarding Popover

Add a tooltip/popover explaining the "All Accounts" portfolio to first-time users.

**Acceptance Criteria**:
- An info icon (`ℹ`) appears next to the "All Accounts" portfolio name in the portfolio selector dropdown and in the portfolio page header.
- Hovering/clicking shows a popover: "All Accounts aggregates holdings across all your connected portfolios. Updated nightly at 22:30 UTC. You cannot record transactions directly here."
- Popover is dismissible and does not re-appear after the user dismisses it (persisted in `localStorage` key `worldview:root_portfolio_popover_dismissed`).
- Unit test: popover renders for `kind="root"`; does not render for `kind="manual"` / `kind="brokerage"`.

---

### FR-10 (LOW): Transaction Filter UI Hits Backend

Replace the client-side type-toggle in `TransactionsTab` with a filter bar that dispatches to the backend.

**Acceptance Criteria**:
- Filter bar components: date range picker (`from_date` / `to_date`), transaction type multi-select (checkboxes: BUY, SELL, DIVIDEND, DEPOSIT, WITHDRAWAL, INTEREST, FEE), ticker text input.
- Filters are debounced (300 ms) before dispatching `GET /api/v1/portfolios/{id}/transactions` with new query params.
- Pagination resets to page 1 on filter change.
- "Clear filters" button resets all fields.
- Total count in pagination reflects filtered total (uses FR-2 count).
- Unit tests: filter change triggers new query with correct params; pagination resets.

---

### FR-11 (LOW): Cost Basis Method Selector

Allow users to choose FIFO or Average Cost (AVCO) per portfolio.

**Acceptance Criteria**:
- `portfolios` table gains a nullable `cost_basis_method` column (`enum: FIFO | AVCO`, default `FIFO`).
- `Portfolio` domain entity gains `cost_basis_method: CostBasisMethod`.
- `PATCH /api/v1/portfolios/{id}` accepts `{"cost_basis_method": "AVCO"}`.
- `ComputeManualHoldingsUseCase` (FR-1) reads `portfolio.cost_basis_method` and switches algorithms accordingly.
- CSV export (FR-3) uses the portfolio's method.
- Frontend: settings panel within portfolio page (or `EditPortfolioDialog`) renders a `<Select>` for cost basis method.
- AVCO algorithm: `cost_basis_per_unit = total_cost_of_remaining_lots / total_qty`.
- Migration: additive nullable column with default `FIFO` — backward compatible.
- Unit tests: FIFO and AVCO algorithms produce correct results for interleaved BUY/SELL sequences.

---

### FR-12 (LOW): Dividend Yield Per Holding

Add `annualized_dividend_yield` to the holdings detail data.

**Acceptance Criteria**:
- S9 proxy response for holdings gains an optional `annualized_dividend_yield: float | null` per holding row.
- Sourced from `market-data` service fundamentals (field `annual_dividend_yield` or equivalent from EODHD fundamentals), joined at the S9 aggregation layer.
- Null when not available (instrument has no dividend data or is not a dividend payer).
- `SemanticHoldingsTable` gains a `DIV YLD` column (hidden by default in column visibility, user can toggle on).
- No S1 schema changes required — the field is sourced from S3 market-data.
- Unit test: column renders `—` when null, renders formatted percentage when non-null.

---

## 5. API Changes

### 5.1 New Endpoints

| Method | Path | Service | Description |
|--------|------|---------|-------------|
| GET | `/api/v1/portfolios/{id}/transactions/export` | S1 | CSV export (FR-3) |
| GET | `/v1/portfolio/portfolios/{id}/transactions/export` | S9 | S9 proxy for FR-3 |

### 5.2 Modified Endpoints

| Endpoint | Change | Backward Compatible? |
|----------|--------|---------------------|
| `GET /api/v1/portfolios/{id}/transactions` | Add `from_date`, `to_date`, `transaction_type[]`, `ticker` query params; total count respects filters | Yes — new optional params, existing calls unaffected |
| `GET /api/v1/transactions` | Same filter params as above | Yes |
| `GET /api/v1/portfolios/{id}/holdings` | Add `brokerage_last_synced_at`, `brokerage_sync_error_count` fields to response | Yes — additive fields |
| `PATCH /api/v1/portfolios/{id}` | Accept `cost_basis_method` field | Yes — new optional field |
| `GET /v1/portfolio/portfolios/{id}/transactions` | Pass through new filter params | Yes |
| `GET /v1/portfolio/portfolios/{id}/holdings` | Pass through new response fields | Yes |

### 5.3 Request/Response Schemas

#### `GET /api/v1/portfolios/{id}/transactions` — Query Params (FR-2)
```
from_date: date (optional, ISO 8601 YYYY-MM-DD — filters on executed_at date portion)
to_date: date (optional, ISO 8601 YYYY-MM-DD — filters on executed_at date portion)
transaction_type: str (optional, repeatable — e.g. ?transaction_type=BUY&transaction_type=SELL)
ticker: str (optional, case-insensitive)
limit: int (default 50, max 500)
offset: int (default 0)
```

#### `GET /api/v1/portfolios/{id}/holdings` — Augmented Response (FR-4, FR-7)
```json
{
  "holdings": [...],
  "total": 12,
  "brokerage_last_synced_at": "2026-06-20T14:32:00Z",
  "brokerage_sync_error_count": 0
}
```

#### `PATCH /api/v1/portfolios/{id}` — New Field (FR-11)
```json
{ "cost_basis_method": "FIFO" }
```
Valid values: `"FIFO"`, `"AVCO"`.

---

## 6. Data Model Changes

### 6.1 New Tables

| DB | Table | Columns | Purpose |
|----|-------|---------|---------|
| `portfolio_db` | (none new) | — | All changes are additive columns or new workers |

### 6.2 Modified Tables

| Table | Change | Migration | Backward Compatible? |
|-------|--------|-----------|---------------------|
| `portfolios` | Add `cost_basis_method VARCHAR(8) NOT NULL DEFAULT 'FIFO'` | Alembic migration with `server_default='FIFO'` | Yes |
| `holdings` | Add `cost_basis_per_unit NUMERIC(20,8) NULL`, `total_cost_basis NUMERIC(20,8) NULL` — both are new columns (the ORM model currently only has `average_cost`) | Additive nullable columns | Yes |

### 6.3 Domain Entities

#### New: `CostBasisMethod` Enum
```python
class CostBasisMethod(str, enum.Enum):
    FIFO = "FIFO"
    AVCO = "AVCO"
```

#### Modified: `Portfolio`
```python
@dataclass
class Portfolio:
    ...
    cost_basis_method: CostBasisMethod = CostBasisMethod.FIFO  # FR-11
```

#### New: `TransactionFilter` Value Object
```python
@dataclass(frozen=True)
class TransactionFilter:
    # Filters on executed_at (datetime) date portion — the Transaction entity
    # uses `executed_at: datetime`, not `transaction_date`. The repo casts
    # executed_at to date at query time: CAST(executed_at AS DATE) >= from_date.
    from_date: date | None = None
    to_date: date | None = None
    transaction_types: list[TransactionType] = field(default_factory=list)
    ticker: str | None = None
    limit: int = 50
    offset: int = 0
```

### 6.4 New Kafka Topic

| Topic | Purpose | Producer | Consumer |
|-------|---------|---------|---------|
| `portfolio.holding.recompute_requested.v1` | Signal that a MANUAL portfolio's holdings need recomputation after a new transaction | `RecordTransactionUseCase` (S1) | `ManualHoldingsRecomputeConsumer` (S1 internal) |

**Avro schema** (`infra/kafka/schemas/portfolio_holding_recompute_requested.v1.avsc`):
```json
{
  "type": "record",
  "name": "PortfolioHoldingRecomputeRequested",
  "fields": [
    {"name": "portfolio_id", "type": "string"},
    {"name": "tenant_id", "type": "string"},
    {"name": "triggered_by_transaction_id", "type": "string"},
    {"name": "occurred_at", "type": "string"},
    {"name": "schema_version", "type": "int", "default": 1}
  ]
}
```

---

## 7. UI/UX Requirements

### 7.1 Component Changes

| Component | Type | Change | FR |
|-----------|------|--------|----|
| `HoldingsTab` | component | Render `ManualEmptyState` when MANUAL+empty; show `LastSyncedBadge` and `SyncErrorBadge` for BROKERAGE | FR-4, FR-5, FR-7 |
| `ManualEmptyState` | new component | Headline + body + "Record Transaction" CTA | FR-5 |
| `BrokerageEmptyState` | new component | "Awaiting first sync" message | FR-5 |
| `LastSyncedBadge` | new component | "Last synced: {relative time}" in tab header | FR-4 |
| `SyncErrorBadge` | new component | Red dot badge; click scrolls to error panel | FR-7 |
| `ClosePositionDialog` | new component | Pre-filled form: ticker, qty, price, date → POST transaction | FR-6 |
| `SemanticHoldingsTable` | component | Add context menu "Close Position" item; add `DIV YLD` hidden column | FR-6, FR-12 |
| `TransactionsTab` | component | Replace client-side toggle with `TransactionFilterBar`; pagination uses server total | FR-10 |
| `TransactionFilterBar` | new component | Date range pickers, type multi-select, ticker input, "Clear" button | FR-10 |
| `AddPositionDialog` | component | Success toast copy updated for MANUAL portfolios | FR-8 |
| `PortfolioSelector` | component | Add `ℹ` icon + `RootPortfolioPopover` for ROOT portfolio entries | FR-9 |
| `PortfolioPageHeader` | component | Add `ℹ` icon + `RootPortfolioPopover` when ROOT portfolio selected | FR-9 |
| `RootPortfolioPopover` | new component | Popover with "All Accounts" explanation; `localStorage` dismiss | FR-9 |
| `EditPortfolioDialog` | component | Add cost basis method `<Select>` (FIFO / Average Cost) | FR-11 |

### 7.2 Wireframe Descriptions

**Holdings Tab — MANUAL, empty state (FR-5)**
```
┌───────────────────────────────────────────────────────┐
│  Holdings    Transactions    Analytics                  │
├───────────────────────────────────────────────────────┤
│                                                         │
│           📂  No positions yet                          │
│                                                         │
│   Record your first transaction to populate your        │
│   holdings. Holdings are computed from your             │
│   transaction history and update within seconds.        │
│                                                         │
│              [ Record Transaction ]                     │
│                                                         │
└───────────────────────────────────────────────────────┘
```

**Holdings Tab — BROKERAGE header (FR-4, FR-7)**
```
┌───────────────────────────────────────────────────────┐
│  Holdings ●  Transactions    Analytics                  │
│  Last synced: 23 min ago                               │
├───────────────────────────────────────────────────────┤
│  TICKER │ QTY │ AVG COST │ MKT VALUE │ DAY Δ% │ ...   │
```
`●` = red dot, only shown when `brokerage_sync_error_count > 0`.

**Close Position Dialog (FR-6)**
```
┌──────────────────────────────┐
│  Close Position              │
├──────────────────────────────┤
│  Ticker:       AAPL (read)   │
│  Quantity:     15 (read)     │
│  Sale Price:   [          ]  │
│  Trade Date:   [2026-06-20]  │
├──────────────────────────────┤
│  [ Cancel ]   [ Close Position ] │
└──────────────────────────────┘
```

---

## 8. Performance & Scale Constraints

| Concern | Constraint | Mitigation |
|---------|-----------|------------|
| `ComputeManualHoldingsUseCase` replay time | Portfolios may have 2+ years of daily transactions (~1,000 rows). Must complete in < 2 s. | Use a single `SELECT … ORDER BY transaction_date ASC` query; no N+1 reads |
| CSV export streaming | Large brokerage histories (730 days × many tickers) could be 10K+ rows. | Use Python `csv.writer` with `StreamingResponse`; no in-memory accumulation |
| Transaction filter query | `from_date` + `to_date` + `ticker` on `transactions` table. Must be < 100 ms p95. | Ensure composite index on `(portfolio_id, transaction_date, instrument_id)` |
| `ManualHoldingsWorker` nightly run | Runs for all MANUAL portfolios. Scale: O(portfolios × transactions). | Process portfolios sequentially; advisory lock per portfolio to prevent overlap with event-driven trigger |
| `brokerage_sync_error_count` join | Added to every holdings response. Must not noticeably degrade holdings endpoint. | Single `COUNT(*)` subquery on `brokerage_sync_errors` with index on `(brokerage_connection_id)` |

---

## 9. Risk Assessment

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| Holdings divergence: event-driven trigger and nightly worker both run concurrently | HIGH | MEDIUM | Advisory lock per `portfolio_id` prevents concurrent recomputation; last writer wins is safe (idempotent UPSERT) |
| FIFO cost basis incorrect for partial-fill split transactions | HIGH | LOW | Unit tests cover partial fills, average-price lots, and zero-quantity suppression; edge cases documented |
| CSV export used for tax filing with incorrect P&L | HIGH | MEDIUM | Add disclaimer in UI: "For informational purposes only — consult a tax professional." No liability for computed P&L values |
| `portfolio.holding.recompute_requested.v1` topic added but never consumed (consumer crash) | MEDIUM | LOW | Nightly worker acts as a fallback; alert on DLQ accumulation |
| Backward compatibility: `cost_basis_method` column migration | LOW | LOW | Column is `NOT NULL DEFAULT 'FIFO'` — no existing functionality changes; migration is additive |
| `brokerage_last_synced_at` null for brand-new connections | LOW | CERTAIN | Frontend handles null with "Never synced" copy; no error state |

---

## 10. Success Metrics

| Metric | Definition | Target | Measurement |
|--------|-----------|--------|-------------|
| MANUAL holdings population rate | % of MANUAL portfolios with ≥ 1 holding after ≥ 1 recorded transaction | 100% | Query: `SELECT … WHERE kind='MANUAL' AND …` |
| Holdings endpoint latency | p95 of `GET /api/v1/portfolios/{id}/holdings` | ≤ 200 ms | Prometheus `http_request_duration_seconds` |
| CSV export latency | p95 of `GET /api/v1/portfolios/{id}/transactions/export` for 1K-row dataset | ≤ 2 s | Prometheus histogram |
| Transaction filter accuracy | Total count returned matches actual filtered count in DB | 100% | Integration test; manual QA |
| FR-5 empty state visibility | Users who open MANUAL portfolio Holdings tab see the empty state (not a blank AG Grid) | 100% | Vitest component test |
| FR-1 latency: holdings visible after transaction | Time from `POST /api/v1/transactions` to holdings updated | ≤ 5 s p95 (event-driven path) | Local integration test |

---

## 11. Architecture Decisions

| # | Decision | Alternatives | Rationale |
|---|----------|-------------|-----------|
| AD-1 | Holdings recomputation is event-driven (Kafka internal topic) + nightly fallback, not synchronous in `RecordTransactionUseCase` | (A) Synchronous update in use case, (B) Polling loop, (C) WebSocket push | Event-driven maintains the separation of concerns from PLAN-0046; synchronous update would add latency to the transaction record path and violate the outbox pattern. Nightly fallback ensures correctness even if events are dropped. |
| AD-2 | CSV export uses `StreamingResponse` from FastAPI, not a batch-then-download approach | Pre-generate S3 object, polling download URL | Simpler, no object lifecycle management, works for thesis scale. S3 pre-generation is appropriate only when export jobs take >30s or files exceed 100MB. |
| AD-3 | `TransactionFilter` is a Value Object passed to `ListTransactionsUseCase`, not added as method params | Direct method params | Value Object is more extensible (future filters don't change method signatures), consistent with existing use-case patterns, and type-safe. |
| AD-4 | `brokerage_last_synced_at` and `brokerage_sync_error_count` are joined at the holdings use-case level (not a separate endpoint) | Add a new `GET /api/v1/portfolios/{id}/brokerage-status` endpoint | Keeps the frontend to a single request for the Holdings tab; the join is cheap (one row lookup on `brokerage_connections`). |
| AD-5 | `ManualPortfolioHoldingsWorker` uses FIFO by default; AVCO is opt-in per portfolio | System-wide method setting | Per-portfolio granularity matches real broker behaviour; users may have one FIFO and one AVCO portfolio for different tax strategies. |

---

## 12. Security Analysis

### 12.1 Threat Model

| Threat | Likelihood | Impact | Mitigation |
|--------|-----------|--------|------------|
| Cross-tenant CSV export: user crafts portfolio_id of another tenant | LOW | HIGH | All portfolio queries are scoped by `owner_id + tenant_id` from JWT; `GetPortfolioUseCase` raises `PortfolioNotFoundError` (→ 404) for wrong tenant |
| CSV injection: ticker or notes fields contain `=CMD()` formulas | MEDIUM | MEDIUM | Prefix cells starting with `=`, `+`, `-`, `@` with a single quote (`'`) in the CSV writer |
| Date range abuse: very wide date range causes slow query | LOW | LOW | Cap `to_date - from_date` at 5 years (1,826 days); return 400 if exceeded |
| Unauthenticated export access | LOW | HIGH | Same `InternalJWTMiddleware` and portfolio ownership guard as all other S1 endpoints |

### 12.2 Multi-Tenant Isolation

All new queries follow the existing S1 pattern: every SQL query includes `WHERE owner_id = :user_id AND tenant_id = :tenant_id` derived from the validated JWT. The `ComputeManualHoldingsUseCase` processes one portfolio at a time and never reads across portfolio boundaries.

---

## 13. Failure Modes & Recovery

| # | Scenario | Probability | Impact | Detection | Recovery |
|---|----------|------------|--------|-----------|----------|
| F-1 | `ManualHoldingsRecomputeConsumer` crashes after transaction recorded | LOW | MEDIUM — holdings stale until nightly run | DLQ accumulation alert | Nightly `ManualHoldingsWorker` self-heals within 24h; consumer restarts automatically |
| F-2 | Holdings UPSERT conflict: event-driven and nightly worker overlap | MEDIUM | LOW — last writer wins; result is idempotent | Advisory lock log warning | Advisory lock on `portfolio_id` prevents concurrent writes; timeout = 5 s, then skip |
| F-3 | CSV export times out for very large portfolios (10K+ rows) | LOW | LOW | Client receives 504 from S9 | Cap at 5-year range (AD-5); add `LIMIT` safety valve at 50K rows with `X-Truncated: true` header |
| F-4 | `brokerage_sync_error_count` subquery slow under high holdings load | LOW | LOW — holdings endpoint degrades | p95 histogram alert | Add index on `brokerage_sync_errors(brokerage_connection_id)`; materialise count in `brokerage_connections.sync_error_count` if needed |

---

## 14. Test Strategy

### 14.1 Unit Tests (S1)

| Area | Test Focus |
|------|-----------|
| `ComputeManualHoldingsUseCase` | FIFO/AVCO algorithms: buy-then-partial-sell, multiple tickers, zero-quantity suppression |
| `TransactionFilter` VO | Serialisation, validation, edge cases (open-ended ranges) |
| `ListTransactionsUseCase` | Each filter independently; combined; count accuracy |
| CSV writer | Field order, CSV injection escaping, empty result |
| `ManualHoldingsWorker` | Schedule cron expression = `"0 22 * * *"`, advisory lock, skip non-MANUAL portfolios |
| `CostBasisMethod` enum | FIFO vs AVCO selection in use case |

### 14.2 Integration Tests (S1 + DB)

| Scenario | Services | Infrastructure |
|----------|---------|---------------|
| Record BUY → holdings table populated within Kafka round-trip | S1 | PostgreSQL, Kafka |
| Record BUY + partial SELL → correct qty and cost basis | S1 | PostgreSQL |
| Export CSV for filtered date range | S1 | PostgreSQL |
| `last_synced_at` null for new BROKERAGE connection | S1 | PostgreSQL |

### 14.3 Frontend Tests (Vitest)

| Component | Test Focus |
|-----------|-----------|
| `ManualEmptyState` | Renders; "Record Transaction" button triggers dialog |
| `ClosePositionDialog` | Pre-fill from holding; form validation; correct payload |
| `TransactionFilterBar` | Filter change triggers query param update; clear resets |
| `RootPortfolioPopover` | Renders for ROOT; dismiss persists to localStorage; does not render for MANUAL |
| `SyncErrorBadge` | Renders when count > 0; hidden when count = 0 |
| `LastSyncedBadge` | Relative time formatting; "Never synced" for null |

---

## 15. Migration Plan

### 15.1 Alembic Migrations Required

> **Note**: Current Alembic head is `0023_backfill_instrument_entity_id_m017.py`. The next available migration numbers are `0024`, `0025`, `0026`.

| Migration # | Change | Strategy |
|-------------|--------|---------|
| 0024 | Add `portfolios.cost_basis_method VARCHAR(8) NOT NULL DEFAULT 'FIFO'` | Additive, `server_default='FIFO'`, no downtime |
| 0025 | Add `holdings.cost_basis_per_unit NUMERIC(20,8) NULL`, `holdings.total_cost_basis NUMERIC(20,8) NULL` (additive — `holdings` currently only has `average_cost`; both are new nullable columns) | Additive nullable, no downtime |
| 0026 | Add composite index on `transactions(portfolio_id, executed_at, instrument_id)` (note: domain field is `executed_at`, not `transaction_date`) + index on `brokerage_sync_errors(brokerage_connection_id)` | `CREATE INDEX CONCURRENTLY IF NOT EXISTS` — no table lock |

### 15.2 Rollback Strategy

All schema changes are additive (new nullable columns, new columns with defaults). Rollback: drop the new columns. No data loss on rollback. The `ManualHoldingsWorker` can be disabled by removing it from `docker-compose.yml` without affecting other functionality.

### 15.3 Data Migration / Backfill

After migration 0023+0024 are applied, the nightly `ManualHoldingsWorker` (FR-1) will automatically backfill MANUAL portfolio holdings on its first run (22:00 UTC). No manual backfill script is required. The event-driven path will only trigger for new transactions going forward.

---

## 16. Observability

### 16.1 Metrics

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `portfolio_manual_holdings_recomputed_total` | counter | `portfolio_id`, `trigger` (`event`/`scheduled`) | Track recomputation frequency |
| `portfolio_manual_holdings_recompute_duration_seconds` | histogram | `portfolio_id` | Alert if p95 > 5 s |
| `portfolio_csv_export_rows_total` | counter | | Track export usage |
| `portfolio_transaction_filter_latency_seconds` | histogram | `has_date_filter`, `has_type_filter` | Alert if p95 > 200 ms |

### 16.2 Logging

| Event | Level | Fields |
|-------|-------|--------|
| Holdings recomputed for MANUAL portfolio | INFO | `portfolio_id`, `holding_count`, `trigger`, `duration_ms` |
| Holdings recomputation skipped (advisory lock) | WARN | `portfolio_id`, `reason` |
| CSV export requested | INFO | `portfolio_id`, `from_date`, `to_date`, `row_count` |
| Brokerage sync error badge triggered | WARN | `portfolio_id`, `error_count` |

---

## 17. Open Questions

| # | Question | Owner | Resolution |
|---|----------|-------|------------|
| OQ-1 | Should the event-driven recomputation topic (`portfolio.holding.recompute_requested.v1`) be a real Kafka topic registered with the schema registry, or an in-process async task queue? | Arnau | Kafka topic preferred for consistency with platform patterns; in-process `asyncio.Task` is simpler but harder to monitor. Default recommendation: Kafka topic. |
| OQ-2 | Should FR-11 (cost basis method) be per-portfolio or per-portfolio-per-ticker (for different tax lot strategies per instrument)? | Arnau | Per-portfolio is simpler and sufficient for thesis scope; per-instrument can be a follow-up. |
| OQ-3 | FR-12 (dividend yield) source: pull from EODHD fundamentals at export time vs. store in a pre-computed field on `holdings`? | Arnau | Join at S9 aggregation layer from S3 market-data fundamentals (no S1 schema change); acceptable latency given fundamentals are cached. |

---

## 18. Implementation Estimation

| Aspect | Estimate |
|--------|----------|
| Sub-plans | 2 (S1 backend, worldview-web frontend) |
| Waves | 6 (W1: FR-1 use case + worker; W2: FR-2 + FR-3 filtering + export; W3: FR-4 + FR-7 holdings response augmentation; W4: FR-5 + FR-8 + FR-9 frontend UX; W5: FR-6 + FR-10 advanced UI; W6: FR-11 + FR-12 optional features + E2E) |
| Total tasks | ~30 |
| Critical path | W1 (FR-1 manual holdings) → W2 (FR-2 filtering) → W3 (FR-4 response) → W4 (FR-5 empty state) |
| Key risk | FIFO cost basis correctness — requires thorough unit testing before integration |

---

## Changelog

| Date | Author | Change |
|------|--------|--------|
| 2026-06-20 | human + claude | Initial draft — investigation findings from 2026-06-20 deep-dive |
| 2026-06-20 | revise-prd | Correctness pass: (1) fixed CSV column `price_per_unit`→`price` and `transaction_date`→`executed_at` (domain field names); (2) fixed migration numbers §15.1 (0023 already taken; correct sequence is 0024/0025/0026); (3) added note that `holdings` only has `average_cost` — `cost_basis_per_unit`/`total_cost_basis` are new columns; (4) fixed frontend kind comparisons — `PortfolioKind` values are lowercase (`"manual"`, `"brokerage"`, `"root"`); (5) aligned transaction filter description: `from_date`/`to_date` filter on `executed_at` date portion |
