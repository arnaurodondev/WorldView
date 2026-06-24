# Postgres Dual-Instance CPU Profile — 2026-06-21

**Type:** READ-ONLY investigation (SELECT / EXPLAIN / pg_stat only — no DDL/DML, no code edits, no restarts).
**Trigger:** Both Postgres instances reported CPU-hot — `worldview-postgres-1` (~92%) and `worldview-postgres-intelligence-1` (~91%). A DB split was deployed mid-session.
**Scope:** Identify the steady-state CPU consumers on each instance, confirm whether the split is live, and produce prioritised optimizations.

---

## TL;DR

1. **The split is NOT live — it is half-deployed and the two instances are hot for two completely different reasons.**
   - `worldview-postgres-intelligence-1` is **not wired into any committed config**. It was started from a sibling worktree (`.claude/worktrees/db-perf-consolidation/infra/compose/docker-compose.yml`). **No live worker connects to it.** Its only client is a `pg_restore` (application_name = `pg_restore`) copying data in. Its ~91–93% CPU is a **one-time `CREATE INDEX … USING hnsw` on `chunk_embeddings`** running inside that restore (27+ minutes and counting). **Transient — it will end when the restore finishes.**
   - `worldview-postgres-1` is the real, live instance: the committed compose defines **a single `postgres` service** that "serves both roles" (all 14 DBs), and every worker `DATABASE_URL` points at `@postgres:5432`. Its CPU is **bursty (seen 27%–92%)**, dominated by two real steady-state workloads (below).

2. **Top steady-state CPU consumer on `postgres-1`: the `RelationEvidencePromoterWorker` (Worker 13B), every 300 s, on `intelligence_db`.** Even after the ANALYZE mitigation it still runs **two 1.17M-cost queries** per cycle — and one of them (`_COUNT_GATED_QUALITY_SQL`) is **purely a diagnostic log metric**, not a gate. This is the single biggest avoidable burn.

3. **Second consumer on `postgres-1`: a market-data ingestion/backfill storm** — high-frequency `INSERT INTO fundamental_metrics` / `INSERT INTO ohlcv_bars` / OHLCV SELECTs on `market_data_db`, plus `ingestion_tasks` claim polling. These are well-indexed and bursty, not pathological, but they compound with #2 because `postgres-1` is badly under-provisioned (`shared_buffers=256MB`, `work_mem=4MB`).

4. **`postgres-1` is mis-tuned for a 14-DB box.** `shared_buffers=256MB`, `work_mem=4MB` vs the new intelligence instance's `2GB / 128MB`. Finishing the split (moving nlp/intelligence/kg traffic OFF `postgres-1`) AND right-sizing `postgres-1`'s buffers is the durable fix.

---

## Instance topology & split status

### Connection counts (per DB, per instance)

`postgres-1` (the live box):
```
nlp_db 26, market_data_db 22, intelligence_db 17, ingestion_db 8,
alert_db 7, content_store_db 6, content_ingestion_db 5, portfolio_db 5, rag_db 3
```

`postgres-intelligence-1` (the new box):
```
nlp_db 1 (pg_restore), postgres 1 (psql)   ← that's all
```

**Finding:** All live application connections are on `postgres-1`. `intelligence_db` on `postgres-1` is actively committing (7490 xacts, 115M `blks_hit`) — i.e. the live KG/intelligence workers connect to `postgres-1`, not the new instance.

### Why the new instance exists but isn't used

- `docker inspect worldview-postgres-intelligence-1` → `com.docker.compose.service = postgres-intelligence`, config file =
  `…/.claude/worktrees/db-perf-consolidation/infra/compose/docker-compose.yml` (a **sibling worktree**, not the working tree).
- Committed compose (`infra/compose/docker-compose.yml`) defines a **single** `postgres` service (line ~121 comment: "this single postgres container … serves both roles") and `INTELLIGENCE_DB_URL: postgresql://…@postgres:5432/intelligence_db`. `grep` for `postgres-intelligence` across all `*.yml/*.env` in the working tree returns **nothing**.
- The only backend on the new instance is `application_name = pg_restore` (pid 1206), `backend_start 21:36`, running the HNSW build.

