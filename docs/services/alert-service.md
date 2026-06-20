# Alert Service (S10)

> **Owner**: Alert domain · **Database**: `alert_db` · **Port**: 8010
> **Status**: Feature-complete (Wave E-3 + PLAN-0013 Wave C-2 + PLAN-0082 Wave B)

---

## Mission

S10 fans out intelligence signals to users watching relevant entities. It:

1. Consumes Kafka events from S6 (NLP) and S7 (KG)
2. Resolves affected watchers by querying S1's internal watchlist endpoints
3. Deduplicates alerts per `(entity_id, alert_type, time-window)`
4. Delivers alerts in real-time via WebSocket (Valkey pub/sub bridge)
5. Stores undelivered alerts for offline clients (`GET /api/v1/alerts/pending`)
6. Sends daily email digests (APScheduler, via Resend/SendGrid/SMTP)

**Never does**: Any direct database access to other services, JWT issuance,
business logic about what constitutes a signal.

---

## Architecture

### Auth Model (PRD-0025)

S10 uses `InternalJWTMiddleware` (RS256, JWKS from S9). All API endpoints except
`/healthz`, `/readyz`, `/metrics` require a valid `X-Internal-JWT`.

**WebSocket auth**: Because `BaseHTTPMiddleware` skips dispatch for WebSocket
connections, the WebSocket route validates the JWT inline by extracting the token
from the `token` query parameter and calling `jwt.decode()` directly with S9's
public key.

**Security invariant**: S10 must **never** be exposed directly to end-user traffic.
All external requests must flow through S9, which enforces authentication and
injects the correct `user_id` from the JWT.

### Process Topology

| Process | Entry Point | Container |
|---------|------------|-----------|
| API server | `uvicorn alert.app:create_app --factory` | `alert` |
| Outbox dispatcher | `python -m alert.infrastructure.messaging.outbox.dispatcher_main` | `alert-dispatcher` |
| Intelligence consumer | `python -m alert.infrastructure.messaging.consumers.intelligence_consumer_main` | `alert-intelligence-consumer` |
| Watchlist consumer | `python -m alert.infrastructure.messaging.consumers.watchlist_consumer_main` | `alert-watchlist-consumer` |
| Email scheduler | `python -m alert.infrastructure.email.scheduler_main` | `alert-email-scheduler` |
| Alert-rule poller | `python -m alert.infrastructure.rules.poller_main` | `alert-rule-poller` |

The **alert-rule poller** (PLAN-0113) is the 5th process (R22). It runs an
APScheduler interval loop (base tick `ALERT_RULE_POLL_TICK_SECONDS`, default 60s)
that loads enabled poll-type rules (`PRICE_CROSS`, `FUNDAMENTAL_CROSS`,
`NEWS_COUNT`, `NEWS_MOMENTUM`), throttles each by its per-type cadence
(`AlertRule.is_due`), resolves an evaluator from `EVALUATOR_REGISTRY`
(`register_default_evaluators()` at boot), runs `evaluate → should_fire`, and on
an edge fires via `FireRuleAlertUseCase`. KG_CONNECTION is event-driven
(intelligence consumer), not polled. Observability per BP-705:
`s10_rule_poller_last_success_timestamp_seconds` (liveness gauge),
`s10_rule_poller_runs_total{outcome}`, `s10_rule_poller_due_rules`,
`s10_rule_evaluations_total{rule_type,outcome}`, `s10_rule_fired_total{rule_type}`,
and a per-cycle `asyncio.wait_for` watchdog (`ALERT_RULE_POLLER_WATCHDOG_SECONDS`).
Set `ALERT_RULE_POLLER_ENABLED=false` to disable evaluation instantly (rules
stay stored but dormant). Metrics on `:9101`.

#### Rule evaluators (PLAN-0113 Wave 2)

Each poll rule type maps to one `RuleEvaluator` in `application/rules/`. Evaluators
depend only on the ABC client ports in `application/ports/signal_clients.py`
(`IS3PriceClient`, `IS6NewsClient`) — never on the concrete HTTP clients (R25). All
reads are best-effort (a flaky upstream returns None → skip, no state change).

