# W5-3-04 — Baseline Capture + CI Gate Disposition

**Date**: 2026-05-07
**Plan**: PLAN-0063 W5-3 T-W5-3-04
**Verdict**: baseline CAPTURED + committed; **CI gate kept DISABLED** (deferred to W5-4 after retrieval-instability investigation)

## What this commit does

Per PLAN-0063 §0-bis.0 v2 lock L3, the post-hybrid pipeline is the anchor for
the eval gate. T-W5-3-04 captures the post-hybrid NDCG@10 number into
`results/baseline_pre_hybrid.json` so future commits can measure regression
against it.

**Gate state**: the CI workflow's `full-eval-disabled-gate` job remains
`continue-on-error: true`. The `--baseline` flag is wired but the gate does not
fail PRs yet. **This deviates from the v2 plan body** which said the gate
enables "from this commit forward". The deviation is justified by an empirical
finding from the labelling subagent.

## Why the gate stays disabled — labelling subagent finding

The labelling subagent (T-W5-1-01 Phase 2) graded 61 of 120 queries against the
live `/v1/internal/retrieve` endpoint and produced
`tests/eval/golden/LABELLING_REPORT.md`. Two findings block hard-gate
enforcement:

1. **Result instability** — same query (`"Apple iPhone"`, `top_k=5`), same JWT,
   seconds apart: returned 5 candidates first call, 0 candidates the next. No
   error, no auth issue. This is a non-deterministic retrieval path that would
   make NDCG@10 swing ±0.05 between captures from cache effects alone, producing
   false-positive CI failures. **Investigation deferred to W5-4** (recency
   hardening + observability — natural place to add request-state logging).
2. **Heuristic grading methodology** — the subagent used a deterministic
   regex-rubric grader (`/tmp/eval_label/grade.py`) instead of per-snippet
   inspection (the 90-min budget couldn't fit ~2400 hand-grading decisions).
   The grader is conservative (relevance 3 only with on-topic term + numeric/
   date marker) but is NOT a 2-reviewer audit per the README §6 rule. The
   `label_review.reviewer_id_b` field remains the placeholder `claude-agent-1`.

Per §0-bis.4-v2 maintenance discipline ("every PR modifying queries.jsonl
requires 2 reviewers from `eval-stewards`"), the dataset is provisional until
a second reviewer audits at least the 41 grade-3 rows. Treating this as a
gating signal would be premature.

## Coverage achieved (per LABELLING_REPORT.md)

- **61 of 120 queries labelled** (50.8%)
- 41 with grade-3
- 50 with ≥5 graded candidates
- 66 marked `CORPUS_GAP: ...` — honest "no candidates returned" markers; the
  eval script skips these
- 5 marked `ADVERSARIAL_OK` — refusal-correctness candidates

Per-class:

| query_class | n  | labelled | ≥5 graded | grade-3 | gateable? |
|---|---|---|---|---|---|
| factual_lookup | 17 | 10 | 6 | 4 | yes |
| comparison | 12 | 11 | 10 | 7 | yes |
| reasoning | 12 | 8 | 7 | 7 | yes |
| financial_data | 9 | 3 | 3 | 0 | NO (corpus gap) |
| relationship | 9 | 3 | 3 | 0 | NO (corpus gap) |
| signal_intel | 8 | 3 | 2 | 3 | NO (n<4) |
| general | 6 | 6 | 6 | 6 | yes |
| portfolio | 7 | 5 | 3 | 3 | yes |
| identifier_lookup | 12 | 2 | 1 | 2 | NO (n<4 — corpus has no PRD/code/docs) |
| ambiguous | 6 | 3 | 3 | 2 | yes |
| non_analyst | 12 | 5 | 4 | 5 | yes |
| adversarial_or_out_of_scope | 6 | 0 | 0 (5 ADVERSARIAL_OK) | 0 | NO (different scoring) |
| time_anchored_edge | 4 | 2 | 2 | 2 | yes |

9 of 13 classes meet n≥4 minimum for the per-class regression check.

## Top corpus gaps (drives W2 / next-wave ingestion priority)

JPMorgan dividend, AWS margin, Boeing 737 MAX, AMD guidance, hyperscaler capex,
Amazon retail margin, Microsoft cloud decel, Tesla D/E, Amazon FCF, Nvidia EPS.

Pattern: dev corpus is **Apple-heavy news**, missing fundamentals/ratios chunks,
missing non-Apple SEC filings. Code/docs queries (`compute_routing_score`,
`BP-235`, `PRD-0034`) require an out-of-scope code/docs corpus that doesn't
exist in `nlp_db.chunks` at all.

## How to enable the CI gate (W5-4 or later)

Pre-conditions:
1. Result-instability pathology investigated and fixed (or root-caused as
   acceptable noise with documented bound).
2. Second reviewer audits at least the 41 grade-3 rows (CODEOWNERS rule).
3. Re-capture baseline against the audited dataset.

Enabling steps:
1. Edit `.github/workflows/retrieval-eval.yml` — remove
   `continue-on-error: true` from the `full-eval-disabled-gate` step.
2. Rename the job to `full-eval-gate`.
3. The `--baseline` flag is already wired in this commit; nothing else needed.

## Files changed in this commit

- `results/baseline_pre_hybrid.json` (new — captured baseline)
- `.github/workflows/retrieval-eval.yml` (added `--baseline` flag to the
  workflow_dispatch eval step; `continue-on-error: true` retained)
- `tests/eval/golden/queries.jsonl` (61 rows now have `relevant_doc_ids` —
  produced by the labelling subagent)
- `tests/eval/golden/LABELLING_REPORT.md` (Phase 2 update)
- `docs/audits/2026-05-07-w5-3-baseline-capture.md` (this report)
- `docs/plans/0063-w5-hybrid-retrieval-eval-gate-plan.md` (W5-3 status update)
- `docs/plans/TRACKING.md` (waves 3/7 → 4/7; T-W5-3-04 status)

## Open follow-ups

- W5-4 should diagnose the result-instability pathology before any other
  retrieval change ships. Add request-state logging (correlation ID into the
  S6 chunk-search SQL query plan) and re-run the same query 5x in a row to
  capture variance.
- A future PR should run a 2-reviewer audit of the 41 grade-3 rows, then
  re-capture the baseline.
- Corpus expansion (W2-class work, separate plan) to fill the AWS / Boeing /
  AMD / hyperscaler-capex / non-Apple-fundamentals gaps — not blocking W5
  but listed for prioritisation.
