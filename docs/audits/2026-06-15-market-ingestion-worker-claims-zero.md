# Market-Ingestion: "Worker claims 0 / no fresh OHLCV bars" — Investigation

**Date:** 2026-06-15
**Author:** Investigation (read-only)
**Severity:** P1 (HIGH) — entire market-data feed is frozen platform-wide; producer side is fine, the **outbox dispatcher is wedged** so nothing reaches Kafka or the bars table.
**Scope:** `services/market-ingestion` (scheduler + worker + outbox dispatcher), `ingestion_db`, Kafka, `market_data_db.ohlcv_bars`.

---

## TL;DR — Root Cause

The premise in the question ("worker claims 0 forever / no real fetch") is **only the symptom that was visible from the worker log line**. The actual data-flow is:

```
scheduler (enqueue PENDING)
   → worker._claim_batch() → worker._try_batch_execute() [REAL Alpaca multi-symbol fetch]
   → run_steps_2..5 writes bronze/canonical + INSERTs an OUTBOX row (market.dataset.fetched)
   → market-ingestion-DISPATCHER publishes outbox → Kafka
   → market-data ohlcv_consumer → market_data_db.ohlcv_bars
```

**The worker is healthy and IS fetching real bars right now** (logs show `batch_execute_fetched symbols_fetched=9`, `bars_returned=300/396/...`, `task_succeeded row_count=300`). `claimed=0` is a *between-batches idle reading*, not a stuck state.

