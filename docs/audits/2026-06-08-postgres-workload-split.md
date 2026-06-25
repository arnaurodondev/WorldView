# Postgres OLTP/OLAP Workload Split

**Date:** 2026-06-08 (revised 2026-06-21)
**Author:** infra split investigation
**Status:** Designed + implemented in worktree; data-migration / gitops / restart steps pending human confirmation.

## 1. Problem

A single Postgres container (`worldview-postgres-1`, built from `infra/postgres/Dockerfile`,
timescaledb-pg16 + pgvector + Apache AGE) serves **all** application databases. Heavy
analytical (OLAP) queries from the knowledge-graph (S7) and nlp-pipeline (S6) services —
multi-hour AGE relation scans, multi-minute FTS — saturate shared resources (CPU, I/O,
shared_buffers, autovacuum) and starve latency-sensitive UI (OLTP) queries from portfolio,
market-data, gateway, and alert. A live investigation proved this is the root cause of UI
timeouts.

The fix: run **two** Postgres instances and partition databases by workload so the OLAP
group can no longer starve the OLTP group.

## 2. Current wiring (service → database → env var)

All runtime DB URLs live in each service's `configs/docker.env` (gitignored; the committed
`*.env.example` files are the structural source of truth). Verified against the live stack.

| Service (container) | Database(s) | Env var(s) | Workload |
|---|---|---|---|
| portfolio (+5 workers) | portfolio_db | `PORTFOLIO_DATABASE_URL` | OLTP |
| market-ingestion | ingestion_db | `MARKET_INGESTION_DATABASE_URL` (+ `_READ`) | OLTP |
| market-data | market_data_db | `MARKET_DATA_DATABASE_URL` (host alias `timescaledb`), `MARKET_DATA_READ_REPLICA_URL` | OLTP (TimescaleDB) |
| api-gateway | gateway_db | `API_GATEWAY_DATABASE_URL` | OLTP |
| alert | alert_db | `ALERT_DATABASE_URL` | OLTP |
| content-ingestion | content_ingestion_db | `CONTENT_INGESTION_DB_URL` | OLTP |
| content-store | content_store_db | `CONTENT_STORE_DATABASE_URL` | OLTP |
| rag-chat | rag_db | `RAG_CHAT_RAG_DB_URL` (+ optional `_READ`) | OLTP |
| **nlp-pipeline** (S6) | **nlp_db** + **intelligence_db** | `NLP_PIPELINE_DATABASE_URL`, `NLP_PIPELINE_INTELLIGENCE_DATABASE_URL` | **OLAP** |
| **knowledge-graph** (S7) | **intelligence_db** | `KNOWLEDGE_GRAPH_DATABASE_URL` (+ optional `_READ`) | **OLAP** |
| **intelligence-migrations** | **intelligence_db** | `INTELLIGENCE_DB_URL` (inline in compose, line ~235) | **OLAP (DDL owner)** |

### Key facts discovered (do not re-derive)

- **AGE lives in `intelligence_db`, not `kg_db`.** The KG service runs `LOAD 'age'` /
  `cypher('worldview_graph', …)` on its `KNOWLEDGE_GRAPH_DATABASE_URL` connection, which
  points at `intelligence_db`. Live check: `intelligence_db` has the `age` extension and the
  `worldview_graph` graph. `intelligence_db` = 1.35 GB.
- **`kg_db` is an orphaned stub.** Live size 8 MB. It holds only the unused `market_kg`
  graph created by `init-databases.sh` and the planned `ticker_aliases` table (intelligence-migrations
  alembic 0040). No service connects to `kg_db` via any env var today.
- **`nlp_db` = 2.15 GB** — the largest OLAP database (embeddings, sections, chunks).
- **No cross-group DB joins.** R9 forbids cross-service DB access; confirmed no OLTP service
  reads intelligence_db/nlp_db and no OLAP service reads an OLTP db. nlp-pipeline reads both
  nlp_db and intelligence_db — but both are in the OLAP group, so they stay co-located.
- **`market_data_db` stays on the existing instance** via the `timescaledb` network alias; it
  is NOT moved (despite high connection count it is OLTP and TimescaleDB-bound).

## 3. Partition

**NEW instance `postgres-intelligence` (port 5433)** — OLAP:
- `intelligence_db` (+ `intelligence_test_db`)
- `nlp_db`
- `kg_db` (moved with the group for cohesion; it is the KG service's logical home and where
  `ticker_aliases` belongs)

**EXISTING instance `postgres` (port 5432)** — OLTP (unchanged set, minus the three moved):
- `portfolio_db`, `market_data_db`, `gateway_db`, `alert_db`,
  `content_ingestion_db`, `content_store_db`, `ingestion_db`, `rag_db`

Cross-group risk: **none** (validated above).

## 4. New compose service

`postgres-intelligence` mirrors the existing `postgres` service exactly (same Dockerfile —
needs AGE + pgvector + pg_trgm), with:
- own volume `postgres_intelligence_data`
- host port `127.0.0.1:5433:5432` (localhost-only, SEC-007)
- its own init dir `../postgres/init-intelligence` that creates **only** the OLAP dbs +
  extensions (AGE in intelligence_db, pgvector in nlp_db + intelligence_db, pg_trgm in
  intelligence_db, AGE graph in kg_db).
