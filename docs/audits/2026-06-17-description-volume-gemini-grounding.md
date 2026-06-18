# KG Entity-Description — Volume, gemini-3.1-flash-lite, and News-Grounding

**Date:** 2026-06-17. **Scope:** audit task #14, three fronts on the open-knowledge
entity-description capability (`DefinitionRefreshWorker` 13D-1 + `StructuredEnrichmentWorker` 13J →
`DeepInfraDescriptionAdapter`). READ-ONLY eval, **no production change.** Builds on
`2026-06-17-kg-description-model-validation.md`. Effective prod config (from
`services/knowledge-graph/configs/docker.env`): `provider=deepinfra`,
`model_id=Qwen/Qwen3-235B-A22B-Instruct-2507`, `temperature=0.3`, `max_tokens=256`,
`description_max_monthly_usd=10.0`, prompt-cached (`prompt_cache_key="entity_description_v1"`).

> **Run status (FINAL, 2026-06-17 — A/B EXECUTED).** The revoked DeepInfra key (`xVi3…GivI` → HTTP 401)
> was rotated to a working key and redeployed across `worldview-gitops`; the platform LLM layer is
> restored. **The full live A/B then ran to completion** (360 gen+judge calls, DeepSeek-V4-Flash judge,
> `news_context.json` rebuilt from the live `relation_evidence_raw` join). **Results in Part 4 below.**
> Headline: **news-grounding on the existing Qwen3-235B is the fix** — obscure-person fabrication
> **1.83 → 0.17** (−91%), grounding **2.50 → 4.75**, description richness preserved. **The gemini arms
> are INVALID**: `google/gemini-3.1-flash-lite` returned **100% empty output** (54/54 + 36/36 blank, 0
> chars) on DeepInfra when called with no reasoning/thinking config — the same empty-output reasoning-model
> trap as gpt-oss. Its apparent "low fabrication" is an artefact of emitting nothing. **Verdict resolves to:
> implement news-grounding on 235b; do NOT migrate to gemini.**

---

## Part 0 — Live DB findings (no-LLM, newly obtained 2026-06-17)

**News-grounding source is richly populated platform-wide.** `relation_evidence_raw` holds **96,732
rows, 96,727 (99.99%) with non-empty `evidence_text`** — so the grounding corpus the Part 3 plumbing
would join against exists and is dense. There is currently **no `capability='description'` row in
`llm_usage_log`** at all (only `extraction` 99,671 and `embedding` 42,709) — the ~3,440-entity
described backlog was minted via a path that doesn't emit description usage logs, so the appendix
volume-SQL returns empty against this DB; Part 1's projections stand on the code-cadence analysis, not
on logged description history.

**Real news-evidence availability for the 18-entity obscure cohort (the cell the prior run guessed).**
Querying live `relation_evidence_raw` for each sampled entity (subject *or* object):

| Has real `evidence_text` (grounding available) | None (→ "no-news guard" branch) |
|---|---|
| **Valaris** (5), **Banza** (2), **TARA** (1), **Mark Meador** (1) — **4/18 = 22%** | the other **14/18 = 78%**: SharkNinja, Xcel Brands, AMZW, five-year note, DTTDC, Uni Express, Paragon Acura, Guotai Haitong, Morgan & Morgan, Allison McNeely, Vinayak Hegde, Stephen Sheldon, Jennifer Schultz, Nacho Traves |

**This corrects two assumptions baked into the staged `news_context.json` stand-ins:**
1. **TARA** was hand-stubbed as *no-news* (`[]`), but real evidence exists:
   *"Tradeweb Markets has introduced TARA, a conversational AI assistant embedded in its institutional
   platform…"* — the stand-in would have wrongly tested the guard branch for a grounded entity.
