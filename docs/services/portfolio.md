# Portfolio Service (S1)

> **Owner**: Portfolio domain · **Database**: `portfolio_db` · **Port**: 8001
> **Status**: Mature — brokerage sync (SnapTrade), FIFO lot analytics, and concentration metrics complete

---

## Mission

S1 is the source of truth for all user-owned financial data: tenants, users, portfolios,
transactions, holdings, watchlists, alert preferences, and brokerage connections. It also
hosts the in-app feedback/NPS/roadmap backend (PLAN-0052). It exposes both public API routes
(proxied through S9) and internal routes (consumed directly by other backend services).

**Owns**: Tenant/user management, portfolio CRUD, transaction recording, holding calculation
(FIFO), instrument reference sync, watchlist management, alert preferences, brokerage
connections (SnapTrade), feedback/NPS/roadmap.

**Never does**: Price lookups (delegates to S3), news/content operations, direct market data
ingestion, cross-service DB queries.

---

## Architecture

### Auth Model (PRD-0025)

All requests to S1 are validated by `InternalJWTMiddleware`, which fetches S9's RS256 public
key from `GET {API_GATEWAY_URL}/internal/jwks` at startup (3 retries, 3 s sleep). The
middleware sets `request.state.tenant_id`, `request.state.user_id`, and `request.state.role`
from the verified JWT claims.

- `POST /internal/v1/users/provision` additionally requires `role=system` in the JWT.
- Health/metrics paths (`/healthz`, `/readyz`, `/metrics`) bypass middleware.
- **`PORTFOLIO_INTERNAL_SERVICE_TOKEN` is REMOVED** — never reference it in new code.

### Process Topology

| Process | Entry Point | Purpose |
|---------|------------|---------|
| API server | `portfolio.app` (uvicorn) | FastAPI HTTP server (port 8001) |
| Outbox dispatcher | `portfolio.infrastructure.messaging.dispatcher_main` | Publishes outbox events to Kafka |
| Instrument consumer | `portfolio.infrastructure.messaging.consumers.instrument_consumer_main` | Syncs instruments from S3/S2 |
| Brokerage sync worker | `portfolio.workers.brokerage_sync_worker` | 4-hour SnapTrade sync cycle |
| Portfolio snapshot worker | `portfolio.workers.portfolio_snapshot_worker` | Daily 21:30 UTC snapshot writer (value history) |

---

## API Endpoints

### Public Endpoints (proxied via S9)

All require `X-Internal-JWT` (RS256, issued by S9 per request).

#### Portfolio

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/portfolios` | Create portfolio |
| GET | `/api/v1/portfolios` | List portfolios (by owner) — paginated (`limit`, `offset`) |
| GET | `/api/v1/portfolios/{id}` | Get portfolio |
| PUT | `/api/v1/portfolios/{id}` | Rename portfolio |
| DELETE | `/api/v1/portfolios/{id}` | Archive portfolio |
| GET | `/api/v1/portfolios/{id}/realized-pnl` | Realised P&L (FIFO) over `[from, to]` date window |
| GET | `/api/v1/portfolios/{id}/value-history` | Equity-curve daily snapshots (`from`, `to`, `days`, `granularity=1d|1w|1m`); response includes `metadata.last_snapshot_at` and `metadata.next_scheduled_run_utc` |
| GET | `/api/v1/portfolios/{id}/exposure` | Invested / cash / leverage breakdown; includes `prices_stale` and `prices_as_of` fields |
| GET | `/api/v1/portfolios/{id}/holdings/{instrument_id}/lots` | FIFO open lots for a single holding — open-date, qty, cost-per-share, days-held, ST/LT classification, optional `unrealised_pnl` (PLAN-0088 E-2) |
| GET | `/api/v1/portfolios/{id}/concentration` | Herfindahl-Hirschman concentration metrics: HHI, diversified/moderate/concentrated/empty label, top-3 share, top-5 positions (PLAN-0088 E-3) |

#### Holdings, Transactions, Instruments

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/holdings/{portfolio_id}` | Get holdings for portfolio |
| POST | `/api/v1/transactions` | Record transaction |
| GET | `/api/v1/transactions` | List transactions — paginated |
| GET | `/api/v1/instruments` | List local instrument refs — paginated |
| GET | `/api/v1/instruments/{id}` | Get instrument by ID |

