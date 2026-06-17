# OHLCV Materialize Concurrency — Audit

**Date:** 2026-06-16
**Scope:** `services/market-data` OHLCV micro-batch consumer
**Mode:** READ-ONLY investigation (live containers up). No code/schema/data changes.
**Question:** After the micro-batch change (parallel S3 prefetch + *serial* per-message materialize), is serial materialize the right choice or the new throughput bottleneck? Would parallelizing the materialize exhaust Postgres? What is the correct concurrency model and safe K?

---

## TL;DR / Recommendation

**Keep the materialize SERIAL. Do not parallelize it.** The serial loop is *not* the
bottleneck, and parallelizing would buy almost nothing while complicating the
contiguous-offset-commit semantics and adding Postgres session pressure.

Evidence in one line: live per-message materialize cost is **p50 = 36 ms, p90 = 100 ms,
mean = 95 ms** — i.e. one batch of 50 messages serially costs **~2-5 s of DB work**, and
the expensive part (the slow S3 GET) is *already* parallelized across the batch. The DB is
fast and is the floor; serial already drains the batch comfortably inside the 600 s poll
interval (>100x margin), so the win is already captured by S3-parallel + batched commit.

If a future load profile ever makes the serial DB phase the bottleneck (it is not today),
the correct next step is **bounded concurrency with `asyncio.Semaphore(K=4)`**, *not* full
`asyncio.gather`. Formula and rationale below. At K=4 with the planned 6 replicas the worst
case is **48 sessions** against a `max_connections=500` cluster currently at 30% — safe.

---

## 1. Postgres connection capacity (live)

```
SHOW max_connections;            -> 500
total backend connections now    -> 152   (30.4% of max)
```

Per-state:

| state | count |
|---|---|
| idle | 136 |
| idle in transaction | 6 |
| active | 2 |
| (background) | 6 |

Per-application (Postgres is **shared by all services — one container, many DBs**):

| application_name | conns |
|---|---|
| nlp-pipeline | 70 |
| **market-data** | **23** |
| knowledge-graph | 21 |
| market-ingestion | 7 |
| content-ingestion | 6 |
| portfolio | 5 |
| alert | 4 |
| content-store | 4 |
| rag-chat | 1 |
| (TimescaleDB bg workers) | 2 |

Per-DB: `intelligence_db` 53, `nlp_db` 38, `market_data_db` 23, others ≤7.

**Headroom: ~348 free connections (70%).** Plenty today, but the budget is *shared*. Any
per-consumer concurrency multiplier (K × replicas) must be sized against this shared pool,
not against market-data in isolation. nlp-pipeline alone already holds 70.

---

## 2. market-data SQLAlchemy pool config

`services/market-data/src/market_data/infrastructure/db/session.py`:

```python
create_async_engine(..., pool_size=20, max_overflow=30, pool_timeout=60, pool_recycle=300,
                    pool_pre_ping=True, application_name="market-data")
```

Two engines are built (write + read), **each with pool_size=20 + max_overflow=30 = 50 max
connections**. So per market-data *process*: up to **100 PG connections** (50 write + 50 read)
before the pool blocks.

**Critical detail — each materialize opens TWO connections, not one.** `SqlAlchemyUnitOfWork.__aenter__`
(`infrastructure/db/uow.py:114`) opens **both** a write session and a read session:

```python
self._write_session = self._write_factory()
self._read_session  = self._read_factory()
```

The OHLCV consumer materialize path only uses the write session (all repos are built from
`self._write()`), but the read session is still checked out for the UoW's lifetime. So:

> **1 concurrent materialize = 1 UoW = 2 checked-out pool connections (1 write + 1 read).**

**Process/replica count:** the ohlcv-consumer runs as its **own** container
(`market-data-ohlcv-consumer`, compose entry `infra/compose/docker-compose.yml:871`),
single replica today (no `deploy.replicas`). It is a **single-threaded asyncio event loop**,
so even though the pool allows 50, the *serial* loop only ever checks out **2** connections
at a time (the live `market-data` total of 23 is the sum of *all* market-data containers:
api, dispatcher, and the 6 consumer containers each with their own pool, mostly idle).

If the ohlcv-consumer materialized **N messages concurrently**, it would open **2N**
connections from its own pool. With pool_size+max_overflow = 50 per engine, the pool can
satisfy up to N=20 from the steady pool and N≤50 with overflow before `pool_timeout=60`
blocks — so the *pool* would not be the first limiter; the shared cluster budget would be.

---

