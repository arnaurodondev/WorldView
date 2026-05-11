# QA Report: KG Population + RAG Chat Retrieval Pipelines

**Date**: 2026-05-03 UTC
**Skill**: qa
**Scope**: KG population pipeline (S6→S7) + RAG chat retrieval pipeline (S8) — branch-changed-only
**Branch**: feat/content-ingestion-wave-a1
**Verdict**: FAIL
**Report file**: docs/audits/2026-05-03-qa-both-pipelines-report.md

---

## Executive Summary

Five specialist agents reviewed the KG population and RAG chat retrieval pipelines against the
current branch state. The review uncovered **8 BLOCKING issues**, **7 CRITICAL issues**, and
**22 MAJOR issues** across all five specializations. The pipelines are not deployment-ready in
their current state.

The most severe finding is a type annotation mismatch in `fusion.py` where `summary_authority:
str | None` causes a `TypeError` at runtime when sorting float relation scores — this silently
drops all RAG context. A second BLOCKING issue is that `provisional_enrichment_core.py`
hard-codes `"nomic-embed-text"` as the embedding model default, which generates a 768-dim vector
against a `vector(1024)` column — a `FatalError` on every provisional enrichment call. A third
BLOCKING is that the `entity.dirtied.v1` payload emitted by both the enrichment worker and
consumer is missing required Avro envelope fields, breaking all downstream Avro consumers.

The circuit breaker (`SourceCircuitBreaker`) is fully implemented but never wired in `app.py`,
making the entire crash-resilience layer dead code. The Kafka base consumer calls
`mark_processed()` before `uow.commit()`, which is a systematic at-least-once violation. The
`S7Client.cypher_traverse()` POSTs to a non-existent endpoint (404), silently returning empty
Cypher results.

Six independent findings across multiple agents confirm that `provisional_entity_queue` rows
can become permanently stuck in `'processing'` status after any process crash, with no recovery
mechanism. The `EmbeddingRefreshWorker` holds the DB session open across all external HTTP
calls (ARCH-003 violation), risking connection pool exhaustion.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| QA/Test | ~25 | 12 | 2 | 0 | 5 | 5 | 0 |
| Security | ~20 | 12 | 0 | 3 | 6 | 3 | 0 |
| Data Platform | ~20 | 14 | 3 | 2 | 6 | 2 | 1 |
| Distributed Systems | ~18 | 14 | 4 | 3 | 5 | 2 | 0 |
| Architecture | ~35 | 15 | 2 | 0 | 8 | 4 | 1 |
| **Total (deduped)** | — | **37** | **8** | **7** | **16** | **5** | **1** |

### Cross-Agent Signals (HIGH Confidence — 2+ agents)

| Finding | Agents | Description |
|---------|--------|-------------|
| `summary_authority` type mismatch | QA, Data Platform | `str\|None` vs actual `float` causes TypeError in sort |
| canonical_entities no UNIQUE constraint | Data Platform, Distributed Systems | Duplicate entities on concurrent processing |
| Phase 3 single shared session | Data Platform, Distributed Systems | Session poisoning corrupts entire batch |
| EmbeddingRefreshWorker ARCH-003 violation | Data Platform, Distributed Systems | Session held across HTTP calls |
| provisional_entity_queue 'processing' stuck | QA, Data Platform, DS (x3) | Rows lost after crash — no recovery |
| KG topics missing from messaging/topics.py | Data Platform, Architecture | Topic strings hardcoded in producers/consumers |

---

## Test Execution Summary

> Full automated test suite not run (infrastructure not available). Unit tests run for changed
> files — all passing at the time of the last commit (`ec5e66bd`). Integration/E2E marked SKIP.

| Layer | Scope | Tests | Passed | Failed | Status |
|-------|-------|-------|--------|--------|--------|
| Lint (ruff) | libs/ + services/ | — | — | 0 | PASS |
| Type Check (mypy) | changed packages | — | — | 0 | PASS |
| KG Unit | knowledge-graph | 51 | 51 | 0 | PASS |
| RAG Unit | rag-chat | 11 | 11 | 0 | PASS |
| ml-clients Unit | ml-clients | 7 (new) | 7 | 0 | PASS |
| Integration | all | — | — | — | SKIP (no infra) |
| E2E | all | — | — | — | SKIP (no infra) |

