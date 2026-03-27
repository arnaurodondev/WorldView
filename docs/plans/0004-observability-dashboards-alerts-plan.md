---
id: PLAN-0004
prd: N/A
title: "Observability Dashboards, Alerts & Recording Rules — Auto-Provisioned"
status: completed
created: 2026-03-27
updated: 2026-03-27
plans: 1
waves: 5
tasks: 22
---

# PLAN-0004: Observability Dashboards, Alerts & Recording Rules

## Overview

**PRD Reference**: N/A (infrastructure-only; driven by investigation of existing metrics and data flows)
**Goal**: Create declarative Grafana dashboards, Prometheus recording rules, and alert rules that auto-provision on every `docker compose up`, giving full visibility into all instrumented services without manual setup.
**Total Scope**: 1 plan, 5 waves, 22 tasks

### Current State (Investigation Summary)

**Instrumented services** (expose `/metrics` + ServiceMetrics + tracing + structlog):
| Service | Port | Standard Metrics | Custom Metrics |
|---------|------|-----------------|----------------|
| S0 API Gateway | 8000 | `api_gateway_*` (6 metrics) | none |
| S1 Portfolio | 8001 | `portfolio_*` (6 metrics) | none |
| S2 Market Ingestion | 8002 | `market_ingestion_*` (6 metrics) | none |
| S3 Market Data | 8003 | `market_data_*` (6 metrics) | none |
| S4 Content Ingestion | 8004 | `content_ingestion_*` (6 metrics) | `s4_fetches_total`, `s4_fetch_duration_seconds`, `s4_outbox_pending_total`, `s4_dlq_total` |
| S5 Content Store | 8005 | `content_store_*` (6 metrics) | `s5_articles_received_total`, `s5_duplicates_suppressed_total`, `s5_canonical_written_total`, `s5_documents_ingested_total`, `s5_minhash_lsh_candidates_total`, `s5_lsh_index_failures_total`, `s5_dedup_duration_seconds`, `s5_outbox_pending_total`, `s5_dlq_total` |

**Standard ServiceMetrics per service** (from `libs/observability`):
- `{service}_requests_total` — Counter [method, path, status]
- `{service}_request_duration_seconds` — Histogram [method, path]
- `{service}_kafka_messages_consumed_total` — Counter [topic, consumer_group]
- `{service}_kafka_messages_produced_total` — Counter [topic]
- `{service}_outbox_dispatched_total` — Counter
- `{service}_outbox_dispatch_errors_total` — Counter

**Not instrumented** (stub services, no metrics): S6 NLP Pipeline, S7 Knowledge Graph, S8 RAG Chat, S10 Alert

**Current observability infrastructure**:
- Prometheus: scrapes 6 services, **zero recording rules, zero alert rules**
- Grafana: 3 datasources provisioned (Prometheus, Tempo, Loki), **zero dashboards**
- Loki: receives Docker container logs via Alloy
- Tempo: receives OTLP traces (but OTLP_ENDPOINT empty in all service envs)
- Alloy: collects Docker logs + forwards OTLP traces
- **No Alertmanager** configured

### Kafka Event Flow (for pipeline dashboards)

```
S4 Content Ingestion ──→ content.article.raw.v1 ──→ S5 Content Store
                                                         │
                                                         ├──→ content.article.stored.v1 ──→ S6 NLP Pipeline
                                                         └──→ entity.dirtied.v1 (compacted) ──→ S7

S2 Market Ingestion ──→ market.dataset.fetched ──→ S3 Market Data (3 consumer groups)
                                                        │
                                                        ├──→ market.instrument.created ──→ S1 Portfolio
                                                        └──→ market.instrument.updated ──→ S1 Portfolio

S1 Portfolio ──→ portfolio.events.v1
             ──→ portfolio.watchlist.updated.v1 ──→ S6 NLP Pipeline
```

---

## Plan Dependency Graph

```
This plan (PLAN-0004) is fully independent:

Wave 1: Infrastructure scaffold (provisioning YAML, volumes, Alertmanager, OTLP env wiring)
    │
    ├──→ Wave 2: Prometheus recording rules + alert rules
    │       │
    │       └──→ Wave 3: Grafana dashboards — Service Overview + API Gateway
    │               │
    │               ├──→ Wave 4: Grafana dashboards — Kafka Pipeline + Outbox Health
    │               │
    │               └──→ Wave 5: Grafana dashboards — Content Pipeline + Logs Explorer
    │
    └── (Waves 4 and 5 can run in parallel after Wave 3)
```

**Execution Order**:
1. Wave 1 — Infrastructure scaffold (no dependencies)
2. Wave 2 — Prometheus rules (depends on W1 for directory mounts)
3. Wave 3 — First dashboards (depends on W1 for dashboard provisioning + W2 for recording rules)
4. Wave 4 — Pipeline dashboards (depends on W3 for dashboard patterns established)
5. Wave 5 — Content + Logs dashboards (parallel with W4)

**No external plan dependencies.** PLAN-0004 runs independently of PLAN-0001-C/D/E.

---

## Pre-Read (agent must read before any wave)

- `infra/compose/docker-compose.yml` — current monitoring stack definition
- `infra/prometheus/prometheus.yml` — current scrape config
- `infra/grafana/provisioning/datasources/datasources.yml` — existing datasource provisioning
- `infra/alloy/config.alloy` — log/trace collection config
- `infra/tempo/tempo.yml` — trace storage config
- `infra/loki/loki-config.yml` — log storage config
- `libs/observability/src/observability/metrics.py` — ServiceMetrics definition
- `services/content-ingestion/src/content_ingestion/infrastructure/metrics/prometheus.py` — S4 custom metrics
- `services/content-store/src/content_store/infrastructure/metrics/prometheus.py` — S5 custom metrics
- `docs/BUG_PATTERNS.md`

---

## Wave 1: Infrastructure Provisioning Scaffold ✅

