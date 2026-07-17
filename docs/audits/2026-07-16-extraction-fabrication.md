# Extraction fabrication — root cause + layered mitigations (S6 nlp-pipeline, 2026-07-16)

**Context.** The 2026-07-16 model bake-off (`2026-07-16-extraction-model-bakeoff.md`)
measured **fabrication** — a claim/relation NOT grounded in the source article — as the
single largest quality drag: **2.13 fabricated items/article** on the live `Qwen3-235B`,
**0.83/art** on the incoming `DeepSeek-V4-Flash`. The operator considers fabrication "a
huge drawback." The model is switching to DeepSeek-V4-Flash regardless; this work makes
**any** extractor fabricate less.

**Deliverable of this investigation:** a fabrication taxonomy from the real judged
artifacts, a root cause, a ranked layered-mitigation plan, and one **deterministic,
yield-neutral fix shipped** on branch `investigate/extraction-fabrication` with tests and
an empirical before/after against fresh prod extractions.

---

## 1. Fabrication taxonomy (from 240 real judge verdicts)

Source: `2026-07-16-extraction-model-bakeoff-artifacts/judge_scores.json` (n=30 articles ×
8 configs). 149/240 extractions carried ≥1 fabrication. Clustering the judge
justifications (keyword + thematic counts across all fabricating verdicts):

### By kind (which channel fabricates)

| Bucket | Signature | Frequency signal |
|---|---|---|
| **Fabricated / mislabelled CLAIMS** | a `claim_type` the text does not support | **dominant.** claim-type mentions in fabrication justifications: DEBT_CHANGE ×26, REVENUE_GROWTH ×16, GUIDANCE_RAISE ×15, HEADCOUNT_CHANGE ×10, GUIDANCE_CUT ×5, EPS_BEAT ×4 |
| **Fabricated RELATIONS** | a predicate the evidence does not assert | `operates_in_country` ×17, `employs` ×11, `competes_with` ×9, `board_member_of` ×9, `partner_of` ×8, `produces` ×8, `acquired` ×8, `has_executive` ×7, `analyst_rating` ×6 |
| **Direction / semantic inversion** | "bidding" read as "acquiring"; "worked at" read as "employs"; "owns" read as "employs" | ~37 thematic hits |
| **Temporal / numeric extrapolation** | invented dates ("Q4 2025 release date — text only says Q4 call"), "late 2025"→"2025", composed figures | ~51 thematic hits |
| **News-source-as-entity** | attaching a relation to the wire/publisher ("GLOBE NEWSWIRE sentiment_signal", "Financial Times analyst_rating", "Zacks credit_rating") | ~14 hits |

### The mechanically-important split

Every fabrication is one of two kinds, and they need **different** defences:

1. **Ungrounded quote** — the model invents or paraphrases its own `evidence_text`, so the
   quote is not a verbatim span of the article. *Deterministically detectable* (substring
   check). **Empirically rare** — see §3.
2. **Mislabelled real quote** — the `evidence_text` IS a real sentence, but the asserted
   `claim_type`/`predicate` is not what the sentence says ("refinanced $2B" → DEBT_CHANGE
   with negative polarity; a résumé enumeration → `competes_with`; a co-mention →
   `partner_of`). *Not* detectable by any substring/structural check — needs **semantic
   entailment**. **Empirically dominant.**

---

## 2. Root cause

Three compounding gaps, in order of impact:

1. **Claims have NO post-extraction guard and NO prompt discipline.** `validate_relations`
   (the deterministic precision gate) and the optional entailment gate touch **relations
   only**. Claims flow straight from the LLM into `raw_claims` → KG. The prompt gives
   relations a **RELATION ASSERTION TEST** + co-mention/self-loop/index negative examples
   (added v1.6), but claims get *no* assertion test and *zero* negative examples. Result:
   the model over-triggers a handful of claim_types (DEBT_CHANGE, GUIDANCE_RAISE,
   REVENUE_GROWTH) on any loosely-related sentence. This is the #1 fabrication bucket and
   is completely unguarded.
