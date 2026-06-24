# Alert Intelligence Consumer — Poll-Loop Watchdog Wedge Root Cause

- **Date:** 2026-06-22
- **Mode:** READ-ONLY investigation (docker logs/exec/inspect + source read; no edits/restarts)
- **Container:** `worldview-alert-intelligence-consumer-1`
- **Service:** alert (S10)
- **Symptom (reported):** watchdog trips at exactly 300s → `os._exit(3)` every ~5 min, CPU spike ~103% (prior audit `docs/audits/2026-06-21-platform-cpu-memory-resweep.md`).
- **Prior context:** memory `project_kafka_resilience_and_qa_2026_06_21` (F-006 fix), `project_cpu_bottleneck_investigation_2026_06_21` (host CPU oversubscription).

---

## TL;DR — Two-part root cause

The wedge is a **false-positive watchdog firing on an idle topic**, and it fires only because **the deployed image is a STALE pre-F-006 build** running under a **CPU-starved broker** that has stopped feeding the consumer messages.

1. **Primary (why it crash-loops): the running container is a pre-F-006 image.**
   The F-006 fix (commit `225c140ce`, 2026-06-21 12:26 PDT) makes the watchdog gate on
   a poll-*cycle* liveness marker (`last_poll_monotonic`, advanced on every poll incl.
   empty) instead of a last-*message* marker (`last_progress_monotonic`, advanced only
   when a message is processed). **The running image `worldview-alert-intelligence-consumer:latest`
   (id `1bbdc4107d34`) was built 2026-06-21 10:28:20 PDT — ~2 hours BEFORE F-006 was
   committed.** The container therefore runs the OLD watchdog that gates on
   `last_progress_monotonic`. On an idle topic no messages arrive → the marker never
   advances → 300s elapses → `os._exit(3)`. This is precisely the bug F-006 already fixes
   in source; the fix was simply never built/deployed.

2. **Trigger (why the topic is idle): the broker is CPU-starved and not serving the group.**
   The broker (`worldview-kafka-1`) is pegged (~87% CPU, host load avg ~29-35, 80 containers)
   and cannot finish loading `__consumer_offsets` or answer Fetch/Heartbeat/ApiVersion
   requests. librdkafka logs `SESSTMOUT ... session timed out ... revoking assignment and
   rejoining group`, `Timed out FetchRequest in flight (after 44933ms)`,
   `Timed out HeartbeatRequest (after 30874ms)`. So even the messages that DO exist on
   `nlp.signal.detected.v1` are not delivered → the old (message-gated) watchdog starves.

**This is NOT a librdkafka reconnect busy-spin in the consumer.** Live sampling showed the
consumer at 0.5–8% CPU, not ~103%. The ~103% in the 2026-06-21 sweep was the BROKER (or an
earlier reconnect-spin window); the *current* state is a calm consumer killed by a stale,
message-gated watchdog while the overloaded broker withholds traffic.

---

## Evidence

### A. The deployed image does NOT contain F-006

`docker exec` introspection of the **running** code:

```
# IntelligenceConsumer._record_progress in the running image:
def _record_progress(self) -> None:
    now = time.time()
    self._last_progress_ts = now
    KAFKA_CONSUMER_LAST_PROGRESS.labels(...).set(now)
    # ← NO self._last_poll_monotonic assignment

hasattr(IntelligenceConsumer, 'last_poll_monotonic') == False
```

```
# _liveness_watchdog in the running image gates on the MESSAGE marker:
last_progress = getattr(consumer, "last_progress_monotonic", time.monotonic())
age = time.monotonic() - last_progress
if age >= stall_seconds:  # 300s
    log.critical("intelligence_consumer_watchdog_stall", ...)
    os._exit(3)
```

Compare the **source / HEAD** (the F-006 fix, present in working tree AND committed):

```
# services/.../intelligence_consumer.py — _record_progress override (F-006):
self._last_poll_monotonic = time.monotonic()   # ← advances on EVERY poll cycle
super()._record_progress()

# property last_poll_monotonic exists; watchdog gates on it:
# intelligence_consumer_main.py L97-101:
last_alive = getattr(consumer, "last_poll_monotonic",
                     getattr(consumer, "last_progress_monotonic", time.monotonic()))
```

Build vs commit timing:

```
running image id           : 1bbdc4107d34
image CreatedAt            : 2026-06-21 10:28:20 -0700 PDT
F-006 commit 225c140ce     : 2026-06-21 12:26:08 -0700  (≈2h AFTER the image build)
F-005 commit 4c5b5a2d8     : 2026-06-21 14:18:26 -0700  (also AFTER the build)
git status of both files   : clean (committed, in HEAD and working tree)
last_poll_monotonic count  : HEAD=5, working-tree=5, running-image=0
```

