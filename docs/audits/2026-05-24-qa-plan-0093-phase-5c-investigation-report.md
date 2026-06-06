---
id: INV-PLAN-0093-PHASE-5C
title: PLAN-0093 Phase 5c — Investigation Consolidation + Fix Orchestration Plan
date: 2026-05-24
plan: docs/plans/0093-intelligence-pipeline-remediation-plan.md
phase_5c_report: docs/audits/2026-05-24-qa-plan-0093-phase-5c-live-report.md
investigators: 5 parallel agents (INV-LIVE-A through INV-LIVE-E)
status: ready_for_fix_orchestration
---

# Phase 5c — Investigation Consolidation Report

## What the investigations changed about our understanding

The original Phase 5c report concluded "PLAN-0093 RAG safety is insufficient — Q4 still fabricates." The 5-agent investigation reveals that conclusion was **misdiagnosed**. The truth is more uncomfortable:

1. The FIX-2 RAG safety patches **never executed** for the Q4 v1 question because a 24-hour Valkey completion cache served the pre-FIX poisoned answer (1-line fix possible).
2. Three other "RAG failures" (Q5/Q6/Q7) were **infrastructure flakes**, not RAG bugs — `RateLimitMiddleware` fail-closed when Valkey hiccuped (the eval never reached S8).
3. The "missing worker" finding (F-LIVE-006) was a **misdiagnosis** — worker IS deployed via APScheduler, but has 2 separate bugs (attribute mismatch + no /metrics port).
4. The "2 real schema bugs" from F-1 PREPARE were **extractor false positives** — fragments composed at module level fail PREPARE in isolation.
5. The "worker backlogged" SLO failures break down: **1 real bug** (FundamentalsRefreshWorker), 1 misdiagnosed (RelevanceScoring upstream-empty), 3 false-positives (cycle hasn't fired on fresh boot).
6. The Q4 v4/v5/v6 "over-refusal" is a **grader precision issue**, not an agent regression — the LLM honestly says "tool doesn't return gross margin" and the grader matches "i cannot provide" as a refusal.

The infrastructure work (Sub-Plans A/B/D/F + restart policies) remains validated. The remediation needed is smaller than Phase 5c suggested but spans 7 distinct concerns.

---

## Consolidated finding matrix (post-investigation)

| ID | Severity | Cluster | Surface | Real root cause | Fix size |
|---|---|---|---|---|---|
| **F-LIVE-008-CACHE** | BLOCKING | RAG | Q4 v1 HARMFUL | Completion cache key `rag:v1:` not bumped on FIX-2 ship → pre-FIX answer served verbatim with 24h TTL | 1 line |
| **F-LIVE-008-RATIONALISATION** | MAJOR | RAG | Q4 prose | `numeric_grounding.py` validates numbers but not rationalisation prose ("may reflect", "potential volatility") | ~20 lines |
| **F-LIVE-006-A** | BLOCKING | KG | path_insights 12.9K rows have NULL explanation | `PathExplanationService._call_llm` accesses `result.output` but `ExtractionOutput` attribute is `result.result` — AttributeError caught silently | 5 lines |
| **F-LIVE-006-B** | MAJOR | KG | gauge invisible | scheduler container has no `prometheus_client.start_http_server` → gauge unscrapeable | 3 lines + compose `expose` |
| **F-LIVE-005C-VALKEY** | BLOCKING | Infra | Q5/Q6/Q7 → HTTP 503 | `RateLimitMiddleware` fail-closed when Valkey op raises; no retry, no metric | ~10 lines |
| **F-LIVE-005C-FALLBACK** | CRITICAL | RAG | Q2 USELESS | `_try_fallback_tools` copies `failed.input` verbatim — alt tool's `**args` signature raises TypeError → ToolExecutor swallows it as `None` | ~30 lines |
| **F-LIVE-005C-REFUSAL** | MINOR | Grader | Q4 v4-v6 USELESS | `_REFUSAL_TOKENS` matches "i cannot provide" even when answer cites tools + has tabular data | 5 lines |
| **F-LIVE-005C-YOY** | MAJOR | RAG | Q5 YoY can't compute | Agent calls `periods=2`; YoY needs `periods≥5` to include prior-year quarter — no prompt hint | prompt addendum |
| **F-LIVE-005C-GROSS-MARGIN** | MINOR | Tool | Q4 v4 can't answer | `_format_fundamentals_table` doesn't emit gross_profit/gross_margin/COGS | depends on S3 |
| **F-LIVE-007** | MAJOR | Test infra | F-1 PREPARE noise | Extractor doesn't handle SQLAlchemy `:name` AND doesn't fold `Name + Constant` SQL fragments | ~80 lines + tests |
| **F-LIVE-NEW-1** | BLOCKING | KG | fundamentals_ohlcv 0/2405 | FundamentalsRefreshWorker hits `market_data_unavailable` on every entity (BP-303 family — auth/JWT missing) | investigate first |
| **F-LIVE-NEW-2** | CRITICAL | NLP | 70% llm_relevance_score NULL last 24h | RoutingWriter producing 0 routing_decisions for recent 85 docs — upstream gap, not worker bug | investigate first |
| **F-LIVE-NEW-3** | MINOR | Docs | Model claim mismatch | DefinitionRefreshWorker actually uses `Qwen/Qwen3-235B-A22B-Instruct-2507` via DeepInfra, not Gemini Flash Lite (MEMORY.md + PRD-0017 wrong) | 1 line doc |

## Findings that the original Phase 5c report had WRONG

| Original claim | Truth (per investigation) | Source |
|---|---|---|
| "PathExplanationBatchWorker not in compose" | Worker IS deployed in `knowledge-graph-scheduler` via APScheduler. Real bug is the `ExtractionOutput.output` attribute mismatch + scheduler has no /metrics port. | INV-LIVE-A |
| "F-1 PREPARE found 2 real schema bugs" | Both are extractor false positives. Fragments composed via `Name + Constant` BinOp at module level fail PREPARE in isolation. | INV-LIVE-B |
| "FIX-2 RAG safety contract is insufficient" | FIX-2 patches are correct but were never executed for Q4 v1 — cache served pre-FIX answer. Patches DID execute for Q4 v2-v6 with mixed results. | INV-LIVE-C |
| "Q5/Q6/Q7 are multi-tool fallback failures" | Q5/Q6/Q7 are HTTP 503 from API gateway rate-limit middleware — never reached S8. Pure infra flake. | INV-LIVE-D |
| "5 workers backlogged → workers broken" | 3 are operational (cycle hasn't fired on fresh boot), 1 is broken (FundamentalsRefresh — auth), 1 is misdiagnosed (RelevanceScoring is healthy, upstream RoutingWriter empty). | INV-LIVE-E |

---

## Fix Orchestration Plan (next phase)

Spawn 6 fix agents in parallel — each gets the exact patch from its corresponding INV-LIVE-* output. All scopes are non-overlapping.

### FIX-LIVE-A — RAG cache poisoning (F-LIVE-008-CACHE) — HIGHEST LEVERAGE
**Files**: `services/rag-chat/src/rag_chat/application/caching/completion_cache.py:23` (key prefix), `services/rag-chat/src/rag_chat/application/pipeline/chat_pipeline.py:540` (cache write gating), optional new env flag `RAG_COMPLETION_CACHE_ENABLED`.
**Patch from**: INV-LIVE-C "Recommended fix" FIX A + FIX B.
**Why first**: 1-line cache prefix bump immediately frees Q4 v1 to flow through FIX-2 patches. Without it, every re-QA produces the same false HARMFUL.
**Validation**: bump prefix, restart rag-chat, re-fire Q4 v1, confirm `raw_events[0] != cache_hit`, confirm `tool_calls` includes `get_fundamentals_history`, confirm answer does NOT contain `$34.6B`.

### FIX-LIVE-B — RAG validator + grader hardening (F-LIVE-008-RATIONALISATION, F-LIVE-005C-REFUSAL, F-LIVE-005C-YOY)
**Files**: `services/rag-chat/src/rag_chat/application/services/numeric_grounding.py` (add `RATIONALISATION_RE` check), `libs/prompts/src/prompts/chat/tool_use.py` (YoY/periods hint), `tests/validation/chat_eval/grading.py:182-197` (tighten refusal detector).
**Patch from**: INV-LIVE-C FIX C + INV-LIVE-D recommendations 5+6.
**Validation**: re-fire Q4 v1 (rationalisation prose should now be caught at validator → rewrite), re-fire Q4 v5 (YoY should call periods≥5), Q4 v4 should grade MARGINAL not USELESS.

### FIX-LIVE-C — PathExplanation worker (F-LIVE-006-A + F-LIVE-006-B)
**Files**: `services/knowledge-graph/src/knowledge_graph/application/services/path_explanation_service.py:152` (attribute fix), `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler_main.py` (start_http_server), `infra/compose/docker-compose.yml` `knowledge-graph-scheduler` (`expose: ["9108"]`), `infra/prometheus/prometheus.yml` (scrape target), `services/knowledge-graph/tests/unit/application/services/test_path_explanation_service.py` (replace MagicMock with `spec=ExtractionOutput`).
**Patch from**: INV-LIVE-A Patch 1 + Patch 2.
**Validation**: rebuild scheduler, observe `path_explanation_persisted` events in logs within 4 min, observe gauge on `/metrics` at scheduler:9108, observe path_insights `llm_explanation IS NOT NULL` count growing.

### FIX-LIVE-D — Gateway Valkey resilience (F-LIVE-005C-VALKEY)
**Files**: `services/api-gateway/src/api_gateway/middleware.py:382-498` (retry-with-backoff on Valkey op, structured `valkey_health` event, metric counter `rate_limiting_unavailable_total`).
**Patch from**: INV-LIVE-D recommendation 1.
**Validation**: kill Valkey for 5s, observe gateway requests retry instead of 503, observe metric counter increments, re-fire Q5+Q6+Q7 → expect 200 with real tool calls.

### FIX-LIVE-E — Tool-fallback arg projection (F-LIVE-005C-FALLBACK)
**Files**: `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:850-913` (per-tool arg-projection table in `_FALLBACK_MAP`), `services/rag-chat/src/rag_chat/application/pipeline/tool_executor.py:239-241` (don't blanket-swallow Exception — log type+repr, classify TypeError/AttributeError as `tool_argument_error`).
**Patch from**: INV-LIVE-D recommendations 2-4.
**Validation**: re-fire Q2 — expect fallback chain to fire visibly via SSE `tool_call`/`tool_result` events for the alt tool; expect at least MARGINAL verdict.

### FIX-LIVE-F — F-1 PREPARE tooling (F-LIVE-007)
**Files**: `tests/architecture/test_repository_sql_prepare.py` (add `_translate_named_to_positional` helper + wire into `_prepare_one`), `tests/architecture/repository_sql_extractor.py` (add `_collect_module_string_constants` + `_fold_addition` for `Name + Constant` BinOp).
**Patch from**: INV-LIVE-B Part 1 + Part 3.
**Validation**: re-run F-1 PREPARE pass — 60+ false positives collapse, surface any GENUINE schema drift hiding underneath the noise.

### FIX-LIVE-G — FundamentalsRefreshWorker JWT/auth (F-LIVE-NEW-1)
**Investigation needed first** — INV-LIVE-E identified this as a deployed-but-broken worker hitting `market_data_unavailable` on every entity. Likely BP-303 family (missing service-account JWT for KG-scheduler → market-data API → 401 silently swallowed).
**Files (to confirm)**: `services/knowledge-graph/src/knowledge_graph/infrastructure/http/market_data_client.py`, `infra/compose/docker-compose.yml` `knowledge-graph-scheduler` env vars (SERVICE_ACCOUNT_TOKEN, MARKET_DATA_INTERNAL_URL).
**Pre-fix step**: spawn focused INV agent to confirm root cause (1 hour).
**Validation**: after fix, observe `fundamentals_refresh_market_data_unavailable` count drops to 0 across next 2h cycle; fundamentals_ohlcv embedding coverage > 0.

### FIX-LIVE-H (deferred) — RoutingWriter empty output (F-LIVE-NEW-2)
INV-LIVE-E flagged but did not investigate. 70% of recent docs have NO `routing_decisions` row, which is why ArticleRelevanceScoringWorker has nothing to score. This is a separate routing-pipeline gap. Defer to a focused investigation in a follow-up.

### FIX-LIVE-I (trivial) — DefinitionRefreshWorker doc drift (F-LIVE-NEW-3)
Update `MEMORY.md` + `docs/specs/0017-narratives-and-screener.md` to reflect actual model `Qwen/Qwen3-235B-A22B-Instruct-2507` via DeepInfra.

---

## Re-QA Plan (post-fix)

After FIX-LIVE-A..F land (G/H/I can ship separately), re-run a focused live-execution QA:

1. **Cache invalidation check**: confirm Q4 v1 actually exercises FIX-2 patches (no cache hit, tool calls present, `$34.6B` absent).
2. **Re-fire all 8 audit questions + A10**: expect ≥6/8 USEFUL, 0 HARMFUL.
3. **Re-fire weak-point survey (T-G-3-11)**: 75 queries against the live agent.
4. **Re-run G-1 SLOs**: confirm definition embedding > 95%, description coverage > 90% (now that DefinitionRefresh has had time to backfill), path_insights llm_explanation populated.
5. **Re-run F-1 PREPARE**: confirm noise is gone, surface any REAL schema drift.
6. **Re-run host-event survival**: confirm 11 app-tier services still self-heal (regression guard for FIX-3).
7. **Soak test (optional)**: 1-hour run-of-everything to catch flakes.

Each gate produces a clear PASS/FAIL with the verdict criteria already documented in PLAN-0093 Wave G-3.

---

## Compounding (new BP / HR / R candidates from this investigation)

- **BP-NEW**: Completion-cache poisoning across prompt versions — bump cache key on every prompt/validator change.
- **BP-NEW**: Eval harness must always disable response cache (or fresh `thread_id` per ask) — otherwise live-eval can't detect post-cache-write fixes.
- **BP-NEW**: Static SQL extractor must fold `Name + Constant` BinOp — module-level SQL fragment patterns produce false positives.
- **BP-NEW**: `assert_*_or_die` / lifespan assertion shipped without matching env wiring → fresh-clone production-grade outage.
- **BP-NEW**: Migration not run live before merging → 0044+0046 had bugs that ANY live run would catch in <30s.
- **BP-NEW**: SQL DEFAULT cannot reference another column — grep rule for `server_default=sa.text("<colname>")`.
- **BP-NEW**: Worker happy-path tests using bare MagicMock instead of `spec=<DataclassType>` mask attribute renames (caught the F-LIVE-006-A bug).
- **BP-NEW**: ToolExecutor blanket Exception swallow masks tool-argument-shape mismatches as "tool returned empty".
- **BP-NEW**: Worker SLO test must distinguish "worker not running" from "no candidates to process" — JOIN-and-explain on upstream filter.
- **BP-NEW**: Long worker cycle on fresh boot triggers false SLO failure — gate on `container_uptime > cycle_seconds * 2`.
- **HR-NEW**: Caching layer above a strict-output validator is unsafe by construction — cache+gate on validator outcome too.
- **HR-NEW**: Markdown-table cell context defeats local-window classifiers — provide structured (value, kind) rows or widen radius for tool-emitted markdown.
- **HR-NEW**: Operational-state SLO assertions need uptime context.
- **HR-NEW**: Static QA cannot certify runtime correctness — the meta-lesson confirmed again. Every assertion of "this fix works" must include a live-execution datapoint.
- **R-NEW (proposed R36)**: Static SQL drift checks run against composed statements only, never on individual fragments.

---

## Ready for next phase

The orchestrator (you) can now spawn 6-7 fix agents per the FIX-LIVE-A..F roster, then run the post-fix re-QA cycle. Estimated total work: ~1 day of focused fix work + ~2 hours of re-QA.

If you would rather scope down to "ship the unambiguous wins now and defer the rest", the minimum viable Phase 5c PASS is:
- FIX-LIVE-A (cache bump — 1 line, 5 min)
- FIX-LIVE-C (PathExplanation attribute — 5 lines, 30 min)
- FIX-LIVE-D (gateway Valkey resilience — ~10 lines, 1 hour)
- Re-fire Q4 v1, Q5, Q6, Q7 → expect 0 HARMFUL + USEFUL/MARGINAL on the infra-blocked questions.

That subset would flip the Phase 5c verdict from FAIL to PASS_WITH_NOTES without touching the larger E-4 fallback / numeric validator / grader work.
