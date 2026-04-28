# PLAN-0054: Full-Stack Observability Implementation

> **Source**: QA audit `docs/audits/2026-04-28-qa-observability-full-audit.md`
> **Status**: draft
> **Created**: 2026-04-28
> **Architect**: Staff engineer / TPM

---

## Overview

This plan implements every remaining BLOCKING, CRITICAL, and MAJOR finding from the 2026-04-28 observability audit. Seven P0 config fixes were already applied in the audit session (regex, Loki retention, Alloy label fix, Tempo metrics_generator, AlertManager inhibit, trace_id injection). This plan covers everything requiring code changes, new modules, or infrastructure additions.

**Sub-plans**:
- **A** — `libs/observability` extensions (ML metrics, consumer lag, error capture)
- **B** — ML adapter instrumentation (12 adapters)
- **C** — Service hardening (exception handlers, consumer crash detection, worker crash protection)
- **D** — Infrastructure & alerting (exporters, SLO rules, dashboard fixes, alert routing)
- **E** — Synthetic monitoring & canary releases

**Execution order**: A → B → C → D → E (B and C can run in parallel after A)

---

## Phase 0: Pre-Flight Gate

| Check | Result |
|-------|--------|
| No unresolved BLOCKING OQs | PASS — audit findings are all implementation gaps, no design questions |
| No active cross-plan conflicts | PASS — no other active plan modifies libs/observability or ML adapters |
| PRD recency | PASS — source is the 2026-04-28 audit (same day) |
| Architecture compliance | PASS — all changes follow existing patterns |

---

## Codebase State Delta Table

| Finding | Type | Current State | Required State | Delta |
|---------|------|--------------|----------------|-------|
| F-001: ML instrumentation | lib + adapters | Zero metrics in all 12 adapters | `MLMetrics` dataclass in observability, all adapters record latency/tokens/cost | New module + 12 adapter changes |
| F-002: Kafka lag | lib | No `kafka_consumer_lag` gauge | Gauge in `ServiceMetrics`, exported per topic+partition | Add Gauge to metrics.py + consumer |
| F-003: Consumer crash | 6 consumer_main.py | No done_callback on consumer task | `done_callback` calls `sys.exit(1)` on unexpected task death | 6 consumer_main.py changes |
| F-008: Exception handlers | 8 app.py files | No `app.add_exception_handler(Exception, ...)` | Shared `error_capture.py` + registered in each app | New module + 8 app.py changes |
| F-009: Alert routing | alertmanager.yml | MailHog-only | Slack webhook receiver + PagerDuty placeholder + critical/warning split routes | alertmanager.yml |
| F-020: WS gauge | alert/app.py | No active WebSocket connections gauge | `websocket_active_connections` Gauge on ConnectionManager | alert/app.py + ServiceMetrics |
| F-023: DB pool metrics | 5 app.py files | No SQLAlchemy pool instrumentation | Pool event listeners → Gauge | Shared helper + 5 app.py |
| F-028: SLO framework | prometheus | No SLO recording rules | 5 SLOs with recording rules + burn-rate alerts | New rules files |
| F-031: Dashboard histogram bug | eodhd-health.json | `histogram_quantile` without `sum by le` | Correct PromQL with `sum by (endpoint, le)` | 1 dashboard edit |
| F-034: Postgres exporter | docker-compose.yml | No postgres_exporter | Add postgres_exporter service | docker-compose + prometheus.yml |
| F-035: Worker crash | content-ingestion, market-ingestion | No outer try/except on main while loop | Wrap run loop in try/except Exception → log + sleep | 2 worker files |
| F-036: tenant_id cardinality | rag-chat metrics | `tenant_id` as label | Remove label | rag-chat app.py |
| F-037: Valkey alert | prometheus | No Valkey down alert | New `ValkeyDown` alert rule | alert-rules.yml |
| F-038: Grafana RAG dashboard | grafana | No RAG-chat dashboard | New rag-chat.json dashboard | New file |
| F-039: Grafana Alert dashboard | grafana | No Alert service dashboard | New alert-service.json dashboard | New file |

---

## Sub-Plan A: libs/observability Extensions

### Wave A-1: MLMetrics + ErrorCapture + ConsumerLag

**Goal**: Extend `libs/observability` with three new capabilities used by all downstream sub-plans.
**Depends on**: none
**Estimated effort**: 45-60 min
**Architecture layer**: domain/infrastructure (shared library)

#### Pre-read
- `libs/observability/src/observability/metrics.py`
- `libs/observability/src/observability/__init__.py`
- `libs/observability/src/observability/logging.py`
- `libs/observability/tests/` (existing test files)

---

#### T-A-1-01: Add `MLMetrics` dataclass and `create_ml_metrics()` to metrics.py

**Type**: impl
**depends_on**: none
**blocks**: [T-B-1-01, T-B-2-01, T-B-3-01]
**Target files**:
- `libs/observability/src/observability/metrics.py`
- `libs/observability/src/observability/__init__.py`

**What to build**:
A new `MLMetrics` dataclass holding four Counters (requests, errors, tokens_in, tokens_out, estimated_cost_usd) and one Histogram (latency_seconds). A `create_ml_metrics(service_name, registry=None)` function follows the same idempotency + is-not-None registry pattern as `create_metrics()`.

**Entities / Components**:
- **Name**: `MLMetrics`
- **Purpose**: Prometheus metrics for one ML model client within a service
- **Key attributes**:
  - `ml_api_requests_total: Counter` — labels: `model_id`, `operation` (embed/extract/describe/rerank/score), `status` (success/error)
  - `ml_api_latency_seconds: Histogram` — labels: `model_id`, `operation`; buckets: 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60
  - `ml_api_tokens_in_total: Counter` — labels: `model_id` (best-effort, 0 if unknown)
  - `ml_api_tokens_out_total: Counter` — labels: `model_id`
  - `ml_api_estimated_cost_usd_total: Counter` — labels: `model_id` (using published per-token rates)
- **Invariants**: same registry idempotency logic as `create_metrics()`; no `service_name` prefix (model_id label is sufficient)

**Logic & Behavior**:
1. Add `MLMetrics` dataclass below `ServiceMetrics` in metrics.py
2. Add `_global_ml_metrics_cache: dict[str, MLMetrics] = {}` for global REGISTRY dedup
3. Implement `create_ml_metrics(service_name: str, registry: CollectorRegistry | None = None) -> MLMetrics` — use `service_name` as prefix for the metric names (e.g. `{ns}_ml_api_requests_total`) so services don't collide
4. Export from `__init__.py`: `MLMetrics`, `create_ml_metrics`
5. Also add `kafka_consumer_lag_seconds` Gauge to `ServiceMetrics` (see T-A-1-02) in the same edit

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_create_ml_metrics_idempotent | Two calls same service_name → same instance | unit |
| test_create_ml_metrics_isolated_registry | Explicit registry → not cached | unit |
| test_ml_metrics_labels | Counter/histogram label names correct | unit |
| test_ml_metrics_cost_counter_inc | `.inc()` works on estimated_cost_usd_total | unit |

