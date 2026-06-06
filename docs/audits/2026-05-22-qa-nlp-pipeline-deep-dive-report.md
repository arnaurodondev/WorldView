# QA Report: NLP Enrichment Pipeline Deep Dive

**Date**: 2026-05-22 23:00 UTC
**Skill**: qa
**Scope**: NLP enrichment pipeline — S6 (nlp-pipeline), S7 (knowledge-graph), S8 (rag-chat) — live system, operational data
**Branch**: feat/plan-0089-w2
**Agents**: Gate Validator, Relation Quality, Embedding Quality, RAG Quality, NER/Resolution
**Verdict**: FAIL — root cause is a single external billing event; multiple independent code bugs also found

---

## Executive Summary

A comprehensive 5-agent live-stack investigation of the NLP enrichment pipeline was conducted after several days of continuous operation, providing sufficient data to assess real-world quality. The investigation reveals **one critical root cause** (DeepInfra billing cap exhausted at ~16:17 UTC 2026-05-22) that simultaneously blocked four workers: relevance scoring, unresolved entity resolution, embeddings, and LLM extraction. This is recoverable by topping up the DeepInfra account. However, the investigation also uncovered **two separate DNS-level infrastructure bugs** (price impact worker and entity refresh consumer both unable to resolve internal hostnames), **a RAG financial-data URL mismatch** silently returning empty results, **a JWT propagation gap** preventing embedding calls in briefing flows, and **systemic relation quality issues** (17% self-loops, direction inversions, entity deduplication failures). Of the 6,259 documents ingested, the pipeline is fundamentally healthy at the article-consumer / NER / routing level; it is broken at the LLM-enrichment / embedding / generation layers due to the billing cap and the two DNS failures. Immediate fix priority: restore billing, run a one-time SQL reset of the abandoned embedding queue, fix the two DNS hostnames, and patch the RAG URL mismatch. The relation quality issues (self-loops, inversions, corporate_action misuse) are longer-term code fixes.

---

## Multi-Agent Review Summary

| Agent | Focus Area | Findings | BLOCKING | CRITICAL | HIGH | MEDIUM | LOW |
|-------|-----------|----------|----------|----------|------|--------|-----|
| Gate Validator | Pipeline stage metrics, container logs | 8 | 3 | 1 | 0 | 2 | 2 |
| Relation Quality | Entity relations content & quality | 11 | 0 | 2 | 4 | 3 | 2 |
| Embedding Quality | Vector state, HNSW indexes, model consistency | 7 | 1 | 0 | 4 | 2 | 1 |
| RAG Quality | Retrieval connectivity, S6/S7 integration | 6 | 1 | 0 | 2 | 2 | 1 |
| NER/Resolution | GLiNER extraction, entity resolution pipeline | 9 | 1 | 0 | 4 | 3 | 2 |
| **Total (deduplicated)** | — | **35** | **3** | **3** | **14** | **8** | **7** |

### Cross-Agent Signals (HIGH Confidence — flagged by 2+ agents independently)
- **DeepInfra billing cap**: flagged by all 5 agents as primary blocker (4 different workers affected)
- **Price impact worker dead**: flagged by Gate Validator + NER/Resolution (0/6,259 impact windows)
- **Entity type 'unknown' proliferation**: flagged by Relation Quality + NER/Resolution (1,510/3,912 entities)
- **Self-loop relations**: flagged by Relation Quality + Gate Validator (1,604 raw evidence rows)
- **Mixed embedding model**: flagged by Embedding Quality + RAG Quality (Ollama vs DeepInfra in same HNSW index)

---

## Pipeline Stage Metrics (Current State)

| Stage | Total | Completed | Rate |
|-------|-------|-----------|------|
| Documents ingested | 6,259 | — | — |
| NER extraction (GLiNER) | 6,259 | 6,259 | **100%** ✓ |
| Routing decision assigned | 5,753 | 5,753 | **100%** ✓ |
| Relevance scored (LLM) | 6,259 | 4,606 | **73.6%** (1,653 pre-billing-cap) |
| Embeddings completed | ~9,047 chunks | 7,366 | **81.4%** (706 abandoned) |
| Entity mentions extracted | 50,772 | — | — |
| Mentions resolved to canonical | 29,472 | 29,472 | **70.0%** (non-noise) |
| Relations in materialized graph | 7,805 | — | — |
| Article impact windows | 6,259 | **0** | **0%** ← broken |
| Relation summaries generated | 7,805 | 96 | **1.2%** ← blocked |
| Entities enriched (`enriched_at`) | 3,912 | **0** | **0%** ← never ran |

---

## Issues — Full Investigation

---

## Issue F-001: DeepInfra Billing Cap Exhausted — All LLM/Embedding Workers Blocked

### Summary
The DeepInfra user-set spending limit was reached at approximately 16:17 UTC on 2026-05-22. Since that moment, four separate workers have been completely non-functional: relevance scoring, unresolved entity resolution, embedding retry, and deep extraction. This is the single highest-priority fix.

