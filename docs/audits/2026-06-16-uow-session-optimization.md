# UoW Session Optimization for the OHLCV Consumer — Audit

**Date:** 2026-06-16
**Scope:** `services/market-data` — `SqlAlchemyUnitOfWork` session usage in the OHLCV micro-batch consumer
**Mode:** READ-ONLY investigation (live containers up). No code/schema/data changes, no git ops.
**Question:** The throughput floor is *Postgres SESSION COUNT*, not CPU/DB-time. Each materialize opens **2 sessions** (write + read). Scaling replicas multiplies this. Reduce sessions PER materialize and optimize session usage so 6-replica scaling stays safely under `max_connections=500`.

---

## TL;DR / Recommendation

**Two complementary changes, ranked by leverage/effort/risk:**

1. **(Highest value, lowest risk) Make the read session lazy** in `SqlAlchemyUnitOfWork.__aenter__`
   (`infrastructure/db/uow.py:114-117`). The OHLCV write-path **never touches the read session** —
   every repo it uses binds to the *write* session (verified below). Today that read session is opened
   eagerly and held idle for the entire UoW lifetime: **pure overhead**. Opening it lazily (only when a
   `*_read` accessor is first used) cuts the consumer from **2 → 1 session per materialize** with zero
   behavior change for any write path, and zero change for API readers (they hit a `*_read` accessor and
   trigger the lazy open). This is a ~5-line change in one shared method.