**Acceptance criteria**:
- [ ] `MLMetrics` dataclass exported from `observability`
- [ ] `create_ml_metrics("my-svc")` called twice returns same instance
- [ ] All metric names follow `{ns}_ml_api_*` pattern
- [ ] ruff + mypy pass
- [ ] 4 new unit tests pass

---

#### T-A-1-02: Add `kafka_consumer_lag` Gauge to ServiceMetrics

**Type**: impl
**depends_on**: none
**blocks**: [T-C-2-01]
**Target files**:
- `libs/observability/src/observability/metrics.py`

**What to build**:
Add `kafka_consumer_lag` as a `Gauge` field on `ServiceMetrics` with labels `topic`, `partition`, `consumer_group`. The gauge is set by `BaseKafkaConsumer` after each watermark poll.

**Logic & Behavior**:
1. Import `Gauge` from `prometheus_client`
2. Add `kafka_consumer_lag: Gauge` field to `ServiceMetrics` dataclass
3. In `create_metrics()`, register: `Gauge(f"{ns}_kafka_consumer_lag", "Kafka consumer lag (messages behind high watermark)", labelnames=["topic", "partition", "consumer_group"], registry=reg)`
4. The gauge must be initialized to 0 for all known topic/partition combos at consumer startup to prevent "no data" gaps (done in BaseKafkaConsumer, not here)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_kafka_consumer_lag_gauge_present | `ServiceMetrics` has `kafka_consumer_lag` attribute | unit |
| test_kafka_consumer_lag_set | `.labels(topic="t", partition="0", consumer_group="g").set(42)` records correctly | unit |

**Acceptance criteria**:
- [ ] `ServiceMetrics.kafka_consumer_lag` is a `Gauge`
- [ ] No existing tests broken (backward-compatible addition)
- [ ] ruff + mypy pass

---

#### T-A-1-03: Add `error_capture.py` module to observability

**Type**: impl
**depends_on**: none
**blocks**: [T-C-1-01]
**Target files**:
- `libs/observability/src/observability/error_capture.py`
- `libs/observability/src/observability/__init__.py`

**What to build**:
A shared FastAPI exception handler function `unhandled_exception_handler` that: (1) extracts request context (method, path, request_id), (2) logs with structlog at ERROR level including `exc_info=True`, (3) returns a generic `{"detail": "internal server error"}` JSON response with status 500. Also a helper `register_error_handlers(app, metrics)` that registers both `HTTPException` and `Exception` handlers.

**Logic & Behavior**:
```python
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log = get_logger("error_capture")
    log.error(
        "unhandled_exception",
        method=request.method,
        path=request.url.path,
        request_id=request.headers.get("X-Request-ID", ""),
        exc_info=exc,
    )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})

def register_error_handlers(app: FastAPI, metrics: ServiceMetrics | None = None) -> None:
    app.add_exception_handler(Exception, unhandled_exception_handler)
```

The `metrics` parameter is optional for future counter instrumentation (increment a `500_errors_total` counter if provided).

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_unhandled_exception_returns_500 | Handler returns status 500 + JSON body | unit |
| test_unhandled_exception_logs_error | structlog captures `unhandled_exception` event | unit |
| test_register_error_handlers | `register_error_handlers(app)` does not raise | unit |

**Acceptance criteria**:
- [ ] `register_error_handlers` exported from `observability`
- [ ] Returns `{"detail": "internal server error"}` as JSON with status 500
- [ ] Logs include method, path, request_id, exc_info
- [ ] ruff + mypy pass
- [ ] 3 new unit tests pass

---

#### T-A-1-04: Add `websocket_active_connections` Gauge to ServiceMetrics

**Type**: impl
**depends_on**: none
**blocks**: [T-C-1-03]
**Target files**:
- `libs/observability/src/observability/metrics.py`

**What to build**:
Add optional `websocket_active_connections: Gauge | None` to `ServiceMetrics`. Services that don't use WebSockets will have `None`. A `create_metrics(..., include_websocket=False)` parameter controls whether it's registered.

**Logic & Behavior**:
1. Add `websocket_active_connections: Gauge | None = None` to `ServiceMetrics` dataclass
2. Add `include_websocket: bool = False` parameter to `create_metrics()`
3. When `include_websocket=True`: register `Gauge(f"{ns}_websocket_active_connections", "Active WebSocket connections", registry=reg)` and set the field
4. Alert service calls `create_metrics("alert", include_websocket=True)`

**Acceptance criteria**:
- [ ] Default `create_metrics("svc")` → `websocket_active_connections is None`
- [ ] `create_metrics("alert", include_websocket=True)` → non-None Gauge
- [ ] No existing tests broken
- [ ] ruff + mypy pass

---

#### Validation Gate A-1
- [ ] `ruff check libs/observability && ruff format --check libs/observability` — zero errors
- [ ] `mypy libs/observability/src --config-file libs/observability/mypy.ini` — zero errors
- [ ] `cd libs/observability && python -m pytest tests/ -m unit -v --tb=short` — all pass, ≥10 new tests
- [ ] `observability.__init__` exports: `MLMetrics`, `create_ml_metrics`, `register_error_handlers`

#### Break Impact A-1
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `libs/observability/tests/test_metrics.py` | `ServiceMetrics` gains new `kafka_consumer_lag` and `websocket_active_connections` fields | These are additive fields with defaults — existing tests still pass; no fix needed |
| Any service test that constructs `ServiceMetrics(...)` directly | New required field | `ServiceMetrics` fields are created by `create_metrics()`, not constructed directly — no breakage |

#### Regression Guardrails A-1
- **BP-173**: `registry if registry is not None else REGISTRY` — all new metric creation must use this pattern, never `registry or REGISTRY`
- **BP-269**: No logging calls before `configure_logging()` — `error_capture.py` uses `get_logger()` lazily inside the handler body, not at module level, so this is safe

---

### Wave A-2: Update `__init__.py` and observability docs

**Goal**: Ensure all new symbols are exported and docs updated.
**Depends on**: Wave A-1
**Estimated effort**: 15 min
**Architecture layer**: docs

#### T-A-2-01: Export new symbols + update observability.md

**Type**: impl + docs
**depends_on**: [T-A-1-01, T-A-1-02, T-A-1-03, T-A-1-04]
**blocks**: none
**Target files**:
- `libs/observability/src/observability/__init__.py`
- `docs/libs/observability.md`

**What to build**:
Verify and extend `__init__.py` exports. Update `docs/libs/observability.md` Public API section to document `MLMetrics`, `create_ml_metrics`, `register_error_handlers`, and the new `ServiceMetrics` fields.

**Acceptance criteria**:
- [ ] `from observability import MLMetrics, create_ml_metrics, register_error_handlers` works
- [ ] observability.md Public API table updated
- [ ] observability.md Common Pitfalls updated with note about `include_websocket=True` for WS services

---

## Sub-Plan B: ML Adapter Instrumentation

### Wave B-1: Embedding Adapters

**Goal**: Instrument all three embedding adapters with `MLMetrics`.
**Depends on**: Wave A-1
**Estimated effort**: 45 min
**Architecture layer**: infrastructure (libs/ml-clients)