| Rule type | Evaluator | Cadence | Source (REST, R9) | Fires when |
|---|---|---|---|---|
| `PRICE_CROSS` | `PriceCrossEvaluator` | 60s | S3 `POST /internal/v1/price/batch` | last price crosses `value` (edge vs `last_state.was_above`) |
| `FUNDAMENTAL_CROSS` | `FundamentalCrossEvaluator` | 21600s (6h) | S3 `GET /api/v1/fundamentals/timeseries` (latest `value_numeric`) | metric crosses `value` (edge); cooldown re-arm 24h |
| `NEWS_COUNT` | `NewsCountEvaluator` | 3600s | S6 `GET /internal/v1/instruments/{id}/news-rollup-7d` (7d) or `GET /api/v1/news/trending-entities` (24/72/168h) | count first ≥ `threshold`; re-arms below |
| `NEWS_MOMENTUM` | `NewsMomentumEvaluator` | 3600s | S6 `GET /api/v1/news/trending-entities` (`delta_pct`, `count`) | `delta_pct ≥ threshold AND count ≥ min_count` (edge) |
| `KG_CONNECTION` | (Wave 3) | event | S7 `/paths/between` confirm | edge first appears (latch) |

`FireRuleAlertUseCase` (`application/use_cases/fire_rule_alert.py`) is the shared
firing path: one transaction writes `alerts` (`alert_type='user_rule'`,
`severity=rule.severity`, `payload={rule_type, rule_id, observed,
condition_snapshot}`, `dedup_key=sha256(rule_id:transition_signature)`) +
a `pending_alerts` row **for `rule.user_id` only** (owner-targeted, never a
watchlist fan-out) + an `outbox_events` row (R8). It advances
`rule.last_state.last_fired_at` only on commit; a rolled-back/duplicate fire never
advances the cooldown clock. Post-commit it pushes over the existing Valkey
WebSocket channel.

### WebSocket Cross-Process Architecture (Valkey Pub/Sub)

The intelligence consumer and the API process are separate OS processes. Real-time
delivery uses Valkey as a pub/sub bridge:

```
intelligence_consumer_main (process)
  └─ AlertFanoutUseCase
       └─ ValkeyNotificationPublisher.send_to_user(user_id, payload)
            └─ PUBLISH alert:{user_id} <JSON>
                                              │ Valkey
                                              ▼
                    API process (FastAPI / alerts_stream WS route)
                      └─ ValkeyClient.subscribe("alert:{user_id}")
                           └─ websocket.send_text(msg["data"])
```

**Delivery is best-effort**: if no WebSocket client is connected when a message is
published, the message is dropped. Clients catch up via `GET /api/v1/alerts/pending`.

Multi-replica capable: each API replica independently subscribes to the Valkey
channel for the user it is serving.

---

## API Endpoints

### Alert Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/alerts` | X-Internal-JWT | Create a user-initiated alert rule |
| GET | `/api/v1/alerts/pending` | X-Internal-JWT | List unacknowledged alerts (paginated) |
| DELETE | `/api/v1/alerts/{alert_id}/ack` | X-Internal-JWT | Mark per-user delivery row as acknowledged |
| PATCH | `/api/v1/alerts/{alert_id}/acknowledge` | X-Internal-JWT | Tenant-level alert ack (idempotent) |
| PATCH | `/api/v1/alerts/{alert_id}/snooze` | X-Internal-JWT | Set `snooze_until` (max 30 days) |
| GET | `/api/v1/alerts/history` | X-Internal-JWT | Paginated tenant alert history |

### Alert-Rule Endpoints (PLAN-0113)

