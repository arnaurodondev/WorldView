# S10 · Alert Service

> **Owner**: Intelligence domain · **Database**: `alert_db` · **Port**: 8010
> **Status**: Not started (❌ Pending S1 deployment gate)

---

## Mission & Boundaries

**Owns**: Consuming intelligence and watchlist events, resolving which users watch
affected entities via S1 REST API (Valkey-cached), deduplicating alerts per
user+entity+alert_type within a configurable time window, pushing structured
notifications to connected clients over WebSocket, storing pending alerts for
offline clients.

**Never does**: Generate signals or extract entities (S6 NLP Pipeline), maintain
the knowledge graph (S7 Knowledge Graph), manage portfolios or watchlists (S1 Portfolio).

**Deployment gate**: S10 cannot deploy until S1 provides all of the following:
1. `GET /internal/v1/watchlists/by-entity/{entity_id}` — list watchlist IDs containing entity
2. `POST /internal/v1/watchlists/by-entities` — batch entity → watchlist lookup
3. Publication to `portfolio.watchlist.updated.v1` Kafka topic
4. Internal token auth (`Authorization: Bearer <INTERNAL_SERVICE_TOKEN>`) on endpoints 1 and 2

---

## API Surface

| Method | Path | Description | Cache |
|--------|------|-------------|-------|
| GET | `/healthz` | Liveness | — |
| GET | `/readyz` | Readiness (DB + Valkey + S1 reachable) | — |
| GET | `/metrics` | Prometheus | — |
| WS | `/api/v1/alerts/stream` | WebSocket stream for connected client (authenticated) | — |
| GET | `/api/v1/alerts/pending` | Fetch undelivered alerts for current user | — |
| DELETE | `/api/v1/alerts/{id}/ack` | Acknowledge / dismiss alert | — |

---

## Kafka Topics

### Consumed

| Topic | Consumer Group | Purpose |
|-------|---------------|---------|
| `nlp.signal.detected.v1` | `alert-service-group` | High-confidence NLP signals from S6 |
| `graph.state.changed.v1` | `alert-service-group` | KG graph state changes from S7 |
| `intelligence.contradiction.v1` | `alert-service-group` | Contradiction events from S7 |
| `portfolio.watchlist.updated.v1` | `alert-service-watchlist-group` | Watchlist membership changes from S1 |

### Produced

| Topic | Event Type | Key | Via |
|-------|-----------|-----|-----|
| `alert.delivered.v1` | `AlertDeliveredV1` | `alert_id` | Outbox in `alert_db` |

---

## Database Schema

```sql
-- alert_db

CREATE TABLE alerts (
    id              UUID PRIMARY KEY,
    user_id         UUID NOT NULL,
    entity_id       UUID NOT NULL,
    alert_type      VARCHAR(50) NOT NULL,
    source_event_id UUID NOT NULL,
    payload         JSONB NOT NULL,
    delivered_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_alerts_user ON alerts(user_id, created_at DESC);
CREATE INDEX idx_alerts_entity ON alerts(entity_id);

CREATE TABLE pending_alerts (
    id              UUID PRIMARY KEY,
    user_id         UUID NOT NULL,
    alert_id        UUID NOT NULL REFERENCES alerts(id),
    expires_at      TIMESTAMPTZ NOT NULL,  -- now() + PENDING_ALERT_TTL_DAYS
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_pending_user ON pending_alerts(user_id, expires_at);

CREATE TABLE alert_dedup (
    dedup_key       TEXT PRIMARY KEY,  -- hash(user_id + entity_id + alert_type + window)
    alert_id        UUID NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL
);

CREATE TABLE outbox_events (
    id              UUID PRIMARY KEY,
    event_type      VARCHAR(100) NOT NULL,
    topic           VARCHAR(100) NOT NULL,
    key             TEXT NOT NULL,
    payload         JSONB NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    published_at    TIMESTAMPTZ
);
CREATE INDEX idx_outbox_unpublished ON outbox_events(published_at) WHERE published_at IS NULL;

CREATE TABLE idempotency (
    event_id        UUID PRIMARY KEY,
    processed_at    TIMESTAMPTZ DEFAULT now()
);
```

---

## Alert Processing Flow

```
Kafka event consumed
        ↓
Extract entity_id from event payload
        ↓
Valkey cache lookup: entity_id → [watchlist_id, ...]
   (miss) → S1 REST GET /internal/v1/watchlists/by-entity/{entity_id}
   (populate cache, TTL = WATCHLIST_CACHE_TTL_SECONDS)
        ↓
For each watchlist_id → resolve user_ids
        ↓
Dedup check: hash(user_id + entity_id + alert_type) within ALERT_DEDUP_WINDOW_SECONDS
   (already alerted) → skip
        ↓
INSERT alerts + pending_alerts (same transaction as outbox_events)
        ↓
WebSocket push to connected clients
        ↓
alert.delivered.v1 emitted via outbox dispatcher
```

---

## Key ENV Vars

| Variable | Default | Description |
|----------|---------|-------------|
| `S1_PORTFOLIO_BASE_URL` | — | S1 internal URL (e.g., `http://svc-portfolio:8001`) |
| `INTERNAL_SERVICE_TOKEN` | — | Shared secret for S1 internal endpoints |
| `WATCHLIST_CACHE_TTL_SECONDS` | `300` | Valkey TTL for entity → watchlist reverse cache |
| `ALERT_DEDUP_WINDOW_SECONDS` | `300` | Dedup window per user+entity+type (5 min) |
| `PENDING_ALERT_TTL_DAYS` | `7` | Undelivered alert retention |
| `OUTBOX_POLL_INTERVAL_SECONDS` | `2` | Dispatcher cadence |
| `OUTBOX_BATCH_SIZE` | `100` | Rows per dispatch cycle |

---

## Internal Modules

```
services/alert-service/src/alert_service/
├── app.py              # FastAPI app factory (includes WebSocket endpoint)
├── config.py           # Settings (DB, Valkey, Kafka, S1 URL, tokens)
├── api/                # WebSocket stream, pending alerts, ack routes
├── domain/             # Alert, Dedup, PendingAlert models
├── application/        # Alert fan-out, dedup, delivery use-cases
└── infrastructure/     # DB, Kafka consumer, outbox dispatcher, Valkey, S1 client
```

---

## Observability

- **Metrics**: `alerts_delivered_total`, `alerts_deduplicated_total`, `s1_watchlist_lookups_total`, `s1_watchlist_cache_hit_ratio`, `websocket_connections_active`
- **Log fields**: `service=alert-service`, `alert_id`, `entity_id`, `user_id`, `alert_type`

---

## Testing Plan

| Type | What | Command |
|------|------|---------|
| Unit | Dedup logic, alert fan-out, watchlist cache hit/miss | `make test` |
| Integration | Consumer + alert_db + Valkey + mock S1 | `make test-integration` |

---

## Local Run

```bash
cd services/alert-service
cp configs/dev.local.env.example .env
make run       # port 8010
make test
make lint
```
