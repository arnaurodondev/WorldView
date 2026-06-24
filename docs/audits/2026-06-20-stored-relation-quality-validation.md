# Stored Relation Quality Validation — 2026-06-20

**Question.** A benchmark A/B (`docs/audits/2026-06-18-relation-precision-gates.md`)
claimed the current extraction model (`openai/gpt-oss-120b@medium`) produces
near-perfect relations: **judge precision 5.0/5, 0.0 fabrication/article, adherence
5.0/5**. Does the quality of the **actually-stored** relations in the production
knowledge graph (`intelligence_db.relations`) match that benchmark, or is the
benchmark optimistic?

**Method (one line).** Re-judge a stratified sample of *stored* `relations` +
`relation_evidence` rows with an independent budget judge
(`deepseek-ai/DeepSeek-V4-Flash`), segmented by extraction-model era, asking only:
*does the stored evidence text actually ASSERT the stored triple?*

---

## Headline answer — NO, reality does not match the benchmark

| | Benchmark claim (gpt-oss, fresh extraction) | This audit (gpt-oss era, **stored** graph) |
|---|---|---|
| Precision / support | **5.0/5 ≈ "near-perfect"** | **SUPPORTED = 67/243 = 27.6%** (95% CI 22.0–33.2%) |
| Fabrication | **0.0 / article** | UNSUPPORTED = 28/243 = 11.5% |
| Direction/schema adherence | **5.0/5** | WRONG_DIRECTION 7.8% + WRONG_PREDICATE 7.4% |

The **RECENT (gpt-oss-120b) cohort of the stored graph is SUPPORTED only 27.6% of the
time** — i.e. roughly **3 in 4 stored relations are NOT asserted by their own evidence
text.** That is a very large gap from the benchmark's 5.0/5. The benchmark is
**optimistic**: it measured a tiny (17-article / 32-relation), time-correlated sample of
*freshly extracted prompt output*, not the materialised graph the product actually reads.

Critically, the model-switch did **not** materially improve stored quality: the OLDER
(Qwen) cohort scores **29.5%** SUPPORTED — statistically indistinguishable from the
gpt-oss 27.6% (overlapping CIs). The benchmark's "clear multi-dimension win" does not
appear in the stored data.

---

## Corpus segmentation

Era split by `relations.created_at` (gpt-oss switch ≈ 2026-06-16, PLAN-0111):

| Metric | Value |
|---|---|
| Total relations | **13,449** |
| RECENT cohort (`created_at >= 2026-06-16`, gpt-oss) | **6,012** |
| OLDER cohort (`created_at < 2026-06-16`, Qwen) | **7,437** |
| Relations `created_at` range | 2026-05-24 .. 2026-06-20 |
| Total `relation_evidence` rows | 119,590 |
| Evidence concentrated in | 2026-05 (74k) + 2026-06 (45k) |

Per-predicate distribution (recent | older | total), top predicates:

| predicate | recent | older | total |
|---|---|---|---|
| operates_in_country | 704 | 1219 | 1923 |
| listed_on | 562 | 935 | 1497 |
| competes_with | 282 | 981 | 1263 |
| partner_of | 427 | 710 | 1137 |
| analyst_rating | 636 | 313 | 949 |
| has_executive | 344 | 457 | 801 |
| headquartered_in | 384 | 396 | 780 |
| is_in_sector | 62 | 621 | 683 |
| regulates | 269 | 317 | 586 |
| produces | 237 | 259 | 496 |

(Full 32-predicate table available via `scripts/eval/validate_stored_relation_quality.py`.)

---

## Sample + method

- **382 stored relations** judged (243 RECENT + 139 OLDER), stratified across **all 32
  predicates × both eras** (~8 RECENT + ~5 OLDER per predicate). Far larger than the
  benchmark's 32.
- For each sampled relation we attached its **longest** `relation_evidence.evidence_text`
  (length > 30) and asked the judge whether that text asserts `subject -[predicate]->
  object` with a relation-bearing verb/phrase.
- Independent judge: `deepseek-ai/DeepSeek-V4-Flash` on DeepInfra (the user's budget
  judge), temperature 0, strict-JSON, per-call 429 retry/backoff.