Standing user rules. The `condition` is a discriminated union validated at the
boundary by `rule_type` (§6.5.3). `tenant_id`/`user_id` come from the JWT, never
the body. Owner-scoped: a cross-owner read/update/delete is a 404. Proxied by S9
at `/v1/alert-rules` (auth-gated, `Cache-Control: no-store`).

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/alert-rules` | X-Internal-JWT | Create a standing rule (201; 400 bad condition / unknown rule_type / bad severity; 422 node_a==node_b; 429 per-user cap) |
| GET | `/api/v1/alert-rules` | X-Internal-JWT | List the caller's rules (`?enabled=`, `?rule_type=`, `?limit=&offset=`) → `{items, total}` |
| GET | `/api/v1/alert-rules/{rule_id}` | X-Internal-JWT | Get one owned rule (404 if missing/cross-owner) |
| PATCH | `/api/v1/alert-rules/{rule_id}` | X-Internal-JWT | Partial update; changing `condition` re-arms (`last_state=null`); `rule_type` immutable |
| DELETE | `/api/v1/alert-rules/{rule_id}` | X-Internal-JWT | Delete an owned rule (204; 404 if missing/cross-owner) |

**Rule types** (`rule_type`, VARCHAR+CHECK per BP-007): `PRICE_CROSS`,
`NEWS_COUNT`, `NEWS_MOMENTUM`, `KG_CONNECTION`, `FUNDAMENTAL_CROSS`. The
read path (List/Get) uses the read replica (`ReadDbSessionDep`, R27); writes use
`DbSessionDep`. Reads/writes go only through use cases in
`application/use_cases/manage_rules.py` (R25), behind the `IAlertRuleRepository`
ABC port.

#### `POST /api/v1/alerts`

Creates a user-initiated alert rule (alert_type = `USER_RULE`). Writes `Alert` + `OutboxEvent` in a single
transaction (R8 outbox pattern). Also used by the S8 rag-chat `create_alert` tool after user confirmation.

**Request body**:
```json
{
  "entity_id": "UUID",
  "condition": "price_below | price_above | volume_spike | percent_change",
  "threshold": {"value": 200.0},
  "severity": "low | medium | high | critical"
}
```

Status codes: 201 success, 409 duplicate rule within dedup window.

The four alert types in the system:
- `SIGNAL` — financial signal detected by S6 NLP pipeline (from `nlp.signal.detected.v1`)
- `GRAPH_CHANGE` — knowledge graph update from S7 (from `graph.state.changed.v1`)
- `CONTRADICTION` — cross-source contradiction from S7 (from `intelligence.contradiction.v1`)
- `USER_RULE` — user-initiated alert created via this endpoint or the LLM `create_alert` tool

#### `GET /api/v1/alerts/pending`

Query params: `limit` (1-200, default 50), `offset` (default 0),
`min_severity` (`low|medium|high|critical`).

Response:
```json
{
  "alerts": [{
    "pending_id": "UUID",
    "alert_id": "UUID",
    "entity_id": "UUID",
    "alert_type": "SIGNAL | GRAPH_CHANGE | CONTRADICTION",
    "severity": "low | medium | high | critical",
    "title": "AAPL — Bullish guidance",
    "ticker": "AAPL",
    "entity_name": "Apple Inc.",
    "signal_label": "Bullish guidance",
    "payload": {},
    "created_at": "ISO-8601"
  }],
  "total": 5,
  "limit": 50,
  "offset": 0
}
```

#### `GET /api/v1/alerts/history`

Query params: `severity`, `entity_id`, `from` (datetime), `to` (datetime),
`status` (`active|acknowledged|snoozed|all`, default `all`), `limit` (1-200),
`offset`.

**Status semantics**:
- `active` — `acknowledged_at IS NULL AND (snooze_until IS NULL OR snooze_until < NOW())`
- `acknowledged` — `acknowledged_at IS NOT NULL`
- `snoozed` — `snooze_until >= NOW() AND acknowledged_at IS NULL`

Response includes `total` (universe count, not page size) and `has_more`.

**Wire contract**:
- `severity` query param MUST be lowercase (`high`, not `HIGH`)
- Snooze body field is `until` (NOT `snooze_until`)

#### `PATCH /api/v1/alerts/{alert_id}/snooze`

**Request body**: `{"until": "<ISO-8601 timezone-aware datetime>"}`

Validation: `until > now`, `until <= now + 30 days`. 422 for past/invalid datetimes.

### WebSocket Endpoint

#### `WS /api/v1/alerts/stream`

Real-time alert stream for a connected user.

**Query params**: `token` (required) — the short-lived WebSocket JWT issued by S9's
`GET /v1/auth/ws-token` (30-second TTL).

**Connection flow**:
1. Client calls `GET /v1/auth/ws-token` at S9 → receives 30-second JWT
2. Client connects to `ws://alert-service:8010/api/v1/alerts/stream?token=<jwt>`
3. S10 validates the JWT inline (not via middleware), sets `user_id` from claims
4. S10 subscribes to Valkey channel `alert:{user_id}`
5. On new alert: sends `{"alert_id": "...", "entity_id": "...", "alert_type": "...", "severity": "...", "created_at": "..."}`
6. Keepalive: if no message in 30 s, sends `{"type": "ping"}`

**Reconnection**: clients should reconnect on disconnect. A fresh `ws-token` is
needed for each new connection (30 s TTL).

### Email Preference Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/v1/email/preferences` | X-Internal-JWT | Get user's email digest preferences |
| PUT | `/api/v1/email/preferences` | X-Internal-JWT | Update email digest preferences |

**EmailPreference fields**: `enabled` (bool), `send_day_of_week` (0-6, Mon-Sun),
`send_hour_utc` (0-23), `timezone` (IANA).

### Health & Observability

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/healthz` | None | Liveness probe (always 200) |
| GET | `/readyz` | None | Readiness (checks alert_db, Kafka, Valkey, S1) |
| GET | `/metrics` | None | Prometheus metrics (`s10_` prefix) |

### DLQ Admin Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/admin/dlq` | `X-Admin-Token` | List failed DLQ entries (paginated) |
| GET | `/admin/dlq/{dlq_id}` | `X-Admin-Token` | Get single DLQ entry |
| POST | `/admin/dlq/{dlq_id}/resolve` | `X-Admin-Token` | Mark entry resolved with note |