#### Watchlists

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/watchlists` | Create watchlist |
| GET | `/api/v1/watchlists` | List watchlists (by owner) |
| GET | `/api/v1/watchlists/{id}` | Get watchlist |
| DELETE | `/api/v1/watchlists/{id}` | Soft-delete watchlist |
| POST | `/api/v1/watchlists/{id}/members` | Add member to watchlist |
| DELETE | `/api/v1/watchlists/{id}/members/{entity_id}` | Remove member |

#### Alert Preferences

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/alert-preferences` | Get alert preferences + suppressions |
| PUT | `/api/v1/alert-preferences/{alert_type}` | Upsert alert preference |
| POST | `/api/v1/alert-preferences/suppressions` | Add entity suppression |
| DELETE | `/api/v1/alert-preferences/suppressions/{entity_id}` | Remove entity suppression |

#### Brokerage Connections (SnapTrade, PRD-0022)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/brokerage-connections` | Register SnapTrade user + create PENDING connection |
| GET | `/api/v1/brokerage-connections` | List connections (`?portfolio_id=` optional) |
| DELETE | `/api/v1/brokerage-connections/{id}` | Disconnect and revoke |
| GET | `/api/v1/brokerage-connections/{id}/callback` | OAuth callback — activates connection + auto-syncs |
| GET | `/api/v1/brokerage-connections/{id}/sync-errors` | List sync errors (`limit` 1-200) |
| GET | `/api/v1/brokerage-connections/{id}/balance` | Cash/buying-power balance (best-effort) |
| POST | `/api/v1/brokerage-connections/{id}/sync` | Trigger immediate background sync (202 Accepted) |

**Callback notes**: The callback endpoint supports both SnapTrade Connection Portal v3
(`authorizationId` + `userId` + `sessionId`) and v4 (`connection_id` param only). On
successful activation, a background task runs one sync cycle immediately so transactions
appear in the UI without waiting the 4-hour cycle.

#### Admin / Operator

| Method | Path | Description |
|--------|------|-------------|
| POST | `/admin/portfolios/{portfolio_id}/recompute-snapshot` | Recompute today's portfolio_value_snapshots row |

#### Tenant & User (internal-only — system JWT required)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/tenants` | Create tenant (requires `role=system`) |
| GET | `/api/v1/tenants/{id}` | Get tenant |
| POST | `/api/v1/users` | Create user |
| GET | `/api/v1/users/{id}` | Get user |

### Internal Endpoints (not proxied through S9)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/internal/v1/health` | None | Readiness check (used by S10) |
| GET | `/internal/v1/watchlists/by-entity/{entity_id}` | JWT | Resolve watchers for an entity |
| POST | `/internal/v1/watchlists/by-entities` | JWT | Batch resolve watchers (1-100 entity IDs) |
| GET | `/internal/v1/watchlists/{watchlist_id}/entities` | JWT | Entity IDs in watchlist |
| GET | `/internal/v1/users/{user_id}/portfolio/context` | JWT | Portfolio context for S8 RAG chat |
| GET | `/internal/v1/users/{user_id}/portfolio/pnl` | JWT | Per-holding overnight P&L (PLAN-0102 W2) |
| GET | `/internal/v1/users/{user_id}` | JWT | User profile (S10 email delivery) |
| POST | `/internal/v1/users/provision` | JWT `role=system` | Idempotent OIDC user provisioning |

#### Portfolio P&L Endpoint (PLAN-0102 W2 T-W2-01)

`GET /internal/v1/users/{user_id}/portfolio/pnl` returns per-holding overnight P&L
(dollar + percent) plus portfolio-wide aggregates so rag-chat's morning brief can
render real performance lines like "AAPL +1.45% pre-mkt — +$280".

Auth: `X-Internal-JWT` — JWT user_id must match path user_id (same shape as
`/portfolio/context`). A `role=system` token whose `service_name` is on the
`_SERVICE_PNL_ALLOWED` allow-list (currently `rag-chat-brief-scheduler`) may
read any user's P&L for the brief pre-generation worker.

