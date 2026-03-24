# Execution Prompt 0013 — Ingestion Pipeline v1: S6+S7+S10 Wave 11

**Wave:** 11 of 13
**Service:** S10 Alert Service
**Focus:** S10 Foundation + Deployment Gate + S1 Contract Testing
**Tasks:** T-S10-001, T-S10-002, T-S10-003, T-S10-011 (parallel)
**Date:** 2026-03-22

---

## Context (read first)

- Planning response: `docs/ai-interactions/agent-responses/0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md`
- Service doc: `docs/services/alert-service.md`

---

## Assigned agent profile(s)

- **backend-engineer** — T-S10-001 (service directory, config, domain), T-S10-002 (alert_db adapter), T-S10-003 (S1 REST client + Valkey cache), T-S10-011 (deployment gate + contract testing)

Single agent can handle all 4 tasks given they are all foundation-level.

---

## Mandatory pre-read

1. `docs/agents/AGENTS.md`
2. `docs/CLAUDE.md`
3. `docs/services/alert-service.md`
4. Wave 10 handoff evidence — confirm S7 is complete and emitting `graph.state.changed.v1`
5. `docs/ai-interactions/agent-responses/0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md` — task details T-S10-001 through T-S10-003, T-S10-011
6. `docs/libs/common.md` — UUIDv7 (`new_uuid7`), UTC time (`utc_now`), cross-service types (`DocumentId`, `EntityId`, `UrlHash`, `MinIOKey`)
7. **`docs/STANDARDS.md`** — engineering standards and anti-patterns: canonical library usage, config conventions, observability setup, testing rules

**PREREQUISITE GATE:** Do not begin Wave 11 until Wave 10 integration test `test_s6_s7_pipeline_continuity` passes. S10 depends on S7 emitting `graph.state.changed.v1`.

---

## Objective

Establish the S10 Alert Service foundation:
- **T-S10-001**: Service directory structure, pyproject.toml, Makefile, config, domain models (Alert, PendingAlert, AlertDedup, AlertType)
- **T-S10-002**: alert_db adapter with 5 repositories; Alembic migrations (S10 OWNS alert_db — Alembic IS enabled here, unlike S6/S7 with intelligence_db)
- **T-S10-003**: httpx S1 client for 2 endpoints + Valkey watchlist cache (TTL=300s); cache-aside pattern
- **T-S10-011**: Document 4 required S1 endpoints; 3 contract tests via pytest-httpserver; deployment gate via readyz; stub strategy for integration tests

Key difference from S6/S7: S10 runs Alembic on `alert_db` at startup — S10 owns alert_db DDL.

---

## Task scope for this wave

### Parallel group (all 4 tasks independent)

**T-S10-001: Service Directory + Config + Domain**
- `services/alert/src/alert_service/config.py`
- `services/alert/src/alert_service/domain/enums.py`
- `services/alert/src/alert_service/domain/models.py`
- `services/alert/pyproject.toml`
- `services/alert/Makefile`
- `services/alert/alembic.ini`

**T-S10-002: alert_db Infrastructure**
- `services/alert/src/alert_service/infrastructure/alert_db/session.py`
- `services/alert/src/alert_service/infrastructure/alert_db/repositories/alert_repository.py`
- `services/alert/src/alert_service/infrastructure/alert_db/repositories/pending_alert_repository.py`
- `services/alert/src/alert_service/infrastructure/alert_db/repositories/alert_dedup_repository.py`
- `services/alert/src/alert_service/infrastructure/alert_db/repositories/idempotency_repository.py`
- `services/alert/src/alert_service/infrastructure/alert_db/repositories/outbox_repository.py`
- `services/alert/alembic/versions/0001_initial_schema.py`

**T-S10-003: S1 REST Client + Valkey Cache**
- `services/alert/src/alert_service/infrastructure/s1_client/client.py`
- `services/alert/src/alert_service/infrastructure/valkey/watchlist_cache.py`

**T-S10-011: Deployment Gate + S1 Contract Testing**
- `services/alert/docs/s1-contract-testing.md`
- `services/alert/tests/contract/test_s1_contract.py`

---

## Why this chunk

Wave 11 mirrors Wave 01 (S6) and Wave 06 (S7) for S10: establish the foundation before consumers and fan-out logic are written. T-S10-011 (contract testing) is grouped here because the S1 dependency must be understood and documented before any S1 calls are implemented (T-S10-003). Contract tests can be written in parallel with the client implementation. All Wave 12 tasks depend on repos (T-S10-002) and the S1 client/cache (T-S10-003).

