# Grounding-Floor Failure Root-Cause Audit

**Date:** 2026-06-28
**Scope:** READ-ONLY investigation. Root-cause every `GROUNDING_FLOOR` veto in the v1.4 finding-run; cross-check against the frozen clean baseline; classify each.
**Matcher / judge:** locked `8137117dd`; `chat_quality_judge@3.0`; `GROUNDING_VETO_FLOOR = 12`.
**Runs:**
- **v1.4 (NOISY):** `tests/validation/chat_quality_benchmark/runs/run_20260628T180900Z` — 15 grounding-floor fails (host-blip merge, judge-key-skip, c=3 concurrency).
- **CLEAN frozen baseline:** `tests/validation/chat_quality_benchmark/runs/run_20260627T032420Z` — 7 grounding-floor fails.
- The clean v1.4 subset `run_20260628T065453Z` **does not exist** on disk; class-(e) determination uses the frozen baseline as the clean reference.

---

## How the grounding veto works (so the classes make sense)

The judge **never sees the full tool payload.** `scripts/chat_quality_judge.py` builds its grounding evidence solely from each tool-result's `grounding_sample` — a bounded, allow-listed value sample emitted by `services/rag-chat/.../sse_emitter.py::build_grounding_sample`. Hard caps:

- `GROUNDING_MAX_ROWS = 3` — at most the **first 3 rows** of a multi-row result are sampled.
- `GROUNDING_MAX_FIELDS_PER_ROW = 8`, `GROUNDING_VALUE_MAX_CHARS = 32`, `GROUNDING_SAMPLE_MAX_BYTES = 1024`.
- Repeated fields across rows get suffixed keys (`revenue`, `revenue_2`, `revenue_3`). Multi-period items pack up to `_GROUNDING_MAX_PERIODS = 4` periods into one item's `grounding_fields`.

The judge floors the answer when its LLM grounding sub-score `< 12`. Because the judge sees only the sample, a number that is correct-but-un-sampled **can** read as "fabricated." This is the eval-artifact risk (class b). The investigation's job is to separate that from genuine fabrication (class a).

---

## Per-question findings (15 v1.4 grounding-floor fails)

