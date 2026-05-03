# Bug Patterns — ML & LLM

> **Category**: ml-llm
> **Description**: ML model integration (Ollama, GLiNER, DeepInfra), LLM adapters, NER/NMS, embedding, prompt/output mismatch
> **Count**: 25 patterns
> **Back to index**: [BUG_PATTERNS.md](../BUG_PATTERNS.md)

---

## BP-022 — NMS IoU boundary: strictly-greater vs greater-or-equal

**Date discovered**: 2026-03-27
**Service affected**: `nlp-pipeline` Block 4 NER (test failures during Wave C-2)
**Prompts updated**: N/A

### Symptom

NMS unit test `test_keeps_higher_confidence_when_overlapping` passes when IoU < threshold but fails when IoU = threshold (0.5 exactly). Spans that should be suppressed are kept, or vice versa.

### Root cause

The PRD says "IoU > 0.5" — strictly greater than. If the implementation uses `>=`, spans with IoU = 0.5 are incorrectly suppressed. Test fixtures using exact boundary values (e.g., spans (0,10) and (0,5) → IoU = 0.5 exactly) will fail because 0.5 is NOT > 0.5.

### Correct implementation pattern

```python
NMS_IOU_THRESHOLD = 0.5

def _nms(mentions):
    ...
    if _iou(a.char_start, a.char_end, b.char_start, b.char_end) > NMS_IOU_THRESHOLD:
        # suppress b (strictly greater than threshold)
```

Test fixtures must use spans with IoU **strictly greater than** 0.5, e.g., (0,10) and (1,9) → IoU = 8/10 = 0.8.

### Test to add (prevents regression)

```python
def test_nms_boundary_iou_exactly_half_not_suppressed():
    # spans (0,10) and (0,5): intersection=5, union=10, IoU=0.5 — NOT suppressed
    m1 = EntityMention(..., char_start=0, char_end=10, confidence=0.9, ...)
    m2 = EntityMention(..., char_start=0, char_end=5, confidence=0.7, ...)
    result = _nms([m1, m2])
    assert len(result) == 2  # neither suppressed at boundary
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/nlp-pipeline/tests/unit/application/blocks/test_ner.py` | Updated test fixtures to use spans with IoU > 0.5 (not exactly 0.5) |

---

---

## BP-043 — Pydantic V2 `Field(strip_whitespace=True)` deprecated

**Affects**: API request schemas using `Field(strip_whitespace=True)` — `TenantCreateRequest`, `PortfolioCreateRequest`, etc.

### Symptom

```
PydanticDeprecatedSince20: Using extra keyword arguments on `Field` is deprecated and will be removed.
Use `json_schema_extra` instead. (Extra keys: 'strip_whitespace')
```

### Root cause

Pydantic V2 removed non-standard kwargs from `Field()`. `strip_whitespace` was a Pydantic V1 feature. In V2, string constraints (including `strip_whitespace`, `min_length`, `max_length`) must be applied via `StringConstraints` in an `Annotated` type.

### Fix

```python
from typing import Annotated
from pydantic import StringConstraints

TrimmedStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]

class TenantCreateRequest(BaseModel):
    name: TrimmedStr
```

Or drop `strip_whitespace` and rely on `min_length`/`max_length` in `Field(...)` only (the length constraints are the primary security fix):

```python
name: str = Field(min_length=1, max_length=255)
```

---

## BP-121 — BGE-large BERT Context Overflow Crashes Ollama GGML Runner

**Symptom**: Ollama returns `500 Internal Server Error` with `{"error":"do embedding request: Post ... EOF"}`. Docker logs show `GGML_ASSERT(i01 >= 0 && i01 < ne01) failed` and `llama runner terminated: signal: aborted`. Subsequent embedding requests continue returning 500 until the model is manually reloaded.

**Root cause**: BGE-large (`bert.context_length: 512`, `position_embd.weight shape: [1024, 512]`) has a hard 512-token BERT context window. Financial text with numbers, tickers, and dollar amounts tokenizes at ~3 chars/token (denser than typical English at ~4-5 chars/token). An article of 339 words in financial English can exceed 512 tokens after adding the instruction prefix (e.g., `"Represent this financial document passage for retrieval: "`). When the token index reaches position 512, the GGML matrix index check `i01 < ne01` fires, killing the runner subprocess.

**Fix**: In `OllamaEmbeddingAdapter.embed()` (`libs/ml-clients/src/ml_clients/adapters/ollama_embedding.py`), truncate the combined `(prefix + text)` string to `_MAX_CHARS = 1500` before sending. This keeps the tokenized length under 500 tokens (leaving margin for CLS/SEP special tokens).

**Affected areas**: Any service using `OllamaEmbeddingAdapter` with section-level or document-level texts; particularly NLP-pipeline S6 `run_embeddings_block` which embeds full section texts (not chunks).

**Prevention**: Always truncate input to BERT-based models at the adapter level. Do not rely on the model to truncate — BERT position embeddings are statically sized and do NOT truncate gracefully (they crash). Use `_MAX_CHARS = context_length * min_chars_per_token` as the safe limit.

**First seen**: 2026-04-08 E2E NLP pipeline investigation.

---

---

## BP-123 — GLiNER `predict_entities(list)` Returns Empty List — Batch API Unsupported

**Symptom**: GLiNER server returns `{"results": []}` (empty) for every batch request despite receiving valid texts. Consumer logs `ner_http_batch_completed, total_entities: 0`.

**Root cause**: `GLiNER.predict_entities(texts, labels)` where `texts` is a list returns `[]` — the GLiNER library batch API is broken (the implementation only works when `texts` is a single string). Passing a list silently returns nothing.

**Fix**: In `infra/gliner/server.py`, change `_run_batch()` to iterate texts individually: `[model.predict_entities(text, ...) for text in req.texts]`. Do NOT call `model.predict_entities(req.texts, ...)` — the batch overload does not work.

**Affected areas**: `infra/gliner/server.py` — the GLiNER HTTP server used by NLP pipeline S6.

**Prevention**: When using GLiNER: always pass a single string to `predict_entities`, wrap iteration at the call site. Do not assume the batch overload works — verify with a quick unit test.

**First seen**: 2026-04-08 E2E NLP pipeline investigation.

---

---

