# PRD-0017 — Entity Screener & Similarity Search

> **Status**: Draft
> **Author**: Architecture session 2026-04-04
> **Depends on**: PRD-0001 (S3 fundamentals, S7 graph), PRD-0015 (S8 embeddings infra)

---

## §1 Problem Statement

Three distinct discovery gaps exist in the platform:

1. **No UI screener.** The `POST /api/v1/fundamentals/screen` endpoint in S3 already exists and works, but the response is thin (`instrument_id` + metrics only — no name/ticker/exchange) and there is no frontend surface for it. Users who want to find instruments by financial criteria (P/E, margins, revenue) have no way to do so.

2. **No similar-companies query.** Given a target company, there is no way to discover similar peers by financial profile. The `fundamentals_ohlcv` embedding exists in `entity_embedding_state` and pgvector's ANN operator is available, but no S7 endpoint exposes it. The `competes_with` relation provides graph-level peer signal but is not surfaced as a ranked similarity result.

3. **Entity embedding views are mis-provisioned.** `ensure_rows_exist()` creates 3 rows (`definition`, `narrative`, `fundamentals_ohlcv`) for **every** entity regardless of type. Non-company entities (persons, countries, organizations, regulatory bodies, etc.) have no fundamentals data — their `fundamentals_ohlcv` row stays `NULL` forever, wastes storage, and pollutes ANN search results with null-embedding gaps. Additionally, non-company entities lack world-knowledge descriptions because the `definition` view's source text is only populated from EODHD data (companies only); non-company entities need LLM-generated descriptions.

---

## §2 Target Users

| User | Pain | Desired Outcome |
|------|------|-----------------|
| Buy-side analyst | Wants to screen for investment ideas (e.g. mid-cap EU tech, P/E < 20, gross margin > 40%) | ScreenerPage with multi-criteria filter + sortable table of matching stocks |
| Portfolio manager | Wants peers for comparison after selecting a company | SimilarCompaniesPanel on company detail page showing top-10 similar names |
| Data quality / admin | Needs confidence that entity embeddings are correctly provisioned | Internal verification: 3 views for `financial_instrument`, 2 views for all other types |

---

## §3 Functional Requirements

| ID | Requirement |
|----|-------------|
| F-001 | Screener endpoint returns instrument `name`, `ticker`, `exchange`, `sector` alongside metrics |
| F-002 | Screener supports `sort_by` (any metric or `ticker` or `name`) and `sort_order` (`asc`/`desc`) |
| F-003 | Screener response includes `total` (total matching rows, ignoring limit/offset) for pagination |
| F-004 | New `GET /api/v1/fundamentals/screen/fields` endpoint returns screener metadata (field name, label, type, unit, min/max range observed in DB) |
| F-005 | S7 new endpoint `POST /api/v1/entities/similar` — returns top-N similar entities by `fundamentals_ohlcv` ANN score + `competes_with` edge boost |
| F-006 | Similar endpoint restricts ANN search to `entity_type = 'financial_instrument'` only (non-company entities have no `fundamentals_ohlcv` embedding) |
| F-007 | `competes_with` edge boost: +0.15 added to ANN cosine similarity for entities linked by `competes_with` relation with confidence ≥ 0.3; final score capped at 1.0 |
| F-008 | `ensure_rows_exist()` creates 3 view rows for `financial_instrument` entities; exactly 2 rows (`definition` + `narrative`) for all other entity types |
| F-009 | `DefinitionRefreshWorker` generates world-knowledge descriptions for non-company entities using `gemini-3.1-flash-lite` via Google AI Studio, falling back to a deterministic template when API is unavailable or cost cap exceeded |
| F-010 | Frontend `ScreenerPage` — multi-criteria filter form, results table with sorting, pagination, "View Company" link to entity detail |
| F-011 | Frontend `SimilarCompaniesPanel` — top-10 similar companies panel on `CompanyDetailPage`, showing name, ticker, similarity score, competitor badge |

---

## §4 Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-001 | Screener: max `limit` = 200, default 50; `offset` max 5000 |
| NFR-002 | Similar endpoint: max `top_k` = 50, default 20; p95 latency < 200ms (pgvector HNSW ANN — existing partial HNSW index on `fundamentals_ohlcv` view already in place from `intelligence-migrations 0001`) |
| NFR-003 | External LLM description: provider-agnostic interface (Protocol); hardcoded to `gemini-3.1-flash-lite` via Google AI Studio; `KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER=gemini` set in deployment config |
| NFR-004 | External LLM cost guard: configurable max monthly spend tracked in Valkey; default $10/month |
| NFR-005 | All new S3 and S7 endpoints proxied through S9 gateway; frontend communicates only with S9 (Rule 14) |
| NFR-006 | Entity embedding fix is non-destructive: existing `fundamentals_ohlcv` rows for non-company entities are NOT deleted automatically; a one-time cleanup migration is included |

---

## §5 Out of Scope

- Saved screens / screen persistence across sessions
- Screener-triggered watchlist creation
- Screener alerts (notify when instruments enter/exit a screen)
- Real-time screener on tick data
- Embedding models other than `nomic-embed-text` (model selection deferred to PRD-0019)
- Cross-modal similarity (combining fundamentals + text + graph embeddings into a single vector)
- Screener on OHLCV / price data (price-based filters deferred)

