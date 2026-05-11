# Pre-Demo QA Report — 2026-04-13

> **Branch**: `feat/content-ingestion-wave-a1`
> **Auditor**: Senior QA + Platform Engineer (Claude Sonnet 4.6)
> **Scope**: Full pre-demo stress test — infrastructure, databases, auth security, test suite, lint, type-check, content-ingestion wave A1 specifics
> **Reference plans**: PLAN-0022 (8/9 waves), PLAN-0025 (6/6 waves, Wave E pending), PLAN-0027 (0/6 waves draft)

---

## P0 BLOCKERS (fix immediately)

### P0-1: Docker daemon not running — ALL infrastructure down

**Impact**: Cannot demo anything live. No services, no databases, no Kafka, no Valkey, no Schema Registry, no Ollama, no MinIO accessible.

**Evidence**:
- `docker compose ps` → `failed to connect to the docker API at unix:///var/run/docker.sock`
- All health endpoints (ports 8000–8008) → `FAIL`
- Kafka topics → not accessible
- Valkey → not accessible
- Schema Registry → not accessible
- Ollama → not running
- All database content queries → not accessible

**Action**: Start Docker Desktop (or Docker daemon) before any demo activity. Then bring up the stack:
```bash
docker compose -f infra/compose/docker-compose.yml --profile infra up -d
```

### P0-2: `rag-chat` unit test regression — `test_providers_status_200` fails with 401

**Impact**: 1 unit test failure in rag-chat (322/322 previously passing → 321 pass, 1 fail).

**Root cause**: `PLAN-0025 Wave C` added `InternalJWTMiddleware` globally to all services including rag-chat. The `GET /api/v1/providers/status` endpoint is NOT in the middleware's `_SKIP_PATHS` or `_SKIP_PREFIXES`, so it now requires `X-Internal-JWT`. The `tests/conftest.py` `client` fixture was not updated to inject a system JWT (BP-134 pattern).

**File**: `services/rag-chat/tests/conftest.py` — `client` fixture missing `headers={"X-Internal-JWT": <system_token>}`.

**Fix**: Add `_make_system_jwt()` + `_INTERNAL_HEADERS` pattern (already used in portfolio, nlp-pipeline, market-data, knowledge-graph tests) to rag-chat's `conftest.py` and pass headers to the `AsyncClient`.

---

## P1 RISKS (fix today)

### P1-1: `API_GATEWAY_JWT_SECRET=dev-secret-change-me` in `docker.env` (stale/dead config)

**File**: `services/api-gateway/configs/docker.env` line 7.

**Assessment**: The `config.py` uses `extra="ignore"` in `SettingsConfigDict`, so this orphaned variable is silently ignored. The source code has no `jwt_secret` field. However, the presence of this value in a committed `docker.env` file is misleading — it suggests HS256 auth is still active when it is not. Stale config creates confusion for operators and increases the risk of someone inadvertently relying on it.

**Action**: Remove `API_GATEWAY_JWT_SECRET` line from `docker.env`.

### P1-2: `RAG_CHAT_S1_INTERNAL_TOKEN=dev-internal-token` in `docker.env` (hardcoded dev token)

**File**: `services/rag-chat/configs/docker.env` line 17.

**Assessment**: This is a docker environment file used for container builds. The security scan passes because it's not a source file. However, for a production demo this token needs to be replaced with a real secret managed via environment injection.

**Action**: Replace with a placeholder (`<change-me>`) before demo. Inject real value at runtime.

### P1-3: Frontend stack mismatch — using Vite (old), not Next.js 15 (target)

**Evidence**: `apps/frontend/package.json` uses `"dev": "vite"` and `vite.config.ts` is present. AGENTS.md and PRD-0027 specify **Next.js 15 App Router + shadcn/ui**. PLAN-0027 is `draft` (0/6 waves done).

**Impact**: Demo frontend is the legacy Vite+React app, not the professional Bloomberg-style UI designed in PRD-0027. The design spec (`docs/ui/DESIGN_SYSTEM.md`, `apps/frontend/designs/DESIGN.md`) exists but the implementation does not.

**Action**: Block demo on frontend until PLAN-0027 Wave 1 is implemented, OR clearly scope the demo to backend/API capabilities only.

### P1-4: Intelligence-migrations tests: 30 errors (psycopg2 not installed)

**Evidence**:
```
ModuleNotFoundError: No module named 'psycopg2'
30 errors in 0.21s
```

