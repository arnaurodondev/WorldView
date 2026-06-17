# OHLCV Consumer Batching — Long-Term Design Decision (Option A vs Option B)

**Date:** 2026-06-16
**Scope:** READ-ONLY design investigation. No code/schema/data changes made.
**Author:** Claude (design investigation)
**Related:** `docs/audits/2026-06-16-ohlcv-consumer-lag-bottleneck.md`, `docs/audits/2026-06-15-market-ingestion-worker-claims-zero.md`

---

## TL;DR — Recommendation

**Sequence the fix in three stages, do not pick a single silver bullet:**

1. **NOW (ops, zero code):** Scale `market-data-ohlcv-consumer` to **6 replicas** (matches the 6 partitions). ~6× throughput, drains the current ~12k backlog in well under 2h. This is the immediate lever and composes with everything below.
2. **SHORT-TERM (contained consumer change):** **Option B — consumer micro-batching**, implemented **consumer-local** (NOT in `BaseKafkaConsumer`). Each cycle, drain a bounded window of already-buffered `market.dataset.fetched` messages, parallelize the S3 GETs, do **one** combined `bulk_upsert_with_priority` across all symbols, commit once, poll lag once. Removes the per-message commit + per-message lag-poll overhead and amortizes DB round-trips. Lower risk than A because it touches **one file** and **no Avro schema**.
3. **STRUCTURAL ENDGAME (optional, only if B + replicas is insufficient):** **Option A — multi-symbol payload**, done as a **v2 topic** (`market.dataset.batch.fetched.v1`), NOT an in-place mutation of the shared `market.dataset.fetched` schema. The current topic is a **shared bus consumed by 9 consumer groups**; an in-place breaking change to it is the highest-blast-radius option in this codebase.

**Why not "just A"?** Option A is the highest theoretical ceiling (collapses ~1000:1 message count) but it requires a producer-side restructure (the fan-out is structural — see §2), a new S3 object shape, a new schema/topic, and re-plumbing the per-symbol partition-key ordering guarantee that downstream KG consumers depend on. It is an "endgame," not a first move.

**Why B before A?** B is reversible, schema-free, single-file, and captures most of the per-message *fixed* overhead (commit, lag-poll) that the prior audit identified as dominant alongside the S3 round-trip. It buys time and may make A unnecessary.

---

## 1. Current Consumer Loop — Precise Map

### Base loop is strictly single-message (verified)

`libs/messaging/src/messaging/kafka/consumer/base.py`, `BaseKafkaConsumer.run()` (L1399–1529):

```
while not stopped:
    _maybe_apply_backpressure()                       # no-op unless policy set
    msg = await run_in_executor(consumer.poll, 1.0)   # ONE message
    if msg is None / error: continue
    await _handle_message(msg)                          # deserialize → dedup → UoW → process → commit-UoW → mark_processed
    if not auto_commit:
        await run_in_executor(consumer.commit, msg)    # PER-MESSAGE Kafka offset commit
    await run_in_executor(_record_consumer_lag)        # PER-MESSAGE lag poll
```

- **`poll()` returns exactly one message.** There is **no** `consume(num_messages=...)` anywhere in the loop.
- **Per-message Kafka commit** (`self._consumer.commit, msg`) at L1502.
- **`_record_consumer_lag()` after EVERY successful message** (L1512). That method (L1062–1100) iterates the assignment and makes **two blocking librdkafka broker round-trips per assigned partition** (`get_watermark_offsets(tp, timeout=1.0)` + `position([tp])`). With one consumer holding all 6 partitions that is up to **12 broker round-trips after every single message**.

### Is batch-consume supported at all? — No.

Confirmed by grep across `libs/messaging` and all `services/*/src`: **no consumer uses `confluent_kafka.Consumer.consume(num_messages=...)`**. Every consumer in the platform runs the single-message base loop above. The base class docstring at `_handle_failure` mentions a "batch-dispatching subclass (e.g. the nlp-pipeline article consumer)" and the `_handle_failure` return value (`True`=settled / `False`=seek-back barrier) exists for such a subclass — but the **base `run()` loop ignores that return value** and never batches. So:

