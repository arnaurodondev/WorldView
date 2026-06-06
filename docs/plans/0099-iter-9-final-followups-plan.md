---
id: PLAN-0099
title: ITER-9 Final Follow-ups — Latency Gate Closure + Pipeline Tails + MARGINAL Q1/Q2 + Phase-D P2 Punch List + Docs Hygiene
prd: inline (see §0)
status: draft
created: 2026-05-25
updated: 2026-05-25
source_audits:
  - docs/plans/0098-iter-9-pipeline-and-cleanup-plan.md (what shipped + what's still open after PLAN-0098 W1/W3 + partial W2)
  - docs/audits/2026-05-27-plan-0098-batch-rowmix-and-latency.md (W1 here — iterator misalignment at fundamentals.py:230-254 + LLM-dominated 289s decomposition)
  - docs/audits/2026-05-27-plan-0098-data-pipelines-and-bp-583-investigation.md (W2 here — §A3 AGE sync, §A4 worker gap, §A5 revenue JSONB)
  - docs/audits/2026-05-27-plan-0097-unblock-chat-eval.md (Q1-Q4 baseline + 289s latency context)
  - docs/audits/2026-05-27-plan-0098-phase-d-code-review.md (10-item PLAN-0099 punch list — §13)
  - /tmp/chat_eval_PLAN0098.log (full 9/9 run: 7 USEFUL / 2 MARGINAL / 0 HARMFUL / median 38.73s / p99 133.19s — gates failed on latency only)
---

# PLAN-0099 — ITER-9 Final Follow-ups (latency gate + pipeline tails + MARGINAL closures + P2 punch list + docs)

## §0 — Inline PRD

> No separate PRD. This plan closes the final remaining items after
> PLAN-0098 shipped W1 (R40 chunk_search), W3 (BP-585 screen_field
> coercion), and partial W2 (T-W2-01 NLP tenant_id stamping with
> safety net + counter still owed). The PLAN-0098 acceptance gate ran
> end-to-end on `/tmp/chat_eval_PLAN0098.log` with the four eval env
> flags and produced **7 USEFUL / 0 HARMFUL / median 38.73s / p99
> 133.19s** — quality bars met, **latency bars not**. PLAN-0099 is
> the umbrella plan to: (a) close both latency gates (W1), (b) drain
> the four PLAN-0098 W2 pipeline tails that were deferred
> (T-W2-02..04 + the silent-stats counter), (c) lift the two MARGINAL
> verdicts on Q1 ("Apple competitors" missing Samsung/Huawei/Microsoft/
> Google/Xiaomi) and Q2 ("MSTR news" missing Bitcoin/BTC) to USEFUL
> (W3), (d) land the 10-item Phase-D P2 punch list (W4), and (e)
> sweep doc drift + consider promoting the W2 safety-net pattern to
> a rule R42 (W5).

### Problem statement

After PLAN-0098 the verdict counts are healthy (7 USEFUL, 0 HARMFUL,
≥6 threshold met, HARMFUL=0 threshold met). The chat-eval acceptance
gate still **FAILS** on two latency gates and **two MARGINAL** verdicts
remain.

Open failure classes:

1. **P0 — Latency gate FAIL** (median 38.73s > 30s; p99 133.19s > 60s).
   The batch-and-LLM round-trip dominates. Root cause split:
   (a) the batch tool can still desync rows because the iterator-fetch
       at `services/market-data/src/market_data/api/routers/fundamentals.py:230-254`
       advances `next(fetch_iter)` only when `task is not None` but
       `asyncio.gather` returns one outcome per *pending* task — a
       failed-resolve ticker mid-list silently shifts every subsequent
       row's outcome (BP-587 latent path, still latent because PLAN-0098
       W5 was never started); (b) the 3 intra-ticker section reads
       inside `GetFundamentalsHistoryUseCase` (lines 83-100:
       earnings_history + income_statement + highlights) serialize
       inside the use case — audit estimates 10-15% wall-clock per call,
       100s+ saved across the eval suite; (c) the second-turn LLM call
       (table generation post-tool) is unmeasured — no per-phase
       instrumentation in `chat_orchestrator.py` exists today, so we
       cannot tell whether the win from (a)+(b) closes the gap or a
       model swap is needed (deferred to PLAN-0100 once data lands).

2. **P1 — PLAN-0098 W2 tails (T-W2-02..04 + counter)** never started:
   AGE TemporalEvent SQL↔Cypher drift (§A3); no
   `FundamentalsRefreshWorker` (§A4 — `scripts/refresh_fundamentals.py`
   from PLAN-0097 W1-T4 is still manual-only); revenue JSONB consumer
   payload-empty write (§A5); and the silent-stats counter
   `nlp_pipeline_pre_persist_tenant_id_substituted_total` recommended
   by the Phase-D code review §10 to make PLAN-0098 W2's safety net
   observable.

3. **P1 — Two MARGINAL chat-eval verdicts**: Q1 missed Samsung/Huawei/
   Microsoft/Google/Xiaomi competitor mentions; Q2 missed Bitcoin/BTC
   in MSTR news. Both need investigation-first (is it a prompt gap, a
   KG narrative gap, a content-ingestion freshness gap, or a search
   ranking gap) before a fix can be scoped.

4. **P2 — 10-item Phase-D code-review punch list** from
   `docs/audits/2026-05-27-plan-0098-phase-d-code-review.md` §13.
   Bundled into 3-4 commits by area.

5. **P3 — Doc/rule hygiene**: `R36 → R41` cosmetic drift still in
   some service docs; PLAN-0097 14→18 fundamentals tables note not
   uniformly propagated; PLAN-0098 batch typed reason codes not in
   all service docs. Plus a rule-promotion candidate (R42 — consumer
   construction-site tenant_id contract).

### Goals

1. Close BOTH chat-eval latency gates (median < 30s, p99 < 60s) via
   W1 row-mix fix + intra-ticker parallelization + per-phase
   instrumentation (the latter as diagnostic input for PLAN-0100).
2. Drain the four PLAN-0098 W2 pipeline tails so live SLO is clean.
3. Bump USEFUL count from 7 → 9/9 by closing Q1 + Q2 MARGINAL.
4. Land all 10 Phase-D P2 punch-list items in ~3-4 commits.
5. Bring service docs back in sync; consider R42 promotion.

### Non-goals

- Swapping the second-turn LLM model (deferred to PLAN-0100 once
  T-W1-03 instrumentation lands data).
- Re-architecting the NLP consumer (PLAN-0098 W2 T-W2-01 safety-net is
  load-bearing; this plan only adds the counter).
- New PRD features.

### Open questions

- W1 T-W1-03: which exact phases (classifier / first-LLM / tool fan-out
  / second-LLM / streaming) dominate? Answered post-deploy by the
  per-phase wall-clock log lines.
