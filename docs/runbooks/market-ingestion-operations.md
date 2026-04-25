# Market Ingestion Service — Operations Runbook

> **Service**: `market-ingestion` | **Port**: 8002 | **Team**: Ingestion domain

---

## Table of Contents

1. [Service Overview](#1-service-overview)
2. [Process Architecture](#2-process-architecture)
3. [Health Checks & Monitoring](#3-health-checks--monitoring)
4. [Common Operations](#4-common-operations)
5. [Runbooks](#5-runbooks)
6. [EODHD Quota Management](#6-eodhd-quota-management)
7. [Go-Live Checklist](#7-go-live-checklist)
8. [Rollback Procedures](#8-rollback-procedures)

---

## 1. Service Overview

The market-ingestion service owns the full lifecycle of raw market data acquisition:
polling, backfill, rate-limiting, object storage (bronze + canonical), and event
publication via the transactional outbox.

**Four processes (all from the same Docker image)**:

| Process | Command | Role |
|---------|---------|------|
| API | `uvicorn market_ingestion.app:create_app --factory` | REST endpoints, readiness/liveness |
| Scheduler | `python -m market_ingestion.scheduler.main` | Tick-based task enqueue |
| Worker | `python -m market_ingestion.worker.main` | Task execution (fetch → store → publish) |
| Dispatcher | `python -m market_ingestion.messaging.dispatcher_main` | Outbox → Kafka relay |

---

## 2. Process Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Scheduler (60s tick)                                            │
│  ScheduleDueTasksUseCase → ingestion_tasks (PENDING)            │
└────────────────────────────────┬────────────────────────────────┘
                                 │ INSERT ON CONFLICT DO NOTHING
                                 ▼
                    ┌─────────────────────────┐
                    │   ingestion_tasks DB     │
                    └──────────┬──────────────┘
                               │ FOR UPDATE SKIP LOCKED
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Worker (batch claim + execute)                                  │
│  1. Fetch raw data from provider (EODHD/Polygon/…)              │
│  2. PUT bronze bytes → MinIO market-bronze/                      │
│  3. Canonicalize → JSONL                                         │
│  4. PUT canonical → MinIO market-canonical/                      │
│  5. Advance watermark + add outbox event + mark DONE            │
└────────────────────────────────┬────────────────────────────────┘
                                 │ INSERT outbox_events
                                 ▼
                    ┌─────────────────────────┐
                    │   outbox_events DB       │
                    └──────────┬──────────────┘
                               │ claim_batch (FOR UPDATE SKIP LOCKED)
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Dispatcher                                                      │
│  Produce to Kafka: market.dataset.fetched                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Health Checks & Monitoring

### Endpoints

```bash
# Liveness (always 200 if process is running)
curl http://localhost:8002/healthz

# Readiness (checks DB + MinIO)
curl http://localhost:8002/readyz

# Prometheus metrics
curl http://localhost:8002/metrics
```

### Key Metrics to Watch

| Metric | Alert threshold | Notes |
|--------|----------------|-------|
| `ingestion_tasks_pending` | > 500 for > 10 min | Worker falling behind |
| `ingestion_tasks_error` | > 50 for > 5 min | Provider or storage failures |
| `outbox_events_pending` | > 200 for > 5 min | Dispatcher falling behind |
| `provider_rate_limited_total` | Any spike | EODHD budget exhausted |
| Worker process exit | Any | Auto-restart via `restart: unless-stopped` |

### Log Queries (structlog)

```bash
# Failed tasks in last 1 hour
docker logs svc-market-ingestion-worker 2>&1 | grep "fetch_fatal_error" | tail -20

# Scheduler tick summary
docker logs svc-market-ingestion-scheduler 2>&1 | grep "scheduler_tick_complete" | tail -10

# Dispatcher publish errors
docker logs svc-market-ingestion-dispatcher 2>&1 | grep "dispatch_failed" | tail -20
```

---

## 4. Common Operations

### Trigger Manual Ingestion

```bash
# Trigger AAPL OHLCV ingestion (202 Accepted)
curl -X POST http://localhost:8002/api/v1/ingest/trigger \
  -H "Content-Type: application/json" \
  -d '{"provider":"eodhd","symbols":["AAPL","MSFT"],"dataset_type":"ohlcv","timeframe":"1d"}'
```

### Trigger Backfill

```bash
# Backfill 3 months of AAPL daily data in 30-day chunks
curl -X POST http://localhost:8002/api/v1/ingest/backfill \
  -H "Content-Type: application/json" \
  -d '{
    "provider":"eodhd",
    "symbol":"AAPL",
    "start_date":"2024-01-01",
    "end_date":"2024-04-01",
    "timeframe":"1d",
    "chunk_days":30
  }'
```

### Check Task Queue Status

```bash
curl http://localhost:8002/api/v1/ingest/status
# Returns: {"counts":{"pending":12,"running":2,"done":1547,"error":0},"total":1561}
```

### List Active Policies

```bash
curl http://localhost:8002/api/v1/policies
```

### Run Database Migration

```bash
# Using Docker
docker compose run --rm migrate-market-ingestion

# Locally
cd services/market-ingestion
alembic upgrade head
```

### Scale Workers

```bash
# Run 3 worker replicas
docker compose up --scale svc-market-ingestion-worker=3 -d
```

---

## 5. Runbooks

### RB-001: Tasks Stuck in PENDING

**Symptom**: `ingestion_tasks_pending` is rising; workers appear healthy.

**Steps**:
1. Check worker logs for errors:
   ```bash
   docker logs svc-market-ingestion-worker --tail=100
   ```
2. Check DB for locked tasks:
   ```sql
   SELECT status, COUNT(*) FROM ingestion_tasks GROUP BY status;
   SELECT * FROM ingestion_tasks WHERE status='running' AND lease_expires < now();
   ```
3. If stale leases exist, restart the worker — `claim_batch` uses `SKIP LOCKED`
   so restarted workers will pick up orphaned tasks once leases expire.
4. If lease_seconds is too short for slow provider calls, increase
   `MARKET_INGESTION_WORKER_LEASE_SECONDS`.

---

### RB-002: Provider Rate Limited (429)

**Symptom**: `provider_rate_limited_total` spiking; tasks retrying repeatedly.

**Steps**:
1. Tasks with `ProviderRateLimited` errors are automatically retried with
   back-off (up to `max_attempts`).
2. Check the provider budget table:
   ```sql
   SELECT * FROM provider_budgets WHERE provider='eodhd';
   ```
3. Reduce `MARKET_INGESTION_SCHEDULER_MAX_TASKS_PER_TICK` to lower throughput.
4. Consider adding a second provider adapter (Polygon, Finnhub) and distributing load.

---

### RB-003: Outbox Dispatcher Stuck

**Symptom**: `outbox_events_pending` growing; Kafka topics not receiving events.

**Steps**:
1. Check dispatcher logs:
   ```bash
   docker logs svc-market-ingestion-dispatcher --tail=100 | grep "dispatch"
   ```
2. Verify Kafka connectivity:
   ```bash
   docker exec svc-market-ingestion-dispatcher \
     python -c "from confluent_kafka import Producer; p=Producer({'bootstrap.servers':'kafka:29092'}); print('OK')"
   ```
3. If Schema Registry is down, the dispatcher will fail to serialize.
   Check `http://schema-registry:8081/subjects`.
4. After fixing connectivity, events exceeding `dispatcher_max_attempts` are in
   `dead_letter_events`. These need manual requeue or replay.

---

### RB-004: Storage (MinIO) Unavailable

**Symptom**: `readyz` returns 503 with `"storage": "error: ..."`.

**Steps**:
1. Check MinIO health:
   ```bash
   curl http://minio:9000/minio/health/live
   ```
2. Workers will get `StorageUnavailable` errors — tasks are retried automatically.
3. Once MinIO recovers, workers resume automatically.
4. Ensure `market-bronze` and `market-canonical` buckets exist (run `init-minio` init job).

---

### RB-005: Dead-Letter Events

**Symptom**: Events in `dead_letter_events` table after max dispatch attempts.

**Steps**:
1. Inspect dead-letter records:
   ```sql
   SELECT id, event_type, error_message, attempts, created_at
   FROM dead_letter_events
   ORDER BY created_at DESC LIMIT 20;
   ```
2. To requeue: move records back to `outbox_events` with `status='pending', attempts=0`:
   ```sql
   INSERT INTO outbox_events (id, event_type, topic, payload, status, attempts, created_at)
   SELECT id, event_type, topic, payload, 'pending', 0, now()
   FROM dead_letter_events
   WHERE id = '<record_id>';
   DELETE FROM dead_letter_events WHERE id = '<record_id>';
   ```

---

## 6. EODHD Quota Management

### Overview

EODHD provides up to 100,000 API credits/month on the professional plan. Each API call costs:
- Real-time quote: 1 credit
- EOD bar: 1 credit
- Fundamentals: 5–50 credits
- Bulk quote: 1 credit per symbol

PLAN-0036 enforces a hard monthly limit via the circuit breaker (opens at 95%).

---

### Monitoring

Key Grafana dashboard: `EODHD API Health` (uid: `eodhd-health-v1`)

Key metrics:

| Metric | Description |
|--------|-------------|
| `s2_eodhd_monthly_credits_used` | Credits used this calendar month |
| `s2_eodhd_circuit_breaker_state` | 0=closed, 1=open, 2=half_open |
| `s2_eodhd_rate_limited_total` | Rate-limit responses from EODHD |
| `s2_eodhd_credits_used_total` | Cumulative credits used (labeled by endpoint, symbol_tier) |

Quick check via the API:
```bash
curl http://localhost:8002/api/v1/eodhd/quota/status
```

---

### Alert Response

#### EodhdQuotaWarning (>80%)

1. Identify which endpoint/tier is consuming most credits via Grafana.
2. Consider promoting high-volume symbols to T3 (EOD-only) tier to reduce intraday calls.
3. Verify fundamentals/macro/economic_events cadence is set to 90 days (migration 0009).

#### EodhdQuotaCritical (>95%)

1. Circuit breaker will open automatically at 95% — no further EODHD calls are made.
2. Prices are now served from stale PriceSnapshots; frontend shows "~" prefix on affected tickers.
3. Check if the monthly reset is imminent (credits reset on the 1st of the month).
4. If many days remain: promote symbols to T3/T4 to reduce future consumption after reset.

#### EodhdCircuitBreakerOpen

1. Confirm circuit breaker state:
   ```bash
   curl http://localhost:8002/api/v1/eodhd/quota/status
   ```
2. If month just reset and counter is stale: restart market-ingestion to reset Valkey counters.
3. If quota is genuinely exhausted: inform stakeholders; prices are served from snapshots until reset.

#### EodhdSustained429s

1. Check the EODHD status page for platform-wide incidents.
2. Verify rate-limiting is applied correctly (Retry-After header is respected by the adapter).
3. Check for multiple competing instances sharing the same quota window — only one scheduler
   should produce tasks at a time.

---

### Tier Management

Symbol tiers control polling frequency and credit consumption:

| Tier | Audience | Frequency | Dataset |
|------|----------|-----------|---------|
| T0 | Portfolio holdings | 5-minute real-time quotes | Real-time + EOD |
| T1 | Watchlist symbols | 15-minute quotes | Real-time + EOD |
| T2 | Tracked symbols (default) | 1-hour quotes | EOD |
| T3 | Screener symbols | EOD only (post-market) | EOD only |
| T4 | Inactive | Not polled | None |

To change a symbol's tier:
```bash
# Via API (preferred)
curl -X POST http://localhost:8002/api/v1/symbols/AAPL/tier \
  -H "Content-Type: application/json" \
  -d '{"tier": "T3"}'

# Or directly in the database
UPDATE symbol_tiers SET tier = 3 WHERE symbol = 'AAPL' AND exchange = 'US';
```

---

### Derived OHLCV Bars

Weekly (1W) and monthly (1M) OHLCV bars are derived locally from daily bars (PLAN-0036 W2-4).
EODHD is **never** called for 1W or 1M timeframes — these cost 0 credits.

To verify derived bars are present for a symbol:
```sql
SELECT timeframe, COUNT(*), MIN(bar_date), MAX(bar_date)
FROM ohlcv_bars
WHERE instrument_id = '<instrument_id>' AND is_derived = true
GROUP BY timeframe;
```

---

### Emergency Procedures

#### Force-reset circuit breaker

Only perform this if you are certain the quota has been reset (new billing month or plan upgrade):

```bash
# Connect to the Valkey CLI and delete the quota counter
redis-cli -h valkey -p 6379 DEL market:eodhd:quota:credits_used
```

Then restart the market-ingestion service so it picks up a fresh counter:
```bash
docker compose restart svc-market-ingestion svc-market-ingestion-scheduler \
  svc-market-ingestion-worker svc-market-ingestion-dispatcher
```

#### Hard-disable EODHD polling

Set `EODHD_ENABLED=false` in the service environment and restart market-ingestion.
No EODHD API calls will be made; prices fall through to the stale PriceSnapshot layer.

```bash
# In docker-compose.override.yml or the .env file:
MARKET_INGESTION_EODHD_ENABLED=false
```

---

## 7. Go-Live Checklist

### Infrastructure Pre-requisites

- [ ] PostgreSQL database `ingestion_db` created and accessible
- [ ] Alembic migrations applied: `docker compose run --rm migrate-market-ingestion`
- [ ] MinIO buckets created (`market-bronze`, `market-canonical`, `market-ingestion`)
- [ ] Kafka topics created: `market.dataset.fetched`
- [ ] Schema Registry running and reachable
- [ ] Avro schemas registered for `MarketDatasetFetchedV1`

### Configuration

- [ ] `MARKET_INGESTION_EODHD_API_KEY` set to production API key (not "demo")
- [ ] `MARKET_INGESTION_DATABASE_URL` points to production Postgres
- [ ] `MARKET_INGESTION_KAFKA_BOOTSTRAP_SERVERS` points to production Kafka
- [ ] `MARKET_INGESTION_STORAGE_ACCESS_KEY` / `SECRET_KEY` set correctly
- [ ] `MARKET_INGESTION_OTLP_ENDPOINT` set for tracing (if using OTel)
- [ ] `MARKET_INGESTION_LOG_LEVEL=INFO` (not DEBUG in prod)
- [ ] Docker env file created: `cp configs/docker.env.example configs/.env`

### Smoke Tests

```bash
# 1. Liveness
curl -f http://localhost:8002/healthz

# 2. Readiness
curl -f http://localhost:8002/readyz

# 3. Trigger ingestion for AAPL
curl -sf -X POST http://localhost:8002/api/v1/ingest/trigger \
  -H "Content-Type: application/json" \
  -d '{"provider":"eodhd","symbols":["AAPL"],"dataset_type":"ohlcv","timeframe":"1d"}' \
  | python3 -m json.tool

# 4. Check task was created
curl -s http://localhost:8002/api/v1/ingest/status | python3 -m json.tool

# 5. Verify seed policies are loaded
curl -s http://localhost:8002/api/v1/policies | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Policies: {d[\"total\"]}')"
```

### Process Health

- [ ] `svc-market-ingestion` API container healthy (`/healthz` returns 200)
- [ ] `svc-market-ingestion-scheduler` container running (check logs for `scheduler_tick_complete`)
- [ ] `svc-market-ingestion-worker` container running (check logs for `tasks_claimed`)
- [ ] `svc-market-ingestion-dispatcher` container running (check logs for `dispatcher_starting`)
- [ ] No containers in restart loop (`docker compose ps`)

### Downstream Validation

- [ ] Kafka topic `market.dataset.fetched` receiving events after first worker tick
- [ ] MinIO `market-bronze/` bucket contains raw data objects
- [ ] MinIO `market-canonical/` bucket contains `.jsonl` files
- [ ] Market Data service consuming `market.dataset.fetched` events (check its logs)

---

## 8. Rollback Procedures

### Code Rollback

```bash
# Stop the new image
docker compose stop svc-market-ingestion svc-market-ingestion-scheduler \
  svc-market-ingestion-worker svc-market-ingestion-dispatcher

# Pull/tag the previous image and restart
docker compose up -d svc-market-ingestion svc-market-ingestion-scheduler \
  svc-market-ingestion-worker svc-market-ingestion-dispatcher
```

### Database Migration Rollback

```bash
# Roll back one revision
cd services/market-ingestion
alembic downgrade -1
```

> **WARNING**: Alembic `downgrade -1` from `0002` removes the seed polling policies.
> Re-run `alembic upgrade head` to restore them.

### Policy Rollback

If new seed policies caused unexpected behaviour:
```sql
-- Disable specific policies without deleting them
UPDATE polling_policies SET enabled = false WHERE id IN (...);
```
