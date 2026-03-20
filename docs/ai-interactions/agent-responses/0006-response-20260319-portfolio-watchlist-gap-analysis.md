# Portfolio Service — Watchlist & Intelligence Layer Gap Analysis

> **Document ID**: 0006
> **Date**: 2026-03-19
> **Author**: Claude Sonnet 4.6 (Analysis Lead)
> **Scope**: Portfolio service (S1) — exhaustive capability audit with focus on watchlist,
> alert subscriptions, and Intelligence Layer readiness
> **Root path**: `services/portfolio/`

---

## 1. Executive Summary

The Portfolio service (S1) is a fully functional, cleanly architected FastAPI microservice
covering the core portfolio management domain: tenant/user/portfolio CRUD, transaction
recording, holding calculation, instrument reference synchronization, outbox-pattern Kafka
publishing, and idempotent consumer wiring. The implementation quality is high — the domain
layer, repositories, use cases, and messaging stack are all complete and tested (253 tests
passing).

**Critical gaps**: The service has zero implementation of watchlist management, alert
preference storage, or the Valkey reverse-index cache that the Intelligence Layer and
alerting workflows (future S10) require. These are not partially implemented features — they
are entirely absent from domain model, database schema, API, use cases, repositories, events,
Avro schemas, and tests. Additionally, the position model lacks a `entity_id` field linking
holdings to the canonical Knowledge Graph entity (required for cross-service joins), unbounded
list endpoints have no pagination, the Kafka topic topology does not include
`portfolio.watchlist.updated.v1`, and there is no configuration or wiring for a Valkey
client within the service. A developer cannot begin any watchlist or alerting work without
first creating approximately 20 new files and 3 new database migrations.

---

## 2. Codebase Summary

### 2.1 Framework / Runtime / Tooling

| Dimension | Value |
|-----------|-------|
| Language | Python 3.11 (`.venv/lib/python3.11`) |
| Framework | FastAPI (lifespan-based factory: `create_app()`) |
| ORM | SQLAlchemy 2.0 async (`Mapped`/`mapped_column`, `async_sessionmaker`) |
| DB | PostgreSQL (`portfolio_db`) |
| Migrations | Alembic — single migration `0001_initial_schema.py` |
| Messaging | `libs/messaging` `BaseKafkaConsumer` + `BaseOutboxDispatcher` |
| Config | `pydantic-settings` with `env_prefix="PORTFOLIO_"` |
| Logging | `libs/observability` structlog adapter |
| Metrics / Tracing | Prometheus (`create_metrics`) + OpenTelemetry (`add_otel_middleware`) |
| Tests | pytest + asyncio_mode=auto, 253 tests (191 unit/contract, 24 integration, 2 e2e) |
| Linting | ruff + mypy strict |

### 2.2 Module Map by Architecture Layer

#### API layer (`src/portfolio/api/`)

| File | Status | Notes |
|------|--------|-------|
| `api/__init__.py` | Complete | |
| `api/dependencies.py` | Complete | `UoWDep` via `SqlAlchemyUnitOfWork` |
| `api/error_mapping.py` | Complete | 7-class MRO-walking mapper |
| `api/exception_handlers.py` | Complete | Domain + unhandled handlers |
| `api/schemas.py` | Complete | 14 Pydantic models; **no watchlist or alert-pref schemas** |
| `api/routes/__init__.py` | Complete | Registers 6 routers |
| `api/routes/tenant.py` | Complete | POST/GET tenant |
| `api/routes/user.py` | Complete | POST/GET user |
| `api/routes/portfolio.py` | Complete | POST/GET/PUT/DELETE portfolio |
| `api/routes/transaction.py` | Complete | POST/GET transaction |
| `api/routes/holding.py` | Complete | GET holdings |
| `api/routes/instrument.py` | Complete | GET instrument(s) |
| `api/routes/watchlist.py` | **Missing** | Entire file absent |
| `api/routes/alert_preferences.py` | **Missing** | Entire file absent |

#### Application layer (`src/portfolio/application/`)

| File | Status | Notes |
|------|--------|-------|
| `application/ports/repositories.py` | Complete (for existing scope) | No `WatchlistRepository`, `AlertPreferenceRepository`, `WatchlistMemberRepository` ABCs |
| `application/ports/unit_of_work.py` | Complete (for existing scope) | No `watchlists`, `alert_preferences` properties |
| `application/use_cases/create_portfolio.py` | Complete | |
| `application/use_cases/record_transaction.py` | Complete | |
| `application/use_cases/portfolio_ops.py` | Complete | |
| `application/use_cases/read_models.py` | Complete | |
| `application/use_cases/tenant.py` | Complete | |
| `application/use_cases/user.py` | Complete | |
| `application/use_cases/instrument.py` | Complete | |
| `application/use_cases/watchlist.py` | **Missing** | Entire file absent |
| `application/use_cases/alert_preferences.py` | **Missing** | Entire file absent |

#### Domain layer (`src/portfolio/domain/`)

| File | Status | Notes |
|------|--------|-------|
| `domain/entities/tenant.py` | Complete | |
| `domain/entities/user.py` | Complete | |
| `domain/entities/portfolio.py` | Complete | |
| `domain/entities/transaction.py` | Complete | |
| `domain/entities/holding.py` | Complete | No `entity_id` (KG link) |
| `domain/entities/instrument.py` | Complete | No `entity_id` (KG link) |
| `domain/entities/watchlist.py` | **Missing** | Entire file absent |
| `domain/entities/watchlist_member.py` | **Missing** | Entire file absent |
| `domain/entities/alert_preference.py` | **Missing** | Entire file absent |
| `domain/enums.py` | Complete | No `WatchlistStatus`, `AlertType` enums |
| `domain/events.py` | Complete | No `WatchlistItemAdded`, `WatchlistItemRemoved` events |
| `domain/errors.py` | Complete | No watchlist or alert-pref errors |
| `domain/value_objects.py` | Complete | |

#### Infrastructure / DB layer (`src/portfolio/infrastructure/db/`)

| File | Status | Notes |
|------|--------|-------|
| `db/models/__init__.py` | Complete | |
| `db/models/tenant.py` | Complete | |
| `db/models/user.py` | Complete | |
| `db/models/portfolio.py` | Complete | |
| `db/models/transaction.py` | Complete | |
| `db/models/holding.py` | Complete | No `entity_id` column |
| `db/models/instrument.py` | Complete | No `entity_id` column |
| `db/models/outbox.py` | Complete | |
| `db/models/idempotency.py` | Complete | |
| `db/models/watchlist.py` | **Missing** | |
| `db/models/watchlist_member.py` | **Missing** | |
| `db/models/alert_preference.py` | **Missing** | |
| `db/repositories/tenant.py` | Complete | |
| `db/repositories/user.py` | Complete | |
| `db/repositories/portfolio.py` | Complete | |
| `db/repositories/transaction.py` | Complete | |
| `db/repositories/holding.py` | Complete | |
| `db/repositories/instrument.py` | Complete | |
| `db/repositories/outbox.py` | Complete | |
| `db/repositories/idempotency.py` | Complete | |
| `db/repositories/watchlist.py` | **Missing** | |
| `db/repositories/watchlist_member.py` | **Missing** | |
| `db/repositories/alert_preference.py` | **Missing** | |
| `db/session.py` | Complete | `create_session_factory(url)` |
| `db/unit_of_work.py` | Complete (for existing scope) | No watchlist/alert repos wired |

#### Messaging layer (`src/portfolio/messaging/`)

| File | Status | Notes |
|------|--------|-------|
| `messaging/dispatcher.py` | Complete | `OutboxDispatcher`, `create_dispatcher` |
| `messaging/dispatcher_main.py` | Complete | SIGTERM-aware async entry point |
| `messaging/mapper.py` | Complete | 8 event-to-dict mappers; no watchlist mappers |
| `messaging/outbox_mapper.py` | Complete | Identity mapper |
| `messaging/serialization.py` | Complete | Builds per-event Avro serializers |
| `messaging/topics.py` | Complete (for existing events) | No `portfolio.watchlist.updated.v1` entry |
| `messaging/schemas/*.avsc` | 8 files, Complete | No `watchlist.item_added.avsc`, `watchlist.item_removed.avsc` |

#### Consumers (`src/portfolio/consumers/`)

| File | Status | Notes |
|------|--------|-------|
| `consumers/instrument_consumer.py` | Complete | Idempotent, logs failures |

#### Alembic migrations (`alembic/`)

| File | Status | Notes |
|------|--------|-------|
| `alembic/env.py` | Complete | Reads DB URL from `Settings()` (BP-006 fix applied) |
| `alembic/versions/0001_initial_schema.py` | Complete | Creates 7 tables for existing scope |
| `alembic/versions/0002_*.py` | **Missing** | No migration for watchlists, alert_preferences, entity_id cols |

