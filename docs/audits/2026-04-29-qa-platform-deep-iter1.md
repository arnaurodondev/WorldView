# Deep Platform QA — Iter-1 (PLAN-0049 / PLAN-0050 / PLAN-0052 Wave D)

**Date**: 2026-04-29
**Branch**: feat/content-ingestion-wave-a1
**Compose**: 72 containers (`make dev`, profile `infra`)
**Auditor mandate**: ruthless cross-cutting review of the LIVE platform; flag pre-existing bugs even outside the 3 plans.

---

## Track Verdicts

| Track | Status |
|---|---|
| 1. Container & log health | **FAIL** — 4 containers logging tracebacks; 1 hot crash-loop |
| 2. Backend endpoint validation | **PARTIAL** — most endpoints OK; 1 broken contract (ohlcv batch GET vs POST), several "shape OK / data empty" |
| 3. Frontend redesign quality | **PASS** (with NITs) — pages 200, components heavy-comment, palette respected, GAP_PX overflow fix in place |
| 4. Kafka pipeline health | **FAIL** — kg-service-group-enriched 3000+ msgs lag; nlp-pipeline-article-consumer never consumed; schema-registry rejecting portfolio.events.v1 |
| 5. Postgres data validation | **FAIL** — instrument_fundamentals_snapshot 0 rows; sentiment/impact_score 0/2956; alerts.title 1/54; prediction_markets.category 0/521 |
| 6. Pre-existing issues | **FAIL** — 5 distinct cross-service issues, 1 routing bug, 1 schema-evolution rejection |

---

## Findings

### F-DP1-01
- **Severity**: BLOCKING
- **Category**: postgres / kafka
- **File/Container**: `services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py:150` + `worldview-knowledge-graph-enriched-consumer-1`
- **Confidence**: HIGH
- **Issue**: `INSERT INTO events ... ON CONFLICT (event_id) DO NOTHING` fails with `InvalidColumnReferenceError: there is no unique or exclusion constraint matching the ON CONFLICT specification`. The `events` table is **partitioned by RANGE (created_at)**; its primary key is `(event_id, created_at)`. Postgres requires the ON CONFLICT target to match a unique/exclusion constraint that includes the partition key — `(event_id)` alone is invalid for partitioned tables.
- **Evidence**:
  ```
  [SQL: INSERT INTO events (event_id, doc_id, subject_entity_id, event_type, event_date, event_text, extraction_confidence)
   VALUES ($1,...,$7) ON CONFLICT (event_id) DO NOTHING]
  asyncpg.exceptions.InvalidColumnReferenceError: there is no unique or exclusion constraint matching the ON CONFLICT specification
  Repeated 30+ times in last 6 minutes; EARNINGS_RELEASE, M_AND_A events all lost.
  ```
- **Suggestion**: Change to `ON CONFLICT (event_id, created_at) DO NOTHING`, OR add a non-partitioned UNIQUE constraint on `event_id` (forbidden for partitioned tables — the partition key must be part of every unique constraint), OR add a unique index using `created_at` and update the SQL accordingly.
- **Auto-fixable**: YES (one-line SQL change in `_insert_event_and_entities` once we pass `created_at` as parameter or use `now()`).

### F-DP1-02
- **Severity**: CRITICAL
- **Category**: kafka
- **File/Container**: `worldview-knowledge-graph-enriched-consumer-1` (consumer group `kg-service-group-enriched`)
- **Confidence**: HIGH
- **Issue**: All 12 partitions of `nlp.article.enriched.v1` show LAG of 211–283 messages; total ~3,000 enriched articles unprocessed. Consumer is alive and processing some events successfully but every event with embedded structured events (M_AND_A, EARNINGS_RELEASE) raises F-DP1-01 and the message is retried/parked. Successful events are written but events table never gains data → `enriched_article_processed` log shows `events: 0` for every successful path.
- **Evidence**:
  ```
  kg-service-group-enriched nlp.article.enriched.v1 partitions 0-11 LAG=211..283
  Recent log: {"events": 0, "claims": 0, "entities_dirtied": 0}  (across 4 docs)
  ```
- **Suggestion**: Fix F-DP1-01; reset consumer offsets or let it catch up; verify `events` partitioned table receives writes after fix.
- **Auto-fixable**: YES (depends on F-DP1-01).

