# PLAN-0097 Revision Report

**Date**: 2026-05-27 · **Plan**: `docs/plans/0097-iter-9-followups-and-quality-plan.md` · **Before**: `draft`, 10 `<TBD>` · **After**: `revised`, 0 placeholders, 4 audits folded.

## Changes

- Status `draft → revised`; source-audits flipped IN-FLIGHT → FOLDED; §0 open questions resolved.
- §3 verification table: every `<TBD>` replaced — HIGHLIGHTS leak `get_fundamentals_history.py:94-97`; classifier prompt `llm_injection_classifier.py:61-93`; grader `grading.py:352-354,337-360,413-416`; AGE `age_sync_worker.py:516-525`; sentinel SQL `news_query.py:139`; tautological tests `test_fundamentals_query_defaults.py:57-122`.
- Wave re-balancing per spec:
  - P2#2 (period_type integration test) **W4 → W1** as T-W1-04.
  - P2#5 (batch endpoint exception sanitization) **W4 → W3**, absorbed into T-W3-02 (same `fundamentals.py` as parallel-verify).
  - T-W3-04 (`DEBUG_SKIP_CLASSIFIER`) **W3 → W2** as T-W2-04 — W2 owns `llm_injection_classifier.py` end-to-end.
  - W4 final: items 1, 3 (NEW migration 023), 4, 6, docs 7–10.
- T-W1-02 rewritten to ship **new** `FundamentalsRefreshWorker` + one-shot backfill (audit §B confirmed worker absent).
- T-W1-01 narrowed to HIGHLIGHTS docstring + assertion + periodicity tag (no migration).
- Migration sequencing 022 (W3 VACUUM autocommit_block) → 023 (W4 IF NOT EXISTS retrofit).
- Acceptance gate (§5): `p99 < 60 s with RAG_COMPLETION_CACHE_DISABLED=true AND DEBUG_SKIP_CLASSIFIER=true APP_ENV=dev` — eval-mode, NOT production SLO.
- Per-wave test coverage matrices added.

## Inconsistencies caught

1. Grader file: `grader.py` → actual `grading.py`.
2. BP collisions: audits proposed BP-562/563/567/568 — all four taken. Renumbered to BP-579/580/581/582. BP-577/578 kept. BP-583 added. Final range: **BP-577..BP-583**.
3. `DEBUG_SKIP_CLASSIFIER` placement: audit suggests `intent_classifier.py:119-136`; real 5-10 s tail is L2 injection classifier (audit §A1:22-28). Plan places gate in `llm_injection_classifier.py`.
4. Migration 019 in-place edit rejected per BP-130; ships NEW 023.
5. VACUUM table count: audit lists 18; plan narrows to the 14 actually indexed by 019.

## Deferred to PLAN-0098

- VACUUM on 3 sibling tables (`outstanding_shares`, `fund_holders`, `institutional_holders`).
- Live profiling instrumentation (§FIX-E).
- Intent classification cache (§FIX-C).
- Per-phase latency metrics in chat-eval artifacts.
- Long-term FY2026 backfill cadence beyond one-shot.
