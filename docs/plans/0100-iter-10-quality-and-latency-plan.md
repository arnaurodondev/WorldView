---
id: PLAN-0100
title: ITER-10 Quality & Latency — Entity-Drift HARMFUL Fix, UX Pattern B + TTFT Semantics, AAPL KG Gap, AMD Fundamentals Freshness, Top-N Market-Cap Endpoint, Model-Swap Decision, §13.4 Upstream Trace
prd: inline (see §0)
status: draft
created: 2026-05-28
updated: 2026-05-28
source_audits:
  - docs/audits/2026-05-27-plan-0100-ux-thinking-vs-reasoning.md (Pattern B — progressive tool status; UX latency perception)
  - docs/audits/2026-05-27-plan-0100-q2-mstr-entity-drift-deepdive.md (3-layer fix: BP-603 retrieval JSONB-fallback / BP-604 orchestrator drift guard / BP-605 synthesis grounding)
  - docs/audits/2026-05-27-plan-0100-latency-structural.md (Part A TTFT semantics + Part B model-swap deferral)
  - docs/audits/2026-05-27-plan-0100-fundamentals-followups.md (Part A AMD H1 diagnostic + Part B top-N-by-market-cap internal endpoint)
  - docs/audits/2026-05-27-plan-0099-w3-q1-q2-investigation.md (Q1 = Branch-B AAPL KG gap; Q2 re-classified MARGINAL → HARMFUL)
  - docs/audits/2026-05-27-plan-0099-live-chat-eval-final.md (live measurements: TTFT-p95 69.7 s, TPS-p50 13.4 tok/s, E2E-p99 98.6 s, 6 USEFUL / 2 MARGINAL / 1 USELESS / 0 HARMFUL in aggregate run)
  - docs/plans/TRACKING.md (PLAN-0100 draft stub row — superseded by this plan; carries §13.4 upstream tenant_id trace + W1-T04 model-swap + W3 Branch-B classes)
---

# PLAN-0100 — ITER-10 Quality & Latency

## §0 — Inline PRD

> No separate PRD. This plan consumes four PLAN-0100-prefixed audits
> that landed on 2026-05-27 plus the two PLAN-0099 retrospective
> audits (W3 Q1/Q2 investigation + live chat-eval final). It
> supersedes the **draft placeholder PLAN-0100 row** in TRACKING.md
> (line 42) — that row only tracked deferred items (§13.4 upstream
> tenant_id trace + W1-T04 model swap + W3 Branch-B classes) without
> scope; this plan promotes those deferrals into concrete waves and
> adds the new P0 entity-drift HARMFUL class surfaced by the Q2 deep
> dive.

### Problem statement

After PLAN-0099 the live chat-eval ran 6 USEFUL / 2 MARGINAL / 1
USELESS / 0 HARMFUL (aggregate), but the W3 audit re-classified Q2
("MSTR Bitcoin news") from MARGINAL to **HARMFUL** because the agent
silently substituted `entity_name="ON Semiconductor Corporation"`
after two empty MSTR results and wrote a confident answer with KG
citations attributed to ON Semi. The Q2 deep-dive audit traced this
to a 3-layer failure stack (BP-603/604/605) which this plan closes
as **W1** (P0).

Five additional open failure classes surfaced across the four PLAN-0100
audits and the W3 retro:

1. **P0 — Q2 MSTR entity drift (HARMFUL fabrication class)** — see
   above; closes via 3 layered tasks + a one-shot JSONB→table backfill.
2. **P1 — UX TTFT perception gap + chat-eval semantic mismatch** —
   live TTFT-p95 is 69.7 s because `_CONTENT_EVENT_KINDS` excludes
   `tool_call`/`status` events. Per the UX audit + latency-structural
   §A, ship Pattern B (one human-readable `status` event right after
   the first LLM turn decides on tools) AND extend the harness gate to
   treat `tool_call`/`status` as user-visible activity. Drops
   perceived TTFT from 69 s → ≤5 s with zero LLM cost.
3. **P1 — Q1 AAPL KG gap (Branch-B from PLAN-0099 W3 audit)** —
   `get_entity_intelligence(AAPL)` returned `item_count: 0`. Either
   AAPL was missed during KG ingestion, or the formatter drops the
   bundle. Investigation-first task.
4. **P1 — AMD fundamentals freshness (H1 from fundamentals audit)** —
   4 of 6 Q4 chat-eval variants still fail because AMD Q1 FY2026 is
   not in the DB. `FUNDAMENTALS_REFRESH_ENABLED` shipped default-OFF
   in PLAN-0099 W2-T02; flip it on once H1 verifies the manual refresh
   path works.
5. **P2 — Top-N-by-market-cap internal endpoint** — `FundamentalsRefreshWorker`
   is stuck on a 30-ticker static CSV because cross-service DB read
   violates R9. Ship `GET /internal/v1/instruments/top-by-market-cap`
   on market-data and consume from the worker.
6. **P2 — Model-swap decision (deferred from PLAN-0099 W1-T04)** —
   pure data-collection wave gated on W2 + 1 week of phase-timing
   artifacts. No swap this wave; outcome is a decision document.
7. **P2 — §13.4 upstream `tenant_id=None` source trace** — gated on
   ≥1 week of `nlp_pipeline_pre_persist_tenant_id_substituted_total{block_source}`
   counter data (shipped PLAN-0099 W2-T04). Find the construction site
   the dominant `block_source` points to and fix upstream so the
   persist-boundary safety net (R43) stops firing.

### Goals

1. Close the Q2 HARMFUL fabrication class — Q2 chat-eval verdict
   moves to USEFUL with `search_documents(entity_tickers=["MSTR"])`
   returning ≥5 chunks (W1).
2. Drop chat-eval TTFT-p95 from 69.7 s → ≤5 s via the combined
   backend status emission + harness gate redefinition (W2).
3. Lift Q1 from MARGINAL to USEFUL by closing the AAPL KG bundle gap
   (W3).
4. Get AMD Q1 FY2026 fundamentals flowing so Q4 chat-eval variants
   pass (W4).
5. Replace the curated CSV in `FundamentalsRefreshWorker` with a
   market-data-served top-N-by-market-cap list (W5).
6. Land a defensible model-swap decision document — either prepare
   PLAN-0101 pilot or close as "not needed" (W6).
7. Fix the upstream `tenant_id=None` construction site once metric
   data identifies the dominant `block_source` (W7).

### Non-goals

- New PRD features.
- Re-architecting the rag-chat orchestrator beyond the entity-drift
  guard + grounding check.
- Schema migrations — none anticipated; W1 BP-603 uses existing
  `chunks.entity_mentions` JSONB; W5 endpoint reads existing
  `fundamental_metrics`.
- Streaming tool-execution context (Option A3 from latency-structural
  audit) — too large; deferred indefinitely.

### Open questions

- W3 T-W3-01: is the gap at ingestion time, at the bundle
  formatter, or at the `get_entity_intelligence` repo? Resolved by the
  investigation report.
- W4 T-W4-01: does H1 (worker disabled / never ran) close the gap on
  its own, or does the team need to walk through H2 → H3 → H4? Cannot
  pre-judge; resolved by running the diagnostic SQL.
- W6 T-W6-02: synthesis-to-tool-planning ratio threshold of 50 % is a
  rough cut; W6 may surface a different decision boundary once real
  phase-timing data lands.

---

## §1 — Overview

**PRD**: inline (above)
**Services affected**: rag-chat (S8), nlp-pipeline (S6), knowledge-graph
                       (S7), market-data (S2), market-ingestion (S11),
                       worldview-web (apps/worldview-web), docs
**Total waves**: **7** (W1 entity-drift HARMFUL / W2 UX Pattern B + TTFT
                  semantics / W3 AAPL KG gap / W4 AMD fundamentals
                  freshness / W5 top-N endpoint / W6 model-swap decision /
                  W7 upstream tenant_id trace)
**Total estimated effort**: ~22 h engineering + 2 chat-eval reruns
                            (~16 min each) + 1 docker rebuild cycle per
                            backend-touching wave; W6 + W7 partly
                            calendar-gated (≥1 week of metric/artifact
                            data).
**Critical path**: W1 (closes HARMFUL class — P0 blocker for thesis-grade
                    chat trust); W2 + W3 + W4 stack into the chat-eval
                    acceptance gate (§5); W5/W6/W7 are independent.

