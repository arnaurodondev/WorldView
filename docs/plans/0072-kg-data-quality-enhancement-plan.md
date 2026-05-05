# PLAN-0072: Knowledge Graph Data Quality Enhancement

**Status:** completed
**Created:** 2026-05-05
**Updated:** 2026-05-05
**Owner:** Knowledge Graph team
**PRD:** Investigation reports from 2026-05-05 sessions (no formal PRD — fixes derive from confirmed root causes)
**Waves:** 3 implementation waves (revised 2026-05-05: Wave 4 evidence promotion deferred to PRD-0074; hub node pollution deferred to PRD-0073/0074)

> **Migration ordering constraint (R-005):** PLAN-0072 migrations will occupy revision IDs **0020–0021** (two migrations, after removing data-repair steps not needed on a fresh-start cluster). IDs 0022–0023 are intentionally unused. PLAN-0073 uses **0024–0027**. Do not start PLAN-0073 Wave A until PLAN-0072 is fully applied to `intelligence_db`.

---

## Context & Motivation

Two /investigate sessions (2026-05-05) identified a cluster of correctness and data-quality bugs in the Knowledge Graph (S7) that fall below the threshold for a full PRD but above the threshold of ad-hoc fixes. This plan covers all **fixable** issues. Larger structural enhancements (multi-hop traversal, isolated-node enrichment, intelligence-layer edge scoring) are deferred to a separate PRD session.

### Issues covered by this plan

| ID | Issue | Severity | Root Cause |
|----|-------|----------|------------|
| KQ-01 | Noise entities ("he", "analysts", "Constant Currency", "Simply Wall St") leak into KG | HIGH | No pre-filter at provisional queue ingestion; UnresolvedResolutionWorker LLM prompt accepts too wide a scope |
| KQ-02 | Relation type case mismatch (seeded UPPERCASE vs LLM lowercase) breaks exact canonicalization | HIGH | `canonicalize_relation_type` Step 1 exact match is case-sensitive; LLM emits lowercase; seed has both |
| KQ-03 | Evidence text stored in DB but never returned in graph API response | MEDIUM | `GraphNeighborhoodResponse` / `RelationResponse` schema missing `evidence_snippets` field; no JOIN added |
| KQ-04 | SummaryWorker (Worker 13C) generates 0 summaries despite 3,582 stale relations | HIGH | `skipped_null_evidence_text` path hit silently; `evidence_text` column NULL on relation_evidence_raw rows generated before BP-346 fix propagated; also missing LLM model registration for `kg-summary-v1` |
| ~~KQ-05~~ | ~~Hub node pollution — generic nodes ("US", "analysts") acquire 60-72 relations~~ | ~~MEDIUM~~ | **Deferred to PRD-0073/0074** — entity quality scoring requires structured enrichment data that PRD-0073 will introduce. |

### Issues deferred to /prd session

- Isolated node enrichment (68% of entities have 0 relations) → PRD-0073
- Intelligence layer: edge opportunity scoring, contradiction visualization, temporal graph view → PRD-0074

### Amended scope (2026-05-05)

Three items added from Finding 4 investigation:
- ~~**4a** (T-72-1-04): Retroactive noise entity cleanup migration — delete isolated noise entities already in DB~~ — **removed**: cluster is always relaunched from scratch; no existing data to repair
- ~~**4b**: Added to T-72-1-03 — mark `confidence_stale=true` on all relations after type normalization~~ — **removed**: T-72-1-03 removed; no UPPERCASE relations exist on a fresh-start cluster
- **4c** (T-72-1-05): UnresolvedResolutionWorker prompt hardening — reduce noise leakage from S6 side

**4d (evidence promotion pipeline) has been deferred to PRD-0074.** The `relation_evidence_raw → relation_evidence` promotion requires a new unique index on `relation_evidence (relation_id, doc_id, evidence_date)` — this index is better designed alongside PRD-0074's evidence-analytics and temporal-decay work, which will define the downstream query patterns the index must serve. No current use case reads from `relation_evidence` directly; the SummaryWorker (Wave 2 fix) already reads from `relation_evidence_raw`.

Multi-hop traversal strategy changed from pure relational BFS to **hybrid**:
- `depth=1` → existing relational `GetEntityGraphUseCase` (full evidence/summary JOIN)
- `depth>1` → delegate to existing `GetCypherNeighborhoodUseCase` (AGE, already implemented) + map response to `GraphNeighborhoodResponse`

---

## Codebase State Verification

| Component | Current State | Required Change | Delta |
|-----------|--------------|-----------------|-------|
| `provisional_enrichment.py` | Queries `status='pending'` rows, no text filter | Add two-layer noise filter: Layer 1 static blocklist, Layer 2 cheap LLM classifier (`meta-llama/8B`), Layer 3 full extraction | Code change |
| `provisional_enrichment_core.py` | No entity_type validation after LLM extraction | Add post-extraction `entity_type` normalization + validation against canonical set; default unrecognized values to `'other'` with warning log | Code change |
| `canonicalization.py` | Step 1 exact match is case-sensitive | Normalize `raw_type.lower().strip()` before exact lookup | Code change |
| `relation_type_registry` table | All seeds are lowercase (migration 0001 + 0004 confirmed) — registry is already correct | No change — T-72-1-02 code fix prevents future case mismatches; no data-repair migration needed on a fresh-start cluster | None |
| `schemas.py` (`RelationResponse`) | No `evidence_snippets` field | Add `evidence_snippets: list[str]` (max 3) | Schema change |
| `graph_query.py` | Uses `relation_repo.list_for_entity()` which has no evidence JOIN | Add evidence JOIN or separate batch fetch | Code change |
| `relation.py` (repo) | `list_for_entity` returns 8 columns, no evidence text | Add optional evidence JOIN | Code change |
| `summary.py` | `skipped_null_evidence_text` branches on `evidence_text` NULL correctly, but logs silently | Add explicit diagnostic log + separate fix for NULL evidence backfill | Code change |
| `summary.py` | Defines `_SUMMARY_MODEL_ID = "kg-summary-v1"` — constant is **dead code**, never passed to `FallbackChainClient.extract()` which has no `model_id` parameter | Remove dead constant; add diagnostic log of raw LLM response before parse | Code |

---

