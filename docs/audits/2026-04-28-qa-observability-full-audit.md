# QA Report: Full Observability Audit — Grafana / Prometheus / Loki / Alloy

**Date**: 2026-04-28 19:57 UTC
**Skill**: /qa (observability focus)
**Scope**: Full platform observability stack + gap analysis + design proposals
**Branch**: feat/content-ingestion-wave-a1
**Verdict**: FAIL — 3 BLOCKING, 13 CRITICAL, 24+ MAJOR unresolved gaps
**Report file**: docs/audits/2026-04-28-qa-observability-full-audit.md

---

## Executive Summary

Five specialist agents reviewed the complete observability stack (Prometheus, Grafana, Loki, Tempo, Alloy, AlertManager) and instrumentation across all 10 microservices, 6 shared libs, and the Next.js frontend. The infrastructure foundation is solid: all 10 services expose `/metrics`, structured logging via `structlog` is consistent, OpenTelemetry tracing is wired everywhere, and 8 Grafana dashboards plus 14 Prometheus alert rules are deployed.

However, three critical architectural invariants are broken: (1) `trace_id` is never injected into structlog logs despite the docs claiming it is — the Loki↔Tempo correlation link is completely non-functional; (2) every ML adapter (DeepInfra, Gemini, Anthropic, Cohere, Jina, GLiNER) has zero Prometheus instrumentation, making 100% of the ML pipeline invisible to monitoring; (3) Kafka consumer lag has no metric and no alert, meaning any consumer falling behind is undetectable until pipeline freshness visibly degrades for users. Additionally, two live secrets are committed to the repository (DeepInfra API key, RSA private key), and alert notifications route exclusively to MailHog (a dev trap) — the team would never see a production alert.

The platform is **not production-ready for observability** in its current state. Six BLOCKING/CRITICAL issues need to be resolved before any public deployment. The report also provides complete designs for: a 5-layer Grafana dashboard hierarchy, SLO/error-budget framework, synthetic monitoring system, canary release architecture, and error escalation ladder.

---

## Multi-Agent Review Summary

| Agent | Primary Focus | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|--------------|----------|----------|-------|-------|-----|
| QA/Infrastructure | Prometheus config, alert rules, dashboards | 3 | 5 | 9 | 6 | 0 |
| Security | Secrets, access control, PII leakage | 0 | 4 | 10 | 4 | 2 |
| Data Platform | ML metrics, Kafka lag, DB pools, workers | 3 | 4 | 10 | 3 | 0 |
| Distributed Systems | Error capture, failure detection, synthetic monitoring | 0 | 4 | 8 | 3 | 1 |
| Architecture | Trace correlation, SLO framework, canary design | 0 | 3 | 9 | 3 | 1 |
| **Consolidated (deduped)** | — | **3** | **13** | **24** | **14** | **3** |

### Cross-Agent HIGH-Confidence Signals (Flagged by 2+ Agents Independently)

| Finding | Agents | Severity |
|---------|--------|----------|
| ML API instrumentation gap (all adapters) | QA, Data Platform, Architecture | BLOCKING |
| Kafka consumer lag — no metric, no alert | QA, Data Platform, Distributed Systems, Architecture | BLOCKING |
| tenant_id as Prometheus label (cardinality + PII) | QA, Security | CRITICAL |
| No infrastructure scrape targets (Postgres, Kafka broker, MinIO, Valkey) | QA, Architecture | MAJOR |
| HighP95Latency fires constantly on rag-chat (alert fatigue) | QA, Distributed Systems | MAJOR |
| Alert routing only to MailHog | Distributed Systems, Architecture | CRITICAL |
| trace_id never reaches Loki (broken correlation) | Architecture, QA (implicit via derivedFields) | CRITICAL |
| No unhandled exception handler in 8/10 services | Distributed Systems, QA | CRITICAL |
| s[1-9] regex excludes S10 from outbox/DLQ alerts | QA, Data Platform | MAJOR |

---

## Consolidated Findings — Full List

### BLOCKING Issues

---

#### Finding F-001: Zero ML API Instrumentation
- **Severity**: BLOCKING
- **Category**: metrics-gap
- **Confidence**: HIGH
- **Flagged by**: QA/Infrastructure, Data Platform, Architecture
- **Files**: `libs/ml-clients/src/ml_clients/adapters/deepinfra_embedding.py`, `deepinfra_llm.py`, `anthropic_extraction.py`, `gemini_extraction.py`, `gemini_description.py`, `cohere_rerank.py`, `jina_embedding.py`, `gliner_http.py`
- **Issue**: Every external ML API adapter — DeepInfra (embedding + LLM), Anthropic, Gemini, Cohere, Jina, and the local GLiNER server — has zero Prometheus instrumentation. No latency histogram, no error counter, no token count, no cost estimation exported to metrics. The `LlmUsageLogProtocol` DB-log infrastructure exists and is partially wired but never feeds Prometheus. Additionally, `GeminiDescriptionAdapter` always passes `latency_ms=0` to its usage logger (documented in a comment as intentional but incorrect).
- **Suggestion**: Create `libs/observability/src/observability/ml_metrics.py` with shared metric definitions (`ml_api_requests_total`, `ml_api_latency_seconds`, `ml_api_tokens_in_total`, `ml_api_tokens_out_total`, `ml_api_estimated_cost_usd_total`). Add a `record_ml_call()` helper. Wrap every adapter's API call. This is the highest-leverage observability gap — one shared helper covers all 8 adapters.
- **Auto-fixable**: NO

---

#### Finding F-002: Kafka Consumer Lag — No Metric, No Alert
- **Severity**: BLOCKING
- **Category**: metrics-gap / alert-gap
- **Confidence**: HIGH
- **Flagged by**: QA/Infrastructure, Data Platform, Distributed Systems, Architecture
- **Files**: `libs/messaging/src/messaging/kafka/consumer/base.py`, `infra/prometheus/rules/alert-rules.yml`, `infra/prometheus/prometheus.yml`
- **Issue**: `BaseKafkaConsumer` has zero consumer lag instrumentation. The platform has 20+ Kafka consumer processes (S5, S6, S7, S8, S9, S10). The only Kafka signals are application-side throughput counters (`kafka_messages_consumed_total`). There is no `kafka_consumer_lag` gauge, no JMX exporter, no `kafka-exporter`. A consumer falling behind the producer head by hours is invisible — `job_topic:kafka_consumed:rate5m` going to zero is the only proxy signal, and it cannot distinguish one stalled consumer from a service-wide issue.
- **Suggestion**: Two complementary approaches: (A) Add `kafka-exporter` to docker-compose for true broker-side lag metrics (`kafka_consumergroup_lag`). (B) In `BaseKafkaConsumer.run()`, after each commit, call `self._consumer.get_watermark_offsets(tp)` and update a `Gauge("kafka_consumer_lag_messages", ..., ["topic", "partition", "consumer_group"])`. Add alert: `kafka_consumer_lag_messages > 10000 for 5m → warning`. Add `KafkaConsumerSilent` alert: `job_topic:kafka_consumed:rate5m == 0 and on(job) up == 1 for 10m → warning`.
- **Auto-fixable**: NO

---

#### Finding F-003: Kafka Consumer Task Crash Undetected — Silently Dies
- **Severity**: BLOCKING
- **Category**: error-capture / failure-detection
- **Confidence**: HIGH
- **Flagged by**: Distributed Systems, Architecture
- **Files**: All `services/*/src/*/infrastructure/messaging/consumers/*_consumer_main.py`
- **Issue**: When `BaseKafkaConsumer.run()` exits due to a fatal exception (DB connection failure during `get_unit_of_work()`, Kafka broker disconnect, etc.), the calling code does `asyncio.create_task(consumer.run())` then blocks on `stop_event.wait()`. The task failure is stored in the task future but never awaited, never observed. The consumer silently stops processing. Docker's `on-failure` restart kicks in only after the process exits — but the main coroutine never observes the failed task and doesn't call `sys.exit(1)`. Detection: zero until cAdvisor/healthcheck fires (30-60 second blind spot, potentially longer).
- **Suggestion**: In every `*_consumer_main.py`, add a `done_callback` to the consumer task:
  ```python
  def _on_consumer_done(task: asyncio.Task) -> None:
      if not task.cancelled() and (exc := task.exception()):
          log.error("consumer_task_fatal", error=str(exc), exc_info=exc)
          sys.exit(1)  # triggers Docker restart
  consumer_task.add_done_callback(_on_consumer_done)
  ```
  Also add `worker_errors_total: Counter` to `ServiceMetrics` and increment it on crash.
