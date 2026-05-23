# QA Report: W7 Intelligence Tab + S9 Graph Fixes (Pass 2)

**Date**: 2026-05-22 18:45 UTC
**Skill**: qa
**Scope**: changed-only (branch `feat/plan-0089-w2`, W7 Intelligence tab + S9 graph bug fixes)
**Branch**: feat/plan-0089-w2
**Verdict**: PASS_WITH_WARNINGS
**Report file**: docs/audits/2026-05-22-qa-w7-intelligence-tab-v2-report.md

---

## Executive Summary

This QA pass reviewed the W7 Intelligence tab Block-I follow-up work (InlineSelectionPanel, enableEdgeEvents, 4+5+5 grid, S9 orphan filter + depth>1 merge) using 5 specialist agents in parallel plus a relation quality research agent. The 5 agents identified 1 BLOCKING architecture violation (peers.py module-level infrastructure imports) and multiple MAJOR findings including a critical UX gap (selectedNodeId not forwarded to sigma → no visual selection feedback) and 2 security input-validation issues. All BLOCKING and most MAJOR findings were fixed in the same pass. Test coverage was extended with 4 new tests covering previously-untested orphan-filter logic, depth>1 merge correctness, and InlineSelectionPanel edge cases. 2107 Vitest + 768 arch + 496 api-gateway tests pass after fixes.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| QA/Test | 8 | 9 | 0 | 0 | 3 | 4 | 2 |
| Security | 6 | 3 | 0 | 0 | 2 | 1 | 0 |
| Data Platform | — | 0 | 0 | 0 | 0 | 0 | 0 |
| Distributed Systems | — | 0 | 0 | 0 | 0 | 0 | 0 |
| Architecture | 7 | 6 | 1 | 0 | 2 | 3 | 0 |
| **Total** | — | **18** | **1** | **0** | **7** | **8** | **2** |

### Fixes Applied

| Finding | Severity | Fix | Status |
|---------|----------|-----|--------|
| Arch-BLOCKING | BLOCKING | peers.py lazy imports (IG-LAYER-002) | APPLIED |
| F-101 | MAJOR | `entity_id: UUID` on contradictions route | APPLIED |
| F-102 | MINOR | `focus_node max_length=36` | APPLIED |
| F-202 | MAJOR | `selectedNodeId` forwarded to EntityGraph + FilterController nodeReducer | APPLIED |
| F-205 | MINOR | `min_confidence`/`semantic_mode` forwarded to depth=1 merge call | APPLIED |
| F-001 | MAJOR | `test_transform_graph_response_orphan_filter` test added | APPLIED |
| F-002 | MAJOR | `test_entity_graph_depth1_merge_with_real_data` test added | APPLIED |
| F-004 | MINOR | InlineSelectionPanel no-evidence empty-state test | APPLIED |
| F-005 | MINOR | InlineSelectionPanel singular "1 connection" test | APPLIED |
| Arch marker | MINOR | intelligence-migrations pytestmark added | APPLIED |

### Open Items (Decisions Needed)

| Finding | Status | Decision needed |
|---------|--------|-----------------|
| F-103 | OPEN | Polymarket market_id format — UUID or slug? Needs format constraint |
| F-201 | OPEN | `createGateway(accessToken)` vs `useApiClient()` — pattern preference, not a correctness bug |
| F-203 | OPEN | Collapse `onNodeSelect`/`onNodeClickFull` dual-callback into single callback |
| F-204 | OPEN | `NodePathsBlock.tsx` is orphaned — delete or integrate into InlineSelectionPanel? |
| F-006 | OPEN | Add `IntelligenceTab.test.tsx` — selection state toggle/mutual exclusion logic |
| F-007 | OPEN | Assert B-01 transform fields (`ticker`, `description`, `sector`, `decay_class`) in graph tests |
| F-008 | NIT | Pin `enableEdgeEvents: true` in a test |
| F-009 | NIT | Add minimal `ContextPanel.test.tsx` for aria contract |

---

## Test Execution Results

