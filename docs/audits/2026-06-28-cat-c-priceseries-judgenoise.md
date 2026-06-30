# Category C audit — Price-series grounding cap (RC-4) & LLM-judge grounding-dimension non-determinism

**Date:** 2026-06-28
**Run analysed:** `tests/validation/chat_quality_benchmark/runs/run_20260628T234356Z/` (RC-FIXED, 67 questions, 2 runs each)
**Scope:** READ-ONLY investigation. Two distinct *measurement-side* defects in Category C. No code/matcher/draft touched. The locked matcher (`8137117dd`) is NOT to be edited; both recommendations land at the runner / aggregation level.

---

## Executive summary

| Issue | What floors | # questions affected | Recommended fix |
|---|---|---|---|
| **C1 — RC-4 price-series grounding cap** | A daily/weekly *series* answer cites N individual closes, but the price-history handler emits only 3 aggregate scalars (`high`/`low`/`close`) into the grounding sample, so the judge can verify almost none of the series. | **1 clean** (`tc_price_history_nvda_90d`) + 1 recurring-class sibling that fails for a *different* reason (`tc_price_history_msft_ytd_range`). Every price-history question in the run = 2; both FAIL `GROUNDING_FLOOR`. | Emit **period-spanning summary stats** (already done) **+ a capped band of per-bar rows** AND steer the agent to *summarise* long series rather than enumerate every bar. |
| **C2 — judge grounding-dim non-determinism** | A perfectly (deterministically) substantiated answer floors because the DeepSeek judge under-scores the `grounding` sub-dimension on that run. | **1 clean** (`da_tsla_revenue_2024_full_year`: 4 matched / 0 unmatched / 0 contradicted, yet grounding=10 → FLOOR) + 1 borderline (`chain_top_mover_fundamentals`: 8/7). | k-times judge grading + **modal verdict**, AND temper the `GROUNDING_FLOOR` gate with the deterministic substantiation signal (anchor, not override). |

Across the run **12 questions FAIL with `fail_reason = GROUNDING_FLOOR`**. Tiering them by the deterministic substantiation check (`matched`/`unmatched`/`contradicted`) separates the genuine grounding failures from the two measurement artefacts above (see §3).

---

## C1 — RC-4: price-series grounding cap

### The defect (traced)

Handler: `services/rag-chat/src/rag_chat/application/pipeline/handlers/market.py`, `_handle_get_price_history` → `_grounding_fields_from_bars` (lines 341–381).

The handler fetches the full OHLCV bar list and renders it into the markdown `text`, but the **structured grounding bag it emits is only 3 aggregate scalars**, computed across the WHOLE window:

```
high  = max(bar.high for bar in bars)      # window extremum
low   = min(bar.low  for bar in bars)      # window extremum
close = bars[-1].close                      # latest bar only
```

(plus `ticker`). The SSE allow-list `_GROUNDING_FIELD_ALLOWLIST["get_price_history"] = ("ticker","period","open","high","low","close","volume")` (`sse_emitter.py:746`) *supports* per-bar fields, but `_grounding_fields_from_bars` never produces them. So the grounding sample the judge receives is a single summary row — NOT the per-bar series.

This is the deliberate design from PLAN-0116 W5 / Item 3, which targeted *high/low* questions ("MSFT's high and low this year"). It is the correct shape for a **high/low** question. It is the WRONG shape for a **series / plot** question.

### Evidence — `tc_price_history_nvda_90d` ("Plot NVDA's price for the last 90 days")

