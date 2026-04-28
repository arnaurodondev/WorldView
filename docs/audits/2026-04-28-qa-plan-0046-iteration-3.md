# QA Audit — PLAN-0046 Portfolio Correctness & Analytics, Iteration 3

**Date**: 2026-04-28
**Auditor**: QA Lead (strict gate, iteration 3)
**Branch**: `feat/content-ingestion-wave-a1`
**HEAD commit**: `d0b56b3` (fix(portfolio/PLAN-0046): address 13 iteration-2 QA findings)
**Stack**: 0 unhealthy containers (all healthy)
**Live state**:
- portfolio_db @ `0012`
- holdings: 17 rows; **5 with quantity > 0** (Demo seed restored)
- portfolio_value_snapshots: 342 rows (Demo 252 / Test 30 / Test2 30 / Root 30)
- transactions: 289 (still 0 with `amount IS NOT NULL` — DEFERRED)
- watchlist_members: 14 total, 3 with `ticker NOT NULL`

---

## Executive Verdict

**FAIL** — 1 BLOCKING / 1 CRITICAL / 2 MAJOR / 1 MINOR new findings. Plus iter-2 F-203 / F-209 / F-210 / F-005 not fully closed despite the iter-2 commit landing real fixes in those code paths.

The iter-2 fix-agent landed substantial engineering: F-201 seed restored, F-202 `?days=N` accepted, F-205 server-side ticker enrichment, F-206 POST mirrors GET, F-208 all-zero empty state, F-211 a11y, F-212 1W reintroduced, F-009 next-snapshot hint. The 418 frontend tests still pass. **However**, the live stack reveals a pair of regressions and three iter-2 fixes that don't actually fire on the seed data the user ships with:

1. **F-301 (BLOCKING)**: Portfolio service's `current_price_client` reads `quote["price"]` from the market-data response, but S3's `/api/v1/quotes/batch` returns `{bid, ask, last, ...}` — there is **no `price` key**. Every per-quote lookup returns None → every holding falls back to average_cost → exposure card reports `prices_stale: true` with `invested = $32,451` (cost basis) on a Demo portfolio whose live market value is closer to ~$45,640 (using `last` quotes). This is the same F-007 bug iter-1 thought it fixed: auth was the symptom, the response shape mismatch is the underlying cause. The portfolio service is **silently rendering cost basis as live exposure** every time the user opens the page.
2. **F-302 (CRITICAL)**: Risk-metrics anomaly detection only checks `values[-1] == 0 AND values[-2] > 0`. Root portfolio's snapshot series contains an **intermediate** $0 (Apr 24) with non-zero values on either side, which produces a real `drawdown_max = -100%` and `sharpe = -3.8` while `data_quality.status` reports `benchmark_unavailable` (not `data_anomaly_detected`). The user sees catastrophic risk metrics with no caption explaining the underlying contaminated history.
3. **F-303 (MAJOR)**: SemanticHoldingsTable renders 12 zero-quantity rows alongside 5 active positions on the Demo portfolio. F-208's all-zero empty state only fires when **every** row has zero quantity; mixed portfolios show noise rows with $0 value, $0 P&L, sector="—" — these are stale orphans from the F-201 wipe that backfill never cleaned up. The table should filter quantity==0 holdings (or render them in a collapsed "inactive positions" group).
4. **F-304 (MAJOR)**: Watchlist seed data uses `instrument_id` UUIDs in the `entity_id` column. The backfill script joined on `instruments.entity_id`, which doesn't match. 11/14 seeded watchlist rows still display "—". The script is correct; the seed is wrong. Frontend now shows "resolving…" badge on these (good UX) but the underlying data corruption persists, defeating the purpose of the backfill closeout.
5. **F-305 (MINOR)**: Demo portfolio snapshot history shows total_value dropping from $342k (Apr 27) to $38k (Apr 28) — a -88% jump caused by the iter-2 reseed reducing the holding set. The chart will show a vertical cliff for any user opening it today. Harmless after a few days of new snapshots, but jarring on initial QA review.

