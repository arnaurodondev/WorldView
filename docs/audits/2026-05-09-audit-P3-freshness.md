# P3 — Data Freshness Sweep

**PRD**: PRD-0087 / PLAN-0087 — Pre-Demo QA
**Wave**: B audit (T-B-P3, VA-9 + cross-cutting)
**Agent**: P3
**Time**: 2026-05-09T17:25Z
**Mode**: read-only
**Defect-id range**: D-P3-001 ..

---

## Executive summary

The platform is **NOT demo-ready from a freshness standpoint.** Investigation surfaced 12 freshness gaps, 6 hard fails on the demo path. Headlines:

1. **No live news ingestion configured.** `content_ingestion_db.sources` is empty (0 rows) and the scheduler logs `sources_evaluated=0 tasks_enqueued=0` once per minute. The 513 articles in `nlp_db.document_source_metadata` are seed/manual data, all created within a single hour (16:00Z today). However a second pathway via `content-ingestion-worker` IS actively pulling from Finnhub-TSLA right now (17:18Z) — there appear to be two distinct ingestion paths.
2. **NLP pipeline is bottlenecked.** `entity_mentions=0`, `mention_resolutions=0`, `chunk_entity_mentions=0`, `routing_decisions=6`, `article_impact_windows=0` against 513 ingested articles. nlp-pipeline-group is consuming only 6/12 partitions of `content.article.stored.v1` (group offsets 15 against topic LEO 99); 6 partitions show CURRENT-OFFSET = `-` (unassigned).
3. **KG enriched-consumer is broken with a SQL bug.** It queries `intelligence_db.document_source_metadata` — a table that lives in `nlp_db`, not `intelligence_db`. Every enriched event triggers `UndefinedTableError`, processes 0 relations/0 evidence/0 events. This is why `intelligence_db.relations=18` (still seed) and `relation_evidence_raw=0`.
4. **Calendars empty.** `earnings_calendar=0`, `economic_events=0`, `prediction_markets=0`, `prediction_market_snapshots=0`. Dashboard tile A2 will show three empty surfaces.
5. **Equity OHLCV stale.** Latest equity bar is 2026-05-06 (3 days old) for the 8 well-known equities (AAPL, MSFT, NVDA, META, AMZN, GOOGL, JPM, TSLA); 28 of 36 instruments have **zero** OHLCV bars; only 8 crypto pairs have last-24h data.
6. **Sector heatmap will under-fill.** Of 11 GICS sectors only 6 have any instrument backing data (Technology, Financial Services, Healthcare, Consumer Cyclical, Communication Services, Consumer Defensive, Energy via XOM). The 11-call heatmap composer will return 4–5 errored sector legs, rendering as gaps.
7. **Entity narratives = 0.** `entity_narrative_versions=0`, `path_insights=0`, `relation_summaries=0` — the entire intelligence layer (A4 Intelligence tab, A7 chat) is producing nothing.
8. **Demo-pickable ticker list is small.** Only 8 tickers (AAPL, MSFT, NVDA, META, AMZN, GOOGL, JPM, TSLA) have OHLCV+fundamentals+news. 28 of 36 instruments are unsafe to pick.

---

## 1. Freshness gap table

Time of measurement: 2026-05-09T17:13Z..17:24Z. `now()` ≈ 2026-05-09T17:13Z.

