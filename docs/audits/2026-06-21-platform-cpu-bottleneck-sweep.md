# Platform CPU Bottleneck Sweep — 2026-06-21

**Scope:** Whole local Docker platform (~77 running containers). READ-ONLY diagnostics.
**Excluded from deep-dive (owned by other agents):** GLiNER NER server, Postgres. Both are noted in the ranking but not analysed.
**Host:** darwin / Apple Silicon, **arm64**, 14 CPUs, 50 GB RAM (Docker VM).

---

## TL;DR — the platform is in CPU-saturation collapse

The single most important finding is **not** any one container. It is a **host-wide CPU oversubscription feedback loop**:

- **Load average = 141.93 / 190.92 / 159.87 on a 14-CPU host** (≈10x oversubscription). Re-sampled minutes later: `104.73 / 175.11 / 155.86`. Sustained 1-min load of 100-190 on 14 cores means every runnable thread waits ~7-13x longer than it should.
- 48 consumer/worker/dispatcher containers + GLiNER + 2 Postgres instances all compete for 14 cores. No single container dominates; CPU% rotates between them sample-to-sample (ohlcv 47% → 27% → 28%, intraday 41% → 11% → 38%, etc.) — the classic signature of **CPU starvation, not real work**.
- **Emulation is NOT a factor.** Every heavy/ML image checked is native **arm64** (postgres, gliner, ollama, kafka, minio, all FastAPI services). No x86 emulation tax exists. This rules out the most-suspected systemic cause.
- The starvation **causes Kafka client request timeouts** (`ApiVersionRequest failed`, `HeartbeatRequest timed out`, `Failed to resolve 'kafka:29092': Temporary failure in name resolution`) → **session timeouts → rebalance storms → watchdog-driven full process restarts**, which burn *more* CPU. This is a runaway loop. Evidence: `market-data-ohlcv-consumer` has **restarted 103 times**; `alert-intelligence-consumer` was caught mid-`Restarting (3)`.

**The highest-leverage non-GLiNER/non-Postgres fix is to stop the consumer crash-restart storm and cut the idle CPU floor of the 48-container fleet — not to optimize any single hot loop.** Once the box is no longer saturated, the Kafka DNS/timeout errors disappear (they are symptoms, not root causes).

---

## 1. Ranked CPU consumers (merged across 4 samples)

CPU% is unstable because the host is saturated; ranges show the swing across samples.

| Rank | Container | CPU% (range across samples) | Why | Owner |
|------|-----------|------------------------------|-----|-------|
| 1 | `worldview-postgres-1` | 35–93% | (other agent) AGE/Cypher + heavy queries | **Postgres — excluded** |
| 2 | `worldview-gliner-server-1` | 45–94% | (other agent) CPU NER inference | **GLiNER — excluded** |
| 3 | `market-data-ohlcv-consumer-1` | 27–48% | **Crash-restart loop — 103 restarts.** Kafka session timeouts → rebalance → watchdog restart. Per-msg work is modest (`json.loads` per bar line, S3 GET amortised) but the churn dominates. | NON-excluded |
| 4 | `market-data-intraday-resampling-consumer-1` | 11–41% | Resamples every source bar into all coarser TFs (`for bar in domain_bars: ResampledOHLCVUseCase.execute`) — genuinely CPU-bound per message, *plus* Kafka reconnect churn. | NON-excluded |
| 5 | `market-data-fundamentals-consumer-1` | 26–42% | Kafka heartbeat/session timeouts (`REQTMOUT HeartbeatRequest`, `SESSTMOUT … revoking assignment`) → rejoin churn. | NON-excluded |
| 6 | `market-ingestion-scheduler-1` / `market-ingestion-worker-1` | 17–36% | Worker claims **0 tasks every ~5s** yet burns 17–20% — pure poll + reconnect overhead, no real work. | NON-excluded |
| 7 | `content-ingestion-worker-1` | 6–26% | Polymarket fetch cycle (100 markets every cycle) + claims **0 tasks every ~5s**. Mostly idle-poll + one external fetch loop. | NON-excluded |
| 8 | `kafka-1` | 7–71% | Broker spikes to 70% under the reconnect/rebalance storm it is being subjected to. **Healthy, 4G heap, no CPU limit.** Hot because clients hammer it. | NON-excluded (symptom) |
| 9 | `alert-intelligence-consumer-1` | up to 48%, then `Restarting (3)` | **Crash-restart loop.** Watchdog logs `exiting_for_restart_poll_loop_presumed_wedged` after 300s stall (stall caused by Kafka DNS/timeout). | NON-excluded |
| 10 | `minio-1` | 7–14% | IO buffers; arm64; within reason. | NON-excluded |
| 11 | `knowledge-graph-instrument-consumer-1`, `nlp-pipeline-*`, `kafka-ui-1`, etc. | 1–22% spikes | Spread of the remaining 40+ idle-expected containers, each taking a slice as they fight for cores. | NON-excluded |

