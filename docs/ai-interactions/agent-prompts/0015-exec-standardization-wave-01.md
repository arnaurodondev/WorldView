# Execution Prompt 0015 — Cross-Service Standardization Wave 01

**Wave:** 01 of N — Foundation Standardization Pass
**Services:** S4 content-ingestion · S3 market-data · S2 market-ingestion · alert · api-gateway
**Focus:** Eliminate every anti-pattern documented in `docs/STANDARDS.md` from all existing services
**Date:** 2026-03-23

---

## Context (read first)

This wave introduces `docs/STANDARDS.md` as the single authoritative engineering reference for the
entire Worldview platform. Every task below corrects a divergence discovered during a cross-service
audit conducted 2026-03-23. No new features are added in this wave — it is a pure correctness pass
that brings all existing services to full compliance before new pipeline work (S5, S6, S7, S10)
is written from scratch.

After this wave every existing service must pass the compliance checklist in `docs/STANDARDS.md`
Appendix and every future wave prompt must include `docs/STANDARDS.md` as a mandatory pre-read.

---

## Assigned agent profiles

- `.claude/agents/backend-engineer.md` — T-STD-001 through T-STD-005
- `.claude/agents/platform-engineer.md` — T-STD-006 through T-STD-007

Tasks within each group that are independent of each other can be executed concurrently.

---

## Mandatory pre-read (in this exact order)

1. `AGENTS.md`
2. `CLAUDE.md`
3. `RULES.md`
4. **`docs/STANDARDS.md`** ← primary reference for ALL work in this wave
5. `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md` — canonical PRD (service overview)
6. `services/content-ingestion/src/content_ingestion/config.py`
7. `services/content-ingestion/src/content_ingestion/app.py`
8. `services/content-ingestion/src/content_ingestion/infrastructure/outbox/dispatcher.py`
9. `services/content-ingestion/src/content_ingestion/infrastructure/outbox/avro_schema.py`
10. `services/content-ingestion/src/content_ingestion/infrastructure/db/models.py`
11. `services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/outbox.py`
12. `services/content-ingestion/src/content_ingestion/infrastructure/storage/minio_bronze.py`
13. `services/content-ingestion/pyproject.toml`
14. `services/market-data/src/market_data/infrastructure/db/models/infrastructure.py`
15. `services/market-data/src/market_data/infrastructure/db/repositories/outbox_event_repo.py`
16. `services/market-ingestion/src/market_ingestion/app.py`
17. `services/market-ingestion/src/market_ingestion/worker/main.py`
18. `services/alert/src/alert/config.py`
19. `services/api-gateway/src/api_gateway/app.py`
20. `services/api-gateway/src/api_gateway/config.py`
21. `docs/libs/common.md` — UUIDv7 and time utilities
22. `docs/libs/messaging.md` — dispatcher, Kafka, Valkey
23. `docs/libs/storage.md` — object storage factory

---

## Objective

Bring all existing services to full compliance with `docs/STANDARDS.md`. This wave has **zero**
tolerance for partially-fixed services — each task's Definition of Done requires a clean
`make test && ruff check && mypy` run. No task is "done" until quality gates pass.

The exact set of violations addressed:

| Task | Service | Violations addressed |
|------|---------|---------------------|
| T-STD-001 | content-ingestion (S4) | Kafka client, Avro, dispatcher, DLQ, outbox layout, status values |
| T-STD-002 | content-ingestion (S4) | Settings SCREAMING_SNAKE_CASE → snake_case |
| T-STD-003 | content-ingestion (S4) | storage lib, observability lib, app.py lifespan wiring |
| T-STD-004 | market-data (S3) | Outbox status SCREAMING_SNAKE_CASE → lowercase canonical values |
| T-STD-005 | market-ingestion (S2) | `uuid.uuid4()` → `common.ids` |
| T-STD-006 | alert | Module-level Settings instantiation; missing observability fields |
| T-STD-007 | api-gateway | `redis.asyncio` → `messaging.valkey.ValkeyClient`; observability wiring |

---

## Task scope for this wave

### Parallel group 1 (T-STD-001 and T-STD-004 and T-STD-005 are independent)

- **T-STD-001** — S4 messaging overhaul (aiokafka + fastavro + custom dispatcher → canonical stack)
- **T-STD-004** — S3 outbox status value migration
- **T-STD-005** — S2 UUID call sites

### Sequential within S4: T-STD-002 and T-STD-003 follow T-STD-001

T-STD-002 (settings rename) and T-STD-003 (storage + observability) may only start after T-STD-001
is merged, because the settings field names are referenced in the dispatcher rewrite.

### Parallel group 2 (T-STD-006 and T-STD-007 are independent of all S4 tasks)

- **T-STD-006** — alert config fix
- **T-STD-007** — api-gateway Valkey + observability

---

## Why this chunk

All seven tasks correct existing violations before new pipeline services (S5, S6, S7, S10) inherit
the same patterns. If these violations are left in place:

- S4 uses a different Kafka serialization path than every other service, so S5's consumer can
  never be tested against a real S4 payload during integration tests.
