# Routing-Classifier Labeled Dataset — Feasibility Report (PLAN-0111 C-3)

**Date:** 2026-06-12
**Author:** automated (`scripts/eval/routing_classifier_dataset.py`)
**Scope:** Build the labeled training dataset for the EmbeddingGemma news-routing
classifier (PLAN-0111 Sub-Plan C) and assess whether the extraction-yield signal
is learnable and how biased the label set is.
**Verdict:** **GO** — the signal is learnable; ship the dataset and proceed to C-4,
but extract a small LIGHT counterfactual sample (~400 docs, ~$0.24) to de-bias the
label set before the C-5 ablation.

All numbers below are from live `nlp_db` + `intelligence_db` (queried READ-ONLY on
2026-06-12). Reproduce with:

```
NLP_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/nlp_db \
INTELLIGENCE_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/intelligence_db \
  python scripts/eval/routing_classifier_dataset.py build --out results/routing_dataset
```

Artefacts: `results/routing_dataset/routing_dataset.csv` (14,742 rows) +
`routing_dataset_manifest.json`.

---

## 1. Label source & join key

The label is the **retroactive extraction yield** per source document:

```
yielded = (n_relations + n_claims + n_events) >= 1
```

The three artefacts live in `intelligence_db` (the KG); the routing features live
in `nlp_db`. They share the document UUIDv7. Verified join keys:

| Artefact  | Table (intelligence_db)      | Join column          |
|-----------|------------------------------|----------------------|
| relations | `relation_evidence_raw`      | `source_document_id` |
| claims    | `claims`                     | `doc_id`             |
| events    | `events`                     | `doc_id`             |

`temporal_events` is **excluded** — it is a derived/macro table keyed by a
`source_article_ids` array, not a per-doc extraction artefact; including it would
over-count macro docs.

Because the two logical DBs cannot be JOINed in one statement, the script pulls
per-doc yield COUNTS from `intelligence_db` into a dict and left-joins them against
the `nlp_db` routing rows in Python.

**Note on the KG population.** The KG holds yield for ~181k distinct doc_ids, far
more than the 18,629 docs currently in `routing_decisions` (historical backfills +
seed). The label is therefore computed only over the routed docs we can attribute
features to — a clean left-join, no inflation.

### Degraded / timed-out docs

Commit `ee76aa957` ("unmask deep-extraction timeouts") added `degraded` /
`timed_out_windows` to the **merged** extraction result so an LLM timeout no longer
masquerades as a clean all-zero result. **However, that merged result is only
logged (`deep_extraction.complete`), never persisted** to any table — so there is
no per-doc `degraded` flag to read back.

What *is* persisted is the `dead_letter_queue`: when **every** window times out, the
article consumer re-raises and the doc lands in the DLQ with
`message_processing_timeout` (**1,562 such rows**). The DLQ payload carries only the
article-stored `event_id`, not the `doc_id`, so it cannot be mapped 1:1 to a routing
row.

**How we handle it:** `yielded = 1` proves extraction completed on ≥1 window, so
those rows are clean. Zero-yield rows are *usually* genuine "model found nothing"
but a minority may be partially-timed-out docs. We set `degraded = False` on every
row (we never fabricate a flag we cannot source) and surface the DLQ timeout count
in the manifest so C-4 can hold out / down-weight a slice. **Recommendation:**
persist the merged extraction result (incl. `degraded`/`timed_out_windows`) in a
future migration so C-4+ gets provably clean negatives.

---

## 2. The 5 hand features — leakage assessment

All five are persisted in `routing_decisions.feature_scores_json` and all are
computed in **Block 5, which runs before Block 10 deep extraction** — so none
observes the label.

| Feature              | What it is (pre-extraction)                                              | Leaks label? |
|----------------------|-------------------------------------------------------------------------|--------------|
| `entity_density`     | `min(1, (#ORG+#FI mentions)/15)` from Block-4 NER                        | No |
| `source_reliability` | `source_trust_weight` from `intelligence_db.source_trust_weights`        | No |
| `recency`            | `exp(-0.02·hours_since_published)` (half-life ~35h)                      | No |
| `document_type`      | static source-type → reliability map (SEC > press > news)               | No |
| `extraction_yield`   | `0.6·min(1,mentions/20)+0.4·min(1,sections/8)` — **prior, not realised** | **No** (but flagged) |

**`extraction_yield` is the one to scrutinise — and it is SAFE.** Despite the name,
it is **not** this doc's realised yield. It is a structural-richness *prior* built
from the Block-4 mention count and Block-3 section count, both available before the
235B ever runs. It does not leak the label. We surface it but flag it in the
manifest so a cautious ablation can drop it.

