# PLAN-0072: Knowledge Graph Data Quality Enhancement

**Status:** draft
**Created:** 2026-05-05
**Owner:** Knowledge Graph team
**PRD:** Investigation reports from 2026-05-05 sessions (no formal PRD — fixes derive from confirmed root causes)
**Waves:** 4 implementation waves (amended 2026-05-05: added Finding-4 items + hybrid depth approach)

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
| KQ-05 | Hub node pollution — generic nodes ("US", "analysts") acquire 60-72 relations | MEDIUM | No confidence threshold applied to hub-to-generic relations; no entity-quality score |

### Issues deferred to /prd session

- Isolated node enrichment (68% of entities have 0 relations) → PRD-0073
- Intelligence layer: edge opportunity scoring, contradiction visualization, temporal graph view → PRD-0074

### Amended scope (2026-05-05)

Four items added from Finding 4 investigation:
- **4a** (T-72-1-04): Retroactive noise entity cleanup migration — delete isolated noise entities already in DB
- **4b**: Added to T-72-1-03 — mark `confidence_stale=true` on all relations after type normalization so Worker 13A auto-recalculates
- **4c** (T-72-1-05): UnresolvedResolutionWorker prompt hardening — reduce noise leakage from S6 side
- **4d** (Wave 4): Evidence promotion pipeline — batch promote `relation_evidence_raw` to immutable `relation_evidence` partition

Multi-hop traversal strategy changed from pure relational BFS to **hybrid**:
- `depth=1` → existing relational `GetEntityGraphUseCase` (full evidence/summary JOIN)
- `depth>1` → delegate to existing `GetCypherNeighborhoodUseCase` (AGE, already implemented) + map response to `GraphNeighborhoodResponse`

---

## Codebase State Verification

| Component | Current State | Required Change | Delta |
|-----------|--------------|-----------------|-------|
| `provisional_enrichment.py` | Queries `status='pending'` rows, no text filter | Add mention_text blocklist check before profile extraction | Code change |
| `provisional_enrichment_core.py` | No blocklist; dedup check added (BP-384) | No additional change | None |
| `canonicalization.py` | Step 1 exact match is case-sensitive | Normalize `raw_type.lower().strip()` before exact lookup | Code change |
| `relation_type_registry` table | Has both UPPERCASE (migration 0004) and lowercase (migration 0001) canonical_types | Normalize all to lowercase via migration | Schema + seed |
| `schemas.py` (`RelationResponse`) | No `evidence_snippets` field | Add `evidence_snippets: list[str]` (max 3) | Schema change |
| `graph_query.py` | Uses `relation_repo.list_for_entity()` which has no evidence JOIN | Add evidence JOIN or separate batch fetch | Code change |
| `relation.py` (repo) | `list_for_entity` returns 8 columns, no evidence text | Add optional evidence JOIN | Code change |
| `summary.py` | `skipped_null_evidence_text` branches on `evidence_text` NULL correctly, but logs silently | Add explicit diagnostic log + separate fix for NULL evidence backfill | Code change |
| `summary.py` | Calls `_SUMMARY_MODEL_ID = "kg-summary-v1"` — model must be registered in FallbackChainClient | Verify model registration in config; add fallback | Config/code |

---

## Wave 1: Noise Entity Filtering + Relation Type Normalization

**Goal:** Stop noise entities from entering the KG and fix the case mismatch that causes ~30% of LLM-extracted relations to emit `canonical_type=None`.
**Depends on:** none
**Estimated effort:** 60-90 min
**Architecture layer:** infrastructure + application

### Tasks

#### T-72-1-01: Mention-text noise blocklist in ProvisionalEnrichmentWorker

**Type:** impl
**depends_on:** none
**blocks:** none
**Target files:**
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py`
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_provisional_enrichment.py` (or add new file)

**PRD reference:** Investigation report 2026-05-05 §KQ-01

