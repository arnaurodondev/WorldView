# PRD-0018 — Geopolitical Intelligence, EODHD Deep Enrichment & Apache AGE Cypher

> **Status**: Draft
> **Author**: Architecture session 2026-04-04
> **Depends on**: PRD-0001 (S6/S7 graph infra), PRD-0017 (entity embedding views)

---

## §1 Problem Statement

Three interconnected gaps make the platform's graph and intelligence pipeline incomplete:

### 1.1 Geopolitical blindness
The knowledge graph models company relations (subsidiaries, competitors, suppliers) and news-derived signals. However, **geopolitical, regulatory, and macroeconomic events** — which are among the highest-impact signals in financial markets — are entirely absent. A trade war, sanctions regime, central bank rate decision, or pandemic has no structured representation in the graph. This means:
- RELATIONSHIP-intent queries ("how does the US-China tariff cycle affect Taiwan Semiconductor?") cannot traverse geopolitical event nodes
- SIGNAL_INTEL intent queries ("what events are currently creating risk for European automakers?") have no event layer to query
- There is no way to distinguish between a company that is specifically exposed to a geopolitical event vs. one that is tangentially in an affected sector

The key challenge: geopolitical/regulatory/macroeconomic events are **ephemeral** — they have a start, an end, and a residual impact period. They do not fit the existing `relations` table model, which uses continuous confidence decay from inception (designed for timeless facts and relationships). We need a separate **temporal events** data model.

### 1.2 EODHD underutilisation

The `FundamentalsConsumer` in S7 currently reads the EODHD fundamentals payload stored in MinIO and only extracts `General.Description`. Several other EODHD endpoints and payload sections are entirely unused:

**Fundamentals payload (already fetched, stored in MinIO) — unused structured fields**:
- `General.FullTimeEmployees` (integer): Headcount — enriches entity `metadata` for description quality
- `Highlights.RevenueTTM` (integer): Annual revenue in USD — useful for entity context narrative
- `SharesStats.PercentInsiders` (float): % shares held by insiders — institutional signal
- `SharesStats.PercentInstitutions` (float): % shares held by institutions — ownership concentration signal

**EODHD Insider Transactions API** (`GET /insider-transactions?code={ticker}`): Form 4 filings for US companies. Contains `ownerName` + `ownerTitle` (CEO, CFO, Director, etc.) + transaction details (buy/sell). This is the **correct source** for `has_executive` relations (company → person entity). Insider transaction data also provides an **insider sentiment signal**: buy/sell direction + transaction size indicates management confidence.

**EODHD Economic Events API** (`GET /economic-events`): Structured macroeconomic events with country, date, event type (CPI, NFP, GDP, Fed rate decisions), actual value, estimate, and surprise magnitude (`actual - estimate`). These are **pre-structured** — no NLP extraction needed. Events map directly to `temporal_events` with `event_type=MACRO, scope=NATIONAL`. The surprise magnitude is a high-signal indicator for market impact.

**EODHD Macro Indicator API** (`GET /macro-indicator/{COUNTRY}`): Annual country-level indicators (GDP, inflation, interest rates, trade balance, unemployment) for ~180 countries. Sourced from World Bank. Enriches country canonical entity descriptions with macro context — dramatically improves embedding quality for country entities used in `is_in_sector` and `revenue_from_country` graph traversals.

These data sources are critical for: "Who are TSMC's executives?", "What's the macro context for investing in Germany?", "How did the Fed rate decision surprise the market last week?".

### 1.3 Path-finding bottleneck
S7 uses SQL recursive CTEs for graph traversal. For path-finding between two entities (e.g., "What is the relationship between BlackRock and TSMC?"), multi-hop SQL joins over hash-partitioned tables are slow (200–500ms at 3 hops) and grow super-linearly with hop count. Apache AGE (PostgreSQL graph extension, already included in the Docker image) provides native Cypher `shortestPath()` queries with 20–100ms latency. A shadow sync worker that keeps AGE in sync with the relational graph would unlock efficient path-finding for the RELATIONSHIP intent in S8.

---

## §2 Target Users

| User | Pain | Desired Outcome |
|------|------|-----------------|
| Research analyst | "How does the Russia-Ukraine conflict affect grain commodity prices and which European food companies are most exposed?" | Graph traversal returns event → commodity/country entities → exposed companies |
| Portfolio manager | "Who are the executives and insiders at my watchlist companies?" | `has_executive` relations from EODHD Insider Transactions API (Worker 13D-8) |
| Quant analyst | "Find the shortest path between BlackRock and TSMC through company relations" | Cypher `shortestPath()` endpoint, sub-100ms |
| Data quality admin | "Are all relation types populated correctly from EODHD?" | Verification dashboard in admin |

---

## §3 Functional Requirements

| ID | Requirement |
|----|-------------|
| F-001 | New `temporal_events` table in `intelligence_db` (owned by intelligence-migrations) for geopolitical/regulatory/macro events |
| F-002 | New `entity_event_exposures` table for company-specific exposure links to temporal events |
| F-003 | `EventScope` enum: `LOCAL` (company-level), `REGIONAL` (multi-country subregion), `NATIONAL` (country-level), `GLOBAL` (sector/industry-level) |
| F-004 | GLOBAL-scope events link to sector/industry canonical entities only; company-level exposure inferred at query time via `is_in_sector` traversal — no per-company rows created |
| F-005 | New S6 Block 13E enhancement: when NLP pipeline detects geopolitical events in enriched articles, produces `temporal_events` records via a new Kafka event `intelligence.temporal_event.v1` |
| F-006 | EODHD `FundamentalsConsumer` (S7 Worker 13D-5) extracts from fundamentals payload: `General.FullTimeEmployees` (entity metadata), `Highlights.RevenueTTM` (entity context), `SharesStats.PercentInsiders` + `PercentInstitutions` (ownership signals stored in entity metadata) |
| F-007 | New relation types added to `relation_type_registry` seed data: `has_executive`, `revenue_from_country`, `operates_in_country` |
| F-008 | AGE extension enabled in `intelligence_db` via migration 0004; graph schema created: vertex labels `Entity`, `TemporalEvent`; edge labels for all relation types + event exposures |
| F-009 | New S7 Worker 13F: AGE shadow sync — periodic (every 15 min) watermark-based sync from relational tables to AGE graph |
| F-010 | New S7 endpoints: `POST /api/v1/graph/cypher/path` (shortest path, max 5 hops) and `POST /api/v1/graph/cypher/neighborhood` (egocentric Cypher neighborhood) |
| F-011 | S8 RELATIONSHIP intent uses `POST /api/v1/graph/cypher/path` when two entities are resolved and `KNOWLEDGE_GRAPH_CYPHER_ENABLED=true` |
| F-012 | Temporal event query endpoint: `GET /api/v1/temporal-events` — list active events filtered by scope, entity_id, date range |
| F-013 | New S7 Worker 13D-6: EODHD Economic Events ingestion — polls `GET /economic-events` daily per country (US, DE, GB, JP, CN, EU), upserts `temporal_events` with `event_type=MACRO, scope=NATIONAL`; includes surprise magnitude (`actual - estimate`) in description |
| F-014 | New S7 Worker 13D-7: EODHD Macro Indicator enrichment — periodically fetches `GET /macro-indicator/{COUNTRY}` for country canonical entities, updates entity `metadata` with key indicators (GDP, inflation, interest rate, unemployment); triggers re-embedding via `entity.dirtied.v1` |
| F-015 | New S7 Worker 13D-8: EODHD Insider Transactions — periodically fetches `GET /insider-transactions?code={ticker}` for all tracked companies, upserts `has_executive` relations (company → person entity) using `ownerName` + `ownerTitle`; transaction direction stored as evidence text (insider sentiment signal) |
| F-016 | `temporal_events` table extended with `region` attribute (ISO-3166 alpha-2 region tag, e.g. `US`, `EU`, `GLOBAL`, `APAC`); at query time (S8), events are filtered by region relevance to the entity being discussed and injected into LLM context as "active macro/geopolitical context" |

---

