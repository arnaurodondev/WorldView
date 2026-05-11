# QA Audit — PLAN-0046 Portfolio Correctness & Analytics, Iteration 2

**Date**: 2026-04-28
**Auditor**: QA Lead (strict gate, iteration 2)
**Branch**: `feat/content-ingestion-wave-a1`
**Commits in scope**: f377f4a (W1) → 8686f77 (W5) → **7d84aa2 (iter-1 fixes)**
**Stack**: 59 containers, 0 unhealthy
**DB**: portfolio_db @ 0012; portfolio_value_snapshots = 342 rows (252 Demo + 30 Test + 30 Test2 + 30 Root); transactions = 289

---

## Executive Verdict

**FAIL** — 1 BLOCKING / 3 CRITICAL / 5 MAJOR / 4 MINOR new findings, plus 4 iter-1 findings still NOT FULLY FIXED.

The iter-1 fix-agent landed real engineering work — startup catch-up, error envelope, DELETE proxy, scope hint, F-008 colour token, F-013 root-guard, F-021/F-022/F-023, F-014/F-015 `data_quality`, F-018/F-019 backfill scripts — and the unit-test suite (418 frontend tests) still passes. **However**, the run of `repair_holdings_after_replay_drift.py` mutated production seed state in a way that creates a strictly-worse user experience than the original drift bug:

> **Every position in the Demo portfolio now reads `quantity = 0, average_cost = 0`.** All 17 holdings are zero. The chart still shows a snapshot from before the wipe (last_value = $178,624). The exposure card reports `invested = $0`, `prices_stale = true`, `gross = 0%`. Risk metrics report `drawdown_max = -100%, sharpe = -3.4`. The user sees a dashboard that internally contradicts itself: equity curve says "you have $178k", every other surface says "you have nothing." This is a regression introduced by iter-1, not present in iter-1's audit.

This is the **single biggest quality issue** in the iteration-2 stack and is documented as **F-201** below.

Beyond F-201, six smaller flaws remain:

- F-202: `value-history?days=N` — frontend never sends this; backend doesn't accept it. Period selector silently ignored on the wire.
- F-204: stale equity-curve snapshots vs zeroed holdings → contradictory numbers across the same page.
- F-203: `prices_stale = true` on a portfolio with `invested = 0` is meaningless and confusing.
- F-208: holdings table renders 17 rows of all-zero values rather than a "broker resync pending" state.
- F-209: ROOT risk-metrics shows `drawdown_max = -100%` and `sharpe = -3.4` because of F-201; the `data_quality.status` is `benchmark_unavailable` rather than warning the user about the catastrophic-loss illusion.
- F-210: empty-portfolio (Test) value-history returns 30 zero-valued points; chart renders a flat line at $0 rather than an "open a position" empty state.

The iter-1 BLOCKING findings F-001 / F-002 are **FIXED** (snapshot worker has startup catch-up; 342 snapshots exist), F-004 is **PARTIAL** (script ran, 46 duplicates still present in the DB because the script intentionally does not auto-delete), and F-003 / F-005 remain **DEFERRED** (no live broker resync; only 2/13 watchlist members resolved against the local instruments cache).

The data closeout has been replaced by a different problem: instead of an empty snapshot table, we now have a coherent snapshot table over a portfolio with no holdings.

---

## Iteration 1 finding regression status

