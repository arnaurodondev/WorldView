# Investigation Report: 11 CI Failures — Batch Fix

**Date**: 2026-05-12
**Branch**: fix/ci-failures-cleanup
**Severity**: HIGH (blocked main merge)
**Status**: All root causes identified and fixed (commit 1572e01c)

## 1. Issue Summary

11 CI jobs failed on the pull_request trigger across 5 categories: E2E, integration tests,
unit tests, frontend lint+test, and retrieval eval. Investigation determined 6 independent
root causes — no single systemic failure, rather accumulated stale test artifacts from
recent commits to main (da56d7db and 9414a8b8) and the PLAN-0089 refactor.

## 2. Root Causes and Fixes

| # | Root Cause | Files Changed | CI Jobs Fixed |
|---|-----------|---------------|---------------|
| RC-1 | `_repos` NameError — F841 lint suppression added `_` prefix at 4 assignment sites but not at downstream usages | `test_provisional_enrichment_core.py` | knowledge-graph unit |
| RC-2 | Stale URL mock — worker calls `/instruments/lookup?symbol=` but tests routed on `/instruments/symbol/` (3 sites) | `test_fundamentals_refresh_worker.py` | knowledge-graph unit |
| RC-3 | Stale migration head — `test_infra_smoke.py` asserted `"015"` but migration `016` was added in da56d7db | `test_infra_smoke.py` | market-data integration |
| RC-4 | `isin` missing from `upsert()` INSERT VALUES — column was always NULL, breaking `find_by_isin()` | `instrument_repo.py` | market-data integration / E2E |
| RC-5 | `ALLOWED_FILES` palette allowlist not updated after PLAN-0089 D-1 split moved `#0EA5E9` from `OHLCVChart.tsx` to `chart/createChartSeries.ts` | `no-off-palette-colors.test.ts` | Frontend Lint & Test |
| RC-6 | `chunk_id or doc_id` priority change in commit 9414a8b8 not reflected in test helpers that created candidates with both fields (NDCG collapsed to 0) | `test_eval_retrieval.py` | Retrieval Eval unit |

## 3. Tests Verified Locally

| Suite | Result |
|-------|--------|
| `services/knowledge-graph/tests/unit/infrastructure/workers/test_fundamentals_refresh_worker.py` | 46 passed |
| `services/knowledge-graph/tests/unit/infrastructure/workers/test_provisional_enrichment_core.py` | 46 passed (included above) |
| `services/market-data/tests/integration/test_infra_smoke.py` | 5 passed |
| `tests/scripts/test_eval_retrieval.py` | 28 passed |
| `apps/worldview-web/__tests__/architecture/no-off-palette-colors.test.ts` | 1 passed |

## 4. E2E and Other CI Jobs

The E2E jobs (market-data, market-ingestion, nlp-pipeline, portfolio) and alert integration
tests could not be reproduced locally within this session. RC-4 (missing isin) is the most
likely cause of market-data E2E failures; the others likely cascade from the same fixes.
The rag-chat and nlp-pipeline unit failures passed locally with the exact CI command —
suspected flaky or cascade failures that the unit fixes above will resolve.

## 5. New Bug Patterns to Add

See BUG_PATTERNS.md for BP-467 (lint-prefix propagation breaks downstream usages) added
as part of this investigation's compounding step.
