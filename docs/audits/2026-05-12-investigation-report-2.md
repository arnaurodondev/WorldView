# Investigation Report: 13 CI Failures — Batch 2

**Date**: 2026-05-12
**Branch**: fix/ci-failures-cleanup
**Severity**: HIGH (blocked merge)
**Status**: All root causes identified

## 1. Issue Summary

13 CI jobs failed on the second CI run triggered by commits `1572e01c` / `3b0dcc9f` (the Batch 1 fixes). The failures fall into 7 independent root causes spanning 4 categories: Docker infrastructure (minio image tag removed), service startup (JWKS fetch with no api-gateway in profile), test isolation (shared DB / stale mocks / missing dependencies), and missing CI dependency.

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| `minio/mc:RELEASE.2024-01-16T16-07-38Z not found` | CI logs for 6 E2E jobs | RC-1: image tag deleted from DockerHub |
| `container worldview-test-alert-1 exited (3)` | CI E2E — alert log | RC-2: uvicorn exits on RuntimeError from startup() |
| `raise RuntimeError("JWKS startup failed after 3 attempts")` | `alert/infrastructure/middleware/internal_jwt.py:123` | RC-2: JWKS fetch raises on 3 failures |
| `FileNotFoundError: .venv/bin/alembic` | CI Integration Tests — alert log | RC-3: hardcoded venv path |
| `assert 'XNAS' == 'US'` | CI Integration Tests — market-data log | RC-4: AAPL/XNAS inserted by earlier test |
| `test_repositories.py:102: exchange="XNAS"` for symbol=AAPL | `test_repositories.py` | RC-4: contaminates shared test DB |
| `POST /v1/auth/dev-login unexpected` | CI nlp-pipeline unit log | RC-5: 2 auth calls, 1 mock |
| `_get_internal_jwt()` called at lines 199 and 277 | `market_data_client.py` | RC-5: confirms 2 calls per get_ohlcv |
| `ModuleNotFoundError: No module named 'nlp_pipeline'` | CI rag-chat unit log | RC-6a: cross-service import |
| `2 responses mocked but not requested` | CI rag-chat unit log | RC-6b: 4 mocks, only 2 consumed |
| Timeout caught → `return {}` immediately (no retry) | `entity_context_client.py:226` | RC-6b: retries only 5xx, not timeouts |
| `ModuleNotFoundError: No module named 'structlog'` | CI eval-script log | RC-7: structlog missing from pip install |
| CI workflow installs `pytest pytest-asyncio httpx pyarrow` only | `.github/workflows/retrieval-eval.yml` | RC-7: structlog not listed |

## 3. Root Causes and Fixes

### RC-1 — minio/mc Docker image tag deleted from DockerHub (6 E2E jobs)

**Jobs**: E2E — content-ingestion, content-store, knowledge-graph, market-data, market-ingestion, nlp-pipeline

**Root cause**: `minio/mc:RELEASE.2024-01-16T16-07-38Z` (and `minio/minio:RELEASE.2024-01-16T16-07-38Z`)
are no longer available on DockerHub. The `minio-init-test` service in
`infra/compose/docker-compose.test.yml:128` uses this exact tag. All six E2E profiles that
depend on `minio-init-test` fail immediately on pull.

**Location**: `infra/compose/docker-compose.test.yml:103,128` (and `docker-compose.yml:33,56`)

**Fix**: Update both `minio/minio` and `minio/mc` to a newer stable tag available on DockerHub
(e.g., `RELEASE.2024-10-07T06-42-08Z`). Verify the tag exists before committing:
`docker pull minio/mc:<tag>`.

---

### RC-2 — Alert + Portfolio InternalJWTMiddleware raises RuntimeError at startup (2 E2E jobs)

**Jobs**: E2E — alert, E2E — portfolio

**Root cause**: Both service lifespan handlers call `await jwt_mw.startup()`. The startup method
(at `alert/infrastructure/middleware/internal_jwt.py:93`) fetches the public key from
`{api_gateway_url}/internal/jwks`. The `alert-test` and `portfolio-test` compose profiles do
NOT include an api-gateway container. After 3 failed attempts, startup raises:
```
RuntimeError: JWKS startup failed after 3 attempts — cannot start without public key
```
This propagates through the FastAPI lifespan → uvicorn exits with code 3.

**Why now**: In the previous CI run the alert container started successfully (likely served from
Docker build cache of a main image built before the JWKS-raise behavior was added in commit
`625c9672`). The current CI run rebuilt the image fresh, exposing the failure.

**Location**: `services/alert/configs/docker.env` and `services/portfolio/configs/docker.env`
(missing `ALERT_INTERNAL_JWT_SKIP_VERIFICATION=true` /
`PORTFOLIO_INTERNAL_JWT_SKIP_VERIFICATION=true`)