Implementation:
- Router: `portfolio.api.routes.internal_pnl.internal_pnl_router`.
- Use case: `portfolio.application.use_cases.get_portfolio_pnl.GetPortfolioPnLUseCase`
  joins holdings (read-replica) with current price + last close fetched in one
  batch call to S3 via the `RecentPricesClient` port.
- Adapter: `portfolio.infrastructure.market_data.recent_prices_client.HttpRecentPricesClient`
  hits `POST /internal/v1/price/batch?include_missing=true` on market-data and
  derives `last_close = price - price_change` per row.

Cache: 60 s Valkey, key `portfolio_pnl:v1:{user_id}`.

Response shape:
```json
{
  "user_id": "uuid",
  "as_of": "2026-05-29T07:00:00Z",
  "holdings": [
    {"symbol": "AAPL", "entity_id": "uuid", "instrument_id": "uuid",
     "qty": 100.0, "last_close_usd": 192.50, "current_price_usd": 195.30,
     "overnight_pnl_usd": 280.0, "overnight_pnl_pct": 0.01454}
  ],
  "total_overnight_pnl_usd": 530.0,
  "total_overnight_pnl_pct": 0.01325,
  "generated_at": "2026-05-29T07:00:00Z"
}
```

Holdings whose S3 price row is missing surface with `null` prices and `0.0` P&L
— a partial market-data outage degrades per-row, never failing the whole brief.

#### Provision Endpoint (ProvisionUserUseCase)

4-step idempotent logic per PRD-0025 §3.3:

1. `find_by_external_id(sub)` → return existing (no writes)
2. `find_by_email_without_external_id(email)` → link + ACCOUNT_LINKED audit
3. `find_by_email_with_conflicting_external_id(email, sub)` → 409 + PROVISION_CONFLICT_409 audit
4. Neither → create Tenant + User atomically + USER_CREATED audit

**Request body**: `{sub, email, username?}`
**Response**: `{user_id, tenant_id, email, created, linked}`

### Health & Observability

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/healthz` | None | Liveness probe |
| GET | `/readyz` | None | Readiness probe (DB check) |
| GET | `/metrics` | X-Internal-Token | Prometheus metrics |

---

## Request/Response Models

### Pagination

All paginated endpoints (`GET /portfolios`, `GET /instruments`, `GET /transactions`) accept
`limit` (default 100, max 500) and `offset` (default 0). Response shape:

```json
{ "items": [...], "total": 42, "limit": 100, "offset": 0 }
```

### Key Schemas

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
    "external_ref": str | None   # dedup key — UNIQUE per portfolio
}

# Holding (response)
{
    "instrument_id": UUID,
    "symbol": str,
    "quantity": Decimal,
    "average_cost": Decimal,
    "currency": str
}

# WatchlistMemberCreateRequest
{ "entity_id": UUID, "entity_type": str = "company" }

# AlertPreferenceUpdateRequest
{ "enabled": bool }
```

### Realised P&L Endpoint

`GET /api/v1/portfolios/{portfolio_id}/realized-pnl` — query params: `from` (ISO date,
default: first day of current UTC year), `to` (ISO date, default: today). Uses FIFO
lot-matching across the full transaction history for correct cost basis.

Response:
```json
{
  "total_realized": "250.00000000",
  "realized_long_term": "0.00000000",
  "realized_short_term": "250.00000000",
  "count": 1,
  "breakdown_by_instrument": [
    {"instrument_id": "...", "ticker": "AAPL", "name": "Apple Inc.", "realized": "250.00000000"}
  ],
  "currency": "USD",
  "from_date": "2026-01-01",
  "to_date": "2026-04-30"
}
```

---

## Kafka Topics

### Produced

| Topic | Event Types |
|-------|-------------|
| `portfolio.events.v1` | `tenant.created`, `user.created`, `portfolio.created`, `portfolio.renamed`, `portfolio.archived`, `transaction.recorded`, `holding.changed`, `instrument_ref.created`, `watchlist.created`, `watchlist.deleted` |
| `portfolio.watchlist.updated.v1` | `watchlist.item_added`, `watchlist.item_removed`, `watchlist.renamed` |

### Consumed