---

## BLOCKING Issues

---

## Issue QA-F-001 / DP-F-011: `summary_authority` Type Mismatch — TypeError in Fusion

### Summary
`RelationResult.summary_authority` is typed `str | None` in the RAG chat port but S7 computes and returns it as a `float`. When sorting relations with the `or ""` fallback, Python raises `TypeError: '<' not supported between instances of 'str' and 'float'`, crashing the entire fusion step and silently dropping ALL RAG context.

### Severity / Confidence
**Severity**: BLOCKING
**Confidence**: HIGH
**Flagged by**: QA/Test, Data Platform

### Root Cause Analysis
- **What**: `upstream_clients.py` port declares `summary_authority: str | None = None`. S7's `schemas.py:208` and `relation_summary.py:193` compute and return a `float`. The sort in `fusion.py:50` uses `r.summary_authority or ""`, producing a mixed `str`/`float` comparison.
- **Why**: The port type annotation was written before verifying the S7 API response schema.
- **When**: Every request that retrieves any relations where at least one has `summary_authority=None`.
- **Where**: `services/rag-chat/src/rag_chat/application/ports/upstream_clients.py` (declaration) + `fusion.py:50` (use).
- **History**: Not in BUG_PATTERNS.md; new finding.

### Evidence
```python
# upstream_clients.py
summary_authority: str | None = None  # WRONG — S7 returns float

# fusion.py:50
sorted(relations, key=lambda r: r.summary_authority or "", reverse=True)
# TypeError when mixing float and "" fallback
```
- **File**: `services/rag-chat/src/rag_chat/application/ports/upstream_clients.py:63`
- **File**: `services/rag-chat/src/rag_chat/application/pipeline/fusion.py:50`

### Impact
- **Immediate**: All chat requests that retrieve KG relations will crash in the fusion step.
- **Blast radius**: Every query where `plan.use_relations=True` — the standard path for instrument-specific queries.
- **Data risk**: No data corruption, but entire RAG answer is dropped silently.
- **User impact**: Chat returns an empty/fallback answer without explanation.

### Solution

#### Option A: Fix type annotation + sort key
**Changes required**:
- `upstream_clients.py:63` — change `str | None` to `float | None`
- `fusion.py:50` — change `or ""` to `or 0.0`
- `test_fusion.py` — update `_relation_result()` fixture to use `float` values
- Add a test with mixed `float` / `None` `summary_authority`

**Effort**: Low | **Risk**: Low

### Verification Steps
- [ ] `pytest services/rag-chat/tests/unit/application/test_fusion.py -v` — all pass
- [ ] Manually verify `sorted([0.8, None, 0.3], key=lambda v: v or 0.0, reverse=True)` returns `[0.8, 0.3, None]`

---

## Issue ARCH-F-006: `"nomic-embed-text"` Hard-Coded Default — 768-dim vs vector(1024) FatalError

### Summary
`provisional_enrichment_core.py` and `provisional_enrichment.py` hard-code `_DEFAULT_EMBED_MODEL_ID = "nomic-embed-text"` as the embedding model fallback. `config.py:72` explicitly warns that `nomic-embed-text` produces 768-dim vectors which raise a `FatalError` on every embed call because the `entity_embedding_state.embedding` column is `vector(1024)`. This hard-coded default silently overrides the correct configured model.

### Severity / Confidence
**Severity**: BLOCKING
**Confidence**: HIGH
**Flagged by**: Architecture

### Root Cause Analysis
- **What**: Module-level constant `_DEFAULT_EMBED_MODEL_ID = "nomic-embed-text"` in two files. The `ProvisionalEnrichmentWorker` constructor default for `embed_model_id` uses this constant.
- **Why**: Copied from the Ollama embedding adapter default without checking dimension alignment.
- **When**: Any deployment where `KNOWLEDGE_GRAPH_EMBEDDING_MODEL_ID` is not explicitly set.
- **Where**: `provisional_enrichment_core.py:32`, `provisional_enrichment.py:47`.

### Evidence
```python
# provisional_enrichment_core.py:32
_DEFAULT_EMBED_MODEL_ID = "nomic-embed-text"  # 768-dim!

# config.py:70-72
embedding_model_id: str = "bge-large:latest"
# WARNING: "nomic-embed-text" produces 768-dim vectors and raises FatalError
# on every embed call because entity_embedding_state.embedding is vector(1024)
```

