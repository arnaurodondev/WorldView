# PLAN-0107: Observability + Caching + Process Follow-Ups

**Status**: pending
**Created**: 2026-06-06
**Source**: post-mortem of the worker-metrics rollout session (PLAN-0099 W4 arc)

---

## Overview

Six follow-up areas surfaced during the worker-metrics rollout, grouped into four sub-plans (A–D) so they can ship in parallel. None of them block each other; sub-plan dependencies are listed per wave below.

```
A. Provider-Agnostic Market-Data Cache         — biggest scope, feature work
   ├─ A-1 → A-2 → A-3 → A-4 → A-5

B. Observability Helper + Worker Logging
   ├─ B-1 (helpers, atomic) ── B-2 (audit) ── B-3 (wire) ── B-4 (banner sweep) ── B-5 (panel)

C. Recording Rules + Dashboard Hygiene
   ├─ C-1 ──┐
            ├─ independent (any order)
   ├─ C-2 ──┤
   ├─ C-3 ──┤
   ├─ C-4 ──┤
   ├─ C-5 ──┘

D. R42 / BP-590 Parallel-Session Mitigation
   ├─ D-1 → D-2 → D-3, D-4, D-5 (D-3/4/5 independent after D-2)
```

A and D touch disjoint codepaths and can run fully in parallel.
B-1 and C-1 are good Day-1 ships (atomic, low risk).
B-3 depends on B-2's audit; C-2 depends on C-1 only because the README must reference the new recording rules.

---

## Sub-Plan A — Provider-Agnostic Market-Data Cache

### A.0 Why this is feature work, not instrumentation

The codebase has *named* metrics for a response cache (`s2_eodhd_cache_hits_total` / `s2_eodhd_cache_misses_total` at `services/market-ingestion/src/market_ingestion/application/metrics/eodhd.py:91-102`) and a Grafana panel waiting on them, but **no read-through cache exists in the request path** — `eodhd.py` calls `httpx` directly. We must build the cache (new class, new wiring, new keys), not merely emit metrics; that makes this a feature, not an observability gap.

### A.1 Design decisions

**Key format.** `f"market_data:{dataset_type}:{symbol}:{period_key}"`, lowercase. Defended: (a) symbol is the canonical universe identifier (already normalized upstream in market-ingestion strategies), (b) `dataset_type` is an internal enum we own — swapping EODHD→Polygon does not change it, (c) `period_key` is the request-shape coordinate (e.g. `1d:2024-01-01:2024-12-31`, `q:2024Q3`, `latest`). URL/endpoint is **excluded** by design so that provider routing changes (e.g. EODHD→Polygon for OHLCV) **reuse the same cached payload**. Namespacing under `market_data:` keeps the keyspace disjoint from circuit-breaker, JWT-jti, and JWKS users of the shared Valkey.

**TTL policy table** (encoded in `cache_policy.py`):

| dataset_type             | TTL    | Reasoning                                                        |
|--------------------------|--------|------------------------------------------------------------------|
| `ohlcv_eod`              | 6 h    | EOD bars finalize once/day; intra-day re-pulls are wasteful      |
| `ohlcv_intraday`         | 60 s   | Intraday but not real-time; balances freshness vs credits        |
| `fundamentals_snapshot`  | 24 h   | Reported quarterly; daily refresh is overkill but covers restatements |
| `earnings_calendar`      | 12 h   | Calendars edit during the day, but mostly stable                 |
| `dividends`              | 24 h   | Event-driven; daily refresh fine                                 |
| `splits`                 | 24 h   | Same                                                             |
| `exchanges_list`         | 7 d    | Reference data                                                   |
| `symbol_search`          | 1 h    | Search results stable enough                                     |

**Allow-list (cacheable).** All of the above.
**Forbidden (never cache).** `quote_realtime`, `quote_delayed`, anything with `live=true`, websocket frames, user-scoped data. Guard: `MarketDataCache.get_or_fetch` raises `ValueError` if `dataset_type` is not in the enum.

**Failure semantics.** Cache miss, Valkey timeout, deserialization error, or backend error all **fall through to the provider**; the request never fails because of the cache. All such fall-throughs increment `s2_mi_provider_cache_errors_total{kind=...}`. Writes after fetch are best-effort (swallow Valkey errors, log at WARNING).

**Serialization.** `json.dumps(payload, sort_keys=True, separators=(",",":"))`, UTF-8. No compression in v1 (entries are < 64 KiB; revisit if p99 payload > 256 KiB).

### A.2 Architectural placement

