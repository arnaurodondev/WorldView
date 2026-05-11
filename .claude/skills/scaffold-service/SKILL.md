---
name: scaffold-service
description: "Scaffold a new FastAPI microservice following worldview's hexagonal architecture. Creates all layers (domain, application, infrastructure, API), pyproject.toml, Alembic, docker-compose entry, .claude-context.md, and initial tests. Use when starting a new service (S8, S11, etc.)."
user-invocable: true
argument-hint: "[service name (e.g. 'rag-chat' or 'S8'), port number, and brief description]"
effort: heavy
---

# Scaffold Service — Hexagonal Architecture Bootstrapper

You are a **Staff Engineer** scaffolding a new FastAPI microservice in the worldview platform. Your job is to produce a complete, standards-compliant skeleton that an agent can immediately start implementing features into — no missing files, no wrong layer boundaries, no placeholder violations.

## Input

Service description: `$ARGUMENTS`
Parse from arguments: service name (slug), port number, brief one-line mission.

---

## Step 1 — Context Loading

1. Read `docs/MASTER_PLAN.md` — identify the new service's ID (S1–S10+), assigned port, DB name, and mission statement
2. Read `RULES.md` — pay special attention to R22 (process topology), R25 (API layer), R27 (read replica)
3. Read an existing mature service for reference patterns:
   - `services/portfolio/` — reference for DB-heavy service with full domain layer
   - `services/market-data/` — reference for TimescaleDB + read-replica pattern
4. Read `services/portfolio/pyproject.toml` — copy dep list as starting point
5. Read `services/portfolio/.claude-context.md` — reference for context file format
6. Check `infra/compose/docker-compose.yml` — understand compose service definition pattern
7. Read `docs/plans/TRACKING.md` — record this scaffold as a new plan if needed

### Determine what already exists:
```bash
ls services/<service-name>/ 2>/dev/null || echo "new"
```

---

## Step 2 — Directory Structure

Create the following structure:

```
services/<service-name>/
├── .claude-context.md          ← agent context file (write last)
├── pyproject.toml              ← Hatch packaging, deps, pytest config
├── mypy.ini                    ← mirrors portfolio/mypy.ini
├── alembic.ini                 ← if service owns its own DB
├── alembic/
│   ├── env.py                  ← wired to Base.metadata
│   └── versions/               ← empty, migrations go here
├── configs/
│   └── dev.local.env.example   ← all env vars with example values
├── src/<service_module>/
│   ├── __init__.py
│   ├── config.py               ← pydantic-settings Settings class
│   ├── app.py                  ← FastAPI lifespan, routers, exception handlers
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── enums.py            ← StrEnum definitions
│   │   ├── errors.py           ← DomainError hierarchy
│   │   ├── value_objects.py    ← frozen dataclasses
│   │   ├── events.py           ← DomainEvent ABC + concrete events
│   │   └── entities/
│   │       └── __init__.py
│   ├── application/
│   │   ├── __init__.py
│   │   ├── ports/
│   │   │   └── __init__.py     ← ABC port interfaces
│   │   └── use_cases/
│   │       └── __init__.py     ← UseCase classes (empty stubs)
│   ├── infrastructure/
│   │   ├── __init__.py
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── models.py       ← SQLAlchemy ORM (DeclarativeBase + Mapped)
│   │   │   ├── session.py      ← create_session_factory()
│   │   │   └── unit_of_work.py ← SqlAlchemyUnitOfWork
│   │   └── kafka/
│   │       └── __init__.py
│   └── api/
│       ├── __init__.py
│       ├── dependencies.py     ← FastAPI dependency functions (UoWDep, ReadUoWDep)
│       └── v1/
│           ├── __init__.py
│           └── health.py       ← GET /health endpoint
└── tests/
    ├── __init__.py
    ├── conftest.py             ← pytest fixtures
    └── unit/
        ├── __init__.py
        └── test_health.py      ← smoke test for /health endpoint
```

**Skip Alembic** if the service is stateless (no DB) or if it shares `intelligence_db` (S6/S7 pattern — those set `ALEMBIC_ENABLED=false`).

---

## Step 3 — Key Files to Write

### 3.1 `pyproject.toml`
Copy from `services/portfolio/pyproject.toml` and modify:
- `[project] name` → service package name
- `[project.scripts]` → entrypoints for api_main, consumer_main, dispatcher_main (add only what applies)
- Keep all lib deps: `common`, `contracts`, `messaging`, `storage`, `observability`
- Add `ml-clients` only if service calls ML models
- Keep dev deps: `pytest`, `pytest-asyncio`, `httpx`, `ruff`, `mypy`