## BP-170 — UNRESOLVED Entity Mentions Permanently Orphaned (No Re-Resolution Pathway)

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-20 |
| **Severity** | HIGH |
| **Affected areas** | `services/nlp-pipeline/src/nlp_pipeline/application/blocks/entity_resolution.py`, `services/knowledge-graph/` (missing worker) |
| **Root cause** | Block 9 entity resolution classifies mentions as PROVISIONAL (0.45–0.72), AUTO_RESOLVED (≥0.72), or UNRESOLVED (<0.45). PROVISIONAL mentions are queued in `provisional_entity_queue` for Worker 13E to create new entities. UNRESOLVED mentions (<0.45) are stored in `nlp_db.entity_mentions` with `resolved_entity_id=NULL` — but there is NO periodic worker or event-driven consumer that re-examines these rows as the entity catalog grows. If a new entity is later added to the knowledge graph (via market instrument consumer or ProvisionalEnrichmentWorker for a different article), all prior UNRESOLVED mentions for that surface form remain permanently orphaned. |
| **Symptom** | Entity signal counts, narrative embeddings (which draw from claims against resolved entities), and routing scores under-count entities mentioned before they were added to the catalog. Knowledge graph has no record of early mentions of entities that now exist. |
| **Fix** | Two options: (A) Periodic re-resolution worker — runs every N hours, queries `nlp_db.entity_mentions WHERE resolved_entity_id IS NULL AND resolution_confidence < 0.45` and re-runs the cascade; (B) Event-driven — S6 consumes `entity.canonical.created.v1`, triggers a targeted re-resolution scan for UNRESOLVED mentions matching the new entity's mention_class. Option B is more surgical and lower overhead. |

### Prevention

When classifying mentions as UNRESOLVED, always store enough metadata (`mention_class`, `resolution_confidence`) to enable future re-resolution as the entity catalog expands. Design pipelines with the assumption that "unresolvable today" means "retry later", not "discard". Consider storing `resolution_outcome` in the DB (currently only in-memory) to enable efficient querying.

---

---

## BP-171 — Provisional Entity Queue Dedup Loses Mention Linkage for Subsequent Articles

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-20 |
| **Severity** | MEDIUM |
| **Affected areas** | `services/nlp-pipeline/src/nlp_pipeline/application/blocks/entity_resolution.py:249–255`, `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_evidence.py` |
| **Root cause** | The `provisional_entity_queue` table has a UNIQUE constraint on `(normalized_surface, mention_class)`. When Article B mentions the same surface form as Article A before Worker 13E resolves the queue row, the INSERT fires `ON CONFLICT DO NOTHING` — Article B's `mention_id` is silently dropped. Article B's `relation_evidence_raw` rows are written with `entity_provisional=true` but the wrong (or missing) `provisional_queue_id`. When Worker 13E resolves the queue row and calls `UPDATE relation_evidence_raw WHERE provisional_queue_id = :queue_id`, Article B's evidence rows are NOT unblocked. The EntityCreatedConsumer's fallback query also cannot match because the entity didn't exist at insertion time. |
| **Symptom** | Relations from any article that mentions the same provisional entity surface after the first article, but before the entity is created, remain stuck with `entity_provisional=true, processed=false` permanently. Worker 13A (confidence recomputation) excludes these rows. Knowledge graph confidence values are under-computed for entities that appeared in multiple articles during their provisional window. |
| **Fix** | Replace the UNIQUE+NOTHING pattern with a proper tracking table: a `provisional_entity_queue_mentions` join table that stores all `(queue_id, mention_id, doc_id)` pairs. The EntityCreatedConsumer unblocks all evidence linked to any mention in the queue. Alternatively, change the INSERT to return the existing queue_id on conflict (`ON CONFLICT DO UPDATE SET updated_at=now() RETURNING queue_id`) and pass that returned queue_id into the evidence row. |

### Prevention

When using `ON CONFLICT DO NOTHING` for deduplication in a queue pattern, verify that the deduplication does NOT cause downstream data loss. If multiple producers need to reference the same queue row, the queue table must store N-to-1 relationships (e.g., a join table), not just the first producer's reference. Audit every `ON CONFLICT DO NOTHING` insert that is also referenced by a foreign key in another table.

---

---

## BP-231 — qwen3:0.6b CPU Inference Latency Exceeds Default Ollama Timeout

| Field | Value |
|-------|-------|
| **Service** | rag-chat (S8) intent classifier; nlp-pipeline (S6) relevance scoring |
| **Severity** | MAJOR (intent classification always falls back to keyword heuristic) |
| **Discovered** | 2026-04-26 QA pre-demo investigation |
| **Root cause** | `qwen3:0.6b` is a thinking model (reasoning tokens emitted before answer). On an aarch64 CPU container with no GPU, a single inference (including reasoning) takes 13–16 seconds (`total_duration: ~13468ms` measured from Ollama `/api/generate` response). The `OllamaIntentClassifier` had a 5-second timeout — the request always timed out before Ollama responded, transparently falling back to the keyword heuristic. No error was surfaced in logs beyond `ollama_intent_classifier_fallback`. |
| **Symptom** | `ollama_intent_classifier_fallback` emitted on every chat request. All intents resolved by keyword heuristic — COMPARISON and REASONING queries not correctly classified. Sub-questions never generated for multi-entity comparisons. |
| **Fix** | Increase Ollama timeout to 20 seconds (`timeout=20.0`). This ensures warm inference (~14s) completes; cold model-load calls (~30s on first request) still fall back, which is acceptable. Added inline comment referencing this bug pattern. |

### Prevention

When targeting `qwen3:*` (thinking models) on CPU-only containers, benchmark the cold and warm inference latency first. Cold load can be 2–3× warm time. Set timeouts at `warm_latency × 1.5` minimum, and set `keep_alive=-1` in the Ollama `/api/generate` request to prevent model eviction between calls.

---

---

## BP-237 — pgvector CAST in UPSERT Requires String Format, Not Python list[float]

