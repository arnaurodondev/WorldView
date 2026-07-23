# Messaging Library

> **Package**: `messaging` · **Path**: `libs/messaging/` · **Version**: 2025.6.0
> **Purpose**: Kafka producer/consumer abstractions, Avro serialization, transactional
> outbox dispatcher, Valkey client, PostgreSQL advisory locks, and EODHD quota
> enforcement. The backbone of all inter-service communication.

---

## Purpose

The `messaging` library provides these independently usable building blocks:

| Building Block | Module | What it solves |
|----------------|--------|----------------|
| **Outbox Dispatcher** | `messaging.kafka.dispatcher` | Atomically couples DB writes with Kafka publishes. Eliminates dual-write inconsistency. |
| **Kafka Consumer** | `messaging.kafka.consumer` | Idempotent event consumption with automatic retry, back-off, dead-lettering, and optional backpressure. |
| **Run() Supervision** | `messaging.kafka.consumer.supervisor` | Entry-point wrapper that fails the process loudly on a terminal `run()` exit instead of wedging on a never-awaited task. |
| **Processed-Events Cleanup** | `messaging.kafka.maintenance` | Retention enforcement for the `processed_events` idempotency table. |
| **Table Retention Pruner** | `messaging.kafka.maintenance.table_retention` | Generic batched, per-batch-committing age-based pruner for any unbounded append/log table (outbox delivered rows, dedup/idempotency logs). |
| **Valkey Client** | `messaging.valkey` | Async Redis/Valkey operations with pooling and structured key taxonomy. |
| **PostgreSQL Advisory Lock** | `messaging.pg` | Single-leader scheduling across replicas without a dedicated lock service. |
| **Shared Async Engine Factory** | `messaging.pg.engine_factory` | One place to build a hardened asyncpg `AsyncEngine` (PgBouncer prepared-statement disabling, client-side `command_timeout`, server-side `statement_timeout`) instead of every service hand-rolling its own `connect_args` (BP-732). |
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

`OutboxStatus` is a `StrEnum`; the string values are the lowercase member names
(`"pending"`, `"processing"`, `"delivered"`, `"failed"`, `"dead_letter"`).

### Package-root re-exports (`messaging`)

Everything in this list is importable directly from the package root
(`from messaging import ...`) — see `messaging.__all__`:

- Consumer: `BaseKafkaConsumer`, `ConsumerConfig`, `FailureInfo`,
  `UnitOfWorkProtocol`, `DLQEmitterProtocol`, `DLQ_TOPIC_SUFFIX`
- Errors: `ConsumerError` (base), `RetryableError`, `FatalError` and all
  subclasses (see Error Classification below)
- Producer / serializer: `KafkaProducerConfig`, `OutboxKafkaValue`,
  `KafkaEventValueSerializer`, `OutboxEventValueSerializer`,
  `build_serializing_producer`, `AvroDictable`, `AvroSerializerConfig`,
  `build_avro_serializer`, `topic_event_type_subject_name_strategy`
- Schema registry: `SchemaRegistryConfig`, `build_schema_registry_client`
- Serialization utils: `load_schema`, `serialize_avro`, `deserialize_avro`,
  `serialize_confluent_avro`, `deserialize_confluent_avro`,
  `serializer_for_schema`, `decimal_to_str`, `iso_datetime`
- Dispatcher: `BaseOutboxDispatcher`, `DispatcherConfig`, `DeliveryResult`,
  `OutboxRecordProtocol`, `OutboxRepositoryProtocol`,
  `UnitOfWorkWithOutboxProtocol`, `run_dispatcher`
- Valkey: `ValkeyClient`, `ValkeyConfig`, `create_valkey_client`,
  `create_valkey_client_from_url`
- Enums: `OutboxStatus`

> `ProcessedEventsCleanupWorker` is **deliberately not** re-exported at the
> package root — it imports `sqlalchemy`, which the S9 api-gateway (no DB by
> design, R7) must not be forced to install. Import it from
> `messaging.kafka.maintenance` directly. Likewise `ValkeyDedupMixin`,
> `BackpressurePolicy`, and `LagCalculator` are exported from
> `messaging.kafka.consumer` (not the package root).

### Kafka Consumer (`messaging.kafka.consumer`)