### Branch & commit hygiene

Land on `feat/plan-0100-iter-10` (or per-wave sub-branches
`feat/plan-0100-w<N>`). Each wave gets its own commit set; W1 ships in
1-2 commits (BP-603 retrieval + backfill in one; BP-604/605 orchestrator
in the second). Strict R19 — no test deletion.

## §2 — Dependency Graph

```
        ┌──────────────────────────────────────────────────────┐
        │ PLAN-0099 W1+W2+W3+W4+W5+W6 in main (TTFT/TPS/E2E    │
        │ gates + per-phase instrumentation + BP-595 chunk     │
        │ streaming + FundamentalsRefreshWorker default-OFF +  │
        │ chat-eval baseline 6 USEFUL / 2 MARGINAL / 1 USELESS │
        │ / 0 HARMFUL aggregate; Q2 re-classified HARMFUL by   │
        │ W3 retro audit)                                      │
        └──────────────────────────┬───────────────────────────┘
                                   │
       ┌──────────────┬────────────┼────────────┬──────────────┬──────┐
       ▼              ▼            ▼            ▼              ▼      ▼
   W1 (P0 entity   W2 (UX        W3 (AAPL    W4 (AMD       W5 (top-N  W7 (§13.4
   drift HARMFUL — Pattern B +  KG gap —    fundamentals  market-cap upstream
   BP-603+604+605  TTFT-sem +   investigate  freshness —   endpoint)  tenant_id
   + JSONB         frontend     + smallest   H1 → H4                  trace —
   backfill)       badge)       possible    diagnostic                gated on
       │              │         fix)        + flip flag)              W2-T04
       │              │            │            │              │     counter
       │              │            │            │              │     ≥1 wk)
       ▼              ▼            ▼            ▼              ▼      ▲
       Cross-cutting acceptance gate (§5):                            │
       chat-eval rerun on rebuilt stack with 4 env flags.             │
       Pass: USEFUL ≥7 (W1 lifts Q2; W3 may lift Q1);                 │
       HARMFUL=0; USELESS=0; TTFT-p95 < 5s (W2);                      │
       TPS-p50 ≥ 30 tok/s (unchanged); E2E-p99 < 90s (relaxed).       │
                                                                       │
       ┌─────────── W6 (model-swap decision — gated on W2 ─────────────┤
       │             landing + ≥1 week phase-timing data)              │
       └───────────────────────────────────────────────────────────────┘
```

W1 + W2 + W3 + W4 are on the critical path for the acceptance gate.
W5 is independent (worker hygiene); W6 + W7 are calendar-gated data
collection.

## §3 — Codebase State Verification

| Reference | Type | Service | Actual current state | Plan target | Delta |
|-----------|------|---------|----------------------|-------------|-------|
| `search_chunks` SQL filter on `entity_mentions` join | code | nlp-pipeline | `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/chunk_search.py` — joins `entity_mentions` table on `doc_id`, filters by `em.resolved_entity_id = ANY($entity_ids)`. Q2 deep-dive audit §2 verified: 25 MSTR chunks exist in `chunks.entity_mentions` JSONB but zero in `entity_mentions` table → join returns 0 rows | extend WHERE with JSONB-containment fallback when `entity_ids` is specified: `OR c.entity_mentions @> jsonb_build_array(jsonb_build_object('resolved_entity_id', $1::text))` | code + regression test seeding 1 JSONB-only chunk |
| `news_query.py` parallel filter site | code | nlp-pipeline | per Q2 deep-dive §2 — same JSONB-vs-table mismatch in the news-query repo | mirror the JSONB-containment fallback | code + test |
| Chat orchestrator iteration loop entity-identity guard | code | rag-chat | `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` — no validation that fallback tool calls preserve entity identity across iterations. Audit §3 verified via Q2 trace: `search_claims(entity_name="ON Semiconductor")` was forwarded after two empty `search_documents(entity_tickers=["MSTR"])` calls with no guard | add `_validate_fallback_tool_call()`: extract entities from question + prior tool_calls; reject tool call naming a new entity; send structured error back to LLM | code + regression test (MSTR question, drift to "ON Semi") |
| Chat orchestrator synthesis grounding check | code | rag-chat | same file — `OutputProcessor` synthesises citations from retrieved items without cross-checking that retrieved-item entities overlap with question entities. Audit §4 verified | add `_check_entity_grounding()`: collect entity_name/entity_id from retrieved items; if zero overlap with question's resolved entities, raise `EntityGroundingError` | code + regression test (retrieved items entity="ON Semi", question="MSTR" → raises) |
| `entity_mentions` table backfill from `chunks.entity_mentions` JSONB | code (new script) | nlp-pipeline | no script today; the JSONB-vs-table lineage gap is a BP-575/586 family resurfacing. Audit §2 recommends the JSONB-fallback query as primary (lower-risk) fix + this script as belt-and-braces backfill | new `scripts/backfill_entity_mentions_from_chunks_jsonb.py` — idempotent, one-shot; iterates chunks WHERE entity_mentions IS NOT NULL AND jsonb_array_length > 0; INSERT ... ON CONFLICT DO NOTHING into entity_mentions | new script + dry-run + integration test |
| Chat orchestrator first-LLM-turn status emission | code | rag-chat | per UX audit §7 + latency-structural §A — no `status` event emitted between first LLM turn and tool dispatch loop today; the existing `emit_thinking()` runs before classifier but is ignored by the frontend | add `emit_status("Loading <tool list>…")` after first LLM turn returns tool_calls but before dispatch loop; compose text from `llm_response.tool_calls[:3]` with overflow `"… (N more)"` | code + unit test on the composition |
| StreamingBubble frontend tool-call badge | code | apps/worldview-web | `apps/worldview-web/features/chat/StreamingBubble.tsx` already renders `tool_call` events as `ToolCallIndicator` pills (UX audit §2 verified) but does NOT render the initial `status` event as a pre-pill badge | add lightweight badge render path for initial `status` event before the full `ToolCallIndicator`; reuse existing pill formatting + iconography | code + Vitest snapshot test |
| Chat-eval `_CONTENT_EVENT_KINDS` | code | rag-chat / tests | `tests/validation/chat_eval/harness.py:74` — `frozenset({"token", "delta", "text", "final_answer"})`. Latency-structural Part A audit recommends Option A2 (add `tool_call` and `status`) | extend to `frozenset({"tool_call", "status", "token", "delta", "text", "final_answer"})`; update gate-module docstring to say "first user-visible activity" with 5.0s gate semantics preserved | code + new unit test on synthetic stream |
| Chat-eval TTFT unit test for tool_call-before-token | code (new) | rag-chat / tests | no test today asserts TTFT ticks on tool_call vs token | new test in `tests/validation/chat_eval/test_harness_latency.py` constructing a synthetic stream `metadata` + `tool_call` (at t=1.2s) + `token` (at t=15s); assert `ttft_s ≈ 1.2`, NOT 15.0 | code |
| `get_entity_intelligence(AAPL)` bundle | runtime + code | knowledge-graph + rag-chat | per W3 audit Q1 §"DB state": `canonical_entities` has Apple Inc. (`01900000-0000-7000-8000-000000001001`) + stray `52a92aa8-…` duplicate; `get_entity_intelligence` returned `item_count: 0` for AAPL. Either KG ingestion missed AAPL relations, or formatter drops the bundle | investigate via S7 KG path: `canonical_entities` ✓; `entity_relations` for AAPL?; `entity_paths`? `entity_narratives`? Document at `docs/audits/2026-05-28-plan-0100-aapl-kg-investigation.md`; ship smallest possible fix | investigate + fix (scope TBD by investigation) |
| `instruments.last_fundamentals_ingest_at` for AMD | runtime | market-data | per fundamentals audit Part A H1 — most likely NULL / pre-Apr-2026 because `FUNDAMENTALS_REFRESH_ENABLED` shipped default-OFF and manual script never triggered for AMD post-deploy | run H1 diagnostic SQL; if NULL/stale, trigger refresh via `scripts/refresh_fundamentals.py --tickers AMD`; if still missing, walk H2 → H3 → H4 | ops + (maybe) code |
| `FUNDAMENTALS_REFRESH_ENABLED` default | code | market-ingestion | shipped `false` default by PLAN-0099 W2-T02 for safe rollout | flip to `true` default once W4 acceptance confirms backoff semantics behave under EODHD load; gate by explicit env var so per-deploy opt-out remains | code + env-doc update |
| Operator-dashboard fundamentals freshness panel | code (new) | observability | no panel today bins instruments by `last_fundamentals_ingest_at` age | new Grafana panel (or equivalent) — instruments rows binned 0-1d / 1-7d / 7-30d / >30d / NULL; "stale" = >7d | code (Grafana JSON) + screenshot in audit dir |
| `GET /internal/v1/instruments/top-by-market-cap` | code (new) | market-data | no endpoint today; `FundamentalsRefreshWorker` uses `FUNDAMENTALS_REFRESH_SYMBOLS` 30-ticker CSV | new endpoint per fundamentals audit Part B §"Sketch — endpoint contract"; reads `instruments` + `fundamental_metrics` (`market_capitalization` field, latest per instrument); `n` ∈ [1, 5000]; auth via `X-Internal-JWT` | new router + use case + 4 tests (happy + edge + auth + NULLs-last) |
| `FundamentalsRefreshWorker` symbol-list source | code | market-ingestion | `services/market-ingestion/src/market_ingestion/infrastructure/workers/fundamentals_refresh_worker.py` — reads `FUNDAMENTALS_REFRESH_SYMBOLS` env CSV with 30-ticker default | consume `GET /internal/v1/instruments/top-by-market-cap?n=500` instead; cache list per 6-hour cycle; CSV demoted to fallback-only (env: `FUNDAMENTALS_REFRESH_SYMBOLS_FALLBACK_ONLY=true` skips remote call) | code + unit test mocking endpoint |
| `chat_phase_timings_ms` artifact aggregation script | code (new) | rag-chat / scripts | per-phase metric shipped by PLAN-0099 W1-T03; no aggregation/pivot script today | small script that pulls `phase_timings_ms` from chat-eval run artifacts AND/OR from container logs over a 7-day window; computes mean/p50/p95 per phase; produces a CSV/markdown table | code (W6 input) |
| `nlp_pipeline_pre_persist_tenant_id_substituted_total{block_source}` counter | runtime | nlp-pipeline | shipped PLAN-0099 W2-T04 with fixed-enum label cardinality | wait ≥1 week of production data; then grep dominant `block_source`; trace to `EntityMention` construction site; fix upstream so persist-boundary safety net stops firing | investigate + fix at construction site |