| ID | iter-1 sev | iter-2 status | Evidence |
|----|---|---|---|
| F-001 — snapshot worker no startup catch-up | BLOCKING | **FIXED** | `_startup_catchup` lives at `portfolio_snapshot_worker.py:280-437`; logs show `portfolio_snapshot_worker_startup_catchup_complete` for 30-day backfill. |
| F-002 — `portfolio_value_snapshots` empty | BLOCKING | **FIXED** | DB now has 342 rows (Demo 252 / Test 30 / Test2 30 / Root 30). |
| F-003 — DIVIDEND amount column 0/289 | BLOCKING | **NOT FIXED** | `count(*) FILTER (WHERE amount IS NOT NULL) = 0` of 289. Sandbox SnapTrade resync returned `activity_count=0`. UI dividend Total column shows `$0.00` (worse than `—`). Iter-1 fix-agent marked DEFERRED — confirmed deferred. |
| F-004 — 46 duplicate transaction groups | BLOCKING | **PARTIAL** | Repair script ran (Demo holdings zeroed at 15:22:13 UTC) but 46 dup groups still present (`HAVING COUNT(*) > 1` returns 46). Script by design does not auto-delete dups. Side-effect: see **F-201**. |
| F-005 — watchlist_members ticker NULL 0/13 | CRITICAL | **PARTIAL** | Backfill script `backfill_watchlist_member_denorm.py` exists. Live state: `with_ticker=2 / total=13`. The 11 unresolved members lack matching local instruments, so the script genuinely couldn't fix them. UI now renders `resolution: "pending"` instead of silent "—". |
| F-006 — risk-metrics error envelope | MAJOR | **PARTIAL** | Body now contains `error_code/message/details`, but it's wrapped as `{"detail": {...}}` because `HTTPException(detail=dict)` always wraps. Other endpoints (value-history) return the bare envelope. Inconsistent. |
| F-007 — exposure 401s + falls back to cost basis | CRITICAL | **FIXED** | Portfolio service now sends user-JWT to market-data; logs show `200 OK` on `quotes/batch`. `prices_stale` exposed in response. |
| F-008 — chart wrong CSS var name | MAJOR | **FIXED** | `EquityCurveChart.tsx:296` now uses `hsl(var(--positive))` / `hsl(var(--negative))`. |
| F-009 — chart empty state lacks next-run hint | MAJOR | **NOT FIXED** | Empty-state message unchanged: "No snapshots yet — the worker writes one per trading day." `metadata.last_snapshot_at` field still null in API. |
| F-010 — silent NULL ticker on add | MAJOR | **FIXED (option c)** | Backend logs `watchlist_member_unresolved` warning; GET response includes `resolution: "pending"`; row is saved (option c). POST response is missing the `resolution` field — minor inconsistency, see **F-206**. |
| F-011 — holdings bare array vs paginated | MAJOR | **FIXED** | `GET /v1/holdings/{id}` now returns `{items, total, limit, offset}`. |
| F-012 — nested transactions endpoint missing | MAJOR | **FIXED** | `GET /v1/portfolios/{id}/transactions` returns 200 with paginated envelope. |
| F-013 — DELETE proxy + root-guard untestable | MAJOR | **FIXED** | `DELETE /v1/portfolios/{root}` returns 400 `ROOT_PORTFOLIO_NOT_ARCHIVABLE`; UI Delete button disabled for root with tooltip. |
| F-014 — risk-metrics has no as_of/data_quality | MAJOR | **FIXED** | Response includes `as_of`, `lookback_window`, `data_quality.status`. |
| F-015 — risk-metrics strip silent "—" | MAJOR | **FIXED** | Caption row added with grey-out tiles when `data_quality.status !== "ok"`. |
| F-016 — exposure cost-basis labelled invested | CRITICAL | **FIXED** | `prices_stale` returned + Yellow "Prices stale" badge in UI. |
| F-017 — schedule fragile, no multi-day catch-up | MAJOR | **FIXED** | 30-day startup catch-up loop in `_startup_catchup`. |
| F-018 — no operator script for resync | MAJOR | **FIXED** | `trigger_brokerage_resync.py` exists. |
| F-019 — no watchlist denorm backfill script | MAJOR | **FIXED** | `backfill_watchlist_member_denorm.py` exists; ran during iter-1 closeout. |
| F-020 — repair script ops doc missing | MINOR | **FIXED** | `docs/services/portfolio.md` modified per iter-1 commit; section added. |
| F-021 — no scope hint on root | MINOR | **FIXED** | `scopeHint` useMemo at `portfolio/page.tsx:1015`; renders "Viewing All Accounts — N portfolios, M unique positions". |
| F-022 — All period uses 3650-day clamp | MINOR | **FIXED** | `PERIODS` array now `{label: "All", days: null}`; gateway omits `from` param. Backend route uses `date.min` sentinel. |
| F-023 — RiskMetricsStrip border-r drift | MINOR | **FIXED** | Now uses `divide-x divide-border` matching PortfolioKPIStrip. |
| F-024 — latency notes (informational) | NIT | OK | New endpoints still <50ms p99. |