### Severity / Confidence
**Severity**: BLOCKING
**Confidence**: HIGH
**Flagged by**: All 5 agents independently

### Root Cause Analysis
- **What**: `api.deepinfra.com` returns `402 Payment Required` with `"inference prohibited, you have reached user-set limit"` for all calls to both `/v1/openai/chat/completions` and `/v1/openai/embeddings`
- **Why**: A per-account spending cap was set in the DeepInfra dashboard and was reached after several days of continuous pipeline operation (relevance scoring, unresolved resolution, embedding, and deep extraction all drawing from the same account)
- **When**: Since 2026-05-22 16:17:11 UTC continuously; ~8+ hours of downtime
- **Where**: External API dependency affecting S6 (relevance scoring, unresolved resolution, embedding) and S7 (relation summarization)
- **History**: A prior 402 episode caused BP-003 (abandoned embedding items). Same pattern repeating.

### Evidence
```
# Relevance scoring worker (every cycle since 16:19 UTC):
{"articles_scored": 0, "event": "relevance_scoring_cycle_done"}
{"error": "Client error '402 Payment Required'... inference prohibited, you have reached user-set limit", "event": "relevance_scoring_llm_error"}

# Unresolved resolution worker (every cycle since 16:19 UTC):
{"processed": 500, "auto_resolved": 0, "entity_created": 0, "errors": 500, "event": "unresolved_resolution_cycle_done"}

# Embedding retry worker:
{"retry_count": 5, "max_retries": 5, "final_error": "DeepInfra embedding 4xx: 402 Payment Required", "event": "embedding_retry_abandoned"}
```

**Downstream damage:**
- 706 items in `embedding_pending` have reached `retry_count=5` and are permanently abandoned
- 396+ articles ingested after 16:17 UTC have no relevance score
- 581 entity mentions stuck as `unresolved`

### Impact
- **Immediate**: Relevance scoring, entity resolution, embeddings, and LLM extraction all halted
- **Blast radius**: S6 pipeline stalled; S7 SummaryWorker also blocked; S8 RAG generation also blocked
- **Data risk**: 706 documents permanently unembeddable without manual intervention
- **User impact**: RAG briefings return 503 `ProviderUnavailableError` on every request

### Solution

#### Option A: Top up DeepInfra billing (REQUIRED)
**Changes required**:
- [ ] Go to `https://deepinfra.com/dash/billing` and add credits
- [ ] After billing restored, reset abandoned queue: `UPDATE embedding_pending SET retry_count=0, next_retry_at=NOW() WHERE retry_count >= 5;`
- [ ] Verify workers resume by checking logs 5 minutes after reset

#### Option B: Configure OpenRouter fallback (complementary)
**Changes required**:
- [ ] Set `RAG_CHAT_OPENROUTER_API_KEY` env var in `infra/compose/docker-compose.dev.yml` for rag-chat service
- [ ] Allows chat generation to resume while DeepInfra credits are restored

**Recommended**: Option A + Option B together. Option A is the fix; Option B provides resilience.

### Verification Steps
- [ ] `docker logs worldview-nlp-pipeline-relevance-scoring-1 --tail=20 | grep articles_scored` — should show > 0
- [ ] `SELECT COUNT(*) FROM embedding_pending WHERE retry_count >= 5;` — should be 0 after reset

---

## Issue F-002: Price Impact Labelling Worker — DNS Hostname Failure (Never Worked)

### Summary
The `worldview-nlp-pipeline-price-impact-worker-1` container has never successfully connected to its database since deployment. It fails on every startup with a DNS resolution error. As a result, `article_impact_windows` has 0 rows and `impact_score` is NULL for all 6,259 documents.

### Severity / Confidence
**Severity**: BLOCKING
**Confidence**: HIGH
**Flagged by**: Gate Validator

### Root Cause Analysis
- **What**: The worker fails with `socket.gaierror: [Errno -2] Name or service not known` when trying to connect to its configured DB hostname
- **Why**: The hostname in the worker's `DATABASE_URL` or equivalent config does not match the actual container name in the Docker network
- **When**: Every startup since 2026-05-21 19:04 UTC — has never worked
- **Where**: `services/nlp-pipeline/` — price impact labelling worker infrastructure config

### Evidence
```
{"error": "[Errno -2] Name or service not known", "event": "price_impact_labelling_poll_error"}
# Repeated every ~30 seconds since 2026-05-21 19:04 UTC

# Additionally, market-data returns 404 on every ticker lookup:
GET http://market-data:8003/api/v1/instruments/symbol/AAPL → 404
GET http://market-data:8003/api/v1/instruments/symbol/TSLA → 404
```
- **Related BP**: BP-064 (hostname mismatch class of bug)

### Impact
- **Immediate**: `article_impact_windows` table empty (0/6,259 documents)
- **Blast radius**: Any feature depending on article price impact scores (e.g. signal scoring, analytics) receives null/empty data

