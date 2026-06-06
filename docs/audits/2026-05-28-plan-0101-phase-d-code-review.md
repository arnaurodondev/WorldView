# PLAN-0101 Phase D — Adversarial Code Review

**Branch:** `feat/plan-0099-w4`
**Commits reviewed:** `ca9e4dc7` (BP-610), `91a363a0` (W3/BP-612/613), `0405ddaf` (PLAN-0100 W1)
**Date:** 2026-05-28
**Reviewer mode:** read-only, adversarial

## Verdict: **CONDITIONAL PASS**

Ship is acceptable, but **two P1 issues** in the W3 commit must be flagged for PLAN-0102 because they silently regress in known cases (numeric-grounding rewrite truncation and double-recording on partial-recovery success). One P2 and several P3s noted. The W1 commit (`0405ddaf`) remains clean on re-check.

Test sweep (run from CWD per request):

| Service | Result | Notes |
| --- | --- | --- |
| `services/market-data tests/unit` | **756 passed, 1 failed** | The lone failure (`test_app_lifespan`) is an env issue — `ModuleNotFoundError: sentry_sdk` — predates this branch and is unrelated to BP-610. |
| `tests/validation/chat_eval/{test_grading,test_harness_latency}` | **57 passed** | All BP-612/BP-613/TPS tests green. |
| `services/rag-chat tests/unit` (with the requested ignores) | **1118 passed, 185 failed, 14 skipped** | All 185 failures are `ModuleNotFoundError: No module named 'tools'` from `tool_registry_builder.py:11` — the requested ignores cover the source file but not every test module that imports the builder. This is a pre-existing collection problem, **NOT** caused by the commits under review. Reproducible on `HEAD~3`. |

Non-test failures therefore have no bearing on this review.

---

## 1. BP-610 — `instrument_repo.py:229-254` flush correctness

`await self._session.flush()` after the UPDATE is the right pattern. Confirmed by grep: every other write method in `instrument_repo.py` (`update_flags`, `update_metadata`) does NOT flush — they rely on UoW commit. So the new convention is "freshness-columns flush eagerly", which the docstring correctly pins.

**Subtle point (S2 — info-only):** the flush truly persists *within* the open transaction; it does **not** issue a COMMIT. If the surrounding UoW later raises and rolls back, the touch is correctly rolled back too. That is desired — the bug was buffered-but-never-sent because autoflush was deferred past a try/except in the consumer, not because of rollback. ✅

**S1 (P3) — missing regression in `tests/unit`.** The new `test_touch_fundamentals_ingest_at_persists` lives in `tests/integration/` and requires Postgres. The commit description quotes "757 unit tests pass" but the unit sweep run above shows **756 passed + 1 unrelated failure**. No assertion that a *subsequent* exception still leaves the touch persisted within the transaction. Recommend a unit-level regression that mocks `session.execute` + asserts the call order `(UPDATE, flush)` so a future refactor cannot drop the flush silently.

**S2 (P3) — container rebuild gap acknowledged.** Commit message documents the stale-image root cause (`worldview-market-data-fundamentals-consumer-1` had zero references to `touch_fundamentals_ingest_at`, image predated `8450666b`). The rebuild was performed but end-to-end verification was deferred. Acceptable per "FundamentalsRefreshWorker (PLAN-0099 W2-T02, default ON) will exercise the path organically", but PLAN-0102 should add a one-shot live check.

**File:** `services/market-data/src/market_data/infrastructure/db/repositories/instrument_repo.py:229-254` — severity **P3**.

---

## 2. BP-612 grader — honest-quote window + directional guard

`grading.py:630 _HONEST_QUOTE_WINDOW_REVENUE = 150`. Calibrated to the verbatim Q4 v1 fixture where the disclaimer ("do not appear in the retrieved results for AMD") sat ~95 chars past the NVDA `$81.6B` — the chosen 150 covers it without being unbounded.