The 3 dead signals (`novelty`=1.0, `watchlist`=0.0, `price_impact`=0.0 — permanently
constant in single-pass routing) are present in the JSON but **excluded** from the
feature set.

---

## 3. Title / subtitle coverage

The classifier input is `title + subtitle`. The schema has no subtitle column, so
the **article lede (first chunk, `chunk_index=0`)** is the subtitle stand-in.

| | Count | Rate |
|---|---|---|
| Rows with non-empty title | 13,685 | **92.8%** |
| Rows missing title | 1,057 | 7.2% |
| Rows with non-empty subtitle (lede) | 14,742 | **100%** |

Title coverage is high enough to train on; the 7.2% title-less rows still have a
lede, so no row is input-empty. C-4 should treat title-less rows as a robustness
slice (EmbeddingGemma still embeds the lede).

---

## 4. Dataset summary

| Metric | Value |
|---|---|
| Labelable rows (`processing_path = full_pipeline`) | **14,742** |
| Positive (`yielded = True`) | 9,241 |
| **Positive rate** | **62.7%** |
| DEEP tier | n=7,090, positive rate **71.8%** |
| MEDIUM tier | n=7,652, positive rate **54.2%** |

Class balance is healthy (no extreme skew). The monotonic DEEP > MEDIUM positive
rate is the first evidence the routing score already tracks yield.

---

## 5. Selection-bias verdict

**The label set is biased**, exactly as anticipated. Extraction ran **only** on
`full_pipeline` (MEDIUM/DEEP) docs. Of **3,903 LIGHT** (`section_embeddings_only`)
docs, **exactly 1** appears in the KG yield set (a stray) — i.e. LIGHT docs are
effectively never extracted and have **no yield label**.

Training only on extracted docs teaches the model
`P(yield | doc was deemed MEDIUM/DEEP)` — a biased sample relative to the full
population the router must score. The cheap tier the router most needs to get right
(LIGHT) is entirely unlabeled.

### Recommended de-biasing sample + cost

Extract a **random sample of N=400 LIGHT docs** to obtain counterfactual labels.
At the 235B DeepInfra rate ($0.071/1M in, $0.10/1M out), with LIGHT docs averaging
**553 words**:

| N (LIGHT docs) | Input tokens | Output (worst-case) | **Est. cost (worst-case)** |
|---|---|---|---|
| 300 | ~0.80M | ~1.23M | ~$0.18 |
| **400** | ~1.07M | ~1.64M | **~$0.24** |
| 500 | ~1.33M | ~2.05M | ~$0.30 |

(Output assumes the 4,096-token cap on every call; real spend is lower.) The cost
is negligible — **recommend N=400** to add ~400 labeled LIGHT rows (~2.6% of the
training set) covering the under-represented cheap tier. **This report does NOT run
extraction** — estimate only.

---

## 6. Go / no-go: is the signal learnable?

**GO.** Even before embeddings, simple group-mean differences between yielded and
non-yielded docs show clear, exploitable structure:

| Feature | mean(yield=1) | mean(yield=0) | Δ |
|---|---|---|---|
| `entity_density` | 0.564 | 0.345 | **+0.219** |
| `recency` | 0.269 | 0.487 | **−0.218** |
| `extraction_yield` (prior) | 0.425 | 0.304 | +0.121 |
| `document_type` | 0.516 | 0.583 | −0.067 |
| `source_reliability` | 0.500 | 0.500 | +0.000 |

`entity_density` is the strongest positive predictor (richer docs yield more);
`recency`'s negative sign reflects that older docs in this historical population are
disproportionately the deeply-extracted backfill. `source_reliability` is flat here
(near-constant 0.5 in this sample) and will contribute little — useful to know for
the ablation. The `title + subtitle` text the EmbeddingGemma router will read
carries far more semantic signal than these 5 scalars, so the embedding classifier
should match or beat the 5-feature GBM baseline — which is exactly the C-5 thesis
result to prove.

**Next (C-4):** train logistic + LightGBM on Gemma embeddings → `P(yield)`,
calibrate (Platt/isotonic). Use the 5-hand-feature GBM on this CSV as the
baseline-to-beat. Add the 400-doc LIGHT sample before the held-out C-5 ablation.

---

## Files

- Builder: `scripts/eval/routing_classifier_dataset.py`
- Tests: `scripts/eval/test_routing_classifier_dataset.py`
- Dataset: `results/routing_dataset/routing_dataset.csv` (14,742 rows)
- Manifest: `results/routing_dataset/routing_dataset_manifest.json`
