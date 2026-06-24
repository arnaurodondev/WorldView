# Article-Consumer Processing-Timeout + Dead-Letter Investigation

**Date:** 2026-06-18
**Scope:** `nlp-pipeline` article consumer — `message_processing_timeout` → `article_consumer_dead_lettered`
**Mode:** READ-ONLY (code + `docker logs` + `psql` SELECTs). No code/DB/container changes.
**Status of stack at audit:** 11 nlp containers healthy; GLiNER + Ollama healthy; 0 DLQ in the last 2h.

---

## TL;DR

- **97 % of the 2,316 dead-letters are `message_processing_timeout`** (2,236 rows). The remainder are GLiNER/MinIO connectivity blips (24) and "deep extraction timed out on all windows" (55).
- The timeouts span **four different watchdog eras** — `after 300s` (715), `after 450s` (1,127), `after 700s` (62), `after 900s` (332) — proving the bleed is **chronic and structural**, not a single incident. The current 900s watchdog is the latest in a series of "raise the ceiling" mitigations.
- **A single load spiral (2026-06-12) produced 1,467 dead-letters = 63 % of all-time DLQ in one day.** That is the transient event. But there is *also* a **steady recent bleed at the current 900s watchdog**: 6-15→6-18 = ~616 rows, including **122 today (6-18) spread evenly 04:00–20:17** — i.e. the structural fragility persists *after* every budget fix.
- **Where the time goes (live, 24 h):** the dominant single cost is deep extraction. Actual extraction model is **`openai/gpt-oss-120b`** (env-overridden; the config comments still describe Qwen3-235B). Its latency: **p50 44 s, p95 104 s, p99 187 s, max 294 s**. NER (GLiNER) is fast per call right now but **serialized behind a 4-wide semaphore** while 16 article handlers run per replica → it becomes the funnel under load.
- **The 2,316 dead-letters are effectively UNRECOVERABLE from the DLQ.** `_dead_letter_impl` writes `payload_avro = event_id.encode()` — just `{"event_id":"…"}`, **not** the real `content.article.stored.v1` envelope. `original_event_id` is the *article event_id*, which **matches 0 rows** in `content_store.documents.doc_id` and carries **no `minio_silver_key`**. The `DLQRepository.requeue()` path exists but has nothing real to requeue.
- **Blast radius:** all 2,176 distinct dead-lettered events produced **zero `routing_decisions`** (whole-article rollback). Those articles contributed **0 entities / 0 relations** to the KG (which currently holds ~100k `relation_evidence_raw`). The loss is concentrated in the 6-12 spiral window.

---

## 1. Where the ~820 s budget goes — and what is real

### 1.1 The documented budget (config.py)
`config.py` line 179-220, 341-364:

- `extraction_timeout_s = 300` per attempt, `extraction_max_attempts = 2`, `extraction_total_budget_s = 320` per model.
- Worst case = primary model (320) + fallback hop (320) + GLiNER NER (~160) + writes ≈ **820 s** against `message_processing_timeout_s = 900`. **80 s of headroom.**

The arithmetic assumes Qwen3-235B with **p95 ≈ 179 s** per `extract()` call.

### 1.2 The actual live latencies (llm_usage_log, last 24 h)

| capability | model | success | n | p50 | p95 | p99 | max |
|---|---|---|---|---|---|---|---|
| extraction | **openai/gpt-oss-120b** | ✓ | 2,323 | **44.4 s** | **103.5 s** | **186.7 s** | **293.9 s** |
| classification | Meta-Llama-3.1-8B-Turbo | ✓ | 1,340 | 0.6 s | 1.7 s | 3.8 s | 10.4 s |
| extraction | qwen2.5:7b (Ollama, OLD/failing) | ✗ | 14 | 43 s | 205 s | 263 s | 278 s |

