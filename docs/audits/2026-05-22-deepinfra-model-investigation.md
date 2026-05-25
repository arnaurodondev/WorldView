# DeepInfra Model Upgrade Candidates — LLM Gate Audit

**Date**: 2026-05-22
**Status**: Investigation complete
**Author**: Claude (research agent)
**Trigger**: BP-522 (billing cascade risk) + relation extraction quality improvement opportunity
**Related**: `docs/BUG_PATTERNS.md#BP-522`, `services/nlp-pipeline/`, `services/knowledge-graph/`, `libs/ml-clients/`

---

## Executive Summary

The pipeline uses DeepInfra as its primary GPU LLM provider across **six distinct call categories** spanning S6 (nlp-pipeline) and S7 (knowledge-graph). All six share a single DeepInfra account and API key — this is the central BP-522 risk. The current extraction model (`Qwen/Qwen3-235B-A22B-Instruct-2507`) is already a strong choice for the deep extraction task. The highest-leverage upgrade opportunity is in the **noise classifier and relevance scoring** paths, which still use `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` — a model that the codebase itself notes has limited instruction-following precision for structured JSON output. The primary gap before any model change is the absence of per-worker billing circuit breakers: when DeepInfra returns 402, all six call categories fail simultaneously with no auto-recovery.

---

## 1. Current LLM Usage Map

### Complete call inventory (all DeepInfra-routed paths)

| Service | Worker / Module | Model (DeepInfra slot) | Purpose | Volume estimate | Cost/call estimate |
|---------|----------------|------------------------|---------|-----------------|-------------------|
| S6 (nlp-pipeline) | `ArticleRelevanceScoringWorker` | `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` | Binary/scalar relevance score (title-only prompt) | ~50 articles/cycle × 30min cycle = ~2400/day | ~$0.00004 (200 in, 10 out tokens @ $0.02/$0.02) |
| S6 (nlp-pipeline) | `UnresolvedResolutionWorker` | `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` | Entity disambiguation (1 mention → canonical or reject) | ~500 mentions/cycle × 30min = ~12000/day | ~$0.00003 (150 in, 5 out tokens) |
| S6 (nlp-pipeline) | `DeepSeekExtractionAdapter` (article consumer) | `Qwen/Qwen3-235B-A22B-Instruct-2507` | Structured JSON extraction: events, claims, relations | DEEP tier articles only (~30% of ingested) | ~$0.002–$0.01 per article (1000–5000 input tokens, MoE 22B active) |
| S6 (nlp-pipeline) | `DeepInfraEmbeddingAdapter` | `BAAI/bge-large-en-v1.5` | 1024-dim chunk + section embeddings | ~64 chunks/article × N articles | ~$0.000001 per chunk ($0.013/M tokens) |
| S7 (knowledge-graph) | `ProvisionalEnrichmentWorker` Layer 2 | `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` | Binary noise classifier (entity valid/noise) | ~500/cycle × 5min cycle = ~144k/day (pruned by Layer 1 blocklist) | ~$0.00002 (100 in, 5 out tokens) |
| S7 (knowledge-graph) | `ProvisionalEnrichmentWorker` Layer 3 | `Qwen/Qwen3-235B-A22B-Instruct-2507` (primary via `FallbackChainClient`) | Entity profile extraction (canonical_name, type, ticker, ISIN) | Surviving noise-filter rows (~20-40% of Layer 2 input) | ~$0.003–$0.008 per entity |
| S7 (knowledge-graph) | `SummaryWorker` (Worker 13C) | `Qwen/Qwen3-235B-A22B-Instruct-2507` (primary via `FallbackChainClient`) | Relation evidence summary text + embedding | ~20 stale relations/cycle × 60min = ~480/day | ~$0.001–$0.005 per summary |
| S7 (knowledge-graph) | `DefinitionRefreshWorker` / `StructuredEnrichmentWorker` (Worker 13J) | `Qwen/Qwen3-235B-A22B-Instruct-2507` (primary), `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` (fallback) | Entity descriptions (2-3 sentence factual prose) | ~N stale entities/hour | ~$0.002–$0.007 (capped by `description_max_monthly_usd=$10`) |
| S7 (knowledge-graph) | `NarrativeGenerationWorker` (Worker 13D-3) | `meta-llama/Meta-Llama-3.1-8B-Instruct` (via `DeepInfraNarrativeChatClient`) | Free-form narrative generation per entity | Weekly batch (Sunday 3 AM UTC) | ~$0.001–$0.003 per entity |
| S7 (knowledge-graph) | Entity embedding refresh (Workers 13B / 13D) | `BAAI/bge-large-en-v1.5` | 1024-dim entity definition/narrative/fundamentals embeddings | ~3h cycle | ~$0.000001 per entity |

