# Metrics-Server Coverage Audit — 13 Entrypoints (PLAN-0107 / Wave B-2)

**Date:** 2026-06-06
**Author:** Wave B-2 investigation
**Source plan:** `docs/plans/0107-observability-followups-plan.md` §B.3
**Scope:** Verdict (INTENTIONAL vs OVERSIGHT) for each of the 13 `*_main.py` entrypoints flagged in B.3 as missing `start_metrics_server`.

---

## 1. Executive Summary

| Metric | Count |
|--------|------:|
| Total audited                | 13 |
| **OVERSIGHT** (wire in B-3)  | **8** |
| **INTENTIONAL** (document)   | **5** |

Method per entrypoint:

1. Read entrypoint file to confirm it lacks `start_metrics_server`.
2. Search `infra/compose/docker-compose.yml` for a compose service whose `command:` invokes this module.
3. If a compose service exists: check `expose:` declaration and `infra/prometheus/prometheus.yml` for a matching scrape job.
4. Verdict:
   - **INTENTIONAL** — no compose service runs this entrypoint (dead-code path, manual-only utility, or co-hosted inside another process).
   - **OVERSIGHT** — compose runs this entrypoint as a standalone container; metrics are not exposed despite the container being a legitimate scrape target.

All 13 files were verified to contain **zero** occurrences of `start_metrics_server` (grep at audit time).

---

## 2. Per-Entrypoint Table

| # | File | Compose service | Verdict | Rationale |
|---|------|------------------|---------|-----------|
| 1 | `services/alert/src/alert/infrastructure/messaging/outbox/dispatcher_main.py` | `alert-dispatcher` (compose L1937) | **OVERSIGHT** | Standalone container. No `expose: 9100`, no scrape job. Dispatcher pattern elsewhere (portfolio-dispatcher, market-ingestion-dispatcher) does expose 9100 — this is a missed alignment. |
| 2 | `services/content-ingestion/src/content_ingestion/infrastructure/messaging/consumers/document_ready_consumer_main.py` | *(none)* — co-hosted | **INTENTIONAL** | No compose service invokes this module. The `document.ready` topic is consumed inside `content-ingestion-worker` (which already exposes /metrics on 9100). Module is a legacy/optional entrypoint. |
| 3 | `services/content-ingestion/src/content_ingestion/infrastructure/scheduler/scheduler_main.py` | `content-ingestion-scheduler` (L718) | **OVERSIGHT** | Standalone scheduler container. No `expose: 9100`, no scrape job. Parallel scheduler containers (`market-ingestion-scheduler`, `alert-email-scheduler`) both expose 9100 — alignment gap. |
| 4 | `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/instrument_discovered_consumer_main.py` | `knowledge-graph-instrument-discovered-consumer` (L1713) | **OVERSIGHT** | Standalone consumer container (separate from `knowledge-graph-instrument-consumer`). No `expose: 9100`, no scrape job. Sibling KG consumers (entity-consumer, fundamentals-consumer, temporal-event-consumer) all expose 9100. |
| 5 | `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/narrative_refresh_consumer_main.py` | *(none)* — not deployed | **INTENTIONAL** | No compose service references this module. Narrative refresh runs inside the `knowledge-graph-scheduler` container's job loop. The standalone entrypoint is reserved for future split-out but currently unused. |
| 6 | `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/structured_enrichment_consumer_main.py` | *(none)* — not deployed | **INTENTIONAL** | No compose service references this module. Structured enrichment is handled inside `knowledge-graph-enriched-consumer` (which exposes 9100). Standalone entrypoint unused. |
| 7 | `services/market-data/src/market_data/infrastructure/messaging/consumers/insider_transactions_consumer_main.py` | *(none)* — not deployed | **INTENTIONAL** | No compose service references this module. Insider transactions land via the dataset-side flow (`knowledge-graph-insider-transactions-dataset-consumer`). Standalone S3-side consumer entrypoint exists but is not wired into compose. |
| 8 | `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer_main.py` | `market-data-ohlcv-consumer` (L862) | **OVERSIGHT** | Standalone consumer container. No `expose: 9100`, no scrape job. Sibling market-data consumers (quotes, fundamentals, prediction-market, intraday-resampling) all expose 9100. |
| 9 | `services/market-data/src/market_data/infrastructure/messaging/outbox/dispatcher_main.py` | `market-data-dispatcher` (L839) | **OVERSIGHT** | Standalone dispatcher container. No `expose: 9100`, no scrape job. Every other dispatcher in the platform exposes 9100 — this is the most obvious alignment gap. |
| 10 | `services/market-ingestion/src/market_ingestion/infrastructure/workers/reclaim_worker_main.py` | *(none)* — co-hosted | **INTENTIONAL** | No compose service references this module. Expired-lease reclaim is performed by `market-ingestion-worker` (BP-112 fix) via the shared task repository; the standalone `reclaim_worker_main.py` is a manual operator utility, not a deployed sidecar. |
| 11 | `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/entity_refresh_consumer_main.py` | `nlp-pipeline-entity-refresh-consumer` (L1372) | **OVERSIGHT** | Standalone consumer container. `expose: 9100` is **already declared** in compose but the code never calls `start_metrics_server`, so port 9100 silently returns connection-refused. Also: no scrape job in `prometheus.yml`. Double miss. |
| 12 | `services/portfolio/src/portfolio/infrastructure/messaging/consumers/instrument_consumer_main.py` | `portfolio-instrument-consumer` (L310) | **OVERSIGHT** | Standalone consumer container. No `expose: 9100`, no scrape job. The other portfolio sidecars (dispatcher, snapshot-worker, brokerage-sync) all expose 9100. |
| 13 | `services/rag-chat/src/rag_chat/infrastructure/scheduling/brief_scheduler_main.py` | `rag-chat-brief-scheduler` (L2079) | **OVERSIGHT** | Standalone scheduler container. `9100:9100` host-port mapping is **already declared** (the compose comment at L2077 explicitly mentions `rag_brief_pregeneration_*` metrics on 9100) and a Grafana panel exists for these metrics — but the code never calls `start_metrics_server`. No scrape job in `prometheus.yml`. The metrics are completely silent. |