- **Auto-fixable**: YES (mechanical pattern, ~5 files)

---

### CRITICAL Issues

---

#### Finding F-004: Live DeepInfra API Key Committed to Repo
- **Severity**: CRITICAL
- **Category**: security-secrets
- **Confidence**: HIGH
- **Flagged by**: Security
- **File**: `services/nlp-pipeline/configs/docker.env`
- **Issue**: The live DeepInfra API key (`xVi3qIVR8yPnu7DnP36GdFs2brm9GivI`) appears four times in committed config files. Comment says "worldview-gitops is PRIVATE — secrets are safe here" — this is security by obscurity. Git history permanently retains keys even after rotation. A private repo leak, supply-chain compromise, or accidental fork exposes this key.
- **Suggestion**: Rotate the key immediately. Replace all values with `<set-via-fetch-secrets>`. Add `git-secrets` or `truffleHog` as a pre-commit hook. Use `scripts/fetch-secrets.sh` to inject at deploy time.
- **Auto-fixable**: NO (key rotation required)

---

#### Finding F-005: RSA Private Key Committed to Repo
- **Severity**: CRITICAL
- **Category**: security-secrets
- **Confidence**: HIGH
- **Flagged by**: Security
- **File**: `services/api-gateway/configs/docker.env:55-56`
- **Issue**: Full PEM-encoded RSA-2048 private key used to sign internal JWTs is in version control. Any party with repo access can forge internal JWTs for any `user_id`/`tenant_id`, gaining full access to all backend services and bypassing authentication entirely.
- **Suggestion**: Move the dev keypair to `.env.local` (in `.gitignore`). Document that `scripts/setup-dev.sh` generates a fresh keypair per developer. Add a `git-secrets` pattern for PEM private-key headers (the `BEGIN ... PRIVATE KEY` line) — written here with an ellipsis so this audit doc does not itself trip the `detect-private-key` hook.
- **Auto-fixable**: NO

---

#### Finding F-006: trace_id Never Injected Into Structlog Logs (Broken Correlation)
- **Severity**: CRITICAL
- **Category**: arch-gap
- **Confidence**: HIGH
- **Flagged by**: Architecture, QA (implicit via derivedFields config referencing non-existent field)
- **File**: `libs/observability/src/observability/logging.py`
- **Issue**: `configure_logging()` shared_processors list contains `merge_contextvars`, `add_log_level`, `TimeStamper`, `StackInfoRenderer`, `format_exc_info` — no span-extraction processor. There is no call to `opentelemetry.trace.get_current_span()` anywhere in the observability lib. The Grafana Loki datasource has `derivedFields` configured to extract `trace_id` from logs and link to Tempo — but `trace_id` never appears in any log line. The entire log↔trace drilldown is non-functional despite being documented as working.
- **Suggestion**: Add an OTel context processor to `configure_logging()`:
  ```python
  def _inject_otel_context(logger, method, event_dict):
      from opentelemetry import trace
      ctx = trace.get_current_span().get_span_context()
      if ctx.is_valid:
          event_dict["trace_id"] = format(ctx.trace_id, "032x")
          event_dict["span_id"] = format(ctx.span_id, "016x")
      return event_dict
  ```
  Insert before the renderer in `shared_processors`. This is a ~10-line fix with large impact: every service immediately gets trace↔log correlation.
- **Auto-fixable**: YES

---

#### Finding F-007: No SLO / Error Budget Framework
- **Severity**: CRITICAL
- **Category**: slo-gap
- **Confidence**: HIGH
- **Flagged by**: Architecture
- **File**: `infra/prometheus/rules/` (absent)
- **Issue**: Zero SLO recording rules exist. `docs/MASTER_PLAN.md` §1 declares "99.5% uptime read APIs" as a non-functional requirement, but there are no Prometheus recording rules measuring SLIs, no error budget gauges, and no burn-rate alerts. The current threshold alerts (`HighErrorRate`, `HighP95Latency`) are symptom signals, not SLO budget instruments. You cannot answer "how much reliability budget remains this month?" or "are we burning budget faster than expected?"
- **Suggestion**: See full SLO Framework section at end of report for complete PromQL definitions for 5 SLOs (API availability, API latency, content freshness, alert delivery, portfolio sync) plus burn-rate alerts.
- **Auto-fixable**: NO

---

#### Finding F-008: Unhandled Exception Handler Missing from 8/10 Services
- **Severity**: CRITICAL
- **Category**: error-capture
- **Confidence**: HIGH
- **Flagged by**: Distributed Systems, QA
- **Files**: `services/alert/app.py`, `services/knowledge-graph/app.py`, `services/nlp-pipeline/app.py`, `services/content-store/app.py`, `services/rag-chat/app.py`, `services/market-data/app.py`, `services/market-ingestion/app.py`, `services/api-gateway/app.py`
- **Issue**: Only `portfolio` and `content-ingestion` have `app.add_exception_handler(Exception, unhandled_exception_handler)` registered. When an unhandled exception reaches FastAPI in the other 8 services, uvicorn logs it to stderr as an unstructured traceback — it never enters structlog, never gets `request_id`/`tenant_id`/`user_id`/`trace_id` context, and cannot be correlated to a specific request in Loki.
- **Suggestion**: Move `unhandled_exception_handler` from `portfolio` to `libs/observability/src/observability/error_capture.py`. Call `add_exception_handlers(app)` from every service's `create_app()`. Add user context binding:
  ```python
  user_id=getattr(request.state, "user_id", None),
  tenant_id=getattr(request.state, "tenant_id", None),
  ```
- **Auto-fixable**: YES (mechanical, ~8 files)

---

#### Finding F-009: Alert Notifications Route Only to MailHog — Team Never Sees Alerts
- **Severity**: CRITICAL
- **Category**: alert-routing
- **Confidence**: HIGH
- **Flagged by**: Distributed Systems, Architecture
- **File**: `infra/alertmanager/alertmanager.yml`
- **Issue**: ALL alerts — including `ServiceDown (critical)` — route only to email via `smtp_smarthost: "mailhog:1025"`. MailHog is a local dev SMTP trap; nobody receives these emails. In any production or demo deployment, `ServiceDown` would fire and the team would have zero notification. Two receivers exist (`default`, `critical`) and both use `email_configs` only.
- **Suggestion**: Add Slack webhook receiver for critical alerts and PagerDuty for ServiceDown. See complete AlertManager config in design section.
- **Auto-fixable**: NO (requires real credentials)

---

#### Finding F-010: Loki Auth Disabled + All-Interface Binding
- **Severity**: CRITICAL
- **Category**: security-config
- **Confidence**: HIGH
- **Flagged by**: Security
- **File**: `infra/loki/loki-config.yml`, `infra/compose/docker-compose.yml`
- **Issue**: Loki is configured with `auth_enabled: false` and port 3100 is published on all interfaces (no `127.0.0.1:` prefix). Any host that can reach the machine can push arbitrary log entries to Loki (inject fabricated audit logs, cover tracks) and read all existing logs including any PII or auth events from all services.
- **Suggestion**: For dev: bind to `127.0.0.1:3100:3100`. For prod: enable `auth_enabled: true` with Loki multi-tenancy. Add network policy restricting direct Loki push to only Alloy container IP.
- **Auto-fixable**: YES (add `127.0.0.1:` prefix to port binding)

---

#### Finding F-011: No Loki Retention Policy — Disk Exhaustion Risk
- **Severity**: CRITICAL
- **Category**: config-error
- **Confidence**: HIGH
- **Flagged by**: QA/Infrastructure
- **File**: `infra/loki/loki-config.yml`
- **Issue**: `limits_config` has `reject_old_samples_max_age: 168h` (ingest acceptance window) but no `retention_period` in the compactor. Loki retains logs forever, bounded only by disk space. On a developer machine or small VPS this will cause disk exhaustion without warning.
- **Suggestion**:
  ```yaml
  compactor:
    working_directory: /loki/compactor
    retention_enabled: true
    retention_delete_delay: 2h
  limits_config:
    retention_period: 720h  # 30 days
    reject_old_samples: true
    reject_old_samples_max_age: 168h
  ```
- **Auto-fixable**: YES

---

