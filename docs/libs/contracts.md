# Contracts Library

> **Package**: `contracts` · **Path**: `libs/contracts/` · **Version**: 2025.6.0
> **Purpose**: Canonical data models and schema versions. Single source of truth for
> the shape of data flowing between services. Minimal runtime dependencies:
> `structlog` and `pydantic` (hard), `pyarrow` (optional, `[parquet]` extra).

---

## Purpose

`contracts` defines **what data looks like** as it crosses service boundaries.
Every Kafka event, every claim-check pointer, every cross-service API payload
uses a model defined here. Without this library, each service would define its
own `Article` or `OHLCVBar` dataclass and they would inevitably drift.

`infra/kafka/schemas/*.avsc` defines **how data is encoded on the wire** (Avro).
`contracts` defines **what it means in Python**. The two must be kept in sync —
`scripts/gen-contracts.sh` validates this.

---

## Installation

```toml
# In a service's pyproject.toml:
[project]
dependencies = ["contracts"]

# With optional Parquet I/O:
dependencies = ["contracts[parquet]"]
```

```bash
pip install -e "libs/contracts"
pip install -e "libs/contracts[parquet]"   # adds pyarrow
```

---

## Public API

### Shared Enums (`contracts.enums`)

```python
from contracts.enums import ContentSourceType, IngestionTaskStatus
# or from the package root:
from contracts import ContentSourceType, IngestionTaskStatus
```

| Enum | Values | Used by |
|------|--------|---------|
| `ContentSourceType` | `eodhd`, `eodhd_ticker_news`, `sec_edgar`, `finnhub`, `newsapi`, `manual`, `polymarket`, `tenant_upload` | S4 (producer), S5 (consumer) |
| `IngestionTaskStatus` | `pending`, `claimed`, `running`, `succeeded`, `retry`, `failed` | S2, S4 scheduler-worker lifecycle |

### Canonical Market Data Models (`contracts.canonical`)

All models are frozen dataclasses with `from_dict(cls, d)` and `to_dict(self)`.

**Core market data:**

| Class | Topic / use | Key fields |
|-------|-------------|------------|
| `CanonicalOHLCVBar` | S2→S3 via claim-check | `symbol`, `exchange`, `date`, `open/high/low/close`, `volume`, `adjusted_close`, `timeframe` |
| `CanonicalQuote` | S3 Valkey cache | `symbol`, `price`, `bid`, `ask`, `volume`, `timestamp` |
| `CanonicalFundamentals` | S2→S3 via claim-check | 18 sections (General, Highlights, Valuation, Technicals, …) |

**Extended market data:**

| Class | Purpose |
|-------|---------|
| `CanonicalEarningsEvent` | Earnings calendar entry (`contracts.canonical.earnings_calendar`) with report date, EPS estimate/actual, revenue |
| `CanonicalInsiderTransaction` | Insider trading transaction (`contracts.canonical.insider_transactions`) — form type, shares, price |
| `CanonicalYieldPoint` | Yield curve point (`contracts.canonical.yield_curve`) — maturity, rate |
| `CanonicalMarketCapPoint` | Historical market cap data point (`contracts.canonical.market_cap`) |
| `CanonicalInstrumentDiscovered` | Trigger event when S3 first observes a new instrument (topic `market.instrument.discovered`). Fields: `event_id`, `occurred_at`, `instrument_id`, `symbol`, `exchange` (`str \| None`), `entity_id` (`str \| None`), `correlation_id`, `causation_id`. |

**NLP / intelligence pipeline:**

| Class | Topic | Producer → Consumer |
|-------|-------|---------------------|
| `CanonicalArticle` | (S5 silver MinIO payload) | S5 → S6 |
| `CanonicalEntity` | NER output record | S6 |
| `CanonicalSentiment` | Article sentiment result | S6 |
| `CanonicalDailySentiment` | Aggregated daily sentiment | S6 |

**Ingestion pipeline events (`contracts.canonical.ingestion`):**