- own healthcheck; OLAP services and intelligence-migrations gain a
  `postgres-intelligence: service_healthy` dependency.

### Resource implications

The new instance needs its own tuning. Recommended (documented; applied via gitops / compose
`command` or a `postgresql.conf` override, not in this worktree's scope to hard-pin):
- `shared_buffers` ≈ 25% of the instance's allotted RAM (e.g. 2 GB if 8 GB allotted)
- `work_mem` higher than OLTP (AGE/FTS sorts): 64–128 MB
- `max_connections` ≈ 100 (KG+NLP pools: KG read pool 20 + overflow 30, NLP write/intel pools)
- dedicate CPU via compose `cpus:` / `mem_limit:` so OLAP autovacuum + scans can't burst into
  the OLTP instance's cores.

## 5. Env-var changes (per service)

Only the **host** changes: `postgres:5432` → `postgres-intelligence:5432` for OLAP URLs.

| File | Var | New value |
|---|---|---|
| `services/knowledge-graph/configs/docker.env.example` | `KNOWLEDGE_GRAPH_DATABASE_URL` | `…@postgres-intelligence:5432/intelligence_db` |
| `services/nlp-pipeline/configs/docker.env.example` | `NLP_PIPELINE_DATABASE_URL` | `…@postgres-intelligence:5432/nlp_db` |
| `services/nlp-pipeline/configs/docker.env.example` | `NLP_PIPELINE_INTELLIGENCE_DATABASE_URL` | `…@postgres-intelligence:5432/intelligence_db` |
| `infra/compose/docker-compose.yml` (inline) | `INTELLIGENCE_DB_URL` | `…@postgres-intelligence:5432/intelligence_db` |

The real `docker.env` files and the gitops `env/dev` config carry the same change (see §8).

## 6. Init / migration story for the new instance

- New init dir `infra/postgres/init-intelligence/` with two scripts (mirrors existing pattern):
  - `init-databases.sh` → creates `intelligence_db`, `nlp_db`, `kg_db` + extensions + AGE graphs.
  - `init-test-databases.sh` → creates `intelligence_test_db` (+ nlp/intelligence pgvector) for
    any test stack that targets this instance.
- `intelligence-migrations` (owns `intelligence_db` DDL, incl. AGE `worldview_graph` setup +
  ticker_aliases in kg_db scope) runs against `postgres-intelligence`.
- nlp-pipeline alembic (`nlp-pipeline-migrate`) runs against `postgres-intelligence` for `nlp_db`.
- The old instance's `init-databases.sh` no longer creates the three moved dbs (idempotent:
  `WHERE NOT EXISTS` guards remain, so existing volumes are unaffected; only fresh `up -v`
  bring-ups stop creating them on the old instance).

## 7. Data migration for EXISTING local data

The three OLAP dbs already hold ~3.5 GB locally. Fresh init does NOT copy data, so a one-time
dump/restore is required (human-confirmed step — see §9). AGE graphs require `--no-acl`-safe
dumps; `pg_dump` captures the `ag_catalog` tables since AGE stores graph data as regular
tables/labels in the database.

## 8. Rollback

- Revert env URLs back to `postgres:5432` and remove the `postgres-intelligence` service +
  its volume. The old instance still contains the original data (the dump/restore is additive;
  the old dbs are not dropped by this change). Rollback is therefore non-destructive as long as
  the old OLAP dbs are not manually dropped.

## 9. Remaining human-confirmation steps (ready to execute)

1. **Data migration** (run once, after new instance is up and dbs created):
   ```bash
   for DB in intelligence_db nlp_db kg_db; do
     docker exec worldview-postgres-1 pg_dump -U postgres -Fc "$DB" \
       > "/tmp/${DB}.dump"
     docker exec -i worldview-postgres-intelligence-1 \
       pg_restore -U postgres -d "$DB" --no-owner --clean --if-exists < "/tmp/${DB}.dump"
   done
   ```
   (Run the AGE graph load-order check after restore: `SELECT name FROM ag_catalog.ag_graph;`)
2. **gitops `env/dev` diff** — apply `docs/audits/postgres-split-gitops.diff` to the
   `worldview-gitops` repo `env/dev` (source of truth), then sync.
3. **Rebuild + restart** the OLAP services so they pick up the new host:
   ```bash
   docker compose -f infra/compose/docker-compose.yml up -d postgres-intelligence
   # then recreate OLAP services to load new docker.env host:
   docker compose -f infra/compose/docker-compose.yml up -d --force-recreate \
     intelligence-migrations nlp-pipeline knowledge-graph \
     nlp-pipeline-dispatcher nlp-pipeline-article-consumer  # + remaining KG/NLP workers
   ```

## 10. gitops `env/dev` diff

See `docs/audits/postgres-split-gitops.diff` (prepared in this worktree). It changes the host
in `KNOWLEDGE_GRAPH_DATABASE_URL`, `NLP_PIPELINE_DATABASE_URL`,
`NLP_PIPELINE_INTELLIGENCE_DATABASE_URL`, and `INTELLIGENCE_DB_URL` from `postgres` to
`postgres-intelligence`, and adds the new instance's resource settings.
