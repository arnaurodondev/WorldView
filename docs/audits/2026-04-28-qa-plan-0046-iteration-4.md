# QA Audit — PLAN-0046 Portfolio Correctness & Analytics, Iteration 4

**Date**: 2026-04-28
**Auditor**: QA Lead (strict gate, iteration 4)
**Branch**: `feat/content-ingestion-wave-a1`
**HEAD commit**: `5421391` (fix(portfolio/PLAN-0046): address 5 iteration-3 QA findings)
**Stack**: 59 containers, 0 unhealthy
**Live state**:
- portfolio_db: 4 portfolios (Demo, Test, Test2, All Accounts/root); 17 holdings (5 active, 12 zero-quantity orphans on Demo)
- watchlist_members: 15 total — `with_ticker = 9`, `null_ticker = 6` (4 of which have a matching instrument in `market_data_db.instruments` but not in `portfolio_db.instruments` — the local cache is stale)
- portfolio_value_snapshots: Demo today $38,703.95 vs live exposure $45,110.95 — a **$6,407.00 silent undercount** caused by missing OHLCV bar for instrument 1005 (see F-401)
- API latency: all touched endpoints <50 ms

---

## Executive Verdict

**FAIL** — 1 BLOCKING / 1 CRITICAL / 1 MAJOR / 1 MINOR new findings (F-401..F-404). Every iter-3 finding (F-301..F-305) is verified FIXED in the live stack, and every iter-2 carry-over (F-007/F-016, F-209, F-208 mixed-portfolio sub-issue) is closed. The new findings are deeper data-integrity issues exposed only after the surface-level bugs were fixed.

The iter-3 fix-agent landed solid, well-commented engineering: `current_price_client.py` reads `last`→mid→`price` with structured warnings on contract regression, `risk_metrics.py` flags any `min(values)==0 AND max(values)>0` as `data_anomaly_detected` with `details.zero_indices`, `holding.py` accepts `?include_closed=true` and filters at the application layer, the watchlist backfill uses dual-key resolution and the seed now sets `instruments.entity_id = id` so both join keys resolve. The 575 + 231 + 418 tests pass. **However**, three deeper issues now dominate the user-visible numbers:

1. **F-401 (BLOCKING)**: Today's Demo snapshot ($38,703.95) silently drops instrument 1005 from the total because no OHLCV bar exists for 2026-04-28 yet. Live exposure (uses quotes) reports $45,110.95. The 14% difference is invisible to the user — chart shows "real" loss, exposure card shows different number, and there's no UI signal that one input was missing. This same logic ships with the daily snapshot worker, so every weekend / pre-close / illiquid name will silently undercount.
2. **F-402 (MAJOR)**: portfolio_db's local instruments cache contains only 5 of the 10 seeded symbols (1001-1005). The 4 unresolvable watchlist rows (NVDA-1006, META-1007, NFLX-1009, DIS-1010) are present in market_data_db.instruments but never reached portfolio_db. The market.instrument event consumer is either not subscribed or has no events to consume on this seed.
3. **F-403 (CRITICAL)**: portfolio_db.instruments:1003 = NVDA, but market_data_db.instruments:1003 = GOOGL. The same UUID maps to **different tickers** across the two databases. A user holding NVDA in Demo silently has GOOGL's prices applied to their P&L. Quote, OHLCV, fundamentals, news enrichment — every market-data lookup for that holding pulls the wrong ticker. This is structural seed corruption checked into `scripts/seed-dev-data.sql`.
4. **F-404 (MINOR)**: Tech and EV watchlists each have AAPL listed twice — once as entity_id `01900000-0000-7000-8000-000000001001` (instruments-id seed shape) and once as `11111111-0001-7000-8000-000000000001` (KG entity shape). No unique constraint on (watchlist_id, ticker_resolved) means dedup must happen client-side or via a new index.

The iter-3 acceptance criteria are 19/25 ✅ (unchanged), but the **three new structural issues** make the platform misrepresent prices to the user even with all surface bugs fixed. F-401 alone (the snapshot-vs-exposure desync) is the new headline blocker.

---