> **Option B as a base-class feature does not exist today.** Implementing B in the base class would be a new shared-lib capability touching idempotency/commit/DLQ semantics for **all 30+ consumers**. Implementing B **consumer-local** (the OHLCV consumer overriding `run()` or adding its own drain-and-batch loop) is contained to one file. **Do the consumer-local variant.**

### OHLCV consumer specifics

`services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py`:

- `process_message` (L173–398) per message: filter `dataset_type=="ohlcv"` (L181) → content-hash + event-id dedup via `ingestion_events.create_if_not_exists` (L200–210) → `object_storage.get_bytes(bucket, key)` (S3 GET, L226) → parse JSONL (L232) → resolve/create instrument (+ outbox `InstrumentDiscovered/Updated`, L244–300) → `ohlcv.bulk_upsert_with_priority(domain_bars)` (L326) → **1m quote write-through** (L347–391, freshness-gated, with `schedule_quote_cache_fanout`).
- Dedup is **DB-backed** (`ingestion_events` table) plus the `ValkeyDedupMixin` belt-and-braces. The consumer does **not** opt into `enable_persistent_retry` → `_handle_failure` runs the **OFF path = commit-as-handled** (a failed message is logged + offset advances; no seek-back).
- DLQ is DB-only (`failed_tasks` rows), no Kafka DLQ emitter wired.

### Producer fan-out is structural (1 symbol = 1 task = 1 S3 object = 1 event)

`services/market-ingestion/.../strategies/pipeline.py` L387–407: `MarketDatasetFetched` is emitted inside the **per-symbol task** completion path. Each task has its own `canonical_ref` (one S3 JSONL object per symbol) and its own watermark/sha256 gate. Kafka key = `{provider}:{symbol}` (`mapper.py to_kafka_key`). So although the *Alpaca HTTP fetch* batches up to 1000 symbols, the pipeline **immediately splits back to one task per symbol** for watermarking, S3 storage, and eventing. **Option A must change this producer structure**, not just the schema.

### Topic facts (verified live)

`infra/kafka/init/create-topics.sh` L37 → `market.dataset.fetched:6:1`. Live `kafka-topics --describe`: **PartitionCount 6, RF 1, retention 30d**. Compose `market-data-ohlcv-consumer` (docker-compose.yml L871) has **no `deploy.replicas`** → single instance → **5 of 6 partitions' parallelism idle**.

### `market.dataset.fetched` is a SHARED BUS — 9 consumer groups

The single topic carries every dataset type, demultiplexed by `dataset_type` string. Consumer groups that subscribe and filter:

| Service | Group | dataset_type filter |
|---|---|---|
| market-data | `market-data-ohlcv` | `ohlcv` |
| market-data | `market-data-intraday-resampling` | `ohlcv` |
| market-data | `market-data-quotes` | `quotes` |
| market-data | `market-data-fundamentals` | `fundamentals` |
| market-data | `market-data-insider-transactions` | `insider_transactions` |
| knowledge-graph | (fundamentals) | `fundamentals` |
| knowledge-graph | (insider_transactions dataset) | `insider_transactions` |
| knowledge-graph | (earnings_calendar) | `earnings_calendar` |
| knowledge-graph | (economic_events) | `economic_events` |
| knowledge-graph | (macro_indicator) | `macro_indicator` |

**This is the central fact for blast radius.** Any change to the *wire schema* of `market.dataset.fetched` affects all 9 groups' deserialization. (Two market-data groups — `ohlcv` and `intraday-resampling` — both consume `ohlcv`, so a multi-symbol OHLCV payload must be understood by *both*.)

---

## 2. Option-by-Option Assessment

### Throughput ceiling

Grounded in the prior audit's measurement: **0.354 msg/s**, ~3s/message, dominated by (a) per-message S3 GET, (b) per-message Kafka commit, (c) per-message multi-partition lag-poll (up to 12 broker round-trips).

