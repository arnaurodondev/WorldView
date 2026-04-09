# PRD-0022 — SnapTrade Brokerage Portfolio Sync (Read-Only)

> **Status**: Draft — 2026-04-06
> **Author**: Arnau Rodon
> **Services affected**: S1 (Portfolio Service), S9 (API Gateway), Frontend
> **Depends on**: No hard dependency on other PRDs; can run in parallel with PRD-0019/0020/0021
> **Plan**: PLAN-0022 (to be generated)
> **Security classification**: HIGH — this feature handles financial account credentials via SnapTrade OAuth

---

## 1. Problem Statement

Worldview's portfolio feature (S1) requires users to manually enter every transaction (buy/sell/dividend) to track holdings. For users with active brokerage accounts at IBKR, Fidelity, Schwab, TastyTrade, or Robinhood, this manual entry creates a friction barrier that prevents portfolio-aware features (risk alerts, entity overlap with watchlists, P&L tracking) from being used at all.

Brokerage portfolio sync eliminates this friction: users connect their brokerage account once via SnapTrade's OAuth-hosted flow, and Worldview automatically imports their transaction history and keeps holdings up to date by replaying transactions through the existing `RecordTransactionUseCase`.

**Explicit scope constraint**: This PRD covers **read-only** data import only. No order placement, no trade execution, no account management. Every potential vector for executing trades is removed at the architecture level.

---

## 2. SnapTrade Terms Assessment

| Aspect | Finding | Impact |
|--------|---------|--------|
| Free tier | $0, 5 connected users, "testing and personal use" | Covers thesis (developer + a few test users) |
| Pay-as-you-go | $2/connected user/month | Affordable if thesis evaluation requires more users |
| Data reselling | Prohibited | No impact — worldview never resells user data |
| User consent | Required: users must agree to SnapTrade End User ToS before connection | Must implement consent checkbox + store evidence |
| Data storage | User brokerage tokens stored by SnapTrade (not Worldview) | Reduces Worldview's data custody obligations |
| Academic use | No explicit exemption; Free tier "personal use" covers thesis scope | Use Free tier for thesis; document as evaluation-only |

**Conclusion**: SnapTrade is viable for thesis use at $0 cost. The Free tier "personal use" clause covers a thesis evaluation with ≤5 users.

---

## 3. Target Users

| User | Workflow | Benefit |
|------|----------|---------|
| **Retail Investors** | Connect IBKR or TastyTrade; portfolio auto-populates | Zero manual transaction entry |
| **Research Analysts** | Track holdings across multiple brokerages | Cross-brokerage portfolio view without manual management |
| **Thesis Evaluators** | See end-to-end portfolio sync demo | Demonstrates OAuth integration and data pipeline completeness |

---

## 4. Functional Requirements

### 4.1 Connection Management

| ID | Requirement | Priority |
|----|-------------|----------|
| F-01 | User can initiate a brokerage connection by clicking "Connect Brokerage" in the frontend | MUST |
| F-02 | Connection flow redirects user to SnapTrade's hosted Connection Portal (OAuth-like flow) | MUST |
| F-03 | SnapTrade returns the user to Worldview via a configured redirect URL after successful connection | MUST |
| F-04 | User must explicitly agree to SnapTrade's End User Terms of Service before the redirect (checkbox) | MUST |
| F-05 | S1 stores the `snaptrade_user_id`, `snaptrade_user_secret`, and `authorization_id` for each connection | MUST |
| F-06 | User can list their active brokerage connections | MUST |
| F-07 | User can disconnect a brokerage connection (deletes connection from SnapTrade + removes from Worldview DB) | MUST |
| F-08 | Disconnecting does NOT delete transactions already imported — historical data is retained | MUST |
| F-09 | A user can connect multiple brokerage accounts | MUST |
| F-10 | Connections are scoped to `connectionType=read` — SnapTrade Connection Portal must not show the "read+trade" option | MUST |

### 4.2 Transaction Sync

| ID | Requirement | Priority |
|----|-------------|----------|
| F-11 | A `BrokerageTransactionSyncWorker` runs on a 4-hour cycle, fetching transactions from all active connections | MUST |
| F-12 | Fetched transactions are replayed through `RecordTransactionUseCase` using the existing transaction model | MUST |
| F-13 | Transaction deduplication uses `external_ref = snaptrade_transaction_id` (existing `UNIQUE (portfolio_id, external_ref)` constraint) | MUST |
| F-14 | Only `BUY`, `SELL`, and `DIVIDEND` transaction types are imported; options/derivatives and transfers are skipped with a warning log | MUST |
| F-15 | If an instrument does not exist in S1's `instruments` table, the worker attempts to resolve it from S3 Market Data by symbol; if not found, the transaction is logged to a `sync_errors` table and skipped | MUST |
| F-16 | The initial sync imports up to 2 years of transaction history (configurable via `BROKERAGE_SYNC_HISTORY_DAYS=730`) | MUST |
| F-17 | Subsequent syncs use a watermark (`last_synced_at`) stored per connection to fetch only new transactions | MUST |
| F-18 | Sync errors (unsupported transaction type, unknown instrument, API error) are stored in `brokerage_sync_errors` table and exposed via a frontend notification | SHOULD |

### 4.3 Security Constraints

