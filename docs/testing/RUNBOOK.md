# Testing Runbook

> Complete guide for running unit, integration, and e2e tests across the worldview platform.

---

## Quick Reference

| What you want to do | Command |
|---------------------|---------|
| Run all Python unit tests (no infra) | `./scripts/test.sh` |
| Run unit tests for one service | `./scripts/run-unit-tests.sh services/api-gateway` |
| Run unit tests for all libs | `./scripts/test-libs.sh` |
| Run lib integration tests (MinIO) | `./scripts/test-libs.sh --integration` |
| Run frontend unit tests + typecheck | `./scripts/test.sh --frontend unit` |
| Run frontend e2e (Playwright) | `./scripts/test.sh --frontend e2e` |
| Run everything | `./scripts/test.sh --full` |
| Full suite with Docker infra | `./scripts/test-full.sh` |
| Run integration + e2e for one service | `./scripts/test-full.sh --no-cleanup` (then run tests manually against live compose) |

---

## Test Layers

### Layer 1: Python Unit Tests (no infra required)

Unit tests run fully in-process with no external dependencies. They mock databases, Kafka, and S3.

**Prerequisites**: Python 3.12 venv activated (`source .venv312/bin/activate` at repo root).

```bash
# All services + libs
./scripts/test.sh

# All services only
./scripts/run-unit-tests.sh

# One service
./scripts/run-unit-tests.sh services/api-gateway

# All libs only
./scripts/test-libs.sh

# One lib
./scripts/test-libs.sh --lib common
```

**pytest markers**: `unit` (default filter applied by the scripts above)

```bash
# Manually, from inside a service directory:
cd services/api-gateway
python -m pytest tests/ -m "not integration and not e2e and not live" -v
```

---

### Layer 2: Python Integration Tests (Docker infra required)

Integration tests hit a real Postgres (port 55433), Kafka (port 59092), and MinIO (port 59000) running in Docker. They use a separate test database per service (no shared state with development).

**Prerequisites**: Docker Desktop running.

**Start test infra (all profiles)**:
```bash
docker compose -f infra/compose/docker-compose.test.yml --profile all up -d --build --wait
```

**Start only what you need (per-service profiles)**:
```bash
# Profiles available: postgres, kafka, minio, valkey, all
# Plus per-service shortcuts: content-ingestion, market-data, knowledge-graph, etc.

# Example: only postgres + kafka (for api-gateway integration tests)
docker compose -f infra/compose/docker-compose.test.yml --profile postgres --profile kafka up -d --wait

# Example: all infra for content-ingestion
docker compose -f infra/compose/docker-compose.test.yml --profile content-ingestion up -d --wait
```

**Run integration tests**:
```bash
# All services (requires all infra up)
./scripts/test.sh --integration

# One service
cd services/content-ingestion
python -m pytest tests/integration/ -m integration -v

# All libs (starts MinIO automatically)
./scripts/test-libs.sh --integration
```

**Stop infra**:
```bash
docker compose -f infra/compose/docker-compose.test.yml --profile all down -v
```

---

### Layer 3: Python E2E Tests (full infra required)

E2E tests run the full service pipeline end-to-end inside Docker. The test compose spins up all services (including the actual FastAPI apps), runs migrations, seeds topics, and fires real Kafka events through the pipeline.

**Run the full automated suite** (starts infra, runs all layers, collects reports):
```bash
./scripts/test-full.sh
```

**Options**:
```bash
./scripts/test-full.sh --retain-logs always      # Keep all compose logs (default: on-failure)
./scripts/test-full.sh --keep-volumes            # Don't wipe Docker volumes on teardown
./scripts/test-full.sh --no-cleanup              # Leave compose running after tests
./scripts/test-full.sh --integration-mode parallel-safe --parallel-safe-services market-data,portfolio
```

**Reports**: Written to `docs/testing/test-runs/<TIMESTAMP>/`:
- `TEST_EXECUTION_REPORT.md` — human-readable summary
- `TEST_EXECUTION_SUMMARY.json` — machine-readable JSON with per-suite results
- `infra/` — compose logs, container inspect, per-service logs

---

### Layer 4: Frontend Unit Tests (worldview-web)

Vitest + React Testing Library tests in `apps/worldview-web/__tests__/`.

**Prerequisites**: `pnpm install` in `apps/worldview-web/`.

```bash
# Via unified script
./scripts/test.sh --frontend unit

# Directly (from apps/worldview-web/)
cd apps/worldview-web
pnpm typecheck          # TypeScript type check (tsc --noEmit)
pnpm test               # Vitest run (all unit tests)
pnpm test:watch         # Vitest watch mode (for development)
pnpm test:coverage      # Vitest with V8 coverage report
```

**Test files**: `__tests__/**/*.test.tsx` and co-located `*.test.tsx` files.

**Config**: `vitest.config.ts` — jsdom environment, globals enabled.

---

### Layer 5: Frontend E2E Tests (Playwright)

Playwright tests in `apps/worldview-web/e2e/`. Tests run against a real Next.js dev server auto-started by Playwright.

**Prerequisites**:
- `pnpm install` in `apps/worldview-web/`
- Playwright browsers installed: `pnpm exec playwright install --with-deps chromium webkit`
- No backend required — auth and data endpoints are mocked via `page.route()`