#### Finding F-012: tenant_id as Prometheus Label — Cardinality Risk + PII Leakage
- **Severity**: CRITICAL
- **Category**: security-tenant-isolation / cardinality-risk
- **Confidence**: HIGH
- **Flagged by**: QA/Infrastructure, Security
- **File**: `services/rag-chat/src/rag_chat/infrastructure/metrics/prometheus.py:13-17,64-68`
- **Issue**: `rag_chat_queries_total` and `rag_thread_count` use `tenant_id` as a Prometheus label. (1) Cardinality: one time series per tenant; at 1000+ tenants this creates memory pressure. (2) PII/isolation: any user with Prometheus access can enumerate all tenant IDs, see per-tenant query volumes and activity patterns — violating multi-tenancy isolation.
- **Suggestion**: Remove `tenant_id` from both metrics. Per-tenant analytics belong in the application database (queryable via SQL with row-level security). If per-tenant Grafana visibility is needed, use a Loki LogQL query against the structured logs (filtered by `tenant_id` from the log fields) rather than a Prometheus metric.
- **Auto-fixable**: YES (remove label from metric definition + call sites)

---

#### Finding F-013: Tempo metrics_generator Not Configured
- **Severity**: CRITICAL
- **Category**: arch-gap
- **Confidence**: HIGH
- **Flagged by**: Architecture
- **File**: `infra/tempo/tempo.yml`
- **Issue**: `metrics_generator:` block is present but has no `processors:` list. Without `span-metrics` and `service-graphs` processors enabled, Tempo does not generate span-derived RED metrics or service dependency graphs. The Grafana Tempo datasource has `nodeGraph: enabled` but there is no graph data. The span-metrics would allow validating that Prometheus-scraped error rates match trace-derived error rates — a critical consistency check.
- **Suggestion**:
  ```yaml
  metrics_generator:
    processors:
      - span-metrics
      - service-graphs
    storage:
      path: /var/tempo/generator/wal
  ```
- **Auto-fixable**: YES (config change only)

---

#### Finding F-014: No Scrape Targets for Observability Infrastructure Itself
- **Severity**: CRITICAL
- **Category**: alert-gap / config-error
- **Confidence**: HIGH
- **Flagged by**: QA/Infrastructure
- **File**: `infra/prometheus/prometheus.yml`
- **Issue**: `prometheus.yml` has 10 scrape jobs — all for microservices S1–S10. None of Prometheus, Grafana, Loki, Tempo, Alloy, AlertManager, Kafka broker, PostgreSQL, MinIO, or Valkey are scrape targets. If Loki goes down, log collection silently stops — no alert fires. If Tempo goes down, all trace ingestion drops — no alert fires.
- **Suggestion**: Add scrape jobs for `loki:3100/metrics`, `tempo:3200/metrics`, `alertmanager:9093/metrics`. These expose native health metrics and automatically trigger `ServiceDown` when they go `up == 0`. For infrastructure: add `postgres-exporter`, `kafka-exporter`, `redis_exporter`, and MinIO's native `/minio/v2/metrics/cluster` endpoint.
- **Auto-fixable**: YES for observability components; NO for infra (requires new containers)

---

#### Finding F-015: Fixed Admin Tokens Committed to Repository
- **Severity**: CRITICAL
- **Category**: security-secrets
- **Confidence**: HIGH
- **Flagged by**: Security
- **Files**: Multiple `services/*/configs/docker.env` files
- **Issue**: Admin tokens (`test-admin-token`, `e2e-admin-token`) providing access to admin-only endpoints (DLQ drain, outbox inspection, cost APIs) across 5 services are committed in plaintext. Unlike the API key in F-004, these tokens have no expiry and provide service-level admin access without JWT validation.
- **Suggestion**: Replace with `<set-via-fetch-secrets>` placeholders. Generate cryptographically random 32-byte tokens per service at deploy time. Do not share tokens across services.
- **Auto-fixable**: NO

---

#### Finding F-016: No Valkey Availability Alert
- **Severity**: CRITICAL
- **Category**: alert-gap
- **Confidence**: HIGH
- **Flagged by**: QA/Infrastructure, Data Platform
- **File**: `infra/prometheus/rules/alert-rules.yml`, `infra/compose/docker-compose.yml`
- **Issue**: Valkey underpins LSH dedup index (S5), EODHD response cache (S2), chat cache (S8), rate limiter (S9), WebSocket token validation (S10), brokerage connection state (S1), and GLiNER cost tracking (S7). `s5_lsh_index_failures_total` is the only metric tracking Valkey-related failures. There is no `redis_exporter` scrape target, no `redis_up` metric, no alert for Valkey being unavailable. A Valkey outage cascades silently into degraded behavior across all 10 services.
- **Suggestion**: Add `redis_exporter` sidecar to docker-compose and a `ValkeyDown: up{job="valkey"} == 0 for 1m → critical` alert. Also add `ValkeyClient` metrics to `libs/messaging/src/messaging/valkey/client.py` (see F-023).
- **Auto-fixable**: NO (requires new container)

---

### MAJOR Issues

---

#### Finding F-017: s[1-9] Regex Excludes S10 from Outbox/DLQ Alerts
- **Severity**: MAJOR
- **Category**: config-error (alert rule bug)
- **Confidence**: HIGH
- **Flagged by**: QA/Infrastructure
- **File**: `infra/prometheus/rules/alert-rules.yml:65,72`
- **Issue**: `OutboxBacklog` and `DeadLetterQueueNonEmpty` alerts use `{__name__=~"s[1-9]_outbox_pending_total"}`. `[1-9]` matches one digit only — `s10_` is excluded. S10 (alert delivery service) outbox and DLQ are silently unmonitored.
- **Suggestion**: Change to `s[0-9]+_outbox_pending_total` (matches s1 through s99).
- **Auto-fixable**: YES

---

#### Finding F-018: HighP95Latency Alert Generates Constant Alert Fatigue on RAG-Chat
- **Severity**: MAJOR
- **Category**: config-error (alert rule)
- **Confidence**: HIGH
- **Flagged by**: QA/Infrastructure, Distributed Systems
- **File**: `infra/prometheus/rules/alert-rules.yml:49`
- **Issue**: `HighP95Latency: job:http_duration_p95:rate5m > 0.5` applies to ALL services including `rag-chat`. Chat completion via DeepSeek R1 32B takes 5–30 seconds — well above 500ms. This alert fires constantly for S8, causing engineers to ignore it entirely (alert fatigue), defeating its purpose for the other 9 services.
- **Suggestion**:
  ```yaml
  - alert: HighP95Latency
    expr: job:http_duration_p95:rate5m{job!="rag-chat"} > 0.5
    for: 5m
    labels:
      severity: warning
  - alert: RagChatHighP95Latency
    expr: job:http_duration_p95:rate5m{job="rag-chat"} > 30
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "RAG-chat p95 >30s — LLM call may be timing out"
  ```
- **Auto-fixable**: YES

---

#### Finding F-019: No Postgres, Kafka Broker, or MinIO Observability
- **Severity**: MAJOR
- **Category**: observability-gap
- **Confidence**: HIGH
- **Flagged by**: QA/Infrastructure, Architecture
- **File**: `infra/prometheus/prometheus.yml`
- **Issue**: All 10 services depend on PostgreSQL (9 separate databases). The Kafka broker is the event backbone for the entire pipeline. MinIO holds all Bronze/Silver layer article content. None have scrape targets. PostgreSQL connection pool exhaustion, Kafka under-replicated partitions, and MinIO disk exhaustion are all undetectable until services fail.
- **Suggestion**: Add `postgres_exporter` (`prometheuscommunity/postgres-exporter`), `kafka-exporter` or JMX exporter, MinIO native metrics (`/minio/v2/metrics/cluster`). Add alerts: `PostgresConnectionPoolNearExhaustion`, `KafkaUnderReplicatedPartitions`, `MinIOStorageFull`.
- **Auto-fixable**: NO (requires new docker-compose services)

---

#### Finding F-020: No WebSocket Active Connections Gauge (S10 Alert Service)
- **Severity**: MAJOR
- **Category**: observability-gap
- **Confidence**: HIGH
- **Flagged by**: Distributed Systems, QA
- **File**: `services/alert/src/alert/infrastructure/websocket/manager.py`
- **Issue**: `ConnectionManager.active_count` property exists in code but is never exported to Prometheus. No alert fires if all WebSocket connections drop. Users could be silently missing critical financial alerts with no operational visibility.
- **Suggestion**: Add `s10_websocket_active_connections = Gauge(...)`. Increment in `connect()`, decrement in `disconnect()`. Alert: `s10_websocket_active_connections == 0 AND s10_alerts_pending_total > 0 for 10m → warning`.
- **Auto-fixable**: YES

---

