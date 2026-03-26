# Edge Case Generation

> Systematic generators for identifying edge cases in worldview services. Used by `/review`, `/test-feature`, and `/investigate` skills.

## Generator 1: Data Volume Extremes

| Scenario | Test |
|----------|------|
| Empty result set | Query returns 0 rows — does caller handle gracefully? |
| Single item | Collection with exactly 1 element — boundary conditions? |
| Maximum batch | EODHD API returns max allowed symbols — pagination correct? |
| Large payload | Article > 100KB — claim-check triggered? Memory OK? |
| High cardinality | 10,000 entities in knowledge graph — query performance? |

## Generator 2: Null / None / Missing

| Scenario | Test |
|----------|------|
| Optional field is None | Pydantic model with Optional[str] = None — serialization? |
| Missing JSON key | External API omits expected field — KeyError? |
| Empty string vs None | "" vs None — are they handled differently? |
| Null in DB column | Nullable column returns None — NoneType access? |
| Missing env var | Required config not set — clear error or silent default? |

## Generator 3: Timestamps & Temporal

| Scenario | Test |
|----------|------|
| Naive datetime | `datetime.now()` without tz — should be caught by lint |
| Timezone mismatch | UTC stored, local displayed — conversion correct? |
| Future timestamp | `occurred_at` in the future — accepted or rejected? |
| Epoch boundary | 1970-01-01, 2038 boundary — handled? |
| DST transition | For any user-facing time display — correct across DST? |
| Stale data | Cache entry from 24h ago — TTL expired correctly? |

## Generator 4: Schema & Type Boundaries

| Scenario | Test |
|----------|------|
| Avro schema evolution | Consumer receives event with new unknown field — ignored gracefully? |
| Avro schema regression | Producer sends event missing a required field — caught at publish? |
| Integer overflow | Price * quantity exceeds float precision — Decimal used? |
| Unicode in entity names | Company name with CJK/Arabic/emoji — NER handles? Storage OK? |
| Very long string | 10KB company description — DB column limit? Truncation? |

## Generator 5: Concurrency & Retry

| Scenario | Test |
|----------|------|
| Duplicate Kafka event | Same event_id delivered twice — idempotent? |
| Concurrent writes | Two consumers process same entity — upsert or conflict? |
| Stale read | Read entity, process, write — entity changed between read and write? |
| Consumer rebalance | Mid-processing rebalance — message reprocessed correctly? |
| Outbox replay | Outbox dispatcher restarts — events published twice? |

## Generator 6: External Dependency Failure

| Scenario | Test |
|----------|------|
| EODHD API down | S2 ingestion — retry with backoff? Negative cache? |
| RSS feed malformed | S4 content ingestion — HTML parse error handled? |
| Ollama timeout | S6 NLP pipeline — backpressure engaged? Consumer paused? |
| LLM returns garbage | S8 RAG chat — output sanitization strips `<think>` blocks? |
| MinIO unreachable | Claim-check dereference — RetryableError, not crash? |
| Valkey down | Cache miss path — fail-open, serve from DB? |
| Schema Registry down | Avro serialization — fail or use cached schema? |

## Generator 7: Worldview-Specific Edge Cases

| Scenario | Test |
|----------|------|
| MinHash collision | Two different articles have same MinHash — dedup threshold correct? |
| Entity resolution ambiguity | "Apple" = company or fruit? — GLiNER confidence threshold? |
| intelligence_db partition boundary | Event spans month boundary — correct partition selected? |
| Compacted topic stale key | entity.dirtied.v1 with old key version — consumer handles? |
| Watchlist cache invalidation race | User updates watchlist while cache being rebuilt — stale? |
| Cross-tenant entity name match | Same company name, different tenants — isolation preserved? |
| Negative EODHD cache | Symbol doesn't exist — neg cache prevents retry storm? |

## How to Use

When reviewing or testing code:
1. Identify which generators apply to the code under review
2. For each applicable generator, walk through each scenario
3. For each scenario: is there a test? Is the code path handled?
4. If not handled: is it a real risk or acceptable limitation?

## Compounding Updates
This document is a living reference. Update it when:
- A new edge case is discovered during testing or production
- A new external dependency is added
- A new service introduces novel data patterns

Last updated: 2026-03-25
