# S10 — Alert Service

> **Status**: In-progress (Wave E-1 complete)
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

---

## Implementation Status

- [x] Wave E-1: Service setup, domain, DB, S1 client, tests (43 tests)
- [ ] Wave E-2: Consumers, alert fan-out, WebSocket, outbox
- [ ] Wave E-3: REST API, health, integration tests, full pipeline validation