**Counter-tests verified:** `test_assertive_amd_above_cap_is_still_flagged` confirms a plain "AMD reported revenue of $20.5B" still trips the cap; `test_reversed_order_ticker_after_number_is_not_flagged` pins the directional guard. The asymmetry is intentional and tested.

**S1 (P3) — multi-sentence directional risk.** `_ticker_precedes_amount` uses a tight 80-char prefix; the example in the docstring ("AMD revenue was $9.2B. NVIDIA reported $81.6B.") is correctly blocked, but a multi-sentence answer where the ticker sits in sentence N-1 (>80 chars away) and the dollar amount in sentence N will now FALSE-NEGATIVE. This is the correct trade-off for the false-positive case in scope, but the design note in the docstring should be expanded so future maintainers don't expand the window naively. Recommend explicit pinned test for the cross-sentence case.

**S2 (P3) — missing plural / inflected refusal markers.** `do not appear` was added. Other natural plurals to consider: `did not appear`, `not appearing in`, `does not include`, `are not present`, `was not reported`. The current set is dominated by present-tense forms; an LLM that drifts into past tense in a refusal sentence ("did not appear in the retrieved results") will be charged a false positive. **Recommend a `_REFUSAL_QUOTE_MARKERS` expansion in PLAN-0102** with a regex fallback (`r"(does|do|did|are|was|were) not (appear|reported|present)"`) so we don't keep growing the literal tuple.

**S3 — false-positive regression scan.** Walked the 4 new BP-612 tests; the assertive-flag test and reversed-order test directly counter the over-relaxation risk. No assertive-claim path now incorrectly passes.

**File:** `tests/validation/chat_eval/grading.py:630-728` — severity **P3**.

---

## 3. BP-613 — answer-assembly fallback (**P1 — highest concern**)

`harness.py:580-598`. The fix picks `joined_tokens` when `final_answer` is empty/missing OR shorter than the token stream:

```python
if final_answer is None or not final_answer:
    answer_text = joined_tokens
elif len(joined_tokens) > len(final_answer):
    answer_text = joined_tokens
else:
    answer_text = final_answer
```

**S1 (P1) — the longer-wins rule fights PLAN-0093 numeric-grounding rewrite.** The rag-chat post-validation pipeline (PLAN-0093 G-3 / numeric grounding) **intentionally re-emits a SHORTER `final_answer`** when it strips ungrounded numeric spans from the streamed draft. After this fix the harness silently REVERTS to the longer (pre-rewrite) `joined_tokens`, presenting the chat-eval grader with the un-validated text. The grading rubric then runs `NumericGroundingValidator` on the version the orchestrator already *rejected* — exactly the failure mode PLAN-0093 G-3 was built to prevent.

The reproducer pattern is plausible: any question where the model streams a number, the validator catches it, and the rewrite drops the number → the new harness keeps the pre-strip version with the hallucinated number. Aggregate-score HARMFUL counts could climb on the next nightly.

**Recommended fix for PLAN-0102:**
```python
if not final_answer:
    answer_text = joined_tokens
elif len(final_answer) < 0.10 * max(1, len(joined_tokens)):
    answer_text = joined_tokens  # truncation safety net only
else:
    answer_text = final_answer  # trust the post-validation rewrite
```
i.e. prefer `final_answer` unless it's empty or *catastrophically* shorter (<10% of tokens). This still catches the Q8 empty-final-answer case while honoring intentional rewrites.

**S2 (P3) — no test pins the rewrite case.** `test_full_final_answer_still_wins_when_present` only tests the case where `final_answer` is LONGER (or near-equal length) than tokens. A test where `final_answer` is, say, 60% the length of `joined_tokens` (validator stripped a paragraph) would currently FAIL on the recommended fix — making it the load-bearing regression.

**File:** `tests/validation/chat_eval/harness.py:590-598` — severity **P1**.

---

## 4. TPS streaming — formula + threshold