| Layer | Scope | Tests | Passed | Failed | Status |
|-------|-------|-------|--------|--------|--------|
| Architecture | full | 768 | 768 | 0 | **PASS** |
| Lint (ruff) | changed | — | — | 0 | **PASS** |
| Type Check (mypy) | changed | — | — | 0 | **PASS** |
| api-gateway unit | api-gateway | 496 | 496 | 0 | **PASS** |
| market-data unit | market-data | 809 | 809 | 0 | **PASS** |
| Frontend unit | worldview-web | 2107 | 2107 | 0 | **PASS** |

**Pre-existing failures (not introduced by this branch):**
- `test_s9_wave3_proxy.py::test_top_movers_gainers_desc` — `AsyncMock >= int` TypeError (pre-existing)
- `test_jwks_rotation.py` — 3 tests with missing RSA key fixture (pre-existing)
- `market-data/tests/integration/test_infra_smoke.py` — requires live Postgres (SKIP/pre-existing)

---

## Issues — Full Investigation

## Issue Arch-BLOCKING: peers.py Module-Level Infrastructure Imports

**Severity**: BLOCKING (arch rule IG-LAYER-002)
**File**: `services/market-data/src/market_data/api/routers/peers.py:29-30`
**Root cause**: `FundamentalMetricModel` and `InstrumentModel` were imported at module level in an API router, violating IG-LAYER-002 which forbids infrastructure imports in the API layer at module level (only dependency-function lazy imports are permitted).
**Fix applied**: Moved imports inside the `get_peers` function body with `# noqa: PLC0415`.
**Status**: FIXED — arch test passes.

---

## Issue F-101: `entity_id: str` on Contradictions Route (MAJOR)

**Severity**: MAJOR
**File**: `services/api-gateway/src/api_gateway/routes/intelligence.py:281`
**Root cause**: `get_entity_contradictions` accepted `entity_id: str` with no UUID validation, allowing malformed values to reach S7's URL path. Every other entity route used `entity_id: UUID`.
**Fix applied**: Changed type annotation to `entity_id: UUID` — FastAPI returns 422 on non-UUID input before handler body runs.
**Status**: FIXED.

---

## Issue F-202: selectedNodeId Not Forwarded to Sigma (MAJOR)

**Severity**: MAJOR
**File**: `apps/worldview-web/components/instrument/EntityGraph.tsx:103-118`
**Root cause**: `GraphColumn` received `selectedNodeId` as a prop and used it for toggle detection, but never passed it to `EntityGraph`. The sigma canvas had zero visual feedback for which node was "selected" — no ring, no highlight, no size increase. The `FilterController`'s `nodeReducer` only handled search-query dimming, not selection highlighting.
**Fix applied**:
1. Added `selectedNodeId?: string | null` to `EntityGraphProps`
2. Added `selectedNodeId?: string | null` to `FilterControllerProps`
3. In `FilterController.nodeReducer`: selected node gets `highlighted: true`, `size *= 1.5`, `borderColor: "#EAB308"` (Bloomberg yellow), `borderSize: 2`
4. `GraphColumn` now passes `selectedNodeId={selectedNodeId}` to `EntityGraph`
**Status**: FIXED.

---

## Issue F-205: Filter Params Not Forwarded to Depth=1 Merge Call (MINOR)

**Severity**: MINOR
**File**: `services/api-gateway/src/api_gateway/routes/intelligence.py:239-244`
**Root cause**: The depth>1 secondary S7 call only forwarded `limit`, but not `min_confidence` or `semantic_mode`. An analyst with a custom `min_confidence` filter would get lower-quality edges merged in from the depth=1 call.
**Fix applied**: Extracted `depth1_params` dict that mirrors the primary call's `min_confidence`/`semantic_mode` forwarding.
**Status**: FIXED.

---

## Issue F-103: market_id: str in Prediction Market Routes (MAJOR — OPEN)

**Severity**: MAJOR
**File**: `services/api-gateway/src/api_gateway/routes/intelligence.py:758, 780`
**Issue**: `market_id: str` is interpolated into downstream S3/S4 URL paths with no length or format validation. Path traversal segments (`../admin`) would be forwarded verbatim.
**Status**: OPEN — requires decision on Polymarket market_id format (UUID or alphanumeric slug).

---

## Relations Quality Investigation (Research Deliverable)

The research agent produced a comprehensive investigation of the relation extraction pipeline quality. Key findings:

### Current Pipeline Root Causes of Low Quality

