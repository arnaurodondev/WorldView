# Relation-Extraction Quality Audit — Are We Too Strict, or Is the Extractor Weak?

**Date:** 2026-06-13
**Author:** Principal NLP Engineer (read-only investigation)
**Scope:** the relation-extraction prompt (`libs/prompts/src/prompts/extraction/deep.py`), the predicate registry (`intelligence_db.relation_type_registry` + `RelationType` enum), the loss funnel from `relation_evidence_raw` → `relations`, and a hand-read sample of zero-relation news articles (silver text from MinIO `worldview-silver`).
**Status:** Root cause established. **NO** code / prompt / schema / data / git changes. All measurements read-only via `docker exec worldview-postgres-1 psql` and `mc cat`.
**Builds on:** `2026-06-13-kg-edge-count-investigation.md` and `2026-06-13-kg-entity-edge-ratio-deepdive.md` (read those first — they establish the 16,817-entity / 4,750-edge headline and the 4,026 mentioned-but-isolated / 3,288 never-in-evidence cohorts that this audit explains).

---

## 0. TL;DR verdict

The graph under-extracts relations because **the LLM never proposes a relation for most articles it processes — not because gates or a narrow predicate vocabulary drop good relations.** The evidence is unambiguous at both the aggregate and the per-article level:

* **Predicate vocabulary drops ZERO relations.** Of 76,869 `relation_evidence_raw` rows, **0** carry an unknown/unmapped predicate (`canonical_type IS NULL` = 0; `canonical_type NOT IN registry` = 0). The 32-type registry exactly matches the prompt's 32-type allow-list. The extractor only ever emits in-vocabulary predicates. The "too strict / closed vocabulary" hypothesis is **REJECTED** as a driver.
* **The confidence gate drops essentially nothing** (112 of 76,869 rows < 0.5; all materialized relations ≥0.9). Already known from the prior audits; re-confirmed.
* **The dominant loss is upstream of all gates:** of **17,308 news articles that ran the deep-extraction LLM** (full_pipeline tier), only **5,040 (29.1%) produced even one narrative relation; 12,268 (70.9%) produced ZERO.** The relation array came back empty.
* **Hand-reading the zero-relation cohort confirms recall failure, not absence of signal:** of **8 substantial news articles** that ran the LLM, had ≥2 resolved entities (both endpoints in the prompt allow-list), and produced no relation, **5 plainly state an extractable in-taxonomy relationship the extractor missed**, 3 are genuinely low-signal (numeric/thematic). The misses include textbook cases — *"JPMorgan Raises its Price Target on Vistra"*, *"Boston Scientific (NYSE:BSX)"* (`listed_on`), *"Lululemon cut its full-year revenue guidance"*.

**One-line root cause:** the deep-extraction prompt/model **under-elicits recall** — it returns an empty `relations` array for ~71 % of articles it sees, even when the text states relations whose both endpoints are in the supplied entity list. The predicate vocabulary and the gates are not the binding constraint.

---

## 1. The relation-extraction prompt (`DEEP_EXTRACTION`, v1.4)

**Location:** `libs/prompts/src/prompts/extraction/deep.py`. **Invoked from:** `services/nlp-pipeline/src/nlp_pipeline/application/blocks/deep_extraction.py:_build_prompt` → `DEEP_EXTRACTION.render(entities=..., text=...)`. Runs only for **MEDIUM and DEEP** routing tiers (`should_run_deep_extraction`); LIGHT/SUPPRESS articles get an empty result by design and can never produce a relation.

**Model:** `Qwen/Qwen3-235B-A22B-Instruct-2507` via DeepInfra (`extraction_api_model_id`, `config.py:132`). **Params** (`libs/ml-clients/src/ml_clients/adapters/deepseek_extraction.py`): `temperature=0.0`, `max_tokens=4096`, **`reasoning_effort="none"`** (chain-of-thought disabled), JSON-object response format.

### 1.1 Limiting instructions (quoted)

The prompt is **precision-first** and contains several instructions that actively discourage recall:

