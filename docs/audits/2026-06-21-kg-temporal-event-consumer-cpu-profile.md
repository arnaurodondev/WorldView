# KG temporal-event consumer — CPU profile (READ-ONLY investigation)

**Date:** 2026-06-21
**Target:** `worldview-knowledge-graph-temporal-event-consumer-1`
**Service:** knowledge-graph (S7), consumer group `kg-service-group-temporal-event`
**Topic:** `intelligence.temporal_event.v1`
**Observed:** sustained ~87% CPU (sampled 61–106%), one of the platform's top CPU consumers.
**Method:** py-spy (dump + native record), `/proc/1/task/*/stat` per-thread CPU accounting, container logs, broker reachability — all read-only. No code edits, commits, or restarts.

---

## TL;DR — the CPU burn is NOT temporal-event processing

The temporal-event handler (`is_in_sector` exposure logic, `entity_event_exposures` fan-out) is **completely innocent**. It has processed **zero messages in the last 60 minutes** and the Python interpreter thread is **0% CPU**.

**The entire ~87% CPU is burned by librdkafka's background `rdk:main` thread spinning in a connection-retry storm because this consumer cannot establish a TCP connection to the Kafka broker.** It is a *failed-connection hot loop*, not a workload.

This is an infrastructure/connectivity fault surfacing as CPU, not a hot code path. Optimising the exposure-write path would have **zero** effect.

---

## Evidence

### 1. Python is idle; a native librdkafka thread owns all the CPU

py-spy `dump --pid 1` (5 consecutive samples) — MainThread **always idle**:

```
Process 1: python -m knowledge_graph...temporal_event_consumer_main
Thread 1 (idle): "MainThread"        # every single sample
```

Per-thread CPU accounting from `/proc/1/task/*/stat` (utime+stime), 5-second delta:

```
   tid comm                  cum_jif       d5s    cpu%
    14 rdk:main               117254       320   64.0%   ← librdkafka main thread
  2114 rdk:broker1              2113         7    1.4%
    13 rdk:broker-1             1983         5    1.0%
    15 rdk:broker-1             2021         5    1.0%
     1 python                   5489         0    0.0%   ← message handler: IDLE
```

