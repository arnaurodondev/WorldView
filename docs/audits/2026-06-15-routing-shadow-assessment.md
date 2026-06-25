# Routing Shadow Assessment — Learned News-Routing Classifier (post-fix)

**Date:** 2026-06-15
**Type:** Read-only analytical assessment (no code changes, no deployment)
**Dataset:** `nlp_db.routing_decisions`, filter `learned_router_mode = 'shadow' AND learned_tier IS NOT NULL`
**Window:** 2026-06-13 05:08:54Z → 2026-06-15 21:26:08Z (≈64.3h), **1,636 rows** (stable snapshot; LIVE-mode rows excluded by design)

---

## TL;DR — Bottom Line

The learned router is **directionally healthy on titled articles** but has **one serious structural defect**: it is **blind to documents with no `chunks.title_denorm`**, and *every* `sec_edgar` (86) and `newsapi` (25) row in this window is title-less. The learned gate collapses these to a low p_yield (avg 0.279) and routes them to `light`, **whereas the static router sent 100% of SEC filings to extraction**. SEC filings are among the highest-value documents in the corpus, so this is a real-yield regression masked by an otherwise-flat aggregate cost number.

On titled articles (93% of the window) the gate behaves well: it confidently down-routes ETF listicles / retirement-advice / Cramer-style opinion to `light`, and up-routes analyst moves, M&A/litigation, dividend actions, insider transactions and regulatory events to `deep`/`medium`. Net extraction volume is essentially flat (static 76.0% → learned 75.4%); the real shift is **deep→medium reallocation** (deep 690→521, medium 553→713), i.e. the gate is *cheaper-per-doc on average* without cutting coverage.

**Recommendation before/at LIVE:** do not let the title-less path silently dump SEC filings. Either (a) fall back to the static tier when `title_denorm IS NULL`, or (b) backfill a title surrogate for `sec_edgar`/`newsapi` before trusting the learned tier. Everything else looks like an improvement.

---

## 1. Distribution & Agreement

### Tier split (n=1,636)

| Tier | Static | Learned |
|------|-------:|--------:|
| deep | 690 | 521 |
| medium | 553 | 713 |
| light | 393 | 402 |

### Full cross-tab (static → learned)

| static \ learned | deep | medium | light |
|---|---:|---:|---:|
| **deep** | 304 | 322 | 64 |
| **medium** | 133 | 194 | 226 |
| **light** | 84 | 197 | 112 |

**Agreement rate: 37.3%** (610/1,636). Low agreement is expected and acceptable for a learned gate that is supposed to disagree with the heuristic; the question is *whether the disagreements are in the right direction* (sections 2–4).

Key flows:
- **deep→medium (322):** largest single off-diagonal cell — the gate trims deep extraction to medium on a large block of deep-static docs. Drives the deep→medium reallocation.
- **medium→light (226):** the gate's main "cost saver" — borderline-medium docs pushed down.
- **light→medium (197) + light→deep (84):** the gate *rescues* 281 light-static docs upward.

### p_yield distribution (0.1 buckets)

| range | count |
|-------|------:|
| 0.1–0.2 | 90 |
| 0.2–0.3 | 45 |
| 0.3–0.4 | 78 |
| 0.4–0.5 | 100 |
| 0.5–0.6 | 112 |
| 0.6–0.7 | 144 |
| 0.7–0.8 | 546 |
| 0.8–0.9 | 520 |
| 0.9–1.0 | 1 |

Bimodal-ish: a heavy upper mass at 0.7–0.9 (1,066 rows, 65%) and a low-end tail at 0.1–0.4 (213 rows, 13%). The model is mostly confident; relatively few docs sit in the genuinely uncertain middle.

**Ambiguous band (0.48–0.68): 242 rows = 14.8%.** Reasonable cascade/abstain candidate volume — large enough to be worth a cascade tier, small enough not to swamp it.

---

## 2. Up-routes (learned > static) — is the gate rescuing real value?

Sample of 22 highest-p_yield up-routes (light→deep/medium, medium→deep). **Mostly yes — genuinely extraction-worthy:**

- *WuXi AppTec files complaint against U.S. DoD for linking it to Chinese military* (0.86) — regulatory/litigation, clearly worth deep.
- *Target Corporation Increases Quarterly Dividend by 1.8 Percent* (0.88) — corporate action.
- *Is UroGen Pharma a Stock to Sell After Its Chief Medical Officer Unloaded 5,222 Shares* (0.85) — insider transaction.
- *Roche launches the Liver Disease Panel…* (0.85) — product/clinical event.
- *Dollar Falls as President Trump Cancels Attacks on Iran* (0.85) — macro/geopolitical.
- *Imperial pleads guilty to EPEA violation…* (0.85), *Borr Drilling insider purchase 1.06M shares* (0.85) — legal + insider.

