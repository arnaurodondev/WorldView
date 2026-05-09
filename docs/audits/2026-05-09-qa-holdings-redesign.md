# Holdings Page Redesign + Computation Audit

**Date**: 2026-05-09
**Auditor**: senior-product-engineer
**Branch**: `feat/content-ingestion-wave-a1`
**Scope**: `/portfolio` Holdings tab — every component, position computation, capital evolution chart
**Trigger**: User report — "current Holdings components feel useless"; capital-evolution prior values "did not represent reality"

---

## Executive Summary

The Holdings tab is **architecturally rich but operationally hollow**: 8 widgets render across 6 vertical zones consuming ~1,400px of scroll height, yet the underlying data pipelines repeatedly fall back to *cost basis* / *empty state*, producing widgets that look broken or carry no information. **Two confirmed correctness bugs** (1 critical, 1 high) cause the equity curve to display a flat line at cost basis even when live OHLCV data is available. The single highest-leverage fix is **#H-1** (rebuild equity curve on live OHLCV — 1-2 hours work, restores trust in the page-level KPI).

**Key findings**:

1. **CRITICAL bug (H-1)**: Equity curve shows `$32,451` flat for 30 days. Reality computed against current OHLCV: `$33,887` today, with intra-period swings of ~$2,400. Root cause: snapshot worker writes cost-basis fallback when the price client is unreachable at startup, then `idempotency-skip-existing` prevents the row from ever being recomputed when prices become available again. **All 30 rows in `portfolio_value_snapshots` carry `data_quality='partial_prices'` and `total_value == total_cost` exactly.**
2. **HIGH bug (H-2)**: `Holding.apply_delta` (FIFO-style avg cost) is dead code — `RecordTransactionUseCase` no longer mutates holdings (BP-264 fix). Holdings only update via SnapTrade `UpsertHoldingsFromSnapshot`. **For users without a connected broker, manual transactions never update holdings.** This silently breaks the entire P&L story for paper-traders and non-SnapTrade users.
3. **MEDIUM (D-1)**: `CashManagementCard` always shows `cash = $0` because `ComputePortfolioValueUseCase` and `GetExposureUseCase` both hard-code `cash = 0` (v1 stub). The 5%-cash-drag badge can never fire. Component contributes ~28px of vertical space for zero information.
4. **MEDIUM (D-2)**: `RealizedPnLChart` is a 2-point line (period-start=0, period-end=total_realized) — geometrically just a sloped segment. With our demo data (0 transactions), it is a flat zero line consuming ~280px of vertical real estate.
5. **MEDIUM (D-3)**: `DividendIncomeTimeline` and `RecentActivityFeed` both reach into `transactions` table — empty for all manual-mode users.
6. **DENSITY (D-4)**: The Holdings tab consumes ~1,400px of scroll for 8 widgets. Bloomberg PORT puts ~14 distinct surfaces in the same vertical budget. Targets: drop 6 widgets to dense single-row formats; surface 4 high-value widgets we don't yet show (cost-basis ladder, sector concentration HHI, lots/tax-lot view, beta-adjusted exposure).

---

## 1. Per-Component Audit Table

