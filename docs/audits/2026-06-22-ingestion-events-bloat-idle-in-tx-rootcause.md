# Root-cause audit: `ingestion_events` 419 MB bloat, idle-in-transaction, never-autovacuumed

**Date:** 2026-06-22
**Scope:** `market_data_db.ingestion_events` on `worldview-postgres-1` (PostgreSQL 16.6)
**Method:** READ-ONLY — `pg_stat_activity` / `pg_class` / `pg_stat_user_tables` sampling + source read. No DDL/DML/VACUUM, no edits.
**Predecessor:** `docs/audits/2026-06-21-postgres-split-optimization.md` (noted the 62 s idle-in-tx backend).

---

## TL;DR

`ingestion_events` (in `market_data_db`) is 419 MB — 208 MB heap + 212 MB indexes — for **19.8 k live rows**, with **49 419 dead tuples (~250 %)** and `autovacuum_count = 0`. Three independent facts, each verified:

1. **Why it bloats (dead tuples on an INSERT-only table):** `n_tup_upd = 0`, `n_tup_del = 0`. Every dead tuple is an **aborted INSERT**. The Kafka consumer inserts the `ingestion_events` idempotency row *first* inside the per-message transaction; on **any** processing failure the base consumer calls `uow.rollback()`, aborting that INSERT → one dead tuple per failed message. Historical DLQ storms (2 236 watchdog timeouts, the ~29 % extraction `api_error` rate, schema-evolution waves) produced tens of thousands of aborted inserts. `ON CONFLICT DO NOTHING` on the duplicate path adds a steady drip of speculative-insertion dead tuples.

2. **Why autovacuum has NEVER run on THIS table (the real lock-out):** **stale, wildly-inflated `pg_class.reltuples = 1 040 627`** while the table holds only 19 853 live rows. The autovacuum daemon computes its dead-tuple trigger from `reltuples`, not from the live count: `threshold = 50 + 0.2 × 1 040 627 ≈ 208 175`. The actual 49 419 dead tuples never reach it → autovacuum never triggers (count stays 0; `last_autovacuum = NULL`). The insert-vacuum trigger (`1000 + 0.2 × reltuples ≈ 209 175`) and the analyze trigger (`50 + 0.1 × reltuples ≈ 104 112`) are *also* above the real workload, so **autoanalyze never runs either — which is exactly what would correct `reltuples`.** Self-perpetuating deadlock. Autovacuum is healthy everywhere else in `market_data_db` (e.g. `fundamental_metrics` autovacuumed 110× in the last hour) — this table alone is locked out by its stale stat.

3. **The idle-in-transaction xmin pin (amplifier + the bridge to point 2):** two code paths hold long write transactions that pin `backend_xmin`, making vacuum no-ops during the windows they were live and (historically) letting dead tuples accumulate faster than they could be cleaned:
   - **market-data fundamentals consumer** — observed `idle in transaction` for **29–33 s** with last query `INSERT INTO fundamental_metrics …`, pinning `market_data_db`'s horizon. This is the path that directly governs `ingestion_events`.
   - **market-ingestion scheduler** — one transaction per tick that scans **2 102 enabled polling policies** sequentially, observed `idle in transaction` up to **47–62 s** (the 62 s backend from the prior audit), pinning `ingestion_db`'s horizon.

`idle_in_transaction_session_timeout = 0` (disabled) — no backstop. No replication slots, no prepared xacts (so neither holds the horizon).

---

## Evidence

### Table state (live)
```
relname=ingestion_events  n_live=19 853  n_dead=49 419  dead≈250%
n_tup_ins=68 804  n_tup_upd=0  n_tup_del=0      ← INSERT-only; all dead = aborted INSERTs
n_ins_since_vacuum=69 322  n_mod_since_analyze=19 903
autovacuum_count=0  vacuum_count=0  last_autovacuum=NULL  last_autoanalyze=NULL  analyze_count=0
size: total 419 MB | heap 208 MB | indexes 212 MB
reltuples=1 040 627  relpages=26 572   ← STALE: 52× the real live count
```

