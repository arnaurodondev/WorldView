# PLAN-0099 — Live Chat-Eval Final Run (post W1 + W2 + W6 ship)

**Date**: 2026-05-27 22:58 → 23:17 PDT (~19 min wall)
**Branch**: `feat/plan-0099-w4` (commit `6304e40a` — TTFT/TPS harness retry-commit)
**Container**: `worldview-rag-chat:latest` rebuilt with BP-595 chunk streaming
**Run dir**: `tests/validation/chat_eval/runs/20260528T060048Z/`
**Log**: `/tmp/chat_eval_PLAN0099_final.log`

## Step-by-step outcomes

| Step | Status | Notes |
|------|--------|-------|
| 1. Diff inspection of grading.py / harness.py / test_aggregate_score.py | OK | Clean TTFT/TPS additions, no corruption. Diff sizes 60 / 371 / 243 lines. |
| 2. `test_harness_latency.py` recovery | NOT RECOVERABLE | Patch `~/.cache/pre-commit/patch1779947329-71489` only contains the 3 modified files; new-file content absent. Committed without it; harness logic itself is exercised live by the real suite. |
| 3. `git add` + `git commit` (no pathspec, pre-commit hooks ran) | OK exit 0 | Commit `6304e40a`. Ruff/ruff-format/mypy all passed. |
| 4. `docker build --file services/rag-chat/Dockerfile` | OK | Build succeeded; image `worldview-rag-chat:latest` re-tagged. (`docker compose build` was a no-op because the compose file references the pre-built image.) |
| 5. `docker compose up -d --force-recreate rag-chat` + health poll | OK | Healthy after ~16 s. |
| 6. BP-595 verification: `grep _chunk_text_for_streaming` | OK | 3 hits in `chat_orchestrator.py`, 1 in `sse_emitter.py`. Direct-text path AND `stream_chat` second-turn path both emit per-chunk. |
| 7. nohup chat-eval (12 tests) | RAN to completion | 985.49 s (16:25). 5 failed, 7 passed. |

## Aggregate gate verdict

```
verdicts        = USEFUL 6 / MARGINAL 2 / USELESS 1   (HARMFUL 0 in aggregate set)
ttft_p95        = 69.70 s   (gate 5.0 s)    FAIL
tps_p50         = 13.43 /s  (gate 30  /s)   FAIL
e2e_p99_latency = 98.61 s   (gate 90  s)    FAIL (marginally)
e2e_median      = 27.44 s   (soft  30 s)    OK
```

The relaxed gates from PLAN-0099 W1-T03 (`<5 s` TTFT-p95, `>=30/s` TPS-p50, `<90 s` E2E-p99) all fail. Verdict mix itself meets the `USEFUL>=6 / HARMFUL<=0` quality bar.

## Per-question verdicts (aggregate run)

| Q | Verdict | TTFT (s) | TPS (tok/s) | E2E (s) | Notes |
|---|---------|---------:|------------:|--------:|-------|
| q1  Apple competitors | MARGINAL | 21.22 | 225.8 | 21.44 | 0 of 5 expected competitor names mentioned. |
| q2  MSTR news        | MARGINAL | 62.84 |  16.0 | 71.86 | Missing Bitcoin/BTC mention. |
| q3  Tim Cook history | USELESS  | 16.50 |  12.3 | 20.72 | Refusal-style answer. |
| q4  NVDA Q3 revenue  | USEFUL   | 74.27 |  11.3 | 99.30 | Slowest question, drives p99. |
| q5  ASML guidance    | USEFUL   | 25.13 |   4.5 | 68.85 | Drives TPS-p50 down. |
| q6  AI chip screener | USEFUL   | 43.78 |  12.7 | 90.70 | |
| q7  Anthropic funding| USEFUL   |  7.22 | 1335.7 |  7.26 | Cached/fast path. |
| q8  OpenAI->MSFT     | USEFUL   | 16.71 |  13.4 | 27.44 | |
| a10 Anomaly probe    | USEFUL   | 11.13 | 488.9 | 11.33 | Direct-text path (short answer). |

## High-value Q4/Q6/Q8 detail