**Goal**: Set up the directory structure, Grafana dashboard provisioning config, Prometheus rules directory mount, Alertmanager container, and enable OTLP endpoints in service env files — so all subsequent waves just drop files into place.
**Depends on**: none
**Estimated effort**: 30-45 minutes
**Status**: **DONE** — 2026-03-27 · docker compose config valid · all files created
**Architecture layer**: config

### Tasks

#### T-1-01: Create Grafana dashboard provisioning config

**Type**: config
**depends_on**: none
**blocks**: [T-1-02, T-3-01, T-3-02, T-4-01, T-4-02, T-5-01, T-5-02]
**Target files**:
- `infra/grafana/provisioning/dashboards/dashboards.yml` (create)

**What to build**:
Create the Grafana provisioning YAML that tells Grafana to auto-load dashboard JSON files from a mounted directory on startup. This is the critical prerequisite that enables all dashboards in Waves 3-5 to be auto-provisioned.

**Logic & Behavior**:
- Use Grafana provisioning API v1 format
- Provider name: `Worldview`
- Provider type: `file`
- Dashboard folder: `Worldview` (organizes dashboards under a named folder in Grafana UI)
- Path: `/var/lib/grafana/dashboards` (where JSON files will be mounted inside the container)
- `disableDeletion: false` (allow manual dashboard management during development)
- `updateIntervalSeconds: 30` (re-scan for changes every 30s — useful during development)
- `foldersFromFilesStructure: false` (flat folder, all dashboards in one "Worldview" folder)

**File content** (exact):
```yaml
apiVersion: 1
providers:
  - name: Worldview
    folder: Worldview
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
      foldersFromFilesStructure: false
```

**Acceptance criteria**:
- [ ] File exists at `infra/grafana/provisioning/dashboards/dashboards.yml`
- [ ] YAML is valid (parseable)
- [ ] Provider points to `/var/lib/grafana/dashboards`

---

#### T-1-02: Mount dashboard directory in Grafana container

**Type**: config
**depends_on**: [T-1-01]
**blocks**: [T-3-01, T-3-02, T-4-01, T-4-02, T-5-01, T-5-02]
**Target files**:
- `infra/compose/docker-compose.yml` (modify grafana service)
- `infra/grafana/dashboards/.gitkeep` (create — ensures directory exists in git)

**What to build**:
Add a read-only volume mount to the Grafana container so that dashboard JSON files placed in `infra/grafana/dashboards/` are available at `/var/lib/grafana/dashboards` inside the container. Also create the empty dashboards directory with a `.gitkeep`.

**Logic & Behavior**:
- Add volume mount `../grafana/dashboards:/var/lib/grafana/dashboards:ro` to the grafana service
- Place it after the existing provisioning mount
- Create `infra/grafana/dashboards/.gitkeep` so the empty directory is tracked in git

**Acceptance criteria**:
- [ ] `infra/grafana/dashboards/.gitkeep` exists
- [ ] Grafana service in docker-compose.yml has the new volume mount
- [ ] `docker compose config` validates successfully

---

#### T-1-03: Create Prometheus rules directory and mount

**Type**: config
**depends_on**: none
**blocks**: [T-2-01, T-2-02]
**Target files**:
- `infra/prometheus/rules/.gitkeep` (create)
- `infra/prometheus/prometheus.yml` (modify — add `rule_files` directive)
- `infra/compose/docker-compose.yml` (modify prometheus service — add volume mount)

**What to build**:
Set up Prometheus to auto-load recording rules and alert rules from a mounted directory. Create the directory, add the `rule_files` stanza to `prometheus.yml`, and mount the directory into the container.

**Logic & Behavior**:
- Create `infra/prometheus/rules/.gitkeep`
- In `prometheus.yml`, add after the `global:` block:
  ```yaml
  rule_files:
    - /etc/prometheus/rules/*.yml
  ```
- In docker-compose.yml, add volume mount to prometheus service:
  ```yaml
  - ../prometheus/rules:/etc/prometheus/rules:ro
  ```

**Acceptance criteria**:
- [ ] `infra/prometheus/rules/.gitkeep` exists
- [ ] `prometheus.yml` contains `rule_files` stanza pointing to `/etc/prometheus/rules/*.yml`
- [ ] Prometheus container has the rules volume mount
- [ ] `docker compose config` validates successfully

---

#### T-1-04: Add Alertmanager container

**Type**: config
**depends_on**: none
**blocks**: [T-2-02]
**Target files**:
- `infra/alertmanager/alertmanager.yml` (create)
- `infra/compose/docker-compose.yml` (modify — add alertmanager service)
- `infra/prometheus/prometheus.yml` (modify — add `alerting` block)

**What to build**:
Add an Alertmanager container to the monitoring stack so Prometheus alert rules have somewhere to route alerts. For a thesis/dev environment, configure a simple "log to stdout" receiver (no Slack/email). Wire Prometheus to send alerts to Alertmanager.

**Logic & Behavior**:
- Create `infra/alertmanager/alertmanager.yml` with a default `web.hook` receiver that logs (suitable for thesis demo — alerts visible in Alertmanager UI at `:9093`):
  ```yaml
  global:
    resolve_timeout: 5m
  route:
    receiver: default
    group_by: [alertname, job]
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 4h
  receivers:
    - name: default
  ```
- Add alertmanager service to docker-compose.yml (monitoring profile):
  - Image: `prom/alertmanager:v0.27.0`
  - Port: `9093:9093`
  - Volume: mount config file
  - Health check: `wget --spider -q http://localhost:9093/-/healthy`
  - Profile: `[monitoring, all]`
  - Depends on: prometheus (service_healthy)
- Add `alerting` block to `prometheus.yml`:
  ```yaml
  alerting:
    alertmanagers:
      - static_configs:
          - targets: ["alertmanager:9093"]
  ```
- Add `alertmanager_data` volume to docker-compose volumes section

