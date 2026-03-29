# Contracts Library

> **Package**: `contracts` · **Path**: `libs/contracts/`
> **Purpose**: Canonical data models and schema versions. Single source of truth for
> the shape of data flowing between services. Zero external dependencies.

---

## Where Contracts Fit

Every event passing between services travels through a shared canonical shape:

```
External API / Provider
        ↓
  Market Ingestion (S2)  ───►  MinIO (claim-check pointer)
        ↓ Kafka event                ↓
  Market Data (S3)  ◄──────►  contracts.CanonicalOHLCVBar
        ↓ Kafka event
  NLP Pipeline (S5)  ◄─────►  contracts.CanonicalArticle
        ↓ Kafka event
  Intelligence (S6)  ◄─────►  contracts.CanonicalSentiment
```

`contracts` defines **what the data looks like** (field names, types, defaults).
`infra/kafka/schemas/` defines **how it is encoded on the wire** (Avro).
The two must be kept in sync. `scripts/gen-contracts.sh` validates this.

---

## Public API

### Shared Enums

| Enum | Values | Used By | Purpose |
|------|--------|---------|---------|
| `ContentSourceType` | eodhd, sec_edgar, finnhub, newsapi, manual | S4, S5 | Content source discriminator in Kafka events |
| `IngestionTaskStatus` | pending, claimed, running, succeeded, retry, failed | S2, S4 | Scheduler-worker task lifecycle states |

Import from `contracts.enums` or the package root:
```python
from contracts.enums import ContentSourceType, IngestionTaskStatus
from contracts import IngestionTaskStatus  # also works
```

Services re-export from their domain layer for internal use (e.g. `market_ingestion.domain.enums`).

### Canonical Models

**Market data (OHLCV, quotes, fundamentals):**

| Class | Purpose | Version |
|-------|---------|---------|
| `CanonicalOHLCVBar` | Open-high-low-close-volume bar | v1 |
| `CanonicalQuote` | Real-time / delayed quote snapshot | v1 |
| `CanonicalFundamentals` | Company fundamentals snapshot (18 sections) | v1 |

**Extended market data (new in waves 01–03, EXT-02–EXT-08):**

| Class | Purpose | Version |
|-------|---------|---------|
| `CanonicalEarningsEvent` | Earnings announcement event | v1 |
| `CanonicalEconomicEvent` | Economic calendar event (inflation, GDP, etc.) | v1 |
| `CanonicalMacroIndicator` | Macro indicator snapshot (GDP, inflation rate, unemployment) | v1 |
| `CanonicalNewsSentiment` | News article with sentiment analysis | v1 |
| `CanonicalInsiderTransaction` | Insider trading transaction | v1 |
| `CanonicalYieldPoint` | Yield curve point (maturity + rate) | v1 |
| `CanonicalMarketCapPoint` | Historical market cap data point | v1 |

**NLP pipeline (sentiment, entities):**

| Class | Purpose | Version |
|-------|---------|---------|
| `CanonicalArticle` | Normalised news/content article | v1 |
| `CanonicalEntity` | Knowledge-graph entity (NER output) | v1 |
| `CanonicalSentiment` | Sentiment analysis result | v1 |
| `CanonicalDailySentiment` | Aggregated daily sentiment signal | v1 |

**Ingestion pipeline events (new in Wave 05):**

| Model | Avro schema | Producer | Consumer | Version constant |
|-------|-------------|----------|---------|-----------------|
| `CanonicalRawArticleEvent` | `content.article.raw.v1.avsc` | S4 | S5 | `RAW_ARTICLE_SCHEMA_VERSION` |
| `CanonicalStoredArticleEvent` | `content.article.stored.v1.avsc` | S5 | S6 | `STORED_ARTICLE_SCHEMA_VERSION` |
| `CanonicalEnrichedArticleEvent` | `nlp.article.enriched.v1.avsc` | S6 | S7 | `ENRICHED_ARTICLE_SCHEMA_VERSION` |
| `CanonicalSignalEvent` | `nlp.signal.detected.v1.avsc` | S6 | S10 | `SIGNAL_SCHEMA_VERSION` |
| `CanonicalWatchlistEvent` | `portfolio.watchlist.updated.v1.avsc` | S1 | S10 | `WATCHLIST_EVENT_SCHEMA_VERSION` |