- S3's SCREAMING status values silently corrupt any shared monitoring query written for the
  canonical schema.
- The alert service module-level `Settings()` prevents pytest from injecting environment overrides,
  which will block all future S10 integration tests.
- api-gateway's bare `redis.asyncio` client bypasses connection pooling and health-check machinery
  that all other services receive from `messaging.valkey.ValkeyClient`.

---

## Implementation instructions

---

### T-STD-001 — S4: Messaging overhaul

**Scope**: `services/content-ingestion/`

This task has five sub-steps. Complete them in order — each step is small but depends on the
previous one.

#### Step 1 — Remove forbidden dependencies from `pyproject.toml`

In `services/content-ingestion/pyproject.toml`, make the following changes:

**Remove:**
```
"aiokafka>=0.10",
"fastavro>=1.9",
"minio>=7.2",
"structlog>=24.1",
```

**Add:**
```
"messaging",
"storage",
"observability",
```

The full `dependencies` list must become:
```toml
dependencies = [
    "common",
    "messaging",
    "storage",
    "observability",
    "fastapi==0.111",
    "uvicorn[standard]==0.29",
    "pydantic==2.5",
    "pydantic-settings==2.1",
    "sqlalchemy[asyncio]==2.0",
    "asyncpg==0.29",
    "alembic==1.13",
    "httpx==0.27",
]
```

#### Step 2 — Convert Avro schema dict → `.avsc` file

Delete:
```
services/content-ingestion/src/content_ingestion/infrastructure/outbox/avro_schema.py
```

Create:
```
services/content-ingestion/src/content_ingestion/infrastructure/messaging/schemas/content.article.raw.v1.avsc
```

Content (exact JSON — do not alter field names or add comments):
```json
{
  "type": "record",
  "name": "ContentArticleRawV1",
  "namespace": "com.worldview",
  "doc": "Raw article fetched by S4 content-ingestion and stored in MinIO bronze.",
  "fields": [
    {"name": "article_id",    "type": "string",            "doc": "UUIDv7 document identifier"},
    {"name": "source_type",   "type": "string",            "doc": "eodhd | sec_edgar | finnhub | newsapi"},
    {"name": "url",           "type": "string"},
    {"name": "url_hash",      "type": "string",            "doc": "SHA-256 hex of the canonical URL"},
    {"name": "minio_key",     "type": "string",            "doc": "bronze/ MinIO object key"},
    {"name": "fetched_at",    "type": "string",            "doc": "ISO-8601 UTC timestamp"},
    {"name": "byte_size",     "type": "int"},
    {"name": "schema_version","type": "int",  "default": 1},
    {"name": "published_at",  "type": ["null", "string"],  "default": null,  "doc": "Source-reported publication date (ISO-8601 UTC); null if not available"},
    {"name": "is_backfill",   "type": "boolean",           "default": false, "doc": "True when this event was produced during a historical backfill run"}
  ]
}
```

Create the required `__init__.py` files so the new directory is a proper package:
```
services/content-ingestion/src/content_ingestion/infrastructure/messaging/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/messaging/schemas/  (directory only, no __init__.py needed)
services/content-ingestion/src/content_ingestion/infrastructure/messaging/outbox/__init__.py
```

#### Step 3 — Rewrite dispatcher to extend `BaseOutboxDispatcher`

Replace the entire content of:
```
services/content-ingestion/src/content_ingestion/infrastructure/outbox/dispatcher.py
```

with this canonical implementation at the new path:
```
services/content-ingestion/src/content_ingestion/infrastructure/messaging/outbox/dispatcher.py
```

```python
"""Content-ingestion outbox dispatcher — extends BaseOutboxDispatcher."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from messaging.kafka.dispatcher.base import BaseOutboxDispatcher, DispatcherConfig
from messaging.kafka.producer import KafkaProducerConfig, build_serializing_producer
from messaging.kafka.serializer import AvroSerializerConfig, build_avro_serializer
from observability.logging import get_logger

from content_ingestion.infrastructure.db.session import create_session_factory
from content_ingestion.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

if TYPE_CHECKING:
    from content_ingestion.config import Settings

_SCHEMA_DIR = Path(__file__).parent.parent / "schemas"
logger = get_logger(__name__)


class ContentIngestionOutboxDispatcher(BaseOutboxDispatcher):
    """Transactional outbox dispatcher for the content-ingestion service."""

    def __init__(self, settings: Settings) -> None:
        config = DispatcherConfig(
            poll_interval_seconds=settings.outbox_poll_interval_seconds,
            lease_seconds=settings.outbox_lease_seconds,
            batch_size=settings.outbox_batch_size,
            max_attempts=settings.outbox_max_attempts,
        )
        super().__init__(config)
        self._settings = settings
        self._session_factory = create_session_factory(settings)
        self._producer: Any = None
        self._serializers: dict[str, Any] = {}

    # ── required by BaseOutboxDispatcher ──────────────────────────────────

    def get_unit_of_work(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self._session_factory)

    def get_producer(self) -> Any:
        if self._producer is None:
            self._producer = build_serializing_producer(
                KafkaProducerConfig(
                    bootstrap_servers=self._settings.kafka_bootstrap_servers,
                    schema_registry_url=self._settings.kafka_schema_registry_url,
                    schema_registry_basic_auth=self._settings.kafka_schema_registry_basic_auth,
                )
            )
        return self._producer

    def get_serializer(self, event_type: str) -> Any:
        if event_type not in self._serializers:
            schema_path = _SCHEMA_DIR / "content.article.raw.v1.avsc"
            schema = json.loads(schema_path.read_text())
            self._serializers[event_type] = build_avro_serializer(
                AvroSerializerConfig(
                    schema=schema,
                    schema_registry_url=self._settings.kafka_schema_registry_url,
                    subject_name_strategy="TopicNameStrategy",
                )
            )
        return self._serializers[event_type]
```

