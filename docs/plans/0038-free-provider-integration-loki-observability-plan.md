---
id: PLAN-0038
title: Free Provider Integration + Loki API Usage Observability
prd: investigation-2026-04-25
status: completed
created: 2026-04-25
updated: 2026-04-26
service: market-ingestion
waves: 5
---

# PLAN-0038 — Free Provider Integration + Loki API Usage Observability

## Overview

This plan integrates two free data provider adapters (Finnhub, Yahoo Finance) to reduce EODHD credit consumption, and establishes a **shared, provider-generic observability layer** so Loki and Prometheus can track API usage across ALL providers (EODHD, Finnhub, Yahoo Finance, and future additions like SEC EDGAR) with a unified event schema.

**Background** (from `/investigate` sessions 2026-04-25):
- EODHD credit costs: `FUNDAMENTALS` = 10 credits, `INTRADAY/MACRO/ECONOMIC/NEWS/INSIDER` = 5 credits, `OHLCV/QUOTES` = 1 credit (defined in `domain/freshness.py:EODHD_CREDIT_COST`).
- Yahoo Finance (yfinance): zero cost, covers `OHLCV` (daily, weekly, monthly) — stub adapter exists, not implemented.
- Finnhub: free tier 60 req/min, covers `NEWS_SENTIMENT`, `EARNINGS_CALENDAR`, `INSIDER_TRANSACTIONS` — config key `finnhub_api_key` exists, no adapter class.
- Loki: running at port 3100 via Grafana Alloy (Docker socket); `logs-explorer.json` dashboard exists. No adapter emits `symbol`/`timeframe`/`bars_returned` in logs today.
- Prometheus: all existing metrics are EODHD-specific (`s2_eodhd_*`). Cross-provider Prometheus queries are impossible without a shared metric set.

**Architecture decision** (from `/investigate` 2026-04-25):
- EODHD-specific metrics (`s2_eodhd_quota_*`, `s2_eodhd_circuit_breaker_state`, `s2_eodhd_daily_budget_headroom`) stay in `infrastructure/metrics/eodhd.py` — quota and circuit breaker are EODHD-only concepts.
- Generic request metrics live in a new `infrastructure/metrics/providers.py` module (`s2_mi_provider_*`).
- A new `BaseProviderAdapter` base class in `infrastructure/adapters/providers/base.py` provides a `_record_api_call()` method that all concrete adapters call. This guarantees every adapter emits the event and increments generic metrics without per-adapter boilerplate.

---

## Dependency Graph

```
Wave A-1 (Structured logging + Loki dashboard)
    ↓
Wave A-2 (Finnhub adapter — NEWS/EARNINGS/INSIDER)  ← can run in parallel with A-3
Wave A-3 (Yahoo Finance adapter — OHLCV daily/weekly/monthly)   ← can run in parallel with A-2
    ↓
Wave A-4 (Provider routing strategy + Prometheus timeframe label)
    ↓
Wave A-5 (Zero-bar failover — Valkey streak counter + _fallback_provider() chain)

Appendix A (Primary Provider Reclaim Worker + Intraday Provider Research — deferred, pick up separately)
```

---

## Codebase State Verification

| PRD Reference | Type | File | Current State | Target State | Delta |
|---|---|---|---|---|---|
| `ProviderFetchResult.bars_returned` | dataclass field | `application/ports/adapters.py` | No `bars_returned` field | Add `bars_returned: int = 0` | Add field |
| `provider_api_call` log event | structured log | `adapters/providers/eodhd.py` | `_get()` logs `eodhd_connection_error`, `eodhd_rate_limited` only | Emit `provider_api_call` on every success | Add call |
| `FinnhubProviderAdapter` | class | `adapters/providers/finnhub.py` | Does not exist | New class implementing `ProviderAdapter` | Create |
| `Provider.FINNHUB` | enum value | `domain/enums.py` | Does not exist | `FINNHUB = "finnhub"` | Add |
| `YahooFinanceProviderAdapter` | class | `adapters/providers/yahoo.py` | Stub — raises `ProviderUnavailable` | Real impl via `yfinance` | Implement |
| `yfinance` dep | pyproject.toml | `pyproject.toml` | Not listed | Add `yfinance>=0.2,<1` | Add |
| `finnhub-python` dep | pyproject.toml | `pyproject.toml` | Not listed | Add `finnhub-python>=2.4,<3` | Add |
| `api-usage-analytics.json` | Grafana dashboard | `infra/grafana/dashboards/` | Does not exist | New Loki-based dashboard | Create |
| `infrastructure/metrics/providers.py` | New file | does not exist | New generic provider metrics (`s2_mi_provider_*`) | Create |
| `infrastructure/adapters/providers/base.py` | New file | does not exist | `BaseProviderAdapter` with `_record_api_call/rate_limited/error()` + `_sanitize_url_slug()` | Create |
| Routing in `execute_task.py` | Use case | adapter always EODHD (`registry.get(task.provider)`) | `_preferred_provider()` overrides adapter at execution time | Modify line 116 |

---

## Wave A-1: Generic Observability Foundation — `BaseProviderAdapter` + Shared Metrics + Loki Dashboard ✅

**Status**: **DONE** — 2026-04-25 · 88 unit tests pass · ruff + mypy clean

**Goal**: Establish a shared observability layer that works across ALL providers. This includes:
1. Generic Prometheus metrics (`s2_mi_provider_*`) in a new `providers.py` metrics module
2. A `BaseProviderAdapter` base class with `_record_api_call()` so every adapter emits the `provider_api_call` structlog event AND increments the shared metrics with zero per-adapter boilerplate
3. Update `EODHDProviderAdapter` to extend `BaseProviderAdapter` and call `_record_api_call()` after each fetch
4. A Loki+Prometheus Grafana dashboard for cross-provider API usage analytics

**Depends on**: none
**Estimated effort**: 45–60 minutes
**Architecture layer**: infrastructure + observability

### Pre-read (agent must read before starting)
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/eodhd.py` (563 lines) — understand all `fetch_*` methods and `_get()` helper
- `services/market-ingestion/src/market_ingestion/application/ports/adapters.py` — `ProviderAdapter` ABC and `ProviderFetchResult`
- `services/market-ingestion/src/market_ingestion/infrastructure/metrics/eodhd.py` — existing EODHD metrics (DO NOT modify)
- `services/market-ingestion/src/market_ingestion/domain/freshness.py` — `EODHD_CREDIT_COST` dict (reuse in adapter)
- `infra/grafana/dashboards/logs-explorer.json` — reference for Loki panel structure

### Tasks

#### T-A-1-01: Add `bars_returned` to `ProviderFetchResult`

**Type**: impl
**depends_on**: none
**blocks**: [T-A-1-02]
**Target files**: `services/market-ingestion/src/market_ingestion/application/ports/adapters.py`

**What to build**: Add `bars_returned: int = 0` field to the `ProviderFetchResult` frozen dataclass. This field carries the number of records/bars returned — zero by default (for scalar datasets like fundamentals), populated by adapters for list datasets (OHLCV, news, etc.).

**Acceptance criteria**:
- [ ] `ProviderFetchResult` gains `bars_returned: int = 0` with default
- [ ] All existing constructors continue to compile (default arg — no forced migration)
- [ ] mypy passes

---

#### T-A-1-02: Create `infrastructure/metrics/providers.py` — generic provider metrics

**Type**: impl
**depends_on**: none
**blocks**: [T-A-1-03]
**Target files**: `services/market-ingestion/src/market_ingestion/infrastructure/metrics/providers.py` (NEW)

**What to build**: A new metrics module with provider-agnostic Prometheus metrics and a single `record_provider_request()` helper. EODHD-specific metrics (`s2_eodhd_*` — quota, CB, budget) stay untouched in `eodhd.py`.

**Metrics to define**:
```python
# s2_mi_* = service-2 market-ingestion, provider-generic
s2_mi_provider_requests_total: prom.Counter = prom.Counter(
    "s2_mi_provider_requests_total",
    "Total provider API requests",
    labelnames=["provider", "dataset_type", "timeframe", "status_code"],
)
s2_mi_provider_credits_total: prom.Counter = prom.Counter(
    "s2_mi_provider_credits_total",
    "Total provider credits consumed (0 for free providers)",
    labelnames=["provider", "dataset_type"],
)
s2_mi_provider_latency_seconds: prom.Histogram = prom.Histogram(
    "s2_mi_provider_latency_seconds",
    "Provider API request latency in seconds",
    labelnames=["provider", "dataset_type"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)
s2_mi_provider_rate_limited_total: prom.Counter = prom.Counter(
    "s2_mi_provider_rate_limited_total",
    "Total HTTP 429 responses from any provider",
    labelnames=["provider"],
)
s2_mi_provider_errors_total: prom.Counter = prom.Counter(
    "s2_mi_provider_errors_total",
    "Total provider errors",
    labelnames=["provider", "reason"],
)
```

**Helper functions** (three — one per `_record_*` method in `BaseProviderAdapter`):
```python
def record_provider_request(
    *,
    provider: str,
    dataset_type: str,
    timeframe: str,
    status_code: int,
    duration_seconds: float,
    credit_cost: int = 0,
) -> None:
    """Record a completed provider API request in all shared counters."""
    s2_mi_provider_requests_total.labels(
        provider=provider,
        dataset_type=dataset_type,
        timeframe=timeframe,
        status_code=str(status_code),
    ).inc()
    if credit_cost > 0:
        s2_mi_provider_credits_total.labels(provider=provider, dataset_type=dataset_type).inc(credit_cost)
    if duration_seconds > 0.0:
        s2_mi_provider_latency_seconds.labels(provider=provider, dataset_type=dataset_type).observe(duration_seconds)


def record_provider_rate_limited(*, provider: str) -> None:
    """Increment the rate-limited counter for a provider (HTTP 429 or equivalent)."""
    s2_mi_provider_rate_limited_total.labels(provider=provider).inc()


def record_provider_error(*, provider: str, reason: str) -> None:
    """Increment the provider error counter with a short reason label."""
    s2_mi_provider_errors_total.labels(provider=provider, reason=reason).inc()
```

**Acceptance criteria**:
- [ ] 5 metrics defined with correct Prometheus types and label dimensions
- [ ] `record_provider_request()` increments all applicable metrics
- [ ] `record_provider_rate_limited()` increments `s2_mi_provider_rate_limited_total`
- [ ] `record_provider_error()` increments `s2_mi_provider_errors_total`
- [ ] `credit_cost=0` skips the credits counter (free providers don't pollute credit metrics)
- [ ] mypy passes

---

#### T-A-1-03: Create `infrastructure/adapters/providers/base.py` — `BaseProviderAdapter`

**Type**: impl
**depends_on**: [T-A-1-01, T-A-1-02]
**blocks**: [T-A-1-04]
**Target files**: `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/base.py` (NEW)

**What to build**: A concrete base class extending `ProviderAdapter` with three observability methods and a URL-sanitizer helper. All concrete adapters extend this class instead of `ProviderAdapter` directly.

```python
"""BaseProviderAdapter — shared observability mixin for all provider adapters."""
from __future__ import annotations

from urllib.parse import urlparse

from market_ingestion.application.ports.adapters import ProviderAdapter
from market_ingestion.infrastructure.metrics.providers import (
    record_provider_error,
    record_provider_rate_limited,
    record_provider_request,
)
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)