## Wave 1: Noise Entity Filtering + Relation Type Normalization ✅

**Goal:** Stop noise entities from entering the KG and fix the case mismatch that causes ~30% of LLM-extracted relations to emit `canonical_type=None`.
**Depends on:** none
**Estimated effort:** 60-90 min
**Status:** **DONE** — 2026-05-05 · 818 KG unit + 710 nlp-pipeline unit + 100 arch tests pass · ruff + mypy clean
**Architecture layer:** infrastructure + application

### Tasks

#### T-72-1-01: Two-layer noise filtering in ProvisionalEnrichmentWorker

**Type:** impl
**depends_on:** none
**blocks:** none
**Target files:**
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py`
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_provisional_enrichment.py` (or add new file)

**PRD reference:** Investigation report 2026-05-05 §KQ-01

**What to build:**
Add a two-layer pre-filter that runs before the expensive DeepSeek V4 Flash profile extraction. The three processing stages are:

- **Layer 1 (O(1) — free):** Static `_NOISE_BLOCKLIST` frozenset. Obvious noise eliminated with zero network cost.
- **Layer 2 (cheap LLM):** `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` via DeepInfra. Binary classification with a tightly constrained prompt. Only mentions that pass Layer 1 reach here.
- **Layer 3 (expensive LLM):** Existing DeepSeek V4 Flash full-profile extraction via `FallbackChainClient`. Only reached when Layer 2 confirms the mention is a real entity.

The `UnresolvedResolutionWorker` (S6) already has 2-phase noise classification before the queue INSERT — these layers are a complementary S7 guard at consumption time, not a replacement.

**Logic & Behavior:**

**Layer 1 — static blocklist:**
```python
_NOISE_BLOCKLIST: frozenset[str] = frozenset({
    # Pronouns / generic references
    "he", "she", "they", "it", "we", "us", "his", "her", "their",
    "him", "them", "who", "what",
    # Generic finance jargon that produce useless nodes
    "constant currency", "organic growth", "analysts", "management",
    "investors", "shareholders", "executives", "regulators",
    "the company", "company", "the firm", "firm", "business",
    # Fake entities from publication names used as subjects
    "simply wall st", "seeking alpha", "the motley fool", "bloomberg",
    "reuters", "cnbc", "marketwatch", "barron's", "wsj",
    # Noise mentions of generic geographic / institutional terms
    "street", "market", "sector", "industry", "index",
})
```
For each row, check `mention_text.lower().strip() in _NOISE_BLOCKLIST`. If matched → collect into `layer1_noise_ids`. No LLM call made.

**Layer 2 — cheap LLM classifier:**
For rows not caught by Layer 1, call `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` (DeepInfra) with a tight binary prompt:
```
Is "{mention_text}" a specific named financial entity (company, person, financial instrument,
index, currency, or commodity)?
Respond ONLY with JSON: {"is_entity": true/false, "confidence": 0.0-1.0}
Do NOT classify generic roles, concepts, or financial jargon as entities.
```
Decision rules:
- `is_entity=false` OR `confidence < 0.7` → collect into `layer2_noise_ids`
- `is_entity=true` AND `confidence >= 0.7` → proceed to Layer 3
- Layer 2 call fails (timeout/error) → **fail-open**: proceed to Layer 3 and log a warning (never silently drop a row)

**Batch noise UPDATE:**
After both filter layers, execute a single batch UPDATE:
```sql
UPDATE provisional_entity_queue
SET status = 'noise', resolved_at = now()
WHERE queue_id = ANY(:ids) AND status = 'pending'
```
Where `:ids` is `layer1_noise_ids + layer2_noise_ids`. Then remove all noise rows from `pending_rows` before Layer 3.

**Layer 3 — full extraction:**
Existing `FallbackChainClient` profile extraction. Unchanged.

**New terminal status `'noise'`:**
The `provisional_entity_queue.status` column is bare `VARCHAR(20) NOT NULL DEFAULT 'pending'` with **no CHECK constraint today** (migration 0001). Add the constraint in a new migration (0020):
```sql
ALTER TABLE provisional_entity_queue
    ADD CONSTRAINT ck_provisional_status
    CHECK (status IN ('pending', 'processing', 'resolved', 'failed', 'noise'));
```

**Tests to write:**
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_layer1_blocklist_marks_noise_no_llm_calls` | `mention_text="he"` → status `'noise'`, Layer 2 LLM never called | unit |
| `test_layer2_low_confidence_marks_noise` | Layer 1 passes, Layer 2 returns `confidence=0.5` → `'noise'`, Layer 3 never called | unit |
| `test_layer2_not_entity_marks_noise` | Layer 1 passes, Layer 2 returns `is_entity=false` → `'noise'`, Layer 3 never called | unit |
| `test_layer2_failure_falls_through_to_layer3` | Layer 2 call raises exception → Layer 3 called (fail-open), warning logged | unit |
| `test_confirmed_entity_reaches_layer3` | `mention_text="Apple Inc."`, Layer 2 → `{is_entity: true, confidence: 0.9}` → Layer 3 called | unit |
| `test_blocklist_case_insensitive` | `mention_text="ANALYSTS"` → Layer 1 filtered | unit |

**Acceptance criteria:**
- [ ] Layer 1 static blocklist applied before any LLM call — O(1) frozenset lookup
- [ ] Layer 2 `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` called for non-blocklist mentions
- [ ] `confidence < 0.7` OR `is_entity=false` → status `'noise'`
- [ ] Layer 2 failure → fail-open (proceed to Layer 3), warning logged — no silent drops
- [ ] Layer 3 (full extraction) only reached when Layer 2 confirms entity
- [ ] Single batch UPDATE for all noise rows from both layers combined
- [ ] Prometheus counters: `s7_provisional_noise_filtered_total` (Layer 1) and `s7_provisional_noise_llm_filtered_total` (Layer 2)
- [ ] Unit tests pass

---

#### T-72-1-02: Relation type case normalization in canonicalization pipeline

**Type:** impl
**depends_on:** none
**blocks:** none
**Target files:**
- `services/knowledge-graph/src/knowledge_graph/application/blocks/canonicalization.py`
- `services/knowledge-graph/tests/unit/application/blocks/test_canonicalization.py`

**PRD reference:** Investigation report 2026-05-05 §KQ-02

**What to build:**
The `canonicalize_relation_type` function's Step 1 exact-match lookup is case-sensitive. LLM outputs like `"competes_with"` fail to match registry entries stored as `"competes_with"` — but AGE labels use `"COMPETES_WITH"` and the registry was seeded with mixed casing across migrations. Fix: normalize `raw_type` to lowercase before the exact lookup, and ensure the registry comparison is also lowercase. This is a 1-line change but requires a corresponding test.

**Logic & Behavior:**
1. In `canonicalize_relation_type()`, before Step 1:
   ```python
   normalized_raw_type = raw_type.lower().strip().replace(" ", "_")
   ```
2. Pass `normalized_raw_type` to `registry_repo.find_by_canonical_type(normalized_raw_type)` instead of `raw_type`.
3. The registry's `canonical_type` seeds (migrations 0001 and 0004) are **already lowercase** — no registry normalization is needed. The `relations` table data-repair migration originally planned as T-72-1-03 has been removed because the cluster is always relaunched from scratch; no UPPERCASE `canonical_type` rows will exist in `relations` when this code change is deployed.
4. The ANN embedding step (Step 2) already works on the text embedding so does not need this fix.

**Tests to write:**
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_exact_match_case_insensitive` | `raw_type="COMPETES_WITH"` resolves to `"competes_with"` via exact match | unit |
| `test_uppercase_llm_output_canonicalized` | `raw_type="HAS_EXECUTIVE"` resolves via normalized lowercase | unit |
| `test_unknown_type_still_proposed` | Truly unknown type still falls through to Step 3 | unit |

