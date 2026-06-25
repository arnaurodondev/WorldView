# OHLCV Batch-UoW + Per-Message SAVEPOINT — Design & De-Risking (Option #3)

**Date:** 2026-06-16
**Scope:** `services/market-data` — replace the OHLCV consumer's per-message UoW with ONE UoW/session per micro-batch using per-message SAVEPOINTs (`session.begin_nested()`).
**Mode:** READ-ONLY design investigation. No code/schema/data changes, no git ops.
**Predecessor:** `docs/audits/2026-06-16-uow-session-optimization.md` (Option #3 = section 3(e) there). This document is the deep, implementation-ready design + de-risking for that option.

---

## TL;DR / Verdict

**Do NOT implement Option #3 as the next step. Ship Option #1 (lazy read-session) + pool right-sizing + replicas first; treat #3 as a deferred, conditional optimization.**

The decisive technical findings:

1. **The session-count win of #3 over #1 is essentially zero at this consumer's actual concurrency.** The batch loop is **serial** (Phase 2 processes one partition's messages one at a time, `await self._handle_message(msg)`). With Option #1, each message opens **one** write session, uses it, commits, closes — then the next message opens one. Because the loop is serial, **at most one session is checked out at any instant**, and the SQLAlchemy pool **reuses the same pooled connection** across all 50 messages (the connection is returned to the pool on `close()` and immediately handed back on the next `__aenter__`'s first I/O). So "#1 = 50 checkouts/batch" is 50 *sequential reuses of one connection*, not 50 concurrent connections. #3 collapses that to "1 checkout/batch" — but **1 concurrent connection either way**. The cluster-budget math (the actual constraint per the predecessor audit) is identical: `replicas × 1 concurrent write conn`. #3 saves ~49 `BEGIN/COMMIT` round-trips per batch (latency/pool-churn), not connections.

2. **The current per-message-UoW failure path already has a latent durability bug that #3 would force us to confront, and #3 makes the correct fix *harder*, not easier** (detailed in §3.1). The DLQ/`failed_tasks` write currently executes against an already-closed, rolled-back session and **is never committed** — it does not persist today. Any redesign that touches this path must fix that, and the batch-session model entangles the fix with savepoint-rollback ordering.

3. The savepoint mechanics themselves are sound and have in-repo precedent (`knowledge-graph/.../canonical_entity.py:409` already uses `async with self._session.begin_nested()`). The risk is **not** SQLAlchemy/asyncpg savepoint support; it is the **side-effect and DLQ ordering** around the batch boundary, plus the **cost of re-implementing `_handle_message`'s dedup/metrics/watchdog inline** (because #3 requires bypassing the base per-message UoW).

**Recommendation:** Land #1 + pools + 6 replicas (predecessor audit's plan). Only revisit #3 if, after that, profiling shows the per-message `BEGIN/COMMIT` round-trip (not S3, not poll-wait, not DB-time) is a measurable throughput floor — which the prior concurrency audit's numbers (p50=36 ms, p90=100 ms/msg) make unlikely. If #3 is ever built, build it to the spec in §5, which keeps the DLQ write in its own committed UoW and defers cache fan-out to after the outer commit.

---

## 1. Current transaction boundaries (verified)

### 1.1 Session lifecycle (`infrastructure/db/uow.py`)

- `__aenter__` (uow.py:114-117): eagerly creates **both** `self._write_session = self._write_factory()` and `self._read_session = self._read_factory()`. The sessionmaker is built with `expire_on_commit=False` (`session.py:57`). Neither session calls `.begin()` — they rely on SQLAlchemy **autobegin**: a transaction starts implicitly on the first statement issued through the session.
- `commit()` (uow.py:134-151): `await self._write_session.commit()`, then invokes `outbox_notifier(events)` if set (it is **not** set for this consumer — see §1.3), then runs accumulated `_post_commit_hooks` each in try/except isolation (F-DS-015).
- `rollback()` (uow.py:153-155): `await self._write_session.rollback()`.
- `__aexit__` (uow.py:119-130): on exception → `rollback()` (errors suppressed); **always** closes both sessions in `finally`. The read session is only closed `if self._read_session and self._read_session is not self._write_session`.

So **each message currently gets its own independent DB transaction that commits independently.** Autobegin → statements → `commit()` (or `rollback()` on error) → `close()`.

### 1.2 Per-message UoW boundary (`base.py:_handle_message`, 719-799)

```
deserialize → extract_event_id → is_duplicate (Valkey mixin) → return if dup
async with await self.get_unit_of_work() as uow:    # ← per-message UoW entered here
    try:
        await self.process_message(...)              # → _materialize (all DB writes)
        await uow.commit()                           # ← per-message commit
        await self.mark_processed(event_id)          # Valkey dedup mark
    except TimeoutError: rollback + dead_letter
    except Exception: rollback; raise                # ← propagates OUT of the `async with`
```

Critical ordering fact: when `process_message` raises, the exception propagates **out of the `async with uow` block**, so `__aexit__` runs `rollback()` **and closes both sessions** *before* the exception reaches the caller. `OHLCVConsumer.get_unit_of_work()` (ohlcv_consumer.py:180-183) stashes the UoW in `self._current_uow` — which, after the `async with` unwinds, points at a **closed, rolled-back UoW**.

### 1.3 No outbox notifier, no DLQ emitter

`uow_factory()` (ohlcv_consumer_main.py:69-70) constructs `SqlAlchemyUnitOfWork(write_factory, read_factory)` with **no `outbox_notifier`**. So outbox rows are plain in-transaction DB writes (`uow.outbox_events.create(...)`), drained later by a separate `OutboxDispatcher` process. The consumer is constructed with **no `dlq_emitter`** (ohlcv_consumer_main.py:89-99), and `enable_persistent_retry` / `enable_auto_commit` are left at defaults (`False` / `False`). So the **OFF failure path** (base.py:928-955) applies.

### 1.4 The contiguous-offset commit (`ohlcv_consumer.py:_process_batch`, 657-700)

Per partition, offset-sorted, serial: `await self._handle_message(msg)`; on success set `last_committable_offset = msg.offset()`; on `ConsumerError`/`Exception` call `await self._handle_failure(msg, exc)` then **`break`**. After the loop, if `last_committable_offset is not None`, commit Kafka offset `last+1`. **`break`-on-first-failure is what blocks the offset from advancing past a poison message** — even though the OFF path `_handle_failure` returns `True`, the `break` means later messages in that partition are never processed and the offset stops at the last contiguous success. They are redelivered next poll.

---

## 2. Savepoint semantics for the batch (validated)

`AsyncSession.begin_nested()` emits a real Postgres `SAVEPOINT`; the returned `AsyncSessionTransaction` `.commit()` issues `RELEASE SAVEPOINT`, `.rollback()` issues `ROLLBACK TO SAVEPOINT` — undoing only that nested block's statements while leaving the outer transaction live. Confirmed:

- **asyncpg supports SAVEPOINT** (it is plain SQL; no protocol-level limitation). No prepared-statement conflict — savepoints are not prepared statements; the prepared-statement/pgbouncer hazard from the predecessor audit applies only to **transaction-mode pgbouncer**, which is *not* in play here (consumers connect directly to `timescaledb:5432`).
- **Repos are savepoint-transparent.** Every repo takes a bare `AsyncSession` and issues statements on it (`ohlcv_repo`, `instrument_repo`, `ingestion_event_repo`, `failed_task_repo`, `quote_repo`, `outbox_event_repo`, `security_repo`). They neither commit nor begin — so wrapping a sequence of repo calls in `async with session.begin_nested():` is transparent to them.
- **In-repo precedent exists:** `services/knowledge-graph/.../repositories/canonical_entity.py:409` already does `async with self._session.begin_nested():` to isolate a recoverable unique-collision from the outer transaction. The pattern is known-good in this codebase against this asyncpg/SQLAlchemy stack.

Designed batch flow (per partition):

```python
async with batch_uow:                                  # ONE session for the whole batch
    session = batch_uow.write_session                  # (needs a public accessor; see §4)
    for msg in part_msgs_sorted_by_offset:
        # dedup BEFORE opening a savepoint (no savepoint needed to skip a dup)
        if await self.is_duplicate(event_id): continue
        try:
            async with session.begin_nested():         # SAVEPOINT
                await self._materialize_for_batch(msg)  # message's writes only
            # savepoint auto-RELEASEd on clean exit
            collected_fanouts += this_msg_fanouts       # (deferred — see §3.3)
            last_committable_offset = msg.offset()
            await self.mark_processed(event_id)         # see idempotency caveat §3.4
        except ConsumerError as exc:
            # savepoint already ROLLED BACK by begin_nested __aexit__
            await self._record_failure_durably(msg, exc) # SEPARATE committed UoW — §3.1
            break                                        # contiguous barrier preserved
    await batch_uow.commit()                            # ONE commit for the contiguous prefix
    # then: fire deferred fan-outs for committed msgs (§3.3); then Kafka offset commit
```

Partial-failure isolation holds: a poison message's `ROLLBACK TO SAVEPOINT` undoes only that message; earlier savepoint-released messages survive in the outer transaction and are committed by the single `batch_uow.commit()`.

---

## 3. The hard edge cases

### 3.1 Per-message DLQ / `failed_tasks` write durability — the subtlest part

**Current state (latent bug, independent of #3):** `store_failure` (ohlcv_consumer.py:200-209) and `_dead_letter_impl` (214-223) write a `failed_tasks` row via `self._current_uow.failed_tasks.create(...)`. `PgFailedTaskRepository.create` (failed_task_repo.py:25-35) only `execute`s an INSERT — **it never commits**. And by the time `_handle_failure` runs (from `_process_batch`), `_handle_message`'s `async with uow` has already exited → `__aexit__` rolled back and **closed** the write session. So the INSERT executes on a closed/rolled-back session and **is silently never committed.** *Today the OHLCV DLQ row does not persist.* (Offset-blocking via `break` still works, so the message redelivers — the durability gap is the audit trail, not the at-least-once guarantee.)

**Why #3 makes this worse before better:** in the batch-session model the failed message's savepoint is rolled back. If you write the `failed_tasks` row on the **same** batch session, you must write it **after** `ROLLBACK TO SAVEPOINT` (so the savepoint rollback doesn't discard it), and it then rides the **outer** `batch_uow.commit()` — which means the DLQ row only persists if the outer commit succeeds, and it is co-mingled with the successful-prefix data. That couples DLQ durability to the success of unrelated messages.

**Correct design — write the failure in its own committed UoW, outside the batch session:**

```python
async def _record_failure_durably(self, msg, exc) -> None:
    # Brand-new short-lived UoW (own session, own transaction) so the DLQ row
    # is committed regardless of the batch outer txn's fate. This also fixes the
    # pre-existing non-persistence bug.
    async with self._uow_factory() as fail_uow:
        await fail_uow.failed_tasks.create(task_type="ohlcv_consumer_dead",
                                           payload=..., max_attempts=0)
        await fail_uow.commit()
```

This guarantees a poison message is both (a) **not materialized** (savepoint rolled back) and (b) **durably recorded** (separate committed UoW) and (c) **offset-blocked** (`break`). It opens a *second, transient* session only on the failure path (rare), so it does not affect the steady-state session count. **This UoW must be entered/exited via `self._current_uow` indirection removed** — the batch path must NOT reuse `self._current_uow` for failures (that is exactly the trap that hides the current bug). Equivalent fix is independently worth applying to the *current* code even if #3 is never built.

### 3.2 Contiguous-offset commit interaction

- **Messages before the failure:** they were savepoint-released into the outer transaction; `batch_uow.commit()` commits them; Kafka offset is committed to `last_committable_offset + 1` **after** the DB commit succeeds (DB-durable-then-offset ordering preserved). Correct.
- **Messages after the failure:** keep the existing **`break`** (skip the rest of the partition). Rationale: at-least-once + the contiguous barrier means everything from the hole onward must redeliver; processing post-hole messages into the same committed transaction would advance their data but you could NOT commit their offsets (there is a hole), so on redelivery they'd reprocess — relying entirely on dedup to no-op. That is *correct* but wasteful and increases the outer-transaction's lock footprint for no offset progress. **Keep `break`.** (Do NOT switch to "process-but-don't-commit-past-the-hole" — it buys nothing and enlarges the transaction.)
- **One subtlety vs today:** today each pre-failure message is *already committed* (its own UoW). In #3 they are only committed at the *end* of the batch. If the process crashes mid-batch **after** several savepoint-releases but **before** `batch_uow.commit()`, **all** of them roll back and redeliver — vs today where the earlier ones would already be durable. This is still correct under at-least-once (they redeliver, dedup/natural-key makes reprocessing idempotent), but it **widens the redelivery window** on crash. Acceptable, but note it.

### 3.3 Side effects that escape the transaction (cache fan-out, outbox)

- **Outbox rows** (`uow.outbox_events.create`) are ordinary in-transaction DB writes. In #3 they are written inside the per-message savepoint → released into the outer txn → committed once. A failed message's outbox rows are savepoint-rolled-back with the rest of its writes. **Correct automatically; no special handling.** (The separate `OutboxDispatcher` polls committed rows; it never sees rolled-back ones.)
- **Quote cache fan-out** (`schedule_quote_cache_fanout` → `uow.schedule_post_commit(...)`) is a **non-transactional Valkey side effect**. Today it fires in `uow.commit()` *after* the per-message write commit — i.e. once per successful message. In #3 there is one `batch_uow.commit()`, so **all** scheduled hooks would fire there. The hazard: if message M's savepoint was **rolled back**, its `schedule_post_commit` coroutine (scheduled inside `_materialize` *before* the savepoint rolled back) is still sitting in `_post_commit_hooks` and would fire on the outer commit — invalidating/warming a cache for a quote that was **never committed**. **Wrong.**

  **Design:** do **not** route the fan-out through the UoW's `schedule_post_commit` in the batch path. Instead **collect the fan-out coroutines locally per message**, and only after a message's savepoint **successfully releases** append them to a batch-level `committed_fanouts` list. Then, **after `batch_uow.commit()` succeeds**, fire `committed_fanouts` (each in its own try/except, mirroring F-DS-015). A rolled-back message's fan-outs are simply never added. (If you must keep using `schedule_post_commit`, you would have to *un-schedule* a rolled-back message's hooks — which the UoW has no API for — so the local-collection approach is cleaner.)

### 3.4 Dedup within the batch + idempotency on retry

- **`create_if_not_exists` (ingestion_events)** runs inside the message's savepoint. If the outer batch commits, the dedup rows for the committed prefix commit atomically with their data — good: a redelivery of a committed message sees the row and short-circuits.
- **Valkey `mark_processed`** (the `ValkeyDedupMixin`) is a *non-transactional* Valkey write. In the per-message model it fires after each commit. In #3, if you call `mark_processed` per message *before* the outer commit and then the outer commit **fails/crashes**, you'd have Valkey-marked messages that were **never committed to Postgres** → on redelivery the Valkey `is_duplicate` check would **skip** them, losing data. **Design:** call `mark_processed` for the committed prefix **only after `batch_uow.commit()` succeeds** (collect the event_ids, mark them post-commit), mirroring the fan-out deferral. The DB-side `create_if_not_exists` is the durable dedup; Valkey is the fast-path optimization and must never run ahead of the DB commit.
- **A later message fails, earlier successes still commit:** correct and desirable — on redelivery the failed/after messages reprocess, the committed ones short-circuit via the DB dedup row. **No double-processing, no lost dedup**, provided the Valkey mark is deferred to post-outer-commit (above).

### 3.5 `max.poll.interval` / heartbeat / lock-hold

- **Liveness:** holding one transaction open across ≤50 messages at the measured ~36–100 ms/msg DB phase is ~2–5 s; the batch already validated <150 s worst case against `max_poll_interval_ms=600_000` (ohlcv_consumer.py:62-76). #3 does not change the *wall-clock* of a batch (work is identical) — it only changes *when* the commit lands. Liveness margin is unchanged and comfortable.
- **Lock-hold / TimescaleDB:** the meaningful difference. Today: 50 short transactions, each holding row/page locks on `ohlcv_bars` (+ chunk locks) for ~tens of ms, releasing between messages. #3: **one** transaction holding all touched rows' locks for the whole batch (~2–5 s) and producing 50 messages' worth of row versions before a single commit. Implications:
  - Longer lock-hold can increase contention with the `OutboxDispatcher` and API readers touching the same hot rows (e.g. a heavily-traded symbol's latest bar / its `quotes` row write-through). On a single-writer consumer this is usually fine, but **with 6 replicas all running batch transactions**, two replicas materializing overlapping instruments hold conflicting row locks for seconds, not milliseconds → higher lock-wait, possible `pool_timeout`/deadlock risk on the `quotes` upsert hot row.
  - Longer transactions hold back `vacuum`'s `xmin` horizon and accumulate dead tuples per commit; on TimescaleDB hypertables this marginally affects chunk bloat. At 50-row batches every few seconds this is negligible, but it is strictly *worse* than many short transactions, not better.
  - **Net:** the lock/bloat trade-off is a *cost* of #3, partially offsetting the round-trip savings. It does not disqualify #3 but it is a real reason the "obviously better" intuition is wrong at fleet scale.

---

## 4. Blast radius & alternatives

### 4.1 Can #3 be consumer-local?

**Partially, and the non-local part is the expensive part.** #3 requires the UoW boundary to live in `_process_batch`, which means **bypassing `_handle_message` entirely** (its whole body is "open per-message UoW, process, commit"). Bypassing it forces re-implementing, inline in the consumer:

- deserialize + `extract_event_id`
- `is_duplicate` (Valkey) gate + `mark_processed` (now deferred — §3.4)
- the `message_processing_timeout_s` watchdog (`asyncio.timeout`) per message
- the success metrics (`kafka_messages_consumed_total`, `KAFKA_CONSUMER_MESSAGES`)
- the `_ASYNCPG_CONN_ERRORS` reconnect-retry wrapper (currently in `_process_batch` around `_handle_message`)
- the failure routing (now to `_record_failure_durably`, §3.1)

This is a **meaningful re-implementation of shared, security/metrics-relevant base logic** in one consumer, which then **drifts** from the base for every future base change. The UoW class also needs a small addition: a **public write-session accessor** (today only `_write()` private + repo properties) so `_process_batch` can call `session.begin_nested()`. So #3 is "consumer-local + one small UoW addition," but the consumer-local part duplicates ~60 lines of correctness-sensitive base code.

The alternative — pushing batch/savepoint support **into the base `_handle_message`/`BaseKafkaConsumer`** — is a far larger, cross-cutting change affecting all ~30 consumers and is out of proportion to a session optimization for one consumer.

### 4.2 #3 vs #1+replicas — quantified, honest

| Metric | #1 (lazy-read), serial | #3 (batch-savepoint), serial |
|---|---|---|
| **Concurrent write connections per replica** | **1** | **1** |
| Write conns at 6 replicas | **6** | **6** |
| Session *checkouts* per 50-msg batch | 50 (sequential, **1 connection reused**) | 1 |
| `BEGIN`/`COMMIT` round-trips per batch | ~50 | ~1 (+ ~50 cheap SAVEPOINT/RELEASE, local to the open txn) |
| Lock-hold per hot row | ~tens of ms | ~2–5 s (whole batch) |
| Crash redelivery window | last 1 message | whole uncommitted batch |
| Code change | ~5 lines, 1 shared method, zero new control flow | ~60 lines re-implementing `_handle_message` + UoW accessor + DLQ-UoW + fan-out/dedup deferral |
| New correctness surfaces to test | ~0 | savepoint rollback, DLQ-outside-savepoint, deferred fan-out, deferred Valkey mark, partial-batch crash |

**The connection-budget constraint that motivated the whole exercise (`replicas × concurrent conns ≤ 500`) is identical for #1 and #3: 6 connections.** #3's only real wins are (a) ~49 fewer `BEGIN/COMMIT` round-trips/batch (a latency/pool-churn improvement, not a connection improvement) and (b) atomic batch dedup. Its costs are longer lock-hold, a wider crash-redelivery window, and substantial duplicated control flow. **Given the pool already reuses one connection serially and #1 already makes that one connection a single write session, #3 does not move the binding constraint.**

---

## 5. Verdict + design spec

### 5.1 Verdict

**#3 is not worth implementing now.** Ship, in order:
1. **#1 lazy read-session** (predecessor audit) — turns the serial loop into 1 write session at a time, 0 idle read sessions. This alone makes 6-replica scaling safe (6 write conns vs 500 budget).
2. **Pool right-sizing** (`pool_size=2, max_overflow=3`) — caps blast radius.
3. **Independently, fix the latent DLQ non-persistence bug** (§3.1) in the *current* code: route `store_failure`/`_dead_letter_impl` through a fresh committed UoW instead of the closed `self._current_uow`. This is a real correctness fix worth doing regardless of #3.

**Revisit #3 only if** post-#1 profiling at 6 replicas shows the per-message `BEGIN/COMMIT` round-trip is a measurable throughput floor (unlikely given p50=36 ms / p90=100 ms per message, where DB-time dominates the round-trip). Even then, weigh the longer lock-hold against the round-trip savings — at 6 replicas the lock contention on hot `quotes`/latest-bar rows may erase the gain.

### 5.2 If #3 *is* built later — the exact design

- **Batch UoW location:** one `async with self._uow_factory() as batch_uow:` per **partition** inside `_process_batch` Phase 2 (not per whole batch — keep per-partition so a partition's barrier maps to one transaction and the contiguous-commit logic is per-partition as today). Add a **public `write_session` accessor** to `SqlAlchemyUnitOfWork`.
- **Per message:** `if await is_duplicate: continue` (no savepoint for dups) → `async with batch_uow.write_session.begin_nested():` wrapping a batch variant of `_materialize` that takes the batch UoW (not `self._current_uow`) → on clean exit collect the message's fan-out coroutines + event_id locally and set `last_committable_offset`.
- **DLQ outside the savepoint:** on `ConsumerError`/`Exception`, the savepoint is already rolled back; call `_record_failure_durably(msg, exc)` which opens its **own** `self._uow_factory()` UoW and **commits** the `failed_tasks` row; then `break`.
- **Outer commit then side effects:** after the per-partition loop, `await batch_uow.commit()`; **only if it succeeds**: (a) fire collected fan-out coroutines for committed messages (each in try/except, F-DS-015 style), (b) Valkey `mark_processed` for committed event_ids, (c) Kafka commit offset `last_committable_offset + 1`. If `batch_uow.commit()` raises, fire none of these → whole partition redelivers (correct).
- **Watchdog + metrics + reconnect:** re-implement the `asyncio.timeout(message_processing_timeout_s)` per savepoint, the success counters, and the `_ASYNCPG_CONN_ERRORS` retry inline (since `_handle_message` is bypassed). Factor these into small private helpers shared with a future base method if possible, to limit drift.

### 5.3 Test matrix required for #3

1. **Happy batch:** N messages, 1 partition → 1 outer commit, N savepoints released, offset = last+1, all data present, fan-outs fired N times post-commit.
2. **Mid-batch poison (ConsumerError):** msgs [ok, ok, BAD, ok] → first 2 committed, BAD savepoint-rolled-back (its writes absent), `failed_tasks` row **present and committed** via separate UoW, offset = 2nd offset +1, BAD + 4th redeliver next poll; fan-outs fired only for the 2 committed.
3. **Fan-out isolation:** a committed message whose fan-out coroutine raises → outer data still committed, offset still advanced, other fan-outs still fire (no propagation).
4. **Rolled-back message must not fan-out or Valkey-mark:** assert the BAD message's `schedule_quote_cache_fanout` effects never run and its event_id is never `mark_processed`-ed.
5. **Outer-commit failure:** force `batch_uow.commit()` to raise → no Valkey marks, no fan-outs, no Kafka offset commit; whole partition redelivers; dedup rows absent (rolled back).
6. **Crash before outer commit (simulated):** savepoints released but commit never called → on next run all redeliver and reprocess idempotently (DB `create_if_not_exists` + natural-key upsert no-op).
7. **Duplicate within batch:** same event_id twice in one batch → second skipped by `is_duplicate`/`create_if_not_exists`, no double upsert, offset still advances.
8. **Watchdog:** a message whose materialize exceeds `message_processing_timeout_s` → TimeoutError → that savepoint rolled back, DLQ row written, partition barrier holds.
9. **asyncpg reconnect:** connection-lost on one message's first attempt → retried once → succeeds, batch continues.
10. **Multi-partition:** two partitions in one batch, one fails → each partition's outer commit + offset independent; the healthy partition fully commits.

### 5.4 Risks (ranked)

1. **DLQ durability ordering** (§3.1) — highest; mis-ordering silently loses the audit row (already broken today) or, worse, ties DLQ persistence to unrelated successes. Mitigation: separate committed UoW.
2. **Cache fan-out / Valkey-mark firing for rolled-back or uncommitted messages** (§3.3, §3.4) — silently corrupts caches / loses data on crash. Mitigation: local collection, fire only post-outer-commit for released messages.
3. **Re-implementation drift from `_handle_message`** (§4.1) — security/metrics/watchdog logic duplicated and diverging over time.
4. **Longer lock-hold at 6 replicas on hot rows** (§3.5) — contention/deadlock risk that may erase the round-trip win.
5. **Wider crash-redelivery window** (§3.2) — acceptable under at-least-once but more reprocessing on restart.

---

## Evidence index

- Per-message UoW boundary + rollback-then-close-then-raise: `base.py:719-799` (esp. `async with await self.get_unit_of_work() as uow:` 750; `except Exception: await uow.rollback(); raise` 782-784).
- `__aexit__` closes both sessions in `finally` even on exception: `uow.py:119-130`.
- Sessions autobegin (no explicit `.begin()`), `expire_on_commit=False`: `session.py:55-57`; eager dual-session open: `uow.py:114-117`.
- `commit()` fires outbox notifier (unset here) + post-commit hooks in isolation: `uow.py:134-151`.
- No outbox notifier / no dlq emitter / OFF retry path: `ohlcv_consumer_main.py:69-70, 89-99`; OFF path `base.py:928-955`.
- DLQ write on closed `self._current_uow`, repo `create` never commits → **not persisted today**: `ohlcv_consumer.py:200-223` + `failed_task_repo.py:25-35` + the close-on-exit at `uow.py:119-130`.
- Contiguous-offset commit + `break`-on-failure + DB-then-offset ordering: `ohlcv_consumer.py:657-700`.
- Quote cache fan-out via `schedule_post_commit` (per-message today): `quote_cache_fanout.py:29-67`; scheduled in `_materialize`: `ohlcv_consumer.py:492-511`.
- Batch already serial per partition (≤1 concurrent session): `ohlcv_consumer.py:658-664`.
- In-repo `begin_nested()` savepoint precedent: `services/knowledge-graph/.../repositories/canonical_entity.py:409`.
- Pool config `pool_size=20, max_overflow=30`, direct connect to timescaledb (no pgbouncer): `session.py:19-52`.
- Predecessor audit (Option #1/#2/#3 ranking, session math, 500-conn budget): `docs/audits/2026-06-16-uow-session-optimization.md`.
- Prior concurrency audit (serial fine; p50=36 ms / p90=100 ms/msg): `docs/audits/2026-06-16-ohlcv-materialize-concurrency.md`.
