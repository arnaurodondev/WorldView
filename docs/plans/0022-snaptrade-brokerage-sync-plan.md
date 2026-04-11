# PLAN-0022 — SnapTrade Brokerage Portfolio Sync

> **PRD**: [PRD-0022](../specs/0022-snaptrade-brokerage-sync.md)
> **Status**: in-progress
> **Created**: 2026-04-09
> **Updated**: 2026-04-11
> **Services affected**: S1 (Portfolio), S9 (API Gateway), Frontend

---

## Codebase State Verification

| PRD Reference | Type | Expected State | Actual State (verified) | Delta |
|--------------|------|---------------|--------------------------|-------|
| `brokerage_connections` table | DB table | new | absent (latest migration: `0005`) | create in Wave A-2 |
| `brokerage_sync_errors` table | DB table | new | absent | create in Wave A-2 |
| `ConnectionStatus` enum | S1 domain | new | absent (domain/enums.py has 8 enums) | create in Wave A-1 |
| `SyncErrorType` enum | S1 domain | new | absent | create in Wave A-1 |
| `BrokerageConnection` entity | S1 domain | new | absent | create in Wave A-1 |
| `IBrokerageClient` port | S1 application | new | absent (ports/repositories.py + ports/unit_of_work.py exist) | create in Wave B-1 |
| `SnapTradeClient` adapter | S1 infra | new | absent (`infrastructure/brokerage/` doesn't exist) | create in Wave B-1 |
| `brokerage_connections` repo | S1 infra | new | absent | create in Wave B-2 |
| `UnitOfWork.brokerage_connections` | S1 UoW | new | absent | extend in Wave B-2 |
| `/api/v1/brokerage-connections` routes (5 total) | S1 API | new | absent | create in Wave C-2 |
| `BrokerageTransactionSyncWorker` | S1 process | new | absent (`workers/` directory absent) | create in Wave D-1 |
| S9 brokerage-connections proxy | S9 proxy | new | absent (`proxy.py` has portfolio/market/news/chat routes) | create in Wave D-2 |
| `SNAPTRADE_CLIENT_ID` config | S1 config | new | absent from `config.py` | add in Wave A-2 |
| `snaptrade-python-sdk` dep | S1 pyproject | new | absent | add in Wave A-2 |

---

## Plan Dependency Graph

```
Wave A-1 (domain entities + ORM models)
    │
    ▼
Wave A-2 (Alembic migration 0006 + config + pyproject.toml)
    │
    ├─────────────────────────────────────────┐
    ▼                                         ▼
Wave B-1 (IBrokerageClient port +            Wave B-2 (Brokerage repos +
         SnapTradeClient adapter)             UoW extension)
    │                                         │
    └──────────────┬──────────────────────────┘
                   ▼
              Wave C-1 (5 use cases)
                   │
                   ├───────────────────────┐
                   ▼                       ▼
              Wave C-2                Wave D-1
              (S1 API routes)         (BrokerageTransactionSyncWorker)
                   │                       │
                   ▼                       ▼
              Wave D-2 (S9 proxy + unit tests)
                   │
                   ▼
              Wave E-1 (Frontend components)
```

**Critical path**: A-1 → A-2 → B-2 → C-1 → C-2 → D-2 → E-1
**Parallelizable**: B-1 ∥ B-2 (after A-2); D-1 ∥ C-2 (after C-1)

---

## Summary

| Metric | Value |
|--------|-------|
| Total waves | 9 |
| Total tasks | 36 |
| Services modified | S1 (Portfolio), S9 (API Gateway), Frontend |
| New DB tables | 2 (`brokerage_connections`, `brokerage_sync_errors`) |
| New use cases | 5 |
| New API endpoints | 5 (S1) + 5 (S9 proxy) |
| New processes | 1 (`BrokerageTransactionSyncWorker`) |
| Estimated total effort | 8–14 hours |

---

## Open Questions Resolution (before starting)

| ID | Question | Resolution for implementation |
|----|----------|-------------------------------|
| OQ-001 | 5-user Free tier scope | Implement with 1 SnapTrade user per Worldview user (1:1). The architecture is identical regardless — if "5" means accounts, no code change needed. |
| OQ-002 | Pagination in `get_activities` | Default SDK behaviour; if SDK returns paginated results implement a loop in Wave D-1 (flag as `TODO: verify SDK pagination in T-D-1-01`) |
| OQ-003 | Sync error retry strategy | Default to automatic retry on next cycle (simplest); Wave D-1 implements this |
| OQ-004 | SNAPTRADE_REDIRECT_URI | Use `http://localhost:5173/portfolio/brokerage/callback` as default in config; documented in Wave A-2 |

---

## Sub-plan A: S1 Domain + DB Foundations

### Wave A-1: Domain Entities, Enums, Errors, and ORM Models ✅

**Goal**: Establish the S1 domain layer foundation for brokerage connections — all types the upper layers depend on.
**Depends on**: none
**Estimated effort**: 45–75 minutes
**Status**: **DONE** — 2026-04-10 · 17 tests pass · ruff + mypy clean
**Architecture layer**: domain + infrastructure/db/models

#### Pre-read (agent must read before starting)
- `services/portfolio/src/portfolio/domain/enums.py`
- `services/portfolio/src/portfolio/domain/entities/portfolio.py` (pattern reference)
- `services/portfolio/src/portfolio/infrastructure/db/models/portfolio.py` (ORM pattern reference)
- `services/portfolio/src/portfolio/domain/errors.py`

#### Tasks

---

##### T-A-1-01: ConnectionStatus and SyncErrorType enums

**Type**: impl
**depends_on**: none
**blocks**: [T-A-1-02, T-A-1-03, T-A-1-04]
**Target files**: `services/portfolio/src/portfolio/domain/enums.py`
**PRD reference**: §6.5

**What to build**:
Extend `domain/enums.py` with two new `StrEnum` classes. These enums are used by `BrokerageConnection` and `BrokerageTransactionSyncError` entities respectively.

**Entities / Components**:
- **`ConnectionStatus(StrEnum)`**
  - `PENDING = "pending"` — Portal link generated, user not yet returned
  - `ACTIVE = "active"` — Authorized and syncing
  - `ERROR = "error"` — Last sync failed; retrying
  - `DISCONNECTED = "disconnected"` — User disconnected

- **`SyncErrorType(StrEnum)`**
  - `UNKNOWN_INSTRUMENT = "unknown_instrument"` — Symbol not found in S1 or S3
  - `UNSUPPORTED_TYPE = "unsupported_type"` — SnapTrade activity type not BUY/SELL/DIV
  - `API_ERROR = "api_error"` — SnapTrade API call failed
  - `VALIDATION_ERROR = "validation_error"` — Mapping/validation failed

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_connection_status_values` | All 4 members have correct string values | unit |
| `test_sync_error_type_values` | All 4 members have correct string values | unit |

**Acceptance criteria**:
- [ ] Both enums importable from `portfolio.domain.enums`
- [ ] ruff + mypy pass

---

##### T-A-1-02: BrokerageConnection domain entity

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-A-1-04, T-C-1-01]
**Target files**: `services/portfolio/src/portfolio/domain/entities/brokerage_connection.py`
**PRD reference**: §6.5

**What to build**:
A mutable dataclass representing a user's brokerage connection. Must redact `snaptrade_user_secret` from `__repr__` (security invariant F-19).

**Entities / Components**:
- **`BrokerageConnection`** (mutable `@dataclass`)
  - `id: UUID` — UUIDv7 internal ID
  - `tenant_id: UUID` — Tenant isolation
  - `user_id: UUID` — Owner user
  - `portfolio_id: UUID` — Target portfolio
  - `snaptrade_user_id: str` — 1–200 chars, SnapTrade user identifier
  - `snaptrade_user_secret: str` — 1–500 chars, opaque token (NEVER LOG)
  - `authorization_id: str | None` — SnapTrade authorization ID (set after callback)
  - `brokerage_name: str | None` — Human-readable name (e.g. "IBKR", set after first sync)
  - `status: ConnectionStatus` — Current state
  - `snaptrade_tos_accepted_at: datetime` — UTC-aware, when user accepted ToS
  - `last_synced_at: datetime | None` — UTC-aware, last successful sync
  - `last_sync_cursor: str | None` — Pagination cursor for incremental sync
  - `created_at: datetime` — UTC-aware
  - `updated_at: datetime` — UTC-aware

**Key methods**:
  - `__repr__(self) -> str` — Returns string with `snaptrade_user_secret` replaced by `"***REDACTED***"`. Never expose the secret in string representation.
  - `activate(self, authorization_id: str) -> None` — Sets `authorization_id`, sets `status = ACTIVE`; raises `BrokerageConnectionStateError` if `status != PENDING`
  - `mark_error(self) -> None` — Sets `status = ERROR`
  - `disconnect(self) -> None` — Sets `status = DISCONNECTED`; raises `BrokerageConnectionAlreadyDisconnectedError` if already `DISCONNECTED`

**Invariants**:
- `snaptrade_tos_accepted_at` is always UTC-aware
- `status` follows the state machine: `PENDING → ACTIVE → ERROR ↔ ACTIVE → DISCONNECTED`
- `snaptrade_user_secret` never appears in `__repr__`, `__str__`, or any log field

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_brokerage_connection_secret_redacted_in_repr` | `repr(conn)` does not contain `snaptrade_user_secret` value | unit |
| `test_connection_activate_valid` | `pending → active` transition sets authorization_id | unit |
| `test_connection_activate_invalid_state` | Activating non-pending connection raises `BrokerageConnectionStateError` | unit |
| `test_connection_disconnect_valid` | `active → disconnected` allowed | unit |
| `test_connection_disconnect_already_disconnected` | Disconnecting disconnected raises `BrokerageConnectionAlreadyDisconnectedError` | unit |

**Acceptance criteria**:
- [ ] `repr(conn)` contains `"***REDACTED***"` not the actual secret value
- [ ] State transition invariants enforced
- [ ] ruff + mypy pass

---

##### T-A-1-03: BrokerageTransactionSyncError entity + domain errors

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-A-1-04, T-C-1-05]
**Target files**:
- `services/portfolio/src/portfolio/domain/entities/brokerage_sync_error.py`
- `services/portfolio/src/portfolio/domain/errors.py` (extend)
**PRD reference**: §6.5, §9

**What to build**:
A frozen dataclass for sync errors (immutable after creation). Extend `errors.py` with new domain error classes.

**Entities / Components**:
- **`BrokerageTransactionSyncError`** (frozen `@dataclass`)
  - `id: UUID` — UUIDv7
  - `connection_id: UUID` — Source connection
  - `snaptrade_transaction_id: str` — SnapTrade's ID
  - `error_type: SyncErrorType` — Error category
  - `error_detail: str | None` — Human-readable description
  - `raw_transaction: dict[str, Any] | None` — Raw SnapTrade JSON (for debugging; never log in production)
  - `created_at: datetime` — UTC-aware

**New domain errors** (extend `portfolio/domain/errors.py`). All errors MUST define an `error_code` class variable (matches pattern in existing `errors.py`):
- `BrokerageConnectionNotFoundError(DomainError)` — `error_code = "BROKERAGE_CONNECTION_NOT_FOUND"` — connection_id not found for this user/tenant
- `BrokerageConnectionForbiddenError(DomainError)` — `error_code = "BROKERAGE_CONNECTION_FORBIDDEN"` — user_id mismatch on connection access
- `TosNotAcceptedError(DomainError)` — `error_code = "TOS_NOT_ACCEPTED"` — `snaptrade_tos_accepted` was False
- `BrokerageConnectionStateError(DomainError)` — `error_code = "BROKERAGE_CONNECTION_STATE_ERROR"` — Invalid state transition (e.g., activating non-pending)
- `BrokerageConnectionAlreadyDisconnectedError(BrokerageConnectionStateError)` — `error_code = "BROKERAGE_CONNECTION_ALREADY_DISCONNECTED"` — Already disconnected
- `BrokerageApiError(DomainError)` — `error_code = "BROKERAGE_API_ERROR"` — SnapTrade SDK raised an exception; wraps the original exception with a safe message that never leaks credentials. **Defined here (domain wave) not in T-B-1-03** — domain errors belong in the domain layer.

