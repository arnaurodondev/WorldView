# Failure Mode Analysis

> Structured procedure for enumerating failure modes per function/operation. Used by `/review` and `/investigate` skills.

## Procedure

For each function or operation with side effects:

### Step 1: Decompose into Steps
Break the function into discrete sequential steps:
```
1. Read input / validate
2. Fetch from database
3. Transform / compute
4. Write to database
5. Publish event (via outbox)
6. Update cache
7. Return response
```

### Step 2: Enumerate Failures Per Step

| Step | Failure Mode | Probability | System State After | Severity | Recovery |
|------|-------------|-------------|-------------------|----------|----------|
| 1. Validate | Malformed input | MEDIUM | Unchanged | LOW | Return 422 |
| 2. DB read | Connection timeout | LOW | Unchanged | MEDIUM | Retry |
| 3. Transform | Business rule violation | MEDIUM | Unchanged | LOW | Return error |
| 4. DB write | Constraint violation | LOW | Unchanged (rollback) | MEDIUM | Fix data |
| 5. Outbox publish | Transaction commit fail | VERY LOW | Unchanged (rollback) | HIGH | Retry tx |
| 6. Cache update | Valkey unavailable | LOW | DB updated, cache stale | LOW | Cache TTL |
| 7. Return | Network error | VERY LOW | All side effects done | LOW | Client retry |

### Step 3: Classify Severity

| Severity | Criteria | Examples |
|----------|----------|---------|
| **CRITICAL** | Data loss, corruption, or security breach | Partial write visible, tenant data leak |
| **HIGH** | System inconsistency requiring manual intervention | Outbox orphan, stuck consumer |
| **MEDIUM** | Degraded functionality, auto-recoverable | Cache miss, retry storm |
| **LOW** | Cosmetic or gracefully handled | Validation error, expected 404 |

### Step 4: Identify Dangerous Modes

Flag any failure where:
- [ ] **Partial visibility**: Some writes committed, others not (dual write without outbox)
- [ ] **Swallowed exception**: Error caught but not logged, re-raised, or classified
- [ ] **Broken idempotency**: Re-delivery causes duplicate side effects
- [ ] **Resource leak**: Connection, file handle, or lock not released on failure path
- [ ] **Silent corruption**: Data written in invalid state without error

## Worldview-Specific Templates

### FastAPI Async Handler
```
1. Parse request (Pydantic validation)
2. Authenticate/authorize (tenant_id extraction)
3. Execute use case (application layer)
   3a. Read from repository (port)
   3b. Domain logic (pure)
   3c. Write to repository (port)
   3d. Publish event (outbox — same DB transaction)
4. Return response

Dangerous modes:
- Step 2 failure: Ensure fail-closed (deny on error, not allow)
- Step 3c+3d: Must be in same transaction (outbox pattern)
- Step 3 exception: Must classify as RetryableError or FatalError
```

### Kafka Consumer
```
1. Deserialize event (Avro)
2. Check idempotency (event_id lookup)
3. Dereference claim-check (MinIO fetch, if applicable)
4. Process business logic
5. Write to DB
6. Commit offset

Dangerous modes:
- Step 1: Malformed message → DLQ, not crash
- Step 2: Missing idempotency key → assume new, process
- Step 3: MinIO unavailable → RetryableError, don't commit offset
- Step 5: DB failure after processing → retry safe (idempotent)
- Step 6: Offset commit failure → message reprocessed (must be idempotent)
```

### Outbox Dispatcher
```
1. Poll outbox table for pending events
2. Serialize to Avro
3. Publish to Kafka
4. Mark outbox row as dispatched (same DB transaction? No — separate)
5. Handle publish failure

Dangerous modes:
- Step 2: Serialization failure (schema mismatch) → FatalError, DLQ the row
- Step 3: Kafka unavailable → RetryableError, leave row pending
- Step 4: DB failure after Kafka success → event published twice on retry (consumers must be idempotent)
- Step 5: Must NOT delete outbox row if Kafka publish failed
```

### MinIO Claim-Check Operations
```
1. Generate deterministic key (service/domain/resource_id/artifact/version.ext)
2. Put object to MinIO
3. Write claim-check pointer to DB/outbox
4. Consumer: dereference pointer (GET from MinIO)

Dangerous modes:
- Step 2: MinIO unavailable → RetryableError, don't write pointer
- Step 3: DB failure after MinIO write → orphaned object (acceptable, no data loss)
- Step 4: Object deleted before consumer reads → FatalError, investigate
```

## Compounding Updates
This document is a living reference. Update it when:
- A new failure pattern is discovered during /review or /fix-bug
- A worldview-specific template proves incomplete
- A session evaluation identifies a gap

Last updated: 2026-03-25