| q-id | Trace summary | Root cause | Class | Fix direction |
|---|---|---|---|---|
| **tc_batch_fundamentals_mag5** | `get_fundamentals_history_batch(periods=4, 5 tickers)` → 5 items, **1 latest quarter each** (`total_rows=5`). Answer renders a **4-quarter** table per ticker. | Tool returns 1 row/ticker; the 3 extra "quarters" per ticker are invented. AAPL/AMZN single values un-sampled (rows 4–5 > `MAX_ROWS=3`) but the per-quarter breakdown is fabricated regardless. Frozen run produced the *correct* 1-row-per-ticker answer (grounding=20 PASS) → answer non-determinism. | **a** (+ partial b for AAPL/AMZN single rows) | Stop fabricating extra quarters when tool returns 1 period; state "latest quarter only." Secondary: raise `GROUNDING_MAX_ROWS` so rows 4–5 are visible. |
| **ru_nvda_amd_revenue_4q** | `get_fundamentals_history_batch(periods=4, [NVDA,AMD])` → 2 items, **1 quarter each** (`total_rows=2`, `result_preview` = 2 rows). Answer invents `$68.1B/$57.0B/$46.7B` (NVDA) + named quarters. | Tool returned **no historical quarters**; the 4-quarter trajectory is pure invention. Reproduced in **frozen** (grounding=10 FAIL). | **a** | Agent must not synthesize a time series from a single-period payload. Real backend gap: batch tool ignores `periods`. |
| **da_tsla_revenue_2024_full_year** | `query_fundamentals(periods=4 → 8 → 12, TSLA, metric=revenue)` three escalating calls, **each returns 1 row** `revenue=22.387B` (Q1 2026). Answer reports four 2024 quarters `21.30/25.50/25.18/25.71B`. | Backend returns only the latest period regardless of `periods=`; agent had **zero 2024 data** and fabricated all four figures. Reproduced in **frozen** (grounding=10 FAIL). | **a** | Real backend defect: `query_fundamentals` does not honor `periods` for revenue history → returns 1 row. Agent must refuse/flag instead of inventing. |
| **ru_tsla_margin_trend** | `query_fundamentals(TSLA)` → 1 row, gross margin `0.2108`. Answer invents `16.31→17.24→17.99→20.12→21.08%` 5-point series. | Single-row tool; 4 intermediate quarters fabricated. **Same fabrication in frozen**, but frozen judge scored it 20 (PASS) — judge non-determinism, not a clean answer. | **a** (frozen PASS = judge miss, not class e) | Same as above. The frozen PASS shows the judge under-catches this, not that v1.4 is noise. |
| **iter3_tesla_revenue_since_2023** | v1.4: one `query_fundamentals` → 1 row; answer fabricates 13 quarters + annual totals 2023–2026. Frozen: agent made **two** `get_fundamentals_history` calls, got more data, PASS. | Single-row payload + fabricated multi-year trajectory. Frozen dodged via different (richer) tool routing. | **a** (v1.4) / tool-routing non-determinism vs frozen | Same backend `periods` gap; agent fabrication. |
| **chain_top_mover_fundamentals** | `get_market_movers` → BLDR; `get_fundamentals_history_batch(periods=4,[BLDR])` → 1 row. Answer gives Q2–Q4 2025 + Q1 2026 values that contradict the single sampled row (`$4.2B vs $3.29B`). | Single-period payload; multi-quarter breakdown fabricated **and** contradicts the one real value. Frozen PASS (grounding=22) = judge non-determinism on a fabricated answer. | **a** | Same backend `periods` gap; agent fabrication. |
| **ru_meta_eps_trend** | `query_fundamentals(META, eps)` → 1 row. Answer gives Q3 FY25=7.25, Q4 FY25=8.88, Q1 FY26=7.31, "Q2 FY26 unavailable." | Single-row tool; 2 of 3 cited EPS values un-grounded/un-sampled. Frozen PASS (20) on near-identical answer = judge non-determinism. | **a** (un-grounded extra quarters) | Same backend `periods` gap. Judge under-catches in frozen. |
| **iter3_top5_tech_marketcap** | Two `screen_universe` calls → tickers PLUS/ROG and CDNS/FTNT (`total_rows=1`, no truncation). Answer's top-5 = **UBER/SHOP/CRM/FTNT/CDNS** — UBER/SHOP/CRM never in any payload. | Screener returned a small set; agent **fabricated well-known large-cap tickers** to "complete" a plausible top-5. Reproduced in **frozen** (grounding=0 FAIL). | **a** | Real fabrication of off-payload entities. Also a screener-coverage gap (universe lacks mega-caps). |
| **ru_ai_semi_screener** | `screen_universe` → MCHP/MPWR only. Answer reports **MRVL $244.10B / 0.276 YoY** — MRVL absent from payload. | Fabricated ticker + market cap not in tool result (`total_rows=1`, not truncated). Reproduced in **frozen** (grounding=0 FAIL). | **a** | Real fabrication of off-payload entity. |
| **da_apple_revenue_fy2024q4_precision** | `get_fundamentals_history(periods=5, AAPL)` → 1 row `revenue=111.184B` (latest, mis-period). Asked FY2024-Q4. Answer reports `$102.5B` labelled "FY2025," plus 2 more fabricated quarters. | Wrong period AND wrong number AND fabricated extra quarters. Tool gave latest quarter, not FY2024-Q4. Reproduced in **frozen** (grounding=0 FAIL). | **a + d** | Backend lacks the requested historical quarter; agent both drifts the period and invents figures. |
| **tc_price_history_msft_ytd_range** | `get_price_history(MSFT)` → 1 row with `high=489.7, low=356.28`. Answer claims "high and low … are not present in the retrieved dataset, so I cannot provide those figures." | **Inverse hallucination**: tool DID return high/low; answer fabricates *missingness*. Reproduced in **frozen** (grounding=0 FAIL). | **a** (false "data missing") | Agent must read the returned `high`/`low` fields. Not an eval issue — the values are in the sample the judge saw. |
| **iter3_apple_revenue_precision** | `query_fundamentals(AAPL)` → `status=ok, item_count=1` (sample only carried `ticker`, no `revenue`). Answer claims a "missing coverage flag" and refuses. | Inverse hallucination / over-refusal: invents a "missing coverage flag" not in the payload. (Frozen failed this q via a **different** gate — `phantom_citation:[unverified]` — so it is *not* a frozen grounding-floor case.) | **a** (false missingness / over-refusal) | If revenue truly absent from the row, refuse honestly; do not invent a coverage-flag. Investigate why `query_fundamentals` returned no `revenue` field for AAPL. |
| **da_msft_fy2024q4_earnings_citations** | Two `query_fundamentals(MSFT)` calls, both `status=ok items=1` (samples carry only `ticker`). Answer refuses entirely: "referenced tool results that were not part of this query." | Over-refusal: data returned (status=ok) but answer presents nothing and asserts an unsupported reason. | **a** (over-refusal on returned data) | Same `query_fundamentals`-returns-only-`ticker` symptom (see below). Agent should surface whatever metric fields exist or refuse with the true reason. |
| **agg_q3_tim_cook** | `get_entity_intelligence` → only current Apple role; `search_documents`/`search_entity_relations` empty. Answer adds IBM/Compaq history **explicitly labelled "unverified, public knowledge."** | Honest parametric-knowledge fill for a biography the KG lacks. No grounding sample → judge "presumed" band, floored at 10. | **a** (technically un-grounded) — borderline; answer is transparent | Over-strict veto on a *transparently-flagged* parametric answer. Either accept flagged-unverified prose or have the agent omit it. Low priority. |
| **da_mstr_news_dec2024** | `search_documents` ×2 empty; `search_claims` → 20 generic KG rows (no dates). Answer correctly says "no news found" but adds an invented "90-day limit" claim. | Mostly correct refusal; the single ungrounded sentence ("news tool only fetches most recent 90 days") is fabricated. | **a** (minor fabricated claim) | Drop the invented tool-limitation sentence. Low severity. |