## §4 — Sub-Plans

---

### Wave W1 — Q2 MSTR entity-drift HARMFUL fix (P0)

**Goal**: Close the HARMFUL fabrication class — the agent silently
substitutes wrong entities when first retrieval returns empty, then
writes confident citation-backed answers. Three layered fixes per the
Q2 deep-dive audit + one belt-and-braces backfill.

**Depends on**: PLAN-0099 W3 retro audit conclusion (Q2 re-classified
                HARMFUL) + PLAN-0099 W2 chunk-streaming in main.
**Estimated effort**: ~6 h (T-W1-01 ~1 h + T-W1-02 ~2 h + T-W1-03 ~2 h
                       + T-W1-04 backfill ~1 h).
**Architecture layer**: nlp-pipeline infrastructure (retrieval) +
                        rag-chat application (orchestrator) + scripts.
**Branch**: `feat/plan-0100-w1`
**Migration**: NO (JSONB column already exists)
**Docker rebuild**: YES — nlp-pipeline + rag-chat

#### Tasks

##### T-W1-01: BP-603 retrieval JSONB-fallback in `search_chunks`

**Type**: impl + regression test
**Audit ref**: `docs/audits/2026-05-27-plan-0100-q2-mstr-entity-drift-deepdive.md` §2.
**Files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/chunk_search.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/news_query.py`
  (parallel filter site)

**What to build**:
1. When `entity_ids` is supplied, extend the WHERE clause to fall back
   on JSONB containment against `chunks.entity_mentions`:
   ```sql
   WHERE (em.resolved_entity_id = ANY($entity_ids)
          OR c.entity_mentions @> ANY(
              ARRAY(SELECT jsonb_build_array(
                  jsonb_build_object('resolved_entity_id', eid::text)
              ) FROM UNNEST($entity_ids::uuid[]) AS eid)
          ))
   ```
2. Mirror in `news_query.py`.
3. New regression test
   `services/nlp-pipeline/tests/integration/repositories/test_chunk_search_jsonb_fallback.py`:
   seed 1 chunk with MSTR in `chunks.entity_mentions` JSONB but **no
   row** in `entity_mentions` table; call `search_chunks(entity_ids=[MSTR_ID])`;
   assert chunk is returned. Also assert: when both table row and JSONB
   are present (the normal path), no duplicate rows.

**Acceptance check**: integration test passes; manual repro
`search_chunks(entity_ids=[MSTR_ID])` against live nlp_db returns ≥5
chunks (Q2 deep-dive §2 confirmed 25 candidates exist in JSONB).

**Migration**: NO. **Docker rebuild**: YES — nlp-pipeline.

##### T-W1-02: BP-604 orchestrator entity-drift guard

**Type**: impl + regression test
**Audit ref**: `docs/audits/2026-05-27-plan-0100-q2-mstr-entity-drift-deepdive.md` §3.
**File**: `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py`

**What to build**:
1. Add `_validate_fallback_tool_call(tool_call, question_entities, prior_tool_call_entities)`
   in the iteration loop. Extract entity identifiers (`ticker`,
   `entity_name`, `entity_id`) from the proposed tool call's arguments
   and check that every one of them either (a) appears in the
   question's resolved entities, or (b) appeared in a prior tool_call's
   input. If not, REJECT and send a structured error message to the
   LLM (e.g. `"entity drift detected — refusing fallback that
   introduces 'ON Semiconductor Corporation' not present in the
   question or prior tool calls"`) so the LLM can either refuse or
   pick the right entity.
2. Wire question-entity extraction once at the top of the iteration
   loop (resolved by the existing classifier/entity-resolution phase).
3. Maintain `prior_tool_call_entities` as a running set updated after
   each iteration.
4. New regression test
   `services/rag-chat/tests/unit/use_cases/test_chat_orchestrator_entity_drift_guard.py`:
   simulate question about MSTR; first tool returns empty; second tool
   call proposes `entity_name="ON Semiconductor"`; assert the guard
   raises (or emits the structured error back to the LLM) AND the
   tool is NOT dispatched.

**Acceptance check**: regression test passes; replaying the Q2 trace
end-to-end shows the third tool call is rejected with the structured
error instead of being forwarded to the search_claims handler.

**Migration**: NO. **Docker rebuild**: YES — rag-chat.

##### T-W1-03: BP-605 synthesis grounding check

**Type**: impl + regression test
**Audit ref**: `docs/audits/2026-05-27-plan-0100-q2-mstr-entity-drift-deepdive.md` §4.
**File**: same orchestrator file (or new `output_processor.py` per
              audit §7 recommendation if scope grows).

**What to build**:
1. Add `_check_entity_grounding(retrieved_items, question_entities)`
   in the synthesis step. Collect `entity_name` and `entity_id` from
   every retrieved item that contributes to citations. If the
   intersection with `question_entities` is empty, raise
   `EntityGroundingError` (new exception type in
   `rag_chat.application.exceptions`) and refuse the answer with a
   user-facing message: `"I cannot find information about
   <question entity> in the retrieved sources."`
2. Wire `EntityGroundingError` handling at the orchestrator entry-point
   to convert into a structured SSE event (`emit_status("refused — no
   grounding")` + `emit_final_answer(<refusal message>)`).
3. New regression test
   `services/rag-chat/tests/unit/use_cases/test_chat_orchestrator_entity_grounding.py`:
   feed retrieved items with `entity_name="ON Semi"` + question about
   MSTR (resolved entities = `{MSTR}`); assert `EntityGroundingError`
   is raised AND the SSE stream emits the refusal final-answer.

**Acceptance check**: regression test passes; replaying Q2 trace shows
the synthesis step refuses cleanly with a user-friendly message
instead of producing the ON Semi fabrication.

**Migration**: NO. **Docker rebuild**: YES — rag-chat.

##### T-W1-04: One-shot backfill `entity_mentions` from `chunks.entity_mentions` JSONB

