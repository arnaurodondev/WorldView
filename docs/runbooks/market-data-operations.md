# Market Data Service — Operations Runbook

> **Service**: market-data · **Port**: 8003 · **DB**: `market_data_db` (TimescaleDB)

---

## Quick Reference

| Check | Command |
|-------|---------|
| Health | `curl http://localhost:8003/healthz` |
| Readiness | `curl http://localhost:8003/readyz` |
| Metrics | `curl http://localhost:8003/metrics` |
| Container status | `docker compose ps market-data` |
| App logs | `docker compose logs -f market-data` |
| DB connect | `psql postgresql://postgres:postgres@localhost:5432/market_data_db` |
| Valkey CLI | `docker compose exec valkey valkey-cli` |

---

## Deployment (6-Phase Checklist)

### Phase 1 — Pre-deployment

- [ ] Confirm all CI gates are green on the release branch.
- [ ] Verify no breaking Avro schema changes: `git diff HEAD~1 infra/kafka/schemas/`.
- [ ] Review Alembic migration plan: `alembic show head` and inspect the migration file.
- [ ] Confirm `prod.env.example` is current; validate all required env vars are set in the
      deployment target.
- [ ] Back up the `market_data_db` if running a destructive migration
      (additive-only migrations do not require a backup).

### Phase 2 — Database migration

```bash
# Run from inside the container or a migration runner pod
cd services/market-data
alembic upgrade head
```

Wait for confirmation that `alembic_version` contains the expected head revision:
```sql
SELECT version_num FROM alembic_version;
-- Expected: 002
```

**Rollback (migration)**: `alembic downgrade -1` reverts one migration. Never run
`downgrade base` in production — data loss is permanent.

> **Constraint-window warning (migration `031_extend_field_type_check`)**: this
> migration `DROP CONSTRAINT`s then `ADD CONSTRAINT`s
> `ck_screen_field_metadata_field_type` (an immediate full check, not `NOT VALID`),
> leaving a sub-millisecond window where the CHECK is absent. Run it during a quiet
> window with no concurrent `screen_field_metadata` writes, or accept the
> near-zero risk — the only concurrent writer, `_screen_fields_refresh_loop`, only
> writes known-good `field_type` values from `_get_static_screen_fields()`, so a
> bad row cannot land in normal operation. Future constraint-widening migrations
> should prefer `ADD CONSTRAINT … NOT VALID` followed by `VALIDATE CONSTRAINT` —
> that pattern never drops the old constraint and eliminates the window entirely.

### Phase 3 — Deploy application containers

```bash
docker compose pull market-data
docker compose up -d --no-deps market-data
```

Monitor startup:
```bash
docker compose logs -f market-data | head -40
```

Expected log lines on healthy start:
```
market_data_started
ohlcv_consumer started
quotes_consumer started
fundamentals_consumer started
outbox_dispatcher started
```

### Phase 4 — Smoke test

```bash
curl -sf http://localhost:8003/healthz | jq .
# {"status":"ok"}

curl -sf http://localhost:8003/readyz | jq .
# {"status":"ok","checks":{"db":"ok","valkey":"ok","storage":"ok","kafka":"ok"}}
```

If `readyz` returns 503, check `checks` for the failing component.

### Phase 5 — Consumer lag check

After deployment, verify consumer groups are catching up:

```bash
# Requires kafkacat / kcat
kcat -b localhost:9092 -G market-data-ohlcv-status market.dataset.fetched
```

Or via Confluent/Redpanda UI: confirm lag < 1000 for all three consumer groups
(`market-data-ohlcv`, `market-data-quotes`, `market-data-fundamentals`).

### Phase 6 — Post-deployment validation

- [ ] Spot-check a recent OHLCV query: `GET /api/v1/ohlcv/{instrument_id}?timeframe=1d&start=...&end=...`
- [ ] Confirm quote cache is warm: `GET /api/v1/quotes/{instrument_id}` should return 200 for an active instrument.
- [ ] Verify outbox backlog is draining: `SELECT count(*) FROM outbox_events WHERE status='PENDING';`
- [ ] Set alert baseline in monitoring dashboard.

---

## Rollback

### Application rollback (no schema change)

```bash
docker compose stop market-data
docker compose up -d --no-deps market-data@<previous-image-tag>
```

### Application rollback (with schema change)

1. Roll back application to previous image tag (same as above).
2. Revert the Alembic migration: `alembic downgrade -1`.
3. Verify `alembic_version` reflects the previous head.
4. Smoke test.

### Per-phase rollback decision tree

| Phase | Failure symptom | Rollback action |
|-------|----------------|-----------------|
| 2 (migration) | Migration fails with error | Fix migration file; re-run `upgrade head` |
| 3 (container deploy) | Container exits immediately | `docker compose logs market-data`; revert image |
| 4 (smoke test) | `/readyz` → 503 on `db` | Check DB connectivity; verify `DATABASE_URL` env var |
| 4 (smoke test) | `/readyz` → 503 on `valkey` | Check Valkey container; verify `VALKEY_URL` |
| 4 (smoke test) | `/readyz` → 503 on `storage` | Check MinIO; verify bucket exists and credentials |
| 5 (consumer lag) | Lag growing indefinitely | Check consumer logs; verify Kafka bootstrap servers |
| 6 (validation) | OHLCV query returns 0 rows | Check consumer lag; verify `canonical_ref` in MinIO |