**Acceptance criteria:**
- [ ] `raw_type.lower().strip()` applied before Step 1 exact lookup
- [ ] Existing unit tests for `canonicalize_relation_type` still pass
- [ ] New tests for case variants pass

---

---

#### T-72-1-05: UnresolvedResolutionWorker prompt hardening

**Type:** impl
**depends_on:** none
**blocks:** none
**Target files:**
- Find the worker in S6 (nlp-pipeline) that enqueues entities to `provisional_entity_queue` — search for `UnresolvedResolutionWorker` or `provisional_entity_queue` INSERT in `services/nlp-pipeline/src/`
- Corresponding prompt template (likely in `libs/prompts/` or `services/nlp-pipeline/src/`)
- Unit tests for the classification step

**PRD reference:** Investigation report 2026-05-05 §Finding-4c / §KQ-01

**What to build:**
The UnresolvedResolutionWorker already has a 2-phase noise classification:
- Phase 1: non-entity-creating mention classes (LOCATION, COMMODITY, etc.) → `noise` immediately, no LLM call
- Phase 2: LLM classification using a prompt that outputs `{"is_named_entity": true/false, ...}`

The Phase 2 classification prompt is **too permissive** — generic terms like "analysts", "management", "constant currency" pass through as `is_named_entity=true` because the prompt lacks explicit negative examples. The `provisional_entity_queue` INSERT occurs when `is_named_entity=true`. Harden the existing Phase 2 prompt with more specific negative examples and tighten the confidence threshold.

**Logic & Behavior:**
1. Locate the classification prompt. Add explicit negative examples and a stricter classification rubric:
   ```
   A REAL NAMED ENTITY is:
   - A specific company, person, product, or financial instrument with a unique identity
   - Examples: "Apple Inc.", "Elon Musk", "NASDAQ", "USD", "S&P 500"

   NOT a real named entity (classify as NOISE):
   - Pronouns ("he", "they", "it", "we")
   - Generic roles or groups ("analysts", "management", "investors", "executives")
   - Financial jargon without a referent ("constant currency", "organic growth")
   - Media outlet names when used as attribution ("Bloomberg", "Reuters", "Seeking Alpha")
   - Generic economic concepts ("market", "sector", "industry", "index")

   Output JSON: {"is_named_entity": true/false, "confidence": 0.0-1.0, "entity_class": "..."}
   ```
2. Add `confidence` threshold: if `confidence < 0.7` → treat as noise.
3. Add unit test asserting that "analysts", "constant currency", "he" → `is_named_entity=false`.

**Acceptance criteria:**
- [ ] Prompt updated with negative examples
- [ ] `confidence < 0.7` → not enqueued to provisional_entity_queue
- [ ] Unit tests for noise classification pass

---

### Wave 1 Pre-read (agent must read before starting)

- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py`
- `services/knowledge-graph/src/knowledge_graph/application/blocks/canonicalization.py`
- `services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py` (relation_type_registry seed + status column definition)
- `services/knowledge-graph/tests/unit/application/blocks/test_canonicalization.py` (if exists)
- Find and read `UnresolvedResolutionWorker` in `services/nlp-pipeline/src/` (for T-72-1-05)

### Wave 1 Validation Gate

- [x] `ruff check` passes on changed files
- [x] `mypy` passes on changed packages
- [x] `python -m pytest tests/ -m "unit" -v` passes in knowledge-graph service (818 pass)
- [x] `python -m pytest tests/ -m "unit" -v` passes in nlp-pipeline service (710 pass)
- [x] Alembic migration 0020 created (`add_noise_status_to_provisional_queue`)
- [x] New unit tests: 9 (6 noise filter + 3 case normalization + 3 confidence threshold = 12 total)

### Wave 1 Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `provisional_entity_queue` CHECK constraint | New `'noise'` status value | Covered by T-72-1-01 migration (0020) |
| Any test asserting exact `status` values on `provisional_entity_queue` | `'noise'` is a new valid terminal state | Add `'noise'` to status assertion sets if needed |

### Wave 1 Regression Guardrails

- **BP-384** (entity dedup): Noise blocklist check must run BEFORE the dedup alias check — noise rows should not even reach `persist_enrichment`. Verify ordering.
- **BP-007** (missing server_default): If the status column CHECK constraint is altered, ensure no `ALTER COLUMN` with NOT NULL on a populated table without a server_default.
- **BP-019** (Alembic migration): Always verify `alembic upgrade head` on the test DB before committing the migration.

---

## Wave 2: Evidence Text in Graph API + SummaryWorker Diagnosis ✅

**Goal:** Expose evidence text snippets in the graph API response (so frontend can show "why does this edge exist?") and fix the SummaryWorker silent skip issue.
**Depends on:** Wave 1 (for normalized relation types)
**Estimated effort:** 60-90 min
**Status:** **DONE** — 2026-05-05 · 830 KG unit tests pass · ruff + mypy clean
**Architecture layer:** infrastructure + API

### Tasks

#### T-72-2-01: Add evidence_snippets to graph API response

**Type:** impl
**depends_on:** none
**blocks:** none
**Target files:**
- `services/knowledge-graph/src/knowledge_graph/api/schemas.py`
- `services/knowledge-graph/src/knowledge_graph/api/routes.py`
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/graph_query.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation.py`
- `services/knowledge-graph/tests/unit/api/test_graph_routes.py` (or nearest test file)

