# PRD-0089 §4 + §5 — Computed-Metrics Worker Ops & Migration-031 Window (Deep-Dive)

> **Scope**: READ-ONLY investigation of `DEFERRED-WORK-PLAN.md` §4 (Migration 031
> deploy-window sequencing) and §5 (L-3 `ComputedMetricsBackfillWorker` smoke /
> runbook / alerting).
> **Date**: 2026-06-16 · **Worktree HEAD**: `2e447e8be` · **Live DB read**: 2026-06-19.
> **Companion**: extends `docs/audits/2026-06-16-prd0089-state-reconciliation.md`
> (which explicitly deferred this deep-dive).

This is backend-ops work, so "UI enhancement" is light — the lens is
**correctness + observability**, with the downstream IB-L3 screener UX noted in
Lens 3.

---

## TL;DR verdicts

| Item | Verdict |
|------|---------|
| §4 Migration `031_extend_field_type_check.py` exists | YES |
| §4 DROP-then-ADD constraint window still present | YES — verbatim, lines 40–49 |
| §4 Runbook constraint-warning note added | NO — 0 hits in `docs/services/market-data.md` and `docs/runbooks/` |
| §4 Migration 031 still HEAD | NO — superseded; HEAD is now `039`. 031 is mid-chain (`032.down_revision="031"`) |
| §5 Worker runs nightly | YES — last run 2026-06-19 02:00 UTC, clean |
| §5 Worker actually WRITES rows (post BP-180) | YES — BP-180 `CAST(:start_id AS uuid)` fix present (worker L155–160); live `metrics_written=4344` |
| §5 Prometheus gauge/counter for the worker | NO — 0 metric definitions; the loop logs INFO/ERROR only |
| §5 Staleness alert wired | NO — only the plan + reconciliation doc reference the proposed metric names |
| §5 20-hour skip-guard present | YES — but it is **in-process memory**, see Lens 2 |
| §5 Production wall-clock baseline | Now measured: **5.4 s** (see Lens 2) — plan's "5–15 min" estimate is ~100× off at current scale |

**New findings beyond the plan**:
1. **92% adjusted_close fallback** — `fallback_adjusted_close_count=601 / 654` instruments; upstream split/dividend-adjustment data is essentially absent (99.997% of recent OHLCV bars have `adjusted_close IS NULL`). Returns are computed on raw `close`. This is a silent data-quality defect the runbook says to "investigate when > 0".
2. **`volatility_30d` is not implemented** — both the runbook metric table and plan §5.1 say "8 metrics", but the worker emits **7 metric names** (5 returns + 2 distance). The runbook table is inaccurate (lists `volatility_30d`, `return_1m`-only naming, and `distance_52w_high/low` instead of the real `dist_from_52w_high_pct/low_pct`).
3. **`return_3y` is effectively empty** — 1 row live (most instruments lack 1095 days of history).

---

## §4 — Migration 031 deploy-window

### Lens 1 — Existence / current state

- **File**: `services/market-data/alembic/versions/031_extend_field_type_check.py` — EXISTS.
- **Window still present**: `upgrade()` does exactly what §4.1 describes:
  - L40 `DROP CONSTRAINT IF EXISTS ck_screen_field_metadata_field_type`
  - L45–49 `ADD CONSTRAINT … CHECK (field_type IN ('numeric','text','date'))`
  - L53–57 `UPDATE … SET field_type='date' WHERE field_name IN (…)`
  - The DROP→ADD gap is real and unmitigated (no `NOT VALID` staging that would avoid the gap; the comment explicitly chooses an immediate full check).
- **Runbook note**: NOT added. `grep "ck_screen_field_metadata_field_type"` → 0 hits across `docs/services/market-data.md` and all of `docs/runbooks/`. The §4.3 one-liner has not been written anywhere.
- **Is 031 still HEAD?**: NO. The chain has advanced to `039_unique_isin_exchange_instruments.py`. `031` sits mid-chain (`032.down_revision = "031"`). It is **not** superseded in function — the widened CHECK and the `date` re-typing remain live — only its position as HEAD changed.