#### Top-level service files

| File | Status | Notes |
|------|--------|-------|
| `app.py` | Complete | Lifespan wires DB, dispatcher, consumer; no Valkey client |
| `config.py` | Complete | `valkey_url` config var exists; **no Valkey client instantiated in app** |

### 2.3 Test Suite Status

| Layer | Files | Status |
|-------|-------|--------|
| Unit — domain entities | `test_domain_entities.py` | Complete; no watchlist/alert tests |
| Unit — domain events | `test_domain_events.py` | Complete; no watchlist event tests |
| Unit — domain errors | `test_domain_errors.py` | Complete |
| Unit — value objects | `test_value_objects.py` | Complete |
| Unit — use cases | `test_use_cases_*.py` (5 files) | Complete; no watchlist or alert UC tests |
| Unit — API error handlers | `test_api_error_handlers.py` | Complete |
| Unit — instrument consumer | `test_instrument_consumer.py` | Complete |
| Unit — serialization | `test_serialization.py` | Complete |
| Unit — UoW | `test_unit_of_work.py` | Complete |
| Contract — Avro | 8 `test_*_contract.py` files | Complete; no watchlist contracts |
| Integration | 6 `test_*_api.py` files | Complete; no watchlist or alert API tests |
| E2E | `tests/e2e/__init__.py` only (no test files visible) | **Effectively empty** |
| Health | `test_health.py` | Complete |

**Gap**: There are zero tests covering any watchlist, alert preference, or Valkey cache
operation. The e2e directory has only an `__init__.py` (pyc evidence suggests prior e2e tests
existed but are absent from the current tree on disk — they may have been removed).

---

## 3. Capability Audit Table

| Capability | Status | Evidence (file + symbol) | Notes / Risk |
|---|---|---|---|
| **A1** Watchlist CRUD (create/read/update/delete) | Missing | No file at `api/routes/watchlist.py`, `application/use_cases/watchlist.py`, `domain/entities/watchlist.py` | Entire feature branch absent |
| **A2** Add/remove entities by `entity_id` | Missing | No `entity_id` field anywhere in domain or schema | Requires `entity_id` in `watchlist_members` table |
| **A3** Multiple watchlists per user | Missing | No `watchlists` or `watchlist_members` table | Blocked on A1 |
| **A4** Reverse-index: `entity_id → user_ids` | Missing | No Valkey client in `app.py`, no cache logic anywhere in portfolio service | Required by alert service S10 |
| **A5** Watchlist mutation Kafka events (`portfolio.watchlist.updated.v1`) | Missing | `messaging/topics.py` — no such entry; no `.avsc` schema | Topic and schema both absent |
| **A6** Valkey reverse-index cache | Missing | `config.py` has `valkey_url` but `app.py` never constructs a `ValkeyClient`; `libs/messaging/valkey/client.py` exists | Wiring is zero |
| **B1** Position model with `entry_price`, `quantity`, `asset_type` | Partial | `domain/entities/holding.py` — `quantity`, `average_cost`; no `entry_price`, no `asset_type` | `entry_price` semantics differ from `average_cost`; `asset_type` exists on `InstrumentRef` but not on `Holding` |
| **B2** Holding ↔ canonical `entity_id` association | Missing | `HoldingModel` (`db/models/holding.py`) — no `entity_id` column; `InstrumentModel` — no `entity_id` | KG link absent from both ORM and migration |
| **B3** Validation rules (`quantity > 0`, `price >= 0`) | Partial | `api/schemas.py` — `quantity > 0` validated; `price > 0` (strict); domain `Holding.apply_delta` validates sell quantity | `price >= 0` is stricter (`> 0`) at API layer; domain allows zero-price dividend-type entries if coded directly |
| **C1** Per-user alert preference storage | Missing | No `alert_preferences` table, model, repo, or use case | Entire feature absent |
| **C2** Per-entity suppression/opt-out | Missing | No entity suppression data model | Blocked on C1 |
| **C3** Alert pref read/write API | Missing | No `api/routes/alert_preferences.py` | Blocked on C1 |
| **C4** Alert pref read by alerting service | Missing | No internal application port for external service query | Unknown consumer; no documented interface |
| **D1** Producer wiring in mutation path | Complete | `application/use_cases/create_portfolio.py`, `record_transaction.py`, `portfolio_ops.py` — all write `OutboxRecord` to DB in same transaction | Outbox pattern correctly applied |
| **D2** Versioned topic names | Complete | `messaging/topics.py` — `portfolio.events.v1`; `infra/kafka/init/create-topics.sh` — `portfolio.events.v1:3:1` | Watchlist topic absent |
| **D3** Schema compatibility | Complete | 8 `.avsc` files in `messaging/schemas/`; contract tests for all 8 | No watchlist schema |
| **D4** Retry/error handling for publish failures | Complete | `libs/messaging` `BaseOutboxDispatcher` handles retries; `OutboxRepository` implements `increment_attempts`, `move_to_dead_letter` | Max attempts = 10, configurable |
| **D5** Idempotency/duplicate handling | Complete | `consumers/instrument_consumer.py` uses `is_duplicate` / `mark_processed` via `IdempotencyRepository` | Only the consumer is idempotent; outbox events themselves use `external_ref` uniqueness |
| **E1** All required tables migrated | Partial | `alembic/versions/0001_initial_schema.py` — 7 tables present for existing scope; watchlist, alert_prefs, entity_id cols missing | `alembic check` would produce a non-empty diff |
| **E2** Indexes on FKs and high-freq WHERE | Partial | `ix_portfolios_tenant_id`, `ix_transactions_tenant_id`, `ix_transactions_portfolio_id`, `ix_holdings_portfolio_id` present; `instruments` table has no index on `id` (PK covers it) but missing index on `symbol` for lookups; watchlist member indexes absent | |
| **E3** Uniqueness constraints for watchlist membership | Missing | `watchlist_members` table absent | Required to prevent duplicate entity enrollment |
| **E4** ORM/migration/table drift | Exists (minor) | `HoldingModel.updated_at` column has no index; `outbox_events` table has no index on `(status, lease_expires)` — critical for `claim_batch` performance | `claim_batch` does `WHERE status='pending' AND (lease_expires IS NULL OR lease_expires < now())` without a covering index |
| **F1** Request/response schemas complete | Partial | Existing 14 Pydantic schemas are complete; no pagination wrappers | No `ListWatchlistsResponse`, `AlertPreferenceResponse` |
| **F2** Error responses consistent | Complete | `ErrorResponse` model + `domain_error_to_status` MRO walker | |
| **F3** Pagination for unbounded lists | Missing | `api/routes/portfolio.py` — `list_portfolios` returns `list[PortfolioResponse]` unbounded; `api/routes/instrument.py` — `list_all` unbounded; `api/routes/transaction.py` — list unbounded | No `limit`/`offset` or cursor parameters |
| **F4** Auth/tenant scoping | Partial | `X-Tenant-ID` header required on all mutating routes; `X-Owner-ID` required for portfolio reads; no JWT/session auth — relies on gateway to inject headers | No validation that `X-Owner-ID` actually belongs to `X-Tenant-ID` at API boundary |
| **G1** Structured logging around mutations | Complete | All use cases call `logger.info` with `tenant_id`, `portfolio_id` | No watchlist or alert-pref log events |
| **G2** Logging around publish outcomes | Partial | Outbox dispatcher logs via `libs/messaging` base; no service-level publish logging in portfolio-specific code | |
| **G3** Metrics/tracing hooks | Partial | `create_metrics` + `add_prometheus_middleware` + `add_otel_middleware` in `app.py`; no custom counters for watchlist/transaction counts | Only HTTP RED metrics via middleware; no domain-level counters |
| **G4** Config vars present and documented | Partial | `config.py` — `valkey_url`, `kafka_*`, `storage_*`, `otlp_endpoint` all present; no `watchlist_cache_ttl_seconds`, `alert_pref_cache_ttl_seconds` | `dev.local.env.example` state unknown (not read) |

---

## 4. Detailed Gap Descriptions

### Gap A: Watchlist Management (Entirely Missing)

#### A1–A6 Current State

There is no file, class, function, table, migration, Avro schema, or test related to watchlists
anywhere in the portfolio service. The `config.py` has `valkey_url` set but the `app.py`
lifespan never creates a `ValkeyClient` instance. The `libs/messaging` library ships a
fully-functional `ValkeyClient` at `libs/messaging/src/messaging/valkey/client.py`.

#### Missing / Incomplete Behaviour

