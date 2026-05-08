# Investigation Report: PLAN-0084 QA Wave 6 Open Items

**Date**: 2026-05-07
**Investigator**: Claude (`/investigate` skill, 3 parallel agents)
**Source QA report**: `docs/audits/2026-05-07-qa-plan-0084-wave6-report.md`
**Status**: Root cause identified for all open items; implementation-ready

---

## Scope

This report covers every open finding from the PLAN-0084 Wave 6 QA pass that was not auto-fixed
in session. The findings break into four severity tiers:

| Tier | Count | IDs |
|------|-------|-----|
| **CRITICAL** | 4 | C-1, C-2, C-3, DS-002 |
| **MAJOR** | 9 | DS-001, DS-003, DS-004, DS-011, QA-003, QA-007, QA-008, SEC-004, SEC-005 |
| **MINOR** | 5 | QA-001, QA-009, QA-013, DP-003, DP-007 |
| **NIT** | 2 | ARCH-001, ARCH-002 |
| **Testing layer** | 11 | TI-1 through TI-11 |

New bug patterns: **BP-421 through BP-425**.
New high-risk patterns: **HR-050 through HR-052**.

---

## CRITICAL Issues

---

### C-1: 7 Hand-Rolled KG Consumers Lack Valkey Fail-Open Error Handling

**Root Cause**

Three KG consumers (`EconomicEventsDatasetConsumer`, `EarningsCalendarDatasetConsumer`,
`MacroIndicatorDatasetConsumer`) define `is_duplicate()` and `mark_processed()` as direct
pass-throughs to `self._dedup_client.exists()` / `self._dedup_client.set()` with **no try/except
block**. When Valkey is unreachable these calls raise `ConnectionError`, which propagates through
`_handle_message()` → `_handle_failure()` in base.py.

Locations:
- `services/knowledge-graph/…/consumers/economic_events_dataset_consumer.py:410-423`
- `services/knowledge-graph/…/consumers/earnings_calendar_dataset_consumer.py:491-503`
- `services/knowledge-graph/…/consumers/macro_indicator_dataset_consumer.py:356-369`

**Impact**

- All three consumers stall or enter retry hell during any Valkey outage.
- If `mark_processed()` fails after the DB commit has already succeeded, the consumer receives
  `_handle_failure()` for a message that was fully processed — producing a duplicate on the
  next retry (natural key upserts absorb this, but it adds DB load and confuses metrics).
- KG service stops ingesting macro-economic / earnings data for the duration of the outage.

**Long-Term Solution**

Migrate all three (and the four other allowlisted consumers) to `ValkeyDedupMixin`, which
wraps every Valkey call in try/except and provides a fail-open contract: `is_duplicate()` returns
`False` on error (safe, at-least-once), `mark_processed()` swallows the exception with a warning.
Class-level `_dedup_prefix` constant is required; allowlist entry for the three consumer classes
already exists in `tests/architecture/_consumer_dedup_allowlist.yaml` and should be removed after
migration.

```python
# Before
class EconomicEventsDatasetConsumer(BaseKafkaConsumer[None]):
    async def is_duplicate(self, event_id: str) -> bool:
        key = f"{self._dedup_prefix}:{event_id}"
        return bool(await self._dedup_client.exists(key))  # ← no error handling

# After
from messaging.kafka.consumer.dedup import ValkeyDedupMixin

class EconomicEventsDatasetConsumer(ValkeyDedupMixin, BaseKafkaConsumer[None]):
    _dedup_prefix: str = "kg:dedup:economic_events_dataset_consumer"
    # is_duplicate / mark_processed inherited from mixin — fail-open contract
```

**New bug pattern**: BP-421 (see §New Bug Patterns).

**Testing Layer Improvement**
- Integration test: mock `dedup_client.exists()` to raise `ConnectionError`; verify the consumer
  does NOT crash and the Kafka offset is NOT committed; verify `dedup.valkey_check_failed` warning.
