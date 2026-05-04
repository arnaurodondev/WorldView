# Bug Patterns — Kafka & Messaging

> **Category**: kafka-messaging
> **Description**: Kafka consumers/producers, Avro serialization, outbox pattern, DLQ, Schema Registry, topic routing, message retention, idempotency
> **Count**: 34 patterns
> **Back to index**: [BUG_PATTERNS.md](../BUG_PATTERNS.md)

---

## BP-001 — OutboxKafkaValue not serialized to bytes

**Date discovered**: 2026-03-09
**Service affected**: `portfolio` (found during `make run-dispatcher`)
**Prompts updated**: `0003-exec-market-ingestion-migration-wave-02.md` T-MI-21 steps 7–8; `0003-exec-market-ingestion-migration-wave-03.md` T-MI-22 step 2

### Symptom

The outbox dispatcher starts and picks up pending records, but every delivery
attempt fails with:

```
error="a bytes-like object is required, not 'OutboxKafkaValue'"
```

Log lines show `outbox_record_dispatch_failed` for every record, cycling until
`max_attempts` is exceeded and records are dead-lettered.

### Root causes (two independent bugs, both required to fix)

#### Bug A — Wrong serializer class used (`KafkaEventValueSerializer` vs `OutboxEventValueSerializer`)

`KafkaEventValueSerializer.__call__` passes the raw `value` argument directly to
the per-type `AvroSerializer`:

```python
# KafkaEventValueSerializer — WRONG for outbox use
return serializer(value, ctx)   # value is OutboxKafkaValue — Avro rejects it
```

`AvroSerializer` expects a plain `dict` matching the Avro schema, not the
`OutboxKafkaValue` wrapper dataclass. This causes the bytes error.

`OutboxEventValueSerializer` (a subclass in `libs/messaging/src/messaging/kafka/producer.py`)
overrides `__call__` to extract `.payload` first:

```python
# OutboxEventValueSerializer — CORRECT for outbox use
return serializer(value.payload, ctx)   # plain dict — Avro accepts it
```

**Fix**: Always use `OutboxEventValueSerializer`, never `KafkaEventValueSerializer`,
when building a value serializer for an outbox dispatcher.

#### Bug B — `value_serializer=` not wired into `build_serializing_producer()`

```python
# WRONG — no value_serializer, producer silently accepts any Python object
return build_serializing_producer(producer_config)

# CORRECT — value_serializer wired in
value_serializer = OutboxEventValueSerializer(self._serializers)
return build_serializing_producer(producer_config, value_serializer=value_serializer)
```

`SerializingProducer` accepts the call without a serializer and only fails at
delivery time — making this a silent misconfiguration that only surfaces on
first dispatch attempt.

### Correct implementation pattern

Every `BaseOutboxDispatcher` subclass must implement `_build_producer()` with
this exact three-step sequence:

```python
def _build_producer(self) -> Any:
    # Step 1 — build per-event-type AvroSerializer dict
    registry_client = build_schema_registry_client(registry_config)
    self._serializers = build_outbox_event_serializers(registry_client)

    # Step 2 — wrap in OutboxEventValueSerializer (NOT KafkaEventValueSerializer)
    value_serializer = OutboxEventValueSerializer(self._serializers)

    # Step 3 — pass value_serializer= explicitly (NOT optional)
    producer_config = KafkaProducerConfig(bootstrap_servers=...)
    return build_serializing_producer(producer_config, value_serializer=value_serializer)
```

### Test to add (prevents regression)

```python
def test_outbox_value_serializer_extracts_payload():
    """OutboxKafkaValue.payload must be passed to AvroSerializer, not the wrapper."""
    mock_avro = MagicMock(return_value=b"avro-bytes")
    ser = OutboxEventValueSerializer({"my.event": mock_avro})
    value = OutboxKafkaValue(event_type="my.event", payload={"foo": 1})
    result = ser(value, ctx=None)
    # The serializer must have been called with the plain dict, not the wrapper
    mock_avro.assert_called_once_with({"foo": 1}, None)
    assert result == b"avro-bytes"

def test_raw_avro_serializer_rejects_wrapper():
    """Confirm that passing OutboxKafkaValue directly to AvroSerializer fails —
    this documents why OutboxEventValueSerializer is required."""
    mock_avro = MagicMock(side_effect=TypeError("bytes-like object required"))
    ser = KafkaEventValueSerializer({"my.event": mock_avro})
    value = OutboxKafkaValue(event_type="my.event", payload={"foo": 1})
    with pytest.raises(TypeError):
        ser(value, ctx=None)
```

### Files changed in fix

| File | Change |
|------|--------|
| `libs/messaging/src/messaging/kafka/producer.py` | Added `OutboxEventValueSerializer.__call__` override that extracts `.payload` |
| `services/portfolio/src/portfolio/messaging/dispatcher.py` | Imported `OutboxEventValueSerializer`; wired `value_serializer=` into `build_serializing_producer()` |

---

---

## BP-009 — DispatcherProcess passes raw Kafka dict as DispatcherConfig

**Date discovered**: 2026-03-10
**Service affected**: `market-ingestion` (found during `test_dispatcher_starts_and_stops_cleanly`)

### Symptom

```
AttributeError: 'dict' object has no attribute 'worker_id'
```

The `DispatcherProcess.__init__` constructs a dict
`{"bootstrap.servers": ...}` and passes it as the `config=` argument to
`build_<service>_dispatcher()`. The factory expects a `DispatcherConfig`
dataclass, not a raw dict.

### Root cause

The original code confused the Kafka producer config dict (used inside the
dispatcher for `SerializingProducer`) with the `DispatcherConfig` dataclass
(tuning parameters for the poll loop). These are completely different objects.
The `build_*_dispatcher` factory already handles constructing the
`DispatcherConfig` from `Settings`; callers should not pass it at all unless
they need to override defaults.

### Correct implementation pattern

```python
# WRONG
kafka_config = {"bootstrap.servers": settings.kafka_bootstrap_servers}
dispatcher = build_service_dispatcher(settings=settings, write_factory=wf, config=kafka_config)

# CORRECT — let the factory derive DispatcherConfig from settings
dispatcher = build_service_dispatcher(settings=settings, write_factory=wf)
```

The `build_*_dispatcher` factory creates `DispatcherConfig` from `settings`
attributes (e.g. `settings.dispatcher_poll_interval_seconds`). The Kafka
`bootstrap.servers` is consumed inside the dispatcher's `_build_producer()`
via `settings.kafka_bootstrap_servers`.

### Files changed in fix

| File | Change |
|------|--------|
| `services/market-ingestion/src/market_ingestion/messaging/dispatcher_main.py` | Removed `kafka_config` dict and `config=kafka_config` from `build_market_ingestion_dispatcher` call |

---

---

## BP-017 — Outbox payload fields mismatch Avro schema

**Date discovered**: 2026-03-26
**Service affected**: `content-ingestion` (found during QA review)

### Symptom

`SerializationError` at dispatcher time, or fields silently dropped. The outbox payload used field names like `url`, `minio_key` while the Avro schema expected `source_url`, `minio_bronze_key`.

### Root cause

Outbox payload was built with domain field names instead of Avro schema field names. No compile-time or test-time validation of the payload structure.

### Correct implementation pattern

Build payloads using a dedicated helper that maps to Avro field names:

```python
def build_raw_article_payload(*, doc_id, source_type, source_url, minio_bronze_key, ...):
    return {"event_id": ..., "source_url": source_url, "minio_bronze_key": minio_bronze_key, ...}
```

Add a test that asserts payload keys match the Avro schema fields.

---

---

## BP-020 — DLQ `move_to_dead_letter` only updates status without copying payload

**Date discovered**: 2026-03-28
**Services affected**: `content-store` (found during multi-agent QA review)
**Prompts updated**: `PLAN-0001-B-R2` tasks T-R2-1-03, T-R2-1-04, T-R2-1-06

### Symptom