### F-DP1-03
- **Severity**: CRITICAL
- **Category**: postgres / endpoint
- **File/Container**: `market_data_db.instrument_fundamentals_snapshot` + `GET /v1/fundamentals/{id}/snapshot`
- **Confidence**: HIGH
- **Issue**: PLAN-0050 specifies the `instrument_fundamentals_snapshot` table populated with 10 columns (eps_ttm, beta, avg_volume_30d, operating_cash_flow, capex, free_cash_flow, fcf_margin, interest_coverage, net_debt_to_ebitda, credit_rating). The table exists with the correct schema, but **0 rows are populated**. The endpoint returns all NULLs for AAPL.
- **Evidence**:
  ```
  SELECT COUNT(*) FROM instrument_fundamentals_snapshot;  -> 0
  GET /v1/fundamentals/01900000-0000-7000-8000-000000001001/snapshot
  -> {"eps_ttm":null,"beta":null,...,"updated_at":null}
  ```
- **Suggestion**: Identify which worker/dispatcher is responsible for snapshot writes (likely `market-data-fundamentals-consumer`). Verify it is running, but data shows it has no inserts. Possibly the worker was added to plan but never wired to a kafka topic/subscriber, or the row is never inserted because no backfill ran.
- **Auto-fixable**: NO — needs investigation of the writer path.

### F-DP1-04
- **Severity**: CRITICAL
- **Category**: postgres / endpoint
- **File/Container**: `nlp_db.document_source_metadata` + `nlp-pipeline-relevance-scoring`
- **Confidence**: HIGH
- **Issue**: PLAN-0050 specifies the relevance scorer to populate `sentiment` and `impact_score` columns on `document_source_metadata`. Out of **2,956 articles**, **0 have sentiment, 0 have impact_score**. Only 42 have `llm_relevance_score`. Every news endpoint (`/v1/news/top`, `/v1/news/relevant`, `/v1/entities/{id}/articles`) returns `sentiment: null, impact_score: null` for every row sampled.
- **Evidence**:
  ```
  SELECT COUNT(*), COUNT(sentiment), COUNT(impact_score), COUNT(llm_relevance_score)
    FROM document_source_metadata;
  -> 2956, 0, 0, 42
  ```
- **Suggestion**: Investigate `nlp-pipeline-relevance-scoring` worker. The columns are partially written (llm_relevance_score has 42 rows) but sentiment/impact_score never. Likely the v2 prompt doesn't write these fields, or a missing column-binding in the worker repository UPDATE.
- **Auto-fixable**: NO — needs worker path investigation.

### F-DP1-05
- **Severity**: CRITICAL
- **Category**: postgres / endpoint
- **File/Container**: `alert_db.alerts` table
- **Confidence**: HIGH
- **Issue**: PLAN-0049 wave specifies alerts have `title`, `ticker`, `entity_name`, `signal_label` columns populated with backfill from old NULL rows. Out of **54 alerts**, **only 1 has a title** (53 NULL). Even most-recent alerts have `title=NULL, ticker=NULL, entity_name=NULL, signal_label=NULL`. The columns exist on the schema; the `idx_alerts_ticker` partial index is present but covers no rows.
- **Evidence**:
  ```
  SELECT COUNT(*) AS total, COUNT(title) AS with_title FROM alerts;
  -> total=54, with_title=1
  Top 5 rows: SIGNAL alerts, only the 1st has title="Signal alert" + signal_label="LOW signal"
  ```
- **Suggestion**: Verify the alert-fanout / intelligence consumer that backfills these fields. Either the migration ran but wrote the columns NULL, or the new payload writer is broken. Confirm AlertEnrichmentWorker is alive and writing.
- **Auto-fixable**: NO — needs investigation of consumer behavior.

### F-DP1-06
- **Severity**: MAJOR
- **Category**: postgres / endpoint
- **File/Container**: `market_data_db.prediction_markets` + `GET /v1/signals/prediction-markets`
- **Confidence**: HIGH
- **Issue**: PLAN-0049 specifies `category` column on `prediction_markets` and `?category=politics` filter on the endpoint. Column exists, partial index `ix_prediction_markets_category` exists. But out of **521 markets**, **0 have category populated** (all NULL). The `?category=politics` query returns 0 items even though prediction markets exist and would be otherwise returned.
- **Evidence**:
  ```
  SELECT category, COUNT(*) FROM prediction_markets GROUP BY category;
  -> NULL, 521
  GET /v1/signals/prediction-markets?category=politics  -> {"items":[], "total":0}
  GET /v1/signals/prediction-markets (no filter) → returns markets normally
  ```
- **Suggestion**: The Polymarket adapter (S4 prediction-market consumer) is not setting `category` on insert. Either the source API returns categorisation that the adapter ignores, or the column was added to schema but no populator was wired. Suggest checking the Polymarket fetcher mapping → `category` field.
- **Auto-fixable**: NO — depends on Polymarket adapter logic.