| Class | Avro topic | Producer | Consumer |
|-------|-----------|----------|---------|
| `CanonicalRawArticleEvent` | `content.article.raw.v1` | S4 | S5 |
| `CanonicalStoredArticleEvent` | `content.article.stored.v1` | S5 | S6 |
| `CanonicalEnrichedArticleEvent` | `nlp.article.enriched.v1` | S6 | S7 |
| `CanonicalSignalEvent` | `nlp.signal.detected.v1` | S6 | S10 |
| `CanonicalWatchlistEvent` | `portfolio.watchlist.updated.v1` | S1 | S10 |

**Price resolution (`contracts.canonical.price_snapshot`):**

| Class | Purpose |
|-------|---------|
| `PriceSnapshot` | Resolved, sourced, and freshness-classified price for one instrument. Stored in Valkey by market-data; consumed by S9 for frontend price requests. Fields: `instrument_id`, `symbol`, `exchange`, `price` (Decimal), `price_change`, `price_change_pct`, `source` (`PriceSource`), `freshness_status` (`FreshnessStatus`). |
| `PriceSource` | StrEnum — `FRESH_QUOTE`, `BULK_QUOTE`, `INTRADAY_5M_CLOSE`, `INTRADAY_1H_CLOSE`, `DAILY_CLOSE`, `STALE_SNAPSHOT`, `UNAVAILABLE` |
| `FreshnessStatus` | StrEnum — `LIVE`, `RECENT`, `DELAYED`, `STALE`, `UNAVAILABLE` |

### Cross-Service Event Models (`contracts.events`)

Typed mirrors of Avro schemas for events that are purely cross-service triggers
(never stored as their own DB entity in the producer service).

**Knowledge Graph events (`contracts.events.kg`):**

| Class | Topic | `dirty_reason` / notes |
|-------|-------|------------------------|
| `CanonicalEntityCanonicalCreated` | `entity.canonical.created.v1` | Fields: `entity_id`, `canonical_name`, `entity_type`, `provisional_queue_id`, `alias_texts` (`tuple[str, ...]`) |
| `CanonicalEntityDirtied` | `entity.dirtied.v1` | `dirty_reason`: `new_evidence`, `new_relation`, `alias_added`, `profile_updated` |
| `CanonicalGraphStateChanged` | `graph.state.changed.v1` | Topology change; consumers use for cache invalidation. Fields: `primary_entity_id`, `affected_entity_ids`, `change_type`, `relation_ids`, `canonical_types` |
| `EntityNarrativeGeneratedEvent` | `entity.narrative.generated.v1` | Triggers immediate narrative embedding refresh. Note: `schema_version` is a semver `str` (default `"1.0.0"`), not an `int`. Fields: `entity_id`, `version_id`, `generation_reason`, `model_id`, `narrative_text_length` |
| `CanonicalEntityProvisionalQueued` | `entity.provisional.queued.v1` | New provisional entity discovered by S6. Fields: `queue_id`, `normalized_surface`, `mention_class` |
| `CanonicalRelationTypeProposed` | `relation.type.proposed.v1` | Raw relation type that failed canonicalization (S7 Block 11); feeds human-in-the-loop registry curation. Fields: `proposed_type`, `semantic_mode`, `suggested_decay_class` |

**NLP events (`contracts.events.nlp`):**

| Class | Topic | Notes |
|-------|-------|-------|
| `CanonicalNlpArticleEnriched` | `nlp.article.enriched.v1` | Full enrichment trigger. Carries `raw_relations_json`, `raw_events_json`, `raw_claims_json` as JSON-encoded strings. Use `encode_raw_array()` / `decode_raw_array()` helpers. |
| `CanonicalNlpSignalDetected` | `nlp.signal.detected.v1` | Claim/signal detected during enrichment. Fields: `doc_id`, `claim_id`, `claim_type`, `polarity`, `extraction_confidence`, `market_impact_score`, optional `claimer_entity_id`/`subject_entity_id` |
| `NlpDocumentReady` | (document-ready trigger) | Document parsed and ready for NLP. Fields: `doc_id`, `tenant_id`, `chunk_count`, `word_count` |

**Content events (`contracts.events.content`):**

| Class | Topic | Notes |
|-------|-------|-------|
| `ContentDocumentDeleted` | — | Content deletion notification. Fields: `event_id`, `event_type`, `schema_version`, `occurred_at`, `doc_id`, `tenant_id`. |