1. **Anti-fabrication framing dominates the opening:**
   > "FABRICATION IS PROHIBITED. Every value you write must be directly traceable to a verbatim phrase in the document. If you cannot point to the exact words, do not include the item. **An empty array is a correct and expected output when nothing qualifies.**"

   This explicitly blesses the empty array as the safe answer — exactly what the model returns 71 % of the time.

2. **Hard entity allow-list (the single strongest constraint):**
   > "ENTITY CONSTRAINT — THIS IS STRICT: entity_ref / subject_ref / object_ref values MUST be an exact string from this list: `{entities}` … If a name appears in the text but is NOT in this list, you MUST omit it entirely. Do NOT paraphrase, abbreviate, or guess a close match."

   The `{entities}` list is the document's **NER mention surface forms** (`mention_names = [m.mention_text for m in mentions]`, deduped). A relation survives only if **both** endpoints were emitted by GLiNER *and* match verbatim. Any relation to an entity GLiNER missed, or whose surface form differs, must be dropped by the model. (Note: in the sampled misses the endpoints *were* in the list — so this constraint is a contributing pressure, not the whole story.)

3. **Confidence floor encourages omission:**
   > "Below 0.50 = do not include; omit the item entirely."

4. **Closed predicate vocabulary, explicitly closed:**
   > "predicate (relation type — pick the closest match, **no other values allowed**)" — followed by 32 inline-described types.

5. **No cap on relation count** (good — there is no "extract at most N" instruction) and **no intra-sentence-only restriction** (good). The few-shot examples are all single-sentence, intra-sentence relations, which may bias the model toward only the most explicit, single-clause relations.

**Net:** the prompt is heavily tuned for **precision** (no fabrication, strict allow-list, omit-if-unsure) with **no counter-pressure for recall** (no "extract every relationship you can ground", no minimum, no encouragement to cover multi-sentence or implied-but-grounded relations). With `reasoning_effort=none`, the model also has no scratchpad to enumerate candidate pairs before deciding. The result is a model that defaults to the empty array.

---

## 2. The predicate vocabulary (count + list + gap analysis)

**Count: 32 canonical types.** `relation_type_registry` holds 32 rows; the prompt enumerates the same 32; the `RelationType` enum (`domain/enums.py`) exposes 16 of them as typed code constants. **The registry and the prompt are in sync** (no drift).

### 2.1 Full list

`acquired_by, analyst_rating, appointed_as, board_member_of, competes_with, corporate_action, credit_rating, divested_from, downgraded_by, earnings_guidance, earnings_released, employs, filed_lawsuit_against, has_executive, headquartered_in, investment_in, is_in_industry, is_in_sector, issues_debt, listed_on, market_share_claim, operates_in_country, owns_stake_in, partner_of, price_target, produces, regulates, reported_revenue_of, revenue_from_country, sentiment_signal, subsidiary_of, supplier_of`

### 2.2 Is the vocabulary too narrow for financial news?

**No — it is adequately broad.** It covers competitor (`competes_with`), customer/supplier (`supplier_of`), regulatory (`regulates`), litigation (`filed_lawsuit_against`), executive moves (`has_executive`, `appointed_as`, `board_member_of`, `employs`), products (`produces`), analyst actions (`analyst_rating`, `price_target`, `downgraded_by`, `credit_rating`), M&A (`acquired_by`, `divested_from`, `owns_stake_in`, `investment_in`), and capital structure (`issues_debt`, `corporate_action`). There is even a catch-all (`sentiment_signal`). The few plausibly-missing types (e.g. an explicit `customer_of`, `joint_venture`, `partnership_ended`) are narrow refinements, not large coverage holes.

### 2.3 Decisive proof the vocabulary is not the bottleneck

| Metric (over 76,869 raw evidence rows) | Count |
|---|---|
| Rows with `canonical_type IS NULL` (predicate unknown → proposed, never registry-matched) | **0** |
| Rows with `canonical_type NOT IN relation_type_registry` | **0** |
| Rows with `extraction_confidence < 0.5` | 112 |
| Distinct `canonical_type` values present | 29 of 32 |

