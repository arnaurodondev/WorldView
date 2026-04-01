# S10 — Alert Service

> **Status**: ✅ Feature-complete (Wave E-3 complete — 2026-03-29)
> **Port**: 8010
> **Database**: alert_db (owned, Alembic enabled)
> **Dependencies**: S1 Portfolio (internal endpoints), Kafka, Valkey

---

## Overview

The Alert service fans out intelligence signals to users who are watching relevant entities. It consumes events from S6 (NLP Pipeline), S7 (Knowledge Graph), and S1 (Portfolio watchlist updates), resolves affected watchers via S1 internal endpoints, deduplicates alerts per entity+type+time window, and delivers them via WebSocket and pending-alert REST API.

---

## Domain Models

### AlertType (enum)
| Value | Source Topic |
|-------|-------------|
| `SIGNAL` | `nlp.signal.detected.v1` |
| `GRAPH_CHANGE` | `graph.state.changed.v1` |
| `CONTRADICTION` | `intelligence.contradiction.v1` |

### Alert
Core entity stored in `alerts` table. Key fields:
- `alert_id` (UUIDv7), `entity_id`, `alert_type`, `source_event_id`, `source_topic`
- `payload` (JSONB), `dedup_key` (sha256, UNIQUE), `created_at` (UTC)

### Dedup Key (AD-9)
```
dedup_key = sha256(f"{entity_id}:{alert_type}:{created_at_epoch // window_seconds}")
```
`source_event_id` is intentionally excluded — enables true dedup per entity+type+window.

### PendingAlert
Per-user pending delivery row: `pending_id`, `user_id`, `alert_id`, `delivered_at`.

### AlertDelivery
Delivery tracking: `delivery_id`, `alert_id`, `user_id`, `channel`, `status`.

### AlertSubscription
User→entity subscription: `subscription_id`, `user_id`, `entity_id`, `watchlist_id`, `alert_types`.

---

## Database Schema (alert_db)

6 tables — owned by S10, Alembic IS enabled:
- `alert_subscriptions` — user watchlist subscriptions
- `alerts` — materialized alerts with dedup_key UNIQUE
- `alert_deliveries` — per-user delivery tracking
- `pending_alerts` — unacknowledged alerts queue
- `outbox_events` — transactional outbox for Kafka
- `dead_letter_queue` — failed dispatch entries

---

## S1 Portfolio Dependency (Deployment Gate)

S10 depends on 4 S1 internal endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/internal/v1/watchlists/by-entity/{entity_id}` | GET | Resolve watchers for a single entity |
| `/internal/v1/watchlists/by-entities` | POST | Batch resolve watchers (max 100 entity_ids) |
| `/internal/v1/watchlists/{watchlist_id}/entities` | GET | List entities in a watchlist |
| `/internal/v1/health` | GET | Health check (no auth) |

**Best-effort contract**: If S1 is unavailable (503, connection refused), S10 returns empty results and never raises. This is validated by 3 contract tests.

### Watchlist Cache
- **Pattern**: Cache-aside with Valkey
- **Key**: `s10:v1:watchlist:by_entity:{entity_id}`
- **TTL**: 300 seconds (configurable)
- **Invalidation**: On `portfolio.watchlist.updated.v1` → `item_deleted` events

---

## Configuration

Environment prefix: `ALERT_`

| Variable | Default | Description |
|----------|---------|-------------|
| `ALERT_DATABASE_URL` | `postgresql+asyncpg://...` | alert_db connection |
| `ALERT_KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka brokers |
| `ALERT_KAFKA_SCHEMA_REGISTRY_URL` | `http://localhost:8081` | Schema registry |
| `ALERT_KAFKA_CONSUMER_GROUP` | `alert-service-group` | Main consumer group |
| `ALERT_KAFKA_WATCHLIST_CONSUMER_GROUP` | `alert-service-watchlist-group` | Watchlist consumer group |
| `ALERT_S1_PORTFOLIO_BASE_URL` | `http://localhost:8001` | S1 base URL |
| `INTERNAL_SERVICE_TOKEN` | `` | Shared inter-service token (no prefix) |
| `ALERT_ALERT_DEDUP_WINDOW_SECONDS` | `300` | Dedup window in seconds |
| `ALERT_WATCHLIST_CACHE_TTL_SECONDS` | `300` | Valkey cache TTL |
| `ALERT_SERVICE_NAME` | `alert` | For observability |
| `ALERT_LOG_LEVEL` | `INFO` | Log level |
| `ALERT_LOG_JSON` | `true` | JSON-structured logs |
| `ALERT_OTLP_ENDPOINT` | `` | OTLP exporter endpoint |
| `ALERT_ADMIN_TOKEN` | `` | DLQ admin endpoint bearer token |
| `ALERT_HOST` | `0.0.0.0` | Server bind host |
| `ALERT_PORT` | `8010` | Server bind port |

---

## Consumer Topology (Wave E-2)

### IntelligenceConsumer
- **Group**: `alert-service-group`
- **Topics**: `nlp.signal.detected.v1`, `graph.state.changed.v1`, `intelligence.contradiction.v1`
- **Routing**: `event_type` field (or `X-Source-Topic` header) → `AlertFanoutUseCase.execute()`
- **At-least-once** with manual offset commit (`enable_auto_commit=False`)

### WatchlistConsumer
- **Group**: `alert-service-watchlist-group`
- **Topic**: `portfolio.watchlist.updated.v1`
- `item_added` → no-op (cache populated on next lookup)
- `item_deleted` → DEL `s10:v1:watchlist:by_entity:{entity_id}` for all affected entities