---

## 3. Compose / Prometheus Cross-Reference (OVERSIGHT items only)

For each OVERSIGHT row, this section enumerates the **verbatim** compose service name plus the exact YAML snippets B-3 must add. The wiring change in code is always the same: insert `start_metrics_server(service_name="<svc>", port=9100)` immediately after `configure_logging(...)`.

### 3.1 `alert-dispatcher`

- **Compose:** add under existing service block (after `command:`, L1951):
  ```yaml
      expose: ["9100"]
  ```
- **Prometheus scrape job:** append to `infra/prometheus/prometheus.yml`:
  ```yaml
    - job_name: "alert-dispatcher"
      static_configs:
        - targets: ["alert-dispatcher:9100"]
  ```

### 3.2 `content-ingestion-scheduler`

- **Compose:** add `expose: ["9100"]` after L723 `command:`.
- **Prometheus:**
  ```yaml
    - job_name: "content-ingestion-scheduler"
      static_configs:
        - targets: ["content-ingestion-scheduler:9100"]
  ```

### 3.3 `knowledge-graph-instrument-discovered-consumer`

- **Compose:** add `expose: ["9100"]` after L1729 `command:`.
- **Prometheus:**
  ```yaml
    - job_name: "knowledge-graph-instrument-discovered-consumer"
      static_configs:
        - targets: ["knowledge-graph-instrument-discovered-consumer:9100"]
  ```

### 3.4 `market-data-ohlcv-consumer`

- **Compose:** add `expose: ["9100"]` after L876 `command:`.
- **Prometheus:**
  ```yaml
    - job_name: "market-data-ohlcv-consumer"
      static_configs:
        - targets: ["market-data-ohlcv-consumer:9100"]
  ```

### 3.5 `market-data-dispatcher`

- **Compose:** add `expose: ["9100"]` after L853 `command:`.
- **Prometheus:**
  ```yaml
    - job_name: "market-data-dispatcher"
      static_configs:
        - targets: ["market-data-dispatcher:9100"]
  ```

### 3.6 `nlp-pipeline-entity-refresh-consumer`

- **Compose:** `expose: ["9100"]` is **already present** (L1385) — no compose edit needed.
- **Prometheus:**
  ```yaml
    - job_name: "nlp-pipeline-entity-refresh-consumer"
      static_configs:
        - targets: ["nlp-pipeline-entity-refresh-consumer:9100"]
  ```

### 3.7 `portfolio-instrument-consumer`

- **Compose:** add `expose: ["9100"]` after L326 `command:`.
- **Prometheus:**
  ```yaml
    - job_name: "portfolio-instrument-consumer"
      static_configs:
        - targets: ["portfolio-instrument-consumer:9100"]
  ```

