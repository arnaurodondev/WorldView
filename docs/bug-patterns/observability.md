# Bug Patterns — Observability

> **Category**: observability
> **Description**: Prometheus metrics, Grafana, Alertmanager, structlog/OTel, metric definition and wiring patterns
> **Count**: 9 patterns
> **Back to index**: [BUG_PATTERNS.md](../BUG_PATTERNS.md)

---

## BP-173 — `create_metrics()` Isolated CollectorRegistry Makes All Shared-Lib Metrics Invisible

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (observability audit) |
| **Severity** | CRITICAL — all HTTP, Kafka, and outbox metrics for 10 services emit zero data |
| **Affected areas** | `libs/observability/src/observability/metrics.py:52`; all services calling `create_metrics()` (S1–S10 except S4/S5 which use their own module-level counters) |
| **Root cause** | `create_metrics()` defaults to `registry or CollectorRegistry()`, which creates a brand-new isolated registry every time it is called without an explicit registry argument. All returned `Counter`/`Histogram` objects are registered in this isolated registry. When Prometheus scrapes `/metrics`, the FastAPI app calls `prometheus_client.generate_latest()`, which reads from the global `REGISTRY` singleton. The custom metrics are in a different object (`reg`) that `generate_latest()` never sees. Result: 60 metric families across 10 services are permanently invisible. |
| **Symptom** | `GET /metrics` returns only Python process metrics (`python_gc_*`, `process_*`). Service-level counters (`s1_requests_total`, `s3_kafka_messages_consumed_total`, etc.) appear as 0 series in Prometheus and are absent from all Grafana panels. |
| **Fix** | Change `libs/observability/metrics.py:52` from `reg = registry or CollectorRegistry()` to `reg = registry if registry is not None else REGISTRY` (where `REGISTRY` is imported from `prometheus_client`). Tests that pass an isolated registry to avoid duplicate-registration errors continue to work unchanged. Services that pass `None` (the production default) will now correctly register in the global registry. Added `_global_registry_cache: dict[str, ServiceMetrics]` to make `create_metrics()` idempotent for the global REGISTRY — returns the cached instance when the same `service_name` is called again, avoiding `ValueError: Duplicated timeseries` in test suites that instantiate consumers multiple times. |

### Prevention

When writing shared-library metrics helpers that accept an optional `registry` parameter, always check `is not None` (not truthiness) to distinguish "no registry provided" from "explicit registry". `CollectorRegistry()` is falsy in Python 3.12+ because it defines no `__bool__`; relying on `or` to fall back causes the same bug. Only use an isolated registry in tests. The global `REGISTRY` must be the default for all production code.

**Grep pattern** (find the bug in any shared metrics helper):
```bash
grep -rn "registry or CollectorRegistry\(\)" libs/ services/ --include="*.py"
```

---

---

## BP-174 — Dead Metric Definitions (Metric Defined but Never Incremented)

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (observability audit) |
| **Severity** | HIGH — dashboards and alerts built on these metrics produce no-data panels and phantom alert state |
| **Affected areas** | `services/content-store/src/content_store/infrastructure/metrics/prometheus.py` (8 of 9 metrics), `services/nlp-pipeline/src/nlp_pipeline/infrastructure/metrics/prometheus.py` (all metrics), `services/rag-chat/src/rag_chat/infrastructure/metrics/prometheus.py` (all metrics) |
| **Root cause** | Metrics modules were created as copy-paste stubs during scaffolding. The counters/gauges/histograms are defined at module level and exported, but no use-case, consumer, or worker code in the service ever calls `.inc()`, `.set()`, or `.observe()` on them. The metric name appears correct in the module, but the metric is a dead symbol — never referenced outside the module. |
| **Symptom** | Prometheus returns the metric with value `0` at startup and it never changes. Dashboards built on these metrics appear to show a healthy flat line at 0, which looks like "no traffic" rather than "metric is broken". Alert rules fire `for: 5m` without matching real conditions. |
| **Fix** | For each dead metric, either: (a) find the correct use-case or consumer code that performs the action the metric is supposed to measure, and add a `metric.inc()` / `metric.observe()` call there; or (b) if the metric was added speculatively and no such code exists, remove the metric definition entirely. Never leave a metric defined but unincremented — it creates false confidence. |

### Prevention

When adding a Prometheus metric to a service, the metric definition and its first call site MUST be in the same commit. A metric with no call site is dead code. During code review, grep for each new metric name across the entire service to confirm at least one `.inc()`/`.set()`/`.observe()` call exists.

**Grep pattern** (find metrics defined but never called):
```bash
# For each metric name found in the metrics module, check for usage:
grep -rn "s5_articles_processed_total\|s5_processing_duration" services/content-store/src/ --include="*.py"
# Should return at least 2 lines: the definition AND a call site.
```

---

---