- W3 T-W3-01 + T-W3-02: prompt-tweak vs data-gap classification —
  resolved by inspecting the live tool result for Apple and MSTR.
- W2 T-W2-02: is the AGE sync worker registered but not invoked
  post-restart, OR not registered at all? §A3 noted both as
  candidates; reconcile script's `--dry-run` will disambiguate.

---

## §1 — Overview

**PRD**: inline (above)
**Services affected**: market-data (S2), rag-chat (S8), nlp-pipeline
                       (S6), knowledge-graph (S7), content-ingestion
                       (S4), docs
**Total waves**: **5** (W1 latency / W2 pipeline tails / W3 MARGINAL
                  closures / W4 P2 punch list / W5 docs hygiene)
**Total estimated effort**: ~14 h engineering + 1 full docker rebuild
                            cycle + 1 chat-eval rerun (~10 min full
                            suite)
**Critical path**: W1 (gates the acceptance criteria); W2 + W3 needed
                    to call PLAN-0099 fully done.

### Branch & commit hygiene

Land on `feat/plan-0099-final-followups` (or rebase onto the active
in-progress branch). Each wave gets its own commit set; W4 explicitly
bundles 3-4 commits by area to avoid mega-commits.

## §2 — Dependency Graph

```
        ┌──────────────────────────────────────────────────────┐
        │ PLAN-0098 W1 + W3 + partial W2 in main (T-W2-01      │
        │ NLP tenant_id stamping shipped; T-W2-02..04 deferred │
        │ here); chat-eval baseline = 7 USEFUL / 2 MARGINAL /  │
        │ 0 HARMFUL / median 38.73s / p99 133.19s              │
        └──────────────────────────┬───────────────────────────┘
                                   │
       ┌──────────────┬────────────┼────────────┬──────────────┐
       ▼              ▼            ▼            ▼              ▼
   W1 (latency    W2 (PLAN-0098  W3 (MARGINAL  W4 (P2 punch  W5 (docs
   gate P1 —      W2 tails —    Q1+Q2 →       list — 10      hygiene +
   row-mix +      AGE sync,     USEFUL —      items in       R42 promotion)
   parallel       worker,       prompt or     3-4 commits)
   sections +     revenue,      data gap)
   instrument.)   counter)
       │              │             │             │              │
       └──────┬───────┴─────┬───────┘             │              │
              ▼             ▼                     │              │
       Cross-cutting acceptance gate (§5):        │              │
       chat-eval full suite rerun with four env   │              │
       flags. Pass criteria: USEFUL ≥7 (already   │              │
       met; ideally 9 if W3 lands), HARMFUL=0     │              │
       (already met), median<30s, p99<60s. W1     │              │
       closes both latency gates. W2 satisfies    │              │
       the live SLO pre-gate.                     │              │
                                                  │              │
       (W4 independent — code/test hygiene) ◄─────┘              │
       (W5 independent — docs/rule) ◄────────────────────────────┘
```

W1 + W2 are on the critical path for the acceptance gate. W3 is
critical for the verdict bump; W4 and W5 are hygiene.

## §3 — Codebase State Verification

