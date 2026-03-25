# Test Infrastructure Map

Last updated: 2026-03-24

## Current Test Files

- Total Python test files: 155
- Total test-related files (including conftest): 176
- Approximate test cases (heuristic from `def test_`): 990
- Coverage gate configured at repository level: 60% minimum in `pyproject.toml`

### Distribution by test folder type

- Unit-style files (`/tests/unit/`): 44
- Integration files (`/tests/integration/`): 20
- Contract files (`/tests/contract/`): 10
- Architecture files (`tests/architecture/`): 8
- E2E files (`/tests/e2e/`): 5
- Live external tests (`/tests/live/`): 2
- Other tests (service root/domain/api/infrastructure/platform_qa): 66

## Test Organization

### Top-level tests

- `tests/architecture/`: global architecture invariant tests
- No top-level `tests/unit`, `tests/integration`, or `tests/e2e` directories currently
- Top-level contract namespace now scaffolded at `tests/contract/templates/`

### Service-level tests

Primary service test roots:

- `services/portfolio/tests/`
- `services/market-ingestion/tests/`
- `services/market-data/tests/`
- `services/content-ingestion/tests/`
- `services/content-store/tests/`
- `services/knowledge-graph/tests/`
- `services/api-gateway/tests/`
- `services/nlp-pipeline/tests/`
- `services/rag-chat/tests/`
- `services/alert/tests/`

### Shared library tests

- `libs/common/tests/`
- `libs/contracts/tests/`
- `libs/messaging/tests/`
- `libs/storage/tests/`
- `libs/observability/tests/`
- `libs/ml-clients/tests/`

### Pytest configuration

From both `pytest.ini` and `pyproject.toml`:

- `testpaths = tests`
- `asyncio_mode = auto`
- `addopts = -ra -q --strict-markers`
- markers include `unit`, `integration`, `contract`, `e2e`, `slow`

Important observation:

- Root defaults target only `tests/`, while most tests are service-local (`services/*/tests`) and lib-local (`libs/*/tests`).
- CI handles this explicitly by invoking pytest on each service/lib path.

## Service Test Matrix

Service | Unit Tests | Contract Tests | Integration Tests | E2E Tests
--------|------------|----------------|-------------------|----------
alert | N | Y | N | N
api-gateway | N | N | N | N
content-ingestion | Y | N | N | N
content-store | N | N | N | N
knowledge-graph | N | N | N | N
market-data | Y | N | Y | Y
market-ingestion | N | N | Y | Y
nlp-pipeline | N | N | N | N
portfolio | Y | Y | Y | Y
rag-chat | N | N | N | N

Notes:

- Contract testing is most mature in `portfolio`.
- `market-data` has integration/e2e coverage but no explicit contract marker usage in current inventory.
- Several services currently have only health/smoke-level tests.

## CI/CD Test Execution Landscape

Current GitHub Actions workflow (`.github/workflows/ci.yml`) includes:

- fast path jobs:
  - lint + mypy on libs
  - schema validation (`infra/kafka/schemas/*.avsc`)
  - service structure checks
  - import guards
  - architecture tests
  - per-lib tests
  - frontend typecheck/lint/tests/build
- service unit job matrix (`test-services`)
- contract tests currently focused on portfolio (`test-contract`)
- testcontainers integration job for portfolio + market-data (`test-integration`)
- compose-backed e2e matrix for portfolio + market-ingestion + market-data (`test-e2e`)

## Integration Test Matrix (Current)

Interaction | Coverage State | Test Location
-----------|----------------|--------------
portfolio API + persistence + outbox | Covered | `services/portfolio/tests/integration/`
market-data pipeline + infra adapters | Covered | `services/market-data/tests/integration/`
market-ingestion scheduler/worker/outbox | Covered (infra-backed) | `services/market-ingestion/tests/integration/` + `platform_qa/`
cross-service full e2e (selected profiles) | Covered for 3 services | service `tests/e2e/` + CI compose matrix
all-service interaction matrix | Not covered | N/A

## Gaps Identified

### High-risk gaps

1. No unified top-level contract test suite across all services/events.
2. Contract tests heavily concentrated in portfolio; other services lack parity.
3. Root pytest defaults do not include service/lib test roots, which can confuse local execution.
4. No single command currently orchestrates layered full-suite execution from repository root.

### Medium-risk gaps

1. No dedicated, centralized test infrastructure guide for compose profiles and env requirements.
2. No standardized reusable contract test templates at repo-level before this wave.
3. Live tests exist but are not clearly separated in central testing docs/runbooks.

### Low-risk gaps

1. Missing shared archive docs for agent planning/task workflows.
2. Test naming/tier structure not fully normalized across services (domain/api/infrastructure folders mixed with unit/integration).

## Immediate Remediation Added In This Wave

- Added centralized docs:
  - `docs/testing/TEST_INFRASTRUCTURE_MAP.md`
  - `docs/testing/DOCKER_COMPOSE_TEST_GUIDE.md`
  - `docs/testing/TEST_EXECUTION_REPORT.md`
  - `docs/testing/TESTING_GUIDE.md`
- Added root helper scripts:
  - `scripts/test-quick.sh`
  - `scripts/test-full.sh`
  - `scripts/wait-for-services.sh`
- Added reusable contract test templates:
  - `tests/contract/templates/`