**Conclusion:** The split is **in-progress data migration**, not a cutover. Both boxes being hot is expected for this transient phase (old box still does all the work; new box is doing a CPU-heavy index build). It is **not** a case of workers split across both — it's old-box-does-everything + new-box-restoring.

---

## Instance A — `worldview-postgres-1` (LIVE)

`docker stats` over the session: **27% – 92% (bursty)**. Mem 1.4 GiB / 46.7 GiB.

### Active-query tally (45 samples across two passes)

| Rank | DB | Query (truncated) | Source |
|---|---|---|---|
| 1 | `intelligence_db` | `SELECT count(*) FROM relation_evidence_raw rer WHERE rer.en…` | `relation_evidence_promoter.py` (`_COUNT_GATED_QUALITY_SQL` / `_FETCH_SQL`) |
| 2 | `market_data_db` | `INSERT INTO fundamental_metrics (…)` | market-data fundamentals consumer |
| 3 | `intelligence_db` | `SELECT rer.raw_id, r.relation_id, rer.source_document_id …` | `relation_evidence_promoter.py` (`_FETCH_SQL`) |
| 4 | `market_data_db` | `INSERT INTO ohlcv_bars (…)` / OHLCV SELECT | market-data OHLCV ingest/backfill |
| 5 | `ingestion_db` | `SELECT ingestion_tasks.id FROM ingestion_tasks WHERE …` | market-ingestion task-claim poller |
| 6 | `intelligence_db` | `INSERT INTO entity_embedding_state (…)` | KG embedding-state worker |
| 7 | `nlp_db` | `REFRESH MATERIALIZED VIEW CONCURRENTLY document_source_…` | `article_relevance_scoring_worker.py` |
| 8 | `content_ingestion_db` | `SELECT … FROM dead_letter_queue / content_ingestion_tasks` | content-ingestion poller |

### CPU consumer #1 — RelationEvidencePromoterWorker (Worker 13B)

**Source:** `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/relation_evidence_promoter.py`
**Cadence:** every `worker_evidence_promote_interval_s` (**default 300 s**).
**Per cycle it issues 4 queries** (`_FETCH_SQL`, `_COUNT_PROVISIONAL_SQL`, `_COUNT_NO_MATCH_SQL`, `_COUNT_GATED_QUALITY_SQL`).

Two of them are heavy because both embed the same **per-row correlated density subquery** with an OR-join that cannot use a single btree:

```sql
(SELECT COUNT(DISTINCT rer3.source_document_id)
 FROM relation_evidence_raw rer3
 WHERE rer3.subject_entity_id IN (rer.subject_entity_id, rer.object_entity_id)
    OR rer3.object_entity_id  IN (rer.subject_entity_id, rer.object_entity_id))
```

**EXPLAIN (no ANALYZE) of `_COUNT_GATED_QUALITY_SQL`** (intelligence_db):

```
Aggregate  (cost=1175055.20..1175055.21 rows=1)
  -> Nested Loop Anti Join  (cost=0.43..1175055.20)
       -> Nested Loop  (cost=0.43..1174972.43)
            -> Append (relations_p0..p7 seq scans, 13433 rows)
            -> Memoize (cache key: subject,object,canonical_type)
                 -> Index Scan idx_raw_evidence_triple on relation_evidence_raw rer
                      Filter: ((SubPlan 1)/NULLIF((SubPlan 2),0)) < 0.05
                      SubPlan 2:  Bitmap Heap Scan + Sort on relation_evidence_raw rer3
                                  Recheck: subject = ANY(...) OR object = ANY(...)
```