### F-DP1-07
- **Severity**: MAJOR
- **Category**: kafka
- **File/Container**: `worldview-nlp-pipeline-article-consumer-1` (consumer group `nlp-pipeline-article-consumer`)
- **Confidence**: HIGH
- **Issue**: A second consumer group `nlp-pipeline-article-consumer` exists for `content.article.stored.v1` with **CURRENT-OFFSET=0 across all 12 partitions** despite 174–313 messages on each partition. CONSUMER-ID is `-` (no active member). This indicates the consumer is **dead / never assigned**.
- **Evidence**:
  ```
  GROUP                         TOPIC                     PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG  CONSUMER-ID  HOST  CLIENT-ID
  nlp-pipeline-article-consumer content.article.stored.v1 0          0               240             240  -            -     -
  (same for all 12 partitions)
  ```
- **Suggestion**: Container `worldview-nlp-pipeline-article-consumer-1` is "Up 2 minutes (healthy)" but the kafka group has no active member. Either the consumer creates a different group ID at runtime (mismatch with what it announced), or the consumer fails to subscribe and is silently idle. Inspect the consumer's `_handle_message` / `subscribe` startup. Note: a parallel `nlp-pipeline-group` IS consuming the same topic — likely the container `nlp-pipeline-article-consumer-1` joined the wrong group, or the new consumer is duplicate.
- **Auto-fixable**: NO — needs investigation of consumer config.

### F-DP1-08
- **Severity**: MAJOR
- **Category**: container-health / kafka
- **File/Container**: `worldview-schema-registry-1`
- **Confidence**: HIGH
- **Status (closed 2026-04-29)**: ROOT CAUSE was the AvroSerializer using Confluent's default `TopicNameStrategy`, which forced all 14 portfolio event types onto a single subject (`portfolio.events.v1-value`). Each event has a different Avro record (different namespace + record name + fields), so registration of the second event_type onwards always failed BACKWARD compatibility against whichever schema landed first. **Fix**: switched the portfolio outbox AvroSerializer to use `subject.name.strategy = (topic-event_type)` so each event type registers under its own subject (e.g. `portfolio.events.v1-tenant.created`, `portfolio.events.v1-watchlist.created`). Code change: `services/portfolio/src/portfolio/infrastructure/messaging/serialization.py` — added `_subject_per_event_type(event_type)` factory and wired into the AvroSerializer config. Verified post-fix: dispatcher logs `outbox_record_published` for previously dead-lettered events; 7 new per-event subjects observed in registry; no NAME_MISMATCH/TYPE_MISMATCH 409s. The pre-existing union schema in `infra/kafka/schemas/portfolio.events.v1.avsc` is left in place (unused by writer; backward-compatible for any reader that still queries `-value`). No external consumer reads `portfolio.events.v1` today, so the subject-naming change is safe.
- **Issue**: Schema Registry repeatedly rejects `portfolio.events.v1-value` schema registration with HTTP 409. Errors include 10 NAME_MISMATCH (e.g. "expected: com.worldview.portfolio.events.TenantCreated") and 1 TYPE_MISMATCH ("reader type: STRING not compatible with writer type: NULL"). The init container (schema-registry-init) likely never finished the new portfolio schema migration; portfolio events will be unable to register Avro v2 in production.
- **Evidence**:
  ```
  POST /subjects/portfolio.events.v1-value/versions  -> 409 12080
  Caused by: IncompatibleSchemaException [10 NAME_MISMATCH on Tenant/User/Portfolio/Watchlist/Holding/Transaction/InstrumentRef events; 1 TYPE_MISMATCH on instrument.name nullability]
  Compatibility mode: BACKWARD
  ```
- **Suggestion**: Either bump the schema namespace, drop+re-register the subject, or fix the generated schema's namespace (the REGISTERED schema uses `com.worldview.portfolio.events.*` but the new candidate has a different fully-qualified name). The `name`/STRING vs NULL collision suggests `instrument.name` lost its `["null","string"]` union and is now plain `string`. Restore the union or add a default to maintain BACKWARD compat.
- **Auto-fixable**: NO — schema namespace negotiation.