---

## Incident Response Playbook

### Scenario: No OHLCV data after ingestion event

**Symptoms**: `GET /api/v1/ohlcv/{id}` returns empty list despite market-ingestion
publishing `market.dataset.fetched` events.

**Steps**:
1. Check consumer logs: `docker compose logs -f market-data | grep ohlcv_consumer`.
2. Check consumer lag for group `market-data-ohlcv`.
3. Check `ingestion_events` table for duplicate: `SELECT * FROM ingestion_events WHERE event_id='<event_id>';`
   If found → duplicate; the event was already processed.
4. Check `failed_tasks` for the event: `SELECT * FROM failed_tasks ORDER BY created_at DESC LIMIT 5;`
5. If the task is in `failed_tasks`, check `last_error` and `attempts`.
6. If the object is missing from MinIO, the ingestion service failed to upload it —
   investigate market-ingestion.

### Scenario: Quote cache returns stale data

**Symptoms**: Quote API returns old values; DB has fresh data.

**Steps**:
1. Confirm TTL: the quote cache TTL is 5 seconds. Stale data resolves automatically.
2. If TTL has passed and values are still stale, check Valkey connectivity.
3. Manual flush: `docker compose exec valkey valkey-cli KEYS 'quote:v1:*' | xargs valkey-cli DEL`

### Scenario: Outbox events not being dispatched

**Symptoms**: `outbox_events` table has many `PENDING` rows; consumer groups do not
see new instrument lifecycle events.

**Steps**:
1. Check dispatcher logs: `docker compose logs market-data | grep outbox`.
2. Check Kafka producer connectivity in dispatcher logs.
3. Check for stale leases: `SELECT count(*) FROM outbox_events WHERE status='PENDING' AND lease_expires_at < now();`
   If high count → dispatcher crashed mid-flight. Run:
   ```sql
   UPDATE outbox_events
   SET claimed_by=NULL, claimed_at=NULL, lease_expires_at=NULL
   WHERE status='PENDING' AND lease_expires_at < now();
   ```
4. Restart the market-data container to restart the dispatcher.

### Scenario: TimescaleDB hypertable chunk count is excessive

**Symptoms**: `ohlcv_bars` query is slow despite indexes; `EXPLAIN` shows many chunks scanned.

**Steps**:
1. Check chunk count:
   ```sql
   SELECT count(*) FROM timescaledb_information.chunks
   WHERE hypertable_name = 'ohlcv_bars';
   ```
2. Confirm chunk interval: should be `1 month` per ADR-0006.
3. Enable chunk pruning by ensuring `bar_date` filter is in all queries (already enforced by `PgOHLCVRepository`).
4. If old chunks are never queried, enable TimescaleDB compression:
   ```sql
   ALTER TABLE ohlcv_bars SET (
     timescaledb.compress,
     timescaledb.compress_orderby = 'bar_date',
     timescaledb.compress_segmentby = 'instrument_id,timeframe'
   );
   SELECT add_compression_policy('ohlcv_bars', INTERVAL '3 months');
   ```

---

## Configuration Reference

All configuration is via `pydantic-settings` with the `MARKET_DATA_` prefix.
See `services/market-data/configs/prod.env.example` for the full list.

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `MARKET_DATA_HOST` | No | `0.0.0.0` | Bind address |
| `MARKET_DATA_PORT` | No | `8003` | HTTP port |
| `MARKET_DATA_DATABASE_URL` | **Yes** | — | asyncpg URL |
| `MARKET_DATA_KAFKA_BOOTSTRAP_SERVERS` | **Yes** | — | `host:port` |
| `MARKET_DATA_SCHEMA_REGISTRY_URL` | **Yes** | — | Confluent SR URL |
| `MARKET_DATA_STORAGE_ENDPOINT` | **Yes** | — | MinIO/S3 endpoint |
| `MARKET_DATA_STORAGE_ACCESS_KEY` | **Yes** | — | S3 access key |
| `MARKET_DATA_STORAGE_SECRET_KEY` | **Yes** | — | S3 secret key |
| `MARKET_DATA_VALKEY_URL` | **Yes** | — | `redis://host:port/db` |
| `MARKET_DATA_OTLP_ENDPOINT` | No | — | OTel collector endpoint; omit to disable tracing |
| `MARKET_DATA_DEBUG` | No | `false` | Enables SQLAlchemy echo |

---

## Useful Queries

```sql
-- How many OHLCV bars per instrument?
SELECT instrument_id, timeframe, count(*) AS bar_count,
       min(bar_date), max(bar_date)
FROM ohlcv_bars
GROUP BY instrument_id, timeframe
ORDER BY bar_count DESC
LIMIT 20;

-- Which instruments have OHLCV but no quotes?
SELECT i.symbol, i.exchange
FROM instruments i
WHERE i.has_ohlcv = true AND i.has_quotes = false;

-- Pending outbox events older than 5 minutes (stuck dispatcher alert)
SELECT count(*) FROM outbox_events
WHERE status = 'PENDING' AND created_at < now() - INTERVAL '5 minutes';

-- TimescaleDB chunk sizes
SELECT chunk_name, range_start, range_end,
       pg_size_pretty(total_bytes) AS total
FROM timescaledb_information.chunks
WHERE hypertable_name = 'ohlcv_bars'
ORDER BY range_start DESC
LIMIT 10;
```
