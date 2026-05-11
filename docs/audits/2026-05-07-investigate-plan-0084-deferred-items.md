# Investigation Report: PLAN-0084 Deferred QA Items

**Date**: 2026-05-07
**Skill**: investigate
**Branch**: feat/content-ingestion-wave-a1
**Scope**: 9 deferred findings from QA Wave 7 (F-S001, F-S004, F-DS002, F-S008, F-DS005, F-DS012, F-T004, F-T007, F-T008)

---

## 1. Issue Summary

QA Wave 7 deferred 9 findings as "acceptable for now" or "needs ADR". This investigation
re-examines each with fresh eyes, measures concrete impact, and classifies each as
ACCEPT (no code change), MITIGATE (fix warranted), or ESCALATE (needs ADR/external decision).

---

## 2. Findings

### F-DS005 — ZADD timestamp-as-member coalescing (MITIGATE — confirmed genuine bug)

**Root Cause**:
`services/rag-chat/src/rag_chat/infrastructure/cache/circuit_breaker_cache.py` uses Valkey ZADD
to store circuit breaker failure timestamps. The ZADD member was set to `str(time.time())` — the
same float used as the score. On macOS (and any platform where Python's `time.time()` resolution
exceeds the actual clock tick rate), consecutive calls within a single tick return identical floats.

**Measured Impact**:
A tight loop of 999 consecutive `time.time()` calls on macOS returned identical values for
957/999 iterations (95.7%). Because ZADD members must be unique within a sorted set, each
duplicate member overwrites the previous entry's score without increasing ZSET cardinality.
Outcome: 999 rapid failures may register as only 42 distinct entries in the ZSET, far below
`failure_threshold=3`. The circuit breaker would never trip under synthetic load or in tests
that mock time.

**Long-Term Fix**:
Append a short random suffix to the ZADD member to guarantee uniqueness:
```python
member = f"{timestamp}:{uuid.uuid4().hex[:8]}"
```
Score remains `timestamp` (float) so ZRANGEBYSCORE TTL pruning is unaffected.

**File**: `services/rag-chat/src/rag_chat/infrastructure/cache/circuit_breaker_cache.py`

---

### F-S001 — Differentiated JWT error messages (information leak) (MITIGATE — reduce externally)

**Root Cause**:
`services/rag-chat/src/rag_chat/infrastructure/middleware/internal_jwt.py` returns distinct
HTTP 401 bodies:
- `"JWT has expired"` — reveals expiry vs. forgery distinction to external callers
- `"Invalid token"` / `"Invalid token format"` — distinguishes decode failure from format failure

An attacker can enumerate whether a stolen token is expired (try again after refresh) vs. invalid
(wrong service or malformed). This is a low-severity information leak (no cryptographic bypass),
but the differentiation provides unnecessary attack surface intelligence.

**Long-Term Fix**:
Return a single opaque external message `"Unauthorized"` for all 401 cases. Preserve internal
observability with structlog: `log.info("jwt_expired", ...)`, `log.info("jwt_invalid", ...)`.
This satisfies debuggability (logs) while eliminating external enumeration.

**File**: `services/rag-chat/src/rag_chat/infrastructure/middleware/internal_jwt.py`

---

### F-S004 — JTI replay fail-open without Prometheus counter (MITIGATE — add counter)

**Root Cause**:
The JTI replay check in `internal_jwt.py` has:
```python
except Exception:
    pass  # fail-open: Valkey outage → bypass JTI check
```
There is no Prometheus counter on this path. If Valkey is degraded, every request bypasses the
JTI replay check silently — zero observability. The existing `rag_jti_check_valkey_unavailable`
counter only covers the SETNX path, not the bypass path.

**Long-Term Fix**:
Add `rag_jti_check_bypass_total` Counter in `services/rag-chat/src/rag_chat/prometheus.py`.
Increment it in the JTI `except Exception` handler. Alert threshold: >0 in production.

**File**: `services/rag-chat/src/rag_chat/infrastructure/middleware/internal_jwt.py`,
          `services/rag-chat/src/rag_chat/prometheus.py`

---

### F-DS002 — DB session cleanup on CancelledError in cron (ACCEPT — confirmed safe)

**Root Cause Investigation**:
`services/rag-chat/src/rag_chat/infrastructure/jobs/citation_accuracy_cron.py` calls
`_ReadSessionRepo.sample_recent_with_citations()`. That repository has:
```python
async def sample_recent_with_citations(self, ...):
    session = self._session_factory()
    try:
        ...
        return results
    finally:
        await session.close()
```
Python 3.8+ `CancelledError` is a `BaseException`, not `Exception`. The `try/finally` block
executes unconditionally on `CancelledError`. Session is guaranteed to close.

**Verdict**: ACCEPT — no code change needed. Added regression test recommendation below.

---