**PRD reference:** Investigation report 2026-05-05 §KQ-03

**What to build:**
Extend `RelationResponse` with `evidence_snippets: list[str]` and wire it through the stack with a configurable per-call limit. Evidence snippets are the top-N `evidence_text` values from `relation_evidence_raw` for each relation, ordered by `extraction_confidence DESC NULLS LAST, evidence_date DESC NULLS LAST`.

**Architecture constraint:** The use case (`GetEntityGraphUseCase`) must not import from infrastructure — it receives data through the repository port.

**Logic & Behavior:**
1. **Schema change** (`schemas.py`): Add to `RelationResponse`:
   ```python
   evidence_snippets: list[str] = Field(
       default_factory=list,
       description="Evidence text snippets supporting this relation.",
   )
   ```

2. **Route parameter** (`routes.py`): Add a query parameter to `get_entity_graph`:
   ```python
   evidence_snippets_limit: int = Query(default=3, ge=1, le=10)
   ```
   Thread this value through to the use case and repository.

3. **Repository method** (`relation_evidence.py`): Add:
   ```python
   async def get_evidence_snippets_batch(
       self,
       relation_ids: list[UUID],
       limit_per_relation: int = 3,
   ) -> dict[UUID, list[str]]:
   ```
   **Implementation — Option B1 (CTE with `ROW_NUMBER()`):**
   ```sql
   WITH ranked AS (
       SELECT relation_id,
              COALESCE(evidence_text, canonicalized_evidence_text) AS snip,
              ROW_NUMBER() OVER (
                  PARTITION BY relation_id
                  ORDER BY extraction_confidence DESC NULLS LAST,
                           evidence_date DESC NULLS LAST
              ) AS rn
       FROM relation_evidence_raw
       WHERE relation_id = ANY(:relation_ids)
         AND (evidence_text IS NOT NULL OR canonicalized_evidence_text IS NOT NULL)
   )
   SELECT relation_id, snip FROM ranked WHERE rn <= :limit
   ```
   Single query for all relations. Group by `relation_id` in Python, return `dict[UUID, list[str]]`. Merge into `relation_rows` in `GetEntityGraphUseCase.execute()`.

4. **Use case change** (`graph_query.py`): Extend the execute signature:
   ```python
   async def execute(
       self,
       entity_repo: CanonicalEntityRepositoryPort,
       relation_repo: RelationRepositoryPort,
       evidence_repo: RelationEvidenceRepositoryPort,  # NEW
       evidence_limit: int = 3,                        # NEW
       ...
   ) -> ...:
   ```

5. **Router change** (`routes.py`): Add `evidence_repo` to `EntityGraphReposDep` and thread `evidence_snippets_limit` through to `use_case.execute(...)`.

6. **Schema validation**: `evidence_snippets` must always be a list (never null) — use `default_factory=list`.

**Architecture decision — evidence retrieval at Bloomberg scale:**

Three options were evaluated for long-term scale (the platform targets Bloomberg-grade data density with thousands of entities and tens of thousands of relations per graph call):

| Option | Approach | Hot-path cost | Scaling characteristic |
|--------|----------|--------------|----------------------|
| **A — LATERAL JOIN** | `LEFT JOIN LATERAL (SELECT ... LIMIT :n) ON true` in the main relation query | One subquery scan per relation row | Degrades linearly with relation count — 200 relations = 200 LATERAL scans |
| **B1 — Batch CTE** (implemented here) | Single `ROW_NUMBER() OVER (PARTITION BY relation_id)` CTE over `ANY(:ids)` | One query for all relations | O(evidence_rows_for_batch) — scales with evidence volume, not relation count |
| **C — Denormalized JSONB** | `top_evidence_snippets JSONB` column on `relations`, maintained by ConfidenceWorker 13A | Zero additional queries — pure column read | Constant per graph call regardless of evidence volume; evidence ranking done during low-frequency confidence recalculation |

**Option C is the correct Bloomberg-grade long-term architecture**: graph reads (high-frequency) become pure column reads; the ranking work is amortized into ConfidenceWorker (13A) which already processes all relations on its own schedule. However, it requires a schema migration and ConfidenceWorker coordination that belongs in PRD-0074's evidence-lifecycle design.

**Decision for this plan:** Implement **Option B1** now. Add a `# TODO(PRD-0074): upgrade to denormalized top_evidence_snippets JSONB on relations` comment in the repository method as the documented upgrade path.

**Tests to write:**
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_graph_response_includes_evidence_snippets` | Relations with evidence return `evidence_snippets` list | unit |
| `test_graph_response_empty_snippets_when_no_evidence` | Relations without evidence return `[]` not None | unit |
| `test_evidence_snippets_respects_limit_param` | `evidence_snippets_limit=5` → up to 5 returned per relation | unit |
| `test_evidence_snippets_default_limit_is_3` | No param → defaults to 3 snippets per relation | unit |
| `test_evidence_snippets_limit_max_10` | `evidence_snippets_limit=11` → 422 | unit |

**Acceptance criteria:**
- [x] `GET /api/v1/entities/{entity_id}/graph` response includes `evidence_snippets: [...]` on each relation
- [x] `evidence_snippets_limit` query param accepted (default=3, min=1, max=10)
- [x] `evidence_snippets` is always a list (never null)
- [x] No N+1 query — single batch CTE fetch for all relations
- [x] Port interface (`RelationEvidenceRepositoryPort`) updated or created with `get_evidence_snippets_batch`
- [x] `# TODO(PRD-0074)` upgrade comment present in repository method

---

#### T-72-2-02: Diagnose and fix SummaryWorker evidence_text NULL path