- Architecture test: extend `test_consumer_dedup_mixin_enforcement.py` with an allowlist audit
  that verifies every allowlisted consumer has inline documentation explaining why it's exempt.

---

### C-2: Canonical Tickers MULTI/EXEC Partial Failure Wipes Cache

**Root Cause**

`CanonicalTickersCache.refresh()` (nlp-pipeline:
`infrastructure/cache/canonical_tickers_cache.py:264-278`) uses a Redis MULTI/EXEC pipeline:

```python
async with self._client.pipeline(transaction=True) as pipe:
    pipe.delete(self._key)
    pipe.sadd(self._key, *normalised)
    await pipe.execute()   # ← network drop here leaves key empty
```

Redis MULTI/EXEC is atomic **on the server** once EXEC is processed. But if the network drops
after the server queues DEL but before EXEC is delivered, the client raises `ConnectionError`,
`self._key` is wiped, and the `except` block logs a warning and returns 0 without restoring
the old data.

**Impact**

- `nlp:v1:canonical_tickers` SET is empty until the next successful refresh (10-min interval).
- All calls to `is_known_ticker()` return `False` (the exception-handling safe default) during
  that window, so the W5 rare-token analyzer degrades to 0% recall on real tickers.
- Entity linking marks legitimate tickers (`AAPL`, `MSFT`) as suspicious; mention counts drop.

**Long-Term Solution**

Replace MULTI/EXEC with a Lua script invoked via `ValkeyClient.execute_lua_script()` (already
available — used by the circuit breaker). Lua scripts execute atomically on the Valkey server
with no partial-failure window:

```python
_ATOMIC_TICKER_SWAP = """
redis.call('DEL', KEYS[1])
if #ARGV > 0 then
    redis.call('SADD', KEYS[1], unpack(ARGV))
end
return redis.call('SCARD', KEYS[1])
"""

async def refresh(self) -> int:
    ...
    try:
        count = await self._client.execute_lua_script(
            _ATOMIC_TICKER_SWAP,
            keys=[self._key],
            args=list(normalised),
        )
        ...
```

**New bug pattern**: related to BP-407 (Redis atomic swap) and BP-413 (circuit breaker probe);
see BP-422 below.

**Testing Layer Improvement**
- Unit test: mock pipeline to simulate connection drop after DEL; verify `is_known_ticker("AAPL")`
  still returns the old result (old data not wiped) after the exception is caught.

---

### C-3: No Exponential Backoff in Canonical Tickers Refresh Loop

**Root Cause**

`CanonicalTickersCache._refresh_loop()` (nlp-pipeline:
`infrastructure/cache/canonical_tickers_cache.py:169-199`) uses a **fixed 60-second sleep** on
any exception:

```python
except Exception:
    log.warning("canonical_tickers.refresh_loop_error", exc_info=True)
    await asyncio.sleep(60)   # ← fixed, not exponential
```

During a 2-hour Valkey outage this emits 120 consecutive warning tracebacks (every 60 s) with no
indication to operators that the loop is stuck. There is no Prometheus counter for consecutive
failures, and no circuit-breaker to stop hammering Valkey.

**Impact**

- Log spam: ~20 KB of traceback per outage.
- The signal "canonical_tickers is broken" drowns in noise.
- No alerting surface: operators cannot set a metric-threshold alert on this condition.

**Long-Term Solution**

Exponential backoff with ceiling (2^n × 60 s, max 300 s) plus a Prometheus counter:

```python
async def _refresh_loop(self) -> None:
    consecutive_failures = 0
    while True:
        try:
            await asyncio.sleep(self._refresh_interval_s)
            await self.refresh()
            consecutive_failures = 0
        except asyncio.CancelledError:
            raise
        except Exception:
            consecutive_failures += 1
            _REFRESH_FAILURE_COUNTER.inc()
            backoff = min(2 ** consecutive_failures * 60, 300)
            log.warning(
                "canonical_tickers.refresh_loop_error",
                exc_info=True,
                consecutive_failures=consecutive_failures,
                backoff_s=backoff,
            )
            await asyncio.sleep(backoff)
```

