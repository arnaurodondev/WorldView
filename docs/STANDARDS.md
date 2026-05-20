# Worldview Platform — Engineering Standards

**Version**: 2.0
**Date**: 2026-03-23
**Status**: Active — Single Source of Truth for contributor standards
**Applies to**: All services, all contributors (human and AI agent)

> This document is **non-negotiable**. Every execution wave prompt references it as a mandatory
> pre-read. When in doubt, follow this document. When this document conflicts with older code,
> fix the older code. This document is the single source of truth for implementation patterns,
> code structure, and automated enforcement. The canonical list of rules (R1–R34) lives in
> `RULES.md` (root) — STANDARDS.md §12 summarises the rules current at version 2.0; the
> complete and up-to-date list is always in `RULES.md`.

---

## Table of Contents

1. [Service Directory Structure](#1-service-directory-structure)
2. [libs/common — IDs, Time, Types](#2-libscommon--ids-time-types)
3. [libs/messaging — Outbox, Dispatcher, Kafka, Valkey](#3-libsmessaging--outbox-dispatcher-kafka-valkey)
4. [libs/storage — Object Storage (MinIO)](#4-libsstorage--object-storage-minio)
5. [libs/observability — Logging, Metrics, Tracing, Health](#5-libsobservability--logging-metrics-tracing-health)
6. [libs/contracts — Canonical Event Payloads](#6-libscontracts--canonical-event-payloads)
7. [FastAPI Application Structure](#7-fastapi-application-structure)
8. [Configuration (pydantic-settings)](#8-configuration-pydantic-settings)
9. [Error Handling](#9-error-handling)
10. [Testing Conventions](#10-testing-conventions)
11. [Anti-Patterns — What NOT To Do](#11-anti-patterns--what-not-to-do)
12. [Platform Rules (R1–R24)](#12-platform-rules-r1r24)
13. [Automated Enforcement — CI Gates](#13-automated-enforcement--ci-gates)
14. [Process Topology Standard](#14-process-topology-standard)
15. [Read/Write Database Session Pattern](#15-readwrite-database-session-pattern)
16. [Session Optimization](#16-session-optimization)
17. [Unit of Work — Explicit Commit Pattern](#17-unit-of-work--explicit-commit-pattern)
18. [Docker Container Validation](#18-docker-container-validation-r31)
19. [Parallel Execution & Subagent Patterns](#19-parallel-execution--subagent-patterns-r33-r34)

---

## 1. Service Directory Structure

Every service **must** follow the canonical DDD (Domain-Driven Design) hexagonal layout below.
No service may place source files outside this structure without an ADR.

### 1.1 Canonical layout

```
services/<service-name>/
├── src/
│   └── <package_name>/          # e.g. content_ingestion, nlp_pipeline
│       ├── __init__.py
│       ├── config.py             # Settings class only — no business logic
│       ├── app.py                # FastAPI factory + lifespan — no route logic
│       ├── domain/               # Pure Python — zero infrastructure imports
│       │   ├── __init__.py
│       │   ├── entities/         # Domain models and aggregates
│       │   │   └── __init__.py
│       │   ├── events.py         # Domain event dataclasses
│       │   ├── exceptions.py     # Domain exception hierarchy
│       │   └── value_objects.py  # Immutable value types
│       ├── application/          # Use cases and ports — depends on domain only
│       │   ├── __init__.py
│       │   ├── ports/            # Abstract interfaces (protocols)
│       │   └── use_cases/        # Business logic, orchestration
│       ├── api/                  # HTTP layer — depends on application
│       │   ├── __init__.py
│       │   ├── routes/           # FastAPI routers, one file per resource
│       │   ├── schemas.py        # Pydantic request/response schemas
│       │   ├── exception_handlers.py
│       │   └── error_mapping.py  # DomainException → HTTP status
│       └── infrastructure/       # External concerns — depends on all layers
│           ├── __init__.py
│           ├── db/               # PostgreSQL (SQLAlchemy + Alembic)
│           │   ├── models/       # SQLAlchemy ORM models
│           │   ├── repositories/ # Data access objects
│           │   └── session.py    # Session factory
│           ├── messaging/        # Kafka, outbox, Avro — ALL Kafka code goes here
│           │   ├── __init__.py
│           │   ├── outbox/       # Singular — one outbox per service
│           │   │   ├── dispatcher.py       # BaseOutboxDispatcher subclass
│           │   │   └── dispatcher_main.py  # Standalone entry point (own process)
│           │   ├── consumers/    # Plural — one file per consumed topic
│           │   │   ├── <type>_consumer.py       # BaseKafkaConsumer subclass
│           │   │   └── <type>_consumer_main.py  # Standalone entry point (own process)
│           │   └── schemas/      # Avro schema files — *.avsc ONLY, no Python dicts
│           ├── scheduler/        # Singular — one scheduling concern per service
│           │   ├── scheduler.py       # Scheduler class (tick-based loop)
│           │   └── scheduler_main.py  # Standalone entry point (own process)
│           ├── workers/          # Plural — horizontally scalable work pool
│           │   ├── worker.py       # Worker class (semaphore-bounded)
│           │   └── worker_main.py  # Standalone entry point (own process)
│           └── cache/            # Valkey / Redis wrappers
│               └── <purpose>_cache.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── contract/                 # S1 contracts, schema compatibility tests
├── alembic/
│   ├── env.py
│   └── versions/
├── alembic.ini
├── pyproject.toml
├── Makefile
└── README.md
```

### 1.2 Layer dependency rules

```
domain ← application ← api
domain ← application ← infrastructure
```

- `domain` imports **nothing** from `application`, `api`, or `infrastructure`.
- `application` imports from `domain` only (uses interfaces/ports for infrastructure).
- `infrastructure` implements the ports defined in `application/ports/`.
- `api` imports from `application` (use cases) and `domain` (entity types for schemas).
- **Cross-layer imports in the wrong direction are a hard blocker** — ruff/mypy must catch them.

### 1.3 Naming conventions

| Concept | Convention | Example |
|---------|-----------|---------|
| Python package | `snake_case` | `content_ingestion` |
| Service directory | `kebab-case` | `content-ingestion` |
| Module files | `snake_case.py` | `fetch_log_repository.py` |
| Domain entity | `PascalCase` dataclass | `class FetchResult` |
| ORM model | `PascalCase` + `Model` suffix | `class FetchLogModel` |
| Repository | `PascalCase` + `Repository` suffix | `class FetchLogRepository` |
| Use case | `PascalCase` + `UseCase` suffix | `class IngestArticleUseCase` |
| Port/Protocol | `PascalCase` + `Port` or `Protocol` suffix | `class OutboxRepositoryProtocol` |
| Avro schema file | `{service}.{event-type}.v{N}.avsc` | `content.article.raw.v1.avsc` |
| Consumer class | `PascalCase` + `Consumer` suffix | `class ArticleRawConsumer` |

### 1.4 Messaging subtree convention (strict)

For every non-scaffolded service, the messaging subtree is standardized as:

```
src/<package>/infrastructure/messaging/
├── __init__.py
├── outbox/                    # singular — one outbox per service
│   ├── dispatcher.py          # BaseOutboxDispatcher subclass
│   └── dispatcher_main.py     # standalone entry point (own process)
├── consumers/                 # plural — optional if service consumes topics
│   ├── <type>_consumer.py         # BaseKafkaConsumer subclass
│   └── <type>_consumer_main.py    # standalone entry point (own process)
├── schemas/
├── mapper.py                  # optional: event -> wire mapping helpers
└── serialization.py           # optional: serializer factories/helpers
```

Rules:
- `mapper.py` and `serialization.py` belong at **messaging root** (`infrastructure/messaging/`).
- Nested transport-specific subfolders such as `infrastructure/messaging/kafka/` are **forbidden** by default.
- If a service needs a nested subtree for exceptional reasons, it must be explicitly allowlisted in
    `scripts/structure_checks/exceptions.yaml` with expiry and owner.
- Outbox dispatchers must remain under `infrastructure/messaging/outbox/`.
- Avro schema files must remain under `infrastructure/messaging/schemas/`.

---

## 2. libs/common — IDs, Time, Types

**Package**: `common` · **Path**: `libs/common/`
**Full API reference**: `docs/libs/common.md`

### 2.1 ID generation — ALWAYS use `common.ids`

```python
# ✅ CORRECT
import common.ids

id = common.ids.new_uuid7()          # time-sortable UUID v7 for new records
id_str = common.ids.new_uuid7_str()  # same, as string
worker_id = common.ids.new_ulid()    # ULID for worker/lease IDs (lexicographic sort)

# ❌ FORBIDDEN — never in service code
import uuid
id = uuid.uuid4()           # bypasses common library, breaks type safety
id = uuid.UUID(str(...))    # constructing UUIDs manually
```

**Rule**: Every primary key in every table, every event ID, every domain entity ID **must** use
`common.ids`. The only exception is Alembic migration files (which may use plain SQL
`gen_random_uuid()` or `uuid_generate_v4()`).

**Which function to use**:

| Use case | Function | Why |
|----------|----------|-----|
| DB primary keys, domain entity IDs | `new_uuid7()` | Time-sortable; index-friendly; monotonically increasing within millisecond |
| Worker IDs, lease tokens, idempotency keys | `new_ulid()` | Lexicographic sort; URL-safe string form |
| Legacy UUID columns (migration only) | `new_uuid()` | Plain UUID v4 where monotonic order not needed |

### 2.2 Time — ALWAYS use `common.time`

```python
# ✅ CORRECT
import common.time

now = common.time.utc_now()              # timezone-aware UTC datetime
iso = common.time.to_iso8601(now)        # "2026-03-23T14:30:00.000000Z"
dt  = common.time.from_iso8601(iso_str)  # parse ISO-8601 string → UTC datetime
dt  = common.time.ensure_utc(any_dt)     # assert/convert to UTC (raises ValueError if naive)

# ❌ FORBIDDEN
from datetime import datetime
datetime.now()              # naive datetime — timezone-unaware, breaks comparisons
datetime.utcnow()           # deprecated since Python 3.12; still naive
datetime.now(timezone.utc)  # only acceptable in libs/common itself
```

**Rule**: All timestamps produced by service code — in DB models, domain events, outbox records,
log lines — **must** come from `common.time.utc_now()`.
SQLAlchemy `server_default=func.now()` is acceptable for DB-generated timestamps (e.g.
`created_at` in `server_default`), but any Python-generated timestamp must use `common.time`.

### 2.3 Type aliases — use `common.types` for cross-service IDs

```python
# ✅ CORRECT
from common.types import DocumentId, EntityId, UrlHash, MinIOKey, TenantId, UserId

def store_document(doc_id: DocumentId, key: MinIOKey) -> None: ...

# ❌ WRONG — raw UUID/str loses semantic meaning
def store_document(doc_id: UUID, key: str) -> None: ...
```

| Type alias | Underlying type | Semantic meaning |
|------------|----------------|-----------------|
| `TenantId` | `UUID` | Portfolio tenant identifier |
| `UserId` | `UUID` | Application user |
| `InstrumentId` | `UUID` | Financial instrument |
| `DocumentId` | `UUID` | Canonical document (content_store_db primary key) |
| `EntityId` | `UUID` | Knowledge graph entity |
| `UrlHash` | `str` | SHA-256 hex of a source URL |
| `MinIOKey` | `str` | MinIO object key string |
| `TopicName` | `str` | Kafka topic name |
| `EventId` | `UUID` | Outbox / domain event identifier |

### 2.4 Shared Enums — Placement Rules

Some enums are shared across multiple services. Use the correct canonical location:

| Enum | Location | Used By | Purpose |
|------|----------|---------|---------|
| `OutboxStatus` | `messaging.enums` | S1, S2, S4, S5+ | Outbox event lifecycle (PENDING → PROCESSING → DELIVERED \| FAILED → DEAD_LETTER) |
| `ContentSourceType` | `contracts.enums` | S4, S5 | Content source discriminator in Avro events |

**Decision criteria for new shared enums:**
1. **3+ services need it** with identical semantics → shared lib
2. **Cross-service event discriminator** (producer sets, consumer reads) → `libs/contracts/enums.py`
3. **Infrastructure lifecycle** (outbox, consumer, dispatcher states) → `libs/messaging/enums.py`
4. **Service-local domain logic** (even if names overlap) → keep in `domain/enums.py`

**Re-export pattern** — services re-export shared enums from `domain/enums.py` to preserve internal import paths:
```python
from messaging.enums import OutboxStatus as OutboxStatus  # re-export
```

---

## 3. libs/messaging — Outbox, Dispatcher, Kafka, Valkey

**Package**: `messaging` · **Path**: `libs/messaging/`
**Full API reference**: `docs/libs/messaging.md`

### 3.1 Kafka client — ALWAYS use `confluent-kafka` via messaging lib

All services produce and consume Kafka messages using `confluent-kafka` through the
`messaging` library abstractions. **No service may add `aiokafka` as a dependency.**

```python
# ✅ CORRECT — producer via messaging lib
from messaging.kafka.producer import build_serializing_producer, KafkaProducerConfig

config = KafkaProducerConfig(
    bootstrap_servers=settings.kafka_bootstrap_servers,
    schema_registry_url=settings.kafka_schema_registry_url,
    schema_registry_basic_auth=settings.kafka_schema_registry_basic_auth,
)
producer = build_serializing_producer(config)

# ❌ FORBIDDEN
from aiokafka import AIOKafkaProducer   # wrong client library entirely
producer = AIOKafkaProducer(...)
```

### 3.2 Outbox dispatcher — ALWAYS extend `BaseOutboxDispatcher`

```python
# ✅ CORRECT
# services/my-service/src/my_service/infrastructure/messaging/outbox/dispatcher.py
from messaging.kafka.dispatcher.base import BaseOutboxDispatcher, DispatcherConfig
from messaging.kafka.producer import build_serializing_producer
from messaging.kafka.serializer import build_avro_serializer, AvroSerializerConfig

class MyServiceOutboxDispatcher(BaseOutboxDispatcher):
    def __init__(self, settings: Settings) -> None:
        config = DispatcherConfig(
            poll_interval_seconds=settings.outbox_poll_interval_seconds,
            lease_seconds=settings.outbox_lease_seconds,
            batch_size=settings.outbox_batch_size,
            max_attempts=settings.outbox_max_attempts,
        )
        super().__init__(config)
        self._settings = settings
        self._producer = None
        self._serializers: dict[str, Any] = {}

    def get_unit_of_work(self) -> UnitOfWorkWithOutboxProtocol:
        return SqlAlchemyUnitOfWork(self._session_factory)

    def get_serializer(self, event_type: str):
        return self._serializers[event_type]

    def get_producer(self):
        if self._producer is None:
            self._producer = build_serializing_producer(
                KafkaProducerConfig(
                    bootstrap_servers=self._settings.kafka_bootstrap_servers,
                    schema_registry_url=self._settings.kafka_schema_registry_url,
                    schema_registry_basic_auth=self._settings.kafka_schema_registry_basic_auth,
                )
            )
        return self._producer

# ❌ FORBIDDEN — never write a custom outbox loop from scratch
class CustomDispatcher:
    async def run_once(self) -> None:
        events = await repo.fetch_pending()
        for e in events:
            await producer.send_and_wait(...)   # no lease, no backoff, race condition
```

### 3.3 Outbox repository — implement `OutboxRepositoryProtocol`

The outbox repository **must** implement the exact protocol defined in
`messaging.kafka.dispatcher.base.OutboxRepositoryProtocol`:

```python
class OutboxRepositoryProtocol(Protocol):
    async def fetch_pending(
        self, worker_id: str, lease_seconds: int, batch_size: int
    ) -> list[OutboxRecordProtocol]: ...
    async def mark_published(self, record_id: Any) -> None: ...
    async def increment_attempts(self, record_id: Any) -> None: ...
    async def move_to_dead_letter(self, record_id: Any) -> None: ...
```

`fetch_pending` **must** use `SELECT … FOR UPDATE SKIP LOCKED` and atomically set the
`lease_owner` and `lease_expires` columns. This prevents multiple dispatcher instances from
claiming the same record.

### 3.4 Outbox table schema — standard columns

Every service's `outbox_events` table **must** have these exact columns (names and types are
canonical; do not rename or omit):

```sql
CREATE TABLE outbox_events (
    id              UUID        PRIMARY KEY,
    event_type      TEXT        NOT NULL,
    topic           TEXT        NOT NULL,
    payload         JSONB       NOT NULL DEFAULT '{}',
    status          TEXT        NOT NULL DEFAULT 'pending',  -- see §3.5
    lease_owner     TEXT,                      -- worker_id that claimed this record
    lease_expires   TIMESTAMPTZ,               -- when the lease expires
    attempt_count   SMALLINT    NOT NULL DEFAULT 0,
    max_attempts    SMALLINT    NOT NULL DEFAULT 5,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    dispatched_at   TIMESTAMPTZ
);
CREATE INDEX ix_outbox_claimable ON outbox_events (status, lease_expires)
    WHERE status IN ('pending', 'processing');
```

Services that need to identify the domain aggregate may add `aggregate_type TEXT` and
`aggregate_id UUID` columns. The columns listed above are the minimum required set.

#### 3.4.1 Cross-service consistency — known historical drift

Historically, several services diverged from the canonical shape (audited
2026-05-09 in `docs/audits/2026-05-09-qa-beta-data-platform.md` finding
F-003). PLAN-0087 #9 reconciled the two outright bugs:

| Service / DB | Drift | Remediation migration |
|---|---|---|
| `portfolio_db` | `topic` column missing — derived from `event_type` via Python `EVENT_TOPIC_MAP` at dispatch time | `services/portfolio/alembic/versions/0017_add_topic_to_outbox_events.py` (adds nullable `topic` + back-fills) |
| `ingestion_db` | `dispatched_at` column missing — only `published_at` was present; SQL tooling that filtered on the canonical column missed this service | `services/market-ingestion/alembic/versions/0013_add_dispatched_at_to_outbox.py` (adds nullable `dispatched_at` + back-fills from `published_at`) |

Other historical column-name variations remain (e.g., the
"avro group" — `intelligence_db`, `nlp_db`, `alert_db` — still uses
`event_id` PK, `payload_avro BYTEA`, `retry_count`). Renaming these is
out-of-scope until a coordinated cut-over wave because it requires
simultaneous code changes across producers, consumers, and replay
tooling. New services MUST adopt the §3.4 canonical shape from day one;
existing-service migrations are the safety net for cross-service tooling.

When you write SQL that scans `outbox_events` across services (replay
scripts, dashboards, retention queries), use the **canonical column names**
(`id`, `topic`, `dispatched_at`, `attempt_count`) — every service's
post-PLAN-0087 schema exposes them.

### 3.5 Outbox status values — canonical state machine

```
pending → processing → delivered
                   ↘ dead_letter   (after max_attempts exhausted)
```

| Status | Meaning |
|--------|---------|
| `pending` | Waiting to be claimed by a dispatcher worker |
| `processing` | Leased by a worker; Kafka produce in progress |
| `delivered` | Kafka delivery acknowledged; record safe to archive/delete |
| `dead_letter` | Max retry attempts exhausted; requires manual intervention |

**No other status values are permitted.** All services must use these exact lowercase strings.

### 3.6 DLQ — status column only, no separate table

Dead-lettered events stay in `outbox_events` with `status = 'dead_letter'`.
There is **no** separate `dlq_events` table. This keeps all operational tooling (admin
endpoints, monitoring queries, retry triggers) pointing at one table.

```python
# Admin retry endpoint (all services implement this pattern):
# POST /admin/outbox/retry/{event_id}
# → sets status='pending', attempt_count=0, lease_owner=NULL, lease_expires=NULL
```

### 3.7 Avro schemas — `.avsc` files, never Python dicts

All Avro schemas **must** be stored as `.avsc` JSON files. Python dict definitions in source
code are **forbidden**.

```
services/<service>/src/<package>/infrastructure/messaging/schemas/
    content.article.raw.v1.avsc
    content.article.stored.v1.avsc
```

**File naming**: `{namespace-dotted}.{event-type}.v{N}.avsc`

```json
{
  "type": "record",
  "name": "ContentArticleRaw",
  "namespace": "com.worldview",
  "doc": "Raw article fetched by S4 and stored in MinIO bronze.",
  "fields": [
    {"name": "event_id",       "type": "string",            "doc": "UUIDv7 event identifier"},
    {"name": "schema_version", "type": "int",   "default": 1},
    {"name": "occurred_at",    "type": "string",            "doc": "ISO-8601 UTC"},
    {"name": "doc_id",         "type": "string"},
    {"name": "source_type",    "type": "string"},
    {"name": "published_at",   "type": ["null","string"],   "default": null},
    {"name": "is_backfill",    "type": "boolean",           "default": false},
    {"name": "correlation_id", "type": ["null","string"],   "default": null}
  ]
}
```

**Schema evolution rules** (enforced by Confluent Schema Registry, compatibility = BACKWARD):
- New fields **must** have a `default` value.
- Never remove or rename an existing field.
- Never change a field's type incompatibly.
- Bump `schema_version` integer when adding fields.

### 3.7.1 Avro on the wire — Hard Rule R28 (PLAN-0062)

Pure JSON on Kafka is **forbidden** (R28). Every topic in the platform follows
the same producer/consumer contract:

| Layer | Rule |
|-------|------|
| **Schema source of truth** | One `.avsc` file per topic in `infra/kafka/schemas/`, registered with the schema registry by `infra/kafka/init/register-schemas.py` at startup. |
| **Canonical model** | One frozen dataclass in `libs/contracts/src/contracts/canonical/<event>.py` (entity-shaped payloads — articles, OHLCV, instruments) **OR** `libs/contracts/src/contracts/events/<domain>/<event>.py` (pure trigger events — provisional queued, contradictions, enrichment). The model mirrors the Avro fields field-for-field with `from_dict` / `to_dict`. |
| **Producer** | `serialize_confluent_avro(schema_path, record)` (5-byte Confluent header + Avro body). Never `json.dumps(...).encode()` for outbox `payload_avro` writes. |
| **Consumer** | `deserialize_confluent_avro(schema_path, raw)` keyed off `get_schema_path(topic)`. JSON fallback is permitted only as a transition aid and must log every fallback hit (warning level) so the migration window is measurable and the branch can be removed once traffic decays to zero. |
| **Architecture test** | `tests/architecture/test_kafka_avro_enforcement.py` is unconditional — any new pure-JSON consumer fails the build. |

The `canonical/` vs `events/<domain>/` split is intentional: `canonical/`
historically carries the *one shape per domain* models that map onto
persisted entities, while `events/<domain>/` carries pure-event payloads
that exist only as Kafka triggers and never persist as their own row.
When in doubt, ask whether the payload corresponds to a row in some
service's database — if yes, it goes under `canonical/`; if it is
purely an event-of-something-happened, it goes under `events/<domain>/`.

#### Schema-id default (known limitation)

`serialize_confluent_avro(schema_path, record, schema_id=0)` defaults the
4-byte schema-id portion of the Confluent header to `0`. This is **invalid**
in a real Confluent Schema Registry — registry IDs start at 1 and are
assigned per registered subject. Internal consumers ignore the id (they load
the schema from disk via `get_schema_path`), so this is fine for in-platform
traffic, but external interoperability (ksqlDB, kafka-connect, third-party
consumers) requires producers to pass the real registry-issued id.
Reference: PLAN-0062 audit F-009.

#### No CI Schema Registry compat-check (known limitation)

CI runs `fastavro.parse_schema()` for **syntax** validation only — it does
NOT execute a registry-vs-PR compatibility test. Non-additive schema
changes (renamed fields, removed fields, narrowed types) therefore pass CI
and only fail at deploy time when the registry rejects the new subject
version. Consider adding `check-compatibility` against a local
schema-registry container in CI.
Reference: PLAN-0062 audit F-010.

### 3.7.2 Transporting heterogeneous arrays through flat Avro records

Some payloads are intrinsically heterogeneous — for example,
`nlp.article.enriched.v1` carries arrays of `raw_relations`, `raw_events`,
and `raw_claims` whose member shapes vary based on extractor mode. Two
designs are available: nested Avro records (one record per shape) or a
flat record with a JSON-string field per heterogeneous array. The flat
JSON-string approach is the project's preferred workaround when:

- The array's element schema is unstable (under active extraction-prompt
  iteration), AND
- The payload still passes through the same R28 Confluent-Avro envelope.

**Pattern**:

- The `.avsc` schema declares `<name>_json: ["null", "string"]` with
  `default: null`. The legacy nested-record fields are kept alongside as
  `["null", {"type": "array", ...}]` for backward compatibility.
- Producer side: `encode_raw_array(items)` from
  `contracts.events.nlp.article_enriched` — JSON-encodes the list and
  returns `None` for empty input so empty arrays do not bloat the wire.
- Consumer side: `decode_raw_array(blob)` — returns `[]` on every error
  branch (missing, invalid JSON, non-list root, oversized) AND emits a
  structured warning so silent drops are observable.
- Defence-in-depth: a 16 MiB hard cap (`_MAX_RAW_ARRAY_BYTES`) bounds the
  decoder against poison messages.

**When to use**:

- Mixed-shape arrays under prompt-engineering churn.
- Payloads where the element shape is best documented in the canonical
  model (not the wire schema).

**When NOT to use**:

- Arrays of stable, homogeneous records — those should be modelled as
  proper Avro nested records so the registry enforces the contract.
- Arrays > 16 MiB — split into a separate topic instead of bypassing the
  cap.

Both helpers are forgiving (`[]` on error) AND observable (warning per
drop branch). Cross-link: `BUG_PATTERNS.md` BP-313.

### 3.8 Valkey — ALWAYS use `messaging.valkey.ValkeyClient`

```python
# ✅ CORRECT
from messaging.valkey import ValkeyClient, ValkeyConfig, create_valkey_client_from_url

client: ValkeyClient = create_valkey_client_from_url(settings.valkey_url)

# ❌ FORBIDDEN
import redis.asyncio as aioredis       # bypasses shared client
import aioredis                         # same — bypasses shared client
client = aioredis.from_url(...)
```

**Key naming**: follow the taxonomy in `docs/architecture/decisions/0004-valkey-key-taxonomy.md`.
Pattern: `{service_prefix}:v{version}:{purpose}:{identifier}`

| Service | Prefix example |
|---------|---------------|
| S1 Portfolio | `portfolio:v1:watchlist:...` |
| S10 Alert | `s10:v1:watchlist:by_entity:{entity_id}` |
| S5 Content Store | `content_store:v1:lsh:{source_type}:{url_hash}` |
| API Gateway | `api_gateway:v1:rate_limit:{user_id}` |

### 3.9 Kafka consumer — ALWAYS extend `BaseKafkaConsumer`

```python
# services/my-service/src/my_service/infrastructure/messaging/consumers/article_raw_consumer.py
from messaging.kafka.consumer.base import BaseKafkaConsumer, ConsumerConfig
from messaging.kafka.consumer.errors import RetryableError, FatalError

class ArticleRawConsumer(BaseKafkaConsumer):
    def __init__(self, settings: Settings, ...) -> None:
        config = ConsumerConfig(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.kafka_consumer_group_id,
            topics=[settings.kafka_input_topic],
            schema_registry_url=settings.kafka_schema_registry_url,
        )
        super().__init__(config)

    async def handle(self, event: dict, raw_message) -> None:
        try:
            await self._process(event)
        except TransientDatabaseError as exc:
            raise RetryableError(str(exc)) from exc    # base class applies backoff
        except ValidationError as exc:
            raise FatalError(str(exc)) from exc        # base class dead-letters
```

**Error classification** (see `docs/architecture/decisions/0005-messaging-error-classification.md`):
- `RetryableError` — transient failures (DB unavailable, network timeout): automatic backoff + retry.
- `FatalError` — permanent failures (schema mismatch, invalid payload): immediate dead-letter, no retry.

### 3.8 Outbox Design Rules

New services implementing the outbox pattern MUST follow these rules:

**R-OUTBOX-1: Canonical column names** — Use protocol-standard names: `id` (UUID), `event_type`, `topic`, `payload` (JSONB), `status`, `attempts`, `leased_until`, `lease_owner`, `created_at`, `dispatched_at`.

**R-OUTBOX-2: Canonical status values** — Import `OutboxStatus` from `messaging.enums`: PENDING → PROCESSING → DELIVERED | FAILED → DEAD_LETTER. Services MAY add service-specific statuses but MUST support the canonical 5.

**R-OUTBOX-3: DLQ population** — If a service defines a `dead_letter_queue` table, `move_to_dead_letter()` MUST insert a row into it (not just change the outbox status). If no DLQ table exists, changing the outbox status to `dead_letter` is sufficient.

**R-OUTBOX-4: Payload format** — Outbox payload SHOULD be stored as JSONB for debuggability. Services that need binary Avro payloads MUST document the reason.

**R-OUTBOX-5: ID type** — Outbox event IDs MUST use UUIDv7 (`common.ids.new_uuid7()`).

### 3.10 Outbox `partition_key` pattern (PLAN-0057-followup)

**Why per-entity ordering matters.** Kafka guarantees ordering only within a single
partition. Without a producer key, librdkafka's sticky/round-robin partitioner spreads
messages across partitions arbitrarily — fine for events with no ordering invariant
(e.g., independent dataset arrivals), but **broken** for events that mutate the same
aggregate. Concrete example: two `market.instrument.created` events for the same
`instrument_id` can land on different partitions and reach the S7 KG consumer
out-of-order, overwriting the enriched canonical with an earlier placeholder. This was
audit finding **F-DATA-06** (`docs/audits/2026-05-01-investigation-plan-0057-open-items.md`
§2.2).

**The fix.** `OutboxRecordProtocol` exposes `partition_key: str | None` and
`BaseOutboxDispatcher` forwards it to `producer.produce(key=partition_key.encode("utf-8"))`.
NULL/None means round-robin (unchanged legacy behaviour); a non-empty string pins all
events with that key to the same Kafka partition.

**Three-step migration pattern (per producing service).** Adopt incrementally — only
services that emit ordered-by-aggregate events need it. Pilot example: market-data Wave B
(this PRD).

1. **Alembic — add the column** (forward-compatible per R11 / R5; nullable, no default):

   ```python
   def upgrade() -> None:
       op.execute(
           "ALTER TABLE outbox_events ADD COLUMN IF NOT EXISTS partition_key TEXT"
       )
   ```

2. **Repo + ORM — accept and persist the kwarg:**

   ```python
   # ORM model
   partition_key: Mapped[str | None] = mapped_column(String, nullable=True)

   # Repository.create — keyword arg, defaults to None
   async def create(
       self, event_type: str, topic: str, payload: dict, partition_key: str | None = None
   ) -> str:
       ...
       insert(OutboxEventModel).values(..., partition_key=partition_key)
   ```

3. **Producer call sites — pass the aggregate id when ordering matters:**

   ```python
   # Pin all events for the same instrument to the same partition.
   await uow.outbox_events.create(
       event_type=event.event_type,
       topic=topic,
       payload=event_to_outbox_payload(event),
       partition_key=str(instrument.id),
   )
   ```

**When NOT to set `partition_key`.** Events without ordering invariants (e.g.,
`market.dataset.fetched`, content-ingestion `content.article.raw.v1`) should leave it
NULL — Kafka's sticky/round-robin partitioner gives better load balancing than a
single-key hot spot. Empty-string keys are coerced to None by the dispatcher to prevent
accidental hot spots.

**Backwards compatibility.** Records that pre-date the protocol change keep working —
`BaseOutboxDispatcher` reads via `getattr(record, "partition_key", None)`, so legacy
outbox row types that don't declare the column dispatch with `key=None`.

**Reference implementation.** `services/market-data` (PLAN-0057-followup Wave B):
- Migration `services/market-data/alembic/versions/014_add_partition_key_to_outbox.py`
- ORM `services/market-data/src/market_data/infrastructure/db/models/infrastructure.py`
- Repo `services/market-data/src/market_data/infrastructure/db/repositories/outbox_event_repo.py`
- Producers: `ohlcv_consumer.py`, `quotes_consumer.py`, `fundamentals_consumer.py` —
  each pins instrument-scoped events with `partition_key=str(instrument.id)`.

### 3.9 Kafka Consumer Standard (R20)

Every Kafka consumer in a service **must** extend `BaseKafkaConsumer` from
`messaging.kafka.consumer.base`. Direct use of `confluent_kafka.Consumer` is forbidden
in service code.

```python
# ✅ CORRECT
# services/my-service/src/my_service/infrastructure/messaging/consumers/my_consumer.py
from messaging.kafka.consumer.base import BaseKafkaConsumer, ConsumerConfig
from messaging.kafka.consumer.errors import FatalError, RetryableError

class MyConsumer(BaseKafkaConsumer[None]):
    def __init__(self, config: ConsumerConfig, ...) -> None:
        super().__init__(config)
        ...

    def is_duplicate(self, event_id: str) -> bool:
        # Check processed_events table
        ...

    def get_unit_of_work(self) -> ...:
        ...

    async def process_message(self, msg: Any) -> None:
        # Business logic — do NOT call commit here
        ...

# ❌ FORBIDDEN
from confluent_kafka import Consumer  # direct consumer import
consumer = Consumer({"bootstrap.servers": "..."})
```

**Required abstract methods** (all must be implemented):
- `is_duplicate(event_id)` — idempotency check before processing
- `get_unit_of_work()` — returns UoW for the message
- `process_message(msg)` — business logic

**`_handle_message` override rule**: When overriding `_handle_message` for post-commit
side effects (e.g., LSH indexing after DB commit), always:
1. Set `self._current_uow = None` and any summary fields at the top of the override
2. Call `await super()._handle_message(msg)` inside a try-except
3. Perform post-commit work (e.g., cache writes) outside the try block, only on success
4. On exception, run compensating deletes (MinIO GC) before re-raising

Enforced by `tests/architecture/test_consumer_enforcement.py`.

### 3.11 Consumer Dedup — ALWAYS use `ValkeyDedupMixin`

Every `BaseKafkaConsumer` subclass **must** declare `ValkeyDedupMixin` as a
direct base class to satisfy the `is_duplicate` / `mark_processed` abstract
interface.  Writing a hand-rolled implementation is **forbidden**.

```python
# ✅ CORRECT
from messaging.kafka.consumer.base import BaseKafkaConsumer, ConsumerConfig
from messaging.kafka.consumer.dedup import ValkeyDedupMixin
from messaging.valkey.client import ValkeyClient

class ArticleRawConsumer(ValkeyDedupMixin, BaseKafkaConsumer[None]):
    def __init__(self, config: ConsumerConfig, valkey: ValkeyClient) -> None:
        super().__init__(config)
        self._dedup_client = valkey
        self._dedup_prefix = "content_ingestion:dedup:article_raw"
        # _dedup_ttl_seconds defaults to 86400 (24 h); override if needed

# ❌ FORBIDDEN — hand-rolled dedup inside the consumer class
class ArticleRawConsumer(BaseKafkaConsumer[None]):
    async def is_duplicate(self, event_id: str) -> bool:
        key = f"my_prefix:{event_id}"
        return bool(await self._valkey.exists(key))  # reinvents the mixin
```

**Contract**:

| Scenario | `is_duplicate` returns | `mark_processed` behaviour |
|----------|----------------------|---------------------------|
| Key exists in Valkey | `True` | — |
| Key absent | `False` | — |
| `_dedup_client is None` | `False` (at-least-once mode) | no-op |
| Valkey unreachable | `False` (at-least-once mode, logs `dedup.valkey_check_failed`) | swallowed (logs `dedup.valkey_mark_failed`) |

**At-least-once fallback safety**: when Valkey is unavailable the mixin
falls back to `False` (prefer reprocessing over silent drop).  This is only
safe when the consumer's downstream writes are idempotent — i.e. they use
deterministic IDs (`uuid5_from_parts`) **or** `INSERT … ON CONFLICT DO NOTHING`.
Every `BaseKafkaConsumer` subclass **must** document which strategy it relies on
in a comment near the class definition.

**Key naming**: follow the taxonomy in `docs/architecture/decisions/0004-valkey-key-taxonomy.md`.
The `_dedup_prefix` should be unique per consumer class:

```
{service_prefix}:dedup:{consumer_name}
# e.g. "content_ingestion:dedup:article_raw"
```

**TTL**: defaults to 86 400 seconds (24 hours).  Override `_dedup_ttl_seconds`
in the subclass when the message replay window differs.

**Cross-reference R9**: Valkey is the correct shared-state store for dedup keys.
PostgreSQL dedup tables are **forbidden** — they create cross-service DB coupling
and are single-point-of-failure under high throughput (R9).

**Enforcement**: `tests/architecture/test_consumer_dedup_mixin_enforcement.py`
(CONSUMER-DEDUP-001).  Allowlist for justified exceptions in
`tests/architecture/_consumer_dedup_allowlist.yaml`.

---

## 4. libs/storage — Object Storage (MinIO)

**Package**: `storage` · **Path**: `libs/storage/`
**Full API reference**: `docs/libs/storage.md`

### 4.1 ALWAYS use `storage.factory.build_object_storage()`

```python
# ✅ CORRECT
from storage.factory import build_object_storage
from storage.interface import ObjectStorage

storage: ObjectStorage = build_object_storage(
    endpoint=settings.minio_endpoint,
    access_key=settings.minio_access_key,
    secret_key=settings.minio_secret_key,
    bucket=settings.minio_bucket,
    secure=settings.minio_secure,
)

# Store an object
key = await storage.put_object(
    key="content-ingestion/eodhd/{url_hash}/raw/v1.json",
    data=json_bytes,
    content_type="application/json",
)

# Check existence
exists = await storage.object_exists(key)

# ❌ FORBIDDEN — never create custom MinIO or boto3 adapters
from minio import Minio
client = Minio(endpoint, access_key, secret_key)
client.put_object(bucket, key, data, length, ...)   # sync blocking call in async service

import boto3                                          # wrong client
s3 = boto3.client("s3", endpoint_url=...)
```

### 4.2 Key naming convention

MinIO object keys **must** follow the pattern:
```
{tier}/{service}/{source_type}/{identifier}/{version}.{ext}
```

| Tier | Purpose | Services |
|------|---------|---------|
| `bronze` | Raw fetched bytes, unprocessed | S4 |
| `silver` | Cleaned canonical text | S5 |
| `gold` | Enriched / structured outputs | S6, S7 |

Examples:
```
bronze/content-ingestion/eodhd/a3f2b1c4.../raw/v1.json
silver/content-store/news/doc_00123.../canonical/v1.txt
```

### 4.3 Error handling with storage lib

```python
from storage.exceptions import StorageError, ObjectNotFoundError, BucketNotFoundError

try:
    key = await storage.put_object(...)
except BucketNotFoundError:
    logger.error("minio_bucket_missing", bucket=settings.minio_bucket)
    raise ConfigurationError(f"MinIO bucket {settings.minio_bucket} does not exist")
except StorageError as exc:
    # Retryable — let the caller handle or raise as RetryableError
    raise
```

### 4.4 MinIO Compensating Delete (GC on DB rollback)

When a service writes to MinIO **before** the DB transaction commits, it must implement
a compensating delete if the commit fails. This prevents orphaned MinIO objects that
consume storage and cannot be garbage-collected.

**Pattern: track pending keys, delete on failure**

```python
# In use cases or consumers that write to MinIO then commit the DB:
pending_minio_keys: list[str] = []

try:
    key = await storage_port.put_object(...)
    pending_minio_keys.append(key)  # track before DB commit

    await db_repo.create(...)          # DB write
    await outbox.append(...)           # outbox write
    await commit()                     # commit — success
    pending_minio_keys = []            # committed: no longer orphaned

except Exception:
    # Rollback DB session first
    await rollback()
    # Then GC all MinIO objects written in this failed batch
    for key in pending_minio_keys:
        try:
            await storage_port.delete_object(key)
        except Exception:
            logger.warning("minio_gc_delete_failed", key=key)  # best-effort
    raise
```

**Rules**:
- The `BronzeStoragePort` and `SilverStoragePort` ABCs must include `delete_object(key: str) -> None`
- GC failures MUST be logged as `WARNING` but MUST NOT mask the original exception
- GC is **best-effort** — callers should never depend on GC succeeding
- The storage lib's `ObjectStorage.delete(bucket, key)` raises `ObjectNotFoundError` on missing keys;
  wrap in `try/except` to handle race conditions

**Affected services**: S4 (bronze MinIO after fetch), S5 (silver MinIO after article processing)

Enforced by:
- `services/content-ingestion/tests/unit/application/test_minio_gc.py`
- `services/content-store/tests/unit/infrastructure/test_minio_gc.py`

---

## 5. libs/observability — Canonical Observability Pattern

**Package**: `observability` · **Path**: `libs/observability/`
**Full API reference**: `docs/libs/observability.md`
**Gold-standard reference**: `services/content-ingestion/src/content_ingestion/app.py`

> Every service MUST follow this exact pattern. No exceptions, no try/except wrappers around
> observability init, no defensive `getattr`. If observability fails to initialize, the service
> should crash loudly at startup — not silently degrade.

### 5.1 Mandatory config fields

Every service's `config.py` MUST include these four fields:

```python
# services/{service}/src/{service}/config.py
class Settings(BaseSettings):
    # ... other fields ...

    # ── Observability (STANDARDS.md §5.1 — mandatory in every service) ──
    service_name: str = "service-name"   # kebab-case, matches Docker service name
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""
```

### 5.2 Observability init — split between `create_app()` and `lifespan`

Starlette forbids `app.add_middleware()` after the application has started. Therefore:
- **Middleware registration** (`add_prometheus_middleware`, `add_otel_middleware`, `RequestIdMiddleware`) → `create_app()`
- **Configuration** (`configure_logging`, `configure_tracing`) → `lifespan()` (runs at startup, before traffic)

```python
# services/{service}/src/{service}/app.py
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from observability import configure_logging, get_logger          # type: ignore[import-untyped]
from observability.metrics import add_prometheus_middleware, create_metrics  # type: ignore[import-untyped]
from observability.tracing import add_otel_middleware, configure_tracing    # type: ignore[import-untyped]

from {service}.config import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    # 1. LOGGING — always first, before any other code logs anything
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("{service}.app")

    # 2. TRACING config — conditional on otlp_endpoint (middleware already in create_app)
    if settings.otlp_endpoint:
        configure_tracing(
            service_name=settings.service_name,
            otlp_endpoint=settings.otlp_endpoint,
        )

    # 3+ Other infrastructure (DB, Valkey, storage, Kafka, etc.)
    log.info("service_started", service=settings.service_name)
    yield
    log.info("service_stopped", service=settings.service_name)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="service-name", lifespan=lifespan)
    app.state.settings = settings

    # Middleware — MUST be registered in create_app, before app starts
    app.add_middleware(RequestIdMiddleware)
    metrics = create_metrics(service_name=settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics

    # ... include routers ...
    return app
```

**Critical rules**:
- `configure_logging()` is ALWAYS first in lifespan — before any `get_logger()` call
- `create_metrics()` + `add_prometheus_middleware(app, metrics)` — in `create_app()`, BOTH args required
- `add_otel_middleware(app)` — always registered in `create_app()` (safe even without tracing config)
- `configure_tracing()` uses `otlp_endpoint=` parameter (NOT `endpoint=`) — in `lifespan()`
- Direct `settings.otlp_endpoint` access — NO `getattr` defensive coding
- NO try/except around observability init — let startup crash on failure
- Starlette constraint: NEVER call `app.add_middleware()` inside `lifespan()` — it will raise `RuntimeError`

### 5.3 Request-ID middleware (in `create_app()`, mandatory)

Every service MUST propagate `X-Request-ID` through the request lifecycle and bind it to the
structlog context. Register the middleware in `create_app()`:

```python
import re
import structlog.contextvars
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, Response

_VALID_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9\-]{1,64}$")

class RequestIdMiddleware(BaseHTTPMiddleware):
    """Propagate X-Request-ID through the request lifecycle.

    Validates the incoming header: only alphanumeric + hyphens, max 64 chars.
    Invalid or missing values are replaced with a fresh ULID.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        import common.ids

        raw_id = request.headers.get("X-Request-ID", "")
        request_id = raw_id if _VALID_REQUEST_ID_RE.match(raw_id) else common.ids.new_ulid()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = str(request_id)
        structlog.contextvars.clear_contextvars()
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="service-name", lifespan=lifespan)
    app.state.settings = settings or Settings()
    app.add_middleware(RequestIdMiddleware)
    # ... include routers ...
    return app
```

**Rules**:
- Use `BaseHTTPMiddleware` class pattern, NOT inline `@app.middleware("http")` decorator
- **Validate** incoming `X-Request-ID`: only `[a-zA-Z0-9-]`, max 64 chars — prevents log injection and header manipulation
- Generate ULID (not UUID) for missing or invalid request IDs: `common.ids.new_ulid()`
- Clear contextvars after response to prevent cross-request leakage

### 5.4 Health endpoints — real checks, not stubs

All services MUST implement three endpoints in a dedicated route file
(`services/{service}/src/{service}/api/routes/health.py`):

| Endpoint | Purpose | Response |
|----------|---------|----------|
| `GET /healthz` | Liveness probe | Always `{"status": "ok"}` (200) |
| `GET /readyz` | Readiness probe | Probes DB, Valkey, storage; 503 if degraded |
| `GET /metrics` | Prometheus scrape | `prometheus_client.generate_latest()` |

```python
import json
import prometheus_client
from fastapi import APIRouter, Request, Response
from sqlalchemy import text
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter()
_log = get_logger(__name__)  # type: ignore[no-any-return]

@router.get("/healthz")
async def healthz() -> dict:
    """Liveness probe — returns 200 if process is running."""
    return {"status": "ok"}

@router.get("/readyz")
async def readyz(request: Request) -> Response:
    """Readiness probe — returns 200 only when all dependencies are reachable."""
    checks: dict[str, str] = {}
    ok = True

    # Database check
    try:
        async with request.app.state.session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        _log.warning("readyz_database_check_failed", exc_info=True)
        checks["database"] = "error"
        ok = False

    # Add Valkey, MinIO, etc. checks per service
    status_code = 200 if ok else 503
    return Response(
        content=json.dumps({"status": "ok" if ok else "degraded", **checks}),
        status_code=status_code,
        media_type="application/json",
    )

@router.get("/metrics")
async def metrics() -> Response:
    """Prometheus metrics endpoint."""
    data = prometheus_client.generate_latest()
    return Response(content=data, media_type=prometheus_client.CONTENT_TYPE_LATEST)
```

### 5.5 Getting a logger in any module

```python
# ✅ CORRECT — use observability wrapper
from observability import get_logger  # type: ignore[import-untyped]
logger = get_logger(__name__)  # type: ignore[no-any-return]

# ❌ FORBIDDEN — bypasses centralized configuration
import structlog
logger = structlog.get_logger(__name__)   # wrong — use observability

import logging
logger = logging.getLogger(__name__)      # wrong — use observability
```

**Structured log fields**:
- Use keyword arguments for all structured data: `logger.info("event_name", key=value, ...)`
- Event name is the first positional arg, always `snake_case`.
- Never interpolate variables into the message string: `logger.info(f"fetched {n} articles")` →
  `logger.info("articles_fetched", count=n)`

### 5.6 Custom metrics (optional, per-service)

Custom metrics live in `services/{service}/src/{service}/infrastructure/metrics/prometheus.py`.

**Naming convention**:
- Counter: `{s_code}_{subsystem}_{action}_total` → `s4_fetcher_articles_fetched_total`
- Histogram: `{s_code}_{subsystem}_{thing}_duration_seconds` → `s5_dedup_duration_seconds`
- Gauge: `{s_code}_{subsystem}_{thing}` → `s4_outbox_pending_events`
- Labels: lowercase `snake_case` keys: `source_type`, `status`, `error_class`

**Gauge polling**: background task in lifespan, 30s default interval (see S4 `_metrics_poller`).

### 5.7 Docker env vars (mandatory in every `configs/docker.env`)

```env
{PREFIX}_LOG_LEVEL=INFO
{PREFIX}_LOG_JSON=true
{PREFIX}_OTLP_ENDPOINT=
```

Where `{PREFIX}` matches the service's `env_prefix` (e.g., `CONTENT_INGESTION_`, `PORTFOLIO_`).

### 5.8 pyproject.toml (mandatory dependency)

Every service MUST declare `observability` as an explicit dependency:

```toml
dependencies = [
    # ... other deps ...
    "observability",
]
```

Direct `prometheus-client` or `structlog` imports are only needed if custom metrics use them directly.

---

## 6. libs/contracts — Canonical Event Payloads

**Package**: `contracts` · **Path**: `libs/contracts/`
**Full API reference**: `docs/libs/contracts.md`

### 6.1 Use canonical model types for event payloads

```python
# ✅ CORRECT — use canonical models from contracts
from contracts import CanonicalRawArticleEvent, CanonicalStoredArticleEvent

event = CanonicalRawArticleEvent(
    event_id=common.ids.new_uuid7_str(),
    schema_version=1,
    occurred_at=common.time.to_iso8601(common.time.utc_now()),
    doc_id=str(doc_id),
    source_type=source_type.value,
    minio_bronze_key=str(minio_key),
    content_hash=url_hash,
    published_at=common.time.to_iso8601(published_at) if published_at else None,
    is_backfill=is_backfill,
)

# ❌ WRONG — raw dict without contracts validation
payload = {
    "event_id": str(uuid.uuid4()),   # wrong: uses uuid4, not common.ids
    "doc_id": doc_id,
    "source_type": "eodhd",
}
```

---

## 7. FastAPI Application Structure

### 7.1 `app.py` — factory function + lifespan only

`app.py` must contain only:
1. The `lifespan` context manager (infrastructure wiring)
2. The `create_app()` factory function
3. Middleware registration

It must NOT contain route definitions, business logic, or direct SQL queries.

```python
# services/my-service/src/my_service/app.py
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from observability.logging import configure_logging, get_logger
from observability.metrics import create_metrics, add_prometheus_middleware
from observability.tracing import configure_tracing, add_otel_middleware
from messaging.valkey import create_valkey_client_from_url
from storage.factory import build_object_storage

from my_service.config import Settings
from my_service.api.routes import health, articles  # import routers
from my_service.infrastructure.db.session import create_session_factory
from my_service.infrastructure.messaging.outbox.dispatcher import MyServiceOutboxDispatcher

if TYPE_CHECKING:
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    app.state.settings = settings

    # 1. Logging — always first
    configure_logging(service_name="my-service", level=settings.log_level, json=settings.log_json)
    logger = get_logger("my_service.app")

    # 2. Metrics
    metrics = create_metrics(service_name="my-service")
    add_prometheus_middleware(app, metrics)
    app.state.metrics = metrics

    # 3. Tracing (optional — skip if no OTLP endpoint)
    if settings.otlp_endpoint:
        configure_tracing(service_name="my-service", otlp_endpoint=settings.otlp_endpoint)
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
    )
    app.state.storage = storage

    logger.info("service_started")
    yield

    # Shutdown
    await valkey.close()
    logger.info("service_stopped")
    # NOTE: Outbox dispatcher and consumers run as standalone processes (R22/§14).
    # Do NOT start asyncio.create_task() for them here — see §14 for entry point conventions.


def create_app() -> FastAPI:
    app = FastAPI(
        title="My Service",
        version="1.0.0",
        lifespan=lifespan,
    )
    from my_service.app import RequestIdMiddleware
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router, tags=["health"])
    app.include_router(articles.router, prefix="/api/v1", tags=["articles"])
    return app
```

### 7.2 Middleware order (top to bottom = outermost to innermost)

1. `RequestIdMiddleware` — bind `request_id` to structlog context
2. `PrometheusMiddleware` — instrument all requests (added by `add_prometheus_middleware`)
3. `OTelMiddleware` — tracing spans (added by `add_otel_middleware`, optional)
4. `CORSMiddleware` — only in API-facing services (api-gateway, rag-chat)

---

## 8. Configuration (pydantic-settings)

### 8.1 Field naming — `snake_case` with `env_prefix`

```python
# ✅ CORRECT
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CONTENT_INGESTION_",   # env var: CONTENT_INGESTION_DB_URL
        env_file=".env",                   # canonical — NOT "configs/dev.local.env"
        env_file_encoding="utf-8",
        extra="ignore",                    # silently ignore unknown env vars
    )

    db_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/content_ingestion_db"
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_schema_registry_url: str = "http://localhost:8081"
    kafka_schema_registry_basic_auth: str = ""
    kafka_outbox_topic: str = "content.article.raw.v1"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "worldview-bronze"
    minio_secure: bool = False
    valkey_url: str = "redis://localhost:6379"
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""
    outbox_poll_interval_seconds: float = 5.0
    outbox_lease_seconds: int = 30
    outbox_batch_size: int = 100
    outbox_max_attempts: int = 5

# ❌ FORBIDDEN — plain dict instead of SettingsConfigDict
class Settings(BaseSettings):
    model_config = {
        "env_prefix": "MY_SERVICE_",
        "env_file": "configs/dev.local.env",  # wrong path — use ".env"
    }   # wrong — use SettingsConfigDict(...) for type safety and IDE support

# ❌ FORBIDDEN — SCREAMING_SNAKE_CASE field names
class Settings(BaseSettings):
    KAFKA_BOOTSTRAP_SERVERS: str = "..."  # wrong — env vars are set by env_prefix
    DB_URL: str = "..."                   # wrong
```

**Every service's `env_prefix`**:

| Service | `env_prefix` |
|---------|-------------|
| S1 Portfolio | `PORTFOLIO_` |
| S2 Market-Ingestion | `MARKET_INGESTION_` |
| S3 Market-Data | `MARKET_DATA_` |
| S4 Content-Ingestion | `CONTENT_INGESTION_` |
| S5 Content-Store | `CONTENT_STORE_` |
| S6 NLP-Pipeline | `NLP_PIPELINE_` |
| S7 Knowledge-Graph | `KNOWLEDGE_GRAPH_` |
| S10 Alert | `ALERT_` |
| API-Gateway | `API_GATEWAY_` |
| RAG-Chat | `RAG_CHAT_` |

### 8.2 Settings instantiation — ALWAYS in `create_app()`, never at module level

```python
# ✅ CORRECT — instantiated inside lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()    # ← constructed here
    app.state.settings = settings
    ...

# ❌ FORBIDDEN — module-level instantiation makes tests un-overridable
settings = Settings()   # breaks test fixtures that need to set env vars
```

**Accessing settings in routes/dependencies**:
```python
from fastapi import Request

def get_settings(request: Request) -> Settings:
    return request.app.state.settings
```

### 8.3 Required settings fields for every service

Every service **must** define these fields in its `Settings` class:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `log_level` | `str` | `"INFO"` | structlog log level |
| `log_json` | `bool` | `True` | JSON vs console output |
| `otlp_endpoint` | `str` | `""` | OpenTelemetry collector URL (empty = disabled) |

---

## 9. Error Handling

### 9.1 Domain exception hierarchy (R21)

Every service **must** define `DomainError` as the root exception in
`domain/errors.py` (preferred) or `domain/exceptions.py`:

```python
# services/my-service/src/my_service/domain/errors.py
class DomainError(Exception):
    """Base exception for all my-service domain errors (R21 canonical name)."""


# Optional descriptive alias — define as a SUBCLASS, not an assignment alias,
# so that architecture tests can trace the inheritance chain via AST.
class MyServiceError(DomainError):
    """Descriptive alias preserved for readability within this service."""


class EntityNotFoundError(MyServiceError):
    def __init__(self, entity_type: str, entity_id: Any) -> None:
        super().__init__(f"{entity_type} {entity_id!r} not found")
        self.entity_type = entity_type
        self.entity_id = entity_id

class ValidationError(MyServiceError):
    pass

class ConfigurationError(MyServiceError):
    """Raised when required configuration is missing or invalid."""
    pass
```

**Why the class-based alias matters**: Architecture tests use AST analysis to verify
that all exception classes inherit from `DomainError`. A simple assignment
`MyServiceError = DomainError` is invisible to AST class-def scanning and causes
subclasses like `EntityNotFoundError(MyServiceError)` to fail the check.
Always use `class MyServiceError(DomainError): ...`.

Enforced by `tests/architecture/test_domain_error_enforcement.py`.

### 9.2 HTTP status mapping — `api/error_mapping.py`

```python
# services/my-service/src/my_service/api/error_mapping.py
from fastapi import Request
from fastapi.responses import JSONResponse
from my_service.domain.exceptions import EntityNotFoundError, ValidationError, ConfigurationError

def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(EntityNotFoundError)
    async def not_found_handler(request: Request, exc: EntityNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(ValidationError)
    async def validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": str(exc)})

    @app.exception_handler(ConfigurationError)
    async def config_error_handler(request: Request, exc: ConfigurationError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"error": "Service misconfigured"})
```

Register in `create_app()`:
```python
def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    from my_service.api.error_mapping import register_exception_handlers
    register_exception_handlers(app)
    return app
```

---

## 10. Testing Conventions

### 10.1 Unit tests

- **Location**: `tests/unit/`
- **Framework**: `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"`)
- **No real I/O**: mock all database, Kafka, and external HTTP calls
- **No `__init__.py`** in test directories — causes `pytest-asyncio 0.23` package resolution bug
- **Async test functions**: mark with `async def test_…()` — `asyncio_mode=auto` handles the rest

### 10.2 Integration tests

- **Location**: `tests/integration/`
- **Use real dependencies via docker-compose**: PostgreSQL, Kafka, Valkey, MinIO
- **Fixtures**: use `pytest-asyncio` session-scoped fixtures for DB setup/teardown
- **Isolation**: each test runs in a transaction rolled back at the end

### 10.3 Contract tests

- **Location**: `tests/contract/`
- **Purpose**: verify S1 API shape, Avro schema compatibility
- **Tool**: `pytest-httpserver` for HTTP contract tests; `fastavro` for schema evolution checks

### 10.4 Quality gates (mandatory before every PR)

```bash
# From the service directory:
make test           # pytest: unit + integration (all must pass, no skips)
ruff check src/     # zero violations
ruff format --check src/
mypy src/           # zero errors
```

---

## 11. Anti-Patterns — What NOT To Do

The following patterns are **explicitly forbidden** and constitute review blockers:

| Anti-pattern | Why | What to do instead |
|-------------|-----|-------------------|
| `uuid.uuid4()` in service code | Bypasses `common.ids`, breaks type safety | `common.ids.new_uuid7()` |
| `datetime.now()` or `datetime.utcnow()` | Produces naive datetime | `common.time.utc_now()` |
| `import aiokafka` in any service | Wrong Kafka client | `messaging.kafka.*` via `confluent-kafka` |
| `import redis.asyncio` or `import aioredis` | Bypasses shared client, no pooling | `messaging.valkey.ValkeyClient` |
| `import minio` or `import boto3` directly | Custom adapters break when storage lib evolves | `storage.factory.build_object_storage()` |
| `import structlog` directly | Bypasses `configure_logging()` | `observability.logging.get_logger()` |
| `settings = Settings()` at module level | Un-testable; breaks pytest fixtures | Instantiate in `create_app()` / lifespan |
| Avro schema as Python dict | Can't be registered, evolved, or versioned | `.avsc` file in `infrastructure/messaging/schemas/` |
| Custom outbox loop (while True + aiokafka) | No lease, no backoff, race condition | `BaseOutboxDispatcher` subclass |
| Separate `dlq_events` table | Splits operational tooling across two tables | `status = 'dead_letter'` column |
| `SCREAMING_SNAKE_CASE` settings fields | Inconsistent with all other services | `snake_case` + `env_prefix` |
| `model_config = {...}` plain dict | No type checking; missing `extra="ignore"`; IDE cannot autocomplete | `SettingsConfigDict(env_prefix=..., env_file=".env", extra="ignore")` |
| `env_file="configs/dev.local.env"` | Non-canonical path; breaks Docker/CI where `.env` is standard | `env_file=".env"` |
| Missing `log_json` field in Settings | `configure_logging()` requires it; cannot switch JSON/console output | Add `log_json: bool = True` to every service `Settings` class |
| Health endpoints returning `{"status": "ok"}` without checks | Hides dependency failures | Real DB/Kafka/Valkey checks |
| Route logic in `app.py` | Violates single-responsibility | Routes in `api/routes/` |
| Infrastructure imports in domain layer | Breaks hexagonal architecture | Use ports/protocols |
| `else: await self.commit()` in `__aexit__` | Silent writes on every clean context exit; double-commit undetectable (R26) | Option B: `__aexit__` only rolls back on exception; every mutating use case calls `await uow.commit()` explicitly — see §17 |
| `from __future__ import annotations` missing | Lazy evaluation needed for `TYPE_CHECKING` pattern | Add to every file using `if TYPE_CHECKING` |
| `print()` statements | Not structured, not queryable | `logger.info(...)` with keyword args |
| Per-request auth (`user_id`, `tenant_id`, `internal_jwt`, `entity_context`) in singleton `__init__` | Singleton holds `None` forever after first request → silent auth strip / cross-tenant leak risk (R30, BP-406) | Split into `<Class>Factory` (singleton) + `<Class>` (per-request); factory exposes `for_request(*, user_id, tenant_id, jwt, entity_context, ...) -> Class` |
| Per-tool `trust_weight` field in `capability_manifest.yaml` (or any other duplicate ranking-weight table) | Two sources of truth drift over time → ranking quality differs between tool-use path and classical path; tied to BP-* drift class | Reference `source_type` only in manifests; let `TrustScorer` (libs/contracts `SOURCE_AUTHORITY` × recency_decay × corroboration × extraction_confidence) compute final weight at retrieval time |
| Pydantic `BaseModel` for domain entities | Convention drift (worldview domain layer = frozen dataclasses); 5–10× slower construction; pydantic stays in API layer | `@dataclass(frozen=True, kw_only=True)` for domain; `BaseModel` only in `api/schemas.py` |
| Hand-rolled `is_duplicate` / `mark_processed` per consumer (returns `False` / `pass` or ad-hoc Valkey logic) | Divergent dedup behaviour; missing at-least-once fallback; inconsistent TTL policies; dialect drift across services (R9, BP-415) | `ValkeyDedupMixin` from `libs/messaging.kafka.consumer.dedup`; enforced by `tests/architecture/test_consumer_dedup_mixin_enforcement.py` (CONSUMER-DEDUP-001) |

---

## 11.1 Ranking trust weights — single source of truth (PLAN-0079)

**Standard**: ranking trust is computed per-item at retrieval time by `TrustScorer` from four named factors. There is one source of truth for source authority — the `SOURCE_AUTHORITY` table in `libs/contracts`.

```
trust(item) = w_source       · source_authority(item)            # SOURCE_AUTHORITY table
            ·                  recency_decay(item, now)          # exp(-Δdays / τ_source)
            · w_corroboration · corroboration_factor(item)       # 1 - exp(-evidence_count / 3)
            · w_extraction   · extraction_confidence(item)       # GLiNER/relation/claim confidence
```

**Hard rules**:

- The flat `DEFAULT_TRUST_WEIGHTS` map (legacy, in `services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py`) is renamed to `SOURCE_AUTHORITY` and lifted into `libs/contracts`. Once PLAN-0079 ships, no service may declare its own per-source-type weight table.
- `capability_manifest.yaml` entries (PLAN-0067 R29) reference `source_type` for tools that produce `RetrievedItem`s. They MUST NOT carry a `trust_weight` field. `TrustScorer` looks up authority via the source_type.
- Tool-handler authors who introduce a new `source_type` value extend `SOURCE_AUTHORITY` in the same PR, with a justifying review comment for the chosen authority value (cite a comparable existing entry: news, filing, transcript, social, …).
- Eval gate: any change to `SOURCE_AUTHORITY` weights, the `TrustScorer` formula, or the four `w_*` / `τ_*` knobs MUST run the PLAN-0063 60-query golden eval and pass within 0.03 NDCG@10 of the prior baseline before merge.

**Why this matters now**: without a single source of truth, a future PLAN that adds a new `source_type` (e.g., `polymarket_clob`) would set its own ad-hoc weight in either the manifest, the orchestrator, or a tool handler — and quietly diverge from the ranking semantics every other source uses. With `TrustScorer` + `SOURCE_AUTHORITY`, every ranking decision is visible and auditable from one place.

---

## 11.2 Per-request auth/scope context — factory pattern (R30)

**Standard**: any class that needs request-scoped state (`user_id`, `tenant_id`, `internal_jwt`, `entity_context`, or any field that varies per HTTP request) is built by a singleton factory's `for_request(...)` method, not via constructor injection of the per-request fields into the class itself.

**Pattern**:

```python
# libs/.../tool_executor.py

class ToolExecutorFactory:                  # singleton — wired into DI container
    """Holds shared collaborators (registry, S3 client, S6 client, ...).
    Builds a fresh ToolExecutor for each HTTP request via for_request()."""

    def __init__(self, registry: ToolRegistry, s3: S3Port, s6: S6Port,
                 s7: S7Port, s1: S1Port) -> None:
        self._registry, self._s3, self._s6 = registry, s3, s6
        self._s7, self._s1 = s7, s1

    def for_request(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        internal_jwt: str,
        entity_context: EntityContext | None = None,
    ) -> ToolExecutor:
        return ToolExecutor(
            registry=self._registry,
            s3=self._s3, s6=self._s6, s7=self._s7, s1=self._s1,
            user_id=user_id, tenant_id=tenant_id,
            internal_jwt=internal_jwt, entity_context=entity_context,
        )

class ToolExecutor:                          # per-request — short-lived
    """One per HTTP request. Auth + scope bound at construction;
    every execute() call inherits them automatically."""

    def __init__(self, *, registry, s3, s6, s7, s1,
                 user_id, tenant_id, internal_jwt, entity_context) -> None: ...

    async def execute(self, tool_call: ToolUseBlock) -> RetrievedItem | None: ...
```

**Route handler usage**:

```python
# services/rag-chat/.../api/routes/chat.py

@router.post("/chat")
async def chat(req: ChatRequest, principal: Principal = Depends(...)):
    executor = tool_executor_factory.for_request(
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        internal_jwt=principal.internal_jwt,
        entity_context=req.entity_context,  # may be None
    )
    # executor lives only for this request; auth + scope already bound
    ...
```

**Hard rules**:

- A class taking `Optional[user_id|tenant_id|jwt]` in `__init__` is a review blocker (R30). Either it's stateless and shouldn't carry it, or it's request-scoped and needs a factory.
- Tools that intend to act on the scoped entity (`search_documents`, `get_entity_graph`, `get_entity_narrative`, etc.) read `self._entity_context` and auto-inject `entity_ids = [entity_context.entity_id]` into the underlying port call. The LLM cannot override this when scope is set — that's the whole point of binding it at executor construction.
- Tools that act cross-entity (`compare_entities`, `screen_universe`, `get_market_movers`) check `if self._entity_context is not None` and refuse / require explicit operands.

**See also**: BP-406 (the silent failure mode this standard prevents), PLAN-0067 §0 (where this pattern was introduced after `/investigate` 2026-05-07), PLAN-0080/0081/0082 (downstream tool plans that depend on this contract).

---

## Appendix: Compliance Checklist

Use this checklist in every PR that adds or modifies a service:

- [ ] Directory structure follows §1.1 canonical layout
- [ ] No `uuid.uuid4()` calls in service code (§2.1)
- [ ] No `datetime.now()` / `datetime.utcnow()` in service code (§2.2)
- [ ] Dispatcher extends `BaseOutboxDispatcher` (§3.2)
- [ ] Outbox repo implements `OutboxRepositoryProtocol` (§3.3)
- [ ] Outbox table has all canonical columns including lease columns (§3.4)
- [ ] Status values are `pending / processing / delivered / dead_letter` (§3.5)
- [ ] No separate `dlq_events` table (§3.6)
- [ ] Avro schemas in `.avsc` files (§3.7)
- [ ] Valkey via `messaging.valkey.ValkeyClient` (§3.8)
- [ ] MinIO via `storage.factory.build_object_storage()` (§4.1)
- [ ] `configure_logging()` called first in lifespan (§5.1)
- [ ] `get_logger()` from `observability.logging` (§5.1)
- [ ] `create_metrics()` + `add_prometheus_middleware()` in lifespan (§5.2)
- [ ] `/healthz` and `/readyz` with real dependency checks (§5.4)
- [ ] `RequestIdMiddleware` registered (§5.5)
- [ ] Settings use `SettingsConfigDict(...)` not plain dict (§8.1)
- [ ] `env_file=".env"` (not `configs/dev.local.env`) and `extra="ignore"` set (§8.1)
- [ ] Settings use `snake_case` field names + `env_prefix` (§8.1)
- [ ] Settings instantiated in lifespan, not at module level (§8.2)
- [ ] `log_level`, `log_json`, `otlp_endpoint` fields present in Settings (§8.3)
- [ ] Domain exception hierarchy in `domain/exceptions.py` (§9.1)
- [ ] HTTP error mapping in `api/error_mapping.py` (§9.2)
- [ ] No `__init__.py` in test directories (§10.1)
- [ ] All quality gates pass: `make test`, `ruff check`, `mypy` (§10.4)
- [ ] Structure validator passes: `python3 scripts/structure_checks/check_service_structure.py --strict` (§13.1)
- [ ] Import guard passes: `python3 scripts/import_guards/check_import_guards.py --strict` (§13.2)
- [ ] Architecture tests pass: `pytest tests/architecture` (§13.3)

---

## 12. Platform Rules (R1–R24)

These rules apply to every contributor (human and AI agent). They are non-negotiable.

### Testing

**R1 — MUST add or update tests for every behavior change**
Every new function, endpoint, consumer, or domain rule needs at least one unit test.
Integration tests are required for database operations and Kafka flows. Untested code is unknown code.

**R2 — MUST run `scripts/lint.sh` and `scripts/test.sh` before committing**
CI enforces both, but catching failures locally saves time and CI minutes. Broken code must never reach `main`.

### Documentation

**R3 — MUST update docs when behavior or contracts change**
Stale docs actively mislead. If you change an API, event schema, or internal workflow, update the corresponding doc in `docs/services/`, `docs/libs/`, or `docs/MASTER_PLAN.md` in the same PR.

**R4 — MUST write an ADR before adding a new service or major architectural change**
Architectural decisions are expensive to reverse. Use `docs/architecture/decisions/ADR_TEMPLATE.md`.

### Contracts

**R5 — MUST version Avro schemas and ensure forward compatibility**
Kafka consumers deploy independently. Breaking schema changes break all consumers simultaneously. Rules:
- Add new fields with **default values** only
- Never remove or rename existing fields
- Bump `schema_version` in the event envelope
- Run `scripts/gen-contracts.sh` to validate compatibility before merging

**R6 — MUST version REST API paths for breaking changes**
Non-breaking additions (new endpoints, new optional fields) are fine. Breaking changes require a new version path (`/api/v2/...`) and a deprecation period.

### Architecture

**R7 — MUST NOT access another service's database directly**
Database ownership is the foundation of microservice independence. Communicate via Kafka events (async) or REST API (synchronous).

**R8 — MUST NOT perform dual writes (DB + Kafka in separate transactions)**
Use the **transactional outbox pattern** from `libs/messaging`: write the event to `outbox_events` in the same DB transaction, then let the dispatcher publish to Kafka.

**R9 — MUST make Kafka consumers idempotent**
Kafka guarantees at-least-once delivery. Every consumer must:
- Check `event_id` against a processed-events table before processing
- Use upsert (`INSERT ON CONFLICT`) for materializations
- Be safe to re-run on the same event

**R10 — MUST use UUIDv7 for all entity IDs**
UUIDv7 is time-sortable, globally unique, and embeds a timestamp. Never use auto-increment integers or UUIDv4. See §2.1.

**R11 — MUST enforce UTC-only timestamps**
All timestamps are UTC timezone-aware. Naive datetimes raise `ValueError` via `libs/common`. DB columns use `TIMESTAMPTZ`. JSON uses ISO-8601 with `Z` suffix. See §2.2.

**R12 — MUST use claim-check pattern for large Kafka payloads**
Kafka is optimized for small messages (~1KB). Store large payloads in MinIO and send a pointer event with `(bucket, key, content_type, etag)`.

### Security

**R13 — MUST NOT embed secrets in code or config files**
Use environment variables loaded via `pydantic-settings`. Use `configs/dev.local.env.example` as a template (never the actual `.env`). Use GitHub Actions secrets for CI.

**R14 — MUST sanitize logs — never log secrets, API keys, tokens, or PII**
Logs are stored and accessible broadly. Use the log sanitization pattern from `libs/observability` to strip `sk-*`, `Bearer *`, `api_key=*` patterns.

**R15 — MUST validate and sanitize all external input**
Use Pydantic models for request validation, domain allowlists for URLs, and input length limits for all user-facing text fields.

**R27 — All internal service-to-service API endpoints MUST enforce `X-Internal-Token`**
Any endpoint that is called only by other platform services (not by end users or the frontend) MUST
require the `X-Internal-Token` header validated via `verify_internal_token` (or equivalent service-local
implementation using `hmac.compare_digest`).  The token must be:
- A strong random secret (≥32 bytes) stored in `INTERNAL_SERVICE_TOKEN` env var
- **`SecretStr`** in pydantic-settings to prevent accidental logging
- Validated with `hmac.compare_digest` to prevent timing attacks
Enforcement pattern (established in S3 market-data D-02): add `_auth: InternalAuthDep = None` to each
internal endpoint signature.  In unit tests, override `verify_internal_token` via
`app.dependency_overrides`.

### Process

**R16 — MUST NOT add a new microservice without an ADR**
Each microservice adds operational overhead. The decision must be deliberate and documented.

**R17 — CI MUST pass before merge to main**
`main` is the deployable branch. CI runs lint, type-check, unit tests, contract tests, structure checks, import guards, and architecture tests. No exceptions.

**R18 — MUST follow the branching convention**
- Feature branches: `feat/<short-description>`
- Bug fixes: `fix/<short-description>`
- Docs: `docs/<short-description>`
- Refactors: `refactor/<short-description>`

### Rules Summary Table

| Rule | Category | Constraint |
|------|----------|------------|
| R1 | Testing | MUST |
| R2 | Testing | MUST |
| R3 | Documentation | MUST |
| R4 | Documentation | MUST |
| R5 | Contracts | MUST |
| R6 | Contracts | MUST |
| R7 | Architecture | MUST NOT |
| R8 | Architecture | MUST NOT |
| R9 | Architecture | MUST |
| R10 | Architecture | MUST |
| R11 | Architecture | MUST |
| R12 | Architecture | MUST |
| R13 | Security | MUST NOT |
| R14 | Security | MUST |
| R15 | Security | MUST |
| R16 | Process | MUST NOT |
| R17 | Process | MUST |
| R18 | Process | MUST |
| R19 | Testing | MUST NOT |
| R20 | Architecture | MUST |
| R21 | Architecture | MUST |
| R22 | Infrastructure | MUST |
| R23 | Infrastructure | MUST |
| R24 | Infrastructure | MUST NOT |
| R25 | Architecture | MUST NOT |
| R26 | Infrastructure | MUST NOT |
| R27 | Security | MUST |
| R28 | Contracts | MUST | (Avro on the wire — see §3.7.1) |
| R29 | Architecture | MUST | (capability manifest sync) |
| R30 | Architecture | MUST NOT | (per-request auth in singleton — see §11.2) |

---

## 13. Automated Enforcement — CI Gates

Three automated gates run in CI on every PR. All three must pass before merging to `main`.

### 13.1 Service Structure Validator (`STR-*` rules)

**Script**: `scripts/structure_checks/check_service_structure.py`
**CI job**: `validate-service-structure`

Validates that every service under `services/` follows the canonical hexagonal layout defined in §1.1.

```bash
# Local run
python3 scripts/structure_checks/check_service_structure.py --strict

# Check specific service only
python3 scripts/structure_checks/check_service_structure.py --strict --services portfolio

# Write machine-readable report
python3 scripts/structure_checks/check_service_structure.py --strict --report-json /tmp/structure.json
```

**Rule reference**:

| Rule ID | What it checks |
|---------|----------------|
| STR-001 | `src/<package>/__init__.py` exists |
| STR-002 | `src/<package>/app.py` exists |
| STR-003 | `src/<package>/config.py` exists |
| STR-004 | `src/<package>/domain/` layer exists (non-scaffolded services) |
| STR-005 | `src/<package>/application/` layer exists (non-scaffolded services) |
| STR-006 | `src/<package>/api/` layer exists (non-scaffolded services) |
| STR-007 | `src/<package>/infrastructure/` layer exists (non-scaffolded services) |
| STR-008 | `infrastructure/messaging/schemas/` exists for Kafka-enabled services |
| STR-009 | `tests/unit/` directory exists |
| STR-010 | `tests/integration/` directory exists |
| STR-011 | `tests/contract/` directory exists |
| STR-012 | `alembic/versions/` exists for services with `alembic.ini` |
| STR-013 | `infrastructure/messaging/kafka/` does not exist (unless explicitly allowlisted) |

**Exceptions**: Documented in `scripts/structure_checks/exceptions.yaml` (expiry-gated; expired exceptions fail CI).

**Scaffolded services** (STR-004 to STR-008 relaxed): `content-store`, `nlp-pipeline`, `knowledge-graph`, `rag-chat`, `alert`.

### 13.2 Import Guard Engine (`IG-*` rules)

**Script**: `scripts/import_guards/check_import_guards.py`
**CI job**: `import-guards`

AST-based scanner that detects forbidden import patterns in service `src/` code.

```bash
# Local run
python3 scripts/import_guards/check_import_guards.py --strict

# Update baseline (after intentionally accepting existing violations)
python3 scripts/import_guards/check_import_guards.py --update-baseline

# Check specific service
python3 scripts/import_guards/check_import_guards.py --strict --services market-ingestion
```

**Rule reference**:

| Rule ID | Forbidden pattern | Correct alternative |
|---------|-------------------|---------------------|
| IG-COMMON-001 | `from uuid import uuid4`, `uuid.uuid4()` | `common.ids.new_uuid7()` — §2.1 |
| IG-COMMON-002 | `datetime.utcnow()`, `datetime.now()` (naive) | `common.time.utc_now()` — §2.2 |
| IG-MSG-001 | `import aiokafka`, `import aiokafka.*` | `messaging.kafka.*` — §3.1 |
| IG-MSG-002 | `import aioredis`, `from redis.asyncio import Redis` | `messaging.valkey.ValkeyClient` — §3.8 |
| IG-STORAGE-001 | `import minio`, `from minio import Minio` | `storage.factory.build_object_storage()` — §4.1 |
| IG-STORAGE-002 | `import boto3`, `from boto3 import *` | `storage.ObjectStorageClient` — §4.1 |
| IG-OBS-001 | `from logging import getLogger`, `print()` | `observability.logging.get_logger()` — §5.1 |
| IG-LAYER-001 | Domain imports from application/api/infrastructure | Use ports/protocols — §1.2 |

**Baseline file**: `scripts/import_guards/baseline.json` — tracks pre-existing violations. Net-new violations always fail CI; baselined violations are allowed but must trend to zero.

**Allowlist**: `scripts/import_guards/allowlist.yaml` — per-file exceptions (e.g. shared lib internals, migration files).

### 13.3 Architecture Test Suite (`ARCH-*` / `LAYER-*` rules)

**Location**: `tests/architecture/`
**CI job**: `architecture-tests`
**Runner**: `pytest tests/architecture -v`

Pytest-based tests that enforce architectural invariants using AST analysis and filesystem inspection. No infrastructure required (no DB, Kafka, etc.).

```bash
# Local run
pytest tests/architecture -v --tb=short

# Run a specific test file
pytest tests/architecture/test_layer_boundaries.py -v
```

**Test modules**:

| File | Rules enforced |
|------|---------------|
| `test_service_structure.py` | Hexagonal layer presence, entry files, test directories |
| `test_layer_boundaries.py` | `LAYER-DOMAIN-PURITY`, `LAYER-APP-ISOLATION` — no wrong-direction imports |
| `test_outbox_dispatcher_contracts.py` | `MSG-DISPATCHER`, `MSG-BASE-CLASS`, `MSG-SCHEMA-ONLY` — dispatcher/schema conventions |
| `test_shared_lib_usage_common.py` | `IG-COMMON-001`, `IG-COMMON-002` at architecture level |
| `test_shared_lib_usage_messaging.py` | `IG-MSG-001`, `IG-MSG-002`, `MSG-DISPATCHER` |
| `test_shared_lib_usage_storage.py` | `IG-STORAGE-001`, `IG-STORAGE-002` |
| `test_shared_lib_usage_observability.py` | `IG-OBS-001` |
| `test_config_patterns.py` | `CFG-SETTINGS-BASE`, `CFG-SETTINGS-CONFIG` |

**Key architectural invariants**:
- `domain/` may not import from `application/`, `api/`, or `infrastructure/`
- `application/` may not import from `api/` or `infrastructure/`
- Every Kafka-enabled mature service must have a `dispatcher.py` extending `BaseOutboxDispatcher`
- Schema directories must contain only `.avsc` files (no Python serialization code)
- Every service `Settings` class must extend `pydantic_settings.BaseSettings`
- `TYPE_CHECKING`-only imports (annotation-only) are exempt from layer boundary checks

### 13.4 Running all gates locally

```bash
# Run all three gates (equivalent to CI)
python3 scripts/structure_checks/check_service_structure.py --strict
python3 scripts/import_guards/check_import_guards.py --strict
pytest tests/architecture -v --tb=short

# Or use the local CI script
bash scripts/ci-local.sh --job validate-service-structure
bash scripts/ci-local.sh --job import-guards
bash scripts/ci-local.sh --job architecture-tests

# Run all gates in sequence
bash scripts/ci-local.sh all
```

### 13.5 Adding exceptions and allowlists

**Structure exceptions** (per-service, expiry-gated):
```yaml
# scripts/structure_checks/exceptions.yaml
exceptions:
  - service: my-service
    rule_id: STR-008
    reason: "Kafka schemas are temporarily at package root; migrating in sprint 4"
    owner: platform
    expires_on: "2026-09-01"   # required — CI fails after expiry
```

**Import guard allowlist** (per-file glob):
```yaml
# scripts/import_guards/allowlist.yaml
allowlist:
  - rule_id: IG-COMMON-001
    path: "services/*/tests/**/*.py"
    reason: "Test factories may use uuid.uuid4() for stub data"
```

---

## 14. Process Topology Standard

> **Rules**: R22 (process separation)
> **Reference implementation**: `services/market-ingestion/`

Services with background processing MUST be decomposed into independent processes. Each process
has its own entry point, signal handling, and connection pool sizing.

### 14.1 Process Types

| Process | Responsibility | Entry Point Pattern | Concurrency |
|---------|---------------|--------------------:|-------------|
| **API** | HTTP request handling (uvicorn) | `python -m <pkg>.app` or `uvicorn <pkg>.app:create_app` | Async — bounded by uvicorn workers |
| **Scheduler** | Evaluate sources/policies, insert task rows | `python -m <pkg>.infrastructure.scheduler.scheduler_main` | Single-threaded, tick-based (60s default) |
| **Worker** | Claim and execute tasks | `python -m <pkg>.infrastructure.workers.worker_main` | Semaphore-bounded (default 4 concurrent) |
| **Dispatcher** | Poll outbox, publish to Kafka | `python -m <pkg>.infrastructure.messaging.outbox.dispatcher_main` | Single-threaded poll loop |
| **Consumer** | Process inbound Kafka events | `python -m <pkg>.infrastructure.messaging.consumers.<type>_consumer_main` | Single-threaded per topic |

### 14.2 Entry Point Pattern

Every process MUST follow this structure:

```python
# <pkg>/infrastructure/workers/worker_main.py  ← standalone entry point

import asyncio
import signal

from <pkg>.config import Settings
from <pkg>.infrastructure.workers.worker import Worker

async def _run_worker() -> None:
    settings = Settings()                          # own Settings instance
    write_factory, read_factory = _build_factories(settings)  # own session factories
    worker = Worker(write_factory, read_factory, settings)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop)  # graceful shutdown

    await worker.run()                             # blocks until stop_event

def main() -> None:
    asyncio.run(_run_worker())

if __name__ == "__main__":
    main()
```

### 14.3 Docker Compose Pattern

Same Dockerfile, different `command` overrides:

```yaml
services:
  content-ingestion-api:
    build: { context: ., dockerfile: services/content-ingestion/Dockerfile }
    command: ["uvicorn", "content_ingestion.app:create_app", "--host", "0.0.0.0", "--port", "8000"]

  content-ingestion-scheduler:
    build: { context: ., dockerfile: services/content-ingestion/Dockerfile }
    command: ["python", "-m", "content_ingestion.infrastructure.scheduler.scheduler_main"]

  content-ingestion-worker:
    build: { context: ., dockerfile: services/content-ingestion/Dockerfile }
    command: ["python", "-m", "content_ingestion.infrastructure.workers.worker_main"]

  content-ingestion-dispatcher:
    build: { context: ., dockerfile: services/content-ingestion/Dockerfile }
    command: ["python", "-m", "content_ingestion.infrastructure.messaging.outbox.dispatcher_main"]
```

### 14.4 Pool Size Recommendations

| Process Type | `pool_size` | `max_overflow` | `pool_pre_ping` | Rationale |
|-------------|------------|---------------|----------------|-----------|
| API server | 10 | 20 | Yes | Concurrent HTTP requests |
| Scheduler | 3 | 5 | Yes | Low concurrency, periodic ticks |
| Worker | 5 | 10 | Yes | Bounded by semaphore concurrency |
| Dispatcher | 3 | 5 | Yes | Single-threaded poll loop |

### 14.5 Signal Handling

Every process MUST:
1. Register handlers for `SIGINT` and `SIGTERM`
2. Set a stop event (`asyncio.Event`) on signal receipt
3. Complete in-flight work before exiting (graceful drain)
4. Return exit code 0 on clean shutdown

```python
loop = asyncio.get_running_loop()
for sig in (signal.SIGINT, signal.SIGTERM):
    loop.add_signal_handler(sig, worker.stop)
```

---

## 15. Read/Write Database Session Pattern

> **Rules**: R23 (read/write split)
> **Reference implementation**: `services/market-ingestion/src/market_ingestion/infrastructure/db/session.py`

### 15.1 Dual Factory Function

Every service with database access MUST provide a factory that returns both a write and read
session factory:

```python
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

def _build_factories(
    settings: Settings,
) -> tuple[async_sessionmaker[AsyncSession], async_sessionmaker[AsyncSession]]:
    """Build write and read session factories.

    When DATABASE_URL_READ is not set, read factory falls back to write factory.
    """
    write_engine = create_async_engine(
        str(settings.db_url),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
    )
    write_factory = async_sessionmaker(write_engine, expire_on_commit=False)

    if settings.db_url_read:
        read_engine = create_async_engine(
            str(settings.db_url_read),
            pool_size=settings.db_pool_size_read,
            max_overflow=settings.db_max_overflow_read,
            pool_pre_ping=True,
        )
        read_factory = async_sessionmaker(read_engine, expire_on_commit=False)
    else:
        read_factory = write_factory  # zero-cost fallback

    return write_factory, read_factory
```

### 15.2 Configuration

```python
class Settings(BaseSettings):
    db_url: PostgresDsn                        # write (required)
    db_url_read: PostgresDsn | None = None     # read (optional, falls back to db_url)
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_size_read: int = 20
    db_max_overflow_read: int = 30
```

### 15.3 Read/Write Routing Rules

| Operation | Write Session | Read Session |
|-----------|:---:|:---:|
| `SELECT` before `INSERT`/`UPDATE` (dedup checks) | **Yes** | No — stale reads cause duplicates |
| Task claiming (`SELECT FOR UPDATE SKIP LOCKED`) | **Yes** | No — requires row locks |
| List/dashboard/analytics queries | No | **Yes** |
| Watermark reads before fetch cycle | Either | **Yes** (staleness acceptable) |
| Health checks / status endpoints | No | **Yes** |
| Read immediately after write in same request | **Yes** | No — replication lag |

### 15.4 Anti-Pattern: Read-After-Write on Replica

```python
# WRONG — read may return stale data due to replication lag
async with write_factory() as ws:
    ws.add(entity)
    await ws.commit()

async with read_factory() as rs:
    result = await rs.get(Entity, entity.id)  # may be None!
```

```python
# CORRECT — use write session for read-after-write
async with write_factory() as ws:
    ws.add(entity)
    await ws.commit()
    result = await ws.get(Entity, entity.id)  # consistent
```

---

## 16. Session Optimization

> **Rules**: R24 (session optimization)

### 16.1 Anti-Pattern: Session Held Across External I/O

```python
# WRONG — connection held idle during HTTP call (BP-057)
async with session_factory() as session:
    data = await repo.get(id)              # uses connection
    result = await http_client.post(...)   # connection held idle!
    await repo.save(result)                # uses connection again
    await session.commit()
```

### 16.2 Correct Pattern: Split Read/IO/Write Phases

```python
# CORRECT — release connection before I/O
async with read_factory() as ro:
    data = await repo.get(id)              # read phase

result = await http_client.post(...)       # I/O phase (no session)

async with write_factory() as rw:
    await repo.save(result)                # write phase
    await rw.commit()
```

### 16.3 Session Lifecycle by Process Type

| Process | Session Lifecycle | Notes |
|---------|------------------|-------|
| **API routes** | Session-per-request via `Depends()` | Acceptable — requests are short-lived (ms). Optimize only if profiling shows contention. |
| **Workers** | Fresh UoW per phase: claim → release → execute → release → write → release | Each external I/O call happens outside a session context. |
| **Scheduler** | One short UoW per tick: evaluate → insert tasks → commit | Tick completes in ms; no external I/O during session. |
| **Dispatcher** | One short UoW per poll batch: claim outbox rows → commit → publish to Kafka → mark published → commit | Kafka publish happens between two separate UoW scopes. |

### 16.4 PgBouncer — Production Recommendation

PgBouncer is **not required for development** (single developer, limited load) but is
**recommended for production** deployments:

- Transaction-mode pooling reduces total connections to PostgreSQL
- Especially beneficial when multiple process types (API + scheduler + worker + dispatcher) share a database
- All services already support independent database URLs, making PgBouncer a drop-in addition

For the thesis project, tuning pool sizes per process type (§14.4) delivers 90% of
PgBouncer's connection-saving benefit without operational overhead.

### 16.5 Managed Database Readiness

All services MUST support independent database URLs (`db_url` setting). This ensures:
- Seamless migration from shared Postgres container to managed RDS/Cloud SQL
- Each service can point to its own database instance without code changes
- Read replicas can be added per-service via `db_url_read`

---

## 17. Unit of Work — Explicit Commit Pattern

> **Rules**: R26 (UoW must not auto-commit in `__aexit__`)
> **Reference implementations**: `services/portfolio/src/portfolio/infrastructure/db/unit_of_work.py`,
> `services/market-data/src/market_data/infrastructure/db/unit_of_work.py`

### 17.1 The Standard: Option B (Explicit-Commit Only)

The **Option B** pattern is the **cross-service standard** for all `UnitOfWork` concrete
implementations. It has two invariants:

1. `__aexit__` **NEVER commits** — it only rolls back on exception and closes the session.
2. Every mutating use case **MUST call `await uow.commit()` explicitly** before returning.

```python
# ✅ CORRECT — Option B (cross-service standard)
class SqlaUnitOfWork(AbstractUnitOfWork):
    async def __aenter__(self) -> "SqlaUnitOfWork":
        self._session = self._session_factory()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        try:
            if exc_type is not None:
                await self.rollback()
        except Exception:
            pass  # swallow rollback failure — session close in finally is the real cleanup
        finally:
            await self._session.close()

    async def commit(self) -> None:
        await self._session.commit()
        await self._drain_post_commit_hooks()

    async def rollback(self) -> None:
        await self._session.rollback()
```

Every mutating use case wraps its work and calls `commit()` explicitly:

```python
# ✅ CORRECT — use case calls commit explicitly
async def execute(self, cmd: CreateFoo) -> Foo:
    async with await self._uow_factory() as uow:
        entity = Foo(...)
        await uow.foos.add(entity)
        await uow.commit()           # ← explicit; __aexit__ never commits
        return entity
```

### 17.2 Anti-Pattern: Option A (Auto-Commit in `__aexit__`)

```python
# ❌ WRONG — Option A (R26 violation, BLOCKING review finding)
async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
    try:
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()   # FORBIDDEN — auto-commits silently on clean exit
    except Exception:
        pass
    finally:
        await self._session.close()
```

**Why this is dangerous**:
- Read-only use cases that open a UoW and do not call `commit()` will auto-commit an empty
  transaction — wasting DB resources and potentially flushing dirty state from ORM identity map.
- Use cases that raise after partial writes still execute rollback correctly, but read-only
  paths that never call `commit()` silently commit.
- Double-commit bugs are invisible: the second `session.commit()` call is a no-op in most
  drivers (SQLAlchemy AsyncSession silently succeeds on a clean session).

**Audit command**:
```bash
grep -rn "else.*commit\|__aexit__.*commit" services/*/src/*/infrastructure/db/unit_of_work.py
```
Any match is a R26 violation.

### 17.3 Post-Commit Hooks

Post-commit hooks (e.g., cache invalidation, metrics emission) run AFTER the database
transaction commits. They are drained inside `commit()` — NOT inside `__aexit__`.

```python
# ✅ CORRECT — hooks drained inside commit(), not __aexit__()
async def commit(self) -> None:
    await self._session.commit()
    await self._drain_post_commit_hooks()  # runs only on explicit commit

async def _drain_post_commit_hooks(self) -> None:
    while self._post_commit_hooks:
        hook = self._post_commit_hooks.pop(0)
        try:
            await hook
        except Exception:
            logger.warning("post_commit_hook_failed", exc_info=True)
            # hook failure must NOT propagate — committed message must not be dead-lettered
```

If a post-commit hook raises, **log and continue** — a successfully-committed message must
never be dead-lettered because a cache flush failed.

### 17.4 Dispatch UoW (Outbox-Only Pattern)

For services where the UoW wraps an outbox repository (e.g., content-ingestion outbox
dispatcher), the correct pattern delegates session lifecycle to the session context manager:

```python
# ✅ CORRECT — Dispatch UoW delegates to session lifecycle
async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
    if exc_type is not None:
        await self._session.rollback()
    await self._session.close()
```

This pattern is correct for outbox-only UoWs because `session.close()` without `commit()`
closes without committing — consistent with Option B.

### 17.5 Compliance Checklist

Before merging any service with a `UnitOfWork` implementation:
- [ ] `__aexit__` has **no** `else: await self.commit()` branch (R26)
- [ ] `__aexit__` has a `finally` block that calls `session.close()` on all paths
- [ ] Every mutating use case calls `await uow.commit()` before returning
- [ ] Read-only use cases do NOT call `commit()` (no phantom commits)
- [ ] Post-commit hooks run inside `commit()`, not `__aexit__()`
- [ ] Hook failures are caught and logged — never propagated to the base consumer

---

## 18. Docker Container Validation (R31)

After any source-code fix that affects runtime behaviour, the running Docker container must
be rebuilt and verified before the fix is declared live. Editing a `.py` file does NOT
affect the running container — the container image was built at `docker compose build` time.

### 18.1 Standard Verification Pattern

```bash
# 1. Rebuild the image for the affected service
docker compose build <svc>

# 2. Replace the running container with the new image
docker compose up -d <svc>

# 3. Verify the new code is present (choose one)
docker compose exec <svc> python -c "from <module> import <symbol>; print('OK')"
docker compose logs <svc> --tail=20   # look for the new log line or version marker
```

### 18.2 Which Containers Need Rebuilding

| Change type | Containers to rebuild |
|------------|----------------------|
| Python source file in service | That service's API, worker, scheduler, and dispatcher containers |
| Shared lib (`libs/`) | Every service that installs the lib |
| `config.py` / env var | That service's containers (API + workers) |
| Alembic migration | The migration runner container only |
| `docker-compose.yml` changes | `docker compose up -d` is sufficient (no build needed) |

### 18.3 Anti-Pattern

```
# ❌ WRONG — source is edited but container is never rebuilt
Edit services/rag_chat/src/rag_chat/pipeline.py
git commit -m "fix: pipeline timeout"
# Container still runs the pre-fix image. Fix is NOT live.

# ✅ CORRECT
Edit services/rag_chat/src/rag_chat/pipeline.py
docker compose build rag-chat && docker compose up -d rag-chat
docker compose exec rag-chat python -c "from rag_chat.pipeline import Pipeline; print(Pipeline.TIMEOUT)"
git commit -m "fix: pipeline timeout — verified in running container"
```

### 18.4 Fast-Path (Development Only)

In active development with bind mounts configured (where the container source is mounted
from the host), container rebuilds are not needed for Python changes. Verify that bind
mounts are active before skipping the rebuild step — production-mode compose files do NOT
use bind mounts.

---

## 19. Parallel Execution & Subagent Patterns (R33, R34)

This section covers standards for sessions that spawn parallel subagents (e.g., `/qa`
with specialist agents, `/implement` with parallel wave agents, or orchestrated fix sprints).

### 19.1 When to Use Parallel Subagents vs Sequential

| Criterion | Use Parallel | Use Sequential |
|-----------|-------------|----------------|
| Tasks touch disjoint file sets | Yes | No |
| Tasks share a fixture, model, or constant | No — sequential | Yes |
| Combined output needs cross-validation | No — run sequentially then validate | Yes |
| Each task takes >10 min independently | Yes — amortise wall-clock time | No |
| Tasks have strict dependency order | No — sequential | Yes |

**Default**: prefer sequential unless wall-clock time savings clearly justify the cross-agent
regression risk. The marginal cost of a cross-agent regression (discover → diagnose → fix)
often exceeds the time saved by parallelism.

### 19.2 Commit Discipline — Subagents

Every subagent MUST commit before returning, even if the commit is incremental. The checklist:

```
[ ] Subagent staged all changed files
[ ] Subagent created a commit with a descriptive message
[ ] Commit is on the main worktree (not a discarded worktree branch)
[ ] Commit message references the plan/task IDs being completed
```

If a subagent returns without committing, the orchestrator must immediately reapply and
commit the reported work before launching the next agent. Stale worktrees are ephemeral;
commits are permanent.

### 19.3 Budget Guardrails Before Launching N Agents

Before spawning N parallel subagents, estimate:
- **Token budget**: N × ~100k tokens/agent (approximate). If total exceeds project context
  budget, reduce N or split into sequential batches.
- **File conflict risk**: do a quick grep to confirm no two agents will touch the same file.
  If conflict is likely, assign non-overlapping file sets explicitly in each agent's prompt.
- **Test isolation**: confirm that each agent's test suite runs independently without
  shared in-memory state (e.g. `pytest-asyncio` event loop isolation).

### 19.4 Post-Return Full Suite Run

After all parallel subagents return and their commits are merged/applied:

```bash
# Run the full suite for every service touched by any agent
for svc in <svc1> <svc2> ...; do
    echo "=== $svc ===" && python -m pytest services/$svc/tests/ -v --tb=short
done
```

Classify failures using the R33 taxonomy: (a) pre-existing, (b) fix-induced regression,
(c) stale test expectation. Resolve all (b) and (c) before the session is complete.

### 19.5 Cross-Agent Regression Examples

Known cross-agent regression patterns to watch for:

| Pattern | Detection |
|---------|-----------|
| Agent A changes a shared fixture; Agent B's test expects the old fixture | `fixture` error in Agent B's tests after merge |
| Agent A renames a constant; Agent B's new code references the old name | `NameError`/`ImportError` after merge |
| Agent A changes a `side_effect` list; Agent B adds a call expecting the old list order | `StopIteration` or `AssertionError` after merge |
| Agent A adds a migration; Agent B adds a conflicting migration with the same version number | Alembic `MultipleHeads` error |

---

## 20. Testing Layer Design Rules

Derived from systemic failure patterns discovered in QA passes (PLAN-0084 Wave 6, 2026-05-07).
Each rule below is numbered TI-20.N for traceability.

### 20.1: Test Marker Consistency (TI-20.1)
All `tests/unit/**/*.py` files MUST use module-level `pytestmark = pytest.mark.unit`.
Per-function `@pytest.mark.unit` decorators are redundant and cause unreliable test selection
with `pytest -m unit`.
**Enforcement**: Architecture test `test_pytest_marker_enforcement.py` scans all unit test files
via AST and rejects per-function markers.

### 20.2: Parametrized Configuration Coverage (TI-20.2)
When a function or class accepts a finite set of valid inputs (skip-paths, retry counts, TTL
options, enum values), tests MUST exercise all variants — not just the most common one.
Single-case tests hide typos and drift silently.
**Example**: JWT middleware skip-paths defines 5 paths + 3 prefixes; ALL 8 must be tested.

### 20.3: Pure Function Edge-Case Testing (TI-20.3)
Every function with conditional logic that depends on time, boundaries, or state MUST have
parametrized unit tests covering all branches, including boundary transitions.
**Tool**: `@pytest.mark.parametrize` with explicit (input, expected) tuples.
**Example**: `_next_sunday_03_utc()` needs 6 boundary cases: before Sunday, same-day before
03:00, same-day at 03:00, same-day after 03:00, week boundary, month boundary.

### 20.4: Mock Provider Partial Failure Injection (TI-20.4)
Any code that uses a Valkey pipeline or Kafka batch operation MUST have a test that injects
a failure mid-operation (e.g. pipeline `execute()` raises after DEL is processed). Verify
graceful degradation — no crash, no corrupted state, appropriate warning log.

### 20.5: Consumer Dedup Strategy Visibility (TI-20.5)
Every `BaseKafkaConsumer` subclass MUST explicitly declare its dedup strategy as a class-level
comment or docstring:
- `ValkeyDedupMixin`: inherits is_duplicate/mark_processed automatically.
- `DbAtomicDedup`: uses `INSERT … ON CONFLICT DO NOTHING`; `is_duplicate` and `mark_processed`
  are explicit no-ops; allowlist entry required.
- `None`: no dedup; consumer is idempotent by another means; allowlist entry required.
**Rationale**: Hidden dedup assumptions cause data duplication bugs when consumers are copied as
templates.

### 20.6: Prometheus Registry Isolation (TI-20.6)
All Prometheus metric tests MUST use an `isolated_registry` fixture that monkeypatches
`prometheus_client.REGISTRY` with a fresh `CollectorRegistry` per test. Never read from the
global `REGISTRY` in test assertions.
**Pattern**:
```python
@pytest.fixture
def isolated_registry(monkeypatch):
    from prometheus_client import CollectorRegistry
    import prometheus_client
    registry = CollectorRegistry()
    monkeypatch.setattr(prometheus_client, "REGISTRY", registry)
    return registry
```
Place this fixture in `services/<service>/tests/unit/conftest.py` for each service with metric tests.

### 20.7: SQLAlchemy ON CONFLICT Verification (TI-20.7)
All `INSERT … ON CONFLICT DO NOTHING` repository methods MUST have an integration test that:
1. First insert: `rowcount == 1`.
2. Duplicate insert: `rowcount == 0`.
3. Compiled SQL text contains both `"ON CONFLICT"` and `"DO NOTHING"` (not checked via
   private `_post_values_clause` attribute).
**Why**: `_post_values_clause is not None` also passes for `RETURNING` clauses. The compiled
SQL string is the authoritative check.

### 20.8: Exponential Backoff and Async Timing (TI-20.8)
All retry loops MUST have a test that mocks `asyncio.sleep`, records the actual durations
passed to it, and asserts the exponential progression (e.g. 60, 120, 240, max 300).
Fixed-interval retries (`asyncio.sleep(CONSTANT)`) MUST be replaced with exponential backoff
before merging. See BP-423 for the anti-pattern.

### 20.9: Documentation Enforcement (TI-20.9)
`.claude-context.md` files MUST stay in sync with code. Each new endpoint, Kafka topic, port
interface, or config field added to a service MUST be reflected in the context file in the
same commit.
**Automation** (target PLAN-0085): CI gate extracts HTTP endpoint patterns from
`.claude-context.md` and verifies their presence in service source files via grep.

### 20.10: Parameter Ambiguity Prevention (TI-20.10)
No function or method may accept two names for the same parameter concept (e.g. both `ttl`
and `ex` for expiry duration). Use the upstream convention (Redis-native `ex`, not custom
`ttl`). If a legacy alias exists, deprecate it with a `warnings.warn` and remove it in the
next major version.

---

## 21. Multi-Tenancy Standards

### 21.1: Tenant Attribution Model

The platform uses **logical multi-tenancy**: shared database cluster, with `tenant_id` column
filtering at query time. Two classes of data exist:

| Class | Tenant-scoped? | Examples |
|-------|----------------|---------|
| **User data** | YES — must have `tenant_id` in every table | portfolios, holdings, watchlists, threads, messages, entity_mentions |
| **Global reference data** | NO — shared across all tenants | canonical_entities, relations, market data (OHLCV, fundamentals), instruments |

**Rule**: When in doubt, ask "Does this data differ between Tenant A and Tenant B?" If yes,
it needs `tenant_id`. If it is a publicly-known fact (an entity, a price, a market event),
it is global reference data.

### 21.2: Avro Schema Tenant Field Rule

All Avro event schemas for **user-attributable events** (content pipeline, NLP pipeline,
intelligence pipeline, RAG, portfolio, alert) MUST include:

```json
{"name": "tenant_id", "type": ["null", "string"], "default": null}
```

Using `["null", "string"]` with `"default": null` satisfies R5 (forward compatibility — adding
a nullable field with a default is always a non-breaking change).

**Exceptions** (schemas that intentionally omit `tenant_id`):
- `market.dataset.fetched.avsc` — global market data, not tenant-attributable
- `market.instrument.*.avsc` — global instrument registry
- `market.prediction.v1.avsc` — global prediction markets

Verification:
```bash
for schema in infra/kafka/schemas/*.avsc; do
  if ! grep -q '"tenant_id"' "$schema"; then echo "CHECK: $schema"; fi
done
```

### 21.3: Vector/HNSW Search Tenant Filter

Any query using `cosine_distance`, `l2_distance`, or `max_inner_product` against a table
that has a `tenant_id` column MUST include:
```sql
AND (tenant_id = :tenant_id OR tenant_id IS NULL)
```

The `IS NULL` clause handles legacy rows ingested before the column was added. Without this
filter, the similarity search returns top-K results globally — the highest-impact multi-tenant
data breach vector (HR-053).

### 21.4: Kafka Consumer Dedup Key Tenant Namespace

When Avro events carry `tenant_id`, all `ValkeyDedupMixin` subclasses MUST incorporate
`tenant_id` in the dedup key. Override `is_duplicate` / `mark_processed` to use:
```python
key = f"{self._dedup_prefix}:{tenant_id}:{event_id}"
```
Or extract `tenant_id` from the event in `extract_event_id()` and embed it in the returned
string:
```python
def extract_event_id(self, payload: dict) -> str:
    return f"{payload.get('tenant_id', 'system')}:{payload['event_id']}"
```

### 21.5: Rate Limiting Key Tenant Namespace

Valkey rate limit keys for authenticated endpoints must be scoped per (tenant, user):
```python
key = f"rl:v1:user:{tenant_id}:{user_id}"
```
Not per user alone — a user could belong to multiple tenants and consume quota across tenant
boundaries.

### 21.6: MinIO Object Key Tenant Convention

The `KeyBuilder` does not include a tenant segment. To ensure tenant isolation, the
`resource_id` component MUST derive from a tenant-scoped entity ID (e.g., `doc_id` from the
`documents` table after the `tenant_id` column is added). Do not use globally-scoped IDs
(instrument tickers, schema version strings) as `resource_id` for tenant-attributable objects.

---

## 22. LLM Agent Loop Budget Standards

Any agent loop implementation (S8 or future services) MUST enforce five independent budgets.
These defaults are validated against worldview's query patterns and the Reference System
investigation (2026-05-10-ai-architecture-enhancement-roi-analysis.md):

```python
@dataclass
class AgentBudget:
    max_tokens: int = 8_000          # soft — blocks further iterations; delivers current answer
    max_tool_latency_s: float = 30.0 # soft — triggers surrender path; injects final-answer prompt
    max_per_tool_s: float = 30.0     # hard — asyncio.wait_for per individual tool call
    max_iterations: int = 6          # hard — unconditional cap independent of any framework
    max_consecutive_errors: int = 2  # soft — consecutive tool failures → surrender
```

**Surrender path** (soft budget hit): inject system message
`"You have reached the tool response budget for this turn. Provide your best answer with the information gathered so far."` — the LLM generates a final answer without further tool calls.

**Token counting**: track cumulative prompt + completion tokens across all iterations of the
loop. When `total_tokens >= max_tokens`, set a flag that breaks after the current LLM
response completes (never mid-stream).

**Consecutive error reset**: reset `consecutive_errors = 0` on any successful tool call.

**Why these values**: `max_tool_latency_s=30.0` covers the known slow path (AGE Cypher
queries on `traverse_graph` can reach 60s without a budget; 30s provides a meaningful partial
answer). `max_iterations=6` matches the Reference System default and is sufficient for
worldview's two-tool + summary pattern.