| Class | Purpose |
|-------|---------|
| `BaseKafkaConsumer[TFailure]` | Abstract generic base. Provides Avro deserialization, idempotency checking, error classification, exponential back-off, concurrent retry loop, graceful shutdown, optional backpressure. |
| `ConsumerConfig` | Typed consumer settings (bootstrap servers, group ID, topics, auto offset reset, timeouts, retry tuning). |
| `FailureInfo[TFailure]` | Carries per-message retry tracking state (event ID, topic, partition, offset, attempt count, last error, optional stored record). |
| `UnitOfWorkProtocol` | Structural protocol for the UoW passed to `get_unit_of_work()`. |
| `DLQEmitterProtocol` | Port for publishing a single dead-letter envelope to `<topic>.dead-letter.v1`. Defines `async emit(topic, payload, headers=None, key=None)`. Pass an implementation to `BaseKafkaConsumer(..., dlq_emitter=...)` to make dead-lettered messages observable in kafka-ui; omit it to keep DB-only DLQ persistence. |
| `DLQ_TOPIC_SUFFIX` | The constant `".dead-letter.v1"` appended to the source topic to derive the canonical DLQ topic. |

**Constructor:**

```python
BaseKafkaConsumer(
    config: ConsumerConfig,
    metrics: ServiceMetrics | None = None,
    backpressure_policy: BackpressurePolicy | None = None,
    dlq_emitter: DLQEmitterProtocol | None = None,
    *,
    metrics_namespace: str | None = None,
)
```

**Abstract methods that subclasses must implement:**

| Method | When called | Contract |
|--------|-------------|----------|
| `process_message(key, value, headers)` | Each non-duplicate message | Core business logic. Raise `RetryableError` or `FatalError`. |
| `is_duplicate(event_id)` | Before `process_message` | Query dedup store. Return `True` to skip. |
| `mark_processed(event_id)` | After successful processing | Insert into dedup store (inside same UoW). |
| `store_failure(failure)` | First failure | Persist `FailureInfo` to retry table. Return saved record. |
| `update_failure(failure)` | Subsequent retries | Update attempt count and last error. |
| `dead_letter(failure, reason=None)` | Fatal error or max retries exceeded | Move to dead-letter store; alert; increments `kafka_messages_dead_lettered_total{reason}`. |
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

### Decode-poison skip (`ConsumerConfig.skip_undecodable_records`)

> Added 2026-07-23 (Recurrence-1 structural fix, bottleneck audit / BP-736).
> **Default: `True`.**

`_handle_message` catches `(EOFError, struct.error)` raised by
`deserialize_value` — the two exception types a raw-bytes decode failure can
produce (e.g. a truncated/misaligned Avro record left behind after a
backward-compatible schema field append, R11) — and, when
`skip_undecodable_records` is `True` (the default), logs a structured
`<consumer>_deserialize_skipped` warning (topic, partition, offset,
`error_type`) and **returns without dead-lettering**. This is deliberately
**not** the same as catching `MalformedDataError`: several consumers
(`entity_consumer.py`, `structured_enrichment_consumer.py`,
`alert/intelligence_consumer.py`) raise `MalformedDataError` from inside
their own `deserialize_value` for a validated business-rule rejection
(oversized-payload cap, Avro-magic-byte-without-registered-schema) that must
stay dead-lettered/DLQ-visible for operator replay — those are unaffected by
this skip path and continue to flow through the normal `dead_letter()` path
below.

Why this matters: before this fix, ANY exception from `deserialize_value`
(including a raw decode failure) was always wrapped into `MalformedDataError`
and dead-lettered inline with no retry. A burst of poison records — the
routine result of appending a nullable field to a long-lived Avro schema —
trips `dead_letter_cap` and force-restarts the container *before* the offset
commits, so the consumer re-reads the same poison batch forever and can
never reach the healthy backlog behind it (BP-736). Two consumers
independently reinvented a hand-rolled `_handle_message` override to fix
this, two months apart, before the fix was folded into the base class.

A per-subclass class attribute, `_deserialize_skip_log_event: str`
(default `"kafka_consumer_deserialize_skipped"`), lets a consumer keep a
bespoke structlog event name for continuity with existing dashboards/alerts
(e.g. `EnrichedArticleConsumer` sets it to
`"enriched_consumer_deserialize_skipped"`).

Set `skip_undecodable_records=False` only for a consumer with a deliberate,
reviewed reason to dead-letter poison records instead of skipping them (e.g.
a DLQ contract that requires every dropped record to be persisted for manual
replay) — in that case the historical "wrap into `MalformedDataError` and
dead-letter" behaviour is preserved byte-for-byte.

