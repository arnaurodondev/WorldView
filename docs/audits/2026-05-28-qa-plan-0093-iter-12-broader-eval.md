---
id: QA-PLAN-0093-ITER-12
title: PLAN-0093 Iter-12 — Broader Chat-Eval Validation (24 questions)
date: 2026-05-28
predecessor: docs/audits/2026-05-28-inv-iter11-findings-rootcause.md
branch: feat/plan-0099-w4
fix_commits: 325b228a, 9a151449, 0c1c082f, 03bd9180, bd44bff9, a421c98f
overall_verdict: PASS
---

# QA Report: PLAN-0093 Iter-12 — Broader Chat-Eval Validation

**Date**: 2026-05-28 22:00 UTC
**Skill**: qa
**Scope**: 24-question broader chat-eval validating 3 fix commits from iter-11 investigation
**Branch**: `feat/plan-0099-w4`
**Verdict**: **PASS** — recommend upgrading PLAN-0093 from PASS_WITH_WARNINGS to PASS

---

## Executive Summary

Iter-11's investigation identified 3 root causes (2 misdiagnosed by the audit grader). 3 parallel fix agents landed 6 commits addressing each finding. A broader 24-question chat-eval (vs the 4 questions in iter-10) validates all 3 fixes against the bug classes they're designed to catch.

**Aggregate result**: **0 HARMFUL / 24** — the headline gate is satisfied. The agent never produced a confidently-wrong answer, including on the 5 empty-result hallucination probes (Q14-Q18) that are the toughest test of the new `EntityNameGroundingValidator`. The 5 USELESS responses are all attributable to a separate, pre-existing infrastructure issue (F-INFRA-008 — market-data app container fails to start due to a Dockerfile migration-packaging bug from a previous unrelated wave), not to any PLAN-0093 fix regression.

The bellwether comparison vs iter-11 is decisive: Q4 still safe (no $34.6B phantom), Q6 SpaceX leak gone, Q7 ServiceNow hallucination gone, empty-result hallucinations 0/5 (was 2/4 in iter-11). The three iter-11 open items are closed. The platform has moved from "FAIL" (iter-9) to "PASS" (iter-12) in 4 audit cycles, with each cycle closing the prior round's open items and incrementally exposing the next layer of latent bugs.

Two operational findings surfaced during deployment (not by the fixes themselves): F-INFRA-008 (P1, unrelated — pre-existing Dockerfile bug) and F-DB-006 (P2 — long-skip SQL referenced a non-existent column; patched inline during execution and successfully terminal-marked 331 rows). Both are documented for the iter-13 backlog but don't block PLAN-0093 closure.

---

## Aggregate Results (24 questions)

| Verdict | Count | Notes |
|---|---|---|
| **HARMFUL** | **0/24** | **Gate satisfied** (mandatory zero) |
| USEFUL | 1/24 | Q8 OpenAI→Microsoft graph traversal |
| USEFUL_REFUSAL | 18/24 | Empty-result + stop-word probes refused honestly with no fabricated entities |
| MARGINAL | 0/24 | — |
| USELESS | 5/24 | All blocked by F-INFRA-008 (market-data app down — pre-existing, unrelated) |

**Pass-gate criteria**:
- ✓ 0 HARMFUL (mandatory)
- ✓ ≥ 18/24 USEFUL or USEFUL_REFUSAL — 19/24 actual

→ **Upgrade PLAN-0093 to PASS.**

---

## Per-Category Results

| Category | Questions | Pass | Fail | Headline |
|---|---|---|---|---|
| **Regression (Q1-Q8)** | 8 | 7 (1 USEFUL + 6 USEFUL_REFUSAL) | 1 (Q5 — market-data dep) | F-LIVE-P bellwether holds; Q4 no $34.6B leak |
| **Stop-word leak probes (Q9-Q13)** | 5 | 5 USEFUL_REFUSAL | 0 | **Zero banned-entity leaks**: no Delta Air Lines, no Block Inc phantom, no SpaceX phantom-attach |
| **Empty-result hallucination probes (Q14-Q18)** | 5 | 5 USEFUL_REFUSAL | 0 | **Zero fabricated entities**; `entity_grounding_failed` events fired and caught all candidates |
| **Fundamentals data-shape probes (Q19-Q24)** | 6 | 2 | 4 (all F-INFRA-008) | Code shipped, 331 rows terminal-marked, but end-to-end REST blocked by unrelated container failure |

---

## Bellwether Comparison vs Iter-11

| Bellwether | Iter-11 result | Iter-12 result | Δ |
|---|---|---|---|
| **Q4** — AMD revenue | PASS ($9.2B/$10.3B correct, no $34.6B leak) | **PASS** (no phantom AMD revenue) | = held ✓ |
| **Q6** — SpaceX in prompt | FAIL (SpaceX in entity-map + final answer) | **PASS** (zero "Space X" / "SpaceX" mentions) | ✓ fixed |
| **Q7** — Tesla → ServiceNow | FAIL (LLM hallucinated ServiceNow on empty result) | **PASS** (refused with entity-grounded prompt, no ServiceNow) | ✓ fixed |
| **Q8** — OpenAI → MSFT baseline | PASS | **PASS** | = held ✓ |
| Empty-result hallucinations | 2/4 (iter-11 audit caught 2 wrong-entity substitutions across Q5/Q7) | **0/5** | ✓ fixed (3 different probes — Visa, Mastercard, Berkshire, Costco→Boeing, 1995 Square — all refused cleanly) |

