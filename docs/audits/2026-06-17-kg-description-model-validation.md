# KG Entity-Description Model Validation — gpt-oss-120b: main or fallback?

**Date:** 2026-06-17. **Scope:** the knowledge-graph open-knowledge **entity-description /
enrichment** capability (audit task #11, items #4/#6 in the 2026-06-17 LLM inventory). READ-ONLY
eval, **no production change.** Validates the inventory audit's quick 12-entity A/B (which flagged
gpt-oss fabricating biographies; hallucination 0.67 vs 235B 0.17) with the **exact production
prompt + params**, a **stratified DB sample**, and a **context-aware DeepSeek-V4-Flash judge**.

## The task (confirmed from code)

`DefinitionRefreshWorker` (Worker 13D-1) and `StructuredEnrichmentWorker` (Worker 13J) both call
`DeepInfraDescriptionAdapter` (`libs/ml-clients/src/ml_clients/adapters/deepinfra_description.py`)
to generate a 2-3 sentence entity description. Config:
`description_deepinfra_model_id` (services/knowledge-graph/src/knowledge_graph/config.py:235).
- **Primary:** `Qwen/Qwen3-235B-A22B-Instruct-2507` (adapter default); **fallback:** `Qwen/Qwen3-32B`.
- **Params:** `temperature=0.3`, **`max_tokens=256`**, no `reasoning_effort` (deliberately — BP-339:
  Qwen3 returns empty with `reasoning_effort=none`).
- **Input context:** *only* `canonical_name + entity_type + optional ticker/exchange/isin hints`.
  **No aggregated mentions, relations, or fundamentals are passed.** This is **pure open-knowledge
  generation** — the model must recall world facts, so fabrication risk scales with entity obscurity.
  (This refutes the "context makes fabrication moot" hypothesis: there is no grounding context.)

## Stratified sample (36 entities, `intelligence_db`)

Balanced 18 well-known / 18 obscure, across the 3 generated types, notability = `node_degree`
(graph connectivity) + ticker presence. Obscure cohort matches the real 2,549 tickerless-FI gap
(`docs/audits/2026-06-14-tickerless-instrument-companies-followup.md`).

| Stratum | financial_instrument | organization | person |
|---|---|---|---|
| **well-known** (deg≥15 / has ticker) | NVIDIA, AAPL, INTC, META, MS, TSLA | SpaceX, Zacks, Simply Wall St, Meta AI, … | Elon Musk, Jim Cramer, Trump, Jensen Huang, … |
| **obscure** (deg≤2, no ticker) | SharkNinja, Xcel Brands, AMZW, "five-year note", Valaris, DTTDC | Banza, Uni Express Inc., Paragon Acura, … | Mark Meador, Allison McNeely, Vinayak Hegde, Nacho Traves, … |

Arms (exact prod prompt + params): **235B-prod** (no reasoning_effort) · **gpt-oss-120b@medium** ·
**gpt-oss-20b@low**. Obscure entities run 2× (stochastic fabrication); well-known 1×. **n=54/arm**,
324 API calls. Judge = DeepSeek-V4-Flash, given the **input context** + description, counts
fabricated claims.

## Results — hallucination / grounding / accuracy by stratum

| Arm | Stratum | n | mean fabricated claims | mean hallu. (0-2) | severe | grounding (1-5) | accuracy | completeness | p50 |
|---|---|---|---|---|---|---|---|---|---|
| **235B-prod** | well-known | 18 | **0.00** | 0.00 | 0 | 5.00 | 5.00 | 4.72 | 3.4s |
| **235B-prod** | **obscure** | 36 | **0.53** | 0.44 | **8** | 3.92 | 3.97 | 3.36 | 3.7s |
| **120b@med** | well-known | 18 | 0.00 | 0.00 | 0 | 5.00 | 5.00 | 4.00 | 4.9s |
| **120b@med** | **obscure** | 36 | 0.19 | 0.39 | 7 | 4.00 | 4.03 | **2.42** | 4.9s |
| **20b@low** | well-known | 18 | 0.06 | 0.11 | 1 | 4.83 | 4.83 | 4.39 | 3.3s |
| **20b@low** | **obscure** | 36 | **1.19** | 0.89 | **16** | 3.08 | 3.00 | 2.72 | 4.0s |

**Decisive cell — obscure PERSON (highest fabrication risk):**

