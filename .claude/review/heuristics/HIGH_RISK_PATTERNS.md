# High-Risk Patterns

> Code patterns that signal elevated risk. When detected, investigate before approving.

## RED — Must Investigate and Fix

### HR-001: Broad Exception Suppression
```python
# BAD
except Exception:
    pass  # or: return None / return default
```
**Risk**: Silently masks bugs, data corruption, security issues.
**Fix**: Catch specific exceptions. Log and re-raise or classify as RetryableError/FatalError.

### HR-002: Empty Except Block
```python
# BAD
except:
    ...
```
**Risk**: Catches SystemExit, KeyboardInterrupt — masks everything.
**Fix**: Always specify exception type. Never use bare `except:`.

### HR-003: Direct Write to Final Path
```python
# BAD — partial write on failure
with open(final_path, 'w') as f:
    f.write(data)
```
**Risk**: Interrupted write leaves corrupted file.
**Fix**: Write to temp file first, then atomic rename.

### HR-004: Dual Write Without Outbox
```python
# BAD
await db.commit()
await kafka.send(event)  # Separate transaction!
```
**Risk**: DB committed but Kafka fails = data inconsistency.
**Fix**: Use outbox pattern from `libs/messaging`.

### HR-005: Hardcoded Credentials
```python
# BAD
password = "my_secret_123"
api_key = "sk-..."
```
**Risk**: Credential exposure in source control.
**Fix**: Use environment variables via pydantic-settings.

### HR-006: F-String SQL
```python
# BAD
query = f"SELECT * FROM users WHERE id = '{user_id}'"
```
**Risk**: SQL injection.
**Fix**: Use parameterized queries or SQLAlchemy ORM.

## ORANGE — Investigate Before Approving

### HR-007: Broad Except in Finally
```python
# SUSPICIOUS
finally:
    try:
        cleanup()
    except Exception:
        pass
```
**Risk**: Masks cleanup failures, may hide resource leaks.
**Action**: Verify cleanup failure is truly non-critical. At minimum, log it.

### HR-008: Return Inside Except
```python
# SUSPICIOUS
except SomeError:
    return default_value
```
**Risk**: May hide the fact that an error occurred from callers.
**Action**: Verify this is intentional and the caller expects this behavior.

### HR-009: External API Call Inside DB Transaction
```python
# SUSPICIOUS
async with session.begin():
    result = await external_api.call()  # Holds transaction!
    await session.add(Entity(data=result))
```
**Risk**: Long transaction hold; external timeout = DB connection exhaustion.
**Fix**: Call external API first, then open transaction for DB write.

### HR-010: Unbounded Collection
```python
# SUSPICIOUS
all_items = await repo.get_all()  # How many?
results = [process(item) for item in all_items]
```
**Risk**: OOM on large datasets.
**Fix**: Use pagination, streaming, or bounded batch size.

### HR-011: Naive Datetime
```python
# SUSPICIOUS
from datetime import datetime
now = datetime.now()  # No timezone!
```
**Risk**: Timezone bugs, comparison failures.
**Fix**: `datetime.now(tz=timezone.utc)` or `common.time.utc_now()`.

### HR-012: Direct UUID4
```python
# SUSPICIOUS
import uuid
entity_id = uuid.uuid4()
```
**Risk**: Non-time-sortable IDs, violates project convention.
**Fix**: Use `common.ids.new_uuid7()`.

## YELLOW — Note for Review

### HR-013: Complex Conditional Without Tests
```python
if a and (b or (c and not d)) and e:
    # Complex branch
```
**Action**: Verify this branch has dedicated test cases.

### HR-014: Magic Numbers
```python
if retry_count > 3:  # Why 3?
    timeout = 0.5  # Why 0.5?
```
**Action**: Extract to named constants with documentation.

### HR-015: Duplicated Logic
```python
# Same pattern in multiple places
result = transform(data)
validated = validate(result)
await publish(validated)
```
**Action**: Check if existing lib utilities cover this pattern.

### HR-016: Direct Logging Import
```python
import logging
logger = logging.getLogger(__name__)
```
**Risk**: Bypasses structlog; violates project convention.
**Fix**: `import structlog; logger = structlog.get_logger()`

---

## RED — Added from S4 QA Review (2026-03-26)

### HR-017: Python `hash()` for Distributed Coordination
```python
lock_id = hash(f"s4:fetch:{source.name}")
await session.execute(text(f"SELECT pg_try_advisory_lock({lock_id})"))
```
**Risk**: `hash()` is randomized per process (PEP 456). Different pods compute different lock IDs, defeating mutual exclusion.
**Fix**: Use `hashlib.sha256` for deterministic cross-process hashing. See `messaging.pg.advisory_lock`.

---

## ORANGE — Added from S4 QA Review (2026-03-26)

### HR-018: `setattr` with User-Controlled Keys Without Allowlist
```python
for key, value in kwargs.items():
    setattr(model, key, value)
```
**Risk**: Mass-assignment vulnerability — callers can overwrite internal fields (`id`, `created_at`, `status`) if not constrained.
**Fix**: Define `_MUTABLE_FIELDS = frozenset({"name", "enabled", "config"})` and reject keys not in the set.