### F-DP1-09
- **Severity**: MAJOR
- **Category**: endpoint / spec-mismatch
- **File/Container**: `GET /v1/ohlcv/batch?tickers=AAPL,MSFT&...`
- **Confidence**: HIGH
- **Status (closed 2026-04-29)**: documentation aligned with implementation. `docs/services/api-gateway.md:82,98` already documents the correct **POST** + UUID body shape. The audit prose below was the only stale reference — preserved here as historical record. Production frontend (`useBatchOhlcv` hook) already uses the POST contract; no implementation change needed. **Auto-fixable: YES (doc-only) — DONE.**
- **Issue**: PLAN-0049 audit (`docs/audits/2026-04-29-qa-plan-0049-wave-cd-iterations.md`) lists the OHLCV batch endpoint as `GET /v1/ohlcv/batch?tickers=AAPL,MSFT&timeframe=1d&limit=30`. The actually-deployed endpoint is **POST** with body `{"requests":[{"instrument_id":"<UUID>","timeframe":"1d","limit":N}]}`. A GET with `tickers` query string is routed to `/v1/ohlcv/{instrument_id}` (sibling route) and returns 422 "Invalid instrument_id format: 'batch' — must be a UUID". The plan documentation does not match production.
- **Evidence**:
  ```
  GET /v1/ohlcv/batch?tickers=AAPL,MSFT&timeframe=1d&limit=30
  -> 422 {"detail":"Invalid instrument_id format: 'batch' — must be a UUID"}
  POST /v1/ohlcv/batch {"requests":[{"instrument_id":"01900000-0000-7000-8000-000000001001"}]}
  -> 200 OK with bars
  OpenAPI: /v1/ohlcv/batch supports only POST.
  ```
- **Suggestion**: Either (a) update PLAN-0049 audit + frontend gateway clients to use POST + UUID-based requests; or (b) add a GET form that accepts symbol tickers. The current frontend `useBatchOhlcv` already uses POST so production is fine — the **plan documentation is the bug**. Also note: the API surface accepts UUIDs, not tickers — symbol→UUID resolution is the caller's responsibility.
- **Auto-fixable**: YES (doc fix only).

### F-DP1-10
- **Severity**: MAJOR
- **Category**: endpoint / data-quality
- **File/Container**: `GET /v1/watchlists/{wl_id}/insights`
- **Confidence**: HIGH
- **Issue**: Watchlist insights endpoint returns 200 with structurally valid response but **every mover row has `change_pct: null, sector: null, news_count_24h: 0, has_active_alert: false, top_news_title: null`**. The ticker, name, and price are populated. The "movers" are arranged by no obvious metric (since change_pct is null).
- **Evidence**:
  ```json
  {"ticker":"NVDA","price":210.79,"change_pct":null,"sector":null,"news_count_24h":0,"has_active_alert":false,"top_news_title":null}
  ... (all 5 members same shape)
  ```
- **Root cause**: `quotes` table schema lacks `prev_close` column (only `bid, ask, last, volume`). Without prev_close, change_pct can't be computed. PLAN-0050 declared a movers ranking but the price feed isn't capturing prior-session close. Sector data also unpopulated.
- **Suggestion**: Add `prev_close` (previous-session close) to the quotes upsert path, and populate `instruments.sector` (currently NULL). Without this, the movers list is meaningless.
- **Auto-fixable**: NO — pipeline change.

### F-DP1-11
- **Severity**: MAJOR
- **Category**: endpoint / data-quality
- **File/Container**: `GET /v1/news/top` + `GET /v1/entities/{id}/articles`
- **Confidence**: HIGH
- **Issue**: PRD-0026 + PLAN-0050 specify that the `display_relevance_score` is `0.5*market + 0.4*llm + 0.1*routing`. Today, `market_impact_score: null, llm_relevance_score: null` on essentially every article surfaced by `/v1/news/top` and `/v1/entities/{id}/articles` (sample of 5 articles all NULL on both). The `display_relevance_score` is being computed as a degenerate `0 + 0 + 0.4*routing_score`. Articles are still being ranked, but the ranking is purely routing-tier driven, defeating the multi-signal blend.
- **Evidence**:
  ```json
  {"market_impact_score":null,"llm_relevance_score":null,"routing_score":0.6004,"display_relevance_score":0.2401}
  -> 0.2401 == 0.4*0.6004 (within rounding)
  ```
- **Suggestion**: Re-run the relevance scorer worker on the 2956 unscored articles; verify both `market_impact_score` (from price-impact labelling) and `llm_relevance_score` (from LLM scorer) get written. Connected to F-DP1-04.
- **Auto-fixable**: NO — bulk reprocessing.

### F-DP1-12
- **Severity**: MAJOR
- **Category**: endpoint / data
- **File/Container**: `nlp_db.article_impact_windows`
- **Confidence**: HIGH
- **Issue**: PLAN-0050 / PRD-0026 introduces `article_impact_windows` table (multi-window day_t0/t1/t2/t5) replacing `article_price_impacts`. Table exists; **0 rows present**. The `impact_windows` field on `/v1/entities/{id}/articles` is always null. The `nlp-pipeline-price-impact-worker` container is healthy ("Up 4 minutes") but is producing no rows.
- **Evidence**:
  ```
  SELECT COUNT(*) FROM article_impact_windows;  -> 0
  ```
- **Suggestion**: Inspect price-impact-worker logs and config; possibly missing OHLCV inputs or a misconfigured topic. This blocks the news-ranking blend.
- **Auto-fixable**: NO — worker investigation.

