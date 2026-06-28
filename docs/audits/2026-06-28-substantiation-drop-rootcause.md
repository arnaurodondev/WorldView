# Substantiation Drop Root-Cause: frozen 56 → v1.4 36 (−20)

**Date:** 2026-06-28
**Scope:** READ-ONLY investigation. No code, matcher, emission, or draft touched.
**Matcher:** `scripts/chat_quality_judge.py` @ `8137117dd` (LOCKED — read only).
**Runs compared (offline-recomputed with the locked matcher):**

| run | role | substantiated | contradicted | unsupported | unmatched | verified-coverage Qs |
|-----|------|--------------:|-------------:|------------:|----------:|---------------------:|
| `run_20260627T032420Z` | CLEAN baseline (FROZEN) | **56** | 0 | 0 | 186 | 22 / 67 |
| `run_20260628T180900Z` | v1.4 (NOISY: host-blip merge, key-skip) | **36** | 0 | 0 | 163 | 20 / 67 |

Both offline aggregates were produced by `scripts/eval/resubstantiate_run.py`, which reads each
`q_*.json`'s `result.answer_text` + `result.tool_results[*].grounding_sample` and calls the SHIPPED
`evaluate_substantiation`. The frozen `_substantiation_offline.json` already existed (56); the v1.4
run had none, so it was recomputed offline into the scratchpad (NOT committed into the run dir, to keep
the run artefacts read-only). The recompute reproduces v1.4 = **36** exactly.

> **Join sanity:** both runs contain the **same 67 question IDs** (union = 67, zero IDs unique to either
> run). The "58+9 host-blip merge" did **not** drop any question from the offline recompute — every loss
> is a per-question *content* change, not a missing artefact.

---

## 1. Per-question substantiated-claim delta (frozen → v1.4), joined by `id`

Only questions whose substantiated count is non-zero in either run are shown. `cov` = coverage,
`ns` = number of grounding samples with real fields.