---

## §6 Technical Design

### §6.1 Affected Services

| Service | Changes |
|---------|---------|
| S3 Market Data | Enhance `ScreenInstrumentResponse`, add `ScreenFieldsMetadataUseCase`, add `sort_by`/`sort_order`/`total` to request/response |
| S7 Knowledge Graph | New `FindSimilarEntitiesUseCase`, new `EntityEmbeddingANNRepository`, new API endpoint `POST /api/v1/entities/similar`; fix `ensure_rows_exist()`; fix `DefinitionRefreshWorker` for non-company entities |
| S9 API Gateway | Proxy new S3 and S7 endpoints |
| `libs/ml-clients` | New `EntityDescriptionClient` Protocol + `GeminiDescriptionAdapter` (gemini-3.1-flash-lite via Google AI Studio) |
| `intelligence-migrations` | One-time cleanup: DELETE orphan `fundamentals_ohlcv` rows for non-`financial_instrument` entities |
| Frontend (`apps/frontend`) | `ScreenerPage` component + `SimilarCompaniesPanel` component + API client types |

---

### §6.2 API Changes

#### PATCH — `POST /api/v1/fundamentals/screen` (S3, enhanced)

The existing endpoint is enhanced in-place. Request and response schemas are extended; no new route path.

**Request body** (`ScreenRequest` — enhanced):

| Field | Type | Required | Default | Validation | Description |
|-------|------|----------|---------|------------|-------------|
| filters | `ScreenFilterRequest[]` | yes | — | min_length=1, max_length=20 | Metric filters |
| limit | int | no | 50 | 1–200 | Result page size. **Breaking change**: current code allows `le=1000` with default 100; this tightens the cap to 200 and changes the default to 50. Coordinate with any existing API consumers before deploying. |
| offset | int | no | 0 | 0–5000 | Pagination offset |
| sort_by | string \| null | no | null | one of metric names, `ticker`, `name`, or null (= no sort guarantee) | Sort key |
| sort_order | `"asc"` \| `"desc"` | no | `"asc"` | — | Sort direction |
| include_fields | `string[]` | no | `["ticker","name","exchange"]` | subset of screen field names | Extra instrument fields to return |

**Response** (`ScreenResponse` — enhanced):

| Field | Type | Description |
|-------|------|-------------|
| results | `ScreenInstrumentResponse[]` | Matching instruments |
| count | int | Number of results in this page |
| total | int | Total matching rows (before limit/offset) — enables pagination |

**`ScreenInstrumentResponse`** (enhanced):

| Field | Type | Description |
|-------|------|-------------|
| instrument_id | string (UUID) | S3 instrument UUID |
| ticker | string \| null | Exchange ticker symbol |
| name | string \| null | Instrument display name |
| exchange | string \| null | Exchange code (e.g. `US`, `XNAS`) |
| sector | string \| null | Sector from fundamentals |
| metrics | `dict[str, float \| null]` | Requested metric values (latest value per instrument) |

- **Error responses**: 400 (no filters), 422 (invalid metric name, invalid sort_by value)
- **Auth**: none (public)
- **Rate limit**: inherited from S9 tenant rate limit
- **Session**: read-replica (R27) — use `ReadUoWDep` in the API route; this endpoint is purely read-only

#### NEW — `GET /api/v1/fundamentals/screen/fields` (S3)

Returns metadata for all screenable fields.

- **Purpose**: Frontend uses this to build the filter form dynamically without hardcoding metric names
- **Auth**: none (public)
- **Response** (200):

```json
{
  "fields": [
    {
      "name": "pe_ratio",
      "label": "P/E Ratio",
      "type": "numeric",
      "unit": "x",
      "description": "Price-to-earnings ratio (trailing twelve months)",
      "observed_min": -50.2,
      "observed_max": 1240.5,
      "null_fraction": 0.12
    }
  ]
}
```

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| name | string | no | Metric key used in `ScreenFilterRequest.metric` |
| label | string | no | Human-readable display name |
| type | `"numeric"` \| `"text"` | no | Data type |
| unit | string \| null | yes | Display unit (e.g. `%`, `x`, `USD`) |
| description | string \| null | yes | Short description |
| observed_min | float \| null | yes | Min value in DB (numeric only); null if no data |
| observed_max | float \| null | yes | Max value in DB (numeric only); null if no data |
| null_fraction | float | no | Fraction of instruments with null value (0–1) |

The field metadata is **static + pre-computed**. A background job refreshes it into Valkey (key `s3:screen:fields:v1`) every 6 hours. The endpoint reads from Valkey; if cache miss, falls back to a synchronous DB query (slow path, <2s). Fallback DB query uses read-replica session (R27).

#### NEW — `POST /api/v1/entities/similar` (S7)

Find entities similar to a given entity by embedding ANN.

- **Purpose**: Discover similar companies by financial profile
- **Auth**: none (public); S7 is an internal service, accessed via S9 proxy
- **Request body**:

| Field | Type | Required | Default | Validation | Description |
|-------|------|----------|---------|------------|-------------|
| entity_id | string (UUID) | yes | — | valid UUID, must exist | Target entity |
| top_k | int | no | 20 | 1–50 | Number of results |
| min_score | float | no | 0.0 | 0.0–1.0 | Minimum final score threshold |
| include_competitors_only | bool | no | false | — | If true, return only entities with `competes_with` relation |

- **Response** (200):

```json
{
  "entity_id": "...",
  "canonical_name": "Apple Inc.",
  "results": [
    {
      "entity_id": "...",
      "canonical_name": "Microsoft Corporation",
      "entity_type": "financial_instrument",
      "ticker": "MSFT",
      "exchange": "US",
      "ann_similarity_score": 0.82,
      "competes_with_confidence": 0.71,
      "final_score": 0.97,
      "has_competes_with_relation": true
    }
  ],
  "total": 8
}
```

| Response Field | Type | Description |
|----------------|------|-------------|
| entity_id | UUID | The query entity |
| canonical_name | string | The query entity's name |
| results | `SimilarEntityResult[]` | Top-K similar entities |
| total | int | Number of results returned (≤ top_k) |

**`SimilarEntityResult`**:

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| entity_id | UUID | no | Similar entity UUID |
| canonical_name | string | no | Entity name |
| entity_type | string | no | Always `financial_instrument` (v1) |
| ticker | string | yes | Exchange ticker |
| exchange | string | yes | Exchange code |
| ann_similarity_score | float | no | Cosine similarity from ANN search (0–1; transformed from distance: `1 - distance`) |
| competes_with_confidence | float | yes | Confidence of `competes_with` relation; null if no such relation |
| final_score | float | no | `min(ann_similarity_score + (0.15 if has_competes_with else 0.0), 1.0)` |
| has_competes_with_relation | bool | no | True if `competes_with` relation exists (confidence ≥ 0.3) |

- **Session**: read-replica (R27) — use read-only session in the API route; this endpoint is purely read-only
- **Error responses**:
  - 404: entity not found
  - 422: entity has no `fundamentals_ohlcv` embedding (e.g., entity_type is not `financial_instrument`)
  - 503: pgvector ANN unavailable

---

### §6.3 Event / Kafka Changes

No new Kafka topics or events. The `entity.dirtied.v1` compacted topic (already exists) is produced when entity embedding state changes — no new production paths needed.

---

### §6.4 Database Changes

#### `intelligence-migrations` — Migration 0003 (partial, cleanup only)

> **Note**: Migration 0002 already exists (`0002_enhance_events_and_relations.py` — events table enhancements, 2026-04-05). This cleanup migration is numbered **0003**.

This migration removes orphan `fundamentals_ohlcv` rows from `entity_embedding_state` for non-`financial_instrument` entities. It is a **data-only migration** — no DDL change.

```sql
-- Remove orphan fundamentals_ohlcv embeddings for non-company entities
DELETE FROM entity_embedding_state ees
WHERE ees.view_type = 'fundamentals_ohlcv'
  AND EXISTS (
    SELECT 1 FROM canonical_entities ce
    WHERE ce.entity_id = ees.entity_id
      AND ce.entity_type != 'financial_instrument'
  );
```

**Estimated rows deleted**: unknown at design time (depends on data volume).
**Downtime**: zero (DELETE does not lock reads).
**Rollback**: INSERT is non-trivial; rollback = re-run embedding worker. Document in runbook.

#### `entity_embedding_state` — No schema change

The table schema is unchanged. Only the application logic for `ensure_rows_exist()` changes (see §6.5).

#### `market_data_db` — New table: `screen_field_metadata`

Used as a persistent fallback when Valkey misses. Populated by a background APScheduler job.

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| field_name | TEXT | no | — | PK | Metric key |
| label | TEXT | no | — | — | Display name |
| field_type | TEXT | no | `'numeric'` | CHECK IN ('numeric','text') | Data type |
| unit | TEXT | yes | null | — | Display unit |
| description | TEXT | yes | null | — | Human-readable description |
| observed_min | NUMERIC | yes | null | — | Min value from last scan |
| observed_max | NUMERIC | yes | null | — | Max value from last scan |
| null_fraction | NUMERIC | no | 0 | CHECK(0<=null_fraction AND null_fraction<=1) | Null rate |
| last_computed_at | TIMESTAMPTZ | no | — | — | Scan timestamp |

- **Indexes**: `(field_name)` PRIMARY KEY
- **Estimated rows**: ~50 (one per distinct metric name; static set)
- **Alembic migration**: new migration in `services/market-data/alembic/`

---

### §6.5 Domain Model Changes

#### `libs/ml-clients` — New Protocol: `EntityDescriptionClient`

```python
class EntityDescriptionClient(Protocol):
    """Protocol for generating entity descriptions using world-knowledge LLMs."""

    async def generate_description(
        self,
        entity_id: str,
        canonical_name: str,
        entity_type: str,
        context_hints: dict[str, str],  # e.g., {"ticker": "MSFT", "exchange": "US"}
    ) -> str | None:
        """Generate a 2-4 sentence description for a canonical entity.

        Returns None when the provider is unavailable or cost limit exceeded.
        The caller must handle None by using a fallback template.
        """
        ...
```