**Known gap (flagged during review, not yet fixed)**: the opt-in batched
path (`_handle_batch`, `consume_batch_size > 1`) has its own, separate,
unconditional `except Exception: ... continue` per-message skip that is
**not** scoped to `(EOFError, struct.error)` and is **not** gated by
`skip_undecodable_records` — it will swallow a deliberate `MalformedDataError`
too if a batched consumer's `deserialize_value` ever raises one. No current
consumer combination triggers this (only
`market-data/prediction_market_consumer_main.py` batches, and its
`MalformedDataError` raises are outside `deserialize_value`), but it is the
same class of over-broad-catch bug sitting undocumented next to the fixed
code — see BP-736's Prevention note.

### Opt-in persistent retry counter (`ConsumerConfig.enable_persistent_retry`)

> Added 2026-06-11 (F-2 / Fix-3). **Default: `False` → zero behaviour change.**

Two latent defects existed in `_handle_failure` with the flag OFF (the historical
default, preserved exactly):

1. **Attempt count was hardcoded to `1`** — the `attempt >= max_retries`
   dead-letter clause was unreachable, so a `RetryableError` could *only* be
   dead-lettered via a `FatalError`, never via retry exhaustion.
2. **Silent skip on failure** — a failed message left its offset *uncommitted*,
   but librdkafka's in-memory position had already advanced. The next message
   that succeeded committed *past* the failed offset, silently dropping it.

Setting `enable_persistent_retry=True` fixes both, but **requires the consumer
to also provide a durable attempt store** by overriding two hooks (default
no-ops, so non-opted consumers are unaffected):

| Hook | Default | Override to |
|------|---------|-------------|
| `async _get_attempt_count(event_id) -> int` | returns `0` | read prior-failure count from a durable `failed_events(consumer_group, event_id, attempt, last_error, last_error_at)` table |
| `async _record_attempt(event_id, attempt, error) -> None` | no-op | upsert the latest attempt + error |

With the flag ON:

- `attempt = _get_attempt_count(event_id) + 1` (the **real** count).
- On `FatalError` or `attempt >= max_retries`: `dead_letter(..., reason=...)`
  **and commit the offset** so the consumer advances past the poison message.
- Otherwise: `_record_attempt(...)`, then **seek back** to the failed offset
  (`_seek_back`, exponential full-jitter backoff bounded by
  `max_backoff_seconds`) so the message is redelivered instead of skipped.
  The offset is **not** committed.

**Metric:** `kafka_messages_dead_lettered_total{service, topic, reason}` is a
global cross-service counter incremented on **every** dead-letter (both the
FatalError and retry-exhaustion paths), so it fires for non-opted consumers too.

**Rollout (per-consumer, deliberately separate from the library change):**

1. Add a `failed_events(consumer_group, event_id, attempt, last_error,
   last_error_at, PRIMARY KEY (consumer_group, event_id))` table via an Alembic
   migration in the opting-in service.
