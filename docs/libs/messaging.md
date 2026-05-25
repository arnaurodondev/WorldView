# Messaging Library

> **Package**: `messaging` · **Path**: `libs/messaging/` · **Version**: 2025.6.0
> **Purpose**: Kafka producer/consumer abstractions, Avro serialization, transactional
> outbox dispatcher, Valkey client, PostgreSQL advisory locks, and EODHD quota
> enforcement. The backbone of all inter-service communication.

---

## Purpose

The `messaging` library provides five independently usable building blocks:

| Building Block | Module | What it solves |
|----------------|--------|----------------|
| **Outbox Dispatcher** | `messaging.kafka.dispatcher` | Atomically couples DB writes with Kafka publishes. Eliminates dual-write inconsistency. |
| **Kafka Consumer** | `messaging.kafka.consumer` | Idempotent event consumption with automatic retry, back-off, dead-lettering, and optional backpressure. |
| **Valkey Client** | `messaging.valkey` | Async Redis/Valkey operations with pooling and structured key taxonomy. |
| **PostgreSQL Advisory Lock** | `messaging.pg` | Single-leader scheduling across replicas without a dedicated lock service. |
| **EODHD Quota Service** | `messaging.eodhd_quota` | Shared monthly EODHD credit quota enforcement via Valkey (prevents per-replica over-consumption). |

No service ever writes directly to another service's database. All inter-service
state changes travel through the **outbox → Kafka → consumer** pipeline.

---

## Installation

```toml
[project]
dependencies = ["messaging"]

# With PostgreSQL advisory lock support:
dependencies = ["messaging[pg]"]
```

```bash
pip install -e "libs/messaging"
pip install -e "libs/messaging[pg]"   # adds sqlalchemy
```

Dependencies: `confluent-kafka[schemaregistry]>=2.4`, `fastavro>=1.9`,
`redis>=5.0`, `requests>=2.31`, `structlog>=25.0`, `observability`. Python 3.11–3.12.

---

## Delivery Architecture

### The Outbox Pattern

The core problem: **you cannot atomically write to a database and publish to Kafka
in two separate operations.** If the process crashes between the DB commit and the
`produce()` call, the event is silently dropped. The outbox pattern fixes this by
writing the event *into the database* as part of the same transaction as the domain
state change, then having a dedicated dispatcher relay it to Kafka.

```
Service writes domain state + outbox record in ONE DB transaction
    ↓
Dispatcher fetches pending outbox records (lease-based, SELECT FOR UPDATE SKIP LOCKED)
    ↓
Dispatcher calls producer.produce(topic, avro_value)
    ↓
On Kafka ACK: marks outbox record as published
On failure: increments attempt count (max_attempts → dead-letter)
    ↓
Background poll loop catches any records missed by a crashed process
```

**Key guarantees:**
- **At-least-once delivery** — a record is only removed from the outbox after Kafka
  returns a delivery acknowledgement. A crash between publish and mark-published will
  republish on the next lease expiry. Consumers must be idempotent.
- **Lease-based concurrency** — `SELECT … FOR UPDATE SKIP LOCKED` ensures multiple
  dispatcher instances never pick the same record.
- **Immediate + background hybrid** — `dispatch_now()` provides low-latency dispatch
  inline after commit; the background `run()` loop is the safety net.

### Consumer Message Lifecycle

```
poll() → deserialize → check is_duplicate → BEGIN UoW → process_message
    ↓ success: mark_processed → UoW.commit() → commit Kafka offset
    ↓ RetryableError: UoW.rollback() → store_failure → retry with back-off
    ↓ FatalError: UoW.rollback() → dead_letter() immediately
    ↓ max retries exceeded: dead_letter()
```

---

## Public API

### Topic Name Constants (`messaging.topics`)

Import topic names from here — never hardcode topic strings in services.

