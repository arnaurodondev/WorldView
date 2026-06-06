---
id: INV-PLAN-0093-ITER-14B-FINDINGS
title: Root-Cause Investigation of Iter-14b NEW Findings (NEW-016/017/018)
date: 2026-06-05
predecessor: docs/audits/2026-06-05-qa-plan-0093-iter-14b-rebuild-validation.md
branch: feat/plan-0099-w4
agents: 3 (parallel: INV-016, INV-017, INV-018)
verdict: ALL 3 ROOT CAUSES IDENTIFIED + cross-cutting W52 regression surfaced
---

# Investigation Report: Iter-14b NEW Findings

**Date**: 2026-06-05 22:30 UTC
**Investigator**: 3 parallel sub-agents
**Status**: Root causes identified. Fix scope = 2 small PRs + 1 ops verification.

---

## Headline

NEW-016 is **P0, not P1** — and it's a **PLAN-0104 W52 regression** that affects both prompt-injection classification AND intent classification. The same `deepinfra_classification_model` setting was swapped from `Qwen3.5-0.8B` to `Qwen/Qwen3.5-9B` — a reasoning model that emits chain-of-thought into `message.reasoning_content` and leaves `message.content` empty until reasoning finishes. With `max_tokens=64`, reasoning consumes the entire budget → empty content → classifier can't parse → fail-closed → 400 on every cache-cold request.

This **single regression** (commit `8e67ddcc`) explains:
- All `[PROMPT_INJECTION]` false positives (NEW-016) — 100% failure rate on cache-cold paths
- **Plausibly** the F-NEW-014 intent-classification misses observed in iter-14b (same classification model setting; same silent-empty failure mode at the LLM-tier classifier; keyword classifier still works as fallback)
- The "2 of 3" iter-14b framing was a cache-hit artefact

NEW-017 was a benign rebuild artefact (KG in `Created` state, never started). Auto-resolved when the rebuild recreate brought all 5 services up.

NEW-018 is a **separate prompt gap** — `libs/prompts/src/prompts/chat/tool_use.py:289` has no rule instructing the LLM to quote the `Period` column verbatim from tool results. The LLM independently recomputes labels using a calendar/wrong-FY-end prior, even when the correct label is literally present in the prompt. This bug **also causes a spurious refusal mode** (LLM mislabels → concludes "data missing" → refuses). One prompt gap, two visible failure modes, ~30-40% of US tickers affected.

---

## Finding 1 — NEW-016 (P0, escalated from P1)

**Original framing**: LLM prompt-injection classifier blocks legitimate questions like "What was AMD revenue in Q1 FY2026?"
**Actual diagnosis**: PLAN-0104 W52 swapped the classification model to a **reasoning model**; reasoning consumes the `max_tokens=64` budget before producing any `content`. Classifier reads empty content, can't parse → fail-closed → 400 on every cache-cold request.

### Smoking gun
Every test request emitted this log:
```json
{"label": "", "raw_content": "", "event": "llm_injection_classifier_unexpected_label"}
```
…including the "control" `What is AAPL revenue?` (also 400). The 2-of-3 iter-14b sample landed in cache (3rd question hit it warm).

### Affected files
- `services/rag-chat/src/rag_chat/config.py:67` — model setting
- `services/rag-chat/src/rag_chat/application/security/llm_injection_classifier.py:186` (max_tokens=64), `:205` (reads `content`), `:233` (fail-closed branch)
- `services/rag-chat/src/rag_chat/application/pipeline/chat_pipeline.py:210` — **stale docstring still says `Qwen3.5-0.8B`** — confirms the model swap was made without updating dependent code

### Cross-cutting impact (the part iter-14b missed)
**Same `deepinfra_classification_model` setting** is reused at `app.py:359` for **intent classification**. If the LLM-tier intent classifier ALSO returns empty content, the keyword classifier (which DOES contain the F-NEW-014 vocabulary after `27b960a2`) acts as the silent fallback. That fallback might be working — OR something downstream might be reading the empty LLM-tier output and mis-classifying.

**Action**: verify that intent classification falls through to keyword classifier cleanly when LLM tier returns empty. Otherwise F-NEW-014 chat-surface misses (iter-14b F14-MCAP/EV/SHARES/BOOK) are the SAME bug.