**Alert events (`contracts.events.alert`):**

| Class | Topic | Notes |
|-------|-------|-------|
| `CanonicalAlertCreated` | `alert.created.v1` | User-initiated alert rule persisted. Fields: `alert_id`, `user_id`, `tenant_id`, `entity_id`, `condition`, `threshold`, `severity` (default `"low"`), `source` (default `"llm_tool"`). |

**Intelligence events (`contracts.events.intelligence`):**

| Class | Topic | Notes |
|-------|-------|-------|
| `CanonicalIntelligenceContradiction` | `intelligence.contradiction.v1` | A new claim contradicts an existing claim about an entity. Fields: `subject_entity_id`, `claim_type`, `new_claim_id`, `contradicting_claim_id`, `contradiction_strength`, `affected_relation_ids`, `is_backfill`. |

**Portfolio events (`contracts.events.portfolio`):**

| Class | Topic | Notes |
|-------|-------|-------|
| `PortfolioHoldingRecomputeRequested` | `portfolio.holding.recompute_requested.v1` | Pydantic `BaseModel` (not a frozen dataclass). Requests recomputation of a portfolio's holdings. Fields: `aggregate_id`/`portfolio_id`, `tenant_id`, `owner_id`, plus standard envelope fields (`event_id`, `event_type`, `occurred_at`, `correlation_id`, `causation_id`). |

### Trust Authority (`contracts.trust`)

```python
from contracts import SOURCE_AUTHORITY  # dict[str, float]
from contracts.trust import SOURCE_AUTHORITY
```

Maps source type strings to authority scores (0.0–1.0) used for retrieval ranking.
Examples: `sec_10k → 1.00`, `eodhd_news → 0.65`, `social → 0.30`, `default → 0.50`.

### Pagination Models (`contracts.pagination`)

```python
from contracts import PaginationParams, PaginatedResponse
```

Opt-in pydantic models (`BaseModel`) for converging per-service limit/offset
pagination onto one canonical shape. Existing per-service schemas keep working.

| Class | Fields | Notes |
|-------|--------|-------|
| `PaginationParams` | `limit: int = 20` (1–200), `offset: int = 0` (≥0) | Query-param input; use as a FastAPI `Depends()`. |
| `PaginatedResponse[T]` | `items: list[T]`, `total: int`, `limit: int`, `offset: int`, `has_more: bool` | Generic response wrapper; `has_more` is set by the caller, not derived. |

```python
@router.get("/items")
async def list_items(p: PaginationParams = Depends()) -> PaginatedResponse[ItemOut]:
    rows, total = await repo.list(limit=p.limit, offset=p.offset)
    return PaginatedResponse[ItemOut](
        items=rows, total=total, limit=p.limit, offset=p.offset,
        has_more=(p.offset + len(rows)) < total,
    )
```

### Numeric Grounding (`contracts.numeric_grounding`)

Shared classification vocabulary + default tolerances for numeric-grounding
validation (PLAN-0093). The validation logic itself lives in rag-chat; this
module exposes only the contract types so consumers depend on `contracts`,
not on the rag-chat service package.

```python
from contracts.numeric_grounding import FieldKind, DEFAULT_TOLERANCES
```

| Symbol | Type | Purpose |
|--------|------|---------|
| `FieldKind` | `str` `Enum` | Financial field families that share rounding behaviour: `price`, `return_pct`, `year`, `quarter`, `eps`, `ratio`, `revenue`, `market_cap`, `shares`, `headcount`, `prose`, `unknown`. |
| `DEFAULT_TOLERANCES` | `dict[FieldKind, float]` | Per-kind relative-diff tolerance (e.g. `PRICE → 0.001`, `YEAR → 0.0`, `EPS → 0.02`). Mutable module-level dict so deployments can patch tolerances at startup. |

### Schema Version Constants (`contracts.versions`)