---

## Kafka Topics

### Produced

| Topic | Description |
|-------|-------------|
| `alert.delivered.v1` | Alert successfully delivered (via outbox dispatcher) |
| `alert.email.sent.v1` | Email digest sent (schema in `infra/kafka/schemas/alert.email.sent.v1.avsc`) |

### Consumed

| Topic | Consumer Group | Purpose |
|-------|---------------|---------|
| `nlp.signal.detected.v1` | `alert-service-group` | Financial signals from S6 |
| `graph.state.changed.v1` | `alert-service-group` | Graph changes from S7 |
| `intelligence.contradiction.v1` | `alert-service-group` | Contradictions from S7 |
| `portfolio.watchlist.updated.v1` | `alert-service-watchlist-group` | Watchlist cache invalidation |

---

## Data Model (`alert_db`)

```sql
CREATE TABLE alerts (
    alert_id UUID PRIMARY KEY,      -- UUIDv7
    tenant_id UUID,
    entity_id UUID NOT NULL,
    alert_type VARCHAR(30) NOT NULL, -- SIGNAL | GRAPH_CHANGE | CONTRADICTION
    severity VARCHAR(10) NOT NULL DEFAULT 'low',  -- low/medium/high/critical
    source_event_id UUID,
    source_topic TEXT,
    payload JSONB NOT NULL,
    dedup_key TEXT UNIQUE NOT NULL,  -- sha256(entity_id:alert_type:window_bucket)
    title VARCHAR(255),              -- pre-composed UI subject
    ticker VARCHAR(20),              -- denormalized
    entity_name VARCHAR(500),        -- denormalized
    signal_label VARCHAR(200),       -- e.g. "Bullish guidance"
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by_user_id UUID,
    snooze_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- PLAN-0113 (migration 0010): standing user rules backing the rule engine.
CREATE TABLE alert_rules (
    rule_id UUID PRIMARY KEY,              -- UUIDv7
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,                 -- rule owner (delivery target)
    rule_type VARCHAR(50) NOT NULL,        -- VARCHAR+CHECK (BP-007), 5 RuleType values
    name VARCHAR(255) NOT NULL,
    entity_id UUID,                        -- instrument/entity key (non-KG types)
    node_a_entity_id UUID,                 -- KG_CONNECTION source
    node_b_entity_id UUID,                 -- KG_CONNECTION target
    condition JSONB NOT NULL,              -- discriminated union per rule_type (§6.5.3)
    severity VARCHAR(10) NOT NULL DEFAULT 'medium',
    enabled BOOLEAN NOT NULL DEFAULT true,
    cooldown_seconds INTEGER NOT NULL DEFAULT 0,
    notify_in_app BOOLEAN NOT NULL DEFAULT true,
    notify_email BOOLEAN NOT NULL DEFAULT false,
    last_state JSONB,                      -- edge-trigger memory (was_above/last_count/connected/last_fired_at/...)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- keying CHECK: KG needs two distinct nodes; others need entity_id
    CONSTRAINT ck_alert_rules_keying CHECK (
        (rule_type = 'KG_CONNECTION' AND node_a_entity_id IS NOT NULL
            AND node_b_entity_id IS NOT NULL AND node_a_entity_id <> node_b_entity_id)
        OR (rule_type <> 'KG_CONNECTION' AND entity_id IS NOT NULL)
    )
    -- + CHECK rule_type IN (...), CHECK severity IN (...), CHECK cooldown_seconds >= 0
);
-- Indexes: (rule_type) WHERE enabled, (entity_id) WHERE enabled,
--          (node_a_entity_id, node_b_entity_id) WHERE enabled, (tenant_id, user_id)

CREATE TABLE pending_alerts (
    pending_id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    alert_id UUID NOT NULL REFERENCES alerts(alert_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at TIMESTAMPTZ
);

CREATE TABLE alert_deliveries (
    delivery_id UUID PRIMARY KEY,
    alert_id UUID NOT NULL,
    user_id UUID NOT NULL,
    channel VARCHAR(20) NOT NULL DEFAULT 'websocket',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE alert_subscriptions (
    subscription_id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    entity_id UUID NOT NULL,
    watchlist_id UUID,
    alert_types JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE outbox_events (
    id UUID PRIMARY KEY,
    topic TEXT NOT NULL,
    avro_bytes BYTEA NOT NULL,  -- pre-serialized Avro
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE dead_letter_queue (
    id UUID PRIMARY KEY,
    topic TEXT,
    payload JSONB,
    error TEXT,
    resolved BOOLEAN DEFAULT false,
    resolved_note TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE email_preferences (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    send_day_of_week SMALLINT NOT NULL DEFAULT 1,  -- 0=Mon, 6=Sun
    send_hour_utc SMALLINT NOT NULL DEFAULT 8,
    last_digest_sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, user_id)
);

CREATE TABLE email_log (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    status VARCHAR(20) NOT NULL,  -- pending/sent/failed
    provider VARCHAR(20),
    provider_message_id TEXT,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## Alert Fan-out Logic

### Dedup Window (AD-9)

```
dedup_key = sha256(f"{entity_id}:{alert_type}:{created_at_epoch // window_seconds}")
```

Default window: 300 s (configurable via `ALERT_ALERT_DEDUP_WINDOW_SECONDS`). Same
entity+type within one window → single alert, multiple pending delivery rows.

### Backfill Suppression

| Topic | Rule |
|-------|------|
| `nlp.signal.detected.v1` | `is_backfill=true` → always suppress |
| `graph.state.changed.v1` | `is_backfill=true` → always suppress |
| `intelligence.contradiction.v1` | `is_backfill=true AND (now - occurred_at) > 30 days` → suppress |

### Fan-out Transaction

1. Backfill check → suppress if applicable
2. Resolve watchers via `WatchlistCache` → S1 fallback (best-effort — S1 unavailable returns `[]`, never raises)
3. Dedup check via `DedupRepository.exists(dedup_key)`
4. **Single transaction**: INSERT alert + INSERT pending_alert (per watcher) + INSERT outbox_event (per watcher)
5. **Post-commit**: WebSocket push via `ValkeyNotificationPublisher` (never inside transaction)

### Alert Title Composition (per-AlertType, payload-aware)

The `title` field is composed deterministically in `AlertFanoutUseCase._compose_alert_title`
from the entity subject (`ticker` → `entity_name`, resolved via S7) **and the raw event
payload**. Subject and detail are joined with an em-dash (`"AAPL — …"`). Per type:

- **SIGNAL** — `"<subject> — <signal_label>"` where `signal_label` is derived from
  `(claim_type, polarity)` (e.g. `"AAPL — Bullish guidance"`). When those NLP fields are
  missing/neutral, degrades to `"<subject> — price signal detected"`, or `"Signal detected"`
  with no subject.
- **GRAPH_CHANGE** — composes a rich tail from the (always-populated) `change_type` +
  `canonical_types` payload: `"AAPL — graph update: 5 new links (2 supplier, 2 executive,
  1 listing)"`. Relation types are humanised (`supplier_of`→supplier, `competes_with`→
  competitor, `has_executive`→executive, …) and counted, top-3 categories shown with a
  `+N more` overflow. Falls back to `"graph update"` when no structural detail is present.