class BaseProviderAdapter(ProviderAdapter):
    """Extends ProviderAdapter with shared observability.

    Every concrete adapter MUST extend this class and call the appropriate
    _record_* method on every completed fetch (success or error).

    Guarantees:
    - A ``provider_api_call`` structlog event for every fetch outcome
    - Generic Prometheus metrics (s2_mi_provider_*) incremented uniformly
    - Loki and Prometheus dashboards work across all providers
    """

    @staticmethod
    def _sanitize_url_slug(url: str) -> str:
        """Extract a safe endpoint label — no query params, no secrets.

        Examples
        --------
            "https://finnhub.io/api/v1/company-news?token=SECRET" → "company-news"
            "https://eodhd.com/api/eod/AAPL.US?api_token=SECRET"  → "eod"
        """
        path = urlparse(url).path
        segments = [p for p in path.split("/") if p and p not in ("api", "v1")]
        return segments[0] if segments else "unknown"

    def _record_api_call(
        self,
        *,
        dataset_type: str,
        symbol: str,
        exchange: str = "",
        timeframe: str = "",
        bars_returned: int = 0,
        latency_ms: int,
        credit_cost: int = 0,
        status: str = "success",
        status_code: int = 200,
    ) -> None:
        """Emit provider_api_call log event and increment shared Prometheus metrics.

        Args:
            dataset_type:  DatasetType.value string (e.g. "ohlcv", "news_sentiment")
            symbol:        Raw ticker symbol (e.g. "AAPL") — never includes API key
            exchange:      Exchange code (e.g. "US") or empty string
            timeframe:     Timeframe string (e.g. "1d", "1h") or "" for non-OHLCV
            bars_returned: Count of records returned (bars, articles, events, ...)
            latency_ms:    Wall-clock duration of the API call in milliseconds
            credit_cost:   Provider credits consumed (0 for free providers)
            status:        "success" | "rate_limited" | "error"
            status_code:   HTTP status code (200 on success)
        """
        logger.info(
            "provider_api_call",
            provider=self.provider.value,
            dataset_type=dataset_type,
            symbol=symbol,
            exchange=exchange,
            timeframe=timeframe,
            bars_returned=bars_returned,
            latency_ms=latency_ms,
            credit_cost=credit_cost,
            status=status,
        )
        record_provider_request(
            provider=self.provider.value,
            dataset_type=dataset_type,
            timeframe=timeframe,
            status_code=status_code,
            duration_seconds=latency_ms / 1000.0,
            credit_cost=credit_cost,
        )

    def _record_rate_limited(self, *, endpoint: str = "") -> None:
        """Emit rate-limit log and increment s2_mi_provider_rate_limited_total."""
        logger.warning(
            "provider_rate_limited",
            provider=self.provider.value,
            endpoint=endpoint,
        )
        record_provider_rate_limited(provider=self.provider.value)

    def _record_error(self, *, reason: str, endpoint: str = "") -> None:
        """Emit error log and increment s2_mi_provider_errors_total."""
        logger.error(
            "provider_error",
            provider=self.provider.value,
            endpoint=endpoint,
            reason=reason,
        )
        record_provider_error(provider=self.provider.value, reason=reason)
```

**Acceptance criteria**:
- [ ] `BaseProviderAdapter` extends `ProviderAdapter` (still abstract — no concrete methods)
- [ ] `_sanitize_url_slug()` strips query params and secrets from URLs
- [ ] `_record_api_call()` emits structlog event with all 9 fields
- [ ] `_record_rate_limited()` emits log + calls `record_provider_rate_limited()`
- [ ] `_record_error()` emits log + calls `record_provider_error()`
- [ ] API key, api_token, or any secret MUST NOT appear in any parameter
- [ ] mypy passes

---

#### T-A-1-04: Update `EODHDProviderAdapter` to extend `BaseProviderAdapter` and call `_record_api_call()`

**Type**: impl
**depends_on**: [T-A-1-03]
**blocks**: none
**Target files**: `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/eodhd.py`

**What to build**: Change `EODHDProviderAdapter(ProviderAdapter)` → `EODHDProviderAdapter(BaseProviderAdapter)`. After every successful `ProviderFetchResult` construction in each `fetch_*` method, call `self._record_api_call()` with the correct parameters.

**Credit costs**: Import `EODHD_CREDIT_COST` and `EODHD_INTRADAY_COST` from `market_ingestion.domain.freshness` (already defined there — do NOT duplicate as a local dict).

**bars_returned calculation** per method:
- `fetch_ohlcv`, `fetch_intraday`, `fetch_news_sentiment`, `fetch_earnings_calendar`, `fetch_economic_events`, `fetch_insider_transactions`, `fetch_yield_curve`, `fetch_historical_market_cap`: `json.loads(raw)` → `len(result) if isinstance(result, list) else 1`; use `try/except` fallback to `0`
- `fetch_quotes`, `fetch_fundamentals`, `fetch_macro_indicator`: `bars_returned=1`

**timeframe parameter**: Pass `timeframe` only to OHLCV/intraday methods; pass `""` for all other methods.

**Example for `fetch_ohlcv`**:
```python
async def fetch_ohlcv(self, symbol, timeframe, start, end, exchange=None):
    ...
    raw = await self._get(url, params)
    duration_ms = int((time.monotonic() - t0) * 1000)
    try:
        import json
        parsed = json.loads(raw)
        bars_returned = len(parsed) if isinstance(parsed, list) else 1
    except Exception:
        bars_returned = 0
    self._record_api_call(
        dataset_type=DatasetType.OHLCV.value,
        symbol=symbol,
        exchange=exchange or "",
        timeframe=timeframe,
        bars_returned=bars_returned,
        latency_ms=duration_ms,
        credit_cost=EODHD_CREDIT_COST.get("ohlcv", 1),
    )
    return ProviderFetchResult(
        ...,
        bars_returned=bars_returned,
    )