## BP-175 — Prometheus Scrape Target Uses Host-Mapped Port Instead of Container Port

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (observability audit) |
| **Severity** | HIGH — two services' metrics are permanently missing from all dashboards |
| **Affected areas** | `infra/prometheus/prometheus.yml` — `portfolio:8001` (correct: `portfolio:8000`) and `content-ingestion:8004` (correct: `content-ingestion:8000`) |
| **Root cause** | The Prometheus scrape config uses the host-side port mapping from `docker-compose.yml` (e.g., `8001:8000` → uses `8001`) instead of the container-internal port (`8000`). Within a Docker network, containers communicate on the container-internal port. The host-mapped port is only accessible from the Docker host, not from other containers. Prometheus (running as a container) cannot reach `portfolio:8001` because that port is only bound on the host interface. |
| **Symptom** | Prometheus shows `portfolio` and `content-ingestion` scrape targets as `DOWN` with `connection refused`. All panels for these services show no-data. Grafana "Service Overview" dashboard appears healthy for 8 services but blank for the other 2. |
| **Fix** | In `infra/prometheus/prometheus.yml`, change: `targets: ["portfolio:8001"]` → `targets: ["portfolio:8000"]` and `targets: ["content-ingestion:8004"]` → `targets: ["content-ingestion:8000"]`. The container-internal port is always the right-hand side of the `host:container` port mapping in docker-compose. When adding a new service, verify the `/metrics` path and the INTERNAL port from the service's `Dockerfile` `CMD` or `uvicorn` invocation. |

### Prevention

When adding a service to `prometheus.yml`, ALWAYS use the container-internal port (right side of `host_port:container_port` in docker-compose). Never use the host-mapped port. A simple way to verify: `docker compose exec prometheus wget -qO- http://<service_name>:<container_port>/metrics` — if this returns text, the port is correct.

---

---

## BP-176 — Alertmanager Receiver With No Notification Channels (Silent Alert Black Hole)

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (observability audit) |
| **Severity** | CRITICAL — all Prometheus alerts fire and are permanently discarded; no human is ever notified |
| **Affected areas** | `infra/alertmanager/alertmanager.yml` |
| **Root cause** | The Alertmanager configuration defines a `default` receiver with no `email_configs`, `slack_configs`, `webhook_configs`, `pagerduty_configs`, or any other notification integration. Prometheus correctly evaluates alert rules, transitions them to `FIRING`, and sends them to Alertmanager — but Alertmanager silently matches them to the empty default receiver and discards them. No log message is emitted by Alertmanager for discarded notifications. |
| **Symptom** | Alertmanager UI shows alerts in `FIRING` state. No email, Slack message, or page is ever sent. On-call engineers have no awareness that alerts are firing. The Grafana "Active Alerts" panel may show counts, but operators never receive actionable notifications. |
| **Fix** | Add at minimum one notification channel to `infra/alertmanager/alertmanager.yml`. For local development, wire to MailHog (already running in the `dev` profile): add `email_configs` with `to: "oncall@worldview.local"`, `from: "alertmanager@worldview.local"`, `smarthost: "mailhog:1025"`, `require_tls: false`. For production, add Slack webhook or PagerDuty integration. Verify by triggering a test alert via `amtool alert add` and confirming delivery. |

### Prevention

An Alertmanager receiver with no integration config is not a valid production configuration. It is equivalent to disabling alerting entirely. Any CI or deployment check must verify that at least one receiver has at least one notification config entry. Add the following to the deployment checklist: "Alertmanager has at least one receiver with a working notification channel (email/Slack/PagerDuty). Verify with `amtool config routes show`."

---

---

## BP-177 — `app = create_app()` at Module Level With uvicorn `--factory` (Double Prometheus Registration)

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (platform cold-start validation) |
| **Severity** | HIGH — service crashes at startup; no traffic served |
| **Affected areas** | FastAPI app factories used with uvicorn `--factory` |
| **Root cause** | A module-level `app = create_app()` call executes when the module is imported by uvicorn, registering Prometheus metrics into the global `CollectorRegistry`. uvicorn then calls `create_app()` a second time (as the factory function), which tries to register the same metrics again. If the `observability.metrics._global_registry_cache` is absent (old image) or the service name is identical, the second registration raises `ValueError: Duplicated timeseries in CollectorRegistry`. |
| **Symptom** | Service exits immediately on startup with `ValueError: Duplicated timeseries in CollectorRegistry: {'<svc>_requests_total', ...}`. Found in `alert/app.py:159`. |
| **Fix** | Remove the module-level `app = create_app()` call. uvicorn `--factory` handles the single instantiation. If module-level access is needed for testing, use `pytest` fixtures that call `create_app()` directly. |

### Prevention

Never add `app = create_app()` at module level in a FastAPI service that uses uvicorn `--factory`. Add to the service scaffold template and `.claude/review/checklists/REVIEW_CHECKLIST.md`: "FastAPI app.py: no module-level `app = create_app()` if CMD uses `--factory`."

---

---

## BP-269 — structlog OTel Context Not Injected — trace_id Missing from Logs

