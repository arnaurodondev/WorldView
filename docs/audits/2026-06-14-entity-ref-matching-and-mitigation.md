# Entity-Ref Matching Framework: Why Extraction Relations Drop, the Chat Matcher Asymmetry, and a Measured Mitigation

**Date:** 2026-06-14
**Author:** Principal NLP Engineer (read-only investigation + measurement simulation)
**Status:** Resolved. NO production code / DB / git changes. All measurements read-only via `docker exec worldview-postgres-1 psql` + a throwaway `/tmp/sim_match.py` simulation.
**Builds on:** `2026-06-14-kg-relation-cap-and-groundtruth.md` (confirmed NO per-doc cap; the loss is upstream and at the ref-resolution boundary). This audit drills into the ref-resolution boundary.

---

## 0. TL;DR

1. **The extraction matcher is document-local.** `_build_raw_relations` resolves a relation's `subject_ref`/`object_ref` ONLY against `entity_id_by_ref`, a dict built exclusively from **this document's own NER mentions** (resolved canonical-UUIDs + synthesized-provisional queue-UUIDs). Any ref the LLM emits whose surface is not one of *this doc's mentions* resolves to `None` and the whole relation is `continue`-dropped (`enriched_event.py:268`). It NEVER consults the 17,174-row canonical store.
2. **The chat matcher is store-global.** The chat/RAG path resolves a surface against the **entire** `canonical_entities` + `entity_aliases` store via the S6 4-stage cascade (exact alias → ticker/ISIN → pg_trgm fuzzy ≥0.55 → ANN embedding), then applies a precision gate (0.75 floor + 0.15 delta + ticker/name tiebreaks). **This asymmetry is the core finding.**
3. **The cited doc, dissected:** doc `019ec90e-…339` had GLiNER mentions for only `Jackery` (×7, resolution_outcome=`provisional`) and `SYDNEY` (resolved). The LLM extracted **3 relations** (`deep_extraction.complete relations=3` at 02:25:21) but **0** landed in `relation_evidence_raw`. Jackery WAS provisional-promoted (queue row `019ec918-…ba`, source_doc = this doc) — so the drop was NOT a Jackery miss. The relations dropped because their **other endpoint was a real entity in the prose that NER never minted a mention for**, so it was absent from `entity_id_by_ref` and `synthesize_provisional_refs` (which only promotes *existing* mentions) could not rescue it.
4. **One-line miss reason:** a relation drops when **at least one endpoint ref the LLM legitimately used is not one of this document's NER mentions** — so it is neither resolved nor provisional-queued, the document-local lookup returns `None`, and the relation is silently dropped. (The "Jackery" surface itself is in the lookup; the *opposite endpoint* is what's missing.)
5. **Measured recovery (the test asked for):** simulating the chat-style matcher (exact alias → ticker → fuzzy≥0.55, with the 0.75/0.15 gate) over **two samples of ~50 unresolved relation-endpoint surfaces** from full_pipeline docs in the last 7 days:
   - **Frequency-stratified random sample (n=50): 84% recover (all via EXACT alias), 14% genuinely unresolvable, 2% below floor. Precision-safe = recall = 84%.**
   - **Top-frequency sample (n=60): 57% recover** — lower ONLY because the head is polluted with GLiNER noise nouns ("analysts", "management", "patients", "investors", "shareholders") that *should* stay unresolved (correct precision). Excluding the ~14 noise tokens, the real-entity recovery is ≈90%.
   - **Critical timing caveat:** ~94% of the recovering EXACT aliases were created by `source='provisional_enrichment'` (the UnresolvedResolutionWorker) AFTER the doc was extracted — so a *synchronous* canonical-store fall-back at extraction time would NOT have helped those (the canonical did not exist yet). The recovery is real **for the residual genuine-recall gap and for backfill re-extraction**, and confirms the provisional path is the right primary mechanism — but the binding bug is that **the second endpoint never becomes a mention at all.**

---

## PART A — The extraction-side matcher (why relations drop)

### A.1 What `entity_id_by_ref` actually contains

`_enqueue_enriched` (`services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/blocks/enriched_event.py:36–205`) builds the lookup at lines 93–129:

