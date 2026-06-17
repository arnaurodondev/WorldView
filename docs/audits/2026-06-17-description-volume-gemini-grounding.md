# KG Entity-Description — Volume, gemini-3.1-flash-lite, and News-Grounding

**Date:** 2026-06-17. **Scope:** audit task #14, three fronts on the open-knowledge
entity-description capability (`DefinitionRefreshWorker` 13D-1 + `StructuredEnrichmentWorker` 13J →
`DeepInfraDescriptionAdapter`). READ-ONLY eval, **no production change.** Builds on
`2026-06-17-kg-description-model-validation.md`. Effective prod config (from
`services/knowledge-graph/configs/docker.env`): `provider=deepinfra`,
`model_id=Qwen/Qwen3-235B-A22B-Instruct-2507`, `temperature=0.3`, `max_tokens=256`,
`description_max_monthly_usd=10.0`, prompt-cached (`prompt_cache_key="entity_description_v1"`).

> **Run status.** Parts 2 & 3 require live DeepInfra calls. The platform was DOWN and **no working
> `DEEPINFRA_API_KEY` is present in this checkout** (the keys in `*/configs/docker.env` are stale
> placeholders → HTTP 401; real keys come from `make fetch-secrets`, which is not wired here). The
> A/B harness is **staged and ready** at `results/desc_grounding_eval/eval.py` (+ `news_context.json`,
> `sample_raw.json`); re-run with a valid key to fill the live cells. Part 1 and the gemini
> price/feasibility verdict need no LLM and are final below; the prior validation's 235B baseline
> anchors the quality comparison.

---

## Part 1 — Call volume & monthly cost (current vs gemini)

**Cadence (from code, not guesses).** `DefinitionRefreshWorker` runs every **3600 s** but only
describes rows whose `next_refresh_at` is due (**90-day** interval) **and** whose
`SHA-256(source_text)` changed — so the periodic pass is a **near-total no-op** (hash match → push
date forward, no LLM call). The real driver is the **first description per new entity**
(`StructuredEnrichmentWorker` Step 3, consumer-triggered) — i.e. **once per new/changed entity**,
not periodic re-description. LLM is invoked for LLM-only types (person/organization/…) and for FIs
with NULL EODHD `source_text` (crypto/FX/index, ~48). FIs with an EODHD description never call it.

**Per-call token sizes (measured, n=54, prior 235B run).** Input ≈ **883 tokens** (mostly the static
example-laden system prompt — prompt-cached, so repeat input is cheap); output mean **80**, median 80,
max **132** (the `max_tokens=256` cap is essentially never hit by 235B).

**Per-call cost.** Qwen3-235B ($0.071 in / $0.10 out per 1M): **$0.0000707/call** (~$0.071 / 1k
calls). gemini-3.1-flash-lite ($0.25 / $1.50): **$0.000341/call** (~$0.34 / 1k) → **≈4.8× per call**
(driven by the 15× output price; input cache softens the 3.5× input gap).

**Volume projection.** Describable universe ≈ **non-FI + null-FI entities** within the ~3,440
described-entity backlog; tickerless-FI head that matters is ~96 (`2026-06-14` follow-up). New-entity
inflow from the news pipeline is modest (low hundreds/day at peak, most deduped before minting).
Bounding cases:

| Scenario | 235B (current) | gemini-3.1-flash-lite |
|---|---:|---:|
| One-time full re-describe (~3,440 entities) | **$0.24** | **$1.17** |
| Steady state @ ~300 new-entity describes/day | ~$0.64/mo | ~$3.07/mo |
| Pessimistic @ ~1,000/day | ~$2.1/mo | ~$10.2/mo |

**Verdict (volume gate):** the endpoint is **not called much** — even gemini stays at single-digit
$/month in realistic regimes, and the existing **$10/month hard cost-cap** caps the downside. Peak
calls/hour are bounded by `description_deepinfra_concurrency=4`. **Cost is not a blocker for gemini.**
(For the exact live figures, query `llm_usage_log WHERE capability='description'` — SQL in the appendix.)

---

## Part 2 — gemini-3.1-flash-lite (web-verified; quality staged)

**Served on DeepInfra:** **yes** — slug `google/gemini-3.1-flash-lite`, **$0.25 in / $1.50 out** per
1M, **1M-token context** (sources: deepinfra.com model page; ai.google.dev pricing; pricepertoken).
A **`gemini` provider path already exists** in `scheduler._build_description_client` →
`GeminiDescriptionAdapter` — migration is a **one-line env flip**
(`KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER=gemini` + key), **no code change**.

**Expected quality per stratum (hypothesis under test, anchored to prior 235B baseline):**
- **well-known** — both already perfect (235B: 0.00 fab, grounding 5.0). gemini ≈ parity; **no lift**.
- **moderately-known** (some real public footprint) — this is where gemini's broader/fresher world
  knowledge *should* help: fewer invented job-titles/tickers than 235B. **This is the cell to watch.**
- **truly-obscure / unknown persons** — **no model can know them**; gemini will still confabulate a
  biography from the no-context prompt. The prior run's worst cell (235B obscure-person **1.58 fab**)
  will **not** be fixed by a better model. Grounding (Part 3) is the only lever here.