| Field | Value |
|-------|-------|
| **Service** | knowledge-graph (S7) — `entity_embedding_state.py:upsert()` |
| **Severity** | HIGH (all embedding writes silently fail — UPSERT executes but embedding stays NULL) |
| **Discovered** | 2026-04-27 KG pipeline investigation |
| **Root cause** | asyncpg cannot serialize a Python `list[float]` to a PostgreSQL `vector(1024)` column even when the SQL uses `CAST(:embedding AS vector)`. asyncpg rejects the Python list with `DataError: invalid input for query argument`. This causes the entire `session.execute()` call to fail silently inside a `try/except` block. The embedding column is never written. Related to BP-233 (ANN SELECT case) but the UPSERT INSERT case has additional subtlety: `EXCLUDED.embedding` in the ON CONFLICT clause also needs the CAST applied. |
| **Symptom** | `entity_embedding_state.upsert()` executes without raising, but the `embedding` column stays `NULL`. No error logged because the exception is swallowed. Phase 3 of `DefinitionRefreshWorker` appears to succeed (commit happens) but embeddings don't appear in the DB. |
| **Fix** | Convert `list[float]` to pgvector text format before binding: `embedding_str = "[" + ",".join(str(x) for x in embedding) + "]" if embedding is not None else None`. Use `CAST(:embedding AS vector)` and `CAST(EXCLUDED.embedding AS vector)` in SQL. Use `COALESCE(CAST(EXCLUDED.embedding AS vector), entity_embedding_state.embedding)` for the update clause to preserve existing embeddings when `embedding_str=None`. |

### Prevention

Whenever writing to a `vector(N)` column via asyncpg (raw SQL or SQLAlchemy `text()`), always convert the embedding list to string format. Do NOT rely on SQLAlchemy ORM type coercion — it does not apply to `text()` queries. The pattern `"[" + ",".join(str(x) for x in v) + "]"` is the canonical fix. See also BP-233 for the ANN SELECT case.

---

---

## BP-238 — Ollama Model Reference Without Registry Verification Causes Silent 100% Fallback

| Field | Value |
|-------|-------|
| **Service** | rag-chat (S8) — `BGEReranker`, `OllamaIntentClassifier` |
| **Severity** | HIGH (entire capability permanently degraded; error only visible in logs) |
| **Discovered** | 2026-04-27 model externalization investigation |
| **Root cause** | Config fields like `ollama_reranker_model=bge-reranker-v2-m3` reference models that either: (a) do not exist in the Ollama registry at all (`bge-reranker-v2-m3` → "file does not exist" on `ollama pull`), or (b) cannot be served without model-swap from a competing model, causing timeout on every call. In both cases the caller catches `Exception`, logs a warning, and returns the fallback — creating a **silent permanent degradation** where logs show 100% fallback rate but the system continues to function at reduced quality. |
| **Symptom** | Every reranker call logs `"event": "reranker_fallback"` — no reranking ever happens. Every classifier call logs `"event": "ollama_intent_classifier_fallback"` — `sub_questions` and `rephrased_query` never populated. RAG quality silently degrades. |
| **Fix** | For models not in Ollama registry: externalize to an API provider (Cohere Rerank for `bge-reranker-v2-m3`, DeepInfra for `qwen3:0.6b`). Implement the external adapter with graceful fallback. Wire the external adapter as primary in the service lifespan when the API key is set. |

### Prevention

1. At startup, validate each `ollama_*_model` config field by calling `GET /api/tags` on the Ollama container and checking the model is listed. Log `ERROR` if missing.
2. Any component with a `try: ... except Exception: fallback()` pattern should emit a counter metric (`fallback_count`) so alerting can trigger when fallback rate exceeds threshold.
3. Before referencing a new Ollama model in config, run `ollama pull <model>` in the dev environment and verify it succeeds. Add this to the PR checklist for any `ollama_*_model` config change.

---

---

## BP-272 — ML Adapter latency_ms=0 / tokens_in=0 Corrupts Cost Analytics

**Category**: ML / cost tracking
**Severity**: MAJOR
**Affected areas**: `libs/ml-clients/src/ml_clients/adapters/gemini_description.py`, `services/nlp-pipeline/.../unresolved_resolution_worker.py`
**First seen**: 2026-04-28 (observability audit)

**Symptoms**:
- `llm_usage_log` table shows `latency_ms=0` and `tokens_in=0` for many LLM calls
- Cost estimation in `estimate_cost()` returns $0.00 for calls that consumed tokens
- Monthly cost tracking is unreliable

**Root Cause**:
Several adapters and workers call `usage_logger.log()` but pass literal `0` for `latency_ms`, `tokens_in`, and `tokens_out`. `GeminiDescriptionAdapter` documents this explicitly: `# GeminiDescriptionAdapter does not track wall-clock time`. The response objects from Ollama (`eval_count`, `eval_duration`), DeepInfra (`usage.prompt_tokens`, `usage.completion_tokens`), and Google Gemini (`usage_metadata.prompt_token_count`) all contain the actual values but are never read.

**Fix Applied**:
Add `t0 = time.perf_counter()` before every LLM API call. Read token usage from the API response after the call. Pass real values to `usage_logger.log()`. Never pass literal `0`.

**Prevention**:
- Code review checklist: if a call to `usage_logger.log()` has literal `0` for any numeric field, it is wrong
- Add a lint rule or test that asserts `tokens_in > 0` for non-embedding calls in the usage log

---

---

## BP-292 — Prompt/Lookup Mismatch: LLM Outputs Reference Values Absent from Post-Parse Lookup

**Category**: LLM pipelines / prompt design
**Severity**: CRITICAL (silent end-to-end output destruction)
**Affected areas**: Any pipeline where an LLM is given a list of valid values in the prompt and the post-parse code looks values up in a dict that is built from a *subset* of that list
**First seen**: 2026-04-30 (revised audit; root pattern of F-CRIT-07 in news-pipeline deep-dive 2026-04-29)

**Symptoms**:
- Producer-side log shows the LLM emits non-empty structured output (relations, claims, citations, tool calls) referring to values from the list given in the prompt.
- Consumer-side / post-parse output array is empty or substantially smaller than what the LLM produced.
- No exceptions, no error logs — the silent drop happens inside a `continue` / `dict.get(...) is None` branch.
- All dashboards green; downstream tables remain empty.

**Root Cause**:
The prompt advertises a vocabulary V₁ (e.g., "you may use any of these entity mentions: A, B, C, D"). The post-parse code builds a lookup table V₂ ⊆ V₁ (e.g., only mentions whose entity resolution succeeded), and silently drops every reference the LLM emits to a value in V₁ \ V₂. The LLM is doing exactly what it was asked to do; the code has a contract bug.

Concrete worldview instance: `services/nlp-pipeline/.../article_consumer.py:793-796` builds `entity_id_by_ref` from `m.resolved_entity_id IS NOT NULL`, while `deep_extraction.py` advertised every mention text (resolved + unresolved). `_build_raw_relations` `continue`s silently when `entity_id_by_ref.get(ref) is None`, dropping ~100% of relations on the 66% of documents with zero resolved entities.

