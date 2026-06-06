---
id: PLAN-0097
title: ITER-9 Follow-ups III — Phase-D Verdict Remediation (Data Integrity P0 + Classifier/Grader P0 + Latency P1 + P2 Punch List)
prd: inline (see §0)
status: revised
created: 2026-05-27
updated: 2026-05-27
revision_report: docs/audits/2026-05-27-plan-0097-revision-report.md
source_audits:
  - docs/audits/2026-05-27-plan-0097-data-integrity-investigation.md (FOLDED — concrete file:line + new FundamentalsRefreshWorker scope)
  - docs/audits/2026-05-27-plan-0097-classifier-grader-investigation.md (FOLDED — grading.py refs + tool equivalence map)
  - docs/audits/2026-05-27-plan-0097-latency-investigation.md (FOLDED — VACUUM ANALYZE on 14 tables + DEBUG_SKIP_CLASSIFIER + batch resolution profile)
  - docs/audits/2026-05-27-plan-0097-p2-punchlist-and-docs.md (FOLDED — 10 items, re-balanced across W1/W2/W3/W4 to avoid file collisions)
  - docs/audits/2026-05-26-iter-9-final-qa-*.md (ITER-9 final code-review + doc audit + SLO check)
  - tests/validation/chat_eval/runs/20260527T005842Z/ (Phase D run dir)
  - /tmp/chat_eval_phaseD.log (Phase D summary)
---

# PLAN-0097 — ITER-9 Phase-D Verdict Remediation

## §0 — Inline PRD

> No separate PRD. This plan closes every open issue surfaced by the
> ITER-9 **Phase D** adversarial chat-eval pass on a freshly rebuilt
> stack. Phase D returned **6 failed / 14 passed verdicts**, **HARMFUL=1**,
> and **p99=207 s** — failing the aggregate gate (≥6 USEFUL, HARMFUL=0,
> p99<60 s) that PLAN-0095 + PLAN-0096 were meant to clear. Four parallel
> investigations are landing into the audit files cited above; this plan
> is the umbrella remediation that will fold their concrete findings in
> on the next `/revise-prd` round.

### Problem statement

The Phase D chat-eval run (`tests/validation/chat_eval/runs/20260527T005842Z/`)
exposed four distinct failure classes:

1. **P0 — Data integrity ($26.4B annualized-field leak + FY2026 backfill
   gap)**: a derived/annualized fundamentals field is being surfaced to the
   chat agent which then quotes it as a quarterly value, producing a single
   HARMFUL verdict. Quarterly FY2026 rows are also missing for at least one
   of the eval tickers, so the agent has no fresh data to ground on.
   Investigation: `2026-05-27-plan-0097-data-integrity-investigation.md`
   §A1–A3 (root cause) + §B1–B4 (remediation).
2. **P0 — Classifier false-positive + grader staleness**: Q8 (a benign
   "discover the relationship between named companies" query) is rejected
   by the LLM-injection classifier as INPUT_REJECTED, and the grader does
   not accept `get_fundamentals_history_batch` as equivalent to the
   singular tool name. Cache-hit + INPUT_REJECTED verdicts also
   incorrectly fail the tool-call assertion.
   Investigation: `2026-05-27-plan-0097-classifier-grader-investigation.md`
   §A1–A4 (root cause) + §B1–B2 (remediation).
3. **P1 — Latency regression to p99=207 s**: PLAN-0095 W2 introduced the
   `get_fundamentals_history_batch` tool and the composite indexes, but
   the post-migration query planner has not refreshed statistics so the
   index is not picked. Ticker resolution in the batch endpoint is
   suspected sequential, and the model still selects the singular tool
   for multi-ticker queries. Eval-mode overhead (5–10 s per question from
   the classifier) is fully avoidable in test runs.
   Investigation: `2026-05-27-plan-0097-latency-investigation.md` §1–§5.
4. **P2 — Punch list (6 items) + docs**: 6 small items from the
   ITER-9 final QA (`docs/audits/2026-05-26-iter-9-final-qa-*.md` —
   code-review + doc-audit + SLO-check) need to land as small
   focused commits, plus 2 new rules (R35 sentinel-SQL-filter contract,
   R36 batch tool selection) and `MASTER_PLAN.md` cross-refs.
   Investigation: `2026-05-27-plan-0097-p2-punchlist-and-docs.md`
   §1–§10.

### Goals

1. Drive Phase-D verdicts to ≥6 USEFUL on a freshly rebuilt stack.
2. Eliminate the HARMFUL verdict ($26.4B annualized leak) at the source
   AND defense-in-depth at the rag-chat tool layer.
3. Restore p99 < 60 s on the chat-eval gate (down from 207 s).
4. Close the 6 P2 punch-list items + ship R35/R36 + MASTER_PLAN cross-refs.

### Non-goals

- Re-architecting the chat pipeline or the classifier model (scope is
  prompt + grader + short-circuit; model swap is out-of-scope).
- Backfilling historical chat-eval runs older than 20260527T005842Z.
- Refactoring `_most_recent_financial_row_with_period` or splitting
  QUARTERLY/ANNUAL TTM snapshot rows (deferred — see PLAN-0096 §0).
- Long-term answer-quality CI integration (PLAN-0075 owns that).

### Open questions — RESOLVED by revise-prd round (2026-05-27)

- **What exactly is the $26.4B field?** **RESOLVED**. Per
  data-integrity audit §A1: the leak source is the HIGHLIGHTS section
  fetched without `period_type` filter in
  `services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py:94-97`
  (`find_by_section(iid_str, FundamentalsSection.HIGHLIGHTS)`). HIGHLIGHTS
  rows are TTM/ANNUAL by source; when joined into a QUARTERLY response
  via `highlights_data` (lines 105-109) they expose annualized net_income
  (~$26.4B for AMD FY2024) as if it were a quarterly figure.
- **Why no FY2026 quarterly rows?** **RESOLVED**. Per audit §B2-B3: **no
  dedicated `FundamentalsRefreshWorker` exists in the codebase**. The
  fundamentals consumer at
  `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py:425`
  is event-driven only (no scheduler triggers the EODHD fetch). All
  fundamentals are stale from initial seed. W1 must SHIP a new worker
  under `services/content-ingestion/src/content_ingestion/application/workers/fundamentals_refresh_worker.py`.
- **Is ticker resolution actually sequential in the batch endpoint?**
  **RESOLVED — NO**. Per latency audit §H2 (lines 85-110): `asyncio.gather`
  at `services/market-data/src/market_data/api/routers/fundamentals.py:149-169`
  already parallelizes `_one(ticker)`. Estimated savings <1 s. T-W3-02
  retained as a *low-priority verification* task, not a critical-path
  fix. Primary latency drivers are VACUUM (40-70 ms/query) + classifier
  tail-p99 (5-10 s/call).
- **Does `DEBUG_SKIP_CLASSIFIER=true` already exist?** **RESOLVED — NO**.
  Per latency audit §FIX-B: env var must be added in
  `services/rag-chat/src/rag_chat/application/security/llm_injection_classifier.py`
  (Layer 2 entry) plus a `settings.app_env in {"dev","test"}` guard. The
  audit places it in `intent_classifier.py`; PLAN-0097 places it in
  `llm_injection_classifier.py` (where the actual 5-10 s latency comes
  from per audit §A1 line 22-28). Task moved W3→W2 to keep
  `llm_injection_classifier.py` ownership in a single wave.

---

## §1 — Overview

**PRD**: inline (above)
**Services affected**: market-data (S2), rag-chat (S8), nlp-pipeline (S6),
                       knowledge-graph (S7), content-ingestion (S4 — new
                       FundamentalsRefreshWorker), docs
**Total waves**: 4
**Total estimated effort**: ~12 h engineering + 1 full docker rebuild
                            cycle + 1 chat-eval rerun (~30 min wall-clock)
**Critical path**: W1 (data integrity + period-type integration test) and
                   W2 (classifier+grader+eval-mode bypass) must both land
                   before the cross-cutting acceptance gate can pass — W1
                   removes HARMFUL=1, W2 removes the Q8 false-positive AND
                   the eval-mode 5-10 s classifier tail. W3 (latency:
                   VACUUM + batch verification + batch endpoint exception
                   sanitization) lands in parallel — independent of W1+W2
                   verdicts. W4 (small P2 items + docs) can run anytime.

**Re-balancing summary (revise-prd round, 2026-05-27)**:
- P2 item 2 (real period_type integration test) moved **W4 → W1** — it
  is market-data data-integrity work and W1 already owns market-data
  test scope.
- P2 item 5 (batch endpoint exception sanitization) moved **W4 → W3** —
  it touches `services/market-data/src/market_data/api/routers/fundamentals.py`
  batch endpoint which W3 already edits for parallel ticker resolution
  (T-W3-02), avoiding inter-wave file collision.
- `DEBUG_SKIP_CLASSIFIER` env var (originally T-W3-04) moved **W3 → W2**
  (renumbered T-W2-04) — W2 owns `llm_injection_classifier.py`
  end-to-end (SAFE example + version bump + eval bypass). W3 no longer
  touches `llm_injection_classifier.py`.
- W4 final scope: P2 items 1 (sentinel SQL filter in nlp-pipeline), 3
  (NEW migration 022 — `IF NOT EXISTS` pattern on a new revision; the
  audit's note "edit committed migration 019" is rejected as it would
  fall foul of BP-130 / re-bring-up DBs already past 019), 4 (AGE
  rollback before invalidate), 6 (cache-version flush in rag-chat),
  and 7-10 (docs: R35, R36, market-data.md, MASTER_PLAN.md).

### Branch & commit hygiene

PLAN-0097 lands on a fresh branch `feat/plan-0097-phase-d-remediation` off
**main** after PLAN-0096 W1+W2 merge. W1 and W2 each get their own
commits; W3 latency fixes split into 4 small commits (one per task);
W4 docs is a single docs-only commit at the end.

## §2 — Dependency Graph

```
                ┌──────────────────────────────────────────────┐
                │ PLAN-0095 W1+W2 + PLAN-0096 W1+W2 in main    │
                │ (composite indexes + batch tool + defensive  │
                │  period_type + freshness column)             │
                └─────────────────────┬────────────────────────┘
                                      │
            ┌──────────────┬──────────┴───────┬──────────────┐
            ▼              ▼                  ▼              ▼
     W1 (data           W2 (classifier      W3 (latency:    W4 (P2 punch
     integrity P0:      + grader P0:        VACUUM + ticker  list + docs:
     $26.4B leak +      Q8 SAFE example +   parallelize +    R35/R36 +
     FY2026 backfill +  benign-relationship intent map +     market-data
     periodicity        regression set +    eval classifier  cleanup +
     labels)            grader updates)     short-circuit)   MASTER_PLAN)
            │              │                  │              │
            └──────┬───────┴──────────┬───────┘              │
                   ▼                  ▼                       │
       Cross-cutting acceptance gate (§5):                    │
       chat-eval rerun on rebuilt stack —                     │
       ≥6 USEFUL, HARMFUL=0, p99<60s, no                      │
       INPUT_REJECTED on Q8-class                             │
                                                              │
       (W4 independent of acceptance gate;                    │
        docs-only commit)  ◄───────────────────────────────────┘
```

W3 can run in parallel with W1+W2 (no shared files). W4 depends on no
other wave but should land last so the docs reflect the final state.

## §3 — Codebase State Verification

