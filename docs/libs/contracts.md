# Contracts Library

> **Package**: `contracts` · **Path**: `libs/contracts/`
> **Purpose**: Canonical data models and schema versions. Single source of truth for
> the shape of data flowing between services. Zero external dependencies.

---

## Public API

### Canonical Models

| Class | Purpose | Version |
|-------|---------|---------|
| `CanonicalOHLCVBar` | Open-high-low-close-volume bar | v2 |
| `CanonicalQuote` | Real-time / delayed quote snapshot | v1 |
| `CanonicalFundamentals` | Company fundamentals snapshot | v1 |
| `CanonicalArticle` | Normalised news/content article | v1 |
| `CanonicalEntity` | Knowledge-graph entity (NER output) | v1 |
| `CanonicalSentiment` | Sentiment analysis result | v1 |

### Schema Versions

```python
from contracts.versions import OHLCV_SCHEMA_VERSION      # 2
from contracts.versions import QUOTE_SCHEMA_VERSION       # 1
from contracts.versions import FUNDAMENTAL_SCHEMA_VERSION # 1
from contracts.versions import ARTICLE_SCHEMA_VERSION     # 1
from contracts.versions import ENTITY_SCHEMA_VERSION      # 1
from contracts.versions import SENTIMENT_SCHEMA_VERSION   # 1
```

Bump the version constant **before** changing the dataclass shape. Consumers
use the version to decide whether they can handle the payload.

### Parsing Utilities

| Function | Purpose |
|----------|---------|
| `parse_ohlcv_from_jsonl(path)` | Parses JSONL file → `list[CanonicalOHLCVBar]` |
| `parse_ohlcv_from_parquet(path)` | Parses Parquet file → `list[CanonicalOHLCVBar]` |
| `to_parquet(bars, path)` | Writes canonical bars to Parquet |
| `to_jsonl(bars, path)` | Writes canonical bars to JSONL |

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
    schema_version: int = field(default=2, init=False)

    @classmethod
    def from_dict(cls, d: dict) -> "CanonicalOHLCVBar":
        ...

    def to_dict(self) -> dict:
        ...
```

---

## Guidelines

1. **No external dependencies**: This library depends only on the Python
   standard library. Pydantic, protobuf, etc. are NOT allowed here.
2. **Frozen**: All models are immutable once created.
3. **Versioned**: Every model carries a `schema_version` field that is
   auto-populated from `contracts.versions`.
4. **Backwards-compatible changes only**: Add fields with defaults. Never
   remove or rename fields — create a new version instead.

---

## Testing Strategy

- **Unit**: Round-trip `from_dict → to_dict` for every model, edge cases
  (missing optional fields, extra keys ignored).
- **Contract tests**: Validate that `to_dict()` output matches the Avro
  schema in `infra/kafka/schemas/`.