Every relation the extractor *did* propose mapped cleanly to a registry type (Block 11 canonicalization: exact-match → ANN soft-map ≤0.35 → propose). **There is no cohort of "good relations dropped because their predicate was out-of-vocabulary."** The closed vocabulary is not costing recall.

---

## 3. The loss funnel — where relations are lost

Two distinct funnels matter. **(A)** the per-article funnel (does the LLM emit anything?) is where the loss is; **(B)** the raw-evidence→edge funnel (the gates) is small and already documented.

### 3.1 Funnel A — article → proposed relation (the real loss)

```
News articles routed (routing_decisions) .......................... 21,382
  ├─ LIGHT tier (no deep extraction by design) ...................... 3,944   → 0 relations possible
  └─ full_pipeline (DEEP+MEDIUM — LLM extraction RAN) ............... 17,308
        ├─ produced ≥1 narrative relation ........................... 5,040   (29.1%)
        └─ produced ZERO relations .................................. 12,268   (70.9%)  ← THE LOSS
              └─ of these, ran LLM + ≥2 resolved entities ........... 5,779    (≥2 in-list endpoints available, still nothing)
```

The headline 76,869 raw-evidence rows are **misleading**: **62,718 (81.6%) are `is_in_sector`** rows produced by *structured* enrichment (one financial_instrument → sector per fundamentals doc, 62,705 distinct docs), **not** by the news LLM. The genuine **narrative (non-`is_in_sector`) extraction is only 14,151 rows across 5,040 distinct news docs.** So the LLM's true output is ~14k relations over 17.3k articles it processed.

### 3.2 Funnel B — raw evidence → materialized edge (the gates; small loss)

```
relation_evidence_raw rows ........................................ 76,869
  ├─ entity_provisional=true (endpoint not yet canonical, deferred)  4,834   (legitimate backlog)
  ├─ self-loops (subject = object, dropped by design BP-384/385) ... 1,179
  ├─ predicate unknown / not in registry .......................... 0       ← vocabulary drops nothing
  ├─ confidence < threshold ....................................... ~0      ← gate never binds (all edges ≥0.9)
  └─ DISTINCT (subj, type, obj) triples ........................... 12,014
        └─ materialized as edges (relations) ...................... 4,750
              └─ residual H3 materialization-gap bug .............. 1,633   (BP-662 family; back-fill keys on wrong flag)
```

### 3.3 Loss attribution (ranked by magnitude)

| Where relations are lost | Mechanism | Magnitude |
|---|---|---|
| **NEVER PROPOSED** | LLM returns empty `relations` array for the article | **12,268 of 17,308 articles (71%)** — the dominant loss |
| Aggregation / dedup collapse | 8.19 evidence rows → 1 edge (cross-document corroboration) | 76,869 raw → 12,014 distinct triples (expected, healthy) |
| Self-loop removal | subject = object dropped by design | 1,179 evidence rows |
| **Materialization-gap bug (H3/BP-662)** | back-fill `_unblock_provisional_evidence` keys on `entity_provisional=true`, misses entity-existence-gate skips | **1,633 edges** recoverable |
| Provisional deferral | endpoint not canonical yet | 4,834 rows (will materialize when entity lands) |
| Invalid-predicate / vocabulary | — | **0** |
| Confidence threshold | — | **~0** |

**Relations-per-article rate:** narrative relations per full_pipeline article = 14,151 / 17,308 = **0.82 raw relations/article**; **0.29 articles yield ≥1 relation**; final edges per processed article = 4,750 / 17,308 = **0.27 edges/article**. A financial-news corpus of this kind should comfortably exceed 1–3 grounded relations per substantive article — the rate is low because most articles return nothing.

---

## 4. Sampled-article verdicts (the decisive evidence)

Articles selected: full_pipeline (LLM ran), ≥2 resolved entities, **zero** relation evidence. Body text read verbatim from MinIO `worldview-silver/content-store/canonical/<doc>/body.json`. The crux cohort is **5,779 articles**, overwhelmingly real news (eodhd_ticker_news 3,323 / finnhub 1,244 / eodhd 978 / sec_edgar 206 / newsapi 25) — **not** EDGAR boilerplate.

