# KG Relation Cap Hunt + Ground-Truth Read — Is There a Per-Doc/Chunk/Window Cap?

**Date:** 2026-06-14
**Author:** Principal NLP/Data Engineer (read-only investigation)
**Question (lead's hypothesis):** Are we capping relations at ~1 per document / per chunk / per window somewhere in the extraction → persistence path, when we should allow MANY relations per chunk? Plus a ground-truth read of real articles.
**Status:** Resolved. **NO** code / DB / git changes. All measurements read-only via `docker exec worldview-postgres-1 psql` (user `postgres`) and direct reads of `nlp_db.chunks.chunk_text`.
**Builds on (read first):** `2026-06-13-relation-extraction-quality-audit.md`, `2026-06-13-kg-entity-edge-ratio-deepdive.md`, `2026-06-14-extraction-transient-failure-investigation.md`, `2026-06-13-extraction-prompt-ab-test.md`.

---

## 0. TL;DR

1. **Is there a per-doc / per-chunk / per-window relation CAP? NO.** There is no `[0]`/`[:1]`/`next(...)`/`first`/"at most N" anywhere in the prompt, the extraction block, the parser, the consumer's `_build_raw_relations`, or the KG `graph_write` loop. Multi-window output is **concatenated and deduped by full triple** (`_merge_results_safe`), all windows are sent (not just the first/title), and `relation_evidence_raw` has **no uniqueness at all** (random `raw_id` PK) so many rows per `(doc, subject, object, type)` are allowed. The `relations` table's unique key is the **full triple** `(subject, canonical_type, object)`, NOT `(subject, object)`, so two predicates between the same pair are two distinct edges.
2. **The live distribution proves no cap.** For the 5,040 docs that yielded narrative relations: **mean = 2.81, median = 2, max = 30** raw relations/doc. Only **32% (1,633/5,040) have exactly 1**; **43% (2,167) have ≥3**; 81 docs have ≥10. A 1-per-doc cap would force nearly all to 1 — it does not. The distribution decays smoothly (1633 → 1240 → 874 → 508 → 285 → 167 → …).
3. **The ONE real truncation surface** is `max_tokens=4096` on the extraction call (`deepseek_extraction.py:219`). It is a *theoretical* cap on very long arrays, but in practice it almost never binds (max observed = 30 relations ≪ 4096-token budget; the A/B reported `malformed=0`; and the partial-JSON recovery only handles a description-path `"aliases"` tail, not relations). Not the binding constraint today.
4. **Ground-truth read: 5 of 8 zero-relation articles contained a clear, in-taxonomy, both-endpoints-resolved relation the pipeline missed; the other 3 are borderline-weak (relations present but thematic / one endpoint not resolved); 0 were genuinely empty.** The misses are textbook (`acquired_by`, `listed_on`, `partner_of`/`supplier_of`, `has_executive`, `owns_stake_in`).

**One-line root cause (re-confirmed, refined):** The loss is **not** a structural cap and **not** the gates — it is the extractor returning an empty `relations` array for articles that plainly state relations, *compounded by transient 429/timeout failures that get persisted as empty* (the BP-677/retry-hardening story in the 06-14 audit). The lead's per-doc-cap hypothesis is **REJECTED**.

---

## PART A — Hunt for a per-doc / per-chunk / per-window cap

### A.1 Prompt — no count cap; multi-relation is the modelled behaviour

`libs/prompts/src/prompts/extraction/deep.py` (the **working tree is now `@1.5`**, `version="1.5"` — note the 06-13 A/B verdict on `@1.5` was *TUNE, do not re-extract 17k as-written*).

- **No "extract THE relation" / "at most N" instruction.** The schema field is `"relations": {"type": "array", ...}` (an unbounded array).
- **The few-shot actively models MULTIPLE relations from one sentence:** `Text: 'TSMC supplies chips to Apple and Nvidia.'` → **two** `supplier_of` triples (deep.py:99–104). So the prompt biases *toward* many-per-chunk, not one.
- The recall-suppressing pressure is the *precision* framing, not a count cap: `"An empty array is a correct and expected output when nothing qualifies."` (deep.py:26–27) + the strict verbatim allow-list (deep.py:28–33). These depress recall but do **not** cap the count of emitted relations.

**max_tokens (the only real truncation lever):** `max_tokens=4096` on the `chat.completions.create` call — `libs/ml-clients/src/ml_clients/adapters/deepseek_extraction.py:219`, `temperature=0.0`, `reasoning_effort="none"`, `response_format={"type":"json_object"}`. A relations array long enough to exceed 4096 completion tokens would truncate, then fail JSON parse. **But** the partial-JSON recovery (`:340–377`) only salvages a trailing `"aliases":…` tail (that is the *entity-description* adapter's schema, not extraction) — a truncated **relations** array falls through to `FatalError("malformed extraction output")` → the window is dropped. This *could* silently cap a pathological article, but it does not bind in practice: the live max is 30 relations/doc, and the A/B observed zero malformed/parse failures across both prompt versions. **Verdict: real but non-binding.** (A cheap defensive win would be to raise `max_tokens` and add relations-array partial recovery, but it is not the cause of the 71% empties.)

### A.2 Chunking / windows — ALL windows sent, output CONCATENATED

`services/nlp-pipeline/src/nlp_pipeline/application/blocks/deep_extraction.py`.

- `_build_windows` (deep.py:151–176): full document text = `" ".join(c.text for c in chunks)` over **all** chunks. If `≤ 24,000` word-tokens → **one window containing the whole doc** (the common case for news). If larger → 6,000-token windows with 500-token overlap. It is **not** title-only and **not** first-chunk-only.
- The run loop (`:411–447`) iterates **every** window and `window_results.append(result)` for each. There is **no `break` after the first window**, no first-only selection.
- `_merge_results_safe` (`:299–328`) **concatenates** every window's `relations` and dedups only by the full triple key `f"{subject_ref}:{predicate}:{object_ref}"`. Per-window relation lists are **unioned**, not overwritten — only one window's output never "wins". Multi-window aggregation is confirmed correct.
- The only window-level loss is transient: a window that raises `RetryableError` is counted (`timed_out_windows`) and, if **all** windows time out, the whole doc raises `RetryableError` (`:462–471`) — the silent-empty-on-transient-failure story (06-14 audit), not a cap.

### A.3 Parsing — the WHOLE array is kept

- `_run_extraction_window` returns the **entire** parsed dict (`return raw` at deep.py:283; fallback `json.loads(output.raw_response)` at `:287`). No slicing, no `[0]`, no `next(...)`.
- The adapter (`extract`, deepseek_extraction.py:378–382) returns the full `result` dict unchanged.
- The consumer's `_build_raw_relations` (`services/nlp-pipeline/.../consumers/blocks/enriched_event.py:237–310`) **iterates `for rel in relations:`** and appends one output dict per relation. The only drop is `if subject_id is None or object_id is None: continue` (refs that resolve to neither a canonical nor a provisional entity) — a per-*ref* drop, never a per-*doc* cap.

`grep` for slice/first-style collapses across the whole path returned nothing relevant — no `relations[0]`, `[:1]`, `.first()`, or `next(iter(...))` on the relations list.

### A.4 Persistence / dedup — no per-doc, per-pair, or one-row collapse

- **`relation_evidence_raw`** (`intelligence-migrations/.../0001_create_intelligence_db.py:328–364`): PK is a random `raw_id UUID DEFAULT gen_random_uuid()`. **No UNIQUE constraint at all.** Every extracted relation from every doc becomes its own row — many rows per `(source_document_id, subject, object, type)` are explicitly allowed (that is how cross-document corroboration accumulates 8.19 evidence rows per edge).
- **KG `graph_write`** (`services/knowledge-graph/.../application/blocks/graph_write.py:459–476`): `for (rel, …) in zip(relations, …, strict=True):` — iterates **all** relations from the message, inserting an evidence row each. The only per-row skips are the **self-loop guard** (`subject == object`, `:484–490`) and the **entity-existence gate** (missing endpoint → deferred as `entity_provisional`, `:553–568`). Neither caps the count for a multi-relation doc.
- **`relations` table** (`0001_…:294,305`): PK `(relation_id, subject_entity_id)`; the dedup key is `uidx_relations_triple ON (subject_entity_id, canonical_type, object_entity_id)` — the **full triple**. Confirmed live:
  ```
  relations_pkey            (relation_id, subject_entity_id)
  uidx_relations_triple     (subject_entity_id, canonical_type, object_entity_id)   ← full triple, NOT (subject,object)
  ```
  So a second predicate between the *same* pair is a *distinct* edge — no per-pair collapse. The 12,014-triple → 4,750-edge funnel is legitimate cross-doc corroboration, not a cap.

### A.5 Live distribution — relations per yielding doc (the smoking-gun query)

`intelligence_db.relation_evidence_raw`, narrative only (`canonical_type IS DISTINCT FROM 'is_in_sector'`), grouped by `source_document_id`:

| Metric | Value |
|---|---:|
| Yielding docs | **5,040** |
| Total narrative evidence rows | 14,151 |
| **Mean relations/doc** | **2.808** |
| **Median** | **2** |
| **Max** | **30** |
| Docs with exactly 1 | 1,633 (32.4%) |
| Docs with 2 | 1,240 (24.6%) |
| Docs with ≥3 | 2,167 (43.0%) |
| Docs with ≥6 | 500 |
| Docs with ≥10 | 81 |

Histogram (n ≤ 12): `1:1633  2:1240  3:874  4:508  5:285  6:167  7:122  8:75  9:55  10:30  11:21  12:8` — a smooth geometric decay, the exact opposite of the spike-at-1 you would see under a 1-per-doc cap.

**Multi-predicate-per-pair survives:** 528 docs have ≥1 entity-pair carrying more than one distinct predicate (`distinct_triples > distinct_pairs`), with max 30 distinct triples in a single doc. This directly disproves any `(doc, subject, object)`-level collapse.

**Part A verdict: there is NO per-doc / per-chunk / per-window / per-pair cap, and no array truncation that binds in practice.** The empty-array rate is upstream of all of these — the model returns `[]`, and (per the 06-14 audit) ~23% of calls are 429/timeout failures persisted as empty.

---

## PART B — Ground-truth read (empty = "no relation" or "missed"?)

Sample: 8 docs, all `processing_path='full_pipeline'` (the LLM ran), each with ≥3–9 distinct **resolved** entities in `nlp_db.chunks.entity_mentions`, and **zero** narrative relation evidence in `intelligence_db`. Text read verbatim from `nlp_db.chunks.chunk_text`. Resolved-entity allow-list pulled from the same `entity_mentions` JSONB. These are **fresh** docs (2026-06-13/14), disjoint from the prior audits' samples.

| # | doc (short) | Title | Resolved entities (allow-list) | In-taxonomy relation present? | Verdict |
|---|---|---|---|---|---|
| 1 | 019ec394…ba | Oklo (OKLO) Acquires ARMEC | Oklo Inc., OKLO, ARMEC, Oak Ridge TN | **YES** — *"Oklo announced the acquisition of ARMEC"* = `acquired_by`(ARMEC, Oklo); `headquartered_in`(ARMEC, Oak Ridge) | **MISSED** |
| 2 | 019ec3a4…c0 | Kinder Morgan / Monument Acquisition | Kinder Morgan, NYSE, U.S., natural gas | **YES** — *"Kinder Morgan (NYSE:KMI) is acquiring Monument Pipeline for \$505 million"* → `listed_on`(Kinder Morgan, NYSE) (both resolved); acquisition (object not resolved) | **MISSED** |
| 3 | 019ec394…02 | CoreWeave Deploys NVIDIA Vera Rubin | CoreWeave Inc., NVIDIA, Dell Technologies, Micron Technology, NASDAQ | **YES** — *"supported by … Dell Technologies for server architecture and Micron Technology for liquid-cooled NVMe storage"* = `supplier_of`/`partner_of`(Dell, CoreWeave),(Micron, CoreWeave); `listed_on`(CoreWeave, NASDAQ) | **MISSED** |
| 4 | 019ec90e…fa | Astera Labs' Taiwan Bet | Astera Labs, Taiwan, Nasdaq-100, Cloud-Scale Interop Lab | **WEAK** — *"interoperability work with AMD, Intel, NVIDIA"* = `partner_of`, but AMD/Intel/NVIDIA NOT in the resolved allow-list for this doc → strict-allow-list pressure, not pure recall | **MISSED (borderline / allow-list)** |
| 5 | 019ec39f…3a | Belite Bio Completes NDA to FDA | Belite Bio, FDA / U.S. FDA, Dr. Tom Lin, NASDAQ | **YES** — *"Dr. Tom Lin, Chairman and Chief Executive Officer of Belite Bio"* = `has_executive`(Belite Bio, Dr. Tom Lin); *"submission … to the FDA"* = `regulates`(FDA, Belite Bio) | **MISSED** |
| 6 | 019ec90e…81 | MercadoLibre Pullback / Coupang Fine | MercadoLibre, MELI, Coupang, NYSE, NASDAQ, Nvidia, Apple, Netflix, Intel | **WEAK** — `listed_on`(MELI, NASDAQ),(Coupang, NYSE) grounded + resolved, but body is thin + Motley-Fool ad boilerplate (Nvidia/Apple/Netflix co-mention) | **MISSED (borderline)** |
| 7 | 019ec90d…e6 | Oracle Collapse Hits Ellison's Wealth | Oracle, Larry Ellison, Amazon.com, Elon Musk, Michael Dell | **YES** — *"Ellison owns around 41% of Oracle stock"* = `owns_stake_in`(Larry Ellison, Oracle); *"co-founder"* / *"Oracle reported record fourth quarter revenue"* = `earnings_released`(Oracle) | **MISSED** |
| 8 | 019ec398…2b | Nu Holdings Banking Empire in LatAm | Nu Holdings, Brazil, Mexico, Colombia, U.S. | **WEAK** — `operates_in_country`(Nu, Brazil/Mexico/Colombia) grounded + resolved (*"Most of the users are in Brazil … presence in Mexico … customers in Colombia"*); thematic profile piece | **MISSED (borderline)** |

**Tally: 5 of 8 are clear-cut missed relations** (Oklo `acquired_by`, Kinder Morgan `listed_on`, CoreWeave `supplier_of`+`listed_on`, Belite Bio `has_executive`+`regulates`, Oracle `owns_stake_in`+`earnings_released`). **3 of 8 are borderline-weak** — they DO contain grounded in-taxonomy relations (`listed_on`, `operates_in_country`, `partner_of`) but the article is thematic or one endpoint missed resolution (Astera's AMD/Intel/NVIDIA not in the allow-list). **0 of 8 were genuinely empty.**

This is *stronger* than the prior audit's 5/8 (which included 3 true no-signal docs): in this fresh sample even the "weak" articles carry an extractable `listed_on`/`operates_in_country` with both endpoints resolved. The misses are again the *easiest, most explicit* relations in the taxonomy, with verbatim trigger phrases and both entities in the supplied list. The model returned `[]` anyway.

**Two distinct failure flavours in the misses:**
- **Pure recall miss** (#1,2,3,5,7): both endpoints resolved, verbatim trigger present → the model simply did not emit. This is the dominant, highest-value lever.
- **Allow-list amputation** (#4): the relation is in text but one endpoint (AMD/Intel/NVIDIA) was not resolved by GLiNER/the resolution cascade, so the strict verbatim allow-list forbids it.

---

## C. Ranked root cause

| Rank | Cause | Verdict | Evidence |
|---|---|---|---|
| **1** | **Extractor returns empty `relations` despite explicit, both-endpoints-resolved relations** (precision-first `@1.5` framing + `reasoning_effort=none`) | **PRIMARY** | 5/8 fresh hand-read docs missed textbook relations; 71% empty-array cohort (prior audit) |
| **2** | **Transient 429/timeout persisted as empty** (BP-677 / consumer OFF-path silent-drop) | **PRIMARY, entangled with #1** | 06-14 audit: 23% of calls fail, 1,003/1,013 failed docs never recovered, persisted empty; fresh `@1.4` recovers 11/15 of the "empty" cohort (A/B §1.1) |
| **3** | **Strict verbatim allow-list amputates relations to unresolved endpoints** | **SECONDARY** | doc #4 (Astera × AMD/Intel/NVIDIA) — relation in text, endpoint not in list |
| **4** | **`max_tokens=4096` array truncation** | **REAL but NON-BINDING** | max observed 30 rel/doc; A/B malformed=0; recovery path doesn't cover relations |
| **5** | **Per-doc / per-chunk / per-window / per-pair CAP** (the lead's hypothesis) | **REJECTED** | no slice/first/at-most-N anywhere; mean 2.81 / median 2 / max 30 per doc; full-triple uniqueness; 528 docs with multi-predicate-per-pair |

---

## D. Single highest-leverage fix

**Land the retry+DLQ hardening from the 06-14 audit FIRST (BP-677 family), then re-baseline the prompt against fresh `@1.4` before any 17k re-extraction.** Quantitatively the biggest, cheapest, lowest-risk recovery is eliminating the *transient-failure-as-empty* substitution: ~23% of extraction calls fail (73% are fast-fail 429 `engine_overloaded`), 99% of failed docs are never retried and are persisted with `relations: []`. The adapter-level bounded retry + `enable_persistent_retry=True` (DLQ instead of silent commit) turns those fake empties back into real extractions — and fresh-`@1.4` re-calls already recover 11/15 of the "empty" cohort, confirming most of the 71% is production noise, not a prompt defect. **Only after that** is the residual genuine-recall gap (doc #1/#3/#5/#7-class misses) worth a *tuned* `@1.6` prompt (per the A/B's TUNE verdict: re-assert closed-vocab/self-loop/endpoint rules, drop the absolutist "empty array is correct" framing) plus softening the verbatim allow-list to *preferred-anchor* so unresolved endpoints (doc #4) flow via the existing provisional path.

---

## E. Appendix — key queries (read-only, live 2026-06-14)

```sql
-- A.5 relations-per-yielding-doc distribution (intelligence_db)
WITH per_doc AS (
  SELECT source_document_id, count(*) n
  FROM relation_evidence_raw
  WHERE canonical_type IS DISTINCT FROM 'is_in_sector'
  GROUP BY source_document_id)
SELECT count(*) yielding_docs, sum(n) rows, round(avg(n),3) mean, max(n) max,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY n) median,
       count(*) FILTER (WHERE n=1) eq1, count(*) FILTER (WHERE n>=3) ge3,
       count(*) FILTER (WHERE n>=10) ge10
FROM per_doc;        -- 5040 | 14151 | 2.808 | 30 | 2 | 1633 | 2167 | 81

-- multi-predicate-per-pair survives (no per-pair collapse)
WITH per_doc AS (
  SELECT source_document_id,
         count(DISTINCT (subject_entity_id,canonical_type,object_entity_id)) triples,
         count(DISTINCT (subject_entity_id,object_entity_id)) pairs
  FROM relation_evidence_raw
  WHERE canonical_type IS DISTINCT FROM 'is_in_sector'
  GROUP BY source_document_id)
SELECT count(*) FILTER (WHERE triples>pairs) docs_multi_predicate, max(triples)
FROM per_doc;        -- 528 | 30

-- relations table unique key = FULL TRIPLE
SELECT indexdef FROM pg_indexes WHERE tablename='relations';
-- uidx_relations_triple ON (subject_entity_id, canonical_type, object_entity_id)

-- Part B candidate pool (nlp_db): full_pipeline + >=4 distinct resolved entities,
-- minus docs already in relation_evidence_raw (narrative). Text from chunks.chunk_text.
```