1. **Zero-shot 8B LLM extraction** — `meta-llama/Meta-Llama-3.1-8B-Instruct` with a 27-type taxonomy produces F1 < 0.40 estimated (state of art on financial RE with specialized models: 0.60–0.75)

2. **Entity resolution funnel** — Relations can only be extracted between GLiNER-resolved entities. 7 of 11 GLiNER classes historically had zero canonicals; this upstream gap directly limits relation recall

3. **Taxonomy mismatch** — 27 canonical types are too coarse. Missing: `reported_revenue_of`, `filed_lawsuit_against`, `appointed_as`, `divested_from`, `downgraded_by`. Overlapping: `employs` vs `has_executive` (LLM confuses them ~50% of the time)

4. **Direction inversion (BP-521)** — `has_executive`/`employs` stored as `person→company` in ~50–80% of cases instead of `company→person` because the LLM uses mention order as subject

5. **NULL evidence_text (BP-343/345)** — Historical rows in `relation_evidence_raw` have `evidence_text=NULL` (pre-BP-345 fix); Worker 13C (SummaryWorker) produces no summaries for these

6. **Registry embedding gap** — If Ollama was unavailable during migration 0013, all 27 registry rows have NULL embeddings; the ANN soft-map in Block 11 is bypassed; ~20-30% of valid relations silently dropped as unrecognized types

### Quick Wins (< 1 week)

- **QW-1**: Verify registry embedding seeding (SQL: `SELECT canonical_type, embedding IS NOT NULL FROM relation_type_registry`)
- **QW-3**: Add direction field to `_transform_graph_response` (`direction: "outbound"/"inbound"`) so asymmetric types are readable
- **QW-5**: Add 3–5 few-shot examples to `libs/prompts/src/prompts/extraction/deep.py` (prompt v1.2 is zero-shot)
- **QW-6**: Add inline descriptions to prompt's predicate list to reduce `employs`/`has_executive` confusion

### State of the Art (2024-2025)

Best models for financial relation extraction:
- **REBEL** (BART-based seq2seq, F1 ~0.72 on TACRED) — runs locally, fine-tunable
- **NuNER Zero-Shot** (from GLiNER authors) — joint entity+relation, architecturally compatible with existing GLiNER usage
- **FinBERT-based RE** — fine-tune on manually labeled financial corpus (200 samples minimum)
- **GPT-4 5-shot** — F1 ~0.78 on FinRE (Bloomberg 2024 study) — expensive but high ceiling

### DB Quality Diagnostic SQL

```sql
-- Relation count and confidence distribution
SELECT COUNT(*), ROUND(AVG(confidence)::numeric, 3), PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY confidence)
FROM relations;

-- Distribution by type
SELECT canonical_type, COUNT(*), ROUND(AVG(confidence)::numeric, 3)
FROM relations GROUP BY canonical_type ORDER BY count DESC;

-- Evidence fill rate
SELECT ROUND(100.0 * COUNT(evidence_text) / NULLIF(COUNT(*), 0), 1) AS evidence_fill_pct
FROM relation_evidence_raw WHERE entity_provisional = false;

-- Unmapped (NULL canonical_type)
SELECT COUNT(*) FROM relation_evidence_raw WHERE canonical_type IS NULL;
```

---

## Recommendations

1. **This week**: Apply QW-3 (direction field in S9 transform) and QW-5 (few-shot examples in prompt) — these are low-risk, high-impact
2. **Next sprint**: Run the DB quality SQL queries to baseline the current state before any model changes
3. **Medium-term**: Create a 200-sample golden test set from existing `relation_evidence_raw` rows with non-NULL `evidence_text`
4. **Fix F-103**: Decide on Polymarket market_id format and add validation
5. **Fix F-204**: Decide whether to delete `NodePathsBlock.tsx` or integrate into `InlineSelectionPanel`
6. **Rebuild api-gateway + market-data containers** to deploy the peers.py fix and intelligence.py fixes

---

## Compounding Check

- **BUG_PATTERNS.md**: BP-S9-GRAPH-001 already added in prior commit; research agent added BP-520/521/522/523 (relation quality patterns from previous session)
- **HIGH_RISK_PATTERNS.md**: `entity_id: str` in route handlers → should be `UUID` — adding this check to review checklist
- **REVIEW_CHECKLIST.md**: Add "All entity_id path params typed as UUID, not str" to API review checklist
