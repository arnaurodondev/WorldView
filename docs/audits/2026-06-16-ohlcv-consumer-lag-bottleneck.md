# OHLCV Pipeline Lag — Bottleneck Investigation (read-only)

**Date:** 2026-06-16
**Scope:** market-ingestion (scheduler/worker/dispatcher) → `market.dataset.fetched` → market-data `ohlcv-consumer`
**Status:** Investigation complete. No code/schema/data changed.

---

## VERDICT (one line)

The bottleneck is the **CONSUMER materialize side (c)**, not the fetch side and not the
outbox/dispatch side. The fetch side is already fully batched (1000 symbols/call) **and is
currently idle** (producer rate = 0/s). The user's batching hypothesis is **directed at the
wrong stage**: batching the Alpaca fetch further cannot reduce the consumer lag, because the
lag is measured on `market.dataset.fetched`, where the pipeline emits **one message per symbol**
regardless of how the fetch was batched.

---

## Measured evidence (live, this session)

### Consumer group `market-data-ohlcv` on `market.dataset.fetched`

| Metric | Value |
|---|---|
| Topic partitions | **6** |
| Consumer instances / group members | **1** container, **1** rdkafka member holding **all 6 partitions** |
| Total lag | ~12,300 (flat) — per partition: P4=4006, P5=3442, P3=3298, P2=1252, P0=153, P1=149 |

### Production vs consumption rate (30s window)

```
dt = 31s
PRODUCTION  (end-offset delta) = 0   =>  0.000 msg/s   (LOG-END-OFFSET frozen at 61644)
CONSUMPTION (current delta)    = 11  =>  0.354 msg/s
LAG: 12288 -> 12277 (delta -11)
```

- **Producer rate is literally zero.** The end-offset does not move — the worker has drained its
  task queue. Worker logs show `tasks_claimed claimed=0 requested=10` on every poll. The fetch
  side has nothing left to do; the backlog is entirely sitting in Kafka waiting for the consumer.
- **Consumer rate ≈ 0.35 msg/s** — one symbol every ~2.8–3.0s, dead serial. Materialize log
  timestamps are evenly spaced ~3.01s apart (22:45:51, :54, :57, :00, :03, :06, :09, :12 …).

### Time-to-drain at the current rate

12,277 backlog ÷ 0.35 msg/s ≈ **9.7 hours** to clear (assuming no new production). This is why
the 1m high-water mark is frozen ~17h behind: the consumer simply cannot keep up.

---

## Findings against the four investigation questions

### 1. Where is the bottleneck?

