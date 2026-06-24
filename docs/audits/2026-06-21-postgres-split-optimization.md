# Postgres Split Optimization Audit — 2026-06-21

**Scope:** Read-only investigation (SELECT / EXPLAIN / pg_stat / docker inspect only). No DDL/DML, no edits, no restarts.
**Topology (target, intended):**
- `worldview-postgres-intelligence-1` → KG/intelligence workload (`intelligence_db`, `kg_db`, `nlp_db`)
- `worldview-postgres-1` → everything else (portfolio, market_data, ingestion, content_*, alert, gateway, rag, …)

**Host:** 48 GB RAM total, ~70 containers sharing it. ~32 GB MemAvailable at sample time.

---

## TL;DR (most important findings first)

1. **SPLIT IS NOT CLEAN — active split-brain on `intelligence_db`.** Two of the 27 KG/NLP containers
   are still running against the OLD box (`@postgres`) instead of `@postgres-intelligence`:
   - `worldview-knowledge-graph-scheduler-1` (172.20.0.59)
   - `worldview-knowledge-graph-1` (the KG API, 172.20.0.2)

   Their **on-disk** `docker.env` is already correct (`@postgres-intelligence`), but the **running**
   containers carry stale env (`@postgres`). They were never recreated after the repoint.
   Result: the KG API serves the graph from a *different, diverging* `intelligence_db` than the one
   the writers populate. **This is the single highest-priority fix.**

2. **`intelligence-migrations` one-shot also points at the wrong box** (`docker-compose.yml:321`,
   hardcoded `@postgres:5432/intelligence_db`). DDL/migrations land on the OLD intelligence_db, not
   the new one. Must be repointed before the next intelligence migration.

3. **The expensive KG promoter workload is running on the OLTP box.** Because the scheduler is
   mis-pointed, the `RelationEvidencePromoter` `_FETCH_SQL` and the 1.17M-cost
   `_COUNT_GATED_QUALITY_SQL` diagnostic run every 300 s against `postgres-1`/`intelligence_db` —
   16+ s per pass, the dominant CPU consumer on the busy box (44 % CPU) — while
   `postgres-intelligence-1` sits ~idle (0.2 % CPU, 0 active queries). Fixing #1 moves this load to
   the dedicated box automatically.

4. **`market_data_db.ingestion_events` is badly bloated and has NEVER been autovacuumed:**
   419 MB on disk for 17,647 live rows; n_dead_tup 48,700 (276 % dead); `last_autovacuum` NULL,
   `autovacuum_count` 0, `last_analyze` NULL. Planner stats are stale (uses ~17 k row estimate).

5. **Per-instance config is mismatched to the workloads.** `postgres-1` (the busier OLTP box) is on
   near-defaults (shared_buffers 256 MB, work_mem 4 MB), while `postgres-intelligence` (currently
   idle) is the one already tuned up (shared_buffers 2 GB, work_mem 128 MB). The tuning is on the
   wrong box relative to current load — and once #1 is fixed, both need role-appropriate values.

---

## (a) Split-correctness confirmation

### Live connections by DB (sampled `pg_stat_activity`)

**postgres-1** (OLTP — correct except KG straggler):
| datname | conns | client |
|---|---|---|
| market_data_db | 27 | market-data ✅ |
| ingestion_db | 10 | market-ingestion ✅ |
| **intelligence_db** | **7** | **knowledge-graph ❌ (should be on intelligence box)** |
| alert_db | 7 | alert ✅ |
| content_store_db | 7 | content-store ✅ |
| content_ingestion_db | 6 | content-ingestion ✅ |
| portfolio_db | 6 | portfolio ✅ |
| rag_db | 1 | rag-chat ✅ |

No `nlp_db` / `kg_db` client connections on postgres-1 — those DBs exist as empty/legacy shells but
nothing connects. OLTP services are all correctly homed here.

**postgres-intelligence-1** (KG/NLP — correct):
| datname | conns | clients |
|---|---|---|
| nlp_db | 33 | nlp-pipeline ✅ |
| intelligence_db | 22 | nlp-pipeline + knowledge-graph (most KG consumers) ✅ |

### The mis-pointed workers

Verified by `docker exec <c> env | grep DATABASE_URL` across all 27 KG/NLP containers. **25/27 correct**
(`@postgres-intelligence`). The 2 exceptions run `@postgres`:

```
worldview-knowledge-graph-scheduler-1  KNOWLEDGE_GRAPH_DATABASE_URL=...@postgres:5432/intelligence_db   ❌
worldview-knowledge-graph-1            KNOWLEDGE_GRAPH_DATABASE_URL=...@postgres:5432/intelligence_db   ❌
```

On-disk config is already fixed:
`services/knowledge-graph/configs/docker.env` →
`KNOWLEDGE_GRAPH_DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres-intelligence:5432/intelligence_db`

→ **Fix: recreate those two containers** so they pick up the corrected env_file
(`docker compose up -d --force-recreate knowledge-graph knowledge-graph-scheduler`).

### Divergence quantified (proof of split-brain, both `intelligence_db`)
| metric | OLD (postgres-1) | NEW (postgres-intelligence) |
|---|---|---|
| relations | 13,436 | 13,471 |
| canonical_entities | 25,102 | 25,161 |
| max(relations.created_at) | 2026-06-21 22:43 | **2026-06-22 05:45** |
| relation_evidence_raw last_autovacuum | 2026-06-22 04:14 | 2026-06-21 21:22 |

Both DBs are *live and diverging*. The OLD one is still receiving promoter writes (its
`relation_evidence_raw` was autovacuumed 06-22 04:14) because the scheduler writes there; the NEW one
has the freshest relations. Readers (KG API) and most writers disagree on which box is truth.

### `intelligence-migrations` (one-shot DDL owner)
`infra/compose/docker-compose.yml:321`:
```yaml
INTELLIGENCE_DB_URL: "postgresql://postgres:postgres@postgres:5432/intelligence_db"   # ❌ OLD box
```
→ **Fix: change to `@postgres-intelligence`** so future intelligence_db DDL targets the canonical DB.

---

## (b) Recommended memory / config tuning

### Current settings
| setting | postgres-1 (OLTP) | postgres-intelligence (KG/NLP) |
|---|---|---|
| shared_buffers | **256 MB** (32768×8kB) | 2 GB (262144×8kB) |
| work_mem | **4 MB** (default) | 128 MB |
| maintenance_work_mem | 64 MB | 64 MB |
| effective_cache_size | 4 GB | 4 GB |
| max_connections | 500 | 120 |
| wal_buffers | 8 MB | 16 MB |
| autovacuum_max_workers | 3 | 3 |
| autovacuum_vacuum_scale_factor | 0.2 | 0.2 |
| statement_timeout | 600 s ✅ | 600 s ✅ |
| default_statistics_target | 100 | 100 |

### Observed pressure
- **Temp spill (work_mem too low for the queries that run there):**
  - postgres-1/intelligence_db: 18 temp files / 53 MB; nlp_db: 6 / 11 MB.
  - postgres-intelligence/intelligence_db: 100 temp files / 93 MB; nlp_db: 56 / 87 MB.
  - The intelligence box spills despite work_mem=128 MB — the per-row density subqueries + sorts
    (see §c) are the cause; raising work_mem helps only marginally, the query needs fixing.
- **Cache hit ratio:** market_data_db 93.0 % (52.9 M blks read — shared_buffers too small for a
  5.8 GB DB), intelligence_db 99.3–99.9 %. The OLTP box would benefit most from more shared_buffers.
- **Live mem:** both ~1.7 GB RSS, 3.7 % of host. Plenty of headroom; current shared_buffers values are
  conservative. Host has ~32 GB available but is shared across ~70 containers — stay realistic.

### Recommended values

**postgres-1 (OLTP: market_data 5.8 GB, fundamentals 2.9 GB, high-churn upserts + outbox polling):**
| setting | recommend | rationale |
|---|---|---|
| shared_buffers | **3 GB** | currently 256 MB vs a ~9 GB working set; market_data reads 52.9 M blocks. Biggest single win. |
| effective_cache_size | **8 GB** | reflect OS cache available to this box; improves index-vs-seq planning |
| work_mem | **16 MB** | up from 4 MB; OLTP queries are small but the outbox COUNT(*)/sort and fundamentals aggregations spill. With max_connections=500 keep modest. |
| maintenance_work_mem | **512 MB** | speeds autovacuum/index builds on the 2.9 GB fundamental_metrics + bloated ingestion_events |
| max_connections | **300** (from 500) | only ~70 client conns observed; 500 reserves ~ (work_mem×500) worst-case. 300 is safe headroom and caps memory blast radius. |
| autovacuum_max_workers | **5** | 3 workers can't keep up with the fundamentals/hypertable churn (see §d) |
| autovacuum_vacuum_cost_limit | **2000** (from default 200) | let autovacuum run faster on the big fundamentals tables without throttling |
| wal_buffers | 16 MB | match the upsert write rate |