**Acceptance criteria**:
- [ ] All 5 error classes importable from `portfolio.domain.errors`
- [ ] `BrokerageTransactionSyncError` is frozen (immutable)
- [ ] ruff + mypy pass

---

##### T-A-1-04: ORM models for brokerage tables

**Type**: impl
**depends_on**: [T-A-1-01, T-A-1-02, T-A-1-03]
**blocks**: [T-A-2-01, T-B-2-01]
**Target files**:
- `services/portfolio/src/portfolio/infrastructure/db/models/brokerage_connection.py`
- `services/portfolio/src/portfolio/infrastructure/db/models/brokerage_sync_error.py`
- `services/portfolio/src/portfolio/infrastructure/db/models/__init__.py` (extend imports)
**PRD reference**: §6.4

**What to build**:
SQLAlchemy 2.x declarative ORM models aligned exactly with the DDL in §6.4. Use `Mapped[T]` annotation style consistent with existing models (see `models/portfolio.py`).

**Entities / Components**:
- **`BrokerageConnectionModel`** (`Base`)
  - `__tablename__ = "brokerage_connections"`
  - `id: Mapped[UUID]` — PK, `postgresql.UUID(as_uuid=True)`
  - `tenant_id: Mapped[UUID]` — NOT NULL, FK `tenants.id`
  - `user_id: Mapped[UUID]` — NOT NULL, FK `users.id`
  - `portfolio_id: Mapped[UUID]` — NOT NULL, FK `portfolios.id`
  - `snaptrade_user_id: Mapped[str]` — NOT NULL, TEXT
  - `snaptrade_user_secret: Mapped[str]` — NOT NULL, TEXT
  - `authorization_id: Mapped[str | None]` — nullable TEXT
  - `brokerage_name: Mapped[str | None]` — nullable TEXT
  - `status: Mapped[str]` — NOT NULL, VARCHAR(20), server_default `'pending'`
  - `snaptrade_tos_accepted_at: Mapped[datetime]` — NOT NULL, TIMESTAMPTZ
  - `last_synced_at: Mapped[datetime | None]` — nullable TIMESTAMPTZ
  - `last_sync_cursor: Mapped[str | None]` — nullable TEXT
  - `created_at: Mapped[datetime]` — NOT NULL, TIMESTAMPTZ, server_default `now()`
  - `updated_at: Mapped[datetime]` — NOT NULL, TIMESTAMPTZ, server_default `now()`
  - Indexes: `ix_brokerage_connections_user_status (user_id, status)`, `ix_brokerage_connections_tenant_id (tenant_id)`, `ix_brokerage_connections_portfolio_id (portfolio_id)`

- **`BrokerageTransactionSyncErrorModel`** (`Base`)
  - `__tablename__ = "brokerage_sync_errors"`
  - `id: Mapped[UUID]` — PK
  - `connection_id: Mapped[UUID]` — NOT NULL, FK `brokerage_connections.id`
  - `snaptrade_transaction_id: Mapped[str]` — NOT NULL, TEXT
  - `error_type: Mapped[str]` — NOT NULL, VARCHAR(50)
  - `error_detail: Mapped[str | None]` — nullable TEXT
  - `raw_transaction: Mapped[dict | None]` — nullable JSONB (`postgresql.JSONB`)
  - `created_at: Mapped[datetime]` — NOT NULL, TIMESTAMPTZ, server_default `now()`
  - `resolved_at: Mapped[datetime | None]` — nullable TIMESTAMPTZ
  - Indexes: `ix_brokerage_sync_errors_connection_created (connection_id, created_at DESC)`, `ix_brokerage_sync_errors_error_type (error_type)`

**Downstream test impact**:
- `services/portfolio/tests/` — Any DDL alignment test that scans ORM models will need updating if present (check `tests/integration/` for `TestDDLAlignment`-pattern tests)

**Acceptance criteria**:
- [ ] Both models importable from `portfolio.infrastructure.db.models`
- [ ] Column types, nullability, and defaults exactly match §6.4 DDL spec
- [ ] No `metadata` column name (BP-021)
- [ ] ruff + mypy pass

---

#### Validation Gate
- [x] `ruff check services/portfolio/src/portfolio/domain/ services/portfolio/src/portfolio/infrastructure/db/models/` passes
- [x] `mypy services/portfolio/src/portfolio/domain/ services/portfolio/src/portfolio/infrastructure/db/models/` passes
- [x] `python -m pytest services/portfolio/tests/ -m unit -k "brokerage" -v` — minimum 7 new tests pass (17 pass)
- [x] No domain entity imports infrastructure modules (CLAUDE.md Hard Rule — domain layer independence; not to be confused with RULES.md R12 which is the claim-check rule)

#### Regression Guardrails
- **BP-021**: No ORM column named `metadata` — check both new models before committing
- **BP-019**: ORM column types must exactly match the §6.4 DDL spec; the migration in Wave A-2 will be written from this model — any drift will cause `UndefinedColumnError` at runtime
- **BP-038**: Domain entity state transitions (`activate`, `disconnect`) must raise `DomainError` subclasses, not `assert`

---

### Wave A-2: Alembic Migration + Config + Dependency ✅

**Goal**: Create DB migration for the two new tables and extend S1 configuration with SnapTrade settings.
**Depends on**: Wave A-1 (ORM models must exist before generating migration)
**Estimated effort**: 30–45 minutes
**Status**: **DONE** — 2026-04-10 · 346 unit tests pass · ruff + mypy clean · migration round-trip verified
**Architecture layer**: infrastructure (DB migration) + config

#### Pre-read (agent must read before starting)
- `services/portfolio/alembic/versions/0005_add_tenant_id_to_holdings.py` (migration pattern)
- `services/portfolio/src/portfolio/config.py`
- `services/portfolio/pyproject.toml`

#### Tasks

---

##### T-A-2-01: Alembic migration 0006 — brokerage tables

**Type**: schema
**depends_on**: [T-A-1-04]
**blocks**: [T-B-2-01]
**Target files**: `services/portfolio/alembic/versions/0006_add_brokerage_tables.py`
**PRD reference**: §6.4, §12

**What to build**:
Alembic migration creating both tables with all columns, FK constraints, and indexes from §6.4. Use explicit `op.create_index` (not inline `Index`). Provide a working `downgrade()`.

**Logic & Behavior**:
- `upgrade()`: create `brokerage_connections` first (parent), then `brokerage_sync_errors` (FK child)
- `downgrade()`: drop `brokerage_sync_errors` first, then `brokerage_connections` (FK ordering)
- All columns from §6.4 with exact types, nullability, and `server_default` values
- `status` column: `VARCHAR(20)`, `server_default=sa.text("'pending'")`, NOT NULL
- `snaptrade_tos_accepted_at`: TIMESTAMPTZ, NOT NULL, **no server_default** (must be provided at insert time)
- `raw_transaction`: `postgresql.JSONB`, nullable

**Downstream test impact**:
- Any DDL alignment test in `services/portfolio/tests/` that expects a specific migration count

**Acceptance criteria**:
- [ ] `alembic upgrade head` runs without error against a clean `portfolio_db`
- [ ] `alembic downgrade -1` runs without error (rollback test)
- [ ] Migration revision chain: `0005 → 0006`
- [ ] All FK constraints reference correct parent tables

---

##### T-A-2-02: S1 config settings — SnapTrade + worker

**Type**: config
**depends_on**: none
**blocks**: [T-B-1-03, T-D-1-01]
**Target files**: `services/portfolio/src/portfolio/config.py`
**PRD reference**: §12, §4.3 F-23

**What to build**:
Extend `Settings` with SnapTrade credentials and worker configuration. Add `@model_validator` warning if `snaptrade_client_id` is empty (mirrors the pattern for `internal_service_token`).

**New settings** (all under `PORTFOLIO_` prefix due to `env_prefix="PORTFOLIO_"`):

Wait — the PRD §12 uses `SNAPTRADE_CLIENT_ID` (not prefixed with `PORTFOLIO_`). But the Settings class uses `env_prefix="PORTFOLIO_"`. The SnapTrade env vars need to be read WITHOUT the portfolio prefix (they're SnapTrade-specific). Use `model_config = SettingsConfigDict(..., env_prefix="PORTFOLIO_")` but define the snaptrade fields using `Field(alias="SNAPTRADE_CLIENT_ID")` OR use `extra="ignore"` with explicit `@field_validator`.

**Better approach**: Define snaptrade fields with explicit `validation_alias` from `pydantic`:
```python
snaptrade_client_id: str = Field(default="", validation_alias=AliasChoices("SNAPTRADE_CLIENT_ID", "PORTFOLIO_SNAPTRADE_CLIENT_ID"))
snaptrade_consumer_key: str = Field(default="", validation_alias=AliasChoices("SNAPTRADE_CONSUMER_KEY", "PORTFOLIO_SNAPTRADE_CONSUMER_KEY"))
snaptrade_redirect_uri: str = Field(default="http://localhost:5173/portfolio/brokerage/callback", validation_alias=AliasChoices("SNAPTRADE_REDIRECT_URI", "PORTFOLIO_SNAPTRADE_REDIRECT_URI"))
snaptrade_secret_encryption_key: str = Field(
    default="",
    validation_alias=AliasChoices("SNAPTRADE_SECRET_ENCRYPTION_KEY", "PORTFOLIO_SNAPTRADE_SECRET_ENCRYPTION_KEY"),
)
brokerage_sync_cycle_seconds: int = 14400
brokerage_sync_history_days: int = 730
```

**Logic**: Add `@model_validator(mode="after")` with TWO structlog warnings (mirrors `_warn_missing_internal_token`):
1. If `snaptrade_client_id` is empty — existing warning
2. If `snaptrade_secret_encryption_key` is empty — new warning: "SNAPTRADE_SECRET_ENCRYPTION_KEY is not set — snaptrade_user_secret will be stored in plaintext. Generate a key with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""

**Acceptance criteria**:
- [ ] All 5 new settings have sensible defaults
- [ ] `snaptrade_client_id` empty triggers structlog warning (not exception — startup must succeed)
- [ ] ruff + mypy pass

---

##### T-A-2-03: Add snaptrade-python-sdk to pyproject.toml

**Type**: config
**depends_on**: none
**blocks**: [T-B-1-03]
**Target files**: `services/portfolio/pyproject.toml`
**PRD reference**: §4.3 F-20, §12

**What to build**:
Add `snaptrade-python-sdk` as a dependency. Pin to a specific minor version to prevent silent API breakage (PRD §9 failure mode: "SnapTrade changes API").

**Logic**: Add to `[project] dependencies`:
```
"snaptrade-python-sdk>=1.0,<2",  # pinned: SnapTrade SDK — update only with migration guide review
"cryptography>=42.0,<43",        # Fernet encryption for snaptrade_user_secret at rest (AD-3)
```
Check PyPI for latest stable version before pinning. Note: `cryptography` may already be a transitive dependency (asyncpg/SQLAlchemy use it for TLS); verify before adding to avoid duplicate pins.

**Acceptance criteria**:
- [ ] `pyproject.toml` has `snaptrade-python-sdk` in dependencies
- [ ] `pip install -e .` succeeds from `services/portfolio/`

---

#### Validation Gate
- [x] `alembic upgrade head` + `alembic downgrade -1` + `alembic upgrade head` (round-trip) passes
- [x] `ruff check services/portfolio/src/portfolio/config.py` passes
- [x] `mypy services/portfolio/src/portfolio/config.py` passes
- [x] `python -m pytest services/portfolio/tests/ -m unit -v` — all existing tests still pass

#### Regression Guardrails
- **BP-008**: Migration DDL must exactly match ORM model columns — cross-check `BrokerageConnectionModel` columns against the `CREATE TABLE` in `upgrade()` before committing
- **BP-019**: Migration column types must match ORM (`TIMESTAMPTZ` for all datetime columns, `UUID(as_uuid=True)` for UUID columns, `JSONB` for `raw_transaction`)
- **BP-126**: All NOT NULL columns without `server_default` (`snaptrade_tos_accepted_at`, `tenant_id`, `user_id`, `portfolio_id`, `snaptrade_user_id`, `snaptrade_user_secret`) must be provided at INSERT time — no `server_default` shortcut on these. Don't add `server_default=null` workaround.


---

## Sub-plan B: S1 Infrastructure

### Wave B-1: IBrokerageClient Port + SnapTradeClient Adapter ✅

**Goal**: Define the brokerage client abstraction (port) and implement the real SnapTrade SDK adapter. This enables dependency injection in tests (use `FakeBrokerageClient`).
**Depends on**: Wave A-2 (config + SDK dependency installed)
**Estimated effort**: 45–75 minutes
**Status**: **DONE** — 2026-04-10 · 361 unit tests pass (15 new) · ruff + mypy clean
**Architecture layer**: application/ports + infrastructure/brokerage

#### Pre-read (agent must read before starting)
- `services/portfolio/src/portfolio/application/ports/repositories.py` (port pattern)
- `services/portfolio/src/portfolio/config.py` (after Wave A-2 — to see new snaptrade fields)
- `services/portfolio/src/portfolio/infrastructure/db/repositories/instrument.py` (infra adapter pattern)

#### Tasks

---

##### T-B-1-01: IBrokerageClient port + SnapTrade value objects

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-B-1-03, T-C-1-01]
**Target files**: `services/portfolio/src/portfolio/application/ports/brokerage_client.py`
**PRD reference**: §6.5 (SnapTradeClient infra)