#### Finding F-021: No KG Worker Crash Alert (Metric Exists, Alert Missing)
- **Severity**: MAJOR
- **Category**: alert-gap
- **Confidence**: HIGH
- **Flagged by**: QA/Infrastructure
- **File**: `infra/prometheus/rules/alert-rules.yml`
- **Issue**: `s7_worker_crash_total[worker]` exists in S7 but no alert rule references it. A crashed APScheduler worker (confidence recompute, summary generation, embedding refresh, AGE sync, economic events, macro indicators) silently stops enriching the knowledge graph.
- **Suggestion**:
  ```yaml
  - alert: KGWorkerCrash
    expr: rate(s7_worker_crash_total[5m]) > 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Knowledge graph worker {{ $labels.worker }} is crashing"
  ```
- **Auto-fixable**: YES

---

#### Finding F-022: ML Worker Token/Latency Fields Always Zero
- **Severity**: MAJOR
- **Category**: ml-gap
- **Confidence**: HIGH
- **Flagged by**: Data Platform
- **Files**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/unresolved_resolution_worker.py`, `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/`, `libs/ml-clients/src/ml_clients/adapters/gemini_description.py`
- **Issue**: Several workers call `usage_logger.log()` but pass `tokens_in=0, tokens_out=0, latency_ms=0` literally. `GeminiDescriptionAdapter` has a comment documenting this as intentional: `"GeminiDescriptionAdapter does not track wall-clock time"`. `UnresolvedResolutionWorker` has zeroed fields on all 4 paths (both providers, success + failure). The llm_usage_log DB table exists but is useless for cost analysis.
- **Suggestion**: Add `t0 = time.perf_counter()` before every LLM API call. Read `response.eval_count` / `response.usage_metadata.prompt_token_count` from the actual API response after the call. Pass real values to `usage_logger.log()`.
- **Auto-fixable**: NO (requires per-worker review)

---

#### Finding F-023: No SQLAlchemy Pool Metrics or ValkeyClient Metrics
- **Severity**: MAJOR
- **Category**: observability-gap
- **Confidence**: HIGH
- **Flagged by**: Data Platform, Architecture
- **Files**: `services/*/src/*/infrastructure/db/session.py`, `libs/messaging/src/messaging/valkey/client.py`
- **Issue**: All session factories use `create_async_engine()` with `pool_size` and `max_overflow` settings but zero pool event listeners. No way to detect connection pool exhaustion (`TimeoutError` stalls under load). `ValkeyClient` similarly has no metrics for hit/miss ratio, command latency, or pool exhaustion.
- **Suggestion**: Register SQLAlchemy pool events at engine creation:
  ```python
  @event.listens_for(engine.sync_engine, "checkout")
  def on_checkout(dbapi_con, con_record, con_proxy):
      db_pool_checkedout.labels(service=SERVICE_NAME).inc()
  ```
  Wrap ValkeyClient methods with `time.perf_counter()` and `valkey_command_latency_seconds` histogram.
- **Auto-fixable**: NO

---

#### Finding F-024: No Log Scrubbing in Alloy or structlog Chain
- **Severity**: MAJOR
- **Category**: security-pii
- **Confidence**: HIGH
- **Flagged by**: Security, Architecture
- **Files**: `infra/alloy/config.alloy`, `libs/observability/src/observability/logging.py`
- **Issue**: All container logs are shipped verbatim to Loki with zero scrubbing. User emails appear in `login_success` log events (`services/api-gateway/src/api_gateway/routes/auth.py:333`). Valkey connection URLs (potentially including passwords) are logged at startup. `httpx.HTTPStatusError` exceptions in ML adapters include the full request URL and response body in `str(exc)`. No structlog PII processor exists.
- **Suggestion**: Add a structlog `_scrub_pii_processor` in `libs/observability/src/observability/logging.py` that redacts known-sensitive keys (`email`, `password`, `token`, `api_key`, `authorization`). Add an Alloy `loki.process` stage with regex-based redaction for URL passwords, API keys, and Bearer tokens.
- **Auto-fixable**: YES (for structlog processor); NO (for Alloy pipeline redesign)

---

#### Finding F-025: Monitoring Ports Exposed on All Network Interfaces
- **Severity**: MAJOR
- **Category**: security-config
- **Confidence**: HIGH
- **Flagged by**: Security
- **File**: `infra/compose/docker-compose.yml`
- **Issue**: Prometheus (:9090), Grafana (:3000), Loki (:3100), Tempo (:3200, :4317, :4318), Alloy (:12345), AlertManager (:9093) are all published on `0.0.0.0` rather than `127.0.0.1`. Data-plane services (Postgres, Kafka, Valkey, MinIO) correctly use `127.0.0.1:` bindings — the monitoring stack does not.
- **Suggestion**: Add `127.0.0.1:` prefix to all monitoring port bindings. In production, route Grafana through a reverse proxy with IP allowlisting. Never expose Prometheus or Loki directly to the internet.
- **Auto-fixable**: YES

---

#### Finding F-026: Grafana Default Password "admin"
- **Severity**: MAJOR
- **Category**: security-config
- **Confidence**: HIGH
- **Flagged by**: Security
- **File**: `infra/compose/docker-compose.yml:526`
- **Issue**: `GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-admin}`. If `GRAFANA_ADMIN_PASSWORD` is unset, Grafana starts with `admin`/`admin`. Anyone who reaches port 3000 can log in as admin, modify alert rules, and add datasources.
- **Suggestion**: Remove the `:-admin` default. Document that `scripts/setup-dev.sh` must set this variable.
- **Auto-fixable**: YES

---

#### Finding F-027: histogram_quantile Bug in eodhd-health.json
- **Severity**: MAJOR
- **Category**: dashboard-gap
- **Confidence**: HIGH
- **Flagged by**: QA/Infrastructure
- **File**: `infra/grafana/dashboards/eodhd-health.json:298-310`
- **Issue**: EODHD latency panels use `histogram_quantile(0.5, rate(s2_eodhd_request_duration_seconds_bucket[5m]))` — missing the required `sum by (endpoint, le)` aggregation before `histogram_quantile`. When `rate()` returns multiple series (one per `endpoint` label), `histogram_quantile` without explicit aggregation picks an arbitrary one, producing meaningless latency values.
- **Suggestion**:
  ```promql
  histogram_quantile(0.50, sum by (endpoint, le) (rate(s2_eodhd_request_duration_seconds_bucket[5m])))
  histogram_quantile(0.95, sum by (endpoint, le) (rate(s2_eodhd_request_duration_seconds_bucket[5m])))
  ```
- **Auto-fixable**: YES

---

#### Finding F-028: External API Errors Not Counted in Metrics
- **Severity**: MAJOR
- **Category**: observability-gap
- **Confidence**: HIGH
- **Flagged by**: Distributed Systems, Data Platform
- **Files**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/article_relevance_scoring_worker.py:107`, multiple adapter files
- **Issue**: When DeepInfra/Gemini/Anthropic returns 429, 500, or a timeout, workers log a structured warning (e.g., `relevance_scoring_provider_unavailable`) but increment zero Prometheus counters. Alerting on external API degradation is impossible.
- **Suggestion**: Add `external_api_errors_total: Counter[api_name, error_type]` to `ServiceMetrics`. Increment on every 429/5xx/timeout. Alert: `rate(external_api_errors_total[5m]) > 0.5 for 2m → warning`. Alert: all-failure for 2m → critical.
- **Auto-fixable**: YES (after F-001 metrics layer is added)

---

#### Finding F-029: No Auth Failure Rate Alert
- **Severity**: MAJOR
- **Category**: alert-gap
- **Confidence**: MEDIUM
- **Flagged by**: QA/Infrastructure
- **File**: `infra/prometheus/rules/alert-rules.yml`
- **Issue**: No alert exists for sustained 401/403 responses from the API Gateway. Sustained auth failures indicate either a broken client configuration or an active attack.
- **Suggestion**:
  ```yaml
  - alert: HighAuthFailureRate
    expr: >
      sum(rate(api_gateway_requests_total{status=~"401|403"}[5m]))
      / sum(rate(api_gateway_requests_total[5m])) > 0.05
    for: 3m
    labels:
      severity: warning
  ```
- **Auto-fixable**: YES

---

#### Finding F-030: Alloy Docker Label Mismatch (Log Label ≠ Prometheus Job Label)
- **Severity**: MAJOR
- **Category**: arch-gap
- **Confidence**: HIGH
- **Flagged by**: Architecture
- **File**: `infra/alloy/config.alloy`
- **Issue**: Alloy's relabel rule strips the leading `/` from `__meta_docker_container_name` using regex `/(.*)`— producing `worldview-portfolio-1`, not `portfolio`. Prometheus uses `job="portfolio"`. The Loki `service` label and Prometheus `job` label never match, making cross-pillar drilldown (alert → logs) require manual label translation.
- **Suggestion**:
  ```alloy
  rule {
    source_labels = ["__meta_docker_container_name"]
    target_label  = "service"
    regex         = "/worldview-(.*)-\\d+"
    replacement   = "$1"
  }
  ```