## §4 Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-001 | AGE Cypher path query: p95 latency < 100ms for max 5 hops over ≤100K entity graph |
| NFR-002 | AGE shadow sync: lag ≤ 15 minutes between relational write and AGE graph update |
| NFR-003 | EODHD enrichment: idempotent — re-processing the same fundamentals payload produces the same set of relations |
| NFR-004 | Temporal events: insertion from NLP pipeline is non-blocking (fire-and-forget via Kafka, not synchronous) |
| NFR-005 | `temporal_events` scope-based query: company exposure to GLOBAL events must complete in < 200ms via `is_in_sector` JOIN (not scan of all entities) |
| NFR-006 | `KNOWLEDGE_GRAPH_CYPHER_ENABLED` feature flag: when `false`, Cypher endpoints return 503 and S8 falls back to SQL-based traversal |

---

## §5 Out of Scope

- Real-time event ingestion (geopolitical events are batch/NLP-driven, not WebSocket)
- User-created custom events or manual event annotations (admin-only in v1)
- AGE Cypher `MATCH` queries with arbitrary Cypher (only predefined path patterns — no Cypher injection)
- Streaming graph updates (all sync is periodic watermark, not event-driven)
- Geographic revenue maps / choropleth visualisation (deferred to PRD-0019 frontend)
- ESG integration (separate initiative)
- Sanctions screening (regulatory/compliance feature, separate system)

---

## §6 Technical Design

### §6.1 Affected Services

| Service | Changes |
|---------|---------|
| `intelligence-migrations` | Migration 0004: AGE extension + schema; Migration 0003: cleanup orphan embeddings (PRD-0017 scope — must run first) |
| S6 NLP Pipeline | New Block 13E enhancement: temporal event detection → `intelligence.temporal_event.v1` Kafka event |
| S7 Knowledge Graph | New Worker 13F (AGE sync); enhanced `FundamentalsConsumer` (metadata enrichment); new Workers 13D-6 (Economic Events), 13D-7 (Macro Indicators), 13D-8 (Insider Transactions); new `TemporalEventRepository`; new relation type constants; new Cypher endpoints |
| S8 RAG/Chat | RELATIONSHIP intent uses Cypher path endpoint when available; adds temporal event context to SIGNAL_INTEL retrieval |
| `libs/contracts` | New Avro schema: `intelligence.temporal_event.v1` |

---

### §6.2 Temporal Events Data Model

#### The Ephemeral Event Lifecycle

Unlike relations (which model timeless facts with continuous confidence decay), temporal events have a **binary activation lifecycle**:

```
PENDING_ACTIVE → ACTIVE (at active_from) → ENDED (at active_until) → RESIDUAL (residual_impact_days) → EXPIRED
```

- **ACTIVE**: Event is current and material; full impact
- **ENDED**: Event has concluded; impact is decaying (residual)
- **RESIDUAL**: Post-event period; impact weight = `exp(-0.02 × days_since_end)` (50-day half-life)
- **EXPIRED**: `days_since_end > residual_impact_days`; event excluded from active context

This lifecycle is managed entirely in the application layer. The DB stores only `active_from`, `active_until` (nullable), and `residual_impact_days`. Query time determines the current lifecycle phase.

#### EventScope Design

| Scope | Meaning | Entity links created | Query-time expansion |
|-------|---------|---------------------|---------------------|
| LOCAL | Affects a specific company or small group | `entity_event_exposures` rows per company | Direct lookup |
| REGIONAL | Affects a geographic region (EU, ASEAN) | `entity_event_exposures` for country entities in region | Via country entities |
| NATIONAL | Affects a country's economy | `entity_event_exposures` for country entity | Via `headquartered_in` + `revenue_from_country` at query time |
| GLOBAL | Affects entire sectors/industries (pandemics, rate cycles) | `entity_event_exposures` for sector/industry entities ONLY | Via `is_in_sector` traversal — no per-company rows |

**The GLOBAL explosion problem**: A GLOBAL event like "COVID-19 pandemic" cannot create rows for every company. The solution: link the event to sector/industry canonical entities (e.g., `entity_id` of the "Airlines" industry entity). At query time, to get exposed companies: traverse `SELECT ce.entity_id FROM canonical_entities ce WHERE ce.metadata->>'industry' = :industry_entity_name`. This keeps `entity_event_exposures` bounded.

---

### §6.3 API Changes

#### NEW — `GET /api/v1/temporal-events` (S7)

List active or historical temporal events.

- **Auth**: none (public read)
- **Query Parameters**:

| Param | Type | Required | Default | Validation | Description |
|-------|------|----------|---------|------------|-------------|
| scope | string | no | null | `LOCAL\|REGIONAL\|NATIONAL\|GLOBAL` | Filter by scope |
| entity_id | UUID | no | null | valid UUID | Filter events where entity is exposed |
| active_only | bool | no | true | — | If true, exclude EXPIRED events |
| event_type | string | no | null | max 50 chars | Filter by event type (e.g. `geopolitical`, `regulatory`, `macro`) |
| region | string | no | null | ISO-3166 alpha-2 or `EU\|APAC\|GLOBAL` | Filter by region tag (for query-time global event injection) |
| from_date | date | no | null | ISO-8601 | Events active_from >= from_date |
| to_date | date | no | null | ISO-8601 | Events active_from <= to_date |
| limit | int | no | 50 | 1–200 | Result page size |
| offset | int | no | 0 | ≥ 0 | Pagination |

- **Response** (200):

```json
{
  "events": [
    {
      "event_id": "...",
      "event_type": "geopolitical",
      "scope": "GLOBAL",
      "title": "US-China Technology Trade Restrictions",
      "description": "Escalating semiconductor export controls affecting US-China tech trade",
      "active_from": "2022-10-07T00:00:00Z",
      "active_until": null,
      "residual_impact_days": 365,
      "lifecycle_phase": "ACTIVE",
      "confidence": 0.92,
      "exposed_entity_count": 3,
      "created_at": "2024-01-15T08:22:10Z"
    }
  ],
  "total": 47
}
```

#### NEW — `POST /api/v1/graph/cypher/path` (S7)

Find shortest path(s) between two entities using Apache AGE Cypher.

- **Auth**: none (public)
- **Feature flag**: Returns 503 if `KNOWLEDGE_GRAPH_CYPHER_ENABLED=false`
- **Request body**:

| Field | Type | Required | Default | Validation | Description |
|-------|------|----------|---------|------------|-------------|
| source_entity_id | UUID | yes | — | valid UUID | Start entity |
| target_entity_id | UUID | yes | — | valid UUID | End entity; must differ from source |
| max_hops | int | no | 3 | 1–5 | Maximum path length (hard cap: 5) |
| min_confidence | float | no | 0.3 | 0.0–1.0 | Minimum relation confidence on path |
| relation_types | `string[]` | no | null | each max 50 chars | Filter path edges by canonical_type; null = all types |
| all_paths | bool | no | false | — | If true, return up to 5 shortest paths; if false, return only shortest |

- **Response** (200):

```json
{
  "source_entity_id": "...",
  "target_entity_id": "...",
  "paths": [
    {
      "hops": 2,
      "nodes": [
        {"entity_id": "...", "canonical_name": "BlackRock", "entity_type": "financial_institution"},
        {"entity_id": "...", "canonical_name": "iShares MSCI Taiwan ETF", "entity_type": "financial_instrument"},
        {"entity_id": "...", "canonical_name": "Taiwan Semiconductor", "entity_type": "financial_instrument"}
      ],
      "edges": [
        {"from": "...", "to": "...", "canonical_type": "investment_in", "confidence": 0.87, "direction": "forward"},
        {"from": "...", "to": "...", "canonical_type": "competes_with", "confidence": 0.61, "direction": "forward"}
      ],
      "path_confidence": 0.53
    }
  ],
  "paths_found": 1,
  "query_time_ms": 42
}
```

`path_confidence = product(edge.confidence for edge in path)` — lower is weaker.

