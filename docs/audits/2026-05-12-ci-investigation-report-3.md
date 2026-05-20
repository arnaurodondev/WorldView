# Investigation Report: CI Batch 3 + Gitops Sync (2026-05-12 Session 3)

**Date**: 2026-05-12
**Branch**: fix/ci-failures-cleanup
**Severity**: HIGH (7 E2E tests still failing after batch 2 fixes)
**Status**: All root causes identified and fixed

---

## 1. Issue Summary

After the Batch 1 (`1572e01c`) and Batch 2 (`865fee5b` + `90441519` + `8a0583fc`) CI fixes, 7 E2E test jobs were still failing. This report covers:

1. **Part A — Gitops sync audit**: Verified that 7 out of 10 service docker.env files had drifted from their gitops counterparts; synced all changes.
2. **Part B — Remaining CI failures**: Identified 2 new root causes (RC-D and RC-E) affecting 7 E2E jobs.

---

## 2. Gitops Sync Status

### Pre-sync drift found

| Service | Drift | Action |
|---------|-------|--------|
| alert | JWT token missing `aud` claim; `ALERT_INTERNAL_JWT_SKIP_VERIFICATION=true` missing | Synced to gitops |
| portfolio | `PORTFOLIO_INTERNAL_JWT_SKIP_VERIFICATION=true` missing | Synced to gitops |
| content-ingestion | `CONTENT_INGESTION_NEWSAPI__POLL_INTERVAL_SECONDS=14400` missing | Synced to gitops |
| content-store | `CONTENT_STORE_INTERNAL_JWT_SKIP_VERIFICATION=true` missing | Synced to gitops |
| knowledge-graph | `CYPHER_ENABLED=false` (should be `true`); skip_verification missing | Synced to gitops |
| market-ingestion | Empty API key declarations missing; skip_verification missing | Synced to gitops |
| nlp-pipeline | `NLP_PIPELINE_INTERNAL_JWT_SKIP_VERIFICATION=true` missing | Synced to gitops |
| rag-chat | `RAG_CHAT_INTERNAL_JWT_SKIP_VERIFICATION=true` missing | Synced to gitops |
| api-gateway | Rate limit 300 → 10000 | Synced to gitops |
| market-data | In sync | No action |

### Post-sync validation

Deleted all worldview docker.env files with `make dev-clean`, then re-ran `worldview-gitops/scripts/setup-dev.sh`. All 10 services populated successfully. The colleague onboarding flow now works correctly.

### Critical note on rag-chat

worldview's docker.env contained the **eval** config (header: "env/eval/rag-chat.env") rather than the dev config. The gitops dev config is correct for `make dev`. setup-dev.sh overwrites with the correct dev version. The eval config should only be used via `worldview-gitops/scripts/setup-eval.sh`.

---

## 3. Remaining CI Failures (RC-D and RC-E)

### RC-D — InternalJWTMiddleware.startup() missing skip_verification early-return in 6 services

**Jobs affected**: E2E — portfolio, content-ingestion, content-store, nlp-pipeline, knowledge-graph, market-ingestion

**Root cause**: The Batch 3 fix (`8a0583fc` RC-A) added `if self._skip_verification: return` to the startup() method, but **only to the alert service's copy** of InternalJWTMiddleware. Each service has its own middleware copy. The 6 affected services all call `await jwt_middleware.startup()` from their lifespan without try-except, so the RuntimeError propagates and crashes uvicorn.

**Why this was masked until now**:
- Before Batch 2 (`865fee5b`): those 6 E2E jobs failed on minio image pull (RC-1). The services never started, so the JWKS crash was invisible.
- After minio fix: services started for the first time in CI → JWKS crash exposed.
- Batch 2 added `INTERNAL_JWT_SKIP_VERIFICATION=true` to docker.env.example for those services, but startup() still didn't check the flag.
- Batch 3 (`8a0583fc`) added the flag to more examples AND fixed alert's startup() — but missed the other 5 services.

**Evidence**: `grep -c "if self._skip_verification:" */middleware/internal_jwt.py` shows:
- alert: 2 (init + startup) ← fixed
- market-data: 2 (init + startup) ← had fix pre-existing
- rag-chat: 2 (init + startup) ← had fix pre-existing
- content-ingestion: 1 (init only) ← missing startup fix
- content-store: 1 (init only) ← missing startup fix
- knowledge-graph: 1 (init only) ← missing startup fix
- market-ingestion: 1 (init only) ← missing startup fix
- nlp-pipeline: 1 (init only) ← missing startup fix
- portfolio: 1 (init only) ← missing startup fix

