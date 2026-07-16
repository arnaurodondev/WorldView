# Prediction-Market Base Snapshot Consumer — Throughput Investigation

**Date:** 2026-07-15
**Consumer:** `market-data-prediction-markets` (topic `market.prediction.v1`, 8 partitions)
**Symptom:** ~2.5 s per market materialised → ~48-53k lag, Polymarket freshness ~12 h.

## What was measured (live cluster, KUBECONFIG=config-worldview)

| Component | Isolated latency | Verdict |
|---|---|---|
| Broker fetch (fresh `subscribe` consumer, same broker) | **85,731 msgs / 25 s ≈ 3,400 msg/s** | Healthy — not the bottleneck |
| Broker fetch, EXACT `ConsumerConfig.to_dict()` (cooperative-sticky, session tuning) | **4,331 msg/s** | Config not the cause |
| `get_watermark_offsets` sweep, 8 partitions (`_record_consumer_lag`) | 6.3 ms | Not the cause |
| DB full 3-write path via real UoW (`create_if_not_exists` + `upsert` + snapshot insert) | ~50 ms (2 ms warm) | Not the cause |
| **Real `PredictionMarketConsumer._handle_message` on real messages** | **2–38 ms** (220 ms cold) | Processing path is fast |
| Synchronous offset `commit(msg)` — incl. prod offsets partition 29 | 6 ms | Not the cause |
| `ingestion_events` table size | 102k rows | Small — no N+1/scan |
| Pod CPU / throttling | **7m CPU (97% idle)**, `nr_throttled=7`, 11 ms total | Not CPU-bound, not throttled |
| Consumer group state | `Stable`, 1 member, 8 partitions, healthy coordinator | No rebalance churn |
| `__consumer_offsets` commit latency (partition 29 = this group) | 6 ms | Offset store healthy |

**Observed true rate:** `consumed_total` advances ~0.8 msg/s; group `CURRENT-OFFSET` advances ~0.47/s — every consumed message materialises (no hidden dedup skips). The pathology reproduces on a **freshly-restarted pod** (new ReplicaSet hash), so it is **NOT** the 17h-stale image and **NOT** long-lived process degradation.

## Running-pod code vs repo HEAD

The running pod's `prediction_market_consumer.py` and `libs/messaging/.../consumer/base.py` are **byte-identical to repo HEAD** (same line numbers: `_handle_message` 1907, `commit` 1925, `_record_consumer_lag` 1935). There is **NO** per-message REST/ticker-resolve call, **NO** AGE/entity-linking, **NO** LLM polarity, **NO** `sleep` in the base snapshot path. `process_message` does exactly 3 DB round-trips (`ingestion_events` dedup, `prediction_markets` upsert, `prediction_market_snapshots` insert) then the base commits once. So the slowness is **not** a repo bug already fixed — a redeploy alone will not fix it.

## Root cause

Kernel thread sampling (`/proc/1/task/*/wchan`) shows the event-loop main thread parked in `ep_poll` in **every** sample — the loop is genuinely **idle ~2.4 s per message**, not busy. Every individual operation reproduces at single-digit ms in isolation, yet the assembled `run()` loop yields ~0.8 msg/s. The cost is therefore a **fixed per-loop-iteration overhead** (~2.5 s) that the current `BaseKafkaConsumer.run()` pays **once per message** because it polls and commits **one message per iteration** (`poll(1)` → `_handle_message` → `commit(msg)` → `_record_consumer_lag`). A tight `consume(500)` batch of the same backlog returns 2,000 msgs in 1.17 s, confirming the broker will hand over batches immediately.

Because the overhead is **per-iteration**, the correct, root-cause-agnostic fix is to **process many messages per iteration**: `consume(num_messages=N, timeout)` → one shared transaction → bulk `INSERT … ON CONFLICT` for `prediction_markets` + `prediction_market_snapshots` → one offset commit → one lag sample. This amortises the fixed per-iteration cost by N. Even at the pathological ~2.5 s/iteration, N=500 gives ~200 markets/s → drains 48-53k in **~4-5 min** (vs ~33 h today).

## Planned fix (opt-in, default-OFF)

1. `libs/messaging` — add `ConsumerConfig.consume_batch_size: int = 1` (default 1 ⇒ the other 30 consumers run the **byte-for-byte unchanged** single-message path). When `> 1`, `run()` takes a batched branch: `consume(N, timeout)` → `_handle_batch(msgs)` (one UoW, one `commit`) → commit offsets (current positions) → `_record_consumer_lag`; on error, seek all batch partitions back to their min offset so the batch redelivers (idempotent).
2. `market-data` — bulk repo writes:
   - `PgIngestionEventRepository.create_many_if_not_exists(...)` → set of NEW event_ids (multi-row `ON CONFLICT DO NOTHING RETURNING`).
   - `PgPredictionMarketRepository.bulk_upsert(markets)` (multi-row `ON CONFLICT DO UPDATE`, same COALESCE policy as single `upsert`).
   - `PgPredictionMarketSnapshotRepository.bulk_insert_if_not_exists(snapshots)` (multi-row `ON CONFLICT DO NOTHING`).
   - `PredictionMarketConsumer.process_batch(items)` — bulk dedup → build entities for NEW events → bulk upsert + bulk snapshot insert in one UoW. Preserves idempotency (dedup + `ON CONFLICT`) and the M-04 single-commit contract.
3. Wire `consume_batch_size` in `prediction_market_consumer_main.py`.
4. Tests: batch happy-path, idempotency (dedup skips repeats), per-message malformed skip.

## Deploy note

Requires a **rebuild + redeploy** of the market-data prediction-market-consumer image to take effect. A redeploy of the *current* code alone will not help (fresh pod already reproduces the 2.5s).