Dead-lettered events are invisible to the `/admin/dlq` API and cannot be requeued. The `move_to_dead_letter` method updates the outbox `status` column to `dead_letter` but does not INSERT a row into the `dead_letter_queue` table. Additionally, `requeue()` creates a new outbox event with `payload={}` (empty) instead of the original payload.

### Root cause

1. `move_to_dead_letter` was implemented as a simple status update (one SQL UPDATE) instead of the S4 pattern which also INSERTs a DLQ row with the original payload.
2. `DeadLetterQueueModel` was missing the `payload_json` column, so even if a DLQ row existed, there was no place to store the payload for requeue.
3. `requeue()` hardcoded `payload={}` instead of reading `entry.payload_json`.

### Correct implementation pattern

```python
async def move_to_dead_letter(self, record_id: UUID, error_detail: str = "") -> None:
    # 1. Fetch the outbox record
    record = await self._get_outbox_record(record_id)
    if not record:
        return
    # 2. INSERT a DLQ row with the original payload
    dlq = DeadLetterQueueModel(
        dlq_id=new_uuid7(),
        original_event_id=record.id,
        topic=record.topic,
        payload_json=record.payload,  # preserve original payload
        error_detail=error_detail,
    )
    self._session.add(dlq)
    # 3. Update outbox status
    record.status = OutboxStatus.DEAD_LETTER
```

For `requeue()`:
```python
async def requeue(self, dlq_id: UUID) -> None:
    entry = await self._get(dlq_id)
    # Use original payload, not empty dict
    await outbox_repo.append(..., payload=entry.payload_json or {})
```

### Test to add (prevents regression)

See `services/content-store/tests/unit/infrastructure/test_dlq_repo.py` — tests verify DLQ row creation and non-empty payload on requeue.

### Files changed in fix

| File | Change |
|------|--------|
| `services/content-store/src/content_store/infrastructure/db/repositories/outbox.py` | Fixed `move_to_dead_letter` to INSERT DLQ row |
| `services/content-store/src/content_store/infrastructure/db/repositories/dlq.py` | Fixed `requeue` to use `entry.payload_json` |
| `services/content-store/src/content_store/infrastructure/db/models.py` | Added `payload_json` column to `DeadLetterQueueModel` |
| `services/content-store/tests/unit/infrastructure/test_dlq_repo.py` | New — DLQ copy + requeue tests |

---

---

## BP-024 — DLQ requeue corrupts aggregate_id

**Date discovered**: 2026-03-27
**Service affected**: `content-store` (found during PLAN-0001-B-R4 QA review)
**Prompts updated**: `docs/plans/0001-b-r4-qa-review-fixes-plan.md` W1

### Symptom

Downstream consumers receive `content.article.stored.v1` events where `aggregate_id` is the outbox primary key UUID instead of the canonical document UUID. Lookups by document ID silently fail — no error, wrong entity referenced.

### Root cause

`DLQRepository.requeue()` created the new outbox event using `entry.original_event_id` (the outbox PK) as `aggregate_id` instead of the actual document UUID stored in `entry.aggregate_id`. Similarly, `event_type` was hardcoded instead of read from the DLQ row.

### Correct implementation pattern

```python
# WRONG — uses outbox PK as aggregate_id
self._session.add(OutboxEventModel(
    aggregate_id=entry.original_event_id,  # ← outbox PK, not doc UUID!
    event_type="content.article.stored.v1",  # ← hardcoded
    ...
))

# CORRECT — use stored metadata with fallback for pre-existing rows
self._session.add(OutboxEventModel(
    aggregate_id=entry.aggregate_id or entry.original_event_id,
    aggregate_type=entry.aggregate_type or "document",
    event_type=entry.event_type or entry.payload_json.get("event_type", "content.article.stored.v1"),
    ...
))
```

Also: `move_to_dead_letter` must store `aggregate_type`, `aggregate_id`, and `event_type` from the source outbox record into the DLQ row when creating it.

### Test to add (prevents regression)

```python
async def test_requeue_uses_stored_aggregate_id():
    entry = make_dlq_entry()
    entry.aggregate_id = UUID("doc-uuid-here")
    entry.original_event_id = UUID("outbox-pk-here")
    ...
    outbox_model = session.add.call_args.args[0]
    assert outbox_model.aggregate_id == entry.aggregate_id  # doc UUID, not outbox PK
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/content-store/src/content_store/infrastructure/db/repositories/dlq.py` | Use `entry.aggregate_id` with fallback |
| `services/content-store/src/content_store/infrastructure/db/repositories/outbox.py` | Store metadata fields in DLQ row |
| `services/content-store/alembic/versions/0001_create_content_store_schema.py` | Add `aggregate_type`, `aggregate_id`, `event_type` columns to `dead_letter_queue` |

---

---

## BP-029 — Content-hash dedup event_type key mismatch — dedup never fires

**Date discovered**: 2026-03-27
**Service affected**: `market-data` (ohlcv, quotes, fundamentals consumers)

### Symptom

Content-hash dedup never fires — identical canonical objects are re-downloaded and re-materialized on every tick.

### Root cause

`mark_processed()` stored `event_type=_TOPIC` (e.g., `"market.dataset.fetched"`) while `exists_by_content_hash()` queried with `event_type=_DATASET_TYPE` (e.g., `"ohlcv"`). The lookup always missed.

### Fix

Use the same value (`_DATASET_TYPE`) in both `mark_processed()` and `exists_by_content_hash()`.

---

---

## BP-034 — Content-hash dedup early return skips `mark_processed`

**Date discovered**: 2026-03-27
**Service affected**: `market-data` (ohlcv_consumer, quotes_consumer, fundamentals_consumer)

### Symptom

The same Kafka message is re-processed on replay even though the data was unchanged. The content-hash dedup path returns early without recording the event_id.

### Root cause

When `exists_by_content_hash(sha256, event_type)` returns `True`, the consumer returns early. But the `event_id` is never written to the `ingestion_events` table. On next replay the `is_duplicate()` check returns `False` (event_id not found) and the consumer re-processes.

### Fix

Call `await self.mark_processed(event_id)` before the early return so the event_id is always recorded:
```python
if sha256 and await uow.ingestion_events.exists_by_content_hash(sha256, _DATASET_TYPE):
    await self.mark_processed(event_id)   # ← ADD THIS
    return
```

---

---

## BP-035 — `is_duplicate()` check-then-insert race under concurrent consumers

**Date discovered**: 2026-03-27
**Service affected**: `market-data` (all three consumers)

### Symptom

Under rebalance or concurrent consumer scenarios, the same message is processed twice even though `ON CONFLICT DO NOTHING` exists on the dedup table.

### Root cause

The `is_duplicate()` SELECT and the `create()` INSERT happen in separate transactions. Two consumers can both pass the `is_duplicate()` check before either has committed the insert. The `ON CONFLICT DO NOTHING` prevents a duplicate row but does not prevent duplicate processing.

### Fix

Use a database-level lock or move the dedup INSERT to be the first operation inside the processing transaction. If the INSERT is rejected by the unique constraint, treat the event as a duplicate and skip processing.

---

---

## BP-039 — `EVENT_TOPIC_MAP.get(event_type, event_type)` silently routes to wrong topic

**Date discovered**: 2026-03-27
**Service affected**: `portfolio` (OutboxRepository)

### Symptom

Outbox events for a newly-added event type are published to a Kafka topic literally named after the event type string (e.g., `portfolio.holding.changed`), not the canonical topic name.

### Root cause

`claim_batch()` resolves topic as `EVENT_TOPIC_MAP.get(row.event_type, row.event_type)`. If the event type is missing from the map, the fallback is the event_type string itself — a spurious topic is created silently.

### Fix

Fail explicitly on missing entries:
```python
topic = EVENT_TOPIC_MAP.get(row.event_type)
if topic is None:
    raise ValueError(f"Unknown event_type for outbox routing: {row.event_type!r}")
```

---

---

## BP-040 — Idempotency `INSERT` missing `ON CONFLICT DO NOTHING`

