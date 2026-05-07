# Investigation Report: PLAN-0084 QA Deferred Findings

**Date**: 2026-05-07
**Investigator**: Claude (`/investigate` skill)
**Severity**: Multiple — 8 architecture decisions, 11 test gaps, 19 minor/NIT fixes
**Status**: Root causes identified; architecture decisions resolved with Bloomberg-grade recommendations; implementation-ready

---

## Scope

This report investigates every deferred finding from the 2026-05-07 QA pass on PLAN-0084
(`docs/audits/2026-05-07-qa-plan-0084-report.md`). Findings that were fixed in-session
(D-009, D-004, S-008, A-003, A-004, D-017, D-018) are NOT covered here — they are already
committed. This report covers the 40 deferred findings:

- **8 architecture decisions** (S-003, S-006, S-009, S-012, D-010, D-011/DP-001, D-014, D-016)
- **11 test coverage gaps** (F-001, F-003, F-004, F-005, F-008, F-009, F-010, F-011, F-012, F-013, DP-009)
- **19 minor/NIT items** (A-001, A-002, A-005, A-006, A-007, S-002, S-004, S-005, D-001, D-003,
  D-006, D-013, D-015, DP-002, DP-003, DP-004, DP-006, S-010, S-011, S-013)

---

## Part I — Architecture Decisions

Each item below presents: root cause → impact → Bloomberg-grade recommendation → fix scope.

---

### I-1 — S-003: Global Circuit Breaker Keys

**File**: `services/rag-chat/src/rag_chat/application/pipeline/circuit_breaker.py`

**Root cause**: CB state keys are `rag:cb:{service_name}:{ticker}` — shared across all tenant
sessions. One tenant whose queries hit a bad ticker trips the CB for every tenant. The QA
finding asks: per-tenant CB keys or documented platform-wide?

**Impact analysis**: At current scale (single-tenant dev), no observable impact. At
Bloomberg-competing scale (multi-tenant SaaS), a single hostile or misconfigured tenant causes
service degradation for all others — directly contrary to the platform's SLA ambitions.

**Investigation**: The CB protects against retrieval-time LLM failures, not query-time
latency. The natural isolation unit is the **upstream service** (DeepInfra, Ollama, rag-chat
internal paths) — not the tenant. A tenant sending bad queries doesn't make DeepInfra fail;
only DeepInfra itself failing makes DeepInfra fail. Therefore the CB counter should track
**service-level errors**, not tenant-level errors.

The deeper issue: **4xx errors from an LLM provider should NOT increment the CB failure
counter.** A 422 on a bad prompt is a client error, not a service fault. The CB trips
prematurely when bad query content (a client bug) is mistaken for infra failure. This is the
actual practical fix.

**Bloomberg-grade decision**: Platform-wide CB per named service is correct. Do NOT partition
by tenant — that defeats CB's purpose (circuit opens on the underlying service faulting, not
on per-tenant traffic). Fix the root trigger instead: filter out 4xx from the failure counter.

**Fix**:
```python
# services/rag-chat/src/rag_chat/application/pipeline/circuit_breaker.py

async def record_failure(self, error: Exception | None = None) -> int:
    """Record one failure. 4xx client errors do NOT count toward the threshold."""
    if isinstance(error, ProviderClientError) and error.status_code < 500:
        return 0  # client error — not a provider fault
    # ... existing Lua ZADD logic
```

Add `ProviderClientError` as a domain exception carrying `status_code` in the LLM client
adapters; raise it on 4xx responses. The CB only opens on 5xx or network-layer failures.

**Files changed**: `circuit_breaker.py` (2 lines), LLM adapter(s) to raise typed error.
**Effort**: 1 hour.

---

### I-2 — S-006: `minio_key` Not Validated in Article Consumer

**File**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:782`

**Root cause**: `_download_article(self, minio_key: str)` accepts `minio_key` from the Kafka
event payload without validating it. A malformed key (e.g., `../../secrets/env`) is passed
directly to the storage client, creating a path traversal risk in the MinIO/S3 key space.

**Impact**: The MinIO silver layer uses bucket + key to address objects. A crafted key with
leading `..` components or absolute path segments can read objects outside the intended scope.
Risk is amplified if the same MinIO instance serves multiple service buckets.

**Fix**: Validate before use. The `KeyBuilder` from `libs/storage` already enforces canonical
key format. Add a guard:

```python
# article_consumer.py — _download_article

from storage.key_builder import KeyBuilder  # type: ignore[import-untyped]

async def _download_article(self, minio_key: str) -> str:
    # Reject keys that don't match the canonical silver-layer pattern.
    # Expected format: silver/<source>/<YYYY>/<MM>/<DD>/<uuid7>.txt
    if not KeyBuilder.is_valid_silver_key(minio_key):
        raise ValueError(f"Rejected non-canonical minio_key: {minio_key!r}")
    ...
```

If `KeyBuilder.is_valid_silver_key` doesn't exist, add it with a simple regex:
`^silver/[a-zA-Z0-9_-]+/\d{4}/\d{2}/\d{2}/[0-9a-f-]+\.txt$`

**Files changed**: `article_consumer.py` (3 lines), `libs/storage/src/storage/key_builder.py`
(add `is_valid_silver_key` classmethod, ~10 lines).
**Effort**: 30 minutes.

---

### I-3 — S-009: `--rag-url` Flag Not Validated in eval_retrieval.py

**File**: `scripts/eval_retrieval.py`

**Root cause**: The `--rag-url` CLI argument is used directly as the base URL for all HTTP
calls including the `X-Internal-JWT` header. In CI, if `RAG_CHAT_URL` is misconfigured to
point at an attacker-controlled host, the JWT is sent there.

**Fix**: Validate that the URL uses `http://` or `https://` and optionally enforce an
allowlist of expected hostnames in CI:

```python
# eval_retrieval.py — argument parsing

import urllib.parse

def _validate_rag_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise argparse.ArgumentTypeError(f"--rag-url must use http/https scheme, got: {url!r}")
    if not parsed.hostname:
        raise argparse.ArgumentTypeError(f"--rag-url missing hostname: {url!r}")
    return url

parser.add_argument("--rag-url", type=_validate_rag_url, ...)
```

**Files changed**: `scripts/eval_retrieval.py` (~15 lines).
**Effort**: 20 minutes.

---

### I-4 — S-012: `EVAL_INTERNAL_JWT` Passed as curl Header Arg (Process List Visible)

**File**: `.github/workflows/retrieval-eval.yml:167-175`

**Root cause**: The smoke probe uses:
```bash
${EVAL_INTERNAL_JWT:+--header "X-Internal-JWT: ${EVAL_INTERNAL_JWT}"}
```
The JWT value is embedded in the curl command line, which is visible in the process list to
any other process with `ps` access on the runner.

