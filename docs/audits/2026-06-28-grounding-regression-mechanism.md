# Grounding Regression Mechanism — FINAL-67 Post-Fix Run

**Date:** 2026-06-28
**Type:** READ-ONLY attribution audit (no code/matcher/draft/eval touched)
**Author:** investigation agent
**Runs compared:**
- PRE-FIX baseline: `run_20260627T032420Z`
- POST-FIX: `run_20260628T022335Z` (ships synthesis prompt 1.3 + tool_use 1.10 to rag-chat)

---

## Verdict (one line)

**Prime cause: the synthesis-prompt directives shipped in C1 (`chat_synthesis_system` 1.2→1.3, "TRANSCRIBE, DO NOT COMPUTE", commit `bc05eab24`) — compounded by the C3 "TRUST YOUR TOOL RESULTS" block already in 1.2 (`7adea4c6f`) — over-corrected the answer LLM into terse, defensive, refusal-prone answers. The answers SHRANK and HEDGED; they did not start emitting wrong numbers. The C1 #2 fabricated-series gate (the team's prime suspect) is EXONERATED — it fired ZERO times.**

Confidence: **HIGH** for "the regression is answer-shrinkage/refusal, not validator/gate mutation, and the prime mover is the synthesis prompt." MEDIUM on the C1-vs-C3 split *within* the prompt (both directives live in the same `chat_synthesis_system` template; only a one-directive-at-a-time bisect separates them — see the confirming test below).

---

## The regression (team-lead numbers, reconfirmed from `_substantiation_offline.json`)

| Metric | PRE `…032420Z` | POST `…022335Z` | Δ |
|---|---|---|---|
| GROUNDING_FLOOR fails | 7 | 16 | **+9 (worse)** |
| substantiated claims (`substantiated_n`) | 56 | 47 | **−9 (worse)** |
| grounding dim | 19.21 | 17.46 | **−1.75 (worse)** |
| `unsupported_n` | **0** | **0** | unchanged |
| `contradicted_n` | 0 | 1 | +1 |
| `unmatched_n` (total claim-evidence pairs examined) | 186 | 151 | **−35** |
| trajectory / phantom-citations | — | — | improved (per brief) |

The two unchanged-at-zero lines are the load-bearing observation: **`unsupported_n` stayed 0**. If the regression were caused by the answer LLM emitting *wrong / fabricated* numbers, `unsupported_n` (and `contradicted_n`) would have climbed. They did not. Instead `unmatched_n` — the count of claim-evidence pairs the offline substantiator had to examine — **fell by 35**. Fewer claims were *made*, so fewer were substantiated. **This is answer shrinkage, not fabrication.**

---

## Mechanism walk-through of the suspects

### Suspect 1 — C1 #2 fabricated-series gate → number-free fallback — **EXONERATED**

Code: `services/rag-chat/src/rag_chat/application/services/numeric_grounding.py::detect_fabricated_series` + the route at `chat_orchestrator.py:4294` → `_build_second_turn_fallback_answer` (`chat_orchestrator.py:1489`).

The hypothesis was sound a priori: when `detect_fabricated_series` fires, the orchestrator replaces the answer with `_build_second_turn_fallback_answer`, a **number-free, content-poor** string ("…the language model could not produce a final summary right now…"), and returns `passed=False`. That would simultaneously raise GROUNDING_FLOOR and drop substantiated claims — matching both symptoms.

But it did not happen:

1. **Live container metric — fired 0 times.** `worldview-rag-chat-1` logs, both full history and the run window (`--since 2026-06-28T02:20Z --until 04:10Z`):
   - `numeric_grounding_fabricated_series_replaced` / `rag_grounding_validation_total{result="failed_fabricated_series"}` → **0**.
2. **Fallback signature absent from every q-file.** `grep "could not produce a final summary"` across all 67 POST answers → **0 hits**.
3. **The gate is heavily conditioned and rarely satisfiable** (`numeric_grounding.py:1626-1706`): requires a Markdown table with ≥3 number-bearing rows whose **first cell is a period label**, AND more such rows than total tool numeric values, AND >60% of row numbers unmatched. The one question it was built for (`da_apple_revenue_fy2024q4_precision`) regressed via a *different* path — see below.