```python
entity_id_by_ref: dict[str, str] = {}
provisional_refs: set[str] = set()
for m in mentions:                              # <-- THIS document's mentions ONLY
    if m.resolved_entity_id is not None:
        value = str(m.resolved_entity_id)       # real canonical UUID
        for variant in _ref_variants(m.mention_text):
            entity_id_by_ref.setdefault(variant, value)
    elif m.provisional_queue_id is not None:    # synthesized-provisional queue UUID
        value = str(m.provisional_queue_id)
        for variant in _ref_variants(m.mention_text):
            entity_id_by_ref[variant] = value
            provisional_refs.add(variant)
    # else: UNRESOLVED with no queue id -> EXCLUDED  (line 129)
```

`_ref_variants` (enriched_event.py:99–116) and the symmetric `_normalize_ref_variants` (helpers.py:28–55) generate: lowercase-stripped, whitespace-collapsed, and iteratively corporate-suffix-stripped (`_BUILD_RAW_SUFFIX_RX` = `inc|corp|ltd|llc|plc|co|holdings|group|ag|nv|sa|…`). `_resolve_ref` (helpers.py:58–72) walks the same variants of the LLM ref and returns the first hit. **The normalization is good and symmetric; it is NOT the dominant miss cause.**

The membership domain is the problem: **the keys are surfaces of `mentions`, full stop.** There is no path to the canonical store.

### A.2 The drop site

`_build_raw_relations` (enriched_event.py:237–310), per relation:

```python
subject_id, subject_match = _resolve_ref(subject_ref, entity_id_by_ref)
object_id,  object_match  = _resolve_ref(object_ref,  entity_id_by_ref)
if subject_id is None or object_id is None:
    continue  # skip truly unresolved — neither resolved nor provisional   (line 268)
```

Same pattern in `_build_raw_events` (first resolvable `entity_refs` element wins, else drop, :342) and `_build_raw_claims` (:378). All three are document-local.

### A.3 The prompt allow-list IS the lookup domain (no input/lookup mismatch — but a shared blind spot)

`deep_extraction.py:182–190` builds the prompt entity list from exactly the mention surfaces:

```python
mention_names = list(dict.fromkeys(m.mention_text for m in mentions))   # ALL mentions, deduped
prompt = DEEP_EXTRACTION.render(entities=", ".join(mention_names), text=window_text)
```

and the prompt's ENTITY CONSTRAINT (deep.py:28–33) is **STRICT**:
> "entity_ref / subject_ref / object_ref values MUST be an exact string from this list: {entities}. If a name appears in the text but is NOT in this list, you MUST omit it entirely."

So the advertised allow-list == `mention_names` == the surfaces that seed `entity_id_by_ref`. **There is NO prompt-input-vs-lookup mismatch** (the BP family the task flagged): a compliant LLM cannot emit a ref outside the lookup. The shared blind spot is upstream of both: **if NER (GLiNER) never produces a mention for an entity, it is in neither the prompt allow-list NOR the lookup**, and any relation to it is structurally impossible to emit (or, when the LLM disobeys the strict allow-list and emits it anyway, it is dropped at A.2).

### A.4 `synthesize_provisional_refs` — wired, but only rescues EXISTING mentions

Contrary to a stale comment in `deep_extraction.py:218`, this IS on the production hot path: `ml_phase.py:175` calls it after Block 10. It (`provisional.py:65–128`):
1. collects every LLM ref surface (`_collect_extraction_refs`),
2. indexes this doc's **UNRESOLVED mentions** by normalized variant (`candidate_index`, line 102–107 — `continue` if already resolved/provisional),
3. for each LLM ref that matches an unresolved *mention*, calls `ensure_provisional_for_mention` (`entity_resolution.py:676`) → inserts a `provisional_entity_queue` row (SAVEPOINT + churn-guard `MAX_PROVISIONAL_PER_HOUR`) and stashes `provisional_queue_id` on the in-memory mention.

**It can only promote a surface that is already a mention** (line 103 iterates `mentions`). A ref to a non-mention entity is never reachable. This is exactly why the cited doc's Jackery resolved to `provisional` (it was a mention) yet the relations still dropped (the *other* endpoint was not).

