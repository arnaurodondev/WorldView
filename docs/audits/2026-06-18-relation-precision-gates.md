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

## Deploy + cleanup (done 2026-06-19/20)

1. **Deployed** — both `nlp-pipeline-article-consumer-0/-1` images rebuilt and restarted;
   the gate is verified live in-container (`validate_relations` importable + wired into
   `deep_extraction`; smoke test drops a self-loop + an index `listed_on`, keeps a valid
   relation). New extractions log `deep_extraction.relations_filtered` when they drop.
2. **Cleanup** — both backfills run inside transactions, dry-run-verified, fully backed up
   to `cleanup_20260618_*` tables in `intelligence_db`:
   - Materialised graph: 442 invalid `listed_on` deleted across `relations` (442) +
     `relation_evidence` (492) + `relation_summaries` (7) + `relations_history` (462) +
     AGE `LISTED_ON` edges (442). `listed_on` 1938→1496 in both `relations` and AGE
     (stayed in sync); residual invalid = 0.
   - Raw evidence: 5,719 self-loops + 612 invalid `listed_on` deleted from
     `relation_evidence_raw` (100,217→93,886); residual self-loops = 0.

## Re-A/B on the LIVE model (2026-06-20) — gate-aware residual measurement

`scripts/eval/gate_residual_ab.py` — runs the **currently deployed** extraction model,
applies the production gate to each output, and judges RAW vs GATED with an independent
budget judge (DeepSeek V4 Flash).

**Key context: the live extraction model changed.** Production now runs
`openai/gpt-oss-120b` @ `reasoning_effort=medium` — NOT the `Qwen/Qwen3-235B` @ `low`
that the 2026-06-14 v1.6 audit (verdict TUNE, ~32% NEW-triple defective) measured. So the
old residual numbers do not transfer; this run re-measures against what is actually live.

Sample: 24 deep-tier articles; 7 lost to DeepInfra `api_error` (≈29% — rate-limiting at
`medium` effort, a throughput/reliability signal, not a quality one), **17 judged, 32
relations**.

| Metric | RAW (gate off) | GATED (gate on) |
|---|---|---|
| relations | 32 | 32 |
| deterministic drops | — | **0** (drop_rate 0.0) |
| mean precision (1–5) | 4.941 | 4.941 |
| mean adherence (1–5) | 5.0 | 5.0 |

**Interpretation.** On the live model, the deterministic gate finds **nothing to drop**
(0/32; rule-of-three upper bound ≈9% — "rare", not provably zero) and relation precision
is already ≈4.94/5 with perfect adherence. The defect classes that polluted the corpus
(self-loops, index `listed_on`) were overwhelmingly produced by the **previous** model;
`gpt-oss-120b` @ medium is dramatically cleaner and **clears the ≥85%-clean GO gate**.

This reframes the gate's role: it currently catches ~nothing, so its value is now
(a) the one-time cleanup of the old model's accumulated junk (done above) and
(b) a permanent, zero-cost **regression guarantee** against future model drift /
prompt changes — not an active filter on the current model.

**Caveats** — small sample (17 articles / 32 relations, low power for rare defects);
articles share a recent time-prefix (correlated window); budget judge (screening-grade);
recent articles may be in-distribution-easy. Treat as a strong directional signal, not a
final precision figure. A larger, time-diverse sample would tighten the bound.

## Remaining open item (new, surfaced by the re-A/B)

- **≈29% extraction `api_error` rate** under load at `gpt-oss-120b` @ `medium` effort
  (DeepInfra 429s exhausting backoff). This is a separate *reliability/throughput*
  concern from extraction *quality* — worth a dedicated look (effort tuning, concurrency
  caps, or fallback-model wiring) since dropped windows degrade recall silently.
