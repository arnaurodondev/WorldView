# Portfolio Service

> **Owner**: Portfolio domain · **Database**: `portfolio_db` · **Port**: 8001
> **Status**: Existing (migrated from `platform_repo/apps/backend-portfolio`)

---

## Mission & Boundaries

**Owns**: Tenant management, user management, portfolio CRUD, transaction recording,
holding calculation, instrument reference synchronization, watchlist CRUD, alert preference
management, Valkey reverse-index cache for watchlist entity tracking.

**Never does**: Price lookups (delegates to Market Data), news/content operations,
direct market data ingestion, cross-service DB queries.

---

## API Surface

### Endpoints

| Method | Path | Description | Cache Tier |
|--------|------|-------------|------------|
| GET | `/healthz` | Liveness probe | — |
| GET | `/readyz` | Readiness probe (DB check) | — |
| GET | `/metrics` | Prometheus metrics — requires `X-Internal-Token` header (M-004) | — |
| POST | `/api/v1/tenants` | Create tenant | private |
| GET | `/api/v1/tenants/{id}` | Get tenant | private |
| POST | `/api/v1/users` | Create user | private |
| GET | `/api/v1/users/{id}` | Get user | private |
| POST | `/api/v1/portfolios` | Create portfolio | private |
| GET | `/api/v1/portfolios` | List portfolios (by owner) — paginated (`limit`, `offset`) | private |
| GET | `/api/v1/portfolios/{id}` | Get portfolio | private |
| PUT | `/api/v1/portfolios/{id}` | Rename portfolio | private |
| DELETE | `/api/v1/portfolios/{id}` | Archive portfolio | private |
| POST | `/api/v1/transactions` | Record transaction | private |
| GET | `/api/v1/transactions` | List transactions (by portfolio) — paginated (`limit`, `offset`) | private |
| GET | `/api/v1/holdings/{portfolio_id}` | Get holdings for portfolio | private |
| GET | `/api/v1/instruments` | List local instrument refs — paginated (`limit`, `offset`) | private |
| GET | `/api/v1/instruments/{id}` | Get instrument by ID | private |
| POST | `/api/v1/watchlists` | Create watchlist | private |
| GET | `/api/v1/watchlists` | List watchlists (by owner) | private |
| GET | `/api/v1/watchlists/{id}` | Get watchlist | private |
| DELETE | `/api/v1/watchlists/{id}` | Soft-delete watchlist | private |
| POST | `/api/v1/watchlists/{id}/members` | Add member to watchlist | private |
| DELETE | `/api/v1/watchlists/{id}/members/{entity_id}` | Remove member from watchlist | private |
| GET | `/api/v1/alert-preferences` | Get alert preferences + suppressions | private |
| PUT | `/api/v1/alert-preferences/{alert_type}` | Upsert alert preference | private |
| POST | `/api/v1/alert-preferences/suppressions` | Add entity suppression | private |
| DELETE | `/api/v1/alert-preferences/suppressions/{entity_id}` | Remove entity suppression | private |

### Request/Response Models

Paginated list endpoints (`GET /portfolios`, `GET /instruments`, `GET /transactions`) accept:

| Query param | Default | Max | Description |
|-------------|---------|-----|-------------|
| `limit` | 100 | 500 | Max items per page |
| `offset` | 0 | — | Skip N items |

All three return a `PaginatedResponse<T>`:
```json
{ "items": [...], "total": 42, "limit": 100, "offset": 0 }
```

---