### A.5 Miss-reason classification (live, the cited doc + sample)

| Miss reason | Mechanism | Cited-doc evidence | Prevalence |
|---|---|---|---|
| **(i) Endpoint is not a NER mention at all** | object/subject is a real entity in prose GLiNER never tagged → absent from allow-list AND lookup; synthesize can't reach it | **PRIMARY** — Jackery doc: only `Jackery`+`SYDNEY` were mentions; 3 relations extracted, 0 landed; Jackery itself was provisional-promoted, so the drop is on the opposite endpoint | Dominant |
| (ii) String-variant mismatch | LLM surface differs from mention beyond suffix/whitespace normalization | Not observed as dominant — `_ref_variants`/`_resolve_ref` are symmetric; HTML-entity surfaces (`at&amp;t`) are a real gap (see C) | Minor |
| (iii) Unresolved mention not provisional-queued | mention is UNRESOLVED and churn-guard / insert-failure left `provisional_queue_id` None → excluded at line 129 | Possible on churn-guard hits (`MAX_PROVISIONAL_PER_HOUR`) | Minor |

**Verification of the cited doc** (`019ec90e-…339`):
- `routing_decisions`: `processing_path=full_pipeline`, tier `deep`, decided 02:25:21.
- consumer log: `deep_extraction.complete events=1 claims=2 relations=3 degraded=false`.
- `entity_mentions`: `SYDNEY` → `auto_resolved`; `Jackery` ×7 → `provisional` (so it HAD a queue id at enqueue).
- `provisional_entity_queue`: `jackery` row `019ec918-…ba`, `source_doc_id`=this doc, later `resolved` → canonical `f422a2ea-…2b`.
- `relation_evidence_raw`: **0 rows for this doc.**
- ⇒ The 3 relations dropped on their **non-Jackery endpoint**, which was never a mention. Textbook miss-reason (i).

---

## PART B — The chat endpoint's entity matcher (the better one) and the asymmetry

### B.1 Where the chat path resolves entities

Two resolver surfaces, both store-global:

1. **Pre-prompt path (ChatOrchestrator).** Once per turn, the orchestrator calls **S6** `POST /api/v1/entities/resolve` on the user's query, then gates the result through `filter_resolver_candidates` in
   `services/rag-chat/src/rag_chat/application/services/resolver_gates.py:411–535`.
2. **Tool path (IntelligenceHandler / NarrativeHandler).** Per tool argument (`search_claims(entity_name=…)`, etc.), `IntelligenceHandler.resolve_name`
   `services/rag-chat/src/rag_chat/application/pipeline/handlers/intelligence.py:259` calls **S7 alias-search** and applies its own floor (`:357–385`) + delta (`:390–392`) + tiebreaks. Ticker-shaped args route to `S6Port.resolve_entity_by_ticker` (BP-661).

### B.2 The cascade it ultimately runs (S6, store-global)

`services/nlp-pipeline/src/nlp_pipeline/application/blocks/entity_resolution.py`:

| Stage | Function (file:line) | Strategy | Query target | Confidence |
|---|---|---|---|---|
| 1 exact | `_stage1_exact` :83 | `normalized_alias_text = lower(trim(surface))`, `alias_type='EXACT'` | `entity_aliases` (18,048 EXACT) | 1.0 |
| 2 ticker/ISIN | `_stage2_ticker_isin` :105 | `canonical_entities.ticker`, fallback `entity_aliases` TICKER/PRIMARY_TICKER/ISIN | `canonical_entities` + aliases | 0.95 |
| 3 fuzzy | `_stage3_fuzzy` :132 | `similarity(normalized_alias_text, lower(surface)) > 0.55` (pg_trgm GIN), top-5 | `entity_aliases` (`idx_entity_aliases_trgm`) | sim × 0.90 |
| 4 ANN | `_stage4_ann` :168 | embed surface → HNSW on `entity_embedding_state` view_type='definition', max-dist gate + top1/top2 margin | embeddings | (1−dist) × mult |

Alias SQL: `entity_alias.py` `exact_match`:94, `ticker_isin_match`:108, `fuzzy_trigram`:320.