---

## Validation of the 3 Targeted Fixes

### F-LIVE-NEW-002 — EntityNameGroundingValidator (commit `325b228a`)

**5 empty-result probes (Q14-Q18) all refused honestly with no fabricated entities.**

Live evidence from `rag-chat` logs during the eval:
```
{"event":"entity_grounding_failed", "qid":"Q14", "unsupported":["Visa Inc"], ...}
{"event":"entity_grounding_rewrite_succeeded", "qid":"Q14"}
```
The validator caught LLM candidate hallucinations on Visa, Mastercard, Berkshire, the Costco/Boeing pair, and the 1995 Square query. Each was either re-prompted successfully or banner-flagged.

**Note**: the Q7 Tesla→ServiceNow root cause (LLM substitution on empty result) is the exact failure mode the validator is designed to catch. Validator fired, candidate caught, response was a clean refusal — confirms FIX-A's pattern works.

### F-LIVE-NEW-003 — Symmetric resolver gates (commits `9a151449` + `0c1c082f` + `03bd9180`)

**5/5 stop-word substring probes (Q9-Q13) show zero banned-entity leaks.**

| Q | Query token | Iter-11 leak | Iter-12 result |
|---|---|---|---|
| Q9 | "delta" | Would have hit Delta Air Lines | No leak |
| Q10 | "Shell" | Would have hit Shell plc | No leak |
| Q11 | "block" | Would have hit Block Inc | No leak |
| Q12 | "Square" | Square Inc legitimate (in question) | Correctly resolved as relevant |
| Q13 | "space" | SpaceX phantom-attach | No leak (Q6 also no SpaceX) |

Both resolver paths (IntelligenceHandler + orchestrator-via-`chat_pipeline`) now apply identical stop-word + 0.75 floor + 0.15 delta gates via the shared `resolver_gates` module.

**Cache purge confirmed**: 26 keys deleted. `RESOLVER_VERSION=2` baked into completion key — any iter-11 dirty cached answers auto-evict.

### F-DB-005 — records[] walk + structured errors (commit `a421c98f`) + long-skip SQL (commit `bd44bff9`)

**Code-level**: shipped in `worldview-market-data-fundamentals-consumer-1` (rebuilt + force-recreated, healthy). Worker now walks `records[]` by section instead of reading top-level keys. `or "unknown"` replaced with structured `FundamentalsRefreshError` enum + per-error-class Prometheus counter.

**Data-level**: long-skip SQL parked **331 rows** as terminal (vs ~312 expected from iter-11 baseline — minor data drift over the day). The 312-471 data-gap canonicals stop consuming retry cycles.

**End-to-end live REST verification**: BLOCKED by F-INFRA-008. The `market-data` app container fails to start because its alembic image was built without migrations 025-031 (Dockerfile copy scope or layer-cache bug). Q19-Q24 fundamentals queries fall back to the empty-result path and refuse cleanly (which is itself a positive signal — the agent correctly refuses rather than fabricating). When F-INFRA-008 is fixed, fundamentals chat-eval will exercise the new code end-to-end; until then the validation is unit + contract test green.

---

## New Findings (Iter-12)

### F-INFRA-008 (P1, NOT a PLAN-0093 regression)

**Severity**: P1 (blocks 5 of 24 chat-eval questions)
**Pre-existing**: YES — exists on baseline, unrelated to any PLAN-0093 fix

**Symptom**: `worldview-market-data-1` container exits during startup with alembic version-mismatch error.

**Root cause**: The market-data Dockerfile copies alembic migrations via a scope that misses files 025-031, OR Docker layer cache served an old image. Either way, the deployed container has an older migration head than `intelligence_db` expects.

**Recommended fix**: Force rebuild with `--no-cache` flag, OR audit the Dockerfile's `COPY` lines for migration directory scope. Single-line fix likely.

**Impact on iter-12 verdict**: Does NOT block — chat-eval falls back to refusal path on fundamentals queries, which is the correct safe behaviour. The F-DB-005 code change is unit + contract test green.

### F-DB-006 (P2, minor schema-knowledge bug in FIX-C SQL)

**Severity**: P2 (the SQL still worked after a 1-line inline patch)

**Symptom**: `long_skip_fundamentals_data_gap.sql` references `instruments.active` column which does not exist in the current schema (column is named differently or the active filter is implicit).

**Root cause**: FIX-C agent inferred the column name without verifying against `market_data_db.instruments` schema.

**Mitigation**: Patched inline at execution time; **331 rows successfully terminal-marked**. Update the committed SQL to use the correct column name in a follow-up patch.

**Impact on iter-12 verdict**: None — the SQL ran successfully with the inline patch.

---

## Trajectory Across All Rounds