| # | Datum | Target | Actual | Gap | Severity |
|---|-------|--------|--------|-----|----------|
| 1 | Latest article `created_at` | within 24h | `2026-05-09T16:01:18Z` (≈1h ago) — **but all 513 docs created within one hour, none earlier** | seed-only | HF-4 |
| 2 | Latest article `published_at <= now()` | within 24h | `2026-05-09T10:13:20Z` (~3h ago) | OK on its own; some seed rows post-dated to 2026-05-15/16 | INFO |
| 3 | Latest OHLCV bar (top-25 equities) | within 1 trading day | `2026-05-06T00:00:00Z` for ALL 8 covered equities (3 days old, daily timeframe) | 3 days | SF-2 |
| 4 | OHLCV coverage of top-25 demo tickers | ≥25 tickers with bars | **8** of 25 expected (AAPL, MSFT, NVDA, META, AMZN, GOOGL, JPM, TSLA — 90 bars each) | 17 missing | HF-4 |
| 5 | Crypto OHLCV (intraday) freshness | within 1h | `2026-05-09T13:50Z` (~3h 23min ago) | mild | SF-2 |
| 6 | Earnings calendar — next 7d | rows for 7d | **0** rows total | catastrophic | HF-4 |
| 7 | Economic events — next 7d, all regions | rows for 7d | **0** rows total | catastrophic | HF-4 |
| 8 | Prediction markets refreshed | within 6h | `prediction_markets=0`, `prediction_market_snapshots=0` | catastrophic | HF-4 |
| 9 | Sector heatmap — 11 GICS sectors | 11/11 | **6/11** with instrument backing (Technology, Financial Services, Healthcare, Consumer Cyclical, Communication Services, Consumer Defensive — Energy single-instrument XOM with 0 bars) | 5+ missing | HF-4 |
| 10 | Entity narratives top-50 | ≥45 | **0** (`entity_narrative_versions`) | total absence | HF-3 |
| 11 | KG canonical entities | ≥400 | **316** (was 277 at init, growing slowly) | -84 | SF-2 |
| 12 | Provisional entity queue drained | ≤10 pending | **0 pending, 0 total** | OK | INFO |
| 13 | Outbox backlog per service | <100 unsent | market_data 20 delivered, nlp 12 dispatched, content_store 6 delivered, alert 2 dispatched, intelligence 0; ingestion 0 pending; gateway/rag/kg have no `outbox_events` table | OK | INFO |
| 14 | KG relation count | high | **18** (seed-only; raw=0, evidence=0) | severe | HF-3 |
| 15 | NLP entity_mentions | hundreds | **0** rows; `chunk_entity_mentions=0`; `mention_resolutions=0`; `routing_decisions=6` | catastrophic | HF-3 |

---

## 2. Per-source ingestion health

### EODHD
- Path: `ingestion_db.ingestion_tasks` (provider=`eodhd`)
- Tasks: 280 succeeded, **3 failed** (2 ohlcv 404 "EODHD does not support endpoint 'eod'"; 1 macro_indicator 404 "endpoint not supported")
- Latest successful run per dataset (all at ~13:56Z, ~3.5h ago):
  - `economic_events` → 6 succeeded, but downstream `market_data_db.economic_events`=0 ⇒ rows fetched but not persisted (evidence in DB)
  - `earnings_calendar` → 1 succeeded, but `market_data_db.earnings_calendar`=0 ⇒ same persistence gap
  - `news_sentiment` → 4 succeeded
  - `yield_curve` → 3 succeeded but `market_data_db.yield_curve`=0
  - `insider_transactions` → 3 succeeded but `market_data_db.insider_transactions`=0
  - `macro_indicator` → 4 succeeded, 1 failed, but `market_data_db.macro_indicators`=0
  - `fundamentals` → 48 succeeded → `market_data_db.fundamental_metrics` has 73,356 rows, 26 instruments — OK
  - `ohlcv` → 196 succeeded, 2 failed → only 8 instruments have bars in DB
- **Diagnosis**: Several ingestion tasks complete (claim "succeeded") but downstream tables stay empty. The bronze/silver write may be happening, but the consumer that promotes those to gold (market_data_db tables) appears to silently drop rows. Needs deeper trace by P1 or fix-now.

### Polymarket
- Tables: `prediction_markets=0`, `prediction_market_snapshots=0`
- No `ingestion_tasks` row matches `provider='polymarket'` (only `eodhd` and `alpaca` recorded)
- **Diagnosis**: Polymarket adapter is not running. PRD-0019 work may be wired but no scheduler entry calls it.

