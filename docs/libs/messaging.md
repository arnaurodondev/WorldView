# Messaging Library

> **Package**: `messaging` · **Path**: `libs/messaging/`
> **Purpose**: Kafka producer/consumer abstractions, Avro serialization, transactional
> outbox dispatcher, Valkey client. The backbone of all inter-service communication.

---

## Public API

### Kafka Consumer

| Class | Purpose |
|-------|---------|
| `BaseKafkaConsumer[TFailure]` | Abstract generic base for all Kafka consumers. Provides Avro deserialization, idempotency checking, error classification (Retryable vs Fatal), exponential backoff, graceful shutdown. |
| `ConsumerConfig` | Typed consumer settings (bootstrap servers, group ID, auto offset reset, timeouts, retry tuning). |
| `RetryableError` | Base for transient errors (network, storage, rate limit). |
| `FatalError` | Base for permanent errors (schema validation, malformed data). |

### Kafka Producer

| Class/Function | Purpose |
|----------------|---------|
| `KafkaProducerConfig` | Producer config with `acks=all`, `enable_idempotence=True`. |
| `build_serializing_producer()` | Factory for `confluent_kafka.SerializingProducer`. |
| `AvroDictable` | Protocol requiring `event_type` property for Avro routing. |
| `AvroSerializerConfig` | Production defaults (`auto_register_schemas=False`). |
| `build_avro_serializer()` | Single translation boundary to Confluent API. |
| `topic_event_type_subject_name_strategy()` | Subject = `{topic}-{event_type}`. |

### Outbox Dispatcher

| Class | Purpose |
|-------|---------|
| `BaseOutboxDispatcher` | Lease-based outbox publisher. Hybrid model: immediate attempt + background poll. Delivery acknowledgement (marks published only after Kafka ack). Dead-letter for exceeded attempts. |
| `DispatcherConfig` | Dispatcher settings (poll interval, lease duration, batch size). |
| `OutboxKafkaValue` | Structured value: `event_type` + `payload` dict. |
| `OutboxEventValueSerializer` | Routes `OutboxKafkaValue` to correct Avro serializer by event type. |

### Valkey Client

| Class | Purpose |
|-------|---------|
| `ValkeyClient` | Async Redis/Valkey client with connection pooling, JSON get/set, TTL operations, batch operations, hash operations. |

### Schema Utilities

| Function | Purpose |
|----------|---------|
| `load_schema(path)` | Load Avro schema from `.avsc` file. |
| `serializer_for_schema(schema, registry)` | Build serializer for a specific schema. |
| `decimal_to_str(d)` | Safe Decimal → string for Avro. |
| `iso_datetime(dt)` | Datetime → ISO-8601 string for Avro. |

---

## How to Use from Services

### Consumer Example

```python
from messaging.kafka.consumer.base import BaseKafkaConsumer, ConsumerConfig
from messaging.kafka.consumer.errors import RetryableError, FatalError

class OHLCVConsumer(BaseKafkaConsumer[str]):
    async def process_message(self, key, value, headers):
        # value is deserialized Avro dict
        canonical_key = value["canonical_key"]
        data = await self.storage.get(value["canonical_bucket"], canonical_key)
        await self.repository.upsert_bars(data)

    async def is_duplicate(self, event_id: str) -> bool:
        return await self.dedup_repo.exists(event_id)
```

### Outbox Usage

```python
from messaging.kafka.dispatcher.base import BaseOutboxDispatcher

class PortfolioDispatcher(BaseOutboxDispatcher):
    # Configure event_type → serializer mapping
    pass
```

### Valkey Usage

```python
from messaging.valkey.client import ValkeyClient

client = ValkeyClient(url="redis://localhost:6379")
await client.set_json("md:v1:quote:abc", {"price": 150.0}, ttl=30)
data = await client.get_json("md:v1:quote:abc")
```

---

## Common Pitfalls

1. **Forgetting idempotency**: Always implement `is_duplicate()` in consumers.
2. **Blocking in async consumer**: Use `run_in_executor` for sync Confluent Kafka calls.
3. **Schema mismatch**: Ensure `.avsc` files match the data being serialized. Run `scripts/gen-contracts.sh`.
4. **Outbox ordering**: Outbox guarantees at-least-once, not exactly-once. Consumers must be idempotent.

---

## Testing Strategy

- **Unit**: test error classification, retry logic, serialization helpers
- **Integration**: test consumer + producer with embedded Kafka (testcontainers)
- **Contract**: validate Avro schema compatibility with schema registry