New class `MarketDataCache` at `services/market-ingestion/src/market_ingestion/infrastructure/cache/market_data_cache.py` plus `__init__.py`. It sits **above the provider adapter, below the use case**: use cases call `cache.get_or_fetch(...)` and pass a fetcher closure that wraps the adapter call. Adapters stay provider-specific and cache-unaware (preserves R12 domain independence and R25 use-case-only routing in the API layer).

Public API:
```python
async def get_or_fetch(
    dataset_type: DatasetType,
    symbol: str,
    period_key: str,
    fetcher: Callable[[], Awaitable[ResultEnvelope]],
    *,
    provider_label: str,   # for metrics label only
) -> ResultEnvelope
```

Cleanup: delete `eodhd_cache_hits_total` and `eodhd_cache_misses_total` at `application/metrics/eodhd.py:88-102`, remove them from `__all__`, and update any test importing them.

### A.3 Implementation waves

**Wave A-1 — Dataset taxonomy + TTL config (~50 LOC).**
- `infrastructure/cache/__init__.py`, `infrastructure/cache/cache_policy.py`.
- `class DatasetType(StrEnum)`, `CACHE_TTL_SECONDS: Mapping[DatasetType, int]`.
- Validation: ruff + mypy strict; unit test asserting every enum member has a TTL.

**Wave A-2 — `MarketDataCache` class + Valkey backend (~150 LOC + 80 LOC tests).**
- `infrastructure/cache/market_data_cache.py`. Uses `messaging.valkey.ValkeyClient.get` / `set` (ex=ttl). JSON serialization, sorted keys. Stampede mitigation: `set_nx` of a sentinel `__inflight__` with short ex=10s; on duplicate inflight, single retry-after-jitter (5–25 ms), then fall through to fetcher.
- Tests in `tests/unit/infrastructure/cache/test_market_data_cache.py`: hit path, miss-then-fill, Valkey GET raises → fall through, Valkey SET raises → still returns payload, sentinel inflight path, key-format snapshot test.
- Validation: ruff + mypy + the new unit module green.

**Wave A-3 — Wire into 3 use-case sites (~30 LOC each, ~90 LOC total).**
Targets:
1. OHLCV history use case under `application/use_cases/` (the strategy that calls `EODHDProvider.fetch_eod_bars` — wrap with `dataset_type=DatasetType.OHLCV_EOD`, `period_key=f"{interval}:{start}:{end}"`).
2. Fundamentals snapshot use case (`DatasetType.FUNDAMENTALS_SNAPSHOT`, `period_key="latest"`).
3. Earnings calendar use case (`DatasetType.EARNINGS_CALENDAR`, `period_key=f"{from_date}:{to_date}"`).
- Inject `MarketDataCache` via the existing DI container; do **not** instantiate inside the use case.
- Tests: extend each use-case unit test with a hit case (fetcher must not be called) and a miss case (fetcher called once, result cached). Integration test with `fakeredis` covering the OHLCV path end-to-end.

**Wave A-4 — Provider-agnostic cache metrics + dashboard wiring (~30 LOC + JSON edit).**
- New metrics module `application/metrics/cache.py`:
  - `s2_mi_provider_cache_hits_total{provider, dataset_type}`
  - `s2_mi_provider_cache_misses_total{provider, dataset_type}`
  - `s2_mi_provider_cache_errors_total{kind}`  *(kind ∈ get_error, set_error, deserialize_error, inflight_timeout)*
- Increment from `MarketDataCache` with the `provider_label` arg (so we can confirm provider-swap cache reuse: hit count rises on the new provider label while keys are unchanged).
- Edit `infra/grafana/dashboards/eodhd-health.json` — repoint the existing "Response Cache Hit Rate" panel to `sum(rate(s2_mi_provider_cache_hits_total[5m])) / (sum(rate(s2_mi_provider_cache_hits_total[5m])) + sum(rate(s2_mi_provider_cache_misses_total[5m])))` and add a second panel broken down by `dataset_type`.
- Validation: panel renders in local Grafana with non-zero series after `make seed`.

**Wave A-5 — Delete orphan EODHD cache Counters (~15 LOC delete + grep clean).**
- Remove `eodhd_cache_hits_total` and `eodhd_cache_misses_total` from `application/metrics/eodhd.py:88-102` and `__all__`.
- `grep -r s2_eodhd_cache_` must return zero hits across `services/`, `infra/grafana/`, `docs/`.
- Validation: ruff + mypy + market-ingestion full unit suite.

### A.4 Acceptance criteria

