# Platform CPU & Memory Re-sweep — 2026-06-21

**Mode:** read-only (docker stats/inspect/logs + code reading; no edits, restarts, or commits).
**Host:** macOS, 14 CPUs / 46.72 GiB RAM, 80 running containers.
**Context:** Re-measures the CURRENT state after this session's fixes (GLiNER OMP=4 + 4G→8G,
Postgres split into 2 instances, Kafka reconnect backoff, intraday-resampling N+1 fix,
market-data consumer recreation, dev-lean mode). Supersedes the earlier per-area reports.

---

## TL;DR

- **CPU is mostly REAL work now.** GLiNER (real NER, ~145%), the two Postgres instances,
  Kafka, and the fundamentals consumer are all doing legitimate work. The prior
  phantom-spin on the market-data consumers is largely gone.
- **TWO consumers are still in a restart/wedge loop and burning CPU:**
  1. `market-data-ohlcv-consumer` — **6 restarts / 5 min**, re-materialising the same
     symbols (BTC-USD 10× in 5 min) → ~88% avg CPU on repeated work. **Top fixable CPU sink.**
  2. `alert-intelligence-consumer` — watchdog trips at exactly 300 s and `os._exit(3)`s
     **every ~5 min (3×/30 min)**; CPU spikes to ~103% around the restart. Real wedge,
     not benign idle (the watchdog gates on poll-cycle liveness, which is NOT advancing).
- **MEMORY is the bigger story now.** Only **4 of 80 containers have a memory limit**.
  - **MinIO is near-OOM:** 3.07 GiB / 4 GiB = **77–79%** (this is the new near-limit container).
  - **Valkey is uncapped + `noeviction`** — can grow unbounded and OOM the host.
  - **Kafka heap is massively over-provisioned:** `-Xmx4G` committed, only ~290–850 MiB used.
- **Host is NOT over-committed today:** ~15.8 GiB in use vs 46.72 GiB. Capped limits sum to
  24 GiB. Risk is *tail* behaviour (uncapped Valkey/Postgres bloat), not steady state.

---

## 1. CPU re-rank (4-snapshot average, sorted)

