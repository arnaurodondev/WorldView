# Market-Data (S3) Consumer CPU Profile — 2026-06-21

**Scope (read-only):** the 4 market-data consumer containers flagged as the platform's top
non-DB CPU sink: `worldview-market-data-{quotes,ohlcv,intraday-resampling,fundamentals}-consumer-1`.
No code edits, no restarts, no mutations — diagnostics only.

**Headline:** the high CPU is **NOT per-message application work**. The dominant cost is
**librdkafka background threads busy-spinning on broker connection/metadata/fetch timeouts**
because all four consumers are wedged off the Kafka broker (connected at the TCP/DNS layer but
unable to complete `FetchRequest`/`MetadataRequest`/`ApiVersionRequest` before timeout). A
genuine secondary local-CPU path exists in **intraday-resampling** (a per-bar DB N+1 + Python
aggregation loop) but it is a distant second to the broker wedge. Fix the broker wedge first;
it is the cause of ~all of the quotes/ohlcv/fundamentals CPU and most of intraday's.

---

## Method & why py-spy was not usable

`py-spy dump`/`record` was attempted on all four containers. It is **not installed** in the
images and **cannot be used even if installed**: every container runs with an **empty
`CapAdd`** (`docker inspect … HostConfig.CapAdd = []`), so it lacks `SYS_PTRACE`. py-spy needs
`process_vm_readv`/ptrace to read another process's stacks → it would fail with a permission
error. (Network-restricted `pip install py-spy` also returned nothing.)

Fallback method used: live `docker stats`, Kafka consumer-group state
(`kafka-consumer-groups --describe`), container restart counts, raw container logs (including
librdkafka `%4|…` diagnostics), `/proc/1/stat` CPU-tick accounting, network/DNS checks, and
direct reading of the consumer + use-case + repository hot paths.

---

## Live evidence

### CPU vs. throughput — the smoking gun

| Consumer | CPU (3 samples) | Processed events / 2 min | Log lines / 60 s |
|---|---|---|---|
| quotes | 77% → 70% → **95%** | 0 | 0 |
| ohlcv | 81% → 92% → **96%** | 0 | 0 |
| intraday-resampling | 54% → 59% | 2–3 | 32–36 |
| fundamentals | 44% → 92% | 4 | 0–31 |

70–96% CPU at **zero processed messages and zero application log lines** is impossible for
per-message work. The CPU is being burned below the application — in the C client.

### Consumer-group state (`kafka-consumer-groups --describe`)

Topic `market.dataset.fetched` has **1 partition**, LOG-END-OFFSET ~42823, consumed by **4
separate consumer groups** (one per consumer).

| Group | CURRENT-OFFSET | LAG | Member (CONSUMER-ID) |
|---|---|---|---|
| market-data-quotes | 42589 | 232 | **none (`-`)** |
| market-data-ohlcv | 3279 | **39544** | **none (`-`)** |
| market-data-fundamentals | 38778 | 4045 | **none (`-`)** |
| market-data-intraday-resampling | 34090 | 8733 | `rdkafka-…` (assigned, draining slowly) |

Three of four groups have **no live member** despite the container running and pinning a CPU.
Only intraday is currently assigned — and even it is flapping (see logs below).

### librdkafka / consumer logs (the actual cause)

From `worldview-market-data-quotes-consumer-1` (representative; ohlcv/fundamentals/intraday
identical pattern):

```
%5 REQTMOUT … Timed out FetchRequest in flight (after 31913ms, timeout #0)
%4 SESSTMOUT … Consumer group session timed out (in join-state steady) after 60327 ms
   without a successful response from the group coordinator … revoking assignment and rejoining group
kafka_connectivity_probe_failed  consecutive_failures=1..3  error=_TIMED_OUT "Failed to get metadata: Local: Timed out"
kafka_unreachable_for_5min  action=exiting_with_code_2_for_dns_refresh   ← probe force-exits the process
%4 FAIL … Connection setup timed out in state CONNECT (after 30990ms in state CONNECT)
%4 FAIL … ApiVersionRequest failed: Local: Timed out … in state APIVERSION_QUERY
```