> The gate is a no-op in this run. It is not the cause.

### Suspect 3 — C1 #1 numeric pin (`pin_numbers_to_tool_values`) — **EXONERATED (it HELPED)**

Code: `numeric_grounding.py:1497`, call site `chat_orchestrator.py:4245`.

- Live metric `numeric_values_pinned_to_tool_exact` fired **9 times** in-window (10 lifetime). Working as designed.
- By construction the pin only rewrites a number that is **within 1% (`_PIN_DRIFT_TOL`)** of an entity-scoped same-kind tool value to that exact value, in the same format (`numeric_grounding.py:1570-1602`). It can only **improve** grounding; it cannot delete content, shorten an answer, or trigger a refusal. The `unsupported_n: 0→0` line is consistent with the pin doing its job.

### Suspect 2 — C1 synthesis prompt 1.3 "transcribe-don't-compute" (+ C3 1.2 "trust your results") — **PRIME CAUSE**

Diff: `bc05eab24` adds the `TRANSCRIBE, DO NOT COMPUTE` block to `libs/prompts/src/prompts/chat/synthesis.py` and bumps `chat_synthesis_system` 1.2→1.3. The block is almost entirely **prohibition** language: "Do NOT infer, extrapolate, annualise, or build a time series…", "Do NOT compute a derived figure…", and "say so plainly ('…was not in the retrieved data') instead of supplying a substitute number."

The before/after answers show the model obeying these prohibitions to a fault — it stopped *answering* and started *withholding*:

| Question | Δscore | PRE len | POST len | What changed |
|---|---|---|---|---|
| `iter3_msft_earnings_citations` | **−95** | 1314 | 182 | Full grounded earnings table (Rev/NI/EPS, cited) → one-sentence **wrongful refusal** "I'm unable to locate…". Judge: *"Answer claims 'no available data' but tool_results show status=ok items=1 … Claim contradicts tool_results."* |
| `da_apple_revenue_fy2024q4_precision` | **−75** | 1360 | 210 | Headline + 3-row supporting table + context → one figure + "Note: some figures … could not be matched". |
| `iter3_tesla_revenue_since_2023` | **−67** | 1642 | 539 | Headline + analysis stripped to a bare table, narrative dropped. |
| `chain_macro_event_market_reaction` | **−50** | 492 | 172 | Cited `get_economic_calendar row 0` answer → "I wasn't able to locate any … No data was found." |
| `chain_nvda_competitor_growth_rank` | **−38** | 906 | 259 | Shrunk >50%, new hedging. |
| `tc_portfolio_dividend_yielders` | **−35** | 709 | 264 | Shrunk >50%. |

Aggregate over the 26 regressions: **6 answers shrank >50%**, **6 picked up new refusal/hedge language not present pre-fix**, and the worst three regressors (−95, −75, −67) are all answer-shrinkage. **0** are the fab-series fallback.

Critically, `iter3_msft`'s refusal is **NOT** any deterministic gate's canned text — it does not match `_EMPTY_POOL_REFUSAL` (`chat_orchestrator.py:959`), and the in-window `empty_pool_refused` events fired only on `get_earnings_calendar`/`search_claims`/`search_events`, never on `query_fundamentals` (which returned `items=1` for MSFT). The refusal is **LLM-authored prose** — the synthesis model itself decided to refuse data it was handed. That is precisely the failure the C3 "TRUST YOUR TOOL RESULTS" block was meant to prevent and the C1 "say 'not in the retrieved data'" escape hatch now actively encourages.

---

## Why this is the prime cause and not a coincidence