```

**Acceptance criteria**:
- [ ] `EODHDProviderAdapter` extends `BaseProviderAdapter`
- [ ] All 11 `fetch_*` methods call `self._record_api_call()` after success
- [ ] `ProviderFetchResult.bars_returned` is populated from the same count
- [ ] Uses `EODHD_CREDIT_COST` from domain — no local credit cost dict
- [ ] No API key or query params in any log field
- [ ] mypy passes

---

#### T-A-1-05: Create Loki+Prometheus `api-usage-analytics` Grafana dashboard

**Type**: impl
**depends_on**: none (runs concurrently with T-A-1-01..04)
**blocks**: none
**Target files**: `infra/grafana/dashboards/api-usage-analytics.json`

**What to build**: A new dashboard `uid: api-usage-analytics-v1` with panels from both Loki (`provider_api_call` log events) and Prometheus (`s2_mi_provider_*` metrics).

**Dashboard spec**:
- Title: "Provider API Usage Analytics"
- Refresh: "30s", Time: last 6 hours
- Tags: `["loki", "prometheus", "api-usage", "provider"]`
- Variables: `$provider` (Prometheus label_values, default `.*`), `$dataset_type` (default `.*`)

**Panels (8 panels)**:

Row 1 — **Prometheus Metrics** (y: 0)

**P1 — "Requests/min by Provider" (timeseries, h:8 w:12 x:0 y:1)**
- Datasource: prometheus
- Expr: `sum by (provider) (rate(s2_mi_provider_requests_total{provider=~"$provider"}[5m])) * 60`
- Legend: `{{provider}}`, Unit: `short`

**P2 — "Credits Consumed by Dataset Type" (bargauge, h:8 w:12 x:12 y:1)**
- Datasource: prometheus
- Expr: `sum by (dataset_type) (increase(s2_mi_provider_credits_total[$__range]))`
- Legend: `{{dataset_type}}`, Unit: `short`, Orientation: horizontal

**P3 — "P95 Latency by Provider" (timeseries, h:8 w:12 x:0 y:9)**
- Datasource: prometheus
- Expr: `histogram_quantile(0.95, sum by (provider, le) (rate(s2_mi_provider_latency_seconds_bucket{provider=~"$provider"}[5m])))`
- Legend: `P95 {{provider}}`, Unit: `s`

**P4 — "Rate Limit Hits by Provider" (timeseries, h:8 w:12 x:12 y:9)**
- Datasource: prometheus
- Expr: `sum by (provider) (rate(s2_mi_provider_rate_limited_total[5m])) * 60`
- Legend: `429/min {{provider}}`, Unit: `short`, Color: red fill

Row 2 — **Loki Log Analytics** (y: 17)

**P5 — "API Calls/min by Dataset Type" (timeseries, h:8 w:12 x:0 y:18)**
- Datasource: loki
- Expr: `sum by (dataset_type) (rate({container=~".*market-ingestion.*"} |= "provider_api_call" | json | dataset_type=~"$dataset_type" [5m])) * 60`
- Legend: `{{dataset_type}}`

**P6 — "Top 10 Tickers by Call Count" (table, h:8 w:12 x:12 y:18)**
- Datasource: loki
- Expr: `topk(10, sum by (symbol) (count_over_time({container=~".*market-ingestion.*"} |= "provider_api_call" | json [$__range])))`
- Transform: Reduce → Last; rename `Value` → `Calls`

**P7 — "Avg Bars Returned by Timeframe" (bargauge, h:8 w:12 x:0 y:26)**
- Datasource: loki
- Expr: `sum by (timeframe) (sum_over_time({container=~".*market-ingestion.*"} |= "provider_api_call" | json | unwrap bars_returned [$__range])) / clamp_min(sum by (timeframe) (count_over_time({container=~".*market-ingestion.*"} |= "provider_api_call" | json [$__range])), 1)`
- Unit: `short` (bars/call), Orientation: horizontal

**P8 — "Credit Cost Distribution (Loki)" (piechart, h:8 w:12 x:12 y:26)**
- Datasource: loki
- Expr: `sum by (dataset_type) (sum_over_time({container=~".*market-ingestion.*"} |= "provider_api_call" | json | unwrap credit_cost [$__range]))`
- Legend: `{{dataset_type}}`

**Acceptance criteria**:
- [ ] Valid Grafana JSON (no duplicate UIDs, correct gridPos for all 8 panels)
- [ ] Prometheus panels use `s2_mi_provider_*` metric names
- [ ] Loki panels use `{container=~".*market-ingestion.*"} |= "provider_api_call"` selector
- [ ] Dashboard auto-provisioned by existing Grafana provisioning (no config change needed — just drop the file)

---

#### T-A-1-06: Unit tests for BaseProviderAdapter and shared metrics

**Type**: test
**depends_on**: [T-A-1-03, T-A-1-04]
**blocks**: none
**Target files**: `services/market-ingestion/tests/unit/adapters/test_base_provider_adapter.py`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_record_api_call_emits_structlog_event` | `_record_api_call()` produces `provider_api_call` event with all fields | unit |
| `test_record_api_call_emits_prometheus_metrics` | `record_provider_request()` is called once per `_record_api_call()` | unit |
| `test_eodhd_fetch_ohlcv_emits_event` | EODHD adapter `fetch_ohlcv` → structlog event present | unit |
| `test_eodhd_bars_returned_populated` | Raw list of 5 bars → `bars_returned=5` in result and log | unit |
| `test_eodhd_fundamentals_bars_returned_is_1` | `fetch_fundamentals` → `bars_returned=1` | unit |
| `test_eodhd_uses_domain_credit_cost` | `credit_cost` matches `EODHD_CREDIT_COST[dataset_type]` | unit |
| `test_free_provider_credit_cost_zero` | `credit_cost=0` when Yahoo/Finnhub adapter calls `_record_api_call(credit_cost=0)` | unit |

Use `pytest-httpx` for HTTP mocking, `structlog.testing.capture_logs()` for event assertions, and `unittest.mock.patch` for Prometheus counters.

**Acceptance criteria**:
- [ ] 7 unit tests, all `pytest.mark.unit`
- [ ] Tests verify that the EODHD adapter now extends `BaseProviderAdapter`

---

### Validation Gate
- [x] `ruff check` passes on all changed files
- [x] `mypy` passes on `market-ingestion` package
- [x] 7 new unit tests pass
- [x] `ProviderFetchResult.bars_returned` default does not break existing tests
- [x] Architecture: `EODHDProviderAdapter` is subclass of `BaseProviderAdapter`

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `tests/unit/adapters/test_eodhd_adapter.py` | `EODHDProviderAdapter` now calls `_record_api_call()` which imports metrics — may fail if Prometheus registry not initialized in tests | Use `unittest.mock.patch("market_ingestion.infrastructure.metrics.providers.record_provider_request")` in affected tests |
| Any test constructing `ProviderFetchResult(...)` | New `bars_returned` field with default — safe | Verify no positional-only callers |

### Regression Guardrails
- **BP-025 (API credential leakage)**: `_record_api_call()` parameters must never include `api_key`, `api_token`, or any secret. The `symbol` param carries ticker identity only. Enforce this in code review.
- **BP-027 (Silent metric mismatch)**: `bars_returned` json parsing uses `try/except` — ensure fallback to 0 is covered by test `test_eodhd_bars_returned_populated`.
- **R25 (API layer imports infra)**: `BaseProviderAdapter` is in infrastructure layer — importing `record_provider_request` from `infrastructure/metrics/providers.py` is correct (infra→infra).

---

## Wave A-2: Finnhub Provider Adapter ✅

**Status**: **DONE** — 2026-04-25 · 95 unit tests pass · ruff + mypy clean

**Goal**: Implement `FinnhubProviderAdapter` for `NEWS_SENTIMENT`, `EARNINGS_CALENDAR`, and `INSIDER_TRANSACTIONS` dataset types. Wire into the provider registry so these datasets no longer consume EODHD credits (5 credits/call saved per request).

**Depends on**: Wave A-1 (for `provider_api_call` logging — adapter must also emit the event)
**Estimated effort**: 45–60 minutes
**Architecture layer**: infrastructure

### Pre-read
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/eodhd.py:358-427` (news_sentiment and insider_transactions fetch patterns)
- `services/market-ingestion/src/market_ingestion/domain/enums.py`
- `services/market-ingestion/src/market_ingestion/config.py`
- `services/market-ingestion/src/market_ingestion/domain/errors.py`

### Tasks

#### T-A-2-01: Add `FINNHUB` to `Provider` enum

**Type**: impl
**depends_on**: none
**blocks**: [T-A-2-02]
**Target files**: `services/market-ingestion/src/market_ingestion/domain/enums.py`

**What to build**: Add `FINNHUB = "finnhub"` to the `Provider` StrEnum class. No other changes.

**Acceptance criteria**:
- [ ] `Provider.FINNHUB.value == "finnhub"`
- [ ] mypy passes

---

#### T-A-2-02: Implement `FinnhubProviderAdapter`

**Type**: impl
**depends_on**: [T-A-2-01]
**blocks**: [T-A-2-03]
**Target files**:
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/finnhub.py` (NEW)
- `services/market-ingestion/pyproject.toml`

**What to build**: A concrete `ProviderAdapter` for Finnhub using the `finnhub-python` SDK (or direct `httpx` if preferred for consistency). The adapter implements three methods:

**CRITICAL — method signatures must match `execute_task._fetch()` cast calls**:

`ExecuteTaskUseCase._fetch()` uses `cast("Any", adapter)` to call extended methods not in the ABC. The signatures MUST match exactly:

```python
# From execute_task.py line 370 — Finnhub must implement this signature:
async def fetch_news_sentiment(
    self,
    symbol: str,
    from_date: str,
    to_date: str,
) -> ProviderFetchResult: ...

# From execute_task.py line 378 — signature:
async def fetch_insider_transactions(self, ticker: str) -> ProviderFetchResult: ...

# From execute_task.py line 340 — earnings calendar signature:
async def fetch_earnings_calendar(
    self,
    from_date: str,
    to_date: str,
) -> ProviderFetchResult: ...
```

