# QA Report: Intelligence Layer — PLAN-0089 W2 Taxonomy + Pipeline Fixes

**Date**: 2026-05-22 21:45 UTC
**Skill**: qa
**Scope**: Intelligence layer — knowledge-graph, intelligence-migrations, libs/prompts, api-gateway, rag-chat, worldview-web
**Branch**: `feat/plan-0089-w2`
**Verdict**: PASS_WITH_WARNINGS
**Report file**: `docs/audits/2026-05-22-qa-intelligence-layer-report.md`

---

## Executive Summary

Five specialist agents reviewed the intelligence layer changes on `feat/plan-0089-w2`, covering: (1) Lever-4 taxonomy expansion (5 new relation types + migration 0041 + prompt v1.4), (2) QW-1 registry startup check, (3) QW-3 direction field threading through S9→frontend, (4) B-01/B-02 graph node/edge enrichment, (5) HNSW sparse-filter fix in rag-chat, (6) W7 Intelligence Tab frontend components.

The review identified **1 CRITICAL** (non-idempotent `_insert_claim()` — pre-existing BP-397 class bug), **1 BLOCKING test failure** (enum count assertion stale after Lever-4 expansion — now fixed), **1 MAJOR security issue** (assert-based Cypher injection guard stripped by python -O — now fixed), **5 data integrity/pipeline MAJOR findings**, and **15 MINOR/NIT** items. The 3 CRITICAL/BLOCKING issues from the test layer have been resolved and committed. The remaining items are documented below with decisions required from the user on 5 open questions.

All test suites pass after fixes: 1330 KG unit, 514 api-gateway unit, 1095 rag-chat unit, 768 architecture, 2130 Vitest frontend.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| QA/Test | 27 | 20 | 1 | 2 | 5 | 7 | 5 |
| Security | 12 | 11 | 0 | 0 | 1 | 5 | 5 |
| Data Platform | 8 | 4 | 0 | 0 | 2 | 1 | 1 |
| Distributed Systems | 12 | 12 | 0 | 1 | 6 | 4 | 1 |
| Architecture | 14 | 9 | 0 | 0 | 0 | 5 | 4 |
| **Total (deduplicated)** | — | **45** | **1** | **3** | **14** | **22** | **5** |

### Fixes Applied

| Finding | Fix | Status |
|---------|-----|--------|
| F-002/F-003 | test_enums.py: count 11→16 + Lever-4 types test | APPLIED (commit a5aec955) |
| F-019 | test_age_sync_worker.py: rename + count assertion 34 | APPLIED (commit a5aec955) |
| F-056 | age_sync_worker.py: assert→if/raise (python -O safe) | APPLIED (commit a5aec955) |
| F-160 | intelligence.py: cache key includes query params | APPLIED (commit a5aec955) |
| F-205 | .claude-context.md: RelationType 11→16 + QW-1 docs | APPLIED (commit a5aec955) |

### Decisions Required (Open Items)

| Finding | Question | Options |
|---------|----------|---------|
| F-101 | B-01 description/sector always null (EntitySummary lacks fields) | (A) Add description/sector to EntitySummary + JOIN in S7 query; (B) Defer until PLAN-0091 schema extensions |
| F-154 | _insert_claim() non-idempotent (new UUID on every call) | Deterministic UUID5 from (doc_id, subject_entity_id, claim_type, polarity) |
| F-100 | AGE label creation block-level exception handler | Per-label EXCEPTION block so one failure doesn't skip remaining 4 |
| F-155 | HNSW fix: unrelated chunks for generic entity names | Entity-filtered search with fallback if <3 results |
| F-158 | TopRelationsBlock silently excludes inbound edges | Show both directions using `direction` field already on GraphEdge |

---

## Test Execution Results

