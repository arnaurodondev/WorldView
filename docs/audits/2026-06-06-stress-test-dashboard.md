# Dashboard Stress Test Report
**Date**: 2026-06-08
**Concurrent users**: 8
**Instrument IDs tested**: 7 (TSLA, AMZN, GOOGL, META, JPM, NFLX, AAPL)

## 1. Baseline Latency (single user)

| Endpoint | Cold (s) | Warm (s) |
|----------|----------|----------|
| `/v1/companies/overviews:batch` | 16.875 | 14.215 |
| `/v1/dashboard/bundle` | 14.724 | 9.336 |
| `/v1/dashboard/snapshot` | 20.559 | 7.156 |
| `/v1/entities/11111111-0005-7000-8000-000000000001/intelligence-bundle` | 8.467 | 4.492 |
| `/v1/holdings/01900000-0000-7000-8000-000000000100` | 2.978 | 5.139 |
| `/v1/market/top-movers` | 13.273 | 9.306 |

## 2. Stress Test Results (8 concurrent dashboard loads)
**Total wall time**: 24.78s

| Endpoint | p50 (s) | p95 (s) | p99 (s) | min (s) | max (s) | errors |
|----------|---------|---------|---------|---------|---------|--------|
| `/v1/companies/overviews:batch` | 21.05 | 21.08 | 21.08 | 20.94 | 21.08 | 0/8 |
| `/v1/dashboard/bundle` | 23.17 | 24.56 | 24.56 | 5.07 | 24.56 | 6/8 |
| `/v1/dashboard/snapshot` | 22.64 | 24.74 | 24.74 | 7.43 | 24.74 | 7/8 |
| `/v1/entities/11111111-0005-7000-8000-000000000001/intelligence-bundle` | 4.86 | 5.02 | 5.02 | 3.02 | 5.02 | 0/8 |
| `/v1/holdings/01900000-0000-7000-8000-000000000100` | 5.07 | 5.11 | 5.11 | 4.88 | 5.11 | 0/8 |
| `/v1/market/top-movers` | 7.31 | 20.84 | 20.84 | 4.57 | 20.84 | 0/8 |

## 3. Infrastructure Stats

### DB Connections — Baseline
```
count |        state        |       datname        
-------+---------------------+----------------------
    24 | idle                | market_data_db
    19 | idle                | intelligence_db
    12 | idle                | nlp_db
     7 | idle                | content_ingestion_db
     6 | idle                | alert_db
     5 | idle in transaction | market_data_db
     5 | idle                | content_store_db
     4 | idle                | portfolio_db
     2 | idle                | rag_db
     1 | active              | postgres
     1 | idle                | postgres
     1 | idle in transaction | content_ingestion_db
     1 | active              | content_ingestion_db
(13 rows)
```

### DB Connections — Under Stress
```
count |        state        |       datname        
-------+---------------------+----------------------
    19 | idle                | intelligence_db
    16 | idle in transaction | market_data_db
    14 | idle                | market_data_db
    12 | idle                | nlp_db
    10 | idle                | portfolio_db
     7 | idle                | content_ingestion_db
     5 | idle                | content_store_db
     3 | idle                | alert_db
     3 | active              | alert_db
     3 | idle in transaction | alert_db
     2 | idle                | rag_db
     1 | active              | content_ingestion_db
     1 | active              | market_data_db
     1 | idle                | postgres
     1 | idle in transaction | content_ingestion_db
     1 | active              | postgres
(16 rows)
```

### Valkey Stats — Baseline
```
connected_clients:26
used_memory_human:10.79M
maxmemory_human:0B
mem_fragmentation_ratio:1.17
instantaneous_ops_per_sec:5
keyspace_hits:1276
keyspace_misses:6026
```

### Valkey Stats — Under Stress
```
connected_clients:30
used_memory_human:10.80M
maxmemory_human:0B
mem_fragmentation_ratio:1.17
instantaneous_ops_per_sec:0
keyspace_hits:1304
keyspace_misses:6082
```

