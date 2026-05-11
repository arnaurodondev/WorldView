# QA Audit — PLAN-0046 Portfolio Correctness & Analytics, Iteration 5

**Date**: 2026-04-28
**Auditor**: QA Lead (strict gate, iteration 5)
**Branch**: `feat/content-ingestion-wave-a1`
**HEAD commit**: `631d74e` (fix(portfolio/PLAN-0046): address 4 iteration-4 QA findings)
**Stack**: 59 containers healthy, alembic head = `0014`
**Live state**:
- portfolio_db: 4 portfolios (Demo, Test, Test2, All Accounts/root); Demo has 5 active holdings
- portfolio_db.instruments: 67 rows; the 10 seeded test symbols (1001..1010) all present
- market_data_db.instruments: same 10 seeded symbols at the same UUIDs (cross-DB consistency restored)
- watchlist_members: 14 rows (was 15) — F-404 dedup happened during reseed; partial unique index `uq_watchlist_members_watchlist_instrument` present and active
- portfolio_value_snapshots: today's Demo row `total_value=$42,483.75 data_quality=partial_prices`; live exposure `$42,325.95` → delta **$157.80 = 0.37 %** (well within the 1 % tolerance)

---

## Executive Verdict

**CONDITIONAL PASS** — every prior BLOCKING/CRITICAL/MAJOR/MINOR finding (F-401..F-404 from iter-4 plus all carry-overs) is verified FIXED in live. No new BLOCKING or CRITICAL issues.