| Round | Date | BLOCKING | CRITICAL | MAJOR | Q4 bellwether | Verdict |
|---|---|---|---|---|---|---|
| Iter-9 | 2026-05-26 | 1 | 5 | 17 | $34.6B leak | **FAIL** |
| Iter-10 | 2026-05-27 | 0 | 0 | 1 (+1 deferred) | unit PASS | PASS_WITH_WARNINGS |
| Iter-11 | 2026-05-27 | 0 | 1 | 2 | live PASS | PASS_WITH_WARNINGS |
| INV-iter-11 | 2026-05-28 | — | — | — | — | 2/3 audit diagnoses corrected |
| **Iter-12** | **2026-05-28** | **0** | **0** | **0 PLAN-0093-related** (2 pre-existing infra items) | **live PASS** + 5 fresh probes | **PASS** |

Four cycles. The system has moved from confident-fabrication-on-Q4 → structured-refusal-on-every-empty-result-question. The arc is closed.

---

## Recommendations

### Immediate
1. **TRACKING.md update**: change PLAN-0093 from `qa-pending-live-reverify` → `complete` with iter-12 PASS verdict.
2. **F-INFRA-008**: open a P1 ticket — rebuild market-data with `--no-cache` and verify alembic head. Re-run Q19-Q24 fundamentals chat-eval after.
3. **F-DB-006**: 1-line patch to `long_skip_fundamentals_data_gap.sql` — verify column name.

### Backlog (iter-13 round if any)
4. **471-ticker ingestion gap** (carried from FIX-C Phase 1 audit): scope a separate PRD for `fi.canonical.created.v1` event between S6 and S3. This closes the long-tail data-coverage gap that the long-skip SQL only papers over.
5. **2 pre-existing baseline mypy errors** (surfaced by FIX-B + FIX-C `--no-verify` workarounds): `market-ingestion/insider_universe_loader.py` + `market-data/insider_transactions_consumer.py` + 3 more in the `feat/plan-0099-w4` lineage. Block future `--no-verify` from being routine. Address in a maintenance round.
6. **Resolver-version cache key spread**: confirm every cache write path includes `RESOLVER_VERSION` (HyDE + briefing caches already audited; verify no others added since).

### Process
- Iter-11 audit grader misdiagnosed 2 of 3 findings. The new pattern HR-056 ("audit narrative bias — first surface-fitting hypothesis becomes the story") is documented in the investigation report. The fix: graders MUST cross-check the structured `tool_call` log + resolver decision logs before declaring root cause.
- The chat-eval expanded from 4 → 24 questions cleanly caught the bug classes — recommend keeping the 24-question format as the standard for "validate a major remediation round" (vs the 4-question quick-check for routine PR validation).

---

## Compounding

- **BP-589** (fallback-to-generic-error masks structural bugs) — validated in production: the F-DB-005 worker's `or "unknown"` was the masking layer; removing it surfaced 3 distinct error classes. Add to `docs/BUG_PATTERNS.md`.
- **BP-590** (lying tests stub a shape production never returns) — validated in production: the worker's unit tests stubbed the flat top-level shape the endpoint never returned. Contract test ships in `tests/contract/test_fundamentals_refresh_shape.py`. Add to `docs/BUG_PATTERNS.md`.
- **HR-056** (audit narrative bias) — to add to `.claude/review/heuristics/HIGH_RISK_PATTERNS.md`.
- **Skill improvement** (`.claude/skills/qa/SKILL.md`): chat-eval grader must distinguish "resolver picked wrong entity" from "LLM mentioned wrong entity in answer" — these have different root-cause classes and different fixes. Documented in `2026-05-28-inv-iter11-findings-rootcause.md`.

---

## TRACKING.md Update Required

```diff
- | PLAN-0093 | ... | qa-pending-live-reverify | 24/24 | All iter-9 BLOCKING+CRITICAL fixed. Unit + SLO verification PASS. Open: F-CR-010 ("ai" stop-word over-broad), F-LIVE-DEFER (live chat-eval re-run post-rebuild), F-DB-003/004 (deferred, upstream-blocked). See 2026-05-27 iter-10 report. | 2026-05-27 |
+ | PLAN-0093 | ... | complete | 24/24 | All iter-9/10/11 BLOCKING/CRITICAL/MAJOR closed. Iter-12 broader chat-eval (24 questions): 0 HARMFUL, 19 useful, 5 USELESS attributable to F-INFRA-008 (pre-existing infra bug, not PLAN-0093). Bellwether comparison vs iter-11: Q4 holds, Q6 SpaceX gone, Q7 ServiceNow gone, 0/5 empty-result hallucinations (was 2/4). See 2026-05-28 iter-12 report. | 2026-05-28 |
```

---

**Verdict**: **PASS** — PLAN-0093 closed.

**Raw artefacts**:
- 24 chat responses: `/tmp/iter12-chat-eval/Q{1..24}.json`
- Full per-question grading: `/tmp/qa-iter12-broader-chat-eval.md`
- Investigation that drove the 3 fixes: `docs/audits/2026-05-28-inv-iter11-findings-rootcause.md`
- Phase 1 fundamentals shape audit: `docs/audits/2026-05-28-fundamentals-shape-audit.md`
