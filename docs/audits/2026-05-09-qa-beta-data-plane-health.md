# Audit — Data-Plane Health (Postgres × Kafka × Container logs)

**PRD**: PRD-0087 / PLAN-0087 — Pre-Demo QA, beta-readiness specialist sweep
**Run timestamp**: 2026-05-09T19:15Z (local stack, post-Postgres-restart at 18:53Z)
**Mode**: read-only
**Defect-id range**: D-DPH-001 ..

---

## Executive summary

The platform has **63 healthy containers**, **12 Postgres databases**, **27 Kafka topics + 26 Schema Registry subjects**, and **22 consumer groups**. Substantial progress vs the P3 freshness audit (entity_mentions 0→415, routing_decisions 6→72, canonical_entities 316→330, entity_narrative_versions 0→**331**, llm_usage_log 6→1,320) — but **9 hard fails and 3 soft fails are open**, several catastrophic.

Headline findings:

1. **`market-data-prediction-markets` consumer is detached.** No CONSUMER-ID. **15,777-message lag on `market.prediction.v1`** (16,500 total). Producer is firing into a void. `market_data_db.prediction_market_snapshots`=**0**. Dashboard A2 prediction-markets tile is empty. (HF-4) **NEW vs P3.**
2. **`nlp-pipeline-group` consumer is detached.** No CONSUMER-ID. **~970-message lag on `content.article.stored.v1`** (1,095 total). The `worldview-nlp-pipeline-1` container is healthy and the FastAPI surface works (entity_resolve handles requests) but the Kafka article-consumer side is **silently not running** since the service-restart at 18:15Z. Zero new articles processed in the last 30 min. (HF-3) **NEW vs P3 — was wedged at 6/12 partitions before; is now at 0/12.**
3. **`worldview-knowledge-graph-enriched-consumer-1` STILL hits the cross-DB SQL bug** identified as D-P3-007. `lookup_source_metadata` queries `intelligence_db.document_source_metadata` — that table lives in `nlp_db`, not `intelligence_db`. Every message logs `evidence_source_metadata_lookup_failed` with `UndefinedTableError` and silently aborts the transaction (`InFailedSQLTransactionError` cascades). Only 9 articles ever produced `enriched_article_processed` — and **all 9 with `relations=0, evidence=0, events=0, claims=0`**. `intelligence_db.relation_evidence_raw=0`, `relations=0`, `relation_evidence=0`. The KG never grows from new ingestion. (HF-3) **CARRIED OVER from D-P3-007, NOT FIXED.**
4. **`knowledge-graph-path-insight-worker` is restarting.** `RestartCount=4` (only restarting container in the platform). Two distinct fatal errors: (a) `[Errno -2] Name or service not known` (DNS/connection loss after Postgres restart at 18:53Z); (b) **PostgresSyntaxError: syntax error at or near "end"** in a Cypher query — `MATCH p=(start:entity ...)-[*2..5]-(end:entity)` — `end` is a Cypher reserved keyword and must be quoted as `\`end\`` or renamed `target`/`finish`. Has failed all 27 jobs in `path_insight_jobs`. (HF-3) **NEW.**
5. **KG scheduler `provisional_enrichment_retry` UPDATE references a non-existent column.** Repeating `UndefinedColumnError: column "subject_provisional_id" does not exist` on `relation_evidence_raw`. Schema lives without that column; the UPDATE statement was written for a different shape. 60 errors in 6 h. Provisional entity dedup write-back is broken; `provisional_entity_queue` keeps 72 rows. (HF-3) **NEW.**
6. **`/api/v1/search/chunks` returns 500.** `RuntimeError: EmbeddingClient is required when query_text is provided without query_embedding` — the API logs `api_embedding_client_ready` at startup but the use-case is receiving `None`. Recurring 5 times in 6 h. Hybrid retrieval is broken on every keyword-only query. (HF-3) **NEW.**
7. **rag-chat tool calls fail wholesale.** 30 `execute_sync_error_event`, 29 `all_tools_failed`, 24 `upstream_http_error`. Specific failures captured: `get_price_history` for "What is the price of AAPL?" → fails because `GET /api/v1/instruments/symbol/AAPL` returns 404 (instrument lookup returns nothing despite seed data showing AAPL exists). API gateway returned `POST /v1/chat → 503 Service Unavailable` to upstream traffic (Cloudflare IPs). (HF-1, HF-6) **NEW.**
8. **rag-chat is not verifying internal JWTs in 53 requests.** Event `internal_jwt_unverified_decode` fired 53× — auth verification is bypassed (likely development-mode permissive decode). Fine for local-dev demo, but the warning indicates the verification path is not exercised; if the demo environment expects RS256 verification, `unverified_decode` is a regression / misconfig. (SF-3 / security HF if production.) **NEW.**
9. **`portfolio-snapshot-worker` failed 900 times** with `ohlcv_price_fetch_error / ConnectError` for instrument backfill snapshots between 13:46Z and 13:50Z (4-min outage). Currently quiescent. The 30 rows in `portfolio_value_snapshots` were written before the outage. **PRE-EXISTING + transient.**
10. **`content-store-consumer` 1,188 error lines** but actually fully caught up (lag=0 on every partition at sample time). Errors are **DNS `getaddrinfo: Name or service not known`** in a brief window after Postgres restarted at 18:53Z. Recovered. (Soft / transient.)
11. **OHLCV stale.** Latest `bar_date=2026-05-09T13:50Z` (~5h ago at audit time); 16 distinct instruments have any bar (was 16 in P3, no improvement). Of 57 instruments, 41 still have **zero** OHLCV bars (DIS, LLY, MA, MS, MSTR, NFLX, PFE, PG, PPA, QQQ, SHY, SPY, TLT, UNH, V, VOO, WMT, XLE, XLK, XOM and others). (HF-4 — same as D-P3-004.)
12. **Calendars still empty.** `earnings_calendar=0`, `economic_events=0`, `macro_indicators=0`, `yield_curve=0`, `insider_transactions=0`. The `kg-earnings-calendar-dataset-group` and friends are caught up (lag=0) — meaning the dataset envelope was consumed but the consumer either silently dropped writes or the source datasets were empty at fetch time. (HF-4 — same as D-P3-002/003.)