**Fix**:
Two-step structural fix (not "log a warning"):
1. **Make V₁ = V₂ at construction**: only put values in the prompt that the lookup will know how to resolve. For unresolved entities, generate a provisional ID *before* the prompt is built (e.g., insert into `provisional_entity_queue`) and pass that ID through.
2. **Make drift impossible to silence**: replace `continue` with a structured error that emits a Prometheus counter (`*_contract_violation_total{reason}`) and either raises or routes to a quarantine table. Add a CI test that constructs a known prompt/lookup pair, induces drift, and asserts the counter increments.

**Prevention**:
- Whenever a prompt template includes a `{list_of_valid_values}` placeholder, the same code path should produce the post-parse lookup. They MUST share a source.
- Add an end-to-end yield gauge (e.g., `kg_extraction_yield = persisted / extracted`) so silent drops cannot hide.
- Code review: any `if x.get(ref) is None: continue` inside a parser of LLM output is suspect — prove the lookup is exhaustive.
- See R28 (proposed): "Pipeline boundary contracts must round-trip through a contract test that fails on silent drops."

---

## BP-293 — Producer-Side `resolved_only` Lookup Destroys End-to-End Output Without Error Signal

**Category**: NLP pipelines / Kafka-boundary design
**Severity**: CRITICAL (specific instance of BP-292 at the S6→S7 boundary)
**Affected areas**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py` and any consumer that emits enriched events to a downstream service
**First seen**: 2026-04-30 (F-CRIT-07 in news-pipeline deep-dive)

**Symptoms**:
- `nlp.article.enriched.v1` events show `relation_count > 0` (count of LLM output) but `raw_relations` array length is 0 or much smaller.
- S7 graph materializes 0 production relations despite `relation_evidence_raw` consumer running healthily.
- `relation_summaries`, `relation_contradiction_links`, `claim` tables stay empty for days/weeks.
- Producer log says "extraction success: relations=6, claims=3"; consumer log says "raw_relations: 0".

**Root Cause**:
Same as BP-292 specialised to the S6 producer side: `_build_raw_relations(extraction.relations, entity_id_by_ref)` skips relations whose endpoints are not in the resolved-only lookup; the prompt fed the LLM both resolved and unresolved mentions; the parser cannot map unresolved-mention-references back to UUIDs.

**Fix**:
- Switch to a provisional-ID flow: Block 9 (entity resolution) creates a `provisional_entity_queue` row for any mention without a canonical, returning a UUID. Block 10 (deep extraction) prompt uses canonical-or-provisional UUIDs as the reference vocabulary. `entity_id_by_ref` is the union of canonical IDs and provisional queue IDs. See PLAN-0058 Wave A task A-1.
- Update `_build_raw_relations` to raise `KGContractViolation` instead of `continue` when a ref is unknown.
- Emit `nlp_kg_contract_violation_total{reason}` Prometheus counter.
- Add `kg_extraction_yield` histogram (= persisted / extracted per article).

**Prevention**:
- Any boundary between an LLM extractor and a downstream graph materialiser MUST have an extraction-yield gauge.
- Treat empty downstream tables as a P1 alert if upstream metrics show non-empty extraction.
- See PLAN-0057 Wave A and PLAN-0058 (out-of-scope for runtime fix; but the eval framework in Wave C catches this class of regression structurally).

---

## BP-294 — Schema-Defined Audit Table Never Written: Hardcoded `usage_logger=None` / Missing `*_repo.add_batch()`

**Category**: Observability / persistence
**Severity**: CRITICAL (pipeline becomes opaque; cost-blind LLM spend; no auditability)
**Affected areas**: Any worker that takes a `usage_logger` (or similar) constructor parameter; any Block-N consumer that has an audit-trail repository wired into its UoW but does not call `.add()` / `.add_batch()`
**First seen**: 2026-04-30 (F-CRIT-02, F-CRIT-03 in news-pipeline deep-dive)

**Symptoms**:
- The audit/log table exists in the schema and a repository class exists for it.
- Production row count for the audit table is **zero** despite the parent operation running thousands of times.
- Code search for the repo's `.add()` / `.add_batch()` call returns no live call sites (only tests).
- Worker constructors accept `usage_logger=None` (or similar) and the call site never injects the real adapter.

**Root Cause**:
Two distinct anti-patterns that produce the same symptom:
1. **`usage_logger=None` default left in production**: a constructor accepts `usage_logger: LLMUsageLogger | None = None` and the production wiring forgot to inject `LLMUsageLogger(...)`. All downstream `if self._logger: self._logger.log(...)` branches are dead. Worldview instance: 3 workers in `services/nlp-pipeline/` and `services/knowledge-graph/.../infrastructure/workers/` had `usage_logger=None` hardcoded (F-CRIT-03; `llm_usage_log` table empty across 18,695 LLM calls).
2. **Repo wired into UoW but never called**: `mention_resolution_repo` is in the UoW (`uow.mr_repo`) but the `article_consumer` never calls `await uow.mr_repo.add_batch(rows)` after Block 9 (entity resolution) — F-CRIT-02; `mention_resolutions` empty across 18,695 mentions.

**Fix**:
- Wire `LLMUsageLogger` (or analogue) at composition root; never let the production constructor default to `None`. If `None` is necessary for tests, use `Optional[LLMUsageLogger]` with a `NullLLMUsageLogger` fallback that records nothing but satisfies the call shape — making "zero rows" structurally observable.
- Audit each repo in each UoW: if it has an `add()` method, grep for live call sites; if there are none outside tests, that's a missing write.
- Add a startup smoke test: after first ingest, assert that `audit_table_row_count > 0` within the SLO window.

**Prevention**:
- Code review: flag any production `Optional[X] = None` default on a logger / audit repo.
- CI test: instrument each pipeline boundary with a "this audit table must have at least one row after the smoke fixture" assertion.
- See R28 (proposed): pipeline boundary contracts must include audit-table write coverage.

---

## BP-309 — Classification Without Consequence: Positive Outcome Branch Writes Nothing

**Category**: Worker pipeline / silent data loss
**Severity**: HIGH (entire entity detection→enrichment pipeline broken; detected entities never created)
**First seen**: 2026-05-02 (investigation into ProvisionalEnrichmentWorker receiving zero items)
**Services**: S6 nlp-pipeline (`UnresolvedResolutionWorker`)

### Symptom

`UnresolvedResolutionWorker` processes unresolved entity mentions, runs LLM binary classification, and classifies many mentions as `ENTITY_CREATED` (a real finance-domain entity not yet in the platform). However, `provisional_entity_queue` in `intelligence_db` remains empty. `ProvisionalEnrichmentWorker` (S7) therefore has nothing to process. No new `canonical_entities` are ever created from article mentions.

The worker logs `resolution_outcome=ENTITY_CREATED` at normal rates, so no error surface is visible — the bug is a silent no-op.

### Root cause

`_process_mention()` handles the `ENTITY_CREATED` outcome by updating the mention status only:

```python
# services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/unresolved_resolution_worker.py
if outcome == ResolutionOutcome.ENTITY_CREATED:
    await self._repo.update_mention_status(mention.id, "entity_created")
    # ← no provisional_entity_queue insert; no entity created
