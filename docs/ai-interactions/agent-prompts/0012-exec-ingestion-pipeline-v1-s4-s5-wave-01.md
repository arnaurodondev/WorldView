# Execution Prompt 0012 — Ingestion Pipeline v1: S4+S5 Wave 01

**Wave:** 01 of 07
**Date issued:** 2026-03-22
**Service:** S4 Content Ingestion — Foundation layer
**Execution model:** 4 agents in parallel (one per task)

---

## Context (read first)

- Planning prompt: `docs/ai-interactions/agent-prompts/0012-ingestion-pipeline-v1-s4-s5-plan.md`
- Planning response: `docs/ai-interactions/agent-responses/0012-response-20260322-ingestion-pipeline-v1-s4-s5.md`

---

## Assigned agent profile(s)

- `docs/agents/backend-engineer.md`
- `docs/agents/data-platform-engineer.md`

---

## Mandatory pre-read

Before writing any code, read in full:

1. `AGENTS.md` — project-wide agent conventions
2. `CLAUDE.md` — project coding standards and architecture rules
3. `docs/services/content-ingestion.md` — S4 service specification
4. `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md` — PRD, domain model, schema definitions
5. `docs/ai-interactions/agent-responses/0012-response-20260322-ingestion-pipeline-v1-s4-s5.md` — this wave's planning context
6. `services/content-ingestion/pyproject.toml` — verify `uuid6`, `aiokafka`, `fastavro`, `minio`/`aioboto3` are listed as dependencies before writing any code; add missing deps before proceeding
7. `docs/libs/common.md` — UUIDv7 (`new_uuid7`), UTC time (`utc_now`), cross-service types (`DocumentId`, `EntityId`, `UrlHash`, `MinIOKey`)
8. **`docs/STANDARDS.md`** — engineering standards and anti-patterns: canonical library usage, config conventions, observability setup, testing rules

---

## Objective

Establish the complete foundation layer for the S4 Content Ingestion service: domain entities, configuration, database infrastructure, outbox dispatcher, and MinIO bronze adapter. These four components have zero inter-dependencies and zero dependencies on any other S4 component, making them fully parallelizable. All subsequent S4 waves depend on the contracts established here.

---

## Task scope for this wave

**All 4 tasks run in parallel:**

| Task ID | Description | Owner |
|---------|-------------|-------|
| T-S4-001 | Config + Domain entities (Source, FetchResult, SourceType, RawArticle, TokenBucket) | Agent A |
| T-S4-002 | DB infrastructure (content_ingestion_db session, FetchLogRepository, OutboxRepository, SourceRepository) | Agent B |
| T-S4-003 | Outbox dispatcher (poll outbox_events, Avro serialize, Kafka publish, mark dispatched/failed, move to DLQ after max_retries) | Agent C |
| T-S4-004 | MinIO bronze adapter (put_object, key pattern: content-ingestion/{source_type}/{url_hash}/raw/v1.json) | Agent D |

---

## Why this chunk

Wave 01 establishes the zero-dependency foundation that all other S4 waves build upon. T-S4-001 defines the domain contracts (entity types) consumed by every other component. T-S4-002 establishes the persistence layer required by adapters and the use-case. T-S4-003 and T-S4-004 are infrastructure components that are also independently implementable at this stage — they consume T-S4-001 types but have no circular dependencies. Running all four in parallel minimises critical-path time before Wave 02 can start.

---

## Implementation instructions

### T-S4-001 — Config + Domain Entities

1. **Verify pyproject.toml** — confirm `uuid6`, `pydantic-settings`, `structlog` are listed. Add any missing deps to `services/content-ingestion/pyproject.toml` before writing code.

2. **Create `services/content-ingestion/src/content_ingestion/config.py`** using `pydantic_settings.BaseSettings`:
   ```python
   class Settings(BaseSettings):
       EODHD_API_KEY: str
       SEC_EDGAR_USER_AGENT: str  # required by SEC policy
       FINNHUB_API_KEY: str
       NEWSAPI_KEY: str
       CONTENT_INGESTION_DB_URL: str
       KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
       KAFKA_OUTBOX_TOPIC: str = "content.article.raw.v1"
       MINIO_ENDPOINT: str = "localhost:9000"
       MINIO_ACCESS_KEY: str
       MINIO_SECRET_KEY: str
       MINIO_BUCKET: str = "worldview-bronze"
       ADMIN_TOKEN: str
       SCHEDULER_INTERVAL_SECONDS: int = 300
       OUTBOX_BATCH_SIZE: int = 100
       OUTBOX_POLL_INTERVAL_SECONDS: int = 5
       MAX_RETRIES: int = 3
       OUTBOX_METRICS_POLL_SECONDS: int = 30
       NEWSAPI_DAILY_LIMIT: int = 100
       VALKEY_URL: str = "redis://localhost:6379"

       model_config = SettingsConfigDict(env_file=".env", extra="ignore")
   ```

