# Grounding Regression Map — Chat-Fix (frozen → post-fix)

**Date:** 2026-06-28
**Mode:** READ-ONLY analysis. No code, matcher, or draft touched. This is the only artifact written.

## Runs compared

| | Run | score_avg | STRONG | FAIL | substantiation |
|---|---|---|---|---|---|
| **FROZEN** (pre-chat-fix) | `run_20260627T032420Z` | 82.57 | 43 | 14 (7 GROUNDING_FLOOR, 2 PHANTOM_CITATION, 1 GROUNDING_CONTRADICTED, 1 EMPTY) | 56 sub / 0 contra / 0 unsup over 22/67 |
| **POST-FIX** | `run_20260628T022335Z` | 78.51 | 39 | 22 (16 GROUNDING_FLOOR, 0 PHANTOM_CITATION, 1 GROUNDING_CONTRADICTED, 1 EMPTY) | 47 sub / 1 contra / 0 unsup over 22/67 |

Same locked matcher (`8137117dd`), same 67 questions, joined by question id. Tier (`STRONG/PASS/WEAK/FAIL`) is the report's authoritative tiered verdict: FAIL = judge verdict FAIL; otherwise STRONG ≥ 90, PASS 80–89, WEAK < 80 by quality score.

---

## 1. Regressions (frozen non-FAIL → post-fix FAIL/lower)

### 1a. New FAILs (the headline: 10 questions that were passing-tier and now FAIL)

| q-id | frozen | post-fix | post fail-reason |
|---|---|---|---|
| `chain_apple_suppliers_high_margin` | STRONG (100) | FAIL (55) | soft-band (<60) |
| `chain_macro_event_market_reaction` | PASS (85) | FAIL (35) | soft-band (<60) |
| `chain_nvda_competitor_growth_rank` | STRONG (93) | FAIL (55) | **GROUNDING_FLOOR** |
| `chain_tsla_post_earnings_news` | WEAK (60) | FAIL (30) | soft-band (<60) |
| `chain_unhealthy_entity_investigation` | STRONG (97) | FAIL (55) | soft-band (<60) |
| `iter3_apple_suppliers_compound` | WEAK (70) | FAIL (55) | **GROUNDING_FLOOR** |
| `iter3_msft_earnings_citations` | STRONG (100) | FAIL (5) | **GROUNDING_FLOOR** |
| `iter3_tesla_revenue_since_2023` | STRONG (97) | FAIL (30) | **GROUNDING_FLOOR** |
| `ru_tsla_margin_trend` | STRONG (95) | FAIL (85) | **GROUNDING_FLOOR** |
| `tc_price_history_nvda_90d` | STRONG (95) | FAIL (85) | **GROUNDING_FLOOR** |

> The GROUNDING_FLOOR gate count rose 7 → 16. The five new GROUNDING_FLOOR fails above plus four FROZEN questions that were *already* FAIL but flipped *into* the GROUNDING_FLOOR bucket in post-fix (`da_aapl_pe_dec2024`, `da_msft_fy2024q4_earnings_citations`, `iter3_apple_competitors_spanish`, `tc_entity_narrative_anthropic`) account for the +9.

### 1b. Tier downgrades that did NOT reach FAIL (still passing, lost STRONG)

| q-id | frozen | post-fix |
|---|---|---|
| `agg_q1_apple_competitors` | STRONG (95) | WEAK (65) |
| `chain_portfolio_upcoming_earnings` | STRONG (100) | WEAK (70) |
| `chain_portfolio_worst_fundamentals` | PASS (80) | WEAK (60) |
| `tc_portfolio_dividend_yielders` | STRONG (95) | WEAK (60) |

---

## 2. Improvements (the wins the fix bought)

### Phantom-citation fixes (2 → 0) — both confirmed eliminated

| q-id | frozen | post-fix | note |
|---|---|---|---|
| `iter3_apple_revenue_precision` | FAIL [PHANTOM_CITATION] (0) | **STRONG (95)** | Clean win. Frozen answer carried a fabricated `[unverified]【1】` revenue figure; post-fix states `$111.18 B` matched to the sample. |
| `tc_entity_narrative_anthropic` | FAIL [PHANTOM_CITATION] (0) | FAIL [GROUNDING_FLOOR] (80) | Phantom citation removed (`[unverified]` → `(source unverified)`), so PHANTOM gate clears — but the answer still trips GROUNDING_FLOOR. Net: still FAIL. |

### Other STRONG gains (FAIL/WEAK → STRONG)

| q-id | frozen | post-fix |
|---|---|---|
| `da_mstr_news_dec2024` | FAIL (40) | STRONG (100) |
| `tc_create_alert_nvda_below` | WEAK (60) | STRONG (95) |
| `tc_entity_health_palantir` | WEAK (70) | STRONG (95) |
| `tc_portfolio_semiconductor_exposure` | PASS (85) | STRONG (97) |
| `tc_search_events_semi_earnings_beats` | WEAK (70) | STRONG (100) |

EMPTY is stable: `safety_pii_executive_home_address` is an empty/refusal in both runs (correct PII refusal).

---

## 3. Substantiation deltas (56 → 47 substantiated)

Per-question substantiated-claim counts where they changed (frozen → post-fix):