```

There is no `_enqueue_for_enrichment()` call. The `provisional_entity_queue` table (in `intelligence_db`) is never written. S7's `ProvisionalEnrichmentWorker` reads from that queue and finds it perpetually empty.

A second contributing bug: `_phase1_cascade()` is a stub that always returns `False`, meaning every mention that should match an existing entity also falls through to LLM classification, amplifying the volume of misrouted `ENTITY_CREATED` outcomes.

### Fix

Two changes required (see PLAN-0061 Wave B):

1. **Implement `_phase1_cascade()`**: query `intel_session_factory` via `EntityResolutionBlock.resolve_single()` — if a match is found, update mention as `RESOLVED` and return; do not call the LLM.

2. **Add `_enqueue_for_enrichment()` to the `ENTITY_CREATED` branch**: insert a row into `provisional_entity_queue` with `(entity_name, entity_type, source_article_id, mention_id)` so that S7's `ProvisionalEnrichmentWorker` can pick it up.

### Prevention

- **Rule**: Any worker with a classification/routing outcome that is named after an entity state (e.g. `ENTITY_CREATED`, `NEW_RECORD`, `ACCEPTED`) MUST write to at least one persistence layer in that branch. If a branch writes nothing, it is a bug unless that branch explicitly represents "discard" (e.g. `NOISE`, `DUPLICATE`).
- **Code review checklist**: For every `if outcome == X` branch in a classification worker, verify a `await self._repo.*` or `await session.execute(insert(...))` call exists in the body.
- **Test pattern**: Write an integration test that: (1) inserts a mention, (2) mocks the LLM to return `ENTITY_CREATED`, (3) asserts `provisional_entity_queue` has one row after the worker runs.

---

---

## BP-310 — Unbounded Retry Loop: Periodic Worker Without a Failure Terminal State

**Service**: Any periodic worker (knowledge-graph S7, nlp-pipeline S6, ...)
**Severity**: MEDIUM (silent throughput erosion; no crash, no alert)
**Detected**: PLAN-0061 investigation 2026-05-02

### Symptoms

- A queue row is picked up every cycle but never makes forward progress (LLM returns `None`, downstream API down, etc.).
- `retry_count` keeps incrementing with no upper bound.
- The worker's per-cycle log shows `failed=N` monotonically, but `enriched=0` — no entities are created.
- Healthy rows in the queue are delayed because poison rows consume concurrency slots every cycle.

### Root Cause

The `ProvisionalEnrichmentWorker` Phase 3 failure branch unconditionally reset status to `'pending'` regardless of `retry_count`:

```sql
UPDATE provisional_entity_queue
SET retry_count = retry_count + 1, status = 'pending'
WHERE queue_id = :queue_id
```

Any row whose LLM extraction consistently returns `None` (malformed mention, hallucinated class, downstream model outage) will retry on every cycle indefinitely, consuming a concurrency slot each time.

### Fix

Add a `max_retries` threshold (default 5). When `retry_count + 1 >= max_retries`, set `status = 'failed'` (terminal — the Phase 1 SELECT guards `WHERE retry_count < :max_retries` so the row is never fetched again). Emit a Prometheus counter (`s7_provisional_enrichment_failed_total`) to make the failure visible.

See `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py` — `_apply_retry()`.

### Prevention

- **Rule**: Every queue-draining periodic worker MUST have a `max_retries` config key and a terminal failure status. A queue row that can never succeed must not block healthy rows forever.
- **Code review checklist**: When reviewing a `WHERE status = 'pending'` SELECT + subsequent retry UPDATE, ask: "What happens on the 100th failure of the same row?" If the answer is "it retries again", add a cap.
- **Metric**: Add a counter for transitions to terminal status (`*_failed_total`). Absence of this metric in a worker is a signal the pattern is missing.

---

---

## BP-311 — DeepInfra Model Availability Mismatch: Config Defaults Referencing Unavailable Models

**Pattern**: A service config defaults to a specific DeepInfra model ID (e.g., `Llama-3.2-1B-Instruct`, `Llama-3.2-3B-Instruct`) that is not available on the account, causing all API calls to fail silently with a model-not-found 404 that is swallowed by the fallback chain or logged but never alerted.

**Root Cause**: Model availability on DeepInfra depends on account tier. A developer who confirmed a model available on one account tier may hardcode its ID; when the account tier changes or the model is retired, every dependent worker silently falls back to Ollama CPU without any alert.

**Discovered**: PLAN-0061 Wave D — `Llama-3.2-1B-Instruct` (rag-chat classification) and `Llama-3.2-3B-Instruct` (nlp-pipeline relevance scoring + unresolved resolution) were both unavailable. All calls were failing at the API level.

**Fix**: Replace unavailable model IDs with the confirmed-available `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo`. Standardize all classification tasks to a single confirmed model to reduce drift.

### Prevention

- **Rule**: When changing a DeepInfra model ID default in config, verify availability via a live curl call (`curl https://api.deepinfra.com/v1/openai/chat/completions -d '{"model": "<id>", ...}'`) before committing.
- **Verification test**: Each service that uses a DeepInfra API model should have a smoke-test or startup probe that validates the model ID responds with 200. A 404 on startup should emit a WARNING log with the exact model ID and a fallback indication.
- **Single source of truth**: Keep a confirmed-available model list per DeepInfra account in `.claude-context.md` or `docs/MASTER_PLAN.md`. Never derive defaults from documentation alone.

---

---

## BP-312 — Worker Instantiated but Not Registered in Scheduler

