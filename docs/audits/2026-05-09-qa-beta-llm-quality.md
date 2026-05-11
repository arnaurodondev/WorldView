# QA — LLM Step-by-Step Quality (PLAN-0087 beta-readiness)

**Audit agent**: LLM-quality specialist (parallel with R1-followup chat audit)
**VAs covered**: VA-1 (chat), VA-2 (intelligence), VA-3 (NLP/KG generation), VA-4 (retrieval embeddings), VA-8 (briefs), VA-10 (TrustScorer / answer quality)
**Date**: 2026-05-09
**Mode**: live-stack, read-only on code; live-test on running stack (`make dev`, 60+ containers healthy)
**Bar**: would a hedge fund analyst trust this output to make decisions?

---

## Headline

**8 LLM call sites graded. Two stand out:**

| Verdict | Sites |
|---|---|
| **A — production-ready** | Article relevance/sentiment (a), Embedding generation (h) |
| **B — usable with one fix each** | Brief generator (g), Chat orchestrator (f) |
| **C — works in places, dangerous overall** | Mention resolution (c) |
| **F — broken / silently degraded** | Deep extraction (b), Narrative generation (d), Entity enrichment (e) |

Three of eight LLM call sites are **demo-blocking quality regressions**: the relation-extraction pipeline produces zero organic relations (b), the narrative worker writes JSON-error envelopes as user-facing prose for the 8 most demo-critical entities (d), and the enrichment worker has populated descriptions for only 8 of 330 entities — and those 8 are all hand-seeded (e).

The chat layer's **upstream quality crisis** (b/d/e) drives most of the 503s and "0 items" tool calls reported in the chat-tool-quality audit (`2026-05-09-qa-chat-tool-quality.md`). Even a perfect orchestrator cannot answer questions when the KG is structurally empty.

---

## 1. Per-step grade table