- **Total cost ≈ 1.17M** — this is exactly the "mitigated → 1.17M" figure from the prior session. The ANALYZE helped, but **1.17M cost every 300 s is still the dominant recurring scan on this box.**
- Row counts: `relation_evidence_raw` ≈ **95,059**, `relations` ≈ **13,433**. `relations` has the unique triple index (`uidx_relations_triple`); the per-partition seq scans are the planner correctly driving from the small side — the cost lives in `SubPlan 2` (the OR density scan + Sort) executed per candidate row.

**Key waste:** `_COUNT_GATED_QUALITY_SQL` is **diagnostic only** — the code comment says "Used for the gated_quality diagnostic log metric and Prometheus counter"; it does NOT gate promotion (the real gate is inside `_FETCH_SQL`). So a 1.17M-cost query runs every 5 minutes **purely to produce one log line + a Prometheus counter**.

### CPU consumer #2 — market-data ingestion/backfill (`market_data_db`)

High-frequency `INSERT INTO fundamental_metrics`, `INSERT INTO ohlcv_bars`, `INSERT INTO cash_flow_statements / earnings_annual_trends`, and OHLCV range SELECTs. These are well-indexed:
- `ohlcv_bars`: 6 indexes incl. pk `(instrument_id,timeframe,bar_date)` and partial daily indexes.
- `fundamental_metrics`: 5 indexes incl. unique `(instrument,date,metric)`.

This is a **bursty backfill**, not a missing-index problem. It is healthy in isolation but competes with consumer #1 for CPU on an under-provisioned box.

### Config (mis-tuned for 14 DBs)

| setting | postgres-1 | intelligence-1 |
|---|---|---|
| shared_buffers | **256 MB** | 2 GB |
| work_mem | **4 MB** | 128 MB |
| maintenance_work_mem | 64 MB | 64 MB |
| max_connections | 500 | 120 |
| effective_cache_size | 4 GB | 4 GB |
| statement_timeout | 600 s | 600 s |

Cache hit ratios are still high (intelligence_db 99.6%, market_data_db 93.9%, content_ingestion 99.5%), and `temp_files` on postgres-1 is low (intelligence_db 6 files / 18 MB) — so the bottleneck is **CPU on the promoter's repeated 1.17M scan**, not IO or temp spill. But `work_mem=4MB` is dangerously small for a box that ever runs the promoter/AGE/sort workloads; the only reason it isn't spilling more is that those workloads moved (or are moving) to the new box.

---

## Instance B — `worldview-postgres-intelligence-1` (NEW, migrating)

`docker stats`: **87–93%**. Mem 2.1 GiB.

### Sole active query (all 5 samples identical)

```
CREATE INDEX idx_chunk_emb_hnsw ON public.chunk_embeddings
  USING hnsw (embedding public.vector_cosine_ops)
  WHERE (embedding_status = 'ready');
```
- pid 1206, `application_name = pg_restore`, running **27+ minutes**.
- `pg_stat_progress_create_index`: phase **"building index: loading tuples"**, ~48,356 / ~52,228 tuples (≈ 92%).
- Source of the index DDL: `services/nlp-pipeline/alembic/versions/0001_create_nlp_schema.py` + `…/infrastructure/nlp_db/repositories/chunk_search.py`.

**Finding:** HNSW index builds are single-threaded and **CPU-bound by design**. This is a **one-time data-migration cost**, not a steady-state problem. It will drop to near-idle once the restore completes. There is currently **no live query load** on this instance to optimise.

---

## Prioritised optimizations

### P0 — Cut the promoter's recurring 1.17M-cost burn (biggest, lowest-risk win)

1. **Stop running `_COUNT_GATED_QUALITY_SQL` every cycle.** It is diagnostic-only. Options (any one):
   - Run it on a **much slower cadence** (e.g. every 1 h, or every Nth promoter cycle) instead of every 300 s.
   - Compute `gated_quality` as a **cheap derived count** (rows fetched-eligible minus promoted is already known per cycle) rather than re-deriving it with a full O(N) density rescan.
   - Gate it behind a debug/ops flag (off by default).
   - **Expected impact:** removes one full 1.17M-cost scan every 5 min — roughly halves the promoter's CPU footprint immediately.