**Fix**: Add `ALERT_INTERNAL_JWT_SKIP_VERIFICATION=true` to `services/alert/configs/docker.env`
and `PORTFOLIO_INTERNAL_JWT_SKIP_VERIFICATION=true` to `services/portfolio/configs/docker.env`.
These are dev/test compose env files — skip_verification is acceptable in this context and the
middleware already supports it.

---

### RC-3 — Alert integration conftest hardcodes `.venv/bin/alembic` (1 integration job)

**Job**: Integration Tests — alert (testcontainers)

**Root cause**: `services/alert/tests/integration/conftest.py:84` constructs the alembic binary
path as:
```python
alembic_bin = os.path.join(service_dir, ".venv", "bin", "alembic")
```
CI installs packages globally into the runner's Python, not into a `.venv` directory. So the
constructed path does not exist.

**Location**: `services/alert/tests/integration/conftest.py:84`

**Fix**:
```python
import shutil
alembic_bin = shutil.which("alembic")
if not alembic_bin:
    raise RuntimeError("alembic not found on PATH")
```

---

### RC-4 — Shared test DB contaminates `test_lookup_by_ticker_live_db` with AAPL/XNAS (1 integration job)

**Job**: Integration Tests — market-data (testcontainers)

**Root cause**: The market-data integration suite uses a session-scoped testcontainer database
shared across all test functions. `test_repositories.py:102` inserts `Instrument(symbol="AAPL",
exchange="XNAS")`. When `test_instrument_lookup_integration.py::test_lookup_by_ticker_live_db`
subsequently runs:

1. `_seed_instrument()` upserts AAPL/US (new row — different conflict key `(symbol, exchange)`)
2. `InstrumentLookupUseCase.execute(symbol="AAPL")` calls `find_by_symbol_icase("AAPL")`
3. `find_by_symbol_icase` returns the FIRST matching row — which may be AAPL/XNAS (inserted
   earlier), not AAPL/US.

The test then fails: `assert result.instrument.exchange == 'US'` → `AssertionError: assert 'XNAS' == 'US'`

This failure became visible after RC-3 from Batch 1 fixed the migration assertion (which was
previously the first failure, masking this one).

**Location**: `services/market-data/tests/integration/test_instrument_lookup_integration.py:65`

**Fix**: Use a unique ticker symbol in `test_instrument_lookup_integration.py` that no other
integration test uses (e.g., `_SYMBOL = "AAPL_LK"` and update all references in that file).
Alternatively add `ORDER BY created_at DESC LIMIT 1` to `find_by_symbol_icase` so the most
recently inserted row is returned, which is deterministic per test.

---

### RC-5 — NLP-pipeline `MarketDataClient` makes 2 auth calls; tests mock only 1 (1 unit job, 2 ERRORs)

**Job**: Test Services — nlp-pipeline (unit)

**Root cause**: `MarketDataClient.get_ohlcv()` calls `_get_internal_jwt()` at line 199 (before
ticker resolution) and again at line 277 (before OHLCV fetch). When the first mint fails (auth
endpoint returns 4xx or 5xx), `self._token` remains `None`; the cache miss causes a second mint
attempt. Two affected tests:

- `test_falls_back_to_no_header_when_gateway_unreachable`: registers ONE mock for
  `POST /v1/auth/dev-login` (503). The client makes TWO dev-login calls → second is unmocked →
  cleanup error: `"The following requests were not expected: POST /v1/auth/dev-login"`.

- `test_service_token_failure_does_not_fall_back_to_dev_login`: registers ONE mock for
  `POST /internal/v1/service-token` (401). Client makes TWO service-token calls → cleanup error.
  (The test comment already documents that 2 calls happen, but only 1 mock was registered.)

**Location**: `services/nlp-pipeline/tests/unit/infrastructure/test_market_data_client.py`
(around lines 247–268 and 414–443)

**Fix**: Add a second mock response (same status code) for the auth endpoint in each failing test,
OR pass `is_reusable=True` to `httpx_mock.add_response()` if the pytest_httpx version supports it.

---

### RC-6a — rag-chat test imports from `nlp_pipeline` (cross-service import) (1 unit job, 2 FAILUREs)

**Job**: Test Services — rag-chat (unit)

**Root cause**: `services/rag-chat/tests/unit/test_metrics_emission.py:66,81`:
```python
from nlp_pipeline.infrastructure.metrics.prometheus import record_display_score_path
```
`nlp_pipeline` is not installed in the rag-chat CI context; only rag-chat's own dependencies
are installed. This is also an architectural violation (cross-service import from test code).

**Location**: `services/rag-chat/tests/unit/test_metrics_emission.py:66,81`