Note: `fetch_news_sentiment` and `fetch_earnings_calendar` receive `from_date`/`to_date` strings (computed in `execute_task._fetch()` from today's date), NOT `exchange`. `fetch_insider_transactions` receives `ticker` not `symbol`. These must match the cast call sites exactly.

**`fetch_news_sentiment(symbol, from_date, to_date)`**
- Finnhub endpoint: `GET https://finnhub.io/api/v1/company-news?symbol={symbol}&from={from_date}&to={to_date}&token={api_key}`
- Returns raw JSON bytes (list of news articles)
- Maps to `DatasetType.NEWS_SENTIMENT`
- Rate limit: 60 req/min → add `asyncio.sleep(1.1)` after each call (conservative throttle)
- Call `self._record_api_call(...)` after success; call `self._record_rate_limited()` on 429

**`fetch_earnings_calendar(from_date, to_date)`**
- Finnhub endpoint: `GET https://finnhub.io/api/v1/calendar/earnings?from={from_date}&to={to_date}&token={api_key}`
- Note: no `symbol` param — returns ALL earnings in the window (Finnhub free tier)
- Returns raw JSON bytes (dict with `earningsCalendar` key)
- Maps to `DatasetType.EARNINGS_CALENDAR`
- Use `task.symbol` for logging only (not for the request)

**`fetch_insider_transactions(ticker)`**
- Finnhub endpoint: `GET https://finnhub.io/api/v1/stock/insider-transactions?symbol={ticker}&token={api_key}`
- Note: parameter is `ticker` (per `execute_task.py:378`), not `symbol`
- Returns raw JSON bytes (dict with `data` key)
- Maps to `DatasetType.INSIDER_TRANSACTIONS`

**Class skeleton**:
```python
class FinnhubProviderAdapter(BaseProviderAdapter):  # extends BaseProviderAdapter, NOT ProviderAdapter
    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str, client: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._client = client

    @property
    def provider(self) -> Provider:
        return Provider.FINNHUB

    # Required by ABC — not supported by Finnhub free tier
    async def fetch_ohlcv(self, ...) -> ProviderFetchResult:
        raise ProviderUnavailable("Finnhub does not provide OHLCV; use EODHD or Yahoo Finance")

    async def fetch_quotes(self, ...) -> ProviderFetchResult:
        raise ProviderUnavailable("Finnhub real-time quotes require paid tier")

    async def fetch_fundamentals(self, ...) -> ProviderFetchResult:
        raise ProviderUnavailable("Finnhub fundamentals not in scope for Wave A-2")
```

**Error handling**: Use same error hierarchy as EODHD adapter: `ProviderAuthError` for 401/403, `ProviderRateLimited` for 429, `ProviderUnavailable` for 5xx/connection errors, `ProviderDataError` for malformed responses.

**API key safety**: Use `self._sanitize_url_slug(url)` inherited from `BaseProviderAdapter` to strip query params and secrets from any logged URL. Never log `api_key` or the raw URL with query params.

**`pyproject.toml` change**: Add `"finnhub-python>=2.4,<3"` to `[project.dependencies]`. Pin to major version.

**Acceptance criteria**:
- [ ] `FinnhubProviderAdapter` implements `ProviderAdapter` ABC
- [ ] `fetch_news_sentiment`, `fetch_earnings_calendar`, `fetch_insider_transactions` return `ProviderFetchResult`
- [ ] `fetch_ohlcv`, `fetch_quotes`, `fetch_fundamentals` raise `ProviderUnavailable`
- [ ] API key not present in any log output
- [ ] `self._record_api_call(credit_cost=0)` called on success (from `BaseProviderAdapter`)
- [ ] mypy passes

---

#### T-A-2-03: Register Finnhub adapter in provider registry

**Type**: impl
**depends_on**: [T-A-2-02]
**blocks**: none
**Target files**: `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/__init__.py`

**What to build**: In `build_provider_registry()`, conditionally register the `FinnhubProviderAdapter` if `settings.finnhub_api_key` is non-empty. Do not register if key is missing (graceful degradation).

```python
finnhub_api_key: str = getattr(settings, "finnhub_api_key", "")
if finnhub_api_key:
    from market_ingestion.infrastructure.adapters.providers.finnhub import FinnhubProviderAdapter
    registry.register(FinnhubProviderAdapter(api_key=finnhub_api_key, client=httpx.AsyncClient()))
```

**Acceptance criteria**:
- [ ] Registry registers Finnhub only when `finnhub_api_key != ""`
- [ ] `Provider.FINNHUB` is retrievable via `registry.get(Provider.FINNHUB)` when registered

---

#### T-A-2-04: Unit tests for Finnhub adapter

**Type**: test
**depends_on**: [T-A-2-02]
**blocks**: none
**Target files**: `services/market-ingestion/tests/unit/adapters/test_finnhub_adapter.py`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_fetch_news_sentiment_returns_result` | 200 response → `ProviderFetchResult` with correct fields | unit |
| `test_fetch_earnings_calendar_returns_result` | 200 response → result | unit |
| `test_fetch_insider_transactions_returns_result` | 200 response → result | unit |
| `test_fetch_ohlcv_raises_provider_unavailable` | `fetch_ohlcv` → `ProviderUnavailable` | unit |
| `test_429_raises_provider_rate_limited` | HTTP 429 → `ProviderRateLimited` | unit |
| `test_401_raises_provider_auth_error` | HTTP 401 → `ProviderAuthError` | unit |
| `test_provider_api_call_log_event_emitted` | structlog event emitted with symbol/dataset_type fields | unit |

Use `pytest-httpx` and `structlog.testing.capture_logs()`.

**Acceptance criteria**:
- [ ] 7 unit tests, all `pytest.mark.unit`
- [ ] ruff + mypy pass

---

### Validation Gate
- [x] `ruff check` on changed files
- [x] `mypy` on `market-ingestion` package
- [x] 7 new unit tests pass (95 total)
- [x] `Provider.FINNHUB` in enum
- [x] `build_provider_registry()` only registers Finnhub when API key present

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `tests/unit/test_provider_enum.py` (if exists) | New enum value | Add `FINNHUB` expectation |
| `tests/unit/adapters/test_registry.py` (if exists) | `all_providers()` count changes | Update count or use `assertIn` |

### Regression Guardrails
- **BP-025**: Finnhub API key must never appear in log output — strip all query params from logged URLs.
- **BP-019 (Missing default for new DB column)**: Not applicable; no DB changes in this wave.

---

## Wave A-3: Yahoo Finance Provider Adapter ✅

**Status**: **DONE** — 2026-04-25 · 507 unit tests pass · ruff + mypy clean

**Goal**: Implement the `YahooFinanceProviderAdapter` using the `yfinance` library to serve `OHLCV` daily/weekly/monthly data without consuming EODHD credits.

**Depends on**: Wave A-1 (logging pattern established)
**Estimated effort**: 30–45 minutes
**Architecture layer**: infrastructure

### Pre-read
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/yahoo.py` (current stub)
- `services/market-ingestion/src/market_ingestion/application/ports/adapters.py` (ProviderFetchResult shape)
- `libs/contracts/src/contracts/canonical/ohlcv.py` (CanonicalOHLCVBar fields — adapter must not produce this; caller does canonicalization)

### Tasks

#### T-A-3-01: Implement `YahooFinanceProviderAdapter.fetch_ohlcv`

**Type**: impl
**depends_on**: none
**blocks**: [T-A-3-02]
**Target files**:
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/yahoo.py`
- `services/market-ingestion/pyproject.toml`

**What to build**: Replace the stub with a real implementation. Yahoo Finance does not use HTTP API keys. The `yfinance` library calls Yahoo's unofficial API.

**`pyproject.toml`**: Add `"yfinance>=0.2,<1"` to `[project.dependencies]`.

**Supported timeframes** (Yahoo Finance period/interval mapping):
```python
_YF_INTERVAL_MAP = {
    "1d": "1d",
    "1w": "1wk",
    "1mo": "1mo",
    "1M": "1mo",
}
_SUPPORTED_TIMEFRAMES = set(_YF_INTERVAL_MAP.keys())
```

**Implementation**:
```python
import asyncio
import json
import time

import yfinance as yf  # type: ignore[import-untyped]

async def fetch_ohlcv(self, symbol, timeframe, start, end, exchange=None):
    if timeframe not in _SUPPORTED_TIMEFRAMES:
        raise ProviderUnavailable(
            f"Yahoo Finance adapter only supports daily/weekly/monthly timeframes; got {timeframe!r}"
        )
    interval = _YF_INTERVAL_MAP[timeframe]
    ticker_sym = symbol if not exchange else f"{symbol}.{exchange}"

    t0 = time.monotonic()
    # yfinance is synchronous; run in executor to avoid blocking the event loop (BP-async-blocking)
    # Use get_running_loop() — get_event_loop() is deprecated since Python 3.10
    loop = asyncio.get_running_loop()
    raw_records = await loop.run_in_executor(
        None,
        lambda: _download_ohlcv(ticker_sym, interval, start, end),
    )
    duration_ms = int((time.monotonic() - t0) * 1000)

    raw_bytes = json.dumps(raw_records).encode()
    bars_returned = len(raw_records)

    # Use BaseProviderAdapter._record_api_call() — emits structlog event + Prometheus metrics
    self._record_api_call(
        dataset_type=DatasetType.OHLCV.value,
        symbol=symbol,
        exchange=exchange or "",
        timeframe=timeframe,
        bars_returned=bars_returned,
        latency_ms=duration_ms,
        credit_cost=0,  # Yahoo Finance is free
    )

    return ProviderFetchResult(
        provider=Provider.YAHOO_FINANCE,
        dataset_type=DatasetType.OHLCV,
        symbol=symbol,
        raw_data=raw_bytes,
        content_type="application/json",
        fetched_at=datetime.now(tz=UTC),
        duration_ms=duration_ms,
        range_start=start,
        range_end=end,
        bars_returned=bars_returned,
    )
```

**`_download_ohlcv` helper** (runs in executor — synchronous):
```python
def _download_ohlcv(
    ticker: str, interval: str, start: datetime | None, end: datetime | None
) -> list[dict]:
    """Download OHLCV bars from Yahoo Finance and return as list of dicts.

    Returns records with fields: timestamp (ISO), open, high, low, close, volume.
    """
    kwargs: dict = {"interval": interval, "auto_adjust": True, "progress": False}
    if start:
        kwargs["start"] = start.strftime("%Y-%m-%d")
    if end:
        kwargs["end"] = end.strftime("%Y-%m-%d")

    ticker_obj = yf.Ticker(ticker)
    hist = ticker_obj.history(**kwargs)

    if hist.empty:
        return []

    records = []
    for ts, row in hist.iterrows():
        records.append({
            "timestamp": ts.isoformat(),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]),
        })
    return records