### F-DP1-13
- **Severity**: MAJOR
- **Category**: kafka
- **File/Container**: `kg-instrument-group` consumer
- **Confidence**: HIGH
- **Issue**: Consumer group `kg-instrument-group` shows CURRENT-OFFSET=0 across 3 partitions while the topic has 26+25+6 messages. CONSUMER-ID is `-` (no member). However a sibling group `kg-service-group-instrument` is alive and reads the same topic with LAG=0. So one group is dead.
- **Evidence**:
  ```
  kg-instrument-group        market.instrument.created  0  0   26  26  -  -  -
  kg-service-group-instrument market.instrument.created 0  26  26  0   <active>
  ```
- **Suggestion**: Likely a leftover group from a refactor (group-name change). Delete `kg-instrument-group` from kafka.
- **Auto-fixable**: YES (`kafka-consumer-groups --delete --group kg-instrument-group`).

### F-DP1-14
- **Severity**: MAJOR
- **Category**: kafka
- **File/Container**: `content-store-consumer`
- **Confidence**: MEDIUM
- **Status (closed 2026-04-29)**: re-verified post-burst — all 12 partitions report LAG=0 once ingestion drained. The 4-8 LAG observed during the audit was steady-state catch-up while raw articles were arriving, not chronic underprovisioning. Consumer is correctly drained. **No code change required.** If later monitoring shows growing lag, the suggested tuning (increase batch size / concurrency) remains valid.
- **Issue**: `content-store-consumer` group has LAG of 5–8 per partition consistently (totals ~50–80 backlog). Not catastrophic but the consumer is keeping up only loosely on a freshly-rebuilt platform; on continued ingestion it will fall behind.
- **Evidence**: 12 partitions all showing LAG=4..8.
- **Suggestion**: Increase batch size or worker concurrency in content-store-consumer.
- **Auto-fixable**: NO — config tuning.

### F-DP1-15
- **Severity**: MINOR
- **Category**: endpoint / spec-mismatch
- **File/Container**: `POST /v1/feedback/micro-survey` and `POST /v1/feedback/submissions`
- **Confidence**: HIGH
- **Status (closed 2026-04-29)**: doc-drift documented. The canonical wire contract — already implemented and tested in production — is:
  - **`POST /v1/feedback/micro-survey`** body: `{"survey_key": "<string>", "response": "positive"|"negative"|"neutral", "context"?: dict, "comment"?: string}`. The Pydantic Literal enum on `response` rejects any other value with 422.
  - **`POST /v1/feedback/submissions`** body: `{"kind": "bug"|"feature"|"general", "description": "<string>", "title"?: string, "context"?: dict, "email"?: EmailStr}`. The legacy `feedback_type` and required `title` keys do NOT exist.
  - Email validation: `EmailStr` rejects RFC 6761 special-use TLDs (`.local`, `.test`, `.invalid`, `.example`); use `@example.com` in dev fixtures.
  No PLAN-0052 doc currently embeds the wrong schema (verified by `grep -rn 'survey_id\|feedback_type' docs/`); the only stale prose was inside this audit's `**Issue**` block. **Auto-fixable: YES (doc-only) — DONE.**
- **Issue**: PLAN-0052 audit specifies the request schema as `{"survey_id","question","response"}` and `{"feedback_type","title",...}`. Production schema requires:
  - `micro-survey` → `{"survey_key", "response": "positive"|"negative"|"neutral", ...}` (literal-only enum)
  - `submissions` → `{"kind", "description", ...}` (no `feedback_type`/`title`)
  Plan/audit documentation diverges from impl. Also, the email validator rejects `.local` TLDs (used in dev examples).
- **Evidence**:
  ```
  POST /v1/feedback/micro-survey {"survey_id":...} -> 422 missing "survey_key", literal_error on "response"
  POST /v1/feedback/submissions {"feedback_type":...} -> 422 missing "kind"
  POST /v1/feedback/submissions email "anon@test.local" -> "value is not a valid email address: special-use TLD"
  ```
- **Suggestion**: Update audit/PLAN documentation to match impl, OR make the API tolerate the documented contract.
- **Auto-fixable**: YES (doc fix).