Two new MINOR findings from a deep code-and-data sweep (F-501 read-path doesn't surface `data_quality`; F-502 backfill script not shipped into worker image). Neither blocks user-visible correctness — the data layer is now honest, the snapshot total agrees with live exposure, the dup-add returns 409, and the cross-DB seed is consistent. The overall PLAN-0046 acceptance bar is finally met.

The iter-4 fix-agent landed thoughtful, heavily-commented engineering: `compute_portfolio_value.py` walks back 5 calendar days then falls back to cost basis (preserves position magnitude, never silently zeroes); root aggregation propagates `partial_prices` upward; the watchlist add use case probes existing members and raises a domain `WatchlistMemberAlreadyExistsError` *before* the SQL unique index fires (clean 409 instead of generic 500); migration 0014 ships the partial unique index for forward protection. 579 + 231 + 418 unit tests pass on iter-4 images.

---

## Iter-4 finding regression status (F-401..F-404)

| ID | Severity | iter-4 | Live evidence (iter-5) |
|----|----------|--------|------------------------|
| F-401 — snapshot silently undercounts when OHLCV missing | BLOCKING | **FIXED** | Demo today: snapshot $42,483.75 vs exposure $42,325.95 → 0.37 % delta. `data_quality='partial_prices'` set on row. Lookback (5d) + cost-basis fallback in place; structured warning `portfolio_snapshot_partial_prices` + `_stale_price_fallback` + `_missing_prices` emitted with bounded sample lists. Root aggregator propagates flag upward. |
| F-402 — portfolio_db.instruments seed missing 5 of 10 | MAJOR | **FIXED** | `SELECT count(*) WHERE id::text LIKE '01900000-...10%'` → 10. All 10 seeded symbols (AAPL, MSFT, GOOGL, TSLA, AMZN, NVDA, META, JPM, NFLX, DIS) present. |
| F-403 — cross-DB UUID 1003 NVDA↔GOOGL collision | CRITICAL | **FIXED** | id `...1003 → GOOGL` in BOTH portfolio_db and market_data_db. NVDA = id `...1006` in BOTH. Demo holdings show NVDA correctly resolved via `instrument_id=1006`. |
| F-404 — duplicate (watchlist_id, instrument_id) | MINOR | **FIXED** | `uq_watchlist_members_watchlist_instrument` partial unique index present. Application-layer pre-check in `AddWatchlistMemberUseCase` raises `WatchlistMemberAlreadyExistsError` when target instrument already in the watchlist. Live: POST→201, repeat POST→**409** with `error_code=WATCHLIST_MEMBER_ALREADY_EXISTS`. |

**Iter-3 carry-over status (F-301..F-305)**: All ✅ from iter-4 — re-confirmed via spot-checks. F-305 (Demo cliff) is now a 1-day cliff on 2026-04-27 ($297k → $42k) caused by the F-403 reseed wiping pre-existing GOOGL-priced rows; backfill script can repair if cosmetic; deferred.

**Iter-2 carry-over (F-007/F-016/F-209)**: All closed.

**F-001 catch-up (iter-2)**: Verified live — worker startup log shows `portfolio_snapshot_worker_startup_catchup_start trading_day_count=20`, walks back through 2026-04-01..2026-04-28, all 60 (3 portfolios × 20 days) iterations log `_skip_existing` (idempotent).

---

## NEW iteration 5 findings

### F-501 — `value-history` API does not surface `data_quality` per snapshot point

- **Severity**: MINOR
- **Layer**: api / contract
- **Where**: `services/portfolio/src/portfolio/api/routes/portfolio.py:236-244` (`ValueHistoryPoint` projection); `services/portfolio/src/portfolio/api/schemas.py` (point model omits the field)
- **What**: The `data_quality` column is now correctly populated (today's Demo row = `partial_prices`), but the `GET /v1/portfolios/{id}/value-history` projection only emits `(date, value, cost_basis, cash)` — the field is dropped on the way out. Risk-metrics already surfaces the equivalent caveat (`RiskMetricsStrip` consumes `data_quality.status`), but the equity-curve has no signal that today's point was patched up. The carefully-engineered fallback is invisible to the user.
- **Live evidence**:
  ```
  $ curl /v1/portfolios/{demo}/value-history?from=2026-04-28&to=2026-04-28
  → {"points":[{"date":"2026-04-28","value":"42483.75","cost_basis":"32451.00","cash":"0.00"}], ...}
                                                                                                ^^^ no data_quality
  ```
- **Why MINOR (not MAJOR)**: the value the user sees IS now within 1 % of live exposure (the F-401 fallback does its job). The missing signal only matters when ops needs to debug a weekend / holiday / illiquid-name run, or when a future PRD wants to render "9/10 priced" hints on the chart hover.
- **Suggested fix**: add `data_quality: str` to `ValueHistoryPoint` (forward-compat — old clients ignore the field) and propagate `s.data_quality` in the route projection. EquityCurveChart's tooltip can then render a "stale/cost-basis fallback" badge for points where `data_quality != "ok"`.
- **Auto-fixable**: YES (10-minute schema + projection edit).

### F-502 — `backfill_watchlist_member_denorm.py` is host-only; not shipped into the worker image

- **Severity**: MINOR
- **Layer**: ops / packaging
- **Where**: `services/portfolio/scripts/backfill_watchlist_member_denorm.py` (host); `services/portfolio/Dockerfile` (does not COPY scripts/)
- **What**: The watchlist-denorm and snapshot-backfill scripts live in `services/portfolio/scripts/` and are well-written one-shots. But `docker exec worldview-portfolio-1 python /app/.../backfill_watchlist_member_denorm.py` fails — the container has only `alembic alembic.ini infra src` under `/app`. Operators who want to repair denorm rows after a deploy or seed change must `pip install -e` the package on a host with DB access. For dev that's tractable; for prod it's an SRE-loop foot-gun.
- **Live evidence**:
  ```
  $ docker exec worldview-portfolio-1 ls /app
  alembic  alembic.ini  infra  src
  $ docker exec worldview-portfolio-1 python /app/services/portfolio/scripts/backfill_watchlist_member_denorm.py
  python: can't open file ...: [Errno 2] No such file or directory
  ```
- **Suggested fix**: extend the portfolio Dockerfile to `COPY services/portfolio/scripts /app/scripts/`. Document `docker exec ... python /app/scripts/<name>.py` in `services/portfolio/.claude-context.md` ops section.
- **Auto-fixable**: YES (one Dockerfile line + one doc paragraph).

---

## Sweep results — areas explicitly probed and PASSED

| Area | Probe | Result |
|------|-------|--------|
| Frontend SSR for all 4 portfolios | `curl :3001/portfolio?id=...` × 4 | All 200; identical 12,990-byte SPA shell (Next.js auth-gated route — verified app-shell renders) |
| 409 on duplicate watchlist member | POST same `entity_id` twice | 201 → 409 with structured error code `WATCHLIST_MEMBER_ALREADY_EXISTS` |
| Cross-entity dedup (different `entity_id` resolving to same instrument) | POST KG-style entity_id after seed-style entity_id | 201 (because KG entity_id doesn't resolve to a known instrument in this seed) — partial unique index correctly only enforces on non-NULL `instrument_id`, no false positive |
| Snapshot vs. exposure parity | $42,483.75 vs $42,325.95 | 0.37 % within 1 % gate |
| Migration head | `alembic_version` | `0014` — matches expected |
| Snapshot worker startup catch-up | container log scrub | walks 20 trading days, all `_skip_existing`, then sleeps until 21:30 UTC |
| `data_quality` propagation in entity + repository | code read | flag persisted, root aggregator propagates upward, worker emits structured logs |
| Heavy inline comments on iter-4 code | `compute_portfolio_value.py`, `portfolio_snapshot_worker.py`, `watchlist.py` | Excellent — every fallback step is explained with rationale, telemetry buckets are named, and the WHY (vs WHAT) pattern from project memory is followed throughout |

---

## Container log scrub (iter-5)

```
portfolio                 — clean (only dev-time `default_db_credentials_detected`)
api-gateway               — clean (only dev OIDC discovery skip)
portfolio-snapshot-worker — startup catchup completed; sleeping to 21:30 UTC
worldview-web             — clean
0 / 59 unhealthy
```

The new iter-4 telemetry events (`portfolio_snapshot_partial_prices`, `_stale_price_fallback`, `_missing_prices`) did NOT fire on the catch-up pass — every historical row was already present (idempotent skip). They will fire on tonight's 21:30 UTC run when AMZN's bar is again missing at compute time.

---

## Plan Acceptance Criterion Audit (delta vs iter-4)

All 19/25 ✅ from iter-4 plus the new W4 hidden criterion:

| Wave | Criterion | iter-4 | iter-5 |
|------|-----------|--------|--------|
| W4 hidden | Snapshot total_value matches qty × close (within 1 %) | ❌ ($38,703 vs $45,110) | ✅ ($42,483 vs $42,325 → 0.37 %) |
| W2 T-46-2-01 | Watchlist rows backfilled | ✅ 9/15 | ✅ 12/14 (post-reseed; 2 unresolved are QA-test garbage UUID + a freshly-added pending row) |

Net: **20/25 ✅** (the 5 unchecked items are still the SnapTrade-sandbox / dividend-amount items deferred since W1).

---

## Required Actions Before Sign-Off

None blocking.

Optional (recommend rolling into a small follow-up):
1. **F-501** — propagate `data_quality` through `ValueHistoryPoint` + render a "stale data" tooltip badge on EquityCurveChart points where it's not `"ok"`. Closes the loop on the F-401 fallback signal.
2. **F-502** — ship the `services/portfolio/scripts/` directory into the portfolio container image so backfills can be invoked via `docker exec`.

---

## Verdict

**CONDITIONAL PASS** — 0 BLOCKING / 0 CRITICAL / 0 MAJOR / 2 MINOR (F-501, F-502).

PLAN-0046's correctness story is now coherent end-to-end:

- W1 — brokerage adapter captures amount/fee, holdings snapshot reconciles
- W2 — watchlist members denormalize tickers, dup-adds return 409
- W3 — root portfolio aggregates non-root sub-portfolios; cannot delete root
- W4 — daily snapshot worker writes per-trading-day rows, walks back 5 days for missing OHLCV, falls back to cost basis as last resort, marks `partial_prices`
- W5 — analytics endpoints (value-history, exposure, risk-metrics) read from those snapshots and surface honest captions to the UI

The two MINOR findings are quality-of-life. The plan is shippable; recommend opening a tiny PLAN-0046.5 cleanup commit for F-501 + F-502 if appetite remains, otherwise close PLAN-0046 and let those two ride along the next portfolio touch.