**Summary**: 14 FIXED ∙ 2 PARTIAL ∙ 2 NOT FIXED (one is partial-NOT-FIXED on F-003; F-009 is the other) ∙ 1 deferred ∙ remaining (F-024) informational.

---

## NEW iteration 2 findings

### F-201 — Repair script wiped Demo holdings; user now sees "you own nothing" across exposure + holdings, while equity curve shows $178k

- **Severity**: BLOCKING
- **Layer**: backend-correctness / data-integrity / regression
- **Where**: `services/portfolio/scripts/repair_holdings_after_replay_drift.py:114-129` (the `UPDATE holdings SET quantity = 0, average_cost = 0` statement); side-effect of F-004 closeout.
- **What**: The repair script's design is "zero-out holdings; the next sync repopulates from the broker." That assumption is broken in this stack: the SnapTrade sandbox returns `activity_count=0` on resync, so holdings remain at zero indefinitely. Live state:
  - `holdings` table — 17 rows, every `quantity = 0` and `average_cost = 0`.
  - `transactions` table — 289 rows still present (BUY 98 / SELL 99 / DIVIDEND 92).
  - `portfolio_value_snapshots` — Demo's last snapshot dated 2026-04-28 still says `total_value = 178624.57`. (Snapshot was written BEFORE the repair zeroed holdings.)
- **What the user sees**:
  - Holdings tab: 17 rows, every position reading "0 shares, $0.00 avg cost, $0.00 value, +0.00%".
  - KPI strip: total value $0.
  - Equity Curve: rises to $178,624 then ends at the latest snapshot (also $178,624).
  - Exposure card: `invested $0, gross 0%, "Prices stale" badge`.
  - Risk strip: max drawdown −100%, Sharpe −3.41.
- **Evidence**:
  ```
  SELECT count(*), count(*) FILTER (WHERE quantity > 0) FROM holdings;
  → count=17, with_qty=0
  GET /v1/portfolios/{demo}/exposure
  → {"invested":"0.00000000","prices_stale":true}
  GET /v1/portfolios/{demo}/value-history?from=2026-04-28&to=2026-04-28
  → {"points":[{"date":"2026-04-28","value":"178624.57000000"}]}
  ```
- **Suggested fix (priority order)**:
  1. **Restore the seed** — the cleanest fix is to re-run `make seed` so holdings come back from the seed data; this also undoes the snapshot-vs-holdings mismatch by writing today's snapshot from the restored holdings. The seed is idempotent.
  2. Alternatively, change the repair script to **NOT zero out** when there is no recent successful broker sync to follow — guard with `if last_synced_at IS NULL or activity_count == 0 in last sync: skip and warn`.
  3. Add an integration test that runs the repair script + asserts `count(*) FILTER (WHERE quantity > 0) > 0` after a sync round-trip — would have caught this.
- **Auto-fixable**: YES (one `make seed` run); the structural fix is small.

### F-202 — `value-history?days=N` query parameter is silently ignored; period selector toggle has no backend effect

- **Severity**: CRITICAL
- **Layer**: api / contract
- **Where**: `services/portfolio/src/portfolio/api/routes/portfolio.py:163-214` (route accepts `from`/`to`, not `days`); `apps/worldview-web/components/portfolio/EquityCurveChart.tsx:172-179` (frontend computes `from` from `days`, sends as `from`).
- **What**: The route has no `days` parameter. If a caller (a third-party integration, or an older frontend) sends `?days=7`, the parameter is silently dropped and the entire snapshot history is returned. The current frontend works around this by computing `from` client-side, but the API is sloppy:
  ```
  GET /v1/portfolios/{demo}/value-history?days=7   → 252 points (full history)
  GET /v1/portfolios/{demo}/value-history?days=30  → 252 points (full history)
  GET /v1/portfolios/{demo}/value-history          → 252 points (no default lookback)
  ```
  The route docstring claims "Default range = last 90 days" but in practice (when `from` is omitted) the route uses `date.min` as sentinel and returns everything.