### Polygon
- Not present in `ingestion_tasks` provider list.
- **Diagnosis**: Not configured. (Per CLAUDE.md, EODHD is primary; Polygon was historical reference.)

### Alpaca
- 10 successful ohlcv tasks, latest at 2026-05-09T13:51Z. Used for crypto intraday — explains the 8 crypto pairs with last-24h data.

### RSS feeds / Finnhub / SEC EDGAR
- `content_ingestion_db.sources` table has **0 rows** — formal source registry is empty.
- BUT `content-ingestion-worker` logs show `fetch_cycle_complete fetched=204 source=Finnhub-TSLA` actively at 17:18Z. So a non-table-driven source list (likely env-var or hardcoded) is fetching Finnhub.
- Articles in `nlp_db` by `source_name`/`source_type` (513 total): yahoo_finance/eodhd_news 252, finnhub/finnhub_news 126, yahoo_finance/financial 41, eodhd 22, sec_edgar/earnings_transcript 21, sec_edgar/sec_10k 14, sec_edgar/sec_8k 12, tenant_upload 6, sec_edgar/sec_10q 5, finnhub/signal_intel 5, finnhub/claim 3, sec_edgar/relation 3, seeking_alpha 2, sec_edgar/press_release 1.
- **Diagnosis**: The 513 articles look like seed-loaded fixtures (all created at 16:00Z within minutes of each other, most published_at in May 2026). Live RSS/Finnhub fetching is happening via the worker but those new articles are not yet visible in `document_source_metadata` because of the NLP-pipeline backlog (see §3).

### NLP-pipeline (consumer)
- `nlp-pipeline-group` consumes `content.article.stored.v1`. **Only 6/12 partitions assigned to its consumer**:
  - Partitions {0,1,5,10,11} have CURRENT-OFFSET set; rest show `-`
  - LAG on assigned partitions: 9, 9, 10, 3, 2 → ~33 messages backlog
  - Partitions without assignment have LOG-END-OFFSET 4–16 (cumulative ~80 unconsumed messages)
- Container `worldview-nlp-pipeline-article-consumer-1` is `Up 3 hours (healthy)` but **last log line is 2026-05-09T14:19:14Z** — silent for ~3 hours. The container reports healthy via probe but has stopped processing.
- **Defect**: assignment lost on partition rebalance and never recovered, OR consumer is wedged on a single message.

### KG enriched-consumer
- `kg-service-group-enriched` is processing `nlp.article.enriched.v1` events successfully (lag=0)
- BUT every message hits a hard SQL error: `UndefinedTableError: relation "document_source_metadata" does not exist` from `relation_evidence.py:112`. The consumer queries `intelligence_db.document_source_metadata` but that table is in `nlp_db`. Output: `relations=0, evidence=0, events=0, claims=0, entities_dirtied=0` per article. Logged as warning, not error → consumer reports `enriched_article_processed` and commits offset, silently dropping all KG writes. This violates R9 (no cross-service DB) and is likely a recent regression.
- Secondary error in same window: `current transaction is aborted` on `INSERT INTO events` partition — this is the cascade after the first error within the same UoW.

---

## 3. Failed-tasks summary

`market_data_db.failed_tasks` is **empty (0 rows)** — no centralized failure log surfacing real problems. `ingestion_db.ingestion_tasks` failure tally:

| Provider | Dataset | Error | Count |
|----------|---------|-------|-------|
| eodhd | ohlcv | `EODHD does not support endpoint 'eod' (HTTP 404)` | 2 |
| eodhd | macro_indicator | `EODHD does not support endpoint 'macro-indicator' (HTTP 404)` | 1 |

These are configuration/URL bugs in the EODHD adapter. The bigger silent failures (described above) do not show up in either table.

`market_data_db.ingestion_events` (deduplication record): 103 ohlcv events, 11 fundamentals, 9 intraday_resampling — none for calendars/predictions.