- **Error responses**:
  - 404: source or target entity not found
  - 422: `source_entity_id == target_entity_id`, or `max_hops > 5`
  - 503: AGE not enabled (`KNOWLEDGE_GRAPH_CYPHER_ENABLED=false`)
  - 504: Query timeout (5s hard limit)

#### NEW — `POST /api/v1/graph/cypher/neighborhood` (S7)

Get egocentric neighborhood using Cypher (richer than existing SQL-based `/entities/{id}/graph`).

- **Auth**: none (public)
- **Feature flag**: Returns 503 if `KNOWLEDGE_GRAPH_CYPHER_ENABLED=false`
- **Request body**:

| Field | Type | Required | Default | Validation | Description |
|-------|------|----------|---------|------------|-------------|
| entity_id | UUID | yes | — | valid UUID | Center entity |
| max_hops | int | no | 2 | 1–3 | Neighborhood depth (max 3 for neighborhood; 5 for path) |
| min_confidence | float | no | 0.4 | 0.0–1.0 | Minimum relation confidence |
| include_temporal_events | bool | no | true | — | Include active temporal event nodes adjacent to entities |
| limit | int | no | 50 | 1–200 | Max relations to return |

- **Response**: Same as existing `/entities/{id}/graph` + `temporal_events[]` section when `include_temporal_events=true`

---

### §6.4 Database Changes

#### `intelligence-migrations` — Migration 0004: AGE Extension + Schema

```sql
-- Step 1: Enable AGE extension
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- Step 2: Create AGE graph
SELECT create_graph('worldview_graph');

-- Step 3: Create vertex labels
SELECT create_vlabel('worldview_graph', 'Entity');
SELECT create_vlabel('worldview_graph', 'TemporalEvent');

-- Step 4: Create edge labels (one per canonical relation type)
SELECT create_elabel('worldview_graph', 'EMPLOYS');
SELECT create_elabel('worldview_graph', 'BOARD_MEMBER_OF');
SELECT create_elabel('worldview_graph', 'SUBSIDIARY_OF');
SELECT create_elabel('worldview_graph', 'ACQUIRED_BY');
SELECT create_elabel('worldview_graph', 'LISTED_ON');
SELECT create_elabel('worldview_graph', 'SUPPLIER_OF');
SELECT create_elabel('worldview_graph', 'PARTNER_OF');
SELECT create_elabel('worldview_graph', 'COMPETES_WITH');
SELECT create_elabel('worldview_graph', 'REGULATES');
SELECT create_elabel('worldview_graph', 'HEADQUARTERED_IN');
SELECT create_elabel('worldview_graph', 'ANALYST_RATING');
SELECT create_elabel('worldview_graph', 'MARKET_SHARE_CLAIM');
SELECT create_elabel('worldview_graph', 'PRICE_TARGET');
SELECT create_elabel('worldview_graph', 'EARNINGS_GUIDANCE');
SELECT create_elabel('worldview_graph', 'SENTIMENT_SIGNAL');
SELECT create_elabel('worldview_graph', 'CREDIT_RATING');
SELECT create_elabel('worldview_graph', 'INVESTMENT_IN');
SELECT create_elabel('worldview_graph', 'OWNS_STAKE_IN');
SELECT create_elabel('worldview_graph', 'ISSUES_DEBT');
SELECT create_elabel('worldview_graph', 'PRODUCES');
SELECT create_elabel('worldview_graph', 'HAS_EXECUTIVE');
SELECT create_elabel('worldview_graph', 'REVENUE_FROM_COUNTRY');
SELECT create_elabel('worldview_graph', 'OPERATES_IN_COUNTRY');
SELECT create_elabel('worldview_graph', 'EVENT_EXPOSES');  -- TemporalEvent → Entity edge
```

**AGE storage estimate**: Each vertex ~200 bytes + each edge ~150 bytes.
- 50K entities × 200B = 10MB for vertices
- 500K relations × 150B = 75MB for edges
- Total AGE shadow: ~85MB (additional to relational tables)
- **Full DB overhead with AGE internal indexes**: ~375MB (30% of base relational size)

#### NEW table: `temporal_events` (intelligence_db)

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| event_id | UUID | no | — | PK | App-generated UUIDv7 |
| event_type | TEXT | no | — | CHECK IN ('geopolitical','regulatory','macro','sanctions','natural_disaster','other') | Event category |
| scope | TEXT | no | — | CHECK IN ('LOCAL','REGIONAL','NATIONAL','GLOBAL') | Impact scope |
| region | TEXT | yes | null | — | ISO-3166 alpha-2 country/region tag + special values: `EU`, `APAC`, `LatAm`, `MENA`, `GLOBAL`; used for query-time filtering |
| title | TEXT | no | — | max_length=500 | Short event title |
| description | TEXT | yes | null | — | Longer narrative; for MACRO events includes surprise magnitude (actual - estimate) |
| source_article_ids | UUID[] | yes | null | — | CanonicalDocument IDs that evidence this event; empty for EODHD-structured events |
| source_url | TEXT | yes | null | — | Primary source URL or EODHD API reference |
| active_from | TIMESTAMPTZ | no | — | — | Event start date (UTC) |
| active_until | TIMESTAMPTZ | yes | null | — | Event end date; null = still active |
| residual_impact_days | INT | no | 90 | CHECK ≥ 0 | Days of residual impact after end |
| confidence | NUMERIC(4,3) | no | — | CHECK 0 ≤ confidence ≤ 1 | NLP confidence or 1.0 for structured EODHD events |
| created_at | TIMESTAMPTZ | no | now() | — | UTC |
| updated_at | TIMESTAMPTZ | no | now() | — | UTC, updated on merge |

**Indexes**:
- `(scope, active_from)` — for scope-filtered queries
- `(active_from, active_until)` — for temporal range queries
- `(event_type, scope)` — for type+scope filter
- `(region, active_from DESC)` — for query-time global event filtering by region
- UNIQUE `(event_type, region, title, date_trunc('day', active_from))` — natural deduplication key for EODHD economic events

**Estimated rows**: ~10K/year (geopolitical + MACRO economic events; MACRO events alone: ~6 countries × 20 events/month × 12 = ~1,440/year)

#### NEW table: `entity_event_exposures` (intelligence_db)

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| exposure_id | UUID | no | — | PK | App-generated UUIDv7 |
| event_id | UUID | no | — | FK → temporal_events | Not null |
| entity_id | UUID | no | — | logical FK → canonical_entities | Not null |
| exposure_type | TEXT | no | — | CHECK IN ('directly_affected','operationally_impacted','supply_chain','revenue_geography','sector_exposure') | How the entity is exposed |
| evidence_text | TEXT | yes | null | — | Extracted evidence snippet |
| confidence | NUMERIC(4,3) | no | — | CHECK 0 ≤ confidence ≤ 1 | Exposure confidence |
| created_at | TIMESTAMPTZ | no | now() | — | UTC |

**Unique constraint**: `(event_id, entity_id, exposure_type)` — prevents duplicate exposure records

**Indexes**:
- `(event_id)` — lookup exposures by event
- `(entity_id)` — lookup events by entity
- UNIQUE `(event_id, entity_id, exposure_type)`

**Estimated rows**: ~20K/year (sparse — GLOBAL events link to sectors only, not companies)

#### NEW relation types in `relation_type_registry` seed

3 new rows to be added via migration 0004:

| canonical_type | decay_class | semantic_mode | description |
|----------------|-------------|---------------|-------------|
| `has_executive` | `DURABLE` | `RELATION_STATE` | Company employs person in executive/board role |
| `revenue_from_country` | `MEDIUM` | `TEMPORAL_CLAIM` | Company derives significant revenue from country |
| `operates_in_country` | `SLOW` | `RELATION_STATE` | Company has operational presence in country |

---

### §6.5 Kafka Schema Changes

#### NEW — `intelligence.temporal_event.v1`

- **Topic**: `intelligence.temporal_event.v1`
- **Partition key**: `event_id`
- **Retention**: 14 days (longer than standard — events are low-volume)
- **Producers**: S6 NLP Pipeline (Block 13E)
- **Consumers**: S7 Knowledge Graph (`TemporalEventConsumer` — new)
- **Compaction**: none (temporal events are append-only)