**What to build:**
Add a pre-filter that checks `mention_text` against a blocklist before any LLM call is made. If a queue row matches the blocklist, update its status to `'noise'` immediately (no LLM extraction, no entity creation, no outbox event). The blocklist is a module-level frozen set for O(1) lookup with case-insensitive normalization.

**Logic & Behavior:**
1. Define `_NOISE_BLOCKLIST: frozenset[str]` at the top of `provisional_enrichment.py` containing normalized (lowercase stripped) values:
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
2. In `ProvisionalEnrichmentWorker.run()`, after loading `pending_rows`, add a pre-filter loop:
   - For each row, check `mention_text.lower().strip() in _NOISE_BLOCKLIST`
   - Collect the `queue_id`s that are noise
   - Batch `UPDATE provisional_entity_queue SET status = 'noise', resolved_at = now() WHERE queue_id = ANY(:ids) AND status = 'pending'`
   - Log `provisional_enrichment_noise_filtered` with count
   - Remove filtered rows from `pending_rows` before continuing
3. A `'noise'` status is a new terminal state — add it to the `CHECK` constraint: `status IN ('pending','processing','resolved','failed','noise')`.

**IMPORTANT:** The `provisional_entity_queue.status` CHECK constraint is defined in the intelligence-migrations Alembic migrations, not in S7. The DDL change goes in `services/intelligence-migrations/alembic/versions/` as a new migration. However, since the status column already uses a text field with a check constraint, also check whether an Alembic migration is already at a point where this can be added cleanly or whether to add it as a separate migration.