### 3.2 `config.py`
```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from common.ids import new_uuid7  # noqa: F401 (re-export)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "<service-name>"
    database_url: str = "postgresql+asyncpg://..."
    read_replica_url: str | None = None

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_schema_registry_url: str = "http://localhost:8081"

    # Observability
    otlp_endpoint: str | None = None
    log_level: str = "INFO"
```

### 3.3 `app.py`
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from observability import get_logger, add_prometheus_middleware  # type: ignore[import-untyped]
from .<service_module>.config import Settings
from .<service_module>.api.v1 import health

logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: create engine, session factory
    yield
    # shutdown: dispose engine

def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or Settings()
    app = FastAPI(title="<Service Name>", lifespan=lifespan)
    add_prometheus_middleware(app)
    app.include_router(health.router, prefix="/api/v1")
    return app
```

### 3.4 `domain/errors.py`
```python
class DomainError(Exception):
    """Base domain error — never expose directly to API layer."""

class NotFoundError(DomainError): ...
class ConflictError(DomainError): ...
class ValidationError(DomainError): ...
```

### 3.5 `api/v1/health.py`
```python
from fastapi import APIRouter
router = APIRouter(tags=["health"])

@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

### 3.6 `tests/unit/test_health.py`
```python
import pytest
from httpx import AsyncClient, ASGITransport
from <service_module>.app import create_app

@pytest.mark.asyncio
@pytest.mark.unit
async def test_health_endpoint():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

---

## Step 4 — Docker Compose Entry

Read `infra/compose/docker-compose.yml` and add:

```yaml
  <service-name>:
    build:
      context: ../..
      dockerfile: services/<service-name>/Dockerfile
    profiles: ["infra"]
    ports:
      - "<port>:<port>"
    env_file: services/<service-name>/configs/dev.local.env.example
    depends_on:
      postgres:
        condition: service_healthy
      kafka:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:<port>/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

Also add to `infra/postgres/init.sql`:
```sql
CREATE DATABASE <service_db> OWNER worldview;
```

---

## Step 5 — `.claude-context.md`

Write `services/<service-name>/.claude-context.md` using this template:

```markdown
# <Service Name> (.claude-context.md)

> Agent context — read this before implementing anything in this service.

## Service Identity
- **ID**: S<N>
- **Port**: <port>
- **Database**: `<db_name>` (PostgreSQL)
- **Mission**: <one-line mission>

## Key Entities
<!-- Add entities as they are implemented -->

## Key Topics
| Topic | Direction | Schema | Purpose |
|-------|-----------|--------|---------|
<!-- Add Kafka topics as they are implemented -->

## Process Topology (R22)
| Process | Entrypoint | Role |
|---------|-----------|------|
| API | `<module>.app:create_app` | HTTP API |
<!-- Add consumers/dispatchers as implemented -->

## Test Commands
```bash
cd services/<service-name>
source ../../.venv312/bin/activate
python -m pytest tests/unit -v -m unit
python -m pytest tests/integration -v -m integration  # needs infra
```

## Known Pitfalls
<!-- Add pitfalls as you encounter them -->

## Architecture Notes
<!-- Service-specific decisions -->
```

---

## Step 6 — Validation

```bash
# Syntax check
python3 -m py_compile services/<service-name>/src/<module>/config.py
python3 -m py_compile services/<service-name>/src/<module>/app.py

# Unit test smoke
cd services/<service-name>
pip install -e ".[dev]"
python -m pytest tests/unit -v -m unit
```

---

## Step 7 — Documentation

1. Update `docs/MASTER_PLAN.md`:
   - Add new service row to the service catalog table (status: `🔄 In-progress`)
   - Add DB to infrastructure table
   - Add port to port inventory

2. Create `docs/services/<service-name>.md` from the template in `docs/services/portfolio.md`

3. Update `docs/plans/TRACKING.md` — record new scaffold plan if this creates a standalone plan

---

## Compounding Check

After scaffolding:
- New service doc created → `docs/services/<service-name>.md`
- MASTER_PLAN.md updated → service catalog + ports
- `.claude-context.md` written → per-service context
- Tests passing → at minimum the /health smoke test

The scaffold is NOT done until `test_health.py` passes.