---

## Class tally

| Class | Count | q-ids |
|---|---|---|
| **(a) REAL platform/answer defect** | **15** (all, with sub-flavors) | every question above |
| **(b) EVAL ARTIFACT (1-row / capped sample)** | **0 pure** — partial contributor on mag5 (rows 4–5 un-sampled) only | tc_batch_fundamentals_mag5 (partial) |
| **(c) CITATION-ATTACHMENT** | **0** | — |
| **(d) PERIOD/DATE drift** | **1** (co-occurs with a) | da_apple_revenue_fy2024q4_precision |
| **(e) RUN NOISE (passed clean, fails noisy)** | **0** | — see note |

**Headline:** **There is no dominant "1-row-sample" eval artifact and no run-noise.** Every one of the 15 grounding-floor vetoes is a **genuine grounding defect** in the answer, driven by **two real platform root causes**, not by the judge mis-reading a capped sample.

### Why the "RUN NOISE" hypothesis is rejected
6 of the 15 (mag5, iter3_tesla_revenue, chain_top_mover, ru_tsla_margin_trend, ru_meta_eps_trend) *passed* grounding in the frozen clean run. But inspection shows those frozen "passes" are **not clean answers** — they are the **same fabrication** scored higher by a non-deterministic judge (ru_tsla_margin_trend, chain_top_mover, ru_meta_eps_trend), or a **different, luckier agent trajectory** that happened to fetch real data (iter3_tesla_revenue made 2 calls; mag5 produced a 1-row-per-ticker table). So the v1.4 FAILs are correct catches; the frozen PASSes are judge/agent stochastic misses. Classifying them as run-noise would *hide* a real defect.

### Why the "1-row eval artifact" hypothesis is rejected
The eval-artifact class requires a **rich multi-row answer whose numbers ARE in the full tool output but not the captured sample.** No question fits:
- Trajectory cases (tsla/nvda/meta/apple/chain): the full payload (`total_rows=1`, identical `result_preview`) genuinely contains **one** period — there is no un-sampled real data to recover. The escalating `periods=4→8→12` TSLA calls all returned the same single row.
- Screener cases (ai_semi, top5): `total_rows=1`, `truncated=false` — the fabricated tickers (MRVL, UBER, SHOP, CRM) are **absent from the payload**, not merely un-sampled.
- "Data missing" cases (msft_ytd, apple_precision, msft_earnings): the answer fabricates *missingness* of data the sample **does** show (high=489.7/low=356.28) or refuses on returned `status=ok` rows.

---

## Two real platform root causes (drive 13 of 15)