2. Override `_get_attempt_count` / `_record_attempt` to read/write that table
   (reuse the service's existing session factory and dedup-table pattern).
3. Set `enable_persistent_retry=True` in that consumer's `ConsumerConfig`.
4. Deploy and watch `kafka_messages_dead_lettered_total` + the
   `failed_events` table.

Do **not** flip the flag without steps 1–2: without a durable store the attempt
count resets to `0` on every redelivery and the message loops until
`dead_letter_cap` trips.

### Consumer connection-setup resilience (FAILURE MODE 2)

`ConsumerConfig` carries consumer-local connection knobs that override the
shared base (`messaging.kafka_config._BASE_RDKAFKA_CONFIG`) for consumers only —
producers keep the base values. These directly address the wedge signature
`GroupCoordinator: Connection setup timed out in state CONNECT (after ~31000ms)`:

| Field | Default | rdkafka key | Why |
|-------|---------|-------------|-----|
| `socket_connection_setup_timeout_ms` | `10_000` | `socket.connection.setup.timeout.ms` | The shared base is 30s (+jitter ≈ 31s). A coordinator CONNECT that hasn't handshaked in 10s is almost certainly dead — abort fast so the BP-700 in-loop reconnect retries promptly instead of burning ~31s per attempt. |
| `connections_max_idle_ms` | `540_000` | `connections.max.idle.ms` | Tear down an idle socket (9 min) before a host-sleep / NAT / LB idle-cutoff leaves a half-dead connection that hangs until the next poll fails. |

Both are dataclass fields → env/settings-retunable. The values are spread on top
of the base in `to_dict()`, so producer config (a separate workstream) is
unaffected.

### Run()-task supervision (`messaging.kafka.consumer.supervisor`)

`run_consumer_supervised(consumer, stop_event, *, liveness_probe=...)` is the
standalone-`_main.py` entry-point wrapper that replaces the historical
`create_task(consumer.run()); await stop_event.wait()` shape. That shape wedged
the process: if `run()` raised (e.g. the initial connect hit the
connection-setup timeout), the task became a failed Future nobody awaited
(`Task exception was never retrieved`) while `main()` parked forever on
`stop_event.wait()` — process up, HTTP healthcheck green, zero progress.

The supervisor **races** `run()` against the stop event:

* `run()` raises → logs `consumer_run_task_crashed` (critical) and raises
  `ConsumerExited` (original error as `__cause__`) so the entry point
  `sys.exit(1)`s and Docker/k3s restarts the container.
* Stop signalled → `consumer.stop()`, drain up to `graceful_stop_timeout_s`,
  cancel on overrun, return normally (exit 0).
* `run()` returns on its own (never happens for a healthy consumer) → treated as
  an unexpected exit → `ConsumerExited`.

Pass a `liveness_probe` (see below) and the run() task is attached to it so
`/healthz` flips to 503 the instant `run()` finishes — even on a crash before
the first poll-loop heartbeat. **Scope:** the supervisor lives at the entry-point
layer and does NOT touch the in-loop BP-700 reconnect in
`messaging.kafka.consumer.base` (that is the PLAN-0113 surface); the two compose
— base.py survives *transient* blips, the supervisor fails loudly on a
*terminal* run() exit.

### Consumer liveness probe (`observability.make_liveness_probe`)

`make_liveness_probe()` returns a `ConsumerLivenessProbe` — a callable
`() -> bool` wired into `start_metrics_server(..., liveness_probe=...)` so
`/healthz` reflects real poll-loop progress instead of always returning 200:

```python
liveness = make_liveness_probe()
start_metrics_server(service_name=..., liveness_probe=liveness)
liveness.bind(consumer)   # after the consumer is constructed
await run_consumer_supervised(consumer, stop_event, liveness_probe=liveness)
```

Health rules: healthy while unbound (startup); unhealthy once the attached
run() task finishes; healthy with no progress tick only within `startup_grace_s`
of `bind`; otherwise healthy iff `seconds_since_progress() <= stale_after_s`. It
reads the consumer's BP-700 heartbeat (`seconds_since_progress`) but owns none of
the reconnect logic.

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
| `load_schema(path: str) -> dict` | Load + fastavro-parse an Avro schema from a `.avsc` file. |
| `serialize_avro(schema: dict, record: dict) -> bytes` | Schemaless Avro binary encoding. |
| `deserialize_avro(schema: dict, data: bytes) -> dict` | Schemaless Avro binary decoding. |
| `serialize_confluent_avro(schema_path: str, record: dict, schema_id: int = 0) -> bytes` | Build the Confluent 5-byte wire-format header (`0x00` magic + 4-byte big-endian `schema_id`) and append the Avro body. Takes the `.avsc` **path** (not a parsed schema) and loads it internally. |
| `deserialize_confluent_avro(schema_path: str, data: bytes, *, expected_schema_ids: set[int] \| None = None) -> dict` | Strip the 5-byte Confluent header (validates the `0x00` magic byte) and decode against the schema at `schema_path`. When `expected_schema_ids` is given, the embedded schema id is checked against it first and a mismatch raises `ValueError` (PLAN-0062 F-020). |
| `serializer_for_schema(schema_str: str, registry) -> AvroSerializer` | Convenience wrapper around `build_avro_serializer` with default config. |
| `decimal_to_str(d: Decimal) -> str` | `Decimal` → fixed-point string for Avro `string` fields. |
| `iso_datetime(dt: datetime) -> str` | `datetime` → ISO-8601 string for Avro `string` fields. |

> Module-level `KNOWN_TOPIC_SCHEMA_IDS: dict[str, set[int]]` is an empty
> registry consumers may populate at startup to feed `expected_schema_ids`.

### Schema Registry (`messaging.kafka.schema_registry`)

| Symbol | Purpose |
|--------|---------|
| `SchemaRegistryConfig` | Confluent Schema Registry connection config (URL, auth, TLS). |
| `build_schema_registry_client(config)` | Factory for `confluent_kafka.schema_registry.SchemaRegistryClient`. |

### Outbox Dispatcher (`messaging.kafka.dispatcher`)

| Symbol | Purpose |
|--------|---------|
| `BaseOutboxDispatcher` | Lease-based outbox publisher. Hybrid: `dispatch_now()` inline + background `run()` poll loop. **Pipelined batch dispatch**: a batch is produced in full, then a single `flush()` awaits all ACKs (not one flush/ACK per record), and the run loop re-polls immediately after a *full* batch (drain-when-full) instead of sleeping — both are required to keep up with high-volume producers (the Polymarket CLOB firehose). Marks records published only after Kafka ACK; a never-ACKed record is retried, never lost. Dead-letters records exceeding `max_attempts`. |
| `DispatcherConfig` | All knobs: `poll_interval_seconds`, `idle_poll_interval_seconds`, `lease_seconds`, `batch_size`, `max_attempts`, `initial_backoff_seconds`/`max_backoff_seconds`/`backoff_multiplier`, `delivery_timeout_seconds`, `immediate_dispatch`, `continue_when_batch_full` (default `True` — re-poll immediately after a full batch), `worker_id` (auto-generated `<hostname>-<uuid8>` when empty). |
| `DeliveryResult` | Outcome of one dispatch: `record_id`, `success`, `topic`, `error`. |
| `OutboxRecordProtocol` | Structural type for outbox table rows: `id`, `event_type`, `topic`, `payload`, `attempts`, `leased_until`, and optional `partition_key` (when set, used as the Kafka message key for per-aggregate ordering — F-DATA-06; read via `getattr` so legacy rows without it still work). |
| `OutboxRepositoryProtocol` | Port for outbox table: `fetch_pending`, `mark_published`, `increment_attempts`, `move_to_dead_letter`. |
| `UnitOfWorkWithOutboxProtocol` | UoW that exposes `.outbox` repository + `commit`/`rollback`. |
| `run_dispatcher(dispatcher)` | Coroutine — run in a background task via `asyncio.create_task(run_dispatcher(d))`. |

**Abstract methods for `BaseOutboxDispatcher`:**

| Method | Purpose |
|--------|---------|
| `get_unit_of_work()` | Return fresh async UoW implementing `UnitOfWorkWithOutboxProtocol`. |
| `get_serializer(event_type)` | Avro value serializer callable for the given `event_type`. |
| `get_producer()` | Confluent `SerializingProducer` instance. |
| `on_delivery_failure(result)` *(optional)* | Override to add alerting on dead-letter. The default logs `error_type` + `repr` so an empty-`str` `TimeoutError` can never hide a wedged producer. |
| `register_notify_listener(on_notify)` *(optional)* | Override to wire a Postgres `LISTEN` (see below). Default returns `None` → legacy polling. |

**LISTEN/NOTIFY wakeup (LIB-003, opt-in):** `DispatcherConfig` carries two
poll intervals — `poll_interval_seconds` (default `5.0`, used when LISTEN/NOTIFY
is **not** wired) and `idle_poll_interval_seconds` (default `60.0`, the safety-net
poll used **when** it is wired). A Postgres-backed subclass overrides
`register_notify_listener(on_notify)` to `LISTEN` on channel
`OUTBOX_NOTIFY_CHANNEL` (`"outbox_events_new"`, exported from
`messaging.kafka.dispatcher.base`) and call `on_notify()` on each NOTIFY; the
run loop then wakes within microseconds of a new insert instead of polling.
Producers attach an AFTER-INSERT trigger that runs `NOTIFY outbox_events_new`:

```sql
CREATE OR REPLACE FUNCTION outbox_notify() RETURNS trigger AS $$
BEGIN
    NOTIFY outbox_events_new;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER outbox_events_notify
    AFTER INSERT ON outbox_events
    FOR EACH ROW EXECUTE FUNCTION outbox_notify();
```

The default `register_notify_listener` returns `None`, so services that have not
opted in keep the 5s poll. A `LISTEN` failure (e.g. SQLite in tests) is caught
and the dispatcher falls back to polling.

**Throughput / draining a backlog (BP outbox-dispatcher-throughput).** The base
`_dispatch_batch` uses `_dispatch_records_pipelined`: it produces the whole
leased batch (in FIFO `created_at` order, forwarding `partition_key` as the Kafka
key) and then issues **one** `flush()` for the batch. The historical path
produced→flushed→awaited each record individually, so a batch of N rows paid N
sequential broker round-trips — under the Polymarket CLOB history/trades firehose
the single FIFO dispatcher could not keep up and `content_ingestion_db.outbox_events`
grew unbounded (~111k rows). Guarantees are unchanged: **ordering** is preserved
(librdkafka keeps per-partition produce order; same-`partition_key` rows share a
partition), and **at-least-once** holds (a row is `mark_published` only when its
delivery callback fires success; produce-time raises, flush failures, and
never-ACKed rows all `increment_attempts` → retry / dead-letter). Combined with
drain-when-full (`continue_when_batch_full`, the run loop skips the
`poll_interval` sleep after a full batch) this lifts steady-state throughput from
`~batch_size / poll_interval` rows/s to broker/DB-bound (hundreds→>1k rows/s).
Services can raise `batch_size` (content-ingestion defaults to `500`) to amortise
the per-batch DB fetch/commit + flush over more rows.

### Valkey Client (`messaging.valkey`)

| Symbol | Purpose |
|--------|---------|
| `ValkeyClient` | Async Redis/Valkey client over `redis.asyncio` with connection pooling. Constructed as `ValkeyClient(config=...)` or `ValkeyClient(url=...)`. See the method list below. |
| `ValkeyConfig` | Connection config (`host`, `port`, `db`, `password`, `username`, `max_connections`, `socket_timeout`, `socket_connect_timeout`, `decode_responses`, `ssl`). Has a `from_url(url, **overrides)` classmethod and a `.url` property. |
| `create_valkey_client(config: ValkeyConfig) -> ValkeyClient` | **Synchronous** factory from a `ValkeyConfig`. |
| `create_valkey_client_from_url(url: str) -> ValkeyClient` | **Synchronous** factory from a Redis-style URL string. Do NOT `await` it. |

**`ValkeyClient` method surface** (all `async`):

- Strings/keys: `get`, `set(key, value, ttl=None, *, ex=None)`, `set_nx(key, value, ex)`,
  `setex(key, seconds, value)`, `delete`, `delete_many`, `delete_pattern`,
  `getdel`, `exists`, `incr`, `incrbyfloat`, `expire`, `ttl`
- JSON: `get_json`, `set_json(key, value, ttl=None)` (no `mget_json` — use `mget`)
- Batch: `mget(keys) -> list[str | None]`, `mset(mapping)`
- Hashes: `hget`, `hset`, `hgetall`, `hdel`
- Lists: `lpush`, `rpush`, `lpop`, `rpop`, `lrange`, `llen`
- Sorted sets: `zadd`, `zrangebyscore`, `zremrangebyscore`, `zcard`
- Pub/sub: `publish(channel, message)`, `subscribe(*channels)` (async ctx mgr → `PubSub`)
- Scripting / batching: `execute_lua_script(script, keys, args)`,
  `pipeline(*, transaction=False)` (async ctx mgr → redis pipeline)
- Connection: `ping`, `close`

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

### Shared Async Engine Factory (`messaging.pg.engine_factory`)

> Added 2026-07-23 (BP-732 Recurrence 2 fix). See `docs/BUG_PATTERNS.md` BP-732
> and `docs/audits/2026-07-23-bottleneck-postgres-oom-pooling.md`.

Three independent Postgres connection-hardening passes (`bea446831`,
`0d0f27119`, `f1d04b8e5`) each landed in only 1-2 services because every
service hand-rolled its own `connect_args` dict in its own
`infrastructure/db/session.py`. `build_async_engine` is the ONE place that
assembles the proven-correct shape, so a future hardening lesson is a
one-file change instead of an N-service hand-edit.

```python
from messaging.pg.engine_factory import build_async_engine

engine = build_async_engine(
    settings.database_url.get_secret_value(),
    pooled=True,                    # this DB connection routes through PgBouncer
    application_name="rag-chat",    # required — surfaces in pg_stat_activity (BP-502)
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=300,
    pool_pre_ping=True,
)
```

```python
def build_async_engine(
    dsn: str,
    *,
    pooled: bool,
    command_timeout_s: float = 600.0,      # DEFAULT_COMMAND_TIMEOUT_S
    statement_timeout_ms: int = 8_000,     # DEFAULT_STATEMENT_TIMEOUT_MS
    application_name: str,
    pool_size: int = 10,
    max_overflow: int = 20,
    pool_recycle: int = 300,
    pool_pre_ping: bool = True,
    pool_timeout: float | None = None,
    connect_timeout_s: float | None = None,
    echo: bool = False,
    extra_connect_args: dict[str, object] | None = None,
) -> AsyncEngine: ...
```

| Param | Purpose |
|-------|---------|
| `pooled` | `True` disables asyncpg's and SQLAlchemy's prepared-statement caches (`statement_cache_size=0`, `prepared_statement_cache_size=0`) — required because server-side prepared statements do not survive across PgBouncer transaction-pooled connections. `False` omits them (harmless either way when connecting direct). |
| `command_timeout_s` | Client-side asyncpg `command_timeout` (seconds). Bounds waiting for a command on an ALREADY-established connection — the fix for the 2026-07-21 2.4h article-pipeline wedge (a half-open dead connection hung forever without this). `<= 0` disables it. |
| `statement_timeout_ms` | Server-side `statement_timeout` (milliseconds), applied via `server_settings`. Caps any single query at the Postgres level. `<= 0` disables it. |
| `connect_timeout_s` | asyncpg's own connect-level `timeout` (DNS + TCP handshake) — a DIFFERENT knob from `command_timeout_s`. Only pass this if the service needs to bound establishing a NEW connection (e.g. `alert`'s PLAN-0088 P0-4 DNS-hiccup hardening). |
| `extra_connect_args` | Escape hatch: additional connect kwargs merged on top of (and able to override) the factory's own — use sparingly; prefer promoting a genuinely shared setting into a named parameter. |