3. **Create `services/content-ingestion/src/content_ingestion/domain/__init__.py`** — export all public symbols.

4. **Create `services/content-ingestion/src/content_ingestion/domain/entities.py`**:
   - `SourceType` enum: `EODHD = "eodhd"`, `SEC_EDGAR = "sec_edgar"`, `FINNHUB = "finnhub"`, `NEWSAPI = "newsapi"`.
   - `Source` dataclass (frozen=False): `id: UUID`, `name: str`, `source_type: SourceType`, `enabled: bool`, `config: dict[str, Any]`, `created_at: datetime`.
   - `FetchResult` dataclass (frozen=True): `source_id: UUID`, `url: str`, `url_hash: str`, `raw_bytes: bytes`, `fetched_at: datetime`, `http_status: int`, `content_type: str`.
   - `RawArticle` dataclass (frozen=True): `id: UUID`, `source_type: SourceType`, `url: str`, `url_hash: str`, `raw_bytes: bytes`, `fetched_at: datetime`, `byte_size: int`.
   - All `datetime` fields must be `datetime` with UTC timezone — never naive datetimes. Use `datetime.now(tz=timezone.utc)` pattern.
   - All `UUID` fields generated with `common.ids.new_uuid7()` by default via `field(default_factory=common.ids.new_uuid7)`.

5. **Create `services/content-ingestion/src/content_ingestion/domain/value_objects.py`**:
   - `TokenBucket` dataclass:
     ```python
     @dataclass
     class TokenBucket:
         capacity: int
         tokens: float
         refill_rate: float  # tokens per second
         last_refill: datetime

         def _refill(self) -> None:
             now = datetime.now(tz=timezone.utc)
             elapsed = (now - self.last_refill).total_seconds()
             self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
             self.last_refill = now

         def consume(self, n: int = 1) -> bool:
             self._refill()
             if self.tokens >= n:
                 self.tokens -= n
                 return True
             return False

         def wait_time(self, n: int = 1) -> float:
             self._refill()
             if self.tokens >= n:
                 return 0.0
             return (n - self.tokens) / self.refill_rate
     ```

6. **Create `services/content-ingestion/src/content_ingestion/domain/exceptions.py`**:
   - `StorageError(Exception)`, `ConfigurationError(Exception)`, `QuotaExhaustedError(Exception)`, `AdapterError(Exception)`.

7. **Write unit tests** at `services/content-ingestion/tests/unit/test_domain.py`:
   - `test_token_bucket_consume_deducts_tokens` — consume 1, assert tokens decremented.
   - `test_token_bucket_consume_returns_false_when_empty` — drain bucket, assert False.
   - `test_token_bucket_refill_over_time` — mock time, assert refill.
   - `test_token_bucket_wait_time_zero_when_sufficient` — tokens=5, n=3 → wait_time=0.0.
   - `test_token_bucket_wait_time_positive_when_insufficient` — tokens=0, n=1 → wait_time > 0.
   - `test_raw_article_byte_size_from_raw_bytes`.

8. **Run:** `cd services/content-ingestion && make test` — all tests must pass.
9. **Run:** `ruff check services/content-ingestion/src/` — zero violations.
10. **Run:** `mypy services/content-ingestion/src/` — zero errors.

---

### T-S4-002 — DB Infrastructure

1. **Create `services/content-ingestion/src/content_ingestion/infrastructure/db/session.py`**:
   ```python
   from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
   from contextlib import asynccontextmanager
   from content_ingestion.config import Settings

   def create_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
       engine = create_async_engine(settings.CONTENT_INGESTION_DB_URL, echo=False)
       return async_sessionmaker(engine, expire_on_commit=False)

   @asynccontextmanager
   async def get_db_session(session_factory: async_sessionmaker[AsyncSession]):
       async with session_factory() as session:
           try:
               yield session
               await session.commit()
           except Exception:
               await session.rollback()
               raise
   ```