### RC-1 — `query_fundamentals` / `get_fundamentals_history[_batch]` do not return historical periods
The fundamentals tools advertise a `periods` argument and a multi-period history, but in this run they returned **exactly one (latest) row** for every fundamentals call — including TSLA where the agent escalated `periods` to 4, 8, then 12 and got the same single `revenue=22.387B` each time. `get_fundamentals_history_batch` returns 1 row **per ticker**, never multiple quarters. The agent, prompted for a trajectory/year-by-year/4-quarter answer, fills the gap by **fabricating the missing quarters**.

This single backend behavior is the upstream cause of: ru_nvda_amd_revenue_4q, da_tsla_revenue_2024_full_year, ru_tsla_margin_trend, iter3_tesla_revenue_since_2023, chain_top_mover_fundamentals, ru_meta_eps_trend, tc_batch_fundamentals_mag5, da_apple_revenue_fy2024q4_precision (8 questions). Several `query_fundamentals` calls returned a `grounding_sample` containing **only `ticker`** (no revenue/eps at all): iter3_apple_revenue_precision, da_msft_fy2024q4_earnings_citations — pointing at a metric-projection gap in `query_fundamentals` itself.

### RC-2 — agent fabricates off-payload entities / fabricates missingness
Independent of RC-1, the chat agent:
- invents well-known tickers absent from a screener result (MRVL, UBER, SHOP, CRM) to produce a "plausible-looking" list (ru_ai_semi_screener, iter3_top5_tech_marketcap); and
- claims data is missing when the tool returned it (tc_price_history_msft_ytd_range: high/low present; iter3_apple_revenue_precision / da_msft_fy2024q4_earnings_citations: status=ok but over-refuses).

These are answer-construction defects in the grounding/refusal policy, not tool-data gaps.

---

## Prioritized fix list

**Real-defect fixes first:**

1. **[RC-1 backend — highest leverage] Make fundamentals tools honor `periods` and return a real multi-period series.** Fix `query_fundamentals` / `get_fundamentals_history[_batch]` (and the S-service they call) so a `periods=N` request returns N historical rows, not the latest one. Also fix the `query_fundamentals` projection that returned only `ticker` (no requested metric) for AAPL/MSFT. Resolves the fabrication driver behind 8 questions.

2. **[Agent grounding policy] Forbid trajectory fabrication from single-period payloads.** When a fundamentals tool returns one period, the agent must present that one value and state the series is unavailable — never synthesize quarter labels and figures. (Catches the same 8 even before RC-1 lands.)

3. **[Agent grounding policy] Forbid off-payload entity invention and false-missingness.** (a) Never add tickers/companies not present in a screener/tool result. (b) Read returned scalar fields (`high`, `low`, `revenue`) before claiming data is missing; only refuse when the field is genuinely absent. Resolves ru_ai_semi_screener, iter3_top5_tech_marketcap, tc_price_history_msft_ytd_range, iter3_apple_revenue_precision, da_msft_fy2024q4_earnings_citations.

**Then the eval/emission improvement (defensive, not the dominant cause):**

4. **[Eval emission] Raise `GROUNDING_MAX_ROWS` (3 → ≥5) and prefer per-row capture for batch tools.** This only matters for the *partial* mag5 case (rows 4–5 un-sampled). It will not, by itself, flip any verdict here because the fabricated *extra quarters* remain ungrounded — but it removes the one place the judge currently can't see real returned rows, and avoids future false "fabricated" reads on ≥4-entity comparisons.

5. **[Judge calibration, optional] Decide policy for transparently-flagged parametric answers** (agg_q3_tim_cook): either accept "unverified public knowledge" prose or instruct the agent to omit it. Low priority — current veto is defensible.

---

## Top 3 fixes (summary)

1. **RC-1:** fix `query_fundamentals` / `get_fundamentals_history[_batch]` to honor `periods` and return the multi-period series (and project requested metrics) — the upstream cause of 8 fabrication fails.
2. **Agent policy:** forbid fabricating un-returned quarters/series from a single-period payload; present the one value + "series unavailable."
3. **Agent policy:** forbid inventing off-payload entities and forbid claiming returned data is "missing" (read `high`/`low`/`revenue` before refusing).

## Class tally (one line)
**a = 15 (every question; 1 also class d), b = 0 pure (mag5 partial only), c = 0, d = 1 (co-occurring), e = 0.**