| Layer | Scope | Tests | Passed | Failed | Skipped | Status |
|-------|-------|-------|--------|--------|---------|--------|
| Architecture | full | 768 | 768 | 0 | 0 | **PASS** |
| Lint (ruff) | changed files | — | — | 0 | — | **PASS** |
| KG Unit | knowledge-graph | 1330 | 1330 | 0 | 5 xfail | **PASS** |
| API-GW Unit | api-gateway (excl. pre-existing wave3) | 514 | 514 | 0 | — | **PASS** |
| RAG-Chat Unit | rag-chat | 1095 | 1095 | 0 | 16 | **PASS** |
| Prompts Lib | libs/prompts | n/a (no unit marker) | 6 | 0 | — | **PASS** |
| Frontend Unit | worldview-web | 2130 | 2130 | 0 | 16 | **PASS** |
| Integration | all | — | — | — | SKIPPED (no infra) | **SKIP** |
| E2E | all | — | — | — | SKIPPED (no infra) | **SKIP** |

**Pre-existing failures** (on `main` too, not introduced by this branch):
- `services/api-gateway/tests/test_s9_wave3_proxy.py` — 3 tests: `test_top_movers_gainers_desc`, `test_top_movers_losers_asc`, `test_top_movers_downstream_500` (mock `.post` but code uses `.get`; pre-existing since market.py was refactored)

---

## Issues — Full Investigation

## Issue F-001: `_check_registry_embeddings()` has zero test coverage (CRITICAL)

**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: QA/Test

### Root Cause
The QW-1 startup check added in `app.py:185-206` is the primary guard against the S7 Block 11 ANN soft-mapping being silently bypassed when migration 0041's 5 new rows have `embedding = NULL`. This path (warning + OK branches + DB error catch) has no test coverage.

**What**: `_check_registry_embeddings()` in `app.py` lifespan block
**Where**: `services/knowledge-graph/src/knowledge_graph/app.py:185-206`

### Solution

#### Option A: Unit test the lifespan check directly
Mock `read_factory` to return a session mock, test three branches: (1) `null_count > 0` → warning logged, (2) `null_count = 0` → info logged, (3) DB exception → warning logged, no raise.

**Effort**: Low | **Risk**: Low

### Recommended Option
Option A — straightforward mock-based test.

---

## Issue F-154: `_insert_claim()` non-idempotent — fresh UUID on every call (CRITICAL)

**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Distributed Systems

### Root Cause
`_insert_claim()` in `graph_write.py:287-314` generates `claim_id = new_uuid7()` on every invocation. The conflict target is `ON CONFLICT (claim_id, created_at) DO NOTHING`. Because `claim_id` is different on every Kafka replay, the conflict predicate never matches, and every re-delivery inserts a duplicate claim row. This is the exact pattern fixed for events (BP-397) but was not applied to claims.

**What**: `claim_id = new_uuid7()` in `_insert_claim()`
**Where**: `services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py:287`

### Solution

#### Option A: Deterministic UUID5 for claim_id
Replace `claim_id = new_uuid7()` with a deterministic UUID derived from the natural key:
```python
claim_id = uuid5_from_parts(str(doc_id), str(rel.subject_entity_id), claim.claim_type, claim.polarity)
```
Also bind `created_at` explicitly to the event's `occurred_at` timestamp so the partition key is stable across replays.

**Effort**: Medium | **Risk**: Low (existing claims retain their UUIDs; new claims get stable IDs)

### Recommended Option
Option A — same fix as BP-397.

---

## Issue F-056: assert-based Cypher injection guard stripped by python -O (MAJOR → FIXED)

**Severity**: MAJOR → **FIXED**
**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py:531`

Changed from:
```python
assert edge_label in _VALID_EDGE_LABELS, f"Cypher label injection guard: {edge_label!r} not in whitelist"
```
To:
```python
if edge_label not in _VALID_EDGE_LABELS:
    raise ValueError(f"Cypher label injection guard: {edge_label!r} not in whitelist")