**postgres-intelligence (KG/NLP: intelligence_db 1.1 GB, nlp_db 2.0 GB, batch promoter + AGE writes):**
| setting | recommend | rationale |
|---|---|---|
| shared_buffers | **2 GB** | keep — fits the ~3 GB combined working set well; 99.8 %+ hit already |
| effective_cache_size | **6 GB** | up from 4 GB |
| work_mem | **128 MB** keep, or **192 MB** | the promoter sorts/aggregates spill (100 temp files); with only ~120 conns and few concurrent heavy queries this is affordable. Prefer fixing the query (§c) over raising further. |
| maintenance_work_mem | **512 MB** | faster vacuum/HNSW & AGE index maintenance |
| max_connections | **120** keep | matches the ~55 observed + headroom |
| autovacuum_max_workers | 3 keep | low dead-tuple pressure here |

> Net memory budget: postgres-1 3 GB + intelligence 2 GB shared_buffers = 5 GB pinned, well within the
> 48 GB host even with 70 containers. work_mem is per-sort-node, so the max_connections reduction on
> postgres-1 is what actually bounds the risk.

---

## (c) Top remaining heavy queries

### 1. `RelationEvidencePromoter._COUNT_GATED_QUALITY_SQL` (diagnostic) — cost ≈ 1,177,513
Source: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/relation_evidence_promoter.py:153`
Runs every `worker_evidence_promote_interval_s` = **300 s** (config.py:145), currently against the
WRONG box (postgres-1).

`EXPLAIN` (postgres-1/intelligence_db) — abridged:
```
Aggregate  (cost=1177513.26..1177513.27 rows=1)
  -> Nested Loop Anti Join (cost=..1177513.25)
     -> Nested Loop (cost=..1177350.66)
        -> Append over relations_p0..p7  (several SEQ SCANS: p0,p2,p3,p4,p5,p6)
        -> Memoize -> Index Scan idx_raw_evidence_triple on relation_evidence_raw
             Filter: ... ((SubPlan 1)/NULLIF((SubPlan 2),0)) < 0.1
             SubPlan 1: Aggregate over relation_evidence_raw rer2 (per row)
             SubPlan 2: Sort + Bitmap Heap Scan over relation_evidence_raw rer3 (per row)  ← density denominator