**The fix exists and is committed; the image was never rebuilt after it landed.**

### B. The base BP-700 heartbeat IS advancing (poll loop is alive)

Live scrape of the consumer's own `/metrics`:

```
kafka_consumer_last_progress_timestamp{group_id="alert-service-group",service="alert"} 1.7821127432e+09
now: 1782112743.86      →  gauge only ~0.6s stale
```

The base `run()` loop (`libs/messaging/.../base.py` L1790-1813) calls `_record_progress()`
on **every** return from `poll()` (idle `msg is None` included). The gauge proves the loop is
cycling ~1×/s. In the F-006 image this same call would bump `last_poll_monotonic` and the
watchdog would never trip. In the deployed (old) image, `_record_progress` does NOT touch the
watchdog's marker, so the loop being alive is invisible to the watchdog.

### C. Broker overload starves message delivery (the trigger)

Consumer container logs (one full restart cycle):

```
SESSTMOUT [thrd:main]: Consumer group session timed out (in join-state steady) after 75790 ms
  without a successful response from the group coordinator (broker 1) ... revoking assignment and rejoining group
REQTMOUT  [thrd:kafka:29092/1]: Timed out FetchRequest in flight (after 44933ms)
REQTMOUT  [thrd:GroupCoordinator]: Timed out HeartbeatRequest in flight (after 30874ms)
FAIL      ApiVersionRequest failed: Local: Timed out ... in state APIVERSION_QUERY (after 10476ms)
kafka_connectivity_probe_failed  _TRANSPORT "Failed to get metadata: Broker transport failure"
intelligence_consumer_watchdog_stall  seconds_since_progress=317.9  → os._exit(3)
```

Broker logs:

```
QuorumController id=1: processExpiredBrokerHeartbeat: controller event queue overloaded.
  Timed out heartbeat from broker 1.
BrokerLifecycleManager id=1: Broker 1 sent a heartbeat request but received error REQUEST_TIMED_OUT.
GroupMetadataManager brokerId=1: Finished loading offsets and group metadata from __consumer_offsets-27
  in 43442 milliseconds, of which 43442 milliseconds was spent in the scheduler.
GroupMetadataManager brokerId=1: Already loading offsets and group metadata from __consumer_offsets-*  (×100, perpetual)
```

Environment:

```
broker CPU (docker stats)  : ~87%
broker heap                : -Xms4G -Xmx4G, G1GC MaxGCPauseMillis=20, IHOP=35
host load average          : 29.10 / 34.77 / 35.23
running containers          : 80
consumer group membership  : alert-service-group, member present, 5 partitions assigned
                              (--members succeeds; --describe FIND_COORDINATOR times out)
topic state                : nlp.signal.detected.v1 has data (offsets 577/690/761);
                              graph.state.changed.v1 + intelligence.contradiction.v1 effectively empty
consumer CPU (live sample)  : 0.5–8% (NOT ~103% — busy-spin ruled out for current state)
RestartCount                : 67→68 during the investigation
```

`43442 ms ... spent in the scheduler` = the JVM thread couldn't get a CPU slice. The broker
isn't out of memory or disk; it is **CPU-starved by host oversubscription** (same class as
`project_cpu_bottleneck_investigation_2026_06_21`).

---

## Classification

| Hypothesis | Verdict | Evidence |
|---|---|---|
| (a) Idle-topic false-positive watchdog | **CONFIRMED (proximate cause of the crash-loop)** | Deployed watchdog gates on `last_progress_monotonic` (message-only); idle topic → marker never advances → 300s exit. BP-700 gauge proves poll loop is alive. |
| (b) Real blocking call in the loop | Ruled out | No hung handler; consumer CPU low; gauge fresh; loop returns from `poll()` ~1×/s. |
| (c) librdkafka reconnect busy-spin in the consumer | Ruled out *for current state* | Consumer CPU 0.5–8%, not ~103%; `reconnect.backoff.max.ms=20s` cap present in config. The ~103% in the 2026-06-21 sweep was the broker / an earlier window. |
| (d) Stale image (fix not deployed) | **CONFIRMED (true root cause)** | Image built 2h before F-006 commit; running code lacks `last_poll_monotonic`; HEAD/working-tree have it. |
| (e) Broker CPU-starvation withholding traffic | **CONFIRMED (environmental trigger)** | 43s `__consumer_offsets` loads "in the scheduler", QuorumController heartbeat timeouts, Fetch/Heartbeat/ApiVersion REQTMOUT, host load ~30. |