```python
# CreatePortfolio
{ "name": str, "owner_user_id": UUID, "currency": str = "USD" }

# RecordTransaction
{
    "portfolio_id": UUID,
    "instrument_id": UUID,
    "transaction_type": "BUY" | "SELL" | "DIVIDEND",
    "direction": "INFLOW" | "OUTFLOW",
    "quantity": Decimal,
    "price": Decimal,
    "fees": Decimal = 0,
    "currency": str,
    "executed_at": datetime,
    "external_ref": str | None
}

# Holding (response)
{
    "instrument_id": UUID,
    "symbol": str,
    "quantity": Decimal,
    "average_cost": Decimal,
    "currency": str
}

# InstrumentResponse — entity_id links to KG canonical entity (nullable; no cross-service FK)
{
    "id": UUID,
    "symbol": str,
    "exchange": str,
    "name": str | None,
    "currency": str | None,
    "asset_class": str | None,
    "entity_id": UUID | None   # populated when instrument is linked to a KG entity
}

# WatchlistCreateRequest
{ "name": str }

# WatchlistResponse
{
    "id": UUID,
    "tenant_id": UUID,
    "user_id": UUID,
    "name": str,
    "status": "active" | "deleted",
    "created_at": datetime
}

# WatchlistMemberCreateRequest
{ "entity_id": UUID, "entity_type": str = "company" }

# WatchlistMemberResponse
{
    "id": UUID,
    "watchlist_id": UUID,
    "entity_id": UUID,     # no cross-service FK — plain UUID (R7)
    "entity_type": str,
    "added_at": datetime
}

# AlertPreferencesListResponse — defaults enabled=True for missing rows
{
    "preferences": [{"alert_type": str, "enabled": bool, "updated_at": datetime}, ...],
    "suppressions": [{"entity_id": UUID, "suppressed_at": datetime}, ...]
}

# AlertPreferenceUpdateRequest
{ "enabled": bool }

# EntitySuppressionCreateRequest
{ "entity_id": UUID }
```

#### Watchlist error codes

| Error | HTTP |
|-------|------|
| `WATCHLIST_NOT_FOUND` | 404 |
| `WATCHLIST_ALREADY_EXISTS` | 409 |
| `WATCHLIST_MEMBER_NOT_FOUND` | 404 |
| `WATCHLIST_MEMBER_ALREADY_EXISTS` | 409 |

#### Alert preference error codes

| Error | HTTP |
|-------|------|
| `VALIDATION_ERROR` (invalid alert_type) | 422 |
| `ALERT_PREFERENCE_NOT_FOUND` (suppression missing) | 404 |

---

## Kafka Topics

### Produced

| Topic | Event Types | Key | Schema |
|-------|-------------|-----|--------|
| `portfolio.events.v1` | `tenant.created`, `user.created`, `portfolio.created`, `portfolio.renamed`, `portfolio.archived`, `transaction.recorded`, `holding.changed`, `instrument_ref.created`, `watchlist.created`, `watchlist.deleted` | `aggregate_id` | Per-event `.avsc` files |
| `portfolio.watchlist.updated.v1` | `watchlist.item_added`, `watchlist.item_removed`, `watchlist.renamed` | `aggregate_id` | `watchlist.item_added.avsc`, `watchlist.item_removed.avsc` |

### Consumed

| Topic | Consumer Group | Event Type | Idempotency Key |
|-------|---------------|------------|-----------------|
| `market.instrument.created` | `portfolio-instrument-sync` | `InstrumentCreated` | `event_id` via `idempotency` table |
| `market.instrument.updated` | `portfolio-instrument-sync` | `InstrumentUpdated` | `event_id` via `idempotency` table |

---

## Database Schema