### Solution

#### Option A: Remove the default, always pass from settings
- Remove `_DEFAULT_EMBED_MODEL_ID` constant from both files
- Ensure `build_workers()` in `scheduler_main.py` always passes `settings.embedding_model_id` explicitly
- Change `ProvisionalQueuedConsumer.__init__` default to `embed_model_id: str = "bge-large:latest"`

**Effort**: Low | **Risk**: Low

---

## Issue ARCH-F-005: `entity.dirtied.v1` Payload Missing Required Avro Fields

### Summary
Both `ProvisionalEnrichmentWorker` and `ProvisionalQueuedConsumer` emit `entity.dirtied.v1` events with only `{"entity_id": "<uuid>"}`. The Avro schema at `infra/kafka/schemas/entity.dirtied.v1.avsc` requires `occurred_at` and `dirty_reason` with no defaults — any Avro-deserializing downstream consumer will fail to parse these events.

### Severity / Confidence
**Severity**: BLOCKING
**Confidence**: HIGH
**Flagged by**: Architecture

### Evidence
```python
# provisional_enrichment.py:248
value=json.dumps({"entity_id": str(dirty_id)}).encode()
# Missing: event_id, event_type, occurred_at, dirty_reason (required, no default)
```
- **File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py:248`
- **File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/provisional_queued_consumer.py:238`

### Solution

#### Option A: Add all required Avro envelope fields
```python
from common.time import utc_now
from common.ids import new_uuid7

value = json.dumps({
    "event_id": str(new_uuid7()),
    "event_type": "entity.dirtied",
    "schema_version": 1,
    "occurred_at": utc_now().isoformat(),
    "entity_id": str(entity_id),
    "dirty_reason": "profile_updated",  # or "new_relation"
    "source_doc_id": None,
    "correlation_id": None,
}).encode()
```

Extract to a shared helper in `provisional_enrichment_core.py`.

**Effort**: Low | **Risk**: Low

---

## Issue DP-F-012: `S7Client.cypher_traverse()` POSTs to Non-Existent Endpoint

### Summary
`S7Client.cypher_traverse()` POSTs to `/api/v1/graph/cypher`. The S7 API router registers only sub-routes `/api/v1/graph/cypher/path` and `/api/v1/graph/cypher/neighborhood`. Every Cypher retrieval call from RAG chat returns 404, silently returning `[]` as results. The entire Cypher graph traversal path is non-functional.

### Severity / Confidence
**Severity**: BLOCKING
**Confidence**: HIGH
**Flagged by**: Data Platform

### Evidence
```python
# s7_client.py
await self._post("/api/v1/graph/cypher", ...)  # 404 — route doesn't exist

# S7 router (api/cypher.py:43)
router = APIRouter(prefix="/api/v1/graph/cypher")
@router.post("/path")        # exists: /api/v1/graph/cypher/path
@router.post("/neighborhood") # exists: /api/v1/graph/cypher/neighborhood
```

### Solution
Replace `cypher_traverse()` with `cypher_neighborhood()` calling `/api/v1/graph/cypher/neighborhood`. Adjust payload structure to match the `CypherNeighborhoodRequest` schema.

---

## Issue DS-F-005: Kafka Consumer `mark_processed()` Called Before `uow.commit()`

### Summary
In `libs/messaging/src/messaging/kafka/consumer/base.py`, `mark_processed(event_id)` (Valkey SET, 24h TTL) is called before `uow.commit()`. If the DB commit fails, the Kafka offset is not committed but the Valkey dedup key is already set. On re-delivery, `is_duplicate()` returns `True` and the message is silently skipped — the DB write is never retried. This is a systematic at-least-once guarantee violation.

### Severity / Confidence
**Severity**: BLOCKING
**Confidence**: HIGH
**Flagged by**: Distributed Systems

### Evidence
```python
# base.py:391-392
await self.process_message(key, value, headers)
await self.mark_processed(event_id)   # ← Valkey set here (premature)
await uow.commit()                    # ← if this fails, event is lost
```

### Solution
Swap order: `await uow.commit()` then `await self.mark_processed(event_id)`.
**Auto-fixable**: YES (swap two lines)
**Effort**: Low | **Risk**: Low

