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


---

## ORANGE — Added from PLAN-0001-B-R4 QA Review (2026-03-27)

### HR-019: Blocking I/O in Pydantic Validators
```python
@field_validator("url")
@classmethod
def validate_url(cls, v: str) -> str:
    addrs = socket.getaddrinfo(hostname, None)  # BLOCKS THE EVENT LOOP
    requests.get(url)                           # BLOCKS THE EVENT LOOP
    open(path).read()                           # BLOCKS THE EVENT LOOP
    ...
```
**Risk**: Pydantic validators called from async FastAPI handlers run synchronously on the event loop. Any blocking I/O (DNS, HTTP, file I/O) freezes the entire service for the duration of that operation.
**Fix**: Only do fast, CPU-bound checks in Pydantic validators (scheme check, regex, literal IP check). Move DNS/HTTP/file I/O to the async route handler using `asyncio.to_thread`.

### HR-020: SSRF With IPv4-Only IP Range Checks
```python
_PRIVATE = [ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("127.0.0.0/8")]
def is_private(addr):
    return any(addr in net for net in _PRIVATE)  # misses ::ffff:127.0.0.1
```
**Risk**: IPv4-mapped IPv6 addresses (e.g., `::ffff:127.0.0.1`) bypass manual IPv4 range lists because the list entries are `IPv4Network` objects but `addr` is `IPv6Address`.
**Fix**: Use `addr.is_private or addr.is_reserved or addr.is_loopback or addr.is_multicast`, and unwrap IPv4-mapped IPv6 first: `if isinstance(addr, IPv6Address) and addr.ipv4_mapped: addr = addr.ipv4_mapped`.

---

## ORANGE — Added from PLAN-0001-E QA Review (2026-03-28)

### HR-021: Non-atomic Consumer Dedup (Separate UoW per Phase)
```python
async def is_duplicate(self, event_id):
    async with await self.get_unit_of_work() as uow:
        return await uow.idempotency.exists(uid)   # transaction 1

async def process_message(self, ...):
    async with await self.get_unit_of_work() as uow:
        await uow.things.upsert(...)               # transaction 2

async def mark_processed(self, event_id):
    async with await self.get_unit_of_work() as uow:
        await uow.idempotency.record(uid)          # transaction 3
```
**Risk**: Concurrent consumers both pass `is_duplicate` → double-process the same event (BP-045).
**Fix**: Apply BP-035 — single transaction with atomic `INSERT … ON CONFLICT DO NOTHING RETURNING` inside `process_message`. Set `is_duplicate()` → `return False`; `mark_processed()` → no-op.

### HR-022: Cache Invalidation Before `uow.commit()` (M-005 Violation)
```python
async def process_message(self, ...):
    await uow.quotes.upsert(quote)          # DB write (uncommitted)
    await self._cache.invalidate(id)        # ← called before commit
    # base class commits uow later
```
**Risk**: A client read between invalidation and commit caches the OLD stale DB value (BP-046). After commit, cache serves stale data until TTL expiry.
**Fix**: Use `uow.schedule_post_commit(cache.invalidate(id))`. The hook drains after `write_session.commit()`.

### HR-023: `readyz` Endpoint Returning Raw Exception String
```python
except Exception as exc:
    checks["db"] = f"error: {exc}"   # leaks DSN, password, host info
```
**Risk**: Clients (or proxies that log 503 bodies) receive internal connection strings including database host, port, user, and potentially password (BP-047).
**Fix**: `checks["db"] = "error"` — opaque string in HTTP; log full details via structured logger internally only.

### HR-025: UoW `__aexit__` Auto-Commit (R26 Violation)

```python
# BAD — Option A (auto-commit in __aexit__)
async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
    try:
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()   # ← FORBIDDEN
    ...
```

**Risk**: BLOCKING — silent writes on every clean context exit. Read-only use cases commit
empty transactions. Double-commit bugs are invisible (second `session.commit()` is a no-op).
Discovered as a live bug in market-ingestion `SqlaUnitOfWork` (F-DS-004/PLAN-0008).

**Grep pattern**:
```bash
grep -rn "else.*commit\|__aexit__.*commit" services/*/src/*/infrastructure/db/unit_of_work.py
```

**Fix**: Remove `else: await self.commit()` from `__aexit__`. Add explicit `await uow.commit()`
to every mutating use case. See STANDARDS.md §17 and RULES.md R26.

---

### HR-024: `asyncio.Event.set()` in librdkafka Delivery Callback Without `call_soon_threadsafe`
```python
def _cb(err, _msg):
    delivery_event.set()   # asyncio primitive mutated from C thread
loop = asyncio.get_event_loop()  # too late — after _cb definition
```
**Risk**: librdkafka delivery callbacks run on a C thread, not the asyncio event loop thread. Direct `event.set()` is not thread-safe (BP-050). Rare deadlocks under contention.
**Fix**: Capture `loop` before defining `_cb`; use `loop.call_soon_threadsafe(delivery_event.set)` inside the callback.