**Acceptance criteria**:
- [ ] `infra/alertmanager/alertmanager.yml` exists and is valid YAML
- [ ] Alertmanager service defined in docker-compose with monitoring profile
- [ ] Prometheus `alerting` block points to `alertmanager:9093`
- [ ] `alertmanager_data` volume declared
- [ ] `docker compose config` validates successfully

---

#### T-1-05: Enable OTLP endpoints in service env files

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**:
- `services/portfolio/configs/docker.env`
- `services/market-ingestion/configs/docker.env`
- `services/market-data/configs/docker.env`
- `services/content-ingestion/configs/docker.env.example`
- `services/content-store/configs/docker.env.example`
- `services/api-gateway/configs/docker.env.example`

**What to build**:
Set the OTLP endpoint env var in all instrumented services' Docker env files so that tracing is enabled when running with the monitoring profile. Currently all services have `*_OTLP_ENDPOINT=` (empty), which disables tracing.

**Logic & Behavior**:
- For each service, change the OTLP endpoint value from empty to `http://alloy:4317` (Alloy receives OTLP gRPC and forwards to Tempo)
- The env var name differs per service (prefixed with service name in SCREAMING_SNAKE_CASE):
  - `PORTFOLIO_OTLP_ENDPOINT=http://alloy:4317`
  - `MARKET_INGESTION_OTLP_ENDPOINT=http://alloy:4317`
  - `MARKET_DATA_OTLP_ENDPOINT=http://alloy:4317`
  - `CONTENT_INGESTION_OTLP_ENDPOINT=http://alloy:4317`
  - `CONTENT_STORE_OTLP_ENDPOINT=http://alloy:4317`
  - `API_GATEWAY_OTLP_ENDPOINT=http://alloy:4317`
- Only modify `.env` / `.env.example` files that already exist — do NOT create new ones

**Acceptance criteria**:
- [ ] All 6 instrumented services have OTLP_ENDPOINT set to `http://alloy:4317`
- [ ] No other env vars changed
- [ ] Services can still start without the monitoring profile (tracing gracefully degrades if Alloy is unreachable — already handled by `configure_tracing()`)

---

### Validation Gate
- [ ] `docker compose -f infra/compose/docker-compose.yml config` validates (no syntax errors)
- [ ] All new directories and files exist in the correct paths
- [ ] Grafana provisioning has both `datasources/` and `dashboards/` directories
- [ ] Prometheus config has `rule_files` and `alerting` blocks
- [ ] Documentation updated (commit message is sufficient for infra-only changes)

### Regression Guardrails
- Ensure no changes to existing service definitions in docker-compose.yml (only modify grafana, prometheus; add alertmanager)
- Ensure no changes to existing datasources.yml
- Verify `.env.example` files still contain all required vars (only OTLP_ENDPOINT value changes)

---

## Wave 2: Prometheus Recording Rules + Alert Rules ✅

**Goal**: Create pre-computed recording rules for RED metrics aggregations (used by dashboards) and alert rules for critical conditions (service down, high error rate, high latency, outbox backlog, DLQ non-empty).
**Depends on**: Wave 1 (rules directory mounted)
**Estimated effort**: 30-45 minutes
**Status**: **DONE** — 2026-03-27 · 11 recording rules + 10 alert rules · YAML valid
**Architecture layer**: config

### Tasks

#### T-2-01: Create Prometheus recording rules

**Type**: config
**depends_on**: [T-1-03]
**blocks**: [T-3-01, T-3-02]
**Target files**:
- `infra/prometheus/rules/recording-rules.yml` (create)

**What to build**:
Create Prometheus recording rules that pre-compute common aggregations. These make dashboards faster (query pre-computed series instead of raw counters) and enable consistent metric names across dashboards.

**Recording rules to create** (group: `worldview_red`):

| Rule Name | Expression | Purpose |
|-----------|-----------|---------|
| `job:http_requests:rate5m` | `sum(rate({__name__=~".+_requests_total"}[5m])) by (job)` | Total request rate per service |
| `job:http_errors:rate5m` | `sum(rate({__name__=~".+_requests_total", status=~"5.."}[5m])) by (job)` | 5xx error rate per service |
| `job:http_error_ratio:rate5m` | `job:http_errors:rate5m / job:http_requests:rate5m` | Error ratio per service (0.0-1.0) |
| `job_path:http_requests:rate5m` | `sum(rate({__name__=~".+_requests_total"}[5m])) by (job, path, method)` | Request rate per endpoint |
| `job:http_duration_p50:rate5m` | `histogram_quantile(0.50, sum(rate({__name__=~".+_request_duration_seconds_bucket"}[5m])) by (job, le))` | p50 latency per service |
| `job:http_duration_p95:rate5m` | `histogram_quantile(0.95, sum(rate({__name__=~".+_request_duration_seconds_bucket"}[5m])) by (job, le))` | p95 latency per service |
| `job:http_duration_p99:rate5m` | `histogram_quantile(0.99, sum(rate({__name__=~".+_request_duration_seconds_bucket"}[5m])) by (job, le))` | p99 latency per service |

Recording rules group for Kafka (group: `worldview_kafka`):

| Rule Name | Expression | Purpose |
|-----------|-----------|---------|
| `job_topic:kafka_consumed:rate5m` | `sum(rate({__name__=~".+_kafka_messages_consumed_total"}[5m])) by (job, topic, consumer_group)` | Kafka consumption rate per consumer group |
| `job:kafka_produced:rate5m` | `sum(rate({__name__=~".+_kafka_messages_produced_total"}[5m])) by (job, topic)` | Kafka production rate per service |
| `job:outbox_dispatched:rate5m` | `sum(rate({__name__=~".+_outbox_dispatched_total"}[5m])) by (job)` | Outbox dispatch rate per service |
| `job:outbox_errors:rate5m` | `sum(rate({__name__=~".+_outbox_dispatch_errors_total"}[5m])) by (job)` | Outbox error rate per service |