**Type**: new script + dry-run + integration test
**Audit ref**: `docs/audits/2026-05-27-plan-0100-q2-mstr-entity-drift-deepdive.md` §2 ("Or: backfill").
**File** (NEW): `scripts/backfill_entity_mentions_from_chunks_jsonb.py`

**What to build**:
1. Iterate `chunks` WHERE `entity_mentions IS NOT NULL AND
   jsonb_array_length(entity_mentions) > 0`; for each JSONB mention,
   INSERT into the normalised `entity_mentions` table; `ON CONFLICT
   (doc_id, resolved_entity_id, offset) DO NOTHING` (idempotent).
2. `--dry-run` flag prints count + sample 10 rows without writing.
3. `--batch-size` (default 5000) for chunked commit.
4. Structlog progress every batch.
5. Integration test in `services/nlp-pipeline/tests/integration/scripts/test_backfill_entity_mentions.py`:
   seed 3 chunks with JSONB mentions, 1 partially present in table;
   run script; assert `entity_mentions` rows = 3 unique tuples; assert
   re-run is no-op.

**Acceptance check**: dry-run reports nonzero candidate count against
live nlp_db; wet run completes without errors; post-run
`SELECT count(*) FROM entity_mentions WHERE resolved_entity_id = $MSTR_ID`
returns ≥25 (matches Q2 deep-dive §2 JSONB count).

**Migration**: NO. **Docker rebuild**: NO (script runs on host).
**Belt-and-braces**: T-W1-01 closes the production read path on its
own; this task removes reliance on the JSONB-fallback for the historic
backlog.

#### Validation gate

- [ ] ruff + mypy clean on nlp-pipeline + rag-chat
- [ ] T-W1-01 integration test passes; live `search_chunks` for MSTR
      returns ≥5 chunks
- [ ] T-W1-02 regression test passes; Q2 trace's third tool call is
      rejected
- [ ] T-W1-03 regression test passes; synthesis refuses cleanly when
      no entity overlap
- [ ] T-W1-04 backfill dry-run + integration test pass; wet run
      idempotent on re-execution
- [ ] Chat-eval Q2 rerun: verdict moves HARMFUL → USEFUL with MSTR
      content + Bitcoin/BTC mentions

#### Compounding updates

- `docs/services/nlp-pipeline.md` — JSONB-fallback contract on
  `search_chunks` + `news_query`; backfill script pointer.
- `docs/services/rag-chat.md` — entity-drift guard + synthesis
  grounding check sections; `EntityGroundingError` doc.
- `services/nlp-pipeline/.claude-context.md` — pitfall on
  JSONB-vs-table lineage gap (BP-603).
- `services/rag-chat/.claude-context.md` — pitfall on fallback tool
  call drift (BP-604) + synthesis grounding (BP-605).