| Topic | Consumer Group | Event Type |
|-------|---------------|------------|
| `market.instrument.discovered.v1` | `portfolio-instrument-sync` | Seeds InstrumentRef with `name=None` (no fundamentals yet) |
| `market.instrument.created` | `portfolio-instrument-sync` | Full fundamentals available — populates ISIN/FIGI/LEI |
| `market.instrument.updated` | `portfolio-instrument-sync` | Updates local instrument cache |

---

## Database Schema (`portfolio_db`)

```sql
CREATE TABLE tenants (
    id UUID PRIMARY KEY,  -- UUIDv7
    name TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE users (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    email TEXT NOT NULL,
    external_id TEXT UNIQUE,  -- Zitadel OIDC sub (nullable)
    role VARCHAR(20) NOT NULL DEFAULT 'owner',  -- owner/admin/member
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (tenant_id, email)
);

CREATE TABLE portfolios (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    owner_id UUID NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    kind VARCHAR(20) DEFAULT 'user',  -- 'user' | 'root'
    currency VARCHAR(3) DEFAULT 'USD',
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (owner_id, name)
);

CREATE TABLE transactions (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    portfolio_id UUID NOT NULL REFERENCES portfolios(id),
    instrument_id UUID NOT NULL,
    transaction_type VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    quantity NUMERIC(18,8) NOT NULL,
    price NUMERIC(18,8) NOT NULL,
    fees NUMERIC(18,8) DEFAULT 0,
    currency VARCHAR(3) NOT NULL,
    executed_at TIMESTAMPTZ NOT NULL,
    external_ref TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (portfolio_id, external_ref)
);

CREATE TABLE holdings (
    id UUID PRIMARY KEY,
    portfolio_id UUID NOT NULL REFERENCES portfolios(id),
    instrument_id UUID NOT NULL,
    quantity NUMERIC(18,8) NOT NULL DEFAULT 0,
    average_cost NUMERIC(18,8) NOT NULL DEFAULT 0,
    currency VARCHAR(3) NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (portfolio_id, instrument_id)
);

CREATE TABLE instruments (
    id UUID PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    exchange VARCHAR(10) NOT NULL,
    name TEXT,
    currency VARCHAR(3),
    asset_class VARCHAR(20),
    entity_id UUID,   -- KG canonical entity; no cross-service FK (R7)
    synced_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (symbol, exchange)
);

CREATE TABLE brokerage_connections (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES users(id),
    portfolio_id UUID REFERENCES portfolios(id),
    brokerage_name VARCHAR(50) NOT NULL DEFAULT 'snaptrade',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending/active/error/disconnected
    snaptrade_user_id TEXT,
    snaptrade_user_secret TEXT,   -- AES-encrypted (Fernet); NEVER log
    last_synced_at TIMESTAMPTZ,
    last_sync_cursor TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE brokerage_sync_errors (
    id UUID PRIMARY KEY,
    connection_id UUID NOT NULL REFERENCES brokerage_connections(id),
    snaptrade_transaction_id TEXT,
    error_type VARCHAR(50) NOT NULL,
    error_detail TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE watchlists (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    name TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, name)
);

CREATE TABLE watchlist_members (
    id UUID PRIMARY KEY,
    watchlist_id UUID NOT NULL REFERENCES watchlists(id),
    entity_id UUID NOT NULL,   -- KG entity; no cross-service FK (R7)
    entity_type VARCHAR(30) NOT NULL DEFAULT 'company',
    added_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (watchlist_id, entity_id)
);

CREATE TABLE alert_preferences (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    alert_type VARCHAR(30) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, alert_type)
);

CREATE TABLE entity_suppressions (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    entity_id UUID NOT NULL,
    suppressed_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, entity_id)
);

CREATE TABLE auth_audit_log (
    id UUID PRIMARY KEY,
    user_id UUID,
    sub TEXT,
    event_type VARCHAR(50) NOT NULL,  -- USER_CREATED/ACCOUNT_LINKED/etc.
    detail JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE outbox_events (
    id UUID PRIMARY KEY,
    tenant_id UUID,
    event_type VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT now(),
    published_at TIMESTAMPTZ,
    lease_owner TEXT,
    lease_expires TIMESTAMPTZ,
    attempt_count INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 10
);

CREATE TABLE idempotency (
    event_id UUID PRIMARY KEY,
    processed_at TIMESTAMPTZ DEFAULT now()
);

-- Feedback tables (PLAN-0052 Wave D) —————————————————————————————————————————
CREATE TABLE feedback_submissions (
    id UUID PRIMARY KEY,  -- UUIDv7
    tenant_id UUID NOT NULL,
    user_id UUID,
    category VARCHAR(30) NOT NULL,  -- bug/feature/ux/design
    description TEXT,
    email TEXT,
    screenshot_url TEXT,
    console_logs TEXT,
    status VARCHAR(20) DEFAULT 'new',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE nps_scores (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 10),
    comment TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
    -- Index: ix_nps_scores_user_recent (user_id, created_at DESC)
);

CREATE TABLE feature_requests (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    category VARCHAR(30),
    status VARCHAR(20) DEFAULT 'open',
    vote_count INTEGER DEFAULT 0,
    is_public BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE feature_votes (
    feature_request_id UUID NOT NULL,
    user_id UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (feature_request_id, user_id)
);

CREATE TABLE micro_survey_responses (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    user_id UUID,
    survey_key VARCHAR(100) NOT NULL,
    score SMALLINT NOT NULL CHECK (score IN (0,1)),
    comment TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE beta_enrollments (
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    enrolled BOOLEAN NOT NULL DEFAULT false,
    programs JSONB DEFAULT '[]',
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id)
);
```