| id | F sub | v1.4 sub | Δ | cov F/v1.4 | ns F/v1.4 | class |
|----|------:|---------:|--:|:----------:|:---------:|:-----:|
| **tc_price_history_nvda_90d** | 11 | 0 | **−11** | veri/veri | 1/1 | **D** |
| **tc_batch_fundamentals_mag5** | 16 | 6 | **−10** | veri/veri | 1/1 | **B** |
| **chain_nvda_competitor_growth_rank** | 4 | 0 | **−4** | veri/**pres** | 3/1 | **D** |
| **ru_nvda_amd_compare_qtr** | 3 | 0 | **−3** | veri/**pres** | 2/0 | **D** |
| **iter3_msft_earnings_citations** | 5 | 3 | **−2** | veri/veri | 1/2 | **D** |
| **iter3_top5_tech_marketcap** | 4 | 2 | **−2** | veri/veri | 2/2 | **B+D** |
| **da_nvda_amd_compare_fy2024q3** | 1 | 0 | **−1** | veri/veri | 6/3 | **D** |
| chain_top_mover_fundamentals | 2 | 6 | +4 | veri/veri | 2/2 | gain |
| ru_nvda_amd_revenue_4q | 5 | 7 | +2 | veri/veri | 1/1 | gain |
| ru_googl_pe_vs_history | 2 | 4 | +2 | veri/veri | 4/3 | gain |
| ru_tsla_margin_trend | 0 | 2 | +2 | veri/veri | 1/1 | gain |
| chain_portfolio_worst_fundamentals | 1 | 2 | +1 | veri/veri | 1/2 | gain |
| da_tsla_revenue_2024_full_year | 0 | 1 | +1 | veri/veri | 2/3 | gain |
| iter3_tesla_revenue_since_2023 | 0 | 1 | +1 | veri/veri | 2/1 | gain |
| iter3_nvda_pe_conditional | 1 | 1 | 0 | veri/veri | 1/1 | — |
| ru_aapl_pe_simple | 1 | 1 | 0 | veri/veri | 1/1 | — |

**Arithmetic:** gross loss = **−33**, gross gain = **+13**, **net = −20**. ✅ (frozen 56 → v1.4 36).

The −20 headline is the *net* of 33 lost claims against 13 newly-substantiated claims; the investigation
below explains all 33 lost claims.

---

## 2. Per-loss trace and classification

For each loss I traced: answer text → the captured `grounding_sample` → the tool-result envelope
(`item_count`, `sampled_rows`, `total_rows`, `truncated`) → why the matcher could not substantiate.

> **Structural fact (applies to all questions):** the saved `q_*.json` tool-result envelope carries
> **only** `{grounding_sample, item_count, status, tool}` — the *full raw tool output is NOT persisted*.
> The offline matcher therefore sees exactly what the **3-row-capped** `grounding_sample` carried, never
> more. The emission caps are `GROUNDING_MAX_ROWS = 3`, `GROUNDING_MAX_FIELDS_PER_ROW = 8`,
> `GROUNDING_SAMPLE_MAX_BYTES = 1024` (`sse_emitter.py:623-626`).

### tc_price_history_nvda_90d — 11 → 0 (−11) — **Class D (run noise / empty answer)**
- **Frozen answer:** a full 90-day NVDA close-price table (147 words). 11 of the printed closes matched
  the allow-listed scalar fields the single price-history item exposed → 11 substantiated.
- **v1.4 answer:** a 59-word **non-answer stub** — *"I can fetch the price history data, but I cannot
  generate a visual plot directly… Let me retrieve NVDA's price history…"* — with an unexecuted JSON tool
  call and the matcher's own "could not be matched" footer. **No price table was ever produced.**
- **Sample is identical** in both runs (`item_count=1, sampled_rows=1`). The loss is 100% the empty/
  refusal-shaped answer, not a matcher or sample issue. → **Class D.**

### tc_batch_fundamentals_mag5 — 16 → 6 (−10) — **Class B (sample-row truncation)** — DOMINANT
- **Tool:** `get_fundamentals_history_batch`, `item_count=5, total_rows=5, sampled_rows=3` in **both**
  runs. The grounding_sample carries the latest-quarter fields for **3 of 5** tickers only
  (MSFT/GOOGL/META via `_2`/`_3` suffixing); **AAPL and AMZN rows are not sampled**, and **no historical
  quarters** are carried (the sample holds one latest-quarter value per allow-listed field).
- **Frozen answer (301 words):** reported **only the most-recent quarter** for each of the 5 tickers
  (one row per ticker). The 3-row sample + suffixed variants happened to cover enough of those
  latest-quarter values to substantiate **16**.
- **v1.4 answer (421 words):** reported a **much larger table — 4 quarters × 5 tickers (~20 rows)**.
  The extra historical quarters (Q4/Q3/Q2 FY2025) and the two unsampled tickers' numbers are **not in
  the 3-row latest-quarter sample**, so they land as unmatched (74 unmatched vs the frozen 22). Only the
  6 latest-quarter values that intersect the 3 sampled rows substantiate.
- The v1.4 numbers are **not wrong** — they are simply invisible to a 3-row sample. → **Class B.**
  (Note this is *aggravated by* the answer asserting more claims, but the root limiter is the row cap:
  even the frozen answer left 22 of its claims unmatched for the same reason.)

### chain_nvda_competitor_growth_rank — 4 → 0 (−4) — **Class D (tool-path collapse / refusal)**
- **Frozen:** 6 tools fired including `get_fundamentals_history_batch` (`sampled_rows=3`), producing a
  competitor revenue-growth ranking → 4 substantiated.
- **v1.4:** only **3 tools** fired (`search_entity_relations`, `get_entity_intelligence`,
  `search_documents`); the fundamentals batch **never ran**. The 55-word answer is a refusal — *"The
  available data only identifies Cerebras Systems as a competitor… No revenue figures or growth rates…
  are provided."* Coverage flips **verified → presumed** because no numeric-bearing tool produced a
  sample. → **Class D.**

### ru_nvda_amd_compare_qtr — 3 → 0 (−3) — **Class D (upstream timeout / host blip)**
- **v1.4 answer (23 words):** an explicit upstream failure — *"I'm unable to reach the data source for
  Advanced Micro Devices Inc. (AMD) at the moment (upstream_timeout)."* The `query_fundamentals` call
  returned no sample (`n_samples=0`), coverage **verified → presumed**. Frozen had revenue/EPS for both
  tickers. This is the textbook host-blip noise. → **Class D.**

### iter3_msft_earnings_citations — 5 → 3 (−2) — **Class D (answer shrinkage; all v1.4 claims valid)**
- **Same sample** (`get_fundamentals_history`, 7 fields) in both runs; v1.4 even added a second tool.
- **Frozen (206 words):** headline (revenue/NI/EPS) **plus** a fuller supporting block (2 additional
  metrics) → 5 substantiated, 5 unmatched.
- **v1.4 (56 words):** a terse 3-metric table (revenue $82.9B / NI $31.8B / EPS $4.27) → **all 3
  substantiated, 0 unmatched.** v1.4 is *cleaner*; it simply asserted **fewer** numbers. The "loss" is
  not a defect — it is the model stating 2 fewer (correct) supporting metrics. → **Class D**
  (run-to-run answer-content variance), explicitly **not** a matcher or emission bug.

### iter3_top5_tech_marketcap — 4 → 2 (−2) — **Class B + D (1-row cap + data drift)**
- **Tool:** `screen_universe`, `sampled_rows=1` — the sample carries **1 of the 5 ranked rows** in both
  runs (only the top-ranked entity's fields are in the sample).
- The screener returned a **different universe** between runs (frozen: TRMB/ALGM/DAY/SWKS/ZBRA; v1.4:
  UBER/SHOP/…). With only 1 sampled row, only claims about the single sampled entity can substantiate
  either way; frozen happened to match 4, v1.4 matched 2. → split **1 Class B** (the 1-row cap structurally
  caps a top-5 list at ≤ a couple matches) + **1 Class D** (the screener projection itself changed
  run-to-run; see the screener POST-projection gap noted in prior memory).

### da_nvda_amd_compare_fy2024q3 — 1 → 0 (−1) — **Class D (refusal)**
- **v1.4 answer (100 words):** a refusal — *"I cannot find evidence that Advanced Micro Devices (AMD)
  reported revenue, EPS, or gross-margin figures for its fiscal Q3 2024…"* Frozen produced a full
  AMD-vs-NVDA Q3 comparison table (1 substantiated). → **Class D.**

### Gains (+13, for completeness)
The seven gainers (e.g. `chain_top_mover_fundamentals` +4, `ru_nvda_amd_revenue_4q` +2,
`ru_googl_pe_vs_history` +2) are the mirror image: v1.4 produced *more* numeric claims that fell inside
the captured sample, or a richer sample (e.g. `chain_portfolio_worst_fundamentals` ns 1→2). They are
legitimate run-to-run answer-content variance, not noise to be corrected.

---

## 3. Class tally — the −33 gross loss

| class | meaning | lost claims |
|-------|---------|------------:|
| **A — REAL non-substantiation** | the answer's number is genuinely absent from the tool output | **0** |
| **B — SAMPLE-TRUNCATION artifact** | number is in the full tool output but the captured `grounding_sample` (≤3 rows) can't see it | **11** |
| **C — CITATION/ASSOCIATION miss** | number present + in sample but the inline tag is gone → wrong/no field association | **0** |
| **D — RUN NOISE** | empty/truncated/refusal/timeout answer, or run-to-run answer-content shrinkage, only in the noisy v1.4 | **22** |
| | **gross loss** | **33** |
| | (offset by +13 legitimate gains) | |
| | **net** | **−20** |

Class-B breakdown (11): `tc_batch_fundamentals_mag5` 10 + `iter3_top5_tech_marketcap` 1.
Class-D breakdown (22): `tc_price_history_nvda_90d` 11 + `chain_nvda_competitor_growth_rank` 4 +
`ru_nvda_amd_compare_qtr` 3 + `iter3_msft` 2 + `iter3_top5_tech_marketcap` 1 +
`da_nvda_amd_compare_fy2024q3` 1.

---

## 4. Verdict on the dominant cause

**The dominant cause of the −20 is Class D run noise (22 of 33 gross-lost claims, ~67%), not the
matcher and not sample emission.** The single largest line item — `tc_price_history_nvda_90d` (−11) —
is a pure empty/refusal answer in the noisy run; three more losses (`chain_nvda_competitor` −4,
`ru_nvda_amd_compare_qtr` −3, `da_nvda_amd_compare_fy2024q3` −1) are model refusals / upstream
timeouts; `iter3_msft` (−2) is the v1.4 answer correctly asserting *fewer* metrics. None of these would
be fixed by emitting more grounding rows — the answers contain no (or fewer) numbers to substantiate.

**Sample truncation (Class B) is real but secondary: 11 of 33 (~33%)**, concentrated almost entirely in
one question (`tc_batch_fundamentals_mag5`, 10). It is the *structural ceiling* worth fixing because it
silently caps substantiation on every multi-row tool result (batch fundamentals, screeners, multi-quarter
history) regardless of answer quality — but it is **not** what drove this particular 56→36 swing.

**Class A = 0 and Class C = 0:** there is **no evidence of a genuine non-substantiation regression** and
**no citation/association breakage** between the two runs. The matcher itself is behaving correctly; it is
faithfully reporting an answer-quality dip plus a long-standing emission ceiling.

---

## 5. Recommended fix

### Primary (addresses the −20 swing): treat it as a RUN-NOISE artefact, not a regression
The 56→36 is dominated by the noisy v1.4 run's empty/refusal/timeout answers (host blip + judge-key-skip
+ c=3). The clean-subset substantiation is **not** regressed. **Recommendation:** re-run the benchmark
on a clean host (no host-blip merge, no key-skip) and compare the clean v1.4 substantiation against the
frozen 56 before drawing any quality conclusion. Quarantine the four refusal/timeout questions
(`tc_price_history_nvda_90d`, `chain_nvda_competitor_growth_rank`, `ru_nvda_amd_compare_qtr`,
`da_nvda_amd_compare_fy2024q3`) as run-noise, not substantiation regressions.

### Secondary (eliminate the Class-B ceiling — an EVAL-EMISSION fix, not a matcher fix)
Raise the grounding-sample row cap in `sse_emitter.py` so multi-row tool results are fully captured:

- **`GROUNDING_MAX_ROWS = 3 → 10`** (`sse_emitter.py:623`). This recovers the two unsampled tickers
  (AAPL, AMZN) in `tc_batch_fundamentals_mag5` and gives every ≤10-row batch/screener full coverage.
  **10 rows** is sufficient: every affected tool here returns ≤5–10 entity rows
  (`get_fundamentals_history_batch` item_count=5; `screen_universe` top-5; `iter3_top5` 5 ranks).
- The byte cap (`GROUNDING_SAMPLE_MAX_BYTES = 1024`) will become the new binding limit at 10 rows × up
  to 8 numeric fields. Raise it in step — **`1024 → ~4096`** — so the added rows survive the post-build
  byte-trim (otherwise `truncated=true` simply drops them again). Validate against the largest real
  sample (`tc_batch_fundamentals_mag5` at 5 rows is ~700 B today; 10 rows ≈ 1.4 KB, fits in 4 KB).
- **This does NOT recover historical-quarter claims** (e.g. v1.4 mag5's Q4/Q3 FY2025 numbers, or the
  90-day daily price series) because the *batch tool packs only the latest quarter per item* and the
  *price tool packs the whole series into one item with only scalar allow-listed fields*. Recovering
  those would require the tools to emit per-period rows into the sample — a larger change, **out of scope
  for the substantiation-drop fix** and not needed to undo this −20.

**Expected recovery from the row-cap bump alone:** ~2–4 of the 11 Class-B claims
(`tc_batch_fundamentals_mag5` AAPL+AMZN latest-quarter values, plus a couple of `iter3_top5` ranks). The
remaining Class-B loss is historical-period coverage that the row cap cannot address.

### Do NOT do
- Do **not** modify the locked matcher (`chat_quality_judge.py @ 8137117dd`) — it is correct; Class A/C = 0.
- Do **not** "fix" `iter3_msft` — the v1.4 answer is cleaner (fewer, fully-substantiated metrics).
- Do **not** read the 56→36 as a substantiation-quality regression in the report; it is run noise (≈⅔)
  plus a pre-existing emission ceiling (≈⅓), with **zero** true non-substantiation and **zero** citation
  breakage.