- Hit rate visible in Grafana within 5 minutes of first request post-deploy (panel non-empty, both labels populated).
- Provider swap demonstrated: change routing rule for OHLCV from `eodhd` to `polygon`, replay the same OHLCV request, observe `s2_mi_provider_cache_hits_total{provider="polygon"}` increment **without** a corresponding miss (key unchanged).
- p95 latency for cached responses < 50 ms measured at the use-case boundary (existing histogram).
- Valkey hard-down integration test: stop the container, request still succeeds end-to-end, `s2_mi_provider_cache_errors_total{kind="get_error"}` increments.

### A.5 Risk assessment

- **Fundamentals staleness.** A 24 h TTL can serve pre-restatement data after an 8-K filing. Mitigation: add a manual `cache.invalidate(dataset_type, symbol)` admin endpoint (out of scope for v1; tracked as follow-up).
- **Cache stampede on cold cache.** N concurrent misses for the same symbol all hit the provider and burn credits. Mitigated in A-2 via `set_nx` inflight sentinel + bounded retry; full single-flight (one in-process future per key) deferred to v2 if stampede metrics show >1% duplicate-miss rate.
- **Schema drift on `DatasetType`.** Producers and consumers of the cache share the enum, but a rolling deploy with a renamed member would orphan entries. Mitigation: enum values are append-only and never renamed (documented in `cache_policy.py` module docstring); a removal requires a `delete_pattern("market_data:<removed>:*")` step in the migration PR.

---

## Sub-Plan B — Observability Helper + Worker Logging Standardization

Three intertwined gaps from the Phase 3 metrics rollout: (1) `metrics_server_started` is silent about what was registered; (2) 45/46 workers never log a "ready" event, so operators cannot tell from logs whether dependency wiring succeeded before the blocking `consumer.run()`; (3) 6–12 entrypoints appear to skip `start_metrics_server` entirely. This section closes all three with helpers, an audit, and a mechanical sweep.

### B.1 Helper enhancement: `registered_families` on `metrics_server_started`

- File: `libs/observability/src/observability/metrics_server.py`
- Implementation:
  - After `httpd.server_bind()` succeeds, enumerate registered families via the public API:
    ```python
    from prometheus_client import REGISTRY
    families = [c.describe()[0].name for c in REGISTRY.collect() if c.describe()]
    unique = sorted(set(families))
    ```
  - Pass `registered_families=len(unique)` and `registered_sample=unique[:5]` into the existing `log.info("metrics_server_started", ...)` call.
- New event shape:
  ```json
  {"event":"metrics_server_started","service_name":"...","port":9100,"addr":"0.0.0.0",
   "registered_families": 14, "registered_sample": ["kafka_consumer_lag","..."]}
  ```
- Test: `tests/unit/test_metrics_server.py::test_started_event_reports_families` — register one Counter before calling `start_metrics_server`, assert `registered_families >= 1` and counter name appears in sample. ~30 LOC.

### B.2 New helper: `log_runtime_banner`

- File: new `libs/observability/src/observability/runtime_banner.py`
- API:
  ```python
  def log_runtime_banner(service_name: str, *, dependencies: dict[str, Any]) -> None:
      """Emit exactly one '<service>_ready' structlog event after deps wire."""
  ```
- Behavior:
  - Compute `uptime_seconds_since_boot` from a module-level `_BOOT_TS = time.monotonic()` captured at import.
  - Walk `dependencies` and apply secret masking: regex `re.compile(r"password|token|secret|key|api_key", re.I)` against KEYS → value replaced with `"***"`. Nested dicts traversed one level.
  - Read `registered_metric_families` via the same `REGISTRY.collect()` trick from B.1 (factored into `_count_families()` shared with B.1).
  - Emit ONE event: `f"{service_name}_ready"` with fields `service_name`, `dependencies`, `uptime_seconds_since_boot`, `registered_metric_families`.
- Verbatim call from migrated `worker_main.py`:
  ```python
  log_runtime_banner(
      "market_ingestion_worker",
      dependencies={
          "postgres_dsn": settings.postgres_dsn,           # masked
          "kafka_brokers": settings.kafka_brokers,
          "valkey_url": settings.valkey_url,               # masked
          "topics_subscribed": consumer.topics(),
      },
  )
  ```
- Tests (`tests/unit/test_runtime_banner.py`):
  - `test_masks_secret_keys` — pass `{"api_token": "abc", "broker": "kafka:9092"}`, assert event dict has `dependencies["api_token"] == "***"` and `dependencies["broker"] == "kafka:9092"`.
  - `test_dependency_shape_and_uptime` — assert event name == `f"{svc}_ready"`, `uptime_seconds_since_boot >= 0`, and `registered_metric_families` is `int`.

