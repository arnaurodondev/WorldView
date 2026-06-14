# Learned Router — 24h Shadow Analysis & Go/No-Go (PLAN-0111 C-6)

**Date:** 2026-06-13 (scheduled 24h analysis after shadow deploy `03f4933fe`)
**Verdict: NO-GO.** Do not flip `NLP_PIPELINE_LEARNED_ROUTER_MODE` to live. A train/serve
skew makes the live gate over-suppress; the model itself is fine.

## Shadow distribution (469 articles, ~24h)

| | DEEP | MEDIUM | LIGHT |
|---|---|---|---|
| Static (actual, controls processing) | 78.7% | 19.6% | 1.7% |
| Learned (proposed) | **0%** | 19.8% | **80.2%** |

- Agreement **5.3%**; mean p_yield **0.434**, **max 0.790** (nothing cleared the 0.80 DEEP cut).
- Cross-tab: deep→light **293**, deep→medium 76, deep→deep **0**, medium→light 75, medium→medium 17, light→light 8.
- Ambiguous-band (p_yield ∈ [0.48, 0.68]) = 33.5%.
- (Note: this window's static split is DEEP-heavy vs the 30-day Ch5 split 56.9/31.8/11.2 — a separate observation.)

## Root cause — train/serve skew (CONFIRMED)

Live call site (`article_consumer._run_learned_router_shadow`) passes **`subtitle=None`**, so the
classifier text is **title only**. The model was trained on **`title + subtitle`** (the C-3 dataset's
first-chunk lede). Live therefore embeds half the input the model expects.

Empirical confirmation (offline, same committed joblib, on live down-routed docs):

| Article | live p_yield (title-only) | offline title-only | **+ subtitle** |
|---|---|---|---|
| Lam Research analyst target | 0.398 | 0.398 | **0.717** |
| Genmab Epcoritamab data | 0.414 | 0.414 | **0.639** |
| Oracle stock plummeting | 0.261 | 0.261 | **0.596** |
| Air Canada / IAMAW agreement | 0.412 | 0.415 | **0.689** |
| Starbucks rally | 0.327 | 0.327 | **0.659** |
| DXC Claude AI promo | 0.424 | 0.424 | 0.524 |

- Offline **title-only ≡ stored live p_yield** → the live path has no *other* bug; the skew is solely the missing subtitle.
- The subtitle lifts p_yield +0.2–0.35, flipping 5/6 genuinely-extractable articles LIGHT→MEDIUM (crossing thr_extract 0.58) while correctly leaving junk LIGHT. Model quality (AUC 0.828) stands.

## Recommended fix (blocks C-7/C-8)

Provide the subtitle/lede at routing-time inference so live matches training. Design choice for the user:
- **(A, preferred)** Wire the lede into the live router: at the routing call site, derive the same
  text training used (first-chunk / first-section lede) and pass it as `subtitle`. Cheapest; preserves
  the evaluated title+subtitle model. Must reproduce the dataset's subtitle construction exactly to
  avoid a *new* skew (sections exist at routing time, stage 1; chunks may not — confirm the text source matches).
- **(B)** Retrain the model on **title-only** to match what's actually available at routing time, then
  re-run the ablation (title-only AUC will be lower than 0.828 — re-measure).

After the fix: redeploy shadow, re-accumulate ~24h, re-check the distribution, *then* C-7 (cascade) + C-8 (live flip).

## Minor
- `chunks.chunk_text` for the first chunk is a JSON envelope (not clean text) for some docs — a separate
  data-hygiene item to verify doesn't affect the lede the router would use.
- Live `predict` passes a numpy array to a model fit with feature names → harmless sklearn warning
  (order preserved, predictions correct). Optional: pass a named frame to silence it.

## Status
Held in SHADOW. No live flip. Tasks: #31 (shadow deploy + analysis) done; new fix task blocks #32.

## Post-fix update (2026-06-14, PLAN-0111 task #33 / C-6b)

Option A applied: `subtitle_from_lede` replicated verbatim from the C-3 dataset into
`services/nlp-pipeline/.../application/blocks/learned_routing.py`; the shadow call was MOVED to
after `run_embeddings_block` (safe — Sub-Plan B made chunk embedding universal, so routing only
needs to precede extraction) and now feeds the RAW first-chunk lede (chunk_index asc, first
non-null) as the subtitle. Image rebuilt `--no-cache` + force-recreated; model still loads
(`learned_router_loaded`, 15,006 training rows).

**Offline reproduction over all 469 shadow docs** (same committed joblib + real EmbeddingGemma
adapter, structured features from `feature_scores_json` in meta order):

| | DEEP | MEDIUM | LIGHT |
|---|---|---|---|
| Learned proposed (pre-fix, title-only) | 0% | 19.8% | 80.2% |
| **Learned proposed (post-fix, title+lede)** | **10.6%** | **73.1%** | **16.3%** |

- The deep→light collapse is gone; the distribution is now a healthy mix.
- **Skew closed (live≡offline):** offline title-only ≡ stored live `learned_p_yield` on every
  sampled doc (`match_title_only=True`), confirming the live path had no other bug. Adding the lede
  lifts p_yield +0.18–0.35 (e.g. 0.398→0.750, 0.414→0.639, 0.261→0.556), matching the §"Root cause"
  table above. The live container runs byte-identical code, so the fixed live path equals the
  post-fix column.
- Stays SHADOW; C-7 (cascade) + C-8 (live flip) await a clean 24h re-accumulation.

**Flagged follow-up (chunk-0 JSON envelope):** for ~71% of docs the first chunk is a JSON envelope
(`{"date":..., "title":..., ...}`) rather than clean body text. The fix faithfully reproduces
training (which used the same raw envelope), so it is correct — but the envelope-as-chunk-0 itself
pollutes the BGE retrieval index (post-Sub-Plan-B universal embedding) and makes training ledes
degenerate. Warrants its own task: fix chunking so chunk 0 is clean body, then retrain the router on
clean ledes.

Offline re-validation harness committed at `scripts/eval/_check_learned_router_parity.py`.