- Five verdicts: **SUPPORTED** (asserted), **CO_MENTION** (entities co-occur, no relation
  asserted), **WRONG_DIRECTION** (subject/object swapped), **WRONG_PREDICATE** (a relation
  exists but a different predicate fits), **UNSUPPORTED** (no support at all).
- Script: `scripts/eval/validate_stored_relation_quality.py`. Raw verdicts:
  `/tmp/wv_verdicts.json` (382 rows, 0 judge errors).

---

## Full verdict breakdown

| Cohort | SUPPORTED | CO_MENTION | WRONG_DIRECTION | WRONG_PREDICATE | UNSUPPORTED | n |
|---|---|---|---|---|---|---|
| **RECENT (gpt-oss)** | **67 (27.6%)** | 111 (45.7%) | 19 (7.8%) | 18 (7.4%) | 28 (11.5%) | 243 |
| **OLDER (Qwen)** | **41 (29.5%)** | 57 (41.0%) | 12 (8.6%) | 8 (5.8%) | 21 (15.1%) | 139 |
| **ALL** | **108 (28.3%)** | 168 (44.0%) | 31 (8.1%) | 26 (6.8%) | 49 (12.8%) | 382 |

**CO_MENTION is the dominant defect (44% of all stored relations)** — entities merely
appear in the same snippet with no relation asserted between them. This is exactly the
**semantic** defect the deterministic precision gate (self-loop / OOV-predicate /
invalid-`listed_on` / common-noun) *cannot* catch: every CO_MENTION relation is
structurally valid (real entities, valid predicate, valid exchange) yet semantically
unfounded. The gate cleaned the *structural* junk; the *semantic* junk is untouched and
dominates.

"Pure noise" (CO_MENTION + UNSUPPORTED, i.e. no real relation of any kind in the
evidence): **RECENT 57.2%, OLDER 56.1%.**

---

## Per-predicate support (RECENT | OLDER | combined)

Worst predicates first (RECENT cohort = current implementation):

| predicate | RECENT | OLDER | combined |
|---|---|---|---|
| corporate_action | 0/8 (0%) | 0/5 (0%) | 0% |
| downgraded_by | 0/8 (0%) | 0/5 (0%) | 0% |
| earnings_released | 0/7 (0%) | 0/5 (0%) | 0% |
| produces | 0/6 (0%) | 0/5 (0%) | 0% |
| regulates | 0/8 (0%) | 0/3 (0%) | 0% |
| earnings_guidance | 0/8 (0%) | – | 0% |
| credit_rating | 0/8 (0%) | 1/3 (33%) | 9% |
| analyst_rating | 1/8 (12%) | 0/5 (0%) | 8% |
| issues_debt | 1/8 (12%) | 0/5 (0%) | 8% |
| market_share_claim | 1/8 (12%) | 0/2 (0%) | 10% |
| revenue_from_country | 1/8 (12%) | 0/5 (0%) | 8% |
| sentiment_signal | 1/8 (12%) | 1/5 (20%) | 15% |
| supplier_of | 1/7 (14%) | 0/5 (0%) | 8% |
| reported_revenue_of | 1/7 (14%) | 1/5 (20%) | 17% |
| operates_in_country | 2/8 (25%) | 1/5 (20%) | 23% |
| is_in_sector | 0/7 (0%) | 4/5 (80%) | 33% |
| ... | ... | ... | ... |
| has_executive | 5/8 (62%) | 4/5 (80%) | 69% |
| divested_from | 5/8 (62%) | 4/5 (80%) | 69% |
| **listed_on** | 4/4 (100%) | 2/3 (67%) | **86%** (best — post-gate cleanup) |

**Pattern: "data-source-as-subject" predicates are catastrophic.** Predicates whose
subject is a research/ratings provider — `analyst_rating`, `credit_rating`,
`downgraded_by`, `price_target`, `sentiment_signal` — score **5/40 = 12%** in the RECENT
cohort, versus **62/203 = 31%** for all other predicates. The extractor routinely emits
e.g. `Zacks -[analyst_rating]-> <company>` from `"<company> is rated Zacks Rank #3"`,
where the evidence describes a *ranking*, not an analyst's rating relation, and frequently
the named "analyst" entity is not even in the sentence.

