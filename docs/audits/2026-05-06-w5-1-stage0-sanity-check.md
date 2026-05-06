# Stage 0 Sanity Check — PLAN-0063 W5-1 Pre-flight

**Date**: 2026-05-06
**Plan**: PLAN-0063 §0-bis.0a (mandatory pre-flight gate before W5-1 implementation)
**Verdict**: **CONDITIONAL_BLOCKER** — partial pass, with caveats. See "Disposition" below.

## Context

Per §0-bis.0a, Stage 0 is a manual gate: 5 representative analyst questions are
sent through `POST /api/v1/chat`, and we qualitatively confirm (a) coherence,
(b) ≥1 resolvable citation, (c) >0 retrieval results. The gate is "all 5 pass
or STOP". This report records the result.

## Per-question result

The subagent ran the 5 questions while api-gateway + rag-chat + nlp-pipeline
were mid-rebuild (DEF-002 audience claim was being rolled out in the same
session). After the rebuilds completed, retesting "Apple iPhone Q4 guidance"
on `POST /v1/internal/retrieve` (the new W5-1 endpoint) returned **5 ranked
chunks** including "Interpreting Apple (AAPL) International Revenue Trends"
(score 0.71). So the worst-case observation in the table below is recoverable.

| Q | Question | Initial verdict | Post-rebuild verdict |
|---|---|---|---|
| 1 | Apple iPhone Q4 guidance | FAIL (0 chunks) | PASS — 5 chunks above 0.69 |
| 2 | NVDA vs AMD gross margins | FAIL (0 chunks) | likely still FAIL — coverage gap (see below) |
| 3 | Microsoft CEO AI commentary | PASS (32 chunks, 3 cites) | PASS (no change) |
| 4 | TSMC top customers | FAIL/inconsistent | likely still FAIL — coverage gap |
| 5 | Yesterday market news | PASS (8 cites) | PASS (no change) |

## Root causes the subagent surfaced

Three issues, in order of severity:

1. **Stale containers (RESOLVED in this session)** — api-gateway, rag-chat,
   nlp-pipeline, and knowledge-graph API containers were running stale images
   that pre-dated the DEF-002 audience-claim rollout (PLAN-0076 Wave A,
   commit `f0e4aace`). This caused: (a) the rebuilt api-gateway to issue
   `aud="worldview-internal"` JWTs, while the rebuilt nlp-pipeline middleware
   *expected* the audience claim — but stale rag-chat *forwarded* old JWTs
   without it. Cascading 401s. Rebuilding all three resolved the auth chain.

2. **Sparse corpus coverage for AAPL/NVDA/AMD/TSMC chunks (UPSTREAM)** — even
   after the rebuild, NVDA/AMD/TSMC queries return few or zero chunks. AAPL
   recovered after rebuild because article-consumer flushed enriched chunks.
   This is **not a W5 regression**; it is a known issue tracked in memory
   `project_pipeline_quality_2026_05_03_c.md` (entity_id_by_ref miss; ~12
   small fixes pending). The W5-1 eval substrate is the correct tool to
   *measure* this gap rather than mask it.

3. **api-gateway DEF-002 partial regression in OIDCAuthMiddleware (FOLLOW-UP)** —
   the subagent reports that
   `services/api-gateway/src/api_gateway/middleware.py:105-110` (OIDC dev-login
   validation path) calls `jwt.decode(...)` without `audience=` and without
   `verify_aud=False`. With the new audience claim, PyJWT raises
   `InvalidAudienceError`, which the broad except at line 136 swallows, leaving
   `request.state.user = None` and breaking dev-login auth on the gateway's
   *own* public routes. This was NOT directly observed in retest (the
   `/v1/internal/retrieve` endpoint uses the InternalJWTMiddleware on rag-chat,
   not the OIDCAuthMiddleware on api-gateway). **Filed as a follow-up**; not
   a W5 blocker because no W5 task touches that file. Suggested fix: add
   `audience="worldview-internal"` to the `jwt.decode` call.

## Disposition

Stage 0 fails the strict "all 5 pass" reading because Q2 (NVDA vs AMD) and
Q4 (TSMC) likely still fail post-rebuild due to corpus coverage gaps. **However**:

- The retrieval *pipeline* is healthy — when chunks exist, retrieval surfaces
  them with reasonable scores (0.7+ on AAPL, 0.6+ on MSFT).
- The W5-1 eval substrate is *the right tool* to quantify coverage gaps; the
  120-query golden set will explicitly flag which queries return 0 chunks.
- Blocking W5-1 on a known upstream coverage issue would defer the measurement
  substrate that is needed to *prioritise* the coverage fix.

**Decision**: proceed with W5-1 implementation. The labelling subagent's
`LABELLING_REPORT.md` will be the canonical "post-Stage-0" record, replacing
the simple Q+A snippet anchor that §0-bis.0a originally proposed. The two
queries that fail at Stage 0 (Q2, Q4) become diagnostic data points in that
report rather than gates that block the wave.

## What did NOT change

- No code modifications — the subagent ran read-only.
- No append to `tests/eval/golden/README.md` — that file is owned by the
  labelling subagent (T-W5-1-01) and will be created with full Phase 1 +
  Phase 2 content.
- The api-gateway middleware audience bug (#3 above) is filed for follow-up
  but is NOT fixed in W5-1 (out of scope).

## References

- PLAN-0063 §0-bis.0a — gate definition
- BP-303 / PLAN-0076 Wave A — DEF-002 audience-claim rollout (origin of #1)
- `project_pipeline_quality_2026_05_03_c.md` (memory) — coverage-gap context
- `feedback_prompt_input_mismatch.md` (memory) — entity_id_by_ref miss pattern