---

## 4. Demo-pickable tickers

Final list of tickers SAFE for the director to pick (have OHLCV last 7d + fundamentals + ≥1 article in last 7d):

| Ticker | OHLCV bars | Latest bar | Fundamentals rows | Articles (title match) | Verdict |
|--------|-----------|-----------|-------------------|------------------------|---------|
| AAPL | 90 | 2026-05-06 | 8,178 | 76 | SAFE |
| MSFT | 90 | 2026-05-06 | 8,089 | 41 | SAFE |
| NVDA | 90 | 2026-05-06 | 7,933 | 60 | SAFE |
| META | 90 | 2026-05-06 | 7,890 | 21 | SAFE |
| AMZN | 90 | 2026-05-06 | 8,090 | 14 | SAFE |
| GOOGL | 90 | 2026-05-06 | 8,178 | 12 | SAFE |
| JPM | 90 | 2026-05-06 | 6,800 | 17 | SAFE |
| TSLA | 90 | 2026-05-06 | 6,400 | 44 | SAFE |
| BTC-USD | 722 | 2026-05-09T13:49Z | 0 | unknown | partial — no fundamentals tab |
| ETH-USD | 228 | 2026-05-09T13:45Z | 0 | unknown | partial |
| SOL-USD | 510 | 2026-05-09T13:47Z | 0 | unknown | partial |

**AVOID** (28 instruments with 0 OHLCV bars):
DIS, LLY, MA, MS, MSTR, NFLX, PFE, PG, PPA, QQQ, SHY, SPY, TLT, UNH, V, VOO, WMT, XLE, XLK, XOM. Each has a row in `instruments` (so `/instruments/{symbol}` will resolve) but **the OHLCV chart will show 0 bars** — direct HF-4 fail.

For Phase B B5 (free-form ticker pick), the safe answer set is the 8 equities + crypto. **Director must be steered to those names.** Any prompt-and-pick exercise must pre-seat the user input.

Cold-start tickers not even in `instruments` (e.g., COIN, CRM, INTC, AMD, ORCL, BAC, WFC, PYPL, OPENAI, XOM as cold-pick): page will 404 unless §B5 cold-start enrichment lands (PLAN-0087-C is pre-flagged for this).

---

## 5. Defects (YAML, paste-ready)