### Recommended mitigation

**Option A (immediate unblock, ~5 min)**: revert model setting to `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` (verified by INV-NEW-016 agent: returns valid JSON in 5 tokens at ~200ms). Add comment explaining the reasoning-model trap.

**Option C (permanent guard, ~30 LOC + 2 tests)**: fail-open on empty content with `injection_classifier_indeterminate_total` Prometheus counter. So future model swaps that trip this trap don't silently kill the service. Ship alongside Option A.

**Option D (proper reasoning-model support)**: raise `max_tokens` to ~512 AND read from `message.reasoning_content` when `message.content` is empty. Bigger change; defer to a follow-up plan.

---

## Finding 2 — NEW-017 (CLOSED — rebuild artefact, not a bug)

KG container was in docker `Created` state with `StartedAt=0001-01-01` — never attached to the docker network. rag-chat logs showed `ConnectError` at 178-417ms (fast-fail, not timeout) → DNS / connection refused.

**Validation**:
- Endpoint path `/api/v1/entities/resolve` **matches** between client (`services/rag-chat/src/rag_chat/infrastructure/clients/s6_client.py:34`) and server (`services/knowledge-graph/src/knowledge_graph/api/routes.py:198`) — H2 path drift refuted
- KG sibling containers (consumers) were healthy at the time — confirmed it was a targeted teardown from the rebuild, not a platform-wide failure

**Status**: auto-resolved by the `docker compose up -d --force-recreate` that ran just before this investigation report. KG-1 now `Up`.

**Optional hardening (not required for closure)**: rag-chat's upstream-client error mapper should return **503** instead of 500 on `httpx.ConnectError` — cleaner QA semantics so a downstream up/down state isn't a generic "internal error". ~5 LOC. Defer.

---

## Finding 3 — NEW-018 (P1 confirmed)

### Root cause
**Where**: `libs/prompts/src/prompts/chat/tool_use.py:289` — the FINANCIAL_DATA per-intent addendum lacks any rule instructing the LLM to **quote the `Period` column verbatim** from tool results.

### What the tool returns vs what the LLM renders
- Tool result (verified correct via market-data direct API): `period_label="Q2 FY2026"` for AAPL `period_end=2026-03-31` (AAPL FY-end=September)
- LLM synthesis: `"Q3 FY2026"` — independently recomputed using a calendar/wrong-FY-end prior

The rag-chat tool renderer DOES pass `period_label` verbatim (`handlers/market.py:677, 717, 1461`) — so this is purely a prompt gap, not a post-processing bug.

### Hypothesis results
- **H1 (prompt gap)**: CONFIRMED
- H2 (post-process rewrites): REJECTED — handler verified correct
- H3 (label stripped from tool): REJECTED — label is in the prompt
- H4 (model bias): CONTRIBUTING — even with `Q2 FY2026` literally in prompt, the 8B-class model overrides

### One prompt gap, two failure modes
Beyond the wrong label, this bug also causes a **spurious refusal**: LLM mislabels `2025-09-30` as something other than its actual fiscal mapping ("Q4 FY2025"), then concludes "the requested period isn't in the response" and refuses. Even though `2025-09-30` IS present and IS Q4 FY2025.

### Blast radius
**~30-40% of US tickers** have non-December fiscal year ends: AAPL (Sep), MSFT (Jun), NVDA (Jan), Oracle (May), CSCO (Jul), and many financials. Every query against any of these is at risk.

### Recommended mitigation
**Option A (1 prompt block)**: add a single addendum block to `tool_use.py` FINANCIAL_DATA section:
```
FISCAL-PERIOD LABEL RULE (mandatory):
- Quote the period labels (e.g. "Q4 FY2025") EXACTLY as they appear in the
  tool result's `Period` column. Do NOT infer fiscal periods from dates.
- Note: fiscal year ends vary by issuer (Apple=Sep, Microsoft=Jun, NVIDIA=Jan).
  The tool result already accounts for this — copy the label verbatim.
```
Plus 1 regression test on AAPL Q4 FY2025. ~10 LOC total.

**Option B (egress validator, optional defence-in-depth)**: post-LLM check that every "Q[1-4] FY[year]" label in the response appears in some tool result. Banner-flag if not. Bigger surface; defer to follow-up.

