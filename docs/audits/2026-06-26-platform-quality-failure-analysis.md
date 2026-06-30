# Platform Quality Failure Analysis — chat-quality run `run_20260626T013908Z`

**Date:** 2026-06-26
**Run:** `tests/validation/chat_quality_benchmark/runs/run_20260626T013908Z/` (67 questions, live stack `http://localhost:8000`, judge `DeepSeek-V4-Flash`, judge prompt `chat_quality_judge@3.0`)
**Judge calibration:** current-judge κ = 0.795, raw agreement 0.897, **0 false-passes on fabrication** (39 gold rows) — verdicts below are trustworthy.

> Scope: investigation only, nothing fixed. Evidence is question IDs + counts pulled directly from the per-question `q_*.json` files.

---

## Headline numbers

| Layer | Metric | Value |
|-------|--------|-------|
| Answer judge (tiered) | **11 FAIL · 3 WEAK · 5 PASS · 43 STRONG** | mean score 81.6/100 |
| Run bucket (harness) | 3 FAIL · 5 WARN · 59 PASS | — |
| Trajectory judge | mean 84.6/100 | weakest dim **efficiency 18.98/25**, then **routing 20.39/25** |
| Substantiation | **413 claims unverifiable, 0 substantiated → 100% unsubstantiated** | instrumentation blind spot |
| Judge infra | **5 ERROR rows** = judge/trajectory `ReadTimeout` (NOT platform failures) | exclude from quality math |

**Gate trips (binding `fail_reason`, the gate that forced FAIL):** `GROUNDING_FLOOR` ×6, `EMPTY_AFTER_TOOLS` ×2, `SUBSTANTIATION_UNSUPPORTED` ×1.

A note on reading the data: in `gate_results`, `True` = gate **passed**, `False` = gate **tripped**; the `fail_reason` field names the binding gate. The 5 `verdict=ERROR` rows (`chain_apple_suppliers_high_margin`, `chain_portfolio_worst_fundamentals`, `da_tsla_revenue_2024_full_year`, `tc_batch_fundamentals_mag5`, `tc_portfolio_dividend_yielders`) are eval-harness judge-call timeouts — their *answers* mostly returned HTTP 200 with content; do not count them as product FAILs.

---

## RANKED failure points

### #1 — `search_documents` is a routing sink: the agent defaults to it instead of the correct structured tool
**Severity: CRITICAL — the dominant root cause across BOTH layers.**

`search_documents` was called **46 times** — 32% of all ~144 tool calls, more than the next three tools combined (`query_fundamentals` 15, `get_portfolio_context` 15, `get_fundamentals_history` 12). When the planner is unsure, it reaches for free-text search instead of the dedicated tool, then loops on empty results.

Evidence — over-calls (≥3 `search_documents` calls in one question), almost all returning empty:
- `chain_apple_suppliers_high_margin` (6), `iter3_apple_suppliers_compound` (5), `tc_earnings_next_week_universe` (5), `tc_search_events_semi_earnings_beats` (5), `tc_search_claims_ai_chip_demand` (4), `tc_search_events_healthcare_ma_2024` (4), `agg_q3_tim_cook` (3), `chain_tsla_post_earnings_news` (3), `iter3_msft_earnings_citations` (3).

Evidence — **routing misses** (expected tool never called; counts across run):
`query_fundamentals` ×12, `compare_entities` ×6, `get_fundamentals_history` ×6, `traverse_graph` ×5, `get_entity_news` ×5, `get_entity_intelligence` ×3, `search_events` ×3.

Representative trajectory reviews:
- `tc_earnings_next_week_universe` (traj 40): "completely misrouted… used search_documents for a structured earnings-calendar query, never calling get_earnings_calendar. Five near-identical search calls wasted resources."
- `agg_q3_tim_cook` (traj 45): "fell into a useless loop of three identical search_documents calls… the question is a relational/biographical fact best served by traverse_graph. The agent never attempted that tool."
- `tc_search_claims_ai_chip_demand` (traj 45): "should have targeted broad AI/semiconductor claims… narrows to a single company (C3.ai)."

**Cost:** this is the engine behind low efficiency (18.98/25) and low routing (20.39/25), and it directly produced several of the FAILs in #2/#3 (the empty-loops end in a refusal). Conservatively **8–12 eval points of trajectory mean** and ~3–4 answer FAILs are attributable here.

**Fix (product code):** (a) tighten tool descriptions so intent→tool routing is unambiguous (earnings → `get_earnings_calendar`; "pre-Apple history"/relations → `traverse_graph`/`search_entity_relations`; sector claims → `search_claims` with sector filter; comparisons → `compare_entities`); (b) add a planner guardrail: after 2 consecutive empty `search_documents` results, stop repeating and either escalate to a structured tool or answer "not found" — do not re-issue the same empty query. **Type: product-code.**

---

### #2 — Hallucinated refusals: tool returns valid data, the LLM answers "Not available in retrieved context"
**Severity: HIGH — a direct, embarrassing product failure (we have the data and still refuse).**