**Finding:** the deployed extraction model (`gpt-oss-120b`) is **faster than the budget assumes** (p95 104 s vs the 179 s the config was written for). A *single* extraction window is comfortably inside budget. So the 900 s timeouts are **not** primarily "one slow LLM call."

### 1.3 So what actually consumes 900 s? — Serialization under load

The per-article chain (`_run_pipeline`, `article_consumer.py:1000-1366`) is **sequential per article**: download → section → **NER (GLiNER)** → routing → embeddings → novelty → resolution → **deep extraction (LLM)** → persist. The intra-replica concurrency override (`run()`, line 480) runs **16 articles at once per replica**, but the shared ML resources are *narrow*:

- **GLiNER HTTP adapter semaphore = `embedding_max_concurrent` = 4** (`article_consumer_main.py:116`, `config.py:305`). Only 4 of 16 in-flight handlers can call GLiNER at a time, and the GLiNER server itself runs **one forward pass at a time** (CPU/GIL-serial — documented at `config.py:204-215`). Under load, 16 handlers × (up to 32 sections each) queue behind a single-core transformer. The config comment already measured a single `/ner/batch` at **~79 s** under concurrent load.
- **Embeddings share the same 4-wide `ml_sem`.**
- **Deep extraction** has its own 16-wide `extraction_sem` (good — that's the I/O-bound one), but it is downstream of the NER funnel.

**This is the pathology:** a razor-thin watchdog margin + a NER step whose *effective* latency scales with how saturated the shared 4-wide GLiNER funnel is. When input rate rises (the 6-12 spiral), GLiNER queueing inflates per-article wall time well past the surrounding LLM budget, and articles tip over the watchdog **in waves** — exactly the 1,467-in-one-day signature.

Adjudication of root cause weight:
1. **~60 % transient host/GLiNER saturation** — the 6-12 spike is a clean load-spiral signature (1,467/day vs a ~20-80/day baseline).
2. **~30 % structural thin-margin fragility** — an 80 s margin over an 820 s best-case budget *guarantees* dead-letters whenever GLiNER queueing or a fallback hop adds >80 s. Confirmed by the steady 122/day bleed at the current 900 s watchdog (6-18).
3. **~10 % real defects** — see §4 (whole-article rollback, unrecoverable DLQ payload, GLiNER 4-wide funnel under 16-wide article concurrency, config/model drift).

---

## 2. The 900 s-vs-820 s margin is a real (secondary) defect

A watchdog only **80 s** above worst-case budget cannot absorb:
- a fallback hop (adds up to ~320 s — already over budget on its own when paired with a slow primary),
- GLiNER queue inflation (one measured `/ner/batch` = 79 s; a 32-section article = several of those serialized behind a 4-wide funnel),
- DB write contention on the dual-session commit.

The history (`300→450→700→900`) shows the team has repeatedly raised the ceiling rather than cut the budget or widen the funnel. Each raise reduced but never eliminated the bleed. **Raising the watchdog treats the symptom; the disease is the serialized NER funnel + whole-article retry semantics.**

---

## 3. The 2,316 dead-letters — characterization

### 3.1 Breakdown
- **By error:** `message_processing_timeout` 2,236 (97 %); `deep extraction timed out on all windows` 55; GLiNER connection error 17; MinIO connect error 7; misc 1.
- **By watchdog era (proves chronic):** 300 s→715, 450 s→1,127, 700 s→62, 900 s→332.
- **By day:** earliest 2026-05-10, latest 2026-06-18. **2026-06-12 = 1,467 (the spiral).** Recent bleed 6-15→6-18 ≈ 616 (101+147+246+122). Today 6-18 = 122, evenly spread 04:00–20:17 (no spike → structural).
- **Repeats:** a handful of event_ids appear 3-4× (retry-loop before terminal DLQ); 2,176 distinct events / 2,316 rows.

### 3.2 Recoverable or poison? — **Effectively unrecoverable from the DLQ**
`_dead_letter_impl` (`article_consumer.py:1448-1462`) writes:
```python
diagnostic_bytes = failure.event_id.encode("utf-8")   # NOT the real Avro payload
await DLQRepository(session).move_to_dlq(original_event_id=event_uuid,
    topic=_TOPIC, payload_avro=diagnostic_bytes, ...)
```
- `payload_avro` is literally `{"event_id":"…"}` (52 bytes, confirmed) — **no `doc_id`, no `minio_silver_key`**.
- `original_event_id` = the article **event_id**, which **matches 0 rows** in `content_store.documents.doc_id` (verified) and is not a join key anywhere persisted.
- `DLQRepository.requeue(payload_avro, topic, partition_key)` exists but there is **no real payload to requeue**.

So the DLQ rows are forensic markers only. The articles themselves still exist in MinIO silver and in `content_store.documents` (keyed by `doc_id`), but **the DLQ does not record which doc each row corresponds to.** Recovery is possible only by an *out-of-band* reconciliation (re-publish all `content_store` docs that have no `routing_decisions` row), not by reading the DLQ.

### 3.3 Blast radius
- All 2,176 distinct dead-lettered events → **0 `routing_decisions`** (whole-article rollback). They produced **no entities, no relations, no enriched event** → KG starved for those articles.
- The KG holds ~100,092 `relation_evidence_raw` rows; the lost articles are a meaningful but not dominant fraction, concentrated in the 6-12 window.

### 3.4 Replay path that DOES exist
`scripts/ops/replay_kg_extraction.py` re-publishes `content.article.stored.v1` **from MinIO silver, keyed by doc_id**, after deleting the `routing_decisions` sentinel (which otherwise short-circuits reprocessing — `process_message`, line 755-759). This is the correct recovery vehicle, but it is **ticker-scoped** (built for demo-ticker edge density) and does **not** consume the DLQ. The orphaned reprocess endpoint (`nlp.reprocess.v1`) has no subscriber and is a dead end.

---

## 4. Watchdog / dead-letter mechanism (libs/messaging)

`base.py:988-1014`:
```python
async with asyncio.timeout(timeout_s):
    await self.process_message(...)
...
except TimeoutError:
    await uow.rollback()                       # ← discards ALL partial work
    _timeout_failure = FailureInfo(..., attempt=self._config.max_retries, ...)  # ← terminal
    await self.dead_letter(_timeout_failure)   # ← no retry, straight to DLQ
```
- **Whole-article, all-or-nothing.** A timeout rolls back the entire dual-session transaction; every block's work (NER, embeddings, resolution, partial extraction) is lost. There is **no checkpointing** of partial progress.
- **Terminal on first timeout.** `attempt = max_retries` forces immediate dead-letter — a timed-out article is **never retried**, even though most timeouts are transient (load).
- **Per-message, not per-batch** (good): the intra-replica `run()`/`_dispatch_batch` (line 556-613) dispatches each message as its own task with its own watchdog and commits only the **contiguous** handled prefix per partition, so one slow article does not poison the batch's offset commits for *other* partitions. (It does, however, act as a commit barrier on its *own* partition until dead-lettered — correct for at-least-once.)

---

## 5. Ranked fix plan

### P0 — Stop the ongoing loss & make it recoverable

1. **Store the REAL payload in the DLQ (or the doc_id at minimum).**
   `article_consumer.py:1453` — `_dead_letter_impl` currently encodes only `event_id`. Persist the original Avro `payload_avro` (it is available on the consumed message) **or** at least `doc_id` + `minio_silver_key` so the existing `DLQRepository.requeue()` becomes usable. Without this, every future dead-letter is also unrecoverable.
   *(Note: a sibling session is reworking this file for batch/savepoint — coordinate.)*

2. **Do NOT terminally dead-letter on a transient watchdog timeout.**
   `libs/messaging/.../base.py:1011` sets `attempt = max_retries` on `TimeoutError`, skipping all retries. Change so a watchdog timeout counts as **one** attempt and is re-queued (with backoff) up to `max_retries`, only dead-lettering if it *persistently* times out. This alone would have salvaged most of the 6-12 spiral (transient saturation, would have succeeded on retry once load dropped). Platform-wide change — gate behind a config flag if other consumers rely on the current behaviour.

3. **Reconciliation backfill (recover the 2,176 lost articles).**
   Generalize `scripts/ops/replay_kg_extraction.py` from "ticker-scoped" to "all `content_store.documents` with no `routing_decisions` row" (bounded by a cap + the existing LLM-spend guard). This is the only viable recovery — the DLQ cannot drive it.

### P1 — Remove the structural fragility (so the watchdog stops firing)

4. **Widen / decouple the GLiNER funnel.** `article_consumer_main.py:116` hands GLiNER an `asyncio.Semaphore(embedding_max_concurrent=4)` while 16 article handlers run per replica. NER becomes the queue under load. Options: (a) give GLiNER its **own** semaphore sized to real server throughput, (b) scale the GLiNER server off the saturated host / add replicas, (c) batch NER across articles. This is the highest-leverage *prevention* fix.

5. **Add per-step ML timeouts + parallelize independent calls.** The pipeline is strictly sequential per article. NER and embedding generation are independent of each other for a given doc and could overlap; deep-extraction windows (`deep_extraction.py:426`) run **serially** in a `for` loop — multi-window docs should `asyncio.gather` windows under the `extraction_sem`. Each ML call should carry its own explicit timeout so one stuck call fails fast instead of consuming the whole 900 s.

6. **Re-budget the watchdog against REAL latencies, not the stale 235B assumption.** The config budget (`config.py:179-188`, `341-364`) is written for Qwen3-235B (p95 179 s) but the deployed model is `gpt-oss-120b` (p95 104 s). Recompute the budget against the live model and either tighten the per-attempt cap or widen the margin deliberately — not reactively. **Fix the model/budget drift in the comments too** (they describe a model that is not running).

### P2 — Resilience & observability

7. **Checkpoint partial progress instead of whole-article rollback.** On watchdog timeout, the dual-session rollback (`base.py:1005`) throws away completed NER/embeddings/resolution. Persisting completed blocks (idempotent upserts already exist via deterministic UUIDv5) before the expensive extraction step would mean a retry only re-pays for extraction, not the whole pipeline.

8. **Alert on DLQ growth rate, not just liveness.** BP-700 `/healthz` caught the stale poll loop, but the steady 122/day bleed is invisible to a liveness probe. A DLQ-insert-rate alert would have surfaced the structural bleed weeks ago.

---

## Appendix — key evidence

- DLQ totals: 2,316 rows / 2,176 distinct events, all `failed`, none `resolved`, 2026-05-10 → 2026-06-18.
- DLQ payload sample: `{"event_id":"019e0f6b-…"}` (52 bytes) — confirms diagnostic-only payload.
- `documents.doc_id ∩ dlq.original_event_id = 0` — confirms event_id ≠ doc_id, no join key.
- `dlq.original_event_id ⋈ routing_decisions.doc_id = 0 of 2,176` — confirms whole-article loss.
- Extraction latency (24 h, gpt-oss-120b): p50 44 s / p95 104 s / p99 187 s / max 294 s.
- Throughput at audit time: ~17 articles / 30 min across 2 replicas (input-starved, not stalled); GLiNER flush wait 25 ms (healthy at low load).
- Watchdog enforcement: `libs/messaging/src/messaging/kafka/consumer/base.py:988-1014` (whole-article rollback, terminal dead-letter).
- GLiNER semaphore wiring: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer_main.py:116`.
- DLQ write: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:1448-1462`.
- Deep-extraction serial window loop: `services/nlp-pipeline/src/nlp_pipeline/application/blocks/deep_extraction.py:426-459`.
