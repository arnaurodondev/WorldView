# Reusing Code from the Original Thesis Repository

> This guide maps every reusable component from `platform_repo/` to its new
> location in `worldview/`. Use it as a migration checklist.

---

## Migration Strategy

**Principle**: Copy → Adapt → Delete legacy imports.

Do **not** symlink or reference the old repo. Every piece of code that moves
into `worldview/` must be reviewed, reformatted (ruff), and re-tested before
it is considered migrated.

---

## Library-by-Library Migration

### 1. `common` → `libs/common/`

| Legacy path | Worldview path | Action |
|-------------|---------------|--------|
| `libs/common/src/common/time.py` | `libs/common/src/common/time.py` | **Copy as-is** — `utc_now`, `ensure_utc`, `to_iso8601`, `from_iso8601`, `parse_bar_date`, `parse_bar_datetime` are all reusable unchanged. |
| `libs/common/src/common/ids.py` | `libs/common/src/common/ids.py` | File was empty placeholder. **Write fresh** with `new_uuid()`, `new_uuid_str()`, `new_ulid()`. |
| `libs/common/src/common/types.py` | `libs/common/src/common/types.py` | File was empty placeholder. **Write fresh** with `NewType` aliases. |

### 2. `contracts` → `libs/contracts/`

| Legacy path | Worldview path | Action |
|-------------|---------------|--------|
| `libs/contracts/src/contracts/versions.py` | `libs/contracts/src/contracts/versions.py` | **Copy & extend** — add `ARTICLE_SCHEMA_VERSION`, `ENTITY_SCHEMA_VERSION`, `SENTIMENT_SCHEMA_VERSION`. |
| `libs/contracts/src/contracts/canonical/ohlcv.py` | `libs/contracts/src/contracts/canonical/ohlcv.py` | **Copy as-is** — `CanonicalOHLCVBar` frozen dataclass. Verify `schema_version` default matches `OHLCV_SCHEMA_VERSION`. |
| `libs/contracts/src/contracts/canonical/quotes.py` | `libs/contracts/src/contracts/canonical/quotes.py` | **Copy as-is** — `CanonicalQuote`. |
| `libs/contracts/src/contracts/canonical/fundamentals.py` | `libs/contracts/src/contracts/canonical/fundamentals.py` | **Copy as-is** — `CanonicalFundamentals`. |
| *(new)* | `libs/contracts/src/contracts/canonical/article.py` | **Write fresh** — `CanonicalArticle` for Content service. |
| *(new)* | `libs/contracts/src/contracts/canonical/entity.py` | **Write fresh** — `CanonicalEntity` for Intelligence service. |
| *(new)* | `libs/contracts/src/contracts/canonical/sentiment.py` | **Write fresh** — `CanonicalSentiment` for Intelligence service. |
| `libs/contracts/src/contracts/parsing.py` | `libs/contracts/src/contracts/parsing.py` | **Copy & review** — JSONL/JSON/Parquet parsing utilities. May need `polars` support added. |

### 3. `messaging` → `libs/messaging/`

| Legacy path | Worldview path | Action |
|-------------|---------------|--------|
| `libs/messaging/src/messaging/consumer.py` | `libs/messaging/src/messaging/consumer.py` | **Copy & refactor** — `BaseKafkaConsumer` (576 lines). Changes: extract metrics to observability lib, add structured logging via `get_logger()`, keep idempotency logic intact. |
| `libs/messaging/src/messaging/producer.py` | `libs/messaging/src/messaging/producer.py` | **Copy & refactor** — Keep `KafkaProducerConfig` (acks=all, enable_idempotence=True). Add schema registry integration. |
| `libs/messaging/src/messaging/outbox.py` | `libs/messaging/src/messaging/outbox.py` | **Copy & refactor** — `BaseOutboxDispatcher` (536 lines). Changes: extract lease logic into a helper, add metrics counters, keep backpressure and error handling. |
| `libs/messaging/src/messaging/schemas.py` | `libs/messaging/src/messaging/schemas.py` | **Copy as-is** — Avro schema loading, `AvroDictable` protocol, `load_schema()`, `serialize_avro()`, `deserialize_avro()`. |
| `libs/messaging/src/messaging/valkey.py` | `libs/messaging/src/messaging/valkey.py` | **Copy & refactor** — `ValkeyClient` async Redis wrapper. Changes: rename old `RedisClient` references, add structured logging. |
| `libs/messaging/src/messaging/topics.py` | `libs/messaging/src/messaging/topics.py` | **Copy & extend** — Topic name constants. Add new topics: `content.article.ingested`, `intelligence.entity.extracted`, `intelligence.sentiment.scored`, `chat.query.answered`. |

