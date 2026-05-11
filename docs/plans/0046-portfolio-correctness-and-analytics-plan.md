# PLAN-0046 — Portfolio Correctness & Analytics

**Created**: 2026-04-28
**Status**: draft
**Source audit**: `docs/audits/2026-04-28-qa-plan-0044-followup-report.md`
**Tracking**: `docs/plans/TRACKING.md`

---

## Problem Statement

PLAN-0044 closed but five gaps remain — confirmed by code-level investigation in the audit report:

1. **F-001 (CRITICAL)** Holdings quantity is inflated 8–10× vs. broker truth — caused by transaction-replay drift in the SnapTrade dual-path adapter
2. **F-002 (CRITICAL)** DIVIDEND rows show $0 total — adapter drops SnapTrade `amount` field
3. **F-003 (BLOCKING)** Watchlists always render empty — S1 has no `GET /watchlists/{id}/members`
4. **F-004 (MAJOR)** No root/aggregate portfolio per user
5. **F-005 (MAJOR)** No analytics: capital evolution, drawdown, volatility, Sharpe, exposure

## Non-Goals

- Manual transaction entry UI (out of scope; handled by brokerage sync)
- Multi-currency consolidation in root portfolio (single-currency only for v1)
- Risk-free rate as a dynamic feed (hard-code US 3M T-bill ~5.0% as a constant for v1)
- Brokerage `cash_balance` ingest (v1 treats cash=0; gross_exposure ≈ invested value)

## Codebase State (verified against source)

| Component | File | Current State | Delta |
|-----------|------|--------------|-------|
| SnapTrade adapter | `services/portfolio/src/portfolio/infrastructure/brokerage/snaptrade_client.py:198-355` | Dual-path activity feed, drops `amount`/`fee` | Add positions endpoint + capture amount/fee |
| Brokerage sync worker | `services/portfolio/src/portfolio/workers/brokerage_sync_worker.py:147-303` | Replays activities → mutates holdings | Snapshot-overwrite holdings after activity sync |
| `record_transaction` | `services/portfolio/src/portfolio/application/use_cases/record_transaction.py:147-159` | `apply_delta` mutates `holdings.quantity` | Drop holding mutation; transactions become history-only |
| `Transaction` entity / model | `domain/entities/transaction.py:26`, `infrastructure/db/models/transaction.py:30-32` | Has `fees`, no `amount` | Add `amount Numeric(18,8) NULL` |
| Watchlist routes | `services/portfolio/src/portfolio/api/routes/watchlist.py` | POST/DELETE on `/members`, no GET | Add `GET /watchlists/{id}/members` |
| `WatchlistMember` model | `services/portfolio/src/portfolio/infrastructure/db/models/watchlist.py` | `entity_id` only | Add denormalised `ticker`, `name`, `instrument_id` |
| `Portfolio` entity / table | `domain/entities/portfolio.py:14-43`, `alembic/versions/0001_initial_schema.py:58` | No `kind` flag | Add `kind ENUM` + partial unique on root |
| Provision use case | `application/use_cases/provision_user.py:102-126` | Creates Tenant+User only | Auto-create root portfolio |
| Holdings/Transactions queries | `application/use_cases/list_holdings*.py`, `list_transactions.py` | Single-portfolio | Detect `kind='root'` and fan out |
| Snapshots table | (none) | — | New `portfolio_value_snapshots` |
| Snapshot worker | (none) | — | New `PortfolioSnapshotWorker` daily at NYSE close |
| Analytics endpoints | (none) | — | New `value-history`, `exposure`, `risk-metrics` in S9 |
| Analytics frontend | (none) | — | New `PortfolioAnalyticsSection` + sub-components |
| Gateway watchlist mapping | `apps/worldview-web/lib/gateway.ts:165-182, 1058-1096` | Hard-codes `members: []` | Fetch members + populate |

## S9 / Cross-Service Endpoint Plan

| New endpoint | Owner | Shape |
|---|---|---|
| `GET /v1/watchlists/{id}/members` | S1 → S9 proxy | `[{entity_id, entity_type, ticker, name, instrument_id, added_at}]` |
| `GET /v1/portfolios/{id}/value-history?from&to&granularity` | S1 read of snapshots; S9 proxy | `{points: [{date, value, cost_basis, cash}]}` |
| `GET /v1/portfolios/{id}/exposure` | S1 use case | `{invested, cash, gross_exposure_pct, net_exposure_pct, leverage}` |
| `GET /v1/portfolios/{id}/risk-metrics?lookback_days` | S9 (computes from value-history + S3 SPY) | `{drawdown_max, drawdown_current, volatility_annualized, sharpe, sortino, beta_vs_spy}` |