## Iter-3 finding regression status (F-301..F-305)

| ID | Severity (orig) | iter-3 verdict | Live evidence (iter-4) |
|----|---|---|---|
| F-301 — current_price_client read non-existent `quote["price"]` | BLOCKING | **FIXED** | `GET /v1/portfolios/{demo}/exposure` → `{invested: 45110.95, prices_stale: false}`. Code reads `last → mid → price` with structured warning on shape regression. |
| F-302 — risk anomaly detection only checked trailing zero | CRITICAL | **FIXED** | `GET /v1/portfolios/{root}/risk-metrics` → `data_quality.status="data_anomaly_detected", details.zero_indices=[27], total_points=30`. Demo same status with all 61 zero indices listed (downstream of F-305 history). |
| F-303 — zero-qty rows rendered alongside active | MAJOR | **FIXED** | `GET /v1/holdings/{demo}` → `total=5` (active only). `?include_closed=true` → `total=17`. Server-side filter via `GetHoldingsUseCase.execute(include_closed=False)` default. |
| F-304 — watchlist seed used wrong key | MAJOR | **FIXED (improved)** | `with_ticker=9 / total=15` (was 3/14). Backfill now uses dual-key OR predicate. Residual 6 rows are a seed-cache mismatch — see F-402. |
| F-305 — Demo snapshot cliff Apr 27 → Apr 28 | MINOR | **PARTIAL (acknowledged)** | Cliff still in the data ($297k → $38k). Tooling exists (`backfill_portfolio_value_snapshots.py`) to repair after seed restoration but was not run. As iter-3 noted, this self-heals after a few days. Operational doc says how to run the backfill. |

**Iter-2 carry-over status (F-007 / F-016 / F-209)**: All three CLOSED. F-007/F-016 (cost-basis fallback) closed via F-301. F-209 (Sharpe -3.4 on root) closed via F-302.

---

## NEW iteration 4 findings

### F-401 — Snapshot worker silently undercounts portfolio value when OHLCV bar is missing for any holding

- **Severity**: BLOCKING
- **Layer**: backend-correctness / data-quality
- **Where**: `services/portfolio/src/portfolio/application/use_cases/compute_portfolio_value.py:102-108`
- **What**: `ComputePortfolioValueUseCase.execute()` iterates holdings; when `price_client.get_close_on_date()` returns None for a holding's `instrument_id × as_of_date`, it appends to `missing_prices`, **continues the loop without contributing anything to `total_value`**, and logs a warning. The persisted snapshot then has `total_value = sum(qty × close) over only the holdings where a bar existed`. There is no field on `PortfolioValueSnapshot` to record "snapshot was computed from N of M holdings" — the user sees a single `total_value` that may silently undercount by any amount.
- **Live evidence** (Demo, today):
  ```
  Snapshot 2026-04-28 total_value = $38,703.95
  Live exposure  (qty × last quote) = $45,110.95
  Delta                              = $6,407.00 (14% undercount)

  Cause: instrument 1005 (AMZN, 25 shares) has no ohlcv_bars row for 2026-04-28
         — last bar is 2026-04-27 close=261.76. Worker logged
         "portfolio_snapshot_missing_prices missing_count=7" (1 active +
         6 zero-qty orphans), but 6 of those are zero-qty so harmless;
         the 1 active orphan = AMZN = $6,528 of silently-dropped value.
  ```