---

## Alert Fan-out Logic (Wave E-2)

### Backfill Suppression (PRD AD-10)
| Topic | Rule |
|-------|------|
| `nlp.signal.detected.v1` | `is_backfill=true` → suppress always |
| `graph.state.changed.v1` | `is_backfill=true` → suppress always |
| `intelligence.contradiction.v1` | `is_backfill=true AND (now - occurred_at) > 30 days` → suppress (recent-impact contradictions are still useful) |

### Dedup Window (PRD AD-9)
```
dedup_key = sha256(f"{entity_id}:{alert_type}:{epoch // dedup_window_seconds}")
```
Default window: 300 s. Same entity+type within one window → single alert.

### Fan-out Transaction
1. Backfill check → suppress if applicable
2. Resolve watchers via `WatchlistCache` → S1 fallback
3. Dedup check via `DedupRepository.exists(dedup_key)`
4. **Single transaction**: INSERT alert + INSERT pending_alert (per watcher) + INSERT outbox_event (per watcher)
5. **Post-commit**: WebSocket push via `ConnectionManager` (never inside transaction)

---

## WebSocket Delivery (Wave E-2)

`ConnectionManager` stores active connections in memory (keyed by `user_id`).

**⚠ Single-replica constraint**: connections are in-process memory. Scaling to ≥2 replicas requires an out-of-process fan-out layer (e.g. Redis Pub/Sub).

| Method | Behaviour |
|--------|-----------|
| `connect(user_id, ws)` | Accept + register; replaces existing connection |
| `disconnect(user_id)` | Remove; no-op if not connected |
| `send_to_user(user_id, data)` | JSON push; cleans up stale connections on failure |
| `broadcast(data)` | Push to all connected users |

---

## Outbox Dispatcher (Wave E-2)

`AlertOutboxDispatcher` polls `outbox_events` table and produces pre-serialized Avro bytes to Kafka.

- No lease semantics (single-replica deployment)
- At-least-once: if crash after `produce()` but before `mark_dispatched()`, event is re-queued
- Produces to `alert.delivered.v1` (topic stored per-row in outbox)

---

## REST API (Wave E-3)

### GET /api/v1/alerts/pending
Returns paginated unacknowledged alerts for a user.

**Query params**: `user_id` (UUID, required), `limit` (1–200, default 50), `offset` (default 0)
**Response**: `{ alerts: PendingAlertResponse[], total, limit, offset }`

### DELETE /api/v1/alerts/{alert_id}/ack
Marks an alert as acknowledged for a user.

**Query params**: `user_id` (UUID, required)
**Returns**: 200 `{"status": "acknowledged"}` on success; 404 when not found or wrong user (avoids user enumeration, per AD-11)

### WebSocket /api/v1/alerts/stream
Real-time alert stream pushed to connected users.

**Query params**: `user_id` (UUID, required)
**Protocol**: S10 pushes JSON `{ alert_id, entity_id, alert_type, created_at }` on each new alert

---

## Health & Observability (Wave E-3)

| Endpoint | Description |
|----------|-------------|
| `GET /healthz` | Liveness probe — always 200 |
| `GET /readyz` | Readiness — checks alert_db, Kafka, Valkey, S1 (503 on any failure) |
| `GET /metrics` | Prometheus metrics (s10_ prefix) |

**Metrics**: `s10_alerts_fanned_out_total[type]`, `s10_alerts_deduplicated_total`, `s10_websocket_pushes_total`, `s10_alerts_pending_total`

---

## DLQ Admin (Wave E-3)

Admin endpoints protected by `X-Admin-Token` header (`ALERT_ADMIN_TOKEN` env var).

| Endpoint | Description |
|----------|-------------|
| `GET /admin/dlq` | List failed DLQ entries (paginated) |
| `GET /admin/dlq/{dlq_id}` | Get a single DLQ entry |
| `POST /admin/dlq/{dlq_id}/resolve` | Mark entry as resolved with a note |

---

## Deployment Constraints

### Single-Replica Requirement (WebSocket)

The `ConnectionManager` stores active WebSocket connections in process memory (`_connections: dict[UUID, WebSocket]`). Running ≥2 replicas of S10 would mean a push arriving at replica A cannot reach a user connected to replica B.

**Current deployment**: single-replica only.  Scaling to ≥2 replicas requires an out-of-process fan-out layer (e.g. Redis Pub/Sub) to broadcast push notifications across all replicas.

This constraint is documented in the `.. warning::` docstring of `services/alert/src/alert/infrastructure/websocket/manager.py`.

### S9 Auth-Injection (user_id Parameter)

The REST and WebSocket endpoints accept `user_id` as a required query parameter (`Query(...)`). **S10 does not validate the user_id against a session token** — it trusts the S9 API Gateway to inject the correct `user_id` from the authenticated JWT before forwarding the request to S10.

**Security invariant**: S10 must never be exposed directly to end-user traffic. All external requests must flow through S9, which enforces authentication and injects the `user_id` claim. S10 endpoints reject connections without `user_id` (returns 422/403), but do not verify it corresponds to a valid session.

This is noted in the docstrings of the REST and WebSocket route handlers in `services/alert/src/alert/api/routes.py`.

---

## Implementation Status

- [x] Wave E-1: Service setup, domain, DB, S1 client, tests (43 tests)
- [x] Wave E-2: Consumers, alert fan-out, WebSocket, outbox (97 tests, ruff + mypy clean)
- [x] Wave E-3: REST API, health, integration tests, full pipeline validation (114 unit tests, ruff + mypy clean — 2026-03-29)