**What to build**:
Define the `IBrokerageClient` Protocol (port interface) and two value objects used for passing data across the adapter boundary.

**Entities / Components**:

- **`SnapTradeUser`** (frozen `@dataclass`)
  - `snaptrade_user_id: str`
  - `snaptrade_user_secret: str` — never log; override `__repr__` to redact

- **`SnapTradeActivity`** (frozen `@dataclass`)
  - `snaptrade_transaction_id: str` — unique ID from SnapTrade
  - `activity_type: str` — raw type string from SnapTrade (e.g. "BUY", "SELL", "DIV", "OPTION_*")
  - `symbol: str` — ticker symbol
  - `quantity: Decimal`
  - `price: Decimal`
  - `currency: str` — e.g. "USD"
  - `executed_at: datetime` — UTC-aware
  - `brokerage_name: str | None` — brokerage display name if available

- **`IBrokerageClient`** (Protocol)
  - `async def register_user(self, user_id_hint: str) -> SnapTradeUser: ...`
    — Calls SnapTrade `POST /snapTrade/registerUser`; returns `SnapTradeUser` with user_id and secret
  - `async def generate_portal_url(self, user: SnapTradeUser, redirect_uri: str) -> str: ...`
    — Calls `POST /authorizations/loginSnapTradeUser` with `connectionType=read`; returns redirect URL
  - `async def revoke_authorization(self, user: SnapTradeUser, authorization_id: str) -> None: ...`
    — Calls `DELETE /authorizations/{authorizationId}`
  - `async def get_activities(self, user: SnapTradeUser, start: date, end: date) -> list[SnapTradeActivity]: ...`
    — Calls `GET /accounts/{userId}/activities`

**Acceptance criteria**:
- [ ] `IBrokerageClient` is a `typing.Protocol` with `runtime_checkable=True`
- [ ] `SnapTradeUser.__repr__` redacts `snaptrade_user_secret`
- [ ] All types imported from domain layer only (no infra imports in application ports)
- [ ] ruff + mypy pass

---

##### T-B-1-02: FakeBrokerageClient for tests

**Type**: impl
**depends_on**: [T-B-1-01]
**blocks**: [T-C-1-01, T-E-1-01]
**Target files**: `services/portfolio/tests/unit/fakes/fake_brokerage_client.py`
**PRD reference**: §11 (unit test strategy)

**What to build**:
An in-memory implementation of `IBrokerageClient` for unit and integration tests. Stores state in lists; configurable to raise errors.

**Entities / Components**:
- **`FakeBrokerageClient`**
  - `register_user_result: SnapTradeUser` — pre-set return value (constructor arg)
  - `portal_url: str = "https://fake-snaptrade.example.com/connect"` — pre-set portal URL returned by `generate_portal_url`
  - `activities: list[SnapTradeActivity] = []` — activities to return from `get_activities`
  - `revoke_calls: list[tuple[SnapTradeUser, str]] = []` — records (user, auth_id) pairs from `revoke_authorization`
  - `register_calls: list[str] = []` — records user_id_hint values from `register_user`
  - `portal_url_calls: list[str] = []` — records the `redirect_uri` string passed to `generate_portal_url` (used by `test_initiate_connection_type_is_always_read` to verify `connectionId` is embedded and `connectionType` is NOT user-supplied)
  - `should_raise_on_revoke: bool = False` — if True, `revoke_authorization` raises `BrokerageApiError`
  - `should_raise_on_activities: bool = False` — if True, `get_activities` raises `BrokerageApiError`
  - All methods must be `async`

**Tests to write**:
(Tests using this fake are in Wave E-1 — no tests in this task itself)

**Acceptance criteria**:
- [ ] `FakeBrokerageClient` satisfies `IBrokerageClient` Protocol (runtime_checkable check)
- [ ] ruff + mypy pass

---

##### T-B-1-03: SnapTradeClient infrastructure adapter

**Type**: impl
**depends_on**: [T-B-1-01, T-A-2-02, T-A-2-03]
**blocks**: [T-C-1-01]
**Target files**:
- `services/portfolio/src/portfolio/infrastructure/brokerage/__init__.py`
- `services/portfolio/src/portfolio/infrastructure/brokerage/snaptrade_client.py`
**PRD reference**: §6.5 (SnapTradeClient), §4.3 F-19/F-20

**What to build**:
Wraps `snaptrade-python-sdk` to implement `IBrokerageClient`. All SnapTrade SDK calls are async (`asyncio.run_in_executor` for sync SDK methods — check if SDK provides async variants; if not, use executor).

**Logic & Behavior**:
1. Constructor: `__init__(self, client_id: str, consumer_key: str)` — instantiates `SnapTrade(client_id=..., consumer_key=...)`
2. `register_user(user_id_hint)`:
   - Calls `self._client.authentication.register_snap_trade_user(body={"userId": user_id_hint})`
   - Returns `SnapTradeUser(snaptrade_user_id=..., snaptrade_user_secret=...)`
   - **NEVER log the returned secret**
3. `generate_portal_url(user, redirect_uri)`:
   - Calls `self._client.authentication.login_snap_trade_user(body={"userId": user.snaptrade_user_id, "userSecret": user.snaptrade_user_secret, "connectionType": "read"})`
   - Returns the `redirectURI` string
   - `connectionType="read"` is HARDCODED — not a parameter (F-22)
4. `revoke_authorization(user, authorization_id)`:
   - Calls `self._client.connections.remove_brokerage_authorization(authorization_id=authorization_id, user_id=user.snaptrade_user_id, user_secret=user.snaptrade_user_secret)`
5. `get_activities(user, start, end)`:
   - Calls `self._client.transactions_and_reporting.get_activities(user_id=..., user_secret=..., start_date=start.isoformat(), end_date=end.isoformat())`
   - Maps each item to `SnapTradeActivity` (see type mapping §6.5)
   - **NEVER log raw API response** (may contain account balance/details)
   - If SDK raises an exception, wrap in `BrokerageApiError` (new error class in domain/errors.py)

**Security invariants**:
- All try/except blocks catch `Exception` to prevent secret leakage in tracebacks
- Log context: bind only `connection_id`, `brokerage_name`, `user_id` — never `snaptrade_user_secret`

**Note**: `BrokerageApiError` is defined in T-A-1-03 (domain errors task) — import from `portfolio.domain.errors`. Do NOT define new domain errors in this infrastructure task.

**Acceptance criteria**:
- [ ] `SnapTradeClient` implements `IBrokerageClient`
- [ ] `connectionType="read"` is hardcoded, not parameterized
- [ ] No `snaptrade_user_secret` appears in any structlog call within the adapter
- [ ] SDK calls wrapped in try/except catching `Exception`
- [ ] ruff + mypy pass

---

#### Validation Gate
- [x] `ruff check services/portfolio/src/portfolio/application/ports/brokerage_client.py services/portfolio/src/portfolio/infrastructure/brokerage/` passes
- [x] `mypy services/portfolio/src/portfolio/application/ports/brokerage_client.py services/portfolio/src/portfolio/infrastructure/brokerage/` passes
- [x] `isinstance(FakeBrokerageClient(...), IBrokerageClient)` is True (Protocol check — assertion in fakes.py fires at import)
- [x] No infrastructure imports in `application/ports/brokerage_client.py` (R12)

#### Regression Guardrails
- **BP-100**: SDK method names verified against snaptrade-python-sdk==1.0.1 (NOT the high-level `SnapTrade` class the plan assumed — SDK is low-level `ApiClient` + per-resource API objects). Actual methods: `snap_trade_register_user_post`, `snap_trade_login_post`, `authorizations_authorization_id_delete`, `activities_get`.
- **BP-025**: SnapTrade SDK calls are synchronous (non-async) — must use `asyncio.run_in_executor(None, ...)` to prevent blocking the event loop
- **BP-057**: Do not hold a DB session while calling SnapTrade API — the adapter receives no session; the calling use case must commit/close DB session before invoking the adapter

---

### Wave B-2: Brokerage Repositories + UoW Extension ✅

**Goal**: Implement repository ports and SQLAlchemy implementations for both new tables, and extend the UnitOfWork.
**Depends on**: Wave A-2 (ORM models + migration exist)
**Estimated effort**: 45–60 minutes
**Status**: **DONE** — 2026-04-11 · 401 unit tests pass · ruff + mypy clean
**Architecture layer**: application/ports + infrastructure/db/repositories

#### Pre-read (agent must read before starting)
- `services/portfolio/src/portfolio/application/ports/repositories.py`
- `services/portfolio/src/portfolio/application/ports/unit_of_work.py`
- `services/portfolio/src/portfolio/infrastructure/db/repositories/transaction.py` (repo pattern)
- `services/portfolio/src/portfolio/infrastructure/db/unit_of_work.py`

#### Tasks

---

##### T-B-2-01: Repository port ABCs

**Type**: impl
**depends_on**: [T-A-1-02, T-A-1-03]
**blocks**: [T-B-2-02, T-B-2-03, T-B-2-04]
**Target files**: `services/portfolio/src/portfolio/application/ports/repositories.py` (extend)
**PRD reference**: §6.5

**What to build**:
Append two new `ABC` repository interfaces to the existing `repositories.py`.

**Entities / Components**:

- **`BrokerageConnectionRepository(ABC)`**
  - `async def get(self, connection_id: UUID, tenant_id: UUID) -> BrokerageConnection | None`
  - `async def get_by_user(self, connection_id: UUID, user_id: UUID, tenant_id: UUID) -> BrokerageConnection | None` — ownership check
  - `async def list_by_user(self, user_id: UUID, tenant_id: UUID, portfolio_id: UUID | None = None) -> list[BrokerageConnection]`
  - `async def list_active_or_error(self) -> list[BrokerageConnection]` — for worker: WHERE status IN ('active','error')
  - `async def save(self, connection: BrokerageConnection) -> None` — INSERT or UPDATE

- **`BrokerageTransactionSyncErrorRepository(ABC)`**
  - `async def save(self, error: BrokerageTransactionSyncError) -> None`
  - `async def list_by_connection(self, connection_id: UUID, limit: int = 50) -> list[BrokerageTransactionSyncError]`

**Acceptance criteria**:
- [ ] Both ABCs use `TYPE_CHECKING` for entity imports (no circular dependency)
- [ ] ruff + mypy pass

---

##### T-B-2-02: SqlAlchemy brokerage connection repository

**Type**: impl
**depends_on**: [T-A-1-04, T-B-2-01]
**blocks**: [T-B-2-04]
**Target files**: `services/portfolio/src/portfolio/infrastructure/db/repositories/brokerage_connection.py`
**PRD reference**: §6.5

**What to build**:
SQLAlchemy implementation of `BrokerageConnectionRepository`. Uses the session passed at construction (standard pattern — see `transaction.py`).