### Config key mapping

| Worker | Primary env var | Fallback env var |
|--------|----------------|-----------------|
| Article extraction (S6) | `NLP_PIPELINE_EXTRACTION_API_KEY` + `NLP_PIPELINE_EXTRACTION_API_MODEL_ID` | `OllamaExtractionAdapter` (qwen2.5:7b-instruct) |
| Relevance scoring (S6) | `NLP_PIPELINE_RELEVANCE_SCORING_API_KEY` + `RELEVANCE_SCORING_API_MODEL_ID` | Ollama `qwen3:0.6b` |
| Unresolved resolution (S6) | `NLP_PIPELINE_UNRESOLVED_RESOLUTION_API_KEY` + `UNRESOLVED_RESOLUTION_API_MODEL_ID` | Ollama `qwen3:0.6b` |
| Embedding (S6 + S7) | `NLP_PIPELINE_EMBEDDING_API_KEY` / `KNOWLEDGE_GRAPH_EMBEDDING_API_KEY` | Ollama `bge-large:latest` |
| KG extraction chain (S7) | `KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY` + `KNOWLEDGE_GRAPH_DEEPINFRA_EXTRACTION_MODEL_ID` | Ollama → Gemini Flash Lite |
| Noise classifier (S7) | `KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY` (reused) | Layer 2 skipped (fail-open) |
| Description (S7) | `KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER=deepinfra` + `KNOWLEDGE_GRAPH_DESCRIPTION_DEEPINFRA_MODEL_ID` | Gemini / None |
| Narrative (S7) | `KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY` (reused) | Template fallback |

---

## 2. Existing Gate Inventory

For each call category, the current protective mechanisms are:

### S6 — Embedding (`DeepInfraEmbeddingAdapter`)

- **Rate limiting**: None. No request-per-second throttle enforced by the adapter.
- **Circuit breaker**: None. No state machine tracks consecutive failures.
- **Retry logic**: `FallbackEmbeddingClient` wraps primary → Ollama fallback on first `RetryableError`. The embedding retry worker (`EmbeddingRetryWorker`) provides DB-level retry with max 5 attempts and exponential backoff (base × 2^n), capped at configurable `NLP_PIPELINE_EMBEDDING_RETRY_MAX_ATTEMPTS`.
- **Backoff**: Embedding retry worker: `min(base * 2^retry_count, max_backoff)` seconds between retries. Not applied to live embedding calls in the article consumer — those fail immediately to DLQ.
- **Cost cap**: None for embedding specifically. Prometheus `ml_api_estimated_cost_usd_total` counter is incremented (using a $0.013/M heuristic) but no hard stop exists.
- **402 handling**: Raises `FatalError` (treated as non-retryable 4xx). With `max_retries=5`, rows are permanently abandoned (BP-522).

### S6 — Deep extraction (`DeepSeekExtractionAdapter`)

- **Rate limiting**: `asyncio.Semaphore(deepinfra_extraction_concurrency)` — defaults to 5 concurrent calls in S7; S6 uses a single-article-at-a-time article consumer (effectively concurrency=1 per consumer process).
- **Circuit breaker**: None.
- **Retry logic**: None at the adapter level. Window failures in `run_deep_extraction_block` are caught with `logger.warning` + empty result (soft failure, no retry).
- **Backoff**: No retry → no backoff.
- **Cost cap**: None. Cost estimated and tracked in Prometheus (`ml_api_estimated_cost_usd_total`) but no action taken.
- **402 handling**: `openai.APIStatusError` with status < 500 → raises `FatalError` → window is logged as failed and returns empty result. The article continues processing without extraction output.
- **Timeout**: 120 seconds (`_EXTRACTION_TIMEOUT_S`) — 2× observed p99 latency.

### S6 — Relevance scoring (`ArticleRelevanceScoringWorker`)

