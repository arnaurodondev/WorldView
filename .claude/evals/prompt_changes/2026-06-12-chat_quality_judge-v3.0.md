# Judge prompt breaking change — CHAT_QUALITY_JUDGE v2.0 → v3.0

> Required record per the `chat_quality_judge.py` module docstring: "Bumping
> this template changes judge verdicts and breaks longitudinal comparisons in
> the thesis evaluation — record the bump in `.claude/evals/`."

| Field | Value |
|-------|-------|
| Date | 2026-06-12 |
| Plan / task | PLAN-0110 W3 / T-W3-03 (PRD-0091 FR-7, FR-12) |
| Template | `libs/prompts/src/prompts/evaluation/chat_quality_judge.py` → `CHAT_QUALITY_JUDGE` |
| Version | `2.0` → `3.0` (BREAKING) |
| content_hash | flips automatically on body edit (computed from template body) |
| Verdict-model schema | `VERDICT_MODEL_VERSION` `1.0` → `1.1` (W3 wires the live numeric cross-check) |

## What changed

1. **DELETED the "PRESUME GROUNDED" instruction.** v2.0's grounding rubric told
   the judge that `status=ok items>=1` was strong evidence and that a matching
   quantitative claim was "PRESUMED GROUNDED → award 20-25". With no payload
   values to check against, this let a fabricated number score as grounded.

2. **Numeric grounding is now verified DETERMINISTICALLY.** A new LLM-free
   `cross_check_grounding(answer, tool_results)` in `scripts/chat_quality_judge.py`
   extracts each numeric claim from the answer and compares it (same field,
   tolerance-based, fence-skipping, scale-aware) against the W2-captured
   `grounding_sample` field values. A contradicted claim populates
   `GroundingCheck(contradicted>0, evidence_mode="verified")` and trips the
   `GROUNDING_CONTRADICTED` invariant → unconditional hard FAIL, regardless of
   the LLM's soft score. With no samples present the check falls back to
   `evidence_mode="presumed"` and NEVER fails for absence (legacy behaviour).

3. **Prompt now grades grounding qualitatively** (attribution discipline +
   scope), uses a rendered `GROUNDING SAMPLE` evidence block when present, and
   falls back to an explicit "presumed" band (saying so in feedback) when no
   sample is supplied.

The 4-dimension schema and the output keys (`feedback`, `reviewer_summary`) are
UNCHANGED from v2.0.

## Why it is breaking

The grounding sub-score distribution shifts (no more automatic 20-25 for
trace-only runs; contradictions now hard-FAIL). Longitudinal trend comparisons
across the v2.0/v3.0 boundary are NOT apples-to-apples.

## Required follow-up

- **FR-12 recalibration (PLAN-0110 W6).** v3.0 is the version under calibration;
  the human-labelled GOLD set + Cohen's κ harness must be re-run against it
  before any cross-version trend claim is made in the thesis.
- Every run artefact now stamps `judge_prompt_version`, `judge_prompt_id`,
  `judge_model_id`, and `verdict_model_version` (`_meta.json` / `_judge_summary.json`)
  so the W4 trend store can detect this discontinuity automatically.

## Data reality (2026-06-12)

W2's captured samples are TICKER-DOMINANT today (handlers render numerics into
prose, not structured fields), so the live numeric cross-check has little to
bite on yet. It is built FORWARD-COMPATIBLY and proven with synthetic samples in
the unit tests (revenue=46.7e9 sample + a "$5.4B" claim → contradiction → FAIL;
a matching claim → verified PASS; no samples → presumed, no fail).