**Tests to write:**
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_noise_blocklist_skips_llm_and_marks_noise` | Queue row with `mention_text="he"` → status `'noise'`, no LLM extract called | unit |
| `test_non_noise_mention_proceeds_normally` | Queue row with `mention_text="Apple Inc."` → proceeds to extract | unit |
| `test_blocklist_case_insensitive` | `mention_text="ANALYSTS"` → filtered | unit |

**Acceptance criteria:**
- [ ] `mention_text.lower().strip() in _NOISE_BLOCKLIST` applied before any LLM call
- [ ] `status='noise'` written for matched rows
- [ ] Prometheus counter incremented: `s7_provisional_noise_filtered_total`
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
3. The registry's `canonical_type` column values should also be stored lowercase — verify seed data in migration 0001 and 0004. If migration 0004 inserted UPPERCASE values, add a data migration to normalize them (see T-72-1-03).
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

#### T-72-1-03: Data migration — normalize relation_type_registry to lowercase

**Type:** schema
**depends_on:** T-72-1-02
**blocks:** none
**Target files:**
- `services/intelligence-migrations/alembic/versions/<next_head>_normalize_relation_types_lowercase.py`

**PRD reference:** Investigation report 2026-05-05 §KQ-02

**What to build:**
A new Alembic migration (head of `intelligence-migrations`) that:
1. `UPDATE relation_type_registry SET canonical_type = LOWER(canonical_type)` for any UPPERCASE entries
2. `UPDATE relations SET canonical_type = LOWER(canonical_type) WHERE canonical_type IS NOT NULL` — normalizes already-stored relation canonical_type values
3. `UPDATE relations SET confidence_stale = true WHERE canonical_type IS NOT NULL` — marks all relations for confidence recalculation so Worker 13A (runs every 15 min) auto-refreshes with the correct decay_alpha for the now-normalized type **(Finding 4b fix)**
4. Down migration: no-op (lowercase is the forward-compatible canonical form)

**Migration metadata:**
- Current head: check with `alembic -c services/intelligence-migrations/alembic.ini current`
- New revision: `<auto-generated>`
- New revision name: `normalize_relation_types_lowercase`

**Downstream test impact:**
- Any test that asserts `canonical_type == "COMPETES_WITH"` (UPPERCASE) will break — grep for UPPERCASE relation type constants in test files and update to lowercase.

**Acceptance criteria:**
- [ ] Migration runs without error on a fresh db (test infra)
- [ ] `SELECT DISTINCT canonical_type FROM relation_type_registry WHERE canonical_type != LOWER(canonical_type)` returns 0 rows after migration
- [ ] `SELECT DISTINCT canonical_type FROM relations WHERE canonical_type IS NOT NULL AND canonical_type != LOWER(canonical_type)` returns 0 rows

---

---

#### T-72-1-04: Retroactive noise entity cleanup migration

**Type:** schema
**depends_on:** T-72-1-01
**blocks:** none
**Target files:**
- `services/intelligence-migrations/alembic/versions/<next_head>_cleanup_noise_entities.py`

**PRD reference:** Investigation report 2026-05-05 §Finding-4a

**What to build:**
Delete existing noise entities (already in DB before the blocklist was added) that are isolated (zero relations). Hub noise entities (those with existing relations, e.g. "analysts" with 72, "US" with 68) are NOT deleted automatically — their pollution is addressed via entity quality scoring in PRD-0073/0074.

**Logic & Behavior:**
```sql
-- Step 1: find isolated entities whose canonical_name matches noise patterns
-- Only delete entities with 0 relations in EITHER direction
WITH noise_candidates AS (
    SELECT e.entity_id
    FROM canonical_entities e
    WHERE LOWER(TRIM(e.canonical_name)) IN (
        'he','she','they','it','we','us','his','her','their','him','them',
        'who','what','constant currency','organic growth','analysts',
        'management','investors','shareholders','executives','regulators',
        'the company','company','the firm','firm','business',
        'simply wall st','seeking alpha','the motley fool','bloomberg',
        'reuters','cnbc','marketwatch','wsj','street','market',
        'sector','industry','index'
    )
    AND NOT EXISTS (
        SELECT 1 FROM relations r
        WHERE r.subject_entity_id = e.entity_id
           OR r.object_entity_id  = e.entity_id
    )
)
DELETE FROM canonical_entities WHERE entity_id IN (SELECT entity_id FROM noise_candidates);
-- CASCADE handles entity_aliases, entity_embedding_state, provisional_entity_queue
```

**Acceptance criteria:**
- [ ] Migration runs cleanly against a populated DB snapshot (test infra or staging)
- [ ] Only zero-relation noise entities are deleted (hub noise entities with relations survive)
- [ ] `SELECT count(*) FROM canonical_entities WHERE LOWER(canonical_name) IN ('he','analysts',...)` returns 0 (or only hub ones)
- [ ] Migration is idempotent

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
The UnresolvedResolutionWorker uses an LLM to classify raw GLiNER-detected entity mentions as either "real named entity" (→ enqueue to provisional_entity_queue) or "noise/generic term" (→ discard). The current prompt is too permissive — terms like "analysts", "management", "constant currency" pass through as "real" entities. Harden the prompt with explicit examples of noise vs real entities.

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
- `services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py` (relation_type_registry seed)
- `services/intelligence-migrations/alembic/versions/0004_geopolitical_age_temporal_events.py` (UPPERCASE AGE labels)
- `services/knowledge-graph/tests/unit/application/blocks/test_canonicalization.py` (if exists)
- Find and read `UnresolvedResolutionWorker` in `services/nlp-pipeline/src/` (for T-72-1-05)

### Wave 1 Validation Gate

- [ ] `ruff check` passes on changed files
- [ ] `mypy` passes on changed packages
- [ ] `python -m pytest tests/ -m "unit" -v` passes in knowledge-graph service
- [ ] Alembic migration head advances cleanly
- [ ] New unit tests: minimum 6

### Wave 1 Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| Any test asserting `canonical_type == "COMPETES_WITH"` | Migration normalizes to lowercase | Change assertion to `"competes_with"` |
| `provisional_entity_queue` CHECK constraint | New `'noise'` status value | Covered by T-72-1-01 migration |

### Wave 1 Regression Guardrails

- **BP-384** (entity dedup): Noise blocklist check must run BEFORE the dedup alias check — noise rows should not even reach `persist_enrichment`. Verify ordering.
- **BP-007** (missing server_default): If the status column CHECK constraint is altered, ensure no `ALTER COLUMN` with NOT NULL on a populated table without a server_default.
- **BP-019** (Alembic migration): Always verify `alembic upgrade head` on the test DB before committing the migration.

---

## Wave 2: Evidence Text in Graph API + SummaryWorker Diagnosis

**Goal:** Expose evidence text snippets in the graph API response (so frontend can show "why does this edge exist?") and fix the SummaryWorker silent skip issue.
**Depends on:** Wave 1 (for normalized relation types)
**Estimated effort:** 60-90 min
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
Extend `RelationResponse` with `evidence_snippets: list[str]` (max 3 items) and wire it through the stack. Evidence snippets are the top-3 `evidence_text` values from `relation_evidence_raw` for each relation, ordered by `extraction_confidence DESC NULLS LAST, evidence_date DESC NULLS LAST`.

**Architecture constraint:** The use case (`GetEntityGraphUseCase`) must not import from infrastructure — it receives data through the repository port. The repository is responsible for the JOIN.

**Logic & Behavior:**
1. **Schema change** (`schemas.py`): Add to `RelationResponse`:
   ```python
   evidence_snippets: list[str] = Field(
       default_factory=list,
       description="Up to 3 evidence text snippets supporting this relation.",
   )
   ```
2. **Repository change** (`relation.py` → `list_for_entity`): Extend the SQL query to LEFT JOIN `relation_evidence_raw` and aggregate top-3 evidence_text values using a lateral subquery or `array_agg` with ORDER BY + LIMIT:
   ```sql
   LEFT JOIN LATERAL (
       SELECT COALESCE(evidence_text, canonicalized_evidence_text) AS snip
       FROM relation_evidence_raw rer
       WHERE rer.relation_id = r.relation_id
         AND (rer.evidence_text IS NOT NULL OR rer.canonicalized_evidence_text IS NOT NULL)
       ORDER BY rer.extraction_confidence DESC NULLS LAST,
                rer.evidence_date DESC NULLS LAST
       LIMIT 3
   ) ev_snips ON true
   ```
   Then `array_remove(array_agg(ev_snips.snip), NULL)` in the outer SELECT.

   Alternatively (simpler): fetch evidence as a second batch query keyed on relation_ids. Batch query is preferred to avoid the lateral JOIN complexity — call `ev_repo.get_evidence_snippets_batch(relation_ids, limit=3)` and merge in Python.

   **Recommended approach:** batch Python merge (simpler, avoids lateral JOIN):
   - Add `get_evidence_snippets_batch(relation_ids: list[UUID], limit_per_relation: int) -> dict[UUID, list[str]]` to `RelationEvidenceRepository`
   - Query: `WHERE relation_id = ANY(:ids) AND evidence_text IS NOT NULL ORDER BY relation_id, extraction_confidence DESC NULLS LAST, evidence_date DESC NULLS LAST`
   - In Python, group by `relation_id`, take first `limit` per group
   - Merge into `relation_rows` in `GetEntityGraphUseCase.execute()`

3. **Use case change** (`graph_query.py`): After fetching `relation_rows`, fetch evidence batch. Add `evidence_snippets_map: dict[UUID, list[str]]` parameter pattern via constructor injection or direct repo call.

   Since the use case currently receives only `entity_repo` and `relation_repo` as port objects, extend the use case signature:
   ```python
   async def execute(
       self,
       entity_repo: CanonicalEntityRepositoryPort,
       relation_repo: RelationRepositoryPort,
       evidence_repo: RelationEvidenceRepositoryPort,  # NEW
       ...
   ) -> ...:
   ```
   Then call `evidence_repo.get_evidence_snippets_batch(...)`.

4. **Router change** (`routes.py`): Add `evidence_repo` to `EntityGraphReposDep` dependency and thread through to `use_case.execute(...)`.

5. **Schema validation**: `evidence_snippets` must be empty list `[]` (not null) when no evidence exists — use `default_factory=list`.

**Tests to write:**
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_graph_response_includes_evidence_snippets` | Relations with evidence return `evidence_snippets` list | unit |
| `test_graph_response_empty_snippets_when_no_evidence` | Relations without evidence return `[]` not None | unit |
| `test_evidence_snippets_capped_at_3` | Even if 10 evidence rows exist, only 3 returned | unit |