| # | doc (short) | Title | Resolved entities (in allow-list) | Extractable in-taxonomy relation present? | Verdict |
|---|---|---|---|---|---|
| 1 | 019eb191 | "Is GE Vernova (GEV) A Good Stock To Buy Now?" | JPMorgan, Vistra, US, Europe, Asia, Middle East, Africa | **YES** — *"JPMorgan Raises its Price Target on Vistra (VST)"* = `price_target`(JPMorgan, Vistra), both endpoints resolved; GEV operates in US/Europe/Asia/etc = `operates_in_country` | **MISSED** |
| 2 | 019eb279 | "FRACTURE IDE … Boston Scientific Valuation" | Boston Scientific, NYSE | **YES** — *"Boston Scientific (NYSE:BSX)"* = `listed_on`(BSX, NYSE); SEISMIQ 4CE catheter = `produces` | **MISSED** |
| 3 | 019eb37f | "Stitch Fix, fuboTV, Sabre Stocks Trade Down" | Lululemon, + several tickers | **YES** — *"Lululemon … cut its full-year revenue guidance to \$11.0–\$11.15B from \$11.35–\$11.5B"* = `earnings_guidance` / GUIDANCE_CUT claim | **MISSED** |
| 4 | 019eb3df | "3 Reasons ITW is Risky…" | Illinois Tool Works, S&P 500, Wall Street | **WEAK** — ITW "General Industrial Machinery" → `is_in_industry` arguably; rest is numeric vs-index comparison | **MISSED (borderline)** |
| 5 | 019eb515 | "Mastercard: Gen Z and Financial Confidence" | Mastercard, BNPL | NO — thematic research report; no grounded entity-entity relation | no-signal |
| 6 | 019eb6d2 | "JPMorgan Chase (JPM) Stock Moves -1.12%" | JPMorgan, S&P 500, Dow, Nasdaq | NO — pure price-move vs indices; co-mention only | no-signal |
| 7 | 019eb64a | "3 Industrials Stocks with Questionable Fundamentals" | S&P 500, + tickers | NO — list/comparison, numeric only | no-signal |
| 8 | 019eb265 | "2 Growth Stocks Set to Flourish…" | StockStory, + tickers | NO — generic screener prose | no-signal |

(Earlier sample of SEC ABS filings — docs `019e6b00…` "Asset-Backed Securities / CF Office / DE" — were genuinely no-signal form headers; excluded from the news verdict above.)