The `services/intelligence-migrations/tests/conftest.py` creates a synchronous SQLAlchemy engine using the `psycopg2` dialect, but `psycopg2` is not installed in the `.venv312` environment (only `asyncpg` and `psycopg[binary]` are present).

**Action**: Either install `psycopg2-binary` in `.venv312` or update the migration test conftest to use `psycopg` or the async engine. This is a CI/CD gap — these tests cannot run locally.

### P1-5: 21 ruff `RUF059` errors (unused unpacked variables in test files)

**Evidence**: `uvx ruff check libs/ services/` → `Found 21 errors` (all `RUF059`).

**Affected files** (7 services):
- `services/alert/tests/unit/application/test_alert_fanout.py` (2)
- `services/alert/tests/unit/application/test_pending_alerts.py` (1)
- `services/knowledge-graph/tests/unit/` (8 across 5 files)
- `services/nlp-pipeline/tests/unit/` (2)
- `services/portfolio/tests/unit/test_internal_jwt_middleware.py` (4)

**Action**: Fix by prefixing unused unpacked variables with `_` (e.g., `_private_key, public_key = _generate_rsa_pair()`). Per R2, ruff must pass before commit.

### P1-6: 34 files need `ruff format` (format drift)

**Evidence**: `uvx ruff format --check libs/ services/` → `34 files would be reformatted`.

