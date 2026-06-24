# Platform LLM Inventory & gpt-oss Upgrade Audit

**Date:** 2026-06-17. **Scope:** every LLM-using capability across the platform, with a
recommendation to KEEP / upgrade to `openai/gpt-oss-20b` / `openai/gpt-oss-120b`.
Both gpt-oss models are **reasoning models** — `reasoning_effort` MUST be set explicitly
or they return empty content (see `docs/audits/2026-06-16-extraction-model-ab-results.md`).
**No production changes were made here.** Targeted A/Bs are small + cheap (DeepSeek-V4-Flash judge).

## Key principle established by the A/Bs

> Reasoning models (gpt-oss) win on **structured, schema-bound, grounded-input** tasks
> (extraction — facts are in the supplied text). They **lose** on **open-ended
> knowledge-generation** tasks (entity descriptions/narratives — the model must recall
> world facts, and the larger Qwen3-235B both knows more and fabricates less). They add
> **nothing** on cheap latency-sensitive classification (relevance/resolution) while
> costing 2-3× the latency.

## Inventory

Volume = live `llm_usage_log` (nlp_db + intelligence_db) over the trailing window.
KG generation workers all log as `capability=extraction / provider=deepinfra` (~3–9k/day combined).

| # | Capability | Service | Current model | reasoning_effort | Volume (recent) | Latency | Profile |
|---|---|---|---|---|---|---|---|
| 1 | deep extraction (KG facts) | nlp-pipeline | **gpt-oss-120b** (swap in progress) | medium | ~30k/wk | ~25s | structured — *being upgraded by sibling agent; excluded* |
| 2 | article relevance + sentiment | nlp-pipeline | Qwen3.5-9B | none | ~12k/wk | ~1s p50, 1.9s avg | latency-sensitive classify, per-article |
| 3 | unresolved-mention resolution | nlp-pipeline | Qwen3.5-9B | none | bursty | ~0.9s p50 | binary classify, per-mention |
| 4 | KG entity-description gen | knowledge-graph | Qwen3-235B (fb Llama-3.1-8B) | (none) | part of ~3-9k/day | 2-30s+ | **open knowledge gen** |
| 5 | KG relation summary | knowledge-graph | FallbackChain → Gemini 2.5 FL | (none) | low | — | grounded (evidence text) gen |
| 6 | KG entity enrichment | knowledge-graph | Qwen3-235B (fb Llama-3.1-8B) | (none) | per-entity + nightly | ≤25s | open knowledge gen |
| 7 | KG entity narrative | knowledge-graph | Llama-3.1-8B | (none) | weekly ≤500 | — | grounded (relations) gen |
| 8 | KG path-insight explanation | knowledge-graph | Llama-3.1-8B | (none) | ~300/12min | — | grounded (path) gen |
| 9 | chat completion (tool-use + synthesis) | rag-chat | DeepSeek-V4-Flash | (none) | user traffic | hot path | agentic tool-use + stream |
| 10 | chat intent classification | rag-chat | Qwen3.5-9B | none | per-message | hot path | latency-sensitive classify |
| 11 | HyDE query expansion | rag-chat | DeepSeek-V4-Flash | (none) | per-query | hot path | short gen |
| 12 | reranker | rag-chat | Cohere v3 → Qwen3-Reranker-0.6B → bge | n/a | per-query | hot path | cross-encoder (not a chat LLM) |
| 13 | injection classifier | rag-chat | (chain) | (none) | per-message | hot path | safety classify |
| 14 | citation judge (cron) | rag-chat | DeepSeek-V4-Flash | (none) | batch, disabled | background | LLM-judge |
| 15 | morning-brief / agentic-brief | rag-chat | DeepSeek-V4-Flash | (none) | ≤100/day/user | background | grounded gen |
| — | embeddings | nlp + kg | BAAI/bge-large-en-v1.5 | — | high | ~50-150ms | **not an LLM — excluded** |

## Targeted A/B results (small, cheap; DeepSeek-V4-Flash judge / weak-label)

**Relevance scoring** (20 live titles, baseline = current Qwen3.5-9B scores):
| Arm | empties | MAE vs baseline score | sentiment agree | p50 |
|---|---|---|---|---|
| Qwen3.5-9B (baseline) | 0 | — | 90% | 1.0s |
| gpt-oss-20b@low | 0 | 0.10 | 90% | 1.2s |
| gpt-oss-120b@low | 0 | 0.087 | 85% | 2.0s |
→ gpt-oss adds **no** calibration/sentiment gain, only divergence + 2× latency. **KEEP.**