---

## Feedback Subsystem (PLAN-0052 Wave D)

The portfolio service hosts the in-app feedback/NPS/roadmap backend. The api-gateway proxies
`/v1/feedback/*` to these routes.

### PII Redaction

`portfolio.security.pii_redaction.redact()` scrubs these patterns from free-text fields
before they hit the database:

| Pattern | Replacement |
|---------|-------------|
| Bearer tokens | `Bearer [REDACTED:JWT]` |
| JWT-shaped strings (`eyJ...`) | `[REDACTED:JWT]` |
| API key assignments | `api_key=[REDACTED:API_KEY]` |
| Authorization headers | `<header>: [REDACTED:HEADER]` |
| Email addresses | `[REDACTED:EMAIL]` |
| 16-digit card numbers | `[REDACTED:CC]` |
| US SSN | `[REDACTED:SSN]` |

### Anonymous Tenant Routing

Anonymous (no-JWT) feedback submissions land under `PORTFOLIO_FEEDBACK_ANONYMOUS_TENANT_ID`
(default: nil UUID `00000000-...`). Admins read them via
`GET /api/v1/feedback/submissions/anonymous` (admin-only route).

---

## Watchlist Reverse-Index Cache (Valkey)

The service maintains a Valkey reverse-index `entity_id → set of user_ids` used by S10
alert fanout.

| Key | `pf:v1:watchlist:entity:{entity_id}` |
|-----|--------------------------------------|
| Structure | Redis Set |
| TTL | `PORTFOLIO_WATCHLIST_CACHE_TTL_SECONDS` (default 300 s) |
| Invalidation | Every `add_member`/`remove_member` calls DEL (not synchronous rebuild) |
| Miss handling | Returns `[]`; callers fall back to DB |

---

## Configuration