**Date discovered**: 2026-03-27
**Service affected**: `portfolio` (IdempotencyRepository), `market-data` (IngestionEventRepository)

### Symptom

On Kafka message replay, the consumer crashes with `IntegrityError: duplicate key value violates unique constraint` instead of silently skipping the duplicate.

### Root cause

The idempotency record INSERT uses a plain `INSERT INTO` without `ON CONFLICT DO NOTHING`. The table has a unique constraint on `event_id`, so a replay raises instead of being ignored.

### Fix

```python
stmt = (
    insert(IdempotencyModel)
    .values(event_id=event_id)
    .on_conflict_do_nothing(constraint="pk_idempotency")
)
```

---

---

## BP-042 — FailureInfo[None] missing value/key/headers fields

**Affects**: `BaseKafkaConsumer[None]` implementations — `dead_letter()` and `process_message_from_failure()`

### Symptom

```
AttributeError: 'FailureInfo' object has no attribute 'value'
mypy: "FailureInfo[None]" has no attribute "value"
```

### Root cause

`FailureInfo[TFailure]` stores the original message in typed form. When `TFailure = None`, the consumer never parses the raw Kafka message into a domain object, so `FailureInfo[None]` has **no** `value`, `key`, or `headers` fields — only:

- `event_id: str`
- `topic: str`
- `partition: int`
- `offset: int`
- `attempt: int`
- `last_error: str`
- `record: Any` (the raw Kafka ConsumerRecord)

### Fix

In `dead_letter()`: use `failure.event_id` for identification, not `failure.value`.
In `process_message_from_failure()`: the original payload is not recoverable — log a warning and return without reprocessing.

```python
def dead_letter(self, failure: FailureInfo[None]) -> None:
    # failure.value does NOT exist — use event_id for the DLQ entry
    asyncio.create_task(self._write_dlq(event_id=failure.event_id, ...))

async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
    # Original payload is not recoverable for TFailure=None consumers
    logger.warning("cannot_reprocess_failure", event_id=failure.event_id)
```

---

## BP-045 — Non-atomic consumer dedup: `is_duplicate` + `process_message` + `mark_processed` in separate transactions

**Category**: Idempotency / Concurrency
**Services affected**: portfolio `InstrumentEventConsumer` (fixed 2026-03-28), any `BaseKafkaConsumer` subclass using 3-method dedup pattern
**First seen**: PLAN-0001-E QA-003

### Symptom

Two concurrent consumer instances process the same event. Both call `is_duplicate(event_id)` → both get `False`. Both proceed through `process_message()`. Both call `mark_processed(event_id)`. The event is processed twice.

### Root cause

The classic 3-method dedup pattern opens **three separate DB transactions**:

```python
# WRONG — 3 separate transactions, race window between each
async def is_duplicate(self, event_id):
    async with await self.get_unit_of_work() as uow:
        return await uow.idempotency.exists(uid)  # Transaction 1

async def process_message(self, ...):
    async with await self.get_unit_of_work() as uow:
        await uow.instruments.upsert(instrument)  # Transaction 2

async def mark_processed(self, event_id):
    async with await self.get_unit_of_work() as uow:
        await uow.idempotency.record(uid)  # Transaction 3
```

Between Transaction 1 returning `False` and Transaction 3 completing, another consumer instance can also pass the `is_duplicate` check.

### Fix

Apply BP-035: atomic `INSERT … ON CONFLICT DO NOTHING RETURNING` inside the **same transaction** as the business logic. `is_duplicate()` always returns `False`; `mark_processed()` is a no-op.

```python
# CORRECT — BP-035 pattern, single transaction
async def is_duplicate(self, event_id: str) -> bool:
    return False  # dedup handled atomically in process_message

async def mark_processed(self, event_id: str) -> None:
    pass  # dedup record inserted atomically in process_message

async def process_message(self, key, value, headers):
    async with await self.get_unit_of_work() as uow:
        # Atomic dedup: both INSERT and business logic in one transaction
        is_new = await uow.idempotency.create_if_not_exists(event_uid)
        if not is_new:
            return  # duplicate — skip
        await uow.instruments.upsert(instrument)
```

The `create_if_not_exists` implementation:

```python
async def create_if_not_exists(self, event_id: UUID) -> bool:
    stmt = (
        insert(IdempotencyModel)
        .values(event_id=event_id, processed_at=datetime.now(tz=UTC))
        .on_conflict_do_nothing()
        .returning(IdempotencyModel.event_id)
    )
    result = await self._session.execute(stmt)
    return result.scalar_one_or_none() is not None
```

### See also

BP-035 (Watermark dedup), BP-040 (idempotency INSERT missing ON CONFLICT)

---

---

## BP-050 — `asyncio.Event.set()` called from librdkafka delivery callback without `call_soon_threadsafe`

**Category**: Thread safety / async
**Services affected**: market-ingestion `OutboxDispatcher` (fixed 2026-03-28), any service using confluent-kafka delivery callbacks with asyncio synchronization primitives
**First seen**: PLAN-0001-E QA-028

### Symptom

Intermittent deadlocks, missed delivery signals, or rare `RuntimeError: no running event loop` in high-throughput scenarios. Under normal load the issue is latent and only manifests under contention.

### Root cause

```python
# WRONG — asyncio.Event mutated from a non-asyncio thread
def _cb(err, _msg):
    nonlocal delivery_error
    if err:
        delivery_error = RuntimeError(str(err))
    delivery_event.set()   # ← called from librdkafka C thread, not asyncio thread

loop = asyncio.get_event_loop()  # captured AFTER _cb definition — too late
producer.produce(..., callback=_cb)
await asyncio.wait_for(asyncio.shield(asyncio.get_event_loop().run_until_complete(...)), ...)
```

librdkafka delivery callbacks run on the librdkafka internal thread pool, which is not the asyncio event loop thread. Calling `asyncio.Event.set()` from a non-asyncio thread is not thread-safe.

### Fix

Capture `loop` **before** defining the callback, then use `loop.call_soon_threadsafe`:

```python
# CORRECT — thread-safe event signaling from delivery callback
loop = asyncio.get_event_loop()    # captured before _cb is defined

def _cb(err: Any, _msg: Any) -> None:
    nonlocal delivery_error
    if err is not None:
        delivery_error = RuntimeError(str(err))
    loop.call_soon_threadsafe(delivery_event.set)   # ← thread-safe

producer.produce(..., callback=_cb)
```

---

---

## BP-051 — Avro record name contains dots or version suffix — invalid Java identifier

**Category**: Avro schema / Schema Registry
**Services affected**: market-data Avro schemas (fixed 2026-03-28); any service that uses dots in Avro `"name"` field
**First seen**: PLAN-0001-E QA-015

### Symptom

Schema Registry registration fails:
```
SchemaRegistryException: Invalid schema: name "instrument.created.v1" is not a valid Avro name
```
Or: two services register schemas for the same logical event type under different subjects because one uses `"name": "instrument.created"` and another uses `"name": "InstrumentCreated"` — they are different subjects.

### Root cause

Avro record names must be valid Java identifiers: start with a letter or `_`, contain only letters, digits, and `_`. Dots are **namespace separators** in Avro fullnames (format: `namespace.Name`), not valid within the `"name"` field itself.

```json
// WRONG — dots in "name" field, version suffix
{ "type": "record", "name": "instrument.created.v1", "namespace": "com.worldview" }

// WRONG — dots in "name", no namespace
{ "type": "record", "name": "instrument.created" }
```

### Fix

Use PascalCase for the `"name"` field; version and path belong in the `"namespace"`:

```json
// CORRECT
{ "type": "record", "name": "InstrumentCreated", "namespace": "com.worldview.market_data.events" }
```

---

---

## BP-052 — Inconsistent Avro namespace creates divergent Schema Registry subjects

**Category**: Avro schema / Schema Registry
**Services affected**: portfolio watchlist Avro schemas (fixed 2026-03-28)
**First seen**: PLAN-0001-E QA-014