`rdk:main` has accumulated **117,254 jiffies (~1,172 CPU-seconds)** vs ~5,489 for Python and ~2,000 per broker thread — a >20× dominance. Over a 5 s window it burns 64% of a core while Python burns nothing. A `--native` py-spy record confirmed all stacks collapse into `libc.so.6` (librdkafka's internal spin), not Python frames.

### 2. The consumer cannot reach the broker — connection-retry storm

Container log tail (rdkafka level-4/5 messages):

```
%5 REQTMOUT  kafka:29092/bootstrap: Timed out ApiVersionRequest in flight (after 24850ms)
%4 FAIL      kafka:29092/bootstrap: ApiVersionRequest failed: Local: Timed out
%4 FAIL      GroupCoordinator: kafka:29092: Connection setup timed out in state CONNECT (15246ms)
%4 FAIL      kafka:29092/1: Connection setup timed out in state CONNECT (40372ms)
{"event":"kafka_connectivity_probe_failed", "consecutive_failures":3, ...
 "error":"KafkaError{code=_TRANSPORT,val=-195,str=\"Failed to get metadata:
          Local: Broker transport failure\"}"}
{"event":"kafka_unreachable_for_5min", "action":"exiting_with_code_2_for_dns_refresh", ...}
```

librdkafka tries `kafka:29092`, the connection setup times out, it immediately retries — endlessly. That retry loop is what `rdk:main` spins on. Meanwhile the BP-700 connectivity probe (`base.py:_connectivity_probe_loop`) force-exits the process every ~5 min (`sys.exit(2)`), the orchestrator restarts it, fresh DNS, same failure, spin resumes.

### 3. DNS resolves, broker is "healthy", but TCP does not connect

```
getent hosts kafka       → 172.20.0.34  kafka      (DNS OK)
docker ps | grep kafka   → worldview-kafka-1  Up 5 hours (healthy)
networks: kafka=172.20.0.34  temporal-consumer=172.20.0.35  (same worldview_default bridge)
```

So name resolution and the broker process are fine — the **TCP path between this container and the broker is broken** (connection setup times out at the 10 s `socket.connection.setup.timeout.ms` we configured, then 15–40 s on coordinator/broker sockets).

### 4. Broker-wide, worst on this consumer

Other KG consumers also logged rdkafka connection errors in the last 5 min (enriched=5, instrument=3, entity=1) but **recovered** — they sit at <2% CPU. The temporal consumer is the only one stuck spinning:

```
knowledge-graph-temporal-event-consumer-1   61.55%   ← stuck reconnecting
knowledge-graph-enriched-consumer-1           0.99%
knowledge-graph-instrument-consumer-1         0.66%
knowledge-graph-entity-consumer-1             1.63%
knowledge-graph-fundamentals-consumer-1       0.50%
worldview-kafka-1                            91.31%   ← broker also hot
```

The broker itself is at 91% CPU. The reconnect storm (this consumer hammering setup requests + the broker's own load) is plausibly self-reinforcing: the broker is too loaded to complete the TCP/ApiVersion handshake within the timeout, the client gives up and retries, adding more handshake load.

### 5. Timeline rules out startup ordering

```
kafka              StartedAt 2026-06-21T16:57:56Z
temporal-consumer  StartedAt 2026-06-21T17:27:29Z   (30 min AFTER broker)
```

The consumer started well after the broker, so this is not a "joined the network before kafka was up" race. The broker has been up only 5 h while consumers have been up longer in prior history — consistent with a **broker restart ~5 h ago leaving stale conntrack / half-open sockets** on some clients, a known librdkafka-after-broker-restart failure mode this repo has hit before (BP-700 reconnect logic, the "silent-consumer-death" incident, and the `socket.connection.setup.timeout.ms` 30s→10s tuning all reference it).

---

## Root cause

**A Kafka broker connectivity fault (broker overloaded / stale TCP path after the ~5 h-ago broker restart) puts this consumer's librdkafka client into a perpetual connection-setup-timeout → immediate-retry loop. That retry loop, running in the native `rdk:main` thread, is the entire CPU cost. The Python temporal-event handler does no work and uses no CPU.**

The per-event graph traversal / exposure fan-out hypotheses from the brief are **disproven**: 0 messages processed, 0% Python CPU. (For the record, the handler is also genuinely cheap — see "Handler is not a risk" below.)

---

## Recommended actions (prioritised)

### P0 — Operational: clear the connectivity fault (root cause)
This is an ops fix, not a code change.
1. **Recycle the wedged consumer**: `docker restart worldview-knowledge-graph-temporal-event-consumer-1`. A fresh process with a fresh socket usually re-handshakes cleanly once the broker has spare CPU. (The in-process BP-700 force-exit is *supposed* to do this every 5 min but the orchestrator's `RestartCount=0` suggests it is being restarted in-place / the loop re-wedges immediately.)
2. **Investigate the broker's 91% CPU** (`worldview-kafka-1`) — if the broker is saturated it cannot complete handshakes within the 10 s setup timeout, which *causes* the client spin. Likely correlated with the overloaded `postgres-intelligence-1` / overall host pressure noted in the brief. Reducing host CPU contention may let the handshake complete.
3. If the broker restarted ~5 h ago, a one-time bounce of the stuck consumers (or the broker) clears stale conntrack.

### P1 — Code: cap the reconnect spin so a failed connection cannot burn a full core
The reconnect loop should back off, not hot-spin. Two concrete levers in
`libs/messaging/src/messaging/kafka/consumer/base.py`:

- **`ConsumerConfig.socket_connection_setup_timeout_ms` (currently 10_000, line ~334)**: at 10 s, a failing client issues ~6 setup attempts/min; librdkafka's internal retry between them is tight. This is fine, but combined with `reconnect.backoff.ms` / `reconnect.backoff.max.ms` (NOT currently set in `to_dict()`, lines ~357-374) the client reconnects with near-zero delay. **Add `reconnect.backoff.ms` (e.g. 1000) and `reconnect.backoff.max.ms` (e.g. 10000)** to the rdkafka config so a down broker is retried with exponential backoff instead of a hot loop. This directly bounds the `rdk:main` spin.
- The Python-side `poll()` is already a 1 s blocking call via `run_in_executor` (`base.py:1734`, `poll_timeout_seconds=1.0`) and is NOT the spin — leave it.

Expected impact: drops the failed-connection CPU from ~one full core to near-idle while disconnected, across **every** consumer in the platform (this is shared lib code), not just temporal-event.

### P2 — Observability: alert on the spin, not just the silence
- The `kafka_consumer_last_progress_timestamp` heartbeat (BP-700) goes stale on a dead loop — good. But a *reconnect-spinning* consumer also never progresses, so the staleness alert should already fire here; verify it does and that it pages before 5 h of wasted CPU.
- Add a CPU-vs-throughput alert: a consumer at >50% CPU with `kafka_messages_consumed_total` flat is, by definition, spinning.

---

## Handler is not a risk (for completeness)

`services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/temporal_event_consumer.py::process_message` was reviewed. Per event it does:
- 1 upsert to `temporal_events` (`TemporalEventRepository.upsert_by_natural_key`),
- a loop over `exposed_entities[]`: for GLOBAL scope, one `SELECT entity_type ... LIMIT 1` per entity (`_get_entity_type`, line 79) then one `entity_event_exposures` upsert per non-rejected entity.

There is **no graph/`is_in_sector` traversal here** — PRD-0018 defers company exposure to *query time*, and the code matches that: GLOBAL events only link sector/industry canonicals, no per-company fan-out. The only mild inefficiency, *if this consumer were ever hot*, is the per-entity `_get_entity_type` round-trip inside the loop (N+1); it could be batched into a single `WHERE entity_id = ANY(:ids)`. But with 0 throughput this is irrelevant to the current CPU and is **not** worth changing now.

---

## Conclusion

Dominant CPU operation: **librdkafka `rdk:main` native thread spinning on Kafka connection-setup timeouts** (broker-transport failure). Not a per-event traversal, not exposure fan-out, not a Python loop — the message handler is idle. Fix is operational (clear the broker connectivity fault / recycle the wedged consumer) plus a shared-lib hardening (add `reconnect.backoff.ms` bounds so no consumer can hot-spin while disconnected).