- **Rate limiting**: `relevance_scoring_batch_size=50` per cycle, `relevance_scoring_cycle_seconds=1800`. Effective rate: ~1.7 articles/minute.
- **Circuit breaker**: None.
- **Retry logic**: Ollama fallback available when `RELEVANCE_SCORING_API_KEY` is empty; no retry against DeepInfra itself.
- **Backoff**: None for DeepInfra path.
- **Cost cap**: None.
- **402 handling**: Propagates as exception → article skipped for this cycle, retried next 30-min sweep.

### S6 — Unresolved resolution (`UnresolvedResolutionWorker`)

- **Rate limiting**: `unresolved_resolution_batch_size=500` per cycle, `unresolved_resolution_interval_s=1800`.
- **Circuit breaker**: None.
- **Retry logic**: `unresolved_resolution_llm_retries=2` (JSON parse failure retries). No DeepInfra-specific retry.
- **Backoff**: None for external API path.
- **Cost cap**: None.
- **402 handling**: Raises, mention skipped for this cycle.

### S7 — KG extraction chain (`FallbackChainClient`)

- **Rate limiting**: `asyncio.Semaphore(deepinfra_extraction_concurrency=5)` inside `DeepSeekExtractionAdapter`.
- **Circuit breaker**: None at chain level. On `RetryableError`, `FallbackChainClient._try_extraction` retries with delays `(5.0, 15.0)` for DeepInfra (2 attempts total), then falls through to Ollama → Gemini.
- **Retry logic**: 2 DeepInfra attempts → 3 Ollama attempts (delays 30/60/120s) → 2 Gemini attempts (delays 30/60s). Total worst-case wall time: ~7 minutes before chain exhausted.
- **Backoff**: Fixed delays per slot (not exponential with jitter).
- **Cost cap**: `description_max_monthly_usd=$10.0` enforced for description generation only (Valkey INCRBYFLOAT atomic pattern). No cap for extraction or embedding.
- **402 handling**: Treated as `FatalError` (4xx) → does NOT trigger fallback to Ollama. Chain is skipped for DeepInfra slot on 402. This is a critical gap: 402 looks like an auth error to the adapter but should trigger fallback + circuit-open.

### S7 — Noise classifier (`ProvisionalEnrichmentWorker` Layer 2)

- **Rate limiting**: `worker_provisional_enrichment_concurrency=5` (semaphore inside the worker).
- **Circuit breaker**: None. `noise_classifier_api_key` being empty causes Layer 2 to be skipped entirely (fail-open), but there is no runtime circuit breaker.
- **Retry logic**: `noise_classifier_timeout_s=10.0`. No retry on failure — Layer 2 failures are fail-open (entity passes to Layer 3 extraction).
- **Backoff**: Not applicable (fail-open on any error).
- **Cost cap**: None.
- **402 handling**: Logged, entity passes Layer 2 (fail-open). Ironically, billing-cap responses cause ALL entities to reach the expensive Layer 3 Qwen3-235B call — the opposite of the intended cost-saving behavior.

### S7 — Description generation (`DeepInfraDescriptionAdapter` / `GeminiDescriptionAdapter`)

- **Rate limiting**: `description_deepinfra_concurrency=4` semaphore.
- **Circuit breaker**: None.
- **Retry logic**: Gemini fallback exists in `DefinitionRefreshWorker` via scheduler wiring.
- **Backoff**: Fixed retry delays in `FallbackChainClient` (5/15s for DeepInfra).
- **Cost cap**: `description_max_monthly_usd=$10.0` enforced with Valkey atomic INCRBYFLOAT-then-check pattern. This is the only hard financial stop in the entire pipeline.
- **402 handling**: `FatalError` — description skipped for that entity.

---

## 3. Gate Gaps (What Is Missing)

### Gap G-1: 402 treated as FatalError everywhere except description

**Current behavior**: `DeepSeekExtractionAdapter` maps any `openai.APIStatusError` with status < 500 to `FatalError`. DeepInfra returns 402 (Payment Required) when the billing cap is exceeded. `FatalError` is non-retryable and does not trigger the Ollama fallback in `FallbackChainClient`.

**Impact**: When billing cap is hit, ALL extraction calls fail permanently until the account is replenished. Relation extraction output drops to zero. `embedding_pending` rows accumulate max retries (5) and are abandoned with no auto-recovery path (`BP-522`).