### 4. `storage` → `libs/storage/`

| Legacy path | Worldview path | Action |
|-------------|---------------|--------|
| `libs/storage/src/storage/object_storage.py` | `libs/storage/src/storage/object_storage.py` | **Copy & refactor** — `ObjectStorage` ABC + `S3ObjectStorage`. Changes: add `put_json`/`get_json` convenience methods, add async streaming for large objects (future). |
| `libs/storage/src/storage/settings.py` | `libs/storage/src/storage/settings.py` | **Copy as-is** — `StorageSettings` pydantic-settings model. |
| `libs/storage/src/storage/key_builder.py` | `libs/storage/src/storage/key_builder.py` | **Copy & extend** — `KeyBuilder`. Add validation regex, new service prefixes. |
| `libs/storage/src/storage/health.py` | `libs/storage/src/storage/health.py` | **Copy as-is** — health check utility. |

### 5. `observability` → `libs/observability/` (NEW)

No legacy code exists. Build from scratch using:
- `structlog` for structured logging (replace ad-hoc `logging` usage in legacy services)
- `prometheus-client` for metrics (extract inline counters from legacy consumers/dispatchers)
- `opentelemetry-*` for distributed tracing (upgrade from legacy's partial OTel integration)

---

## Service-by-Service Migration

### S1: Portfolio Service

| Legacy path | Worldview path | Action |
|-------------|---------------|--------|
| `apps/backend-portfolio/src/portfolio/domain/` | `services/portfolio/src/portfolio/domain/` | **Copy as-is** — entities (Portfolio, Holding, Transaction), value objects (Money, Weight), domain services. Clean architecture boundary is well-defined. |
| `apps/backend-portfolio/src/portfolio/application/` | `services/portfolio/src/portfolio/application/` | **Copy & refactor** — use-case handlers. Replace direct logger with `get_logger()`. |
| `apps/backend-portfolio/src/portfolio/infrastructure/persistence/` | `services/portfolio/src/portfolio/infrastructure/persistence/` | **Copy & refactor** — async SQLAlchemy repositories. Update imports to new lib paths. |
| `apps/backend-portfolio/src/portfolio/infrastructure/kafka/` | `services/portfolio/src/portfolio/infrastructure/kafka/` | **Copy & refactor** — `TenantCreatedConsumer`, `UserCreatedConsumer`, `TransactionRecordedDispatcher`. Update base class imports. |
| `apps/backend-portfolio/src/portfolio/api/` | `services/portfolio/src/portfolio/api/` | **Copy & refactor** — 14+ FastAPI endpoints. Add `/healthz`, `/readyz`, `/metrics` if missing. |
| `apps/backend-portfolio/alembic/` | `services/portfolio/alembic/` | **Copy & regenerate** — Copy `alembic.ini` + `env.py`. Regenerate migration files against clean DB to avoid legacy state. |

### S2: Market Ingestion Service

| Legacy path | Worldview path | Action |
|-------------|---------------|--------|
| `apps/backend-market-ingestion/src/market_ingestion/domain/` | `services/market-ingestion/src/market_ingestion/domain/` | **Copy as-is** — Dataset, Instrument entities, scheduling logic. |
| `apps/backend-market-ingestion/src/market_ingestion/application/` | `services/market-ingestion/src/market_ingestion/application/` | **Copy & refactor** — worker orchestration, scheduling. |
| `apps/backend-market-ingestion/src/market_ingestion/infrastructure/` | `services/market-ingestion/src/market_ingestion/infrastructure/` | **Copy & refactor** — EOD Historical Data adapter, Kafka producer, S3 upload (claim-check). |
| `apps/backend-market-ingestion/alembic/` | `services/market-ingestion/alembic/` | **Regenerate** — Fresh migrations. |

### S3: Market Data Service

| Legacy path | Worldview path | Action |
|-------------|---------------|--------|
| `apps/backend-market-data/src/market_data/` | `services/market-data/src/market_data/` | **Copy & refactor** — 3 Kafka consumers (OHLCV materializer, quote consumer, fundamentals consumer), REST API (18+ endpoints), TimescaleDB queries. Major refactor: split monolithic query module. |
| `apps/backend-market-data/alembic/` | `services/market-data/alembic/` | **Regenerate** — Fresh migrations with TimescaleDB hypertable creation. |

### S4–S5: Content Service (NEW)

No legacy code. Build from scratch per `docs/services/content.md`.

### S6–S7: Intelligence Service (NEW)

No legacy code. Build from scratch per `docs/services/intelligence.md`.

### S8: RAG / Chat Service (NEW)

No legacy code. Build from scratch per `docs/services/rag-chat.md`.

### S9: API Gateway (NEW)

No legacy code. Build from scratch per `docs/services/api-gateway.md`.

---

## Avro Schema Migration

| Legacy schema | Worldview path | Action |
|---------------|---------------|--------|
| `scripts/schemas/market.dataset.fetched.avsc` | `infra/kafka/schemas/market.dataset.fetched.avsc` | **Copy & review** — namespace `market.events`, fields: topic, bucket, key, symbol, exchange, from_date, to_date, row_count, schema_version. |
| `scripts/schemas/instrument.created.avsc` | `infra/kafka/schemas/instrument.created.avsc` | **Copy as-is** — namespace `com.platform.market_data.events`. |
| `scripts/schemas/tenant.created.avsc` | `infra/kafka/schemas/tenant.created.avsc` | **Copy as-is** — namespace `portfolio`. |
| `scripts/schemas/user.created.avsc` | `infra/kafka/schemas/user.created.avsc` | **Copy as-is** — namespace `portfolio`. |
| `scripts/schemas/transaction.recorded.avsc` | `infra/kafka/schemas/transaction.recorded.avsc` | **Copy as-is** — namespace `portfolio.events`. |
| *(new)* | `infra/kafka/schemas/content.article.ingested.avsc` | **Write fresh** |
| *(new)* | `infra/kafka/schemas/intelligence.entity.extracted.avsc` | **Write fresh** |
| *(new)* | `infra/kafka/schemas/intelligence.sentiment.scored.avsc` | **Write fresh** |

---

## Docker Compose Migration

The legacy `deploy/compose/docker-compose.yml` is a solid foundation. Key changes:

1. **Keep**: Service definitions for postgres, kafka, schema-registry, minio, valkey, kafka-ui, pgweb
2. **Update**: Add `ollama` service for local LLM
3. **Update**: Add init jobs for new DBs (content_db, intelligence_db, rag_db, gateway_db)
4. **Update**: Add new topic creation for content/intelligence/chat topics
5. **Remove**: Legacy service containers (will be replaced with new service definitions)
6. **Add**: Per-service `Dockerfile` in each `services/<name>/` directory

---

## What NOT to Reuse

| Legacy item | Reason |
|-------------|--------|
| `Poetry` lock files | Switching to Hatch |
| `pyproject.toml` (per service) | Rewrite with hatchling backend |
| Legacy Alembic migration files | Regenerate from clean state |
| `create_tables.py` (root) | Ad-hoc script, replaced by proper Alembic migrations |
| `fix_schema.sql` (root) | One-off patch, not needed |
| Analysis markdown files (root) | Thesis documentation, not code |
| `scripts/register_schemas.py` | Rewrite with new schema paths |

---

## Migration Order

Execute in this order to minimise broken dependencies:

1. **common** — no deps
2. **contracts** — depends on common (optional)
3. **observability** — no internal deps
4. **storage** — no internal deps
5. **messaging** — depends on contracts, observability
6. **Portfolio service** — depends on all libs
7. **Market Ingestion service** — depends on messaging, storage, contracts
8. **Market Data service** — depends on messaging, storage, contracts
9. **Content service** — new, depends on messaging, storage
10. **Intelligence service** — new, depends on messaging, storage
11. **RAG/Chat service** — new, depends on messaging
12. **API Gateway** — new, depends on common