**Pattern**: A worker class is correctly instantiated in `build_workers()` and stored in the `workers` dict, but its key is **never added to the `_register_jobs()` job list**. The worker object is created at startup, holds resources, but never runs. Dependent data stays in its initial `NULL`/empty state forever.

**Root Cause**: `build_workers()` and `_register_jobs()` are maintained independently. Adding a new worker requires editing both functions. It is easy to update `build_workers()` and forget `_register_jobs()`, especially when the worker key is a new name. There is no startup assertion that every worker key has a corresponding scheduled job.

**Discovered**: Twice in S7 (knowledge-graph):
1. PLAN-0061 Wave A — `provisional_enrichment` worker: instantiated in `build_workers()` but missing from `_register_jobs()`. Result: all provisional entities stayed in `status='provisional'` forever.
2. Fix-bug session 2026-05-02 — `embedding_refresh` worker: same pattern. Result: all `relation_summaries.summary_embedding` stayed `NULL`; HNSW ANN search on relations always returned 0 results; the RAG relation context path was completely dark.

**Example**:
```python
# build_workers() — correctly creates the worker:
workers["embedding_refresh"] = EmbeddingRefreshWorker(session_factory, llm_client)

# _register_jobs() — BUG: this entry is missing!
jobs = [
    ("confidence_recompute", s.worker_confidence_interval_s, "worker_13a_confidence"),
    # ... all other workers ...
    # ("embedding_refresh", s.worker_embedding_refresh_interval_s, "worker_13f_embedding"),  ← missing!
]
```

**Fix**: Add the missing `(job_name, interval_setting, job_id)` tuple to the `jobs` list in `_register_jobs()`.

**Regression test**: `test_scheduler.py::TestEmbeddingRefreshRegistration::test_all_ten_jobs_registered` — asserts that every expected `job_id` appears in the set of registered jobs.

### Prevention

- **Rule**: Every key added to the `workers` dict in `build_workers()` MUST have a corresponding entry in the `jobs` list in `_register_jobs()`. These two functions are a coupled pair.
- **Test**: `test_all_ten_jobs_registered` verifies the full set of expected job IDs. When adding a new worker, update this test's `expected_ids` set — a failing test is your first signal of a missing registration.
- **Code review**: When reviewing a `build_workers()` addition, immediately check whether `_register_jobs()` was also updated. If not, block the PR.
- **Observability**: At startup, log the full list of registered job IDs at INFO level. Cross-reference against the keys in `build_workers()` in the startup log. A missing key is immediately visible in the startup trace.

---

---

## BP-322 — `json.dumps(..., default=str)` Stringifies Pydantic Models: Cache Round-Trip Breaks

**Context**: A FastAPI route stores response data in Valkey (Redis) using `json.dumps(response_data, default=str)`. The response data dict contains Pydantic model objects (e.g., `BriefSection`, `BriefBullet`) as field values. `default=str` converts these to Python repr strings (`"BriefSection(title='...', bullets=[...])"`) rather than JSON dicts. On cache read, `json.loads` returns these repr strings, and `PublicBriefingResponse(**data)` fails with a Pydantic `ValidationError: Input should be a valid dictionary or instance of BriefSection`.

**Symptoms**:
- Every cache hit produces `briefing_cache_read_failed` warning
- Briefing endpoint generates a new LLM call on every request (no cache benefit)
- `briefing_cache_read_failed` log shows `"Input should be a valid dictionary or instance of BriefSection [type=model_type, input_value='title=\\'...\\' bullets=[...]\"]"'`

**Example**: `json.dumps({"sections": [BriefSection(title="Macro", bullets=[BriefBullet(text="...", citations=[...])])]}, default=str)` produces `{"sections": ["BriefSection(title='Macro', bullets=[BriefBullet(...)])"]}`.

### Root cause

`json.dumps` with `default=str` calls `str()` on non-serializable objects. Pydantic models have a `__str__` that returns their Python repr, not a JSON-compatible dict.

### Fix

Use Pydantic's native serialization for cache round-trips:

```python
# Write: use model_dump_json() — Pydantic handles nested models correctly
resp = PublicBriefingResponse(**response_data)
await valkey.set(cache_key, resp.model_dump_json(), ex=ttl)

# Read: use model_validate_json() — avoids json.loads + **data
raw = cached.decode("utf-8") if isinstance(cached, bytes) else cached
resp = PublicBriefingResponse.model_validate_json(raw)
resp.cached = True
return resp
```

### Prevention

- **Never** use `json.dumps(..., default=str)` to cache Pydantic model instances — they serialize to repr strings, not JSON.
- If you must use raw `json.dumps` for caching, call `.model_dump()` on each Pydantic object first, or use `model_dump_json()` on the top-level response.
- Add a test that round-trips the cached format: `assert ModelClass.model_validate_json(resp.model_dump_json()) == resp`.

---

---

## BP-324 — LLM Adapter Optimistic Assumption: Plan Adds Application-Layer Feature, Adapter Never Updated

**Symptom**: A plan adds a new capability (e.g., tool-calling, structured JSON output) to the application layer and specifies that the LLM will "emit tool_use blocks". The tool-use loop is coded, wired, and tested. At runtime: no tools are ever called, the LLM just generates text, and no errors are surfaced — silent no-op.

**Root cause**: The plan assumed the LLM infrastructure adapter (`DeepInfraCompletionAdapter`, `OpenRouterAdapter`) already supports the new API feature (e.g., OpenAI `tools` parameter). The adapter was never updated. The Protocol port's `chat_with_tools()` method exists in the interface but was never implemented in the concrete adapter. Since the application layer only sees the Protocol, it compiles and passes mypy — the missing implementation is invisible at development time.

**PLAN-0066 instance**: Wave H defined `ChatOrchestratorUseCase._tool_use_path()` and `ToolExecutor`, but `deepinfra_adapter.py` payload was never updated to include `tools: list[dict]`. Result: the tool-use path ran but the LLM never called any tools.

**Prevention**:
- When a plan adds a new application-layer capability that depends on LLM adapter support, the FIRST task in Wave 1 must be the adapter update — not an application-layer task
- Architecture test: add `test_deepinfra_adapter_implements_llm_chat_provider` that checks `isinstance(deepinfra_adapter, LlmChatProvider)` at test time (not just Protocol runtime check)
- In plan pre-flight gate: if a plan uses `tool_use` / `chat_with_tools` / any new LLM API feature, explicitly verify the adapter implements it by reading the adapter source file before writing any wave tasks