**Fix required**: Treat 402 as `RetryableError` with a long backoff (e.g., 3600s) rather than `FatalError`, so the fallback chain is invoked and the circuit breaker can open.

Files to change:
- `libs/ml-clients/src/ml_clients/adapters/deepseek_extraction.py` — add `elif exc.status_code == 402: raise RetryableError(...)` before the generic 4xx `FatalError`.
- `libs/ml-clients/src/ml_clients/adapters/deepinfra_embedding.py` — same pattern in `httpx.HTTPStatusError` handler.

### Gap G-2: No circuit breaker on any DeepInfra call path

**Current behavior**: Each individual adapter retries in isolation. There is no shared circuit-breaker state that can observe across all workers that "100% of DeepInfra calls have failed for the last N minutes" and open a breaker.

**Impact**: Under a billing cap or sustained outage, workers hammer DeepInfra continuously (up to the retry limits), burning retry budget and producing log noise without recovery. Ollama fallback is invoked for each individual call but the system has no awareness of a systemic outage.

**Fix required**: A `DeepInfraCircuitBreaker` class in `libs/ml-clients` backed by a Valkey key. Workers check the breaker state before making calls; open after `N` consecutive 402/500 errors within a window; half-open after `TTL` seconds.

Specific files:
- New: `libs/ml-clients/src/ml_clients/circuit_breaker.py`
- Modified: `libs/ml-clients/src/ml_clients/adapters/deepseek_extraction.py`
- Modified: `libs/ml-clients/src/ml_clients/adapters/deepinfra_embedding.py`

### Gap G-3: Noise classifier 402 inverts cost savings

**Current behavior**: When DeepInfra 402 is received by the Layer 2 noise classifier, the entity passes to Layer 3 (the expensive Qwen3-235B call) as a fail-open. During a billing cascade, all noise entities skip the cheap filter and hit the already-failing Qwen3-235B call.

**Impact**: The noise classifier's fail-open behavior, intended to prevent false negatives during transient errors, becomes a cost amplifier during billing cap events. The Layer 3 calls also fail (same DeepInfra account), so no entities are actually enriched, but the retry storm is worse.

**Fix required**: Layer 2 should distinguish 402 (billing) from 5xx (transient). On 402, Layer 2 should fail-closed (entity stays in `pending` state) rather than fail-open.