1. No endpoint to create/read/update/delete a watchlist.
2. No endpoint to add/remove a canonical entity to/from a watchlist.
3. No reverse-index lookup `entity_id → [user_id, ...]` for alert fanout.
4. No `portfolio.watchlist.updated.v1` Kafka events on membership changes.
5. No Valkey key `pf:v1:watchlist:entity:{entity_id}` (or equivalent) to cache reverse-index.
6. No invalidation of the reverse-index when a member is added or removed.

#### Files to Create

| Path | Purpose |
|------|---------|
| `src/portfolio/domain/entities/watchlist.py` | `Watchlist` entity |
| `src/portfolio/domain/entities/watchlist_member.py` | `WatchlistMember` entity |
| `src/portfolio/domain/events.py` (modify) | Add `WatchlistItemAdded`, `WatchlistItemRemoved` |
| `src/portfolio/domain/errors.py` (modify) | Add `WatchlistNotFoundError`, `WatchlistMemberAlreadyExistsError`, `WatchlistMemberNotFoundError` |
| `src/portfolio/domain/enums.py` (modify) | Add `WatchlistStatus` |
| `src/portfolio/application/ports/repositories.py` (modify) | Add `WatchlistRepository`, `WatchlistMemberRepository` ABCs |
| `src/portfolio/application/ports/unit_of_work.py` (modify) | Add `watchlists`, `watchlist_members` properties |
| `src/portfolio/application/use_cases/watchlist.py` | 6 use cases (create, get, list, delete, add_member, remove_member) |
| `src/portfolio/infrastructure/db/models/watchlist.py` | `WatchlistModel` ORM |
| `src/portfolio/infrastructure/db/models/watchlist_member.py` | `WatchlistMemberModel` ORM |
| `src/portfolio/infrastructure/db/repositories/watchlist.py` | `SqlAlchemyWatchlistRepository` |
| `src/portfolio/infrastructure/db/repositories/watchlist_member.py` | `SqlAlchemyWatchlistMemberRepository` |
| `src/portfolio/infrastructure/db/unit_of_work.py` (modify) | Wire new repos |
| `src/portfolio/infrastructure/cache/watchlist_cache.py` | Valkey reverse-index write/invalidate/read |
| `src/portfolio/api/schemas.py` (modify) | Add watchlist request/response schemas |
| `src/portfolio/api/routes/watchlist.py` | 6 endpoints |
| `src/portfolio/api/routes/__init__.py` (modify) | Register watchlist router |
| `src/portfolio/messaging/topics.py` (modify) | Add `portfolio.watchlist.updated.v1` entry |
| `src/portfolio/messaging/mapper.py` (modify) | Add `watchlist_item_added_to_dict`, `watchlist_item_removed_to_dict` |
| `src/portfolio/messaging/serialization.py` (modify) | Add watchlist event schemas |
| `src/portfolio/messaging/schemas/watchlist.item_added.avsc` | New Avro schema |
| `src/portfolio/messaging/schemas/watchlist.item_removed.avsc` | New Avro schema |
| `alembic/versions/0002_add_watchlists.py` | New migration |
| `src/portfolio/app.py` (modify) | Instantiate `ValkeyClient` in lifespan |
| `src/portfolio/config.py` (modify) | Add `watchlist_cache_ttl_seconds` |

#### DB Design Required

**Table: `watchlists`**

| Column | Type | Nullability | Notes |
|--------|------|-------------|-------|
| `id` | `UUID` (PK) | NOT NULL | UUIDv7 |
| `tenant_id` | `UUID` (FK → `tenants.id`) | NOT NULL | Tenant scoping |
| `user_id` | `UUID` (FK → `users.id`) | NOT NULL | Owner |
| `name` | `TEXT` | NOT NULL | User-visible label |
| `status` | `VARCHAR(20)` | NOT NULL DEFAULT `'active'` | |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT `now()` | |

Indexes:
- `ix_watchlists_user_id` on `(user_id)`
- `ix_watchlists_tenant_id` on `(tenant_id)`
- `uq_watchlists_user_name` UNIQUE on `(user_id, name)` — prevents duplicate names per user

**Table: `watchlist_members`**