| Reference | Type | Service | Actual current state | Plan target | Delta |
|-----------|------|---------|----------------------|-------------|-------|
| $26.4B annualized field source | code | market-data | `services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py:94-97` — `GetFundamentalsHistoryUseCase.execute()` calls `self._uow.fundamentals_read.find_by_section(iid_str, FundamentalsSection.HIGHLIGHTS)` with NO `period_type=` kwarg; highlights record selected at lines 105-109 may be sourced from an ANNUAL EODHD payload; net_income (~$26.4B AMD FY2024) then flows into `highlights_data` and is quoted in the LLM tool response as period-level data | document HIGHLIGHTS is TTM-only at the repository layer; add `period_type` safety filter to `find_by_section` for HIGHLIGHTS OR explicit assertion + docstring; add regression test `test_highlights_never_mixed_into_period_revenue` in `services/market-data/tests/unit/test_get_fundamentals_history.py` (new file) | code + test |
| FY2026 quarterly fundamentals rows | data + code | content-ingestion + market-data | **NO `FundamentalsRefreshWorker` exists**. Grep `find services -name "*.py" \| xargs grep -l "FundamentalsRefreshWorker"` returns ZERO hits. Existing flow is event-driven: `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py:425` bumps `instruments.last_fundamentals_ingest_at` only when a `market.dataset.fetched` event arrives. No service publishes such events on a schedule, so post-seed fundamentals never refresh. | NEW worker at `services/content-ingestion/src/content_ingestion/application/workers/fundamentals_refresh_worker.py` per audit §B4 lines 230-245: periodic (every 6 h) EODHD fetch → publish `market.dataset.fetched` → existing consumer ingests. Top-500 by market cap; exponential backoff on 429. Until the worker ships, run a one-shot backfill script `services/content-ingestion/scripts/backfill_fundamentals.py` for the 7 eval tickers (AMD/NVDA/AAPL/MSFT/GOOGL/META/TSLA). | new worker + ops one-shot |
| rag-chat fundamentals tool response shape | code | rag-chat | `services/rag-chat/src/rag_chat/application/tools/get_fundamentals_history.py` + `_batch.py` — currently returns row dicts with field name + value, no `periodicity` label per-field | every annualized-derived field carries an explicit `periodicity` key in the row dict so the LLM grounding rules can refuse to quote it as quarterly | code change |
| Q8 SAFE classifier example | prompt | rag-chat | `services/rag-chat/src/rag_chat/application/security/llm_injection_classifier.py:61-93` — system-prompt string literal with SAFE-example list at lines 77-87 (per classifier audit §A2). Currently 5 SAFE categories: conditional reasoning, listing/comparing, benign uses of "ignore"/"forget", reasoning/citations, hostile/off-topic. Lacks any relationship-discovery / graph-traversal exemplar. | insert new SAFE example block AFTER line 86, BEFORE the hostile-message clause, covering "relationship between", "connections", "paths", "supply chain link" (verbatim text in classifier audit §A2 lines 44-50) | prompt change |
| Benign-relationship regression test set | test | rag-chat | does not exist (verify via `ls services/rag-chat/tests/unit/security/`) | new test file `services/rag-chat/tests/unit/security/test_llm_injection_classifier_benign_relationships.py` — 12 benign discovery/relationship queries (verbatim list in classifier audit §A4 Suites 1-3), each must classify as SAFE; LLM call MUST be mocked (no live DeepInfra) | new tests |
| Grader equivalence: batch vs singular tool | code | chat-eval harness | `tests/validation/chat_eval/grading.py:352-354` — `any(t in required_tools for t in tools_called)` (exact string match, no equivalence). Also `grading.py:337-360` lacks a `_TOOL_EQUIVALENCES` dict + helper. Refusal/error gating at `grading.py:413-416` does not distinguish `INPUT_REJECTED` (upstream classifier) from model errors. Per-question tests at `tests/validation/chat_eval/test_q4_nvda_amd_revenue.py:70`. | add `_TOOL_EQUIVALENCES` constant + `_check_tool_requirement_satisfied()` helper (verbatim in classifier audit §B1 lines 132-143); patch `grading.py:352-354` to call the helper; patch `grading.py:413-416` to flag `INPUT_REJECTED` as upstream-classifier USELESS, not generic FAIL | code change |
| Migration 019 composite indexes — post-migrate ANALYZE | infra | market-data | `services/market-data/alembic/versions/019_composite_fundamentals_indexes.py` (confirmed filename; PLAN-0095 T-W1-03) — creates 18 composite (instrument_id, period_end_date ASC) indexes via plain `op.create_index()`; no `VACUUM ANALYZE` follows, planner stats stale per latency audit §H1 lines 67-83. **14 tables** to VACUUM per audit §FIX-A lines 200-211 (NB: audit also lists `splits_dividends` and `outstanding_shares` for completeness — total 18; PLAN-0097 W3 sticks to the 14 fundamentals-section tables enumerated below). | NEW Alembic revision 022 `022_vacuum_analyze_fundamentals.py` using `op.get_context().autocommit_block()` (VACUUM cannot run inside a transaction). Tables: `analyst_consensus`, `balance_sheets`, `cash_flow_statements`, `dividend_history`, `earnings_annual_trends`, `earnings_history`, `earnings_trends`, `highlights`, `income_statements`, `insider_transactions_snapshot`, `share_statistics`, `splits_dividends`, `technicals_snapshots`, `valuation_ratios`. | migration |
| Batch endpoint ticker resolution | code | market-data | `services/market-data/src/market_data/api/routers/fundamentals.py:149-169` — `asyncio.gather` ALREADY parallelizes `_one(ticker)` per latency audit §H2 lines 85-110. Resolution is NOT the bottleneck. Estimated savings <1 s. | LOW-PRIORITY verification only: T-W3-02 adds a unit test asserting `await asyncio.gather` is in the call path + measures parallelism via mock timings. No code change expected unless the test reveals an unexpected `await` in the loop. | test only (verify-only task) |
| Batch tool description strength | prompt + intent | rag-chat | `services/rag-chat/src/rag_chat/application/tools/get_fundamentals_history_batch.py` description string + `services/rag-chat/src/rag_chat/application/tools/intent_inference.py` mapping (PLAN-0095 W3 strengthened 5 graph tool descriptions; batch tool description lacks a "USE THIS for multi-ticker" lead-in — verify exact line via `grep -n "description" services/rag-chat/src/rag_chat/application/tools/get_fundamentals_history_batch.py`) | strengthen description with explicit "**USE THIS** when the question mentions ≥2 tickers" + add intent-map entry mapping multi-ticker fundamentals questions to the batch tool | prompt + code |
| `DEBUG_SKIP_CLASSIFIER` env var | code | rag-chat | does not exist (verified via `grep -rn "DEBUG_SKIP_CLASSIFIER" services/rag-chat/src/` returns no hits per audit §FIX-B). Audit suggests placing in `intent_classifier.py` lines 119-136 but the **actual 5-10 s tail-p99 latency** documented in audit §A1-A2 comes from the L2 LLM injection classifier at `services/rag-chat/src/rag_chat/application/security/llm_injection_classifier.py` (DeepInfra Meta-Llama-3.1-8B-Instruct-Turbo per audit §A1 line 25-28). PLAN-0097 W2 places the short-circuit there. | new env var read at the L2 classifier entry; when `true` AND `settings.app_env in {"dev","test"}` AND not prod, return SAFE immediately + WARN log. Eval harness `tests/validation/chat_eval/conftest.py` (verified present per `ls` above) exports it for the test session. **Hard safety gate**: `app_env` must be checked at runtime, not at import. | new env + safety gate |
| P2 item 1 — sentinel SQL filter (R35) | code | nlp-pipeline | `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/news_query.py:139` — `em.tenant_id IS NULL OR em.tenant_id = :tenant_id` silently inverts visibility post-W4 sentinel fix per p2-punchlist audit §1: legacy NULL articles visible only to PUBLIC_TENANT_ID (anonymous), invisible to real tenants. | branch the SQL filter on the caller's tenant: if `tenant_id != PUBLIC_TENANT_ID` → `tenant_id == tenant_id OR tenant_id == PUBLIC_TENANT_ID`; else (sentinel caller) → `tenant_id IS NULL OR tenant_id == PUBLIC_TENANT_ID` (verbatim in p2-punchlist audit §1). R35 added in W4 docs commit codifying contract. | code |
| P2 item 2 — real period_type integration test (MOVED W4 → W1) | test | market-data | `services/market-data/tests/unit/test_fundamentals_query_defaults.py:57-122` — current tests `grep` compiled SQL strings for `"QUARTERLY"` (tautological per p2-punchlist audit §2 — proves the filter is present in SQL but not that it *excludes* ANNUAL rows). | add async integration test that seeds (QUARTERLY $50B + ANNUAL $200B) at the same `period_end_date`, queries `income_statement` without explicit `period_type`, asserts returned revenue == $50B (QUARTERLY shadows ANNUAL). Keep the string-inspection tests for regression coverage. | new integration test |
| P2 item 3 — NEW migration 023 `IF NOT EXISTS` retrofit | migration | market-data | `services/market-data/alembic/versions/019_composite_fundamentals_indexes.py:106-114` — uses plain `op.create_index()` per p2-punchlist audit §3; partial re-run fails. **NB**: editing committed migration 019 in-place is rejected (BP-130: re-bring-ups already past 019 would see no diff). PLAN-0097 ships a NEW revision 023 `023_make_019_indexes_if_not_exists.py` that DROPs and re-CREATEs each of the 18 indexes via `CREATE INDEX IF NOT EXISTS` per audit §3 verbatim. | NEW Alembic revision 023 (sequences AFTER W3's 022); same `_FUNDAMENTALS_TABLES` list referenced from a shared constants module so 022 + 023 stay in sync | NEW migration 023 (not in-place edit) |
| P2 item 4 — AGE rollback before invalidate | code | knowledge-graph | `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py:516-525` — `_invalidate_session_connection()` per p2-punchlist audit §4: calls `session.connection().invalidate()` without explicit `await session.rollback()` first; transactional state ambiguous. | add `await session.rollback()` immediately before `await session.connection().invalidate()` inside the try block (verbatim diff in p2-punchlist audit §4); unit test mocks `AsyncSession` and asserts call order rollback→invalidate. | code + unit test |
| P2 item 5 — batch endpoint exception sanitization (MOVED W4 → W3) | code | market-data | `services/market-data/src/market_data/api/routers/fundamentals.py:177-213` (batch handler), specifically line 205 returns `reason=str(exc)` per p2-punchlist audit §5; leaks SQL table/column names to LLM output. | distinguish `InstrumentNotFoundError` → `reason="instrument_not_found"`; bare `Exception` → `log.exception(...)` server-side + `reason="internal_error"` client-side. Test mocks a `ValueError`, asserts response `reason="internal_error"` and `log.exception` was called. Combined with T-W3-02 in the same fundamentals.py edit to avoid file collision with W4. | code + test |
| P2 item 6 — classifier-before-cache deploy-time flush | code | rag-chat | `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:456-475` + `docs/BUG_PATTERNS.md` per p2-punchlist audit §6 — W4 (PLAN-0096) reordered cache-then-classifier; pre-existing cache entries may have bypassed classifier (feature flag / dev override). Need one-shot `rag:completion:*` flush at deploy. | add deploy-time `SCAN MATCH rag:completion:* + DEL` to the rag-chat startup entrypoint (best-effort; non-blocking on failure); update BP-572 precondition note. Unit test mocks Valkey, asserts SCAN+DEL flow; integration test seeds poisoned key, runs flush, verifies deletion. | code + docs update |
| P2 items 7–10 — docs | docs | docs | (7) R35 not in `RULES.md` after R34; (8) R36 not in `RULES.md` after R35; (9) `docs/services/market-data.md` missing "## Period-Type Contract" subsection per p2-punchlist audit §9; (10) `docs/MASTER_PLAN.md` missing PLAN-0097 cross-refs in S2/S7 subsections | single docs commit per p2-punchlist audit §7-§10 with verbatim rule text | docs |
| Chat-eval harness — `RAG_COMPLETION_CACHE_DISABLED` env | code | tests/validation | shipped PLAN-0095 W3 (verified) | reuse — no change | none |
| `tests/validation/chat_eval/test_aggregate_score.py` | test | chat-eval | shipped, used as the verdicts + p99 gate harness | re-run after deploy with `RAG_CHAT_BASE_URL=http://localhost:8000`; confirm verdicts + `p99_seconds < 60.0` + HARMFUL=0 | execution gate |

## §4 — Sub-Plans

---

### Wave W1 — Data integrity P0 ($26.4B leak + FY2026 backfill + periodicity labels)

**Goal**: Eliminate the HARMFUL=1 verdict by (a) plugging the annualized-
field leak at its source, (b) restoring FY2026 quarterly fundamentals for
the eval tickers, and (c) defense-in-depth at the rag-chat tool layer so
no future annualized field can be quoted as quarterly without an explicit
`periodicity` label.

**Depends on**: PLAN-0096 W1 (defensive period_type default + freshness
column) must be in main.
**Estimated effort**: ~5 h (45 min HIGHLIGHTS source fix + 90 min new
                       FundamentalsRefreshWorker + 30 min one-shot
                       backfill + 60 min periodicity-label tool change +
                       45 min period_type integration test + 30 min unit
                       tests)
**Architecture layer**: market-data application + content-ingestion
                        application (NEW worker) + rag-chat application
**Branch**: `feat/plan-0097-w1`
**Migration**: NO (W1 ships no Alembic revisions; W3 owns the next
               revision number 022 for VACUUM; W4 owns 023 for the
               IF NOT EXISTS retrofit)
**Docker rebuild**: YES — `market-data` + `rag-chat` + `content-ingestion`
                    (new worker)

#### Tasks

##### T-W1-01: Fix the $26.4B HIGHLIGHTS-leak at the source

**Type**: impl + test
**depends_on**: none
**blocks**: T-W1-03

**Target files**:
- `services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py:94-97`
  — `GetFundamentalsHistoryUseCase.execute()` calls `find_by_section(iid_str, FundamentalsSection.HIGHLIGHTS)` without a `period_type` kwarg
- `services/market-data/tests/unit/test_get_fundamentals_history.py` (new file — directory may already exist; verify with `ls services/market-data/tests/unit/`)

**Audit reference**: `2026-05-27-plan-0097-data-integrity-investigation.md`
§A1 (lines 12-30, root cause walked line-by-line) + §A3 (lines 60-115,
fix sketch + regression test).

**What to build**:

1. **Docstring + assertion at the HIGHLIGHTS fetch** (verbatim from
   audit §A3 lines 71-80): the HIGHLIGHTS section is TTM-only by EODHD
   contract; document that assumption and gate it with a runtime
   assertion that fails fast if any HIGHLIGHTS row carries a non-NULL,
   non-TTM `period_type`:
   ```python
   highlights_records = await self._uow.fundamentals_read.find_by_section(
       iid_str, FundamentalsSection.HIGHLIGHTS,
   )
   # HIGHLIGHTS section is TTM-only by EODHD contract. If any row carries
   # a non-NULL period_type, surface it as an error rather than silently
   # exposing an annualized value as if it were period-level data.
   assert all(
       r.period_type in (None, PeriodType.TTM)
       for r in highlights_records
   ), "BP-577: HIGHLIGHTS row has non-TTM period_type"
   ```
2. **Defense at the JSON dict layer** (lines 105-109): tag every key
   merged from `highlights_data` with a `_periodicity: "ANNUAL_TTM"`
   sibling so downstream T-W1-03 enforcement can refuse to quote it as
   quarterly.

**Acceptance check**:
- New unit test `test_highlights_never_mixed_into_period_revenue` in
  `services/market-data/tests/unit/test_get_fundamentals_history.py`
  (verbatim shape in audit §A3 lines 100-113): seed (HIGHLIGHTS
  net_income=$26.4B TTM, income_statement Q1FY26 revenue=$10.3B);
  assert returned Q1FY26 row has revenue=$10.3B AND that no field in
  the response carries the $26.4B value unlabelled.
- Re-running the Phase-D harmful question against a deployed stack
  produces a quarterly figure in the $5-15B range, not $26.4B.

**Migration**: NO
**Docker rebuild needed**: YES (market-data)
**No-deploy**: NO

##### T-W1-02: NEW `FundamentalsRefreshWorker` + one-shot eval-ticker backfill

**Type**: impl (new worker class) + ops (one-shot backfill script)
**depends_on**: none
**blocks**: cross-cutting acceptance gate

**Target files**:
- `services/content-ingestion/src/content_ingestion/application/workers/fundamentals_refresh_worker.py`
  (NEW file — the audit confirms no such worker exists; grep
  `find services -name "fundamentals_refresh_worker.py"` returns ZERO hits)
- `services/content-ingestion/scripts/backfill_fundamentals.py` (NEW
  one-shot script for the 7 eval tickers — mirrors PLAN-0096 W3's
  `scripts/reconcile_age_temporal_events.py` shape: idempotent,
  `--dry-run` supported, structured logging)
- `services/content-ingestion/tests/unit/application/workers/test_fundamentals_refresh_worker.py`
  (NEW unit test file)

**Audit reference**: `2026-05-27-plan-0097-data-integrity-investigation.md`
§B2 (lines 154-169, missing worker confirmed) + §B3 (lines 172-197,
hypothesis ranking) + §B4 (lines 200-260, fix sketch verbatim).

**What to build**:

1. **New `FundamentalsRefreshWorker` class** (audit §B4 lines 230-245):
   - Schedule: every 6 h (post-market, morning, afternoon, night).
   - Scope: top-500 instruments by market cap (quota burn control).
   - Backoff: exponential on 429 (BP-114 pattern reuse).
   - Publishes `market.dataset.fetched` Kafka events; existing
     `fundamentals_consumer.py:425` consumer already ingests them.
   - Emit telemetry `fundamentals_batch_fetched{count, errors}`.
2. **One-shot backfill script** for the 7 eval tickers (AMD, NVDA,
   AAPL, MSFT, GOOGL, META, TSLA) — direct EODHD call →
   `market.dataset.fetched` publish → consumer ingests. Runs once
   pre-acceptance-gate so the chat-eval sees current FY2026 quarters.
3. **Unit test** (audit §B4 lines 253-260): mock EODHD response with
   quarterly=[2026Q1, 2026Q2] + annual=[2025]; assert Kafka payload
   has `period_type='QUARTERLY'` for Q1/Q2, `'ANNUAL'` for 2025.

**Acceptance check**:
- `SELECT max(period_end_date) FROM income_statements WHERE instrument_id IN (<7 eval tickers>) AND period_type='QUARTERLY'` returns at least one row dated within the last 120 days for every eval ticker.
- Worker unit test passes; backfill script runs cleanly with
  `--dry-run` then for real.
- `kafka-consumer-groups.sh ... --group market-data-fundamentals --describe` shows 0 lag after backfill.

**Migration**: NO
**Docker rebuild needed**: YES (content-ingestion — new worker module)
**No-deploy**: backfill script can run against live; worker rollout
needs a content-ingestion restart

##### T-W1-03: Defense-in-depth — periodicity labels on every annualized field

**Type**: impl
**depends_on**: [T-W1-01]
**blocks**: W1 sign-off
**Target files**:
- `services/rag-chat/src/rag_chat/application/tools/get_fundamentals_history.py` (verify exact path via `find services/rag-chat -name "get_fundamentals_history*.py"`)
- `services/rag-chat/src/rag_chat/application/tools/get_fundamentals_history_batch.py`
- LLM grounding prompt: `libs/prompts/src/prompts/chat/tool_use.py` (per memory: BP-565 prior precedent for adding tool-use safety rules to this file) — add an explicit "if a row carries `periodicity != "QUARTERLY"` and the user asked a quarterly question, DO NOT quote the value" instruction

**Audit reference**: `2026-05-27-plan-0097-data-integrity-investigation.md`
§A2 (lines 33-57, schema inventory + risk levels) + §B4 (defense-in-depth).

**What to build**:

Every row returned by the rag-chat fundamentals tools must carry an
explicit `periodicity` key with one of `{"QUARTERLY","ANNUAL","ANNUAL_TTM"}`
so the LLM cannot accidentally quote an annualized value in a quarterly
context. The tool description + LLM grounding prompt explicitly tell
the model to refuse / re-query if periodicity does not match the user's
intent.

```python
# Example shape change in get_fundamentals_history.py response:
return {
    "rows": [
        {
            "period_end_date": "2026-03-31",
            "periodicity": "QUARTERLY",   # <- new key, mandatory
            "revenue": 7_500_000_000,
            ...
        },
        ...
    ],
}
```

**Acceptance check**:
- Unit test `test_fundamentals_tool_rows_carry_periodicity_key` — every
  row in the response has a non-null `periodicity` ∈ allowed set.
- Unit test `test_fundamentals_batch_tool_rows_carry_periodicity_key` —
  same for the batch tool.
- Phase D harmful question now returns either a quarterly figure with
  `periodicity="QUARTERLY"` OR refuses with "the requested period is not
  available" — never the unlabelled $26.4B.

**Migration**: NO
**Docker rebuild needed**: YES (rag-chat)
**No-deploy**: NO

##### T-W1-04: Real period_type integration test (MOVED from W4 P2 item 2)

**Type**: test (new integration test; keeps existing string-inspection
unit tests for regression coverage per R19)
**depends_on**: none
**blocks**: W1 sign-off

**Target files**:
- `services/market-data/tests/unit/test_fundamentals_query_defaults.py:57-122`
  — current tests `grep` the compiled SQL strings for `"QUARTERLY"`
  (tautological per p2-punchlist audit §2; prove the filter is present
  in SQL but not that it *excludes* ANNUAL rows)
- `services/market-data/tests/integration/test_fundamentals_query_period_type.py`
  (NEW file; integration test seeds the DB)

**Audit reference**: `2026-05-27-plan-0097-p2-punchlist-and-docs.md`
§2 (lines 39-49, verbatim integration-test sketch).

**What to build**:

Verbatim from p2-punchlist audit §2:
- Seed: QUARTERLY revenue=$50B + ANNUAL revenue=$200B at same `period_end_date`.
- Query `income_statement` without explicit `period_type` (relies on
  PLAN-0096 W1 T-W1-01 repository default of QUARTERLY).
- Assert returned revenue == $50B (QUARTERLY shadows ANNUAL).
- Reverse: seed ANNUAL-only; verify the returned value matches.

Keep `test_fundamentals_query_defaults.py:57-122` unchanged (R19 — never
delete tests). This task is **additive**.

**Rationale for the W4 → W1 move**: W1 already owns market-data
data-integrity work (T-W1-01 ships another test in the same test dir);
keeping both period-type tests in one wave avoids two waves racing on
the same `services/market-data/tests/` tree. P2-punchlist audit §2 also
flags it as "data-integrity" rather than "P2 hygiene".

**Acceptance check**:
- New integration test passes both directions (QUARTERLY default, ANNUAL
  explicit override).
- `pytest services/market-data/tests/ -k "period_type"` count goes up
  (existing tautological tests remain green).

**Migration**: NO
**Docker rebuild needed**: NO (test-only)
**No-deploy**: YES

#### Validation gate

- [ ] ruff + mypy clean on `market-data`, `rag-chat`, and `content-ingestion`
- [ ] All existing market-data + rag-chat + content-ingestion unit tests pass
- [ ] New unit/integration tests pass (T-W1-01 x1 + T-W1-02 x1 + T-W1-03 x2 + T-W1-04 x2 = 6 new tests)
- [ ] Docker rebuild of `market-data` + `rag-chat` + `content-ingestion` clean
- [ ] Phase-D harmful question re-run no longer yields HARMFUL verdict
- [ ] FY2026 quarterly coverage verified per T-W1-02 acceptance SQL

**Cross-service test coverage matrix (W1)**:
| Fix | Test file | Why it proves the fix |
|-----|-----------|----------------------|
| T-W1-01 HIGHLIGHTS leak | `services/market-data/tests/unit/test_get_fundamentals_history.py::test_highlights_never_mixed_into_period_revenue` | Seeded ANNUAL net_income=$26.4B + QUARTERLY revenue=$10.3B; asserts response shape never quotes $26.4B as period-level |
| T-W1-02 refresh worker | `services/content-ingestion/tests/unit/application/workers/test_fundamentals_refresh_worker.py` | Mocks EODHD; asserts period_type='QUARTERLY' on Kafka payload for Q1/Q2 |
| T-W1-03 periodicity label | `services/rag-chat/tests/unit/tools/test_get_fundamentals_history_periodicity.py` (+ batch variant) | Every row carries `periodicity` ∈ {QUARTERLY,ANNUAL,ANNUAL_TTM} |
| T-W1-04 real period filter | `services/market-data/tests/integration/test_fundamentals_query_period_type.py` | Seeded mixed-periodicity DB rows; asserts QUARTERLY default shadows ANNUAL |

#### Architecture compliance

- [ ] **R10** — `utc_now()` from `common.time` for any timestamp writes
- [ ] **R12** — structlog for the leak-fix WARN log path
- [ ] **R15** — every code change has a matching docs change (see W4 T-W4-03)
- [ ] **R24** — only `market-data` owns its DDL if T-W1-01 chooses Alembic 022
- [ ] **R32** — Alembic revision 022 sequences after PLAN-0096's 021
- [ ] **BP-393** — no CONCURRENTLY if T-W1-01 adds a column

#### Break impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| Existing rag-chat fundamentals tool consumers (LLM prompt grounding) | Response shape gains a new mandatory `periodicity` key | LLM prompt updated in same wave; downstream LLM treats unknown keys gracefully |
| Tests that assert exact response shape | New `periodicity` key | Update assertions to allow the new key |
| Dashboards reading the highlights table | If T-W1-01 chooses Option A and adds a new column | Add `revenue_ttm_annualized` to relevant dashboard queries |

#### Regression guardrails

- **BP-126** — additive nullable column needs no `server_default` (observational).
- **BP-130** — re-check smoke-test migration-head assertions if T-W1-01 ships 022.
- **BP-393** — additive column migration in default transaction; no CONCURRENTLY.

#### Compounding updates

- `docs/services/market-data.md` — update Fundamentals section to document
  the annualized-leak fix + periodicity contract.
- `services/market-data/.claude-context.md` Pitfalls — new entry on the
  annualized-vs-quarterly distinction in the highlights/snapshot path.
- `docs/services/rag-chat.md` — document the mandatory `periodicity` key
  in fundamentals tool responses.
- `services/rag-chat/.claude-context.md` Pitfalls — new entry: "every
  fundamentals tool row must carry `periodicity`; LLM grounding refuses
  to quote rows where `periodicity` does not match user intent".
- `docs/BUG_PATTERNS.md` — new BP-577 ("HIGHLIGHTS-section leak in
  quarterly response shape; defense-in-depth via `periodicity` label")
  + new BP-578 ("missing FundamentalsRefreshWorker; data never updates
  post-seed").
- `docs/plans/TRACKING.md` — flip PLAN-0097 row state.
- `RULES.md` — no new rule (R36 is added by W4, covers batch-tool
  selection not periodicity contract).
- `CLAUDE.md` — no change.

---

### Wave W2 — Classifier + grader P0 (Q8 SAFE example + regression set + grader updates)

**Goal**: Close the Q8 INPUT_REJECTED false-positive by augmenting the
classifier system prompt with a benign-relationship SAFE example, then
lock the behavior with a 10–15 query regression set. Update the chat-eval
grader to accept the batch tool name as equivalent to the singular tool
name and to relax tool-call assertions on cache-hit + INPUT_REJECTED
verdicts.

**Depends on**: none (independent of W1)
**Estimated effort**: ~3.5 h (30 min prompt fix + 60 min regression set +
                       45 min grader updates + 45 min DEBUG_SKIP_CLASSIFIER
                       + 30 min tests)
**Architecture layer**: rag-chat security + chat-eval harness
**Branch**: `feat/plan-0097-w2`
**Migration**: NO
**Docker rebuild**: YES — `rag-chat`

**File ownership**: W2 owns `services/rag-chat/src/rag_chat/application/security/llm_injection_classifier.py`
**end-to-end** (SAFE example, `classifier_version` bump, AND
`DEBUG_SKIP_CLASSIFIER` env var). W3 does NOT touch this file.

#### Tasks

##### T-W2-01: Classifier system-prompt — Q8 SAFE example

**Type**: prompt
**depends_on**: none
**blocks**: T-W2-02

**Target files**:
- `services/rag-chat/src/rag_chat/application/security/llm_injection_classifier.py:61-93`
  (system-prompt string literal; SAFE-example list at lines 77-87 per
  classifier audit §A2; insert new exemplar AFTER line 86, BEFORE the
  hostile-message clause)

**Audit reference**: `2026-05-27-plan-0097-classifier-grader-investigation.md`
§A1 (lines 9-30, intermittent Q8 INPUT_REJECTED trace) + §A2 (lines
33-53, current SAFE coverage gap) + §A4 (lines 88-114, regression suites).

**What to build**:

Insert the **verbatim** SAFE example from classifier audit §A2 lines
44-50 (preserving the audit's wording so prompt drift is auditable):

```
  - Requests to discover connections, relationships, or paths between entities
    (e.g. 'How is Company A related to Company B?', 'Show me the relationship
    paths', 'Traverse the graph to find connections between X and Y', 'What is
    the supply chain link?'). These are fundamental financial-analysis tasks,
    not instruction-override attempts.
```

Insertion point: after line 86 in the SAFE bullet list, before the
hostile-message clause.

Classifier-version bump is now T-W2-04 sub-step (rather than W4) so W2
owns the whole file end-to-end (avoids W4 → W2 race on
`llm_injection_classifier.py`).

**Acceptance check**:
- Unit test `test_classifier_accepts_q8_relationship_query` in
  `services/rag-chat/tests/unit/security/test_llm_injection_classifier.py`
  (already in git status as modified; extend it) — asserts the Q8 query
  classifies as SAFE.
- See T-W2-02 for the broader regression set.

**Migration**: NO
**Docker rebuild needed**: YES (rag-chat)
**No-deploy**: NO

##### T-W2-02: Regression test set — 10–15 benign discovery/relationship queries

**Type**: test
**depends_on**: [T-W2-01]
**blocks**: T-W2-03

**Target files**:
- `services/rag-chat/tests/unit/security/test_llm_injection_classifier_benign_relationships.py` (new file)

**Audit reference**: `2026-05-27-plan-0097-classifier-grader-investigation.md`
§B2 (regression set).

**What to build**:

A parametrised pytest case with 10–15 benign queries that MUST classify
as SAFE. Suggested coverage:

```python
BENIGN_RELATIONSHIP_QUERIES = [
    "What is the relationship between Apple and Microsoft?",
    "How are Tesla and SpaceX connected?",
    "Discover the link between NVIDIA and AMD.",
    "Are OpenAI and Anthropic competitors?",
    "What deals exist between Google and Samsung?",
    "Show me how Meta is connected to Reality Labs.",
    "Which suppliers does Boeing share with Airbus?",
    "Compare the boards of JPMorgan and Goldman Sachs.",
    "What partnerships does Stripe have with Visa?",
    "How does Berkshire Hathaway relate to Apple?",
    "Find the connection between TSMC and Nvidia.",
    "Are there any cross-holdings between Pfizer and Moderna?",
]

@pytest.mark.parametrize("query", BENIGN_RELATIONSHIP_QUERIES)
def test_benign_relationship_classifies_safe(query: str) -> None:
    ...  # assert verdict == SAFE
```

Each query MUST classify as SAFE; any single fail blocks the W2 commit.

**Acceptance check**:
- All 12+ parametrised cases pass.
- Test runs in <5 s (mock the LLM call to the deterministic SAFE-stamped
  fixture — do NOT actually call the classifier model in unit tests).

**Migration**: NO
**Docker rebuild needed**: NO (test-only)
**No-deploy**: NO

##### T-W2-03: Chat-eval grader updates

**Type**: code (test harness)
**depends_on**: none
**blocks**: cross-cutting acceptance gate

**Target files**:
- `tests/validation/chat_eval/grading.py:352-354` (current exact-match
  tool-call check; verified filename `grading.py`, NOT `grader.py`)
- `tests/validation/chat_eval/grading.py:337-360` (insertion point for
  new `_TOOL_EQUIVALENCES` + `_check_tool_requirement_satisfied()`)
- `tests/validation/chat_eval/grading.py:413-416` (current generic-error
  branch; needs `INPUT_REJECTED` carve-out)
- `tests/validation/chat_eval/test_q4_nvda_amd_revenue.py:70` (per
  classifier audit §B1 table — assertion will pass unchanged once
  grader maps batch → singular)
- `tests/validation/chat_eval/test_grading.py` (existing test file;
  extend with the 4 new cases below)

**Audit reference**: `2026-05-27-plan-0097-classifier-grader-investigation.md`
§B1 (lines 117-145, change table + pseudocode verbatim) + §B2 (lines
147-162, refusal vs INPUT_REJECTED policy).

**What to build**:

Three independent grader-policy changes:

1. **Tool-name equivalence** — accept
   `get_fundamentals_history_batch` as equivalent to
   `get_fundamentals_history` for any tool-call assertion. Backing rule:
   PLAN-0095 W2 introduced the batch tool; PLAN-0097 W3 strengthens the
   intent map to prefer it for multi-ticker questions. The grader must
   reflect that the model is free to choose either.

   ```python
   TOOL_EQUIVALENCE = {
       "get_fundamentals_history": {"get_fundamentals_history", "get_fundamentals_history_batch"},
       # ... other equivalence sets as needed
   }
   ```

2. **Cache-hit + INPUT_REJECTED relax tool-call assertions** — when the
   chat pipeline short-circuits via cache-hit OR via classifier
   INPUT_REJECTED, the LLM never gets the chance to call a tool; the
   grader must not penalise this. Mark the assertion as "N/A" rather
   than FAIL.

3. **Refusal-vs-USELESS policy** — explicit rule: a refusal grounded
   in "data not available" or "out of scope" is USELESS (not FAIL); a
   refusal that misclassifies a SAFE query as injection is FAIL (this
   is the Q8 failure mode we are closing). This is documented in the
   grader docstring + asserted via two new test cases.

**Acceptance check**:
- Unit test `test_grader_accepts_batch_tool_equivalent` — assertion
  passes when the actual tool call was `get_fundamentals_history_batch`
  but the expectation was `get_fundamentals_history`.
- Unit test `test_grader_relaxes_assertion_on_cache_hit` — when the
  response carried a `cache_hit=True` flag, tool-call assertion is "N/A".
- Unit test `test_grader_relaxes_assertion_on_input_rejected` — when
  the verdict is INPUT_REJECTED, tool-call assertion is "N/A".
- Unit test `test_grader_refusal_data_not_available_is_useless` — a
  documented-data-gap refusal scores USELESS, not FAIL.

**Migration**: NO
**Docker rebuild needed**: NO (test-only)
**No-deploy**: NO

##### T-W2-04: Eval-mode classifier short-circuit (`DEBUG_SKIP_CLASSIFIER`) + classifier_version bump (MOVED from W3 T-W3-04; ABSORBS W4 P2 item 6)

**Type**: impl + env + version bump
**depends_on**: [T-W2-01]
**blocks**: cross-cutting acceptance gate

**Target files**:
- `services/rag-chat/src/rag_chat/application/security/llm_injection_classifier.py`
  (Layer 2 entry point — same file W2 already owns. Audit §FIX-B suggests
  `intent_classifier.py` lines 119-136, but the **actual 5-10 s tail-p99
  latency** documented in latency audit §A1 line 22-28 is the L2
  injection classifier's DeepInfra call, NOT the intent classifier.
  Placing the short-circuit at the L2 entry kills the larger latency
  source AND keeps file ownership in W2.)
- `services/rag-chat/src/rag_chat/config.py` (or equivalent
  pydantic-settings file — verify via `find services/rag-chat/src -name "config.py"`) — declare `debug_skip_classifier: bool = False` + `app_env: str`
- `tests/validation/chat_eval/conftest.py` (verified present) — set
  `os.environ["DEBUG_SKIP_CLASSIFIER"] = "true"` for the session
- `services/rag-chat/tests/unit/security/test_llm_injection_classifier.py`
  (already in git status as modified; extend it)

**Audit reference**: `2026-05-27-plan-0097-latency-investigation.md`
§FIX-B (lines 219-244, code template verbatim) + §5 (lines 304-313,
expected -30-40 s eval-mode improvement) + §A1 line 22-28
(L2 injection classifier identified as the 5-10 s sink).

**What to build**:

1. **Eval-mode short-circuit at L2 classifier entry**:
   ```python
   if (
       os.getenv("DEBUG_SKIP_CLASSIFIER") == "true"
       and settings.app_env in {"dev", "test"}
   ):
       logger.warning(
           "classifier_short_circuit",
           reason="DEBUG_SKIP_CLASSIFIER",
           app_env=settings.app_env,
       )
       return ClassifierVerdict.SAFE
   ```
   **Hard safety gate**: BOTH conditions required. Reading
   `app_env` at runtime (not at module import) guards against the
   classic "env was unset at import, then set later" footgun.
2. **`classifier_version` bump** (originally W4 P2 item 6; absorbed
   into W2 so the whole `llm_injection_classifier.py` change is one
   wave): bump the version constant after T-W2-01 prompt edit so the
   on-disk classifier cache invalidates. Single line constant bump.

**Acceptance check**:
- Unit test `test_debug_skip_classifier_honored_in_dev_only` — with
  `app_env="dev"` + env var set, returns SAFE immediately (asserts the
  DeepInfra mock was NOT called); with `app_env="prod"` + env var set,
  runs the full classifier path (mock IS called).
- Unit test `test_classifier_version_constant_matches_current_prompt_hash`
  — computes SHA256 of the prompt text; asserts the version constant
  encodes the current hash prefix. Fails on next prompt change that
  forgets to bump the constant.
- Eval harness sets `DEBUG_SKIP_CLASSIFIER=true`; per-question latency
  drops by 5-10 s (verify via T-W3-01 EXPLAIN + chat-eval run).

**Migration**: NO
**Docker rebuild needed**: YES (rag-chat)
**No-deploy**: NO (env-driven; production unaffected by gate)

#### Validation gate

- [ ] ruff + mypy clean on `rag-chat` and `tests/validation/chat_eval/`
- [ ] All existing rag-chat unit tests pass (including the one already
      modified in git status)
- [ ] New unit tests pass (T-W2-01 x1 + T-W2-02 x12 + T-W2-03 x4 + T-W2-04 x2 = 19 new)
- [ ] Docker rebuild of `rag-chat` clean
- [ ] Q8 re-run via chat-eval — no INPUT_REJECTED
- [ ] With `DEBUG_SKIP_CLASSIFIER=true APP_ENV=dev`, classifier cost ≈ 0 (verify via metrics or trace)

**Cross-service test coverage matrix (W2)**:
| Fix | Test file | Why it proves the fix |
|-----|-----------|----------------------|
| T-W2-01 SAFE example | `services/rag-chat/tests/unit/security/test_llm_injection_classifier.py::test_classifier_accepts_q8_relationship_query` | Asserts Q8 verbatim text classifies as SAFE with mocked LLM |
| T-W2-02 regression set | `services/rag-chat/tests/unit/security/test_llm_injection_classifier_benign_relationships.py` | 12 parametrised benign queries; LLM mocked deterministic SAFE; any single fail blocks commit |
| T-W2-03 grader equivalence | `tests/validation/chat_eval/test_grading.py` (4 new cases per §B1) | Asserts batch→singular acceptance, cache-hit N/A, INPUT_REJECTED N/A, refusal=USELESS |
| T-W2-04 eval-mode bypass | `services/rag-chat/tests/unit/security/test_llm_injection_classifier.py::test_debug_skip_classifier_honored_in_dev_only` | Mock DeepInfra; assert not-called in dev with flag, called in prod with flag |
| T-W2-04 version bump | `services/rag-chat/tests/unit/security/test_llm_injection_classifier.py::test_classifier_version_constant_matches_current_prompt_hash` | Prompt SHA256 prefix matches version constant; fails on prompt drift |

#### Architecture compliance

- [ ] **R12** — structlog for the classifier WARN paths
- [ ] **R19** — never delete tests; T-W2-03 extends existing grader tests
- [ ] **BP-407** — no retry storm risk (prompt change, not network retry)

#### Break impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| Existing classifier cache entries | Prompt change invalidates cache (P2 item 6) | Bump `classifier_version` (W4 T-W4-02) — cache keys roll forward automatically |
| Chat-eval expected verdicts JSON | Q8 was previously INPUT_REJECTED in golden file | Update golden file to expect SAFE / USEFUL |
| Tests that assert exact tool name | Now accept the batch equivalent too | Update assertions per the equivalence map |

#### Regression guardrails

- **BP-407** — no retry storm (prompt-only change).
- **Phase D HARMFUL=1** — W1 owns the HARMFUL fix; W2 closes only the
  Q8 INPUT_REJECTED false-positive, not the harm.
- **Classifier drift risk** — prompt augmentation is additive (new SAFE
  example, no removal); does not regress prior INJECTION detections.
  The 12+ benign regression set defends the SAFE side; existing
  injection-pattern tests defend the UNSAFE side.

#### Compounding updates

- `docs/services/rag-chat.md` — document the SAFE-example expansion and
  the grader policy changes.
- `services/rag-chat/.claude-context.md` Pitfalls — new entry: "benign
  relationship/discovery queries between named entities must classify
  as SAFE; the classifier prompt carries explicit SAFE exemplars
  (PLAN-0097 W2 T-W2-01); regression set in
  `test_llm_injection_classifier_benign_relationships.py` is the gate".
- `tests/validation/chat_eval/README.md` (if exists; else create) —
  document the grader policy: tool-name equivalence, cache-hit /
  INPUT_REJECTED relaxation, refusal-vs-USELESS rule.
- `docs/BUG_PATTERNS.md` — new BP-579 (Q8 INPUT_REJECTED false-
  positive — benign relationship/discovery query rejected as injection;
  fix = SAFE exemplars in classifier prompt + regression set) + BP-581
  (eval-mode `DEBUG_SKIP_CLASSIFIER` short-circuit + APP_ENV gate) +
  BP-582 (batch tool routing + grader equivalence — half-W2 half-W3).
- `docs/plans/TRACKING.md` — flip PLAN-0097 row state.
- `RULES.md` — no new rule.

---

### Wave W3 — Latency P1 (VACUUM ANALYZE + parallelize + intent + eval short-circuit)

**Goal**: Restore chat-eval p99 from 207 s back under the 60 s gate by
(a) refreshing planner stats so the PLAN-0095 composite indexes are
actually used, (b) **verifying** ticker resolution is parallel in the
batch endpoint (audit confirmed it already is — verify-only task), (c)
strengthening the batch tool selection so multi-ticker questions pick
it on the first turn, and (d) sanitizing batch endpoint exception
reasons (MOVED from W4 P2 item 5 — same file as T-W3-02).
Eval-mode classifier short-circuit (originally T-W3-04) was MOVED to
W2 T-W2-04 so `llm_injection_classifier.py` ownership is single-wave.

**Depends on**: none (independent of W1+W2; can run in parallel)
**Estimated effort**: ~3 h (30 min VACUUM migration + 30 min batch
                       parallel verification + 30 min batch endpoint
                       exception sanitization + 45 min intent/description
                       + 45 min tests)
**Architecture layer**: market-data infrastructure + rag-chat application
**Branch**: `feat/plan-0097-w3`
**Migration**: YES — Alembic revision 022 (VACUUM ANALYZE on 14
               fundamentals tables; autocommit block required)
**Docker rebuild**: YES — `market-data` + `rag-chat`

**File ownership**: W3 owns
`services/market-data/src/market_data/api/routers/fundamentals.py`
(both T-W3-02 parallel verification and T-W3-02b exception
sanitization in a single commit) and the new Alembic 022. W3 does
NOT touch `llm_injection_classifier.py` (W2 owns it).

#### Tasks

##### T-W3-01: `VACUUM ANALYZE` on fundamentals tables post-migration 019

**Type**: ops + maybe migration
**depends_on**: none
**blocks**: T-W3-02

**Target files** (single chosen path — Option A per audit §FIX-A):
- NEW `services/market-data/alembic/versions/022_vacuum_analyze_fundamentals.py`
  using `op.get_context().autocommit_block()` (VACUUM cannot run inside
  a transaction). Revision sequences after PLAN-0096's 021 and BEFORE
  W4 T-W4-01 item 3's 023 (`IF NOT EXISTS` retrofit).
- Constants: 14 tables enumerated verbatim in latency audit §FIX-A
  lines 200-211 (with the 4 audit-listed sibling tables removed for
  scope: `splits_dividends`, `outstanding_shares`, `fund_holders`,
  `institutional_holders` — those are non-section tables and are not
  indexed by 019). Final list: `analyst_consensus`, `balance_sheets`,
  `cash_flow_statements`, `dividend_history`, `earnings_annual_trends`,
  `earnings_history`, `earnings_trends`, `highlights`,
  `income_statements`, `insider_transactions_snapshot`,
  `share_statistics`, `splits_dividends`, `technicals_snapshots`,
  `valuation_ratios`.

**Audit reference**: `2026-05-27-plan-0097-latency-investigation.md`
§H1 (lines 67-83, planner stats stale post-019) + §FIX-A (lines
194-216, verbatim bash + VACUUM-vs-VACUUM-FULL note) + §6 BP-567
(rejected — collision with existing BP-567 in BUG_PATTERNS.md; PLAN-0097
ships as BP-580 instead).

**Migration safety note**: VACUUM ANALYZE acquires only `SHARE UPDATE
EXCLUSIVE` (does NOT block reads/writes). Audit §FIX-A line 213
confirms zero-risk; rejects VACUUM FULL.

**What to build** (Option A example):

```python
"""022 — VACUUM ANALYZE fundamentals tables after 019 composite indexes.

After migration 019 created composite (instrument_id, period_end_date ASC)
indexes on the 14 fundamentals section tables, the planner's column
statistics are stale and it still picks the seq-scan plan. A one-shot
VACUUM ANALYZE refreshes pg_statistic so the new indexes win. VACUUM
cannot run inside a transaction, so this revision uses autocommit_block().
"""

def upgrade() -> None:
    with op.get_context().autocommit_block():
        for table in _FUNDAMENTALS_TABLES:
            op.execute(f"VACUUM ANALYZE {table}")

def downgrade() -> None:
    # No-op — stats refresh is non-reversible (and not harmful to leave).
    pass
```

> **Note**: VACUUM ANALYZE acquires a `SHARE UPDATE EXCLUSIVE` lock; it
> does NOT block reads or writes (unlike `VACUUM FULL`). Safe to run on
> live data, but heavy on I/O — run during a low-traffic window if
> possible. CREATE INDEX (in 019) was already CONCURRENTLY so this is
> the analogous follow-up.

**Acceptance check**:
- Pre-fix: `EXPLAIN ANALYZE` of a representative fundamentals query
  shows `Seq Scan` (or low-selectivity Bitmap Index Scan).
- Post-fix: same `EXPLAIN ANALYZE` shows `Index Scan using ix_<table>_instrument_id_period_end_date`.
- Chat-eval rerun — the fundamentals-heavy questions drop from ~15s/each
  to <2s/each.

**Migration**: YES (if Option A) — Alembic 022
**Docker rebuild needed**: YES (if Option A) — `market-data-migrate`
**No-deploy**: NO

##### T-W3-02: VERIFY parallel ticker resolution + ABSORB P2 item 5 exception sanitization (batch endpoint)

**Type**: test (parallel verify) + impl (exception sanitize) — single
commit, single file edit
**depends_on**: none
**blocks**: T-W3-03

**Target files**:
- `services/market-data/src/market_data/api/routers/fundamentals.py:149-169`
  (batch handler `_one(ticker)` + `asyncio.gather` per latency audit §H2)
- `services/market-data/src/market_data/api/routers/fundamentals.py:177-213`
  (batch handler exception branch; line 205 `reason=str(exc)` per
  p2-punchlist audit §5)
- `services/market-data/tests/unit/api/test_fundamentals_batch.py` (verify
  path via `find services/market-data/tests -name "test_fundamentals*"`;
  extend or create)

**Audit reference**:
- Parallel verify: `2026-05-27-plan-0097-latency-investigation.md` §H2
  (lines 85-110, confirms `asyncio.gather` already parallelizes; primary
  bottleneck is VACUUM + classifier, NOT resolution).
- Exception sanitize (ABSORBED FROM W4 P2 ITEM 5): `2026-05-27-plan-0097-p2-punchlist-and-docs.md`
  §5 (lines 78-87, verbatim diff `except InstrumentNotFoundError → reason="instrument_not_found"`
  + bare `except Exception → log.exception(...) + reason="internal_error"`).

**What to build**:

1. **Parallel verification** — no code change expected. Unit test
   `test_batch_endpoint_resolves_tickers_in_parallel` patches the
   `lookup_uc` with deterministic 100 ms `asyncio.sleep`; with 5
   tickers, asserts total wall-clock < 250 ms (parallel) NOT 500 ms
   (sequential). If this test fails, audit §H2 conclusion was wrong
   and PLAN-0098 owns a follow-up. Estimated savings <1 s per
   latency audit.
2. **Exception sanitization** — apply p2-punchlist audit §5 diff
   verbatim to lines 177-213. Both fixes land in the same file edit
   to avoid W3↔W4 file collision on `fundamentals.py`.

**Acceptance check**:
- `test_batch_endpoint_resolves_tickers_in_parallel` passes with
  mocked timings.
- `test_batch_endpoint_unexpected_exception_sanitized` — mock a
  `ValueError`, call batch endpoint, assert response
  `reason="internal_error"` (NOT `str(exc)`) AND `log.exception()` was
  called with full traceback (use `caplog`).
- No regression in existing batch endpoint tests.

**Migration**: NO
**Docker rebuild needed**: YES (market-data)
**No-deploy**: NO

##### T-W3-03: Strengthen batch tool description + intent map

**Type**: prompt + code
**depends_on**: none
**blocks**: cross-cutting acceptance gate

**Target files**:
- `services/rag-chat/src/rag_chat/application/tools/get_fundamentals_history_batch.py` — tool description string
- `services/rag-chat/src/rag_chat/application/tools/intent_inference.py` — intent map

**Audit reference**: `2026-05-27-plan-0097-latency-investigation.md`
§4 — model picks singular tool for multi-ticker questions; cascade of
N separate tool calls inflates p99.

**What to build**:

1. **Tool description** — add an explicit "**USE THIS** when the
   question mentions ≥2 tickers" lead-in (mirror PLAN-0095 W3's
   "DO NOT use for…" anti-pattern carve-outs). Example:

   ```
   USE THIS TOOL when the question mentions ≥2 ticker symbols or asks to
   compare fundamentals across multiple companies. ONE call covers all
   tickers — significantly faster than calling get_fundamentals_history
   per ticker. DO NOT use for single-ticker questions (use
   get_fundamentals_history instead).
   ```

2. **Intent map** — add entries mapping multi-ticker fundamentals
   questions to the batch tool (mirror the 3 new RELATIONSHIP entries
   added in PLAN-0095 W3). Example mappings (revise-prd round fills
   in the exact keys based on the audit):
   - `"compare fundamentals"` → `get_fundamentals_history_batch`
   - `"compare revenue"` → `get_fundamentals_history_batch`
   - `"revenue across"` → `get_fundamentals_history_batch`

**Acceptance check**:
- Unit test `test_intent_map_routes_multi_ticker_fundamentals_to_batch`
  — assert each new intent key maps to the batch tool.
- Eval-shape integration: a hand-crafted "compare AAPL vs MSFT
  fundamentals" question selects the batch tool on the first turn
  (verify via tool-call log in a manual chat-eval pass).

**Migration**: NO
**Docker rebuild needed**: YES (rag-chat)
**No-deploy**: NO

##### T-W3-04: MOVED to W2 T-W2-04

`DEBUG_SKIP_CLASSIFIER` env var ownership moved to W2 (W2 owns
`llm_injection_classifier.py` end-to-end). See T-W2-04 above. This
slot intentionally left as a back-reference for traceability.

#### Validation gate

- [ ] ruff + mypy clean on `market-data` and `rag-chat`
- [ ] All existing tests pass
- [ ] New unit tests pass (T-W3-01 implicit via EXPLAIN check, T-W3-02 x2, T-W3-03 x1)
- [ ] Alembic 022 up→down→up clean (downgrade is no-op per audit §FIX-A line 213)
- [ ] Docker rebuild clean
- [ ] Live: `EXPLAIN ANALYZE` post-VACUUM shows `Index Scan using ix_<table>_instrument_id_period_end_date` (not Seq Scan or single-column index)
- [ ] **Live: chat-eval rerun p99 < 60 s on `tests/validation/chat_eval/test_aggregate_score.py` with `RAG_COMPLETION_CACHE_DISABLED=true` AND `DEBUG_SKIP_CLASSIFIER=true APP_ENV=dev`** (eval-mode value, NOT a production target — production p99 will be higher because the L2 classifier still runs)

**Cross-service test coverage matrix (W3)**:
| Fix | Test file | Why it proves the fix |
|-----|-----------|----------------------|
| T-W3-01 VACUUM | (no unit test) | `EXPLAIN ANALYZE` post-migration shows composite index in use; ad-hoc chat-eval timing drops |
| T-W3-02 parallel verify | `services/market-data/tests/unit/api/test_fundamentals_batch.py::test_batch_endpoint_resolves_tickers_in_parallel` | Mocked timings; asserts <250 ms for 5×100 ms |
| T-W3-02 exception sanitize | `services/market-data/tests/unit/api/test_fundamentals_batch.py::test_batch_endpoint_unexpected_exception_sanitized` | Mocks ValueError; asserts response reason+log content |
| T-W3-03 intent map + description | `services/rag-chat/tests/unit/tools/test_intent_map_routes_multi_ticker_fundamentals_to_batch.py` | Asserts every multi-ticker intent key maps to batch tool |

#### Architecture compliance

- [ ] **R12** — structlog for the short-circuit WARN log
- [ ] **R24** — only `market-data` owns its DDL if T-W3-01 ships 022
- [ ] **R28** — no Kafka changes
- [ ] **R32** — Alembic revision 022 sequences after PLAN-0096's 021
      (collision check with W1 T-W1-01: if W1 also adds 022, W3 takes
      023 — revise-prd round resolves the sequence)
- [ ] **BP-393** — VACUUM ANALYZE needs autocommit_block (not CONCURRENTLY-
      adjacent but same "cannot run in tx" constraint)

#### Break impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| Tests that asserted classifier always runs | New short-circuit | Update assertion to check the env-gate path |
| Tests that asserted sequential ticker resolution | Now parallel | Update timing assertions |
| Production deploys | None — DEBUG_SKIP_CLASSIFIER is APP_ENV-gated | n/a |

#### Regression guardrails

- **BP-393** — VACUUM cannot run inside transaction; use
  `op.get_context().autocommit_block()` if Option A chosen.
- **BP-130** — re-check smoke-test migration-head assertions if 022 ships.
- **BP-407** — no retry storm (latency-side, not network-retry-side).
- **Auth bypass risk** — `DEBUG_SKIP_CLASSIFIER` MUST be APP_ENV-gated;
  no production override path.

#### Compounding updates

- `docs/services/market-data.md` — note the post-migration VACUUM
  requirement; document the ops runbook OR the 022 migration.
- `services/market-data/.claude-context.md` Pitfalls — entry: "after
  any new composite index migration on fundamentals tables, follow
  with `VACUUM ANALYZE` so planner stats refresh; otherwise the index
  is created but unused (BP-580)".
- `docs/services/rag-chat.md` — document the batch-tool routing
  heuristic + `DEBUG_SKIP_CLASSIFIER` env var.
- `services/rag-chat/.claude-context.md` Pitfalls — entry: "multi-ticker
  fundamentals questions MUST route to `get_fundamentals_history_batch`
  via the intent map; tool description leads with `USE THIS`".
- `docs/BUG_PATTERNS.md` — new BP-580 (post-migration VACUUM ANALYZE
  required for planner stats refresh on composite index adoption).
- `docs/plans/TRACKING.md` — flip PLAN-0097 row state.
- `RULES.md` — R36 added in W4 (batch-tool selection rule).

---

### Wave W4 — P2 punch list (reduced scope after re-balancing) + docs

**Goal**: Close the **remaining 5 P2 items** after re-balancing — items
1 (nlp-pipeline sentinel SQL filter), 3 (NEW migration 023 for
`IF NOT EXISTS` retrofit of 019's index DDL), 4 (AGE rollback before
invalidate), 6 (rag-chat deploy-time cache flush), and 7-10 (docs:
R35, R36, market-data.md, MASTER_PLAN.md). Items 2 and 5 were moved
to W1 and W3 respectively to prevent inter-wave file collisions.

**Depends on**: W1, W2, W3 (so the docs commit reflects the final state)
**Estimated effort**: ~2 h (45 min nlp-pipeline + AGE + cache-flush
                       small-fix commits + 45 min docs + 15 min new
                       migration 023 + 15 min validation)
**Architecture layer**: cross-service + docs
**Branch**: `feat/plan-0097-w4`
**Migration**: YES — NEW Alembic revision 023
               `023_make_019_indexes_if_not_exists.py` (sequences AFTER
               W3's 022). Rejects the audit's "edit migration 019
               in-place" suggestion — BP-130 forbids it (re-bring-up DBs
               already past 019 would see no diff).
**Docker rebuild**: YES — touched services (nlp-pipeline +
                    knowledge-graph + rag-chat + market-data for 023)

#### Tasks

##### T-W4-01: NEW Alembic revision 023 — `IF NOT EXISTS` retrofit of 019 indexes (P2 item 3)

**Type**: migration + test
**depends_on**: W3 T-W3-01 (must sequence after 022)
**blocks**: T-W4-03

**Target files**:
- NEW `services/market-data/alembic/versions/023_make_019_indexes_if_not_exists.py`
  (sequences `down_revision = "022"`; verified prior revisions via `ls services/market-data/alembic/versions/` → `019_composite_fundamentals_indexes.py`, `020_snapshot_period_type_columns.py`, `021_instruments_last_fundamentals_ingest_at.py` are committed)

**Audit reference**: `2026-05-27-plan-0097-p2-punchlist-and-docs.md`
§3 (lines 52-61, verbatim diff `op.execute("CREATE INDEX IF NOT EXISTS ...")`).

**Why NOT in-place edit of 019** (rejection of audit's "modify
019_composite_fundamentals_indexes.py" suggestion): BP-130 forbids it
— re-bring-up DBs already past 019 would not re-apply; new ones get
the safe version but the schema diverges silently. PLAN-0097 ships a
new revision that is idempotent against existing 019 state (DROP IF
EXISTS + CREATE INDEX IF NOT EXISTS per index name).

**What to build**:

For each of the 18 composite indexes created by 019: `op.execute(f"DROP
INDEX IF EXISTS {name}"); op.execute(f"CREATE INDEX IF NOT EXISTS {name}
ON {table}(instrument_id, period_end_date ASC)")`. Downgrade: no-op
(safe — 019 still owns the canonical index DDL).

**Acceptance check**:
- Alembic up→down→up clean on a fresh DB.
- Alembic up clean on a DB that already has 019's indexes (DROP IF
  EXISTS + CREATE IF NOT EXISTS pattern is idempotent).
- Unit test `services/market-data/tests/unit/test_migration_023_idempotency.py`
  asserts every index name from 019 is present after 023 applies (use
  `pg_indexes` system catalog).

**Migration**: YES (NEW revision 023)
**Docker rebuild needed**: YES (`market-data-migrate`)
**No-deploy**: NO

##### T-W4-02: nlp-pipeline sentinel filter (item 1) + AGE rollback (item 4) + rag-chat deploy-time cache flush (item 6) — 3 separate small commits

**Type**: 3 separate single-service commits
**depends_on**: none
**blocks**: T-W4-03

**Target files**:
- **Item 1 (sentinel SQL filter — R35)**:
  `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/news_query.py:139`
  (verbatim line cited in p2-punchlist audit §1; the file is also in
  current git status as modified)
- **Item 4 (AGE rollback before invalidate)**:
  `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py:516-525`
  (verbatim `_invalidate_session_connection` function per p2-punchlist
  audit §4)
- **Item 6 (deploy-time cache flush)**:
  `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:456-475`
  (audit §6 startup-flush location) plus the rag-chat entrypoint
  (verify path via `find services/rag-chat -name "main.py" -o -name "entrypoint*"`).
  Note: `classifier_version` bump is OWNED by W2 T-W2-04 (combined into
  the same `llm_injection_classifier.py` edit so the file lives in a
  single wave). W4 item 6 covers only the deploy-time
  `SCAN MATCH rag:completion:* + DEL` scaffolding from audit §6 lines
  95-100 + the BP-572 precondition note update in `docs/BUG_PATTERNS.md`.

**Audit reference**: `2026-05-27-plan-0097-p2-punchlist-and-docs.md`
§1 + §4 + §6.

**What to build**:

- **Item 1** (nlp-pipeline): branch the SQL filter on caller's tenant
  per p2-punchlist audit §1 verbatim diff:
  - if `tenant_id != PUBLIC_TENANT_ID`: `(em.tenant_id == tenant_id) | (em.tenant_id == PUBLIC_TENANT_ID)`
  - else (sentinel caller): `(em.tenant_id.is_(None)) | (em.tenant_id == PUBLIC_TENANT_ID)`
- **Item 4** (knowledge-graph): insert `await session.rollback()` AS
  THE FIRST STATEMENT inside the try block of
  `_invalidate_session_connection`, BEFORE `await session.connection().invalidate()`
  (verbatim diff in p2-punchlist audit §4).
- **Item 6** (rag-chat): deploy-time best-effort
  `SCAN MATCH rag:completion:* + DEL` in the rag-chat startup
  entrypoint; non-blocking on Valkey failure (log warn + continue);
  update BP-572 precondition note in `docs/BUG_PATTERNS.md`.

**Acceptance check**:
- Item 1: 3-row seed test per p2-punchlist §1 acceptance — assert
  visibility for (a) NULL legacy, (b) PUBLIC_TENANT_ID sentinel, (c)
  real_tenant_id row, called by both a real-tenant caller and an
  anonymous (PUBLIC_TENANT_ID) caller.
- Item 4: unit test `test_age_invalidate_calls_rollback_first` mocks
  `AsyncSession`, asserts `rollback().assert_called_once()` happens
  before `invalidate()` (use mock `call_args_list` order assertion).
- Item 6: unit test `test_deploy_time_cache_flush_scans_and_deletes`
  mocks Valkey client; asserts SCAN MATCH + DEL flow on startup;
  failure path logged but does not raise.

**Migration**: NO
**Docker rebuild needed**: YES (nlp-pipeline, knowledge-graph, rag-chat)
**No-deploy**: NO

##### T-W4-03: docs commit (P2 items 7–10 + R35 + R36 + MASTER_PLAN cross-refs)

**Type**: docs (no code change)
**depends_on**: [T-W4-01, T-W4-02, W1, W2, W3]
**blocks**: W4 sign-off

**Target files**:
- `RULES.md` — append R35 + R36
- `docs/services/market-data.md` — batch-endpoint section, periodicity
  contract, post-migration VACUUM note
- `docs/services/rag-chat.md` — classifier SAFE-exemplar policy,
  grader policy, batch-tool routing, DEBUG_SKIP_CLASSIFIER
- `docs/MASTER_PLAN.md` — PLAN-0097 cross-refs in the relevant service
  subsections
- `services/<each>/.claude-context.md` — Pitfalls confirmed (W1/W2/W3
  compounding updates list each)
- `docs/BUG_PATTERNS.md` — confirm all new BP entries are filed

**Audit reference**: `2026-05-27-plan-0097-p2-punchlist-and-docs.md`
§7–§10.

**What to build**:

1. **R35 — sentinel-SQL-filter contract**:
   > Any query or dashboard surfacing per-tenant totals MUST filter
   > out the `PUBLIC_TENANT_ID` sentinel (PLAN-0096 T-W4-01) with
   > `WHERE tenant_id <> common.ids.PUBLIC_TENANT_ID`. The sentinel
   > represents legacy / pre-PLAN-0086 data with no real tenant
   > ownership; surfacing it in tenant-scoped views is a data-leak
   > class bug. (PLAN-0097 W4 T-W4-02 item 1.)

2. **R36 — batch tool selection for multi-entity questions**:
   > When a rag-chat tool surface exposes both a singular and a
   > batch variant (e.g. `get_fundamentals_history` vs
   > `get_fundamentals_history_batch`), the tool description MUST
   > lead with an explicit "USE THIS when …" routing rule, AND the
   > intent map MUST carry entries that route multi-entity questions
   > to the batch variant. Singular cascades for multi-entity
   > questions are a latency-class regression. (PLAN-0097 W3 T-W3-03;
   > PLAN-0095 W2 T-W2-02 + W3 precedent.)

3. **MASTER_PLAN cross-refs**: append one-line pointers to the
   relevant service subsections (market-data §Fundamentals,
   rag-chat §Classifier, rag-chat §Tools).

4. **Per-service `.claude-context.md`**: confirm Pitfalls entries
   promised in W1/W2/W3 compounding updates are all filed.

5. **BUG_PATTERNS.md**: confirm every BP number from W1/W2/W3
   (BP-577..BP-583) is filed.

**Acceptance check**:
- `grep "^R35" RULES.md` returns a hit.
- `grep "^R36" RULES.md` returns a hit.
- `grep "PLAN-0097" docs/MASTER_PLAN.md` returns ≥3 hits (market-data,
  rag-chat classifier, rag-chat tools).
- All BP markers BP-577..BP-583 across W1/W2/W3 compounding updates are
  filed in `docs/BUG_PATTERNS.md`.
- `docs/services/market-data.md` mentions the post-migration VACUUM.
- `docs/services/rag-chat.md` mentions the grader policy + SAFE
  exemplars + DEBUG_SKIP_CLASSIFIER.

**Migration**: NO
**Docker rebuild needed**: NO
**No-deploy**: YES (docs-only)

#### Validation gate

- [ ] ruff + mypy clean on every service touched by T-W4-01 + T-W4-02
- [ ] All existing tests pass
- [ ] New unit tests pass (T-W4-01 x1 migration-idempotency + T-W4-02 x3 small-fix unit tests = 4 new tests + T-W4-03 docs grep checks)
- [ ] Alembic 023 up→down→up clean on fresh DB AND clean apply on a 019-already-applied DB
- [ ] All grep checks in T-W4-03 acceptance return hits
- [ ] No `<TBD>` markers remain anywhere in the plan, docs, or BUG_PATTERNS.md

**Cross-service test coverage matrix (W4)**:
| Fix | Test file | Why it proves the fix |
|-----|-----------|----------------------|
| T-W4-01 023 idempotency | `services/market-data/tests/unit/test_migration_023_idempotency.py` | Asserts pg_indexes shows all 18 names after re-apply on 019-state DB |
| T-W4-02 item 1 sentinel filter | `services/nlp-pipeline/tests/unit/infrastructure/nlp_db/repositories/test_news_query_sentinel_visibility.py` | 3-row seed (NULL+PUBLIC+real); 2 caller types; full visibility matrix |
| T-W4-02 item 4 AGE rollback | `services/knowledge-graph/tests/unit/infrastructure/workers/test_age_invalidate_rollback_first.py` | Mock AsyncSession; assert rollback→invalidate call order |
| T-W4-02 item 6 cache flush | `services/rag-chat/tests/unit/infrastructure/test_deploy_time_cache_flush.py` | Mock Valkey; assert SCAN+DEL flow on startup; failure path logged not raised |

#### Architecture compliance

- [ ] **R15** — every code change in W1/W2/W3 has a matching docs entry
- [ ] **R19** — T-W1-04 augments rather than replaces the tautological tests
- [ ] **R32** — Alembic revision sequencing: 021 (PLAN-0096) → 022 (W3) → 023 (W4)
- [ ] **R35** (new) — sentinel-SQL-filter contract documented + enforced
- [ ] **R36** (new) — batch tool selection contract documented + enforced
- [ ] **BP-130** — Alembic 023 is a NEW revision (not an in-place edit of 019)
- [ ] **BP-393** — Alembic 023 uses idempotent DDL only; no CONCURRENTLY required

#### Break impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| `news_query.py:139` consumers | Visibility semantics now include sentinel rows for real-tenant callers (R35) | Intentional — see W4 T-W4-02 item 1 |
| Tests asserting AGE invalidate has no preceding rollback | T-W4-02 item 4 adds the explicit rollback | Update fixtures to expect rollback→invalidate order |
| `rag:completion:*` Valkey keys | Flushed on rag-chat startup post-deploy | Intentional — closes BP-572 precondition (audit §6) |

#### Regression guardrails

- **R19** — never delete tests; T-W1-04 augments period_type tests.
- **BP-130** — Alembic 023 is a NEW revision, not in-place edit of 019;
  migration head bumps to 023.
- **R15** — every W1/W2/W3 code change must have a docs entry by the
  end of W4 T-W4-03.
- **BP-393** — Alembic 023 uses DROP IF EXISTS + CREATE INDEX IF NOT EXISTS
  (idempotent, no CONCURRENTLY required, no autocommit_block needed).

#### Compounding updates

- `RULES.md` — append R35 + R36 (T-W4-03).
- `docs/services/market-data.md` — batch endpoint, periodicity, VACUUM
  (T-W4-03).
- `docs/services/rag-chat.md` — classifier policy, grader policy,
  batch-tool routing, DEBUG_SKIP_CLASSIFIER (T-W4-03).
- `docs/MASTER_PLAN.md` — PLAN-0097 cross-refs (T-W4-03).
- `services/<each>/.claude-context.md` — confirm Pitfalls (T-W4-03).
- `docs/BUG_PATTERNS.md` — file BP-577..BP-583 (T-W4-03).
- `docs/plans/TRACKING.md` — flip PLAN-0097 row to complete (T-W4-03).
- `CLAUDE.md` — no change.

---

## §5 — Cross-cutting concerns

### Cross-cutting acceptance gate: chat-eval rerun on rebuilt stack

After **W1 + W2 + W3** deploy (W4 is docs-only and not part of the gate):

```bash
# 1. Rebuild affected services
docker compose build market-data rag-chat content-ingestion

# 2. Apply new migrations (W3 ships 022 VACUUM ANALYZE; W4 ships 023 IF NOT EXISTS retrofit; W1 ships NO migrations)
docker compose run --rm market-data-migrate alembic upgrade head

# 3. One-shot eval-ticker backfill (T-W1-02) — populates current FY2026 quarters for the 7 eval tickers via FundamentalsRefreshWorker direct invocation
docker compose run --rm content-ingestion python scripts/backfill_fundamentals.py

# 4. Restart the stack
docker compose up -d market-data rag-chat content-ingestion

# 5. Run the aggregate gate with eval-mode env (DEBUG_SKIP_CLASSIFIER is an EVAL-ONLY value — production p99 will be higher because the L2 classifier still runs)
RAG_CHAT_BASE_URL=http://localhost:8000 \
RAG_COMPLETION_CACHE_DISABLED=true \
DEBUG_SKIP_CLASSIFIER=true \
APP_ENV=dev \
  pytest tests/validation/chat_eval/test_aggregate_score.py -v
```

**Pass criteria** (gates the closure of PLAN-0097 W1+W2+W3):

- `verdicts` count ≥ 6 USEFUL (up from 14 - 6 = 8 currently USEFUL, target is ≥ 14/20 ≈ 70%).
  > Specifically: of the 6 currently-failed verdicts, at least the
  > harmful one (W1) and the Q8 INPUT_REJECTED (W2) must convert to
  > USEFUL. The remaining 4 latency-induced timeouts should convert
  > naturally as W3 lands.
- `verdicts.HARMFUL == 0`.
- **`latency.p99_seconds < 60` on chat-eval `test_aggregate_score.py`
  with `RAG_COMPLETION_CACHE_DISABLED=true` AND
  `DEBUG_SKIP_CLASSIFIER=true APP_ENV=dev`** (down from 207 s in Phase D).
  NOTE: this is the **eval-mode** value with the classifier bypassed —
  NOT a production SLO. Production p99 will be higher (5-10 s additional
  per question from the L2 classifier); production SLO is owned by PLAN-0075.
- **No INPUT_REJECTED on Q8-class** (benign relationship/discovery
  queries between named companies).

If the run fails, root-cause-analyse against the per-wave investigation
audits before adding more code — each wave has a narrow remit and a
failure pinpoints which one regressed.

### Other cross-cutting items

- **Contract changes** (all additive):
  - rag-chat fundamentals tools' response gains a `periodicity` key per
    row (W1 T-W1-03).
  - rag-chat fundamentals batch handler sanitizes exception reasons
    (W3 T-W3-02 absorbed P2 item 5).
  - `RULES.md` gains R35 + R36 (W4 T-W4-03).
- **Migration needs** (final after re-balancing):
  - **022** (W3 T-W3-01) — `VACUUM ANALYZE` on the 14 fundamentals
    section tables using `op.get_context().autocommit_block()`.
    Sequences after PLAN-0096's 021.
  - **023** (W4 T-W4-01) — `IF NOT EXISTS` retrofit of 019's 18
    composite indexes (DROP IF EXISTS + CREATE IF NOT EXISTS).
    Sequences after 022.
  - W1 ships NO migrations (HIGHLIGHTS fix is application-layer only).
- **Event flow changes**: NEW publisher (W1 T-W1-02
  `FundamentalsRefreshWorker` publishes `market.dataset.fetched` every
  6 h for top-500 instruments by market cap). Consumer unchanged.
- **Configuration changes**:
  - rag-chat: new `DEBUG_SKIP_CLASSIFIER` env var (APP_ENV-gated;
    OWNED by W2 T-W2-04).
  - chat-eval harness: `tests/validation/chat_eval/conftest.py` sets
    `DEBUG_SKIP_CLASSIFIER=true` for the session.
  - content-ingestion: FundamentalsRefreshWorker schedule constants
    (top-N, cadence) via pydantic-settings.
  - No new secrets.
- **Documentation updates**: see per-wave Compounding updates +
  W4 T-W4-03 single docs commit.

## §6 — Risk assessment

- **Critical path**: W1 + W2 + W3 are all pre-requisites for the
  cross-cutting acceptance gate. W4 is docs-only; can land anytime
  before plan close.
- **Highest-risk task**: T-W3-01 (`VACUUM ANALYZE`).
  - **Why**: Acquires `SHARE UPDATE EXCLUSIVE` lock; safe vs reads + writes
    but heavy on I/O. If misapplied as `VACUUM FULL`, takes ACCESS
    EXCLUSIVE and blocks all reads.
  - **Mitigation**: never `VACUUM FULL`; always plain `VACUUM ANALYZE`.
    Run during low-traffic window if Option A (Alembic). Document in
    runbook if Option B (ops one-shot).
- **Second-highest**: T-W2-01 (classifier prompt drift).
  - **Why**: Prompt changes can have non-obvious effects on the UNSAFE
    side (regression: previously-detected injection now classified SAFE).
  - **Mitigation**: T-W2-02 only adds SAFE exemplars (additive on the
    SAFE side); existing injection-pattern tests defend the UNSAFE side.
    Run the full classifier test suite before commit.
- **Third-highest**: T-W4-02 item 1 (sentinel SQL filter migration timing).
  - **Why**: Adding `WHERE tenant_id <> PUBLIC_TENANT_ID` to live
    dashboards mid-traffic might temporarily change visible totals.
  - **Mitigation**: deploy during low-traffic window; pre-deploy
    communication to dashboard consumers if any are operator-facing.
- **Fourth-highest**: T-W1-01 (the $26.4B source fix).
  - **Why**: Until the audit lands, the exact source is unknown; the fix
    surface could be larger than estimated.
  - **Mitigation**: revise-prd round resolves the placeholder before
    implementation begins; effort estimate (45 min) is conservative.
- **Auth-bypass risk** (T-W3-04 `DEBUG_SKIP_CLASSIFIER`).
  - **Why**: If the APP_ENV gate is missing or misconfigured, the flag
    becomes a remote classifier-bypass primitive.
  - **Mitigation**: unit test `test_debug_skip_classifier_honored_in_dev_only`
    explicitly asserts the gate; security review on the W3 commit
    must verify.
- **Rollback strategy**:
  - W1: revert the source-fix commit (the HARMFUL verdict returns —
    known failure mode, not a worse regression); the `periodicity` key
    is additive on the response shape and safe to leave in place if
    only T-W1-01 is rolled back. Alembic downgrade if a revision shipped.
  - W2: revert the classifier prompt commit (Q8 INPUT_REJECTED returns
    — known failure mode). Grader updates are independent and can stay.
  - W3: Alembic downgrade is a no-op (stats refresh is non-reversible
    and not harmful). Revert the parallelize commit if it regresses
    behaviour. `DEBUG_SKIP_CLASSIFIER` is env-driven — unset to roll back.
  - W4: docs revert is safe; R35/R36 can be removed without code impact;
    sentinel-filter additions are individual reverts.
- **Testing gaps**: no CI-level chat-eval gate (run is operator-driven —
  same as PLAN-0096 §6). Acceptable for this remediation cycle.
- **Deployment risks**:
  - **CREATE INDEX lock**: T-W3-01 VACUUM ANALYZE takes a SHARE UPDATE
    EXCLUSIVE lock — safe vs reads + writes; safer than the original
    PLAN-0095 T-W1-03 CREATE INDEX CONCURRENTLY.
  - **Classifier prompt drift** (T-W2-01): see "Second-highest" risk.
  - **Sentinel SQL filter migration timing** (T-W4-02 item 1): see
    "Third-highest" risk.

## §7 — Compounding step

> **BP-number collision check (revise-prd round)**: the source audits
> proposed BP-562, BP-563, BP-567, BP-568, BP-577, BP-578. Of these,
> **BP-562 / BP-563 / BP-567 / BP-568 are already taken** in
> `docs/BUG_PATTERNS.md` (BP-562 = DeepInfra 30s timeout; BP-563 = L1
> regex false-positives; BP-567 = lifespan assertion env seeding;
> BP-568 = migration not run live). PLAN-0096 introduced
> BP-574/575/576. PLAN-0097 takes **BP-577..BP-582** (next free range
> after BP-576).

- **New bug patterns** to add to `docs/BUG_PATTERNS.md`:
  - **BP-577** (data-integrity audit §A — KEPT as proposed) — $26.4B
    HIGHLIGHTS-section leak: `find_by_section(HIGHLIGHTS)` without
    `period_type` filter exposes TTM/ANNUAL values as period-level data
    in chat tool responses; defense-in-depth via `periodicity` label on
    every fundamentals tool row (W1 T-W1-01 + T-W1-03)
  - **BP-578** (data-integrity audit §B — KEPT as proposed) — no
    `FundamentalsRefreshWorker` exists; consumer is event-driven only;
    all fundamentals stale post-seed. FIX: new worker publishes
    `market.dataset.fetched` every 6 h for top-500 instruments (W1 T-W1-02)
  - **BP-579** (classifier audit — was BP-562 in audit, RENUMBERED due
    to collision with existing BP-562) — classifier false-positive on
    benign relationship/discovery queries between named companies; fix
    via SAFE exemplar in classifier system prompt + 12-query
    regression set (W2 T-W2-01 + T-W2-02)
  - **BP-580** (latency audit — was BP-567 in audit, RENUMBERED due to
    collision with existing BP-567) — composite index migration without
    post-migration `VACUUM ANALYZE` leaves planner stats stale; the
    index is created but unused; follow every composite-index migration
    with a VACUUM ANALYZE revision (autocommit_block) (W3 T-W3-01)
  - **BP-581** (latency audit — was BP-568 in audit, RENUMBERED due to
    collision with existing BP-568) — eval-mode L2 classifier pays full
    DeepInfra cost (5-10 s tail p99) for every test; cache disabled by
    design; FIX: `DEBUG_SKIP_CLASSIFIER` env var gated on
    `app_env in {"dev","test"}` (W2 T-W2-04, MOVED from W3)
  - **BP-582** (classifier/grader audit §B + latency audit) —
    multi-tool agent tool-choice misroutes multi-ticker fundamentals to
    the singular tool when batch description / intent map lack explicit
    "USE THIS when ≥2 tickers" routing; grader must accept batch as
    equivalent to singular (W2 T-W2-03 grader, W3 T-W3-03 tool
    description; R36 codifies)
  - **BP-583** (P2-punchlist audit §1) — sentinel rows
    (`PUBLIC_TENANT_ID`) silently invert visibility in tenant-scoped
    SQL filters; legacy NULL articles become invisible to real tenants
    after the W4 sentinel migration; fix: branch the WHERE clause on
    caller's tenant identity (W4 T-W4-02 item 1; R35 codifies)
- **New rules** (`RULES.md`):
  - **R35** — sentinel SQL filter contract (W4 T-W4-03; codifies BP-548
    follow-up).
  - **R36** — batch tool selection for multi-entity questions
    (W4 T-W4-03; codifies PLAN-0095 W2 + W3 precedent + PLAN-0097 W3).
- **No CLAUDE.md change** — workflow unchanged.
- **TRACKING.md**: append PLAN-0097 row (see below for content). Flip
  status across wave lifecycle.
- **REVIEW_CHECKLIST.md**: confirm the Phase-D verdict-gate checklist
  item is present (no change needed — already covered by general QA
  checklist).
- **MASTER_PLAN.md cross-refs**: W4 T-W4-03 adds ≥3 PLAN-0097 pointers.

---

## Owner

**Owner**: TBD (assign at implementation start). Suggested split:
data-platform engineer for W1 (mirrors PLAN-0095 W1 + PLAN-0096 W1
ownership pattern); rag-chat engineer for W2 (security + harness
domain knowledge); platform engineer for W3 (Postgres ops + batch
endpoint + classifier middleware); cross-functional + docs engineer
for W4 (3 small commits + 1 docs commit; lower technical depth, higher
breadth).