**Migrated services** (as of 2026-07-23): `rag-chat`, `content-store`, `alert`,
`market-ingestion` — all pass `pooled=True`. **Intentionally NOT migrated:**
`content-ingestion` and `portfolio` stay on direct (non-PgBouncer) connections
because of session-scoped AGE/advisory-lock state (see BP-732); `market-data`
has its own independently-hardened session module with Prometheus pool gauges
and a fail-fast pool and was left as a follow-up.

**CI backstop:** `scripts/check_db_session_parity.py` greps every service's
`infrastructure/*/session.py` for the pooled signal and the two timeout knobs,
warning (or `--strict` failing) if a pooled service is missing a knob another
pooled service already has. Wired into `.github/workflows/ci.yml` as a
warn-only job (`db-session-parity`) — it currently reports `market-data` as a
residual gap, which is expected (out of scope for the 2026-07-23 fix).

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
| `get_daily_credits_used(day)` | `int` | Cumulative credits consumed on `day` (UTC, defaults to today). The true daily-spend source `DailyBudgetTracker` reads — not derived from token-bucket depletion. |
| `get_by_service(service, month)` | `int` | Credits used by one service this month. |
| `get_by_symbol(symbol, month)` | `int` | Credits used for one symbol this month. |

`try_consume` can also return `QuotaCheckResult.OK` (below the soft limit).
Class constants `EodhdQuotaService.HARD_LIMIT` (100,000) and
`SOFT_LIMIT_RATIO` (0.80) are the defaults; both are overridable per instance.