**Sample verdict: 5 of 8 substantive news articles missed a real, in-taxonomy, both-endpoints-in-list relation** (4 clear + 1 borderline; conservatively **4 of 8 clear-cut**). 3 of 8 are legitimately low-signal (numeric price-move / thematic). Critically, the misses (#1 `price_target`, #2 `listed_on`, #3 `earnings_guidance`) are among the *easiest, most explicit* relations in the taxonomy, with verbatim trigger phrases and both entities already in the supplied allow-list — exactly the cases a precision-first prompt should catch. The model returned an empty array anyway.

---

## 5. ROOT-CAUSE verdict (ranked)

| Rank | Cause | Verdict | Evidence |
|---|---|---|---|
| **1** | **Prompt under-elicits recall** (precision-first framing, "empty array is correct", omit-if-unsure, no recall counter-pressure, `reasoning_effort=none` removes candidate-pair enumeration) | **PRIMARY** | 71 % of processed articles return zero relations; 4–5/8 hand-read articles missed explicit relations with in-list endpoints |
| **2** | **Model capability / configuration** (Qwen3-235B at `reasoning_effort=none`, `temperature=0`, single pass) | **SECONDARY (entangled with #1)** | Disabling reasoning + a precision-skewed prompt jointly suppress recall; the model is large enough that the prompt/config is the more likely lever |
| **3** | **Entity-existence / materialization gating** (H3 / BP-662 back-fill) | **REAL BUT SMALL** | 1,633 edges recoverable; does not explain the 12,268 never-proposed articles |
| **4** | **Genuinely sparse signal** | **MINORITY** | 3/8 sampled articles legitimately have no entity-entity relation (price-move/thematic) — real but not the bulk |
| **5** | **Closed / narrow predicate vocabulary** | **REJECTED** | 0 of 76,869 evidence rows dropped for unknown/out-of-registry predicate; 32-type vocabulary covers competitor/customer/regulatory/litigation/exec/product |

---

## 6. Ranked fixes (with expected impact)

1. **Rebalance the prompt toward recall (highest leverage, lowest cost).** Keep the no-fabrication rule but **remove the "empty array is a correct and expected output" sentence** and add an explicit recall directive, e.g. *"For every pair of entities from the list that the text connects — even across sentences — emit the relation. Omit only if no grounded relationship exists. Most financial articles contain at least one relation."* Add a few-shot **multi-sentence** and **multi-relation** example, and a counter-example showing a missed `listed_on`/`price_target`. **Expected impact: large** — directly attacks the 71 % empty-array rate; plausibly 2–4× the articles-with-≥1-relation rate. Validate on a held-out set of the 5,779 crux docs.

2. **Re-enable lightweight reasoning for extraction** (`reasoning_effort` low instead of `none`, or a two-step "list candidate entity pairs, then classify" prompt). Lets the model enumerate pairs before committing. **Expected impact: medium-high**, at some latency/token cost — A/B against fix #1 since they overlap.

3. **Fix the H3 / BP-662 materialization back-fill** (periodic reconciler that re-materializes any `relation_evidence_raw` triple where both endpoints are now canonical and no `relations` row exists, **independent of `entity_provisional`**). **Expected impact: bounded +1,633 edges** (relations 4,750 → ~6,383). Mechanical, no recall change.

4. **Loosen the entity allow-list pressure** — instead of demanding verbatim membership, supply the entity list as *preferred* anchors but allow the model to surface a relation to a clearly-named entity not in the list (then resolve it downstream via the provisional path that already exists). Reduces silent drops when GLiNER misses an endpoint or the surface form differs. **Expected impact: medium** (the sampled misses had in-list endpoints, so this is secondary to #1).

5. **Predicate expansion: not warranted now.** The vocabulary drops nothing; expanding it before fixing recall would add types with no rows. Revisit only after #1/#2 raise recall and `relation.type.proposed.v1` starts surfacing recurrent unknown types.

---

## 7. Appendix — key queries

```sql
-- Predicate vocabulary drops nothing (intelligence_db)
SELECT count(*) total,
       count(*) FILTER (WHERE canonical_type IS NULL) predicate_unknown,
       count(*) FILTER (WHERE canonical_type IS NOT NULL
                        AND canonical_type NOT IN (SELECT canonical_type FROM relation_type_registry)) not_in_registry,
       count(*) FILTER (WHERE extraction_confidence < 0.5) conf_below_0_5
FROM relation_evidence_raw;             -- 76869 / 0 / 0 / 112

-- Structured vs narrative split
SELECT count(*) FILTER (WHERE canonical_type='is_in_sector') sector,
       count(*) FILTER (WHERE canonical_type<>'is_in_sector') narrative
FROM relation_evidence_raw;             -- 62718 / 14151

-- Article funnel (nlp_db routing_decisions; tiers are lowercase)
SELECT COALESCE(final_routing_tier,routing_tier) tier, count(DISTINCT doc_id)
FROM routing_decisions GROUP BY 1;       -- deep 8843 / medium 8595 / light 3944
SELECT processing_path, count(DISTINCT doc_id) FROM routing_decisions GROUP BY 1;
                                         -- full_pipeline 17308 / section_embeddings_only 4074

-- Cross-DB: full_pipeline docs that produced ≥1 narrative relation = 5040 (29.1%)
--   (doc-id list intersection of routing_decisions[full_pipeline]
--    with relation_evidence_raw[canonical_type<>'is_in_sector'])

-- Crux cohort: full_pipeline + zero relation + ≥2 resolved entities = 5779
--   source_type: eodhd_ticker_news 3323 / finnhub 1244 / eodhd 978 / sec_edgar 206 / newsapi 25
```