intraday-resampling (the "healthy" one) is also flapping:
```
%4 SESSTMOUT … session timed out (in join-state steady) after 61498 ms … revoking and rejoining
kafka_connectivity_probe_failed … error=_TRANSPORT "Failed to get metadata: Local: Broker transport failure"
```

### Restart / crash-loop accounting

- `ohlcv` consumer: **RestartCount = 127** — it is in a tight crash→reconnect→force-exit loop
  (the connectivity probe's `sys.exit(2)` fires every ~3 min, supervisor restarts it, the new
  process re-wedges). The 39544-message lag is the direct consequence.
- `quotes`/`fundamentals`: caught mid-cycle being force-exited by the same probe
  (`exiting_with_code_2_for_dns_refresh`, `quotes_consumer_stopped`, `SystemExit(2)`).

### Broker is healthy — this is a client/connection-path wedge, not a broker outage

- `worldview-kafka-1`: **Up 5 hours (healthy), 7.84% CPU, 823 MiB** — not overloaded, no error
  lines in its last 3 min of logs.
- DNS resolves correctly: `kafka → 172.20.0.34`; both broker and consumers are on
  `worldview_default` (172.20.0.x) — same subnet, no IP/listener mismatch.
- `KAFKA_ADVERTISED_LISTENERS=…PLAINTEXT_INTERNAL://kafka:29092` is correct for in-cluster
  clients.
- `kafka-consumer-groups … --bootstrap-server localhost:29092` (run *inside the broker*) works
  instantly — the broker serves requests fine to a local client.

The requests **from the consumer containers** time out in-flight (`CONNECT`/`APIVERSION_QUERY`/
`Fetch`/`Metadata` all 17–31 s) even though the broker is idle. This is a **network-path /
client-side wedge** between the consumer containers and the broker (e.g. a saturated or
half-broken bridge connection, an MTU/conntrack issue, or librdkafka socket state that the
30 s connection timeout + force-exit-and-restart is not clearing). It is consistent across all
four consumers and self-perpetuating (force-exit → fresh container → re-wedge).

---

## Per-consumer verdict

### 1. quotes — `quotes_consumer.py::process_message`
- **Dominant CPU op:** librdkafka reconnect/metadata-timeout spin (group has no member, 0
  messages processed, 70–95% CPU). **Not** application work.
- Per-message work *when healthy* is light: one S3 GET, one JSON parse of a single quote, an
  instrument lookup, one `quotes.upsert`, and a Valkey fan-out. Not a CPU concern.
- **Verdict: wasteful — 100% of current CPU is broker-wedge spin.**

### 2. ohlcv — `ohlcv_consumer.py` (batched path, `_process_partition_batch`)
- **Dominant CPU op:** same broker-wedge spin, **amplified by a 127× crash-loop**. The batched
  `run()` override calls `consume(num_messages=50, timeout=poll_timeout)` via
  `run_in_executor`; with no broker it returns immediately every cycle, so the asyncio loop
  *also* spins on top of the librdkafka thread spin.
- Per-message work *when healthy* is already well-optimized (Option B: concurrent S3 prefetch,
  one shared UoW + per-message SAVEPOINT, one combined `bulk_upsert_with_priority`, batched
  commit). No redundant recompute found.
- **Verdict: wasteful — broker-wedge spin + crash-loop; the code path itself is fine.**

### 3. intraday-resampling — `intraday_resampling_consumer.py` + `resample_ohlcv.py`
- **Two costs, both real:**
  - (a) broker-wedge spin / session-timeout flapping (same as the others), and
  - (b) **a genuine local CPU + DB N+1 hot path** — the one agent C flagged. Confirmed below.