| ID | Requirement | Priority |
|----|-------------|----------|
| F-19 | `snaptrade_user_secret` is NEVER logged (sanitised by `libs/observability` log sanitiser) | MUST |
| F-20 | SnapTrade API calls use the `snaptrade-python-sdk` exclusively; no manual HTTP calls that could accidentally log credentials | MUST |
| F-21 | The brokerage connections endpoint (`/api/v1/brokerage-connections`) is tenant-isolated: a user can only see and manage their own connections | MUST |
| F-22 | The `connectionType=read` parameter is hardcoded server-side in the SnapTrade portal URL generation — it is NOT a user-supplied parameter | MUST |
| F-23 | SnapTrade credentials (`SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY`) are loaded from env vars via pydantic-settings (R13) | MUST |
| F-24 | The redirect URL must be validated to match the configured `SNAPTRADE_REDIRECT_URI` — no open redirects | MUST |

---

## 5. Non-Functional Requirements

| Attribute | Target |
|-----------|--------|
| Sync latency | Holdings reflect transactions within 4 hours of execution at the brokerage |
| Import coverage | BUY/SELL/DIVIDEND for US equities and ETFs (the instruments already in S1's `instruments` table) |
| Cost | $0 for thesis (≤5 users, Free tier); $2/user/month at scale |
| Security | SnapTrade user secrets never stored in plaintext in logs or error messages |
| Idempotency | Re-syncing the same transactions produces identical DB state (existing `external_ref` UNIQUE constraint handles this) |

---

## 6. Technical Design

### 6.1 Affected Services

| Service | Change Type | Summary |
|---------|-------------|---------|
| **S1 Portfolio Service** | New domain entities + DB tables + use cases + background worker | `BrokerageConnection`, `BrokerageTransactionSyncWorker`, 3 new tables |
| **S9 API Gateway** | New proxy routes (3 connection endpoints) | JWT-authenticated, tenant-isolated |
| **Frontend** | New "Connect Brokerage" UI in portfolio page | Connection list, connect button, disconnect, sync error notifications |

---

### 6.2 API Changes

#### POST /api/v1/brokerage-connections (S1)

- **Purpose**: Initiates a SnapTrade connection — registers the user with SnapTrade, generates a Connection Portal redirect URL, and stores the pending connection
- **Auth**: required (JWT via S9; `user_id` injected by S9)
- **Request body**:

| Field | Type | Required | Default | Validation | Description |
|-------|------|----------|---------|------------|-------------|
| `portfolio_id` | UUID | yes | — | valid UUIDv7 | Portfolio to sync transactions into |
| `snaptrade_tos_accepted` | bool | yes | — | must be `true` | User confirmation of SnapTrade End User ToS |

- **Business rules**:
  - `snaptrade_tos_accepted` must be `true` — returns 422 if false
  - S1 calls SnapTrade `POST /snapTrade/registerUser` to get `snaptrade_user_id` and `snaptrade_user_secret`
  - S1 calls SnapTrade `POST /authorizations/loginSnapTradeUser` with `connectionType=read` to get `redirectURI`
  - `redirectURI` is returned to frontend (not stored) — frontend immediately redirects user
  - S1 creates a `brokerage_connections` row with `status=pending`

- **Response** (201):

| Field | Type | Description |
|-------|------|-------------|
| `connection_id` | UUID | Worldview internal connection ID (UUIDv7) |
| `redirect_uri` | string | SnapTrade Connection Portal URL — frontend redirects here |

- **Error responses**: 400 (portfolio_id not found or wrong tenant), 422 (ToS not accepted)

---

#### GET /api/v1/brokerage-connections (S1)

- **Purpose**: List user's active brokerage connections
- **Auth**: required; `user_id` injected by S9
- **Query parameters**:

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `portfolio_id` | UUID | no | — | Filter by portfolio |

- **Response** (200):

| Field | Type | Description |
|-------|------|-------------|
| `items` | `BrokerageConnectionResponse[]` | List of connections |

`BrokerageConnectionResponse` fields:

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `connection_id` | UUID | no | Internal connection ID |
| `portfolio_id` | UUID | no | Linked portfolio |
| `brokerage_name` | string | yes | Brokerage name as returned by SnapTrade (e.g. "IBKR", "Robinhood") |
| `status` | string | no | `pending` / `active` / `error` / `disconnected` |
| `last_synced_at` | datetime | yes | UTC timestamp of last successful sync |
| `created_at` | datetime | no | Connection creation time |

---

#### DELETE /api/v1/brokerage-connections/{connection_id} (S1)

- **Purpose**: Disconnects a brokerage account — removes from SnapTrade and marks as disconnected in Worldview
- **Auth**: required; checks `connection.user_id == request.user_id` (tenant isolation)
- **Business rules**:
  - Calls SnapTrade `DELETE /authorizations/{authorizationId}` to revoke access
  - Updates `brokerage_connections.status = 'disconnected'`
  - **Does NOT delete imported transactions or holdings** (historical data retained per F-08)
- **Response** (200): `{ "status": "disconnected" }`
- **Error responses**: 404 (not found), 403 (wrong user)

---

#### GET /api/v1/brokerage-connections/{connection_id}/callback (S1)

- **Purpose**: SnapTrade redirects the user here after completing the Connection Portal flow
- **Auth**: required (JWT) — this is a frontend route that calls this endpoint after being redirected
- **Query parameters** (injected by SnapTrade redirect):

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `authorizationId` | string | yes | SnapTrade authorization ID |
| `userId` | string | yes | SnapTrade user ID (must match stored value) |
| `sessionId` | string | yes | SnapTrade session ID |

- **Business rules**:
  - Validates `userId` matches stored `snaptrade_user_id` for `connection_id`
  - Updates `brokerage_connections.authorization_id = authorizationId` and `status = 'active'`
  - Triggers an immediate transaction sync for this connection (async task)
- **Response** (200): `{ "status": "active", "connection_id": "..." }`
- **Error responses**: 400 (userId mismatch), 404 (connection not found), 422 (SnapTrade params missing)

---

#### GET /api/v1/brokerage-connections/{connection_id}/sync-errors (S1)

- **Purpose**: Returns the list of sync errors for a specific brokerage connection
- **Auth**: required; `user_id` injected by S9. Use case verifies ownership before returning data.
- **Path parameter**: `connection_id` (UUID)
- **Query parameters**:

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `limit` | int | no | 50 | Max number of errors to return (1–200) |

- **Response** (200):

`GetSyncErrorsResponse` fields:

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `items` | `SyncErrorResponse[]` | no | Sync errors for this connection, newest first |

`SyncErrorResponse` fields:

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `id` | UUID | no | Error record ID |
| `connection_id` | UUID | no | Source connection |
| `snaptrade_transaction_id` | str | no | SnapTrade's transaction identifier |
| `error_type` | str | no | `unknown_instrument` / `unsupported_type` / `api_error` / `validation_error` |
| `error_detail` | str | yes | Human-readable description |
| `created_at` | datetime | no | Error record creation time |

> **Privacy note**: `raw_transaction` (§6.4) is intentionally **excluded** from this response schema. It may contain raw brokerage positions, balances, and account metadata — it is stored for admin DB-level debugging only. `resolved_at` is also excluded: no code path in PLAN-0022 sets it (reserved for a future `AcknowledgeSyncError` use case).

- **Error responses**: 404 (connection not found or wrong user)

---

#### S9 Gateway proxy routes (new)

| Method | Gateway Path | Proxied To |
|--------|-------------|-----------|
| POST | `/api/v1/brokerage-connections` | `S1 POST /api/v1/brokerage-connections` |
| GET | `/api/v1/brokerage-connections` | `S1 GET /api/v1/brokerage-connections` |
| DELETE | `/api/v1/brokerage-connections/{id}` | `S1 DELETE /api/v1/brokerage-connections/{id}` |
| GET | `/api/v1/brokerage-connections/{id}/callback` | `S1 GET /api/v1/brokerage-connections/{id}/callback` |
| GET | `/api/v1/brokerage-connections/{id}/sync-errors` | `S1 GET /api/v1/brokerage-connections/{id}/sync-errors` |

All: JWT auth required (S9 injects `user_id`), 30 req/min per user (lower than default — these endpoints involve external API calls).

---

### 6.3 Event Changes

No new Kafka events. The existing `portfolio.events.v1` topic already carries `transaction.recorded` and `holding.changed` events when `RecordTransactionUseCase` runs — brokerage-imported transactions emit the same events as manual transactions. This is the core advantage of transaction-replay: full observability from existing infrastructure.

---

### 6.4 Database Changes

#### New table: `brokerage_connections` (`portfolio_db`)

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `id` | UUID | no | `new_uuid7()` | PK | Internal connection ID |
| `tenant_id` | UUID | no | — | NOT NULL, FK tenants(id) | Tenant isolation |
| `user_id` | UUID | no | — | NOT NULL, FK users(id) | Owner |
| `portfolio_id` | UUID | no | — | NOT NULL, FK portfolios(id) | Target portfolio |
| `snaptrade_user_id` | TEXT | no | — | NOT NULL | SnapTrade user identifier |
| `snaptrade_user_secret` | TEXT | no | — | NOT NULL | SnapTrade user secret (opaque token — NOT a password) |
| `authorization_id` | TEXT | yes | `null` | — | SnapTrade authorization ID (set after callback) |
| `brokerage_name` | TEXT | yes | `null` | — | Human-readable brokerage name (set after first sync) |
| `status` | VARCHAR(20) | no | `'pending'` | NOT NULL | `pending` / `active` / `error` / `disconnected` |
| `snaptrade_tos_accepted_at` | TIMESTAMPTZ | no | — | NOT NULL | When user accepted SnapTrade ToS |
| `last_synced_at` | TIMESTAMPTZ | yes | `null` | — | Last successful transaction sync time |
| `last_sync_cursor` | TEXT | yes | `null` | — | Watermark for incremental sync |
| `created_at` | TIMESTAMPTZ | no | `now()` | NOT NULL | |
| `updated_at` | TIMESTAMPTZ | no | `now()` | NOT NULL | |

- **Indexes**: `(user_id, status)`, `(tenant_id)`, `(portfolio_id)`
- **Critical security note**: `snaptrade_user_secret` is an **opaque token** issued by SnapTrade for that user's API calls — it is NOT a brokerage password or credential. It must never appear in logs (R14). It is stored in plaintext in the DB because it must be used for every SnapTrade API call; encryption at rest (provided by Postgres/Docker volume) is the protection layer.
- **Estimated rows**: ~10 total for thesis

---

#### New table: `brokerage_sync_errors` (`portfolio_db`)

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `id` | UUID | no | `new_uuid7()` | PK | |
| `connection_id` | UUID | no | — | NOT NULL, FK brokerage_connections(id) | |
| `snaptrade_transaction_id` | TEXT | no | — | NOT NULL | SnapTrade's transaction identifier |
| `error_type` | VARCHAR(50) | no | — | NOT NULL | `unknown_instrument`, `unsupported_type`, `api_error`, `validation_error` |
| `error_detail` | TEXT | yes | `null` | — | Human-readable error description |
| `raw_transaction` | JSONB | yes | `null` | — | Raw SnapTrade transaction for debugging |
| `created_at` | TIMESTAMPTZ | no | `now()` | NOT NULL | |
| `resolved_at` | TIMESTAMPTZ | yes | `null` | — | Set when user acknowledges |

- **Indexes**: `(connection_id, created_at DESC)`, `(error_type)`
- **Estimated rows**: ~100 total for thesis
- **Privacy**: `raw_transaction` MUST NEVER be included in any API response — it may contain sensitive financial data (account balances, positions, transaction details) from the brokerage. It is stored for admin DB-level debugging only and is excluded from all `SyncErrorResponse` API schemas.

---

### 6.5 Domain Model Changes

#### New entity: `BrokerageConnection` (S1 domain, mutable)

| Attribute | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| `id` | UUID | yes | UUIDv7 | Internal ID |
| `tenant_id` | UUID | yes | UUIDv7 | Tenant |
| `user_id` | UUID | yes | UUIDv7 | Owner user |
| `portfolio_id` | UUID | yes | UUIDv7 | Target portfolio |
| `snaptrade_user_id` | str | yes | 1–200 chars | SnapTrade user ID |
| `snaptrade_user_secret` | str | yes | 1–500 chars | SnapTrade user secret (never log) |
| `authorization_id` | str \| None | no | — | SnapTrade authorization ID |
| `brokerage_name` | str \| None | no | — | Brokerage display name |
| `status` | ConnectionStatus | yes | enum | `pending`/`active`/`error`/`disconnected` |
| `snaptrade_tos_accepted_at` | datetime | yes | UTC-aware | ToS acceptance time |
| `last_synced_at` | datetime \| None | no | UTC-aware | Last sync time |
| `last_sync_cursor` | str \| None | no | — | Pagination cursor for incremental sync |
| `created_at` | datetime | yes | UTC-aware | Connection creation time (set once, never mutated) |
| `updated_at` | datetime | yes | UTC-aware | Last modification time (updated on every `save()`) |

- **Invariants**: `snaptrade_tos_accepted_at` is UTC-aware. `snaptrade_user_secret` must never appear in `__repr__`, `__str__`, or log serialisation (override `__repr__` to redact).
- **State transitions**: `pending` → `active` (on callback); `active` → `error` (on sync failure); `active`/`error` → `disconnected` (on delete)

---

#### New enum: `ConnectionStatus` (S1 domain)

```python
class ConnectionStatus(StrEnum):
    PENDING = "pending"         # Portal link generated, user not yet returned
    ACTIVE = "active"           # Authorized and syncing
    ERROR = "error"             # Last sync failed; retrying
    DISCONNECTED = "disconnected"  # User disconnected
```

---

#### New entity: `BrokerageTransactionSyncError` (S1 domain, frozen)

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | UUID | yes | UUIDv7 |
| `connection_id` | UUID | yes | Source connection |
| `snaptrade_transaction_id` | str | yes | SnapTrade's ID |
| `error_type` | SyncErrorType | yes | Error category |
| `error_detail` | str \| None | no | Human-readable description |
| `raw_transaction` | dict \| None | no | Raw SnapTrade JSON — **internal DB inspection only; NEVER exposed via any API response** (may contain positions, balances, and account details from the brokerage) |
| `created_at` | datetime | yes | UTC-aware record creation time |

> **Note on `resolved_at`**: The `brokerage_sync_errors` DB table (§6.4) reserves a `resolved_at TIMESTAMPTZ` column for a future `AcknowledgeSyncError` use case. It is **not** part of the domain entity or any use case in PLAN-0022 — implementers must not populate or expose it.

---

#### New enum: `SyncErrorType` (S1 domain)

```python
class SyncErrorType(StrEnum):
    UNKNOWN_INSTRUMENT = "unknown_instrument"
    UNSUPPORTED_TYPE = "unsupported_type"
    API_ERROR = "api_error"
    VALIDATION_ERROR = "validation_error"
```

---

#### New process: `BrokerageTransactionSyncWorker` (S1)

```
services/portfolio/src/portfolio/workers/
└── brokerage_sync_worker.py
```

Entry point: `python -m portfolio.workers.brokerage_sync_worker`

**Process lifecycle**:
1. Run `sync_cycle()` immediately on startup, then loop on `BROKERAGE_SYNC_CYCLE_SECONDS` (default: 14400 = 4h)
2. `sync_cycle()`:
   a. Query `brokerage_connections` WHERE `status IN ('active', 'error')` (not pending, not disconnected)
   b. For each connection:
      - Call SnapTrade `GET /accounts/{userId}/activities` with `startDate = last_sync_cursor OR (now - HISTORY_DAYS)`, `endDate = now`
      - For each returned transaction:
        - Skip if `snaptrade_transaction_id` already has a row in `transactions.external_ref` (dedup)
        - Map transaction type: `BUY`→`BUY/OUTFLOW`, `SELL`→`SELL/INFLOW`, `DIV`→`DIVIDEND/INFLOW`; others → `brokerage_sync_errors` + skip
        - Resolve instrument: match by symbol in `portfolio.instruments`; if not found → call S3 `/api/v1/instruments/{symbol}`; if still not found → `brokerage_sync_errors` + skip
        - Call `RecordTransactionUseCase` with `external_ref = snaptrade_transaction_id`
      - Update `last_synced_at = now()` and `last_sync_cursor = latest_transaction_date`
      - If any API error: set `status = 'error'` with exponential backoff (cap: 24h)

**SnapTrade SDK usage** — ⚠️ **Verify before implementing (BP-100)**:
> All SnapTrade SDK method names, module paths, and parameter names MUST be verified against the installed `snaptrade-python-sdk` version before committing. Run `python -c "from snaptrade_client import SnapTrade; help(SnapTrade)"` to inspect available methods. Method names documented elsewhere in this PRD (e.g., `account_information.get_activities`, `transactions_and_reporting.get_activities`) are **unverified** — confirm the exact API from the installed SDK. Refer to BP-100 in PLAN-0022 Wave B-1 regression guardrails.

**Security invariants for the worker**:
- Never pass `snaptrade_user_secret` to structlog — use `bind_contextvars` only for `connection_id`, `user_id`, `brokerage_name`
- Use try/except around SnapTrade calls; catch `Exception` to prevent crashes that might leak secrets in tracebacks
- Log `snaptrade_transaction_id` but never log raw SnapTrade response (may contain balance/account details)

---

#### SnapTrade Transaction Type Mapping

| SnapTrade `type` | Worldview `TransactionType` | Worldview `direction` | Notes |
|------------------|---------------------------|----------------------|-------|
| `BUY` | `BUY` | `OUTFLOW` | Standard equity purchase |
| `SELL` | `SELL` | `INFLOW` | Standard equity sale |
| `DIV` or `DIVIDEND` | `DIVIDEND` | `INFLOW` | Cash dividend |
| `OPTION_*` | — | — | Skip + log SyncErrorType.UNSUPPORTED_TYPE |
| `TRANSFER_*` | — | — | Skip + log SyncErrorType.UNSUPPORTED_TYPE |
| `INTEREST` | — | — | Skip + log SyncErrorType.UNSUPPORTED_TYPE |
| All others | — | — | Skip + log SyncErrorType.UNSUPPORTED_TYPE |

---

#### New use cases (S1 application layer)

| Use Case | Description |
|----------|-------------|
| `InitiateBrokerageConnectionUseCase` | Register SnapTrade user, generate portal URL, create `brokerage_connections` row with `status=pending` |
| `ActivateBrokerageConnectionUseCase` | Process callback, set `authorization_id`, update `status=active` |
| `ListBrokerageConnectionsUseCase` | Return connections for a user (tenant-filtered) |
| `DisconnectBrokerageConnectionUseCase` | Revoke SnapTrade authorization, set `status=disconnected` |
| `GetSyncErrorsUseCase` | Return `brokerage_sync_errors` for a connection |

All use cases follow the existing hexagonal pattern: depend on abstract repository ports, receive `UnitOfWork` via DI.

---

#### New infrastructure: `SnapTradeClient` (S1 infrastructure layer)

```
services/portfolio/src/portfolio/infrastructure/brokerage/
├── snaptrade_client.py    # Wraps snaptrade-python-sdk; port interface defined in application/ports/
└── __init__.py
```

Port interface (application layer):
```python
class IBrokerageClient(Protocol):
    async def register_user(self, user_id_hint: str) -> SnapTradeUser: ...
    async def generate_portal_url(self, user: SnapTradeUser, redirect_uri: str) -> str: ...
    async def revoke_authorization(self, user: SnapTradeUser, authorization_id: str) -> None: ...
    async def get_activities(self, user: SnapTradeUser, start: date, end: date) -> list[SnapTradeActivity]: ...
```

**Why a port?**: Enables dependency injection of a `FakeSnapTradeClient` in unit tests — no SnapTrade API calls in CI.

---

### 6.6 Frontend Changes

#### Portfolio Page: "Connected Brokerages" section

- **Location**: `apps/frontend/src/pages/Portfolio.tsx` — new section below portfolio header
- **Components**:
  - `ConnectedBrokeragesList` — displays existing connections
  - `ConnectBrokerageModal` — modal for initiating a new connection
  - `SyncErrorsBanner` — banner showing count of unresolved sync errors with a details link

#### `ConnectBrokerageModal` flow

1. User clicks "Connect Brokerage"
2. Modal opens with text: "Connect your brokerage account to automatically sync your transactions. You will be redirected to SnapTrade's secure connection portal." + SnapTrade ToS link
3. Checkbox: "I agree to SnapTrade's End User Terms of Service" (required)
4. Portfolio selector dropdown (if user has multiple portfolios)
5. "Connect" button → calls `POST /api/v1/brokerage-connections` → receives `redirect_uri` → `window.location.href = redirect_uri`
6. After SnapTrade flow, user returns to `/portfolio/brokerage/callback?authorizationId=...`
7. Frontend calls `GET /api/v1/brokerage-connections/{id}/callback?authorizationId=...` → shows success

#### `ConnectedBrokeragesList`

Shows each connection as a row:
- Brokerage name (or "Pending" if not yet active)
- Status badge (pending/active/error/disconnected)
- Last synced time (relative)
- "Disconnect" button (calls DELETE endpoint with confirmation dialog)

---

### 6.7 Data Flow

#### Initial Connection Flow

```
[User: clicks "Connect Brokerage"] → POST /api/v1/brokerage-connections
[S9] → injects user_id → [S1: InitiateBrokerageConnectionUseCase]
  → SnapTrade SDK: register_user() → snaptrade_user_id + snaptrade_user_secret
  → SnapTrade SDK: generate_portal_url(connectionType=read,
       redirect_uri=f"{SNAPTRADE_REDIRECT_URI}?connectionId={connection.id}") → redirect_uri
       ^^^ connectionId embedded so SnapTrade appends it alongside authorizationId/userId/sessionId
  → INSERT brokerage_connections (status=pending)
  → return {connection_id, redirect_uri}
[Frontend] → window.location.href = redirect_uri
[User] → completes SnapTrade portal (selects brokerage, logs in via SnapTrade)
       → redirected to SNAPTRADE_REDIRECT_URI?connectionId={connection.id}&authorizationId=...&userId=...&sessionId=...
[Frontend /brokerage/callback] → reads connectionId from URL → GET /api/v1/brokerage-connections/{connectionId}/callback?authorizationId=...&userId=...&sessionId=...
[S1: ActivateBrokerageConnectionUseCase]
  → validates userId matches stored snaptrade_user_id
  → UPDATE brokerage_connections SET authorization_id, status='active'
  → triggers immediate BrokerageTransactionSyncWorker run for this connection
```

#### Recurring Sync Flow

```
[BrokerageTransactionSyncWorker] (every 4h)
  → SELECT brokerage_connections WHERE status IN ('active','error')
  → for each connection:
    → SnapTrade SDK: get_activities(start=last_sync_cursor, end=now)
    → for each activity:
      → map type (BUY/SELL/DIV or skip)
      → resolve instrument (S1 instruments table or S3 API)
      → RecordTransactionUseCase(external_ref=snaptrade_transaction_id)
        ← INSERT transactions ON CONFLICT (portfolio_id, external_ref) DO NOTHING
        → UPSERT holdings (qty + avg_cost)
        → outbox_event (TransactionRecorded + HoldingChanged)
    → UPDATE last_synced_at, last_sync_cursor
```

---

## 7. Architecture Decisions

### AD-1: SnapTrade vs direct IBKR + TastyTrade

| | SnapTrade | Direct IBKR + TastyTrade |
|-|-----------|--------------------------|
| Brokerage coverage | 25+ with one integration | 2 with two separate integrations |
| Maintenance | SnapTrade handles brokerage API changes | We maintain each direct integration |
| Complexity | Low (one SDK, hosted auth flow) | Medium per brokerage |
| Cost | $2/user/month at scale; $0 for thesis | $0 (IBKR free; TastyTrade free) |
| Credential handling | SnapTrade holds credentials, not Worldview | Worldview holds OAuth tokens directly |

**Decision**: SnapTrade. The security benefit alone (SnapTrade holds credentials, not Worldview) justifies the choice.

### AD-2: Transaction-replay vs snapshot sync

| | Transaction-replay | Snapshot sync |
|-|--------------------|---------------|
| Holdings accuracy | Derived from transactions (exact) | Snapshot at poll time |
| Transaction history | Full lineage preserved | Not available |
| Existing infrastructure reuse | `RecordTransactionUseCase` unchanged | New `UpsertHoldingUseCase` needed |
| Options/fractional shares | Skip unsupported types | More complex mapping needed |
| Complexity | Medium (mapping types, resolving instruments) | Lower |

**Decision**: Transaction-replay. Full transaction lineage is essential for P&L, cost basis, and tax-related features.

### AD-3: `snaptrade_user_secret` storage

The SnapTrade user secret is an opaque token (like an API key for that user) that must accompany every SnapTrade API call. Options:
- A) Store in DB encrypted with application-layer key (e.g., Fernet with env-var key)
- B) Store in DB plaintext (protected by Postgres/volume encryption at rest)
- C) Store in Valkey with TTL (rotating)