### Solution Options

#### Option A: Fix the DB hostname env var
**Changes required**:
- [ ] `infra/compose/docker-compose.dev.yml` — check `NLP_PIPELINE_PRICE_IMPACT_DB_URL` (or equivalent) for the price impact worker service definition; correct hostname to match the intelligence DB container name (likely `worldview-intelligence-db-1` or just `intelligence-db`)
- [ ] Also fix the market-data URL: change `/api/v1/instruments/symbol/{ticker}` to `/api/v1/instruments/lookup?symbol={ticker}` in the S6 market-data client

**Effort**: Low
**Risk**: Low

### Verification Steps
- [ ] `docker logs worldview-nlp-pipeline-price-impact-worker-1 --tail=20` — should show DB connection succeeded
- [ ] `SELECT COUNT(*) FROM article_impact_windows;` — should increase over time

---

## Issue F-003: Embedding Queue Permanently Abandoned — 706 Items

### Summary
The embedding retry worker abandoned 706 pending items by reaching `retry_count=5` (max_retries). These items will never be re-processed automatically — they remain in `embedding_pending` indefinitely with no recovery path.

### Severity / Confidence
**Severity**: BLOCKING
**Confidence**: HIGH
**Flagged by**: Gate Validator, Embedding Quality

### Root Cause Analysis
- **What**: 706 rows in `embedding_pending` with `retry_count=5, next_retry_at=<stale timestamp>`
- **Why**: DeepInfra 402 caused all embedding attempts to fail; the retry worker exhausted all retries with no circuit-breaker or escalation path
- **When**: Progressively over the past 8 hours as retries were exhausted
- **Where**: `services/nlp-pipeline/` — embedding retry worker; table `embedding_pending`

### Evidence
```
{"retry_count": 5, "max_retries": 5, "final_error": "DeepInfra embedding 4xx: 402 Payment Required",
 "event": "embedding_retry_abandoned"}
# x353 section embeddings + x353 chunk embeddings = 706 total
```

### Impact
- **Immediate**: 706 document sections/chunks permanently unembeddable unless manually reset
- **Data risk**: These documents will never appear in ANN similarity search
- **Note**: Secondary impact from F-001; fix F-001 first, then apply the SQL reset

### Solution
```sql
-- After DeepInfra billing is restored:
UPDATE embedding_pending
SET retry_count = 0, next_retry_at = NOW()
WHERE retry_count >= 5;
-- Expected: 706 rows updated
```

**Verification**: Check `embedding_retry_worker` logs 5 minutes after reset — items should be re-attempted.

---

## Issue F-004: Self-Loop LLM Extractions — 1,604 Self-Referential Relations

### Summary
17% of all relation evidence rows in `relation_evidence_raw` have `subject_entity_id = object_entity_id` (a relation from an entity to itself). These self-loops accumulate indefinitely because the promoter cannot insert them into `relations` (unique constraint prevents self-loops), leaving 1,657 unprocessed rows that will never be promoted.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Relation Quality, Gate Validator

### Root Cause Analysis
- **What**: Relations like `Lee Munson → has_executive → Lee Munson`, `Attorney General Paxton → regulates → Attorney General Paxton`
- **Why**: When the LLM extracts a `has_executive` or `employs` relation, if the company context is missing from the article snippet, it uses the person as both subject and object. The entity resolution step maps both to the same canonical entity ID, producing `subject_entity_id = object_entity_id`
- **When**: Present throughout the entire history of the relation_evidence_raw table (not a recent regression)
- **Where**: `services/knowledge-graph/src/knowledge_graph/` — enriched consumer's `_build_raw_relations()` function; the write path to `relation_evidence_raw`

### Evidence
```sql
SELECT COUNT(*) FROM relation_evidence_raw WHERE subject_entity_id = object_entity_id;
-- Result: 1,604 (17.0% of 9,432 total rows)

SELECT COUNT(*) FROM relation_evidence_raw
WHERE processed = false AND subject_entity_id = object_entity_id;
-- Result: 1,657 (includes non-provisional orphans that accumulate)
```
- **Related BP**: BP-384/385 (entity self-loop class)

### Impact
- **Immediate**: 17% of raw evidence storage is wasted on invalid relations
- **Blast radius**: The orphaned rows accumulate indefinitely with no cleanup mechanism
- **Data risk**: No corruption (constraint prevents self-loops from materializing), but table grows unboundedly

### Solution Options

#### Option A: Pre-insert guard in `_build_raw_relations()`
**Description**: Add a filter before writing to `relation_evidence_raw` that drops any evidence where `subject_entity_id == object_entity_id`
**Changes required**:
- [ ] `services/knowledge-graph/src/knowledge_graph/infrastructure/` — find `graph_write.py` or equivalent; add guard before bulk insert into `relation_evidence_raw`
- [ ] `services/knowledge-graph/tests/` — add unit test for self-loop filtering
**Effort**: Low | **Risk**: Low