The five iter-1 BLOCKING findings — F-001, F-002, F-003, F-004 — have shifted: F-001/F-002 stay FIXED (snapshots populate, worker has startup catch-up), F-003 is still DEFERRED (sandbox returns no activities), F-004 PARTIAL (script ran but doesn't dedup transactions). The plan acceptance criteria are now 19/25 ✅ vs 18/25 in iter-2.

---

## Iteration 1 + 2 finding regression status

| ID | First reported | Sev (orig) | iter-2 status | iter-3 verdict | Live evidence (iter-3) |
|----|---|---|---|---|---|
| F-001 — snapshot worker no startup catch-up | iter-1 | BLOCKING | FIXED | **FIXED** | `portfolio_snapshot_worker_startup_catchup_complete` log; 30-day backfill on every restart. |
| F-002 — value_snapshots empty | iter-1 | BLOCKING | FIXED | **FIXED** | 342 rows total; Demo today = $38,703.95. |
| F-003 — DIVIDEND amount 0/289 | iter-1 | BLOCKING | NOT FIXED | **NOT FIXED (DEFERRED)** | `count(*) FILTER (WHERE amount IS NOT NULL) = 0` of 289. Sandbox SnapTrade returns nothing. |
| F-004 — 46 dup tx groups | iter-1 | BLOCKING | PARTIAL | **PARTIAL** | Still 46 groups in the DB. Script does not auto-dedup transactions — only zeroes holdings. |
| F-005 — watchlist_members ticker NULL | iter-1 | CRITICAL | PARTIAL (2/13) | **PARTIAL (3/14)** | `with_ticker=3, total=14`. Backfill script correct; seed data wrong (see F-304). |
| F-006 — risk-metrics error envelope | iter-1 | MAJOR | PARTIAL | **FIXED** | Now returns bare `{error_code, message, details}` — no `{detail: {...}}` wrap. |
| F-007 — exposure 401 + cost basis fallback | iter-1 | CRITICAL | FIXED (auth) | **REGRESSED via F-301** | Auth fix landed (200 OK on quote calls), but the response-shape mismatch hides every quote → exposure still rendering cost basis. |
| F-008 — wrong CSS var name | iter-1 | MAJOR | FIXED | **FIXED** | `EquityCurveChart.tsx:343` uses `hsl(var(--positive))`. |
| F-009 — chart empty-state lacks next-run hint | iter-1 | MAJOR | NOT FIXED | **FIXED** | API returns `metadata.next_scheduled_run_utc`; chart renders sub-line "Next snapshot scheduled for YYYY-MM-DD HH:MM UTC". |
| F-010 — silent NULL ticker on add | iter-1 | MAJOR | FIXED (option c) | **FIXED** | POST returns `resolution`, `ticker`, etc.; UI shows "resolving…" badge. |
| F-011 — holdings bare array | iter-1 | MAJOR | FIXED | **FIXED** | `GET /v1/holdings/{id}` returns `{items, total, limit, offset}`. |
| F-012 — nested transactions endpoint | iter-1 | MAJOR | FIXED | **FIXED** | `GET /v1/portfolios/{id}/transactions` returns 200 with envelope. |
| F-013 — DELETE proxy + root-guard | iter-1 | MAJOR | FIXED | **FIXED** | DELETE root → 400 `ROOT_PORTFOLIO_NOT_ARCHIVABLE` with details. |
| F-014 — risk-metrics no as_of/data_quality | iter-1 | MAJOR | FIXED | **FIXED** | `as_of`, `lookback_window`, `data_quality.{status,n_returns,lookback_days}` all present. |
| F-015 — risk strip silent "—" | iter-1 | MAJOR | FIXED | **FIXED** | Caption row + grey-out + per-tile aria-label. |
| F-016 — exposure cost-basis labelled invested | iter-1 | CRITICAL | FIXED | **REGRESSED via F-301** | `prices_stale: true` is correctly returned, but the underlying problem (cost basis as exposure) is back because no quote ever resolves. |
| F-017 — schedule fragile, no multi-day catch-up | iter-1 | MAJOR | FIXED | **FIXED** | 30-day catch-up loop confirmed by logs. |
| F-018 — no operator script for resync | iter-1 | MAJOR | FIXED | **FIXED** | `trigger_brokerage_resync.py` present. |
| F-019 — no watchlist denorm backfill | iter-1 | MAJOR | FIXED | **FIXED (script); F-304 separate** | Script ran; data limitation tracked separately. |
| F-020 — repair script ops doc | iter-1 | MINOR | FIXED | **FIXED** | `docs/services/portfolio.md` updated. |
| F-021 — no scope hint on root | iter-1 | MINOR | FIXED | **FIXED** | "Viewing All Accounts — N portfolios, M unique positions" rendered at `portfolio/page.tsx:1015`. |
| F-022 — All period uses 3650-day clamp | iter-1 | MINOR | FIXED | **FIXED** | "All" → `days: null` → omits param. |
| F-023 — strip border drift | iter-1 | MINOR | FIXED | **FIXED** | `divide-x divide-border`. |
| F-024 — latency informational | iter-1 | NIT | OK | OK | All endpoints <50ms p99. |
| F-201 — Demo holdings wiped | iter-2 | BLOCKING | (new) | **FIXED** | 5 holdings with quantity > 0; today's Demo snapshot recomputed to $38,703.95. |
| F-202 — `?days=N` ignored | iter-2 | CRITICAL | (new) | **FIXED** | `?days=7` → 6 points; `?days=30` → 21; `?days=365` → 252; omitted → 252 (full). |
| F-203 — prices_stale on all-zero portfolio | iter-2 | MAJOR | (new) | **FIXED** | Test (no holdings) → `prices_stale: false`. Demo (mixed) → `prices_stale: true` due to F-301 unrelated regression. |
| F-204 — snapshot table out of sync | iter-2 | CRITICAL | (new) | **FIXED** | Today's Demo snapshot recomputed after seed restore; matches holdings. |
| F-205 — transactions ticker null | iter-2 | MAJOR | (new) | **FIXED** | `GET /v1/portfolios/{id}/transactions` returns `ticker: "TLT"` etc. directly from server. |
| F-206 — POST add-member missing resolution | iter-2 | MINOR | (new) | **FIXED** | POST returns `{ticker, name, instrument_id, resolution: "resolved"}`. |
| F-208 — all-zero rows render | iter-2 | MAJOR | (new) | **PARTIAL** | All-zero empty state correctly fires when every row is zero. Mixed portfolios still render zero-qty noise rows — see F-303. |
| F-209 — Sharpe -3.4 on root | iter-2 | CRITICAL | (new) | **NOT FIXED** | Root still shows `drawdown_max=-1.0, sharpe=-3.8`, `data_quality.status="benchmark_unavailable"`. Anomaly detection too narrow — see F-302. |
| F-210 — empty-portfolio flat zero curve | iter-2 | MAJOR | (new) | **FIXED (frontend)** | `allZeroValues` guard at `EquityCurveChart.tsx:258`; renders "Open a position to see your equity curve" on Test. |
| F-211 — risk strip a11y | iter-2 | MINOR | (new) | **FIXED** | `role="group" aria-label="Risk metrics"` + per-tile `aria-label`. |
| F-212 — 1W removed | iter-2 | MINOR | (new) | **FIXED** | `PERIODS = [1W, 1M, 3M, 6M, 1Y, All]`. |

**Summary**: 26 FIXED ∙ 3 PARTIAL ∙ 2 NOT FIXED (F-003 deferred, F-209 incomplete) ∙ 1 informational ∙ 2 REGRESSED (F-007 / F-016 via F-301).

---

## NEW iteration 3 findings

### F-301 — Portfolio price client reads `quote["price"]` but market-data returns `last`/`bid`/`ask` (no `price` key)

- **Severity**: BLOCKING
- **Layer**: backend-correctness / contract-mismatch
- **Where**: `services/portfolio/src/portfolio/infrastructure/market_data/current_price_client.py:138`
- **What**: After iter-1 closed F-007 by adding internal-JWT auth, the portfolio service successfully reaches `http://market-data:8003/api/v1/quotes/batch` with `200 OK`. But the response shape is `{"quotes": {"<uuid>": {"bid": "...", "ask": "...", "last": "...", "volume": ..., "timestamp": "..."}}}` — there is **no `price` key**. The current code calls `quote.get("price")`, which returns `None` for every entry, so the dict is filtered out and `prices` ends up empty. Every holding falls back to `average_cost` and `prices_stale` flips True. The exposure card silently shows cost basis labelled as live `invested`, with `gross_exposure_pct = 1.0` and `leverage = 1.0` — F-016's exact failure mode resurrected.
- **Evidence**:
  ```
  $ docker compose exec portfolio python -c "..."
  body: {"quotes":{"01900000-0000-7000-8000-000000001001":{"bid":"267.61","ask":"267.61","last":"267.61", ...}}}
                                                        ^^^^                          ^^^^^^^^^^^^^^^^^^^^
                                                        no "price" key
  ```
  ```
  GET /v1/portfolios/{demo}/exposure
  → {"invested":"32451.00", "prices_stale":true, "gross_exposure_pct":"1.0"}
  Demo's actual market value (sum qty*last) ≈ $45,640.
  ```
- **Suggested fix**: In `current_price_client.py:138`, read `quote.get("last") or quote.get("price")`. The `last` field is the canonical "most recent traded price" in the S3 schema. Alternatively, the gateway-shape that the F-007 commit referenced (with `price`) does exist on the S9 proxy (`_map_price_snapshot_to_quote`) but the portfolio service goes direct to S3, bypassing the gateway transformation. Two options:
  1. Switch the portfolio service to call S9's `/v1/quotes/batch` instead of S3 directly (more layers but consistent shape).
  2. Add a `last` lookup as the primary source with `price` as a fallback.
- **Auto-fixable**: YES — one-line `quote.get("price") or quote.get("last")` change.

### F-302 — Risk-metrics anomaly detection only catches trailing zeros; intermediate zeros produce -100% drawdown with `benchmark_unavailable` status

- **Severity**: CRITICAL
- **Layer**: api / data-integrity (downstream of legacy F-201 contamination)
- **Where**: `services/api-gateway/src/api_gateway/routes/risk_metrics.py:564`
- **What**: F-209's anomaly check is `len(portfolio_values) >= 2 and portfolio_values[-1] == 0.0 and portfolio_values[-2] > 0.0`. Root portfolio's snapshot series contains an intermediate $0 (Apr 24, between $28k Apr 23 and $40k Apr 27) due to the F-201 wipe writing a single-day zero before being repaired. The series ends at $38k (non-zero), so the anomaly check doesn't fire. But the math still computes:
  ```
  drawdown_max  = -1.0  (from $40k → $0 inside the window)
  sharpe        = -3.8
  sortino       = -3.1
  data_quality.status = "benchmark_unavailable"  ← misleading; the SPY series isn't the issue
  ```
  The frontend shows the strip dimmed to 60% with the caption "Beta vs SPY is unavailable while the benchmark series is being ingested." — but every other tile renders the catastrophic-loss numbers as if real, with no caption explaining the data anomaly.
- **Evidence**:
  ```
  GET /v1/portfolios/{root}/risk-metrics
  → {"drawdown_max":-1.0, "sharpe":-3.8, "data_quality":{"status":"benchmark_unavailable"}}
  ```
  ```
  SELECT snapshot_date, total_value FROM portfolio_value_snapshots
  WHERE portfolio_id = '{root}' AND snapshot_date BETWEEN '2026-04-23' AND '2026-04-28'
  → 04-23: 28661, 04-24: 0, 04-27: 342618, 04-28: 38703  ← contaminated history
  ```
- **Suggested fix**: Detect any zero value in the daily series, not just the trailing one:
  ```python
  has_zero_value = any(v == 0.0 for v in portfolio_values)
  has_extreme_drop = any(
      abs((portfolio_values[i] - portfolio_values[i-1]) / max(portfolio_values[i-1], 1e-9)) > 0.5
      for i in range(1, len(portfolio_values))
  )
  if has_zero_value or has_extreme_drop:
      data_quality_status = "data_anomaly_detected"
      # null all metrics
  ```
  Plus: the seed pipeline should re-write contaminated snapshots after a holdings-restoration repair (i.e., when iter-2's reseed wrote new holdings, it should also have rewritten the snapshots for the pre-wipe dates).
- **Auto-fixable**: YES (logic fix); medium effort to also rewrite contaminated history.

### F-303 — SemanticHoldingsTable renders zero-quantity orphan rows alongside active positions

- **Severity**: MAJOR
- **Layer**: frontend-ux
- **Where**: `apps/worldview-web/components/portfolio/SemanticHoldingsTable.tsx:144-159`
- **What**: F-208 added an "all-zero" empty state guarded by `holdings.every(h => Number(h.quantity) === 0)`. On the Demo portfolio, **5 of 17 holdings have quantity > 0** — the rest are zero-quantity orphans left over from the F-201 wipe. The empty-state check fails (`every` requires all-zero), so the table renders 17 rows including 12 noise rows showing "0 shares, $0 avg, $0 value, +0.00% / -0.00%, weight 0.00%, sector —". Every column is meaningless; the user has to mentally filter the real positions out of a sea of zeros. A pro user reads "AAPL 0×$0=$0 / TSLA 0×$0=$0 / ..." as a system bug, not stale data.
- **Evidence**:
  ```
  GET /v1/holdings/{demo}
  → {"items":[{ticker:"AAPL", quantity:50, ...}, {ticker:null, quantity:0, ...}, ... 16 more rows]}
  ```
- **Suggested fix**: Filter zero-quantity holdings client-side before rendering OR add a "Show inactive positions" toggle that defaults to off. Server-side, the holdings endpoint could accept `?active_only=true` (default true) — pro traders sometimes want to see history of fully-sold positions, so pure deletion isn't right.
- **Auto-fixable**: YES (one-line filter or a toggle).

### F-304 — Watchlist seed data uses `instrument_id` UUIDs in the `entity_id` column; backfill script can't resolve them

- **Severity**: MAJOR
- **Layer**: seed-data / data-integrity
- **Where**: seed pipeline (likely `services/portfolio/src/portfolio/infrastructure/db/seed.py` or migration init)
- **What**: 11/14 watchlist rows have `entity_id` values like `01900000-0000-7000-8000-000000001001` — these are **`instruments.id`** UUIDs, not entity UUIDs. The actual entity_id for AAPL is `11111111-0001-7000-8000-000000000001` (different tree). The backfill script (`backfill_watchlist_member_denorm.py`) correctly joins `instruments.entity_id`, which never matches. Result: every QA reviewer sees a watchlist with mostly "—" tickers. The frontend now politely renders "resolving…" badges (F-010 fix), but the badge will be there forever because nothing will ever resolve.
- **Evidence**:
  ```sql
  SELECT entity_id, ticker FROM watchlist_members WHERE ticker IS NULL LIMIT 3;
  → 01900000-0000-7000-8000-000000001001 / NULL  ← AAPL's instrument_id, not entity_id
    01900000-0000-7000-8000-000000001004 / NULL  ← TSLA's instrument_id
    01900000-0000-7000-8000-000000001005 / NULL  ← AMZN's instrument_id

  SELECT id, symbol, entity_id FROM instruments WHERE id = '01900000-0000-7000-8000-000000001001';
  → AAPL / 11111111-0001-7000-8000-000000000001  ← real entity_id
  ```
- **Suggested fix**: Either (a) fix the seed to use the right entity_id, OR (b) extend the backfill script to also try `JOIN instruments ON instruments.id = watchlist_members.entity_id` as a secondary lookup (with logging to flag the mismatch). Option (a) is the right long-term fix.
- **Auto-fixable**: YES.

### F-305 — Demo equity curve shows -88% cliff between Apr 27 and Apr 28 due to iter-2 reseed

- **Severity**: MINOR (cosmetic; self-heals after a few days)
- **Layer**: data-history
- **Where**: `portfolio_value_snapshots` for Demo
- **What**: Today's snapshot is $38,703 (5 active holdings × current prices). Yesterday's snapshot is $342,618 (17 holdings × prices, written before the F-201 wipe and not rewritten). The chart renders a near-vertical drop on the most recent bar — visually alarming, even though it's an artifact of how the iter-2 reseed worked (only today's snapshot was recomputed, not yesterday's). A new user opening the page first thing would assume real catastrophic loss.
- **Evidence**:
  ```
  Apr 23: 28,661   Apr 24: 0     Apr 27: 342,618   Apr 28: 38,703
                   ^anomaly      ^pre-wipe         ^post-restore
  ```
- **Suggested fix**: When the seed restoration runs (or any holdings-mutation that affects historical totals), rewrite all affected snapshot dates by recomputing total_value as `Σ qty × historical_price` for the new holding set. Or: add an "exclude pre-restoration history" data flag and start the chart at Apr 28 when corruption is detected. Or: mark snapshots as `is_seed_baseline=true` when generated by seed and warn / exclude them from analytics.
- **Auto-fixable**: PARTIAL (requires a backfill rewrite).

---

## Plan Acceptance Criterion Audit (delta vs iter-2)

| Wave | Criterion | iter-2 | iter-3 | Note |
|------|-----------|--------|--------|------|
| W1 T-46-1-01 | DIV row shows correct cash amount post-resync | ❌ | ❌ | sandbox 0 activities — DEFERRED |
| W1 T-46-1-03 | Holdings.qty = SnapTrade qty after sync | REGRESSED | ✅ | F-201 fixed by reseed; 5 active positions |
| W1 T-46-1-04 | Repair script idempotent + dry-run | ✅ | ✅ | dups still present (F-004 PARTIAL) |
| W1 Validation manual | Holdings match TastyTrade exactly | ❌ | ❌ | seed-data, not broker |
| W1 Validation manual | Dividend rows show non-zero amounts | ❌ | ❌ | shows "$0.00" |
| W2 T-46-2-01 | Watchlist rows backfilled by script | ✅ ran | ✅ ran (3/14 resolved due to F-304) | seed bug |
| W3 T-46-3-02 | Cannot DELETE root | ✅ | ✅ | 400 returned with details |
| W3 T-46-3-04 | Delete button disabled for root | ✅ | ✅ | tooltip + opacity |
| W4 T-46-4-04 | Backfill writes 252 rows in <2 min | ✅ | ✅ | 252 Demo |
| W4 Validation manual | Rows in portfolio_value_snapshots | ✅ | ✅ | 342 |
| W5 T-46-5-04 | Chart renders with real data | ✅ Demo, ⚠️ Test | ✅ Demo, ✅ Test (empty state) | F-210 fixed |

Net: **19/25 ✅** vs iter-2's 18/25.

---

## Container log scrub (iter-3)

```
portfolio                — clean except `default_db_credentials_detected` (dev-only)
api-gateway              — clean except OIDC discovery skipped (expected for dev)
portfolio-snapshot-worker — startup catch-up complete; sleeping until 21:30 UTC
worldview-web             — clean
0/59 containers unhealthy
```

No new error / 500 / unhandled exception lines. The legacy `current_price_unexpected_status: 401` is permanently gone.

---

## Required Actions Before Sign-Off

In priority order:

1. **F-301 — fix `current_price_client` to read `last`** (one-line patch). Without this, every exposure number on every portfolio is silently cost-basis. This is the single most user-impactful issue.
2. **F-302 — broaden anomaly detection** to catch intermediate zeros and large drops, not just trailing zeros. Or rewrite contaminated snapshot history when seed restoration runs.
3. **F-303 — filter zero-quantity holdings client-side** (or add `?active_only` server filter, default true). 12 noise rows on Demo today.
4. **F-304 — fix the watchlist seed data** to use real `entity_id` UUIDs, then rerun the backfill. Closes F-005 fully.
5. **F-305 — rewrite contaminated snapshots after seed restore** OR document the cliff as known-self-healing.
6. **Carry-over**: F-003 (DIV amount — DEFERRED until brokerage SDK upgrade), F-004 (dedup script — present but not auto-run).

The first two (F-301, F-302) are **blocking for sign-off**. F-303 / F-304 / F-305 should ship together as a cleanup wave but are not blocking if F-301 / F-302 land.

---

## Verdict

**FAIL** — 1 BLOCKING (F-301) + 1 CRITICAL (F-302) new findings.

**Recommended path**: PLAN-0046.3 — surgical correctness wave. The five new findings are all 1–4 hour fixes; the whole cleanup fits in a single working day. F-301 and F-302 alone should be cut as a 2-hour hot-fix because they degrade the headline numbers (exposure, risk metrics) on every existing user's main view.

Despite the FAIL verdict, this iteration represents real progress: 26 of 35 findings across all three audits are now FIXED, the live stack is healthy, all 418 frontend tests pass, and the user-facing surfaces (equity curve, risk strip, holdings table empty states, watchlist resolving badges, scope hints) are now genuinely finance-grade in their handling of edge cases. The remaining gaps are concentrated in two specific code paths (price client response shape; risk-metrics anomaly heuristic) plus seed-data hygiene.