| # | Component | File:Line | Current Data Source | Useful? | Issue |
|---|-----------|-----------|---------------------|---------|-------|
| 1 | `CashManagementCard` | `components/portfolio/CashManagementCard.tsx:55` | `GET /v1/portfolios/{id}/exposure` (`cash` field) | **F** | `cash` always `0` — v1 stub; "Sweep APY" hard-coded `—`. 28px of zero-info chrome. |
| 2 | `RealizedPnLChart` | `components/portfolio/RealizedPnLChart.tsx:67` | `GET /v1/portfolios/{id}/realized-pnl` | **C** | 2-point chart (period-start=0 → period-end=total). For demo (0 tx) renders flat zero. ~280px tall. |
| 3 | `SemanticHoldingsTable` | `components/portfolio/SemanticHoldingsTable.tsx:91` | `holdings + quotes + sectors` (parent) | **A** | Best component on the page. 12 columns, AG Grid, live cell-flash, URL-backed sort. Keep. |
| 4 | `SectorAllocationPanel` | `components/portfolio/SectorAllocationPanel.tsx:1` | Parent (`bySector + byType`) | **B** | Useful but the squarified treemap eats ~320px for 6 sectors. Bars-only (toggle exists) is denser. |
| 5 | `RecentActivityFeed` | `components/portfolio/RecentActivityFeed.tsx:71` | `getTransactions(limit:20) + getBrokerageConnections` | **C** | Empty for paper-trader (no tx). For active broker user, 20-row feed is reasonable. |
| 6 | `DividendIncomeTimeline` | `components/portfolio/DividendIncomeTimeline.tsx` | YTD-filtered `getTransactions` (DIVIDEND only) | **D** | No dividend tx in demo data, no broker-tracked dividends in v1 schema. Renders empty state. ~470px wasted. |
| 7 | `EquityCurveChart` (inside `PortfolioAnalyticsSection`) | `components/portfolio/EquityCurveChart.tsx:253` | `GET /v1/portfolios/{id}/value-history` | **F** | **CRITICAL BUG** — flat $32,451 line. See §3. |
| 8 | `ExposureBreakdown` | `components/portfolio/ExposureBreakdown.tsx` | `GET /v1/portfolios/{id}/exposure` | **C** | One bar, one number. Useful but the panel wrapper is min-h-200px. Could be 22px row. |
| 9 | `RiskMetricsStrip` | `components/portfolio/RiskMetricsStrip.tsx` | (TBD — likely vol / beta endpoint) | **C** | Strip is fine; data quality unverified for demo data. |
| 10 | `PortfolioKPIStrip` (above tabs) | `components/portfolio/PortfolioKPIStrip.tsx:1` | Parent KPI hook | **A** | 7 tiles. Top-of-page summary done correctly. Keep. |

**Vertical budget today**: ~1,400px for 8 widgets (Cash 28px + RealizedPnL 280px + Table 350px + Sectors 320px + Activity 240px + Dividends 470px + Equity 200px + Exposure 200px + Risk 100px = approx 2,200px scrolling).

---

## 2. Replacement Proposals (12 widgets, competitor-anchored)

### High-leverage replacements (smaller + more useful)

