# QA Report: Live Running Instances

**Date**: 2026-06-21 ~18:45 UTC
**Skill**: qa (live-instance variant)
**Scope**: Running platform — verify this session's deployed work end-to-end (Kafka resilience, AI brief, beta/alpha, frontend fixes, data pipeline, S9 API, container/DB health)
**Branch**: feat/frontend-enhancement-sprint
**Verdict**: **PASS_WITH_WARNINGS** — all session code fixes verified holding; the degradation found was operational (down services), fixed during the pass.

---

## Executive Summary

Five specialist agents ran live QA against the running platform (S9 @ :8000, web @ :3001, the containers + DBs). The session's **core deployed work is verified holding**: the Kafka-resilience fixes show **0 wedge signals / 0 connection-timeouts / 0 crash-loops** across all 8 dispatchers; the AI brief is **populated**; chat streams real grounded answers; the news/KG/NLP pipeline is healthy and in sync. However, the pass caught a **real platform degradation** — MinIO had been OOM-killed (~6h), and three API tiers (portfolio/market-data/alert) were stuck `Created` because their migrate sidecars had failed earlier — which blocked live verification of several fixes. **All were restored during the QA pass** (MinIO restarted, the three services started cleanly once the committed migration fix `37ecd4e3b` no-op'd, and a **stale api-gateway image** was rebuilt to deploy the beta/alpha date-parse fix). Post-restoration, **every previously-blocked fix verifies**: portfolios/movers/screener return 200, **beta/alpha compute (1.1218 / 1.7067)**, and OHLCV materialization resumed (0 S3 failures). Remaining items are non-blocking follow-ups.

---

## Multi-Agent Review Summary

| Agent | Domain | Verdict | Key signal |
|-------|--------|---------|-----------|
| QA/Functional (S9) | API endpoints | DEGRADED→PASS | brief populated; chat real; 3 tiers were 500 (now up) |
| Data Platform | pipeline/DBs | PARTIAL→PASS | news/KG healthy; OHLCV was MinIO-blocked (now flowing) |
| Distributed Systems | Kafka resilience | **PASS** | 0 wedge/crash signals; broker 4G+G1GC clean; fixes holding |
| Frontend | web + data | PASS (infra-blocked) | routes 200; brief+momentum data clean; analytics blocked (now up) |
| Security + Health | auth/secrets/health | DEGRADED→PASS | auth enforced, no secret leak; 3 tiers down (now up) |

---

## ✅ Verified holding (this session's work)

- **Kafka resilience (BP-704/705/706)**: 0 `dispatch_failed`, 0 `Connection setup timed out`, 0 empty-error wedges across all 8 dispatchers (`--since 15m`); broker heap `-Xmx4G` + G1GC confirmed, broker logs clean (0 `controller event queue overloaded`); all dispatchers healthy on new images.
- **AI brief**: `GET /v1/briefings/morning` returns a full multi-section narrative (market snapshot, portfolio, macro, news) with citations `[c1]–[c7]` — not the placeholder.
- **Chat**: SSE streams a real grounded answer (news-grounded query returned 10 real articles + final answer).
- **News/KG/NLP pipeline**: 25,057 canonical entities (3,329 with descriptions), 13,449 relations, AGE graph in sync (13,979 edges ≈ relations), fundamentals fresh (today). No all-green-zero-output.
- **Security**: auth enforced (401 no-token / 401 invalid / 200 valid; internal routes not publicly reachable); no secrets leaked in logs; no stack-trace/SQL leakage to clients; security headers present.
- **Frontend**: web container healthy, all key routes 200; momentum data consistent **%** units (the fix); SPY/QQQ benchmark series present.
- **beta/alpha (BP-682)**: **1.1218 / 1.7067** (verified after the api-gateway rebuild).

---

## 🔴 Degradation found AND fixed during the pass

### F-001 (CRITICAL→RESOLVED): MinIO OOM-killed, OHLCV materialization blocked
`worldview-minio-1` Exited (137, OOMKilled) at 12:57 UTC (~6h before QA); every `market.dataset.fetched` failed its S3 download in a retry loop, 0 OHLCV bars materializing. A stray `priceless_curie` MinIO container also existed.
**Fix applied**: removed the stray container, `up -d minio` → healthy; OHLCV materialization resumed (**150 bars / 3 min, 0 S3 failures**).