---

## 1. Postgres table matrix

Row counts via `pg_stat_user_tables`. Freshness via `MAX(created_at | generated_at | invoked_at | bar_date)`. "Expected?" = whether a writer should be populating it under live ingestion.

### 1.1 `intelligence_db` (KG / NLP shared)

| Table | Rows | Expected? | Latest ts | Diagnosis |
|-------|-----:|:---------:|-----------|-----------|
| `canonical_entities` | 330 | Y | recent | Growing (was 316 in P3, 277 baseline). Healthy. |
| `entity_aliases` | 785 | Y | — | Growing. Healthy. |
| `entity_embedding_state` | 721 | Y | — | Healthy. |
| `entity_narrative_versions` | **331** | Y | recent | **MAJOR PROGRESS** — was 0 in P3. NarrativeGenerationWorker is now firing for every entity with definition embedding. |
| `llm_usage_log` | **1,320** | Y | recent | Healthy growth (was 6 in P3). |
| `provisional_entity_queue` | 72 | Y on demand | — | **STUCK** — 60 `provisional_enrichment_error` events failing UPDATE on a non-existent column (`subject_provisional_id`). Rows never drain. → F-DPH-002 |
| `path_insight_jobs` | 9 | Y | — | All 9 jobs FAILED with `syntax error at or near "end"` (Cypher reserved keyword). → F-DPH-003 |
| `path_insights` | **0** | Y | — | Cascade of F-DPH-003. The Intelligence tab "paths" surface will be empty. |
| `relations` | **0** | Y | — | Cascade of D-P3-007 (still open). KG never grows. |
| `relation_evidence_raw` | **0** | Y | — | Cascade of D-P3-007. |
| `relation_evidence` | 0 (24 partitions, all 0) | Y | — | Cascade. |
| `relation_summaries` | 0 | Y | — | Cascade. |
| `relation_type_registry` | 27 | Y (seed) | — | Healthy. |
| `decay_class_config` | 6 | Y (seed) | — | Healthy. |
| `source_trust_weights` | 11 | Y (seed) | — | Healthy. |
| `prompt_templates` | 3 | Y (seed) | — | Healthy. |
| `path_templates` | 3 | Y (seed) | — | Healthy. |
| `claims` (24 partitions) | 0 each | Y | — | Cascade — no claim extraction has ever run. |
| `events` (24 partitions) | 0 each | Y | — | Cascade — no temporal events written. |
| `entity_event_exposures` | 0 | Y | — | Cascade. |
| `temporal_events` | 0 | Y | — | Cascade. |
| `outbox_events` | 331 (all `dispatched`) | Y | — | Healthy — no backlog. |
| `dead_letter_queue` | 0 | acceptable | — | Healthy. |
| `prompt_templates`, `model_registry`, `decay_class_config`, `path_templates`, `source_trust_weights` | seed tables | — | — | Populated. |
| `embedding_migration_state` | 0 | Y once | — | Migration not yet run; defer. |
| AGE labels (`worldview_graph.*`) | 0 across 30+ vertex/edge labels | Y | — | The AGE graph is **empty**. KG visualisation tab will show nothing past seed UUIDs. |

### 1.2 `nlp_db`

| Table | Rows | Expected? | Latest ts | Diagnosis |
|-------|-----:|:---------:|-----------|-----------|
| `document_source_metadata` | 579 | Y | 17:41Z (~1.5h) | **MAJOR PROGRESS** — was 513 (seed only). Live ingestion delivered ~66 docs in 17:00Z hour. But last 30 min: **0** new — Kafka consumer detached. → F-DPH-004 |
| `chunks` | 602 | Y | 17:41Z | OK. |
| `chunk_embeddings` | 598 | Y | 17:41Z | OK. |
| `chunk_entity_mentions` | 415 | Y | 17:41Z | OK (was 0 in P3). |
| `entity_mentions` | **415** | Y | 17:41Z | **MAJOR PROGRESS** — was 0 in P3. |
| `mention_resolutions` | **1,347** | Y | 17:41Z | **MAJOR PROGRESS**. |
| `routing_decisions` | **72** | Y | 17:41Z | **PROGRESS** — was 6 in P3, but 1 doc per ~7 routing decisions — fewer routings than docs because the consumer stalled before processing the rest. |
| `sections` | 579 | Y | — | OK. |
| `section_embeddings` | 66 | Y | — | OK. |
| `document_source_llm_scores` / `_latest` | 136 each | Y | — | RelevanceScoringWorker has run. OK. |
| `document_entity_stats` | 72 | Y | — | OK. |
| `llm_usage_log` | 236 | Y | 18:17Z | OK. |
| `article_impact_windows` | **0** | Y | — | PriceImpactLabellingWorker has never written. → see § 4 (price impact worker errors). |
| `embedding_pending` | 0 | acceptable | — | OK. |
| `dead_letter_queue` | 0 | OK | — | OK. |
| `outbox_events` | 90 (all `dispatched`) | Y | — | OK. |

### 1.3 `market_data_db`