**Decision**: A — application-layer Fernet encryption using `cryptography.Fernet`, with the encryption key stored in `SNAPTRADE_SECRET_ENCRYPTION_KEY` env var.

**Rationale**: `snaptrade_user_secret` grants read-only access to a user's real brokerage account. DB snapshot exposure (leaked backup, compromised volume mount) would immediately expose live brokerage credentials. Fernet encryption (symmetric, authenticated, from the standard `cryptography` library) prevents this: the ciphertext stored in the DB is useless without the key. The key is a single env var — no KMS, no external dependency, minimal added complexity.

**Implementation**: `SqlAlchemyBrokerageConnectionRepository.save()` encrypts `snaptrade_user_secret` via `Fernet.encrypt()` before writing; `_to_entity()` decrypts via `Fernet.decrypt()` after reading. Plaintext secret exists only in memory during active SnapTrade API calls. The `Fernet` instance is constructed from the env var key and passed down from `app.py` lifespan → `SqlAlchemyUnitOfWork` → `SqlAlchemyBrokerageConnectionRepository`.

**Degraded mode**: If `SNAPTRADE_SECRET_ENCRYPTION_KEY` is empty (dev environment with no SnapTrade configured), store and return plaintext (startup warning logged). This allows unit tests and CI to run without configuring the key.