**Acceptance criteria:**
- [ ] `GET /api/v1/entities/{entity_id}/graph` response includes `evidence_snippets: [...]` on each relation
- [ ] At most 3 snippets per relation
- [ ] `evidence_snippets` is always a list (never null)
- [ ] No N+1 query — single batch fetch for all relations
- [ ] Port interface (`RelationEvidenceRepositoryPort`) updated if it exists, or created if needed

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

**Issue B — `kg-summary-v1` model ID registration:** Verify that `FallbackChainClient` has `kg-summary-v1` registered as a valid model. If the LLM client silently returns `None` for unrecognized model IDs (as documented in BP-337), then every summary attempt returns `None` → `summaries_skipped` or `summaries_failed`. Check `services/knowledge-graph/src/knowledge_graph/infrastructure/llm/fallback_chain.py` for model routing.

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

3. In `fallback_chain.py`, verify that `extract()` with `model_id="kg-summary-v1"` routes correctly. If `kg-summary-v1` is not in the model routing table, map it to the default extraction model (same as `_EXTRACT_MODEL_ID` in `provisional_enrichment_core.py`). Add a fallback:
   ```python
   # In model routing: if model_id unknown, fall back to default extraction chain
   effective_model = self._model_registry.get(model_id, self._default_extract_model)
   ```

