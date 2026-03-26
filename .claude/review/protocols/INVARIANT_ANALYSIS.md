# Invariant Analysis

> Worksheet for identifying and testing system invariants. Used by `/review` and `/investigate` skills.

## What Is an Invariant?

A property that must ALWAYS hold, regardless of input, timing, or failure conditions. If an invariant is violated, the system is in an inconsistent state.

## Invariant Categories

### 1. Data Integrity Invariants

| Invariant | Enforcement | Test |
|-----------|-------------|------|
| All entity IDs are UUIDv7 | `common.ids.new_uuid7()` | Grep for `uuid.uuid4()` — must not exist in production code |
| All timestamps are UTC-aware | `common.time.utc_now()` | Grep for `datetime.now()` without tz, `datetime.utcnow()` |
| Foreign keys reference existing entities | DB constraints or app-level validation | Test with non-existent FK → expect error |
| Enum values are from defined set | Pydantic validation at API boundary | Test with invalid enum → expect 422 |
| Entity state transitions follow defined graph | Domain entity validation | Test invalid transition → expect DomainError |

### 2. Transaction Boundary Invariants

| Invariant | Enforcement | Test |
|-----------|-------------|------|
| DB write + Kafka publish in same logical transaction | Outbox pattern (libs/messaging) | Test DB commit + Kafka failure → event still in outbox |
| No partial writes visible to consumers | Single DB transaction scope | Test mid-transaction failure → no partial data visible |
| Alembic migrations are atomic per version | Alembic transaction-per-migration default | Test rollback after failed migration |

### 3. Ordering Invariants

| Invariant | Enforcement | Test |
|-----------|-------------|------|
| Events processed at-least-once | Kafka consumer offset management | Test consumer restart → messages reprocessed |
| Idempotent processing | event_id dedup or upsert | Test duplicate event → no side effects |
| UUIDv7 IDs are time-sortable | Generation via `new_uuid7()` | Verify ordering of IDs generated in sequence |

### 4. Tenant Isolation Invariants

| Invariant | Enforcement | Test |
|-----------|-------------|------|
| Queries always filter by tenant_id | Repository implementations | Audit all SELECT queries for WHERE tenant_id = |
| API responses contain only requesting tenant's data | API layer filtering | Test cross-tenant access → expect 403 or empty |
| Kafka events include tenant_id | Event envelope contract | Validate event schema includes tenant_id field |
| Valkey cache keys include tenant scope | Cache key pattern | Verify key format: `<scope>:<version>:<resource>:<tenant_id>:<id>` |

### 5. Worldview-Specific Invariants

| Invariant | Enforcement | Test |
|-----------|-------------|------|
| intelligence_db DDL only from init container | `ALEMBIC_ENABLED=false` in S6/S7 | Test S6/S7 startup with ALEMBIC_ENABLED=true → should be blocked |
| ml-clients is only path for ML calls | Import guards (check_import_guards.py) | Architecture test: no direct ollama/anthropic imports |
| No cross-service DB access | Import guards + architecture tests | Test: service A cannot import service B's DB adapters |
| Avro schemas are forward-compatible | Schema guard hook + gen-contracts.sh | Test field removal → validation failure |
| Outbox events eventually dispatched | Outbox dispatcher poll loop | Test: create outbox row → verify Kafka message within N seconds |
| Claim-check pointers resolve | MinIO object exists at pointer path | Test: publish pointer → dereference → object exists |

## Testing Invariants Under Edge Cases

For each invariant, test these scenarios:

| Scenario | Description |
|----------|-------------|
| **Empty** | Empty input, empty collection, empty result set |
| **Large** | Maximum expected volume + 10x |
| **Null** | None where optional, missing field where required |
| **Retry** | Same operation executed twice (idempotency) |
| **Concurrent** | Two operations on same resource simultaneously |
| **Partial failure** | Infrastructure fails mid-operation |
| **Timeout** | External dependency takes longer than expected |
| **Out of order** | Events arrive in non-chronological order |

## Compounding Updates
This document is a living reference. Update it when:
- A new invariant is identified during implementation or review
- An existing invariant is found to be incorrectly specified
- A new service or feature introduces invariants not covered here

Last updated: 2026-03-25