---

## Wave 1 — Brokerage Adapter Correctness (F-001 + F-002)

**Goal**: Stop holding-quantity drift and capture dividend `amount` / trade `fee`.
**Depends on**: none — highest priority
**Estimated effort**: 4–6 hours
**Architecture layer**: domain + infrastructure (S1)

### T-46-1-01: Capture SnapTrade `amount` and `fee` end-to-end

**Type**: impl
**depends_on**: none
**blocks**: T-46-1-02 (so the new column is in the DB before the snapshot worker writes)
**Target files**:
- `services/portfolio/alembic/versions/0009_add_transaction_amount.py` (new)
- `services/portfolio/src/portfolio/domain/entities/transaction.py`
- `services/portfolio/src/portfolio/infrastructure/db/models/transaction.py`
- `services/portfolio/src/portfolio/application/ports/brokerage_client.py`
- `services/portfolio/src/portfolio/infrastructure/brokerage/snaptrade_client.py`
- `services/portfolio/src/portfolio/application/use_cases/record_transaction.py`
- `services/portfolio/src/portfolio/api/schemas/transactions.py`
- `apps/worldview-web/types/api.ts`
- `apps/worldview-web/lib/gateway.ts`
- `apps/worldview-web/components/portfolio/TransactionsTable.tsx`

**What to build**:
Add a real `amount` column to `transactions`. Capture both `amount` and `fee` from SnapTrade `UniversalActivity` and persist them. Frontend uses `tx.amount` for DIVIDEND total.

**Logic**:
1. Alembic 0009 — `op.add_column("transactions", sa.Column("amount", sa.Numeric(18, 8), nullable=True))` with default `NULL` (forward-compatible). No backfill (historical dividends will populate on next sync).
2. `Transaction` entity — add `amount: Decimal | None = None` field; preserve `fees: Decimal = Decimal(0)` for trade fees.
3. `TransactionModel` — add `amount` column; map in `to_entity` / `from_entity`.
4. `SnapTradeActivity` VO — add `amount: Decimal | None`, `fee: Decimal | None`.
5. `_parse_activity_list` (snaptrade_client.py:315-355) — read both fields with `Decimal(str(item.get("amount"))) if item.get("amount") is not None else None`.
6. `_process_activity` (brokerage_sync_worker.py:291-303) — pass `amount=activity.amount` and `fees=(activity.fee or Decimal(0))` to `RecordTransactionCommand`.
7. `RecordTransactionUseCase` — accept `amount` in command, persist on `Transaction`.
8. API schema — include `amount: Decimal | None` in `TransactionListItem`.
9. Frontend `Transaction` TS type — add `amount: number | null`.
10. `gateway.ts:856-858` — map `amount: tx.amount != null ? Number(tx.amount) : null`.
11. `TransactionsTable.tsx:181` — `const total = isDividend ? (tx.amount ?? 0) : tx.quantity * tx.price`.
12. Add a comment at the parse site documenting BP-263.

**Acceptance criteria**:
- [ ] Alembic upgrade + downgrade tested
- [ ] Re-sync a brokerage with a known dividend → DIV row shows correct cash amount
- [ ] BUY/SELL fee captured into `tx.fee`; total still computes from `quantity × price`
- [ ] Unit test: `_parse_activity_list` extracts `amount` and `fee` from a recorded SnapTrade payload
- [ ] No mypy/ruff errors

---

### T-46-1-02: Add SnapTrade positions endpoint to adapter

**Type**: impl
**depends_on**: none (parallelisable with T-46-1-01)
**blocks**: T-46-1-03
**Target files**:
- `services/portfolio/src/portfolio/application/ports/brokerage_client.py` — new `SnapTradePosition` VO + `get_account_positions` method
- `services/portfolio/src/portfolio/infrastructure/brokerage/snaptrade_client.py` — implementation calling `account_information.get_user_account_positions`

**What to build**:
A read of "current positions" (quantity per symbol per account) from SnapTrade — the broker's snapshot of what the account holds *right now*.

**Logic**:
1. `SnapTradePosition` VO: `account_id, symbol, quantity, average_purchase_price, currency`.
2. `BrokerageClient.get_account_positions(user, account_id) -> list[SnapTradePosition]` port method.
3. `SnapTradeClient.get_account_positions` implementation: `await self._client.account_information.get_user_account_positions(...)`. Iterate response, parse to VO. Handle missing symbol (skip), zero quantity (include — represents a closed position the user may want to see).
4. Unit test using a recorded fixture from SnapTrade docs.