**Fix**: `record_display_score_path` should live in a shared module (e.g., `observability` lib)
or in rag-chat's own metrics module if rag-chat is the caller. Remove the cross-service import.
Alternatively, if the function is only tested in the context of nlp-pipeline, move the tests to
that service's test suite.

---

### RC-6b — rag-chat `test_timeout_enforced_returns_empty_context` registers 4 mocks, only 2 consumed (1 unit job, 1 ERROR)

**Job**: Test Services — rag-chat (unit)

**Root cause**: The test at `test_entity_context_client.py:148` registers 4 timeout exceptions:
```python
for _ in range(4):  # enough for both calls + retry attempts
    httpx_mock.add_exception(httpx.TimeoutException("timed out"))
```
The comment assumes retries happen on timeout. But `EntityContextClient._get_with_retry()`
(line 188) only retries on `resp.status_code >= 500`. On `httpx.TimeoutException`, the except
block at line 226 returns `{}` immediately without retry. Result: only 2 HTTP calls are made
(one per endpoint, no retry), consuming 2 mocks; 2 remain unused → cleanup error:
`"The following responses are mocked but not requested"`.

**Location**: `services/rag-chat/tests/unit/infrastructure/clients/test_entity_context_client.py:148`

**Fix**: Change `range(4)` to `range(2)` — one exception per endpoint, no retry on timeout.

---

### RC-7 — Retrieval eval CI job missing `structlog` dependency (1 eval job)

**Job**: Retrieval Eval / Eval-script unit tests

**Root cause**: `.github/workflows/retrieval-eval.yml` unit-tests job pip-installs only:
```
pytest pytest-asyncio httpx pyarrow
```
But `scripts/eval_retrieval.py:56` has `import structlog` at module level. Test collection fails
immediately: `ModuleNotFoundError: No module named 'structlog'`.

**Location**: `.github/workflows/retrieval-eval.yml` (unit-tests job, Install test dependencies step)

**Fix**:
```yaml
python -m pip install pytest pytest-asyncio httpx pyarrow structlog
```

## 4. Failure × Root Cause Matrix

| CI Job | RC-1 | RC-2 | RC-3 | RC-4 | RC-5 | RC-6a | RC-6b | RC-7 |
|--------|------|------|------|------|------|-------|-------|------|
| E2E — content-ingestion | ✓ | | | | | | | |
| E2E — content-store | ✓ | | | | | | | |
| E2E — knowledge-graph | ✓ | | | | | | | |
| E2E — market-data | ✓ | | | | | | | |
| E2E — market-ingestion | ✓ | | | | | | | |
| E2E — nlp-pipeline | ✓ | | | | | | | |
| E2E — alert | | ✓ | | | | | | |
| E2E — portfolio | | ✓ | | | | | | |
| Integration Tests — alert | | | ✓ | | | | | |
| Integration Tests — market-data | | | | ✓ | | | | |
| Test Services — nlp-pipeline (unit) | | | | | ✓ | | | |
| Test Services — rag-chat (unit) | | | | | | ✓ | ✓ | |
| Retrieval Eval / Eval-script | | | | | | | | ✓ |

## 5. Recommended Fix Order

1. **RC-1** — Update minio/mc and minio/minio tags in both docker-compose.yml files (unblocks 6 E2E)
2. **RC-2** — Add skip_verification=true to alert and portfolio docker.env (unblocks 2 E2E)
3. **RC-3** — Fix alert conftest alembic path (unblocks integration Tests — alert)
4. **RC-4** — Use unique ticker in lookup integration test (unblocks Integration Tests — market-data)
5. **RC-5** — Add second auth mock in 2 nlp-pipeline tests (unblocks unit nlp-pipeline)
6. **RC-6a** — Remove cross-service import from rag-chat test (unblocks 2 rag-chat FAILUREs)
7. **RC-6b** — Change range(4) to range(2) in entity_context_client test (unblocks 1 rag-chat ERROR)
8. **RC-7** — Add structlog to retrieval eval CI pip install (unblocks eval job)

## 6. New Bug Patterns

- **BP-469**: Minio Docker image tag expiry breaks all E2E tests that use minio-init-test (cross-cutting). Mitigation: pin to `latest` or use a tag from the last 90 days and add a CI step that validates the tag exists before the compose up.
- **BP-470**: InternalJWTMiddleware raises RuntimeError on JWKS failure, causing uvicorn exit code 3. Test compose profiles that include a service with JWKS startup but no api-gateway MUST set `INTERNAL_JWT_SKIP_VERIFICATION=true` in the service's test env.
- **BP-471**: Session-scoped testcontainer DB shared across integration test files causes symbol/exchange collisions. Each test file should use a unique ticker symbol or use function-scoped DB isolation.
