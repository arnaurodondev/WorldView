# QA Report: PLAN-0044 Portfolio Enhancement — Follow-up

**Date**: 2026-04-28
**Skill**: qa
**Scope**: PLAN-0044 follow-up — five user-reported gaps that survived the original implementation
**Branch**: feat/content-ingestion-wave-a1
**Verdict**: FAIL (5 BLOCKING/CRITICAL findings — all confirmed at code level; no test execution gate run because all five are correctness/feature gaps requiring backend changes)
**Report file**: docs/audits/2026-04-28-qa-plan-0044-followup-report.md
**Follow-up plan**: docs/plans/0046-portfolio-correctness-and-analytics-plan.md

---

## Executive Summary

PLAN-0044 was applied (commit 6874396) and a first QA pass logged at 2026-04-28-qa-plan-0044-report.md. The user has since exercised the live UI and surfaced five gaps that are all confirmed by source-level investigation:

1. **Holdings quantity is wildly inflated** (e.g. +800 shares of one ticker vs. <100 in TastyTrade). Root cause is *transaction replay* into `holdings.quantity` instead of using SnapTrade's position-snapshot endpoint, combined with a SnapTrade dual-path (`legacy` then `per-account`) that can return the same activity twice with different `id`s. CRITICAL — data correctness.
2. **DIVIDEND rows show no amount.** SnapTrade returns dividends with `units≈0, price≈0, amount=<cash>`; our adapter at `snaptrade_client.py:315-355` only reads `id, type, symbol, units, price, currency, trade_date, institution` and silently drops `amount` and `fee`. The frontend already expects the dividend value in `tx.fee` (TransactionsTable.tsx:181) but the field is always `0`. CRITICAL.
3. **Watchlist tab still empty after adding symbols.** Frontend is correctly built (delete, create, rename, real-entity_id search all in place). The break is upstream: S1 has no `GET /v1/watchlists/{id}/members` route and `gateway.ts:177` hard-codes `members: []`. Every watchlist appears empty regardless of how many members exist. BLOCKING for the watchlist feature.
4. **Root/aggregate portfolio missing.** No `kind` flag on `Portfolio`; no auto-creation on user provisioning; "All portfolios" view doesn't exist; delete is allowed on every portfolio. MAJOR (feature gap).
5. **Analytics components missing** (capital evolution, market exposure, drawdown, volatility, Sharpe). No daily NAV snapshot table, no `value-history` endpoint, no risk-metrics endpoint. MAJOR (feature gap; explicitly deferred in PLAN-0044 line 23).