### Symptom

Two schemas for the same service use different namespaces (`"portfolio.events"` vs `"com.worldview.portfolio.events"`). The Schema Registry registers them under different subjects. One service registers `portfolio.events.WatchlistCreated-value`; the consumer expects `com.worldview.portfolio.events.WatchlistCreated-value`. Deserialization fails at runtime.

### Root cause

No enforced namespace convention. Different developers use different namespace styles.

```json
// WRONG — short namespace
{ "type": "record", "name": "WatchlistCreated", "namespace": "portfolio.events" }

// WRONG — inconsistent with other schemas in same service
{ "type": "record", "name": "WatchlistCreated", "namespace": "events" }
```

### Fix

Enforce **canonical namespace** across all schemas: `com.worldview.<service_name>.events`

```json
// CORRECT — canonical namespace
{ "type": "record", "name": "WatchlistCreated", "namespace": "com.worldview.portfolio.events" }
```

All schemas in a service **must** use the same namespace. Add a CI check to enforce this.

---

---

## BP-053 — `schema_version: ClassVar[int] = 0` footgun — subclasses emit version-0 events silently

**Category**: Event schema versioning
**Services affected**: market-data domain events (fixed 2026-03-28)
**First seen**: PLAN-0001-E QA-026

### Symptom

A consumer parses an event with `schema_version=0` and either crashes (unexpected version) or silently uses the wrong schema. Debugging is hard because the producer code appears correct — the subclass simply forgot to override `SCHEMA_VERSION`.

### Root cause

```python
# WRONG — base class default is 0 ("unset")
class DomainEvent:
    SCHEMA_VERSION: ClassVar[int] = 0

class QuoteUpdated(DomainEvent):
    # forgot to override SCHEMA_VERSION
    pass  # emits schema_version=0 silently
```

Version 0 is meaningless as a valid schema version. A default of 0 is indistinguishable from "forgot to set this".

### Fix

Set base class default to `1` (the minimum valid production version):

```python
# CORRECT — default 1 means "unversioned but valid"
class DomainEvent:
    SCHEMA_VERSION: ClassVar[int] = 1
```

Subclasses that intentionally use a higher version override it explicitly. Version 0 should never appear in production events and can be used as a signal for misconfiguration.


---

---

## BP-060

**Category**: Kafka / outbox — non-atomic event emission

**Symptom**: Events sometimes not dispatched (if `outbox_notifier` is missing or crashes after commit). Double-dispatch risk if `commit()` is called twice. Race between DB write and event emission.

**Root cause**: `uow.collect_event()` stores events in memory; they are emitted after `commit()` via the optional `outbox_notifier`. If the notifier is not wired, events are lost. Even if wired, there's a window between DB commit and notification.

**Fix**: Write directly to `outbox_events` within the same DB transaction as domain writes. The dispatcher polls and publishes atomically:

```python
# PREFERRED — atomic outbox write in consumer (no outbox_notifier needed)
event = InstrumentCreated(instrument_id=..., symbol=..., exchange=...)
await uow.outbox_events.create(
    event_type=event.event_type,
    topic=EVENT_TOPIC_MAP[event.event_type],
    payload=event_to_outbox_payload(event),
)
# event is committed atomically with the domain write in the same transaction
```

**Affected areas**: S3 consumers; any consumer emitting domain events that other services depend on.

---

---

## BP-063

**Category**: Kafka serialization — consumer format mismatch

**Symptom**: `json.JSONDecodeError` on Kafka message deserialization. Or garbled data (first bytes are binary, not `{`).

**Root cause**: Producer uses `OutboxEventValueSerializer` (Confluent Avro: magic byte `0x00` + 4-byte schema ID + Avro binary). Consumer does `json.loads(raw)` expecting plain JSON.

**Fix**: Use `deserialize_confluent_avro(schema_path, raw)` with a fallback to JSON:

```python
def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
    if schema_path:
        try:
            return cast("dict[str, Any]", deserialize_confluent_avro(schema_path, raw))
        except Exception:
            pass
    return cast("dict[str, Any]", json.loads(raw))
```

**Affected areas**: S1 portfolio `InstrumentEventConsumer`; any consumer receiving from topics produced by `OutboxEventValueSerializer`.

---

## BP-086 — Hardcoded Kafka consumer group IDs in standalone entry points

**Context**: Process topology refactoring — standalone `*_consumer_main.py` entry points

**Symptom**: Consumer group cannot be overridden via environment variable. Blue/green deployments collide on the same group ID. Non-default `kafka_consumer_group` in `.env` is silently ignored for some consumers but respected for others in the same service.

**Root cause**: Consumer group IDs hardcoded as string literals (`group_id="kg-fundamentals-group"`) instead of derived from `settings.kafka_consumer_group` with a suffix.

**Fix**: Replace hardcoded strings with `f"{settings.kafka_consumer_group}-{suffix}"` (e.g., `f"{settings.kafka_consumer_group}-fundamentals"`).

**Prevention**: When writing a new `*_consumer_main.py`, always derive `group_id` from `settings.kafka_consumer_group`. Search the same service's other consumer mains for the correct pattern before writing a new one.

---

---

## BP-105 — DLQ `original_event_id` Set to New UUID Instead of Kafka Event ID

**Category**: Data correctness / infrastructure
**Affected areas**: Any `dead_letter()` override in `BaseKafkaConsumer` subclasses

**Symptom**: DLQ entries have an `original_event_id` that bears no relation to the original Kafka message. Operators cannot correlate a DLQ entry with the Kafka topic, the `processed_events` table, or Avro envelope to diagnose root cause.

**Root cause**: `dead_letter()` override copies `dlq_id=common.ids.new_uuid7()` to both columns — `dlq_id` (correct, new PK) and `original_event_id` (wrong, should be `UUID(failure.event_id)`). The two fields have similar construction and are trivially confused.

**Fix**: `original_event_id=UUID(failure.event_id)` where `failure.event_id` is the string event_id extracted from the Kafka envelope. Add a `try/except ValueError` fallback to generate a new UUID if `failure.event_id` is not a valid UUID string (defensive, should not happen in practice).

**First seen**: QA-S4S5-INFRA-001 (2026-04-07), S5 `article_consumer.py:205`.

---

---

## BP-122 — Confluent Avro Wire Format Not Detected in S6 Consumer

**Symptom**: `article_consumer.py` raises `json.JSONDecodeError: Expecting value: line 1 column 1` or `AttributeError` when trying to read fields from the Kafka message. The message bytes start with `\x00` (magic byte) followed by 4 bytes schema ID — this is Confluent Schema Registry wire format, not JSON.

**Root cause**: The content-store dispatcher (S5) publishes `content.article.stored.v1` using Confluent Avro serialization (5-byte header: magic `0x00` + 4-byte schema ID + Avro binary payload). The original S6 consumer called `json.loads(raw)` directly, which fails on binary Avro payloads.

**Fix**: Override `deserialize_value()` in `ArticleProcessingConsumer` to detect the `\x00` magic byte and call `deserialize_confluent_avro(schema_path, raw)` from `messaging.kafka.serialization_utils`. Override `get_schema_path()` to return the `.avsc` file path for the topic.