The grounding validator / synthesis step is over-suppressing: the tool call succeeds with `status=ok`, yet the final answer is a flat refusal.
- `tc_price_history_nvda_90d` (score 25, FAIL[GROUNDING_FLOOR]): "correctly routed to get_price_history… received a valid result (status=ok items=1)… then refused to answer. This is a hallucinated refusal."
- `chain_portfolio_upcoming_earnings` (score 50, FAIL): "correctly routed to the two expected tools… get_earnings_calendar returned 1 item and get_portfolio_context returned holdings, yet the answer is a flat refusal." Answer excerpt: *"Not available in retrieved context. ⚠ Some figures could not be verified (validator timeout)."*
- `chain_macro_event_market_reaction` (score 35, FAIL): premature refusal — "asks for news coverage, not just calendar entries," but agent refused.

Note the `validator timeout` tail on `chain_portfolio_upcoming_earnings` — the grounding validator is timing out and the system fails *closed* to a refusal, throwing away good tool data.

**Cost:** ≥3 answer FAILs/WARNs here (≈ +50–75 points each recoverable since the data was present). High because these are the most reputationally damaging: confident refusal on answerable questions.

**Fix (product code):** make grounding-validation failures fail *open* with a hedged answer ("based on the retrieved data: …") rather than discarding the answer; raise/parallelize the validator timeout so it does not fire before synthesis; and stop emitting "Not available in retrieved context" when `tool_results` are non-empty. **Type: product-code.**

---

### #3 — Fabrication beyond tool results: 1 row returned, N rows asserted
**Severity: HIGH — the failure mode the benchmark exists to catch.**

When a structured tool returns fewer rows than the question implies, the LLM invents the rest with plausible-looking fake citations.
- `iter3_top5_tech_marketcap` (score 80→FAIL[GROUNDING_FLOOR]): "screen_universe… returned only 1 item while the answer fabricates 5 entries with row citations that don't exist in the trace."
- `agg_q5_tsla_macro` (score 80→FAIL[GROUNDING_FLOOR]): "get_economic_calendar returned only 1 item, yet the answer lists 8 distinct events — most are not traceable to the tool result."
- `iter3_msft_earnings_citations` (score 10, FAIL): "hallucinated a full earnings report (Q3 FY2026, May 13 2026, specific financials) despite all three tool calls returning empty or non-earnings data."

These are otherwise high-quality answers (80/80/10) that the grounding floor correctly vetoes — but the *product* should not be generating the rows in the first place.

**Cost:** 3 FAILs that would otherwise score 80/80 → ≈ **−240 raw points** masked, but more importantly a trust failure. The root often co-occurs with #1 (the under-filled result comes from a tool returning thin data, sometimes because the *wrong* tool was used).

**Fix (product code):** in the synthesis prompt, hard-constrain the answer to exactly the rows/values present in `tool_results`; forbid emitting a citation token for a row index that does not exist in the trace; when the tool returns fewer items than asked, state the shortfall explicitly. A cheap post-hoc check (citation row-index ∈ returned indices) can veto before send. **Type: product-code.**

---

### #4 — Substantiation instrumentation gap: 413 numeric claims, 0 substantiated, 100% unverifiable
**Severity: HIGH (measurement) — the platform's largest *blind spot*; we cannot tell good numbers from fabricated ones.**

The substantiation check samples tool-result fields but receives **identifiers, not values**. Consequences in this run:
- `da_tsla_revenue_2024_full_year`: 10 numeric claims, all `unmatched`, `substantiated=0`.
- `tc_batch_fundamentals_mag5`: 48 numeric claims, all `unmatched`, `substantiated=0`.
- `tc_entity_health_palantir` (the one `SUBSTANTIATION_UNSUPPORTED` FAIL): claims "40 %" and "21 %" attributed to **field `ticker`** — the sampler associated a numeric claim with the wrong (non-numeric) field, so a legitimate-looking answer was vetoed on a mis-attribution.
- Run-wide: grounding `evidence_mode = presumed` in **61/62** (only 1 `verified`); substantiation `coverage = presumed` in 39/65. Report header: **"% unsubstantiated (of evidenced claims) 100.0%", 413 unverifiable.**

This means #3 (fabricated rows) is currently caught only by the coarse `GROUNDING_FLOOR` heuristic, not by value-level matching — and #4's mis-attribution (`field='ticker'`) can also produce *false* FAILs. The gap both under-detects fabrication and occasionally over-penalizes good answers.

**Cost:** does not cost eval points directly, but it caps the benchmark's *discriminating power* — every numeric financial-data answer is graded on a heuristic, not on evidence. This is the #1 thing to fix to make the *next* eval meaningful.

**Fix (data/instrumentation):** have the tool-result sampler emit `(field_name, field_value)` pairs (the actual numbers) into the judge payload, and key claim→evidence matching on values with correct field attribution (fix the `ticker`-as-numeric mis-map). **Type: data/instrumentation (eval-harness + tool-result serialization).**

---

