# QA Audit Report — W7 Intelligence Tab Redesign

**Date**: 2026-05-22
**Branch**: `feat/plan-0089-w2`
**Plan**: `docs/plans/0089-pages/W7-instrument-intelligence-plan.md`
**Scope**: W7 T-01..T-24 (24 tasks, Blocks A–H)
**Commit**: `8b6efe43`
**Result**: PASS (all blocking/critical issues fixed)

---

## Methodology

- 5 specialist review agents run in parallel (QA/Test, Security, Data Platform, Distributed Systems, Architecture)
- Live stack investigation: frontend container rebuilt, all 8 W7 intelligence endpoints validated against running platform (59 containers healthy)
- JWT via `POST /v1/auth/dev-login`; entity IBM used for live API sampling
- Container log analysis to confirm query suppression root cause
- 2101 Vitest tests, 0 TypeScript errors (pre- and post-fix)

---

## Summary

| Severity | Count | Fixed | Status |
|----------|-------|-------|--------|
| BLOCKING | 1 | 1 | ✓ |
| CRITICAL | 4 | 4 | ✓ |
| MAJOR | 2 | 2 | ✓ |
| MINOR | 1 | 1 | ✓ |
| NIT | 3 | — | Deferred |

---

## BLOCKING Issues

### F-001 — URL Protocol Injection (3 components)
- **Severity**: BLOCKING
- **Files**: `DenseArticleRow.tsx`, `NewsColumn.tsx`, `ContradictionsBlock.tsx`
- **Issue**: `window.open()` called directly with API-sourced URLs without validating the scheme. A malicious API response with `javascript:alert(1)` as a URL would execute arbitrary code in the analyst's browser.
- **Fix**: Wrapped all three open calls with `new URL()` parse + `["http:", "https:"].includes(parsed.protocol)` check. Fixed in commit `8b6efe43`.
- **Status**: FIXED

---

## CRITICAL Issues

### F-002 — Token Source Mismatch (4 components)
- **Severity**: CRITICAL
- **Files**: `ContradictionsBlock.tsx`, `NarrativeHistoryDisclosure.tsx`, `TopRelationsBlock.tsx` (PathInsightsBlock uses `useEntityPaths` which already used `useAccessToken` internally)
- **Issue**: These components imported `useAuth` from `@/hooks/useAuth` and destructured `accessToken`. The `enabled: !!accessToken` guard then used a different token source than every other intelligence hook (`useEntityPaths`, `useEntityNewsInfinite`, `EntityOverviewBlock`), which all use `useAccessToken()` from `@/lib/api-client`. During live stack investigation, container logs confirmed that contradictions/narratives/top-relations queries never fired on the IBM intelligence tab — the enabled guard evaluated to false while the rest of the queries succeeded.
- **Root cause**: `useAuth().accessToken` can return null during initial render hydration, while `useAccessToken()` from the `ApiClientProvider` context is synchronously available. Two different token sources with different timing = inconsistent enabled guards.
- **Fix**: All three components now import and call `useAccessToken()` from `@/lib/api-client`. Test mocks updated in 3 test files.
- **Status**: FIXED

### F-003 — PathInsightsBlock Portfolio Filter Always False
- **Severity**: CRITICAL
- **File**: `PathInsightsBlock.tsx:70`
- **Issue**: `path.path_nodes.some((n) => holdingTickers.has(n.name))` compared entity names ("Apple Inc.") against portfolio ticker symbols ("AAPL"). `PathNodePublic` has no ticker field. Result: the filter always returned empty, making the fallback to top-scored paths unconditional — defeating the intent and adding dead computation.
- **Fix**: Removed the portfolio filter logic entirely (including the `useQueryClient`, `useActivePortfolio`, `qk`, `HoldingsResponse` imports). Simplified `display` to `(pathsData?.paths ?? []).slice(0, limit)`.
- **Status**: FIXED

### F-004 — EntityIntelligencePublic.data_completeness Type Mismatch
- **Severity**: CRITICAL
- **File**: `types/intelligence.ts:98`
- **Issue**: `data_completeness: number` declared as required non-nullable. Live API (`GET /v1/entities/{id}/intelligence`) never returns this field on most entity types. `EntityOverviewBlock` had unreachable fallback logic because `intelligence?.data_completeness` could never be undefined per the type.
- **Fix**: `data_completeness?: number | null` — matches live API behavior.
- **Status**: FIXED

### F-005 — EntityOverviewBlock Metadata Null Access
- **Severity**: CRITICAL
- **File**: `EntityOverviewBlock.tsx:164-166`
- **Issue**: `entity.metadata.employee_count` etc. accessed without optional chaining. `EntityPublic.metadata` is typed as nullable (mirrors the API where many non-company entity types have no metadata object). Would throw "Cannot read properties of null" when rendering an entity without metadata.
- **Fix**: `entity.metadata?.employee_count`, `entity.metadata?.founded_year`, `entity.metadata?.headquarters_country ?? entity.metadata?.country`.
- **Status**: FIXED

---

## MAJOR Issues