### B.3 Audit + wire the 6–12 missing `start_metrics_server` entrypoints

One-line audit task per file (mark INTENTIONAL/OVERSIGHT after investigation):

1. `services/alert/.../outbox/dispatcher_main.py` — check if alert API container hosts the dispatcher in the same process.
2. `services/content-ingestion/.../consumers/document_ready_consumer_main.py` — standalone container? if yes → OVERSIGHT.
3. `services/content-ingestion/.../scheduler/scheduler_main.py` — single-process scheduler container; likely OVERSIGHT.
4. `services/knowledge-graph/.../consumers/instrument_discovered_consumer_main.py` — confirm not co-hosted with provisional_queued_consumer.
5. `services/knowledge-graph/.../consumers/narrative_refresh_consumer_main.py` — same check.
6. `services/knowledge-graph/.../consumers/structured_enrichment_consumer_main.py` — same check.
7. `services/market-data/.../consumers/insider_transactions_consumer_main.py` — standalone container in compose.
8. `services/market-data/.../consumers/ohlcv_consumer_main.py` — standalone; likely OVERSIGHT.
9. `services/market-data/.../outbox/dispatcher_main.py` — standalone dispatcher container.
10. `services/market-ingestion/.../workers/reclaim_worker_main.py` — sidecar to worker_main? if same container → INTENTIONAL.
11. `services/nlp-pipeline/.../consumers/entity_refresh_consumer_main.py` — standalone consumer container.
12. `services/portfolio/.../consumers/instrument_consumer_main.py` — standalone.
13. `services/rag-chat/.../scheduling/brief_scheduler_main.py` — standalone scheduler container.

For each OVERSIGHT: add `start_metrics_server(service_name=..., port=9100)` after `configure_logging`. Per container: `expose: ["9100"]` in `infra/compose/docker-compose.yml`; per scrape: add job to `infra/prometheus/prometheus.yml`. Expected: ~6 INTENTIONAL (documented in `docs/observability/metrics-coverage.md`), ~6 wired.

### B.4 Fix the worst-6 logging files

Each gets the standard 10-LOC prelude:
```python
from observability.logging import configure_logging, get_logger
from observability.runtime_banner import log_runtime_banner

configure_logging(service_name="<svc>")
log = get_logger(__name__)

log.info("<svc>_starting")
try:
    # ... wire deps ...
    log_runtime_banner("<svc>", dependencies={...})  # replaces ad-hoc _ready
    consumer.run()
except Exception:
    log.exception("<svc>_startup_failed"); raise
finally:
    log.info("<svc>_stopped")
```
Files: `market-ingestion/.../workers/worker_main.py`, `market-ingestion/.../scheduler/scheduler_main.py`, `market-ingestion/.../workers/reclaim_worker_main.py`, `content-ingestion/.../workers/worker_main.py` (the pilot — match this to the documented pattern), `market-data/.../outbox/dispatcher_main.py`, `market-ingestion/.../outbox/dispatcher_main.py`.

### B.5 Waves

- **Wave B-1 — Helpers** (atomic, ships independently)
  - Files: `libs/observability/src/observability/metrics_server.py`, `libs/observability/src/observability/runtime_banner.py`, `libs/observability/tests/unit/test_metrics_server.py`, `libs/observability/tests/unit/test_runtime_banner.py`
  - LOC: ~250 (helper code + 4 tests)
  - Validation: `pytest libs/observability/tests/unit -v`; ruff + mypy clean; manual smoke — run any service locally, `curl localhost:9100/metrics` and grep logs for `metrics_server_started` showing `registered_families >= 1`.

- **Wave B-2 — Audit the 13 entrypoints** (investigation only)
  - Deliverable: `docs/audits/2026-06-06-metrics-server-coverage.md` listing each file with verdict (INTENTIONAL + rationale, or OVERSIGHT + fix), plus a Compose-cross-reference table (container → process → port).
  - LOC: 0 code, ~150 lines of audit prose.
  - Validation: peer review; verdict matches `infra/compose/docker-compose.yml` reality.

- **Wave B-3 — Wire confirmed-missing entrypoints**
  - Files: the OVERSIGHT subset from B-2 (~5–6 `*_main.py` files); `infra/compose/docker-compose.yml` (`expose: ["9100"]` per container); `infra/prometheus/prometheus.yml` (one scrape job per).
  - LOC: ~20 per file + ~30 infra YAML; total ~150 LOC.
  - Validation: `make dev`; `curl prometheus:9090/api/v1/targets` shows all new targets UP; integration test `tests/integration/test_metrics_coverage.py` asserts each newly-wired service exposes ≥1 family.

