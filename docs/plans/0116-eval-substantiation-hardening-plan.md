---
id: PLAN-0116
title: Evaluation-Framework Substantiation Hardening — make the in-run numeric verifier trustworthy
status: draft
created: 2026-06-26
prd: none (CIKM-2026 proposal-driven; follows the 2026-06-26 subset diagnosis)
---

# PLAN-0116 — Evaluation-Framework Substantiation Hardening

> **Goal**: make in-run numeric **substantiation** produce a trustworthy rate, and stop the
> grounding **contradiction veto** from false-failing correct answers — validated on the
> 10-question strategic subset, then the full 67. EVERY change is **evaluation instrumentation**
> (eval-only / flag-gated / the offline judge); none touches the model or the production answer path.

## Why (root cause, from the 2026-06-26 subset run `run_20260626T185654Z`)
The numeric-claim **matcher** is under-built and the grounding-sample **instrumentation** is
incomplete, so even after the prior fixes: substantiation reads `substantiated=0` on `verified`
coverage, the veto false-fires `GROUNDING_CONTRADICTED`, and tools routed to `query_fundamentals`
stay `presumed`. Concretely observed:
- A **"34 % growth" claim was associated to the `revenue` *absolute-value* field** → false contradiction.
- Multi-period answers contradict because nearest-match picks ONE period, ignoring the `_2/_3` set.
- `evaluate_substantiation` and `cross_check_grounding` use **divergent** claim extraction (veto found 9, substantiation 0 on the same answer).
- `query_fundamentals` computes values but isn't on the emit allow-list → no sample.
- `grounding_sample` is dropped from the in-memory `ToolResult` for compare/batch shapes → judge sees nothing.

## Wave 1 — Unify + TYPE the numeric matcher  [the core, highest leverage]
**Files**: `scripts/chat_quality_judge.py`
- **W1.1 One shared pipeline.** Extract → type → associate → compare, used by BOTH
  `evaluate_substantiation` and `cross_check_grounding` (kill the divergence). One claim list, one association.
- **W1.2 Claim typing.** Classify each numeric claim as `{absolute_value, percentage, ratio, count/structural}`
  from format + context words (`$`, scale suffix, `%`, "growth", "margin", "YoY"). Associate a claim ONLY to a
  sampled field of a **compatible kind** — a `34 %` growth claim can never match the `revenue` absolute field
  (the exact observed false contradiction). Percentage claims map to margin/growth fields (ratio↔%), not levels.
- **W1.3 Multi-period SET matching.** When a field has period-suffixed variants (`revenue`, `revenue_2`, …),
  a claim is `substantiated` if it matches ANY value in that set within tolerance — not just the single nearest.
  Removes the multi-period false-contradictions (da_msft 18, chain_top_mover 14, ru_googl 7, ru_nvda 5).
- **W1.4 Scale/unit robustness.** B/M/K/T, commas, `$`, `%`↔ratio (`0.586`↔`58.6 %`), and the existing
  `_is_structural_number` guard retained.
- **Tests**: the W4.1 real-case golden corpus + unit edge cases. ALL existing matcher tests stay green (R19).

## Wave 2 — Complete grounding-sample emission
**Files**: `services/rag-chat/.../pipeline/sse_emitter.py` (`_GROUNDING_FIELD_ALLOWLIST`), `handlers/market.py`
- **W2.1** Add `query_fundamentals` to the allow-list with its metric fields; ensure its handler populates
  `grounding_fields` (routed-but-uninstrumented in 3/10 subset Qs).
- **W2.2** Audit ALL value-bearing tools (`get_quote`, `get_market_movers`, `compare_entities`,
  the fundamentals family) for allow-list coverage + `grounding_fields` population; log a one-line coverage table.
- **W2.3** Confirm multi-period emission shape (suffixed keys) is consistent with W1.3 set-matching.
- Stay behind `CHAT_EVAL_GROUNDING_SAMPLES` (flag-OFF byte-identical in prod). Unit tests per tool.

## Wave 3 — Robust harness→judge plumbing
**Files**: `tests/validation/chat_eval/harness.py`, `scripts/run_chat_quality_benchmark.py` (~:1886)
- **W3.1** Preserve `grounding_sample` onto the in-memory `ToolResult` for ALL tool-result shapes
  (single / compare / batch) so `JudgeInput(tool_results=…)` always carries it (today dropped for compare/batch
  → substantiation_check absent on ru_nvda, empty on da_msft).
- **W3.2** Harness test: every parsed `tool_result` carrying a sample round-trips into `JudgeInput` and reaches
  `evaluate_substantiation` (assert coverage=`verified`, not `presumed`, for a fundamentals fixture).

## Wave 4 — Real-case test corpus + validation gate
- **W4.1 Golden numeric-substantiation corpus** built from the ACTUAL subset answers (da_msft,
  ru_nvda_amd_revenue_4q, ru_googl_pe, ru_tsla_margin, ru_aapl_pe): each `(answer snippet, sample fields,
  expected substantiated/contradicted/unsupported)`. This is the regression net **against reality**, not synthetic.
- **W4.2 Re-run the 10-Q subset** (`--ids …`, rebuild rag-chat first). ACCEPTANCE:
  financial Qs `coverage=verified` with `substantiated>0`; **zero** false `GROUNDING_CONTRADICTED` on a
  correct multi-period answer; `query_fundamentals` Qs no longer `presumed`.
- **W4.3 Full 67-run** → the trustworthy substantiation rate for the draft.

## Acceptance / "done" bar
1. W4.1 golden corpus passes (the `34%→revenue` and multi-period cases classified correctly).
2. 10-Q subset clean per W4.2.
3. Full-67 substantiation rate stable + defensible (no n=2 / artifact denominators).

## Sequence & risk
W1 → (W2 ∥ W3) → W4. **W1 (claim typing + multi-period set-matching) is the genuinely hard,
research-adjacent piece** — a robust numeric-claim verifier. We validate against the REAL failing
cases (W4.1) before trusting any rate. Est. ~1–1.5 days. **Fallback**: if W1 can't clear the
acceptance bar, ship the honest-journey v6 (already drafted; it needs no rate).

## Draft impact
On success, v6's substantiation section flips from "machinery works, rate pending" to a **real cited
rate** — while we keep the journey (the gaps we fixed) as the methodological contribution. Best of both:
a working number AND the honest account of how hard honest measurement was.

## [VERIFY] at implementation
- Exact current names/locations in `chat_quality_judge.py`: `evaluate_substantiation`, `cross_check_grounding`,
  `_nearest_field`, `_collect_grounding_fields`, `_values_within_tolerance`, `_is_structural_number`, `_FIELD_ALIASES`.
- The `query_fundamentals` handler signature + whether it already populates `grounding_fields`.
- The compare/batch `ToolResult` shape in the SSE parser that drops the sample.