| Table | Rows | Expected? | Latest ts | Diagnosis |
|-------|-----:|:---------:|-----------|-----------|
| `instruments` | 57 | Y | 17:20Z | OK. |
| `securities` | 57 | Y | — | OK. |
| `ohlcv_bars` | (TimescaleDB hypertable) 4,367 across 7 chunks | Y | bar_date 2026-05-09T13:50Z | 16 distinct instrument_ids — same set as P3 (8 equities + 8 crypto). 41 instruments have **0** bars. → cf. D-P3-004 (still open) |
| `fundamental_metrics` | 209,526 | Y | — | OK (47 distinct instruments). |
| `prediction_markets` | **500** | Y | — | **PROGRESS** — was 0 in P3. Catalog pulled. |
| `prediction_market_snapshots` | **0** | Y | — | **CONSUMER NOT ATTACHED** to `market.prediction.v1` — 15,777 messages waiting. → F-DPH-001 |
| `quotes` | 0 | Y | — | No live quote stream. |
| `earnings_calendar` | 0 | Y | — | Cascade of P3 D-P3-002. |
| `economic_events` | 0 | Y | — | Cascade of P3 D-P3-003. |
| `macro_indicators` | 0 | Y | — | P3 D-P3-003 cascade. |
| `yield_curve` | 0 | Y | — | P3 D-P3-003 cascade. |
| `insider_transactions` | 0 (snapshot=31) | Y | — | P3 D-P3-003 cascade — gold table empty even though snapshot has rows. |
| `daily_sentiments` | 0 | Y | — | Empty. Honest gap. |
| `outstanding_shares` | 0 | Y | — | Empty. |
| `market_cap_history` | 0 | Y | — | Empty. |
| Other fundamentals (income/cash_flow/balance/earnings_history) | 1.0k–8.2k each | Y | — | OK. |
| `splits_dividends`, `share_statistics`, `valuation_ratios`, `analyst_consensus`, `highlights` | 31 each | Y | — | OK (covers 31 of 47 fundamentals-instruments). |
| `failed_tasks` | 0 | OK | — | Centralised failure log unused — silent failures don't surface here. |
| `ingestion_events` | 987 | Y | 17:42Z | OK. |
| `outbox_events` | 47 (all `delivered`) | Y | — | OK. |
| `screen_field_metadata` | 0 | Y | — | **Empty** — Screener field metadata never seeded. Frontend Screener page (A9) may render with no field schema. |

### 1.4 `content_ingestion_db`

| Table | Rows | Expected? | Latest ts | Diagnosis |
|-------|-----:|:---------:|-----------|-----------|
| `sources` | **11** | Y | 17:14Z | **MAJOR PROGRESS** — was 0 in P3. 8 Finnhub-{ticker} + 2 NewsAPI + 1 Polymarket. |
| `article_fetch_log` | 1,529 | Y | recent | OK. |
| `content_ingestion_tasks` | 994 | Y | — | OK. |
| `prediction_market_fetch_log` | 16,306 | Y | — | OK — Polymarket adapter actively pulling. |
| `outbox_events` | 17,993 (all `delivered`) | Y | — | OK — but the very high count suggests the prediction market fetch produces an outbox row per snapshot per market — see F-DPH-001 (Kafka consumer absent on receiving side). |
| `tenant_document_uploads` | 6 | Y | — | OK. |
| `source_adapter_state` | 0 | Y | — | Sources never persisted last-cursor state. Adapters refetch from scratch every cycle (cost / dedup risk). |
| `dead_letter_queue` | 0 | OK | — | OK. |

### 1.5 `content_store_db`

| Table | Rows | Expected? | Diagnosis |
|-------|-----:|:---------:|-----------|
| `documents` | 1,096 | Y | OK. |
| `dedup_hashes` | 2,192 | Y | OK. |
| `minhash_signatures` | 1,096 | Y | OK. |
| `duplicate_clusters` | 0 | Y on dup | No dup clusters formed yet. |
| `minhash_entity_mentions` | 0 | Y | Empty — minhash not generating entity mentions. |
| `processed_events` | 0 | Y | **Empty** — `is_duplicate(event_id)` always returns False. Idempotency check never finds a match → consumer would re-process duplicates if the broker re-delivers. (Likely fine because every event_id IS a UUIDv7, but the table being empty after 1,066 outbox dispatches indicates the consumer never actually writes idempotency rows.) |
| `outbox_events` | 1,066 (all `delivered`) | Y | OK. |

### 1.6 `portfolio_db`

| Table | Rows | Diagnosis |
|-------|-----:|-----------|
| `users` | 1 | seed |
| `tenants` | 1 | seed |
| `portfolios` | 1 | seed |
| `holdings` | 5 | seed |
| `transactions` | 0 | empty — no brokerage sync ever ran |
| `brokerage_connections` | 0 | empty — Phase B B1 demo flow has never been exercised |
| `portfolio_value_snapshots` | 30 | OK |
| `watchlists` | 3 / `watchlist_members` 0 | empty members |
| `idempotency` | 47 | OK |
| `auth_audit_log`, `feature_*`, `nps_*`, `feedback_*`, `entity_suppressions`, `beta_enrollments`, `invitations`, `micro_survey_responses`, `alert_preferences`, `brokerage_sync_errors` | 0 | New tables; no events recorded. Demo doesn't depend on these. |

### 1.7 `rag_db`

| Table | Rows | Diagnosis |
|-------|-----:|-----------|
| `threads` | 34 | active sessions. OK. |
| `messages` | 68 | active. OK. |
| `llm_usage_log` | 1,166 | OK. |
| `user_briefs` | **1** | Only one morning brief ever generated. The dashboard A2 brief tile depends on this — fresh demo will need at least one fresh row. |
| `brief_feedback` | 0 | empty (no feedback path). |

### 1.8 `alert_db`

| Table | Rows | Diagnosis |
|-------|-----:|-----------|
| `alerts` | 2 | seed |
| `alert_subscriptions` | 0 | nobody subscribed |
| `alert_deliveries` | 0 | no alerts delivered |
| `email_log` | 0 | no email sent |
| `pending_alerts` | 0 | empty |
| `email_preferences` | 1 | seed |
| `outbox_events` | 2 (`dispatched`) | OK. |

### 1.9 `ingestion_db`

| Table | Rows | Diagnosis |
|-------|-----:|-----------|
| `ingestion_tasks` | 283 | active scheduler. OK. |
| `ingestion_watermarks` | 399 | OK. |
| `polling_policies` | 424 | OK. |
| `provider_budgets` | 2 | OK. |
| `symbol_tiers` | 0 | empty — tier-aware throttling never activated; relevant if demo crosses budget caps. |
| `outbox_events` | 280 (`published`) | OK. |

