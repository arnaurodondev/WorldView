# Dead-Letter / Failed Backlog — Root-Cause Investigation

**Date:** 2026-06-22
**Mode:** READ-ONLY (psql SELECT + LIMIT, docker logs, code/git read). No mutations, no edits, no commits. Secrets redacted.
**Scope:** The STALE, frozen-pre-deploy backlogs only:
- `content_ingestion_db` — ~2,259 outbox `dead_letter` rows (1,653 Polymarket `market.prediction.v1` + 606 raw articles `content.article.raw.v1`), frozen ~2026-06-21.
- `nlp` — ~815 outbox `failed` rows, frozen 2026-06-18.

**Explicitly OUT of scope (owned by another agent — NOT touched):** the LIVE nlp `dead_letter_queue` `message_processing_timeout` rows (2,528) and the `provisional_entity_queue` path.

Context inputs: `docs/audits/2026-06-22-qa-postgres.md`, `docs/audits/2026-06-22-qa-pipeline.md`.

---

## TL;DR / Recommendation per backlog

| Backlog | Count | Root cause | Live bug? | Recommendation |
|---|---|---|---|---|
| `market.prediction.v1` dead_letter | 1,653 | **Transient Kafka-delivery failures** during episodic incident windows; retries exhausted (5 attempts). NOT a serializer bug — `event_type=market.prediction.snapshot` IS registered and is publishing fine post-deploy. | **No** (frozen 06-21 18:35; 1.27M delivered, 0.13% failed) | **Reprocess** (idempotent downstream) OR **discard** (snapshots are point-in-time; stale by weeks → low value). Prefer discard-as-obsolete. |
| `content.article.raw.v1` dead_letter | 606 | Same transient-delivery class, clustered on incident days (05-21: 418, 06-12: 146). NOT a content bug. | **No** (frozen 06-21 07:00) | **Reprocess** — these are real lost article ingestions; downstream (content-store dedup) is idempotent. |
| nlp outbox `failed` | 815 | (see §4) | TBD | (see §4) |

