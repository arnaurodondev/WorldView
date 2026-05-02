---
id: PLAN-0061
title: "Provisional Enrichment Reliability + DeepSeek-V4-Flash Migration"
status: in-progress
created: 2026-05-02
updated: 2026-05-03
source: /investigate 2026-05-02 (provisional enrichment deep-dive + billing audit)
waves: 5
---

# PLAN-0061 — Provisional Enrichment Reliability + DeepSeek-V4-Flash Migration

## Overview

**Goal**: Fix 6 confirmed bugs in the provisional entity enrichment pipeline that cause entities to be enriched 3× too slowly, silently retry forever, and classify mentions without ever creating the downstream canonical entity. Concurrently, migrate the primary extraction LLM to `deepseek-ai/DeepSeek-V4-Flash` (better quality for structured extraction, already supported by existing adapter infrastructure) and audit the untracked `Llama-3.2-11B-Vision-Instruct` usage ($0.39/day, source unknown).

**Source investigation**: `/investigate` session 2026-05-02 — ProvisionalEnrichmentWorker + UnresolvedResolutionWorker deep-dive.

**Dependencies**: None. All changes are isolated to S6 (nlp-pipeline), S7 (knowledge-graph), `libs/ml-clients`, and worldview-gitops. Wave E adds one new Kafka topic (`entity.provisional.queued.v1`) and one Avro schema.

**Does NOT overlap with**:
- PLAN-0057 (completed 2026-05-01)
- PLAN-0058 (touches rag-chat/retrieval only)
- PLAN-0060 (KG + retrieval activation — different files)

---

## Pre-Flight Gate

| Check | Result | Note |
|-------|--------|------|
| No unresolved BLOCKING open questions | PASS | All bugs confirmed via code reading |
| No external API field reality check needed | PASS | DeepSeek-V4-Flash API key confirmed live by user |
| No active cross-plan conflicts | PASS | No other plan modifies provisional_enrichment.py or fallback_chain.py |
| Architecture compliance | PASS | No RULES.md violations; session-boundary pattern (ARCH-003) already respected in worker |

---

## Codebase State Verification

| Item | Current State (from code) | Target State | Delta |
|------|--------------------------|--------------|-------|
| `worker_embedding_refresh_interval_s` | 10800s (3h), used for provisional enrichment scheduler slot | Separate `worker_provisional_enrichment_interval_s` default 600s | New config key + scheduler rewire |
| `_BATCH_LIMIT` in provisional_enrichment.py | 20, hardcoded constant | Configurable, default 50; LLM Phase 2 runs concurrently | Constant → config + asyncio.gather |
| `build_workers()` | Two `ProvisionalEnrichmentWorker` instances: `"provisional_enrichment"` (used) + `"worker_13e_provisional"` (dead) | Single instance under `"provisional_enrichment"` | Remove dead entry |
| `provisional_entity_queue` fetch query | No `retry_count` cap; rows retry forever | `WHERE retry_count < :max_retries`; terminal `'failed'` status | SQL guard + config key |
| `_phase1_cascade()` | Stub: always returns `False` | Implements cascade re-resolution via `intel_session_factory` | Real implementation |
| `ENTITY_CREATED` outcome in UnresolvedResolutionWorker | Updates mention status only; no downstream write | Also inserts to `provisional_entity_queue` | New INSERT call |
| `FallbackChainClient` | Ollama primary → Gemini secondary (2 slots) | DeepInfra V4-Flash primary → Ollama fallback-1 → Gemini fallback-2 (3 slots) | New constructor param + wire |
| `cost.py` PRICING table | `deepinfra`: only `deepseek-r1-distill-qwen-32b` | Add `deepseek-ai/DeepSeek-V4-Flash` entry ($0.14/$0.28) | Dict entry |
| `NLP_PIPELINE_EXTRACTION_API_MODEL_ID` | `meta-llama/Meta-Llama-3.1-8B-Instruct` | `deepseek-ai/DeepSeek-V4-Flash` | gitops env update |
| `Llama-3.2-11B-Vision-Instruct` billing (1.58M tokens) | Source unknown — not in gitops | Identified + replaced/documented | Audit task |

---

## Plan Dependency Graph

```
Wave A (Worker Reliability)
  ↓
Wave B (Resolution Pipeline) — depends on A (retry-cap infra)
  ↓
Wave C (DeepSeek-V4-Flash) — depends on nothing, can parallel with A/B
  ↓
Wave D (Audit + GitOps) — depends on C (new model ID must exist)
  ↓
Wave E (Event-Driven Enrichment) — depends on B (emit from _enqueue_for_enrichment)
```

Waves A and C can be executed **in parallel** (different files).
Wave B depends on Wave A (uses new config keys). Wave D depends on C.
Wave E depends on Wave B (`_enqueue_for_enrichment` must exist before we wire the Kafka emit into it).

---

## Wave A — Provisional Enrichment Worker Reliability ✅

**Goal**: Fix the four ProvisionalEnrichmentWorker bugs that cap enrichment at 20 entities/3h, allow infinite retries, and create a dead worker instance.

**Status**: **DONE** — 2026-05-02 · 19 tests pass · ruff + mypy clean

**Depends on**: none
**Estimated effort**: 45–60 min
**Architecture layer**: infrastructure + config

### Pre-read (agent must read before starting)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py`
- `services/knowledge-graph/src/knowledge_graph/config.py`
- `worldview-gitops/env/dev/knowledge-graph.env`
- `worldview-gitops/values/knowledge-graph.yaml`

---

#### T-A-1: Fix scheduler interval — add dedicated config key

**Type**: impl + config
**depends_on**: none
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/config.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py`
- `worldview-gitops/env/dev/knowledge-graph.env`
- `worldview-gitops/values/knowledge-graph.yaml`

**What to build**:
The scheduler currently maps `provisional_enrichment` to `s.worker_embedding_refresh_interval_s` (10800s = 3h). The docstring says 10 minutes but the wrong config key is used. Add a dedicated `worker_provisional_enrichment_interval_s: int = 600` to `Settings` and rewire the scheduler tuple.

**Logic**:
1. In `config.py`, add after `worker_embedding_refresh_interval_s`:
   ```python
   worker_provisional_enrichment_interval_s: int = 600  # 10 min — PLAN-0061
   ```
2. In `scheduler.py` `_register_jobs()`, change the tuple:
   ```python
   # Before:
   ("provisional_enrichment", s.worker_embedding_refresh_interval_s, "worker_13e_provisional"),
   # After:
   ("provisional_enrichment", s.worker_provisional_enrichment_interval_s, "worker_13e_provisional"),
   ```
3. In `worldview-gitops/env/dev/knowledge-graph.env`, add:
   ```
   KNOWLEDGE_GRAPH_WORKER_PROVISIONAL_ENRICHMENT_INTERVAL_S=600
   ```
4. In `worldview-gitops/values/knowledge-graph.yaml`, add the env var under the `env:` block.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_provisional_enrichment_uses_dedicated_interval` | `scheduler.get_job("worker_13e_provisional").trigger.interval.seconds == 600` when settings has `worker_provisional_enrichment_interval_s=600` | unit |

