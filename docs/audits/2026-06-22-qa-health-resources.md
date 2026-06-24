# QA — Container Health & Resources (Post-Redeploy)

**Date:** 2026-06-22
**Mode:** READ-ONLY (docker ps/inspect/stats/logs — no edits, no restarts)
**Scope:** Full Worldview Docker Compose stack after a full redeploy (~88 containers Up)
**Repo:** `/Users/arnaurodon/Projects/University/final_thesis/worldview`

---

## Executive Summary

The post-redeploy stack is **healthy and stable**. Of 88 running `worldview-*` containers:

- **0 restart loops** — every running container has `RestartCount=0` (re-checked after ~2 min elapsed, none climbing).
- **0 functional failures** — no OOM-kills, no crash loops, no wedged/high-CPU-low-throughput containers.
- **2 containers report `unhealthy`**, but BOTH are **cosmetic healthcheck-config bugs** — the underlying workers are running and doing real work. Neither is a functional outage.
- All resource-capped containers are comfortably under their limits (no OOM risk).
- **Prior-session fixes CONFIRMED NOT recurring**: alert-intelligence-consumer (F-006 os._exit loop) and market-data-ohlcv-consumer (_MAX_PARAMS crash) are both stable at RestartCount=0 and processing normally. KG/NLP services started cleanly on `postgres-intelligence`.

---

## Ranked Issue Table

| # | Container | State | RestartCount | CPU / Mem | Issue | Severity |
|---|-----------|-------|--------------|-----------|-------|----------|
| 1 | `worldview-knowledge-graph-scheduler-1` | Up (unhealthy) | 0 | 0.73% / 120 MiB | **Healthcheck port mismatch** — probe hits `:9100/healthz` but the scheduler binds its metrics/health server to **port 9108** (`scheduler_main.py:71`). Worker is fully functional (fundamentals refresh, narrative gen, DeepInfra 200s). FailingStreak=4. Cosmetic. | **MEDIUM** (false-unhealthy; no functional impact) |
| 2 | `worldview-portfolio-manual-holdings-worker-1` | Up (unhealthy) | 0 | 0.47% / 73 MiB | **Wrong/missing healthcheck** — compose block has NO `healthcheck:` and NO `expose: 9100`, so it inherits the Dockerfile default API probe `:8000/readyz` (Dockerfile:64). The worker actually binds metrics on **9100** and is running (`manual_holdings_worker_started`, sleeping 41463s). FailingStreak=6. Cosmetic. | **MEDIUM** (false-unhealthy; no functional impact) |
| 3 | `worldview-mailhog-1` | Exited (137) 24h ago | n/a | n/a | Pre-existing orphan OOM-kill (`OOMKilled=true`), predates this deploy session. Not a current-session regression. | **LOW / INFO** (pre-existing, out of scope) |

No HIGH-severity findings. No restart loops, no current OOM, no resource outliers.

---

## 1. Health States

`docker ps -a` shows 88 `worldview-*` containers Up, all `(healthy)` except the two below. Benign one-shot `*-migrate-1` / `*-init-1` containers all `Exited (0)` as expected. Pre-existing orphans with random names (`modest_stonebraker`, `unit_*`, `mailhog`, `determined_vaughan`, `sharp_kowalevski`, `focused_tesla`, `fixit-backend-postgres-1`) noted but out of scope.

### 1a. `knowledge-graph-scheduler-1` — UNHEALTHY (false alarm)

- **Healthcheck def** (compose `docker-compose.yml:1820`):
  `python -c "...urlopen('http://localhost:9100/healthz', timeout=4)..."`
- **Probe error:** `ConnectionRefusedError: [Errno 111] Connection refused` on `:9100`.
- **Root cause:** `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler_main.py:71` calls
  `start_metrics_server(service_name="knowledge-graph-scheduler", port=9108)` — it binds **9108**, not 9100. (Comment in source notes 9108 is "preserved for backwards compatibility with the existing Prometheus scrape job.") The compose probe was never updated to match. Sibling KG consumers (e.g. `enriched_consumer_main.py`) bind 9100 and pass the same probe.
- **Functional state: HEALTHY.** Logs show active work: `fundamentals_refresh_worker_complete`, `narrative_generation_complete`, DeepInfra `200 OK`, embeddings batch OK. The 2h interval job "executed successfully."
- **Fix (not applied — read-only):** change the compose probe to `:9108/healthz`, OR change `scheduler_main.py` to bind 9100 and add `expose: ["9100"]`.