- `docs/BUG_PATTERNS.md` — **BP-603** ("entity-mention lineage gap —
  normalised `entity_mentions` table empty while `chunks.entity_mentions`
  JSONB populated; extend retrieval with JSONB-containment fallback");
  **BP-604** ("fallback tool drift — orchestrator forwarded
  search_claims(entity_name='ON Semi') after empty MSTR results;
  validate fallback tool calls preserve entity identity");
  **BP-605** ("synthesis grounding gap — citations attributed to
  retrieved entities that don't overlap question entities; check
  entity overlap before answer").
- `docs/plans/TRACKING.md` — PLAN-0100 row update.

---

### Wave W2 — UX Pattern B (progressive tool status) + TTFT semantics fix (P1) — **SHIPPED 2026-05-27**

**Status**: COMPLETE. All four tasks landed in a single commit on `feat/plan-0099-w4`
(continuation branch). T-W2-01 `chat_orchestrator.py` emits one aggregate
`Loading <tools>… (N more)…` status frame right after iteration-0 picks tools;
T-W2-02 `harness.py` extended `_CONTENT_EVENT_KINDS` to include `tool_call` +
`status`; T-W2-03 `MessageTurn.tsx` renders the badge via `initialStatus` prop
(wired from `useChatStream` → `StreamingMessage.initial_status`); T-W2-04 docs
updated (`docs/services/rag-chat.md` SSE table + TTFT row, rag-chat
`.claude-context.md` pitfall, harness docstring). Regression tests:
`test_orchestrator_emits_aggregate_status_badge_before_tool_calls` +
`test_harness_latency.py::TestTTFTBroadenedSemantics` (4 cases) +
`MessageTurn.test.tsx` (2 new cases). Bug pattern: BP-607.


**Goal**: Drop chat-eval TTFT-p95 from 69.7 s → ≤5 s and bring
user-perceived latency in line with Claude.ai / ChatGPT / Cursor /
Perplexity by emitting one human-readable status event at first-LLM-turn
completion and redefining the harness gate to treat tool_call/status as
"first user-visible activity".

**Depends on**: none (independent of W1; safe to ship in parallel).
**Estimated effort**: ~3 h (T-W2-01 ~30m + T-W2-02 ~1 h + T-W2-03 ~30m
                       + T-W2-04 ~1 h).
**Architecture layer**: rag-chat application + apps/worldview-web
                        feature + tests/validation harness.
**Branch**: `feat/plan-0100-w2`
**Migration**: NO
**Docker rebuild**: YES — rag-chat (T-W2-01); frontend rebuild for
                    T-W2-02.

#### Tasks

##### T-W2-01: Backend `emit_status("Loading <tool list>…")` after first LLM turn

**Type**: impl + unit test
**Audit refs**: `docs/audits/2026-05-27-plan-0100-ux-thinking-vs-reasoning.md` §7
              + `docs/audits/2026-05-27-plan-0100-latency-structural.md` Part A.
**File**: `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py`

**What to build**:
1. After the first LLM turn returns `tool_calls` and before the
   tool-dispatch loop begins, compose:
   ```python
   tool_summary = ", ".join(tc.name for tc in llm_response.tool_calls[:3])
   if len(llm_response.tool_calls) > 3:
       tool_summary += f"… ({len(llm_response.tool_calls)} more)"
   yield p.emitter.emit_status(f"Loading {tool_summary}…")
   ```
2. Use a small lookup table (`_TOOL_FRIENDLY_LABELS`) to map
   internal tool names (e.g. `search_documents` → "documents",
   `get_entity_intelligence` → "entity intelligence") so the composed
   string is user-friendly, not API-named.
3. Unit test in `services/rag-chat/tests/unit/use_cases/test_chat_orchestrator_status_emission.py`:
   simulate 1 / 2 / 4 tool calls; assert composed string matches
   expected ("Loading documents…" / "Loading documents, fundamentals…"
   / "Loading documents, fundamentals, entity map… (1 more)").

**Acceptance check**: unit test passes; live SSE stream against a
tool-using question shows a `status` event with the friendly text
within ~1-3s of request start.

**Migration**: NO. **Docker rebuild**: YES — rag-chat.

##### T-W2-02: Frontend render initial `status` event as lightweight badge

**Type**: impl + Vitest snapshot
**Audit ref**: `docs/audits/2026-05-27-plan-0100-ux-thinking-vs-reasoning.md` §2 + §7.
**File**: `apps/worldview-web/features/chat/StreamingBubble.tsx`
              (and any sibling files holding the badge component if
              not already present).

**What to build**:
1. Render the first `status` event with `kind === "status"` as a
   lightweight pill (smaller, dimmer than the full `ToolCallIndicator`)
   ABOVE the soon-to-arrive tool-call pills. Once any `tool_call`
   event arrives, the status pill is replaced by the full
   `ToolCallIndicator` row.
2. Reuse the existing pill formatting + iconography (per UX audit §2:
   "Frontend has everything needed for Pattern B — just needs an
   earlier trigger").
3. Vitest snapshot test:
   - Snapshot 1: SSE stream contains only `status` → badge renders.
   - Snapshot 2: SSE stream contains `status` then `tool_call` →
     `ToolCallIndicator` replaces the badge.

**Acceptance check**: snapshot tests pass; manual smoke against a
local rag-chat shows the badge appears in ≤1-3s and is smoothly
replaced by the full pills.

**Migration**: NO. **Docker rebuild**: frontend rebuild only.

##### T-W2-03: Chat-eval harness — extend `_CONTENT_EVENT_KINDS`

**Type**: impl + docstring update
**Audit ref**: `docs/audits/2026-05-27-plan-0100-latency-structural.md` Part A Option A2 (RECOMMENDED).
**File**: `tests/validation/chat_eval/harness.py` (line 74 today).

**What to build**:
1. Update:
   ```python
   _CONTENT_EVENT_KINDS: frozenset[str] = frozenset(
       {"tool_call", "status", "token", "delta", "text", "final_answer"}
   )
   ```
2. Update the gate-module docstring (in
   `tests/validation/chat_eval/test_aggregate_score.py` and the
   harness module-level docstring) so the **5.0 s TTFT-p95 gate
   threshold is unchanged** but its semantics now read: *"time to
   first user-visible activity (status / tool_call / token)"*. Cite
   PLAN-0100 W2 + the latency-structural audit.
3. Cross-reference in `docs/services/rag-chat.md` "Chat-eval
   acceptance gate" subsection.

**Acceptance check**: harness unit tests still pass; gate documentation
reflects new semantics.

##### T-W2-04: Unit test for new TTFT semantics on synthetic stream

**Type**: new test
**File** (NEW or extend): `tests/validation/chat_eval/test_harness_latency.py`

**What to build**:
1. Synthetic event stream:
   - `metadata` event at t=0.5 s (excluded — non-content)
   - `tool_call` event at t=1.2 s (NEW — should tick TTFT)
   - `tool_result` event at t=4.5 s (excluded)
   - `token` event at t=15.0 s (existing content kind)
2. Assert `ttft_s ≈ 1.2` (NOT 15.0). Use `pytest.approx` with
   ±0.05 s tolerance.
3. Add second test: synthetic stream containing ONLY `metadata` +
   `status` + `token` — assert TTFT ticks on status, not token.

**Acceptance check**: tests pass; intentionally removing `tool_call`
from `_CONTENT_EVENT_KINDS` flips them red.

#### Validation gate

- [ ] ruff + mypy clean on rag-chat
- [ ] T-W2-01 unit test passes; live SSE shows status event ≤3 s
- [ ] T-W2-02 Vitest snapshots pass; frontend smoke shows badge
- [ ] T-W2-03 + T-W2-04 harness tests pass with new gate semantics
- [ ] Chat-eval rerun: TTFT-p95 drops 69.7 s → ≤5 s; verdict mix
      unchanged from W1's contribution

#### Compounding updates

- `docs/services/rag-chat.md` — Pattern B status emission section +
  updated chat-eval gate semantics.
- `apps/worldview-web/.claude-context.md` (if exists) or
  `docs/apps/worldview-web.md` — status-badge render path.
- `services/rag-chat/.claude-context.md` — pitfall: "do not silently
  skip the first-LLM-turn status emission; chat-eval TTFT gate depends
  on it landing within 5 s".
- `docs/BUG_PATTERNS.md` — **BP-606** ("TTFT gate measured only
  content-token events; tool-using questions paid full tool RTT before
  first tick → 69 s p95; extended `_CONTENT_EVENT_KINDS` + emit
  `status` after first LLM turn"). Reserved.
- `docs/plans/TRACKING.md` — PLAN-0100 row update.

---

### Wave W3 — Q1 AAPL KG gap (P1 — investigate + smallest possible fix)

**Goal**: Lift Q1 ("Apple competitors") from MARGINAL to USEFUL by
fixing the empty `get_entity_intelligence(AAPL)` bundle. Per the
PLAN-0099 W3 audit, this is Branch-B (KG/data gap, not prompt).

**Depends on**: none (independent of W1/W2/W4/W5/W6/W7).
**Estimated effort**: ~3 h (T-W3-01 ~1.5 h investigation + T-W3-02
                       ~1 h fix + T-W3-03 ~30m test).
**Architecture layer**: knowledge-graph application/infrastructure +
                        possibly content-ingestion or migrations
                        (TBD by investigation).
**Branch**: `feat/plan-0100-w3`
**Migration**: NO (anticipated; investigation may surface a small
                 backfill script)
**Docker rebuild**: knowledge-graph if formatter fix; otherwise none.

#### Tasks

##### T-W3-01: Investigate why `get_entity_intelligence(AAPL)` returns empty

**Type**: investigate + audit report
**Audit ref**: `docs/audits/2026-05-27-plan-0099-w3-q1-q2-investigation.md` Q1 §"Database state".

**Investigation steps**:
1. Walk the S7 KG path:
   - `SELECT id, ticker, canonical_name FROM canonical_entities WHERE ticker='AAPL';`
     — confirm Apple Inc. + duplicate `52a92aa8-…`.
   - `SELECT count(*) FROM entity_relations WHERE source_entity_id IN
     (SELECT id FROM canonical_entities WHERE ticker='AAPL');`
     — does AAPL have outbound `competitor_of` edges?
   - `SELECT count(*) FROM entity_paths WHERE source_entity_id = $AAPL_ID;`
     — are there pre-computed paths?
   - `SELECT * FROM entity_narratives WHERE entity_id = $AAPL_ID;`
     — narrative present?
2. Trace the `get_entity_intelligence` use case + formatter — does it
   filter on `is_active`, `published_at`, or similar that would drop
   AAPL rows?
3. Compare with a known-good entity (e.g. NVDA, MSFT) — what differs?
4. Write findings to
   `docs/audits/2026-05-28-plan-0100-aapl-kg-investigation.md`.

**Acceptance check**: report classifies root cause as one of: (a)
KG ingestion missed AAPL relations; (b) formatter drops bundle on a
specific filter; (c) duplicate `52a92aa8-…` is hijacking the resolver
and the real AAPL bundle is on the canonical row but resolver picks
the empty duplicate.

##### T-W3-02: Ship smallest possible fix

**Type**: impl (scope TBD by T-W3-01)
**File**: TBD — could be formatter, resolver, or a backfill script.

**What to build**:
- If (a): trigger ingestion backfill for AAPL via the relevant worker;
  verify relations populate.
- If (b): fix the offending formatter filter; add a regression test.
- If (c): clean up the duplicate (one-shot script merging into the
  canonical row); add resolver guard preferring rows with non-empty
  bundles.

**Acceptance check**: `get_entity_intelligence(AAPL)` returns a
non-empty bundle in live nlp_db / intelligence_db.

**Migration**: NO. **Docker rebuild**: only if formatter fix
(knowledge-graph).

##### T-W3-03: Regression test for `get_entity_intelligence(AAPL)`

**Type**: new test
**File** (NEW): `services/knowledge-graph/tests/integration/test_get_entity_intelligence_aapl.py`

**What to build**:
1. Seed AAPL canonical entity + at least 1 `competitor_of` relation
   + 1 narrative paragraph.
2. Call `get_entity_intelligence(entity_id=AAPL_ID)`.
3. Assert: non-empty `relations` list with at least one
   `competitor_of` edge; non-empty `narrative` field.

**Acceptance check**: test passes; deliberately deleting the relation
flips it red.

#### Validation gate

- [ ] ruff + mypy clean on knowledge-graph (if code shipped)
- [ ] T-W3-01 investigation report filed
- [ ] T-W3-02 fix shipped (or backfill executed) per investigation
- [ ] T-W3-03 regression test passes
- [ ] Chat-eval Q1 rerun: verdict moves MARGINAL → USEFUL with ≥2 of
      Samsung / Microsoft / Google / Huawei / Xiaomi mentioned

#### Compounding updates

- `docs/services/knowledge-graph.md` — note on the AAPL fix path
  (formatter / resolver / backfill, whichever shipped).
- `services/knowledge-graph/.claude-context.md` — pitfall entry.
- `docs/BUG_PATTERNS.md` — **BP-607** if a new failure class
  identified; otherwise documentation-only update referencing
  BP-461 / BP-459 family of KG resolution issues. Reserved.
- `docs/plans/TRACKING.md` — PLAN-0100 row update.

---

### Wave W4 — AMD fundamentals freshness (P1)

**Goal**: Get AMD Q1 FY2026 fundamentals flowing so Q4 chat-eval
variants pass. Per the fundamentals-followups audit Part A, most likely
H1 (worker disabled / never ran).

**Depends on**: PLAN-0099 W2-T02 `FundamentalsRefreshWorker` in main.
**Estimated effort**: ~3 h (T-W4-01 diagnostic ~30m + T-W4-02 manual
                       refresh ~30m + T-W4-03 flag flip ~30m + T-W4-04
                       dashboard panel ~1.5 h).
**Architecture layer**: market-data ops + market-ingestion env config +
                        observability dashboards.
**Branch**: `feat/plan-0100-w4`
**Migration**: NO
**Docker rebuild**: NO for T-W4-01 / T-W4-02; market-ingestion env
                    rebuild for T-W4-03.

#### Tasks

##### T-W4-01: H1 diagnostic SQL — `last_fundamentals_ingest_at` for AMD

**Type**: ops + audit note
**Audit ref**: `docs/audits/2026-05-27-plan-0100-fundamentals-followups.md` Part A H1.

**What to run**:
```sql
SELECT id, symbol, exchange, last_fundamentals_ingest_at, fiscal_year_end_month
FROM instruments WHERE symbol='AMD';
```

Document the actual value in
`docs/audits/2026-05-28-plan-0100-amd-fundamentals-investigation.md`.

**Acceptance check**: H1 confirmed (NULL or pre-Apr-2026) OR H1
falsified (recent timestamp), guiding next step.

##### T-W4-02: Trigger refresh + verify; walk H2 → H3 → H4 if still missing

**Type**: ops + (maybe) diagnostic
**Audit ref**: Part A H2-H4.

**Sequence**:
1. If H1 confirmed: `python scripts/refresh_fundamentals.py --tickers AMD`;
   re-query `last_fundamentals_ingest_at` (should update within ~30 s);
   `SELECT period_end_date, period_type, data->'revenue' FROM
   earnings_history WHERE instrument_id = $AMD_ID ORDER BY
   period_end_date DESC LIMIT 6;` — expect Q1 FY2026 + Q4 FY2025 with
   non-empty revenue.
2. If still missing: H2 — direct EODHD API call to confirm Q1 FY2026
   data exists upstream.
3. H3: remove period_type filter in a one-off query; check if Q1
   appears under any label.
4. H4: check `fiscal_year_end_month` NULL; if so, document the
   labeling fallback's behaviour.
5. Update investigation audit with conclusion at each step.

**Acceptance check**: live `GET /v1/fundamentals/AMD/history?periods=4`
returns Q1 FY2026 + Q4 FY2025 with non-empty `revenue` field.

##### T-W4-03: Flip `FUNDAMENTALS_REFRESH_ENABLED` default → `true`

**Type**: env config + doc
**Audit ref**: Part A "Sustainable".
**File**: `services/market-ingestion/configs/docker.env` (or wherever
              the default is wired) + `services/market-ingestion/src/.../config.py`
              if the default sits in pydantic-settings.

**What to build**:
1. Flip default `FUNDAMENTALS_REFRESH_ENABLED=true`. Per-deploy
   opt-out is preserved by the explicit env var.
2. Document the change in `docs/services/market-ingestion.md` —
   include the opt-out instruction.
3. Verify post-flip behaviour for 24 h: monitor
   `fundamentals_refresh_attempts_total{status="rate_limited"}` —
   expect it to stay low (BP-114 backoff working).

**Acceptance check**: 24 h after flip, ≥50 % of top-500-by-market-cap
instruments have `last_fundamentals_ingest_at > now() - interval '24h'`;
rate-limit counter stays within bounded backoff envelope.

**Migration**: NO. **Docker rebuild**: YES — market-ingestion.

##### T-W4-04: Operator-dashboard freshness panel

**Type**: ops (Grafana JSON or equivalent)
**File** (NEW): `infra/grafana/dashboards/fundamentals_freshness.json`
              (or per existing dashboard convention).

**What to build**:
1. Panel: rows from `instruments` binned by `last_fundamentals_ingest_at`
   age:
   - 0-1 d (fresh)
   - 1-7 d (acceptable)
   - 7-30 d (stale)
   - >30 d (very stale)
   - NULL (never ingested)
2. Definition of "stale" for alerting: `> 7 days`.
3. Screenshot in the W4 investigation audit doc.

**Acceptance check**: panel renders against live metrics; rows sum
to total instrument count.

#### Validation gate

- [ ] T-W4-01 diagnostic recorded in audit
- [ ] T-W4-02 AMD Q1 FY2026 present in DB with non-empty revenue
- [ ] T-W4-03 flag flipped; 24 h backoff envelope clean
- [ ] T-W4-04 dashboard panel deployed and renders
- [ ] Chat-eval Q4 variants v1/v2/v3/v4/v6 pass (USEFUL, not refusal)

#### Compounding updates

- `docs/services/market-ingestion.md` — `FUNDAMENTALS_REFRESH_ENABLED`
  default flipped to `true`; opt-out instructions.
- `docs/services/market-data.md` — fundamentals freshness dashboard
  panel reference.
- `services/market-ingestion/.claude-context.md` — pitfall: "default
  is now enabled; opt out per-deploy if EODHD quota is tight".
- `docs/BUG_PATTERNS.md` — note BP-578 status review (likely
  promote MITIGATED → FIXED if T-W4-03 holds 1 week of clean
  metrics).
- `docs/plans/TRACKING.md` — PLAN-0100 row update.

---

### Wave W5 — Top-N-by-market-cap internal endpoint (P2)

**Goal**: Replace the curated 30-ticker CSV in `FundamentalsRefreshWorker`
with a market-data-served top-N-by-market-cap list. Per fundamentals
audit Part B Option 1 (REST endpoint, not Kafka).

**Depends on**: PLAN-0099 W2-T02 worker in main; W4 not blocking but
                strongly preferred so W5 ships on a known-good worker.
**Estimated effort**: ~4 h (T-W5-01 endpoint ~2 h + T-W5-02 worker
                       refactor ~1 h + T-W5-03 CSV demotion ~30m).
**Architecture layer**: market-data API + market-ingestion infrastructure.
**Branch**: `feat/plan-0100-w5`
**Migration**: NO
**Docker rebuild**: YES — market-data + market-ingestion

#### Tasks

##### T-W5-01: New endpoint `GET /internal/v1/instruments/top-by-market-cap`

**Type**: new router + use case + tests
**Audit ref**: `docs/audits/2026-05-27-plan-0100-fundamentals-followups.md` Part B "Sketch — endpoint contract".
**File** (NEW or extend): `services/market-data/src/market_data/api/routers/instruments.py`
              + new use case `services/market-data/src/market_data/application/use_cases/get_top_instruments_by_market_cap.py`
              + read repo port + adapter.

**What to build**:
1. Endpoint signature:
   ```
   GET /internal/v1/instruments/top-by-market-cap?n=500&offset=0
   Headers: X-Internal-JWT: <signed-jwt>
   ```
   Response shape per audit:
   ```json
   {
     "total": <int>, "offset": <int>, "limit": <int>,
     "results": [{"id", "symbol", "exchange", "market_cap_usd",
                   "currency_code"}, ...]
   }
   ```
2. Clamp `n` to `[1, 5000]`; reject otherwise (422).
3. SQL per audit:
   ```sql
   WITH latest_mktcap AS (
       SELECT DISTINCT ON (instrument_id) instrument_id,
              value_numeric AS market_cap_usd
       FROM fundamental_metrics
       WHERE field_name = 'market_capitalization'
       ORDER BY instrument_id, ingested_at DESC
   )
   SELECT i.id, i.symbol, i.exchange,
          COALESCE(lm.market_cap_usd, 0) AS market_cap_usd,
          i.currency_code
   FROM instruments i
   LEFT JOIN latest_mktcap lm ON i.id = lm.instrument_id
   WHERE i.is_active = TRUE
   ORDER BY lm.market_cap_usd DESC NULLS LAST
   LIMIT :limit OFFSET :offset;
   ```
4. Per R16: API router calls a use case (`GetTopInstrumentsByMarketCapUseCase`)
   — never `infrastructure/` directly.
5. Per R17: use case depends on `ReadOnlyUnitOfWork` (read-only).
6. 4 tests in `services/market-data/tests/unit/api/test_top_by_market_cap.py`:
   - happy path (top-10 returns 10 sorted desc)
   - edge: `n=1` returns 1; `n=5001` clamped (or 422)
   - auth: missing `X-Internal-JWT` → 401
   - all-NULL market_caps fallback to symbol-order tail

**Acceptance check**: endpoint returns sorted list; tests pass; live
curl with internal JWT returns top-10 ordered by market cap.

**Migration**: NO. **Docker rebuild**: YES — market-data.

##### T-W5-02: `FundamentalsRefreshWorker` consumes the endpoint

**Type**: impl + unit test
**File**: `services/market-ingestion/src/market_ingestion/infrastructure/workers/fundamentals_refresh_worker.py`

**What to build**:
1. At worker boot OR once per 6-hour cycle: call the new endpoint via
   internal JWT (existing `InternalJWTMiddleware`-issued token).
2. Cache the result list in-memory for the 6-hour cycle.
3. Fall back to `FUNDAMENTALS_REFRESH_SYMBOLS` CSV if the endpoint
   call fails (logged WARN; counter `fundamentals_refresh_topn_fetch_total{outcome}`).
4. Unit test mocking the endpoint: assert worker uses the response
   over the CSV; assert fallback to CSV on HTTP error.

**Acceptance check**: unit test passes; live worker logs show
"top-500 fetched from market-data" on each 6h cycle.

**Migration**: NO. **Docker rebuild**: YES — market-ingestion.

##### T-W5-03: Demote curated CSV to fallback-only

**Type**: code + doc
**File**: same worker config.

**What to build**:
1. Add env var `FUNDAMENTALS_REFRESH_SYMBOLS_FALLBACK_ONLY=true`
   (default `true`) — when set, the CSV is used ONLY on endpoint
   fetch failure.
2. Update doc to reflect that the normal operational path is the
   endpoint; CSV is the operator escape hatch.

**Acceptance check**: with `FALLBACK_ONLY=true`, manual CSV edits
have no effect when endpoint is reachable; with `=false`, CSV
overrides (back-compat mode).

#### Validation gate

- [ ] ruff + mypy clean on market-data + market-ingestion
- [ ] T-W5-01 4 tests pass; endpoint live + auth-gated
- [ ] T-W5-02 unit test passes; live worker pulls from endpoint
- [ ] T-W5-03 fallback path works on simulated 500 from endpoint

#### Compounding updates

- `docs/services/market-data.md` — new internal endpoint section.
- `docs/services/market-ingestion.md` — worker consumes endpoint
  instead of curated CSV; CSV is fallback-only.
- `services/market-data/.claude-context.md` + `services/market-ingestion/.claude-context.md` —
  cross-references.
- `docs/BUG_PATTERNS.md` — no new BP; this is a feature-add.
- `docs/plans/TRACKING.md` — PLAN-0100 row update.

---

### Wave W6 — Model-swap decision data collection (P2 — gated on W2)

**Goal**: After W2 ships and ≥1 week of phase-timing artifacts
accumulate, decide whether to prepare PLAN-0101 model-swap pilot
(Llama 3.1 70B Turbo) or close the deferred W1-T04 as "not needed".
Pure data collection — NO swap this wave.

**Depends on**: W2 in main + ≥1 week of chat-eval runs producing
                `chat_phase_timings_ms` artifacts.
**Estimated effort**: ~2 h (T-W6-01 ~1.5 h aggregation + T-W6-02 ~30m
                       decision doc).
**Architecture layer**: scripts + docs.
**Branch**: `feat/plan-0100-w6`
**Migration**: NO
**Docker rebuild**: NO

#### Tasks

##### T-W6-01: Aggregate `chat_phase_timings_ms` from ≥1 week of artifacts

**Type**: script + audit
**Audit ref**: `docs/audits/2026-05-27-plan-0100-latency-structural.md` Part B "Data to Collect".
**File** (NEW): `scripts/aggregate_chat_phase_timings.py`

**What to build**:
1. Iterate `tests/validation/chat_eval/runs/<*>/agg_q*.json` over the
   trailing 7 days (or take a `--since` flag).
2. Pull `chat_phase_timings_ms` from each artifact (and/or grep
   container logs over the same window).
3. Compute mean / p50 / p95 per phase:
   `check_cache`, `validate_input`, `load_history`, `entity_resolution`,
   `llm_tool_planning`, `tool_execution`, `llm_synthesis_streaming`,
   `grounding_validation`, `persist_and_cache`.
4. Output CSV + markdown table to
   `docs/audits/2026-06-XX-plan-0100-w6-phase-timings-aggregate.md`.

**Acceptance check**: aggregate table populated with ≥20 sample runs.

##### T-W6-02: Decision document — pilot or close

**Type**: docs
**File** (NEW): `docs/audits/2026-06-XX-plan-0100-w6-model-swap-decision.md`

**Decision criterion**:
- If `llm_synthesis_streaming` > 50 % of LLM time (planning + synthesis)
  AND `e2e_p99 > 60 s` post-W2 → **prepare PLAN-0101 model-swap pilot**
  using Llama 3.1 70B Turbo per latency-structural Part B "Recommended
  Model Swap Candidates" table.
- Otherwise → **close as "not needed"** with rationale citing the
  aggregate table.

**Acceptance check**: decision documented; if pilot, PLAN-0101 stub
row appended to TRACKING.md.

#### Validation gate

- [ ] T-W6-01 aggregate table populated and committed
- [ ] T-W6-02 decision document committed
- [ ] If decision = pilot: PLAN-0101 stub row in TRACKING.md

#### Compounding updates

- `docs/services/rag-chat.md` — phase-timing observability section
  extended with aggregate snapshot.
- `services/rag-chat/.claude-context.md` — pointer to the decision
  audit.
- `docs/BUG_PATTERNS.md` — no new BP; data-collection wave.
- `docs/plans/TRACKING.md` — PLAN-0100 row update; PLAN-0101 row if
  pilot.

---

### Wave W7 — §13.4 upstream `tenant_id=None` source trace (P2 — gated on counter data)

**Goal**: Identify the dominant `block_source` from the
`nlp_pipeline_pre_persist_tenant_id_substituted_total{block_source}`
counter (shipped PLAN-0099 W2-T04) and fix the upstream construction
site so the persist-boundary safety net (R43) stops firing.

**Depends on**: PLAN-0099 W2-T04 counter in main + ≥1 week of
                production data accumulated.
**Estimated effort**: ~2 h (T-W7-01 calendar-gated wait + T-W7-02
                       ~1.5 h trace + fix + test).
**Architecture layer**: nlp-pipeline (upstream construction sites).
**Branch**: `feat/plan-0100-w7`
**Migration**: NO
**Docker rebuild**: YES — nlp-pipeline (if fix ships)

#### Tasks

##### T-W7-01: Wait for ≥1 week of counter data

**Type**: calendar gate + grep

**What to do**:
1. After ≥7 days post-PLAN-0099 W2-T04 ship, query Prometheus:
   ```
   topk(5, sum by (block_source)(
       increase(nlp_pipeline_pre_persist_tenant_id_substituted_total[7d])
   ))
   ```
2. Document the dominant `block_source` label in
   `docs/audits/2026-06-XX-plan-0100-w7-upstream-tenant-id-trace.md`.

**Acceptance check**: top `block_source` identified with a clear
plurality (>50 % of substitutions).

##### T-W7-02: Trace upstream + fix construction site

**Type**: investigate + fix + test
**File**: TBD (the block-source-specific consumer / worker / mention-
              constructor — likely one of NER post-stamp, GLiNER
              consumer, LLM extract handler, per the W2-T04 enum).

**What to build**:
1. Grep the dominant `block_source` from its label value back to its
   `EntityMention` construction site.
2. Walk the call chain to find why `tenant_id` arrives as `None` at
   the construction site (per audit §13.6 — the correct long-term
   fix lives at construction, not at persist boundary).
3. Fix upstream so the persist-boundary safety net stops firing for
   this `block_source`.
4. Regression test asserting that the previously-offending construction
   path now sets `tenant_id` correctly without relying on the
   persist-boundary default.

**Acceptance check**: 7 days post-fix, the counter for the previously-
dominant `block_source` is at zero (or near-zero); R43 safety net
remains a backstop but no longer carries production load for that
source.

**Migration**: NO. **Docker rebuild**: YES — nlp-pipeline.

#### Validation gate

- [ ] T-W7-01 audit identifies dominant `block_source`
- [ ] T-W7-02 fix shipped; regression test passes
- [ ] 7-day post-fix counter for dominant `block_source` ≈ 0

#### Compounding updates

- `docs/services/nlp-pipeline.md` — construction-site fix note;
  R43 safety-net status update (still required as a backstop).
- `services/nlp-pipeline/.claude-context.md` — pitfall update.
- `docs/BUG_PATTERNS.md` — **BP-608** ("upstream `tenant_id=None`
  at <block_source> construction site; fixed at construction; R43
  persist-boundary safety net remains as backstop"). Reserved.
- `docs/plans/TRACKING.md` — PLAN-0100 row update.

---

## §5 — Cross-Cutting Acceptance Gate

**Trigger**: W1 + W2 + W3 + W4 all ship (W5 is hygiene; W6/W7 are
calendar-gated).

**Why all 4 are gating**: W1 closes the HARMFUL class (verdict mix
floor); W2 brings TTFT into spec; W3 lifts Q1 → USEFUL; W4 lifts Q4
variants → USEFUL. Together they target USEFUL ≥7 + HARMFUL = 0 +
USELESS = 0 with TTFT-p95 < 5 s.

**Command** (foreground bash + `disown`, NOT nested agent — per
PLAN-0098 §5 + unblock audit §6):

```bash
RAG_CHAT_BASE_URL=http://localhost:8000 \
  RAG_COMPLETION_CACHE_DISABLED=true \
  DEBUG_SKIP_CLASSIFIER=true \
  APP_ENV=dev \
  pytest tests/validation/chat_eval/test_aggregate_score.py 2>&1 | tee /tmp/chat_eval_PLAN0100.log &
disown
```

**Pre-gate live SLO checks**:

```sql
-- 1. entity_mentions backfill landed (W1-T04)
SELECT count(*) FROM entity_mentions WHERE resolved_entity_id IN
  (SELECT id FROM canonical_entities WHERE ticker='MSTR');
-- expect ≥25

-- 2. AMD Q1 FY2026 present (W4)
SELECT period_end_date, period_type, data ? 'revenue' AS has_revenue
FROM earnings_history
WHERE instrument_id = (SELECT id FROM instruments WHERE symbol='AMD')
  AND period_type = 'QUARTERLY'
ORDER BY period_end_date DESC LIMIT 4;
-- expect Q1 FY2026 row with has_revenue=true

-- 3. AAPL KG bundle non-empty (W3)
-- application-level check via tool: get_entity_intelligence(AAPL).item_count > 0

-- 4. Status emission live (W2)
-- grep rag-chat logs for "emit_status" with text matching "Loading "
```

**Pass criteria**:
- **Verdict**: USEFUL ≥ 7 (W1 lifts Q2 from HARMFUL to USEFUL; W3 may
  lift Q1 from MARGINAL); HARMFUL = 0; USELESS = 0.
- **Latency**: TTFT-p95 < 5 s (W2 redefines + emits status);
  TPS-p50 ≥ 30 tok/s (unchanged from PLAN-0099 — chunk streaming
  already live via BP-595); E2E-p99 < 90 s (relaxed watchdog — W2
  doesn't change E2E).
- No new error log lines in nlp-pipeline / rag-chat / market-data /
  knowledge-graph / market-ingestion for 15 min post-deploy.

**On fail**: investigate which gate is red; if TTFT-p95 still > 5 s
after W2, verify `emit_status` event actually fires (rag-chat log
grep) AND harness `_CONTENT_EVENT_KINDS` actually includes `status` /
`tool_call`; if verdict mix is red, attribute per-question and file
follow-up.

---

## §6 — Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| W1 BP-603 JSONB-containment query changes production search ranking / ordering, surfacing previously-hidden chunks that change answer text for non-MSTR questions | Medium | Medium | Integration test asserts no-duplicate on chunks where both table + JSONB present; pre-deploy live-replay 5 known-good queries (NVDA earnings, AAPL competitors, etc.) and diff retrieved-item count before/after; if delta > 20 %, investigate before merge |
| W1 BP-604 entity-drift guard rejects legitimate multi-entity iteration (e.g. "compare AAPL and MSFT" where the second turn legitimately introduces MSFT) | Medium | High | Guard explicitly checks question-resolved entities AND prior tool_call inputs (NOT just question); add regression test for the "compare AAPL and MSFT" case to ensure MSFT in second turn is accepted |
| W1 BP-605 synthesis grounding check refuses answers where the LLM produced an entity-name with slightly different casing / formatting than the resolved entity (e.g. "MicroStrategy Inc" vs "MicroStrategy Incorporated") | Medium | Medium | Grounding check normalises entity names via the resolver (existing canonical-entity lookup) before comparison; fall back to `entity_id` equality; regression test for casing variants |
| W2 status badge confuses users who are used to silent execution | Low | Low | Badge is a small additive UX element; if user feedback is negative, the harness change still stands (zero LLM cost) and the frontend badge can be reverted independently |
| W4 `FUNDAMENTALS_REFRESH_ENABLED=true` default hits EODHD rate limits under top-500 fan-out | Medium | Medium | BP-114 exponential backoff already in worker; monitor `fundamentals_refresh_attempts_total{status="rate_limited"}` for 24 h; if > 5 % of attempts throttle, revert default to `false` and ship larger backoff |
| W4 H1 falsified — worker did run for AMD but data is genuinely missing → H2-H4 escalation extends wave to ~6 h | Low | Low | Wave estimate already includes hypothesis walk; if H4 also negative, file as PLAN-0101 ingestion-source coverage follow-up |
| W5 new endpoint becomes a hot read path; market-data DB pool exhaustion | Low | Low | Worker calls once per 6-hour cycle; expected QPS ~ negligible; endpoint reads only from `instruments` + `fundamental_metrics`, both indexed; load test with 100 concurrent requests in T-W5-01 unit tests |
| W6 aggregate table identifies no dominant phase (all phases roughly equal); no defensible swap decision | Low | Low | Decision doc explicitly allows "no clear winner" outcome → close W6 as "not needed"; revisit in a future PLAN if latency regresses |
| W7 dominant `block_source` is `"unknown"` (the catch-all enum bucket) — no actionable source | Medium | Medium | If `"unknown"` dominates, T-W7-01 widens to inspect raw consumer logs around substitution events to attribute manually; may surface a new enum value to add to the cardinality cap |
| Parallel-session worktree corruption (BP-590) during W1+W2+W3 parallel branches | Medium | High | Per CLAUDE.md "Parallel Sessions" + BP-590 — one worktree per branch; orchestrators that spawn parallel agents MUST allocate `git worktree add <path> -b <branch>` per child |

---

## §7 — Owner stub

- **PLAN-0100 owner**: Arnau Rodon (`arnaurodondev@gmail.com`)
- **W1 owner**: Arnau (P0 — all 4 tasks; ship in 1-2 commits)
- **W2 owner**: Arnau (backend + frontend + harness in parallel
                       sub-branches)
- **W3 owner**: Arnau (investigation-first; scope of fix TBD)
- **W4 owner**: Arnau (ops + env flip + dashboard)
- **W5 owner**: Arnau (endpoint + worker refactor)
- **W6 owner**: Arnau (calendar-gated; pull data + author decision)
- **W7 owner**: Arnau (calendar-gated; trace + fix)
- **Acceptance-gate executor**: Arnau (foreground bash + `disown`,
                                       NOT nested agent)

---

## §8 — Next revise-prd round

This plan is ready for next session's revise-prd + implementation
orchestration round. Remaining items for any future revise-prd round:

1. After W1 ships, confirm Q2 verdict moves HARMFUL → USEFUL on the
   first chat-eval rerun; if not, escalate which of BP-603/604/605
   failed to land.
2. After W2 ships, confirm TTFT-p95 drops from 69.7 s → ≤5 s; if
   gap remains, investigate whether `emit_status` fires on
   non-tool-using questions (refusal paths might skip it).
3. After W4 T-W4-03 flag flip + 24 h, decide whether to mark BP-578
   FIXED.
4. After W6 calendar gate, fold the decision into either PLAN-0101
   (pilot) or a "model-swap not needed" closure note.
5. After W7 calendar gate + fix, decide whether R43 (PLAN-0099 W5-T02)
   can demote from "load-bearing safety net" to "backstop only".

End of PLAN-0100 (draft 2026-05-28).