4. Add `SUMMARY_WORKER_FORCE_REGENERATE_BATCH_SIZE` config env var (default 50) so ops can force-regenerate stale summaries in batches.

**Tests to write:**
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_summary_worker_uses_canonicalized_text_when_evidence_text_null` | Row with `evidence_text=NULL`, `canonicalized_evidence_text="..."` → text used for summary | unit |
| `test_summary_worker_skips_when_both_null` | Row with both NULL → `skipped_null_evidence_text += 1` | unit |
| `test_summary_worker_calls_llm_when_texts_available` | Happy path: LLM called, `insert_new` called, `mark_summary_updated` called | unit |

**Acceptance criteria:**
- [ ] `canonicalized_evidence_text` accepted as fallback when `evidence_text` IS NULL
- [ ] Diagnostic log emitted per relation showing evidence null breakdown
- [ ] `kg-summary-v1` model ID routes to valid LLM chain (verified by tracing `fallback_chain.py`)
- [ ] Unit tests pass

---

#### T-72-2-03: Add relation summary text to graph API response (optional read-only field)

**Type:** impl
**depends_on:** T-72-2-01, T-72-2-02
**blocks:** none
**Target files:**
- `services/knowledge-graph/src/knowledge_graph/api/schemas.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation.py`

**PRD reference:** Investigation report 2026-05-05 §KQ-03

**What to build:**
Expose the current LLM-generated `relation_summaries` text (if available) in `RelationResponse`. This is an additive-only schema change.

**Logic & Behavior:**
1. Add `relation_summary: str | None = None` to `RelationResponse`.
2. In `relation.py` → `list_for_entity()`, LEFT JOIN `relation_summaries rs ON rs.relation_id = r.relation_id AND rs.is_current = true` and include `rs.summary_text` in the SELECT.
3. In `routes.py` → `_entity_summary()` → the existing `_summary_authority()` call: also extract `rs.summary_text` and set on `RelationResponse.relation_summary`.

**Acceptance criteria:**
- [ ] `RelationResponse.relation_summary` present and non-null when a summary exists
- [ ] `relation_summary = null` when no current summary exists (not an error)
- [ ] Existing graph API tests pass

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

- [ ] `ruff check` passes on changed files
- [ ] `mypy` passes on changed packages
- [ ] `python -m pytest tests/ -m "unit" -v` in knowledge-graph passes
- [ ] `GET /api/v1/entities/{entity_id}/graph` response includes `evidence_snippets` and `relation_summary` (live test against running stack)
- [ ] New unit tests: minimum 5

### Wave 2 Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| Any test asserting exact shape of `RelationResponse` | New fields added (`evidence_snippets`, `relation_summary`) | Add `evidence_snippets=[]` and `relation_summary=None` to test fixtures |
| Frontend graph component (worldview-web) | New fields in API response | Frontend is additive — new fields ignored if not consumed; no break |

### Wave 2 Regression Guardrails

- **BP-025** (N+1 query): Evidence batch fetch MUST be a single query (`ANY(:ids)` pattern), not a loop of individual fetches. Verify in code review.
- **BP-313 / SA-005**: Evidence JOIN does not write any state — read-only use case, no outbox concern.

---

## Wave 3: Graph API Depth Parameter + Entity Type Consistency

**Goal:** Wire the frontend depth slider to the backend (currently backend always returns 1-hop regardless of depth param) and fix seeded entity type inconsistencies.
**Depends on:** Wave 2
**Estimated effort:** 90-120 min
**Architecture layer:** application + infrastructure

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
- [ ] `GET /api/v1/entities/{entity_id}/graph` (no depth or depth=1) → unchanged behavior, includes evidence_snippets
- [ ] `GET /api/v1/entities/{entity_id}/graph?depth=2` → AGE neighborhood with 2-hop data
- [ ] `depth > 3` returns 422
- [ ] `CYPHER_ENABLED=false` → depth param silently capped at 1 with log warning
- [ ] Response shape is `GraphNeighborhoodResponse` in all cases

---

#### T-72-3-02: Entity type consistency — normalize seeded instrument entity types

**Type:** schema + impl
**depends_on:** T-72-1-03
**blocks:** none
**Target files:**
- `services/intelligence-migrations/alembic/versions/<next_head>_normalize_entity_types.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/fundamentals_refresh.py` (if entity_type used)

**PRD reference:** Investigation report 2026-05-05 §"entity type correction"

**What to build:**
The seeded `canonical_entities` rows for instruments use inconsistent `entity_type` values (`"ORGANIZATION"`, `"company"`, `"financial_instrument"`, `"person"` in mixed casing). LLM extraction emits types in different casing than the seeds. Fix by normalizing all entity_type values to the canonical set defined in migration 0001.

**Canonical entity types (from migration 0001 seed):**
`company`, `financial_instrument`, `person`, `organization`, `country`, `currency`, `commodity`, `index`, `sector`, `concept`, `event`, `other`

**Logic & Behavior:**
1. New Alembic migration:
   ```sql
   UPDATE canonical_entities
   SET entity_type = LOWER(TRIM(entity_type))
   WHERE entity_type != LOWER(TRIM(entity_type));

   -- Map non-standard types to standard ones
   UPDATE canonical_entities SET entity_type = 'organization'
   WHERE LOWER(entity_type) IN ('organisation', 'inst', 'institution');

   UPDATE canonical_entities SET entity_type = 'company'
   WHERE LOWER(entity_type) IN ('corp', 'corporation', 'enterprise', 'firm', 'business');
   ```
2. Down migration: no-op (normalization is forward-compatible).

**Acceptance criteria:**
- [ ] `SELECT DISTINCT entity_type FROM canonical_entities WHERE entity_type != LOWER(entity_type)` returns 0 rows
- [ ] No entity_type values outside the canonical set remain after migration
- [ ] Migration is idempotent (running twice produces same result)

---

### Wave 3 Pre-read (agent must read before starting)

- `services/knowledge-graph/src/knowledge_graph/api/routes.py` (graph endpoint)
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/graph_query.py`
- `services/knowledge-graph/src/knowledge_graph/application/ports/repositories.py`
- `services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py` (entity_type seed values)