**Known limitation**: The encryption key in an env var is not rotatable without re-encrypting all rows. Acceptable for a thesis evaluation with ≤5 connections. A production version would use HashiCorp Vault or cloud KMS.

---

## 8. Security Analysis

| Threat | Mitigation |
|--------|-----------|
| `snaptrade_user_secret` in logs | `IBrokerageClient` port implementation never passes secret to structlog; `BrokerageConnection.__repr__` redacts it; observability sanitiser (`libs/observability`) catches `*secret*` patterns |
| `snaptrade_user_secret` exposed via DB snapshot/backup leak | Application-layer Fernet encryption (AD-3): ciphertext stored in DB, plaintext only in memory during active SnapTrade API calls. Key stored in `SNAPTRADE_SECRET_ENCRYPTION_KEY` env var, never committed to code |
| `raw_transaction` sync error data exposing brokerage account details | `raw_transaction` column is stored for admin DB-level debugging only; it is NEVER included in any API response schema — `SyncErrorResponse` exposes only `error_type` and `error_detail` |
| `connectionType=read` bypassed by attacker | Server-side hardcoded in `InitiateBrokerageConnectionUseCase` — frontend sends `portfolio_id` only; `connectionType` never user-supplied |
| Open redirect on callback URL | `SNAPTRADE_REDIRECT_URI` is a fixed config value; callback URL validated server-side to match it |
| Tenant cross-contamination in brokerage connections | All use cases filter by `user_id` + `tenant_id` before accessing connections |
| SnapTrade API request forgery | All SnapTrade calls use SDK with credentials from env, not from request parameters |
| Transaction injection via fake SnapTrade response | `snaptrade_transaction_id` is used as `external_ref`; the UNIQUE constraint prevents injecting fake transactions with same ID; no input from user in the transaction import path |
| SSRF via brokerage name | `brokerage_name` is display-only; never used as a URL |
| SnapTrade terms non-compliance | Free tier used, `connectionType=read`, no data reselling. ToS acceptance stored in `snaptrade_tos_accepted_at`. |