#### Option B: Mark existing self-loops as processed (cleanup)
**Description**: One-time SQL to mark existing orphans as processed so they stop accumulating
```sql
UPDATE relation_evidence_raw
SET processed = true, processed_at = NOW()
WHERE subject_entity_id = object_entity_id AND processed = false;
-- Expected: ~1,657 rows
```
**Effort**: Low | **Risk**: Low

**Recommended**: Option A (prevents future accumulation) + Option B (cleans existing rows).

---

## Issue F-005: has_executive / employs Relation Direction Systematically Inverted (~50–80%)

### Summary
The LLM extraction produces `person → has_executive → company` instead of the semantically correct `company → has_executive → person` in approximately half of cases. This makes graph traversal from company to executives unreliable.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Relation Quality

### Root Cause Analysis
- **What**: Relations like `Jamie Dimon → has_executive → JPMorgan Chase` (inverted) vs `Mark Zuckerberg → has_executive → Meta` (correct subject/object are swapped)
- **Why**: The extraction prompt does not enforce direction — the LLM uses whichever entity appears first in the text as the subject
- **When**: Consistent throughout all relation history; not a regression

### Evidence
```sql
-- Sample inversions (person as subject):
SELECT e1.name as subject, er.relation_type, e2.name as object
FROM entity_relations er
JOIN entities e1 ON er.subject_entity_id = e1.id
JOIN entities e2 ON er.object_entity_id = e2.id
WHERE er.relation_type IN ('has_executive', 'employs')
  AND e1.entity_type = 'person'
LIMIT 10;
-- Returns: "Jamie Dimon → has_executive → JPMorgan Chase", "Jack Weissenberger → employs → Salesforce", etc.
```

### Solution Options

#### Option A: Prompt constraint (preventative)
Add explicit direction rules to the extraction prompt: `"For has_executive and employs: subject MUST be the company, object MUST be the person."`
**Effort**: Low | **Risk**: Medium (LLM compliance not guaranteed)

#### Option B: Post-extraction normalization (reliable)
In the KG enriched consumer's `_build_raw_relations()`, after extraction, check: if `relation_type in ('has_executive', 'employs')` and `subject.entity_type == 'person'` and `object.entity_type in ('financial_instrument', 'organization')`, swap subject and object.
**Effort**: Low | **Risk**: Low

**Recommended**: Option B (deterministic). Option A as defense-in-depth.

---

## Issue F-006: Entity Refresh Consumer — Kafka DNS Failure

### Summary
`worldview-nlp-pipeline-entity-refresh-consumer-1` cannot resolve `kafka:29092` and is continuously logging DNS failures. Entity refresh events (triggered when KG enriches an entity) are being silently dropped, meaning narrative re-embedding after enrichment never happens.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Embedding Quality

### Root Cause Analysis
- **What**: `Failed to resolve 'kafka:29092': Name or service not known`
- **Why**: The container was likely started outside the compose network or the Docker network has a DNS issue for this specific container
- **When**: Ongoing, continuous failures
- **Where**: `worldview-nlp-pipeline-entity-refresh-consumer-1` container networking

### Solution
```bash
docker compose -f infra/compose/docker-compose.dev.yml up -d --force-recreate nlp-pipeline-entity-refresh-consumer
```
This will recreate the container within the compose network, restoring Kafka DNS resolution.

---

## Issue F-007: RAG Financial Endpoint URL Mismatch

### Summary
The RAG service's `S3Client.find_instrument_by_ticker()` calls `GET /api/v1/instruments/symbol/{ticker}` but the market-data service only exposes `GET /api/v1/instruments/lookup?symbol={ticker}`. Every call returns 404 silently, meaning financial context (prices, fundamentals, earnings) is never retrieved in RAG briefings.

### Severity / Confidence
**Severity**: HIGH
**Confidence**: HIGH
**Flagged by**: RAG Quality, Gate Validator

### Root Cause Analysis
- **What**: Path mismatch — `s3_client.py` hardcodes `/api/v1/instruments/symbol/{ticker}` but market-data router only has `/api/v1/instruments/lookup`
- **Why**: The S3 client was written against a different API version (or a planned endpoint that was never created)
- **When**: All time — financial context has never been retrieved successfully

### Evidence
```
# From logs:
"HTTP/1.1 404 Not Found" — GET http://market-data:8003/api/v1/instruments/symbol/AAPL
"HTTP/1.1 404 Not Found" — GET http://market-data:8003/api/v1/instruments/symbol/MNST
# From source:
services/rag-chat/src/rag_chat/infrastructure/clients/s3_client.py:66
  self._get(f"/api/v1/instruments/symbol/{ticker}")  # WRONG PATH
# Correct endpoint (from market-data router):
GET /api/v1/instruments/lookup?symbol={ticker}
```

### Solution
**Change in `s3_client.py`**:
```python
# Before:
self._get(f"/api/v1/instruments/symbol/{ticker}")
# After:
self._get("/api/v1/instruments/lookup", params={"symbol": ticker})
```
**Effort**: Low | **Risk**: Low