**Implementations**:

| Class | Provider | Model | Notes |
|-------|----------|-------|-------|
| `GeminiDescriptionAdapter` | Google AI Studio | `gemini-3.1-flash-lite` | Primary and only adapter; chosen for cost, latency, and world knowledge |
| `NullDescriptionAdapter` | — | — | Returns None always; used when `KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER=none` (test/dev) |

**Config** (`KnowledgeGraphSettings` additions):

| Env Var | Type | Default | Description |
|---------|------|---------|-------------|
| `KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER` | string | `"none"` | `"gemini"` \| `"none"` — hardcoded to `gemini` in production |
| `KNOWLEDGE_GRAPH_GEMINI_API_KEY` | string | — | Google AI Studio API key |
| `KNOWLEDGE_GRAPH_DESCRIPTION_MAX_MONTHLY_USD` | float | `10.0` | Monthly cost cap; enforced via Valkey counter `s7:desc:cost:{YYYY-MM}` |

**Cost tracking**:
- Each API call logs tokens used → estimated cost → `INCR s7:desc:cost:{YYYY-MM}` in Valkey
- Gemini 3.1 Flash Lite pricing: $0.000075/1K input + $0.0003/1K output (as of 2026-04)
- Description prompt ~200 input tokens + ~150 output tokens → ~$0.00006/entity
- At 10K non-company entities, full refresh costs ~$0.60 — well within $10/month cap
- If estimated monthly total ≥ `MAX_MONTHLY_USD`, return None without calling API and log warning

---

#### S3 — New Domain Object: `ScreenFieldMetadata`

```python
@dataclass(frozen=True, slots=True)
class ScreenFieldMetadata:
    name: str           # metric key
    label: str          # display name
    field_type: str     # "numeric" | "text"
    unit: str | None    # display unit or None
    description: str | None
    observed_min: float | None
    observed_max: float | None
    null_fraction: float  # 0.0–1.0
```

**Static field definitions** (seeded, not from DB):

| name | label | unit | description |
|------|-------|------|-------------|
| `pe_ratio` | P/E Ratio | x | Trailing P/E (TTM) |
| `revenue_usd` | Revenue | USD M | Annual revenue (USD millions) |
| `gross_margin_pct` | Gross Margin | % | Gross profit / revenue × 100 |
| `net_margin_pct` | Net Margin | % | Net income / revenue × 100 |
| `ev_ebitda` | EV/EBITDA | x | Enterprise value / EBITDA |
| `debt_to_equity` | Debt/Equity | x | Total debt / shareholders' equity |
| `return_on_equity` | ROE | % | Net income / avg. equity × 100 |
| `dividend_yield_pct` | Dividend Yield | % | Annual dividends / price × 100 |
| `market_cap_usd` | Market Cap | USD M | Market capitalisation (USD millions) |
| `price_to_book` | Price/Book | x | Market price / book value per share |
| `operating_margin_pct` | Operating Margin | % | Operating income / revenue × 100 |
| `current_ratio` | Current Ratio | x | Current assets / current liabilities |

---

#### S7 — New Domain Object: `SimilarEntityResult`

```python
@dataclass(frozen=True, slots=True)
class SimilarEntityResult:
    entity_id: UUID
    canonical_name: str
    entity_type: str
    ticker: str | None
    exchange: str | None
    ann_similarity_score: float   # 0–1; 1 = identical
    competes_with_confidence: float | None
    final_score: float            # min(ann_similarity_score + boost, 1.0)
    has_competes_with_relation: bool
```

**Invariants**:
- `0.0 ≤ ann_similarity_score ≤ 1.0`
- `0.0 ≤ final_score ≤ 1.0`
- `final_score == min(ann_similarity_score + (0.15 if has_competes_with_relation else 0.0), 1.0)`
- `has_competes_with_relation == (competes_with_confidence is not None)`

---

#### S7 — New Use Case: `FindSimilarEntitiesUseCase`

```python
class FindSimilarEntitiesUseCase:
    """Find similar financial instrument entities by fundamentals_ohlcv embedding ANN."""

    async def execute(
        self,
        entity_repo: CanonicalEntityRepositoryPort,
        embedding_repo: EntityEmbeddingANNRepositoryPort,
        relation_repo: RelationRepositoryPort,
        entity_id: UUID,
        top_k: int = 20,
        min_score: float = 0.0,
        include_competitors_only: bool = False,
    ) -> tuple[dict, list[SimilarEntityResult]]:
        """Returns (query_entity_dict, results)."""
```