---

## 9. Failure Modes

| Failure | Detection | Recovery |
|---------|-----------|---------|
| SnapTrade API unavailable (503) | SDK raises exception → connection `status=error`, error logged | Exponential backoff; retry on next cycle; existing holdings unchanged |
| SnapTrade returns malformed transaction | `SyncErrorType.VALIDATION_ERROR` → `brokerage_sync_errors` row | Admin can inspect raw_transaction; transaction skipped, others continue |
| Unknown instrument (not in S1 or S3) | `SyncErrorType.UNKNOWN_INSTRUMENT` → `brokerage_sync_errors` row | User sees sync error notification; can manually add instrument then re-sync |
| `RecordTransactionUseCase` fails (e.g. duplicate key race) | Exception caught; transaction skipped; logged | Idempotency: next cycle retries; `external_ref` UNIQUE prevents double-insert |
| Connection in `pending` for > 1 hour (user never completed portal) | Monitor with `pending_since > 1h` alert metric | Worker skips pending connections; user can re-initiate |
| SnapTrade changes API (breaking change) | SDK version pin; integration test with wiremock fails | Pin SDK version; update when SnapTrade releases migration guide |

---

## 10. Scalability

This feature is inherently low-throughput for a thesis application (≤5 connections, ≤1000 transactions per connection). No scalability concerns. The 4-hour sync cycle is conservative — could be increased to hourly if needed.