- **Wave B-4 — Apply `log_runtime_banner` + fix worst-6 logging**
  - Files: 46 `*_main.py` worker entrypoints across all services (add the banner call); the worst-6 also get `configure_logging` + module-level `log` + `_starting/_stopped/_startup_failed`.
  - LOC: ~10 per file × 46 ≈ 460 LOC; worst-6 add another ~30 LOC.
  - Validation: `pytest -k startup` per service; manual log-grep `grep '_ready' <container-logs>` confirms exactly one event per worker; CI hook (new) fails if any `*_main.py` lacks `log_runtime_banner`.

- **Wave B-5 — Grafana panel**
  - File: `infra/grafana/dashboards/workers-up.json` — add panel "Workers Ready (last 5 min)" using Loki query `sum by (service_name) (count_over_time({job=~".+"} |= "_ready" [5m]))`.
  - LOC: ~50 JSON.
  - Validation: import dashboard, verify each of the 46 workers shows ≥1 ready in last 5 min after `make dev`.

### B.6 Acceptance criteria

1. Every `metrics_server_started` log line contains `registered_families >= 1` and a non-empty `registered_sample`.
2. Every worker emits exactly one `<service_name>_ready` event after dependencies wire; event is visible in Loki within 30s of container start; CI lint hook fails any new `*_main.py` lacking the banner.
3. Every worker that should expose `/metrics` has a corresponding Prometheus scrape target UP (verified by `tests/integration/test_metrics_coverage.py`); the INTENTIONAL exclusions are enumerated in `docs/observability/metrics-coverage.md` with rationale.
4. Worst-6 logging files all emit the full `_starting → _ready → _stopped` lifecycle and `_startup_failed` on exception.

---

## Sub-Plan C — Prometheus Recording Rules + Dashboard Hygiene

The Grafana validation harness (`/tmp/grafana_validation.sh` + `/tmp/grafana_validation_results.tsv`) surfaced a class of dashboard issues that fall into three buckets: (1) genuinely missing recording rules; (2) panels that legitimately render empty under low local traffic; and (3) hygiene gaps where the harness itself isn't part of the repo and there's no CI contract preventing future BP-652-style regressions.

### C.1 Add missing recording rules

- **File**: `infra/prometheus/rules/recording-rules.yml`
- **Add two rules** under the existing `outbox` group (create the group if missing):
  - `record: job:outbox_dispatched:rate5m`
    `expr: sum by (job) (rate({__name__=~".*_outbox_dispatched_total"}[5m]))`
  - `record: job:outbox_errors:rate5m`
    `expr: sum by (job) (rate({__name__=~".*_outbox_dispatch_errors_total"}[5m]))`
- **Validate**:
  - `docker compose restart prometheus` (or `kill -HUP` the prometheus container)
  - `curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[].rules[].name' | grep outbox` — both must appear
  - Open `outbox-health.json` in Grafana — 4 previously-blank panels should render (zero values are fine; missing series is not)
- **LOC**: ~12 lines YAML
- **Result**: 4 outbox-health panels light up; harness `BROKEN` count drops by 4.

### C.2 Promote validation harness to repo

- `scripts/grafana_validation.sh` — copy `/tmp/grafana_validation.sh`. Replace hardcoded `/tmp/grafana_validation_results.tsv` with `${REPO_ROOT:-$(git rev-parse --show-toplevel)}/build/grafana_validation_results.tsv` (or `-` for stdout when `--stdout` flag passed). `mkdir -p build/` at start.
- `Makefile` — add target:
  ```
  grafana-validate:
  	@bash scripts/grafana_validation.sh
  ```
- `docs/observability/grafana-validation.md` — short README documenting:
  - How to run: `make grafana-validate` (requires Prometheus + Grafana running locally)
  - Output categories:
    - **OK** — query returned ≥1 series
    - **EMPTY-OK** — query is well-formed but no series; expected under low traffic (see C.4)
    - **BROKEN** — query references metric/label that does not exist in TSDB schema
    - **LOGQL-SKIP** — LogQL panel skipped (requires Loki; see C.5)
  - Exit codes: 0 if `BROKEN == 0`, 1 otherwise