### Schema Versions

```python
# Market data
from contracts.versions import OHLCV_SCHEMA_VERSION                   # 1
from contracts.versions import QUOTE_SCHEMA_VERSION                   # 1
from contracts.versions import FUNDAMENTAL_SCHEMA_VERSION             # 1

# Extended market data (waves 01–03)
from contracts.versions import EARNINGS_EVENT_SCHEMA_VERSION          # 1
from contracts.versions import ECONOMIC_EVENT_SCHEMA_VERSION          # 1
from contracts.versions import MACRO_INDICATOR_SCHEMA_VERSION         # 1
from contracts.versions import NEWS_SENTIMENT_SCHEMA_VERSION          # 1
from contracts.versions import INSIDER_TRANSACTION_SCHEMA_VERSION     # 1
from contracts.versions import YIELD_CURVE_SCHEMA_VERSION             # 1
from contracts.versions import MARKET_CAP_SCHEMA_VERSION              # 1

# NLP pipeline
from contracts.versions import ARTICLE_SCHEMA_VERSION                 # 1
from contracts.versions import ENTITY_SCHEMA_VERSION                  # 1
from contracts.versions import SENTIMENT_SCHEMA_VERSION               # 1
from contracts.versions import DAILY_SENTIMENT_SCHEMA_VERSION         # 1

# Pointer event
from contracts.versions import MARKET_DATASET_FETCHED_SCHEMA_VERSION  # 1

# Ingestion pipeline events (Wave 05)
from contracts.versions import RAW_ARTICLE_SCHEMA_VERSION             # 1
from contracts.versions import STORED_ARTICLE_SCHEMA_VERSION          # 1
from contracts.versions import ENRICHED_ARTICLE_SCHEMA_VERSION        # 1
from contracts.versions import SIGNAL_SCHEMA_VERSION                  # 1
from contracts.versions import WATCHLIST_EVENT_SCHEMA_VERSION         # 1
```

---

### Ingestion Event Models

Five new frozen dataclasses in `contracts.canonical.ingestion` cover the S4→S5→S6→S7/S10 event chain.

**`article_id` field naming**: Both `CanonicalStoredArticleEvent` and `CanonicalEnrichedArticleEvent` use `article_id` (not `doc_id`) to match the Avro schema field name exactly. In `content_store_db` the column is `doc_id`, but the event field is `article_id` for schema backward compatibility. Do NOT rename to `doc_id`.

**`CanonicalEnrichedArticleEvent.embedding_model` default mismatch**: The Avro schema default is `"all-MiniLM-L6-v2"` (preserved for backward compatibility with early consumers). The active production model is `bge-large-en-v1.5`. Always read the actual `embedding_model` value from the event payload — never assume the default is the current model.

**`CanonicalWatchlistEvent` event_type values**: There are exactly two valid values:
- `"watchlist.item_added"` — entity added to watchlist
- `"watchlist.item_deleted"` — entity removed from watchlist

`"watchlist.item_removed"` was deprecated in Wave 01 (T-F-001) and is a bug if it appears. The test `test_watchlist_event_type_deleted_not_removed` is a regression guard for this.

**`tuple` vs `list` for collection fields**: `source_article_ids` (on `CanonicalSignalEvent`) and `entity_ids_affected` (on `CanonicalWatchlistEvent`) are stored internally as `tuple` because these are frozen dataclasses — mutable containers like `list` would allow accidental mutation via aliasing. `to_dict()` converts them back to `list` for Avro array compatibility.

**How to bump a schema version (step-by-step):**

1. Add the new field(s) to the dataclass **with a default value** — never remove
   or rename existing fields.
2. Increment the corresponding `*_SCHEMA_VERSION` constant.
3. Update the Avro `.avsc` file in `infra/kafka/schemas/` to add the field with
   a `"default"` key — Avro requires defaults for forward compatibility.
4. Run `scripts/gen-contracts.sh` to validate Python ↔ Avro parity.
5. Update the `schema_version` field default in the dataclass `__post_init__`
   or `field(default=N)` to the new version.
6. Update `docs/libs/contracts.md` model table to reflect the new version.
7. Consumers reading older events (version `N-1`) must handle the missing field
   gracefully (the Avro default fills it in automatically during deserialization).

