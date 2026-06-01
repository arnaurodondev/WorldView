---
id: QA-PLAN-0093-ITER-13
title: PLAN-0093 Iter-13 — Follow-up Fixes Validation (F-INFRA-008 + F-DB-006 + mypy)
date: 2026-05-31
predecessor: docs/audits/2026-05-28-qa-plan-0093-iter-12-broader-eval.md
branch: feat/plan-0099-w4
fix_commits: 87106e53, a041966f, (operational for F-INFRA-008)
overall_verdict: PASS_WITH_WARNINGS
---

# QA Report: PLAN-0093 Iter-13 — Follow-up Fixes Validation

**Date**: 2026-05-31 23:55 UTC
**Skill**: qa
**Scope**: 3 follow-up fixes from iter-12 backlog (F-INFRA-008, F-DB-006, 5 baseline mypy errors) + 12-question focused chat-eval
**Branch**: `feat/plan-0099-w4`
**Verdict**: **PASS_WITH_WARNINGS** (PASS upgrade gated on F-NEW-015 timeout regression)

---

## Executive Summary

Three parallel fix agents addressed iter-12's P1/P2 follow-up backlog: F-INFRA-008 (market-data container's stuck alembic head), F-DB-006 (bogus `WHERE active = true` in long-skip SQL), and the 5 baseline mypy errors that had forced 3 recent commits to use `--no-verify`. All 3 fixes delivered cleanly. The mypy fix's value was proven in real-time when the cherry-pick of FIX-2 went through the full pre-commit hook chain (ruff + ruff-format + mypy + avro + merge-markers) without `--no-verify` — first such clean commit since iter-11.

A focused 12-question chat-eval validated the fixes and confirmed iter-12's bellwethers still hold. **0 HARMFUL / 12** (mandatory gate met). Fundamentals queries (Q19-Q24) now reach the worker path without HTTP 5xx (was 0/6 in iter-12 — all blocked by the down market-data container); a verifiable NVDA P/E of `32.4x` was returned and confirmed against `market_data_db.fundamental_metrics` (`32.383`). The Q4 bellwether held and the entity-grounding validator (shipped in iter-12) **also caught a new $57B AMD revenue hallucination this round** — earning its keep beyond the original $34.6B case it was built for.

The PASS_WITH_WARNINGS rather than full PASS is driven by one regression (F-NEW-015: Q6 AI-semiconductor screener went from iter-12 PASS to iter-13 90s timeout) and 3 new low-severity findings. F-INFRA-009 (the `net_value_usd` column-mismatch error FIX-1 had flagged but not fixed) showed zero log occurrences across the QA window — downgraded to "not reproducing" pending re-probe after the next insider batch.

---

## Aggregate Results (12 questions)

| Verdict | Count | Detail |
|---|---|---|
| **HARMFUL** | **0/12** | **Gate satisfied** |
| USEFUL | 2/12 | Q20 NVDA P/E (cross-verified vs DB), Q24 TSLA revenue trend (numbers correct, labels off-by-one — see F-NEW-013) |
| USEFUL_REFUSAL | 6/12 | Q19/Q22/Q23 fundamentals (data not ingested → honest refusal), QA1 prompt-injection detected, QB1 + QB3 (bellwethers reaffirmed) |
| PASS | 2/12 | F-INFRA-008 verification queries answered correctly |
| USELESS | 1/12 | Q21 "Apple market cap" — see F-NEW-014 |
| TIMEOUT | 1/12 | QB2 — see F-NEW-015 |

---

## Three Fix Outcomes

### F-INFRA-008 — Market-data container ✓ CLOSED

- `alembic_version` went 025 → **031** after migrate sidecar re-run
- `worldview-market-data-1` healthy
- `worldview-market-data-fundamentals-consumer-1` healthy
- 6 fundamentals chat queries (Q19-Q24) all completed without HTTP 5xx (iter-12: 0/6 due to container failure)
- Not a Dockerfile bug — the COPY scope was correct; failure was a stale sidecar from before the image rebuild that needed manual re-run. Follow-up recommendation (compose-level `restart: on-failure:5` on migrate services) carried over to iter-14 backlog.

### F-DB-006 — Long-skip SQL ✓ CLOSED