```python
from messaging.topics import (
    # Portfolio
    PORTFOLIO_EVENTS,                # "portfolio.events.v1"
    # Market
    MARKET_DATASET_FETCHED,          # "market.dataset.fetched"
    MARKET_INSTRUMENT_CREATED,       # "market.instrument.created"
    MARKET_INSTRUMENT_UPDATED,       # "market.instrument.updated"
    # Content
    CONTENT_ARTICLE_RAW,             # "content.article.raw.v1"
    CONTENT_ARTICLE_STORED,          # "content.article.stored.v1"
    # Intelligence / NLP
    NLP_ARTICLE_ENRICHED,            # "nlp.article.enriched.v1"
    NLP_SIGNAL_DETECTED,             # "nlp.signal.detected.v1"
    INTELLIGENCE_TEMPORAL_EVENT,     # "intelligence.temporal_event.v1"
    # Knowledge Graph
    ENTITY_PROVISIONAL_QUEUED,       # "entity.provisional.queued.v1"
    ENTITY_DIRTIED,                  # "entity.dirtied.v1"
    ENTITY_CANONICAL_CREATED,        # "entity.canonical.created.v1"
    GRAPH_STATE_CHANGED,             # "graph.state.changed.v1"
    ENTITY_NARRATIVE_GENERATED,      # "entity.narrative.generated.v1"
    # Prediction
    MARKET_PREDICTION,               # "market.prediction.v1"
    # Dead-letter
    MARKET_DEAD_LETTER,              # "market.dead-letter.v1"
)
```

### Outbox Status Enum (`messaging.enums`)

```python
from messaging import OutboxStatus
# OutboxStatus.PENDING | PROCESSING | DELIVERED | FAILED | DEAD_LETTER
```

### Kafka Consumer (`messaging.kafka.consumer`)

| Class | Purpose |
|-------|---------|
| `BaseKafkaConsumer[TFailure]` | Abstract generic base. Provides Avro deserialization, idempotency checking, error classification, exponential back-off, concurrent retry loop, graceful shutdown, optional backpressure. |
| `ConsumerConfig` | Typed consumer settings (bootstrap servers, group ID, topics, auto offset reset, timeouts, retry tuning). |
| `FailureInfo[TFailure]` | Carries per-message retry tracking state (event ID, topic, partition, offset, attempt count, last error, optional stored record). |
| `UnitOfWorkProtocol` | Structural protocol for the UoW passed to `get_unit_of_work()`. |

**Abstract methods that subclasses must implement:**

| Method | When called | Contract |
|--------|-------------|----------|
| `process_message(key, value, headers)` | Each non-duplicate message | Core business logic. Raise `RetryableError` or `FatalError`. |
| `is_duplicate(event_id)` | Before `process_message` | Query dedup store. Return `True` to skip. |
| `mark_processed(event_id)` | After successful processing | Insert into dedup store (inside same UoW). |
| `store_failure(failure)` | First failure | Persist `FailureInfo` to retry table. Return saved record. |
| `update_failure(failure)` | Subsequent retries | Update attempt count and last error. |
| `dead_letter(failure)` | Fatal error or max retries exceeded | Move to dead-letter store; alert. |
| `_dead_letter_impl(failure)` | Called by `dead_letter()` after cap check | **Default**: publish to `<topic>.dead-letter.v1` via `dlq_emitter` (LIB-002). Override to add DB persistence; call `await super()._dead_letter_impl(failure)` to keep topic emission. |
| `get_pending_retries()` | Background retry loop | Return all `FailureInfo` records eligible for retry. |
| `process_message_from_failure(failure)` | Retry | Re-run business logic from `failure.record` (stored payload). |
| `get_unit_of_work()` | Each message | Return a fresh async UoW context manager. |
| `deserialize_value(raw, schema_path)` | Deserialization | Call `deserialize_avro` or `deserialize_confluent_avro`. |
| `get_schema_path(topic)` | Before deserialization | Return path to `.avsc` file, or `None` to skip Avro. |
| `extract_event_id(value)` | After deserialization | Usually `return value["event_id"]`. |