**Fix applied**:
- Added `if self._skip_verification: return` to `startup()` in 6 middleware files.
- Portfolio additionally required `app.state._internal_jwt_skip_verification = True` in `__init__` (to inform the readyz check) and a readyz fix (see RC-E-portfolio below).

### RC-E — Alert /readyz makes S1 (Portfolio) connectivity a hard healthcheck dependency

**Job affected**: E2E — alert

**Root cause**: After RC-A fixed alert's startup(), the container starts successfully. But the Docker healthcheck hits `/readyz`, which checks 4 dependencies including `s1_client.health_check()` (GET `http://portfolio:8000/internal/v1/health`). Portfolio is not in the `alert-test` compose profile. The connection fails → `s1_healthy = False` → `ok = False` → `/readyz` returns 503 → all 5 healthcheck retries fail → container marked `unhealthy` → `docker compose --wait` exits 1.

**The contradiction**: `S1Client`'s module docstring explicitly states:
> "Best-effort: if S1 is unreachable or returns an error, methods return empty results and never raise. This follows the deployment gate contract (PRD §12.1 — S10 degrades gracefully when S1 is unavailable)."

Making `/readyz` return 503 when S1 is unreachable directly contradicts this contract.

**Fix applied**: Changed the S1 check in `services/alert/src/alert/api/health.py` from blocking to informational:
- Before: `checks["s1"] = "ok" if s1_healthy else "error"; if not s1_healthy: ok = False`
- After: `checks["s1"] = "ok" if s1_healthy else "degraded"` (ok not modified)

**RC-E-portfolio sub-case**: Portfolio's `readyz()` has a unique check `F-003B: JWKS public key must be loaded before accepting traffic` at `app.py:221`. After RC-D's fix (startup early-returns without setting `_internal_jwt_public_key`), this check finds the key absent and returns 503. Fix: added `skip_jwt = getattr(app.state, "_internal_jwt_skip_verification", False)` guard before the key check.

---

## 4. Root Cause × Job Matrix (Full Picture)

| E2E Job | RC-1 (minio) | RC-2 (skip env) | RC-A (startup fix) | RC-B (nlp db url) | RC-D (startup all) | RC-E (readyz s1) |
|---------|--------|--------|--------|--------|--------|--------|
| content-ingestion | ✓ B2 | | | | ✓ B3 | |
| content-store | ✓ B2 | | | | ✓ B3 | |
| knowledge-graph | ✓ B2 | | | ✓ B3 | ✓ B3 | |
| market-data | ✓ B2 | | | | | |
| market-ingestion | ✓ B2 | | | | ✓ B3 | |
| nlp-pipeline | ✓ B2 | | | ✓ B3 | ✓ B3 | |
| alert | | ✓ B2 | ✓ B3 | | | ✓ B3 |
| portfolio | | ✓ B2 | ✓ B3 | | ✓ B3 | ✓ B3 |

Batches: B2 = `865fee5b`+`90441519`, B3 = `8a0583fc`+`3a5bcb68` (this session)

---

## 5. RC-F — F-003B readyz JWKS guard blocks 3 services in `make dev` (skip_verification mode)

**Discovered**: During `make dev` after the B3 CI fixes were applied.

**Jobs affected**: knowledge-graph, content-store, nlp-pipeline containers in the full dev stack.

**Root cause**: The F-003B readyz check `if _internal_jwt_public_key is None: ok = False` was added to `/readyz` in these three services without a corresponding guard for `skip_verification=True` mode. When skip_verification=True, `startup()` returns early without loading the JWKS key, so the check always fires. Additionally, unlike portfolio (which was already fixed in RC-D), these three services' `InternalJWTMiddleware.__init__` never set `app.state._internal_jwt_skip_verification = True`, so the health.py had no way to detect skip mode.

**Fix applied** (commit `86b019a5`):
- Added `contextlib.suppress(AttributeError): app.state._internal_jwt_skip_verification = True` to `InternalJWTMiddleware.__init__` in 3 services.
- Added `skip_jwt = getattr(app.state, "_internal_jwt_skip_verification", False)` guard to `readyz()` in all 3 health.py files.