`listed_on` (86%) is the standout *good* predicate — consistent with the 2026-06-18
deterministic gate + the 442-row invalid-`listed_on` cleanup having scrubbed exactly that
class. This confirms the gate works for the structural defect it targets; it just doesn't
touch the semantic ones.

---

## Concrete defect examples (RECENT / gpt-oss cohort — the current implementation)

### CO_MENTION (44% of corpus — the gate cannot catch these)

- `JPMorgan Chase & Co -[analyst_rating]-> NASDAQ`
  EV: *"On June 11, JPMorgan reiterated an Overweight rating on the stock and maintained
  its price target…"* — JPMorgan rated *a stock*, not NASDAQ; NASDAQ is just the listing
  venue mentioned nearby.
- `Healthcare Foresights -[analyst_rating]-> Pfizer Inc`
  EV: *"The key market players listed in the report … are Novo Nordisk, Eli Lilly, Sanofi,
  AstraZeneca, … Pfizer Inc., Merck…"* — a vendor-list co-occurrence, no rating asserted.
- `Bloomberg Intelligence -[analyst_rating]-> JPMorgan Chase & Co`
  EV: *"…Jamie Dimon said the bank is likely to hire more employees with AI skills…
  Bloomberg reported."* — "Bloomberg reported" ≠ a Bloomberg Intelligence analyst rating.

### WRONG_DIRECTION (subject/object swapped — 7.8%)

- `Mainstream Renewable Power South Africa -[acquired_by]-> A.P. Moller Capital`
  EV: *"A.P. Moller Capital has agreed to **acquire** Mainstream Renewable Power South
  Africa…"* — direction is actually correct here per the judge note, but several genuine
  swaps exist:
- `Adobe Systems Incorporated -[acquired_by]-> Semrush`
  EV: *"…bolstered by the acquisition of SEMrush…"* — Semrush was acquired, not Adobe.
- `Accenture plc -[acquired_by]-> Alfahealth`
  EV: *"Accenture (ACN) has agreed to **acquire** Alfahealth…"* — Accenture is the
  acquirer; the triple says Accenture *was acquired by* Alfahealth.

### WRONG_PREDICATE (a relation exists but a different one fits — 7.4%)

- `ING -[credit_rating]-> MSCI Inc`
  EV: *"ING's **ESG** rating by MSCI has been upgraded from 'AA' to 'AAA'…"* — ESG rating,
  not a credit rating.
- `Leerink Partners -[downgraded_by]-> Johnson & Johnson`
  EV: *"Leerink Partners … **upgraded** the shares to Outperform…"* — an upgrade stored as
  `downgraded_by`, and direction-inverted.
- `Fox Corp Class B -[divested_from]-> Disney Cruise Line`
  EV: *"Fox **sold** its … studio business **to Disney**…"* — divested *to* Disney, of a
  studio, not "from Disney Cruise Line".

### UNSUPPORTED (no support / wrong entity / hallucination — 11.5%)

- `XAI Octagon Floating Rate & Alternative Income Trust -[acquired_by]-> SpaceX`
  EV: *"…through its acquisition of … xAI, SpaceX acquired a large hyperscale operation…"*
  — **entity-resolution error**: the closed-end fund "XAI Octagon" was conflated with Elon
  Musk's "xAI".
- `GLOBE NEWSWIRE -[credit_rating]-> O2`
  EV: *"READING, Reino Unido, June 11, 2026 (GLOBE NEWSWIRE)"* — a press-release dateline
  treated as a credit-rating relation.
- `NVIDIA Corporation -[analyst_rating]-> S&P 500 Index`
  EV: *"Jensen Huang's 'next trillion-dollar company' call … sent shares surging 32.5%…"*
  — no rating, no S&P 500 in the evidence.

---

## Why does the benchmark say 5.0/5 while the stored graph is 28%?