**Valkey dedup mixin (`messaging.kafka.consumer.dedup`):**

```python
from messaging.kafka.consumer.dedup import ValkeyDedupMixin

class MyConsumer(ValkeyDedupMixin, BaseKafkaConsumer[None]):
    def __init__(self, config, valkey):
        super().__init__(config)
        self._dedup_client = valkey
        self._dedup_prefix = "my_service:dedup:my_consumer"
        # _dedup_ttl_seconds defaults to 86400 (24 hours)
```

`ValkeyDedupMixin` implements `is_duplicate` and `mark_processed` against a Valkey
set with a configurable TTL. On Valkey failure, `is_duplicate` returns `False`
(at-least-once fallback) and increments the `messaging_dedup_valkey_fallback_total`
Prometheus counter. Use this mixin instead of rolling your own dedup logic.

**Backpressure (`messaging.kafka.consumer.backpressure`):**

```python
from messaging.kafka.consumer import BackpressurePolicy

policy = BackpressurePolicy.from_settings(settings)
consumer = MyConsumer(config=cfg, backpressure_policy=policy)
```

Opt-in AIMD-style per-partition pause/resume. Reads four settings attributes:

| Attribute | Env var | Default |
|-----------|---------|---------|
| `kafka_consumer_backpressure_enabled` | `KAFKA_CONSUMER_BACKPRESSURE_ENABLED` | `False` |
| `kafka_consumer_lag_pause_threshold` | `KAFKA_CONSUMER_LAG_PAUSE_THRESHOLD` | `10_000` |
| `kafka_consumer_lag_resume_threshold` | `KAFKA_CONSUMER_LAG_RESUME_THRESHOLD` | `1_000` |
| `kafka_consumer_backpressure_check_interval_seconds` | `KAFKA_CONSUMER_BACKPRESSURE_CHECK_INTERVAL_SECONDS` | `30.0` |

### Error Classification (`messaging.kafka.consumer.errors`)

| Error class | Category | Default behaviour |
|-------------|----------|-------------------|
| `RetryableError` | Transient | Store failure, retry with full-jitter exponential back-off |
| `StorageUnavailableError` | Transient | ↑ |
| `DatabaseConnectionError` | Transient | ↑ |
| `NetworkTimeoutError` | Transient | ↑ |
| `ServiceUnavailableError` | Transient | ↑ |
| `RateLimitedError` | Transient | ↑ |
| `FatalError` | Permanent | Dead-letter immediately, no retry |
| `SchemaVersionError` | Permanent | ↑ |
| `MalformedDataError` | Permanent | ↑ (also raised by deserialization step) |
| `MissingRequiredFieldError` | Permanent | ↑ |
| `BusinessRuleViolationError` | Permanent | ↑ |

When `max_retries` is exceeded for a `RetryableError`, the message is dead-lettered.

### Dead-letter topic emission (LIB-002 / TASK-W2-06)

`BaseKafkaConsumer._dead_letter_impl` ships a **concrete default** that
publishes a JSON failure envelope to `<original_topic>.dead-letter.v1` via
an optional `DLQEmitterProtocol` passed at construction time. This makes
dead-lettered messages observable from kafka-ui and external DLQ consumers
without each subclass having to wire its own topic publishing.

```python
from messaging import BaseKafkaConsumer, ConsumerConfig, DLQEmitterProtocol

class MyEmitter:
    async def emit(self, topic, payload, headers=None, key=None):
        # Use the service's outbox repo or a direct Kafka producer here.
        await self._outbox_repo.add(topic=topic, payload=payload, headers=headers)

consumer = MyConsumer(
    config=ConsumerConfig(...),
    dlq_emitter=MyEmitter(),  # NEW — opt-in for topic publishing
)
```

**Behaviour matrix:**