**Acceptance criteria**:
- [ ] `SnapTradePosition` VO has all required fields
- [ ] `get_account_positions` port + implementation in place
- [ ] Unit test with mock SDK response
- [ ] No mypy/ruff errors

---

### T-46-1-03: Snapshot-based holdings overwrite

**Type**: impl
**depends_on**: T-46-1-02
**blocks**: T-46-1-04
**Target files**:
- `services/portfolio/src/portfolio/application/use_cases/upsert_holdings_from_snapshot.py` (new)
- `services/portfolio/src/portfolio/workers/brokerage_sync_worker.py:147-194`
- `services/portfolio/src/portfolio/application/use_cases/record_transaction.py:147-159`
- `services/portfolio/src/portfolio/domain/entities/holding.py:31-55` (remove `apply_delta` callsites; keep method for backward compatibility)

**What to build**:
After the activity sync runs, fetch positions from SnapTrade and overwrite `holdings` for that portfolio. Drop the `apply_delta` mutation from `record_transaction` so transactions become history-only.

**Logic**:
1. New `UpsertHoldingsFromSnapshotUseCase`:
   - Input: `portfolio_id, tenant_id, list[SnapTradePosition]`
   - For each position: resolve `instrument_id` from symbol via S3 (already done elsewhere — reuse `instrument_resolver`)
   - Upsert `Holding(portfolio_id, instrument_id, quantity=position.quantity, average_cost=position.average_purchase_price)`
   - Delete holdings present in DB but absent from snapshot (closed positions)
2. `brokerage_sync_worker.py` orchestration: after activity loop completes, call `get_account_positions` for each linked account, aggregate by symbol (multi-account user), call `UpsertHoldingsFromSnapshotUseCase`.
3. In `record_transaction.py:147-159`, remove the `holding.apply_delta` calls. Transactions still write to the `transactions` table.
4. Reject `kind='root'` portfolios at `RecordTransactionUseCase` entry (defensive — root has no transactions of its own).
5. Add a comment citing BP-264.

**Acceptance criteria**:
- [ ] After sync, `holdings.quantity` equals SnapTrade position quantity (within 1e-8)
- [ ] Closing a position upstream → snapshot returns 0 → our holding row is deleted
- [ ] Transactions table still grows on each sync (history preserved)
- [ ] Integration test simulating duplicate activities verifies holdings stay correct
- [ ] No mypy/ruff errors

---

### T-46-1-04: Data cleanup migration for affected portfolios

**Type**: impl
**depends_on**: T-46-1-03
**blocks**: none
**Target files**:
- `services/portfolio/scripts/repair_holdings_after_replay_drift.py` (new ad-hoc script)
- Documentation in `docs/services/portfolio.md` (add a "Operational Recovery" section)

**What to build**:
A one-shot script to:
1. Zero-out `holdings.quantity` for all portfolios with `brokerage_connection` rows.
2. Trigger `BrokerageTransactionSyncWorker` to re-sync (which now uses snapshot). Holdings will be repopulated correctly from the broker's truth.
3. Detect duplicate transactions (same `instrument_id, trade_date, quantity, price` within a portfolio) and emit a report. Operator decides whether to delete (transactions are history; duplicates only matter if anything still reads them aggregatively).

**Acceptance criteria**:
- [ ] Script runs idempotently (safe to re-run)
- [ ] Dry-run mode (`--dry-run`) reports what would change without mutating
- [ ] Operational guide documents the recovery flow

---

### Wave 1 Validation Gate

- [ ] `cd services/portfolio && python -m pytest tests/ -m unit -v` passes
- [ ] `cd services/portfolio && python -m pytest tests/ -m integration -v` passes
- [ ] `ruff check services/portfolio/src` passes
- [ ] `mypy services/portfolio/src --config-file services/portfolio/mypy.ini` passes
- [ ] Manual: re-sync a real TastyTrade account → holdings match TastyTrade UI exactly
- [ ] Manual: dividend rows in Transactions tab show non-zero amounts

---

## Wave 2 — Watchlist Members End-to-End (F-003)

**Goal**: Make the watchlist tab actually show its members.
**Depends on**: none (parallelisable with Wave 1)
**Estimated effort**: 3–4 hours
**Architecture layer**: S1 + frontend

### T-46-2-01: Denormalise ticker/name into `watchlist_member`