**(c) CONSUMER MATERIALIZE.** Production = 0/s, consumption = 0.35/s. The slower stage is the
consumer by definition (the producer isn't even running). Each message is processed strictly
serially in `BaseKafkaConsumer`’s poll loop
(`libs/messaging/src/messaging/kafka/consumer/base.py`, the `_handle_message` dispatch at
~L1484/L1499): one message → one UoW → `process_message` → `uow.commit()` →
`self._consumer.commit(msg)` → `_record_consumer_lag()` → next message. No intra-poll
parallelism.

Per-message cost (~2.8s) is the sum of:
- **S3/MinIO `get_bytes`** claim-check download (`ohlcv_consumer.process_message`, L226) — one
  blocking object fetch per symbol.
- **Per-message synchronous Kafka commit** (`self._consumer.commit, msg` on the executor, base
  L~1501).
- **`_record_consumer_lag()` after EVERY message** (base L~1510 → method at
  `_record_consumer_lag`): this makes **two blocking librdkafka broker round-trips per assigned
  partition** — `get_watermark_offsets(tp, timeout=1.0)` **and** `position([tp])`. With **6
  partitions** assigned to this one consumer, that is up to **6×(watermark+position)** broker
  calls *after every single message*. The method's own docstring (PLAN-0087 D-P3-006) warns this
  is "up to 12s of event-loop blocking" with 12 partitions and was a known "wedged consumer"
  contributor. It is hopped onto the executor but still runs once per message, serialized in the
  loop.
- Dedup + content-hash queries + `bulk_upsert_with_priority` + the 1m quote write-through
  fan-out.

The `bulk_upsert_with_priority` itself
(`services/market-data/src/market_data/infrastructure/db/repositories/ohlcv_repo.py`) is a single
multi-row `INSERT … ON CONFLICT DO UPDATE` — it is **not** the dominant cost (a few hundred rows
per message is cheap). The dominant costs are the per-message S3 round-trip, the per-message
commit, and the per-message multi-partition lag-polling overhead, all multiplied by the fact that
there is exactly **one consumer doing everything sequentially**.

### 2. Does the Alpaca adapter already batch multiple symbols per call?

**Yes — and the prior audit (2026-06-15) is correct about the fetch.**
`AlpacaProviderAdapter.fetch_ohlcv_batch`
(`services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/alpaca.py`,
L210–307) sends up to `_BATCH_SIZE = 1000` comma-separated symbols in **one** HTTP call to
`/v2/stocks/bars` (equities) or `/v1beta3/crypto/us/bars` (crypto), splitting equity vs crypto and
chunking by 1000. `supports_batch` returns `True`.

The worker uses it: `Worker._try_batch_execute`
(`infrastructure/workers/worker.py`, L241–367) groups claimed tasks by (provider, timeframe),
calls `fetch_ohlcv_batch(symbols=…)` **once per group**, then —

**— critically — FANS OUT to one event per symbol.** After the single batched fetch, the worker
loops `for symbol, fetch_result in results_map.items()` (L333) and runs
`ExecuteTaskUseCase.execute_with_prefetched_result(matched_task, fetch_result)` **per symbol**.
Each per-symbol execution stores its own bronze/canonical object and writes its **own outbox
row**, which the dispatcher publishes as its **own** `market.dataset.fetched` message.

So: **fetch is batched 1000:1, but downstream events are 1:1 per symbol.** Batching the fetch
does nothing for the consumer message count.

### 3. What does one `market.dataset.fetched` message contain?

**One symbol.** The Avro schema `infra/kafka/schemas/market.dataset.fetched.avsc` has scalar
`symbol`, `timeframe`, `range_start/end`, and a single claim-check pair
(`canonical_ref_*`/`bronze_ref_*`) — there is **no list of symbols and no multi-symbol payload**.
The consumer (`ohlcv_consumer.process_message`) reads `value["symbol"]`, downloads that one
symbol's canonical object, and materializes that one symbol. Therefore:

> lag (message count) = number of (symbol × fetch-cycle) datasets

and the only way to cut the consumer's work is to **reduce message count** OR **speed up /
parallelize per-message materialize** — not to batch the upstream fetch.

### 4. Validate / correct the user's hypothesis

- **Correct part:** Alpaca *does* support multi-symbol + time-range 1m bars in one call (up to
  ~1000 symbols via `symbols=` CSV with `start`/`end`/`limit`), and the adapter *already*
  implements exactly that. The user's mental model of the Alpaca capability is accurate.
- **Wrong part:** the lag is **not** on the fetch side. It is on `market.dataset.fetched`, between
  the dispatcher and the consumer. The fetch is already batched **and currently idle** (0
  produced/s). Extending fetch batching "to cover all tasks" gives **zero** improvement to the
  consumer lag, because each fetched symbol still becomes its own message and the consumer still
  materializes one symbol at a time.
- **Where the user is partially right:** the diagnosis "the lag is just 1m-bar tasks for different
  tickers" is true — the backlog *is* ~12k per-symbol 1m datasets. But the lever is the
  **consumer / message-count side**, not the Alpaca call count.

---

## Highest-leverage optimizations (ranked)

### #1 — Scale the consumer to use all 6 partitions (immediate, no code) — ~6×
The topic has **6 partitions** but only **1 consumer instance** owns all of them. A consumer group
parallelizes up to `min(consumers, partitions)`. Run **6 replicas** of
`worldview-market-data-ohlcv-consumer` (group `market-data-ohlcv`); Kafka will assign one partition
each. Expected throughput: ~0.35 → **~2.1 msg/s** (≈6×). Drain time ~9.7h → **~1.6h**. This is
purely an ops/compose scaling change (replicas/`docker compose up --scale`), no code, and is the
single fastest lever. Caveat: partition skew (P4/P5/P3 hold most of the lag) means the ceiling is
6× only once the skewed partitions are co-drained; still by far the cheapest win.
- Code/config site: market-data ohlcv-consumer service definition in `infra` docker-compose;
  consumer group already fixed at `_GROUP_ID = "market-data-ohlcv"` in
  `ohlcv_consumer.py` L38.

### #2 — Reduce/stop the per-message lag-polling overhead (small code change) — meaningful
`_record_consumer_lag()` runs after **every** message and does 2 blocking broker calls per assigned
partition (`base.py`). Change it to run on a **time interval** (e.g. every N seconds or every K
messages) instead of per-message. This removes up to `2 × partitions` broker round-trips per
message from the critical path. Combined with #1 (1 partition per consumer) the impact is smaller,
but on the current single-consumer-6-partition topology it is large.
- Code site: `libs/messaging/src/messaging/kafka/consumer/base.py` — the
  `await loop.run_in_executor(None, self._record_consumer_lag)` call in the poll loop (~L1510) and
  `_record_consumer_lag`.

### #3 — Emit fewer, bigger dataset events (multi-symbol per message) (larger change) — large
The structural fix for message count: have the worker emit ONE `market.dataset.fetched` per
(provider, timeframe, batch) carrying all symbols (one canonical object holding all symbols' bars),
and have the consumer materialize the whole batch in one UoW + one `bulk_upsert_with_priority`.
This collapses ~1000 messages → 1, cutting both Kafka message count and per-message fixed overhead
(S3 GET, commit, lag poll) by ~1000×.
- Requires: schema change (`market.dataset.fetched.avsc` — add a multi-symbol/manifest variant,
  forward-compatible per R11), worker emit path (`worker.py` `_try_batch_execute` /
  `execute_task.py` persist path), and consumer materialize (`ohlcv_consumer.process_message` to
  loop symbols within one message). Higher effort; biggest ceiling. Note the 1m quote
  write-through and `is_backfill` semantics must be preserved per symbol.

### #4 — Cheaper per-message materialize (incremental)
Within the current 1-message-per-symbol model: skip the S3 round-trip where possible (the canonical
payload for 1m windows is small — consider inlining small payloads in the event, or batching S3
reads), and avoid the per-message synchronous commit by committing every K messages. Lower ceiling
than #1/#3 but stackable.

### Recommended sequence
**Do #1 now** (6 replicas — ~6× for free, drains the current 12k backlog in ~1.6h), **then #2**
(remove per-message lag polling overhead), and schedule **#3** (multi-symbol dataset events) as the
durable structural fix so steady-state 1m ingestion stops generating ~N-symbol messages per
minute. Further Alpaca fetch-batching is **not** recommended as a lag fix — it is already optimal
and idle.

---

## Key code sites referenced
- Alpaca batch fetch: `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/alpaca.py` (`fetch_ohlcv_batch`, L210–307; `supports_batch` L108)
- Worker fan-out (one event per symbol): `services/market-ingestion/src/market_ingestion/infrastructure/workers/worker.py` (`_try_batch_execute`, L241–367; per-symbol loop L333)
- Per-symbol event emission: `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py` (`execute_with_prefetched_result`, L90)
- Event schema (single `symbol`): `infra/kafka/schemas/market.dataset.fetched.avsc`
- Consumer materialize (one symbol/message, serial): `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py` (`process_message`, L173–398)
- Bulk upsert: `services/market-data/src/market_data/infrastructure/db/repositories/ohlcv_repo.py` (`bulk_upsert_with_priority`)
- Serial dispatch + per-message commit + per-message lag poll: `libs/messaging/src/messaging/kafka/consumer/base.py` (poll loop ~L1484–1510; `_record_consumer_lag`)
