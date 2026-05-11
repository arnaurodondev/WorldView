# PRD-0023 — Knowledge Graph Analytics & NLP Cache Layer

> **Status**: Draft — 2026-04-08
> **Author**: Arnau Rodon
> **Origin**: Graphify open-source investigation (2026-04-08)
> **Services affected**: S7 (Knowledge Graph), S6 (NLP Pipeline), S4 (Content Ingestion), S10 (Alert Service)
> **Depends on**: PLAN-0018 (intelligence_db migrations owner), PRD-0021 (S10 alert fan-out)
> **Plan**: PLAN-0023 (to be generated)

---

## 1. Problem Statement

The worldview knowledge graph (S7) stores thousands of canonical entities and tens of thousands of relations, but has **no structural intelligence** about the graph itself:

1. **No community awareness** — The platform cannot answer "which entities are in the same sector cluster?" beyond GICS seed relations. Embedding similarity finds individually close entities but cannot group them into coherent communities.
2. **No hub detection** — Entities that structurally bridge many communities (e.g., "Federal Reserve", "S&P 500") have the same API representation as singleton entities with one relation. There is no way to surface the most structurally important nodes.
3. **No evolution tracking** — The knowledge graph changes continuously as new articles are ingested, but there is no mechanism to detect or broadcast "a meaningful new entity or relationship appeared." S10 flash alerts (PRD-0021) are score-gated on NLP signals, but **graph-structural changes** (new hub entities, new cross-community edges) have no alert path.
4. **No NER extraction cache** — S6's NLP pipeline re-runs GLiNER entity extraction on every article, including re-delivered or re-ingested articles with identical text. This wastes GPU/CPU cycles and creates non-deterministic duplicate mentions when the same entity text is scored slightly differently across runs.
5. **No redirect re-validation in S4** — The SSRF transport (`SSRFSafeTransport`) validates the initial URL but does not re-validate the resolved IP after HTTP redirects, leaving a TOCTOU window for DNS rebinding attacks.

The graphify open-source project (MIT, 2026) implements graph community detection, hub analysis, graph evolution diffing, and content-addressed extraction caching. This PRD specifies which patterns to extract, adapt, or implement from scratch to address the five gaps above.

---

## 2. Target Users

| User | Workflow | Benefit |
|------|----------|---------|
| **Research Analysts** | Browsing entity relationships to understand market structure | Community clustering surfaces related entities beyond direct neighbours; hub entities provide natural starting points for research |
| **Retail Investors** | Monitoring portfolio entities for significant developments | Graph evolution alerts notify when a watched entity gains new structural connections |
| **Quantitative Traders** | Programmatic access to entity similarity scores | `surprise_score` in similarity results exposes cross-domain connections not visible in embedding distance alone |
| **Thesis Evaluators** | Assessing system sophistication | Community detection + hub scoring + evolution alerting demonstrate graph-structural intelligence on top of the vector layer |

---

## 3. Functional Requirements

### 3.1 Community Detection (S7)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-01 | A `CommunityDetectionWorker` runs on a configurable schedule (default: every 30 minutes) in S7's scheduler | MUST |
| F-02 | The worker builds an undirected igraph from `canonical_entity` + `relations` tables (type-filtered: `financial_instrument`, `organization`, `person`, `government_body`, `regulatory_body`, `financial_institution`) with at least 1 relation | MUST |
| F-03 | Leiden algorithm (`leidenalg` library) partitions the graph into communities | MUST |
| F-04 | The anchor entity for each community is the node with the highest in-community degree | MUST |
| F-05 | Community stable key is `UUIDv5(UUID_NAMESPACE_DNS, str(anchor_entity_id))` | MUST |
| F-06 | Results are persisted to a new `entity_communities` table in `intelligence_db` (DDL via `intelligence-migrations`) | MUST |
| F-07 | Stale community assignments (entity left its community in the latest run) are soft-deleted (set `removed_at = now()`) rather than hard-deleted | MUST |
| F-08 | Community size (member count) and cohesion score (actual_edges / max_possible_edges) are stored per community | MUST |
| F-09 | The detection run follows R24: read entities → close session → run leidenalg (pure CPU) → open new session → write results | MUST |

### 3.2 Hub Entity Detection (S7)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-10 | `GET /api/v1/entities/hubs` returns the top-N entities by total relation count (in + out) across all canonical types | MUST |
| F-11 | `GET /api/v1/entities/{entity_id}/community` returns the community membership of a given entity | MUST |
| F-12 | Hub score is defined as `hub_score = relation_count / max_relation_count_in_dataset` (0–1), computed at query time via SQL aggregation — no pre-materialized column | MUST |
| F-13 | Both endpoints use read-replica sessions (R27) | MUST |

### 3.3 Graph Evolution Events (S7 → S10)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-14 | After each `CommunityDetectionWorker` run, a `GraphEvolutionWorker` computes the delta since the last snapshot | MUST |
| F-15 | "New entity" delta: entities whose `created_at` is within the watermark window AND whose `relation_count ≥ 2` after the run | MUST |
| F-16 | "New bridge edge" delta: edges whose `first_evidence_at` is within the watermark window AND which connect two entities in **different communities** where at least one entity has `hub_score ≥ 0.10` | MUST |
| F-17 | Each delta item produces a `graph.evolution.v1` Kafka event via S7's outbox | MUST |
| F-18 | S10's `GraphEvolutionConsumer` extends `BaseKafkaConsumer`, consumes `graph.evolution.v1`, and creates an `Alert` with `severity = LOW` for new entities and `severity = MEDIUM` for new bridge edges (overridable by PRD-0021 score-gating if `market_impact_score` is non-zero) | MUST |
| F-19 | Deduplication key in S10: `entity_id:graph_evolution:YYYYMMDD` (one alert per entity per day per event type) | MUST |
| F-20 | The `GraphEvolutionConsumer` deduplicates on `evolution_id` in S10's processed-events table (R9) | MUST |

### 3.4 NER Content-Addressed Cache (S6)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-21 | Before calling `ner_client.batch_extract_entities()`, `run_ner_block()` computes `SHA256(article_text)` and checks Valkey key `nlp:ner_cache:{sha256_hex}` | MUST |
| F-22 | On cache hit, deserialize the cached JSON span list and reconstruct `EntityMention` objects with fresh UUIDs and the correct `doc_id` and `section_id` from the current processing context | MUST |
| F-23 | On cache miss, run GLiNER as normal, serialize the raw span data (not `EntityMention` objects) to JSON, and write to Valkey with TTL = 24h | MUST |
| F-24 | Cache key format: `nlp:ner_cache:v1:{sha256_hex}` where sha256 is of the full concatenated article text (all sections joined) | MUST |
| F-25 | If Valkey is unavailable (connection error), the cache check is skipped silently; GLiNER runs as normal — never raises | MUST |
| F-26 | Cache hits and misses are tracked via new Prometheus counters `nlp_ner_cache_hits_total` and `nlp_ner_cache_misses_total` | MUST |
| F-27 | Cached span data format: list of dicts with keys `text`, `label`, `score`, `start`, `end` (raw GLiNER output, pre-NMS) | MUST |