**Acceptance criteria**:
- [ ] `config.py` has `worker_provisional_enrichment_interval_s: int = 600`
- [ ] Scheduler tuple uses the new key, not `worker_embedding_refresh_interval_s`
- [ ] gitops env + values updated
- [ ] Test passes

---

#### T-A-2: Remove duplicate worker instance in build_workers()

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py`

**What to build**:
In `build_workers()`, `ProvisionalEnrichmentWorker` is instantiated twice:
- `workers["provisional_enrichment"]` — used by scheduler (key matches job name)
- `workers["worker_13e_provisional"]` — never looked up (dead code)

Remove the second instantiation. The scheduler's `_resolve_job("provisional_enrichment")` will find the first one.

**Logic**: Delete lines 250-255 in `scheduler.py` (the `"worker_13e_provisional"` dict entry).

**Acceptance criteria**:
- [ ] `build_workers()` creates exactly one `ProvisionalEnrichmentWorker` instance
- [ ] mypy passes (no unused import)

---

#### T-A-3: Add retry cap and 'failed' terminal status

**Type**: impl + config
**depends_on**: none
**blocks**: T-B-1 (B-1 reads from the queue; cap prevents it processing poison rows)
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py`
- `services/knowledge-graph/src/knowledge_graph/config.py`

**What to build**:
Without a cap, a row with malformed mention text that consistently causes LLM to return `None` will be retried on every cycle forever. Add `WHERE retry_count < :max_retries` to the SELECT, and after exhausting retries transition the row to `'failed'` (terminal — never picked up again).

**Logic**:
1. In `config.py` (knowledge-graph), add:
   ```python
   worker_provisional_enrichment_max_retries: int = 5
   ```
2. Inject `max_retries` into `ProvisionalEnrichmentWorker.__init__` (default 5).
3. In the Phase 1 SELECT, add: `AND retry_count < :max_retries`
4. In Phase 3, when `profile is None` and `retry_count + 1 >= max_retries`, set `status = 'failed'` instead of resetting to `'pending'`:
   ```sql
   UPDATE provisional_entity_queue
   SET retry_count = retry_count + 1,
       status = CASE WHEN retry_count + 1 >= :max_retries THEN 'failed' ELSE 'pending' END
   WHERE queue_id = :queue_id
   ```
5. Emit Prometheus counter `kg_provisional_enrichment_failed_total` when transitioning to `'failed'`.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_retry_cap_transitions_to_failed` | Row with `retry_count=4` + LLM None → status becomes `'failed'` | unit |
| `test_retry_below_cap_stays_pending` | Row with `retry_count=2` + LLM None → status stays `'pending'` | unit |

**Acceptance criteria**:
- [ ] SELECT includes `AND retry_count < :max_retries`
- [ ] Row at max retries transitions to `'failed'`, not re-queued
- [ ] Prometheus counter emitted on `'failed'` transition
- [ ] Tests pass

---

#### T-A-4: Increase batch size and parallelize LLM Phase 2

**Type**: impl + config
**depends_on**: none
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py`
- `services/knowledge-graph/src/knowledge_graph/config.py`

**What to build**:
`_BATCH_LIMIT = 20` is a hardcoded constant. Phase 2 LLM calls are sequential (for loop). With a 10-min interval and 20 sequential calls at ~1s each, throughput is fine. But with higher batch sizes and concurrent calls the worker can handle spikes. Make the limit configurable and parallelize Phase 2 with a semaphore.

**Logic**:
1. Replace hardcoded `_BATCH_LIMIT = 20` with a constructor parameter `batch_limit: int = 50`.
2. Add `KNOWLEDGE_GRAPH_WORKER_PROVISIONAL_ENRICHMENT_BATCH_SIZE=50` to config.
3. In Phase 2, replace the sequential `for queue_id, ... in pending_rows:` loop with `asyncio.gather` bounded by a semaphore (default concurrency = 5):
   ```python
   semaphore = asyncio.Semaphore(self._concurrency)
   async def _enrich_one(row): ...
   results = await asyncio.gather(*[_enrich_one(r) for r in pending_rows])
   ```
4. Add `worker_provisional_enrichment_concurrency: int = 5` to config and `concurrency: int = 5` constructor param.
5. Wire `batch_limit` and `concurrency` from `build_workers()` via `settings`.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_batch_limit_respected` | With 100 pending rows, only `batch_limit` are fetched | unit |
| `test_concurrent_enrichment` | 10 rows processed with concurrency=3: no more than 3 coroutines active simultaneously | unit |

**Acceptance criteria**:
- [ ] `_BATCH_LIMIT` is gone; batch size is config-driven (default 50)
- [ ] Phase 2 uses `asyncio.gather` with configurable semaphore
- [ ] Tests pass; no session held during concurrent LLM calls (ARCH-003)

---

### Validation Gate — Wave A
- [x] `ruff check services/knowledge-graph/` passes
- [x] `mypy services/knowledge-graph/` passes
- [x] `python -m pytest services/knowledge-graph/tests/unit/infrastructure/workers/test_provisional_enrichment.py -v` — 10 new tests (6 new T-A-3/A-4 + 1 T-A-1 scheduler)
- [x] `python -m pytest services/knowledge-graph/tests/unit/infrastructure/ -v` — 409 pass, 0 regressions
- [x] gitops env + values updated (worldview-gitops/ + configs/docker.env)

### Break Impact — Wave A
| Broken File | Why | Fix Required |
|-------------|-----|-------------|
| `tests/unit/infrastructure/workers/test_provisional_enrichment.py` | `ProvisionalEnrichmentWorker(session_factory, llm_client)` constructor gains `batch_limit`, `max_retries`, `concurrency` params | Add keyword args with defaults to all test instantiations |
| `scheduler.py` `build_workers()` | Passes new params from settings | Pass `batch_limit=settings.worker_provisional_enrichment_batch_size` etc. in `build_workers()` |

### Regression Guardrails — Wave A
- **BP-235 variant**: do not hold DB session during asyncio.gather LLM calls. Phase 1 (read+lock) must commit+release before Phase 2 begins. ARCH-003 pattern already in place — do not break it.
- **BP-007**: no new DB columns added in this wave; no migration needed.

---

## Wave B — UnresolvedResolutionWorker: Phase 1 Cascade + Entity Creation ✅

**Goal**: Implement the two missing behaviors that cause the worker to waste LLM budget on every mention (Phase 1 stub) and to classify entities without ever creating them (ENTITY_CREATED gap).

**Status**: **DONE** — 2026-05-02 · 9 new tests (27 total pass) · ruff + mypy clean

**Depends on**: Wave A (retry-cap infra in place before we insert new provisional_queue rows)
**Estimated effort**: 60–90 min
**Architecture layer**: application + infrastructure

### Pre-read (agent must read before starting)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/unresolved_resolution_worker.py`
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/entity_resolution.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/entity_mention.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py` (for provisional_entity_queue schema reference)

---

#### T-B-1: Implement Phase 1 cascade re-resolution

**Type**: impl
**depends_on**: none (parallel with T-B-2)
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/unresolved_resolution_worker.py`