**Type**: impl
**depends_on**: none
**blocks**: T-46-2-02
**Target files**:
- `services/portfolio/alembic/versions/0010_add_watchlist_member_ticker_name.py` (new)
- `services/portfolio/src/portfolio/infrastructure/db/models/watchlist.py`
- `services/portfolio/src/portfolio/domain/entities/watchlist.py`
- `services/portfolio/src/portfolio/application/use_cases/add_watchlist_member.py`

**What to build**:
Add `ticker VARCHAR(20) NULL`, `name VARCHAR(255) NULL`, `instrument_id UUID NULL` columns to `watchlist_member`. On `add_member`, resolve these via the existing instrument/KG resolver and persist. This avoids a cross-service JOIN at read time (R9 compliance).

**Acceptance criteria**:
- [ ] Migration adds the three columns nullable + forward-compatible
- [ ] `AddWatchlistMemberUseCase` resolves and persists ticker/name/instrument_id at add-time
- [ ] Existing rows backfilled by a separate script (best-effort; user can re-add if missing)

---

### T-46-2-02: New `GET /v1/watchlists/{id}/members` route

**Type**: impl
**depends_on**: T-46-2-01
**blocks**: T-46-2-03
**Target files**:
- `services/portfolio/src/portfolio/application/use_cases/list_watchlist_members.py` (new)
- `services/portfolio/src/portfolio/infrastructure/db/repositories/watchlist.py`
- `services/portfolio/src/portfolio/api/routes/watchlist.py`
- `services/portfolio/src/portfolio/api/schemas/watchlist.py`
- `services/api-gateway/src/api_gateway/routes/proxy.py` (proxy to S1)

**What to build**:
S1 returns `WatchlistMemberListResponse` with `[{entity_id, entity_type, ticker, name, instrument_id, added_at}]`. S9 proxies it under the same path.

**Acceptance criteria**:
- [ ] `GET /v1/watchlists/{id}/members` returns 200 with members
- [ ] Returns 404 if watchlist doesn't belong to caller
- [ ] Pagination via standard `limit`/`offset` (default 100)
- [ ] Contract test against the proxied S9 path

---

### T-46-2-03: Frontend gateway + UI wiring

**Type**: impl
**depends_on**: T-46-2-02
**blocks**: none
**Target files**:
- `apps/worldview-web/lib/gateway.ts:165-182, 1058-1096`
- `apps/worldview-web/components/portfolio/WatchlistsTabPanel.tsx`
- `apps/worldview-web/app/(app)/portfolio/page.tsx:697-711`

**What to build**:
- New `getWatchlistMembers(watchlistId)` gateway method
- Modify `getWatchlists()` to call members for the active watchlist (lazy: only the selected one)
- Update `mapRawWatchlist` to accept an optional members array
- Cache invalidation on add/remove/delete watchlist

**Acceptance criteria**:
- [ ] Adding a symbol → row appears in <500ms after success
- [ ] Removing a symbol → row disappears
- [ ] Quotes load for displayed members
- [ ] Empty state shown only when `members.length === 0`

---

### Wave 2 Validation Gate

- [ ] S1 unit + integration tests pass
- [ ] Frontend Vitest passes; Playwright test for "add → see → delete" passes
- [ ] Manual smoke: full add/remove/create/delete flow works on a real account

---

## Wave 3 — Root Portfolio (F-004)

**Goal**: Auto-create an undeletable "All Accounts" portfolio per user that aggregates positions from all other portfolios.
**Depends on**: Wave 1 (snapshot-based holdings make aggregation trivial)
**Estimated effort**: 4–6 hours
**Architecture layer**: S1 domain + application

### T-46-3-01: Schema + entity for `kind`

**Type**: impl
**depends_on**: Wave 1 complete
**blocks**: T-46-3-02
**Target files**:
- `services/portfolio/alembic/versions/0011_portfolio_kind.py` (new)
- `services/portfolio/src/portfolio/domain/enums.py`
- `services/portfolio/src/portfolio/domain/entities/portfolio.py`
- `services/portfolio/src/portfolio/infrastructure/db/models/portfolio.py`

**What to build**:
- `PortfolioKind` enum: `MANUAL | BROKERAGE | ROOT`
- `kind VARCHAR(16) NOT NULL DEFAULT 'manual'` with `CHECK (kind IN ('manual','brokerage','root'))`
- `CREATE UNIQUE INDEX uq_portfolios_owner_root ON portfolios(owner_id) WHERE kind = 'root'`
- `CHECK (NOT (kind = 'root' AND status = 'archived'))`
- `Portfolio.kind: PortfolioKind` field (default `MANUAL`)
- `Portfolio.archive()` raises `RootPortfolioNotArchivableError` if `kind == ROOT`