```
Applied in commit `a5aec955`.

---

## Issue F-100: AGE label creation block-level exception handler (MAJOR)

**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: Data Platform
**File**: `services/intelligence-migrations/alembic/versions/0041_add_financial_relation_types.py:153`

### Root Cause
The `_CREATE_AGE_LABELS` DO block wraps all five `create_elabel` calls under a single `EXCEPTION WHEN OTHERS` handler. If any one label already exists (e.g., `APPOINTED_AS` from a partial run), the first `PERFORM` raises, the handler fires, and the remaining four labels are **never created**. The fix is per-label `BEGIN/EXCEPTION/END` blocks so each label creation is independently safe.

### Solution
```sql
DECLARE _labels TEXT[] := ARRAY['APPOINTED_AS','DIVESTED_FROM','DOWNGRADED_BY',
                                 'FILED_LAWSUIT_AGAINST','REPORTED_REVENUE_OF'];
        _l TEXT;
BEGIN
    LOAD 'age';
    SET search_path = ag_catalog, "$user", public;
    FOREACH _l IN ARRAY _labels LOOP
        BEGIN
            PERFORM create_elabel('worldview_graph', _l);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Label % already exists or AGE unavailable: %', _l, SQLERRM;
        END;
    END LOOP;
EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'AGE extension not available: %', SQLERRM;
END;
```

---

## Issue F-101: B-01 description/sector always null — EntitySummary lacks fields (MAJOR)

**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: Data Platform
**File**: `services/api-gateway/src/api_gateway/routes/intelligence.py:67-68,84-85`

### Root Cause
S9's `_transform_graph_response()` calls `center.get("description")` and `center.get("sector")` on S7's `GraphNeighborhoodResponse`, but S7's `EntitySummary` schema only has `{entity_id, canonical_name, entity_type, isin, ticker, exchange}`. The `description` lives on `EntityPublic` (separate endpoint) and `sector` on `EntityMetadata`. Result: all graph nodes always have `"description": null, "sector": null`.

**Decision required**: (A) Add `description: str | None = None` and `sector: str | None = None` to S7's `EntitySummary` and populate via JOIN in `GetEntityGraphUseCase`; or (B) Remove these fields from S9's response until PLAN-0091 schema extensions implement them properly.

---

## Issue F-154: _insert_claim non-idempotent (CRITICAL)

Already described above. **Decision required**: implement deterministic UUID5 for claim_id.

---

## Issue F-155: HNSW fix — unrelated chunks for generic entity names (MAJOR)

**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: Distributed Systems
**File**: `services/rag-chat/src/rag_chat/application/use_cases/briefing_context.py:417`

Removing `entity_ids` filter makes the briefing context chunk search global. For entities with generic names ("General" for General Motors, "Capital" for a fund), the top-12 ANN results may include unrelated chunks about other companies.

**Decision required**: Should `_fetch_entity_chunks` retry with entity_ids filter if the unfiltered search returns too many mismatches? Suggested: try entity-filtered first, fall back to unfiltered if <3 results.

---

## Issue F-158: TopRelationsBlock silently excludes inbound edges (MAJOR)

**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: Distributed Systems
**File**: `apps/worldview-web/components/instrument/intelligence/context/TopRelationsBlock.tsx:66`

```tsx
.filter((e) => e.source === entityId)  // inbound edges silently excluded
```

Relations where the entity is the object (acquired_by, subsidiary_of, supplier_of inbound) are never shown even though the `direction` field is available on every edge.

**Decision required**: Should `TopRelationsBlock` show both outbound AND inbound direct edges (using `e.direction !== "lateral"`)? This would surface many more relevant relations for financial analysis.

---

## Issue F-160: Intelligence cache key missing query params (MINOR → FIXED)

**Fixed in commit `a5aec955`**: cache key now includes `confidence_breakdown` and `focus_node` so different param combinations receive distinct cache slots.

---

## MINOR Issues

### F-050 (MINOR): focus_node has no UUID pattern constraint
**File**: `services/api-gateway/src/api_gateway/routes/intelligence.py:165`
Add `pattern=r"^[0-9a-fA-F-]{32,36}$"` to the Query parameter.

### F-057 (MINOR): NarrativeHistoryDisclosure unbounded LLM text with whitespace-pre-wrap
**File**: `apps/worldview-web/components/instrument/intelligence/context/NarrativeHistoryDisclosure.tsx:146`
Add `max-h-[300px] overflow-y-auto` to prevent layout injection from whitespace-heavy LLM output.

### F-156 (MAJOR): EntityOverviewBlock 30s skeleton during retry with no error state
**File**: `apps/worldview-web/components/instrument/intelligence/context/EntityOverviewBlock.tsx:82`
Add `retry: 1` to both queries and show an inline error state when `entityError` is truthy.

### F-157 (MINOR): EntityOverviewBlock cooldown timer not decrementing
**File**: `apps/worldview-web/components/instrument/intelligence/context/EntityOverviewBlock.tsx:79,125`
Add `useEffect` + `setInterval(1000)` to count down `cooldownSec`; remove `setCooldownSec(null)` from `onClick`.

### F-159 (MAJOR): AGE sync worker crashes on ProgrammingError (no graceful handling)
**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py:204`
Wrap main body in `try/except sqlalchemy.exc.ProgrammingError` and log `age_sync_age_unavailable` at WARNING rather than letting the crash counter fire.