1. **Direction of the validator metrics rules out the gates/validator.** `unsupported_n` and `contradicted_n` stayed at/near zero. The numeric-grounding validator did not start rejecting more numbers; the answers simply contained fewer numbers/claims. A validator- or gate-driven regression would have moved `unsupported_n` or shown the canned-refusal/fallback strings — neither happened.
2. **The mutation surface that changed is the prompt.** The deterministic C1 #1/#2 code paths are observable (metrics) and account for 9 benign pin edits and 0 fab-series replacements. The only other thing this batch changed in the answer-generation path is the synthesis system prompt (1.2→1.3). The answers changed in exactly the way the new prohibitions/escape-hatch would predict (shorter, more "not in the retrieved data", wrongful refusals on present data).
3. **The flagship question regressed via the prompt, not its gate.** `da_apple_revenue_fy2024q4_precision` — the very case `detect_fabricated_series` was written for — went 75→0 because the model self-truncated to a single figure + disclaimer, while the gate never fired.

---

## Recommended fix (low-risk, prompt-first)

**Primary:** Soften the C1 1.3 prohibitions so they stop suppressing legitimate transcription and synthesis. Keep the genuinely valuable rule ("copy figures digit-for-digit; don't round") and **remove/narrow the over-broad "don't compute / don't build a series / prefer 'not in the retrieved data'" language** that is causing the model to withhold data it was handed. Concretely, in `libs/prompts/src/prompts/chat/synthesis.py`:
- Keep: "Copy each number EXACTLY as the tool returned it."
- Narrow: scope the "do NOT build a time series" line to *periods the tool did not return* (it already says this, but the model reads the surrounding prohibitions as "say less"); add an explicit counter-instruction: **"When the tools DID return the figure, you MUST report it in full — do not refuse, hedge, or shorten an answer you can ground."**
- This re-balances against the C3 "trust your results" block rather than fighting it.

**Why not just revert 1.3→1.2:** 1.2 still carries C3, and the regression is the *interaction* of "trust your results" with the new "prefer 'not in the retrieved data'" escape hatch. A clean revert of 1.3 is the safe fallback if the softening does not recover the score, but the targeted softening preserves the digit-for-digit win (which is the part that actually helped — `unsupported_n` stayed 0).

**Do NOT** touch the C1 #1 pin or C1 #2 gate — both are exonerated and the pin is helping.

---

## The single bisect test that would confirm (for a follow-up agent)

**Re-run the 67-question benchmark with the synthesis prompt reverted to 1.2 (i.e. C1 prompt-block removed) but C1 #1 pin and C1 #2 gate left in place.**

Expected if this attribution is correct:
- `substantiated_n` recovers toward ~56 and GROUNDING_FLOOR fails fall back toward ~7;
- `iter3_msft_earnings_citations`, `da_apple_revenue_fy2024q4_precision`, `iter3_tesla_revenue_since_2023` re-expand to full grounded tables and recover their scores;
- `numeric_grounding_fabricated_series_replaced` stays 0 and `numeric_values_pinned_to_tool_exact` keeps firing (~9) — proving the gates were never the cause.

A second, tie-breaking run with **1.3 minus only the C3 "TRUST" block** (or 1.3 minus only the new C1 block) would split the C1-vs-C3 contribution, which is the one thing this audit cannot fully separate from artefacts alone.

---

## Evidence index (verbatim sources)

- Validator/gate code: `services/rag-chat/src/rag_chat/application/services/numeric_grounding.py` — `detect_fabricated_series` (L1647), `pin_numbers_to_tool_values` (L1497).
- Orchestrator routing: `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` — pin L4245, fab-series route L4294, `_build_second_turn_fallback_answer` L1489, `_EMPTY_POOL_REFUSAL` L959.
- Prompt change: commit `bc05eab24` on `libs/prompts/src/prompts/chat/synthesis.py` (+ CHANGELEG entry 1.3).
- Substantiation deltas: `tests/validation/chat_quality_benchmark/runs/{run_20260627T032420Z,run_20260628T022335Z}/_substantiation_offline.json`.
- Regression list + per-question answers: same runs, `_regressions.json` and `q_*.json`.
- Live firing counts: `docker logs worldview-rag-chat-1` (window 2026-06-28T02:20–04:10Z): `fabricated_series_replaced`=0, `numeric_values_pinned_to_tool_exact`=9, `empty_pool_refused`=4 (none on `query_fundamentals`).
