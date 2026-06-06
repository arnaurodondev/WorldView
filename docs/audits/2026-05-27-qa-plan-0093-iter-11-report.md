---
id: QA-PLAN-0093-ITER-11
title: PLAN-0093 Iter-11 — Open-Items Closure
date: 2026-05-27
predecessor: docs/audits/2026-05-27-qa-plan-0093-iter-10-report.md
branch: feat/plan-0089-wl-2
fix_commits_iter11: 3ca1b4b5
ops_actions: F-DB-004 unblock (UPDATE entity_embedding_state + Valkey backoff purge)
overall_verdict: PASS_WITH_WARNINGS  (downgrade gate: F-LIVE-NEW-002 Tesla→ServiceNow CRITICAL; F-DB-004 unblock surfaced upstream refresh failure F-DB-005)
---

# QA Report: PLAN-0093 Iter-11 — Open-Items Closure

## Executive Summary

Iter-11 closed all four iter-10 open items: F-LIVE-DEFER resolved via live re-verification (Q4 AMD bellwether PASS — `$9.2B/$10.3B` correct, no `$34.6B` fabrication), F-CR-010 fixed in commit `3ca1b4b5` (removed `"ai"` from default stop-word list with two regression tests), F-DB-003 reclassified NOT_A_BUG (a documented 25 h timing gate in `PriceImpactLabellingWorker.min_age_hours`; first labelling eligibility ≈ 2026-05-28 20:54 UTC), and F-DB-004 unblocked via A7's recipe (2,446 rows reset + 929 backoff keys purged). The unblock itself executed cleanly, but the very next scheduler cycle drained all 811 due rows back into backoff with zero refreshes (failure breakdown: 312 `instrument_lookup_failed` + 488 `unknown` + 11 `http_404`), surfacing a new finding **F-DB-005** — the artificial freeze was masking an upstream refresh-pipeline failure. Two additional findings emerged during live chat-eval: **F-LIVE-NEW-002 (CRITICAL)** Tesla → ServiceNow Inc miscanonicalisation in CONTRADICTION pipeline and **F-LIVE-NEW-003 (MAJOR)** SpaceX still present in prompt context for AI-semi queries despite the stop-word filter. Verdict downgrades from a clean PASS to **PASS_WITH_WARNINGS**, gated on F-LIVE-NEW-002 because the Tesla→ServiceNow miscanonicalisation is strictly worse than the original F-LIVE-O it was supposed to replace, and undoes the perceived value of A5's CONTRADICTION-intent fix for the marquee Tesla case.

## Iter-10 open items — closure status

| Iter-10 ID | Status | Evidence |
|---|---|---|
| F-LIVE-DEFER | RESOLVED | Q4 chat-eval PASS; AMD Q4 datacentre `$9.2B`, total `$10.3B`; no `$34.6B` leak; A4's `period_type` fix held; NVDA figures flagged with `[unverified]` marker by agent |
| F-CR-010 | FIXED | commit `3ca1b4b5` — removed `"ai"` from default stop-word list; 2 regression tests added; 13/13 resolver tests pass; SpaceX block holds via 0.75 absolute floor |
| F-DB-003 | NOT_A_BUG | 25 h `min_age_hours` timing gate in `PriceImpactLabellingWorker`; NLP fully recovered (692 mentions, 43 FI, 30 resolved = 70%); first eligibility 2026-05-28 20:54 UTC |
| F-DB-004 | UNBLOCKED + new finding | A7 recipe executed: 2446 rows `next_refresh_at` reset, 929 backoff keys purged; **next worker cycle re-failed all 811 due rows → F-DB-005** (upstream refresh pipeline broken; freeze was a symptom not the cause) |

## NEW findings from live chat-eval

### F-LIVE-NEW-002 (CRITICAL) — Tesla → ServiceNow Inc miscanonicalisation in CONTRADICTION pipeline

