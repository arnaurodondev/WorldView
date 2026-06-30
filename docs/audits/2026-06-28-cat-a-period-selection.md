# Category A — Synthesis PERIOD-SELECTION Defects (read-only audit)

**Date:** 2026-06-28
**Scope:** Chat agent answers the WRONG fiscal period / quarter, even though RC-1 already fixed the
fundamentals tools to return real multi-period data. These are NOT data-gap fabrications — they are the
model **selecting and/or labelling the wrong period** from a payload that (mostly) contains the right numbers.
**Runs:** RC-fixed `run_20260628T234356Z` (primary), frozen `run_20260627T032420Z` (contrast).
**Method:** for each question, trace requested period → periods the tool returned → period the model selected
and how it labelled it → why it is wrong → root-cause class.

Cause classes used throughout:
- **(a)** model misreads / misaligns period labels (fiscal vs calendar, scrambled ordering, wrong FY).
- **(b)** tool returns ambiguous/misleading labels that invite the error.
- **(c)** the requested historical period is genuinely **absent** from the returned window → model should
  refuse/flag, but instead substitutes the **nearest** period.
- **(d)** the prompt does not enforce "match the user's requested period to the tool's period label before quoting."

---

## Key architectural fact (applies to every question)

The market-data history use case **does** compute a correct, unambiguous fiscal label per row.
`_period_label()` in `services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py:422`
resolves the issuer's `fiscal_year_end_month` and returns `"Q4 FY2024"`-style labels
(AAPL fy_end=9, 2024-09-28 → **Q4 FY2024**; NVDA fy_end=1, 2026-01-31 → **Q4 FY2026**). The LLM-facing
markdown table (`handlers/market.py:2047 _format_fundamentals_table`) renders a `Period` column from
`p.get("period") or p.get("date")`. So when the row carries a label, the model **sees** a correct fiscal label.

Two consequences:
1. The grounding-sample shown in the run JSON (`grounding_sample.fields`) is a **label-stripped** flattening
   (`revenue`, `revenue_2`, `revenue_3` …) used only by the judge/SSE — it is NOT what the LLM consumes.
   Do not conclude "the tool returned no labels" from the run JSON alone; the LLM gets the labelled table.
2. Therefore the defects are predominantly **(a)** (model mis-selects/mislabels despite correct labels) and,
   for the Apple case, **(c)** (asked-for period is outside the returned window). They are NOT **(b)** —
   the tool's labels are correct. **(d)** is the missing guardrail that would catch both.

---

## Q1 — `da_apple_revenue_fy2024q4_precision`  → CAUSE (c) primary, (a) secondary

**Requested:** Apple revenue for **fiscal Q4 2024 (quarter ending September 28, 2024)**, 3 decimals.
**Truth:** Apple Q4 FY2024 revenue = **$94.930B**.

**Tool call:** `get_fundamentals_history(ticker=AAPL, period_type=quarterly, periods=6)`.

**Periods the tool returned** (decoded from the revenue values; newest-first):

| Returned value | Identifies | Fiscal label |
|----------------|------------|--------------|
| revenue   = $111.184B | Dec 2025 holiday quarter | Q1 FY2026 |
| revenue_2 = $143.756B | Dec 2024 holiday quarter | Q1 FY2025 |
| revenue_3 = $102.466B | Sep 2025 quarter         | **Q4 FY2025** |

The asked-for **Q4 FY2024 ($94.930B, Sep 2024) is NOT in the returned window.** The 6-period window only
reaches back to ~Sep 2025 because the run clock is mid-2026. Confirmed by contrast: the frozen run
`run_20260627T032420Z` returned only `{revenue: 111.184B, revenue_2: 143.756B}` — an even shallower window;
the RC fix widened it by one quarter (added revenue_3=102.466B) but **still does not reach Sep 2024.**

**What the model selected & how it labelled it:** picked `revenue_3 = $102.466B` (the **Sep 2025** quarter,
the nearest September-ending quarter to the asked one) and labelled it — incoherently — as both
"fiscal Q4 2024" (early token) and "**Q4 FY2025** (quarter ending September 28 **2025**)" (final answer).
It even self-contradicted mid-stream: `| billion | Q4 FY2025 (Fiscal Q4 2024) |`.

**Substantiation layer:** `substantiated=1, unmatched=5` — only the $102.5B value matched a returned row;
the requested-period value never appears. Grounding judge = 0 → GROUNDING VETO → FAIL.

**Why it's wrong / root cause:** The requested historical quarter is **genuinely absent** from the returned
set → cause **(c)**. The correct behaviour is to refuse / flag "Q4 FY2024 (Sep 2024) is outside the available
history; the oldest quarter returned is Q1 FY2025 (Dec 2024)." Instead the model **substituted the nearest
September-ending quarter and relabelled it**. This is aggravated by Apple's structural label trap: two
consecutive Q4s (Sep 2024 and Sep 2025) **both end "September 28,"** so a model anchoring on the day-of-month
in the prompt is easily lured into the wrong fiscal year — a flavour of **(a)** on top of the absence.
A secondary precision defect: the table rounds revenue to `$X.1f B` (`market.py:2075`), so 3-decimal precision
is impossible from the table alone — the model padded "$102.500B" which is itself unsubstantiated.