- Commit `87106e53` (cherry-picked from worktree `4820d901`)
- Bogus `WHERE active = true` predicate dropped (the column doesn't exist; intent was always "ticker absent from instruments table at all")
- Re-run is idempotent: 331 rows parked on first run, `UPDATE 0` on re-run
- Cherry-pick required a one-file conflict resolution (took FIX-2's corrected version over main's bogus version) — resolved cleanly

### FIX-3 — 5 baseline mypy errors ✓ CLOSED

- Commit `a041966f`
- `mypy libs services` → **Success: no issues found in 1,351 source files** (was 5 errors)
- Per-error fixes:
  - `rollup_insider_90d.py:96` — `# type: ignore[attr-defined]` on `Result.rowcount`
  - `libs/messaging/.../processed_events_cleanup.py:127` — same fix
  - `nlp-pipeline/.../entity_refresh_consumer.py:172` — same fix (note: nlp-pipeline, not knowledge-graph as my prompt listed)
  - `market-ingestion/scripts/backfill_fundamentals.py:584` — broadened to `[import-not-found,import-untyped]` for asyncpg
  - `content-ingestion/.../upload_tenant_document.py:81` — pdfminer comment moved up one line (mypy attributes to `from X import (`, not the imported name)
- **Real-time validation**: the FIX-2 cherry-pick (immediately after FIX-3 landed) committed cleanly through the full pre-commit chain without `--no-verify`. Mission accomplished — no longer forced to skip hooks.

---

## Bellwether Comparison vs Iter-12

| Bellwether | Iter-12 | Iter-13 | Δ |
|---|---|---|---|
| **QB1** Q4 AMD revenue | PASS (no $34.6B) | **PASS** (also blocked NEW $57B hallucination) | ✓ held, +1 new catch |
| **QB2** Q6 SpaceX | PASS | **TIMEOUT** (90s) | ✗ regressed → F-NEW-015 |
| **QB3** Q7 Tesla → ServiceNow | PASS (refused cleanly) | **PASS** | ✓ held |
| Empty-result hallucinations | 0/5 | 0/3 (subset) | ✓ held |
| Fundamentals queries (Q19-Q24) | 0/6 USEFUL (blocked) | 2 USEFUL + 3 REFUSAL + 1 USELESS | ↑ from blocked → reachable |

**Key gain — entity grounding earns its keep beyond the original $34.6B case**: the validator caught a fresh $57B AMD revenue hallucination on QB1 this round. The pattern shipped to handle one historical bug now defends against new ones automatically.

---

## Cross-Verification of Cited Numbers

For the 2 USEFUL responses, numbers were cross-checked against `market_data_db.fundamental_metrics`:

| Q | Cited number | DB value | Match |
|---|---|---|---|
| Q20 NVDA P/E | `32.4x` | `32.383` | ✓ within 0.06% (numeric tolerance OK) |
| Q24 TSLA Q-by-Q revenue | All values | All match DB | ✓ values correct |

**Quarter-label mis-mapping on Q24** (F-NEW-013): the values are correct but labels are off by one (calendar quarter vs reported fiscal quarter). The data is right; the synthesis labels are wrong. Low severity — analyst can re-derive.

---

## New Findings

### F-NEW-013 (LOW) — Q24 TSLA quarter-label mis-mapping
- Symptom: returned revenue values match DB, but quarter labels (e.g. "Q1 2026") are off by one when compared to TSLA's reported fiscal quarter
- Likely cause: synthesis layer joins by `period_end` calendar date without translating to TSLA's fiscal-quarter convention
- Severity LOW — values right, labels wrong; analyst-correctable
- Recommend: open as a follow-up data-presentation task

### F-NEW-014 (LOW) — Q21 "Apple market cap" intent miss
- Symptom: "What is Apple's market capitalization?" classified as `GENERAL` intent → no autonomous fundamentals tool call → USELESS response
- Likely cause: intent classifier's `FINANCIAL_DATA` regex doesn't catch "market capitalization" phrasing
- Severity LOW — narrow phrasing miss; "What is Apple's market cap?" would likely work
- Recommend: extend intent-pattern keywords; cheap fix

### F-NEW-015 (MEDIUM) — QB2 AI-semiconductor screener 90s timeout
- Symptom: Q6 (iter-12 PASS) regressed to 90-second timeout this round
- **The single PASS_WITH_WARNINGS gate** — full PASS verdict requires this resolved
- Likely cause: the resolver-gate refactor (FIX-B from iter-12) or one of the PLAN-0103 W15-W20 commits that landed between iter-12 and iter-13 introduced a latency regression on screener queries
- Recommend: spawn `/investigate` to isolate — diff the chat orchestrator + screener handler between iter-12 commit and iter-13 HEAD; focus on hot loops that could blow latency

### F-NEW-016 (INFO) — Prompt-injection guard masks entity-grounding diagnostic
- Symptom: QA1 ("Why did Apple acquire Twitter last quarter?") was caught by `[PROMPT_INJECTION]` guard rather than reaching the entity-grounding validator
- Not a bug — defensive layer working as intended
- Note: the test was designed to probe entity grounding; this confirms entity grounding is the **second line of defence**, not the first. Both layers active = good. Just a test-design observation.
- Recommend: future entity-grounding probes should use less-adversarial framings (e.g. "Apple's most recent major acquisition was Twitter, right?") so they pass the prompt-injection filter and exercise the grounding layer

### F-INFRA-009 — Not reproducing
- FIX-1 had flagged that `worldview-market-data-fundamentals-consumer-1` was logging `insider_rollup_error` with `column "net_value_usd" does not exist`
- Iter-13 probe: **zero occurrences** in fundamentals-consumer logs across the past hour AND the QA window
- Status downgraded to "not reproducing"
- Recommend: re-probe after the next insider-data batch lands; if it returns, escalate

---

## Trajectory Across All Rounds

| Round | Date | Verdict | Headline |
|---|---|---|---|
| Iter-9 | 2026-05-26 | FAIL | $34.6B AMD fabrication caught live |
| Iter-10 | 2026-05-27 | PASS_WITH_WARNINGS | 8 fix commits, unit-test PASS |
| Iter-11 | 2026-05-27 | PASS_WITH_WARNINGS | 3 new findings (Tesla, SpaceX, worker 0/811) |
| INV-iter-11 | 2026-05-28 | (investigation) | 2/3 audit diagnoses corrected |
| Iter-12 | 2026-05-28 | **PASS** | 6 fix commits, 24-Q broader eval, 0 HARMFUL |
| **Iter-13** | **2026-05-31** | **PASS_WITH_WARNINGS** | 3 follow-up fixes; 0 HARMFUL; 1 latency regression |

PLAN-0093 itself stays CLOSED. Iter-13 is post-closure cleanup; the warnings are quality-of-life items, not gating bugs.

---

## Recommendations

### Immediate
1. **F-NEW-015 (latency regression)**: spawn `/investigate` to bisect between iter-12 commit and iter-13 HEAD. Suspect FIX-B's resolver-gate insertion in `chat_pipeline.resolve_entities` OR one of the PLAN-0103 W15-W20 hot-path changes. If isolated quickly, patch + verify; if not, document the bisect range for the next round.

### Short-term (low-severity backlog)
2. **F-NEW-013**: 1-line fix to TSLA quarter-label synthesis (calendar→fiscal mapping)
3. **F-NEW-014**: extend `FINANCIAL_DATA` intent regex to include "market capitalization" + similar phrasings

### Backlog (carried from iter-12 + iter-13)
4. **F-INFRA-009**: re-probe after next insider batch
5. **Compose hardening**: `restart: on-failure:5` on migrate sidecars
6. **Data backfill**: AMD/MSFT/GOOG historical fundamentals (so Q19/Q22/Q23 can flip from REFUSAL to USEFUL)
7. **471-ticker ingestion gap**: separate PRD for `fi.canonical.created.v1` S6→S3 event

---

## Compounding

- **No new BP/HR candidates** this round — all 3 fixes were narrow operational/syntactic; no new structural failure patterns to catalogue.
- **Skill improvement (`/qa`)**: probe queries designed to test a specific defensive layer should use framings that pass upstream defensive layers (else you can't reach the layer you're trying to validate). F-NEW-016 surfaced this.
- **Process learning**: the "FIX-3's value proven in-line" outcome (FIX-2 cherry-pick committing cleanly through full hook chain immediately after FIX-3 landed) is the kind of small validation that's worth documenting. Hooks-are-clean is a **first-class platform property**.

---

## TRACKING.md Update

PLAN-0093 remains `complete` from iter-12. Iter-13 is a maintenance pass; no TRACKING change needed.

---

**Verdict**: **PASS_WITH_WARNINGS** — full PASS pending F-NEW-015 (Q6 timeout regression) resolution.

**Raw artefacts**:
- 12 chat responses: `/tmp/iter13-chat-eval/Q{19..24,B1..B3,A1..A3}.json`
- Full per-question grading: `/tmp/qa-iter13-followup-fixes.md`
- FIX-1 operational fix log: not captured (was a `docker compose run --rm market-data-migrate` invocation)
- FIX-2 commit: `87106e53`
- FIX-3 commit: `a041966f`