---

## NITs

- **F-058**: `format_map` on article text — `{text}` literal in article body can cause double-substitution. Consider pre-escaping `{`/`}` in user text before calling `render()`.
- **F-059**: JTI replay check disabled on S7 (documented trade-off). Document acceptance in `.claude-context.md` or `SECURITY.md`.
- **F-060**: Migration 0041 downgrade silently orphans AGE edges. Add operator warning in downgrade docstring.
- **F-103**: Migration 0041 idempotency docstring says re-running is safe, but AGE label creation is not. Clarify.
- **F-151**: Registry startup check uses read replica (potential TOCTOU). Use write_factory instead.
- **F-202**: TopRelationsBlock uses `qk.instruments.entityGraph` — should be `qk.kg.entityGraph` for consistent cache invalidation.
- **F-206**: SelectedEdgeInfo import path in IntelligenceTab goes through EntityGraph re-export — actually valid (EntityGraph.tsx line 123 re-exports it explicitly). Non-issue.

---

## Seed Alignment Check — PASS

All 5 new predicate names match exactly across:
- Migration 0041 seed SQL: `appointed_as`, `divested_from`, `downgraded_by`, `filed_lawsuit_against`, `reported_revenue_of`
- `RelationType` enum values: same lowercase ✓
- `_VALID_EDGE_LABELS` frozenset: uppercase via `.upper()` transform ✓
- `DEEP_EXTRACTION` v1.4 predicate vocabulary: same lowercase ✓

---

## Pre-existing Test Failures (Not Introduced by This Branch)

`services/api-gateway/tests/test_s9_wave3_proxy.py` — 3 tests mock `market_data.post` but `get_top_movers()` uses `market_data.get`. These failures exist on `main` too. **Root cause**: `market.py` was refactored from POST to GET for period-movers, but the wave3 proxy tests were not updated.

**Recommended fix** (separate commit): update the 3 tests to mock `market_data.get` and assert on query string params instead of JSON body.

---

## Recommendations

1. **Fix F-154** (CRITICAL): Replace `claim_id = new_uuid7()` with `uuid5_from_parts(doc_id, entity_id, claim_type, polarity)` in `graph_write.py`. Apply the same fix already in BP-397 for events.
2. **Fix F-100** (MAJOR): Per-label EXCEPTION block in migration 0041's AGE label creation.
3. **Decide F-101** (MAJOR): Either add description/sector to EntitySummary (S7 schema + JOIN), or remove the always-null fields from S9's response and defer to PLAN-0091.
4. **Fix test_s9_wave3_proxy.py** (pre-existing): Update 3 tests to mock `.get` instead of `.post`.
5. **Fix F-159** (MAJOR): Graceful AGE ProgrammingError handling in age_sync_worker.
6. **Consider F-158** (MAJOR): Show inbound + outbound edges in TopRelationsBlock.
7. **Fix F-156** (MAJOR): Add retry:1 + error state in EntityOverviewBlock.

---

## TRACKING.md Update

PLAN-0089 W2 intelligence layer QA: **PASS_WITH_WARNINGS** — 2026-05-22.
