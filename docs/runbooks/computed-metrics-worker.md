# Computed Metrics Worker — Operations Runbook

> **Service**: market-data · **Worker**: `ComputedMetricsBackfillWorker`
> **Source**: `services/market-data/src/market_data/infrastructure/db/computed_metrics_worker.py`
> **Scheduler**: lifespan task in `services/market-data/src/market_data/app.py`
> **Plan**: PLAN-0089 Wave L-3 (shipped 2026-05-28)

---

## What it does

Sweeps all instruments where `has_ohlcv = true` and computes **10** derived
market metrics into `fundamental_metrics` (`period_type='SNAPSHOT'`,
`section='computed_returns'`). The metric NAMES below are the exact strings
written to `fundamental_metrics.metric` — an operator query MUST use these
(earlier versions of this runbook listed wrong names like `distance_52w_high`
and a 252-day `return_1y`; those return zero rows):

| Metric (exact name) | Lookback | Notes |
|---------------------|----------|-------|
| `return_1m` | 30 calendar days | LATERAL JOIN, COALESCE(adj, close) on both sides |
| `return_3m` | 90 calendar days | same shape |
| `return_6m` | 182 calendar days | same shape |
| `return_ytd` | DATE_TRUNC('year') | Calendar anchor — on Jan 1 the anchor equals latest → 0.0 (expected) |
| `return_1y` | 365 calendar days | **Slowest formula** — start here when debugging |
| `return_3y` | 1095 calendar days | Often empty in dev (needs ~3y of bars) |
| `dist_from_52w_high_pct` | 365-day MAX | LATERAL JOIN window; `(close/max)-1` |
| `dist_from_52w_low_pct` | 365-day MIN | LATERAL JOIN window; `(close/min)-1` |
| `volatility_30d` | last 30 trading-day bars | `STDDEV_SAMP(daily returns) * sqrt(252)` (annualised); window function |
| `returns_adjustment_quality` | latest bar | `1.0` = adjusted_close present (returns correct); `0.0` = raw-close fallback (returns may be wrong across splits/dividends) |

> Note: the lookbacks for `return_*` are **calendar** days (the LATERAL JOIN
> selects the most recent bar at or before `latest - N days`, absorbing
> weekends/holidays), NOT trading days. `volatility_30d` uses the last 30
> **bars** (≈ 30 trading sessions).

All return/distance/volatility formulas use `COALESCE(adjusted_close, close)` on
both the numerator and the anchor. The summary field
`fallback_adjusted_close_count` tracks the number of distinct instruments where
`adjusted_close` was `NULL` for any metric; `returns_adjustment_quality` exposes
the same signal PER INSTRUMENT so the screener can badge unadjusted returns.

---

## Schedule

- **Trigger**: daily at **02:00 UTC** (controlled by `COMPUTED_METRICS_REFRESH_HOUR_UTC`).
- **Runner**: lifespan-task `market_data.app._computed_metrics_refresh_loop`.
- **Guard**: if a previous run finished within the last 20 hours, the scheduler
  skips and logs `computed_metrics_skip_too_recent` (INFO) and increments
  `computed_metrics_worker_runs_total{outcome="skipped"}`. The last-success
  timestamp is now persisted DURABLY in the `worker_runs` table (migration 040),
  so the guard survives a container restart (previously it was an in-process
  variable wiped on every restart, defeating its own purpose).
- **Watchdog**: each run is wrapped in `asyncio.wait_for(..., timeout=3600s)`. A
  run that hangs (e.g. a wedged asyncpg connection) raises `TimeoutError` into
  the loop's except branch instead of silently wedging the nightly refresh — it
  increments `computed_metrics_worker_runs_total{outcome="failed"}`.

---

## Expected runtime

