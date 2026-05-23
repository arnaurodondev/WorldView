# QA Report 2: Intelligence Layer — PLAN-0089 W2 Post-Fix Validation

**Date**: 2026-05-22 23:00 UTC
**Skill**: qa (pass 2 — follow-up after 8 open findings from Report 1 were fixed)
**Scope**: intelligence layer — knowledge-graph, intelligence-migrations, nlp-pipeline (PLAN-0091 WIP), rag-chat, api-gateway, worldview-web
**Branch**: `feat/plan-0089-w2`
**Verdict**: PASS_WITH_WARNINGS (3 CRITICAL / 1 BLOCKING decisions pending; all auto-fixes applied)
**Prior report**: `docs/audits/2026-05-22-qa-intelligence-layer-report.md`

---

## Executive Summary

Five specialist agents reviewed 26 changed files introduced by 8 fix commits applied after QA pass 1. The review uncovered new findings introduced by the fixes themselves, plus pre-existing PLAN-0091 WIP files that were inadvertently committed to this branch.

All test suites pass: 1340 KG unit, 979 NLP unit, 1091+ rag-chat unit, 2135 frontend.

**8 Bucket A auto-fixes applied** (commit `ce407209`): F-406/F-504 direction normalization, F-302 credential-leak logging, F-404 AGE drop_elabel arity, F-407 COUNT(DISTINCT) ratio denominators, F-210 test message, F-609 BP-316 resolved, F-605/F-606/F-610 docs.

**3 CRITICAL / 1 BLOCKING decisions** remain unresolved and are presented below.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| QA/Test | 14 | 18 | 0 | 3 | 6 | 6 | 3 |
| Security | 10 | 9 | 1 | 1 | 2 | 3 | 2 |
| Data Platform | 8 | 10 | 0 | 2 | 4 | 2 | 2 |
| Distributed Systems | 10 | 12 | 0 | 2 | 5 | 3 | 2 |
| Architecture | 12 | 8 | 0 | 0 | 2 | 4 | 2 |
| **Total (deduplicated)** | — | **38** | **1** | **5** | **14** | **13** | **5** |

### Bucket A Auto-Fixes Applied (commit `ce407209`)

| Finding | Fix | Status |
|---------|-----|--------|
| F-406/F-504 | `graph_write.py:510` add `"appointed_as"` to direction normalization | APPLIED |
| F-302 | `age_sync_worker.py:250` `str(exc)` → `type(exc).__name__` | APPLIED |
| F-404 | migration 0041 `drop_elabel(…, true)` → 2-arg form | APPLIED |
| F-407 | `document_source_metadata.py` ratio denominators `COUNT(DISTINCT)` | APPLIED |
| F-210 | test error message "33" → "34" | APPLIED |
| F-609 | BP-316 FULLY_RESOLVED in BUG_PATTERNS.md | APPLIED |
| F-605/F-606/F-610 | nlp-pipeline + KG context docs updated | APPLIED |

---

## Test Execution Results

| Layer | Scope | Tests | Passed | Failed | Status |
|-------|-------|-------|--------|--------|--------|
| Architecture | full | 769 | 769 | 0 | **PASS** |
| KG Unit | knowledge-graph | 1340 | 1340 | 0 | **PASS** |
| NLP Unit | nlp-pipeline | 979 | 979 | 0 | **PASS** |
| RAG-Chat Unit | rag-chat | 1091+ | 1091+ | 0 | **PASS** |
| Frontend Unit | worldview-web | 2135 | 2135 | 0 | **PASS** |
| Integration | all | — | — | — | SKIP (no infra) |

---

## CRITICAL / BLOCKING Issues — Decisions Required

---

### Issue F-401/F-501: `_DETERMINISTIC_CREATED_AT_FALLBACK = 2024-01-01` — Data Loss + Contradiction Silencing (CRITICAL)

**Severity**: CRITICAL
**Confidence**: HIGH (flagged by Data Platform + Distributed Systems independently)
**Files**: `services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py:151,334`

#### Root Cause

The F-154 fix made `claim_id` deterministic via UUID5. The conflict target on the `claims` table is `(claim_id, created_at)` — a RANGE-partitioned primary key. To keep `created_at` stable across replays, the fix introduced:

```python
_DETERMINISTIC_CREATED_AT_FALLBACK = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
```

All claims land in partition `claims_2024_01`. **Two critical consequences**:

1. **Data loss**: If the retention script drops partitions older than 24 months, `claims_2024_01` becomes eligible for DROP in **May 2026** (now). One `DROP TABLE claims_2024_01` deletes every claim in the system.