## 3. What one materialize actually costs — DB-bound, single dominant statement

Read path of `_materialize` (`ohlcv_consumer.py:285`). DB round-trips per message:

1. `ingestion_events.exists_by_content_hash(sha256)` — SELECT (dedup)
2. `ingestion_events.create_if_not_exists(...)` — INSERT … ON CONFLICT DO NOTHING RETURNING
3. `instruments.find_by_symbol_exchange(...)` — SELECT
4. (new instrument only) `securities.upsert` + `instruments.upsert` + `outbox_events.create` — 3 writes (rare; once per symbol lifetime)
5. **`ohlcv.bulk_upsert_with_priority(domain_bars)`** — **ONE** `INSERT … VALUES(<all bars>) ON CONFLICT DO UPDATE` (`ohlcv_repo.py:86-105`) — the dominant statement (87-1054 rows in one round-trip)
6. (1m + fresh only) `quotes.upsert_if_newer` + cache fan-out — 1 write + post-commit hook
7. `uow.commit()` — COMMIT

So the steady-state hot path is **~4-5 small queries + 1 bulk upsert + 1 commit ≈ 6-7
round-trips**, of which the bulk upsert is the cost center (it carries 100-1000+ rows).

**Live measurement (from consumer logs, 299 consecutive `materialized` events):**

```
min=7ms  p50=36ms  p90=100ms  p99=3032ms*  max=3100ms*  mean=95ms
(* p99/max are the GAP BETWEEN BATCHES — next poll + S3 prefetch wait — not single-message DB time)
```

This **directly contradicts the "~3 s/message worst case"** claimed in the
`_DEFAULT_BATCH_MAX` docstring (`ohlcv_consumer.py:72`). Real per-message DB cost is
**tens of milliseconds**, dominated by the single bulk-upsert statement. The "3 s" figures
are inter-batch idle, not work.

**Implication:** the cost is DB-bound on **one bulk statement per message**. Parallel
sessions would therefore contend on the *same* write path (PK `ohlcv_bars_pkey` =
`(instrument_id, timeframe, bar_date)` + 5 secondary indexes; `\d ohlcv_bars`), and each
upsert must maintain **6 indexes**. Within one batch, messages are *different instruments*
(different PK ranges) so row-locks rarely collide — but they share buffer/WAL/index-maintenance
pressure, so parallel sessions give **sub-linear** speedup on an already-fast operation.

---

## 4. Concurrency model trade-offs

`ohlcv_bars` is a TimescaleDB hypertable (1 dimension, 15 chunks live). Concurrent upserts
to **different** chunks/instruments don't contend on row locks; same-chunk upserts to
*different* PKs take separate row locks (no contention) but share index-leaf-page latches.
Upserts to the *same* (instrument, tf, bar_date) would serialize on the row lock — but that
never happens within a batch (one message per instrument/timeframe window).

| Model | Throughput ceiling | PG sessions (this consumer) | Lock/index contention | Commit semantics |
|---|---|---|---|---|
| **(a) Serial (current)** | batch_drain ≈ Σ per-msg ≈ 50 × ~50 ms ≈ **2-5 s/batch**; bounded by single event loop | **2** (1 write + 1 read) | none | **Trivial** — process in offset order, `break` on first failure, commit highest contiguous offset. Already implemented (`_process_batch:657-700`). |
| **(b) Bounded `Semaphore(K)`** | ~K× the serial DB phase, sub-linear (shared WAL/index) → realistically ~2-3× at K=4 | **2K** | low (different instruments/chunks); shared index-leaf latches | **Harder** — can't `break` on first failure; must `gather` all, then compute the contiguous-success prefix from results and commit that. Requires rewriting the per-partition loop. |
| **(c) Full `gather` over batch** | bounded by pool/DB, not loop | **2 × batch_max (up to 100 at batch=50)** | higher index-leaf + WAL flush contention; risks `pool_timeout` | **Hardest** + worst PG pressure. Single replica could alone hold 100 connections; 6 replicas → 600 > max_connections=500. **Unsafe.** |

**Interaction with contiguous-offset-commit + partial failure (the load-bearing constraint):**
the current serial loop relies on `break`-on-first-failure to define "highest contiguous
succeeded offset" (`ohlcv_consumer.py:676-688`). Any parallel model destroys this: you must
await *all* concurrent materializes, then walk the per-partition offset-sorted results and
commit up to the first failure. This is doable but is a real correctness rewrite — and a
common source of off-by-one/over-commit bugs (committing past a failed-but-concurrently-succeeded
later offset → silent data loss on that partition). The serial model gets this for free.