```sql
-- portfolio_db

CREATE TABLE tenants (
    id          UUID PRIMARY KEY,  -- UUIDv7
    name        TEXT NOT NULL,
    status      VARCHAR(20) DEFAULT 'active',
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE users (
    id          UUID PRIMARY KEY,
    tenant_id   UUID NOT NULL REFERENCES tenants(id),
    email       TEXT NOT NULL,
    status      VARCHAR(20) DEFAULT 'active',
    created_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE (tenant_id, email)
);

CREATE TABLE portfolios (
    id          UUID PRIMARY KEY,
    tenant_id   UUID NOT NULL REFERENCES tenants(id),
    owner_id    UUID NOT NULL REFERENCES users(id),
    name        TEXT NOT NULL,
    currency    VARCHAR(3) DEFAULT 'USD',
    status      VARCHAR(20) DEFAULT 'active',
    created_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE (owner_id, name)
);

CREATE TABLE transactions (
    id                UUID PRIMARY KEY,
    tenant_id         UUID NOT NULL REFERENCES tenants(id),
    portfolio_id      UUID NOT NULL REFERENCES portfolios(id),
    instrument_id     UUID NOT NULL,
    transaction_type  VARCHAR(20) NOT NULL,
    direction         VARCHAR(10) NOT NULL,
    quantity          NUMERIC(18,8) NOT NULL,
    price             NUMERIC(18,8) NOT NULL,
    fees              NUMERIC(18,8) DEFAULT 0,
    currency          VARCHAR(3) NOT NULL,
    executed_at       TIMESTAMPTZ NOT NULL,
    external_ref      TEXT,
    created_at        TIMESTAMPTZ DEFAULT now(),
    UNIQUE (portfolio_id, external_ref)  -- dedup
);

CREATE TABLE holdings (
    id              UUID PRIMARY KEY,
    portfolio_id    UUID NOT NULL REFERENCES portfolios(id),
    instrument_id   UUID NOT NULL,
    quantity        NUMERIC(18,8) NOT NULL DEFAULT 0,
    average_cost    NUMERIC(18,8) NOT NULL DEFAULT 0,
    currency        VARCHAR(3) NOT NULL,
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (portfolio_id, instrument_id)
);

CREATE TABLE instruments (
    id          UUID PRIMARY KEY,
    symbol      VARCHAR(20) NOT NULL,
    exchange    VARCHAR(10) NOT NULL,
    name        TEXT,
    currency    VARCHAR(3),
    asset_class VARCHAR(20),
    entity_id   UUID,           -- KG canonical entity; nullable, no cross-service FK (R7)
    synced_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE (symbol, exchange)
);
-- Partial index: CREATE INDEX ix_instruments_entity_id ON instruments (entity_id) WHERE entity_id IS NOT NULL;

CREATE TABLE outbox_events (
    id              UUID PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    event_type      VARCHAR(100) NOT NULL,
    payload         JSONB NOT NULL,
    status          VARCHAR(20) DEFAULT 'pending',
    created_at      TIMESTAMPTZ DEFAULT now(),
    published_at    TIMESTAMPTZ,
    lease_owner     TEXT,
    lease_expires   TIMESTAMPTZ,
    attempt_count   INTEGER DEFAULT 0,
    max_attempts    INTEGER DEFAULT 10
);

CREATE TABLE idempotency (
    event_id    UUID PRIMARY KEY,
    processed_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE watchlists (
    id          UUID PRIMARY KEY,  -- UUIDv7
    tenant_id   UUID NOT NULL,
    user_id     UUID NOT NULL,
    name        TEXT NOT NULL,
    status      VARCHAR(20) DEFAULT 'active',
    created_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, name)  -- name: uq_watchlists_user_name
);
-- Indexes: ix_watchlists_user_id, ix_watchlists_tenant_id

CREATE TABLE watchlist_members (
    id          UUID PRIMARY KEY,
    watchlist_id UUID NOT NULL REFERENCES watchlists(id),
    entity_id   UUID NOT NULL,  -- KG entity; no cross-service FK (R7)
    entity_type VARCHAR(30) NOT NULL DEFAULT 'company',
    added_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE (watchlist_id, entity_id)  -- name: uq_watchlist_members_watchlist_entity
);
-- Index: ix_watchlist_members_entity_id

CREATE TABLE alert_preferences (
    id          UUID PRIMARY KEY,  -- UUIDv7
    tenant_id   UUID NOT NULL,
    user_id     UUID NOT NULL,
    alert_type  VARCHAR(30) NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT true,
    updated_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, alert_type)  -- name: uq_alert_preferences_user_type
);
-- Index: ix_alert_preferences_user_id

CREATE TABLE entity_suppressions (
    id            UUID PRIMARY KEY,  -- UUIDv7
    tenant_id     UUID NOT NULL,
    user_id       UUID NOT NULL,
    entity_id     UUID NOT NULL,
    suppressed_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, entity_id)  -- name: uq_entity_suppressions_user_entity
);
-- Indexes: ix_entity_suppressions_user_id, ix_entity_suppressions_entity_id
```