### 3.5 Surprise Score in Similarity Search (S7)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-28 | `POST /api/v1/entities/similar` response adds an optional `surprise_score: float | null` field to each `SimilarEntityResult` | MUST |
| F-29 | `surprise_score` is computed as: `cross_type_bonus + cross_community_bonus + hub_bonus` where: cross_type_bonus = 0.3 if entity types differ, cross_community_bonus = 0.4 if entities are in different communities (requires community data), hub_bonus = 0.3 × `hub_score` of the candidate | MUST |
| F-30 | `surprise_score` is `null` when community data is unavailable (worker hasn't run yet) | MUST |
| F-31 | `final_score` is unchanged (backward compatible) | MUST |

### 3.6 SSRF Redirect Re-Validation (S4)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-32 | `SSRFSafeTransport.handle_async_request()` additionally validates the resolved IP of any redirect `Location` header before following it | MUST |
| F-33 | If a redirect target resolves to a private IP, raise `httpx.ConnectError` with a structured log entry `ssrf_redirect_blocked` | MUST |
| F-34 | Maximum redirect depth: 5 (httpx default); apply IP validation at each hop | MUST |

---

## 4. Non-Functional Requirements

| Attribute | Target |
|-----------|--------|
| Community detection latency | ≤ 60s wall-clock for 200K-node subgraph (leidenalg C++ on CPU) |
| Hub endpoint latency | ≤ 100ms p95 (pure SQL aggregation, indexed on relation count) |
| Community endpoint latency | ≤ 50ms p95 (single PK lookup on `entity_communities`) |
| NER cache hit latency | ≤ 5ms (Valkey GET) |
| NER cache miss overhead | < 1ms additional (SHA256 hash is negligible) |
| Graph evolution event lag | ≤ 35 min from entity creation to S10 alert (30-min worker cadence + 5-min outbox flush) |
| leidenalg dependency size | < 20MB total (leidenalg ~5MB + python-igraph ~10MB); no numba, no scikit-learn |
| Backward compatibility | `SimilarEntityResult` `surprise_score` is nullable — existing callers receive `null` before first community detection run |

---

## 5. Out of Scope

The following are explicitly excluded from this PRD:

- **MCP stdio server** for graph traversal (graphify pattern) — different protocol, different thesis scope
- **Wiki article generation** per entity/community — S7's `DefinitionRefreshWorker` already generates descriptions via Gemini
- **Frontend community visualization** — deferred to a future PRD after community data is available
- **Betweenness centrality computation** — computationally expensive at scale (O(nm) for unweighted); hub scoring by degree alone is sufficient for thesis purposes
- **Leiden resolution parameter tuning** — fixed resolution = 1.0 (default); tuning requires labelled ground truth
- **Cross-service community access** — S6 and other services access community data via S7 REST API, not direct DB reads (R7)
- **Community-based alert filtering** — PRD-0021 score-gating takes precedence; this PRD only introduces the `graph.evolution.v1` trigger
- **NER cache for embedding computation** — embedding cache is a separate concern (EmbeddingRefreshWorker already handles stale state)

---

## 6. Technical Design

### 6.1 Affected Services

| Service | Change Type | Scope |
|---------|------------|-------|
| **S7 — Knowledge Graph** | New workers (2), new endpoints (3), new entity (`EntityCommunity`), `SimilarEntityResult` extension, new Kafka topic producer | Large |
| **S6 — NLP Pipeline** | NER block cache layer, new Prometheus counters | Small |
| **S4 — Content Ingestion** | `SSRFSafeTransport` redirect re-validation | Very Small |
| **S10 — Alert Service** | New Kafka consumer (`GraphEvolutionConsumer`), new alert type | Medium |
| **intelligence-migrations** | 2 new tables: `entity_communities`, `entity_hub_scores_cache` | Small |
| **infra/kafka/schemas** | New Avro schema: `graph.evolution.v1.avsc` | Small |

---

### 6.2 API Changes

#### GET /api/v1/entities/hubs

- **Service**: S7 (Knowledge Graph, port 8007)
- **Purpose**: Returns the top-N canonical entities by structural hub score (total relation count normalized)
- **Auth**: None (public, same as other S7 read endpoints)
- **Use case**: `GetEntityHubsUseCase` → `ReadOnlyUoW` (R27)
- **Request parameters**:

  | Parameter | Type | Required | Default | Validation | Description |
  |-----------|------|----------|---------|------------|-------------|
  | `top_k` | integer | no | 20 | 1–100 | Number of hub entities to return |
  | `entity_type` | string | no | null | enum value or null | Filter by entity type (e.g. `financial_instrument`) |
  | `min_hub_score` | float | no | 0.0 | 0.0–1.0 | Minimum normalized hub score to include |

- **Response** (200):

  | Field | Type | Description |
  |-------|------|-------------|
  | `total_entities` | integer | Total canonical entities in the dataset |
  | `max_relation_count` | integer | Highest relation count across all entities (denominator for hub_score) |
  | `hubs` | array[HubEntityResult] | Ordered by hub_score DESC |

  `HubEntityResult` object:

  | Field | Type | Nullable | Description |
  |-------|------|----------|-------------|
  | `entity_id` | UUID | no | Canonical entity ID |
  | `canonical_name` | string | no | Entity display name |
  | `entity_type` | string | no | Entity type (organization, financial_instrument, etc.) |
  | `ticker` | string | yes | Ticker symbol (financial instruments only) |
  | `relation_count` | integer | no | Total relations (in + out) |
  | `hub_score` | float | no | `relation_count / max_relation_count` ∈ [0, 1] |
  | `community_id` | UUID | yes | Stable community key; null if no community run yet |
  | `community_size` | integer | yes | Members in community; null if no community data |

- **Error responses**:
  - `422`: `top_k` outside [1, 100] or `min_hub_score` outside [0.0, 1.0]
- **Rate limit**: none (internal, thesis scale)

---

#### GET /api/v1/entities/{entity_id}/community

- **Service**: S7 (Knowledge Graph, port 8007)
- **Purpose**: Returns the community membership record for a specific entity
- **Auth**: None (public)
- **Use case**: `GetEntityCommunityUseCase` → `ReadOnlyUoW` (R27)
- **Path parameter**: `entity_id` — UUID of the canonical entity

- **Response** (200):

  | Field | Type | Nullable | Description |
  |-------|------|----------|-------------|
  | `entity_id` | UUID | no | The queried entity |
  | `community_id` | UUID | no | Stable community key (UUIDv5 of anchor) |
  | `anchor_entity_id` | UUID | no | Highest-degree entity in community |
  | `anchor_name` | string | no | Canonical name of anchor entity |
  | `community_size` | integer | no | Total members |
  | `cohesion_score` | float | no | `actual_edges / max_possible_edges` ∈ [0, 1] |
  | `joined_at` | datetime | no | UTC ISO-8601; when entity was assigned to this community |
  | `members_preview` | array[string] | no | Up to 5 canonical names of other members (ordered by degree DESC) |

- **Error responses**:
  - `404`: Entity not found in `canonical_entities`
  - `422`: `entity_id` is not a valid UUID
  - `503`: Community detection has never run (no rows in `entity_communities`) — body: `{"detail": "community_data_unavailable", "message": "Community detection has not yet run. Try again after the scheduled worker completes."}`

- **Rate limit**: none

---

#### POST /api/v1/entities/similar (extension — no path change)

- **Service**: S7 (Knowledge Graph, port 8007)
- **Change**: Existing endpoint; response schema extended with `surprise_score`
- **Request body**: Unchanged (see PRD-0017)
- **Response** (200) — changed fields only:

  `SimilarEntityResult` object gains:

  | Field | Type | Nullable | Description |
  |-------|------|----------|-------------|
  | `surprise_score` | float | yes | Cross-type + cross-community + hub bonus score ∈ [0, 1]; null if community data unavailable |
  | `surprise_components` | object | yes | `{cross_type: bool, cross_community: bool, hub_bonus: float}` for transparency; null when surprise_score is null |

- **Backward compatibility**: `surprise_score` and `surprise_components` are new nullable fields. Existing callers parsing only `final_score` are unaffected.

---

### 6.3 Event Changes

#### graph.evolution.v1 (NEW)

- **Topic**: `graph.evolution.v1`
- **Partition key**: `primary_entity_id` (consistent routing per entity)
- **Retention**: 7 days
- **Compaction**: none (not a compacted topic)
- **Producers**: S7 (`GraphEvolutionWorker` via outbox)
- **Consumers**: S10 (`GraphEvolutionConsumer`)
- **Avro schema**:

  | Field | Type | Default | Nullable | Description |
  |-------|------|---------|----------|-------------|
  | `event_id` | string | — | no | UUIDv7 envelope ID |
  | `event_type` | string | `"graph.evolution"` | no | Always `"graph.evolution"` |
  | `schema_version` | int | 1 | no | Schema version |
  | `occurred_at` | string | — | no | ISO-8601 UTC; time of evolution detection |
  | `evolution_id` | string | — | no | UUIDv7; stable dedup key for this specific delta item |
  | `primary_entity_id` | string | — | no | Entity that triggered the evolution event |
  | `primary_entity_name` | string | — | no | Canonical name at time of event |
  | `evolution_type` | string | — | no | `"new_entity"` \| `"new_bridge_edge"` |
  | `community_id` | string | `""` | yes | Stable community key at time of event; empty string if unavailable |
  | `related_entity_id` | string | `""` | yes | For `new_bridge_edge`: the other endpoint; empty string for `new_entity` |
  | `related_entity_name` | string | `""` | yes | Canonical name of related entity |
  | `relation_type` | string | `""` | yes | For `new_bridge_edge`: canonical relation type; empty for `new_entity` |
  | `hub_score` | float | 0.0 | no | Hub score of `primary_entity_id` at detection time |
  | `is_backfill` | boolean | false | no | True if entity/edge is from historical data |
  | `correlation_id` | string | `""` | yes | Propagated from triggering pipeline |

---

### 6.4 Database Changes

All new tables are in `intelligence_db`. DDL is owned exclusively by `intelligence-migrations` (S7 has `ALEMBIC_ENABLED=false`).

#### Table: `entity_communities` (NEW — intelligence_db)

Stores community membership for each entity as determined by the latest successful Leiden run.

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `id` | UUID | no | `gen_random_uuid()` | PK | UUIDv7 generated by app, not DB default |
| `entity_id` | UUID | no | — | FK → `canonical_entities.entity_id`, NOT NULL | Member entity |
| `community_id` | UUID | no | — | NOT NULL | UUIDv5 stable key; same anchor = same UUID across runs |
| `anchor_entity_id` | UUID | no | — | FK → `canonical_entities.entity_id`, NOT NULL | Highest-degree member |
| `community_size` | integer | no | — | NOT NULL, CHECK > 0 | Total members at time of detection |
| `cohesion_score` | float | no | — | NOT NULL, CHECK BETWEEN 0 AND 1 | actual_edges / max_possible_edges |
| `detected_at` | TIMESTAMPTZ | no | — | NOT NULL | UTC timestamp of the Leiden run |
| `removed_at` | TIMESTAMPTZ | yes | NULL | — | Set when entity leaves community; NULL = active |

- **Indexes**:
  - `(entity_id) WHERE removed_at IS NULL` — PRIMARY LOOKUP (entity → current community)
  - `(community_id) WHERE removed_at IS NULL` — community membership listing
  - `(anchor_entity_id) WHERE removed_at IS NULL` — community info by anchor
  - `(detected_at)` — for watermark-based queries
- **Unique constraint**: `UNIQUE (entity_id) WHERE removed_at IS NULL` — one active community per entity
- **Partitioning**: none (expected ≤ 500K active rows)
- **Estimated rows**: ~50K active rows at thesis scale; historical rows accumulate at ~50K per Leiden run that causes reassignments

---

#### Table: `graph_evolution_watermarks` (NEW — intelligence_db)

Stores the watermark for the `GraphEvolutionWorker` to enable incremental delta computation.

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `id` | integer | no | 1 | PK, CHECK = 1 | Singleton row; enforces single watermark |
| `last_entity_watermark` | TIMESTAMPTZ | no | `'2000-01-01 00:00:00+00'` | NOT NULL | `MAX(created_at)` of entities processed in last run |
| `last_relation_watermark` | TIMESTAMPTZ | no | `'2000-01-01 00:00:00+00'` | NOT NULL | `MAX(first_evidence_at)` of relations processed in last run |
| `updated_at` | TIMESTAMPTZ | no | — | NOT NULL | Updated by worker on each successful run |

- **Indexes**: none (PK = 1 row singleton)
- **Partitioning**: none
- **Estimated rows**: 1 (always)

---

#### NLP Pipeline — No new tables

The NER cache is stored entirely in Valkey (Redis-compatible). No new `nlp_db` tables. The cache key format is: `nlp:ner_cache:v1:{sha256_hex}` with a 24h TTL.

---

#### Intelligence-Migrations: New Migration File

- Migration `0004_entity_communities_and_watermark.py` (follows existing 0003 migration)
- Creates `entity_communities` and `graph_evolution_watermarks` tables
- Seeds `graph_evolution_watermarks` with the singleton row (id=1, both watermarks = epoch)
- Does **not** run Alembic against `intelligence_db` from S7 — the `intelligence-migrations` service owns this

---

### 6.5 Domain Model Changes

#### Entity: `EntityCommunity` (NEW — S7 domain layer)

- **Purpose**: Represents a community membership assignment for a canonical entity
- **Frozen**: yes
- **Module**: `knowledge_graph.domain.models`
- **Attributes**:

  | Attribute | Type | Required | Validation | Description |
  |-----------|------|----------|------------|-------------|
  | `id` | UUID | yes | UUIDv7 | Row PK |
  | `entity_id` | UUID | yes | valid UUID | Member entity |
  | `community_id` | UUID | yes | UUIDv5 | Stable community identifier |
  | `anchor_entity_id` | UUID | yes | valid UUID | Highest-degree community member |
  | `community_size` | int | yes | ≥ 1 | Members in this community |
  | `cohesion_score` | float | yes | 0.0–1.0 | actual_edges / max_possible_edges |
  | `detected_at` | datetime | yes | UTC-aware | When this assignment was computed |
  | `removed_at` | datetime \| None | no | UTC-aware or None | None = active membership |

- **Invariants**:
  - `0.0 ≤ cohesion_score ≤ 1.0`
  - `community_size ≥ 1`
  - `removed_at is None` for the active assignment; only one active row per `entity_id` at any time
  - `community_id == uuid5(UUID_NAMESPACE_DNS, str(anchor_entity_id))` — derivable, stored for query efficiency

---

#### Entity: `GraphEvolutionDelta` (NEW — S7 domain layer)

- **Purpose**: Represents a detected change in the knowledge graph structure; emitted as `graph.evolution.v1`
- **Frozen**: yes
- **Module**: `knowledge_graph.domain.models`
- **Attributes**:

  | Attribute | Type | Required | Validation | Description |
  |-----------|------|----------|------------|-------------|
  | `evolution_id` | UUID | yes | UUIDv7 | Stable dedup key |
  | `primary_entity_id` | UUID | yes | valid UUID | Entity that triggered the event |
  | `primary_entity_name` | str | yes | non-empty | Canonical name at detection time |
  | `evolution_type` | EvolutionType | yes | enum | `NEW_ENTITY` or `NEW_BRIDGE_EDGE` |
  | `community_id` | UUID \| None | no | UUIDv5 or None | Community of primary entity; None if no community data |
  | `related_entity_id` | UUID \| None | no | valid UUID | For `NEW_BRIDGE_EDGE`: other endpoint |
  | `related_entity_name` | str \| None | no | — | Canonical name of related entity |
  | `relation_type` | str \| None | no | — | Canonical relation type for bridge edges |
  | `hub_score` | float | yes | 0.0–1.0 | Hub score at detection time |
  | `is_backfill` | bool | yes | — | Whether entity/edge is historical |
  | `occurred_at` | datetime | yes | UTC-aware | Detection timestamp |

---

#### Enum: `EvolutionType` (NEW — S7 domain layer)

- **Module**: `knowledge_graph.domain.enums`
- **Values**:
  - `NEW_ENTITY = "new_entity"` — A new canonical entity with ≥ 2 relations was first detected
  - `NEW_BRIDGE_EDGE = "new_bridge_edge"` — A new relation connects two entities in different communities where at least one has hub_score ≥ 0.10

---

#### Model: `SimilarEntityResult` (EXTENDED — S7 domain layer)

Existing frozen dataclass in `knowledge_graph.domain.models`. **Addition only** (backward-compatible):

| Attribute | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `surprise_score` | float \| None | no | None | Cross-type + cross-community + hub bonus; null until community data available |
| `surprise_components` | SurpriseComponents \| None | no | None | Component breakdown; null when surprise_score is null |

New value object `SurpriseComponents` (frozen dataclass):

| Attribute | Type | Description |
|-----------|------|-------------|
| `cross_type` | bool | True if entity types differ |
| `cross_community` | bool | True if entities are in different communities |
| `hub_bonus` | float | 0.3 × hub_score of candidate entity |

**Surprise score formula**:
```
cross_type_bonus    = 0.30 if entity types differ else 0.0
cross_community_bonus = 0.40 if in different communities else 0.0
hub_bonus           = 0.30 × candidate_hub_score
surprise_score      = min(cross_type_bonus + cross_community_bonus + hub_bonus, 1.0)
```
Returns `None` when community data is unavailable (no rows in `entity_communities`).

---

#### Value Object: `NERCacheSpan` (NEW — S6 domain layer, internal)

- **Purpose**: Serializable representation of a single GLiNER span for Valkey caching
- **Module**: `nlp_pipeline.application.blocks.ner` (inline dataclass, not exported)
- **Note**: Not a full domain entity — it is an internal representation used only within `run_ner_block()`. No persistence, no repository.

| Attribute | Type | Description |
|-----------|------|-------------|
| `text` | str | Span text as extracted by GLiNER |
| `label` | str | Entity class label (one of 11 NER classes) |
| `score` | float | GLiNER confidence score |
| `start` | int | Character start offset |
| `end` | int | Character end offset |

Serialization: `json.dumps([dataclasses.asdict(span) for span in spans])` (list of dicts).
Deserialization: `[NERCacheSpan(**d) for d in json.loads(cached)]`.

---

### 6.6 Infrastructure Changes

#### New Python Dependencies — S7 (`services/knowledge-graph/pyproject.toml`)

```toml
python-igraph = ">=0.11,<1.0"   # C++ sparse graph; ~10MB wheel
leidenalg = ">=0.10,<1.0"       # Leiden algorithm; ~5MB wheel; requires python-igraph
```

**NOT added**: `graspologic`, `numba`, `scikit-learn`, `scipy`. The leidenalg C++ backend has no JVM/JIT warm-up overhead. Container image delta: ~15MB.

These deps are imported **lazily** inside `CommunityDetectionWorker.run()` with `TYPE_CHECKING` guards everywhere else. The S7 API server process never imports leidenalg.

#### New Python Dependencies — S6 (`services/nlp-pipeline/pyproject.toml`)

None. SHA256 uses Python stdlib `hashlib`. Valkey access uses the existing `redis.asyncio` client already in `infrastructure/valkey/`.

#### New Kafka Topic Registration

```yaml
# infra/kafka/topics.yaml (or equivalent bootstrap)
graph.evolution.v1:
  partitions: 6
  replication_factor: 1
  retention_ms: 604800000  # 7 days
  cleanup_policy: delete
```

#### New Config Variables — S7 (`Settings`)

| Env Var | Type | Default | Description |
|---------|------|---------|-------------|
| `KNOWLEDGE_GRAPH_COMMUNITY_DETECTION_INTERVAL_S` | int | 1800 | Leiden run interval in seconds (30 min) |
| `KNOWLEDGE_GRAPH_GRAPH_EVOLUTION_INTERVAL_S` | int | 1800 | Graph evolution delta interval in seconds (30 min) |
| `KNOWLEDGE_GRAPH_KAFKA_TOPIC_GRAPH_EVOLUTION` | str | `"graph.evolution.v1"` | Evolution event topic |
| `KNOWLEDGE_GRAPH_COMMUNITY_DETECTION_MIN_RELATION_COUNT` | int | 1 | Min relations for entity to enter igraph |
| `KNOWLEDGE_GRAPH_GRAPH_EVOLUTION_MIN_RELATION_COUNT` | int | 2 | Min relations for new entity to emit an evolution event |
| `KNOWLEDGE_GRAPH_GRAPH_EVOLUTION_HUB_SCORE_THRESHOLD` | float | 0.10 | Minimum hub_score for bridge-edge evolution |
| `KNOWLEDGE_GRAPH_LEIDEN_RESOLUTION` | float | 1.0 | Leiden resolution parameter (higher = more/smaller communities) |

#### New Config Variables — S6 (`Settings`)

| Env Var | Type | Default | Description |
|---------|------|---------|-------------|
| `NLP_PIPELINE_NER_CACHE_TTL_S` | int | 86400 | Valkey NER cache TTL in seconds (24h) |
| `NLP_PIPELINE_NER_CACHE_ENABLED` | bool | true | Feature flag to disable cache without code change |

#### Docker Compose — No New Services

No new containers. The leidenalg worker runs inside the existing `kg-scheduler` process/container (same image, different `command`). The `graph.evolution.v1` topic is auto-created by the Kafka broker on first produce (or pre-registered in topic bootstrap).

---

### 6.7 Data Flow Design

#### Flow A: Community Detection (every 30 minutes)

```
KnowledgeGraphScheduler (APScheduler)
  → CommunityDetectionWorker.run()
    1. [R24 Phase 1] Open intelligence_db read session
       → CanonicalEntityRepository.fetch_for_community_detection(entity_types=[...], min_relation_count=1)
         Returns: list[(entity_id, relation_count, [neighbour_entity_ids])]
       → Close read session
    2. [R24 Phase 2 — no session] Build igraph.Graph from entity adjacency
       → leidenalg.find_partition(G, leidenalg.ModularityVertexPartition, resolution=1.0)
       → For each community partition:
           anchor = member with max degree in community
           community_id = uuid5(NAMESPACE_DNS, str(anchor.entity_id))
           cohesion = actual_intra_edges / (size * (size-1) / 2) or 1.0 if size == 1
    3. [R24 Phase 3] Open intelligence_db write session
       → EntityCommunityRepository.soft_delete_stale(detected_before=now())
       → EntityCommunityRepository.bulk_upsert(List[EntityCommunity])
         Uses INSERT ... ON CONFLICT (entity_id) WHERE removed_at IS NULL DO UPDATE
       → session.commit()
       → Close write session
    4. Log: community_detection_complete {n_communities, n_entities, wall_clock_ms}
```

#### Flow B: Graph Evolution Detection (every 30 minutes, offset 15 min from community)

```
KnowledgeGraphScheduler (APScheduler)
  → GraphEvolutionWorker.run()
    1. [R24 Phase 1] Read watermarks from graph_evolution_watermarks (singleton row)
    2. Query new entities: canonical_entities WHERE created_at > last_entity_watermark AND relation_count >= 2
    3. Query new bridge edges: relations r
         JOIN entity_communities ec1 ON r.subject_entity_id = ec1.entity_id (active)
         JOIN entity_communities ec2 ON r.object_entity_id = ec2.entity_id (active)
       WHERE r.first_evidence_at > last_relation_watermark
         AND ec1.community_id != ec2.community_id
         AND (hub_score(r.subject_entity_id) >= 0.10 OR hub_score(r.object_entity_id) >= 0.10)
    4. For each new entity or bridge edge: construct GraphEvolutionDelta
    5. [R24: close session before outbox write loop]
    6. Open write session
       → For each delta: write outbox event (graph.evolution.v1) via transactional outbox (R8)
       → Update graph_evolution_watermarks singleton
       → session.commit()
    7. S7 OutboxDispatcher picks up events → publishes to Kafka topic graph.evolution.v1
```

#### Flow C: S10 Graph Evolution Alert Fan-Out

```
Kafka: graph.evolution.v1
  → GraphEvolutionConsumer (S10, extends BaseKafkaConsumer)
    1. is_duplicate check: processed_events WHERE event_id = evolution_id
    2. Dedup check: existing Alert WHERE entity_id = primary_entity_id
                                   AND alert_type = 'graph_evolution_' + evolution_type
                                   AND created_at >= today_UTC
       → if dedup hit: ack and skip
    3. AlertFanoutUseCase.create_alert(
           entity_id=primary_entity_id,
           alert_type='graph_evolution_new_entity' | 'graph_evolution_bridge_edge',
           question=f"New entity '{primary_entity_name}' has entered the knowledge graph"
                  | f"New bridge: '{primary_entity_name}' ↔ '{related_entity_name}' ({relation_type})",
           severity=AlertSeverity.LOW (new_entity) | AlertSeverity.MEDIUM (bridge_edge)
       )
    4. WebSocket push to connected tenants watching relevant entities
```

#### Flow D: NER Content Cache (S6 — per article)

```
ArticleProcessingConsumer → NLP Pipeline blocks
  → Block 4 run_ner_block(doc_id, sections, ner_client)
    1. article_text = "\n".join(s.text for s in sections)
    2. sha256_key = "nlp:ner_cache:v1:" + hashlib.sha256(article_text.encode()).hexdigest()
    3. cached_json = await valkey.get(sha256_key)  [best-effort: skip on error]
    4a. CACHE HIT:
        spans = [NERCacheSpan(**d) for d in json.loads(cached_json)]
        mentions = _spans_to_mentions(spans, doc_id, sections)  # fresh UUIDs + section_id
        nlp_ner_cache_hits_total.inc()
        return mentions, _compute_stats(doc_id, mentions)
    4b. CACHE MISS:
        mentions, stats = [original GLiNER batch + NMS logic]
        nlp_ner_cache_misses_total.inc()
        spans = _mentions_to_spans(mentions)  # extract raw text/label/score/start/end
        await valkey.setex(sha256_key, NER_CACHE_TTL_S, json.dumps([dataclasses.asdict(s) for s in spans]))
        return mentions, stats
```

#### Flow E: SSRF Redirect Validation (S4)

```
SSRFSafeTransport.handle_async_request(request)
  1. [existing] Resolve initial hostname → block private IPs
  2. [NEW] Create httpx client with follow_redirects=False, max_redirects=0
  3. [NEW] Manual redirect loop (max 5 hops):
       response = await inner.handle_async_request(request)
       while response.is_redirect and hop_count < 5:
           location = response.headers["location"]
           redirect_url = httpx.URL(location)
           redirect_hostname = redirect_url.host
           [resolve redirect_hostname → block private IPs → raise ConnectError if private]
           request = request.copy(url=redirect_url)
           response = await inner.handle_async_request(request)
           hop_count += 1
  4. return response
```

---

## 7. Architecture Decisions

### ADR-0023-001: leidenalg + python-igraph over graspologic

**Decision**: Use `leidenalg` (C++ binding) + `python-igraph` (C++ sparse graph) instead of `graspologic`.

**Context**: graphify uses `graspologic` which transitively pulls in `numba` (~380MB) + `scikit-learn` (~60MB) + `scipy` (~150MB) for spectral methods that worldview will never use. numba incurs a 15-second JIT warm-up on first invocation.

**Alternatives**:

| Option | Deps Size | Warm-up | Notes |
|--------|-----------|---------|-------|
| **graspologic** (graphify's choice) | ~650MB | 15s JIT | Full spectral + Leiden; overkill |
| **leidenalg + python-igraph** ✓ | ~15MB | none | Same Leiden algorithm; C++ throughout |
| **networkx + cdlib** | ~30MB | none | Pure Python Leiden; 10–50× slower |
| **Pure SQL clustering** | 0MB | — | Cannot run Leiden; only spectral via pgvector |

**Consequence**: `leidenalg` is the standard academic Leiden implementation (same authors as the original paper). Identical algorithmic results; dramatically smaller image.

---

### ADR-0023-002: Community ID stability via anchor-entity UUIDv5

**Decision**: Stable community ID = `uuid.uuid5(uuid.NAMESPACE_DNS, str(anchor_entity_id))`.

**Context**: Leiden is non-deterministic — the same graph may produce different community memberships across runs. Raw sequential community IDs would invalidate all stored membership records on every run.

**Alternatives**:

| Option | Stability | Complexity |
|--------|-----------|-----------|
| **Anchor entity UUIDv5** ✓ | Stable while anchor stays | O(n) degree lookup per community |
| Centroid embedding hash | Stable if embeddings don't drift | Requires embedding fetch in community detection |
| Random UUIDv7 per run | Completely unstable | Simple but useless for dedup |
| Largest-label entity name hash | Fragile on entity rename | Simple |

**Consequence**: A community's ID only changes if its highest-degree member changes (e.g., entity added with more connections than current anchor). This is rare and acceptable. The `soft_delete_stale` + re-insert pattern handles this without data corruption.

---

### ADR-0023-003: Graph evolution via SQL watermarks not in-memory diff

**Decision**: Use SQL `WHERE created_at > watermark` queries rather than loading full graph into memory and diffing snapshots.

**Context**: graphify's `graph_diff()` works because it operates on a single-process in-memory NetworkX graph of ~10K nodes (a code repository). At worldview's scale (up to 500K entities), loading the full entity graph into memory every 30 minutes (~500K × ~200 bytes = 100MB minimum) and computing a full set-diff is feasible but wasteful and fragile.

**Alternatives**:

| Option | Memory | Latency | Correctness |
|--------|--------|---------|-------------|
| **SQL watermark** ✓ | O(new rows) | <10ms | Exact; no missed deltas |
| In-memory NetworkX diff | O(total entities) | 2–10s | Requires stable node IDs across runs |
| Change-data-capture via Postgres LISTEN | Minimal | Real-time | Requires pg_notify plumbing |

**Consequence**: The watermark approach is simpler, uses indexes, and is correct at any scale. The watermark is a singleton row in `graph_evolution_watermarks`, updated atomically with the outbox events in the same transaction.

---

### ADR-0023-004: NER cache stores raw spans (pre-NMS), not EntityMention objects

**Decision**: Cache the raw GLiNER output (`text, label, score, start, end`) before NMS and ID assignment.

**Context**: `EntityMention` objects carry `mention_id` (UUIDv7), `doc_id`, and `section_id` — all of which are specific to the current processing context and must be fresh. Caching the full `EntityMention` would require caching N versions per article (one per re-delivery with different doc_id). Caching raw spans is universal — NMS and ID assignment happen after the cache hit, just as they would after GLiNER.

**Consequence**: On a cache hit, `_nms()` and `_compute_stats()` still run — these are O(n²) in spans but spans per section are typically ≤ 50, so this is negligible. GLiNER forward passes (the expensive part) are fully skipped.

---

## 8. Security Analysis

### 8.1 Threat Model

| Threat | Surface | Mitigation |
|--------|---------|-----------|
| **SSRF via redirect** | S4 `SSRFSafeTransport` — redirect to internal service | Flow E re-validates every redirect hop; private IPs blocked at each step |
| **Community ID forgery** | `GET /api/v1/entities/{id}/community` | `community_id` is deterministic UUIDv5; client cannot forge a valid one for a different anchor |
| **Injection via entity name in evolution events** | `primary_entity_name` in Avro event | Name sourced from DB `canonical_name` field, never from user input; length-capped at 255 chars by entity schema |
| **NER cache poisoning** | Valkey `nlp:ner_cache:v1:{sha256}` | SHA256 collision probability negligible; Valkey is internal-only (no external access); 24h TTL limits blast radius |
| **Large igraph OOM** | `CommunityDetectionWorker` loading 500K-node graph | Hard limit: if entity count > `MAX_COMMUNITY_ENTITIES = 500_000`, worker logs a warning and skips the run (circuit breaker) |

### 8.2 Multi-Tenant Isolation

All new S7 endpoints are **read-only** against `intelligence_db` which does not have a `tenant_id` column on `canonical_entities` (entities are global, not per-tenant — established in PRD-0001). This is consistent with existing S7 endpoints.

S10's `GraphEvolutionConsumer` creates alerts with a `tenant_id` — when `primary_entity_id` is on a user's watchlist, S10 fans out to that tenant's WebSocket. This follows the existing `AlertFanoutUseCase` pattern.

### 8.3 Input Validation

| Input | Source | Validation |
|-------|--------|------------|
| `top_k` query param | HTTP | `1 ≤ top_k ≤ 100`; FastAPI `Query(default=20, ge=1, le=100)` |
| `entity_type` query param | HTTP | enum allowlist; `None` accepted |
| `min_hub_score` query param | HTTP | `0.0 ≤ x ≤ 1.0`; FastAPI `Query(default=0.0, ge=0.0, le=1.0)` |
| `entity_id` path param | HTTP | UUID parse; `422` on invalid format |
| `evolution_id` in Kafka event | Kafka | Parsed as UUID string; invalid → DLQ |
| Leiden partition result | Internal | `community_size ≥ 1` asserted; `cohesion_score` clamped to [0, 1] |

---

## 9. Failure Modes

| Failure | Impact | Recovery |
|---------|--------|---------|
| `leidenalg` raises on malformed graph (isolated nodes) | Community detection run aborted | Worker catches `Exception`, logs `leiden_partition_failed`, increments `s7_worker_crash_total`; stale community data retained; retry on next interval |
| `intelligence_db` unavailable during community write | Community results lost for this run | R24 phase separation: read session already closed; write fails cleanly; watermark not updated; retry on next interval |
| `graph_evolution_watermarks` row missing (first run) | `GraphEvolutionWorker` cannot read watermark | Worker seeds default watermark row via INSERT ON CONFLICT DO NOTHING at startup |
| Outbox dispatcher lagging | Evolution events arrive at S10 late | At-least-once delivery guarantee preserved; S10 dedup prevents duplicate alerts |
| S10 down when evolution events arrive | Events accumulate in Kafka | Consumer group offset preserved; S10 processes backlog on restart |
| Valkey unavailable for NER cache | Cache skipped entirely | `try/except Exception` around all Valkey calls; `nlp_ner_cache_misses_total` incremented; GLiNER runs normally |
| Valkey NER cache TTL expired mid-article | Cache miss on re-delivery | Same as cold miss path; idempotent |
| igraph OOM on very large graphs | Community detection worker crashes | Circuit breaker: skip run if entity count > 500K; crash increments `s7_worker_crash_total`; alert via Prometheus alert rule |
| SSRF redirect to private IP | S4 blocked | `ConnectError` raised; article fetch fails; task retried per S4's existing retry policy |
| `graph.evolution.v1` Avro schema registry unavailable | Evolution events not published | Outbox events remain in DB; retry on next dispatcher poll |

---

## 10. Scalability & Performance

### 10.1 Community Detection

| Metric | Thesis Scale (10K entities) | Scale Target (500K entities) |
|--------|----------------------------|------------------------------|
| igraph build time | < 1s | ~5–15s (C++ sparse) |
| leidenalg partition time | < 2s | ~20–60s (depends on edge density) |
| DB write (bulk upsert) | < 0.5s | < 5s (batch 500K inserts) |
| Total wall clock | < 5s | ~90s worst case |

**Risk at 500K**: leidenalg's C++ implementation is designed for 10M+ node graphs in benchmark conditions. At 500K nodes with average degree ~5 (sparse social graph), Leiden completes in seconds. However, entity_communities bulk upsert at 500K rows may take 5–10s. Mitigation: use `INSERT ... ON CONFLICT DO UPDATE` with a single COPY-based batch; chunk into 10K-row batches.

### 10.2 Hub Endpoint

`GET /api/v1/entities/hubs` computes hub scores via:
```sql
SELECT entity_id, canonical_name, entity_type, ticker,
       COUNT(*) OVER () as total_entities,
       relation_count,
       relation_count::float / MAX(relation_count) OVER () as hub_score
FROM canonical_entities
ORDER BY relation_count DESC
LIMIT :top_k
```

`relation_count` is a materialized column in `canonical_entities` (or computed as `(SELECT COUNT(*) FROM relations WHERE ...)` with a covering index). At 500K entities, this is a single sorted scan on an indexed column — < 10ms.

### 10.3 NER Cache

Valkey GET/SET latency is ~0.5ms p99 on localhost. SHA256 of a 10KB article is ~0.01ms. Total cache overhead per article: < 2ms. Expected hit rate after warm-up: ~15–25% (re-delivered and duplicate-source articles).

### 10.4 Graph Evolution Worker

SQL watermark queries are indexed on `created_at` and `first_evidence_at`. At 500K entities with ~1% new per 30-min window (5K), the query returns in < 10ms. The bridge-edge query joins two copies of `entity_communities` (indexed on `entity_id WHERE removed_at IS NULL`) and the `relations` table (indexed on `first_evidence_at`). Estimated < 50ms at thesis scale.

---

## 11. Test Strategy

### Unit Tests — S7

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_community_id_is_deterministic` | Same anchor_entity_id → same UUIDv5 community_id across calls | HIGH |
| `test_cohesion_score_complete_graph` | 3-node fully-connected community → cohesion = 1.0 | HIGH |
| `test_cohesion_score_sparse_graph` | 4-node community with 2 edges → cohesion = 2/6 | HIGH |
| `test_cohesion_score_singleton` | 1-node community → cohesion = 1.0 (degenerate case) | HIGH |
| `test_entity_community_invariants` | `cohesion_score` outside [0,1] raises `ValueError` | HIGH |
| `test_graph_evolution_delta_new_entity` | Entity with relation_count ≥ 2 → `EvolutionType.NEW_ENTITY` | HIGH |
| `test_graph_evolution_delta_bridge_edge` | Cross-community edge with hub_score ≥ 0.10 → `EvolutionType.NEW_BRIDGE_EDGE` | HIGH |
| `test_graph_evolution_delta_below_hub_threshold` | Cross-community edge with hub_score = 0.05 → no delta emitted | HIGH |
| `test_surprise_score_cross_type` | org candidate + financial_instrument query → cross_type_bonus = 0.30 | HIGH |
| `test_surprise_score_cross_community` | Different community IDs → cross_community_bonus = 0.40 | HIGH |
| `test_surprise_score_null_when_no_community_data` | No entity_communities rows → surprise_score = None | HIGH |
| `test_surprise_score_capped_at_1` | Max bonuses (0.30 + 0.40 + 0.30) clamped to 1.0 | MEDIUM |
| `test_hub_score_normalization` | hub_score = relation_count / max_relation_count | HIGH |
| `test_evolution_type_enum_values` | `EvolutionType` has exactly 2 members | MEDIUM |
| `test_get_entity_hubs_use_case_top_k` | Returns ≤ top_k results ordered by relation_count DESC | HIGH |
| `test_get_entity_community_use_case_not_found` | Entity with no community → 503 community_data_unavailable | HIGH |

### Unit Tests — S6

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_ner_cache_hit_returns_reconstructed_mentions` | Cache hit with valid JSON → reconstructs EntityMention with fresh UUID | HIGH |
| `test_ner_cache_miss_calls_gliner` | Empty Valkey → GLiNER called; result cached | HIGH |
| `test_ner_cache_hit_skips_gliner` | Cache populated → GLiNER mock never called | HIGH |
| `test_ner_cache_valkey_unavailable_falls_through` | Valkey raises ConnectionError → GLiNER runs normally; no exception | HIGH |
| `test_ner_cache_key_is_sha256_of_all_sections` | Two articles with same text → same cache key | HIGH |
| `test_ner_cache_fresh_uuids_on_hit` | Same cache key, different doc_id → different mention_id UUIDs | HIGH |
| `test_ner_cache_section_id_assigned_from_context` | Cache hit → section_id matches the input section | HIGH |
| `test_ner_cache_spans_are_pre_nms` | Cached spans may include overlaps; NMS applied after reconstruction | MEDIUM |

### Unit Tests — S4

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_ssrf_redirect_to_private_ip_blocked` | Redirect Location resolves to 10.0.0.1 → ConnectError | HIGH |
| `test_ssrf_redirect_to_public_ip_allowed` | Redirect to 8.8.8.8 → proceeds normally | HIGH |
| `test_ssrf_redirect_max_depth_respected` | 6 redirects → error after 5 | MEDIUM |
| `test_ssrf_redirect_schema_change_blocked` | Redirect to `ftp://` → blocked | HIGH |

### Integration Tests — S7

| Test | Infrastructure | What It Verifies |
|------|---------------|-----------------|
| `test_community_detection_worker_writes_communities` | intelligence_db | Worker produces rows in entity_communities with correct community_id stability |
| `test_community_detection_soft_deletes_stale` | intelligence_db | Re-run with changed graph → old membership soft-deleted, new rows created |
| `test_graph_evolution_worker_emits_outbox_events` | intelligence_db | New entities above threshold → outbox events with correct evolution_type |
| `test_graph_evolution_watermark_updated` | intelligence_db | After run → watermarks row updated to current max timestamps |
| `test_get_entity_hubs_endpoint` | intelligence_db (read replica) | Returns ranked hubs, correct hub_score normalization |
| `test_get_entity_community_endpoint_active` | intelligence_db (read replica) | Entity with community → 200 with correct fields |
| `test_get_entity_community_endpoint_no_data` | intelligence_db (read replica, empty) | 503 community_data_unavailable |
| `test_similar_entities_with_surprise_score` | intelligence_db (with community data) | surprise_score populated when community data exists |

### Integration Tests — S6

| Test | Infrastructure | What It Verifies |
|------|---------------|-----------------|
| `test_ner_cache_integration_valkey` | Valkey | SHA256 key stored; TTL = 86400s |
| `test_ner_cache_integration_cache_hit` | Valkey + GLiNER mock | Second call with same text → GLiNER not called |

### Contract Tests

| Test | What It Verifies |
|------|-----------------|
| `test_graph_evolution_v1_avro_schema` | Avro schema parses correctly; all fields with defaults can be omitted by producer |
| `test_graph_evolution_v1_forward_compat` | Adding a new field with default to the schema does not break existing readers |

---

## 12. Migration Strategy

### 12.1 Database Migrations (intelligence-migrations)

Migration file: `0004_entity_communities_and_watermark.py`

```
Sequence:
  1. CREATE TABLE entity_communities (...)
  2. CREATE TABLE graph_evolution_watermarks (...)
  3. INSERT INTO graph_evolution_watermarks (id, last_entity_watermark, last_relation_watermark, updated_at)
     VALUES (1, '2000-01-01 00:00:00+00', '2000-01-01 00:00:00+00', now())
     ON CONFLICT (id) DO NOTHING
  4. CREATE INDEX CONCURRENTLY ON entity_communities (entity_id) WHERE removed_at IS NULL
  5. CREATE INDEX CONCURRENTLY ON entity_communities (community_id) WHERE removed_at IS NULL
  6. CREATE INDEX CONCURRENTLY ON entity_communities (anchor_entity_id) WHERE removed_at IS NULL
  7. CREATE INDEX CONCURRENTLY ON entity_communities (detected_at)
  8. CREATE UNIQUE INDEX CONCURRENTLY ON entity_communities (entity_id) WHERE removed_at IS NULL
```

All indexes use `CREATE INDEX CONCURRENTLY` to avoid table locks during migration on live instances.

### 12.2 Kafka Topic Bootstrap

`graph.evolution.v1` must be created before the `GraphEvolutionWorker` first runs. Options:
- **Auto-create**: Kafka `auto.create.topics.enable=true` (enabled in dev docker-compose) — topic created on first produce
- **Pre-register**: Add to `infra/kafka/topics.yaml` if it exists; run topic creation script during `docker compose up`

For thesis environment, auto-create is acceptable.

### 12.3 S7 Dependency Addition

```toml
# services/knowledge-graph/pyproject.toml — [project.dependencies]
"python-igraph>=0.11,<1.0",
"leidenalg>=0.10,<1.0",
```

The `leidenalg` wheel requires `python-igraph` as a C-level dependency. Both are available on PyPI with pre-built wheels for Python 3.12 on linux/aarch64 (M-series Mac Docker) and linux/amd64.

### 12.4 Rollback Plan

If community detection causes instability:
1. Set `KNOWLEDGE_GRAPH_COMMUNITY_DETECTION_INTERVAL_S=999999` (effectively disables worker)
2. Community endpoints return 503 (no data) — graceful degradation
3. `surprise_score` returns null — no API break
4. `graph.evolution.v1` topic stops receiving events — S10 processes no evolution alerts

No data corruption risk: `entity_communities` is append-only with soft deletes. All changes are additive.

---

## 13. Observability

### 13.1 New Prometheus Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `s7_community_detection_duration_seconds` | Histogram | — | Wall-clock duration of `CommunityDetectionWorker.run()` |
| `s7_community_detection_n_communities` | Gauge | — | Number of communities in last run |
| `s7_community_detection_n_entities` | Gauge | — | Number of entities in last run's graph |
| `s7_graph_evolution_deltas_total` | Counter | `evolution_type` | Evolution events produced per type |
| `nlp_ner_cache_hits_total` | Counter | — | NER Valkey cache hits |
| `nlp_ner_cache_misses_total` | Counter | — | NER Valkey cache misses |

### 13.2 Structured Log Events

| Event | Service | Level | Fields |
|-------|---------|-------|--------|
| `community_detection_started` | S7 | INFO | — |
| `community_detection_complete` | S7 | INFO | `n_communities, n_entities, wall_clock_ms` |
| `community_detection_circuit_breaker` | S7 | WARNING | `entity_count, limit` |
| `leiden_partition_failed` | S7 | ERROR | `exc_info=True` |
| `graph_evolution_deltas_emitted` | S7 | INFO | `new_entities, new_bridge_edges` |
| `ssrf_redirect_blocked` | S4 | WARNING | `hostname, resolved_ip, hop` |
| `ner_cache_hit` | S6 | DEBUG | `sha256_prefix (first 8 chars)` |
| `ner_cache_miss` | S6 | DEBUG | `sha256_prefix` |
| `ner_cache_error` | S6 | WARNING | `exc_info=True` (Valkey unavailable) |

---

## 14. Open Questions

| # | Question | Classification | Resolution |
|---|----------|---------------|------------|
| OQ-001 | Does graph diff complement or replace PRD-0021 score-gated alerts? | RESOLVED | Complement — `graph.evolution.v1` is a distinct alert type consumed alongside `nlp.signal.detected.v1` |
| OQ-002 | How to keep community IDs stable across non-deterministic Leiden runs? | RESOLVED | Anchor = highest-degree entity; `community_id = uuid5(NAMESPACE_DNS, str(anchor_entity_id))` |
| OQ-003 | Should NER cache store full EntityMention or raw spans? | RESOLVED | Raw spans (pre-NMS): `text, label, score, start, end`. EntityMention reconstructed with fresh UUIDs on cache hit |
| OQ-004 | Should surprise_score replace or augment final_score? | RESOLVED | Augment — `surprise_score` is a new nullable field; `final_score` unchanged (backward compat) |
| OQ-005 | Graph evolution at 100K–500K nodes? | RESOLVED | SQL watermark queries (no in-memory diff); leidenalg C++ for community detection on type-filtered subgraph |
| OQ-006 | graspologic vs leidenalg for community detection? | RESOLVED | `leidenalg + python-igraph` (15MB C++, no numba, same algorithm) |
| OQ-007 | Should `entity_communities` be in `nlp_db` or `intelligence_db`? | RESOLVED | `intelligence_db` — community membership is a property of canonical entities, which live there |

---

## 15. Implementation Estimation

| Area | Waves | Complexity | Notes |
|------|-------|-----------|-------|
| intelligence-migrations: 2 new tables | 1 | Low | Standard DDL + seed |
| S7: `CommunityDetectionWorker` + leidenalg dep | 1 | Medium | igraph build + Leiden + bulk upsert |
| S7: `GraphEvolutionWorker` + watermark | 1 | Medium | SQL watermarks + outbox integration |
| S7: 3 new endpoints + repositories | 1 | Medium | Standard FastAPI + ReadOnlyUoW + R27 |
| S7: `SimilarEntityResult.surprise_score` | 1 | Low | Extend existing use case + compute surprise |
| S6: NER content-addressed cache | 1 | Low | SHA256 + Valkey get/set + metrics |
| S4: SSRF redirect re-validation | 1 | Very Low | Extend SSRFSafeTransport (~25 lines) |
| S10: `GraphEvolutionConsumer` | 1 | Low | New BaseKafkaConsumer + alert creation |
| Avro schema: `graph.evolution.v1.avsc` | — | Very Low | JSON schema file |
| Tests (unit + integration) | Per wave | — | Per test table above |

**Total estimated waves**: 8 (one per area above)
**Suggested plan structure**:
- Wave A: infrastructure-migrations (0004) + Avro schema
- Wave B: S7 CommunityDetectionWorker
- Wave C: S7 GraphEvolutionWorker + outbox integration
- Wave D: S7 new endpoints (hubs, community, surprise_score extension)
- Wave E: S6 NER cache
- Wave F: S4 SSRF redirect hardening
- Wave G: S10 GraphEvolutionConsumer
- Wave H: Integration tests + observability validation

---

## Appendix: Architecture Compliance Gate

| Rule | Applies? | Design Decision | Status |
|------|----------|----------------|--------|
| R5 — Avro forward compat | YES | `graph.evolution.v1` all fields have defaults | PASS |
| R7 — No cross-service DB | YES | S7 reads only `intelligence_db`; S5 reads only `nlp_db` | PASS |
| R8 — No dual writes | YES | Evolution events via outbox; community writes in single transaction | PASS |
| R9 — Kafka idempotency | YES | `GraphEvolutionConsumer` deduplicates on `evolution_id` | PASS |
| R10 — UUIDv7 | YES | `evolution_id`, `entity_community.id` are UUIDv7; `community_id` UUIDv5 (documented exception for stability) | PASS |
| R11 — UTC timestamps | YES | All `TIMESTAMPTZ`; `datetime.now(UTC)` in all workers | PASS |
| R15 — Validate external input | YES | SSRF redirect re-validation; `top_k`/`min_hub_score` range constraints | PASS |
| R20 — BaseKafkaConsumer | YES | `GraphEvolutionConsumer` extends `BaseKafkaConsumer` | PASS |
| R22 — Independent processes | YES | Workers register in existing scheduler_main.py; no new process entrypoints | PASS |
| R24 — No DB across I/O | YES | CommunityDetectionWorker 3-phase: read → CPU (leidenalg) → write | PASS |
| R25 — API layer isolation | YES | All 3 new endpoints use dedicated use case classes | PASS |
| R27 — ReadOnlyUoW for reads | YES | All GET endpoints use `ReadUoWDep` + `ReadOnlyUnitOfWork` | PASS |