| ID | Step | Model(s) | Sample | Grade | Demo-blocker? |
|----|------|----------|--------|-------|---------------|
| **a** | Article relevance + sentiment scoring (S6 ArticleRelevanceScoringWorker) | Llama-3.1-8B-Instruct-Turbo via DeepInfra | 10 articles | **A−** | No |
| **b** | Deep extraction (relations / events / claims) | Llama-3.1-8B (DeepInfra) — tagged `deepinfra` in usage log | 1141 calls / 18 relations | **F** | YES (HF-7, drives D-Q-010) |
| **c** | Unresolved-resolution worker (mention → canonical_entity) | Llama-3.1-8B (DeepInfra) | 415 mentions | **C** (36.9 % win-rate) | Partial (hits A4/A6/A7 quality) |
| **d** | KG NarrativeGenerationWorker | Llama-3.1-8B-Instruct (DeepInfra) | 8 LLM + 322 template | **F** | YES (HF-3 narrative tab) |
| **e** | Entity enrichment (Worker 13E ProvisionalEnrichmentWorker, 13J StructuredEnrichmentWorker) | Llama-3.1-8B-Instruct (DeepInfra) | 330 canonicals | **F** | YES (HF-7 instrument page) |
| **f** | S8 chat orchestrator (DeepSeek R1 Distill 32B → DeepInfra) | DeepSeek R1 Distill 32B / Qwen3-235B-A22B | 4 fresh prompts (augments R1-followup's 13) | **B** | One unfixed gap (citation marker placement) |
| **g** | Brief generator (morning + instrument briefs) | DeepSeek R1 Distill 32B / Qwen3-235B-A22B | 1 morning + 3 instrument briefs (AAPL, NVDA, MSFT) | **B+** | Minor (fact direction in NVDA) |
| **h** | Embedding generation (BGE-large via DeepInfra) | BAAI/bge-large-en-v1.5 (DeepInfra) + bge-large (Ollama) | 598 chunks + 589 entity-rows | **A** for vector ops; **C-** for **what is being embedded** | No (substrate OK; content layer F) |

**Sample-mean quality** column is pushed into the per-step sections below.

---

## 2. Step a — Article relevance + sentiment scoring (Grade A−)

### Findings

- 136 LLM scores, 100 % on Llama-3.1-8B-Instruct-Turbo (DeepInfra). Zero failures, zero error_code.
- Score range [0.0, 0.9], 100 % within [0,1] bound, **0 hallucinated values out of range**.
- Score distribution: avg 0.66, quantized cleanly to {0.3, 0.6, 0.9} as specified by the prompt anchor in `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/article_relevance_scoring_worker.py:50-67`.
- 10-row spot-check **agrees with human judgement**:
  - "Stock Market Today, May 8: Nasdaq Gains 1.7%…" → 0.9 (correct)
  - "Nvidia, Apple and Microsoft may be trading at best valuations…" → 0.9 (correct)
  - "Friday's big stock stories…" → 0.3 (correct, generic)
  - "AmbiguousParameterError-asyncpg" (a leaked dev-error article) → 0.3 (correct)
  - "Warren Buffett's McLane makes major bet on driverless big rigs" → 0.6 (correct, indirect)
- Sentiment classification: 8/8 sample agreed with human judgement. No hallucinated enum values (`positive|negative|neutral|mixed` only).

### Concerns

1. **Two-source coverage gap** — only 136 scores written but 415 mentions exist across articles. The relevance worker is keeping up with intake, but ~50 % of articles haven't been LLM-scored; they fall back to routing-tier-only scoring.
2. **Article quality leak**: an article literally titled `BP-235` (a worldview internal bug pattern) reached the corpus. Not LLM's fault, but feeds the model junk.
3. **No three-significant-figures granularity** — score values are quantized to 0.3/0.6/0.9 (the prompt's anchor levels). For UI display this is fine, but for retrieval ranking it collapses into 4 levels and reduces ranking precision.

### Why A− not A

Coverage is at ~33 % of corpus. Quality is excellent on what gets scored.

---

## 3. Step b — Deep extraction (Grade **F** — demo-blocker)

### Headline

**1141 LLM extraction calls in `llm_usage_log` produced 0 organic `relation_evidence_raw` rows and 0 `relation_evidence` rows.** All 18 rows in `relations` are hand-seeded entities (UUID prefix `11111111-…`) with `evidence_count = 1` each. This means the entire deep-extraction pipeline is a **no-op at the persistence layer**.

### Findings

- `intelligence_db.relations` total: 18 (3 EXPOSED_TO_THEME × 13, COMPETES_WITH × 4, SUPPLIER_OF × 1)
- `intelligence_db.relation_evidence_raw`: 0
- `intelligence_db.relation_evidence`: 0
- `intelligence_db.llm_usage_log` for capability=`extraction`: 1141 successful calls, avg 3442 ms, 0 failures
- The 18 relations have `first_evidence_at = 2026-05-07` — i.e. seeded 2 days ago and untouched since.
- Demo-critical entities OpenAI, Tesla, Meta, JPM, XOM have **zero outgoing or incoming relations**.

### Likely root cause(s)

The audit memory entry `project_pipeline_quality_2026_04_30` already documented a "silent drop in `_build_raw_*` (entity_id_by_ref miss); 7 of 11 GLiNER classes have ZERO canonicals; 66 % of docs have 0 entities resolved." That cause appears not fully fixed:

- **Mention-class mismatch (already documented as F-CRIT-07)** — the GLiNER-NER produces `organization` mentions for Apple/Intel/Microsoft/etc., but the canonical entity is stored as `financial_instrument`. The deep-extractor's relation-side resolver looks up by exact mention_class match, so subject/object are never both resolved → relation cannot be persisted.
- **`llm_usage_log.model_id` literally stores the value `"deepinfra"` (the provider token), not the model name** (`Meta-Llama-3.1-8B-Instruct`). This is a logging defect that obscures observability.

### Severity for demo

**HF-7 (KG isolated nodes for Apple/Microsoft/OpenAI/NVIDIA/Meta).** Compounds with D-Q-010 from the chat audit. If a director asks "Apple ↔ NVIDIA?" or "Tesla competitors", the system has no edges to surface.

### Recommendations

1. **F-LLM-001 (P0)** — fix the relation extractor's canonical-entity resolution to fall back from `organization` to `financial_instrument` (or company) when a ticker-form canonical exists. Estimated 2 h. Without this, every dollar spent on the 1141 extraction LLM calls is wasted.
2. **F-LLM-002 (P0)** — fix `llm_usage_log.model_id` write so the actual model identifier is logged. Currently makes incident triage impossible. 30 min.
3. **F-LLM-003 (P1)** — emit a `relation_evidence_raw` row even when entity resolution fails, with `entity_provisional=true`. Today the path silently drops; we should be queueing for later resolution.

---

## 4. Step c — Unresolved-mention resolution (Grade C)

### Findings (from `nlp_db.entity_mentions` + `mention_resolutions`)

| Metric | Value |
|---|---|
| Total entity_mentions | 415 |
| Mentions with `resolved_entity_id` populated | 69 (16.6 %) |
| `resolution_outcome = noise` | 34 |
| `resolution_outcome = unresolved` (default) | **381 (91.8 %)** |
| `resolution_outcome = resolved` | **0** |
| `resolution_outcome = ambiguous` | 0 |
| Total mention_resolutions rows | 1347 |
| Mentions reaching at least 1 winner-row | 153 / 415 (36.9 %) |
| Stage-3 winning score (LLM stage) | avg 0.16 |

### Defects

- **Outcome-column never set to `resolved`** — even when `resolved_entity_id` is populated, `resolution_outcome` stays `unresolved`. Looks like a write-back bug in the worker.
- **Mention-class mismatch is the primary leak** (same root cause as step b). 57 mentions of "Apple" + 30 of "Intel" + 5 of "Microsoft" + 8 of "Nvidia" remain unresolved because they are tagged `mention_class=organization` while the canonicals exist as `financial_instrument`.
- **0/61 mentions resolved at LLM stage 4** (max stage). Stage 4 has 245 attempts but 3 winners → 1.2 % success rate. The LLM disambiguation prompt is **almost never confidently picking** a candidate.
- Avg winner-score 0.083 — most "winners" win by virtue of being the only candidate, not by high confidence.

### Why C not F

Noise classification (34 mentions) appears correct (e.g. "company", "Yahoo", "U.S.", "company"). When the system DOES resolve (153 mentions), the bindings appear correct in spot-check (AAPL→Apple Inc., S&P 500→index, Warren Buffett→person).

### Recommendations

1. **F-LLM-004 (P0)** — fix mention-class fallback (org → financial_instrument), same root cause as step b. **One fix unlocks both extraction and resolution.**
2. **F-LLM-005 (P1)** — fix `resolution_outcome` write-back so the column reflects reality.
3. **F-LLM-006 (P2)** — investigate why stage-4 LLM disambiguator picks no winner in 99 % of stage-4 cases. Is the threshold too high, or is the prompt asking the wrong thing? Today the stage is dead weight.

---

## 5. Step d — KG NarrativeGenerationWorker (Grade **F** — demo-blocker)

### Findings

- 330 narratives in `entity_narrative_versions`. 322 use `model_id = template-v1` (deterministic fallback). 8 use `meta-llama/Meta-Llama-3.1-8B-Instruct`.
- All 8 LLM-tagged narratives are **literal JSON error strings** stored as the user-facing prose:

| Entity | Stored narrative_text |
|---|---|
| Intel Corporation | `{ "error": "The provided input is empty or invalid. Please supply valid information…" }` |
| Netflix, Inc. | `{ "error": { "message": "No response from model", "type": "api_error" … } }` |
| Coinbase Global Inc. | `{ "error": { "message": "The model gpt-3.5-turbo does not exist or you do not have access to it." } }` |
| OpenAI | `{ "error": { "message": "The input data is empty or invalid.", … } }` |
| Anthropic | `{ "error": { "message": "The model gpt-3.5-turbo does not exist…" } }` |
| QUALCOMM Incorporated | `{ "error": { "message": "No entity provided." … } }` |
| Advanced Micro Devices, Inc. | `{ "error": { "message": "The model gpt-3.5-turbo does not exist…" } }` |
| Alphabet Inc. Class C | `{ "error": { "message": "The model gpt-3.5-turbo-instruct does not exist…" } }` |

These are exactly the 8 demo-critical entities — Apple, Microsoft, NVIDIA narratives are template-v1 fallbacks (boring but harmless), but Intel/Netflix/Coinbase/OpenAI/Anthropic/QUALCOMM/AMD/GOOG (Class C) **render JSON garbage in the Intelligence tab** if surfaced.

### Root cause and fix-presence audit

- The fix exists in source: `services/knowledge-graph/src/knowledge_graph/application/use_cases/generate_narrative.py:469-475` adds a `looks_like_error` JSON envelope detector. Verified on disk with `grep "looks_like_error"`.
- The fix is **NOT live in the running container's importable code**:
  - `/app/src/.../generate_narrative.py` (source, mounted) → 2 occurrences of `looks_like_error` (fix present)
  - `/app/.venv/lib/python3.11/site-packages/knowledge_graph/.../generate_narrative.py` (installed copy) → 0 occurrences (fix absent)
  - The container's PYTHONPATH resolves the venv copy first, so the production runtime is using the **un-fixed** code path.
- As of 2026-05-09 18:36:14Z (the most recent narrative regen), the unfixed worker generated 8 bad rows and stopped (likely because the regen job covered only those 8 entities first).

### Concerns beyond the JSON-error data

- **The LLM literally hallucinated that gpt-3.5-turbo is the active model**. This betrays the model is not following its actual identity. We must verify the prompt does not include "gpt-3.5-turbo" anywhere; if it does, this is a prompt-template defect.
- The "good" narratives (template-v1) average 33 words — far below PRD §3.3's implicit "≥100 words for finance-grade prose". Even when the system path runs cleanly, output is too thin to be useful.
- Word-count constraint check `length(narrative_text) >= 50 AND length(narrative_text) <= 10000` — the check is character-based, while word_count column shows ≤39. Inconsistency.

### Recommendations

1. **F-LLM-007 (P0, demo-blocker)** — repackage the knowledge-graph venv install or remove the venv copy so the editable source is the only path. Short term: `docker exec worldview-knowledge-graph-1 cp /app/src/knowledge_graph/application/use_cases/generate_narrative.py /app/.venv/lib/python3.11/site-packages/knowledge_graph/application/use_cases/generate_narrative.py && docker restart worldview-knowledge-graph-scheduler-1`. Then trigger narrative regen for the 8 broken entities. 1 h.
2. **F-LLM-008 (P0)** — DELETE the 8 bad narrative rows (or set `is_current=false`) before any demo. They are visible to the Intelligence tab. 5 min.
3. **F-LLM-009 (P1)** — increase the `_MIN_NARRATIVE_LEN` threshold to 400 chars / ~80 words. Today's 50-char minimum lets through the JSON-error envelope (which is ~150 chars) and the trivial template fallback.
4. **F-LLM-010 (P1)** — investigate the prompt that produces "model gpt-3.5-turbo does not exist" output. Likely the FallbackChain is calling a different provider (OpenRouter?) with a stale model name. Trace through `ml_clients.fallback_chain`.

---

## 6. Step e — Entity enrichment (Grade **F** — demo-blocker)

### Findings

- `canonical_entities`: 330 rows total
- `description IS NOT NULL`: **8 rows** (2.4 %)
- All 8 are **hand-seeded** demo entities with concise (90-118 char) factual descriptions (Intel, GOOG-C, Netflix, Coinbase, QUALCOMM, AMD; verified by canonical_name pattern).
- **0 of 322 unsealed entities have an LLM-generated description.**
- `enrichment_attempts > 0` for the 322 entities — the worker IS being invoked, but produces nothing storable.
- `provisional_entity_queue`: 60 in `processing`, 11 in `noise`, 1 in `resolved`. Effectively jammed.

### Severity

**HF-7 (instrument page deep-dive).** When Phase B B5 happens (director types any ticker), if it's not one of the 8 hand-seeded entities, the description, narrative, and intelligence tab are all empty/template-only.

### Recommendations

1. **F-LLM-011 (P0)** — the same install-vs-source skew likely affects the StructuredEnrichmentWorker. Audit `provisional_enrichment_core.py` and `structured_enrichment_worker.py` in the venv for parity with the source tree.
2. **F-LLM-012 (P0, demo-shaping)** — for the demo-critical 12 tickers (AAPL, MSFT, NVDA, GOOGL, META, OPENAI, TSLA, AMZN, JPM, XOM, UNH, COIN), hand-seed descriptions via `ALTER canonical_entities` SQL. Already done for 8 of these — extend to the other 4.

---

## 7. Step f — S8 chat orchestrator (Grade B)

This step largely re-validates the chat-tool-quality audit. I added 4 fresh prompts after the cache flush, augmenting that audit's 13 prompts.

### Live re-test results (post-D-Q-001 fix)

| Prompt | Tool selected | Provider populated? | Citations populated? | `[N#]` markers in answer? | Quality |
|---|---|---|---|---|---|
| "What is Apple latest revenue?" | `get_fundamentals_history` | YES `deepinfra` (D-Q-001 fixed) | 1 | NO | A− factual / B− attribution |
| "What are Apple latest fundamentals?" | `get_fundamentals_history` | YES | 1 | NO | A− / B− |
| "What is the latest on NVIDIA?" | search_documents → 503 | n/a | n/a | n/a | F (down-stream) |
| "Compare Apple and Microsoft revenue trends" | `compare_entities` + `get_fundamentals_history` | YES | (response truncated, but had numbers) | not seen | B factual; needs full grade |
| "Show me earnings this week" | get_earnings_calendar → 503 | n/a | n/a | n/a | F (down-stream JWT issue D-Q-007) |
| "Who are Tesla's competitors?" | search_entity_relations → 503 | n/a | n/a | n/a | F (KG empty — step b consequence) |
| "What is driving the energy sector?" | **(no tool — model knowledge only)** | YES | 0 | NO | C — convincing prose, ZERO citations on a market question — hallucination risk |

### New observations

- D-Q-001 (provider name) is **fixed in the running container** — confirmed via two live runs.
- D-Q-002 (citation markers) is **NOT yet fixed in production** — the LLM is producing factual answers without `[N#]` markers, and the orchestrator isn't injecting them. The retrieved citations (count=1 for AAPL questions) DO surface in the API response's `citations[]` array, so the frontend has data — but the answer prose doesn't reference [N1] inline. Frontend would need to render citations as a separate "Sources" footer rather than inline.
- "What is driving the energy sector?" answered with **5 numbered points and zero tool calls / zero citations**. This is a prose-grade hallucination risk: a director would assume the answer is grounded in current data, but it is pure model-knowledge from training cutoff. The orchestrator should either route to news/search OR add a `[Note: from training data, not live retrieval]` disclaimer.

### Recommendations

1. **F-LLM-013 (P0)** — D-Q-002 carry-over: prompt the model to insert `[N1]…[Nk]` markers. Already prescribed in chat-tool-quality audit §4.
2. **F-LLM-014 (P1)** — add an explicit "if no tool was useful, prefix the answer with 'Based on general knowledge: …'" instruction to the system prompt. Hedge-fund analysts will not tolerate confidently-numbered prose without provenance.
3. **F-LLM-015 (P2)** — increase tool-routing aggressiveness for sector / theme questions ("driving the energy sector"). Today the model treats them as general knowledge; they should call `search_documents(sector_filter)` or equivalent.

---

## 8. Step g — Brief generator (Grade B+)

### Findings (1 morning + 3 instrument briefs sampled live)

#### Morning brief — verdict A−

- **Headline-quality, multi-section markdown** (4 sections: Semiconductor / Apple Supply Chain / Market Sentiment / Earnings & Operations).
- 8 citations populated, all linkable to real article URLs (finnhub.io news IDs).
- Article references match the cited content (verified Intel-Apple deal articles).
- Inline timestamps appear: `*(as of 2026-05-09)*` — correct date.
- **Format violation**: uses `[c2]…[c8]` markers instead of `[N1]…[Nk]` per PRD §3.3. Frontend needs to parse `[c#]`.
- **Persistence defect**: `id=null`, history empty (`{"items":[],"total":0}`). Brief is generated on-the-fly each call but **not persisted to `rag_db.user_briefs`**. This breaks the morning-brief-history feature (PLAN-0066 Wave B).

#### AAPL instrument brief — verdict B

- Coherent prose. Real citations.
- Section-template structure: LEAD / DETAILS / Entity Overview / Price & Fundamentals (`Not available in retrieved context`) / Recent Developments / Entity Relationships
- "Not available" honest empty-state copy is **good** (per PRD §3.3 quality bar)
- **Hallucination risk**: "A supplier relationship exists, though the specific entity is not identified in context [c1]" — `[c1]` is the AAPL ROIC article, not a supplier-relationship source. Citation misalignment.

#### NVDA instrument brief — verdict B−

- 1115 chars / 2 citations
- **Factually inverted relation surfaced**: "Apple Inc. is a customer of NVIDIA, with supplier relationship confirmed at 75 % confidence" + "NVIDIA supplies components to Apple Inc." — Apple does NOT buy NVIDIA chips for products (they make their own M-series). The 75 % confidence comes from a seeded `SUPPLIER_OF` relation (NVDA→AAPL) that is itself questionable seed data.
- Otherwise factually plausible (AI exposure, US-China tensions).

#### MSFT instrument brief — verdict C

- 873 chars / **0 citations** even though `[c1]…[c5]` markers appear in body — citation map broken
- "Not available in retrieved context [cN]" — leaks **literal `[cN]` placeholder** into user-facing prose (HF-8 territory)
- "Microsoft competes with unspecified entities with confidence scores of 80 %, 85 %, and 82 % [c3][c4][c5]" — explicitly admits the relation is missing object name. This should be filtered, not surfaced.

### Recommendations

1. **F-LLM-016 (P0)** — fix `[cN]` placeholder leakage in instrument briefs. Either the fallback string `"Not available in retrieved context [cN]"` is hardcoded, or the LLM is filling in `[cN]` literally because the prompt example uses `[cN]`. 30 min audit.
2. **F-LLM-017 (P0)** — when relation exists but `object_name IS NULL` or `"unspecified"`, **drop the relation from the brief context**. Today MSFT brief surfaces 3 anonymous competitors with bare confidences. 30 min.
3. **F-LLM-018 (P1)** — review seeded SUPPLIER_OF relation NVDA→AAPL. This is factually wrong and propagates into briefs. Alternatively allow it but ensure citations in the brief actually attest the relation (today they don't).
4. **F-LLM-019 (P1)** — wire brief persistence so `id` is populated and rows land in `user_briefs`. Today the brief generator works but is non-cacheable, so cold load every time → latency cost on dashboard.
5. **F-LLM-020 (P2)** — switch brief markers from `[c#]` to `[N#]` to align with PRD §3.3. Frontend must support this anyway for chat. Standardise on one.

---

## 9. Step h — Embedding generation (Grade A vector ops; **C− content**)

### Vector-mechanics — Grade A

- 598 chunks embedded. 1024-dim across the board. 100 % populated.
- 2 model providers active: `BAAI/bge-large-en-v1.5` (DeepInfra, 536 chunks) + `bge-large` (Ollama fallback, 62 chunks). Healthy fallback ratio.
- Spot-check on 100-row sample: e1 range [-0.0329, 0.0652], stddev 0.020 → reasonable variance, NOT a constant or near-zero vector. No NaN/null detected.
- HNSW indexes on all three view types (definition, narrative, fundamentals_ohlcv) confirmed present.

### Content alignment — Grade **C−**

| view_type | rows | populated | notes |
|---|---|---|---|
| definition | 330 | 267 (81 %) | **Critical gap: of these 267, 267 have `description IS NULL`** in canonical_entities. Embedding source is unclear — likely just the `canonical_name` string (3-5 words). |
| narrative | 330 | 322 (97 %) | **All 322 are over `template-v1` narratives** (33-word generic strings). Vector signal is near-identical across entities. |
| fundamentals_ohlcv | 61 | **0** | **Entire view non-functional.** Rows exist but `embedding IS NULL`. |

### What this means for retrieval

- Definition-view ANN search will return mostly junk because there's nothing to embed beyond entity names.
- Narrative-view ANN search will collapse every entity to roughly the same vector cluster.
- Fundamentals-view ANN search returns zero results.
- Chunk-embedding (the chat retrieval substrate) is healthy — this is why chat answers using `search_documents` (when not 503'd by step b) do produce relevant articles.

### Recommendations

1. **F-LLM-021 (P0)** — fix the entity-description backfill (step e dependency). Cannot fix definition-view embeddings until descriptions exist.
2. **F-LLM-022 (P0)** — fix narrative generation (step d). Cannot get useful narrative embeddings while 97 % of inputs are templates.
3. **F-LLM-023 (P1)** — investigate why `fundamentals_ohlcv` view type writes a row but never an embedding. Likely the worker fetches OHLCV data but the data is stale/empty (61 rows = 1 view per financial_instrument; market data freshness check).
4. Keep Ollama-bge fallback in production — its 62/598 share confirms it's working as a real fallback.

---

## 10. Cross-cutting findings — F-NNN format

These are the most critical issues, ranked by demo-day impact.

```yaml
- id: F-LLM-001
  severity: HF-7 (demo-blocker)
  surface: A4 KG tab, A6 chat news, A7 chat intelligence, B3-B6 hands-on
  problem: |
    1141 LLM extraction calls produce ZERO organic relations. All 18 stored
    relations are hand-seeded. KG tab will show isolated nodes for any entity
    the user inspects beyond the 8 seed canonicals.
  root_cause: |
    Mention-class mismatch — GLiNER NER tags Apple/Intel/Microsoft as
    `organization`, but canonical entities are `financial_instrument`. The
    relation extractor's resolver requires exact class match.
  fix_effort: 2h (single resolver tweak)
  fix_priority: P0 — must fix before demo or trim KG tab from path

- id: F-LLM-002
  severity: SF-3
  surface: cross-cutting observability
  problem: |
    `intelligence_db.llm_usage_log.model_id` is literally writing the string
    "deepinfra" (the provider token), not the model name. Makes incident
    triage and cost-attribution by-model impossible.
  fix_effort: 30 min
  fix_priority: P0

- id: F-LLM-007
  severity: HF-3 / HF-8
  surface: A4 Intelligence tab for Intel/Netflix/Coinbase/OpenAI/Anthropic/QUALCOMM/AMD/GOOG-C
  problem: |
    The narrative worker stored JSON-error envelopes as user-facing
    narrative_text for the 8 most demo-critical entities. The bug-fix
    (looks_like_error guard, commit on 2026-05-09) is in source but NOT in
    the venv copy that the running container imports.
  evidence: |
    /app/src/.../generate_narrative.py — fix present
    /app/.venv/lib/python3.11/site-packages/knowledge_graph/.../generate_narrative.py — fix absent
  fix_effort: 1h (cp + restart + regen)
  fix_priority: P0 — director WILL hover over Intel/OpenAI/etc.

- id: F-LLM-008
  severity: HF-8 (effective)
  surface: A4 Intelligence tab
  problem: |
    8 narrative_versions rows for demo-critical entities contain raw JSON
    error strings as `narrative_text`. Even after F-LLM-007, these bad rows
    are `is_current=true`.
  fix_effort: 5 min (UPDATE entity_narrative_versions SET is_current=false WHERE model_id LIKE 'meta%' AND narrative_text LIKE '{%')
  fix_priority: P0

- id: F-LLM-016
  severity: HF-8
  surface: A4 News/Intelligence tab, instrument briefs
  problem: |
    Instrument briefs for entities with sparse data leak the literal string
    "Not available in retrieved context [cN]" into user-facing prose.
  fix_effort: 30 min
  fix_priority: P0

- id: F-LLM-013
  severity: HF-3
  surface: A6/A7/A8 chat answers
  problem: |
    Chat orchestrator returns factual answers (e.g. AAPL fundamentals) with
    citations populated in API response, but answer prose lacks `[N#]`
    markers — frontend cannot render inline citations. Carry-over from
    chat-tool-quality D-Q-002.
  fix_effort: 1h
  fix_priority: P0

- id: F-LLM-014
  severity: SF-3 (hallucination risk)
  surface: A6/A8 chat
  problem: |
    Chat returns confident-sounding numbered prose (e.g. "What is driving the
    energy sector?") with ZERO tool calls and ZERO citations — pure model
    training-data answer. A director will treat it as live data.
  fix_effort: 30 min (system prompt addition)
  fix_priority: P1

- id: F-LLM-017
  severity: SF-3
  surface: A4 Instrument page Intelligence tab
  problem: |
    Instrument briefs surface anonymous competitor relations like "Microsoft
    competes with unspecified entities with confidence scores of 80%, 85%,
    82% [c3][c4][c5]". These should be filtered out, not surfaced.
  fix_effort: 30 min
  fix_priority: P0

- id: F-LLM-021
  severity: SF-1 (NDCG suppression)
  surface: VA-4 retrieval substrate; chat news answers
  problem: |
    267/330 entity definition embeddings are over canonical_name only
    (no description). 322/330 narrative embeddings are over template-v1
    fallbacks. 0/61 fundamentals_ohlcv embeddings populated. Vector substrate
    is mechanically healthy but content-starved → ANN retrieval over entities
    is near-random.
  root_cause: |
    Cascade from F-LLM-007 (narrative) and F-LLM-011 (enrichment).
  fix_effort: dependent on F-LLM-007/011
  fix_priority: P0

- id: F-LLM-005
  severity: SF-3
  surface: cross-cutting observability
  problem: |
    `entity_mentions.resolution_outcome` is written 'unresolved' even when
    `resolved_entity_id` IS NOT NULL. Counts in the table are wrong by ~17%.
  fix_effort: 30 min
  fix_priority: P1
```

---

## 11. Summary recommendations — priority-ordered for the demo

### P0 — must fix before director sits down (estimated 7-9 h total)

1. **F-LLM-007 + F-LLM-008** — fix narrative venv-vs-source skew, regen 8 broken narratives, mark old rows non-current. **1.5 h.**
2. **F-LLM-001 + F-LLM-005** — fix mention-class fallback (org → financial_instrument). Single resolver tweak unlocks both extraction (step b) AND mention resolution (step c). Run a regen pass. **3 h.** *Highest leverage fix in this audit.*
3. **F-LLM-016 + F-LLM-017** — fix `[cN]` literal leakage and anonymous-relation surfacing in briefs. **1 h.**
4. **F-LLM-013 (D-Q-002 carry-over)** — citation marker prompting in chat orchestrator. **1 h.**
5. **F-LLM-012** — extend hand-seed coverage from 8 to 12 demo entities (description backfill SQL). **30 min.**

### P1 — fix if time permits

6. **F-LLM-002** — fix `llm_usage_log.model_id` to record real model names. **30 min.**
7. **F-LLM-014** — add "based on general knowledge" disclaimer for tool-less answers. **30 min.**
8. **F-LLM-019** — wire brief persistence to `user_briefs`. **1 h.**

### P2 — defer (track in deferred list)

9. **F-LLM-006** — investigate why stage-4 LLM disambiguation has 1.2 % win-rate.
10. **F-LLM-011** — broader audit of all worker venv-vs-source skew (likely structural; may need bigger Dockerfile fix).
11. **F-LLM-020** — standardise `[N#]` vs `[c#]` markers across chat + briefs.

### Strategic recommendation

The single highest-leverage fix in this audit is the **mention-class fallback (F-LLM-001 + F-LLM-005)**. It is **one resolver patch** and unlocks: (a) step b organic relation generation, (b) step c mention resolution win-rate from 36.9 % toward ~80 %, and (c) downstream KG-derived narrative content (step d) and entity descriptions (step e) once the regen runs. Without it, every other fix is stitching on a dam.

The narrative-venv skew (F-LLM-007) is **the single most director-visible defect**: the Intelligence tab renders raw JSON for the 8 most likely entity clicks. It is a 1-h fix.

If only ONE thing is fixed before the demo, fix F-LLM-007 + F-LLM-008.

---

## 12. Cross-checks performed

- `docker ps` — 60+ containers healthy at audit start.
- `make seed` had been run (415 mentions, 598 chunks, 330 canonicals consistent with seed-on baseline).
- 4 fresh chat prompts after Valkey FLUSHDB (verified by latency 800-9700 ms range).
- 1 morning brief + 3 instrument briefs (AAPL/NVDA/MSFT) generated live.
- `intelligence_db.entity_narrative_versions` ordered by generated_at — confirmed JSON-error rows are the LATEST writes (18:36:11Z onwards), proving the fix is not deployed.
- `docker exec ... grep -c "looks_like_error"` confirms source-vs-venv divergence in knowledge-graph container.
- `entity_embedding_state` view-type breakdown confirms the 0/61 fundamentals_ohlcv anomaly.
- Sample 100-row variance check on `chunk_embeddings` confirms vectors are non-degenerate (stddev=0.02).

---

## 13. Out of scope for this audit (would need follow-up)

- Latency budget per LLM call (only sampled p95 ≈ 9.7 s on AAPL fundamentals) — defer to performance audit.
- TrustScorer (PLAN-0079) output validation — surface not directly inspected; intelligence-tab callers (`/v1/entities/.../intelligence`) returning 200 was confirmed but content not graded. Defer.
- Path insight worker LLM quality — 0 path_insights rows in `path_insights` table at sample time; nothing to grade.
- Cost-per-query estimation — `estimated_cost_usd = 0.0` everywhere, so cost telemetry is not wired in. Separate defect.

---

**End of audit.**