2. **Create `services/content-ingestion/src/content_ingestion/infrastructure/db/models.py`** using SQLAlchemy 2.x declarative base:
   - `Base = DeclarativeBase()`
   - `SourceModel` → table `sources`: `id UUID PK`, `name TEXT UNIQUE NOT NULL`, `source_type TEXT NOT NULL`, `enabled BOOL NOT NULL DEFAULT TRUE`, `config JSONB NOT NULL DEFAULT '{}'`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`.
   - `FetchLogModel` → table `fetch_logs`: `id UUID PK`, `source_id UUID NOT NULL FK→sources.id`, `url TEXT NOT NULL`, `url_hash TEXT NOT NULL`, `http_status INT`, `byte_size INT`, `fetched_at TIMESTAMPTZ NOT NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`. Add `UniqueConstraint('url_hash', name='uq_fetch_logs_url_hash')`.
   - `OutboxEventModel` → table `outbox_events`: `id UUID PK`, `aggregate_type TEXT NOT NULL`, `aggregate_id UUID NOT NULL`, `event_type TEXT NOT NULL`, `payload JSONB NOT NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `dispatched_at TIMESTAMPTZ`, `retry_count INT NOT NULL DEFAULT 0`, `status TEXT NOT NULL DEFAULT 'pending'`, `error TEXT`. Add index on `(status, created_at)`.
   - `DLQEventModel` → table `dlq_events`: `id UUID PK`, `original_event_id UUID NOT NULL`, `payload JSONB NOT NULL`, `error TEXT NOT NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `resolved_at TIMESTAMPTZ`, `status TEXT NOT NULL DEFAULT 'open'`.

3. **Create repositories** at `services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/`:
   - `fetch_log.py` — `FetchLogRepository(session)`:
     - `async def create(url: str, url_hash: str, source_id: UUID, http_status: int, byte_size: int, fetched_at: datetime) -> None`
     - `async def exists_by_url_hash(url_hash: str) -> bool`
   - `outbox.py` — `OutboxRepository(session)`:
     - `async def append(aggregate_type: str, aggregate_id: UUID, event_type: str, payload: dict) -> None`
     - `async def fetch_pending(limit: int = 100) -> list[OutboxEventModel]`
     - `async def mark_dispatched(event_id: UUID) -> None` — sets `status='dispatched'`, `dispatched_at=now()`
     - `async def mark_failed(event_id: UUID, error: str) -> None` — increments `retry_count`, sets `status='failed'`, `error=error`
     - `async def move_to_dlq(event_id: UUID) -> None` — inserts into `dlq_events`, deletes from `outbox_events`
   - `source.py` — `SourceRepository(session)`:
     - `async def get_all() -> list[SourceModel]`
     - `async def get_by_id(source_id: UUID) -> SourceModel | None`
     - `async def create(name: str, source_type: str, config: dict, enabled: bool = True) -> SourceModel`
     - `async def update(source_id: UUID, **kwargs) -> SourceModel`

4. **Create Alembic migration** `services/content-ingestion/alembic/versions/0001_initial_s4_schema.py`:
   - `revision = '0001'`, `down_revision = None`
   - `upgrade()`: CREATE EXTENSION IF NOT EXISTS "pgcrypto"; CREATE TABLE sources; CREATE TABLE fetch_logs; CREATE TABLE outbox_events; CREATE INDEX; CREATE TABLE dlq_events.
   - `downgrade()`: DROP TABLE dlq_events; DROP TABLE outbox_events; DROP TABLE fetch_logs; DROP TABLE sources.

5. **Write unit tests** at `services/content-ingestion/tests/unit/test_repositories.py` using `pytest-asyncio` with mock async session:
   - `test_fetch_log_repo_create` — assert INSERT called.
   - `test_fetch_log_repo_exists_by_url_hash_true` — mock query returns row.
   - `test_fetch_log_repo_exists_by_url_hash_false` — mock returns None.
   - `test_outbox_repo_append` — assert INSERT with correct payload.
   - `test_outbox_repo_mark_dispatched` — assert status='dispatched'.
   - `test_outbox_repo_move_to_dlq` — assert INSERT dlq_events + DELETE outbox_events.
   - `test_source_repo_get_all` — assert list returned.

6. **Run:** `cd services/content-ingestion && make test`, `ruff check`, `mypy`.

---

### T-S4-003 — Outbox Dispatcher

1. **Confirm `fastavro` in pyproject.toml.** If absent, add it.

2. **Create `services/content-ingestion/src/content_ingestion/infrastructure/outbox/avro_schema.py`**:
   ```python
   ARTICLE_RAW_V1_SCHEMA = {
       "type": "record",
       "name": "ArticleRawV1",
       "namespace": "com.worldview.content",
       "fields": [
           {"name": "article_id", "type": "string"},
           {"name": "source_type", "type": "string"},
           {"name": "url", "type": "string"},
           {"name": "url_hash", "type": "string"},
           {"name": "minio_key", "type": "string"},
           {"name": "fetched_at", "type": "string"},
           {"name": "byte_size", "type": "int"},
       ]
   }
   ```

3. **Create `services/content-ingestion/src/content_ingestion/infrastructure/outbox/dispatcher.py`**:
   ```python
   import asyncio
   import io
   import fastavro
   import structlog
   from content_ingestion.infrastructure.outbox.avro_schema import ARTICLE_RAW_V1_SCHEMA

   logger = structlog.get_logger(__name__)

   class OutboxDispatcher:
       def __init__(self, session_factory, kafka_producer, settings):
           self._session_factory = session_factory
           self._kafka_producer = kafka_producer
           self._settings = settings

       async def run_once(self) -> None:
           async with get_db_session(self._session_factory) as session:
               repo = OutboxRepository(session)
               events = await repo.fetch_pending(limit=self._settings.OUTBOX_BATCH_SIZE)
           for event in events:
               await self._dispatch_event(event)

       async def _dispatch_event(self, event) -> None:
           try:
               avro_bytes = self._serialize(event.payload)
               await self._kafka_producer.send_and_wait(
                   self._settings.KAFKA_OUTBOX_TOPIC,
                   value=avro_bytes,
                   key=str(event.aggregate_id).encode()
               )
               async with get_db_session(self._session_factory) as session:
                   await OutboxRepository(session).mark_dispatched(event.id)
               logger.info("outbox.dispatched", event_id=str(event.id))
           except Exception as exc:
               logger.error("outbox.dispatch_failed", event_id=str(event.id), error=str(exc))
               async with get_db_session(self._session_factory) as session:
                   repo = OutboxRepository(session)
                   await repo.mark_failed(event.id, str(exc))
                   # Reload to check retry_count
                   updated = await repo.get_by_id(event.id)
                   if updated and updated.retry_count >= self._settings.MAX_RETRIES:
                       await repo.move_to_dlq(event.id)

       def _serialize(self, payload: dict) -> bytes:
           buf = io.BytesIO()
           fastavro.schemaless_writer(buf, ARTICLE_RAW_V1_SCHEMA, payload)
           return buf.getvalue()

       async def run_loop(self) -> None:
           while True:
               try:
                   await self.run_once()
               except Exception as exc:
                   logger.error("outbox.loop_error", error=str(exc))
               await asyncio.sleep(self._settings.OUTBOX_POLL_INTERVAL_SECONDS)
   ```

4. Add `async def get_by_id(event_id: UUID)` to `OutboxRepository` if not already there (needed for retry_count check).

5. **Write unit tests** at `services/content-ingestion/tests/unit/test_outbox_dispatcher.py`:
   - `test_dispatch_success` — mock session + kafka producer; run `run_once()`; assert `send_and_wait` called; assert `mark_dispatched` called.
   - `test_dispatch_kafka_failure_marks_failed` — mock kafka raises; assert `mark_failed` called.
   - `test_dispatch_moves_to_dlq_after_max_retries` — mock event with `retry_count = MAX_RETRIES`; assert `move_to_dlq` called.
   - `test_serialize_avro_roundtrip` — serialize dict → deserialize → assert equal.

6. **Run:** `cd services/content-ingestion && make test`, `ruff check`, `mypy`.

---

### T-S4-004 — MinIO Bronze Adapter

1. **Check pyproject.toml** — if `minio` SDK present, use sync client wrapped with `asyncio.to_thread`. If `aioboto3` present, use native async. Document the choice in a module-level docstring.

2. **Create `services/content-ingestion/src/content_ingestion/infrastructure/storage/minio_bronze.py`**:
   ```python
   import asyncio
   import base64
   import json
   from datetime import timezone
   from content_ingestion.domain.entities import RawArticle, SourceType
   from content_ingestion.domain.exceptions import StorageError

   class MinioBronzeAdapter:
       KEY_PATTERN = "content-ingestion/{source_type}/{url_hash}/raw/v1.json"

       def __init__(self, client, bucket: str):
           self._client = client  # minio.Minio or aioboto3 client
           self._bucket = bucket

       def _make_key(self, source_type: SourceType, url_hash: str) -> str:
           return self.KEY_PATTERN.format(
               source_type=source_type.value,
               url_hash=url_hash
           )

       def _make_envelope(self, article: RawArticle) -> bytes:
           return json.dumps({
               "url": article.url,
               "source_type": article.source_type.value,
               "fetched_at": article.fetched_at.isoformat(),
               "byte_size": article.byte_size,
               "raw_bytes_b64": base64.b64encode(article.raw_bytes).decode("ascii"),
           }).encode("utf-8")

       async def put_object(self, article: RawArticle) -> str:
           key = self._make_key(article.source_type, article.url_hash)
           envelope = self._make_envelope(article)
           try:
               await asyncio.to_thread(
                   self._client.put_object,
                   self._bucket,
                   key,
                   io.BytesIO(envelope),
                   length=len(envelope),
                   content_type="application/json",
               )
               return key
           except Exception as exc:
               raise StorageError(f"MinIO put failed: {exc}") from exc

       async def object_exists(self, url_hash: str, source_type: SourceType) -> bool:
           key = self._make_key(source_type, url_hash)
           try:
               await asyncio.to_thread(self._client.stat_object, self._bucket, key)
               return True
           except Exception:
               return False
   ```

3. **Write unit tests** at `services/content-ingestion/tests/unit/test_minio_bronze.py`:
   - `test_put_object_key_format` — mock client; call `put_object`; assert key matches pattern `content-ingestion/eodhd/{url_hash}/raw/v1.json`.
   - `test_put_object_envelope_structure` — capture bytes written; assert JSON parseable; assert keys `url`, `source_type`, `fetched_at`, `raw_bytes_b64` present.
   - `test_put_object_raises_storage_error_on_s3_error` — mock client raises; assert `StorageError` raised.
   - `test_object_exists_returns_true_when_stat_succeeds`.
   - `test_object_exists_returns_false_on_exception`.

4. **Run:** `cd services/content-ingestion && make test`, `ruff check`, `mypy`.

---

## Constraints

- Do NOT implement any code outside T-S4-001, T-S4-002, T-S4-003, T-S4-004.
- Do NOT create scheduler, adapters (EODHD/SEC/Finnhub/NewsAPI), admin API, or integration tests — those are future waves.
- Do NOT import from future wave modules (e.g., do not import `EodhdAdapter` into this wave's code).
- Hexagonal architecture: no API layer in this wave; no application use-cases; domain and infrastructure only.
- No `print()` statements — use `structlog` exclusively.
- All datetimes: UTC only (`timezone.utc`).
- All IDs: UUIDv7 via `common.ids.new_uuid7()`.
- **`common.ids.new_uuid7()` mandatory** — all entity, document, fetch-log, and outbox primary keys must use `common.ids.new_uuid7()`. Never call `common.ids.new_uuid7()` directly in service code; `uuid6` must not appear in service-layer imports.
- **`common.time.utc_now()` mandatory** — all timestamp generation uses `common.time.utc_now()`. Never call `datetime.now(UTC)` or `datetime.utcnow()` directly in service code.
- **`common.types` for cross-service IDs** — use `DocumentId` (from `common.types`) for canonical document primary keys; `UrlHash` for sha256(url) values; `MinIOKey` for MinIO object key strings.

---

## Scope & token budget

**Write paths (exhaustive — do not create files outside this list):**

```
services/content-ingestion/src/content_ingestion/config.py
services/content-ingestion/src/content_ingestion/domain/__init__.py
services/content-ingestion/src/content_ingestion/domain/entities.py
services/content-ingestion/src/content_ingestion/domain/value_objects.py
services/content-ingestion/src/content_ingestion/domain/exceptions.py
services/content-ingestion/src/content_ingestion/infrastructure/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/db/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/db/session.py
services/content-ingestion/src/content_ingestion/infrastructure/db/models.py
services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/fetch_log.py
services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/outbox.py
services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/source.py
services/content-ingestion/alembic/versions/0001_initial_s4_schema.py
services/content-ingestion/src/content_ingestion/infrastructure/outbox/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/outbox/avro_schema.py
services/content-ingestion/src/content_ingestion/infrastructure/outbox/dispatcher.py
services/content-ingestion/src/content_ingestion/infrastructure/storage/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/storage/minio_bronze.py
services/content-ingestion/tests/unit/test_domain.py
services/content-ingestion/tests/unit/test_repositories.py
services/content-ingestion/tests/unit/test_outbox_dispatcher.py
services/content-ingestion/tests/unit/test_minio_bronze.py
services/content-ingestion/pyproject.toml
services/content-store/pyproject.toml
```

**Max exploration:** Read at most 10 files outside write paths for context (pyproject.toml, existing test infrastructure, alembic env.py).

**Stop condition:** Stop when all 4 tasks have passing tests, zero ruff violations, zero mypy errors. Do not proceed to Wave 02 tasks.

---

## Required tests

```bash
# Unit tests — must pass before marking wave complete
cd services/content-ingestion && make test