- **CONTRADICTION** — `"<subject> — conflicting signals"` / `"Conflicting signals"`.

When no subject is resolved (S7 miss), the detail is capitalised as a standalone headline
(e.g. `"Graph update: 5 new links (…)"`) — still far better than the old opaque
`"Graph pattern change"`.

**Root-cause note**: opaque titles in the live demo were caused by (a) the S7 resolver
being unconfigured (`ALERT_S7_KNOWLEDGE_GRAPH_BASE_URL` / `ALERT_S7_INTERNAL_JWT` unset →
every subject `None`) and (b) graph titles ignoring the rich payload. Both are fixed:
the env vars are now in the config templates, and `_compose_graph_change_detail` mines the
payload.

**Invariant**: `title` MUST NEVER be a bare severity string like `"LOW signal"`.

The `backfill_alert_titles.py` script reuses the same composition (passing the persisted
`payload` as the event) so legacy rows get the same rich titles.

---

## S1 Portfolio Dependency

S10 requires these S1 internal endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/internal/v1/health` | GET | Health check |
| `/internal/v1/watchlists/by-entity/{entity_id}` | GET | Resolve watchers for single entity |
| `/internal/v1/watchlists/by-entities` | POST | Batch resolve watchers (max 100) |
| `/internal/v1/watchlists/{watchlist_id}/entities` | GET | Entities in watchlist |
| `/internal/v1/users/{user_id}` | GET | User profile for email delivery |

**Best-effort contract**: S1 unavailable (503, connection refused) → empty results,
never raises. Validated by 3 contract tests.

### Watchlist Cache (Valkey)

- **Key**: `s10:v1:watchlist:by_entity:{entity_id}`
- **TTL**: 300 s (configurable)
- **Invalidation**: On `portfolio.watchlist.updated.v1` → `item_deleted` events (DEL key)

---

## Email Digest (PLAN-0016 Waves C-1/D-1)

`EmailScheduler` (APScheduler `CronTrigger(minute=0)`) runs hourly, checks
`email_preferences.send_day_of_week` and `send_hour_utc`, and applies a 23-hour dedup
guard (`last_digest_sent_at < now() - 23h`).

Email content: calls S8 `POST /internal/v1/briefings` for the AI narrative +
S3 for portfolio performance data. Rendered via `render_digest_email()` (XSS-safe
`html.escape()`).

Email providers (configured via `ALERT_EMAIL_PROVIDER`):

| Provider | Env Var | Notes |
|----------|---------|-------|
| Resend | `ALERT_RESEND_API_KEY` | Primary |
| SendGrid | `ALERT_SENDGRID_API_KEY` | Fallback |
| SMTP | `ALERT_SMTP_*` vars | Local dev (MailHog) |

---

## Configuration

All env vars use prefix `ALERT_` except where noted.

| Variable | Default | Description |
|----------|---------|-------------|
| `ALERT_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/alert_db` | alert_db write URL |
| `ALERT_DATABASE_URL_READ` | `""` | Read replica URL for R27 (falls back to write URL when empty) |
| `ALERT_DB_POOL_SIZE` | `10` | Write pool size |
| `ALERT_DB_MAX_OVERFLOW` | `20` | Write pool max overflow |
| `ALERT_DB_POOL_SIZE_READ` | `20` | Read pool size |
| `ALERT_DB_MAX_OVERFLOW_READ` | `30` | Read pool max overflow |
| `ALERT_KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka brokers |
| `ALERT_KAFKA_SCHEMA_REGISTRY_URL` | `http://localhost:8081` | Schema registry |
| `ALERT_KAFKA_CONSUMER_GROUP` | `alert-service-group` | Intelligence consumer group |
| `ALERT_KAFKA_WATCHLIST_CONSUMER_GROUP` | `alert-service-watchlist-group` | Watchlist consumer group |
| `ALERT_KAFKA_TOPIC_SIGNAL` | `nlp.signal.detected.v1` | Consumed signal topic |
| `ALERT_KAFKA_TOPIC_GRAPH_STATE` | `graph.state.changed.v1` | Consumed graph change topic |
| `ALERT_KAFKA_TOPIC_CONTRADICTION` | `intelligence.contradiction.v1` | Consumed contradiction topic |
| `ALERT_KAFKA_TOPIC_WATCHLIST` | `portfolio.watchlist.updated.v1` | Consumed watchlist change topic |
| `ALERT_KAFKA_TOPIC_ALERT_DELIVERED` | `alert.delivered.v1` | Produced alert delivery topic |
| `ALERT_KAFKA_DLQ_TOPIC` | `alert.dead-letter.v1` | Produced DLQ topic |
| `ALERT_VALKEY_URL` | `redis://localhost:6379/0` | Valkey pub/sub + watchlist cache |
| `ALERT_API_GATEWAY_URL` | `http://api-gateway:8000` | S9 URL for JWKS fetch at startup |
| `ALERT_S1_PORTFOLIO_BASE_URL` | `http://localhost:8001` | S1 base URL for watchlist/user lookups |
| `ALERT_S7_KNOWLEDGE_GRAPH_BASE_URL` | `http://knowledge-graph:8007` | S7 URL for entity name/ticker enrichment |
| `ALERT_S8_BASE_URL` | `http://rag-chat:8008` | S8 URL for email digest briefing generation |
| `ALERT_S3_MARKET_DATA_BASE_URL` | `http://market-data:8003` | S3 URL for portfolio performance data + rule price/fundamental reads |
| `ALERT_S6_NLP_BASE_URL` | `http://nlp-pipeline:8006` | S6 URL for news-count/momentum rule reads (PLAN-0113, new) |
| `ALERT_S6_INTERNAL_JWT` | `""` | Pre-signed RS256 service JWT for S6 calls (PLAN-0113) |
| `ALERT_ALERT_RULE_POLLER_ENABLED` | `true` | Master switch for rule evaluation (false = rules dormant) |
| `ALERT_ALERT_RULE_POLL_TICK_SECONDS` | `60` | Poller base tick |
| `ALERT_ALERT_RULE_CADENCE_PRICE_SECONDS` | `60` | PRICE_CROSS poll cadence |
| `ALERT_ALERT_RULE_CADENCE_NEWS_COUNT_SECONDS` | `3600` | NEWS_COUNT poll cadence |
| `ALERT_ALERT_RULE_CADENCE_NEWS_MOMENTUM_SECONDS` | `3600` | NEWS_MOMENTUM poll cadence |
| `ALERT_ALERT_RULE_CADENCE_FUNDAMENTAL_SECONDS` | `21600` | FUNDAMENTAL_CROSS poll cadence (6h) |
| `ALERT_ALERT_RULE_MAX_PER_USER` | `200` | Per-user rule cap (PRD §9) |
| `ALERT_ALERT_RULE_POLLER_WATCHDOG_SECONDS` | `180` | Per-cycle `asyncio.wait_for` watchdog (BP-705) |
| `ALERT_S1_INTERNAL_JWT` | `""` | Pre-signed RS256 service JWT for S1 calls. **Required for watchlist lookups.** Without it, S1 returns 401. |
| `ALERT_S7_INTERNAL_JWT` | `""` | Pre-signed RS256 service JWT for S7 entity enrichment. Without it, entity_name/ticker will be null in alerts. |
| `ALERT_S8_INTERNAL_JWT` | `""` | Pre-signed RS256 service JWT for S8 briefing calls in email digests. **Required for email digest generation.** |
| `ALERT_ALERT_DEDUP_WINDOW_SECONDS` | `300` | Dedup window in seconds (AD-9) |
| `ALERT_WATCHLIST_CACHE_TTL_SECONDS` | `300` | Valkey watchlist cache TTL (seconds) |
| `ALERT_PENDING_ALERT_TTL_DAYS` | `7` | How long pending alerts are kept before pruning |
| `ALERT_ENTITY_RESOLVER_CACHE_TTL_SECONDS` | `900` | Entity name/ticker enrichment cache TTL (15 min) |
| `ALERT_INTERNAL_JWT_SKIP_VERIFICATION` | `false` | **Dev/test only** — skip RS256 JWT verification. Rejected when `APP_ENV=production`. |
| `ALERT_JTI_REPLAY_CHECK_ENABLED` | `false` | Disable JTI replay check (disabled by default — S10 receives forwarded user JWTs from S8 which have already been consumed) |
| `ALERT_ADMIN_TOKEN` | `""` | DLQ admin endpoint bearer token (`X-Admin-Token` header) |
| `ALERT_DISPATCHER_POLL_INTERVAL_S` | `1.0` | Outbox dispatcher poll interval |
| `ALERT_DISPATCHER_BATCH_SIZE` | `50` | Outbox dispatcher batch size |
| `ALERT_EMAIL_PROVIDER` | `resend` | Email provider: `resend` \| `sendgrid` \| `smtp` |
| `ALERT_EMAIL_FROM_ADDRESS` | `""` | From address for outbound emails |
| `ALERT_RESEND_API_KEY` | `""` | Resend API key |
| `ALERT_SENDGRID_API_KEY` | `""` | SendGrid API key |
| `ALERT_SMTP_HOST` | `localhost` | SMTP host (local dev: MailHog at `mailhog:1025`) |
| `ALERT_SMTP_PORT` | `587` | SMTP port |
| `ALERT_SMTP_USER` | `""` | SMTP username |
| `ALERT_SMTP_PASSWORD` | `""` | SMTP password |
| `ALERT_SEVERITY_CRITICAL_THRESHOLD` | `0.85` | `market_impact_score` threshold for CRITICAL |
| `ALERT_SEVERITY_HIGH_THRESHOLD` | `0.65` | `market_impact_score` threshold for HIGH |
| `ALERT_SEVERITY_MEDIUM_THRESHOLD` | `0.40` | `market_impact_score` threshold for MEDIUM |
| `ALERT_LOG_LEVEL` | `INFO` | Log level |
| `ALERT_LOG_JSON` | `true` | JSON-structured logs |
| `ALERT_OTLP_ENDPOINT` | `""` | OpenTelemetry collector endpoint |

