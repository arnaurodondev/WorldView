# Deterministic Relation Precision Gates — 2026-06-18

Follow-up to the 2026-06-14 v1.6 extraction-prompt re-A/B
(`docs/audits/2026-06-14-extraction-prompt-v16-reab.md`, verdict **TUNE**).

## Problem

The v1.6 DEEP_EXTRACTION prompt *instructs* the relation extractor (Qwen3-235B) to
never emit self-loops, out-of-vocabulary predicates, index/ticker `listed_on` objects,
or bare common-noun endpoints. The re-A/B proved the model **ignores these
explicitly-named, few-shot-demonstrated prohibitions ~⅓ of the time** — the prompt
halves the defect rate but cannot *guarantee* the gates. These four defect classes are
*structural*: such a relation cannot be true regardless of the article, so they are safe
to drop deterministically in code.

## Fix

New module `services/nlp-pipeline/src/nlp_pipeline/application/blocks/relation_validation.py`
— `validate_relations()` — applied in `deep_extraction.py` at the single
`_merge_results_safe` choke point, **after the LLM returns and before relations become
evidence**. A code filter makes the gates a guarantee independent of model drift.

Four gates (one drop reason counted per dropped relation, priority order):

| Reason | Rule |
|---|---|
| `empty_field` | missing/blank subject_ref, predicate, or object_ref (or non-dict) |
| `self_loop` | subject and object normalise to the same entity |
| `oov_predicate` | predicate ∉ the closed 32-type vocabulary |
| `common_noun_endpoint` | subject or object is a bare generic noun (`stock`, `oil`, `the company`…) |
| `invalid_listed_on` | `listed_on` object is not a real stock exchange (index/ticker/country/company) |

Design notes:
- **Predicate vocabulary** mirrors the prompt's closed 32-type set; a unit drift-guard
  (`test_valid_predicates_match_deep_extraction_prompt`) parses the predicate names back
  out of the live prompt and asserts set-equality, so the gate can never silently drift
  from what the model is told to emit.
- **`listed_on` allow-list** keys are *alphanumeric-normalised* (lower-cased, every
  non-`[a-z0-9]` removed). This was forced by the live corpus: the naïve allow-list
  mis-flagged ~360 real listings written as `NasdaqGS`, `NYSE MKT`, `FSE`, `CSE`,
  `TSX Venture`. Normalisation keeps them while still dropping every index/ticker —
  `nasdaq` stays in the set, `nasdaqcomposite` does not.
- **Conservative by construction**: only structurally-invalid relations are dropped,
  never merely low-confidence ones. Confidence/decay stays in S7
  (`knowledge_graph.domain.confidence`).

## Live-corpus impact (measured 2026-06-18, `intelligence_db`)

Quantifies what the gates would have caught on already-extracted data:

| Layer | Metric | Count |
|---|---|---|
| `relation_evidence_raw` | total | 100,217 |
| `relation_evidence_raw` | self-loops (gate would prevent) | **5,719 (5.7%)** |
| `relation_evidence_raw` | OOV predicates | 0 *(canonicalisation already maps/drops these downstream; the gate now kills them earlier, before wasted resolution)* |
| `relation_evidence_raw` | `listed_on` total / invalid | 5,959 / **1,133 (19%)** |
| `relations` (materialised graph) | self-loops | 0 *(KG already drops, BP-384/385)* |
| `relations` (materialised graph) | `listed_on` total / invalid | 1,938 / **442 (23%)** |

The 442 invalid `listed_on` rows in the materialised graph (`Apple listed_on S&P 500`,
`X listed_on US Dollar`, …) are **user-visible** — RAG-chat and the frontend read this
table. The gate prevents future ones; cleaning the existing 442 is a separate
(destructive) backfill decision, pending go-ahead.

## Tests

`services/nlp-pipeline/tests/unit/test_relation_validation.py` — 40 cases: happy path,
each gate, spelling-variant exchanges kept, country endpoints not mis-dropped, mixed
batches, hygiene, and the prompt-sync drift-guard. Full `application/blocks` suite: 259
passed. ruff + mypy clean.

## Follow-ups

1. **Deploy** — rebuild + restart the article-processing consumer so new extractions are
   gated (then watch the `deep_extraction.relations_filtered` structured log).
2. **Backfill cleanup** (pending decision) — delete the 442 invalid `listed_on` rows from
   the materialised `relations` graph and the ~6.8k structurally-invalid rows from
   `relation_evidence_raw`.
3. **Quiet-hour re-A/B** — with the deterministic classes now guaranteed at 0, re-measure
   the *residual* (probabilistic) defect rate — co-mention hallucination, wrong-direction
   — which remains the prompt's job, to decide if the GO gate (≥85% clean) is met.