---

## Implementation instructions

### T-S10-001: Service Directory + Config + Domain

#### Directory structure to create

```
services/alert/
├── src/
│   └── alert_service/
│       ├── __init__.py
│       ├── config.py
│       ├── domain/
│       │   ├── __init__.py
│       │   ├── enums.py
│       │   └── models.py
│       ├── infrastructure/
│       │   ├── __init__.py
│       │   ├── alert_db/
│       │   ├── s1_client/
│       │   ├── valkey/
│       │   └── outbox/
│       ├── application/
│       │   ├── __init__.py
│       │   ├── consumers/
│       │   └── use_cases/
│       └── api/
│           ├── __init__.py
│           └── routes/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── contract/
├── alembic/
│   ├── env.py
│   └── versions/
├── docs/
├── pyproject.toml
├── Makefile
├── alembic.ini
└── README.md
```

#### config.py

```python
# services/alert/src/alert_service/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # alert_db (S10 owns this — Alembic IS enabled)
    ALERT_DB_URL: str

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_GROUP_ID: str = "alert-service-group"
    KAFKA_WATCHLIST_GROUP_ID: str = "alert-service-watchlist-group"

    # Valkey
    VALKEY_URL: str = "redis://localhost:6379"

    # S1 dependency
    S1_BASE_URL: str
    INTERNAL_SERVICE_TOKEN: str

    # Alert behavior
    WATCHLIST_CACHE_TTL_SECONDS: int = 300
    ALERT_DEDUP_WINDOW_SECONDS: int = 300

    # Admin
    ADMIN_TOKEN: str

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
```

#### domain/enums.py

```python
from enum import Enum

class AlertType(str, Enum):
    SIGNAL_DETECTED = "SIGNAL_DETECTED"         # from nlp.signal.detected.v1
    GRAPH_CHANGED = "GRAPH_CHANGED"             # from graph.state.changed.v1
    CONTRADICTION_DETECTED = "CONTRADICTION_DETECTED"  # from intelligence.contradiction.v1
```

#### domain/models.py

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID
from alert_service.domain.enums import AlertType

@dataclass
class Alert:
    id: UUID
    user_id: str
    entity_id: str
    alert_type: AlertType
    payload: dict
    created_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class PendingAlert:
    id: UUID
    alert_id: UUID
    user_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class AlertDedup:
    id: UUID
    dedup_key: str
    expires_at: datetime
```

#### pyproject.toml

```toml
[tool.poetry]
name = "alert-service"
version = "0.1.0"
description = "S10 Alert Service"

[tool.poetry.dependencies]
python = "^3.12"
fastapi = "^0.111.0"
sqlalchemy = {version = "^2.0", extras = ["asyncio"]}
asyncpg = "^0.29"
aiokafka = "^0.10"
prometheus-client = "^0.20"
httpx = "^0.27"
structlog = "^24.0"
pydantic-settings = "^2.0"
alembic = "^1.13"
redis = {version = "^5.0", extras = ["hiredis"]}
pytest-httpserver = "^1.0"

[tool.poetry.dev-dependencies]
pytest = "^8.0"
pytest-asyncio = "^0.23"
ruff = "^0.4"
mypy = "^1.10"
```

#### Makefile

```makefile
test:
	pytest tests/unit/ -v

test-integration:
	docker compose -f docker-compose.test.yml up -d --wait
	pytest tests/integration/ -m integration -v
	docker compose -f docker-compose.test.yml down

test-contract:
	pytest tests/contract/ -v

lint:
	ruff check src/

typecheck:
	mypy src/
```

### T-S10-002: alert_db Infrastructure

#### session.py (Alembic IS enabled — S10 owns alert_db)

```python
# services/alert/src/alert_service/infrastructure/alert_db/session.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from alembic.config import Config
from alembic import command
import structlog

logger = structlog.get_logger(__name__)

async def run_migrations(db_url: str) -> None:
    """Run Alembic migrations on startup. S10 owns alert_db."""
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", db_url.replace("postgresql+asyncpg", "postgresql"))
    command.upgrade(alembic_cfg, "head")
    logger.info("alert_db_migrations_complete")

from alert_service.config import settings