### Autovacuum IS healthy on the rest of the database (rules out global disable / global xmin block)
```
fundamental_metrics  n_dead=29 821  last_autovacuum=07:09  autovacuum_count=110
income_statements     n_dead=16 074  last_autovacuum=05:59  autovacuum_count=15
_hyper_1_20_chunk     n_dead=49 967  last_autovacuum=07:13  autovacuum_count=9
ingestion_events      n_dead=49 419  last_autovacuum=NULL   autovacuum_count=0   ← only this table
```
14 of 101 tables have been autovacuumed; the daemon works. The xmin pin is therefore **not** what stops `ingestion_events` — the stale `reltuples` is. (The xmin pin is a real, separate problem that made *every* table's vacuum a partial no-op during the long-tx windows and accelerated the historical accumulation.)

### Idle-in-transaction backends (live samples)
```
# market_data_db — fundamentals consumer, sampled 3 s apart:
pid 35346  idle in transaction  xact_age=29s  state_age=0s  query=INSERT INTO fundamental_metrics …
pid 35346  idle in transaction  xact_age=33s  state_age=0s  query=INSERT INTO fundamental_metrics …

# ingestion_db — scheduler tick:
pid 34894  idle in transaction  xact_age=47s  query=SELECT polling_policies.id, polling_policies.provider …
```
`pg_replication_slots`: 0 rows. `pg_prepared_xacts`: 0. `idle_in_transaction_session_timeout = 0`.

### Index bloat detail
```
uq_ingestion_events_event_id  101 MB  (idx_scan 69 023)   ← should be ~1–2 MB for 19.8k rows
ingestion_events_pkey         101 MB  (idx_scan 0)         ← PK on id = gen_random_uuid() (random UUIDv4)
ix_ingestion_events_content_sha256  9.4 MB
```
The PK is `gen_random_uuid()` (random UUIDv4) — random insertion points cause btree bloat, and with vacuum locked out the indexes never get cleaned, so both 101 MB indexes carry mostly dead/empty space. (Also a latent violation of project Rule #6 — UUIDv7 via `common.ids.new_uuid7()`.)

---

## The exact code paths

### A. Dead-tuple source — base consumer rollback after the idempotency INSERT
`libs/messaging/src/messaging/kafka/consumer/base.py`, `_handle_message`, lines ~1010–1070:
```python
async with await self.get_unit_of_work() as uow:
    try:
        async with asyncio.timeout(timeout_s):           # 45 s watchdog
            await self.process_message(key, value, headers)  # inserts ingestion_events row early
        await uow.commit()
        await self.mark_processed(event_id)
    except TimeoutError as timeout_exc:
        ...
        await uow.rollback()      # ← aborts the ingestion_events INSERT → 1 dead tuple
    except Exception:
        await uow.rollback()      # ← same
        raise
```
The insert happens at the top of `process_message`:
`services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py`, `_process_message_inner`, lines 342–351:
```python
if sha256 and await uow.ingestion_events.exists_by_content_hash(sha256, _DATASET_TYPE):
    await uow.ingestion_events.create_if_not_exists(event_id, _DATASET_TYPE, sha256 or None)
    return
is_new = await uow.ingestion_events.create_if_not_exists(event_id, _DATASET_TYPE, sha256 or None)
```
`create_if_not_exists` (`ingestion_event_repo.py:53-67`) is `INSERT … ON CONFLICT DO NOTHING RETURNING id`. Because it runs *before* the bulk of section/metric writes, **any** later failure (S3 timeout, malformed payload, 45 s watchdog, asyncpg blip) rolls it back → dead tuple. The same shape applies to every market-data consumer that writes `ingestion_events` first (ohlcv, quotes, insider, prediction, intraday).

> Note: the F-004 fix (commit `a17665249`) already corrected the *separate* leak where `store_failure` / `_dead_letter_impl` wrote via the stale, already-rolled-back UoW and left the backend idle-in-tx. Those now use a fresh committed `async with self._uow_factory() as uow`. That fix is in place and is **not** the residual problem here.

### B. Live idle-in-tx / xmin pin #1 — fundamentals consumer holds the write tx for the whole message
Same `_handle_message` block: the UoW transaction is open from the first DB call in `process_message` until `uow.commit()`. `_process_message_inner` does, *inside that one transaction*: the dedup INSERT, `find_by_symbol_exchange`, instrument upsert, then a loop over every fundamentals section calling `handler(record)` **and** `_upsert_metrics_for_record` (an `upsert_metrics` round-trip) per row, then `_upsert_fundamentals_snapshot` which issues an extra `SELECT AVG(volume) … ohlcv_bars` and a `fetch_next_earnings_date` query. For a multi-section EODHD payload that is hundreds of sequential round-trips plus CPU-bound `extract_metrics` — up to the 45 s watchdog. Throughout, the backend is `idle in transaction` whenever Python is computing between round-trips, holding `backend_xmin` for 30+ s (observed). This is the horizon pin on `market_data_db`.

### C. Live idle-in-tx / xmin pin #2 — scheduler 2 102-policy mega-transaction
`services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py`, `execute()`, lines 116–165: one `async with self._uow:` wraps the whole tick. `list_enabled()` (`policy_repository.py:51`) returns **2 102 enabled policies**; the code then loops issuing `watermarks.get_or_create` (SELECT + maybe INSERT) and `tasks.has_active_task` (SELECT) **per policy**, plus a `budgets.get_for_update` (`SELECT … FOR UPDATE`) per provider, and only `commit()`s at the very end. That is ~4 000+ sequential round-trips in a single transaction → the 47–62 s idle-in-tx window seen in `pg_stat_activity` (`SELECT polling_policies …` as the last statement). UoW (`market_ingestion/infrastructure/db/unit_of_work.py`) is otherwise correct (rollback on exception, sessions always closed) — the defect is transaction *duration/scope*, not a missing close.

---

## How the deadlock formed (timeline reconstruction)

1. A past DLQ/abort storm (timeouts + ~29 % api_error retries + schema-evolution waves) inserted-then-rolled-back a very large number of `ingestion_events` rows. At peak the table held ≈1 M tuples (live + dead).
2. A vacuum/analyze around that peak recorded `reltuples ≈ 1.04 M` into `pg_class`.
3. The long idle-in-tx transactions (B and C) repeatedly pinned the xmin horizon, so vacuums during those windows were no-ops and couldn't shrink the table or refresh `reltuples` downward.
4. The workload normalised to ~20 k live rows, but `reltuples` stayed at 1.04 M.
5. From then on every autovacuum trigger (dead-tuple, insert, analyze) computes its threshold from the inflated `reltuples`, so none ever fire on this table — including the autoanalyze that would correct `reltuples`. Permanent lock-out; bloat only grows.

---

## Long-term fix (layered — design only, NOT applied)

### (a) Code fix #1 — stop generating dead tuples: insert the idempotency row in its OWN committed sub-transaction *before* the heavy work, OR mark it processed only on success via a separate path
The cheapest robust change: keep the dedup *check* inside the message transaction, but perform the dedup-row **insert + commit in a short, separate transaction up front** so a later rollback of the heavy work cannot abort it. Concretely, in the market-data consumers, do the `create_if_not_exists` via `async with self._uow_factory() as uow: … await uow.commit()` (same pattern already used by the F-004 `store_failure` fix), then run section/metric writes in the main per-message UoW. Trade-off: a crash between the dedup commit and the data commit would skip reprocessing — acceptable because the message is redelivered and the dedup row already records it; if exactly-once data matters, gate on a `processed_at` column set only after the data commit instead. This removes the dominant dead-tuple source for an INSERT-only table.

### (b) Code fix #2 — shrink the xmin-pinning transactions
- **Fundamentals consumer (path B):** move the CPU-bound `extract_metrics` and the best-effort snapshot side-queries (`AVG(volume)`, `fetch_next_earnings_date`) *outside* the open write transaction, or commit section writes in bounded batches so no single transaction spans 30–45 s. Also confirm `_upsert_fundamentals_snapshot`'s side SELECTs run on the read replica session, not the write session, so they don't extend the write tx.
- **Scheduler (path C):** chunk the tick — read `list_enabled()` (read replica, R27 `ReadOnlyUnitOfWork`), release that transaction, then enqueue in batches each in its own short write transaction (e.g. 200 policies per commit). This caps any single transaction to sub-second and removes the 47–62 s `ingestion_db` xmin pin. The `budgets … FOR UPDATE` should be its own brief transaction per provider.

### (b′) Read paths must use the read-only UoW (R27)
The scheduler's policy scan is read-only and should run on `ReadOnlyUnitOfWork` (read replica) so it never holds a *write* snapshot. Audit other long read loops for the same.

### (c) Backstop — `idle_in_transaction_session_timeout`
Set a cluster (or per-role) `idle_in_transaction_session_timeout` (e.g. `60s`, comfortably above the 45 s consumer watchdog, or a per-role value: short for the API/scheduler roles, longer for the consumer role) so any *genuinely leaked* transaction is force-aborted and stops pinning the horizon. This is a safety net, not the fix — the consumer's legitimate 45 s transaction must stay under it, which argues for (b) first.

### (d) Per-table aggressive autovacuum + break the reltuples deadlock
Even after (a)/(b), the table will not self-heal until `reltuples` is corrected, because the daemon is locked out by the stale stat. Plan:
1. **One-off `ANALYZE ingestion_events;`** — recomputes `reltuples` to the real ~20 k, which immediately re-enables the dead-tuple/insert/analyze triggers. (Cheap, no lock beyond a brief sample; do this even before the VACUUM FULL in (e) — it is the single highest-leverage one-liner.)
2. Set per-table storage parameters so it stays aggressive and never re-locks:
   ```sql
   ALTER TABLE ingestion_events SET (
     autovacuum_vacuum_scale_factor = 0.05,
     autovacuum_vacuum_threshold = 1000,
     autovacuum_vacuum_insert_scale_factor = 0.05,
     autovacuum_analyze_scale_factor = 0.02,
     autovacuum_analyze_threshold = 1000
   );
   ```
   Lower scale factors keep the trigger proportional to the *real* size and make autoanalyze run often enough that `reltuples` can never drift 52× again.

### (e) One-off reclaim of the 419 MB
After the `ANALYZE`, the 208 MB heap + 212 MB index bloat is still allocated. Options, in order of preference:
- **`VACUUM (FULL, ANALYZE) ingestion_events;`** — fully reclaims heap *and* rebuilds the indexes (kills the 101 MB random-UUID index bloat). Takes an `ACCESS EXCLUSIVE` lock for the duration; on 419 MB it is seconds-to-low-minutes. Run in a maintenance window with the market-data consumers paused (so no INSERT blocks on the lock). **Recommended.**
- Non-blocking alternative if a window is hard: `pg_repack` (online) or `REINDEX INDEX CONCURRENTLY` on the two 101 MB indexes + a plain `VACUUM` — reclaims most space without the exclusive lock, at higher operational cost.
- Do **not** rely on a plain `VACUUM` alone: it returns free space to the table's free-space map but does not shrink the 419 MB on disk and does not rebuild the bloated indexes.

### (f) Treat it as a bounded event log — retention / partitioning
`ingestion_events` is a pure idempotency/event log that grows without bound (68 k inserts and counting). Add a retention strategy so it cannot regrow to multi-hundred-MB:
- Partition by `occurred_at` (monthly range partitions) and `DROP` partitions older than the redelivery/dedup window (dedup only needs to recognise recent event_ids; weeks-to-months is ample). Dropping a partition is instant and never produces dead tuples.
- Or a scheduled `DELETE … WHERE occurred_at < now() - interval 'N days'` followed by autovacuum — simpler but reintroduces UPDATE/DELETE churn, so partitioning is preferred.
- Independently, switch the `id` PK default from `gen_random_uuid()` (random UUIDv4) to `common.ids.new_uuid7()` (Rule #6) so future index growth is append-friendly and far less prone to btree bloat.

---

## Priority order for remediation
1. **`ANALYZE ingestion_events;`** (one line, re-enables autovacuum immediately — fixes the lock-out).
2. **`VACUUM (FULL, ANALYZE) ingestion_events;`** in a maintenance window (reclaims the 419 MB + rebuilds indexes).
3. **Per-table aggressive autovacuum** settings (d.2) so it never re-locks.
4. **Code fix (a)** — commit the dedup row up front so rollbacks stop minting dead tuples.
5. **Code fix (b/b′)** — chunk the scheduler tick and shorten the consumer write transaction to remove the 30–62 s xmin pins.
6. **Backstop (c)** — `idle_in_transaction_session_timeout`.
7. **Retention/partition + UUIDv7 PK (f)** — long-term bound on growth.

Items 1–3 are operational (covered by `/migrate-db` or a DBA runbook). Items 4–7 are code changes; route 4/5 through `/fix-bug` or `/implement` with regression tests asserting (i) no `ingestion_events` dead tuple after a forced consumer failure and (ii) the scheduler tick holds no transaction longer than the batch size.