**File structure** (exact YAML):
```yaml
groups:
  - name: worldview_red
    interval: 30s
    rules:
      - record: job:http_requests:rate5m
        expr: sum(rate({__name__=~".+_requests_total"}[5m])) by (job)
      # ... (all rules above)

  - name: worldview_kafka
    interval: 30s
    rules:
      - record: job_topic:kafka_consumed:rate5m
        expr: ...
      # ... (all rules above)
```

**Acceptance criteria**:
- [ ] File exists at `infra/prometheus/rules/recording-rules.yml`
- [ ] YAML is valid
- [ ] All 11 recording rules defined
- [ ] Rules use `{__name__=~".+_..."}` pattern to match across all services dynamically (no hardcoded service names)
- [ ] `promtool check rules infra/prometheus/rules/recording-rules.yml` passes (if promtool available) — otherwise manual YAML validation

---

#### T-2-02: Create Prometheus alert rules

**Type**: config
**depends_on**: [T-1-03, T-1-04]
**blocks**: none
**Target files**:
- `infra/prometheus/rules/alert-rules.yml` (create)

**What to build**:
Create Prometheus alert rules for critical operational conditions. Alerts fire to Alertmanager (configured in W1). Thresholds are calibrated for a thesis/dev environment (more sensitive than production).

**Alert rules to create** (group: `worldview_alerts`):

| Alert Name | Expression | For | Severity | Description |
|-----------|-----------|-----|----------|-------------|
| `ServiceDown` | `up == 0` | 1m | critical | Service target is unreachable by Prometheus |
| `HighErrorRate` | `job:http_error_ratio:rate5m > 0.05` | 5m | warning | >5% of requests returning 5xx |
| `CriticalErrorRate` | `job:http_error_ratio:rate5m > 0.20` | 2m | critical | >20% of requests returning 5xx |
| `HighP95Latency` | `job:http_duration_p95:rate5m > 2.0` | 5m | warning | p95 latency >2 seconds |
| `OutboxBacklog` | `{__name__=~"s[45]_outbox_pending_total"} > 100` | 5m | warning | >100 pending outbox events (S4 or S5) |
| `DeadLetterQueueNonEmpty` | `{__name__=~"s[45]_dlq_total"} > 0` | 2m | critical | Dead-letter queue has entries |
| `OutboxDispatchErrors` | `job:outbox_errors:rate5m > 0.1` | 5m | warning | Outbox dispatch error rate >0.1/sec |
| `HighDedupLatency` | `histogram_quantile(0.95, sum(rate(s5_dedup_duration_seconds_bucket[5m])) by (tier, le)) > 2.0` | 5m | warning | S5 dedup p95 >2 seconds |
| `LSHIndexFailures` | `rate(s5_lsh_index_failures_total[5m]) > 0` | 5m | warning | S5 LSH Valkey index errors occurring |
| `ContentFetchErrors` | `sum(rate(s4_fetches_total{status="failed"}[5m])) > 0.5` | 10m | warning | S4 fetch failures sustained for 10 minutes |

**File structure** (exact YAML):
```yaml
groups:
  - name: worldview_alerts
    rules:
      - alert: ServiceDown
        expr: up == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "{{ $labels.job }} is down"
          description: "Prometheus target {{ $labels.instance }} (job: {{ $labels.job }}) has been unreachable for >1 minute."
      # ... (all alerts above with proper annotations)
```

**Annotations pattern**: Every alert must include:
- `summary`: One-line human-readable description with template variables
- `description`: Detailed description with current value (`{{ $value }}`) and label context

**Acceptance criteria**:
- [ ] File exists at `infra/prometheus/rules/alert-rules.yml`
- [ ] YAML is valid
- [ ] All 10 alert rules defined with `for`, `labels`, and `annotations`
- [ ] Severity labels are either `warning` or `critical`
- [ ] No hardcoded service names where regex patterns suffice
- [ ] Alert expressions reference recording rules from T-2-01 where appropriate (e.g., `job:http_error_ratio:rate5m`)

---

### Validation Gate
- [ ] Both YAML files are valid and parseable
- [ ] Recording rules use consistent naming convention: `{aggregation}:{metric}:{window}`
- [ ] Alert rules all have `for`, `labels.severity`, `annotations.summary`, `annotations.description`
- [ ] No duplicate rule names
- [ ] Rules reference valid metric names (cross-check with ServiceMetrics definition)

### Regression Guardrails
- Do not modify `prometheus.yml` scrape configs
- Recording rule names must not conflict with raw metric names
- Alert thresholds should be reasonable for dev environment (not production-grade)

---

## Wave 3: Grafana Dashboards — Service Overview + API Gateway ✅

**Goal**: Create the two most foundational dashboards: (1) a fleet-wide service overview showing RED metrics for all services at a glance, and (2) an API Gateway deep-dive showing per-route latency and error rates.
**Depends on**: Wave 1 (dashboard provisioning), Wave 2 (recording rules for pre-computed metrics)
**Estimated effort**: 45-60 minutes
**Status**: **DONE** — 2026-03-27 · 2 dashboards · valid JSON · no grid overlaps
**Architecture layer**: config

### Dashboard JSON Conventions

All Grafana dashboards in this plan MUST follow these conventions:
- **UID**: `worldview-<slug>` (e.g., `worldview-service-overview`) — deterministic, enables linking between dashboards
- **editable**: `true` (allow devs to tweak during development; provisioning resets on restart)
- **refresh**: `30s` (default auto-refresh interval)
- **time range**: Last 1 hour default (`from: "now-1h"`, `to: "now"`)
- **Datasource**: Use `${DS_PROMETHEUS}` variable for Prometheus, `${DS_LOKI}` for Loki — with `__inputs` or templating so Grafana resolves them against provisioned datasource names
- **Templating**: Include a `job` variable (multi-select, query: `label_values(up, job)`) so users can filter by service
- **Panel layout**: Use Grafana grid layout (24-column grid, `gridPos` with `h`, `w`, `x`, `y`)
- **Color scheme**: Use Grafana default palette; red for errors, green for success