**Affected areas**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py`. Any consumer reading from topics published by Schema Registry-aware producers.

**Prevention**: When connecting a consumer to a topic produced with Confluent Schema Registry: (1) check if the first byte is `\x00`, (2) strip the 5-byte header, (3) use `fastavro.schemaless_reader` with the loaded schema. Never assume Kafka messages on SR topics are plain JSON.

**First seen**: 2026-04-08 E2E NLP pipeline investigation.

---

---

## BP-124 — Kafka Consumer Idempotency Check Skips Embedding on Entity Replay

**Symptom**: Entity exists in `canonical_entities` table but `entity_embedding_state.embedding` is permanently NULL for that entity. Embedding refresh worker never generates an embedding for it.

**Root cause**: `InstrumentEntityConsumer.process_message()` checks `if entity exists → early return`. If the pod crashes after the DB commit (entity created) but before offset commit, the message is replayed. On replay, the early return at `entity_repo.get()` is triggered, and `_def_worker.refresh_for_entity()` is never called. The definition embedding row is left permanently absent.

**Fix**: Change the idempotency check to be embedding-aware. If the entity exists but the definition embedding row is absent (or `embedding IS NULL`), still call `refresh_for_entity`. Alternatively, fold `refresh_for_entity` into the same DB transaction scope as entity creation.

**Affected areas**: Any Kafka consumer in S7 that creates an entity and then calls a worker with a separate DB session (two-phase write). Specifically `instrument_consumer.py`.

**Prevention**: When splitting consumer work into "create entity" + "trigger enrichment" phases, ensure the idempotency guard covers both phases. A "entity present but embedding absent" state must still trigger enrichment.

**First seen**: PLAN-0017 QA pass 2026-04-08.

---

---

## BP-130 — `DirectKafkaProducerProtocol.produce_bytes` Has No Concrete Adapter — AttributeError in Production

**Symptom**: `AttributeError: 'cimpl.Producer' object has no attribute 'produce_bytes'` in S7 hot-path graph write (every enriched article that materialises relations/claims). The `EnrichedArticleConsumer` processes the article, reaches step 5 of `materialize_entities()`, and crashes. Articles end up in the DLQ. `entity.dirtied.v1` is never produced.

**Root cause**: `DirectKafkaProducerProtocol` in `graph_write.py` defines a `produce_bytes(topic, key, value)` method as the interface. However `confluent_kafka.Producer` has no such method — only `produce(topic, value, key, ...)`. The `enriched_consumer_main.py` passes a raw `confluent_kafka.Producer` with `# type: ignore[arg-type]`, masking the duck-type mismatch. At runtime, `direct_producer.produce_bytes(...)` raises `AttributeError`.

**Fix**: Create a `ConfluentDirectProducer` adapter class that wraps `confluent_kafka.Producer` and implements `produce_bytes`:
```python
class ConfluentDirectProducer:
    def __init__(self, producer: Producer) -> None:
        self._producer = producer

    def produce_bytes(self, *, topic: str, key: bytes, value: bytes) -> None:
        """Enqueue to librdkafka buffer — non-blocking, no flush."""
        self._producer.produce(topic, value=value, key=key)
```
Do NOT call `flush()` — `produce()` alone enqueues to the internal librdkafka buffer and is sub-millisecond. `flush()` is synchronous-blocking and would block the asyncio event loop. Delivery is handled by librdkafka's background thread.

In `enriched_consumer_main.py`:
```python
raw_producer = Producer({"bootstrap.servers": settings.kafka_bootstrap_servers})
direct_producer = ConfluentDirectProducer(raw_producer)  # remove # type: ignore
```

**Prevention**:
- Never use `# type: ignore[arg-type]` to pass a dependency that doesn't satisfy the Protocol — this suppresses the type mismatch that would have caught the bug.
- When defining a Protocol for an external library type, immediately create the adapter in the same commit.
- Add a protocol conformance test: `isinstance(direct_producer, DirectKafkaProducerProtocol)` or mypy structural check.

**Affected areas**: `enriched_consumer_main.py`, `graph_write.py` step 5, any EODHD worker wired with a direct producer, `provisional_enrichment.py`.

**First seen**: PRD-0018 investigation, 2026-04-09.

---

## BP-138 — Kafka Consumer Crashes on Non-Numeric Float Field

**Symptom**: Consumer dead-letters an event with `TypeError: float() argument must be a string or a number, not 'NoneType'` or `ValueError: could not convert string to float`. The event never reaches the use case; the crash is silent (just logged) and the partition continues processing with offset committed.

**Root cause**: `float(value.get("field", 0.0))` raises `TypeError` when the field is `None` (JSON null) and `ValueError` when it is a non-numeric string. Both arise from Avro union types that include `null` or from schema mismatches between producers.

**Fix**: Guard with try/except:
```python
raw = value.get("market_impact_score", 0.0)
try:
    score = max(0.0, min(1.0, float(raw or 0.0)))
except (ValueError, TypeError):
    score = 0.0
```

**Prevention**: Any consumer extracting a float from a Kafka event dict must use the guarded pattern above. Add a unit test for `None` and non-numeric string values.

**First seen**: PLAN-0021 QA pass, 2026-04-10 (F-003/F-055/F-157 merged finding).

---

---

## BP-147 — Outbox Dispatcher Missing Serializer Registration → KeyError Dead-Letter

**Category**: Kafka / Outbox
**Severity**: HIGH (silent event loss)

**Pattern**: A Kafka outbox dispatcher maps event type strings to Avro serializers via `_SERIALIZERS: dict[str, Callable]`. When a new Kafka event type is introduced (e.g., by a new PRD), the serializer dict is not updated. The dispatcher raises `KeyError` and the message is moved to the dead-letter queue.

**Symptom**: New events never appear at the consumer. DLQ count increases. No startup error — failure occurs only when the first message of the new type is dispatched.

**Fix**: Add the missing serializer registration:
```python
_SERIALIZERS = {
    "content.article.raw.v1": article_ser,
    "market.prediction.snapshot": prediction_ser,  # ← was missing
}
```

**Prevention**: When adding a new Kafka event type, checklist: (1) Avro schema, (2) topic constant, (3) outbox serializer registration, (4) DLQ test. Write a startup validation test that asserts every known event type has a registered serializer.

**First seen**: `services/content-ingestion/src/content_ingestion/infrastructure/messaging/outbox_dispatcher.py`, PLAN-0025 QA Phase 2, fixed 2026-04-12.

---

## BP-148 — Avro Schema Field With Empty String Default — Schema Registry Rejection

**Category**: Kafka / Avro Schema
**Severity**: HIGH (producer initialization failure)

**Pattern**: An Avro schema field is given `"default": ""` (empty string) on a non-string type (timestamp, enum, long). Schema Registry validates that the default value matches the declared type. An empty string is rejected for non-string fields.

**Symptom**: On service startup or schema registration, Schema Registry returns `422 Unprocessable Entity: default value is not compatible with schema`. All producers fail to initialize.

**Root cause**: Copy-paste of `"default": ""` from a string field onto a differently-typed field. The Avro Python library may not validate defaults locally, but Schema Registry enforces strict type correctness.

**Fix**: Remove the default (making the field required) or use a type-valid default:
```json
{ "name": "occurred_at", "type": "string" }
```

**Prevention**: Run schema compatibility check (`scripts/gen-contracts.sh --validate`) after every Avro schema change. Register all schemas against Schema Registry in CI before producer tests run.

**First seen**: `infra/kafka/schemas/market.prediction.v1.avsc`, PLAN-0025 QA Phase 2, fixed 2026-04-12.

---

---

## BP-149 — Non-Deterministic Entity PKs Break Kafka Re-Delivery Idempotency

**Pattern**: Consumer generates entity primary keys with `new_uuid7()` during processing. ON CONFLICT DO NOTHING guards are keyed on these PKs. On Kafka re-delivery, the same message produces *new* PKs — the conflict is never detected, and duplicate rows accumulate silently.

**Root cause**: `new_uuid7()` is not a function of the input — it yields a different UUID on each call. ON CONFLICT on a PK only protects against exact-same-PK retries, not logical-duplicate retries.

**Affected code**: `section_document()` in S6, `run_ner_block()` in S6 — every new Section, Chunk, and EntityMention gets a fresh `new_uuid7()` on each pipeline run for the same article.

**Symptom**: After a crash-and-restart that hits the re-delivery window (DB commit succeeded, Kafka offset not yet committed), duplicate section/chunk/mention rows appear in nlp_db with the same `doc_id` but different PKs.

**Fix**: Add an explicit idempotency pre-check before the main write transaction. Use an existing "pipeline completed" sentinel — the `routing_decisions.doc_id` row — to detect already-processed articles and skip the pipeline entirely.