```

**Error handling**: Wrap the executor call in `try/except Exception` → raise `ProviderUnavailable` with descriptive message. yfinance raises generic exceptions on invalid tickers or network errors.

**`fetch_quotes` and `fetch_fundamentals`**: Leave raising `ProviderUnavailable` — Yahoo Finance does not serve these in the current scope. Add a clear message: `"Yahoo Finance adapter: use EODHD for quotes/fundamentals"`.

**Acceptance criteria**:
- [ ] `fetch_ohlcv` returns `ProviderFetchResult` with non-zero `bars_returned` for valid symbols
- [ ] `fetch_ohlcv` raises `ProviderUnavailable` for unsupported timeframes (e.g. "1h", "5m")
- [ ] yfinance is called in executor (not blocking event loop)
- [ ] `provider_api_call` event emitted with `credit_cost=0`
- [ ] mypy passes (use `# type: ignore[import-untyped]` for yfinance if needed)

---

#### T-A-3-02: Unit tests for Yahoo Finance adapter

**Type**: test
**depends_on**: [T-A-3-01]
**blocks**: none
**Target files**: `services/market-ingestion/tests/unit/adapters/test_yahoo_adapter.py`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_fetch_ohlcv_returns_result` | Mock yf.Ticker → returns ProviderFetchResult with bars | unit |
| `test_fetch_ohlcv_empty_history_returns_zero_bars` | Empty DataFrame → `bars_returned=0` | unit |
| `test_fetch_ohlcv_unsupported_timeframe_raises` | "1h" → `ProviderUnavailable` | unit |
| `test_fetch_quotes_raises_provider_unavailable` | `fetch_quotes` → `ProviderUnavailable` | unit |
| `test_provider_api_call_event_credit_cost_zero` | `credit_cost=0` in log event | unit |

Use `unittest.mock.patch("yfinance.Ticker")` to mock the yfinance API.

**Acceptance criteria**:
- [ ] 5 unit tests, all `pytest.mark.unit`
- [ ] ruff + mypy pass

---

### Validation Gate
- [x] `ruff check` passes
- [x] `mypy` passes
- [x] 5 unit tests pass (507 total)
- [x] `yfinance` in `pyproject.toml`
- [x] No blocking I/O in async path (uses `run_in_executor`)

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `tests/unit/adapters/test_yahoo_adapter.py` (old stub test, if any) | Stub now raises `ProviderUnavailable` → real impl may change exception message | Update test assertions |

### Regression Guardrails
- **BP-async-blocking (HR-019 Blocking I/O in async service)**: yfinance is synchronous. MUST run via `asyncio.get_event_loop().run_in_executor(None, ...)`. Validate no direct yfinance call exists outside the executor lambda.
- **BP-025 (Credential leakage)**: Yahoo Finance has no API key, but log events must not include any internal URLs or user-identifiable data.

---

## Wave A-4: Provider Routing Strategy + Prometheus Timeframe Label ✅

**Status**: **DONE** — 2026-04-26 · 118 unit tests pass · ruff + mypy clean

**Goal**: Add routing logic so that `NEWS_SENTIMENT`, `EARNINGS_CALENDAR`, `INSIDER_TRANSACTIONS` prefer Finnhub when configured, and `OHLCV` daily/weekly/monthly prefers Yahoo Finance. Add `timeframe` label to EODHD Prometheus metrics for lower-cost breakdowns without per-ticker cardinality explosion.

**Depends on**: Wave A-2 (Finnhub adapter), Wave A-3 (Yahoo Finance adapter)
**Estimated effort**: 45–60 minutes
**Architecture layer**: application + infrastructure

### Pre-read
- `services/market-ingestion/src/market_ingestion/application/use_cases/trigger_ingestion.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/metrics/eodhd.py`
- `infra/grafana/dashboards/eodhd-health.json` (to update panels if label added)
- `docs/architecture/decisions/ADR_EODHD_FAILOVER.md`

### Tasks

#### T-A-4-01: Add provider routing logic to `ExecuteTaskUseCase`

**Type**: impl
**depends_on**: none
**blocks**: [T-A-4-03]
**Target files**: `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py`

**What to build**: Routing must happen at **execution time** (in `ExecuteTaskUseCase`), not at trigger time. The reason: `TriggerIngestionUseCase` creates task DB records with a `provider` field; the `SchedulerWorker` later calls `self._registry.get(task.provider)` to select the adapter. If we only route in the trigger use case without changing the stored provider, the worker ignores the routing decision.

**Architecture of the fix**:
- Add a `_preferred_provider()` module-level function to `execute_task.py`
- In `ExecuteTaskUseCase.__call__()`, after `adapter = self._registry.get(task.provider)` at line 116, override the adapter selection with the preferred provider if a better one is available
- The `task.provider` stored in DB is **not changed** (it reflects what was requested); only the in-memory adapter used for this execution is overridden
- This is safe because `task.provider` is informational metadata; the actual fetch provider is in the `ProviderFetchResult.provider` field

**`_preferred_provider()` function** (module-level in `execute_task.py`):
```python
_YAHOO_TIMEFRAMES: frozenset[str] = frozenset({"1d", "1w", "1mo", "1M"})
_FINNHUB_TYPES: frozenset[DatasetType] = frozenset({
    DatasetType.NEWS_SENTIMENT,
    DatasetType.EARNINGS_CALENDAR,
    DatasetType.INSIDER_TRANSACTIONS,
})

def _preferred_provider(
    dataset_type: DatasetType,
    timeframe: str | None,
    registry: ProviderRegistry,
) -> Provider:
    """Return the cheapest registered provider for this dataset/timeframe.

    Priority order:
      OHLCV + (1d | 1w | 1mo | 1M) → Yahoo Finance if registered (0 credits)
      NEWS_SENTIMENT | EARNINGS_CALENDAR | INSIDER_TRANSACTIONS → Finnhub if registered (free)
      All other combinations → EODHD (default, always registered)
    """
    if dataset_type == DatasetType.OHLCV and timeframe in _YAHOO_TIMEFRAMES:
        try:
            registry.get(Provider.YAHOO_FINANCE)
            return Provider.YAHOO_FINANCE
        except ProviderUnavailable:
            pass
    if dataset_type in _FINNHUB_TYPES:
        try:
            registry.get(Provider.FINNHUB)
            return Provider.FINNHUB
        except ProviderUnavailable:
            pass
    return Provider.EODHD
```

**Usage in `ExecuteTaskUseCase.__call__()`** — replace the single adapter lookup:
```python
# Line 116 currently: adapter = self._registry.get(task.provider)
# Replace with:
preferred = _preferred_provider(task.dataset_type, task.timeframe, self._registry)
adapter = self._registry.get(preferred)
if preferred != task.provider:
    log.info(
        "provider_routing_override",
        requested=str(task.provider),
        selected=preferred.value,
        dataset_type=str(task.dataset_type),
        timeframe=task.timeframe or "",
    )
```

**EODHD quota/CB guard**: The quota check (lines 122–163 in `execute_task.py`) is gated by `self._quota_service is not None`. The quota service is only relevant for EODHD. After routing, if `preferred != Provider.EODHD`, skip the quota check:
```python
if self._quota_service is not None and preferred == Provider.EODHD:
    # ... existing quota check ...
```

Similarly, the circuit breaker check should only apply to EODHD:
```python
if self._circuit_breaker is not None and preferred == Provider.EODHD:
    # ... existing CB check ...