`harness.py:_compute_tps_streaming` (lines 717-744). NaN handling is correct: missing dict, missing key, zero/negative ms, `output_tokens<=0` all collapse to NaN; the aggregate gate drops NaN before percentile math, so error-paths cannot poison the median.

**S1 (P2) — fast-synthesis upper-bound noise.** No upper-bound sanity check. A 60-token answer synthesized in 200 ms reports `300 tok/s` — plausible for a small model, implausible for DeepSeek-R1-Distill-32B. With p50 = 20 tok/s target, a single 300 tok/s outlier shifts the p50 mildly but does **NOT** cause a gate failure (false PASS not false FAIL). Recommend logging `tps_streaming > 100` as anomaly so calibration drift gets surfaced.

**S2 (P3) — 20 tok/s calibration rationale.** Commit message says "calibrated for DeepInfra DeepSeek-R1-Distill-32B baseline (~25-40 tok/s observed)" but no audit cites the run that produced the histogram. Acceptable for now; PLAN-0102 should write `tps_streaming_p50` + p90 stats from a real run to confirm headroom.

**S3 — NaN-skip policy.** Older backends (no `phase_timings_ms`) → that question's TPS is NaN → dropped from the aggregate. This means a partial rollback would silently shrink the sample size; if >50% of questions go NaN the median is meaningless. Recommend the aggregate gate emit a structured warning when `nan_count / total > 0.5`.

**File:** `tests/validation/chat_eval/harness.py:713-744` — severity **P2**.

---

## 5. Backend phase recording — `llm_synthesis_streaming` (**P1**)

`chat_orchestrator.py:1687` (failure branch) and `1696` (success branch).

**S1 (P1) — double-recording on partial-recovered path.** `phase_timings.py:50-52` shows `PhaseTimings.record` ACCUMULATES (sums) repeated entries:
```python
self._data[name] = self._data.get(name, 0.0) + float(elapsed_ms)
```
The orchestrator's partial-recovery path at line 1676-1682 keeps `full_text` when `len >= 80` AND does NOT return; the control falls through to line 1696 where `phases.record("llm_synthesis_streaming", ...)` fires again with the SAME `_synthesis_t0` start time. The two recordings are therefore *near-identical* (same start) and the bucket holds **roughly 2x the true wall-clock** on every partial-recovery success.

Wait — re-reading: line 1687 only fires in the `else` branch (when `_partial_len < 80` → error return). When `_partial_len >= 80` we fall through without recording at 1687, hit 1696, record once. So the two branches ARE exclusive. ✅ No double-record.

**However (P1 still):** the diff requires both branches to keep that invariant — anyone adding a new partial-recovery branch (e.g. medium-length partial: 40-80 chars handled differently) WILL introduce double-recording silently. The TPS denominator then halves → `tps_streaming` doubles → false PASS on the gate.

**Recommended fix for PLAN-0102:** convert the accumulator semantics for `llm_synthesis_streaming` to *replace* OR introduce a `record_once` method; alternatively guard `_synthesis_t0` with a "already recorded" sentinel and assert in the exception branch. The phase-name itself is now public contract per the rag-chat doc update — any backend behavior change is a contract break.

**Files:** `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:1687,1696`; `services/rag-chat/src/rag_chat/application/observability/phase_timings.py:50-52` — severity **P1** (latent, not currently triggered).

---

## 6. Cherry-pick hygiene (`ca9e4dc7`)

Diff confirms BP-610 entry in `docs/BUG_PATTERNS.md` survived the conflict resolution intact (line 630, multi-line entry verified — full root-cause prose, ORM tag, market-data scope, regression-test path, all present). No file path drift. The cherry-pick added only:
- `instrument_repo.py` (+15 lines)
- `test_repositories.py` (+39 lines)
- `BUG_PATTERNS.md` (+1 line table row)
- `services/market-data/.claude-context.md` (1-line note)
- `docs/services/market-data.md` (10-line section)

No collateral damage. ✅

---