| Column | Type | Nullability | Notes |
|--------|------|-------------|-------|
| `id` | `UUID` (PK) | NOT NULL | UUIDv7 |
| `watchlist_id` | `UUID` (FK → `watchlists.id`) | NOT NULL | |
| `entity_id` | `UUID` | NOT NULL | Canonical KG entity ID (no FK — cross-service) |
| `entity_type` | `VARCHAR(50)` | NOT NULL DEFAULT `'company'` | e.g. `company`, `person`, `topic` |
| `added_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT `now()` | |

Indexes:
- `uq_watchlist_members_watchlist_entity` UNIQUE on `(watchlist_id, entity_id)` — prevents duplicate enrollment
- `ix_watchlist_members_entity_id` on `(entity_id)` — powers reverse-index lookup (alert fanout)
- `ix_watchlist_members_watchlist_id` on `(watchlist_id)` — powers list-members query

**No FK to an external entity table** — entity_id references the Knowledge Graph service's
namespace; cross-service FK would violate R7.

#### API Contract Required

```
POST   /api/v1/watchlists
GET    /api/v1/watchlists                       (list by user, via X-Owner-ID header)
GET    /api/v1/watchlists/{watchlist_id}
DELETE /api/v1/watchlists/{watchlist_id}
POST   /api/v1/watchlists/{watchlist_id}/members
DELETE /api/v1/watchlists/{watchlist_id}/members/{entity_id}
GET    /api/v1/watchlists/reverse/{entity_id}   (returns user_ids tracking this entity)
```

**POST /api/v1/watchlists** — Request:
```json
{ "name": "My Tech Watchlist" }
```
Headers: `X-Tenant-ID`, `X-Owner-ID`
Response 201:
```json
{
  "id": "uuid",
  "tenant_id": "uuid",
  "user_id": "uuid",
  "name": "My Tech Watchlist",
  "status": "active",
  "created_at": "ISO-8601"
}
```
Error cases: 409 (`WatchlistAlreadyExistsError` — duplicate name per user), 404 (`UserNotFoundError`).

**POST /api/v1/watchlists/{watchlist_id}/members** — Request:
```json
{ "entity_id": "uuid", "entity_type": "company" }
```
Response 201:
```json
{ "id": "uuid", "watchlist_id": "uuid", "entity_id": "uuid", "entity_type": "company", "added_at": "ISO-8601" }
```
Error cases: 404 (watchlist not found), 409 (`WatchlistMemberAlreadyExistsError`), 403 (not owner).

**DELETE /api/v1/watchlists/{watchlist_id}/members/{entity_id}** — Response 204 No Content.
Error cases: 404 (member not found), 403 (not owner).

**GET /api/v1/watchlists/reverse/{entity_id}** — Response 200:
```json
{ "entity_id": "uuid", "user_ids": ["uuid", ...] }
```
Cache-Control: private (user-specific data).
Note: This endpoint exposes cross-user data; access must be restricted to service-internal
calls or a privileged API key. **This is an open question — see Section 6.**

#### Messaging Contract Required

**New topic**: `portfolio.watchlist.updated.v1`
Key: `aggregate_id` (watchlist_id)
Retention: 7 days, 3 partitions
Schema version: 1

Two event types on the same topic:

**`watchlist.item_added`** — `watchlist.item_added.avsc`:
```json
{
  "type": "record",
  "name": "watchlist.item_added",
  "namespace": "portfolio.events",
  "fields": [
    {"name": "event_id", "type": "string"},
    {"name": "event_type", "type": "string", "default": "watchlist.item_added"},
    {"name": "aggregate_type", "type": "string", "default": "watchlist"},
    {"name": "aggregate_id", "type": "string"},
    {"name": "tenant_id", "type": "string"},
    {"name": "occurred_at", "type": "string"},
    {"name": "schema_version", "type": "int", "default": 1},
    {"name": "correlation_id", "type": ["null", "string"], "default": null},
    {"name": "causation_id", "type": ["null", "string"], "default": null},
    {"name": "watchlist_id", "type": "string", "default": ""},
    {"name": "user_id", "type": "string", "default": ""},
    {"name": "entity_id", "type": "string", "default": ""},
    {"name": "entity_type", "type": "string", "default": "company"}
  ]
}
```

**`watchlist.item_removed`** — `watchlist.item_removed.avsc`: same envelope fields with the
same `watchlist_id`, `user_id`, `entity_id`, `entity_type`.

Both events MUST be written to the outbox in the same DB transaction as the membership
insert/delete (R8 compliance).

#### Cache Strategy Required

**Valkey key**: `pf:v1:watchlist:entity:{entity_id}` → JSON array of `user_id` strings
**TTL**: 300 seconds (configurable via `PORTFOLIO_WATCHLIST_CACHE_TTL_SECONDS`)
**Invalidation trigger**: on every `add_member` and `remove_member` use case execution,
the cache key for the affected `entity_id` must be deleted (DEL) before the DB commit
completes, or the add/remove member use case must write-through the new set after commit.

**Recommended strategy**: delete-on-mutation (simpler, avoids stale reads). The alert service
reads through: cache hit → return; cache miss → call `GET /api/v1/watchlists/reverse/{entity_id}`
which repopulates the cache.

**Write-through path** (for lower latency):
```
add_member commit → ValkeyClient.sadd(key, user_id) + EXPIRE
remove_member commit → ValkeyClient.srem(key, user_id)
```
Use Redis Sets (`SADD`/`SREM`) rather than JSON arrays for atomic incremental updates.

**Key naming** conforms to MASTER_PLAN §5.3 convention: `{scope}:{version}:{resource}:{id}`.

#### Dependencies

- `libs/messaging` `ValkeyClient` (`messaging.valkey.client`) — already exists
- `infra/kafka/init/create-topics.sh` — add `portfolio.watchlist.updated.v1:3:1`
- Alert service (S10, future) — consumes `portfolio.watchlist.updated.v1`
- Knowledge Graph service (S7) — produces canonical `entity_id` values; no FK required

#### Required Tests

| Test | Type | Pass Evidence |
|------|------|--------------|
| `test_domain_watchlist.py` — entity creation, status transitions, member validation | Unit | pytest green |
| `test_use_cases_watchlist.py` — create/get/list/delete/add_member/remove_member with FakeUoW | Unit | pytest green |
| `test_watchlist_events.py` — `WatchlistItemAdded.to_dict()` round-trip | Unit | pytest green |
| `test_watchlist_item_added_contract.py` — Avro round-trip | Contract | pytest green |
| `test_watchlist_item_removed_contract.py` — Avro round-trip | Contract | pytest green |
| `test_watchlist_api.py` — all 7 endpoints via TestClient with testcontainers Postgres | Integration | pytest green |
| `test_watchlist_cache.py` — `WatchlistCacheClient.get_user_ids`, invalidation | Unit (fakeredis) | pytest green |
| `test_reverse_index_lookup.py` — add member → cache populated; remove → invalidated | Integration | pytest green |

---

### Gap B1: Position Model — Missing `entity_id` Link to Knowledge Graph

#### Current State

`domain/entities/holding.py` (class `Holding`) has: `portfolio_id`, `instrument_id`,
`quantity` (Decimal 18,8), `average_cost` (Decimal 18,8), `currency`, `id`, `updated_at`.

`domain/entities/instrument.py` (class `InstrumentRef`) has: `symbol`, `exchange`,
`source_event_id`, `name`, `currency`, `asset_class`, `id`, `synced_at`.

Neither entity has a `entity_id` field linking to the Knowledge Graph canonical entity
namespace.

#### Missing / Incomplete Behaviour

The Intelligence Layer (S7) assigns canonical `entity_id` values to companies/instruments
after NLP entity linking. Without this field, it is impossible to:
- Join a user's holdings to their watchlist (watchlist tracks `entity_id`; holding tracks `instrument_id`)
- Retrieve all holdings in a portfolio that belong to entities on a watchlist
- Power the "portfolio vs. watchlist overlap" intelligence feature

There is also no `asset_type` field on `Holding` — the API gateway composition endpoint
`GET /api/v1/portfolios/{id}/holdings` (which merges portfolio holdings with Market Data
prices) would need this to return typed positions.

#### Files to Modify

- `src/portfolio/domain/entities/instrument.py` — add `entity_id: UUID | None = None`
- `src/portfolio/infrastructure/db/models/instrument.py` — add `entity_id` nullable column
- `alembic/versions/0003_add_entity_id_to_instruments.py` — new migration (additive, nullable)
- `src/portfolio/consumers/instrument_consumer.py` — read `entity_id` from
  `market.instrument.created` event payload (if Market Data publishes it)
- `src/portfolio/messaging/schemas/instrument_ref.created.avsc` — add `entity_id` field with null default
- `src/portfolio/messaging/mapper.py` — include `entity_id` in `instrument_ref_created_to_dict`

Note: `Holding` itself should NOT store `entity_id` directly — the `instrument_id` FK is the
join key. The `entity_id` should live on `InstrumentRef` and be resolved at query time.

#### DB Design Required

**Alter table `instruments`** — additive:
```sql
ALTER TABLE instruments ADD COLUMN entity_id UUID NULL;
CREATE INDEX ix_instruments_entity_id ON instruments (entity_id) WHERE entity_id IS NOT NULL;
```

#### Required Tests

| Test | Pass Evidence |
|------|--------------|
| `test_domain_entities.py` — `InstrumentRef` with `entity_id` field | Unit green |
| `test_instrument_ref_created_contract.py` — Avro includes `entity_id` with null default | Contract green |
| `test_instrument_api.py` — GET instrument response includes `entity_id` | Integration green |

---

### Gap B3: Validation Rules — Strict `price > 0` vs. `price >= 0`

#### Current State

`api/schemas.py` `RecordTransactionRequest.validate_price`: raises `ValueError` if `price <= 0`
(meaning price must be strictly positive). The domain `Holding.apply_delta` does not validate
price independently.

#### Missing / Incomplete Behaviour

Dividend transactions and certain fee adjustments legitimately have `price = 0`. The current
API-level validator would reject them with a 422. The doc comment in `portfolio.md`
states `price >= 0`, contradicting the implementation.

#### Files to Modify

- `src/portfolio/api/schemas.py` — change validator to `price < 0` (allow zero)
- `src/portfolio/domain/errors.py` — add `InvalidPriceError`

#### Required Tests

| Test | Pass Evidence |
|------|--------------|
| `test_use_cases_transaction.py` — BUY with price=0 accepted for dividend path | Unit green |
| `test_transaction_api.py` — POST with price=0 returns 201 for DIVIDEND type | Integration green |

---

### Gap C: Alert Subscriptions (Entirely Missing)

#### Current State

There is no alert preference entity, table, repository, use case, API endpoint, or schema
anywhere in the portfolio service.

#### Missing / Incomplete Behaviour

1. No per-user per-alert-type preference (enabled/disabled for `signal`, `contradiction`,
   `confidence_drop`, `new_event`).
2. No per-entity suppression (user opts out of alerts for specific entity_id).
3. No read endpoint for the alerting service to query preferences.
4. No Kafka event when preferences change (alerting service cannot react to changes without polling).

#### Files to Create

| Path | Purpose |
|------|---------|
| `src/portfolio/domain/entities/alert_preference.py` | `AlertPreference`, `EntitySuppression` entities |
| `src/portfolio/domain/enums.py` (modify) | Add `AlertType` StrEnum |
| `src/portfolio/domain/errors.py` (modify) | Add `AlertPreferenceNotFoundError` |
| `src/portfolio/application/ports/repositories.py` (modify) | Add `AlertPreferenceRepository` ABC |
| `src/portfolio/application/ports/unit_of_work.py` (modify) | Add `alert_preferences` property |
| `src/portfolio/application/use_cases/alert_preferences.py` | `GetAlertPreferences`, `UpsertAlertPreferences`, `SetEntitySuppression` |
| `src/portfolio/infrastructure/db/models/alert_preference.py` | `AlertPreferenceModel` ORM |
| `src/portfolio/infrastructure/db/models/entity_suppression.py` | `EntitySuppressionModel` ORM |
| `src/portfolio/infrastructure/db/repositories/alert_preference.py` | `SqlAlchemyAlertPreferenceRepository` |
| `src/portfolio/infrastructure/db/unit_of_work.py` (modify) | Wire new repo |
| `src/portfolio/api/schemas.py` (modify) | Add `AlertPreferenceRequest/Response`, `EntitySuppressionRequest/Response` |
| `src/portfolio/api/routes/alert_preferences.py` | 4 endpoints |
| `src/portfolio/api/routes/__init__.py` (modify) | Register new router |
| `alembic/versions/0004_add_alert_preferences.py` | New migration |

#### DB Design Required

**Table: `alert_preferences`**

| Column | Type | Nullability | Notes |
|--------|------|-------------|-------|
| `id` | `UUID` (PK) | NOT NULL | UUIDv7 |
| `tenant_id` | `UUID` (FK → `tenants.id`) | NOT NULL | |
| `user_id` | `UUID` (FK → `users.id`) | NOT NULL | |
| `alert_type` | `VARCHAR(50)` | NOT NULL | `signal`, `contradiction`, `confidence_drop`, `new_event` |
| `enabled` | `BOOLEAN` | NOT NULL DEFAULT `true` | |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT `now()` | |

Constraints:
- `uq_alert_preferences_user_type` UNIQUE on `(user_id, alert_type)`
- `ix_alert_preferences_user_id` index on `(user_id)` — primary access pattern

**Table: `entity_suppressions`**

| Column | Type | Nullability | Notes |
|--------|------|-------------|-------|
| `id` | `UUID` (PK) | NOT NULL | UUIDv7 |
| `tenant_id` | `UUID` (FK → `tenants.id`) | NOT NULL | |
| `user_id` | `UUID` (FK → `users.id`) | NOT NULL | |
| `entity_id` | `UUID` | NOT NULL | KG canonical entity ID |
| `suppressed_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT `now()` | |