2. **Rewrite the density denominator to avoid the per-row OR-scan.** The `subject IN (a,b) OR object IN (a,b)` form forces a BitmapOr + Sort per candidate row (`SubPlan 2`). Precompute per-entity distinct-doc counts **once per cycle** into a CTE / temp result keyed by entity, then join — turning N per-row scans into one pass. Same result, drops cost from ~1.17M to roughly O(N).
   - Targets: `_FETCH_SQL` (lines 79–127) and `_COUNT_GATED_QUALITY_SQL` (lines 153–192) in `relation_evidence_promoter.py`.

3. **Consider lengthening `worker_evidence_promote_interval_s`** from 300 s if a 5-minute promotion latency is not required — directly proportional CPU reduction.

### P1 — Finish the split cleanly (the actual intended fix)

4. **Cut nlp_db / intelligence_db / kg_db traffic over to `postgres-intelligence-1` once the restore completes**, and remove those DBs from `postgres-1`. The split is only valuable when the live workers' `DATABASE_URL`s point at the new instance:
   - `INTELLIGENCE_DB_URL`, the KG service DB URL, and `NLP_PIPELINE_*DATABASE_URL` must move to `@postgres-intelligence:5432`.
   - This must be done in the **committed** `infra/compose/docker-compose.yml` (today the new instance exists only in a worktree compose, so a normal `make dev` / redeploy would not recreate it — a deployment hazard).
   - After cutover, `postgres-1` keeps portfolio/market_data/ingestion/content/alert/rag/gateway; `postgres-intelligence-1` owns the 3 intelligence DBs. Each box then has headroom.

5. **Wait for the HNSW build to finish before cutover** (currently ~92%); do not point live readers at the new instance until the index is `VALID`.

### P2 — Right-size `postgres-1`

6. **Raise `shared_buffers` and `work_mem` on `postgres-1`.** 256 MB / 4 MB is far too small for a box hosting market_data + ingestion + content + (until cutover) the intelligence DBs.
   - Suggested starting point on a 46 GB host: `shared_buffers=4–8GB`, `work_mem=32–64MB`, `effective_cache_size=24GB`, `maintenance_work_mem=512MB` (helps future index builds/VACUUM).
   - `max_connections=500` is high; with PgBouncer or fewer pool sizes it could come down, freeing per-connection work_mem budget.

### P3 — Housekeeping

7. **The market-data backfill is healthy** (well-indexed, high cache hit, no temp spill). No index work needed; just ensure it isn't running concurrently with a heavy promoter cycle on the same under-provisioned box (P0+P1 resolve this).
8. **`REFRESH MATERIALIZED VIEW CONCURRENTLY document_source_…`** (nlp_db, `article_relevance_scoring_worker.py`) appears occasionally; CONCURRENTLY is correct but cost scales with the view — confirm its cadence is not sub-minute after cutover.

---

## Evidence index (queries run, all read-only)

- `pg_stat_activity` sampled ~45× across both instances (state='active', client backends).
- `pg_stat_database` (temp_files, temp_bytes, blks_hit/read) both instances.
- `pg_stat_progress_create_index` on intelligence-1.
- `EXPLAIN` (no ANALYZE) of `_COUNT_GATED_QUALITY_SQL` → cost 1,175,055.
- `pg_indexes` on `relation_evidence_raw`, `relations*`, `ohlcv_bars`, `fundamental_metrics`.
- `docker inspect` / `docker stats` on both containers.
- `pg_settings` (buffers/work_mem/connections/timeout) both.
- Codebase grep mapped every hot query to its source worker/repository.

No mutations were issued. Queries used `LIMIT`, `reltuples` (no full scans of `relations`/`relation_evidence_raw`), and `EXPLAIN` without ANALYZE per the OOM caution.