2. **Real evidence is noisier/thinner than the polished stand-ins.** Valaris's actual snippets are
   repetitive price-blips (*"Oilfield Services company Valaris (NYSE:VAL) fell 4%"* ×4 + *"Valaris(NYSE:VAL)"*)
   — they confirm the *category* (offshore-driller, NYSE:VAL) but carry little biographical substance.
   By contrast **Mark Meador**'s real evidence correctly pins him as an *FTC commissioner* alongside
   Ferguson — exactly the fact 235B fabricated/omitted from the no-context prompt; grounding would fix
   this case. **Banza**'s evidence (Campbell's chickpea-pasta partnership) is genuinely descriptive.

**Implication for Part 3 (sharpened by real data):** for the obscure cohort the **dominant branch is the
"no-news guard" (78%)**, not the rich-grounding branch. The grounding win therefore splits in two: (a) a
**few** entities (~22%) get real corroborating snippets that should sharply cut fabrication (Meador,
Banza) — though some grounding is so thin (Valaris) it only safely anchors the category; (b) the
**majority** rely on the **guard** ("no corroborating news → describe only the category") to *suppress*
confabulated biographies. Both levers still beat the status quo, but the realistic lift is **guard-driven
fabrication suppression for most obscure entities, with true evidence-paraphrase for the minority that
have news** — re-confirm exact magnitudes on the staged A/B once a key is live.

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

## Part 4 — LIVE A/B results (EXECUTED 2026-06-17, n=360 gen+judge calls)

Four arms, DeepSeek-V4-Flash judge, `max_tokens=256 temperature=0.3` (prod), news snippets from the
**live** `relation_evidence_raw.evidence_text` join (top-3 by `extracted_at DESC`, subject-or-object).
Fabrication / hallucination / severe are *per-description* counts (lower = better); grounding / accuracy
/ completeness are 1–5 (higher = better).

| Arm | stratum | n | **fab↓** | hallu↓ | severe↓ | ground↑ | acc↑ | compl↑ | toks_out |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 235b (baseline) | obscure | 36 | 0.64 | 0.44 | 8 | 3.89 | 3.92 | 3.28 | 82 |
| **235b+news** | obscure | 36 | **0.19** | 0.17 | 3 | **4.64** | **4.67** | **3.50** | 70 |
| gemini ⚠️ | obscure | 36 | 0.08 | 0.17 | 3 | 4.39 | 4.39 | 2.33 | **9 (EMPTY)** |
| gemini+news ⚠️ | obscure | 36 | 0.03 | 0.06 | 1 | 4.64 | 4.64 | 2.64 | **9 (EMPTY)** |
| 235b (baseline) | **obscure_person** | 12 | **1.83** | 1.17 | 7 | **2.50** | 2.50 | 2.17 | 82 |
| **235b+news** | **obscure_person** | 12 | **0.17** | 0.17 | 1 | **4.75** | 4.67 | 3.33 | 70 |
| gemini ⚠️ | obscure_person | 12 | 0.25 | 0.50 | 3 | 4.00 | 4.00 | 2.33 | **9 (EMPTY)** |
| gemini+news ⚠️ | obscure_person | 12 | 0.08 | 0.17 | 1 | 4.67 | 4.67 | 2.50 | **9 (EMPTY)** |