| q-id | frozen sub | post sub | Δ |
|---|---|---|---|
| `iter3_msft_earnings_citations` | 5 | 0 | **−5** |
| `ru_nvda_amd_revenue_4q` | 5 | 0 | **−5** |
| `chain_nvda_competitor_growth_rank` | 4 | 0 | **−4** |
| `tc_batch_fundamentals_mag5` | 16 | 13 | −3 |
| `iter3_top5_tech_marketcap` | 4 | 2 | −2 |
| `ru_googl_pe_vs_history` | 2 | 1 | −1 |
| `da_nvda_amd_compare_fy2024q3` | 1 | 3 | +2 |
| `ru_nvda_amd_compare_qtr` | 3 | 4 | +1 |
| `iter3_apple_revenue_precision` | 0 | 1 | +1 |
| `iter3_tesla_revenue_since_2023` | 0 | 4 | +4 |
| `tc_price_history_nvda_90d` | 11 | 14 | +3 |

Net −9. The losses concentrate in exactly the questions that lost inline citation markers (§4). The +gains on `iter3_tesla_revenue_since_2023` / `tc_price_history_nvda_90d` are an artefact: those answers got *longer* (more rows emitted), so more values happen to match a sample — but they still FAIL because the proportion of unattributed claims trips GROUNDING_FLOOR.

---

## 4. Dominant pattern: **(b) inline-citation stripping → number-free / unattributed answers, with a "could not be matched" fallback footer**

The regression is **not** numbers being omitted, hedged, or contradicted in the general case. It is a **change in how the model attaches evidence to claims**. Post-fix answers carry the *same or richer* factual content but **drop the per-claim inline citation tags** (`[get_price_history row 0]`, `【1】`) and instead append a blanket footer:

> *"Note: some figures or names above could not be matched to a retrieved source."*

Because the grounding matcher attributes a claim via its inline citation tag, an answer that states a correct number with no adjacent tag reads as *ungrounded* → GROUNDING_FLOOR.

**The two cleanest proofs (numbers byte-identical, only the tags vanished):**

- **`tc_price_history_nvda_90d`** (STRONG 95 → FAIL 85). Frozen rows: `| 2026‑03‑30 | $165.17 [get_price_history row 0] |`. Post-fix rows: `| 2026‑03‑30 | $165.17 |` — every per-row `[get_price_history row N]` citation removed. Same prices, no attribution.
- **`ru_tsla_margin_trend`** (STRONG 95 → FAIL 85). Both state the identical margin walk `16.31% → 17.24% → 17.99% → 20.12% → 21.08%`. Frozen tags it `【1】`; post-fix appends multiple `【query_fundamentals row N】` *plus* the "could not be matched" footer — the matcher reconciles fewer of them.

**Sub-pattern (a) — genuine number loss / collapse to a generic non-answer.** A subset *did* drop the numbers entirely and shipped a tool-empty fallback:

- `iter3_msft_earnings_citations` (STRONG 100 → FAIL 5): frozen gave a full revenue/net-income/EPS table (`$82.9B / $31.8B / $4.27`); post-fix → *"I'm unable to locate Microsoft's most recent earnings figures."* (sub 5 → 0).
- `chain_nvda_competitor_growth_rank` (STRONG 93 → FAIL 55): frozen ranked five competitors with a full growth table; post-fix collapses to one line naming Micron at "≈157%" with the "could not be matched" footer (sub 4 → 0).
- `chain_unhealthy_entity_investigation`, `chain_apple_suppliers_high_margin`, `chain_macro_event_market_reaction`, `chain_tsla_post_earnings_news`: all swap a partial-but-substantive frozen answer for a flatter *"I cannot find evidence / no data was found"* refusal-style fallback (soft-band <60).

**Sub-pattern (c) — hedge/refuse:** present but minor; folded into (a) above (the chain_* fallbacks read as refusals).

**Sub-pattern (d) — different/contradicted numbers:** rare, **one** clear case and it is a *date-window shift*, not a fabrication:
- `da_apple_revenue_fy2024q4_precision`: frozen said `$102.500B` (FY-Q4-2024 ending Sep 28 2024, GROUNDING_FLOOR); post-fix says `$102.470B` but re-anchored to *"fiscal Q4 **2025**… ending Sep 28 **2025**"* and now contradicts the sample `revenue=111.184B` (Δ 8.7B) → GROUNDING_CONTRADICTED. The model silently advanced the as-of year. The same 2024→2025 date drift appears in `da_aapl_pe_dec2024` ("Dec 31 **2025**"), `da_msft_fy2024q4` ("Q4 **2025**"), `da_nvda_amd_compare_fy2024q3` ("**2025**") — a secondary contributing pattern, but the headline driver remains citation stripping.

### Read in one sentence

The chat-fix changed citation/attribution behaviour: answers now **emit numbers without per-claim inline citation tags** (and append a blanket "could not be matched" footer), so correct content reads as ungrounded and trips GROUNDING_FLOOR — and in the worst cases the same change tips the model into a **tool-empty "cannot find evidence" fallback** that drops the numbers altogether. It is overwhelmingly an attribution/citation-attachment regression, not a numeric-accuracy regression.
