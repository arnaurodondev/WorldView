# Alert-Service Kafka Consumer Stall — Root-Cause Audit

**Date:** 2026-06-16
**Scope:** READ-ONLY diagnosis (task #2). No code or data changes.
**Symptom:** Consumer group `alert-service-group` lag stuck at ~22,427 on
`nlp.signal.detected.v1` + `graph.state.changed.v1` (delta 0 over 18s — not
draining), while all alert containers report `healthy`.

---

## TL;DR

The owning container **`worldview-alert-intelligence-consumer-1`** (IP
`172.20.0.61`) has a **wedged Python poll loop**. Its asyncio consume loop has
not advanced an offset since **2026-06-15 ~04:46 UTC** (~43h before this audit).
The container is reported `healthy` because the Docker healthcheck only checks
`os.kill(1, 0)` (PID 1 exists), and the rdkafka **background heartbeat thread is
still alive**, so the broker keeps the member in the group (`STATE=Stable`,
1 member, partitions assigned) even though no fetches are being processed.

Root cause is **not** a poison message, an Avro/deserialization error, or a DB
lock. It is an **infrastructure flap (Kafka broker + Valkey transport timeouts)
that wedged the blocking `consumer.poll()` call, combined with two
supervision-loop gaps in `BaseKafkaConsumer` / the consumer `main()` that let the
process limp along instead of crashing for a restart.**

---

## 1. Owning consumer

`grep` over `services/alert/src` for the two topics:

- Topic constants: `services/alert/src/alert/config.py:44-45`
  (`kafka_topic_signal`, `kafka_topic_graph_state`).
- Subscription: `services/alert/src/alert/infrastructure/messaging/consumers/intelligence_consumer.py:32-38`
  (`IntelligenceConsumer`, group `alert-service-group`, also subscribes
  `intelligence.contradiction.v1`).
- Entry point: `services/alert/src/alert/infrastructure/messaging/consumers/intelligence_consumer_main.py`.

Container → IP map confirms the live group member `rdkafka-0edf0c59-...` at
`/172.20.0.61` is **`worldview-alert-intelligence-consumer-1`**. The other alert
containers (watchlist-consumer, dispatcher, email-scheduler, the FastAPI api) do
not own these topics.

## 2. Assigned / consuming / stuck?

`kafka-consumer-groups --describe` + `--state`:

- `STATE=Stable`, `#MEMBERS=1`, strategy `cooperative-sticky`. Partitions ARE
  assigned to a live `CONSUMER-ID` — **not** rebalancing, **not** empty.
- Offsets are **frozen**. Two measurements ~15s apart:
  `current-offset-sum 17871 → 17871` (delta 0); `lag-sum ~22449 → ~22450`. The
  member exists but is not committing.
- This is the classic "**assigned but not draining**" pattern: the rdkafka C
  heartbeat thread keeps the session alive; the Python poll loop is dead.

## 3. Consumer logs (the smoking gun)

- **Zero application log lines since the container's reported boot**, and the
  last app-level log of any kind is `2026-06-15T04:46:52Z`
  (`intelligence_consumer.valkey_mark_failed`).
- After that timestamp the logs contain **only rdkafka C-level `REQTMOUT` /
  `SESSTMOUT` / `FAIL ApiVersionRequest` warnings** — i.e. the librdkafka
  background thread is still emitting, but the asyncio handler loop has stopped.
- The watchlist HTTP calls visible at the tail (`GET portfolio:8000/internal/
  v1/watchlists/by-entity/...`, all `200 OK`) are spaced **~22 seconds apart**
  near the end (06:35–06:38 on 06-15) — the loop was crawling, then stopped.
  Normal spacing is sub-second.

### Timeline of the disruption (from logs)

| Time (UTC)            | Event |
|-----------------------|-------|
| 2026-06-12 22:18:48   | Process start, `intelligence_consumer_starting` + `alert-intelligence-consumer_ready` banner. Consuming normally. |
| 2026-06-13 07:15–07:18 | `kafka_connectivity_probe_failed` reaches **`consecutive_failures=3`** (the exit threshold) — but the process did **not** restart (see §5, Gap B). |
| 2026-06-14 → 06-15    | Repeated `REQTMOUT ListOffsetsRequest` / `SESSTMOUT ... revoking assignment and rejoining` / `ApiVersionRequest failed: Local: Timed out` — broker connectivity flapping. |
| 2026-06-15 02:18:15   | `kafka_connectivity_probe_failed consecutive_failures=1` again. |
| 2026-06-15 04:46:52   | Last app-level log: `intelligence_consumer.valkey_mark_failed` — `redis.exceptions.TimeoutError: Timeout reading from valkey:6379`. |
| 2026-06-15 ~06:38     | Last (crawling) watchlist HTTP call. **Poll loop wedged from here.** |
| 2026-06-16 (audit)    | Container `healthy`, offsets frozen, lag ~22,449. Only rdkafka `REQTMOUT` lines continue. |

> Note on Docker metadata: `docker inspect` reports `StartedAt=2026-06-16T22:27`
> with `RestartCount=0`, and `/proc/1` uptime is implausible (clock skew on this
> host). The **authoritative process lifetime is the application log banner of
> 2026-06-12 22:18:48** — there has been no restart since. Do not trust the
> Docker `StartedAt`/`/proc` clock here.

## 4. What the handler does (and why it amplified the wedge)

`process_message` → `AlertFanoutUseCase.execute` (`alert_fanout.py`). Per signal
event it: resolves watchers via **Valkey-cached watchlist lookups** that fall
back to a **blocking S1 REST call** (`portfolio:8000/internal/v1/watchlists/
by-entity/{id}`), enriches via S7, writes alerts + outbox rows (Postgres), and
publishes notifications to Valkey pub/sub.

Two of those downstreams were timing out during the window:
- **Valkey** — `mark_processed` (`intelligence_consumer.py:211`) raised
  `redis.exceptions.TimeoutError: Timeout reading from valkey:6379`.
- **S1 REST** — repeated `s1_client_request_failed` warnings.

These slowed each message to tens of seconds (matching the 22s HTTP spacing),
which interacts badly with the wedged `consumer.poll()` and the rdkafka session
timeout (`SESSTMOUT after 61719 ms ... revoking assignment and rejoining`).

## 5. Why the safety nets did NOT fire (the real defect)

`BaseKafkaConsumer` (`libs/messaging/src/messaging/kafka/consumer/base.py`) has
a connectivity probe and a lag-stall early-warning, but **both fail to recover
this specific failure mode**:

**Gap A — probe needs 3 *consecutive* failures; the broker only flapped.**
`_connectivity_probe_loop` (base.py:1314) increments `consecutive_failures` on a
failed `list_topics`, but **a single successful probe resets it to 0**
(base.py:1361). The broker was intermittently reachable, so the counter
oscillated 1→0→1→0 and (mostly) never reached `_probe_failure_threshold = 3`
(base.py:1292). `sys.exit(2)` for a DNS-refresh restart was therefore never
reached during the final wedge.

**Gap B — when the probe DID reach 3, the process still didn't restart.**
At 2026-06-13 07:18 the probe hit `consecutive_failures=3`. The code calls
`sys.exit(2)` *inside the probe coroutine* (base.py:1397). `sys.exit` raises
`SystemExit`, which is captured by the asyncio Task, not the process. The
probe's done-callback `_on_probe_task_done` (base.py:1429) only **logs**
`connectivity_probe_crashed` for a non-None task exception — it does **not**
re-raise or call `sys.exit` on the main thread. So the probe task died, the
process kept running **with no connectivity monitoring at all**, and the
lag-stall early-warning (which lives in the same probe loop, base.py:1366) was
also dead from that point.

**Gap C — `main()` does not supervise the consume task.**
`intelligence_consumer_main.py:157-158`:

```python
consumer_task = asyncio.create_task(consumer.run())
await stop_event.wait()          # blocks forever unless SIGTERM
```

If `consumer.run()` returns or raises, nothing awaits `consumer_task` and
`stop_event` is never set, so `main()` blocks on `stop_event.wait()` forever
and the process never exits. There is no `asyncio.wait(..., FIRST_COMPLETED)`
race and no done-callback on `consumer_task` (unlike the retry/probe tasks
inside `run()`). Combined with Gap B, a dead poll loop is invisible to the
orchestrator.

**Gap D — healthcheck is liveness-of-PID-1 only.**
`Healthcheck: python -c "import os; os.kill(1, 0)"`. It returns 0 as long as
PID 1 exists. It does **not** check Kafka consumption progress or last-poll
timestamp, so a wedged consumer reports `healthy` indefinitely.

## 6. Ruled out

- **Poison message / dead-letter loop:** no — offsets are not seeking back on a
  single offset; there are zero `dead_lettered` / `MalformedDataError` /
  `kafka_unexpected_error` logs. The consumer is not retrying one bad event; it
  has simply stopped polling.
- **Avro / deserialization error:** none in logs.
- **DB lock / Postgres outage:** the failing downstreams were Kafka transport
  and Valkey, not Postgres; no `consumer_db_connection_lost_retrying`.
- **Rebalance / no assignment:** no — group is `Stable` with the partitions
  assigned to a live member.

---

## Root cause (one sentence)

A sustained Kafka-broker + Valkey transport flap wedged `IntelligenceConsumer`'s
blocking `consumer.poll()` loop, and three supervision gaps
(`consecutive_failures` reset on flap; `sys.exit(2)` swallowed inside an asyncio
Task; `main()` never supervising `consumer.run()`) plus a PID-only healthcheck
let the dead consumer keep reporting `healthy` with frozen offsets and ~22k lag.

## Recommended fixes (for the follow-up implementation task)

1. **Immediate remediation (ops, no code):** force-recreate the container —
   `docker compose up -d --force-recreate alert-intelligence-consumer` (or
   `docker restart worldview-alert-intelligence-consumer-1`). On a clean start it
   re-joins, re-fetches, and drains the ~22k backlog. Verify with
   `kafka-consumer-groups --describe` that offsets advance.

2. **Gap B/C — make a dead consume/probe task actually kill the process.**
   In `intelligence_consumer_main.py`, race the tasks instead of blocking on
   `stop_event`:
   `done, _ = await asyncio.wait({consumer_task, stop_task}, return_when=FIRST_COMPLETED)`
   then inspect `consumer_task.exception()` and `sys.exit(1)` if it completed.
   In `BaseKafkaConsumer._on_probe_task_done`, escalate `SystemExit`/any probe
   exit to a real process exit (e.g. `os._exit(2)` or signal the main task) so
   the threshold-3 path restarts the container as intended.

3. **Gap A — add a wall-clock liveness watchdog.** Track `last_successful_poll`
   / `last_commit` timestamps and exit non-zero if no progress for N minutes
   while partitions are assigned and lag > 0 (the lag-stall warning already
   computes this; make it *act*, not just log CRITICAL). This catches the
   flap-then-wedge case that `consecutive_failures` misses.

4. **Gap D — upgrade the healthcheck** from `os.kill(1, 0)` to a real liveness
   probe (e.g. scrape the local `/metrics` `last_poll_age` gauge, or a file
   touched each successful poll) so a wedged consumer reports `unhealthy` and the
   orchestrator restarts it.

5. **Harden the Valkey/S1 client timeouts + retries** in the fanout path so a
   downstream blip degrades gracefully rather than stretching per-message time to
   tens of seconds (which feeds the session-timeout / rejoin churn).

These are the same class of bug as the documented "all-green / zero-output"
pattern: a process that is up and `healthy` but doing no work, with the failure
masked by a liveness-only check.