- **Verdict:** FAIL, `fail_reason = GROUNDING_FLOOR`. Veto: `grounding=10 < floor 12 → forced FAIL (sum=85 would otherwise PASS)`.
- **Deterministic substantiation:** `matched=2 / unmatched=40 / contradicted=0`, coverage `verified`.
  (The team-lead's brief cited 12/66; the actual matcher numbers in this run are **2 matched / 40 unmatched** — even more unmatched, same conclusion.)
- **Judge grounding feedback (verbatim):** *"the tool returned only high=236.54, low=166.96/164.27, close=198.94 — a single summary, not a daily series. The answer fabricates a full daily price series with specific dates and close values that do not appear in the tool results. The ASCII chart is also unsupported."*
- **Answer:** a 14-row weekly close table (`2026-03-31 $174.40`, `2026-04-07 $178.10`, …) plus an ASCII chart. Each individual close is **unverifiable** because only the window high/low/last-close were exposed. The agent HAD the bars (they were in `tool_results`); the grounding *sample* hid them from the judge.

This is exactly the price-bar analog of RC-3 (the fundamentals multi-period cap): the answer quotes one figure per period, but only the latest/aggregate figures are substantiated.

### `tc_price_history_msft_ytd_range` is NOT the same failure (important nuance)

- **Verdict:** FAIL, `GROUNDING_FLOOR`, grounding=0.
- The tool DID emit `high=489.7, low=356.28` — the summary-stat design **worked** for this high/low question.
- The judge floored it because the **answer claimed the data lacked high/low values** — an *answer-side* defect (the agent under-trusted its own tool result), not a tool-emission gap. Judge: *"Tool results contain high=489.7 and low=356.28, but answer claims data does not contain high/low values — contradicts available data."*

**Takeaway:** the summary-stat approach is correct and sufficient for *high/low/range* questions (MSFT proves it). It is insufficient only for *series/plot* questions (NVDA). So the fix must ADD per-bar coverage WITHOUT removing the summary stats.

### Recommended fix (C1) — a mix, in priority order

**(A) Keep the period-spanning summary stats (already emitted).** They correctly substantiate high/low/range/last-close claims and cover the most common price questions. Do not remove them.

**(B) Add a capped band of per-bar grounding rows.** Emit up to `K` evenly-sampled bars as suffixed grounding fields (`close`, `close_2`, … and `period`/`date` so a claim like "$215.20 on 2026-05-12" can match a specific bar). A 90-bar daily series cannot be fully covered under the per-row field cap (`GROUNDING_MAX_FIELDS_PER_ROW=14`, `GROUNDING_MAX_ROWS=10`), so a row cap will NOT fully cover a long series — accept partial coverage and **down-sample** (first, last, and evenly-spaced interior bars) so the judge can verify a representative subset and the endpoints. Couple with `truncated=true` so the judge knows coverage is partial rather than treating absent bars as fabricated.

**(C) Steer the agent to summarise long series instead of enumerating every bar (highest-leverage, lowest-cost).** The root behavioural problem is that the agent renders a full per-date table from a series it cannot fully cite. For a "plot / last 90 days" request the *correct* answer is: report the window high/low/range/last-close/start-close/N-bars/trend direction (all summary-substantiated) and describe the trajectory — NOT a fabricated daily table. This is a system-prompt / tool-description steer ("for a multi-week price series, summarise the trajectory and cite window stats; do not enumerate individual daily closes you cannot verify"), and it makes (A) sufficient on its own for most series questions.

**Recommendation:** ship **(A)+(C)** first — they fully resolve the NVDA-class failure with no matcher change and minimal risk. Add **(B)** only if questions that genuinely need specific-bar citations (e.g. "what did NVDA close at on May 12?") show up; for those, a small down-sampled per-bar band plus `truncated=true` is the right shape. This is a **recurring class**: every price-history *series* question is exposed; both price-history questions in this run floored.

---

## C2 — LLM-judge grounding-dimension non-determinism

### The defect (quantified)

The `GROUNDING_FLOOR` gate fires purely on the LLM judge's `grounding` sub-dimension:
`scripts/chat_quality_judge.py:1355-1357` — `if grounding_score < GROUNDING_VETO_FLOOR (12): GROUNDING_FLOOR fires`.
This single stochastic number, on a single judge call per run, can flip a verdict that the **deterministic** substantiation check (the locked matcher) says is well-grounded.

The runner re-runs the **agent** `max_runs_per_q` times (`run_chat_quality_benchmark.py:2079`), but each agent run gets exactly **one** judge call. There is **no k-times judge grading with a modal verdict** on a given answer today — judge variance is unmitigated.

### Cross-reference: deterministic substantiation vs LLM grounding-dim (all 12 floored questions)

| Question | grounding_dim | matched / unmatched / contra | coverage | tier |
|---|---|---|---|---|
| `da_tsla_revenue_2024_full_year` | 10 | **4 / 0 / 0** | verified | **STRONG — clean C2** |
| `chain_top_mover_fundamentals` | 10 | **8 / 7 / 0** | verified | strong-ish (matched > unmatched) |
| `tc_price_history_nvda_90d` | 10 | 2 / 40 / 0 | verified | weak (this is C1, not C2) |
| `iter3_top5_tech_marketcap` | 0 | 3 / 9 / 0 | verified | weak |
| `da_nvda_amd_compare_fy2024q3` | 5 | 1 / 3 / 0 | verified | weak |
| `da_apple_revenue_fy2024q4_precision` | 0 | 1 / 5 / 0 | verified | weak |
| `da_aapl_pe_dec2024` | 0 | 1 / 1 / 0 | verified | weak |
| `ru_ai_semi_screener` | 5 | 0 / 1 / 0 | verified | weak |
| `tc_price_history_msft_ytd_range` | 0 | 0 / 0 / 0 | verified | weak (answer-side) |
| `agg_q1_apple_competitors` | 5 | 0 / 0 / 0 | presumed | no samples |
| `chain_apple_suppliers_high_margin` | 10 | 0 / 0 / 0 | presumed | no samples |
| `iter3_apple_competitors_spanish` | 0 | 0 / 0 / 0 | presumed | no samples |

**Clean C2 case — `da_tsla_revenue_2024_full_year`:** deterministic substantiation is **4 matched / 0 unmatched / 0 contradicted** (perfect), yet the LLM scored grounding=10 → floored → FAIL. The judge's stated reason was NOT a value mismatch — all four quarter revenues matched the sample — but a **quarter-labelling reversal** ("answer labels Q2 as 25.50B and Q4 as 25.71B, reversing the actual quarter ordering"). So the floor here is *partly* signal (a real semantic labelling error the value-matcher can't see) and *partly* a 25-point sub-dimension reacting to a labelling nit. This is the canonical borderline: **the numbers are right; an outlier-low grounding score floored an otherwise-PASS answer.**