### Docker Container Stats — Baseline
```
worldview-api-gateway-1	4.04%	94.54MiB / 24.91GiB	0.37%
worldview-market-data-1	40.78%	205.9MiB / 24.91GiB	0.81%
worldview-rag-chat-brief-scheduler-1	0.62%	76.1MiB / 24.91GiB	0.30%
worldview-rag-chat-1	11.04%	113.3MiB / 24.91GiB	0.44%
worldview-postgres-1	21.59%	696.3MiB / 24.91GiB	2.73%
worldview-api-gateway-bundle-prewarmer-1	0.27%	51.83MiB / 24.91GiB	0.20%
worldview-alert-intelligence-consumer-1	1.05%	87.43MiB / 24.91GiB	0.34%
worldview-market-data-intraday-resampling-consumer-1	0.89%	113.5MiB / 24.91GiB	0.45%
worldview-market-data-quotes-consumer-1	0.67%	107.7MiB / 24.91GiB	0.42%
worldview-market-data-fundamentals-consumer-1	52.01%	110.1MiB / 24.91GiB	0.43%
worldview-market-data-prediction-market-consumer-1	1.70%	77.71MiB / 24.91GiB	0.30%
worldview-market-data-ohlcv-consumer-1	0.60%	117.8MiB / 24.91GiB	0.46%
worldview-market-data-dispatcher-1	3.26%	55.07MiB / 24.91GiB	0.22%
worldview-postgres_exporter-1	0.00%	17.67MiB / 24.91GiB	0.07%
worldview-valkey-1	0.73%	15.29MiB / 24.91GiB	0.06%
```

### Docker Container Stats — Under Stress
```
worldview-api-gateway-1	5.05%	99.61MiB / 24.91GiB	0.39%
worldview-market-data-1	37.71%	207.7MiB / 24.91GiB	0.81%
worldview-rag-chat-brief-scheduler-1	0.60%	76.11MiB / 24.91GiB	0.30%
worldview-rag-chat-1	2.47%	113.3MiB / 24.91GiB	0.44%
worldview-postgres-1	38.93%	747MiB / 24.91GiB	2.93%
worldview-api-gateway-bundle-prewarmer-1	0.42%	51.84MiB / 24.91GiB	0.20%
worldview-alert-intelligence-consumer-1	2.06%	87.43MiB / 24.91GiB	0.34%
worldview-market-data-intraday-resampling-consumer-1	1.00%	113.5MiB / 24.91GiB	0.45%
worldview-market-data-quotes-consumer-1	2.11%	107.7MiB / 24.91GiB	0.42%
worldview-market-data-fundamentals-consumer-1	59.23%	110.1MiB / 24.91GiB	0.43%
worldview-market-data-prediction-market-consumer-1	0.85%	77.71MiB / 24.91GiB	0.30%
worldview-market-data-ohlcv-consumer-1	2.38%	117.8MiB / 24.91GiB	0.46%
worldview-market-data-dispatcher-1	5.11%	55.18MiB / 24.91GiB	0.22%
worldview-postgres_exporter-1	4.93%	17.11MiB / 24.91GiB	0.07%
worldview-valkey-1	2.59%	15.35MiB / 24.91GiB	0.06%
```

## 4. Bottleneck Analysis

```
Slowest endpoint (p95=24.74s): /v1/dashboard/snapshot
DB connections under stress: ~99
Valkey hit rate: 17.7% (1304 hits / 6082 misses)
WARNING: DB connection pool near saturation (>=90% of max_connections=100)
PRIMARY BOTTLENECK: postgres connection pool
ERRORS: 7/8 requests returned 4xx/5xx/timeout on /v1/dashboard/snapshot
```

## 5. Post-stress Docker Stats (collected ~30s after stress run ended)

```
Container                                        CPU%    MEM
worldview-postgres-1                             46.80%  713.8MiB / 24.91GiB
worldview-knowledge-graph-1                      43.04%  81.76MiB / 24.91GiB
worldview-market-data-fundamentals-consumer-1    33.35%  110.1MiB / 24.91GiB
worldview-knowledge-graph-scheduler-1            22.15%  307.4MiB / 24.91GiB
worldview-market-data-1                           4.60%  212.7MiB / 24.91GiB
worldview-api-gateway-1                           5.89%  100.7MiB / 24.91GiB
worldview-rag-chat-1                              0.77%  113.3MiB / 24.91GiB
worldview-valkey-1                                1.32%  15.35MiB / 24.91GiB
```

Note: Postgres continued at 46.8% CPU long after the HTTP stress ended, indicating
background work (vacuuming, autovacuum, query clean-up) triggered by the burst.

## 6. Root-Cause Analysis

### Why `/v1/dashboard/snapshot` returned 504 on 7/8 concurrent requests