---

## 6. New Bug Patterns Added

- **BP-470** (updated): Extended to clarify the two-part fix (env var + startup() check in ALL copies) and the lesson: when a feature flag is added, ALL code paths must be updated simultaneously.
- **BP-472** (new): Best-effort S1 dependency in alert `/readyz` — readyz should not return 503 for dependencies documented as degradable.
- **BP-473** (new): F-003B readyz JWKS guard blocks containers in skip_verification mode — `_internal_jwt_skip_verification` flag must be set on `app.state` in `__init__` AND health.py must check it before returning 503.

---

## 8. Batch 4 — Remaining CI Failures (RC-G through RC-K)

**Commit**: `e6ef9bd0` (2026-05-12 Session 4)

### RC-G — E2E conftest fixtures missing X-Internal-JWT header (8 services)

**Jobs affected**: All 8 E2E jobs (alert, portfolio, content-ingestion, content-store, market-ingestion, market-data, knowledge-graph, nlp-pipeline)

**Root cause**: After Batch 3 added `INTERNAL_JWT_SKIP_VERIFICATION=true` to all `docker.env.example` files (RC-2), services start without fetching JWKS. But `InternalJWTMiddleware` still requires the `X-Internal-JWT` header on non-health routes — it just skips signature verification. Every E2E test client fixture was making requests WITHOUT the header.

- portfolio: header was present, but `tenant_id: ""` (empty string) caused `{"detail":"Missing tenant_id in JWT"}` on tenant-scoped routes
- content-ingestion: `_E2E_INTERNAL_JWT` was defined at module level but never wired into the `e2e_client` headers
- alert, market-ingestion, knowledge-graph, nlp-pipeline, content-store, market-data: no JWT at all

**Fix**: Added `_make_e2e_system_jwt()` + `_INTERNAL_JWT` constant to all 8 conftest files; wired `headers={"X-Internal-JWT": _INTERNAL_JWT}` into `e2e_client`. Portfolio: changed `tenant_id: ""` → `tenant_id: "e2e-tenant"`.

### RC-H — Unit test assertions not updated after B3 behavior changes

**Tests affected**: `services/alert/tests/unit/api/test_health.py`, `services/portfolio/tests/test_health.py`

- **alert** `test_readyz_503_when_s1_unhealthy`: RC-E changed S1 from hard-blocking to informational (`"degraded"`), but the test still asserted 503. Renamed to `test_readyz_200_when_s1_degraded` and updated assertions.
- **portfolio** `test_readyz_jwks_not_loaded`: `create_app()` sets `app.state._internal_jwt_skip_verification = True` from the test env's `PORTFOLIO_INTERNAL_JWT_SKIP_VERIFICATION=true`. The RC-F readyz guard then SKIPS the JWKS check, falls through to DB check, returns `reason: "db"` not `"jwks_not_loaded"`. Fix: test now explicitly clears `_internal_jwt_skip_verification` from `app.state` before asserting the JWKS-not-loaded path.

### RC-I — market-data integration test respx mock URL using hardcoded symbol

**Tests affected**: `services/market-data/tests/integration/test_instrument_lookup_integration.py`

**Root cause**: A recent commit changed `_SYMBOL` from `"AAPL_LK"` to `"APLQ"` (underscore not in ticker validation regex), but two `respx.get()` mock URLs still had hardcoded `"eodhd.com/api/fundamentals/AAPL.US"`. The mock never matched the actual request URL, causing `test_on_demand_eodhd_fallback_mocked` and `test_on_demand_eodhd_429_propagates_rate_limit_live_db` to fail.

**Fix**: Changed hardcoded URLs to `f"https://eodhd.com/api/fundamentals/{_SYMBOL}.{_EXCHANGE}"`.

### RC-J — content-ingestion E2E app fixture missing `bronze_storage` on app.state

**Root cause 1**: The `e2e_app` fixture in `tests/e2e/conftest.py` did not set `app.state.bronze_storage`. Routes using `BronzeStorageDep` read directly from `request.app.state.bronze_storage`, raising `AttributeError: 'State' object has no attribute 'bronze_storage'`.

**Root cause 2**: `SourceRepository.create()` returns `tuple[SourceModel, bool]` (model + was_created flag). The `_seed_source` helper in `test_scheduler_e2e.py` called `.id` directly on the returned tuple.