> **Note**: `INTERNAL_SERVICE_TOKEN` (no prefix) was removed — S10 now uses `ALERT_S1_INTERNAL_JWT` / `ALERT_S7_INTERNAL_JWT` / `ALERT_S8_INTERNAL_JWT` for per-service auth.

---

## How to Run Locally

### Full Docker Compose (Recommended)

```bash
make dev    # starts all services including S10 on port 8010
```

### Standalone

```bash
cd services/alert

cat > .env << 'EOF'
ALERT_DATABASE_URL=postgresql+asyncpg://alert:alertpw@localhost:5432/alert_db
ALERT_KAFKA_BOOTSTRAP_SERVERS=localhost:9092
ALERT_VALKEY_URL=redis://localhost:6379/0
ALERT_S1_PORTFOLIO_BASE_URL=http://localhost:8001
ALERT_INTERNAL_JWT_SKIP_VERIFICATION=true   # no Zitadel required
# For email digests, set pre-signed service JWTs:
# ALERT_S1_INTERNAL_JWT=<pre-signed-jwt>
# ALERT_S7_INTERNAL_JWT=<pre-signed-jwt>
# ALERT_S8_INTERNAL_JWT=<pre-signed-jwt>
EOF

# Run API server
uvicorn alert.app:create_app --factory --host 0.0.0.0 --port 8010 --reload

# In separate terminals:
python -m alert.infrastructure.messaging.consumers.intelligence_consumer_main
python -m alert.infrastructure.messaging.consumers.watchlist_consumer_main
python -m alert.infrastructure.messaging.outbox.dispatcher_main
```