```

**Acceptance criteria**:
- [ ] OHLCV + 1d/1w uses Yahoo Finance adapter when registered (not EODHD)
- [ ] NEWS_SENTIMENT uses Finnhub adapter when registered (not EODHD)
- [ ] Falls back to EODHD if preferred provider not registered
- [ ] `provider_routing_override` event logged when adapter is overridden
- [ ] EODHD quota/CB checks are skipped when using Yahoo/Finnhub
- [ ] Unit tests cover all routing paths

---

#### T-A-4-02: (SUPERSEDED — no longer needed)

> With `s2_mi_provider_requests_total{provider, dataset_type, timeframe, ...}` from Wave A-1, timeframe breakdown by provider is already available in the generic metrics. Adding `timeframe` to the EODHD-specific `s2_eodhd_requests_total` counter would duplicate the data and introduce a Prometheus label-addition breaking change for no gain. Task T-A-4-02 is dropped. The `eodhd-health.json` dashboard remains unchanged.

---

#### T-A-4-03: Unit tests for routing logic

**Type**: test
**depends_on**: [T-A-4-01]
**blocks**: none
**Target files**: `services/market-ingestion/tests/unit/use_cases/test_execute_task_routing.py`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_ohlcv_1d_routes_to_yahoo_when_registered` | Yahoo registered → OHLCV 1d uses Yahoo adapter | unit |
| `test_ohlcv_1h_stays_eodhd` | Yahoo only supports daily — 1h stays EODHD | unit |
| `test_news_routes_to_finnhub_when_registered` | Finnhub registered → NEWS_SENTIMENT uses Finnhub | unit |
| `test_news_falls_back_to_eodhd_when_no_finnhub` | No Finnhub registered → EODHD | unit |
| `test_fundamentals_always_eodhd` | FUNDAMENTALS always EODHD (no free alternative) | unit |
| `test_routing_override_logged` | `provider_routing_override` event emitted when adapter changed | unit |
| `test_quota_check_skipped_for_yahoo` | When Yahoo selected, quota service `try_consume()` is NOT called | unit |
| `test_quota_check_skipped_for_finnhub` | When Finnhub selected, quota service `try_consume()` is NOT called | unit |

**Acceptance criteria**:
- [ ] 8 unit tests, all `pytest.mark.unit`

---

#### T-A-4-04: Documentation + service context update

**Type**: docs
**depends_on**: [T-A-4-01, T-A-4-03]
**blocks**: none
**Target files**:
- `docs/services/market-ingestion.md` — add "Provider Coverage" section
- `services/market-ingestion/.claude-context.md` — update provider list, add routing info
- `docs/architecture/decisions/ADR_EODHD_FAILOVER.md` — note free provider routing added

**Content for `docs/services/market-ingestion.md` "Provider Coverage" section**:
```markdown
## Provider Coverage

| Dataset Type | Primary Provider | Fallback | Credit Cost | Notes |
|---|---|---|---|---|
| OHLCV (1d/1w/1M) | Yahoo Finance | EODHD | 0 / 1 | Preferred when `yfinance` registered |
| OHLCV (intraday) | EODHD | — | 5 | Yahoo only supports EOD |
| QUOTES | EODHD | — | 1 | |
| FUNDAMENTALS | EODHD | — | 10 | Most expensive; no free alternative yet |
| NEWS_SENTIMENT | Finnhub | EODHD | 0 / 5 | Preferred when `finnhub_api_key` set |
| EARNINGS_CALENDAR | Finnhub | EODHD | 0 / 5 | |
| INSIDER_TRANSACTIONS | Finnhub | EODHD | 0 / 5 | |
| ECONOMIC_EVENTS | EODHD | — | 5 | |
| MACRO_INDICATOR | EODHD | — | 5 | |
| YIELD_CURVE | EODHD | — | 5 | |
| MARKET_CAP | EODHD | — | 1 | |
```

**Acceptance criteria**:
- [ ] `docs/services/market-ingestion.md` has updated provider coverage table
- [ ] `.claude-context.md` lists `Provider.FINNHUB` and routing behavior

---

### Validation Gate
- [x] `ruff check` passes
- [x] `mypy` passes
- [x] 8 routing + quota-bypass unit tests pass
- [x] All prior unit tests (Wave A-1..A-3) still pass
- [x] `execute_task.py` quota/CB checks gated on `preferred == Provider.EODHD`
- [x] Documentation updated

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `services/market-ingestion/tests/unit/use_cases/test_execute_task.py` | `ExecuteTaskUseCase.__call__()` now calls `_preferred_provider()` and may select a different adapter; quota/CB checks gated on `preferred == Provider.EODHD` | Update tests that assert adapter is always EODHD; add tests for routing override path |

### Regression Guardrails
- **BP-027 (Silent metric label mismatch)**: Adding a label dimension to an existing counter resets all historical series in Prometheus. This is acceptable in dev but must be documented. For production, note in the commit message: "Prometheus label addition — expect time series gap for `s2_eodhd_requests_total`".
- **BP-023 (pre-commit ruff divergence)**: Run `ruff format` on all modified `.py` files before committing.

---

## Wave A-5: Zero-Bar Failover — Valkey Streak Counter ✅

**Status**: **DONE** — 2026-04-26 · 118 unit tests pass · ruff + mypy clean

**Goal**: After a provider returns `bars_returned=0` for 5 consecutive executions on the same (provider, symbol, timeframe, dataset_type), automatically re-route to the next provider in the priority chain. Resets on any non-zero response. Does not replace the circuit breaker (zero bars ≠ network error).

**Depends on**: Wave A-4 (requires `_preferred_provider()`, `_YAHOO_TIMEFRAMES`, `_FINNHUB_TYPES` from that wave)
**Estimated effort**: 60–90 minutes
**Architecture layer**: application + infrastructure

### Pre-read
- `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py` — Step 1 fetch block (line ~165)
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/circuit_breaker.py` — pattern for Valkey-backed port+adapter
- `services/market-ingestion/src/market_ingestion/application/ports/circuit_breaker.py` — port ABC pattern to follow

### Tasks

#### T-A-5-01: `ZeroBarTrackerPort` + `ValkeyZeroBarTracker`

**Type**: impl
**depends_on**: none
**blocks**: [T-A-5-02]
**Target files**:
- `services/market-ingestion/src/market_ingestion/application/ports/zero_bar_tracker.py` (NEW)
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/zero_bar_tracker.py` (NEW)

**What to build**: A port ABC and a Valkey-backed implementation for tracking consecutive zero-bar responses per (provider, symbol, timeframe, dataset_type) tuple.

**Port (`application/ports/zero_bar_tracker.py`)**:
```python
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import ClassVar

class ZeroBarTrackerPort(ABC):
    """Tracks consecutive zero-bar API responses per (provider, symbol, timeframe, dataset_type).

    Used by ExecuteTaskUseCase to decide when to failover to the next provider.
    Zero-bar responses are not errors (e.g., weekend, holiday, new listing), so
    the circuit breaker doesn't apply — this tracker handles soft data-quality signals.
    """

    FAILOVER_THRESHOLD: ClassVar[int] = 5

    @abstractmethod
    async def record_zero(
        self, provider: str, symbol: str, timeframe: str, dataset_type: str
    ) -> int:
        """Record a zero-bar result. Returns new consecutive streak count."""

    @abstractmethod
    async def reset(
        self, provider: str, symbol: str, timeframe: str, dataset_type: str
    ) -> None:
        """Reset the zero-bar streak after a successful non-zero fetch."""

    def should_failover(self, streak: int) -> bool:
        """Return True when streak has reached FAILOVER_THRESHOLD."""
        return streak >= self.FAILOVER_THRESHOLD
```

**Adapter (`infrastructure/adapters/zero_bar_tracker.py`)**:
```python
from __future__ import annotations
from typing import TYPE_CHECKING
from market_ingestion.application.ports.zero_bar_tracker import ZeroBarTrackerPort

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

class ValkeyZeroBarTracker(ZeroBarTrackerPort):
    """Valkey-backed zero-bar streak counter.

    Key schema: ``neg:prov:{provider}:{symbol}:{timeframe}:{dataset_type}:zbs``
    TTL: 86400 seconds (24h) — stale streaks from weekends auto-expire.

    Thread-safe: INCR is atomic in Valkey. Last-writer-wins for concurrent
    resets is acceptable (matches circuit breaker design philosophy).
    """

    _KEY_PREFIX: str = "neg:prov"
    _STREAK_TTL: int = 86_400  # 24h

    def __init__(self, valkey: ValkeyClient) -> None:
        self._valkey = valkey

    def _key(self, provider: str, symbol: str, timeframe: str, dataset_type: str) -> str:
        return f"{self._KEY_PREFIX}:{provider}:{symbol}:{timeframe}:{dataset_type}:zbs"

    async def record_zero(self, provider: str, symbol: str, timeframe: str, dataset_type: str) -> int:
        key = self._key(provider, symbol, timeframe, dataset_type)
        streak = await self._valkey.incr(key)
        await self._valkey.expire(key, self._STREAK_TTL)
        return int(streak)

    async def reset(self, provider: str, symbol: str, timeframe: str, dataset_type: str) -> None:
        key = self._key(provider, symbol, timeframe, dataset_type)
        await self._valkey.delete(key)
```

**Acceptance criteria**:
- [ ] `ZeroBarTrackerPort` is abstract — no concrete I/O
- [ ] `ValkeyZeroBarTracker.record_zero()` uses INCR + EXPIRE atomically per call
- [ ] TTL is 24h (stale weekend streaks auto-clear)
- [ ] Key schema follows `neg:prov:` prefix convention (matches existing negative cache keys)
- [ ] mypy passes

---

#### T-A-5-02: `_fallback_provider()` + zero-bar failover logic in `execute_task.py`

**Type**: impl
**depends_on**: [T-A-5-01]
**blocks**: [T-A-5-03]
**Target files**: `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py`