---

## Issue DS-F-006: Circuit Breaker Never Wired — Dead Code

### Summary
`SourceCircuitBreaker` is fully implemented in `circuit_breaker.py`. `ParallelRetrievalOrchestrator` has a complete `_with_cb()` method that uses circuit breakers. However, `app.py` instantiates `ParallelRetrievalOrchestrator` without the `circuit_breakers` parameter, defaulting to `{}`. No `SourceCircuitBreaker` instances are ever created. A permanently-failing S7 service will be retried on every single request indefinitely.

### Severity / Confidence
**Severity**: BLOCKING
**Confidence**: HIGH
**Flagged by**: Distributed Systems

### Evidence
```python
# app.py:329-336
retrieval=ParallelRetrievalOrchestrator(
    s6_client=s6, s7_client=s7, s3_client=s3, s1_client=s1,
    timeout=settings.upstream_timeout_seconds,
    # circuit_breakers ABSENT — {} default
),
```

### Solution
Instantiate one `SourceCircuitBreaker` per source name and pass the dict:
```python
cbs = {
    name: SourceCircuitBreaker(
        name, settings.cb_failure_threshold,
        settings.cb_failure_window_seconds,
        settings.cb_cool_down_seconds, valkey_client
    )
    for name in ["chunk", "relations", "graph", "claims",
                 "events", "contradictions", "financial", "portfolio"]
}
retrieval=ParallelRetrievalOrchestrator(..., circuit_breakers=cbs if settings.cb_enabled else {})
```

---

## Issue QA-F-004 / DP-F-004 / DS-F-003/F-007: `provisional_entity_queue` Stuck in `'processing'`

### Summary
Both `ProvisionalEnrichmentWorker` and `ProvisionalQueuedConsumer` mark rows `status='processing'` and commit before the LLM I/O phase. If the process crashes, rows remain in `'processing'` permanently. The Phase 1 SELECT filters `WHERE status='pending'`, so these rows are never retried. No recovery sweep, no `processing_started_at` column, no timeout mechanism.

### Severity / Confidence
**Severity**: BLOCKING
**Confidence**: HIGH
**Flagged by**: QA/Test, Data Platform, Distributed Systems (3 independent agents)

### Evidence
```sql
-- Phase 1 SELECT (both worker and consumer)
WHERE status = 'pending' AND retry_count < :max_retries
-- 'processing' rows NEVER matched — permanently stuck after crash
```
No recovery query exists anywhere in the codebase.

### Solution

#### Option A: Add `processing_started_at` + recovery sweep
1. Add `processing_started_at TIMESTAMPTZ` column to `provisional_entity_queue`
2. Set `processing_started_at = now()` when marking `'processing'`
3. Add recovery step at the start of `ProvisionalEnrichmentWorker.run()`:
   ```sql
   UPDATE provisional_entity_queue
   SET status='pending', retry_count=retry_count+1, processing_started_at=NULL
   WHERE status='processing'
     AND processing_started_at < now() - interval '15 minutes'
   ```
4. Add a corresponding test for crash recovery

**Effort**: Medium | **Risk**: Low

---

## CRITICAL Issues

---

## Issue DP-F-001 / DS-F-004: `canonical_entities` Has No UNIQUE Constraint on `canonical_name`

### Summary
Two concurrent enrichment calls for the same `mention_text` can both INSERT into `canonical_entities` and produce duplicate entities with different `entity_id`s. The `CanonicalEntityRepository.create()` has no `ON CONFLICT` clause and the table has no UNIQUE index on `canonical_name`.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Data Platform, Distributed Systems

### Solution
Add `UNIQUE (canonical_name, entity_type)` DB constraint + `ON CONFLICT DO NOTHING RETURNING entity_id` pattern, or use a deterministic UUID5 from `(canonical_name, entity_type)` as the entity_id.

---

## Issue DP-F-002 / DS-F-002: Phase 3 Single Shared Session — Session Poisoning

### Summary
`ProvisionalEnrichmentWorker.run()` Phase 3 processes all N entities in a single `AsyncSession`. When `_persist_enrichment()` for entity K raises `IntegrityError`, the session enters an aborted state. The `except` block then calls `_apply_retry(session, ...)` on the same broken session — this fails silently. All subsequent rows in the batch miss their retry transitions and stay stuck in `'processing'`.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Data Platform, Distributed Systems

