# Market Ingestion Service — Operations Runbook

> **Service**: `market-ingestion` | **Port**: 8002 | **Team**: Ingestion domain

---

## Table of Contents

1. [Service Overview](#1-service-overview)
2. [Process Architecture](#2-process-architecture)
3. [Health Checks & Monitoring](#3-health-checks--monitoring)
4. [Common Operations](#4-common-operations)
5. [Runbooks](#5-runbooks)
6. [Go-Live Checklist](#6-go-live-checklist)
7. [Rollback Procedures](#7-rollback-procedures)

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

## 6. Go-Live Checklist

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

## 7. Rollback Procedures

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