- **Auto-fixable**: YES

---

#### Finding F-031: Alloy Collects All Docker Containers (Infrastructure Noise in Loki)
- **Severity**: MAJOR
- **Category**: config-error
- **Confidence**: MEDIUM
- **Flagged by**: QA/Infrastructure
- **File**: `infra/alloy/config.alloy`
- **Issue**: `loki.source.docker` collects ALL containers including Kafka, Zookeeper, PostgreSQL, MinIO — producing noisy checkpoint/re-election/access log messages in Loki that flood the platform logs and make error detection harder.
- **Suggestion**: Add a `keep` action filtering to worldview service containers only:
  ```alloy
  rule {
    source_labels = ["__meta_docker_container_name"]
    regex = "/(portfolio|market-ingestion|market-data|content-ingestion|content-store|api-gateway|nlp-pipeline|knowledge-graph|rag-chat|alert).*"
    action = "keep"
  }
  ```
- **Auto-fixable**: YES

---

#### Finding F-032: No Dashboard for RAG-Chat or Alert Service
- **Severity**: MAJOR
- **Category**: dashboard-gap
- **Confidence**: HIGH
- **Flagged by**: QA/Infrastructure
- **Issue**: S8 RAG-Chat has 12 custom metrics (query latency, cache hits, first-token, provider fallback, retrieval items, contradiction surfacing, injection blocking, etc.). S10 Alert has 6 custom metrics (WebSocket pushes, fan-out count, pending gauge, by-severity breakdown). Neither service has any Grafana dashboard. These are two of the most operationally critical services.
- **Suggestion**: Create `rag-chat.json` and `alert-service.json` dashboards. See Dashboard Hierarchy section for panel specifications.
- **Auto-fixable**: NO

---

#### Finding F-033: s7_insider_transactions ticker Label — Cardinality Time Bomb
- **Severity**: MAJOR
- **Category**: cardinality-risk
- **Confidence**: HIGH
- **Flagged by**: QA/Infrastructure
- **File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/metrics/prometheus.py`
- **Issue**: `s7_insider_transactions_relations_total` has a `ticker` label. EODHD covers 60,000+ tickers — this creates one time series per ticker, potentially 60,000 Prometheus time series from a single metric. This will cause significant Prometheus memory pressure.
- **Suggestion**: Remove the `ticker` label. The total count without ticker breakdown is sufficient for operational monitoring. Per-ticker analytics belong in the database.
- **Auto-fixable**: YES

---

#### Finding F-034: Domain Exceptions Leaked to API Clients
- **Severity**: MAJOR
- **Category**: security-pii
- **Confidence**: HIGH
- **Flagged by**: Security
- **Files**: `services/knowledge-graph/src/knowledge_graph/app.py:128`, `services/portfolio/src/portfolio/api/internal.py:109`
- **Issue**: Exception handlers use `detail=str(exc)` which can expose internal data structure details, entity names, relationship types, and entity IDs to API clients.
- **Suggestion**: Map domain errors to fixed, human-readable messages. Log full `str(exc)` server-side only with `logger.warning("entity_not_found", exc_info=exc)`. Never pass `str(exc)` to HTTP response `detail`.
- **Auto-fixable**: YES

---

#### Finding F-035: Worker Task Loops Not Crash-Protected (Content Ingestion, Market Ingestion)
- **Severity**: MAJOR
- **Category**: worker-crash
- **Confidence**: HIGH
- **Flagged by**: Distributed Systems
- **Files**: `services/content-ingestion/src/content_ingestion/infrastructure/workers/worker.py:135`, `services/market-ingestion/src/market_ingestion/infrastructure/workers/`
- **Issue**: `WorkerProcess.run()` outer `while` loop has no `try/except Exception` guard. If `asyncio.gather` raises (cancelled from external signal race) or `_claim_batch()` raises an uncaught exception, the `while` exits and the worker silently stops processing. No counter, no ERROR log, no restart.
- **Suggestion**: Wrap `while` body in `try/except Exception` that logs at ERROR level, increments `worker_errors_total`, sleeps briefly (backoff), and continues. Only exit on `self._stop_event.is_set()`.
- **Auto-fixable**: YES

---

#### Finding F-036: AlertManager Missing ServiceDown Inhibit Rule (Alert Flood)
- **Severity**: MINOR
- **Category**: config-error
- **Confidence**: HIGH
- **Flagged by**: QA/Infrastructure
- **File**: `infra/alertmanager/alertmanager.yml:37-46`
- **Issue**: When a service goes completely down, `ServiceDown`, `HighErrorRate`, `CriticalErrorRate`, `HighP95Latency`, `OutboxBacklog`, `DeadLetterQueueNonEmpty` all fire simultaneously for the same service — notification flood for a single root cause.
- **Suggestion**: Add inhibit rule suppressing all other alerts when `ServiceDown` fires for the same job.
- **Auto-fixable**: YES

---

### MINOR Issues

| ID | Severity | File | Issue |
|----|----------|------|-------|
| F-037 | MINOR | `infra/alertmanager/alertmanager.yml:6-7` | SMTP `require_tls: false` — alerts sent unencrypted |
| F-038 | MINOR | `infra/grafana/dashboards/outbox-health.json` | Only covers S4/S5 outbox; S1/S6/S7 outbox invisible |
| F-039 | MINOR | `infra/grafana/provisioning/dashboards/dashboards.yml:8` | `foldersFromFilesStructure: false` blocks dashboard hierarchy |
| F-040 | MINOR | `libs/ml-clients/src/ml_clients/cost.py:25` | Pricing table missing Anthropic, Jina, Cohere entries |
| F-041 | MINOR | `services/nlp-pipeline/.../embedding_retry_worker.py` | No Prometheus metrics (queue depth, retry success/fail) |
| F-042 | MINOR | `services/nlp-pipeline/.../price_impact_labelling_worker.py` | No counter for windows upserted |
| F-043 | MINOR | `infra/grafana/provisioning/dashboards/dashboards.yml` | `disableDeletion: false` allows deletion of audit dashboards |
| F-044 | MINOR | `infra/compose/docker-compose.yml:519` | Grafana missing security hardening env vars |
| F-045 | NIT | `libs/observability/src/observability/logging.py` | No PII scrubbing processor in structlog chain |
| F-046 | NIT | `infra/compose/docker-compose.yml:39-43` | MinIO default credentials hardcoded in compose file |
| F-047 | NIT | `libs/observability/src/observability/metrics.py` | No outbox dispatch latency histogram in `ServiceMetrics` |

---

## Test Execution Results

> **Note**: This QA pass is a full observability audit (config, architecture, metrics, security). Unit and integration test suites for individual services are not scoped to this investigation — they cover service business logic, not observability infrastructure. Relevant test results from recent QA passes:
> - 550+649 unit tests PASS (confirmed 2026-04-27, commit 77fa9a6)
> - No tests exist for Prometheus alert rule correctness, Alloy config, or dashboard PromQL queries

| Layer | Status | Notes |
|-------|--------|-------|
| Prometheus Alert Rules (semantic) | FAIL | F-017 (regex), F-018 (rag-chat false alert), F-027 (histogram_quantile) |
| Grafana Dashboard PromQL | FAIL | eodhd-health.json histogram_quantile bug |
| Loki Config | FAIL | No retention policy (disk exhaustion risk) |
| Alloy Config | FAIL | Label mismatch, no filter, no scrubbing |
| Tempo Config | FAIL | metrics_generator not configured |
| AlertManager Config | FAIL | Routes to MailHog only, missing inhibit rules |
| Security Config | FAIL | 2 live secrets in repo, auth disabled on Loki |
| ML Instrumentation | FAIL | All adapters uninstrumented |
| observability lib | FAIL | trace_id not injected into logs |

---

## Supplementary Checks

| Check | Status | Notes |
|-------|--------|-------|
| Import Guards | N/A | Not applicable to observability config |
| Service Structure | PASS | All 10 services follow hexagonal structure |
| Schema Validation | N/A | No Avro changes in scope |
| Doc Freshness | WARN | `docs/libs/observability.md` states trace_id is injected — this is incorrect per F-006 |
| Security Scan | FAIL | F-004 (API key), F-005 (RSA key), F-015 (admin tokens) |
| Dependency Check | N/A | No new dependencies added |

---

## BLOCKING Issue Deep Investigations

---

## Issue F-001: Zero ML API Instrumentation

### Summary
Every external ML API adapter in `libs/ml-clients` (DeepInfra embedding, DeepInfra LLM, Anthropic, Gemini extraction, Gemini description, Cohere rerank, Jina embedding, GLiNER HTTP) has zero Prometheus metrics for latency, error rate, token consumption, or cost. The `LlmUsageLogProtocol` DB-log infrastructure exists and is partially wired in some workers, but the latency and token fields are often zeroed, and none of it feeds Prometheus.

### Root Cause Analysis
- **What**: All 8 ML adapters lack `time.perf_counter()` calls and Prometheus metric increments around API calls.
- **Why**: The `LlmUsageLogProtocol` was designed for DB-based cost tracking (llm_usage_log table). Prometheus metrics were added to application services but never extended to the shared ML client library. The protocol exists but was treated as a DB concern, not an observability concern.
- **When**: Always — every ML API call since the adapters were created.
- **Where**: `libs/ml-clients/src/ml_clients/adapters/` — the infrastructure layer of the ML client library.
- **History**: This is a new class of gap, not a regression. The observability lib was designed for HTTP services; ML adapters are not HTTP services.

### Impact
- **Immediate**: 100% of the ML pipeline is invisible to Prometheus monitoring.
- **Blast radius**: DeepInfra going down, being rate-limited, or returning degraded results produces zero metrics. No alert fires. The only signal is degraded pipeline throughput, which takes minutes to hours to become visible.
- **Data risk**: Cost tracking is unreliable — many adapters pass zeroed token/latency values to the DB log.
- **User impact**: Users see stale enrichment, slow searches, incomplete morning briefs — with no operational visibility for the team.

### Solution

**Option A (Recommended): Shared helper in libs/observability**

Create `libs/observability/src/observability/ml_metrics.py`:
```python
from prometheus_client import Counter, Histogram
import time