### F-002 (CRITICAL→RESOLVED): portfolio/market-data/alert API tiers stuck `Created`
The three API containers never started because their migrate sidecars had failed (old non-idempotent `0025`; missing revisions `041`/`0010`). The source fix (`37ecd4e3b`) was committed and the DBs already at head, but the containers were left un-started.
**Fix applied**: `up -d portfolio market-data alert` → all three migrate sidecars now **Exit 0** (no-op, DB at head) and the APIs are **healthy**. `/v1/portfolios`, `/v1/market/top-movers` now 200.

### F-003 (CRITICAL→RESOLVED): stale api-gateway image — beta/alpha date-parse fix not deployed
Despite `2ea10ac6d` being committed (and verified live earlier by the implementing agent), the **running api-gateway image lacked `_parse_iso_date`** → `data_quality.benchmark="no_data"`, beta/alpha null. The deployed image had drifted behind the commit.
**Fix applied**: rebuilt + recreated api-gateway → **beta/alpha compute (1.1218 / 1.7067)**, no degradation.

---

## 🟠 Remaining follow-ups (non-blocking)

### F-004 (MAJOR): market-data `idle in transaction` connection leak
15–23 backends held `idle in transaction` for ~25 min after `INSERT INTO failed_tasks` — a missing `commit()`/`rollback()` on the worker's failed-task error path. Cascade-amplified by F-001/F-002; **cleared to 1 after restoration**, but the underlying code bug remains. *Fix*: scope the `failed_tasks` insert in a committed UoW / ensure the error branch closes the transaction. Recommend `/fix-bug`.

### F-005 (MAJOR): consumer liveness probe is not stall-aware
The Docker healthcheck is `python -c "os.kill(1,0)"` (PID-1 alive only) — it does NOT reflect Kafka/consume liveness, so a wedged/stalled consumer still reports Docker "healthy" (the BP-704 `make_liveness_probe`/`/healthz` work isn't wired into the orchestrator healthcheck). *Fix*: point the compose `healthcheck` at the `/healthz` liveness endpoint on the metrics port.

### F-006 (MAJOR): alert-intelligence-consumer watchdog crash-loop (pre-existing)
`alert-intelligence-consumer` RestartCount=10, `intelligence_consumer_watchdog_stall ... presumed_wedged` every ~5 min — an over-aggressive progress watchdog firing on **idle low-traffic topics** (0 Kafka connection errors; NOT a wedge regression). *Fix*: gate the watchdog on partition-assignment + recent traffic so an idle topic doesn't trip it.

### F-007 (MEDIUM): Valkey rate-limiter degraded on the quotes path
Gateway logs `valkey_operation_failed → 503_no_retry` then 429/503 on `/v1/quotes/*`, though Valkey reports healthy. *Fix*: investigate the Valkey op failure (connection/auth) on the rate-limit path.

### F-008 (MINOR): dead-letter backlog + observability stack
24,162 terminal `market.dataset.fetched` dead rows (empty `last_error` — observability gap) need a deliberate requeue (the replay mechanism is proven). The observability stack (grafana/prometheus/loki/tempo) is down (Exited 137) — non-blocking but no metrics/traces.

---

## Recommendations (priority order)
1. **F-004** — fix the market-data failed-task transaction leak (real correctness bug). `/fix-bug`.
2. **F-005** — wire `/healthz` into the Docker healthcheck so BP-704's liveness actually gates orchestration.
3. **F-006/F-007** — alert watchdog gating + Valkey rate-limit path.
4. **F-008** — requeue the 24k dead-letter backlog in paced waves; populate `last_error` on dead-letter; bring the observability stack back up.

## Compounding
- The migrate-divergence + stale-image class (F-002/F-003) reinforces: **a committed fix is not deployed until the image is rebuilt**; `make rebuild` aborting on a migrate failure leaves the API container `Created` + a stale image silently serving — worth a deploy-hygiene note alongside `docs/ops/docker-build-hygiene.md`.
- F-005 (liveness not wired to healthcheck) is the operational gap behind BP-700/704 — recommend folding into those BP entries.