**Type:** impl
**depends_on:** none
**blocks:** none
**Target files:**
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/summary.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_evidence.py`
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_summary.py` (or add)

**PRD reference:** Investigation report 2026-05-05 §KQ-04

**What to build:**
The SummaryWorker generates 0 summaries because most `relation_evidence_raw` rows have `evidence_text = NULL` (they were inserted before BP-346 fixed `evidence_text` propagation from the NLP chain). The worker already has a `skipped_null_evidence_text` counter but it only warns — it does not expose the LLM model registration failure either. Fix two issues:

**Issue A — NULL evidence_text skip:** The worker falls back to `canonicalized_evidence_text` in its filter but may still skip rows if both columns are NULL. Add a backfill path: if `evidence_text` IS NULL but `canonicalized_evidence_text` IS NOT NULL, treat `canonicalized_evidence_text` as the evidence text for summary generation. This is already partially coded (`e.get("evidence_text", "") or e.get("canonicalized_evidence_text", "")`) but only in the list comprehension filter — ensure the `if e.get(...)` guard accepts either field.

**Issue B — LLM call visibility:** `FallbackChainClient.extract()` takes `(inp: ExtractionInput)` with **no `model_id` parameter** — there is no model routing registry in the client. The `_SUMMARY_MODEL_ID = "kg-summary-v1"` constant in `summary.py` is defined but never passed to the client and has no effect. The chain tries DeepInfra → Ollama → Gemini regardless; it returns `None` only when all three are exhausted. The real risk is that the `ExtractionInput` prompt is constructed incorrectly or too short, causing all providers to return empty/invalid JSON that the worker discards. Fix: add a diagnostic log of the raw LLM response string **before** any parse step so the next debugging session has visibility:
```python
logger.info(
    "summary_worker_llm_raw_response",
    relation_id=str(relation_id),
    raw_response_length=len(raw_result) if raw_result else 0,
    raw_response_preview=(raw_result or "")[:200],
)
```
Remove the `_SUMMARY_MODEL_ID` constant entirely (it is dead code).

**Logic & Behavior:**
1. In `summary.py`, fix the evidence text filter:
   ```python
   evidence_texts = []
   for e in evidence_rows:
       text = e.get("evidence_text") or e.get("canonicalized_evidence_text")
       if text:
           evidence_texts.append(str(text))
   ```
   Remove the previous list comprehension that drops rows with `canonicalized_evidence_text` only.

2. Add a mandatory diagnostic log **before** the `if not evidence_texts: continue` guard:
   ```python
   logger.info(
       "summary_worker_relation_evidence_audit",
       relation_id=str(relation_id),
       evidence_rows_fetched=len(evidence_rows),
       evidence_text_null_count=sum(1 for e in evidence_rows if not e.get("evidence_text")),
       canonicalized_text_null_count=sum(1 for e in evidence_rows if not e.get("canonicalized_evidence_text")),
       evidence_texts_available=len(evidence_texts),
   )
   ```

3. Remove the dead `_SUMMARY_MODEL_ID = "kg-summary-v1"` constant from `summary.py` — it is never passed to `FallbackChainClient.extract()` and has no effect. `FallbackChainClient` has no model routing registry; it always runs DeepInfra → Ollama → Gemini regardless.

4. Add a diagnostic log of the raw LLM response **before** any parse step (see Issue B above). This is not strictly required for correctness but is essential for future debugging — the SummaryWorker is a silent failure vector.

5. Add `SUMMARY_WORKER_FORCE_REGENERATE_BATCH_SIZE` config env var (default 50) so ops can force-regenerate stale summaries in batches.

**Tests to write:**
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_summary_worker_uses_canonicalized_text_when_evidence_text_null` | Row with `evidence_text=NULL`, `canonicalized_evidence_text="..."` → text used for summary | unit |
| `test_summary_worker_skips_when_both_null` | Row with both NULL → `skipped_null_evidence_text += 1` | unit |
| `test_summary_worker_calls_llm_when_texts_available` | Happy path: LLM called, `insert_new` called, `mark_summary_updated` called | unit |

**Acceptance criteria:**
- [x] `canonicalized_evidence_text` accepted as fallback when `evidence_text` IS NULL
- [x] Diagnostic log emitted per relation showing evidence null breakdown
- [x] Dead `_SUMMARY_MODEL_ID` constant removed from `summary.py`
- [x] Diagnostic log of raw LLM response (length + 200-char preview) emitted before parse step
- [x] Unit tests pass

---

#### T-72-2-03: Add relation summary text to graph API response (optional read-only field)

**Type:** impl
**depends_on:** T-72-2-01, T-72-2-02
**blocks:** none
**Target files:**
- `services/knowledge-graph/src/knowledge_graph/api/schemas.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_summaries.py` (find or create)
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/graph_query.py`
- `services/knowledge-graph/src/knowledge_graph/api/routes.py`
- `services/knowledge-graph/tests/unit/api/test_graph_routes.py`

**PRD reference:** Investigation report 2026-05-05 §KQ-03

**What to build:**
Expose the current LLM-generated `relation_summaries` text (if available) in `RelationResponse`. Fetch summaries via a **batch second query** (same pattern as `evidence_snippets`) — do not JOIN into `list_for_entity()`.

**Why not a JOIN in list_for_entity():** `relations` is hash-partitioned ×8 on `subject_entity_id`; adding a JOIN on an unpartitioned `relation_summaries` table inside that query adds cross-partition join complexity. It also couples two separate concerns into one method. The batch-query pattern is architecturally consistent with T-72-2-01 and keeps each method single-responsibility.

**Logic & Behavior:**
1. **Schema change** (`schemas.py`): Add to `RelationResponse`:
   ```python
   relation_summary: str | None = None
   ```

2. **Repository method** (`relation_summaries.py`): Add:
   ```python
   async def get_current_summaries_batch(
       self,
       relation_ids: list[UUID],
   ) -> dict[UUID, str]:
   ```
   Query:
   ```sql
   SELECT relation_id, summary_text
   FROM relation_summaries
   WHERE relation_id = ANY(:relation_ids)
     AND is_current = true
   ```
   Return `dict[UUID, str]`. One query for all relations. With a partial index `WHERE is_current = true`, this is a direct index scan.

