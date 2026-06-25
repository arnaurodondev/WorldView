# Extraction-Model A/B Results — gpt-oss-120b vs Qwen3-235B vs Llama-3.3-70B

**Date:** 2026-06-16. Harness: `scripts/eval/extraction_quality_eval.py` (production prompt v1.6, identical schema for every arm). Judge: **DeepSeek-V4-Flash** (budget). Golden set: 100 DEEP-tier articles (235B arm bounded to 15 due to its latency/saturation). Scores 1–5; fabrication / allowlist-violation / missed are counts.

## Verdict: SWAP primary 235B → `openai/gpt-oss-120b@low`

gpt-oss-120b@low beats the production 235B on precision, schema adherence, fabrication, and allowlist compliance — and is ~19× faster under production load and ~1/10th the cost. The 235B's only edge is a small recall lead, which comes with *more* fabrication.

## Full-set results (100 docs; 235B 15)

| Model | n | Precision | Recall | Adherence | Fabricated | Allowlist viol. | Missed | Latency p50/p95 | empty |
|---|---|---|---|---|---|---|---|---|---|
| **openai/gpt-oss-120b@low** | 100 | **4.96** | 3.31 | **4.90** | **1** | **4** | 154 | **8.5s / 16.3s** | 13 |
| meta-llama/Llama-3.3-70B@none | 100 | 4.31 | 3.51 | 3.83 | 30 | 76 | 125 | 29.1s / 82.7s | 1 |

## Head-to-head on the SAME 15 docs (vs the production baseline)

| Metric | Qwen3-235B@low | **gpt-oss-120b@low** |
|---|---|---|
| Precision | 4.40 | **5.00** |
| Recall | **3.73** | 3.27 |
| Adherence | 3.93 | **4.93** |
| Fabricated | 3 | **0** |
| Allowlist viol. | 4 | **1** |

## Key findings

1. **gpt-oss-120b is the highest-precision, near-zero-fabrication, schema-cleanest arm.** 1 fabricated item + 4 predicate violations across 100 docs. Ideal KG-writer profile (a missed fact is absent; a fabricated one poisons the graph).
2. **The 235B's 160s production latency is a SATURATION artefact, not the model.** Bounded (15 docs, no 48-way concurrency) it ran **6–31s**. Under production's 48 concurrent calls it degrades to ~160s + `engine_overloaded` 429s. gpt-oss holds 8.5s under load → structurally more robust.
3. **Llama-3.3-70B is NOT a clean fallback** — fast but 30 fabrications + 76 allowlist violations. Its higher yield is noise. Do not adopt as-is; test `gpt-oss-20b` for the fast fallback, or accept Llama only as a last-resort on the rare 429.
4. **gpt-oss-120b is a REASONING model** — at DeepInfra default it spends all tokens on hidden reasoning and returns empty `content`. It only emits answer JSON with `reasoning_effort` set explicitly (`@low` validated). The config MUST set it.

## Recommended config change
- **Primary:** `NLP_PIPELINE_EXTRACTION_API_MODEL_ID = openai/gpt-oss-120b` + `reasoning_effort=low` (explicit). Keep the production prompt v1.6.
- **Fallback:** replace `deepseek-ai/DeepSeek-V4-Flash` (303s, useless) — test `openai/gpt-oss-20b`; interim, Llama-3.3-70B as last-resort only.
- Validate post-swap: live extraction yield, grounding spot-check, latency drop, backlog drain.

Eval cost: ~well under $1 (gpt-oss/Llama runs + DeepSeek-Flash judge + 15 235B).

## gpt-oss-120b tuning (reasoning_effort + max_tokens; 45-doc subset, DeepSeek-Flash judge)

| Variant | empty | yield/doc | latency p50 | Precision | Recall | Adherence | Fabricated | Allowlist |
|---|---|---|---|---|---|---|---|---|
| `@low` / max_tokens 4096 | 12 | 1.53 | 9.6s | 5.00 | 3.44 | 4.89 | 0 | 2 |
| **`@medium` / 4096 (RECOMMENDED)** | **3** | 3.09 | 24.9s | 4.93 | **3.62** | 4.98 | 1 | 0 |
| `@high` / 8192 | 37 | 0.38 | 180s (timeout) | 4.88 | 4.00 | 5.00 | 0 | 0 |

- **`@medium` is optimal:** recall 3.44→3.62, empties 12→3, yield doubled, holding precision ~4.93 / adherence 4.98 / ~0 fabrication, at ~25s p50 (still 6× faster than the 235B under production load). Nearly closes the recall gap to the 235B (3.62 vs 3.73) while beating it on precision (4.93 vs 4.40), adherence (4.98 vs 3.93), fabrication (1 vs 3).
- **`@high` unusable** — high reasoning is so slow it hits the 180s timeout → 82% empty. Raising max_tokens did NOT help; *medium reasoning* (not more tokens) recovered recall — so the `@low` empties were under-reasoning, not truncation.

## Fallback candidates (full set, DeepSeek-Flash judge)

| Model | Precision | Recall | Adherence | Fabricated | Allowlist | Verdict |
|---|---|---|---|---|---|---|
| **gpt-oss-20b@low** | 4.94 | 3.40 | 4.75 | 2 | 15 | **fast, near-120b quality → best fallback** |
| Llama-3.3-70B@none | 4.31 | 3.51 | 3.83 | 30 | 76 | noisy — reject |
| DeepSeek-V4-Flash | — all runs failed (0 ok) — | | | | | dead — reject |

## Rigorous head-to-head (45 docs, same set, post-limit-increase; 235B unsaturated)

| Metric | Qwen3-235B@low | **gpt-oss-120b@medium** |
|---|---|---|
| Precision | 4.36 | **4.93** |
| Recall | 3.62 | **3.62 (tie)** |
| Adherence | 3.84 | **4.98** |
| Fabricated | **15** | **1** |
| Allowlist viol. | 12 | **0** |
| Latency p50 | 19.1s (unsaturated; ~160s under prod 48-way concurrency) | 24.9s |

gpt-oss-120b@medium **ties recall and dominates precision/adherence/fabrication/schema**. The 235B's 15 fabricated items + 12 allowlist violations (vs 1 / 0) make it the worse KG writer. No remaining argument for the 235B. Verdict reconfirmed on the larger sample.

## FINAL production config
- **Primary:** `openai/gpt-oss-120b`, `reasoning_effort=medium`, `max_tokens=4096` (recall/precision balance). Use `@low` only if raw throughput must trump the recall gain.
- **Fallback:** `openai/gpt-oss-20b`, `reasoning_effort=low`.
- Both are reasoning models — `reasoning_effort` MUST be set explicitly (default → empty output).