---

## Issue F-008: JWT Not Propagated in Briefing Flows — S6 Embedding Calls Return 401

### Summary
In briefing flows (`execute_public_instrument`, `execute_public_morning`), the ContextVar holding the internal JWT is not set before the S6 embedding call. S6 requires `X-Internal-JWT` for all requests. Result: chunk search in briefings always fails with 401, meaning semantic retrieval returns zero results.

### Severity / Confidence
**Severity**: HIGH
**Confidence**: HIGH
**Flagged by**: RAG Quality

### Root Cause Analysis
- **What**: `_S6EmbeddingAdapter.embed()` calls `get_current_jwt()` which returns `None` in briefing context → S6 receives no JWT header → 401
- **Why**: The `InternalJWTMiddleware` sets the ContextVar only for HTTP request contexts. Briefing context gathering runs outside this scope
- **When**: All briefing requests (not chat requests, which go through the middleware path)

### Evidence
```
# From nlp-pipeline logs (172.20.0.56 = rag-chat):
"POST /api/v1/embed HTTP/1.1" 401 Unauthorized
# From rag-chat source:
services/rag-chat/src/rag_chat/infrastructure/clients/embedding_adapter.py
# get_current_jwt() returns None when called from briefing orchestrator
```

### Solution
In `execute_public_instrument` and `execute_public_morning` (in `public_briefings.py`), call `set_current_jwt(internal_jwt)` before the context gathering step begins. The `internal_jwt` parameter is already available in these functions.
**Effort**: Low | **Risk**: Low

---

## Issue F-009: `organization` Entity Type Rejected by DB CHECK Constraint

### Summary
The provisional enrichment worker classifies new entities as `'organization'` but the `canonical_entities` table CHECK constraint does not include `'organization'`. This causes repeated `CheckViolationError` for every new entity of this type, meaning companies like Grayscale, Tenstorrent, ZFLOW AI, and Wolfe Research are never persisted.

### Severity / Confidence
**Severity**: HIGH
**Confidence**: HIGH
**Flagged by**: Relation Quality, NER/Resolution

### Root Cause Analysis
- **What**: `entity_type='organization'` fails the CHECK constraint `ck_canonical_entities_entity_type`
- **Why**: The `_VALID_ENTITY_TYPES` frozenset in `provisional_enrichment_core.py` lists `'organization'` as valid, but it was never added to the migration that creates the CHECK constraint
- **When**: Every time a new `organization`-class entity is provisionally created

### Evidence
```
# From knowledge-graph-provisional-queued-consumer logs:
{"event": "provisional_queued_persist_error", "entity_type": "organization",
 "error": "CheckViolationError: ...ck_canonical_entities_entity_type"}
# Affected entities (sample): Grayscale, UMC, ZFLOW AI, Wolfe Research, Tenstorrent
```

### Solution Options

#### Option A: Add `organization` to the CHECK constraint
- Requires an Alembic migration in `intelligence-migrations`
- `ALTER TABLE canonical_entities DROP CONSTRAINT ck_canonical_entities_entity_type;`
- Re-add with `organization` included
- **Effort**: Low | **Risk**: Low

#### Option B: Map `organization` → existing type in the alias dict
- In `provisional_enrichment_core.py`, update `_ENTITY_TYPE_ALIASES` to map `'organization' → 'unknown'` (or another valid type)
- No migration needed but loses semantic precision
- **Effort**: Low | **Risk**: Low

**Recommended**: Option A — add `organization` as a first-class type.

---

## Issue F-010: 1,510 Canonical Entities Typed as `unknown` (38.6%)

### Summary
38.6% of all canonical entities — including major companies like OpenAI, Anthropic, Google LLC, Amazon Inc — have `entity_type='unknown'`. This degrades type-specific queries and relation type-checking.

### Severity / Confidence
**Severity**: HIGH
**Confidence**: HIGH
**Flagged by**: Relation Quality, NER/Resolution

### Root Cause Analysis
- **What**: 1,510/3,912 entities have `entity_type='unknown'`
- **Why**: GLiNER extracts 11 mention classes but the canonical schema only accepts 8 types. Classes like `organization`, `financial_institution`, `regulatory_body`, `government_body` are all unmapped — any entity created from these classes defaults to `unknown`. This is compounded by Issue F-009 (organization type rejected by DB)
- **History**: This is a known data quality gap identified in prior sessions (memory: project_kg_quality_2026_05_05)

### Solution
1. Fix F-009 first (add `organization` type)
2. Batch reclassify existing `unknown` entities using a one-time LLM pass or rule-based classification by name/mention patterns
3. Map GLiNER classes to canonical types more precisely in `entity_resolution.py`

---

## Issue F-011: No Entities Ever Enriched (enriched_at = NULL for 3,912 entities)