### Restart/health evidence
- `market-data-ohlcv-consumer-1`: **RestartCount = 103** (started 21:09, long after platform boot at 20:47). ExitCode 0 (clean watchdog-driven exit → compose restart).
- `alert-intelligence-consumer-1`: RestartCount = 2, observed `Restarting (3)`.
- `market-data-insider-transactions-consumer-1`: **(unhealthy)**.
- `ollama-1`: **0.00% CPU, 17 MiB** — fully idle. Only serves health-check `GET /api/tags` every 30s. **Not doing any inference.**

---

## 2. Apple-Silicon emulation sweep — CLEAN

Host `uname -m` = `arm64`. Architecture of every key image:

| Container | Image | Arch |
|-----------|-------|------|
| postgres | worldview-postgres | arm64 |
| gliner-server | worldview-gliner-server | arm64 |
| ollama | ollama/ollama:0.6.7 | arm64 |
| kafka | confluentinc/cp-kafka:7.6.0 | arm64 |
| minio | minio/minio:…2025-04-08 | arm64 |
| nlp/api-gateway/rag-chat/market-* | worldview-* (locally built) | arm64 |

**No emulated x86 images.** There is no platform-wide emulation CPU tax. (This was the leading hypothesis going in; it is disproven.)

---

## 3. ML / inference CPU — OFFLOADED, not local

- **Embeddings:** `NLP_PIPELINE_EMBEDDING_PROVIDER=deepinfra` (`services/nlp-pipeline/configs/docker.env:69`). Live logs confirm `POST https://api.deepinfra.com/v1/openai/embeddings 200` + `deepinfra_embedding_batch_ok` (BAAI/bge-large-en-v1.5). The Ollama bge-large CPU fallback is **NOT firing**.
- **Extraction:** offloaded to DeepInfra (`openai/gpt-oss-120b`, `Qwen/Qwen3-235B`), confirmed in logs.
- **Ollama:** idle (0% CPU). The only in-process CPU inference on the box is **GLiNER** (excluded).

There is **no hidden sentence-transformers/torch CPU inference** burning cores in the services. ML cost is correctly offloaded. The one CPU-bound numeric path that *is* local is the **intraday-resampling use case** (pure-Python per-bar resampling), ranked #4.

---

## 4. Hot loops / inefficient polling

| Finding | File / config | Impact |
|---------|---------------|--------|
| **Watchdog restart loop** (primary CPU sink among non-excluded) | `services/alert/.../intelligence_consumer_main.py` (`_WATCHDOG_POLL_SECONDS=30`, 300s stall → process exit) and equivalent market-data consumer watchdogs | Each restart = full Python interpreter boot + Kafka rejoin + rebalance across the *whole* group. With the box saturated, the 300s stall threshold trips constantly, causing perpetual restarts. **This is self-inflicted CPU under saturation.** |
| **0-task poll loops at 5s idle sleep** | `content-ingestion` & `market-ingestion` `worker_idle_sleep_seconds = 5.0`; logs show `claimed: 0, requested: N` every ~5s forever | Each wake = a DB `claim_batch` round-trip (SELECT … FOR UPDATE SKIP LOCKED). 48 such loops collectively add a constant DB + CPU floor even with no work to do. Adds to Postgres load too. |
| **Dispatcher poll = 1.0s** (outbox) | `market-ingestion` `dispatcher_poll_interval_seconds=1.0`, `knowledge-graph` `dispatcher_poll_interval_s=1.0`, `alert` `dispatcher_poll_interval_s=1.0`, `nlp-pipeline` `1.0` | 1s outbox polling × ~7 dispatchers = constant DB SELECTs. Fine individually, but a needless floor when the box is saturated. |
| **Polymarket re-fetch** | `content-ingestion-worker` fetches 100 Polymarket markets per cycle | One external HTTP + 100-row processing on a loop. Minor, but not free under saturation. |

No genuine busy-wait (`while True` with no sleep) was found — all loops use `asyncio.sleep`/`wait_for`. The problem is **loop *count × frequency* under a 10x-oversubscribed host**, amplified by the restart storm.

---

## 5. Kafka / infra

- **Kafka broker is healthy** (`health=healthy`, `RestartCount=0`, 4G heap `-Xms4G -Xmx4G`). It spikes to 70% only because 48 clients hammer it with reconnect/ApiVersion/heartbeat traffic during the rebalance storm. The recent BP-705/706 GC/connection-churn hardening is in place; the broker is the *victim* here, not the cause.
- **The `Failed to resolve 'kafka:29092'` DNS errors are a saturation symptom.** Docker's embedded DNS resolver (and the client's resolver thread) are CPU-starved, so name resolution intermittently times out. Kafka's own DNS is fine. These errors will vanish once host CPU is freed.
- **`deploy.resources.limits` (cpus) are silently ignored** by `docker compose up` (only Swarm honors them). `docker inspect` confirms `NanoCpus=0` on Kafka despite a `cpus: "2.0"` block in compose. So the compose CPU caps that *look* like governance are **not actually enforced** — every container can grab unbounded CPU, which is exactly how the box hit load 142.
- Valkey (1%), exporters, Grafana/Prometheus/Loki/Tempo are all within normal range.