**Logic & Behavior**:
- `get()`: `SELECT * FROM brokerage_connections WHERE id = :id AND tenant_id = :tenant_id`
- `get_by_user()`: adds `AND user_id = :user_id` — prevents tenant cross-contamination
- `list_by_user()`: `WHERE user_id = :user_id AND tenant_id = :tenant_id` + optional `AND portfolio_id = :portfolio_id`; ordered by `created_at DESC`
- `list_active_or_error()`: `WHERE status IN ('active', 'error')` — no tenant filter (worker processes all tenants)
- `save()`: `INSERT ... ON CONFLICT (id) DO UPDATE SET status=..., authorization_id=..., brokerage_name=..., last_synced_at=..., last_sync_cursor=..., updated_at=now()`

**ORM→Domain mapping** (`_to_entity`):
Construct `BrokerageConnection` from `BrokerageConnectionModel`; map `status` string → `ConnectionStatus` enum.

**Encryption of `snaptrade_user_secret`** (AD-3 — privacy requirement):
- The repository constructor accepts `cipher: Fernet | None` (passed from `SqlAlchemyUnitOfWork`)
- `save()`: if `cipher` is set, call `cipher.encrypt(connection.snaptrade_user_secret.encode()).decode()` and store the ciphertext; otherwise store plaintext (dev mode with empty key)
- `_to_entity()`: if `cipher` is set, call `cipher.decrypt(model.snaptrade_user_secret.encode()).decode()` to return the plaintext secret; otherwise return the value as-is
- **NEVER** log the encryption key or the decrypted secret value

```python
# Pattern for safe degraded mode:
def _encrypt(self, plaintext: str) -> str:
    return self._cipher.encrypt(plaintext.encode()).decode() if self._cipher else plaintext

def _decrypt(self, ciphertext: str) -> str:
    return self._cipher.decrypt(ciphertext.encode()).decode() if self._cipher else ciphertext
```

**Acceptance criteria**:
- [ ] All 5 methods implemented
- [ ] `save()` uses upsert, not plain INSERT (re-entrant)
- [ ] `save()` encrypts `snaptrade_user_secret` when cipher is set
- [ ] `_to_entity()` decrypts `snaptrade_user_secret` when cipher is set
- [ ] Unit test: save+load round-trip preserves the original plaintext secret
- [ ] ruff + mypy pass

---

##### T-B-2-03: SqlAlchemy sync error repository

**Type**: impl
**depends_on**: [T-A-1-04, T-B-2-01]
**blocks**: [T-B-2-04]
**Target files**: `services/portfolio/src/portfolio/infrastructure/db/repositories/brokerage_sync_error.py`
**PRD reference**: §6.5

**What to build**:
SQLAlchemy implementation of `BrokerageTransactionSyncErrorRepository`.

**Logic & Behavior**:
- `save()`: plain `INSERT` (sync errors are immutable once written; no upsert needed)
- `list_by_connection()`: `WHERE connection_id = :id ORDER BY created_at DESC LIMIT :limit`

**Acceptance criteria**:
- [ ] Both methods implemented
- [ ] ruff + mypy pass

---

##### T-B-2-04: Extend UnitOfWork + SqlAlchemyUnitOfWork

**Type**: impl
**depends_on**: [T-B-2-01, T-B-2-02, T-B-2-03]
**blocks**: [T-C-1-01]
**Target files**:
- `services/portfolio/src/portfolio/application/ports/unit_of_work.py`
- `services/portfolio/src/portfolio/infrastructure/db/unit_of_work.py`
**PRD reference**: §6.5

**What to build**:
Add two abstract properties to `UnitOfWork` ABC and wire their concrete implementations in `SqlAlchemyUnitOfWork`.

**Changes to `UnitOfWork` ABC**:
```python
@property
@abstractmethod
def brokerage_connections(self) -> BrokerageConnectionRepository: ...

@property
@abstractmethod
def brokerage_sync_errors(self) -> BrokerageTransactionSyncErrorRepository: ...
```

**Changes to `SqlAlchemyUnitOfWork`**:
- Add `_brokerage_connections: SqlAlchemyBrokerageConnectionRepository | None = None`
- Add `_brokerage_sync_errors: SqlAlchemyBrokerageTransactionSyncErrorRepository | None = None`
- Accept `snaptrade_cipher: Fernet | None = None` in `__init__` (passed from `app.py` lifespan via `SnapTradeCipher` helper)
- Initialize brokerage repos in `__aenter__`, passing `cipher=self._snaptrade_cipher` to `SqlAlchemyBrokerageConnectionRepository`
- Add concrete `@property` implementations
- **`app.py` wiring**: In `lifespan()`, construct `cipher = Fernet(settings.snaptrade_secret_encryption_key.encode()) if settings.snaptrade_secret_encryption_key else None` and pass it to `SqlAlchemyUnitOfWork` factory

**Acceptance criteria**:
- [ ] `UnitOfWork` ABC has two new abstract properties
- [ ] `SqlAlchemyUnitOfWork` initializes both repos in `__aenter__`
- [ ] `snaptrade_cipher` is threaded to `SqlAlchemyBrokerageConnectionRepository` (not to `SqlAlchemyBrokerageTransactionSyncErrorRepository` — sync errors are not encrypted)
- [ ] ruff + mypy pass (mypy will catch if abstract methods not implemented)

---

#### Validation Gate
- [x] `ruff check services/portfolio/src/portfolio/application/ports/ services/portfolio/src/portfolio/infrastructure/db/repositories/brokerage*.py services/portfolio/src/portfolio/infrastructure/db/unit_of_work.py` passes
- [x] `mypy services/portfolio/src/portfolio/` passes (UoW abstract methods fully satisfied)
- [x] `python -m pytest services/portfolio/tests/ -m unit -v` — all existing tests pass (401 pass, no regressions from UoW extension)

#### Regression Guardrails
- **BP-032**: `save()` in `BrokerageConnectionRepository` uses `ON CONFLICT (id) DO UPDATE ... RETURNING` — verify the upsert returns the persisted entity
- **BP-076**: If any raw SQL uses `:param::type` cast syntax, replace with `cast(:param AS type)` (asyncpg incompatibility)
- **BP-019**: `_to_entity` mapping must cover all columns including `updated_at` — stale ORM state after upsert is prevented by explicit `RETURNING` or session refresh
- **Privacy (AD-3)**: `save()` MUST encrypt `snaptrade_user_secret` via Fernet before writing to DB; `_to_entity()` MUST decrypt after reading. Run a save+load round-trip test to confirm the plaintext is preserved. Never store raw plaintext in the DB when the cipher is configured.

---

## Sub-plan C: S1 Application + API

### Wave C-1: Use Cases (5) ✅

**Goal**: Implement all 5 brokerage connection use cases following the hexagonal pattern.
**Depends on**: Wave B-1 + Wave B-2 (ports and adapters available)
**Estimated effort**: 60–90 minutes
**Status**: **DONE** — 2026-04-11 · 23 new tests pass (424 unit total) · ruff + mypy clean
**Architecture layer**: application/use_cases

#### Pre-read (agent must read before starting)
- `services/portfolio/src/portfolio/application/use_cases/create_portfolio.py` (use case command/result pattern)
- `services/portfolio/src/portfolio/application/use_cases/record_transaction.py` (complex use case pattern)
- `services/portfolio/src/portfolio/application/ports/unit_of_work.py` (after B-2 extension)
- `services/portfolio/src/portfolio/application/ports/brokerage_client.py` (IBrokerageClient)

#### Tasks

---

##### T-C-1-01: InitiateBrokerageConnectionUseCase

**Type**: impl
**depends_on**: [T-B-1-01, T-B-2-04]
**blocks**: [T-C-2-01]
**Target files**: `services/portfolio/src/portfolio/application/use_cases/brokerage_connection.py`
**PRD reference**: §6.2 (POST /api/v1/brokerage-connections), §6.5, §4.1 F-01..F-05

**What to build**:
Create the file `brokerage_connection.py` containing all 5 use case classes. Start with `InitiateBrokerageConnectionUseCase`.

**Command/Result**:
```python
@dataclass
class InitiateBrokerageConnectionCommand:
    tenant_id: UUID
    user_id: UUID
    portfolio_id: UUID
    snaptrade_tos_accepted: bool  # must be True or TosNotAcceptedError

@dataclass
class InitiateBrokerageConnectionResult:
    connection_id: UUID
    redirect_uri: str
```

**Logic & Behavior**:
1. Check `cmd.snaptrade_tos_accepted is True` → raise `TosNotAcceptedError` if False
2. Load portfolio via `uow.portfolios.get(cmd.portfolio_id, cmd.tenant_id)` → raise `PortfolioNotFoundError` if None or tenant_id mismatch
3. Call `brokerage_client.register_user(user_id_hint=str(cmd.user_id))` → `SnapTradeUser`
4. Call `brokerage_client.generate_portal_url(user=snaptrade_user, redirect_uri=f"{settings.snaptrade_redirect_uri}?connectionId={connection_pending_id}")` → `redirect_uri`
   — Embedding `connectionId` in the redirect URI ensures SnapTrade appends it to its outbound redirect alongside `authorizationId`/`userId`/`sessionId`, letting the frontend callback page route back to this specific connection (PRD §6.7 data flow fix R-004)
5. Create `BrokerageConnection(id=connection_pending_id, ..., status=PENDING, snaptrade_tos_accepted_at=utc_now())`
   — `connection_pending_id = new_uuid7()` must be generated BEFORE step 4 so it can be embedded in the redirect URI
6. `await uow.brokerage_connections.save(connection)`
7. `await uow.commit()`
8. Return `InitiateBrokerageConnectionResult(connection_id=connection.id, redirect_uri=redirect_uri)`

**Error classification**:
- `TosNotAcceptedError` → 422 (use case layer raises; API maps)
- `PortfolioNotFoundError` → 400
- `BrokerageApiError` → 503 (SnapTrade unavailable)

**Acceptance criteria**:
- [ ] ToS not accepted → `TosNotAcceptedError` raised before any SnapTrade call
- [ ] `connectionType=read` is server-side only — not in command
- [ ] `snaptrade_user_secret` never passed to structlog

---

##### T-C-1-02: ActivateBrokerageConnectionUseCase

**Type**: impl
**depends_on**: [T-C-1-01]
**blocks**: [T-C-2-01]
**Target files**: `services/portfolio/src/portfolio/application/use_cases/brokerage_connection.py` (append)
**PRD reference**: §6.2 (GET /api/v1/brokerage-connections/{id}/callback), §6.7

**Command/Result**:
```python
@dataclass
class ActivateBrokerageConnectionCommand:
    connection_id: UUID
    user_id: UUID
    tenant_id: UUID
    snaptrade_user_id: str  # from SnapTrade callback param "userId"
    authorization_id: str   # from SnapTrade callback param "authorizationId"

@dataclass
class ActivateBrokerageConnectionResult:
    connection_id: UUID
    status: str  # "active"
```

**Logic & Behavior**:
1. Load connection via `uow.brokerage_connections.get_by_user(cmd.connection_id, cmd.user_id, cmd.tenant_id)` → raise `BrokerageConnectionNotFoundError` if None
2. Validate `cmd.snaptrade_user_id == connection.snaptrade_user_id` → raise `BrokerageConnectionForbiddenError` if mismatch (prevents callback spoofing)
3. Call `connection.activate(authorization_id=cmd.authorization_id)` → raises `BrokerageConnectionStateError` if not PENDING
4. `await uow.brokerage_connections.save(connection)`
5. `await uow.commit()`
6. Return `ActivateBrokerageConnectionResult(connection_id=connection.id, status="active")`

---

##### T-C-1-03: ListBrokerageConnectionsUseCase

**Type**: impl
**depends_on**: [T-C-1-01]
**blocks**: [T-C-2-01]
**Target files**: `services/portfolio/src/portfolio/application/use_cases/brokerage_connection.py` (append)
**PRD reference**: §6.2 (GET /api/v1/brokerage-connections)

**Command/Result**:
```python
@dataclass
class ListBrokerageConnectionsQuery:
    user_id: UUID
    tenant_id: UUID
    portfolio_id: UUID | None = None

@dataclass
class ListBrokerageConnectionsResult:
    items: list[BrokerageConnection]
```

**Logic**: `uow.brokerage_connections.list_by_user(...)` → return result. Uses `ReadOnlyUnitOfWork` (R27 — this is a read-only use case).

**Note on R27 compliance**: `ListBrokerageConnectionsUseCase` must accept `UnitOfWork` (not hard-coupled to `ReadOnlyUnitOfWork`) — the dependency is injected from the API layer which uses `ReadUoWDep`. The use case ABC doesn't enforce this.