**Fix**: Added `app.state.bronze_storage = AsyncMock()` to `e2e_app` fixture. Changed `model = await repo.create(...)` to `model, _ = await repo.create(...)`.

### RC-K — market-ingestion E2E duplicate-stream assertion false positive on backfill tasks

**Root cause**: The backfill scheduler legitimately creates multiple active tasks for the same stream key (one per date-range chunk). The duplicate-active-task dedup assertion in `test_scheduler_active_guard_prevents_duplicate_active_tasks` queried ALL active tasks without filtering, so backfill chunks from `test_backfill_90_days_produces_3_chunks` triggered it.

**Fix**: Added `.where(IngestionTaskModel.is_backfill.is_(False))` filter — the dedup invariant only applies to incremental (non-backfill) streams.

---

## 9. Full Root Cause × Batch Matrix (Complete)

| E2E Job | RC-1 (minio) | RC-2 (skip env) | RC-A (startup fix) | RC-B (nlp db url) | RC-D (startup all) | RC-E (readyz s1) | RC-F (readyz jwks) | RC-G (e2e headers) |
|---------|--------|--------|--------|--------|--------|--------|--------|--------|
| content-ingestion | ✓ B2 | | | | ✓ B3 | | | ✓ B4 |
| content-store | ✓ B2 | | | | ✓ B3 | | | ✓ B4 |
| knowledge-graph | ✓ B2 | | | ✓ B3 | ✓ B3 | | | ✓ B4 |
| market-data | ✓ B2 | | | | | | | ✓ B4 |
| market-ingestion | ✓ B2 | | | | ✓ B3 | | | ✓ B4 |
| nlp-pipeline | ✓ B2 | | | ✓ B3 | ✓ B3 | | | ✓ B4 |
| alert | | ✓ B2 | ✓ B3 | | | ✓ B3 | | ✓ B4 |
| portfolio | | ✓ B2 | ✓ B3 | | ✓ B3 | ✓ B3 | | ✓ B4 |

Batches: B2 = `865fee5b`+`90441519`, B3 = `8a0583fc`+`3a5bcb68`+`86b019a5`+`571ae62d`, B4 = `e6ef9bd0`

---

## 10. New Bug Patterns Added (Batch 4)

- **BP-474** (new): E2E conftest `e2e_client` missing `X-Internal-JWT` default header — when `skip_verification=True`, InternalJWTMiddleware still gates on header presence. Every service `e2e_client` fixture must include it.
- **BP-475** (new): Unit tests asserting on pre-fix behavior not updated after fix — after RC-E changed alert's S1 check from 503→200, test still expected 503. Rule: when behavior-changing fixes land, grep all tests for old assertion values.
- **BP-476** (new): `respx` mock URLs using hardcoded symbol strings instead of module-level test constants — when the constant is updated, hardcoded mock URLs silently stop matching. Rule: always reference `_SYMBOL`/`_EXCHANGE` constants in mock URL strings.
- **BP-477** (new): E2E `e2e_app` fixture missing `app.state` attributes required by routes — `BronzeStorageDep` and similar deps read directly from `app.state`; the test fixture must stub them.
- **BP-478** (new): `SourceRepository.create()` returns `tuple[Model, bool]`; callers that treat it as a plain model get `AttributeError: 'tuple' object has no attribute 'id'`.

---

## 11. Prevention Recommendations

1. **Shared middleware library**: The root cause of RC-D and RC-F is that each service has its own copy of `InternalJWTMiddleware`. A single copy in `libs/common` or `libs/observability` would ensure fixes are applied once. However, this is a refactor (PLAN-level change), not a quick fix.

2. **Readyz contract test**: Add a contract test that verifies `/readyz` returns 200 when all "hard" dependencies are healthy, even if "soft" (best-effort) dependencies are down. Use testcontainers with S1 intentionally stopped.

3. **Gitops sync check script**: Add a CI step or pre-commit hook that diffs `worldview/services/*/configs/docker.env` against `worldview-gitops/env/dev/*.env` and warns when they diverge. Prevents silent config drift.

4. **`make dev` as a post-fix gate**: After every batch of CI fixes, run `make dev` locally to verify the dev stack comes up fully healthy. CI E2E and `make dev` exercise different code paths (test profiles vs full profiles); a fix that clears CI may still break `make dev`.