Constraints:
- `uq_entity_suppressions_user_entity` UNIQUE on `(user_id, entity_id)`
- `ix_entity_suppressions_user_id` index on `(user_id)`
- `ix_entity_suppressions_entity_id` index on `(entity_id)` — for bulk query by alerting service

#### API Contract Required

```
GET    /api/v1/alert-preferences              (for authenticated user via X-Owner-ID)
PUT    /api/v1/alert-preferences/{alert_type} (upsert a preference)
POST   /api/v1/alert-preferences/suppressions (suppress an entity)
DELETE /api/v1/alert-preferences/suppressions/{entity_id} (un-suppress)
```

**GET /api/v1/alert-preferences** — Response 200:
```json
{
  "preferences": [
    {"alert_type": "signal", "enabled": true},
    {"alert_type": "contradiction", "enabled": false},
    ...
  ],
  "suppressions": [
    {"entity_id": "uuid", "suppressed_at": "ISO-8601"}
  ]
}
```

**PUT /api/v1/alert-preferences/{alert_type}** — Request: `{ "enabled": false }`
Response 200: `{ "alert_type": "signal", "enabled": false, "updated_at": "ISO-8601" }`
Error cases: 422 (invalid `alert_type`), 404 (`UserNotFoundError`).

Note: Alert preferences should also be readable by the alerting service (S10) through a
service-to-service call, likely via the API Gateway. The access control model (whether S10
calls Portfolio directly or via Gateway) is an open question — see Section 6.

#### Required Tests

| Test | Pass Evidence |
|------|--------------|
| `test_domain_alert_preference.py` | Unit green |
| `test_use_cases_alert_preferences.py` — get/upsert/suppress/unsuppress with FakeUoW | Unit green |
| `test_alert_preferences_api.py` — all 4 endpoints | Integration green |

---

### Gap D2/D5: Watchlist Topic and Schema Absent from Kafka Infrastructure

#### Current State

`infra/kafka/init/create-topics.sh` lists 8 topics; `portfolio.watchlist.updated.v1` is absent.

`infra/kafka/schemas/` has 8 `.avsc` files; no watchlist Avro schemas.

#### Missing / Incomplete Behaviour

When the add_member or remove_member use cases are implemented, they will write to the outbox.
The dispatcher will attempt to deliver to a topic that does not exist in Kafka — messages will
fail or block.

#### Files to Modify

- `infra/kafka/init/create-topics.sh` — add `portfolio.watchlist.updated.v1:3:1`
- `infra/kafka/schemas/watchlist.item_added.avsc` — create (same content as
  `messaging/schemas/watchlist.item_added.avsc` — these should be symlinked or identical)
- `infra/kafka/schemas/watchlist.item_removed.avsc` — create

Note: The portfolio service stores its Avro schemas locally in `messaging/schemas/` (not in
`infra/kafka/schemas/`). The `infra/kafka/schemas/` files are for the global schema registry
registration script (`infra/kafka/init/register-schemas.py`). Both locations must be updated.

#### Required Tests

- Contract test: serialize `watchlist.item_added` event dict against local `.avsc` → success
- Contract test: serialize `watchlist.item_removed` event dict → success

---

### Gap E4: Missing Performance Indexes

#### Current State

The `outbox_events` table (created in `0001_initial_schema.py`) has no index on
`(status, lease_expires)`. The `claim_batch` query in `SqlAlchemyOutboxRepository`
(`infrastructure/db/repositories/outbox.py` line 58–66) does:
```sql
WHERE status = 'pending'
  AND (lease_expires IS NULL OR lease_expires < now())
LIMIT batch_size
FOR UPDATE SKIP LOCKED
```
Without an index on `(status, lease_expires)`, this becomes a full table scan as the outbox
grows, degrading dispatcher throughput.

#### Files to Modify

- `alembic/versions/0002_add_watchlists.py` or a dedicated `alembic/versions/000X_add_outbox_index.py`

Migration SQL:
```sql
CREATE INDEX ix_outbox_events_status_lease_expires
ON outbox_events (status, lease_expires NULLS FIRST)
WHERE status IN ('pending', 'processing');
```

#### Required Tests

None blocking, but load/performance tests should validate claim_batch stays under 5ms with
1K+ pending records.

---

### Gap F3: Pagination for Unbounded List Endpoints

#### Current State

Three endpoints return unbounded lists:
- `GET /api/v1/portfolios` (`list_portfolios` via `ListPortfoliosUseCase.execute`)
- `GET /api/v1/instruments` (`list_all_instruments` via `ListInstrumentsUseCase.execute`)
- `GET /api/v1/transactions` (`list_transactions` via `ListTransactionsUseCase.execute`)

None accept `limit`, `offset`, or cursor query parameters.

#### Missing / Incomplete Behaviour

As instrument count grows (thousands of instruments synced from Market Data), these endpoints
will return arbitrarily large payloads, causing OOM in the API process and gateway timeouts.

#### Files to Modify

- `src/portfolio/api/schemas.py` — add `PaginatedResponse[T]` generic wrapper
- `src/portfolio/api/routes/portfolio.py` — add `limit: int = 100`, `offset: int = 0`
- `src/portfolio/api/routes/instrument.py` — same
- `src/portfolio/api/routes/transaction.py` — same
- `src/portfolio/application/ports/repositories.py` — update list ABCs with `limit`/`offset`
- `src/portfolio/infrastructure/db/repositories/` — update SQL queries with `.limit().offset()`

#### API Contract Change

This is a non-breaking addition (new optional query params with defaults). No version bump
required per R6.

---

### Gap G3: Domain-Level Metrics Missing

#### Current State

`app.py` adds Prometheus middleware (`add_prometheus_middleware`) which provides HTTP RED
metrics. No custom counters or gauges are defined for business events.

#### Missing / Incomplete Behaviour

No counters for:
- Transactions recorded by type
- Holdings created/updated
- Watchlist members added/removed
- Alert preferences changed
- Kafka events published (from outbox)

These are referenced in `portfolio.md` § Observability but not implemented.

#### Files to Modify

- `src/portfolio/app.py` — create custom `Counter` and `Gauge` objects
- `src/portfolio/application/use_cases/*.py` — increment counters in use case execute methods

---

## 5. Prioritized Implementation Plan

Dependencies flow: A1 domain → A2 DB → A3 repos/UoW → A4 use cases → A5 API → A6 cache/events.

### Task W-001: Add Watchlist Domain Entities and Events

**ID**: W-001
**Title**: Implement `Watchlist`, `WatchlistMember` domain entities and events
**Objective**: Create the pure domain model for watchlists
**Depends_on**: None
**Can_run_with**: C-001 (alert pref domain, independently)
**Target paths**:
- `src/portfolio/domain/entities/watchlist.py`
- `src/portfolio/domain/entities/watchlist_member.py`
- `src/portfolio/domain/events.py` (modify)
- `src/portfolio/domain/errors.py` (modify)
- `src/portfolio/domain/enums.py` (modify)

**Implementation steps**:
1. Add `WatchlistStatus` StrEnum (`active`, `deleted`) to `enums.py`.
2. Create `Watchlist` frozen dataclass: `id` (UUIDv7), `tenant_id`, `user_id`, `name`, `status`, `created_at`. Add `is_active()` method.
3. Create `WatchlistMember` frozen dataclass: `id` (UUIDv7), `watchlist_id`, `entity_id` (UUID), `entity_type` (str), `added_at`.
4. Add to `events.py`: `WatchlistItemAdded(DomainEvent)` with `watchlist_id`, `user_id`, `entity_id`, `entity_type`; `WatchlistItemRemoved` with same fields.
5. Add to `errors.py`: `WatchlistNotFoundError`, `WatchlistMemberNotFoundError`, `WatchlistMemberAlreadyExistsError`, `WatchlistAlreadyExistsError`.

**Tests required**: `tests/unit/test_domain_watchlist.py` — entity creation, error hierarchy, event fields
**Effort**: Small