Delete the old file:
```
services/content-ingestion/src/content_ingestion/infrastructure/outbox/dispatcher.py
services/content-ingestion/src/content_ingestion/infrastructure/outbox/avro_schema.py
services/content-ingestion/src/content_ingestion/infrastructure/outbox/__init__.py
```

If `infrastructure/outbox/` is now empty, delete the directory.

#### Step 4 — Migrate outbox DB model and repository to canonical schema

**4a. `OutboxEventModel`** in `infrastructure/db/models.py`:

The current model is missing the `lease_owner`, `lease_expires`, `attempt_count`, and `max_attempts`
columns and uses a non-canonical index. Replace it with the canonical schema (STANDARDS.md §3.4).
Also delete `DLQEventModel` entirely — there is no `dlq_events` table in the canonical schema.

Remove `DLQEventModel` class and its `dlq_events` table declaration in full.

Modify `OutboxEventModel` to:

```python
class OutboxEventModel(Base):
    """Transactional outbox event pending Kafka dispatch (canonical schema)."""

    __tablename__ = "outbox_events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False, default="content.article.raw.v1")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    lease_owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "ix_outbox_claimable",
            "status",
            "lease_expires",
            postgresql_where=text("status IN ('pending', 'processing')"),
        ),
    )
```

Add the missing `text` import from `sqlalchemy`.

**4b. `OutboxRepository`** in `infrastructure/db/repositories/outbox.py`:

Replace the entire file. The new implementation must implement `OutboxRepositoryProtocol`
from `messaging.kafka.dispatcher.base` with `FOR UPDATE SKIP LOCKED` claiming:

```python
"""Outbox repository — implements OutboxRepositoryProtocol with lease-based claiming."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select, text, update

import common.ids
import common.time
from content_ingestion.infrastructure.db.models import OutboxEventModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def fetch_pending(
        self, worker_id: str, lease_seconds: int, batch_size: int
    ) -> list[OutboxEventModel]:
        """Atomically claim up to *batch_size* pending records using FOR UPDATE SKIP LOCKED."""
        expires_at = common.time.utc_now() + __import__("datetime").timedelta(seconds=lease_seconds)
        result = await self._session.execute(
            select(OutboxEventModel)
            .where(
                OutboxEventModel.status.in_(["pending", "processing"]),
                (OutboxEventModel.lease_expires.is_(None))
                | (OutboxEventModel.lease_expires <= common.time.utc_now()),
            )
            .order_by(OutboxEventModel.created_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        records = list(result.scalars().all())
        for record in records:
            record.status = "processing"
            record.lease_owner = worker_id
            record.lease_expires = expires_at
        await self._session.flush()
        return records

    async def mark_published(self, record_id: UUID) -> None:
        await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.id == record_id)
            .values(
                status="delivered",
                dispatched_at=common.time.utc_now(),
                lease_owner=None,
                lease_expires=None,
            )
        )

    async def increment_attempts(self, record_id: UUID) -> None:
        await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.id == record_id)
            .values(
                attempt_count=OutboxEventModel.attempt_count + 1,
                status="pending",
                lease_owner=None,
                lease_expires=None,
            )
        )

    async def move_to_dead_letter(self, record_id: UUID) -> None:
        await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.id == record_id)
            .values(status="dead_letter", lease_owner=None, lease_expires=None)
        )

    async def append(
        self,
        aggregate_type: str,
        aggregate_id: UUID,
        event_type: str,
        topic: str,
        payload: dict,
    ) -> None:
        self._session.add(
            OutboxEventModel(
                id=common.ids.new_uuid7(),
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                event_type=event_type,
                topic=topic,
                payload=payload,
            )
        )
```

#### Step 5 — Create Alembic migration for schema changes

Create `services/content-ingestion/alembic/versions/0003_outbox_canonical_schema.py`:

