# Eval scripts

This directory holds standalone, read-only offline eval/data tooling.

## `routing_classifier_dataset.py` — routing-classifier labeled dataset (PLAN-0111 C-3)

Builds the labeled training dataset for the EmbeddingGemma news-routing classifier:
one row per historical `full_pipeline` doc with `title + subtitle`, the 5 persisted
pre-extraction hand features, the routed tier, per-doc relation/claim/event counts,
and the label `yielded = (n_relations + n_claims + n_events) >= 1`. Joins KG
extraction outputs (`intelligence_db`) back to `routing_decisions` (`nlp_db`) by
doc UUID. READ-ONLY, idempotent. See
`docs/audits/2026-06-12-routing-classifier-dataset-feasibility.md` for the
feasibility verdict (signal is learnable; LIGHT tier is unlabeled → de-bias sample).

```
NLP_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/nlp_db \
INTELLIGENCE_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/intelligence_db \
  python scripts/eval/routing_classifier_dataset.py build --out results/routing_dataset
```

---

## `routing_classifier_train.py` — train + ablation harness (PLAN-0111 C-4/C-5)

Offline modelling harness (NOT wired to production — that is C-6). Embeds each
row's `title + "\n" + subtitle` with `EmbeddingGemmaRouterAdapter` (classification
prompt, cached to `results/routing_dataset/embeddings_<dims>.parquet` by `doc_id`),
then runs a stratified 5-fold cross-validated ablation over feature sets:

- **A** — 5 hand features (baseline-to-beat); **A_no_yield** drops `extraction_yield`.
- **B** — EmbeddingGemma(title+subtitle) only.
- **C** — embedding + cheap structured (`source_reliability`, `recency`, `document_type`).
- **D** — the deployed static weighted-sum rule, scored as a classifier (lift baseline).

Each learned set trains logistic-regression + GBM (LightGBM if importable — requires
`libomp` on macOS — else sklearn `HistGradientBoostingClassifier`), wrapped in
`CalibratedClassifierCV(isotonic)`. Reports out-of-fold ROC-AUC / PR-AUC / Brier /
accuracy / F1 at the Youden threshold, plus a cost-vs-yield (routed-fraction vs
yield-recall) curve. Outputs `results/routing_dataset/ablation_results.json` (gitignored)
and `docs/audits/2026-06-12-routing-classifier-ablation.md`. The `--dataset` flag is the
single knob to re-run on the C-3b augmented + de-biased CSV.

```
NLP_PIPELINE_EXTRACTION_API_KEY=... \
  python scripts/eval/routing_classifier_train.py \
    --dataset results/routing_dataset/routing_dataset.csv --dims 768
```

---

# Extraction-quality A/B harness (LLM-as-judge)

`extraction_quality_eval.py` — an **offline** harness to decide whether a
faster/cheaper DeepInfra extraction model (e.g. `deepseek-ai/DeepSeek-V4-Flash`,
`Qwen/Qwen3.6-35B-A3B`) matches the current production model
`Qwen/Qwen3-235B-A22B-Instruct-2507` on **extraction quality**, before we swap it.

Extraction (events / claims / relations) feeds the knowledge graph, so a bad swap
silently degrades the graph. This tool screens candidates with an **independent
LLM judge** — no human labelling needed for a verdict. A human spot-check sheet is
emitted as an optional secondary signal only.

It is a **standalone** tool: it does **not** modify or wire into the live pipeline,
the `DeepSeekExtractionAdapter`, `config.py`, or any model env var. It only *reads*
nlp_db + content_store_db to build a frozen input set, and makes its own HTTP calls.

## Pipeline (4 stages, each persists its output)

| Stage | Command | Reads | Writes |
|-------|---------|-------|--------|
| 1. Assemble golden set | `assemble` | nlp_db (`routing_decisions`, `chunks`, `entity_mentions`, `document_source_metadata`) | `golden_set.json` |
| 2. Run candidates | `run` | `golden_set.json`, DeepInfra | `model_runs.json` |
| 3. Judge | `judge` | `golden_set.json`, `model_runs.json`, judge API | `judge_scores.json` |
| 4. Report | `report` | all of the above | `report.md`, `aggregate.json`, `human_spotcheck.md` |

Helpers: `estimate-cost` (no spend), `dry-run` (tiny end-to-end smoke run).

## Golden-set fidelity

The golden set captures the **exact** extraction inputs the pipeline would build,
mirroring `services/nlp-pipeline/.../blocks/deep_extraction.py`:

- **`entities`** = order-preserving de-dup of `entity_mentions.mention_text` for the
  doc (`list(dict.fromkeys(...))`) — the literal `{entities}` allow-list.
- **`text`** = `chunks.chunk_text` joined in `chunk_index` order — the literal
  `{text}` window. Truncated to the 24k-token single-window budget (the pipeline's
  `SINGLE_WINDOW_TOKEN_LIMIT`); we evaluate the first/representative window.

Only **DEEP**-tier docs are pulled (`routing_decisions` final tier = `DEEP`). The
sample is balanced across span buckets (earnings / M&A / management / macro / thin /
general) so we also test that good models correctly return *little* on thin docs.