**Avro schema** (`infra/kafka/schemas/intelligence.temporal_event.v1.avsc`):

| Field | Type | Default | Nullable | Description |
|-------|------|---------|----------|-------------|
| event_id | string | — | no | UUIDv7 |
| event_type | string | — | no | `geopolitical\|regulatory\|macro\|sanctions\|natural_disaster\|other` |
| scope | string | — | no | `LOCAL\|REGIONAL\|NATIONAL\|GLOBAL` |
| region | string | `""` | no | ISO-3166 alpha-2 or `EU\|APAC\|LatAm\|MENA\|GLOBAL`; empty for local events |
| title | string | — | no | Short title (max 500) |
| description | string | `""` | no | Narrative description; for MACRO includes surprise magnitude |
| source_article_ids | `{type:"array",items:"string"}` | `[]` | no | CanonicalDocument UUIDs; empty for structured EODHD events |
| source_url | string | `""` | no | Primary source URL |
| active_from | string | — | no | ISO-8601 UTC |
| active_until | string | `""` | no | ISO-8601 UTC; empty string = still active |
| residual_impact_days | int | 90 | no | Residual impact period in days |
| confidence | float | — | no | 0.0–1.0 |
| exposed_entities | `{type:"array",items:{type:"record",name:"ExposedEntity",fields:[...]}}` | `[]` | no | Array of `{entity_id, exposure_type, confidence}` |
| occurred_at | string | — | no | ISO-8601 UTC (event envelope field) |
| schema_version | int | 1 | no | Schema version |

**`ExposedEntity` inline record**:

| Field | Type | Default | Nullable | Description |
|-------|------|---------|----------|-------------|
| entity_id | string | — | no | UUIDv7 |
| exposure_type | string | — | no | `directly_affected\|operationally_impacted\|supply_chain\|revenue_geography\|sector_exposure` |
| confidence | float | — | no | 0.0–1.0 |

---

### §6.6 Domain Model Changes

#### S7 — New Domain Entities

**`TemporalEvent`** (frozen dataclass):

| Attribute | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| event_id | UUID | yes | UUIDv7 | Identifier |
| event_type | EventType | yes | enum | geopolitical/regulatory/macro/sanctions/natural_disaster/other |
| scope | EventScope | yes | enum | LOCAL/REGIONAL/NATIONAL/GLOBAL |
| region | str | no | ISO-3166-alpha-2 or special tag | Region for query-time filtering; None for LOCAL events |
| title | str | yes | max 500 chars | Short title |
| description | str | no | — | Narrative; for MACRO includes surprise magnitude |
| source_article_ids | `tuple[UUID, ...]` | yes | — | Source evidence; empty tuple for EODHD-structured events |
| active_from | datetime | yes | UTC-aware | Event start |
| active_until | datetime | no | UTC-aware or None | Event end; None = ongoing |
| residual_impact_days | int | yes | ≥ 0 | Post-end impact period |
| confidence | float | yes | 0.0–1.0 | Extraction confidence; 1.0 for EODHD-structured events |
| created_at | datetime | yes | UTC-aware | Record creation |

**Computed property**:
```python
@property
def lifecycle_phase(self) -> str:
    now = utc_now()
    if now < self.active_from:
        return "PENDING_ACTIVE"
    if self.active_until is None or now <= self.active_until:
        return "ACTIVE"
    days_since_end = (now - self.active_until).days
    if days_since_end <= self.residual_impact_days:
        return "RESIDUAL"
    return "EXPIRED"

@property
def current_impact_weight(self) -> float:
    """Impact weight: 1.0 if ACTIVE, exp(-0.02 × days_since_end) if RESIDUAL, 0.0 if EXPIRED."""
    phase = self.lifecycle_phase
    if phase == "ACTIVE":
        return 1.0
    if phase == "RESIDUAL":
        days_since_end = (utc_now() - self.active_until).days  # type: ignore
        return math.exp(-0.02 * days_since_end)
    return 0.0
```

**`EntityEventExposure`** (frozen dataclass):

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| exposure_id | UUID | yes | UUIDv7 |
| event_id | UUID | yes | FK → TemporalEvent |
| entity_id | UUID | yes | FK → canonical_entities |
| exposure_type | ExposureType | yes | Enum |
| evidence_text | str | no | Snippet |
| confidence | float | yes | 0.0–1.0 |

**`EventScope`** (StrEnum): `LOCAL`, `REGIONAL`, `NATIONAL`, `GLOBAL`

**`EventType`** (StrEnum): `GEOPOLITICAL`, `REGULATORY`, `MACRO`, `SANCTIONS`, `NATURAL_DISASTER`, `OTHER`

**`ExposureType`** (StrEnum): `DIRECTLY_AFFECTED`, `OPERATIONALLY_IMPACTED`, `SUPPLY_CHAIN`, `REVENUE_GEOGRAPHY`, `SECTOR_EXPOSURE`

---

#### S7 — New Worker 13F: AGE Shadow Sync

```python
class AgeSyncWorker:
    """Worker 13F: Periodic watermark-based sync from relational tables to Apache AGE.

    Reads canonical_entities + relations WHERE updated_at > last_sync_watermark.
    Uses MERGE Cypher to upsert vertices and edges in the AGE graph.
    Runs every 15 minutes via APScheduler.

    Watermark stored in Valkey: s7:age:sync:watermark (ISO-8601 UTC string).
    Initial watermark: epoch (syncs all existing data on first run).
    """

    async def run(self) -> None:
        watermark = await self._get_watermark()
        new_watermark = utc_now()
        await self._sync_entities(since=watermark)
        await self._sync_relations(since=watermark)
        await self._sync_temporal_events(since=watermark)
        await self._set_watermark(new_watermark)
```

**Algorithm detail**:

1. Read watermark from Valkey `s7:age:sync:watermark`; default to epoch if missing
2. Query `canonical_entities WHERE updated_at > watermark LIMIT 1000` (paginate)
3. For each entity: execute AGE Cypher:
   ```cypher
   MERGE (e:Entity {entity_id: $entity_id})
   SET e.canonical_name = $name, e.entity_type = $type, e.ticker = $ticker, e.updated_at = $updated_at
   ```
4. Query `relations WHERE updated_at > watermark AND confidence > 0.1 LIMIT 5000` (paginate)
5. For each relation: execute AGE Cypher:
   ```cypher
   MATCH (s:Entity {entity_id: $subject_id}), (o:Entity {entity_id: $object_id})
   MERGE (s)-[r:RELATION_TYPE {relation_id: $relation_id}]->(o)
   SET r.confidence = $confidence, r.updated_at = $updated_at
   ```
   Where `RELATION_TYPE` is derived from `canonical_type` (uppercase, spaces→underscores)
6. Sync `temporal_events` to `TemporalEvent` AGE vertices
7. Sync `entity_event_exposures` to `EVENT_EXPOSES` edges
8. Update watermark in Valkey to `new_watermark`
9. Emit Prometheus metrics: `s7_age_sync_entities_total`, `s7_age_sync_relations_total`, `s7_age_sync_duration_seconds`