```python
# At the start of _run_pipeline:
async with self._nlp_sf() as check_session:
    check_routing_repo = RoutingDecisionRepository(check_session)
    if await check_routing_repo.get_by_doc(doc_id) is not None:
        logger.info("article_consumer.skip_already_processed", doc_id=str(doc_id))
        return
```

**Prevention**:
- Prefer deterministic IDs derived from input (e.g., `uuid5(namespace, f"{doc_id}:{index}")`) when idempotency via ON CONFLICT is required.
- If IDs must be random (UUIDv7 monotonic), add a separate idempotency gate before the write session (see fix above).
- In tests: mock `session.execute` result so `scalar_one_or_none()` returns `None` — otherwise the idempotency guard fires on the first call and skips the pipeline being tested.

**First seen**: S6 `ArticleProcessingConsumer._run_pipeline`, investigation 2026-04-13, fixed 2026-04-13.

---

---

## BP-150 — Kafka Default Retention (7 Days) Causes Silent Backlog Loss on Extended Downtime

**Pattern**: Pipeline consumer services are taken down for maintenance or a failure lasting >7 days. The Kafka default `log.retention.hours=168` (7 days) expires messages that accumulated during the downtime. On restart with `auto.offset.reset=earliest`, the consumer starts from the oldest *remaining* message — silently skipping everything from the downtime window.

**Root cause**: Kafka topics created without explicit `retention.ms` configuration inherit the broker default (7 days). For high-value pipeline topics that carry non-reproducible articles and market data, this is insufficient for real maintenance windows.

**Affected topics**: `content.article.stored.v1`, `market.dataset.fetched`, `nlp.article.enriched.v1` (and by extension all downstream topics in those pipelines).

**Symptom**: After >7 days of downtime, the NLP pipeline / knowledge graph silently processes fewer articles than were published during the outage. No error is raised; the consumer simply has no messages to process.

**Fix**: Set `retention.ms=2592000000` (30 days) on all primary pipeline topics in `infra/kafka/init/create-topics.sh`.

**Prevention**:
- Every new primary pipeline topic should have an explicit retention config in `create-topics.sh`.
- Alert when consumer lag on `content.article.stored.v1` exceeds 3 days (half the old retention).
- Dead-letter topics can use a shorter retention (14 days) — dead-lettered messages are for investigation, not replay.

**First seen**: `infra/kafka/init/create-topics.sh`, investigation 2026-04-13, fixed 2026-04-13.

---

---

## BP-168 — Cross-Database Dual-Commit: intel_db Persists Before nlp_db Commits

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-20 |
| **Severity** | CRITICAL |
| **Affected areas** | `services/nlp-pipeline/src/nlp_pipeline/infrastructure/consumers/article_consumer.py`, `services/nlp-pipeline/src/nlp_pipeline/application/blocks/entity_resolution.py` |
| **Root cause** | The S6 `ArticleEnrichedConsumer` processes two separate databases (`nlp_db` and `intelligence_db`). The `entity_resolution` block opens and commits the `intelligence_db` session internally (inside its own scope), BEFORE the outer consumer commits `nlp_db`. If the `nlp_db` commit subsequently fails (connection error, constraint violation), the `intelligence_db` writes are already durably persisted with no rollback mechanism. This creates ghost entity-resolution records that reference article NLP rows that were never committed. |
| **Symptom** | Entity mention rows in `intelligence_db.entity_mentions` pointing to articles that do not exist in `nlp_db.document_chunks`. Knowledge graph builds on phantom data. Deduplication misses on re-delivery since `nlp_db` shows the article as unprocessed but `intelligence_db` already has its entity mentions. |
| **Fix (PLAN-0031 Wave B-3)** | Restructure `article_consumer.py` to open both sessions at the outermost level. Pass both sessions into all blocks. Commit `nlp_db` FIRST (since it is the source-of-truth for article existence), then commit `intelligence_db`. Remove the internal `session.commit()` from `entity_resolution.py` — it must be driven by the consumer, not the block. |

### Prevention

When a consumer writes to two separate databases in a single logical transaction, ALWAYS commit the source-of-truth database FIRST and the derived/downstream database SECOND. Never allow a sub-block to commit its own session; all commits must be controlled at the consumer level. If atomicity is required, use the outbox pattern (write to one DB + outbox, consume outbox to drive the other DB).

---

---

## BP-169 — Kafka Produce Before DB Commit (Pre-Commit Event Leakage)

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-20 |
| **Severity** | HIGH |
| **Affected areas** | `services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py:375`, `services/knowledge-graph/src/knowledge_graph/infrastructure/consumers/enriched_consumer.py:232` |
| **Root cause** | `materialize_graph()` calls `direct_producer.produce_bytes()` for `entity.dirtied.v1` events at line 375, which is INSIDE the function and occurs BEFORE the consumer's `session.commit()` at `enriched_consumer.py:232`. If the DB commit fails after the produce, downstream consumers (S7 confidence recomputation workers) receive events for graph state that was never committed. The compacted `entity.dirtied.v1` topic then contains the latest entry for those entity IDs, suppressing future valid dirtying events via log compaction. |
| **Symptom** | S7 confidence recomputation workers trigger on ghost entities. Entities that were "dirtied" by a failed graph write never get reprocessed because the compacted topic already holds an entry for their ID with a later offset. |
| **Fix (PLAN-0031 Wave C-1)** | **FIXED 2026-04-21.** Refactored `materialize_graph()` to return `frozenset[uuid.UUID]` of entity IDs that need dirtying. Moved the `entity.dirtied.v1` produce loop to AFTER `session.commit()` in `enriched_consumer.py`. If the commit fails, no events are produced. If the produce fails after commit, the next re-delivery will produce a duplicate dirty event (idempotent — the worker re-runs confidence computation). 5 regression tests added. |

### Prevention

NEVER produce Kafka events inside a block/function that is called before the DB transaction commits. Either: (a) use the outbox pattern (write event to DB outbox within the same transaction, dispatch after commit), or (b) return the event payloads to the caller and produce them AFTER a successful `session.commit()`. This applies to all direct producers, not just compacted topics.

---

---

## BP-259 — Shared `ingestion_events` Dedup Table: Same Event ID Used by Multiple Consumers

**Summary**: Multiple Kafka consumers subscribing to the same topic share event IDs. A `UNIQUE` constraint on `event_id` alone causes the second consumer to see every event as a duplicate.

**Symptoms**: Consumer processes all messages (LAG=0), commits offsets, but emits no INFO logs and creates no derived records. `create_if_not_exists` silently returns `False` for all matching events.

**Affected areas**: Any two consumers in the same service subscribing to the same Kafka topic (e.g., `ohlcv_consumer` + `intraday_resampling_consumer` both consuming `market.dataset.fetched`).

**Pattern**:
`ingestion_events` has `UNIQUE (event_id)`. Consumer A processes event `xyz` and inserts `(event_id="xyz", event_type="ohlcv")`. Consumer B (same service, same table) also tries to insert `(event_id="xyz", event_type="intraday_resampling")` → `ON CONFLICT DO NOTHING` → returns `False` → message silently dropped.

**Root cause**:
The unique constraint uses only `event_id`, treating the same external event as processed regardless of which consumer is processing it.

**Fix**:
Namespace the dedup key per consumer: `dedup_key = f"{event_id}:{consumer_name}"`. This makes the insert unique per (event, consumer) pair without requiring a schema migration.

**Alternative fix**:
Change the unique constraint to `(event_id, event_type)` and use `event_type` = consumer name. Requires a DB migration.

**Prevention**:
- Document that `ingestion_events` dedup is keyed on `event_id` alone.
- When adding a new consumer to a topic already consumed by an existing consumer in the same service, always namespace the dedup key.

---

## BP-275 — Kafka `MemberIdRequiredException` On First JoinGroup (Cosmetic)