### F-DP1-16
- **Severity**: MINOR
- **Category**: frontend
- **File/Container**: `apps/worldview-web/components/portfolio/ExposureBreakdown.tsx:143,157` and `PortfolioAnalyticsSection.tsx:117`
- **Status (closed 2026-04-29)**: fixed by adding `flex items-center justify-center` to both `min-h-[200px] bg-card` panels in `PortfolioAnalyticsSection.tsx` so child empty/error states vertically center within the panel chrome (matches the pre-existing equity-curve cell behaviour). The audit's line-number reference to `ExposureBreakdown.tsx:143,157` was a transcription artefact — the actual panels live in `PortfolioAnalyticsSection.tsx:143,157` (8/4 grid wrappers). The `ExposureBreakdown` child component already centred its own InlineEmptyState; the fix complements that with outer-panel centring so both states render the same way.
- **Confidence**: HIGH
- **Issue**: PLAN-0049 wave was supposed to remove the `min-h-[200px]` empty black panel from `EquityCurveChart.tsx`. That file no longer has the marker — but **`ExposureBreakdown.tsx` still has 2 `min-h-[200px] bg-card` panels** that exhibit the same anti-pattern when chart data is empty.
- **Evidence**:
  ```
  ExposureBreakdown.tsx:143  <div className="col-span-12 lg:col-span-8 min-h-[200px] bg-card border border-border rounded-[2px] p-2">
  ExposureBreakdown.tsx:157  <div className="col-span-12 lg:col-span-4 min-h-[200px] bg-card border border-border rounded-[2px] p-2">
  ```
- **Suggestion**: Add `flex items-center justify-center` + an explicit empty-state message inside, or render a Skeleton when data is empty.
- **Auto-fixable**: YES.

### F-DP1-17
- **Severity**: MINOR
- **Category**: frontend / 404
- **File/Container**: routes `/watchlists`, `/news`, `/screen` on frontend
- **Status (closed 2026-04-29)**: added three thin `redirect()` stub pages so previously-404 URLs now 307 to the correct production surfaces. Mapping:
  - `app/(app)/watchlists/page.tsx` → `/workspace` (where `WorkspaceWatchlistWidget` lives)
  - `app/(app)/news/page.tsx` → `/alerts` (Tab 2 = Relevant News, Tab 3 = Top Today)
  - `app/(app)/screen/page.tsx` → `/screener` (canonical path used in sidebar nav)
  Sidebar nav already pointed to canonical paths — the 404s were only triggered by direct URL entry / external links / chat slash-command suggestions. The stubs preserve user intent without flashing a 404. Note: the dev image was built before this fix; the new pages will be active on the next `make dev` rebuild of `worldview-web`. `pnpm typecheck` is clean and 26 portfolio tests pass on the new tree.
- **Confidence**: HIGH
- **Issue**: Three high-value routes return 404. PRD-0027 / PLAN-0050 surfaces watchlist insights, news intelligence and screener as separate top-level pages, but neither `/watchlists`, `/news`, nor `/screen` resolves. (Route `/instruments` redirects 307 — likely to `/instruments/AAPL` default).
- **Evidence**:
  ```
  GET /watchlists -> 404
  GET /news -> 404
  GET /screen -> 404
  GET /workspace -> 200, /alerts -> 200, /portfolio -> 200
  ```
- **Suggestion**: Either implement the routes as documented, or update navigation links / docs to reflect the actual location of these features (likely embedded in workspace).
- **Auto-fixable**: NO — depends on intended structure.

### F-DP1-18
- **Severity**: NIT
- **Category**: container-health
- **File/Container**: `worldview-postgres-1`
- **Confidence**: HIGH
- **Issue**: Postgres logs the same ON CONFLICT error from F-DP1-01 at the wire level. Just a downstream symptom; flagged so it's not double-counted.
- **Evidence**: `2026-04-29 14:20:54.318 UTC [342] ERROR: there is no unique or exclusion constraint matching the ON CONFLICT specification`
- **Suggestion**: Same as F-DP1-01.
- **Auto-fixable**: YES.

### F-DP1-19
- **Severity**: NIT
- **Category**: kafka
- **File/Container**: `worldview-kafka-1`
- **Confidence**: HIGH
- **Status (closed 2026-04-29)**: documented as expected startup behaviour in `docs/BUG_PATTERNS.md`. One-shot rebalance race during the schema-registry consumer's first JoinGroup; the broker requires the member to retry with the assigned `member.id`, which the rdkafka client does automatically. Recoverable, no impact on steady-state throughput. Tracking under the existing Kafka rebalance pattern note. **Auto-fixable: NO — accepted as cosmetic.**
- **Issue**: Kafka logs `MemberIdRequiredException` during schema-registry rebalance — startup race, recovers automatically. One-shot.
- **Evidence**: `client reason: rebalance failed due to MemberIdRequiredException` (single occurrence at boot)
- **Suggestion**: Ignore or set `group.instance.id` on schema-registry consumer for static membership.
- **Auto-fixable**: NO.