---

##### T-C-1-04: DisconnectBrokerageConnectionUseCase

**Type**: impl
**depends_on**: [T-C-1-01]
**blocks**: [T-C-2-01]
**Target files**: `services/portfolio/src/portfolio/application/use_cases/brokerage_connection.py` (append)
**PRD reference**: §6.2 (DELETE /api/v1/brokerage-connections/{id}), §4.1 F-07/F-08

**Command/Result**:
```python
@dataclass
class DisconnectBrokerageConnectionCommand:
    connection_id: UUID
    user_id: UUID
    tenant_id: UUID

@dataclass
class DisconnectBrokerageConnectionResult:
    status: str  # "disconnected"
```

**Logic & Behavior**:
1. Load connection via `uow.brokerage_connections.get_by_user(...)` → `BrokerageConnectionNotFoundError` if None
2. If `connection.authorization_id` is set: call `brokerage_client.revoke_authorization(user, connection.authorization_id)` (catch `BrokerageApiError` — log warning but continue; still mark disconnected)
3. Call `connection.disconnect()` → raises `BrokerageConnectionAlreadyDisconnectedError` if already disconnected
4. `await uow.brokerage_connections.save(connection)`
5. `await uow.commit()`
6. **Does NOT delete transactions or holdings** (F-08)

---

##### T-C-1-05: GetSyncErrorsUseCase

**Type**: impl
**depends_on**: [T-C-1-01]
**blocks**: [T-C-2-01]
**Target files**: `services/portfolio/src/portfolio/application/use_cases/brokerage_connection.py` (append)
**PRD reference**: §4.2 F-18, §11

**Command/Result**:
```python
@dataclass
class GetSyncErrorsQuery:
    connection_id: UUID
    user_id: UUID
    tenant_id: UUID
    limit: int = 50

@dataclass
class GetSyncErrorsResult:
    items: list[BrokerageTransactionSyncError]
```

**Logic**:
1. Verify ownership: `uow.brokerage_connections.get_by_user(connection_id, user_id, tenant_id)` → `BrokerageConnectionNotFoundError` if None
2. `uow.brokerage_sync_errors.list_by_connection(connection_id, limit=query.limit)`
3. Return result — read-only use case, uses `ReadUoWDep` at API layer

---

#### Validation Gate
- [x] `ruff check services/portfolio/src/portfolio/application/use_cases/brokerage_connection.py` passes
- [x] `mypy services/portfolio/src/portfolio/application/use_cases/brokerage_connection.py` passes
- [x] No infrastructure imports in use case file (R12, R16)
- [x] `python -m pytest services/portfolio/tests/ -m unit -v` — all existing tests pass (424 pass)

#### Regression Guardrails
- **BP-038**: Use `if not cmd.snaptrade_tos_accepted:` not `assert cmd.snaptrade_tos_accepted` — assertions are stripped with `-O`
- **BP-057**: SnapTrade API calls in `Initiate` and `Disconnect` must happen BEFORE `uow.commit()` — so if the API call fails, no connection row is committed. Pattern: call API → create entity → `uow.save()` → `uow.commit()`

---

### Wave C-2: S1 API Routes + Wiring

**Goal**: Expose the 4 API endpoints for brokerage connections and wire everything into the S1 FastAPI app.
**Depends on**: Wave C-1 (use cases complete)
**Estimated effort**: 45–75 minutes
**Architecture layer**: API

#### Pre-read (agent must read before starting)
- `services/portfolio/src/portfolio/api/routes/portfolio.py` (route pattern)
- `services/portfolio/src/portfolio/api/schemas.py` (Pydantic schema pattern)
- `services/portfolio/src/portfolio/api/dependencies.py`
- `services/portfolio/src/portfolio/api/error_mapping.py`
- `services/portfolio/src/portfolio/app.py`

#### Tasks

---

##### T-C-2-01: Pydantic request/response schemas

**Type**: impl
**depends_on**: [T-C-1-01]
**blocks**: [T-C-2-02]
**Target files**: `services/portfolio/src/portfolio/api/schemas.py` (extend)
**PRD reference**: §6.2

**What to build**:
Append brokerage connection schemas to `schemas.py`. Follow existing schema conventions (Pydantic v2, `model_config = ConfigDict(from_attributes=True)` for response models).

**New schemas**:

- **`InitiateBrokerageConnectionRequest`** (request body for POST)
  - `portfolio_id: UUID`
  - `snaptrade_tos_accepted: bool`
  - Validator: `snaptrade_tos_accepted` must be `True` (pydantic `@field_validator` with message "You must accept SnapTrade's End User Terms of Service")

- **`InitiateBrokerageConnectionResponse`** (201 response)
  - `connection_id: UUID`
  - `redirect_uri: str`

- **`BrokerageConnectionResponse`** (list item)
  - `connection_id: UUID`
  - `portfolio_id: UUID`
  - `brokerage_name: str | None`
  - `status: str` — one of `pending/active/error/disconnected`
  - `last_synced_at: datetime | None`
  - `created_at: datetime`

- **`ListBrokerageConnectionsResponse`**
  - `items: list[BrokerageConnectionResponse]`

- **`ActivateBrokerageConnectionResponse`**
  - `status: str`
  - `connection_id: UUID`

- **`DisconnectBrokerageConnectionResponse`**
  - `status: str`  — `"disconnected"`

- **`SyncErrorResponse`**
  - `id: UUID`
  - `connection_id: UUID`
  - `snaptrade_transaction_id: str`
  - `error_type: str`
  - `error_detail: str | None`
  - `created_at: datetime`

- **`GetSyncErrorsResponse`**
  - `items: list[SyncErrorResponse]`

**Acceptance criteria**:
- [ ] All schemas use Pydantic v2 style (no `class Config`)
- [ ] `snaptrade_tos_accepted` validator raises `ValueError` if False (maps to 422)
- [ ] ruff + mypy pass

---

##### T-C-2-02: API router for brokerage connections

**Type**: impl
**depends_on**: [T-C-2-01, T-C-1-01]
**blocks**: [T-C-2-03]
**Target files**: `services/portfolio/src/portfolio/api/routes/brokerage_connections.py`
**PRD reference**: §6.2

**What to build**:
FastAPI router with 4 endpoints. All routes require authentication (JWT via S9 injects `X-User-Id`, `X-Tenant-Id`). Use existing `UoWDep`/`ReadUoWDep` injection.

**Routes**:

1. **`POST /api/v1/brokerage-connections`** (status_code=201)
   - Body: `InitiateBrokerageConnectionRequest`
   - Extract `user_id` from `X-User-Id` header, `tenant_id` from `X-Tenant-Id` header
   - Instantiate `InitiateBrokerageConnectionUseCase`
   - Inject `IBrokerageClient` from `request.app.state.brokerage_client`
   - Uses `UoWDep` (write)
   - Returns `InitiateBrokerageConnectionResponse`

2. **`GET /api/v1/brokerage-connections`** (status_code=200)
   - Query param: `portfolio_id: UUID | None = None`
   - Uses `ReadUoWDep`
   - Returns `ListBrokerageConnectionsResponse`

3. **`DELETE /api/v1/brokerage-connections/{connection_id}`** (status_code=200)
   - Path param: `connection_id: UUID`
   - Uses `UoWDep` (write — calls SnapTrade API)
   - Returns `DisconnectBrokerageConnectionResponse`

4. **`GET /api/v1/brokerage-connections/{connection_id}/callback`** (status_code=200)
   - Path params: `connection_id: UUID`
   - Query params: `authorizationId: str`, `userId: str`, `sessionId: str`
   - Uses `UoWDep` (write — updates status)
   - Returns `ActivateBrokerageConnectionResponse`

5. **`GET /api/v1/brokerage-connections/{connection_id}/sync-errors`** (status_code=200)
   - Path param: `connection_id: UUID`
   - Query param: `limit: int = 50` (1–200)
   - Uses `ReadUoWDep` (read-only — R27)
   - Returns `GetSyncErrorsResponse`
   - **Privacy**: `SyncErrorResponse` must NEVER include a `raw_transaction` field — add a comment in the schema class as a permanent guard: `# raw_transaction intentionally excluded — contains sensitive brokerage data (see PRD §6.4 privacy note)`
   - **Future**: `resolved_at` is also excluded from `SyncErrorResponse` until an `AcknowledgeSyncError` use case is added that actually sets it — add a comment: `# resolved_at excluded: no code path in this plan sets it (reserved for future AcknowledgeSyncError use case)`

**Header extraction helper** (reuse pattern from `internal.py`):
```python
def _require_user_headers(request: Request) -> tuple[UUID, UUID]:
    user_id_str = request.headers.get("X-User-Id")
    tenant_id_str = request.headers.get("X-Tenant-Id")
    if not user_id_str or not tenant_id_str:
        raise HTTPException(status_code=401, detail="Missing auth headers")
    return UUID(user_id_str), UUID(tenant_id_str)
```

**Acceptance criteria**:
- [ ] All 5 routes implemented with correct HTTP status codes
- [ ] No direct infrastructure imports in router (R16 / R25)
- [ ] `IBrokerageClient` injected from `app.state`, not instantiated inline
- [ ] `SyncErrorResponse` schema has comments marking `raw_transaction` and `resolved_at` as intentionally excluded
- [ ] ruff + mypy pass

---

##### T-C-2-03: Wire brokerage router into app.py + error mapping

**Type**: impl
**depends_on**: [T-C-2-02]
**blocks**: [T-D-2-01]
**Target files**:
- `services/portfolio/src/portfolio/app.py`
- `services/portfolio/src/portfolio/api/error_mapping.py`
**PRD reference**: §6.1, §4.3 F-23

**What to build**:
Register the brokerage connections router in FastAPI app, instantiate `SnapTradeClient` in lifespan and attach to `app.state.brokerage_client`, and map new domain errors to HTTP status codes.

**app.py changes**:
- In `lifespan()`: add `app.state.brokerage_client = SnapTradeClient(client_id=settings.snaptrade_client_id, consumer_key=settings.snaptrade_consumer_key)`
- Import and include `brokerage_connections_router` with prefix `/api`

**error_mapping.py changes** (extend existing error→HTTP dict):
```python
TosNotAcceptedError: 422,
BrokerageConnectionNotFoundError: 404,
BrokerageConnectionForbiddenError: 403,
BrokerageConnectionStateError: 422,
BrokerageConnectionAlreadyDisconnectedError: 422,
BrokerageApiError: 503,
```

**Acceptance criteria**:
- [ ] `POST /api/v1/brokerage-connections` returns 201 in integration test
- [ ] `TosNotAcceptedError` maps to 422
- [ ] ruff + mypy pass on `app.py` and `error_mapping.py`

---

#### Validation Gate
- [ ] `ruff check services/portfolio/src/portfolio/api/` passes
- [ ] `mypy services/portfolio/src/portfolio/api/` passes
- [ ] `python -m pytest services/portfolio/tests/ -m unit -v` — all existing tests pass
- [ ] No infrastructure imports in `routes/brokerage_connections.py` (R16/R25)

#### Regression Guardrails
- **BP-043**: Use `Annotated[bool, Field(...)]` not `Field(strip_whitespace=True)` for schema validators
- **R25 / IG-LAYER-002**: API router must NOT import from `infrastructure/` — use `request.app.state.brokerage_client` (already app.state, not direct import)
- **R27**: `ListBrokerageConnectionsUseCase` and `GetSyncErrorsUseCase` routes must use `ReadUoWDep`, not `UoWDep`
- **Privacy**: `SyncErrorResponse` must NOT include `raw_transaction` — add a `# raw_transaction intentionally excluded` comment to the schema class as a permanent guard against accidental addition

---

## Sub-plan D: Worker + S9 Gateway

### Wave D-1: BrokerageTransactionSyncWorker

**Goal**: Implement the background worker that runs every 4 hours, fetching brokerage transactions and replaying them through `RecordTransactionUseCase`.
**Depends on**: Wave C-1 (use cases), Wave B-1 (SnapTradeClient), Wave B-2 (repos via UoW)
**Estimated effort**: 75–120 minutes
**Architecture layer**: infrastructure/workers