**Category**: Kafka / startup race
**Severity**: NIT (one-shot, auto-recovers; no operator action required)
**Affected areas**: Any consumer that joins a fresh group with a brand-new broker (compose `up` from a clean volume)
**First seen**: 2026-04-29 (PLAN-deep-QA F-DP1-19)

**Symptoms**:
- Single log line at boot from `worldview-kafka-1`: `client reason: rebalance failed due to MemberIdRequiredException`
- The same consumer group successfully rebalances on the next iteration; never observed steady-state.

**Root Cause**:
The first time a consumer issues a `JoinGroup` request to the coordinator, it has no `member.id` (empty string is sent). KIP-394 mandates that the broker reject this with `MEMBER_ID_REQUIRED`, returning an assigned `member.id` in the response. The client is then expected to retry the JoinGroup with that member.id. This is a **protocol-level handshake**, not a fault — the rdkafka client does the retry automatically and the rebalance completes within a second.

**Fix**:
None required. The exception is emitted once per consumer-group bootstrap from a clean slate. Subsequent restarts re-use the cached member.id so the message does not recur.

**Prevention**:
- If the noise is undesirable in CI logs, set `group.instance.id` on the consumer for static membership — the broker then trusts the client's identity across restarts and skips the initial empty-ID JoinGroup.
- Do NOT alarm on this log line in `alertmanager` rules; reserve rebalance alerts for *repeated* `RebalanceInProgressException` or sustained `consumer_lag` growth.

---

## BP-276 — Wire field naming MUST be pinned by an end-to-end contract test

**Category**: API contract / frontend-backend integration
**Severity**: CRITICAL when a feature ships with the mismatch (request 422s every time)
**Affected areas**: Any frontend gateway method that POSTs/PATCHes a JSON body or builds query params from typed enums; any S9-proxied endpoint where the canonical Pydantic schema lives in a different repo from the frontend
**First seen**: 2026-04-29 (PLAN-0051 QA iter1 — C-1 snooze body, C-2 severity case, C-3 pagination total semantics)