**How often does a strongly-substantiated answer still floor?** With a strict definition (verified coverage, ≥2 matched, 0 contradicted, unmatched ≤ matched): **2 of 12** floored questions (`da_tsla_revenue_2024_full_year` 4/0, `chain_top_mover_fundamentals` 8/7). The remaining 10 are genuine grounding problems — real unmatched figures (the C1 NVDA case, the precision/compare cases) or no samples at all — and should NOT be rescued.

### Recommended mitigation (C2) — two complementary levers, runner/aggregation only

**(1) k-times judge grading + modal verdict** (consistent with the earlier κ work, which recommended exactly this). Call the judge `k` times (e.g. k=3, temp held low) on the SAME answer and take the **modal verdict** (and median grounding sub-score). A single outlier grounding=10 among {22, 20, 10} no longer floors. This directly attacks the non-determinism and is the cleaner, more general fix. Cost: k× judge calls — the judge is the cheap DeepSeek model per the budget guidance, so this is affordable.

**(2) Anchor the floor partly on the deterministic substantiation result** (`scripts/chat_quality_judge.py:1355` — `substantiation_check` is ALREADY in scope at that gate). When the deterministic signal is **strong** (`coverage == "verified"` AND `substantiated ≥ T` AND `contradicted == 0` AND `unmatched ≤ substantiated`), **temper** the floor: either raise the effective grounding score to the floor, or require BOTH `grounding < 12` AND a *non-strong* deterministic signal for `GROUNDING_FLOOR` to fire. This makes the gate refuse to call "fabrication" on an answer the matcher proved is substantiated. Keep it conservative — `contradicted > 0` must still floor regardless (a real contradiction is fabrication), so this only rescues the *outlier-low LLM-score-on-clean-answer* case.

**Recommendation:** implement **both**. (1) reduces the variance at the source; (2) is a deterministic backstop so a strongly-substantiated answer can never be floored by a single judge call. (2) alone would have rescued `da_tsla_revenue_2024_full_year` and `chain_top_mover_fundamentals` in this run (2 questions). Neither change touches the locked matcher — (1) is in the runner's judge-call loop, (2) is in `run_invariant_gates` where the substantiation check is already a parameter.

---

## Affected-question tally (final message)

- **C1 (price-series cap):** 1 clean (`tc_price_history_nvda_90d`); the run's only other price-history question (`tc_price_history_msft_ytd_range`) floors for an answer-side reason, not the cap. Recurring class = every price-*series* question.
- **C2 (judge grounding-dim noise):** 1 clean (`da_tsla_revenue_2024_full_year`) + 1 borderline (`chain_top_mover_fundamentals`); the deterministic-substantiation floor-temper (mitigation 2) rescues both.
- **Context:** 12 of 67 questions FAIL `GROUNDING_FLOOR`; the other 9 are genuine grounding gaps (real unmatched figures or no samples) and must keep failing.