- **Verdict: partially genuine work, but the hot path is badly shaped and should be vectorized
  regardless of the broker fix.**

#### The resampling hot path (genuine, fixable)
`IntradayResamplingConsumer.process_message` (lines 262–285) parses a JSONL batch into
`domain_bars`, then:
```python
for bar in domain_bars:                       # observed: 425–663 bars per message
    derived = await use_case.execute(bar)     # ResampledOHLCVUseCase.execute
```
`ResampledOHLCVUseCase.execute` (`resample_ohlcv.py:157`) loops the 5 target timeframes
(5m/15m/30m/1h/4h) and for **each** issues a **separate DB round-trip**:
```python
for target_tf in effective_targets:          # 5 timeframes
    source_bars = await self._uow.ohlcv.find_by_instrument_timeframe_datetime_range(...)  # 1 SELECT each
    derived = _aggregate_bars(...)            # Python max()/min()/sum() generators over source_bars
```
`find_by_instrument_timeframe_datetime_range` (`ohlcv_repo.py:341`) is a real per-call SELECT +
`[self._to_domain(row) for row in …]` materialization.

**Measured blast radius (from live logs):** `source_bars=663 → derived_bars=3315` per message.
That is **663 bars × 5 timeframes ≈ 3,315 individual SELECT round-trips per single Kafka
message**, each re-fetching an overlapping window of the same 1m bars, plus 3,315 Python-level
`max`/`min`/`sum` generator passes and 3,315 `_to_domain` row mappings. The aggregation is
re-derived from scratch on every bar even though consecutive bars in the same period share
almost all source rows. This is the classic per-bar Python/DB loop that should be a single
grouped/windowed query (or in-memory pandas/numpy resample over the already-parsed
`domain_bars`).

### 4. fundamentals — `fundamentals_consumer.py::_process_message_inner`
- **Dominant CPU op:** same broker-wedge spin (group has no member; observed being force-exited).
- Per-message work *when healthy* is moderate JSON/section parsing: `json.loads` of the EODHD
  payload, then iteration over ~18 sections, each section iterating quarterly/yearly/date-keyed
  sub-dicts and doing `handler(record)` + `extract_metrics` + `_upsert_metrics_for_record`
  **per row** (another per-row await loop, `_process_message_inner` lines 531–630), plus a
  best-effort snapshot upsert with extra SELECTs. This is genuinely heavier than quotes but is
  not the current CPU driver (throughput is ~4/2 min).
- **Verdict: current CPU is wasteful broker-wedge spin; the per-section/per-row await loop is a
  secondary, real-but-lower-priority cost worth batching later.**

---

## Prioritised, concrete optimizations

### P0 — Stop the broker-connectivity wedge (cause of ~all quotes/ohlcv/fundamentals CPU + most of intraday)
This is an **infrastructure/runtime incident**, not a code defect in the consumers. The
consumers are behaving as designed (probe → force-exit for a fresh DNS lookup); the restart is
simply not clearing the wedge. Recommended diagnosis/remediation (requires a mutation window,
out of scope for this read-only pass):
1. **Restart the broker's client connections / the consumer containers together** (a clean
   broker + consumer cycle, not just the consumer) to clear half-open sockets. The fact that a
   broker-local client works while in-container clients time out points at the network bridge,
   not the broker process.
2. **Inspect the docker network** (`worldview_default`): conntrack table, MTU, and any stale
   ARP/endpoint entries for 172.20.0.34. A bridge/conntrack issue produces exactly this
   "TCP connects, requests time out in-flight" signature.
3. **Tune librdkafka reconnect** so a wedged socket is dropped faster instead of spin-retrying
   for 30 s: set `socket.connection.setup.timeout.ms`, `reconnect.backoff.max.ms`, and
   `metadata.request.timeout.ms` lower (these flow through `ConsumerConfig` in
   `libs/messaging/src/messaging/kafka/consumer/base.py`). A tighter, backed-off reconnect
   spins the CPU far less than the current 17–31 s in-flight timeouts.