### Solution
Open a per-entity session inside the loop, or use `session.begin_nested()` (SAVEPOINT) per entity.

---

## Issue DP-F-006 / DS-F-001: `EmbeddingRefreshWorker` ARCH-003 Violation

### Summary
`EmbeddingRefreshWorker` holds a single DB session open for the entire fetch + embed + write loop (up to 100 rows × ~13s per embed = up to 1,300s). This violates ARCH-003, exhausts the connection pool (BP-057), and means a single LLM timeout discards all uncommitted embedding writes.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Data Platform, Distributed Systems

### Solution
Apply the 3-phase ARCH-003 pattern: fetch rows + close session → compute embeddings in parallel (asyncio.gather with semaphore) → open new session + bulk-write + commit.

---

## Issue SEC-F-002 / SEC-F-003: Production API Keys Stored as Plain `str`

### Summary
In `knowledge_graph/config.py`, `storage_access_key`, `storage_secret_key`, `embedding_api_key`, and `deepinfra_api_key` are typed `str`. In `rag-chat/config.py`, `deepinfra_api_key`, `openrouter_api_key`, `cohere_api_key`, and `jina_api_key` are typed `str | None`. All appear in cleartext in `model_dump()`, exception tracebacks, and any logger that dumps settings.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Security

### Solution
Change all to `SecretStr` / `SecretStr | None`. Access with `.get_secret_value()` only at the construction site of the adapter that needs the raw key.

---

## Issue DS-F-006b: No Backpressure / Retry Backoff During LLM Outage

### Summary
When the LLM API is down, `ProvisionalEnrichmentWorker` hammers it on every 5-minute interval with no exponential backoff or circuit breaking. With `max_retries=5` and a `batch_limit=500`, a 25-minute outage permanently fails up to 2,500 rows.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Distributed Systems

### Solution
Add a per-worker in-process backoff flag, or a `next_retry_at TIMESTAMPTZ` column on `provisional_entity_queue` that gates the Phase 1 SELECT.

---

## Issue SEC-F-005: Unvalidated `context_snippet` Reaches LLM Prompt

### Summary
The `context_snippet` field — originating from untrusted article text, arriving via Kafka event — is passed verbatim as the `context` field of `ExtractionInput` with no length cap, sanitization, or delimiter wrapping. A crafted article could include prompt injection instructions that corrupt the entity profile written to `canonical_entities`.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Security

### Solution
1. Truncate `context_snippet` to 500 chars before constructing `ExtractionInput`
2. Wrap in XML delimiters: `<article_context>{context_snippet}</article_context>`
3. Validate LLM output `entity_type` against an allowed-values set before DB write

---

## MAJOR Issues

---

### Finding DS-F-010: Circuit Breaker `record_failure()` Race Condition
- **Severity**: MAJOR | **File**: `circuit_breaker.py:88-118`
- **Issue**: The `ZADD → ZREMRANGEBYSCORE → ZCARD → EXPIRE` pipeline uses `transaction=False`. Two concurrent coroutines can both read `failure_count < threshold` before either writes the `"open"` state key, preventing the breaker from tripping. The state key write is also outside the pipeline (TOCTOU race).
- **Suggestion**: Use `transaction=True` or a Lua script for atomic check-and-set.

---

### Finding DP-F-005: Evidence Unblocking SQL Only Updates `subject_entity_id`
- **Severity**: MAJOR | **File**: `provisional_enrichment_core.py:163-172`
- **Issue**: The `SET subject_entity_id = :entity_id` UPDATE in `persist_enrichment()` never updates `object_entity_id`. For relations where the provisional entity is the object, the wrong column is updated.
- **Suggestion**: Apply the same `CASE WHEN`-based dual-column update pattern as `entity_consumer._unblock_provisional_evidence()`.

---

### Finding DP-F-007: `EmbeddingRefreshWorker` Doesn't Track `model_id` on Write
- **Severity**: MAJOR | **File**: `embedding_refresh.py:72`
- **Issue**: `update_embedding()` only writes the vector — no `model_id` or `last_refreshed_at`. Mixed-model rows produce semantically wrong ANN search results.
- **Suggestion**: Add `model_id` param to `update_embedding()` and write it to a new `summary_embedding_model_id` column.