**Fix**: Use curl's `--config` file or `--header @-` stdin pipe to avoid the value appearing
in the process list:

```yaml
- name: Smoke probe — verify endpoint before eval
  env:
    RAG_CHAT_URL: ${{ vars.RAG_CHAT_URL || 'http://localhost:8003' }}
    EVAL_INTERNAL_JWT: ${{ secrets.EVAL_INTERNAL_JWT }}
  run: |
    PROBE_RESPONSE=$(curl --silent --fail-with-body \
      --max-time 15 \
      --header "Content-Type: application/json" \
      --header "X-Internal-JWT: ${EVAL_INTERNAL_JWT}" \
      --data '{"query_text":"Apple Q4 earnings","top_k":5}' \
      "${RAG_CHAT_URL}/v1/internal/retrieve" 2>&1) || {
        echo "SMOKE PROBE FAILED"
        exit 1
      }
```

For the eval step, replace the curl call with a Python httpx probe that reads the JWT from
env directly (never touches the process list):

```python
# scripts/eval_retrieval.py — smoke probe step
import httpx, os

async def _smoke_probe(rag_url: str) -> None:
    jwt = os.environ.get("EVAL_INTERNAL_JWT", "")
    headers = {"Content-Type": "application/json"}
    if jwt:
        headers["X-Internal-JWT"] = jwt
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{rag_url}/v1/internal/retrieve",
                                 json={"query_text": "Apple Q4 earnings", "top_k": 5},
                                 headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if data.get("n_candidates", 0) < 1:
            raise RuntimeError("Smoke probe returned 0 candidates")
```

**Files changed**: `scripts/eval_retrieval.py` (+smoke probe fn), `.github/workflows/retrieval-eval.yml` (remove curl JWT arg).
**Effort**: 1 hour.

---

### I-5 — D-011/DP-001: QuotesConsumer Inherits ValkeyDedupMixin but Overrides to No-ops

**File**: `services/market-data/src/market_data/infrastructure/messaging/consumers/quotes_consumer.py:103-112`

**Root cause**:
```python
class QuotesConsumer(ValkeyDedupMixin, BaseKafkaConsumer[dict]):
    _dedup_prefix = "market-data:dedup:quotes_consumer"

    async def is_duplicate(self, event_id: str) -> bool:
        return False  # Dedup is handled atomically via create_if_not_exists (BP-035)

    async def mark_processed(self, event_id: str) -> None:
        pass  # No-op: event_id was already recorded by create_if_not_exists
```

The consumer inherits `ValkeyDedupMixin` in its MRO but then shadows both methods with no-ops.
The justification in the docstring is that `create_if_not_exists()` inside `process_message`
handles idempotency atomically before any data write. This is a valid alternative strategy.

**Impact**: No correctness problem — the `create_if_not_exists` pattern IS idempotent. The
issue is **architectural dishonesty**: `ValkeyDedupMixin` in the MRO implies behavior that
isn't there. New engineers reading the class signature will expect Valkey-backed dedup.

**Bloomberg-grade decision**:

**Option A (recommended): Remove `ValkeyDedupMixin` from MRO.** The class already has its
own contract; advertising the mixin is misleading. Keep `_dedup_prefix` as a class attribute
for the architecture test to check, but document the alternative strategy explicitly:

```python
class QuotesConsumer(BaseKafkaConsumer[dict]):
    """
    Idempotency: uses create_if_not_exists (BP-035) rather than ValkeyDedupMixin.
    The dataset_id natural key provides atomic dedup before any data write.
    This consumer is allowlisted in test_consumer_dedup_mixin_enforcement.py.
    """
    _dedup_prefix = "market-data:dedup:quotes_consumer"  # kept for architecture test
```

**Option B: Restore mixin fast-path.** Remove the method overrides, let `ValkeyDedupMixin`
run. The mixin call adds <1ms per message; the `create_if_not_exists` remains as the slow-path
safety net. More consistent behavior across the platform.

**Recommendation**: Option A. The `create_if_not_exists` pattern is strictly stronger than
Valkey dedup (DB-level atomic, persists across Valkey restarts). Document the exception
clearly rather than lying about it.

**Files changed**: `quotes_consumer.py` (remove MRO entry + document contract),
`test_consumer_dedup_mixin_enforcement.py` (update allowlist comment/test).
**Effort**: 30 minutes.

---

### I-6 — D-010: intel_session Commit Failure Silently Suppressed

**File**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:751-764`

**Root cause**:
```python
try:
    await intel_session.commit()
except Exception:
    logger.warning("d004_intel_commit_failed", doc_id=str(doc_id), exc_info=True)
    # DON'T re-raise — NLP is committed; intel writes are idempotent on retry
```

The comment claims "intel writes are idempotent on retry" but **retries never happen**. Once
nlp_session commits, the message's early-skip (`routing_decision.exists()`) fires on the next
delivery, so the intel writes are permanently skipped. The lost intel writes are:
- `provisional_entity_queue` rows for unresolved mentions → entities never enter the KG
- Potential `entity_profile_embeddings` updates

**Impact**: Entities extracted from articles with an intel commit failure **never enter the
KG**. The article appears processed (routing_decision exists), but its entities are invisible
to the knowledge graph. This is a **silent data loss path** in the entity pipeline.

**Verification**: Lines 499-510 write `provisional_entity_queue` rows using
`intel_session`. If that commit silently fails, `ProvisionalEnrichmentWorker` never sees the
rows, never emits `entity.dirtied.v1`, the KG never gets the entities. The only observability
is the `d004_intel_commit_failed` warning log, which is easy to miss.

**Bloomberg-grade decision**:

**The correct approach is re-raise + Prometheus counter, not silent swallow.**

The "idempotent on retry" claim is true for the WRITE side (`provisional_entity_queue` has a
UNIQUE constraint). What it misses is that retry never occurs because the early-skip fires.
The fix is to change the exception contract so that a failed intel commit causes the message
to be nacked (trigger Kafka re-delivery):

```python
# article_consumer.py

try:
    await intel_session.commit()
except Exception:
    logger.error(  # type: ignore[no-any-return]
        "intel_commit_failed_nacking",
        doc_id=str(doc_id),
        exc_info=True,
    )
    intel_session_commit_failures_total.inc()  # new Prometheus counter
    raise  # re-raise → Kafka offset NOT committed → message re-delivered