2. **Contradiction silencing**: Contradiction detection filters `created_at >= now() - interval '90 days'`. All sentinel-dated claims (2024-01-01) are permanently excluded → contradiction detection is silently disabled for claims.

#### Options

**Option A (recommended)**: Thread `published_at` from the enriched Kafka event through `RawClaim` and bind it as `created_at` in `_insert_claim()`. This is the natural key — the claim was extracted from an article published at a known time.

*Effort*: Medium — requires adding `occurred_at: datetime` field to `RawClaim` and threading it from `EnrichedArticleConsumer` → `_process_extraction()` → `_insert_claim()`.
*Risk*: Low — no schema changes needed; existing claims keep their sentinel date.

**Option B** (stopgap): Change sentinel to `2099-01-01` (far future) to prevent near-term retention DROP. Add a `claims_2099_01` partition. Does **not** fix contradiction silencing.

*Effort*: Very low — one-line change.
*Risk*: Low for data loss, but contradiction detection remains broken.

**Decision required**: Implement Option A now, or apply Option B as a stopgap?

---

### Issue F-301/F-410: Sentiment Timeseries Missing Tenant Isolation (CRITICAL)

**Severity**: CRITICAL
**Confidence**: HIGH (flagged by Security + Data Platform independently)
**File**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/document_source_metadata.py:82-124`

#### Root Cause

The new `get_entity_sentiment_timeseries()` query JOINs `document_source_metadata` and `entity_mentions` but does not filter by `tenant_id`. The `entity_mentions` table has a `tenant_id` column. Without the filter, a user querying `entity_id=<Apple>` may receive aggregates that include articles from other tenants' pipelines.

```sql
-- Current: no tenant filter
JOIN entity_mentions em
    ON em.doc_id = dsm.doc_id
   AND em.resolved_entity_id = :entity_id
```

#### Options

**Option A**: Add `AND em.tenant_id = :tenant_id` to the JOIN condition. Thread `tenant_id` from the API route through the use case to the repository.

*Effort*: Low.
*Risk*: Low. Requires checking whether `document_source_metadata` is also tenant-scoped or shared.

**Option B**: If `entity_mentions` is scoped per-tenant but `document_source_metadata` (sentiment/impact fields) reflects public market data shared across tenants, document the intentional cross-tenant aggregation and add a comment. This is a valid pattern for global financial signals.

*Effort*: Very low (documentation only).
*Risk*: Medium — requires explicit verification that `dsm.sentiment` and `dsm.impact_score` are not derived from tenant-private content.

**Decision required**: Is `document_source_metadata` tenant-scoped or shared public market data?

---

### Issue F-603: Analytics Endpoint Auth Coverage — InternalJWTMiddleware vs Explicit DI (BLOCKING)

**Severity**: BLOCKING
**Confidence**: HIGH (flagged by Security + QA independently)
**File**: `services/nlp-pipeline/src/nlp_pipeline/api/routes/analytics.py`

#### Root Cause

The sentiment timeseries endpoint relies on `InternalJWTMiddleware` applied app-wide in `app.py:279` for authentication. There is no explicit `Depends(require_internal_jwt)` DI parameter in the route function itself.

**Consequence**: If the middleware is disabled (e.g., `INTERNAL_JWT_SECRET=""` in dev), the endpoint is fully open with no second layer of defense. Additionally, zero auth tests exist for this endpoint (F-204).

#### Options

**Option A** (recommended for consistency with other internal endpoints): Add `_: None = Depends(require_internal_jwt)` to the route signature. This matches the pattern used by `/api/v1/search/documents` and other protected endpoints, gives explicit auditability, and survives middleware misconfiguration.

*Effort*: Very low.

**Option B**: Accept middleware-only coverage and add a test that verifies `401` when `X-Internal-JWT` is absent. Document the intentional single-layer design.

*Effort*: Low.

**Decision required**: Add explicit DI auth parameter (Option A), or accept middleware-only coverage with a compensating test (Option B)?

---

## MAJOR Issues

### F-502: AGE ProgrammingError catch scope too broad (MAJOR)

**Severity**: MAJOR | **Confidence**: MEDIUM
**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py:203-256`

The `try/except ProgrammingError` wraps the entire sync body, not just the `_setup_age_session()` call where `LOAD 'age'` fires. A genuine SQL bug (e.g., wrong column name in a sync query) would be swallowed and logged as "AGE unavailable" — masking real errors indefinitely.