# Lint — zero violations
ruff check services/content-ingestion/src/

# Types — zero errors
mypy services/content-ingestion/src/
```

**Pass criteria:**
- All unit tests green (no skips, no failures, no errors).
- `ruff check` exits 0.
- `mypy` exits 0 (strict mode as configured in `pyproject.toml`).

---

## Retroactive amendment — Backfill support (added 2026-03-23)

Wave 01 was executed before the backfill architecture (§2.4 of PRD) was designed.  The following
corrections were applied during the session that delivered this wave; they are recorded here for
reference by agents reading this wave prompt in future sessions.

### T-S4-001 amendments

**`config.py`** — five backfill env vars added to `Settings`:

| Variable | Default | Type |
|----------|---------|------|
| `BACKFILL_ENABLED` | `False` | `bool` |
| `BACKFILL_FROM_DATE` | `""` | `str` |
| `BACKFILL_TO_DATE` | `""` | `str` |
| `BACKFILL_SOURCES` | `""` | `str` |
| `BACKFILL_BATCH_DELAY_SECONDS` | `0.5` | `float` |

**`entities.py`** — `published_at` and `is_backfill` added to `FetchResult` and `RawArticle`:

```python
@dataclass(frozen=True)
class FetchResult:
    ...
    published_at: datetime | None = None   # source-reported editorial date
    is_backfill: bool = False              # True during boot-time backfill run