**Category**: Observability / Loki↔Tempo correlation
**Severity**: CRITICAL
**Affected areas**: `libs/observability/src/observability/logging.py`
**First seen**: 2026-04-28 (observability audit)

**Symptoms**:
- Grafana "Logs from trace" drilldown returns zero results
- Loki derivedFields `trace_id` regex matches nothing
- Loki logs have no `trace_id` or `span_id` fields despite OTel middleware being configured

**Root Cause**:
`configure_logging()` shared_processors list contained no processor that reads the active OTel span. Documentation and `docs/libs/observability.md` claimed `trace_id + span_id are injected into every log line by OTel middleware` — this was incorrect. The OTel middleware creates spans and propagates context in the ASGI scope, but structlog is a separate logging layer that does not automatically read OTel context.

**Fix Applied**:
Added `_inject_otel_trace_context` processor to `shared_processors` in `configure_logging()`:
```python
def _inject_otel_trace_context(logger, method, event_dict):
    from opentelemetry import trace
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict
```

**Prevention**:
- Always verify end-to-end log↔trace correlation after observability stack changes
- Test with: make a request, copy trace_id from Tempo, search Loki for it; if no results, the injection is broken
- `docs/libs/observability.md` updated to document the processor requirement

---

---

## BP-270 — Prometheus Regex s[1-9] Excludes Service S10

**Category**: Monitoring / alert configuration
**Severity**: MAJOR
**Affected areas**: `infra/prometheus/rules/alert-rules.yml`
**First seen**: 2026-04-28 (observability audit)

**Symptoms**:
- `OutboxBacklog` and `DeadLetterQueueNonEmpty` alerts never fire for S10 (alert delivery service)
- S10 outbox/DLQ completely unmonitored

**Root Cause**:
`{__name__=~"s[1-9]_outbox_pending_total"}` — the character class `[1-9]` matches a SINGLE digit 1–9. Service S10 has a two-digit service number; `s10_` is never matched.

**Fix Applied**:
Changed to `s[0-9]+_outbox_pending_total` — matches s1 through s99.

**Prevention**:
- Never use `[0-9]` or `[1-9]` alone when matching service numbers that could reach double digits
- Always use `[0-9]+` (one or more digits) or `\d+` in service name regex patterns

---

---

## BP-271 — histogram_quantile Without sum by (label, le) Returns Incorrect Percentiles

**Category**: Monitoring / Prometheus PromQL
**Severity**: MAJOR
**Affected areas**: `infra/grafana/dashboards/eodhd-health.json`
**First seen**: 2026-04-28 (observability audit)

**Symptoms**:
- EODHD latency dashboard shows wildly incorrect p50/p95 values
- Values may appear correct for one endpoint but be wrong for others

**Root Cause**:
`histogram_quantile(0.5, rate(s2_eodhd_request_duration_seconds_bucket[5m]))` — when `rate()` returns multiple series (one per `endpoint` label value), `histogram_quantile` without explicit aggregation picks an arbitrary series rather than merging histograms correctly. The correct form requires `sum by (relevant_label, le)` before `histogram_quantile` to merge the bucket series properly.

**Fix Applied**:
```promql
histogram_quantile(0.50, sum by (endpoint, le) (rate(s2_eodhd_request_duration_seconds_bucket[5m])))
```

**Prevention**:
- Always wrap histogram metric `rate()` with `sum by (<breakdown_labels>, le)` before passing to `histogram_quantile`
- The `le` label MUST be included in the `by` clause — without it the merge is incorrect
- Recording rules in `recording-rules.yml` already use the correct pattern; dashboard panels must follow the same rule

---

---

## BP-321 — Grafana Alloy Service Filter Omits New Container: Logs Silently Dropped

**Context**: `infra/alloy/config.alloy` uses a `loki.relabel` block with a `keep` rule that whitelists specific container names. New services added to the platform will have their logs silently dropped by Loki until explicitly added to this filter.

**Example**: `worldview-web` (frontend container) was not in the keep regex. All frontend access logs, startup messages, and warnings were forwarded to Loki's write endpoint but discarded at the relabeling stage.

**Symptoms**: `make monitoring` + Grafana shows all backend services but no frontend logs; `{service="worldview-web"}` query returns empty even with the container running.

### Root cause

`infra/alloy/config.alloy`:
```alloy
rule {
  source_labels = ["__meta_docker_container_name"]
  regex         = "/(portfolio|...|alert).*"   # worldview-web missing
  action        = "keep"
}
```

### Fix

Add the new service name to the alternation in the `keep` rule regex. After editing the config, restart the monitoring stack:
```bash
make monitoring-down && make monitoring
```

### Prevention

- When scaffolding a new service with `/scaffold-service` or `/scaffold-frontend`, immediately add the service's container name to the Alloy keep regex as part of the scaffold checklist.
- The second relabel rule auto-derives the `service` label from the container name (e.g., `worldview-web-1` → `service="worldview-web"`), so no other config changes are needed.


---

---