**The freeze is one hop downstream: the outbox DISPATCHER is wedged.**
- `ingestion_db.outbox_events`: **~21,377 rows with `published_at IS NULL`**, newest created at the current minute → the producer keeps writing fetch events; nobody publishes them.
- The dispatcher container is `Status=running, Restarts=0`, **but its newest log line is `2026-06-15T06:38:27Z`** (confirmed via `docker logs --timestamps`) — it has emitted **nothing for ~15 h** while the outbox kept growing.
- The process is alive (PID 1, librdkafka bg threads 967/975/976) and **blocked on I/O at ~1.3 % CPU** — i.e. it is hung inside librdkafka `flush()` / delivery-wait, not crash-looping.
- Every one of its last log lines is `outbox_record_dispatch_failed` with **`error=""`** (empty) — a librdkafka delivery failure whose `str()` came back empty (classic `_MSG_TIMED_OUT` after the 2-day broker outage left the producer's connection/metadata stale).

Net effect: `market_data_db.ohlcv_bars` `max(bar_date)` is stuck at **2026-06-12** for *every* timeframe (1m/5m/15m/30m/1h/4h/1d), `last-24h count = 0`, even though Alpaca 1m (no EODHD budget gate) is being fetched continuously. **Stale bars are a publish-side stall, not a fetch-side stall.**

---

## Thread 1 — The claim path

**Code:** `application/use_cases/claim_tasks.py` → `infrastructure/db/repositories/task_repository.py::claim_batch` (lines 206-260).

Claim predicate (single atomic CTE, `FOR UPDATE SKIP LOCKED`):
```sql
(status IN ('pending','retry')
   OR (status='running' AND locked_until < now))
AND (next_attempt_at IS NULL OR next_attempt_at <= now)
ORDER BY created_at LIMIT :limit
```
New tasks default to `PENDING` (`domain/entities/ingestion_task.py:48`) with `next_attempt_at=NULL`, so they ARE claimable.

**Live DB (this session):**
```
status counts: succeeded 146335 | failed 288 | pending 19 | running 2
```
`pending`/`running` oscillate 0..N as the worker drains each batch — exactly what a *working* claim loop looks like. The `claimed=0` log lines interleave with `batch_execute_fetched` + `task_succeeded row_count=300` lines in the same worker. **No filter is excluding everything; the claim path is healthy.** The earlier "always 0" observation was captured during the cold-start window right after bring-up (see Thread 4).

---

## Thread 2 — The enqueue → terminal path

**Code:** `application/use_cases/schedule_tasks.py::execute` + `task_repository.py::add_many` (lines 131-162).

- `tasks_enqueued=120` = rows that **survived budget+cap filtering** and were INSERTed via `pg_insert(...).on_conflict_do_nothing(index_elements=["provider","dedupe_key"])`. `rowcount` only counts *new* PENDING rows; ON-CONFLICT no-ops do **not** count, so 120 is genuinely-new pending tasks/tick.
- Tasks are **not** inserted directly as `succeeded`. They go `PENDING → RUNNING → SUCCEEDED` via the worker. The "1084 updated / 10 min, 0 pending" reconciliation is simply throughput: the worker drains pending faster than the 60 s scheduler tick refills it, so a point-in-time snapshot frequently shows pending≈0. This is **normal**, not a skip-no-op.
- `_build_incremental_task` (lines 240-272) buckets intraday dedupe_key per-MINUTE (`range_end = now.replace(second=0)`), per the `FIX-INTRADAY-DEDUP` comment, so re-enqueues are NOT swallowed by ON-CONFLICT within the day. Confirmed not the bug.

**Watermarks are not the freeze cause** either: incremental due-ness uses `watermark.last_success_at` (wall-clock, written by the worker on success) via `policy.is_due(...)` (`FIX-WALLCLOCK`, lines 200-205), and the worker *is* succeeding, so policies keep coming due.

**Conclusion:** enqueue and terminal-transition are correct. Tasks reach `succeeded` legitimately *with real bars in the canonical payload* — the payload just never leaves the outbox (Thread = root cause).

---

## Thread 3 — The two budget mechanisms (the desync is real but is a *secondary* issue)

There are indeed **two independent budgets**, and they disagree:

1. **Local token bucket** — `ingestion_db.provider_budgets`, driven by `_apply_budgets` (`schedule_tasks.py:404-455`). This is what produces `budget_limited=1321`. It refills on elapsed time and charges `_EODHD_CREDIT_COST` per task (fundamentals=10, intraday OHLCV=5, etc.). After a multi-day downtime the bucket is **fully replenished**, so `provider_budgets` reads "nearly idle" (alpaca ≈1.65/10000, eodhd ≈0.73/10000). The `budget_limited=1321` is this bucket draining *within a single tick* (a burst of candidate tasks exceeds the per-tick token allotment, the rest are deferred to the next tick) — it then refills before the next read, so the stored counter looks idle. **Not contradictory once you account for per-tick burst vs. between-tick refill.**

2. **Real EODHD account quota** — enforced server-side (`/api/user`, 100k/100k exhausted) and mirrored by `messaging.eodhd_quota.EodhdQuotaService` (the `quota_service` injected into `ExecuteTaskUseCase`, checked in `pre_fetch_checks` step 0). The local `provider_budgets` row has **no knowledge** of the real account-level consumption.

**Desync verdict:** the local bucket can green-light EODHD tasks that the real account rejects; those tasks fail/skip at fetch time, not at schedule time. This wastes scheduler/worker cycles and pollutes the picture, **but it is not why bars are frozen** — Alpaca (Thread 4) proves the freeze is provider-independent. Recommend (lower priority) seeding/refreshing `provider_budgets` from the real `EodhdQuotaService` headroom so the scheduler stops enqueuing EODHD work that will bounce.

---

## Thread 4 — Alpaca 1m specifically (the control case that proves the root cause)

Alpaca 1m has **no EODHD budget gate** (`credit_cost=0` in the worker `provider_api_call` logs), so if it's frozen the cause must be downstream of fetch. Live worker logs:

```
provider_api_call alpaca ohlcv 1m BTC-USD  bars_returned=396 status=success credit_cost=0
provider_api_call alpaca ohlcv 1m SOL-USD  bars_returned=305 status=success
batch_execute_fetched alpaca 1m symbols_fetched=9
task_succeeded alpaca BTC-USD ohlcv row_count=396
task_succeeded alpaca XRP-USD ohlcv row_count=310
```
Alpaca 1m **is fetching fresh bars successfully**. Yet:
```
market_data_db.ohlcv_bars  1m  max(bar_date)=2026-06-12 19:59  last24h=0
```
The bars are produced by the worker and **stuck in the outbox** — they never reach `market.dataset.fetched` → `ohlcv_consumer` → `ohlcv_bars`. This is the decisive evidence that the stall is the **publish hop (dispatcher)**, not fetch, budget, watermark, or claim.

---

## Root-cause statement

> The market-ingestion **outbox dispatcher** (`infrastructure/messaging/dispatcher.py` / `outbox/dispatcher_main.py`) is **hung** after the 2026-06-13→06-15 outage. Its per-record path (`_dispatch_single`, lines 147-219) calls `producer.flush(delivery_timeout_seconds=10)` + `asyncio.wait_for(delivery_event, 10s)`, but the underlying librdkafka producer (`messaging.kafka.producer`, `delivery_timeout_ms=120_000`) holds each message for up to **120 s** before firing the delivery callback. After the broker outage the producer's connection/metadata is stale, deliveries time out, the 10 s app-level wait fires first and logs `dispatch_failed error=""`, but the message stays queued in librdkafka. With a 21 k backlog the internal producer queue saturates and `flush()` blocks, wedging the single serial dispatch loop entirely (last log 06:38, no progress for ~15 h). The worker keeps appending outbox rows, so `outbox_events.published_at IS NULL` grows unbounded and **every `ohlcv_bars` timeframe stays frozen at 2026-06-12**.

Contributing factors:
- **Mismatched timeouts:** app-level `delivery_timeout_seconds=10` < librdkafka `delivery_timeout_ms=120000`. The app gives up before librdkafka does, so messages are "failed" in the DB while still in-flight in the producer — double-counting and queue saturation.
- **Empty error string** (`error=str(delivery_error)` → `""`) hid the real librdkafka error, masking the outage for 15 h with no actionable log.
- **No `published_at` index + 206 MB/178 MB bloat** on `outbox_events` (87 k rows): ad-hoc `published_at` aggregates and even `GROUP BY status` time out at 8-15 s, slowing recovery tooling and any monitoring that scans that column.

---

## Self-heal vs. code fix

**Does NOT self-heal.** This is NOT the EODHD-quota story (that only affects EODHD-gated datasets and would free over ~24 h). The dispatcher is process-wedged on librdkafka I/O; it will stay stuck until **restarted**. EODHD quota freeing up will not move a single bar while the dispatcher is hung.

**Immediate remediation (ops, no code):**
1. `docker restart worldview-market-ingestion-dispatcher-1` — a fresh producer re-bootstraps broker metadata and drains the 21 k backlog (the dispatcher claim query is index-backed on `(status, locked_until)`, so drain is fast once Kafka delivery succeeds).
2. Confirm `ohlcv_consumer` is consuming (it was force-recreated per the outage note) and watch `market_data_db.ohlcv_bars max(bar_date)` advance past 2026-06-12.
3. Reclaim any `in_flight` outbox rows left with expired leases from the wedge (the dispatcher re-claims `status IN ('pending','retry')` only — rows stuck `in_flight` need their lease to expire or a manual `UPDATE ... SET status='retry' WHERE status='in_flight' AND locked_until < now()`).

**Minimal code fix (recommended):**
1. **Align timeouts:** set librdkafka `delivery_timeout_ms` ≤ the app-level `delivery_timeout_seconds*1000`, OR raise the app wait above librdkafka's. Best: drive the loop off the delivery callback only and drop the redundant `flush()`-per-record (batch-produce then one `flush()` + gather callbacks).
2. **Surface the real error:** in `_dispatch_single._cb`, capture the full `KafkaError` (`.code()/.name()/.str()`) not just `str(err)`, so an empty message can never hide a broker outage again.
3. **Add a watchdog/liveness signal:** emit a heartbeat metric each loop iteration and a healthcheck that fails if no outbox row published in N minutes while pending>0 — so a wedged-but-"running" container is caught.
4. **Add `published_at` partial index** (`WHERE published_at IS NULL`) and ensure periodic prune/vacuum of `outbox_events` to kill the 178 MB bloat.

---

## Thread 5 — Batch-recovery optimization (explicitly requested)

**Multi-symbol batching is ALREADY implemented and active.**
- `infrastructure/adapters/providers/alpaca.py`: `supports_batch=True`, `_BATCH_SIZE=1000`, `fetch_ohlcv_batch(symbols, timeframe, start, end)` chunks up to **1000 symbols/request** with `limit=10000` bars (lines 78-85, 108-109, 210-255).
- `infrastructure/workers/worker.py::_try_batch_execute` (lines 241-331) groups claimed intraday OHLCV tasks by `(provider, timeframe)` and issues **one HTTP call per group** (`batch_execute_fetched symbols_fetched=9` confirms it live).

**The remaining, un-implemented optimization is the time-WINDOW, not the symbol-fan-out.** After a 3-day outage the catch-up is crippled because the scheduler hard-codes the fetch window to **today only**:

- `schedule_tasks.py::_build_incremental_task` (lines 249-272): `range_start = today (UTC midnight)`, `range_end = now-truncated-to-minute`. It does **not** consult the watermark to widen the window. After the gap, incremental tasks fetch only 2026-06-15 bars; **2026-06-13 and 06-14 are never backfilled** by the steady-state path.
- The worker batch call inherits this: `worker.py:307-308` passes `group_tasks[0].range_start / range_end` straight to `fetch_ohlcv_batch` — so the window is exactly what the scheduler set (today).

**Recommended optimization (code site = `schedule_tasks.py::_build_incremental_task`):** set
`range_start = min(today_midnight, watermark.current_bar_ts or last_success bar)` so the window is **proportional to staleness**. One Alpaca call already returns up to 10 000 bars across up to 1000 symbols, so a 3-day, 9-symbol, 1m backfill (~3×1440×9 ≈ 38 k bar-rows) collapses into a handful of batched HTTP calls instead of being silently skipped. **Speedup: from "never catches up" (today-only window) to full gap closed in O(ceil(gap_bars/10000)) requests per symbol-chunk** — effectively one or two extra calls per timeframe group. This is the single highest-leverage catch-up change and is independent of the dispatcher fix.

---

## Suggested BUG_PATTERNS.md entry (next free: BP-701)

**BP-701 — Outbox dispatcher silently wedged on librdkafka delivery after broker outage; "running" container, growing backlog, empty error string.**
- *Symptom:* service container `Status=running, Restarts=0`, low CPU, but **no log output for hours**; `outbox_events.published_at IS NULL` grows unbounded; downstream tables frozen. Last log lines are `*_dispatch_failed` with `error=""`.
- *Root cause:* app-level delivery wait (`delivery_timeout_seconds`) shorter than librdkafka `delivery_timeout_ms`; after a broker outage deliveries time out, messages stay queued, the internal producer queue saturates, and a serial `flush()`-per-record dispatch loop blocks. `str(KafkaError)` can be empty, hiding the cause.
- *Fix:* (1) keep app wait ≥ librdkafka `delivery_timeout_ms`, or drive purely off delivery callbacks; (2) log full `KafkaError.code()/.name()`, never bare `str()`; (3) liveness watchdog: alert if pending>0 and nothing published in N min; (4) restart drains the backlog. Related: BP-590-class "running-but-dead" loops; outbox bloat needs a `published_at` partial index + vacuum.

---

## Evidence index
- Worker live logs: `batch_execute_fetched symbols_fetched=9`, `task_succeeded row_count=300/396`, interleaved `tasks_claimed claimed=0`.
- Dispatcher: `docker logs --timestamps` newest line `2026-06-15T06:38:27Z`, all `outbox_record_dispatch_failed error="" topic=market.dataset.fetched`; `docker inspect` `Status=running Restarts=0`; `docker stats` CPU≈1.3 %.
- `ingestion_db`: status counts (succeeded 146335 / pending 19 / running 2); `outbox_events` ~21,377 `published_at IS NULL`, newest at current minute; total/heap size 206 MB / 178 MB for 87 k rows; `GROUP BY status` / `published_at` scans exceed 8-15 s `statement_timeout`.
- `market_data_db.ohlcv_bars`: every timeframe `max(bar_date)=2026-06-12`, `last24h=0`.
- Kafka: topic `market.dataset.fetched` exists, schema subject `market.dataset.fetched-value` registered, dispatcher TCP-connects to `kafka:29092`, broker advertised listeners correct → infra reachable; failure is delivery-ack, not connectivity.
- Code: `claim_tasks.py`, `task_repository.py:206-304`, `schedule_tasks.py:85-272,404-455`, `worker.py:129-331`, `dispatcher.py:111-219`, `outbox_repository.py:97-133`, `alpaca.py:78-255`.