**Interaction with planned 6-replica scaling:** Kafka assigns partitions to replicas, so 6
replicas materialize *different* partitions in parallel **for free** — that is already 6×
parallelism at the partition granularity with **zero** added per-consumer sessions (each
replica is still serial = 2 connections). This is the right axis to scale on. Per-message
concurrency *multiplies on top*: 6 replicas × 2K. At full `gather` (model c) that is
6 × 100 = **600 connections > max_connections (500)** → cluster exhaustion, especially with
nlp-pipeline's 70 + everything else. Bounded K=4: 6 × 2×4 = **48** — safe.

---

## 5. Recommendation (concrete + quantified)

**Verdict: serial is correct today. The throughput win is already captured by
(1) parallel S3 prefetch and (2) batched single-commit + once-per-batch lag.** The DB is the
floor at ~36-100 ms/message and is not saturated. Adding materialize concurrency would
trade a real correctness simplification (free contiguous-commit) for a sub-linear speedup on
an operation that is not the bottleneck.

**Scale on the replica/partition axis first** (the planned 6 replicas): it gives 6×
throughput with **no** added per-consumer connections and keeps each consumer's commit logic
trivially serial. Ensure the topic has ≥6 partitions for the OHLCV dataset so 6 replicas can
each own one.

**Only if** post-6-replica profiling shows the serial DB phase (not S3, not poll-wait) is the
bottleneck, introduce **bounded concurrency** — never full `gather`:

- **Code site:** `_process_batch`, Phase 2 per-partition loop (`ohlcv_consumer.py:657-700`).
  Replace the serial `for msg in part_msgs` with `asyncio.gather` over an
  `asyncio.Semaphore(K)`-guarded `_handle_message`, then compute the contiguous-success
  prefix from the gathered results (per partition, offset-sorted) and commit that offset.
  Keep the per-partition grouping so the contiguous barrier stays well-defined.
- **Safe K formula** (tie K to pool and the 6-replica fan-out; remember **2 connections per UoW**):

  ```
  total_ohlcv_sessions = K × 2 × replicas
  constraint:  total_ohlcv_sessions  ≤  safe_fraction × (max_connections − other_services_peak)

  with max_connections = 500, other services peak ≈ 150 (nlp 70 + kg 21 + … + headroom),
  safe budget for the ohlcv fleet ≈ 100 connections:

      K × 2 × 6  ≤  100   →   K ≤ 8
  ```

  **Recommended K = 4** (not the ceiling): 4 × 2 × 6 = **48 sessions** for the whole ohlcv
  fleet — ~10% of the cluster, leaving generous headroom for nlp-pipeline and every other
  service, and staying well inside market-data's per-process pool (50/engine). K=4 also keeps
  the contiguous-prefix recompute small and the index-leaf/WAL contention low enough to stay
  near-linear.

- **Also fix the stale docstring** (`ohlcv_consumer.py:62-76`): the "~3 s/message worst case"
  is wrong by ~30-80×; measured worst-case single-message DB cost is ~100 ms (p90). The
  3 s figures are inter-batch idle. The batch_max safety argument should be re-derived from
  ~100 ms/message (50 × 100 ms = 5 s ≪ 600 s poll interval — even a 50× larger batch is safe
  on the heartbeat constraint, so heartbeat is *not* the binding limit; throughput/commit
  granularity is).

---

## Evidence index

- `max_connections=500`, 152 live (30%); per-app/per-DB tables — live `pg_stat_activity` (2026-06-16).
- Per-message timing p50=36ms/p90=100ms/mean=95ms — 299 consecutive `ohlcv_consumer.materialized` log deltas.
- Pool config (50/engine, 2 engines) — `infrastructure/db/session.py:19-52`.
- 2 connections per UoW — `infrastructure/db/uow.py:114-117`.
- UoW-per-message lifecycle — `libs/messaging/.../consumer/base.py:750-757`.
- Serial loop + contiguous commit + break-on-failure — `ohlcv_consumer.py:596-700`.
- Parallel S3 prefetch (already done) — `ohlcv_consumer.py:625-655`.
- Bulk upsert = one statement, 6 indexes — `ohlcv_repo.py:56-105`; `\d ohlcv_bars`.
- Single-replica own container — `infra/compose/docker-compose.yml:871-893` (no `deploy.replicas`).
- Hypertable, 15 chunks — `timescaledb_information.{hypertables,chunks}`.