Valkey keys (32-day TTL on monthly keys, 2-day TTL on the daily key,
all auto-expiring):

```
eodhd:v1:quota:{YYYY-MM}:credits_used                 # total monthly counter
eodhd:v1:quota:{YYYY-MM}:{service}:credits_used       # per-service attribution
eodhd:v1:quota:{YYYY-MM}:symbol:{sym}:credits_used    # per-symbol attribution
eodhd:v1:quota:day:{YYYY-MM-DD}:credits_used          # cumulative per-UTC-day
```

### Processed-Events Cleanup Worker (`messaging.kafka.maintenance`)

Stateless retention enforcer for the per-service `processed_events`
idempotency table. Not re-exported at the package root (it imports
`sqlalchemy`); import the concrete path:

```python
from messaging.kafka.maintenance.processed_events_cleanup import (
    ProcessedEventsCleanupWorker,
)

worker = ProcessedEventsCleanupWorker(
    service_name="content-store",   # keyword-only; used for structured logging
    retention_days=30,              # rows older than now() - retention_days are deleted
    batch_size=10_000,              # rows deleted per committed transaction
)
deleted = await worker.run_once(session)   # pass a fresh AsyncSession per invocation
```

| Member | Purpose |
|--------|---------|
| `ProcessedEventsCleanupWorker(*, service_name, retention_days=30, batch_size=10_000)` | Constructor; `retention_days` and `batch_size` must be `> 0` (else `ValueError`). |
| `async run_once(session: AsyncSession) -> int` | Run one cleanup pass in batches, committing per batch; returns total rows deleted. Stops when a batch returns fewer than `batch_size` rows. |