### Wave 3 Validation Gate

- [ ] `ruff check` passes on changed files
- [ ] `mypy` passes on changed packages
- [ ] `python -m pytest tests/ -m "unit" -v` in knowledge-graph passes
- [ ] Live test: `GET /api/v1/entities/entity-aapl/graph?depth=2` returns 2-hop data
- [ ] `depth=4` returns 422
- [ ] New unit tests: minimum 5

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

## Wave 4: Evidence Promotion Pipeline

**Goal:** Promote evidence rows from the staging table `relation_evidence_raw` to the immutable partition table `relation_evidence`, enabling proper evidence lifecycle management and unblocking long-term evidence analytics.
**Depends on:** Wave 2 (SummaryWorker must be producing summaries before evidence promotion is meaningful)
**Estimated effort:** 60-90 min
**Architecture layer:** infrastructure (worker + migration)

### Tasks

#### T-72-4-01: Batch evidence promotion worker (basic path)

**Type:** impl
**depends_on:** none
**blocks:** none
**Target files:**
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/evidence_promotion.py` (new)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py` (register worker)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_evidence.py` (add `promote_raw_to_immutable` method)
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_evidence_promotion.py` (new)

**PRD reference:** Investigation report 2026-05-05 §Finding-4d

**What to build:**
A new scheduled worker (Worker 13I) that promotes `relation_evidence_raw` rows to the current active immutable partition in `relation_evidence`. The promotion is idempotent (keyed on `(relation_id, source_doc_id, evidence_date)`).