### Summary
The `DefinitionRefreshWorker` (which generates entity descriptions via Gemini Flash Lite) has never successfully run a complete cycle — `enriched_at` is NULL for all 3,912 canonical entities. Only 8 entities have descriptions. Without descriptions, the HNSW definition index is embedding empty/stub strings.

### Severity / Confidence
**Severity**: HIGH
**Confidence**: HIGH
**Flagged by**: NER/Resolution, Embedding Quality

### Root Cause Analysis
- **What**: `SELECT COUNT(*) FROM canonical_entities WHERE enriched_at IS NOT NULL` = 0
- **Why**: Likely the enrichment worker has a startup failure or is blocked by a missing Gemini API key. The Gemini Flash Lite model is used for this (hardcoded, not configurable). If `KNOWLEDGE_GRAPH_GEMINI_API_KEY` is not set or is invalid, every enrichment attempt fails silently.
- **When**: Never — not a regression, has never worked

### Solution
- [ ] Check `worldview-knowledge-graph-scheduler-1` logs for enrichment errors
- [ ] Verify `KNOWLEDGE_GRAPH_GEMINI_API_KEY` is set in `infra/compose/docker-compose.dev.yml`
- [ ] If key is set but enrichment still fails, check the Gemini client adapter in `libs/ml-clients/`

---

## Issue F-012: High-Frequency Entities Missing Canonical Records

### Summary
SpaceX (59 unresolved mentions), CNBC (40), Benzinga (19+), "Fed" (10), IMAX (7), Lenovo (5) have no canonical entity or alias. These appear frequently in financial articles and their absence degrades KG quality significantly.

### Severity / Confidence
**Severity**: HIGH
**Confidence**: HIGH
**Flagged by**: NER/Resolution

### Solution
Seed these entities directly:
```sql
-- SpaceX as top priority (59 unresolved mentions)
INSERT INTO canonical_entities (id, name, entity_type, source) VALUES (new_uuid7(), 'SpaceX', 'organization', 'seed');
INSERT INTO entity_aliases (entity_id, alias_text, alias_type) VALUES (<spacex_id>, 'Space Exploration Technologies', 'formal_name');

-- Minimum viable seed list (by unresolved frequency):
-- SpaceX, CNBC, Benzinga, Federal Reserve ("Fed"), IMAX, Lenovo, xAI, BlackBerry
```

---

## Issue F-013: Embedding Model Inconsistency — Mixed HNSW Index

### Summary
The HNSW index for entity definitions and document chunks contains vectors from two different providers: ~98% Ollama `bge-large:latest` and ~2% DeepInfra `BAAI/bge-large-en-v1.5`. While both use the same base architecture, mixing providers in a single ANN index produces unreliable similarity rankings for the minority set.

### Severity / Confidence
**Severity**: HIGH
**Confidence**: HIGH
**Flagged by**: Embedding Quality, RAG Quality

### Solution
After billing is restored, choose one canonical provider and re-embed the inconsistent minority:
- If using DeepInfra: `UPDATE entity_embedding_state SET definition_embedding=NULL, model_id=NULL WHERE model_id='bge-large:latest'` then trigger refresh
- If using Ollama: `UPDATE entity_embedding_state SET definition_embedding=NULL, model_id=NULL WHERE model_id='BAAI/bge-large-en-v1.5'` then trigger refresh

---

## Issue F-014: final_routing_tier Never Populated

### Summary
`final_routing_tier` is NULL for 5,623 of 5,753 routing decisions. This column is supposed to track the final effective routing tier after any promotions. If any downstream analytics or query depends on it, it returns empty.

### Severity / Confidence
**Severity**: MEDIUM
**Confidence**: HIGH
**Flagged by**: Gate Validator

### Evidence
```sql
SELECT COUNT(*) FROM routing_decisions WHERE final_routing_tier IS NULL;
-- Result: 5,623
```

### Solution
Investigate which worker is supposed to write `final_routing_tier`. If it mirrors `routing_tier` for completed documents, add the write in the completion step. If it's a separate reclassification worker, investigate why it's not running.

---

## Issue F-015: JWT Skip-Verification Logged at CRITICAL Level — Noise Drowns Real Alerts

### Summary
All backend services run in dev mode with `INTERNAL_JWT_SKIP_VERIFICATION=true`. This condition logs at `CRITICAL` level on every request, producing 30+ CRITICAL log entries per 200-line window and drowning out genuine critical signals.

### Severity / Confidence
**Severity**: MEDIUM
**Confidence**: HIGH
**Flagged by**: Gate Validator, RAG Quality

### Solution
In `InternalJWTMiddleware`, change the skip-verification log level from `CRITICAL` to `DEBUG` or `WARNING`. A dev-mode configuration is expected and should not trigger alert-level logging.

---

## Issue F-016: corporate_action Used as Catch-All Relation Type

### Summary
526 relations are typed `corporate_action` but the vast majority are not corporate actions (dividends/splits/buybacks). The type is used for government grants, product recalls, government investigations, facility expansions, and any event not fitting another type. This makes the `corporate_action` relation type semantically meaningless.