- **Current (1 replica):** ~0.354 msg/s. Backlog ~12k → ~9.4h to drain at steady state (it was flat → effectively never).
- **+6 replicas only:** ceiling ≈ 6 × per-replica, BUT bounded by **partition skew** (audit: P4/P5/P3 hold ~10.7k of 12.3k). Realistically ~3–5× on the current skewed backlog, ~6× once skew evens out. Backlog drains in ~1.5–2h. Bottleneck moves to per-replica per-message overhead (still S3 + commit + lag-poll per message).
- **Option B (micro-batch, consumer-local), 1 replica:** removes per-message commit and per-message lag-poll (replace with one-per-batch), parallelizes the N S3 GETs (asyncio.gather), and does one combined bulk upsert. The per-message *fixed* overhead collapses by the batch factor; the **floor becomes the N parallel S3 GETs** (still N objects — B does not reduce object count) and the single bulk upsert. Estimate: per-replica throughput improves several-fold (the audit attributes the 3s/msg largely to commit + lag-poll + S3; B kills the first two and parallelizes the third). With 6 replicas, multiplies again.
- **Option A (multi-symbol payload), 1 replica:** collapses message count ~1000:1. One event → one (multi-symbol) S3 object → one bulk upsert → one commit → one lag-poll for ~1000 symbols. This is the **highest ceiling**: the per-symbol Kafka/commit/lag overhead effectively vanishes; the cost becomes one large S3 GET + one large bulk upsert per ~1000 symbols. Bottom-out: DB upsert throughput and S3 object size.
- **Best combination:** A (or B) + 6 replicas. A+replicas is the structural maximum; B+replicas is the pragmatic near-maximum without a schema change.

| Config | Rough throughput | Backlog (~12k) drain |
|---|---|---|
| Current (1×) | 0.354 msg/s | ~9h+ (was flat) |
| +6 replicas only | ~1.5–2 msg/s effective (skew-bounded), ~2 msg/s post-skew | ~1.5–2h |
| Option B, 1× | ~1.5–3 msg/s (commit+lag removed, S3 parallel) | ~1.5–2.5h |
| Option B + 6× | ~9–18 msg/s | ~10–20 min |
| Option A, 1× | message count ÷ ~1000 → effectively backlog-as-symbols drains in minutes | minutes |
| **Option A/B + 6×** | structural max | minutes |

