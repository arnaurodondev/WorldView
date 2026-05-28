# PLAN-0099 W2 T-W2-01 — AGE TemporalEvent Reconciliation Run

**Date:** 2026-05-27
**Branch:** feat/plan-0093-remediation
**Script:** `scripts/reconcile_age_temporal_events.py` (PLAN-0096 W3)

## Pre-state

| Source | Count |
|---|---|
| `intelligence_db.temporal_events` (SQL) | **15 346** |
| AGE `(:TemporalEvent)` nodes in `worldview_graph` | **15 346** |
| Gap | **0** |

The relational source and the AGE graph were already in lockstep before
this remediation ran. The historical 14 822-node backlog described in
BP-574 / PLAN-0096 W3 has already been drained by the periodic
`AgeSyncWorker` after the session-cache fix was deployed.

## Dry-run output

Executed from the host (script not shipped inside the container image):

```
$ source .venv312/bin/activate && \
  python scripts/reconcile_age_temporal_events.py --dry-run
2026-05-27 20:09:01 INFO starting reconcile_age_temporal_events:
    db_url=localhost:5432/intelligence_db batch_size=500 dry_run=True
2026-05-27 20:09:01 INFO scanned temporal_events: 15346 rows
2026-05-27 20:09:01 INFO [dry-run] would MERGE 15346 rows in batches of 500
2026-05-27 20:09:01 INFO DONE: scanned=15346 merged=0 skipped=0 (dry_run=True)
```

Script executes cleanly: connects, scans, reports, no errors. The scan
took ~155 ms for 15 346 rows.

## Wet-run output

**Not executed.** Per the task constraints, the dry-run output had to be
"reasonable" to proceed. Reasonable here would normally mean a small
positive backlog (≤ 1000). The dry-run reports the script would attempt
to MERGE all 15 346 rows because it does no diff-against-AGE — but the
post-state already matches the source. Running wet would have driven
15 346 idempotent MERGE statements against AGE for zero behavioural
benefit (each row already exists), at the cost of ~15 k unnecessary
Cypher round-trips and write-amplification on `ag_label_vertex`.

The script is correct (the MERGE is idempotent so a wet run is safe),
but it is not the right tool when the gap is already zero.

## Post-state

Unchanged from pre-state — both counts remain **15 346**. Gap **0**.

## Root cause: why did auto-sync deliver, and why was a manual run on
the PLAN-0099 backlog?

Auto-sync **did** deliver. The `AgeSyncWorker` is registered as an
"early job" in `scheduler.py:160-180`:

* fires `now + 120 s` after container boot (faster than the
  pre-PLAN-0089 60-min wait), and
* runs every `worker_age_sync_interval_s = 900 s` (15 min) thereafter.

Recent scheduler logs (last 30 min) show two cycles at `02:53:59 UTC`
and `03:08:59 UTC`, both completing in ~100-130 ms with
`temporal_events_synced=0` — the watermark is current and there is
nothing left to drain. The `age_sync_worker_no_changes` warning is
expected steady-state behaviour, not a fault.

PLAN-0099 listed this task because at planning time (immediately after
the BP-574 fix shipped) the backlog still existed and a manual one-shot
was the documented remediation path. By the time T-W2-01 actually ran,
the periodic worker had already chewed through the entire backlog over
its boot-delay + a handful of 15-min ticks.

## Recommendation: should auto-sync be tightened?

**No code change needed.** The current configuration is already tight:

1. `next_run_time = now + 120 s` — fires ~2 min after container boot,
   not after a full 15-min interval. PLAN-0089 already tightened this
   from the pre-existing "fire after one full interval" anti-pattern.
2. 15-min cadence on a 15 346-row table that grows by single-digit
   rows/minute is comfortable headroom; the worker run takes ~130 ms
   end-to-end.
3. Idempotent MERGEs — re-running on overlap is safe.

The one residual friction is operator visibility: the warning
`age_sync_worker_no_changes` fires on every steady-state tick (96×/day)
and is indistinguishable from a genuine "watermark is stale" alert.
Downgrading this to `info` (or gating it on `synced_count == 0 AND
watermark_lag > some_threshold`) would reduce log noise without
sacrificing the diagnostic. Filed as a PLAN-0099 follow-up candidate,
not blocking.

## Outcome

* Script validated working (clean dry-run, correct row count).
* No data-plane change required — backlog already drained by the
  periodic worker.
* T-W2-01 closes as **no-op verified**, not as a remediation that
  delivered new rows.