**What to build**:
`_phase1_cascade()` always returns `False`. It is supposed to re-run the 4-stage entity resolution cascade against the current `canonical_entities` table for each unresolved mention. This is a "free" operation (no LLM cost) that would retroactively resolve mentions whose entity was seeded after the article was originally processed (e.g., Wave B seeds added in PLAN-0057).

The `intel_session_factory` is already accepted as `__init__` parameter. When it is not None, Phase 1 should:
1. Build a minimal `EntityResolutionBlock` (or call the equivalent repo methods) using the `intel_session_factory`.
2. Attempt cascade re-resolution: Stage 1 (exact alias), Stage 2 (ticker/ISIN), Stage 3 (fuzzy), Stage 4 (ANN).
3. If a canonical is found, write `resolved_entity_id` to the `entity_mention` row and return `True`.

**Logic**:
```python
async def _phase1_cascade(self, mention: EntityMentionModel) -> bool:
    if self._intel_sf is None:
        return False
    # Import late to avoid circular deps
    from nlp_pipeline.application.blocks.entity_resolution import EntityResolutionBlock
    async with self._intel_sf() as intel_session:
        block = EntityResolutionBlock(intel_session)
        result = await block.resolve_single(
            mention_text=mention.mention_text,
            mention_class=mention.mention_class,
        )
    if result is None:
        return False
    # Write resolved_entity_id back to nlp_db
    async with self._nlp_sf() as session:
        repo = EntityMentionRepository(session)
        await repo.update_resolved_entity(mention.mention_id, result.entity_id)
        await session.commit()
    return True
```

Check `EntityResolutionBlock` for the exact method signature. If no `resolve_single` exists, read the block and call the closest equivalent (likely the existing 4-stage method adapted for single mention).

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_phase1_cascade_resolves_mention` | When intel_session_factory returns a matching canonical, mention is marked resolved and True returned | unit |
| `test_phase1_cascade_returns_false_no_match` | When no canonical found, returns False; mention not modified | unit |
| `test_phase1_cascade_skipped_without_intel_factory` | `intel_sf=None` → returns False immediately, no DB call | unit |

**Acceptance criteria**:
- [ ] `_phase1_cascade()` is no longer a stub
- [ ] When a canonical exists for the mention, Phase 2 LLM call is skipped
- [ ] `intel_session_factory` is required at service startup (log WARNING if None)
- [ ] Tests pass

---

#### T-B-2: On ENTITY_CREATED outcome, insert to provisional_entity_queue

**Type**: impl
**depends_on**: none (parallel with T-B-1)
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/unresolved_resolution_worker.py`

**What to build**:
When the LLM binary classifier decides `is_entity=true`, the worker marks the mention `resolution_outcome=ENTITY_CREATED` — but does nothing else. No canonical entity is created. The fix: after marking the mention, also insert a row into `provisional_entity_queue` so that S7's `ProvisionalEnrichmentWorker` picks it up and calls the LLM for a full entity profile.

The `provisional_entity_queue` insert should be idempotent — if a row for `(normalized_surface, mention_class)` already exists with status != `'failed'`, skip the insert (ON CONFLICT DO NOTHING on `(normalized_surface, mention_class)` if a unique index exists, otherwise check via SELECT first).

**Logic** (in `_process_mention`, after writing `ENTITY_CREATED` to entity_mention):
```python
if outcome == ResolutionOutcome.ENTITY_CREATED:
    # Mark mention
    async with self._nlp_sf() as session:
        repo = EntityMentionRepository(session)
        await repo.update_resolution_outcome(mention.mention_id, ResolutionOutcome.ENTITY_CREATED.value)
        await session.commit()
    stats.entity_created += 1
    # Enqueue for full enrichment in S7
    await self._enqueue_for_enrichment(mention)
```

```python
async def _enqueue_for_enrichment(self, mention: EntityMentionModel) -> None:
    """Insert into provisional_entity_queue so S7 can create the canonical entity."""
    from nlp_pipeline.infrastructure.nlp_db.repositories.provisional_queue import ProvisionalQueueRepository
    async with self._nlp_sf() as session:
        repo = ProvisionalQueueRepository(session)
        await repo.enqueue_if_absent(
            queue_id=new_uuid7(),
            mention_text=mention.mention_text,
            normalized_surface=mention.normalized_mention_text or mention.mention_text.lower().strip(),
            mention_class=str(mention.mention_class),
            context_snippet=None,
            source_doc_id=mention.doc_id,
        )
        await session.commit()
```