| Arm | n | mean fabricated claims | severe | empty `content` |
|---|---|---|---|---|
| 235B-prod | 12 | **1.58** | 8 | 0 |
| 120b@medium | 12 | 0.50 | 6 | **12 / 12** |
| 20b@low | 12 | **2.42** | 10 | 1 |

## The finding that overturns the quick A/B: gpt-oss-120b@medium produces EMPTY content

**33 / 54 of gpt-oss-120b@medium's outputs were empty** (`content=""`), including **all 12 obscure
persons** and most obscure orgs/FIs. Every empty hit `tokens_out=256` exactly — the reasoning model
**burned the entire production `max_tokens=256` budget on hidden reasoning and never emitted answer
text** (the BP-339 family: gpt-oss reasoning lives in a field the adapter does not read). The
adapter treats empty as failure and **falls through to `Qwen/Qwen3-32B`** — the malformed
word-per-line fallback. So gpt-oss-120b@medium's apparently "low" fabrication is an **artefact of
saying nothing**, not of staying grounded; it is **non-functional for this worker as configured.**

**235B is not the fabrication-safe model the inventory audit assumed.** On unknown persons it
*confidently invents* full biographies — quoted below — fabricating **more specific false claims
(1.58) than the (broken) 120b**. The audit's 12-entity check under-sampled obscure persons.

### Example fabrications (quoted)

- **235B-prod / "Mark Meador" (unknown person):** *"…serving as Chief Financial Officer of publicly
  traded companies… associated with firms such [Workiva]"* — invented CFO role.
- **235B-prod / "Vinayak Hegde":** *"…currently serves as the Chief Executive Officer of Infosys
  BPM…"* — invented CEO role.
- **235B-prod / "Stephen Sheldon":** *"…founder of SRS Investment Management, a hedge fund…"* — invented fund.
- **20b@low / "Nacho Traves":** *"…Spanish professional footballer who plays as a midfielder for
  Real Sociedad B…"* — invented entire football career (the audit's "NFL" pattern, confirmed & worse).
- **120b@medium / "SharkNinja" (obscure FI):** ticker *"SHNK"* — fabricated (actual: SN). 235B left it null.

## Verdict — **gpt-oss-120b is the 429 FALLBACK only, NOT the main model**

1. **Not viable as main as currently configured.** At the worker's `max_tokens=256`, gpt-oss-120b@medium
   returns empty content for the entire obscure cohort → silent fallthrough to the broken Qwen3-32B →
   **no description for exactly the tickerless/unknown entities that most need one.** Swapping it to
   primary would *degrade* the KG.
2. **Keep `Qwen/Qwen3-235B-A22B-Instruct-2507` as primary** — it is the only arm that reliably emits a
   real description for every stratum, and it is clean (0 fabrication) on well-known + obscure orgs/FIs.
   Its weakness is confident biography-invention for **unknown persons** (1.58 fab) — a real but
   bounded harm, and *better* than the alternatives (20b 2.42; 120b "0.50" only via empties).
3. **gpt-oss-120b@medium as the 429 / saturation fallback** (the inventory audit's hedge): exactly
   right. The 235B saturates to ~160s under 48-way load; on the rare 429, a fast 120b that *hedges/empties*
   on unknowns rather than inventing is an acceptable degraded mode — but it must NOT be primary, and the
   adapter must keep Qwen3-32B *after* it so an empty 120b still yields something.
4. **Do NOT adopt gpt-oss-20b** anywhere here — worst fabricator (1.19 obscure / 16 severe; invents
   footballers, MPs, NFL players).

**Exact config for the fallback role:** `description_deepinfra_fallback_model_id = openai/gpt-oss-120b`
with **`reasoning_effort=medium` AND `max_tokens` raised to ≥1024** (the 256 cap is what breaks it; a
medium reasoner needs budget to reason *and* answer). Without the token bump, do not wire it in at all.

**Bigger fish:** the highest-leverage description fix is not the model — it is that **unknown persons
get confident fabricated biographies from every arm**. Recommend a downstream guard (suppress/flag
person descriptions for entities with `node_degree ≤ N` and no corroborating context) rather than
chasing a model that fabricates less.

**Eval cost:** 324 DeepInfra calls (162 generations ≤256 tok-out + 162 judge ≤300 tok-out, ~600-tok
prompts). At DeepInfra rates (235B $0.071/$0.10; gpt-oss-120b ~$0.05/$0.45; 20b ~$0.04/$0.16;
DeepSeek-V4-Flash $0.14/$0.28 per 1M) ≈ **< $0.15 total**. Raw: `results/kg_desc_eval/`.
