# PLAN-0114 — Portfolio Positions Enhancement

> **PRD**: [docs/specs/0114-portfolio-positions-enhancement.md](../specs/0114-portfolio-positions-enhancement.md)
> **Status**: pending
> **Author**: agent-plan
> **Date**: 2026-06-20
> **Branch**: `feat/plan-0114-portfolio-positions-enhancement` (create from `feat/frontend-enhancement-sprint`)
> **Services**: S1 (portfolio), S9 (api-gateway), worldview-web
> **Total waves**: 6 | **Total tasks**: ~32 | **Estimated effort**: ~8 developer-days

---

## Overview

This plan resolves the six gap clusters (G-1 through G-11) identified in the 2026-06-20 portfolio
investigation. The most critical is **G-1**: MANUAL portfolio holdings are never computed from
transactions — the `RecordTransactionUseCase` deliberately does not write to `holdings` (BP-264 /
PLAN-0046 decision), and no worker backfills the gap.

**Dependency order**:
- W1 (manual holdings computation) must ship before W4 (frontend empty state) to avoid misleading UX.
- W2 (transaction filtering + CSV export) is independent of W1 and can be parallelised.
- W3 (holdings response enrichment) depends on W1 being merged (adds brokerage metadata to the
  same holdings response envelope that W1's consumer populates).
- W4 (Holdings tab polish) depends on W1 + W3 for correct data shapes.
- W5 (Transaction UX + filters) depends on W2 for backend query params.
- W6 (cost-basis method selector + dividend yield) is independent of all prior waves and can
  ship last.

**Critical path**: W1 → W3 → W4; W2 → W5; W6 independent.

---

## Pre-flight Context

| Item | Value |
|------|-------|
| Current Alembic head (portfolio) | `0023_backfill_instrument_entity_id_m017.py` |
| Next migration numbers | `0024`, `0025`, `0026` |
| `PortfolioKind` | `MANUAL / BROKERAGE / ROOT` (existing enum) |
| `TransactionType` | `BUY / SELL / DIVIDEND / DEPOSIT / WITHDRAWAL / FEE / INTEREST / TRADE` (added PLAN-0108) |
| `TradeSide` | `BUY / SELL` (added PLAN-0108) |
| `RecordTransactionUseCase` | Does NOT write holdings (BP-264 / PLAN-0046) |
| `UpsertHoldingsFromSnapshotUseCase` | Existing brokerage path — must be reused/extended for MANUAL |
| `ListTransactionsUseCase` | Only accepts `limit` + `offset` — no date/type/ticker filters |
| `GetHoldingsUseCase` | Returns `list[EnrichedHolding]` — no brokerage metadata |
| `holdings` table | Has `quantity`, `average_cost` fields; check for `cost_basis_per_unit` / `total_cost_basis` |
| `brokerage_connections` | Has `last_synced_at` field; `brokerage_sync_errors` has count per connection |
| `SemanticHoldingsTable` | AG Grid, `components/portfolio/SemanticHoldingsTable.tsx` |
| `TransactionsFilterBar` | Already exists: `components/portfolio/TransactionsFilterBar.tsx` (but does client-side filtering only) |
| `HoldingsTab` | `features/portfolio/components/HoldingsTab.tsx` |
| `TransactionsTab` | `features/portfolio/components/TransactionsTab.tsx` |
| `AddPositionDialog` | `features/portfolio/components/AddPositionDialog.tsx` |
| `useTransactionsFilterState` | `features/portfolio/hooks/useTransactionsFilterState.ts` (already exists) |
| **`PortfolioKind` values** | **Lowercase strings**: `"manual"`, `"brokerage"`, `"root"` — NOT uppercase. Confirmed by `usePortfolioData.ts` line `portfolio.kind === "root"`. All frontend kind checks MUST use lowercase. |
| **Transaction field names** | Domain entity `Transaction` uses `price: Decimal` (not `price_per_unit`) and `executed_at: datetime` (not `transaction_date`). Filters on date range apply to `CAST(executed_at AS DATE)`. `total_value` does not exist as a field — compute as `quantity × price`. |
| **`EditPortfolioDialog`** | Does **not** currently exist — must be created new in W6. |

---

## Architecture Compliance Requirements

All waves must satisfy:

| Rule | What it means for this plan |
|------|-----------------------------|
| R25 | API routers must never import from `infrastructure/`; all reads/writes go through use case classes |
| R27 | New read use cases must use `ReadOnlyUnitOfWork`; API routes use `ReadUoWDep` for reads, `UoWDep` for writes |
| R5  | Outbox pattern for the new `portfolio.holding.recompute_requested.v1` event — never DB + Kafka in separate transactions |
| R6  | `new_uuid7()` for all new entity IDs |
| R7  | `utc_now()` for all timestamps; no naive datetimes |
| R10 | structlog only; no stdlib logging |
| R11 | Forward-compatible schema changes — new fields with defaults, no removals |
| R13 | Domain layer must not import from infrastructure |
| R14 | Frontend only calls S9 (`/v1/...`) proxy routes — no direct S1 calls |
| R1  | Tests with every behavior change; no deferred test writing |
| BP-655 | When adding a field to a domain entity, update both `save()` AND `_to_entity()` in the SQLAlchemy repo |
| BP-126 | NOT NULL Alembic columns must have `server_default` in both migration AND `mapped_column` |

---

## Wave 1 — Backend: Manual Holdings Computation (FR-1)

**Goal**: Compute and maintain the `holdings` table for MANUAL portfolios by replaying transaction
history. This fixes the most critical gap (G-1): users who record BUY transactions see an empty
holdings tab because no worker writes from the `transactions` table.

**Dependencies**: None. Self-contained — ships first.

### Tasks

#### T-W1-01: Domain — `CostBasisMethod` enum + `Portfolio.cost_basis_method` field

**Files**:
- `services/portfolio/src/portfolio/domain/enums.py` — add `CostBasisMethod(StrEnum): FIFO = "FIFO"; AVCO = "AVCO"`
- `services/portfolio/src/portfolio/domain/entities/portfolio.py` — add `cost_basis_method: CostBasisMethod = CostBasisMethod.FIFO`

**Notes**:
- `CostBasisMethod` lives in `enums.py` alongside `PortfolioKind`.
- `Portfolio` dataclass gets the new field with a default so all existing constructors keep working.

#### T-W1-02: Alembic migrations 0024 + 0025

**Files**:
- `services/portfolio/alembic/versions/0024_add_portfolio_cost_basis_method.py` — `ALTER TABLE portfolios ADD COLUMN cost_basis_method VARCHAR(8) NOT NULL DEFAULT 'FIFO'`; `server_default='FIFO'`
- `services/portfolio/alembic/versions/0025_add_holdings_cost_basis_columns.py` — add `cost_basis_per_unit NUMERIC(20,8) NULL` and `total_cost_basis NUMERIC(20,8) NULL` to `holdings` (both are new — the ORM model currently only has `average_cost`; add composite index `CONCURRENTLY` on `transactions(portfolio_id, executed_at, instrument_id)` — note: domain field is `executed_at`, not `transaction_date` — (FR-3 perf, §8)

**Notes**:
- Migration 0024: check whether `holdings` already has these columns from prior sessions; if not, add them additively.
- Migration 0025: use `CREATE INDEX CONCURRENTLY` — no table lock (§15.1).
- Both migrations are fully backward-compatible (additive, no NOT NULL without default).

#### T-W1-03: Infrastructure — `HoldingRepository` + ORM model updates

**Files**:
- `services/portfolio/src/portfolio/infrastructure/db/models/holding.py` — add `cost_basis_per_unit` and `total_cost_basis` mapped columns (nullable)
- `services/portfolio/src/portfolio/infrastructure/db/models/portfolio.py` — add `cost_basis_method` mapped column
- `services/portfolio/src/portfolio/infrastructure/db/repositories/holding.py` — update `_to_entity()` and `save()` to handle new fields (BP-655)
- `services/portfolio/src/portfolio/infrastructure/db/repositories/portfolio.py` — update `_to_entity()` and `save()` for `cost_basis_method`

#### T-W1-04: Application — `ComputeManualHoldingsUseCase`

**Files**:
- `services/portfolio/src/portfolio/application/use_cases/compute_manual_holdings.py` (new)

**Logic**:
- Input: `portfolio_id`, `tenant_id`, `owner_id`
- Fetch all transactions for the portfolio ordered by `executed_at ASC`
- FIFO algorithm: maintain an ordered `deque` of open lots `(qty, cost_per_unit)` per ticker
  - BUY/TRADE+BUY: push lot onto deque
  - SELL/TRADE+SELL: pop from the front of the deque, computing `realized_pnl` per lot
  - DIVIDEND/DEPOSIT/WITHDRAWAL/FEE/INTEREST: skip (no position impact)
- After replay: for each ticker with a non-zero net quantity, compute `cost_basis_per_unit` = weighted-average cost of remaining lots
- AVCO algorithm (when `portfolio.cost_basis_method == AVCO`): `cost_basis_per_unit = total_remaining_cost / total_remaining_qty`
- Produce a list of `ResolvedSnapshotPosition`-compatible DTOs
- Delegate to `UpsertHoldingsFromSnapshotUseCase` to write holdings (reuse existing brokerage path)
- Zero-quantity positions are deleted (existing brokerage behaviour is correct: snapshot = truth)
- Emit `portfolio_manual_holdings_recomputed_total` Prometheus counter

**Notes**:
- Single `SELECT * FROM transactions WHERE portfolio_id = :pid ORDER BY executed_at ASC` — no N+1.
- Advisory lock on `portfolio_id` to prevent concurrent recomputation (use `pg_try_advisory_xact_lock(hash)`).
- `UpsertHoldingsFromSnapshotUseCase` already handles upsert + zero-qty deletion + `HoldingChanged` outbox events — reuse it directly.
- `ResolvedSnapshotPosition` requires `instrument_id: UUID`. Transactions already carry `instrument_id` directly, so the FIFO replay groups by `instrument_id` (not ticker); tickers are only used in the export CSV. No additional resolution step is needed.

#### T-W1-05: Kafka — `portfolio.holding.recompute_requested.v1` topic + Avro schema

**Files**:
- `infra/kafka/schemas/portfolio_holding_recompute_requested.v1.avsc` (new) — global schema registry copy per PRD §6.4 (used by `scripts/gen-contracts.sh` and forward-compat checks)
- `services/portfolio/src/portfolio/infrastructure/messaging/schemas/portfolio_holding_recompute_requested.v1.avsc` (new) — local service copy (the service `serialization.py` uses `_SCHEMA_DIR = Path(__file__).parent / "schemas"`; the global `infra/kafka/schemas/` is for schema registry registration only)
- `libs/contracts/src/contracts/events/portfolio/holding_recompute_requested.py` (new) — canonical Pydantic model matching the Avro schema field-for-field (R28: every topic must have a canonical model in `libs/contracts`)
- `infra/kafka/init/create-topics.sh` — add topic `portfolio.holding.recompute_requested.v1` with 1 partition (dev), RF=1 dev / RF=3 prod
- `services/portfolio/src/portfolio/application/messaging/topics.py` — add `PORTFOLIO_HOLDING_RECOMPUTE_REQUESTED = "portfolio.holding.recompute_requested.v1"`
- `services/portfolio/src/portfolio/infrastructure/messaging/serialization.py` — register serializer for the new topic in `_AVSC_MAP` (key = the event_type used in outbox; the new topic uses a single event type so the key = the topic name or a stable event type string)

#### T-W1-06: `RecordTransactionUseCase` — emit recompute event (outbox)

**Files**:
- `services/portfolio/src/portfolio/application/use_cases/record_transaction.py` — after committing the transaction, if `portfolio.kind == PortfolioKind.MANUAL`, write a second outbox row for `portfolio.holding.recompute_requested.v1` in the SAME DB transaction (before `uow.commit()`)
- `services/portfolio/src/portfolio/domain/events.py` — add `PortfolioHoldingRecomputeRequested` domain event dataclass
- `services/portfolio/src/portfolio/application/messaging/mapper.py` — add `holding_recompute_requested_to_dict()`

**Notes**:
- Both outbox rows (TransactionRecorded + HoldingRecomputeRequested) are written atomically before the single `await uow.commit()` call — outbox pattern preserved (R5).
- The event is only emitted when `portfolio.kind == MANUAL`; brokerage and root portfolios are unaffected.

#### T-W1-07: Consumer — `ManualHoldingsRecomputeConsumer`

**Files**:
- `services/portfolio/src/portfolio/infrastructure/messaging/consumers/manual_holdings_consumer.py` (new) — extends `BaseKafkaConsumer`; on message, calls `ComputeManualHoldingsUseCase`
- `services/portfolio/src/portfolio/infrastructure/messaging/consumers/manual_holdings_consumer_main.py` (new) — entrypoint
- `infra/compose/docker-compose.yml` — add `portfolio-manual-holdings-consumer` service

#### T-W1-08: Scheduled worker — `ManualHoldingsWorker`

**Files**:
- `services/portfolio/src/portfolio/workers/manual_holdings_worker.py` (new) — extends `BaseScheduledWorker`; cron `"0 22 * * *"` (22:00 UTC); iterates all MANUAL portfolios with at least 1 transaction; calls `ComputeManualHoldingsUseCase` for each; skips portfolio if advisory lock is held
- `infra/compose/docker-compose.yml` — add `portfolio-manual-holdings-worker` service

#### T-W1-09: Tests

**Files**:
- `services/portfolio/tests/unit/use_cases/test_compute_manual_holdings.py` (new):
  - FIFO: 3 BUY lots + 1 partial SELL → correct qty + weighted-average cost basis
  - FIFO: BUY then full SELL → zero qty (position deleted)
  - AVCO: interleaved BUY/SELL → correct average-cost basis
  - Zero-quantity suppression: net zero after SELL → no holding row
  - DIVIDEND skipped: does not affect qty
  - Advisory lock: concurrent call skips recomputation
- `services/portfolio/tests/integration/test_manual_holdings_recompute.py` (new):
  - Record 3 BUY + 1 partial SELL → assert 1 holdings row with correct qty and cost basis
  - Record BUY for BROKERAGE portfolio → assert NO recompute event emitted
- `services/portfolio/tests/unit/workers/test_manual_holdings_worker.py` (new):
  - Cron expression is `"0 22 * * *"`
  - Skips ROOT and BROKERAGE portfolios

### Validation Gate

```bash
cd services/portfolio && python -m pytest tests/ -m "unit" -k "manual_holdings or cost_basis" -v
cd services/portfolio && python -m pytest tests/ -m "integration" -k "manual_holdings" -v
cd services/portfolio && python -m ruff check src/ tests/ && python -m mypy src/
```

**Complexity**: L

---

## Wave 2 — Backend: Transaction Filtering + CSV Export (FR-2, FR-3) [DONE 2026-06-20]

**Goal**: Add server-side filtering to `ListTransactionsUseCase` and a new streaming CSV export
endpoint. Fixes G-2 (client-side filtering) and G-3 (no export).

**Dependencies**: None. Can be developed in parallel with W1.

### Tasks

#### T-W2-01: Domain — `TransactionFilter` value object

**Files**:
- `services/portfolio/src/portfolio/domain/value_objects.py` — add `@dataclass(frozen=True) class TransactionFilter` with fields: `from_date: date | None`, `to_date: date | None`, `transaction_types: list[TransactionType]`, `ticker: str | None`, `limit: int = 50`, `offset: int = 0`

**Notes**:
- Value object is immutable (frozen). Validation: `to_date >= from_date` when both set; `to_date - from_date <= 1826 days` (5-year cap, §12.1 security).
- `ticker` stored as-is; case-insensitive comparison happens in the repository.
- `from_date` / `to_date` are Python `date` objects used to filter on `CAST(executed_at AS DATE)` — the `Transaction` domain entity uses `executed_at: datetime` (not `transaction_date`). The API query param names `from_date`/`to_date` are user-facing labels only; the SQL maps them onto the `executed_at` column.

#### T-W2-02: Repository — `TransactionRepository` filter methods

**Files**:
- `services/portfolio/src/portfolio/application/ports/repositories.py` — add `list_by_portfolio_filtered(portfolio_id, tenant_id, filter: TransactionFilter) -> tuple[list[Transaction], int]` to `TransactionRepository` ABC; add `list_by_portfolio_ids_filtered(...)` for ROOT case
- `services/portfolio/src/portfolio/infrastructure/db/repositories/transaction.py` — implement both methods; SQL uses `AND` predicates for each non-null filter field; `from_date`/`to_date` filter on `CAST(executed_at AS DATE)` (the domain field is `executed_at: datetime`, not `transaction_date`); `ticker` filter uses `ILIKE :ticker || '%'` on a JOIN with `instruments`; uses `COUNT(*) OVER()` window for total; validates `from_date`/`to_date` as `CAST(:param AS date)` (BP-180 guard)

#### T-W2-03: Application — `ListTransactionsUseCase` filter support

**Files**:
- `services/portfolio/src/portfolio/application/use_cases/read_models.py` — update `ListTransactionsUseCase.execute()` to accept an optional `filter: TransactionFilter | None = None`; when present, call the new filtered repository methods; when absent, fall back to existing `list_by_portfolio()` (backward-compatible)

#### T-W2-04: API route — update `GET /api/v1/portfolios/{id}/transactions`

**Files**:
- `services/portfolio/src/portfolio/api/routes/transaction.py` — add `from_date: date | None = Query(None)`, `to_date: date | None = Query(None)`, `transaction_type: list[str] | None = Query(None)`, `ticker: str | None = Query(None)` query params; validate `transaction_type` values against `TransactionType` enum (return 422 on invalid value); construct `TransactionFilter` and pass to use case
- `services/portfolio/src/portfolio/api/schemas.py` — add `TransactionListResponse` with `total: int` field (update if not already present to reflect filtered count)

#### T-W2-05: Application — `ExportTransactionsUseCase`

**Files**:
- `services/portfolio/src/portfolio/application/use_cases/export_transactions.py` (new) — accepts `portfolio_id`, `tenant_id`, `owner_id`, `filter: TransactionFilter`, `cost_basis_method: CostBasisMethod`
- Logic:
  1. Fetch all matching transactions (no pagination — streaming export)
  2. Replay FIFO/AVCO in chronological order to compute `cost_basis_per_unit` and `realized_pnl` per SELL row
  3. Yield CSV rows as `Iterator[dict]`; caller streams to HTTP response
  4. CSV injection guard: prefix cells starting with `=`, `+`, `-`, `@` with `'`
- CSV column mapping (domain field names): `date` ← `executed_at.date()`, `price` ← `transaction.price` (NOT `price_per_unit` — that field does not exist), `total_value` ← computed `quantity × price`, `description` ← `transaction.description` (replaces non-existent `notes` field)
- Uses `ReadOnlyUnitOfWork` (R27)

#### T-W2-06: API route — `GET /api/v1/portfolios/{id}/transactions/export`

**Files**:
- `services/portfolio/src/portfolio/api/routes/transaction.py` — add new route `GET /{portfolio_id}/transactions/export`; uses `StreamingResponse` with `media_type="text/csv"`; sets `Content-Disposition: attachment; filename="transactions_{portfolio_id}_{from_date}_{to_date}.csv"`; calls `ExportTransactionsUseCase`

#### T-W2-07: S9 proxy routes

**Files**:
- `services/api-gateway/src/api_gateway/api/routes/portfolio.py` — add pass-through for `GET /v1/portfolio/portfolios/{id}/transactions` new query params; add new proxy route `GET /v1/portfolio/portfolios/{id}/transactions/export` (streaming pass-through, no response body buffering)

#### T-W2-08: Tests

**Files**:
- `services/portfolio/tests/unit/use_cases/test_list_transactions_filtered.py` (new):
  - `from_date` filter: only returns transactions on/after date
  - `to_date` filter: only returns transactions on/before date
  - `transaction_types` filter: BUY+SELL excludes DIVIDEND
  - `ticker` filter: case-insensitive prefix match
  - Combined filters (date + type + ticker): AND semantics
  - Total count reflects filtered set, not total unfiltered
  - 5-year cap exceeded: raises 400 (via ValidationError)
  - Invalid `transaction_type` value: raises 422
- `services/portfolio/tests/unit/use_cases/test_export_transactions.py` (new):
  - CSV column order and header names
  - CSV injection escaping (`=SUM(...)` → `'=SUM(...)`)
  - Empty result: valid CSV with headers only
  - FIFO cost basis computed correctly across interleaved rows
- `services/portfolio/tests/integration/test_transaction_export.py` (new):
  - Seed 10 transactions, export, assert row count = 10 and column names correct

### Validation Gate

```bash
cd services/portfolio && python -m pytest tests/ -m "unit" -k "transactions_filter or export" -v
cd services/portfolio && python -m pytest tests/ -m "integration" -k "export" -v
cd services/portfolio && python -m ruff check src/ tests/ && python -m mypy src/
```

**Complexity**: M

---

## Wave 3 — Backend: Holdings Response Enrichment (FR-4, FR-7)

**Goal**: Surface `brokerage_last_synced_at` and `brokerage_sync_error_count` in the holdings
response. Fixes G-4 (no last-synced timestamp) and G-7 (hidden sync errors).

**Dependencies**: None at the code level; semantically after W1 is merged so the holdings response
and the manual path share the same envelope.

### Tasks

#### T-W3-01: Application — `HoldingsResponseEnvelope` + `GetHoldingsUseCase` enrichment

**Files**:
- `services/portfolio/src/portfolio/application/use_cases/read_models.py` — add `@dataclass class HoldingsResponse` with fields: `holdings: list[EnrichedHolding]`, `brokerage_last_synced_at: datetime | None`, `brokerage_sync_error_count: int`; update `GetHoldingsUseCase.execute()` to return `HoldingsResponse` instead of `list[EnrichedHolding]`
- For BROKERAGE portfolios: join `brokerage_connections.last_synced_at` (single row lookup) and `COUNT(*) FROM brokerage_sync_errors WHERE brokerage_connection_id = :conn_id` (with index)
- For MANUAL + ROOT portfolios: both fields are `None` / `0`

#### T-W3-02: Repository — `BrokerageConnectionRepository` additions

**Files**:
- `services/portfolio/src/portfolio/application/ports/repositories.py` — add `get_by_portfolio_id(portfolio_id: UUID, tenant_id: UUID) -> BrokerageConnection | None` to `BrokerageConnectionRepository` ABC
- `services/portfolio/src/portfolio/infrastructure/db/repositories/brokerage_connection.py` — implement; also add `count_errors_for_connection(connection_id: UUID) -> int`
- `services/portfolio/src/portfolio/infrastructure/db/repositories/brokerage_sync_error.py` — add `count_for_connection(connection_id: UUID) -> int`

**Performance notes**:
- Index on `brokerage_sync_errors(brokerage_connection_id)` required — check migration history; add in migration 0026 if absent.

#### T-W3-03: Alembic migration 0026 — brokerage_sync_errors index

**Files**:
- `services/portfolio/alembic/versions/0026_add_brokerage_sync_errors_index.py` — `CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_brokerage_sync_errors_connection_id ON brokerage_sync_errors(brokerage_connection_id)` (skip if already exists)

#### T-W3-04: API route — update holdings response schema

**Files**:
- `services/portfolio/src/portfolio/api/routes/holding.py` — update handler to consume `HoldingsResponse`; update Pydantic response schema to include `brokerage_last_synced_at: datetime | None` and `brokerage_sync_error_count: int`
- `services/portfolio/src/portfolio/api/schemas.py` — update `HoldingsListResponse` (or equivalent)

#### T-W3-05: S9 proxy — pass through new fields

**Files**:
- `services/api-gateway/src/api_gateway/api/routes/portfolio.py` — ensure holdings proxy response passes `brokerage_last_synced_at` and `brokerage_sync_error_count` fields through to frontend (verify no field stripping in the S9 response model)

#### T-W3-06: Unit of Work — expose brokerage connection repo

**Files**:
- `services/portfolio/src/portfolio/application/ports/unit_of_work.py` — verify `ReadOnlyUnitOfWork` exposes `brokerage_connections` and `brokerage_sync_errors` repos; add if missing

#### T-W3-07: Tests

**Files**:
- `services/portfolio/tests/unit/use_cases/test_get_holdings_enriched.py` (new/extend):
  - BROKERAGE portfolio: `brokerage_last_synced_at` non-null, `brokerage_sync_error_count = 3`
  - BROKERAGE portfolio: new connection, `last_synced_at = None` → `brokerage_last_synced_at = None`
  - MANUAL portfolio: `brokerage_last_synced_at = None`, `brokerage_sync_error_count = 0`
  - ROOT portfolio: same as MANUAL (both null/0)
  - Count subquery uses index (explain plan in integration test)

### Validation Gate

```bash
cd services/portfolio && python -m pytest tests/ -m "unit" -k "holdings_enriched or brokerage_metadata" -v
cd services/portfolio && python -m pytest tests/ -m "integration" -k "holdings" -v
cd services/portfolio && python -m ruff check src/ tests/ && python -m mypy src/
cd services/api-gateway && python -m pytest tests/ -k "portfolio" -v
```

**Complexity**: M

---

## Wave 4 — Frontend: Holdings Tab Polish (FR-4, FR-5, FR-7, FR-8)

**Goal**: Surface last-synced timestamp and sync error badge in the Holdings tab header; add
onboarding empty states for MANUAL and BROKERAGE portfolios; update AddPositionDialog success toast.

**Dependencies**: W1 (manual holdings must be computed for empty-state logic to be correct) +
W3 (brokerage metadata fields must exist in the API response).

### Tasks

#### T-W4-01: TypeScript types — update holdings API response shape

**Files**:
- `apps/worldview-web/lib/api/portfolio.ts` (or equivalent API client) — add `brokerage_last_synced_at: string | null` and `brokerage_sync_error_count: number` to the holdings response type
- `apps/worldview-web/hooks/usePortfolioHoldings.ts` (or `usePortfolioBundle.ts`) — ensure the new fields flow through to consumers

#### T-W4-02: New component — `LastSyncedBadge`

**Files**:
- `apps/worldview-web/components/portfolio/LastSyncedBadge.tsx` (new):
  - Props: `lastSyncedAt: string | null`
  - Renders `"Last synced: {relative time}"` using `useFormattedTimestamp` hook
  - `null` → renders `"Never synced"` in muted text
  - No badge for non-BROKERAGE portfolios (caller controls visibility)

#### T-W4-03: New component — `SyncErrorBadge`

**Files**:
- `apps/worldview-web/components/portfolio/SyncErrorBadge.tsx` (new):
  - Props: `errorCount: number; onClickScrollToErrors: () => void`
  - Renders red `●` dot + count when `errorCount > 0`; hidden when 0
  - `onClick` calls `onClickScrollToErrors` prop
  - Heavy inline comments explaining the badge placement and color rationale

#### T-W4-04: New component — `ManualPortfolioEmptyState`

**Files**:
- `apps/worldview-web/components/portfolio/ManualPortfolioEmptyState.tsx` (new):
  - Renders headline "No positions yet", body copy per PRD §7.2, primary CTA "Record Transaction" button
  - CTA `onClick` receives an `onOpenAddPosition: () => void` prop (passed from HoldingsTab)
  - Uses shadcn/ui `Button` (variant="default"), no custom styles
  - `BrokerageEmptyState` component: separate message "Awaiting first sync — check back in a few minutes" (already exists at `components/portfolio/BrokerageEmptyState.tsx` — extend or replace with correct copy)

#### T-W4-05: Wire `HoldingsTab` — empty states + badges

**Files**:
- `apps/worldview-web/features/portfolio/components/HoldingsTab.tsx`:
  - When `portfolio.kind === "manual"` and `holdings.length === 0`: render `ManualPortfolioEmptyState` with `onOpenAddPosition` wired to existing Add Position dialog open state. (Kind values are lowercase per `PortfolioKind` StrEnum: `"manual"`, `"brokerage"`, `"root"` — confirmed by existing frontend usage `portfolio.kind === "root"` in `usePortfolioData.ts`.)
  - When `portfolio.kind === "brokerage"` and `holdings.length === 0`: render `BrokerageEmptyState`
  - In tab header: render `LastSyncedBadge` (`kind === "brokerage"` only) and `SyncErrorBadge` (`kind === "brokerage"` only, when `brokerage_sync_error_count > 0`)
  - `onClickScrollToErrors` scrolls to or expands the existing `BrokerageStatusBanner` component

#### T-W4-06: Update `AddPositionDialog` success toast (FR-8)

**Files**:
- `apps/worldview-web/features/portfolio/components/AddPositionDialog.tsx`:
  - On success toast, if `portfolio.kind === "manual"`: show copy "Transaction recorded. Holdings will reflect this trade within seconds."
  - For non-manual portfolios: retain existing generic copy
  - Toast auto-dismisses after 5 seconds (use `{ duration: 5000 }` on sonner/toast)

#### T-W4-07: Tests

**Files**:
- `apps/worldview-web/components/portfolio/__tests__/LastSyncedBadge.test.tsx` (new):
  - Renders relative time when `lastSyncedAt` is a valid ISO string
  - Renders "Never synced" when `lastSyncedAt` is null
- `apps/worldview-web/components/portfolio/__tests__/SyncErrorBadge.test.tsx` (new):
  - Renders red dot + count when `errorCount > 0`
  - Renders nothing when `errorCount === 0`
  - `onClick` calls `onClickScrollToErrors` prop
- `apps/worldview-web/components/portfolio/__tests__/ManualPortfolioEmptyState.test.tsx` (new):
  - Renders headline, body copy, and CTA button
  - CTA button calls `onOpenAddPosition` on click
- `apps/worldview-web/features/portfolio/components/__tests__/HoldingsTab.test.tsx` (extend):
  - `kind="manual"` + empty holdings: renders `ManualPortfolioEmptyState`
  - `kind="brokerage"` + empty holdings: renders `BrokerageEmptyState`
  - `kind="brokerage"` + `brokerage_sync_error_count > 0`: renders `SyncErrorBadge`
  - `kind="manual"` + non-empty holdings: renders AG Grid, not empty state
- `apps/worldview-web/features/portfolio/components/__tests__/AddPositionDialog.test.tsx` (extend):
  - Success for `kind="manual"` portfolio: toast copy contains "within seconds"
  - Success for `kind="brokerage"` portfolio: generic toast copy

### Validation Gate

```bash
cd apps/worldview-web && pnpm vitest run --reporter=verbose features/portfolio components/portfolio/LastSyncedBadge components/portfolio/SyncErrorBadge components/portfolio/ManualPortfolioEmptyState
cd apps/worldview-web && pnpm tsc --noEmit
```

**Complexity**: M

---

## Wave 5 — Frontend: Transaction UX + Filters + "Close Position" (FR-6, FR-9, FR-10)

**Goal**: Wire `TransactionFilterBar` to backend query params (instead of client-side filtering);
add CSV export button; add "Close Position" AG Grid context menu; add ROOT portfolio popover.

**Dependencies**: W2 (backend filter params must exist) + W3/W4 for API shape consistency.

### Tasks

#### T-W5-01: Update `useTransactionsFilterState` hook — wire to backend

**Files**:
- `apps/worldview-web/features/portfolio/hooks/useTransactionsFilterState.ts` — extend existing hook to emit `from_date`, `to_date`, `transaction_types`, `ticker` as URL search params (or TanStack Query key parts) instead of driving client-side array filtering; 300 ms debounce on ticker text input; pagination resets to page 1 on filter change

#### T-W5-02: Update `TransactionsFilterBar` — full filter UI

**Files**:
- `apps/worldview-web/components/portfolio/TransactionsFilterBar.tsx` — extend existing component:
  - Add date range pickers (`from_date` / `to_date`) using shadcn/ui `DatePicker` or `Calendar`
  - Transaction type multi-select: checkboxes for BUY, SELL, DIVIDEND, DEPOSIT, WITHDRAWAL, INTEREST, FEE (7 types)
  - Ticker text input with 300 ms debounce (already partially exists — wire to backend param)
  - "Clear filters" button: resets all filter state
  - Pagination total now comes from backend `total` field (not `holdings.length`)

#### T-W5-03: Update `TransactionsTab` — use backend totals + render filter bar

**Files**:
- `apps/worldview-web/features/portfolio/components/TransactionsTab.tsx`:
  - Remove client-side type-toggle filtering (use backend `transaction_type` param instead)
  - Pass `filter` object to `GET /v1/portfolio/portfolios/{id}/transactions` query
  - Pagination uses `total` from API response (not local array length)
  - Render `TransactionFilterBar` at the top

#### T-W5-04: New component — `ExportTransactionsButton`

**Files**:
- `apps/worldview-web/components/portfolio/ExportTransactionsButton.tsx` (new):
  - Props: `portfolioId: string; filter: TransactionFilter`
  - On click: fetch `GET /v1/portfolio/portfolios/{id}/transactions/export?...` with current filter params; trigger browser file download via `URL.createObjectURL(blob)`
  - Shows loading spinner while downloading; shows error toast on failure
  - Renders an "Export CSV" button using shadcn/ui `Button` (variant="outline")
  - Heavy inline comments explaining the streaming download approach

#### T-W5-05: New component — `ClosePositionDialog`

**Files**:
- `apps/worldview-web/components/portfolio/ClosePositionDialog.tsx` (new):
  - Props: `holding: Holding; portfolioId: string; onSuccess: () => void; onClose: () => void`
  - Form fields per PRD §7.2: Ticker (read-only), Quantity (read-only, from holding), Sale Price (editable, required), Trade Date (date picker, default = today)
  - On confirm: `POST /v1/portfolio/portfolios/{id}/transactions` with `{ transaction_type: "TRADE", trade_side: "SELL", quantity: holding.quantity, price_per_unit: enteredPrice, transaction_date: selectedDate, instrument_id: holding.instrument_id, currency: holding.currency }`
  - On success: toast "Position closed. Holdings will update within seconds." + call `onSuccess()` (triggers holdings refetch)
  - On error: toast with error message from API
  - Lazy-loaded via `React.lazy` + `Suspense` (not in initial bundle)

#### T-W5-06: Wire "Close Position" into `SemanticHoldingsTable` AG Grid

**Files**:
- `apps/worldview-web/components/portfolio/SemanticHoldingsTable.tsx`:
  - Add AG Grid `getContextMenuItems` callback
  - "Close Position" item visible only when `row.quantity > 0` and `portfolio.kind !== "root"` (kind is lowercase — `"root"`, not `"ROOT"`)
  - On click: set state to open `ClosePositionDialog` with the selected holding's data
  - Render `ClosePositionDialog` lazily when open

#### T-W5-07: New component — `RootPortfolioPopover`

**Files**:
- `apps/worldview-web/components/portfolio/RootPortfolioPopover.tsx` (new):
  - Renders an `ℹ` icon that opens a shadcn/ui `Popover` with the "All Accounts" explanation copy per PRD §4 FR-9
  - Dismissible: sets `localStorage` key `worldview:root_portfolio_popover_dismissed = "1"` on dismiss
  - Does not re-appear after dismissal (checked on mount)
  - Renders only when `portfolio.kind === "root"` (lowercase — consistent with existing `usePortfolioData.ts` check)

#### T-W5-08: Wire `RootPortfolioPopover` into page header + selector

**Files**:
- `apps/worldview-web/features/portfolio/components/PortfolioPageHeader.tsx` — add `ℹ` icon + `RootPortfolioPopover` when active portfolio `kind === "root"` (the portfolio selector dropdown is also embedded in this component — confirmed by code inspection; there is no separate `PortfolioSelector.tsx` file)
- `apps/worldview-web/app/(app)/portfolio/layout.tsx` — if the portfolio switcher is rendered at layout level, add `ℹ` icon next to "All Accounts" entry there; otherwise the `PortfolioPageHeader.tsx` change above covers both the header and selector

#### T-W5-09: Tests

**Files**:
- `apps/worldview-web/features/portfolio/hooks/__tests__/useTransactionsFilterState.test.ts` (extend):
  - Filter change dispatches correct backend query params
  - Ticker debounce: rapid typing → single request after 300 ms
  - Pagination resets to page 1 on filter change
  - "Clear" resets all params
- `apps/worldview-web/components/portfolio/__tests__/ExportTransactionsButton.test.tsx` (new):
  - Click triggers fetch to export endpoint
  - Loading state shown during download
  - Error toast on API failure
- `apps/worldview-web/components/portfolio/__tests__/ClosePositionDialog.test.tsx` (new):
  - Ticker field is read-only
  - Quantity field is read-only and pre-filled from holding
  - Confirm dispatches correct payload (TRADE, SELL, holding qty)
  - Error from API renders error toast
- `apps/worldview-web/components/portfolio/__tests__/RootPortfolioPopover.test.tsx` (new):
  - Renders for `kind="root"` portfolio
  - Does not render for `kind="manual"` / `kind="brokerage"`
  - Dismiss sets localStorage key `worldview:root_portfolio_popover_dismissed`
  - Does not render on re-mount after dismissal

### Validation Gate

```bash
cd apps/worldview-web && pnpm vitest run --reporter=verbose features/portfolio/hooks/__tests__/useTransactionsFilterState components/portfolio/__tests__/ExportTransactionsButton components/portfolio/__tests__/ClosePositionDialog components/portfolio/__tests__/RootPortfolioPopover
cd apps/worldview-web && pnpm tsc --noEmit
```

**Complexity**: L

---

## Wave 6 — Backend + Frontend: Cost Basis Method Selector + Dividend Yield (FR-11, FR-12)

**Goal**: Per-portfolio FIFO/AVCO selector (optional, low-priority); dividend yield column in
holdings table (sourced from S9 aggregation, no S1 schema changes).

**Dependencies**: W1 (CostBasisMethod enum and domain changes already shipped) + W3 + W5 (settings
panel in UI already exists from W5 or prior waves).

### Tasks

#### T-W6-01: API route — `PATCH /api/v1/portfolios/{id}` accepts `cost_basis_method`

**Files**:
- `services/portfolio/src/portfolio/api/routes/portfolio.py` — extend `PATCH` handler to accept `cost_basis_method: CostBasisMethod | None` in body; call `UpdatePortfolioUseCase` with the new field
- `services/portfolio/src/portfolio/application/use_cases/portfolio_ops.py` — add `cost_basis_method` to `UpdatePortfolioCommand`; persist via `uow.portfolios.save()`

#### T-W6-02: S9 proxy — `PATCH /v1/portfolio/portfolios/{id}`

**Files**:
- `services/api-gateway/src/api_gateway/api/routes/portfolio.py` — ensure `PATCH` proxy passes `cost_basis_method` field through

#### T-W6-03: Frontend — `CostBasisMethodSelector` in portfolio settings

**Files**:
- `apps/worldview-web/features/portfolio/components/CreatePortfolioDialog.tsx` (extend) — add `<Select>` for cost basis method (FIFO / Average Cost) on portfolio creation
- `apps/worldview-web/features/portfolio/components/EditPortfolioDialog.tsx` (**new** — this file does not currently exist; `CreatePortfolioDialog.tsx` exists but there is no edit variant; create a new dialog that patches `cost_basis_method` via `PATCH /v1/portfolio/portfolios/{id}`)

#### T-W6-04: S9 aggregation — `annualized_dividend_yield` field (FR-12)

**Files**:
- `services/api-gateway/src/api_gateway/api/routes/portfolio.py` — in the holdings proxy handler, fan out to `GET /v1/market/fundamentals/batch?tickers=...` (or per-ticker fundamentals endpoint) to fetch `annual_dividend_yield`; join by ticker into the holdings response items; null when not available
- Holdings proxy response type extended with `annualized_dividend_yield: float | null` per holding item
- Valkey cache for the fundamentals batch call (15-min TTL) to avoid per-request fan-out latency

#### T-W6-05: Frontend — `DIV YLD` column in `SemanticHoldingsTable`

**Files**:
- `apps/worldview-web/components/portfolio/ag-holdings-columns.tsx` — add `DIV YLD` column; hidden by default in column visibility state; renders `—` when `annualized_dividend_yield` is null; renders formatted percentage (e.g. `"2.4%"`) when non-null
- `apps/worldview-web/components/portfolio/holdings-columns.tsx` — add corresponding column def

#### T-W6-06: Docs + TRACKING update

**Files**:
- `docs/services/portfolio.md` — document new `cost_basis_method` field, `ComputeManualHoldingsUseCase`, new Kafka topic, `ManualHoldingsWorker` cron
- `docs/services/api-gateway.md` — document new export endpoint + filter params + dividend yield aggregation
- `docs/plans/TRACKING.md` — mark PLAN-0114 active, all waves + status

#### T-W6-07: Tests

**Files**:
- `services/portfolio/tests/unit/use_cases/test_update_portfolio.py` (extend):
  - `PATCH` with `cost_basis_method = "AVCO"` persists the value
  - `PATCH` with invalid method: 422
- `apps/worldview-web/components/portfolio/__tests__/holdings-columns.test.ts` (extend):
  - `DIV YLD` column renders `—` for null
  - `DIV YLD` column renders `"2.4%"` for `0.024`
- `services/api-gateway/tests/unit/test_portfolio_holdings_proxy.py` (extend):
  - Holdings response includes `annualized_dividend_yield` per holding item from fundamentals join

### Validation Gate

```bash
cd services/portfolio && python -m pytest tests/ -m "unit" -k "cost_basis_method or update_portfolio" -v
cd services/api-gateway && python -m pytest tests/ -k "portfolio_holdings" -v
cd apps/worldview-web && pnpm vitest run --reporter=verbose components/portfolio/__tests__/holdings-columns
cd apps/worldview-web && pnpm tsc --noEmit
cd services/portfolio && python -m ruff check src/ tests/ && python -m mypy src/
```

**Complexity**: M

---

## Dependency Graph

```
W1 (manual holdings computation)
 ├── unblocks → W4 (HoldingsTab empty state: needs real holdings data to test empty→populated)
 └── shares domain changes with → W6 (CostBasisMethod enum, cost_basis_method column)

W2 (transaction filtering + CSV export)
 └── unblocks → W5 (filter bar uses backend params)

W3 (holdings response enrichment: brokerage metadata)
 └── unblocks → W4 (LastSyncedBadge + SyncErrorBadge need brokerage_last_synced_at + count)

W4 (Holdings tab polish)
 └── depends on W1 + W3

W5 (Transaction UX + ClosePositionDialog + RootPortfolioPopover)
 └── depends on W2

W6 (cost basis method selector + dividend yield)
 └── depends on W1 (CostBasisMethod enum) + W3 (holdings envelope) + W5 (settings panel)
```

**Recommended implementation order**: W1 + W2 (parallel) → W3 → W4 → W5 → W6

---

## Migration Summary

| # | Migration | Table | Change | Safe? |
|---|-----------|-------|--------|-------|
| 0024 | `add_portfolio_cost_basis_method` | `portfolios` | Add `cost_basis_method VARCHAR(8) NOT NULL DEFAULT 'FIFO'` | Yes — additive with default |
| 0025 | `add_holdings_cost_basis_columns` | `holdings`, `transactions` | Add nullable `cost_basis_per_unit`, `total_cost_basis` (new columns; `holdings` currently only has `average_cost`); `CREATE INDEX CONCURRENTLY` on `transactions(portfolio_id, executed_at, instrument_id)` (note: `executed_at` is the datetime field name, not `transaction_date`) | Yes — additive nullable + CONCURRENTLY |
| 0026 | `add_brokerage_sync_errors_index` | `brokerage_sync_errors` | `CREATE INDEX CONCURRENTLY IF NOT EXISTS` on `(brokerage_connection_id)` | Yes — IF NOT EXISTS guard |

All migrations are backward-compatible. Rollback: drop the new columns. No data loss.

---

## Process Topology Changes

| Process (new) | Module | Description |
|---------------|--------|-------------|
| `portfolio-manual-holdings-consumer` | `portfolio.infrastructure.messaging.consumers.manual_holdings_consumer_main` | Consumes `portfolio.holding.recompute_requested.v1`; triggers `ComputeManualHoldingsUseCase` |
| `portfolio-manual-holdings-worker` | `portfolio.workers.manual_holdings_worker` | Nightly 22:00 UTC cron; recomputes all MANUAL portfolios with at least 1 transaction |

---

## Observability

| Metric | Wave | Type | Notes |
|--------|------|------|-------|
| `portfolio_manual_holdings_recomputed_total` | W1 | counter | Labels: `trigger` (`event`/`scheduled`) |
| `portfolio_manual_holdings_recompute_duration_seconds` | W1 | histogram | Alert if p95 > 5 s |
| `portfolio_csv_export_rows_total` | W2 | counter | Track export usage |
| `portfolio_transaction_filter_latency_seconds` | W2 | histogram | Alert if p95 > 200 ms |

---

## Open Questions (resolved per PRD §17)

| OQ | Decision |
|----|----------|
| OQ-1 | Kafka topic `portfolio.holding.recompute_requested.v1` (not in-process queue) — consistency with platform patterns; nightly worker acts as fallback |
| OQ-2 | `cost_basis_method` is per-portfolio (not per-instrument) — sufficient for thesis scope |
| OQ-3 | FR-12 dividend yield sourced from S9 aggregation layer, joined from S3 market-data fundamentals — no S1 schema changes |