---

### Finding DP-F-008: `EntityCreatedConsumer` Uses JSON Instead of Avro
- **Severity**: MAJOR | **File**: `entity_consumer.py` + `provisional_enrichment_core.py:175`
- **Issue**: The outbox payload is emitted as `json.dumps(...).encode()` and deserialized with `json.loads(raw)`. The platform standard is Avro. A future migration to Avro wire format will silently corrupt these events.
- **Suggestion**: Either emit via Avro serializer and deserialize with Avro, or add a contract test pinning the wire format as JSON.

---

### Finding ARCH-F-007 / DP-F-009: KG Topics Missing from `messaging/topics.py`
- **Severity**: MAJOR | **File**: `libs/messaging/src/messaging/topics.py`
- **Issue**: `entity.provisional.queued.v1`, `entity.dirtied.v1`, `entity.canonical.created.v1`, `graph.state.changed.v1` are all hardcoded strings in KG service code. Not in the central topic registry.
- **Suggestion**: Add constants for all KG topics to `messaging/topics.py`.

---

### Finding DP-F-010: `graph_write.py` Non-Deterministic `event_id` — Non-Idempotent on Replay
- **Severity**: MAJOR | **File**: `application/blocks/graph_write.py:145`
- **Issue**: `event_id = new_uuid7()` generates a new UUID on every call. Kafka replay will insert duplicate event rows since `ON CONFLICT (event_id, created_at) DO NOTHING` never fires for fresh UUIDs.
- **Suggestion**: Derive `event_id` deterministically from `(doc_id, subject_entity_id, event_type)` using UUID5 or SHA-256 truncation.

---

### Finding DS-F-011: `EmbeddingRefreshWorker` No Checkpoint on Mid-Batch API Failure
- **Severity**: MAJOR | **File**: `embedding_refresh.py:63-73`
- **Issue**: If an embedding API exception propagates out of the loop, all previously successful (but uncommitted) writes are lost. A 2h cycle restarts from scratch.
- **Suggestion**: Commit every N=10 rows inside the loop. Add `s7_embedding_refresh_skipped_total` counter for silent skips.

---

### Finding ARCH-F-004: `chat.py` Route Directly Imports Infrastructure UoW
- **Severity**: MAJOR | **File**: `services/rag-chat/src/rag_chat/api/routes/chat.py:120`
- **Issue**: The streaming route handler imports `RagUnitOfWork` from `rag_chat.infrastructure.db.unit_of_work` inline — a direct API→infrastructure import bypassing DI.
- **Suggestion**: Extract to a `Depends()` generator pattern consistent with `dependencies.py`.

---

### Finding SEC-F-001: `database_url` Has Non-Empty Default With Embedded Credentials
- **Severity**: MAJOR | **File**: `knowledge_graph/config.py:30`
- **Issue**: `database_url: SecretStr = SecretStr("postgresql+asyncpg://postgres:postgres@localhost/...")` — a misconfigured production deployment silently uses `postgres:postgres`.
- **Suggestion**: Remove the default. Pydantic will raise `ValidationError` at startup if missing.

---

### Finding QA-F-002: `DeepInfraReranker` Has Zero Tests
- **Severity**: MAJOR | **File**: `services/rag-chat/src/rag_chat/application/pipeline/reranker.py:226`
- **Issue**: The canonical production reranker is 80+ lines with no test coverage. Score normalisation, fallback on error, and semaphore concurrency are all untested.
- **Suggestion**: Add `TestDeepInfraReranker` covering happy path, API error fallback, semaphore, and empty input.

---

### Finding QA-F-003: `DeepInfraEmbeddingAdapter` Has Zero Tests
- **Severity**: MAJOR | **File**: `libs/ml-clients/src/ml_clients/adapters/deepinfra_embedding.py`
- **Issue**: The embedding adapter used by both KG and RAG pipelines has no tests for dimension validation, API error handling, or cost-cap logic.
- **Suggestion**: Add `TestDeepInfraEmbeddingAdapter` in `test_adapters.py`.

---

