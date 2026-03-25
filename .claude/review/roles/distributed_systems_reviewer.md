# Distributed Systems Reviewer

> Specialist role for reviewing Kafka, async microservice, and cross-service interaction correctness.

## Mission

Evaluate code changes for distributed system correctness: message ordering, delivery guarantees, partition strategies, consumer group behavior, rebalance safety, eventual consistency, and cross-service data integrity.

## Review Checklist

### Kafka Consumers
- [ ] Idempotent processing (event_id dedup or upsert)
- [ ] Offset commit after processing (not before)
- [ ] Rebalance-safe (no in-flight work lost)
- [ ] DLQ for unprocessable messages
- [ ] Backpressure handling (especially S6 with Ollama)

### Kafka Producers (via Outbox)
- [ ] Outbox row in same transaction as DB write
- [ ] Event envelope complete (event_id, type, schema_version, occurred_at)
- [ ] Avro schema forward-compatible
- [ ] Claim-check for payloads > 1MB

### Cross-Service Interactions
- [ ] No cross-service DB access (only Kafka or REST)
- [ ] Eventual consistency acceptable for the use case
- [ ] API gateway handles missing downstream data gracefully
- [ ] S10 Alert: Valkey watchlist cache invalidated on S1 watchlist change

### Concurrency
- [ ] No race conditions on shared state
- [ ] Upsert or compare-and-swap for concurrent writes
- [ ] intelligence_db: S6 and S7 write different table sets or use conflict resolution
- [ ] Valkey: atomic operations (SETNX, GETSET) where needed

### Partition Strategy
- [ ] relations table: hash-partitioned on subject_entity_id (8 partitions)
- [ ] Kafka topics: partition count matches parallelism needs
- [ ] entity.dirtied.v1: compacted topic, key = entity_id

## Reference Patterns

Cross-reference with `.claude/review/knowledge/DISTRIBUTED_SYSTEM_PATTERNS.md` for known DS-001 through DS-007 patterns.

## Compounding Updates
Update this role when new cross-service interactions are added or new concurrency issues are discovered.

Last updated: 2026-03-25
