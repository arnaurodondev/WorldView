# ADR-0004: Valkey Key Taxonomy and TTL Conventions

**Date**: 2026-03-08
**Status**: Accepted
**Deciders**: Architecture Decision Lead, Data Platform Engineer

---

### Context

Multiple services in the Worldview platform use Valkey (Redis-compatible) as a
cache layer:

- **S3 Market Data** — caches OHLCV bars, quotes, and fundamentals.
- **S9 API Gateway** — caches aggregated portfolio views and rate-limit counters.
- **S7 RAG/Chat** — caches embedding lookup results.

Without a standard key structure, the platform risks:
- Key collisions between services sharing a Valkey instance.
- Unbounded key growth (no TTL → memory exhaustion).
- Opaque cache keys that are hard to debug or invalidate.

### Decision

Adopt a **five-segment key format** for all Valkey keys:

```
<scope>:<version>:<resource>:<id>[:<qualifier>]
```

#### Segment definitions

| Segment | Required | Description | Example |
|---------|----------|-------------|---------|
| `scope` | Yes | Owning service abbreviation | `md`, `gw`, `nlp`, `content` |
| `version` | Yes | API/schema version | `v1`, `v2` |
| `resource` | Yes | Logical resource type | `quote`, `ohlcv`, `session`, `enrichment` |
| `id` | Yes | Resource identifier (instrument, user, etc.) | `AAPL`, `user-42` |
| `qualifier` | No | Sub-resource or facet | `sentiment`, `1d`, `daily` |

#### Scope registry

| Scope | Service | Notes |
|-------|---------|-------|
| `md` | S3 Market Data | Market prices and fundamentals |
| `gw` | S9 API Gateway | Rate limits, session tokens, aggregated views |
| `content` | S4 Content Store | Article metadata lookups |
| `nlp` | S7 NLP Pipeline | Enrichment results, signal cache |

#### Key examples

```
md:v1:quote:AAPL
md:v1:ohlcv:AAPL:1d
gw:v1:session:abc123
nlp:v1:enrichment:article-42:sentiment
content:v1:article-meta:article-99
```

#### TTL tiers

| Tier | Default TTL | Use cases |
|------|-------------|-----------|
| Real-time | 10 s | L1 ticker price, bid/ask spread |
| Quote | 30 s | Last quote, intraday snapshot |
| OHLCV | 5 min | Aggregated bars |
| Fundamentals | 1 hr | P/E ratio, EPS |
| Static | 24 hr | Instrument metadata, supported tickers list |

All keys **must** have a TTL.  Keys without TTL are a configuration error.

#### Invalidation strategy

Cache invalidation follows an **event-driven cache-bust** model:

1. A Kafka consumer listening on the relevant domain topic (e.g.
   `market.dataset.fetched`) calls `ValkeyClient.delete()` or
   `ValkeyClient.delete_many()` for affected keys when a new data version
   arrives.
2. TTL-based expiry serves as the safety net if the invalidation consumer
   is temporarily unavailable.
3. Services **must not** rely solely on active invalidation; TTL expiry is
   always the last line of defence.

### Consequences

#### Positive
- Collision-free namespacing across all services on a shared Valkey instance.
- TTL enforcement prevents memory exhaustion.
- Readable, debuggable key names in logs and monitoring.
- Predictable cardinality — scoped scans (`md:v1:quote:*`) remain bounded.

#### Negative
- All services must follow the convention; violations require a breaking
  change to invalidation logic.
- Key length increases slightly vs bare identifiers.

#### Neutral
- `SCAN` commands using prefix patterns (`md:v1:quote:*`) are safe for
  bounded-result sets; `KEYS *` in production is an anti-pattern.

### Alternatives Considered

| Alternative | Pros | Cons | Why Rejected |
|-------------|------|------|--------------|
| Flat keys (`quote:AAPL`) | Simple | No namespace isolation; collision risk between services | Rejected — services share one Valkey instance |
| Per-service Valkey DB index | Full isolation | DB index is a coarse lever; no cross-service queries possible | Rejected — adds operational complexity |
| Hash-per-resource (`HSET md:v1:quote AAPL ...`) | Atomic batch updates | No per-field TTL in Redis hash; memory management harder | Rejected — TTL is a hard requirement per key |

### References

- `libs/messaging/src/messaging/valkey/client.py` — `ValkeyClient` implementation
- `docs/libs/messaging.md` — Valkey usage section
- AGENTS.md §2 Naming Conventions — MinIO/Valkey key patterns