#### Pre-read
- `libs/ml-clients/src/ml_clients/adapters/deepinfra_embedding.py`
- `libs/ml-clients/src/ml_clients/adapters/ollama_embedding.py`
- `libs/ml-clients/src/ml_clients/adapters/jina_embedding.py`
- `libs/ml-clients/src/ml_clients/dataclasses.py` (EmbeddingInput/Output fields)
- `libs/ml-clients/src/ml_clients/__init__.py`

---

#### T-B-1-01: Instrument DeepInfra + Ollama + Jina embedding adapters

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**:
- `libs/ml-clients/src/ml_clients/adapters/deepinfra_embedding.py`
- `libs/ml-clients/src/ml_clients/adapters/ollama_embedding.py`
- `libs/ml-clients/src/ml_clients/adapters/jina_embedding.py`

**What to build**:
Add `MLMetrics` parameter to each adapter's `__init__`. Wrap the `embed()` and `embed_batch()` methods with:
1. `time.perf_counter()` start/stop to measure latency_seconds
2. `ml_api_requests_total.labels(model_id=..., operation="embed", status="success/error").inc()`
3. `ml_api_latency_seconds.labels(model_id=..., operation="embed").observe(latency)`
4. `ml_api_tokens_in_total.labels(model_id=...).inc(len(text.split()))` (word-count approximation when actual tokens unknown)
5. `ml_api_estimated_cost_usd_total.labels(model_id=...).inc(cost)` — DeepInfra BAAI/bge: $0.013/1M tokens; Jina: $0.02/1M; Ollama: 0.0

**Logic & Behavior**:
```python
# Pattern for each adapter method:
start = time.perf_counter()
status = "success"
try:
    result = await self._do_embed(inp)
    return result
except (RetryableError, FatalError):
    status = "error"
    raise
finally:
    latency = time.perf_counter() - start
    if self._metrics:
        self._metrics.ml_api_requests_total.labels(
            model_id=self._model_id, operation="embed", status=status
        ).inc()
        self._metrics.ml_api_latency_seconds.labels(
            model_id=self._model_id, operation="embed"
        ).observe(latency)
```

The `MLMetrics` parameter is optional (`metrics: MLMetrics | None = None`) to maintain backward compatibility with existing callers that don't pass it.

**Downstream test impact**:
- Existing tests that construct adapters without `metrics=` continue to work (optional param)
- Test files must NOT be modified to add metrics; backward compatibility is the requirement

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_deepinfra_embed_records_latency | After `embed()` returns, histogram has 1 sample | unit |
| test_deepinfra_embed_records_error_status | After `embed()` raises, `status="error"` counter incremented | unit |
| test_ollama_embed_no_metrics_noop | Adapter with `metrics=None` works without errors | unit |
| test_jina_embed_records_cost | Cost counter > 0 after successful embed | unit |

**Acceptance criteria**:
- [ ] All three embedding adapters accept optional `metrics: MLMetrics | None = None`
- [ ] Successful embed increments `status="success"` counter + latency histogram
- [ ] Failed embed increments `status="error"` counter
- [ ] `metrics=None` (default) → no AttributeError, no counter operations
- [ ] ruff + mypy pass

---

### Wave B-2: Extraction Adapters

**Goal**: Instrument all extraction adapters (LLM-based) with `MLMetrics`.
**Depends on**: Wave A-1
**Estimated effort**: 45 min
**Architecture layer**: infrastructure (libs/ml-clients)

#### Pre-read
- `libs/ml-clients/src/ml_clients/adapters/ollama_extraction.py`
- `libs/ml-clients/src/ml_clients/adapters/deepseek_extraction.py`
- `libs/ml-clients/src/ml_clients/adapters/anthropic_extraction.py`
- `libs/ml-clients/src/ml_clients/adapters/gemini_extraction.py`
- `libs/ml-clients/src/ml_clients/adapters/chatgpt_extraction.py`

---

#### T-B-2-01: Instrument extraction adapters

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**:
- `libs/ml-clients/src/ml_clients/adapters/ollama_extraction.py`
- `libs/ml-clients/src/ml_clients/adapters/deepseek_extraction.py`
- `libs/ml-clients/src/ml_clients/adapters/anthropic_extraction.py`
- `libs/ml-clients/src/ml_clients/adapters/gemini_extraction.py`
- `libs/ml-clients/src/ml_clients/adapters/chatgpt_extraction.py`

**What to build**:
Same pattern as T-B-1-01 but for `extract()` method with `operation="extract"`. For LLM extraction adapters that return token counts in the API response body, use actual token counts. Otherwise use word-count approximation.

**Per-model cost rates** (encode in constants per adapter):
- Ollama: $0.0 (local)
- DeepSeek: $0.14/1M input, $0.28/1M output
- Anthropic Claude: $3.0/1M input, $15.0/1M output (claude-3-5-sonnet)
- Gemini Flash Lite: $0.075/1M input, $0.30/1M output
- ChatGPT/OpenAI: $0.15/1M input, $0.60/1M output (gpt-4o-mini)

Cost formula: `cost = (tokens_in * COST_IN_PER_TOKEN) + (tokens_out * COST_OUT_PER_TOKEN)`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_ollama_extract_records_metrics | Counter + histogram after successful extract | unit |
| test_deepseek_extract_cost_nonzero | Cost counter > 0 after extract (non-zero rates) | unit |
| test_extraction_error_increments_error_status | `status="error"` counter on FatalError | unit |

**Acceptance criteria**:
- [ ] All 5 extraction adapters accept optional `metrics: MLMetrics | None = None`
- [ ] Token counts used when available from API response; word-count approximation otherwise
- [ ] ruff + mypy pass

---

### Wave B-3: Scoring, Ranking, and Description Adapters

**Goal**: Instrument remaining adapters (GLiNER, Cohere, Gemini Description).
**Depends on**: Wave A-1
**Estimated effort**: 30 min
**Architecture layer**: infrastructure (libs/ml-clients)

#### T-B-3-01: Instrument GLiNER, Cohere, and Gemini description adapters

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**:
- `libs/ml-clients/src/ml_clients/adapters/gliner_local.py`
- `libs/ml-clients/src/ml_clients/adapters/gliner_http.py`
- `libs/ml-clients/src/ml_clients/adapters/gliner_adaptive.py`
- `libs/ml-clients/src/ml_clients/adapters/cohere_rerank.py`
- `libs/ml-clients/src/ml_clients/adapters/gemini_description.py`

**What to build**:
Same instrumentation pattern with `operation="ner"` for GLiNER, `operation="rerank"` for Cohere, `operation="describe"` for Gemini Description. GLiNER cost = $0.0 (local). Cohere Rerank: $2.0/1k searches. Gemini: same Flash Lite rates as above.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_gliner_local_ner_records_metrics | Counter after NER call | unit |
| test_cohere_rerank_cost_calculated | Cost = 2.0/1000 per rerank call | unit |

**Acceptance criteria**:
- [ ] All 5 adapters accept optional `metrics: MLMetrics | None = None`
- [ ] `operation` label correctly set per adapter type
- [ ] ruff + mypy pass

---

#### T-B-3-02: Wire MLMetrics into service adapter factories