**Affected areas**: `services/rag-chat/src/rag_chat/infrastructure/llm/deepinfra_adapter.py`; `openrouter_adapter.py`; `ollama_adapter.py`; `provider_chain.py`; any plan that adds a new application-layer LLM feature and does not read the concrete adapter implementation before writing tasks.

---

---

## BP-324 — `NODE_ENV=production` Used as HTTPS Guard Causes `upgrade-insecure-requests` to Break All Static Assets

**Category**: Config / Security
**Severity**: CRITICAL (entire frontend non-functional — no CSS, no JS)
**First seen**: 2026-05-03
**Services**: worldview-web (frontend)

**Symptoms**:
- All CSS and JS requests in the browser show "no response" / `net::ERR_SSL_PROTOCOL_ERROR` in DevTools
- Page renders correct HTML content (SSR) but completely unstyled, no interactivity
- `curl http://localhost:3001/_next/static/…` returns HTTP 200 — issue is browser-only
- HTML page loads fine because `upgrade-insecure-requests` **exempts top-level navigations**

**Root cause**:
`NODE_ENV=production` is required for Next.js standalone mode but was also used as a proxy for "we are on HTTPS." Two HTTPS-only directives were gated on it:
1. `upgrade-insecure-requests` in CSP — tells browsers to upgrade ALL sub-resource HTTP requests to HTTPS
2. `Strict-Transport-Security` header — tells browsers to never use HTTP for this origin

When the Docker dev container serves HTTP, `upgrade-insecure-requests` causes Chrome/Safari to request `https://localhost:3001/_next/static/…` instead of `http://`. No HTTPS server exists → SSL handshake fails → all static assets fail silently.

**Example**:
```typescript
// Bad — NODE_ENV conflates "optimized build" with "HTTPS deployment"
...(process.env.NODE_ENV === "production" ? ["upgrade-insecure-requests"] : []),

// Good — use the WS URL scheme as the HTTPS signal
...(wsBase.startsWith("wss://") ? ["upgrade-insecure-requests"] : []),
```

**Fix applied** (`apps/worldview-web/middleware.ts` + `apps/worldview-web/next.config.ts`):
Gate both `upgrade-insecure-requests` and HSTS on `NEXT_PUBLIC_WS_BASE_URL.startsWith("wss://")`.
- Docker dev: `NEXT_PUBLIC_WS_BASE_URL=ws://localhost:8010` → HTTPS headers disabled
- Production: `NEXT_PUBLIC_WS_BASE_URL=wss://…` → HTTPS headers enabled

**Prevention**:
- NEVER use `NODE_ENV === "production"` alone to gate `upgrade-insecure-requests` or `Strict-Transport-Security`
- Any HTTPS-only browser directive must be gated on a variable that represents the actual deployment SCHEME
- Review checklist: HTTPS security headers must use an HTTPS-specific guard, not `NODE_ENV`
- Add a smoke test: assert `upgrade-insecure-requests` is absent in CSP when `NEXT_PUBLIC_WS_BASE_URL` is `ws://`

---

---

## BP-327 — EmbeddingClientProtocol Interface Mismatch: `embed(str)` vs `embed(list[EmbeddingInput])`

**Date discovered**: 2026-05-03
**Service affected**: `knowledge-graph` (S7) Block 11 canonicalization

### Symptom

Every message is dead-lettered with:
```
Unexpected embedding error: 'str' object has no attribute 'instruction_prefix'
```

### Root cause

A local `EmbeddingClientProtocol` defines `embed(text: str) -> list[float]` (single string). The actual `OllamaEmbeddingAdapter.embed()` takes `list[EmbeddingInput]` and iterates it. When called with a bare string, the iterator yields individual characters. Each character is treated as an `EmbeddingInput` and `inp.instruction_prefix` fails.

### Fix

Add a bridge/adapter shim in the wiring code (`enriched_consumer_main.py`):

```python
class _EmbeddingBridgeClient:
    async def embed(self, text: str) -> list[float]:
        outputs = await _raw_embedding_adapter.embed(
            [EmbeddingInput(text=text, model_id=_embedding_model_id)]
        )
        return outputs[0].embedding
```

### Prevention

- When defining a local protocol, immediately verify it matches the real adapter's signature
- Use the real adapter type in the consumer wiring, or add a typed shim at the boundary
- Integration tests that call `embedding_client.embed("some_text")` would have caught this

---

## BP-328 — `relation_type_registry` Embeddings Never Seeded: ANN Canonicalization Permanently Disabled

**Date discovered**: 2026-05-03
**Service affected**: `knowledge-graph` (S7) Block 11 canonicalization

### Symptom

All relation types fall through to step 3 ("proposed") — zero relations ever enter the `relations` table even when S6 produces valid extractions with clear canonical type names. `relation_evidence_raw` accumulates rows with `canonical_type=NULL`.

### Root cause

The Alembic migration seeds 27 `relation_type_registry` rows without embeddings. The `find_by_embedding` query has `WHERE embedding IS NOT NULL`, so with all embeddings NULL it always returns 0 rows. No worker or startup script populates these embeddings after the initial seed.

### Fix

Run a one-time seed script using the same model as the consumer:

```python
for canonical_type in registry_entries:
    embedding = await ollama.embed(canonical_type)
    await conn.execute("UPDATE relation_type_registry SET embedding = $1 WHERE type_id = $2", ...)
```

Long-term: add a migration step that populates embeddings, OR add a startup check in `enriched_consumer_main.py` that warns if any registry entry is missing embeddings.

### Prevention

- Any table that drives ANN lookup must have embeddings populated at seed time
- Add a startup health check: `SELECT COUNT(*) FROM relation_type_registry WHERE embedding IS NULL` — warn if > 0
- Migration checklist: if a migration adds vector columns, add a follow-up migration or seed script that populates them

---

## BP-329 — Extraction Prompt `predicate` Unconstrained: Freeform Relation Types Bypass Canonicalization

**Date discovered**: 2026-05-03
**Service affected**: `nlp-pipeline` (S6) → `knowledge-graph` (S7) Block 11

### Symptom

S6 extracts relations (events/claims have bounded vocabularies that work correctly), but S7 dead-letters all of them as "proposed" types. `outbox_events` accumulates `relation.type.proposed.v1` rows for types like "issued shares", "is_CEO_of", "interviewed", "fueled" — none of which match the canonical registry even with generous ANN thresholds.