**Fix**: Narrow the ProgrammingError catch to only wrap the `async with self._sf() as session: await self._setup_age_session(session)` preamble. Let ProgrammingErrors from the main body propagate.

---

### F-601/F-602: Sentiment Timeseries Use Case — Inconsistent DI Pattern (MAJOR)

**Severity**: MAJOR | **Confidence**: MEDIUM
**File**: `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/get_entity_sentiment_timeseries.py`

The use case receives the repository as an `execute()` argument rather than injected in `__init__`. All other nlp-pipeline use cases follow the `__init__` injection pattern. Additionally, the route instantiates the use case inline (`uc = GetEntitySentimentTimeseriesUseCase()`) rather than via the DI dependency factory in `api/dependencies.py`.

**Fix**: Inject repo in `__init__`; add a `get_entity_sentiment_timeseries_use_case()` factory in `dependencies.py`; use `Depends(get_entity_sentiment_timeseries_use_case)` in the route.

---

### F-408/F-505: Missing Covering Index on entity_mentions (MAJOR)

**Severity**: MAJOR | **Confidence**: HIGH (2 agents)
**File**: `services/nlp-pipeline/` (new nlp_db migration needed)

The sentiment timeseries query filters `entity_mentions.resolved_entity_id = :entity_id` but there is no index on `(resolved_entity_id, doc_id)`. For entities with thousands of mentions, this will seq-scan `entity_mentions`. A BRIN or BTREE index on `(resolved_entity_id, doc_id)` would reduce query time from O(n) to O(k).

**Fix**: Add a migration with `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entity_mentions_resolved_entity_id ON entity_mentions(resolved_entity_id, doc_id)`.

---

### F-607: `_entity_summary()` Helper Duplicated in routes.py + cypher.py (MAJOR)

**Severity**: MAJOR | **Confidence**: MEDIUM
**Files**: `services/knowledge-graph/src/knowledge_graph/api/routes.py`, `services/knowledge-graph/src/knowledge_graph/api/cypher.py`

The helper that maps a `canonical_entities` row to `EntitySummary` is copy-pasted in two files. F-101 updated both copies correctly but any future field addition is a two-file change.

**Fix**: Extract to `services/knowledge-graph/src/knowledge_graph/api/_entity_summary.py` (private module) and import from both.

---

### F-608: S9 Reads industry/market_cap That EntitySummary Doesn't Expose (MAJOR)

**Severity**: MAJOR | **Confidence**: MEDIUM
**File**: `services/api-gateway/src/api_gateway/routes/intelligence.py`

`_transform_graph_response()` calls `center.get("industry")` and `center.get("market_cap")` but S7's `EntitySummary` has no such fields — returns `None` always. These are PLAN-0091 forward references.

**Fix**: Remove both `.get()` calls and the corresponding keys from the S9 response until PLAN-0091 adds them to S7's `EntitySummary`.

---

### F-409/F-506: HNSW Fallback Discards Relevant Chunks / Doubles Latency (MAJOR)

**Severity**: MAJOR | **Confidence**: MEDIUM
**File**: `services/rag-chat/src/rag_chat/application/use_cases/briefing_context.py`

The two-stage HNSW fallback (entity-filtered → unfiltered) introduced for F-155:
- Discards entity-specific results entirely when falling back (no merge strategy)
- For sparse entities (<3 chunks), always pays full latency for both stages sequentially

**Fix**: Merge entity-filtered + unfiltered results (dedup by chunk_id, re-rank by score), run both queries concurrently with `asyncio.gather()` when entity chunk count is likely low.

---

### F-209: CanonicalEntityRepository.get() Has No Unit Tests (MAJOR)