Check `nlp_db` models to confirm the `provisional_entity_queue` table is accessible from nlp_pipeline's session (it may be in `intelligence_db`, not `nlp_db`). If it's in `intelligence_db`, use `self._intel_sf` instead. Verify via `services/intelligence-migrations/alembic/versions/` which DB the table lives in.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_entity_created_enqueues_provisional` | After `ENTITY_CREATED` outcome, provisional_queue repo `enqueue_if_absent` is called | unit |
| `test_entity_created_enqueue_idempotent` | Second call for same surface+class does not create duplicate | unit |
| `test_noise_does_not_enqueue` | `NOISE` outcome: provisional_queue repo NOT called | unit |

**Acceptance criteria**:
- [ ] `ENTITY_CREATED` outcome triggers provisional_queue insert
- [ ] Insert is idempotent (duplicate call is a no-op)
- [ ] `NOISE` and `UNRESOLVED` outcomes do not enqueue
- [ ] Tests pass
- [ ] Correct session factory used (intel vs nlp based on which DB hosts provisional_entity_queue)

---

### Validation Gate — Wave B
- [x] `ruff check services/nlp-pipeline/` passes
- [x] `mypy services/nlp-pipeline/` passes
- [x] `python -m pytest services/nlp-pipeline/tests/unit/infrastructure/workers/ -v` — 9 new tests added (27 total pass)
- [x] No regressions in `services/nlp-pipeline/tests/` (665 pass excluding pre-existing env-missing deepseek test)

### Break Impact — Wave B
| Broken File | Why | Fix Required |
|-------------|-----|-------------|
| `tests/unit/infrastructure/workers/test_unresolved_resolution_worker.py` | `_process_mention` gains a provisional_queue side-effect | Mock the new `_enqueue_for_enrichment` call in existing tests that test other outcomes |

### Regression Guardrails — Wave B
- **BP-007**: `provisional_entity_queue` is in `intelligence_db`. Do not write to it via `nlp_db` session — use `intel_session_factory`. Confirm DB by reading the Alembic migration that creates the table.
- **R24 (RULES.md)**: Only `intelligence-migrations` owns `intelligence_db` DDL. No schema changes here — insert-only.

---

## Wave C — DeepSeek-V4-Flash Integration ✅

**Goal**: Add `deepseek-ai/DeepSeek-V4-Flash` as the primary extraction provider in `FallbackChainClient` (for S7 entity profile enrichment) and as the NLP deep extraction model (replacing `Meta-Llama-3.1-8B-Instruct` for structured JSON extraction tasks). Binary classification tasks (relevance scoring, intent, entity noise classification) stay on `Meta-Llama-3.1-8B-Instruct` — they are simpler yes/no decisions where the 7× lower cost outweighs any quality delta.

**Status**: **DONE** — 2026-05-02 · 7 new tests (13 fallback-chain + 6 scheduler-provider = 19 total) · ruff + mypy clean

**Depends on**: none (can run in parallel with Waves A and B)
**Estimated effort**: 45–60 min
**Architecture layer**: infrastructure + config

### Model Migration Decision Matrix

| Task | Current Model | Migrate? | Reason |
|------|--------------|----------|--------|
| S7 entity profile extraction (ProvisionalEnrichmentWorker) | Ollama qwen2.5:7b → Gemini Flash Lite | YES → V4-Flash primary | Entity knowledge requires a capable model; Ollama is slow on CPU; V4-Flash at $0.14/M is cheaper than Gemini |
| NLP deep article extraction (Block 10) | `Meta-Llama-3.1-8B` ($0.02/M) | YES → V4-Flash ($0.14/M) | 8B is undersized for structured JSON extraction; V4-Flash produces better schema adherence and fewer parse retries |
| NLP relevance scoring | `Meta-Llama-3.1-8B` ($0.02/M) | NO | Binary scoring — cheap model is fine |
| NLP unresolved entity classification | `Meta-Llama-3.1-8B` ($0.02/M) | NO | Binary yes/no — cheap model is fine |
| RAG intent classification | `Meta-Llama-3.1-8B` ($0.02/M) | NO | Simple 8-class classification — keep cheap |
| RAG chat completion | `DeepSeek-R1-Distill-Qwen-32B` | NO | Reasoning quality required for financial Q&A |

### Pre-read (agent must read before starting)
- `libs/ml-clients/src/ml_clients/cost.py`
- `libs/ml-clients/src/ml_clients/adapters/deepseek_extraction.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/llm/fallback_chain.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py` (`build_workers` function)
- `services/knowledge-graph/src/knowledge_graph/config.py`
- `worldview-gitops/env/dev/knowledge-graph.env`
- `worldview-gitops/env/dev/nlp-pipeline.env`

---

#### T-C-1: Add DeepSeek-V4-Flash to cost.py and FallbackChainClient

**Type**: impl
**depends_on**: none
**blocks**: T-C-2
**Target files**:
- `libs/ml-clients/src/ml_clients/cost.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/llm/fallback_chain.py`

**What to build**:

**Part 1 — cost.py**: Add V4-Flash pricing to the `"deepinfra"` dict:
```python
"deepinfra": {
    "deepseek-r1-distill-qwen-32b": {"input": 0.69, "output": 2.19},
    "deepseek-ai/DeepSeek-V4-Flash": {"input": 0.14, "output": 0.28},  # PLAN-0061
},
```

**Part 2 — FallbackChainClient**: The current chain is Ollama → Gemini. Add DeepInfra as the new primary slot (position 0). The chain becomes: DeepInfra-V4-Flash → Ollama → Gemini. DeepInfra is fast (GPU, ~1-2s) so short retry delays make sense.

Constructor changes:
```python
def __init__(
    self,
    *,
    deepinfra_extraction: ExtractionClient | None = None,  # NEW — primary
    ollama_embedding: EmbeddingClient | None = None,
    gemini_embedding: EmbeddingClient | None = None,
    ollama_extraction: ExtractionClient | None = None,
    gemini_extraction: ExtractionClient | None = None,
    usage_logger: LlmUsageLogProtocol | None = None,
    retry_delays_deepinfra: tuple[float, ...] = (5.0, 15.0),  # fast GPU retries
    retry_delays_ollama: tuple[float, ...] = _DEFAULT_OLLAMA_DELAYS,
    retry_delays_gemini: tuple[float, ...] = _DEFAULT_GEMINI_DELAYS,
) -> None:
```

In `extract()`, prepend the DeepInfra attempt:
```python
async def extract(self, inp, *, entity_id=None):
    if self._deepinfra_ext is not None:
        result = await self._try_extraction(
            self._deepinfra_ext, inp, provider="deepinfra",
            delays=self._delays_deepinfra, entity_id=entity_id,
            estimated_cost_usd=_deepinfra_extraction_cost(inp),
        )
        if result is not None:
            return result
    # ... existing Ollama → Gemini ...
```

Add cost estimator:
```python
def _deepinfra_extraction_cost(inp: ExtractionInput) -> float:
    chars = len(inp.prompt) + len(inp.context)
    return round(chars / 1_000_000 * 0.14, 8)
```

Note: Embedding stays Ollama → Gemini (DeepInfra embeddings are handled separately via `DeepInfraEmbeddingAdapter` in S6/S7 config, not via FallbackChainClient).

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_deepinfra_primary_called_first` | When deepinfra_extraction is set, it's called before ollama | unit |
| `test_falls_back_to_ollama_on_deepinfra_failure` | DeepInfra raises → Ollama called | unit |
| `test_falls_back_to_gemini_on_both_failures` | DeepInfra + Ollama both raise → Gemini called | unit |
| `test_deepinfra_cost_logged` | Successful DeepInfra call logs non-zero estimated_cost_usd | unit |
| `test_v4_flash_pricing` | `estimate_cost("deepinfra", "deepseek-ai/DeepSeek-V4-Flash", 1_000_000, 1_000_000)` == 0.42 | unit |

**Acceptance criteria**:
- [ ] `cost.py` has V4-Flash entry under `"deepinfra"`
- [ ] `FallbackChainClient` accepts `deepinfra_extraction` as new primary slot
- [ ] Extraction chain order: DeepInfra → Ollama → Gemini
- [ ] Embedding chain unchanged: Ollama → Gemini
- [ ] All existing FallbackChainClient tests still pass (new param is keyword-only with default None)
- [ ] Tests pass

---

#### T-C-2: Wire DeepSeek-V4-Flash into KG build_workers()

**Type**: impl + config
**depends_on**: T-C-1
**blocks**: T-D-1 (D-1 updates gitops env, needs config keys to exist first)
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py` (`build_workers`)
- `services/knowledge-graph/src/knowledge_graph/config.py`

**What to build**:
Add `KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY` and `KNOWLEDGE_GRAPH_DEEPINFRA_EXTRACTION_MODEL_ID` to `Settings`. In `build_workers()`, if the API key is set, instantiate a `DeepSeekExtractionAdapter` pointing at DeepInfra and pass it as `deepinfra_extraction` to `FallbackChainClient`.

Config additions to `knowledge_graph/config.py`:
```python
deepinfra_api_key: str = ""  # KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY
deepinfra_extraction_model_id: str = "deepseek-ai/DeepSeek-V4-Flash"  # KNOWLEDGE_GRAPH_DEEPINFRA_EXTRACTION_MODEL_ID
deepinfra_extraction_base_url: str = "https://api.deepinfra.com/v1/openai"  # KNOWLEDGE_GRAPH_DEEPINFRA_EXTRACTION_BASE_URL
deepinfra_extraction_concurrency: int = 5  # KNOWLEDGE_GRAPH_DEEPINFRA_EXTRACTION_CONCURRENCY
```

In `build_workers()`, inside `if llm_client is not None:` block, before constructing `FallbackChainClient`:
```python
deepinfra_ext = None
if settings.deepinfra_api_key:
    from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter
    import asyncio
    deepinfra_ext = DeepSeekExtractionAdapter(
        api_key=settings.deepinfra_api_key,
        model_id=settings.deepinfra_extraction_model_id,
        base_url=settings.deepinfra_extraction_base_url,
        semaphore=asyncio.Semaphore(settings.deepinfra_extraction_concurrency),
    )