### Connecting WebSocket (Dev)

```bash
# 1. Get a short-lived WebSocket token from S9:
curl http://localhost:8000/v1/auth/ws-token \
  -H "Authorization: Bearer <access_token>"
# → {"token": "<30s-jwt>"}

# 2. Connect:
wscat -c "ws://localhost:8010/api/v1/alerts/stream?token=<30s-jwt>"
```

---

## How to Run Tests

```bash
cd services/alert

python -m pytest tests/ -v              # all tests
python -m pytest tests/ -m unit -v     # unit only (fast)
python -m pytest tests/ -m contract -v # contract tests (Avro schema validation)
python -m pytest tests/ -m integration -v  # requires Docker (testcontainers)
```

Tests use: testcontainers for Postgres, `fakeredis.FakeServer` for Valkey,
`pytest-httpserver` for S1.

---

## Backfill Script

```bash
export ALERT_DB_URL="postgres://alert:alertpw@localhost:5443/alert_db"

# Dry-run (count NULL title rows)
python -m alert.scripts.backfill_alert_titles --dry-run

# Live (fills in batches of 1000)
python -m alert.scripts.backfill_alert_titles
```

---

## Observability

**Prometheus metrics** (`s10_` prefix):

| Metric | Description |
|--------|-------------|
| `s10_alerts_fanned_out_total` | Alerts emitted, by `type` label |
| `s10_alerts_deduplicated_total` | Alerts suppressed by dedup |
| `s10_websocket_pushes_total` | Successful WS pushes |
| `s10_alerts_pending_total` | Current unacknowledged alert count |
| `s10_alerts_by_severity_total` | Alerts created by severity |
| `s10_flash_overlays_triggered_total` | Frontend flash overlay triggers |