| `dlq_emitter` | Subclass overrides `_dead_letter_impl`? | Result |
|---------------|-----------------------------------------|--------|
| `None`        | No                                      | Logs `dead_letter_no_emitter_configured` warning, returns. (back-compat default) |
| `None`        | Yes (no `super()` call)                 | Subclass behaviour only (e.g. DB write). |
| Set           | No                                      | Publishes envelope to `<topic>.dead-letter.v1`. |
| Set           | Yes + calls `super()._dead_letter_impl` | Subclass behaviour **and** topic publishing. |

**Envelope payload** (JSON, UTF-8):

```json
{
  "event_id": "01HXYZ...",
  "original_topic": "content.article.raw.v1",
  "partition": 3,
  "offset": 42,
  "attempt": 5,
  "error": "<exception repr>",
  "error_type": "RetryableError",
  "dead_lettered_at": "2026-05-20T13:47:25.123456+00:00",
  "consumer_group": "content-store-group-article"
}
```

**Headers** emitted on every DLQ message:

- `X-Dead-Letter-Error` — truncated stringified exception (≤1024 chars)
- `X-Dead-Letter-Original-Topic` — source topic name
- `X-Dead-Letter-Timestamp` — ISO-8601 UTC at dead-letter time
- `X-Dead-Letter-Event-Id` — original `event_id` (also used as Kafka key)

Emitter failures inside `_dead_letter_impl` are **logged and swallowed**
(`dead_letter_emit_failed`) — by the time we reach this code the message
has already been retried and counted against the cap, so re-raising would
just churn the consumer loop. Wire an alert on the log event instead.

### Kafka Producer (`messaging.kafka.producer`)

| Symbol | Purpose |
|--------|---------|
| `KafkaProducerConfig` | Producer config with `acks=all`, `enable_idempotence=True`. |
| `build_serializing_producer()` | Factory for `confluent_kafka.SerializingProducer`. |
| `OutboxKafkaValue` | Wire value: `event_type` + `payload` dict, routed to correct Avro serializer. |
| `KafkaEventValueSerializer` | Type alias for the serializer callable. |
| `OutboxEventValueSerializer` | Serializer that routes by `event_type` field. |

### Avro Serializer (`messaging.kafka.serializer`)

| Symbol | Purpose |
|--------|---------|
| `AvroDictable` | Protocol requiring `event_type: str` and `to_dict() -> dict`. Used for subject-name routing. |
| `AvroSerializerConfig` | Production defaults (`auto_register_schemas=False`). |
| `build_avro_serializer()` | Factory for Confluent `AvroSerializer`. |
| `topic_event_type_subject_name_strategy()` | Subject naming: `{topic}-{event_type}`. |

### Serialization Utilities (`messaging.kafka.serialization_utils`)

| Function | Purpose |
|----------|---------|
| `load_schema(path)` | Load Avro schema from `.avsc` file (fastavro-parsed). |
| `serialize_avro(schema, record)` | Schemaless Avro binary encoding. |
| `deserialize_avro(schema, data)` | Schemaless Avro binary decoding. |
| `serialize_confluent_avro(schema_id, schema, record)` | Confluent 5-byte wire-format header + Avro body. |
| `deserialize_confluent_avro(schema, data)` | Decode Confluent wire-format (detects 0x00 magic byte). |
| `serializer_for_schema(schema_str, registry)` | Build Confluent `AvroSerializer` for a specific schema. |
| `decimal_to_str(d)` | `Decimal` → string for Avro `string` fields. |
| `iso_datetime(dt)` | `datetime` → ISO-8601 string for Avro `string` fields. |

### Schema Registry (`messaging.kafka.schema_registry`)

| Symbol | Purpose |
|--------|---------|
| `SchemaRegistryConfig` | Confluent Schema Registry connection config (URL, auth, TLS). |
| `build_schema_registry_client(config)` | Factory for `confluent_kafka.schema_registry.SchemaRegistryClient`. |

### Outbox Dispatcher (`messaging.kafka.dispatcher`)