### 1.10 `kg_db`, `gateway_db`

Both have only metadata tables (kg_db: AGE catalog with 0 rows; gateway_db: only public schema and no user tables). Expected — kg_db is reserved for AGE legacy; gateway is stateless.

---

## 2. Kafka topic matrix

Producer count not directly visible in CLI; deduced from "topic has any messages at all" and grep on producer code paths.

| Topic | Producer? | Consumer | LAG (max) | Last total | Subject? | Diagnosis |
|-------|:----------|:---------|----------:|-----------:|:---------|-----------|
| alert.created.v1 | Y | (none — output side) | — | 2 | Y | OK — emitted but no internal consumer; subscribed by frontend WS via S10 |
| alert.delivered.v1 | Y | — | — | 0 | Y | Empty — no alerts delivered yet |
| content.article.raw.v1 | Y | content-store-consumer | 0 (caught up) | 1,493 | Y | OK — but had transient DNS errors at 18:53Z post-Postgres-restart (recovered). |
| content.article.stored.v1 | Y | nlp-pipeline-group | **~970** | 1,095 | Y | **F-DPH-004** — consumer detached (CONSUMER-ID `-` on every partition). |
| entity.canonical.created.v1 | (Y, none currently) | kg-service-group-entity | 0 | 0 | Y | OK — no events being produced; consumer idle but attached. |
| entity.dirtied.v1 | Y | (none — used for embedding refresh) | — | 0 | Y | Empty — no dirty events yet. |
| entity.narrative.generated.v1 | Y | (none) | — | 330 | Y | NarrativeGenerationWorker is firing! 330 events. No consumer attached but topic exists. |
| entity.provisional.queued.v1 | Y | kg-provisional-queued-group | 0 | 16 | Y | Caught up. |
| graph.state.changed.v1 | (none) | alert-service-group | 0 | 0 | Y | Empty. |
| intelligence.contradiction.v1 | (none) | alert-service-group | 0 | 0 | Y | Empty. |
| intelligence.temporal_event.v1 | Y | kg-service-group-temporal-event | **lag UNKNOWN** (CURRENT-OFFSET=`-`) | 3 | Y | Consumer never assigned a partition. 3 messages stuck. |
| market.dataset.fetched | Y | kg-* (5 groups), market-data-* (4 groups) | 0–2 | 280 | Y | OK — most groups caught up, kg-economic-events has lag 2 on partition 4. |
| market.instrument.created | Y | kg-service-group-instrument, portfolio-instrument-sync | 0 | 39 | Y | OK. |
| market.instrument.discovered.v1 | Y | kg-service-group-instrument-discovered, portfolio-instrument-sync | 0 | 8 | Y | OK. |
| market.instrument.updated | Y | portfolio-instrument-sync | 0 | 0 | Y | Empty (no instrument updates emitted). |
| market.prediction.v1 | Y | market-data-prediction-markets | **15,777** | 16,500 | Y | **F-DPH-001** — consumer DETACHED. Producer (Polymarket adapter) actively writing 16,500 records, **0** in `market_data_db.prediction_market_snapshots`. |
| nlp.article.enriched.v1 | Y | kg-service-group-enriched | 0–2 | 72 | Y | KG enriched-consumer **commits offsets despite SQL error** (D-P3-007); zero KG writes. |
| nlp.document.ready.v1 | Y | content-ingestion document_ready_consumer | 0 | 6 | Y | OK. |
| nlp.signal.detected.v1 | (sparse) | alert-service-group | 0 | 9 | Y | OK. |
| portfolio.events.v1 | (none) | (none active) | — | 0 | Y | Empty. |
| portfolio.watchlist.updated.v1 | (none) | nlp-watchlist-group, alert-service-watchlist-group | 0 | 0 | Y | OK. |
| relation.type.proposed.v1 | (none) | (none active) | — | 0 | Y | Empty. |
| `*.dead-letter.v1` (5 topics) | (none) | (none) | — | 0 each | n/a (DLQ envelope, no avsc) | All 5 DLQ topics are empty. Healthy. |

### Schema Registry coverage

26 subjects registered. **All 22 active topics have a matching `*-value` subject.** 4 subjects have no Kafka topic yet (`alert.email.sent.v1`, `content.document.deleted.v1`, `entity.narrative.generated.v1` — actually has 330 messages! topic exists, sample query above confirms; subject mapping is fine, `auto.create.topics.enable=true`). **No R5 gaps.**

Two cosmetic drift cases (carried from P2 audit, INFO):
- `watchlist.item_added-value` record `name = "item_added"` (lowercase, no `Watchlist` prefix).
- `watchlist.item_added-value` and `watchlist.item_deleted-value` subjects lack the `.v1` suffix — pre-PLAN-0062 legacy.

---

## 3. Container log summary (last 6 h)