```bash
# Via unified script
./scripts/test.sh --frontend e2e

# Directly (from apps/worldview-web/)
cd apps/worldview-web
pnpm test:e2e                        # All tests, all browsers
pnpm test:e2e --project=chromium     # Chromium only (faster for development)
pnpm test:e2e e2e/auth.spec.ts       # One spec file
pnpm test:e2e --ui                   # Interactive Playwright UI (for debugging)
pnpm test:e2e --debug                # Debug mode with step-through
```

**Auth mocking**: E2E tests that require an authenticated user mock `POST /api/v1/auth/refresh` via `page.route()` to return a fake token with a future `exp` claim. No Zitadel backend needed.

**Config**: `playwright.config.ts` — Chromium + WebKit, auto-starts `pnpm dev` on port 3001.

**Reports**: HTML report written to `apps/worldview-web/playwright-report/` after each run.

---

### Layer 6: Full Suite (all layers)

```bash
# Python + frontend unit + frontend e2e
./scripts/test.sh --full

# Python + infra integration + e2e (complete)
./scripts/test-full.sh
```

---

## Docker Compose Files

| File | Purpose | When to use |
|------|---------|-------------|
| `infra/compose/docker-compose.test.yml` | **CANONICAL test compose** — ephemeral tmpfs volumes, offset ports (55433, 59092), per-service profiles | All automated testing |
| `infra/compose/docker-compose.yml` | Dev/production compose — persistent volumes, standard ports | Local development, not testing |
| `infra/compose/docker-compose.zitadel.yml` | Zitadel OIDC stack for auth development | Auth development only |
| `docker-compose.yml` (root) | **DEPRECATED** — legacy compose with old Kafka image | Do not use |

### Test Compose Profiles

The test compose (`docker-compose.test.yml`) supports granular profiles:

```bash
# Start only what you need:
--profile postgres          # Postgres 16 (TimescaleDB) on port 55433
--profile kafka             # Kafka + Schema Registry on port 59092
--profile minio             # MinIO on port 59000
--profile valkey            # Valkey (Redis-compatible) on port 56379
--profile all               # Everything above + service-level init containers
```

Individual service profiles (subset of infra needed for that service's tests):
```bash
--profile content-ingestion   # postgres + kafka
--profile market-data         # postgres + kafka
--profile knowledge-graph     # postgres + kafka
--profile nlp-pipeline        # postgres + kafka + minio
--profile alert               # postgres + kafka + valkey
```

---

## Running Individual Services in CI

When you only need to test one service without pulling everything up:

```bash
# Start the minimum infra for api-gateway
docker compose -f infra/compose/docker-compose.test.yml --profile postgres up -d --wait

# Run its tests
cd services/api-gateway
python -m pytest tests/ -v --tb=short

# Tear down
docker compose -f infra/compose/docker-compose.test.yml --profile postgres down -v
```

---

## Pytest Markers

All Python tests use explicit markers registered in each service's `pyproject.toml`:

| Marker | Description | Infra needed |
|--------|-------------|--------------|
| `unit` | In-process, all mocked | None |
| `integration` | Hits real Postgres/Kafka/MinIO | Docker test compose |
| `contract` | Validates Avro schema / API contract | None |
| `e2e` | Full pipeline end-to-end | Full Docker compose |
| `slow` | Takes > 10s | — |
| `live` | Hits real external APIs (EODHD, Polymarket) | External API keys |

Run a specific marker:
```bash
python -m pytest tests/ -m unit -v
python -m pytest tests/ -m "unit or contract" -v
python -m pytest tests/ -m integration -v  # requires infra
```

---

## Common Troubleshooting

### `cryptography` module missing in root venv
```bash
# The root .venv312 may not have cryptography (used by JWT middleware tests)
pip install "cryptography>=42.0" --target .venv312/lib/python3.12/site-packages/
```

### Port conflict with test compose (55433 already in use)
```bash
# Check what's using the port
lsof -i :55433
# Or change the port in docker-compose.test.yml temporarily
```

### Playwright browser not installed
```bash
cd apps/worldview-web
pnpm exec playwright install --with-deps chromium webkit
```

### Frontend e2e test fails to start dev server
```bash
# Ensure port 3001 is free
lsof -i :3001
kill -9 <pid>
# Then retry
pnpm test:e2e
```

### `test-full.sh` compose startup timeout
```bash
# Check which service is unhealthy
docker compose -f infra/compose/docker-compose.test.yml --profile all ps
docker compose -f infra/compose/docker-compose.test.yml logs <service-name>
```

---

## Adding New Tests

### Python unit test
1. Create `tests/unit/test_<feature>.py` in the service directory
2. Mark with `@pytest.mark.unit`
3. Run: `python -m pytest tests/unit/test_<feature>.py -v`

### Python integration test
1. Create `tests/integration/test_<feature>.py`
2. Mark with `@pytest.mark.integration`
3. Use fixtures from `tests/conftest.py` (db session, kafka producer, etc.)
4. Run with infra: `docker compose -f infra/compose/docker-compose.test.yml --profile all up -d --wait && python -m pytest tests/integration/ -m integration`

### Frontend unit test
1. Create `__tests__/<Component>.test.tsx` in `apps/worldview-web/`
2. Use `@testing-library/react` + `vitest`
3. Run: `pnpm test`

### Frontend e2e test
1. Create `e2e/<feature>.spec.ts` in `apps/worldview-web/e2e/`
2. Use `page.route()` to mock S9 endpoints as needed
3. For auth-protected pages: mock `POST /api/v1/auth/refresh` with a fake token
4. Run: `pnpm test:e2e`
