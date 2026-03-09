# Bug Patterns & Post-Mortems

> **Purpose**: A living knowledge base of bugs encountered during development.
> AI agents MUST read this file before implementing any component that matches
> the "Affected areas" column in the index. Prompt authors SHOULD reference
> pattern IDs (e.g., `BP-001`) when writing implementation instructions to
> prevent recurrence.

---

## How to use this file

1. **Before implementing**: scan the index below for categories matching your
   task (e.g., "Kafka", "outbox", "serializer"). Read the full entry for any match.
2. **When you hit a runtime error**: search this file for the error message string
   before debugging from scratch.
3. **After fixing a new bug**: add an entry here and update any affected prompts,
   linking back to the pattern ID.

---

## Quick-reference index

| ID | Category | Symptom (error message or behaviour) | Affected areas |
|----|----------|---------------------------------------|----------------|
| [BP-001](#bp-001) | Kafka / outbox serialization | `"a bytes-like object is required, not 'OutboxKafkaValue'"` | Any service implementing `BaseOutboxDispatcher` |

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

## Template for new entries

Copy this block when adding a new pattern:

```markdown
## BP-NNN — Short title

**Date discovered**: YYYY-MM-DD
**Service affected**: `<service-name>` (found during `<make target or test>`)
**Prompts updated**: `<prompt file>` task `<T-XX-NN>` step N

### Symptom

<exact error message or observable behaviour>

### Root cause

<explanation of why it fails>

### Correct implementation pattern

<code snippet showing the correct way>

### Test to add (prevents regression)

<pytest test that would have caught this>

### Files changed in fix

| File | Change |
|------|--------|
| `path/to/file.py` | What was changed |
```