```python
from contracts.versions import (
    OHLCV_SCHEMA_VERSION,               # 1
    QUOTE_SCHEMA_VERSION,               # 1
    FUNDAMENTAL_SCHEMA_VERSION,         # 1
    ARTICLE_SCHEMA_VERSION,             # 1
    ENTITY_SCHEMA_VERSION,              # 1
    SENTIMENT_SCHEMA_VERSION,           # 1
    MARKET_DATASET_FETCHED_SCHEMA_VERSION,  # 1
    RAW_ARTICLE_SCHEMA_VERSION,         # 1
    STORED_ARTICLE_SCHEMA_VERSION,      # 1
    ENRICHED_ARTICLE_SCHEMA_VERSION,    # 1
    SIGNAL_SCHEMA_VERSION,              # 1
    WATCHLIST_EVENT_SCHEMA_VERSION,     # 1
)
```

### Parsing Utilities (`contracts.parsing`)

| Function | Purpose |
|----------|---------|
| `parse_ohlcv_from_jsonl(path)` | Parse JSONL file → `list[CanonicalOHLCVBar]` |
| `parse_ohlcv_from_json(path)` | Parse JSON array file → `list[CanonicalOHLCVBar]` |
| `parse_ohlcv_from_parquet(path)` | Parse Parquet file → `list[CanonicalOHLCVBar]` (requires `pyarrow`) |
| `to_parquet(bars, path)` | Write canonical bars to Parquet (requires `pyarrow`) |
| `to_jsonl(bars, path)` | Write canonical bars to JSONL |

### NLP Article Enrichment Helpers (`contracts.events.nlp.article_enriched`)

| Function | Purpose |
|----------|---------|
| `encode_raw_array(items)` | Encode `list[dict] | None` → JSON string for Avro transport. Returns `None` for empty/None input. |
| `decode_raw_array(blob)` | Decode JSON string → `list[dict]`. Returns `[]` on None, malformed, or oversized (>16 MB) input. Logs a warning instead of raising. |

---

## Model Anatomy

Most canonical/event models are **frozen dataclasses** with `from_dict(cls, d)` /
`to_dict(self)`. The exceptions are the pydantic models in
`contracts.pagination` (`PaginationParams`, `PaginatedResponse`) and
`contracts.events.portfolio` (`PortfolioHoldingRecomputeRequested`).

```python
from dataclasses import dataclass, field
from contracts.versions import OHLCV_SCHEMA_VERSION

@dataclass(frozen=True)
class CanonicalOHLCVBar:
    symbol: str
    exchange: str
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    adjusted_close: float | None = None
    source: str = ""
    provider: str = ""
    timeframe: str = "1d"
    fetched_at: datetime | None = None
    schema_version: int = field(default=OHLCV_SCHEMA_VERSION, init=False)

    @classmethod
    def from_dict(cls, d: dict) -> "CanonicalOHLCVBar":
        ...

    def to_dict(self) -> dict:
        ...
```

- **`frozen=True`** — immutable after creation; no accidental mutation through aliasing.
- **`from_dict` / `to_dict`** — explicit serialization boundary; no magic.
- **`schema_version`** — auto-set; used for monitoring, not consumer branching.
- **`float` for prices** — deliberate choice; `float64` gives ~15 significant digits,
  adequate for OHLCV data. `Decimal` would break Avro serialization.

---

## Usage Examples

```python
# Consuming a stored article event from Kafka:
from contracts.canonical.ingestion import CanonicalStoredArticleEvent

raw_dict = deserialize_confluent_avro(schema, raw_bytes)
event = CanonicalStoredArticleEvent.from_dict(raw_dict)
print(event.article_id)    # NOTE: field is "article_id", not "doc_id" (Avro compat)

# Building an enriched article event to publish:
from contracts.events.nlp.article_enriched import CanonicalNlpArticleEnriched, encode_raw_array

event = CanonicalNlpArticleEnriched(
    event_id=new_ulid(),
    occurred_at=to_iso8601(utc_now()),
    doc_id=str(doc_id),
    source_type="eodhd_news",
    routing_tier="standard",
    routing_score=0.72,
    section_count=3,
    chunk_count=12,
    mention_count=8,
    raw_relations_json=encode_raw_array(relations),
    raw_events_json=encode_raw_array(events),
    raw_claims_json=encode_raw_array(claims),
)
payload = event.to_dict()   # Avro-ready dict

# Trust-weighted ranking:
from contracts import SOURCE_AUTHORITY
weight = SOURCE_AUTHORITY.get(source_type, SOURCE_AUTHORITY["default"])  # 0.50 fallback
```