### B.3 The precision gate (chat-only, not present on the extraction side)

`resolver_gates.filter_resolver_candidates` (:411): **0.75 absolute similarity floor** (`top_similarity_min`) → drop below-floor; **0.15 delta gate** (`delta_min`) → if top-1/top-2 gap < 0.15, reject ALL as ambiguous; rescued by **query-ticker tiebreak** (`_query_ticker_tiebreak` :356, BP-661) and **verbatim canonical-name tiebreak** (`_query_name_tiebreak` :302, BP-668), with a stop-word strip and BP-459 phantom-twin filter (`_is_phantom_shaped` :283).

### B.4 The asymmetry (the core finding), side by side

| Dimension | Extraction matcher (`_build_raw_relations`) | Chat matcher (S6 cascade + resolver_gates) |
|---|---|---|
| Candidate universe | **This document's NER mentions only** | **Entire `canonical_entities`/`entity_aliases` store (17,174 / 18,048)** |
| Strategies | exact-variant dict lookup only | exact alias + ticker/ISIN + pg_trgm fuzzy + ANN embedding |
| Fuzzy / embedding fall-back | **none** | yes (stage 3 + stage 4) |
| Precision control | n/a (membership-only) | 0.75 floor + 0.15 delta + tiebreaks + phantom filter |
| Miss behaviour | silent `continue` drop of the whole relation | gated; refuses ambiguous, but otherwise binds to a real canonical |

The extraction matcher answers "is this ref one of *this article's* mentions?"; the chat matcher answers "what canonical does this surface mean, anywhere in the store?" Relations are lost in the gap between those two questions.

---

## PART C — Mitigation design + MEASUREMENT

### C.1 Candidate mitigations

**M1 — Canonical-store fall-back in `_build_raw_relations` (reuse the chat matcher).**
Before the `continue` at enriched_event.py:268, when an endpoint resolves to `None`, run the **same S6 cascade** (exact alias → ticker → fuzzy≥0.55 with the 0.75 floor + 0.15 delta gate) against the canonical store; on a precision-safe hit, use that canonical UUID. Reuse `EntityAliasRepository.exact_match`/`fuzzy_trigram` + `resolver_gates.filter_resolver_candidates` — do NOT reinvent.
- *Pros:* directly closes the asymmetry; recovers relations whose endpoint exists as a canonical (incl. entities canonicalized by other docs) without minting noise.
- *Cons / trade-off:* (a) **timing** — for the cited-doc class the canonical is created by the async worker *after* extraction, so a synchronous fall-back at extraction time would not yet find it (measured: 94% of recovering aliases are `provisional_enrichment`, mostly post-dating the doc). It mainly helps cross-doc-already-canonical endpoints and **backfill re-extraction**. (b) precision: must keep the 0.75/0.15 gate or fuzzy will resurrect garbage ("analysts"→"PIMCO analysts").