**Resolution** (28 live mentions, weak label = resolution_outcome):
| Arm | accuracy | fp | fn | p50 |
|---|---|---|---|---|
| Qwen3.5-9B (baseline) | 100% | 0 | 0 | 0.9s |
| gpt-oss-20b@low | 89% | 2 | 1 | 0.9s |
| gpt-oss-120b@medium/low | 100% | 0 | 0 | 2.2s |
→ baseline already perfect; 120b only matches at 2.4× latency, 20b regresses. **KEEP.**

**Entity description** (12 entities incl. obscure persons/orgs; judged for fabrication):
| Arm | mean hallucination (0-2) | severe | quality (1-5) | p50 |
|---|---|---|---|---|
| Qwen3-235B (prod) | **0.17** | **1** | **3.92** | 2.4s |
| gpt-oss-20b@low | 0.67 | 4 | 3.25 | 2.2s |
| gpt-oss-120b@medium | 0.33 | 2 | 3.67 | 7.9s |
→ gpt-oss-20b **invents biographies** (e.g. a fake NFL career for an unknown "Jordan Klein"); 235B
stays in-domain. The reasoning models are **worse** here. **KEEP 235B.** This generalises to the
other open-knowledge KG workers (enrichment, narrative).

## Per-capability recommendations

| Capability | Verdict | Rationale |
|---|---|---|
| relevance scoring (#2) | **KEEP Qwen3.5-9B** | hot-ish, per-article; no quality gain, +latency. Reasoning model = bad fit (CoT overhead on a 1-token-class task). |
| resolution (#3) | **KEEP Qwen3.5-9B** | already 100% on weak labels; 20b regresses. |
| entity description (#4) | **KEEP Qwen3-235B** | reasoning models fabricate more on open knowledge gen. |
| enrichment (#6) | **KEEP Qwen3-235B** | same open-knowledge profile as #4. |
| narrative (#7) / path-insight (#8) | **KEEP Llama-3.1-8B** | grounded short gen on a budget model; fine. Optional future: test gpt-oss-20b@low for #8 (grounded, schema-light) only if quality complaints arise. |
| summary (#5) | **KEEP** (FallbackChain) | grounded, low volume. |
| chat completion (#9) | **EVALUATE separately — likely KEEP** | DeepSeek-V4-Flash is already a strong reasoning model; gpt-oss-120b is a plausible alt but needs the full chat-quality rubric (out of this audit's cheap budget) + agentic tool-use parity check. Do NOT swap blind. |
| HyDE (#11) | **KEEP** | tiny throwaway gen; reasoning latency would hurt the hot path. |
| intent (#10) / injection (#13) | **KEEP** | latency-critical hot-path classify; reasoning overhead is pure cost. |
| citation judge (#14) | **KEEP DeepSeek-V4-Flash** | budget judge per memory. |

## ACTION ITEM (config bug found, not a model swap)

KG workers #4/#6 run **Qwen3-235B with NO `reasoning_effort`** — but 235B is *not* a reasoning
model, so that's fine for them. However, the **extraction A/B proved 235B saturates to ~160s
under production's 48-way concurrency**. KG description/enrichment share that model and that
saturation risk. **Recommend:** once the sibling agent's extraction swap to gpt-oss-120b lands,
re-point the *open-knowledge* KG workers' fallback to gpt-oss-120b@medium **only as the 429
fallback**, keeping Qwen3-235B primary for its lower fabrication — this hedges saturation without
the fabrication penalty.

## Prioritised upgrade list

1. **(highest impact) NONE require an upgrade.** The single highest-leverage swap on the
   platform — deep extraction → gpt-oss-120b@medium — is already in progress.
2. KG saturation hedge (above) — config-only, no quality cost. Low effort.
3. Chat completion (#9) — worth a dedicated future eval with the chat rubric; NOT a blind swap.
4. Everything else: **KEEP**.

**Net:** gpt-oss is the right model for *grounded extraction*, the wrong model everywhere
else on this platform. The audit's value is the three "do NOT upgrade" findings backed by data.

Eval cost: **< $0.50** total (gpt-oss/Qwen/235B sample runs + DeepSeek-V4-Flash judge; ≤80 generations + ≤24 judge calls). Raw results: `results/llm_audit_relevance/`, `results/llm_audit_desc/`.