1. **Different object measured.** The benchmark judged *fresh extraction prompt output*
   (`subject_ref` / `object_ref` with the full article and prompt context in front of the
   judge). This audit judges the *stored, materialised, canonicalised* relation against a
   *single* persisted evidence snippet — which is what RAG-chat and the frontend actually
   read. Information is lost between the two (canonicalisation, entity resolution,
   evidence truncation, multi-evidence collapse).
2. **Tiny, time-correlated benchmark sample.** 17 articles / 32 relations sharing a recent
   time-prefix; the audit itself flagged "low power for rare defects … recent articles may
   be in-distribution-easy." Our 382-row, all-predicate sample has far more power and
   surfaces the long tail (data-source predicates, entity-resolution errors).
3. **The benchmark over-weights the easy/clean predicates.** `listed_on` (86% here) and
   `divested_from` / `has_executive` (~70%) are genuinely good; if a small sample happens
   to draw those, precision looks near-perfect. The volume predicates that dominate the
   graph (`analyst_rating`, `operates_in_country`, `is_in_sector`, `produces`) are the
   noisy ones.

---

## Method caveats (be skeptical of THIS audit too)

- **Single-evidence judging.** We judged each relation against its *longest* evidence
  snippet only. A relation with multiple evidence rows might be asserted by a *different*
  snippet we did not show the judge → this can **understate** true support. (Most sampled
  relations are low-evidence; see `relations.evidence_count`.) The 27.6% is therefore a
  *lower bound* on per-relation support, but the **CO_MENTION dominance is unlikely to be
  an artifact** — the snippets shown are the ones the system itself stored as the
  evidence, and 44% of them assert nothing.
- **Budget judge** (DeepSeek-V4-Flash, screening grade) at temperature 0; a stronger judge
  might shift borderline CO_MENTION/WRONG_PREDICATE calls, but the gross gap (28% vs
  ~100%) far exceeds plausible judge noise.
- **Evidence-text truncation / canonicalisation** in storage may strip the relation-bearing
  clause that existed at extraction time — this is itself a real product defect (the stored
  artifact is what users see), not merely a measurement artifact.
- The sample is balanced *per predicate*, not *by volume*; a volume-weighted estimate
  would weight the noisy high-volume predicates more, likely pushing the true graph-wide
  support **below** 28%.

---

## Takeaways

1. **The benchmark's 5.0/5 precision does NOT describe the stored graph.** Real stored
   support is **≈28%** (gpt-oss 27.6%, Qwen 29.5%) — the benchmark is optimistic by a wide
   margin and should not be cited as evidence of graph quality.
2. **The model switch did not improve stored quality** (27.6% vs 29.5%, CIs overlap).
3. **The dominant defect (CO_MENTION, 44%) is semantic and invisible to the deterministic
   gate.** The 2026-06-18 gate + cleanup fixed the *structural* junk (`listed_on` is now
   the best predicate at 86%) but the graph's headline problem is unasserted co-mentions,
   which need a *semantic* validation step (e.g. an evidence-entailment check at write
   time), not another structural rule.
4. **Highest-leverage targets:** the "data-source-as-subject" predicates
   (`analyst_rating`, `credit_rating`, `downgraded_by`, `price_target`, `sentiment_signal`
   = 12% support) and `corporate_action` / `earnings_*` / `produces` / `regulates`
   (0% support in the sample). These look like prompt/extraction-schema mismatches where a
   *ranking* or *mention* is being coerced into a *relation*.

---

### Reproduce

```
source .venv312/bin/activate
KEY=$(docker exec worldview-nlp-pipeline-article-consumer-0-1 \
        printenv NLP_PIPELINE_EXTRACTION_API_KEY)
# 1. stratified sample TSV produced by the SQL in this audit (relation_id, era,
#    subject, predicate, object, longest evidence_text) → /tmp/wv_sample_clean.tsv
# 2. judge:
python scripts/eval/validate_stored_relation_quality.py \
    --key "$KEY" --tsv /tmp/wv_sample_clean.tsv --out /tmp/wv_verdicts.json --workers 8
```

Script: `scripts/eval/validate_stored_relation_quality.py` (READ-ONLY DB; judge only).