**Same connection-wedge family as market-data/temporal?** Partially. The *transport-layer
symptom* (`_TRANSPORT`, REQTMOUT, SESSTMOUT) is the same broker-handshake-starvation class
seen on those consumers — its origin is the shared overloaded broker, not an alert-specific
blocking call. But the *crash-loop mechanism* is alert-specific: a stale, message-gated
watchdog that F-006 already fixes. The other consumers don't have this watchdog, so they spin
on reconnect instead of `os._exit`.

---

## Long-term fix (design — not applied)

### Fix 1 — PRIMARY: rebuild + redeploy the alert-intelligence-consumer image

The F-006 fix is **already correct and committed**; it was never built into the running image.

- **Action:** rebuild `worldview-alert-intelligence-consumer` from current HEAD and recreate
  the container. Per memory `feedback_compose_profile_recreate`, profile-gated services need
  `--profile all` (or explicit `--no-deps --build`) or the recreate silently no-ops.
- **Verification (post-deploy):**
  `docker exec worldview-alert-intelligence-consumer-1 python -c "from alert.infrastructure.messaging.consumers.intelligence_consumer import IntelligenceConsumer as C; print(hasattr(C,'last_poll_monotonic'))"`
  must print `True`.
- After redeploy the idle-topic crash-loop stops immediately: the watchdog will read
  `last_poll_monotonic`, which the base loop advances every poll cycle.

The relevant fix code already in source (no change needed, just deploy):
- `services/alert/src/alert/infrastructure/messaging/consumers/intelligence_consumer.py`
  - `_record_progress` (L182-192): `self._last_poll_monotonic = time.monotonic()` then `super()._record_progress()`.
  - `last_poll_monotonic` property (L169-180).
- `services/alert/src/alert/infrastructure/messaging/consumers/intelligence_consumer_main.py`
  - `_liveness_watchdog` (L97-101): gate on `last_poll_monotonic` with fallback to `last_progress_monotonic`.

### Fix 2 — TRIGGER: relieve broker CPU starvation (platform-wide)

Even with F-006 deployed, the consumer cannot drain `nlp.signal.detected.v1` while the broker
can't serve Fetch requests. This is the host-oversubscription problem
(`project_cpu_bottleneck_investigation_2026_06_21`): 80 containers, load ~30 on ~14 cores.

- **Options:** reduce concurrent container count for local QA; pin/limit CPU-heavy services
  (GLiNER, promoter) as already done in that investigation; or give the broker CPU
  reservation so G1GC + the request handler threads get scheduled. The broker heap (4G) and
  GC config are fine — the bottleneck is CPU scheduling, not heap.
- The `Already loading __consumer_offsets` perpetual loop is a downstream symptom of the
  broker flapping in/out of the controller's view (heartbeat timeouts); it clears once the
  broker gets CPU.

### Fix 3 — DEFENSE-IN-DEPTH: make the watchdog robust to broker-starvation (optional)

Once F-006 is deployed the watchdog correctly distinguishes idle-but-cycling from wedged.
But note a residual edge: if the broker is so starved that `poll()` itself blocks longer than
300s inside the executor (it shouldn't — `poll_timeout_seconds=1.0` returns `None` on timeout),
the watchdog *would* correctly fire and restart. That is acceptable behaviour (a genuinely
wedged poll loop should restart). No change required beyond Fix 1, but operators should expect
some restarts to persist until Fix 2 relieves the broker — those are then *true* wedges
(coordinator unreachable for >300s), which a restart legitimately addresses by forcing a fresh
group rejoin.

---

## Precise answer to the deliverable

- **Exact reason the poll-cycle liveness stalls:** It does **not** actually stall in the
  current source — the BP-700 gauge proves the loop cycles ~1×/s. The *deployed image* uses the
  **pre-F-006 watchdog that gates on the last-MESSAGE marker (`last_progress_monotonic`)**, which
  on an idle topic (no messages delivered — because the **CPU-starved broker can't serve Fetch
  requests**) never advances, so the 300s timer expires and `os._exit(3)` fires. It is an
  **idle-topic false-positive watchdog**, made possible solely by a **stale image that lacks the
  committed F-006 fix**, and triggered by **broker CPU-starvation withholding traffic**.
- **Precise long-term fix:**
  1. **Rebuild + redeploy** `worldview-alert-intelligence-consumer` from HEAD — F-006 is already
     committed (`225c140ce`); the liveness-bump line is
     `self._last_poll_monotonic = time.monotonic()` in `IntelligenceConsumer._record_progress`
     (`intelligence_consumer.py` ~L191), read by the watchdog at `intelligence_consumer_main.py`
     L97-101. Verify with the `hasattr(..., 'last_poll_monotonic')==True` check above.
  2. **Relieve broker CPU oversubscription** (host has 80 containers, load ~30) so the broker can
     serve Fetch/Heartbeat and finish `__consumer_offsets` loading.