```python
"""Migrate outbox_events to canonical schema; drop dlq_events table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop non-canonical DLQ table
    op.drop_table("dlq_events")

    # Add canonical lease + attempt columns to outbox_events
    op.add_column("outbox_events", sa.Column("topic", sa.Text(), nullable=False,
                  server_default="content.article.raw.v1"))
    op.add_column("outbox_events", sa.Column("lease_owner", sa.Text(), nullable=True))
    op.add_column("outbox_events", sa.Column("lease_expires", sa.DateTime(timezone=True), nullable=True))
    op.add_column("outbox_events", sa.Column("attempt_count", sa.SmallInteger(), nullable=False,
                  server_default="0"))
    op.add_column("outbox_events", sa.Column("max_attempts", sa.SmallInteger(), nullable=False,
                  server_default="5"))

    # Rename non-canonical columns / remove deprecated ones
    # retry_count → drop (replaced by attempt_count)
    op.drop_column("outbox_events", "retry_count")
    # error → drop (no error column in canonical schema)
    op.drop_column("outbox_events", "error")

    # Migrate non-canonical status values to canonical ones
    op.execute("UPDATE outbox_events SET status = 'delivered' WHERE status = 'dispatched'")
    op.execute("UPDATE outbox_events SET status = 'dead_letter' WHERE status = 'failed'")

    # Drop old non-canonical index
    op.drop_index("ix_outbox_events_status_created_at", table_name="outbox_events")

    # Add canonical claimable index
    op.execute(
        """
        CREATE INDEX ix_outbox_claimable ON outbox_events (status, lease_expires)
        WHERE status IN ('pending', 'processing')
        """
    )


def downgrade() -> None:
    # Not supported — destructive migration
    raise NotImplementedError("Downgrade not supported for outbox canonical migration")
```

#### Quality gate — T-STD-001

```bash
cd services/content-ingestion
make test         # all unit tests pass, no skips
ruff check src/   # zero violations
ruff format --check src/
mypy src/         # zero errors
```

Verify manually:
- `grep -r "aiokafka\|fastavro\|from minio\b\|import minio\b\|import structlog\b" src/` → **zero results**
- `grep -r "dlq_events\|DLQEvent\|ARTICLE_RAW_V1_SCHEMA" src/` → **zero results**
- `grep -r "status.*=.*['\"]dispatched\|status.*=.*['\"]failed" src/` → **zero results**
- `.avsc` file exists at `src/content_ingestion/infrastructure/messaging/schemas/content.article.raw.v1.avsc`

---

### T-STD-002 — S4: Settings snake_case migration

**Scope**: `services/content-ingestion/src/content_ingestion/config.py`

This is a pure rename — no logic changes. Every `SCREAMING_SNAKE_CASE` field name becomes
`snake_case`. The `env_prefix` is set so that environment variables remain unchanged.

Replace the entire `config.py` with:

```python
"""Service configuration via environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the Content Ingestion service (S4).

    All env vars are prefixed with CONTENT_INGESTION_ (set by env_prefix).
    Example: field `db_url` is read from env var `CONTENT_INGESTION_DB_URL`.

    Exception: source API keys use their own conventional names without the prefix
    because they are shared across services and set once in the environment.
    """

    model_config = SettingsConfigDict(
        env_prefix="CONTENT_INGESTION_",
        env_file=".env",
        extra="ignore",
    )

    # ── External API keys (no prefix — shared across services) ────────────
    # These fields override the env_prefix via `validation_alias`.
    eodhd_api_key: str = ""
    sec_edgar_user_agent: str = "worldview/1.0 contact@worldview.example"
    finnhub_api_key: str = ""
    newsapi_key: str = ""

    # ── Database ──────────────────────────────────────────────────────────
    db_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/content_ingestion_db"

    # ── Kafka ─────────────────────────────────────────────────────────────
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_schema_registry_url: str = "http://localhost:8081"
    kafka_schema_registry_basic_auth: str = ""
    kafka_outbox_topic: str = "content.article.raw.v1"

    # ── MinIO (object storage) ────────────────────────────────────────────
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "worldview-bronze"
    minio_secure: bool = False

    # ── Security ──────────────────────────────────────────────────────────
    admin_token: str = ""

    # ── Scheduler / outbox ────────────────────────────────────────────────
    scheduler_interval_seconds: int = 300
    outbox_batch_size: int = 100
    outbox_poll_interval_seconds: float = 5.0
    outbox_lease_seconds: int = 30
    outbox_max_attempts: int = 5
    outbox_metrics_poll_seconds: int = 30

    # ── Rate limiting ─────────────────────────────────────────────────────
    newsapi_daily_limit: int = 100

    # ── Valkey ────────────────────────────────────────────────────────────
    valkey_url: str = "redis://localhost:6379"

    # ── Backfill ─────────────────────────────────────────────────────────
    backfill_enabled: bool = False
    backfill_from_date: str = ""
    backfill_to_date: str = ""
    backfill_sources: str = ""
    backfill_batch_delay_seconds: float = 0.5

    # ── Observability ─────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""
```

After replacing `config.py`, update all call sites in `src/content_ingestion/` that reference the
old SCREAMING_SNAKE_CASE field names (e.g. `settings.KAFKA_OUTBOX_TOPIC` →
`settings.kafka_outbox_topic`). Run `grep -rn "settings\.[A-Z]" src/` to find all occurrences.

#### Quality gate — T-STD-002