| Container | Restart | ErrLines | Top error pattern | Action |
|-----------|--------:|---------:|-------------------|--------|
| `worldview-knowledge-graph-path-insight-worker-1` | **4** | 31 | `path_insight_worker_fatal_error` ([Errno -2] DNS) + `path_insight_job_failed` (Cypher syntax error at "end") | **F-DPH-003 — fix Cypher** |
| `worldview-content-store-consumer-1` | 0 | 1,188 | `kafka_unexpected_error` `[Errno -2] Name or service not known` (DNS post Postgres restart 18:53Z) | Transient — but log rate suggests no exponential backoff. Add backoff. |
| `worldview-content-ingestion-worker-1` | 0 | 690 | `default_db_credentials_detected` warning (production gate) + intermittent finnhub fetches | INFO; warning is for prod, fine in dev. No real errors at error-level. |
| `worldview-portfolio-snapshot-worker-1` | 0 | 900 | `ohlcv_price_fetch_error` ConnectError | Transient (single 4-min outage at 13:46-13:50Z). Resolved. |
| `worldview-market-data-1` | 0 | 360 | `404 GET /api/v1/instruments/symbol/META` (also AAPL, etc.) | **F-DPH-005 — symbol lookup endpoint 404 for known instruments** |
| `worldview-knowledge-graph-enriched-consumer-1` | 0 | 167 | `evidence_source_metadata_lookup_failed` UndefinedTableError + `kafka_unexpected_error` InFailedSQLTransactionError | **D-P3-007 — STILL OPEN** |
| `worldview-knowledge-graph-scheduler-1` | 0 | 100 | `provisional_enrichment_error` UndefinedColumnError `subject_provisional_id` (60×) | **F-DPH-002** |
| `worldview-postgres-1` | 0 | 122 | (transient log spam during restart at 18:53Z) | Transient. |
| `worldview-nlp-pipeline-1` | 0 | 94 | `unhandled_error` `EmbeddingClient is required` (5×) + entity_resolve_request requests | **F-DPH-006 — chunk search 500** |
| `worldview-schema-registry-1` | 0 | 45 | (Kafka producer disconnects during initial bootstrap — recovered) | Transient. |
| `worldview-rag-chat-1` | 0 | 36 | `execute_sync_error_event` (30) + `all_tools_failed` (29) + `upstream_http_error` (24) + `internal_jwt_unverified_decode` (53) | **F-DPH-007 + F-DPH-008** |
| `worldview-knowledge-graph-provisional-queued-consumer-1` | 0 | 34 | unknown — likely cascaded F-DPH-002 | Likely same as F-DPH-002 |
| `worldview-alert-dispatcher-1` | 0 | 28 | (low-rate; not investigated — non-critical for demo) | INFO |
| `worldview-nlp-pipeline-dispatcher-1` | 0 | 27 | (non-critical) | INFO |
| `worldview-market-ingestion-dispatcher-1` | 0 | 26 | (non-critical) | INFO |
| `worldview-knowledge-graph-economic-events-dataset-consumer-1` | 0 | 15 | (non-critical) | INFO |
| `worldview-kafka-1` | 0 | 15 | (broker startup chatter) | INFO |
| `worldview-market-ingestion-worker-1` | 0 | 13 | (non-critical) | INFO |
| `worldview-ollama-1` | 0 | 11 | (model load) | INFO |
| `worldview-knowledge-graph-temporal-event-consumer-1` | 0 | 10 | (non-critical) | INFO |
| All others | 0 | 0–10 | benign | OK |

**Restart-loop alarm**: only path-insight-worker has restartCount>0. **4 restarts in 6 h** is borderline — combination of post-restart DNS losses and the Cypher bug. Once F-DPH-003 lands, expect this to drop to 0.

---

## 4. F-NNN findings — action-needed items

