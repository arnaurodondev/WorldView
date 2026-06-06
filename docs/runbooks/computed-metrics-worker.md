# Computed Metrics Worker — Operations Runbook

> **Service**: market-data · **Worker**: `ComputedMetricsBackfillWorker`
> **Source**: `services/market-data/src/market_data/infrastructure/db/computed_metrics_worker.py`
> **Scheduler**: lifespan task in `services/market-data/src/market_data/app.py`
> **Plan**: PLAN-0089 Wave L-3 (shipped 2026-05-28)

---

## What it does

Sweeps all instruments where `has_ohlcv = true` and computes 8 derived market
metrics into `fundamental_metrics`:

| Metric | Lookback | Notes |
|--------|----------|-------|
| `return_1m` | 21 trading days | LATERAL JOIN, COALESCE(adj, close) on both sides |
| `return_3m` | 63 trading days | same shape |
| `return_6m` | 126 trading days | same shape |
| `return_ytd` | DATE_TRUNC('year') | Calendar anchor — on Jan 1 the anchor equals latest → 0.0 (expected) |
| `return_1y` | 252 trading days | **Slowest formula** — start here when debugging |
| `distance_52w_high` | 252-day MAX | LATERAL JOIN window |
| `distance_52w_low` | 252-day MIN | LATERAL JOIN window |
| `volatility_30d` | 21-day stddev of log returns | Window function |

All formulas use `COALESCE(adjusted_close, close)` on both the numerator and the
anchor. The summary field `fallback_adjusted_close_count` tracks the number of
distinct instruments where `adjusted_close` was `NULL` for any metric.

---

## Schedule

- **Trigger**: daily at **02:00 UTC** (controlled by `COMPUTED_METRICS_REFRESH_HOUR_UTC`).
- **Runner**: lifespan-task in `market_data.app._computed_metrics_scheduler_task`.
- **Guard**: if a previous run finished within the last 20 hours, the scheduler
  skips and logs a WARNING (`computed_metrics_backfill.skipped_recent_run`).

---

## Expected runtime

| Scale | Wall-clock |
|-------|------------|
| Smoke test (50 instruments × 800 bars) | < 30 s (asserted by `tests/integration/test_computed_metrics_worker_perf.py`) |
| Production (3000 instruments × ~1100 bars) | ≈ 5–15 min |

The smoke threshold is **not** a production SLO — it is a regression tripwire.
If the smoke test starts taking > 30 s, expect production to take roughly 10×
that wall-clock.

---

## Watch metrics

Per-run telemetry is logged at INFO as `computed_metrics_backfill.summary` with
fields:

- `instruments_processed` — should match `SELECT count(*) FROM instruments WHERE has_ohlcv = true`
- `metrics_written` — expected ≈ `instruments_processed × 8`
- `failed_instruments` — non-zero means batches threw an exception (with `continue_on_error=True` the run continues)
- `skipped_short_history_count` — instruments with insufficient history for a given lookback (e.g., < 252 bars for `return_1y`)
- `fallback_adjusted_close_count` — **investigate when this is > 0**; signals OHLCV adjustment gap upstream (split / dividend not yet applied)
- `runtime_seconds` — alert if > 3600 (1 hour); the 20h skip-guard prevents next-day overlap, but a long run delays freshness

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

Symptoms: logged at WARNING (`computed_metrics_backfill.fallback_used`).

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

The 8 LATERAL JOIN formulas are committed in
`computed_metrics_worker.py:127-241` (`_RETURN_FORMULA_SQL`, `_YTD_RETURN_SQL`,
`_DISTANCE_52W_SQL`). When performance degrades:

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
