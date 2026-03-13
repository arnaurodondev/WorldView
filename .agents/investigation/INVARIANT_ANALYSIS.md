# Invariant Analysis

> **Purpose**: A worksheet for identifying and verifying system invariants.
> Used as a sub-procedure within [PR_INVESTIGATION_PROTOCOL.md](PR_INVESTIGATION_PROTOCOL.md)
> (Step 4).

---

## What Is an Invariant?

An invariant is a condition that must **always** hold, regardless of execution path,
input values, timing, or retries.

Invariants are the contracts the code makes with the rest of the system.
A broken invariant is always a bug — often a silent one.

---

## Invariant Categories

### Category 1 — Data Integrity Invariants

The shape and consistency of data must be preserved.

**Examples**:

```
len(features) == len(labels)
  — arrays must stay aligned throughout transformation

instrument_id in (SELECT id FROM instruments)
  — foreign key consistency: no orphan records

ohlcv_bars final prefix contains either all bar files or none
  — storage atomicity invariant

outbox_events.status IN ('PENDING', 'CLAIMED', 'DISPATCHED', 'DEAD')
  — state machine invariant: no unknown statuses
```

### Category 2 — Transaction Boundary Invariants

Writes that must succeed or fail atomically.

**Examples**:

```
(domain entity written to DB) AND (outbox event written to DB) are atomic
  — dual-write invariant: both or neither

migration 001 and migration 002 both applied, or neither
  — migration atomicity invariant
```

### Category 3 — Ordering Invariants

Operations that must occur in a fixed order.

**Examples**:

```
TimescaleDB extension must be created before create_hypertable() is called

Alembic migration 001 must be applied before migration 002

Kafka consumer processes events in offset order within a partition
```

### Category 4 — Idempotency Invariants

Operations that must produce the same result when run twice.

**Examples**:

```
Ingestion event processing is idempotent:
  processing the same event_id twice must not create duplicate DB rows

Outbox dispatch is idempotent:
  dispatching the same outbox_event_id twice must not produce duplicate Kafka messages

Alembic upgrade head is idempotent:
  running upgrade head twice must leave the DB in the same state
```

### Category 5 — Visibility Invariants

What external observers can see at any point in time.

**Examples**:

```
No reader observes a partial S3 prefix during a copy operation

No downstream consumer reads an MLflow run until it is in FINISHED state

No API response references an instrument that has no associated security record
```

---

## Invariant Identification Worksheet

For the code under review, fill in this table:

| # | Invariant statement | Category | Where enforced | Broken by? |
|---|--------------------|---------|--------------|-----------|
| 1 | | | | |
| 2 | | | | |

**Where enforced**: which code path, transaction boundary, or constraint enforces this invariant?

**Broken by?**: which failure mode from [FAILURE_MODE_ANALYSIS.md](FAILURE_MODE_ANALYSIS.md)
can violate this invariant?

---

## Test Matrix

For each invariant, test it under:

| Scenario | Expected: invariant holds? | Actual (code reading)? |
|---------|--------------------------|----------------------|
| Normal execution | ✓ | |
| Empty input | ✓ | |
| Failure at step N | ✓ | |
| Retry after failure | ✓ | |
| Concurrent execution | ✓ | |
| Large input (10x expected) | ✓ | |

If "Actual" is ✗ for any scenario, that is a finding.

---

## Common Invariant Violations in This Codebase

### Violation: Dual-write without outbox

```python
# WRONG — two separate writes; one can succeed and the other fail
await session.add(entity)
await session.commit()
await kafka_producer.send(event)  # can fail after DB commit
```

```python
# CORRECT — outbox pattern; both writes in the same transaction
async with uow:
    uow.repository.add(entity)
    uow.collect_event(DomainEvent(...))
    await uow.commit()  # commits entity + outbox row atomically
```

### Violation: Partial storage prefix visible to readers

```python
# WRONG — copies objects to final prefix one by one; readers see partial state
for obj in objects:
    s3.copy(obj, final_prefix + obj.key)
# failure here leaves partial final prefix
```

```python
# CORRECT — copy to staging first, then atomic rename (or delete-on-failure)
for obj in objects:
    s3.copy(obj, staging_prefix + obj.key)
try:
    s3.copy_prefix(staging_prefix, final_prefix)
except:
    s3.delete_prefix(final_prefix)  # roll back partial
    raise
finally:
    s3.delete_prefix(staging_prefix)
```

### Violation: Array alignment lost after filter

```python
# WRONG — filter on one array but not the other
features = [f for f in features if f is not None]
# labels unchanged — len(features) != len(labels) now
```

---

## Output

For each invariant violation found, produce a finding using the format from
[PR_INVESTIGATION_PROTOCOL.md](PR_INVESTIGATION_PROTOCOL.md) (Output Requirements section).