```yaml
- id: D-P3-001
  va: VA-9
  surface: A2 (dashboard — predictions tile)
  severity: HF-4
  status: open
  agent: P3
  found_at: 2026-05-09T17:13Z
  reproduce: |
    docker exec worldview-postgres-1 psql -U postgres -d market_data_db \
      -c "SELECT COUNT(*) FROM prediction_markets; SELECT COUNT(*) FROM prediction_market_snapshots;"
    Both return 0.
  evidence:
    - count: prediction_markets=0
    - count: prediction_market_snapshots=0
    - ingestion_tasks: zero rows with provider='polymarket'
  root_cause: |
    Polymarket adapter / scheduler entry not running. PRD-0019 implementation may
    be wired but no scheduler dispatches it. content-ingestion-scheduler logs
    'sources_evaluated=0 tasks_enqueued=0' every minute — the polling-policy table
    has rows but adapter binding is missing.
  fix_decision: TBD

- id: D-P3-002
  va: VA-9
  surface: A2 (dashboard — earnings tile), A4 instrument fundamentals
  severity: HF-4
  status: open
  agent: P3
  found_at: 2026-05-09T17:13Z
  reproduce: |
    docker exec worldview-postgres-1 psql -U postgres -d market_data_db \
      -c "SELECT COUNT(*) FROM earnings_calendar;"  → 0
  evidence:
    - count: earnings_calendar=0
    - ingestion_db.ingestion_tasks shows 1 succeeded earnings_calendar task at 13:56Z
      but the gold table is empty (consumer dropping rows silently)
  root_cause: |
    EODHD earnings_calendar dataset task succeeds at the fetch layer but the
    market.dataset.fetched consumer either fails to upsert or commits offset
    without writing.  KG-earnings-calendar-dataset-consumer also has lag=24-67
    on partition 2 (assigned) plus partitions 0,3,4 unassigned (offset='-').
  fix_decision: TBD

- id: D-P3-003
  va: VA-9
  surface: A2 (dashboard — economic events / world clock)
  severity: HF-4
  status: open
  agent: P3
  found_at: 2026-05-09T17:13Z
  reproduce: |
    docker exec worldview-postgres-1 psql -U postgres -d market_data_db \
      -c "SELECT COUNT(*) FROM economic_events;"  → 0
  evidence:
    - count: economic_events=0
    - ingestion_db: 6 succeeded economic_events tasks; gold table empty
  root_cause: |
    Same persistence-gap pattern as D-P3-002. Plus all other macro tables are
    empty: macro_indicators=0, yield_curve=0, insider_transactions=0,
    quotes=0, daily_sentiments=0.
  fix_decision: TBD

- id: D-P3-004
  va: VA-3
  surface: A4 (instrument page — KG tab, fundamentals chart), B5 (deep-dive)
  severity: HF-4
  status: open
  agent: P3
  found_at: 2026-05-09T17:13Z
  reproduce: |
    docker exec worldview-postgres-1 psql -U postgres -d market_data_db \
      -c "SELECT i.symbol, COUNT(o.bar_date) FROM instruments i \
          LEFT JOIN ohlcv_bars o ON o.instrument_id=i.id GROUP BY i.symbol \
          ORDER BY 2 DESC;"
    28 of 36 instruments return COUNT=0 (DIS, LLY, MA, MS, MSTR, NFLX, PFE, PG,
    PPA, QQQ, SHY, SPY, TLT, UNH, V, VOO, WMT, XLE, XLK, XOM).
  evidence:
    - eight equity tickers (AAPL/MSFT/NVDA/META/AMZN/GOOGL/JPM/TSLA) have 90 bars,
      latest 2026-05-06 (3 days old)
    - 8 crypto pairs have intraday up to 2026-05-09T13:50Z
  root_cause: |
    Backfill OHLCV ingestion never ran for the 28 missing instruments — they were
    discovered (created in instruments) but no ingestion_tasks were enqueued for
    them. Symbol_tiers / polling_policies coverage gap.
  fix_decision: TBD

- id: D-P3-005
  va: VA-3
  surface: A2 (dashboard — sector heatmap)
  severity: HF-4
  status: open
  agent: P3
  found_at: 2026-05-09T17:13Z
  reproduce: |
    SELECT sector, COUNT(*) FROM market_data_db.instruments WHERE sector IS NOT NULL
      GROUP BY 1 ORDER BY 2 DESC;
    → 6 sectors only: Technology(6), Financial Services(3), Healthcare(2),
      Consumer Cyclical(2), Communication Services(2), Consumer Defensive(1),
      Energy(1 = XOM but 0 bars).
  evidence:
    - get_market_heatmap composer at services/api-gateway/src/api_gateway/clients.py:893
      makes 11 parallel screener calls; only 6 will return non-empty.
    - Missing GICS sectors: Industrials, Materials, Real Estate, Utilities, Energy(degraded).
  root_cause: |
    Instrument seed list does not cover all 11 GICS sectors. No instrument exists
    for Industrials/Materials/Real Estate/Utilities; Energy has only XOM with 0 bars.
  fix_decision: TBD

- id: D-P3-006
  va: VA-3
  surface: cross-cutting (NLP pipeline throughput)
  severity: HF-3
  status: open
  agent: P3
  found_at: 2026-05-09T17:14Z
  reproduce: |
    docker exec worldview-kafka-1 kafka-consumer-groups --bootstrap-server \
      localhost:9092 --describe --group nlp-pipeline-group
    → only partitions {0,1,5,10,11} have CURRENT-OFFSET set; partitions
      {2,3,4,6,7,8,9} show '-' (unassigned). Topic LEO totals 99 across 12
      partitions; group has consumed only ~15.
    docker logs worldview-nlp-pipeline-article-consumer-1 --tail 5
    → last log line is 2026-05-09T14:19:14Z (~3h silent). Container is healthy.
  evidence:
    - Kafka group describe output (above) — 7/12 partitions unassigned
    - nlp_db.entity_mentions=0, chunk_entity_mentions=0, mention_resolutions=0,
      routing_decisions=6 against 513 ingested articles (only 6 articles fully
      processed via the NLP pipeline)
    - article_impact_windows=0 (PriceImpactLabellingWorker has nothing to label)
  root_cause: |
    nlp-pipeline-article-consumer wedged after partial processing of a batch on
    2026-05-09T14:19:14Z. Health probe still passes (likely TCP /healthz)
    but the rdkafka consumer has stopped polling on the 7 unassigned partitions
    and stopped processing on the assigned ones.
    Likely BP-407 (Kafka backpressure) recurrence or a single poison-pill
    message stuck on the polling loop.
  fix_decision: TBD

- id: D-P3-007
  va: VA-2
  surface: A4 (Intelligence tab), A7 (entity-graph chat)
  severity: HF-3
  status: open
  agent: P3
  found_at: 2026-05-09T17:24Z
  reproduce: |
    docker logs worldview-knowledge-graph-enriched-consumer-1 --tail 20
    Every message produces:
      WARNING evidence_source_metadata_lookup_failed
      asyncpg.exceptions.UndefinedTableError: relation "document_source_metadata" does not exist
      [SQL: SELECT source_name, source_type FROM document_source_metadata WHERE document_id = $1 LIMIT 1]
    Followed by:
      INFO enriched_article_processed relations=0 evidence=0 events=0 claims=0
  evidence:
    - file: services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_evidence.py:112
    - intelligence_db has no document_source_metadata table; that table lives in nlp_db
    - intelligence_db.relations=18 (all seed), relation_evidence_raw=0,
      relation_evidence=0, entity_narrative_versions=0, path_insights=0,
      relation_summaries=0
  root_cause: |
    Repository method lookup_source_metadata uses the intelligence_db session
    but the table belongs to nlp_db (R9 cross-service DB violation, but intentional
    pre-fix). Either the SQL should target the read replica of nlp_db, or
    source metadata should arrive on the nlp.article.enriched.v1 envelope.
    Recent regression — likely introduced after PLAN-0083 frozen-dataclass
    migration or PLAN-0086 multi-tenant content isolation rename.
  fix_decision: TBD  # very likely fix-now, single-file repository fix or contract change

- id: D-P3-008
  va: VA-3
  surface: A4 KG tab, A7 chat
  severity: HF-3
  status: open
  agent: P3
  found_at: 2026-05-09T17:24Z
  reproduce: |
    docker exec worldview-postgres-1 psql -U postgres -d intelligence_db \
      -c "SELECT COUNT(*) FROM entity_narrative_versions; \
          SELECT COUNT(*) FROM path_insights; \
          SELECT COUNT(*) FROM relation_summaries;"
    → 0, 0, 0
  evidence:
    - canonical_entities=316 (growing slowly from 277 baseline)
    - entity_aliases=580, entity_embedding_state=612, llm_usage_log=6
    - NarrativeGenerationWorker (PLAN-0074) has not run OR has run and produced 0
      because relations=18 (seed only, no real KG to summarise) — see D-P3-007 cascade
  root_cause: |
    Cascade from D-P3-007. With relation_evidence_raw=0, no relations get
    promoted, no narrative trigger fires. NarrativeGenerationWorker is idle.
  fix_decision: TBD

- id: D-P3-009
  va: VA-7
  surface: pipeline (multiple KG dataset consumers)
  severity: SF-3
  status: open
  agent: P3
  found_at: 2026-05-09T17:14Z
  reproduce: |
    kafka-consumer-groups --describe --all-groups | awk 'NR==1 || $5+0 > 0'
    → kg-earnings-calendar-dataset-group lag 25 on partition 2; 4 partitions unassigned
    → kg-economic-events-dataset-group lag 23 on partition 2; 4 partitions unassigned
    → kg-insider-transactions-dataset-group lag 24 on partition 2; 4 partitions unassigned
    → kg-macro-indicator-dataset-group lag 25 on partition 2; 4 partitions unassigned
    → kg-service-group-fundamentals lag 25 on partition 2; 4 partitions unassigned
  evidence: kafka-consumer-groups output above
  root_cause: |
    Same partial-assignment pattern as D-P3-006. Each KG-dataset-consumer is one
    container that started ~6 minutes ago (after the make-dev rebuild) and has
    only claimed half its partitions. May be librdkafka rebalance bug or
    static-membership / cooperative-sticky misconfig.
  fix_decision: TBD

- id: D-P3-010
  va: VA-9
  surface: ops (live news ingestion)
  severity: HF-1
  status: open
  agent: P3
  found_at: 2026-05-09T17:08Z
  reproduce: |
    docker exec worldview-postgres-1 psql -U postgres -d content_ingestion_db \
      -c "SELECT COUNT(*) FROM sources;"  → 0
    docker logs worldview-content-ingestion-scheduler-1 --tail 5
    → "scheduler_tick_no_sources" "sources_evaluated=0 tasks_enqueued=0" (every 60s)
  evidence:
    - content_ingestion_db.sources=0
    - Scheduler runs but enqueues nothing
  root_cause: |
    sources table never seeded. Either make seed missed it or the source registry
    moved to a different storage. Note: content-ingestion-WORKER (separate container)
    IS actively polling Finnhub-TSLA at 17:18Z, fetching 204 articles per cycle —
    so a parallel hardcoded source list exists somewhere outside the DB.
    The scheduler-driven path (RSS + new sources) is dead.
  fix_decision: TBD

- id: D-P3-011
  va: VA-3
  surface: A4 (intraday chart for equities)
  severity: SF-2
  status: open
  agent: P3
  found_at: 2026-05-09T17:13Z
  reproduce: |
    SELECT MAX(bar_date) FROM ohlcv_bars o JOIN instruments i ON o.instrument_id=i.id
      WHERE i.symbol='AAPL';
    → 2026-05-06T00:00:00Z (3 days old)
  evidence:
    - All 8 equities with bars share the same MAX(bar_date)=2026-05-06 (likely
      the seed cutoff). Today is 2026-05-09 (Saturday in walltime); last
      trading day was Friday 2026-05-08 ⇒ should have a 2026-05-08 bar.
  root_cause: |
    Daily OHLCV refresh has not run since seed. ingestion-scheduler not
    enqueueing daily bars for those instruments today.
  fix_decision: TBD

- id: D-P3-012
  va: VA-7
  surface: ops (content-store ingest path)
  severity: SF-3
  status: open
  agent: P3
  found_at: 2026-05-09T17:18Z
  reproduce: |
    docker logs worldview-content-store-1 --tail 30 | grep "422"
    → "POST /api/v1/documents/batch HTTP/1.1 422 Unprocessable Entity"
  evidence:
    - At least one 422 within last 30 lines (others 200 OK)
  root_cause: |
    Some article payloads from content-ingestion-worker fail content-store
    schema validation. Quantity unclear without longer log window.
    Likely candidates: missing required fields on Finnhub records, or
    SnapTrade/multi-tenant rename mismatch (PLAN-0086).
  fix_decision: TBD
```