**Acceptance criteria**:
- [ ] Migration upgrade + downgrade tested
- [ ] All existing portfolios get `kind='manual'` via DEFAULT
- [ ] Domain unit test for archive guard

---

### T-46-3-02: Auto-provision root on user creation

**Type**: impl
**depends_on**: T-46-3-01
**blocks**: T-46-3-03
**Target files**:
- `services/portfolio/src/portfolio/application/use_cases/ensure_root_portfolio.py` (new)
- `services/portfolio/src/portfolio/application/use_cases/provision_user.py:102-126`
- `services/portfolio/scripts/backfill_root_portfolios.py` (new)

**What to build**:
- `EnsureRootPortfolioUseCase`: idempotent — creates `Portfolio(name='All Accounts', kind=ROOT, owner_id=user.id, currency='USD')` if not exists.
- Call it at the end of `provision_user.py` (steps 2 and 4 — linked existing user without portfolios, and brand new user).
- Backfill script: for every existing user without a root, create one.

**Acceptance criteria**:
- [ ] New user provisioning creates root
- [ ] Repeated provisioning doesn't duplicate
- [ ] Backfill script idempotent
- [ ] Cannot delete root via `DELETE /v1/portfolios/{id}` — returns 400 with `RootPortfolioNotArchivableError`

---

### T-46-3-03: Holdings + transactions fan-out for root

