# Distributed System Patterns

> Known failure patterns in Kafka-based microservice architectures. Cross-reference during `/review` and `/investigate`.

## DS-001: Consumer Rebalance During Processing

**Pattern**: Kafka consumer is processing a message when a rebalance occurs. The message is re-assigned to another consumer, causing duplicate processing.

**Symptoms**: Duplicate records, double-counted metrics, duplicate notifications.

**Worldview relevance**: All Kafka consumers (S3, S5, S6, S7, S10).

**Prevention**:
- Idempotent processing (event_id dedup or upsert)
- Short processing time (reduces rebalance window)
- Cooperative rebalancing (Kafka 3.0+)

## DS-002: Outbox Dispatcher Race Condition

**Pattern**: Outbox dispatcher reads pending rows, publishes to Kafka, marks as dispatched. If dispatcher crashes between publish and mark, the event is published again on restart.

**Symptoms**: Duplicate events in Kafka topic.

**Worldview relevance**: All services with outbox pattern (S1, S2, S3, S4, S5, S6, S7, S10).

**Prevention**:
- Consumers MUST be idempotent (this is the intended design)
- Dispatcher should use atomic mark-after-publish where possible
- Monitor outbox table for stuck rows (dispatched_at IS NULL AND age > threshold)

## DS-003: Cross-Service Eventual Consistency

**Pattern**: Service A writes to its DB and publishes an event. Service B consumes the event and updates its DB. Between publish and consumption, the two databases are inconsistent.

**Symptoms**: Queries that join data from multiple services return stale or mismatched results.

**Worldview relevance**: S2→S3 (market data), S4→S5→S6→S7 (content pipeline), S1↔S10 (portfolio↔alerts).

**Prevention**:
- Accept eventual consistency as a design constraint (not a bug)
- Frontend should show "last updated" timestamps
- API gateway composition endpoints should handle missing downstream data gracefully

## DS-004: intelligence_db Concurrent Writes

**Pattern**: S6 (NLP Pipeline) and S7 (Knowledge Graph) both write to `intelligence_db`. If both write to the same entity simultaneously, one may overwrite the other.

**Symptoms**: Lost updates, inconsistent entity state.

**Worldview relevance**: Critical for canonical_entities, relation_evidence_raw tables.

**Prevention**:
- S6 and S7 write to different table sets where possible
- Use upsert with conflict resolution (ON CONFLICT DO UPDATE)
- Entity resolution uses deterministic merge logic (not last-writer-wins)

## DS-005: Kafka Non-Idempotent Consumer

**Pattern**: Consumer processes a message and produces side effects (DB write, external API call, notification) without checking if the message was already processed.

**Symptoms**: Duplicate alerts, duplicate DB rows, incorrect aggregations.

**Worldview relevance**: S10 Alert Service (must not send duplicate alerts to users).

**Prevention**:
- Idempotency table with event_id
- Alert dedup window (S10: 300s per user+entity+alert_type)
- Upsert semantics for DB writes

## DS-006: LLM Provider Fallback Chain Failure

**Pattern**: S8 RAG Chat has a 4-tier fallback chain (Ollama → Groq → OpenRouter → OpenAI). If all providers fail simultaneously, the service has no fallback.

**Symptoms**: Chat endpoint returns 503, user sees error.

**Worldview relevance**: S8 RAG Chat service.

**Prevention**:
- Negative cache (60s) prevents retry storms on failing providers
- Graceful degradation message to user ("Service temporarily unavailable")
- Monitor provider health independently (provider status endpoint)

## DS-007: Claim-Check Dereference Failure

**Pattern**: Kafka event contains a MinIO pointer (claim-check). Consumer tries to dereference but the object doesn't exist (deleted, wrong key, MinIO down).

**Symptoms**: Consumer fails, message goes to DLQ, data loss.

**Worldview relevance**: S3 (market data from S2), S5 (articles from S4), S6 (cleaned text from S5).

**Prevention**:
- MinIO objects are immutable (never deleted while referenced)
- Consumer treats MinIO unavailable as RetryableError (not FatalError)
- Log full claim-check key on failure for debugging

## Compounding Updates
This document is a living reference. Update it when:
- A new distributed failure pattern is observed
- A new inter-service interaction is added
- An existing pattern's mitigation proves insufficient

Last updated: 2026-03-25