| Scale | Wall-clock |
|-------|------------|
| Smoke test (50 instruments × 800 bars) | < 30 s (asserted by `tests/integration/test_computed_metrics_worker_perf.py`) |
| **Measured prod (654 instruments, 2026-06-19)** | **≈ 5.4 s** (`metrics_written≈4344`, `fallback_adjusted_close_count≈601`) |
| Projected at 3000 instruments | low minutes (linear-ish) — re-measure when the universe grows |

The smoke threshold is **not** a production SLO — it is a regression tripwire.
The earlier "5–15 min" estimate was unmeasured and is ~100× high at the current
654-instrument scale; the measured baseline above replaces it.

---

## Watch metrics

### Prometheus (scrape `/metrics`)

| Metric | Type | Use |
|--------|------|-----|
| `computed_metrics_worker_last_success_timestamp_utc_seconds` | Gauge | UTC epoch seconds of the last successful run. Seeded from `worker_runs` on boot. **Alert: `time() - <gauge> > 26*3600`** (one daily cadence + slack) → the nightly refresh has silently stalled. |
| `computed_metrics_worker_runs_total{outcome}` | Counter | `outcome` ∈ `success` \| `skipped` \| `failed`. Alert on any `failed` increase over 1 day. |
| `computed_metrics_worker_fallback_adjusted_close_ratio` | Gauge | Fraction of instruments using raw-close fallback (no `adjusted_close`). `1.0` = all unadjusted. At ~0.92 today this should already fire — it is the canary for the upstream split/dividend-adjustment gap. |

### Per-run log telemetry

Logged at INFO as `computed_metrics_refresh_completed` (loop) and
`computed_metrics_backfill.completed` (worker) with fields:

- `instruments_processed` — should match `SELECT count(*) FROM instruments WHERE has_ohlcv = true`
- `metrics_written` — expected ≈ `instruments_processed × <metrics with enough history>` (≤ 10; `return_3y` is usually absent in dev)
- `failed_instruments` — non-zero means batches threw an exception (with `continue_on_error=True` the run continues)
- `skipped_short_history_count` — instruments with insufficient history for a given lookback (e.g., short OHLCV history for `return_1y`/`return_3y`, or < 2 bars for `volatility_30d`)
- `fallback_adjusted_close_count` — **investigate when this is > 0**; signals OHLCV adjustment gap upstream (split / dividend not yet applied). Also exposed as the `..._fallback_adjusted_close_ratio` gauge.
- `runtime_seconds` — the run is hard-capped at 3600 s by the watchdog; a long run delays freshness even though the 20h skip-guard prevents next-day overlap.

---

## Failure modes

### 1. Run duration > 1 hour

Symptoms: `runtime_seconds > 3600` in summary log.

Risk: even with the 20-hour skip-guard, persistent slowdown means the metrics
will be stale by the time the morning brief generates at 06:00 UTC.

Diagnose:
- Check Postgres connection pool saturation (`pg_stat_activity`).
- `EXPLAIN ANALYZE` the `return_1y` LATERAL JOIN — it is the deepest formula.
- Confirm the index `idx_ohlcv_instrument_bar_date` is healthy
  (`SELECT * FROM pg_stat_user_indexes WHERE indexrelname LIKE '%ohlcv%'`).
- Look for autovacuum lag on `ohlcv_bars`.

### 2. `fallback_adjusted_close_count` spike

Symptoms: logged at WARNING (`computed_metrics_backfill.adjusted_close_fallback`)
and surfaced as the `computed_metrics_worker_fallback_adjusted_close_ratio` gauge.

> **Known live state (2026-06-18)**: ~92% of instruments (601/654) use the
> raw-close fallback because `adjusted_close` is NULL on essentially all recent
> OHLCV bars. Root cause is **upstream** — `market-ingestion` is not populating
> `adjusted_close` (only EODHD `/eod/` end-of-day bars carry it; the Alpaca 1m
> write-through and intraday bars do not). market-data persists `adjusted_close`
> faithfully when the provider sends it (see `ohlcv_consumer.py`), so the fix
> belongs in the market-ingestion provider adapters. Until then,
> `returns_adjustment_quality=0.0` correctly flags the affected instruments so
> the screener does not present unadjusted returns as truth.