---

## Q2 — `ru_nvda_amd_revenue_4q`  → CAUSE (a) (fabricated quarters + wrong FY labels)

**Requested:** Compare NVIDIA vs AMD revenue trajectories over the **last 4 quarters**.

**Tool call:** `get_fundamentals_history_batch(tickers=[NVDA, AMD], periods=4)`.

**Periods the tool returned** (4 per ticker; sample shows NVDA `revenue/_3` and AMD `revenue_2/_4`):
NVDA = {$81.615B, $57.006B, …}; AMD = {$10.253B, $7.685B, …}. Four real quarters per ticker, correctly
labelled by `_period_label` (NVDA fy_end=1 ⇒ fiscal labels; AMD fy_end=12 ⇒ calendar = fiscal).

**What the model produced:** a 4-row table that **invents two quarters not in the payload** — "Q4 FY2026"
NVDA $68.1B and "Q2 FY2026" NVDA $46.7B — and assigns AMD a "Q3 FY2026 $9.2B" figure absent from the sample.
It also mislabels the fiscal years (NVDA's most-recent real quarter is FY2026 Q3, not "Q1 FY2026").

**Substantiation layer:** `substantiated=8, unmatched=6` — **6 of the reported figures match NO returned row.**
Grounding judge = 15 (floor).

**Why it's wrong / root cause:** **(a)** — the model both **mislabels** the fiscal years of the 4 real
quarters AND **fabricates** two extra quarters to pad a "4 quarter-over-quarter growth" narrative. The tool
returned exactly 4 correctly-labelled quarters per ticker; the model did not read those labels and instead
manufactured a tidy descending FY sequence. No ticker-collision in the data itself — the collision is in the
model's invented labels. This is the classic "pad the series to look complete" failure the synthesis prompt
already warns against (`synthesis.py:64-67, 98-101`) but does not enforce against label-by-label.

---

## Q3 — `da_tsla_revenue_2024_full_year`  → CAUSE (a) (scrambled quarter ORDERING)

**Requested:** Tesla quarterly revenue for **each quarter of calendar 2024 (Q1–Q4 2024)**.

**Tool calls:** `query_fundamentals(TSLA, quarterly, periods=8)` then `periods=12`.

**Periods the tool returned:** 8–12 real quarters with correct `period_label` + `period_end` (TSLA fy_end=12
⇒ fiscal = calendar, so labelling is trivially unambiguous here). The four 2024 calendar quarters are present:
Q1=$21.301B, Q2=$25.500B, Q3=$25.182B, Q4=$25.707B.

**What the model produced:**

| Model label | Model value | Actual quarter of that value |
|-------------|-------------|------------------------------|
| Q1 2024 | $21.30B | Q1 2024 ✓ |
| **Q2 2024** | **$25.50B** | …is Q2 ✓ but paired against… |
| Q3 2024 | $25.18B | Q3 2024 ✓ |
| **Q4 2024** | **$25.71B** | the model sourced this from the wrong row position |

**Substantiation layer:** `substantiated=4, unmatched=0` — **every value matches a returned row.** The grounding
judge (score 10) flags that the answer "**reverses the actual quarter ordering**" — it pairs `revenue_8` and
`revenue_6` to the wrong Q-labels.

**Why it's wrong / root cause:** **(a)**, in its purest form. The values are 100% substantiated; the **only**
defect is that the model **assigned the right numbers to the wrong quarter labels** — it mapped table rows to
Q1/Q2/Q3/Q4 by guessing position rather than reading each row's `period_label`/`period_end`. Because TSLA's
calendar = fiscal, there is no fiscal ambiguity to blame; this is a clean demonstration that the model is not
binding values to the labels the tool already provides. The fix is a label-binding directive (and/or a
deterministic guard), not better tool labels.

---

## Q4 — `da_msft_fy2024q4_earnings_citations`  → CAUSE (c)+routing; period mislabel as symptom

**Requested:** What Microsoft reported in **fiscal Q4 2024 earnings (quarter ending June 30, 2024)**, with a
source per number. (Score improved 25→75 vs frozen but still floors.)

**Tool calls:** 5× `search_documents(MSFT, source_types=[sec_filing, earnings])` — **NOT a fundamentals tool.**
Four of five returned `status=empty`; one returned 1 item.

**What the model produced:** a refusal — "The retrieved sources do not contain Microsoft's fiscal **Q4 2026**
earnings figures … not available." It refused correctly on substance (no numbers fabricated, grounding=25),
which is why the score rose; but it **mislabelled the requested period as "fiscal Q4 2026"** when the user
asked for fiscal Q4 2024.

**Why it floors / root cause:** This is mostly a **tool-routing** miss (it queried `search_documents` for
earnings text instead of `get_fundamentals_history`/`query_fundamentals` for the numbers) layered on a
**(c)** outcome (the document corpus has no MSFT Q4-FY2024 filing → genuine absence). The **period-selection**
symptom relevant to Category A is the same as the others: even while refusing, the model **echoed the wrong
fiscal period back** ("Q4 2026" for a "Q4 2024" question), confirming it is not parsing/anchoring the user's
requested fiscal period. A period-anchoring directive (d) would at least make the refusal name the correct
period; the routing/data-absence is a separate (out-of-scope) fix.

---

## Cause distribution

| Question | Dominant cause | Mechanism |
|----------|----------------|-----------|
| da_apple_revenue_fy2024q4_precision | **(c)** + (a) | Sep-2024 quarter absent from 6-quarter window; model substitutes nearest Sep-2025 quarter and relabels; Apple's two Sep-28 Q4s aggravate |
| ru_nvda_amd_revenue_4q | **(a)** | mislabels fiscal years + fabricates 2 quarters to pad the series (6 unmatched values) |
| da_tsla_revenue_2024_full_year | **(a)** | correct values, **scrambled Q1–Q4 ordering**; values not bound to the tool's period labels |
| da_msft_fy2024q4_earnings_citations | (c)+routing | wrong tool + genuine doc absence; period echoed wrong ("Q4 2026") as a symptom |

**Dominant cause across the category: (a) — the model does not bind quoted values to the period labels the
tool already returns** (3 of 4 questions exhibit it; it is the *sole* defect in the cleanest case, TSLA).
**(c) — refuse-when-absent — is the dominant cause for the single hardest case (Apple)** and contributes to
MSFT. The tool labels themselves are correct (**not (b)**); the missing guardrail is **(d)**.

---

## Prioritized fix

### FIX 1 (top, highest leverage) — Synthesis period-binding directive **(d)** — fixes TSLA + NVDA/AMD, mitigates Apple/MSFT

Add to the synthesis prompt (`libs/prompts/src/prompts/chat/synthesis.py`, the ANTI-FABRICATION POLICY block
around lines 64-69 / 98-101) an explicit **period-matching rule**, paraphrased:

> Before quoting any figure, identify the row's `period_label` (or `period_end`) in the tool table and quote
> the value **only under that exact label** — never re-order, re-index, or re-assign quarters by position.
> When the user names a specific fiscal period (e.g. "fiscal Q4 2024 ending Sep 28 2024"), find the row whose
> `period_label`/`period_end` matches it. **If no returned row matches the requested period, say so explicitly
> and name the closest available period — do NOT substitute the nearest quarter under the requested label.**

- Fixes **TSLA** outright (forces row-bound labelling instead of positional guessing).
- Fixes **NVDA/AMD** (forbids inventing FY labels / padding quarters; binds the 4 real quarters to their labels).
- Mitigates **Apple** and **MSFT** (forces an explicit "Q4 FY2024 not in the returned history; oldest available
  is Q1 FY2025 (Dec 2024)" rather than a relabelled substitute).
- This is the cheapest, broadest fix and is the dominant cause's natural counter.

### FIX 2 (defense-in-depth) — Deterministic period-alignment guard — hard backstop for Apple/MSFT **(c)**

A prompt directive is probabilistic. Because **getting the period right is a financial-correctness issue**,
add a deterministic post-synthesis check in the rag-chat pipeline: parse the user's requested fiscal period
(quarter + fiscal year, or explicit period_end date) and verify it is present among the returned rows'
`period_label`/`period_end`. If the requested period is **absent**, force the answer to flag it (or veto a
quoted value labelled with the absent period). This converts the Apple-class failure from "silent wrong
answer" to "explicit refusal/flag" without relying on the model. Same class of guard as the existing
phantom-row drop (`market.py:817`) and BP-577 periodicity tag — extend it to *requested-period presence*.

### FIX 3 (small, Apple-precision only) — surface raw period_end + un-rounded revenue to the model

The table rounds revenue to `$X.1f B` (`market.py:2075`) and renders `period` but the LLM-visible cell does
not always carry the explicit `period_end` ISO date next to the label. For 3-decimal-precision questions the
model cannot answer from the rounded cell, so it pads digits. Render `period_end` (ISO date) alongside the
label and pass an un-rounded revenue figure (or refuse precision the table cannot support). Narrow scope:
helps Apple precision; does not address the core selection defect.

**Recommendation:** ship **FIX 1 now** (covers the dominant (a) cause and 2 of 4 questions immediately),
and **FIX 2** as the deterministic backstop for the (c) Apple-class refusal (the financial-correctness
guarantee). FIX 3 is optional polish for the 3-decimal precision sub-requirement.