---

## 11. Test Strategy

### Unit Tests (S1)

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_brokerage_connection_secret_redacted_in_repr` | `repr(connection)` does not contain `snaptrade_user_secret` | HIGH |
| `test_connection_status_transition_valid` | `pending → active` allowed | HIGH |
| `test_connection_status_transition_invalid` | `disconnected → active` raises error | MEDIUM |
| `test_initiate_connection_tos_not_accepted` | `snaptrade_tos_accepted=False` raises `DomainError` | HIGH |
| `test_sync_worker_skips_option_transactions` | SnapTrade activity with `type=OPTION_EXERCISE` → `SyncErrorType.UNSUPPORTED_TYPE` | HIGH |
| `test_sync_worker_maps_buy_transaction` | SnapTrade `BUY` → `TransactionType.BUY`, `direction=OUTFLOW` | HIGH |
| `test_sync_worker_maps_dividend_transaction` | SnapTrade `DIV` → `TransactionType.DIVIDEND`, `direction=INFLOW` | HIGH |
| `test_sync_worker_deduplicates_by_external_ref` | Same `snaptrade_transaction_id` processed twice → 1 transaction row | HIGH |
| `test_sync_worker_unknown_instrument_creates_error` | Instrument not found → `SyncErrorType.UNKNOWN_INSTRUMENT` row, worker continues | HIGH |
| `test_activate_connection_user_id_mismatch` | `ActivateBrokerageConnectionUseCase` with wrong userId → error | HIGH |
| `test_disconnect_revokes_snaptrade_authorization` | `FakeSnapTradeClient.revoke_authorization()` called once | HIGH |
| `test_disconnect_retains_transactions` | After disconnect, existing transactions remain | HIGH |
| `test_get_sync_errors_raw_transaction_excluded` | `GET /api/v1/brokerage-connections/{id}/sync-errors` response items do not contain a `raw_transaction` field — verified with `assert "raw_transaction" not in response.json()["items"][0]` | HIGH |

### Integration Tests (S1)

| Test | Infrastructure | What It Verifies |
|------|---------------|-----------------|
| `test_initiate_connection_creates_pending_row` | Postgres + FakeSnapTradeClient | POST `/api/v1/brokerage-connections` → `brokerage_connections` row with `status=pending` |
| `test_activate_connection_updates_status` | Postgres + FakeSnapTradeClient | GET `/api/v1/brokerage-connections/{id}/callback` → `status=active` |
| `test_sync_worker_end_to_end` | Postgres + FakeSnapTradeClient | Worker fetches activities → transactions inserted → holdings updated |
| `test_sync_worker_idempotent` | Postgres | Worker runs twice on same data → identical DB state |
| `test_brokerage_connections_api_tenant_isolation` | Postgres | User A cannot see User B's connections |
| `test_disconnect_marks_disconnected` | Postgres + FakeSnapTradeClient | DELETE `/api/v1/brokerage-connections/{id}` → `status=disconnected` |
| `test_sync_error_stored_for_unknown_instrument` | Postgres | Unknown symbol → `brokerage_sync_errors` row |

---

## 12. Migration Plan

1. **S1 Alembic**: New migration adding `brokerage_connections` and `brokerage_sync_errors` tables.
2. **SnapTrade SDK**: Add `snaptrade-python-sdk` to S1's `pyproject.toml` dependencies.
3. **Env vars**: Add `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY`, `SNAPTRADE_REDIRECT_URI`, `BROKERAGE_SYNC_CYCLE_SECONDS=14400`, `BROKERAGE_SYNC_HISTORY_DAYS=730` to S1 env.
4. **Encryption key (required for production)**: Generate `SNAPTRADE_SECRET_ENCRYPTION_KEY` with:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   Store in S1 env. If empty, S1 logs a startup warning and degrades to plaintext storage (acceptable for dev/CI; mandatory for any deployment with real brokerage connections).
5. **SnapTrade registration**: Developer must register a SnapTrade application at `app.snaptrade.com` to receive `CLIENT_ID` and `CONSUMER_KEY`. Free tier registration is self-service.
5. **Deployment**: New `brokerage_sync_worker` process added to docker-compose as a new command under the `portfolio` service image.

---

## 13. Observability

| Metric | Labels | Description |
|--------|--------|-------------|
| `s1_brokerage_sync_transactions_imported_total` | `status={success,skipped,error}`, `error_type` | Transaction import rate |
| `s1_brokerage_sync_cycle_duration_seconds` | — | Time per 4h sync cycle |
| `s1_brokerage_connections_total` | `status={pending,active,error,disconnected}` | Connection status distribution |
| `s1_brokerage_pending_connections_age_seconds` | — | Age of oldest pending connection (alert if > 3600s) |

### Log fields (sanitised)

- Worker: `service=portfolio`, `worker=brokerage_sync`, `connection_id`, `brokerage_name`
- **Never log**: `snaptrade_user_secret`, `authorization_id`, raw SnapTrade API responses

---

## 14. Open Questions

| ID | Question | Owner | Deadline |
|----|----------|-------|----------|
| OQ-001 | SnapTrade Free tier: 5 connected users — does "user" mean SnapTrade user (1 per Worldview user) or 5 total brokerage accounts? If 5 accounts, one user with 2 brokerages counts as 2. Clarify from SnapTrade docs. | Arnau | Before Wave A-1 |
| OQ-002 | SnapTrade's `get_activities` endpoint pagination — does it support cursor-based pagination? Need to verify SDK behaviour for users with >1000 transactions. | Arnau | Wave A-2 |
| OQ-003 | Should sync errors be automatically re-attempted on next cycle (after instrument becomes available in S1), or only on user manual trigger? | Arnau | Wave A-3 |
| OQ-004 | SNAPTRADE_REDIRECT_URI must be a public URL in production (SnapTrade redirects back to it). For local development, use `localhost:5173/portfolio/brokerage/callback`. For thesis demo, confirm URL with evaluators. | Arnau | Before implementation |

---

## 15. Effort Estimation

| Area | Waves | Complexity |
|------|-------|-----------|
| DB migrations: `brokerage_connections`, `brokerage_sync_errors` | 0.5 wave | Low |
| `IBrokerageClient` port + `SnapTradeClient` infrastructure | 1.5 waves | Medium |
| S1 domain entities + use cases (5 use cases) | 2 waves | Medium |
| S1 API routes (4 endpoints) + S9 proxy | 1 wave | Medium |
| `BrokerageTransactionSyncWorker` | 2 waves | Medium-High |
| Frontend: ConnectBrokerageModal + ConnectedBrokeragesList + callback route | 2 waves | Medium |
| Tests + docs | 1.5 waves | Medium |
| **Total** | **~10.5 waves** | — |