3. **Use case change** (`graph_query.py`): After fetching evidence snippets (T-72-2-01), also fetch summaries:
   ```python
   summaries_map = await summary_repo.get_current_summaries_batch(relation_ids)
   ```
   Merge into relation response objects: `relation_summary = summaries_map.get(relation_id)`.

4. **Router change** (`routes.py`): Add `summary_repo` to `EntityGraphReposDep` and thread through to `use_case.execute(...)`.

5. **Upgrade path note:** Add a comment in the repository method:
   ```python
   # TODO(PRD-0074): denormalize to current_summary_text TEXT on relations table,
   # updated atomically by SummaryWorker 13C. Eliminates this query entirely on
   # the hot path — pure column read, zero JOIN cost.
   ```
   This is the correct Bloomberg-grade long-term architecture. Summary is a single scalar per relation — the cheapest possible denormalization. SummaryWorker already writes to `relation_summaries`; it can trivially also write `relations.current_summary_text` in the same transaction.

**Tests to write:**
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_graph_response_includes_relation_summary` | Relation with a current summary returns non-null `relation_summary` | unit |
| `test_graph_response_null_summary_when_none_exists` | Relation with no `relation_summaries` row → `relation_summary=None` | unit |

**Acceptance criteria:**
- [x] `RelationResponse.relation_summary` present and non-null when a current summary exists
- [x] `relation_summary = null` when no current summary exists (not an error)
- [x] No JOIN added to `list_for_entity()` — summaries fetched via dedicated batch query
- [x] No N+1 query — single `ANY(:ids)` batch fetch for all relations
- [x] `# TODO(PRD-0074)` denormalization comment present in repository method
- [x] Unit tests pass

---

### Wave 2 Pre-read (agent must read before starting)

- `services/knowledge-graph/src/knowledge_graph/api/schemas.py`
- `services/knowledge-graph/src/knowledge_graph/api/routes.py`
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/graph_query.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_evidence.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/summary.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/llm/fallback_chain.py`

### Wave 2 Validation Gate

- [x] `ruff check` passes on changed files
- [x] `mypy` passes on changed packages (8 files clean)
- [x] `python -m pytest tests/ -m "unit" -v` in knowledge-graph passes (830 pass)
- [ ] `GET /api/v1/entities/{entity_id}/graph` response includes `evidence_snippets` and `relation_summary` (live test against running stack)
- [x] New unit tests: 14 new tests across 3 test files

### Wave 2 Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| Any test asserting exact shape of `RelationResponse` | New fields added (`evidence_snippets`, `relation_summary`) | Add `evidence_snippets=[]` and `relation_summary=None` to test fixtures |
| Frontend graph component (worldview-web) | New fields in API response | Frontend is additive — new fields ignored if not consumed; no break |

### Wave 2 Regression Guardrails

- **BP-025** (N+1 query): Both evidence batch fetch (T-72-2-01) and summary batch fetch (T-72-2-03) MUST be single `ANY(:ids)` queries. Neither may loop over individual relation IDs. Verify in code review.
- **BP-313 / SA-005**: Both fetches are read-only — no outbox concern.
- **No JOIN in list_for_entity()**: `relations` is hash-partitioned; adding JOINs on unpartitioned tables inside `list_for_entity()` adds cross-partition planner complexity. Use batch second queries for all auxiliary data (evidence, summaries).

---

## Wave 3: Graph API Depth Parameter + Entity Type Consistency ✅

**Goal:** Wire the frontend depth slider to the backend (currently backend always returns 1-hop regardless of depth param) and fix seeded entity type inconsistencies.
**Depends on:** Wave 2
**Estimated effort:** 90-120 min
**Architecture layer:** application + infrastructure
**Status:** **DONE** — 2026-05-05 · 841 KG unit + 74 prompts + 100 arch tests pass · ruff + mypy clean

### Tasks

#### T-72-3-01: Add depth parameter to graph endpoint — hybrid relational/AGE approach

**Type:** impl
**depends_on:** none
**blocks:** none
**Target files:**
- `services/knowledge-graph/src/knowledge_graph/api/routes.py`
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/graph_query.py` (depth=1 path, unchanged)
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/graph_query_cypher.py` (read existing)
- `services/knowledge-graph/src/knowledge_graph/api/schemas.py` (response mapping)
- `services/knowledge-graph/tests/unit/api/test_graph_routes.py`

**PRD reference:** Investigation report 2026-05-05 §"Graph depth slider disconnected" + §Finding-1 (hybrid decision)

**Architecture decision (Option C — amended 2026-05-05):**
- `depth=1` (default): routes to existing `GetEntityGraphUseCase` — full evidence_snippets + relation_summary JOIN from Wave 2, best data richness
- `depth=2` or `depth=3`: delegates to the **already-implemented** `GetCypherNeighborhoodUseCase` (AGE, Wave E-2 complete) which supports max_hops 1–3, then maps its response to `GraphNeighborhoodResponse`

This avoids reinventing BFS that AGE already provides. The response shape unification is the key work in this task.

**Logic & Behavior:**
1. **Route change** (`routes.py`): Add `depth: int = Query(default=1, ge=1, le=3)` to `get_entity_graph`.
2. **Dispatch logic** in the route handler:
   ```python
   if depth == 1:
       # Existing path — full evidence/summary richness
       entity_row, relation_rows, entities_map = await get_graph_use_case.execute(...)
       return _build_graph_response(entity_row, relation_rows, entities_map)
   else:
       # depth > 1: delegate to AGE Cypher neighborhood
       cypher_result = await get_cypher_neighborhood_use_case.execute(
           entity_id=entity_id,
           max_hops=depth,
           min_confidence=min_confidence,
           include_temporal_events=False,
           limit=limit,
       )
       return _map_cypher_to_graph_response(cypher_result, entity_id)
   ```
3. **`_map_cypher_to_graph_response()`** — new private function in `routes.py`:
   - Maps AGE vertex rows to `EntitySummary` objects
   - Maps AGE edge rows to `RelationResponse` objects (set `evidence_snippets=[]`, `relation_summary=None` for depth>1 — evidence JOIN is too expensive across multi-hop; can be added in a future iteration)
   - Constructs `GraphNeighborhoodResponse` with `center`, `relations`, `entities`
4. **`CYPHER_ENABLED` guard**: If `CYPHER_ENABLED=false` in config, fall back to depth=1 regardless and log a warning. This prevents errors in environments where AGE is not loaded.
5. **Validation**: `depth > 3` returns 422 (enforced by `le=3` on the Query param).

**Tests to write:**
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_depth_1_uses_relational_path` | `depth=1` → `GetEntityGraphUseCase` called, not Cypher use case | unit |
| `test_depth_2_delegates_to_cypher` | `depth=2` → `GetCypherNeighborhoodUseCase` called | unit |
| `test_depth_limit_caps_at_3` | `depth=4` → 422 Unprocessable Entity | unit |
| `test_cypher_disabled_falls_back_to_depth1` | `CYPHER_ENABLED=false`, `depth=2` → depth=1 path with warning | unit |
| `test_map_cypher_to_graph_response_shape` | `_map_cypher_to_graph_response()` produces valid `GraphNeighborhoodResponse` | unit |