### Tasks

#### T-3-01: Create Service Overview dashboard (RED metrics)

**Type**: config
**depends_on**: [T-1-01, T-1-02, T-2-01]
**blocks**: none
**Target files**:
- `infra/grafana/dashboards/service-overview.json` (create)

**What to build**:
A fleet-wide dashboard showing the health of all instrumented services at a glance. Uses the RED methodology (Rate, Errors, Duration) and leverages recording rules from Wave 2.

**Dashboard layout** (6 rows):

**Row 1: Service Health Status (y=0, h=4)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| Service Status | Stat (repeated per job) | `up{job=~"$job"}` | w=24 |

**Row 2: Request Rate (y=4, h=8)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| Request Rate (all services) | Time series | `job:http_requests:rate5m{job=~"$job"}` | w=12 |
| Request Rate by Endpoint | Time series | `job_path:http_requests:rate5m{job=~"$job"}` | w=12 |

**Row 3: Error Rate (y=12, h=8)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| Error Ratio (%) | Time series | `job:http_error_ratio:rate5m{job=~"$job"} * 100` | w=12 |
| 5xx Errors/sec | Time series | `job:http_errors:rate5m{job=~"$job"}` | w=12 |

**Row 4: Latency (y=20, h=8)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| p50 / p95 / p99 Latency | Time series (3 queries) | `job:http_duration_p50:rate5m`, `p95`, `p99` for `{job=~"$job"}` | w=24 |

**Row 5: Kafka Throughput (y=28, h=8)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| Messages Consumed/sec | Time series | `job_topic:kafka_consumed:rate5m{job=~"$job"}` | w=12 |
| Messages Produced/sec | Time series | `job:kafka_produced:rate5m{job=~"$job"}` | w=12 |

**Row 6: Outbox Health (y=36, h=8)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| Outbox Dispatch Rate | Time series | `job:outbox_dispatched:rate5m{job=~"$job"}` | w=8 |
| Outbox Error Rate | Time series | `job:outbox_errors:rate5m{job=~"$job"}` | w=8 |
| Active Alerts | Alert list | (Grafana built-in alert list panel) | w=8 |

**Templating variables**:
- `job`: Multi-select, query `label_values(up, job)`, include "All" option

**Acceptance criteria**:
- [ ] Valid JSON file at `infra/grafana/dashboards/service-overview.json`
- [ ] Dashboard UID: `worldview-service-overview`
- [ ] Contains 11 panels across 6 rows
- [ ] Uses recording rules (not raw `rate()` queries) for all RED panels
- [ ] `$job` template variable defined and used in all queries
- [ ] `gridPos` values are consistent (no overlapping panels)

---

#### T-3-02: Create API Gateway dashboard

**Type**: config
**depends_on**: [T-1-01, T-1-02, T-2-01]
**blocks**: none
**Target files**:
- `infra/grafana/dashboards/api-gateway.json` (create)

**What to build**:
A focused dashboard for the API Gateway (S9/S0) showing per-route performance. The API Gateway is the single entry point for all frontend requests, so this dashboard shows upstream service latency and route-level breakdowns.

**Dashboard layout** (4 rows):

**Row 1: Overview Stats (y=0, h=4)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| Total RPS | Stat | `sum(rate(api_gateway_requests_total[5m]))` | w=6 |
| Error Rate % | Stat (threshold: >5% red) | `sum(rate(api_gateway_requests_total{status=~"5.."}[5m])) / sum(rate(api_gateway_requests_total[5m])) * 100` | w=6 |
| p95 Latency | Stat (threshold: >1s yellow, >2s red) | `histogram_quantile(0.95, sum(rate(api_gateway_request_duration_seconds_bucket[5m])) by (le))` | w=6 |
| Active Alerts | Stat | Count of firing alerts for job=api-gateway | w=6 |

**Row 2: Request Breakdown (y=4, h=10)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| Requests by Route | Time series (stacked) | `sum(rate(api_gateway_requests_total[5m])) by (path)` | w=12 |
| Requests by Status Code | Time series (stacked) | `sum(rate(api_gateway_requests_total[5m])) by (status)` | w=12 |

**Row 3: Latency by Route (y=14, h=10)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| p50 Latency by Route | Time series | `histogram_quantile(0.50, sum(rate(api_gateway_request_duration_seconds_bucket[5m])) by (path, le))` | w=12 |
| p95 Latency by Route | Time series | `histogram_quantile(0.95, sum(rate(api_gateway_request_duration_seconds_bucket[5m])) by (path, le))` | w=12 |

**Row 4: Error Details (y=24, h=8)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| 4xx by Route | Time series | `sum(rate(api_gateway_requests_total{status=~"4.."}[5m])) by (path)` | w=12 |
| 5xx by Route | Time series | `sum(rate(api_gateway_requests_total{status=~"5.."}[5m])) by (path)` | w=12 |

**Acceptance criteria**:
- [ ] Valid JSON file at `infra/grafana/dashboards/api-gateway.json`
- [ ] Dashboard UID: `worldview-api-gateway`
- [ ] Contains 10 panels across 4 rows
- [ ] Stat panels have color thresholds configured
- [ ] All queries target `api_gateway_*` metrics specifically
- [ ] `gridPos` values are consistent

---

### Validation Gate
- [ ] Both JSON files are valid (parseable by `python -m json.tool`)
- [ ] Dashboard UIDs are unique
- [ ] No hardcoded datasource UIDs (use variable references or `"datasource": {"type": "prometheus", "uid": "..."}` matching provisioned name)
- [ ] All PromQL expressions are syntactically valid
- [ ] Panel grid positions don't overlap

### Regression Guardrails
- Do not modify any existing files in `infra/grafana/provisioning/`
- Dashboard JSON must be self-contained (no external dependencies beyond datasources)

---

## Wave 4: Grafana Dashboards — Kafka Pipeline + Outbox Health ✅