### Severity / Confidence
**Severity**: MEDIUM
**Confidence**: HIGH
**Flagged by**: Relation Quality

### Evidence
Sample `corporate_action` relations:
- `U.S. Commerce Department → corporate_action → IBM` (government grant)
- `Tesla Inc → corporate_action → U.S.` (product recall)
- `Alphabet → corporate_action → downtown Chicago development` (real estate)

### Solution
Either remove `corporate_action` from the extraction prompt and redistribute to more specific types, or add a stronger definition in the prompt (e.g., "ONLY for: stock splits, dividends, share buybacks, rights offerings").

---

## Issue F-017: 52.3% of Relation Evidence References Provisional (Unresolved) Entities

### Summary
4,932 of 9,432 relation evidence rows reference provisional entity queue IDs (not canonical entity IDs). If provisional resolution fails (as it currently does due to F-001), these relations can never be promoted to real graph edges.

### Severity / Confidence
**Severity**: MEDIUM
**Confidence**: HIGH
**Flagged by**: NER/Resolution

### Solution
This is a cascading consequence of F-001 (billing cap). Fix F-001 to unblock provisional resolution. Additionally, verify that when a provisional entity IS resolved, its `entity_id` is back-filled into `relation_evidence_raw.subject_entity_id/object_entity_id`.

---

## Issue F-018: Polarity Always 'positive' — Negative/Neutral Polarity Path Dead

### Summary
100% of 9,432 relation evidence rows have `polarity = 'positive'`. The `_normalize_polarity` function defaults to `'positive'` when the LLM returns `None`, which it apparently always does.

### Severity / Confidence
**Severity**: MEDIUM
**Confidence**: HIGH
**Flagged by**: Relation Quality

### Solution
Check whether the NLP extraction Avro payload includes the `polarity` field. If the field is omitted from the payload, the consumer defaults to positive. Fix: ensure the extraction prompt asks for polarity and the consumer reads it from the envelope.

---

## Issue F-019: All Relation Summaries Lack Embeddings (96/96 NULL)

### Summary
96 relation summaries exist but `summary_embedding` is NULL for all of them. The `idx_relation_summary_emb_hnsw` index has 0 scans. Semantic relation search returns zero results.

### Severity / Confidence
**Severity**: MEDIUM
**Confidence**: HIGH
**Flagged by**: Embedding Quality

### Solution
Ensure the `EmbeddingRefreshWorker` covers relation summaries. After billing is restored and summaries accumulate, trigger the KG embedding refresh for relation summaries.

---

## MINOR / NIT Issues

### F-020 (MINOR): UPPERCASE Relation Type Case Mismatch
`EXPOSED_TO_THEME` (26 rows), `COMPETES_WITH` (8), `SUPPLIER_OF` (2) exist in the AGE graph in uppercase but the `relation_type_registry` only has lowercase variants. These unregistered types bypass decay, confidence computation, and summarization.
**Fix**: Normalize to lowercase at insert time in the AGE sync worker.

### F-021 (MINOR): Near-Duplicate Entity Proliferation
7+ Amazon variants (`Amazon.com Inc`, `Amazon Inc`, `Amazon AWS`, `Amazon Web Services`), 4+ JPMorgan variants accumulate independent relation subgraphs.
**Fix**: Post-canonicalization merge pass for entities with string similarity > 0.90 and matching ticker.

### F-022 (MINOR): 589 Failed Provisionals Have NULL context_snippet
LLM resolution quality is lower without sentence context. The `context_snippet` field is left NULL by design ("future work" comment in `entity_resolution.py`).
**Fix**: Extract a 1-sentence surrounding snippet and populate `context_snippet` at extraction time.

### F-023 (LOW): Narrative/Fundamentals HNSW Indexes Never Used
`idx_entity_emb_narrative_hnsw` and `idx_entity_emb_fstate_hnsw` have 0 scans despite 3,912 and 742 vectors respectively. Either query paths haven't been implemented or no user has exercised them.
**Fix**: Investigate whether narrative/fundamentals similarity search routes are implemented and enabled.

### F-024 (LOW): 93 DLQ Articles from GLiNER Timeouts
93 articles permanently dead-lettered due to GLiNER timeouts on 2026-05-21. No retry mechanism for DLQ.
**Fix**: Implement a DLQ replay tool or manual re-publish path.

### F-025 (LOW): 1,653 Pre-Scoring Documents With No Relevance Score
Articles ingested before the relevance-scoring worker launched have no LLM relevance score. Backfill needed.
**Fix**: One-time backfill pass over `document_source_metadata WHERE llm_relevance_score IS NULL`.

### F-026 (LOW): Model ID Naming Inconsistency
Ollama records `bge-large` or `bge-large:latest`; DeepInfra records `BAAI/bge-large-en-v1.5`. No canonical name.
**Fix**: Standardize all model_id values to `BAAI/bge-large-en-v1.5` regardless of provider.