ml_api_requests_total = Counter(
    "ml_api_requests_total",
    "ML API calls by provider, model, capability, status",
    ["provider", "model", "capability", "status"]
)
ml_api_latency_seconds = Histogram(
    "ml_api_latency_seconds",
    "ML API call wall-clock latency",
    ["provider", "model", "capability"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0)
)
ml_api_tokens_in_total = Counter(
    "ml_api_tokens_in_total", "Input tokens", ["provider", "model", "capability"]
)
ml_api_tokens_out_total = Counter(
    "ml_api_tokens_out_total", "Output tokens", ["provider", "model", "capability"]
)
ml_api_estimated_cost_usd_total = Counter(
    "ml_api_estimated_cost_usd_total", "Estimated USD cost", ["provider", "model", "capability"]
)

def record_ml_call(*, provider, model, capability, input_tokens, output_tokens,
                   latency_seconds, success, error_type=None):
    status = "ok" if success else (error_type or "error")
    ml_api_requests_total.labels(provider, model, capability, status).inc()
    ml_api_latency_seconds.labels(provider, model, capability).observe(latency_seconds)
    if success:
        ml_api_tokens_in_total.labels(provider, model, capability).inc(input_tokens)
        ml_api_tokens_out_total.labels(provider, model, capability).inc(output_tokens)
```

Wrap each adapter's API call:
```python
t0 = time.perf_counter()
try:
    result = await self._call_api(...)
    latency = time.perf_counter() - t0
    record_ml_call(provider="deepinfra", model=self._model_id, capability="embedding",
                   input_tokens=usage.get("prompt_tokens", 0), output_tokens=0,
                   latency_seconds=latency, success=True)
    return result
except Exception as exc:
    latency = time.perf_counter() - t0
    error_type = "timeout" if isinstance(exc, TimeoutError) else "rate_limit" if "429" in str(exc) else "error"
    record_ml_call(provider="deepinfra", model=self._model_id, capability="embedding",
                   input_tokens=0, output_tokens=0, latency_seconds=latency,
                   success=False, error_type=error_type)
    raise
```

**Changes required**:
- [ ] Create `libs/observability/src/observability/ml_metrics.py` with shared metric definitions + `record_ml_call()`
- [ ] Update `libs/ml-clients/src/ml_clients/adapters/deepinfra_embedding.py` — wrap `embed()`
- [ ] Update `libs/ml-clients/src/ml_clients/adapters/deepinfra_llm.py` — wrap `complete()`
- [ ] Update `libs/ml-clients/src/ml_clients/adapters/anthropic_extraction.py` — wrap `extract()`
- [ ] Update `libs/ml-clients/src/ml_clients/adapters/gemini_extraction.py` — wrap `extract()`
- [ ] Update `libs/ml-clients/src/ml_clients/adapters/gemini_description.py` — fix `latency_ms=0`
- [ ] Update `libs/ml-clients/src/ml_clients/adapters/cohere_rerank.py` — wrap `rerank()`
- [ ] Update `libs/ml-clients/src/ml_clients/adapters/jina_embedding.py` — wrap `embed()`
- [ ] Update `libs/ml-clients/src/ml_clients/adapters/gliner_http.py` — wrap `batch_extract_entities()`
- [ ] Update `libs/ml-clients/src/ml_clients/cost.py` — add Anthropic, Jina, Cohere pricing
- [ ] Create `infra/grafana/dashboards/L5-ml/ml-pipeline.json` — ML observability dashboard

**Effort**: Medium | **Risk**: Low

### Verification
- [ ] `curl http://nlp-pipeline:8000/metrics | grep ml_api_requests_total` returns values after processing articles
- [ ] Grafana ML dashboard shows non-zero latency for each provider
- [ ] Alert `MLApiHighErrorRate` fires in a test where DeepInfra returns 429

---

## Issue F-002: Kafka Consumer Lag — No Metric, No Alert

### Summary
`BaseKafkaConsumer` tracks throughput (messages/sec) but not lag (how far behind consumers are from the topic head). A consumer can be processing at 90% of the production rate and silently accumulate a multi-hour backlog. The platform has 20+ consumer processes spanning all 10 services, none with lag visibility.

### Root Cause Analysis
- **What**: No `kafka_consumer_lag_messages` Gauge in `ServiceMetrics`, no JMX/kafka-exporter scrape target.
- **Why**: The `libs/observability` metrics module was designed around the 6 standard RED metrics. Kafka lag requires either broker-side access (JMX/AdminClient) or consumer position tracking, which is more complex than a simple counter.
- **When**: Always. A consumer that falls 10,000 messages behind fires no alert and shows no signal in any dashboard.
- **Where**: `libs/messaging/src/messaging/kafka/consumer/base.py` (application side); `infra/prometheus/prometheus.yml` (missing broker scrape).

### Impact
- **Immediate**: Content freshness SLO is unverifiable. Pipeline freshness degradation is undetectable.
- **Blast radius**: S5 dedup, S6 NLP enrichment, S7 knowledge graph, S10 alerts — all can silently fall behind.
- **User impact**: Stale news, outdated entity knowledge, delayed or missing flash alerts.

### Solution

**Option A (Recommended): Lightweight position tracking in BaseKafkaConsumer**
After each message commit, compute lag from watermark offsets:
```python
# In BaseKafkaConsumer._handle_message() after commit:
for tp in self._consumer.assignment():
    low, high = self._consumer.get_watermark_offsets(tp, timeout=1.0, cached=True)
    committed = self._consumer.committed([tp], timeout=1.0)
    lag = high - (committed[0].offset if committed[0] else 0)
    self._metrics.kafka_consumer_lag.labels(
        topic=tp.topic, partition=tp.partition,
        consumer_group=self._config.group_id
    ).set(max(0, lag))
```

**Option B (Authoritative)**: Add `kafka-exporter` container with `kafka_consumergroup_lag` metric.

**Alert rules to add**:
```yaml
- alert: KafkaConsumerLagHigh
  expr: kafka_consumer_lag_messages > 10000
  for: 5m
  labels:
    severity: warning
- alert: KafkaConsumerSilent
  expr: job_topic:kafka_consumed:rate5m == 0 and on(job) up == 1
  for: 10m
  labels:
    severity: warning
```

**Changes required**:
- [ ] Add `kafka_consumer_lag: Gauge` to `ServiceMetrics` in `libs/observability/src/observability/metrics.py`
- [ ] Add watermark polling to `BaseKafkaConsumer._handle_message()` after commit
- [ ] Add `KafkaConsumerLagHigh` and `KafkaConsumerSilent` alert rules
- [ ] Optionally add `kafka-exporter` to `docker-compose.yml` for broker-side accuracy

**Effort**: Medium | **Risk**: Low

---