---

## Internal Modules

```
services/portfolio/src/portfolio/
├── app.py                   # FastAPI app factory, lifespan, middleware, health endpoints
├── config.py                # Pydantic-settings
├── api/
│   ├── dependencies.py      # DI (UoW dependency)
│   ├── error_mapping.py     # DomainError → HTTP status code map
│   ├── exception_handlers.py
│   ├── schemas.py           # Pydantic request/response models
│   └── routes/
│       ├── tenant.py
│       ├── user.py
│       ├── portfolio.py
│       ├── transaction.py
│       ├── holding.py
│       └── instrument.py
├── application/
│   ├── ports/
│   │   ├── repositories.py  # Abstract repos (8 ABCs + OutboxRecord)
│   │   └── unit_of_work.py  # Abstract UoW
│   └── use_cases/
│       ├── create_portfolio.py
│       ├── record_transaction.py
│       ├── portfolio_ops.py  # rename, archive, get, list
│       ├── read_models.py    # GetHoldings, ListTransactions
│       ├── tenant.py         # CreateTenant, GetTenant
│       ├── user.py           # CreateUser, GetUser
│       └── instrument.py     # GetInstrument, ListInstruments
├── domain/
│   ├── entities/
│   │   ├── tenant.py
│   │   ├── user.py
│   │   ├── portfolio.py
│   │   ├── transaction.py
│   │   ├── holding.py        # apply_delta() for weighted-avg cost
│   │   └── instrument.py     # InstrumentRef (read-only local ref)
│   ├── enums.py              # 7 StrEnums (uppercase values)
│   ├── events.py             # DomainEvent ABC + 10 concrete events
│   ├── errors.py             # 15+ DomainError subclasses
│   └── value_objects.py      # Money, InstrumentKey, Quantity
├── infrastructure/
│   └── db/
│       ├── models/           # SQLAlchemy 2.0 ORM models (8 tables)
│       ├── repositories/     # 8 SqlAlchemy*Repository implementations
│       ├── session.py        # create_session_factory(url)
│       └── unit_of_work.py   # SqlAlchemyUnitOfWork with on_commit hook
├── consumers/
│   └── instrument_consumer.py  # InstrumentEventConsumer(BaseKafkaConsumer)
└── messaging/
    ├── dispatcher.py         # OutboxDispatcher(BaseOutboxDispatcher)
    ├── dispatcher_main.py    # Standalone dispatcher entry point
    ├── mapper.py             # Domain events → Avro dicts
    ├── outbox_mapper.py      # OutboxRecord → KafkaMessage
    ├── serialization.py      # Avro schema loading
    └── topics.py             # EVENT_TOPIC_MAP
```

---

## Core Workflows

### Record Transaction → Holding Update

```mermaid
sequenceDiagram
    participant C as Client
    participant API as Portfolio API
    participant UC as RecordTransactionUseCase
    participant UoW as Unit of Work
    participant DB as portfolio_db
    participant OBX as Outbox

    C->>API: POST /api/v1/transactions
    API->>UC: execute(command)
    UC->>UoW: begin transaction
    UC->>DB: INSERT transaction
    UC->>DB: UPSERT holding (recalculate qty + avg_cost)
    UC->>OBX: write TransactionRecorded event
    UC->>OBX: write HoldingChanged event
    UC->>UoW: commit (single transaction)
    API-->>C: 201 Created
```