All env vars use prefix `PORTFOLIO_`.

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `PORTFOLIO_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/portfolio_db` | Yes | Write URL |
| `PORTFOLIO_DATABASE_URL_READ` | (falls back to write) | No | Read replica URL (R27) |
| `PORTFOLIO_DB_POOL_SIZE` | `10` | No | Write pool size |
| `PORTFOLIO_DB_MAX_OVERFLOW` | `20` | No | Write pool max overflow |
| `PORTFOLIO_DB_POOL_SIZE_READ` | `20` | No | Read pool size |
| `PORTFOLIO_DB_MAX_OVERFLOW_READ` | `30` | No | Read pool max overflow |
| `PORTFOLIO_KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | No | Kafka broker(s) |
| `PORTFOLIO_SCHEMA_REGISTRY_URL` | `http://localhost:8081` | No | Schema registry |
| `PORTFOLIO_KAFKA_SCHEMA_REGISTRY_BASIC_AUTH` | `""` | No | `user:pass` for schema registry auth |
| `PORTFOLIO_KAFKA_AUTO_REGISTER_SCHEMAS` | `true` | No | Auto-register Avro schemas |
| `PORTFOLIO_VALKEY_URL` | `redis://localhost:6379/0` | No | Valkey/Redis URL |
| `PORTFOLIO_WATCHLIST_CACHE_TTL_SECONDS` | `300` | No | Valkey watchlist reverse-index TTL |
| `PORTFOLIO_API_GATEWAY_URL` | `http://api-gateway:8000` | No | S9 URL for JWKS fetch at startup |
| `PORTFOLIO_INTERNAL_JWT_ISSUER` | `worldview-gateway` | No | Expected JWT issuer |
| `PORTFOLIO_INTERNAL_JWT_SKIP_VERIFICATION` | `false` | No | **Dev/test only** — skip RS256 verification. Rejected when `APP_ENV=production` |
| `PORTFOLIO_STORAGE_ENDPOINT` | `http://localhost:7480` | Yes | S3-compatible storage endpoint (MinIO) for feedback screenshots |
| `PORTFOLIO_STORAGE_ACCESS_KEY` | _(required)_ | Yes | S3 access key |
| `PORTFOLIO_STORAGE_SECRET_KEY` | _(required)_ | Yes | S3 secret key |
| `PORTFOLIO_SNAPTRADE_CLIENT_ID` | `""` | For brokerage | SnapTrade API client ID (also reads `SNAPTRADE_CLIENT_ID`) |
| `PORTFOLIO_SNAPTRADE_CONSUMER_KEY` | `""` | For brokerage | SnapTrade API consumer key |
| `PORTFOLIO_SNAPTRADE_REDIRECT_URI` | `http://localhost:3001/portfolio/brokerage/callback` | No | OAuth redirect URI |
| `PORTFOLIO_SNAPTRADE_SECRET_ENCRYPTION_KEY` | `""` | For brokerage | Fernet key for encrypting `snaptrade_user_secret` at rest. Empty = plaintext (dev only). |
| `PORTFOLIO_BROKERAGE_SYNC_CYCLE_SECONDS` | `14400` | No | 4-hour sync interval |
| `PORTFOLIO_BROKERAGE_SYNC_HISTORY_DAYS` | `730` | No | 2-year initial import window |
| `PORTFOLIO_MARKET_DATA_SERVICE_URL` | `http://market-data:8003` | No | S3 URL for instrument resolution during brokerage sync |
| `PORTFOLIO_FEEDBACK_S3_BUCKET` | `worldview-feedback-screenshots` | No | Feedback screenshot bucket |
| `PORTFOLIO_FEEDBACK_SCREENSHOT_TTL_DAYS` | `90` | No | Screenshot retention in S3 |
| `PORTFOLIO_FEEDBACK_CONSOLE_LOGS_TTL_DAYS` | `7` | No | Console log retention in S3 |
| `PORTFOLIO_FEEDBACK_ANONYMOUS_TENANT_ID` | `00000000-0000-0000-0000-000000000000` | No | Tenant for anonymous feedback (must be a valid UUID) |
| `PORTFOLIO_LOG_LEVEL` | `INFO` | No | structlog level |
| `PORTFOLIO_LOG_JSON` | `true` | No | JSON-structured logs |
| `PORTFOLIO_OTLP_ENDPOINT` | `""` | No | OpenTelemetry collector endpoint |

**Generate Fernet key** for `PORTFOLIO_SNAPTRADE_SECRET_ENCRYPTION_KEY`:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Note**: `PORTFOLIO_STORAGE_ACCESS_KEY` and `PORTFOLIO_STORAGE_SECRET_KEY` are required fields with no default. The service will fail to start without them. For local dev, set them to any non-empty string (MinIO will be used with its own credentials from docker-compose).

---

## External Dependencies