### Lens 2 — Root cause of the gap

- The window risk is **theoretical** and, on inspection, even smaller than §4.2 claims: the only writers to `screen_field_metadata` are alembic (serialized by alembic's advisory lock) and `_screen_fields_refresh_loop` (writes only known-good `field_type` values from `_get_static_screen_fields()`). For a bad row to land, a concurrent writer would have to attempt `field_type='invalid'` inside the sub-millisecond DROP→ADD gap. No such writer exists.
- Root cause of the "gap" item: it is a **documentation debt**, not a code defect. The fix was scoped as a 10-min runbook note and simply never landed.

### Lens 3 — UI / data-quality downstream

- Negligible. The CHECK governs whether `next_earnings_date` / `next_dividend_date` render as a calendar widget vs a plain number in the screener. The migration already fixed that (rows are `field_type='date'` live). A bad row during the window would render one field wrong; the only writer never produces one.

### Lens 4 — Bloomberg-competitive

- Not material. This is internal schema hygiene; no competitive surface.

### Recommended fix (§4)

- **Lowest-cost, do it**: add the §4.3 one-liner to `docs/runbooks/market-data-operations.md` (a deploy-runbook already exists there, more appropriate than the service doc). 10 minutes.
- **Optional hardening (not required)**: future constraint-widening migrations should use `ADD CONSTRAINT … NOT VALID` followed by `VALIDATE CONSTRAINT` — that pattern never drops the old constraint, eliminating the window entirely. Capture as a migration-authoring convention rather than reworking 031.

---

## §5 — L-3 ComputedMetricsBackfillWorker

### Lens 1 — Existence / current state (with live numbers)

**It runs and writes.** Live `fundamental_metrics` (market_data_db, 2026-06-19):

```
metric                  rows   instruments  latest_as_of
return_ytd              2016   654          2026-06-16
dist_from_52w_high_pct  2016   (654)        2026-06-16
dist_from_52w_low_pct   2016   (654)        2026-06-16
return_1m               1962   626
return_3m               1895   594
return_6m               1891   592
return_1y               1352   570
return_3y                  1     1   <- effectively empty (needs 1095d history)
```

Last nightly run (from `worldview-market-data-1` logs, `computed_metrics_backfill.completed`):

```
started_at  2026-06-19T02:00:00Z
completed_at 2026-06-19T02:00:05Z
runtime_seconds            5.44
instruments_processed       654
metrics_written            4344
skipped_short_history_count   0
fallback_adjusted_close_count 601   <-- 92% of 654
failed_instruments            0
```

- **BP-180 cast fix is present and effective**: worker L155–160 / L203 / L242 use `CAST(:start_id AS uuid)`; `metrics_written=4344` (not 0). The "silently writes 0" failure described in §5.1 is resolved.
- **Metric-name mismatch (NOTE)**: the live metric names are `return_1m/3m/6m/1y/3y`, `dist_from_52w_high_pct`, `dist_from_52w_low_pct` (worker `_PERIOD_RETURN_LOOKBACKS` L79–85 + L174–175). The runbook's metric table (lines 15–24) lists `volatility_30d`, `distance_52w_high/low`, and a 252-day `return_1y` — none of which match the code. **A naive operator query using runbook names returns zero rows** (I hit this during the investigation). The runbook table needs correcting.
- **`volatility_30d` is not implemented at all** — 0 occurrences in `computed_metrics_worker.py`. Both the plan ("8 metrics") and runbook are wrong; it is 7 metric names.

**No Prometheus instrumentation.** `grep` for any Counter/Gauge/`.inc()`/`.set()` tied to `computed_metrics*` in `services/market-data/src/` → **0 hits**. The loop (`app.py:714 _computed_metrics_refresh_loop`) emits only:
- `computed_metrics_refresh_completed` (INFO)
- `computed_metrics_skip_too_recent` (INFO)
- `computed_metrics_refresh_error` (ERROR)
- `computed_metrics_invalid_hour_using_default` (WARNING)

None of these is a metric. There is **no** `computed_metrics_worker_runs_total` and **no** `computed_metrics_worker_last_success_timestamp_utc_seconds`. `grep` across the whole repo finds those proposed names only in `DEFERRED-WORK-PLAN.md` and the reconciliation audit. **No alert is wired anywhere.**

### Lens 2 — Root cause + concrete silent-stall assessment

**20-hour skip-guard (`app.py:756–770`)** uses `last_success_at`, a **local variable inside the loop coroutine** (L748). Critical consequences:

- **It does NOT persist across restarts.** On pod restart `last_success_at=None`, so the guard is a no-op until the first in-process success. Its only job (per the docstring) is to stop a double-run inside the same 24h window after a restart — which it *cannot* do, because the restart wipes the state it relies on. The guard is effectively dead against the exact scenario it was written for. (Low severity: a double-run is idempotent — it just re-UPSERTs the same metrics.)

- **The silent-stall scenario the plan worries about**: "if a run exceeds 20h, the daily refresh silently stops." Concrete trace:
  - The scheduler is a single `while True` with `await asyncio.sleep(seconds_until_next_hour)` then `await run_computed_metrics_backfill(...)`. It is **strictly sequential** — the next sleep is computed only after the current run returns. So a long run delays (does not overlap) the next run; the 20h guard is largely irrelevant to overlap.
  - **If the run hangs forever** (e.g. a wedged asyncpg connection, no statement timeout visible in the worker), the loop never reaches the next iteration. **Nothing detects this.** No watchdog, no metric, no alert. The morning brief at 06:00 silently consumes whatever is in `fundamental_metrics` — i.e. stale-but-present rows — so there is no error, just silently aging data.
  - **If the run raises**, the `except Exception` (L780) logs `computed_metrics_refresh_error` at ERROR and sleeps `_COMPUTED_METRICS_RETRY_SECONDS`, then retries. An ERROR log is the *only* signal — and only if someone is grepping logs or has a Sentry/Loki rule on that event string (none found).

- **At current scale the freshness risk is low** (5.4 s per run, ~100× headroom to the 20h guard). **But the plan's premise is the right one for the future**: the differentiator is freshness, and the only thing standing between "fresh" and "silently 3 days stale" is a human noticing an absent INFO log. That is the textbook "all-green / silent stall" pattern this codebase has repeatedly been bitten by (BP-180, audit-return-persistence feedback).

- **Why the gaps exist**: §5 was explicitly scoped as *post-staging follow-ups* (T-WL3-FILL-01/02/03) and was never executed because there has been no staging cutover. The runtime/fallback baselines were "placeholders" in intent; the runbook actually shipped with *estimates* (5–15 min) rather than measured numbers, and the estimates are wrong by 2 orders of magnitude at current scale.

### Lens 3 — UI / data-quality downstream

- The returns (`return_1m…1y`) and `dist_from_52w_high_pct/low_pct` feed the **IB-L3 screener columns** (Returns + 52W-distance). Linkage:
  - **Silent stall → stale/empty screener columns.** If the worker stops, `fundamental_metrics` ages silently; the screener keeps rendering last-good values with no "as-of" warning. A user sorting "biggest 1Y gainers" gets a ranking frozen at the last successful run — a classic silent-failure UX (looks live, isn't).
  - **92% adjusted_close fallback → materially wrong returns across split/dividend events.** Every return is currently computed on raw `close`. For any instrument that split or paid a dividend in the lookback window, the displayed return is wrong (e.g. a 4:1 split shows a fake −75% 1Y return). The screener will surface these as spurious outliers. This is a **live data-quality defect today**, independent of the stall risk, and the single highest-impact correctness issue in this area.
  - **`return_3y` column would be ~empty** (1 instrument) — if IB-L3 exposes a 3Y column it should be hidden or badged until OHLCV history deepens.

### Lens 4 — Bloomberg-competitive: what observability makes this trustworthy

Returns + 52W-distance screening is table-stakes vs Bloomberg/Finviz; the moat is **freshness + provable reliability**. Minimum bar to be trustworthy:

1. **Liveness metric + alert** (the §5.2 ask): `computed_metrics_worker_last_success_timestamp_utc_seconds` gauge + `computed_metrics_worker_runs_total{outcome}` counter; alert `time() - last_success > 26*3600`. This is the single fix that converts "silently 3 days stale" into a page. **Do this first.**
2. **Run-duration histogram** `computed_metrics_worker_runtime_seconds` so the 5.4 s → minutes-scale drift (when instrument count grows toward 3000) is visible *before* it threatens the 20h guard.
3. **Fallback-rate gauge** `computed_metrics_worker_fallback_adjusted_close_ratio` — at 92% today this should already be firing. It is the canary for the upstream split-adjustment gap. Surfacing it ties the screener's correctness to the OHLCV-adjustment pipeline.
4. **Data-as-of surfaced in the UI**: the IB-L3 columns should carry the `max(as_of_date)` so the screener degrades *visibly* (a "as of Jun 16" stamp) rather than silently when the worker stalls. This is the cheapest UX guard and is what Bloomberg terminals do (every cell is timestamped).
5. **Hang watchdog**: wrap `run_computed_metrics_backfill` in `asyncio.wait_for(..., timeout=...)` so a wedged connection raises into the existing `except` (and increments the `failed` counter) instead of hanging the loop forever.
6. **Persist `last_success_at`** (e.g. a row in a small `worker_runs` table or Valkey key) so the skip-guard actually works across restarts and the liveness metric survives a deploy.

### Recommended fixes (§5), priority order

| Pri | Fix | Effort | Why |
|-----|-----|--------|-----|
| P0 | Add `last_success_timestamp` gauge + `runs_total{outcome}` counter + 26h staleness alert | ~2 h | Converts silent stall → page (the core §5.2 gap) |
| P0 | Correct the runbook metric table (real names; drop `volatility_30d`; fix `return_1y` lookback note) and fill measured baseline (5.4 s / 4344 metrics / 601 fallback) | ~20 min | Runbook currently misleads operators; baseline now exists |
| P1 | Investigate 92% `adjusted_close` fallback — confirm market-ingestion adjustment worker; it is currently a live data-quality defect feeding wrong returns to the screener | ~half-day | Highest correctness impact on IB-L3 |
| P1 | `asyncio.wait_for` timeout around the backfill run + fallback-ratio gauge | ~1 h | Closes the infinite-hang silent-stall path |
| P2 | Surface `as_of_date` in IB-L3 columns (visible staleness) | frontend | Bloomberg-grade freshness UX |
| P2 | Persist `last_success_at` across restarts | ~1 h | Makes the 20h guard real + metric deploy-durable |
| P3 | EXPLAIN ANALYZE `return_1y`/`return_3y` LATERAL join (T-WL3-FILL-03) | ~2 h | Pre-emptive; at 5.4 s it is not urgent until scale grows |

---

## Evidence index

- Migration: `services/market-data/alembic/versions/031_extend_field_type_check.py` (window L40–49); chain HEAD `039`.
- Worker: `services/market-data/src/market_data/infrastructure/db/computed_metrics_worker.py` (BP-180 cast L155–160; metric names L79–85, L174–175; fallback warn L531–534; no `volatility`, no prometheus).
- Scheduler: `services/market-data/src/market_data/app.py:714 _computed_metrics_refresh_loop` (in-process `last_success_at` L748; guard L756–770; INFO/ERROR-only telemetry).
- Runbook: `docs/runbooks/computed-metrics-worker.md` (metric table L15–24 inaccurate; runtime estimate L46 unmeasured).
- Live DB: `worldview-postgres-1` / `market_data_db` — `fundamental_metrics` counts above; `ohlcv_bars` adjusted_close NULL = 343,869 / 343,880 recent bars.
- Live logs: `worldview-market-data-1` — `computed_metrics_backfill.completed` 2026-06-19 02:00, runtime 5.44 s, fallback 601/654.
- No alert: `grep` for proposed metric names hits only `DEFERRED-WORK-PLAN.md` + `2026-06-16-prd0089-state-reconciliation.md`.