```

Pass `deepinfra_extraction=deepinfra_ext` to `FallbackChainClient`.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_build_workers_wires_deepinfra_when_key_set` | With `deepinfra_api_key="key"`, `FallbackChainClient.deepinfra_extraction` is not None | unit |
| `test_build_workers_no_deepinfra_without_key` | With `deepinfra_api_key=""`, `FallbackChainClient.deepinfra_extraction` is None | unit |

**Acceptance criteria**:
- [ ] Config keys added to `Settings` with correct `env_prefix="KNOWLEDGE_GRAPH_"`
- [ ] `DeepSeekExtractionAdapter` instantiated when API key is set
- [ ] `FallbackChainClient` receives `deepinfra_extraction=...`
- [ ] Tests pass

---

#### T-C-3: Update NLP pipeline extraction model in gitops

**Type**: config
**depends_on**: none (gitops-only change, no code change needed — adapter already supports model_id)
**blocks**: none
**Target files**:
- `worldview-gitops/env/dev/nlp-pipeline.env`
- `worldview-gitops/values/nlp-pipeline.yaml`

**What to build**:
Change `NLP_PIPELINE_EXTRACTION_API_MODEL_ID` from `meta-llama/Meta-Llama-3.1-8B-Instruct` to `deepseek-ai/DeepSeek-V4-Flash`. The existing `DeepSeekExtractionAdapter` (or generic OpenAI-compatible adapter) already uses `NLP_PIPELINE_EXTRACTION_API_BASE_URL=https://api.deepinfra.com/v1/openai` — no code change needed.

Keep the following models unchanged (binary classification — cheaper is correct):
- `NLP_PIPELINE_RELEVANCE_SCORING_API_MODEL_ID` — keep `Meta-Llama-3.1-8B-Instruct`
- `NLP_PIPELINE_UNRESOLVED_RESOLUTION_API_MODEL_ID` — keep `Meta-Llama-3.1-8B-Instruct`
- `RAG_CHAT_DEEPINFRA_CLASSIFICATION_MODEL` — keep `Meta-Llama-3.1-8B-Instruct`

Add inline comment explaining why extraction differs from classification:
```
# Deep extraction uses V4-Flash: structured JSON extraction benefits from a capable model.
# Binary classifiers (relevance, resolution, intent) stay on 3.1-8B: simpler task, 7x cheaper.
NLP_PIPELINE_EXTRACTION_API_MODEL_ID=deepseek-ai/DeepSeek-V4-Flash
```

Also add to `worldview-gitops/values/nlp-pipeline.yaml` under `env:`:
```yaml
- name: NLP_PIPELINE_EXTRACTION_API_MODEL_ID
  value: "deepseek-ai/DeepSeek-V4-Flash"
```

**Acceptance criteria**:
- [ ] `NLP_PIPELINE_EXTRACTION_API_MODEL_ID=deepseek-ai/DeepSeek-V4-Flash` in env and values
- [ ] Classification models unchanged
- [ ] Comment explains the split decision

---

### Validation Gate — Wave C
- [x] `ruff check libs/ml-clients/` passes
- [x] `mypy libs/ml-clients/` passes
- [x] `python -m pytest libs/ml-clients/tests/ -v` — 54 unit tests pass (1 new V4-Flash pricing test)
- [x] `ruff check services/knowledge-graph/` passes
- [x] `mypy services/knowledge-graph/` passes
- [x] `python -m pytest services/knowledge-graph/tests/unit/ -v` — 699 pass (5 new fallback-chain + 2 scheduler-provider tests)
- [x] gitops files updated (nlp-pipeline + knowledge-graph)

### Break Impact — Wave C
| Broken File | Why | Fix Required |
|-------------|-----|-------------|
| `services/knowledge-graph/tests/unit/infrastructure/test_scheduler.py` | `build_workers()` call sites gain new settings fields | Pass `deepinfra_api_key=""` (empty = no DeepInfra) in test fixtures to preserve existing behavior |
| `services/knowledge-graph/tests/unit/infrastructure/llm/test_fallback_chain.py` | Constructor gains `deepinfra_extraction` param | Existing tests unaffected (new param is `None` by default); add new tests for the DeepInfra path |

### Regression Guardrails — Wave C
- **BP-235**: `DeepSeekExtractionAdapter` must use the same `asyncio.Semaphore` concurrency pattern. Do not create an unbounded semaphore.
- **ARCH-003 (R23)**: No session held during `DeepSeekExtractionAdapter.extract()` call. Confirm the extract call happens in Phase 2 outside any DB session (already true in ProvisionalEnrichmentWorker).
- Model ID must match exactly `"deepseek-ai/DeepSeek-V4-Flash"` — verify against DeepInfra docs; confirm with the user's confirmed curl endpoint.

---

## Wave D — Llama-3.2-11B-Vision Audit + GitOps Finalization ✅

**Goal**: Identify the source of 1.58M tokens/day from `meta-llama/Llama-3.2-11B-Vision-Instruct`, replace with V4-Flash if text-only, and finalize all gitops env vars from Waves A–C.

**Status**: **DONE** — 2026-05-02 · 479 rag-chat + 676 nlp-pipeline unit tests pass · ruff + mypy clean

**Depends on**: Wave C (V4-Flash config keys must exist before gitops finalization)
**Estimated effort**: 30–45 min
**Architecture layer**: config + infra