## Issue F-003: Consumer Task Crash Not Detected

### Summary
A fatal exception in a Kafka consumer's `run()` loop silently kills the consumer. The main coroutine (blocked on `stop_event.wait()`) never observes the failed task. Detection occurs only when Docker's healthcheck fires (30-60 seconds), during which time messages accumulate unprocessed.

### Root Cause Analysis
- **What**: `asyncio.create_task(consumer.run())` — task failure is never observed by the main coroutine.
- **Why**: Standard asyncio fire-and-forget pattern without done_callback. The `except Exception` in main() only catches exceptions from `consumer_task.cancel()` path (SIGTERM handling), not from the task's internal failure.
- **When**: On any unhandled exception in the consumer loop — DB connection reset, Kafka connection reset, unexpected data format, OOM.
- **Where**: All `*_consumer_main.py` files across all consumer services.

### Solution

Add a `done_callback` that triggers `sys.exit(1)` on unexpected task termination:
```python
def _on_consumer_exit(task: asyncio.Task) -> None:
    if not task.cancelled() and not stop_event.is_set():
        exc = task.exception()
        if exc is not None:
            log.error("consumer_task_fatal", error=str(exc), exc_info=exc)
            sys.exit(1)

consumer_task = asyncio.create_task(consumer.run())
consumer_task.add_done_callback(_on_consumer_exit)
```

**Changes required** (all consumer_main.py files):
- [ ] `services/content-store/src/content_store/intelligence_consumer_main.py`
- [ ] `services/nlp-pipeline/src/nlp_pipeline/article_consumer_main.py`
- [ ] `services/knowledge-graph/src/knowledge_graph/article_consumer_main.py`
- [ ] `services/rag-chat/src/rag_chat/article_consumer_main.py`
- [ ] `services/alert/src/alert/alert_consumer_main.py`
- [ ] `services/market-data/src/market_data/ohlcv_consumer_main.py` (and 4 others)

**Effort**: Low | **Risk**: Low

---

## DESIGN PROPOSALS

### I. Error Monitoring System

**A. Server-side Error Capture (implement in `libs/observability`)**

Move `unhandled_exception_handler` from portfolio to a shared module:
```python
# libs/observability/src/observability/error_capture.py

def add_exception_handlers(app: FastAPI, service_name: str, error_counter: Counter) -> None:
    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        error_counter.labels(
            error_class=type(exc).__name__,
            endpoint=request.url.path,
        ).inc()
        logger.error(
            "unhandled_exception",
            error_class=type(exc).__name__,
            path=request.url.path,
            user_id=getattr(request.state, "user_id", None),
            tenant_id=getattr(request.state, "tenant_id", None),
            exc_info=exc,
        )
        return JSONResponse(status_code=500, content={"error": "internal_server_error"})
```

**B. Background Worker Error Capture**
```python
async def run_worker_forever(fn, *, name: str, interval_seconds: float, error_counter: Counter):
    while True:
        try:
            await fn()
        except Exception as exc:
            error_counter.labels(worker_name=name, error_class=type(exc).__name__).inc()
            logger.error("worker_error", worker=name, exc_info=exc)
        await asyncio.sleep(interval_seconds)
```

**C. Alert Routing Redesign**
```yaml
# infra/alertmanager/alertmanager.yml (proposed)
receivers:
  - name: slack-critical
    slack_configs:
      - api_url: "${SLACK_WEBHOOK_URL}"
        channel: "#incidents"
        title: ':rotating_light: [CRITICAL] {{ .GroupLabels.alertname }}'
        send_resolved: true
  - name: pagerduty-critical
    pagerduty_configs:
      - routing_key: "${PAGERDUTY_INTEGRATION_KEY}"

route:
  routes:
    - match:
        severity: critical
      receiver: pagerduty-critical
      continue: true
    - match:
        severity: critical
      receiver: slack-critical
```

---

### II. Synthetic Monitoring System

Deploy a dedicated `worldview-synthetic` Docker container running Python health probes via `httpx`. The container pushes results to a Prometheus Pushgateway every 30 seconds.

**Checked flows** (every 30s for critical, 5m for full flows):
1. `health_*` — direct healthcheck probe per service
2. `login` — dev-login → JWT obtained
3. `instrument_list` — `GET /api/v1/instruments` (SLA: 500ms)
4. `instrument_detail` — fetch AAPL detail (SLA: 500ms)
5. `news_search` — `GET /api/v1/news/top` (SLA: 1s)
6. `portfolio_holdings` — `GET /api/v1/portfolio/holdings` (SLA: 500ms)
7. `websocket_connect` — WebSocket connect + ping receive (SLA: 3s)
8. `morning_brief` — `GET /api/v1/morning-brief` (SLA: 3s)

**Prometheus metrics exported**:
```
synthetic_check_up{check_name, service}              # 1=ok, 0=failing
synthetic_check_duration_seconds{check_name, status} # histogram
synthetic_last_run_timestamp_seconds{check_name}     # for dead-monitor alert
```

**Alert rules**:
```yaml
- alert: SyntheticCheckFailed
  expr: synthetic_check_up == 0
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "User-visible flow '{{ $labels.check_name }}' is failing"

- alert: SyntheticMonitoringDead
  expr: time() - synthetic_last_run_timestamp_seconds{check_name="login"} > 120
  for: 0m
  labels:
    severity: critical
  annotations:
    summary: "Synthetic monitoring container is not running"
```

**Security architecture**:
- Dedicated Zitadel machine user (`synthetic@worldview.local`) in isolated `synthetic` tenant
- Rotate OIDC client secret every 30 days via CI/CD
- Rate-limiter allowlist for synthetic user_id
- Alloy drops `synthetic=true` labeled logs before shipping to main Loki tenant

---

### III. Canary Release Architecture (Feature Flag Approach)

**Recommended approach** for Docker Compose + <50 users: **Feature flags in Valkey**, evaluated per-request in API Gateway (S9).

**Flag Store**: `gw:v1:flag:{flag_name}` → `{"enabled": true, "rollout_pct": 10}`

**Cohort assignment**: Deterministic hash of `user_id` mod 100. Same user always gets same variant — no flickering.

**Metric labeling**:
```
api_gateway_requests_total{..., flag="news_ranking_v2=canary"}
api_gateway_requests_total{..., flag="news_ranking_v2=stable"}
```

**Rollback triggers** (Prometheus alert → AlertManager webhook → `POST /internal/v1/flags/rollback`):
```yaml
- alert: CanaryErrorRateTooHigh
  expr: >
    flag_variant:http_error_ratio:rate5m{flag=~".+=canary"}
      > 2 * on() group_left()
    flag_variant:http_error_ratio:rate5m{flag=~".+=stable"}
  for: 3m
  labels:
    severity: critical
    action: rollback
```

**Grafana comparison panels**:
- Canary vs stable error rate side-by-side (time series, 1h window)
- Canary/stable error ratio stat (red threshold at 2.0x)
- Traffic distribution pie (canary% vs stable%)
- Latency comparison p50/p95 per variant
- Rollback event annotations

---

### IV. SLO Framework

Five SLOs aligned with MASTER_PLAN non-functional requirements:

| SLO | User Journey | SLI | Target | 30d Budget |
|-----|-------------|-----|--------|-----------|
| SLO-001 | API Availability | `avg(up{job=~"..."})` | 99.5% | 3.6h |
| SLO-002 | API Latency | Fraction of requests served ≤500ms (excl. rag-chat) | 99% | 7.2h |
| SLO-003 | Content Freshness | NLP throughput ≥ fetch rate (no backpressure) | 95% | 36h |
| SLO-004 | Alert Delivery | `s10_alert_delivery_latency_seconds{le="30"}` fraction | 99% | 7.2h |
| SLO-005 | Portfolio Sync | `s1_portfolio_sync_duration_seconds{le="60"}` fraction | 99% | 7.2h |

**Burn-rate alerts** (fast-burn at 14.4x for 5m → critical; slow-burn at 6x over 6h → warning) following Google SRE error budget pattern.

---

### V. Dashboard Hierarchy (Proposed 5-Layer Structure)

Change `foldersFromFilesStructure: true` in Grafana provisioning and reorganize:

