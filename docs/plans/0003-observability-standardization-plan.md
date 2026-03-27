# PLAN-0003: Observability Standardization

> **Status**: in-progress
> **PRD**: N/A (cross-cutting improvement)
> **Created**: 2026-03-27
> **Updated**: 2026-03-27

---

## Overview

Standardize the observability layer (logging, metrics, tracing, health endpoints) across all active
microservices (S1-S5, S9) and add the monitoring infrastructure stack (Prometheus, Grafana, Tempo,
Loki, Alloy) to Docker Compose (both development/testing and production).

### Problem Statement

Investigation revealed:
- **S2 Market-Ingestion**: broken Prometheus middleware call (missing `metrics` arg), no `configure_logging()`, wrong tracing parameter name
- **S5 Content-Store**: never calls `configure_logging()`, `create_metrics()`, or `add_prometheus_middleware()` — only has custom metrics
- **S3 Market-Data**: missing explicit `observability` dependency in `pyproject.toml`
- **S1, S3, S4, S9**: inconsistent placement of observability init (some in `create_app`, some in `lifespan`; some have `/metrics` endpoint, some don't; request-ID middleware in some, not others)
- **No monitoring stack**: services emit metrics/traces but nothing collects or visualizes them

### Goals

1. Document the **canonical observability pattern** as an addendum to STANDARDS.md
2. Make every active service follow the same pattern (logging, metrics, tracing, health, request-ID)
3. Add Prometheus + Grafana + Tempo + Loki + Alloy to Docker Compose (both development/testing and production)

### Out of Scope

- S6, S7, S8, Alert: scaffolds with no real logic — observability wired when implemented (PLAN-0001-C)
- Custom domain metrics for S1, S3, S9 (nice-to-have, not blocking)
- Grafana dashboards and alerting rules (follow-up work)

---

## Sub-Plans and Dependency Graph

| Sub-Plan | Scope | Waves | Est. Effort |
|----------|-------|-------|-------------|
| **A** | Standards documentation | 1 | 30 min |
| **B** | Service standardization (S1-S5 + S9) | 2 | 60-90 min |
| **C** | Docker Compose monitoring stack | 1 | 45-60 min |

```
Sub-Plan A (standards doc)
    │
    └──→ Sub-Plan B Wave 1 (fix broken: S2, S5)
              │
              └──→ Sub-Plan B Wave 2 (standardize: S1, S3, S4, S9)

Sub-Plan C (docker compose) ──── independent, can run in parallel with A/B
```

**Critical path**: A → B-W1 → B-W2
**Parallelizable**: C can run alongside any wave

---

## Task Tracking

| Task ID | Wave | Title | Status |
|---------|------|-------|--------|
| T-A-1-01 | A-1 | Document canonical observability pattern in STANDARDS.md | done |
| T-B-1-01 | B-1 | Fix S2 market-ingestion observability | done |
| T-B-1-02 | B-1 | Wire S5 content-store standard observability | done |
| T-B-1-03 | B-1 | Add observability dep to S3 market-data pyproject.toml | done |
| T-B-2-01 | B-2 | Standardize S1 portfolio observability placement | pending |
| T-B-2-02 | B-2 | Standardize S3 market-data request-ID middleware | pending |
| T-B-2-03 | B-2 | Standardize S4 content-ingestion minor alignment | pending |
| T-B-2-04 | B-2 | Standardize S9 api-gateway request-ID middleware | pending |
| T-B-2-05 | B-2 | Ensure docker.env files have observability vars | pending |
| T-C-1-01 | C-1 | Add Prometheus + config to Docker Compose | pending |
| T-C-1-02 | C-1 | Add Grafana + provisioning to Docker Compose | pending |
| T-C-1-03 | C-1 | Add Tempo (tracing backend) to Docker Compose | pending |
| T-C-1-04 | C-1 | Add Loki (log aggregation) to Docker Compose | pending |
| T-C-1-05 | C-1 | Add Alloy (telemetry collector) to Docker Compose | pending |
| T-C-1-06 | C-1 | Wire OTLP endpoints in docker.env files | pending |

---

## Sub-Plan A: Standards Documentation

### Wave A-1: Document Canonical Observability Pattern ✅

**Goal**: Write the authoritative reference for how every service must wire observability, so `/implement` agents can follow it without making design decisions.
**Depends on**: none
**Estimated effort**: 30 min
**Status**: **DONE** — 2026-03-27 · docs-only wave · ruff clean
**Architecture layer**: docs

#### Tasks

#### T-A-1-01: Document canonical observability pattern in STANDARDS.md

**Type**: docs
**depends_on**: none
**blocks**: [T-B-1-01, T-B-1-02, T-B-2-01, T-B-2-02, T-B-2-03, T-B-2-04]
**Target files**:
- `docs/STANDARDS.md` (update §5 — replace/extend the observability section)

**What to build**:
Rewrite STANDARDS.md §5 to include the **exact canonical pattern** that every service must follow. The current §5 is a reference for the library API but doesn't specify the exact wiring sequence or placement rules. The new version must be a copy-paste template that eliminates all ambiguity.

**Content to document**:

1. **Observability init sequence** (mandatory order in `lifespan`):
   ```python
   # 1. LOGGING — always first, before any other code
   configure_logging(service_name=settings.service_name, level=settings.log_level, json=settings.log_json)
   logger = get_logger("service_module.app")

   # 2. METRICS — create and wire middleware
   metrics = create_metrics(service_name=settings.service_name)
   add_prometheus_middleware(app, metrics)
   app.state.metrics = metrics  # store for later use by custom metrics

   # 3. TRACING — conditional on otlp_endpoint
   if settings.otlp_endpoint:
       configure_tracing(service_name=settings.service_name, otlp_endpoint=settings.otlp_endpoint)
       add_otel_middleware(app)

   # 4+ Other infrastructure (DB, Valkey, storage, etc.)
   ```

2. **Config fields** (mandatory in every service's `config.py`):
   ```python
   service_name: str = "service-name"  # kebab-case, matches Docker service name
   log_level: str = "INFO"
   log_json: bool = True
   otlp_endpoint: str = ""
   ```

3. **Request-ID middleware** (mandatory in every service's `create_app()`):
   ```python
   class RequestIdMiddleware(BaseHTTPMiddleware):
       async def dispatch(self, request, call_next):
           request_id = request.headers.get("X-Request-ID") or common.ids.new_ulid()
           structlog.contextvars.bind_contextvars(request_id=request_id)
           response = await call_next(request)
           response.headers["X-Request-ID"] = str(request_id)
           structlog.contextvars.clear_contextvars()
           return response

   app.add_middleware(RequestIdMiddleware)
   ```

4. **Health endpoints** (mandatory, in route file or inline):
   - `GET /healthz` — liveness: always returns `{"status": "ok"}` (200)
   - `GET /readyz` — readiness: probes actual dependencies (DB, Valkey, storage); returns 503 if degraded
   - `GET /metrics` — Prometheus scrape endpoint via `prometheus_client.generate_latest()`

5. **Custom metrics pattern** (optional, per-service):
   - File: `services/{service}/src/{service}/infrastructure/metrics/prometheus.py`
   - Naming: `{s_code}_{subsystem}_{action}_total` (counters), `{s_code}_{subsystem}_{thing}_duration_seconds` (histograms), `{s_code}_{subsystem}_{thing}` (gauges)
   - Gauge polling: background task in lifespan, 30s default interval

6. **Docker env vars** (mandatory in every `configs/docker.env`):
   ```
   {PREFIX}_LOG_LEVEL=INFO
   {PREFIX}_LOG_JSON=true
   {PREFIX}_OTLP_ENDPOINT=
   ```

7. **pyproject.toml** (mandatory dependency):
   ```toml
   "observability",
   ```
   Direct `prometheus-client` or `structlog` only if custom metrics use them directly.

**Acceptance criteria**:
- [ ] STANDARDS.md §5 contains the exact canonical pattern (copy-paste ready)
- [ ] Pattern specifies: init order, config fields, request-ID middleware, health endpoints, /metrics, custom metrics, docker env vars, pyproject.toml
- [ ] No ambiguity about placement (lifespan vs create_app)
- [ ] Examples reference existing gold-standard services (S4 for custom metrics)

#### Pre-read (agent must read before starting)
- `docs/STANDARDS.md` (current §5)
- `services/content-ingestion/src/content_ingestion/app.py` (gold standard with custom metrics)
- `libs/observability/src/observability/__init__.py`

#### Validation Gate
- [x] STANDARDS.md updated with canonical pattern
- [x] No code changes (docs-only wave)

#### Regression Guardrails
- N/A (documentation only)

---

## Sub-Plan B: Service Standardization

### Wave B-1: Fix Broken Services (S2, S5) + Missing Dep (S3) ✅

**Goal**: Fix the two services with broken/missing observability wiring and the missing dependency declaration.
**Depends on**: Wave A-1 (standards doc defines the pattern)
**Estimated effort**: 45-60 min
**Status**: **DONE** — 2026-03-27 · S2: 317 tests pass, S5: 141 tests pass (excl. pre-existing DLQ test) · ruff + mypy clean
**Architecture layer**: infrastructure / application

#### Tasks

#### T-B-1-01: Fix S2 market-ingestion observability

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-B-2-05]
**Target files**:
- `services/market-ingestion/src/market_ingestion/app.py`
- `services/market-ingestion/src/market_ingestion/config.py`

**What to build**:
Rewrite the observability wiring in market-ingestion's `app.py` to follow the canonical pattern. Currently the service has 3 critical bugs: (1) `add_prometheus_middleware(app)` called without the required `metrics` argument, (2) no `configure_logging()` call, (3) tracing uses wrong parameter name `endpoint=` instead of `otlp_endpoint=` and defensive `getattr` despite the field existing in config.

**Current broken code** (`app.py`):
```python
# In lifespan — tracing with wrong param name + defensive getattr
otlp_endpoint = getattr(settings, "otlp_endpoint", None)
if otlp_endpoint:
    configure_tracing(service_name="market-ingestion", endpoint=otlp_endpoint)

# In create_app — broken middleware call
add_prometheus_middleware(app)  # MISSING metrics arg
```

**Required changes to `app.py`**:
1. Move ALL observability init into `lifespan`, remove from `create_app`
2. Add `configure_logging()` as first call in lifespan
3. Add `metrics = create_metrics(service_name=settings.service_name)` before middleware
4. Fix `add_prometheus_middleware(app, metrics)` — add `metrics` arg
5. Fix tracing: `configure_tracing(service_name=settings.service_name, otlp_endpoint=settings.otlp_endpoint)` — direct access, correct param name
6. Add `add_otel_middleware(app)` after tracing config
7. Convert inline request-ID middleware function to `RequestIdMiddleware` class pattern
8. Remove try/except wrappers around observability init (it should fail loud, not silently degrade)

**Required changes to `config.py`**:
1. Add `service_name: str = "market-ingestion"` field (currently hardcoded in app.py)
2. Fields `log_level`, `log_json`, `otlp_endpoint` already exist — no change needed

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_create_app_has_prometheus_middleware | App has prometheus middleware registered | unit |
| test_create_app_has_request_id_middleware | App has RequestIdMiddleware registered | unit |
| test_healthz_returns_ok | GET /healthz returns 200 | unit |
| test_readyz_returns_ok | GET /readyz returns 200 when deps healthy | unit |
| test_metrics_endpoint_returns_prometheus | GET /metrics returns prometheus format | unit |
- Minimum test count: 5
- Edge cases: missing X-Request-ID header (should generate ULID)
- Error paths: readyz with unhealthy DB

**Acceptance criteria**:
- [ ] `configure_logging()` called first in lifespan
- [ ] `create_metrics()` + `add_prometheus_middleware(app, metrics)` called correctly
- [ ] `configure_tracing()` uses `otlp_endpoint=` parameter (not `endpoint=`)
- [ ] No `getattr` defensive coding — direct `settings.otlp_endpoint` access
- [ ] RequestIdMiddleware class registered
- [ ] `GET /metrics` endpoint returns prometheus format
- [ ] `ruff check` + `mypy` pass on `services/market-ingestion/`
- [ ] All existing tests still pass + 5 new tests

---

#### T-B-1-02: Wire S5 content-store standard observability

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-B-2-05]
**Target files**:
- `services/content-store/src/content_store/app.py`
- `services/content-store/src/content_store/config.py`

**What to build**:
Content-store has excellent custom metrics (`infrastructure/metrics/prometheus.py`) but never calls the standard observability functions — no `configure_logging()`, no `create_metrics()`, no `add_prometheus_middleware()`, no `configure_tracing()`. Wire the standard pattern in the lifespan while preserving all existing custom metrics.

**Required changes to `app.py`**:
1. Add imports: `from observability import configure_logging, get_logger` and `from observability.metrics import add_prometheus_middleware, create_metrics` and `from observability.tracing import add_otel_middleware, configure_tracing`
2. In lifespan, add standard init sequence BEFORE existing infrastructure setup:
   - `configure_logging(service_name=settings.service_name, level=settings.log_level, json=settings.log_json)`
   - `metrics = create_metrics(service_name=settings.service_name)`
   - `add_prometheus_middleware(app, metrics)`
   - `app.state.metrics = metrics`
   - Conditional tracing setup
3. Add `RequestIdMiddleware` class if not present
4. Add explicit `GET /metrics` endpoint if not present
5. **Preserve**: all existing custom metrics, `_poll_metrics` background task, health endpoints

**Required changes to `config.py`**:
1. Add `service_name: str = "content-store"` if not present
2. Verify `log_level`, `log_json`, `otlp_endpoint` exist (they do based on investigation)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_create_app_has_prometheus_middleware | App has prometheus middleware registered | unit |
| test_create_app_has_request_id_middleware | RequestIdMiddleware is registered | unit |
| test_metrics_endpoint_returns_prometheus | GET /metrics returns prometheus text | unit |
| test_logging_configured_in_lifespan | configure_logging called before other init | unit |
- Minimum test count: 4
- Edge cases: custom metrics still work alongside standard metrics

**Acceptance criteria**:
- [ ] Standard observability init (logging, metrics, tracing) wired in lifespan
- [ ] Existing custom metrics (`s5_*`) still functional
- [ ] Existing `_poll_metrics` background task preserved
- [ ] RequestIdMiddleware registered
- [ ] `ruff check` + `mypy` pass on `services/content-store/`
- [ ] All existing tests still pass + 4 new tests

---

#### T-B-1-03: Add observability dep to S3 market-data pyproject.toml

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**:
- `services/market-data/pyproject.toml`

**What to build**:
Market-data imports from `observability` but doesn't declare it as an explicit dependency in `pyproject.toml`. It works via transitive dependency but violates the "explicit is better than implicit" principle and could break if the transitive path changes.

**Required change**:
Add `"observability"` to the `[project] dependencies` list.

**Downstream test impact**:
- None — adding a dependency doesn't break existing tests.

**Acceptance criteria**:
- [ ] `observability` listed in `services/market-data/pyproject.toml` dependencies
- [ ] `pip install -e services/market-data` still succeeds

#### Pre-read (agent must read before starting)
- `docs/STANDARDS.md` (the updated §5 from Wave A-1)
- `services/market-ingestion/src/market_ingestion/app.py` (current broken state)
- `services/market-ingestion/src/market_ingestion/config.py`
- `services/market-ingestion/src/market_ingestion/api/routes.py` (current health endpoints)
- `services/content-store/src/content_store/app.py` (current state)
- `services/content-store/src/content_store/config.py`
- `services/content-store/src/content_store/infrastructure/metrics/prometheus.py` (preserve this)
- `services/content-ingestion/src/content_ingestion/app.py` (gold standard reference)

#### Validation Gate
- [x] ruff check passes on `services/market-ingestion/` and `services/content-store/`
- [x] mypy passes on both services
- [x] Unit tests pass — 10 new tests (6 for S2 + 4 for S5)
- [x] All existing tests in both services still pass
- [x] No architecture violations (no domain → infra imports)

#### Regression Guardrails
- BP-010: Docker Compose healthcheck misconfiguration — verify `/healthz` endpoint still works for S2's compose healthcheck
- Ensure S5's `_poll_metrics` background task is not disrupted by new standard metrics init

---

### Wave B-2: Standardize Remaining Active Services (S1, S3, S4, S9)

**Goal**: Align the remaining 4 active services to the canonical pattern — move observability init to consistent location, add request-ID middleware where missing, ensure docker.env files are complete.
**Depends on**: Wave B-1
**Estimated effort**: 45-60 min
**Architecture layer**: infrastructure / application

#### Tasks

#### T-B-2-01: Standardize S1 portfolio observability placement

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**:
- `services/portfolio/src/portfolio/app.py`

**What to build**:
Portfolio currently creates metrics in `create_app()` (not lifespan) and doesn't have request-ID middleware. Move metrics init to lifespan for consistency and add `RequestIdMiddleware`.

**Current state** (from investigation):
- `configure_logging()` — in lifespan (correct)
- `configure_tracing()` — in lifespan (correct)
- `create_metrics()` + `add_prometheus_middleware()` — in `create_app()` (inconsistent, should be in lifespan)
- `add_otel_middleware()` — in `create_app()` (inconsistent)
- `/metrics` endpoint — manual in `create_app()` (correct, keep)
- Request-ID middleware — **MISSING**

**Required changes**:
1. Move `metrics = create_metrics(...)` and `add_prometheus_middleware(app, metrics)` from `create_app()` to lifespan (after logging, before tracing)
2. Move `add_otel_middleware(app)` to lifespan (after `configure_tracing()`)
3. Add `app.state.metrics = metrics` in lifespan
4. Add `RequestIdMiddleware` class and register in `create_app()`
5. Keep the manual `/metrics` endpoint as-is
6. Add `service_name` to config if not present (currently hardcoded as `settings.service_name`)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_request_id_middleware_generates_ulid | Missing X-Request-ID gets generated | unit |
| test_request_id_middleware_preserves_header | Existing X-Request-ID is preserved | unit |
- Minimum test count: 2

**Acceptance criteria**:
- [ ] Metrics + tracing init moved to lifespan
- [ ] RequestIdMiddleware registered
- [ ] All existing portfolio tests pass
- [ ] `ruff check` + `mypy` clean

---

#### T-B-2-02: Standardize S3 market-data request-ID middleware

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**:
- `services/market-data/src/market_data/app.py`

**What to build**:
Market-data has correct observability placement in lifespan but is missing request-ID middleware. Also remove try/except wrappers around observability init — these should fail loud during startup, not silently degrade.

**Required changes**:
1. Add `RequestIdMiddleware` class and register in `create_app()`
2. Remove try/except around `create_metrics()` and `add_prometheus_middleware()` calls — let startup fail if metrics can't init
3. Add `GET /metrics` endpoint if missing (via `prometheus_client.generate_latest()`)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_request_id_middleware_generates_ulid | Missing X-Request-ID gets generated | unit |
| test_request_id_middleware_preserves_header | Existing X-Request-ID is preserved | unit |
- Minimum test count: 2

**Acceptance criteria**:
- [ ] RequestIdMiddleware registered
- [ ] No try/except around observability init
- [ ] All existing market-data tests pass
- [ ] `ruff check` + `mypy` clean

---

#### T-B-2-03: Standardize S4 content-ingestion minor alignment

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**:
- `services/content-ingestion/src/content_ingestion/app.py`
- `services/content-ingestion/src/content_ingestion/config.py`

**What to build**:
Content-ingestion is the closest to the gold standard but has minor inconsistencies: verify `service_name` field exists in config (not hardcoded), ensure `/metrics` endpoint is explicit, verify `add_otel_middleware()` is called. This is a light-touch alignment task.

**Required changes** (if needed — verify first):
1. Add `service_name` to config if hardcoded in app.py
2. Add explicit `GET /metrics` endpoint if missing
3. Verify `app.state.metrics = metrics` is set (investigation says it is)

**Tests to write**:
- No new tests unless changes are made — existing test suite is comprehensive

**Acceptance criteria**:
- [ ] `service_name` comes from config, not hardcoded
- [ ] All existing tests pass
- [ ] `ruff check` + `mypy` clean

---

#### T-B-2-04: Standardize S9 api-gateway request-ID middleware

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**:
- `services/api-gateway/src/api_gateway/app.py`

**What to build**:
API-gateway has correct observability placement but is missing request-ID middleware. Since the gateway is the entry point for all external traffic, it's especially important that it generates/propagates request IDs.

**Required changes**:
1. Add `RequestIdMiddleware` class and register in `create_app()`
2. Add explicit `GET /metrics` endpoint if missing

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_request_id_middleware_generates_ulid | Missing X-Request-ID gets generated | unit |
| test_request_id_middleware_preserves_header | Existing X-Request-ID is preserved | unit |
- Minimum test count: 2

**Acceptance criteria**:
- [ ] RequestIdMiddleware registered
- [ ] All existing api-gateway tests pass
- [ ] `ruff check` + `mypy` clean

---

#### T-B-2-05: Ensure docker.env files have observability vars

**Type**: config
**depends_on**: [T-B-1-01, T-B-1-02]
**blocks**: [T-C-1-06]
**Target files**:
- `services/market-ingestion/configs/docker.env` (add `LOG_JSON`)
- `services/market-data/configs/docker.env` (add `LOG_LEVEL`, `LOG_JSON`)
- `services/content-ingestion/configs/docker.env` (create or update with observability vars)
- `services/content-store/configs/docker.env` (create or update with observability vars)
- `services/api-gateway/configs/docker.env` (create or update with observability vars)

**What to build**:
Ensure every active service's `docker.env` (or `docker.env.example`) has the three mandatory observability env vars: `{PREFIX}_LOG_LEVEL`, `{PREFIX}_LOG_JSON`, `{PREFIX}_OTLP_ENDPOINT`.

**Required changes per service**:
| Service | Prefix | Missing Vars |
|---------|--------|-------------|
| market-ingestion | MARKET_INGESTION_ | LOG_JSON |
| market-data | MARKET_DATA_ | LOG_LEVEL, LOG_JSON |
| portfolio | PORTFOLIO_ | none (already complete) |
| content-ingestion | CONTENT_INGESTION_ | verify all three exist |
| content-store | CONTENT_STORE_ | verify all three exist |
| api-gateway | API_GATEWAY_ | verify all three exist |

**Acceptance criteria**:
- [ ] All 6 active services have `LOG_LEVEL`, `LOG_JSON`, `OTLP_ENDPOINT` in their docker.env
- [ ] Values are defaults: `LOG_LEVEL=INFO`, `LOG_JSON=true`, `OTLP_ENDPOINT=` (blank)

#### Pre-read (agent must read before starting)
- `docs/STANDARDS.md` (the updated §5 from Wave A-1)
- `services/portfolio/src/portfolio/app.py`
- `services/market-data/src/market_data/app.py`
- `services/content-ingestion/src/content_ingestion/app.py`
- `services/api-gateway/src/api_gateway/app.py`
- All `configs/docker.env` files for the 6 services

#### Validation Gate
- [ ] ruff check passes on all modified services
- [ ] mypy passes on all modified services
- [ ] Unit tests pass — minimum 6 new tests (2 each for S1, S3, S9)
- [ ] All existing tests across all services still pass
- [ ] All docker.env files have the 3 mandatory observability vars

#### Regression Guardrails
- BP-010: Docker Compose healthcheck — verify services still start with `docker compose --profile infra up`
- Ensure no breaking changes to existing API routes or health endpoints

---

## Sub-Plan C: Docker Compose Monitoring Stack

### Wave C-1: Add Prometheus + Grafana + Tempo + Loki + Alloy

**Goal**: Add the full monitoring infrastructure to Docker Compose so services' metrics, traces, and logs can be collected and visualized locally.
**Depends on**: none (can run in parallel with Sub-Plans A/B)
**Estimated effort**: 45-60 min
**Architecture layer**: infrastructure

#### Tasks

#### T-C-1-01: Add Prometheus + config to Docker Compose

**Type**: config
**depends_on**: none
**blocks**: [T-C-1-02, T-C-1-05]
**Target files**:
- `infra/compose/docker-compose.yml` (add prometheus service)
- `infra/prometheus/prometheus.yml` (create — scrape config)

**What to build**:
Add Prometheus to Docker Compose with a scrape configuration that targets all service `/metrics` endpoints. Prometheus is the metrics backend — it scrapes `/metrics` from each service on a schedule and stores time-series data.

**Docker Compose service definition**:
```yaml
prometheus:
  image: prom/prometheus:v3.2.1
  profiles: [infra, all]
  ports:
    - "9090:9090"
  volumes:
    - ../prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    - prometheus_data:/prometheus
  depends_on:
    portfolio:
      condition: service_healthy
  healthcheck:
    test: ["CMD", "wget", "--spider", "-q", "http://localhost:9090/-/healthy"]
    interval: 15s
    timeout: 5s
    retries: 3
    start_period: 10s
```

**Prometheus config** (`infra/prometheus/prometheus.yml`):
```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: "portfolio"
    static_configs:
      - targets: ["portfolio:8000"]
    metrics_path: /metrics

  - job_name: "market-ingestion"
    static_configs:
      - targets: ["market-ingestion:8002"]
    metrics_path: /metrics

  - job_name: "market-data"
    static_configs:
      - targets: ["market-data:8003"]
    metrics_path: /metrics

  - job_name: "content-ingestion"
    static_configs:
      - targets: ["content-ingestion:8004"]
    metrics_path: /metrics

  - job_name: "content-store"
    static_configs:
      - targets: ["content-store:8005"]
    metrics_path: /metrics

  - job_name: "api-gateway"
    static_configs:
      - targets: ["api-gateway:8009"]
    metrics_path: /metrics
```

**Note**: Service ports are the internal container ports (not host-mapped). Verify actual ports from each service's config before finalizing.

**Acceptance criteria**:
- [ ] `prometheus` service defined in docker-compose.yml with `infra` profile
- [ ] `prometheus_data` volume declared
- [ ] `infra/prometheus/prometheus.yml` with scrape targets for all 6 active services
- [ ] Prometheus starts and reaches healthy state
- [ ] Prometheus UI accessible at `http://localhost:9090`

---

#### T-C-1-02: Add Grafana + provisioning to Docker Compose

**Type**: config
**depends_on**: [T-C-1-01]
**blocks**: none
**Target files**:
- `infra/compose/docker-compose.yml` (add grafana service)
- `infra/grafana/provisioning/datasources/datasources.yml` (create — auto-provision Prometheus + Tempo + Loki)

**What to build**:
Add Grafana to Docker Compose with auto-provisioned datasources for Prometheus (metrics), Tempo (traces), and Loki (logs). Grafana is the visualization layer — dashboards and alerting are out of scope for this plan but the datasources must be wired.

**Docker Compose service definition**:
```yaml
grafana:
  image: grafana/grafana:11.6.0
  profiles: [infra, all]
  ports:
    - "3000:3000"
  environment:
    GF_SECURITY_ADMIN_USER: admin
    GF_SECURITY_ADMIN_PASSWORD: admin
    GF_AUTH_ANONYMOUS_ENABLED: "true"
    GF_AUTH_ANONYMOUS_ORG_ROLE: Admin
  volumes:
    - ../grafana/provisioning:/etc/grafana/provisioning:ro
    - grafana_data:/var/lib/grafana
  depends_on:
    prometheus:
      condition: service_healthy
  healthcheck:
    test: ["CMD", "wget", "--spider", "-q", "http://localhost:3000/api/health"]
    interval: 15s
    timeout: 5s
    retries: 3
    start_period: 15s
```

**Datasource provisioning** (`infra/grafana/provisioning/datasources/datasources.yml`):
```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false

  - name: Tempo
    type: tempo
    access: proxy
    url: http://tempo:3200
    editable: false
    jsonData:
      tracesToMetrics:
        datasourceUid: prometheus
      serviceMap:
        datasourceUid: prometheus
      nodeGraph:
        enabled: true

  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    editable: false
    jsonData:
      derivedFields:
        - datasourceUid: tempo
          matcherRegex: '"trace_id":"(\w+)"'
          name: TraceID
          url: "$${__value.raw}"
```

**Acceptance criteria**:
- [ ] `grafana` service defined in docker-compose.yml with `infra` profile
- [ ] `grafana_data` volume declared
- [ ] Datasource provisioning file created with Prometheus, Tempo, Loki sources
- [ ] Grafana UI accessible at `http://localhost:3000` (admin/admin)
- [ ] Anonymous access enabled for local dev convenience

---

#### T-C-1-03: Add Tempo (tracing backend) to Docker Compose

**Type**: config
**depends_on**: none
**blocks**: [T-C-1-02]
**Target files**:
- `infra/compose/docker-compose.yml` (add tempo service)
- `infra/tempo/tempo.yml` (create — Tempo configuration)

**What to build**:
Add Grafana Tempo to Docker Compose as the distributed tracing backend. Tempo receives OTLP gRPC spans from services (via Alloy or direct) and stores them. It provides a query API used by Grafana for trace visualization.

**Docker Compose service definition**:
```yaml
tempo:
  image: grafana/tempo:2.7.2
  profiles: [infra, all]
  command: ["-config.file=/etc/tempo.yml"]
  ports:
    - "3200:3200"   # Tempo query API (Grafana connects here)
    - "4317:4317"   # OTLP gRPC receiver
    - "4318:4318"   # OTLP HTTP receiver
  volumes:
    - ../tempo/tempo.yml:/etc/tempo.yml:ro
    - tempo_data:/var/tempo
  healthcheck:
    test: ["CMD", "wget", "--spider", "-q", "http://localhost:3200/ready"]
    interval: 15s
    timeout: 5s
    retries: 3
    start_period: 10s
```

**Tempo config** (`infra/tempo/tempo.yml`):
```yaml
server:
  http_listen_port: 3200

distributor:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317
        http:
          endpoint: 0.0.0.0:4318

storage:
  trace:
    backend: local
    local:
      path: /var/tempo/traces
    wal:
      path: /var/tempo/wal

metrics_generator:
  storage:
    path: /var/tempo/generator/wal
  traces_storage:
    path: /var/tempo/generator/traces
```

**Acceptance criteria**:
- [ ] `tempo` service defined in docker-compose.yml with `infra` profile
- [ ] `tempo_data` volume declared
- [ ] Tempo config accepts OTLP gRPC on port 4317
- [ ] Tempo query API accessible at `http://localhost:3200`

---

#### T-C-1-04: Add Loki (log aggregation) to Docker Compose

**Type**: config
**depends_on**: none
**blocks**: [T-C-1-02]
**Target files**:
- `infra/compose/docker-compose.yml` (add loki service)
- `infra/loki/loki-config.yml` (create — Loki configuration)

**What to build**:
Add Grafana Loki to Docker Compose as the log aggregation backend. Loki receives structured JSON logs from Alloy (which tails service stdout) and makes them queryable via LogQL in Grafana. Uses local filesystem storage for dev.

**Docker Compose service definition**:
```yaml
loki:
  image: grafana/loki:3.5.0
  profiles: [infra, all]
  command: ["-config.file=/etc/loki/local-config.yml"]
  ports:
    - "3100:3100"
  volumes:
    - ../loki/loki-config.yml:/etc/loki/local-config.yml:ro
    - loki_data:/loki
  healthcheck:
    test: ["CMD", "wget", "--spider", "-q", "http://localhost:3100/ready"]
    interval: 15s
    timeout: 5s
    retries: 5
    start_period: 15s
```

**Loki config** (`infra/loki/loki-config.yml`):
```yaml
auth_enabled: false

server:
  http_listen_port: 3100

common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: "2024-01-01"
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

limits_config:
  reject_old_samples: true
  reject_old_samples_max_age: 168h
  allow_structured_metadata: true
```

**Acceptance criteria**:
- [ ] `loki` service defined in docker-compose.yml with `infra` profile
- [ ] `loki_data` volume declared
- [ ] Loki config uses local filesystem storage
- [ ] Loki ready endpoint accessible at `http://localhost:3100/ready`

---

#### T-C-1-05: Add Alloy (telemetry collector) to Docker Compose

**Type**: config
**depends_on**: [T-C-1-01, T-C-1-03, T-C-1-04]
**blocks**: [T-C-1-06]
**Target files**:
- `infra/compose/docker-compose.yml` (add alloy service)
- `infra/alloy/config.alloy` (create — Alloy pipeline config)

**What to build**:
Add Grafana Alloy to Docker Compose as the unified telemetry collector. Alloy replaces the need for separate Promtail (logs), OTel Collector (traces), and custom scrapers. It:
1. Tails Docker container logs and forwards to Loki
2. Receives OTLP traces from services and forwards to Tempo
3. Optionally scrapes Prometheus metrics (but Prometheus already does this, so Alloy focuses on logs + traces)

Services send OTLP traces to Alloy (port 4317), which forwards to Tempo. Alloy tails Docker logs via the Docker socket and pushes to Loki.

**Docker Compose service definition**:
```yaml
alloy:
  image: grafana/alloy:v1.8.3
  profiles: [infra, all]
  command:
    - run
    - /etc/alloy/config.alloy
    - --storage.path=/var/lib/alloy/data
    - --server.http.listen-addr=0.0.0.0:12345
    - --stability.level=generally-available
  ports:
    - "12345:12345"  # Alloy UI
    - "4317"         # OTLP gRPC (internal only, services connect via Docker network)
    - "4318"         # OTLP HTTP
  volumes:
    - ../alloy/config.alloy:/etc/alloy/config.alloy:ro
    - /var/run/docker.sock:/var/run/docker.sock:ro
    - alloy_data:/var/lib/alloy/data
  depends_on:
    loki:
      condition: service_healthy
    tempo:
      condition: service_healthy
  healthcheck:
    test: ["CMD", "wget", "--spider", "-q", "http://localhost:12345/ready"]
    interval: 15s
    timeout: 5s
    retries: 3
    start_period: 10s
```

**Alloy config** (`infra/alloy/config.alloy`):
```alloy
// ── OTLP receiver: services send traces here ──
otelcol.receiver.otlp "default" {
  grpc {
    endpoint = "0.0.0.0:4317"
  }
  http {
    endpoint = "0.0.0.0:4318"
  }
  output {
    traces = [otelcol.exporter.otlp.tempo.input]
  }
}

// ── Forward traces to Tempo ──
otelcol.exporter.otlp "tempo" {
  client {
    endpoint = "tempo:4317"
    tls {
      insecure = true
    }
  }
}

// ── Docker log discovery ──
discovery.docker "containers" {
  host = "unix:///var/run/docker.sock"
  filter {
    name = "name"
    values = ["worldview-portfolio-1", "worldview-market-ingestion-1", "worldview-market-data-1",
              "worldview-content-ingestion-1", "worldview-content-store-1", "worldview-api-gateway-1"]
  }
}

// ── Tail container logs ──
loki.source.docker "containers" {
  host = "unix:///var/run/docker.sock"
  targets = discovery.docker.containers.targets
  forward_to = [loki.write.default.receiver]
  relabel_rules = loki.relabel.docker.rules
}

// ── Add service name label from container name ──
loki.relabel "docker" {
  forward_to = []
  rule {
    source_labels = ["__meta_docker_container_name"]
    target_label  = "service"
    regex         = "/(.*)"
  }
}

// ── Push logs to Loki ──
loki.write "default" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
```

**Acceptance criteria**:
- [ ] `alloy` service defined in docker-compose.yml with `infra` profile
- [ ] `alloy_data` volume declared
- [ ] Alloy config receives OTLP traces and forwards to Tempo
- [ ] Alloy config tails Docker logs and pushes to Loki
- [ ] Alloy UI accessible at `http://localhost:12345`
- [ ] Docker socket mounted (read-only) for log tailing

---

#### T-C-1-06: Wire OTLP endpoints in docker.env files

**Type**: config
**depends_on**: [T-B-2-05, T-C-1-05]
**blocks**: none
**Target files**:
- All 6 service `configs/docker.env` files

**What to build**:
Set the `OTLP_ENDPOINT` env var in each service's docker.env to point to Alloy's OTLP gRPC receiver (`http://alloy:4317`). This enables tracing when running in Docker Compose. The value remains blank for local development outside Docker.

**Required changes**:
| Service | Env Var | Value |
|---------|---------|-------|
| portfolio | `PORTFOLIO_OTLP_ENDPOINT` | `http://alloy:4317` |
| market-ingestion | `MARKET_INGESTION_OTLP_ENDPOINT` | `http://alloy:4317` |
| market-data | `MARKET_DATA_OTLP_ENDPOINT` | `http://alloy:4317` |
| content-ingestion | `CONTENT_INGESTION_OTLP_ENDPOINT` | `http://alloy:4317` |
| content-store | `CONTENT_STORE_OTLP_ENDPOINT` | `http://alloy:4317` |
| api-gateway | `API_GATEWAY_OTLP_ENDPOINT` | `http://alloy:4317` |

**Acceptance criteria**:
- [ ] All 6 docker.env files set OTLP_ENDPOINT to `http://alloy:4317`
- [ ] Services connect to Alloy for trace export when running in Docker Compose

#### Pre-read (agent must read before starting)
- `infra/compose/docker-compose.yml` (current state)
- All `configs/docker.env` files
- Grafana Alloy documentation for config syntax

#### Validation Gate
- [ ] `docker compose -f infra/compose/docker-compose.yml config` validates without errors
- [ ] All new config files are syntactically valid
- [ ] `docker compose --profile infra up -d` starts all infrastructure including monitoring
- [ ] Prometheus targets page shows all services
- [ ] Grafana loads with pre-provisioned datasources
- [ ] Tempo accepts OTLP on port 4317
- [ ] Loki ready on port 3100

#### Regression Guardrails
- BP-010: Ensure existing services still start correctly with new monitoring stack
- Verify Docker socket mount doesn't cause permission issues on macOS
- Verify port conflicts: 3000 (Grafana) doesn't conflict with frontend dev server (Vite typically uses 5173)

---

## Cross-Cutting Concerns

### Contract Changes
- None — this plan doesn't modify Avro schemas, API contracts, or Kafka topics

### Migration Needs
- None — no database schema changes

### Event Flow Changes
- None — no new Kafka topics or changed event semantics

### Configuration Changes
- **New env vars**: `{PREFIX}_LOG_LEVEL`, `{PREFIX}_LOG_JSON`, `{PREFIX}_OTLP_ENDPOINT` (standardized across all services)
- **New Docker services**: prometheus, grafana, tempo, loki, alloy
- **New Docker volumes**: prometheus_data, grafana_data, tempo_data, loki_data, alloy_data
- **New config directories**: `infra/prometheus/`, `infra/grafana/`, `infra/tempo/`, `infra/loki/`, `infra/alloy/`

### Documentation Updates
- `docs/STANDARDS.md` §5 — rewritten with canonical observability pattern (Wave A-1)
- `docs/MASTER_PLAN.md` §11 — should be updated to reference the monitoring stack (Alloy instead of separate collectors)
- Service `.claude-context.md` files — update to note observability is standardized

---

## Risk Assessment

### Critical Path
**A → B-W1 → B-W2** — standards doc must be written first, then broken services fixed, then remaining services aligned. Sub-Plan C is independent.

### Highest Risk
**Wave B-1 (T-B-1-01)**: Rewriting S2 market-ingestion's `app.py` — this is a mature service with scheduler, worker, and dispatcher processes. The observability rewrite must not break the existing lifespan logic that wires DB, Valkey, storage, and Kafka.

### Rollback Strategy
- Each wave is a single commit — `git revert` reverts the entire wave
- Sub-Plan C is purely additive (new Docker services) — removing the monitoring stack is trivial
- Service changes (Sub-Plan B) are isolated per service — one service's revert doesn't affect others

### Testing Gaps
- **Docker Compose integration**: no automated test verifies the full monitoring stack starts. Manual verification required after Wave C-1.
- **Alloy log tailing**: Docker socket access may behave differently on Linux vs macOS. Manual testing recommended.
- **OTLP trace end-to-end**: verifying traces flow from service → Alloy → Tempo → Grafana requires manual inspection in Grafana UI