**Algorithm** (step-by-step):
1. `entity_repo.get(entity_id)` → if None: raise `EntityNotFoundError`
2. Look up `entity_embedding_state WHERE entity_id=? AND view_type='fundamentals_ohlcv'` → if embedding is null: raise `EmbeddingNotAvailableError(entity_id, 'fundamentals_ohlcv')`
3. Query `EntityEmbeddingANNRepository.find_nearest(embedding, view_type='fundamentals_ohlcv', limit=top_k*2, exclude_entity_id=entity_id)` → returns `list[AnnResult]` sorted by cosine distance ascending; filtered to `entity_type='financial_instrument'` only
4. Transform distances to similarity: `ann_similarity_score = 1.0 - distance`
5. For each ANN result: query `relation_repo.find_competes_with(subject=entity_id, object=result.entity_id, min_confidence=0.3)` + `relation_repo.find_competes_with(subject=result.entity_id, object=entity_id, min_confidence=0.3)` (bidirectional)
6. Compute `final_score = min(ann_similarity_score + (0.15 if competes_with else 0.0), 1.0)`
7. Filter by `min_score`, apply `include_competitors_only` filter
8. Sort by `final_score DESC`, take `top_k`
9. For each result: `entity_repo.get(result.entity_id)` → populate canonical_name, ticker, exchange
10. Return `(entity_dict, list[SimilarEntityResult])`

**N+1 optimization**: Steps 4 and 8 use batch queries. `find_competes_with_batch(entity_id, candidate_ids)` returns a dict mapping candidate_id → (has_relation, confidence).

---

#### S7 — New Repository Port: `EntityEmbeddingANNRepositoryPort`

```python
class EntityEmbeddingANNRepositoryPort(ABC):
    """Port for pgvector ANN queries on entity_embedding_state."""

    @abstractmethod
    async def find_nearest(
        self,
        query_embedding: list[float],
        view_type: str,
        limit: int = 40,
        exclude_entity_id: UUID | None = None,
        entity_types: list[str] | None = None,
    ) -> list[AnnResult]:
        """Return nearest neighbours by cosine distance.

        AnnResult: {entity_id: UUID, distance: float}  where 0=identical, 2=opposite.
        Filters: entity_type IN entity_types (applied via JOIN on canonical_entities).
        """
```

**Concrete implementation** uses pgvector: `embedding <=> :query_embedding ORDER BY ... LIMIT :limit`.

---

#### S7 — Fix: `ensure_rows_exist()` entity type awareness

```python
# Current (wrong):
ALL_VIEW_TYPES = ("definition", "narrative", "fundamentals_ohlcv")
# Always creates 3 rows

# Fixed:
COMPANY_ENTITY_TYPES = frozenset({"financial_instrument"})

def get_view_types_for_entity_type(entity_type: str) -> tuple[str, ...]:
    if entity_type in COMPANY_ENTITY_TYPES:
        return ("definition", "narrative", "fundamentals_ohlcv")
    return ("definition", "narrative")
```

`ensure_rows_exist(entity_id, entity_type)` — new signature requires `entity_type`. All callers updated:
- `instrument_consumer_main.py` — has access to entity_type from the `market.instrument.created` event
- `provisional_enrichment.py` — has entity_type from canonical profile

> **Note**: `entity_consumer.py` does NOT call `ensure_rows_exist()` (confirmed by codebase audit — it only clears provisional flags on `relation_evidence_raw`). No change needed there.

---

#### S7 — Fix: `DefinitionRefreshWorker` for non-company entities

Current behaviour: `source_text` for non-company entities' `definition` view is populated by `provisional_enrichment.py` which uses Qwen via `FallbackChainClient`. This gives low-quality descriptions for persons, countries, organizations (Qwen does not have world knowledge for arbitrary entities).

**Updated constructor** (adds `description_client` parameter):
```python
def __init__(
    self,
    session_factory: async_sessionmaker[AsyncSession],
    llm_client: FallbackChainClient,                    # embedding (unchanged)
    description_client: EntityDescriptionClient,         # NEW — text generation for non-company entities
) -> None:
```

Wave A-4 must update the scheduler wiring (`scheduler.py`) to inject `GeminiDescriptionAdapter` (or `NullDescriptionAdapter` when `KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER=none`).

**Enhanced behaviour** (when `KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER != "none"`):

1. Worker detects entity_type is NOT `financial_instrument`
2. Calls `EntityDescriptionClient.generate_description(...)` with `entity_type`, `canonical_name`, context hints
3. Uses response as `source_text` for embedding
4. Falls back to deterministic template if API unavailable or cost cap exceeded

**Non-company prompt template** (sent to Gemini 3.1 Flash Lite):
```
Generate a concise 2-4 sentence factual description of the entity:
- Name: {canonical_name}
- Type: {entity_type}
{context_hints formatted as key: value pairs}

Requirements: Focus on what this entity is and its significance in financial markets.
Be factual, neutral, and informative. No marketing language.
```

The generated description becomes `source_text`; the SHA-256 hash prevents re-generation on unchanged entities.

---

### §6.6 S9 Gateway Proxy Routes

New proxy routes to add to the S9 gateway:

| S9 Route | Upstream | Auth Required | Status |
|----------|----------|---------------|--------|
| `POST /api/v1/fundamentals/screen` | S3 | X-Tenant-ID | update existing proxy handler |
| `GET /api/v1/fundamentals/screen/fields` | S3 | none | new |
| `GET /api/v1/fundamentals/timeseries` | S3 | X-Tenant-ID | **new** — not currently proxied through S9 |
| `POST /api/v1/entities/similar` | S7 | X-Tenant-ID | new |