#### Pre-read (agent must read before starting)
- `services/portfolio/src/portfolio/application/use_cases/record_transaction.py` (full file — worker calls this)
- `services/portfolio/src/portfolio/application/ports/brokerage_client.py` (after B-1)
- `services/portfolio/src/portfolio/config.py` (after A-2 — for worker settings)
- `services/portfolio/src/portfolio/infrastructure/db/session.py` (session_factory creation pattern)
- `services/portfolio/src/portfolio/infrastructure/metrics/prometheus.py` (metrics pattern)

#### Tasks

---

##### T-D-1-00: Extend InstrumentRepository with get_by_symbol()

**Type**: impl
**depends_on**: none
**blocks**: [T-D-1-03]
**Target files**:
- `services/portfolio/src/portfolio/application/ports/repositories.py` (extend `InstrumentRepository`)
- `services/portfolio/src/portfolio/infrastructure/db/repositories/instrument.py` (implement)
**PRD reference**: §4.2 F-15, §6.5 (instrument resolution in worker)

**What to build**:
The existing `InstrumentRepository.get_by_symbol_exchange(symbol, exchange)` cannot reliably find instruments for SnapTrade activities because SnapTrade provides a ticker symbol but no exchange. The worker needs a symbol-only lookup.

**Changes to `InstrumentRepository` ABC**:
```python
@abstractmethod
async def get_by_symbol(self, symbol: str) -> InstrumentRef | None: ...
```
Returns the first instrument matching by symbol (case-insensitive). If multiple instruments share the same symbol across exchanges, returns any one (implementation: `LIMIT 1`).

**`SqlAlchemyInstrumentRepository` implementation**:
```python
async def get_by_symbol(self, symbol: str) -> InstrumentRef | None:
    result = await self._session.execute(
        select(InstrumentModel)
        .where(func.upper(InstrumentModel.symbol) == symbol.upper())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return self._to_entity(row) if row else None
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_get_by_symbol_found` | Case-insensitive match returns `InstrumentRef` | unit |
| `test_get_by_symbol_not_found` | Unknown symbol returns `None` | unit |

**Acceptance criteria**:
- [ ] `InstrumentRepository` ABC has the new abstract method
- [ ] `SqlAlchemyInstrumentRepository` implements it with case-insensitive matching
- [ ] Existing `get_by_symbol_exchange` tests still pass (no regression)
- [ ] ruff + mypy pass

---

##### T-D-1-01: Worker module + sync cycle lifecycle

**Type**: impl
**depends_on**: [T-C-1-01, T-B-1-03, T-B-2-04]
**blocks**: [T-D-1-02]
**Target files**:
- `services/portfolio/src/portfolio/workers/__init__.py`
- `services/portfolio/src/portfolio/workers/brokerage_sync_worker.py`
**PRD reference**: §6.5 (BrokerageTransactionSyncWorker process lifecycle)

**What to build**:
The worker module with `asyncio.run` entry point and main sync loop.

**Process lifecycle**:
```python
async def main() -> None:
    settings = Settings()
    setup_logging(settings)
    session_factory = create_session_factory(settings)
    brokerage_client = SnapTradeClient(settings.snaptrade_client_id, settings.snaptrade_consumer_key)
    # R-001 FIX: construct Fernet cipher here and thread it to every SqlAlchemyUnitOfWork the
    # worker creates. Without this, when SNAPTRADE_SECRET_ENCRYPTION_KEY is set the worker would
    # load encrypted ciphertext as the user secret and pass it to SnapTrade — causing all sync
    # operations to fail with invalid credentials (silently caught as BrokerageApiError).
    from cryptography.fernet import Fernet  # noqa: PLC0415
    cipher = Fernet(settings.snaptrade_secret_encryption_key.encode()) \
        if settings.snaptrade_secret_encryption_key else None
    worker = BrokerageTransactionSyncWorker(session_factory, brokerage_client, settings, cipher=cipher)
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())
```

**`BrokerageTransactionSyncWorker.__init__`** must accept `cipher: Fernet | None = None` and store it as `self._cipher`.

**`BrokerageTransactionSyncWorker.run()`**:
```python
async def run(self) -> None:
    logger.info("brokerage_sync_worker_started", cycle_seconds=self._settings.brokerage_sync_cycle_seconds)
    while True:
        try:
            await self.sync_cycle()
        except Exception as e:
            logger.error("sync_cycle_error", error=str(e))
        await asyncio.sleep(self._settings.brokerage_sync_cycle_seconds)
```

**Note on `TODO: OQ-002`**: Add a comment `# TODO: verify SnapTrade SDK pagination for accounts with >1000 activities` near `get_activities` call.

**Acceptance criteria**:
- [ ] `python -m portfolio.workers.brokerage_sync_worker` is the entry point
- [ ] `run()` loops on `brokerage_sync_cycle_seconds` (default 14400 = 4h)
- [ ] `BrokerageTransactionSyncWorker.__init__` accepts `cipher: Fernet | None = None`
- [ ] `cipher` is passed to every `SqlAlchemyUnitOfWork(self._session_factory, snaptrade_cipher=self._cipher)` the worker creates
- [ ] ruff + mypy pass

---

##### T-D-1-02: sync_cycle — connection iteration + SnapTrade fetch

**Type**: impl
**depends_on**: [T-D-1-01]
**blocks**: [T-D-1-03]
**Target files**: `services/portfolio/src/portfolio/workers/brokerage_sync_worker.py` (extend)
**PRD reference**: §6.5, §6.7 (Recurring Sync Flow)

**What to build**:
The `sync_cycle()` method that fetches all `active/error` connections and iterates through them.

**Logic**:
```
sync_cycle():
    # Use self._cipher (from R-001 fix) when constructing UoW so that brokerage_connections
    # repo decrypts snaptrade_user_secret correctly.
    1. async with SqlAlchemyUnitOfWork(self._session_factory, snaptrade_cipher=self._cipher) as uow:
         connections = await uow.brokerage_connections.list_active_or_error()
    2. For each connection in connections:
         await self._sync_connection(connection)
```

**`_sync_connection(connection)`**:
```
1. Determine start_date:
   - if connection.last_sync_cursor: parse as date
   - else: date.today() - timedelta(days=settings.brokerage_sync_history_days)
2. end_date = date.today()
3. try:
     activities = await self._brokerage_client.get_activities(
         user=SnapTradeUser(connection.snaptrade_user_id, connection.snaptrade_user_secret),
         start=start_date, end=end_date
     )
4. except BrokerageApiError as e:
     log warning; set connection.status = ERROR; save; return
5. for each activity: await self._process_activity(connection, activity, uow)
6. Update connection: last_synced_at=utc_now(), last_sync_cursor=end_date.isoformat()
7. If connection.status == ERROR: set status = ACTIVE (recovery after successful sync)
8. save connection, commit uow
```

**Important**: Open a NEW `UnitOfWork` per connection (not one UoW for the entire cycle) to avoid long-running transactions (BP-057). Explicitly close session before calling SnapTrade API. **Always pass `snaptrade_cipher=self._cipher`** when constructing any `SqlAlchemyUnitOfWork` in this worker — omitting it means encrypted secrets are returned as raw ciphertext and passed to SnapTrade (R-001 fix).

**Acceptance criteria**:
- [ ] New UoW opened per connection in `_sync_connection`
- [ ] Every `SqlAlchemyUnitOfWork(...)` call passes `snaptrade_cipher=self._cipher`
- [ ] `BrokerageApiError` → sets `status=ERROR`, logs warning, continues to next connection
- [ ] `snaptrade_user_secret` never in structlog calls
- [ ] ruff + mypy pass

---

##### T-D-1-03: Activity processing — type mapping + instrument resolution + transaction record

**Type**: impl
**depends_on**: [T-D-1-02, T-D-1-00]
**blocks**: [T-D-1-04]
**Target files**: `services/portfolio/src/portfolio/workers/brokerage_sync_worker.py` (extend)
**PRD reference**: §6.5 (SnapTrade Transaction Type Mapping), §4.2 F-11..F-17

**What to build**:
The `_process_activity()` method and the transaction type mapper.

**Type mapping** (from §6.5 table):
```python
_TYPE_MAP: dict[str, tuple[TransactionType, TransactionDirection]] = {
    "BUY": (TransactionType.BUY, TransactionDirection.OUTFLOW),
    "SELL": (TransactionType.SELL, TransactionDirection.INFLOW),
    "DIV": (TransactionType.DIVIDEND, TransactionDirection.INFLOW),
    "DIVIDEND": (TransactionType.DIVIDEND, TransactionDirection.INFLOW),
}
```

**`_process_activity(connection, activity, uow)` logic**:
1. **Type check**: if `activity.activity_type` not in `_TYPE_MAP`:
   - Create `BrokerageTransactionSyncError(error_type=UNSUPPORTED_TYPE, ...)`
   - `await uow.brokerage_sync_errors.save(error)`; increment `s1_brokerage_sync_transactions_imported_total{status=skipped}`; return
2. **Dedup check** (optional optimisation): `await uow.transactions.find_by_external_ref(connection.portfolio_id, connection.tenant_id, activity.snaptrade_transaction_id)` → if found, skip silently
3. **Instrument resolution**:
   a. `instrument = await uow.instruments.get_by_symbol(activity.symbol)` (exchange unknown from SnapTrade — uses the new `get_by_symbol` method added in T-D-1-00; case-insensitive)
   b. If not found: call S3 `GET /api/v1/instruments/{symbol}` via httpx (see note below)
   c. If still not found: create `BrokerageTransactionSyncError(error_type=UNKNOWN_INSTRUMENT, ...)`; save; return
4. **Record transaction**:
   - Build `RecordTransactionCommand(tenant_id=..., portfolio_id=..., owner_id=..., instrument_id=instrument.id, transaction_type=tx_type, direction=direction, quantity=activity.quantity, price=activity.price, currency=activity.currency, executed_at=activity.executed_at, external_ref=activity.snaptrade_transaction_id)`
   - `await RecordTransactionUseCase().execute(cmd, uow)`
   - On `IdempotencyConflictError` (duplicate external_ref) — skip silently (F-13 dedup)
   - On other exception — create `BrokerageTransactionSyncError(error_type=VALIDATION_ERROR, error_detail=str(e))`; save; continue

**S3 instrument resolution** (step 3b):
- Use `httpx.AsyncClient` to call `GET http://{S3_HOST}/api/v1/instruments/{symbol}`
- S3 hostname from new config setting: `market_data_service_url: str = "http://market-data:8003"` (add to config in this task)
- **SECURITY (R-002)**: URL-encode the symbol before embedding it in the path — SnapTrade symbols like `"BRK.B"`, `"BTC/USD"`, or `"BF.B"` contain characters that corrupt path routing without encoding:
  ```python
  import urllib.parse
  encoded_symbol = urllib.parse.quote(activity.symbol, safe="")
  response = await http_client.get(
      f"{settings.market_data_service_url}/api/v1/instruments/{encoded_symbol}"
  )
  ```
- If S3 returns 404 → instrument not found → proceed to create sync error
- If S3 returns 200 → upsert instrument via `uow.instruments.upsert(InstrumentRef(...))` then use

**Metrics** (using `prometheus_client` — see pattern in `infrastructure/metrics/prometheus.py`):
- Increment `s1_brokerage_sync_transactions_imported_total` with appropriate label

**Acceptance criteria**:
- [ ] `BUY` → `TransactionType.BUY, OUTFLOW`
- [ ] `SELL` → `TransactionType.SELL, INFLOW`
- [ ] `DIV`/`DIVIDEND` → `TransactionType.DIVIDEND, INFLOW`
- [ ] All other types → `SyncErrorType.UNSUPPORTED_TYPE` row, worker continues
- [ ] Unknown instrument creates `SyncErrorType.UNKNOWN_INSTRUMENT` row, worker continues
- [ ] `IdempotencyConflictError` silently skipped (dedup is correct behavior)
- [ ] Symbol URL-encoded via `urllib.parse.quote(symbol, safe="")` before S3 path construction (R-002)
- [ ] ruff + mypy pass

---

##### T-D-1-04: Worker Prometheus metrics

**Type**: impl
**depends_on**: [T-D-1-01]
**blocks**: none
**Target files**: `services/portfolio/src/portfolio/infrastructure/metrics/prometheus.py` (extend)
**PRD reference**: §13