```bash
cd services/content-ingestion
ruff check src/
mypy src/
# Verify no old field names remain:
grep -rn "settings\.[A-Z]" src/    # must return zero results
grep -rn "CONTENT_INGESTION_DB_URL\|KAFKA_BOOTSTRAP\|MINIO_ENDPOINT" src/  # zero in Python files
```

---

### T-STD-003 — S4: Storage lib, observability wiring, app.py lifespan

**Scope**: `services/content-ingestion/src/content_ingestion/`

This task has three sub-steps.

#### Step 1 — Replace `MinioBronzeAdapter` with `storage.factory.build_object_storage()`

Delete:
```
services/content-ingestion/src/content_ingestion/infrastructure/storage/minio_bronze.py
```

All call sites of `MinioBronzeAdapter` must be replaced with the canonical storage client:

```python
# Before (anti-pattern)
from content_ingestion.infrastructure.storage.minio_bronze import MinioBronzeAdapter
adapter = MinioBronzeAdapter(client=minio_client, settings=settings)
await adapter.put_object(key, data)

# After (canonical)
from storage.factory import build_object_storage
from storage.interface import ObjectStorage

storage: ObjectStorage = build_object_storage(
    endpoint=settings.minio_endpoint,
    access_key=settings.minio_access_key,
    secret_key=settings.minio_secret_key,
    bucket=settings.minio_bucket,
    secure=settings.minio_secure,
)
key = await storage.put_object(key=key, data=data, content_type="application/json")
```

If `infrastructure/storage/` directory is now empty, delete it.

#### Step 2 — Replace direct `structlog` imports with `observability.logging`

Find every file in `src/content_ingestion/` that uses `import structlog` or
`structlog.get_logger()` directly and replace with the canonical form:

```python
# Before (anti-pattern)
import structlog
logger = structlog.get_logger(__name__)

# After (canonical)
from observability.logging import get_logger
logger = get_logger(__name__)
```

Run `grep -rn "import structlog" src/` to locate all instances. Zero instances must remain.

#### Step 3 — Wire observability into `app.py` lifespan

Replace the stub `app.py` with a fully-wired lifespan following the canonical pattern from
STANDARDS.md §7.1. The lifespan must:

1. Instantiate `Settings()` first
2. Call `configure_logging(service_name="content-ingestion", ...)` before anything else
3. Call `create_metrics()` and `add_prometheus_middleware()`
4. Wire the session factory, Valkey client, and object storage into `app.state`
5. Start `ContentIngestionOutboxDispatcher` as a background asyncio task
6. Expose `/healthz` (liveness only) and `/readyz` (checks DB + Valkey) via
   `api/routes/health.py` — not inline in `app.py`
7. Register `RequestIdMiddleware`

```python
"""FastAPI application factory — content-ingestion service."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from observability.logging import configure_logging, get_logger
from observability.metrics import add_prometheus_middleware, create_metrics
from observability.tracing import add_otel_middleware, configure_tracing
from messaging.valkey import create_valkey_client_from_url
from storage.factory import build_object_storage

from content_ingestion.api.routes import health
from content_ingestion.config import Settings
from content_ingestion.infrastructure.db.session import create_session_factory
from content_ingestion.infrastructure.messaging.outbox.dispatcher import (
    ContentIngestionOutboxDispatcher,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    app.state.settings = settings

    # 1. Logging — always first
    configure_logging(
        service_name="content-ingestion",
        level=settings.log_level,
        json=settings.log_json,
    )
    logger = get_logger("content_ingestion.app")

    # 2. Metrics
    metrics = create_metrics(service_name="content-ingestion")
    add_prometheus_middleware(app, metrics)
    app.state.metrics = metrics

    # 3. Tracing (optional)
    if settings.otlp_endpoint:
        configure_tracing(service_name="content-ingestion", otlp_endpoint=settings.otlp_endpoint)
        add_otel_middleware(app)

    # 4. Database
    session_factory = create_session_factory(settings)
    app.state.session_factory = session_factory

    # 5. Valkey
    valkey = create_valkey_client_from_url(settings.valkey_url)
    app.state.valkey = valkey

    # 6. Object storage
    storage = build_object_storage(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket=settings.minio_bucket,
        secure=settings.minio_secure,
    )
    app.state.storage = storage

    # 7. Outbox dispatcher
    dispatcher = ContentIngestionOutboxDispatcher(settings=settings)
    dispatch_task = asyncio.create_task(dispatcher.run())
    app.state.dispatcher = dispatcher

    logger.info("service_started", service="content-ingestion")
    yield

    dispatcher.stop()
    await dispatch_task
    await valkey.close()
    logger.info("service_stopped", service="content-ingestion")


def create_app() -> FastAPI:
    app = FastAPI(
        title="content-ingestion",
        version="2025.6.0",
        lifespan=lifespan,
    )
    from content_ingestion.app import RequestIdMiddleware  # avoid circular import
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router, tags=["health"])
    return app
```

Create `services/content-ingestion/src/content_ingestion/api/__init__.py` and
`services/content-ingestion/src/content_ingestion/api/routes/__init__.py` if they don't exist.