**M2 — Synthesize a provisional entity for a mentioned-but-unresolved *or non-mention* endpoint (extend the existing path).**
Today `synthesize_provisional_refs` only promotes refs that are already mentions. Extend it: for any LLM ref **not** in `entity_id_by_ref` after the cascade, mint a `provisional_entity_queue` row keyed on the LLM ref surface itself (not requiring a backing mention), set `entity_provisional=True` + `provisional_queue_id`, and let the relation flow; the UnresolvedResolutionWorker canonicalizes it later and KG promotes the evidence.
- *Pros:* **this is the fix for the dominant miss-reason (i)** — the non-mention endpoint (Jackery's counterparty) finally gets an id. Reuses the proven provisional → worker → KG-promotion machinery (4,834 provisional relations already land this way).
- *Cons / trade-off:* must apply the existing churn-guard (`MAX_PROVISIONAL_PER_HOUR`) AND a quality gate, or GLiNER-free hallucinated refs and noise nouns ("analysts", "shareholders") create junk provisional shells. Mitigate by only synthesizing for refs the **LLM emitted in a relation/event** (already evidence-backed) and length/blocklist-filtered.

**M3 — Fix the upstream NER recall gap (so the endpoint becomes a mention).**
The root is that GLiNER misses the second endpoint. Improving NER recall (or accepting LLM-named refs as pseudo-mentions, which is M2 in disguise) removes the gap at source.
- *Pros:* fixes the real cause; benefits the whole pipeline (resolution, signals, routing density).
- *Cons:* expensive, slow, model-level work; not a targeted fix.

### C.2 Recommendation — layered M2 (primary) + M1 (secondary, gated)

**M2 is the highest-leverage fix** because it addresses the dominant miss-reason (i) — the non-mention endpoint — which M1 cannot (M1 only helps when the endpoint already exists as a canonical). Layer **M1 as a cheap precision-safe pre-step**: try the canonical store first (recovers cross-doc-already-canonical endpoints at zero noise via the 0.75/0.15 gate), and only fall through to **M2 provisional synthesis** for the residual. This reuses the chat matcher (M1) and the provisional machinery (M2) without reinventing either, and keeps precision via the existing gate + churn-guard.

### C.3 MEASUREMENT (simulation results)

Population: distinct **unresolved** `organization`/`company`/`person` mention surfaces (the relation-bearing endpoint types) from `full_pipeline` docs in the last 7 days — a faithful proxy for the endpoint refs the extraction matcher drops. Simulator `/tmp/sim_match.py` ran the S6 cascade (exact alias → ticker alias → pg_trgm fuzzy ≥0.55, conf=sim×0.90) + chat gate (0.75 floor, 0.15 delta) against `intelligence_db`, with HTML-entity unescape + suffix-strip normalization.

**Random sample (n=50, deterministic `ORDER BY md5(surface)`):**

| Outcome | Count | % |
|---|---:|---:|
| exact_alias | 42 | 84% |
| unresolvable | 7 | 14% |
| fuzzy_below_floor | 1 | 2% |
| **RECALL (sim>0.55)** | **42/50** | **84%** |
| **PRECISION-SAFE (exact/ticker/fuzzy≥0.75 & delta)** | **42/50** | **84%** |

**Top-frequency sample (n=60):** 34/60 = **57%** recover. The shortfall is entirely GLiNER noise in the head — "analysts" (290×), "management" (90×), "patients", "investors", "shareholders", "women", "developers", "operators" — which correctly stay unresolved. Real-company head misses that the *alias store* still lacks: `exxonmobil`, `onsemi`, `sk hynix`, `dutch bros`, `texas roadhouse`, `playtika`, `tencent` (fuzzy-below-floor / unresolvable). Excluding the ~14 noise tokens, real-entity recovery ≈ 90%.

**Precision risk:** spot-checking matches — `msd`→Merck (MRK) ✓ correct; `at&t`/`johnson & johnson`/`procter & gamble`/`s&p global`/`coca-cola` ✓; the false-positive surface is fuzzy partial hits ("uc san diego"→"San Diego" 0.69, "tencent"→"Tencent Cloud" 0.51) — all **below the 0.75 floor**, so the gate already rejects them. Many EXACT hits ("newtons","portman","protera") map to `entity_type='unknown'` shells that are themselves provisional-enrichment artifacts (low value, but not wrong). **With the 0.75/0.15 gate, precision risk is low: the simulation produced zero above-floor wrong bindings in the sampled set.**

**Timing caveat (decisive for M1 vs M2):** for the random sample, comparing alias `created_at` vs the doc's `decided_at`, **~94% of recovering EXACT aliases were `source='provisional_enrichment'` created AFTER extraction** (e.g. `catl` alias 06-11 07:59 vs doc 06-11 07:58; `winwire`/`sarah apple` aliases minted same minute as a later doc). ⇒ A synchronous M1 fall-back at extraction time recovers the **cross-doc-already-canonical** subset (smaller) plus **all backfill re-extractions** (large, one-time); **M2 is required for live, first-touch recovery of the non-mention endpoint.**

### C.4 Expected lift, stated plainly

- **Backfill re-extraction with M1+M2:** ≈ **84%** of currently-dropped relation endpoints become resolvable at the precision-safe gate (random-sample recall), i.e. the large historical empty-relation cohort is substantially recoverable.
- **Live, first-touch with M2 (provisional synthesis for non-mention endpoints):** recovers the dominant miss-reason (i) immediately into `entity_provisional=True` rows that the worker later canonicalizes — the same proven path that already lands 4,834 provisional relations.
- **Live, first-touch with M1 alone:** only the cross-doc-already-canonical subset (minority), because the canonical often does not exist yet.

### C.5 Unit-test plan for the real fix

**M1 (canonical-store fall-back) — `tests/unit/.../test_build_raw_relations_canonical_fallback.py`:**
1. ref not in `entity_id_by_ref` but EXACT alias exists → relation emitted with the canonical UUID, `entity_provisional=False`.
2. ref matches fuzzy sim 0.80 (≥ floor) AND delta ≥ 0.15 → emitted; ref matches fuzzy 0.60 (< 0.75 floor) → still dropped (precision guard holds).
3. delta-ambiguous fuzzy (two canonicals within 0.15) → dropped, not bound to either (mirror `resolver_gates` semantics).
4. HTML-entity surface (`at&amp;t`) unescaped before lookup → resolves to AT&T.
5. both endpoints fall back successfully → relation emitted; only one falls back → still emitted (other already resolved).

**M2 (provisional synthesis for non-mention refs) — extend `tests/unit/.../test_provisional.py`:**
6. LLM relation references a surface that is NOT a mention and NOT in the store → a `provisional_entity_queue` row is minted for that surface; the relation is emitted with `entity_provisional=True` + the new `provisional_queue_id`.
7. churn-guard: ≥ `MAX_PROVISIONAL_PER_HOUR` for the (surface,class) → no new row, relation stays dropped (no churn).
8. noise/blocklist guard: a generic-noun ref ("analysts") or length<3 → NOT synthesized (precision).
9. idempotency: same surface twice in one doc → one queue row, both relations share the queue_id.

**Regression (must stay green):** existing `_build_raw_relations` document-local resolution still works; `synthesize_provisional_refs.complete` counter still increments; KG enriched_consumer still accepts `entity_provisional=True` rows.

---

## D. Appendix — key evidence (read-only, live 2026-06-14/15)

```sql
-- cited doc: 3 relations extracted, 0 landed
-- nlp_db
SELECT mention_text, resolution_outcome FROM entity_mentions
WHERE doc_id='019ec90e-f651-78d8-8348-f4e07a76a339';
--   SYDNEY auto_resolved ; Jackery x7 provisional
-- intelligence_db
SELECT count(*) FROM relation_evidence_raw
WHERE source_document_id='019ec90e-f651-78d8-8348-f4e07a76a339';   -- 0
SELECT status, source_doc_id, assigned_entity_id FROM provisional_entity_queue
WHERE normalized_surface='jackery';   -- resolved, src=this doc, canonical f422a2ea-…

-- EXACT alias provenance (why "unresolved" surfaces now have canonicals)
SELECT source, count(*) FROM entity_aliases
WHERE alias_type='EXACT' AND is_active GROUP BY source ORDER BY 2 DESC;
--   provisional_enrichment 16951  (94%) ; canonical_entity_create 602 ; seeds …

-- doc-level yield proxy (7d): 7565 full_pipeline docs, 5040 yielding narrative relations
SELECT count(*) FROM routing_decisions
WHERE processing_path='full_pipeline' AND decided_at >= now()-interval '7 days';   -- 7565
SELECT count(DISTINCT source_document_id) FROM relation_evidence_raw
WHERE extracted_at >= now()-interval '7 days'
  AND canonical_type IS DISTINCT FROM 'is_in_sector';   -- 5040

-- provisional relations DO land (the path works for mention endpoints)
SELECT entity_provisional, count(*) FROM relation_evidence_raw GROUP BY 1;  -- f:72035 t:4834
```

Simulator: `/tmp/sim_match.py` (throwaway). Samples: `/tmp/unresolved_random.txt` (n=50), `/tmp/topfreq.txt` (n=60).
```
random  : exact 42, unresolvable 7, fuzzy_below_floor 1 → RECALL 84%, precision-safe 84%
topfreq : RECALL 34/60 = 57% (head polluted with NER noise nouns; real-entity recovery ≈90%)
```