---

## 6. Recommended triage priority

For Wave D (triage), recommend the following order based on demo-path leverage:

1. **D-P3-007** (KG enriched consumer cross-DB SQL bug) — fix-now, single repository file. Unblocks D-P3-008 and the entire intelligence layer. **Highest leverage, smallest fix.**
2. **D-P3-006** (NLP article consumer wedged on 7/12 partitions) — fix-now (restart consumer + investigate librdkafka rebalance). Restoring throughput here populates entity_mentions, routing_decisions, and feeds the KG pipeline. Pair with rebuild of `worldview-nlp-pipeline-article-consumer-1`.
3. **D-P3-002 / D-P3-003** (calendars empty) — investigate market.dataset.fetched consumer for earnings/economic-events. Likely same partial-assignment pattern as D-P3-009.
4. **D-P3-001** (Polymarket prediction markets) — needs Polymarket adapter scheduler entry; may be sub-agent if PRD-0019 wiring is incomplete.
5. **D-P3-005** (sector heatmap 6/11) — seed extra instruments (XLI, XLB, XLRE, XLU, XLE) into seed script, OR have heatmap composer fall back to ETF returns when no constituents exist. Frontend mitigation: render gaps honestly with "no data" tile copy.
6. **D-P3-004 + D-P3-011** (OHLCV gaps on 28 instruments + 3-day stale on the 8) — schedule a one-shot daily backfill via S2 ingestion-scheduler.
7. **D-P3-010** (sources table empty) — seed RSS source list; alternative is to leave content-ingestion-worker's hardcoded path running.
8. **D-P3-009 / D-P3-012** — observability and tail issues, lower priority.

