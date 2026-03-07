# Testing Strategy

## Test Pyramid

```
         ╱ ╲
        ╱ E2E╲          ← Few: smoke tests, critical paths
       ╱───────╲
      ╱Contract ╲       ← Schema compatibility
     ╱───────────╲
    ╱ Integration  ╲    ← Service + infra (DB, Kafka, MinIO)
   ╱─────────────────╲
  ╱     Unit Tests     ╲ ← Majority: fast, isolated, no I/O
 ╱───────────────────────╲
```

---

## Pytest Markers

Defined in root `pytest.ini`:

| Marker | When to use | Runs in CI | Needs infra |
|--------|-------------|------------|-------------|
| `@pytest.mark.unit` | Pure logic, no I/O | Always | No |
| `@pytest.mark.integration` | Touches DB, Kafka, MinIO, Valkey | Main only | Yes |
| `@pytest.mark.contract` | Avro schema ↔ dataclass compat | Always | No |
| `@pytest.mark.slow` | Long-running (ML models, large data) | Nightly | Varies |

```bash
pytest -m unit                  # Fast feedback loop
pytest -m "unit or contract"    # Pre-push recommendation
pytest -m integration           # After docker compose up
pytest                          # Everything
```

---

## Test Organisation

```
services/portfolio/
  tests/
    unit/
      test_domain_portfolio.py      # Domain logic
      test_application_services.py   # Use-cases with mocked repos
    integration/
      test_repository_postgres.py    # Real Postgres via testcontainers
      test_kafka_consumer.py         # Real Kafka
    contract/
      test_avro_compatibility.py     # Schema round-trips
    conftest.py                      # Shared fixtures
```

### Shared Fixtures

```python
# conftest.py
@pytest.fixture
def sample_tenant_id():
    return TenantId(uuid.UUID("00000000-0000-0000-0000-000000000001"))

@pytest.fixture
async def db_session(tmp_postgres_url):
    engine = create_async_engine(tmp_postgres_url)
    async with AsyncSession(engine) as session:
        yield session
        await session.rollback()
```

---

## Coverage Targets

| Package type | Target | Rationale |
|-------------|--------|-----------|
| `libs/*` | ≥ 90% | Shared code — high trust required |
| `services/*/domain` | ≥ 90% | Business rules — must be verified |
| `services/*/application` | ≥ 80% | Use-cases |
| `services/*/infrastructure` | ≥ 60% | I/O adapters — integration tests cover these |
| `services/*/api` | ≥ 70% | Routes — tested via httpx + TestClient |

---

## Integration Test Infrastructure

**Approach**: Docker Compose for CI, testcontainers for local.

```python
# Using testcontainers
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="session")
def postgres():
    with PostgresContainer("timescale/timescaledb:latest-pg16") as pg:
        yield pg.get_connection_url()
```

---

## Contract Tests

Verify that Python dataclasses stay compatible with Avro schemas:

```python
def test_ohlcv_bar_matches_avro():
    schema = load_avro_schema("infra/kafka/schemas/market.dataset.fetched.avsc")
    bar = CanonicalOHLCVBar(symbol="AAPL", ...)
    # Must serialize without error
    serialized = serialize_avro(schema, bar.to_dict())
    deserialized = deserialize_avro(schema, serialized)
    assert deserialized["symbol"] == "AAPL"
```

---

## Frontend Testing

The web frontend (`apps/frontend/`) follows a separate test strategy:

| Type | Tool | Location | What |
|------|------|----------|------|
| Unit | Vitest + Testing Library | `apps/frontend/tests/` | Component rendering, hooks |
| E2E | Playwright (Chromium) | `apps/frontend/e2e/` | Navigation, page content |

```bash
cd apps/frontend
pnpm test         # Unit tests
pnpm test:e2e     # E2E tests (starts dev server)
```

---

## What NOT to Test

- Framework internals (FastAPI routing, SQLAlchemy engine)
- Exact log messages (test log *presence*, not wording)
- Third-party API responses (mock them)
- CSS styling details (test behavior, not appearance)

---

## Three-Layer Execution Model

Adopt a 3-layer model to balance fast feedback, realistic service verification,
and full-platform confidence.

| Layer | Scope | Goal | Typical Runtime | CI Trigger |
|------|-------|------|------------------|------------|
| L1 · Unit | Per module/service, no external infra | Validate business logic quickly | 1–8 min | Every PR |
| L2 · Service Container Tests | One service + required infra (DB/Kafka/MinIO/Valkey) | Validate real adapters and migrations | 5–20 min per service | PR (changed services) + main |
| L3 · Full Platform QA | Fresh full stack from scratch | Validate cross-service workflows end-to-end | 20–60+ min | Nightly + pre-release |

### L1 — Unit Tests (fast gate)

- Keep isolated and deterministic (no network, no real infrastructure).
- Focus on domain rules, use-cases, validation, mapping, and pure helpers.
- Required pass condition for all PRs.

### L2 — Service Container Tests (real service validation)

- Start the service under test in containers with only required dependencies.
- Run real migrations (`alembic upgrade head`) before test execution.
- Exercise API routes, consumer/dispatcher loops, repository behavior, and
  serialization with real engines.
- Required pass condition for changed services before merge.

### L3 — Full Platform QA (system confidence)

- Provision complete platform from clean state (databases, Kafka,
  schema-registry, MinIO, Valkey, all active services, frontend if needed).
- Run smoke + critical-path scenarios (ingest → materialize → consume/query).
- Produce report artifacts: failing step, service logs, test traces,
  environment metadata, and summary metrics.
- Start as non-blocking nightly; promote to release gate once stable.

---

## Feasibility Assessment

This model is feasible with current architecture and is recommended.

| Area | Feasibility | Notes |
|------|-------------|-------|
| L1 Unit | High | Already aligned with existing pytest structure and markers |
| L2 Service Containers | High | Requires per-service compose/test profile + deterministic seed data |
| L3 Full Platform QA | Medium-High | Operationally heavier; requires strong orchestration and diagnostics |

### Primary Risks

- Flaky tests from timing/race conditions in async consumers.
- Non-deterministic data fixtures across services.
- Slow feedback if full-stack tests are run on every PR.

### Required Preconditions

- Stable migration path for each service DB.
- Repeatable fixture strategy (idempotent setup/teardown).
- Health/readiness checks for all containers and dependencies.
- Artifact collection in CI (logs, reports, traces) for quick triage.

---

## Recommended Adoption Policy

Use phased rollout:

1. **Phase 1 (immediate)**: enforce L1 on all PRs.
2. **Phase 2**: enforce L2 for changed services on PRs and `main`.
3. **Phase 3**: run L3 nightly and before release tags.
4. **Phase 4**: once flake rate is acceptable, optionally make selected L3
   smoke tests blocking for releases.

### Suggested Gating

| Pipeline Event | Required Layers |
|----------------|-----------------|
| Pull Request | L1 + impacted L2 |
| Merge to `main` | L1 + impacted L2 (+ optional focused L3 smoke) |
| Nightly | Full L3 suite |
| Release Candidate | Full L3 suite (blocking) |

### Flakiness and Quality Targets

- Keep flaky failure rate under 2% in nightly runs.
- Quarantine and ticket flaky tests immediately.
- Track median runtime and failure causes per layer to avoid regression in
  developer feedback loops.

---

## Reporting Requirements

Every L2/L3 run should publish:

- pass/fail summary by service and test class
- failed test list with stack traces
- container logs for failing services
- migration output and health check results
- execution metadata (commit SHA, environment, duration)

This enables independent execution, reproducibility, and faster incident
triage when regressions appear.