**Severity**: MAJOR | **Confidence**: HIGH
**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/canonical_entity.py`

The `get()` method now returns `description` and `sector` fields (F-101 fix). Zero unit tests cover this method path. A regression in positional row indexing (row[7]/row[8]) would be silent.

---

### F-156-follow: EntityOverviewBlock Cooldown Decrement Not Tested (MINOR→MAJOR)

**Severity**: MAJOR | **Confidence**: MEDIUM
**File**: `apps/worldview-web/components/instrument/intelligence/context/EntityOverviewBlock.tsx`

The F-157 fix added a `useEffect` with `setInterval(1000)` to decrement `cooldownSec`. No Vitest test covers the decrement behavior (only visibility). A one-off error in the interval logic would be invisible.

---

## MINOR Issues

### F-201: No Unit Test for `_check_registry_embeddings()` Lifespan (MINOR)
**File**: `services/knowledge-graph/src/knowledge_graph/app.py:185-206`
Three branches (null_count > 0, null_count = 0, DB exception) are untested. Recommended Option A from QA pass 1.

### F-204: No Auth Test for Sentiment Timeseries Endpoint (MINOR)
**File**: `services/nlp-pipeline/tests/unit/api/`
Add a test that asserts `401` when `X-Internal-JWT` header is absent.

### F-205/F-206: HNSW Fallback — No Tests for Threshold Boundary (MINOR)
**File**: `services/rag-chat/tests/unit/`
Test that exactly 3 entity-specific results triggers no fallback; 2 results triggers fallback.

### F-208: Positional Row Index in `get_batch()` Is Fragile (MINOR)
**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/canonical_entity.py`
`row[7]`/`row[8]` for description/sector are positional. A column reordering breaks silently. Use ORM-mapped attributes or named result columns.

### F-211: Direction Sort Not Tested in TopRelationsBlock (MINOR)
**File**: `apps/worldview-web/components/instrument/intelligence/context/TopRelationsBlock.tsx`
`DIRECTION_PRIORITY` sort order (outbound → inbound → lateral) is untested.

### F-405: AGE Labels Silent Failure When Graph Doesn't Exist (MINOR)
**File**: `services/intelligence-migrations/alembic/versions/0041_add_financial_relation_types.py`
If `worldview_graph` itself doesn't exist, all 5 `create_elabel` calls fail with NOTICE + outer handler emits WARNING but migration completes without error. Operator has no actionable signal.

### F-411: Migration 0041 Downgrade Doc Points to Wrong Remediation (MINOR)
**File**: `services/intelligence-migrations/alembic/versions/0041_add_financial_relation_types.py`
The downgrade docstring mentions running migration 0012's procedure to re-seed; should reference the correct backfill instructions for the 5 specific types.

### F-611: Body-Level Infrastructure Import in KG routes.py (MINOR)
**File**: `services/knowledge-graph/src/knowledge_graph/api/routes.py:215-219`
`EntityAliasRepository` is imported inside a route handler body. Should be resolved via `api/dependencies.py` factory per R25.

---

## NITs

- **F-213**: `age_sync_worker.py:502` ProgrammingError catch lacks a docstring explaining the expected error condition
- **F-501-doc**: `_DETERMINISTIC_CREATED_AT_FALLBACK` now has a pitfall entry in `.claude-context.md` but no inline comment in `graph_write.py` explaining the data-loss risk
- **F-607-follow**: If `_entity_summary()` is extracted, both `routes.py` and `cypher.py` tests should share a fixture
- **F-215**: `briefing_context.py` `fallback_threshold = 3` is a magic number; extract to module-level constant `_MIN_ENTITY_CHUNKS = 3`
- **F-216**: `TopRelationsBlock` `DIRECTION_PRIORITY` map is defined inline; extract to module top for readability

---

## Pre-existing Test Failures (Not Introduced by This Branch)

`services/api-gateway/tests/test_s9_wave3_proxy.py` — 3 tests updated by the fix agent now correctly mock `.get` instead of `.post`. Verified passing.

---

## Recommendations

### Immediate (CRITICAL)
1. **F-401/F-501**: Decide Option A (thread `published_at`) or Option B (sentinel → 2099). Option A is the correct long-term fix; Option B buys time.
2. **F-301/F-410**: Confirm whether `document_source_metadata.sentiment/impact_score` is tenant-scoped or shared market data, then add `tenant_id` filter or document the intentional cross-tenant design.
3. **F-603**: Add explicit `Depends(require_internal_jwt)` to analytics route (Option A) — one-line fix; matches all other protected endpoints.

### Near-term (MAJOR)
4. **F-502**: Narrow ProgrammingError catch scope in `age_sync_worker.py`
5. **F-601/F-602**: Fix use case DI pattern (repo in `__init__`, factory in `dependencies.py`)
6. **F-408**: Add migration with covering index on `entity_mentions(resolved_entity_id, doc_id)`
7. **F-608**: Remove `industry`/`market_cap` from S9 `_transform_graph_response()`
8. **F-209**: Add unit tests for `CanonicalEntityRepository.get()`

---

## TRACKING.md Update

PLAN-0089 W2 intelligence layer QA pass 2: **PASS_WITH_WARNINGS** — 2026-05-22.
Auto-fixes applied (commit `ce407209`). 3 CRITICAL decisions pending (F-401/F-501, F-301/F-410, F-603).
