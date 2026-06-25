# Postgres QA — OLTP/OLAP Split Verification (Post-Redeploy)

**Date:** 2026-06-22
**Scope:** Read-only QA on both Postgres instances (SELECT / pg_stat / pg_locks / EXPLAIN-no-ANALYZE only — no DDL/DML).
**Trigger:** Redeploy landed the OLTP/OLAP split. Verify the split is clean and find data/query problems.
**Method:** `docker exec worldview-postgres-1` (OLTP) and `worldview-postgres-intelligence-1` (OLAP). Both containers up ~6 min at audit start (post-redeploy). Credentials redacted.

---

## Verdict (Executive Summary)

- **Split-brain: RESOLVED for connections.** Every KG/NLP service (knowledge-graph, knowledge-graph-scheduler, nlp-pipeline) connects ONLY to `worldview-postgres-intelligence-1`. ZERO connections to the OLAP databases (`intelligence_db`/`kg_db`/`nlp_db`) remain on `worldview-postgres-1`. The 2 previously mis-pointed KG containers are now correct. **No service is on the wrong box.**
- **Caveat:** the OLAP databases (`intelligence_db`, `kg_db`, `nlp_db`, `intelligence_test_db`) physically STILL EXIST on the OLTP box (`postgres-1`) as orphaned leftovers. No traffic, but a config regression on any KG/NLP service would silently reconnect there and write to stale data → split-brain returns. Should be dropped/renamed.
- **Data freshness: ALL pipelines fresh.** Market data (ohlcv 10:31, quotes 10:32), NLP (chunks/mentions 10:32), KG (relations + relation_evidence_raw 10:32) all writing as of today. Portfolio sane.
- **Active problem (NOT caused by split):** a persistent **lock convoy on `nlp_db→intelligence_db.provisional_entity_queue`** under 50 concurrent nlp-pipeline backends is causing statement-timeout cancellations and feeding a **2,528-row, 100%-unresolved dead-letter queue** (`content.article.stored.v1`, all `message_processing_timeout after 900s`). Articles are silently failing enrichment.
- No deadlocks, no OOM, no FATAL (other than benign startup "not yet accepting connections" at 10:25). intelligence_db alembic at **0062** as expected.

---

## Ranked Issue List

| # | Instance / DB | Issue | Evidence | Severity |
|---|---------------|-------|----------|----------|
| 1 | postgres-intelligence / nlp_db | **Dead-letter queue 100% unresolved, growing.** 2,528 rows, ALL `topic=content.article.stored.v1`, `status=failed`, `resolved_at=NULL`. Recent errors all `message_processing_timeout after 900s`. Spans 2026-05-10 → 2026-06-22 09:45 (10 in last hour). Articles are failing NLP enrichment and never reprocessed = silent data loss. | `SELECT topic,status,count(*) … GROUP BY` → single row 2528 failed; `error_detail` = `message_processing_timeout after 900s` ×109 in 6h; `count(*) FILTER (status!='resolved')` = 2528 | **CRITICAL** |
| 2 | postgres-intelligence / intelligence_db | **Persistent lock convoy on `provisional_entity_queue`.** 5–6 nlp-pipeline INSERTs blocked on `tuple` ExclusiveLock, waiting 40–51s, root blocker is an **idle-in-transaction backend (ClientRead)** holding the tuple lock (pid rotates, e.g. 381 RELEASE SAVEPOINT, xact_age 48s). Re-checked ~2 min later: still 5 blocked → ongoing, not transient. Postgres logs show 6 `canceling statement due to statement timeout` in a 90s window. Likely the upstream of issue #1. Cause: unique index `(normalized_surface, mention_class)` → `ON CONFLICT` inserts serialize on the same tuple; 50 concurrent nlp backends amplify it; an idle-in-tx holder pins the convoy. | `pg_blocking_pids` → 6 blocked PIDs; `pg_locks` on `provisional_entity_queue` = 3 ungranted `tuple ExclusiveLock`; `pg_stat_activity` pid 381 `idle in transaction / ClientRead`; logs `ERROR: canceling statement due to statement timeout` ×6 | **HIGH** |
| 3 | postgres-1 (OLTP) | **Orphaned OLAP databases on the OLTP box.** `intelligence_db`, `kg_db`, `nlp_db`, `intelligence_test_db` still physically present on postgres-1 with 0 connections. Stale-data split-brain hazard if any KG/NLP service env regresses to the old host. Should be dropped (or renamed to `*_DEPRECATED`) after confirming no recovery dependency. | `SELECT datname FROM pg_database` on postgres-1 lists all four; `pg_stat_activity WHERE datname IN (…)` = 0 rows | **MEDIUM** |
| 4 | postgres-intelligence / intelligence_db | **`kg_db` has zero connections** (KG services use `intelligence_db`, where AGE graph + relations live). Not a bug — AGE graph is colocated in intelligence_db by design — but `kg_db` is effectively an empty/unused database on the OLAP box; confirm it is intentional and not a half-migrated artifact. | activity table: `kg_db` absent; `SELECT count FROM pg_stat_activity WHERE datname='kg_db'` = 0 | **LOW** |
| 5 | postgres-intelligence / nlp_db | **Leftover cleanup table `cleanup_20260621_xai_mentions`** (~67 rows) from the 2026-06-21 xAI mention cleanup still present in `nlp_db` public schema. Cosmetic clutter; drop when no longer needed. | `pg_class` lists `cleanup_20260621_xai_mentions` reltuples=67 | **LOW** |