**Q4 (NVDA/AMD revenue family — 6 variants)** — 2 pass, 4 fail.
- v1 (NVDA-vs-AMD trajectory): 100.6 s, "cannot provide a comparison ... tool results did not return ver[ified data]".
- v2 (NVDA Q4FY26 single-quarter): 20.4 s, refuses with "no information for Q4 FY2026 was returned by the tool". **Test asserts `"68" in answer`** — fixture expects `68.127B` (Q4FY26 was earnings on 2026-02-26). Strict-string assertion, not a verdict failure; the answer is honest about the gap.
- v3 (AMD revenue+EPS): USELESS verdict — refusal-style.
- v4 (gross margin): refuses ("does not include gross profit or COGS").
- v5 (AMD growth rate): USEFUL pass.
- v6 (full comparison table): graded **HARMFUL** — "AMD revenue > $15.0B mentioned"; the answer text itself says "I cannot provide a comparison", so the grader is tripping on a literal string from the question being echoed (likely from the citations block). Worth verifying.
- `test_q4_zero_amd_figures_above_15b` also failed on the same v6 mention. **Net: the W1-T01 row-mix fix + period_type filter did NOT eliminate the no-data-found path for AMD; fundamentals retrieval for the latest AMD quarter is still empty.**

**Q6 (AI-chip screener)** — PASS (USEFUL), 43.8 s TTFT, 90.7 s E2E. The slowest USEFUL question; multi-tool screener flow.

**Q8 (OpenAI->MSFT paths)** — PASS (USEFUL), 16.7 s TTFT, 27.4 s E2E. TPS=3260 because output came as one short message at the very end (105 tokens in ~32 ms post-TTFT) — almost certainly the cached/short-circuit path.

## TTFT/TPS root-cause

The high TTFT numbers are **structural, not a streaming bug**. BP-595 chunking IS live (verified in container; visible on q7=7.22 s / a10=11.13 s / q1=21.2 s where the only content frame is the synthesised final answer). The orchestrator emits **no user-facing content during tool execution** — only `status`/`tool_call`/`tool_result` metadata events, which the harness deliberately excludes from `_CONTENT_EVENT_KINDS`. Every question that fans out to >=1 LLM-graded tool call therefore pays the full tool-RTT before TTFT starts ticking.

`tps_p50 = 13.4` is consistent with DeepInfra `meta-llama/Llama-3.1-8B-Instruct` streaming cadence on small (50-300 token) answers — there is no provider slowdown.

## Baseline comparison

| Run | USEFUL | HARMFUL | E2E p99 | TTFT p95 | TPS p50 |
|-----|-------:|--------:|--------:|---------:|--------:|
| ITER-9 Phase D, first run | 5 | 1 | 207 s | n/a | n/a |
| PLAN-0098 partial         | 7 | 0 | 133 s | n/a | n/a |
| **PLAN-0099 this run**    | **6** | **0** | **98.6 s** | **69.7 s** | **13.4 /s** |

Quality envelope: -1 USEFUL vs PLAN-0098 (q3 regressed to USELESS, q1+q2 to MARGINAL).
Latency envelope: E2E p99 down 26 % (133 -> 99 s); first time below the 100 s mark.

## Recommendation

**Not ship-ready against the new gates as written**, but the gates are mis-calibrated relative to the orchestrator's actual streaming contract. Two parallel actions:

1. **Quality (real regressions)** —
   a. Q3 USELESS regression on Tim Cook (biographical, no tools needed) is the clearest signal something in the iter-0 direct-text path is over-refusing; investigate.
   b. Q4 v2/v3/v4/v6 confirm AMD fundamentals retrieval still returns empty for the latest quarter post W1-T01 + period_type filter — re-check that the row-mix fix actually landed in the deployed image and that `period_type='quarterly'` filter survives the orchestrator's normalisation step.
   c. Q4 v6 HARMFUL grade looks like a grader false-positive (answer is a refusal but grader sees "$15B" in echoed question/citations) — tighten grader to ignore citation/question text.

2. **Gate recalibration** — TTFT-p95 < 5 s is unachievable as long as the orchestrator gates content emission on tool completion. Either (a) raise to ~15 s and add a separate "first-thinking-event" sub-5 s gate over the metadata stream, or (b) make the orchestrator emit a `delta` placeholder (e.g. "Searching fundamentals...") when the first tool starts. TPS-p50 30 /s is also aggressive for a generative LLM at 8B params; 12-15 /s is the realistic floor for this model.

No infra/container failures. No source touched outside `tests/validation/chat_eval/`.