**Type**: impl
**depends_on**: T-46-3-02
**blocks**: T-46-3-04
**Target files**:
- `services/portfolio/src/portfolio/application/use_cases/list_holdings_enriched.py` (or wherever today's GET /holdings lives)
- `services/portfolio/src/portfolio/application/use_cases/list_transactions.py`
- `services/portfolio/src/portfolio/infrastructure/db/repositories/holding.py`

**What to build**:
- `GetHoldingsUseCase` detects `portfolio.kind == ROOT`. Replaces `WHERE portfolio_id = X` with `WHERE portfolio_id IN (SELECT id FROM portfolios WHERE owner_id = ? AND kind != 'root' AND status = 'active')`.
- Aggregation by `instrument_id`: `SUM(quantity)` and qty-weighted average cost: `SUM(qty * avg_cost) / NULLIF(SUM(qty), 0)`.
- Same fan-out for `ListTransactionsUseCase` (no aggregation — just UNION).
- Defensive: `RecordTransactionUseCase` rejects `portfolio.kind == ROOT`.

**Acceptance criteria**:
- [ ] Selecting root portfolio in UI shows aggregated holdings (sum of all sub-portfolio quantities by ticker)
- [ ] Transactions tab on root shows union of all sub-portfolio transactions sorted by date desc
- [ ] No transactions can be recorded against root (returns 400)

---

### T-46-3-04: Frontend UX — root badge + delete guard

**Type**: impl
**depends_on**: T-46-3-03
**blocks**: none
**Target files**:
- `apps/worldview-web/app/(app)/portfolio/page.tsx`
- `apps/worldview-web/components/portfolio/PortfolioSelector.tsx` (or wherever the dropdown is)
- `apps/worldview-web/types/api.ts`

**What to build**:
- Add `kind: "manual" | "brokerage" | "root"` to `Portfolio` TS type.
- In selector, show root portfolio first with an "ALL" badge.
- Hide/disable Delete button when active portfolio has `kind === "root"`.
- "New Portfolio" button creates `kind='manual'` (default).
- Default-select root on first page load.

**Acceptance criteria**:
- [ ] Root portfolio appears at top of selector with badge
- [ ] Delete button disabled with tooltip "Cannot delete the aggregate portfolio"
- [ ] First load defaults to root
- [ ] No regressions on existing portfolio selection

---

### Wave 3 Validation Gate

- [ ] All S1 tests pass
- [ ] Frontend lint/typecheck/Vitest pass
- [ ] Manual: create new portfolio → appears alongside root; delete it → root remains; verify holdings on root = sum of holdings on others

---

## Wave 4 — Daily Snapshot Foundation (F-005, part 1)

**Goal**: Build the data plumbing required for any time-series analytics.
**Depends on**: Wave 1 (snapshot-based holdings ensure correct snapshot values)
**Estimated effort**: 6–8 hours
**Architecture layer**: S1 + new worker

### T-46-4-01: Snapshot table + repository

**Type**: impl
**depends_on**: Wave 1
**blocks**: T-46-4-02
**Target files**:
- `services/portfolio/alembic/versions/0012_portfolio_value_snapshots.py` (new)
- `services/portfolio/src/portfolio/domain/entities/portfolio_value_snapshot.py` (new)
- `services/portfolio/src/portfolio/infrastructure/db/models/portfolio_value_snapshot.py` (new)
- `services/portfolio/src/portfolio/infrastructure/db/repositories/portfolio_value_snapshot.py` (new)
- `services/portfolio/src/portfolio/application/ports/repositories.py`

**What to build**:
- Table `portfolio_value_snapshots`:
  - `id UUID PRIMARY KEY`
  - `portfolio_id UUID NOT NULL REFERENCES portfolios(id)`
  - `snapshot_date DATE NOT NULL`
  - `total_value NUMERIC(20,8) NOT NULL`
  - `total_cost NUMERIC(20,8) NOT NULL`
  - `cash_value NUMERIC(20,8) NOT NULL DEFAULT 0`
  - `tenant_id UUID NOT NULL` (multi-tenant)
  - `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
  - `UNIQUE (portfolio_id, snapshot_date)` for idempotent re-runs
  - Index on `(portfolio_id, snapshot_date DESC)` for range queries
- Repository interface + implementation: `upsert(snapshot)`, `list_range(portfolio_id, from, to)`, `get_latest(portfolio_id)`.

**Acceptance criteria**:
- [ ] Migration up/down tested
- [ ] Repository unit test
- [ ] Idempotent upsert verified (re-running for same date doesn't duplicate)

---

### T-46-4-02: PortfolioSnapshotWorker

**Type**: impl
**depends_on**: T-46-4-01
**blocks**: T-46-4-03
**Target files**:
- `services/portfolio/src/portfolio/workers/portfolio_snapshot_worker.py` (new)
- `services/portfolio/src/portfolio/application/use_cases/compute_portfolio_value.py` (new)
- `services/portfolio/Dockerfile.snapshot-worker` (new) and entry in `infra/docker-compose/*.yml`

**What to build**:
- `ComputePortfolioValueUseCase`:
  - Input: `portfolio_id, as_of_date`
  - For each holding in portfolio (excluding root): get close price on `as_of_date` from S3 (`/api/v1/ohlcv/single?instrument_id=X&date=Y`)
  - Compute `total_value = Σ quantity × close`, `total_cost = Σ quantity × avg_cost`
  - Treat missing prices as zero contribution + log warning (don't fail the whole snapshot)
- `PortfolioSnapshotWorker`:
  - Cron-style: run at 21:30 UTC daily (after NYSE close)
  - For each non-root portfolio with status=active, call `ComputePortfolioValueUseCase` for today
  - Idempotent — safe to re-run if missed
  - Skip non-trading days (Saturday/Sunday + US holidays — use `pandas-market-calendars` or hard-coded list for v1)
- Compute root portfolio snapshots by aggregation in T-46-4-03 (separate pass — depends on sub-portfolios being snapshot first).

**Acceptance criteria**:
- [ ] Worker runs once at scheduled time
- [ ] All non-root portfolios get a snapshot per trading day
- [ ] Re-running same day is a no-op (idempotent upsert)
- [ ] Logs warning on missing OHLCV; continues for other instruments

---

### T-46-4-03: Root portfolio snapshot via aggregation

**Type**: impl
**depends_on**: T-46-4-02
**blocks**: T-46-4-04
**Target files**:
- `services/portfolio/src/portfolio/workers/portfolio_snapshot_worker.py`

**What to build**:
After non-root snapshots complete, for each user, aggregate their sub-portfolio snapshots into a root snapshot for the same date: sum `total_value`, sum `total_cost`, sum `cash_value`.

**Acceptance criteria**:
- [ ] Root snapshot for date X = Σ non-root snapshots for that user on date X (within 1e-6)
- [ ] Idempotent

---

### T-46-4-04: Historical backfill script

**Type**: impl
**depends_on**: T-46-4-03
**blocks**: none
**Target files**:
- `services/portfolio/scripts/backfill_portfolio_value_snapshots.py` (new)

**What to build**:
- For each portfolio, replay snapshots backwards from today to the earliest transaction date (cap at 365 days for v1).
- For each historical date, reconstruct holdings as-of that date by replaying transactions up to that date, then multiply by S3 close prices.
- Write to `portfolio_value_snapshots` (idempotent upsert).

**Acceptance criteria**:
- [ ] Script writes ~252 trading-day rows per active portfolio
- [ ] Dry-run mode reports volumes without writing
- [ ] Re-run on partial state fills only missing dates

---

### Wave 4 Validation Gate

- [ ] All S1 tests pass
- [ ] Manual: trigger worker; verify rows in `portfolio_value_snapshots`
- [ ] Manual: backfill script writes 252 rows for an active portfolio in <2 min

---

## Wave 5 — Analytics Endpoints + Frontend (F-005, part 2)

**Goal**: Expose value-history, exposure, risk-metrics endpoints and surface them in the portfolio page.
**Depends on**: Wave 4
**Estimated effort**: 8–10 hours
**Architecture layer**: S9 + frontend

### T-46-5-01: `GET /v1/portfolios/{id}/value-history`

**Type**: impl
**depends_on**: Wave 4
**blocks**: T-46-5-04 (frontend chart)
**Target files**:
- `services/portfolio/src/portfolio/application/use_cases/get_value_history.py` (new)
- `services/portfolio/src/portfolio/api/routes/portfolio.py`
- `services/portfolio/src/portfolio/api/schemas/portfolio.py`
- `services/api-gateway/src/api_gateway/routes/proxy.py`

**What to build**:
S1 use case reads `portfolio_value_snapshots` over the requested range. Granularity 1d (default), 1w (sample weekly), 1m (sample monthly). S9 proxies the path.

**Acceptance criteria**:
- [ ] Returns `{points: [{date, value, cost_basis, cash}]}` sorted ascending
- [ ] Default range = 90 days
- [ ] 404 if portfolio not owned by caller
- [ ] Contract test

---

### T-46-5-02: `GET /v1/portfolios/{id}/exposure`

**Type**: impl
**depends_on**: Wave 1
**blocks**: T-46-5-05
**Target files**:
- `services/portfolio/src/portfolio/application/use_cases/get_exposure.py` (new)
- `services/portfolio/src/portfolio/api/routes/portfolio.py`
- `services/api-gateway/src/api_gateway/routes/proxy.py`

**What to build**:
Compute current exposure: `invested = Σ quantity × current_price`, `cash = 0` (v1), `gross_exposure_pct = invested / (invested + cash)`, `leverage = invested / total_cost`. Pull current prices from S3 batch quotes.

**Acceptance criteria**:
- [ ] Returns `{invested, cash, gross_exposure_pct, net_exposure_pct, leverage}`
- [ ] Handles empty portfolio (returns zeros, not NaN)
- [ ] Contract test

---

### T-46-5-03: `GET /v1/portfolios/{id}/risk-metrics`

**Type**: impl
**depends_on**: T-46-5-01
**blocks**: T-46-5-06
**Target files**:
- `services/api-gateway/src/api_gateway/routes/risk_metrics.py` (new — pure S9 composition; doesn't need S1)

**What to build**:
S9 endpoint that:
1. Calls S1 `value-history` for the requested lookback (default 90 days)
2. Computes daily returns: `r_t = (V_t - V_{t-1}) / V_{t-1}`
3. **Drawdown**: `dd_max = min over t of (V_t - max_so_far) / max_so_far`; `dd_current = (V_now - max_so_far) / max_so_far`
4. **Volatility**: `stdev(r) × √252`
5. **Sharpe**: `(mean(r) × 252 - rf) / vol`, where `rf = 0.05` constant for v1
6. **Sortino**: same but uses downside-deviation
7. **Beta vs SPY**: pull SPY OHLCV from S3 over same range; compute `cov(r_portfolio, r_spy) / var(r_spy)`

**Acceptance criteria**:
- [ ] Returns `{drawdown_max, drawdown_current, volatility_annualized, sharpe, sortino, beta_vs_spy}`
- [ ] Handles short series (<10 points) by returning `null` for unstable metrics
- [ ] Unit test against a hand-computed reference series (verify Sharpe within 0.01)
- [ ] Contract test

---

### T-46-5-04: `EquityCurveChart` component

**Type**: impl
**depends_on**: T-46-5-01
**blocks**: T-46-5-07
**Target files**:
- `apps/worldview-web/components/portfolio/EquityCurveChart.tsx` (new)
- `apps/worldview-web/lib/gateway.ts`

**What to build**:
- Recharts `LineChart` plotting `total_value` over time
- Period toggle: 1M / 3M / 6M / 1Y / All (drives `from` query param)
- Hover tooltip: date, value, cost basis, return %
- Loading skeleton while query in-flight; empty state if no snapshots yet

**Acceptance criteria**:
- [ ] Chart renders with real data
- [ ] Period toggle re-fetches and re-renders
- [ ] Tooltip values format correctly with `formatPrice` and `formatPercent`

---

### T-46-5-05: `ExposureBreakdown` component

**Type**: impl
**depends_on**: T-46-5-02
**blocks**: T-46-5-07
**Target files**:
- `apps/worldview-web/components/portfolio/ExposureBreakdown.tsx` (new)

**What to build**:
- Horizontal stacked bar showing invested vs cash; gross-exposure-% headline number
- Color-coded by sector (reuse `SectorAllocationPanel` palette)

**Acceptance criteria**:
- [ ] Renders correctly with 100% invested (no cash)
- [ ] Renders correctly with mixed cash + invested
- [ ] Empty state for empty portfolio

---

### T-46-5-06: `RiskMetricsStrip` component

**Type**: impl
**depends_on**: T-46-5-03
**blocks**: T-46-5-07
**Target files**:
- `apps/worldview-web/components/portfolio/RiskMetricsStrip.tsx` (new)

**What to build**:
Horizontal strip of 5 KPI tiles: Max Drawdown, Volatility (Ann.), Sharpe, Sortino, Beta vs SPY. Each tile shows the metric, a 1-line label, and a quality badge (e.g. Sharpe > 1 → green, < 0 → red).

**Acceptance criteria**:
- [ ] All 5 metrics render with correct formatting (% for drawdown/vol, decimal for ratios)
- [ ] `null` metrics show "—" not "NaN"
- [ ] Color coding matches design tokens

---

### T-46-5-07: Wire `PortfolioAnalyticsSection` into portfolio page

**Type**: impl
**depends_on**: T-46-5-04, T-46-5-05, T-46-5-06
**blocks**: none
**Target files**:
- `apps/worldview-web/components/portfolio/PortfolioAnalyticsSection.tsx` (new — composes the three sub-components)
- `apps/worldview-web/app/(app)/portfolio/page.tsx`

**What to build**:
Render `PortfolioAnalyticsSection` below `SemanticHoldingsTable` in the Holdings tab. Layout: 12-column grid — equity curve (col-span-8), exposure (col-span-4), risk metrics strip full-width below.

**Acceptance criteria**:
- [ ] Section appears below holdings; doesn't break existing layout
- [ ] All three sub-components load and render
- [ ] Loading/empty/error states handled

---

### Wave 5 Validation Gate

- [ ] All S1 + S9 tests pass
- [ ] Frontend Vitest + Playwright pass
- [ ] Manual: portfolio page shows working equity curve, exposure, and risk metrics

---

## Cross-Cutting Concerns

- **Multi-tenant**: every new query MUST filter by `tenant_id`. Repositories enforce this.
- **R9** (no cross-service DB): S9's risk-metrics endpoint reads via REST from S1 (`value-history`) and S3 (SPY OHLCV) — no direct DB.
- **R25** (API uses only use cases): all new routes go through use case classes.
- **Outbox pattern**: not needed (no Kafka events emitted in this plan).
- **Forward-compatible schemas**: all new columns nullable with defaults; new endpoints additive.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Snapshot endpoint behaves differently across SnapTrade institutions | Medium | High | Recorded fixtures per institution; integration test matrix |
| Holdings cleanup migration deletes legitimate state | Low | High | Dry-run mode; manual verification before live run; full DB backup first |
| Snapshot worker fails silently on a portfolio | Medium | Medium | Per-portfolio try/except; structured logging; Slack alert on >5% failure rate |
| Risk metrics produce misleading values on short series | High | Low | Return `null` when N < 10; UI shows "Insufficient history" |
| Root portfolio aggregation has perf issues with many sub-portfolios | Low | Low | Single SQL query with GROUP BY; index on `(owner_id, kind)` |
| Frontend chart performance with 252 points × multiple portfolios | Low | Low | Recharts handles this fine; debounce period toggle |

## Regression Guardrails

- **R19** (never delete tests): every existing test stays. Update assertions where shape changes.
- **BP-023, BP-065** (pre-commit ruff format): sync staged + working files before commit.
- **BP-124** (consumer idempotency): snapshot worker is idempotent; activity dedup tightened.
- **BP-264** (new): document holdings-from-snapshot pattern in `services/portfolio/.claude-context.md`.

## Compounding

After each wave commit:
- Update `docs/plans/TRACKING.md`
- Update `services/portfolio/.claude-context.md` if new pitfalls emerge
- Add BP-263 (DIV amount), BP-264 (replay drift), BP-265 (gateway hard-coded empty) to `docs/BUG_PATTERNS.md`
- Mark this plan's row complete in TRACKING.md only when all 5 waves pass their validation gates