> **Never**: remove a field, rename a field, or change a field's type.
> These are breaking changes that require a new topic (`*.v2`).

### Parsing Utilities

| Function | Purpose |
|----------|---------|
| `parse_ohlcv_from_jsonl(path)` | Parses JSONL file → `list[CanonicalOHLCVBar]` |
| `parse_ohlcv_from_json(path)` | Parses JSON array file → `list[CanonicalOHLCVBar]` |
| `parse_ohlcv_from_parquet(path)` | Parses Parquet file → `list[CanonicalOHLCVBar]` (requires `pyarrow`) |
| `to_parquet(bars, path)` | Writes canonical bars to Parquet (requires `pyarrow`) |
| `to_jsonl(bars, path)` | Writes canonical bars to JSONL |

Parquet support is optional — install with `pip install contracts[parquet]`.

---

## Model Anatomy

All canonical models are **frozen dataclasses** with:

- Type-annotated fields matching the Avro schema
- A `from_dict(cls, d)` classmethod (for deserialization)
- A `to_dict(self)` method (for serialization)
- An `AvroDictable` protocol compliance

```python
from dataclasses import dataclass, field
from datetime import datetime

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
    provider: str = ""          # added in wave-01 for legacy consumer parity
    timeframe: str = "1d"       # added in wave-01 for legacy consumer parity
    fetched_at: datetime | None = None  # added in wave-01 for legacy consumer parity
    schema_version: int = field(default=1, init=False)

    @classmethod
    def from_dict(cls, d: dict) -> "CanonicalOHLCVBar":
        ...

    def to_dict(self) -> dict:
        ...
```

### float vs Decimal

All price and numeric fields use `float` (Python `float64`, ~15 significant
digits). The legacy codebase used `Decimal` — this was intentionally simplified.
Float64 precision is adequate for OHLCV financial data; downstream services
that require exact decimal arithmetic (e.g., order books) should apply their
own Decimal conversion.

---

## Guidelines

1. **Runtime dependency**: `structlog` is required (used by `parsing.py`).
   `pyarrow` is optional — add the `[parquet]` extra for Parquet I/O.
2. **Frozen**: All models are immutable once created.
3. **Versioned**: Every model carries a `schema_version` field that is
   auto-populated from `contracts.versions`.
4. **Backwards-compatible changes only**: Add fields with defaults. Never
   remove or rename fields — create a new version instead.
5. **AvroDictable compliance**: Every canonical model's `to_dict()` output must
   be accepted by `fastavro.validate(schema, output)` with no exception. Run
   the contract tests in `libs/contracts/tests/` after every model change.

---

## Common Pitfalls

1. **Removing or renaming a field** — this breaks every consumer that reads
   old events from Kafka (topics are retained; old messages never disappear).
   Always add new fields with defaults instead.
2. **Forgetting to update the Avro schema** — the Python dataclass and the
   `.avsc` file diverge silently. Run `scripts/gen-contracts.sh` every time.
3. **Comparing `schema_version` in consumer logic** — don't branch on version
   numbers in business logic. Avro defaults handle missing fields automatically.
   Version numbers are for monitoring and alerting, not routing.
4. **Using `Decimal` for price fields** — all price fields use `float`. The
   decision was deliberate (see Model Anatomy). Introducing `Decimal` here would
   break Avro serialization and require custom serializers.
5. **Forgetting `frozen=True`** — if you add a mutable dataclass to this library
   it will be accidentally mutated somewhere in a pipeline. All canonical models
6. **Using `list` for `source_article_ids` or `entity_ids_affected`** — these fields
   are `tuple` internally (frozen dataclass constraint). `to_dict()` converts to `list`
   for Avro array serialization. Don't try to mutate them after construction and don't
   assign a `list` directly to these fields in the constructor.
   must be `frozen=True`.

---

## Testing Strategy

- **Unit**: Round-trip `from_dict → to_dict` for every model (11+ canonical models), edge cases
  (missing optional fields, extra keys ignored).
- **Contract tests**: Validate that `to_dict()` output matches the Avro
  schema in `infra/kafka/schemas/` using `fastavro.validate` (all pointer and canonical schemas).
- **Field additions**: When adding a new canonical model, ensure `from_dict` gracefully
  handles missing fields (use field defaults), and `to_dict` produces valid Avro JSON.