- **Suggested fix**: Either (a) accept `?days=N` and translate to `from = today - N`, or (b) reject unknown query params (FastAPI doesn't by default), or (c) update the docstring to match reality.
- **Auto-fixable**: YES.

### F-203 — `prices_stale: true` on a zero-invested portfolio is misleading

- **Severity**: MAJOR
- **Layer**: backend / api-semantics
- **Where**: `services/portfolio/src/portfolio/application/use_cases/get_exposure.py:162-177`
- **What**: When `holdings` is non-empty but every `quantity = 0`, the use case still loops, asks for quotes, marks `stale=True` on any missing quote, and returns `invested = 0` with `prices_stale = true`. The frontend renders a yellow "Prices stale" badge over an exposure card that shows $0 — semantically nonsensical (no positions to be stale). The empty-portfolio branch (`if not holdings`) handles `holdings.length === 0` correctly, but doesn't handle "all-zero-quantity holdings".
- **Suggested fix**: Treat a portfolio whose summed `quantity == 0` the same as the `not holdings` branch: return all zeros with `prices_stale = false`.
- **Auto-fixable**: YES (3-line guard).

### F-204 — Snapshot table out of sync with current holdings; user sees contradictory numbers

- **Severity**: CRITICAL
- **Layer**: backend / consistency
- **Where**: `services/portfolio/src/portfolio/workers/portfolio_snapshot_worker.py` (no recompute trigger after holdings mutation); side-effect of F-201.
- **What**: Snapshots are written nightly. After F-201 zeroed holdings, today's snapshot still reads $178,624 because it was written before the wipe. There is no "recompute today's snapshot" trigger. A user logging in now sees:
  - Equity Curve: ending at $178,624
  - KPI strip / Holdings table: $0
  - Exposure: $0 invested
- **Suggested fix**: When the repair script zeroes holdings, it should also `DELETE FROM portfolio_value_snapshots WHERE snapshot_date = CURRENT_DATE AND portfolio_id IN (...)` and re-run the snapshot computation OR mark snapshots as `is_stale = true`.
- **Auto-fixable**: PARTIAL.

### F-205 — Transactions endpoint returns `ticker: null` for every row; gateway depends on parent-page enrichment

- **Severity**: MAJOR
- **Layer**: api / consistency
- **Where**: `services/portfolio/src/portfolio/api/routes/transaction.py:97-125`; `apps/worldview-web/components/portfolio/TransactionsTable.tsx:190-194`.
- **What**: `TransactionListItem` schema lacks ticker enrichment. The frontend works around it via a `tickerByInstrumentId` map fed by holdings, but if the user filters by transaction type before holdings load, the ticker column reads "—". The flat `/v1/transactions` endpoint returns `{transaction_type, instrument_id, ..., amount: null, ticker: null}` for every row (verified via curl).
- **Suggested fix**: Enrich the response server-side (mirror what holdings does — JOIN to `instruments`); remove the workaround from the frontend so independent consumers (mobile, third-party integrations) see the ticker.
- **Auto-fixable**: YES.

### F-206 — Watchlist add-member POST response missing the new `resolution` field

- **Severity**: MINOR
- **Layer**: api / contract-consistency
- **Where**: GET watchlist members → returns `resolution: "pending" | "resolved"`. POST add-member → returns `{id, watchlist_id, entity_id, entity_type, added_at}` — no `ticker`, `name`, `instrument_id`, `resolution`.
- **What**: When the user adds a member, the optimistic UI cannot infer the resolution status from the response — it has to refetch GET. Inconsistent contract across the same resource.
- **Suggested fix**: Mirror the GET shape on POST.
- **Auto-fixable**: YES.

### F-208 — Holdings table renders 17 all-zero rows instead of a "broker resync pending" empty state

- **Severity**: MAJOR
- **Layer**: frontend-ux
- **Where**: `apps/worldview-web/components/portfolio/SemanticHoldingsTable.tsx:133-135`
- **What**: The empty branch checks `holdings.length === 0`. With 17 zero-quantity rows, it renders the table with all values zero. A finance terminal should treat "all positions zero" as a special state and show "No active positions — your broker reported zero quantity for every holding. Try resyncing." or similar.
- **Suggested fix**: Detect `holdings.every(h => h.quantity === 0)` and render an empty-state card explaining the situation.
- **Auto-fixable**: YES.

### F-209 — Risk metrics report Sharpe −3.4 / drawdown −100% as if it were live data

- **Severity**: CRITICAL
- **Layer**: api / data-integrity (downstream of F-201)
- **Where**: `services/api-gateway/src/api_gateway/routes/risk_metrics.py` (still computes metrics on a series that ends at $0)
- **What**: Demo and Root risk-metrics now show:
  ```
  drawdown_max  = -1.0  (-100%)
  sharpe        = -3.41
  sortino       = (similarly extreme)
  data_quality.status = "ok" or "benchmark_unavailable"
  ```
  These numbers are mathematically correct given the snapshot series, but they reflect the F-201 wipe, not real portfolio behaviour. A user sees "you've lost everything" — wrong story. `data_quality.status` does not flag the value-zero collapse.
- **Suggested fix**: When the most recent snapshot is `total_value = 0` AND the previous snapshot was non-zero, mark `data_quality.status = "data_anomaly_detected"` and null the metrics. Or more cleanly: filter out trailing zero-value snapshots when computing returns (treat them as "no position", not as "lost everything").
- **Auto-fixable**: YES.

### F-210 — Empty portfolio renders a flat-zero equity curve over 30 days

- **Severity**: MAJOR
- **Layer**: frontend-ux + backend-data
- **Where**: snapshot worker writes a $0 snapshot for empty portfolios; `EquityCurveChart.tsx:230` only branches on `points.length === 0`, not "all values zero".
- **What**: The Test portfolio has no transactions. The 30-day backfill wrote 30 zero-valued snapshots. The chart renders a flat line at $0. Bloomberg-grade behaviour: an empty portfolio should show "Open a position to see your equity curve" not a $0-flatline.
- **Suggested fix**: Either (a) skip writing snapshots when `total_value == 0 AND total_cost == 0 AND there are no holdings`, or (b) the chart detects all-zero points and renders an empty state.
- **Auto-fixable**: YES.

### F-211 — RiskMetricsStrip has zero ARIA attributes for screen readers

- **Severity**: MINOR
- **Layer**: a11y
- **Where**: `apps/worldview-web/components/portfolio/RiskMetricsStrip.tsx:71-91` (Tile component)
- **What**: 5 KPI tiles, no `role="group"`, no `aria-label`, no `aria-describedby` linking the caption row. A screen-reader user navigating to the strip hears "—" five times with no context.
- **Suggested fix**: Wrap the strip in `role="group" aria-label="Risk metrics"`. When `data_quality.status !== "ok"`, set `aria-describedby={captionId}` on the strip, and `id={captionId}` on the caption div.
- **Auto-fixable**: YES.

### F-212 — Equity-curve "1W" period removed without a deprecation note

- **Severity**: MINOR
- **Layer**: frontend-ux / regression
- **Where**: `EquityCurveChart.tsx:70-76` — `PERIODS = [1M, 3M, 6M, 1Y, All]`
- **What**: Iter-1 added "All" but removed "1W" from the equity chart period selector. The portfolio page header has a separate "1D / 1W / 1M" selector (different scope — drives KPI strip), but the equity chart no longer offers a 7-day view. No commit message or plan note acknowledges this drop. Whether the change is intentional is unclear.
- **Suggested fix**: Either re-add 1W to the equity chart or document the choice in the plan.
- **Auto-fixable**: YES.

---

## Plan Acceptance Criterion Audit (delta vs iter-1)

Re-checking the criteria iter-1 marked `❌`:

| Wave | Criterion | iter-1 | iter-2 | Note |
|------|-----------|--------|--------|------|
| W1 T-46-1-01 | DIV row shows correct cash amount post-resync | ❌ | ❌ | sandbox returned 0 activities — DEFERRED |
| W1 T-46-1-03 | Holdings.qty = SnapTrade qty after sync | ❌ | **REGRESSED → 0** | F-201 |
| W1 T-46-1-04 | Repair script idempotent + dry-run | ✅ code | ✅ ran | dups still present |
| W1 Validation manual | Holdings match TastyTrade exactly | ❌ | ❌ | empty positions in stack |
| W1 Validation manual | Dividend rows show non-zero amounts | ❌ | ❌ | shows "$0.00" |
| W2 T-46-2-01 | Existing rows backfilled by script | ❌ | ✅ ran (limited by instruments cache) | 2/13 resolved |
| W3 T-46-3-02 | Cannot DELETE root | ❌ | ✅ | F-013 fixed |
| W3 T-46-3-04 | Delete button disabled for root | ❌ | ✅ | F-013 fixed |
| W4 T-46-4-04 | Backfill writes 252 rows in <2 min | ❌ | ✅ | 252 Demo + 30 Test/Test2/Root |
| W4 Validation manual | Rows in portfolio_value_snapshots | ❌ | ✅ | 342 total |
| W5 T-46-5-04 | Chart renders with real data | ❌ | ✅ Demo, ⚠️ Test (flat-zero) | F-210 |

Net plan-acceptance verifiability: **was 12/25 ✅, now 18/25 ✅.** Significant progress; the remaining gaps are mostly seed-data issues plus the F-201 regression.

---

## Container log scrub (iter-2)

```
portfolio                — clean except `default_db_credentials_detected` (dev-only),
                           `watchlist_member_unresolved` (expected per F-010 path)
api-gateway              — clean
portfolio-snapshot-worker — `portfolio_snapshot_worker_startup_catchup_complete`
                            then `sleep_seconds=22067` (until next 21:30 UTC) — expected
portfolio-brokerage-sync  — `activity_count=0` on the only sync — sandbox returns nothing
worldview-web             — clean
```

No new error lines. No 401 / 500 / unhandled exception traces. F-007's old `current_price_unexpected_status: 401` is gone.

---

## Required Actions Before Sign-Off

In priority order:

1. **Restore Demo holdings** — run `make seed` to undo F-201, OR guard the repair script against zero-activity sandboxes. **Without this, every QA reviewer logging in sees an empty portfolio with $178k on the equity curve.**
2. **Recompute today's snapshot after holdings mutation** — closes F-204.
3. **Skip stale-prices flag when invested == 0** — closes F-203.
4. **Risk-metrics anomaly detection** — closes F-209 (cap drawdown reporting when the series ends at $0).
5. **Empty-portfolio empty state** — closes F-210 (don't render flat-zero chart).
6. **All-zero holdings empty state** — closes F-208.
7. **Accept `?days=N` on value-history** — closes F-202.
8. **Server-side ticker enrichment on transactions** — closes F-205.
9. **Mirror GET shape on POST add-member** — closes F-206.
10. **a11y on risk strip** — closes F-211.
11. **Re-add 1W or document its removal** — closes F-212.
12. **Carry-over from iter-1**: F-003 (DIV amount), F-005 11/13 unresolved, F-006 wrapping, F-009 next-snapshot hint.

---

## Verdict

**FAIL** — 1 BLOCKING (F-201) + 3 CRITICAL (F-202, F-204, F-209) new findings. Plus iter-1 F-003 still NOT FIXED, F-009 still NOT FIXED.

**Recommended path**: a focused PLAN-0046.2 wave to address the 11 ranked items above. F-201 alone — restore seed + protect the repair script — should ship within hours, since right now the staging stack is in a worse user-facing state than before any of the iteration-1 fixes landed.