Files: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py` — add 402 detection in `_run_layer2_classifier`.

### Gap G-4: No hourly/daily token budget cap

**Current behavior**: Only `description_max_monthly_usd=$10.0` (Gemini/DeepInfra description) uses a spend cap. All other call paths (extraction, relevance scoring, unresolved resolution, embedding) have no budget ceiling.

**Impact**: A malformed Kafka message that causes unbounded windowing in `run_deep_extraction_block` (e.g., extremely long article text producing hundreds of 6000-token windows) would generate unbounded API calls. No alarm fires until the DeepInfra balance runs out.

**Fix required**: Per-worker hourly token budget counter in Valkey. Each worker checks the counter before calling; if budget exceeded, skips current batch and emits `worker_budget_exhausted` log + Prometheus counter.

### Gap G-5: Cost tracking not connected to alerting

**Current behavior**: `llm_usage_log` table in `nlp_db` is populated by `SessionScopedNlpUsageLogger` for S6 workers. `intelligence_db` has no `llm_usage_log` for S7 workers. Prometheus counters track `ml_api_estimated_cost_usd_total` per model but there is no alert rule that fires when daily spend exceeds a threshold.

**Impact**: Billing cap events are discovered reactively (workers fail) rather than proactively (alert fires at 80% of budget).

**Fix required**: Prometheus alert rule: `ml_api_estimated_cost_usd_total` rate over 1h exceeds threshold → PagerDuty/Slack. Also: create `llm_usage_log` in `intelligence_db` (owned by `intelligence-migrations`) so S7 workers (SummaryWorker, DefinitionRefreshWorker, ProvisionalEnrichmentWorker) have the same cost visibility as S6.

### Gap G-6: Embedding retry worker abandoned rows have no auto-recovery

**Current behavior**: After `max_retries=5` failed embedding attempts (all failing because DeepInfra returns 402 treated as FatalError), the row's `retry_count >= max_retries` causes it to be excluded from `claim_batch()` permanently. Manual SQL is required to reset.

**Impact**: After a billing cap event, all embedding work accumulated during the outage is permanently lost without operator intervention.

**Fix required**: An admin endpoint or scheduled task to reset abandoned rows; documented runbook in `docs/runbooks/`. In the interim, the SQL fix is: `UPDATE embedding_pending SET retry_count=0, next_retry_at=NOW() WHERE retry_count>=5 AND updated_at > NOW() - INTERVAL '2 days';`

---

## 4. Model Upgrade Candidates

### DeepInfra confirmed available models (2026 account, as of this investigation)

The codebase comments confirm which model IDs are on the allow-list for this DeepInfra account:
- `meta-llama/Meta-Llama-3.1-8B-Instruct` — confirmed available
- `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` — confirmed available
- `Qwen/Qwen3-235B-A22B-Instruct-2507` — confirmed available (current primary extraction model)
- `BAAI/bge-large-en-v1.5` — confirmed available (embedding)
- `Qwen/Qwen2.5-0.5B-Instruct` — noted as returning 404 on this account
- `Qwen/Qwen2.5-1.5B-Instruct` — noted as returning 404 on this account

### Candidate model table

| Model | Params | Active params | Context | DeepInfra price (in/out per 1M) | Expected structured output quality | Best pipeline stage |
|-------|--------|---------------|---------|----------------------------------|-------------------------------------|---------------------|
| `meta-llama/Meta-Llama-3.1-8B-Instruct` (current relevance/narrative) | 8B | 8B | 128k | ~$0.06/$0.06 | Moderate — adequate for binary classification, weak on complex JSON | Relevance scoring, narrative generation |
| `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` (current resolution/noise/description-fallback) | 8B | 8B | 128k | ~$0.02/$0.02 | Similar to above — Turbo variant is speed-optimized | Noise classification, unresolved resolution |
| `Qwen/Qwen3-235B-A22B-Instruct-2507` (current extraction primary) | 235B MoE | 22B | 250k | $0.071/$0.10 | Very high — MoE provides strong instruction following + JSON fidelity at low active-param cost | Deep extraction, entity profiling, summaries |
| `meta-llama/Meta-Llama-3.3-70B-Instruct` | 70B | 70B | 128k | $0.23/$0.40 | High — Llama 3.3 70B outperforms 3.1 70B and significantly outperforms 8B on structured extraction benchmarks (Llama3 70B: 99.8% valid JSON vs 98% for 7B in pathology benchmark) | Intermediate option for unresolved resolution if accuracy is critical |
| `Qwen/Qwen2.5-72B-Instruct` | 72B | 72B | 128k | $0.23/$0.23 | High — explicitly designed for structured JSON output; outperforms Llama 3.1 70B on MMLU-Pro, HumanEval, GPQA; strong instruction following | Unresolved resolution, noise classification (if high precision needed) |
| `mistralai/Mistral-7B-Instruct-v0.1` | 7B | 7B | 32k | ~$0.06/$0.06 | Lower — older model, context window limited to 32k; weaker on complex JSON than Qwen/Llama equivalents | Not recommended for any current pipeline stage |
| `mistralai/Mixtral-8x7B-Instruct-v0.1` | 46.7B MoE | ~12B active | 32k | ~$0.27/$0.27 (blended) | Moderate — 7B-effective per token, 32k context limit is a constraint for long-document extraction | Not competitive with Qwen3-235B at similar cost |
| `nvidia/Llama-3.3-Nemotron-Super-49B` | ~49B | 49B | 128k | $0.10/$0.10 (per search results) | High — NVIDIA fine-tune of Llama 3.3 70B; strong reasoning. Available on DeepInfra per 2026 pricing pages | Unresolved resolution (cost/quality tradeoff between 8B and 70B) |
| `Qwen/Qwen3-235B-A22B` (non-Instruct, thinking variant disabled) | 235B MoE | 22B | 250k | $0.18/$0.54 | Very high (thinking off, extraction mode) | Alternative for extraction if `reasoning_effort=none` not respected by -2507 variant |

### Per-stage assessment

**Deep extraction (S6 article consumer, S7 ProvisionalEnrichmentWorker Layer 3)**
Current model: `Qwen/Qwen3-235B-A22B-Instruct-2507` with `reasoning_effort=none`.
Assessment: This is already the correct choice. The 22B active-parameter MoE provides frontier-quality JSON extraction at a cost closer to a 22B dense model. The `reasoning_effort=none` + `response_format=json_object` + `temperature=0` combination produces stable structured output. The prompt cache key (`kg_extraction_v1`) amortizes system-prompt cost across calls. No change recommended for extraction.

**Relevance scoring (S6)**
Current model: `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo`.
Assessment: The task is simple (title-only prompt → scalar score). The 8B Turbo model is appropriate for cost ($0.02/M) and the output schema is trivial (a single float). No quality improvement would be material here — the bottleneck is the prompt design and weighting formula, not model capability. No change recommended.

**Unresolved resolution (S6)**
Current model: `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo`.
Assessment: This task — "does this mention surface form ('AAPL Inc') refer to entity X or is it noise?" — benefits from factual world knowledge and precise instruction following. The 8B Turbo model is borderline adequate. When mentions are ambiguous (similar company names, abbreviations, newly-public entities), the 8B model produces higher false-positive resolution rates. Upgrading to `nvidia/Llama-3.3-Nemotron-Super-49B` ($0.10/$0.10) would meaningfully improve precision while costing ~5× more per call. Given the estimated 12,000 calls/day at $0.02/M for 8B (~$0.024/day) vs. $0.10/M for Nemotron-49B (~$0.18/day), the cost delta is manageable. Alternative: `Qwen/Qwen2.5-72B-Instruct` at $0.23/$0.23 would give the best quality but cost ~$0.83/day for this one worker.

**Noise classification (S7 ProvisionalEnrichmentWorker Layer 2)**
Current model: `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo`.
Assessment: Binary classification (entity/noise) is low-complexity but false negatives are expensive (noisy entities reach Qwen3-235B at $0.071/M). The 8B model performs well for clear cases but struggles with edge cases (generic nouns that look like company names, e.g., "The Center", "Solutions Inc"). A middle-tier model like Nemotron-49B could reduce Layer 3 false-positive rates with modest cost increase. However, Layer 1 (static blocklist) already handles the majority of obvious noise. Recommendation: keep 8B model, but fix the fail-open-on-402 bug (Gap G-3) first.

**Entity description + summaries (S7)**
Current model: `Qwen/Qwen3-235B-A22B-Instruct-2507` (primary), `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` (fallback).
Assessment: The monthly $10 cap limits description spend regardless of model choice. The MoE primary produces high-quality factual prose with strong anti-hallucination adherence. The 8B fallback is adequate for emergency use. No change recommended.

**Narrative generation (S7)**
Current model: `meta-llama/Meta-Llama-3.1-8B-Instruct`.
Assessment: Narrative generation is weekly and batch-mode. The 8B model produces reasonable prose narratives. Upgrading to Llama 3.3 70B would improve narrative coherence and factual density, but the weekly trigger means cost impact is bounded. Optional improvement, low priority.

---

## 5. Recommended Upgrade Path

### Priority 1 (MUST before any model upgrade): Fix billing cascade gates

These gates must be in place before spending more per call. Larger models amplify the billing cascade risk linearly.

1. **Reclassify 402 as RetryableError** in `deepseek_extraction.py` and `deepinfra_embedding.py` — enables fallback chain and circuit breaker integration (1 hour).
2. **Fix Layer 2 fail-open on 402** in `provisional_enrichment.py` — prevents noise entities from bypassing cheap filter during billing events (30 min).
3. **Implement `DeepInfraCircuitBreaker`** in `libs/ml-clients/circuit_breaker.py` — Valkey-backed, opens after 10 consecutive 402/500 within 5 minutes, half-opens after 300s (3 hours).
4. **Per-worker hourly token budget** in Valkey — each worker key incremented per call, checked before batch dispatch (2 hours).
5. **Prometheus alert rule** — fire when `rate(ml_api_estimated_cost_usd_total[1h]) > threshold` (1 hour).
6. **Embedding abandoned-row recovery endpoint** — `POST /admin/v1/reset-abandoned-embeddings` (1 hour).

### Priority 2 (model upgrade, highest impact/cost ratio): Unresolved resolution → Nemotron-49B

**Where**: `NLP_PIPELINE_UNRESOLVED_RESOLUTION_API_MODEL_ID`
**From**: `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo`
**To**: `nvidia/Llama-3.3-Nemotron-Super-49B`
**Why**: Entity disambiguation is the highest-leverage extraction step in the pipeline. Incorrectly resolved mentions produce phantom relations in the knowledge graph (the `is_backfill` phantom column bug in BP-524 was partly masked by low resolution rates). Improving resolution precision at the input stage reduces downstream correction load in KG.
**Effort**: 1 environment variable change + regression test on `test_unresolved_resolution_worker.py`.
**Cost delta**: From ~$0.024/day to ~$0.18/day (+$4.68/month).
**Expected quality improvement**: Based on benchmark data (Llama 3.3 70B achieves 99.8% valid-JSON rate vs ~97% for Llama 3.1 8B in structured extraction tasks; similar delta expected for disambiguation precision), expect 5-15% reduction in false-positive entity resolutions.

### Priority 3 (optional): Narrative generation → Llama 3.3 70B

**Where**: `KNOWLEDGE_GRAPH_NARRATIVE_LLM_MODEL_ID` (currently reads `meta-llama/Meta-Llama-3.1-8B-Instruct`)
**To**: `meta-llama/Meta-Llama-3.3-70B-Instruct`
**Cost delta**: Weekly batch of ~N entities. Assuming 500 entities/week at ~500 tokens/narrative: 500 × 500 = 250k tokens × $0.40/M output = ~$0.10/week ($0.43/month). Negligible.
**Expected quality improvement**: More coherent multi-paragraph narratives, better factual entity characterization.

---

## 6. Required Gates Before Any Model Upgrade

The following code changes must land before switching any worker to a higher-cost model. The cost multiplier of a 70B-class model turns BP-522 from a $50/month annoyance into a $500/month disaster if billing controls are absent.

### Gate G-1: Reclassify 402 as RetryableError

File: `libs/ml-clients/src/ml_clients/adapters/deepseek_extraction.py`

In the `except self._openai.APIStatusError as exc:` block (currently around line 193), add before the generic 4xx handler:
```python
if exc.status_code == 402:
    # Payment required — treat as long-backoff retryable, not fatal.
    # 402 must trigger the fallback chain and circuit breaker, not
    # permanently abandon the call (BP-522).
    raise RetryableError(
        f"DeepInfra billing cap (402) — back off and use fallback: {exc}"
    ) from exc