**What to build**:

1. Add `zero_bar_tracker: ZeroBarTrackerPort | None = None` parameter to `ExecuteTaskUseCase.__init__()`. Store as `self._zero_bar_tracker`.

2. Add `_fallback_provider()` module-level function (after `_preferred_provider()`):

```python
def _fallback_provider(
    dataset_type: DatasetType,
    timeframe: str | None,
    current_provider: Provider,
    registry: ProviderRegistry,
) -> Provider | None:
    """Return the next provider in the priority chain after current_provider returns zero bars.

    Chain (matches _preferred_provider() inverse):
      OHLCV daily/weekly/monthly: Yahoo Finance → EODHD → None
      NEWS_SENTIMENT / EARNINGS_CALENDAR / INSIDER_TRANSACTIONS: Finnhub → EODHD → None
      OHLCV intraday / all others: EODHD → None  (no free intraday alternative)

    Returns None when no fallback is registered or dataset has no alternative.
    """
    if dataset_type == DatasetType.OHLCV and timeframe in _YAHOO_TIMEFRAMES:
        if current_provider == Provider.YAHOO_FINANCE:
            return Provider.EODHD  # Yahoo empty → try EODHD
    if dataset_type in _FINNHUB_TYPES:
        if current_provider == Provider.FINNHUB:
            return Provider.EODHD  # Finnhub empty → try EODHD
    return None  # EODHD is the terminal fallback; no further chain
```

3. Insert zero-bar failover logic in `execute_task()` **immediately after** the `fetch_result = await self._fetch(adapter, task)` + circuit breaker `record_success` block, and **before** Step 2 (store bronze):

```python
# ── Zero-bar failover check ─────────────────────────────────────────────────
# Tracks consecutive zero-bar responses per (provider, symbol, timeframe, dataset).
# After FAILOVER_THRESHOLD (default 5) consecutive misses, reroute to fallback.
# This handles soft data-quality failures (holiday, listing gap, provider lag)
# that are NOT caught by the circuit breaker (which targets HTTP errors).
# Dataset gate: only list-type datasets can have meaningful zero-bar counts;
# FUNDAMENTALS / MACRO always return bars_returned=1 from the adapter.
_ZERO_BAR_DATASET_TYPES: frozenset[DatasetType] = frozenset({
    DatasetType.OHLCV,
    DatasetType.NEWS_SENTIMENT,
    DatasetType.EARNINGS_CALENDAR,
    DatasetType.INSIDER_TRANSACTIONS,
})
if self._zero_bar_tracker is not None and task.dataset_type in _ZERO_BAR_DATASET_TYPES:
    if fetch_result.bars_returned == 0:
        streak = await self._zero_bar_tracker.record_zero(
            provider=str(preferred),
            symbol=task.symbol,
            timeframe=task.timeframe or "",
            dataset_type=str(task.dataset_type),
        )
        log.debug("zero_bar_streak_recorded", streak=streak, provider=str(preferred))
        if self._zero_bar_tracker.should_failover(streak):
            fallback = _fallback_provider(task.dataset_type, task.timeframe, preferred, self._registry)
            if fallback is not None:
                fallback_adapter = self._registry.get(fallback)
                log.warning(
                    "provider_zero_bar_failover",
                    streak=streak,
                    primary_provider=str(preferred),
                    fallback_provider=fallback.value,
                    symbol=task.symbol,
                    timeframe=task.timeframe or "",
                )
                # Re-fetch with fallback; if this also returns 0 bars we proceed
                # normally (no nested failover — one level deep is sufficient).
                fetch_result = await self._fetch(fallback_adapter, task)
            else:
                log.warning(
                    "provider_zero_bar_no_fallback",
                    streak=streak,
                    provider=str(preferred),
                    dataset_type=str(task.dataset_type),
                )
    else:
        # Non-zero result: reset streak for this provider/symbol/timeframe
        await self._zero_bar_tracker.reset(
            provider=str(preferred),
            symbol=task.symbol,
            timeframe=task.timeframe or "",
            dataset_type=str(task.dataset_type),
        )
```

**Note**: `_ZERO_BAR_DATASET_TYPES` can be a module-level constant (placed with other module-level constants after the function definitions at the bottom of the file). The `preferred` variable is introduced by Wave A-4 — this wave strictly depends on A-4 being implemented.

**Acceptance criteria**:
- [ ] `zero_bar_tracker=None` → zero-bar logic is completely bypassed (backward-compatible)
- [ ] After 5 consecutive zero-bar OHLCV 1d responses from Yahoo → uses EODHD adapter for that tick
- [ ] After 5 consecutive zero-bar NEWS from Finnhub → uses EODHD adapter
- [ ] EODHD zero-bar OHLCV intraday → logs `provider_zero_bar_no_fallback` but does NOT failover
- [ ] Streak resets on any non-zero `bars_returned`
- [ ] `provider_zero_bar_failover` log event emitted on failover (with streak, primary, fallback)
- [ ] mypy passes

---

#### T-A-5-03: Unit tests for zero-bar failover

**Type**: test
**depends_on**: [T-A-5-02]
**blocks**: none
**Target files**: `services/market-ingestion/tests/unit/use_cases/test_execute_task_zero_bar_failover.py` (NEW)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_zero_bar_ohlcv_increments_streak` | `bars_returned=0` → `record_zero()` called once | unit |
| `test_nonzero_bar_resets_streak` | `bars_returned=5` → `reset()` called | unit |
| `test_failover_fires_at_threshold_5` | streak=5 + Yahoo → EODHD re-fetch triggered | unit |
| `test_failover_does_not_fire_below_threshold` | streak=4 → no re-fetch | unit |
| `test_eodhd_intraday_no_fallback_logs_warning` | EODHD 1m zero → `provider_zero_bar_no_fallback` event, no re-fetch | unit |
| `test_fallback_returns_none_for_eodhd_ohlcv_intraday` | `_fallback_provider(OHLCV, "1m", EODHD, registry)` → None | unit |
| `test_fallback_returns_eodhd_for_yahoo_daily` | `_fallback_provider(OHLCV, "1d", YAHOO, registry)` → EODHD | unit |
| `test_fallback_returns_eodhd_for_finnhub_news` | `_fallback_provider(NEWS_SENTIMENT, None, FINNHUB, registry)` → EODHD | unit |
| `test_zero_bar_tracker_none_skips_logic` | `zero_bar_tracker=None` → no calls to record/reset | unit |
| `test_fundamentals_not_tracked` | `dataset_type=FUNDAMENTALS` + zero bars → no `record_zero()` call | unit |

**Acceptance criteria**:
- [ ] 10 unit tests, all `pytest.mark.unit`
- [ ] Mock `ZeroBarTrackerPort` using `AsyncMock`
- [ ] ruff + mypy pass

---

#### T-A-5-04: Wire `ValkeyZeroBarTracker` into `app.py`

**Type**: impl
**depends_on**: [T-A-5-01, T-A-5-02]
**blocks**: none
**Target files**: `services/market-ingestion/src/market_ingestion/app.py`

**What to build**: In the application factory, construct `ValkeyZeroBarTracker(valkey=valkey_client)` and pass it to `ExecuteTaskUseCase`. Should only be wired when a Valkey client is available (follows same conditional pattern as circuit breaker).

```python
# In app.py, alongside circuit_breaker construction:
from market_ingestion.infrastructure.adapters.zero_bar_tracker import ValkeyZeroBarTracker

zero_bar_tracker = ValkeyZeroBarTracker(valkey=valkey_client) if valkey_client is not None else None