- **Symptom**: Q7 Tesla CONTRADICTION query (intent correctly classified as `CONTRADICTION` thanks to A5's fix) resolves the "Tesla" subject to `ServiceNow Inc (NOW)` instead of `Tesla Inc (TSLA)`. End user sees ServiceNow-framed reasoning when asking about Tesla.
- **Root-cause hypothesis**: After A5's CONTRADICTION-intent routing, the resolver path used by the contradiction branch differs from the canonical lookup path used by the QUOTE/FINANCIALS branches. Likely picks an alphabetically- or alias-overlapping candidate (`NOW` vs `TSLA`) when the contradiction prompt does not pass the same priors (ticker hint, sector hint) that the other branches do.
- **Why it is worse than original F-LIVE-O**: F-LIVE-O surfaced a generic-intent fallback for "Tesla overpriced" — annoying but recoverable. F-LIVE-NEW-002 actively delivers WRONG-ENTITY content to the user under the marquee Tesla flow that A5 was supposed to fix; iter-10's celebrated CONTRADICTION-intent win now ships incorrect grounding.
- **Recommended fix**: (1) Audit the resolver call site inside the CONTRADICTION pipeline; pass the same `priors` payload (ticker, prior_session_entity, top_instrument_candidates) the QUOTE branch uses. (2) Add a regression test: input "Tesla is overpriced" → resolver MUST return TSLA, never NOW. (3) Add a guard: if the resolved canonical's ticker is not in the top-5 lexical candidates AND text contains a known ticker substring, reject and fall back.

### F-LIVE-NEW-003 (MAJOR) — SpaceX prompt-context contamination

- **Symptom**: AI-semi queries (Q6) still render SpaceX into the LLM prompt context even though the entity resolver correctly suppresses SpaceX downstream (NVDA / AMD / AVGO are the tools' returned entities). The user-visible reasoning paragraph references SpaceX as if it were on-topic, then the final answer pivots to NVDA/AMD/AVGO — confusing and degrades trust.
- **Root-cause hypothesis**: The stop-word filter (and the 0.75 absolute floor) is applied at the resolver layer but the prompt-context renderer (the component that builds the "evidence list" passed to the LLM) pulls its entity list from a pre-filter snapshot — typically the mention-extraction stage. Two code paths read different states of the same entity list.
- **Recommended fix**: Make the prompt-context renderer read from the *post-resolver* entity list, not the mention list. Add a regression test that the prompt for "AI semiconductor leaders" must NOT contain the string "SpaceX".

## Live chat-eval results table

| Q | Verdict | Evidence |
|---|---|---|
| Q4 (AMD datacentre revenue) | PASS | `$9.2B` Q4 datacentre, `$10.3B` total; no `$34.6B` fabrication; A4's `period_type` fix held |
| Q6 (AI semiconductor leaders) | MARGINAL | NVDA/AMD/AVGO correctly returned by tools; SpaceX still appears in prompt context — F-LIVE-NEW-003 |
| Q7 (Tesla is overpriced — contradiction) | FAIL | Intent correctly = CONTRADICTION (A5 fix held); but subject resolved to ServiceNow Inc (NOW) instead of TSLA — F-LIVE-NEW-002 |
| Q8 (OpenAI partnership → MSFT) | PASS | works end-to-end |

Tally: 2 PASS / 1 MARGINAL / 1 FAIL / **0 HARMFUL**.

## F-DB-004 unblock execution

| Stage | Metric | Value |
|---|---|---|
| Pre-state | `fundamentals_ohlcv` rows | 2446 |
| Pre-state | `embedding IS NULL` | 2446 |
| Pre-state | `next_refresh_at <= NOW()` (due_now) | 811 |
| Pre-state | `s7:fundamentals:backoff:*` keys | 929 |
| Op 1 | `UPDATE … SET next_refresh_at = NOW()` | `UPDATE 2446` |
| Op 2 | `valkey-cli DEL …` on 929 keys | 929 deleted |
| Post-unblock | due_now | 2446 (as expected) |
| Post-unblock | backoff keys | 0 |
| Worker cycle T+90s | `refreshed` | **0** |
| Worker cycle T+90s | `backoff_escalations` | **811** |
| Worker cycle T+90s | `failure_breakdown` | `instrument_lookup_failed: 312, unknown: 488, fundamentals_http_404: 11` |
| Worker cycle T+90s | new backoff keys | 1 (sentinel cluster key; per-ticker keys repopulating as worker cycles) |

**Drain status**: NOT HEALTHY. The unblock recipe itself succeeded — Postgres state and Valkey backoff were cleared exactly as A7 specified. However, the very next `fundamentals_refresh_worker` cycle failed every single due row and re-escalated 811 backoffs to 3600 s. **Zero rows were actually refreshed.** Per A7's safety guidance ("if the worker doesn't drain healthily after 5 min, stop, document, and recommend the staged approach"), I did NOT issue a second sweep.

### NEW finding F-DB-005 — fundamentals refresh pipeline upstream failure

- **Symptom**: Post-unblock, the worker fails 800/811 rows with the breakdown above. `instrument_lookup_failed: 312` indicates the worker cannot resolve 312 of its own scheduled tickers to instruments — likely a join against `instruments` / `entity_canonicals` returning empty. `unknown: 488` means the worker swallows the exception class — instrumentation gap. `http_404: 11` is the only "real" upstream failure.
- **Conclusion**: F-DB-004's freeze was a SYMPTOM. The root cause is a pipeline failure that backoff was hiding. The freeze "protected" us from seeing this.
- **Recommended next steps** (post-iter-11, do not attempt in this iter):
  1. Add explicit exception classification in the worker's `_refresh_single` so `unknown` becomes meaningful labels.
  2. Investigate the 312 `instrument_lookup_failed` — likely a missing join condition or stale ticker cache.
  3. Try the **10-ticker staged approach** (AAPL, MSFT, NVDA, AMD, GOOGL, META, AMZN, TSLA, AVGO, BRK.B) — if even these fail with `instrument_lookup_failed`, the bug is in the resolver path, not the data set.

## TRACKING.md recommended update

Convert PLAN-0093 row from:

```
status: qa-pending-live-reverify
```

to:

```
status: qa-passed-with-warnings
open_items:
  - F-LIVE-NEW-002 (CRITICAL) — Tesla→ServiceNow miscanonicalisation in CONTRADICTION pipeline
  - F-LIVE-NEW-003 (MAJOR)    — SpaceX prompt-context contamination for AI-semi queries
  - F-DB-005      (MAJOR)     — fundamentals refresh pipeline 100% failure post-unblock (was masked by F-DB-004 freeze)
closed_in_iter11:
  - F-LIVE-DEFER (RESOLVED)
  - F-CR-010     (FIXED, 3ca1b4b5)
  - F-DB-003     (NOT_A_BUG)
  - F-DB-004     (UNBLOCKED via ops; surfaced F-DB-005)
```

## Compounding

### BP-NEW candidates

- **BP-NEW-A (F-LIVE-NEW-002 class)**: Entity resolver picks alphabetically- or alias-overlapping canonical when the calling pipeline forgets to pass priors (ticker/sector hints). Pattern: same input string ("Tesla") returns different canonicals depending on which use-case calls the resolver because the priors payload differs between branches. **Mitigation**: standardise the resolver-call wrapper — every branch MUST pass the same `ResolverPriors` dataclass; assert non-empty in CI.
- **BP-NEW-B (F-LIVE-NEW-003 class)**: Stop-word / floor filters applied at one stage but not at the downstream prompt renderer. Pattern: same entity list is read from two different lifecycle stages by two consumers, one filtered and one not. **Mitigation**: name the post-filter list distinctly (`resolved_entities` vs `extracted_mentions`); lint rule that prompt renderers may only import `resolved_entities`.
- **BP-NEW-C (F-DB-005 class)**: Backoff / freeze hiding upstream failure. Pattern: a circuit-breaker style backoff escalates on every failure but the underlying exception class is `unknown`, so operators see only "frozen" never "broken". **Mitigation**: forbid bare `except Exception` in worker refresh loops; require exception-class label in `backoff_escalated` log event.

### Skill improvement

- **chat-eval grader gap**: The iter-9/iter-10 grader marked Q6 as PASS because the *tool output* contained NVDA/AMD/AVGO. Iter-11 caught F-LIVE-NEW-003 only because the human-style grader read the LLM's prompt context AND its reasoning paragraph. **Update the grader checklist**: for every chat answer, evaluate (1) tool output entities, (2) prompt-context entities, (3) reasoning-paragraph entities — each independently. A correct tool output with contaminated reasoning is MARGINAL, not PASS.
- **Live-ops gating skill**: A7's "execute then observe one worker cycle" pattern proved its worth — F-DB-005 would have been hidden if we had mass-overwritten without observing. Codify this as a `/live-ops-unblock` skill: pre-state → op → ONE cycle observe → decide.

## Verdict logic

| Gate | Required | Actual | Pass? |
|---|---|---|---|
| Iter-10 open items addressed | 4/4 | 4/4 (3 fixed, 1 unblocked + surfaced new issue) | YES |
| New BLOCKING findings | 0 | 0 | YES |
| New CRITICAL findings | 0 | **1** (F-LIVE-NEW-002) | **NO** |
| New MAJOR findings | ≤2 | 2 (F-LIVE-NEW-003, F-DB-005) | YES |
| Q4 bellwether (AMD revenue fabrication) | PASS | PASS | YES |
| HARMFUL answers in chat-eval | 0 | 0 | YES |

**Verdict: PASS_WITH_WARNINGS** — gated on F-LIVE-NEW-002.

The Tesla → ServiceNow miscanonicalisation is strictly worse than the original F-LIVE-O issue it replaced. A5's CONTRADICTION-intent fix shipped value at the intent layer but its downstream resolver call site was not audited; the marquee Tesla case now delivers WRONG-ENTITY content. This is a single-finding gate to upgrade to clean PASS in iter-12. F-LIVE-NEW-003 and F-DB-005 are MAJOR but do not gate the verdict because (3) tools still recover the correct semis and (5) is a pre-existing pipeline issue we merely surfaced (the freeze was hiding it; no regression).

## Files & artefacts

- This report: `docs/audits/2026-05-27-qa-plan-0093-iter-11-report.md`
- Predecessor: `docs/audits/2026-05-27-qa-plan-0093-iter-10-report.md`
- F-DB-004 recipe source: `docs/audits/2026-05-26-F-DB-003-004-deferred-investigation.md`
- F-CR-010 fix commit: `3ca1b4b5`