## 7. Cross-bug interaction (BP-612 + BP-613, both in 91a363a0)

Both touch the chat-eval surface. BP-612 lives in `grading.py`, BP-613 in `harness.py`. **Region collision risk: zero** — different files, different module-level constants. The interaction concern is downstream: BP-613 reverting to `joined_tokens` (issue 3 above) means BP-612's grader now sees the un-validated text, but BP-612's logic is text-substance-agnostic (regex-based), so the only collision is the P1 already filed in §3.

---

## 8. Re-check of 0405ddaf (W1 PLAN-0100)

Already QA-reviewed; this re-check looked for late-surfaced interactions with the cherry-pick + grader changes. Findings:

- `news_query.py` JSONB-fallback UNION leg unchanged by either later commit.
- `chat_orchestrator.py` entity-drift guards live at separate line ranges (collect/validate helpers, ~lines 700-800) from the synthesis recorder (1687/1696). No collision.
- `_check_entity_grounding` (1717-1719) refusal path bypasses both lines 1687 and 1696 — the refusal short-circuit emits without calling `phase`. This is correct (no synthesis wall-clock to record), but means `tps_streaming` will be NaN for any entity-grounding refusal. ✅ Aligns with the NaN-skip policy.

No new issue. W1 remains clean.

---

## 9. New / weird

**S1 (P3) — public-contract phase name as string literal.** `llm_synthesis_streaming` is now load-bearing in both backend and harness. Recommend extracting to a `chat_eval_contracts.py` (or similar) module so a typo in either side is a compile error rather than a silent NaN. Currently the rag-chat `.claude-context.md` pitfall is the only enforcement; ToolSearch / grep would let an agent rename it.

**S2 (P3) — `phase_timings_ms` serialised by `to_json_dict`.** `ChatRunResult.to_json_dict` now includes the raw dict. Some phases (`tool_execution`, `llm_tool_planning`) carry zero PII risk; this is fine. No secret leakage observed.

**S3 — backfill script BP-606.** `scripts/backfill_entity_mentions_from_chunks_jsonb.py` (in 0405ddaf) is marked dry-run-default + idempotent. No interaction with the touch-fundamentals UoW.

---

## 10. PLAN-0102 punch list

| ID | Severity | File / Area | Fix |
| --- | --- | --- | --- |
| D-1 | **P1** | `harness.py:590-598` | Replace "longer wins" with "prefer `final_answer` unless empty or <10% of tokens" — protects PLAN-0093 numeric-grounding rewrites. Add fixture-test where `final_answer` is 60% of `joined_tokens` and validator-stripped. |
| D-2 | **P1 (latent)** | `chat_orchestrator.py:1687,1696` + `phase_timings.py:50` | Add `record_once` semantics (or sentinel-guard `_synthesis_t0`) so a future partial-recovery branch cannot double-record `llm_synthesis_streaming`. |
| D-3 | P2 | `harness.py:_compute_tps_streaming` | Log `tps_streaming > 100` as anomaly; emit warning when NaN-share > 50% across a run. |
| D-4 | P3 | `grading.py:_REFUSAL_QUOTE_MARKERS` | Replace literal tuple with a regex covering tense/number variants (`(does|do|did|are|was) not (appear|present|reported)`). |
| D-5 | P3 | `instrument_repo.py:229-254` | Add a unit-level test mocking `session.execute` + asserting call order; tighten guard so future writers cannot drop the flush silently. |
| D-6 | P3 | `chat_eval contract` | Extract `llm_synthesis_streaming` literal to a shared constants module. |
| D-7 | P3 | `grading._ticker_precedes_amount` | Pin a cross-sentence test (ticker > 80 chars before number) as expected false-negative so the design intent is enforced. |
| D-8 | P3 | live verification | One-shot end-to-end check that `instruments.last_fundamentals_ingest_at` populates after `FundamentalsRefreshWorker` cycle (currently deferred). |

---

**End of review.** All findings derive from the source under review; no code modified.