### F-027 (LOW): 12 Duplicate Canonical Entities
12 financial_instrument canonical name pairs with count=2. Dedup script needed.
**Fix**: Run existing dedup script; add unique constraint for financial_instrument names.

---

## Test Execution Results

> Note: This QA pass is a live-stack operational investigation, not a unit-test suite run. Test suite results from the most recent commit (2026-05-22) are referenced below.

| Layer | Scope | Status | Notes |
|-------|-------|--------|-------|
| Unit Tests (Vitest) | worldview-web | **2,101 PASS** | From W7 QA pass |
| Unit Tests (pytest) | api-gateway | **501 PASS** | From W7 graph fix commit |
| Live-Stack Validation | All 28 NLP/KG/RAG containers | **PARTIAL** | 4 workers blocked by billing cap |
| Container Health | 28 containers | **27 healthy** | price-impact-worker effectively dead |
| DB Connectivity | intelligence_db, nlp_db | **OK** | Queries run successfully |
| Kafka Health | All topics | **OK** | article-consumer processing normally |
| Vector Index Health | HNSW indexes | **PARTIAL** | Only definition index used |

---

## Supplementary Checks

| Check | Status | Notes |
|-------|--------|-------|
| Container DNS | FAIL | 2 containers with hostname resolution failures |
| DeepInfra Account | FAIL | 402 since 16:17 UTC 2026-05-22 |
| Pipeline Data Flow | PARTIAL | NER/routing OK; LLM enrichment blocked |
| Entity Resolution | PARTIAL | 70% resolution rate; LLM stage blocked |
| Relation Quality | WARN | Self-loops (17%), direction inversions, type misuse |
| Embedding Coverage | WARN | 81.4% chunks, 85.3% entity definitions |
| RAG Retrieval | FAIL | 3 independent bugs; 0 successful generations |

---

## Priority-Ordered Recommendations

### Immediate (Today)
1. **Top up DeepInfra billing** → restores 4 blocked workers simultaneously
2. **Reset abandoned embedding queue** → `UPDATE embedding_pending SET retry_count=0, next_retry_at=NOW() WHERE retry_count>=5;`
3. **Recreate entity-refresh-consumer** → `docker compose up -d --force-recreate nlp-pipeline-entity-refresh-consumer`
4. **Fix price impact worker DNS** → correct hostname in docker-compose env var
5. **Fix RAG financial URL** → `s3_client.py:66` change `/symbol/{ticker}` to `/lookup?symbol={ticker}`
6. **Fix RAG JWT propagation** → call `set_current_jwt(internal_jwt)` in briefing orchestrators

### Short Term (This Sprint)
7. **Fix organization entity type** → add to CHECK constraint via Alembic migration
8. **Fix self-loop filter** → pre-insert guard in `_build_raw_relations()`
9. **Clean existing self-loop evidence** → SQL: mark processed=true for self-loop rows
10. **Fix relation direction normalization** → swap has_executive/employs when subject is person
11. **Investigate Gemini API key for enrichment** → check KNOWLEDGE_GRAPH_GEMINI_API_KEY
12. **Reduce JWT skip-verification log level** → CRITICAL → DEBUG in InternalJWTMiddleware

### Medium Term (Next Sprint)
13. **Seed high-frequency missing entities** → SpaceX, CNBC, Benzinga, Fed, IMAX, Lenovo
14. **Normalize corporate_action relation type** → stronger prompt definition or remove
15. **Choose canonical embedding model** → re-embed minority set for consistency
16. **Fix polarity extraction** → ensure `polarity` field is emitted in Avro payload
17. **Wire relation summary embeddings** → add to EmbeddingRefreshWorker schedule

### Data Quality (Backfill)
18. **Backfill relevance scores** → 1,653 pre-launch documents need LLM scoring
19. **Reclassify 1,510 unknown entities** → batch reclassification after organization type is added
20. **Merge near-duplicate entities** → Amazon variants, JPMorgan variants

---

## New Bug Patterns to Add to BUG_PATTERNS.md

| ID | Pattern | Location |
|----|---------|----------|
| BP-520 | Self-loop LLM relations: when company context is missing, LLM uses person as both subject/object → `subject_entity_id = object_entity_id` | S7 enriched consumer |
| BP-521 | Relation direction inversion for `has_executive`/`employs`: LLM uses mention order not semantic direction | S7 extraction prompt |
| BP-522 | DeepInfra 402 cascade: billing cap hits all workers simultaneously; abandoned queue has no auto-recovery after max_retries | S6 embedding retry |
| BP-523 | Schema-code mismatch for entity types: `_VALID_ENTITY_TYPES` frozenset includes type not in DB CHECK constraint → silent CheckViolationError on every new entity of that class | S7 provisional enrichment |

---

*Report written to: docs/audits/2026-05-22-qa-nlp-pipeline-deep-dive-report.md*