---

## Common Pitfalls

- **WebSocket auth is inline, not middleware** — `BaseHTTPMiddleware` skips WS connections.
  The route validates `?token=` manually using S9's public key.

- **`AlertFanoutUseCase` takes `notification_publisher: INotificationPublisher`** — tests
  must pass `notification_publisher=` kwarg, not `connection_manager=`.

- **`ack` endpoint returns 200 (not 204)** — FastAPI 0.111 requires explicit `Response` for 204.

- **`severity` query param must be lowercase** — `AlertSeverity` is a lowercase StrEnum.
  `?min_severity=HIGH` returns 422.

- **Snooze body field is `until`** — NOT `snooze_until`.

- **ACK and snooze on rows with `tenant_id IS NULL`** return `forbidden`, not `ok`.

- **`ConnectionManager._connections` is in-memory** — use `ValkeyNotificationPublisher`
  (the primary path) for cross-process delivery; `ConnectionManager` is retained for
  in-process tests only.

- **Outbox dispatcher uses raw `confluent_kafka.Producer`** (no schema registry) — bytes
  are pre-serialized by `AlertFanoutUseCase`.

- **`create_app()` does NOT run lifespan** — wire `app.state.*` manually in tests.

- **S10 does NOT validate `user_id` against a session token** — it trusts S9 to inject
  the correct `user_id`. Never expose S10 directly to public traffic.

- **`INTERNAL_SERVICE_TOKEN` (no prefix) is REMOVED** — replaced by per-service JWTs
  `ALERT_S1_INTERNAL_JWT`, `ALERT_S7_INTERNAL_JWT`, `ALERT_S8_INTERNAL_JWT`. Without these,
  S1/S7/S8 calls will return 401 and alerts will have null `entity_name`/`ticker` fields.

- **`ALERT_JTI_REPLAY_CHECK_ENABLED=false` by default** — S10 receives forwarded user JWTs
  from S8's briefing call path; these JWTs have already been consumed by InternalJWTMiddleware
  on S8, so JTI replay detection on S10 would falsely reject them.

- **Email scheduler requires all three JWTs** — `ALERT_S8_INTERNAL_JWT` for the briefing call,
  `ALERT_S1_INTERNAL_JWT` for user email lookup. Without them the scheduler logs a CRITICAL
  warning at startup and email digests will fail silently with 401.