**Goal**: Create dashboards for monitoring the event-driven backbone: Kafka message flow across the entire pipeline and outbox dispatcher health across all services.
**Depends on**: Wave 3 (dashboard JSON conventions established)
**Estimated effort**: 45-60 minutes
**Status**: **DONE** — 2026-03-27 · 2 dashboards · valid JSON · no grid overlaps
**Architecture layer**: config

### Tasks

#### T-4-01: Create Kafka Pipeline dashboard

**Type**: config
**depends_on**: [T-1-01, T-1-02, T-2-01]
**blocks**: none
**Target files**:
- `infra/grafana/dashboards/kafka-pipeline.json` (create)

**What to build**:
A dashboard visualizing the complete Kafka event flow across the platform. Shows production and consumption rates per topic, consumer group throughput, and allows tracing an event's journey from source to sink.

**Dashboard layout** (5 rows):

**Row 1: Pipeline Overview (y=0, h=4)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| Total Events Produced/sec | Stat | `sum(job:kafka_produced:rate5m)` | w=8 |
| Total Events Consumed/sec | Stat | `sum(job_topic:kafka_consumed:rate5m)` | w=8 |
| Production-Consumption Delta | Stat (threshold: >10 yellow, >100 red) | `sum(job:kafka_produced:rate5m) - sum(job_topic:kafka_consumed:rate5m)` | w=8 |

**Row 2: Market Data Pipeline (y=4, h=8)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| Market Pipeline Flow | Time series | Production: `sum(rate({__name__=~".+_kafka_messages_produced_total", topic="market.dataset.fetched"}[5m])) by (job)` + Consumption: `sum(rate({__name__=~".+_kafka_messages_consumed_total", topic="market.dataset.fetched"}[5m])) by (job, consumer_group)` | w=12 |
| Instrument Events | Time series | `sum(rate({__name__=~".+_kafka_messages_produced_total", topic=~"market.instrument.*"}[5m])) by (topic)` + consumption by portfolio | w=12 |

**Row 3: Content Pipeline (y=12, h=8)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| Content Raw → Stored Flow | Time series | Production of `content.article.raw.v1` (S4) + Consumption of `content.article.raw.v1` (S5) + Production of `content.article.stored.v1` (S5) | w=12 |
| NLP Pipeline Input | Time series | Consumption of `content.article.stored.v1` by `nlp-pipeline-group` + Production of `nlp.article.enriched.v1` and `nlp.signal.detected.v1` | w=12 |

**Row 4: Consumer Groups (y=20, h=10)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| Consumption by Consumer Group | Time series (stacked) | `sum(rate({__name__=~".+_kafka_messages_consumed_total"}[5m])) by (consumer_group)` | w=24 |

**Row 5: Production by Service (y=30, h=10)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| Production by Service & Topic | Time series (stacked) | `sum(rate({__name__=~".+_kafka_messages_produced_total"}[5m])) by (job, topic)` | w=24 |

**Templating variables**:
- `topic`: Multi-select, query `label_values({__name__=~".+_kafka_messages_consumed_total"}, topic)`, include "All"
- `consumer_group`: Multi-select, query `label_values({__name__=~".+_kafka_messages_consumed_total"}, consumer_group)`, include "All"

**Acceptance criteria**:
- [ ] Valid JSON file at `infra/grafana/dashboards/kafka-pipeline.json`
- [ ] Dashboard UID: `worldview-kafka-pipeline`
- [ ] Contains 8 panels across 5 rows
- [ ] Visualizes the 3 main pipeline flows (market, content, portfolio→NLP)
- [ ] Template variables for topic and consumer_group filtering

---

#### T-4-02: Create Outbox Health dashboard

**Type**: config
**depends_on**: [T-1-01, T-1-02, T-2-01]
**blocks**: none
**Target files**:
- `infra/grafana/dashboards/outbox-health.json` (create)

**What to build**:
A dashboard monitoring the transactional outbox pattern across all services. The outbox is critical — if it backs up, events stop flowing. This dashboard shows dispatch rates, error rates, pending backlogs, and dead-letter queue status.

**Dashboard layout** (4 rows):

**Row 1: Outbox Overview Stats (y=0, h=4)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| Total Dispatch Rate | Stat | `sum(job:outbox_dispatched:rate5m)` | w=6 |
| Total Error Rate | Stat (threshold: >0 red) | `sum(job:outbox_errors:rate5m)` | w=6 |
| S4 Pending Outbox | Stat (threshold: >10 yellow, >100 red) | `s4_outbox_pending_total` | w=6 |
| S5 Pending Outbox | Stat (threshold: >10 yellow, >100 red) | `s5_outbox_pending_total` | w=6 |

**Row 2: Dispatch Rates (y=4, h=8)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| Outbox Dispatch Rate by Service | Time series | `job:outbox_dispatched:rate5m` (per job) | w=12 |
| Outbox Error Rate by Service | Time series | `job:outbox_errors:rate5m` (per job) | w=12 |

**Row 3: Pending Backlog (y=12, h=8)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| S4 Outbox Pending (gauge) | Time series | `s4_outbox_pending_total` | w=12 |
| S5 Outbox Pending (gauge) | Time series | `s5_outbox_pending_total` | w=12 |

**Row 4: Dead Letter Queue (y=20, h=8)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| S4 DLQ Entries | Time series (fill: red when >0) | `s4_dlq_total` | w=12 |
| S5 DLQ Entries | Time series (fill: red when >0) | `s5_dlq_total` | w=12 |

**Acceptance criteria**:
- [ ] Valid JSON file at `infra/grafana/dashboards/outbox-health.json`
- [ ] Dashboard UID: `worldview-outbox-health`
- [ ] Contains 10 panels across 4 rows
- [ ] Stat panels have color thresholds for backlog and errors
- [ ] DLQ panels highlight non-zero values in red
- [ ] Uses recording rules where available

---

### Validation Gate
- [ ] Both JSON files are valid
- [ ] Dashboard UIDs are unique across all dashboards
- [ ] PromQL expressions reference correct metric names
- [ ] Panel grid positions don't overlap