---

### Task W-002: Add Watchlist Repository Ports and UoW Properties

**ID**: W-002
**Title**: Add `WatchlistRepository` and `WatchlistMemberRepository` ABCs
**Objective**: Define the application layer ports for watchlist storage
**Depends_on**: W-001
**Can_run_with**: C-002
**Target paths**:
- `src/portfolio/application/ports/repositories.py` (modify)
- `src/portfolio/application/ports/unit_of_work.py` (modify)
- `tests/unit/fakes.py` (modify)

**Implementation steps**:
1. Add `WatchlistRepository` ABC: `get(id, tenant_id) → Watchlist | None`, `list_by_user(user_id, tenant_id) → list[Watchlist]`, `save(watchlist)`, `delete(id)`.
2. Add `WatchlistMemberRepository` ABC: `get(watchlist_id, entity_id) → WatchlistMember | None`, `list_by_watchlist(watchlist_id) → list[WatchlistMember]`, `list_by_entity(entity_id) → list[WatchlistMember]` (reverse-index query), `save(member)`, `delete(watchlist_id, entity_id)`.
3. Add `watchlists: WatchlistRepository` and `watchlist_members: WatchlistMemberRepository` abstract properties to `UnitOfWork`.
4. Add `FakeWatchlistRepository` and `FakeWatchlistMemberRepository` to `tests/unit/fakes.py`. Wire them into `FakeUnitOfWork`.

**Tests required**: No new test file needed — fakes are tested implicitly by W-004
**Effort**: Small

---

### Task W-003: Add Watchlist DB Migration, ORM Models, and Repositories

**ID**: W-003
**Title**: Implement watchlist database layer
**Objective**: Create `watchlists` and `watchlist_members` tables and SQLAlchemy implementations
**Depends_on**: W-002
**Can_run_with**: C-003
**Target paths**:
- `src/portfolio/infrastructure/db/models/watchlist.py`
- `src/portfolio/infrastructure/db/models/watchlist_member.py`
- `src/portfolio/infrastructure/db/repositories/watchlist.py`
- `src/portfolio/infrastructure/db/repositories/watchlist_member.py`
- `src/portfolio/infrastructure/db/unit_of_work.py` (modify)
- `src/portfolio/infrastructure/db/models/__init__.py` (modify)
- `alembic/versions/0002_add_watchlists.py`

**Implementation steps**:
1. Create `WatchlistModel(Base)` with columns per Section 4-A DB design.
2. Create `WatchlistMemberModel(Base)` with columns per Section 4-A DB design. Include the `UNIQUE` constraint on `(watchlist_id, entity_id)` using `NULLS NOT DISTINCT` pattern (see BP-007 — no nullable columns in this case, so standard `UniqueConstraint` is safe).
3. Create `alembic/versions/0002_add_watchlists.py` using `op.create_table` for both tables with all indexes. Also add `CREATE INDEX ix_outbox_events_status_lease` for Gap E4 in this migration.
4. Implement `SqlAlchemyWatchlistRepository` with standard `get`, `list_by_user`, `save`, `delete` patterns matching existing repo implementations.
5. Implement `SqlAlchemyWatchlistMemberRepository`. `list_by_entity` performs `SELECT * FROM watchlist_members JOIN watchlists ON ... WHERE entity_id = :entity_id AND watchlists.status = 'active'` to get `user_id` values via join.
6. Wire both repos into `SqlAlchemyUnitOfWork.__aenter__` and add matching properties.
7. Register both models in `db/models/__init__.py`.
8. Run `alembic check` to verify migration produces empty diff.

**Tests required**: `tests/integration/test_watchlist_api.py` (placeholder, tested properly in W-006)
**Docs updates**: None yet — update `docs/services/portfolio.md` at W-006
**Effort**: Medium

---

### Task W-004: Implement Watchlist Use Cases

**ID**: W-004
**Title**: Implement all 6 watchlist use cases
**Objective**: Business logic for watchlist CRUD and membership management
**Depends_on**: W-002
**Can_run_with**: Nothing else (core logic)
**Target paths**:
- `src/portfolio/application/use_cases/watchlist.py`

**Implementation steps**:
1. `CreateWatchlistUseCase` — validate user active, check name uniqueness, create `Watchlist`, write `WatchlistCreated` outbox event (use `portfolio.events.v1` topic).
2. `GetWatchlistUseCase` — fetch by id+tenant, auth check (owner only), raise `WatchlistNotFoundError`.
3. `ListWatchlistsUseCase` — `list_by_user(owner_id, tenant_id)`.
4. `DeleteWatchlistUseCase` — soft-delete by setting `status=deleted`, write `WatchlistDeleted` outbox event.
5. `AddWatchlistMemberUseCase` — check watchlist exists and is active, check member doesn't already exist (raise `WatchlistMemberAlreadyExistsError`), create `WatchlistMember`, write `WatchlistItemAdded` outbox event to `portfolio.watchlist.updated.v1` topic, **invalidate Valkey cache key `pf:v1:watchlist:entity:{entity_id}`**.
6. `RemoveWatchlistMemberUseCase` — fetch member (raise `WatchlistMemberNotFoundError` if absent), delete, write `WatchlistItemRemoved` outbox event, invalidate Valkey cache.

**Cache dependency**: Steps 5 and 6 require a `WatchlistCachePort` (abstract) injected into the use case. This follows the hexagonal pattern — the use case calls `await cache.invalidate_entity(entity_id)`. The concrete `ValkeyWatchlistCache` is wired by the API dependency.

**Tests required**: `tests/unit/test_use_cases_watchlist.py` — 12+ test functions covering happy path, error cases, outbox event types, cache invalidation call
**Effort**: Medium

---

### Task W-005: Implement Watchlist Avro Schemas and Messaging

**ID**: W-005
**Title**: Add watchlist Avro schemas and wire messaging
**Objective**: Enable outbox dispatcher to serialize watchlist events
**Depends_on**: W-001
**Can_run_with**: W-003, W-004
**Target paths**:
- `src/portfolio/messaging/schemas/watchlist.item_added.avsc`
- `src/portfolio/messaging/schemas/watchlist.item_removed.avsc`
- `src/portfolio/messaging/topics.py` (modify)
- `src/portfolio/messaging/mapper.py` (modify)
- `src/portfolio/messaging/serialization.py` (modify)
- `infra/kafka/schemas/watchlist.item_added.avsc`
- `infra/kafka/schemas/watchlist.item_removed.avsc`
- `infra/kafka/init/create-topics.sh` (modify)

**Implementation steps**:
1. Create the two `.avsc` files per schema in Section 4-A Messaging Contract.
2. Copy identical content to `infra/kafka/schemas/` (the global registry registration script reads from there).
3. Add `"watchlist.item_added": WATCHLIST_UPDATED_V1` and `"watchlist.item_removed": WATCHLIST_UPDATED_V1` to `EVENT_TOPIC_MAP` in `topics.py`. Add `WATCHLIST_UPDATED_V1 = "portfolio.watchlist.updated.v1"` constant.
4. Add `watchlist_item_added_to_dict` and `watchlist_item_removed_to_dict` mappers to `mapper.py`.
5. Add both event types to `_AVSC_MAP` in `serialization.py`.
6. Add `portfolio.watchlist.updated.v1:3:1` to `create-topics.sh`.

**Tests required**:
- `tests/contract/test_watchlist_item_added_contract.py`
- `tests/contract/test_watchlist_item_removed_contract.py`
**Effort**: Small

---

### Task W-006: Implement Watchlist API Endpoints

**ID**: W-006
**Title**: Add 7 watchlist REST endpoints
**Objective**: Expose watchlist management to the API Gateway and alert service
**Depends_on**: W-004, W-005
**Target paths**:
- `src/portfolio/api/schemas.py` (modify)
- `src/portfolio/api/routes/watchlist.py`
- `src/portfolio/api/routes/__init__.py` (modify)

**Implementation steps**:
1. Add `WatchlistCreateRequest`, `WatchlistResponse`, `WatchlistMemberCreateRequest`, `WatchlistMemberResponse`, `ReverseIndexResponse` to `schemas.py`.
2. Implement all 7 endpoints per Section 4-A API Contract. All endpoints require `X-Tenant-ID` and `X-Owner-ID` headers. The reverse-index endpoint (`GET /api/v1/watchlists/reverse/{entity_id}`) should require a service API key header distinct from the regular user headers.
3. Add `from portfolio.api.routes.watchlist import router as watchlist_router` and `api_router.include_router(watchlist_router)` to `routes/__init__.py`.
4. Add `watchlist_not_found`, `watchlist_member_already_exists` to `error_mapping.py`.

