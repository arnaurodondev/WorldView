# Extraction model bake-off — S6 nlp-pipeline (2026-07-16)

**Goal:** find the best cost/quality model for the S6 deep-extraction task (events / claims /
relations → KG). Extraction is the single largest LLM cost line. This is a **decision input**,
not a deploy: **nothing swaps until the operator decides from the table below.** The live model
stays `Qwen/Qwen3-235B-A22B-Instruct-2507`.

## Method

- **Harness:** `scripts/eval/extraction_quality_eval.py` (enhanced this branch to capture
  DeepInfra's authoritative `usage.estimated_cost` per call → exact `$/1000 docs` + `$/mo`).
- **Inputs:** 30 real DEEP-tier articles frozen read-only from prod `nlp_db` (`assemble`),
  balanced across extraction-relevant buckets: earnings 6, m&a 6, general 6, macro 5,
  management 5, thin 2. Same rendered `DEEP_EXTRACTION` prompt + prod decode params
  (`temperature=0`, `response_format=json_object`, `max_tokens=4096`) for every config.
- **Judge (held constant):** `deepseek-ai/DeepSeek-V3.1`, independent of every candidate
  (self-preference guard). 1–5 per dimension: **Precision** (no fabrication), **Recall**
  (coverage), **Adherence** (allow-list / vocab / direction compliance = the entity-accuracy proxy).
- **Cost projection:** authoritative per-doc cost × **4,500 DEEP docs/day** × 30. Scales linearly —
  if the real firehose is higher, multiply accordingly.
- **Sample size caveat:** n=30 articles × 8 configs = 240 judged extractions. This is a
  **preliminary read** (good enough to rank + separate the two levers); a production go/no-go
  should widen to ≥100 docs and tighten the judge tolerance. api_error and JSON-validity failures
  were **0%** across all configs at these effort levels.

## Comparison table (n=30, judge = DeepSeek-V3.1)

`F1h` = harmonic mean of judge Precision & Recall (1–5 scale; **not** set-based F1 — the judge
scores ordinally, no TP/FP counts). `Entity/schema acc` = Adherence dim + allow-list violations/art.
Yield = mean items extracted per article.

| Config (model × effort) | Prec | Rec | F1h | Adher (ent-acc) | Fab/art | Violn/art | API-err | JSON-fail | p50 s | p95 s | ev/art | cl/art | rel/art | $/1k docs | **$/mo** | Δoverall vs base |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `Qwen3-235B@medium` ⭐**baseline (live)** | 3.23 | 2.80 | 3.00 | 3.07 | 2.13 | 0.67 | 0% | 0% | 67.6 | 96.4 | 2.20 | **2.67** | **5.90** | $1.041 | **$140.5** | — |
| `Qwen3-235B@low` | 3.43 | 2.90 | 3.14 | 3.40 | 2.00 | 0.73 | 0% | 0% | 74.8 | 130.2 | 2.43 | 2.73 | 5.57 | $1.044 | $140.9 | +0.21 |
| `Qwen3-235B@none` | 3.63 | 2.70 | 3.10 | 3.43 | 1.53 | 0.57 | 0% | 0% | 57.7 | 110.0 | 2.03 | 2.50 | 4.67 | $0.948 | $128.0 | +0.22 |
| `gpt-oss-120b@medium` | **4.27** | 2.63 | **3.26** | **4.60** | 0.13 | 0.10 | 0% | 0% | 57.3 | 93.1 | 1.57 | 1.63 | 2.47 | $0.546 | $73.7 | +0.80 |
| `gpt-oss-120b@low` | 4.37 | 2.10 | 2.84 | 4.83 | 0.23 | 0.07 | 0% | 0% | 13.5 | 32.3 | 0.60 | **0.17** | 2.13 | $0.292 | **$39.4** | +0.73 |
| `DeepSeek-V4-Flash` | 4.00 | 2.70 | 3.22 | 3.83 | 0.83 | 0.30 | 0% | 0% | **7.2** | **17.1** | 2.23 | 1.27 | 4.00 | $0.563 | $76.0 | +0.48 |
| `Qwen2.5-72B-Instruct` | 3.87 | 2.57 | 3.09 | 4.17 | 1.03 | 0.30 | 0% | 0% | 46.5 | 64.6 | 0.70 | 1.23 | 3.97 | $2.066 | $279.0 | +0.50 |
| `Llama-3.3-70B-Instruct` | 3.50 | 2.67 | 3.03 | 3.73 | 1.40 | 0.40 | 0% | 0% | 57.7 | 95.4 | 1.63 | 2.00 | 4.10 | $0.714 | $96.3 | +0.27 |

Model availability: all target models resolved on the account **except**
`meta-llama/Meta-Llama-3.3-70B-Instruct` (404 → used `meta-llama/Llama-3.3-70B-Instruct`).
`DeepSeek-V3`, `V3.1`, `gpt-oss-20b` also available (V3 = $0.32/$0.89 /Mtok, too expensive; 20b
≈ 120b on cost so 120b is the real candidate — both dropped from the final table for signal).

## Two headline findings

1. **The judge ranks the live 235B baseline LAST on overall quality.** Not because it extracts
   less — it extracts the **most** (5.9 relations, 2.67 claims/art) — but because it **fabricates
   the most** (2.13 unsupported items/art, 0.67 allow-list violations/art), which tanks Precision
   (3.23) and Adherence (3.07). Every candidate is *more faithful*; the trade is **yield**. So
   "quality" splits into two axes the operator must weigh: **faithfulness** (judge-favoured) vs
   **graph richness / yield** (235B-favoured). This matches prior KG cleanups of junk relations.

2. **The `reasoning_effort` lever on 235B is NOT the cost win a sibling eval suggested.**
   `Qwen3-235B-A22B-Instruct-2507` is the **non-thinking Instruct** SKU; effort barely changes its
   output: **out-tokens/doc = medium 1057 ≈ low 1063 ≈ none 888.** Measured cost: medium **$140.5**,
   low $140.9, none **$128.0** → effort=none saves only **~$12/mo (9%)**, not the ~$100–130 claimed.
   (The 2× surcharge story applies to *reasoning* SKUs like gpt-oss: 120b@medium burns 2119
   out-tok/doc vs @low 624 → cost $73.7 vs $39.4.) **The cheap lever here is the model, not the effort.**

## Pricing reconciliation (`libs/ml-clients/pricing.py` is STALE)

Live DeepInfra standard-tier vs the matrix. The bake-off's `$/mo` uses the API's authoritative
`estimated_cost`, so it is correct regardless — but **cost tracking / dashboards driven by
`pricing.py` are wrong**, most importantly the baseline's output rate:

| Model | pricing.py in/out $/Mtok | live DeepInfra in/out | issue |
|---|---|---|---|
| Qwen3-235B-…-2507 | 0.071 / **0.10** | 0.09 / **0.55** | output **5.5× understated** → extraction cost under-reported |
| gpt-oss-120b | 0.09 / 0.45 | 0.037 / 0.17 | matrix too high (DeepInfra cut prices) |
| gpt-oss-20b | 0.04 / 0.16 | 0.03 / 0.14 | slightly high |
| DeepSeek-V4-Flash | 0.14 / 0.28 | 0.09 / 0.18 | too high |
| DeepSeek-V3 | (absent) | 0.32 / 0.89 | add |
| Qwen2.5-72B-Instruct | (absent) | 0.36 / 0.40 | add |
| Llama-3.3-70B-Instruct | (absent) | 0.10 / 0.32 (API-derived) | add |

**Action (separate PR):** refresh `MODEL_PRICING`, especially the 235B output rate.

## Recommendation — ranked, with the two levers separated

Baseline = `Qwen3-235B@medium`, measured **$140.5/mo**. **Do not flip anything yet.**

### Lever (a) — reasoning_effort on 235B (low-risk, no model swap)
- **`Qwen3-235B@none`**: saves **~$12/mo (9%)** AND scores *higher* on faithfulness (Precision
  3.23→3.63, fabrication 2.13→1.53). Cost: yield drops ~21% (relations 5.9→4.67). A near-free
  faithfulness win, but small $ — the effort knob is **not** where the money is.

### Lever (b) — model swap (yield-gated; the real cost lever)
Ranked for the operator's decision:

1. **Best cost/quality (balanced) — `DeepSeek-V4-Flash`.** **$76/mo, saves $64.5/mo (46%)**,
   **fastest by far (7.2s p50 vs 67.6s)**, quality above baseline (F1h 3.22, Adher 3.83), and it
   **preserves the most yield of any cheap option** (relations 4.0 = −32%, events 2.23, claims 1.27
   = −52%). Best all-round if ~half the claims-yield is acceptable.
2. **Quality-max on faithfulness / cheapest-acceptable — `gpt-oss-120b@medium`.** **$73.7/mo,
   saves $66.8/mo (48%)**, the **highest Precision (4.27) + Adherence (4.60)** and near-zero
   fabrication (0.13/art). **Gate:** yield halves (relations 2.47 = −58%, claims 1.63 = −39%).
   Pick this if a *cleaner, smaller* graph beats a bigger noisier one.
3. **Cheapest overall — `gpt-oss-120b@low` — $39.4/mo (−72%). REJECT for the KG:** claims
   collapse to **0.17/art** (near-zero, confirming the sibling's n=8 signal at scale). Only viable
   if claims are not needed.
4. `Llama-3.3-70B` ($96, −31%) and `Qwen2.5-72B` (**$279, +99% — more expensive**) are dominated.

### Quality-max on graph RICHNESS
Stay on **235B** (optionally `@none` for the small faithfulness+cost win). Nothing else matches
its 5–6 relations/article; the cost of that richness is fabrication the judge penalises.

## Config change to flip a winner (do NOT apply yet)

Single env var on S6 (`services/nlp-pipeline`), no code change:

```
NLP_PIPELINE_EXTRACTION_API_MODEL_ID=deepseek-ai/DeepSeek-V4-Flash    # balanced pick
# or
NLP_PIPELINE_EXTRACTION_API_MODEL_ID=openai/gpt-oss-120b              # faithfulness pick
```

- **No image rebuild** — it's a runtime env var (pydantic-settings). Set it in the S6 deployment
  env and roll the pods.
- For gpt-oss, also confirm reasoning effort: `ML_CLIENTS_EXTRACTION_REASONING_EFFORT=medium`
  (prod default is `low`; **`gpt-oss@low` is rejected above** because it kills claims). gpt-oss
  needs an explicit effort or it emits empty `content`.
- The 235B-effort lever (a) is `ML_CLIENTS_EXTRACTION_REASONING_EFFORT=none` (also no rebuild) —
  but it only buys ~$12/mo, so treat it as a faithfulness tweak, not a cost play.

## Raw artifacts (re-inspectable)
`docs/audits/2026-07-16-extraction-model-bakeoff-artifacts/`: `report.md`, `aggregate.json`,
`judge_scores.json` (per-doc P/R/A + justifications), `model_runs_metrics.json` (per-doc tokens +
estimated_cost + yield counts; raw model outputs omitted to respect the 500KB repo limit and are
regenerable). Golden set is regenerable read-only via `extraction_quality_eval.py assemble` (not
committed — contains prod article text).