| Symbol | Purpose |
|--------|---------|
| `BaseOutboxDispatcher` | Lease-based outbox publisher. Hybrid: `dispatch_now()` inline + background `run()` poll loop. Marks records published only after Kafka ACK. Dead-letters records exceeding `max_attempts`. |
| `DispatcherConfig` | All knobs: `poll_interval_seconds`, `idle_poll_interval_seconds`, `lease_seconds`, `batch_size`, `max_attempts`, back-off params, `immediate_dispatch`, `worker_id`. |
| `DeliveryResult` | Outcome of one dispatch: `record_id`, `success`, `topic`, `error`. |
| `OutboxRecordProtocol` | Structural type for outbox table rows. |
| `OutboxRepositoryProtocol` | Port for outbox table: `fetch_pending`, `mark_published`, `increment_attempts`, `move_to_dead_letter`. |
| `UnitOfWorkWithOutboxProtocol` | UoW that exposes `.outbox` repository + `commit`/`rollback`. |
| `OUTBOX_NOTIFY_CHANNEL` | Postgres channel name (`"outbox_events_new"`) used by the LISTEN/NOTIFY wake-up optimisation (LIB-003 / TASK-W4-01). |
| `run_dispatcher(dispatcher)` | Coroutine — run in a background task via `asyncio.create_task(run_dispatcher(d))`. |

**Abstract methods for `BaseOutboxDispatcher`:**

| Method | Purpose |
|--------|---------|
| `get_unit_of_work()` | Return fresh async UoW implementing `UnitOfWorkWithOutboxProtocol`. |
| `get_serializer(event_type)` | Avro value serializer callable for the given `event_type`. |
| `get_producer()` | Confluent `SerializingProducer` instance. |
| `on_delivery_failure(result)` *(optional)* | Override to add alerting on dead-letter. |
| `register_notify_listener(on_notify)` *(optional)* | Wire a Postgres `LISTEN` on `OUTBOX_NOTIFY_CHANNEL` so the dispatcher wakes immediately on each new outbox INSERT. Default returns `None` (no LISTEN, dispatcher uses legacy 5s polling). See "LISTEN/NOTIFY wake-up" below. |

#### LISTEN/NOTIFY wake-up (LIB-003 / TASK-W4-01)

Polling the outbox every 5 seconds across 10 services costs ~172 800
idle queries per day — pure waste when the table is empty. The
dispatcher now supports a Postgres `LISTEN/NOTIFY` wake-up that
collapses idle polling to a safety-net `idle_poll_interval_seconds`
(default 60s) while keeping at-least-once semantics intact.

**Activation is opt-in per service** in two steps:

**1. Add an AFTER-INSERT trigger to `outbox_events`** (one-time Alembic
migration per service that owns an outbox table):

```sql
CREATE OR REPLACE FUNCTION notify_outbox_events_new() RETURNS trigger AS $$
BEGIN
  -- Statement-level trigger: one NOTIFY per INSERT batch, not per row.
  -- The dispatcher always re-polls the table when woken, so collapsing
  -- multiple inserts into a single NOTIFY is safe and cheaper.
  NOTIFY outbox_events_new;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER outbox_events_notify_trigger
  AFTER INSERT ON outbox_events
  FOR EACH STATEMENT
  EXECUTE FUNCTION notify_outbox_events_new();
```

Producers do not need to know about the trigger — any normal
`INSERT INTO outbox_events (...)` automatically fires `NOTIFY
outbox_events_new`. The NOTIFY is delivered to all LISTEN sessions
when the transaction commits, so dual-write semantics are preserved
(no spurious wake-ups on rolled-back inserts).

**2. Override `register_notify_listener` in the service dispatcher** to
wire `asyncpg.Connection.add_listener` on a dedicated connection:

```python
from messaging.kafka.dispatcher import OUTBOX_NOTIFY_CHANNEL, BaseOutboxDispatcher

class MyServiceDispatcher(BaseOutboxDispatcher):
    async def register_notify_listener(self, on_notify):
        conn = await self._engine.connect()
        raw = await conn.get_raw_connection()
        asyncpg_conn = raw.driver_connection

        def _callback(*_args):
            # Called from asyncpg's I/O loop — must be sync + cheap.
            on_notify()

        await asyncpg_conn.add_listener(OUTBOX_NOTIFY_CHANNEL, _callback)

        async def _cleanup():
            await asyncpg_conn.remove_listener(OUTBOX_NOTIFY_CHANNEL, _callback)
            await conn.close()

        return _cleanup
```

**Back-compat is mandatory.** Services that don't override the hook
behave exactly as before — `register_notify_listener` returns `None`
by default, and the dispatcher falls back to the legacy
`poll_interval_seconds=5` loop. Any exception raised inside the hook
is caught and logged as `outbox_dispatcher_listen_unavailable`; the
dispatcher then continues polling. This means a test using SQLite or
a misconfigured driver never breaks the run loop.

**Operational notes:**

- LISTEN ties up a Postgres connection — use a dedicated one outside
  the regular pool.
- NOTIFY is delivered only on commit, so a producer rollback never
  wakes the dispatcher (correct: nothing to dispatch).
- The safety-net poll still fires every `idle_poll_interval_seconds`
  to catch NOTIFYs lost during connection drops / restarts.
- Multiple NOTIFYs between polls collapse into a single wake-up; the
  dispatcher always re-polls the table after waking.

### Valkey Client (`messaging.valkey`)

| Symbol | Purpose |
|--------|---------|
| `ValkeyClient` | Async Redis/Valkey client with connection pooling. Methods: `get`, `set`, `exists`, `delete`, `expire`, `incr`, `incrbyfloat`, `set_json`, `get_json`, `mget_json`, `set_nx`, `hset`, `hget`, `lpush`, `lrange`. |
| `ValkeyConfig` | Connection config (host, port, db, password, SSL, pool size, timeouts). Has `from_url(url)` classmethod. |
| `create_valkey_client(config)` | Factory from `ValkeyConfig`. |
| `create_valkey_client_from_url(url)` | Factory from a Redis-style URL string. |

**Key taxonomy**: `<scope>:<version>:<resource>:<id>[:<qualifier>]`

Examples:
```python
"md:v1:quote:AAPL"                    # market-data quote cache
"eodhd:v1:quota:2026-05:credits_used" # EODHD monthly quota counter
"nlp:dedup:article_consumer:evt123"   # consumer dedup key
```

### PostgreSQL Advisory Lock (`messaging.pg`)

```python
from messaging.pg.advisory_lock import pg_advisory_lock, advisory_lock_id

async with pg_advisory_lock(session, "market-ingestion:eodhd-scheduler") as acquired:
    if not acquired:
        return  # another replica holds the lock
    await run_scheduled_fetch()
```