_engine = create_async_engine(settings.ALERT_DB_URL, pool_size=10, max_overflow=5)
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    _engine, class_=AsyncSession, expire_on_commit=False
)
```

#### Initial Alembic migration

```python
# services/alert/alembic/versions/0001_initial_schema.py
"""Initial alert_db schema."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", sa.String, nullable=False),
        sa.Column("entity_id", sa.String, nullable=False),
        sa.Column("alert_type", sa.String, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_table(
        "pending_alerts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("alert_id", UUID, sa.ForeignKey("alerts.id"), nullable=False),
        sa.Column("user_id", sa.String, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_table(
        "alert_dedup",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("dedup_key", sa.String, nullable=False, unique=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("idx_alert_dedup_key", "alert_dedup", ["dedup_key"])
    op.create_index("idx_pending_alerts_user_id", "pending_alerts", ["user_id"])
    op.create_table(
        "outbox_events",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_type", sa.String, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("dispatched_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

def downgrade() -> None:
    op.drop_table("outbox_events")
    op.drop_table("alert_dedup")
    op.drop_table("pending_alerts")
    op.drop_table("alerts")
```

#### Repositories (critical pattern: all inserts in one transaction in fan-out use-case)

```python
# AlertDedupRepository — critical for correctness of dedup
class AlertDedupRepository:
    async def exists(self, dedup_key: str) -> bool:
        from sqlalchemy import text
        result = await self.session.execute(
            text("SELECT 1 FROM alert_dedup WHERE dedup_key = :key AND expires_at > NOW()"),
            {"key": dedup_key}
        )
        return result.fetchone() is not None

    async def insert(self, dedup_key: str, expires_at) -> None:
        from sqlalchemy import text
        await self.session.execute(
            text("INSERT INTO alert_dedup (id, dedup_key, expires_at) VALUES (gen_random_uuid(), :key, :exp) ON CONFLICT (dedup_key) DO NOTHING"),
            {"key": dedup_key, "exp": expires_at}
        )
```

### T-S10-003: S1 REST Client + Valkey Cache

```python
# services/alert/src/alert_service/infrastructure/s1_client/client.py
import httpx
import structlog
from alert_service.config import settings

logger = structlog.get_logger(__name__)

class S1Client:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.S1_BASE_URL,
            headers={"Authorization": f"Bearer {settings.INTERNAL_SERVICE_TOKEN}"},
            timeout=5.0,
        )

    async def get_watchlist_by_entity(self, entity_id: str) -> list[str]:
        """GET /internal/v1/watchlists/by-entity/{entity_id} → list[user_id]"""
        try:
            response = await self._client.get(f"/internal/v1/watchlists/by-entity/{entity_id}")
            response.raise_for_status()
            return response.json().get("user_ids", [])
        except httpx.HTTPStatusError as e:
            logger.warning("s1_get_watchlist_error", entity_id=entity_id, status=e.response.status_code)
            return []
        except Exception as e:
            logger.warning("s1_client_error", entity_id=entity_id, error=str(e))
            return []  # Best-effort — never fail alert processing on S1 error

    async def get_watchlists_by_entities(self, entity_ids: list[str]) -> dict[str, list[str]]:
        """POST /internal/v1/watchlists/by-entities → {entity_id: [user_ids]}"""
        try:
            response = await self._client.post(
                "/internal/v1/watchlists/by-entities",
                json={"entity_ids": entity_ids}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning("s1_batch_watchlist_error", error=str(e))
            return {}

    async def health_check(self) -> bool:
        """GET /internal/v1/health → True if S1 is healthy."""
        try:
            response = await self._client.get("/internal/v1/health", timeout=2.0)
            return response.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.aclose()
```

```python
# services/alert/src/alert_service/infrastructure/valkey/watchlist_cache.py
import json
import structlog
from alert_service.config import settings

logger = structlog.get_logger(__name__)

class WatchlistCache:
    CACHE_KEY_PREFIX = "s10:v1:watchlist:by_entity:"

    def __init__(self, valkey_client, s1_client) -> None:
        self.valkey = valkey_client
        self.s1_client = s1_client

    def _key(self, entity_id: str) -> str:
        return f"{self.CACHE_KEY_PREFIX}{entity_id}"

    async def get_users_for_entity(self, entity_id: str) -> list[str]:
        """Cache-aside: check Valkey first, fall back to S1."""
        key = self._key(entity_id)
        try:
            cached = await self.valkey.get(key)
            if cached is not None:
                return json.loads(cached)
        except Exception as e:
            logger.warning("valkey_cache_get_failed", entity_id=entity_id, error=str(e))

        # Cache miss — call S1
        user_ids = await self.s1_client.get_watchlist_by_entity(entity_id)

        # Populate cache (best-effort — don't fail if Valkey is down)
        try:
            await self.valkey.set(
                key,
                json.dumps(user_ids),
                ex=settings.WATCHLIST_CACHE_TTL_SECONDS,
            )
        except Exception as e:
            logger.warning("valkey_cache_set_failed", entity_id=entity_id, error=str(e))

        return user_ids

    async def invalidate(self, entity_id: str) -> None:
        """Delete cache key for entity. Called on watchlist.item_deleted event."""
        key = self._key(entity_id)
        try:
            await self.valkey.delete(key)
            logger.info("watchlist_cache_invalidated", entity_id=entity_id)
        except Exception as e:
            logger.warning("valkey_cache_invalidate_failed", entity_id=entity_id, error=str(e))
```

### T-S10-011: Deployment Gate + S1 Contract Testing

```markdown
# S10 Deployment Gate and S1 Contract Testing

## Required S1 Endpoints

S10 cannot function without S1 providing these 4 capabilities:

| Endpoint | Method | Response Shape | Auth |
|----------|--------|---------------|------|
| `/internal/v1/watchlists/by-entity/{entity_id}` | GET | `{"user_ids": ["uid1", "uid2"]}` | Bearer INTERNAL_SERVICE_TOKEN |
| `/internal/v1/watchlists/by-entities` | POST | `{"entity_id1": ["uid1"], "entity_id2": ["uid2"]}` | Bearer INTERNAL_SERVICE_TOKEN |
| `/internal/v1/health` | GET | `{"status": "ok"}` (HTTP 200) | None |
| Bearer token validation | - | 401 on invalid token | S1 enforces |

## Deployment Gate

S10's `/readyz` calls `GET S1_BASE_URL/internal/v1/health`.
If S1 returns non-200 or is unreachable: `/readyz` returns 503 with `{"failing": ["s1_health"]}`.
Kubernetes readiness probe uses `/readyz` → S10 pod will not receive traffic until S1 is available.

## Contract Testing Strategy

Use `pytest-httpserver` to run a mock S1 server in-process.
Tests import actual S1Client code and validate request/response shapes.

## Integration Test Stub Strategy

`docker-compose.test.yml` includes `mock-s1` service (minimal FastAPI).
`S1_BASE_URL=http://mock-s1:8000` in test environment.
```

```python
# services/alert/tests/contract/test_s1_contract.py
import pytest
from pytest_httpserver import HTTPServer
from alert_service.infrastructure.s1_client.client import S1Client
from alert_service.config import settings

@pytest.fixture
def mock_s1(httpserver: HTTPServer):
    return httpserver

@pytest.mark.asyncio
async def test_contract_get_watchlist_by_entity(mock_s1: HTTPServer):
    """S1 contract: GET /by-entity/{entity_id} returns {user_ids: [...]}"""
    mock_s1.expect_request(
        "/internal/v1/watchlists/by-entity/AAPL",
        headers={"Authorization": f"Bearer {settings.INTERNAL_SERVICE_TOKEN}"}
    ).respond_with_json({"user_ids": ["user-1", "user-2"]})

    client = S1Client.__new__(S1Client)
    import httpx
    client._client = httpx.AsyncClient(
        base_url=mock_s1.url_for(""),
        headers={"Authorization": f"Bearer {settings.INTERNAL_SERVICE_TOKEN}"},
    )

    result = await client.get_watchlist_by_entity("AAPL")
    assert result == ["user-1", "user-2"]
    await client.close()

@pytest.mark.asyncio
async def test_contract_post_watchlists_by_entities(mock_s1: HTTPServer):
    """S1 contract: POST /by-entities returns {entity_id: [user_ids]}"""
    mock_s1.expect_request(
        "/internal/v1/watchlists/by-entities",
        method="POST",
    ).respond_with_json({
        "AAPL": ["user-1"],
        "MSFT": ["user-2", "user-3"]
    })

    client = S1Client.__new__(S1Client)
    import httpx
    client._client = httpx.AsyncClient(base_url=mock_s1.url_for(""))

    result = await client.get_watchlists_by_entities(["AAPL", "MSFT"])
    assert result == {"AAPL": ["user-1"], "MSFT": ["user-2", "user-3"]}
    await client.close()

@pytest.mark.asyncio
async def test_contract_s1_down(mock_s1: HTTPServer):
    """S1 returns 503 → S1Client returns [] gracefully; does not raise."""
    mock_s1.expect_request("/internal/v1/watchlists/by-entity/AAPL").respond_with_data(
        "Service Unavailable", status=503
    )

    client = S1Client.__new__(S1Client)
    import httpx
    client._client = httpx.AsyncClient(base_url=mock_s1.url_for(""))

    result = await client.get_watchlist_by_entity("AAPL")
    assert result == []  # Best-effort — never raises
    await client.close()
```

---

## Constraints

- S10 alert_db: Alembic IS enabled (unlike S6/S7 with intelligence_db) — `run_migrations()` called at startup
- T-S10-003: S1 errors MUST return `[]` — never raise; log warning only
- T-S10-003: cache miss → S1 call → populate Valkey with TTL=300s; Valkey failure is best-effort
- T-S10-011: 4 required S1 endpoints must be documented (not just 2 client methods) — include health and bearer token
- Contract tests: use pytest-httpserver (not MagicMock); test actual S1Client code
- Domain layer: AlertType enum must have exactly 3 values matching 3 intelligence topics
- structlog only; UTC datetimes only
- **`common.ids.new_uuid7()` mandatory** — all alert, pending-alert, and outbox primary keys must use `common.ids.new_uuid7()`. Never call `common.ids.new_uuid7()` directly in service code.
- **`common.time.utc_now()` mandatory** — all timestamp generation uses `common.time.utc_now()`. Never call `datetime.now(UTC)` or `datetime.utcnow()` directly in service code.
- **`common.types` for cross-service IDs** — use `EntityId` (from `common.types`) for watchlist entity_id keys; use `DocumentId` for any document references.
- **`EntityId` for fan-out**: S10 watchlist lookups use `common.types.EntityId` for entity_id keys.

---

## Scope & token budget

**Write paths:**
```
services/alert/src/alert_service/__init__.py
services/alert/src/alert_service/config.py
services/alert/src/alert_service/domain/__init__.py
services/alert/src/alert_service/domain/enums.py
services/alert/src/alert_service/domain/models.py
services/alert/src/alert_service/infrastructure/__init__.py
services/alert/src/alert_service/infrastructure/alert_db/__init__.py
services/alert/src/alert_service/infrastructure/alert_db/session.py
services/alert/src/alert_service/infrastructure/alert_db/repositories/alert_repository.py
services/alert/src/alert_service/infrastructure/alert_db/repositories/pending_alert_repository.py
services/alert/src/alert_service/infrastructure/alert_db/repositories/alert_dedup_repository.py
services/alert/src/alert_service/infrastructure/alert_db/repositories/idempotency_repository.py
services/alert/src/alert_service/infrastructure/alert_db/repositories/outbox_repository.py
services/alert/src/alert_service/infrastructure/s1_client/__init__.py
services/alert/src/alert_service/infrastructure/s1_client/client.py
services/alert/src/alert_service/infrastructure/valkey/__init__.py
services/alert/src/alert_service/infrastructure/valkey/watchlist_cache.py
services/alert/alembic/env.py
services/alert/alembic/versions/0001_initial_schema.py
services/alert/alembic.ini
services/alert/pyproject.toml
services/alert/Makefile
services/alert/docs/s1-contract-testing.md
services/alert/tests/unit/domain/test_models.py
services/alert/tests/unit/infrastructure/test_alert_db.py
services/alert/tests/unit/infrastructure/test_s1_client.py
services/alert/tests/unit/infrastructure/test_watchlist_cache.py
services/alert/tests/contract/test_s1_contract.py
```

**Stop condition:** All 4 tasks implemented; unit + contract tests pass; ruff+mypy pass.

---

## Required tests

```bash
cd services/alert && pytest tests/unit/ tests/contract/ -v
ruff check services/alert/src/
mypy services/alert/src/
```

**Pass criteria:**
- AlertType enum has exactly 3 values
- Alembic migration creates all 4 tables (alerts, pending_alerts, alert_dedup, outbox_events)
- S1Client.get_watchlist_by_entity returns [] on 503 (not exception)
- WatchlistCache cache hit skips S1 call
- 3 contract tests pass with pytest-httpserver mock S1

---

## Incremental quality gates (mandatory)

1. **T-S10-001:**
   ```bash
   pytest tests/unit/domain/ -v
   ruff check src/alert_service/domain/ src/alert_service/config.py
   mypy src/alert_service/domain/ src/alert_service/config.py
   ```

2. **T-S10-002:**
   ```bash
   pytest tests/unit/infrastructure/test_alert_db.py -v
   ruff check src/alert_service/infrastructure/alert_db/
   mypy src/alert_service/infrastructure/alert_db/
   ```

3. **T-S10-003:**
   ```bash
   pytest tests/unit/infrastructure/test_s1_client.py tests/unit/infrastructure/test_watchlist_cache.py -v
   ruff check src/alert_service/infrastructure/s1_client/ src/alert_service/infrastructure/valkey/
   mypy src/alert_service/infrastructure/s1_client/ src/alert_service/infrastructure/valkey/
   ```

4. **T-S10-011:**
   ```bash
   pytest tests/contract/ -v
   ```

---

## Documentation requirements

| File | Update | Action |
|------|--------|--------|
| `docs/services/alert-service.md` | Service overview | Add service description, dependencies (S1, S7, alert_db, Valkey, Kafka) |
| `docs/services/alert-service.md` | Domain models | Add AlertType enum table, domain model fields |
| `docs/services/alert-service.md` | S1 dependency | Add S1 deployment gate description, 4 required endpoints table |
| `services/alert/docs/s1-contract-testing.md` | New file | Full contract testing documentation |

---

## Required handoff evidence

### Validation ledger

| Command | Scope | Exit code | Result |
|---------|-------|-----------|--------|
| `pytest tests/unit/domain/ -v` | T-S10-001 | 0 | Pass |
| `pytest tests/contract/test_s1_contract.py -v` | T-S10-011 | 0 | 3 contract tests pass |
| `pytest tests/unit/infrastructure/test_s1_client.py::test_s1_client_error_returns_empty_list` | T-S10-003 | 0 | Pass |
| `pytest tests/unit/ tests/contract/ -v` | Full wave 11 | 0 | All pass |
| `ruff check src/` | Full S10 so far | 0 | No violations |
| `mypy src/` | Full S10 so far | 0 | No errors |

### Commit message
```
feat(s10): add service foundation, alert_db repos, S1 client+cache, contract tests

Create alert_service structure with pyproject.toml+Makefile, config, AlertType
enum (3 values), domain models, alert_db AsyncSession with Alembic (S10 owns
DDL), 5 repositories, httpx S1Client (errors return [] not raise), Valkey
watchlist cache (TTL=300s, invalidate on delete), and 3 pytest-httpserver
contract tests for S1 endpoint shapes.
```

---

## Definition of done

- [ ] AlertType enum has exactly 3 values (SIGNAL_DETECTED, GRAPH_CHANGED, CONTRADICTION_DETECTED)
- [ ] alert_db Alembic creates 4 tables (alerts, pending_alerts, alert_dedup, outbox_events)
- [ ] S1Client: errors return [] not exception; log warning only
- [ ] WatchlistCache: cache hit skips S1; cache miss populates Valkey with TTL=300s
- [ ] WatchlistCache: invalidate() deletes Valkey key
- [ ] 4 required S1 endpoints documented in `services/alert/docs/s1-contract-testing.md`
- [ ] 3 contract tests pass using pytest-httpserver
- [ ] Unit + contract tests pass
- [ ] ruff exits 0; mypy exits 0
- [ ] `docs/services/alert-service.md` updated with overview, domain models, S1 dependency

---

## Backfill suppression requirement (added 2026-03-23)

**Mandatory — implement in Wave 12 (alert consumer).**  Documented here so the domain and
infrastructure established in this wave are built backfill-aware.

When S10 processes `nlp.signal.detected.v1` or `graph.state.changed.v1` events, it **must**
check the `is_backfill` field on the decoded event payload before doing any watchlist resolution
or fan-out:

```python
async def process_signal(self, event: dict) -> None:
    # Backfill suppression — MANDATORY
    # Backfilling 3 years of news would fire tens of thousands of alerts on startup.
    if event.get("is_backfill", False):
        logger.debug("alert_suppressed_backfill", event_id=event.get("event_id"))
        return  # acknowledge offset, skip fan-out entirely

    # ... normal watchlist resolution and fan-out logic ...
```

**`intelligence.contradiction.v1` is never suppressed** — contradiction events carry no
`is_backfill` field and must always trigger alerts.

**Domain implication:** The `Alert` domain model does NOT need an `is_backfill` field —
backfill events are dropped before any `Alert` is created.  No database change is needed.

**Test to add in Wave 12:**
- `test_backfill_signal_suppressed` — construct event with `is_backfill=True`; assert alert NOT
  created; assert watchlist NOT queried; assert offset committed.
- `test_non_backfill_signal_processed` — construct event with `is_backfill=False`; assert
  watchlist queried and alert created normally.