| Dependency | Purpose | Required |
|-----------|---------|----------|
| PostgreSQL | `portfolio_db` — all portfolio data | Yes |
| Kafka + Schema Registry | Event publishing (outbox pattern) | Yes |
| Valkey | Watchlist reverse-index cache | Yes |
| S9 API Gateway | JWKS endpoint for JWT verification | Yes (at startup) |
| SnapTrade API | Brokerage connections and transaction sync (SDK: `snaptrade-python-sdk>=11.0,<12`) | Optional |
| S3 Market Data (S3) | Instrument resolution during brokerage sync; live price quotes for exposure/concentration | Optional |
| S3-compatible storage (MinIO) | Screenshot uploads for feedback subsystem | Yes (startup fails without credentials) |

---

## How to Run Locally

### Option A — Full Docker Compose (Recommended)

```bash
# From repo root
make dev    # starts all services including portfolio on port 8001
make seed   # load sample data
```

### Option B — Run Standalone (no Zitadel needed)

```bash
# Install deps
uv pip install -e libs/common -e libs/contracts -e libs/messaging \
               -e libs/observability -e libs/storage \
               -e services/portfolio

cd services/portfolio

# Configure (minimal)
cat > .env << 'EOF'
PORTFOLIO_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/portfolio_db
PORTFOLIO_KAFKA_BOOTSTRAP_SERVERS=localhost:9092
PORTFOLIO_VALKEY_URL=redis://localhost:6379/0
PORTFOLIO_INTERNAL_JWT_SKIP_VERIFICATION=true   # no Zitadel required
PORTFOLIO_STORAGE_ACCESS_KEY=minioadmin           # required field — any value works for local dev
PORTFOLIO_STORAGE_SECRET_KEY=minioadmin           # required field
EOF

# Migrate and run
make migrate   # alembic upgrade head
make run       # uvicorn on port 8001
```

**Note**: Set `PORTFOLIO_INTERNAL_JWT_SKIP_VERIFICATION=true` to skip RS256 JWT validation
when running without a full S9+Zitadel stack. Never use this in production.

---

## How to Run Tests

```bash
cd services/portfolio

# Unit tests only (fast, no Docker)
python -m pytest tests/unit/ -v

# Integration tests (requires Docker — spins up Postgres via testcontainers)
python -m pytest tests/integration/ -v

# Contract tests (validates Avro schemas)
python -m pytest tests/contract/ -v

# All tests
python -m pytest tests/ -v

# Lint + types
make lint   # ruff check + mypy strict
```

Test suite: 300+ tests (unit + contract + integration + e2e).

---

## Operational Scripts

All scripts live in `services/portfolio/scripts/` and are baked into the container at
`/app/scripts/`. Every script supports `--dry-run` and is idempotent.

```bash
# Generic invocation:
docker compose exec portfolio python /app/scripts/<script_name>.py [--dry-run]
```

| Script | When to Run | What It Does |
|--------|------------|--------------|
| `repair_holdings_after_replay_drift.py` | Holdings quantities inflated (BP-264) | Zeroes holdings for portfolios with brokerage connections; next sync repopulates |
| `backfill_root_portfolios.py` | After PLAN-0046 deploy | Creates one `kind='root'` portfolio per user that lacks one |
| `backfill_portfolio_value_snapshots.py` | Fresh environment or after worker outage | Replays transactions × close prices (max 365 days) |
| `backfill_watchlist_member_denorm.py` | Legacy watchlist rows with NULL ticker/name | Updates from `instruments` table by `entity_id` |
| `trigger_brokerage_resync.py` | After adding `transactions.amount` column | Zeroes `last_synced_at` to force full re-fetch |

### Day-1 Deploy Checklist

1. Apply migrations (`alembic upgrade head`)
2. `repair_holdings_after_replay_drift --dry-run` → review
3. `repair_holdings_after_replay_drift` (live)
4. `backfill_root_portfolios`
5. `backfill_watchlist_member_denorm`
6. `backfill_portfolio_value_snapshots`
7. `trigger_brokerage_resync` (optional)

---

## Portfolio Snapshot Worker

`portfolio.workers.portfolio_snapshot_worker` — daily equity curve snapshot.