### Pre-read (agent must read before starting)
- `services/rag-chat/src/rag_chat/config.py` — full file
- `services/rag-chat/src/rag_chat/app.py` — full file (look for hardcoded model IDs)
- `services/nlp-pipeline/src/nlp_pipeline/config.py` — lines 60-130
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/article_relevance_scoring_worker.py`
- Any `configs/dev.local.env` or `configs/docker.env` files across services

---

#### T-D-1: Audit and replace Llama-3.2-11B-Vision-Instruct usage

**Type**: impl + config
**depends_on**: T-C-2 (V4-Flash config keys exist)
**blocks**: none
**Target files**: TBD by audit

**What to build**:
The billing shows 1.58M input tokens from `meta-llama/Llama-3.2-11B-Vision-Instruct` — nearly as much as the entire NLP pipeline combined — but it's not in gitops. This must be found and either documented (if vision is genuinely needed) or replaced.

**Audit steps**:
1. `grep -rn "Llama-3.2-11B\|llama-3.2-11b\|11B-Vision\|vision" services/ libs/ --include="*.py" --include="*.env" --include="*.yaml" --exclude-dir=.venv`
2. Also check local dev env files not in git: `configs/dev.local.env`, `configs/docker.env` in each service
3. Check if any service has a hardcoded model string in an adapter or worker that bypasses config
4. Check if `RAG_CHAT_DEEPINFRA_CLASSIFICATION_MODEL` was ever set to this model in a local override

**Resolution**:
- If the usage is for **text-only tasks** (extraction, classification, scoring): replace with `deepseek-ai/DeepSeek-V4-Flash`. Cost goes from $0.245/M → $0.14/M (43% cheaper, better quality).
- If the usage is for **vision tasks** (PDF analysis, image parsing, chart reading): document the requirement in `.claude-context.md` for the relevant service. Do NOT replace with V4-Flash (vision capability is lost). Create a separate `RAG_CHAT_VISION_MODEL` config key.

**Acceptance criteria**:
- [x] Source of Llama-3.2-11B-Vision usage identified and documented in the commit message
- [x] If text-only: replaced with `deepseek-ai/DeepSeek-V4-Flash` in config + gitops
- [x] If vision: config key named `*_VISION_MODEL`, documented in service `.claude-context.md`
- [x] No more untracked model IDs in billing

---

#### T-D-2: Finalize all gitops env vars

**Type**: config
**depends_on**: T-D-1, T-A-1, T-C-2, T-C-3
**blocks**: none
**Target files**:
- `worldview-gitops/env/dev/knowledge-graph.env`
- `worldview-gitops/values/knowledge-graph.yaml`

**What to build**:
Collect all new env vars introduced in Waves A–C and ensure they are present in both the env file and the values.yaml Helm override.

New vars to add to `knowledge-graph.env` + `knowledge-graph.yaml`:
```
KNOWLEDGE_GRAPH_WORKER_PROVISIONAL_ENRICHMENT_INTERVAL_S=600
KNOWLEDGE_GRAPH_WORKER_PROVISIONAL_ENRICHMENT_BATCH_SIZE=50
KNOWLEDGE_GRAPH_WORKER_PROVISIONAL_ENRICHMENT_CONCURRENCY=5
KNOWLEDGE_GRAPH_WORKER_PROVISIONAL_ENRICHMENT_MAX_RETRIES=5
KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY=<same key as NLP_PIPELINE_EXTRACTION_API_KEY>
KNOWLEDGE_GRAPH_DEEPINFRA_EXTRACTION_MODEL_ID=deepseek-ai/DeepSeek-V4-Flash
KNOWLEDGE_GRAPH_DEEPINFRA_EXTRACTION_BASE_URL=https://api.deepinfra.com/v1/openai
KNOWLEDGE_GRAPH_DEEPINFRA_EXTRACTION_CONCURRENCY=5
```

**Important**: `KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY` contains a secret. In gitops it should be referenced via SOPS/K8s secret, not plaintext. Follow the existing pattern for `KNOWLEDGE_GRAPH_STORAGE_ACCESS_KEY` — add a comment `# knowledge-graph-secrets: DEEPINFRA_API_KEY` and ensure it's in the secrets block, not the env block.

**Acceptance criteria**:
- [x] All Wave A–C new env vars present in `knowledge-graph.env` and `knowledge-graph.yaml`
- [x] `DEEPINFRA_API_KEY` handled as a secret (not plaintext in env file)
- [x] `git diff --stat worldview-gitops/` shows only expected files changed

---

### Validation Gate — Wave D
- [x] All gitops files updated, consistent between `env/dev/` and `values/`
- [x] Llama-3.2-11B-Vision source documented or replaced
- [x] `git diff worldview-gitops/` reviewed — no unexpected changes
- [ ] Full end-to-end smoke test: start dev stack, ingest 1 article, verify `provisional_entity_queue` gets populated within 10 min (deferred — requires live stack)

### Break Impact — Wave D
None expected — this wave is gitops config only.

### Regression Guardrails — Wave D
- **Secret hygiene (R13 RULES.md)**: `DEEPINFRA_API_KEY` is a secret. Do not commit it in plaintext to any `.env` file in gitops. Follow the SOPS pattern.

---

## Wave E — Event-Driven Provisional Enrichment (Two-Track Architecture)

**Goal**: Add an immediate-response enrichment path alongside the existing 5-min polling catch-up. When S6's `UnresolvedResolutionWorker` enqueues a provisional entity (Wave B T-B-2), it also emits `entity.provisional.queued.v1` to Kafka. S7 consumes this event immediately and calls the enrichment logic without waiting for the next polling sweep. The polling sweep is retained as the catch-up channel for any events missed by the hot path (startup gaps, consumer lag, etc.).

**Architecture**: Two tracks serve different failure modes:
- **Hot path** (Wave E): S6 emits event → S7 consumer reacts in <100 ms → entity enriched within seconds of mention classification. Zero polling lag.
- **Catch-up sweep** (existing): `ProvisionalEnrichmentWorker` polls every 300 s for `status='pending'` rows with `retry_count < max_retries`. Catches anything the hot path missed (consumer was down, Kafka lag, startup race).
- **Graph integration**: `entity.canonical.created.v1` is already produced by S7 after enrichment and already consumed by S7's `entity_consumer.py` for graph write-back — no changes needed to that path.

**Depends on**: Wave B (T-B-2 adds `_enqueue_for_enrichment()` which this wave extends with a Kafka emit)
**Estimated effort**: 60–90 min
**Architecture layer**: infrastructure (schema + Kafka) + application (consumer + emit)

### Pre-read (agent must read before starting)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/unresolved_resolution_worker.py` — specifically `_enqueue_for_enrichment()`
- `infra/kafka/schemas/entity.canonical.created.v1.avsc` — reference for Avro schema style
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py` — shared enrichment logic to call from consumer
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/` — existing consumer wiring pattern
- `services/knowledge-graph/src/knowledge_graph/config.py`
- `services/nlp-pipeline/src/nlp_pipeline/config.py`
- `worldview-gitops/env/dev/knowledge-graph.env`
- `worldview-gitops/env/dev/nlp-pipeline.env`

---

#### T-E-1: Create Avro schema `entity.provisional.queued.v1`

**Type**: schema
**depends_on**: none
**blocks**: T-E-2, T-E-3
**Target files**:
- `infra/kafka/schemas/entity.provisional.queued.v1.avsc`

**What to build**:
New Avro schema for the event that S6 emits when a provisional entity is inserted into `provisional_entity_queue`. S7 consumes this to trigger immediate enrichment. Partition key is `normalized_surface` — ensures all events for the same entity surface form arrive on the same partition, enabling consumer-side deduplication without cross-partition coordination.