2. **(Highest *structural* leverage) One UoW/session per BATCH with per-message SAVEPOINTs** instead of
   one UoW per message. Combined with (1) this takes a 50-message batch from **2 × 50 = 100 session-checkouts**
   down to **1 session for the whole batch**, while preserving per-message partial-failure isolation
   (a poison message rolls back to its savepoint, not the batch) *and* the contiguous-offset commit. This
   is a larger, correctness-sensitive change (it requires moving the UoW boundary out of the base
   `_handle_message` into the consumer's `_process_batch`), so do it **second**, after (1) lands and the
   6-replica scaling is validated.

**Why this matters more than bounded-K (the prior audit's recommendation):** the prior report
(`2026-06-16-ohlcv-materialize-concurrency.md`) correctly concluded serial materialize is fine for
*throughput* and that bounded-K concurrency is the lever *if* DB-time ever becomes the bottleneck. But
the user's insight reframes the constraint: the binding limit at fleet scale is **session count**, and
the cheapest win is not adding concurrency — it is **removing the unused second session** and
**amortizing the UoW across the batch**. Both *reduce* sessions; bounded-K *adds* them.

---

## 1. Does the OHLCV materialize use the read session? — **No. Never.**

Traced every UoW call in `_materialize` (`ohlcv_consumer.py:285-518`) against the repository wiring in
`SqlAlchemyUnitOfWork` (`infrastructure/db/uow.py:199-324`):

| `_materialize` call | UoW accessor | Session it binds to | Source |
|---|---|---|---|
| `exists_by_content_hash` / `create_if_not_exists` | `uow.ingestion_events` | **write** (`self._write()`) | uow.py:239-242 |
| `find_by_symbol_exchange` / `upsert` / `update_flags` | `uow.instruments` | **write** | uow.py:208-211 |
| `securities.upsert` | `uow.securities` | **write** | uow.py:202-205 |
| `outbox_events.create` | `uow.outbox_events` | **write** | uow.py:251-254 |
| `ohlcv.bulk_upsert_with_priority` | `uow.ohlcv` | **write** | uow.py:214-217 |
| `quotes.upsert_if_newer` | `uow.quotes` | **write** | uow.py:220-223 |
| `failed_tasks.create` (failure path) | `uow.failed_tasks` | **write** | uow.py:245-248 |

**Every accessor used in the materialize path is a write-side accessor bound to `self._write()`. The
consumer never calls any `*_read` accessor, never calls `get_read_session()`, never calls `_read()`.**

Confirmed at the wiring level too: the `*_read` accessors (`instruments_read`, `ohlcv_read`,
`quotes_read`, …, uow.py:286-324) are the *only* call sites of `self._read()`, and `grep` shows the OHLCV
consumer references none of them.

> **Conclusion:** the read session opened in `__aenter__` for every materialize is **checked out and held
> idle for the UoW's entire lifetime, then closed unused**. It is pure overhead — exactly the "2 sessions
> per materialize" the prior audit flagged, with the second one doing nothing in this code path.

This is true for *every* write-path consumer in market-data (quotes, fundamentals, insider, prediction,
intraday-resampling), since each builds the same dual-session `SqlAlchemyUnitOfWork`
(`*_consumer_main.py`, all `return SqlAlchemyUnitOfWork(write_factory, read_factory)`). The waste
generalizes across the whole consumer fleet, not just OHLCV.

---

## 2. How the two sessions are created

`SqlAlchemyUnitOfWork.__aenter__` (`infrastructure/db/uow.py:114-117`):

```python
async def __aenter__(self) -> SqlAlchemyUnitOfWork:
    self._write_session = self._write_factory()   # eager
    self._read_session  = self._read_factory()    # eager — opened even if never used
    return self
```

**Both sessions are opened EAGERLY**, unconditionally, on context entry. (Note: a SQLAlchemy
`AsyncSession` created by the sessionmaker does not check out a DBAPI connection until first I/O — but the
materialize *commits* the write session and the `__aexit__` *closes* both, and under load each session
holds a pooled connection for the bulk of the UoW lifetime. The read session, having issued no I/O, is
the cheaper of the two, but it still occupies a session object and is closed via an extra `close()` round
in `__aexit__` (uow.py:129-130). More importantly, the *intent and accounting* the prior audit used — "2
checked-out connections per UoW" — holds whenever the read session does any work; for this consumer it
does none, so removing it is strictly safe.)

**Same DB, no replica configured.** Live verification:

- `MARKET_DATA_READ_REPLICA_URL` is **not set** in `worldview-market-data-ohlcv-consumer-1`
  (only `MARKET_DATA_DATABASE_URL=postgresql+asyncpg://postgres:postgres@timescaledb:5432/market_data_db`).
- `build_read_engine` (`session.py:34-52`) falls back to `settings.database_url` when `read_replica_url`
  is `None` (config.py:31). So **both engines point at the same `timescaledb:5432/market_data_db`.**

> The second session is **two connections to the SAME Postgres**, not a replica offload. Locally there is
> no read/write split at all — the split exists only in code, dormant until a replica URL is configured.

**Per-process connection ceiling** (`session.py:19-52`): each engine is
`pool_size=20, max_overflow=30` → **50 max connections per engine**, **100 per process** (write+read),
`pool_timeout=60`, `pool_recycle=300`, `pool_pre_ping=True`. No `NullPool`.

**Live cluster picture (2026-06-16):**

```
SHOW max_connections;                              -> 500
total backends (all DBs)                           -> 135
application_name='market-data' (all containers)    -> 25   (23 idle, 0 active, 2 bg)
```

25 connections is the sum across ~9 market-data containers (api, outbox-dispatcher, and 7 consumer
containers), each with its own 100-connection-capable pool but almost entirely idle — confirming the
single-threaded serial loop in each consumer only ever holds a tiny handful. The pool is **not** the
limiter today; the *shared 500-connection cluster budget* is the thing the fleet math must respect.

---

## 3. Optimization options for the write-only consumer path

### (a) Lazy read-session acquisition — **RECOMMEND (do first)**

Open `self._read_session` only when `_read()` is first called:

```python
async def __aenter__(self):
    self._write_session = self._write_factory()
    # read session created lazily in _read()
    return self

def _read(self):
    if self._read_session is None:
        self._read_session = self._read_factory()
    return self._read_session
```

(Note `_read()` already raises "not entered" today via the `None` check — that guard must move to a
separate "entered" flag, or be dropped in favor of the lazy-create, so the not-entered error is still
distinguishable. Trivial.)

- **Effect on OHLCV consumer:** read session is never accessed → **2 → 1 session per materialize.** Same
  for every write-only consumer.
- **Blast radius:** `_read()`/`get_read_session()`/all `*_read` accessors are shared by ALL market-data
  use cases. Anything that *uses* a read accessor still gets a session — lazily, on first access — so API
  readers and any mixed read+write use case are unaffected (the read session simply materializes when
  touched). **Nothing relies on the read session existing eagerly:** the only eager touch is the unused
  `__aenter__` open and the `__aexit__` close, both of which already null-guard
  (`if self._read_session and self._read_session is not self._write_session`). `SqlAlchemyReadOnlyUnitOfWork`
  is unaffected (separate class, single session already). **Risk: very low.** Recommend a unit test
  asserting the read session stays `None` after a write-only UoW lifecycle.

### (b) A write-only UoW variant (single session)

R23/R27 give a *read-only* `SqlAlchemyReadOnlyUnitOfWork` (uow.py:327, single read session). There is
**no symmetric write-only single-session UoW** today. Per finding #1, no materialize call would need to
move off the read session — they are *all already on the write session* — so a `WriteOnlyUnitOfWork` that
simply omits `__aenter__`'s read open and drops the `*_read` accessors would be a drop-in for the OHLCV
consumer's factory.

- **Effect:** **2 → 1 session per materialize**, same as (a).
- **Trade-off vs (a):** (b) is a new class + new ABC + per-consumer factory rewiring (more surface, more
  tests, a 3rd UoW type to maintain). (a) achieves the identical session reduction for the consumer with
  **one shared method change and zero new types**, and *also* benefits any future write path that happens
  not to read. **Prefer (a) over (b).** (b) is only worth it if you want a *type-level* guarantee that a
  consumer cannot accidentally read (symmetry with R27) — a nice-to-have, not a session win on top of (a).

### (c) Pool sizing — **RECOMMEND (cheap, do alongside (a))**

The per-engine `pool_size=20 + max_overflow=30 = 50` is wildly oversized for a single-threaded serial
consumer that checks out 1-2 connections. With 6 replicas each owning a 50/engine × 2-engine = 100-cap
pool, the *theoretical* ceiling is 600 connections per consumer type — already over `max_connections=500`
before counting nlp-pipeline's ~70 and everyone else. Right-size **per consumer process**:

```
pool_size = 2, max_overflow = 3   # serial loop never needs more; +headroom for the lag/retry tasks
```

Tie to the fleet math (section 4) so `replicas × per_process_cap ≤ safe budget`. This caps the *blast
radius* of any future bug (e.g. a leaked session) and makes the per-process footprint legible. Combined
with lazy-read, the read engine should get a tiny pool too (or be skipped entirely for write-only
consumers under option (b)).

### (d) pgbouncer in transaction mode — feasible, but not the first lever

A transaction-mode pooler would let many consumer *client* sessions share few PG *backends*, decoupling
"sessions per materialize" from "PG backends consumed" — directly attacking the ceiling the user
identified. **Caveats:**
- **asyncpg + transaction-mode pgbouncer = prepared-statement hazard.** asyncpg caches server-side
  prepared statements per connection; transaction pooling reassigns backends mid-session, so cached
  statement names collide ("prepared statement does not exist"/"already exists"). Mitigation:
  `statement_cache_size=0` on the asyncpg connect args (and/or `prepared_statement_name_func`), which
  costs some plan-caching benefit.
- Adds an operational component (HA, monitoring, a new failure mode) to the stack.
- **Verdict:** high *ceiling* leverage, but higher effort/risk than (a)+(e), and orthogonal to them. Keep
  it as the **scale-out escape hatch** once the cheap in-process wins (a/c/e) are exhausted, or if you
  deploy a real read replica and want both primary and replica fronted by a pooler.

### (e) One session per BATCH with per-message SAVEPOINTs — **RECOMMEND (highest structural leverage, do second)**

The consumer already micro-batches (`run()`/`_process_batch`, ohlcv_consumer.py:522-707) but still opens
**one UoW per message** inside the base `_handle_message` (base.py:750 `async with await
self.get_unit_of_work() as uow:`). A 50-message batch therefore opens **50 UoWs sequentially** (50 ×
{write+read}, or 50 × write after option (a)). Replacing this with **one UoW/session for the whole batch**
+ a **SAVEPOINT per message** collapses that to **1 session for the entire batch**.

**Savepoint semantics & isolation:** SQLAlchemy exposes `AsyncSession.begin_nested()` (emits `SAVEPOINT`).
Per message:

```python
async with batch_uow:                     # ONE session for the whole batch
    for msg in part_msgs_sorted_by_offset:
        sp = await session.begin_nested()  # SAVEPOINT
        try:
            await materialize(msg)
            await sp.commit()              # RELEASE SAVEPOINT (still inside outer txn)
            last_committable_offset = msg.offset()
        except ConsumerError:
            await sp.rollback()            # ROLLBACK TO SAVEPOINT — only this msg undone
            await handle_failure(msg)
            break                          # contiguous barrier preserved
    await batch_uow.commit()              # ONE COMMIT for the whole contiguous prefix
```

- **Partial-failure isolation is preserved:** a poison message's `ROLLBACK TO SAVEPOINT` undoes only that
  message's writes; everything committed-to-savepoint before it survives in the outer transaction. This is
  the same guarantee the per-message UoW gives, at savepoint granularity.
- **Contiguous-offset commit interaction:** today the per-partition loop (`_process_batch:658-700`)
  already does `break`-on-first-failure and commits `last_committable_offset + 1`. With the batch-UoW the
  loop is *identical* in shape — the only change is the transaction boundary moves outward and each
  iteration wraps in a savepoint. The Kafka offset commit (`_consumer.commit`) MUST happen **after**
  `batch_uow.commit()` succeeds (DB durable first, then offset), so the existing ordering still holds:
  `break` defines the contiguous prefix, DB commits that prefix's writes, then the offset is committed.
- **Repos support savepoints for free:** every repo takes a bare `AsyncSession` (verified:
  `ohlcv_repo.py:31`, `instrument_repo.py:24`, `ingestion_event_repo.py:20`) and issues statements on it;
  `begin_nested()` is transparent to them. **No savepoint usage exists anywhere in the service today** —
  this is net-new, so it needs careful tests.
- **Caveat — outbox/post-commit hooks & cache fan-out:** `schedule_quote_cache_fanout` and the outbox
  notifier fire on the *outer* `commit()`. Batching means they fire **once per batch** for *all* messages
  in the contiguous prefix, not once per message. The outbox rows are written inside the txn (fine), but
  the post-commit cache fan-out coroutines accumulate across the batch — verify `_post_commit_hooks`
  ordering and that one message's fan-out failure (already isolated per F-DS-015, uow.py:146-151) doesn't
  affect others. This is the main correctness surface to test.
- **Caveat — failure DLQ writes:** `store_failure`/`_dead_letter_impl` write via `self._current_uow.failed_tasks`
  (write session). On a mid-batch failure, the failed-task row must be written and committed *even though*
  we're rolling back that message's savepoint. With a batch-UoW the failed-task insert should go on the
  outer transaction *after* the savepoint rollback (so it survives the commit of the contiguous prefix),
  or in a separate small UoW. This needs explicit handling — it is the subtlest part of the change.
- **Effect:** **50-message batch: 100 sessions (today) → 1 session (with savepoints).** This is the
  single largest reduction available, and it *reduces* rather than *adds* sessions (unlike bounded-K).
- **Risk:** medium — it relocates the UoW boundary out of the shared base path into the consumer override,
  and the DLQ/fan-out edge cases above must be handled. Do it **after** (a).

---

## 4. Quantified sessions vs the 500 ceiling

Baseline: live cluster total **135**, of which **market-data = 25** (≈23 idle). Headroom ≈ **365**. The
ohlcv consumer is **1 replica, serial, 2 sessions/msg** today. Batch size = 50.

Per-materialize / per-batch session demand of the **ohlcv-consumer fleet** (the thing we scale):

| Scenario | sessions per active unit | fleet sessions (this consumer) | vs 500 ceiling (with ~135 baseline) |
|---|---|---|---|
| **Today** (1 replica, serial, 2/msg) | 2 (1 used, 1 idle) | **2** | trivially safe |
| **Serial + lazy-read (a)** (1 replica, 1/msg) | 1 | **1** | trivially safe |
| **6 replicas × 2/msg** (no change) | 2 | **12** | safe, but each *also* keeps a 100-cap pool |
| **6 replicas × 1/msg** (lazy-read) | 1 | **6** | safe |
| **6 replicas × bounded-K=4 × 2/msg** (prior audit's option) | 2K = 8 | **48** | safe but *adds* sessions |
| **6 replicas × bounded-K=4 × 1/msg** (K + lazy-read) | K = 4 | **24** | safe, half the prior plan |
| **6 replicas × batch-savepoint (e)+(a)** | 1 per active batch | **6** | safest at scale |

> The decisive comparison: at **6 replicas**, the prior plan's **bounded-K=4** path costs **48 sessions**;
> **lazy-read alone** costs **6**; **lazy-read + batch-savepoint** also costs **6** while *also* removing
> 49 of every 50 UoW open/close cycles (lower latency, less pool churn). **Lazy-read makes 6-replica
> scaling safe on its own**; batch-savepoint makes it safe *and* cheap; bounded-K should only be layered
> on top *after* lazy-read if DB-time (not sessions) ever becomes the bottleneck — and even then it costs
> half as many sessions once lazy-read removes the idle read session.

**Pool-sizing constraint to enforce regardless of option** (so a leak can't exhaust the cluster):

```
replicas × per_process_pool_cap  ≤  safe_budget
6 × (pool_size + max_overflow)   ≤  ~100      →  per-engine cap ≤ ~16
```

Today's `50/engine` blows this (6 × 100 = 600 > 500). Right-size to `pool_size=2, max_overflow=3`
(per-process write cap = 5; read engine ~0 under lazy-read or omitted under option (b)) → 6 × 5 = **30**
worst-case, well inside budget.

---

## 5. Recommendation (ranked)

| # | Change | Effort | Risk | Session win | Code site |
|---|---|---|---|---|---|
| **1** | **Lazy read-session** in `__aenter__`/`_read` | Tiny (~5 lines, 1 method) | Very low | 2 → 1 per UoW, fleet-wide | `infrastructure/db/uow.py:114-117, 180-189` |
| **2** | **Right-size pools** per consumer process | Tiny (config) | Low | caps blast radius; enables safe 6-replica | `infrastructure/db/session.py:19-52` (or per-consumer engine build) |
| **3** | **One UoW/session per batch + per-message SAVEPOINTs** | Medium | Medium | 2×batch → 1 per batch | move UoW boundary into `ohlcv_consumer.py:_process_batch:658-700`; `AsyncSession.begin_nested()`; handle DLQ + fan-out edge cases |
| 4 | (optional) write-only UoW type | Medium | Low | same as #1 (don't stack) | new class in `uow.py` + ports + `*_consumer_main.py` rewiring |
| 5 | (optional, scale-out) pgbouncer transaction mode | High | Medium | decouples sessions from PG backends | infra + `statement_cache_size=0` |

**The single highest-value change is #1 (lazy read-session).** It directly removes the unused second
session the prior audit identified, with near-zero risk and fleet-wide benefit, and it alone makes
6-replica scaling safe (6 sessions vs the prior plan's 48). **Pair it with #2** (pool right-sizing) so the
per-process footprint is bounded and a future leak cannot exhaust the shared 500-connection cluster.

**#3 (batch-UoW + savepoints) is the highest *structural* leverage** and the right second step once #1 is
in and 6 replicas are validated: it preserves partial-failure isolation (savepoint rollback per message)
and the contiguous-offset commit (unchanged `break`-on-failure + commit `last+1` *after* the single DB
commit), while collapsing a 50-message batch from 100 session-checkouts to **one**. Its risk is confined
to two edge cases that must be tested: (i) the per-message DLQ/failed-task write must survive the contiguous
commit (write it on the outer txn after the savepoint rollback), and (ii) post-commit cache fan-out / outbox
now fire once per batch for the whole contiguous prefix.

**Do NOT lead with bounded-K concurrency.** It *adds* sessions (2K per replica) to solve a DB-time problem
that the prior audit showed does not exist today (p50=36ms, p90=100ms/message). The actual constraint is
sessions, and #1/#3 *reduce* them. Bounded-K is a valid *layer on top* only if post-6-replica profiling
shows the serial DB phase (not S3, not poll-wait) is the bottleneck — and even then, apply it *after* #1
so each concurrent slot costs 1 session, not 2.

---

## Evidence index

- Read session unused in materialize: every accessor in `_materialize` binds to `_write()` — `ohlcv_consumer.py:285-518` cross-referenced with `uow.py:199-282` (write accessors) vs `uow.py:284-324` (`*_read` accessors, none referenced by the consumer).
- Eager dual-session open — `uow.py:114-117`; close both — `uow.py:126-130`.
- No replica configured live: `MARKET_DATA_READ_REPLICA_URL` unset in `worldview-market-data-ohlcv-consumer-1`; `build_read_engine` falls back to `database_url` — `session.py:34-52`, `config.py:31`. Both engines → `timescaledb:5432/market_data_db`.
- Pool config `pool_size=20, max_overflow=30` per engine, 2 engines — `session.py:19-52`.
- Live cluster: `max_connections=500`, 135 total backends, market-data=25 (23 idle, 0 active) — `pg_stat_activity` (2026-06-16).
- UoW-per-message lifecycle in base consumer — `libs/messaging/.../consumer/base.py:750-757`.
- Micro-batch loop + contiguous commit + break-on-failure — `ohlcv_consumer.py:522-707` (Phase 2: 657-700).
- Repos take a bare `AsyncSession` (savepoint-transparent) — `ohlcv_repo.py:31`, `instrument_repo.py:24`, `ingestion_event_repo.py:20`.
- No savepoint/`begin_nested` usage anywhere in market-data today — `grep` over `services/market-data/src`.
- `SqlAlchemyReadOnlyUnitOfWork` already single-session (R27 precedent for a single-session UoW) — `uow.py:327-403`.
- R23 (dual DB URLs / read-write split) and R27 (read-only use cases use `ReadOnlyUnitOfWork`) — `RULES.md:226-248`.
- Prior audit (serial-vs-concurrent, bounded-K) — `docs/audits/2026-06-16-ohlcv-materialize-concurrency.md`.
