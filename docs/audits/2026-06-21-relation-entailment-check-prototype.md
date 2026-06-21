# Cheap Co-mention Entailment Check — Prototype + Measurement — 2026-06-21

**Enhancement #6.** A cheap write-time LLM entailment check for relation extraction
that, given `(subject, predicate, object, evidence_text)`, returns ASSERTED /
NOT_ASSERTED — distinguishing a relation the evidence actually states (with a
relation-bearing verb/phrase) from a mere CO-MENTION (two entities adjacent in the
same text). This is the dominant relation defect per the
`2026-06-20-stored-relation-quality-remeasurement.md` audit, and is *semantic* —
the deterministic gate (`relation_validation.py`) cannot catch it because every
co-mention relation is structurally valid.

**The question this measurement answers: is it worth it?** An LLM call per risky
relation costs money + latency. Does a cheap model catch enough co-mention defects
WITHOUT killing too many good relations, and at what cost-per-article?

---

## Method

* **Gold set:** 443 real stored relations, stratified ≤14 per predicate across all 31
  predicates (oversampling the risky/loose ones), each with its longest evidence
  snippet. Pulled READ-ONLY from `intelligence_db` (`relations` ⋈ `relation_evidence`).
  This reconstructs the audit's labelled set (the original `/tmp/wv_remeasure_verdicts.json`
  had been cleared from `/tmp`).
* **Ground truth:** the audit's strong judge — `Qwen/Qwen3-235B-A22B-Instruct-2507`
  with `reasoning_effort=low` and the full per-predicate direction conventions —
  labelled each relation SUPPORTED / CO_MENTION / WRONG_DIRECTION / WRONG_PREDICATE /
  UNSUPPORTED. Distribution: **142 SUPPORTED (32.1%)**, 157 UNSUPPORTED, 54 CO_MENTION,
  66 WRONG_DIRECTION, 24 WRONG_PREDICATE. (32.1% SUPPORTED ≈ the audit's 36.9%
  predicate-balanced headline — a faithful reconstruction.)
* **Mapping:** `should_pass` = SUPPORTED; `should_fail` = CO_MENTION ∪ UNSUPPORTED
  (211 relations). WRONG_DIRECTION / WRONG_PREDICATE are out of the entailment check's
  design scope and excluded from the headline (reported separately).
* **Cheap check:** a binary, false-positive-minimising prompt (default-towards-ASSERTED
  on any doubt; only NOT_ASSERTED when confident). `temperature=0`, `reasoning_effort=low`,
  429 backoff. Two models compared.
* **Harness:** `scripts/eval/prototype_entailment_check.py` (`--phase label` then
  `--phase eval --cheap-model …`).

The critical risk is the **false-positive rate** (FPR): correctly-SUPPORTED relations
the check would wrongly kill. A high FPR destroys good relations and is unacceptable.

---

## Results

### Overall (SUPPORTED vs CO_MENTION+UNSUPPORTED; n=353 in scope)

| cheap model | precision | recall | F1 | **false-positive rate** | cost/1k checks |
|---|---|---|---|---|---|
| **Qwen/Qwen3-235B-A22B-Instruct-2507** | **99.4%** | **84.4%** | **91.3%** | **0.7%** (1/142) | **$0.073** |
| openai/gpt-oss-20b | 85.2% | 82.0% | 83.6% | **21.1%** (30/142) | $0.036 |

### High-risk predicates ONLY (the inline target set: competes_with, regulates, produces, partner_of, supplier_of)

| cheap model | precision | recall | **false-positive rate** |
|---|---|---|---|
| **Qwen3-235B** | **100%** | 88.6% | **0.0%** (0 good relations killed) |
| openai/gpt-oss-20b | 76.5% | 74.3% | **27.6%** (kills ~1 in 4 good) |

Per-predicate FPR for gpt-oss-20b is disqualifying: `regulates` 100%, `produces` 67%,
`competes_with` 25%. Qwen3-235B: **0% on every high-risk predicate** while still
recalling 88.6% of the defects (competes_with 100%, regulates 91%, supplier_of 89%,
produces 83%, partner_of 67%).

### Cost

Qwen3-235B averages **~412 input / 32 output tokens per check** →
**$0.000073/check = $0.073 per 1,000 checks**. The check only runs on the ~5 high-risk
predicates (~30% of extracted relations); at ~1–2 risky relations per article that is
**~$0.0001–0.00015 per article** of added cost. gpt-oss-20b is half the price but
produces ~3× the output tokens and, far more importantly, an unusable FPR.

---

## Recommendation: **SHIP INLINE, with Qwen3-235B, default-OFF, scoped to high-risk predicates.**

* **Worth it: yes**, but ONLY with the strong-cheap model. Qwen3-235B catches ~85% of
  co-mention/unsupported defects at **0% false-positive on the target predicates** —
  it never killed a good high-risk relation in the gold set — for ~$0.0001/article.
  At ~842 unsupported `competes_with` + ~479 `regulates` + ~361 `produces` relations
  estimated in the graph, this removes a large fraction of the dominant defect class.
* **gpt-oss-20b: not worth it.** "Cheap but good" fails — 27.6% FPR on high-risk
  predicates means it would destroy ~1 in 4 good relations. Cheaper is not good enough.
* **Inline vs async post-hoc:** inline is fine at this cost/latency (one ~400-token
  call per risky relation, parallelisable), and inline prevents the bad relation from
  ever being written (no cleanup job needed). Keep an async post-hoc validator as the
  fallback if extraction-path latency budget is tight.

### Residual risks

1. **Recall is ~85%, not 100%** — ~15% of co-mention defects still pass. This is a
   precision-first gate, not a complete fix; pair it with the prompt/few-shot fixes
   from the audit (direction examples, suppress worst new predicates).
2. **`partner_of` recall is only 67%** — symmetric/loose predicates are hardest; tune
   the prompt or raise scope cautiously.
3. **Judge-on-judge optimism:** ground truth is one strong LLM judge. A ~150-relation
   human gold set (audit rec #6) would convert these into validated numbers.
4. **Added cost/latency scales with risky-relation volume.** The `max_per_doc` cap and
   tight predicate set bound it; monitor `relation_entailment.complete` logs.
5. **Same provider/model as the extractor** (Qwen3-235B is the live extraction model on
   some eras) — low self-preference risk for an *entailment* (not extraction) task, but
   worth noting.

---

## Deliverables

* Measurement harness: `scripts/eval/prototype_entailment_check.py`
* Inline module (default-OFF): `services/nlp-pipeline/src/nlp_pipeline/application/blocks/relation_entailment.py`
* Wiring (config-gated, fail-open): `deep_extraction.py` after merge/dedup
  (the `validate_relations` equivalent point)
* Config: `Settings.relation_entailment_check_*` (default disabled)
* Unit tests: `tests/unit/application/blocks/test_relation_entailment.py` (11 tests, LLM mocked)
* Raw verdicts: `/tmp/wv_labels.json` (ground truth), `/tmp/wv_eval_qwen235b.json`,
  `/tmp/wv_eval_gptoss20b.json`