Schema content:
```json
{
  "type": "record",
  "name": "EntityProvisionalQueuedV1",
  "namespace": "com.worldview.intelligence",
  "doc": "Emitted by S6 UnresolvedResolutionWorker when a provisional entity is inserted into provisional_entity_queue. S7 ProvisionalQueuedConsumer reacts immediately to trigger enrichment without waiting for the next polling sweep. Partition key: normalized_surface.",
  "fields": [
    {"name": "event_id", "type": "string", "doc": "UUIDv7 event identifier"},
    {"name": "event_type", "type": "string", "default": "entity.provisional.queued", "doc": "Event type discriminator"},
    {"name": "schema_version", "type": "int", "default": 1},
    {"name": "occurred_at", "type": "string", "doc": "ISO-8601 UTC timestamp of the provisional_entity_queue insert"},
    {"name": "queue_id", "type": "string", "doc": "UUID of the provisional_entity_queue row — used for idempotent processing"},
    {"name": "normalized_surface", "type": "string", "doc": "Lowercased, stripped entity surface form. Also the Kafka partition key."},
    {"name": "mention_class", "type": "string", "doc": "NLP mention class: ORGANIZATION | PERSON | FINANCIAL_INSTRUMENT | LOCATION | COMMODITY | etc."},
    {"name": "source_doc_id", "type": ["null", "string"], "default": null, "doc": "Source article/document UUID that triggered this provisional entity"},
    {"name": "correlation_id", "type": ["null", "string"], "default": null, "doc": "Tracing correlation ID from the originating article pipeline run"}
  ]
}
```

**Downstream test impact**:
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `tests/contract/test_avro_schemas.py` (if it checks schema file count) | New schema file added | Update expected count |

**Acceptance criteria**:
- [ ] File created at `infra/kafka/schemas/entity.provisional.queued.v1.avsc`
- [ ] All field names in snake_case, all fields documented
- [ ] `null` fields use Avro union `["null", "string"]` with `"default": null`
- [ ] Schema validates against Avro specification (no syntax errors)

---

#### T-E-2: Emit `entity.provisional.queued.v1` from S6 after INSERT

**Type**: impl
**depends_on**: T-E-1
**blocks**: T-E-3
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/unresolved_resolution_worker.py`
- `services/nlp-pipeline/src/nlp_pipeline/config.py`
- `worldview-gitops/env/dev/nlp-pipeline.env`
- `worldview-gitops/values/nlp-pipeline.yaml`

**What to build**:
Extend `_enqueue_for_enrichment()` (created in Wave B T-B-2) to emit `entity.provisional.queued.v1` after a successful INSERT into `provisional_entity_queue`. The emit must happen after the DB commit (not before) to avoid emitting an event for a row that doesn't exist yet. Use the existing Kafka producer that is already wired into `UnresolvedResolutionWorker`.

**Logic**:
```python
async def _enqueue_for_enrichment(self, mention: EntityMentionModel, queue_id: str) -> None:
    """Insert into provisional_entity_queue and emit Kafka event for immediate S7 enrichment."""
    # T-B-2: DB insert (already implemented in Wave B)
    inserted = await self._do_queue_insert(mention, queue_id)
    if not inserted:
        return  # ON CONFLICT DO NOTHING — row already exists, skip emit

    # T-E-2: Emit hot-path event after commit (emit only if insert succeeded)
    if self._kafka_producer is not None:
        event = {
            "event_id": str(uuid7()),
            "event_type": "entity.provisional.queued",
            "schema_version": 1,
            "occurred_at": utc_now_iso(),
            "queue_id": queue_id,
            "normalized_surface": mention.normalized_mention_text or mention.mention_text.lower().strip(),
            "mention_class": str(mention.mention_class),
            "source_doc_id": str(mention.doc_id) if mention.doc_id else None,
            "correlation_id": None,
        }
        await self._kafka_producer.produce(
            topic=self._settings.kafka_topic_provisional_queued,
            key=event["normalized_surface"],  # partition key
            value=event,
        )
```

Config addition to `nlp_pipeline/config.py`:
```python
kafka_topic_provisional_queued: str = "entity.provisional.queued.v1"  # NLP_PIPELINE_KAFKA_TOPIC_PROVISIONAL_QUEUED
```

Add to `worldview-gitops/env/dev/nlp-pipeline.env`:
```
NLP_PIPELINE_KAFKA_TOPIC_PROVISIONAL_QUEUED=entity.provisional.queued.v1
```

Add to `worldview-gitops/values/nlp-pipeline.yaml` under `env:`:
```yaml
- name: NLP_PIPELINE_KAFKA_TOPIC_PROVISIONAL_QUEUED
  value: "entity.provisional.queued.v1"
```

**Important**: If `UnresolvedResolutionWorker` does not currently hold a Kafka producer reference, check how `UnresolvedResolutionWorker` is instantiated in the scheduler and whether a producer can be injected. If the producer is not available, emit via a side-channel helper that shares the existing producer from `ArticleConsumer` (read scheduler.py `build_workers()` to understand the constructor args).

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_enqueue_emits_kafka_event_on_insert` | When INSERT succeeds (returns True), Kafka producer `.produce()` is called with correct topic and key=normalized_surface | unit |
| `test_enqueue_skips_emit_on_conflict` | When INSERT returns False (ON CONFLICT), producer NOT called | unit |
| `test_enqueue_emit_skipped_without_producer` | When `kafka_producer=None`, no error, DB insert still happens | unit |

**Acceptance criteria**:
- [ ] `entity.provisional.queued.v1` emitted only when INSERT actually creates a new row
- [ ] Kafka partition key = `normalized_surface`
- [ ] Config key `kafka_topic_provisional_queued` added
- [ ] Gitops env + values updated
- [ ] Tests pass

---

#### T-E-3: New S7 consumer `provisional_queued_consumer.py`

**Type**: impl
**depends_on**: T-E-1, T-E-2
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/provisional_queued_consumer.py` (new file)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/__init__.py` (register)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py` (wire consumer)
- `services/knowledge-graph/src/knowledge_graph/config.py`
- `worldview-gitops/env/dev/knowledge-graph.env`
- `worldview-gitops/values/knowledge-graph.yaml`

**What to build**:
A new Kafka consumer in S7 that subscribes to `entity.provisional.queued.v1` and calls the same enrichment logic as `ProvisionalEnrichmentWorker._enrich_one()` — but immediately, without waiting for the polling sweep. The consumer must be idempotent: before calling enrichment, check `provisional_entity_queue` status. If `status != 'pending'`, log and skip (already processing or resolved). The idempotency check + status transition to `'processing'` must be atomic (SELECT FOR UPDATE or CAS on `status` column).

**Consumer class structure**:
```python
class ProvisionalQueuedConsumer:
    """Kafka consumer for entity.provisional.queued.v1.

    Hot path: reacts immediately when S6 inserts a provisional entity,
    reducing median enrichment latency from ~2.5 min (polling) to <10 s.
    The polling sweep (ProvisionalEnrichmentWorker) is the catch-up channel.
    """

    TOPIC = "entity.provisional.queued.v1"
    CONSUMER_GROUP = "kg-provisional-queued-group"

    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        llm_client: FallbackChainClient,
        settings: Settings,
    ) -> None: ...

    async def consume_loop(self) -> None:
        """Main consumer loop — subscribes and processes messages indefinitely."""
        ...

    async def _handle_message(self, msg: KafkaMessage) -> None:
        """Process one event: idempotency check → enrich → mark resolved/failed."""
        queue_id = msg.value["queue_id"]
        normalized_surface = msg.value["normalized_surface"]
        mention_class = msg.value["mention_class"]

        async with self._sf() as session:
            row = await session.execute(
                select(ProvisionalEntityQueue)
                .where(ProvisionalEntityQueue.queue_id == queue_id)
                .with_for_update(skip_locked=True)
            )
            queue_row = row.scalar_one_or_none()
            if queue_row is None or queue_row.status != "pending":
                logger.debug("provisional_queued_skip", queue_id=queue_id, reason="not_pending")
                return
            queue_row.status = "processing"
            await session.commit()

        # Call shared enrichment logic outside any session (ARCH-003)
        await self._enrich_queue_row(queue_id, normalized_surface, mention_class)