### Regression Guardrails
- Do not modify existing dashboard JSON files from Wave 3
- Ensure no hardcoded datasource UIDs

---

## Wave 5: Grafana Dashboards — Content Pipeline + Logs Explorer ✅

**Goal**: Create dashboards leveraging S4/S5 custom metrics (content ingestion and dedup pipeline) and a Loki-based log explorer dashboard for structured log querying.
**Depends on**: Wave 3 (dashboard JSON conventions established)
**Estimated effort**: 45-60 minutes
**Status**: **DONE** — 2026-03-27 · 2 dashboards · valid JSON · no grid overlaps
**Architecture layer**: config

### Tasks

#### T-5-01: Create Content Pipeline dashboard

**Type**: config
**depends_on**: [T-1-01, T-1-02]
**blocks**: none
**Target files**:
- `infra/grafana/dashboards/content-pipeline.json` (create)

**What to build**:
A dashboard showing the content ingestion and processing pipeline in detail. S4 fetches articles from external sources, S5 deduplicates and stores them. This dashboard shows fetch rates, dedup effectiveness, and processing latency.

**Dashboard layout** (5 rows):

**Row 1: Pipeline Overview Stats (y=0, h=4)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| Articles Fetched/sec | Stat | `sum(rate(s4_fetches_total{status="fetched"}[5m]))` | w=6 |
| Articles Received by S5/sec | Stat | `rate(s5_articles_received_total[5m])` | w=6 |
| Duplicates Suppressed/sec | Stat | `sum(rate(s5_duplicates_suppressed_total[5m]))` | w=6 |
| Canonical Written/sec | Stat | `rate(s5_canonical_written_total[5m])` | w=6 |

**Row 2: S4 Content Ingestion (y=4, h=8)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| Fetch Rate by Source & Status | Time series (stacked) | `sum(rate(s4_fetches_total[5m])) by (source, status)` | w=12 |
| Fetch Duration by Source (p95) | Time series | `histogram_quantile(0.95, sum(rate(s4_fetch_duration_seconds_bucket[5m])) by (source, le))` | w=12 |

**Row 3: S5 Dedup Pipeline (y=12, h=8)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| Dedup Results | Time series (stacked) | `sum(rate(s5_documents_ingested_total[5m])) by (dedup_result)` | w=12 |
| Dedup Duration by Tier (p95) | Time series | `histogram_quantile(0.95, sum(rate(s5_dedup_duration_seconds_bucket[5m])) by (tier, le))` | w=12 |

**Row 4: S5 LSH & MinHash (y=20, h=8)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| Suppression by Tier | Time series (stacked) | `sum(rate(s5_duplicates_suppressed_total[5m])) by (tier)` | w=8 |
| LSH Candidate Lookups/sec | Time series | `rate(s5_minhash_lsh_candidates_total[5m])` | w=8 |
| LSH Index Failures/sec | Time series (red fill) | `rate(s5_lsh_index_failures_total[5m])` | w=8 |

**Row 5: Backlog & DLQ (y=28, h=6)**
| Panel | Type | Query | Size |
|-------|------|-------|------|
| S4 Outbox Pending | Gauge | `s4_outbox_pending_total` | w=6 |
| S4 DLQ | Gauge (red when >0) | `s4_dlq_total` | w=6 |
| S5 Outbox Pending | Gauge | `s5_outbox_pending_total` | w=6 |
| S5 DLQ | Gauge (red when >0) | `s5_dlq_total` | w=6 |

**Templating variables**:
- `source`: Multi-select, query `label_values(s4_fetches_total, source)`, include "All"
- `tier`: Multi-select, query `label_values(s5_dedup_duration_seconds_bucket, tier)`, include "All"

**Acceptance criteria**:
- [ ] Valid JSON file at `infra/grafana/dashboards/content-pipeline.json`
- [ ] Dashboard UID: `worldview-content-pipeline`
- [ ] Contains 13 panels across 5 rows
- [ ] Covers both S4 (ingestion) and S5 (dedup/store) metrics
- [ ] Template variables for source and dedup tier filtering
- [ ] LSH failure panel uses red fill for non-zero values

---

#### T-5-02: Create Logs Explorer dashboard

**Type**: config
**depends_on**: [T-1-01, T-1-02]
**blocks**: none
**Target files**:
- `infra/grafana/dashboards/logs-explorer.json` (create)

**What to build**:
A Loki-based dashboard for exploring structured logs across all services. Since all services use structlog with JSON output captured by Alloy, this dashboard enables querying by service, log level, trace_id, and free text. Also provides a link to Tempo for trace correlation.

**Dashboard layout** (3 rows):

**Row 1: Log Volume Overview (y=0, h=6)**
| Panel | Type | Query (Loki) | Size |
|-------|------|-------------|------|
| Log Volume by Service | Time series (stacked) | `sum(count_over_time({container=~"$service"} [1m])) by (container)` | w=12 |
| Error Log Volume | Time series (red) | `sum(count_over_time({container=~"$service"} |= "error" [1m])) by (container)` | w=12 |

**Row 2: Log Stream (y=6, h=16)**
| Panel | Type | Query (Loki) | Size |
|-------|------|-------------|------|
| Log Stream | Logs panel | `{container=~"$service"} | json | level=~"$level" | line_format "{{.timestamp}} [{{.level}}] {{.service}}: {{.event}}"` | w=24 |

**Row 3: Error Details (y=22, h=10)**
| Panel | Type | Query (Loki) | Size |
|-------|------|-------------|------|
| Recent Errors | Logs panel | `{container=~"$service"} | json | level="error"` | w=24 |

**Templating variables**:
- `service`: Multi-select, query `label_values({job=~".+"}, container)`, include "All"
- `level`: Multi-select, values: `debug, info, warning, error, critical`, default: `info, warning, error, critical`
- `search`: Text box for free-text search (used as `|= "$search"` filter)