**⚠️ The gemini arms are INVALID — 100% empty output.** `google/gemini-3.1-flash-lite` returned blank
strings for **all 90** of its calls (54 no-news + 36 news; avg 0 chars, `tokens_out`≈9). Called with no
`reasoning_effort`/thinking config it spends its budget on hidden reasoning and emits empty `content` —
identical to the gpt-oss trap. Its "best fabrication" scores are an artefact of saying nothing; ignore
them. (To evaluate gemini at all would require the adapter to send a thinking/effort param — but see the
verdict: it's moot, grounding-on-235b already wins.)

**The real result — news-grounding on 235b is decisive:**
- **Obscure persons (the worst cell): fabrication 1.83 → 0.17 (−91%), grounding 2.50 → 4.75, completeness
  2.17 → 3.33.** It both kills invented facts *and* makes descriptions more complete (because real
  evidence gives it something true to say).
- **All obscure: fabrication 0.64 → 0.19 (−70%), grounding 3.89 → 4.64**, richness preserved (390 chars).
- **Qualitative proof (real outputs):**
  - *Mark Meador* — 235b: **"Chief Financial Officer of Workday, Inc."** (fabricated). 235b+news:
    **"Commissioner of the U.S. Federal Trade Commission"** (correct — grounded in the injected news).
  - *Allison McNeely* (zero news) — 235b: **"leadership roles in asset management and investment advisory
    firms"** (invented). 235b+news: **"without corroborating information, no specific role or achievements
    can be verified"** — the **no-news guard** suppressing confabulation exactly as designed.

**This confirms the two-branch design with live numbers:** (a) for the ~22% of obscure entities *with*
news, grounding paraphrases real facts (Meador); (b) for the ~78% *without*, the explicit "no
corroborating news → describe only the category" guard turns a confident fabrication into an honest
non-claim (McNeely). Both branches are already exercised in the prototype prompt and both work.

**Eval $:** ~360 calls ≈ <$0.40, completed. Raw: `results/desc_grounding_eval/results.json`.

---

## Part 5 — Implementation plan (ready to execute; news-grounding on 235b)

Fully mapped against the live code. Every new arg is **defaulted (`= None`)** → forward-compatible, each
layer lands independently. **Do NOT touch `structured_enrichment_consumer_main.py`** (active sibling
session, R42). Suggested order (leaf → root), one commit + tests per step:

**1. `libs/ml-clients/src/ml_clients/adapters/deepinfra_description.py`** (the QA-proven core)
- `generate_description(...)` + `_build_prompt(...)`: add `news_context: list[str] | None = None`.
- In `_build_prompt`, after the base line, append the grounding block when snippets exist:
  *"## Recent news context (ground your description in these facts; state nothing they do not support):"*
  then up to 3 sanitized, ≤300-char snippets wrapped as data; **else** the no-news guard:
  *"## No corroborating news found. If not independently certain of specifics, describe only the general
  category/type — do not invent roles, titles, affiliations, or biographical detail."*
  (Sanitize each snippet with the existing `_NAME_CONTROL_CHAR_RE` + length cap — evidence_text is
  untrusted news → prompt-injection surface; keep the system prompt static for KV-cache.)
- Keep the BP-339 note: still **no** `reasoning_effort` on Qwen3 (empty-output trap).

**2. `libs/ml-clients/src/ml_clients/adapters/gemini_description.py`** — mirror the `news_context` arg for
parity (defaulted). (Gemini stays rejected, but the protocol must be uniform.)

**3. Protocol/forwarding:** `description_client.py` (`EntityDescriptionClient`, `NullDescriptionAdapter`)
and `chained_description.py` (`ChainedDescriptionAdapter` — forward `news_context=news_context` at the
call site): add the defaulted arg.

**4. `services/knowledge-graph/.../infrastructure/intelligence_db/adapters/entity_enrichment_adapter.py`**
- New read method `fetch_recent_evidence(entity_id, limit=3) -> list[str]`, opening its **own read
  session via `self._read_session_factory()`** (exact pattern of `list_unenriched`; R27 read replica):
  ```sql
  SELECT evidence_text, extracted_at FROM relation_evidence_raw
  WHERE (subject_entity_id = :eid OR object_entity_id = :eid)
    AND evidence_text IS NOT NULL AND length(btrim(evidence_text)) > 0
  ORDER BY extracted_at DESC LIMIT :fetch   -- fetch ~10, dedup in Python, take top 3
  ```
  Dedup verbatim duplicates (Valaris-style repeats), truncate ~300 chars.

**5. `services/knowledge-graph/.../application/use_cases/structured_enrichment.py`**
- `DescriptionLlmClientProtocol.generate_description`: add `news_context: list[str] | None = None`.
- In Step 3, **before** the `generate_description` call (still Phase-2, but a quick open/close read that
  is NOT held during the LLM I/O): `news = await self._adapter.fetch_recent_evidence(entity.entity_id)`;
  pass `news_context=news`. Wrap in try/except → on read failure, log + proceed with `news_context=None`
  (grounding is best-effort, never blocks enrichment).
- Mirror the same 2-line fetch+pass in `DefinitionRefreshWorker` (Worker 13D-1) for the non-company path.

**6. Tests** (one per layer): adapter builds the NEWS CONTEXT block when snippets present / the guard when
empty (+ injection-sanitization test, extending `test_deepinfra_description_prompt_safety.py`); chained
forwards `news_context`; `fetch_recent_evidence` dedup/limit/empty; use case passes fetched snippets and
degrades to `None` on read error. **7. Docs:** `docs/services/knowledge-graph.md` (enrichment Step 3 now
news-grounded) + this audit's verdict.

Acceptance: re-run `results/desc_grounding_eval/eval.py` `235b+news` arm against the shipped path —
expect obscure-person fab ≤ ~0.2 (from 1.83), grounding ≥ ~4.5.

---

## Bottom line — prioritized

1. **(b) Add news-grounding — DO THIS FIRST.** Biggest fabrication reduction, attacks the root cause,
   negligible cost, model-agnostic. Helps obscure entities no model can otherwise describe. **Live DB
   evidence (Part 0) reinforces this:** the grounding corpus exists and is dense (96.7k snippets), but
   for the obscure cohort the **guard branch dominates (78% have no news)** — so the implementation must
   ship the *"no corroborating news → category-only"* guard as a first-class path, not an afterthought;
   that guard alone suppresses most obscure-person confabulation. Also **fetch evidence at query time**
   (the TARA stand-in error proves a static news map goes stale — join `relation_evidence_raw` live).
2. **(a) Migrate to gemini — NO (resolved by the live A/B).** `google/gemini-3.1-flash-lite` returned
   **100% empty output** on DeepInfra (no reasoning/thinking config → empty `content`, the gpt-oss trap).
   It cannot be evaluated as-is, and it is **moot regardless**: news-grounding on the existing 235b
   already drives obscure-person fabrication to 0.17 with *higher* completeness (3.33) than any gemini
   arm. No model swap — keep Qwen3-235B and add grounding. (If a future need arises, gemini would first
   require an adapter thinking/effort param before it emits anything.)
3. **Not (d) "neither":** the status quo confidently poisons the graph with fabricated biographies for
   unknown persons (235B **1.83** fab/obscure-person, live). Doing nothing is the worst option for KG
   quality.

**Do grounding on 235b — that single change is the win** (no model swap). It includes the
no-news/category-only guard as a first-class branch (the 78% majority). Independent of it, optionally keep
the prior audit's downstream guard (suppress/flag person descriptions for `node_degree ≤ N` with no
corroborating context) as defence-in-depth.

**Eval $ spent:** **$0.00.** The live LLM A/B was attempted but **blocked: the DeepInfra key is revoked
(HTTP 401 `invalid_api_key`)** — verified by direct call and by the platform's own real-time extraction
failures in `llm_usage_log`. **No DeepInfra calls were issued.** The DB queries (Part 0 volume +
news-evidence availability) are free Postgres reads. A full live A/B re-run, once a valid key is
restored, is **~180 gen+judge calls ≈ <$0.20**. Raw + harness: `results/desc_grounding_eval/`.

> **To finish Parts 2 & 3:** restore a valid DeepInfra key (`make fetch-secrets`), then
> `DEEPINFRA_API_KEY=<key> python results/desc_grounding_eval/eval.py`. Recommended improvement before
> re-running: replace the hand-built `news_context.json` with a **live** join against
> `relation_evidence_raw.evidence_text` (top-3 newest per `entity_id`, subject-or-object) so the A/B
> measures grounding on the *real* — and as Part 0 shows, often thinner/absent — evidence, not idealized
> stand-ins. SQL skeleton is in Part 0 / the appendix.

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