### Caveat
MSFT (FY-end=June) cross-check could not be executed during INV-NEW-018 — `worldview-api-gateway-1` was in `Dead` state at the time (rebuild recreate window). Recommend a 1-question re-probe post-rebuild to confirm the FY-end-June case. The AAPL evidence + code-grep is independently conclusive.

---

## Cross-Cutting Pattern — PLAN-0104 W52 reasoning-model trap

Commit `8e67ddcc feat: PLAN-0104 W52 — platform model upgrades (DeepSeek V4 Flash + Qwen3.5)` swapped the LLM classification model without:
1. Updating the response parser to handle reasoning models (`reasoning_content` vs `content`)
2. Raising `max_tokens` to leave room for content after reasoning
3. Updating dependent docstrings (`chat_pipeline.py:210` still says Qwen3.5-0.8B)
4. Adding any regression test for the empty-content edge case

The swap broke:
- LLM-tier prompt-injection classification → 100% empty content → fail-closed → 400
- **Plausibly** LLM-tier intent classification (same setting) → keyword classifier fallback masks this in normal cases, but may explain iter-14b F-NEW-014 chat-surface misses

### BP-NEW candidate — BP-592
"Swapping an LLM classification model from a non-reasoning to a reasoning model silently breaks `message.content`-reading callers because reasoning models emit chain-of-thought into a separate field and leave content empty until the reasoning budget is exhausted."

**Detection**: any LLM client that calls a model and reads `message.content` (not `message.reasoning_content`) AND uses a low `max_tokens` (≤ 256) is vulnerable.

**Fix pattern**: read BOTH fields; OR raise max_tokens; OR explicitly disable reasoning via API (`reasoning_effort="off"` or model variant without reasoning).

### HR-NEW candidate — HR-059
"Platform-model upgrade commits (`*model upgrade*` or version-bump commits) MUST include a regression test that exercises every classifier / parser that uses the affected setting." Add to `.claude/review/heuristics/HIGH_RISK_PATTERNS.md`.

---

## Consolidated Fix Scope

Single feature branch, ~3 hours, 2 small commits + 1 ops verification:

| Wave | Fix | Effort | Severity |
|---|---|---|---|
| **1A** | NEW-016 model revert + fail-open guard + metric | ~30 LOC | **P0** — unblocks `/v1/chat` |
| **1B** | NEW-018 fiscal-label verbatim prompt addendum | ~10 LOC + 1 test | P1 |
| **1C** | NEW-017 verify KG actually up + optional 503 mapping | 5 min ops + optional 5 LOC | DEFERRED |
| **2** (verification) | Confirm intent classifier doesn't share NEW-016 silent-failure mode; if it does, generalize the fail-open to both classifiers | ~10 LOC + 1 test | derived |

**Pass gate for PLAN-0093 final PASS**:
- NEW-016 Wave 1A + 1B applied
- Re-run iter-15 chat-eval with 9 questions
- 0 HARMFUL + chat surface returns real data for all F-NEW-013/014 questions

---

## Trajectory

| Round | Verdict | Key Event |
|---|---|---|
| Iter-14b | PASS_WITH_WARNINGS | Wave 1+2+3 fixes validated; 3 NEW findings surfaced |
| **INV-iter-14b** | (investigation) | **NEW-016 = P0 W52 regression** (not P1 as audit thought); NEW-017 auto-resolved; NEW-018 confirmed prompt gap |

PLAN-0093 stays at PASS_WITH_WARNINGS. Wave 1+2+3 backend work is **VALIDATED and DONE**. Final PASS upgrade now gated on NEW-016 model revert (3-hour PR).

---

## Raw artefacts

- `/tmp/inv-NEW-016-report.md` — INV-016 full report (W52 reasoning-model regression)
- `/tmp/inv-NEW-017-report.md` — INV-017 full report (KG rebuild artefact)
- `/tmp/inv-NEW-018-report.md` — INV-018 full report (synthesis prompt gap)

**Recommended next step**: `/fix-bug` for NEW-016 (the P0 model revert) + the small NEW-018 prompt addendum. Then iter-15 QA confirms full PASS.