**Implementation pattern**: S9 does NOT use generic reverse-proxy routes. Follow the existing pattern:
1. Add typed handler methods in `services/api-gateway/src/api_gateway/clients.py` (using the appropriate `ServiceClients.market_data` or `ServiceClients.knowledge_graph` `httpx.AsyncClient`)
2. Add route handlers in `services/api-gateway/src/api_gateway/routes/proxy.py` that call those client methods

Wave C-1 covers all four routes, including the `GET /api/v1/fundamentals/timeseries` proxy which is new work not previously routed through S9.

---

### §6.7 Frontend Changes

#### `ScreenerPage` (`apps/frontend/src/pages/ScreenerPage.tsx`)

**Route**: `/screener`

**Layout**:
- Left panel: Filter form (dynamic, built from `GET /screen/fields` response)
- Right panel: Results table
- Filter form: one row per active filter — metric dropdown, min/max inputs, `+ Add Filter` button
- Results table columns: Ticker, Name, Exchange, Sector, + active filter metric values; sortable
- Pagination: page size selector (25/50/100), prev/next buttons
- Row click: navigate to `/entity/{entity_id}` (lookup entity by ticker via S7 entity search)
- Export: CSV download of current results (client-side)

**State**:
- `filters: ScreenFilterDraft[]` — pending filters not yet submitted
- `results: ScreenInstrumentResult[]` — server results
- `loading: boolean`
- `total: number`
- `page: number`, `pageSize: number`, `sortBy: string | null`, `sortOrder: 'asc' | 'desc'`

#### `SimilarCompaniesPanel` (`apps/frontend/src/components/SimilarCompaniesPanel.tsx`)

**Placement**: `CompanyDetailPage` — new collapsible card below the existing graph neighborhood section

**Layout**:
- Card title: "Similar Companies"
- Loading skeleton (3 placeholder rows)
- List of top-10 similar companies (from `POST /api/v1/entities/similar`, top_k=10)
- Each row: ticker badge, company name, final_score bar, competitor badge (if `has_competes_with_relation=true`)
- Empty state: "No similar companies found for this entity"
- "View all (N)" link → modal with full list (top_k=50)

---

### §6.8 Data Flow

#### Screener flow:
```
User filters form → POST /api/v1/fundamentals/screen (S9) → POST /api/v1/fundamentals/screen (S3)
  → ScreenInstrumentsUseCase.execute(filters, sort_by, sort_order, limit, offset)
  → fundamental_metrics_query.screen() [SQL: SELECT fm.*, i.symbol AS ticker, i.name, i.exchange,
     f_sector.value_text as sector FROM fundamental_metrics fm JOIN instruments i ...]
  -- NOTE: instruments table column is `symbol`; aliased to `ticker` in the API response
  → ScreenResponse {results[], count, total}
  → S9 returns JSON → Frontend renders table
```

#### Similar companies flow:
```
CompanyDetailPage loads → POST /api/v1/entities/similar (S9 → S7)
  → FindSimilarEntitiesUseCase.execute(entity_id, top_k=10)
  → entity_embedding_state (pgvector ANN, fundamentals_ohlcv view)
  → batch competes_with check (relations table)
  → SimilarEntityResult[] sorted by final_score
  → S7 response → S9 → Frontend SimilarCompaniesPanel
```

#### Description generation flow:
```
DefinitionRefreshWorker.run() [APScheduler, every 90 days per entity]
  → entity_type != 'financial_instrument'
  → EntityDescriptionClient.generate_description(canonical_name, entity_type, hints)
  → if API available AND cost < cap: LLM description → source_text
  → else: deterministic template → source_text
  → sha256_hex(source_text) != existing source_hash?
  → if changed: embed source_text → upsert entity_embedding_state
```

---

## §7 Architecture Decision Records

### ADR-0017-001: No cross-service DB join for screener entity_id

**Decision**: S3 screener does NOT return `entity_id` from `intelligence_db`.
**Alternatives**: (A) S9 joins S3 + S7 responses, (B) store entity_id FK in S3 instruments table
**Rationale**: Both alternatives add inter-service coupling. S3's mission is market data, not identity resolution. In v1, the frontend resolves entity pages by ticker via S7 entity search. When PRD-0018 adds deeper EODHD enrichment, the entity_id linkage can be added.

### ADR-0017-002: ANN restricted to `fundamentals_ohlcv` view only

**Decision**: `POST /api/v1/entities/similar` searches only the `fundamentals_ohlcv` embedding space.
**Alternatives**: Multi-view fusion (weighted combination of definition + narrative + fundamentals_ohlcv distances)
**Rationale**: Financial similarity (fundamentals profile) is the stated use case. Multi-view fusion increases complexity and requires tuning weights. Single-view ANN is simpler, faster, and more interpretable to users. Multi-view similarity deferred to PRD-0019 (advanced retrieval).

### ADR-0017-003: `competes_with` boost is additive (+0.15), not multiplicative

**Decision**: Boost = `+0.15` to ANN similarity, capped at 1.0.
**Alternatives**: Multiplicative (`score * 1.2`), re-rank slot guarantee
**Rationale**: Additive boost is interpretable and bounded. Multiplicative would push high-ANN-similarity competitors disproportionately high. A flat +0.15 ensures that a direct competitor with poor financial similarity (ANN score = 0.30) doesn't rank above a non-competitor with strong financial similarity (ANN score = 0.80).