**Notable files**:
- `services/nlp-pipeline/alembic/versions/0005_add_article_price_impacts.py`
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/routing.py`
- `services/nlp-pipeline/tests/unit/infrastructure/test_consumer.py`
- `services/portfolio/src/portfolio/application/ports/brokerage_client.py`
- `services/rag-chat/tests/unit/application/test_general_intent.py`
- `services/market-ingestion/tests/live/test_eodhd_live.py`

**Action**: Run `uvx ruff format libs/ services/` and commit the formatting fixes.

---

## P2 GAPS (fix before demo)

### P2-1: PLAN-0027 (Frontend MVP) not started — 0/6 waves

Demo frontend is the placeholder Vite app. PRD-0027 specifies a professional Bloomberg/Finviz-style UI with 11 workspace panels, 18 fundamentals sections, portfolio strategy analytics, and 20+ S9 proxy routes. None of this is implemented.

### P2-2: PLAN-0025 Wave E (frontend OIDC/PKCE) not implemented

Auth flow in the frontend (`GET /v1/auth/login`, callback, refresh, logout) exists in S9 but the frontend doesn't use it. The app has no authentication UX.

### P2-3: PLAN-0022 Wave 9 (final brokerage wave) incomplete

PLAN-0022 is at 8/9 waves. The 9th wave (likely frontend brokerage UI or final E2E test) is pending.

### P2-4: `IG-LAYER-002` import guard — 1 baselined violation

`services/alert/src/alert/infrastructure/cache/watchlist_cache.py:19` imports `from redis.asyncio import Redis` directly rather than using `libs/messaging`'s Valkey abstraction. Baselined (not net-new), but should be resolved before demo to comply with R25.

### P2-5: Portfolio brokerage connection tests — spurious `@pytest.mark.asyncio` on sync functions

**File**: `services/portfolio/tests/unit/api/test_brokerage_connections.py` lines 350, 361.

Two sync functions (`test_initiate_request_tos_false_raises_validation_error`, `test_initiate_request_tos_true_passes`) are marked `@pytest.mark.asyncio` but are not async. This generates `PytestWarning` noise without affecting pass/fail. Remove the `asyncio` marks from those two functions.

### P2-6: Alert service — two untracked files not committed to branch

```
services/alert/src/alert/application/ports/metrics.py   (untracked)
services/alert/src/alert/infrastructure/metrics/prometheus_metrics_impl.py  (untracked)
```

These files exist on disk but are not staged or committed. If they contain implementation used by the alert service, this is a silent bug risk (the service may work locally but break in a clean checkout). Verify if they are import-referenced; if so, commit them.

### P2-7: PLAN-0023, PLAN-0024, PLAN-0026 all in draft/partial state

- PLAN-0023 (Knowledge Graph Analytics): 0/8 waves
- PLAN-0024 (Production Deployment): 3/6 waves (Helm, ArgoCD, Vercel not done)
- PLAN-0026 (News Intelligence APIs): 0/7 waves

These are not demo-blockers if the demo scope is limited, but they represent significant product gaps.

### P2-8: Market-ingestion has only 3 unit tests

`services/market-ingestion/tests/unit/` contains 3 tests. Most testing occurs in platform_qa, api, application, domain, infrastructure layers (408 total passing). This is thin for a production-grade service but acceptable if those layers are well-covered.

---

## PASSING

- **Docker** (infrastructure-only concern): Docker binary is available; daemon not running is a startup issue, not a code issue.
- **All mypy checks PASS** across all 10 services: portfolio (115 files), market-data (115), content-ingestion (87), nlp-pipeline (87), knowledge-graph (107), rag-chat (85), alert (70), market-ingestion (68), content-store (58), api-gateway (14).
- **Security scan** (`scripts/hooks/security-scan.sh`): CLEAN.
- **Import guard**: 0 net-new violations (1 baselined).
- **BP-144 (RateLimitMiddleware valkey=None)**: FIXED — middleware reads from `app.state.valkey` at request time.
- **BP-145 (OIDCAuthMiddleware missing issuer param)**: FIXED — `jwt.decode()` passes `issuer=oidc_config.issuer`.
- **BP-146 (PKCE GET+DEL non-atomic)**: FIXED — uses atomic `GETDEL` command.
- **BP-149/BP-150 (NLP idempotency + Kafka retention)**: FIXED in HEAD commit — `ArticleProcessingConsumer` checks for existing routing_decision before processing; topic retention set to 30 days.
- **Auth architecture (PRD-0025)**: S9 OIDC+RS256 infrastructure complete. `OIDCAuthMiddleware` validates Zitadel RS256 JWTs with issuer. `InternalJWTMiddleware` uses atomic `GETDEL` for PKCE. `RateLimitMiddleware` reads from `app.state` at request time.
- **PLAN-0022 Wave D-2**: S9 brokerage proxy routes committed and tested.

---

## DATA QUALITY SUMMARY

All Docker infrastructure was offline during this audit. No live database queries could be executed. The following table reflects the expected/designed state based on code and plan review.

| Metric | Status |
|--------|--------|
| Docker daemon | **DOWN** — no containers running |
| Instruments (market_data_db) | Not queryable |
| OHLCV bars | Not queryable |
| Fundamentals sections | Not queryable |
| Articles (content_store_db) | Not queryable |
| NLP chunks with embeddings | Not queryable |
| Knowledge graph entities | Not queryable |
| Knowledge graph relations | Not queryable |
| Temporal events | Not queryable |
| Chat threads (rag_db) | Not queryable |
| Users / Portfolios / Holdings | Not queryable |
| Alerts pending | Not queryable |

**Recommended action before demo**: Start Docker daemon, bring up the full stack, re-run the database content queries from Phase 2 of this script to verify data population.

---

## TEST SUITE RESULTS

### Services (unit tests only, no integration/E2E/contract)

| Service | Tests | Result | Notes |
|---------|-------|--------|-------|
| portfolio (S1) | 468 | PASS | 2 PytestWarning (asyncio mark on sync tests) |
| market-ingestion (S2) | 408 pass, 9 skip | PASS | Live tests excluded (need EODHD API key) |
| market-data (S3) | 432 | PASS | Live tests excluded (need running DB) |
| content-ingestion (S4) | 533 | PASS | All unit + health tests pass |
| content-store (S5) | 290 | PASS | |
| nlp-pipeline (S6) | 403 | PASS | |
| knowledge-graph (S7) | 575 | PASS | |
| rag-chat (S8) | 321 pass, 1 fail | **FAIL** | `test_providers_status_200` → 401 (P0-2) |
| api-gateway (S9) | 76 | PASS | Integration tests excluded (need OIDC) |
| alert (S10) | 334 | PASS | |
| intelligence-migrations | 0 pass, 30 errors | **FAIL** | `psycopg2` not installed (P1-4) |

### Libraries

| Library | Tests | Result | Notes |
|---------|-------|--------|-------|
| libs/common | 67 | PASS | |
| libs/contracts | 106 pass, 3 skip | PASS | |
| libs/messaging | 186 | PASS | |
| libs/storage | 79 | PASS | |
| libs/observability | 38 | PASS | |
| libs/ml-clients | 90 pass, 3 fail | PARTIAL | 3 Ollama integration tests fail (Ollama not running — expected) |

### Total unit tests passing: ~3,620 pass / 2 services with failures

### Lint & Type Check

| Check | Result | Details |
|-------|--------|---------|
| `ruff check` | FAIL (P1-5) | 21 errors (all RUF059 — unused unpacked vars in tests) |
| `ruff format --check` | FAIL (P1-6) | 34 files need reformatting |
| `mypy` (all services) | PASS | All 10 services clean |
| Import guards | PASS | 0 net-new violations |
| Security scan | PASS | Clean |

---

## BRANCH STATUS: `feat/content-ingestion-wave-a1`

This branch was opened for PLAN-0001-B Wave A1 (S4 content-ingestion foundation) and has accumulated **64 commits** touching all 10 services across multiple plans:

- PLAN-0001-B: Content Ingestion Wave A1–A4 + Content Store Wave B1–B4 (foundational)
- PLAN-0025: Auth Foundation (Zitadel OIDC + RS256 internal JWT) — 6/6 infra waves
- PLAN-0022: SnapTrade Brokerage — Wave D-2 (S9 proxy routes)
- Fix commits: BP-134 (JWT headers), BP-144/145/146 (auth security), BP-149/150 (NLP idempotency + Kafka retention)
- Design: PRD-0027 frontend UI design spec

**Diff size**: 1,537 files changed from `main`.

**Assessment**: The branch is extremely large for a single PR. Consider splitting into feature-specific PRs before merging to main. The core issue is that this branch started as a single feature branch and became the catch-all integration branch for the thesis project.

---

## OPEN SECURITY FINDINGS

| ID | Severity | Status | Finding |
|----|----------|--------|---------|
| SEC-001 | HIGH | FIXED (PRD-0025) | HS256 jwt_secret replaced by Zitadel RS256 JWKS |
| SEC-003 | HIGH | FIXED (PRD-0025) | CORS method/header allowlist enforced |
| SEC-004 | HIGH | FIXED (PRD-0025) | RateLimitMiddleware wired and reading app.state at request time |
| SEC-007 | HIGH | FIXED (PRD-0025) | SecurityHeadersMiddleware added |
| SEC-008 | HIGH | FIXED (PRD-0025) | Rate limit by user_id after auth |
| BP-144 | CRITICAL | FIXED | RateLimitMiddleware valkey=None at construction |
| BP-145 | CRITICAL | FIXED | OIDCAuthMiddleware missing issuer= param |
| BP-146 | CRITICAL | FIXED | PKCE GET+DEL non-atomic → GETDEL |
| NEW | MEDIUM | **OPEN** | `API_GATEWAY_JWT_SECRET=dev-secret-change-me` in docker.env (dead config but misleading) |
| NEW | LOW | **OPEN** | `RAG_CHAT_S1_INTERNAL_TOKEN=dev-internal-token` in docker.env (should be injected) |

---

## DEMO READINESS: **NO-GO**

### Blockers

1. **P0-1 (CRITICAL)**: Docker daemon not running — zero live infrastructure. Cannot demo.
2. **P0-2 (HIGH)**: rag-chat unit test regression — `test_providers_status_200` fails 401.

### Conditional GO (after blockers resolved)

If Docker is started and P0-2 is fixed (estimated 30 min of work), the backend services are in solid shape:
- All 10 services pass unit tests (3,600+ passing)
- All mypy checks pass across all services
- Auth security hardening (PRD-0025) complete and verified
- Content-ingestion Wave A1 (the branch's original feature) is clean: 533 unit tests pass
- NLP pipeline idempotency guard (BP-149/BP-150) is in HEAD

The remaining P1/P2 items are quality improvements, not demo-blockers for a backend-focused demo.

For a **full product demo** (including frontend), the verdict is **NO-GO** until PLAN-0027 Wave 1+ is implemented — the current Vite frontend is not the professional UI specified in PRD-0027.

---

## PRIORITIZED ACTION LIST

| Priority | Action | Effort | Owner |
|----------|--------|--------|-------|
| P0 | Start Docker daemon | 1 min | DevOps |
| P0 | Fix `rag-chat` conftest: add `_make_system_jwt()` + `_INTERNAL_HEADERS` to `client` fixture | 15 min | Backend |
| P1 | Run `uvx ruff format libs/ services/` to fix 34 format violations | 2 min | Automation |
| P1 | Fix 21 `RUF059` errors (prefix unused `_private_key` etc.) | 30 min | Backend |
| P1 | Remove `API_GATEWAY_JWT_SECRET` from `docker.env` | 2 min | Backend |
| P1 | Install `psycopg2-binary` in `.venv312` OR update migration test conftest | 15 min | Backend |
| P2 | Commit or stage-gate the 2 untracked alert metrics files | 5 min | Backend |
| P2 | Remove `@pytest.mark.asyncio` from 2 sync tests in portfolio | 5 min | Backend |
| P2 | Bring up full Docker stack; re-run Phase 2 DB queries to verify data | 30 min | DevOps |

---

*Generated by QA stress-test pass on 2026-04-13. Next QA pass recommended after P0/P1 fixes are merged.*