| # | New Widget | Replaces | Density target | Competitor | Justification |
|---|------------|----------|----------------|-------------|---------------|
| **R-1** | **Equity Curve (rebuilt)** with **deposits/withdrawals overlay + benchmark** (SPY/QQQ dashed line) | EquityCurveChart | unchanged size, restored correctness | **Bloomberg PORT EQR** + **Wealthfront historical chart** | Today shows flat cost basis. After fix, overlay benchmark + cash-flow markers (deposit ▲, withdraw ▼, dividend $) so the user can immediately distinguish *contribution-driven* vs *return-driven* growth — Wealthfront's signature pattern. |
| **R-2** | **Day P&L Distribution sparkline** (last 30 trading days, ±%) | (new) | h-7 row | **Robinhood Gold "Investing Activity"** | One row showing the last 30-day distribution as a horizontal sparkline + ±% spread. Anchored to actual daily snapshot deltas, not cost basis. |
| **R-3** | **Position Concentration (HHI)** + **Top-3-share** badge | (new) | 22px row | **FactSet PORT-CONC** | Herfindahl index in one number — HHI < 1500 = diversified, 1500–2500 = moderate, >2500 = concentrated. Single-row insight; no chart needed. |
| **R-4** | **Tax Lots / Holdings drilldown** (expand-row in main table) | (new — replaces empty space below table) | inline expand | **Fidelity Active Trader Pro Lot Lookup** | Click a row → expand into FIFO lots: open date, qty, cost-per-share, days-held, ST/LT classification, unrealised. Already 90% computable from `get_realized_pnl._OpenLot` walker. |
| **R-5** | **Sector Allocation — bars only (no treemap toggle)** | SectorAllocationPanel | h-32 (was h-80) | **Refinitiv Eikon Allocation panel** | Horizontal bars are easier to compare precisely than treemap squares (Cleveland & McGill 1984). Drop the toggle; -180px vertical. |
| **R-6** | **Dividend Income — single-row YTD strip** | DividendIncomeTimeline | h-7 row | **Public.com dividend tracker** | "Dividends YTD: $X across N tickers · Next: AAPL $0.25 on May 14". Falls back gracefully to "—" when zero. ~440px reclaimed. |
| **R-7** | **Cash + Settlement Strip** | CashManagementCard | h-7 row | **Schwab StreetSmart cash row** | Cash + Settlement-pending + Margin-available + Sweep APY. Drops to "—" cleanly. Same height — keep when fields populate. |
| **R-8** | **Broker Sync + Health Strip** (replaces RecentActivityFeed for paper-trader case) | RecentActivityFeed (paper case) | h-7 row | **Schwab account-sync row** | Last sync 3m ago · Next 1h · 0 errors. Activity feed still shown for active-broker users. |
| **R-9** | **Risk metrics strip — already terse** (keep, verify data) | RiskMetricsStrip | h-22 (already) | **Bloomberg PORT-RISK** | Beta, vol, max DD, Sharpe. Already correct shape. |
| **R-10** | **Realized P&L sparkline** (cumulative, daily) | RealizedPnLChart | h-12 (was h-280) | **Bloomberg P&L** | Replace 2-point chart with a 30-day cumulative sparkline + ST/LT split badges. ~268px reclaimed. |
| **R-11** | **Position Bar Heat Strip** (ticker × pnl% mini-bars) | (new) | h-12 row | **Finviz portfolio bar** | Each ticker as a colored vertical bar — height = position weight, color = pnl%. Identifies winners/losers at a glance. |
| **R-12** | **Exposure: gross / net / leverage row** | ExposureBreakdown panel (200px) | h-7 | **FactSet PORT-EXP row** | Single row: `Inv $X (98%) · Cash $Y (2%) · Lev 1.0× · Gross $X · Net $X`. ~190px reclaimed. |

**Net vertical budget after redesign**: ~700px (down from ~1,400px) for **12 widgets** (up from 8) — 2× density, more information, all anchored to single-row terminal aesthetic.

### Layout proposal

```
┌───────────────── KPI Strip (existing) ──────────────────────┐
│ Total · Day P&L · Unrealised · Realised · Top↑ · Top↓ · #pos │
├──────────────────────────────────────────────────────────────┤
│ R-7  CASH 0.0% · SETTLE — · MARGIN — · SWEEP —              │  h-7
│ R-3  HHI 1,847 (moderate) · Top3 share 71% · 5 names         │  h-7
│ R-12 INV $33.9k · CASH $0 · LEV 1.0× · GROSS — · NET —       │  h-7
│ R-2  DAY P&L 30D ▁▂▃▅▇▅▃▂ avg +0.42% · σ 1.1%               │  h-7
├─ Equity Curve (R-1) ─── 8col ──┬─ Sectors-bars (R-5) 4col ──┤
│ [equity + benchmark + flow]     │ Tech 71%  Cons 18% ...     │  h-200
├──────────────────────────────────┴────────────────────────────┤
│ Holdings table (existing) — expand-row drilldown (R-4)       │  h-auto
│   ▸ AAPL  50 sh  $213.85  +1.0%  $1,768  +19.8%  $10,693    │
│     ↳ lots: 50 sh @ $178.50  · 4mo · ST · +$1,768            │  on click
├──────────────────────────────────────────────────────────────┤
│ R-11 Position Bar Heat ▮▮▯▯▮  (vert bars: weight × pnl)     │  h-12
│ R-10 Realised cumulative ▁▂▃▄ · ST $X · LT $Y · 0 disposals  │  h-12
│ R-6  DIVIDENDS YTD $0 · Next: —                             │  h-7
│ R-8  BROKERS: 0 connected · last sync — · errors 0          │  h-7
├──────────────────────────────────────────────────────────────┤
│ R-9 RISK: β 1.12 · σ 18% · MaxDD -8% · Sharpe 0.91          │  h-22
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Equity Curve — Audit Verdict

### Reproducibility (verified live, 2026-05-09 17:30 UTC)

```sql
-- ALL 30 rows have total_value == total_cost == 32451, data_quality='partial_prices':
SELECT snapshot_date, total_value, total_cost, data_quality
FROM portfolio_value_snapshots ORDER BY snapshot_date;
-- 2026-03-27 → 2026-05-08: every row 32451.00 / 32451.00 / partial_prices
```

### Real value computed from live OHLCV (same instruments, May 6 closes)

```
AAPL  50 × $213.86 = $10,693  (cost  $8,925  → +$1,768)
MSFT  30 × $362.24 = $10,867  (cost $12,383  → -$1,515)
NVDA  20 × $86.30  = $ 1,726  (cost  $2,824  → -$1,098)
TSLA  15 × $311.12 = $ 4,667  (cost  $3,680  →   +$987)
AMZN  25 × $237.37 = $ 5,934  (cost  $4,640  → +$1,294)
                              ─────────────────────────