**Tests required**: `tests/integration/test_watchlist_api.py` — all 7 endpoints, auth failures, duplicate member rejection, reverse lookup
**Docs updates**: `docs/services/portfolio.md` — add watchlist endpoint table
**Effort**: Medium

---

### Task W-007: Implement Valkey Reverse-Index Cache

**ID**: W-007
**Title**: Wire ValkeyClient and implement watchlist reverse-index cache
**Objective**: Sub-10ms `entity_id → user_ids` lookup for alert fanout
**Depends_on**: W-004, W-006
**Target paths**:
- `src/portfolio/infrastructure/cache/watchlist_cache.py`
- `src/portfolio/application/ports/cache.py` (new)
- `src/portfolio/app.py` (modify)
- `src/portfolio/api/dependencies.py` (modify)
- `src/portfolio/config.py` (modify)

**Implementation steps**:
1. Add `PORTFOLIO_WATCHLIST_CACHE_TTL_SECONDS: int = 300` to `config.py`.
2. Define `WatchlistCachePort` ABC in `application/ports/cache.py`: `get_user_ids(entity_id) → list[UUID]`, `invalidate_entity(entity_id) → None`, `set_user_ids(entity_id, user_ids, ttl) → None`.
3. Implement `ValkeyWatchlistCache(WatchlistCachePort)` in `infrastructure/cache/watchlist_cache.py` using `libs/messaging` `ValkeyClient`. Key: `pf:v1:watchlist:entity:{entity_id}`. Use Redis Set (`SADD`, `SMEMBERS`, `DEL`).
4. Modify `app.py` lifespan to create `ValkeyClient(config=ValkeyConfig(url=settings.valkey_url))` and store it in `app.state.valkey_client`.
5. Modify `api/dependencies.py` to expose `WatchlistCacheDep`.
6. Inject `WatchlistCacheDep` into the watchlist member add/remove endpoints.

**Tests required**:
- `tests/unit/test_watchlist_cache.py` — using `fakeredis.aioredis.FakeRedis` injected into `ValkeyClient._redis`
- `tests/integration/test_watchlist_reverse_index.py` — real Valkey via testcontainers, verify add → cache populated, remove → invalidated
**Effort**: Medium

---

### Task C-001: Implement Alert Preference Domain Entities

**ID**: C-001
**Title**: Add alert preference and entity suppression domain entities
**Objective**: Create the pure domain model for alert preferences
**Depends_on**: None
**Can_run_with**: W-001
**Target paths**:
- `src/portfolio/domain/entities/alert_preference.py`
- `src/portfolio/domain/enums.py` (modify)
- `src/portfolio/domain/errors.py` (modify)

**Implementation steps**:
1. Add `AlertType` StrEnum: `SIGNAL`, `CONTRADICTION`, `CONFIDENCE_DROP`, `NEW_EVENT`.
2. Create `AlertPreference` dataclass: `id`, `tenant_id`, `user_id`, `alert_type: AlertType`, `enabled: bool = True`, `updated_at`.
3. Create `EntitySuppression` dataclass: `id`, `tenant_id`, `user_id`, `entity_id: UUID`, `suppressed_at`.
4. Add `AlertPreferenceNotFoundError` to `errors.py`.

**Tests required**: `tests/unit/test_domain_alert_preference.py`
**Effort**: Small

---

### Task C-002: Add Alert Preference Repository Ports and DB Layer

**ID**: C-002
**Title**: Alert preference and entity suppression DB migration + SQLAlchemy
**Objective**: Persist alert preferences
**Depends_on**: C-001
**Can_run_with**: W-003
**Target paths**:
- `src/portfolio/application/ports/repositories.py` (modify)
- `src/portfolio/application/ports/unit_of_work.py` (modify)
- `src/portfolio/infrastructure/db/models/alert_preference.py`
- `src/portfolio/infrastructure/db/models/entity_suppression.py`
- `src/portfolio/infrastructure/db/repositories/alert_preference.py`
- `src/portfolio/infrastructure/db/unit_of_work.py` (modify)
- `alembic/versions/0004_add_alert_preferences.py`

**Implementation steps**:
1. Define `AlertPreferenceRepository` ABC: `get_by_user(user_id, tenant_id) → list[AlertPreference]`, `upsert(pref)`.
2. Define `EntitySuppressionRepository` ABC: `list_by_user(user_id, tenant_id) → list[EntitySuppression]`, `get(user_id, entity_id) → EntitySuppression | None`, `save(suppression)`, `delete(user_id, entity_id)`.
3. Create ORM models per Section 4-C DB design.
4. Create Alembic migration 0004 (after 0003 which handles `entity_id` column).
5. Implement `SqlAlchemyAlertPreferenceRepository` using `pg_insert(...).on_conflict_do_update(...)` for upsert.

**Tests required**: `tests/unit/test_use_cases_alert_preferences.py` (after C-003 adds use cases)
**Effort**: Small

---

### Task C-003: Implement Alert Preference Use Cases and API

**ID**: C-003
**Title**: Add use cases and endpoints for alert preferences
**Objective**: Users can read and write alert preferences
**Depends_on**: C-002
**Target paths**:
- `src/portfolio/application/use_cases/alert_preferences.py`
- `src/portfolio/api/schemas.py` (modify)
- `src/portfolio/api/routes/alert_preferences.py`
- `src/portfolio/api/routes/__init__.py` (modify)

**Implementation steps**:
1. `GetAlertPreferencesUseCase` — returns all preferences and suppressions for a user; defaults to enabled if no row exists for a given `alert_type`.
2. `UpsertAlertPreferenceUseCase` — validates `alert_type` is a known `AlertType` value; upserts.
3. `SetEntitySuppressionUseCase` — saves a suppression.
4. `RemoveEntitySuppressionUseCase` — raises `AlertPreferenceNotFoundError` if absent.
5. Implement 4 API endpoints per Section 4-C API Contract.

**Tests required**: `tests/unit/test_use_cases_alert_preferences.py`, `tests/integration/test_alert_preferences_api.py`
**Docs updates**: `docs/services/portfolio.md` — add alert preference endpoint table
**Effort**: Medium

---

### Task B-001: Add `entity_id` to InstrumentRef

**ID**: B-001
**Title**: Link `InstrumentRef` to canonical Knowledge Graph `entity_id`
**Objective**: Enable KG-to-portfolio joins for intelligence features
**Depends_on**: None
**Can_run_with**: W-001, C-001
**Target paths**:
- `src/portfolio/domain/entities/instrument.py`
- `src/portfolio/infrastructure/db/models/instrument.py`
- `src/portfolio/consumers/instrument_consumer.py`
- `src/portfolio/messaging/schemas/instrument_ref.created.avsc`
- `src/portfolio/messaging/mapper.py`
- `src/portfolio/api/schemas.py` (`InstrumentResponse` — add `entity_id` optional field)
- `alembic/versions/0003_add_entity_id_to_instruments.py`

**Implementation steps**:
1. Add `entity_id: UUID | None = None` to `InstrumentRef` dataclass.
2. Add nullable `entity_id UUID` column to `InstrumentModel`.
3. Create migration 0003 with `ALTER TABLE instruments ADD COLUMN entity_id UUID NULL` and index.
4. Update `instrument_consumer.py` to parse `entity_id` from event payload.
5. Add `"entity_id"` field with `["null", "string"]` type and `null` default to `instrument_ref.created.avsc`.
6. Update `instrument_ref_created_to_dict` mapper to include `entity_id`.
7. Update `InstrumentResponse` schema to include `entity_id: UUID | None = None`.

**Tests required**: `tests/contract/test_instrument_ref_created_contract.py` (update), `tests/unit/test_domain_entities.py` (update)
**Effort**: Small

---

### Task F-001: Add Pagination to Unbounded List Endpoints

**ID**: F-001
**Title**: Add `limit`/`offset` query parameters to list endpoints
**Objective**: Prevent OOM from unbounded list responses
**Depends_on**: None
**Can_run_with**: All other tasks
**Target paths**:
- `src/portfolio/api/schemas.py`
- `src/portfolio/api/routes/portfolio.py`
- `src/portfolio/api/routes/instrument.py`
- `src/portfolio/api/routes/transaction.py`
- `src/portfolio/application/ports/repositories.py`
- `src/portfolio/infrastructure/db/repositories/portfolio.py`
- `src/portfolio/infrastructure/db/repositories/instrument.py`
- `src/portfolio/infrastructure/db/repositories/transaction.py`

**Implementation steps**:
1. Add `PaginatedResponse[T]` generic Pydantic model with `items: list[T]`, `total: int`, `limit: int`, `offset: int`.
2. Update each list endpoint to accept `limit: int = Query(default=100, le=500)` and `offset: int = Query(default=0, ge=0)`.
3. Update repository ABCs to accept `limit`/`offset` params.
4. Update SQL queries to use `.limit(limit).offset(offset)`.

