---
id: QA-PLAN-0093-ITER-4-RESULTS
title: ITER-4 — 5 fixes + chat-eval 57/64 PASS (89%)
date: 2026-05-25
predecessor: docs/audits/2026-05-25-iter-3-results.md
branch: feat/plan-0093-remediation
overall_verdict: NEAR_COMPLETE — chat-eval at 89% pass (Q1-Q5/Q7/Q8 all green, 4 of 6 Q4 variants green, weak-point survey 9/9 PASS, all grader unit tests green). 6 remaining failures: 1 data gap (deferred to FIX-LIVE-G), 1 test bug, 4 actionable code issues. Picked up in ITER-5.
---

# ITER-4 Results

## Commits

| SHA | Scope |
|---|---|
| `b287d8b8` | FIX-LIVE-W — grader speculative-phrase exemption (separate marker sets; orphan-context check) |
| `23f40db9` | FIX-LIVE-Z (SAFETY P0) — speculative-price refusal guardrail in tool_use + intent_prompts |
| `835dba55` | FIX-LIVE-Y — orchestrator splits empty vs errored tool results; graceful "no data found" instead of all_tools_failed (+ BP-550) |
| `3d3d0fb3` | FIX-LIVE-V — mid-loop chat_with_tools recovery + partial-stream preservation |
| `fb69ba87` (merge of `a25623ae`) | FIX-LIVE-X — DeepInfra tool-call timeout 30→90s + non-blank exception messages |

## Chat-eval matrix (64 tests)

| Group | Pass | Fail | Notes |
|---|---|---|---|
| Aggregate-score gate | 0 | 1 | sums of below |
| Grader unit tests | 22 | 0 | FIX-N + FIX-W extensions all green |
| Q1..Q3 | 3 | 0 | stable |
| Q4 v1..v6 + 2 cross-cutting | 8 | 1 | only Q4 v2 fails (data gap) |
| Q5 | 1 | 0 | stable |
| Q6 | 0 | 1 | LLM misreads screener output (FIX-DD scope) |
| Q7 | 1 | 0 | FIX-Y "no contradictions found" |
| Q8 | 1 | 0 | FIX-V partial recovery |
| Adversarial (8) | 7 | 1 | speculative-price test bug + multihop iter-0 |
| ITER-3 topics (8) | 5 | 2 | conditional prompt-injection FP + 1 skip |
| Weak-point survey (9) | 9 | 0 | **all PASS!** |

**Aggregate: 57 PASS / 6 FAIL / 1 SKIP out of 64 (89%)**

## 6 remaining failures (iter-5 scope)

### Real product issues (3)
- **Q6 misread screener** → FIX-LIVE-DD: screener returns raw `2500000000000` market cap; LLM treats it as "unverifiable". Add `market_cap_formatted: "$2.50T"` derived field + stronger render prompt.
- **multihop_supply_chain** iter-0 first-turn DeepInfra failure → FIX-LIVE-BB: FIX-V only covers iter>0; add iter-0 retry/synthesis-only fallback.
- **conditional reasoning** false-positive INPUT_REJECTED → FIX-LIVE-CC: prompt-injection detector flags legitimate `if X then Y` financial reasoning.

### Test bug (1)
- **speculative-price** ("will go up" in refusal) → FIX-LIVE-AA: agent's refusal "I cannot provide a yes-or-no on whether stock will go up or down" trips substring check. Mirror FIX-N/W hedge-window logic.

### Data gap (1, deferred)
- **Q4 v2** NVDA Q4FY26 revenue 68.127B not in DB → FIX-LIVE-G follow-up (EODHD ingestion). No code fix possible this iteration.

### Meta (1)
- **aggregate_score_gate** — meta-test that sums the above; will pass when the 5 actionable ones resolve.

## ITER-5 launched (4 parallel agents)

| Agent | Scope |
|---|---|
| **FIX-LIVE-AA** | refine speculative-price assertion to ignore hedge-context occurrences |
| **FIX-LIVE-BB** | iter-0 first-turn recovery (retry + synthesis-only fallback) |
| **FIX-LIVE-CC** | prompt-injection FP on legitimate conditional reasoning |
| **FIX-LIVE-DD** | Q6 screener formatted-mcap field + imperative render prompt |

## Long-tail (deferred — multi-iteration follow-up plan)
- 6 worker-starvation SLOs (`test_impact_score_populated`, `test_article_impact_windows_populated`, `test_llm_relevance_score_lag`, `test_summary_coverage`, `test_definition_embedding_coverage`, `test_description_coverage_for_company_entities`)
- 1 data-coverage SLO (`test_fundamentals_ohlcv_embedding_coverage` 0/2405) tracked under FIX-LIVE-G
- `test_retry_workers_gate_on_healthy_deps` restart-policy contract violations
- S6 ticker-resolver "ARE" false-positive (logged in FIX-LIVE-Y; non-blocking)