Risk: returns computed on raw `close` instead of `adjusted_close` will misstate
post-split / post-dividend periods.

Diagnose:
- Cross-check `market_ingestion` adjustment worker is running.
- Spot-check an affected instrument:
  `SELECT bar_date, close, adjusted_close FROM ohlcv_bars WHERE instrument_id = '<id>' ORDER BY bar_date DESC LIMIT 30`.

### 3. `failed_instruments > 0`

Symptoms: `computed_metrics_backfill.batch_failed` ERROR log.

Risk: a sub-batch raised — usually an asyncpg connection drop or a transient
Postgres error. With `continue_on_error=True` (the default) the sweep moves on.

Diagnose:
- Check the per-batch error message in the log.
- Re-run manually for the affected `start_instrument_id` range (see below).

### 4. YTD returns 0.0 on Jan 1

**Not a bug.** On the first trading day of the year the YTD anchor LATERAL JOIN
selects `latest` itself, producing exactly `0.0`. This is mathematically
correct (0 % YTD on day 1) and is pinned by
`test_ytd_edge_case_first_trading_day_of_year_returns_zero`.

---

## Manual restart

The worker has **no dedicated CLI entry point** — it runs only as a lifespan
task inside the market-data FastAPI process. To trigger an out-of-band sweep
without waiting for 02:00 UTC, the simplest options are:

1. **Restart the pod** with `COMPUTED_METRICS_REFRESH_HOUR_UTC` set to the
   current hour, then revert after the sweep completes.
2. **Add a CLI script** if manual re-runs become routine (deferred — track as a
   follow-up if Ops requests it). The function to invoke is
   `market_data.infrastructure.db.computed_metrics_worker.run_computed_metrics_backfill`.

For a partial re-run (e.g., one instrument range), use
`ComputedMetricsBackfillOptions(start_instrument_id=<uuid>)`.

---

## Heavy-SQL reference

The formulas are committed in `computed_metrics_worker.py`
(`_RETURN_FORMULA_SQL`, `_YTD_RETURN_SQL`, `_DISTANCE_52W_SQL`,
`_VOLATILITY_30D_SQL`, `_ADJUSTMENT_QUALITY_SQL`). When performance degrades:

```sql
-- Run against market_data_db with a real instrument_id and lookback.
EXPLAIN (ANALYZE, BUFFERS)
SELECT
    i.id, latest.px, ref.px,
    (latest.px / NULLIF(ref.px, 0)) - 1.0 AS value_numeric
FROM instruments i
JOIN LATERAL (
    SELECT COALESCE(adjusted_close, close) AS px, bar_date
    FROM ohlcv_bars
    WHERE instrument_id = i.id AND timeframe = '1d'
    ORDER BY bar_date DESC
    LIMIT 1
) latest ON true
JOIN LATERAL (
    SELECT COALESCE(adjusted_close, close) AS px
    FROM ohlcv_bars
    WHERE instrument_id = i.id AND timeframe = '1d'
      AND bar_date <= latest.bar_date - INTERVAL '252 days'
    ORDER BY bar_date DESC
    LIMIT 1
) ref ON true
WHERE i.has_ohlcv = true
LIMIT 50;
```

Expected plan: `Index Scan` on `idx_ohlcv_instrument_bar_date` for both
LATERAL subqueries. Any `Seq Scan` here means the index is missing or
disabled — investigate before deploying.

---

## Related

- Unit tests: `services/market-data/tests/unit/test_computed_metrics_backfill.py`
- Perf smoke test: `services/market-data/tests/integration/test_computed_metrics_worker_perf.py`
- Plan: `docs/plans/0089-plan.md` (Wave L-3)
