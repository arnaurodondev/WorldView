# Kafka Pipeline Checklist

> Point-by-point checklist for Kafka-based event pipeline correctness. Worldview uses Kafka + Avro + outbox pattern across 10 services.

## 1. Consumer Configuration

- [ ] Consumer group ID follows naming convention (`<service>-<purpose>`)
- [ ] Auto-commit disabled (manual offset management after processing)
- [ ] Deserialization uses Avro with Schema Registry validation
- [ ] Error handler routes to DLQ on deserialization failure (not crash)
- [ ] Consumer handles rebalance gracefully (no in-flight processing lost)

## 2. Idempotency

- [ ] `event_id` checked before processing (dedup via DB lookup or idempotency table)
- [ ] Processing is safe for re-delivery (upsert, not insert-if-not-exists)
- [ ] No side effects on duplicate: no duplicate notifications, no double-counting
- [ ] Idempotency window covers realistic retry scenarios (minutes, not seconds)

## 3. Outbox Pattern (Producers)

- [ ] DB write + outbox row in same transaction
- [ ] Outbox table has: `event_id`, `topic`, `key`, `payload`, `created_at`, `dispatched_at`
- [ ] Outbox dispatcher polls on interval (not triggered by write)
- [ ] Dispatcher marks row dispatched AFTER successful Kafka publish
- [ ] Dispatcher handles Kafka unavailability (retry with backoff, not crash)
- [ ] Dispatcher handles serialization failure (DLQ the row, don't block queue)

## 4. Avro Schema Compatibility

- [ ] Schema registered in Schema Registry before producing
- [ ] New fields have defaults (forward-compatible)
- [ ] No fields removed or renamed (backward-compatible)
- [ ] Schema version bumped in event envelope
- [ ] Consumer can deserialize both old and new schema versions

## 5. Claim-Check Pattern

- [ ] Large payloads stored in MinIO, pointer in Kafka event
- [ ] MinIO key follows convention: `<service>/<domain>/<resource_id>/<artifact>/<version>.<ext>`
- [ ] Consumer dereferences pointer before processing
- [ ] MinIO unavailable → RetryableError (not FatalError)
- [ ] Orphaned objects acceptable (no cascade delete requirement)

## 6. DLQ Handling

- [ ] Dead letter queue table exists per consumer service
- [ ] Failed events routed to DLQ with error context (not silently dropped)
- [ ] DLQ events are reviewable (original payload + error message + timestamp)
- [ ] DLQ replay mechanism exists or is planned
- [ ] FatalError → DLQ; RetryableError → retry with backoff

## 7. Backpressure (S6 NLP Pipeline Specific)

- [ ] `asyncio.Semaphore` limits concurrent Ollama/ML calls
- [ ] Queue depth monitored (metric exposed)
- [ ] Consumer pauses consumption when backpressure threshold reached
- [ ] Recovery: consumer resumes when queue drains below threshold

## 8. Event Envelope

- [ ] Event includes all required envelope fields:
  - `event_id` (UUIDv7)
  - `event_type` (`domain.entity.verb_past`)
  - `schema_version` (integer)
  - `occurred_at` (ISO-8601 UTC)
  - `correlation_id` (optional, for tracing)
  - `causation_id` (optional, event that caused this)
- [ ] `event_type` matches topic name semantics
- [ ] `occurred_at` is event time, not processing time

## 9. Topic Configuration

- [ ] Topic name follows convention: `<domain>.<entity>.<verb_past>`
- [ ] Partition count appropriate for parallelism needs
- [ ] Retention policy set (time-retention or compacted)
- [ ] Compacted topics: key = entity ID, value = latest state
- [ ] Replication factor ≥ 1 for durability

## Scoring

| Result | Meaning |
|--------|---------|
| All PASS or N/A | Pipeline is correct |
| FAIL in 1-3 | Investigate — may be safe depending on context |
| FAIL in 4-6 | Fix before merge — data integrity at risk |
| FAIL in 7+ | Block — pipeline fundamentally broken |

## Compounding Updates
This document is a living reference. Update it when:
- A new Kafka-related bug pattern is discovered
- A new service adds Kafka consumers/producers
- Backpressure tuning changes for ML pipeline services

Last updated: 2026-03-25