4. **Expected impact:** quotes/ohlcv/fundamentals drop from 70–96% to near-idle; intraday drops
   to whatever its genuine resampling work costs; the ohlcv 39k-message lag and 127× restart
   loop stop.

### P1 — Vectorize the intraday resampling loop (genuine local CPU + DB N+1)
**File:** `services/market-data/src/market_data/application/use_cases/resample_ohlcv.py`
(`ResampledOHLCVUseCase.execute`) and its caller
`…/consumers/intraday_resampling_consumer.py::process_message` (lines 281–285).

- **Eliminate the per-bar × per-timeframe SELECT N+1.** The full batch of source bars is
  *already in memory* as `domain_bars`. Resample in-memory by flooring each bar to each target
  period boundary and aggregating per `(target_tf, period_start)` group — no DB read per bar at
  all. A single `bulk_upsert_derived` of the final derived bars (which already exists) writes
  them.
  - This collapses **~3,315 SELECTs per message → 0**, and replaces 663×5 Python generator
    passes with one grouped pass.
- If a DB read is still wanted for cross-batch continuity, do **one** ranged SELECT for the
  whole batch window per timeframe (5 queries total) instead of one per bar (3,315).
- **Implementation note:** the natural form is `pandas`/`numpy` `resample`/`groupby` over the
  parsed bars (OHLC = first/max/min/last, volume = sum), or a pure-Python `dict[period_start]`
  accumulator if a new dependency is undesirable. Either is O(N) over the bars vs. the current
  O(N×5) DB round-trips.
- **Expected impact:** intraday's *genuine* CPU and its DB write-amplification drop by ~1–2
  orders of magnitude; the 8.7k lag drains far faster once the broker wedge (P0) is cleared.

### P2 — Reduce per-row await fan-out in fundamentals (secondary)
**File:** `…/consumers/fundamentals_consumer.py::_process_message_inner` (lines 531–630).
- Each fiscal-period row currently does `await handler(record)` + `await
  _upsert_metrics_for_record(uow, record)` individually. Accumulate all `FundamentalsRecord`s
  and all extracted metric rows per section and issue **one bulk upsert per section** (the
  repository already exposes `upsert_metrics(rows)` for the batched form).
- **Expected impact:** fewer DB round-trips per fundamentals message; lower tail latency on the
  `fundamentals_consumer_processing_ms` histogram. Lower priority — throughput is low and this
  is not the current CPU driver.

### P3 — Topic/partition + group sizing (architectural note)
`market.dataset.fetched` has **1 partition** but is fanned out to **4 consumer groups**, each
maintaining its own connection, heartbeat, and (in the wedge) reconnect spin against the single
broker. Each consumer also receives and **discards 3/4 of all messages** (every group sees
every dataset_type and filters to its own). This multiplies the connection/heartbeat load 4×
and the deserialize-and-discard churn. Worth considering post-incident:
- bump the partition count so the assigned consumers can actually parallelize, and/or
- route by `dataset_type` at the producer (separate topics or a key-partitioned topic) so each
  consumer only fetches the messages it will keep.

---

## Summary of genuine-vs-wasteful

| Consumer | Current CPU is… | Genuine work when healthy |
|---|---|---|
| quotes | **wasteful** (broker-wedge spin, 0 msgs) | light |
| ohlcv | **wasteful** (broker-wedge spin + 127× crash-loop) | already well-optimized (batched) |
| intraday-resampling | **mostly wasteful spin + a genuine, badly-shaped DB N+1 loop** | real, but should be vectorized (P1) |
| fundamentals | **wasteful** (broker-wedge spin) | moderate JSON/per-row work (P2) |

**Do P0 first** — it removes the bulk of the CPU across all four. **P1** is the one real code
optimization worth doing regardless (it also fixes a 3,315-SELECT-per-message write
amplification). P2/P3 are follow-ups.
