# Implementation Guide — messaging

## Status: Complete

**Verified**: 2026-03-08 (Wave 03 — T-030..T-038)

## Modules Implemented

- [x] `messaging.kafka.consumer.errors` — `ConsumerError`, `RetryableError`, `FatalError` + 8 subclasses
- [x] `messaging.kafka.consumer.base` — `BaseKafkaConsumer[TFailure]` with idempotency, back-off, graceful shutdown, observability integration
- [x] `messaging.kafka.producer` — `KafkaProducerConfig`, `OutboxKafkaValue`, `KafkaEventValueSerializer`, `OutboxEventValueSerializer`, `build_serializing_producer`
- [x] `messaging.kafka.schema_registry` — `SchemaRegistryConfig`, `build_schema_registry_client`
- [x] `messaging.kafka.serializer` — `AvroDictable` protocol (with `event_type`), `AvroSerializerConfig`, `build_avro_serializer`, `topic_event_type_subject_name_strategy`
- [x] `messaging.kafka.serialization_utils` — `load_schema`, `serialize_avro`, `deserialize_avro`, `iso_datetime`, `decimal_to_str`, `serializer_for_schema`
- [x] `messaging.kafka.dispatcher.base` — `BaseOutboxDispatcher`, protocols, `DispatcherConfig`, `DeliveryResult`, `run_dispatcher`
- [x] `messaging.schemas` — re-exports fastavro helpers (`AvroDictable` protocol lives in `serializer.py`)
- [x] `messaging.valkey.client` — `ValkeyClient`, `ValkeyConfig`, `create_valkey_client`, `create_valkey_client_from_url`
- [x] `messaging.topics` — topic name constants (9 services)
- [x] `messaging.__init__` — full public API re-exports

## Tests

160 tests across 9 test files (all passing):

**Unit tests (104)**:
- `tests/test_errors.py` — 22 tests (error hierarchy, branching, root imports)
- `tests/test_producer.py` — 10 tests (config, OutboxKafkaValue, serializer routing)
- `tests/test_schemas.py` — 18 tests (load_schema, roundtrip, iso_datetime, decimal_to_str)
- `tests/test_serializer.py` — 11 tests (AvroDictable protocol, AvroSerializerConfig, subject naming)
- `tests/test_valkey.py` — 14 tests (ValkeyConfig, URL parsing, client construction, method presence)
- `tests/test_topics.py` — 29 tests (all topic constants, uniqueness, naming convention)

**Integration tests (56)** — no live infra required:
- `tests/test_valkey_integration.py` — 28 tests (full ValkeyClient via fakeredis: string/JSON/batch/hash/list/ping)
- `tests/test_consumer_integration.py` — 13 tests (BaseKafkaConsumer pipeline: happy path, dedup, retry, dead-letter)
- `tests/test_dispatcher_integration.py` — 15 tests (BaseOutboxDispatcher: success, failure, dead-letter, lifecycle)

## Type Stubs

Minimal stubs for `confluent-kafka` at `stubs/confluent_kafka/`:
- `__init__.pyi` — `KafkaError`, `KafkaException`, `Message`, `Consumer`, `Producer`, `SerializingProducer`, `DeserializingConsumer`
- `schema_registry/__init__.pyi` — `Schema`, `RegisteredSchema`, `SchemaRegistryClient`
- `schema_registry/avro.pyi` — `AvroSerializer`, `AvroDeserializer`
- `serialization.pyi` — `SerializationContext`, `MessageField`, `Serializer`, `Deserializer`, `StringSerializer`, `StringDeserializer`

`mypy.ini` wired with `mypy_path = stubs`; the `[mypy-confluent_kafka.*] ignore_missing_imports` override is removed.

## Architecture Decisions

- ADR-0004: `docs/architecture/decisions/0004-valkey-key-taxonomy.md`
- ADR-0005: `docs/architecture/decisions/0005-messaging-error-classification.md`

## Migration Source

- `platform_repo/libs/messaging/` — copied & refactored
- Observability (metrics/logging) extracted from inline code → `observability` lib
- `AvroDictable` reconciled: protocol now in `serializer.py` (with `event_type` property)
  to match legacy consumer expectations; `schemas.py` is a re-export facade.