```yaml
- id: F-DPH-001
  va: VA-9 / VA-7
  surface: A2 (dashboard prediction-markets tile), A6 (chat over predictions)
  severity: HF-4
  status: open
  agent: data-plane-health
  found_at: 2026-05-09T19:15Z
  reproduce: |
    docker exec worldview-kafka-1 kafka-consumer-groups \
      --bootstrap-server localhost:9092 \
      --describe --group market-data-prediction-markets
    → 8 partitions, every row CONSUMER-ID `-`, total LAG 15,777 / LOG-END-OFFSET 16,500.
    docker exec worldview-postgres-1 psql -U postgres -d market_data_db \
      -c "SELECT COUNT(*) FROM prediction_market_snapshots;"
    → 0
    docker logs worldview-market-data-prediction-market-consumer-1 --tail 10
    → no recent activity (1 errLine in 6h)
  evidence:
    - market.prediction.v1 has 16,500 messages produced
    - 0 rows in prediction_market_snapshots
    - prediction_markets table has 500 rows (catalog only, not snapshots)
    - the prediction-market-consumer container is "healthy" but its rdkafka
      client is not in any active rebalance group
  root_cause: |
    Either: (a) the consumer process inside `worldview-market-data-prediction-market-consumer-1`
    is not subscribing on startup; (b) it crashed silently; (c) its consumer-group config
    differs from what's actually being committed in the broker.
    Tail of the container is sparse — needs `docker logs --since 24h` on first failure path.
    SUSPECTED: BaseKafkaConsumer.subscribe() ordering bug (memory: BP-407) re-introduced after
    PLAN-0076 W6 / Sub-Plan B Kafka backpressure refactor.
  fix_decision: TBD  # likely fix-now (restart + log inspection); escalate if still detached.

- id: F-DPH-002
  va: VA-3
  surface: cross-cutting (KG entity dedup; Intelligence tab)
  severity: HF-3
  status: open
  agent: data-plane-health
  found_at: 2026-05-09T19:15Z
  reproduce: |
    docker logs worldview-knowledge-graph-scheduler-1 --since 6h | grep provisional_enrichment_error
    → 60 occurrences with:
      asyncpg.exceptions.UndefinedColumnError: column "subject_provisional_id" does not exist
      [SQL: UPDATE relation_evidence_raw
            SET entity_provisional = false,
                subject_entity_id = CASE WHEN subject_provisional_id = $1 THEN $2 ELSE subject_entity_id END,
                object_entity_id  = CASE WHEN object_provisional_id  = $1 THEN $2 ELSE object_entity_id  END
            WHERE (subject_provisional_id = $1 OR object_provisional_id = $1)
              AND entity_provisional = true]
    docker exec worldview-postgres-1 psql -U postgres -d intelligence_db \
      -c "\\d relation_evidence_raw" | grep -i provisional
    → confirm subject_provisional_id is NOT a column on relation_evidence_raw.
  evidence:
    - 60 errors in 6h, all identical
    - provisional_entity_queue has 72 stuck rows
  root_cause: |
    `ProvisionalEnrichmentRetryUseCase` in services/knowledge-graph references columns
    `subject_provisional_id` / `object_provisional_id` that were either never added or
    were renamed. The `relation_evidence_raw` shape probably uses `subject_entity_id`
    + a separate `entity_provisional` boolean flag, with no parallel `*_provisional_id`
    column. Likely a leftover column reference from PLAN-0072 KG dedup work after a rename.
  fix_decision: TBD  # likely fix-now (rewrite the UPDATE to filter on entity_provisional flag
                     # + match on subject_entity_id instead of subject_provisional_id), or add
                     # the missing columns via migration if the design intended them.

- id: F-DPH-003
  va: VA-2
  surface: A4 (Intelligence tab — paths)
  severity: HF-3
  status: open
  agent: data-plane-health
  found_at: 2026-05-09T19:15Z
  reproduce: |
    docker logs worldview-knowledge-graph-path-insight-worker-1 --tail 10
    → repeating PostgresSyntaxError: syntax error at or near "end"
    SQL: SELECT ... FROM ag_catalog.cypher('worldview_graph', $$
      MATCH p=(start:entity {entity_id: $id})-[*2..5]-(end:entity)
      WHERE id(start) <> id(end)
      ...
    $$, $1) AS (...)
    Cause: `end` is a reserved keyword in Cypher (along with `start`, but openCypher
    tolerates `start`); `end` rejected by AGE/openCypher parser.
    docker inspect worldview-knowledge-graph-path-insight-worker-1 --format '{{.RestartCount}}'
    → 4
  evidence:
    - 27 path_insight_jobs all FAILED
    - path_insights table has 0 rows
    - container has restarted 4 times (DNS losses + crashes)
  root_cause: |
    Code in services/knowledge-graph/src/.../path_insights.py uses unquoted `end`
    as the variable name in the MATCH pattern. Must be renamed to `target` /
    `finish` / `node_b`, or quoted as `\`end\`` (graph-name-style backticks
    don't work for variable names in openCypher).
  fix_decision: TBD  # 1-line fix in the Cypher template; small reach.

- id: F-DPH-004
  va: VA-3
  surface: cross-cutting (NLP pipeline throughput)
  severity: HF-3
  status: open
  agent: data-plane-health
  found_at: 2026-05-09T19:15Z
  reproduce: |
    docker exec worldview-kafka-1 kafka-consumer-groups \
      --bootstrap-server localhost:9092 --describe --group nlp-pipeline-group
    → 9 partitions visible (only those with offsets), all CURRENT-OFFSET frozen at
      a few-tens, LOG-END-OFFSET ~80-128 each, total LAG ≈ 970, CONSUMER-ID `-`.
    docker exec worldview-postgres-1 psql -U postgres -d nlp_db -tAc \
      "SELECT COUNT(*) FROM document_source_metadata WHERE created_at > NOW() - INTERVAL '30 minutes';"
    → 0
    docker logs worldview-nlp-pipeline-1 --since 1h | grep -iE "kafka|consumer|article_consumer"
    → empty (no consumer-side log lines since service started at 18:15Z)
    BUT the FastAPI service is healthy and processing `entity_resolve_request`.
  evidence:
    - 1,095 articles in content.article.stored.v1 (deduped), only ~125 ever consumed
      (CURRENT-OFFSET sum across visible partitions)
    - 0 new docs persisted in last 30 min
    - nlp-pipeline-1 service reports healthy via /readyz; the embedded
      ArticleStoredConsumer has stopped polling
  root_cause: |
    The article-consumer is embedded in worldview-nlp-pipeline-1 (no separate
    container in current docker-compose). On service-restart at 18:15Z, the
    consumer task either failed to subscribe or its background task crashed
    without restarting. Suspected:
    - Same cooperative-sticky / static-membership pattern as P3 D-P3-006
    - Or the consumer was disabled by a config flag (NLP_PIPELINE_ARTICLE_CONSUMER_ENABLED?)
      after the embedding-client refactor that broke search/chunks (F-DPH-006)
  fix_decision: TBD  # diagnose first (logs, env), then fix-now restart with verification.

- id: F-DPH-005
  va: VA-1 (chat tool routing) + VA-5 (instrument page)
  surface: A4 instrument page, A6 chat "What is the price of AAPL?"
  severity: HF-1 / HF-6
  status: open
  agent: data-plane-health
  found_at: 2026-05-09T19:15Z
  reproduce: |
    curl -fsS http://localhost:8000/api/v1/instruments/symbol/AAPL  # via api-gateway
    OR look at: docker logs worldview-market-data-1 --since 6h | grep "404"
    → many `INFO 172.20.0.15:51418 - "GET /api/v1/instruments/symbol/META HTTP/1.1" 404 Not Found`
    AND `... AAPL ... 404`.
    AAPL exists in market_data_db.instruments (and securities) so this is a routing/case
    or schema mismatch, not a missing record.
  evidence:
    - market_data_db.instruments has AAPL/MSFT/META rows
    - the symbol-resolve endpoint at `/api/v1/instruments/symbol/{sym}` returns 404
    - rag-chat tool `get_price_history` for AAPL fails because of this 404 cascade
    - 29 occurrences of "all_tools_failed" in rag-chat
  root_cause: |
    Either:
    - Endpoint case-sensitivity bug (looks for lowercase "aapl" while DB has "AAPL")
    - Tenant/multi-tenant filter (PLAN-0086) added after rag-chat sample tenant header
      and rag-chat is not passing tenant_id properly through the JWT
    - The endpoint moved to a different path (e.g., `/securities/symbol/{sym}` or
      `/instruments/by-symbol/{sym}`) and the rag-chat tool catalog wasn't updated.
    Confirm: SELECT symbol FROM instruments WHERE upper(symbol)='AAPL'; vs the
    endpoint behaviour.
  fix_decision: TBD  # high leverage — unblocks the entire Phase A6/A7 chat demo.

- id: F-DPH-006
  va: VA-4
  surface: A4 (chunk search backing the News tab) + chat retrieval substrate
  severity: HF-1
  status: open
  agent: data-plane-health
  found_at: 2026-05-09T19:15Z
  reproduce: |
    docker logs worldview-nlp-pipeline-1 --since 6h | grep "EmbeddingClient is required"
    → 5 occurrences
    All 500 responses on POST /api/v1/search/chunks when query_text is provided
    without query_embedding (the canonical caller from rag-chat).
    File: services/nlp-pipeline/src/nlp_pipeline/application/use_cases/enhanced_chunk_search.py:565
  evidence:
    - service_started event followed by api_embedding_client_ready event at startup,
      yet at request time _resolve_embedding receives client=None and raises
    - 5 unhandled_error events
    - Hybrid retrieval (PLAN-0084 / PLAN-0063) entirely broken when caller does not
      precompute the embedding
  root_cause: |
    Likely a DI wiring regression: the EmbeddingClient is constructed at startup
    (logged ready) but the use-case dependency-graph instantiates a different
    instance (None) — perhaps because the use-case binds to the request scope
    rather than the app scope, and the request-scope provider returns None when
    DEEPINFRA_API_KEY env var is not set or is empty.
    Cross-reference: BP-179 (pydantic-settings empty SecretStr handling).
  fix_decision: TBD  # critical for retrieval; investigate config + DI wiring.

- id: F-DPH-007
  va: VA-1 (chat tools)
  surface: A6 chat — tool-call answers
  severity: HF-1 / HF-6
  status: open
  agent: data-plane-health
  found_at: 2026-05-09T19:15Z
  reproduce: |
    POST /v1/chat with body: {"messages":[{"role":"user","content":"What is the price of AAPL?"}]}
    → 503 Service Unavailable
    docker logs worldview-rag-chat-1 --since 6h | grep all_tools_failed
    → "tool_count":1,"tools":["get_price_history"],"query":"What is the price of AAPL?"
    → "execute_sync_error_event" 30 occurrences
    → "upstream_http_error" 24 occurrences (mostly 404 on instruments/symbol/{sym}, 401 on
       /v1/fundamentals/earnings-calendar)
  evidence:
    - rag-chat invokes one tool, the tool fails, and rag-chat returns 503 to the gateway
    - the underlying tool failures are F-DPH-005 (symbol 404) and a 401 on
      fundamentals/earnings-calendar (auth pass-through bug)
  root_cause: |
    Compound: F-DPH-005 (symbol 404) + auth-passthrough bug for upstream calls
    (rag-chat does not propagate the user's internal JWT to S2/market-data).
    Also rag-chat returns 503 on first tool failure rather than retrying or asking
    the LLM to recover — but the upstream issue must land first.
  fix_decision: TBD  # blocked-by F-DPH-005; then add tool-error recovery story.

- id: F-DPH-008
  va: SEC-002 follow-up
  surface: Cross-cutting (auth)
  severity: SF-3 (HF if production)
  status: open
  agent: data-plane-health
  found_at: 2026-05-09T19:15Z
  reproduce: |
    docker logs worldview-rag-chat-1 --since 6h | grep internal_jwt_unverified_decode
    → 53 occurrences
  evidence:
    - rag-chat receives X-Internal-JWT but logs `internal_jwt_unverified_decode`
      meaning it is using `jwt.decode(..., options={"verify_signature": False})`
      OR it's not configured with the JWKS URL.
  root_cause: |
    Either rag-chat InternalJWTMiddleware is not yet wired to fetch /internal/jwks
    from api-gateway (R23 / PRD-0025 wave gap), or the public-key fetch failed at
    startup and the middleware fell back to unverified decode (security regression).
    Per CLAUDE.md / RULES, internal JWT MUST be verified.
  fix_decision: TBD  # demo can run unverified for local dev, but a hedge-fund-grade
                     # demo asking about security posture would not survive scrutiny.

- id: F-DPH-009
  va: VA-3
  surface: pipeline observability
  severity: SF-3
  status: open
  agent: data-plane-health
  found_at: 2026-05-09T19:15Z
  reproduce: |
    docker exec worldview-postgres-1 psql -U postgres -d content_store_db -tAc \
      "SELECT COUNT(*) FROM processed_events;"
    → 0  # despite content-store-consumer having committed 1,095 article-stored events
  evidence:
    - processed_events should grow by 1 per consumed event (idempotency record)
    - 0 rows means the consumer never persists idempotency keys
  root_cause: |
    BP-064 candidate: `content-store-consumer.is_duplicate(event_id)` queries the
    table but no companion writer call records the event_id post-success. If
    the broker re-delivers an event due to rebalance, content-store will reprocess
    it → potential duplicate documents (deduped by minhash for now, but observability
    is broken).
  fix_decision: TBD  # not a demo blocker; noteworthy hardening gap.

- id: F-DPH-010
  va: VA-9
  surface: A9 (Screener page)
  severity: HF-4
  status: open
  agent: data-plane-health
  found_at: 2026-05-09T19:15Z
  reproduce: |
    docker exec worldview-postgres-1 psql -U postgres -d market_data_db -tAc \
      "SELECT COUNT(*) FROM screen_field_metadata;"
    → 0
  evidence:
    - Screener UI (PRD-0027 12-col grid) needs field metadata to render headers + filters
    - Empty table means UI either falls back to hardcoded fields or shows nothing
  root_cause: |
    Seed never ran for screen_field_metadata. Possibly added in PLAN-0070 BFF
    work without a seed migration.
  fix_decision: TBD  # frontend will tell us if it has hardcoded fallback; if not, fix-now.

- id: F-DPH-011
  va: cross-cutting
  surface: pipeline (KG enriched-consumer commit-on-error)
  severity: SF-3 (architectural)
  status: open
  agent: data-plane-health
  found_at: 2026-05-09T19:15Z
  reproduce: |
    docker logs worldview-knowledge-graph-enriched-consumer-1 --since 6h | grep enriched_article_processed
    → 9 entries, every one with relations=0, evidence=0, events=0, claims=0
    → All are paired with an earlier evidence_source_metadata_lookup_failed
  evidence:
    - The consumer logs error then logs "enriched_article_processed" with all-zeros
    - Kafka offset is committed → message is "successfully consumed" from the broker's view
  root_cause: |
    The enriched-consumer's process_message catches the SQL transaction abort,
    logs it as a warning, returns success, and commits the offset. This combines
    with D-P3-007 to silently destroy 100% of KG ingestion. R28 / "no silent
    drops" architectural rule violated. Consumer should NOT commit offset when
    the use-case returns 0 writes alongside an SQL error.
  fix_decision: TBD  # blocked-by D-P3-007 root-cause fix; then revisit commit policy.
```

---

## 5. Cross-reference with prior audits

- **D-P3-007** (KG enriched-consumer cross-DB SQL bug): **STILL OPEN**, observed live in this audit. Highest leverage carry-over. Pair with **F-DPH-011** (silent commit-on-error).
- **D-P3-001** (Polymarket prediction markets): **PARTIALLY RESOLVED** — catalog is now populated (500 rows in `prediction_markets`); sources table has Polymarket entry; producer is firing 16,500 messages. **F-DPH-001** is the new blocker (consumer detached).
- **D-P3-002 / D-P3-003** (calendars empty): **STILL OPEN** — every dataset consumer caught up but gold tables remain empty. The dataset envelopes likely contain empty arrays.
- **D-P3-006** (NLP article consumer wedged 6/12 partitions): **WORSE** — now 0/12 partitions assigned. Captured as **F-DPH-004**.
- **D-P3-007** ↔ **F-DPH-011**: same root cause, second symptom.
- **D-P3-009** (KG dataset consumer partial assignment): **RESOLVED** — all dataset consumers now own all 6 partitions and are caught up.
- **D-P3-010** (sources empty): **RESOLVED** — sources table has 11 rows.
- **D-P3-008** (entity narratives, path insights, relation summaries empty): **PARTIALLY RESOLVED** — `entity_narrative_versions=331` (was 0). `path_insights=0` (now blocked on F-DPH-003 instead of D-P3-007). `relation_summaries=0` still cascade of D-P3-007.
- **D-P2-001** (content-store-consumer lag): **RESOLVED** — caught up to 0 lag.

---

## 6. Recommended Wave-D triage priority

For the fix phase, ordered by demo-path leverage and time-to-fix:

1. **F-DPH-005** (symbol-lookup 404) — ≤30 min single-file fix; unblocks **F-DPH-007** (chat tool catalog).
2. **D-P3-007** + **F-DPH-011** (KG enriched-consumer) — ≤2 h; unblocks the entire intelligence layer (relations, events, claims, narratives).
3. **F-DPH-001** (prediction-markets consumer detached) — ≤1 h diagnostic + restart; unblocks dashboard A2 tile.
4. **F-DPH-004** (NLP article consumer detached) — ≤1 h restart + verify; restores live ingestion throughput.
5. **F-DPH-003** (path-insight Cypher syntax) — 1-line fix; unblocks Intelligence-tab paths sub-surface.
6. **F-DPH-002** (provisional enrichment column missing) — ≤2 h; investigate schema vs UPDATE intent.
7. **F-DPH-006** (EmbeddingClient None) — ≤1 h DI wiring fix; restores hybrid retrieval.
8. **F-DPH-008** (rag-chat unverified-decode) — ≤30 min config or middleware fix.
9. **F-DPH-010** (screener metadata seed) — depends on frontend fallback presence.
10. **D-P3-002 / D-P3-003** (calendars) — needs dataset envelope inspection; defer past triage.
11. **D-P3-004** (OHLCV missing instruments) — backfill enqueue script; ≤2 h.

---

## 7. Diagnostic SQL bundle (re-validation after fixes)

```sql
-- 1. Polymarket consumer health
SELECT COUNT(*) AS snapshots, MAX(snapshot_at) FROM market_data_db.public.prediction_market_snapshots;
-- Expected after F-DPH-001: snapshots > 1000 within 2 h.

-- 2. NLP throughput resumed
SELECT COUNT(*) FROM nlp_db.public.document_source_metadata WHERE created_at > NOW() - INTERVAL '15 minutes';
SELECT COUNT(*) FROM nlp_db.public.routing_decisions WHERE decided_at > NOW() - INTERVAL '15 minutes';
-- Expected after F-DPH-004: both > 0.

-- 3. KG growth
SELECT COUNT(*) FROM intelligence_db.public.relation_evidence_raw;
SELECT COUNT(*) FROM intelligence_db.public.relations;
-- Expected after D-P3-007 fix: > 0 within 30 min.

-- 4. Path insights
SELECT COUNT(*) FROM intelligence_db.public.path_insights;
-- Expected after F-DPH-003 fix: > 0 within 5 min.

-- 5. Provisional queue draining
SELECT COUNT(*) FROM intelligence_db.public.provisional_entity_queue;
-- Expected after F-DPH-002 fix: shrinking from 72 toward 0.

-- 6. Symbol lookup
-- Run against the gateway:  curl http://localhost:8000/api/v1/instruments/symbol/AAPL
-- Expected after F-DPH-005: 200 with JSON payload.
```

---

## 8. Key file paths surfaced (absolute)

- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_evidence.py:112` — D-P3-007 origin (UndefinedTableError query).
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/enriched_consumer.py:250,269` — silent-commit-on-error logic (F-DPH-011).
- `services/knowledge-graph/src/knowledge_graph/application/blocks/canonicalization.py:125` — second-stage failure path after relation_type_registry lookup is poisoned by aborted txn.
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_type_registry.py:31` — re-issue point for aborted txn.
- `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/enhanced_chunk_search.py:241,565` — F-DPH-006 EmbeddingClient None.
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/search.py:41` — F-DPH-006 entry point.
- Path-insight worker Cypher template (F-DPH-003) — exact path needs grep but the Cypher pattern `MATCH p=(start:entity ...)-[*2..5]-(end:entity)` is unique enough to locate; likely under `services/knowledge-graph/src/knowledge_graph/application/path_insight_worker.py` or similar.

**End of data-plane health audit.**