2. **`evidence_text` is required by the prompt but never verified.** The prompt says
   "FABRICATION IS PROHIBITED … Every value must be traceable to a verbatim phrase … Use
   evidence_text to quote the exact sentence." Nothing enforced it — a model could cite an
   invented quote and it was accepted. (Fixed — §4.)
3. **Model over-generation is real but secondary.** 235B extracts the most (5.9 rel, 2.67
   claims/art) and fabricates the most; the trade is yield. But the fabrication is not
   mostly "made-up facts from nothing" — it is **wrong labels on real sentences**, i.e. a
   *precision-of-classification* problem, not a *hallucination-of-text* problem.

---

## 3. Empirical read: what the deterministic span-check actually catches

Fresh read-only replay: 15 real DEEP-tier prod articles (`nlp_db`, balanced buckets),
same rendered `DEEP_EXTRACTION` prompt + prod decode params, extracted with both models,
then the shipped grounding gate applied. (`scripts/eval/extraction_quality_eval.py` +
`apply_evidence_grounding`.)

| Model | claims/art | rels/art | ungrounded-quote drops/art | false drops |
|---|---|---|---|---|
| `DeepSeek-V4-Flash` | 0.36 | 4.64 | **0.00** | 0 / 70 items |
| `Qwen3-235B` | 1.60 | 6.53 | **0.07** | 0 / 122 items* |

\* After a robustness fix (edge-punctuation tolerance): the raw substring check first
false-dropped 2 faithful quotes that differed only by a trailing "." the model appended.
Fixing that left a single true drop — `"Forward yield 0.74%"` on Qwen, a *composed* phrase
("yield" and "0.74" appear separately in the source, never as that contiguous quote).

**Interpretation (the honest headline):**

- The deterministic span-check is **provably yield-neutral** — 0 false drops across 192
  items once edge-punctuation is tolerated. A faithfully-quoted item is always a substring,
  so it never removes a true positive.
- The span-check **catches very little fabrication** (~0.07/art on 235B, ~0/art on
  DeepSeek) because the models **do quote verbatim** — the 2.13/art and 0.83/art the judge
  penalised are almost entirely **kind-2 (mislabelled real quotes)**, which no substring
  check can catch.

So the span-check is the right **floor** (free, model-agnostic, zero-risk, and it hardens
the platform against a future cheaper/noisier model that *does* hallucinate quotes) — but
it is **not** the lever that moves the 2.13/art number. That requires semantics.

---

## 4. Shipped fix — deterministic evidence-span grounding gate

`services/nlp-pipeline/src/nlp_pipeline/application/blocks/evidence_grounding.py`
(+ wired into `run_deep_extraction_block`, `run_ml_phase`, `article_consumer[_main]`,
`config.py`; unit tests `tests/unit/test_evidence_grounding.py`).

- Drops any claim/relation whose `evidence_text` is present but is **not a normalised
  substring** of the source passage. Normalisation: NFKC + unicode-punctuation folding
  (curly quotes, en/em dashes, nbsp) + whitespace collapse + case; ellipsis-elided quotes
  pass iff every non-trivial fragment appears; leading/trailing punctuation tolerated.