---

## Prioritised optimizations (NON-GLiNER / NON-Postgres)

Ordered by expected impact on the host-wide CPU saturation.

### P0 — Stop the consumer crash-restart storm (root of the feedback loop)
- **What:** `market-data-ohlcv-consumer` (103 restarts) and `alert-intelligence-consumer` are looping through watchdog-stall restarts because Kafka heartbeats time out under CPU starvation.
- **Change:** Raise the watchdog stall threshold and Kafka `session.timeout.ms` / `max.poll.interval.ms` so a temporarily-starved consumer is *not* killed, AND reduce the running consumer count (see P1). Files: `services/alert/.../intelligence_consumer_main.py` (`_WATCHDOG_POLL_SECONDS` / 300s stall), market-data consumer watchdog + `ConsumerConfig` (`max_poll_interval_ms`, `session_timeout_ms`).
- **Impact:** Eliminates the restart→rebalance→CPU-spike loop. Expected to remove the largest non-GLiNER/non-Postgres CPU sink and stop the `kafka:29092` DNS errors across the fleet.

### P1 — Cut the running container fleet for local dev (highest raw CPU reclaim)
- **What:** 48 consumer/worker/dispatcher containers on 14 cores is the structural cause of load 142. Most are idle-polling.
- **Change:** Provide a slimmed compose profile that runs one consumer per logical group instead of every specialized consumer, collapses the 3 `nlp-pipeline-article-consumer` replicas to 1 for local dev, and disables datasets/consumers not under active test. (`infra/compose/docker-compose.yml`.)
- **Impact:** Directly proportional CPU reclaim. Dropping from 48 to ~20 consumers should bring load from ~150 toward the 14-core ceiling, ending starvation.

### P2 — Enforce real CPU limits (the compose caps are no-ops today)
- **What:** `deploy.resources.limits.cpus` is ignored by `docker compose up`; `NanoCpus=0` everywhere.
- **Change:** Use the Compose `cpus:` short-form (top-level service key, honored by compose) or `cpu_quota`/`cpu_period` for the heavy offenders (GLiNER, Postgres, market-data consumers) so no container can monopolize cores. Add reservations for the infra trio (Kafka/MinIO already partly done).
- **Impact:** Prevents one runaway consumer/GLiNER from starving Kafka heartbeats — caps the blast radius even if a hot loop reappears.

### P3 — Raise idle poll intervals for the 0-task loops
- **What:** `content-ingestion` & `market-ingestion` workers claim 0 tasks every 5s indefinitely; 7 outbox dispatchers poll at 1.0s.
- **Change:** Increase `worker_idle_sleep_seconds` 5.0 → 15–30s when consecutive empty claims occur (exponential backoff), and raise dev outbox `dispatcher_poll_interval*` 1.0 → 3–5s. Files: `services/content-ingestion/config.py:173`, `services/market-ingestion/config.py:161`, the four `dispatcher_poll_interval*` settings.
- **Impact:** Removes a constant CPU + Postgres SELECT floor from ~10 always-on loops. Modest per-loop, meaningful in aggregate at this fleet size.

### P4 — Resampling consumer (only genuine local CPU-bound numeric path)
- **What:** `intraday_resampling_consumer` runs a per-bar Python resample into all coarser timeframes.
- **Change:** Batch the resample (vectorize across bars / group by timeframe once) instead of `for bar in domain_bars: use_case.execute(...)`. File: `services/market-data/.../intraday_resampling_consumer.py:283`.
- **Impact:** Cuts the one real per-message CPU cost among non-excluded services; secondary to P0–P1 but worth it once the box is unsaturated.

### Not needed
- **No native-arch rebuilds required** — everything is already arm64.
- **No ML offloading required** — embeddings + extraction are already on DeepInfra; Ollama is idle.

---

## Appendix — key commands & evidence
- `uname -m` → `arm64`; `docker info` → 14 CPUs, 50 GB.
- `/proc/loadavg` (inside kafka container) → `141.93 190.92 159.87` then `104.73 175.11 155.86`.
- `docker inspect market-data-ohlcv-consumer-1 → RestartCount=103`.
- Kafka client errors observed in 4 consumers: `Failed to resolve 'kafka:29092'`, `ApiVersionRequest failed … broker version < 0.10`, `SESSTMOUT … revoking assignment and rejoining group`, `REQTMOUT HeartbeatRequest`.
- `docker inspect kafka-1 → NanoCpus=0` despite `cpus: "2.0"` in compose (limit not enforced).
- nlp logs → `POST api.deepinfra.com/v1/openai/embeddings 200` (no Ollama fallback).