### F-S008 — Multi-tenant dedup key isolation (ACCEPT — single-tenant platform)

**Root Cause**:
`ValkeyDedupMixin.is_duplicate()` builds dedup key as `f"{self._dedup_prefix}:{event_id}"` —
no tenant component. In a multi-tenant deployment, tenant A could replay an event with the
same UUID as tenant B and receive a false-positive dedup hit (fail-open, so no data loss, but
silent suppression).

**Verdict**: ACCEPT — platform is single-tenant for thesis scope. Existing `WARNING (multi-tenant)`
docstring in `dedup.py` is sufficient. Add tenant isolation when multi-tenant ADR is written.

---

### F-DS012 — Throughput spike docstring missing (MITIGATE — docstring addition)

**Root Cause**:
`ValkeyDedupMixin.is_duplicate()` fails open on `ConnectionError` — every message is processed
if Valkey is unavailable. This means a Valkey outage during a high-throughput burst can cause
100× throughput amplification downstream (all messages bypass dedup). This failure mode is
not documented in the code.

**Long-Term Fix**:
Add docstring paragraphs to `is_duplicate()` and `mark_processed()` documenting the fail-open
contract and counter names observers should alert on.

**File**: `libs/messaging/src/messaging/kafka/consumer/dedup.py`

---

### F-T004 — Prometheus counter test for is_duplicate ConnectionError (MITIGATE — add tests)

**Root Cause**:
`libs/messaging/tests/unit/kafka/consumer/test_dedup.py` tests that `is_duplicate` returns
False on `ConnectionError` (fail-open), but does NOT assert that `messaging_dedup_valkey_fallback_total`
is incremented. Similarly, `mark_processed` failure does not assert `messaging_dedup_mark_failed_total`
is incremented.

**Long-Term Fix**:
Add two tests:
1. `test_is_duplicate_connection_error_increments_fallback_counter`
2. `test_mark_processed_failure_increments_failed_counter`

Both use an `isolated_registry` fixture pattern from rag-chat conftest.

**File**: `libs/messaging/tests/unit/kafka/consumer/test_dedup.py`

---

### F-T007 — Space-separated date test for EU events (MITIGATE — add test)

**Root Cause**:
`services/knowledge-graph/src/knowledge_graph/infrastructure/consumers/economic_events_dataset_consumer.py`
calls `_parse_event_date(date_str)` which normalizes `"T"` separator. But EU-locale date strings
from some EODHD endpoints use a space separator: `"2026-04-30 12:15:00"`. The space-separated
format is handled by: `date_str.replace(" ", "T")`. This logic exists in production but has no
test coverage.

**Long-Term Fix**:
Add parametrized test case `_parse_event_date("2026-04-30 12:15:00")` → `date(2026, 4, 30)`.

**File**: `services/knowledge-graph/tests/unit/infrastructure/consumers/test_economic_events_dataset_consumer.py`

---

### F-T008 — _background_refresh error path test (MITIGATE — add test)

**Root Cause**:
`services/rag-chat/src/rag_chat/infrastructure/middleware/internal_jwt.py` has a
`_background_refresh()` coroutine that fetches the JWKS key on a schedule. The error path
(`httpx.HTTPStatusError`, `httpx.RequestError`) logs and retains the old key — but this
behavior has no test coverage. A regression (e.g., accidentally re-raising the exception and
crashing the background task) would be undetected.

**Long-Term Fix**:
Add `test_background_refresh_retains_old_key_on_http_error` — mock `httpx.AsyncClient.get`
to raise `httpx.HTTPStatusError`, assert the middleware's `_public_key` remains unchanged and
no exception propagates.

**File**: `services/rag-chat/tests/unit/api/test_internal_jwt_middleware.py`

---

## 3. Action Classification

| Finding | Verdict | Action |
|---------|---------|--------|
| F-DS005 | MITIGATE | Fix ZADD member uniqueness in circuit_breaker_cache.py |
| F-S001  | MITIGATE | Unify external 401 message; add structlog for internal |
| F-S004  | MITIGATE | Add `rag_jti_check_bypass_total` counter + test |
| F-DS002 | ACCEPT   | Confirmed safe; add regression test |
| F-S008  | ACCEPT   | Single-tenant; docstring sufficient |
| F-DS012 | MITIGATE | Add fail-open docstrings to is_duplicate + mark_processed |
| F-T004  | MITIGATE | Add Prometheus counter tests in test_dedup.py |
| F-T007  | MITIGATE | Add space-separated date parametrized test |
| F-T008  | MITIGATE | Add _background_refresh error path test |

---

## 4. New Bug Patterns

**BP-426** — ZADD member = timestamp: sub-second failures coalesce when timestamp resolution
is insufficient (clock granularity exceeds event rate). Fix: append random suffix to ZADD member.
Affects any circuit breaker or rate limiter implemented via Valkey ZSET.