**New bug pattern**: see BP-423 below.

---

### DS-002: TOCTOU Race in ValkeyDedupMixin (At-Least-Once by Design)

**Root Cause**

`ValkeyDedupMixin` implements dedup as two separate async calls:

```python
# base.py:427
if await self.is_duplicate(event_id):   # ← T1: EXISTS check
    return
# ... process message, commit DB ...
await self.mark_processed(event_id)     # ← T2: SET
```

Between T1 and T2, another consumer instance processing the same message can also observe
"not yet processed" at T1 and proceed to process. The mixin's docstring documents this as
"at-least-once" semantics, requiring idempotent downstream writes.

**When it manifests**: Consumer group with N≥2 replicas + Kafka partition rebalance during
message processing (rolling deployments, consumer pod restarts).

**Impact**

- No data corruption when downstream writes use natural-key upserts (ON CONFLICT DO UPDATE/NOTHING).
- Redundant processing: both replicas compute the same upserts; minor CPU waste.
- Prometheus counters incremented twice per duplicate (metrics inflation).
- If a consumer's downstream write is NOT idempotent (bare INSERT), the second replica gets a PK
  violation → message goes to DLQ.

**Long-Term Solution**

Replace the two-step check/mark with an atomic Lua script that does SET NX + returns whether the
key already existed:

```python
_ATOMIC_DEDUP_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 1 then return 1 end
redis.call('SET', KEYS[1], '1', 'EX', ARGV[1])
return 0
"""

async def is_and_mark_duplicate(self, event_id: str) -> bool:
    """Atomic check+mark. Returns True if already processed."""
    ...
```

This is a non-trivial change to `BaseKafkaConsumer.base` (the call site) and should be tracked
as PLAN-0085. Until then, the at-least-once guarantee is acceptable because all consumers use
upserts.

**Testing Layer Improvement**
- Concurrency test: 10 coroutines process the same event_id simultaneously; verify ≤1 actually
  proceeds to `process_message` (requires real Valkey or fakeredis, not a mock).

---

## MAJOR Issues

---

### DS-001: SETNX Probe Starvation After Failed Probe

**Root Cause** (`services/rag-chat/…/circuit_breaker.py:112-116`)

When the circuit breaker transitions to HALF_OPEN, one caller wins the SETNX probe slot with a
5-second TTL. If that caller crashes or times out before calling `record_success()` or
`record_failure()`, all other callers see `set_nx` return `False` (slot taken) and return
`True` (service appears OPEN) for the full 5-second probe TTL. No new probes are admitted
during the blocked window.

**Impact**: ~5-second "false positive hold" after a probe crash. Rare in practice but
observable in high-latency environments.

**Long-Term Solution**: Lower probe TTL to 2–3 seconds (configurable via `cb_probe_ttl_seconds`
which already exists in `Settings`). Add an observability log when a probe slot is NOT won
so operators can tune `upstream_timeout_seconds`. No code change required for the immediate
fix — the setting is already in place; documentation and alert tuning are the action items.

---

### DS-003: Citation Cron First-Run Failure Only at WARNING Level

**Root Cause** (`services/rag-chat/…/citation_accuracy_cron.py:44-48`)

```python
except Exception as exc:
    log.warning("citation_accuracy_cron_first_run_failed", error=str(exc))
```

A first-run failure (empty message table, cold DB, etc.) logs at WARNING with no Prometheus
counter. The cron then sleeps 7 days before the next attempt. This 7-day stale window has no
alerting surface.

**Long-Term Solution**

1. Change to `log.error(...)` (not `.warning`) — operators filter dashboards by ERROR+.
2. Add `_CITATION_CRON_FAIL_COUNTER.inc()` Prometheus counter.
3. Set a `citation_cron_last_success_timestamp` gauge so staleness alerting can be configured
   as `now() - last_success > 8 days → alert`.

---

### DS-004: Citation Cron CancelledError Not Caught on Graceful Shutdown

**Root Cause** (`services/rag-chat/…/citation_accuracy_cron.py:44-48`)