Create `services/content-ingestion/src/content_ingestion/api/routes/health.py`:

```python
"""Health and readiness endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


def get_db_session(request: Request) -> AsyncSession:
    return request.app.state.session_factory()


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> Response:
    checks: dict[str, str] = {}
    ok = True

    # Database
    try:
        async with request.app.state.session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
        ok = False

    # Valkey
    try:
        await request.app.state.valkey.ping()
        checks["valkey"] = "ok"
    except Exception as exc:
        checks["valkey"] = f"error: {exc}"
        ok = False

    status = 200 if ok else 503
    return Response(
        content=json.dumps({"status": "ok" if ok else "degraded", **checks}),
        status_code=status,
        media_type="application/json",
    )
```

Also create the `RequestIdMiddleware` class in `app.py` following STANDARDS.md §5.5.

#### Quality gate — T-STD-003

```bash
cd services/content-ingestion
make test
ruff check src/
mypy src/
grep -rn "import structlog\b" src/                     # zero results
grep -rn "from minio import\|import minio\b" src/      # zero results
grep -rn "MinioBronzeAdapter" src/                     # zero results
grep -rn "TODO.*healthz\|TODO.*readyz" src/            # zero results
```

---

### T-STD-004 — S3: Outbox status value migration

**Scope**: `services/market-data/`

The market-data service uses `SCREAMING_SNAKE_CASE` status strings (`PENDING`, `DISPATCHED`,
`DEAD_LETTER`) throughout the outbox implementation. These must be migrated to the canonical
lowercase values (`pending`, `delivered`, `dead_letter`) from STANDARDS.md §3.5.

#### Step 1 — Update all Python status string literals

Find every status string in `services/market-data/src/market_data/`:

```bash
grep -rn "'PENDING'\|\"PENDING\"\|'DISPATCHED'\|\"DISPATCHED\"\|'DEAD_LETTER'\|\"DEAD_LETTER\"\|'FAILED'\|\"FAILED\"\|'PROCESSING'\|\"PROCESSING\"" src/
```

Apply these exact replacements (case-sensitive, string literals only):

| Old value | New value |
|-----------|-----------|
| `"PENDING"` / `'PENDING'` | `"pending"` |
| `"PROCESSING"` / `'PROCESSING'` | `"processing"` |
| `"DISPATCHED"` / `'DISPATCHED'` | `"delivered"` |
| `"DEAD_LETTER"` / `'DEAD_LETTER'` | `"dead_letter"` |
| `"FAILED"` / `'FAILED'` | `"dead_letter"` |

**Important**: The docstrings that describe these values (e.g., `"""status=PENDING, next_attempt_at <= now"""`)
should also be updated to match the new lowercase values.

#### Step 2 — Update ORM model `server_default`

In `services/market-data/src/market_data/infrastructure/db/models/infrastructure.py`, change:

```python
# Before
status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="'PENDING'")

# After
status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
```

Apply to both `OutboxEventModel` and `FailedTaskModel` (or whichever models use a `status`
`server_default` of `'PENDING'`).

#### Step 3 — Create Alembic migration

Create `services/market-data/alembic/versions/XXXX_lowercase_outbox_status.py`
(use the next available revision number):

```python
"""Migrate outbox status values to canonical lowercase.

Revision ID: <next_revision>
Revises: <previous_revision>
Create Date: 2026-03-23
"""

from alembic import op


def upgrade() -> None:
    # outbox_events table
    op.execute("UPDATE outbox_events SET status = 'pending'     WHERE status = 'PENDING'")
    op.execute("UPDATE outbox_events SET status = 'processing'  WHERE status = 'PROCESSING'")
    op.execute("UPDATE outbox_events SET status = 'delivered'   WHERE status = 'DISPATCHED'")
    op.execute("UPDATE outbox_events SET status = 'dead_letter' WHERE status IN ('DEAD_LETTER', 'FAILED')")

    # Repeat for any other tables that use status column with SCREAMING values
    # (check failed_tasks, scheduler_tasks as applicable)


def downgrade() -> None:
    op.execute("UPDATE outbox_events SET status = 'PENDING'      WHERE status = 'pending'")
    op.execute("UPDATE outbox_events SET status = 'PROCESSING'   WHERE status = 'processing'")
    op.execute("UPDATE outbox_events SET status = 'DISPATCHED'   WHERE status = 'delivered'")
    op.execute("UPDATE outbox_events SET status = 'DEAD_LETTER'  WHERE status = 'dead_letter'")
```

#### Quality gate — T-STD-004

```bash
cd services/market-data
make test
ruff check src/
mypy src/
# Verify no SCREAMING status values remain:
grep -rn "'PENDING'\|'DISPATCHED'\|'DEAD_LETTER'\|'FAILED'\|'PROCESSING'" src/ # zero results
```

---

### T-STD-005 — S2: Replace `uuid.uuid4()` with `common.ids`

**Scope**: `services/market-ingestion/src/market_ingestion/app.py` and
`services/market-ingestion/src/market_ingestion/worker/main.py`

Two call sites use `uuid.uuid4()` for generating request IDs and worker IDs:

```
app.py:63      request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
worker/main.py:83  self._worker_id = worker_id or str(uuid.uuid4())
```

**app.py change** — The request ID is an idempotency/correlation key (not a DB primary key), so
`new_ulid()` is appropriate (lexicographic sort, URL-safe):

```python
# Before
import uuid
request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

# After
import common.ids
request_id = request.headers.get("X-Request-ID") or common.ids.new_ulid()
```

**worker/main.py change** — The worker ID is a lease token (lexicographic sort needed), so
`new_ulid()` is also appropriate:

```python
# Before
import uuid
self._worker_id = worker_id or str(uuid.uuid4())

# After
import common.ids
self._worker_id = worker_id or common.ids.new_ulid()
```

After the replacement, remove the bare `import uuid` statement if it is no longer used elsewhere
in those files. If `uuid.UUID` type annotation is still needed, keep only the `from uuid import UUID`
form (type-only import).

#### Quality gate — T-STD-005

```bash
cd services/market-ingestion
make test
ruff check src/
mypy src/
# Verify no bare uuid.uuid4() calls remain:
grep -rn "uuid\.uuid4()" src/  # zero results
```

---

### T-STD-006 — Alert: Remove module-level Settings instantiation

**Scope**: `services/alert/src/alert/config.py`

The current file ends with `settings = Settings()` at module level. This is explicitly forbidden
by STANDARDS.md §8.2 because it breaks pytest fixtures that need to inject environment variables.

**Remove the module-level instantiation**:

```python
# Delete this line at the bottom of config.py:
settings = Settings()
```

Also add the three mandatory observability fields that are currently missing from the `Settings`
class (STANDARDS.md §8.3):

```python
# Add to Settings class:
log_level: str = "INFO"
log_json: bool = True
otlp_endpoint: str = ""
```

After this change, every call site in the alert service that imports `settings` directly
(e.g. `from alert.config import settings`) must be updated to use dependency injection via
`request.app.state.settings` or receive `settings` as a constructor argument.

Find all such call sites:
```bash
grep -rn "from alert.config import settings\|from alert\.config import settings" \
  services/alert/src/
```

Update each call site to accept settings via constructor injection or FastAPI `Request.app.state`.

If `services/alert/src/alert/app.py` does not yet instantiate `Settings()` in its lifespan,
add:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    app.state.settings = settings
    configure_logging(service_name="alert", level=settings.log_level, json=settings.log_json)
    # ... rest of wiring
    yield
```

#### Quality gate — T-STD-006

```bash
cd services/alert
make test
ruff check src/
mypy src/
# Verify no module-level settings instantiation:
grep -n "^settings = Settings()" src/alert/config.py  # zero results
grep -rn "from alert.config import settings\b" src/   # zero results
```

---

### T-STD-007 — API Gateway: Valkey client + observability wiring

**Scope**: `services/api-gateway/src/api_gateway/app.py`

#### Step 1 — Replace `redis.asyncio` with `messaging.valkey.ValkeyClient`

The current lifespan uses `import redis.asyncio as aioredis` inside a try/except. Replace the
entire Valkey connection block with the canonical client:

```python
# Before (anti-pattern)
try:
    import redis.asyncio as aioredis
    valkey_client = aioredis.from_url(settings.valkey_url)
    await valkey_client.ping()
except Exception:
    valkey_client = None  # fail-open: rate limiting disabled

# After (canonical)
from messaging.valkey import create_valkey_client_from_url

valkey_client = create_valkey_client_from_url(settings.valkey_url)
try:
    await valkey_client.ping()
except Exception:
    # fail-open: rate limiting disabled if Valkey is unavailable
    valkey_client = None
```

Update the shutdown block accordingly:
```python
# Before
if valkey_client:
    await valkey_client.aclose()

# After
if valkey_client is not None:
    await valkey_client.close()   # ValkeyClient uses .close(), not .aclose()
```

#### Step 2 — Add observability wiring to lifespan

The api-gateway lifespan currently has no logging, metrics, or tracing setup. Add the canonical
wiring before the httpx client construction:

```python
from observability.logging import configure_logging, get_logger
from observability.metrics import add_prometheus_middleware, create_metrics
from observability.tracing import add_otel_middleware, configure_tracing

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    # 1. Logging first
    configure_logging(service_name="api-gateway", level=settings.log_level, json=settings.log_json)
    logger = get_logger("api_gateway.app")

    # 2. Metrics
    metrics = create_metrics(service_name="api-gateway")
    add_prometheus_middleware(app, metrics)

    # 3. Tracing
    if settings.otlp_endpoint:
        configure_tracing(service_name="api-gateway", otlp_endpoint=settings.otlp_endpoint)
        add_otel_middleware(app)

    # ... existing httpx client construction ...
    # ... canonical Valkey client (from Step 1) ...

    logger.info("service_started", service="api-gateway")
    yield

    # ... existing shutdown ...
    logger.info("service_stopped", service="api-gateway")