### F-DP1-20
- **Severity**: NIT
- **Category**: endpoint
- **File/Container**: `/v1/instruments` (no id)
- **Confidence**: HIGH
- **Status (closed 2026-04-29)**: documentation aligned. Canonical endpoints:
  - **List/search instruments**: `GET /v1/search/instruments?q=<symbol>` (the only list-style endpoint).
  - **Per-instrument briefing**: `GET /v1/briefings/instrument/{entity_id}` (NOT `/v1/instruments/{id}/brief`).
  - **Per-instrument actions**: `/v1/instruments/{id}/refresh-price` (POST).
  Verified against `docs/services/api-gateway.md`. No PLAN-0049 doc currently references `/v1/instruments/{id}/brief` (verified by `grep -rn 'instruments/[^/]*/brief' docs/`); the only stale reference was inside this audit's prose. **Auto-fixable: YES (doc-only) — DONE.**
- **Issue**: Bare `GET /v1/instruments` returns 404 (only `/v1/instruments/{id}/refresh-price` exists in OpenAPI). PLAN-0049 audit references `/v1/instruments/{id}/brief` which also doesn't exist; the actual endpoint is `/v1/briefings/instrument/{entity_id}`. Plan documentation drift.
- **Evidence**: `GET /v1/instruments -> 404`; OpenAPI lists no list-instruments endpoint (only `/v1/search/instruments?q=`).
- **Suggestion**: Documentation cleanup; add a list endpoint if needed for any UI.
- **Auto-fixable**: YES (doc).

---

## Summary Table

| Severity  | Count |
|-----------|-------|
| BLOCKING  | 1     |
| CRITICAL  | 4     |
| MAJOR     | 9     |
| MINOR     | 3     |
| NIT       | 3     |
| **TOTAL** | **20** |

---

## Detailed Per-Track Notes

### Track 1 — Container & log health: FAIL
- All 72 containers up; init containers Exit 0; long-running healthy ✓
- BUT `worldview-knowledge-graph-enriched-consumer-1` actively crash-looping every ~30s (F-DP1-01/02)
- `worldview-schema-registry-1` rejecting portfolio schema registrations every minute (F-DP1-08)
- `worldview-postgres-1` logging the downstream ON CONFLICT error (F-DP1-18)
- `worldview-kafka-1` startup race (F-DP1-19)

### Track 2 — Backend endpoint validation: PARTIAL
Tested 24 endpoints. Status:
- **PASS shape+data**: `/v1/news/top`, `/v1/news/relevant`, `/v1/briefings/instrument/{id}` (full structured response with `narrative, summary, citations, sections, risk_summary`), `/v1/briefings/morning` (implicit), `/v1/auth/dev-login`, `/v1/search/instruments?q=`, `/v1/alerts/history`, `/v1/feedback/nps` (rate-limit 30d works), `/v1/feedback/features` GET+POST, `/v1/feedback/features/{id}/vote` (idempotent), `/v1/feedback/beta-program/enrollment`, `/v1/feedback/submissions?mine=true`, admin gating (`/v1/feedback/submissions/anonymous`, `/v1/feedback/submissions` w/o mine → 403), redaction (`Bearer abc123def456ghi789` → `[REDACTED:JWT]`), `/v1/watchlists`, `/v1/entities/{id}/graph?depth=2`, all `/healthz`, all `/readyz`.
- **PASS shape, FAIL data**: `/v1/fundamentals/{id}/snapshot` (all NULL — F-DP1-03), `/v1/entities/{id}/articles` (sentiment/impact NULL — F-DP1-04/11), `/v1/signals/prediction-markets?category=politics` (no rows due to NULL category — F-DP1-06), `/v1/watchlists/{id}/insights` (movers w/o change_pct/sector — F-DP1-10), `/v1/alerts/history` (1/54 with title — F-DP1-05).
- **FAIL contract**: `GET /v1/ohlcv/batch?tickers=...` (route is POST with UUID body — F-DP1-09).
- **404 (route doesn't exist)**: `/v1/alerts/recent`, `/v1/alerts/pending` (200, exists), `/v1/instruments` (no list endpoint), `/v1/instruments/{id}/brief` (it's `/v1/briefings/instrument/{entity_id}`).