@dataclass(frozen=True)
class RawArticle:
    ...
    published_at: datetime | None = None
    is_backfill: bool = False
```

### T-S4-002 amendments

**`models.py`** — `FetchLogModel` gained two columns:
- `published_at: Mapped[datetime | None]` — `DateTime(timezone=True)`, nullable
- `is_backfill: Mapped[bool]` — `Boolean`, not null, default `False`

**`fetch_log.py`** — `FetchLogRepository.create()` signature extended:
```python
async def create(
    self,
    url: str,
    url_hash: str,
    source_id: UUID,
    http_status: int,
    byte_size: int,
    fetched_at: datetime,
    published_at: datetime | None = None,
    is_backfill: bool = False,
) -> None: ...
```

**Migrations** — two migration files replace the original single file:
- `0001_initial_s4_schema.py` — initial schema (sources, fetch_logs including new columns, outbox_events, dlq_events)
- `0002_add_backfill_fields.py` (`down_revision = "0001"`) — ALTER TABLE fetch_logs ADD COLUMN published_at, is_backfill (for running deployments that had the old 0001)

### T-S4-003 amendments

**`avro_schema.py`** — two new backward-compatible fields added to `ARTICLE_RAW_V1_SCHEMA`:
```python
{"name": "published_at", "type": ["null", "string"], "default": None},
{"name": "is_backfill",  "type": "boolean",           "default": False},
```

All three amendments (T-S4-001, T-S4-002, T-S4-003) were verified passing: 26 unit tests green,
ruff clean, mypy clean.

---

## Incremental quality gates (mandatory)

Apply per-task — complete in order, never defer:

1. **T-S4-001**: write code → `make test` (domain tests) → `ruff check` → `mypy` → all green → DONE.
2. **T-S4-002**: write code → `make test` (repo tests) → `ruff check` → `mypy` → all green → DONE.
3. **T-S4-003**: write code → `make test` (dispatcher tests) → `ruff check` → `mypy` → all green → DONE.
4. **T-S4-004**: write code → `make test` (storage tests) → `ruff check` → `mypy` → all green → DONE.

**No deferred fixes:** If `ruff` or `mypy` or `pytest` fails on any task, fix it before moving to the next task. Do not mark a task done with outstanding failures.

---

## Documentation requirements

**Files impacted by this wave:**

| File | Update condition | Required update |
|------|-----------------|-----------------|
| `docs/services/content-ingestion.md` | Domain entities section | Add/update `Source`, `FetchResult`, `SourceType`, `RawArticle`, `TokenBucket` descriptions; add MinIO key pattern; add outbox Avro schema field list |

**Documentation quality criteria (all must be satisfied or N/A justified):**

1. Accuracy — all entity fields match implementation exactly. ✓ required.
2. Diagrams — no non-trivial multi-component flows in this wave. N/A.
3. Realistic code examples — entity construction examples in service doc. ✓ required.
4. Abstract methods documented — `TokenBucket.consume()` and `wait_time()` documented with what they do and return. ✓ required.
5. Common pitfalls — add to service doc: (a) naive datetimes in entity fields cause comparison bugs; (b) `TokenBucket` is not thread-safe — use per-adapter instance; (c) `url_hash` UNIQUE constraint means re-fetching same URL is silently skipped.
6. Lib docs — N/A (no new lib surface in this wave).
7. Service docs reflect final state — update `docs/services/content-ingestion.md`. ✓ required.
8. No orphan documentation — N/A (no doc files deleted).

---

## Required handoff evidence

Provide the following before declaring Wave 01 complete:

1. **Changed files list** (git diff --name-only).
2. **Test results:** paste output of `cd services/content-ingestion && make test` showing all tests passed.
3. **Ruff output:** paste `ruff check services/content-ingestion/src/` showing exit 0.
4. **Mypy output:** paste `mypy services/content-ingestion/src/` showing 0 errors.
5. **Docs changed:** confirm `docs/services/content-ingestion.md` updated with domain entity table.
6. **Validation ledger:**

| Task | Tests | Ruff | Mypy | Docs |
|------|-------|------|------|------|
| T-S4-001 | PASS | PASS | PASS | UPDATED |
| T-S4-002 | PASS | PASS | PASS | N/A |
| T-S4-003 | PASS | PASS | PASS | N/A |
| T-S4-004 | PASS | PASS | PASS | N/A |

7. **Commit message proposal:**

```
feat(s4): add S4 foundation — domain entities, DB infra, outbox dispatcher, MinIO bronze adapter