---

## 7. Observations not raised as defects

- `intelligence_db.canonical_entities` is growing organically (277 → 316 over ~2h; ~20/h). At this rate, the ≥400 target needs ~5h more. The ingestion path that creates canonicals appears healthy.
- `entity_aliases=580`, `entity_embedding_state=612` — embeddings infrastructure is alive; consumers are running.
- `llm_usage_log=6` rows total in intelligence_db means the KG LLM-using workers (Llama 3.1 8B for unresolved-resolution, narrative gen) have barely run. Not a freshness gap per se — symptom of D-P3-006/7 bottleneck.
- No `outbox_events` row backlog above 100 anywhere — the dual-write pattern is healthy (BP-440/441 not regressed).
- ingestion-scheduler `last_task` updated at 13:56Z (~3h ago); since it has no sources, it would be the same forever. Not a freshness lag, just an idle service.

---

## 8. Diagnostic SQL bundle

For re-validation after fixes:

```sql
-- 1. Article freshness
SELECT MAX(created_at), MAX(published_at), COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours') FROM nlp_db.public.document_source_metadata;
-- 2. NLP throughput (must be >0 after fix)
SELECT COUNT(*) FROM nlp_db.public.entity_mentions;
SELECT COUNT(*) FROM nlp_db.public.mention_resolutions;
SELECT COUNT(*) FROM nlp_db.public.routing_decisions;
-- 3. KG growth
SELECT COUNT(*) FROM intelligence_db.public.relation_evidence_raw;
SELECT COUNT(*) FROM intelligence_db.public.entity_narrative_versions;
-- 4. Calendars
SELECT COUNT(*) FROM market_data_db.public.earnings_calendar WHERE report_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days';
SELECT COUNT(*) FROM market_data_db.public.economic_events WHERE event_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days';
-- 5. Predictions
SELECT COUNT(*), MAX(snapshot_at) FROM market_data_db.public.prediction_market_snapshots;
-- 6. Top-25 OHLCV
SELECT i.symbol, COUNT(o.bar_date), MAX(o.bar_date) FROM market_data_db.public.instruments i
  LEFT JOIN market_data_db.public.ohlcv_bars o ON o.instrument_id=i.id GROUP BY i.symbol ORDER BY 2 DESC;
-- 7. Kafka lag (run from kafka container)
-- kafka-consumer-groups --bootstrap-server localhost:9092 --describe --all-groups | awk 'NR==1||$5+0>0'
```

---

**End of P3 report.**