| Rank | Container | Avg CPU% | Real or phantom? | Evidence |
|------|-----------|---------:|------------------|----------|
| 1 | `gliner-server` | 145.2 | **REAL** | `gliner_micro_batch_flushed` logs; OMP=4 by design. Healthy. |
| 2 | `postgres-1` (market) | 101.3 | **REAL** | Serves OHLCV/quotes/fundamentals materialisation load. |
| 3 | `market-data-ohlcv-consumer` | 88.0 | **PHANTOM/WASTE** | 6 restarts/5 min; re-materialises same symbols (BTC-USD ×10/5 min). Restart loop re-does work. |
| 4 | `kafka` | 64.7 | **REAL** (partly amplified) | GroupCoordinator churns rebalancing `market-data-ohlcv` every ~10 s (driven by #3). |
| 5 | `market-data-fundamentals-consumer` | 52.7 | **REAL** | 0 restarts/5 min; draining distinct symbols (JPM, QQQ…). Backlog work. |
| 6 | `minio` | 31.0 | **REAL** | Object I/O for materialisation. |
| 7 | `kg-instrument-discovered-consumer` | 21.1 | **MOSTLY IDLE** (transient) | No recent processing logs; had `REQTMOUT ListOffsetsRequest` 3 h ago. Spiky, not sustained. |
| 8 | `nlp-article-consumer-2` | 16.6 | REAL | Article processing. |
| 9 | `market-data-intraday-resampling-consumer` | 16.6 | REAL | Post N+1 fix; normal now. |
| 10 | `nlp-price-impact-worker` | 16.2 | REAL | Price-impact labelling. |

Confirmation requested by brief: **market-data + temporal-event consumers are now doing real
work** — fundamentals/quotes/intraday/temporal-event consumers all show real processing logs
and zero restart loops. The exception is **ohlcv-consumer**, which regressed into a restart loop.

### 1a. ohlcv-consumer restart loop (root cause)

- `docker logs` shows `kafka_consumer_started` **6× in 5 min** and the Kafka broker shows
  `market-data-ohlcv` group going Empty→rebalance→Stabilized→Empty every ~10 s
  (generations 4458→4461 in one minute).
- Each cycle re-materialises the full symbol set (BTC/ETH/SOL/… hundreds of bars) → 512 KB of
  `ohlcv_consumer.materialized` logs in 5 min. The producer is NOT republishing
  (`market-ingestion-scheduler` logs `tasks_enqueued: 0`), so the repeated work comes from the
  restart loop re-reading after each LeaveGroup.
- The supervisor (`libs/messaging/.../supervisor.py`) is working as designed: `run()` terminates
  → `ConsumerExited` → `sys.exit(1)` → Docker restarts. The bug is *upstream* — `run()` keeps
  terminating. Most likely the materialisation batch (large crypto bar sets) overruns the
  consumer session/rebalance timeout, the broker evicts the member, and the rejoin triggers a
  fresh full reprocess. Needs a focused fix (commit the offset before the long materialise, or
  bound batch size / extend `max.poll.interval.ms`).

### 1b. alert-intelligence-consumer wedge loop

- `intelligence_consumer_watchdog_stall` fires at `stall_seconds: 300.0`, `seconds_since_progress: ~300`,
  then `os._exit(3)` — **3× in 30 min**.
- Code: `services/alert/src/alert/infrastructure/messaging/consumers/intelligence_consumer_main.py:88-113`.
  The watchdog gates on `last_poll_monotonic`, which is documented to advance on EVERY poll cycle
  (idle or message). It is still tripping → the poll loop is genuinely not cycling (real wedge),
  not merely an idle topic. CPU spikes to ~103% around the reconnect/restart.
- Topics are all low-traffic (`nlp.signal.detected.v1`, `graph.state.changed.v1`,
  `intelligence.contradiction.v1`), so the user-visible impact is low, but it is a 5-minute
  CPU-churn cycle that should not exist.

---

## 2. MEMORY sweep

### 2a. Containers WITH a memory limit (only 4 of 80)

| Container | Usage | Limit | Headroom | Risk |
|-----------|------:|------:|---------:|------|
| **minio** | 3.07 GiB | 4 GiB | ~0.9 GiB (**77–79%**) | **HIGH — near OOM.** Was MemLimit=0 before; now capped but the cap is tight. Bump to 6 GiB or watch for OOM-kill. |
| gliner-server | 1.76 GiB | 8 GiB | 6.2 GiB (22%) | LOW — over-provisioned now (was OOM-looping at 4 GiB). 6 GiB would be ample; 8 GiB is safe-but-generous. |
| kafka | 0.83–0.94 GiB | 6 GiB | ~5 GiB | LOW container-side, but JVM heap mis-sized (see 2c). |
| ollama | 0.02 GiB | 6 GiB | ~6 GiB | LOW — idle (GLiNER/extraction externalised). Could drop to 2 GiB. |

### 2b. Containers with NO memory limit (the main gap — 76 containers)

`docker inspect ... HostConfig.Memory == 0` for **all 76 others.** The host-OOM-relevant ones:

| Container | Usage | Limit | Risk |
|-----------|------:|------:|------|
| **valkey** | 95 MiB | **0 (unlimited)** + `maxmemory=0`, policy `noeviction` | **MEDIUM-HIGH** — no container cap AND no Redis cap; under cache/dedup pressure it grows until host OOM, and `noeviction` means it never sheds. Two unbounded layers. |
| **postgres-intelligence-1** | 1.71 GiB | **0** | MEDIUM — `work_mem=128 MiB` × `max_connections=120` = up to **15 GiB** worst-case transient. No cap to contain a query storm. |
| **postgres-1** (market) | 1.73 GiB | **0** | LOW-MEDIUM — `work_mem=4 MiB` × 500 conns ≈ 2 GiB worst-case + 320 MiB shared_buffers. Bounded but uncapped. |
| 73 app/worker/observability containers | 14–450 MiB each | 0 | LOW individually; collectively the long tail. |

### 2c. JVM heap right-sizing (Kafka)

- `KAFKA_HEAP_OPTS=-Xms4G -Xmx4G` (G1GC, MaxGCPauseMillis=20, IHOP=35).
- Actual heap: **used 291 MB of 4 GB** (`GC.heap_info`), container RSS 0.83–0.94 GiB.
- The 4 GiB heap is **~13× larger than working set.** `-Xms4G` forces 4 GiB committed up front.
  Right-size to `-Xms1G -Xmx2G` — frees ~2–3 GiB of committed JVM memory with zero risk at this load.

### 2d. Postgres memory configs (for reference)

| Setting | postgres-1 (market) | postgres-intelligence-1 |
|---------|--------------------:|------------------------:|
| shared_buffers | 320 MiB | 2.5 GiB |
| work_mem | 4 MiB | **128 MiB** |
| max_connections | 500 | 120 |
| effective_cache_size | 5 GiB | (n/a checked) |
| worst-case work_mem fan-out | ~2 GiB | **~15 GiB** |

`postgres-intelligence` `work_mem=128 MiB` is aggressive for 120 connections — fine while
connection count stays low, dangerous if a consumer fan-out opens many concurrent sorts/hashes.

---

## 3. Idle-but-burning (aggregate idle-poll overhead)

Beyond the two wedge loops above, the steady-state idle poll/dispatch overhead is now modest:

- ~10 dispatchers/poll-loops at 0.2–1.1% CPU each (market-ingestion-dispatcher 1 s interval,
  content/portfolio/alert/kg/nlp dispatchers, alert-rule-poller). Aggregate ≈ **5–8% of one core**
  — small; dev-lean already collapses the worst idle consumers.
- `market-ingestion-scheduler` evaluates **2102 policies per 60 s tick** with `tasks_enqueued: 0`
  — CPU spiked to ~72% in one snapshot during a tick. Real but periodic (once/min). Could be
  cheaper if policy evaluation short-circuits when no policy is due, but low priority.
- The dominant waste is NOT the idle pollers; it's the two restart loops (§1a, §1b).

---

## 4. Host-level over-commit assessment

- **CPU:** 14 cores. Sum of average CPU ≈ ~5.5 cores in use (GLiNER 1.45 + pg 1.0 + ohlcv 0.88 +
  kafka 0.65 + fundamentals 0.53 + tail). **Not over-committed**, but ~0.9 core is pure waste in
  the ohlcv restart loop + alert wedge churn.
- **Memory:** ~15.8 GiB in use of 46.72 GiB host. Capped limits total 24 GiB. **Not over-committed
  in steady state.** The risk is *uncapped tail growth*: Valkey (`noeviction`, unbounded) and
  postgres-intelligence (15 GiB worst-case work_mem) have no container backstop. A single runaway
  there can OOM the host because nothing caps them.

---

## 5. Prioritised optimizations (concrete)

### P0 — stop the two restart/wedge loops (CPU + churn)
1. **ohlcv-consumer restart loop.** Investigate why `run()` keeps terminating (likely batch
   materialise overruns the rebalance/session timeout on large crypto bar sets).
   - File: `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py`
   - Options: bound per-poll batch size, commit offset before the long materialise, or raise
     `max.poll.interval.ms` for this consumer's `ConsumerConfig`.
   - Payoff: removes ~0.9 core of repeated work + stops Kafka rebalance churn.
2. **alert-intelligence-consumer wedge.** The poll loop stops cycling and trips the watchdog every
   300 s. File: `services/alert/src/alert/infrastructure/messaging/consumers/intelligence_consumer.py`
   (poll loop) + `..._main.py:88` (watchdog). Diagnose the genuine poll-loop stall; the 300 s
   `os._exit` is the symptom-masker, not the cure.

### P1 — memory caps (prevent host OOM from the tail)
3. **Cap Valkey** at the container level (e.g. `mem_limit: 1g`) AND set Redis `maxmemory` +
   `maxmemory-policy allkeys-lru` (it's a cache/dedup store — eviction is safe). Today both layers
   are unbounded with `noeviction`.
4. **Raise MinIO** limit from 4 GiB → 6 GiB (currently 77–79%, near OOM) or confirm steady-state
   and accept; do not leave it at 4 GiB while it sits at 3.07 GiB.
5. **Cap the two Postgres instances** (e.g. `mem_limit: 4g` each) so a work_mem fan-out
   (intelligence: 15 GiB worst-case) cannot OOM the host.

### P2 — right-size over-provisioned reservations
6. **Kafka heap:** `-Xms4G -Xmx4G` → `-Xms1G -Xmx2G` (uses 291 MB). Frees ~2–3 GiB committed.
7. **GLiNER limit:** 8 GiB → 6 GiB (uses 1.76 GiB; 4 GiB was the OOM point, so keep margin).
8. **Ollama limit:** 6 GiB → 2 GiB (idle, 16 MiB used; models externalised to DeepInfra).

### P3 — minor
9. `market-ingestion-scheduler`: short-circuit policy evaluation when nothing is due (2102 policies
   evaluated/min for 0 enqueues).

---

## Appendix — method

- CPU: `docker stats --no-stream` ×4, averaged via awk. Real-vs-phantom cross-checked against each
  container's own processing logs (`*.materialized`, `*_flushed`, `kafka_consumer_started` counts)
  and Kafka GroupCoordinator rebalance logs.
- Memory: `docker stats` + `docker inspect --format '{{.HostConfig.Memory}}'` for all 80; Kafka
  heap via `jcmd 1 GC.heap_info`; Postgres via `pg_settings`; Valkey via `redis-cli config get`.