```

#### Step 3 — Add missing Settings fields

The api-gateway `Settings` class is missing the three mandatory observability fields. Add to
`services/api-gateway/src/api_gateway/config.py`:

```python
# Add to Settings class:
log_level: str = "INFO"
log_json: bool = True
otlp_endpoint: str = ""
```

Also add `SettingsConfigDict` import and set `env_file=".env"` (consistent with all other services):

```python
# Before
model_config = {
    "env_prefix": "API_GATEWAY_",
    "env_file": "configs/dev.local.env",
    "env_file_encoding": "utf-8",
}

# After
from pydantic_settings import BaseSettings, SettingsConfigDict
model_config = SettingsConfigDict(
    env_prefix="API_GATEWAY_",
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
)
```

#### Step 4 — Replace stub health/metrics endpoints with real ones

Remove the inline route definitions in `create_app()`:

```python
# Remove these stubs:
@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/readyz")
async def readyz() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/metrics")
async def metrics() -> dict[str, str]:
    return {"status": "stub"}
```

`/metrics` is already exposed automatically by `add_prometheus_middleware`. Create a proper health
router at `services/api-gateway/src/api_gateway/routes/health.py`:

```python
"""Health and readiness endpoints for the API Gateway."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request, Response

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> Response:
    checks: dict[str, str] = {}
    ok = True

    # Valkey check
    if request.app.state.valkey is not None:
        try:
            await request.app.state.valkey.ping()
            checks["valkey"] = "ok"
        except Exception as exc:
            checks["valkey"] = f"error: {exc}"
            ok = False
    else:
        checks["valkey"] = "degraded (fail-open)"

    # Downstream service reachability is not checked here (would be too slow for a readiness probe)

    status = 200 if ok else 503
    return Response(
        content=json.dumps({"status": "ok" if ok else "degraded", **checks}),
        status_code=status,
        media_type="application/json",
    )
```

Add `messaging` and `observability` to `services/api-gateway/pyproject.toml` dependencies.
Remove `redis` / `redis-py` if present (replaced by `messaging` lib which uses `valkey` package).

#### Quality gate — T-STD-007

```bash
cd services/api-gateway
make test
ruff check src/
mypy src/
# Verify:
grep -rn "import redis\.asyncio\|from redis\b\|import aioredis\b" src/   # zero results
grep -rn "\"status\": \"stub\"" src/                                       # zero results
```

---

## Future waves: mandatory pre-read requirement

Effective immediately, **every future execution wave prompt** (0016 onward) must include
`docs/STANDARDS.md` as item 4 in its Mandatory pre-read section, immediately after `RULES.md`.
This ensures every AI agent contributor reads the engineering standards before writing a single
line of code.

Template pre-read block for all future waves:

```markdown
## Mandatory pre-read (in this exact order)

1. `AGENTS.md`
2. `CLAUDE.md`
3. `RULES.md`
4. **`docs/STANDARDS.md`** ← engineering standards and anti-patterns reference
5. <wave-specific docs>
...
```

Stub services S5, S6, S7, and S10 currently contain only empty scaffolding. They do not require
remediation in this wave. However, their implementation waves (0012 onward) already include
`docs/STANDARDS.md` in the pre-read block and must be verified to comply on day 1.

---

## Definition of Done

This wave is **complete** when all of the following are true simultaneously:

- [ ] `services/content-ingestion`: zero `aiokafka`, `fastavro`, `minio`, direct `structlog` imports
- [ ] `services/content-ingestion`: `.avsc` file exists; no Python dict Avro schema
- [ ] `services/content-ingestion`: `OutboxDispatcher` extends `BaseOutboxDispatcher`; no `dlq_events` table
- [ ] `services/content-ingestion`: `Settings` uses `snake_case` fields + `env_prefix="CONTENT_INGESTION_"`
- [ ] `services/content-ingestion`: `app.py` lifespan wires logging → metrics → db → valkey → storage → dispatcher
- [ ] `services/content-ingestion`: `make test && ruff check && mypy` green
- [ ] `services/market-data`: all outbox status literals are lowercase canonical values
- [ ] `services/market-data`: Alembic migration for status value normalization created
- [ ] `services/market-data`: `make test && ruff check && mypy` green
- [ ] `services/market-ingestion`: zero `uuid.uuid4()` calls; uses `common.ids.new_ulid()` in both files
- [ ] `services/market-ingestion`: `make test && ruff check && mypy` green
- [ ] `services/alert`: no module-level `settings = Settings()` in `config.py`
- [ ] `services/alert`: `Settings` includes `log_level`, `log_json`, `otlp_endpoint`
- [ ] `services/alert`: `make test && ruff check && mypy` green
- [ ] `services/api-gateway`: uses `messaging.valkey.ValkeyClient`; no `redis.asyncio` import
- [ ] `services/api-gateway`: lifespan wires `configure_logging` + `create_metrics`
- [ ] `services/api-gateway`: real `/readyz` endpoint with Valkey check; no stub `/metrics` endpoint
- [ ] `services/api-gateway`: `make test && ruff check && mypy` green
- [ ] All future wave prompts (0016+) include `docs/STANDARDS.md` as mandatory pre-read item 4