### 1b. `portfolio-manual-holdings-worker-1` — UNHEALTHY (false alarm, KNOWN)

- **Healthcheck def (inherited from Dockerfile, NOT overridden in compose):**
  `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz')"` (Dockerfile:64-65 — the API readiness probe).
- **Probe error:** `ConnectionRefusedError: [Errno 111]` on `:8000` — this worker has no API server on 8000.
- **Root cause:** the `portfolio-manual-holdings-worker` compose block (`docker-compose.yml:497`) defines neither a `healthcheck:` override nor `expose: ["9100"]`, so it falls back to the image's default API HEALTHCHECK. By contrast, its sibling `portfolio-snapshot-worker` (line ~515) correctly overrides with the `:9100/healthz` probe + `expose: ["9100"]`.
- **Functional state: HEALTHY.** Logs: `metrics_server_started port=9100`, `manual_holdings_worker_started`, then `manual_holdings_worker_sleeping sleep_seconds=41463` (working as designed; the worker binds metrics on 9100).
- **Fix (not applied — read-only):** copy the `healthcheck:` + `expose: ["9100"]` from `portfolio-snapshot-worker` onto the `portfolio-manual-holdings-worker` block.

**Pattern note:** both bugs are the same class — a worker that exposes metrics on 9100 but whose compose healthcheck targets the wrong port (9100-vs-9108 / 9100-vs-default-8000). Worth a one-time sweep of all worker compose blocks to ensure each `start_metrics_server(port=N)` matches its probe and has `expose: [N]`.

---

## 2. Restart Loops & OOM

- `RestartCount=0` for **all 88** running `worldview-*` containers; re-checked after ~2 min — none climbing.
- Exit-137 / OOMKilled scan across all `worldview-*` containers: only `worldview-mailhog-1` (exited 24h ago, pre-existing orphan). No current-session OOM.

---

## 3. Resource Outliers

Host: 46.72 GiB RAM. No memory pressure anywhere. Two `docker stats --no-stream` passes:

**Capped containers (OOM-risk watch) — all comfortably under limit:**

| Container | Mem | Limit | % |
|-----------|-----|-------|---|
| `gliner-server` | 1.87 GiB | 8 GiB | 23% |
| `kafka` | 780 MiB | 6 GiB | 13% |
| `minio` | 1.43 GiB | 4 GiB | 36% |
| `ollama` | 22 MiB | 6 GiB | <1% |
| `valkey` | 115 MiB | (no docker limit; redis maxmemory 1536mb internal) | — |

- `gliner-server` CPU 0.13% — the thread-pin fix (threads=4) is holding; no thread-thrash recurrence.
- `valkey` `HostConfig.Memory=0` (no cgroup limit). The `maxmemory=1536mb` is an internal redis eviction policy, not a Docker hard cap — so no docker OOM-kill risk; redis will evict before exhausting.
- Highest CPU at snapshot: `postgres-1` (25–58%, normal write activity), `market-data-fundamentals-consumer` (45% momentary). No high-CPU-low-throughput wedge pattern observed.

---

## 4. Prior-Fix Regression Cross-Check

| Fix | Container | Result |
|-----|-----------|--------|
| F-006 (alert wedge — should NOT os._exit loop) | `alert-intelligence-consumer-1` | **PASS** — RestartCount=0, steady-state processing `watchlists/by-entity 200 OK`. No exit loop. |
| OHLCV crash (`_MAX_PARAMS`) | `market-data-ohlcv-consumer-1` | **PASS** — RestartCount=0, `ohlcv_consumer.materialized` flowing for many symbols. No crash loop. |
| KG/NLP on `postgres-intelligence` | `knowledge-graph-1`, `nlp-pipeline-1`, `knowledge-graph-enriched-consumer-1` | **PASS** — clean startup, no connection-refused / fatal / traceback in logs. |

---

## Conclusion

Deploy is **green**. No HIGH-severity issues. The only two `unhealthy` flags are misconfigured healthchecks on functional workers (MEDIUM, cosmetic — they pollute the health dashboard and could mask a real failure, so worth fixing, but no outage). All previously-fixed crash/wedge patterns remain resolved.