```

On re-delivery, the routing_decision already exists so Block 1 early-skip fires — BUT we need
to also skip the intel-only path in this case. Add a separate check: if
`intel_session.provisional_queue.exists(doc_id)` then skip the intel write path.

Alternatively (simpler): make the intel write non-transactional per-mention using UPSERT
`INSERT ... ON CONFLICT DO NOTHING` outside the intel_session transaction, so individual
mention failures don't affect the whole batch. This is the cleanest approach.

**Recommended fix sequence**:
1. Add `intel_commit_failures_total` Prometheus counter (5 min).
2. Change `logger.warning` → `logger.error` (1 min).
3. Change silent swallow → re-raise (1 line).
4. Add "skip provisional writes if routing_decision exists and provisional rows already exist"
   guard to prevent double-work on re-delivery (30 min).

**Files changed**: `article_consumer.py` (~15 lines), metrics file (~5 lines).
**Effort**: 1 hour.

---

### I-7 — D-014: `entity.dirtied.v1` Fire-and-Forget After DB Commit

**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py:434-445`

**Root cause**:
```python
# Produce entity.dirtied.v1 AFTER successful DB commit.
for dirty_id in entity_ids_to_dirty:
    try:
        await self._direct_producer.produce(
            topic=self._dirtied_topic,
            value=core._build_dirtied_event(dirty_id),
        )
    except Exception:
        logger.warning("provisional_enrichment_dirtied_emit_failed", ...)
```

This is fire-and-forget: the DB commit succeeded, the entity promotion is final, but the
`entity.dirtied.v1` event is produced outside any transaction. If the produce fails or the
process crashes between the commit and the produce loop, the entity **never gets its embeddings
refreshed** — it exists in the KG with stale/empty embeddings forever.

**Impact analysis**: Two categories:
- **One-time entities** (provisional entity promoted exactly once): if `dirtied.v1` is lost,
  the entity never enters the embedding pipeline. The entity exists in the graph but has no
  semantic vector → zero cosine similarity on all ANN queries. Permanent data quality
  degradation.