# Pass to ExecuteTaskUseCase:
execute_use_case = ExecuteTaskUseCase(
    ...,
    circuit_breaker=circuit_breaker,
    zero_bar_tracker=zero_bar_tracker,  # ← new
)
```

**Acceptance criteria**:
- [ ] `ValkeyZeroBarTracker` wired when Valkey is available
- [ ] `None` passed when no Valkey (degraded mode — failover disabled, not crashed)
- [ ] mypy passes

---

### Validation Gate
- [x] `ruff check` passes on all changed files
- [x] `mypy` passes on `market-ingestion` package
- [x] 10 unit tests pass
- [x] `ExecuteTaskUseCase(zero_bar_tracker=None)` → no behavior change (all prior tests still pass)
- [x] `provider_zero_bar_failover` event present in structlog output on failover path

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `tests/unit/use_cases/test_execute_task.py` | New `zero_bar_tracker` parameter | Add `zero_bar_tracker=None` to all `ExecuteTaskUseCase(...)` constructors in test fixtures |

### Regression Guardrails
- **BP-034 (mark_processed before early return)**: The zero-bar failover adds a new early-exit-like path (re-fetch). Ensure `task.succeed()` is called once after the final `fetch_result` is known — never twice. The re-fetch only replaces `fetch_result`; all downstream steps (Steps 2–5) run once on the final result.
- **BP-023 (pre-commit ruff divergence)**: Run `ruff format` on all modified files before committing.
- **Zero-bar false-positive guard**: Weekends and market holidays legitimately return 0 bars. The 5-streak threshold prevents false positives from single-day gaps. Always test with a mock that returns 0 bars 4 times before testing failover at 5.

---

## Appendix A — Deferred Work

These designs were investigated on 2026-04-25 but deferred to future plans. Document them here so they can be picked up without re-investigation.

---

### A.1 Intraday Provider Research (2026-04-25)

**Context**: EODHD REST-based intraday polling (1m/5m) is credit-prohibitive at scale. A parallel provider search was conducted to find better alternatives.

**Findings**:

| Provider | REST Intraday | WebSocket | Free Tier | Paid (500-1k sym) | Python SDK | 1m History |
|---|---|---|---|---|---|---|
| **EODHD** | Yes (5 credits/call) | Ticks only (50 sym/conn) | 20 calls/day | €29.99/mo (100k credits/day) | Unofficial | 120 days |
| **Polygon.io** | Yes | Real-time bar aggregates | 15-min delayed, unlimited REST, 2yr history | $29/mo Starter | `polygon-api-client` | 2+ years (paid) |
| **Alpaca** | Yes | Real-time + SIP feed | Free: IEX feed, 1m bars, unlimited symbols | $99/mo for full SIP | `alpaca-py` | ~5 years |
| **Alpha Vantage** | Yes | No | 25 calls/day (useless at scale) | $49.99/mo (75 req/min) | `alpha_vantage` | 20+ years |
| **Twelve Data** | Yes | Real-time price events | 800 credits/day (~8 calls) | $29/mo Basic | `twelvedata-python` | ~1.5 years |
| **IEX Cloud** | Yes | Yes | No free tier since 2023 | ~$9/mo (pay-per-use) | `pyEX` | ~5 years |

**EODHD intraday credit analysis** (1000 symbols, 5m bars):
- 1000 symbols × 5 credits/call × 78 poll cycles/trading day = **390,000 credits/day**
- Hard limit on €29.99/mo plan: **100,000 credits/day**
- → EODHD REST polling for 1000 symbols at 5m resolution is **not viable** (3.9× over limit)
- For 500 symbols at 5m: ~195,000 credits/day (still 1.95× over limit)
- EODHD WebSocket delivers tick/trade data only, not OHLCV bars; limited to 50 symbols/connection

**Recommendation**: For intraday OHLCV at scale, use **Alpaca free tier** (WebSocket, unlimited symbols, 1m bars, 5-year history) as the primary intraday provider, with daily REST reconciliation to fill gaps. Polygon.io ($29/mo) is the best paid option.

**WebSocket vs REST for intraday**:
- REST polling at 1m/5m resolution for 1000 symbols is structurally infeasible with per-call billing models
- WebSocket streaming (single connection, all symbols) is the correct architectural choice
- Alpaca and Polygon both support subscribing to `*` (all symbols) on one connection — filter client-side
- WebSocket feeds are not guaranteed complete; reconcile against REST at end of each trading session
- Architecture: WebSocket producer → Kafka → market-ingestion consumer (maps to existing Kafka pattern)

**Resampling viability**: Ingest at 1m, resample to 5m/15m/1h/4h using pandas/polars `resample().agg()`. Standard OHLCV agg: open=first, high=max, low=min, close=last, volume=sum. One ingestion source → multiple derived resolutions. This is the recommended approach.

---

### A.2 Primary Provider Reclaim Worker (Design Spec)

**Status**: Deferred — implement when zero-bar failover (Wave A-5) is in production and data shows meaningful failover events that warrant back-filling.

**Context**: When zero-bar failover routes OHLCV fetches to EODHD instead of Yahoo Finance, those dates are stored with EODHD data. When Yahoo Finance recovers, we want to overwrite those bars with Yahoo data (0-cost, higher frequency update cadence). The Reclaim Worker is the background healing mechanism.

**Design**:

**Step 1 — Track actual fetch provider** (migration required):

Add `fetched_by_provider: str | None` column to `ingestion_tasks`:
```sql
ALTER TABLE ingestion_tasks ADD COLUMN fetched_by_provider VARCHAR(64);
-- Backfill: assume EODHD for all historical tasks
UPDATE ingestion_tasks SET fetched_by_provider = provider WHERE fetched_by_provider IS NULL;
```

In `ExecuteTaskUseCase.execute()`, after `fetch_result = await self._fetch(adapter, task)`, set:
```python
task.fetched_by_provider = fetch_result.provider.value
```
(Requires `fetched_by_provider: str | None = None` on `IngestionTask` entity and ORM model.)

**Step 2 — Reclaim Worker process**:

```
PrimaryProviderReclaimWorker (new class in infrastructure/workers/reclaim_worker.py)
Cadence: every 4 hours (configurable via MARKET_INGESTION_RECLAIM_INTERVAL_SECONDS)
```

Logic per tick:
1. Query `ingestion_tasks` for rows where:
   - `status = 'SUCCEEDED'`
   - `completed_at > NOW() - INTERVAL '30 days'`  (configurable lookback window)
   - `fetched_by_provider != <preferred_provider(dataset_type, timeframe)>`
2. For each distinct (symbol, dataset_type, timeframe, exchange):
   - Derive the full date range covered (min `range_start` → max `range_end`)
   - Create one new `IngestionTask` with `provider=primary` for the full range
   - Enqueue via `uow.tasks.add_many([task])` (ON CONFLICT DO NOTHING — idempotent)
3. Tasks flow through normal `ExecuteTaskUseCase` pipeline
4. New task overwrites the MinIO canonical ref via watermark advance

**Key invariants**:
- Bulk re-fetch (full date range, not per-day) — single task per symbol per reclaim tick
- Idempotent: re-running the worker creates at most one task per symbol (dedupe_key collision on second run)
- Old MinIO objects orphaned (acceptable — MinIO lifecycle policy can clean after 90 days)
- Worker only runs when Valkey is available (requires `ValkeyCircuitBreaker` to be live, indicating infra is healthy)
- Does NOT run during backfill mode (check watermark `backfill_enabled` flag)

**New files needed** (future plan):
- `services/market-ingestion/alembic/versions/<hash>_add_fetched_by_provider.py` — migration
- `services/market-ingestion/src/market_ingestion/domain/entities/ingestion_task.py` — new field
- `services/market-ingestion/src/market_ingestion/infrastructure/db/models/ingestion_task.py` — new column
- `services/market-ingestion/src/market_ingestion/infrastructure/workers/reclaim_worker.py` — new worker
- `services/market-ingestion/src/market_ingestion/app.py` — register worker process
- `services/market-ingestion/tests/unit/workers/test_reclaim_worker.py` — tests

**Open questions before implementing**:
1. Should the reclaim window be 7 days (for recent failover events) or 30 days (for historical gaps)?
2. Should the worker skip symbols that are still in zero-bar streak state (to avoid immediate re-failover)?
3. What is the MinIO retention policy for orphaned objects?

---

## Cross-Cutting Concerns

### New Dependencies
- `yfinance>=0.2,<1` — pure Python, no system deps, MIT license, no API key
- `finnhub-python>=2.4,<3` — HTTP SDK, MIT license, API key in config

### New Configuration
| Env Var | Service | Default | Description |
|---|---|---|---|
| `FINNHUB_API_KEY` | market-ingestion | `""` | Finnhub API key; empty = Finnhub adapter not registered |
| _(yfinance has no API key)_ | — | — | — |

Update `services/market-ingestion/configs/dev.local.env.example`:
```
# Finnhub provider (free tier: 60 req/min)
# Register at https://finnhub.io — get free API key under 60s
FINNHUB_API_KEY=
```

### New Grafana Dashboard
- `infra/grafana/dashboards/api-usage-analytics.json` — Loki-based, uid `api-usage-analytics-v1`
- Auto-provisioned by existing Grafana Alloy setup (no additional config needed)

### No Avro Schema Changes
No new Kafka topics or Avro schemas. The `provider_api_call` event is a log event only (not Kafka).

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| yfinance API breaks (unofficial Yahoo API) | Medium | Medium | Rate-limit friendly; EODHD fallback always works |
| Finnhub rate limit (60/min) exceeded in backfill | Medium | Low | Conservative 1.1s sleep in Wave A-2; token bucket in future wave |
| Prometheus label dimension reset (timeframe) | High | Low | Dev only; document in commit; no alarm rules use `s2_eodhd_requests_total` directly |
| Loki LogQL panel expressions need tuning | Low | Low | Dashboards are advisory; broken panels don't affect data flow |

**Critical path**: A-1 → A-2 (or A-3, parallel) → A-4 → A-5
**Highest risk wave**: A-3 (yfinance async executor pattern, unofficial API)
**Rollback**: All waves are additive (new files, new labels with defaults). Rolling back means removing the new adapters — EODHD continues to work unchanged. Wave A-5 is fully gated behind `zero_bar_tracker=None` — removing the wiring in `app.py` reverts to pre-A-5 behavior without any data impact.

---

## Estimated Total Effort

| Wave | Tasks | Effort |
|---|---|---|
| A-1 | 6 (T-A-1-01..06) | 60–75 min |
| A-2 | 4 (T-A-2-01..04) | 45–60 min |
| A-3 | 2 (T-A-3-01..02) | 30–45 min |
| A-4 | 3 (T-A-4-01, T-A-4-03, T-A-4-04) | 45–60 min |
| A-5 | 4 (T-A-5-01..04) | 60–90 min |
| **Total** | **19** | **4–5.5 hours** |