The `relation_evidence` table is partitioned by `evidence_date` (month). The promotion logic selects `relation_evidence_raw` rows where:
1. `entity_provisional = false` (already resolved)
2. `evidence_text IS NOT NULL OR canonicalized_evidence_text IS NOT NULL`
3. Not already present in `relation_evidence` (deduplicate by natural key)

**Logic & Behavior:**
1. New `EvidencePromotionWorker` class following the same APScheduler pattern as existing workers:
   ```python
   class EvidencePromotionWorker:
       _BATCH_LIMIT = 500  # rows per run

       async def run(self) -> None:
           async with self._sf() as session:
               ev_repo = RelationEvidenceRepository(session)
               promoted = await ev_repo.promote_raw_to_immutable(self._BATCH_LIMIT)
               logger.info("evidence_promotion_complete", promoted=promoted)
   ```
2. `promote_raw_to_immutable()` in the repo:
   ```sql
   INSERT INTO relation_evidence (
       evidence_id, relation_id, source_doc_id, evidence_date,
       evidence_text, canonicalized_evidence_text, extraction_confidence,
       source_weight, created_at
   )
   SELECT
       gen_random_uuid(), rer.relation_id, rer.source_doc_id,
       COALESCE(rer.evidence_date, CURRENT_DATE),
       rer.evidence_text, rer.canonicalized_evidence_text,
       rer.extraction_confidence, rer.source_weight, rer.created_at
   FROM relation_evidence_raw rer
   WHERE rer.entity_provisional = false
     AND (rer.evidence_text IS NOT NULL OR rer.canonicalized_evidence_text IS NOT NULL)
   ON CONFLICT (relation_id, source_doc_id, evidence_date) DO NOTHING
   LIMIT :batch_limit
   RETURNING evidence_id
   ```
3. Schedule: every 4 hours. Not time-critical — SummaryWorker already falls back to `raw` table.
4. Prometheus counter: `s7_evidence_promoted_total`.

**Tests to write:**
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_promotion_inserts_resolved_rows` | Rows with `entity_provisional=false` + non-null text → inserted to relation_evidence | unit |
| `test_promotion_skips_provisional_rows` | Rows with `entity_provisional=true` → not inserted | unit |
| `test_promotion_idempotent` | Running twice → ON CONFLICT DO NOTHING, count unchanged | unit |

**Acceptance criteria:**
- [ ] Worker registered in scheduler.py as `"evidence_promotion"` every 4 hours
- [ ] `ON CONFLICT DO NOTHING` on `(relation_id, source_doc_id, evidence_date)` — idempotent
- [ ] Only `entity_provisional=false` rows promoted
- [ ] Unit tests pass

---

### Wave 4 Pre-read (agent must read before starting)

- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/summary.py` (pattern to follow)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py` (how workers are registered)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_evidence.py` (existing repo methods for `relation_evidence` and `relation_evidence_raw`)
- `services/intelligence-migrations/alembic/versions/` — find the migration that created `relation_evidence` table to understand partition schema