Schedule `run_once` daily (e.g. 02:00 UTC) from the service's scheduler or a
dedicated `*_cleanup_main.py` process. Class defaults are exposed as
`DEFAULT_RETENTION_DAYS`, `BATCH_SIZE`, and `INTER_BATCH_SLEEP_SECONDS`.

### Generic Table Retention Pruner (`messaging.kafka.maintenance.table_retention`)

`RetentionCleanupWorker` is a generalisation of the processed-events cleanup for
**any** unbounded append/log table. It was added after the **2026-07-18 Postgres
disk-full outage**, whose root cause was that the outbox dispatcher marks rows
`status='delivered'` but NEVER pruned them — `content_ingestion_db.outbox_events`
grew to 7.2 GB / 4.3M rows (the claimable partial index only covers
`pending`/`processing`, so delivered rows are invisible and accumulate forever).
Two other tables had the same shape: `prediction_market_fetch_log` (3.8M rows /
1.1 GB) and `market_data_db.ingestion_events` (~1 GB).

```python
from datetime import timedelta
from messaging.kafka.maintenance import (
    RetentionCleanupWorker, RetentionPolicy, build_retention_loop_coros,
)

worker = RetentionCleanupWorker(
    policy=RetentionPolicy(
        table="outbox_events",
        pk_column="id",
        age_column="dispatched_at",
        retention=timedelta(hours=1),
        status_column="status",       # OPTIONAL equality filter
        status_value="delivered",     # only delivered rows are ever deleted
    ),
    service_name="content-ingestion",
    batch_size=10_000,                # rows per committed transaction
    max_batches=200,                  # per-pass safety cap (drains huge backlogs across passes)
    interval_seconds=300.0,           # this worker's own scheduling cadence
)
```