All five issues are *real, not perceived*. Two (#1, #2) are correctness bugs that misrepresent the user's portfolio. One (#3) means the watchlist feature is non-functional end-to-end. The remaining two are feature additions with concrete designs below.

A follow-up plan, **PLAN-0046**, has been drafted alongside this report to address all five.

---

## Multi-Agent Review Summary

| Agent | Findings | BLOCKING | CRITICAL | MAJOR | MINOR |
|-------|----------|----------|----------|-------|-------|
| Position Quantity Investigator | 1 | 0 | 1 | 0 | 0 |
| Brokerage Sync Investigator (DIV) | 1 | 0 | 1 | 0 | 0 |
| Watchlist Page Investigator | 1 | 1 | 0 | 0 | 0 |
| Portfolio Architecture Investigator | 2 | 0 | 0 | 2 | 0 |
| **Total** | **5** | **1** | **2** | **2** | **0** |

### Cross-Agent Signals (HIGH Confidence)
- F-001 and F-002 share a common upstream component (`SnapTradeClient` adapter, `services/portfolio/src/portfolio/infrastructure/brokerage/snaptrade_client.py`). Both are caused by the adapter dropping fields it should be reading. PLAN-0046 addresses them as one wave.

---

## Issue F-001: Holdings Quantity Inflated 8–10× vs. Brokerage Truth

### Summary
`holdings.quantity` is computed by replaying transactions (`apply_delta` per BUY/SELL), not from SnapTrade's position snapshot. A combination of (a) the SnapTrade adapter's `legacy → per-account` fallback path, (b) inclusive `last_sync_cursor`, and (c) intra-batch dedup gaps causes activities to be applied multiple times. The user sees 800 shares where their broker shows <100.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Position Quantity Investigator (agent #1)

### Root Cause Analysis

- **What**: Holdings quantity is the running cumulative sum of `qty_delta` applied at `services/portfolio/src/portfolio/application/use_cases/record_transaction.py:147-159` (`apply_delta` mutates `Holding`). There is no position-snapshot ingest path.
- **Why**: The architectural choice is "transactions are the source of truth, holdings are a materialised view". This is reasonable in principle, but it makes us 100% dependent on SnapTrade returning each activity *exactly once* with a *stable, unique* `id`. Today neither holds:
  - `snaptrade_client.py:198-225` calls `_get_activities_legacy` first; on `BrokerageApiError` falls back to `_get_activities_per_account` (`:288-313`). Both endpoints can succeed in different cycles, returning the same trade with **different** activity IDs (legacy and per-account use different ID schemes). Different `external_ref` → no dedup → quantity counted twice.
  - `_get_activities_per_account` iterates user accounts and concatenates results (`:303`) with no in-memory dedup. If SnapTrade exposes a trade across multiple linked sub-accounts (joint/individual mirrors), the same trade with the same id appears twice in `all_activities`.
  - `last_sync_cursor` is inclusive (`brokerage_sync_worker.py:155-159`), so the cursor day is re-fetched every cycle. The unique constraint on `transactions(portfolio_id, external_ref)` would normally catch this — but with the multi-endpoint id mismatch above, the constraint doesn't fire.
- **When**: Manifests over time as duplicates accumulate. Consistent with "user has used app for weeks and now sees 800 shares".
- **Where**: Crosses `infrastructure/brokerage/snaptrade_client.py` (returns dupes) → `workers/brokerage_sync_worker.py` (orchestration) → `application/use_cases/record_transaction.py` (compounds the holding).
- **History**: Introduced with the SnapTrade-replay design from the start of S1's brokerage sync feature. Has not been QA'd against ground-truth broker positions until now.

### Evidence

```python
# services/portfolio/src/portfolio/infrastructure/brokerage/snaptrade_client.py:198-225
async def get_activities(self, user, start, end):
    try:
        return await self._get_activities_legacy(user, start, end)
    except BrokerageApiError:
        return await self._get_activities_per_account(user, start, end)
```

```python
# services/portfolio/src/portfolio/application/use_cases/record_transaction.py:147-159
holding = await uow.holdings.get(portfolio_id, instrument_id) or Holding.empty(...)
qty_delta = quantity if direction == INFLOW else -quantity
holding.apply_delta(qty_delta, price)   # mutates running quantity
await uow.holdings.upsert(holding)
```

- **File**: `services/portfolio/src/portfolio/infrastructure/brokerage/snaptrade_client.py:198-313`
- **File**: `services/portfolio/src/portfolio/workers/brokerage_sync_worker.py:147-194`
- **File**: `services/portfolio/src/portfolio/application/use_cases/record_transaction.py:147`
- **Related BP**: candidate BP-264 — "Broker activity replay drift: never trust dual-path activity feeds for cumulative state; always reconcile against a snapshot."

### Impact

- **Immediate**: Every dashboard/portfolio number derived from quantity is wrong: `value`, `weight`, `pnl`, `pnl_pct`, `total_invested`, sector exposure. The user cannot trust the app.
- **Blast radius**: Dashboard `PortfolioSummary`, KPI strip, sector allocation, top gainers/losers, watchlist quotes (where they reference holdings), `/v1/portfolios/{id}/performance` (S9 composition uses `quantity`).
- **Data risk**: Holdings table contains compounded quantities; transactions table may already contain duplicate rows with different `external_ref`s. **Cleanup migration required.**
- **User impact**: Visible on every portfolio screen. The single most damaging bug in the report.

### Solution Options

#### Option A — Snapshot-based holdings (definitive fix)
**Description**: Replace transaction-replay as the source of holdings with SnapTrade's `account_information.get_user_account_positions(user, account_id)`. The sync worker writes `Holding` rows directly from the snapshot (one upsert per (portfolio, instrument)). Transactions remain in the `transactions` table for history but no longer mutate `holdings`.
**Changes required**:
- [ ] `infrastructure/brokerage/snaptrade_client.py` — add `get_account_positions(user, account_id) -> list[SnapTradePosition]`
- [ ] `application/ports/brokerage_client.py` — add `SnapTradePosition` VO + port method
- [ ] `workers/brokerage_sync_worker.py` — after activity sync, call positions and overwrite `holdings` rows for that portfolio
- [ ] `application/use_cases/upsert_holdings_from_snapshot.py` — new use case
- [ ] `application/use_cases/record_transaction.py` — keep transaction recording, drop the `apply_delta` mutation (transactions become history-only)
- [ ] `tests/unit/test_brokerage_sync_snapshot.py` — new tests
- [ ] One-time data migration: zero-out `holdings` for affected portfolios, then trigger a fresh sync
**Benefits**: Eliminates ALL replay drift forever. Always matches broker truth. Survives any upstream bug in the activity feed.
**Drawbacks**: Loses the "holdings are derivable from transactions" invariant. Manual transactions (if we add them later) won't auto-update holdings — would need a separate "manual holding adjustment" path.
**Effort**: Medium
**Risk**: Low (snapshot is what every other broker app does)

#### Option B — Add a recompute-from-transactions reconciliation
**Description**: After every sync cycle, run a `RecomputeHoldingsFromTransactionsUseCase` that issues `SELECT instrument_id, SUM(CASE direction WHEN INFLOW THEN qty ELSE -qty END) FROM transactions WHERE portfolio_id = ? GROUP BY instrument_id` and overwrites `holdings.quantity`. This makes the materialised view eventually consistent with the (possibly duplicated) transaction history.
**Changes required**:
- [ ] `application/use_cases/recompute_holdings.py` — new
- [ ] `workers/brokerage_sync_worker.py` — call it at end of each sync cycle
- [ ] **Still need to dedupe transactions** otherwise the recompute is just as wrong. So this requires Option A or a transaction-dedup migration anyway.
**Benefits**: Self-healing if the bug ever recurs.
**Drawbacks**: Doesn't actually fix the root cause (duplicated transactions). Useful as belt-and-braces alongside Option A or C.
**Effort**: Low
**Risk**: Low

#### Option C — Fix the SnapTrade adapter dedup + cursor
**Description**: Three sub-fixes inside `snaptrade_client.py`:
1. Cache which endpoint family worked per connection; never call the other after first success
2. In-memory dedup by activity `id` after concatenation (`_get_activities_per_account`)
3. Make `last_sync_cursor` exclusive (start_date = cursor + 1ms or +1day)
**Changes required**:
- [ ] `snaptrade_client.py:198-313` — add `_endpoint_family_cache` + dedup
- [ ] `brokerage_sync_worker.py:155-159` — exclusive cursor
- [ ] Backfill data migration to remove existing duplicate transactions
**Benefits**: Keeps the replay architecture; smallest code change.
**Drawbacks**: Brittle — any future SnapTrade SDK quirk re-introduces drift. We're betting the farm on activity feed quality.
**Effort**: Low
**Risk**: Medium — may not catch all duplication paths

### Recommended Option
**Option A** plus **Option B as belt-and-braces**. Snapshot is the only source of truth a finance app can defensibly stand behind; replay is fine as a transaction history but should not be the holdings source. Option C alone leaves us vulnerable.

### Verification Steps
- [ ] Pick one ticker in a test portfolio; manually verify SnapTrade returns the same quantity our `holdings` table now has (within 1e-8 tolerance).
- [ ] Run the user's affected portfolio through a fresh sync after Option A; expect <100 shares for the previously-800 ticker.
- [ ] Add an integration test using a recorded SnapTrade response with known position counts.

---

## Issue F-002: DIVIDEND Transactions Show $0 Total

### Summary
Our SnapTrade adapter only reads `id, type, symbol, units, price, currency, trade_date, institution` from each activity (`snaptrade_client.py:315-355`) and drops `amount` and `fee`. SnapTrade returns dividends as `units≈0, price≈0, amount=<cash dividend>` — so by the time the row reaches the frontend, `quantity*price = 0` and `tx.fee = 0`, and the dividend appears with no value.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Brokerage Sync Investigator (agent #2)

### Root Cause Analysis

- **What**: Field-mapping omission in `_parse_activity_list`.
- **Why**: When the adapter was written, `amount` was likely overlooked because BUY/SELL activities have it equal to `quantity * price`. Dividends — which carry the value entirely in `amount` — weren't considered as a distinct shape.
- **When**: Always (every dividend ever ingested).
- **Where**: `infrastructure/brokerage/snaptrade_client.py` (`_parse_activity_list`).

### Evidence

```
SnapTrade UniversalActivity has:
  id, account_id, symbol, units, price, amount, fee, currency, type, ...
                                       ^^^^^^  ^^^
                                       these are dropped
```

```python
# services/portfolio/.venv/lib/python3.11/site-packages/snaptrade_client/model/universal_activity.py:119,122
amount: typing.Optional[Union[float, schemas.Decimal]] = ...
fee:    typing.Optional[Union[float, schemas.Decimal]] = ...
```

```python
# services/portfolio/src/portfolio/infrastructure/brokerage/snaptrade_client.py:342-353
return SnapTradeActivity(
    snaptrade_transaction_id=...,
    activity_type=...,
    symbol=...,
    quantity=Decimal(units),
    price=Decimal(price),
    currency=currency,
    trade_date=trade_date,
    institution=institution,
    # NOTE: amount and fee are silently dropped
)
```

```typescript
// apps/worldview-web/components/portfolio/TransactionsTable.tsx:181
const total = isDividend ? tx.fee : tx.quantity * tx.price;
//                          ^^^^^^ frontend ALREADY expects amount in fee, but it's 0
```

- **File**: `services/portfolio/src/portfolio/infrastructure/brokerage/snaptrade_client.py:315-355`
- **File**: `services/portfolio/src/portfolio/application/ports/brokerage_client.py:31-42` (VO has no `amount`)
- **File**: `services/portfolio/src/portfolio/workers/brokerage_sync_worker.py:291-303` (passes `fees=Decimal(0)`)
- **File**: `services/portfolio/src/portfolio/infrastructure/db/models/transaction.py:30-32` (no `amount` column)
- **Related BP**: candidate BP-263 — "SnapTrade adapter must capture `amount` and `fee` from `UniversalActivity`."

### Impact

- **Immediate**: All dividend rows show $0 total. Dividend income is invisible in the app.
- **Blast radius**: Any "income" or "yield" widget we add later will be wrong; YTD return excludes dividends.
- **Data risk**: Historical dividends are not stored anywhere (the field was never read). A backfill requires a re-sync.
- **User impact**: Visible on every Transactions tab DIV filter.

### Solution Options

#### Option A — Reuse `fees` column for DIV amount (smallest)
**Description**: Capture SnapTrade `amount` and `fee` in `SnapTradeActivity`. For DIVIDEND activities, write `amount` into `Transaction.fees` (which the frontend already reads as the dividend total). For BUY/SELL, write `fee` into `Transaction.fees` as today.
**Changes required**:
- [ ] `application/ports/brokerage_client.py` — add `amount: Decimal | None`, `fee: Decimal | None` to `SnapTradeActivity`
- [ ] `infrastructure/brokerage/snaptrade_client.py:315-355` — read both fields
- [ ] `workers/brokerage_sync_worker.py:291-303` — set `fees=activity.amount if DIVIDEND else activity.fee`
- [ ] No DB migration needed; frontend works as-is
**Benefits**: Fastest; matches existing TS code at `TransactionsTable.tsx:181` and `gateway.ts:856-858`.
**Drawbacks**: Semantic overloading — `fees` means "trade fee" for BUY/SELL and "gross amount" for DIVIDEND. Requires comments to prevent regression.
**Effort**: Low
**Risk**: Low

#### Option B — Add an `amount` column (clean)
**Description**: Add `amount Numeric(18,8) NULL` to `transactions` via Alembic; add the field through every layer (domain, model, schema, gateway TS type). Frontend uses `tx.amount` for the DIV total. Keeps `fees` semantically pure.
**Changes required**:
- [ ] Alembic migration adding `amount` column
- [ ] `Transaction` domain entity
- [ ] `TransactionModel`
- [ ] S1 response schema
- [ ] `apps/worldview-web/types/api.ts` — add `amount`
- [ ] `apps/worldview-web/lib/gateway.ts:856-858` — map field
- [ ] `apps/worldview-web/components/portfolio/TransactionsTable.tsx:181` — `tx.amount` not `tx.fee`
- [ ] Worker captures both `fee` (into `fees`) and `amount` (into `amount`)
**Benefits**: Future-proof, semantically clean, supports BUY/SELL with both `fee` and `amount` reported separately.
**Drawbacks**: Migration plus code touched in ~7 files.
**Effort**: Medium
**Risk**: Low

### Recommended Option
**Option B**. The clean schema is worth the migration cost — we will inevitably want both fee and gross amount for all transaction types (cost-basis accuracy, post-fee P&L). Doing the overload now creates tech debt we'll repay anyway.

### Verification Steps
- [ ] Re-sync a brokerage with known dividends; verify DIVIDEND rows show non-zero `tx.amount`
- [ ] Unit test: `_parse_activity_list` captures `amount` and `fee`
- [ ] Frontend snapshot test: DIVIDEND row renders `tx.amount` formatted as currency

---

## Issue F-003: Watchlist Members Never Render — Backend GET Missing

### Summary
The watchlist UI is fully built (delete-member ×, +New, delete watchlist, rename, AddSymbolBar with real KG entity_id via `searchFundamentals`). However, **`gateway.ts:177` hard-codes `members: []`** because S1 has no `GET /v1/watchlists/{id}/members` endpoint. Every watchlist appears empty regardless of how many members were added.

### Severity / Confidence
**Severity**: BLOCKING (the watchlist feature is non-functional)
**Confidence**: HIGH
**Flagged by**: Watchlist Page Investigator (agent #4)

### Root Cause Analysis

- **What**: S1's `WatchlistResponse` has no `members[]` field; there is no `GET /watchlists/{id}/members` route. The gateway compensates by returning `members: []` from `mapRawWatchlist`.
- **Why**: When the watchlist domain was scaffolded, only `add_member` and `remove_member` operations were implemented; `list_members` was missed.
- **When**: Always (since the watchlist feature shipped).
- **Where**: `services/portfolio/src/portfolio/api/routes/watchlist.py` (no GET-members route) → `apps/worldview-web/lib/gateway.ts:165-182` (returns empty).

### Evidence

```typescript
// apps/worldview-web/lib/gateway.ts:165-182 (mapRawWatchlist)
return {
  watchlist_id: ...,
  name: ...,
  member_count: 0,    // ← always 0
  members: [],        // ← always empty
  ...
};
```

```typescript
// apps/worldview-web/lib/gateway.ts:1078-1080 (docstring admits the gap)
// "S1 does NOT include members in the single-watchlist response either…
//  For now, members default to an empty array and the component handles the empty state."
```

- **File**: `apps/worldview-web/lib/gateway.ts:165-182, 1058-1096`
- **File**: `services/portfolio/src/portfolio/api/routes/watchlist.py` (POST/DELETE on `/members`, no GET)
- **File**: `apps/worldview-web/components/portfolio/WatchlistsTabPanel.tsx` (UI is correct; data layer starves it)
- **File**: `apps/worldview-web/app/(app)/portfolio/page.tsx:697-711` (consumer sees empty `members`, never fetches quotes)

### Impact

- **Immediate**: Empty state is permanently shown ("Search above to add your first symbol") even after successful add.
- **Blast radius**: Watchlist tab unusable. Quote pre-fetch for watchlist members never fires.
- **Data risk**: None (data is in DB, just not retrievable via API).
- **User impact**: Watchlist feature appears completely broken.

### Solution Options

#### Option A — Add `GET /v1/watchlists/{id}/members` to S1
**Description**: New route returning `[{entity_id, entity_type, ticker, name, instrument_id, added_at}]`. Requires JOIN against KG (`entities`) and instruments (S3) for ticker/name resolution. Gateway calls it during `getWatchlist`/`getWatchlists` and populates `members`.
**Changes required**:
- [ ] `services/portfolio/src/portfolio/api/routes/watchlist.py` — new GET route
- [ ] `services/portfolio/src/portfolio/application/use_cases/list_watchlist_members.py`
- [ ] `services/portfolio/src/portfolio/infrastructure/db/repositories/watchlist.py` — list-with-enrichment query (cross-DB JOIN forbidden by R9 — must call KG/S3 over REST or via local cache)
- [ ] `apps/worldview-web/lib/gateway.ts` — fetch members and merge into watchlist
- [ ] Tests
**Benefits**: Correct architecture; fixes the feature.
**Drawbacks**: Cross-service enrichment is non-trivial — ticker/name aren't local to S1. Need to decide between (a) S1 stores ticker/name redenormalised at add-time; (b) S1 returns entity_ids only and the gateway calls S7/S3 for enrichment.
**Effort**: Medium
**Risk**: Low

#### Option B — Embed `members[]` in `GET /v1/watchlists/{id}` (single-fetch)
**Description**: Augment the existing `WatchlistResponse` to include `members[]` directly. Same backend work as Option A but exposed via the single watchlist endpoint rather than a sub-resource.
**Changes required**: Same as A but route is the existing GET; one fewer round-trip in the gateway.
**Benefits**: Single network call for watchlist + members.
**Drawbacks**: Larger payload when listing many watchlists; harder to paginate members.
**Effort**: Medium
**Risk**: Low

### Recommended Option
**Option A** for the list view (cheap when many watchlists), with members fetched lazily when a watchlist is selected. Most users have ≤5 watchlists with ≤30 members each — Option B's single-call argument is reasonable too. PLAN-0046 picks A but flags this as a small judgment call.

For ticker/name enrichment: store ticker, name, and instrument_id **redundantly in `watchlist_member`** at add-time (`POST /members` resolves them once and persists). This avoids the cross-service JOIN and matches how S1 already redenormalises in `holdings_enriched`.

### Verification Steps
- [ ] Add a member to a watchlist; reload page; member appears with correct ticker
- [ ] Delete a member; row disappears; cache invalidates
- [ ] Vitest: `WatchlistsTabPanel` renders members from a non-empty mock

---

## Issue F-004: No Root/Aggregate Portfolio per User

### Summary
There is no concept of a "root" portfolio that aggregates positions across all of a user's other portfolios. `Portfolio` has no `kind` flag, provisioning doesn't auto-create one, and any portfolio can be deleted (no system-owned guard).

### Severity / Confidence
**Severity**: MAJOR (feature gap, not a correctness bug)
**Confidence**: HIGH
**Flagged by**: Portfolio Architecture Investigator (agent #3)

### Root Cause Analysis
- **What**: `Portfolio` entity (`services/portfolio/src/portfolio/domain/entities/portfolio.py:14-43`) has only `id, tenant_id, owner_id, name, currency, status, created_at`. No `kind`, `is_root`, or `is_default`. `provision_user.py:102-126` creates `Tenant` + `User` only; no portfolio. The user must manually create one.
- **Why**: Wasn't a requirement when S1 was scaffolded; PRD-0022 (brokerage) added one connection per portfolio but didn't define a default.
- **Where**: Schema (`alembic/versions/0001_initial_schema.py:58-69`), domain entity, provision flow, archive route (`portfolio.py:131` allows archive on any portfolio).

### Impact
- **Immediate**: Users with multiple brokerages see disconnected portfolios with no aggregate view.
- **Blast radius**: Dashboard, portfolio page, KPI strip all show one portfolio at a time.
- **User impact**: Can't see "all my money" in one screen.

### Solution Options

#### Option A — Application fan-out (recommended)
**Description**: Add `kind: ENUM('manual','brokerage','root')` to `portfolios`. On user provisioning, auto-create a `kind='root'` portfolio named "All Accounts". Holdings/transactions queries detect `kind='root'` and replace `WHERE portfolio_id = X` with `WHERE portfolio_id IN (SELECT id FROM portfolios WHERE owner_id = ? AND kind != 'root' AND status = 'active')`. Aggregate by `instrument_id` (sum quantity, qty-weighted avg cost).
**Changes required**:
- [ ] Alembic migration: `kind` column + partial unique index `WHERE kind='root'` + CHECK constraint
- [ ] `Portfolio` entity + `PortfolioKind` enum
- [ ] `EnsureRootPortfolioUseCase` called from `provision_user.py`
- [ ] `GetHoldingsUseCase` / `ListTransactionsUseCase` — detect root, fan out
- [ ] `ArchivePortfolioUseCase` — reject root
- [ ] Frontend: surface `kind='root'` in portfolio selector with badge; disable delete button
- [ ] Backfill script for existing users
**Benefits**: Reuses repos, ports, response schemas. `SemanticHoldingsTable` works unchanged. Portfolio listing returns root naturally.
**Drawbacks**: Aggregation logic must handle weighted avg cost carefully; root holdings have no transactions of their own.
**Effort**: Medium
**Risk**: Low

#### Option B — Postgres VIEW union
**Description**: Define a SQL view that unions holdings across all non-root portfolios per user; address it via the root portfolio_id.
**Changes required**: View migration + read-model changes.
**Benefits**: Always consistent.
**Drawbacks**: Hard to integrate with existing `holdings_repository`; can't FK; second model layer needed.
**Effort**: Medium-high
**Risk**: Medium

### Recommended Option
**Option A**. Cleaner integration with hexagonal architecture and existing repos. Detailed in PLAN-0046 Wave 4.

### Verification Steps
- [ ] New user provisioning creates a `kind='root'` portfolio
- [ ] Selecting it in the UI shows aggregated holdings across all non-root portfolios
- [ ] Delete button is hidden/disabled for root
- [ ] Archive request returns 400 with `RootPortfolioNotArchivableError`

---

## Issue F-005: Missing Portfolio Analytics (Capital Evolution, Drawdown, Vol, Sharpe)

### Summary
The portfolio page lacks all of: capital evolution chart, market exposure breakdown, drawdown, volatility, Sharpe ratio. The required data plumbing — daily portfolio NAV snapshots — does not exist. Only one analytics endpoint exists today: S9's `GET /v1/portfolios/{id}/performance` (stateless composition over current holdings, not a time series).

### Severity / Confidence
**Severity**: MAJOR (feature gap; explicitly deferred in PLAN-0044 line 23)
**Confidence**: HIGH
**Flagged by**: Portfolio Architecture Investigator (agent #3)

### Root Cause Analysis
- No `portfolio_value_snapshots` table. No daily snapshot worker.
- S9's `/performance` endpoint reconstructs return only from current holdings × historical OHLCV; it can't account for transactions over the lookback period.
- No analytics components exist in `apps/worldview-web/components/portfolio/`.

### Impact
- **User impact**: Portfolio page is just a holdings table; no risk/return metrics. The user explicitly listed five they expect.

### Solution Options

#### Option A — Daily snapshot table + value-history endpoint + client-side metrics (recommended)
**Description**:
1. New table `portfolio_value_snapshots(portfolio_id, snapshot_date, total_value, total_cost, cash_value, ...)`.
2. New worker `PortfolioSnapshotWorker` — runs once at NYSE close per trading day. Computes today's value for every active portfolio: `Σ(holding.quantity × close_price[holding.instrument_id])`.
3. New endpoint `GET /v1/portfolios/{id}/value-history?from&to&granularity` returning `{points: [{date, value, cost_basis, cash}]}`.
4. New endpoint `GET /v1/portfolios/{id}/exposure` returning `{invested, cash, gross_exposure_pct, net_exposure_pct, leverage}`.
5. New endpoint `GET /v1/portfolios/{id}/risk-metrics?lookback_days` returning `{drawdown_max, drawdown_current, volatility_annualized, sharpe, sortino, beta_vs_spy}` — computed from value-history server-side.
6. Frontend `PortfolioAnalyticsSection` component below holdings table with: equity curve (recharts), exposure pie, metrics strip.

**Easy vs hard metrics** (assuming snapshots exist):
| Metric | Difficulty | Notes |
|---|---|---|
| Capital evolution | Easy | direct line chart of value |
| Drawdown | Easy | one-pass over series |
| Volatility | Easy | stdev(daily returns) × √252 |
| Sharpe | Medium | needs risk-free rate (FRED 3M T-bill) |
| Exposure | Easy if cash=0 | medium with real cash (need brokerage_balances) |
| Beta vs SPY | Medium | needs SPY OHLCV (already in S3) |

**Changes required**:
- [ ] Alembic migration: `portfolio_value_snapshots` table
- [ ] Domain entity + repository + use case
- [ ] `PortfolioSnapshotWorker` (daily, market-close trigger)
- [ ] Three new S1/S9 endpoints
- [ ] `PortfolioAnalyticsSection.tsx` + `EquityCurveChart.tsx` + `RiskMetricsStrip.tsx` + `ExposureBreakdown.tsx`
- [ ] One-time backfill: replay holdings × historical OHLCV to populate ~252 trading days of history per portfolio
**Benefits**: Authoritative time series; powers all five user-requested metrics; future-proofs benchmarking.
**Drawbacks**: Storage (~365 rows/portfolio/year — trivial), backfill effort (one-shot script).
**Effort**: Large (multiple waves)
**Risk**: Medium (snapshot worker correctness, backfill correctness)

### Recommended Option
**Option A**. Detailed multi-wave breakdown in PLAN-0046 Wave 5.

### Verification Steps
- [ ] Snapshot worker writes a row per portfolio per trading day
- [ ] `value-history` returns ≥30 days of data after backfill
- [ ] Equity curve renders, drawdown matches manual calc on a known sequence
- [ ] Sharpe matches a hand-computed reference within 0.01

---

## Test Execution Results
**Skipped this round.** All five findings are correctness/feature gaps with no implementation yet — running the suite would not surface them. The follow-up plan (PLAN-0046) will run the full QA suite per-wave at completion.

## Supplementary Checks
| Check | Status | Notes |
|-------|--------|-------|
| Doc Freshness | WARN | PLAN-0044 closed but follow-up gaps not noted; this report fills that |
| Architecture | WARN | Holdings-replay-only design needs to be reconsidered (F-001) |

## Recommendations (priority-ordered)

1. **PLAN-0046 Wave 1 — Brokerage adapter correctness** (Issues F-001 + F-002): snapshot-based holdings + capture `amount`/`fee`. Single wave because both touch `snaptrade_client.py`. Highest priority: data correctness.
2. **PLAN-0046 Wave 2 — Watchlist members backend** (Issue F-003): add `GET /watchlists/{id}/members` with denormalised ticker/name on `watchlist_member`. Fixes the feature end-to-end.
3. **PLAN-0046 Wave 3 — Root portfolio** (Issue F-004): schema + provisioning + fan-out use cases + UI surfacing.
4. **PLAN-0046 Wave 4 — Daily snapshot foundation** (Issue F-005, part 1): table + worker + backfill.
5. **PLAN-0046 Wave 5 — Analytics endpoints + components** (Issue F-005, part 2): three S9 endpoints + `PortfolioAnalyticsSection`.

## Compounding Notes

**New BUG_PATTERNS.md candidates**:
- BP-263: SnapTrade adapter must capture `amount` and `fee` from `UniversalActivity`; activities (especially DIVIDEND) carry value in fields beyond `units × price`.
- BP-264: Never compute holdings purely from broker activity replay; always reconcile against the broker's position snapshot. Activity feeds can return duplicates across endpoint families.
- BP-265: When the gateway hard-codes a missing field (e.g. `members: []`), surface it as a TODO with a route name so the backend gap is discoverable.

**HIGH_RISK_PATTERNS.md candidate**:
- HR-XXX: "Cumulative state derived from external feeds" — flag any code that computes a running sum from a third-party paginated/multi-endpoint feed without snapshot reconciliation.

**Skill improvement**:
- `/qa` should run a "ground truth comparison" check when a brokerage integration is in scope (e.g. compare our holdings.quantity against a one-shot SnapTrade snapshot in CI).