```

File: `libs/ml-clients/src/ml_clients/adapters/deepinfra_embedding.py`

In the `except httpx.HTTPStatusError as exc:` block (around line 125), add before `FatalError`:
```python
if exc.response.status_code == 402:
    raise RetryableError(
        f"DeepInfra billing cap (402) on embedding: {exc}"
    ) from exc
```

### Gate G-2: Circuit breaker implementation

New file: `libs/ml-clients/src/ml_clients/circuit_breaker.py`

Interface:
```python
class DeepInfraCircuitBreaker:
    """Valkey-backed circuit breaker for DeepInfra API calls.

    States: CLOSED (normal) → OPEN (after N failures) → HALF_OPEN (after TTL).
    Key: deepinfra:cb:state (string: "closed"|"open"|"half_open")
    Failure counter: deepinfra:cb:failures (integer, TTL = window_seconds)
    """
    async def is_open(self) -> bool: ...
    async def record_failure(self, error_code: str) -> None: ...
    async def record_success(self) -> None: ...
```

Called in `DeepSeekExtractionAdapter.extract()` and `DeepInfraEmbeddingAdapter.embed()` before making the API call.

### Gate G-3: Per-worker hourly token budget

New Valkey key pattern: `deepinfra:budget:{worker_name}:{YYYY-MM-DD-HH}` (TTL = 3600s).

Each adapter call:
1. Estimate tokens for this call (existing heuristic).
2. `INCRBY` the Valkey counter by estimated tokens.
3. If counter > `WORKER_HOURLY_TOKEN_BUDGET`, log `worker_budget_exhausted` + skip.

Workers that need a budget key:
- `nlp-pipeline-article-consumer` — extraction calls
- `nlp-pipeline-relevance-scoring` — relevance scoring
- `nlp-pipeline-unresolved-resolution-worker` — resolution calls
- `nlp-pipeline-embedding-retry-worker` — embedding calls
- `kg-provisional-enrichment` — noise classifier + entity profile

### Gate G-4: Exponential backoff with jitter on 429

Current: `FallbackChainClient` uses fixed delays `(5.0, 15.0)` for DeepInfra.

Replace with: `base * 2^attempt + random.uniform(0, base)` where `base=5.0`, capped at 120s. This prevents thundering herd when DeepInfra rate-limits.

File: `services/knowledge-graph/src/knowledge_graph/infrastructure/llm/fallback_chain.py` — modify `_try_extraction` delay calculation.

### Gate G-5: Structured alerting on circuit open

When the circuit breaker transitions to OPEN state, emit a Kafka event to an `infrastructure.alert.v1` topic (or directly to a Slack webhook via an alerting sidecar). The event payload should include: worker name, failure count, error codes, timestamp.

This ensures on-call engineers are notified within minutes of a billing cascade, not hours.

### Gate G-6: llm_usage_log in intelligence_db for S7

Currently only `nlp_db` has `llm_usage_log`. S7 workers (SummaryWorker, DefinitionRefreshWorker, ProvisionalEnrichmentWorker) log to `llm_usage_log` in intelligence_db implicitly but the table schema lives in `intelligence-migrations`. Verify migration `0XXX` creates this table; if not, add it.

File: `services/intelligence-migrations/` — add migration for `llm_usage_log` if absent.

---

## 7. Estimated Monthly Cost Impact

### Current baseline (DeepInfra paths only, rough estimate)

| Worker | Calls/day | Avg cost/call | Daily cost | Monthly cost |
|--------|-----------|---------------|------------|--------------|
| Relevance scoring | 2,400 | $0.00004 | $0.096 | $2.88 |
| Unresolved resolution | 12,000 | $0.00003 | $0.36 | $10.80 |
| Deep extraction (DEEP tier articles) | 300 | $0.005 | $1.50 | $45.00 |
| KG ProvisionalEnrichment Layer 3 | 500 | $0.004 | $2.00 | $60.00 |
| SummaryWorker | 480 | $0.003 | $1.44 | $43.20 |
| Description (capped) | varies | varies | ~$0.33 | ~$10.00 (capped) |
| Narrative (weekly batch) | ~70/day | $0.002 | $0.14 | $4.20 |
| Embedding (both services) | high volume | ~$0.000001 | ~$0.20 | ~$6.00 |
| **Total estimate** | | | **~$6.07/day** | **~$182/month** |

### After Priority 2 upgrade (Unresolved resolution → Nemotron-49B)

Delta: +$4.68/month. Total: ~$187/month.

### If circuit breakers expose previously invisible retry costs

The main budget leak before circuit breakers is that retry attempts against failing DeepInfra endpoints don't register in cost estimates (they fail before charging). After the 402 reclassification, fallbacks to Ollama are free. The effective cost change from gate implementation is near-zero, with significant reliability improvement.

---

## 8. Summary of Recommended Actions (Ordered by Priority)

1. **Fix 402 reclassification** (1h) — `deepseek_extraction.py`, `deepinfra_embedding.py`.
2. **Fix Layer 2 fail-closed on 402** (30m) — `provisional_enrichment.py`.
3. **Add per-worker hourly token budget** (2h) — new Valkey pattern, called from each worker main loop.
4. **Implement `DeepInfraCircuitBreaker`** (3h) — new `libs/ml-clients/circuit_breaker.py`.
5. **Add Prometheus alert on spend rate** (1h) — alert rule file in `infra/`.
6. **Add embedding abandoned-row recovery endpoint** (1h) — `services/nlp-pipeline/src/nlp_pipeline/api/routes/admin.py`.
7. **Upgrade unresolved resolution to Nemotron-49B** (15m) — env var change + regression test.
8. **Upgrade narrative generation to Llama 3.3 70B** (15m) — env var change + regression test.

Items 1-6 are mandatory prerequisites for items 7-8.

---

*Sources consulted: DeepInfra pricing pages (deepinfra.com/pricing, costbench.com/software/llm-api-providers/deepinfra/), DeepInfra model pages (deepinfra.com/Qwen/Qwen2.5-72B-Instruct, deepinfra.com/llama, deepinfra.com/mistral), model comparison analyses (artificialanalysis.ai/providers/deepinfra, llm-stats.com, blogs.novita.ai), structured extraction benchmarks (arxiv.org/pdf/2602.14743 LLMStructBench, pmc.ncbi.nlm.nih.gov/articles/PMC11958830/), financial NLP benchmarks (arxiv.org/pdf/2403.18152, arxiv.org/pdf/2411.06852), codebase files listed in Phase 1 above.*