**Two real CODE bugs found (both latent, neither is the backlog's root cause but both hurt diagnosis/ops):**
- **BUG-1 (diagnostic blindness):** `dead_letter_queue.error_detail` is **NULL for all 2,356 rows**. `BaseOutboxDispatcher._dispatch_record` calls `uow.outbox.move_to_dead_letter(record.id)` WITHOUT passing the error; the repo signature `move_to_dead_letter(record_id, error_detail="")` defaults to empty → stored as NULL. The error type is logged but never persisted to the DLQ row. Every DLQ entry is un-triageable from the table alone.
- **BUG-2 (no auto-redrive):** there is no automatic reprocessing path. A manual DLQ-retry use case exists (`RetryDLQEntryUseCase`, one row at a time via admin route) but nothing re-drives in bulk, so any transient incident permanently strands its victims.

---

## 1. The 1,653 Polymarket dead-letters (`market.prediction.v1`)

### Evidence
`content_ingestion_db.outbox_events` (OLTP, postgres-1):
```
topic                  | status      | count    | min(created_at)        | max(created_at)
market.prediction.v1   | delivered   | 1,275,378| 2026-05-09 17:16       | 2026-06-22 10:47  (LIVE)
market.prediction.v1   | dead_letter | 1,653    | 2026-05-22 05:18       | 2026-06-21 18:35  (FROZEN)
content.article.raw.v1 | delivered   | 54,954   | 2026-05-09 14:00       | 2026-06-22 10:47  (LIVE)
content.article.raw.v1 | dead_letter | 606      | 2026-05-21 02:06       | 2026-06-21 07:00  (FROZEN)
```
All dead-lettered rows: `attempts=4, max_attempts=5`, `event_type=market.prediction.snapshot`.
(attempts=4 stored because the 5th increment + dead-letter happen in the same pass: `new_attempts = record.attempts(4) + 1 = 5 >= max_attempts` → dead-letter; DB shows the pre-increment value 4.)

DLQ daily distribution = **episodic clusters, not a steady drip**:
```
2026-05-22  prediction   100
2026-05-23  prediction   700   <- big spike
2026-05-25  prediction   121
2026-05-26  prediction   100
2026-06-14  prediction   121
2026-06-15  prediction    82
2026-06-17  prediction   274
2026-06-18  prediction    54
2026-06-21  prediction   101
```

### Root cause = TRANSIENT delivery failure, NOT a Polymarket adapter bug
1. **Serializer is correct.** The dispatcher registers a serializer keyed on `event_type` (the `OutboxEventValueSerializer.__call__` routes on `value.event_type`, NOT topic — the dispatcher's docstring is misleading). The prediction rows carry `event_type="market.prediction.snapshot"`, which **is** in the map (`dispatcher.py:111`). The old BP-147 "missing serializer KeyError" is already fixed in the running image.
2. **It is publishing fine post-deploy.** Live dispatcher logs show a continuous stream of `outbox_record_published event_type=market.prediction.snapshot topic=market.prediction.v1` at 10:49. 1,275,378 delivered vs 1,653 dead-lettered = **0.13% lifetime failure rate**, all frozen at 06-21 18:35.
3. **Clustered on incident days** matches transient Kafka-broker / schema-registry unavailability windows (cf. MEMORY: BP-705/706 broker GC-freeze wedge modes on 06-21; the 06-21 cluster aligns). A persistent payload/schema bug would fail ~100% steadily, not in day-shaped spikes.

### Payload recoverability
`payload_json` is fully preserved (canonical snapshot incl. `market_id`, `outcomes`, prices, `occurred_at`). `payload_avro=b""` sentinel (BP-040) — re-serialization happens from `payload_json` on requeue, so recovery is possible. BUT prediction snapshots are point-in-time market quotes; replaying a 4-week-old snapshot injects stale prices. **Recommend discard-as-obsolete** unless downstream consumers tolerate/ignore stale `occurred_at`.

---

## 2. The 606 raw-article dead-letters (`content.article.raw.v1`)

Same failure class (attempts exhausted, episodic). Clusters: 2026-05-21 = 418, 2026-06-12 = 146, 2026-06-14 = 79. `payload_json` preserved. These represent **real lost article ingestion** that was never reprocessed.

Downstream (`content-store` dedup consumer) is idempotent on content hash, so replay is safe (duplicates are dropped). **Recommend reprocess — but only 606, not 703.** Reconciled via JOIN on `original_event_id`: of the 703 raw DLQ rows, **97 have an outbox row now in `delivered` status** (they were redelivered later but their DLQ rows were never marked resolved — stale DLQ entries), and **606 are still genuinely dead** (`dead_letter`). Only replay the 606; skip/resolve the 97 stale DLQ rows.

---

## 3. The 815 nlp `failed` outbox rows (`nlp_db.outbox_events`, OLAP / postgres-intelligence)

### Evidence
```
topic                          | status | count | min                  | max
nlp.article.enriched.v1        | failed | 411   | 2026-06-18 10:11     | 2026-06-18 19:44
nlp.signal.detected.v1         | failed | 375   | 2026-05-21 04:42     | 2026-06-18 19:31
intelligence.temporal_event.v1 | failed | 29    | 2026-06-18 10:24     | 2026-06-18 18:50
```
- **ALL 815 rows have `retry_count=1`.**
- **814 of 815 are on a single day (2026-06-18)** (1 outlier `signal` on 05-21). This is **one incident**, not chronic.
- `payload_avro` is **intact (octet_length>0) for all 815** → fully recoverable.
- The nlp dispatcher is healthy post-deploy (continuous `outbox_record_dispatched` at 10:52, zero new failures).

### Root cause = a DESIGN BUG in the nlp dispatcher (BUG-3, still live), triggered by the 06-18 incident
This outbox uses a **different, S6-era schema** (`payload_avro` bytea, `retry_count`, `failed_at`; no `payload_json`, no error column) and a **different dispatcher** (`nlp_pipeline/infrastructure/messaging/outbox/dispatcher.py`).

The bug: on a delivery failure the dispatcher calls `OutboxRepository.mark_failed(event_id)`, which sets:
```python
status="failed", failed_at=now, retry_count=retry_count + 1
```
But `claim_batch()` selects **only `status == "pending"`**. A record set to `failed` is therefore **never re-claimed**. So:
- The intended 5-attempt retry (`_MAX_DISPATCH_ATTEMPTS=5`) is **dead code** — a record can never accumulate more than `retry_count=1`, because after the first failure it leaves the `pending` pool forever.
- It also **never reaches the DLQ table** (the `move_to_dlq` branch requires `retry_count+1 >= 5`, which is unreachable).
- Result: a single transient delivery failure (the 06-18 broker/SR incident — aligns with the BP-705/706 wedge history) **permanently strands** the event at `retry_count=1`, status `failed`, with no retry and no DLQ → silent data loss.

Contrast with content-ingestion's dispatcher, which on failure resets `status="pending"` (via `increment_attempts`) so the record is re-claimed until it either succeeds or hits `max_attempts` then dead-letters. The nlp dispatcher is missing that `failed → pending` reset.

### Recoverability — SAFE to reprocess now
- The incident is over; the broker/dispatcher is healthy.
- `payload_avro` intact for all 815.
- The outbox `add()` uses deterministic UUID5 + `ON CONFLICT (event_id) DO NOTHING`, and the downstream nlp consumers are idempotent (per the service design). Re-dispatching the same `event_id` is therefore safe (re-delivery is swallowed/deduped downstream).
- **Recommendation: reprocess** by resetting `failed → pending` so the live dispatcher re-claims them (see §5 dry-run). The 414 enriched/temporal are pure 06-18 incident victims (high value: lost article enrichment + temporal events). The 375 signal events are also recoverable.

---

## 4. Re-drive mechanisms — what exists vs. the gap

| Path | content-ingestion | nlp-pipeline |
|---|---|---|
| Failed outbox auto-retry | Yes — `increment_attempts` resets `pending`, re-claimed until `max_attempts` | **NO** — `mark_failed` sets `failed`, never re-claimed (BUG-3) |
| Dead-letter persistence | `dead_letter_queue` table (but `error_detail` NULL — BUG-1) | `dead_letter_queue` table (`move_to_dlq` — but unreachable, see BUG-3) |
| Manual DLQ re-drive | `POST /admin/dlq/{dlq_id}` → `RetryDLQEntryUseCase.requeue` (one row) | `dlq_admin.py` + `DLQRepository.requeue` (one row) |
| Bulk re-drive of a whole backlog | **NO** | **NO** |
| Coverage of the 815 nlp `failed` rows | n/a | **NONE** — they are in the OUTBOX (`status=failed`), not the DLQ table, so the DLQ admin path can't see them |

**Gaps:**
- **BUG-1** — content-ingestion DLQ rows have NULL `error_detail`: `BaseOutboxDispatcher._dispatch_record` (line 553) calls `move_to_dead_letter(record.id)` without the error; repo default `error_detail=""` → NULL. Fix: pass `error_type`/`repr(delivery_error)` through to `move_to_dead_letter`.
- **BUG-3** — nlp `mark_failed` should reset `status="pending"` (not `failed`) so the retry loop actually works, OR `claim_batch` should also re-claim `failed` rows whose `retry_count < _MAX_DISPATCH_ATTEMPTS` after a backoff. As-is, the retry + DLQ machinery is unreachable.
- **No bulk re-drive tool** for either backlog.

---

## 5. Recovery plan (DRY-RUN ONLY — nothing executed)

> All queries below are **SELECT-only counts** (dry-run). Mutations are shown commented-out for a human operator to run deliberately, gently, in small batches.

### 5a. nlp 815 `failed` → reprocess (RECOMMENDED, highest value)
Dry-run (confirm the set before touching it):
```sql
-- DRY RUN: how many, and intact?
SELECT topic, count(*) FILTER (WHERE octet_length(payload_avro) > 0) AS recoverable,
       count(*) AS total
FROM outbox_events
WHERE status = 'failed' AND created_at >= '2026-05-21'
GROUP BY topic;
```
Re-drive (operator runs deliberately, in batches — flips them back into the `pending` pool the live healthy dispatcher already polls):
```sql
-- NOT EXECUTED. Batch of 200, oldest-first, idempotent (UUID5 + ON CONFLICT downstream):
-- UPDATE outbox_events SET status='pending', retry_count=0, failed_at=NULL
-- WHERE event_id IN (
--   SELECT event_id FROM outbox_events WHERE status='failed' ORDER BY created_at LIMIT 200
-- );
-- Then watch dispatcher logs for outbox_record_dispatched; repeat until 0 remain.
```
Idempotency guarantee: re-publishing the same `event_id` is deduped (outbox `ON CONFLICT (event_id) DO NOTHING`) and downstream nlp consumers are idempotent. Do it in small batches to avoid hammering the already-contended intelligence Postgres (see qa-postgres issue #2).

### 5b. content-ingestion 606 raw articles → reprocess
The DLQ table preserves `payload_json`. The existing single-row admin path works but is impractical at 600+ rows. Two options:
1. **Script the existing admin route** (`POST /admin/dlq/{dlq_id}`) over the 703 raw DLQ ids — safest, uses the supported `requeue` use case, content-store dedup drops duplicates.
2. **Bulk SQL requeue** mirroring `OutboxRepository.append` (insert fresh `pending` outbox rows from `payload_json`).

Dry-run:
```sql
-- DRY RUN: raw-article DLQ entries eligible for replay
SELECT count(*), count(*) FILTER (WHERE payload_json IS NOT NULL) AS replayable
FROM dead_letter_queue WHERE topic = 'content.article.raw.v1' AND resolved_at IS NULL;
```
Reconcile against outbox `dead_letter` (703 DLQ rows vs 606 outbox) on `original_event_id` first, to avoid double-replaying rows already requeued.

### 5c. content-ingestion 1,653 Polymarket → DISCARD-as-obsolete (recommended) or reprocess
Prediction snapshots are point-in-time prices with `occurred_at` weeks old. Replaying injects stale market data. Unless a downstream consumer is known to ignore stale `occurred_at`, **mark resolved/obsolete** rather than replay:
```sql
-- DRY RUN: confirm count + age
SELECT count(*), min(created_at), max(created_at)
FROM dead_letter_queue WHERE topic='market.prediction.v1' AND resolved_at IS NULL;
-- NOT EXECUTED (discard): UPDATE dead_letter_queue SET resolved_at=now(),
--   resolution_note='obsolete: stale prediction snapshot, discarded 2026-06-22'
--   WHERE topic='market.prediction.v1' AND resolved_at IS NULL;
```

---

## 6. Fix plan (code — for a follow-up /fix-bug or /implement)

1. **BUG-1 (content-ingestion DLQ error_detail NULL).** In `BaseOutboxDispatcher._dispatch_record` (libs/messaging/.../dispatcher/base.py:553), pass the error to `move_to_dead_letter`, e.g. `await uow.outbox.move_to_dead_letter(record.id, error_detail=f"{error_type}: {delivery_error!r}")`. Verify all `move_to_dead_letter` implementations accept it (content-ingestion repo already does; default `""`). Add a regression test asserting `error_detail` is non-NULL on dead-letter. Also fix the misleading docstring in `ContentIngestionOutboxDispatcher.get_serializer` ("routes based on topic" — it routes on `event_type`).
2. **BUG-3 (nlp dispatcher fail-and-strand).** In `nlp_pipeline/infrastructure/nlp_db/repositories/outbox.py::mark_failed`, set `status="pending"` (not `"failed"`) while `retry_count < _MAX_DISPATCH_ATTEMPTS`, and only set a terminal status once attempts are exhausted (where the DLQ move already happens). OR widen `claim_batch` to re-claim `failed` rows below the cap after a backoff. Add a test that a transient failure is retried and either delivered or DLQ'd — never silently stranded. This is the structural cause of the 814 lost 06-18 events.
3. **Bulk re-drive ops tool.** Add an admin endpoint / management command to bulk-requeue a backlog by topic + date range, idempotent and rate-limited (small batches), for both the content-ingestion DLQ table and the nlp `failed` outbox rows. Removes the need for raw SQL during incidents.

---

## 7. Notes / caveats

- Read-only throughout: only `SELECT`/`\d`/`docker logs`. No DDL/DML executed. Postgres treated gently (counts/MAX/LIMIT, no full scans).
- DB credentials never printed (superuser `postgres` via `docker exec`, password not echoed).
- The LIVE nlp `dead_letter_queue` `message_processing_timeout` rows (2,528) and `provisional_entity_queue` are owned by another agent and were **not** touched or analyzed here.
- BP candidates to record after fixes land: BUG-1 (dispatcher dead-letter drops error_detail) and BUG-3 (outbox `mark_failed` strands records outside the `pending` claim set — retry/DLQ machinery unreachable).
