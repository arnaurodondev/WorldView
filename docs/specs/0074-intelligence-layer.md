# PRD-0074 — Intelligence Layer

> **Version**: 1.0 | **Date**: 2026-05-05
> **Status**: Draft | **Owner**: Arnau Rodon
> **Affected Services**: S7 (knowledge-graph), S8 (rag-chat), intelligence-migrations, S9 (api-gateway), worldview-web

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Target Users](#2-target-users)
3. [Requirements](#3-requirements)
4. [Out of Scope](#4-out-of-scope)
5. [Affected Services](#5-affected-services)
6. [API Changes](#6-api-changes)
7. [Kafka Events](#7-kafka-events)
8. [Database Changes](#8-database-changes)
9. [Domain Model Changes](#9-domain-model-changes)
10. [Data Flow](#10-data-flow)
11. [Architecture Decisions](#11-architecture-decisions)
12. [Security Analysis](#12-security-analysis)
13. [Failure Modes](#13-failure-modes)
14. [Scalability](#14-scalability)
15. [Test Strategy](#15-test-strategy)
16. [Migration Plan](#16-migration-plan)
17. [Observability](#17-observability)
18. [Open Questions](#18-open-questions)
19. [Estimation](#19-estimation)

---

## 1. Problem Statement

The knowledge graph's intelligence page is a basic graph viewer: nodes, edges, and a flat sidebar. It doesn't surface the reasoning behind confidence scores, doesn't let analysts understand *why* two entities are connected, and doesn't help users discover non-obvious multi-hop relationships.

Specific gaps:

| Gap | Impact |
|-----|--------|
| No LLM-generated entity narratives exposed in UI | Users can't understand what the platform knows about an entity |
| No narrative version history | Can't track how entity understanding evolved as evidence accumulated |
| `ConfidenceComponents` (support/corroboration/contradiction) computed but never exposed | Users see a confidence number with no way to interrogate it |
| 4 unused schema elements (`valid_from`/`valid_to`, `relation_period_type`, contra tracking columns, `summary_embedding`) | Schema debt — columns designed, never activated |
| Evidence promotion gap: `relation_evidence_raw` has 2,802 rows; `relation_evidence` has 0 | Monthly immutable partitions never populated; evidence archival broken |
| Source diversity undercount: corroboration formula counts `(source_type, source_name)` pairs but `source_name` is NULL | Corroboration bonus systematically undercomputed for all relations |
| No pre-computed opportunity paths | Multi-hop discoveries unavailable to users |
| No entity-scoped Q&A | Users can't ask questions about a specific entity |
| Intelligence page 2-column layout conflates graph (interactive), tabular data (relations/evidence), and card data (narrative/metrics) | UX confusion; data density too low for professional use |

---

## 2. Target Users

- **Research analyst**: Wants to understand what the platform knows about Apple Inc., who its suppliers are, how confident those relations are, and what news drove that confidence. Needs narratives, confidence breakdowns, and evidence attribution.
- **Portfolio manager**: Wants to discover hidden supply-chain connections between holdings. Needs pre-computed multi-hop opportunity paths with LLM explanations.
- **Data quality operator**: Wants to see where entity understanding is weak (low `health_score`, stale evidence, high contradiction scores). Needs confidence trend + source distribution.

---

## 3. Requirements

### Functional

| ID | Requirement |
|----|-------------|
| FR-1 | Intelligence page MUST display the current LLM-generated narrative for the anchor entity |
| FR-2 | Narrative versions MUST be stored with `version_id`, `model_id`, `generation_reason`, `input_snapshot`, and `generated_at` |
| FR-3 | Users MUST be able to view the full narrative version history (timestamps + generation reasons) |
| FR-4 | `GET /api/v1/entities/{id}/graph` MUST support `?depth=N` (N=1–5) via hybrid relational/AGE strategy (PLAN-0072 T-72-3-01) |
| FR-5 | Clicking a node in the graph panel MUST synchronize the center Intelligence Panel to that node's edges and evidence |
| FR-6 | Relations tab MUST show `support`, `corroboration`, `contradiction` per relation (from `ConfidenceComponents`) |
| FR-7 | Evidence snippets MUST include `source_type`, `source_name`, and `published_at` |
| FR-8 | Opportunity paths MUST be displayed with `hop_count`, `composite_score`, and LLM explanation (lazy-cached) |
| FR-9 | Entity Q&A chat MUST be available at the bottom of the intelligence page (full-width, collapsible) |
| FR-10 | Entity `health_score` (0–1 composite) MUST be computed and displayed in the entity header |
| FR-11 | Source distribution (breakdown by `source_type` + `source_name`) MUST be displayed in the entity sidebar |
| FR-12 | Confidence trend (30/90-day time series of mean relation confidence) MUST be displayed as a sparkline |
| FR-13 | `valid_from` / `valid_to` on `relations` MUST be populated from evidence metadata |
| FR-14 | `strongest_contra_score`, `contra_count_by_type`, `latest_contra_at` on `relations` MUST be computed and populated by `ContradictionBatchWorker` |
| FR-15 | `summary_embedding VECTOR(1024)` on `relation_summaries` MUST be populated by `SummaryWorker` after text generation |
| FR-16 | `source_name` and `source_type` MUST be stored on `relation_evidence_raw` (fix for source diversity undercount) |
| FR-17 | `PathInsightWorker` MUST support horizontal scaling via `docker compose up --scale` |
| FR-18 | Narrative generation MUST be idempotent (same `entity_id` + same `input_snapshot` → no duplicate version inserted) |

### Non-Functional

| ID | Requirement |
|----|-------------|
| NFR-1 | `GET /api/v1/entities/{id}/intelligence` MUST respond in <500ms P95 (pre-computed fields, no live LLM) |
| NFR-2 | `GET /api/v1/entities/{id}/paths` MUST respond in <200ms (indexed SELECT from `path_insights`) |
| NFR-3 | Narrative generation MUST NOT block the hot path — runs as async background worker |
| NFR-4 | Entity chat MUST stream responses via SSE (same as existing S8 chat endpoint) |
| NFR-5 | `PathInsightWorker` nightly run MUST complete within 4 hours for up to 2,000 hub entities at N=4 worker instances |

---

## 4. Out of Scope

- Cross-entity comparison side-by-side → future PRD
- Watchlist / entity bookmarking → future PRD
- Export entity knowledge to PDF → future PRD
- Multi-entity chat (comparing two specific entities beyond current RAG) → PLAN-0067 full tool catalog
- Entity merging / splitting (admin graph operations) → future PRD
- Evidence promotion worker (EvidencePromotionWorker 13I) → covered in PLAN-0072 Wave 4

---

## 5. Affected Services

| Service | Change Type | Summary |
|---------|-------------|---------|
| intelligence-migrations | DDL | Migrations **0028–0033**: `entity_narrative_versions`, `path_insight_jobs`, `path_insights`, activate unused schema elements, `source_name`/`source_type` on `relation_evidence_raw`, `path_templates` seed |
| S7 knowledge-graph | New workers + API changes | `NarrativeGenerationWorker` (13D-3), `PathInsightWorker` + seeder, contra column activation, `summary_embedding` population, `ConfidenceComponents` in API response, `source_name` population at insert |
| S8 rag-chat | New endpoint | `POST /api/v1/chat/entity-context` — entity-scoped RAG with pre-loaded entity context |
| S9 api-gateway | New proxy routes + schemas | 4 new entity intelligence endpoints + entity chat proxy |
| worldview-web | New page redesign | 3-column intelligence page with synchronized graph↔center panel + full-width chat |

---

## 6. API Changes

### 6.1 GET /api/v1/entities/{entity_id}/intelligence

Full entity intelligence summary. All fields pre-computed from DB — no live LLM call on this path.

- **Auth**: required (Bearer JWT)
- **Path params**:
  | Param | Type | Required | Description |
  |-------|------|----------|-------------|
  | entity_id | UUID | yes | Canonical entity ID |
- **Response (200)**:
  | Field | Type | Description |
  |-------|------|-------------|
  | entity_id | UUID | |
  | canonical_name | string | |
  | entity_type | string | |
  | health_score | float \| null | 0.0–1.0 composite: `(data_completeness×0.4) + (evidence_freshness×0.3) + (min(relation_count/20,1)×0.3)` |
  | data_completeness | float \| null | From `canonical_entities.data_completeness` (PRD-0073) |
  | enriched_at | ISO-8601 \| null | From `canonical_entities.enriched_at` |
  | current_narrative | NarrativeVersionPublic \| null | See §9.1 |
  | confidence_breakdown | ConfidenceBreakdownPublic | Mean support/corroboration/contradiction across all active relations |
  | source_distribution | SourceSharePublic[] | Breakdown by `(source_type, source_name)` — top 10 by evidence_count |
  | confidence_trend | ConfidenceTrendPoint[] | 90-day daily series of `mean(confidence_score)` across relations |
  | key_metrics | object | Entity-type-specific from `metadata JSONB` (sector, market_cap, P/E for company; role, org for person; etc.) |
- **Error responses**: 401, 403, 404 (entity not found), 422 (invalid UUID)
- **Rate limit**: 300 req/min authenticated

### 6.2 GET /api/v1/entities/{entity_id}/paths

Pre-computed opportunity paths from `path_insights` table.

- **Auth**: required
- **Query params**:
  | Param | Type | Default | Validation |
  |-------|------|---------|------------|
  | limit | int | 10 | 1–50 |
  | min_score | float | 0.3 | 0.0–1.0 |
  | min_hops | int | 2 | 2–5 |
  | max_hops | int | 5 | 2–5 |
- **Response (200)**:
  | Field | Type | Description |
  |-------|------|-------------|
  | entity_id | UUID | Anchor entity |
  | paths | PathInsightPublic[] | Sorted by `composite_score DESC` |
  | computed_at | ISO-8601 \| null | When paths were last computed for this entity |
- **PathInsightPublic fields**:
  | Field | Type | Description |
  |-------|------|-------------|
  | insight_id | UUID | |
  | hop_count | int | 2–5 |
  | harmonic_score | float | harmonic_mean of edge confidences |
  | diversity_score | float | Entity-type diversity reward |
  | surprise_score | float | Path rarity metric |
  | template_match | string \| null | Matched manufacturing-chain template name |
  | composite_score | float | Final ranking score |
  | path_nodes | PathNodePublic[] | `[{entity_id, name, entity_type}]` |
  | path_edges | PathEdgePublic[] | `[{relation_type, confidence}]` — len = len(path_nodes)-1 |
  | llm_explanation | string \| null | Multi-sentence explanation; null if not yet generated |
  | explanation_pending | bool | true if async explanation generation is in flight |
  | computed_at | ISO-8601 | |
- **Error responses**: 401, 403, 404, 422

### 6.3 GET /api/v1/entities/{entity_id}/narratives

Narrative version history.

- **Auth**: required
- **Query params**: `limit` (default 20, max 100), `cursor` (opaque pagination cursor)
- **Response (200)**:
  | Field | Type | Description |
  |-------|------|-------------|
  | entity_id | UUID | |
  | versions | NarrativeVersionPublic[] | Sorted `generated_at DESC` |
  | next_cursor | string \| null | For pagination |
- **NarrativeVersionPublic**:
  | Field | Type | Description |
  |-------|------|-------------|
  | version_id | UUID | |
  | is_current | bool | |
  | model_id | string | Which LLM or `template-v1` |
  | generation_reason | string | INITIAL \| PERIODIC_REFRESH \| DATA_UPDATE \| EVIDENCE_SURGE \| MANUAL_TRIGGER |
  | generated_at | ISO-8601 | |
  | word_count | int \| null | |
  | narrative_text | string | Full narrative text |
- **Error responses**: 401, 403, 404, 422

### 6.4 POST /api/v1/entities/{entity_id}/narratives/generate

Trigger manual narrative regeneration.

- **Auth**: required (any authenticated user; rate-limited)
- **Request body**: empty (no body required)
- **Response (202)**:
  | Field | Type | Description |
  |-------|------|-------------|
  | message | string | "Narrative generation queued" |
  | entity_id | UUID | |
- **Rate limit**: 1 req/hour/entity/user (enforced via Valkey key `narrative_gen:{tenant_id}:{entity_id}`)
- **Error responses**: 401, 403, 404, 422, 429 (rate limit exceeded with `Retry-After` header)

### 6.5 POST /api/v1/chat/entity-context

Entity-scoped Q&A — pre-loads entity context into the RAG pipeline.

- **Auth**: required
- **Request body**:
  | Field | Type | Required | Default | Validation | Description |
  |-------|------|----------|---------|------------|-------------|
  | entity_id | UUID | yes | — | valid UUID | Anchor entity for context loading |
  | question | string | yes | — | 1–2000 chars, no HTML | User question |
  | conversation_id | UUID | no | null | UUIDv7 | For multi-turn continuity |
  | include_graph_context | bool | no | true | | Include top relations in system prompt |
- **Response**: SSE stream — same `data: {...}` format as `POST /api/v1/chat`
  | Event field | Type | Description |
  |-------------|------|-------------|
  | type | string | `token` \| `done` \| `error` |
  | content | string | Streamed token text (type=token) |
  | conversation_id | UUID | Echoed for multi-turn (type=done) |
  | sources | SourceRef[] | Articles cited (type=done) |
- **Error responses**: 400 (empty question), 401, 403, 404 (entity not found), 422, 429

### 6.6 GET /api/v1/entities/{entity_id}/graph (enhancement)

Already implemented. PRD-0074 adds query params:

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| confidence_breakdown | bool | false | If true, include `ConfidenceComponents` fields in each `RelationResponse` |
| focus_node | UUID | null | If provided, response metadata includes that node's edges pre-filtered for panel synchronization |

New fields added to `RelationResponse` when `confidence_breakdown=true`:
| Field | Type | Description |
|-------|------|-------------|
| support | float \| null | From `confidence_components JSONB` |
| corroboration | float \| null | |
| contradiction | float \| null | |
| valid_from | ISO-8601 \| null | |
| valid_to | ISO-8601 \| null | |
| relation_period_type | string \| null | POINT_IN_TIME \| ONGOING \| HISTORICAL |
| strongest_contra_score | float | |
| latest_contra_at | ISO-8601 \| null | |

---

## 7. Kafka Events

### entity.narrative.generated.v1

- **Topic**: `entity.narrative.generated.v1`
- **Partition key**: `entity_id`
- **Retention**: 7 days
- **Cleanup policy**: delete
- **Producers**: S7 `NarrativeGenerationWorker` (13D-3)
- **Consumers**: S7 `NarrativeRefreshWorker` (13D-2) — triggers re-embedding with new narrative text

**Avro schema**:
| Field | Type | Default | Nullable | Description |
|-------|------|---------|----------|-------------|
| event_id | string | — | no | UUIDv7 |
| event_type | string | entity.narrative.generated.v1 | no | |
| schema_version | int | 1 | no | |
| occurred_at | string | — | no | ISO-8601 UTC |
| entity_id | string | — | no | UUIDv7 of the canonical entity |
| version_id | string | — | no | UUIDv7 of the new `entity_narrative_versions` row |
| generation_reason | string | — | no | INITIAL \| PERIODIC_REFRESH \| DATA_UPDATE \| EVIDENCE_SURGE \| MANUAL_TRIGGER |
| model_id | string | — | no | LLM model used, e.g. `Qwen/Qwen3-235B-A22B-Instruct-2507` |
| word_count | int | 0 | yes | Narrative word count |

---

## 8. Database Changes

All migrations owned by `intelligence-migrations`. S7 sets `ALEMBIC_ENABLED=false`.

### 8.1 NEW TABLE: entity_narrative_versions

| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| version_id | UUID | no | `new_uuid7()` | PK |
| entity_id | UUID | no | — | FK `canonical_entities(entity_id)` ON DELETE CASCADE |
| tenant_id | UUID | yes | NULL | NULL = shared platform narrative (visible to all tenants); non-null = tenant-scoped enrichment overlay (tenant-generated only) |
| narrative_text | TEXT | no | — | CHECK `length(narrative_text) BETWEEN 50 AND 10000` |
| model_id | TEXT | no | — | e.g. `Qwen/Qwen3-235B-A22B-Instruct-2507` \| `template-v1` |
| generation_reason | TEXT | no | — | CHECK IN ('INITIAL','PERIODIC_REFRESH','DATA_UPDATE','EVIDENCE_SURGE','MANUAL_TRIGGER') |
| input_snapshot | JSONB | yes | NULL | Fingerprint of all data fed to LLM (for idempotency) |
| generated_at | TIMESTAMPTZ | no | `NOW()` | |
| is_current | BOOLEAN | no | false | |
| word_count | INT | yes | NULL | |
| quality_score | FLOAT | yes | NULL | 0.0–1.0 LLM self-scored |

**Indexes**:
- `UNIQUE (entity_id, is_current) WHERE is_current = TRUE` — at most 1 current version per entity
- `(entity_id, generated_at DESC)` — version history pagination

### 8.2 MODIFY TABLE: canonical_entities

Add columns:
| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| current_narrative_version_id | UUID | yes | NULL | FK `entity_narrative_versions(version_id)` ON DELETE SET NULL |
| health_score | FLOAT | yes | NULL | Computed by `NarrativeGenerationWorker` or health recompute task; CHECK `health_score BETWEEN 0.0 AND 1.0` |

### 8.3 NEW TABLE: path_insight_jobs (work queue)

| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| job_id | UUID | no | `new_uuid7()` | PK |
| entity_id | UUID | no | — | FK `canonical_entities(entity_id)` ON DELETE CASCADE |
| tenant_id | UUID | yes | NULL | NULL = platform-level path job; non-null = tenant-scoped job |
| status | TEXT | no | `'pending'` | CHECK IN ('pending','running','done','failed') |
| claimed_by | TEXT | yes | NULL | Worker instance UUID (set at claim time) |
| claimed_at | TIMESTAMPTZ | yes | NULL | |
| completed_at | TIMESTAMPTZ | yes | NULL | |
| paths_found | INT | yes | NULL | |
| error_text | TEXT | yes | NULL | |
| retry_count | INT | no | 0 | |

**Indexes**:
- `(status, retry_count) WHERE status = 'pending'` — claim query index
- `UNIQUE (entity_id) WHERE status IN ('pending','running')` — one active job per entity at a time

### 8.4 NEW TABLE: path_insights (pre-computed scored paths)

| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| insight_id | UUID | no | `new_uuid7()` | PK |
| anchor_entity_id | UUID | no | — | FK `canonical_entities(entity_id)` ON DELETE CASCADE |
| tenant_id | UUID | yes | NULL | NULL = shared path insight; non-null = tenant-scoped path (future: tenant-specific graph overlays) |
| path_nodes | JSONB | no | — | `[{entity_id, name, entity_type}]` — min 2 nodes |
| path_edges | JSONB | no | — | `[{relation_type, confidence}]` — len = len(path_nodes)-1 |
| hop_count | INT | no | — | CHECK `hop_count BETWEEN 2 AND 5` |
| harmonic_score | FLOAT | no | — | `harmonic_mean(edge_confidences)` |
| diversity_score | FLOAT | no | — | entity_type_diversity bonus (see §10.2) |
| surprise_score | FLOAT | no | — | path rarity metric (see §10.2) |
| template_match | TEXT | yes | NULL | Matched manufacturing-chain template name; NULL if none |
| composite_score | FLOAT | no | — | Final: `harmonic×0.4 + diversity×0.35 + surprise×0.25 + (0.1 if template_match else 0.0)` clamped to 1.0 |
| llm_explanation | TEXT | yes | NULL | Cached multi-sentence LLM explanation; NULL until first API request |
| explanation_model | TEXT | yes | NULL | Model that generated the explanation |
| computed_at | TIMESTAMPTZ | no | `NOW()` | |
| explanation_at | TIMESTAMPTZ | yes | NULL | |

**Indexes**:
- `(anchor_entity_id, composite_score DESC)` — primary query path (O(1) per entity)
- `(anchor_entity_id, computed_at DESC)` — freshness check

> **Tenant isolation roadmap**: `tenant_id NULL` = shared platform paths (visible to all). Future per-tenant enrichment will allow tenants to inject private graph edges (e.g., internal supply-chain data) and recompute paths scoped to their overlay. `canonical_entities` itself remains platform-wide (no `tenant_id`) — the isolation boundary sits at the `entity_narrative_versions`, `path_insight_jobs`, and `path_insights` level. Full multi-tenant isolation (including `canonical_entities.tenant_id`) is tracked as a deferred item in PLAN-0023.

### 8.5 MODIFY TABLE: relations — activate unused schema elements

These columns already exist in migration 0001 but are never populated. Activation = add missing indexes + update workers to populate them.

**Columns to activate** (add no new columns, only enforce via worker logic):

| Column | Type | Currently | Fix |
|--------|------|-----------|-----|
| `valid_from TIMESTAMPTZ` | nullable | Always NULL | Populate from `MIN(evidence_date)` across `relation_evidence_raw` per relation, in `ConfidenceRefreshWorker` |
| `valid_to TIMESTAMPTZ` | nullable | Always NULL | Set by `ContradictionBatchWorker` when contradiction invalidates the relation (confidence < 0.1) |
| `valid_to_confidence FLOAT` | nullable | Always NULL | Set alongside `valid_to` |
| `valid_to_source VARCHAR(30)` | nullable | Always NULL | Set alongside `valid_to` with model_id |
| `relation_period_type VARCHAR(20)` | NOT NULL DEFAULT 'ONGOING' | Always 'ONGOING' | Derive on confidence refresh: `POINT_IN_TIME` if `valid_to < valid_from + 7 days`; `HISTORICAL` if `valid_to IS NOT NULL`; else `ONGOING` |
| `strongest_contra_score FLOAT` | NOT NULL DEFAULT 0.0 | Always 0.0 | Updated by `ContradictionBatchWorker` on each contradiction detection |
| `contra_count_by_type JSONB` | NOT NULL DEFAULT '{}' | Always '{}' | Updated by `ContradictionBatchWorker` — `{relation_type: count}` |
| `latest_contra_at TIMESTAMPTZ` | nullable | Always NULL | Updated by `ContradictionBatchWorker` |

**New indexes to add in migration 0026**:
```sql
CREATE INDEX idx_relations_contra_active
    ON relations (latest_contra_at DESC)
    WHERE strongest_contra_score > 0.0;

CREATE INDEX idx_relations_active_period
    ON relations (valid_from, valid_to)
    WHERE valid_to IS NULL AND relation_period_type = 'ONGOING';
```

### 8.6 MODIFY TABLE: relation_summaries — activate summary_embedding

`summary_embedding VECTOR(1024)` column and HNSW index already exist (migration 0001 Block K). The index definition already includes `WHERE is_current = true AND summary_embedding IS NOT NULL`.

**Fix**: Update `SummaryWorker` (13C) to call `embed(summary_text)` after generating the summary and UPSERT the result into `summary_embedding`. No migration needed — only worker code change.

### 8.7 MODIFY TABLE: relation_evidence_raw — fix source diversity undercount

Currently: `source_document_id UUID NOT NULL` exists, but `source_name` and `source_type` are absent. The corroboration bonus in the confidence formula counts `distinct (source_type, source_name)` pairs per relation but these fields are not stored, so every evidence row contributes no diversity signal.

**Migration 0028** adds:
| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| source_name | TEXT | yes | NULL | Publisher name — e.g. "Reuters", "Bloomberg", "SEC EDGAR" |
| source_type | TEXT | yes | NULL | `news` \| `filing` \| `transcript` \| `market_data` — copied from `document_source_metadata` |

**Population**:
- At insert time (KG consumer): JOIN `document_source_metadata` on `source_document_id` to fetch and store both fields
- Data migration for existing rows: UPDATE via JOIN on `source_document_id` (best-effort; NULL for rows where metadata is unavailable)

**Index**: `(canonical_type, source_type, source_name) WHERE processed = true` — for corroboration aggregation query

---

## 9. Domain Model Changes

### 9.1 EntityNarrativeVersion (new entity, S7 domain layer)

**Frozen**: yes
**Location**: `services/knowledge-graph/src/knowledge_graph/domain/entities/narrative.py`

| Attribute | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| version_id | UUID | yes | UUIDv7 | Generated on creation |
| entity_id | UUID | yes | — | Owning entity |
| narrative_text | str | yes | 50–10000 chars | LLM-generated prose |
| model_id | str | yes | non-empty | e.g. `Qwen/Qwen3-235B-A22B-Instruct-2507` |
| generation_reason | NarrativeGenerationReason | yes | enum member | Why regenerated |
| input_snapshot | dict | no | — | Data fingerprint for idempotency |
| generated_at | datetime | yes | UTC-aware | |
| is_current | bool | yes | — | |
| word_count | int | no | ≥0 | `len(narrative_text.split())` |
| quality_score | float | no | 0.0–1.0 | LLM self-scored |

**Invariants**:
- `word_count == len(narrative_text.split())` when word_count is not None
- Entity can have at most one version where `is_current=True` (enforced by DB partial unique index)

### 9.2 NarrativeGenerationReason (new enum)

```python
class NarrativeGenerationReason(str, Enum):
    INITIAL = "INITIAL"
    PERIODIC_REFRESH = "PERIODIC_REFRESH"
    DATA_UPDATE = "DATA_UPDATE"         # data_completeness increased by >0.2
    EVIDENCE_SURGE = "EVIDENCE_SURGE"   # evidence_count increased by >10 in 24h
    MANUAL_TRIGGER = "MANUAL_TRIGGER"
```

### 9.3 PathInsight (new entity, S7 domain layer)

**Frozen**: yes
**Location**: `services/knowledge-graph/src/knowledge_graph/domain/entities/path_insight.py`

| Attribute | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| insight_id | UUID | yes | UUIDv7 | |
| anchor_entity_id | UUID | yes | — | |
| path_nodes | list[PathNode] | yes | min 2 items | |
| path_edges | list[PathEdge] | yes | len = len(path_nodes)-1 | |
| hop_count | int | yes | 2–5 | |
| harmonic_score | float | yes | 0.0–1.0 | |
| diversity_score | float | yes | 0.0–1.0 | |
| surprise_score | float | yes | 0.0–1.0 | |
| template_match | str | no | — | |
| composite_score | float | yes | 0.0–1.0 | |
| llm_explanation | str | no | — | |
| computed_at | datetime | yes | UTC-aware | |

**Invariants**:
- `hop_count == len(path_edges)`
- `composite_score == min(harmonic×0.4 + diversity×0.35 + surprise×0.25 + (0.1 if template_match else 0.0), 1.0)`

### 9.4 PathInsightJob (new entity, S7 domain layer)

**Location**: `services/knowledge-graph/src/knowledge_graph/domain/entities/path_insight.py`

| Attribute | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| job_id | UUID | yes | UUIDv7 | |
| entity_id | UUID | yes | — | |
| status | PathJobStatus | yes | enum | pending \| running \| done \| failed |
| claimed_by | str | no | — | Worker instance UUID |
| claimed_at | datetime | no | UTC-aware | |
| retry_count | int | yes | ≥0 | |

**Invariants**:
- `claimed_by IS NOT NULL ↔ status == running`
- `retry_count ≤ 3` (failed permanently after 3 attempts)

### 9.5 EntityIntelligence (new read model / value object, S7 domain layer)

**Location**: `services/knowledge-graph/src/knowledge_graph/domain/models.py`
Read model assembled by `GetEntityIntelligenceUseCase` — not persisted, computed on query.

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| entity_id | UUID | yes | |
| canonical_name | str | yes | |
| entity_type | str | yes | |
| health_score | float | no | Composite 0–1 |
| data_completeness | float | no | |
| enriched_at | datetime | no | |
| current_narrative | EntityNarrativeVersion | no | |
| confidence_breakdown | ConfidenceBreakdown | yes | |
| source_distribution | list[SourceShare] | yes | |
| confidence_trend | list[ConfidenceTrendPoint] | yes | 90 data points |
| key_metrics | dict | yes | Entity-type-specific from metadata JSONB |

**Supporting value objects**:
```python
@dataclass(frozen=True)
class ConfidenceBreakdown:
    mean_confidence: float
    mean_support: float
    mean_corroboration: float
    mean_contradiction: float
    latest_evidence_at: datetime | None
    evidence_count: int

@dataclass(frozen=True)
class SourceShare:
    source_type: str
    source_name: str | None
    evidence_count: int
    pct: float          # 0.0–1.0

@dataclass(frozen=True)
class ConfidenceTrendPoint:
    date: datetime      # UTC midnight
    mean_confidence: float
```

---

## 10. Data Flow

### 10.1 Narrative Generation Flow (NarrativeGenerationWorker 13D-3)

```
Trigger (scheduled weekly / MANUAL_TRIGGER API / EVIDENCE_SURGE consumer)
  │
  ▼
Load entity context (READ session only — ARCH-003):
  ├── canonical_entities: canonical_name, entity_type, description, metadata
  ├── top-10 relations (confidence DESC) with evidence_text snippets
  ├── last-5 news article headlines (S5 internal API: GET /internal/v1/articles?entity_id=)
  └── active contradictions summary
  │
  ▼
Build input_snapshot (sha256 of all inputs → deterministic dict)
  │
  ▼
Idempotency check: entity_narrative_versions WHERE entity_id=X AND input_snapshot=?
  If version already exists → skip (log "narrative_already_current"), exit
  │
  ▼
Call LLM (NARRATIVE_LLM_MODEL_ID env var, DeepInfra):
  -- Separate from PRD-0073's ENRICHMENT_LLM_MODEL_ID; both registered in worldview-gitops,
  -- synced to worldview via setup-secrets.sh. Allows independent model tuning per use case.
  Prompt: entity-specific template (few-shot with 2 EODHD description examples)
  Response: narrative_text (multi-paragraph, finance-professional grade)
  │
  ▼
BEGIN TRANSACTION (WRITE session):
  INSERT entity_narrative_versions (is_current=false)           -- Step 1: safe insert
  UPDATE entity_narrative_versions SET is_current=false          -- Step 2: clear old current
    WHERE entity_id=X AND is_current=true
  UPDATE entity_narrative_versions SET is_current=true           -- Step 3: promote new
    WHERE version_id=<new_version_id>
  UPDATE canonical_entities SET                                  -- Step 4: update pointer
    current_narrative_version_id=<new_version_id>,
    health_score=<computed>
    WHERE entity_id=X
COMMIT
  │
  ▼
Emit entity.narrative.generated.v1 (via Outbox — never dual-write)
  │
  ▼
NarrativeRefreshWorker (13D-2) consumes event → re-embeds narrative_text
```

### 10.2 PathInsightWorker Flow (horizontally scalable)

**Nightly seeder** (02:30 UTC cron, separate lightweight task):
```sql
-- Identify hub entities dynamically via relation count
-- Will be optimized to use canonical_entities.is_hub index once PLAN-0023 adds that column
WITH hub_entities AS (
    SELECT subject_entity_id AS entity_id
    FROM relations
    GROUP BY subject_entity_id
    HAVING COUNT(*) > 10
)
INSERT INTO path_insight_jobs (entity_id)
SELECT he.entity_id
FROM hub_entities he
WHERE he.entity_id NOT IN (
    SELECT entity_id FROM path_insight_jobs
    WHERE completed_at > NOW() - INTERVAL '23h'
)
ON CONFLICT (entity_id) WHERE status IN ('pending', 'running') DO NOTHING
```

**Per-entity processing** (N worker instances, claim-based):
```
Worker loop (each instance polls every 30s):
  │
  ▼
Claim batch: UPDATE path_insight_jobs
  SET status='running', claimed_by={instance_uuid}, claimed_at=NOW()
  WHERE job_id IN (
      SELECT job_id FROM path_insight_jobs
      WHERE status='pending' AND retry_count < 3
      ORDER BY job_id FOR UPDATE SKIP LOCKED LIMIT 10
  )
  │
  ▼
For each claimed entity:
  │
  ├── Open AGE session: SET search_path = ag_catalog, "$user", public
  │
  ├── Run Cypher (max 5 hops, LIMIT 200):
  │   MATCH p=(start:entity {entity_id: $id})-[*2..5]-(end:entity)
  │   WHERE id(start) <> id(end)
  │   RETURN p,
  │     [rel IN relationships(p) | rel.confidence] AS edge_confs,
  │     [n IN nodes(p) | n.entity_type] AS node_types
  │   ORDER BY length(p) DESC
  │   LIMIT 200
  │
  ├── Score each path:
  │   harmonic_score  = harmonic_mean(edge_confs)
  │   diversity_score = 1 - (max_type_count / hop_count)   -- penalises same-type repeats
  │   surprise_score  = 1 - (path_frequency / total_paths) -- rarity; cached global dict
  │   template_match  = check against path_templates config table
  │   composite_score = min(harmonic×0.4 + diversity×0.35 + surprise×0.25 + (0.1 if template), 1.0)
  │
  ├── Keep top 50 by composite_score
  │
  ├── BEGIN TRANSACTION:
  │   DELETE FROM path_insights WHERE anchor_entity_id = $entity_id
  │   INSERT INTO path_insights (top 50 rows, llm_explanation=NULL)
  │   UPDATE path_insight_jobs SET status='done', completed_at=NOW(), paths_found=N
  │   COMMIT
  │
  └── On exception: UPDATE status='failed', error_text=..., retry_count+1

Lazy LLM explanation (triggered on first GET /paths response with null explanation):
  Background task (asyncio): call LLM with path_nodes + path_edges context
  → UPDATE path_insights SET llm_explanation=..., explanation_model=..., explanation_at=NOW()
  Next API response returns cached explanation
```

### 10.3 Entity Chat Flow (S8 extension)

```
POST /api/v1/chat/entity-context  (S9 → S8)
  │
  ▼
S8: Load entity context (parallel fetches):
  ├── GET /internal/v1/entities/{entity_id}/intelligence
  │     → narrative_text, key_metrics, confidence_breakdown
  └── GET /internal/v1/entities/{entity_id}/graph?depth=1&limit=5
        → top 5 relations with canonical_type + object_entity_name
  │
  ▼
Build system prompt prefix:
  "You are a market intelligence analyst reviewing [canonical_name] ([entity_type]).
   Entity context: [narrative_text]
   Key relations: [top 5 relation summaries with confidence]
   Data quality: health_score=[X], data_completeness=[Y]
   Answer questions about this entity only. Cite sources from retrieved evidence."
  │
  ▼
Run existing RAG retrieval with entity_id filter:
  Vector search on article_chunks WHERE entity_mentions CONTAINS entity_id
  + BM25 full-text on entity canonical_name
  + Rerank with relation relevance boost
  │
  ▼
Generate + stream via SSE (existing S8 pipeline)
```

### 10.4 Panel Synchronization Flow (Frontend)

```
User clicks node N in Cytoscape graph (col 1)
  │
  ▼
React: setSelectedEntityId(N.entity_id)  [shared context, no server round-trip]
  │
  ├── Center panel (Intelligence tabs):
  │   Relations tab — filter displayed rows: WHERE subject_id=N OR object_id=N
  │   Evidence tab — filter: WHERE relation.subject_id=N OR relation.object_id=N
  │   Paths tab — highlight paths containing N
  │
  └── Right sidebar (Entity Detail):
        If N !== anchorEntityId:
          Fetch GET /api/v1/entities/N/intelligence  (lightweight)
          Render N's narrative, metrics, confidence in sidebar
        Else:
          Render anchor entity's data (already loaded)
```

---

## 11. Architecture Decisions

### ADR-0074-001: Lazy LLM Explanation for Paths
**Decision**: `PathInsightWorker` writes paths with `llm_explanation=NULL`. Explanation generated on first API request and cached.
**Rationale**: 2,000 hub entities × 50 paths = 100,000 potential explanations. At 2s/call = 55 hours of LLM calls per nightly run at a single worker — infeasible. Only viewed paths get explanations; ~95% of computed paths are never requested.
**Rejected**: Pre-compute all with higher parallelism. Risk: LLM cost at scale, nightly window violation, rate limit exposure.

### ADR-0074-002: Append-Only Narrative Versioning with is_current Partial Index
**Decision**: `entity_narrative_versions` is append-only. Current version tracked via `UNIQUE (entity_id, is_current) WHERE is_current = TRUE` partial index.
**Rationale**: Rollback = 2 UPDATE statements in one transaction (flip flags). Full history preserved forever — negligible storage at this entity count. Research value: observable evolution of entity understanding over time.
**Rejected**: Overwrite single `narrative_text` column in `canonical_entities`. Loses history; no rollback path.

### ADR-0074-003: Claim-Based SKIP LOCKED for PathInsightWorker
**Decision**: Work queue table `path_insight_jobs` with `SELECT FOR UPDATE SKIP LOCKED`. True horizontal scaling via `docker compose up --scale path-insight-worker=N`.
**Rationale**: Same proven pattern as `provisional_entity_queue` in this codebase. No external coordinator (Redis, Celery). Stateless workers — crash-safe, auto-restart.
**Rejected**: Hash-partition by entity_id at startup. Rejected: static partitioning doesn't rebalance on worker crash; entities served unevenly if some are heavier than others.

### ADR-0074-004: Entity Chat as S8 Extension (Not New Service)
**Decision**: Add `POST /api/v1/chat/entity-context` to existing S8 rag-chat.
**Rationale**: Same LLM pipeline, same Valkey session store, same auth middleware. New endpoint = ~150 lines + 1 new use case class. New service = 2,000+ lines of boilerplate.
**Rejected**: New dedicated intelligence-chat service. Rejected: violates DRY at service level; no distinct infrastructure requirement.

### ADR-0074-005: 3-Column Layout with Full-Width Chat
**Decision**: Graph (25%) | Intelligence tabs (45%) | Entity sidebar (30%) + full-width chat (collapsible, 200px).
**Rationale**: Three genuinely different information archetypes — interactive network (graph), tabular analytical data (relations/evidence/paths), and card-based contextual data (narrative/metrics/news). Conflating them in 2 columns forces scrolling tradeoffs. Full-width chat gives enough horizontal space for multi-turn dialogue.

### ADR-0074-006: Client-Side Panel Synchronization via Shared React Context
**Decision**: `selectedEntityId` is a React context value. Clicking a graph node calls `setSelectedEntityId` — no server round-trip for synchronization.
**Rationale**: All relation data for visible nodes is already in the graph response. Client-side filtering is O(1). Server round-trip would add 100–300ms latency to every node click, breaking the interactive feel.

### ADR-0074-007: Manufacturing Chain Templates as Config Table
**Decision**: `path_templates` table in intelligence_db — stores `template_name`, `entity_type_sequence` (JSONB array of allowed types per hop), `relation_type_sequence` (JSONB array of allowed relation types).
**Rationale**: Templates are data, not code. Adding a new manufacturing chain template (e.g. semiconductor → EDA software → chip designer) requires only a row INSERT, not a deployment.
**Example template** (migration 0033 seed — see §16 migration table):
```json
{"template_name": "supply_chain_3hop",
 "entity_type_sequence": ["company", "company", "company"],
 "relation_type_sequence": ["SUPPLIES_TO|MANUFACTURES_FOR", "SUPPLIES_TO|MANUFACTURES_FOR"]}
```

---

## 12. Security Analysis

| Threat | Mitigated by |
|--------|-------------|
| Tenant data leakage in narrative | `canonical_entities` is a **platform-wide shared table** (no `tenant_id` column — all users see all canonical entities). `entity_narrative_versions` has `tenant_id UUID NULL`: queries filter by `tenant_id IS NULL OR tenant_id = :requesting_tenant_id` to return both shared and tenant-owned narratives. Entity intelligence endpoints enforce this filter at the use-case layer. |
| LLM prompt injection via entity name | `prompts.knowledge.alias.sanitize_description()` applied to all entity fields before LLM call (same as PRD-0073 Worker 13J) |
| LLM cost abuse via manual narrative trigger | Rate limit: 1 req/hour/entity/user enforced via Valkey key `narrative_gen:{tenant_id}:{entity_id}:{user_id}` |
| path_insights JSONB injection | All entity_ids in `path_nodes` validated as well-formed UUIDs before serialization; `path_edges.relation_type` validated against `relation_type_registry.canonical_type` |
| Entity chat cross-tenant leakage | S8 RAG retrieval already filters articles by `tenant_id`; entity intelligence endpoint validates entity belongs to requesting tenant |
| PathInsightWorker SSRF | AGE Cypher runs inside PostgreSQL — no outbound HTTP. No SSRF surface. |
| Narrative version history exposure | `GET /narratives` requires same tenant auth as base entity read — no additional privilege needed |

---

## 13. Failure Modes

| Component | Failure | Impact | Recovery |
|-----------|---------|--------|---------|
| NarrativeGenerationWorker LLM call | LLM 429 / 503 | Generation skipped | Exponential backoff (3 retries); previous narrative version stays current; `narrative_generation_failure_total` metric incremented |
| NarrativeGenerationWorker transaction | DB write fails | Version not inserted | Rolled back cleanly; no partial state; next scheduled run retries |
| PathInsightWorker AGE timeout | Query takes >60s | Job marked failed | `retry_count++`; after 3 retries, job parked in `failed` state; operator re-inserts manually |
| path_insights stale | Nightly run incomplete | Stale paths served | `computed_at` timestamp shown to user; next run overwrites; tolerable for analytics use case |
| Lazy LLM explanation race | Two requests fire simultaneously for same null explanation | Two LLM calls → last writer wins | UPSERT on `explanation_at` — idempotent; both explanations semantically equivalent |
| entity_narrative_versions concurrent generation | Two workers generate for same entity simultaneously | Partial unique index violation on second COMMIT | Second transaction rolls back; first version stands; next periodic refresh will regenerate if needed |
| S8 entity context load failure | Internal entity intelligence endpoint down | Chat degraded to generic mode (no entity context injected) | Log warning; proceed with empty context prefix; user still gets generic RAG response |
| source_name data migration | document_source_metadata JOIN returns NULL | source_name stays NULL for those rows | Best-effort migration acceptable; existing rows don't break corroboration formula (they contribute 0 diversity as before) |

---

## 14. Scalability

| Component | Current State | Scaling Strategy |
|-----------|--------------|-----------------|
| PathInsightWorker | 1 instance | `SELECT FOR UPDATE SKIP LOCKED` — add instances via `docker compose up --scale path-insight-worker=N`; linear scaling; 4 instances process 500 hub entities in ~10 minutes |
| path_insights table | Max 2,000 entities × 50 paths = 100,000 rows × ~2KB = 200MB | Trivial. Nightly full-replace (DELETE + INSERT) keeps size bounded |
| entity_narrative_versions | 10,000 entities × 10 avg versions = 100,000 rows × 2KB avg = 200MB | Full retention; grow at ~20MB/month at 100 narrative generations/day |
| confidence trend query | Aggregates `relation_evidence_raw` grouped by date per entity | Add index `(subject_entity_id, evidence_date::date)` — query <50ms for 3,000 evidence rows per entity |
| NarrativeGenerationWorker | Single-threaded batch | Add batch parallelism via asyncio gather (max 5 concurrent LLM calls); bounded by LLM rate limit |
| entity chat | Stateless S8 endpoint | Scales with S8 replicas; SSE connections closed after response completes |

---

## 15. Test Strategy

### Unit Tests (S7 knowledge-graph)

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_narrative_version_insert_sets_is_current` | New version inserts with `is_current=False`, then promoted correctly | unit |
| `test_narrative_idempotency_same_snapshot` | Duplicate `input_snapshot` → no new version inserted | unit |
| `test_narrative_generation_reason_enum_values` | All 5 enum values serialize/deserialize correctly | unit |
| `test_health_score_formula_completeness_40_freshness_30_density_30` | `health_score` computed correctly for known inputs | unit |
| `test_path_insight_composite_score_formula` | `composite_score == min(h×0.4 + d×0.35 + s×0.25 + template_bonus, 1.0)` | unit |
| `test_path_insight_hop_count_invariant` | `hop_count == len(path_edges)` enforced in domain entity | unit |
| `test_path_insight_job_claim_sets_running_status` | Claim sets `status='running'`, `claimed_by`, `claimed_at` | unit |
| `test_confidence_breakdown_public_exposes_components` | `ConfidenceComponents` fields appear in `RelationResponse` when `confidence_breakdown=true` | unit |
| `test_source_diversity_score_populated` | `source_name` populated at `relation_evidence_raw` insert | unit |
| `test_contra_columns_updated_by_contradiction_worker` | `strongest_contra_score`, `contra_count_by_type`, `latest_contra_at` populated | unit |
| `test_valid_from_populated_from_earliest_evidence` | `valid_from` set to `MIN(evidence_date)` across relation's raw evidence | unit |
| `test_relation_period_type_derivation` | POINT_IN_TIME when valid_to within 7 days; HISTORICAL when valid_to set; ONGOING otherwise | unit |
| `test_summary_embedding_populated_by_summary_worker` | SummaryWorker calls embed() and stores result | unit |
| `test_manufacturing_chain_template_match` | Path matching `supply_chain_3hop` template receives 0.1 bonus | unit |
| `test_path_job_skip_locked_allows_parallel_claims` | Two workers claim different jobs without conflict (asyncio test) | unit |

### Integration Tests (S7 knowledge-graph)

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_get_entity_intelligence_endpoint_returns_narrative` | Full round-trip: entity created → narrative generated → GET intelligence returns it | integration |
| `test_get_entity_paths_returns_scored_paths` | PathInsightWorker run → GET paths returns top-N with scores | integration |
| `test_narrative_version_history_pagination` | 25 versions → GET narratives?limit=10 returns cursor | integration |
| `test_manual_narrative_trigger_rate_limited` | Second trigger within 1 hour returns 429 | integration |

### Integration Tests (S8 rag-chat)

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_entity_chat_context_loaded_in_system_prompt` | Entity narrative appears in system prompt prefix | integration |
| `test_entity_chat_streams_sse_events` | Response is well-formed SSE stream with token/done events | integration |

### Contract Tests

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_entity_narrative_generated_avro_schema` | Avro schema for `entity.narrative.generated.v1` is valid and forward-compatible | contract |
| `test_entity_intelligence_response_schema` | `GET /entities/{id}/intelligence` response matches `EntityIntelligencePublic` Pydantic schema | contract |
| `test_path_insights_public_schema` | `PathInsightPublic` response matches spec | contract |

---

## 16. Migration Plan

All migrations owned by `intelligence-migrations`. Run in strict numerical order. S7 and S8 set `ALEMBIC_ENABLED=false`.

| Migration | Description | Depends On |
|-----------|-------------|------------|
| 0024 (PRD-0073) | `canonical_entities` structured enrichment columns (`description`, `data_completeness`, `enriched_at`, `enrichment_attempts`) | — |
| 0025 (PRD-0073) | `relation_type_registry` data_source/source_field columns | 0024 |
| 0026 (PRD-0073) | `relations.relation_source` column | 0025 |
| 0027 (PRD-0073) | Seed EODHD/market-data relation-type mappings in `relation_type_registry` | 0026 |
| **0028** | `entity_narrative_versions` table (with `tenant_id NULL`) + `canonical_entities.current_narrative_version_id` + `health_score` | 0027 |
| **0029** | `path_insight_jobs` table (with `tenant_id NULL`) + `path_insights` table (with `tenant_id NULL`) | 0028 |
| **0030** | `relations` unused column activation: indexes for `latest_contra_at`, `valid_from`/`valid_to`; `relation_period_type` CHECK constraint | 0029 |
| **0031** | Noop migration (HNSW index on `relation_summaries.summary_embedding` already created in 0001); adds `WHERE is_current = true` partial condition verification | 0030 |
| **0032** | `relation_evidence_raw`: ADD `source_name TEXT`, `source_type TEXT` + data migration UPDATE via JOIN on `document_source_metadata` | 0031 |
| **0033** | `path_templates` config table + seed manufacturing-chain templates | 0032 |

**Migration 0028 detail** — uses `autocommit_block` for concurrent index (avoids table lock):
```python
with op.get_context().autocommit_block():
    op.execute("CREATE INDEX CONCURRENTLY ...")
```

**Migration 0030 note** — `relation_period_type` already has `NOT NULL DEFAULT 'ONGOING'` from migration 0001. The activation migration adds a CHECK constraint (safe to add when all existing values are 'ONGOING'):
```sql
ALTER TABLE relations
    ADD CONSTRAINT chk_relation_period_type
    CHECK (relation_period_type IN ('POINT_IN_TIME','ONGOING','HISTORICAL'));
```

---

## 17. Observability

| Metric | Type | Labels |
|--------|------|--------|
| `narrative_generation_total` | counter | reason, model_id, status (success/failure) |
| `narrative_generation_duration_seconds` | histogram | model_id |
| `path_insight_job_duration_seconds` | histogram | worker_instance |
| `path_insight_paths_per_entity` | gauge | — |
| `path_explanation_generated_total` | counter | model_id, trigger (lazy/manual) |
| `entity_chat_context_load_duration_seconds` | histogram | — |
| `source_name_null_rate` | gauge | — (monitor source diversity fix coverage) |
| `contra_columns_populated_rate` | gauge | — (monitor contra activation coverage) |

**Log events** (structlog):
- `narrative_generation_started`, `narrative_generation_complete`, `narrative_idempotent_skip`
- `path_insight_job_claimed`, `path_insight_job_complete`, `path_insight_job_failed`
- `entity_chat_context_loaded`, `entity_chat_context_fallback` (when entity intelligence fetch fails)

---

## 18. Open Questions

| ID | Question | Classification | Notes |
|----|----------|---------------|-------|
| OQ-1 | Should confidence trend aggregate daily or weekly data points? | DEFERRED | Daily recommended (90 daily points = lightweight); weekly if performance issues |
| OQ-2 | Manufacturing chain template registry — add via API or migration seed only? | DEFERRED | Migration seed for MVP; API endpoint in future if analysts want custom templates |
| OQ-3 | Should `NarrativeGenerationWorker` degrade gracefully (fall back to `template-v1`) when LLM is unavailable? | DEFERRED | Recommended YES — log model_id='template-v1', generation_reason preserved. Prevents gaps during LLM outages. |
| OQ-4 | Maximum path depth: 5 hops or configurable per-entity? | DEFERRED | 5 fixed for MVP; configurable via `path_templates` `max_hops` field in future |
| OQ-5 | Entity narrative exposure in screener / instrument overview pages (cross-page reuse)? | DEFERRED | Same endpoint available; integration in other pages out of scope for this PRD |

---

## 19. Estimation

| Area | Effort |
|------|--------|
| intelligence-migrations (0028–0033) | 0.5 days |
| S7 NarrativeGenerationWorker (13D-3) + `entity_narrative_versions` repo + use case | 1.5 days |
| S7 PathInsightWorker + seeder + `path_insight_jobs`/`path_insights` repos | 2.0 days |
| S7 activate contra columns + valid_from/valid_to + summary_embedding + source_name | 0.5 days |
| S7 `GetEntityIntelligenceUseCase` + `GetEntityPathsUseCase` + API endpoints | 1.0 day |
| S8 entity-context chat endpoint + entity context loading use case | 0.5 days |
| S9 proxy routes + response schema updates | 0.5 days |
| worldview-web 3-column intelligence page + synchronized panels + chat component | 2.5 days |
| Tests (unit + integration + contract) | 1.0 day |
| **Total** | **~10 days** |