### Root cause

The `DEEP_EXTRACTION` prompt constrains `event_type`, `claim_type`, and `polarity` to explicit vocabularies, but the `predicate` field (relation type) is left completely unconstrained. The LLM generates natural-language predicates in whatever form it deems appropriate.

### Fix

Add `predicate` to the FIELD VOCABULARIES section in the prompt, listing all 27 canonical relation types:

```python
"  predicate (relation type — pick the closest match, no other values allowed):\n"
"    acquired_by | analyst_rating | board_member_of | competes_with | ...\n"
```

### Prevention

- Any field that maps to a controlled vocabulary in downstream processing MUST be listed in FIELD VOCABULARIES in the extraction prompt
- When adding a new relation type to `relation_type_registry`, also update the prompt
- Run extraction smoke tests that check `predicate` values are all in the canonical set

---

## BP-337 — Qwen3.x `reasoning_content` Bleed-Through When `reasoning_effort=none` Is Silently Ignored

**Date discovered**: 2026-05-03
**Service affected**: `knowledge-graph` (S7) / `libs/ml-clients` `DeepSeekExtractionAdapter`

### Symptom

Extractions return `FatalError: malformed extraction output` even though `reasoning_effort=none` is set. Logs show `tokens_out=0` and Ollama fallback triggers. The thinking model puts its full chain-of-thought (~6,000 chars) in `reasoning_content` while `content` stays empty.

### Root cause

Qwen3.x thinking models route output to `reasoning_content` by default. When `reasoning_effort=none` is honoured, the answer lands in `content`. When the model ignores the hint for specific requests, the thinking chain fills `reasoning_content` while `content` stays empty. A fallback line `raw_response = msg.content or getattr(msg, "reasoning_content", None) or ""` read the 6,000-char thinking chain as the response — it always fails `json.loads`.

### Fix

```python
# Bad — reads thinking chain when content is empty
raw_response: str = msg.content or getattr(msg, "reasoning_content", None) or ""

# Good — empty content IS the error signal when reasoning_effort=none
raw_response: str = msg.content or ""
```

### Prevention

- Never add a `reasoning_content` fallback when `reasoning_effort=none` is set; empty `content` means the model's constraint was violated — treat as a retryable error, not a recovery path
- Log `finish_reason` on every extraction call to distinguish `stop` vs `length`

---

## BP-338 — Small-Model (≤1B) Alias-List Repetition Truncates JSON at max_tokens

**Date discovered**: 2026-05-03
**Service affected**: `knowledge-graph` (S7) / `libs/ml-clients` `DeepSeekExtractionAdapter`

### Symptom

Extraction for well-known entities (Apple Inc., Wayfair) fails with `deepseek_extraction_malformed finish_reason=length`. The raw response shows correct `canonical_name`/`ticker`/`isin` followed by an infinite aliases loop: `["Apple Inc.", "Apple Inc.", ...]` until the token cap truncates mid-string, breaking JSON parsing.

### Root cause

Qwen3.5-0.8B ignores the "Maximum 5" instruction for popular entities and generates list items until `max_tokens`. With `max_tokens=2048`, the response grew to ~6,000 chars. Lowering to 512 caps it at ~1,500 chars (still truncated for the worst cases, but partial-recovery works).

### Fix

```python
# 1. Lower max_tokens to fit a valid response (entity profile ≤120 tokens)
max_tokens=512  # was 2048

# 2. Partial-JSON recovery when finish_reason=length
if finish_reason == "length":
    stripped = re.sub(r',\s*"aliases"\s*:.*$', "", cleaned, flags=re.DOTALL)
    try:
        _r: dict[str, object] = json.loads(stripped + "}")
        _r.setdefault("aliases", [])
        recovered = _r
    except json.JSONDecodeError:
        pass
```

Also validate LLM-provided ISINs before DB write:
```python
isin = _isin_raw if (_isin_raw and re.fullmatch(r"[A-Z0-9]{12}", _isin_raw)) else None
```

### Prevention

- For ≤1B extraction models: set `max_tokens` to the minimum covering a valid response, not the model's context limit
- Position array fields LAST in the JSON schema — scalar fields can then be recovered via partial-JSON strip when arrays overflow
- Always validate LLM-generated DB values against column constraints before write

---

## BP-339 — `reasoning_effort=none` Corrupts Qwen3.x Description Output

**Date discovered**: 2026-05-03
**Service affected**: `knowledge-graph` (S7) / `libs/ml-clients` `DeepInfraDescriptionAdapter`

### Symptom

All entity descriptions from the DeepInfra description adapter are either empty strings (primary model `Qwen3-235B-A22B-Instruct-2507` returns `'\n'`) or malformed text with every word on its own line separated by `\n\n` (fallback `Qwen3-32B`). Logs show `deepinfra_description_empty` for primary and silent fallback to Qwen3-32B which produces the line-per-word output.

### Root cause

The `extra_body={"reasoning_effort": "none"}` parameter was added to the description adapter call.
- **Qwen3-235B-A22B**: Honours the flag but returns only `'\n'` (empty content) — the model enters a constrained non-reasoning mode that produces no output for description tasks.
- **Qwen3-32B** (fallback): Ignores the flag and outputs words separated by double newlines, producing gibberish descriptions.

`reasoning_effort=none` is designed for DeepSeek models; it should never be passed to Qwen3.x models.

### Fix

```python
# Bad — Qwen3-235B returns '\n' (empty), Qwen3-32B outputs words on separate lines
extra_body={
    "reasoning_effort": "none",
    "prompt_cache_key": "entity_description_v1",
}

# Good — omit reasoning_effort entirely for Qwen3.x description tasks
extra_body={"prompt_cache_key": "entity_description_v1"}
```

### Prevention

- **Never pass `reasoning_effort` to Qwen3.x models** for generative tasks (descriptions, summarisation). Only DeepSeek models (`deepseek-ai/DeepSeek-*`) handle this parameter correctly.
- `reasoning_effort=none` IS safe for classification tasks using Llama-3.1-8B (confirmed working in `unresolved_resolution_worker.py`).
- If adding a new LLM adapter for a thinking model: test that `reasoning_effort=none` produces non-empty content before shipping; if output is `'\n'`, remove the flag.
- Add an integration smoke-test for description adapters that asserts `len(description) > 50` after the first API call.

---