| Reference | Type | Service | Actual current state | Plan target | Delta |
|-----------|------|---------|----------------------|-------------|-------|
| Fundamentals batch handler iterator | code | market-data | `services/market-data/src/market_data/api/routers/fundamentals.py:235-269` — `fetch_iter = iter(fetch_results)` + `next(fetch_iter)` only when `task is not None`. `asyncio.gather(*pending)` returns N=len(pending) outcomes (per audit §A — preserves input task order). When N_pending < N_fetch_tasks (a resolve failed), the iterator drift only manifests if asyncio.gather reorders OR if a task is skipped mid-loop. The audit confirms order is preserved, but the structure is brittle: any future addition that mutates `fetch_iter` consumption asymmetrically with the `continue` branches re-introduces the bug | replace iterator with indexed/zipped access keyed by ticker so the row→ticker binding is structural, not positional | code + integration test |
| GetFundamentalsHistoryUseCase intra-ticker section reads | code | market-data | `services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py:83-108` — 3 sequential `find_by_section` calls (EARNINGS_HISTORY at line 105-108 + INCOME_STATEMENT later + HIGHLIGHTS later). Audit estimates 10-15% per-call wall-clock reduction via `asyncio.gather` | wrap the 3 reads in `asyncio.gather`; serial bound (3 × ~100ms each) becomes ~max(~100ms) | code + asyncio-Event barrier test |
| Chat orchestrator per-phase wall-clock instrumentation | code | rag-chat | `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` — no per-phase timing emitted today; only total wall-clock is logged | add structlog `event=chat_phase_timing` lines for classifier / first-LLM / tool fan-out / second-LLM / streaming so the next eval artifact decomposes 38.73s and 133.19s | code + log assertion test |
| AGE TemporalEvent sync | runtime + ops | knowledge-graph | per PLAN-0098 W2 §A3: PLAN-0096 W3 connection-invalidate fix shipped; reconcile script exists at `services/knowledge-graph/scripts/reconcile_age_temporal_events.py`; sync worker not invoked post-restart | run `--dry-run` first to confirm drift scope, then wet run; investigate sync worker registration in `services/knowledge-graph/src/knowledge_graph/app.py` (or wherever workers register) | ops + (likely) small wire-up |
| FundamentalsRefreshWorker | code | content-ingestion | per PLAN-0098 W2 §A4: no proper worker exists; `scripts/refresh_fundamentals.py` (PLAN-0097 W1-T4) is manual-only; BP-578 MITIGATED not FIXED | new `services/content-ingestion/src/content_ingestion/infrastructure/workers/fundamentals_refresh_worker.py` — 6h cadence top-N by market-cap; exponential backoff on 429 (BP-114); `FUNDAMENTALS_REFRESH_ENABLED` env flag | new worker + lifespan registration + Prom metric + test |
| Revenue JSONB hydration | code | market-data | per PLAN-0098 W2 §A5: `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py` writes rows with `data={}` — Avro field mapping bug OR EODHD fallback path | pick an offending earnings_history row with `data={}`, find the source instrument, replay through consumer, trace where revenue is dropped, fix mapping | code + consumer test |
| Pre-persist tenant_id Prom counter | code | nlp-pipeline | per Phase-D code review §10: PLAN-0098 W2 T-W2-01 safety net only emits structlog WARN; no metric. Will be invisible week-over-week | add `nlp_pipeline_pre_persist_tenant_id_substituted_total{block_source}` counter at the substitution site; cardinality limit `block_source` to a small enum (3-5 buckets max) | code + metric registration test |
| Q1 "Apple competitors" verdict | runtime | rag-chat + knowledge-graph | per `/tmp/chat_eval_PLAN0098.log`: model called `get_entity_intelligence` (correct tool selection) but response did not mention any of Samsung/Huawei/Microsoft/Google/Xiaomi. Investigation needed to classify | reproduce against the live tool — is the competitor list in the KG narrative? If yes → prompt tweak. If no → data gap to KG (different problem class) | investigate + likely prompt or KG follow-up |
| Q2 "MSTR news" verdict | runtime | rag-chat + content-ingestion + nlp-pipeline | per `/tmp/chat_eval_PLAN0098.log`: `search_documents ×2, search_claims` called; Bitcoin/BTC missing in response. Investigation needed | verify recent MSTR-Bitcoin articles exist in nlp_db; if yes → search ranking gap; if no → content-ingestion freshness gap | investigate + likely ranking or ingestion follow-up |
| Phase-D code-review P2 punch list (10 items) | mixed | nlp-pipeline + rag-chat + market-data + knowledge-graph + docs + working tree | per `docs/audits/2026-05-27-plan-0098-phase-d-code-review.md` §13: 10 items including stash-marker scrub, BP-584 file, observability counter (folded into W2 above), `or PUBLIC_TENANT_ID` defensive, TRACKING.md discipline, working-tree contamination (portfolio/internal.py + migration 019), R36→R41 sweep, others | bundle into 3-4 commits by area: tests/flake, defensiveness, docs/tracking, working-tree cleanup | code + tests + docs |
| R36/R41 references in service docs | docs | docs/services/*.md | per Phase-D code review §8: cosmetic mismatches; PLAN-0097 R40+R41 + PLAN-0098 W3 BP-585 not uniformly reflected; PLAN-0097 14→18 fundamentals tables note not uniformly propagated; PLAN-0098 batch typed reason codes not in all service docs | sweep + correct | docs |
| R42 rule promotion candidate | docs | RULES.md | per W2 safety-net pattern: every consumer constructing mentions from Avro payloads should default null tenant_id to PUBLIC_TENANT_ID at the persist boundary. Recurring class (BP-575 + BP-586) | add R42 with rationale + audit pointer | docs |

## §4 — Sub-Plans

---

### Wave W1 — Latency gate P1 (close median < 30s + p99 < 60s)

**Goal**: Close both chat-eval latency gates by removing the iterator
brittleness, parallelizing intra-ticker section reads, and adding
per-phase wall-clock instrumentation so PLAN-0100 can decide whether
a second-turn model swap is needed.

**Depends on**: PLAN-0098 W1 + W3 + partial W2 in main.
**Estimated effort**: ~4 h (T-W1-01 ~1 h + T-W1-02 ~1 h + T-W1-03 ~2 h
                       diagnostic; T-W1-04 deferred to PLAN-0100).
**Architecture layer**: market-data api + market-data application use
                        cases + rag-chat application use case
                        (orchestrator).
**Branch**: `feat/plan-0099-w1`
**Migration**: NO
**Docker rebuild**: YES — market-data + rag-chat
**No-deploy variant**: T-W1-03 instrumentation is safe to ship without
                        a backend behaviour change but must be deployed
                        to surface data — listed as deploy-required.

#### Tasks

##### T-W1-01: Fix batch tool row-mix at `fundamentals.py:230-254`

**Type**: impl + integration test
**Audit ref**: `docs/audits/2026-05-27-plan-0098-batch-rowmix-and-latency.md`
**File**: `services/market-data/src/market_data/api/routers/fundamentals.py`
              lines **230-254** (current iterator construction) and the
              surrounding result-assembly loop.

**Root cause** (audit §A): `fetch_iter = iter(fetch_results)` is
advanced via `next(fetch_iter)` only when `task is not None`. Today
this works because `asyncio.gather` preserves input order and `pending`
is built in the same loop iteration order, but the binding is
positional, not structural. Any future change that mutates the
iterator-consumption asymmetry with the `continue` branches (or any
ordering bug in `asyncio.gather`) silently desyncs the row→ticker map.

**What to build**:
1. Replace iterator with indexed/zipped access keyed by ticker. Use a
   parallel `dict[str, FetchOutcome]` indexed by ticker built from
   `zip(pending_tickers, fetch_results, strict=True)`; the assembly
   loop then looks up by ticker, not by iterator position.
2. Drop the `fetch_iter` variable and the `next(fetch_iter)` call.
3. Add an integration test
   `services/market-data/tests/integration/test_fundamentals_batch_mixed_resolution_outcomes.py`
   with **1 invalid + 1 valid ticker**:
   - Request `tickers=["INVALID_XYZ_999", "NVDA"], periods=4`.
   - Assert `result.results["INVALID_XYZ_999"].status == "error"` with
     `reason == "invalid_ticker"` (per PLAN-0097 W3 typed reason codes).
   - Assert `result.results["NVDA"].status == "ok"` and that NVDA's
     periods match the singular endpoint output for NVDA exactly.
   - Assert that no row from the invalid ticker bleeds into NVDA's
     columns (defensive: shape-check that NVDA period values are
     non-None numeric, not the sentinel error reason string).

**Acceptance check**: integration test passes; manual repro
`curl /v1/fundamentals/batch?tickers=INVALID,NVDA&periods=4` returns
NVDA's own data without cross-ticker bleed.

**Migration**: NO. **Docker rebuild**: YES — market-data.

##### T-W1-02: Parallelize the 3 intra-ticker section reads in `GetFundamentalsHistoryUseCase`

**Type**: impl + asyncio-Event barrier test
**Audit ref**: `docs/audits/2026-05-27-plan-0098-batch-rowmix-and-latency.md` §B
              ("Optimization Opportunity").
**File**: `services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py`
              lines **83-100** (current sequential `find_by_section`
              calls for EARNINGS_HISTORY at 105-108 + INCOME_STATEMENT
              + HIGHLIGHTS).

**Root cause**: per audit §B, the 3 section reads serialize inside
the use case. Audit estimates 10-15% wall-clock per call; across a
batch fan-out the cumulative win compounds.

**What to build**:
1. Wrap the 3 `find_by_section` calls in `asyncio.gather`:
   ```python
   earnings_records, income_records, highlights_records = await asyncio.gather(
       self._uow.fundamentals_read.find_by_section(iid_str, FundamentalsSection.EARNINGS_HISTORY),
       self._uow.fundamentals_read.find_by_section(iid_str, FundamentalsSection.INCOME_STATEMENT, period_type=selected_period_type),
       self._uow.fundamentals_read.find_by_section(iid_str, FundamentalsSection.HIGHLIGHTS),
   )
   ```
2. Preserve current error semantics: if any of the 3 raises, propagate
   (don't swallow; the batch handler already maps exceptions to typed
   reason codes per PLAN-0097 W3).
3. Add a unit test
   `services/market-data/tests/unit/application/use_cases/test_get_fundamentals_history_parallel_sections.py`
   that uses the **asyncio.Event barrier pattern** (NOT wall-clock —
   per PLAN-0098 W5 T-W5-02 guidance to avoid CI flake): each section
   repo mock awaits a shared `asyncio.Event` that is set only when all
   3 mocks have been invoked. If the use case awaits them serially,
   the event never sets and the test times out.

**Acceptance check**: unit test passes; barrier proves all 3 mocks
are invoked concurrently.

**Migration**: NO. **Docker rebuild**: YES — market-data.

##### T-W1-03: Add per-phase wall-clock instrumentation to chat orchestrator (diagnostic only)

**Type**: impl + log assertion test
**File**: `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py`

**Root cause for instrumentation**: The PLAN-0098 chat-eval log shows
median 38.73s + p99 133.19s but no per-phase decomposition. We cannot
tell whether (a) classifier dominates, (b) first-LLM, (c) tool fan-out,
(d) second-LLM (table generation), or (e) streaming. Without this,
T-W1-04 (model swap) is a shot in the dark.

**What to build**:
1. At each phase boundary in `chat_orchestrator.py`, capture a
   `time.perf_counter()` snapshot.
2. Emit one structlog `event=chat_phase_timing` line per request with
   keys `classifier_ms`, `first_llm_ms`, `tool_fanout_ms`,
   `second_llm_ms`, `streaming_ms`, `total_ms`.
3. Add `query_id` (or `request_id`) so the next chat-eval artifact can
   join these log lines back to the verdict CSV.
4. Add a unit test that mocks the 5 phases with known sleep durations
   and asserts the emitted log line carries the right approximate
   numbers (use asyncio.Event barriers if needed to avoid wall-clock
   flake; per-phase tolerance ±10ms).

**Acceptance check**: log assertion test passes; deploying to live
yields `event=chat_phase_timing` lines in rag-chat logs on every
chat request. The first post-deploy eval log decomposes total latency
into the 5 phases.

**Migration**: NO. **Docker rebuild**: YES — rag-chat.
**Diagnostic only — no behaviour change.**

##### T-W1-04: Consider smaller / faster model for second-turn table generation (deferred to PLAN-0100)

**Status**: **DEFERRED** to PLAN-0100. Justification: cannot make a
defensible model-swap decision without T-W1-03 data. Re-evaluate after
the first post-deploy chat-eval artifact lands and the per-phase log
shows whether `second_llm_ms` dominates.

#### Validation gate

- [ ] ruff + mypy clean on market-data + rag-chat
- [ ] T-W1-01 integration test passes; manual repro shows no row-mix
- [ ] T-W1-02 barrier test passes; 3 section reads run concurrently
- [ ] T-W1-03 log assertion test passes; live `event=chat_phase_timing`
      lines visible in rag-chat logs
- [ ] Chat-eval rerun: median < 30s AND p99 < 60s (cross-cutting §5)

#### Compounding updates

- `docs/services/market-data.md` — note structural binding of batch
  rows (no longer iterator-positional); intra-ticker parallelization.
- `docs/services/rag-chat.md` — per-phase timing instrumentation note.
- `services/market-data/.claude-context.md` — pitfall on iterator-
  positional batch result mapping (BP-587 latent fix).
- `services/rag-chat/.claude-context.md` — note per-phase timing.
- `docs/BUG_PATTERNS.md` — **BP-593** ("batch result iterator-positional
  row-mix latent path; bind structurally by ticker"); **BP-594**
  ("intra-ticker section reads serialized inside use case; parallelize
  via asyncio.gather"). _Reservation renumbered 2026-05-27 by PLAN-0099
  W4 T-W4-03: BP-589/BP-590 were taken by PLAN-0089 Wave K (HEAD of
  BUG_PATTERNS.md at audit time was BP-587; HEAD at W4 fix time is
  BP-592 because PLAN-0099 W1 T-W1-01 already filed BP-592). See
  `docs/BUG_PATTERNS.md` numbering note._
- `docs/plans/TRACKING.md` — PLAN-0099 row update.

---

### Wave W2 — PLAN-0098 W2 data-pipeline tails (T-W2-02..04 + counter)

**Goal**: Close the four PLAN-0098 W2 deferrals so the live SLO
pre-gate (entity_mentions > 0, AGE synced, fundamentals fresh, revenue
JSONB hydrated) is clean.

**Depends on**: PLAN-0098 W2 T-W2-01 in main (NLP tenant_id stamping
                shipped — verified in TRACKING.md line 40).
**Estimated effort**: ~6 h (T-W2-01 AGE drain 60-90m + T-W2-02 worker
                       4-6 h + T-W2-03 revenue JSONB 60-90m + T-W2-04
                       counter 30m).
**Architecture layer**: knowledge-graph ops + content-ingestion
                        application/infrastructure + market-data
                        infrastructure + nlp-pipeline infrastructure.
**Branch**: `feat/plan-0099-w2`
**Migration**: NO (none anticipated; investigation surfaced no DDL
                 needs)
**Docker rebuild**: YES — content-ingestion + market-data + nlp-pipeline

#### Tasks

##### T-W2-01: AGE TemporalEvent reconcile drain

**Type**: ops + (likely) small code wire-up
**Audit ref**: PLAN-0098 W2 §A3.
**File**: `services/knowledge-graph/scripts/reconcile_age_temporal_events.py`
              + `services/knowledge-graph/src/knowledge_graph/app.py`
              (worker registration site).

**What to build**:
1. Run `python services/knowledge-graph/scripts/reconcile_age_temporal_events.py --dry-run`
   first to confirm drift scope (SQL row count vs Cypher node count).
2. If drift confirmed > 0, run wet (drop `--dry-run`).
3. Investigate why the auto-sync didn't deliver post-restart (audit §A3
   hypothesised the sync worker isn't being invoked). Check worker
   registration in `app.py` (or wherever workers register) — is the
   periodic AGE sync worker registered AND does it start after
   `AgeBootstrap`? If absent, wire it back; if registered, capture
   why post-restart invocation drops.
4. If a wire-up fix is needed, add a unit test that confirms the
   worker is in the lifespan registry.

**Acceptance check**: `MATCH (n:TemporalEvent) RETURN count(n)` in
AGE matches `SELECT count(*) FROM temporal_events` within 30s of next
restart; subsequent inserts replicate within the worker's cadence.

**Migration**: NO. **Docker rebuild**: only if code wire-up needed.

##### T-W2-02: Ship FundamentalsRefreshWorker (proper periodic worker)

**Type**: new worker (replaces PLAN-0097 W1-T4 manual script)
**Audit ref**: PLAN-0098 W2 §A4 + BP-578.
**File** (NEW): `services/content-ingestion/src/content_ingestion/infrastructure/workers/fundamentals_refresh_worker.py`

**What to build**:
1. New worker that polls EODHD every 6h for the top-N (configurable,
   default 500) instruments by market cap.
2. Fans out to existing `POST /api/v1/ingest/trigger` per instrument
   (reuses the consumer path that already works for one-off triggers).
3. Exponential backoff on 429 per BP-114 (EODHD demo rate-limit gotcha).
4. `FUNDAMENTALS_REFRESH_ENABLED=false` env flag default-OFF for safe
   rollout; flip to `true` in `services/content-ingestion/configs/docker.env`
   only after the unit test + first live cycle confirm behaviour.
5. New Prom counter
   `fundamentals_refresh_attempts_total{symbol, status}` where status
   ∈ `{success, retry, failed, throttled}`. **Cardinality note**: with
   N=500 instruments × 4 status values = 2000 series per scrape — high
   but bounded; if concern, drop `symbol` and keep just `status` (see
   §6 risk register).
6. Register in `services/content-ingestion/src/content_ingestion/app.py`
   lifespan when enabled.
7. Unit test for batch-and-backoff loop (mock EODHD, assert backoff
   sequence on 429).

**Fallback (Option B — if §A4 deeper investigation flips to NOT
shipping the worker)**: cron-wrap the existing
`scripts/refresh_fundamentals.py` every 6h via a compose sidecar;
document the gap in `docs/services/content-ingestion.md`. Default:
ship the worker.

**Acceptance check**: with flag ON, `SELECT count(*) FROM instruments
WHERE last_fundamentals_ingest_at > now() - interval '24 hours'` > 50%
of top-500 by market cap within 6h of deploy; Prom counter increments
visible.

**Migration**: NO. **Docker rebuild**: YES — content-ingestion.

##### T-W2-03: Revenue JSONB hydration bug fix

**Type**: impl + test
**Audit ref**: PLAN-0098 W2 §A5.
**File**: `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py`

**What to build**:
1. Query: pick **one** `earnings_history` row with `data={}` from live
   DB (`SELECT id, instrument_id, period_end_date FROM earnings_history
   WHERE data = '{}'::jsonb LIMIT 1`).
2. Find the corresponding instrument and the most-recent matching
   Avro payload (replay topic offset OR pull from MinIO bronze bucket
   if available).
3. Trace through `fundamentals_consumer.py` to identify where the
   `revenue` key is being dropped — likely either (a) Avro→domain
   mapping missing the key, or (b) EODHD parsing fallback path
   silently dropping it on partial responses.
4. Fix the mapping; add a regression test
   `services/market-data/tests/unit/infrastructure/messaging/consumers/test_fundamentals_consumer_revenue_hydration.py`
   that ingests a sample payload (fixture) and asserts the resulting
   `data` JSONB is non-empty AND contains the `revenue` key.

**Acceptance check**: `GET /v1/fundamentals/{nvda_id}/history?periods=6`
returns non-null `revenue` on QUARTERLY rows post-deploy; regression
test passes.

**Migration**: NO. **Docker rebuild**: YES — market-data.

##### T-W2-04: Prom counter `nlp_pipeline_pre_persist_tenant_id_substituted_total{block_source}`

**Type**: impl + metric registration test
**Audit ref**: `docs/audits/2026-05-27-plan-0098-phase-d-code-review.md` §9 + §10.
**File**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py`
              (substitution site in the pre-persist safety net shipped
              by PLAN-0098 W2 T-W2-01).

**What to build**:
1. Add Prometheus counter
   `nlp_pipeline_pre_persist_tenant_id_substituted_total` with label
   `block_source` (the code path the offending mention originated
   from). **Cardinality cap**: enumerate `block_source` values to a
   small fixed enum (e.g. `ner_post_stamp` / `gliner` / `llm_extract`
   / `unknown`) — DO NOT use free-form strings.
2. Increment at the substitution site immediately before the
   structlog WARN that PLAN-0098 already emits.
3. Metric registration test in the existing
   `tests/unit/infrastructure/messaging/consumers/test_article_consumer_tenant_id_propagation.py`
   that asserts the counter increments on each substitution.

**Acceptance check**: metric appears in `/metrics` endpoint with a 0
baseline after deploy; if the safety-net WARN fires post-deploy, the
counter increments; cardinality stays bounded (≤5 distinct label
values).

**Migration**: NO. **Docker rebuild**: YES — nlp-pipeline.

#### Validation gate

- [ ] ruff + mypy clean on all touched services
- [ ] T-W2-01..04 acceptance checks green
- [ ] No new errors in any container for 15 min post-deploy
- [ ] Live SLO pre-gate (§5): AGE node count == SQL row count,
      entity_mentions row count > 0 and climbing, fundamentals
      freshness > 0 instruments

#### Compounding updates

- `docs/services/knowledge-graph.md` — AGE reconcile runbook +
  worker-registration note.
- `docs/services/content-ingestion.md` — FundamentalsRefreshWorker
  cadence + env flag + Prom metric.
- `docs/services/market-data.md` — revenue JSONB shape note +
  consumer mapping gotcha (BP-591).
- `docs/services/nlp-pipeline.md` — pre-persist counter contract +
  cardinality cap.
- `.claude-context.md` for each affected service — pitfall entries.
- `docs/BUG_PATTERNS.md` — **BP-595** ("revenue Avro field mapping
  dropped in fundamentals consumer; assert JSONB non-empty on ingest");
  **BP-596** ("AGE sync worker not invoked post-restart; reconcile
  script + worker registration audit"); **BP-578 → FIXED** (mark
  status update if T-W2-02 ships the worker). _Reservation renumbered
  2026-05-27 by PLAN-0099 W4 T-W4-03 (BP-591/BP-592 already taken)._
- `docs/plans/TRACKING.md` — PLAN-0099 row update.

---

### Wave W3 — MARGINAL Q1 + Q2 → USEFUL closures

**Goal**: Bump USEFUL count from 7/9 to 9/9 by investigating then
closing the two MARGINAL verdicts on Q1 ("Apple competitors") and Q2
("MSTR news"). Both are investigation-first because the root cause
class differs depending on what the tool actually returned.

**Depends on**: none (independent of W1/W2/W4/W5).
**Estimated effort**: ~2 h investigation + variable fix effort (prompt
                       tweak ~30m; ranking gap ~2 h; data gap ~filed
                       as follow-up plan).
**Architecture layer**: rag-chat + knowledge-graph + content-ingestion
                        + nlp-pipeline (depending on classification).
**Branch**: `feat/plan-0099-w3`
**Migration**: NO
**Docker rebuild**: rag-chat only if prompt tweak ships; investigation
                    has no rebuild need.

#### Tasks

##### T-W3-01: Q1 "Apple competitors" — investigate + close MARGINAL

**Type**: investigate + (probably) prompt tweak
**Audit ref**: `/tmp/chat_eval_PLAN0098.log` — Q1 verdict reason
              `"only 0 of ['Samsung', 'Microsoft', 'Google', 'Huawei',
              'Xiaomi'] mentioned; need ≥ 2"`.

**Investigation steps**:
1. Reproduce: run the Q1 prompt against the live rag-chat with the
   same env flags as the eval (`DEBUG_SKIP_CLASSIFIER=true` etc.).
2. Capture the `get_entity_intelligence` tool result for Apple — does
   it actually surface competitor entities?
3. Classify:
   - **Branch A — competitors ARE in the tool result**: prompt tweak.
     Update the rag-chat synthesis prompt to encourage explicit
     enumeration of competitor entities when the user asks about
     competitors. Ship + regression-pin Q1 in chat-eval.
   - **Branch B — competitors are NOT in the tool result**: KG
     narrative gap (different problem class). File as follow-up
     under PLAN-0100; this task closes with the investigation report
     instead of a fix.

**Acceptance check**:
- Branch A: Q1 grades USEFUL on next chat-eval rerun with ≥2 of
  Samsung/Microsoft/Google/Huawei/Xiaomi mentioned.
- Branch B: investigation report filed at
  `docs/audits/<DATE>-q1-apple-competitors-kg-gap.md`; PLAN-0100 row
  drafted in TRACKING.md.

**Migration**: NO. **Docker rebuild**: only if prompt ships
(rag-chat).

##### T-W3-02: Q2 "MSTR news" — investigate + close MARGINAL

**Type**: investigate + (probably) search ranking OR ingestion fix
**Audit ref**: `/tmp/chat_eval_PLAN0098.log` — Q2 verdict reason
              `"missing any-of mention from ['Bitcoin', 'BTC']"`.

**Investigation steps**:
1. SQL probe: `SELECT id, title, published_at FROM articles WHERE
   ticker_mentions @> '["MSTR"]'::jsonb AND (title ILIKE '%bitcoin%'
   OR title ILIKE '%btc%') ORDER BY published_at DESC LIMIT 10`.
2. Classify:
   - **Branch A — recent MSTR-Bitcoin articles EXIST in nlp_db**:
     search ranking gap. Trace the `search_documents` tool's actual
     query + ranking; if BM25/embedding ranking is suppressing them,
     adjust scoring or boost recency. Ship + regression-pin Q2.
   - **Branch B — no recent MSTR-Bitcoin articles**: content-ingestion
     freshness gap. File a follow-up under PLAN-0100 for the news
     ingestion source coverage. This task closes with investigation
     report.

**Acceptance check**:
- Branch A: Q2 grades USEFUL on next chat-eval rerun with Bitcoin/BTC
  mentioned.
- Branch B: investigation report filed; PLAN-0100 row drafted.

**Migration**: NO. **Docker rebuild**: only if ranking ships (rag-chat
or nlp-pipeline depending on where the ranking lives).

#### Validation gate

- [ ] ruff + mypy clean on touched services (if any code shipped)
- [ ] Investigation reports filed if Branch B for either task
- [ ] Q1 + Q2 grade USEFUL on next chat-eval rerun (if Branch A both)
      OR PLAN-0100 follow-ups drafted in TRACKING.md (if Branch B)

#### Compounding updates

- `docs/services/rag-chat.md` — synthesis prompt note if T-W3-01 prompt
  tweak ships; ranking note if T-W3-02 ranking fix ships.
- `docs/services/knowledge-graph.md` — competitor narrative note if
  T-W3-01 Branch B → PLAN-0100 row.
- `docs/services/content-ingestion.md` — freshness coverage note if
  T-W3-02 Branch B → PLAN-0100 row.
- `docs/BUG_PATTERNS.md` — BP entries only if a fix ships:
  **BP-597** (Q1 prompt-tweak class if Branch A); **BP-598** (Q2
  ranking class if Branch A). Numbers reserved; do not file if Branch
  B (those become PLAN-0100 BPs instead). _Reservation renumbered
  2026-05-27 by PLAN-0099 W4 T-W4-03 (BP-593/BP-594 reassigned to W2)._
- `docs/plans/TRACKING.md` — PLAN-0099 row update + PLAN-0100 row
  draft if either task lands in Branch B.

---

### Wave W4 — Phase-D code-review P2 punch list (10 items in 3-4 commits)

**Goal**: Land the 10-item PLAN-0099 punch list from
`docs/audits/2026-05-27-plan-0098-phase-d-code-review.md` §13 in 3-4
commits bundled by area.

**Depends on**: none (independent of W1/W2/W3/W5).
**Estimated effort**: ~2 h.
**Architecture layer**: mixed.
**Branch**: `feat/plan-0099-w4`
**Migration**: NO
**Docker rebuild**: minor (nlp-pipeline if items 3+6 ship; market-data
                    if working-tree migration 019 cleanup ships)

#### Tasks

The 10 items from §13 of the code-review audit, bundled into 4 commits
by area. Each item carries its `§13.N` reference. Items already folded
into other waves are noted as **MOVED** and not re-implemented here.

##### T-W4-01: Test quality / flake-prevention bundle (1 commit)

**Type**: tests + hook
**Audit refs**: §13.1, §13.5.

- **§13.1 Stash-marker scrub hook**: add a pre-commit hook script
  `scripts/hooks/scrub_stash_markers.sh` that runs
  `! grep -rn "^<<<<<<< " <staged-files>` and exits 1 on any hit.
  Register in `.pre-commit-config.yaml`. Document in
  `docs/plans/TRACKING.md` "feedback" line.
- **§13.5 TRACKING.md discipline**: add a one-line lint or pre-PR
  script that asserts every TRACKING.md "SHIPPED <date>" claim has a
  commit hash in `git log --grep PLAN-XXXX`. Lightweight — can be a
  simple grep + git-log assertion.

**Acceptance check**: deliberately introducing a `<<<<<<< Updated
upstream` marker in a fixture file flips the pre-commit hook red;
deliberately editing TRACKING.md to claim SHIPPED without a commit
flips the lint red.

##### T-W4-02: Minor defensiveness bundle (1 commit)

**Type**: impl + tests
**Audit refs**: §13.6, §13.10.

- **§13.6 Defensive `or PUBLIC_TENANT_ID` on NER post-stamp**: at
  `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:585`
  (or wherever the unconditional NER post-stamp landed in PLAN-0098 W2
  T-W2-01), change `m.tenant_id = tenant_id` to
  `m.tenant_id = tenant_id or PUBLIC_TENANT_ID`. Preserves the prior
  safety even if the envelope-level non-None precondition silently
  breaks. Add a regression test.
- **§13.10 Repo-wide arch test for `ScreenFieldMetadata(field_type=...)`
  literal values**: scan all source trees, assert every `field_type=`
  literal value is in `{"numeric", "text"}`. Pre-empts BP-585 recurrence.
  New test `tests/architecture/test_screen_field_metadata_field_type_enum.py`.

**Acceptance check**: regression test passes; deliberately re-
introducing `field_type="boolean"` in a fixture flips the arch test
red; deliberately removing the `or PUBLIC_TENANT_ID` flips the NER
test red.

##### T-W4-03: Doc and tracking cleanups (1 commit)

**Type**: docs + bookkeeping
**Audit refs**: §13.2 (folded into compounding §5 here — files renumbered
              BP-593..BP-598 as of 2026-05-27 because PLAN-0089 Wave K
              consumed BP-588..BP-591 and PLAN-0099 W1 T-W1-01 took BP-592
              before this commit landed; see numbering note at the top of
              `docs/BUG_PATTERNS.md`).
- **§13.2 BP numbering reconciliation**: PLAN-0099 was drafted when
  `docs/BUG_PATTERNS.md` high-water was BP-587. By the time PLAN-0099
  W4 fix lands, PLAN-0089 Wave K filed BP-588..BP-591 and PLAN-0099
  W1 T-W1-01 filed BP-592. Renumber all PLAN-0099 W2/W3 reservations
  to start at BP-593 (W2: 593/594/595/596; W3 Branch A: 597/598). The
  shipped reservation map is documented in a one-paragraph note at the
  top of `docs/BUG_PATTERNS.md`.
- **§13.3 Observability counter** — **MOVED to W2 T-W2-04**, not
  re-implemented here.
- **§13.4 Upstream `tenant_id=None` source trace** — defer to PLAN-0100
  with a structured-investigation TODO referencing the counter from
  W2 T-W2-04 (once 1 week of metric data is available).
- **§13.9 Chat-eval rerun gating** — **TRACKED in §5 here** as
  cross-cutting acceptance gate.

**Acceptance check**: BUG_PATTERNS.md numbering note added; PLAN-0100
TODO row drafted in TRACKING.md for §13.4 deferral.

##### T-W4-04: Working-tree contamination cleanup (1 commit)

**Type**: investigate + revert OR document
**Audit refs**: §13.7.

- **§13.7 working-tree contamination**: verify
  `services/portfolio/src/portfolio/api/internal.py` and the
  modifications visible in `git status` to `services/market-data/alembic/versions/019_composite_fundamentals_indexes.py`
  are intentional. If accidental contamination from concurrent work,
  revert before commit. If intentional, document under which PLAN row
  they belong. Also: §13.8 + §13.9 + §13.10 already folded into other
  W4 commits above.

**Acceptance check**: `git status` clean of the two contamination
files (either reverted or attributed to a documented PLAN row).

#### Validation gate

- [ ] ruff + mypy clean on all touched services
- [ ] All 4 W4 commits ship; targeted unit suites green
- [ ] Pre-commit hook for stash markers fires red on deliberate
      introduction
- [ ] Arch test for `field_type` literals fires red on deliberate
      regression

#### Compounding updates

- `docs/BUG_PATTERNS.md` — numbering reconciliation note;
  documentation entry for the W4 arch test pattern.
- `scripts/hooks/scrub_stash_markers.sh` — new file.
- `.pre-commit-config.yaml` — new hook registration.
- `docs/plans/TRACKING.md` — PLAN-0099 row update + PLAN-0100 draft row
  for deferred §13.4 upstream tenant_id source trace.

---

### Wave W5 — Documentation hygiene + R42 rule promotion

**Goal**: Sweep service docs for stale references; promote the
PLAN-0098 W2 safety-net pattern to a numbered rule.

**Depends on**: none (independent of W1/W2/W3/W4).
**Estimated effort**: ~1.5 h.
**Architecture layer**: docs.
**Branch**: `feat/plan-0099-w5`
**Migration**: NO
**Docker rebuild**: NO

#### Tasks

##### T-W5-01: Sweep `docs/services/*.md` for stale references

**Type**: docs

**What to sweep**:
1. **R36 vs R41 cosmetic drift**: per Phase-D code-review §8 + §11 —
   some agents reported `R36` references where the canonical rule is
   `R41`. Grep `docs/services/*.md` + `docs/MASTER_PLAN.md` for `R36`
   and verify each is the correct rule (some R36 references might be
   for a different rule; if so, leave them; if they're for the AGE
   bootstrap pattern, replace with R41).
2. **PLAN-0097 14→18 fundamentals tables**: PLAN-0097 W3 T-W3-01
   migration 022 actually targets 18 mixin-using tables (corrected
   from a prior "14" claim). Verify all service docs reflect 18.
3. **PLAN-0098 batch typed reason codes**: PLAN-0097 W3 T-W3-04 +
   PLAN-0098 W4 T-W4-02 typed reason codes (`invalid_ticker`,
   `upstream_timeout`, `upstream_404`, `upstream_error`,
   `invalid_lookup`) must be documented in `docs/services/market-data.md`
   batch endpoint section.

**Acceptance check**: grep returns expected counts post-sweep; each
service doc references current rule numbers + counts.

##### T-W5-02: Promote safety-net pattern to rule R42

**Type**: docs

**What to add** to `RULES.md`:

> **R42 — Consumer mention-construction sites that derive from
> external Avro payloads MUST default null `tenant_id` to
> `PUBLIC_TENANT_ID` at the persist boundary, not at construction
> time.**
>
> **Rationale**: Construction-time defaults silently mask upstream
> regressions where a payload field starts arriving as null. The
> persist-boundary default + a structlog WARN + a Prom counter
> (per BP-575 + BP-586 + PLAN-0099 W2 T-W2-04) turns "silently
> wrong row" into "loudly observable substitution event".
>
> **Audit pointers**: BP-575 (PLAN-0096 W2), BP-586 (PLAN-0098 W2
> T-W2-01), `docs/audits/2026-05-27-plan-0098-phase-d-code-review.md`
> §9 + §10.

**Acceptance check**: R42 row appears in RULES.md; cross-reference
added in `docs/services/nlp-pipeline.md` + `.claude-context.md`.

#### Validation gate

- [ ] Doc sweep complete; grep returns expected post-sweep counts
- [ ] R42 appears in RULES.md with rationale + audit pointers

#### Compounding updates

- `docs/services/*.md` — sweep results.
- `RULES.md` — R42 added.
- `services/nlp-pipeline/.claude-context.md` + other affected
  `.claude-context.md` files — R42 cross-reference.
- `docs/BUG_PATTERNS.md` — note R42 as the rule-level codification of
  BP-575 + BP-586.
- `docs/plans/TRACKING.md` — PLAN-0099 row update.

---

## §5 — Cross-Cutting Acceptance Gate

**Trigger**: W1 + W2 BOTH ship (W3/W4/W5 are hygiene; W3 lifts
verdicts but does not block the gate since 7/9 USEFUL already meets
the ≥6 threshold).

**Why W1 + W2 are both gating**: W1 closes BOTH latency gates (the
only remaining failure in `/tmp/chat_eval_PLAN0098.log`). W2 ensures
the live SLO pre-gate (entity_mentions > 0, AGE synced, fundamentals
fresh, revenue JSONB hydrated) is clean so the chat-eval rerun is
running against healthy data.

**Command** (run from foreground bash, NOT nested in agent — per
PLAN-0098 §5 + unblock audit §6):

```bash
RAG_CHAT_BASE_URL=http://localhost:8000 \
  RAG_COMPLETION_CACHE_DISABLED=true \
  DEBUG_SKIP_CLASSIFIER=true \
  APP_ENV=dev \
  pytest tests/validation/chat_eval/test_aggregate_score.py 2>&1 | tee /tmp/chat_eval_PLAN0099.log &
disown
```

**Pre-gate live SLO checks** (5 queries):

```sql
-- 1. entity_mentions climbing
SELECT count(*) FROM entity_mentions WHERE created_at > now() - interval '1 hour';
-- expect > 0 and climbing on subsequent runs

-- 2. AGE node count matches SQL
-- Compare:
SELECT count(*) FROM temporal_events;
-- vs MATCH (n:TemporalEvent) RETURN count(n) in AGE

-- 3. Fundamentals freshness
SELECT count(*) FROM instruments
WHERE last_fundamentals_ingest_at > now() - interval '24 hours';
-- expect > 50% of top-500 by market cap

-- 4. Revenue JSONB hydration
SELECT count(*) FROM earnings_history WHERE data ? 'revenue';
-- expect equal to total row count (no NULLs)

-- 5. screen_field_metadata refresh errors
-- Inspect last 15 min of market-data logs for event=screen_fields_refresh_error
-- expect 0 occurrences
```

**Pass criteria**:
- All 5 pre-gate SQL checks green.
- chat-eval verdicts: ≥7 USEFUL (already met; ideally 9/9 if W3 lands
  Branch A on both Q1+Q2); HARMFUL=0 (already met).
- **median latency < 30s** (currently 38.73s — W1-T01+T02 must close).
- **p99 latency < 60s** (currently 133.19s — W1-T01+T02 must close).
- No new error log lines in nlp-pipeline / market-data /
  knowledge-graph / rag-chat / content-ingestion for 15 min
  post-deploy.

**On fail**: investigate which specific gate is still red; if p99 is
between 60-100s after W1, T-W1-04 (model swap) becomes a PLAN-0100
must-do; otherwise file a sub-bug and iterate the relevant wave.

---

## §6 — Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| W2 T-W2-02 FundamentalsRefreshWorker exhausts EODHD rate limits (BP-578 recurrence path) | Medium | Medium | Exponential backoff on 429 per BP-114; `FUNDAMENTALS_REFRESH_ENABLED=false` default; ship to dev first; monitor `fundamentals_refresh_attempts_total{status="throttled"}` for 24h before prod flip |
| W2 T-W2-01 AGE reconciliation locks `temporal_events` table for an unbounded duration on large drift | Medium | Medium | Run `--dry-run` first to size the drift; if > 100k rows, batch in chunks; AGE writes are append-only so reader-side locks are short |
| W1 T-W1-02 parallel section reads exhaust asyncpg pool when fan-out × 3 sections × batch tickers stacks up | Medium | Medium | Concurrency is bounded (3 sections per ticker × N tickers per batch; default N≤5); monitor `event=fundamentals_batch_fetch_timing` (if added in T-W1-03) for pool-exhaustion warnings; if observed, cap `asyncio.gather` with a Semaphore(3) per request |
| W2 T-W2-04 Prom counter `block_source` label cardinality explodes if a developer free-forms the label value | Low | Medium | Implementation uses a fixed enum (4-5 values); add unit test that asserts unknown values fall to `"unknown"` bucket; add `docs/BUG_PATTERNS.md` note BP-575 cross-reference |
| W3 T-W3-01/T-W3-02 investigation outcomes flip to Branch B (data gap) for both Q1 + Q2 — PLAN-0099 closes with 0 verdict bump | Low | Low | Branch B is still a successful outcome: produces investigation reports + PLAN-0100 draft rows. PLAN-0099 gate does NOT require USEFUL bump (only ≥7 is needed; already met) |
| W1 T-W1-03 instrumentation adds latency overhead | Low | Low | `time.perf_counter()` calls are nanosecond-cheap; only one structlog line per request; estimated overhead < 1ms |
| W4 §13.4 deferred upstream `tenant_id=None` source trace is forgotten | Medium | Low | Track explicitly in PLAN-0100 draft row in TRACKING.md; re-evaluate after 1 week of W2 T-W2-04 counter data |
| W5 R42 rule promotion conflicts with an in-flight rule numbering claim | Low | Low | Verify next-free rule number in RULES.md before commit; if R42 is taken, escalate to next free |
| Working-tree contamination items (W4 §13.7) belong to a different in-flight plan | Medium | Low | Investigation step in T-W4-04 explicitly checks `git log` for any plan reference before reverting; document attribution if intentional |

---

## §7 — Owner stub

- **PLAN-0099 owner**: Arnau Rodon (`arnaurodondev@gmail.com`)
- **W1 owner**: Arnau (T-W1-01 + T-W1-02 + T-W1-03; T-W1-04 deferred
                       to PLAN-0100)
- **W2 owner**: Arnau (all 4 tasks)
- **W3 owner**: Arnau (investigation-first, branch on findings)
- **W4 owner**: Arnau (4 bundled commits)
- **W5 owner**: Arnau
- **Acceptance-gate executor**: Arnau (foreground bash + `disown`,
                                       NOT nested agent)

---

## §8 — Next revise-prd round

This plan is ready for next session's revise-prd + implementation
orchestration round; no in-flight investigations need to land first.

Remaining items for any future revise-prd round:

1. After W1 T-W1-03 instrumentation lands data, decide if PLAN-0100
   must include a second-turn model swap (T-W1-04 originally
   deferred) — depends on whether `second_llm_ms` dominates.
2. After W2 T-W2-02 lands, decide if BP-578 can be marked FIXED.
3. After W3 investigations land, fold any Branch B outcomes into a
   PLAN-0100 draft (KG narrative gap or content-ingestion freshness
   gap, depending on which task flipped).
4. After 1 week of W2 T-W2-04 counter data, schedule the upstream
   `tenant_id=None` source trace under PLAN-0100.

End of PLAN-0099 (draft 2026-05-25).