Establishes the complete foundation layer for Content Ingestion: domain entities
(Source, FetchResult, SourceType, RawArticle, TokenBucket), async SQLAlchemy repositories,
Avro outbox dispatcher, and MinIO bronze storage adapter with canonical key pattern.

Co-authored-by: <agent>
```

---

## Definition of done

Wave 01 is complete when ALL of the following are true:

- [ ] T-S4-001: domain entities importable, `TokenBucket` tested, `ruff`/`mypy` clean.
- [ ] T-S4-002: session factory + 3 repositories functional, Alembic migration written, `ruff`/`mypy` clean.
- [ ] T-S4-003: outbox dispatcher polls/serializes/publishes/marks, retry/DLQ logic tested, `ruff`/`mypy` clean.
- [ ] T-S4-004: MinIO adapter puts objects at correct key pattern, raises `StorageError` on failure, `ruff`/`mypy` clean.
- [ ] All unit tests green (`make test` exit 0).
- [ ] `ruff check` exit 0 on `services/content-ingestion/src/`.
- [ ] `mypy` exit 0 on `services/content-ingestion/src/`.
- [ ] `docs/services/content-ingestion.md` updated (domain entity table, MinIO key pattern, Avro schema fields, 3 common pitfalls).
- [ ] Documentation quality gate: all 8 criteria ✓ or N/A justified.
- [ ] Commit message proposal provided.
- [ ] No code outside the listed write paths created.