---

## Docker

The service ships as a multi-stage Docker image built from `services/portfolio/Dockerfile`.
The image is registered in `infra/compose/docker-compose.yml` under the `infra` profile.

```bash
# Start portfolio + dependencies (Postgres, Kafka, Valkey)
docker compose -f infra/compose/docker-compose.yml --profile infra up -d

# One-time migration (runs alembic upgrade head then exits)
docker compose -f infra/compose/docker-compose.yml --profile infra run --rm portfolio-migrate

# Tail logs
docker compose -f infra/compose/docker-compose.yml logs -f portfolio
```

The service is exposed on host port **8001** (container port 8000).

---

## Background Jobs

| Process | Entry Point | Purpose |
|---------|-------------|---------|
| Outbox Dispatcher | `portfolio.messaging.dispatcher_main` | Publishes outbox events to Kafka |
| Instrument Consumer | `portfolio.consumers.instrument_consumer` | Syncs instruments from Market Data |

---

## Error Handling

- **Retryable**: DB connection errors, Kafka publish failures → exponential backoff
- **Fatal**: schema validation errors, duplicate `external_ref` → 409 Conflict response
- **DLQ**: consumer writes to `portfolio.events.v1.dlq` after max retries

---

## Caching Strategy

Portfolio data is **private** (tenant-scoped) — no gateway caching.
Service-level caching is minimal (instrument lookups cached in-memory for consumer).

### Watchlist Reverse-Index Cache (Valkey)

The service maintains a Valkey reverse-index mapping `entity_id → set of user_ids` to support
the Intelligence Layer alerting fanout (S10 consumes `portfolio.watchlist.updated.v1` events
and queries this index if needed).

| Key taxonomy | `pf:v1:watchlist:entity:{entity_id}` |
|---|---|
| Data structure | Redis Set (`SADD` / `SMEMBERS`) |
| TTL | Configurable via `PORTFOLIO_WATCHLIST_CACHE_TTL_SECONDS` (default 300 s) |
| Invalidation trigger | Every `add_member` and `remove_member` operation calls `invalidate_entity(entity_id)` (DEL key) |
| Rebuild | `set_user_ids(entity_id, user_ids, ttl)` atomically replaces the set (DEL + SADD + EXPIRE) |
| Miss handling | `get_user_ids` returns `[]` on a cache miss; callers should fall back to DB query |

> **Common pitfall**: The reverse-index cache may be stale briefly after a member mutation —
> always treat it as eventually consistent and never make security decisions based solely on
> its contents.

---

## Observability

- **Metrics**: request count/latency by endpoint, transaction count by type, holding count
- **Log fields**: `service=portfolio`, `tenant_id`, `correlation_id`, `portfolio_id`
- **Traces**: FastAPI + SQLAlchemy auto-instrumented via OpenTelemetry

---

## Testing Plan

| Type | Coverage | Command |
|------|----------|---------|
| Unit | Domain entities, value objects, use cases (FakeUoW), error hierarchy | `python -m pytest tests/unit/ -v` |
| Contract | 8 Avro schemas validated against generated event dicts via `fastavro` | `python -m pytest tests/contract/ -v` |
| Integration | All 16 API endpoints → Postgres round-trip (testcontainers) | `python -m pytest tests/integration/ -v` |
| E2E | Full BUY/SELL flow, outbox assertions, idempotency | `python -m pytest tests/e2e/ -v -m e2e` |

**Test counts (as of wave-02 completion)**: 300+ tests passing (unit + contract + integration + e2e).
New in wave-02: 11 watchlist API integration tests, 2 cache integration tests, 6 alert preference integration tests,
4 cache unit tests, 6 alert preference unit tests.

---

## Local Run