The prompt is rendered from the **real** `prompts.extraction.deep.DEEP_EXTRACTION`
template (v1.4) — never a copy — so the harness can't drift from production.

## Model run fidelity

Each candidate runs through the **same** decode params as the production adapter:
`temperature=0`, `response_format=json_object`, `reasoning_effort=none`,
`max_tokens=4096`. Latency and token usage are captured per call. Timeouts / HTTP
errors are recorded per-article (`status=api_error`) — they never crash the run.
Unparseable JSON is recorded (`status=json_error`) and scored at the rubric floor.

## The judge (the measurement instrument)

**The judge is never the model it is grading** — the self-preference guard
(`_resolve_judge_for_model`) enforces this:

- If `ANTHROPIC_API_KEY` is set → judge is **Claude Opus 4.8** (`claude-opus-4-8`).
  A *different model family* from every DeepInfra candidate, so it is independent of
  **all** of them — including the 235B baseline. This is the preferred judge.
- Otherwise → judge is the **235B on DeepInfra** (strong, independent of every
  *non-235B* candidate). The harness **refuses to let it grade its own output**:
  judging the 235B candidate with the 235B judge returns `judge_error` with a clear
  message to set `ANTHROPIC_API_KEY` or pass a different `--judge-model`.

The judge scores three dimensions, **1–5** each, plus counts and a short
justification, returned as strict JSON:

- **Precision** — is every item supported by a verbatim phrase? (hallucination check)
- **Recall** — did it miss obvious events/claims/relations? (a thin article correctly
  returning empty is a **5**, not a miss)
- **Adherence** — refs in allow-list? dates verbatim? valid predicates/event_types?
  person↔company direction correct?

Both extraction and judge run at `temperature=0` for reproducibility.

### Judge-methodology risks & mitigations

| Risk | Mitigation |
|------|------------|
| **Self-preference** (a model rating its own output higher) | Judge is never the candidate; default judge is a different family (Claude). Code-level guard refuses self-grading. |
| **Verbosity bias** (rewarding longer extractions) | The prompt has explicit NEUTRALITY RULES: "Do NOT reward longer output… A short, fully-correct extraction outscores a long padded one." Recall is judged against *what the article supports*, not a quota. |
| **Terseness bias** (rewarding empty output) | Recall penalises missing clearly-stated facts; the rubric rewards *calibration* (right amount for the article). |
| **Judge non-determinism** | `temperature=0`; strict-JSON output; deterministic floor for unparseable model output. |

The dry-run below is the sanity check that the rubric behaves: faithful extraction
→ high scores; off-allow-list fabrication → low adherence + flagged violation;
correct empty output on a thin article → 5/5/5.

## Usage

```bash
# 1. Freeze the golden set (reads the DBs)
NLP_DB_URL=postgresql://user:pw@host/nlp_db \
  python scripts/eval/extraction_quality_eval.py assemble \
    --sample-size 100 --out results/extraction_eval

# 2. Run candidates (DeepInfra)
DEEPINFRA_API_KEY=... python scripts/eval/extraction_quality_eval.py run \
  --out results/extraction_eval \
  --models "Qwen/Qwen3-235B-A22B-Instruct-2507,deepseek-ai/DeepSeek-V4-Flash"

# 3. Judge (Claude Opus 4.8 if ANTHROPIC_API_KEY set; else 235B on DeepInfra)
ANTHROPIC_API_KEY=... python scripts/eval/extraction_quality_eval.py judge \
  --out results/extraction_eval

# 4. Report + verdict
python scripts/eval/extraction_quality_eval.py report --out results/extraction_eval

# Cost preview (no spend) — run after `assemble`
python scripts/eval/extraction_quality_eval.py estimate-cost \
  --out results/extraction_eval \
  --models "Qwen/Qwen3-235B-A22B-Instruct-2507,deepseek-ai/DeepSeek-V4-Flash"

# Tiny end-to-end smoke run (3 articles) once a golden set + keys exist
DEEPINFRA_API_KEY=... ANTHROPIC_API_KEY=... \
  python scripts/eval/extraction_quality_eval.py dry-run --out results/extraction_eval
```

All model lists, the judge model, and the sample size are CLI args so re-runs are
cheap. Stages are independent — re-judge without re-running models, etc.

## Cost (token-aware)

For **100 articles × 3 models** at ~700 words/article (worst-case 4096-token
outputs):

- Extraction: ~858k in + ~1.23M out tokens → **≈ $0.18** (DeepInfra 235B rate)
- Judge (DeepInfra 235B): ~858k in + ~90k out → **≈ $0.07** → **total ≈ $0.25**
- Judge (Claude Opus 4.8 instead): ≈ **$5–6** for the judge leg ($5/$25 per 1M)

Real spend is lower (few extractions hit the 4096-token cap). Run `estimate-cost`
after `assemble` for figures against your actual golden set.

## Tests

`test_extraction_quality_eval.py` — 13 offline tests (no DB / no network): prompt
render against the real template, output parsing (good / fenced / json-error /
api-error), the judge flow (DeepInfra + Anthropic paths), the self-preference guard,
the unparseable-output floor, aggregation, the report verdict (match vs below
tolerance), cost estimation, and the spot-check sheet.

```bash
python -m pytest scripts/eval/test_extraction_quality_eval.py -v
```