### Wave 4 Validation Gate

- [ ] `ruff check` passes on changed files
- [ ] `mypy` passes on `knowledge_graph` package
- [ ] Unit tests pass (minimum 3 new tests)
- [ ] Worker registered in scheduler without disrupting existing workers
- [ ] `SELECT count(*) FROM relation_evidence` increases after worker runs (live test)

### Wave 4 Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| None expected | New worker, new repo method, no existing behavior changed | — |

### Wave 4 Regression Guardrails

- **BP-025** (N+1): Batch INSERT with LIMIT — not a query loop, no N+1 risk
- **BP-007** (Alembic partition): `relation_evidence` is partitioned by `evidence_date` month. Inserting a row with an `evidence_date` for a month that has no partition yet will fail. The existing partition worker (13G/H) creates partitions on the 1st of each month — ensure rows with `evidence_date` in the current + next month have partitions before promotion runs

---

## Cross-Cutting Concerns

### Contract Changes
- `RelationResponse` gains `evidence_snippets: list[str]` and `relation_summary: str | None` — additive, forward-compatible
- `GET /api/v1/entities/{entity_id}/graph` gains optional `depth: int` param (default 1) — backward-compatible

### Migration Order
1. Wave 1, T-72-1-01: `add_noise_status_to_provisional_queue` migration
2. Wave 1, T-72-1-03: `normalize_relation_types_lowercase` migration (includes confidence_stale reset)
3. Wave 1, T-72-1-04: `cleanup_noise_entities` migration
4. Wave 3, T-72-3-02: `normalize_entity_types` migration
All go into `intelligence-migrations`; they must be applied in the order above.

### Documentation Updates
- `docs/services/knowledge-graph.md` — update graph endpoint spec with `depth` param and new response fields
- `services/knowledge-graph/.claude-context.md` — add noise blocklist location, SummaryWorker status, evidence_snippets

---

## Risk Assessment

**Critical path:** Wave 1 (noise filtering + normalization + cleanup) → Wave 2 (evidence + SummaryWorker) → Wave 3 (depth hybrid + entity type) → Wave 4 (evidence promotion)

**Highest risk tasks:**
- T-72-3-01 (hybrid depth): Requires reading the existing Cypher neighborhood use case response shape carefully to map to `GraphNeighborhoodResponse`. If the shape is significantly different, mapping is complex.
- T-72-1-04 (retroactive cleanup): Must verify CASCADE behavior on `canonical_entities` DELETE — aliases, embedding_state, provisional_entity_queue rows all have FKs. Run against DB snapshot first.
- T-72-2-02 (SummaryWorker): LLM model ID routing may require config changes that affect other workers. Test in isolation first.

**Rollback strategy:**
- Wave 1 migration: Down migration is no-op; noise entities that were deleted are gone (acceptable — they were noise)
- Wave 2 schema: `evidence_snippets` field removal is backward-compatible (just remove the JOIN and field)
- Wave 3 hybrid: Removing hybrid routing → revert to depth=1 always (backward-compatible)
- Wave 4 promotion: Worker can be disabled in scheduler without data loss

---

## Deferred to PRD Session

The following enhancements require formal PRDs (in progress):

1. **Isolated node enrichment** (68% entities with 0 relations) → **PRD-0073** — synthetic relations from structured data (EODHD), new worker, new confidence sub-profile
2. **Intelligence layer** (edge opportunity scoring, contradiction visualization, temporal graph view) → **PRD-0074**
3. **Hub node quality scoring** (entity quality score to down-rank pollution nodes) → subsumed in PRD-0073 or PRD-0074
4. **Multi-hop depth > 3** — deferred; AGE Cypher path endpoint supports up to 5 hops but needs frontend pagination design