- Config-gated per item kind (`NLP_PIPELINE_EVIDENCE_GROUNDING_CLAIMS_MODE` /
  `_RELATIONS_MODE`): `off` | `present_only` (default) | `require`. `present_only` never
  drops a quote-less relation (relations don't schema-require `evidence_text`); `require`
  additionally drops missing-quote items (defensible for claims, which do).
- **Runs after** `validate_relations` and the entailment gate — complementary layer.
- **This is a floor, not the fix for §1.** Kept because it is free, yield-neutral, and
  model-agnostic. Default `present_only` chosen over `require` to guarantee no yield
  surprise; the operator can tighten claims to `require` after a wider eval.

---

## 5. Ranked mitigation plan (fabrication-reduction vs yield-cost)

| # | Lever | Deterministic? | Expected fabrication ↓ | Yield cost | Status |
|---|---|---|---|---|---|
| 1 | **Evidence-span grounding gate** | ✅ free | small on today's models (kind-1 only), but a zero-risk floor | **none** (proven 0 false drops) | **SHIPPED** |
| 2 | **Prompt hardening for CLAIMS** — add a CLAIM ASSERTION TEST + per-type negative examples for the over-triggered types (DEBT_CHANGE from refinancing/cash; GUIDANCE_RAISE/CUT with no guidance; REVENUE_GROWTH from a segment mention) | ✅ free | **high** — targets the #1 bucket, unguarded today; mirrors the v1.6 relation-assertion-test that measurably cut relation fabrication | low-moderate on claims (intended: these are the fabrications). Needs a bake-off run to confirm recall holds | **DESIGNED** — v1.8 prompt bump; validate via `extraction_quality_eval` before ship |
| 3 | **LLM claim-type verification pass** — extend the entailment concept to claims: cheap model answers "does this quote support claim_type X?" for high-fab types only; veto NOT_SUPPORTED | ❌ LLM | **high** on kind-2 residue (the dominant mode) | none (drops only vetoed items) | **DESIGNED** — see §6 cost |
| 4 | **Enable the existing relation entailment gate** (`relation_entailment_check_enabled`, default OFF) for symmetric predicates | ❌ LLM | measured 88.6% defect recall, **0% FP** on high-risk predicates (2026-06-21 prototype) | none at 0% FP | **READY** — flip env + wire client |
| 5 | **Confidence gating** — the schema emits per-item `confidence` | ✅ free | **low** — judged fabrications frequently carry ≥0.9 confidence; weak signal | drops true positives too | not recommended as a primary lever |

**Recommended sequence:** ship #1 (done) → author + bake-off #2 (biggest free win, targets
the dominant claim bucket) → enable #4 (already built, 0% FP) → add #3 for the residue if
fabrication is still material after #2+#4.

**Yield tradeoff, stated plainly:** none of #1/#3/#4 reduce true-positive yield (they drop
only ungrounded/unsupported items). #2 *will* reduce claim yield — but the yield it removes
is the fabricated claims themselves; it must be A/B'd on the bake-off harness to confirm it
does not also suppress grounded claims (the v1.5→v1.6 history shows an over-absolutist
prompt can cause a recall collapse — the reason #2 is DESIGNED, not shipped blind).

---

## 6. What needs an LLM pass and its cost

Levers #3 (claim verification) and #4 (relation entailment) need a cheap verifier. Sizing
from the bake-off's authoritative per-call costs at **4,500 DEEP docs/day**:

- Gate to **high-fabrication types only** (claims: DEBT_CHANGE, GUIDANCE_*, REVENUE_GROWTH,
  HEADCOUNT_CHANGE; relations: the 5 symmetric predicates) → ~1–2 verifier calls/article,
  tiny verdict JSON.
- The 2026-06-21 entailment prototype measured **~$0.07 per 1,000 checks** on Qwen3-235B
  with 0% FP; a DeepSeek-V4-Flash verifier is cheaper still. At ≤2 checks/doc × 4,500
  docs/day that is well under **$1/mo** — negligible against the $76–140/mo extraction line.
- **Do NOT** use a weak model as the verifier: the prototype rejected gpt-oss-20b at 27.6%
  FP (it kills good items). Verifier ≥ Qwen3-235B / DeepSeek-V4-Flash class.

---

## 7. Do-not / scope

- **No model flip, no deploy** — the model swap is a separate track; this branch is not
  deployed. The gate defaults to `present_only` (active-by-default in code) but is
  env-toggleable to `off`.
- Read-only against prod throughout (replay `assemble` reads `nlp_db`; extraction hits the
  DeepInfra API only). Golden set not committed (contains prod article text).
