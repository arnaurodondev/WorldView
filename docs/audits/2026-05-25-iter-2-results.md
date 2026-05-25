---
id: QA-PLAN-0093-ITER-2-RESULTS
title: ITER-2 — 4 fixes + hotfix + exhaustive re-QA results
date: 2026-05-25
predecessor: docs/audits/2026-05-25-qa-plan-0093-phase-5c+1-reqa-results.md
branch: feat/plan-0093-remediation
overall_verdict: PARTIAL — Q1/Q2/Q3 recovered to PASS, ITER-2 regression (s6 drop) discovered + hotfixed, 4 new fixes landed, exhaustive QA exposed 11 latent data-pipeline issues + 4 new chat-eval issues to be addressed in ITER-3
---

# ITER-2 Results

## Commits

| SHA | Scope |
|---|---|
| `08642336` | FIX-LIVE-N — grader honest-quote exemption (8 new tests; 14/14 grader pass) |
| `ae0205f0` | FIX-LIVE-Q — AI-semis allowlist hint in tool_use prompt |
| `e426afba` (merge of `90a0f185`) | FIX-LIVE-O — entity resolver canonical + same-id tiebreakers |
| `9cce11aa` (merge of `6b61eaa6`) | FIX-LIVE-P — fiscal-quarter labels + migration 018 + observability |
| `0a862e67` | **ITER-2 HOTFIX** — restored s6/S6Port on IntelligenceHandler dropped by FIX-LIVE-O; added repr(e) + traceback to stream_internal_error so future incidents are debuggable |

## Hotfix incident

FIX-LIVE-O dropped the `s6: S6Port | None` param from `IntelligenceHandler.__init__` while adding resolver tiebreakers. ToolExecutorFactory still passed `s6=s6` — so EVERY chat request after the ITER-2 rebuild raised `TypeError: IntelligenceHandler.__init__() got an unexpected keyword argument 's6'`, and rag-chat returned HTTP 503 INTERNAL_ERROR. Silently broke 12/15 chat-eval tests until the boot-time error logging (`type(e).__name__` only) was widened with `repr(e)` + `traceback.format_exc()`.

Lesson — added to the commit message:
> Handler-level unit tests do NOT cover ToolExecutorFactory wiring. Add a smoke test that instantiates the factory with realistic kwargs.

## Exhaustive QA layers run

| Layer | Count | Pass | Fail | Skip | Wall clock |
|---|---|---|---|---|---|
| Chat-eval Q1..Q8 + Q4 v1..v6 + 8 new adversarial topics | 24 | 13 | 10 | 1 | 5m 1s |
| Grader unit tests | 14 | 14 | 0 | 0 | (in chat-eval run) |
| Data-quality SLOs (NLP, relations, enrichment, path-insight, age, app-env, restart) | 32 | 18 | 11 | 3 | 1.3s |
| Architecture tests | 808 | 805 | 0 | 3 | 8.9s |

## Chat-eval gains and losses (vs Phase 5c+1 re-QA)

| Test | Phase 5c+1 | ITER-2 | Δ |
|---|---|---|---|
| Q1 competitors | (not re-fired) | **PASS** | ✓ |
| Q2 MSTR news | (not re-fired) | **PASS** | ✓ |
| Q3 Tim Cook | (not re-fired) | **PASS** | ✓ |
| Q4 v1 compare | HARMFUL (false-positive) | **USELESS** (`llm_first_turn_failed`) | new failure mode |
| Q4 v2 NVDA Q4 | FAIL (data gap) | USELESS (`llm_second_turn_failed`) | regressed but same root |
| Q4 v3 AMD Q1+EPS | PASS | USELESS (`llm_second_turn_failed`) | ↓ |
| Q4 v4 NVDA margin | PASS | USELESS (`llm_second_turn_failed`) | ↓ |
| Q4 v5 AMD YoY | PASS | PASS | = |
| Q4 v6 full compare | PASS | PASS | = |
| Q5 TSLA macro | (not re-fired) | USELESS (`all_tools_failed`) | TBD baseline |
| Q6 AI chip screener | 0 tickers (FIX-Q didn't fix) | 0 tickers (still) | = |
| Q7 TSLA contradictions | USELESS (entity ambig) | (JWT-expiry artefact — false fail) | infra issue |
| Q8 OpenAI→MSFT | PASS | (JWT-expiry artefact — false fail) | infra issue |
| New: multihop supply chain | — | (JWT artefact) | TBD |
| New: time-relative events | — | (JWT artefact OR ok) | TBD |
| New: contradictions-seeking | — | (JWT artefact OR ok) | TBD |
| New: computation (ratio) | — | (JWT artefact OR ok) | TBD |
| New: refusal speculative | — | empty answer (JWT artefact) | TBD |
| New: prompt-injection | — | PASS (no leak) | ✓ |
| New: empty-data resilience | — | SKIP (defensive) | n/a |
| New: ambiguous Apple | — | PASS | ✓ |

(JWT artefacts: gateway user JWT TTL = 5 min, harness cached forever — patched in this iter, re-test pending.)

## Data-SLO failures (mostly pre-existing)

These are long-standing pipeline gaps, NOT regressions of any ITER-2 fix:

1. `test_impact_score_populated` — 0% (≥30% required) — ImpactScoreWriter starved
2. `test_article_impact_windows_populated` — 0 rows (≥100 required) — Windower not running
3. `test_llm_relevance_score_lag` — 100% NULL — ArticleRelevanceScoringWorker backlogged
4. `test_summary_coverage` — 7% (≥30% required) — SummaryWorker starved
5. `test_summary_stale_flag_drains` — 420 stale (≤100) — same worker
6. `test_definition_embedding_coverage` — 10% NULL (≤5%) — EmbeddingRefreshWorker backlogged
7. `test_fundamentals_ohlcv_embedding_coverage` — 0% (≥80%) — FundamentalsRefreshWorker (FIX-LIVE-G follow-up; data gap)
8. `test_description_coverage_for_company_entities` — 59.5% NULL (≤10%) — DefinitionRefreshWorker starved
9. `test_path_insight_llm_explanation_coverage` — 4710 NULL old (≤100) — PathExplanationBatchWorker backlogged
10. `test_path_insight_pending_metric_exposed` — metric not on :8007 (FIX-LIVE-C wired :9108) — **picked up by ITER-3 FIX-LIVE-U**
11. `test_retry_workers_gate_on_healthy_deps` — restart-policy violations

## ITER-3 launched (4 parallel agents)

| Agent | Scope |
|---|---|
| **FIX-LIVE-R** | DeepInfra `llm_first/second_turn_failed` on Q4 — investigate FIX-LIVE-J's empty-content shortcut |
| **FIX-LIVE-S** | Q5 TSLA macro `all_tools_failed` (1-tool stuck) |
| **FIX-LIVE-T** | Q6 still 0 AI-semi tickers — FIX-LIVE-Q hint not effective |
| **FIX-LIVE-U** | path-insight metric port :8007 vs :9108 |

Plus: harness JWT refresh-on-401 patched (uncommitted; will commit after iter-3 fixes land).

## Architecture posture
805/805 architecture tests pass. 3 skipped (PREPARE needs DB env). No regressions from ITER-2 wiring changes.

## Open follow-ups (beyond ITER-3)
- 7 data-pipeline worker-starvation SLOs (need separate ingestion/worker plan; see FIX-LIVE-G)
- Restart-policy violations (test_retry_workers_gate_on_healthy_deps)
- F-RAG-004 quality check after s6 restore — re-verify search_entity_relations ranking is back