**Note on dual-write trade-off**: AGE is a shadow copy — NOT the source of truth. The relational tables remain authoritative. The 15-minute sync lag is acceptable for path-finding queries (historical relationships don't change that fast). For real-time queries (S8 pipeline), the SQL neighborhood endpoint still works without AGE. The Cypher path endpoint is additive.

---

#### S7 — Enhanced FundamentalsConsumer

**Current**: Downloads EODHD fundamentals JSON from MinIO; extracts `General.Description`; triggers `DefinitionRefreshWorker` if description changed.

**Enhanced**: After existing description processing, extract and upsert structured fields from the payload:

**A. Entity metadata enrichment** (no relations — updates `canonical_entities.metadata`)

EODHD fields that exist and are reliably populated:
- `General.FullTimeEmployees` → stored as `entity.metadata["employee_count"]`
- `Highlights.RevenueTTM` → stored as `entity.metadata["revenue_ttm_usd"]`
- `SharesStats.PercentInsiders` → stored as `entity.metadata["pct_insiders"]`
- `SharesStats.PercentInstitutions` → stored as `entity.metadata["pct_institutions"]`

```python
general = payload.get("General", {})
highlights = payload.get("Highlights", {})
shares_stats = payload.get("SharesStats", {})

metadata_updates = {}
if emp := general.get("FullTimeEmployees"):
    metadata_updates["employee_count"] = int(emp)
if rev := highlights.get("RevenueTTM"):
    metadata_updates["revenue_ttm_usd"] = int(rev)
if pct_ins := shares_stats.get("PercentInsiders"):
    metadata_updates["pct_insiders"] = float(pct_ins)
if pct_inst := shares_stats.get("PercentInstitutions"):
    metadata_updates["pct_institutions"] = float(pct_inst)

if metadata_updates:
    await entity_repo.update_metadata(company_entity_id, metadata_updates)
```

These values are factored into the entity's `narrative` embedding source text, improving search quality for queries like "large US tech company with high institutional ownership".

**Idempotency**: Metadata updates are idempotent — same payload re-processed produces same metadata values.

> **Note**: `General.Officers`, `Financials.Revenue_Segment`, and `Holders.Institutions` are **not available** in the EODHD fundamentals payload at the subscription tier in use. See §1.2 for correct data sources for `has_executive` relations (Insider Transactions API — Worker 13D-8) and ownership signals (PercentInsiders/PercentInstitutions above).

---

#### S7 — New Worker 13D-6: EODHD Economic Events Ingestion

**Purpose**: Poll EODHD Economic Events API daily and upsert structured macro events as `temporal_events` with `event_type=MACRO`.

**Schedule**: APScheduler daily job, runs at 06:00 UTC (markets closed overnight; events from prior day available).

**EODHD endpoint**: `GET /economic-events?country={iso2}&from={yesterday}&to={today}&fmt=json`

**Countries tracked** (configurable via `KNOWLEDGE_GRAPH_ECONOMIC_EVENT_COUNTRIES`): `US,DE,GB,JP,CN,EU` (default — major market movers).

**Processing logic**:
```python
for country in countries:
    events = await eodhd_client.get_economic_events(country=country, from_date=yesterday)
    for ev in events:
        if ev["actual"] is None:
            continue  # Skip unreleased scheduled events

        surprise = None
        if ev["actual"] is not None and ev["estimate"] is not None:
            surprise = ev["actual"] - ev["estimate"]

        title = f"{ev['type']} ({country}) — {ev['period']}"
        description_parts = [f"Actual: {ev['actual']}, Previous: {ev['previous']}"]
        if surprise is not None:
            direction = "beat" if surprise > 0 else "missed"
            description_parts.append(f"Estimate {direction} by {abs(surprise):.2f} ({ev['change_percentage']:.1f}%)")

        await temporal_event_repo.upsert_by_natural_key(
            event_type="macro",
            scope="NATIONAL",
            region=country,
            title=title,
            description="; ".join(description_parts),
            active_from=parse_event_date(ev["date"]),
            active_until=parse_event_date(ev["date"]) + timedelta(hours=24),  # point-in-time events
            residual_impact_days=30,  # macro events have 30-day residual
            confidence=1.0,  # structured data, no NLP uncertainty
        )
        # Link to country canonical entity
        country_entity_id = await entity_repo.find_country_entity(country)
        if country_entity_id:
            await exposure_repo.upsert(
                event_id=event_id,
                entity_id=country_entity_id,
                exposure_type="directly_affected",
                confidence=1.0,
            )
```

**Deduplication key**: `(event_type='macro', region=country, title, active_from::date)` — prevents duplicates across daily runs.

---

#### S7 — New Worker 13D-7: EODHD Macro Indicator Enrichment

**Purpose**: Enrich country canonical entity metadata with World Bank macro indicators; triggers re-embedding when indicators change.

**Schedule**: APScheduler weekly job (Sunday 03:00 UTC) — indicators are annual, weekly refresh is sufficient.

**EODHD endpoint**: `GET /macro-indicator/{ISO3_COUNTRY}?indicator={indicator}&fmt=json`

Note: Macro Indicator API uses **ISO 3166-1 alpha-3** codes (USA, GBR, DEU, JPN, CHN) — different from Economic Events API which uses alpha-2.

**Indicators fetched per country**:
| Indicator code | Description |
|---|---|
| `gdp_current_usd` | GDP (current USD) |
| `gdp_growth_annual` | GDP growth rate (annual %) |
| `inflation_consumer_prices_annual` | CPI inflation (annual %) |
| `real_interest_rate` | Real interest rate (%) |
| `unemployment_total_pct` | Unemployment rate (%) |
| `current_account_balance_bop_usd` | Current account balance (USD) |

**Processing logic**:
```python
for iso3, iso2 in country_map.items():  # e.g. {"USA": "US", "GBR": "GB", ...}
    country_entity_id = await entity_repo.find_country_entity(iso2)
    if not country_entity_id:
        continue

    macro_data = {}
    for indicator_code in MACRO_INDICATORS:
        result = await eodhd_client.get_macro_indicator(iso3, indicator_code)
        if result:
            # Take most recent value (results are sorted by date desc)
            latest = result[0]
            macro_data[indicator_code] = {"value": latest["Value"], "year": latest["Period"]}

    if macro_data:
        old_hash = await entity_repo.get_metadata_hash(country_entity_id, "macro_indicators")
        new_hash = sha256_hex(json.dumps(macro_data, sort_keys=True))
        if old_hash != new_hash:
            await entity_repo.update_metadata(country_entity_id, {"macro_indicators": macro_data})
            # Trigger re-embedding by dirtying the entity
            await kafka_producer.produce("entity.dirtied.v1", {"entity_id": str(country_entity_id)})
```

**Idempotency**: Metadata JSON hash comparison prevents unnecessary re-embedding and Kafka events.

---

#### S7 — New Worker 13D-8: EODHD Insider Transactions → `has_executive` Relations

**Purpose**: Discover company executives from insider transaction filings; create `has_executive` relations (company → person entity).

**Schedule**: APScheduler weekly job (Monday 02:00 UTC) — insider transaction filings are periodic, weekly refresh is sufficient.

**EODHD endpoint**: `GET /insider-transactions?code={ticker}.US&limit=100&fmt=json`

**Coverage**: US-listed companies only (EODHD Insider Transactions API covers SEC Form 4 filers, US exchanges).

**Processing logic**:
```python
for instrument in await entity_repo.list_us_instruments():
    ticker = instrument.ticker
    transactions = await eodhd_client.get_insider_transactions(code=f"{ticker}.US", limit=100)

    # Deduplicate officers: same ownerName may appear multiple times across transactions
    seen_officers: dict[str, str] = {}  # ownerName → ownerTitle (most recent)
    for txn in transactions:
        name = txn.get("ownerName", "").strip()
        title = txn.get("ownerTitle", "").strip()
        if not name:
            continue
        # Filter noise: only C-suite, Board, and significant insiders
        if not is_executive_title(title):  # checks for CEO/CFO/COO/Director/President/10% Owner
            continue
        if name not in seen_officers:
            seen_officers[name] = title

    for officer_name, officer_title in seen_officers.items():
        person_entity_id = await entity_repo.find_or_create_person(
            officer_name, context_ticker=ticker
        )
        # transaction direction adds insider sentiment to evidence
        recent_txn = next((t for t in transactions if t["ownerName"] == officer_name), {})
        direction = "bought" if recent_txn.get("transactionAcquiredDisposed") == "A" else "sold"

        await relation_repo.upsert_relation(
            subject_entity_id=instrument.entity_id,
            object_entity_id=person_entity_id,
            canonical_type="has_executive",
            evidence_text=f"{officer_name} ({officer_title}) recently {direction} shares in {instrument.canonical_name}",
            source_weight=0.90,  # SEC filing is authoritative
            is_backfill=True,
        )
```

**`is_executive_title()` whitelist**: `{"CEO", "CFO", "COO", "CTO", "Director", "President", "Chairman", "VP", "General Counsel", "10% Owner"}` — substring match.

**Idempotency**: Existing advisory-lock upsert mechanism prevents duplicates. Re-processing same transactions produces same relations.

---

#### S6 — Block 13E Enhancement: Temporal Event Detection

The S6 NLP pipeline already extracts entities and relations from enriched articles. Block 13E (entity canonicalization) is enhanced to also detect geopolitical/regulatory/macro events:

**Detection heuristic** (applied in `EnrichedArticleConsumer.on_message()`):

```python
# If article has RoutingTier.DEEP and contains event-class mentions
if routing_tier == "deep" and any_event_mention(enriched_payload):
    event = extract_temporal_event(enriched_payload, article_metadata)
    if event.confidence >= 0.5:
        await kafka_producer.produce("intelligence.temporal_event.v1", event)
```

**`extract_temporal_event()` uses Qwen2.5:3b** (same classification model as S8 intent classifier):
- Input: article title + first 500 chars of text
- Output: `{event_type, scope, title, active_from, active_until, confidence, exposed_entities[]}`
- If Qwen unavailable: skip silently (temporal events are additive, not required)

**Exposed entities**: Only entities already resolved in the enriched article (no new entity resolution in this block). Scope defaults to `NATIONAL` for most geopolitical events; S6 sets `GLOBAL` only when the article explicitly mentions multiple countries/sectors.

---

### §6.7 S8 RAG/Chat Integration

#### RELATIONSHIP Intent — Cypher path usage

When `KNOWLEDGE_GRAPH_CYPHER_ENABLED=true` and two entities are resolved:

```python
# In retrieval step (step 6 of S8 pipeline)
if intent == QueryIntent.RELATIONSHIP and len(resolved_entities) >= 2:
    try:
        path_result = await s7_client.find_path(
            source=resolved_entities[0].entity_id,
            target=resolved_entities[1].entity_id,
            max_hops=4,
            min_confidence=0.35,
        )
        # path_result nodes/edges added as KG retrieval items
    except (S7ServiceUnavailableError, CypherDisabledError):
        # Fall back to existing SQL neighborhood
        pass
```

#### SIGNAL_INTEL Intent — Temporal event context injection

For `SIGNAL_INTEL` queries (and any intent with resolved entities), after entity resolution, fetch and inject active temporal events as "active macro/geopolitical context":

```python
active_events = await s7_client.get_temporal_events(
    entity_ids=[e.entity_id for e in resolved_entities],
    active_only=True,
)
# Inject into context as "active geopolitical context" section
```

#### Global Event Query-Time Filtering

Beyond entity-specific events, MACRO and GLOBAL events with matching `region` are injected for any query:

```python
# Determine relevant regions for the query entities
entity_regions = set()
for entity in resolved_entities:
    # Use entity metadata: country_iso, sector, industry
    if country := entity.metadata.get("country_iso"):
        entity_regions.add(country)
    entity_regions.add("GLOBAL")  # Always include global-scope events

# Fetch active macro/geopolitical events for matching regions
global_events = await s7_client.get_temporal_events_by_region(
    regions=list(entity_regions),
    event_types=["macro", "geopolitical", "regulatory"],
    active_only=True,
    limit=5,  # Top 5 most recent, sorted by active_from DESC
)
# Injected into LLM prompt as:
# "Active macro/geopolitical context:
#  - US NFP Beat (+25K, May 2026): Strong employment exceeds estimates
#  - ECB Rate Decision: ECB held rates at 3.75% (no surprise)
#  - US-China Tech Restrictions: Ongoing semiconductor export controls (ACTIVE)"
```

This ensures every query benefits from macro context even when the user doesn't explicitly ask about geopolitical events. The `region` attribute on `temporal_events` is the key enabler: events can be matched to entities by comparing entity `metadata.country_iso` to event `region`, without requiring explicit `entity_event_exposures` rows for every company.

---

### §6.8 Data Flow

#### Temporal event ingestion:
```
News article → S4 → S5 (clean + deduplicate) → nlp.article.enriched.v1 (S6)
→ S7 EnrichedArticleConsumer → Block 11+12 (entity/relation extraction)
→ Block 13E enhancement: event detection via Qwen2.5:3b
→ if confidence ≥ 0.5: produce intelligence.temporal_event.v1
→ S7 TemporalEventConsumer:
  → upsert temporal_events table
  → create entity_event_exposures rows (scope-tiered)
  → AGE sync picks up at next 15-min window
```

#### EODHD fundamentals metadata enrichment:
```
market.dataset.fetched (S2→S4) → S7 FundamentalsConsumer:
→ Download from MinIO
→ Extract General.Description (existing — change detection + re-embedding)
→ Extract General.FullTimeEmployees → entity.metadata["employee_count"]
→ Extract Highlights.RevenueTTM → entity.metadata["revenue_ttm_usd"]
→ Extract SharesStats.PercentInsiders → entity.metadata["pct_insiders"]
→ Extract SharesStats.PercentInstitutions → entity.metadata["pct_institutions"]
→ entity.dirtied.v1 produced if metadata changed
```

#### EODHD Economic Events ingestion (Worker 13D-6):
```
[Daily 06:00 UTC, APScheduler]
→ EODHD GET /economic-events?country={US,DE,GB,JP,CN,EU}&from=yesterday
→ For each released event (actual ≠ null):
  → Compute surprise magnitude: actual - estimate
  → Upsert temporal_events (event_type=MACRO, scope=NATIONAL, region=country)
  → Link to country canonical entity via entity_event_exposures
→ Emit metrics: s7_economic_events_ingested_total{country}
```

#### EODHD Macro Indicator enrichment (Worker 13D-7):
```
[Weekly Sunday 03:00 UTC, APScheduler]
→ For each tracked country (USA, GBR, DEU, JPN, CHN, ...):
  → EODHD GET /macro-indicator/{ISO3}?indicator={gdp|inflation|rates|unemployment}
  → Compare JSON hash with stored metadata hash
  → If changed: update entity.metadata["macro_indicators"]
  → Produce entity.dirtied.v1 → triggers re-embedding in S6 DefinitionRefreshWorker
```

#### EODHD Insider Transactions → has_executive relations (Worker 13D-8):
```
[Weekly Monday 02:00 UTC, APScheduler]
→ For each US-listed instrument tracked:
  → EODHD GET /insider-transactions?code={TICKER}.US&limit=100
  → Deduplicate by ownerName → extract unique executives (title whitelist filter)
  → find_or_create_person(ownerName) → person canonical entity
  → Upsert has_executive relation: company → person
  → Evidence text includes transaction direction (insider sentiment)
→ entity.dirtied.v1 for each company with new/changed officers
```

#### AGE shadow sync:
```
[Every 15 minutes, APScheduler Worker 13F]
→ Read watermark from Valkey (s7:age:sync:watermark)
→ Query canonical_entities WHERE updated_at > watermark
→ Cypher MERGE Entity vertices
→ Query relations WHERE updated_at > watermark AND confidence > 0.1
→ Cypher MERGE relation edges (dynamically select edge label from canonical_type)
→ Query temporal_events WHERE updated_at > watermark
→ Cypher MERGE TemporalEvent vertices + EVENT_EXPOSES edges
→ Update watermark in Valkey
→ Emit metrics
```

#### Cypher path query (S8 → S7 → AGE):
```
S8 RELATIONSHIP intent → POST /api/v1/graph/cypher/path (S7)
→ CypherPathUseCase.execute()
→ Validate both entities exist in canonical_entities (SQL)
→ Execute Cypher via AGE:
  SELECT * FROM ag_catalog.cypher('worldview_graph', $$
    MATCH path = shortestPath((s:Entity {entity_id: $source})-[r*1..5]->(t:Entity {entity_id: $target}))
    WHERE ALL(rel IN relationships(path) WHERE rel.confidence >= $min_conf)
    RETURN path
  $$, $params) AS (path ag_catalog.agtype)
→ Parse path → CypherPathResult
→ Return to S8
→ S8 formats path as KG retrieval items for context assembly
```

---

## §7 Architecture Decision Records

### ADR-0018-001: Temporal events as separate table, not in `relations`

**Decision**: `temporal_events` is a new table, not rows in `relations`.
**Alternatives**: (A) Add `is_event` boolean to `relations`; (B) New `event_type` semantic mode in `relations`
**Rationale**: Relations use continuous confidence decay from inception. Events have binary activation (PENDING → ACTIVE → ENDED → RESIDUAL). Cramming events into `relations` would require special-casing the confidence formula, decay class, and query logic. Separate table is cleaner, more maintainable, and allows event-specific fields (scope, active_until, residual_impact_days).

### ADR-0018-002: AGE sync is periodic watermark, not event-driven

**Decision**: AGE shadow sync runs every 15 minutes reading `updated_at > watermark`.
**Alternatives**: (A) Dual-write to AGE on every relation upsert; (B) Consume `entity.dirtied.v1` to trigger sync
**Rationale**: Dual-write couples every relation write to AGE availability — an AGE outage would break the hot path. `entity.dirtied.v1` requires AGE consumer to deserialize Avro, adds consumer group lag, and makes ordering hard. Periodic watermark is the simplest, most resilient approach. 15-minute lag is acceptable for path-finding queries.

### ADR-0018-003: GLOBAL events link to sectors, not companies

**Decision**: GLOBAL-scope temporal events link via `entity_event_exposures` to sector/industry canonical entities only. Company exposure is inferred at query time via `is_in_sector`.
**Alternatives**: (A) Create exposures for every company in affected sectors (thousands of rows); (B) Store GLOBAL events without entity links
**Rationale**: A pandemic affects thousands of companies. Writing individual exposure rows for each would create millions of rows and degrade write performance. Sector/industry entities as the link point keeps `entity_event_exposures` bounded (~3 rows per GLOBAL event) while still enabling company-level exposure queries.

### ADR-0018-004: Max 5 hops for Cypher path queries

**Decision**: `max_hops` hard cap is 5 (not 7 or 10).
**Rationale**: At 5 hops in a ~100K entity graph, the AGE query already traverses O(degree^5) candidate paths before pruning. Beyond 5 hops, noise dominates the signal — a 7-hop path between companies is almost always spurious or trivially indirect. The LLM context window cannot coherently explain >5-hop paths. Raising the cap would exponentially increase query latency.

### ADR-0018-005: EODHD data sources corrected — separate APIs for different signals

**Decision**: Use distinct EODHD APIs for each data category:
- Executive discovery: **Insider Transactions API** (`/insider-transactions`) — not `General.Officers` (non-existent)
- Ownership context: **SharesStats.PercentInsiders/PercentInstitutions** from fundamentals payload — aggregate signals only, not individual holders
- Macro events: **Economic Events API** (`/economic-events`) — structured, no NLP needed
- Country enrichment: **Macro Indicator API** (`/macro-indicator/{COUNTRY}`) — World Bank data

**Why not the assumed EODHD fields**: `General.Officers`, `Holders.Institutions`, and `Financials.Revenue_Segment` do not exist in the EODHD fundamentals response. Investigation of actual API responses confirmed their absence.

**ADR for insider transactions**: Insider Transactions API has the added benefit of transaction direction (buy/sell) as an insider sentiment signal — richer than a static officer list would provide.

**ADR for macro events**: Economic Events API provides `actual - estimate` surprise magnitude, which is a more useful market-impact signal than a narrative description of the event. Structured data removes NLP extraction uncertainty entirely.

---

## §8 Security Analysis

| Threat | Mitigation |
|--------|-----------|
| Cypher injection via entity_id | `entity_id` is a validated UUID — passed as parameterized Cypher `$entity_id`, never string-interpolated |
| AGE query DoS (unbounded path search) | `max_hops` hard-capped at 5 in route validation; AGE query has `5s` timeout via `SET statement_timeout = '5s'` |
| Officer name injection in relation evidence text | `evidence_text` stored as plain text (never executed); no SQL interpolation |
| Country entity auto-creation via officer data | `find_or_create_country()` validates country name against ISO-3166 whitelist (237 countries); rejects unknown values |
| Temporal event confidence manipulation | Events have minimum confidence threshold 0.5 before Kafka production; all events are NLP-extracted (no user input) |
| AGE watermark tampering | Watermark stored in Valkey with `KNOWLEDGE_GRAPH_AGE_SYNC_SECRET` auth; unauthorized modification causes re-sync of recent window (idempotent) |

---

## §9 Failure Modes

| Component | Failure | Behaviour |
|-----------|---------|-----------|
| AGE extension unavailable | `CREATE EXTENSION age` fails | Migration fails; S7 starts in degraded mode; `KNOWLEDGE_GRAPH_CYPHER_ENABLED` auto-set to `false`; SQL endpoints unchanged |
| AGE sync Worker 13F crash | APScheduler task exception | Logged + metrics; next run at `watermark + 15min`; no data loss (relational tables are source of truth) |
| `POST /graph/cypher/path` AGE timeout | Statement timeout 5s | 504 response + log; S8 falls back to SQL neighborhood endpoint |
| EODHD Insider Transactions API unavailable | HTTP 5xx / rate limit | Retry next weekly run; existing `has_executive` relations preserved (idempotent upsert); log warning per company |
| EODHD Economic Events API returns no data | Empty array for country/date | Skip silently; no temporal_events rows created for that run; next daily run retries |
| EODHD Macro Indicator API unavailable | HTTP 5xx | Skip country for this week; existing metadata preserved; no re-embedding triggered |
| Temporal event Kafka consumption failure | Consumer exception | Event goes to DLQ; relational tables not updated; AGE sync picks up when DLQ is retried |
| Country entity not in ISO-3166 whitelist | Unknown country name from EODHD | Log warning; `revenue_from_country` relation not created for that segment; no error |

---

## §10 Scalability & Performance

### AGE Cypher path queries

- IVFFlat equivalent in AGE: AGE uses B-tree indexes on vertex/edge properties
- Add property index on `entity_id` for Entity vertices: `CREATE INDEX ON worldview_graph.entity_id_idx FOR (v:Entity) ON (v.entity_id)`
- Cypher `shortestPath()` with confidence filter: expected 20–100ms for 5-hop paths on 100K entities
- For all_paths mode (up to 5 shortest paths): may reach 500ms at 5 hops; acceptable for RELATIONSHIP intent

### Temporal event queries

- `entity_event_exposures (entity_id)` index enables O(log N) lookup per entity
- For GLOBAL events: `SELECT ce.entity_id FROM canonical_entities ce JOIN relations r ON ...` — covered by existing `relations` hash partition on `subject_entity_id`

### EODHD enrichment throughput

- `FundamentalsConsumer` processes one company at a time (sequential consumer)
- Each company: ~3 officer relations + ~5 revenue segment relations + ~10 holder relations = ~18 upserts
- Existing consumer processes ~200 companies/hour → ~3,600 new relations/hour
- Backfill of existing companies: ~10K companies × 18 upserts = ~180K upserts (one-time, ~1h runtime)

---

## §11 Test Strategy

### Unit Tests (services/knowledge-graph)

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_temporal_event_lifecycle_active` | Event with `active_from=yesterday, active_until=None` → `lifecycle_phase=ACTIVE`, `impact_weight=1.0` | HIGH |
| `test_temporal_event_lifecycle_residual` | Event ended 20 days ago, `residual_impact_days=90` → `lifecycle_phase=RESIDUAL`, `impact_weight=exp(-0.02×20)` | HIGH |
| `test_temporal_event_lifecycle_expired` | Event ended 100 days ago, `residual_impact_days=90` → `lifecycle_phase=EXPIRED`, `impact_weight=0.0` | HIGH |
| `test_global_event_no_company_rows` | GLOBAL scope event → `entity_event_exposures` rows for sector entities only, not companies | HIGH |
| `test_cypher_path_entity_id_parameterized` | CypherPathUseCase builds query with parameterized `$entity_id`, not f-string | HIGH |
| `test_age_sync_worker_watermark_update` | After run(), Valkey watermark updated to start of run (not end) | HIGH |
| `test_fundamentals_consumer_metadata_enrichment` | Payload with FullTimeEmployees + RevenueTTM → entity.metadata updated | HIGH |
| `test_fundamentals_consumer_missing_fields` | Payload missing Highlights → no exception; partial metadata update | HIGH |
| `test_fundamentals_consumer_idempotent` | Processing same payload twice → same metadata (no re-emit of entity.dirtied.v1) | HIGH |
| `test_economic_events_worker_creates_temporal_event` | EODHD economic event with actual+estimate → temporal_event with surprise magnitude in description | HIGH |
| `test_economic_events_worker_skips_unreleased` | Event with `actual=null` → skipped, no temporal_event row | HIGH |
| `test_economic_events_worker_deduplication` | Same event processed twice → one temporal_event row (upsert idempotent) | HIGH |
| `test_macro_indicator_worker_metadata_update` | GDP + inflation values fetched → entity.metadata["macro_indicators"] updated | HIGH |
| `test_macro_indicator_worker_no_change` | Same indicators as existing metadata → no entity.dirtied.v1 produced | HIGH |
| `test_insider_transactions_worker_creates_relation` | CEO transaction for AAPL → has_executive relation company→person | HIGH |
| `test_insider_transactions_worker_title_filter` | VP Sales (non-executive title) → skipped; CEO → included | HIGH |
| `test_insider_transactions_worker_deduplication` | Same officer in 3 transactions → 1 has_executive relation | HIGH |
| `test_cypher_endpoint_disabled` | `CYPHER_ENABLED=false` → 503 with `CYPHER_DISABLED` error code | HIGH |

### Integration Tests

| Test | Infrastructure | What It Verifies |
|------|---------------|-----------------|
| `test_age_sync_entity_created` | intelligence_db + AGE | New entity synced to AGE vertex after `sync_worker.run()` |
| `test_age_sync_relation_upsert` | intelligence_db + AGE | New relation synced to AGE edge with correct confidence |
| `test_cypher_path_finds_shortest` | intelligence_db + AGE with seed data | 3-hop path found; nodes/edges in correct order |
| `test_temporal_event_consumer` | intelligence_db + Kafka | `intelligence.temporal_event.v1` consumed → rows in `temporal_events` + `entity_event_exposures` |

---

## §12 Migration Plan

**Order** (all non-destructive; zero downtime):

1. Run `intelligence-migrations` migration 0004 (AGE extension + schema + new tables + new relation type seeds)
2. Deploy updated S7 with `FundamentalsConsumer` enhancements — starts enriching new fundamentals payloads; existing companies enriched on next fundamentals fetch cycle
3. Deploy updated S7 with `TemporalEventConsumer` — starts consuming new temporal events from S6
4. Deploy updated S6 with Block 13E temporal event detection
5. Deploy updated S7 `AgeSyncWorker` — first run syncs all existing entities/relations (backfill)
6. Deploy updated S7 Cypher endpoints — feature-flagged; enable `KNOWLEDGE_GRAPH_CYPHER_ENABLED=true` after AGE backfill verified
7. Deploy updated S8 with RELATIONSHIP intent Cypher integration
8. **EODHD backfill**: Trigger re-processing of existing fundamentals payloads via admin endpoint or manual replay of `market.dataset.fetched` topic (coordinator task)

---

## §13 Observability

### Metrics (S7 additions)
- `s7_temporal_events_total{scope, event_type}` — events ingested by scope/type
- `s7_entity_event_exposures_total{exposure_type}` — exposure links created
- `s7_age_sync_duration_seconds` — AGE sync worker duration histogram
- `s7_age_sync_entities_synced_total` — entities synced per run
- `s7_age_sync_relations_synced_total` — relations synced per run
- `s7_age_sync_lag_seconds` — gauge: time since last successful sync
- `s7_cypher_path_requests_total{status}` — Cypher path requests by status
- `s7_cypher_path_duration_seconds` — Cypher path query latency histogram (target p95 < 100ms)
- `s7_fundamentals_metadata_updates_total` — entity metadata updates from fundamentals payload
- `s7_economic_events_ingested_total{country}` — economic events ingested by country
- `s7_economic_events_surprises_total{country,direction}` — events where actual ≠ estimate (beat/miss)
- `s7_macro_indicator_updates_total{country}` — country entities re-enriched
- `s7_insider_transactions_relations_total{ticker}` — has_executive relations created/updated
- `s7_insider_transactions_skipped_total{reason}` — skipped transactions (non-executive title, no name)

### Alerts
- `s7_age_sync_lag_seconds > 1800` (30 min) → PagerDuty (AGE sync stuck)
- `s7_cypher_path_duration_seconds_p95 > 200ms` (5min window) → Warning (AGE performance degrading)

---

## §14 Open Questions

| # | Question | Status |
|---|----------|--------|
| OQ-001 | ~~Are `General.Officers`, `Holders.Institutions`, and `Financials.Revenue_Segment` present in the EODHD subscription tier used?~~ **Resolved (2026-04-05)**: These fields **do not exist** in the EODHD API. Replaced by: Insider Transactions API (executives), SharesStats (ownership aggregates), Economic Events API (macro events), Macro Indicator API (country enrichment). See §1.2 and §6.6. |
| OQ-002 | Should `revenue_from_country` relations use TTM revenue percentages or most recent year? | → Most recent annual reporting period (stability over recency) |
| OQ-003 | AGE `shortestPath()` vs `allShortestPaths()` — which to use for `all_paths=true`? | → `allShortestPaths()` with `LIMIT 5`; yields multiple paths of the same minimum length |
| OQ-004 | Should Block 13E temporal event detection use a separate LLM call or be co-generated with entity extraction? | → Separate call (different classification model: Qwen2.5:3b vs existing extraction); adds ~200ms to NLP pipeline for DEEP-tier articles |
| OQ-005 | How to handle temporal event deduplication across articles (same event mentioned in 100 articles)? | → Deduplicate by (title hash + event_type + active_from date); merge confidence scores via maximum |
| OQ-006 | Should AGE backfill run in one pass or paginated with checkpointing? | → Paginated with Valkey checkpoint per batch of 10K; allows restart on failure |

---

## §15 Implementation Estimate

| Wave | Description | Services | Effort |
|------|-------------|----------|--------|
| A-1 | intelligence-migrations 0004: AGE extension + temporal_events + entity_event_exposures tables + new relation type seeds | intelligence-migrations | 4h |
| A-2 | S7: `TemporalEvent` + `EntityEventExposure` domain models + `TemporalEventRepository` | S7 | 3h |
| A-3 | `libs/contracts`: `intelligence.temporal_event.v1` Avro schema | libs/contracts | 2h |
| A-4 | S7: `TemporalEventConsumer` (new Kafka consumer, `intelligence.temporal_event.v1`) | S7 | 4h |
| B-1 | S6: Block 13E temporal event detection (Qwen classification + Kafka produce) | S6 | 5h |
| B-2 | S7: Enhanced `FundamentalsConsumer` — metadata enrichment (FullTimeEmployees, RevenueTTM, PercentInsiders, PercentInstitutions); Workers 13D-6 (Economic Events), 13D-7 (Macro Indicators), 13D-8 (Insider Transactions) | S7 | 8h |
| C-1 | S7: `AgeSyncWorker` (Worker 13F) — watermark sync, Cypher MERGE, metrics | S7 | 6h |
| C-2 | S7: `CypherPathUseCase` + `GET /api/v1/temporal-events` + `POST /api/v1/graph/cypher/path` + `POST /api/v1/graph/cypher/neighborhood` endpoints | S7 | 6h |
| D-1 | S8: RELATIONSHIP intent Cypher path integration + SIGNAL_INTEL temporal event context | S8 | 4h |
| D-2 | Integration tests + EODHD backfill replay tooling | S7 + ops | 4h |

**Total estimate**: ~43h (5.5 working days)