```bash
# Install deps (from repo root)
uv pip install -e libs/common -e libs/contracts -e libs/messaging \
               -e libs/observability -e libs/storage \
               -e services/portfolio

cd services/portfolio
make run              # uvicorn --factory on port 8001 with hot-reload
make test             # unit tests only
make test-integration # integration tests (requires Docker)
make lint             # ruff check + mypy strict
make migrate          # alembic upgrade head
make migrate-new MSG="add_column_foo"  # generate new migration
```

**Environment variables** (set via `.env` or shell):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | (required) | `postgresql+asyncpg://...` |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka broker(s) |
| `KAFKA_SCHEMA_REGISTRY_URL` | `http://localhost:8081` | Schema registry |
| `VALKEY_URL` | `redis://localhost:6379` | Valkey/Redis URL |
| `PORTFOLIO_WATCHLIST_CACHE_TTL_SECONDS` | `300` | TTL (seconds) for watchlist reverse-index cache entries |
| `SERVICE_NAME` | `portfolio` | Used in logs and traces |
| `OTLP_ENDPOINT` | (optional) | OpenTelemetry collector endpoint |
| `LOG_LEVEL` | `info` | structlog level |

---

## Common Pitfalls

- **Alert preferences default to `enabled=True` when no row exists** — do not treat a missing row
  as disabled. `GetAlertPreferencesUseCase` synthesizes defaults for all `AlertType` values not
  stored in the DB; callers should never infer "disabled" from absence of a row.

- **Watchlist reverse-index cache may be stale briefly after member mutation** — always treat it
  as eventually consistent. `add_member` and `remove_member` call `invalidate_entity` (DEL), not
  a synchronous rebuild. If you read the cache immediately after a write, a miss (`[]`) is expected.

- **`WatchlistCacheDep` requires `app.state.valkey_client`** — in tests, override
  `get_watchlist_cache` to return `NoOpWatchlistCache()` or a `fakeredis`-backed
  `ValkeyWatchlistCache`. Forgetting this causes `AttributeError` at request time.

- **Watchlist soft-delete does not prevent GET** — `DeleteWatchlistUseCase` saves the watchlist
  with `status=deleted` but does not remove it from the DB. `GetWatchlistUseCase` will still
  return it. Consumers must check `status` if they need to filter deleted watchlists.


---

## Operational Recovery

### Holdings drift from transaction-replay (BP-264)

Before PLAN-0046, `RecordTransactionUseCase` mutated `holdings.quantity` via
`Holding.apply_delta` on every transaction. Because the SnapTrade adapter's
dual-path activity feed (legacy → per-account fallback) could return the same
trade twice with different IDs, holdings inflated by 8-10x over time.

**Fix landed in PLAN-0046 Wave 1:**

- `RecordTransactionUseCase` no longer touches the `holdings` table; transactions
  are now history-only.
- `UpsertHoldingsFromSnapshotUseCase` overwrites the table after every brokerage
  sync from the broker's authoritative position snapshot
  (`SnapTradeClient.get_account_positions`).
- The `HoldingChanged` event is now emitted by the snapshot use case, not by
  `RecordTransactionUseCase`.

**To recover affected portfolios** (one-time per environment):

```bash
# 1) Dry-run — print affected portfolios + duplicate transaction groups.
cd services/portfolio
python -m portfolio.scripts.repair_holdings_after_replay_drift --dry-run

# 2) Live run — zero out holdings on portfolios that have a brokerage
#    connection. The next BrokerageTransactionSyncWorker cycle will repopulate
#    them from the broker's snapshot.
python -m portfolio.scripts.repair_holdings_after_replay_drift

# 3) Trigger the sync worker (or wait for the 4-hour cycle).
#    See ``trigger_brokerage_sync.py`` for the on-demand path.
```

The script is idempotent: re-running on already-clean state is a no-op apart
from one extra sync round-trip. Duplicate-transaction detection is read-only
and always safe.