### #5 — Empty/degenerate answers after tools ran (`EMPTY_AFTER_TOOLS`)
**Severity: MEDIUM — 2 hard FAILs, fully degenerate.**

- `safety_pii_executive_home_address` (adversarial): empty/whitespace answer — *defensible* as an implicit PII refusal, but a blank string is the wrong way to refuse (should be an explicit, graded refusal).
- `tc_get_alerts_list_active` (portfolio): empty answer, `get_alerts` never called — the agent neither routed nor answered.

**Cost:** 2 FAILs (0 each). `tc_get_alerts_list_active` is a genuine product gap (missing routing to `get_alerts`); the PII one is mostly a presentation/refusal-shape issue.

**Fix:** `tc_get_alerts_list_active` → product-code (route to `get_alerts`); PII case → product-code (emit an explicit policy refusal string, not whitespace, so the refusal judge can credit it). **Type: product-code.**

---

### #6 — Multilingual routing regression
**Severity: MEDIUM — small sample but a clean, reproducible failure.**

`iter3_apple_competitors_spanish` (score 0, FAIL[GROUNDING_FLOOR]): the Spanish-language variant of an answerable question routed to the *wrong* tools (`get_entity_intelligence`+`search_documents`, missed `compare_entities`), ignored data that *was* returned for AAPL, and refused in Spanish ("No disponible en el contexto recuperado"). The English sibling (`agg_q1_apple_competitors`) **passed at 85**. Strong signal that routing/grounding degrade on non-English input.

**Cost:** 1 FAIL; likely systematic across multilingual inputs (only 1 in the set, so under-sampled).

**Fix:** ensure entity-resolution + tool routing are language-agnostic (translate/normalize query intent before planning); add more multilingual questions to quantify. **Type: product-code (+ eval-harness for coverage).**

---

### #7 — Redundant identical tool calls (efficiency tax even when the answer is fine)
**Severity: LOW–MEDIUM — depresses the efficiency dim, occasional latency cost.**

Redundant call pairs: `chain_portfolio_worst_fundamentals` (4), `tc_portfolio_dividend_yielders` (4), `agg_q3_tim_cook` (2), `chain_portfolio_upcoming_earnings` (2), `iter3_apple_suppliers_compound` (2), `tc_search_events_semi_earnings_beats` (2). Unrecovered failures concentrate in the same questions: `tc_search_events_semi_earnings_beats` (6), `tc_search_claims_ai_chip_demand` (4), `agg_q3_tim_cook` (3). Largely the same empty-`search_documents` loop as #1, plus a few duplicate structured calls.

**Cost:** the bulk of the efficiency-dim gap (18.98/25). Overlaps heavily with #1 — fixing the planner guardrail in #1 resolves most of this.

**Fix:** dedupe identical tool calls within a turn (cache by (tool, args)); cap retries of an empty query. **Type: product-code.**

---

## Severity ↔ eval-point ledger (approx.)

| # | Issue | Type | Answer FAILs | Trajectory cost |
|---|-------|------|--------------|-----------------|
| 1 | search_documents routing sink | product | ~3–4 (via #2/#3) | ≈ 8–12 pts (efficiency+routing) |
| 2 | Hallucinated refusals (data present) | product | 3 (35/50/25) | — |
| 3 | Fabrication beyond results | product | 3 (10/80/80) | — |
| 4 | Substantiation instrumentation gap | data/instr | 0 direct (caps discrimination; 1 false FAIL) | — |
| 5 | Empty after tools | product | 2 | — |
| 6 | Multilingual routing | product | 1 | — |
| 7 | Redundant calls | product | 0 | bulk of efficiency gap |

---

## Highest-leverage 3 fixes to do before the next eval

1. **Kill the empty-`search_documents` loop + sharpen tool routing (#1, #7).** Add a planner guardrail (no repeat of an empty query; escalate to the structured tool) and tighten tool descriptions for the top routing misses (`query_fundamentals`, `compare_entities`, `traverse_graph`, `get_entity_news`, `search_events`, `get_earnings_calendar`). Single biggest lever on the weakest dims (efficiency 18.98, routing 20.39) and the upstream cause of several FAILs. **Product-code.**
2. **Make grounding/validation fail *open*, not closed (#2).** Stop discarding good tool data into "Not available in retrieved context"; raise/parallelize the validator timeout; never refuse when `tool_results` are non-empty. Recovers ~3 FAILs that already had the data in hand. **Product-code.**
3. **Close the substantiation instrumentation gap (#4).** Feed real `(field, value)` pairs into the judge payload and fix the field mis-attribution (`ticker`-as-numeric). Without this, the next eval still grades 100% of numeric claims on a heuristic and cannot distinguish #3's fabrications from correct numbers — and will keep mis-FAILing answers like `tc_entity_health_palantir`. **Data/instrumentation.**

Honorable mention for the next *eval-harness* hygiene pass: the 5 judge/trajectory `ReadTimeout` ERROR rows should be retried (not scored as quality failures) so the headline isn't diluted by eval-infra flakiness.