**Tests required**: Update integration tests to assert pagination works; test `limit=1` returns 1 item with `total > 1`
**Effort**: Small

---

## 6. Open Questions and Decision Points

### Q1: Reverse-Index Endpoint Access Control

**Ambiguity**: `GET /api/v1/watchlists/reverse/{entity_id}` returns which users are tracking
an entity. This is cross-user data — a regular authenticated user should NOT be able to call
this and learn which other users track the same entity.

**Options**:
- A. Restrict to service-internal calls via a `X-Service-Token` header validated against a
  shared secret (simple, no JWT infrastructure needed at this stage).
- B. The alert service (S10) calls the Portfolio service directly (bypassing Gateway) on an
  internal network, no auth needed between services.
- C. Expose a Kafka consumer in the alert service that subscribes to `portfolio.watchlist.updated.v1`
  and maintains its own local `entity_id → user_ids` index. This avoids the HTTP call entirely
  and aligns with event-driven principles.

**Recommended default**: Option C is the cleanest architectural choice. The alert service
consumes `portfolio.watchlist.updated.v1` events and maintains its own materialized reverse
index. The Portfolio service still publishes the events (W-005) and maintains the Valkey cache
for internal use (W-007), but does not expose the reverse-index HTTP endpoint to other services.
If Option C is chosen, skip the `GET /api/v1/watchlists/reverse/{entity_id}` endpoint.

---

### Q2: Alert Preference Query by Alerting Service

**Ambiguity**: How does the alert service (S10) retrieve a user's alert preferences before
sending a notification?

**Options**:
- A. S10 calls `GET /api/v1/alert-preferences` via the API Gateway, impersonating the user.
  This requires the gateway to support service-impersonation tokens.
- B. S10 calls a service-to-service endpoint on Portfolio directly (bypassing Gateway), similar
  to Q1 option B.
- C. S10 subscribes to a `portfolio.alert_preferences.updated.v1` Kafka topic and maintains
  its own local preference cache.
- D. S10 caches preferences in Valkey with a short TTL (fetched from Portfolio on first alert
  per user, then cached).

**Recommended default**: Option D — S10 fetches preferences from Portfolio's API on first
alert attempt per user (or per session), caches them in its own Valkey namespace with a 60s TTL.
The Portfolio service does not need to emit preference-change Kafka events in the initial
implementation. Add this as a future enhancement.

---

### Q3: Watchlist vs. Portfolio Overlap

**Ambiguity**: The MASTER_PLAN's component diagram does not explicitly document a
portfolio-watchlist overlap feature. It is unclear whether a user's watchlist should
automatically include their portfolio holdings, or whether these are strictly separate.

**Options**:
- A. Watchlists are entirely independent of portfolio holdings — a user explicitly adds entities
  to a watchlist regardless of what they hold.
- B. Portfolio holdings can be "promoted" to a watchlist with one click — convenience feature,
  no data model change required beyond the `entity_id` linkage.

**Recommended default**: Option A (simpler). Design for independence; add convenience UX
later.

---

### Q4: Schema Location Convention — Local vs. Global

**Ambiguity**: Portfolio service stores Avro schemas in `src/portfolio/messaging/schemas/`.
The global schema registry registration script reads from `infra/kafka/schemas/`. Both
must be kept in sync.

**Options**:
- A. Keep both copies; ensure CI validates they are identical (e.g., diff check in `scripts/gen-contracts.sh`).
- B. Store schemas only in `infra/kafka/schemas/` and have the portfolio service load them
  from a path relative to repo root (as the market-ingestion service does).
- C. Symlink `src/portfolio/messaging/schemas/` to `infra/kafka/schemas/`.

**Recommended default**: Option B — align with how `services/market-ingestion` resolves schemas.
This requires updating `messaging/serialization.py` to use a repo-root relative path. It
eliminates the sync problem. Note BP-011 (missing schemas in container image) applies — the
Dockerfile must COPY `infra/kafka/schemas` into the image.

---

### Q5: `entity_id` Source — Where Does Portfolio Get KG IDs?

**Ambiguity**: The `entity_id` on `InstrumentRef` would be populated from the
`market.instrument.created` event. But that event is produced by Market Data (S3), which
consumes from Market Ingestion (S2). Neither S3 nor S2 currently knows about Knowledge Graph
entity IDs (those are produced by S7/S6 during NLP entity linking).

**Options**:
- A. Market Data adds `entity_id` to `market.instrument.created` after S7 resolves it
  (requires S3 to consume from S7 or an entity linking event).
- B. Portfolio directly consumes an S7 or S6 entity-linking event (e.g., `nlp.article.enriched.v1`)
  to patch `entity_id` onto existing `InstrumentRef` records.
- C. Portfolio exposes a PATCH endpoint that S7 calls after entity linking is complete.
- D. Portfolio stores `symbol:exchange` as the linkage key, not `entity_id`, and the Intelligence
  Layer resolves the mapping at query time.

**Recommended default**: Option D for the current thesis phase. `entity_id` on `InstrumentRef`
should be nullable and left unset until the NLP pipeline is complete. This avoids a complex
cross-service data flow for a feature that won't be needed until Phase 3 of the roadmap.
Task B-001 should create the column but not mandate population.

---

## 7. Risk Register

| ID | Risk | Probability | Impact | Mitigation | Rollback |
|----|------|-------------|--------|------------|---------|
| R1 | Watchlist migration adds tables but `alembic check` shows drift (BP-008 pattern) | Medium | High | Run `alembic upgrade head && alembic check` after each migration; verify ORM model matches migration exactly | Downgrade migration; fix model alignment |
| R2 | `NULLS NOT DISTINCT` on `watchlist_members` unique constraint not used, allowing duplicate membership under NULL `entity_id` | Low | Medium | `entity_id` is NOT NULL in this schema so standard UniqueConstraint is safe; add `CHECK (entity_id IS NOT NULL)` constraint as defense | New migration to enforce NOT NULL |
| R3 | Valkey `ValkeyClient` not available at startup causes `AttributeError` in add_member endpoint | Medium | High | Initialize `ValkeyClient` in lifespan with explicit health check; if connection fails, app should fail readiness probe, not start serving traffic | Revert `app.py` lifespan change; service degrades to uncached reverse-index queries |
| R4 | Watchlist Avro schema incompatibility with existing `portfolio.events.v1` envelope structure | Low | High | Use a separate topic `portfolio.watchlist.updated.v1` with its own schema — no overlap with existing envelope | Remove watchlist topic from topic map; keep events in DB until schema is fixed |
| R5 | Reverse-index endpoint leaks cross-user data if access control not implemented | High | Critical | Do not expose the endpoint publicly; use Option C from Q1 (event-driven approach) instead of HTTP endpoint; or add `X-Service-Token` validation immediately | Remove endpoint from router before deployment |
| R6 | `claim_batch` full-table scan on `outbox_events` degrades dispatcher throughput as table grows | Medium | Medium | Add `ix_outbox_events_status_lease_expires` index in migration 0002 before any watchlist load | Add index in a subsequent migration (online, no lock for Postgres 12+) |
| R7 | Alert preference default behavior (all enabled) when no DB row exists could result in spam notifications if S10 assumes default-disabled | Low | High | Document the default clearly in the API response; S10 must explicitly handle the "no preference set" case; return explicit defaults in `GetAlertPreferencesUseCase` | S10 can fail-safe by not sending if preference is missing |
| R8 | Watchlist test suite lacks Valkey container fixture, leading to skipped integration tests | Medium | Medium | Add `valkey_container` session fixture to `tests/integration/conftest.py` using `testcontainers` (pattern from market-data service) | Fakeredis covers unit layer; integration Valkey tests can be marked `@pytest.mark.integration` and skipped locally |
| R9 | Schema location divergence (local vs. `infra/kafka/schemas/`) causes `FileNotFoundError` in container (BP-011 pattern) | High | High | Adopt Option B from Q4 — single location in `infra/kafka/schemas/`; update Dockerfile to `COPY infra/kafka/schemas /app/infra/kafka/schemas` | Keep local copies as fallback; add path resolution fallback |
| R10 | `price > 0` validator (Gap B3) breaks existing integration tests that create dividend transactions with price=0 | Low | Medium | Audit all integration test fixtures for zero-price transactions; update before relaxing validator | Revert validator change; separate DIVIDEND transaction type validation |

---

*End of gap analysis. This document is authoritative for the Portfolio service watchlist
implementation sprint. All section references are traceable to specific file paths and
symbols in the codebase as of 2026-03-19.*