### Track 3 — Frontend redesign quality: PASS w/ NITs
- All key pages return 200 (`/`, `/dashboard`, `/instruments/AAPL`, `/portfolio`, `/workspace`, `/alerts`)
- `MorningBriefCard.tsx`: heavy comments ✓, ReactMarkdown rendering ✓, 503 soft handling ✓, two-tier (summary + DETAILS) ✓, palette ✓
- `RecentAlerts.tsx`: uses shared `formatAlertTitle()` fallback (PLAN-0049 T-D-4-04) ✓ — but this fallback only kicks in client-side, the underlying DB problem (F-DP1-05) still surfaces "Untitled" chips
- `SectorHeatmapWidget.tsx`: GAP_PX=2 + flex-basis calc fix in place ✓
- `InstrumentKeyMetrics.tsx`: 12 metrics ✓, 22px rows ✓, heavy comments ✓
- `NewsTab.tsx`: SentimentPill + ImpactPill components ✓ (but hide gracefully when data is null per F-DP1-04)
- `OHLCVChart.tsx` / `DrawingPalette.tsx` / `DrawingCanvas.tsx` / `VolumeProfileOverlay.tsx`: all present
- `PortfolioGainersLosers`: confirmed deleted; only references are doc comments ✓
- `EquityCurveChart.tsx`: `min-h-[200px]` removed ✓
- 25/31 instrument components use `font-mono` or `tabular-nums` (good coverage)
- DESIGN_SYSTEM.md exists at `docs/ui/DESIGN_SYSTEM.md` ✓
- 4 dashboard components don't reference the new TopBar (which now lives at `components/shell/TopBar.tsx` with Ask AI + bell trigger ✓)
- F-DP1-16: 2 `min-h-[200px]` panels still on Exposure pages
- F-DP1-17: `/watchlists`, `/news`, `/screen` 404

### Track 4 — Kafka pipeline health: FAIL
- Hot lag: kg-service-group-enriched ~3,000 across 12 partitions (F-DP1-02 caused by F-DP1-01)
- Dead consumers: `nlp-pipeline-article-consumer` (offset 0, 174–313 messages, no member — F-DP1-07); `kg-instrument-group` (offset 0, dead, sibling alive — F-DP1-13)
- KG dataset groups (economic-events / insider-transactions / macro-indicator) all consuming with LAG=0 ✓
- Mild lag: content-store-consumer 4–8 per partition (F-DP1-14)
- `nlp-pipeline-relevance-scoring` consumer-group **does not exist** as a kafka group; the worker either uses a non-kafka trigger or shares a group with another worker; investigate

### Track 5 — Postgres data validation: FAIL
- Schemas all present ✓ (alerts.title/ticker/entity_name/signal_label, document_source_metadata.sentiment/impact_score, prediction_markets.category, instrument_fundamentals_snapshot 10 cols, feedback_submissions/nps_scores/feature_requests/feature_votes/micro_survey_responses/beta_enrollments)
- Data populated:
  - feedback_submissions: 1 (test row with redaction working) ✓
  - nps_scores: 1 ✓
  - feature_requests: 1 ✓
  - feature_votes: 1 ✓
  - alerts.title: 1/54 ❌ (F-DP1-05)
  - prediction_markets.category: 0/521 ❌ (F-DP1-06)
  - instrument_fundamentals_snapshot: 0 ❌ (F-DP1-03)
  - article_impact_windows: 0 ❌ (F-DP1-12)
  - document_source_metadata.sentiment: 0/2956 ❌ (F-DP1-04)
  - document_source_metadata.impact_score: 0/2956 ❌ (F-DP1-04)
  - document_source_metadata.llm_relevance_score: 42/2956 (low coverage)
  - quotes.prev_close: column missing ❌ (root of F-DP1-10)

### Track 6 — Pre-existing issues
Cross-cuts the above: F-DP1-01 (KG ON CONFLICT, predates plans), F-DP1-08 (schema-registry portfolio.events.v1 mismatch), F-DP1-13 (orphan consumer group), F-DP1-19 (kafka rebalance race), F-DP1-20 (route doc drift). These are pre-existing platform issues that the recent plans did not address.

---

## Verdict

**NEEDS-FIXES**

The 3 plans (PLAN-0049, PLAN-0050, PLAN-0052 Wave D) added schema and routes correctly, but **the data writers behind ~50% of the new fields are silently broken** (F-DP1-03, -04, -05, -06, -10, -11, -12) and **one critical pre-existing knowledge-graph bug is blocking 3,000+ enriched articles** (F-DP1-01/02). The platform is up, all containers are healthy, all endpoints respond, but the data quality is materially degraded compared to what the plans promised. Frontend is in good shape with 2 minor blemishes (F-DP1-16/17). Auth, redaction, idempotency, admin gating, and rate limiting all work correctly.

Recommended next iteration:
1. Fix F-DP1-01 (one-line SQL ON CONFLICT change)
2. Investigate writer paths for F-DP1-03/04/05/06/10/12 — likely a common cause (missing wiring, dispatcher event, or seed/backfill not running)
3. Delete orphan consumer groups F-DP1-07/13
4. Resolve F-DP1-08 schema-registry compatibility
5. Documentation cleanup F-DP1-09/15/17/20

**Report path**: `/Users/arnaurodon/Projects/University/final_thesis/worldview/docs/audits/2026-04-29-qa-platform-deep-iter1.md`