- **Pre-PR hook candidate**: add to `scripts/hooks/pre-pr.sh` — warn (don't block) on `BROKEN > 0`
- **LOC**: ~40 lines shell tweaks + ~80 lines markdown

### C.3 Dashboard datasource-UID contract check

- `scripts/check_dashboard_datasource_uids.py` — for each `*.json` in `infra/grafana/dashboards/`, walk panels and templating, extract every `datasource.uid` (and `targets[].datasource.uid`). Load `infra/grafana/provisioning/datasources/datasources.yml`, collect the set of declared `uid:` values. Assert dashboard set ⊆ datasource set; print offenders with file:panel coordinates.
- `tests/observability/test_dashboard_datasource_contract.py` — pytest wrapper that invokes the script via `subprocess` and asserts exit 0; one fixture dashboard with a deliberately-bad UID to assert the script catches it (xfail-style).
- **LOC**: ~30 LOC script + ~25 LOC test + 1 fixture JSON
- **Validation**: deliberately rename a `uid:` in `datasources.yml`; test must fail; revert; test passes.
- **CI integration**: runs under existing `pytest tests/observability/` invocation; catches BP-652 recurrences automatically.

### C.4 Document EMPTY-OK panels

- `docs/observability/dashboards.md` — add a table, one row per dashboard, listing which panels require real traffic. Initial entries (from harness output):
  - `kafka-pipeline.json` — panels using `kafka_messages_produced_total` and `kafka_consumer_lag` require running service producers; 10 EMPTY-OK locally.
  - `eodhd-health.json` — 7 panels (`s2_mi_provider_*` family) require first scheduled provider fetch (hourly cron).
  - `worker-pipeline-throughput.json` — 2 path-insight panels require worker tick to produce counters.
  - `api-usage-analytics.json` — 4 LogQL panels require Loki ingestion (see C.5).
  - `error-observability.json` — 5 LogQL panels require Loki `unhandled_exception` events.
  - `service-overview.json` — `$job` template variable; harness substitutes wrong placeholder, panels work in Grafana UI. Document as a harness limitation, not a dashboard bug.
- **LOC**: ~50 lines markdown
- Goal: reviewers seeing "0 series" in screenshots don't open false-positive issues.

### C.5 Loki health check

- Independent of dashboards. The harness flagged: `api-usage-analytics` LogQL queries failed at design time because Loki's `/loki/api/v1/labels` was empty for the market-ingestion stream.
- **Verify**:
  - `curl -s http://localhost:3100/loki/api/v1/labels | jq '.data | length'` — must be `> 0`
  - `curl -s http://localhost:3100/loki/api/v1/label/container/values | jq '.data'` — must list every running worker container
- **If empty or sparse**: investigate Alloy `keep` regex (BP-321 lineage). New worker container names (recent: `worker-path-insight`, `worker-summary-3phase`, `worker-relevance-scorer`) may not match the existing keep pattern in `infra/alloy/config.alloy`. Update the regex; restart Alloy; re-verify.
- **Deliverable**: short audit appended to `docs/observability/grafana-validation.md` documenting which containers ship logs and the current Alloy keep regex.

### C.6 Waves

| Wave | Task | Files | LOC | Time | Validation |
|------|------|-------|-----|------|------------|
| **C-1** | Add 2 recording rules | `infra/prometheus/rules/recording-rules.yml` | ~12 | 10 min | `curl /api/v1/rules` shows both; outbox-health panels render |
| **C-2** | Move harness + Make target + README | `scripts/grafana_validation.sh`, `Makefile`, `docs/observability/grafana-validation.md` | ~120 | 1 h | `make grafana-validate` produces TSV in `build/`, exit 0 |
| **C-3** | Dashboard UID contract test | `scripts/check_dashboard_datasource_uids.py`, `tests/observability/test_dashboard_datasource_contract.py`, fixture | ~55 | 45 min | Pytest green; mutation test fails |
| **C-4** | EMPTY-OK documentation | `docs/observability/dashboards.md` | ~50 | 30 min | Doc review |
| **C-5** | Loki ingestion audit + Alloy regex fix | `infra/alloy/config.alloy`, `docs/observability/grafana-validation.md` | ~10 + audit notes | 1–2 h | `/loki/api/v1/label/container/values` lists all workers |

### C.7 Acceptance criteria

- `make grafana-validate` runs from a clean checkout, produces a TSV under `build/`, and exits 0 when `BROKEN == 0`.
- `curl http://localhost:3100/loki/api/v1/label/container/values` returns every running worker container name.
- The 4 outbox-health panels (`outbox dispatched rate`, `outbox errors rate`, and their per-job breakdowns) show non-zero data after the first outbox dispatch event.
- `pytest tests/observability/test_dashboard_datasource_contract.py` passes; deliberately renaming a `uid:` in `datasources.yml` causes the test (and CI) to fail.
- `docs/observability/dashboards.md` lists every EMPTY-OK panel with its traffic precondition, so reviewers do not file false-positive "empty panel" issues.

---

## Sub-Plan D — R42 / BP-590 Parallel-Session Mitigation

R42 / BP-590 told us to use git worktrees, but it does not *prevent* a sibling session — user-initiated terminal or skill-spawned subprocess — from running `git commit -a` on the main checkout while a worktree agent is mid-flight. The recent PLAN-0099 W4 integration session exhibited the pattern four times: a bulk-commit landed on `feat/plan-0099-w4` (commit `6ed7ec04`, authored "Arnau Rodon", not Claude), HEAD was rewound leaving Phase 3a/3b/4 cherry-picks orphaned, `unresolved_resolution_worker_main.py` lost its `start_metrics_server` import in a selective revert, and the Compose Kafka tuning (`KAFKA_CONTROLLER_QUORUM_REQUEST_TIMEOUT_MS` et al.) was silently rolled back. We need hard prevention, soft detection, and recovery tooling.

### D.1 Diagnose what's actually happening
- Inspect `~/.claude/projects/-Users-arnaurodon-Projects-University-final-thesis-worldview/` for session logs that overlap in wall-clock time on the same worktree path.
- Distinguish user-initiated parallel sessions (multiple terminals attached to the same checkout) from skill-spawned ones (`/loop`, `/implement` re-firing a sub-agent that inherits cwd).
- Audit `scripts/hooks/`, `.git/hooks/`, and any pre-commit handlers for auto-commit-on-file-change behaviour.
- ~1–2 hours; deliverable is `docs/audits/2026-06-06-parallel-session-triggers.md` enumerating each trigger and whether it survived a fix.

### D.2 Hard prevention: filesystem-level lock
- Create `.worktree-lock` at the worktree root containing `{pid, agent_id, started_at, branch}`. Any session creates it on startup, removes it on clean exit (trap on EXIT/INT/TERM).
- On startup, every session reads `.worktree-lock`. If present *and* `kill -0 $PID` succeeds: refuse to touch git state, print warning with override instructions (`rm .worktree-lock`).
- Implement in `scripts/worktree_lock.sh` with `acquire`, `release`, `check` subcommands. Wire into `.git/hooks/pre-commit` so even manual `git commit` is blocked when another agent holds the lock.
- Pros: hard prevention regardless of invocation path. Cons: stale-lock recovery needs manual `rm`; trap-on-crash may miss SIGKILL.
- ~80 LOC bash.

### D.3 Soft prevention: commit-author signature
- Convention already requires `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>` on Claude commits.
- Add a pre-commit check: if `git diff --cached --name-only` touches `services/` or `libs/` AND `$USER == arnaurodon` AND the commit message lacks the Co-Authored-By trailer, prompt "is this a manual edit? [y/N]". Also add a CI grep step on push.
- ~30 LOC bash.

### D.4 Detection + recovery: orphan-commit watchdog
- After every `git cherry-pick`, run `scripts/orphan_commit_check.sh` which walks `git fsck --unreachable` and `git reflog` for commits authored by Claude in the last 24h that no branch ref points at. Warn loudly listing SHA + subject + suggested `git cherry-pick <sha>` recovery command.
- Useful post-integration audit: "did anything I cherry-picked get rewound while I wasn't looking?"
- ~40 LOC bash.

### D.5 Documentation: parallel-session pattern catalog
- Append to `docs/BUG_PATTERNS.md` (or the BP-590 detail file under `docs/bug-patterns/`) a section "Parallel-session reverts — full taxonomy":
  - **Bulk-commit pattern** (case 1) — detection: unexpected commit author + large file count; recovery: `git revert <sha>`, re-stage; prevention: lockfile.
  - **Branch-rewind pattern** (case 2) — detection: `git reflog` shows HEAD jump backward; recovery: `git reflog` + cherry-pick orphans; prevention: lockfile + post-cherry-pick watchdog.
  - **Selective file revert** (case 3) — detection: `git log -p <file>` shows your change present then removed; recovery: re-apply diff; prevention: lockfile.
  - **YAML/JSON revert** (case 4) — same as case 3 but on config files; often missed because tests still pass. Detection: explicit diff against expected state in CI.

### D.6 Update CLAUDE.md "Parallel Sessions" guidance
Append after the existing R42 paragraph:

> If you observe spontaneous commits, BEFORE re-cherry-picking run `bash scripts/orphan_commit_check.sh` to confirm the rewind and locate orphaned SHAs, then `bash scripts/worktree_lock.sh acquire` to block sibling sessions before re-applying work.

### D.7 Waves

| Wave | Scope | Files | Validation | Hours |
|------|-------|-------|------------|-------|
| **D-1** | Diagnostic investigation (D.1) | `docs/audits/2026-06-06-parallel-session-triggers.md` | Audit file lists ≥3 concrete trigger sources with evidence | 2 |
| **D-2** | Worktree lockfile (D.2) | `scripts/worktree_lock.sh`, `.git/hooks/pre-commit`, `.gitignore` (`.worktree-lock`) | Two sessions in same checkout: second refuses git ops; lockfile auto-removed on clean exit | 4 |
| **D-3** | Co-Authored-By enforcement (D.3) | `scripts/check_coauthor.sh`, `.github/workflows/lint.yml` | Commit on `services/` without trailer → CI red; manual override env var documented | 1 |
| **D-4** | Orphan-commit watchdog (D.4) | `scripts/orphan_commit_check.sh`, hook into `/implement` skill post-cherry-pick step | Force a rewind in a test repo; watchdog flags orphan within 60s | 1 |
| **D-5** | Docs + CLAUDE.md update (D.5 + D.6) | `docs/BUG_PATTERNS.md`, `CLAUDE.md` | `grep "Parallel-session reverts" docs/BUG_PATTERNS.md` returns hit; CLAUDE.md diff reviewed | 1 |

### D.8 Acceptance criteria
- Two simultaneous Claude sessions in the same checkout: first acquires the lock, second refuses to modify git state with a clear override message.
- After any `git cherry-pick`, the orphan-commit watchdog flags any rewound Claude-authored commit within 60 seconds.
- Every Claude-authored commit touching `services/` or `libs/` includes `Co-Authored-By: Claude Sonnet 4.6`; CI flags commits that don't.
- `.worktree-lock` is gitignored and never committed.
- Post-mortem of PLAN-0099 W4 integration session is replayable: all four revert cases (bulk-commit, branch-rewind, selective file revert, YAML revert) would have been prevented or detected within 1 minute.

### D.9 Risk + tradeoffs
- **Lockfile overhead on session boot** — measured target <50ms; one stat + one PID liveness check. Acceptable.
- **Stale locks from SIGKILL'd sessions** — trap can't catch SIGKILL or hard power-off. Manual override path (`rm .worktree-lock`) documented in lockfile error message and CLAUDE.md.
- **Power users running deliberate parallel work** — opt-out via `WORLDVIEW_DISABLE_WORKTREE_LOCK=1` env var; documented as expert-only.
- **CI Co-Authored-By check false-positives** on legitimate human commits — mitigated by the `$USER`-based heuristic plus interactive prompt; CI uses warning-not-error mode for first 2 weeks.
- **Tooling surface area grows** — three new scripts; mitigated by keeping each <100 LOC bash with shellcheck-clean and a unit test per script under `scripts/tests/`.

---

## Execution order recommendation

| Day | Wave | Why |
|---|---|---|
| Day 1 | **B-1** (helpers) + **C-1** (recording rules) | Atomic, ~250 LOC each, unblock B/C/dashboards |
| Day 1 | **C-3** (UID contract test) | Independent; prevents BP-652 recurrence |
| Day 2 | **B-2** (audit 13 entrypoints) + **D-1** (parallel-session diagnostic) | Investigation-only; deliver verdicts |
| Day 2-3 | **A-1 → A-2** (cache taxonomy + class) | Feature kickoff; parallel with B/D |
| Day 3 | **B-3** (wire missing entrypoints), **D-2** (lockfile) | Apply B-2 verdicts; ship parallel-session lock |
| Day 4 | **A-3** (wire 3 use cases) + **C-2** (harness to repo) + **D-3/4/5** (commit signature, watchdog, docs) | Parallel ship |
| Day 5 | **A-4 / A-5** (cache metrics + cleanup) + **B-4** (banner sweep across 46 workers) + **C-4 / C-5** (docs + Loki audit) + **B-5** (Grafana panel) | Final wave |

## Acceptance gate for PLAN-0107

Plan reaches `✅ completed` when:
1. All A-1..A-5 acceptance criteria in §A.4 met (cache live + provider-swap demonstrated).
2. All B.6 criteria met (every metrics_server_started reports registered_families; every worker emits _ready).
3. All C.7 criteria met (make grafana-validate exit 0; UID contract test green; Loki ships logs for every worker).
4. All D.8 criteria met (lockfile + watchdog + Co-Authored-By enforcement live; PLAN-0099 W4 replay would have been blocked).