The inner exception handler catches `Exception` but not `BaseException`. When
`_cron_task.cancel()` fires during lifespan shutdown while `use_case.execute()` is running,
`asyncio.CancelledError` propagates uncaught through the exception handler and out of the
`while True` loop, potentially leaving DB sessions open depending on whether the use case's
context managers handle cancellation.

**Long-Term Solution**

```python
except asyncio.CancelledError:
    log.info("citation_accuracy_cron_shutdown_gracefully")
    raise  # allow the task to complete cleanly
except Exception as exc:
    ...
```

`use_case.execute()` already wraps sessions in try/finally so the risk of a leaked connection
is low, but the explicit catch eliminates the ambiguity.

---

### DS-011: ZSET Not Reset on record_success() — Quick Re-Trip Possible

**Root Cause** (`services/rag-chat/…/circuit_breaker.py:140-165`)

`record_success()` deletes the `_state_key` and `_probe_key` but intentionally leaves the
failures ZSET intact (documented: "The failures ZSET is NOT deleted — it expires naturally via
its TTL"). This means 2 old failures in the ZSET + 1 new failure immediately after recovery
= 3 failures = threshold crossed = breaker re-opens.

**Assessment**: This is **intentional design** (DS-011 comment). The trade-off is documented.
The risk is acceptable because: (a) failure_threshold=3 is configurable, (b) the failure_window
is 120 s — old failures age out quickly after recovery. **No code change recommended.**

**Action**: Document the "sticky ZSET" behaviour in the class-level docstring so future
maintainers understand why ZSET is not cleared and don't remove the behaviour.

---

### QA-003: Disabled-Cron Test Guard Prevents the Code Under Test From Running

**Root Cause** (`services/rag-chat/tests/unit/test_app_lifespan_citation_cron.py:75-99`)

```python
with patch("…start_citation_accuracy_cron") as mock_start:
    if settings.citation_cron_enabled:   # ← False → _wire_citation_cron never called
        _wire_citation_cron(app, settings, read_factory, log)
    mock_start.assert_not_called()       # ← trivially True
```

The test is supposed to verify the lifespan code path rejects an enabled-but-disabled cron,
but the guard condition prevents `_wire_citation_cron` from ever running. The test passes
vacuously and catches no regression.

**Long-Term Solution**

Test the actual wiring function directly without the guard:

```python
def test_wire_citation_cron_disabled_does_not_start() -> None:
    settings = _make_settings(citation_cron_enabled=False)
    with patch("…start_citation_accuracy_cron") as mock_start:
        _wire_citation_cron(app, settings, read_factory, log)   # ← no guard
        mock_start.assert_not_called()
```

**New bug pattern**: BP-424 (see §New Bug Patterns).

---

### QA-007: ON CONFLICT DO NOTHING Assertion Checks Private Attribute, Not SQL Text

**Root Cause** (`services/nlp-pipeline/tests/unit/…/test_outbox_repo.py:39-51`)

```python
assert stmt._post_values_clause is not None   # ← checks presence, not content
```

`_post_values_clause` can be set by `RETURNING`, `ON CONFLICT DO UPDATE`, or `ON CONFLICT DO
NOTHING` — a `RETURNING` clause passes the test trivially.

**Long-Term Solution**

Compile the statement and assert the SQL text:

```python
from sqlalchemy.dialects import postgresql
compiled = stmt.compile(dialect=postgresql.dialect())
sql_text = str(compiled)
assert "ON CONFLICT" in sql_text
assert "DO NOTHING" in sql_text
```

The same pattern applies to `test_entity_mention_repo.py`.

---

### QA-008: Prometheus REGISTRY Global State Pollutes Circuit Breaker Tests

**Root Cause** (`services/rag-chat/tests/unit/application/test_circuit_breaker.py:328-371`)

Tests use unique `source_name` labels as a workaround (BP-404), but the global `REGISTRY`
accumulates label combinations across the test session. In parallel test runs (pytest -n),
two tests registering different sources simultaneously can race on the collector map.

**Long-Term Solution**

Add an `isolated_registry` fixture to `services/rag-chat/tests/unit/conftest.py`:

```python
@pytest.fixture
def isolated_registry(monkeypatch):
    from prometheus_client import CollectorRegistry
    import prometheus_client
    registry = CollectorRegistry()
    monkeypatch.setattr(prometheus_client, "REGISTRY", registry)
    return registry
```

Tests that assert on gauge values should accept `isolated_registry` as a fixture and
read from it instead of the global `REGISTRY`.

**New bug pattern**: BP-425 (see §New Bug Patterns).

---

### SEC-004: APP_ENV="" Bypasses skip_verification Guard

**Root Cause** (`services/rag-chat/src/rag_chat/config.py:151-171`)

The guard only blocks `skip_verification=True` when `APP_ENV` is in
`{"production", "prod", "staging", "stage"}`. An empty or absent `APP_ENV` (common in
bare Docker deployments without explicit env setup) bypasses the check.

**Risk Assessment**: Medium. In practice, every properly-configured deployment sets
`APP_ENV=production`. The risk is limited to misconfigured deployments that also explicitly
set `INTERNAL_JWT_SKIP_VERIFICATION=true`.

**Recommended Decision** (requires user confirmation before code change):

Option A (Restrictive): require `APP_ENV` to be set when `skip_verification=True`; reject
empty `APP_ENV`.

Option B (Allow local dev): document that `APP_ENV=""` is a valid local-dev state; add a
LOUD WARNING log when `skip_verification=True` and `APP_ENV` is empty or unknown (not an error,
just a visual guard in stdout).

**Recommendation**: Option B — developers use `APP_ENV=""` for local eval frequently; a startup
error would break their workflow. A LOUD log is the right balance.

---

### SEC-005: Malformed JWT in skip_verification Mode Passes Through with Empty Claims

**Root Cause** (`services/rag-chat/…/internal_jwt.py:181-198`)

When `skip_verification=True` and the JWT is malformed:
1. `jwt.decode(token, options={"verify_signature": False})` raises `DecodeError`.
2. The except block sets `tenant_id = ""`, `user_id = ""`, `role = ""`.
3. The request is passed through to the route handler.

**Impact**: A route handler that does not defensively check `tenant_id != ""` might default
to a system tenant or skip authorization. Affected only in skip_verification mode (local dev
/ eval harness only).

**Long-Term Solution**

Return 401 on malformed JWT even in skip_verification mode:

```python
except jwt.DecodeError as exc:
    log.warning("internal_jwt_malformed_skip_verification", error=str(exc))
    return Response(
        content='{"detail":"Malformed JWT"}',
        status_code=401,
        media_type="application/json",
    )
```

Additionally, validate `tenant_id != ""` even when skip_verification succeeds.

---

## MINOR Issues

---

### QA-001: Per-Function @pytest.mark.unit Instead of Module-Level pytestmark

**Root Cause**: Inconsistency between test files — some use `pytestmark = pytest.mark.unit`
at module level, others use `@pytest.mark.unit` per function. Both work but the per-function
form is redundant and can cause selection issues with `pytest -m unit --collect-only`.

**Fix**: Standardize to module-level `pytestmark`. Add architecture test `TI-8` to enforce.

---

### QA-009: `_next_sunday_03_utc()` Has No Dedicated Unit Tests

**Root Cause** (`services/rag-chat/…/citation_accuracy_cron.py:25-38`)

The function has three conditional branches (before Sunday, same-day before 03:00, same-day
at or after 03:00) tested only via integration tests of the cron loop. An off-by-one on
DST or week rollover would silently shift the cron run by 7 days.

**Fix**: Add parametrized unit tests covering all 6 boundary cases (see TI-2 in §Testing Layer).

---

### QA-013: JWT Skip-Path Tests Cover Only `/healthz`

**Root Cause** (`services/rag-chat/tests/unit/api/test_internal_jwt_middleware.py`)

`_SKIP_PATHS` has 5 entries; `_SKIP_PREFIXES` has 3 prefixes. The existing test only checks
`/healthz`. A typo in the other 7 paths would go undetected.

**Fix**: Parametrize the test with all 8 paths (see TI-3 in §Testing Layer).

---

### DP-003: QuotesConsumer Has Dedup Attributes But No-Op Methods

**Root Cause** (`services/market-data/…/quotes_consumer.py:61-121`)

The consumer defines `_dedup_prefix` and `_dedup_ttl_seconds` but overrides `is_duplicate()`
and `mark_processed()` with no-ops. A developer copying this class as a template might assume
dedup is active when it is not.

**Fix**: Add a class-level docstring comment: `# Dedup strategy: DB atomic (INSERT … ON CONFLICT DO NOTHING per BP-035). ValkeyDedupMixin intentionally NOT used.` Remove `_dedup_prefix` and `_dedup_ttl_seconds` (unused, misleading).

---

### DP-007: ValkeyClient.set() Accepts Both `ttl` and `ex` Parameters

**Root Cause** (`libs/messaging/src/messaging/valkey/client.py:142-149`)

Both `ttl` and `ex` are accepted; `ex` takes priority. Two names for the same concept
creates silent semantic bugs when both are passed.

**Fix**: Deprecate `ttl`; use only the Redis-native `ex`. Add a test that documents the
priority rule (TI-7).

---

### ARCH-001 / ARCH-002: Service `.claude-context.md` Missing New Ports

**Root Cause**: Context files are updated manually post-code-review. After PLAN-0084 Wave D,
the new `ChunkSearchPort` and `CanonicalEntityPort` modules are not referenced in
`services/nlp-pipeline/.claude-context.md`.

**Fix**: Update `.claude-context.md` files (action for PLAN-0085 Wave 1). Long-term: add CI
gate TI-6 to detect drift between documented endpoints and actual code.

---

## Testing Layer Improvements

The following 11 improvements are recommended for PLAN-0085 or as standalone tasks. Each
is mapped to the issue(s) it would have caught.

| ID | Improvement | Catches |
|----|-------------|---------|
| TI-1 | Architecture test: enumerate consumer dedup strategies; require documented allowlist entries with inline class comment | C-1, DP-003 |
| TI-2 | Parametrized unit tests for `_next_sunday_03_utc()` — 6 boundary cases | QA-009 |
| TI-3 | Parametrize JWT skip-path tests across all 8 configured paths | QA-013 |
| TI-4 | Pipeline partial-failure injection tests for MULTI/EXEC and Lua scripts | C-2 |
| TI-5 | Exponential backoff test: mock `asyncio.sleep`, verify durations follow 2^n×60 with max 300 s | C-3 |
| TI-6 | CI gate: extract HTTP endpoints from `.claude-context.md`, verify presence in service code | ARCH-001/002 |
| TI-7 | ValkeyClient.set() parameter priority test: document `ex` wins over `ttl`; deprecate `ttl` | DP-007 |
| TI-8 | Architecture test: scan all `tests/unit/**/*.py` via AST, assert module-level `pytestmark` (no per-function markers) | QA-001 |
| TI-9 | Property-based concurrent dedup test (Hypothesis): N coroutines process same event_id, verify only one proceeds | DS-002 |
| TI-10 | `isolated_registry` pytest fixture in conftest; all Prometheus metric tests use it | QA-008 |
| TI-11 | Integration test: INSERT ON CONFLICT DO NOTHING — first insert rowcount=1, second rowcount=0; compile SQL to assert text | QA-007 |

---

## Implementation Priority

### PLAN-0085 Wave 1 — Critical Fixes (block before next QA pass)

1. Migrate 3 remaining KG consumers (`EconomicEventsDatasetConsumer`,
   `EarningsCalendarDatasetConsumer`, `MacroIndicatorDatasetConsumer`) to `ValkeyDedupMixin`.
   Update allowlist entries accordingly.
2. Replace canonical tickers MULTI/EXEC with Lua atomic swap (C-2).
3. Add exponential backoff to `_refresh_loop()` (C-3).
4. Fix `test_lifespan_disabled_does_not_call_start_citation_accuracy_cron` — remove trivial
   guard (QA-003).
5. Strengthen ON CONFLICT assertions in `test_outbox_repo.py` and `test_entity_mention_repo.py`
   to check compiled SQL text (QA-007).

### PLAN-0085 Wave 2 — Major Fixes

6. Catch `asyncio.CancelledError` in citation cron (DS-004).
7. Log citation cron first-run failure at ERROR level + add Prometheus counter (DS-003).
8. Return 401 on malformed JWT in skip_verification mode (SEC-005).
9. Add `isolated_registry` fixture + update circuit breaker tests (QA-008).

### PLAN-0085 Wave 3 — Minor / Testing Layer

10. Update `.claude-context.md` files for nlp-pipeline and rag-chat (ARCH-001/002).
11. Add `_next_sunday_03_utc()` unit tests (QA-009).
12. Parametrize JWT skip-path tests (QA-013).
13. Add module-level `pytestmark` architecture test (TI-8).
14. Document ZSET sticky behaviour in circuit breaker docstring (DS-011).

### Deferred / Requires Decision

- **SEC-004** (APP_ENV guard): Decision needed on Option A vs Option B (see §Major Issues).
- **DS-002** (TOCTOU atomic dedup): Significant base.py refactor; acceptable as-is while all
  consumers use natural-key upserts; track in PLAN-0086+.

---

## New Bug Patterns

### BP-421: Hand-Rolled Dedup Methods Without Fail-Open Valkey Error Handling

**Summary**: `BaseKafkaConsumer` subclasses that implement `is_duplicate()` / `mark_processed()`
by calling `self._dedup_client.exists()` / `.set()` without try/except crash the consumer on
any Valkey outage. The mixin already handles this via fail-open semantics.

**Detection**: Any `is_duplicate` override in a consumer that calls `_dedup_client.*` without a
try/except block is suspect. Enforcement: architecture test `test_consumer_dedup_mixin_enforcement.py`.

**Fix**: Use `ValkeyDedupMixin`. See §C-1 for migration pattern.

**Category**: Kafka & Messaging

---

### BP-422: Redis MULTI/EXEC Partial Failure Wipes a Cache Key

**Summary**: A cache refresh that uses MULTI/EXEC (DEL + SADD) can wipe the cache key if the
network drops between server-side DEL and client-side EXEC. Result: empty cache until next
successful refresh. Fix: use a Lua script via `EVAL` for atomic cache swap. Pattern is the
same as BP-407 (Lua for threshold counters); BP-422 covers cache-key replacement.

**Detection**: Any `pipeline(transaction=True)` block that issues a DEL followed by a bulk
write to the same key is suspect.

**Category**: Architecture / Cache

---

### BP-423: Fixed Retry Interval in Background Loop Causes Log Spam and Operator Blindness

**Summary**: A background loop that uses `await asyncio.sleep(N)` on every exception (fixed
N) produces O(duration/N) identical log lines during a sustained outage. Operators cannot
distinguish a brief transient from a multi-hour outage. Fix: exponential backoff with a
ceiling (e.g., min(2^failures × 60, 300)) and a Prometheus counter for consecutive failures.

**Detection**: Any `except Exception: log.warning(...); await asyncio.sleep(FIXED_CONSTANT)`
in a `while True` loop is a BP-423 candidate.

**Category**: Architecture / Observability

---

### BP-424: Disabled-Feature Test Guard Prevents the Code Under Test From Running

**Summary**: A test patches a function, then wraps the call to the function under test in
`if settings.<feature_flag>:`. With the flag disabled, the function is never called and
`mock.assert_not_called()` trivially passes — the test provides zero coverage of the flag
evaluation logic. Fix: call the function under test unconditionally; let the function
decide its own behavior based on settings.

**Detection**: `mock_x.assert_not_called()` in a test that also has `if settings.X:` guarding
the function call that would invoke `mock_x`.

**Category**: Testing

---

### BP-425: Prometheus REGISTRY Global State Leaks Between Unit Tests

**Summary**: `prometheus_client.REGISTRY` is a process-wide singleton. Tests that register
metrics with the same `labels()` in the same session pollute each other's label state. Parallel
test runs (pytest -n) can race on the collector map. Fix: use an `isolated_registry` fixture
that monkeypatches `prometheus_client.REGISTRY` per test.

**Detection**: Any test that calls `for m in REGISTRY.collect()` without an `isolated_registry`
fixture is a BP-425 candidate. Related: BP-404 (MetricFamily name stripping).

**Category**: Testing

---

## New High-Risk Patterns (HR)

### HR-050: Consumer Class With Hand-Rolled Dedup and No try/except on Valkey Calls

Any `BaseKafkaConsumer` subclass that:
1. Defines `is_duplicate()` or `mark_processed()`, AND
2. Calls `self._dedup_client.exists()` or `.set()` inside those methods, AND
3. Does NOT wrap the call in `try/except`

is a **RED risk signal** for consumer stalls on Valkey outages.

**Automatic check**: Architecture test `CONSUMER-DEDUP-001` catches classes that don't
use `ValkeyDedupMixin`. For allowlisted classes, manually verify the hand-rolled methods
have try/except wrapping.

---

### HR-051: Redis Pipeline MULTI/EXEC Where DEL + Bulk-Write Operate on the Same Key

Any `pipeline(transaction=True)` block that issues:
1. `DELETE key`, then
2. `SADD key *values` or `HSET key …`

to the **same key** is suspect for partial-failure cache wipe. Use a Lua script instead.

**Automatic check**: grep for `pipe.delete` followed by `pipe.sadd` or `pipe.hset` within the
same `async with pipeline` block.

---

### HR-052: Background `while True` Loop With Fixed `asyncio.sleep` on Exception

Any `while True` loop containing:

```python
except Exception:
    await asyncio.sleep(FIXED_N)
```

without backoff state is a BP-423 candidate. **YELLOW risk signal** — acceptable for short
outages but causes log spam and operator blindness for sustained failures.

**Automatic check**: grep for `asyncio.sleep` inside an `except` block inside a `while True`
loop in any `_*_loop` or `_run_*` method.

---

## Compounding Actions (Mandatory)

| Document | Update | Reason |
|----------|--------|--------|
| `docs/BUG_PATTERNS.md` | Add BP-421..BP-425 | New failure patterns discovered |
| `.claude/review/heuristics/HIGH_RISK_PATTERNS.md` | Add HR-050..HR-052 | New detection rules |
| `docs/STANDARDS.md` | Add §20 Testing Layer Rules (TI-20.1..TI-20.10) | 11 testing principles formalized |
| `.claude/review/checklists/REVIEW_CHECKLIST.md` | Add dedup-mixin check + ON CONFLICT SQL-text check + MULTI/EXEC Lua check | New review checks |
| `services/nlp-pipeline/.claude-context.md` | Add ChunkSearchPort and CanonicalEntityPort module paths | ARCH-001 |
| `services/rag-chat/.claude-context.md` | Add citation cron wiring notes, CB probe TTL config | ARCH-002 |

---

## Open Questions

1. **SEC-004**: Should `APP_ENV=""` be rejected when `skip_verification=True` (breaks local eval)
   or produce a LOUD WARNING (allows local dev but visible)? Awaiting user decision.

2. **DS-002 (TOCTOU)**: Atomic Lua check+mark in `ValkeyDedupMixin` requires touching
   `BaseKafkaConsumer.base` — a cross-cutting change. Should this be PLAN-0085 Wave 1 or
   deferred to PLAN-0086 given all consumers currently use idempotent upserts?

3. **C-1 Allowlist**: After migrating the 3 remaining consumers, the allowlist still has 4
   entries (DB-atomic pattern). Should those be left as-is, or should Wave 3 consolidate them
   into a standard `DbAtomicDedupMixin` for documentation clarity?