**What to build**:
Register the 4 new metrics from PRD §13 using the existing `prometheus_client` pattern.

**New metrics**:
```python
BROKERAGE_SYNC_TRANSACTIONS_TOTAL = Counter(
    "s1_brokerage_sync_transactions_imported_total",
    "Transaction import rate",
    ["status", "error_type"],
)
BROKERAGE_SYNC_CYCLE_DURATION = Histogram(
    "s1_brokerage_sync_cycle_duration_seconds",
    "Time per 4h sync cycle",
)
BROKERAGE_CONNECTIONS_TOTAL = Gauge(
    "s1_brokerage_connections_total",
    "Connection status distribution",
    ["status"],
)
BROKERAGE_PENDING_CONNECTIONS_AGE = Gauge(
    "s1_brokerage_pending_connections_age_seconds",
    "Age of oldest pending connection",
)
```

**Acceptance criteria**:
- [ ] All 4 metrics registered at module import time
- [ ] Worker uses `BROKERAGE_SYNC_CYCLE_DURATION.time()` context manager around `sync_cycle()`
- [ ] ruff + mypy pass

---

#### Validation Gate
- [ ] `ruff check services/portfolio/src/portfolio/workers/` passes
- [ ] `mypy services/portfolio/src/portfolio/workers/` passes
- [ ] `python -m pytest services/portfolio/tests/ -m unit -k "worker" -v` — minimum 5 new tests pass
- [ ] Worker module runs without error on startup (no SnapTrade calls needed if `snaptrade_client_id` empty)

#### Regression Guardrails
- **BP-057**: DB session must NOT be held open while calling SnapTrade API. Pattern: open UoW → load connection → close UoW → call API → open new UoW → save results
- **BP-025**: SnapTrade SDK is synchronous — wrap in `asyncio.run_in_executor(None, sdk_call)` or verify SDK provides async variant before direct `await`
- **BP-016**: Same as BP-057 — advisory/DB lock must not span external I/O
- **BP-100**: `get_activities` SDK method name must be verified against installed SDK version before committing
- **BP-040**: `RecordTransactionUseCase` uses idempotency table with `create_if_not_exists` — catch `IdempotencyConflictError` not bare `Exception` for dedup path

---

### Wave D-2: S9 Gateway Proxy Routes + Unit Tests

**Goal**: Expose the 4 brokerage connection endpoints through the S9 API Gateway and write the core unit tests for the use cases.
**Depends on**: Wave C-2 (S1 routes exist), Wave D-1 (worker exists for docker-compose entry)
**Estimated effort**: 45–75 minutes
**Architecture layer**: S9 proxy + tests

#### Pre-read (agent must read before starting)
- `services/api-gateway/src/api_gateway/routes/proxy.py`
- `services/api-gateway/src/api_gateway/config.py`
- `services/portfolio/tests/unit/` (existing test patterns)
- PRD §11 (test scenarios)

#### Tasks

---

##### T-D-2-01: S9 proxy routes for brokerage connections