**Acceptance criteria**:
- [ ] Valid JSON file at `infra/grafana/dashboards/logs-explorer.json`
- [ ] Dashboard UID: `worldview-logs-explorer`
- [ ] Contains 4 panels across 3 rows
- [ ] Uses Loki datasource (not Prometheus)
- [ ] Template variables for service, level, and free-text search
- [ ] Log stream panel uses JSON parsing for structured log fields
- [ ] Derived fields link trace_id values to Tempo (leveraging existing Loki→Tempo derived field config in datasources.yml)

---

### Validation Gate
- [ ] Both JSON files are valid
- [ ] Dashboard UIDs are unique across all 6 dashboards
- [ ] Content pipeline dashboard queries reference correct S4/S5 metric names
- [ ] Logs explorer uses Loki queries (LogQL), not PromQL
- [ ] Panel grid positions don't overlap

### Regression Guardrails
- Do not modify existing dashboard JSON files from Waves 3-4
- Logs explorer must not hardcode container names — use template variable
- Ensure Loki queries are compatible with Alloy's label enrichment (container name from Docker labels)

---

## Cross-Cutting Concerns

### Contract Changes
None. This plan only creates infrastructure config files (YAML, JSON). No Avro schemas, REST APIs, or database schemas are modified.

### Migrations
None. No database changes.

### Configuration Changes
| Service/Component | Change | Purpose |
|-------------------|--------|---------|
| Grafana (docker-compose) | New volume mount for dashboards | Dashboard auto-provisioning |
| Prometheus (docker-compose) | New volume mount for rules | Recording/alert rule loading |
| Prometheus (prometheus.yml) | `rule_files` + `alerting` blocks | Enable rules and Alertmanager integration |
| Alertmanager (new container) | New service in docker-compose | Alert routing and silencing UI |
| All 6 instrumented services | `*_OTLP_ENDPOINT=http://alloy:4317` | Enable distributed tracing |

### Documentation Updates
| Document | Update Required |
|----------|----------------|
| `docs/MASTER_PLAN.md` § Observability | Reference new dashboards and alerts (brief mention) |
| `infra/compose/docker-compose.yml` header comments | Add `monitoring` profile usage instructions |

### Downstream Test Impact
None. This plan creates no Python code and modifies no service source. No existing tests will break.

---

## Risk Assessment

### Critical Path
**Wave 1** blocks everything — if the provisioning scaffold is wrong, no dashboards or rules will load. However, Wave 1 is entirely deterministic config files, so risk is low.

### Highest Risk
| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Dashboard JSON syntax error prevents Grafana startup | Low | Medium | Validate with `python -m json.tool` before committing |
| PromQL query in recording rule is invalid | Low | Medium | Test with `promtool check rules` if available; otherwise manual review |
| Alloy container name labels don't match Loki queries | Medium | Low | Check Alloy config relabeling rules; adjust LogQL `container=~` pattern |
| OTLP endpoint causes service startup delay if Alloy is down | Low | Low | `configure_tracing()` already handles missing endpoint gracefully (NoOp) |
| Metric names changed in future service updates | Low | Medium | Recording rules use regex patterns (`{__name__=~".+_requests_total"}`) for resilience |

### Rollback Strategy
All changes are additive config files. To roll back:
1. Remove dashboard JSON files from `infra/grafana/dashboards/`
2. Remove rule YAML files from `infra/prometheus/rules/`
3. Revert docker-compose volume mounts and Alertmanager service
4. Revert OTLP endpoint env vars to empty
5. `docker compose down && docker compose up` — clean restart

No data loss risk. No service code changes.

---

## Tracking

### Wave Status
| Wave | Status | Tasks Done | Tasks Total | Blockers |
|------|--------|-----------|-------------|----------|
| Wave 1: Infrastructure Scaffold | ✅ done | 5 | 5 | none |
| Wave 2: Prometheus Rules | ✅ done | 2 | 2 | — |
| Wave 3: Service Overview + API GW Dashboards | ✅ done | 2 | 2 | — |
| Wave 4: Kafka Pipeline + Outbox Dashboards | ✅ done | 2 | 2 | — |
| Wave 5: Content Pipeline + Logs Dashboards | ✅ done | 2 | 2 | — |

### Task Status
| ID | Task | Wave | Status |
|----|------|------|--------|
| T-1-01 | Grafana dashboard provisioning config | W1 | ✅ done |
| T-1-02 | Mount dashboard directory in Grafana | W1 | ✅ done |
| T-1-03 | Prometheus rules directory and mount | W1 | ✅ done |
| T-1-04 | Add Alertmanager container | W1 | ✅ done |
| T-1-05 | Enable OTLP endpoints in env files | W1 | ✅ done |
| T-2-01 | Prometheus recording rules | W2 | ✅ done |
| T-2-02 | Prometheus alert rules | W2 | ✅ done |
| T-3-01 | Service Overview dashboard (RED) | W3 | ✅ done |
| T-3-02 | API Gateway dashboard | W3 | ✅ done |
| T-4-01 | Kafka Pipeline dashboard | W4 | ✅ done |
| T-4-02 | Outbox Health dashboard | W4 | ✅ done |
| T-5-01 | Content Pipeline dashboard | W5 | ✅ done |
| T-5-02 | Logs Explorer dashboard | W5 | ✅ done |

### Deliverables Summary
| Category | Count | Files |
|----------|-------|-------|
| Grafana dashboards | 6 | `infra/grafana/dashboards/*.json` |
| Prometheus recording rules | 1 | `infra/prometheus/rules/recording-rules.yml` |
| Prometheus alert rules | 1 | `infra/prometheus/rules/alert-rules.yml` |
| Alertmanager config | 1 | `infra/alertmanager/alertmanager.yml` |
| Provisioning config | 1 | `infra/grafana/provisioning/dashboards/dashboards.yml` |
| Modified configs | 3 | `docker-compose.yml`, `prometheus.yml`, 6x env files |
| **Total new files** | **10** | |