- Wakes at **21:30 UTC** every day (well after NYSE close, EODHD bars available by 20:00 UTC)
- Skips weekends and hard-coded US NYSE holidays for 2025/2026
- Two-phase pass:
  1. For every non-root active portfolio: `ComputePortfolioValueUseCase` → write `portfolio_value_snapshots` row
  2. For every root active portfolio: sum same-date non-root snapshots → upsert root row
- Idempotent via `ON CONFLICT DO UPDATE` — safe to re-run
- Entry point: `python -m portfolio.workers.portfolio_snapshot_worker`

`GET /portfolios/{id}/value-history` response includes:
- `metadata.last_snapshot_at` — latest snapshot date in the filtered window
- `metadata.next_scheduled_run_utc` — next 21:30 UTC wake-up
- `data_quality` per point — `"ok"` or `"partial_prices"` (stale close or cost-basis fallback)

---

## Core Workflows

### Record Transaction → Holding Update (PLAN-0046)

Since PLAN-0046, `RecordTransactionUseCase` is **history-only** — it no longer mutates the
`holdings` table. Holdings are now overwritten exclusively by
`UpsertHoldingsFromSnapshotUseCase` after every brokerage sync. The `HoldingChanged` event
is emitted by the snapshot use case.

```
POST /api/v1/transactions
  → RecordTransactionUseCase
    → INSERT transaction (history)
    → INSERT outbox event (TransactionRecorded)
    → commit
```

```
BrokerageTransactionSyncWorker (4h cycle)
  → SnapTrade.get_account_positions()
  → UpsertHoldingsFromSnapshotUseCase
    → UPSERT holdings (authoritative snapshot)
    → INSERT outbox event (HoldingChanged)
    → commit
```

---

## Common Pitfalls

- **Alert preferences default to `enabled=True` when missing** — `GetAlertPreferencesUseCase`
  synthesizes defaults for all `AlertType` values not in the DB. Never infer "disabled" from
  a missing row.

- **Watchlist soft-delete preserves DB rows** — `DeleteWatchlistUseCase` sets `status=deleted`
  but does not remove the row. Consumers must check `status`.

- **Watchlist cache invalidation is DEL, not rebuild** — `add_member`/`remove_member` call
  `invalidate_entity(entity_id)` (DEL). A read immediately after a write will see a cache
  miss (`[]`), not stale data.

- **SnapTrade `snaptrade_user_secret` is OPAQUE** — never log it. `BrokerageConnection.__repr__`
  redacts it. `connectionType=read` must be hardcoded server-side.

- **`UnitOfWork.__aexit__` does NOT auto-commit** — every mutating use case must call
  `await uow.commit()` explicitly.

- **`PORTFOLIO_INTERNAL_SERVICE_TOKEN` is REMOVED** — use `InternalJWTMiddleware` / RS256.

- **`POST /tenants` requires `role=system`** — integration tests cannot call it directly;
  use direct DB seeding instead.

- **In-progress brokerage sync triggers**: the activation callback schedules a background sync
  task; failures are logged but never surface as 5xx (the 200 response is already sent).

---

## Observability

- **Metrics**: request count/latency by endpoint, transaction count by type, holding count
- **Log fields**: `service=portfolio`, `tenant_id`, `correlation_id`, `portfolio_id`
- **Traces**: FastAPI + SQLAlchemy auto-instrumented via OpenTelemetry (`PORTFOLIO_OTLP_ENDPOINT`)

---

## Error Codes

| Error | HTTP |
|-------|------|
| `WATCHLIST_NOT_FOUND` | 404 |
| `WATCHLIST_ALREADY_EXISTS` | 409 |
| `WATCHLIST_MEMBER_NOT_FOUND` | 404 |
| `WATCHLIST_MEMBER_ALREADY_EXISTS` | 409 |
| `VALIDATION_ERROR` (invalid alert_type) | 422 |
| `ALERT_PREFERENCE_NOT_FOUND` | 404 |
| `PORTFOLIO_NOT_FOUND` | 404 |
| `TRANSACTION_DUPLICATE` (duplicate external_ref) | 409 |
| `PORTFOLIO_ARCHIVED` | 409 |
| `BROKERAGE_CONNECTION_NOT_FOUND` | 404 |
| `BROKERAGE_ALREADY_CONNECTED` | 409 |
| `from`/`days` produces start > end | 400 |