### ADR-0017-004: 2 views for non-company entities (not 3)

**Decision**: Non-`financial_instrument` entities get only `definition` + `narrative` views.
**Rationale**: `fundamentals_ohlcv` embeddings require structured financial data (P/E, revenue, margins) that is only available for listed instruments. Creating empty rows for other entity types wastes storage and contaminates the ANN index with null embeddings that may score arbitrarily close to any query.

---

## §8 Security Analysis

| Threat | Mitigation |
|--------|-----------|
| SQL injection via `sort_by` field | `sort_by` validated against whitelist of allowed field names; never interpolated into SQL |
| ANN query DoS (large embedding dimension, many candidates) | `top_k` capped at 50; HNSW index limits traversal via `ef_search` parameter (set at index creation time; no per-query tuning needed) |
| LLM prompt injection via `canonical_name` | `canonical_name` is XML-wrapped before interpolation into description prompt |
| Cost drain via repeated description generation | Valkey cost counter with monthly cap; SHA-256 change detection prevents re-generation |
| Multi-tenant isolation | Screener is public (no tenant filter needed — market data is public); `POST /entities/similar` has no tenant-scoped data |
| `description` leakage of internal entity metadata | Generated descriptions contain only publicly available entity names and types; no financial secrets |

---

## §9 Failure Modes

| Component | Failure | Behaviour |
|-----------|---------|-----------|
| `POST /entities/similar` — entity has no `fundamentals_ohlcv` embedding | Null embedding in DB | 422 + `"EMBEDDING_NOT_AVAILABLE"` error code; message explains entity must be financial_instrument |
| `GET /screen/fields` — Valkey miss + DB slow | Cold DB scan | Falls back to synchronous DB query; 1–2s response; logs `screen_fields_cache_miss` |
| External LLM description API | HTTP 5xx or timeout | Returns None; falls back to deterministic template; logs warning; schedules retry via normal next_refresh_at cycle |
| External LLM cost cap exceeded | Valkey counter ≥ monthly cap | Returns None immediately without API call; description falls back to template; no retry until next calendar month |
| pgvector ANN during high concurrency | HNSW graph traversal under load | HNSW has no centroid locking (unlike IVFFlat); concurrent reads are safe; if contention arises, add connection pool limit in AsyncPG settings |
| Screener `sort_by` on metric with sparse data | NULL values break ordering | Use `ORDER BY ... NULLS LAST` always |

---

## §10 Scalability & Performance

### Screener
- `fundamental_metrics` is a pre-materialized read-optimized projection table (already exists, TimescaleDB)
- Add composite index: `(metric, as_of_date DESC, value_numeric)` — covers range scans
- **Total count strategy**: Use `COUNT(*) OVER()` window function in the main screening SQL — computes total matching rows in a single query pass before `LIMIT`/`OFFSET`:
  ```sql
  SELECT fm.*, i.ticker, i.name, ..., COUNT(*) OVER() AS total_count
  FROM fundamental_metrics fm
  JOIN instruments i ON ...
  WHERE <filters>
  ORDER BY ...
  LIMIT :limit OFFSET :offset
  ```
  No separate `COUNT(DISTINCT instrument_id)` query needed. For an even faster approximation, use `SELECT COUNT(*) FROM instruments WHERE has_fundamentals = true AND sector = :sector` (instruments table already has `has_fundamentals` boolean and sector column).

### Similar entities ANN
- `entity_embedding_state` has `embedding VECTOR(1024)` — 1024 floats × 4 bytes × N entities
- Estimate: 50K entities × 1024 × 4 = ~200MB for the fundamentals_ohlcv view alone
- **No new index creation needed**: `intelligence-migrations 0001` already created a partial HNSW index:
  ```sql
  CREATE INDEX idx_entity_emb_fstate_hnsw ON entity_embedding_state
      USING hnsw (embedding vector_cosine_ops)
      WHERE view_type = 'fundamentals_ohlcv' AND embedding IS NOT NULL;
  ```
- HNSW advantages over IVFFlat: no training step, dynamic insertion, no centroid lock contention, better recall at same latency
- Expected ANN latency: 10–30ms for 50K entities with HNSW (better than IVFFlat at equivalent recall)

---

## §11 Test Strategy