- **Why this is BLOCKING**: the snapshot is the canonical history layer used by
  - the equity-curve chart (renders the cliff visually),
  - the risk-metrics computation (returns become noise — already triggers F-302's anomaly path on Demo),
  - the time-series for any future PnL ribbon, allocation drift report, or backtest.

  Every consumer downstream of the snapshot table is lying to the user. The exposure card uses live quotes so it's correct, but the chart + risk strip + history all silently disagree. With more illiquid holdings or pre-close runs (currently scheduled at 21:30 UTC ≈ market close, but holidays / OTC tickers / pre-IPO ETFs will routinely lack a close-date bar), the undercount can be arbitrary.
- **Suggested fixes** (pick one):
  1. **Last-known-price fallback** (preferred): when `get_close_on_date(date_T)` returns None, retry `get_close_on_date(date_T-1)`, then T-2, … up to N=5 days. Mark the snapshot as `priced_from_stale=true` if any holding used a fallback. The total_value is then "best available" not "missing".
  2. **Quote fallback**: when no OHLCV bar, pull current quote (we already authenticate to S3 from the snapshot worker for OHLCV — same auth works). Same `priced_from_stale=true` flag.
  3. **Reject + retry** (most conservative): if any active-quantity holding has missing price, skip the snapshot entirely for that day — the next run inherits the gap and tries again. This avoids lying about totals at the cost of equity-curve gaps.
  4. **Surface the gap**: keep current behaviour but add `total_value_completeness = priced_holdings / total_holdings` to the snapshot row + propagate to the equity-curve and risk-metrics responses so the UI can render "9/10 priced" caveats.
- **Auto-fixable**: YES. Recommend (1) + (4) together.

### F-402 — portfolio_db's instruments cache is missing 4 of 10 seeded symbols (NVDA-1006, META, NFLX, DIS) leaving watchlist rows permanently unresolvable

- **Severity**: MAJOR
- **Layer**: seed-data / event-consumer
- **Where**: `scripts/seed-dev-data.sh:11-105` (portfolio_db section); `portfolio_instrument_consumer` (event subscriber)
- **What**: 6 of the 15 watchlist rows still have `ticker IS NULL` after the iter-3 backfill. 4 of those entity_ids (1006, 1007, 1009, 1010) exist in market_data_db.instruments (NVDA, META, NFLX, DIS respectively) but **not in portfolio_db.instruments** (which has only 1001-1005). The local cache is populated by the `market.instrument.created` Kafka consumer — but the seed script doesn't emit those events, and the watchlist backfill can only see what's in the local cache. The 6 "—" rows in the UI ("resolving…" badge will be there forever) are the symptom.
- **Live evidence**:
  ```
  $ docker exec ... psql portfolio_db -c "SELECT count(*) FROM instruments;"
  → 62

  $ docker exec ... psql market_data_db -c "SELECT id,symbol FROM instruments WHERE id LIKE '01900000-0000-7000-8000-00000000100%';"
  → 1001 AAPL, 1002 MSFT, 1003 GOOGL, 1004 TSLA, 1005 AMZN,
    1006 NVDA, 1007 META, 1008 JPM, 1009 NFLX, 1010 DIS

  $ docker exec ... psql portfolio_db -c "SELECT id,symbol FROM instruments WHERE id LIKE '01900000-0000-7000-8000-00000000100%';"
  → 1001 AAPL, 1002 MSFT, 1003 NVDA, 1004 TSLA, 1005 AMZN
  ```
- **Suggested fix**: extend `scripts/seed-dev-data.sh` portfolio_db section to insert the same 10 instruments that go into market_data_db.instruments. The two cache layers must be consistent (or, ideally, the portfolio service should subscribe to `market.instrument.*` and let real-time replication populate the cache from market-data — but for dev that's overkill).
- **Auto-fixable**: YES (one INSERT block).

### F-403 — Cross-database instrument seed corruption: same UUID maps to DIFFERENT tickers in portfolio_db vs market_data_db

- **Severity**: CRITICAL
- **Layer**: seed-data / multi-tenant integrity
- **Where**: `scripts/seed-dev-data.sql:46` vs `scripts/seed-dev-data.sql:82`
- **What**: ID `01900000-0000-7000-8000-000000001003` is seeded as **NVDA** in `portfolio_db.instruments` but as **GOOGL** in `market_data_db.instruments`. A user holding NVDA in Demo (`holdings.instrument_id = 1003`) sees the symbol "NVDA" on the UI (resolved from portfolio_db) but every market-data lookup uses the same UUID and returns GOOGL's price/OHLCV/fundamentals/news.
- **Live evidence**:
  ```
  $ curl /v1/holdings/{demo} | jq '.items[2]'
  → {ticker: "NVDA", instrument_id: "01900000-0000-7000-8000-000000001003", quantity: 20, avg_cost: 141.20}

  $ curl -X POST /v1/quotes/batch -d '{"instrument_ids": ["01900000-0000-7000-8000-000000001003"]}'
  → {"quotes":{"...1003":{"ticker":"GOOGL", "price":347.74, ...}}}  ← reports GOOGL!
  ```
  Demo NVDA position: 20 shares × cost $141.20 = $2,824 invested. With GOOGL price $347.74 the system reports $6,955 mark-to-market and a **+146% unrealized gain** that doesn't exist. Real NVDA (id 1006) closed today at $399.13 (or whatever) — never queried for this holding.
- **Why CRITICAL**: every analytics surface for this holding is wrong:
  - Exposure card includes GOOGL price.
  - Equity curve uses GOOGL OHLCV.
  - Risk-metrics return distribution mixes in GOOGL.
  - News widget surfaces GOOGL articles under "NVDA holding news".
  - AI insights / morning brief reference the wrong stock.
  - Dashboard top-movers / portfolio gainers identify a "winner" from data that doesn't match the position.
- **Suggested fix**: align the seed. Either change portfolio_db's row to GOOGL (and update Demo's holding accordingly), or change market_data_db's row to NVDA and update OHLCV/quote backfill scripts. The convention should be: **the same UUID always means the same security, in every database**. Production already enforces this implicitly (events flow id+symbol together) — the seed needs the same property.
- **Auto-fixable**: YES (one-line edit + reseed).

### F-404 — Watchlist members have AAPL duplicated in 2 watchlists (no unique constraint on resolved-ticker per watchlist)

- **Severity**: MINOR
- **Layer**: data-model / seed-data
- **Where**: `scripts/seed-dev-data.sql` watchlist_members inserts (one with `entity_id=1001`, another later with `entity_id=11111111-0001-...`)
- **What**: Tech Watchlist and EV Watchlist each contain AAPL twice — once via the seed-style entity_id `01900000-0000-7000-8000-000000001001` and once via the KG-style entity_id `11111111-0001-7000-8000-000000000001`. Both resolve to the same `instrument_id=1001` and therefore the same `ticker="AAPL"`, so the user sees "AAPL — Apple Inc." twice on the panel.
- **Live evidence**:
  ```sql
  SELECT watchlist_id, ticker, count(*) FROM watchlist_members
  WHERE ticker IS NOT NULL GROUP BY 1,2 HAVING count(*) > 1;
  → 01900000-...000200 / AAPL / 2
    01900000-...000201 / AAPL / 2
  ```
- **Suggested fix**:
  1. Add a partial unique index `CREATE UNIQUE INDEX … ON watchlist_members (watchlist_id, instrument_id) WHERE instrument_id IS NOT NULL;` once F-402 lets `instrument_id` be populated everywhere.
  2. De-dup at write time in the watchlist-add use case (reject if an existing member resolves to the same instrument).
  3. De-dup at read time on `GET /v1/watchlists/{id}/members`.
- **Auto-fixable**: YES (any of the three options).

---

## Plan Acceptance Criterion Audit (delta vs iter-3)

| Wave | Criterion | iter-3 | iter-4 | Note |
|------|-----------|--------|--------|------|
| W1 T-46-1-01 | DIV row shows correct cash amount post-resync | ❌ | ❌ | sandbox 0 activities — DEFERRED |
| W1 T-46-1-03 | Holdings.qty = SnapTrade qty after sync | ✅ | ✅ | 5 active positions |
| W1 T-46-1-04 | Repair script idempotent + dry-run | ✅ | ✅ | Still 46 dup tx groups (script doesn't auto-dedup tx) |
| W1 Validation manual | Holdings match TastyTrade exactly | ❌ | ❌ | seed-data, not broker |
| W1 Validation manual | Dividend rows show non-zero amounts | ❌ | ❌ | shows "$0.00" |
| W2 T-46-2-01 | Watchlist rows backfilled by script | ✅ (3/14) | ✅ (9/15 — IMPROVED) | residuals are F-402 |
| W3 T-46-3-02 | Cannot DELETE root | ✅ | ✅ | 400 with details |
| W3 T-46-3-04 | Delete button disabled for root | ✅ | ✅ | tooltip + opacity |
| W4 T-46-4-04 | Backfill writes 252 rows in <2 min | ✅ | ✅ | 252 Demo |
| W4 Validation manual | Rows in portfolio_value_snapshots | ✅ | ✅ | 342 |
| W4 hidden | Snapshot total_value matches qty × close | — | ❌ NEW | F-401: $38,703 vs $45,110 actual (-14%) |
| W5 T-46-5-04 | Chart renders with real data | ✅ Demo+Test | ✅ | (renders the cliff & undercount) |

Net: **19/25 ✅** — same as iter-3, but with a new failure mode (F-401's snapshot underflow) that wasn't visible until F-301 made the live exposure honest.

---

## Container log scrub (iter-4)

```
portfolio                 — clean except `default_db_credentials_detected` (dev-only)
api-gateway               — clean except OIDC discovery skipped (expected for dev)
portfolio-snapshot-worker — single warning per portfolio per day:
                              portfolio_snapshot_missing_prices
                              missing_count=7  (Demo: 1 active + 6 zero-qty orphans)
                              instrument_ids_sample=[1005, 6 random uuids]
                            ↑ this warning IS the F-401 signal but the snapshot
                              was still persisted with the undercounted total.
worldview-web             — clean
0 / 59 unhealthy
```

The new structured warning `current_price_all_quotes_missing_price` from F-301's defensive logging never fires (good — the fix is correct). The `portfolio_snapshot_missing_prices` warning fires once per portfolio per day and is the canary for F-401 — actionable signal, but ignored by the persistence layer.

---

## Required Actions Before Sign-Off

In priority order:

1. **F-403 (CRITICAL) — fix the cross-DB UUID/symbol mismatch on `01900000-0000-7000-8000-000000001003`**. Pick a side and align both seed inserts. Without this, Demo's "NVDA" holding silently quotes GOOGL on every refresh.
2. **F-401 (BLOCKING) — fix the snapshot worker to either (a) fall back to last-known close, (b) fall back to current quote, or (c) surface a `total_value_completeness` field on the snapshot row + carry it through equity-curve + risk-metrics responses**. Without this, the equity-curve and risk-metrics keep silently disagreeing with the exposure card.
3. **F-402 (MAJOR) — extend `scripts/seed-dev-data.sh` to insert all 10 instruments into portfolio_db.instruments**. Closes the 4 unresolvable watchlist rows (NVDA-1006, META, NFLX, DIS).
4. **F-404 (MINOR) — de-dup watchlist seed AAPL** + add `(watchlist_id, instrument_id) WHERE instrument_id IS NOT NULL` partial-unique index for forward-protection.
5. **Carry-over**: F-003 (DIV amount — DEFERRED), F-004 (transaction dedup — script present but not auto-run), F-305 (Demo cliff — self-heals; backfill script available).

F-401 + F-403 are blocking for sign-off. F-402 + F-404 should ship in the same wave but are not blocking.

---

## Verdict

**FAIL** — 1 BLOCKING (F-401) + 1 CRITICAL (F-403) new findings.

**Recommended path**: PLAN-0046.4 — data-integrity wave. F-401 needs a 2-3 hour fix (price fallback + completeness flag); F-403 is a 5-minute seed edit + reseed. F-402 + F-404 ride along as cleanup. Plan to land all four together so the next iter sees a clean Demo with: $45,110.95 exposure = $45,110.95 today's snapshot, 9 watchlist rows resolved, no AAPL duplicates, NVDA quotes for the NVDA holding.

Despite the FAIL verdict, this iteration represents real progress on user-facing surfaces: 31 of 35 prior findings are now FIXED, the live exposure card is finally honest about the user's actual market value, the risk strip caption reads `data_anomaly_detected` with the offending indices, the holdings table shows only active positions by default, and watchlist resolution improved from 3/14 to 9/15. The remaining gaps have moved from API-shape and UI-rendering issues into the **data layer** — specifically, seed-data hygiene and the snapshot pipeline's handling of missing inputs. That's the right direction; one more wave should close the file.
