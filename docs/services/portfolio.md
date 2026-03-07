# Portfolio Service

> **Owner**: Portfolio domain · **Database**: `portfolio_db` · **Port**: 8000
> **Status**: Existing (migrated from `platform_repo/apps/backend-portfolio`)

---

## Mission & Boundaries

**Owns**: Tenant management, user management, portfolio CRUD, transaction recording,
holding calculation, instrument reference synchronization.

**Never does**: Price lookups (delegates to Market Data), news/content operations,
direct market data ingestion, cross-service DB queries.

---

## API Surface

### Endpoints

| Method | Path | Description | Cache Tier |
|--------|------|-------------|------------|
| GET | `/healthz` | Liveness probe | — |
| GET | `/readyz` | Readiness probe (DB check) | — |
| GET | `/metrics` | Prometheus metrics | — |
| POST | `/api/v1/tenants` | Create tenant | private |
| GET | `/api/v1/tenants/{id}` | Get tenant | private |
| POST | `/api/v1/users` | Create user | private |
| GET | `/api/v1/users/{id}` | Get user | private |
| POST | `/api/v1/portfolios` | Create portfolio | private |
| GET | `/api/v1/portfolios` | List portfolios (by owner) | private |
| GET | `/api/v1/portfolios/{id}` | Get portfolio | private |
| PUT | `/api/v1/portfolios/{id}` | Rename portfolio | private |
| DELETE | `/api/v1/portfolios/{id}` | Archive portfolio | private |
| POST | `/api/v1/transactions` | Record transaction | private |
| GET | `/api/v1/transactions` | List transactions (by portfolio) | private |
| GET | `/api/v1/holdings/{portfolio_id}` | Get holdings for portfolio | private |
| GET | `/api/v1/instruments` | List local instrument refs | private |

### Request/Response Models

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
```

---

## Kafka Topics

### Produced

| Topic | Event Types | Key | Schema |
|-------|-------------|-----|--------|
| `portfolio.events.v1` | `tenant.created`, `user.created`, `portfolio.created`, `portfolio.renamed`, `portfolio.archived`, `transaction.recorded`, `holding.changed`, `instrument_ref.created` | `aggregate_id` | Per-event `.avsc` files |

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
    synced_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE (symbol, exchange)
);

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
```

---

## Internal Modules

```
services/portfolio/src/portfolio/
├── api/
│   ├── main.py              # FastAPI app factory, middleware, health endpoints
│   ├── dependencies.py      # DI (UoW, repos, use cases)
│   ├── schemas.py           # Pydantic request/response models
│   ├── exception_handlers.py
│   └── routes/
│       ├── tenant.py
│       ├── user.py
│       ├── portfolio.py
│       ├── transaction.py
│       ├── holding.py
│       └── instrument.py
├── application/
│   ├── ports/
│   │   ├── repositories.py  # Abstract repos (TenantRepo, PortfolioRepo, etc.)
│   │   └── unit_of_work.py  # Abstract UoW
│   └── use_cases/
│       ├── create_portfolio.py
│       ├── record_transaction.py
│       ├── portfolio_ops.py  # rename, archive
│       ├── read_models.py    # query use cases
│       ├── tenant.py
│       ├── user.py
│       └── instrument.py    # sync from Kafka
├── domain/
│   ├── entities/
│   │   ├── tenant.py
│   │   ├── user.py
│   │   ├── portfolio.py
│   │   ├── transaction.py
│   │   ├── holding.py
│   │   └── instrument.py
│   ├── enums.py
│   ├── events.py            # domain events (TenantCreated, TransactionRecorded, etc.)
│   ├── errors.py
│   └── value_objects.py
├── infrastructure/
│   ├── config/settings.py   # Pydantic-settings
│   ├── db/
│   │   ├── models/          # SQLAlchemy ORM models
│   │   ├── repositories/    # Concrete repo implementations
│   │   ├── session.py       # Async session factory
│   │   └── unit_of_work.py  # Concrete UoW with outbox dispatch hook
│   └── messaging/
│       ├── dispatcher.py    # Outbox dispatcher (BaseOutboxDispatcher)
│       └── kafka/
│           ├── mapper.py
│           ├── outbox_mapper.py
│           ├── serialization.py
│           ├── topics.py
│           └── schemas/     # .avsc files
├── consumers/
│   └── instrument_consumer.py  # Kafka consumer for instrument sync
└── messaging/
    └── dispatcher_main.py   # Standalone dispatcher entry point
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

---

## Observability

- **Metrics**: request count/latency by endpoint, transaction count by type, holding count
- **Log fields**: `service=portfolio`, `tenant_id`, `correlation_id`, `portfolio_id`
- **Traces**: FastAPI + SQLAlchemy auto-instrumented via OpenTelemetry

---

## Testing Plan

| Type | What to Test | Command |
|------|-------------|---------|
| Unit | Domain entities (holding calculation, transaction validation) | `make test` |
| Unit | Use cases (mock repos) | `make test` |
| Integration | API endpoints → DB round-trip | `make test-integration` |
| Contract | Avro schema compatibility | `scripts/gen-contracts.sh` |

---

## Local Run

```bash
cd services/portfolio
cp configs/dev.local.env.example .env
make run       # uvicorn with hot-reload on port 8000
make test      # pytest
make lint      # ruff + mypy
make migrate   # alembic upgrade head
```