---

## Architecture Notes

### Why frozen dataclasses for wire models?

Avro-backed wire models (everything in `contracts.canonical` and most of
`contracts.events`) are frozen dataclasses: zero runtime overhead for field
access, no validation cost on the hot deserialization path, and `frozen=True`
guards against accidental mutation while a payload flows through a pipeline.
`from_dict`/`to_dict` make the serialization boundary explicit.

Pydantic **is** a hard dependency of `contracts` (see `pyproject.toml`) and is
used for the validation-bearing models that are not raw Avro wire payloads:
`PaginationParams` / `PaginatedResponse` (HTTP request/response shaping with
bounds) and `PortfolioHoldingRecomputeRequested` (R28 canonical topic model).

### `article_id` vs `doc_id`

`CanonicalStoredArticleEvent` and `CanonicalEnrichedArticleEvent` use the field
name `article_id` (not `doc_id`) to match the Avro schema exactly. In
`content_store_db` the column is `doc_id`, but the event field was named
`article_id` for backward compatibility with early consumers. Do NOT rename it.

### `tuple` vs `list` for collection fields

`source_article_ids` (on `CanonicalSignalEvent`) and `entity_ids_affected` (on
`CanonicalWatchlistEvent`) are stored as `tuple` internally because frozen
dataclasses must not contain mutable containers. `to_dict()` converts them back
to `list` for Avro array compatibility.

### `CanonicalWatchlistEvent.event_type`

Valid values: `"watchlist.item_added"` and `"watchlist.item_deleted"`.
The value `"watchlist.item_removed"` was deprecated in Wave 01 (T-F-001) — it
is a bug if it appears.

---

## How to Bump a Schema Version

1. Add the new field(s) to the dataclass **with a default value** (never remove or rename).
2. Increment the `*_SCHEMA_VERSION` constant in `contracts/versions.py`.
3. Update the Avro `.avsc` file in `infra/kafka/schemas/` — add the field with a `"default"` key.
4. Run `scripts/gen-contracts.sh` to validate Python ↔ Avro parity.
5. Update `docs/libs/contracts.md` model table.

> **Never**: remove a field, rename a field, or change a field's type. These
> are breaking changes that require a new topic (e.g. `*.v2`).

---

## Configuration

`contracts` has no configuration and reads no environment variables. All models
are statically defined.

---

## Extension Points

- **New canonical model**: create `contracts/canonical/<domain>.py`, add to
  `contracts/__init__.py`, create matching `.avsc` in `infra/kafka/schemas/`.
- **New cross-service event**: create `contracts/events/<domain>/<event_name>.py`.
  Not all events need a canonical Python model — only those consumed by services
  that benefit from typed deserialization.
- **New trust authority entry**: add to `contracts/trust/__init__.py`.

---

## Testing

```bash
cd libs/contracts
python -m pytest tests/ -v
```

**Test coverage:**
- Round-trip `from_dict → to_dict` for all models (11+ canonical models).
- Avro schema alignment using `fastavro.validate` against `infra/kafka/schemas/`.
- `from_dict` handles missing optional fields gracefully (uses field defaults).
- `CanonicalWatchlistEvent` regression: `event_type` must be `item_deleted` not `item_removed`.
- `decode_raw_array` handles `None`, malformed JSON, oversized blobs.

---

## Common Pitfalls

1. **Removing or renaming a field** — Kafka topics retain old messages. Old consumers
   will break. Add fields with defaults; create `*.v2` topics for breaking changes.
2. **Forgetting to update the Avro schema** — Python dataclass and `.avsc` silently
   diverge. Run `scripts/gen-contracts.sh` every time.
3. **Using `Decimal` for price fields** — all price fields use `float`. Introducing
   `Decimal` breaks Avro serialization and requires custom serializers.
4. **`frozen=True` missing** — without it, mutable dataclasses are accidentally
   mutated somewhere in a pipeline.
5. **Branching on `schema_version` in business logic** — don't. Avro defaults handle
   missing fields automatically. Version numbers are for monitoring, not routing.