**Acceptance criteria:**
- [x] `GET /api/v1/entities/{entity_id}/graph` (no depth or depth=1) → unchanged behavior, includes evidence_snippets
- [x] `GET /api/v1/entities/{entity_id}/graph?depth=2` → AGE neighborhood with 2-hop data
- [x] `depth > 3` returns 422
- [x] `CYPHER_ENABLED=false` → depth param silently capped at 1 with log warning
- [x] Response shape is `GraphNeighborhoodResponse` in all cases

---

#### T-72-3-02: Entity type hardening — validation at source + CHECK constraint enforcement

**Type:** impl + schema
**depends_on:** none
**blocks:** none
**Target files:**
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment_core.py`
- LLM extraction prompt template (search for `entity_type` in `services/knowledge-graph/src/` to locate the prompt)
- `services/intelligence-migrations/alembic/versions/0021_add_entity_type_check_constraint.py`
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_provisional_enrichment_core.py`

**PRD reference:** Investigation report 2026-05-05 §"entity type correction"

**What to build:**
Rather than repairing existing data (the cluster is relaunched from scratch with no stale rows), harden the generation pipeline so invalid `entity_type` values can never be inserted. Three layers: code validation, prompt constraint, database enforcement.

**Canonical entity types (from migration 0001 seed):**
`company`, `financial_instrument`, `person`, `organization`, `country`, `currency`, `commodity`, `index`, `sector`, `concept`, `event`, `other`

**Logic & Behavior:**

**Step 1 — Post-extraction normalization in code** (`provisional_enrichment_core.py`):
After parsing the LLM extraction response, normalize and validate `entity_type` before any DB write:
```python
_VALID_ENTITY_TYPES: frozenset[str] = frozenset({
    "company", "financial_instrument", "person", "organization",
    "country", "currency", "commodity", "index",
    "sector", "concept", "event", "other",
})
_ENTITY_TYPE_ALIASES: dict[str, str] = {
    "corp": "company", "corporation": "company", "enterprise": "company",
    "firm": "company", "business": "company",
    "organisation": "organization", "inst": "organization", "institution": "organization",
}

raw_type = (extracted.entity_type or "").lower().strip().replace(" ", "_")
normalized = _ENTITY_TYPE_ALIASES.get(raw_type, raw_type)
if normalized not in _VALID_ENTITY_TYPES:
    logger.warning(
        "provisional_enrichment_invalid_entity_type",
        raw_type=raw_type,
        mention_text=mention_text,
        defaulting_to="other",
    )
    normalized = "other"
entity_type = normalized
```
Unrecognized types default to `'other'` with a warning log — never silently drop or silently pass invalid values.

**Step 2 — LLM prompt hardening:**
In the entity profile extraction prompt, add explicit type enumeration:
```
entity_type MUST be exactly one of:
  company, financial_instrument, person, organization, country, currency,
  commodity, index, sector, concept, event, other
Do NOT invent new types. Use "other" for anything that does not fit the above list.
```

**Step 3 — CHECK constraint migration (enforcement, not repair):**
New Alembic migration `0021_add_entity_type_check_constraint.py`:
```sql
ALTER TABLE canonical_entities
    ADD CONSTRAINT ck_canonical_entity_type
    CHECK (entity_type IN (
        'company', 'financial_instrument', 'person', 'organization',
        'country', 'currency', 'commodity', 'index',
        'sector', 'concept', 'event', 'other'
    ));
```
This is **enforcement, not repair**. On a fresh-start cluster all existing rows are already valid. If a partial deployment ever created bad rows, the migration will error rather than silently pass — that is the intended behavior. Down migration: `ALTER TABLE canonical_entities DROP CONSTRAINT ck_canonical_entity_type`.

**Tests to write:**
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_valid_entity_type_passes_unchanged` | `entity_type="company"` → written as-is | unit |
| `test_uppercase_entity_type_normalized` | `entity_type="ORGANIZATION"` → normalized to `"organization"` | unit |
| `test_alias_corp_normalized_to_company` | `entity_type="corp"` → `"company"` | unit |
| `test_unknown_entity_type_defaults_to_other` | `entity_type="conglomerate"` → `"other"` + warning logged | unit |

**Acceptance criteria:**
- [x] `provisional_enrichment_core.py` normalizes and validates `entity_type` after extraction
- [x] Unrecognized types default to `'other'` with a warning log (never silently dropped or silently passed)
- [x] LLM extraction prompt explicitly enumerates all valid entity types
- [x] CHECK constraint migration runs cleanly on a fresh DB (migration 0021)
- [x] Unit tests pass

---

### Wave 3 Pre-read (agent must read before starting)

- `services/knowledge-graph/src/knowledge_graph/api/routes.py` (graph endpoint)
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/graph_query.py`
- `services/knowledge-graph/src/knowledge_graph/application/ports/repositories.py`
- `services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py` (entity_type seed values)

### Wave 3 Validation Gate

- [x] `ruff check` passes on changed files
- [x] `mypy` passes on changed packages
- [x] `python -m pytest tests/ -m "unit" -v` in knowledge-graph passes
- [ ] Live test: `GET /api/v1/entities/entity-aapl/graph?depth=2` returns 2-hop data (requires live AGE — deferred to next live-stack QA)
- [x] `depth=4` returns 422 (covered by `test_depth_limit_caps_at_3`)
- [x] New unit tests: minimum 5 (11 new tests added)