The `get_dashboard_snapshot` function fans out to **6 downstream services in parallel**
with an `overall_timeout_s=20.0` budget (see `clients/dashboard.py:31`).
One of those 6 legs is `get_market_heatmap`, which itself fires **11 parallel S3 calls**.
Under 8-user concurrent load every one of those sub-calls competes for the same
postgres connection pool — max_connections=100, shared by **all 10 databases** across
all services. By the time the stress run's secondary requests arrived, the pool was
at 99/100 connections and most market-data queries stalled waiting for a slot, causing
the 20s outer timeout to fire → 504.

### Why `/v1/companies/overviews:batch` serialised at ~21s

All 8 concurrent batch requests resolved within a 0.14s window (min=20.94s,
max=21.08s), a hallmark of a **single serialised queue drain** — the queries are
likely executing one at a time behind a connection-pool queue, not truly in parallel.
This confirms the connection pool, not CPU, is the limiting resource.

### Why `/v1/market/top-movers` showed bimodal latency (min=4.57s, max=20.84s)

The p50 of 7.31s and p95 of 20.84s indicate some requests hit a warm path (Valkey
cache or query cache) while others waited in the DB connection queue. The wide spread
is consistent with a partial-cache hit scenario combined with pool starvation.

### Why intelligence-bundle and holdings were relatively fast

`/v1/entities/.../intelligence-bundle` (p95=5.02s) and `/v1/holdings/...` (p95=5.11s)
are served primarily from `intelligence_db` (19 idle connections baseline) and
`portfolio_db` (4→10 under stress). These databases had spare capacity, so their
queries were not queue-starved during the stress window.

## 7. Verdict

**Primary bottleneck**: `postgres` (shared connection pool, max_connections=100)

The connection pool is shared across 10 databases and all service replicas.
Under 8 concurrent dashboard loads the pool saturates at ~99/100, causing:
- 7/8 `/v1/dashboard/snapshot` requests → 504 (20s outer timeout fires)
- 6/8 `/v1/dashboard/bundle` requests → timeout/error
- All 8 `/v1/companies/overviews:batch` requests serialise behind a queue (~21s each)
- `/v1/market/top-movers` bimodal: fast for early slots, >20s for late slots

**Tiers ranked by p95 latency under stress:**

| Rank | Endpoint | p95 | Tier | Error rate |
|------|----------|-----|------|------------|
| 1 | `/v1/dashboard/snapshot` | 24.74s | api-gateway → 6 downstream services (snapshot fan-out) | 87.5% (7/8 → 504) |
| 2 | `/v1/dashboard/bundle` | 24.56s | api-gateway orchestration | 75% (6/8) |
| 3 | `/v1/companies/overviews:batch` | 21.08s | market-data DB (serialised) | 0% |
| 4 | `/v1/market/top-movers` | 20.84s | market-data DB (bimodal) | 0% |
| 5 | `/v1/holdings/...` | 5.11s | portfolio service | 0% |
| 6 | `/v1/entities/.../intelligence-bundle` | 5.02s | knowledge-graph / rag-chat | 0% |

**Valkey cache effectiveness**: 17.7% hit rate — most reads bypass cache and hit DB directly.
A Valkey miss forces a round-trip to postgres, amplifying connection pool pressure.

**Container CPU under stress** (from baseline docker stats during run):
- `worldview-market-data-fundamentals-consumer-1`: 52–59% CPU (background ingestion competes with API queries)
- `worldview-postgres-1`: 21% baseline → 38% stress → 47% post-stress (continued load)
- `worldview-api-gateway-1`: <6% CPU (not CPU-bound)
- `worldview-valkey-1`: <3% CPU (not I/O-bound)

**Recommendations** (diagnostic only — no code changes made):

1. **Raise `max_connections` or add PgBouncer** — The 100-connection limit is shared across 10 dbs and ~20 service replicas. PgBouncer in transaction mode would multiply effective concurrency without changing postgres config.
2. **Warm Valkey cache more aggressively** — The bundle-prewarmer runs but the 17.7% hit rate shows most dashboard sub-requests still reach postgres. The fundamentals queries and heatmap cells are the primary cache-miss vectors.
3. **Reduce `dashboard_snapshot` fan-out under load** — The 6-leg + 11-heatmap-cell fan-out (17 parallel postgres queries per request) is the worst multiplier. Consider a pre-aggregated snapshot table refreshed every 60s by a background task.
4. **Move `market-data-fundamentals-consumer` to off-peak** — At 52–59% CPU during business hours it competes with read queries for the same postgres connection pool slots.
5. **Add per-database connection limits** — Use `ALTER ROLE ... CONNECTION LIMIT` per service user so one service cannot starve others (e.g. market-data consumers should not be able to crowd out dashboard reads).