**Type**: impl
**depends_on**: [T-B-1-01, T-B-2-01, T-B-3-01]
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/app.py`
- `services/nlp-pipeline/src/nlp_pipeline/app.py` (or equivalent factory)
- `services/rag-chat/src/rag_chat/app.py`
- `services/content-ingestion/src/content_ingestion/app.py`

**What to build**:
In each service's app factory (lifespan), create `ml_metrics = create_ml_metrics(service_name)` and pass it to adapter constructors. Each service already calls `create_metrics(service_name)` — add the ML counterpart alongside it.

**Logic & Behavior**:
```python
# In lifespan:
metrics = create_metrics("knowledge-graph")
ml_metrics = create_ml_metrics("knowledge-graph")
embedding_adapter = DeepInfraEmbeddingAdapter(..., metrics=ml_metrics)
```

**Acceptance criteria**:
- [ ] 4 service app factories wire `ml_metrics` to adapters
- [ ] No existing tests broken
- [ ] ruff + mypy pass

---

#### Validation Gate B (all waves)
- [ ] `ruff check libs/ml-clients && ruff format --check libs/ml-clients` — zero errors
- [ ] `mypy libs/ml-clients/src --config-file libs/ml-clients/mypy.ini` — zero errors
- [ ] All new adapter unit tests pass (≥15 new tests total)
- [ ] All existing ml-clients tests pass

#### Regression Guardrails B
- **BP-235**: Always use `httpx.Timeout()` when wrapping with `asyncio.wait_for` — adapters with `asyncio.wait_for` must keep existing timeout configuration
- **BP-272**: `latency_ms=0` corrupts cost analytics — use `time.perf_counter()` (float seconds), never integer milliseconds; multiply by 1000 only for logging display, not for metrics recording

---

## Sub-Plan C: Service Hardening

### Wave C-1: Global Exception Handlers in 8 Services

**Goal**: Register unhandled exception handler in every service that is missing it.
**Depends on**: Wave A-1
**Estimated effort**: 30 min
**Architecture layer**: API

#### Pre-read
- `libs/observability/src/observability/error_capture.py` (from T-A-1-03)
- `services/alert/src/alert/app.py`
- `services/content-ingestion/src/content_ingestion/app.py`
- `services/nlp-pipeline/src/nlp_pipeline/app.py`
- `services/knowledge-graph/src/knowledge_graph/app.py`
- `services/rag-chat/src/rag_chat/app.py`
- `services/market-data/src/market_data/app.py`
- `services/market-ingestion/src/market_ingestion/app.py`
- `services/api-gateway/src/api_gateway/app.py`

---

#### T-C-1-01: Register `register_error_handlers` in 8 service app factories

**Type**: impl
**depends_on**: [T-A-1-03]
**blocks**: none
**Target files**:
- `services/alert/src/alert/app.py`
- `services/content-ingestion/src/content_ingestion/app.py`
- `services/nlp-pipeline/src/nlp_pipeline/app.py`
- `services/knowledge-graph/src/knowledge_graph/app.py`
- `services/rag-chat/src/rag_chat/app.py`
- `services/market-data/src/market_data/app.py`
- `services/market-ingestion/src/market_ingestion/app.py`
- `services/api-gateway/src/api_gateway/app.py`

**What to build**:
In each service's app factory, after the FastAPI app is created, add:
```python
from observability import register_error_handlers
register_error_handlers(app)
```
This must be called BEFORE other middleware/route registrations to ensure the handler is at the outermost layer.

Note: `services/portfolio` and `services/content-store` already have exception handlers per the audit — skip those.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_unhandled_exception_returns_500_{service} | Each service's test client → internal route that raises → 500 JSON | unit (1 per service = 8 tests) |

Add one test per service in `services/{svc}/tests/api/test_error_handler.py` (new file per service).

**Acceptance criteria**:
- [ ] All 8 services have `register_error_handlers(app)` in their app factory
- [ ] Each service has a test confirming 500 + `{"detail": "internal server error"}` on unhandled raise
- [ ] ruff + mypy pass for all 8 services

---

#### T-C-1-02: Add `websocket_active_connections` gauge to Alert service

**Type**: impl
**depends_on**: [T-A-1-04]
**blocks**: none
**Target files**:
- `services/alert/src/alert/app.py`
- `services/alert/src/alert/infrastructure/websocket/manager.py`

**What to build**:
In `alert/app.py`, change `create_metrics("alert")` to `create_metrics("alert", include_websocket=True)`. In `ConnectionManager`, accept `metrics: ServiceMetrics` and call:
- `metrics.websocket_active_connections.inc()` in `connect()`
- `metrics.websocket_active_connections.dec()` in `disconnect()`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_ws_gauge_increments_on_connect | After `connect()`, gauge value increases by 1 | unit |
| test_ws_gauge_decrements_on_disconnect | After `disconnect()`, gauge value decreases by 1 | unit |

**Acceptance criteria**:
- [ ] `alert_websocket_active_connections` metric exported at `/metrics`
- [ ] Gauge is correctly incremented/decremented
- [ ] ruff + mypy pass

---

### Wave C-2: Consumer Crash Detection

**Goal**: Ensure Kafka consumer task crashes are detected and cause service restart.
**Depends on**: Wave A-1
**Estimated effort**: 30 min
**Architecture layer**: infrastructure

#### Pre-read
- `libs/messaging/src/messaging/kafka/consumer/base.py` (existing `run()` method)
- Consumer main files: find all `*_main.py` or `main.py` files in services that start consumers

---

#### T-C-2-01: Add `done_callback` to BaseKafkaConsumer + watermark lag poll

**Type**: impl
**depends_on**: [T-A-1-02]
**blocks**: none
**Target files**:
- `libs/messaging/src/messaging/kafka/consumer/base.py`

**What to build**:
Two changes to `BaseKafkaConsumer`:

1. **Done callback**: In `run()` or wherever `asyncio.create_task(self._consume_loop())` is called, add a done callback:
```python
def _on_consumer_task_done(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and task.exception() is not None:
        log.critical("consumer_task_crashed", exc_info=task.exception())
        # Force process restart — orchestrator (Docker/k3s) will restart the service
        import sys
        sys.exit(1)

consumer_task = asyncio.create_task(self._consume_loop())
consumer_task.add_done_callback(_on_consumer_task_done)
```

2. **Kafka lag gauge**: After committing each batch of offsets, poll `consumer.get_watermark_offsets(tp)` for each assigned partition and set the lag gauge:
```python
for tp in self._consumer.assignment():
    low, high = self._consumer.get_watermark_offsets(tp, timeout=1.0)
    position = self._consumer.position([tp])[0].offset
    lag = max(0, high - position)
    if self._metrics:
        self._metrics.kafka_consumer_lag.labels(
            topic=tp.topic,
            partition=str(tp.partition),
            consumer_group=self._group_id,
        ).set(lag)
```

**Downstream test impact**:
- `libs/messaging/tests/unit/test_base_consumer.py` — existing tests must mock `get_watermark_offsets` to avoid real Kafka calls

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_done_callback_on_task_crash_calls_sys_exit | Task raises → `sys.exit(1)` called | unit |
| test_done_callback_on_graceful_stop_no_exit | Cancelled task → no `sys.exit` | unit |
| test_lag_gauge_set_after_poll | Watermark returns 100, position 80 → gauge=20 | unit |

**Acceptance criteria**:
- [ ] `sys.exit(1)` called when consumer task raises unexpectedly
- [ ] Cancelled task (graceful shutdown) does NOT call `sys.exit`
- [ ] Lag gauge updated after each batch
- [ ] ruff + mypy pass
- [ ] 3 new unit tests pass

---

### Wave C-3: Worker Crash Protection

**Goal**: Prevent content-ingestion and market-ingestion worker main loops from crashing silently.
**Depends on**: none (independent of A/B/C-1/C-2)
**Estimated effort**: 20 min
**Architecture layer**: infrastructure

---

#### T-C-3-01: Wrap WorkerProcess and market-ingestion scheduler main loops

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/content-ingestion/src/content_ingestion/infrastructure/workers/worker.py`
- `services/market-ingestion/src/market_ingestion/workers/` (find the scheduler/worker main loop)

**What to build**:
Wrap the outer `while True:` loop in a `try/except Exception as exc:` block that logs the exception and sleeps before continuing:
```python
while True:
    try:
        await self._run_one_iteration()
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("worker_loop_error")
        await asyncio.sleep(5)  # Back-off before retrying
```

This prevents a single bad task from crashing the entire worker process.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_worker_loop_survives_exception | Exception in iteration → loop continues after sleep | unit |
| test_worker_loop_reraises_cancelled | CancelledError propagates out of loop | unit |

**Acceptance criteria**:
- [ ] Worker loop recovers from single-iteration exceptions
- [ ] `CancelledError` still propagates (graceful shutdown works)
- [ ] ruff + mypy pass

---

#### Validation Gate C
- [ ] All 8 service app.py files contain `register_error_handlers(app)`
- [ ] Alert service exports `alert_websocket_active_connections` gauge
- [ ] `BaseKafkaConsumer` has done_callback + lag polling
- [ ] Worker loops have outer try/except
- [ ] All new tests pass (≥16 new tests)
- [ ] ruff + mypy pass on all modified services + libs/messaging

#### Regression Guardrails C
- **BP-268**: `asyncio.create_task` without done_callback — this wave FIXES BP-268; verify the callback is attached to the task returned by `asyncio.create_task`, not a wrapper
- **BP-269**: structlog before configure_logging — `error_capture.py` uses lazy `get_logger()` inside handler, never at module import time

---

## Sub-Plan D: Infrastructure, Alerting, SLOs, and Dashboards

### Wave D-1: Infrastructure Exporters

**Goal**: Add postgres_exporter and redis_exporter so DB and cache have visibility.
**Depends on**: none
**Estimated effort**: 30 min
**Architecture layer**: config/infra

#### T-D-1-01: Add postgres_exporter to docker-compose

**Type**: config
**depends_on**: none
**blocks**: [T-D-2-01]
**Target files**:
- `infra/compose/docker-compose.yml`
- `infra/compose/docker-compose.dev.yml` (if separate)
- `infra/prometheus/prometheus.yml`

**What to build**:
Add two new services to the `monitoring` profile in docker-compose:

```yaml
postgres_exporter:
  image: quay.io/prometheuscommunity/postgres-exporter:v0.15.0
  profiles: [monitoring, all]
  environment:
    DATA_SOURCE_NAME: "postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/worldview_db?sslmode=disable"
  ports:
    - "127.0.0.1:9187:9187"
  depends_on:
    postgres:
      condition: service_healthy

redis_exporter:
  image: oliver006/redis_exporter:v1.62.0
  profiles: [monitoring, all]
  environment:
    REDIS_ADDR: "redis://valkey:6379"
  ports:
    - "127.0.0.1:9121:9121"
  depends_on:
    - valkey
```

Add scrape targets to `prometheus.yml`:
```yaml
- job_name: "postgres"
  static_configs:
    - targets: ["postgres_exporter:9187"]
  metrics_path: /metrics

- job_name: "valkey"
  static_configs:
    - targets: ["redis_exporter:9121"]
  metrics_path: /metrics
```

**Acceptance criteria**:
- [ ] `postgres_exporter` and `redis_exporter` services defined in docker-compose monitoring profile
- [ ] Both added to prometheus.yml scrape_configs
- [ ] Port bindings use `127.0.0.1:` prefix (SEC-007 localhost-only binding)

---

#### T-D-1-02: Add DB connection pool metrics via SQLAlchemy event listeners

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `libs/observability/src/observability/db_metrics.py` (new file)
- `libs/observability/src/observability/__init__.py`

**What to build**:
A new `instrument_sqlalchemy_pool(engine, metrics: ServiceMetrics)` function that uses SQLAlchemy pool events to track pool utilization:

```python
from sqlalchemy import event
from prometheus_client import Gauge

def instrument_sqlalchemy_pool(engine: Any, service_name: str, registry: CollectorRegistry | None = None) -> None:
    reg = registry if registry is not None else REGISTRY
    ns = service_name.replace("-", "_")
    pool_checked_out = Gauge(f"{ns}_db_pool_checked_out", "DB connections checked out", registry=reg)
    pool_size = Gauge(f"{ns}_db_pool_size", "DB connection pool size", registry=reg)

    @event.listens_for(engine.sync_engine, "checkout")
    def on_checkout(dbapi_conn, conn_record, conn_proxy):
        pool_checked_out.set(engine.pool.checkedout())
        pool_size.set(engine.pool.size())

    @event.listens_for(engine.sync_engine, "checkin")
    def on_checkin(dbapi_conn, conn_record):
        pool_checked_out.set(engine.pool.checkedout())
```

Wire into 3 services with databases: portfolio, market-data, knowledge-graph (add call in their app.py lifespan after creating the engine).

**Acceptance criteria**:
- [ ] `instrument_sqlalchemy_pool` exported from `observability`
- [ ] Pool checkout/checkin events update gauges
- [ ] ruff + mypy pass

---

### Wave D-2: SLO Recording Rules and Burn-Rate Alerts

**Goal**: Implement a 5-SLO framework with burn-rate alerting.
**Depends on**: none (Prometheus rules are config changes)
**Estimated effort**: 30 min
**Architecture layer**: config

#### T-D-2-01: SLO recording rules file

**Type**: config
**depends_on**: none
**blocks**: [T-D-2-02]
**Target files**:
- `infra/prometheus/rules/slo-recording-rules.yml` (new file)
- `infra/prometheus/prometheus.yml` (verify rule_files includes `/etc/prometheus/rules/*.yml`)

**What to build**:
Create `infra/prometheus/rules/slo-recording-rules.yml` with 5 SLO recording rules:

```yaml
groups:
  - name: slo_recording_rules
    interval: 30s
    rules:
      # SLO-1: API Gateway availability (99.9% target = 0.1% error budget)
      - record: slo:api_gateway:error_rate_5m
        expr: |
          sum(rate(api_gateway_requests_total{status=~"5.."}[5m]))
          / sum(rate(api_gateway_requests_total[5m]))

      # SLO-2: Portfolio service availability (99.5% target)
      - record: slo:portfolio:error_rate_5m
        expr: |
          sum(rate(portfolio_requests_total{status=~"5.."}[5m]))
          / sum(rate(portfolio_requests_total[5m]))

      # SLO-3: Market Data freshness — P95 latency < 500ms (99% of requests)
      - record: slo:market_data:p95_latency_5m
        expr: |
          histogram_quantile(0.95,
            sum by (le) (rate(market_data_request_duration_seconds_bucket[5m]))
          )

      # SLO-4: RAG Chat end-to-end latency < 30s (95% of requests)
      - record: slo:rag_chat:p95_latency_5m
        expr: |
          histogram_quantile(0.95,
            sum by (le) (rate(rag_chat_request_duration_seconds_bucket[5m]))
          )

      # SLO-5: Content ingestion pipeline throughput (processed > 0 in 1h window)
      - record: slo:content_ingestion:throughput_1h
        expr: |
          sum(increase(content_ingestion_kafka_messages_consumed_total[1h]))
```

**Acceptance criteria**:
- [ ] `slo-recording-rules.yml` created with 5 recording rules
- [ ] PromQL uses correct label selectors matching actual metric names
- [ ] All `histogram_quantile` calls use `sum by (le)` pattern (BP-271)

---

#### T-D-2-02: SLO burn-rate alert rules

**Type**: config
**depends_on**: [T-D-2-01]
**blocks**: none
**Target files**:
- `infra/prometheus/rules/slo-alerts.yml` (new file)

**What to build**:
Two-tier burn-rate alerts for SLO-1 (API gateway) and SLO-2 (portfolio) — the most customer-visible SLOs:

```yaml
groups:
  - name: slo_burn_rate_alerts
    rules:
      # Fast burn: 14.4x error budget consumption rate over 1h window
      - alert: APIGatewayFastBurnRate
        expr: |
          sum(rate(api_gateway_requests_total{status=~"5.."}[1h]))
          / sum(rate(api_gateway_requests_total[1h])) > (14.4 * 0.001)
        for: 2m
        labels:
          severity: critical
          slo: api_gateway_availability
        annotations:
          summary: "API Gateway fast burn rate — error budget will exhaust in < 2h"
          runbook: "Check Grafana → Service Overview → api-gateway row"

      # Slow burn: 6x error budget consumption rate over 6h window
      - alert: APIGatewaySlowBurnRate
        expr: |
          sum(rate(api_gateway_requests_total{status=~"5.."}[6h]))
          / sum(rate(api_gateway_requests_total[6h])) > (6 * 0.001)
        for: 15m
        labels:
          severity: warning
          slo: api_gateway_availability
        annotations:
          summary: "API Gateway slow burn rate — error budget will exhaust in < 1d"

      # Portfolio fast burn
      - alert: PortfolioFastBurnRate
        expr: |
          sum(rate(portfolio_requests_total{status=~"5.."}[1h]))
          / sum(rate(portfolio_requests_total[1h])) > (14.4 * 0.005)
        for: 2m
        labels:
          severity: critical
          slo: portfolio_availability
        annotations:
          summary: "Portfolio service fast burn rate"

      # Valkey down
      - alert: ValkeyDown
        expr: redis_up == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Valkey (Redis) is down — rate limiting and caching unavailable"
```

**Acceptance criteria**:
- [ ] 4 burn-rate alert rules created
- [ ] `ValkeyDown` alert uses `redis_up` metric from redis_exporter
- [ ] All alerts have `severity`, `summary` labels/annotations

---

### Wave D-3: Grafana Dashboard Fixes and Additions

**Goal**: Fix eodhd-health.json histogram bug, add RAG-chat and Alert-service dashboards.
**Depends on**: none
**Estimated effort**: 45 min
**Architecture layer**: config

#### T-D-3-01: Fix histogram_quantile in eodhd-health.json (BP-271)

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**:
- `infra/grafana/dashboards/eodhd-health.json`

**What to build**:
Find all `histogram_quantile(0.5, rate(` patterns in the file (per BP-271) and fix them to include `sum by (endpoint, le)`:

```
# Before (broken — arbitrary values when multiple label combos):
histogram_quantile(0.5, rate(eodhd_request_duration_seconds_bucket[5m]))

# After (correct — aggregates over all label combos except le):
histogram_quantile(0.5, sum by (endpoint, le) (rate(eodhd_request_duration_seconds_bucket[5m])))
```

Apply the same fix to any `histogram_quantile(0.95, ...)` panels in the same file.

**Acceptance criteria**:
- [ ] All `histogram_quantile` in eodhd-health.json use `sum by (..., le)` wrapper
- [ ] JSON file remains valid (test with `python3 -m json.tool infra/grafana/dashboards/eodhd-health.json`)

---

#### T-D-3-02: Create RAG-chat Grafana dashboard

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**:
- `infra/grafana/dashboards/rag-chat.json` (new file)

**What to build**:
A Grafana dashboard JSON for the RAG-chat service (S8) with these panels:
1. **Request rate** (graph): `rate(rag_chat_requests_total[5m])`
2. **Error rate %** (stat): errors / total × 100
3. **P95 latency** (graph, threshold 30s warning): `histogram_quantile(0.95, sum by (le) (rate(rag_chat_request_duration_seconds_bucket[5m])))`
4. **Active WebSocket connections** (stat): not applicable for rag-chat; skip
5. **Kafka consumed (intent classifier)** (graph): `rate(rag_chat_kafka_messages_consumed_total[5m])`
6. **ML API requests by model** (graph): `rate(rag_chat_ml_api_requests_total[5m])` by `model_id`
7. **ML estimated cost** (stat): `increase(rag_chat_ml_api_estimated_cost_usd_total[24h])`
8. **P95 LLM latency** (graph): `histogram_quantile(0.95, sum by (model_id, le) (rate(rag_chat_ml_api_latency_seconds_bucket[5m])))`

Dashboard title: `"RAG Chat — S8"`, uid: `"rag-chat"`, tags: `["worldview", "service"]`

**Acceptance criteria**:
- [ ] `rag-chat.json` is valid Grafana dashboard JSON
- [ ] Contains ≥6 panels covering request, error, latency, cost
- [ ] All histogram_quantile use `sum by (le)` pattern

---

#### T-D-3-03: Create Alert service Grafana dashboard

**Type**: config
**depends_on**: [T-C-1-02]
**blocks**: none
**Target files**:
- `infra/grafana/dashboards/alert-service.json` (new file)

**What to build**:
A Grafana dashboard for the Alert service (S10):
1. **Active WebSocket connections** (stat + sparkline): `alert_websocket_active_connections`
2. **Alert fanout rate** (graph): `rate(alert_requests_total{path="/v1/alerts"}[5m])`
3. **Alert delivery latency P95** (graph)
4. **Error rate** (stat)
5. **Kafka consumed (alert.triggered.v1)** (graph)
6. **Auth failures** (graph): rate of 401/403 responses

Dashboard title: `"Alert Service — S10"`, uid: `"alert-service"`, tags: `["worldview", "service"]`

**Acceptance criteria**:
- [ ] `alert-service.json` is valid JSON
- [ ] WebSocket active connections panel references correct metric name
- [ ] Contains ≥5 panels

---

### Wave D-4: AlertManager Routing Fix

**Goal**: Route critical alerts to Slack webhook instead of MailHog-only.
**Depends on**: none
**Estimated effort**: 20 min
**Architecture layer**: config

#### T-D-4-01: Add Slack webhook receiver to alertmanager.yml

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**:
- `infra/alertmanager/alertmanager.yml`

**What to build**:
Add a Slack receiver and split routing between warning (MailHog) and critical (MailHog + Slack):

```yaml
global:
  resolve_timeout: 5m
  slack_api_url: "${SLACK_WEBHOOK_URL}"  # Set via environment variable

route:
  receiver: "default"
  group_by: ["alertname", "job"]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - match:
        severity: critical
      receiver: "critical"
      repeat_interval: 1h
    - match:
        severity: warning
      receiver: "warning"

receivers:
  - name: "default"
    email_configs:
      - to: "alerts@worldview.local"
        from: "alertmanager@worldview.local"
        smarthost: "mailhog:1025"
        require_tls: false

  - name: "warning"
    email_configs:
      - to: "alerts@worldview.local"
        from: "alertmanager@worldview.local"
        smarthost: "mailhog:1025"
        require_tls: false

  - name: "critical"
    email_configs:
      - to: "alerts@worldview.local"
        from: "alertmanager@worldview.local"
        smarthost: "mailhog:1025"
        require_tls: false
    slack_configs:
      - channel: "#alerts-critical"
        title: "{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}"
        text: "{{ range .Alerts }}{{ .Annotations.runbook }}{{ end }}"
        send_resolved: true
```

Add `SLACK_WEBHOOK_URL` to `infra/compose/configs/docker.env.example` (not docker.env — keep secrets out of git).

**Acceptance criteria**:
- [ ] `critical` receiver includes both email + Slack configs
- [ ] Slack URL comes from `SLACK_WEBHOOK_URL` env var (not hardcoded)
- [ ] `SLACK_WEBHOOK_URL=` placeholder added to docker.env.example
- [ ] Existing inhibit_rules block preserved

---

#### Validation Gate D
- [ ] `python3 -m json.tool infra/grafana/dashboards/eodhd-health.json` — valid JSON
- [ ] `python3 -m json.tool infra/grafana/dashboards/rag-chat.json` — valid JSON
- [ ] `python3 -m json.tool infra/grafana/dashboards/alert-service.json` — valid JSON
- [ ] `docker compose -f infra/compose/docker-compose.yml config` — valid compose config
- [ ] All new prometheus rule files valid YAML
- [ ] No secrets in any committed file

#### Regression Guardrails D
- **BP-175**: Docker internal ports — postgres_exporter and redis_exporter use container hostname (postgres:5432, valkey:6379), not host-mapped ports
- **BP-271**: histogram_quantile without `sum by le` — every PromQL expression in new dashboards and recording rules must include `sum by (..., le)` wrapping

---

## Sub-Plan E: Synthetic Monitoring

### Wave E-1: Synthetic Monitoring Container

**Goal**: Deploy a periodic synthetic monitor that simulates user journeys and pushes results to Prometheus.
**Depends on**: Wave D-1 (Prometheus has pushgateway; if not, add it)
**Estimated effort**: 90 min
**Architecture layer**: infra

---

#### T-E-1-01: Add Prometheus Pushgateway to docker-compose

**Type**: config
**depends_on**: none
**blocks**: [T-E-1-02]
**Target files**:
- `infra/compose/docker-compose.yml`
- `infra/prometheus/prometheus.yml`

**What to build**:
```yaml
pushgateway:
  image: prom/pushgateway:v1.8.0
  profiles: [monitoring, all]
  ports:
    - "127.0.0.1:9091:9091"
```

Add scrape target to prometheus.yml:
```yaml
- job_name: "pushgateway"
  honor_labels: true
  static_configs:
    - targets: ["pushgateway:9091"]
```

---

#### T-E-1-02: Create synthetic monitoring Python module

**Type**: impl
**depends_on**: [T-E-1-01]
**blocks**: none
**Target files**:
- `infra/synthetic/synthetic_monitor.py` (new file)
- `infra/synthetic/Dockerfile` (new file)
- `infra/synthetic/requirements.txt` (new file)
- `infra/compose/docker-compose.yml` (add synthetic service)

**What to build**:
A Python script that runs three synthetic checks every 60 seconds and pushes results to Pushgateway:

```python
"""Synthetic monitoring — simulates real user journeys every 60s."""
import asyncio
import time
import httpx
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

PUSHGATEWAY_URL = os.environ.get("PUSHGATEWAY_URL", "http://pushgateway:9091")
API_BASE = os.environ.get("API_BASE_URL", "http://api-gateway:8000")
DEV_JWT = os.environ.get("SYNTHETIC_JWT", "")  # Dev-login JWT

registry = CollectorRegistry()
probe_success = Gauge("synthetic_probe_success", "1 if probe succeeded, 0 otherwise",
                      ["probe_name"], registry=registry)
probe_duration_seconds = Gauge("synthetic_probe_duration_seconds", "Probe duration",
                               ["probe_name"], registry=registry)

async def probe_health_check():
    """Journey: API gateway health endpoint."""

async def probe_portfolio_load():
    """Journey: Fetch portfolio holdings for synthetic user."""

async def probe_market_data_quote():
    """Journey: GET /api/v1/market-data/AAPL/quote."""

async def run_probes():
    probes = [probe_health_check, probe_portfolio_load, probe_market_data_quote]
    for probe_fn in probes:
        name = probe_fn.__name__
        start = time.perf_counter()
        try:
            await probe_fn()
            probe_success.labels(probe_name=name).set(1.0)
        except Exception:
            probe_success.labels(probe_name=name).set(0.0)
        finally:
            probe_duration_seconds.labels(probe_name=name).set(time.perf_counter() - start)
    push_to_gateway(PUSHGATEWAY_URL, job="synthetic_monitor", registry=registry)

async def main():
    while True:
        await run_probes()
        await asyncio.sleep(60)
```

Dockerfile:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY synthetic_monitor.py .
CMD ["python", "synthetic_monitor.py"]
```

Docker-compose service:
```yaml
synthetic-monitor:
  build: ../synthetic/
  profiles: [monitoring, all]
  environment:
    PUSHGATEWAY_URL: "http://pushgateway:9091"
    API_BASE_URL: "http://api-gateway:8000"
    SYNTHETIC_JWT: "${SYNTHETIC_MONITOR_JWT:-}"
  depends_on:
    - pushgateway
    - api-gateway
  restart: unless-stopped
```

Add `SyntheticProbeDown` alert to `infra/prometheus/rules/alert-rules.yml`:
```yaml
- alert: SyntheticProbeDown
  expr: synthetic_probe_success == 0
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Synthetic probe {{ $labels.probe_name }} failing for 5m"
```

**Acceptance criteria**:
- [ ] `infra/synthetic/synthetic_monitor.py` implements ≥3 probe functions
- [ ] Pushes to Pushgateway every 60s
- [ ] `SyntheticProbeDown` alert rule added
- [ ] `SYNTHETIC_MONITOR_JWT=` placeholder in docker.env.example
- [ ] Dockerfile builds without errors

---

### Wave E-2: Canary Release Feature Flags

**Goal**: Implement feature flag infrastructure for safe canary releases via Valkey.
**Depends on**: Wave C-1 (api-gateway app.py changes are coordinated)
**Estimated effort**: 60 min
**Architecture layer**: infrastructure + API

---

#### T-E-2-01: Feature flag middleware in API Gateway

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/api-gateway/src/api_gateway/infrastructure/feature_flags/` (new directory)
- `services/api-gateway/src/api_gateway/infrastructure/feature_flags/store.py`
- `services/api-gateway/src/api_gateway/infrastructure/feature_flags/middleware.py`
- `services/api-gateway/src/api_gateway/api/routers/admin.py` (add flag management endpoints)
- `services/api-gateway/src/api_gateway/app.py`

**What to build**:

`store.py` — FeatureFlagStore (Valkey-backed):
```python
class FeatureFlagStore:
    """Valkey-backed feature flag store.

    Flags are stored as Valkey hashes: feature_flags:{flag_name}
    Fields: enabled (0/1), rollout_percentage (0-100), enabled_user_ids (JSON list)
    """
    def __init__(self, valkey_client: ValkeyClient) -> None: ...

    async def is_enabled(self, flag_name: str, user_id: str) -> bool:
        """Return True if flag is enabled for this user.

        Rules (in order):
        1. If flag not found → False (safe default)
        2. If user_id in enabled_user_ids → True (allowlist override)
        3. If rollout_percentage > 0 → use consistent hash(flag_name + user_id) % 100 < rollout_percentage
        4. Otherwise → use `enabled` field
        """
```

`middleware.py` — FeatureFlagMiddleware:
```python
class FeatureFlagMiddleware(BaseHTTPMiddleware):
    """Injects X-Feature-Flags header into downstream requests."""
    async def dispatch(self, request: Request, call_next):
        user_id = request.state.user_id  # Set by OIDCAuthMiddleware
        active_flags = await self._store.get_active_flags_for_user(user_id)
        request.state.feature_flags = active_flags
        response = await call_next(request)
        return response
```

Admin endpoints (must be protected by admin role check):
- `POST /internal/v1/feature-flags/{flag_name}` — create/update flag
- `GET /internal/v1/feature-flags` — list all flags
- `DELETE /internal/v1/feature-flags/{flag_name}` — delete flag

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_flag_disabled_by_default | Unknown flag → `is_enabled()` returns False | unit |
| test_flag_allowlist_user | User in allowlist → True regardless of rollout% | unit |
| test_flag_rollout_50pct_deterministic | Same user+flag always gets same result | unit |
| test_flag_rollout_distributes_evenly | 50% rollout → ~50% of 1000 unique user IDs enabled | unit |
| test_admin_create_flag_returns_201 | POST /internal/v1/feature-flags/test → 201 | unit |

**Acceptance criteria**:
- [ ] FeatureFlagStore implements `is_enabled(flag_name, user_id)` with consistent hashing
- [ ] Admin endpoints require admin role (validated via JWT claims)
- [ ] Flags default to disabled (safe)
- [ ] 5 unit tests pass
- [ ] ruff + mypy pass

---

#### Validation Gate E
- [ ] `infra/synthetic/Dockerfile` builds with `docker build infra/synthetic/`
- [ ] `docker compose config` valid after adding pushgateway + synthetic services
- [ ] 5 feature flag unit tests pass
- [ ] ruff + mypy clean for api-gateway

---

## Cross-Cutting Concerns

### Contract Changes
- `libs/observability` gains new public symbols (`MLMetrics`, `create_ml_metrics`, `register_error_handlers`, `instrument_sqlalchemy_pool`) — backward compatible additions, no breaking changes
- `libs/messaging` gains done_callback behavior + lag polling — existing consumer API unchanged, behavior change only
- `libs/ml-clients` adapters gain optional `metrics=` parameter — all existing callers unaffected

### Migration Needs
None — no database schema changes in this plan.

### Event Flow Changes
None — no Kafka topic changes.

### Configuration Changes
New env vars (all optional with safe defaults):
- `SLACK_WEBHOOK_URL` — Slack webhook for critical alerts; empty = Slack disabled
- `SYNTHETIC_MONITOR_JWT` — JWT for synthetic monitor probes; empty = health-only probes
- `PUSHGATEWAY_URL` — default `http://pushgateway:9091`

All three must be added to `infra/compose/configs/docker.env.example` as empty placeholders.

### Documentation Updates
- `docs/libs/observability.md` — update Public API table (Wave A-2)
- `docs/libs/observability.md` — add `db_metrics.py` section
- `docs/services/alert.md` — note WebSocket active connections metric
- `docs/services/api-gateway.md` — add Feature Flags section

---

## Risk Assessment

**Critical path**: A-1 → (B-1 ∥ B-2 ∥ B-3 ∥ C-1 ∥ C-2) → B-3-02 (wire ML metrics into services) → D

**Highest risk**: T-C-2-01 (done_callback + sys.exit) — incorrect implementation causes restart loops. Risk mitigation: unit test `test_done_callback_on_graceful_stop_no_exit` explicitly verifies cancelled tasks don't trigger exit.

**Rollback strategy**: All changes are additive. The `metrics: MLMetrics | None = None` pattern ensures all adapter changes are backward compatible. Exception handlers only add behavior (500 → structured JSON) and cannot cause new failures. Consumer done_callback only triggers on unexpected crashes.

**Testing gaps**: Synthetic monitoring probes require a live stack to verify end-to-end. Unit tests verify the push mechanism but not actual probe execution against the platform. Mark Wave E-1 probe functions as `@pytest.mark.integration`.

---

## Task Dependency Summary

```
Wave A-1 (no deps)
    ├─→ Wave B-1 (embedding adapters)
    ├─→ Wave B-2 (extraction adapters)
    ├─→ Wave B-3 (other adapters) → T-B-3-02 (wire into services)
    ├─→ Wave C-1 (exception handlers)
    └─→ Wave C-2 (consumer lag + crash)

Wave C-3 (no deps — independent worker crash protection)
Wave D-1 (no deps — infra exporters)
Wave D-2 (no deps — SLO rules)
Wave D-3 (no deps — dashboards)
Wave D-4 (no deps — alert routing)

Wave E-1 → depends on D-1 (pushgateway)
Wave E-2 → independent
```

Recommended execution order:
1. Wave A-1 (unblocks everything)
2. Waves B-1, B-2, B-3, C-1, C-2, C-3, D-1, D-2, D-3, D-4 (all in parallel after A-1)
3. T-B-3-02 (after B-1+B-2+B-3 complete)
4. Waves E-1, E-2 (after D-1 complete)

---

## Compounding Notes

**New bug patterns identified**:
- BP-268: asyncio.create_task without done_callback → silent pipeline death (already added)
- BP-269: structlog OTel processor missing → trace_id never in logs (already added)
- BP-270: Prometheus regex s[1-9] excludes S10 (already added)
- BP-271: histogram_quantile without sum by le (already added)
- BP-272: ML adapter latency_ms=0 corrupts cost analytics (already added)