```
**Why it's slow:** the density denominator (SubPlan 2) is a correlated subquery that bitmap-scans
`relation_evidence_raw` (95 k rows) **once per candidate row**, with **no LIMIT** on the outer count.
`_FETCH_SQL` (line 79) embeds the same density subquery but is bounded by `LIMIT :batch_size`, so it is
much cheaper; the unbounded COUNT is the real cost.

**Fixes (in priority order):**
1. **Move the workload to postgres-intelligence** (fix §a #1) — removes it from the OLTP box entirely.
2. **Fold the diagnostic count into the fetch pass or lower its cadence** (already the agreed plan):
   the gated-quality metric does not need to be exact every 5 min. Run it every Nth cycle (e.g. hourly)
   or derive it from rows already scanned by `_FETCH_SQL`.
3. The 6 partitions being **seq-scanned** (p0,p2,p3,p4,p5,p6) lack the
   `(subject_entity_id, canonical_type, object_entity_id)` index that p1 and p7 have
   (`relations_pN_subject_entity_id_canonical_type_object_entity_idx`). Adding the matching index to
   the remaining partitions converts those seq scans to index-only scans. *(DDL — out of scope here,
   recommend to intelligence-migrations.)*

### 2. `RelationEvidencePromoter._FETCH_SQL` — runs every 300 s, ~16 s observed
Same source file:79. Same density subquery, but `LIMIT :batch_size` bounds it. Observed live taking
2–16 s per pass on postgres-1. Same fixes (1) and (3) above apply. The `idx_raw_evidence_triple` and
`idx_raw_evidence_object` indexes are present and used.

### 3. market_data ingest (postgres-1) — fundamentals/ohlcv upserts + outbox polling
Sampled live: `market-data` autovacuum/analyze on `balance_sheets` running 18 s (autovacuum, not a
query — see §d); `content-ingestion` and `portfolio` outbox poll queries
(`SELECT ... FROM outbox_events WHERE status=$1`, `COUNT(*) ... WHERE status=$1`) recurring sub-second.
These are healthy; the outbox COUNT(*) benefits from the work_mem bump. No missing index flagged on the
outbox path. Largest tables: `fundamental_metrics` 2.9 GB / 4.57 M rows, `_hyper_1_20_chunk` (OHLCV
TimescaleDB chunk) 938 MB / 796 k rows.

---

## (d) Vacuum / bloat issues

### CRITICAL — `market_data_db.ingestion_events` never autovacuumed
```
n_live_tup        17,647
n_dead_tup        48,700      (276 % dead)
n_mod_since_analyze 17,640    (stats never refreshed)
last_vacuum/autovacuum  NULL
autovacuum_count  0
total size        419 MB      (should be ~5–10 MB for ~18 k rows)
reloptions        (none — uses cluster default scale_factor 0.2)
```
Default trigger threshold ≈ 0.2×17,640 + 50 ≈ 3,578 dead tuples — far exceeded (48,700) yet autovacuum
has *never* fired. Two contributing causes:
1. **Stale planner stats** (n_live frozen at 17,640; physical tuple count is ~66 k) — the trigger math
   is computed off a wrong base, and the planner mis-estimates this table in every join.
2. **Vacuum-horizon pinning:** a `market-data` connection was observed **idle-in-transaction for 62 s**;
   long-lived idle-in-transaction backends hold back the global xmin and prevent dead-tuple cleanup
   cluster-wide. 4 idle-in-transaction backends present on postgres-1 at sample time.

**Recommendation (no DDL/restart in this audit):**
- Run a one-off `VACUUM (ANALYZE) ingestion_events;` to reclaim the 400+ MB and refresh stats.
- Set aggressive per-table autovacuum on it (it is high-churn / low-retention):
  `autovacuum_vacuum_scale_factor=0.05, autovacuum_vacuum_threshold=500, autovacuum_analyze_scale_factor=0.05`.
- Investigate the market-data idle-in-transaction backends (set a client-side
  `idle_in_transaction_session_timeout`, e.g. 60 s) — they are the likely root cause of the
  horizon pin and also explain why `_hyper_1_20_chunk` carries 128 k dead tuples (16 %).

### Moderate — high-churn fundamentals on postgres-1
`fundamental_metrics` already has good per-table tuning (`scale_factor=0.02, threshold=1000`,
autovacuum_count=109) — healthy at 0.7 % dead. `income_statements` (14 %), `earnings_history` (14 %),
`earnings_annual_trends` (20 %), `earnings_trends` (13 %) carry moderate dead-tuple ratios on cluster
defaults; raising `autovacuum_max_workers` to 5 and lowering their scale_factor to ~0.05 would keep them
tighter. `_hyper_1_20_chunk` 16 % is partly the horizon-pin issue above.

### postgres-intelligence — clean
Only `entity_embedding_state` (1.8 % dead) and `nlp_db.document_source_metadata` (1.7 %) above the 500
dead-tuple floor. last_autovacuum timestamps are ~8 h stale only because the box has been idle (the
promoter load is wrongly on postgres-1). Once §a is fixed, expect autovacuum activity to shift here —
the recommended maintenance_work_mem 512 MB will help it keep up.

### statement_timeout
Confirmed **600 s on both instances** (cluster-level `SHOW statement_timeout` = 600000 ms; no per-db
override needed). Backstop is in place. ✅

---

## Action checklist (ordered)

| # | Action | Box | Type |
|---|---|---|---|
| 1 | Recreate `knowledge-graph` + `knowledge-graph-scheduler` to load corrected env (@postgres-intelligence) | both | **ops, urgent** |
| 2 | Repoint `intelligence-migrations` env in docker-compose.yml:321 → `@postgres-intelligence` | infra | config |
| 3 | Reconcile the two diverged `intelligence_db` copies, then retire OLD intelligence_db on postgres-1 | data | ops |
| 4 | `VACUUM (ANALYZE) ingestion_events` + add aggressive per-table autovacuum; add idle_in_transaction_session_timeout to market-data | postgres-1 | maint |
| 5 | shared_buffers 256 MB → 3 GB, work_mem 4 → 16 MB, effective_cache_size 8 GB, max_connections 500 → 300, autovacuum_max_workers 5 | postgres-1 | config |
| 6 | effective_cache_size 6 GB, maintenance_work_mem 512 MB (shared_buffers/work_mem already fine) | postgres-intelligence | config |
| 7 | Add `(subject_entity_id, canonical_type, object_entity_id)` index to relations_p0/p2..p6; lower/fold gated-quality diagnostic cadence | intelligence_db (via intelligence-migrations) | DDL/code |

*All findings gathered read-only; no changes were applied.*