**Verdict (pending live cells):** gemini is **cheap-enough and feasible** (one env flip). Its upside is
confined to the moderately-known stratum; it does **not** address the dominant failure (obscure-person
fabrication). **Migrate only if the live run shows a real moderately-known lift** — otherwise the spend
buys nothing the current 235B doesn't already deliver.

---

## Part 3 — News-grounding A/B (the bigger structural win)

**Root cause** (confirmed by the prior validation): the prompt passes **only name+type+ticker** — pure
open-knowledge recall, so fabrication scales with obscurity. The fix is to **inject the entity's own
news** as grounding context.

**Prototype (staged).** `results/desc_grounding_eval/eval.py` adds two arms — `235b+news`,
`gemini+news` — that prepend a **NEWS CONTEXT** block (verbatim evidence snippets) to the exact prod
prompt, instructing the model to ground in and not exceed those facts; when no news exists it injects
an explicit *"no corroborating news — describe only the category"* guard. Snippets come from
`news_context.json` (representative stand-ins for the production join
`relation_evidence_raw.evidence_text` / nlp chunks, because the news DB was down). The harness
re-judges fabrication/grounding/accuracy with the same DeepSeek-V4-Flash judge.

**Expected lift (hypothesis under test):**
- **Obscure entities WITH ≥1 news mention** (the ~853-mention head): large drop in fabricated claims —
  the model paraphrases real evidence instead of inventing. This is the **highest-leverage** change.
- **Obscure entities with the "no news" guard:** should fall back to safe category statements
  (grounding↑, fab→~0) instead of confabulated biographies — *even without any real news*, just by
  telling the model the news is absent.
- **Well-known:** neutral (already grounded).

**Cost of grounding.** 3 snippets ≈ +150–250 input tokens/call. At 235B that is **~+$0.000016/call**
(negligible — input is the cheap side and prompt-cacheable for the static portion). gemini's higher
input price still leaves it single-digit $/month. **Cost is not the obstacle — plumbing is.**

**Plumbing sketch (what the worker must add):**
1. In `StructuredEnrichmentWorker` Step 3 / `DefinitionRefreshWorker._resolve_non_company_text`,
   before the LLM call, **fetch top-N (≈3) evidence snippets** for `entity_id` from `intelligence_db`
   (`relation_evidence_raw.evidence_text` where subject/object = entity_id, newest first; or
   `claims`/`relations`), de-duplicated, truncated to ~300 chars each.
2. Pass them through a new `news_context: list[str]` arg on
   `DescriptionLlmClientProtocol.generate_description` → adapter appends the NEWS CONTEXT block (and
   the "no news" guard when empty). Forward-compatible (default `None` = today's behaviour).
3. Bump `max_tokens` only if outputs lengthen (current 80-token mean has headroom under 256).
4. Add a read-replica query (`ReadOnlyUnitOfWork`, R27) — this is a read-only enrichment fetch.

**Verdict:** **news-grounding is the highest-impact change** — it attacks the actual root cause and
helps obscure entities precisely where a better *model* cannot. Recommend prototyping → measuring the
lift on the staged A/B, then wiring the plumbing.

---

## Bottom line — prioritized

1. **(b) Add news-grounding — DO THIS FIRST.** Biggest fabrication reduction, attacks the root cause,
   negligible cost, model-agnostic. Helps obscure entities no model can otherwise describe.
2. **(a) Migrate to gemini — CONDITIONAL / SECOND.** Cheap (single-digit $/mo, under the $10 cap),
   zero-code (env flip), but upside is confined to the moderately-known stratum and **does not** fix
   obscure-person fabrication. Adopt **only if** the live run shows a real moderately-known lift; it
   pairs well with grounding (gemini+news) but is not a substitute for it.
3. **Not (d) "neither":** the status quo confidently poisons the graph with fabricated biographies for
   unknown persons (235B 1.58 fab/obscure-person). Doing nothing is the worst option for KG quality.

**Both, in order: grounding then (conditionally) gemini.** Independent of either, keep the prior
audit's downstream guard (suppress/flag person descriptions for `node_degree ≤ N` with no
corroborating context).

**Eval $ spent:** **$0.00** (live LLM blocked on missing key; only web-checks + offline analysis ran).
A full live A/B re-run is **~180 gen+judge calls ≈ <$0.20**. Raw + harness: `results/desc_grounding_eval/`.

---

### Appendix — live volume SQL (run against intelligence_db)
```sql
-- calls/day, total, peak hour, token sizes for the description capability
SELECT date_trunc('day', created_at) d, count(*) calls,
       avg(tokens_in) tin, avg(tokens_out) tout
FROM llm_usage_log WHERE capability='description' GROUP BY 1 ORDER BY 1;
SELECT count(*) total FROM llm_usage_log WHERE capability='description';
SELECT date_trunc('hour', created_at) h, count(*) FROM llm_usage_log
WHERE capability='description' GROUP BY 1 ORDER BY 2 DESC LIMIT 5;  -- peak hour
```