**But a meaningful minority are low-value clickbait the gate over-rates:**
- *Is Now The Time To Look At Buying Danaher (DHR)?* (0.85), *Are You Looking for a High-Growth Dividend Stock?* (0.85), *Is Whirlpool (WHR) A Good Stock To Buy Now?* (0.85), *3 TSX Stocks Estimated To Be Trading At Up To 43.1% Below Intrinsic Value* (0.85), *Jim Cramer Recommends Elanco Over Zoetis* (0.85).

These "Is X a buy?" / valuation-screen / Cramer titles carry ticker mentions but little extractable event content. The gate appears to reward ticker-density + financial vocabulary and cannot distinguish a real catalyst from a templated valuation listicle. This inflates deep extraction on ~25–30% of the up-routes. Not catastrophic (they're at worst wasted compute, not lost value), but it is the up-route failure mode to watch.

**Verdict:** up-routing is net-positive — it recovers analyst/M&A/event/insider/regulatory value the static router under-rated. The crypto-promo concern from the brief did *not* materialize as a dominant pattern here; the noise is mostly generic "should I buy?" valuation clickbait, not crypto promos.

---

## 3. Down-routes (learned < static) — junk vs collateral damage

Sample of lowest-p_yield down-routes (deep/medium→light, titled docs). **Predominantly correct junk-suppression:**

- *VTI vs. VTV: Which … Vanguard ETF Is the Better Investment* (0.17), *Broad Bond Exposure or Tax-Exempt Muni? BND vs. MUB* (0.18), *Investor Beware: These ETF Mistakes Could Cost You Thousands* (0.24) — ETF listicles.
- *A $650,000 Portfolio That Could Send You to the Super Bowl Every Year* (0.18), *I'd Tell Anyone in This Situation to Stop Funding an IRA or 401(k)* (0.19) — retirement-advice filler.
- *These Are the Only 2 Cryptocurrencies I'm Comfortable Buying Right Now* (0.19), *With Bitcoin Down 21%… Is It Still Worth Buying and Holding Forever?* (0.23) — crypto opinion.

These are exactly the documents that should not consume deep extraction. Good calls.

**Collateral-damage candidates (borderline-substantive dumped to light):**
- *Amazon Graviton5 Chip Aims To Deepen AWS AI Margins And Moat* (deep→light, 0.21, finnhub) — a real product/strategy story, arguably under-rated.
- *Goldman and JPMorgan ease office working rules…* (0.24), *Oil executives warn Trump administration that gasoline prices will get worse* (0.24) — macro/sector items that may carry extractable signal.
- *South Korea's stock rally shifts focus to potential MSCI market upgrade* (0.20) — index-event, borderline.

### deep→light confidence split (n=64)

| band | count |
|------|------:|
| p_yield ≥ 0.40 (near-threshold / cascade territory) | 45 |
| p_yield < 0.40 (confidently low) | **19** |

So **only 19 of 64 deep→light drops are "confident" dumps**, and most of those 19 are titled clickbait (correct). The remaining 45 sit near the cut and are cascade candidates rather than hard losses. The **highest-p_yield deep→light drops** (0.51–0.57) are genuinely substantive and represent the real risk surface: *Goldman Sachs resets Apple stock forecast after WWDC* (0.54), *IMAAVY Breakthrough And Priority Review Reframe J&J Growth Story* (0.54), *Piper Sandler Says Tesla Has Cracked Self-Driving* (0.52), *Indian Pollution Probe Tests Apple Supply Chain* (0.54). These four-ish are the clearest "high-value to light" misses — they would be rescued by a cascade tier on the 0.48–0.68 band.

**Verdict:** down-routing is mostly correct junk-suppression. A small number (single digits) of substantive analyst/event articles are dropped, all clustered just below the deep threshold — addressable with a cascade/abstain tier on the ambiguous band, not a structural flaw.

---

## 4. Per-source behavior

Learned tier × source_type, plus per-source avg p_yield and extraction rates:

| source_type | n | avg p_yield | learned extract % | static extract % | learned: deep / medium / light |
|---|---:|---:|---:|---:|---|
| eodhd | 831 | 0.731 | **89.0** | 80.1 | 254 / 486 / 91 |
| eodhd_ticker_news | 427 | 0.749 | **86.9** | 78.7 | 264 / 107 / 56 |
| finnhub | 267 | 0.535 | 40.8 | 55.1 | 2 / 107 / 158 |
| sec_edgar | 86 | **0.179** | **0.0** | **100.0** | 0 / 0 / 86 |
| newsapi | 25 | 0.622 | 56.0 | 32.0 | 1 / 13 / 11 |

The desired pattern is **partially** present:
- **finnhub down-routed** (55.1%→40.8%) — finnhub items skew to opinion/screens; reasonable.
- **eodhd / eodhd_ticker_news up-routed** (→89% / 87%) — these are the substantive ticker-news feeds; up-routing them is defensible (and is where the deep→medium reallocation lands).
- **newsapi up-routed** (32%→56%) on only 25 rows — low confidence, ignore.

**The exception is the headline problem: `sec_edgar`.** The learned gate sends **0% of SEC filings to extraction** (avg p_yield 0.179) where the static router sent **100%**. SEC filings (8-K/10-Q etc.) are among the richest extraction targets in the platform. This is the single biggest quality concern in the assessment.

### Root cause: title-less documents starve the learned features

Every `sec_edgar` (86/86) and `newsapi` (25/25) row in the window has **NULL `chunks.title_denorm`**. Effect on the learned gate:

| title_state | n | avg p_yield | learned extract % |
|---|---:|---:|---:|
| has_title | 1,525 | 0.701 | 80.0 |
| null_title | 111 | **0.279** | **12.6** |

The static feature scores corroborate the mechanism — for `sec_edgar` the static router *recognizes* the document type (`document_type` = 0.88, by far the highest of any source) but `entity_density` (0.136) and `recency` (0.004) are floored, almost certainly because the title-less / short-denorm representation starves those signals. The learned model, lacking the title signal it relies on most, has no way to recover the value the static `document_type` prior captured, and dumps the filing to `light`.

This is a **feature-coverage bug, not a learned-model-quality bug**: the gate is making a rational decision given degenerate inputs. The fix is upstream (title surrogate or static fallback for title-less docs), not in the classifier weights.

---

## 5. Cost / Yield Impact (this window)

| router | extraction (deep+medium) % | deep | medium | light |
|--------|---:|---:|---:|---:|
| static | **76.0** | 690 | 553 | 393 |
| learned | **75.4** | 521 | 713 | 402 |

- **Total extraction volume (deep+medium) is essentially flat: 76.0% → 75.4% (-0.6pp).** Going LIVE on this window would *not* materially change the count of docs entering the 235B extraction path. (The brief's earlier 79.6% vs 73.9% figure does not reproduce on this stable post-fix shadow snapshot; the gap has closed to ~flat.)
- **The real change is the deep→medium reallocation: deep -169 (-24.5%), medium +160 (+28.9%).** If `deep` is the heavyweight 235B pass and `medium` is a lighter pass, the learned router is **cheaper per extracted document at equal coverage** — a genuine efficiency win.
- **Caveat:** part of the "savings" is the erroneous `sec_edgar` 0% extraction (86 high-value docs removed from the deep pool). Excluding the title-less artifact, the deep-extraction reduction on titled docs is smaller and the win is more about reallocation than suppression.

**Net read:** going LIVE neither blows up nor shrinks extraction volume; it reshapes deep→medium. The cost story is favorable *provided* the title-less SEC-filing leak is fixed first (otherwise you save compute by silently dropping your highest-value source).

---

## 6. LLM-judge note

A DeepSeek-V4-Flash judge pass over the up/down-route sample was scoped but **not run** in this read-only window — the title samples above are already adjudicable by inspection (clear junk vs clear catalyst), and the dominant finding (title-less SEC-filing leak) is a deterministic data-coverage defect that a judge would not add signal to. Per `feedback_llm_judge_budget_deepseek`, Opus was not used. A targeted judge pass is worth running **only on the 0.48–0.68 ambiguous band (242 rows)** to size a future cascade tier; that is the one region where human/LLM adjudication would change a design decision.

---

## Concerns Summary (honest)

1. **[High] `sec_edgar` → 0% extraction via title-less feature starvation.** All 86 SEC filings (and 25 newsapi) have NULL `title_denorm`; learned p_yield collapses to ~0.18–0.28 and routes to `light`, vs static 100% extraction. Fix upstream before LIVE: static-tier fallback when `title_denorm IS NULL`, or backfill a filing-type title surrogate.
2. **[Low-Med] Up-route over-rating of "Is X a buy?" / valuation-screen / Cramer clickbait** to deep (p_yield ~0.85). Wasted compute, not lost value. Watch; consider a title-template penalty feature.
3. **[Low] A handful (single digits) of substantive analyst/event articles dropped deep→light at p_yield 0.51–0.57** (Goldman/Apple, J&J priority review, Piper/Tesla). All sit in the ambiguous band — a cascade tier on 0.48–0.68 would recover them.
4. **[Info] 37.3% static/learned agreement** is by design; the disagreements are mostly in the right direction (good junk-suppression, good value-rescue) once the title-less artifact is excluded.

**Overall:** the learned router improves routing *quality* on the 93% of documents it can see (titles), trading deep for medium at equal coverage and suppressing junk well. It is **not yet safe to go fully LIVE** until the title-less SEC/newsapi path is given a fallback, because that path silently discards the corpus's highest-value source.