### Unit Tests (services/market-data)

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_screen_response_includes_instrument_fields` | `ScreenInstrumentResponse` has `ticker`, `name`, `exchange`, `sector` fields | HIGH |
| `test_screen_sort_by_ticker` | `sort_by='ticker'` returns instruments sorted alphabetically | HIGH |
| `test_screen_sort_by_metric_nulls_last` | Metric with NULL values: NULLs appear after non-NULLs in ASC sort | HIGH |
| `test_screen_total_count` | `total` reflects rows before limit/offset, not current page size | HIGH |
| `test_screen_field_metadata_static` | `ScreenFieldMetadata` for `pe_ratio` has correct label, unit, type | MEDIUM |
| `test_screen_sort_by_invalid_field` | Unknown `sort_by` value raises 422 | HIGH |

### Unit Tests (services/knowledge-graph)

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_ensure_rows_exist_company` | `financial_instrument` entity → 3 rows created | HIGH |
| `test_ensure_rows_exist_non_company` | `person` entity → 2 rows created (definition + narrative only) | HIGH |
| `test_ensure_rows_exist_all_entity_types` | Every MentionClass except `financial_instrument` → 2 rows | HIGH |
| `test_similar_entities_final_score_with_boost` | `ann=0.75` + `competes_with` → `final_score=0.90` | HIGH |
| `test_similar_entities_final_score_cap` | `ann=0.95` + `competes_with` → `final_score=1.0` (not 1.10) | HIGH |
| `test_similar_entities_no_embedding` | Entity with null `fundamentals_ohlcv` → `EmbeddingNotAvailableError` | HIGH |
| `test_similar_entities_not_found` | Unknown entity_id → `EntityNotFoundError` | HIGH |
| `test_description_client_cost_cap` | Monthly counter ≥ cap → `generate_description` returns None | HIGH |
| `test_description_client_null_adapter` | `NullDescriptionAdapter.generate_description(...)` always returns None | MEDIUM |
| `test_description_fallback_on_none` | When client returns None → deterministic template used as source_text | HIGH |

### Integration Tests

| Test | Infrastructure | What It Verifies |
|------|---------------|-----------------|
| `test_screener_with_real_db` | market_data_db with seed data | Metric filter returns correct instruments; total count correct |
| `test_similar_entities_ann` | intelligence_db + pgvector | ANN query returns nearest neighbours in correct order |
| `test_cleanup_migration` | intelligence_db | Migration 0003 deletes orphan fundamentals_ohlcv rows; company rows preserved |

---

## §12 Migration Plan

1. Run `intelligence-migrations` migration 0003 (data cleanup, no schema change) — safe to run on live DB
2. Deploy updated S7 with `ensure_rows_exist()` fix — new entities correctly provisioned from this point
3. Deploy updated S3 with enhanced screener response — backwards compatible (new fields added, none removed)
4. Deploy updated S7 with similar entities endpoint — new endpoint, no existing behaviour changed
5. Deploy S9 proxy updates
6. Deploy frontend `ScreenerPage` + `SimilarCompaniesPanel`

---

## §13 Observability

### Metrics (S3 additions)
- `s3_screen_requests_total{sort_by}` — total screen requests by sort key
- `s3_screen_fields_cache_misses_total` — Valkey cache misses for screen/fields
- `s3_screen_duration_seconds` — screener query latency histogram

### Metrics (S7 additions)
- `s7_similar_entities_requests_total{result_count}` — total similarity requests by result count bucket
- `s7_similar_entities_duration_seconds` — similarity query latency histogram (target p95 < 500ms)
- `s7_description_generated_total{provider}` — external description API calls
- `s7_description_cost_usd_total{provider}` — cumulative cost gauge (Valkey-sourced)
- `s7_description_fallback_total` — description generations that fell back to template

---

## §14 Open Questions

| # | Question | Status |
|---|----------|--------|
| OQ-001 | Should `GET /screen/fields` `observed_min`/`observed_max` be recomputed on demand or scheduled? | → Scheduled (6h via APScheduler job) — avoids slow query on hot path |
| OQ-002 | Should similar companies ANN include the `narrative` view with lower weight? | → Deferred to PRD-0019 (multi-view fusion) |
| OQ-003 | Which entity types should appear in similar entity results beyond `financial_instrument`? | → v1: financial_instrument only. ETFs, indices deferred. |
| OQ-004 | Should the screener support OR logic between filters? | → v1: AND only. OR deferred. |
| OQ-005 | ~~IVFFlat `lists` parameter for 50K entities?~~ **Resolved**: HNSW is used (existing partial index `idx_entity_emb_fstate_hnsw`); IVFFlat is not applicable. No index tuning required. |

---

## §15 Implementation Estimate

| Wave | Description | Services | Effort |
|------|-------------|----------|--------|
| A-1 | intelligence-migrations 0003 cleanup migration | intelligence-migrations | 2h |
| A-2 | S7: Fix `ensure_rows_exist()` + entity type awareness | S7 | 3h |
| A-3 | `libs/ml-clients`: `EntityDescriptionClient` Protocol + adapters | libs/ml-clients | 4h |
| A-4 | S7: `DefinitionRefreshWorker` non-company description enhancement | S7 | 3h |
| B-1 | S3: Enhanced screener response + sort + total + `screen_field_metadata` table | S3 | 4h |
| B-2 | S3: `GET /screen/fields` endpoint + Valkey cache + APScheduler job | S3 | 3h |
| B-3 | S7: `EntityEmbeddingANNRepository` + pgvector ANN index | S7 | 3h |
| B-4 | S7: `FindSimilarEntitiesUseCase` + `POST /api/v1/entities/similar` endpoint | S7 | 4h |
| C-1 | S9: Proxy new S3 + S7 endpoints | S9 | 2h |
| C-2 | Frontend: `ScreenerPage` component | Frontend | 6h |
| C-3 | Frontend: `SimilarCompaniesPanel` component | Frontend | 4h |

**Total estimate**: ~38h (5 working days)