**Type**: impl
**depends_on**: none (S9 is stateless — doesn't need S1 to be running)
**blocks**: [T-E-1-01]
**Target files**: `services/api-gateway/src/api_gateway/routes/proxy.py` (extend)
**PRD reference**: §6.2 (S9 Gateway proxy routes)

**What to build**:
Add 4 passthrough proxy routes to S9's `proxy.py`. S9 injects JWT-derived `X-User-Id` and `X-Tenant-Id` headers before forwarding.

**Routes to add**:
```python
# Rate limit: 30/min per user (lower — involves external API calls)
@router.post("/brokerage-connections")  # → S1 POST /api/v1/brokerage-connections
@router.get("/brokerage-connections")   # → S1 GET /api/v1/brokerage-connections
@router.delete("/brokerage-connections/{connection_id}")  # → S1 DELETE ...
@router.get("/brokerage-connections/{connection_id}/callback")  # → S1 GET .../callback
@router.get("/brokerage-connections/{connection_id}/sync-errors")  # → S1 GET .../sync-errors
```

**Implementation pattern**: Follow existing proxy patterns in `proxy.py` — forward request body + query params, inject auth headers from `_auth_headers(request)`, forward response as-is.

**S9 config** — ensure `portfolio_service_url` is in `api_gateway/config.py` (verify it exists; if not, add `portfolio_service_url: str = "http://portfolio:8001"`).

**Acceptance criteria**:
- [ ] All 5 routes registered with correct HTTP methods and paths
- [ ] Auth headers injected from JWT payload (`X-User-Id`, `X-Tenant-Id`)
- [ ] ruff + mypy pass on `proxy.py`

---

##### T-D-2-02: docker-compose entry for brokerage sync worker

**Type**: config
**depends_on**: [T-D-1-01]
**blocks**: none
**Target files**: `infra/docker-compose.yml` (or service-specific compose file for portfolio)
**PRD reference**: §12

**What to build**:
Add `portfolio-brokerage-sync` service entry to docker-compose that runs the new worker process.

```yaml
portfolio-brokerage-sync:
  image: worldview-portfolio:latest
  command: python -m portfolio.workers.brokerage_sync_worker
  environment:
    - PORTFOLIO_DATABASE_URL=${PORTFOLIO_DATABASE_URL}
    - SNAPTRADE_CLIENT_ID=${SNAPTRADE_CLIENT_ID:-}
    - SNAPTRADE_CONSUMER_KEY=${SNAPTRADE_CONSUMER_KEY:-}
    - SNAPTRADE_REDIRECT_URI=${SNAPTRADE_REDIRECT_URI:-http://localhost:5173/portfolio/brokerage/callback}
    - SNAPTRADE_SECRET_ENCRYPTION_KEY=${SNAPTRADE_SECRET_ENCRYPTION_KEY:-}  # Logs warning if empty; required for production
    - PORTFOLIO_MARKET_DATA_SERVICE_URL=${PORTFOLIO_MARKET_DATA_SERVICE_URL:-http://market-data:8003}  # R-005: instrument fallback lookup
  depends_on:
    portfolio-migrate:
      condition: service_completed_successfully
```

Note: Worker starts even with empty `SNAPTRADE_CLIENT_ID` (warns but doesn't crash — config validator uses `warning` not `exception`).

**Acceptance criteria**:
- [ ] `docker-compose config` validates without error
- [ ] Worker service has correct `depends_on` (migration must complete first)

---

##### T-D-2-03: Unit tests — domain entities + use cases

**Type**: test
**depends_on**: [T-C-1-01, T-B-1-02]
**blocks**: none
**Target files**: `services/portfolio/tests/unit/test_brokerage_connection.py`
**PRD reference**: §11 (unit test strategy — HIGH priority tests)

**What to build**:
Unit tests for domain entities and all 5 use cases using `FakeBrokerageClient` and a fake UoW pattern.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_brokerage_connection_secret_redacted_in_repr` | `repr(conn)` never contains actual `snaptrade_user_secret` | unit |
| `test_connection_activate_pending_to_active` | `pending → active` sets `authorization_id` | unit |
| `test_connection_activate_invalid_state` | `active → active` raises `BrokerageConnectionStateError` | unit |
| `test_connection_disconnect_active` | `active → disconnected` | unit |
| `test_connection_disconnect_already_disconnected` | `BrokerageConnectionAlreadyDisconnectedError` | unit |
| `test_initiate_connection_tos_not_accepted` | `snaptrade_tos_accepted=False` raises `TosNotAcceptedError` before any API call | unit |
| `test_initiate_connection_creates_pending_connection` | Use case creates connection with `status=PENDING` | unit |
| `test_activate_connection_user_id_mismatch` | `userId` from callback doesn't match stored → `BrokerageConnectionForbiddenError` | unit |
| `test_disconnect_revokes_snaptrade_authorization` | `FakeBrokerageClient.revoke_calls` has 1 entry | unit |
| `test_disconnect_retains_transactions` | Use case never calls `transaction_repo.delete` | unit |
| `test_list_connections_filters_by_portfolio` | Only connections for `portfolio_id` returned | unit |
| `test_get_sync_errors_requires_ownership` | Wrong `user_id` → `BrokerageConnectionNotFoundError` | unit |
| `test_initiate_connection_type_is_always_read` | `FakeBrokerageClient.portal_url_calls` confirms `connectionType=read` is hardcoded — `generate_portal_url` received `redirect_uri` containing `connectionId` but NOT `connectionType` (connectionType must be hardcoded server-side per F-22) | unit |
| `test_sync_worker_uses_history_days_for_initial_cursor` | Worker with `last_sync_cursor=None` computes `start_date = date.today() - timedelta(days=settings.brokerage_sync_history_days)` — verifies F-16 | unit |
| `test_get_sync_errors_raw_transaction_excluded` | `GET /api/v1/brokerage-connections/{id}/sync-errors` response items do not contain a `raw_transaction` key — `assert "raw_transaction" not in response.json()["items"][0]` — enforces PRD §6.4 privacy invariant at the serialization boundary | unit |

Minimum: **15 unit tests**

**Test infrastructure**: Use `FakeBrokerageClient` (from T-B-1-02) + inline fake UoW (dict-backed repos — similar pattern to existing portfolio unit tests). Do NOT make real SnapTrade API calls.

**Acceptance criteria**:
- [ ] All 15 tests pass
- [ ] No real SnapTrade SDK calls (FakeBrokerageClient used)
- [ ] `pytest -m unit -k brokerage` runs in < 5 seconds

---

##### T-D-2-04: Unit tests — worker type mapping + instrument resolution

**Type**: test
**depends_on**: [T-D-1-03, T-B-1-02]
**blocks**: none
**Target files**: `services/portfolio/tests/unit/test_brokerage_sync_worker.py`
**PRD reference**: §11

**What to build**:
Unit tests for the worker's type mapping and per-activity processing logic.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_worker_maps_buy_to_buy_outflow` | `BUY` → `TransactionType.BUY, OUTFLOW` | unit |
| `test_worker_maps_sell_to_sell_inflow` | `SELL` → `TransactionType.SELL, INFLOW` | unit |
| `test_worker_maps_div_to_dividend_inflow` | `DIV` → `TransactionType.DIVIDEND, INFLOW` | unit |
| `test_worker_maps_dividend_to_dividend_inflow` | `DIVIDEND` → `TransactionType.DIVIDEND, INFLOW` | unit |
| `test_worker_skips_option_transactions` | `OPTION_EXERCISE` → `SyncErrorType.UNSUPPORTED_TYPE` row created | unit |
| `test_worker_skips_transfer_transactions` | `TRANSFER_IN` → `SyncErrorType.UNSUPPORTED_TYPE` | unit |
| `test_worker_unknown_instrument_creates_error` | Symbol not found → `SyncErrorType.UNKNOWN_INSTRUMENT` row, worker does not crash | unit |
| `test_worker_deduplicates_by_external_ref` | `IdempotencyConflictError` from `RecordTransactionUseCase` → silently skipped | unit |
| `test_worker_api_error_sets_connection_error_status` | `BrokerageApiError` → `connection.status = ERROR`, other connections continue | unit |

Minimum: **9 unit tests**

**Acceptance criteria**:
- [ ] All 9 tests pass
- [ ] No real SnapTrade SDK calls

---

---

##### T-D-2-05: Update .env.example with SnapTrade env vars

**Type**: config
**depends_on**: [T-A-2-02]
**blocks**: none
**Target files**: `.env.example` (or `dev.local.env.example` — check repo root for the actual filename)
**PRD reference**: §12 (Migration Plan), §4.3 F-23

**What to build**:
Add all 5 new env vars required for SnapTrade brokerage sync to the project's env example file. This is the single reference a developer needs to set up local testing with a real brokerage account (e.g. TastyTrade).

**Entries to add** (under a new `# ── SnapTrade Brokerage Sync (S1) ──` section):
```bash
# ── SnapTrade Brokerage Sync (S1) ──────────────────────────────────────────────
# Register at https://app.snaptrade.com (free tier, self-service) to receive these credentials.
# Required for: portfolio brokerage connection flow + BrokerageTransactionSyncWorker.
# Leave blank in CI — service logs a startup warning but still starts.
SNAPTRADE_CLIENT_ID=
SNAPTRADE_CONSUMER_KEY=
# Redirect URI — must be reachable by the user's browser after SnapTrade OAuth completes.
# For local dev, localhost:5173 works (the browser redirect, NOT a server-side callback).
SNAPTRADE_REDIRECT_URI=http://localhost:5173/portfolio/brokerage/callback
# Fernet encryption key for snaptrade_user_secret at rest in portfolio_db.
# Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# If empty: plaintext fallback (acceptable for dev; MANDATORY for any deployment with real accounts).
SNAPTRADE_SECRET_ENCRYPTION_KEY=
# Market Data service URL for instrument fallback lookup (worker only).
# In docker-compose: default http://market-data:8003 is correct. Override for non-compose dev.
PORTFOLIO_MARKET_DATA_SERVICE_URL=http://localhost:8003
```

**Acceptance criteria**:
- [ ] All 5 env vars present in the example file with comments explaining each
- [ ] `SNAPTRADE_SECRET_ENCRYPTION_KEY` generation command included as a comment
- [ ] SnapTrade registration URL included (`https://app.snaptrade.com`)

---

#### Validation Gate
- [ ] `ruff check services/api-gateway/ services/portfolio/tests/unit/test_brokerage*.py` passes
- [ ] `mypy services/api-gateway/` passes
- [ ] `python -m pytest services/portfolio/tests/ -m unit -v` — minimum 24 new tests total (15 + 9), all pass
- [ ] `docker-compose config` validates
- [ ] `.env.example` contains all 5 new SnapTrade env vars (T-D-2-05)

#### Regression Guardrails
- **BP-010**: `portfolio-brokerage-sync` docker-compose entry must NOT inherit the API service healthcheck — it's a background process with no HTTP port
- **R-001**: Every `SqlAlchemyUnitOfWork(...)` in the worker must pass `snaptrade_cipher=self._cipher`; grep for bare `SqlAlchemyUnitOfWork(self._session_factory)` and reject any that omit the cipher arg

---

## Sub-plan E: Frontend

### Wave E-1: Frontend Components + Callback Route

**Goal**: Implement the "Connected Brokerages" UI section in the Portfolio page, the connect modal, sync error banner, and callback route.
**Depends on**: Wave D-2 (S9 routes available)
**Estimated effort**: 60–90 minutes
**Architecture layer**: Frontend (React + TypeScript)

#### Pre-read (agent must read before starting)
- `apps/frontend/src/pages/PortfolioPage.tsx`
- `apps/frontend/src/App.tsx` (React Router routes)
- `apps/frontend/src/components/Layout.tsx` (layout patterns)
- PRD §6.6 (frontend changes spec)

#### Tasks

---

##### T-E-1-01: API client hooks for brokerage connections

**Type**: impl
**depends_on**: none
**blocks**: [T-E-1-02]
**Target files**: `apps/frontend/src/hooks/useBrokerageConnections.ts`
**PRD reference**: §6.6

**What to build**:
A React hooks module with typed API calls for brokerage connection CRUD.

**Functions to implement**:
```typescript
// Types
interface BrokerageConnection {
  connection_id: string;
  portfolio_id: string;
  brokerage_name: string | null;
  status: "pending" | "active" | "error" | "disconnected";
  last_synced_at: string | null;
  created_at: string;
}

// Hooks / functions
export function useBrokerageConnections(portfolioId?: string): {
  connections: BrokerageConnection[];
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
}

export async function initiateConnection(portfolioId: string): Promise<{ connection_id: string; redirect_uri: string }>
export async function disconnectConnection(connectionId: string): Promise<void>

interface SyncError {
  id: string;
  connection_id: string;
  snaptrade_transaction_id: string;
  error_type: "unknown_instrument" | "unsupported_type" | "api_error" | "validation_error";
  error_detail: string | null;
  created_at: string;
  // raw_transaction intentionally absent — excluded from API (see PRD §6.4 privacy note)
}

export function useSyncErrors(connectionId: string): {
  errors: SyncError[];
  isLoading: boolean;
  error: string | null;
}
```

The `initiateConnection` call uses `snaptrade_tos_accepted: true` (ToS is always accepted by this point — the modal checkbox guards entry). All API calls go to `/api/v1/brokerage-connections` (via S9).

**Acceptance criteria**:
- [ ] `useBrokerageConnections` uses `useEffect` + `fetch` pattern (or existing API client if project uses one)
- [ ] TypeScript types match the API response schema from PRD §6.2
- [ ] No direct calls to backend service URLs — always via `/api/v1/...` (R14)

---

##### T-E-1-02: ConnectBrokerageModal + ConnectedBrokeragesList + SyncErrorsBanner

**Type**: impl
**depends_on**: [T-E-1-01]
**blocks**: [T-E-1-03]
**Target files**:
- `apps/frontend/src/components/ConnectBrokerageModal.tsx`
- `apps/frontend/src/components/ConnectedBrokeragesList.tsx`
- `apps/frontend/src/components/SyncErrorsBanner.tsx`
**PRD reference**: §6.6

**What to build**:

**`ConnectBrokerageModal`**:
- Props: `portfolioId: string`, `onClose: () => void`, `onConnected: () => void`
- Modal with explanatory text + SnapTrade ToS link
- Checkbox: "I agree to SnapTrade's End User Terms of Service" (required)
- Portfolio selector if `portfolioId` is undefined
- "Connect" button (disabled until checkbox checked): calls `initiateConnection(portfolioId)` → `window.location.href = redirect_uri`
- Loading state while API call in flight

**`ConnectedBrokeragesList`**:
- Props: `portfolioId?: string`
- Calls `useBrokerageConnections(portfolioId)`
- Renders each connection as a row: brokerage name (or "Pending"), status badge, relative last-synced time ("2 hours ago")
- "Disconnect" button per row → confirmation dialog → `disconnectConnection(id)` → refetch

**`SyncErrorsBanner`**:
- Props: `connectionId: string`
- Calls `GET /api/v1/brokerage-connections/{id}/sync-errors`
- Shows: "X sync errors — view details" if count > 0; renders nothing if `items` is empty

**Acceptance criteria**:
- [ ] Connect modal only enables "Connect" after checkbox checked
- [ ] Disconnect shows confirmation dialog before calling API
- [ ] All components are TypeScript (no implicit `any`)
- [ ] `tsc --noEmit` passes

---

##### T-E-1-03: Portfolio page integration + callback route

**Type**: impl
**depends_on**: [T-E-1-02]
**blocks**: none
**Target files**:
- `apps/frontend/src/pages/PortfolioPage.tsx` (extend)
- `apps/frontend/src/pages/BrokerageCallbackPage.tsx` (new)
- `apps/frontend/src/App.tsx` (add route)
**PRD reference**: §6.6

**What to build**:

**`PortfolioPage.tsx` extension**:
- Add "Connected Brokerages" section below existing portfolio header
- Include `ConnectedBrokeragesList` and a "Connect Brokerage" button that opens `ConnectBrokerageModal`

**`BrokerageCallbackPage.tsx`** (new page):
- Route: `/portfolio/brokerage/callback`
- Reads URL query params: `authorizationId`, `userId`, `connectionId` (passed via redirect URI fragment or query string)
- Calls `GET /api/v1/brokerage-connections/{connectionId}/callback?authorizationId=...&userId=...&sessionId=...`
- Shows loading spinner → success message ("Brokerage connected! Your transactions are being imported.") → redirect to `/portfolio` after 2s
- On error: shows error message + "Go back" link

**`App.tsx` change**:
- Add route: `<Route path="/portfolio/brokerage/callback" element={<BrokerageCallbackPage />} />`

**Acceptance criteria**:
- [ ] Callback page handles success and error states
- [ ] After successful callback, user is redirected to `/portfolio` within 3 seconds
- [ ] React Router route registered in `App.tsx`
- [ ] `tsc --noEmit` passes
- [ ] `npm run lint` passes (or project equivalent)

---

#### Validation Gate
- [ ] `tsc --noEmit` passes from `apps/frontend/`
- [ ] `npm run lint` (or `eslint`) passes
- [ ] No direct backend service URL calls in frontend (all via `/api/v1/...`)
- [ ] `ConnectBrokerageModal` shows ToS checkbox (visual review)

#### Regression Guardrails
- **R14**: Frontend must only call S9 gateway (`/api/v1/...`), never backend services directly
- No hardcoded SnapTrade portal URLs in frontend components — the redirect URL comes from the API response

---

## Cross-Cutting Concerns

### Contract Changes
- No new Avro schemas — brokerage sync reuses existing `portfolio.events.v1` topic via `RecordTransactionUseCase`
- New REST API endpoints (S1 + S9) — no contract tests needed beyond unit tests (no downstream consumers)

### Migration Dependencies
- Alembic chain: `0005_add_tenant_id_to_holdings` → `0006_add_brokerage_tables` (Wave A-2)
- No `intelligence-migrations` involvement (brokerage tables are in `portfolio_db`, not `intelligence_db`)

### New Kafka Topics
- None — existing `portfolio.events.v1` carries all events

### New Environment Variables
Add to `dev.local.env.example` / deployment docs:
```
SNAPTRADE_CLIENT_ID=          # Required for live SnapTrade calls; empty disables with warning
SNAPTRADE_CONSUMER_KEY=       # Required for live SnapTrade calls
SNAPTRADE_REDIRECT_URI=http://localhost:5173/portfolio/brokerage/callback
SNAPTRADE_SECRET_ENCRYPTION_KEY=  # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" — required for production; empty degrades to plaintext (dev OK)
# Worker settings (optional — have defaults)
PORTFOLIO_BROKERAGE_SYNC_CYCLE_SECONDS=14400
PORTFOLIO_BROKERAGE_SYNC_HISTORY_DAYS=730
PORTFOLIO_MARKET_DATA_SERVICE_URL=http://market-data:8003
```

### Documentation Updates Required
- `docs/services/portfolio.md` — add new entities, endpoints, worker process
- `services/portfolio/.claude-context.md` — add new entities, endpoints, pitfalls
- `docs/MASTER_PLAN.md` — SnapTrade integration note under S1 section

---

## Risk Assessment

### Critical Path
A-1 → A-2 → B-2 → C-1 → C-2 → D-2 → E-1

### Highest Risk Waves

| Wave | Risk | Mitigation |
|------|------|-----------|
| B-1 (SnapTradeClient) | SnapTrade SDK method names may differ from PRD (BP-100) | Verify SDK API with `help(SnapTrade)` before implementing; add `TODO: verify` comments |
| D-1 (Worker) | Blocking sync SDK in async context (BP-025) | Use `asyncio.run_in_executor` for all SDK calls |
| D-1 (Worker) | DB session held during SnapTrade API call (BP-057) | Open separate UoW per connection; close before API call |
| A-2 (Migration) | Column type mismatch between ORM and DDL (BP-019) | Cross-check every column before committing |

### Rollback Strategy
- Waves A-1..C-2 can be rolled back by running `alembic downgrade -1` (drops both brokerage tables)
- Worker process: simply do not start the docker-compose entry
- S9 routes: remove 4 route handlers from `proxy.py`
- Frontend: revert `PortfolioPage.tsx` to single-paragraph stub + remove callback route

### Testing Gaps
- No integration tests in this plan for the worker against a real (wiremock'd) SnapTrade API
- No E2E tests for the full OAuth flow (SnapTrade portal is external)
- Deferred to post-implementation if needed for thesis evaluation

---

## Task ID Reference

| Wave | Task IDs |
|------|----------|
| A-1 | T-A-1-01, T-A-1-02, T-A-1-03, T-A-1-04 |
| A-2 | T-A-2-01, T-A-2-02, T-A-2-03 |
| B-1 | T-B-1-01, T-B-1-02, T-B-1-03 |
| B-2 | T-B-2-01, T-B-2-02, T-B-2-03, T-B-2-04 |
| C-1 | T-C-1-01, T-C-1-02, T-C-1-03, T-C-1-04, T-C-1-05 |
| C-2 | T-C-2-01, T-C-2-02, T-C-2-03 |
| D-1 | T-D-1-01, T-D-1-02, T-D-1-03, T-D-1-04 |
| D-2 | T-D-2-01, T-D-2-02, T-D-2-03, T-D-2-04 |
| E-1 | T-E-1-01, T-E-1-02, T-E-1-03 |
