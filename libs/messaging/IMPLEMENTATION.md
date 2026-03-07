# Implementation Guide — messaging

## Status: Scaffold

## Modules to Implement

- [ ] `messaging.consumer` — `BaseKafkaConsumer` with idempotency, backpressure, graceful shutdown
- [ ] `messaging.producer` — `KafkaProducerConfig`, `produce_avro()`
- [ ] `messaging.outbox` — `BaseOutboxDispatcher` with lease-based locking, batch dispatch
- [ ] `messaging.schemas` — `AvroDictable` protocol, `load_schema()`, `serialize_avro()`, `deserialize_avro()`
- [ ] `messaging.valkey` — `ValkeyClient` async Redis wrapper
- [ ] `messaging.topics` — Topic name constants

## Migration Source

- `platform_repo/libs/messaging/` → copy & refactor (extract metrics to observability lib)