TOTAL              = $33,887  (cost $32,451  → +$1,436 / +4.4%)
```

**Chart shows $32,451 flat. Reality is $33,887 today, varying daily across the 30-day window.**

### Root causes

#### Bug H-1 (CRITICAL): Snapshot worker writes-once, never recomputes cost-basis fallbacks

**Path**: `services/portfolio/src/portfolio/workers/portfolio_snapshot_worker.py:393`

```python
# In _startup_catchup:
existing = await uow.portfolio_value_snapshots.list_range(portfolio.id, d, d)
if existing:
    logger.info("portfolio_snapshot_catchup_skip_existing", ...)
    continue   # ← skips even when the existing row is data_quality='partial_prices'
```

**What happened**:
1. Worker starts up at 13:46 UTC. Market-data S3 not yet healthy → `httpx.ConnectError`.
2. `_resolve_close_with_fallback` returns `(None, None)` → `total_value += holding_cost` (cost-basis fallback).
3. Snapshot row written: `total_value = 32451 = total_cost`, `data_quality = 'partial_prices'`.
4. S3 becomes reachable seconds later — but the worker already wrote the row.
5. On next startup catchup, `if existing: continue` skips it forever.

**Compounding**: The data_quality='partial_prices' flag is intended exactly to flag rows that should be recomputed when prices become fresh — but the worker never reads it back as a "needs retry" signal.

#### Bug H-2 (HIGH): Manual transactions don't update holdings

**Path**: `services/portfolio/src/portfolio/application/use_cases/record_transaction.py:168-181`

```python
# ── BP-264 (PLAN-0046 T-46-1-03) ─────────────────────────────────────
# Holdings are NO LONGER mutated here. Previously this use case called
# ``Holding.apply_delta`` per transaction... The fix is to derive
# holdings from the broker's position snapshot. Manual transaction
# APIs that previously relied on apply_delta would need a separate
# "manual holding adjust" path; that is deferred and out of scope for Wave 1.
```

**Implication**: For any user without a connected SnapTrade broker (i.e. all paper-trade / demo / non-SnapTrade users), recording a transaction does NOT update the holdings table. The `Holding.apply_delta` method (`domain/entities/holding.py:31`) is dead code reachable only through legacy/test paths.

The audit fixture confirms this: 0 transactions, 5 holdings — the holdings were seeded directly via SQL, not via the transaction flow.

### Fix recommendations (priority order)

| # | Fix | Effort | Files |
|---|-----|--------|-------|
| **F-H-1** | Worker: when an existing row has `data_quality != 'ok'`, recompute it instead of skipping. Add `force_recompute` flag to `_startup_catchup`. | 30 min | `portfolio_snapshot_worker.py:393` |
| **F-H-1b** | One-time backfill: SQL `DELETE FROM portfolio_value_snapshots WHERE data_quality='partial_prices'` then restart worker. | 5 min | (operational) |
| **F-H-2** | Re-introduce `apply_delta` invocation in `RecordTransactionUseCase`, but gated on `portfolio.source_kind != 'BROKER'`. Manual portfolios mutate holdings; broker-synced ones still derive from snapshots. | 2 hr | `record_transaction.py:168` |
| **F-H-3** | Add cash flow tracking: extend `PortfolioValueSnapshot` with `net_flow_in` (deposits-withdrawals on the day). Equity curve overlays markers. (Enables R-1 redesign.) | 3 hr | new migration + worker |

### Time-axis / aggregation review

- **Time axis**: ascending date, daily granularity. Correct.
- **Aggregation 1w/1m**: keeps the *last* snapshot in each ISO week / calendar month. Correct (`get_value_history.py:88`).
- **Resampling location**: in-memory Python pass over the asyncpg result. Correct for the volume (≤365 rows for 1Y / single portfolio).
- **Time-zone handling**: snapshot_date is a naive `date`; the snapshot worker uses `datetime.now(tz=UTC).date()` and the chart treats it as midnight UTC. Acceptable but **not labelled** anywhere in the UI — a user in Sydney looking at a "May 8" point is actually seeing the US trading day that closed at their local Friday morning. Recommend adding "Times in UTC" footer.
- **Deposits / withdrawals**: **NOT modeled**. There is no `cash_flow` column or `transactions` rollup feeding the snapshot. A user depositing $10k → buying AAPL at $190 → AAPL going to $213 would see a curve going from $0 → $9,500 (residual cash 0%) → $10,725 — but on the *deposit day* the curve discontinuously jumps because the prior snapshot was $0 and the new snapshot is $9,500. **Recommend adding deposit/withdrawal markers + a `time-weighted return` toggle** (see R-1).

---

## 4. Position Computation Audit

### Cost basis method — **WEIGHTED AVERAGE (not FIFO/LIFO)** for current holdings

`Holding.apply_delta` (`domain/entities/holding.py:31`) computes weighted-avg on buys, leaves avg unchanged on sells. **This is the running cost basis used for all UI display.** Standard for a brokerage statement view; correct.

`UpsertHoldingsFromSnapshotUseCase` (line 99-113) also uses weighted-avg when aggregating cross-account positions — but the resulting `average_cost` comes verbatim from SnapTrade's per-account `book_average_cost` field (which itself uses each broker's accounting method, typically FIFO or weighted-avg). Subtle: **the displayed avg_cost is the broker's truth, not a worldview-recomputed value.** This is correct for SnapTrade users and consistent across re-syncs.

### FIFO is used ONLY for realised P&L (`get_realized_pnl.py`)

`GetRealizedPnLUseCase` walks transactions chronologically, building per-instrument FIFO lot queues (`_OpenLot` deque). Correct, idiomatic, well-commented (lines 1-53). Long-term threshold: 365 days (US tax convention — close enough for display, not for filing). **Verdict: implementation is solid.**

### Currency handling

- `RecordTransactionUseCase` (`record_transaction.py:137`) **rejects** transactions whose currency ≠ portfolio currency → `CurrencyMismatchError` (400).
- `GetRealizedPnLUseCase` returns `currency = portfolio.currency` (line 269) — single-currency assumption documented (line 266-268).
- **Multi-currency portfolios are explicitly out of scope.** Any FX handling is deferred. Acceptable for v1, **but undocumented in the UI** — the user has no signal that mixing currencies isn't supported. Recommend a portfolio-level currency badge in the header.

### Splits / dividends

- **Splits**: NO modelling. `Holding.average_cost` is not adjusted on a stock split. SnapTrade may or may not surface the post-split book cost (it usually does). **Risk**: a user manually recording transactions across a 2-for-1 split will see incorrect avg cost.
- **Dividends**: tracked as `transactions` rows with `transaction_type=DIVIDEND` (cash amount in `amount` field). **Not** added to a cash balance (cash = 0 stub). Not deducted from cost basis (correct — DRIP would add new lots, plain dividends are income).

### Transaction batching / idempotency

`RecordTransactionUseCase` uses `idempotency.create_if_not_exists` (atomic INSERT-ON-CONFLICT, BP-035) plus a TOCTOU recovery via `IntegrityError` catch (line 222-238). **Solid.**

### Bugs found

| # | Severity | Bug | File:Line |
|---|----------|-----|-----------|
| H-1 | CRITICAL | Equity curve frozen at cost basis — see §3 | `portfolio_snapshot_worker.py:393` |
| H-2 | HIGH | Manual transactions don't update holdings | `record_transaction.py:168` |
| C-1 | MEDIUM | `cash_value` always 0 — but no UI caveat (cash card silently shows $0) | `compute_portfolio_value.py:232` + `get_exposure.py:187` |
| C-2 | LOW | Split adjustment not modelled, no UI warning | `domain/entities/holding.py` |
| C-3 | LOW | Multi-currency rejected at API but no UI hint of single-currency restriction | `record_transaction.py:137` |
| C-4 | INFO | `Holding.apply_delta` is dead code in production paths but still exposed in domain — confusing for future contributors | `domain/entities/holding.py:31` |

**Overall correctness verdict for position computation**: the code that runs (FIFO realised P&L, weighted-avg cost basis from broker snapshot) is correct. **The code that DOESN'T run** (manual-mode `apply_delta`) is the silent failure mode. The chain `record_transaction → snapshot → holdings update → re-snapshot → curve update` is broken at link 2.

---

## 5. Implementation Order (highest-leverage first)

1. **F-H-1 + F-H-1b** — fix snapshot worker recompute logic + delete stale rows (2 hours total). **Restores trust in the chart immediately.**
2. **R-1** — equity curve redesign with deposit/withdrawal markers + benchmark overlay (4 hours). **Builds on F-H-1.**
3. **R-3 + R-7 + R-8 + R-12** — replace 4 panels with 4 single-row strips (Concentration HHI, Cash row, Broker row, Exposure row). 4 × 30 min = 2 hours, **reclaims ~600px**.
4. **R-5** — drop sector treemap, keep bars only (15 min, -180px).
5. **R-10** — realised P&L sparkline replacing 280px chart (1 hour, -270px).
6. **F-H-2** — manual-transaction holdings update (2 hours). Unblocks paper-trader path.
7. **R-2 + R-11** — new sparkline strips (Day P&L distribution + Position Bar Heat). 2 hours.
8. **R-4** — tax-lots expand-row in main table (3 hours, builds on existing FIFO walker).
9. **R-6** — Dividend YTD single-row (30 min).

Total estimated effort: **~16 hours** for full redesign + bug fixes.

---

## 6. Implementation (this session)

This audit covers analysis only. Time budget at end of investigation does not permit implementation in this run. **Suggested next step**: run `/implement` against item 1 (F-H-1) — it is a 30-min surgical fix on a single function; massive UX leverage.

### Suggested patch for F-H-1 (preview)

```python
# In _startup_catchup — replace the existing skip-if-existing block:
existing = await uow.portfolio_value_snapshots.list_range(portfolio.id, d, d)
if existing and existing[0].data_quality == DATA_QUALITY_OK:
    logger.info("portfolio_snapshot_catchup_skip_existing_ok", ...)
    continue
# else: row is missing OR is partial_prices — recompute (idempotent upsert).
```

Combined with the SQL one-liner

```sql
DELETE FROM portfolio_value_snapshots WHERE data_quality = 'partial_prices';
```

executed before the worker restarts, the chart will populate with real OHLCV-derived values within seconds.

---

## Cross-References

- **PRD-0027 §8 Portfolio** — original spec for KPI strip + tabs
- **PLAN-0046** — Wave 4/5: snapshot worker + equity curve
- **PLAN-0051 Wave A** — FIFO realised P&L
- **PLAN-0053 §T-B-2-04..06** — cash card, activity feed, dividend timeline
- **BP-264** — manual `apply_delta` removed; SnapTrade-only path (the trigger for H-2)
- **F-401** — partial-prices fallback flag (the trigger for H-1)
- Memory note `project_platform_status_2026_04_28.md` — TastyTrade brokerage fixes — relevant only for users with broker connections