*(Figures are order-of-magnitude, grounded in 0.354 msg/s and the audit's 3s/msg breakdown — exact numbers depend on S3 latency and DB upsert width.)*

### Blast radius / invasiveness

**Option A (multi-symbol) — HIGH. Touches:**
1. **Avro schema** — new repeated array of `{symbol, exchange, timeframe, canonical_ref_*, row_count, range_*, is_backfill}` OR a single claim-check to a multi-symbol S3 object. Because the topic is a **9-group shared bus** (§1), this is **not** a safe in-place edit → use a **v2 topic** `market.dataset.batch.fetched.v1`.
2. **Producer** — `pipeline.py` must aggregate per-symbol tasks into a batch event and write a **multi-symbol S3 object** (today each task writes its own object and emits its own event at L387–407). This crosses the watermark/sha256 logic, which is currently per-symbol — non-trivial.
3. **S3 object shape** — new multi-symbol canonical object (or keep per-symbol objects but list many refs in one event; the latter keeps N S3 GETs, reducing only Kafka overhead — i.e. "A-lite").
4. **Both `ohlcv` consumers** — `OHLCVConsumer` and the `IntradayResamplingConsumer` both filter `dataset_type=="ohlcv"` and must learn the batch shape.
5. **Partition-key / ordering** — today every event is keyed `{provider}:{symbol}` so per-instrument events are ordered (KG depends on causal order of `instrument.discovered`→enrichment, see L275/L297 comments). A batch event cannot be keyed per-symbol; you'd need to preserve per-instrument ordering for the outbox `InstrumentDiscovered/Updated` emissions some other way.
6. **Dedup semantics** — event-id dedup becomes per-batch; per-symbol content-hash dedup (`exists_by_content_hash`) must move inside the batch loop.

**Option B (micro-batch, consumer-local) — LOW (if kept consumer-local). Touches:**
1. **`ohlcv_consumer.py` only** — add a drain-and-batch loop (override `run()` or add a batching wrapper that calls `consumer.consume(num_messages=X, timeout=...)`, or accumulates from repeated `poll()`), then process the window together.
2. **No schema change, no producer change, no other consumer affected.**
3. Risk surface: must re-implement the commit/lag/dedup/DLQ logic that the base loop currently provides per-message (see Idempotency below). This is the real cost of B — you are forking a slice of the base loop.

**Option B as a base-class feature — HIGH (avoid).** Would change commit/dedup/DLQ/retry for all 30+ consumers. Not warranted for one hot consumer.

### Idempotency & failure semantics

Both options must preserve: event-id + content-hash dedup, retry/DLQ on partial failure, offset-commit correctness, `is_backfill` handling, and the 1m quote write-through.

- **Option A:** **Hardest on partial failure.** If 1 of ~1000 symbols in a batch event fails (bad bar, S3 partial, one upsert constraint), the whole event either commits (silently dropping that symbol) or fails (re-processing 999 good symbols → relies on per-symbol idempotency to be safe, which it is via `bulk_upsert_with_priority` + content-hash, but it re-does the work). Event-id dedup is now coarse (per batch). You want per-symbol sub-idempotency so a retried batch skips already-materialized symbols. Quote write-through and `is_backfill` are already per-symbol fields → fine to keep per-symbol inside the batch.
- **Option B:** **Easier, but you own the commit barrier.** Process X messages, then **commit only the highest contiguous offset whose entire batch succeeded**. If symbol k fails, do NOT commit past it (commit up to k-1; let k+ redeliver). The base loop's per-message `commit(msg)` must become a deliberate "commit the last fully-succeeded message" call. Each message keeps its own event-id/content-hash dedup (unchanged — still per-symbol). DLQ a single poison message individually rather than failing the whole window. `is_backfill` and quote write-through stay exactly as today (per message). The base `_handle_failure` return-value contract (`True`=settled, `False`=seek-back barrier) is the intended hook for exactly this — but since the OHLCV consumer is on the **OFF retry path**, a simpler "commit last-good offset, DLQ the bad one to `failed_tasks`" is sufficient and matches current behavior.

**Verdict:** B has strictly simpler failure semantics because dedup/DLQ stay per-symbol; only the commit point changes. A forces coarser dedup and a partial-failure policy.

### Forward-compatibility (R5 / R11) for Option A

The schema **cannot** safely go scalar-`symbol` → multi-symbol in place: 9 consumer groups deserialize this topic, and removing/repurposing the required `symbol` field is a breaking change (R11 forbids removing/renaming). Options:
- **Additive repeated field on the same topic:** add an optional `datasets: ["null", {array of records}]` (default null) while keeping scalar fields populated for legacy consumers. Awkward (two parallel representations) and every consumer must decide which to read; the scalar fields can't represent N symbols, so you'd emit either-or, complicating all 9 readers.
- **New v2 topic `market.dataset.batch.fetched.v1` (RECOMMENDED if A is pursued):** clean schema, only the OHLCV-path consumers subscribe, legacy topic untouched, gradual cutover, trivial rollback. This is the R5/R11-clean path.

### Interaction with the 6-partition / replica-scaling lever

Both options **compose** with scaling to 6 replicas:
- **+replicas** is orthogonal: it parallelizes across partitions regardless of payload shape. It is the only lever that needs **zero code** and should ship first.
- **Option B** raises **per-replica** throughput (less fixed overhead per message), so B + 6 replicas multiplies.
- **Option A** raises per-replica throughput even more (≈1000× fewer messages), but with ~1000:1 fewer messages the **6-partition parallelism matters less** (few large messages spread less evenly) — A partially substitutes for replica scaling rather than multiplying with it. With A, partition skew also becomes coarser (a single batch message can dominate a partition).

---

## 3. Quantified Summary

(See table in §2.) Anchored to measured **0.354 msg/s** and **~3s/msg** (audit-attributed mostly to S3 GET + per-message commit + 12-round-trip lag poll), backlog **~12k**:

- **Current:** ~0.35 msg/s → backlog effectively never drains (flat).
- **+6 replicas:** ~6× ceiling, skew-bounded to ~3–5× on the current backlog → **drain ~1.5–2h**.
- **Option B (1×):** kill per-message commit + per-message lag-poll, parallelize S3 → per-replica several-fold → **drain ~1.5–2.5h**; **B + 6× → ~10–20 min**.
- **Option A (1×):** ~1000:1 message collapse → **drain in minutes**; A + 6× similar (replica benefit diminishes).
- **Best:** **B (or A) + 6 replicas → minutes**, with steady-state headroom of 10–50× current.

---

## 4. Recommendation (Opinionated)

**Ship in this order:**

### Stage 1 — Scale replicas now (ops, zero code)
Run `market-data-ohlcv-consumer` at **6 replicas** (cooperative-sticky assignor is already the default in `ConsumerConfig`, so incremental rebalancing is in place). Immediate ~6× and drains the current backlog within ~2h. **No risk, no merge.**

- Site: `infra/compose/docker-compose.yml` `market-data-ohlcv-consumer` service (add scaling / run multiple instances).
- Guard: partition skew (P4/P5/P3 heavy) means the *first* drain is uneven; that's transient.

### Stage 2 — Option B, consumer-local micro-batching (the long-term consumer fix)
Implement batching **inside `ohlcv_consumer.py`** (do **not** touch `BaseKafkaConsumer`). Per cycle: drain up to X buffered messages (`consumer.consume(num_messages=X, timeout=small)` or accumulate via repeated `poll()`), filter `dataset_type=="ohlcv"`, **`asyncio.gather` the S3 GETs**, accumulate `domain_bars` across all symbols, do **one** `bulk_upsert_with_priority`, run the per-symbol dedup/quote-write-through as today, then **commit the highest contiguous fully-succeeded offset once** and **poll lag once**.

- Site: `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py` (+ its `_main`).
- Key risks to guard:
  - **Commit barrier:** never commit past a failed message; DLQ the single poison message to `failed_tasks` and continue (preserves current OFF-path behavior at batch granularity).
  - **Per-symbol dedup unchanged:** keep `create_if_not_exists` / `exists_by_content_hash` per message inside the loop — do not coarsen dedup.
  - **session.timeout vs batch time:** a large X must finish within `message_processing_timeout_s` (45s) / `session_timeout_ms` (60s). Keep X bounded (e.g. 25–100) so a batch never out-runs the heartbeat window (the exact failure mode documented in `ConsumerConfig` L181–194).
  - **Quote write-through + `is_backfill`:** keep per-symbol (already per-message fields) — no change.
- Why this is the long-term consumer fix: it captures the dominant per-message *fixed* overhead the audit identified, is reversible, schema-free, single-file, and stacks with replicas.

### Stage 3 — Option A, only if needed, as a v2 topic
If B + 6 replicas still cannot keep up (e.g. universe grows to many thousands of symbols × 1m cadence), pursue the structural collapse via a **new `market.dataset.batch.fetched.v1` topic** carrying many `{symbol, ref, …}` records (or one multi-symbol S3 object). Do it as v2, not in place — the current topic is a 9-group shared bus and R11 forbids the breaking edit.

- Sites: new `.avsc`; `pipeline.py` producer aggregation + multi-symbol S3 write; `OHLCVConsumer` + `IntradayResamplingConsumer` batch readers; create-topics.sh.
- Key risks to guard:
  - **Per-instrument ordering** for the outbox `InstrumentDiscovered/Updated` emissions (today guaranteed by `{provider}:{symbol}` key — a batch event breaks it; preserve ordering downstream).
  - **Partial-failure policy** (1-of-N symbol fails) + **per-symbol sub-idempotency** on batch retry.
  - **Coarser partition skew** with few large messages.

**Bottom line:** the *long-term* answer the user is asking for is **Option B (consumer-local) as the consumer fix, preceded immediately by replica scaling, with Option A held in reserve as a v2-topic structural endgame.** Do not implement Option B in the shared base class, and do not mutate the shared `market.dataset.fetched` schema in place.