```
L1-overview/
  operations-overview.json    — service health grid + error budgets + active alerts + deploy annotations
  slo-error-budget.json       — 5 SLO burn-rate panels + budget gauges
  canary-comparison.json      — canary vs stable RED comparison

L2-service-red/
  portfolio.json / market-ingestion.json / market-data.json / content-ingestion.json
  content-store.json / nlp-pipeline.json / knowledge-graph.json / rag-chat.json
  api-gateway.json (KEEP+ENHANCE) / alert-service.json

L3-pipeline/
  content-pipeline.json (KEEP+ENHANCE) / kafka-pipeline.json (KEEP+ENHANCE)
  market-data-pipeline.json / portfolio-sync-pipeline.json / outbox-health.json (KEEP)

L4-infrastructure/
  postgres-health.json / kafka-broker-health.json / minio-health.json
  valkey-health.json / docker-containers.json (cAdvisor)

L5-ml/
  ml-providers.json           — per-provider: latency, error rate, token usage, cost
  nlp-throughput.json         — articles/hr, embedding queue, enrichment age
  kg-enrichment.json          — relation confidence distributions, contradiction rate
```

**Existing 8 dashboards**: service-overview → L2; api-gateway → L2 enhanced; content-pipeline → L3 enhanced; kafka-pipeline → L3 enhanced; outbox-health → L3; logs-explorer → keep as utility; eodhd-health → merge into L2/market-ingestion (with histogram_quantile bug fixed); api-usage-analytics → L1.

---

## Priority-Ordered Action Plan

### P0 — Fix immediately (BLOCKING/CRITICAL bugs, config-only or small code changes)

| # | Finding | Effort | Impact |
|---|---------|--------|--------|
| 1 | F-017: Fix `s[1-9]` regex → `s[0-9]+` in alert rules | 5 min | S10 now covered |
| 2 | F-018: Fix HighP95Latency to exclude rag-chat | 10 min | Eliminate alert fatigue |
| 3 | F-027: Fix histogram_quantile in eodhd-health.json | 5 min | Accurate EODHD latency |
| 4 | F-011: Add Loki retention policy | 15 min | Prevent disk exhaustion |
| 5 | F-036: Add ServiceDown inhibit rule in AlertManager | 15 min | Reduce notification flood |
| 6 | F-006: Add trace_id OTel processor to structlog | 1h | Enable log↔trace correlation |
| 7 | F-013: Configure Tempo metrics_generator | 30 min | Enable service graphs |
| 8 | F-030: Fix Alloy Docker label (worldview-X-1 → X) | 20 min | Log↔metric label alignment |
| 9 | F-031: Add container filter to Alloy | 20 min | Reduce Loki noise |
| 10 | F-014: Add loki/tempo/alertmanager scrape targets | 20 min | Infra observability |

### P1 — Fix this sprint (security + high-impact gaps)

| # | Finding | Effort | Impact |
|---|---------|--------|--------|
| 11 | F-004/F-005/F-015: Rotate secrets, replace with placeholders | 1h | Eliminate credential exposure |
| 12 | F-008: Add exception handler to 8 services | 2h | Structured error capture everywhere |
| 13 | F-003: Add consumer task done_callback | 2h | Consumer crash auto-detected |
| 14 | F-009: Add Slack receiver to AlertManager | 2h | Team actually sees alerts |
| 15 | F-010: Bind monitoring ports to 127.0.0.1 | 30 min | Reduce attack surface |
| 16 | F-026: Remove Grafana default password | 5 min | Eliminate admin access risk |
| 17 | F-024: Add structlog PII scrubbing processor | 1h | Stop PII in Loki |
| 18 | F-021: Add KGWorkerCrash alert | 15 min | S7 worker crash visible |
| 19 | F-020: Add WebSocket active connections gauge + alert | 1h | Alert delivery health |
| 20 | F-034: Fix domain exception detail exposure | 2h | Stop internal details in responses |

### P2 — Next sprint (instrumentation + dashboards)

| # | Finding | Effort | Impact |
|---|---------|--------|--------|
| 21 | F-001: ML adapter instrumentation (all 8 adapters) | 1 day | Full ML pipeline visibility |
| 22 | F-002: Kafka consumer lag metric | 1 day | Pipeline freshness observable |
| 23 | F-019/F-032: Add Postgres, Valkey, Kafka broker scrapes | 2 days | Infrastructure layer visible |
| 24 | F-023: Add SQLAlchemy pool events + ValkeyClient metrics | 1 day | DB/cache health visible |
| 25 | Create RAG-chat and Alert service dashboards | 1 day | S8/S10 operational panels |
| 26 | F-007/F-003: Implement SLO recording rules + alerts | 1 day | Error budget framework |
| 27 | F-012: Remove ticker label from s7_insider_transactions | 30 min | Prevent cardinality explosion |
| 28 | F-022: Fix ML worker zeroed token/latency fields | 2h | Accurate cost tracking |

### P3 — This quarter (design work)

| # | Finding | Effort | Impact |
|---|---------|--------|--------|
| 29 | Synthetic monitoring system (worldview-synthetic container) | 3 days | End-to-end user flow detection |
| 30 | Canary release feature flag system | 3 days | Safe gradual deployments |
| 31 | Full 5-layer Grafana dashboard hierarchy | 1 week | Complete operational visibility |
| 32 | `libs/observability` extensions (error_capture, slo_metrics, synthetic, cost_tracker) | 3 days | Shared reliability primitives |

---

## New Bug Patterns (add to docs/BUG_PATTERNS.md)

**BP-260**: `asyncio.create_task()` without `add_done_callback()` — consumer task crash goes undetected. Pattern: always add `_on_consumer_exit` callback that calls `sys.exit(1)` on unexpected task failure.

**BP-261**: structlog OTel context not injected — docs claim `trace_id` in every log line but it only works if `opentelemetry.trace.get_current_span()` is called in a structlog processor. Verify with `curl http://service/v1/some-endpoint` then search Loki for the trace_id from Tempo.

**BP-262**: Prometheus regex `[1-9]` matches single digit — always use `[0-9]+` or `\d+` for service number patterns to avoid silently excluding service S10.

**BP-263**: Histogram quantile without `sum by (label, le)` — `histogram_quantile(q, rate(metric_bucket[5m]))` must be wrapped with `sum by (relevant_labels, le)` first, otherwise multi-series histograms return incorrect percentiles.

**BP-264**: ML adapter latency_ms=0 — when calling `usage_logger.log()`, always pass actual `time.perf_counter()` measurement. Never pass literal `0` — it permanently corrupts cost analytics in the DB.

---

## Recommendations (Priority Order)

1. **Rotate the secrets now** (F-004, F-005, F-015): The DeepInfra key and RSA private key in git history are an immediate security risk. Rotate both keys, replace files with placeholders, add `git-secrets` hook.

2. **Fix the 10 P0 config bugs** (alert regex, HighP95Latency threshold, histogram_quantile, Loki retention, Alloy labels): These are all under 30 minutes each and fix observability infrastructure that is actively wrong today.

3. **Wire trace_id into logs** (F-006): Single 10-line function in `libs/observability`. Without it, Loki↔Tempo correlation — a core feature of the stack — doesn't work. Do this before any other observability work.

4. **Add exception handlers to 8 services and consumer done_callbacks** (F-008, F-003): These two changes ensure 500 errors and consumer crashes produce structured, queryable log events within seconds of occurrence.

5. **Add Slack/PagerDuty to AlertManager** (F-009): Without this, no alert ever reaches the team in a real deployment. Even a free Slack workspace with a webhook makes the monitoring functional.

6. **Instrument all ML adapters** (F-001): Create the shared helper in `libs/observability/ml_metrics.py`. The DeepInfra, Gemini, Anthropic, Cohere, Jina, GLiNER adapters all need < 20 lines each added.

7. **Add Kafka consumer lag** (F-002): Use the lightweight position-tracking approach in `BaseKafkaConsumer`. Add `KafkaConsumerSilent` alert using the existing recording rule. This closes the biggest pipeline freshness blind spot.

8. **Deploy synthetic monitoring**: The `worldview-synthetic` container (complete Python implementation provided above) gives immediate end-to-end user-flow detection covering multiple failure modes simultaneously. It detects issues the Prometheus scrape-based system cannot (login broken, search returns no results, WebSocket disconnected).

9. **Implement SLO framework** (F-007): Add the 5 SLO recording rules and burn-rate alerts. This transforms the alerting from "something is wrong" to "we're spending reliability budget at Nx rate and will exhaust it in Yh."

10. **Canary releases**: The feature flag approach using Valkey for flag state and S9 for cohort assignment is the right fit for Docker Compose at thesis scale. Implement as part of the next major feature deployment.

---

*Compounding check: BP-260 through BP-264 added above. `docs/libs/observability.md` should be updated to correct the false claim that trace_id is injected into logs (F-006). `RULES.md` should add: "R28: Every consumer task created with asyncio.create_task() MUST have a done_callback that calls sys.exit(1) on unexpected failure."*