### Finding QA-F-006: `provisional_enrichment_core.py` Functions All Patched Out in Tests
- **Severity**: MAJOR | **File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment_core.py`
- **Issue**: Every test in `test_provisional_enrichment.py` and `test_provisional_queued_consumer.py` patches `extract_entity_profile`, `compute_embedding`, `persist_enrichment` — meaning the actual SQL and retry transitions are never executed by any test.
- **Suggestion**: Create `test_provisional_enrichment_core.py` with direct unit tests using mocked sessions.

---

### Finding SEC-F-004: JWT Audience Claim Not Validated
- **Severity**: MAJOR | **File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/middleware/internal_jwt.py:210`
- **Issue**: `jwt.decode()` does not validate the `aud` claim. A valid JWT issued for any other internal service is accepted by S7 and S8.
- **Suggestion**: Add `audience="worldview-internal"` to both `jwt.decode()` calls and add `"aud"` to the `require` list.

---

### Finding DS-F-008: No Backpressure on Kafka Consumer
- **Severity**: MAJOR | **File**: `libs/messaging/src/messaging/kafka/consumer/base.py`
- **Issue**: No pause/resume mechanism. Under sustained load, the consumer falls behind indefinitely with no alerting or flow control.

---

## MINOR Issues

---

### QA-F-007: ContextManager Write-Side Circuit Breaker Untested
- **File**: `context_manager.py:295` | **Issue**: 51 tests but none cover the write-path failure counter, breaker open state, or half-open probe.

### QA-F-009: Cohere Reranker Test Doesn't Verify Reranking
- **File**: `test_reranker.py:83` | **Issue**: Test input already sorted correctly — test passes even without reranking. Swap input order to make the test meaningful.
- **Auto-fixable**: YES

### QA-F-010: `doc_id=None` Items Not Deduplicated in Fusion
- **File**: `fusion.py:126` | **Issue**: KG relation results (`doc_id=None`) can duplicate in fused output. Use `(entity_id, relation_type)` as secondary dedup key.

### QA-F-011: Fire-and-Forget `asyncio.create_task` Without Strong Reference
- **File**: `deepinfra_description.py:215` | **Issue**: Usage log tasks can be GC'd before completion. Follow the `ContextManager` pattern: `self._background_tasks.add(task); task.add_done_callback(self._background_tasks.discard)`.

### SEC-F-007: `APP_ENV` Check Bypassable by Case Variation
- **File**: `config.py:175` | **Issue**: `"production"` vs `"Production"` vs `"PRODUCTION"` — only exact lowercase match skips the guard. Use `.strip().lower() in {"production", "prod"}`.
- **Auto-fixable**: YES

---

## NIT

### ARCH-F-008: `worker_13f_*` Job ID Prefix Used for 3 Different Workers
- **File**: `scheduler.py:97-108` | **Issue**: `worker_13f_embedding`, `worker_13f_partition`, `worker_13f_age_sync` all share `13f_` — should be `13g_partition`, `13h_age_sync`.
- **Auto-fixable**: YES (rename strings + update tests + update docs)

---

## Consolidated Finding Index