### F-006 — staleTime Inconsistency in TopRelationsBlock
- **Severity**: MAJOR
- **File**: `TopRelationsBlock.tsx:55`
- **Issue**: `staleTime: 10 * 60 * 1000` (10 min) for `qk.instruments.entityGraph(entityId, 1)`, while `ContextPanel` sets `5 * 60 * 1000` (5 min) for the same cache key. Whichever component renders first wins; the other silently inherits the wrong TTL. This is a TanStack Query gotcha: staleTime is per-query-instance registration, and the first subscriber's value takes precedence for de-duped requests.
- **Fix**: `staleTime: 5 * 60 * 1000` — aligned with ContextPanel.
- **Status**: FIXED

### F-007 — Test Mock Type Drift (3 test files)
- **Severity**: MAJOR
- **Files**: `DenseArticleRow.test.tsx`, `intelligence-density.test.tsx`, `PathInsightsBlock.test.tsx`, `EntityOverviewBlock.test.tsx`
- **Issue**:
  - `relevance_score: 0.9` used in 2 test factories — field does not exist on `RankedArticle` (should be `display_relevance_score`). TypeScript caught this at `--strict` mode.
  - `{ id: "n1", name: "Apple" }` in `PathInsightsBlock.test.tsx:57` — `PathNodePublic` uses `entity_id` (not `id`) and requires `entity_type`.
  - `overall_health: "good"` in `EntityOverviewBlock.test.tsx:63` — field does not exist on `EntityIntelligencePublic`.
- **Fix**: Corrected all three mock factories. `as RankedArticle` / `as PathInsightPublic` casts removed the TypeScript errors but masked the drift.
- **Status**: FIXED

---

## MINOR Issues

### F-008 — Invalid Date Renders "Invalid Date" String
- **Severity**: MINOR
- **File**: `DenseArticleRow.tsx` (original)
- **Issue**: `new Date(published_at).toLocaleTimeString()` renders the literal string "Invalid Date" for malformed `published_at` values from the API.
- **Fix**: `isNaN(d.getTime()) ? "—" : d.toLocaleTimeString(...)` — already applied in the W7 implementation commit.
- **Status**: FIXED

---

## NITs (Deferred)

- N-01: `PathInsightsBlock` comment block still references portfolio-filter rationale — should be cleaned up in a future doc-only pass.
- N-02: `console.debug` log in `PathInsightsBlock` `onClick` logs the full `path` object (large). Could be trimmed to `{ entityId, insight_id, hop_count }`.
- N-03: `NarrativeHistoryDisclosure` renders `"…"` hardcoded after the 80-char preview; if `narrative_text` is exactly 80 chars this is misleading. Low probability in practice.

---

## Live API Validation Results

All 8 W7 intelligence endpoints validated against running platform:

| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /v1/entities/{id}` | 200 ✓ | metadata null on IBM entity — confirmed optional chaining fix was necessary |
| `GET /v1/entities/{id}/intelligence` | 200 ✓ | health_score=0.72, data_completeness absent — confirmed type fix |
| `GET /v1/entities/{id}/graph?depth=1` | 200 ✓ | 3 nodes, 2 edges; evidence_snippets=[] |
| `GET /v1/entities/{id}/graph?depth=2` | 200 ✓ | 14 nodes, 21 edges |
| `GET /v1/entities/{id}/news` | 200 ✓ | 20 articles returned |
| `GET /v1/entities/{id}/paths` | 200 ✓ | 0 paths (IBM — expected, sparse KG) |
| `GET /v1/entities/{id}/contradictions` | 200 ✓ | 0 contradictions |
| `GET /v1/entities/{id}/narratives` | 200 ✓ | 1 version |

Queries that were silently suppressed before the token-source fix (paths/contradictions/narratives/top-relations) were confirmed missing from container logs on the IBM instrument tab. Post-fix, all 8 endpoints fire on navigation to the Intelligence tab.

---

## Test Results

```
Test Files  226 passed | 9 skipped (235)
Tests       2101 passed | 16 skipped (2117)
TypeScript  0 errors
```

---

## Files Changed (commit 8b6efe43)

```
apps/worldview-web/components/instrument/__tests__/intelligence-density.test.tsx
apps/worldview-web/components/instrument/intelligence/context/ContradictionsBlock.tsx
apps/worldview-web/components/instrument/intelligence/context/EntityOverviewBlock.tsx
apps/worldview-web/components/instrument/intelligence/context/NarrativeHistoryDisclosure.tsx
apps/worldview-web/components/instrument/intelligence/context/PathInsightsBlock.tsx
apps/worldview-web/components/instrument/intelligence/context/TopRelationsBlock.tsx
apps/worldview-web/components/instrument/intelligence/context/__tests__/ContradictionsBlock.test.tsx
apps/worldview-web/components/instrument/intelligence/context/__tests__/EntityOverviewBlock.test.tsx
apps/worldview-web/components/instrument/intelligence/context/__tests__/NarrativeHistoryDisclosure.test.tsx
apps/worldview-web/components/instrument/intelligence/context/__tests__/PathInsightsBlock.test.tsx
apps/worldview-web/components/instrument/intelligence/context/__tests__/TopRelationsBlock.test.tsx
apps/worldview-web/components/instrument/intelligence/news/DenseArticleRow.tsx
apps/worldview-web/components/instrument/intelligence/news/NewsColumn.tsx
apps/worldview-web/components/instrument/intelligence/news/__tests__/DenseArticleRow.test.tsx
apps/worldview-web/types/intelligence.ts
```