### 3.8 `rag-chat-brief-scheduler`

- **Compose:** `9100:9100` host-port mapping is already declared (L2094); also add an `expose: ["9100"]` for clarity (optional — `ports:` implies expose).
- **Prometheus:**
  ```yaml
    - job_name: "rag-chat-brief-scheduler"
      static_configs:
        - targets: ["rag-chat-brief-scheduler:9100"]
  ```

---

## 4. Wave B-3 Work-List (priority order)

Highest-impact items first. Each item = one OVERSIGHT row from §3.

1. **`rag-chat-brief-scheduler`** — A Grafana panel and metric names (`rag_brief_pregeneration_*`) already exist and rely on this; today they are silent. Highest user-visible payoff.
2. **`market-data-dispatcher`** — Outbox dispatcher metrics (`*_outbox_dispatched_total`, `*_outbox_dispatch_errors_total`) feed the new C.1 recording rules (`job:outbox_dispatched:rate5m`). Without scrape, the C-1 outbox-health dashboard remains partly dark for the S5 service.
3. **`alert-dispatcher`** — Same outbox-health rationale; needed for symmetry across all six service dispatchers (5 already scraped, alert is the only laggard).
4. **`nlp-pipeline-entity-refresh-consumer`** — Compose already declares `expose: 9100`; only a code line + scrape job are missing. Smallest delta, cleanest fix.
5. **`market-data-ohlcv-consumer`** — Highest-traffic market-data consumer; lag/throughput visibility is operationally important.
6. **`content-ingestion-scheduler`** — Scheduler cadence/health is opaque without metrics; parallel schedulers already scraped.
7. **`portfolio-instrument-consumer`** — Lower volume but needed for portfolio sidecar parity.
8. **`knowledge-graph-instrument-discovered-consumer`** — Lowest priority (low traffic, narrow scope), but trivial to wire alongside its KG siblings.

### 4.1 Files B-3 will touch

- 8 Python entrypoints listed in §3.1–§3.8 (one `start_metrics_server(...)` call each, ~3 LOC including import).
- `infra/compose/docker-compose.yml` — 7 `expose: ["9100"]` insertions (3.1–3.5, 3.7, 3.8). 3.6 already exposed.
- `infra/prometheus/prometheus.yml` — 8 new scrape jobs (one per OVERSIGHT entry).

### 4.2 INTENTIONAL list to document in `docs/observability/metrics-coverage.md`

These five entrypoints exist as Python modules but are NOT deployed as standalone containers. They are tracked so future readers do not confuse "no /metrics" with a bug:

| Entrypoint | Effective host process |
|------------|------------------------|
| `content_ingestion/.../document_ready_consumer_main.py` | `content-ingestion-worker` (consumes `document.ready` inline) |
| `knowledge_graph/.../narrative_refresh_consumer_main.py` | `knowledge-graph-scheduler` (job-loop driven) |
| `knowledge_graph/.../structured_enrichment_consumer_main.py` | `knowledge-graph-enriched-consumer` (combined consumer) |
| `market_data/.../insider_transactions_consumer_main.py` | Not deployed; dataset flow via `knowledge-graph-insider-transactions-dataset-consumer` |
| `market_ingestion/.../reclaim_worker_main.py` | `market-ingestion-worker` (reclaim performed via shared task repo, BP-112) |

### 4.3 Validation hooks for B-3

After wiring:

- `make dev` → `curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job | test("alert-dispatcher|market-data-(dispatcher|ohlcv-consumer)|content-ingestion-scheduler|portfolio-instrument-consumer|knowledge-graph-instrument-discovered-consumer|nlp-pipeline-entity-refresh-consumer|rag-chat-brief-scheduler")) | {job: .labels.job, health: .health}'` — all 8 must be `up`.
- `tests/integration/test_metrics_coverage.py` (per acceptance §B.6.3) asserts each newly wired service exposes ≥1 metric family.

---

## 5. Sources

- Plan: `docs/plans/0107-observability-followups-plan.md` §B.3, §B.5 (Wave B-3).
- Compose: `infra/compose/docker-compose.yml` (line numbers as of HEAD `52fe7831`).
- Prometheus: `infra/prometheus/prometheus.yml` (line numbers as of HEAD `52fe7831`).
- Bug pattern referenced: BP-112 (market-ingestion expired-lease reclaim moved into shared task repo).