### Wave 3 Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| Any test calling `get_entity_graph` without `depth` param | Default depth=1 is backward-compat — no break | None |
| Frontend graph component | New `depth` param is optional with default — no break | Frontend already sends `depth` param (it was just ignored before) |

### Wave 3 Regression Guardrails

- **BP-025** (N+1 query): Hybrid approach delegates depth>1 to AGE Cypher — no Python-level N+1 risk. Verify Cypher neighborhood use case has its own query budget.
- **BP-007** (Alembic): Entity type migration must be idempotent — test on a populated DB snapshot before committing.
- **CYPHER_ENABLED guard**: If AGE is not loaded (common in CI), depth>1 must fall back gracefully, not error. Add integration test with `CYPHER_ENABLED=false`.

---

## Wave 4: Deferred

**Wave 4 (evidence promotion pipeline) has been deferred to PRD-0074.**

Reasons:
1. `relation_evidence` has no unique constraint on `(relation_id, doc_id, evidence_date)` — the `ON CONFLICT DO NOTHING` idempotency guarantee requires a new unique index, which is better co-designed with PRD-0074's evidence-analytics query patterns.
2. No current consumer reads from `relation_evidence` directly. The SummaryWorker (Wave 2) reads from `relation_evidence_raw`. Promoting rows to the immutable table solves a future problem, not a current one.
3. The column names in `relation_evidence_raw` (`doc_id`) differ from what was originally specced in this plan (`source_doc_id`) — PRD-0074 should reconcile the schema before building a promotion pipeline on top of it.
4. UUIDv7 compliance (R10): the correct `new_uuid7()` call belongs in a future plan with full evidence-lifecycle design, not as a patch here.

**What PRD-0074 should include for this feature:**
- `CREATE UNIQUE INDEX CONCURRENTLY uidx_relation_evidence_dedup ON relation_evidence (relation_id, doc_id, evidence_date)` as an explicit migration
- `EvidencePromotionWorker` (Worker 13I) registered in scheduler
- `promote_raw_to_immutable()` repo method using `new_uuid7()` for IDs and correct column names
- Partition existence guard (coordinate with `MonthlyPartitionWorker` 13G)

---

## Cross-Cutting Concerns

### Contract Changes
- `RelationResponse` gains `evidence_snippets: list[str]` and `relation_summary: str | None` — additive, forward-compatible
- `GET /api/v1/entities/{entity_id}/graph` gains optional `depth: int` param (default 1) — backward-compatible

### Migration Order

Two migrations go into `intelligence-migrations` (data-repair migrations removed — fresh-start cluster). IDs 0022–0023 are intentionally skipped.

| Revision | Name | Wave | Key change |
|----------|------|------|-----------|
| **0020** | `add_noise_status_to_provisional_queue` | Wave 1, T-72-1-01 | Add `CHECK (status IN ('pending','processing','resolved','failed','noise'))` to `provisional_entity_queue` |
| **0021** | `add_entity_type_check_constraint` | Wave 3, T-72-3-02 | Add `CHECK (entity_type IN (...))` to `canonical_entities` — enforcement, not repair |

> IDs 0022–0023 are reserved/unused. **PLAN-0073 uses revision IDs 0024–0027** — do not start PLAN-0073 Wave A until migrations 0020–0021 are merged.

### Documentation Updates
- `docs/services/knowledge-graph.md` — update graph endpoint spec with `depth` param and new response fields
- `services/knowledge-graph/.claude-context.md` — add noise blocklist location, SummaryWorker status, evidence_snippets

---

## Risk Assessment

**Critical path:** Wave 1 (noise filtering + normalization + cleanup) → Wave 2 (evidence + SummaryWorker) → Wave 3 (depth hybrid + entity type)

**Highest risk tasks:**
- T-72-3-01 (hybrid depth): Requires reading the existing `GetCypherNeighborhoodUseCase` response shape carefully to map to `GraphNeighborhoodResponse`. The Cypher path returns `CypherNeighborhoodResponse` — the mapping function `_map_cypher_to_graph_response()` must correctly flatten entity vertex data. Read `application/use_cases/graph_query_cypher.py` before implementing.
- T-72-1-01 (two-layer noise filter): The Layer 2 fail-open path is critical — a timeout in the cheap classifier must never silently drop a queue row. Verify the exception handler falls through to Layer 3 correctly, not to noise marking.
- T-72-2-02 (SummaryWorker): The NULL evidence_text issue is the root cause, not LLM routing. Verify with the diagnostic log (Issue B) that `FallbackChainClient.extract()` is actually returning a result before concluding the issue is fixed.

**Rollback strategy:**
- Wave 1 migrations: `ck_provisional_status` constraint can be dropped with `ALTER TABLE provisional_entity_queue DROP CONSTRAINT ck_provisional_status`; no data changed by this migration
- Wave 2 schema: `evidence_snippets` and `relation_summary` field removal is backward-compatible (just remove the JOIN and fields)
- Wave 3 migrations: `ck_canonical_entity_type` constraint can be dropped with `ALTER TABLE canonical_entities DROP CONSTRAINT ck_canonical_entity_type`; no data changed
- Wave 3 hybrid: Removing hybrid routing → revert to depth=1 always (backward-compatible, as depth param has default=1)

---

## Deferred to PRD Session

| Item | Target | Reason |
|------|--------|--------|
| **Isolated node enrichment** (68% entities with 0 relations) | **PRD-0073** | Requires structured enrichment from EODHD, new worker, new confidence sub-profile |
| **Hub node quality scoring** (KQ-05: "US" 68 relations, "analysts" 72 relations) | **PRD-0073 or PRD-0074** | Entity quality scoring requires structured data that PRD-0073 introduces; down-ranking logic fits alongside the enrichment scoring model |
| **Evidence promotion pipeline** (4d: `relation_evidence_raw → relation_evidence`) | **PRD-0074** | `relation_evidence` lacks the unique index required for idempotent promotion; co-design with PRD-0074 evidence-analytics patterns; no current downstream consumer reads from `relation_evidence` |
| **Intelligence layer** (edge opportunity scoring, contradiction visualization, temporal graph view) | **PRD-0074** | Formal PRD in progress |
| **Multi-hop depth > 3** | Future | AGE Cypher supports up to 5 hops but frontend pagination design is needed first |