**Symptoms**:
- Frontend integration test passes (component-level mock matches the frontend's own assumptions about the wire shape).
- Backend unit test passes (Pydantic schema is correct on its own).
- Live request 422s with `Field required: <X>` or `Invalid value: must be <enum members>`.
- "Load more" never appears in pagination because `rows.length < total` is always False.
- The bug is invisible to type-checking because `apiFetch<T>(...)` types the **response**, not the request body.

**Root Cause**:
A wire-shape mismatch between the frontend gateway and the backend Pydantic schema. Common patterns:
1. **Field rename**: backend declares `until: datetime`, frontend sends `{snooze_until: ...}` (C-1).
2. **Case mismatch**: backend `StrEnum` lowercase, frontend TS literal type uppercase, query string built from the literal (C-2).
3. **Pagination semantics**: backend ``total`` is a per-page row count; frontend computes `hasMore = rows.length < total` and the affordance never appears (C-3).

**Fix**:
For each (gateway method ↔ Pydantic schema) pair, add **one Vitest** that asserts the request body / query string built by the gateway, and **one pytest** that pins the schema's required fields and enum values. The Vitest captures the bug at the wire boundary; the pytest prevents the schema drifting underneath.

```ts
// gateway.test.ts — pins the wire body shape
const spy = mockFetch(200, {});
await gw.snoozeAlert("a-1", new Date(...));
const body = JSON.parse((spy.mock.calls[0][1] as RequestInit).body as string);
expect(body.until).toBeDefined();           // canonical
expect(body.snooze_until).toBeUndefined();  // negative — bug regression
```

**Prevention**:
- For every new gateway method that takes a body or builds query params, write the contract test BEFORE the integration test. The latter is too coarse — it tests "the UI eventually shows X" not "the wire shape is exactly Y".
- When a backend schema renames or case-folds a field, grep the frontend repo for the OLD name and update both sides plus the contract test in one PR. Do NOT add a Pydantic alias as a "compat" shim — that just postpones the cleanup and lets the next refactor regress silently.
- Pagination shape (`total` semantics, `has_more` flag, cursor vs offset) MUST be documented in the schema docstring and asserted in both Vitest and pytest. The frontend "Load more" affordance is the canary — if it never appears in QA, the bug is in the pair.

---

## BP-313 — JSON-Only Kafka Consumer Hides Schema-Evolution Bugs (PLAN-0062)

**Pattern**: A Kafka consumer's `deserialize_value` calls `json.loads(raw)` on
the wire bytes with no Avro path. The producer side writes the outbox row's
`payload_avro` column as `json.dumps(payload).encode()`. There is an `.avsc`
schema in `infra/kafka/schemas/` for the topic, but no code path actually
consults it — the schema is decoration, not enforcement.

**Root Cause**: In a JSON-on-the-wire pipeline, every dict key the consumer
reads is implicitly part of the contract, but no tool checks alignment
between the producer dict and the schema. Consumers silently accept extra,
missing, or renamed fields. Schema-evolution bugs surface only when a
consumer crashes in production, often weeks after the producer changed.

**Discovered**: PLAN-0062 architecture sweep (2026-05-03). Found three
JSON-only consumers — alert `intelligence_consumer`, kg `enriched_consumer`,
kg `entity_consumer` — for topics that already had `.avsc` schemas. In each
case the producer's outbox row was missing fields that the schema declared
required (e.g. `entity.canonical.created.v1.occurred_at` was absent from
the `provisional_enrichment_core` payload). The mismatch was invisible to
runtime tests because nothing decoded against the schema.

**Fix**: Switch the producer to
`messaging.kafka.serialization_utils.serialize_confluent_avro(schema_path, record)`
and the consumer to
`messaging.kafka.serialization_utils.deserialize_confluent_avro(schema_path, raw)`.
Keep a JSON fallback temporarily and **log every fallback hit** so the
residual JSON traffic is measurable; remove the branch once it decays to
zero.

**Regression test**: `tests/architecture/test_kafka_avro_enforcement.py` —
unconditional after PLAN-0062 Wave D — fails the build for any consumer
whose `deserialize_value` body uses `json.loads` with no Avro call.

### Prevention

- **Rule**: All Kafka contracts use Avro on the wire (R28). Pure JSON
  consumers are forbidden — there is no baseline / escape hatch.
- **Architecture test**: The classifier test scans every
  `services/*/src/**/consumers/*.py` and rejects any `deserialize_value`
  that lacks `deserialize_confluent_avro` / `deserialize_avro`.
- **Producer-side audit**: When adding a new outbox writer, the call site
  must use `serialize_confluent_avro(schema_path, ...)` — outbox dispatchers
  produce the bytes verbatim and do NOT prefix the Confluent header, so the
  responsibility lives at the row-construction site.
- **Canonical model**: Every topic has a frozen-dataclass canonical model
  in `libs/contracts` mirroring the schema field-for-field, with field-set
  alignment asserted by a contract test at
  `libs/contracts/tests/test_events_*_*.py`.

---

---

### BP-345: NLP Evidence Text Silently Dropped from Relation Dicts

**Category**: Kafka & Messaging
**Severity**: HIGH
**First seen**: 2026-05-03
**Services**: nlp-pipeline, knowledge-graph

**Symptoms**:
- All `relation_evidence_raw` rows have `evidence_text=NULL`
- `SummaryWorker` `summary_worker_complete summaries_created=0` (fallback produces no summaries)
- `enriched_consumer_null_evidence_text` warnings fire for every processed article

**Root cause**:
The LLM extraction prompt (in `libs/prompts/src/prompts/extraction/deep.py`) explicitly instructs the LLM to include `"evidence_text": "..."` for each relation, and the LLM complies. But `_build_raw_relations()` in `article_consumer.py` built the output dict with only 5 fields, silently dropping `evidence_text` from the LLM response. The field never reached the `encode_raw_array()` call or the Kafka payload.

**Example**:
```python
# Bad — evidence_text silently dropped
result.append({
    "subject_entity_id": subject_id,
    "object_entity_id": object_id,
    "raw_type": str(rel_d.get("predicate", "")),
    "extraction_confidence": float(rel_d.get("confidence", 0.5)),
    "entity_provisional": ...,
    "provisional_queue_id": ...,
})

# Good — evidence_text forwarded
result.append({
    "subject_entity_id": subject_id,
    "object_entity_id": object_id,
    "raw_type": str(rel_d.get("predicate", "")),
    "extraction_confidence": float(rel_d.get("confidence", 0.5)),
    "evidence_text": str(rel_d.get("evidence_text", "")) or None,
    "entity_provisional": ...,
    "provisional_queue_id": ...,
})
```

**Fix**:
- Add `"evidence_text": str(rel_d.get("evidence_text", "")) or None` to the dict built in `_build_raw_relations()`
- Add `"evidence_text": {"type": "string"}` to the relations items properties in `_EXTRACTION_SCHEMA` for documentation consistency

**Prevention**:
- Whenever the LLM extraction schema defines a field for a type (events/claims/relations), explicitly verify the field is forwarded through the entire chain: LLM → output_schema → `_build_raw_*()` → Kafka payload → consumer → DB insert
- Add a unit test asserting that `evidence_text` is forwarded through `_build_raw_relations()`

**Regression test**: `services/nlp-pipeline/tests/unit/application/blocks/test_deep_extraction.py`

---

### BP-348: Provider Format Mismatch Silently Drops All Earnings Calendar Data

**Category**: Kafka & Messaging
**Severity**: HIGH
**First seen**: 2026-05-03
**Services**: knowledge-graph (earnings_calendar_dataset_consumer)

**Symptoms**:
- `temporal_events` table has rows from Finnhub fetches but zero rows from EODHD fetches
- `entity_event_exposures = 0` even after `earnings_calendar_dataset_consumer` starts
- Consumer logs show `earnings_calendar_consumer_empty_payload` for every EODHD-sourced message
- `ingestion_tasks.fetched_by_provider = 'eodhd'` tasks produce 0 temporal_events

**Root cause**:
The consumer was written for Finnhub's response shape only. When `_preferred_provider()` falls
back to EODHD (Finnhub unavailable), S2 stores the raw EODHD payload verbatim. The consumer
then looks for `"earningsCalendar"` (Finnhub key) which doesn't exist in EODHD's `"earnings"` key
→ empty list → silent drop of every event. Three additional field mismatches also caused silent
data corruption when the ticker/EPS fields were being read:

| Field | Finnhub | EODHD |
|-------|---------|-------|
| Payload root key | `"earningsCalendar"` | `"earnings"` |
| Ticker | `"symbol"` (`"AAPL"`) | `"code"` (`"AAPL.US"` — exchange suffix) |
| EPS estimate | `"epsEstimate"` | `"estimate"` |
| EPS actual | `"epsActual"` | `"actual"` |
| Report date | `"reportDate"` | `"report_date"` |
| Timing | `"hour"` (`"bmo"` / `"amc"`) | `"before_after_market"` (`"BeforeMarket"` / `"AfterMarket"`) |

**Example**:
```python
# Bad — only handles Finnhub
events = raw_payload.get("earningsCalendar", [])          # returns [] for EODHD
ticker = ev.get("symbol") or ev.get("ticker") or ""       # misses EODHD "code"
eps_estimate = ev.get("epsEstimate")                       # None for EODHD

# Good — handles both providers
events = raw_payload.get("earningsCalendar") or raw_payload.get("earnings") or []
ticker_raw = ev.get("symbol") or ev.get("ticker") or ev.get("code") or ""
# Strip EODHD exchange suffix: "AAPL.US" → "AAPL"
if "." in ticker_raw:
    ticker_raw = ticker_raw.split(".")[0]
eps_estimate = ev.get("epsEstimate") if "epsEstimate" in ev else ev.get("estimate")
```

**Fix**:
1. Multi-key payload extraction: `raw_payload.get("earningsCalendar") or raw_payload.get("earnings") or []`
2. `_upserted_ticker()`: add `ev.get("code")` fallback; strip `.XX` exchange suffix
3. `_upsert_event()`: normalize `epsEstimate`/`estimate`, `epsActual`/`actual`, `reportDate`/`report_date`
4. Map `"before_after_market"` string → `"bmo"`/`"amc"` hour code

**Prevention**:
- When writing a consumer that handles data from a multi-provider S2 pipeline, always check
  what format EACH provider returns — never assume the canonical envelope normalizes field names
- The `serialize_passthrough()` adapter in S2 stores the raw provider response verbatim inside
  `payload`; field names are provider-specific and must be handled in the consumer
- Add provider-specific test fixtures for every consumer that reads `market.dataset.fetched`
  (both Finnhub and EODHD shapes)

**Regression test**: `services/knowledge-graph/tests/unit/infrastructure/consumer/test_earnings_calendar_dataset_consumer.py::TestEohdEarningsFormat`

---

### BP-349: Raw vs Processed Event Dict Field Name Mismatch Silently Drops All Events

**Category**: Kafka & Messaging
**Severity**: CRITICAL
**First seen**: 2026-05-04
**Services**: nlp-pipeline (article_consumer Block 13E)

**Symptoms**:
- `intelligence.temporal_event.v1` outbox always empty despite MACRO/REGULATORY events extracted
- `temporal_events` table has 0 NLP-derived rows after Block 13E deployment
- All extracted MACRO/GEOPOLITICAL events silently filtered — no log output from `_emit_temporal_events`
- `extraction_confidence` key missing from event dicts → defaults to 0.0 → fails confidence threshold

**Root cause**:
`_emit_temporal_events()` was written to receive **processed** event dicts (output of `_build_raw_events()`
with normalized field names). But its call site passed **raw** LLM output dicts instead.

Field name mismatch:
| Use case | LLM raw field | Processed field (`_build_raw_events` output) |
|----------|--------------|----------------------------------------------|
| Confidence | `"confidence"` | `"extraction_confidence"` |
| Event text | `"description"` | `"event_text"` |
| Entities | `"entity_refs"` (strings) | `"participant_entity_ids"` (resolved UUIDs) |

Since `evt_d.get("extraction_confidence", 0.0)` returns `0.0` for raw dicts, every event fails
`if confidence < 0.5: continue` — all events silently discarded.

**Example**:
```python
# Bad — passes raw LLM output dicts
await _emit_temporal_events(
    raw_events=extraction_result.get("events", []),  # has "confidence", not "extraction_confidence"
    ...
)

# Good — normalize through _build_raw_events() first
_te_provisional_refs = {v for v, eid in _te_entity_id_by_ref.items() if eid in _te_provisional_ids}
_te_processed = _build_raw_events(extraction_result.get("events", []), _te_entity_id_by_ref, _te_provisional_refs)
if _te_processed:
    await _emit_temporal_events(raw_events=_te_processed, ...)
```

**Fix**:
At the Block 13E call site in `_run_pipeline()`, call `_build_raw_events()` on the raw events
before passing to `_emit_temporal_events`. This normalizes field names and resolves entity refs.

**Prevention**:
- When a helper function is designed for pre-processed data, enforce this with a type alias or
  `TypedDict` parameter type so callers can't accidentally pass raw dicts
- Add structured logging inside filter steps: `logger.debug("temporal_event_skipped", reason="low_confidence", confidence=confidence)` — makes silent filters visible in logs
- Write a unit test that verifies the end-to-end path: raw_LLM_output → _build_raw_events → _emit_temporal_events → outbox_repo.add() called

**Regression test**: `services/nlp-pipeline/tests/unit/infrastructure/messaging/consumers/test_article_consumer_temporal_events.py::TestNormalizeTemporalEventsForEmit::test_end_to_end_pipeline_with_raw_llm_output` + `test_raw_llm_output_without_normalization_fails_confidence_threshold`

**Status**: FIXED 2026-05-04 — added `_normalize_temporal_events_for_emit()` called at Block 13E call site; also fixes QG-3 (macro events with no entity refs are now emitted with empty exposed_entities).

---