| Member | Purpose |
|--------|---------|
| `RetentionPolicy(table, pk_column, age_column, retention, status_column=None, status_value=None)` | Declarative prune spec. Identifiers are validated against `^[A-Za-z_][A-Za-z0-9_]*$`; `retention` must be positive; `status_value` required when `status_column` set. |
| `RetentionCleanupWorker(*, policy, service_name, batch_size=10_000, max_batches=None, interval_seconds=300.0, inter_batch_sleep_seconds=0.1)` | Batched pruner; commits per batch (autocommit-per-batch → flat WAL). Each worker owns its `interval_seconds` cadence, so hot tables prune more often than slow ones. |
| `async run_once(session, *, now=None) -> int` | One pass; `DELETE ... WHERE pk IN (SELECT pk ... WHERE age_column < cutoff [AND status=...] ORDER BY age_column LIMIT n [FOR UPDATE SKIP LOCKED])`. `FOR UPDATE SKIP LOCKED` emitted for PostgreSQL only (dialect-detected; SQLite tests omit it). |
| `async run_retention_loop(*, worker, session_factory, interval_seconds, stop_event, initial_delay_seconds=0.0)` | Fail-open periodic loop; fresh session per pass; stops on `stop_event`. |
| `build_retention_loop_coros(*, workers, session_factory, stop_event)` | Returns one zero-arg coroutine factory per worker (for `asyncio.create_task`), each running at its own `worker.interval_seconds`, staggered. |

**Wiring (no new deployment):** each owning service hosts the pruner inside its
already-running **outbox dispatcher process** (`*/outbox/dispatcher_main.py`),
using the dispatcher's write session factory:

- `content-ingestion` dispatcher_main → `outbox_events` (delivered, 1h retention /
  300s cadence) + `prediction_market_fetch_log` (14d retention / 3600s cadence).
  Env: `CONTENT_INGESTION_OUTBOX_RETENTION_SECONDS`,
  `..._OUTBOX_PRUNE_{BATCH_SIZE,INTERVAL_SECONDS,MAX_BATCHES}`,
  `..._PREDICTION_FETCH_LOG_RETENTION_DAYS` (+ `..._PRUNE_{BATCH_SIZE,INTERVAL_SECONDS,MAX_BATCHES}`).
- `market-data` dispatcher_main → `outbox_events` (delivered, 1h retention /
  300s cadence — same latent delivered-pileup bug, pruned pre-emptively) +
  `ingestion_events` (14d retention / 3600s cadence). Env:
  `MARKET_DATA_OUTBOX_RETENTION_SECONDS` (+ `..._OUTBOX_PRUNE_{BATCH_SIZE,INTERVAL_SECONDS,MAX_BATCHES}`),
  `MARKET_DATA_INGESTION_EVENTS_RETENTION_DAYS` (+ `..._PRUNE_{BATCH_SIZE,INTERVAL_SECONDS,MAX_BATCHES}`).

Set any retention window to `0` to disable that table's pruner. **The outbox
pruner NEVER deletes `pending`/`processing`/`failed`/`dead_letter` rows.**

> **Space reclamation:** these deletes free space *inside* the table files but do
> NOT return it to the OS. After the first prune of a bloated table, run a
> maintenance-window `VACUUM FULL <table>` or `pg_repack` (with a temporary
> `maintenance_work_mem` bump) to shrink the physical files — routine
> autovacuum only prevents *further* growth.

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

# The factory is SYNCHRONOUS — construct without await; the I/O methods are async.
client = create_valkey_client_from_url("redis://localhost:6379")
await client.set_json("md:v1:quote:AAPL", {"price": 150.0}, ttl=30)
quote = await client.get_json("md:v1:quote:AAPL")
# There is no mget_json — fetch raw and decode, or call get_json per key.
raw = await client.mget(["md:v1:quote:AAPL", "md:v1:quote:MSFT"])
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