---

## Detailed Evidence

### 1. Split-brain (RESOLVED)

`postgres-1` (OLTP) connections by db — all correct, NO OLAP dbs:
```
market_data_db   9   (market-data)
ingestion_db     6   (market-ingestion)
content_ingestion_db 5 (content-ingestion)
content_store_db 4   (content-store)
portfolio_db     4   (portfolio)
alert_db         3   (alert)
```
`SELECT … WHERE datname IN ('intelligence_db','kg_db','nlp_db')` on postgres-1 → **0 rows.**

`postgres-intelligence` (OLAP) connections by db — all KG/NLP, correct box:
```
intelligence_db  33  (nlp-pipeline + knowledge-graph)
nlp_db           26  (nlp-pipeline)
kg_db            0
```
`application_name` confirms only `nlp-pipeline` and `knowledge-graph` clients on the intelligence box. No portfolio/market/gateway/alert clients leaked over.

### 2. Connection health
- postgres-1: 29 idle, 2 active, 0 idle-in-tx, 0 long-running >30s, 0 blocked. Healthy.
- postgres-intelligence: 48 idle, 8 active, **5 idle-in-transaction**, **6 blocked** (issue #2). `statement_timeout` (global) = 10min; the 900s DLQ timeouts match this ceiling.

### 3. Data sanity (cheap — pg_class estimates / MAX, no full scans)
| db | signal | value |
|----|--------|-------|
| intelligence_db | relations max(updated_at)/max(created_at) | 2026-06-22 10:32:19 |
| intelligence_db | relations est rows | ~13,433 |
| intelligence_db | relation_evidence_raw max(extracted_at) | 2026-06-22 10:32:27 |
| intelligence_db | relation_evidence_raw est rows | ~95,200 |
| intelligence_db | provisional_entity_queue rows | 35,034 |
| intelligence_db | alembic_version | **0062** ✓ |
| nlp_db | chunks max(created_at) | 2026-06-22 10:32:32 |
| nlp_db | entity_mentions max(created_at) | 2026-06-22 10:32:24 |
| nlp_db | alembic_version | 0022 |
| market_data_db | ohlcv_bars max(bar_date) | 2026-06-22 10:31:00 |
| market_data_db | quotes max(timestamp)/max(updated_at) | 2026-06-22 10:31 / 10:32 |
| portfolio_db | portfolios / holdings | 2 / 10 |
| portfolio_db | last transaction | 2026-06-13 04:31 (no recent trades — expected, seed data) |
| portfolio_db | alembic_version | 0027 |

Note: `relations` has no `promoted_at` column (the prompt's expected column name); freshness verified via `updated_at`/`created_at` instead.

### 4. Errors (docker logs --since 15m)
- postgres-1: only `FATAL: the database system is not yet accepting connections` ×3 at 10:25 (boot window — benign).
- postgres-intelligence: 6× `canceling statement due to statement timeout` (10:31–10:32, the convoy victims). No deadlock / OOM / PANIC. (The `promoted_at`/`error_type` "does not exist" entries are this audit's own probe queries, not application errors.)

### 5. Locks
Root blocker is idle-in-transaction (ClientRead) holding a granted `tuple ExclusiveLock` on `provisional_entity_queue`; 3 INSERTs hold ungranted `tuple ExclusiveLock` requests behind it. RowExclusiveLock on the relation is shared fine; contention is at the **tuple** level (unique-key conflict serialization), consistent with `ON CONFLICT (normalized_surface, mention_class)` under 50 concurrent inserters.

---

## Recommendations (no action taken — read-only audit)

1. **Issue #1/#2 (same root):** reduce nlp-pipeline insert concurrency on `provisional_entity_queue`, OR batch-dedup mentions before insert, OR switch to `INSERT … ON CONFLICT DO NOTHING` with a short `lock_timeout` + app-side retry-with-backoff so a single idle-in-tx holder cannot pin a 900s convoy. Investigate why a backend goes idle-in-transaction mid-batch (ClientRead = app stalled holding the tx open — candidate for the xmin-pin / savepoint pattern). Then drain & reprocess the 2,528 DLQ entries.
2. **Issue #3:** after a backup-confirmed grace period, `DROP DATABASE intelligence_db/kg_db/nlp_db/intelligence_test_db` on postgres-1 to eliminate the split-brain regression hazard.
3. **Issue #4/#5:** confirm `kg_db` is intentionally empty on OLAP; drop the `cleanup_20260621_xai_mentions` scratch table.
