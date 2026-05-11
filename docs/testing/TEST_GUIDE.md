# Worldview Platform — Test Guide

> Complete reference for all test types, how to run them, what they cover, and what infrastructure they require.
> Last updated: 2026-04-22

---

## Index

- [IMPORTANT: Understanding the Mock Boundary](#important-understanding-the-mock-boundary)
   - [Test Honesty Matrix](#test-honesty-matrix)
- [Quick Reference](#quick-reference)
- [Test Layers (from fastest to most comprehensive)](#test-layers-from-fastest-to-most-comprehensive)
   - [Layer 1: Static Analysis (no infrastructure)](#layer-1-static-analysis-no-infrastructure)
   - [Layer 2: Unit Tests (no infrastructure)](#layer-2-unit-tests-no-infrastructure)
   - [Layer 3: Architecture Tests (no infrastructure)](#layer-3-architecture-tests-no-infrastructure)
   - [Layer 4: Contract Tests (no infrastructure)](#layer-4-contract-tests-no-infrastructure)
   - [Layer 5: Integration Tests (testcontainers / Docker infra)](#layer-5-integration-tests-testcontainers--docker-infra)
   - [Layer 6: Frontend E2E -- Mocked API (auto-starts dev server)](#layer-6-frontend-e2e--mocked-api-auto-starts-dev-server)
   - [Layer 7: Backend Exhaustive QA (live dev stack)](#layer-7-backend-exhaustive-qa-live-dev-stack)
   - [Layer 8: Frontend Exhaustive QA -- Mocked (auto-starts dev server)](#layer-8-frontend-exhaustive-qa--mocked-auto-starts-dev-server)
   - [Layer 9: Frontend Live-Stack QA — NO MOCKS (live dev stack)](#layer-9-frontend-live-stack-qa--no-mocks-live-dev-stack)
   - [Layer 10: Contract Alignment (live dev stack)](#layer-10-contract-alignment-live-dev-stack)
   - [Layer 11: Full E2E Pipeline Tests (Docker Compose test stack)](#layer-11-full-e2e-pipeline-tests-docker-compose-test-stack)
- [What Each Layer Tests](#what-each-layer-tests)
   - [Layer Matrix](#layer-matrix)
- [Running Tests](#running-tests)
   - [Recommended Daily Workflow](#recommended-daily-workflow)
   - [Before Committing (verify real platform health)](#before-committing-verify-real-platform-health)
   - [Full Validation (before PR or QA certification)](#full-validation-before-pr-or-qa-certification)
   - [Single-Service Development](#single-service-development)
   - [Frontend Development](#frontend-development)
- [Test File Inventory](#test-file-inventory)
   - [Python Tests by Service](#python-tests-by-service)
   - [Python Tests by Library](#python-tests-by-library)
   - [Root-Level Python Tests](#root-level-python-tests)
   - [Frontend Tests (apps/worldview-web)](#frontend-tests-appsworldview-web)
- [Configuration Files](#configuration-files)
   - [Pytest Markers (from pytest.ini)](#pytest-markers-from-pytestini)
- [Adding New Tests](#adding-new-tests)
   - [Python service unit test](#python-service-unit-test)
   - [Python service integration test](#python-service-integration-test)
   - [Python architecture test](#python-architecture-test)
   - [Frontend unit test (Vitest)](#frontend-unit-test-vitest)
   - [Frontend E2E test (Playwright)](#frontend-e2e-test-playwright)
   - [Live-stack QA test](#live-stack-qa-test)
- [Test Scripts Reference](#test-scripts-reference)
- [Troubleshooting](#troubleshooting)
   - [Common issues](#common-issues)
- [Docker Compose Test Infrastructure Reference](#docker-compose-test-infrastructure-reference)
   - [Stack Design Principles](#stack-design-principles)
   - [Profile Reference](#profile-reference)
   - [Port Reference](#port-reference)
   - [Per-Service E2E Sequences](#per-service-e2e-sequences)
   - [One-Shot Init Containers](#one-shot-init-containers)
   - [Docker Compose Debugging](#docker-compose-debugging)
- [Interpreting Test Execution Reports](#interpreting-test-execution-reports)
   - [Report sections](#report-sections)
   - [Key metrics](#key-metrics)
   - [Common failure signatures](#common-failure-signatures)

---

If you want the shortest practical path through the guide, start with [Recommended Workflows](#recommended-workflows), then use [Quick Reference](#quick-reference) only when you need a command lookup.

## Recommended Workflows

The testing surface is broad on purpose, but day-to-day work usually fits one of three paths:

- Fast iteration: `make qa` for Python changes, `pnpm test` and `pnpm typecheck` for frontend changes.
- Real platform verification: `make qa-live-stack` plus `make qa-contract`, and `make qa-exhaustive-backend` when you changed live API behavior.
- Broader regression checks: `make qa-exhaustive` or `make test-all` before a release-style handoff, and `make test-e2e` when you need the full Docker-backed pipeline.

Use the more specialized commands below when you are working on a single service, debugging infrastructure, or validating a specific failure mode. They are not the default path for most changes.

## IMPORTANT: Understanding the Mock Boundary

Most tests in this project use **mocked API responses** — they do NOT hit real backend services. This means:

- **Tests that pass with mocks prove the frontend/component code is correct** — they do not prove the backend works.
- **If a backend endpoint returns 503 or 404, mocked tests will still pass.** The mock intercepts the request before it reaches the network.
- **Only live-stack tests (`make qa-live-stack`, `make qa-exhaustive-backend`) hit real endpoints.** These are the tests that expose broken backends.
- **Contract alignment tests (`make qa-contract`) detect when mocks drift from real API shapes** — a mock returning `{watchlist_id: ...}` while the real API returns `{id: ...}` is a bug that only this layer catches.

### Test Honesty Matrix

| Command | Hits real API? | Proves backend works? | Proves frontend works? |
|---------|:-:|:-:|:-:|
| `pnpm test` (Vitest) | No (MSW mocks) | **No** | Yes (with mock data) |
| `pnpm test:e2e` (Playwright mocked) | No (page.route mocks) | **No** | Yes (with mock data) |
| `make qa-exhaustive-backend` | **Yes** | **Yes** | Partially (smoke only) |
| `make qa-live-stack` | **Yes** | **Yes** | **Yes** (real integration) |
| `make qa-contract` | **Yes** | Shape only | Validates mock accuracy |
| `make test-all` (full pipeline) | **Yes** (Docker) | **Yes** | N/A (backend only) |

**Rule of thumb**: If you want to know if the platform actually works end-to-end, run `make qa-live-stack`. If it passes, the real user experience is functional. If `pnpm test` passes but `make qa-live-stack` fails, you have a backend problem that the frontend is masking.

---

## Quick Reference

| Command | What It Runs | Infrastructure Required | Approx. Time |
|---------|-------------|----------------------|------|
| `make lint` | ruff check + ruff format --check on `libs/`, `services/`, `tests/` | None | ~15 sec |
| `make typecheck` | mypy for every service and lib that has a `mypy.ini` | None | ~90 sec |
| `make test-unit` | Lib tests (`scripts/test-libs.sh`) + all service unit tests (`scripts/run-unit-tests.sh`) | None | ~2 min |
| `make test-unit SERVICE=portfolio` | Unit tests for a single service | None | ~15 sec |
| `make test-arch` | Architecture/standards compliance (`tests/architecture/`) | None | ~10 sec |
| `make qa` | `lint` + `typecheck` + `test-unit` (the CI gate) | None | ~3 min |
| `make qa-exhaustive` | Backend exhaustive QA + frontend exhaustive QA (Playwright) | Dev stack running (`make dev && make seed`) | ~5 min |
| `make qa-exhaustive-backend` | `scripts/qa_exhaustive.py` against live S9 + frontend | Dev stack running | ~2 min |
| `make qa-exhaustive-frontend` | `e2e/qa-exhaustive.spec.ts` via Playwright | None (auto-starts dev server) | ~1 min |
| `make qa-live-stack` | Frontend vs **real API** (no mocks!) — exposes broken backends | Dev stack running (`make dev && make seed`) | ~1 min |
| `make qa-contract` | Verify mock fixtures match real API response shapes | Dev stack running (`make dev && make seed`) | ~10 sec |
| `make test-all` | Full layered suite via `scripts/test-full.sh` (arch + libs + unit + contract + integration + e2e) | Docker Compose test stack (auto-started) | ~15-25 min |
| `make test-e2e` | Full E2E via `scripts/test-full.sh --no-cleanup` | Docker Compose test stack (auto-started) | ~15-25 min |
| `make test-e2e SERVICE=portfolio` | Single-service E2E via `scripts/run-service-e2e.sh` | Docker Compose test stack | ~5 min |
| `make infra-up` | Start Docker Compose test stack (`--profile all`) | Docker | ~3 min |
| `make infra-down` | Stop test stack and remove volumes | Docker | ~10 sec |
| `pnpm test` (in `apps/worldview-web`) | Vitest unit tests (jsdom, React Testing Library) | None | ~3 sec |
| `pnpm test:watch` (in `apps/worldview-web`) | Vitest in watch mode | None | continuous |
| `pnpm test:coverage` (in `apps/worldview-web`) | Vitest with v8 coverage report | None | ~5 sec |
| `pnpm test:e2e` (in `apps/worldview-web`) | Playwright E2E (Chromium + WebKit) | None (auto-starts dev server on `:3001`) | ~30 sec |
| `pnpm lint` (in `apps/worldview-web`) | ESLint (next lint) | None | ~5 sec |
| `pnpm typecheck` (in `apps/worldview-web`) | `tsc --noEmit` | None | ~5 sec |
| `./scripts/test.sh` | Python unit tests (libs + services) | None | ~2 min |
| `./scripts/test.sh --integration` | Python unit + integration tests | Docker (MinIO, Postgres) | ~5 min |
| `./scripts/test.sh --frontend unit` | Frontend typecheck + Vitest | None | ~8 sec |
| `./scripts/test.sh --frontend e2e` | Frontend Playwright E2E | None (auto-starts dev server) | ~30 sec |
| `./scripts/test.sh --frontend all` | Frontend unit + E2E | None (auto-starts dev server) | ~40 sec |
| `./scripts/test.sh --full` | All Python (all markers) + all frontend layers | Docker (for integration) | ~10 min |

---

## Test Layers (from fastest to most comprehensive)

### Layer 1: Static Analysis (no infrastructure)

**What it checks**: Lint rules (ruff), type correctness (mypy for Python, tsc for TypeScript), format conformance.

**Python**:
```bash
make lint       # ruff check + ruff format --check on libs/, services/, tests/
make typecheck  # mypy per service/lib using each directory's mypy.ini
```

**Frontend**:
```bash
cd apps/worldview-web
pnpm lint       # next lint (ESLint with next config)
pnpm typecheck  # tsc --noEmit
```

**What it catches**: syntax errors, type mismatches, unused imports, import violations, style issues, missing type annotations, dead code.

**Infrastructure**: None -- runs on source code only.

---

### Layer 2: Unit Tests (no infrastructure)

**What it checks**: Business logic, domain entities, value objects, use cases (with mocked ports), utility functions, React component rendering, hooks.

#### Python (10 services + 6 libs)

```bash
# All services + all libs
make test-unit

# Single service
make test-unit SERVICE=portfolio

# Single lib
./scripts/test-libs.sh --lib common

# Via unified test script
./scripts/test.sh              # unit only (default marker)
./scripts/test.sh --all        # no marker filter
```

How it works:
- `scripts/test-libs.sh` iterates over `libs/*/tests/`, installing each lib in editable mode, running pytest with `-m "not integration"`.
- `scripts/run-unit-tests.sh` iterates over `services/*/tests/`, running pytest with `--ignore tests/integration --ignore tests/e2e --ignore tests/live` and `-m "not integration and not e2e and not live"`.
- Each service may have its own `.venv/` -- the scripts detect and use it automatically.

Pytest markers (from `pytest.ini`):
- `unit` -- fast isolated unit tests (default for `make test-unit`)
- `integration` -- tests requiring DB, Kafka, or MinIO
- `contract` -- Avro/OpenAPI schema compatibility
- `e2e` -- end-to-end scenario tests (in-process ASGI, testcontainers)
- `slow` -- long-running tests excluded from CI fast path

#### Frontend

```bash
cd apps/worldview-web
pnpm test           # vitest run (single pass)
pnpm test:watch     # vitest (watch mode)
pnpm test:coverage  # vitest run --coverage (v8 provider)
```

Configuration (`vitest.config.ts`):
- Environment: `jsdom` (simulates browser DOM in Node.js)
- Setup file: `vitest.setup.ts` (imports `@testing-library/jest-dom`, stubs `scrollIntoView` and `ResizeObserver` for jsdom)
- Includes: `**/__tests__/**/*.test.{ts,tsx}` and `**/*.test.{ts,tsx}`
- Excludes: `node_modules`, `e2e/**`, `.next/**`
- Coverage: `app/`, `components/`, `hooks/`, `lib/` directories
- Path alias: `@/` maps to project root (matches tsconfig)

**Infrastructure**: None -- all external calls are mocked.

---

### Layer 3: Architecture Tests (no infrastructure)

**What it checks**: Structural compliance with project rules -- hexagonal layer boundaries, shared lib usage, consumer patterns, config patterns, outbox dispatcher contracts, domain error patterns, process topology, compose alignment.

```bash
make test-arch
# Equivalent to:
python -m pytest tests/architecture/ -v --tb=short
```

**Files** (15 test files in `tests/architecture/`):
| File | What It Enforces |
|------|-----------------|
| `test_layer_boundaries.py` | Domain layer has no infrastructure imports (R12) |
| `test_service_structure.py` | Every service has `api/`, `application/`, `domain/`, `infrastructure/` |
| `test_shared_lib_usage_common.py` | Services use `common.ids`, `common.time` (not uuid4, naive datetime) |
| `test_shared_lib_usage_messaging.py` | Services use `libs/messaging` for Kafka (not raw confluent_kafka) |
| `test_shared_lib_usage_observability.py` | Services use structlog (not stdlib logging) |
| `test_shared_lib_usage_storage.py` | Services use `libs/storage` for S3/MinIO |
| `test_consumer_enforcement.py` | Kafka consumers implement idempotency |
| `test_ports_enforcement.py` | Port interfaces in `application/`, not `infrastructure/` |
| `test_domain_error_enforcement.py` | Domain errors follow naming conventions |
| `test_config_patterns.py` | All config via pydantic-settings |
| `test_outbox_dispatcher_contracts.py` | Outbox pattern for dual writes |
| `test_database_session_patterns.py` | Correct session/UoW patterns |
| `test_process_topology.py` | Service topology matches compose config |
| `test_utils_process_topology.py` | Utility tests for topology validation |
| `test_compose_alignment.py` | Docker Compose config matches service definitions |

**Infrastructure**: None -- reads source files via AST/regex analysis.

---

### Layer 4: Contract Tests (no infrastructure)

**What it checks**: Avro schema forward-compatibility, OpenAPI contract alignment, inter-service Pydantic model consistency.

```bash
# Root-level contract tests
python -m pytest tests/contract/ -v

# Per-service contract tests (if present)
python -m pytest services/<service>/tests/contract/ -v -m contract
```

**Root-level files** (3 test files in `tests/contract/`):
- `test_avro_schemas.py` -- validates all `.avsc` files in `infra/kafka/schemas/`
- `test_market_data_contracts.py` -- market data Pydantic model alignment
- `test_portfolio_contracts.py` -- portfolio Pydantic model alignment

**Templates** (in `tests/contract/templates/`):
- `avro_contract_test.py` -- reusable Avro schema validation pattern
- `openapi_contract_test.py` -- reusable OpenAPI contract test pattern
- `service_integration_contract_test.py` -- cross-service contract test pattern

**Infrastructure**: None -- validates schema files and model definitions statically.

---

### Layer 5: Integration Tests (testcontainers / Docker infra)

**What it checks**: Real database reads/writes, Kafka publish/consume cycles, MinIO object storage, repository implementations against Postgres, Alembic migration execution.

```bash
# Run as part of full suite (Docker Compose auto-managed)
make test-all

# Run integration for a specific lib (starts MinIO automatically)
./scripts/test-libs.sh --integration

# Run via unified script
./scripts/test.sh --integration
```

Integration tests are located in `services/<service>/tests/integration/` and require running infrastructure (Postgres, Kafka, MinIO). The `test-full.sh` script handles the full lifecycle:
1. Starts Docker Compose test stack (`infra/compose/docker-compose.test.yml --profile all`)
2. Waits for service readiness (`scripts/wait-for-services.sh all`)
3. Runs `tests/integration/` with `-m integration` marker
4. Captures infra diagnostics on failure
5. Tears down compose on exit

Service-specific database URLs are injected as environment variables (e.g., `CONTENT_INGESTION_E2E_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55433/content_ingestion_db`).

**Infrastructure**: Docker Compose test stack (Postgres, Kafka, MinIO, Zookeeper, Schema Registry).

---

### Layer 6: Frontend E2E -- Mocked API (auto-starts dev server)

**What it checks**: Full browser rendering of every route, navigation flows, auth redirects, search, workspace layout, dashboard widget rendering -- all with mocked API responses.

```bash
cd apps/worldview-web
pnpm test:e2e                          # All E2E specs (Chromium + WebKit)
pnpm test:e2e -- --project=chromium    # Chromium only (faster)
npx playwright test e2e/auth.spec.ts   # Single spec file
```

Configuration (`playwright.config.ts`):
- Test directory: `./e2e`
- Match pattern: `**/*.spec.ts`
- Fully parallel: `true`
- Workers: 1 locally, 4 on CI
- Retries: 0 locally, 1 on CI
- Base URL: `http://localhost:3001`
- Trace: captured on first retry
- Browser projects: **Chromium** (primary) + **WebKit** (Safari 17+ support)
- Dev server: auto-started via `pnpm dev`, reuses existing server locally, 120s timeout

**E2E spec files** (7 files in `apps/worldview-web/e2e/`):
| File | What It Tests |
|------|--------------|
| `auth.spec.ts` | Login flow, auth redirects, token handling |
| `navigation.spec.ts` | Nav rail, route transitions, active state |
| `dashboard.spec.ts` | Dashboard page rendering, widget layout |
| `workspace.spec.ts` | Workspace panels, grid layout |
| `search.spec.ts` | Command palette search, results rendering |
| `authenticated-pages.spec.ts` | All authenticated routes render without errors |
| `qa-exhaustive.spec.ts` | Comprehensive QA (9 groups, ~37 tests -- see Layer 8) |

Mock strategy: Uses `page.route()` with shared mock fixtures from `e2e/fixtures/api-mocks.ts`. Auth endpoints always return 200 to prevent redirect during tests.

**Infrastructure**: None -- Playwright auto-starts the Next.js dev server. No backend required.

---

### Layer 7: Backend Exhaustive QA (live dev stack)

**What it checks**: Endpoint coverage against the live S9 API Gateway, auth boundary enforcement (authenticated vs. unauthenticated), response schema validation, security headers, SQL injection probes, IDOR/tenant isolation, frontend smoke test.

```bash
# Requires dev stack running first
make dev && make seed

# Then run
make qa-exhaustive-backend
# Equivalent to:
python3 scripts/qa_exhaustive.py
```

How it works:
- Connects to S9 at `http://localhost:8000` and frontend at `http://localhost:3001`
- Authenticates via `POST /v1/auth/dev-login` to get a real JWT
- Tests every endpoint with and without authentication
- Validates response shapes, status codes, and security headers
- Results tracked as `(category, name, status, detail)` tuples
- Supports `EXPECTED_FAIL` for endpoints that are known to be unimplemented
- Exit code 0 = all tests passed, 1 = unexpected failures

**Infrastructure**: Full dev stack (`make dev`) with seed data (`make seed`).

---

### Layer 8: Frontend Exhaustive QA -- Mocked (auto-starts dev server)

**What it checks**: Every frontend route, UI states (loading, empty, error), security headers, navigation and keyboard shortcuts, visual design audit, accessibility basics.

```bash
make qa-exhaustive-frontend
# Equivalent to:
cd apps/worldview-web && npx playwright test e2e/qa-exhaustive.spec.ts --reporter=list
```

The `qa-exhaustive.spec.ts` file contains 9 coverage groups (~37 tests):

| Group | Tests | What It Validates |
|-------|-------|-------------------|
| 1. Public Route Rendering | 5 | Login, not-found, root redirect |
| 2. Authenticated Route Rendering | 8 | Dashboard, portfolio, screener, alerts, chat, workspace, settings |
| 3. Security Headers | 3 | CSP, X-Frame-Options, X-Content-Type-Options |
| 4. Loading States | 4 | Skeleton/spinner appears before data loads (delayed mocks) |
| 5. Empty States | 4 | Correct empty-state UI when API returns empty arrays |
| 6. Error States | 3 | Error boundary rendering when API returns 500 |
| 7. Navigation & Keyboard | 4 | Nav rail, route transitions, keyboard shortcuts |
| 8. Visual Design Audit | 3 | Color palette, font usage, spacing consistency |
| 9. Accessibility Basics | 3 | Landmarks, heading hierarchy, focus management |

Screenshots are saved to `test-results/qa-*.png` for visual review.

**Infrastructure**: None -- Playwright auto-starts the dev server. All API calls are mocked.

---

### Layer 9: Frontend Live-Stack QA — NO MOCKS (live dev stack)

**What it checks**: Whether the frontend works against the **real running backend**. No API mocks. Authenticates via the real dev-login endpoint, navigates via sidebar links (to preserve React auth state), and verifies pages render with real data.

**This is the only frontend test that will fail when a backend endpoint is broken.**

```bash
# Requires dev stack running first
make dev && make seed

# Then run
make qa-live-stack
# Equivalent to:
cd apps/worldview-web && npx playwright test e2e/qa-live-stack.spec.ts --project=chromium --reporter=list
```

**How it works**:
1. Authenticates by navigating to `/login` and clicking the real "Dev Login" button
2. Waits for redirect to `/dashboard` (confirms auth token is in React state)
3. Navigates between pages using **sidebar link clicks** (not `page.goto()` which resets React state)
4. For each page: asserts no uncaught JS exceptions, `<main>` element renders, takes screenshot
5. Checks dashboard widget health (how many show real data vs error/skeleton)
6. Tests data-bearing assertions (portfolio holdings, search results, alerts structure)

**Why sidebar navigation?** The auth token lives in React state (never localStorage). A `page.goto()` triggers a full-page navigation that resets all React state, losing the token. Sidebar `<Link>` clicks use client-side navigation which preserves state.

**Infrastructure**: Full dev stack (`make dev`) with seed data (`make seed`).

**Expected behavior when backends are broken**:
- S8 down (JWKS race): Chat page shows error → test reports it
- S5 missing: News tabs show empty/error → test reports it
- Healthy backends: Pages render with real data → test passes

---

### Layer 10: Contract Alignment (live dev stack)

**What it checks**: Whether the **mock fixtures** used by Playwright E2E tests match the **real API response shapes**. Detects "mock drift" — when a mock returns `{watchlist_id: ...}` but the real API returns `{id: ...}`.

```bash
# Requires dev stack running first
make dev && make seed

# Then run
make qa-contract
# Equivalent to:
python3 scripts/qa_contract_alignment.py
```

**How it works**:
1. Parses `apps/worldview-web/e2e/fixtures/api-mocks.ts` to extract all mock response shapes
2. Calls the real S9 endpoint for each mock
3. Compares response shapes recursively (keys, types, nesting)
4. Reports: `EXTRA_IN_MOCK` (mock has key real doesn't), `MISSING_IN_MOCK` (real has key mock doesn't), `TYPE_MISMATCH`

**Infrastructure**: Full dev stack (`make dev`) with seed data (`make seed`).

**When this fails**: Update `e2e/fixtures/api-mocks.ts` to match the real API response shape. This is a sign that the API changed but the mock was not updated.

---

### Layer 11: Full E2E Pipeline Tests (Docker Compose test stack)

**What it checks**: Cross-service data flows, Kafka event propagation, multi-service pipelines (content ingestion -> NLP -> knowledge graph), market data pipelines, security isolation between tenants, deployment readiness.

```bash
# Full automated suite (manages Docker Compose lifecycle)
./scripts/test-full.sh

# Or with options:
./scripts/test-full.sh --no-cleanup                    # Keep containers after run
./scripts/test-full.sh --retain-logs always             # Always capture infra logs
./scripts/test-full.sh --run-integration-on-readiness-failure  # Continue even if some services fail health checks
```

`test-full.sh` runs 6 layers sequentially:
1. **Architecture tests** (`tests/architecture/`)
2. **Library tests** (`scripts/test-libs.sh`)
3. **Service unit tests** (all `services/*/tests/unit/`)
4. **Service contract tests** (all `services/*/tests/contract/`)
5. **Compose-backed integration + E2E** (starts Docker Compose, then runs `tests/integration/` and `tests/e2e/` per service)
6. **Cross-service E2E** (`tests/e2e/` at repo root)

**Root-level E2E files** (8 test files in `tests/e2e/`):
| File | What It Tests |
|------|--------------|
| `test_full_pipeline.py` | End-to-end content ingestion -> NLP -> knowledge graph pipeline |
| `test_content_pipeline.py` | Content ingestion -> content store flow |
| `test_market_data_pipeline.py` | Market data ingestion -> market data service flow |
| `test_market_intelligence_pipeline.py` | Market intelligence aggregation across services |
| `test_intelligence_pipeline.py` | NLP pipeline -> knowledge graph entity enrichment |
| `test_security_isolation.py` | Multi-tenant isolation, IDOR prevention |
| `test_real_data_providers.py` | Real external API provider connectivity |
| `test_deployment_readiness.py` | Health endpoints, migration status, schema registry |

**Artifacts**: Each run generates a timestamped directory under `docs/testing/test-runs/<RUN_ID>/` containing:
- `TEST_EXECUTION_REPORT.md` -- human-readable report
- `TEST_EXECUTION_SUMMARY.json` -- machine-readable summary
- `suites/` -- per-suite log files
- `junit/` -- JUnit XML files per suite
- `infra/` -- Docker Compose logs, container inspect dumps

**Infrastructure**: Docker Compose test stack (`infra/compose/docker-compose.test.yml --profile all`). Managed automatically by the script.

---

## What Each Layer Tests

### Layer Matrix

| Concern | L1 | L2 | L3 | L4 | L5 | L6 | L7 | L8 | L9 | L10 | L11 |
|---------|----|----|----|----|----|----|----|----|----|----|-----|
| Syntax/types | x | | | | | | | | | | |
| Component rendering | | x | | | | x | | x | x | | |
| Business logic | | x | | | x | | | | | | |
| API contracts | | | | x | | | x | | | x | x |
| Hexagonal layer boundaries | | | x | | | | | | | | |
| Shared lib compliance | | | x | | | | | | | | |
| Auth boundaries | | x | | | | | x | | x | | x |
| DB writes/reads | | | | | x | | | | | | x |
| Kafka publish/consume | | | | | x | | | | | | x |
| Avro schema compatibility | | | | x | | | | | | | |
| UI loading states | | | | | | x | | x | | | |
| UI empty states | | | | | | | | x | x | | |
| UI error states | | | | | | | | x | x | | |
| **Real API integration** | | | | | | | **x** | | **x** | **x** | **x** |
| Security headers | | | | | | | x | x | | | |
| SQL injection probes | | | | | | | x | | | | |
| IDOR/tenant isolation | | | | | | | x | | | | x |
| **Mock drift detection** | | | | | | | | | | **x** | |
| Cross-service flows | | | | | | | | | | | x |
| Navigation & keyboard | | | | | | x | | x | x | | |
| Accessibility | | | | | | | | x | | | |
| Visual design | | | | | | | | x | | | |

**Bold rows** = the layers that actually hit real backend endpoints. Everything else uses mocks.

---

## Running Tests

### Recommended Daily Workflow

```bash
# Fast feedback (after every code change) — ~3 min, no infra, uses MOCKS
make qa

# Frontend fast feedback — ~10 sec, no infra, uses MOCKS
cd apps/worldview-web && pnpm test && pnpm typecheck
```

### Before Committing (verify real platform health)

```bash
# Start dev stack (first time or after dev-reset)
make dev && make seed

# Test against REAL running backend — no mocks
make qa-live-stack                # Frontend vs real API (~1 min)
make qa-exhaustive-backend        # All S9 endpoints (~30 sec)
make qa-contract                  # Mock fixture accuracy (~10 sec)
```

**Why this order?** `qa-live-stack` tells you "does the platform work for a real user?" — which is the question that matters. If it passes, commit confidently. If it fails, you have a real bug (not a mock drift).

### Full Validation (before PR or QA certification)

```bash
# Clean slate
make dev-reset && make dev && make seed

# All layers — from mocked to real
make qa                           # Static + unit (~3 min) — mocked
make qa-exhaustive                # Endpoint + frontend QA (~5 min) — mixed
make qa-live-stack                # Frontend vs real API (~1 min) — REAL
make qa-contract                  # Mock alignment (~10 sec) — REAL

# Full pipeline (optional, ~20 min)
./scripts/test-full.sh --no-cleanup
```

### Single-Service Development

```bash
# Python unit tests for one service
make test-unit SERVICE=portfolio

# From the service directory (more control over markers/filters)
cd services/portfolio
python -m pytest tests/unit/ -v --tb=short

# Run with a specific marker
cd services/portfolio
python -m pytest tests/ -m "unit and not slow" -v
```

### Frontend Development

```bash
cd apps/worldview-web

# Unit tests (fast)
pnpm test                  # Single run
pnpm test:watch            # Watch mode (re-runs on file change)

# Type checking
pnpm typecheck             # tsc --noEmit

# E2E (starts dev server automatically)
pnpm test:e2e              # Chromium + WebKit
pnpm test:e2e -- --project=chromium --headed  # Chromium only, visible browser

# Coverage report
pnpm test:coverage         # Generates text + JSON + HTML reports
```

---

## Test File Inventory

### Python Tests by Service

| Service | Total Test Files | Unit | Integration | E2E | Top-Level |
|---------|:---:|:---:|:---:|:---:|:---:|
| alert | 36 | 26 | 6 | 1 | 0 |
| api-gateway | 17 | 5 | 2 | 0 | 10 |
| content-ingestion | 66 | 58 | 5 | 2 | 1 |
| content-store | 35 | 28 | 4 | 1 | 2 |
| intelligence-migrations | 1 | 0 | 0 | 0 | 1 |
| knowledge-graph | 61 | 52 | 7 | 1 | 1 |
| market-data | 48 | 34 | 7 | 2 | 2 |
| market-ingestion | 37 | 1 | 3 | 1 | 4 |
| nlp-pipeline | 41 | 36 | 2 | 1 | 1 |
| portfolio | 61 | 35 | 12 | 2 | 2 |
| rag-chat | 33 | 31 | 1 | 0 | 1 |
| **Total** | **436** | **306** | **49** | **11** | **25** |

### Python Tests by Library

| Library | Test Files |
|---------|:---:|
| common | 3 |
| contracts | 10 |
| messaging | 11 |
| ml-clients | 3 |
| observability | 3 |
| storage | 6 |
| **Total** | **36** |

### Root-Level Python Tests

| Directory | Test Files | Purpose |
|-----------|:---:|---------|
| `tests/architecture/` | 15 | Structural compliance (layer boundaries, shared lib usage, config patterns) |
| `tests/contract/` | 3 | Avro schema + cross-service contract validation |
| `tests/e2e/` | 8 | Cross-service pipeline E2E (Docker Compose backed) |
| **Total** | **26** | |

### Frontend Tests (`apps/worldview-web`)

| File | Type | What It Covers |
|------|------|---------------|
| `__tests__/AuthContext.test.tsx` | Vitest | Auth context provider, token state |
| `__tests__/AlertStreamContext.test.tsx` | Vitest | WebSocket alert stream context |
| `__tests__/AskAiPanel.test.tsx` | Vitest | AI chat panel component |
| `__tests__/chat.test.tsx` | Vitest | Chat page rendering |
| `__tests__/dashboard.test.tsx` | Vitest | Dashboard page + widgets |
| `__tests__/screener.test.tsx` | Vitest | Screener page + heat cells |
| `__tests__/alerts-page.test.tsx` | Vitest | Alerts page rendering |
| `__tests__/workspace.test.tsx` | Vitest | Workspace grid layout |
| `__tests__/settings.test.tsx` | Vitest | Settings page sections |
| `__tests__/portfolio.test.tsx` | Vitest | Portfolio page + holdings |
| `__tests__/instrument-detail.test.tsx` | Vitest | Instrument detail page |
| `__tests__/instrument-graph.test.tsx` | Vitest | Entity graph (sigma.js) |
| `__tests__/gateway.test.ts` | Vitest | S9 gateway client functions |
| `__tests__/market-schedule.test.ts` | Vitest | Market hours utility |
| `__tests__/utils.test.ts` | Vitest | Utility functions (cn, formatters) |
| `e2e/auth.spec.ts` | Playwright | Login flow, auth redirects |
| `e2e/navigation.spec.ts` | Playwright | Nav rail, route transitions |
| `e2e/dashboard.spec.ts` | Playwright | Dashboard rendering E2E |
| `e2e/workspace.spec.ts` | Playwright | Workspace panels E2E |
| `e2e/search.spec.ts` | Playwright | Command palette search E2E |
| `e2e/authenticated-pages.spec.ts` | Playwright | All auth routes render |
| `e2e/qa-exhaustive.spec.ts` | Playwright | Comprehensive QA (~37 tests, 9 groups) — **mocked API** |
| `e2e/qa-live-stack.spec.ts` | Playwright | Live-stack QA (18 tests) — **REAL API, no mocks** |

---

## Configuration Files

| File | Tool | Purpose |
|------|------|---------|
| `pytest.ini` (repo root) | pytest | Root-level test config: `asyncio_mode=auto`, strict markers, `-ra -q` addopts |
| `services/*/mypy.ini` | mypy | Per-service type checking config |
| `libs/*/mypy.ini` | mypy | Per-lib type checking config |
| `ruff.toml` (repo root) | ruff | Lint + format config: `line-length=120`, `fix=true` |
| `apps/worldview-web/vitest.config.ts` | Vitest | Frontend unit test config: jsdom env, path aliases, coverage |
| `apps/worldview-web/vitest.setup.ts` | Vitest | Global setup: jest-dom matchers, jsdom stubs (scrollIntoView, ResizeObserver) |
| `apps/worldview-web/playwright.config.ts` | Playwright | E2E config: Chromium + WebKit, auto-start dev server on `:3001` |
| `apps/worldview-web/tsconfig.json` | TypeScript | TS config for type checking (`pnpm typecheck`) |
| `apps/worldview-web/.eslintrc.json` | ESLint | Frontend lint config (next/core-web-vitals) |
| `infra/compose/docker-compose.test.yml` | Docker Compose | Test infrastructure stack definition |

### Pytest Markers (from `pytest.ini`)

```ini
[pytest]
testpaths = tests
asyncio_mode = auto
addopts = -ra -q --strict-markers
markers =
    unit: fast isolated unit tests
    integration: tests requiring infrastructure (DB, Kafka, MinIO)
    contract: Avro / OpenAPI schema compatibility tests
    e2e: end-to-end scenario tests (in-process ASGI, testcontainers)
    slow: long-running tests excluded from CI fast path
```

---

## Adding New Tests

### Python service unit test

1. **Where to put it**: `services/<service>/tests/unit/<module>/test_<name>.py`
2. **Mark it**: add `@pytest.mark.unit` (or omit -- unit is the default)
3. **Mock infrastructure**: all DB, Kafka, and external calls must be mocked (no real connections in unit tests)
4. **Run it**:
   ```bash
   cd services/<service>
   python -m pytest tests/unit/<module>/test_<name>.py -v
   ```
5. **Verify via CI gate**: `make qa` must still pass

### Python service integration test

1. **Where to put it**: `services/<service>/tests/integration/test_<name>.py`
2. **Mark it**: `@pytest.mark.integration`
3. **Requires**: running Postgres/Kafka/MinIO (provided by Docker Compose test stack)
4. **Run it**: `./scripts/test-full.sh --no-cleanup` or start infra manually with `make infra-up`

### Python architecture test

1. **Where to put it**: `tests/architecture/test_<pattern>.py`
2. **Pattern**: read source files via `pathlib`/`ast`, assert structural invariants
3. **Run it**: `make test-arch`

### Frontend unit test (Vitest)

1. **Where to put it**: `apps/worldview-web/__tests__/<name>.test.tsx` (or co-located next to the component as `*.test.tsx`)
2. **Framework**: React Testing Library + Vitest
3. **Mock API calls**: use `vi.mock()` or MSW for fetch mocking
4. **Key imports**:
   ```typescript
   import { render, screen } from "@testing-library/react";
   import userEvent from "@testing-library/user-event";
   import { describe, it, expect, vi } from "vitest";
   ```
5. **Run it**:
   ```bash
   cd apps/worldview-web
   pnpm test                    # All unit tests
   pnpm test -- __tests__/<name>.test.tsx  # Single file
   ```

### Frontend E2E test (Playwright)

1. **Where to put it**: `apps/worldview-web/e2e/<name>.spec.ts`
2. **Mock API**: use `page.route()` with shared fixtures from `e2e/fixtures/api-mocks.ts`:
   ```typescript
   import { installStrictApiMocks } from "./fixtures/api-mocks";

   test.beforeEach(async ({ page }) => {
     await installStrictApiMocks(page);
   });
   ```
3. **Navigate using relative paths**: `await page.goto('/dashboard')` (baseURL is `http://localhost:3001`)
4. **Screenshots**: `await page.screenshot({ path: 'test-results/<name>.png' })`
5. **Run it**:
   ```bash
   cd apps/worldview-web
   pnpm test:e2e                                   # All specs
   npx playwright test e2e/<name>.spec.ts           # Single spec
   npx playwright test e2e/<name>.spec.ts --headed  # Visible browser
   ```
6. **Debug**: `npx playwright test --debug e2e/<name>.spec.ts` opens the Playwright Inspector

### Live-stack QA test

To add a new endpoint to the backend exhaustive QA:
1. **Edit**: `scripts/qa_exhaustive.py`
2. **Use the `record()` helper**: `record("category", "test_name", passed=True/False, detail="...")`
3. **For expected failures** (known unimplemented endpoints): use `expected_fail="TICKET-ID"`
4. **No mocks**: all requests hit the live S9 at `http://localhost:8000`
5. **Run it**: `make qa-exhaustive-backend` (requires `make dev && make seed`)

---

## Test Scripts Reference

| Script | Purpose | Usage |
|--------|---------|-------|
| `scripts/test.sh` | Unified entry point for Python + frontend tests | `./scripts/test.sh [--integration] [--frontend unit\|e2e\|all] [--full]` |
| `scripts/test-libs.sh` | Library tests (unit, optionally integration with MinIO) | `./scripts/test-libs.sh [--integration] [--lib <name>]` |
| `scripts/run-unit-tests.sh` | Service unit tests (all or single) | `./scripts/run-unit-tests.sh [<service-dir>]` |
| `scripts/test-full.sh` | Full layered suite with Docker Compose lifecycle | `./scripts/test-full.sh [--no-cleanup] [--retain-logs always]` |
| `scripts/qa_exhaustive.py` | Backend exhaustive QA against live dev stack | `python3 scripts/qa_exhaustive.py` |
| `scripts/qa_contract_alignment.py` | **Mock↔API shape alignment** — detects mock drift | `python3 scripts/qa_contract_alignment.py` |
| `scripts/qa_endpoint_test.py` | In-container endpoint test (runs inside api-gateway Docker container) | `docker compose exec -T api-gateway python3 /app/qa_endpoint_test.py` |
| `scripts/test-docker-builds.sh` | Validates all Dockerfiles build successfully | `./scripts/test-docker-builds.sh` |
| `scripts/test-quick.sh` | Quick smoke test subset | `./scripts/test-quick.sh` |
| `scripts/test-secrets.sh` | Validates secret files exist and are non-empty | `./scripts/test-secrets.sh` |
| `scripts/test-alertmanager-email.sh` | Tests Alertmanager email notification delivery | `./scripts/test-alertmanager-email.sh` |

---

## Troubleshooting

### Common issues

**"No Python interpreter found"**: Activate the repo venv (`source .venv312/bin/activate`) or set `PYTHON=/path/to/python3.12`.

**pytest-asyncio crash on collection**: Ensure `pytest-asyncio>=0.23.4` (0.23.0 has a Package object bug with `asyncio_mode=auto`).

**Ruff format mismatch in pre-commit**: The pre-commit hook uses a pinned ruff from `~/.cache/pre-commit/`. Run `ruff format` with the same version, or fix files before `git add` to avoid staged/working-tree divergence (see BP-023, BP-127).

**Vitest "scrollIntoView is not a function"**: The `vitest.setup.ts` should stub it. If you see this error, ensure your test file is matched by `include` in `vitest.config.ts`.

**Playwright timeout waiting for dev server**: The dev server has a 120s startup timeout. If Next.js takes longer (cold start with no cache), increase `timeout` in `playwright.config.ts` or start the server manually first (`pnpm dev`).

**Docker Compose test infra won't start**: Check Docker daemon is running. The test stack uses `infra/compose/docker-compose.test.yml` with `--profile all`. Run `make infra-down` to clean up orphaned containers, then `make infra-up` again.

**Service venv out of date**: `test-full.sh` auto-installs shared libs into each service venv before running tests. If you see import errors, manually run `pip install -e libs/common libs/contracts` etc. in the service venv.

---

## Docker Compose Test Infrastructure Reference

> Operational reference for `infra/compose/docker-compose.test.yml`. For a conceptual overview of what each layer tests see Layer 11 above.

### Stack Design Principles

**tmpfs-backed stateful services.** Postgres, TimescaleDB, MinIO, and Valkey all mount their data directories on tmpfs. Each `docker compose up` starts with a completely blank slate — no leftover rows, blobs, or cache entries from a previous run.

**Healthcheck-gated startup with `--wait`.** Every service declares a healthcheck. Running `docker compose up --wait` blocks until all healthchecks pass before returning. This removes the need for sleep loops in test scripts.

**Profile-driven service selection.** 11 profiles — you only start the services a given test tier needs. Running `--profile portfolio-test` brings up Postgres, Kafka, Schema Registry, and the portfolio-specific containers — nothing more.

**One-shot init containers.** Migration and initialization jobs run as separate containers with `restart: "no"`. Downstream services depend on them via `condition: service_completed_successfully`, so no service starts before its schema is current.

---

### Profile Reference

| Profile | Services | API port(s) |
|---|---|---|
| `portfolio-test` | postgres, kafka, schema-registry, kafka-init, schema-registry-init, portfolio-migrate, portfolio, portfolio-instrument-consumer, portfolio-dispatcher | 8001 |
| `market-ingestion-test` | postgres, minio, minio-init-test, kafka, schema-registry, kafka-init, schema-registry-init, market-ingestion-migrate, market-ingestion, market-ingestion-scheduler, market-ingestion-worker, market-ingestion-dispatcher | 8002 |
| `market-data-test` | timescaledb, valkey, minio, minio-init-test, kafka, schema-registry, kafka-init, schema-registry-init, market-data-migrate, market-data, market-data-dispatcher, market-data-ohlcv-consumer, market-data-quotes-consumer, market-data-fundamentals-consumer, market-data-prediction-market-consumer | 8003 |
| `content-ingestion-test` | postgres, valkey, minio, minio-init-test, kafka, schema-registry, kafka-init, schema-registry-init, content-ingestion-migrate, content-ingestion, content-ingestion-dispatcher, content-ingestion-scheduler, content-ingestion-worker | 8004 |
| `content-store-test` | postgres, valkey, minio, minio-init-test, kafka, schema-registry, kafka-init, schema-registry-init, content-store-migrate, content-store, content-store-dispatcher, content-store-consumer | 8005 |
| `intelligence-test` | postgres (pgvector), valkey, minio, minio-init-test, kafka, schema-registry, kafka-init, schema-registry-init, intelligence-migrations, ollama, gliner-server, nlp-pipeline-migrate, nlp-pipeline, nlp-pipeline-dispatcher, nlp-pipeline-article-consumer, nlp-pipeline-watchlist-consumer, nlp-pipeline-price-impact-worker, nlp-pipeline-unresolved-resolution-worker, knowledge-graph, knowledge-graph-dispatcher, knowledge-graph-scheduler, knowledge-graph-enriched-consumer, knowledge-graph-entity-consumer, knowledge-graph-fundamentals-consumer, knowledge-graph-instrument-consumer, knowledge-graph-temporal-event-consumer | 8006 (nlp-pipeline), 8007 (knowledge-graph) |
| `alert-test` | postgres (pgvector), valkey, kafka, schema-registry, kafka-init, schema-registry-init, alert-migrate, alert, alert-dispatcher, alert-intelligence-consumer, alert-watchlist-consumer, alert-email-scheduler | 8010 |
| `rag-chat-test` | postgres, valkey, rag-chat-migrate, rag-chat | 8008 |
| `api-gateway-test` | valkey, api-gateway | 8000 |
| `dev-tools` | All core infra + kafka-ui (8082), pgadmin (5050) — **local dev only, not used in CI** | — |
| `all` | Every service in the compose file | all ports |

> **`intelligence-test` note**: Both S6 (nlp-pipeline) and S7 (knowledge-graph) share `intelligence_db`. Both are in the same profile. In CI, two separate matrix runners use this profile — one for nlp-pipeline E2E, one for knowledge-graph E2E. GLiNER has a 120-second start period; the `--wait` may take several minutes on first run.

---

### Port Reference

**Core infrastructure (host-mapped)**

| Service | Host port | Container port |
|---|---|---|
| postgres (pgvector) | **55433** | 5432 |
| timescaledb | 5433 | 5432 |
| valkey | 6379 | 6379 |
| minio API | 7480 | 9000 |
| minio console | 7481 | 9001 |
| kafka | 9092 | 9092 |
| schema-registry | 8081 | 8081 |

> Postgres is mapped to 55433 (not 5432) to avoid collisions with a local Postgres instance.

**Service API ports**

| Service | Host port |
|---|---|
| api-gateway (S9) | 8000 |
| portfolio (S1) | 8001 |
| market-ingestion (S2) | 8002 |
| market-data (S3) | 8003 |
| content-ingestion (S4) | 8004 |
| content-store (S5) | 8005 |
| nlp-pipeline (S6) | 8006 |
| knowledge-graph (S7) | 8007 |
| rag-chat (S8) | 8008 |
| alert (S10) | 8010 |
| worldview-web (frontend) | 3001 |
| kafka-ui (dev-tools) | 8082 |
| pgadmin (dev-tools) | 5050 |
| ollama (intelligence-test) | 11434 |
| gliner-server (intelligence-test) | 8090 |

**Connection strings for host-side tests** (pytest running on your machine, not inside a container):

| Infra | Connection string |
|---|---|
| Postgres | `postgresql+asyncpg://postgres:postgres@localhost:55433/<db_name>` |
| TimescaleDB | `postgresql+asyncpg://postgres:postgres@localhost:5433/market_data_db` |
| Kafka | `localhost:9092` |
| Schema Registry | `http://localhost:8081` |
| MinIO API | `http://localhost:7480` (access key: `minioadmin`, secret: `minioadmin`) |
| Valkey | `redis://localhost:6379/0` |

---

### Per-Service E2E Sequences

These sequences mirror exactly what CI does. Run from the repository root.

```bash
# portfolio
docker compose -f infra/compose/docker-compose.test.yml --profile portfolio-test up --build --wait
pytest services/portfolio/tests/e2e -m e2e -v --tb=short
docker compose -f infra/compose/docker-compose.test.yml --profile portfolio-test down -v

# market-ingestion (requires env var overrides for host-side tests)
docker compose -f infra/compose/docker-compose.test.yml --profile market-ingestion-test up --build --wait
export MARKET_INGESTION_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55433/ingestion_db
export MARKET_INGESTION_STORAGE_ENDPOINT=http://localhost:7480
export MARKET_INGESTION_KAFKA_BOOTSTRAP_SERVERS=localhost:9092
export MARKET_INGESTION_SCHEMA_REGISTRY_URL=http://localhost:8081
export MARKET_INGESTION_EODHD_API_KEY=demo
export MARKET_INGESTION_VALKEY_URL=redis://localhost:6379/0
pytest services/market-ingestion/tests/integration -m integration -v --tb=short
pytest services/market-ingestion/tests/e2e -m e2e -v --tb=short
docker compose -f infra/compose/docker-compose.test.yml --profile market-ingestion-test down -v

# market-data
docker compose -f infra/compose/docker-compose.test.yml --profile market-data-test up --build --wait
pytest services/market-data/tests/e2e -m e2e -v --tb=short
docker compose -f infra/compose/docker-compose.test.yml --profile market-data-test down -v

# content-ingestion
docker compose -f infra/compose/docker-compose.test.yml --profile content-ingestion-test up --build --wait
export S4_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55433/content_ingestion_test_db
pytest services/content-ingestion/tests/integration -m integration -v --tb=short
pytest services/content-ingestion/tests/e2e -m e2e -v --tb=short
docker compose -f infra/compose/docker-compose.test.yml --profile content-ingestion-test down -v

# content-store
docker compose -f infra/compose/docker-compose.test.yml --profile content-store-test up --build --wait
export S5_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55433/content_store_test_db
pytest services/content-store/tests/integration -m integration -v --tb=short
pytest services/content-store/tests/e2e -m e2e -v --tb=short
docker compose -f infra/compose/docker-compose.test.yml --profile content-store-test down -v

# nlp-pipeline (uses intelligence-test profile — also starts knowledge-graph)
docker compose -f infra/compose/docker-compose.test.yml --profile intelligence-test up --build --wait
pytest services/nlp-pipeline/tests/e2e -m e2e -v --tb=short
docker compose -f infra/compose/docker-compose.test.yml --profile intelligence-test down -v

# knowledge-graph (same profile as nlp-pipeline)
docker compose -f infra/compose/docker-compose.test.yml --profile intelligence-test up --build --wait
pytest services/knowledge-graph/tests/e2e -m e2e -v --tb=short
docker compose -f infra/compose/docker-compose.test.yml --profile intelligence-test down -v

# alert
docker compose -f infra/compose/docker-compose.test.yml --profile alert-test up --build --wait
pytest services/alert/tests/e2e -m e2e -v --tb=short
docker compose -f infra/compose/docker-compose.test.yml --profile alert-test down -v
```

---

### One-Shot Init Containers

These containers run once per `docker compose up`, complete successfully, and exit. Downstream services depend on them via `condition: service_completed_successfully`.

| Container | What it does |
|---|---|
| `minio-init-test` | Creates test buckets in MinIO |
| `kafka-init` | Creates all Kafka topics |
| `schema-registry-init` | Registers all Avro schemas from `infra/kafka/schemas/*.avsc` |
| `portfolio-migrate` | `alembic upgrade head` for `portfolio_db` |
| `market-ingestion-migrate` | `alembic upgrade head` for `ingestion_db` |
| `market-data-migrate` | `alembic upgrade head` for `market_data_db` |
| `content-ingestion-migrate` | `alembic upgrade head` for `content_ingestion_db` |
| `content-store-migrate` | `alembic upgrade head` for `content_store_db` |
| `intelligence-migrations` | `alembic upgrade head` for `intelligence_db` + seed SQL |
| `nlp-pipeline-migrate` | `alembic upgrade head` for nlp-pipeline's own tables |
| `alert-migrate` | `alembic upgrade head` for `alert_db` |
| `rag-chat-migrate` | `alembic upgrade head` for `rag_chat_db` |

> **S7 (knowledge-graph) has no migrate container.** Its DDL is entirely owned by `intelligence-migrations`. S7 connects to `intelligence_db` with `ALEMBIC_ENABLED=false`.

---

### Docker Compose Debugging

```bash
# Status of a specific profile
docker compose -f infra/compose/docker-compose.test.yml --profile portfolio-test ps

# Tail all logs for a profile
docker compose -f infra/compose/docker-compose.test.yml --profile portfolio-test logs -f

# Tail logs for a single container
docker compose -f infra/compose/docker-compose.test.yml --profile intelligence-test logs -f gliner-server

# Check migration container logs first when a profile fails to start
docker compose -f infra/compose/docker-compose.test.yml --profile portfolio-test logs portfolio-migrate

# Open shell inside a running container
docker compose -f infra/compose/docker-compose.test.yml --profile portfolio-test exec portfolio /bin/bash

# Force full rebuild (bypasses Docker layer cache)
docker compose -f infra/compose/docker-compose.test.yml --profile portfolio-test build --no-cache portfolio
```

**Common Docker Compose failure modes:**

- **Migration container exits non-zero** — the API service will never become healthy. Check the `*-migrate` container logs.
- **Schema Registry never healthy** — depends on Kafka. Increase Docker Desktop memory (4 GB minimum, 8 GB recommended).
- **`--wait` times out** — most common culprits: (1) a `*-migrate` failed, (2) GLiNER needs >120s to download the model on first run, (3) Kafka not ready within its start period on a slow machine.
- **Connection refused from local pytest** — test is using container-internal DNS (`postgres:5432`) instead of host-mapped port (`localhost:55433`). Add the env var overrides from the per-service E2E sequence above.
- **Port already in use** — a local service is bound to the same port. Stop it or change the host mapping in the compose file.
- **Stale images after code changes** — use `--build --no-cache` to force a full rebuild.

---

## Interpreting Test Execution Reports

`scripts/test-full.sh` generates a `TEST_EXECUTION_REPORT.md` (and `TEST_EXECUTION_SUMMARY.json`) in `docs/testing/test-runs/<RUN_ID>/` after each run.

### Report sections

| Section | What it shows |
|---|---|
| **Header & Environment** | Run ID, timestamp, git branch/SHA, Python/Docker versions, duration |
| **Summary** | Suite counts (passed/failed/skipped), total collected tests, total failed tests |
| **By Layer** | Metrics rolled up per layer (architecture, libs, unit, contract, integration, e2e) |
| **By Service** | Metrics rolled up per service — green ✓ / yellow ⊘ (skipped) / red ✗ (failed) |
| **Failure Hotspots** | Ranked list of suites with the most failures |
| **Suite Results** | One-line entry per suite: `<service>:<layer>: <status> (collected=N, duration=Xs)` |
| **Failed Tests** | Per-test: name, suite, kind (error/failure/script_failure), traceback excerpt |

> **"suites" ≠ "tests"**: A suite is a collection like `market-data:unit`. `Total collected tests` aggregates all pytest discoveries. `Total failed tests` is extracted from JUnit XML files.

### Key metrics

- Architecture and Libs layers should **always** pass
- Unit layer should have >95% pass rate
- E2E layer may have transient failures (<5% acceptable)
- Duration: unit <10s, integration/e2e <60s per service

### Common failure signatures

| Log message | Likely cause |
|---|---|
| `fixture_failure` / `OSError: Connect call failed` | DB not ready — check compose logs |
| `pytest exited with code 4` | Import error or missing dependency — check suite log |
| `UniqueViolationError` / `duplicate key` | Test fixture didn't clean up — check fixture isolation |
| `httpx.ConnectError` / `Connection refused` | API service didn't start — usually transient, rerun |
| `failure_type=script_failure` on api-gateway | pytest couldn't run — check service config and imports |