| ID | Severity | Description | Agents | Auto-fix |
|----|----------|-------------|--------|----------|
| B-1 | BLOCKING | `summary_authority` type mismatch — TypeError in fusion sort | QA + DP | YES |
| B-2 | BLOCKING | `"nomic-embed-text"` hard-coded — 768-dim FatalError | Arch | YES |
| B-3 | BLOCKING | `entity.dirtied.v1` missing required Avro fields | Arch | YES |
| B-4 | BLOCKING | `S7Client.cypher_traverse()` posts to non-existent URL (404) | DP | NO |
| B-5 | BLOCKING | `mark_processed()` before `uow.commit()` — at-least-once violation | DS | YES |
| B-6 | BLOCKING | Circuit breaker never wired — dead code in app.py | DS | NO |
| B-7 | BLOCKING | `provisional_entity_queue` stuck in `'processing'` — no recovery | QA+DP+DS | NO |
| C-1 | CRITICAL | `canonical_entities` no UNIQUE constraint — duplicate entities | DP + DS | NO |
| C-2 | CRITICAL | Phase 3 single shared session — session poisoning | DP + DS | NO |
| C-3 | CRITICAL | `EmbeddingRefreshWorker` ARCH-003 violation — pool exhaustion | DP + DS | NO |
| C-4 | CRITICAL | Secrets stored as plain `str` in Settings | Security | YES |
| C-5 | CRITICAL | LLM retry storm during outage — no backoff | DS | NO |
| C-6 | CRITICAL | `context_snippet` unvalidated prompt injection | Security | NO |
| C-7 | CRITICAL | `DeepInfraReranker` zero tests | QA | NO |
| M-1 | MAJOR | CB `record_failure()` race condition | DS | NO |
| M-2 | MAJOR | Evidence unblocking only updates `subject_entity_id` | DP | NO |
| M-3 | MAJOR | `EmbeddingRefreshWorker` no `model_id` on write | DP | NO |
| M-4 | MAJOR | `EntityCreatedConsumer` JSON vs Avro mismatch | DP | NO |
| M-5 | MAJOR | KG topics not in `messaging/topics.py` | DP + Arch | YES |
| M-6 | MAJOR | `graph_write.py` non-deterministic `event_id` | DP | NO |
| M-7 | MAJOR | `EmbeddingRefreshWorker` no mid-batch checkpoint | DS | NO |
| M-8 | MAJOR | `chat.py` imports infra UoW directly | Arch | NO |
| M-9 | MAJOR | `database_url` non-empty default with credentials | Security | YES |
| M-10 | MAJOR | `DeepInfraEmbeddingAdapter` zero tests | QA | NO |
| M-11 | MAJOR | `provisional_enrichment_core.py` functions all patched in tests | QA | NO |
| M-12 | MAJOR | JWT audience not validated | Security | NO |
| M-13 | MAJOR | No backpressure on Kafka consumer | DS | NO |
| Mi-1 | MINOR | ContextManager write-side CB untested | QA | NO |
| Mi-2 | MINOR | Cohere reranker test doesn't verify reordering | QA | YES |
| Mi-3 | MINOR | `doc_id=None` items not deduplicated in fusion | QA | NO |
| Mi-4 | MINOR | asyncio task GC risk in `deepinfra_description.py` | QA | NO |
| Mi-5 | MINOR | `APP_ENV` check bypassable by case | Security | YES |
| N-1 | NIT | Worker job IDs reuse `13f_` prefix for 3 workers | Arch | YES |

---

## Recommended Fix Priority

### Immediate (before next deploy)
1. **B-1** — Fix `summary_authority` type annotation + sort key
2. **B-2** — Remove `"nomic-embed-text"` hard-coded default
3. **B-3** — Add required Avro envelope fields to `entity.dirtied.v1` emit
4. **B-4** — Fix `S7Client.cypher_traverse()` endpoint URL
5. **B-5** — Swap `mark_processed` / `uow.commit` order in base consumer
6. **B-6** — Wire `SourceCircuitBreaker` instances in `app.py`

### Short-term (within 1 sprint)
7. **B-7** — Add `processing_started_at` + recovery sweep for stuck rows
8. **C-1** — Add UNIQUE constraint on `canonical_entities(canonical_name, entity_type)`
9. **C-2** — Per-entity session in Phase 3 (or SAVEPOINT pattern)
10. **C-3** — Fix `EmbeddingRefreshWorker` to use 3-phase ARCH-003 pattern
11. **C-4** — Change all API key fields to `SecretStr`
12. **M-2** — Fix evidence unblocking to update both subject and object columns
13. **M-3** — Track `model_id` on `update_embedding()`

### Backlog
14-37: Remaining MAJOR, MINOR, NIT items

---

## Compounding Updates

### New Bug Patterns to Add
- **BP-313**: Kafka `mark_processed` before `uow.commit` — systematic at-least-once violation (DS-F-005)
- **BP-314**: Circuit breaker implemented but not wired in app factory (DS-F-006)
- **BP-315**: Non-deterministic `event_id` — INSERT idempotency lost on Kafka replay (DP-F-010)
- **BP-316**: Prometheus metric name mismatch between code and context docs (ARCH-F-012)

### HIGH_RISK_PATTERNS.md Updates
- HR-new: "Shared session across batch loop with per-item error handling — see C-2"
- HR-new: "asyncio.create_task without strong reference — task may be GC'd"

### REVIEW_CHECKLIST.md Updates
- Add: "Check that `entity.dirtied.v1` emit includes all required Avro envelope fields"
- Add: "Verify circuit breakers are instantiated and passed in app factory, not just defined"
- Add: "Check `mark_processed` is called AFTER `uow.commit`, not before"
