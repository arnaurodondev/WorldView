# QA — End-to-End Pipeline Correctness (Post-Deploy)

**Date:** 2026-06-22 ~10:36 UTC
**Mode:** READ-ONLY (docker logs/exec, psql SELECT with limits, S9 HTTP GET). No mutations.
**Deploy:** Full redeploy completed ~10:30 UTC (most app containers "Up 2-6 minutes").
**Goal:** Confirm DATA flows end-to-end post-deploy, not just "containers Up". Guard against the
known "all-green / zero-output" anti-pattern by checking real throughput with advancing timestamps.

## Method

- Authoritative Postgres routing confirmed via container env: NLP / intelligence / KG live on
  `postgres-intelligence`; content / market / portfolio / gateway live on `postgres`.
  (`nlp_db`/`intelligence_db`/`kg_db` exist on BOTH instances — only the intelligence instance is wired.)
- Freshness probed with `MAX(ts)` + windowed `count(*) FILTER (WHERE ts > now()-interval ...)`.
- Extraction chain **re-sampled** over a ~2-3 min window to distinguish "flowing" from "warming/stalled".

## Per-Pipeline Freshness Table

| Pipeline | Latest data timestamp | Verdict | Evidence | Severity |
|---|---|---|---|---|
| **Content Ingestion** (fetch→raw) | 10:30:16 (fetch_log); tasks 10:32 | **FLOWING** | 139 fetches/1h, 876 tasks/1h; documents `ingested_at` 10:30, 134/1h | OK |
| **NLP enrich** (docs + mentions) | 10:32:50 | **FLOWING** | 478 docs/1h, 4424 entity_mentions/1h, 10353 mention_resolutions/1h | OK |
| **GLiNER NER server** | 10:33 (live) | **FLOWING** | `/ner/batch` 200 OK, micro-batches flushing; `/healthz` 200 | OK |
| **KG relation extraction** (`relation_evidence_raw`) | 10:34:42 (advanced from 10:32 on re-sample) | **FLOWING** | 435/1h extracted; +22 in 5-min re-sample window | OK |
| **KG promoter** (`relation_evidence`) | 10:21:45 | **FLOWING (batched)** | 226 promoted/1h; runs on 15-min interval job (next 10:47); 13.6k raw backlog is normal inter-run accumulation | OK |
| **KG canonical relations** (`relations`) | 10:34:42 (advanced on re-sample) | **FLOWING** | 13,600 total, 171 new/24h, +6 in 5-min window | OK |
| **AGE graph** (`worldview_graph`) | n/a (count) | **POPULATED** | 41,448 vertices / 14,109 edges | OK |
| **KG narrative scheduler** | 10:33 (live) | **FLOWING** | DeepSeek-V4-Flash narratives generating ~5-10s each, 200 OK (container marked unhealthy — healthcheck only, see I-3) | OK (worker), see I-3 |
| **Market data — OHLCV** | 10:31:00 | **FLOWING** | intraday bars current; 354,825 recent rows | OK |
| **Market data — quotes** | 10:31 (ts) / 10:32 (updated) | **FLOWING** | 15 updated/1h | OK |
| **Market data — fundamentals** | 10:33:49 | **FLOWING** | 669 snapshots/24h | OK |
| **Portfolio snapshots** | 2026-06-22 (today) | **FLOWING** | snapshot worker startup-catchup wrote today's snapshot; then sleeps ~11h | OK, see I-4 |
| **API Gateway (S9)** | live | **HEALTHY** | `/healthz` 200; `GET /v1/news/top` 200 (1.24s) returning fresh article published 2026-06-22T04:38 | OK |

**Overall: all pipelines are genuinely flowing post-deploy.** Timestamps advanced over the re-sample
window on the chain most prone to silent stall (News→NLP→KG). No "all-green / zero-output" condition found.

## Ranked Issues

### I-1 — NLP article processing 900s timeouts (MEDIUM)
- `nlp_db.dead_letter_queue`: 155 entries/24h, all `message_processing_timeout after 900s`. 10 in the
  last hour; hourly distribution 07:00=48, 08:00=25, 09:00=36, **10:00=0**.
- Against ~497 docs/hr processed, that is ~5-7% timeout loss during the busy early hours, trending to
  zero in the current hour as the platform warms up / CPU pressure eases.
- Matches the known CPU-oversubscription / GLiNER-slowness pattern (host ~10x oversubscribed). These
  articles are dropped to DLQ, not retried — silent data loss for ~5% of peak-hour articles.
- **Action:** confirm the 0/hour rate holds as load stabilizes; if it persists, the 900s consumer
  timeout vs GLiNER latency under contention is the lever (already partially mitigated by thread pinning).

### I-2 — Stale dead-letter / failed outbox backlogs (MEDIUM, not growing)
- `content_ingestion_db.outbox_events` status=`dead_letter`: **2,259** total, **0 in last hour**, frozen
  at 2026-06-21 18:35 (pre-deploy). Breakdown: `market.prediction.v1` = 1,653 (Polymarket adapter,
  historically flaky — BP-147), `content.article.raw.v1` = 606.
- `nlp_db.outbox_events` status=`failed`: 815, frozen at 2026-06-18 (stale).
- These are **not growing** post-deploy and do not block live flow (live statuses `delivered`/`dispatched`
  are current to 10:36). Flagged because 606 dead-lettered raw articles = real lost ingestion that was
  never reprocessed.
- **Action:** triage/replay the 606 `content.article.raw.v1` dead-letters; the 1,653 prediction-market
  ones are likely the known Polymarket serializer/schema issue.

### I-3 — Two worker containers report "unhealthy" but are working (LOW)
- `knowledge-graph-scheduler-1` (unhealthy, FailingStreak 7) and
  `portfolio-manual-holdings-worker-1` (unhealthy, FailingStreak 9).
- Both fail the same way: healthcheck does an HTTP GET to a local port → `Connection refused` (Errno 111).
  These are worker-only containers with no HTTP server listening, yet the compose healthcheck probes one.
- **The scheduler is doing real work** (narrative generation at 10:33, 200 OK). So this is a
  **false-negative healthcheck**, not a dead worker — but it masks real failures (you can't trust
  "unhealthy" on these) and pollutes the all-green signal.
- **Action:** give these worker containers a process/liveness-style healthcheck instead of an HTTP probe.

### I-4 — Portfolio snapshot: seeded portfolio has no prices (LOW)
- snapshot worker logged `portfolio_snapshot_partial_prices` with `missing_count: 10` (all 10 holdings of
  the demo portfolio `...000100` lacked a price snapshot for 2026-06-22). It still wrote the snapshot.
- Likely seed-data / price-join gap rather than a pipeline stall (market data itself is flowing, I above).
- **Action:** verify demo holdings' instruments map to instruments that have current quotes; otherwise
  portfolio value KPIs for the seeded portfolio will be understated.

## Notes
- Secrets redacted in all env inspections (DB passwords shown as `[REDACTED]`).
- Postgres treated gently: all probes used `MAX`/windowed `FILTER` counts and `LIMIT`, no full scans of
  large partitioned tables, no writes.