```

The enrichment logic (`_enrich_queue_row`) should call the same LLM extraction + canonical entity creation path as `ProvisionalEnrichmentWorker._enrich_one()`. Refactor the shared logic into a standalone `enrich_provisional_entity(queue_id, normalized_surface, mention_class, session_factory, llm_client)` function in a shared module (e.g., `infrastructure/workers/provisional_enrichment_core.py`) and call it from both workers.

Config additions:
```python
kafka_topic_provisional_queued: str = "entity.provisional.queued.v1"  # KNOWLEDGE_GRAPH_KAFKA_TOPIC_PROVISIONAL_QUEUED
kafka_consumer_group_provisional_queued: str = "kg-provisional-queued-group"  # KNOWLEDGE_GRAPH_KAFKA_CONSUMER_GROUP_PROVISIONAL_QUEUED
```

Wire in `scheduler.py` (or wherever other consumers are started) — look at `entity_consumer.py` for the startup pattern. The consumer should run as a long-lived background task launched at startup.

Gitops additions to `knowledge-graph.env`:
```
KNOWLEDGE_GRAPH_KAFKA_TOPIC_PROVISIONAL_QUEUED=entity.provisional.queued.v1
KNOWLEDGE_GRAPH_KAFKA_CONSUMER_GROUP_PROVISIONAL_QUEUED=kg-provisional-queued-group
```

Same additions to `values/knowledge-graph.yaml`.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_handle_message_calls_enrich_for_pending_row` | When queue row is `pending`, status set to `processing` and enrichment called | unit |
| `test_handle_message_skips_non_pending_row` | When row is `processing` or `resolved`, enrichment NOT called | unit |
| `test_handle_message_skips_missing_row` | When `queue_id` not found in DB, enrichment NOT called, no exception | unit |
| `test_handle_message_idempotent_concurrent` | Two concurrent calls with same queue_id: exactly one reaches enrichment (skip_locked ensures only one wins lock) | unit |

**Acceptance criteria**:
- [ ] Consumer subscribes to `entity.provisional.queued.v1`
- [ ] Idempotency check via SELECT FOR UPDATE SKIP LOCKED before enrichment
- [ ] Shared enrichment logic extracted so both worker and consumer use the same function
- [ ] Consumer started at S7 startup alongside existing consumers
- [ ] Config keys added; gitops env + values updated
- [ ] Tests pass; ARCH-003 respected (no DB session held during LLM call)

---

### Validation Gate — Wave E
- [ ] `ruff check infra/kafka/schemas/ services/nlp-pipeline/ services/knowledge-graph/` passes
- [ ] `mypy services/nlp-pipeline/ services/knowledge-graph/` passes
- [ ] `python -m pytest services/nlp-pipeline/tests/unit/infrastructure/workers/test_unresolved_resolution_worker.py -v` — 3 new emit tests pass
- [ ] `python -m pytest services/knowledge-graph/tests/unit/infrastructure/messaging/test_provisional_queued_consumer.py -v` — 4 new consumer tests pass
- [ ] No regressions in existing S6 + S7 test suites
- [ ] Manual smoke test: trigger a mention through S6, verify `entity.provisional.queued.v1` arrives in S7 consumer within 2 s

### Break Impact — Wave E
| Broken File | Why | Fix Required |
|-------------|-----|-------------|
| `tests/contract/test_avro_schemas.py` | New schema file added | Update expected schema count |
| `services/knowledge-graph/tests/unit/infrastructure/workers/test_provisional_enrichment.py` | Core enrichment logic extracted to shared module | Update import path from `provisional_enrichment.py` to `provisional_enrichment_core.py` |

### Regression Guardrails — Wave E
- **ARCH-003 (R23)**: Consumer must release the DB session before calling the LLM. The status transition to `'processing'` commits and releases the session; enrichment runs in a separate async call. Match the pattern in `provisional_enrichment.py`.
- **BP-007**: No schema changes. `provisional_entity_queue` table already exists. Only INSERT and UPDATE operations.
- **BP-235**: Consumer concurrency must be bounded. Use `asyncio.Semaphore` with the same `worker_provisional_enrichment_concurrency` setting to cap simultaneous LLM calls from the consumer, matching the polling worker's cap.
- **Idempotency via SKIP LOCKED**: Two consumer instances (horizontal scale) compete for the same row. `SKIP LOCKED` ensures exactly one processes each row without blocking the other. Do not use a plain SELECT + separate UPDATE — race condition window exists between the two statements.

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `DeepSeek-V4-Flash` structured JSON output format differs from `Meta-Llama-3.1-8B` | MEDIUM | The existing `_extract_json_object()` tolerant parser in nlp-pipeline already handles fence wrapping and malformed JSON. Test with a batch before full rollout. |
| Phase 1 cascade in UnresolvedResolutionWorker introduces N+1 queries | LOW | EntityResolutionBlock uses indexed lookups (alias, ticker, ANN). Single mention per call. No scan risk. |
| asyncio.gather in ProvisionalEnrichmentWorker creates session contention | LOW | ARCH-003 (no session held during I/O) already enforced. Phase 2 runs entirely outside any session. |
| Llama-3.2-11B-Vision source is a required capability (vision) | MEDIUM | If found, isolate into dedicated config key rather than replacing. Do not assume text-only. |

## Critical Path

`Wave A` (fixes throughput) → `Wave B` (fixes entity creation) → everything works end-to-end.
`Wave C` (model migration) is independent and can ship first if desired.
`Wave D` must come last (depends on C for config keys, and D-1 needs A–C complete to know what to audit).

---

## Compounding Updates

After implementing this plan, update:
- `docs/BUG_PATTERNS.md`: Add **BP-310 "Classification without consequence"** — worker classifies an item but writes no downstream effect. Review pattern: ask "what DB write does this classification trigger?"
- `services/knowledge-graph/.claude-context.md`: Document the new 3-slot FallbackChainClient order (DeepInfra → Ollama → Gemini) and the new config keys.
- `docs/STANDARDS.md`: Add note under worker patterns — periodic enrichment workers must have a `max_retries` cap with a terminal failure status. Unbounded retry loops are a bug class.