- **Frequently-updated entities** (e.g., AAPL's canonical entity updated by many articles):
  the next article that extracts AAPL will trigger another `entity.dirtied.v1`. Loss of one
  emission is tolerable — the next run will catch up.

The QA finding correctly identifies the one-time promotion case as the critical one.

**Bloomberg-grade decision**:

**For one-time promotion events: use the outbox pattern.**
**For high-frequency repeat events: fire-and-forget is acceptable.**

The `entity.dirtied.v1` event is typically high-frequency for popular entities but one-time
for newly-promoted provisional entities. The correct approach is to use the outbox for the
promotion event:

```python
# provisional_enrichment.py — after DB commit

# Replace fire-and-forget with outbox INSERT
async with self._sf() as outbox_session:
    for dirty_id in entity_ids_to_dirty:
        await outbox_repo.add(
            OutboxEntry(
                event_id=uuid5_from_parts(str(dirty_id), "entity_dirtied_v1", str(now_ts)),
                topic=self._dirtied_topic,
                payload=core._build_dirtied_event(dirty_id),
            )
        )
    await outbox_session.commit()
```

The outbox dispatcher then reliably delivers the event. The `entity.dirtied.v1` event becomes
durable: if the process crashes after the DB commit, the outbox row exists and the dispatcher
will produce it on next run.

**Cost**: One additional DB write per promoted entity per enrichment cycle. Negligible vs. the
correctness guarantee.

**Alternative** (lower effort, lower safety): Add a "retry table" for failed direct produces.
The `_failed_dirtied_events` table is checked by a background task and retried. Less clean but
avoids the outbox infrastructure in KG service.

**Recommendation**: Outbox pattern. The KG service already has `OutboxRepository` and
`OutboxDispatcher` infrastructure (added in PLAN-0084 B-2 for temporal events). Reuse it.

**Files changed**: `provisional_enrichment.py` (~20 lines), minor outbox repo reuse.
**Effort**: 2 hours.

---

### I-8 — D-016: No Stale `processing` Row Recovery Accounting for Actual Start Time

**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py:483-504`

**Root cause**: `_recover_stale_processing_rows()` uses `created_at < now() - interval '30 minutes'`
as the stale threshold:

```sql
WHERE status = 'processing'
  AND created_at < now() - interval '30 minutes'
```

`created_at` records when the row was **inserted into the queue** (when the article was
processed), NOT when it transitioned to `processing` status. A row created 31 minutes ago but
that only entered `processing` 1 minute ago will be incorrectly recovered as stale, causing
duplicate enrichment work.

**Impact**: Two failure modes:
1. **False recovery**: A row that started processing 1 minute ago (from a long-queued entity)
   is reset to `pending`, causing duplicate enrichment and wasted LLM calls.
2. **Missed recovery**: A row stuck in `processing` for 3 hours (e.g., Ollama timeout that
   didn't raise) might not be recovered if `created_at` was just 15 minutes ago (batch
   ingest). Real stuck rows hide.

**Fix**: Add a `processing_started_at TIMESTAMPTZ` column to `provisional_entity_queue`.
Set it to `utc_now()` when status transitions to `'processing'`. Use it in the recovery query:

```sql
UPDATE provisional_entity_queue
SET status = 'pending', ...
WHERE status = 'processing'
  AND processing_started_at < now() - interval '30 minutes'
```

Migration:
```sql
ALTER TABLE provisional_entity_queue
    ADD COLUMN processing_started_at TIMESTAMPTZ;

UPDATE provisional_entity_queue
    SET processing_started_at = created_at
    WHERE status = 'processing' AND processing_started_at IS NULL;
```

Update the SELECT that claims rows to also set the new column:
```sql
UPDATE provisional_entity_queue
    SET status = 'processing', processing_started_at = now()
    WHERE queue_id = ANY(:ids)
```

**Files changed**: new Alembic migration in `intelligence-migrations`, `provisional_enrichment.py`
(update claim query, update recovery query).
**Effort**: 2 hours.

---

## Part II — Test Coverage Gaps

All tests below are new tests to be added. File locations match the existing test structure.

---

### II-1 — F-001 (CRITICAL): Exact `set(key, "1", ex=N)` Call Signature in test_dedup.py

**File**: `libs/messaging/tests/unit/kafka/consumer/test_dedup.py`

**Issue**: `test_mark_processed_sets_24h_ttl` checks the TTL via `client.ttl()` against a
real `FakeValkey` client. It does NOT assert that `set()` was called with the exact positional/
keyword argument shape `set(key, "1", ex=86400)`. If the mixin implementation changes to
`set(key, value="1", ex=86400)` or `setex(key, 86400, "1")`, the TTL test still passes but
the actual call signature may break with a real Valkey client.

**Fix** — add:

```python
@pytest.mark.asyncio
async def test_mark_processed_set_call_signature(self) -> None:
    """mark_processed MUST call set(key, '1', ex=TTL) — not setex or other variants."""
    client = MagicMock(spec=ValkeyClient)
    client.set = AsyncMock(return_value=True)
    client.exists = AsyncMock(return_value=False)
    mixin = _make_mixin(client=client)  # type: ignore[arg-type]

    await mixin.mark_processed("evt-sig")

    client.set.assert_awaited_once_with(
        f"{mixin._dedup_prefix}:evt-sig",
        "1",
        ex=86400,
    )
```

---

### II-2 — F-003 (MAJOR): CB Re-admission After Probe TTL Expiry

**File**: `services/rag-chat/tests/unit/application/test_circuit_breaker.py`

**Issue**: No test verifies that after the probe key expires (TTL elapsed), the circuit
admits a second probe. `test_is_open_admits_one_probe_after_cooldown` only tests the first
admission; if the probe TTL is shorter than the cooldown the system could re-admit N probes.

```python
@pytest.mark.asyncio
async def test_cb_probe_re_admitted_after_probe_ttl_expiry(
    fake_redis: MagicMock,
) -> None:
    """After probe_ttl_seconds elapses, the next is_open() must admit a second probe."""
    cb = RagCircuitBreaker(redis=fake_redis, service_name="svc", ticker="AAPL")

    # Simulate: CB is in HALF_OPEN (state key exists, probe key absent)
    async def _fake_get(key: str) -> str | None:
        if "state" in key:
            return "open"
        return None  # probe key absent

    async def _fake_set_nx(key: str, value: str, ex: int | None = None) -> bool:
        return True  # probe key set successfully

    fake_redis.get = AsyncMock(side_effect=_fake_get)
    fake_redis.set = AsyncMock(side_effect=_fake_set_nx)

    # First probe: admitted (set_nx returns True)
    result1 = await cb.is_open()
    assert result1 is False, "First probe in HALF_OPEN must be admitted"

    # Second probe with expired probe key (set_nx returns True again)
    result2 = await cb.is_open()
    assert result2 is False, "Re-admission after probe TTL expiry must work"
```

---

### II-3 — F-004 (MAJOR): CB HALF_OPEN → Re-OPEN After Failed Probe

**File**: `services/rag-chat/tests/unit/application/test_circuit_breaker.py`

```python
@pytest.mark.asyncio
async def test_cb_half_open_reopens_after_failed_probe(
    fake_redis: MagicMock,
) -> None:
    """A record_failure() call while the probe is active must re-OPEN the circuit."""
    cb = RagCircuitBreaker(redis=fake_redis, service_name="svc", ticker="AAPL")

    call_log: list[str] = []

    async def _track_call(script: Any, keys: list[str], args: list[Any]) -> int:
        call_log.append("lua_failure")
        return 3  # threshold reached → circuit opens

    fake_redis.evalsha = AsyncMock(side_effect=_track_call)
    fake_redis.script_load = AsyncMock(return_value="abc123")

    # Probe admitted (probe key set)
    fake_redis.get = AsyncMock(return_value="open")
    fake_redis.set = AsyncMock(return_value=True)
    await cb.is_open()

    # Probe fails
    await cb.record_failure()

    assert "lua_failure" in call_log
    # After the Lua script bumps count past threshold, the next is_open must return True
    fake_redis.get = AsyncMock(return_value="open")
    fake_redis.set = AsyncMock(return_value=False)  # probe key still active
    assert await cb.is_open() is True
```

---

### II-4 — F-005 (MAJOR): Disabled Cron Test Actually Calls Application Code

**File**: `services/rag-chat/tests/unit/application/test_app_lifespan_citation_cron.py`

**Issue**: The test that verifies the citation cron is disabled does NOT verify that
`ScoreCitationAccuracyUseCase` is NOT invoked. It may check that a flag is false without
verifying no downstream code runs.

```python
@pytest.mark.asyncio
async def test_citation_cron_disabled_does_not_call_use_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When CITATION_CRON_ENABLED=false, ScoreCitationAccuracyUseCase.execute must NOT be called."""
    from unittest.mock import AsyncMock, patch

    with patch(
        "rag_chat.application.use_cases.score_citation_accuracy.ScoreCitationAccuracyUseCase.execute",
        new_callable=AsyncMock,
    ) as mock_execute:
        from rag_chat.infrastructure.jobs.citation_accuracy_cron import CitationAccuracyCron

        cron = CitationAccuracyCron(
            use_case=None,  # type: ignore[arg-type]  # should not be reached
            enabled=False,
            interval_seconds=60,
        )
        await cron.run_once()

        mock_execute.assert_not_called()
```

---

### II-5 — F-008 (MAJOR): QuotesConsumer No-op Dedup Contract Test

**File**: `services/market-data/tests/unit/infrastructure/messaging/consumers/test_quotes_consumer_dedup.py` (new file)

```python
"""Tests for QuotesConsumer's explicit no-op dedup contract (BP-035 pattern)."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from market_data.infrastructure.messaging.consumers.quotes_consumer import QuotesConsumer

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_quotes_consumer_is_duplicate_always_false() -> None:
    """is_duplicate must always return False — dedup is handled by create_if_not_exists."""
    consumer = QuotesConsumer(
        uow_factory=MagicMock(),
        object_storage=None,
        valkey_client=None,
    )
    assert await consumer.is_duplicate("any-event-id") is False


@pytest.mark.asyncio
async def test_quotes_consumer_mark_processed_is_noop() -> None:
    """mark_processed must be a transparent no-op — no Valkey writes."""
    mock_valkey = MagicMock()
    mock_valkey.set = AsyncMock()
    consumer = QuotesConsumer(
        uow_factory=MagicMock(),
        object_storage=None,
        valkey_client=mock_valkey,
    )
    await consumer.mark_processed("any-event-id")
    mock_valkey.set.assert_not_awaited()


def test_quotes_consumer_dedup_prefix_is_class_attr() -> None:
    """_dedup_prefix must be a class attribute (not instance) for the allowlist enforcement."""
    assert hasattr(QuotesConsumer, "_dedup_prefix"), "_dedup_prefix must be a class attribute"
    assert isinstance(QuotesConsumer._dedup_prefix, str)
    assert QuotesConsumer._dedup_prefix.startswith("market-data:")
```

---

### II-6 — F-009 (MAJOR): Valkey-Down Fail-Open Path Per Consumer

**File**: `libs/messaging/tests/unit/kafka/consumer/test_dedup.py`

```python
@pytest.mark.asyncio
async def test_fail_open_re_delivery_after_valkey_error(self) -> None:
    """If Valkey is down during mark_processed, the next is_duplicate check must still
    return False (fail-open) — ensuring at-least-once delivery rather than blocking."""
    call_count = 0

    class _FlakyClient:
        async def exists(self, key: str) -> bool:
            return False  # always misses (Valkey down)

        async def set(self, key: str, value: str, ex: int | None = None) -> bool:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("connection refused")
            return True

        async def ttl(self, key: str) -> int:
            return -2

    mixin = _make_mixin(client=_FlakyClient())  # type: ignore[arg-type]

    # mark_processed fails silently (Valkey down)
    await mixin.mark_processed("evt-flaky")

    # Next is_duplicate call must return False (fail-open, not raise)
    result = await mixin.is_duplicate("evt-flaky")
    assert result is False, "Valkey-down must fail-open, not block processing"
```

---

### II-7 — F-010 (MAJOR): uuid5 Determinism for mention_id

**File**: `services/nlp-pipeline/tests/unit/infrastructure/nlp_db/repositories/test_build_chunk_entity_mentions.py`

```python
@pytest.mark.asyncio
async def test_mention_id_is_deterministic_on_replay() -> None:
    """mention_id must be identical across two calls with the same (doc_id, mention_index, surface)."""
    from nlp_pipeline.application.blocks.entity_mentions import build_chunk_entity_mentions
    from uuid import UUID

    doc_id = UUID("00000000-0000-0000-0000-000000000001")
    mentions_run1 = build_chunk_entity_mentions(
        doc_id=doc_id,
        mentions=[{"surface": "Apple Inc", "entity_type": "ORG", "char_start": 0, "char_end": 9}],
    )
    mentions_run2 = build_chunk_entity_mentions(
        doc_id=doc_id,
        mentions=[{"surface": "Apple Inc", "entity_type": "ORG", "char_start": 0, "char_end": 9}],
    )

    assert mentions_run1[0].mention_id == mentions_run2[0].mention_id, (
        "mention_id must be deterministic — uuid5_from_parts(doc_id, idx, surface)"
    )


@pytest.mark.asyncio
async def test_mention_id_differs_by_position() -> None:
    """Two mentions with same surface but different positions must have different IDs."""
    from nlp_pipeline.application.blocks.entity_mentions import build_chunk_entity_mentions
    from uuid import UUID

    doc_id = UUID("00000000-0000-0000-0000-000000000002")
    mentions = build_chunk_entity_mentions(
        doc_id=doc_id,
        mentions=[
            {"surface": "Apple Inc", "entity_type": "ORG", "char_start": 0, "char_end": 9},
            {"surface": "Apple Inc", "entity_type": "ORG", "char_start": 50, "char_end": 59},
        ],
    )
    assert mentions[0].mention_id != mentions[1].mention_id
```

---

### II-8 — F-011 (MAJOR): Outbox Repo ON CONFLICT DO NOTHING Unit Test

**File**: `services/nlp-pipeline/tests/unit/infrastructure/nlp_db/repositories/test_outbox_repo.py` (new)

```python
"""Tests for OutboxRepository ON CONFLICT DO NOTHING idempotency."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID
from nlp_pipeline.infrastructure.nlp_db.repositories.outbox import OutboxRepository
from nlp_pipeline.domain.models import OutboxEntry

pytestmark = pytest.mark.unit


def _make_session() -> tuple[MagicMock, list]:
    executed = []

    async def _fake_execute(stmt, *args, **kwargs):
        executed.append(stmt)
        return MagicMock()

    session = MagicMock()
    session.execute = _fake_execute
    return session, executed


@pytest.mark.asyncio
async def test_outbox_add_uses_on_conflict_do_nothing() -> None:
    """add() must use pg_insert with on_conflict_do_nothing to guard replays."""
    from sqlalchemy.dialects.postgresql import Insert as PgInsert

    session, executed = _make_session()
    repo = OutboxRepository(session)
    entry = OutboxEntry(
        event_id=UUID("00000000-0000-0000-0000-000000000001"),
        topic="nlp.article.enriched.v1",
        payload=b"{}",
    )

    await repo.add(entry)

    assert len(executed) == 1
    stmt = executed[0]
    assert isinstance(stmt, PgInsert), "add() must use pg_insert (ON CONFLICT DO NOTHING)"
    assert stmt._post_values_clause is not None, "ON CONFLICT DO NOTHING clause must be present"


@pytest.mark.asyncio
async def test_outbox_add_passes_deterministic_event_id() -> None:
    """event_id kwarg must be passed through to the pg_insert values."""
    session, executed = _make_session()
    repo = OutboxRepository(session)
    fixed_id = UUID("12345678-0000-0000-0000-000000000001")

    entry = OutboxEntry(event_id=fixed_id, topic="test.v1", payload=b"x")
    await repo.add(entry)

    vals = {col.key: bp.value for col, bp in executed[0]._values.items()}
    assert vals["event_id"] == fixed_id
```

---

### II-9 — F-012 (MAJOR): entity_mention Repo ON CONFLICT DO NOTHING Unit Test

**File**: `services/nlp-pipeline/tests/unit/infrastructure/nlp_db/repositories/test_entity_mention_repo.py` (new)

```python
"""Tests for EntityMentionRepository ON CONFLICT DO NOTHING idempotency."""
import pytest
from unittest.mock import MagicMock
from uuid import UUID
from nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention import EntityMentionRepository

pytestmark = pytest.mark.unit


def _make_session():
    executed = []

    async def _fake_execute(stmt, *args, **kwargs):
        executed.append(stmt)
        return MagicMock(rowcount=1)

    session = MagicMock()
    session.execute = _fake_execute
    return session, executed


@pytest.mark.asyncio
async def test_bulk_insert_uses_on_conflict_do_nothing() -> None:
    """bulk_insert must use ON CONFLICT DO NOTHING so duplicate mention_ids are silently skipped."""
    from sqlalchemy.dialects.postgresql import Insert as PgInsert

    session, executed = _make_session()
    repo = EntityMentionRepository(session)

    mentions = [
        {"mention_id": UUID("00000000-0000-0000-0000-000000000001"),
         "doc_id": UUID("00000000-0000-0000-0000-000000000002"),
         "surface": "Apple Inc", "entity_type": "ORG", "char_start": 0, "char_end": 9}
    ]
    await repo.bulk_insert(mentions)

    assert len(executed) == 1
    stmt = executed[0]
    assert isinstance(stmt, PgInsert)
    assert stmt._post_values_clause is not None
```

---

### II-10 — F-013 (MAJOR): Per-Class Gate with <6 Graded Queries Skip Path

**File**: `tests/scripts/test_eval_retrieval.py`

```python
def test_per_class_gate_skips_class_with_fewer_than_6_queries() -> None:
    """Classes with n < 6 must emit a warning and be excluded from regression check."""
    import io
    from contextlib import redirect_stderr

    baseline = {"classes": {"thin_class": {"ndcg_at_10": 0.9, "n": 5}}}
    current = {"classes": {"thin_class": {"ndcg_at_10": 0.5, "n": 5}}}  # -0.4 regression

    stderr_buf = io.StringIO()
    with redirect_stderr(stderr_buf):
        regressions = _check_per_class_regressions(current, baseline, threshold=0.05)

    assert regressions == [], "class with n < 6 must be skipped, not trigger a regression"
    assert "thin_class" in stderr_buf.getvalue(), "must warn about skipped class"
    assert "only 5 graded" in stderr_buf.getvalue().lower() or "n_graded" in stderr_buf.getvalue()
```

---

### II-11 — DP-009 (MAJOR): Fail-Open Re-delivery Sequence in test_dedup.py

**File**: `libs/messaging/tests/unit/kafka/consumer/test_dedup.py`

```python
@pytest.mark.asyncio
async def test_fail_open_sequence_mark_fails_then_next_check_returns_false(self) -> None:
    """Sequence: mark_processed fails (Valkey down) → next is_duplicate check returns False.

    This is the at-least-once guarantee: we never block delivery, even when the dedup
    store is unavailable. The caller should expect possible re-processing.
    """
    failed_set = False

    class _MarkFailClient:
        async def set(self, key: str, value: str, ex: int | None = None) -> bool:
            nonlocal failed_set
            failed_set = True
            raise ConnectionError("valkey unreachable")

        async def exists(self, key: str) -> bool:
            return False  # key was never stored because set() failed

        async def ttl(self, key: str) -> int:
            return -2

    mixin = _make_mixin(client=_MarkFailClient())  # type: ignore[arg-type]
    await mixin.mark_processed("evt-recover")

    assert failed_set, "set() must have been attempted"
    result = await mixin.is_duplicate("evt-recover")
    assert result is False, "After failed mark_processed, is_duplicate must return False (fail-open)"
```

---

## Part III — Minor/NIT Fixes

All items below are ready to implement. No architecture decision required.

---

### III-1 — A-001: `LLMJudgePort` Defined in `use_cases/` Rather Than `application/ports/`

**File**: `services/rag-chat/src/rag_chat/application/use_cases/score_citation_accuracy.py:99`

**Fix**: Extract `LLMJudgePort` to a dedicated ports file:

```python
# services/rag-chat/src/rag_chat/application/ports/llm_judge.py (NEW)
from typing import Protocol, runtime_checkable

@runtime_checkable
class LLMJudgePort(Protocol):
    async def score_citation(self, *, claim: str) -> str: ...
```

Update `score_citation_accuracy.py` to import from the new location. Update
`citation_judge_adapter.py` to also reference the port for type checking.

---

### III-2 — A-002: `LLMJudgePort.score_citation` Has Phantom `snippet` Param

**File**: `services/rag-chat/src/rag_chat/application/use_cases/score_citation_accuracy.py:102`
**File**: `services/rag-chat/src/rag_chat/infrastructure/llm/citation_judge_adapter.py:44`

The protocol declares `score_citation(*, claim: str, snippet: str)` but the use case comment
at line 198 says `snippet=safe_snippet  # kept for protocol compliance` — the adapter ignores
`snippet` entirely (it uses the prompt already built from the snippet). The `snippet` param is
dead weight in the interface.

**Fix**: Remove `snippet` from the protocol signature:
```python
class LLMJudgePort(Protocol):
    async def score_citation(self, *, claim: str) -> str: ...
```
Update all callers: the use case already passes the full prompt as `claim`, so removing
`snippet` from the call site at line 196-198 is a 3-line change.

---

### III-3 — A-005: L1 Locked Decision Says "All 8 Migrate" But 14 Were Allowlisted

**File**: `docs/plans/0084-w5-5b-operating-table-hardening-plan.md`

The plan's §0-bis.0 L1 decision text says "the 8 remaining legacy hand-rolled consumers
migrate to ValkeyDedupMixin" but PLAN-0084 B-2 ended up allowlisting 14 grandfathered entries.
Update the plan text to match actual outcome: "14 grandfathered entries were allowlisted in B-2;
future consumers must use ValkeyDedupMixin."

---

### III-4 — A-006: Citation Judge Uses 235B Completion Model

**File**: `services/rag-chat/src/rag_chat/config.py:80`

The citation judge calls `ScoreCitationAccuracyUseCase` which uses the same
`completion_model = "Qwen/Qwen3-235B-A22B-Instruct-2507"` (235B params) as the main chat
flow. A 0-3 rubric scoring task needs a 0.5B-8B model, not 235B.

**Fix**: Add a separate config field:
```python
citation_judge_model: str = "meta-llama/Meta-Llama-3.1-8B-Instruct"  # RAG_CHAT_CITATION_JUDGE_MODEL
```
Wire it in `app.py` when constructing `CitationJudgeAdapter`. The 8B model cuts per-citation
LLM cost by ~30x.

---

### III-5 — A-007: `canon_repo` Wiring Lacks `: CanonicalEntityPort` Annotation

**File**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:499`

```python
canon_repo = CanonicalEntityRepository(intel_session)
```

Should be typed to the port:
```python
canon_repo: CanonicalEntityPort = CanonicalEntityRepository(intel_session)
```

This requires `CanonicalEntityPort` to be defined first (see PLAN-0084's D-1 wave which added
`CanonicalEntityPort` — verify import is available).

---

### III-6 — S-002: Dedup Key Has No Tenant Dimension

**File**: `libs/messaging/src/messaging/kafka/consumer/dedup.py`

The dedup key is `{prefix}:{event_id}`. In a multi-tenant deployment, two tenants whose
articles are processed by the same consumer pod share the dedup namespace. This is NOT a
current problem (single-tenant) but IS a future footgun.

**Fix**: Add a docstring warning:
```python
class ValkeyDedupMixin:
    """
    WARNING (multi-tenant): dedup keys are global per consumer group, not per tenant.
    If tenant isolation is ever required, subclasses should override `_make_dedup_key()`
    to incorporate `tenant_id` into the key: `{prefix}:{tenant_id}:{event_id}`.
    """
```

No code change required now. The warning prevents future engineers from assuming isolation.

---

### III-7 — S-004: `s1_internal_token` Is `str` Not `SecretStr`

**File**: `services/rag-chat/src/rag_chat/config.py:101`

```python
s1_internal_token: str = ""
```

Should be:
```python
s1_internal_token: SecretStr = SecretStr("")  # RAG_CHAT_S1_INTERNAL_TOKEN
```

Update all call sites to use `.get_secret_value()`. This prevents the token from appearing
in `repr(settings)` logs.

---

### III-8 — S-005: `internal_jwt_skip_verification` Guard Doesn't Cover `staging` Env

**File**: `services/rag-chat/src/rag_chat/config.py:155-157`

```python
_app_env = os.environ.get("APP_ENV", "").strip().lower()
if self.internal_jwt_skip_verification and _app_env in {"production", "prod"}:
    raise ValueError(...)
```

`staging` is not covered. A misconfigured staging deployment with skip_verification=True
would go undetected.

**Fix**:
```python
_PROTECTED_ENVS = {"production", "prod", "staging", "stage"}
if self.internal_jwt_skip_verification and _app_env in _PROTECTED_ENVS:
    raise ValueError("internal_jwt_skip_verification MUST NOT be enabled in production or staging")
```

---

### III-9 — D-001: No Prometheus Metric on Valkey-Error At-Least-Once Fallback

**File**: `libs/messaging/src/messaging/kafka/consumer/dedup.py`

When `is_duplicate()` catches a Valkey error and returns `False` (fail-open), there's no
metric emitted. Silent at-least-once fallbacks are invisible in dashboards.

**Fix**: Add a counter:
```python
from observability.metrics import counter  # type: ignore[import-untyped]

_dedup_valkey_fallback_total = counter(
    "messaging_dedup_valkey_fallback_total",
    "Number of times dedup check failed open due to Valkey error",
    ["consumer_prefix"],
)

async def is_duplicate(self, event_id: str) -> bool:
    ...
    except Exception:
        _dedup_valkey_fallback_total.labels(consumer_prefix=self._dedup_prefix).inc()
        logger.warning("dedup.valkey_check_failed", event_id=event_id, exc_info=True)
        return False
```

---

### III-10 — D-003: 24h Dedup TTL < Max Replay Horizon for Long Consumer Pauses

**File**: `libs/messaging/src/messaging/kafka/consumer/dedup.py`

The `_dedup_ttl_seconds = 86400` (24h) is documented as "matches KG-consumer convention"
but the Kafka topic retention for `nlp.article.enriched.v1` is 7 days. If a consumer is
paused for 25+ hours (e.g., scheduled maintenance, rolling deployment), the dedup window
expires and re-delivery re-processes articles.

**Fix**: No code change; add a docstring:
```python
_dedup_ttl_seconds: int = 86400
"""Dedup TTL in seconds. Must exceed max expected consumer pause duration.
Current Kafka topic retention is 7 days (604800s) for nlp.article.enriched.v1.
If consumers are paused longer than 24h, increase this to match the topic retention.
"""
```

---

### III-11 — DP-002/DP-003: `_dedup_prefix` Set as Instance Attr, Not Class Attr

**Files**:
- `services/knowledge-graph/.../fundamentals_consumer.py:118`
- `services/market-data/.../quotes_consumer.py:52` (already class-level — correct)
- Check other consumers

In `FundamentalsDescriptionConsumer.__init__`:
```python
self._dedup_prefix = f"kg:fund:{config.group_id}"  # instance attr — DP-002/DP-003
```

`OHLCVConsumer` has the same pattern. The architecture test checks `_dedup_prefix` as a class
attribute; setting it as an instance attribute breaks the test expectation.

**Fix**: Move to class attribute with a placeholder, then allow `__init__` to specialise:
```python
class FundamentalsDescriptionConsumer(...):
    _dedup_prefix: str = "kg:fund"  # class-level default; specialised in __init__

    def __init__(self, ..., config: ConsumerConfig, ...):
        self._dedup_prefix = f"kg:fund:{config.group_id}"  # instance specialisation OK
```

The architecture test must explicitly handle "class has placeholder, instance may override"
— check what the current test asserts and adjust accordingly.

---

### III-12 — DP-004: `TemporalEventConsumer` Uses `kg:temporal:` Prefix (Inconsistent)

**File**: `services/knowledge-graph/.../temporal_event_consumer.py:145`

```python
self._dedup_prefix = f"kg:temporal:{config.group_id}"
```

All other KG consumers use `kg:dedup:` prefix. This inconsistency makes it impossible to
write a single Valkey key scan that covers all KG consumer dedup keys.

**Fix**: Change to `kg:dedup:temporal:{config.group_id}` for consistency. Since the old keys
will expire after 24h, no migration is needed — just update the prefix string.

---

### III-13 — DP-006/D-015: `exposure_id` Uses `new_uuid7()` — Deterministic Preferred

**File**: `services/knowledge-graph/.../temporal_event_consumer.py:216`

```python
exposure_id=new_uuid7(),
```

On Kafka re-delivery of the same `intelligence.temporal_event.v1`, a new `new_uuid7()` is
generated, creating a duplicate row in `entity_event_exposures` (if the UNIQUE constraint is
on natural key, the insert is rejected — but the UUID7 approach bypasses `ON CONFLICT
(exposure_id) DO NOTHING`).

**Fix**: Use `uuid5_from_parts(str(event_id), str(entity_id), "exposure")` so the exposure_id
is deterministic per `(event_id, entity_id)` pair. This requires verifying that
`entity_event_exposures` has a natural key UNIQUE constraint on `(temporal_event_id,
canonical_entity_id)`.

```python
from common.ids import uuid5_from_parts  # type: ignore[import-untyped]

exposure_id = uuid5_from_parts(str(temporal_event_id), str(entity_id), "exposure")
```

---

### III-14 — D-013: `FundamentalsConsumer._upsert_fundamentals_snapshot` Uses Two Sessions

**File**: `services/knowledge-graph/.../fundamentals_consumer.py`

The method opens a second session inside an already-open session, creating two independent
transactions for what should be a single atomic write. If the first commit succeeds and the
second fails, the fundamentals data is partially written.

**Fix**: Pass the existing session to `_upsert_fundamentals_snapshot` rather than creating a
new one. Remove the nested `async with self._session_factory() as session2:` pattern.

---

### III-15 — D-006: Prometheus Gauge Not Reconciled with Valkey CB State on Restart

**File**: `services/rag-chat/src/rag_chat/application/pipeline/circuit_breaker.py`

On service restart, the `cb_open_gauge` is initialised to 0. If the CB was `open` in Valkey
before restart (the state key persists across restarts), the gauge shows `0` (closed) but
the CB is actually open. Dashboards show a false healthy state.

**Fix**: Add a `reconcile_gauge()` call in the CB constructor or service lifespan:
```python
async def reconcile_gauge(self) -> None:
    """Sync Prometheus gauge with current Valkey CB state on startup."""
    for ticker in self._tracked_tickers:
        state = await self._redis.get(self._state_key(ticker))
        if state == "open":
            self._cb_open_gauge.labels(...).set(1)
        else:
            self._cb_open_gauge.labels(...).set(0)
```

Call from `app.py` lifespan after the Redis client is initialised.

---

### III-16 — S-010: JWT Error Log May Include Response Body

**File**: `services/rag-chat/src/rag_chat/...` (JWT middleware)

If the internal JWT verification call to S9 fails with a non-2xx response, the error log
might include the full response body, which could contain sensitive fields (e.g., user info,
error details with token fragments).

**Fix**: Log only `status_code` and a fixed error category, never the response body:
```python
except httpx.HTTPStatusError as exc:
    log.warning(
        "jwt_verification_failed",
        status_code=exc.response.status_code,
        # DO NOT log exc.response.text — may contain sensitive data
    )
```

---

### III-17 — S-011: Path Traversal in Boost Sweep `--boost-sweep-inputs`

**File**: `scripts/eval_retrieval.py`

The `--boost-sweep-inputs` argument accepts a file path that is read without validation.
A relative path with `../` components can escape the expected directory.

**Fix**: Resolve and validate the path:
```python
def _validate_input_path(p: str) -> pathlib.Path:
    resolved = pathlib.Path(p).resolve()
    if not resolved.exists():
        raise argparse.ArgumentTypeError(f"File not found: {p}")
    return resolved
```

---

### III-18 — S-013: `EVAL_JWT_REFRESH_URL` Is a Repo Variable, Should Be a Secret

**File**: `.github/workflows/retrieval-eval.yml:189`

```yaml
EVAL_JWT_REFRESH_URL: ${{ vars.EVAL_JWT_REFRESH_URL || '' }}
```

`EVAL_JWT_REFRESH_URL` is a GitHub repository variable (visible to all contributors) but it
represents the URL to which JWT credentials are sent. This should be a repository secret:

```yaml
EVAL_JWT_REFRESH_URL: ${{ secrets.EVAL_JWT_REFRESH_URL || '' }}
```

---

## Part IV — Implementation Task List

The following plan (PLAN-0085 or a follow-up wave of PLAN-0084) should implement these
findings in the order below. All architecture decisions have been resolved; no additional
decisions are needed before implementing.

### Wave 1 — Security & CI Quick Wins (1-2 hours)
- S-006: MinIO key validation (`KeyBuilder.is_valid_silver_key`)
- S-009: `--rag-url` scheme/host validation
- S-012: Replace curl JWT arg with Python httpx smoke probe
- S-004: `s1_internal_token` → `SecretStr`
- S-005: Add `staging` to protected-envs guard
- S-010: JWT error log response body removal
- S-011: `--boost-sweep-inputs` path traversal guard
- S-013: `EVAL_JWT_REFRESH_URL` → secret

### Wave 2 — Architecture/Config Cleanup (1-2 hours)
- A-001: Extract `LLMJudgePort` to `application/ports/llm_judge.py`
- A-002: Remove phantom `snippet` param from `LLMJudgePort.score_citation`
- A-005: Fix L1 plan text inconsistency
- A-006: Add `citation_judge_model` config field wired to 8B model
- A-007: Add `: CanonicalEntityPort` annotation to `canon_repo`
- D-011/DP-001: Remove `ValkeyDedupMixin` from `QuotesConsumer` MRO + document contract

### Wave 3 — Data Consistency Fixes (2-3 hours)
- DP-002/DP-003: Fix `_dedup_prefix` as class attribute in `FundamentalsDescriptionConsumer`
- DP-004: Align `TemporalEventConsumer` prefix to `kg:dedup:temporal:`
- DP-006/D-015: Deterministic `exposure_id` via `uuid5_from_parts`
- D-013: Single-session `_upsert_fundamentals_snapshot`
- S-003: Filter 4xx from CB failure counter

### Wave 4 — Observability & Documentation (1 hour)
- D-001: Prometheus counter for Valkey fallback
- D-003: Document 24h TTL < 7-day retention in docstring
- D-006: CB gauge reconciliation on restart
- S-002: Multi-tenant dedup key warning docstring

### Wave 5 — Critical Correctness Fixes (3-4 hours)
- D-010: Re-raise intel_session commit failure + Prometheus counter
- D-014: Outbox pattern for `entity.dirtied.v1` on provisional promotion
- D-016: Add `processing_started_at` column + fix recovery query

### Wave 6 — Test Coverage (2-3 hours)
- F-001: Exact `set(key, "1", ex=N)` call signature test
- F-003: CB re-admission after probe TTL expiry
- F-004: CB HALF_OPEN → re-OPEN after failed probe
- F-005: Disabled cron doesn't call use case
- F-008: QuotesConsumer no-op dedup contract
- F-009: Valkey-down fail-open path
- F-010: uuid5 determinism for mention_id
- F-011: Outbox repo ON CONFLICT DO NOTHING
- F-012: entity_mention repo ON CONFLICT DO NOTHING
- F-013: Per-class gate with <6 queries skip
- DP-009: Fail-open re-delivery sequence

---

## Part V — Compounding Updates

### BUG_PATTERNS.md — New Patterns

**BP-NEW (Testing category)**: "Session already open: nested `async with session_factory()`
in method called within open session creates a second independent transaction — partial write
on failure. Always pass the active session as a parameter instead of opening a new one."
→ Affected: `FundamentalsConsumer._upsert_fundamentals_snapshot` (D-013)

**BP-NEW (Kafka/Messaging category)**: "Fire-and-forget after DB commit: Kafka produce or
outbox insert placed AFTER `session.commit()` without its own transaction creates a permanent
loss window if the process crashes between commit and produce. Use outbox pattern for
events that must be emitted exactly once per DB transition."
→ Affected: `entity.dirtied.v1` in `provisional_enrichment.py` (D-014)

**BP-NEW (Auth/Security category)**: "JWT in curl argument: `--header 'X-JWT: ${TOKEN}'`
exposes the token in `ps aux` on shared CI runners. Use `--config <(echo "header = X-JWT: ${TOKEN}")` or httpx in Python."
→ Affected: `retrieval-eval.yml` (S-012)

### HIGH_RISK_PATTERNS.md — New Patterns

**HR-NEW**: `except Exception: logger.warning(...) # DON'T re-raise` after a DB commit in a
dual-session consumer is a RED FLAG. A silent swallow on the second session commit guarantees
data loss on the first failure — the next re-delivery's early-skip fires before the second
session's writes are retried. **Always re-raise + increment a counter.**

### REVIEW_CHECKLIST.md — New Checks

- "Dual-session consumers: does each session's commit failure trigger a re-raise (nack) or
  is it swallowed? Swallowed failures + early-skip = permanent data loss."
- "After-commit Kafka produce: is it inside an outbox transaction or fire-and-forget? For
  one-time lifecycle events (entity promotion, entity deletion), outbox is required."
- "CB `record_failure()`: does it distinguish 4xx (client error) from 5xx/network (service
  fault)? Counting 4xx inflates CB failure count, causing false-positive circuit opens."

---

**End of investigation report.**