- `advisory_lock_id(name: str) -> int` — deterministic 32-bit positive lock ID
  from a string name using SHA-256 (not Python's `hash()`, which is randomised).
- `pg_advisory_lock(session, name)` — async context manager; yields `True` if
  acquired, `False` otherwise. Uses `pg_try_advisory_lock` (non-blocking).
  Automatically releases on context exit.

### `processed_events` Retention (`messaging.kafka.maintenance`)

The Kafka consumer base class writes every successfully processed event id
into a service-local ``processed_events`` table so that re-delivery
(operator-driven offset rewinds, rebalance replays) is dropped via
``is_duplicate()``. Without retention this table grows monotonically.

`ProcessedEventsCleanupWorker` enforces a configurable retention window
(default 30 days, default batch size 10 000 rows) with a batched, non-blocking
DELETE using `FOR UPDATE SKIP LOCKED` so the live consumer is never blocked.

```python
from messaging import ProcessedEventsCleanupWorker

worker = ProcessedEventsCleanupWorker(
    service_name="content-store",
    retention_days=30,   # default; override per service
    batch_size=10_000,   # default; override on resource-constrained DBs
)

async with write_session_factory() as session:
    deleted = await worker.run_once(session)
```

**Wiring guidance**:
- Invoke `run_once()` daily (e.g. 02:00 UTC) via your service's existing
  scheduler, or via a dedicated standalone entry point (`*_cleanup_main.py`)
  per R22.
- Use the **write** session factory — the worker issues DELETE statements.
- Schema assumption: a `processed_events` table with `event_id` PRIMARY KEY
  and `processed_at TIMESTAMPTZ`. Today only S5 content-store materialises
  this table; other services use Valkey-backed dedup
  (`ValkeyDedupConsumer`) and require no cleanup.

**Safety note**: `processed_events` is belt-and-suspenders against operator
offset rewinds — the consumer offset itself is the primary at-least-once
guarantee. The 30-day default is comfortably longer than any plausible
rewind window.

### EODHD Quota Service (`messaging.eodhd_quota`)

Prevents per-replica over-consumption of the shared monthly EODHD credit budget.
All services that call EODHD APIs (S2, S4) share one counter in Valkey.

```python
from messaging.eodhd_quota.quota_service import EodhdQuotaService, QuotaCheckResult

service = EodhdQuotaService(valkey_client, hard_limit=100_000)

result = await service.try_consume(cost=1, service="market-ingestion", symbol="AAPL")
if result == QuotaCheckResult.HARD_LIMIT_EXCEEDED:
    return  # block the EODHD call
if result == QuotaCheckResult.SOFT_LIMIT_EXCEEDED:
    logger.warning("approaching_eodhd_quota")  # log but proceed

status = await service.get_status()
# QuotaStatus(month="2026-05", credits_used=42000, soft_limit=80000,
#             hard_limit=100000, percent_used=42.0)
```

| Method | Returns | Description |
|--------|---------|-------------|
| `try_consume(cost, service, symbol, month)` | `QuotaCheckResult` | Consume credits atomically. `HARD_LIMIT_EXCEEDED` means block; `SOFT_LIMIT_EXCEEDED` means warn but proceed. |
| `get_status(month)` | `QuotaStatus` | Point-in-time snapshot of usage. |
| `get_by_service(service, month)` | `int` | Credits used by one service this month. |
| `get_by_symbol(symbol, month)` | `int` | Credits used for one symbol this month. |

Valkey keys: `eodhd:v1:quota:{YYYY-MM}:credits_used` (32-day TTL, auto-expires).

---

## Usage Examples

### Full Outbox + Producer Cycle

```python
from messaging.kafka.dispatcher.base import BaseOutboxDispatcher, DispatcherConfig, run_dispatcher
import asyncio

class PortfolioDispatcher(BaseOutboxDispatcher):
    def __init__(self, uow_factory, producer, serializers):
        super().__init__(config=DispatcherConfig(
            poll_interval_seconds=5.0,
            lease_seconds=30,
            max_attempts=5,
        ))
        self._uow_factory = uow_factory
        self._producer = producer
        self._serializers = serializers

    async def get_unit_of_work(self):
        return self._uow_factory()

    def get_serializer(self, event_type: str):
        return self._serializers[event_type]

    def get_producer(self):
        return self._producer

# In FastAPI lifespan:
dispatcher = PortfolioDispatcher(...)
asyncio.create_task(run_dispatcher(dispatcher))

# In a use case:
async with await uow_factory() as uow:
    await uow.portfolios.add(portfolio)
    await uow.outbox.add(OutboxRecord(
        event_type="portfolio.portfolio.created",
        topic="portfolio.events.v1",
        payload=portfolio.to_event_dict(),
    ))
    await uow.commit()
await dispatcher.dispatch_now()  # optional fast path
```

### Full Consumer Cycle

```python
from messaging import BaseKafkaConsumer, ConsumerConfig, RetryableError, FatalError
from messaging.kafka.consumer.dedup import ValkeyDedupMixin

class ArticleConsumer(ValkeyDedupMixin, BaseKafkaConsumer[None]):
    def __init__(self, config, valkey, storage, repo):
        super().__init__(config)
        self._dedup_client = valkey
        self._dedup_prefix = "content_store:dedup:article_raw"
        self._storage = storage
        self._repo = repo

    async def process_message(self, key, value, headers):
        try:
            data = await self._storage.get_bytes(value["bucket"], value["key"])
        except StorageUnavailableError as exc:
            raise RetryableError("storage down") from exc
        await self._repo.upsert(parse(data))

    async def dead_letter(self, failure):
        await self._dlq_repo.move(failure)

    # ... implement remaining abstract methods
```

### Valkey Client

```python
from messaging import create_valkey_client_from_url

client = await create_valkey_client_from_url("redis://localhost:6379")
await client.set_json("md:v1:quote:AAPL", {"price": 150.0}, ttl=30)
quote = await client.get_json("md:v1:quote:AAPL")
quotes = await client.mget_json(["md:v1:quote:AAPL", "md:v1:quote:MSFT"])
```

---

## Architecture Notes

### `serialize_confluent_avro` vs `serialize_avro`

`serialize_confluent_avro` produces a 5-byte wire-format header (magic byte `0x00`
+ 4-byte schema ID) followed by the Avro body. This is the format the Confluent
Schema Registry and Confluent Kafka clients expect. Use it for all Kafka messages.
`serialize_avro` is schemaless — use it for MinIO payloads and test fixtures.

### `deserialize_confluent_avro` vs `deserialize_avro`

`deserialize_confluent_avro` detects the `0x00` magic byte and strips the 5-byte
header before decoding. Use it in all Kafka consumers. BP-122 was caused by a
consumer using `deserialize_avro` on Confluent-format messages.

---

## Configuration

Messaging configuration comes from each service's own settings class
(no global `MessagingSettings`). Services pass configuration at construction time.

```bash
# Typical service environment variables:
KAFKA_BOOTSTRAP_SERVERS=kafka:9092
KAFKA_CONSUMER_GROUP_ID=my-service
SCHEMA_REGISTRY_URL=http://schema-registry:8081
VALKEY_URL=redis://valkey:6379
```

---

## Testing

```bash
cd libs/messaging
python -m pytest tests/ -v                              # unit tests only
python -m pytest tests/ -v -m integration               # requires Kafka + Valkey
```

**Unit tests** mock the Confluent producer, Valkey client, and database. Cover
error classification, retry back-off arithmetic, serialization helpers, and
`DeliveryResult` outcomes.

**Integration tests** use `testcontainers` for Kafka and `fakeredis` for Valkey.
Test consumer + producer round-trip, idempotency (replay same message twice —
handler called once), and outbox crash recovery.

---

## Common Pitfalls

1. **Missing idempotency** — at-least-once delivery is guaranteed. Without `is_duplicate`
   + `mark_processed`, messages are processed more than once after any restart.
2. **Auto-commit enabled** — `enable_auto_commit=True` decouples offset advances from
   processing success, causing silent data loss on crash. Keep it `False`.
3. **Blocking calls in async handlers** — `process_message` runs on the asyncio event
   loop. Synchronous I/O must use `asyncio.to_thread()` / `run_in_executor`.
4. **Not storing payload in `store_failure`** — the retry loop calls
   `process_message_from_failure`, not `process_message`. If `failure.record` is
   missing the original payload, retries silently do nothing.
5. **Dual writes without the outbox** — never call `producer.produce()` inside a use
   case alongside a DB write. The outbox is the only safe coupling mechanism.
6. **`fetch_pending` without lease check** — the SQL must atomically update
   `leased_until` (`SELECT … FOR UPDATE SKIP LOCKED`). Without this, multiple
   dispatcher instances publish duplicates.
7. **ValkeyDedupMixin TTL shorter than consumer pause** — if consumers are paused
   longer than `_dedup_ttl_seconds` (default 24h), expired dedup keys cause
   duplicate processing on re-delivery.
