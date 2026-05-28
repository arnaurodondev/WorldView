# PLAN-0095 Revision Report — 2026-05-26

**Auditor**: Claude (revise-prd skill)
**Plan**: `docs/plans/0095-iter-9-pipeline-quality-plan.md`
**Sources**: ITER-9 multi-issue audit + EODHD fundamentals deep-dive (same date)
**Overall verdict**: NEEDS_REVISION → fixes applied in-place

## Summary

- EODHD findings folded in: 4 new tasks (T-W1-04..07)
- Stale file:line citations corrected: 1
- Stale env-var assumption corrected: 2
- New "missing env-var" surfaced: 1 (now implementation task)
- Migration count corrected: 1 → 3
- Cross-PRD conflicts: none (PLAN-0094 W2 WIP file set is disjoint from PLAN-0095)
- Deferred to PLAN-0096: 3 EODHD items

## Changes Applied

| # | Section / Task | Change | Reason |
|---|----------------|--------|--------|
| 1 | §3 verification table — `chat_pipeline.py` order | Corrected `:457` → `:154-155` (orchestrator call site); definitions at `:203` (validate_input) and `:251` (check_cache) | Audit cited stale line; verified against current code |
| 2 | T-W2-03 target files | Same correction inside the task | Same reason |
| 3 | T-W1-99 placeholder | **Removed**, replaced with concrete T-W1-04 (BP-542), T-W1-05 (BP-543), T-W1-06 (BP-544), T-W1-07 (BP-545) | EODHD deep-dive landed; folded in |
| 4 | W1 migration footprint | "1 migration" → "3 migrations (019/020/021)"; current head verified `018_add_fiscal_year_end_month.py` | T-W1-04 + T-W1-07 each add a column |
| 5 | W1 validation gate | Added 4 new check items (snapshot period_type, freshness column, unknown-field log, sequenced up/down/up) | Match expanded scope |
| 6 | W1 compounding updates | Added 3 BP entries (542/543/544/545) and 2 new pitfalls; "files touched" sub-section to sequence T-W1-04/06/07 edits in `fundamentals_consumer.py` | Multiple tasks touch the same consumer file — non-overlapping line ranges noted to prevent merge issues |
| 7 | §1 commit-blocker callout | Strengthened with explicit "READ FIRST" header; enumerated PLAN-0094 W2 file set and confirmed disjoint from PLAN-0095 | Cross-PRD conflict check requested |
| 8 | W2 dependency on W1 | Made explicit: T-W1-03 composite index is HARD prereq for W2 acceptance gate (not just correctness) | Implicit dep promoted to explicit |
| 9 | T-W2-04 acceptance gate | Pointed at concrete artifact path: `runs/<ts>/summary.json` field `latency.p99_seconds` | "Testable" requirement |
| 10 | §3 `RAG_COMPLETION_CACHE_DISABLED` | Marked **NEW** (does not exist in repo); T-W3-04 now also implements the bypass in `chat_pipeline.check_cache()` | `git grep` returned zero hits — audit's claim was aspirational |
| 11 | W3 "no deploy" → "deploy needed" | Adjusted | The new env-var implementation requires a rag-chat rebuild |
| 12 | T-W4-01 (path-insight env) | Flagged stale-defaults assumption: `config.py:276-278` already 300/7; only `cycle=12` is novel | Verified live code; audit baseline was stale |
| 13 | §7 BP list | Expanded from 5 to 9 entries (added 542/543/544/545) | EODHD findings |

## Cross-PRD Conflict Check

| Resource | PLAN-0094 W2 WIP | PLAN-0095 | Conflict? |
|----------|------------------|-----------|-----------|
| `apps/.../PortfolioNewsWidget.tsx` | YES (modified) | NO | clean |
| `services/rag-chat/.../handlers/news.py` | YES | NO | clean |
| `services/rag-chat/.../security/llm_injection_classifier.py` | YES | NO | clean |
| `services/rag-chat/tests/unit/security/test_llm_injection_classifier.py` | YES | NO | clean |
| `services/knowledge-graph/tests/unit/application/test_structured_enrichment.py` | YES | NO | clean |
| `services/rag-chat/.../pipeline/chat_pipeline.py` | NO | YES (T-W2-03, T-W3-04) | clean |
| 14 market-data files | NO | YES | clean |

**Conclusion**: zero file overlap. The pre-commit blocker remains because mypy runs across the staging area, but no merge collision exists.

## Deferred to PLAN-0096

| Item | Source | Reason |
|------|--------|--------|
| EODHD §3 zero-vs-null FCF margin semantics | EODHD §3 | Cosmetic; no live failure |
| Backfill `fiscal_year_end_month` for non-US tickers | EODHD §6 | Coverage gap, not correctness |
| BP-542 alternative (b): split snapshot into quarterly+annual TTM rows | EODHD §5 | Larger schema change; T-W1-04 v1 ships nullable columns |

## Inconsistencies Found but NOT Auto-Fixed

None — all blocking items resolved by in-place edits. Three speculative EODHD items were explicitly deferred (above) rather than included.

## TRACKING.md

Existing PLAN-0095 row already advertises 4 waves and the EODHD placeholder; the wave count is unchanged (still 4). Task count grew (T-W1 went from 3 → 7 tasks). Material enough to update — recommend a small TRACKING.md amendment to add "+EODHD T-W1-04..07 folded in (BP-542/543/544/545)" to the W1 summary, but no row-level fields change (status still `draft`, waves still `0/4`). Left to the implementer to update on first W1 commit.
