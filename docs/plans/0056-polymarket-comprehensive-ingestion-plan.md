---
id: PLAN-0056
title: "Prediction Markets: Activation, Signals & Enrichment (Wave 2)"
prd: PRD-0033
status: completed
created: 2026-05-01
updated: 2026-07-10
supersedes: PLAN-0056 (original ingestion-first draft, withdrawn 2026-07-09)
branch: feat/prediction-data-activation
---

# PLAN-0056 — Prediction Markets: Activation, Signals & Enrichment (Wave 2)

## Overview

PRD: [PRD-0033](../specs/0033-polymarket-comprehensive-ingestion.md) ·
Investigation: [2026-07-09](../audits/2026-07-09-prediction-data-enhancement-investigation.md)

**Services**: S3 market-data (extend — owns prediction storage), S4 content-ingestion (4 adapters +
synthetic-doc emitter), S6 nlp-pipeline (UNCHANGED — reused via synthetic docs), S7 knowledge-graph
(PREDICTION temporal events + exposures + polarity + signal emit), alert (prediction signal subtype
via existing fanout), S9 api-gateway (read + brief leg), worldview-web (page + chat), plus
libs/messaging + libs/contracts + libs/prompts + intelligence-migrations.

**Total: 6 sub-plans, 20 waves.** Keystone = Sub-Plan C (KG linking); signals (D) depend on it.
(Wave B4 added 2026-07-10 as a corrective wave under Sub-Plan B.)

### Model decisions from recon (2026-07-09) — supersede PRD first-draft wording (reconcile in /revise-prd)

1. **Markets are `temporal_events(event_type='prediction')`, NOT new canonical entities.** Mirrors the
   shipped `EarningsCalendarDatasetConsumer` (CORPORATE) pattern exactly. Referenced entities are
   **existing** canonical entities. No `EntityType.prediction_market`, no `canonical_entities`
   CHECK widening, no 30k entity-node bloat. (PRD §6.2 "new entity types" → withdrawn.)
2. **Market↔entity link = `entity_event_exposures`** (one row per referenced entity), created by a new
   S7 consumer from the NER-enriched synthetic doc. **Polarity lives on the exposure** (new columns),
   because the hot `relations` table has no metadata/JSONB column (only `contra_count_by_type`) and
   its polarity is on `relation_evidence_raw`. (PRD §6.3 "polarity on references relation" → polarity
   on exposure.)
3. **Signals reuse the existing alert fanout.** `AlertFanoutUseCase` already gates on the watchlist
   (= our "tracked entity" gate), classifies severity from `market_impact_score`, dedups, and
   delivers. S3 emits raw moves (`market.prediction.move.v1`); S7 joins to exposures + polarity and
   emits `market.prediction.signal.v1`; alert `IntelligenceConsumer` subscribes to it. Minimal alert
   change (topic subscription + field map + `prediction` alert/rule type).
4. **Gateway namespace stays `/v1/signals/prediction-markets/*`** (shipped) — extend it; do NOT
   introduce a parallel `/v1/predictions/*`. (PRD §11 path → align to shipped namespace.)

### Verified Alembic HEADs (2026-07-09, filesystem-authoritative)
| Service | HEAD file | rev id | next |
|---|---|---|---|
| market-data | `042_vacuum_analyze_screener_tables.py` | `042` (down `041`) | **043** |
| content-ingestion | `0010_sec_edgar_cik_watchlist.py` | `0010_sec_edgar_cik_watchlist` (down `0009_...`) | **0011** |
| intelligence-migrations | `0065_seed_non_us_private_entities.py` | `0065` (down `0064`) | **0066** ⚠️ |
| alert | `0010_create_alert_rules.py` | `0010` (down `0009`) | **0011** |

> ⚠️ intelligence-migrations **0066 collision risk**: a `0066_parked_predicate` exists on the unmerged
> `feat/kg-relation-proposals` branch (memory KG-relation-growth-loop). If that branch merges first,
> renumber this plan's migration to the next free integer and re-chain `down_revision`. Verify HEAD
> again at implement time (R32).

## Dependency graph (execution order)

```
Z (contracts+topics) ──┬──► A (S3 storage+consumers) ──┐
                       └──► B (S4 adapters+synth-doc) ──┤
                                        │ (synth docs → S6 NER, unchanged)
                                        ▼
                              C (S7 KG linking + polarity)  ◄── KEYSTONE
                                        │
                          ┌─────────────┴─────────────┐
                          ▼                           ▼
              D (signals: S3 move → S7 signal → alert)   E (S9 + frontend + chat)
```

Z → {A, B} → C → {D, E}. A and B run in parallel (worktrees). D and E run in parallel after C.

## Codebase-state delta table (from 5-area recon — all values read from code)

| PRD ref | Type | Svc | Current state (verified) | Target | Delta |
|---|---|---|---|---|---|
| `prediction_markets` / `_snapshots` | tables | S3 | EXIST; `_snapshots` is TimescaleDB hypertable on `snapshot_at`; `liquidity` stored | keep; add `event_id` col | small |
| `liquidity` on API | field | S3 | stored on snapshot, **absent** from `SnapshotPointResponse`/summary/detail | expose | schema add |
| `prediction_market_prices/_trades/_oi/_events` | tables | S3 | do not exist | NEW (mirror snapshot hypertable) | migration 043 |
| `market.prediction.{history,event,trade,oi,move,signal}.v1` | topics/Avro | Z | do not exist | NEW ×6 | schemas+topics |
| Polymarket adapters (events/CLOB/trades/OI) | adapters | S4 | only Gamma `/markets` (`PolymarketAdapter`) | NEW ×4 (copy pattern) | impl |
| `SyntheticDocumentEmitter` | class | S4 | does not exist; `content.article.raw.v1` produced by `build_raw_article_payload` | NEW | impl |
| `ContentSourceType.POLYMARKET_*` | enum | libs/contracts | only `POLYMARKET` | +4 values | enum |
| `EventType.PREDICTION` | enum | S7 | `EventType` has CORPORATE (migration 0018); no PREDICTION | +1 + CHECK widen | migration 0066 |
| `entity_event_exposures.polarity` | column | S7 | table exists (earnings uses it); no polarity col | +`polarity`,`polarity_confidence` | migration 0066 |
| `EntityType.prediction_market` | enum | S7 | **N/A** — entity kinds are a DB CHECK (11 kinds), not a Python enum | **NOT ADDED** (temporal-event model) | none |
| `nlp.signal.detected.v1` fanout | flow | alert | `IntelligenceConsumer` subscribes 3 topics; `AlertFanoutUseCase` gates on watchlist, severity from `market_impact_score`, has `polarity` | subscribe `market.prediction.signal.v1`; `prediction` alert/rule type | topic+enum+migration 0011 |
| `/v1/signals/prediction-markets/*` | routes | S9 | 4 routes proxy S3 (`intelligence.py:1546`) | +history-interval/trades/events/liquidity + `/entities/{id}/predictions` + brief leg | impl |
| `/prediction-markets` page + widget | UI | web | list+sparkline+filters (`recharts@3.8.1` avail; `EarningsBarChart` pattern) | +chart/groupings/chips/badges/detail | impl |
| `get_prediction_markets` grounding | handler | rag-chat | `handlers/market.py:2555` builds `RetrievedItem` **without** `grounding_fields` | add odds grounding_fields | impl |

## Name-verification (BP-405) — key targets

**Existing (verified, callable):** `PolymarketAdapter`/`PolymarketClient`, `FetchAndWritePredictionMarketsUseCase`,
`build_raw_article_payload`, `PredictionMarket{,Snapshot}Repository` + `Pg…`, `UnitOfWork`/`ReadOnlyUnitOfWork`
(+`prediction_market_snapshots_read`), `PredictionMarketConsumer`, `OHLCVBarModel`+`create_hypertable`
pattern, `EarningsCalendarDatasetConsumer`, `TemporalEventRepository.upsert_by_natural_key`,
`EntityEventExposureRepository.upsert`, `EventType.CORPORATE`/`EventScope.LOCAL`/`ExposureType.DIRECTLY_AFFECTED`,
`EnrichedArticleConsumer`, `materialize_graph`, `ArticleRelevanceScoringWorker` + `ARTICLE_RELEVANCE_SCORER`
prompt, `AlertFanoutUseCase`/`IntelligenceConsumer`/`SeverityThresholds`/`AlertRuleRepository`,
`proxy_json_response`/`_auth_headers`, `get_dashboard_snapshot`, `EarningsBarChart`, `buildPolymarketUrl`.

**NEW (tag `(NEW)` at first mention in tasks):** the 4 adapters/clients, `SyntheticDocumentEmitter`, the 4
S3 tables + models + ports + `Pg…` repos, `PredictionMoveDetector` worker, S7 `PredictionEnrichedConsumer` +
`PredictionSignalEmitter`, `MarketPolarityClassifier` + `MARKET_POLARITY` prompt, 6 Avro schemas, the S9
`/entities/{id}/predictions` route, frontend `ProbabilityChart` + `usePredictionMarketHistory`.

## TRACKING
Row updated in `docs/plans/TRACKING.md` (status `draft`, 0/18). Branch `feat/prediction-data-activation`.

---

# Sub-Plan Z — Contracts, Topics & Avro Schemas (foundation)

**Goal**: define every new Kafka topic, Avro schema, and enum value that A/B/C/D depend on, so
producers and consumers compile against a shared contract. **Depends on**: none.

### Wave Z1 — enums, topics, Avro schemas ✅
**Architecture layer**: contracts. **Effort**: 45–60m.
**Status**: **DONE** — 2026-07-09 · 6 Avro schemas + 4 enum values + 6 topics · 30 new contract
tests pass (parse + envelope + field-count + minimal-payload forward-compat round-trip) · ruff +
mypy clean · 5 pre-existing unrelated contract failures logged (market.dataset.fetched count drift,
content.article.* counts, entity.narrative/refresh envelope — untouched by this wave).

#### Tasks
- **T-Z-1-01 (schema)** — Add 4 values to `ContentSourceType` (`libs/contracts/src/contracts/enums.py`):
  `POLYMARKET_GAMMA_EVENTS`, `POLYMARKET_CLOB`, `POLYMARKET_DATA_TRADES`, `POLYMARKET_DATA_OI`.
  *Downstream test impact*: any exhaustive enum test in `libs/contracts/tests`.
- **T-Z-1-02 (config)** — Register 6 new topics in `libs/messaging/src/messaging/topics.py`:
  `MARKET_PREDICTION_HISTORY`=`market.prediction.history.v1`, `…EVENT`=`market.prediction.event.v1`,
  `…TRADE`=`market.prediction.trade.v1`, `…OI`=`market.prediction.oi.v1`, `…MOVE`=`market.prediction.move.v1`,
  `…SIGNAL`=`market.prediction.signal.v1`. Add retention/partition-key rows to MASTER_PLAN topic table.
- **T-Z-1-03 (schema)** — Add 6 Avro schemas under `infra/kafka/schemas/` (and mirror into the
  producing service's `…/messaging/schemas/` where that service keeps local copies). All use the
  standard envelope (`event_id` UUIDv7, `occurred_at` timestamp-micros, `schema_version` int default 1)
  + payload per PRD §6.4 / §8. `…move.v1`: `market_id, token_id, outcome_name?, interval, prev_price,
  new_price, delta, direction(up|down), liquidity?, volume_24h?, window_start_ts, is_backfill`.
  `…signal.v1`: `subject_entity_id(string uuid), market_id, trigger(new_market|material_move|resolution),
  market_impact_score(double 0..1), polarity(bullish|bearish|neutral), question, url?, occurred_at`.
  history/event/trade/oi per PRD §3.3 sketch. **Forward-compat: optional fields defaulted (R5/R11).**
- **T-Z-1-04 (test)** — contract tests: schema JSON validity + envelope presence + round-trip
  serialize/deserialize for each; register subjects. Pre-read the existing
  `market.prediction.v1.avsc` + one contract test for the pattern.

#### Validation Gate
- [ ] ruff+mypy on libs/contracts, libs/messaging · [ ] Avro JSON valid (schema-guard hook) ·
  [ ] contract tests pass (≥6 new) · [ ] docs: MASTER_PLAN topic table updated
#### Architecture Compliance
- [ ] R5 forward-compat (defaults on all optional fields) · [ ] R11 UTC `timestamp-micros` · [ ] R6 UUIDv7 ids
#### Break Impact
| File | Why | Fix |
|---|---|---|
| `libs/contracts/tests/*enum*` | new enum values | update any exhaustive assertion |
| MASTER_PLAN topic table | new topics | add 6 rows |
#### Regression Guardrails
- BP-001/BP-017/BP-024 (Kafka): new topics need a consumer before they are produced in prod (here
  consumers land in A/C/D before B/D produce) — sequence enforced by the dependency graph.
- Avro forward-compat: never remove/rename; only add defaulted fields.

---

# Sub-Plan A — S3 Storage Extension + Deeper-Stream Consumers

**Status**: **COMPLETE** — 2026-07-09 (A1, A2, A3, A4 all ✅). All 4 new streams stored,
consumed, and exposed via read use cases + API routes.

**Goal**: co-locate the 4 new streams in `market_data_db` next to the existing prediction tables;
expose `liquidity`. **Depends on**: Z. Mirrors `PredictionMarketSnapshotModel` + OHLCV hypertable +
`PredictionMarketConsumer` patterns throughout.

### Wave A1 — models + migration 043 + expose liquidity ✅
**Status**: **DONE** — 2026-07-09 · 79 targeted + 1264 unit tests pass · ruff+mypy clean
**Layer**: schema. **Effort**: 60m. **depends_on**: Z1.
- **T-A-1-01 (schema)** — Migration `043_prediction_deeper_streams.py` (`revision="043"`,
  `down_revision="042"`) creating (NEW): `prediction_market_prices` (cols `id` uuid, `market_id` text,
  `token_id` text, `outcome_name` text null, `interval` varchar(4), `window_start_ts` timestamptz,
  `price` numeric, `source` text, `is_backfill` bool; composite PK `(id, window_start_ts)`, UK
  `(market_id, token_id, interval, window_start_ts)`, index `(market_id, window_start_ts desc)`;
  `create_hypertable('prediction_market_prices','window_start_ts', chunk_time_interval => INTERVAL '1 month')`);
  `prediction_market_trades` (`id, market_id, trade_id, token_id, price, size_usd, side, ts`; PK
  `(id, ts)`, UK `(market_id, trade_id)`; hypertable on `ts`); `prediction_market_oi` (`id, market_id,
  snapshot_date date, total_oi_usd, total_volume_24h_usd`; PK `(market_id, snapshot_date)`; NOT a
  hypertable — daily); `prediction_events` (`id, event_id text UK, name, category, start_date,
  end_date, market_count int, created_at, updated_at`). ALTER `prediction_markets` ADD `event_id text null`.
- **T-A-1-02 (impl)** — ORM models mirroring `PredictionMarketSnapshotModel` in
  `infrastructure/db/models/prediction_markets.py`. Register in models `__init__`.
- **T-A-1-03 (impl)** — Expose `liquidity`: add to `SnapshotPointResponse` (+summary/detail if desired)
  in `api/schemas/prediction_markets.py`; ensure `_row_to_snapshot`/history use case carry it.
**Tests**: model metadata + migration up/down (test DB) + history response includes liquidity. **Break impact**:
`services/market-data/tests` snapshot/history assertions gain `liquidity`. **Guardrails**: BP-007 (VARCHAR
not PG enum for `interval`/`side`), BP-019/032 (hypertable created after table+index; `migrate_data=>true`),
R32 (043 chained from verified 042).

### Wave A2 — ports + Pg repos + UoW accessors ✅
**Status**: **DONE** — 2026-07-09 · 24 tests (16 repo-unit + 3 UoW-wiring + 5 integration, real TimescaleDB) · ruff+mypy clean
**Layer**: infrastructure. **Effort**: 60m. **depends_on**: A1.
- **T-A-2-01..04 (impl)** — 4 ABC ports (`PredictionMarketPricesRepository`, `…TradesRepository`,
  `…OIRepository`, `…EventsRepository`) in `application/ports/repositories.py` + `Pg…` impls mirroring
  `PgPredictionMarketSnapshotRepository` (`insert_if_not_exists` ON CONFLICT DO NOTHING; `list_*` date-range
  DESC; batch upsert for backfill). Add write + `_read` accessors to `UnitOfWork` and `ReadOnlyUnitOfWork`
  (`uow.py`). **R25**: ports are ABCs; use cases never import `Pg…`. **R27**: `_read` accessors on ReadOnlyUoW.
**Tests**: repo insert/dedup/list per table (≥8). **Guardrails**: BP-034/035 idempotent inserts.

### Wave A3 — 4 stream consumers ✅
**Status**: **DONE** — 2026-07-09 · 32 tests · ruff+mypy clean
**Layer**: infrastructure. **Effort**: 75m. **depends_on**: A2, Z1.
> Impl note: `PredictionEventConsumer` upserts the `prediction_events` row only
> (group_id→event_id, name, category, start/end dates, market_count). The
> market→event_id linkage is set S4-side later (the event Avro schema carries
> only the group, not its child market ids), so no `prediction_markets.event_id`
> backfill happens here. 4 `_main.py` entrypoints + 8 docker-compose services
> (dev + test harness) added; 4 static-membership instance-id settings in
> `config.py`. All consume `auto_offset_reset="earliest"` (durable append/upsert
> streams; duplicates return is_new=False from `ingestion_events`).
- **T-A-3-01..04 (impl)** — 4 consumers mirroring `PredictionMarketConsumer` (+ `_main.py` entrypoints,
  docker-compose services): `PredictionHistoryConsumer` (`market.prediction.history.v1`→prices),
  `PredictionEventConsumer` (`…event.v1`→events + backfill `prediction_markets.event_id`),
  `PredictionTradeConsumer` (`…trade.v1`→trades), `PredictionOIConsumer` (`…oi.v1`→oi). Avro-first w/ JSON
  fallback; dedup via `ingestion_events.create_if_not_exists` + table ON CONFLICT; no commit in
  `process_message` (base owns it). **R9**: consume via Kafka only.
**Tests**: each consumer happy-path + replay no-op (≥8). **Guardrails**: BP-034/035, base-consumer
`is_duplicate` ordering (reset `_current_uow`).

### Wave A4 — query use cases + routes (history-interval, trades, events) ✅
**Status**: **DONE** — 2026-07-09 · 21 new tests · ruff+mypy clean · 1348 unit pass
> Impl note: added 4 read-only use cases (`GetPredictionMarketPriceHistoryUseCase`,
> `GetPredictionMarketTradesUseCase`, `ListPredictionEventsUseCase`,
> `GetPredictionEventUseCase`) — all depend on `ReadOnlyUnitOfWork` and use the
> `*_read` accessors (R27). The existing `GetPredictionMarketHistoryUseCase`
> (snapshots) is kept intact; the `/history` route now declares BOTH it and the
> new price use case as deps and branches on `?interval` (1h|1d|1w validated →
> prices hypertable; omitted → snapshots, backward-compatible). Union
> `response_model` (`PredictionMarketHistoryResponse | PredictionMarketPriceHistoryResponse`).
> New literal `/events` + `/events/{event_id}` routes registered before
> `/{market_id}`; `/{market_id}/trades` before `/{market_id}`. `GetPredictionEventUseCase`
> returns event metadata only (the `list_markets` port has no `event_id` filter).
> New schemas: `PriceHistoryPointResponse`, `PredictionMarketPriceHistoryResponse`,
> `PredictionMarketTradeResponse`, `PredictionMarketTradesResponse`,
> `PredictionEventResponse`, `PredictionEventsListResponse`. Dep factories added
> in `api/dependencies.py` mirroring the existing history dep.
**Layer**: API. **Effort**: 60m. **depends_on**: A2.
- **T-A-4-01..03 (impl)** — Read-only use cases (`ReadOnlyUnitOfWork`) + routes under the existing S3
  `/prediction-markets` router: `GET /{market_id}/history?interval=&since=` (extend existing history to
  read `prediction_market_prices` when `interval` given, else snapshots), `GET /{market_id}/trades`,
  `GET /events` + `GET /events/{event_id}`. Dependencies via `get_read_uow` (`ReadUoWDep`).
**Tests**: route + use case per endpoint (≥6). **Guardrails**: R27 ReadOnlyUoW; BP-712 query tokenizer if text search.

---

# Sub-Plan B — S4 Adapters + Synthetic-Document Emitter

**Goal**: fetch the 4 deeper streams and emit them to Kafka; emit one synthetic doc per market
(first-sight + resolution) onto `content.article.raw.v1` for S6 NER. **Depends on**: Z.
Mirrors `PolymarketClient`/`PolymarketAdapter` + `FetchAndWritePredictionMarketsUseCase` +
`build_raw_article_payload` + worker routing patterns. **Note**: new adapters route directly in
`worker._execute_polymarket_task` (NOT via `ADAPTER_REGISTRY`), same as existing Polymarket.

### Wave B1 — 4 clients + config settings + 4 adapters ✅
**Status**: **DONE** — 2026-07-09 · 31 new tests · ruff+mypy clean · full S4 suite green (0 failures)
**Layer**: infrastructure. **Effort**: 90m. **depends_on**: Z1.
- **T-B-1-01..04 (impl)** — Per stream, a `{Name}Client` (NEW) + `{Name}Adapter` (NEW) under
  `infrastructure/adapters/{polymarket_gamma_events,polymarket_clob,polymarket_data_trades,polymarket_data_oi}/`:
  - `PolymarketEventsClient/Adapter` — Gamma `/events`, cursor-paginated (1h cadence).
  - `PolymarketClobHistoryClient/Adapter` — CLOB `/prices-history`, per-token-id; backfill + 6h window;
    **resolved-market fallback: on 400/empty for `interval=1h`, retry `interval=1d`** (PRD §4.4 / §9.2).
  - `PolymarketTradesClient/Adapter` — Data `/trades`, per-market last-cursor.
  - `PolymarketOIClient/Adapter` — Data `/oi`, daily.
  Each: `AdapterError` on non-200; **429 → backoff/Retryable**; MinIO bronze write non-fatal. Add
  `{Name}ProviderSettings` (base_url, page_size, timeouts) to `config.py` + wire into `Settings`.
**Tests**: per adapter — happy-path parse, dedup, 429 backoff, CLOB `1d` fallback (≥12). **Guardrails**:
BP-025/026/027 (external I/O: timeouts, retry classification, rate-limit).

### Wave B2 — SyntheticDocumentEmitter ✅
**Status**: **DONE** — 2026-07-09 · 16 new tests · ruff+mypy clean · full S4 suite green (0 failures).
Delivered `application/use_cases/emit_synthetic_prediction_document.py` (`SyntheticDocumentEmitter` +
`build_synthetic_document_body` + first-sight/resolution `url_hash` helpers) and wired
`WorkerProcess._emit_synthetic_documents(results)` into `_execute_polymarket_task()` (runs outside the
snapshot advisory lock, best-effort, own atomic fetch_log+outbox tx per doc). B3 still owns the 4-adapter
routing / outbox dispatcher / scheduler seeding.
**Layer**: application. **Effort**: 60m. **depends_on**: B1(config only) — can start with A.
- **T-B-2-01 (impl)** — `SyntheticDocumentEmitter` (NEW): from a `PredictionMarketFetchResult`, build a
  `content.article.raw.v1` payload via the existing `build_raw_article_payload` shape with
  `source_type='polymarket'` (ContentSourceType) — body = question + outcomes (implied %) + close date +
  category + event name (PRD §7). **One doc per market**, deduped on `url_hash = sha256("polymarket:"+condition_id)`
  via `FetchLogRepository.exists_by_url_hash`; **second doc on resolution** (append resolution suffix →
  distinct url_hash). DB write + outbox in one tx (**R8 outbox**). Wire into the Polymarket snapshot path
  (`_execute_polymarket_task`) so first-sight/resolution triggers the emit.
**Tests**: first-sight emits 1; re-poll emits 0 (dedup); resolution emits 1; body contains entities (≥5).
**Guardrails**: R8 outbox; audit-return-persistence (emitter output must be committed, not just logged).

### Wave B3 — worker routing + scheduler seeding + migration 0011 + env ✅
**Status**: **DONE** — 2026-07-09 · 43 new tests · ruff+mypy clean · full S4 suite green (0 failures) ·
contract + avro-prediction contract tests green. **Sub-Plan B COMPLETE (B1, B2, B3).**
Delivered: `application/use_cases/fetch_and_write_prediction_streams.py` (4 payload builders +
`PredictionStreamSpec` registry + generic `FetchAndWritePredictionStreamUseCase`, R8 outbox);
`WorkerProcess._execute_prediction_stream_task` + `_build_prediction_stream_adapter` +
`_prediction_stream_spec` route the 4 new `SourceType`s directly (mirrors `_execute_polymarket_task`,
loads live source config for `token_ids`/`condition_ids`, advisory-locked fetch_log+outbox tx);
outbox dispatcher registers the 4 new `event_type`s → their Avro serializers (4 `.avsc` copied into the
service-local schemas dir; serializer routes on `event_type`); `scheduler_main` adds per-stream cadence
(events 1h, CLOB 6h, trades 1h, OI daily) from each provider's `poll_interval_seconds`; migration
`0011_seed_pm_wave2_sources.py` (down_revision `0010_sec_edgar_cik_watchlist`) seeds 4 sources;
env vars `CONTENT_INGESTION_POLYMARKET_HISTORY_BACKFILL_DAYS` / `…_TRADES_BACKFILL_DAYS` (default 14,
gated by `BACKFILL_ON_STARTUP`) added to `Settings` + `dev.local.env.example` + `docker.env`.
Known limitation: B1 CLOB/trades entities carry no parent `conditionId`, so history/trade payloads use
`token_id` as the non-null surrogate `market_id` (S3 dedup keys already include token_id/trade_id — a
later wave can enrich token→conditionId).
**Layer**: config. **Effort**: 60m. **depends_on**: B1, B2.
- **T-B-3-01 (impl)** — Extend `worker._execute_polymarket_task` dispatch: map each new
  `ContentSourceType` → its client/adapter class.
- **T-B-3-02 (impl)** — Outbox dispatcher: map the 4 new outbox `event_type`s → their Avro serializers/topics.
- **T-B-3-03 (schema)** — content-ingestion migration `0011_seed_pm_wave2_sources.py`
  (`down_revision="0010_sec_edgar_cik_watchlist"`) seeding 4 new `sources` rows with per-adapter cadence.
- **T-B-3-04 (config)** — env vars `CONTENT_INGESTION_POLYMARKET_HISTORY_BACKFILL_DAYS=14`,
  `…TRADES_BACKFILL_DAYS=14` (+ `dev.local.env.example`, docker.env). Backfill gated by existing
  `CONTENT_INGESTION_BACKFILL_ON_STARTUP`.
**Tests**: routing dispatch per source type; scheduler seeds 4 sources; migration up/down (≥6).
**Guardrails**: R32 (0011 chained from verified 0010); compose-profile recreate gotcha (feedback memory).

### Wave B4 — CLOB/trades conditionId association (corrective) ✅
**Status**: **DONE** — 2026-07-10 · 12 new/updated tests · ruff+mypy clean (only pre-existing pdfminer
stub) · full S4 suite green (1019 passed / 60 pre-existing integration skips) · avro-prediction contract
tests green (32 passed). **Corrective wave** fixing the B3 **token_id-surrogate bug**: CLOB
`/prices-history` and Data `/trades` are keyed by per-outcome `token_id` and carry no parent
`conditionId`, so B3 set the outbox `market_id = token_id` → S3 `prediction_market_prices` /
`prediction_market_trades` rows did NOT JOIN to `prediction_markets` (keyed on conditionId), breaking the
probability chart (E2) and move-signal (D1).
Fix: CLOB/trades source `config` now carries a **`markets` work-list** — `[{"condition_id": ...,
"token_ids": [...]}]` pairing each parent market with its child CLOB outcome tokens (derivable from Gamma
`/markets` `clobTokenIds`) — parsed by the new shared `infrastructure/adapters/polymarket_worklist.py`
(`parse_markets` → `MarketWorkItem`, camelCase-tolerant, legacy flat `token_ids`/`condition_ids` fallback
with `condition_id=None`). The adapters thread the parent `condition_id` into
`PredictionHistoryFetchResult`/`PredictionTradeFetchResult` (new `market_id: str | None` field, set via
`from_api_response(..., condition_id=...)`); the history/trade payload builders now emit
`market_id = result.market_id or result.token_id` (surrogate only when the parent is unknown) with
`token_id` unchanged. Migration `0011` seed reshaped to `{"markets": []}` for CLOB + trades (OI keeps
`condition_ids`). No Avro change — both `market_id` and `token_id` fields already exist (Wave A1). Dedup
keys unchanged (history→token_id, trade→trade_id).
**Layer**: infrastructure/domain. **Effort**: 45m. **depends_on**: B1, B3.
- **T-B-4-01 (impl)** — shared `polymarket_worklist.parse_markets` (`markets` work-list → `MarketWorkItem`).
- **T-B-4-02 (impl)** — CLOB + trades adapters parse the work-list and thread `condition_id` onto results.
- **T-B-4-03 (impl)** — entities carry `market_id`; payload builders set `market_id = parent conditionId`.
- **T-B-4-04 (schema)** — migration `0011` seed reshaped to `{"markets": []}` for CLOB + trades.
**Tests**: work-list parser (6); history/trade payload market_id=conditionId + surrogate fallback;
2-token market shares parent conditionId; migration seed has `markets` (≥12 total).
**Guardrails**: R8 (outbox unchanged); R32 (0011 seed edited, HEAD verified); no Avro break (both columns exist).

---

# Sub-Plan C — S7 KG Activation (KEYSTONE)

**Goal**: turn NER-enriched synthetic docs into PREDICTION temporal events + entity exposures with
LLM-classified polarity, and expose them per entity. **Depends on**: B2 (synthetic docs flowing through
S6). Mirrors `EarningsCalendarDatasetConsumer` + `TemporalEventRepository.upsert_by_natural_key` +
`EntityEventExposureRepository.upsert`.

### Wave C1 — migration 0066: PREDICTION event type + exposure polarity ✅
**Status**: **DONE** — 2026-07-10 · verified HEAD 0065 (filesystem-authoritative, R32) so chained
`0066`→`0065` · widened `ck_temporal_event_type` to add `'prediction'` (keeps all 7 prior values) +
`entity_event_exposures.polarity varchar(20) null` / `polarity_confidence double precision null` +
`ck_exposure_polarity` CHECK (bullish|bearish|neutral OR NULL, VARCHAR not enum per BP-007) · 7 DB-free
static-guard tests pass · ruff clean · mypy N/A (alembic/ + tests/ excluded) · DB-dependent
integration/apply/rollback tests NOT run (no Postgres in env).
**Layer**: schema. **Effort**: 45m. **depends_on**: none (but verify HEAD per ⚠️ above).
- **T-C-1-01 (schema)** — intelligence-migrations `0066_prediction_event_type_and_exposure_polarity.py`
  (`revision="0066"`, `down_revision="0065"`): widen `ck_temporal_event_type` to include `'prediction'`
  (mirror `0018_add_corporate_event_type`); ALTER `entity_event_exposures` ADD `polarity varchar(20) null`,
  `polarity_confidence double precision null`. Downgrade drops prediction rows + columns.
**Tests**: migration up/down; CHECK accepts 'prediction'; columns present (≥3). **Guardrails**: R24
(intelligence_db DDL only via intelligence-migrations; S7 `ALEMBIC_ENABLED=false`), R32, ⚠️0066 collision note.

### Wave C2 — EventType.PREDICTION + PredictionEnrichedConsumer ✅
**Status**: **DONE** — 2026-07-10 · 15 new consumer tests + 1 entrypoint test · full KG suite green (1692 pass, 0 fail) · ruff + mypy + import-guards clean.
**IMPLEMENTATION NOTES (source-of-truth corrections vs the task text below)**:
- **Filter is `source_type == 'polymarket'`**, NOT `'prediction_market'`. Wave B2 stamps
  `ContentSourceType.POLYMARKET` (= `"polymarket"`) and S6 passes it through verbatim; `'prediction_market'`
  is never emitted (prompt-input-vs-lookup guardrail). A regression test asserts `'prediction_market'` is skipped.
- **The enriched event carries NO title / source_url / condition_id** (verified against the S6 producer +
  `nlp.article.enriched.v1.avsc`). It only carries `doc_id`, `source_type`, `resolved_entity_ids`,
  `published_at`, `occurred_at`. So the question text and condition_id are NOT recoverable here (an nlp_db read
  would violate R7). The temporal event therefore uses `region="prediction"` (constant category) and
  `title=f"Prediction market {doc_id}"` — doc_id is the only stable per-market key (B2 emits one doc/market),
  giving idempotency via the `(event_type, region, title, active_from::day)` natural key. `active_from` =
  published_at||occurred_at||now; `active_until=None` (close_time unavailable); `residual_impact_days=30`;
  `confidence=0.5`. Wave E/C4 can enrich the title/region if S6 starts carrying the question through.
- **Polarity**: `EntityEventExposureRepository.upsert` (+ its port) extended with optional
  `polarity`/`polarity_confidence` (default None → NULL, allowed by 0066's `ck_exposure_polarity`). The consumer
  exposes a `polarity_classifier` injection seam (`_resolve_polarity`) that returns (None, None) today; Wave C3
  drops in the LLM classifier without touching the write path.
- **Benign-overlap CONFIRMED**: `materialize_graph` only writes inside `for` loops over relations/events/claims;
  a Polymarket question yields empty arrays → `EnrichedArticleConsumer` produces 0 evidence rows / 0 edges /
  0 dirtied entities for these docs. No junk relations.
- **R26 commit**: consumer owns an explicit `session.commit()` (tested) — no HTTP200-but-rollback.
- Files: `domain/enums.py` (PREDICTION), `infrastructure/messaging/consumers/prediction_enriched_consumer.py` +
  `_main.py`, `application/ports/temporal_event_repository.py` + `infrastructure/.../temporal_event_repository.py`
  (polarity params), `config.py` (instance-id), `docker-compose.yml` (new service).
**Layer**: application/infrastructure. **Effort**: 90m. **depends_on**: C1.
- **T-C-2-01 (impl)** — Add `PREDICTION="prediction"` to `EventType` (`domain/enums.py`).
- **T-C-2-02 (impl)** — `PredictionEnrichedConsumer` (NEW) + `_main.py`, own consumer group on
  `nlp.article.enriched.v1`, **filtered to `source_type='prediction_market'`**. For each such doc:
  (a) `TemporalEventRepository.upsert_by_natural_key(event_type=PREDICTION, scope=LOCAL, region=<market
  category or primary ticker>, title=question, active_from=created, active_until=close_time,
  residual_impact_days=…, confidence=<implied prob>)`; (b) for each **resolved** entity mention in the
  enriched payload, `EntityEventExposureRepository.upsert(event_id, entity_id, exposure_type=
  DIRECTLY_AFFECTED, confidence, polarity=<C3 classifier>, polarity_confidence)`. Idempotent on natural key.
  **Note**: the existing `EnrichedArticleConsumer` (different group) will also see these docs; a market
  question yields ~0 raw_relations so impact is benign — QA must confirm no junk relations (guardrail).
**Tests**: prediction doc → 1 temporal event + N exposures; re-delivery idempotent; non-prediction docs
ignored (≥6). **Guardrails**: BP-034/035 idempotency; R26 use-cases-commit (no HTTP200-but-rollback,
per KG-relation-growth memory); entity-noise gate.

### Wave C2b — external_id passthrough (corrective) ✅
**Status**: **DONE** — 2026-07-10 · 15 new tests (5 KG parse + 3 KG condition_id path + 1 S6 enriched-event ×2 + 3 S5 passthrough + 2 S4 payload + 3 schema round-trip) across contracts/S4/S5/S6/S7 · ruff + mypy clean · affected unit suites green (content-ingestion 1011, content-store 382, nlp consumers 147, kg consumer 281, contracts 197 — only unrelated pre-existing `ContentSourceType`/`SourceType` enum-drift + `market.dataset.fetched`/`entity.narrative`/`entity.refresh` field-count failures remain).
**PROBLEM**: Wave C2's temporal events were **anonymous** — the `nlp.article.enriched.v1` event dropped the market's identity, so C2 used `region="prediction"` + `title="Prediction market {doc_id}"`. C4 (entity page) and D2 (move-signal) could not resolve exposures to a real market, and the two synthetic docs per market (first-sight + resolution) produced two rows.
**FIX**: added a nullable `external_id` passthrough field (`["null","string"]`, default null, R5 forward-compat) carrying `"polymarket:<condition_id>"`, threaded verbatim **S4 → S5 → S6 → S7**:
- **Contracts/schemas**: `external_id` added to `content.article.raw.v1.avsc` (+ its content-ingestion service-local copy), `content.article.stored.v1.avsc`, `nlp.article.enriched.v1.avsc`, and the `CanonicalNlpArticleEnriched` model (to_dict/from_dict). Field-count test bumped (raw 14→16, stored 15→17, enriched 25→26 — the raw/stored priors were pre-existing stale drift, noted in-line).
- **S4 (content-ingestion)**: `build_raw_article_payload` gained an `external_id` param (default None for normal articles); the synthetic emitter sets `external_id=f"polymarket:{result.market_id}"`. `source_url` kept as the real URL (not overloaded).
- **S5 (content-store) — BLAST-RADIUS HOP (not in original task scope, but required)**: S6 consumes `content.article.stored.v1`, NOT raw — so S5 must copy `external_id` through or it never reaches S6. `RawArticleEvent` + `_parse_raw_event` + `_build_stored_payload` extended (mirrors the `tenant_id` PLAN-0086 pattern exactly).
- **S6 (nlp-pipeline)**: pure in-memory passthrough (NO DB persist/re-read → **no migration**). `process_message` reads `value.get("external_id")` → `_run_pipeline` → `_enqueue_enriched` → `payload["external_id"]`. Zero NER/extraction change.
- **S7 (knowledge-graph)**: `PredictionEnrichedConsumer` parses the condition_id via `_parse_condition_id` (strips `polymarket:` prefix). When present → `region=<condition_id>`, `title=f"Prediction market {condition_id}"` (natural key now unique **per market** → first-sight + resolution collapse to ONE row, idempotent per condition_id). Absent/malformed → old anonymous doc_id behaviour (backward-compatible).
**Files**: 4 avsc + `article_enriched.py`; `fetch_and_write.py`, `emit_synthetic_prediction_document.py`; `process_article.py`, content-store `article_consumer.py`; nlp `article_consumer.py`, `blocks/enriched_event.py`; `prediction_enriched_consumer.py`; `tests/contract/test_avro_schemas.py` + 5 test files.
**Layer**: contracts/application/infrastructure. **depends_on**: C2.

### Wave C3 — MarketPolarityClassifier (LLM at link time) ✅
**Status**: **DONE** — 2026-07-10 · ~20 new/updated tests (schema round-trip + field-count 27,
canonical-model source_title round-trip ×3, prompt ×7, classifier ×11, S6 passthrough ×2,
consumer C3 ×7) · full KG unit (1680) + nlp-pipeline unit (1368) + libs/prompts + libs/contracts
suites green · ruff + mypy clean on all touched packages. Pre-existing unrelated failures logged
(market.dataset.fetched count, entity.narrative/refresh envelope, ContentSourceType enum-drift —
untouched by this wave).
**IMPLEMENTATION NOTES**:
- **source_title passthrough (Part 1)**: added a nullable `source_title` (`["null","string"]`,
  default null, R5) to `nlp.article.enriched.v1.avsc` + `CanonicalNlpArticleEnriched`
  (to_dict/from_dict). S6 copies the inbound `content.article.stored.v1.title` verbatim onto the
  enriched event (`article_consumer.process_message` → `_run_pipeline` → `_enqueue_enriched`) — pure
  in-memory passthrough, no NER change, no migration. Field-count test bumped 26→27; the
  canonical↔avro alignment test (`avro_fields == to_dict keys`) stays green because BOTH sides gained
  the field. No service-local enriched schema copy exists, so only the canonical `.avsc` changed.
- **MARKET_POLARITY prompt (Part 2)**: `libs/prompts/src/prompts/classification/market_polarity.py`
  (`MARKET_POLARITY_CLASSIFIER`, version 1.0), mirrors `article_relevance.py` (static block +
  caller-appended dynamic trailer, `parameters=frozenset()`). Output JSON
  `{polarity: bullish|bearish|neutral, confidence, reason}`.
- **MarketPolarityClassifier (Part 3)**: S7 `infrastructure/llm/market_polarity_classifier.py`, reuses
  the S6 relevance stack (DeepInfra OpenAI-compat `/chat/completions`, small model
  `Qwen/Qwen2.5-0.5B-Instruct`, `response_format=json_object`, `enable_thinking=False`,
  `httpx.AsyncClient`). Every call logs to `llm_usage_log` via `SessionScopedKgUsageLogger` with a
  NON-ZERO cost resolved through `ml_clients.pricing.resolve_cost` (DeepInfra `usage.estimated_cost` →
  `cost_source="provider"`). Any error/timeout/parse-failure → `("neutral", 0.0)`. Caches per
  `(condition_id, entity_id)`. Config env vars added to S7 `config.py`
  (`polarity_classifier_model_id`/`_base_url`/`_timeout_seconds`); wired in
  `prediction_enriched_consumer_main.py` only when `deepinfra_api_key` is set.
- **Consumer wiring (Part 4)**: `PredictionEnrichedConsumer` now reads `source_title` → titles the
  temporal event with the real question (fallback to the condition_id/doc_id placeholder). When a
  classifier is injected AND the question is present, it resolves each entity's canonical name (short
  read session, released BEFORE the LLM HTTP calls — R24) then classifies polarity, writing
  `polarity`/`polarity_confidence` onto each exposure. Idempotent + graceful (NULL polarity) when
  `source_title`/classifier/entity-name absent or the classifier raises.
- Files: `nlp.article.enriched.v1.avsc`, `libs/contracts/.../article_enriched.py`,
  `libs/prompts/.../classification/market_polarity.py` (+ `__init__`), S7
  `infrastructure/llm/market_polarity_classifier.py`, `prediction_enriched_consumer.py` +
  `_main.py`, `config.py`, S6 `blocks/enriched_event.py` + `article_consumer.py`, contract/unit tests.
**Layer**: infrastructure. **Effort**: 60m. **depends_on**: C2.
- **T-C-3-01 (impl)** — `MARKET_POLARITY` prompt (NEW) in `libs/prompts/src/prompts/classification/market_polarity.py`
  (mirror `article_relevance.py` structure/versioning): input (market question, outcome, entity name) →
  JSON `{polarity: bullish|bearish|neutral, confidence: float, reason: <=10 words}`.
- **T-C-3-02 (impl)** — `MarketPolarityClassifier` (NEW) in S7 `infrastructure/llm/`, wrapping an
  `ml-clients` adapter (reuse the relevance/sentiment stack: DeepInfra small model + `LlmUsageLogProtocol`
  so cost is tracked — avoid the S6/S8 `$0` cost bug). Called by C2 per (market, entity); on LLM failure
  **default `neutral`** (never blocks ingestion, PRD §13). Cache by (condition_id, entity_id) — classify once.
**Tests**: bearish/bullish/neutral cases; failure→neutral; cost logged (≥5). **Guardrails**: LLM-cost
tracking (feedback memory: every call site must set non-zero `estimated_cost_usd`); prompt-input-vs-lookup match.

### Wave C4 — S7 entity-predictions read API ✅
**Layer**: API. **Effort**: 45m. **depends_on**: C2. **Status: DONE (2026-07-10).**
- **T-C-4-01 (impl)** — `GET /api/v1/entities/{entity_id}/predictions` (NEW) via a read-only use case on
  the read-replica session (S7's R27 mechanism — `ReadOnlyDbSessionDep`): join
  `entity_event_exposures`(polarity) → `temporal_events`(event_type='prediction') for the entity; return
  `condition_id` (region), `question` (title), `polarity`, `polarity_confidence`, `close_time`
  (active_until), `confidence`. **R25/R27**. Implemented as
  `EntityEventExposureRepository.list_prediction_exposures_for_entity` +
  `GetEntityPredictionsUseCase` + router `api/entity_predictions.py` + schemas
  `EntityPredictionItem`/`EntityPredictionsResponse`. Ordered by `active_until DESC NULLS LAST, created_at DESC`.
  Empty entity → 200 empty list (never 404). `limit` clamped 1..200 (FastAPI query validation), `offset` echoed.
  Note: **current implied prob is NOT returned here** — the S9 gateway (Wave E1) hydrates live odds/liquidity
  from S3 by `condition_id`, the critical join key returned by this endpoint.
**Tests**: 21 new (route 10, use-case 5, repo 6) — 2 markets w/ different polarities; empty→empty list;
prediction-only filter (non-prediction exposures excluded); limit/offset clamp + echo; NULL-polarity passthrough;
read-replica session (R27). **Guardrails**: R27 read replica, R25 route→use-case-only.

**Sub-Plan C (KEYSTONE) COMPLETE** — C1..C4 all DONE. KG prediction linkage (write side C2/C2b/C3 +
read side C4) is fully wired; Sub-Plan D (signals) and E (gateway/frontend/chat) can now build on it.

---

# Sub-Plan D — Signals (S3 move → S7 signal → alert fanout)

**Goal**: fire score-gated prediction signals through the existing alert engine. **Depends on**: A
(snapshots/prices), C (exposures + polarity).

### Wave D1 — S3 PredictionMoveDetector worker ✅
**Status**: **DONE** — 2026-07-10 · 11 new unit tests · ruff + mypy clean (173 files) · full market-data suite: 1490 passed / 34 pre-existing e2e+integration+live errors (need live DB/Kafka). Delivered `PredictionMoveDetector` (`infrastructure/workers/prediction_move_detector.py`) + `_main.py` entrypoint + docker-compose service `market-data-prediction-move-detector`; new `PredictionMarketMove` domain event + `EVENT_TOPIC_MAP`/`_AVSC_MAP` wiring (`market.prediction.move` → `market.prediction.move.v1`); 9 env-driven `prediction_move_*` settings (NO hardcoded gates) in `config.py` + `dev.local.env.example`. Reads open markets + snapshots via the read replica (R27), emits via the outbox (R8, `partition_key=market_id`). Gate: `|Δ| ≥ τ` AND latest-snapshot `liquidity ≥ floor` AND `volume_24h ≥ floor` (missing liquidity/volume fails the gate). **Dedup**: in-memory watermark per `(market_id, token_id)` = latest emitted `snapshot_at`; re-emit only when the latest snapshot is strictly newer (same snapshots re-observed → no re-emit); cross-restart dup absorbed by S7's per-`(condition_id, trigger, window)` idempotency (D2).
**Layer**: infrastructure. **Effort**: 75m. **depends_on**: A3.
- **T-D-1-01 (impl)** — `PredictionMoveDetector` (NEW) worker + `_main.py` in market-data: periodically
  scan `prediction_market_snapshots`/`_prices` per open market, compute Δ implied-probability over a
  window; **gate on liquidity + volume floor + |Δ|≥τ** (config env). On trigger emit
  `market.prediction.move.v1` (condition_id, token_id, prev/new price, delta, direction, liquidity, volume).
  Dedup per (market_id, token_id, window). **R9** (only its own DB). **R27** read replica for scans.
**Tests**: Δ above/below threshold; illiquid suppressed; dedup (≥5). **Guardrails**: BP-025 (worker cadence),
audit-return-persistence, config-driven thresholds (no hardcode).

### Wave D2 — S7 PredictionSignalEmitter ✅
**Status**: **DONE** — 2026-07-10 · 33 new tests · ruff + mypy clean · full KG suite 1774 passed / 55 skipped. Delivered `PredictionSignalEmitter` (`application/services/prediction_signal_emitter.py`) — one `market.prediction.signal.v1` per exposure via the outbox (R8): score `material_move`=clamp(|Δ|) with adverse ×`material_move_adverse_factor` (bearish-outcome rising OR bullish-outcome falling), `new_market`=`new_market_base`×exposure.confidence, `resolution`=`resolution_base` fixed — all in `Settings.prediction_signal_*` (env-driven, no hardcode). Idempotency: deterministic `uuid5` outbox event_id keyed on `(condition_id, subject_entity_id, trigger, window)` (window = move `window_start_ts` for material_move, else the trigger name) so re-delivery hits `ON CONFLICT (event_id) DO NOTHING`. New `PredictionMoveConsumer` (+`_main.py` + docker-compose `knowledge-graph-prediction-move-consumer`) on `market.prediction.move.v1` — joins exposures by `temporal_events.region==condition_id` via new `EntityEventExposureRepository.list_exposures_for_condition` (repo + port), emits material_move signals for ≥1 linked entity, skips `is_backfill`. `PredictionEnrichedConsumer` wired: first-sight → `new_market` (gated by `prediction_signal_emit_new_market`), `:resolved` → `resolution`; only when `condition_id` known. S4 corrective: `emit_synthetic_prediction_document` stamps `external_id=polymarket:<cid>:resolved` on the resolution doc; S7 `_parse_condition_id` strips the suffix (both docs still collapse to ONE market row) + new `_is_resolution_external_id`. Outbox topic const + dispatcher `_ALLOWED_TOPICS` extended for `market.prediction.signal.v1` (BP-147). The "tracked entity" noise-gate lives downstream in the alert watchlist fanout (D3).
**Layer**: application. **Effort**: 75m. **depends_on**: C2, D1, Z1.
- **T-D-2-01 (impl)** — `PredictionSignalEmitter` (NEW): three triggers → `market.prediction.signal.v1`
  per affected **tracked** entity, computing `market_impact_score` (new-market: fixed base × confidence;
  material-move: scaled by |Δ| × liquidity; resolution: fixed) and reading `polarity` from the exposure:
  (1) **new-market** — on C2 exposure creation; (2) **material-move** — consume `market.prediction.move.v1`,
  join exposures by condition_id → one signal per linked entity; (3) **resolution** — on market status→resolved.
  Emits `subject_entity_id, market_id, trigger, market_impact_score, polarity, question, url`. Outbox (**R8**).
**Tests**: each trigger emits per-entity signal with correct score/polarity; no exposure → no signal (≥6).
**Guardrails**: R8 outbox; noise-gate (only tracked-linked entities); idempotency per (condition_id, trigger, window).

### Wave D3 — alert: subscribe + prediction type + rule toggle ✅ DONE (2026-07-10)
**Status**: DONE — **Sub-Plan D COMPLETE**. `IntelligenceConsumer` now subscribes
`market.prediction.signal.v1` (topic const `kafka_topic_prediction_signal`; added to `_KNOWN_TOPICS`,
`_TOPIC_SCHEMA_PATHS`, `_resolve_topic`, ConsumerConfig + banner). `AlertFanoutUseCase` maps the topic →
`AlertType.PREDICTION` (`TOPIC_ALERT_TYPE`), extracts `subject_entity_id` as the fanout watchlist key, and
derives severity from `market_impact_score` via `SeverityThresholds.classify` (NOT in the MEDIUM-override set —
score already carries D2's adverse boost, so bearish moves land higher naturally). `_compose_prediction_detail`
composes adverse-emphasis copy from `trigger`+`polarity`+`question` ("AAPL — prediction market moving against:
…" for bearish; "in favor of" for bullish; neutral direction-less); `polarity`/`trigger`/`market_id`/`question`/
`url` all carried into the persisted payload for the frontend link. `AlertType.PREDICTION="prediction"` (VARCHAR,
no alerts-table migration — `alerts.alert_type` has NO CHECK). `RuleType.PREDICTION` + `PredictionCondition`
(`entity_id`/`min_impact_score`/`polarities`/`triggers`) + event-driven `PredictionRuleEvaluator` (registered;
poller-skipped like KG_CONNECTION) + `should_fire`/`next_state` PREDICTION branch (score-floor + 1h cooldown).
Migration `0011_add_prediction_rule_type.py` (rev 0011 / down 0010) widens `ck_alert_rules_rule_type`. **Gating
that actually fires prediction alerts = watchlist membership** (like all SIGNAL-class events); the rule type is a
user-configurable toggle/filter only. 35 new tests; 696 alert tests pass; ruff+mypy clean.
**Layer**: infrastructure/schema. **Effort**: 60m. **depends_on**: D2.
- **T-D-3-01 (impl)** — `IntelligenceConsumer`: subscribe `market.prediction.signal.v1`; map
  `subject_entity_id`→entity, `market_impact_score`→severity via `SeverityThresholds`, `polarity`→alert
  metadata, `trigger`→title. Reuse `AlertFanoutUseCase` (watchlist gate = tracked-entity gate) verbatim.
- **T-D-3-02 (impl)** — Add `prediction` to `AlertType` (VARCHAR — no migration) and adverse-direction
  emphasis in severity/copy (bearish move on held entity → higher severity).
- **T-D-3-03 (schema)** — alert migration `0011_add_prediction_rule_type.py` (`down_revision="0010"`)
  widening `ck_alert_rules_rule_type` to include `'PREDICTION'` so users can toggle prediction alerts;
  add `PredictionCondition` value-object + register a `PredictionRuleEvaluator`.
**Tests**: signal → gated alert for watching user; unwatched entity → suppressed; adverse severity bump;
rule toggle on/off (≥6). **Guardrails**: BP-007 (VARCHAR+CHECK, not PG enum), BP-034/035 dedup_key.

---

# Sub-Plan E — Gateway + Frontend + Chat

**Goal**: surface everything to the user. **Depends on**: A4 (S3 routes), C4 (entity predictions), D (badges).

### Wave E1 — S9 gateway routes + brief leg ✅ DONE (2026-07-10)
**Layer**: API. **Effort**: 60m. **depends_on**: A4, C4.
**Status**: DONE. Added S3 proxies `/events`, `/events/{id}`, `/{id}/trades` (registered BEFORE
`/{market_id}` for FastAPI route-ordering) + history `interval`/`token_id` passthrough; explicit
`liquidity`/`open_interest` + `PredictionEvent`/`PredictionMarketTrade` schemas (`extra=allow`).
`GET /v1/entities/{id}/predictions` proxies S7 C4 **verbatim** (no gateway odds-hydration — frontend
hydrates by `condition_id`; simpler + no fan-out latency/partial-failure surface). Morning brief
(`routes/chat.py get_morning_briefing`) augmented with a partial-failure-safe `prediction_signals`
leg (top open S3 markets; `None` on failure, non-200 briefs pass through untouched). 18 new tests
(13 route + 5 brief), ruff/mypy clean, 730 api-gateway tests pass.
- **T-E-1-01 (impl)** — Under existing `/v1/signals/prediction-markets/*` (`routes/intelligence.py`),
  add proxies: history `?interval=`, `/{id}/trades`, `/events`, `/events/{id}`, and expose `liquidity`/OI
  in the passthrough schemas (`schemas/prediction_markets.py`, `extra=allow`). Copy the `proxy_json_response`
  + `_auth_headers` pattern.
- **T-E-1-02 (impl)** — `GET /v1/entities/{id}/predictions` (NEW) proxy → S7 C4 endpoint.
- **T-E-1-03 (impl)** — Add a prediction leg to the morning-brief snapshot compose (`clients/dashboard.py`
  `_safe_market_data` pattern) — portfolio-relevant signals/odds; partial-failure-safe.
**Tests**: proxy routes + auth-required + brief leg partial-failure (≥6). **Guardrails**: gateway 401 guard,
`extra=allow` verbatim proxy.

### Wave E2 — frontend page enrichment ✅ DONE (2026-07-10)
**Status**: DONE. **Layer**: UI. **depends_on**: E1.
- **T-E-2-01 (impl)** — `ProbabilityChart` (NEW `components/prediction-markets/ProbabilityChart.tsx`,
  recharts `LineChart`, HEX palette mirroring `EarningsBarChart`, 1h/1d/1w shadcn Tabs toggle, loading/
  error/empty states) + `usePredictionMarketPriceHistory` TanStack hook + gateway
  `getPredictionMarketPriceHistory(conditionId, interval)`. Pure pivot/delta helpers in
  `probability-series.ts`. NOTE: added a SECOND history method rather than overloading the legacy
  days-based `getPredictionMarketHistory` (snapshots, consumed by the dashboard widget) — distinct
  response shapes.
- **T-E-2-02 (impl)** — **Detail view = right-side shadcn Sheet** (`MarketDetailSheet.tsx`) opened from a
  list row, NOT a `/[conditionId]` route — preserves the infinite-scroll list's scroll + filter state
  (a route push would unmount it). Shows chart, current YES/NO odds, liquidity/OI/24h-volume stats
  (OI honestly labelled "n/a" — not in S3 payload; liquidity from snapshot points), recent-flow strip
  from `/trades`, and the external Polymarket link via `buildPolymarketUrl`. **Signal badges**
  (`SignalBadge.tsx`): resolved/closed driven by `market.status` (list + detail); "moving" driven by a
  MEASURED YES Δpp ≥ 8pp from the visible interval's history (detail only — list rows don't fetch
  per-row history, so no unfounded badge). No "new" badge (list payload has no reliable created_at).
  **Event groupings** (`EventGroupings.tsx`): collapsible section fetching `/events`; renders group
  headers (name/category/market_count) collapsibly — child-market membership isn't on the wire yet
  (documented). **Entity approach = reverse edge**: `EntityPredictionsSection.tsx` on the intelligence
  sidebar via `/entities/{id}/predictions` with bullish-green/bearish-red/neutral-muted polarity +
  market link (the LIST payload carries no entity_ids, so per-market chips aren't possible — the reverse
  edge is higher-value). Extended `types/api.ts` + `lib/api/prediction-markets.ts` +
  `lib/api/prediction-markets-hooks.ts` (4 hooks).
**Tests**: 30 new Vitest tests across 6 files (probability-series pure maths, SignalBadge drivers, hooks
path+token-gating, ProbabilityChart states+toggle, EntityPredictionsSection render/polarity/link,
EventGroupings render/collapse). Full suite 3887 pass. ruff/eslint + tsc clean.

### Wave E3 — chat grounding ✅ DONE (2026-07-10)
**Status**: DONE. **Layer**: impl. **Effort**: 30m. **depends_on**: none.
- **T-E-3-01 (impl)** — In `handlers/market.py` (`_handle_get_prediction_markets`), each prediction
  `RetrievedItem` now sets `grounding_fields`: one `(<outcome>_probability, NN)` entry per outcome via
  the new `_probability_grounding_value` helper (emits the SAME integer percent the prose cites — e.g.
  price `0.63` → `"63"`, matching the `Yes 63%` text — never the raw 0..1 fraction), plus `volume_24h`
  (raw, coerced) and `market_id`. Empty-safe (no outcomes → `market_id`-only or `()`; never crashes).
  Metadata-only: text/citation rendering untouched, so it cannot reintroduce the phantom-citation refusal.
  New tests in `test_prediction_markets.py` (5): odds+volume populated, percentage-matches-text,
  empty-outcomes safe, no-volume, fully-empty market. ruff/mypy clean; 398 related unit tests pass.
**Tests**: grounding_fields populated from outcomes/volume; empty-safe (≥3). **Guardrails**: numeric-grounding
(don't reintroduce phantom-citation refusal — see 2026-07-03 refusal audit).

**Sub-Plan E COMPLETE** (E1, E2, E3 all DONE). **PLAN-0056 COMPLETE** — all 20 waves across
Sub-Plans A–E are done. Remaining validation: live Docker deploy + QA of the prediction-market chat
grounding and the full activation pipeline.

---

# Cross-cutting concerns

- **Contracts/migrations order**: Z (schemas) → A1/B3/C1 (migrations 043/0011/0066) → alert 0011 (D3).
  Verify each HEAD at implement time (R32). ⚠️ intelligence 0066 collision (see Overview).
- **Config**: 2 backfill env vars (B3) + move-threshold/liquidity-floor env (D1) + signal-score weights
  (D2) → all to `dev.local.env.example` + docker.env.
- **Observability**: metrics per PRD §13 (`polymarket_adapter_polls_total`, `…history_rows_inserted_total`,
  `…synthetic_documents_emitted_total`, `prediction_signals_emitted_total{trigger,direction}`,
  `s3_prediction_consumer_lag_seconds{topic}`); "Prediction Pipeline" Grafana board.
- **Docs**: update `services/market-data`, `services/content-ingestion`, `services/knowledge-graph`,
  `alert`, `api-gateway` `.claude-context.md` + `docs/services/*` + `docs/apps/worldview-web.md` +
  MASTER_PLAN data-flow, per touched wave (R15).

# Risk assessment

- **Critical path**: Z → B2 (synthetic docs) → C2/C3 (linking+polarity) → D2 → D3. The KG link is the
  keystone; nothing user-visible-as-signal works until C lands.
- **Highest risk**: C3 polarity LLM (quality + cost-tracking) and D1/D2 signal gating (noise). Mitigate
  with hard liquidity/volume floors, `neutral` default, and eval on a labelled market set.
- **Rollback**: each stream is independent (PRD §4.2); a failed adapter/consumer degrades one leg, not the
  page. Migrations have tested downgrades. Signals are additive (no existing behavior changed).
- **Testing gaps**: live Polymarket CLOB/Data responses vary — contract tests use captured fixtures;
  E2E needs a live poll window. Polarity correctness needs a human-labelled sample (QA phase).

# Compounding (post-implementation)
Per PRD §16: BP entries (CLOB closed-market granularity; plumbed-but-unused), `.claude-context.md` for
S3/S4/S7/alert, service docs, MASTER_PLAN diagram.

# Deploy fixes (2026-07-10) — local-validation blockers

Two blockers found during local Docker validation of the code-complete branch, both fixed (BP-720):

- **BLOCKER-1 (Sub-Plan C/D) — `kg-prediction-enriched-group` crash-loop (166 restarts).** The new
  `PredictionEnrichedConsumer` group read the ~20.6k-message historical `nlp.article.enriched.v1` backlog
  (written under the pre-C2b/C3 schema). The no-registry `fastavro.schemaless_reader` decodes those old
  records with the NEW reader schema → union misalignment (`IndexError` in `read_union`) → every old
  record dead-lettered → `dead_letter_cap` (5000) → forced restart forever. Fix (both): (1) the
  consumer is FORWARD-ONLY (needs only NEW polymarket synthetic docs; ZERO polymarket docs exist in the
  news backlog) → new config `kafka_prediction_enriched_consumer_auto_offset_reset="latest"` starts the
  fresh group at LATEST so it never reads the backlog; (2) resilient deserialize — `_handle_message`
  override catches the base `MalformedDataError`, logs it with the offset (`..._deserialize_skipped`),
  and advances past the poison/old-schema record. **Deploy op**: `auto.offset.reset` only applies with
  NO committed offset; the crash-loop OFF-path never committed (CURRENT-OFFSET was `-`), but as
  belt-and-suspenders the group was reset while it had no active members:
  `kafka-consumer-groups --group kg-prediction-enriched-group --topic nlp.article.enriched.v1
  --reset-offsets --to-latest --execute`. Verified live: 0 restarts / 0 dead-letters over ~70s, group
  at LATEST (LAG 0).
- **BLOCKER-2 (Sub-Plan B) — migration 0011 revision id > 32 chars.** The Wave B3 revision id
  `0011_seed_polymarket_wave2_sources` (34 chars) overflows `alembic_version.version_num varchar(32)`
  → `StringDataRightTruncationError` on a fresh DB (whole migration rolls back). Fix: renamed the id
  (and file) to `0011_seed_pm_wave2_sources` (26 chars ≤ 32); prefer shortening the id over widening
  the column. The live content_ingestion_db had a deploy-time `ALTER COLUMN … varchar(255)` workaround
  + the old 34-char id recorded — reconciled to the shortened id and reverted the column to varchar(32).
  Verified: `content-ingestion-migrate` sidecar exits 0 on the rebuilt image.

# QA fixes (2026-07-10) — Wave D1 correctness + prediction-data hygiene

Post-D1 QA of `PredictionMoveDetector` + the A1 prediction schema (market-data only; no wave-count change):

- **FIX 1 (HIGH, correctness) — affirmative-outcome move only.** The detector emitted one move per
  outcome; a binary Yes/No market cleared τ on BOTH tokens (equal-and-opposite Δ) → two events with the
  same `(market_id, window)`. S7's `PredictionSignalEmitter` dedups on a `uuid5` that omits `token_id`, so
  the pair collapsed to an arbitrary winner → for the No token, adverseness/polarity was computed
  backwards. Now emits **at most one** move per market per cycle, for the affirmative outcome (name
  `"yes"` case-insensitive, else the FIRST outcome in `market.outcomes` JSONB order — deterministic),
  tying the move to the exact frame the polarity classifier uses. Non-binary markets track only the
  affirmative/first outcome (accepted — Polymarket is overwhelmingly binary).
- **FIX 2 (MED, correctness) — true window-start baseline.** Δ was measured from `snapshots[-1]`, the
  oldest row of the `list_snapshots(limit=snapshot_limit)` DESC page — only the true window start when a
  market has ≤`snapshot_limit` in-window snapshots; beyond that the window silently shrank and slow moves
  fell under τ. New read-replica port+Pg method `get_earliest_snapshot_at_or_after(market_id, window_start)`
  (`ORDER BY snapshot_at ASC LIMIT 1`) supplies the authoritative baseline.
- **FIX 3 (LOW, data) — `prediction_markets.event_id` index.** Migration `044` (→043) adds partial index
  `ix_prediction_markets_event_id ON prediction_markets(event_id) WHERE event_id IS NOT NULL`.
- **FIX 4 (LOW, data) — hypertable retention.** `044` also registers a **180-day** `add_retention_policy`
  on `prediction_market_trades` (unbounded) + `prediction_market_prices`, guarded behind a
  timescaledb-extension check (no-op on plain Postgres) + `if_not_exists`; downgrade removes both.
- **Tests:** extended `test_prediction_move_detector.py` (binary→one affirmative event with No NOT emitted;
  no-"yes"→first outcome; >LIMIT window-start correctness; None window-start skip) + new
  `test_migration_044_*`. Validation: ruff + `mypy services/market-data/src` clean; full market-data suite
  1498 passed / 33 pre-existing e2e+integration+live errors (need live DB — `market_data_db` absent).

## QA fix (2026-07-10) — Waves C2b/C3: append additive Avro fields at the END (rolling-deploy safety, BP-720)

Waves C2b/C3 INSERTED `external_id` (and `source_title`) **MID-record** into three shared Avro records.
The platform deserializes with `fastavro.schemaless_reader` against the LOCAL reader schema — there is NO
Schema-Registry writer-schema resolution — so field decode is purely **POSITIONAL**. A rolling deploy where
the PRODUCER ships new bytes before a CONSUMER image upgrades would make the old consumer misread every
field after the insertion point (crash or SILENT corruption) across the
`content.article.raw.v1 → content.article.stored.v1 → nlp.article.enriched.v1` chain.

- **Fix:** moved `external_id` to the END of `content.article.raw.v1.avsc` and `content.article.stored.v1.avsc`,
  and moved BOTH `external_id` and `source_title` to the END of `nlp.article.enriched.v1.avsc` (type/default
  unchanged — nullable union `["null","string"]` default null). Updated the byte-identical service-local copy
  `services/content-ingestion/.../messaging/schemas/content.article.raw.v1.avsc`. Reordered the canonical model
  `CanonicalNlpArticleEnriched` field declarations + `to_dict` emission order to mirror the new avsc.
  Field COUNTS unchanged (reorder only) so `EXPECTED_FIELD_COUNTS` stays. Producers build event dicts BY NAME
  (S4 `fetch_and_write`/`emit_synthetic_prediction_document`, S5 `process_article`/`_build_stored_payload`,
  S6 `enriched_event`) and the outbox serializer loads the schema file, so serialization stays consistent with
  no producer code change; fastavro writes from a dict by schema order, so the emitted bytes are identical.
- **Why safe now:** the feature is NOT in production yet, so fixing field ORDER before any prod deploy means
  prod only ever sees the END-ordered schema. Local dev may hold a few mid-record messages in Kafka, but the
  enriched consumer is already start-at-latest + defensive-deserialize (BP-720 part 1/2) and content-store/S6
  resume at committed offset, so any transient local backlog is already handled — no additional code needed.
- **Tests:** `tests/contract/test_avro_schemas.py` (article field-count + C2b/C3 round-trip), plus
  `libs/contracts/tests/test_avro_alignment.py`, `test_avro_tenant_schemas.py`, `test_events_nlp_article_enriched.py`
  all pass (all field-set/name-based, order-independent). Service unit suites: content-store, content-ingestion,
  nlp-pipeline (1340 passed), knowledge-graph (1737 passed) all green. Pre-existing unrelated failures logged
  (`market.dataset.fetched`/`entity.narrative.generated.v1`/`entity.refresh.v1` count+envelope; content-store
  `test_enums.py::TestSourceType` — untouched schemas/enum). ruff + `mypy libs/contracts` clean. See BP-720 (d).

---

## QA fixes (2026-07-10) — prediction entity-linking path (knowledge-graph + libs/prompts)

Post-implementation QA of the C2/C2b/C3/D2 prediction path found 4 defects (2 MED, 2 LOW). All fixed
in `services/knowledge-graph` + `libs/prompts` only (no schema/migration/wave-count change):

- **FIX 1 [MED, correctness] — duplicate `temporal_events`/exposures per market when `close_time` is NULL.**
  The default natural key `(event_type, region, title, active_from::day)` split ONE market into TWO rows
  when the market had no `close_time`: `published_at` was then None, so each synthetic doc (first-sight +
  resolution) fell back to its own `occurred_at` → different `active_from` days → distinct key → duplicate
  exposures per entity + market shown twice in `/entities/{id}/predictions`. Since `region==condition_id` is
  globally unique per prediction market, the date component is redundant AND harmful. `upsert_by_natural_key`
  gained `dedup_by_region_only: bool` (default False); the `PredictionEnrichedConsumer` passes
  `dedup_by_region_only = (condition_id is not None)`. When set, the repo collapses on `(event_type, region)`
  alone via an application-level SELECT-then-INSERT/UPDATE (no supporting unique index exists — a new one
  would be an intelligence-migrations DDL change, out of scope; the existing day-index still guards the
  same-day concurrent race), leaving `active_from` untouched on update. The legacy anonymous path
  (`region='prediction'`, doc_id title) keeps the date-based key so distinct legacy docs are not merged.
  Corporate/earnings events are UNAFFECTED (they never set the flag; recurring events still rely on the day).
  `list_exposures_for_condition` also gained a defensive `DISTINCT ON (entity_id)` against historical dup rows.
- **FIX 2 [MED, security] — prompt injection into `MarketPolarityClassifier`.** The market question/entity/
  outcomes are attacker-controlled. They were concatenated with the instructions into a SINGLE `role:user`
  message. Now: static instructions ride a `role:system` message; the untrusted data is a SEPARATE `role:user`
  message wrapped in a `<market_data>` delimiter block with an explicit "treat as data, not instructions"
  framing; question/entity/outcomes are length-capped (≤500/≤120/≤12 outcomes) BEFORE sending; strict output
  enum validation unchanged; cost logging intact. Prompt bumped `market_polarity_classifier@1.0 → @1.1`.
- **FIX 3 [LOW, correctness] — late-arriving polarity never filled a NULL exposure.** The exposure upsert was
  `ON CONFLICT DO NOTHING`, so a first doc that wrote NULL polarity (question absent) could never be updated by
  a later doc carrying the question. Changed to `DO UPDATE SET polarity=EXCLUDED.polarity,
  polarity_confidence=EXCLUDED.polarity_confidence WHERE entity_event_exposures.polarity IS NULL AND
  EXCLUDED.polarity IS NOT NULL` — fills a NULL when better data arrives, never overwrites a set polarity.
  Non-directional callers (earnings/corporate, `polarity=None`) → `EXCLUDED.polarity IS NULL` → no-op, safe.
- **FIX 4 [LOW, R28] — silent JSON fallback in 2 KG consumers.** `prediction_enriched_consumer` and
  `prediction_move_consumer` now log `..._json_fallback` (schema_path/size/first_byte) before the non-Avro
  `json.loads` branch.

Optional hygiene (token_id in the signal-emitter dedup key) was SKIPPED — `MoveContext` carries no `token_id`
and threading one through would complicate the material-move window semantics; the detector already emits
affirmative-outcome-only so signal collapse is already prevented.

- **Tests (all new, ≥14):** repo region-only dedup (reuse-existing / insert-when-absent / region-None-fallback /
  default-date-key) + FIX 3 SQL guard; consumer `dedup_by_region_only` wiring + null-`close_time`-distinct-days
  + legacy-keeps-date-key + json-fallback-log; move-consumer json-fallback-log; classifier system/user split +
  crafted-injection-still-valid-enum + overlong-truncation; prompt `@1.1` version + hardening-line. Suites:
  knowledge-graph unit **1767 passed** (5 skipped, 2 xfailed), libs/prompts **308 passed**. ruff check+format
  clean; mypy `services/knowledge-graph/src` (5 files) + `libs/prompts/src` clean.

## QA fixes (2026-07-10) — final CI/correctness batch (alert + market-data + content-ingestion + content-store)

Final QA sweep of the PLAN-0056 prediction pipeline surfaced 2 CI blockers, 2 correctness/R24
fixes, and 2 low-severity hygiene items. All fixed on `feat/prediction-data-activation`; no
wave-count change.

- **FIX 1 [MED, CI blocker] — 4 market-data consumers missing from the dedup allowlist.**
  `PredictionHistoryConsumer` / `PredictionEventConsumer` / `PredictionTradeConsumer` /
  `PredictionOIConsumer` extend `BaseKafkaConsumer` and rely on natural-key idempotency
  (`ingestion_events.create_if_not_exists` + ON CONFLICT), so `is_duplicate()` returns False.
  Added all four to `tests/architecture/_consumer_dedup_allowlist.yaml` mirroring the
  `PredictionMarketConsumer` (BP-035) justification. `test_consumer_dedup_mixin_enforcement.py` GREEN.

- **FIX 2 [MED, CI blocker] — 2 KG consumers missing from `docker-compose.test.yml`.**
  `prediction_enriched_consumer_main` and `prediction_move_consumer_main` had prod containers but
  no test-topology entry. Added both to `docker-compose.test.yml` (profiles `[intelligence-test, all]`)
  mirroring the prod entries. `test_compose_alignment.py` GREEN.

- **FIX 3 [MED, correctness] — alert dedup collapsed distinct prediction markets for one entity.**
  `Alert.compute_dedup_key` was `sha256(entity_id:alert_type:window_bucket)`, so two DISTINCT markets
  about the same entity in one 300s window shared a key → one alert silently suppressed. Added an
  optional `discriminator` arg; `AlertFanoutUseCase` threads `market_id:trigger` for `AlertType.PREDICTION`
  only. Other alert types pass `discriminator=None` → key identical to the historical per-entity+type key
  (SIGNAL/GRAPH/CONTRADICTION collapse unchanged). Repeated moves on the SAME market still share a key and
  remain rate-limited by the upstream `PredictionRuleEvaluator` 1h per-market cooldown.

- **FIX 4 [MED, R24 pool-hold] — content-ingestion held a write session across Polymarket HTTP + MinIO I/O.**
  Both `_execute_polymarket_task` and `_execute_prediction_stream_task` bound the dedup callback to a
  session opened via `async with self._write_factory()` AROUND `adapter.fetch()`, pinning a write-pool
  connection for the entire paginated fetch + every MinIO put (the documented S4 pool-exhaustion→500 path).
  Fix: new `WorkerProcess._make_dedup_exists_fn()` returns a callback that opens+closes its OWN short-lived
  session per check (acquire→check→release), so NO connection is pinned across the fetch. The stream path
  additionally reads the source config in a short-lived session that CLOSES before I/O. Both paths verified.

- **FIX 5 [LOW] — Polymarket JSON not length-bounded + non-list guard.** The Gamma `/events` and Data-API
  `/trades` clients assigned a non-list body straight to the items list; a malformed body then crashed the
  whole task. Both now coerce a non-list body to an empty page and keep only dict items. Free-text fields
  (`question`/`title`/`category`/`name`) are `_truncate_text`-capped to 500 chars in
  `PredictionMarketFetchResult.from_gamma_response` and `PredictionEventFetchResult.from_gamma_response`
  before they enter the DTO → synthetic-doc body / Avro.

- **FIX 6 [LOW, stale test] — content-store SourceType enum drift.** Wave Z1 added 4
  `ContentSourceType` values (`polymarket_gamma_events`/`polymarket_clob`/`polymarket_data_trades`/
  `polymarket_data_oi`). `content-store/tests/unit/domain/test_enums.py::TestSourceType::test_all_sources`
  (SourceType re-exports `contracts.ContentSourceType`) expected the old set. Updated the expected set to
  reality; exhaustiveness guarantee preserved.

- **Tests (all new/adjusted):** alert — `TestPredictionDedupKey` (two distinct markets→2 alerts; same market
  repeated→dedup-suppressed; distinct trigger→split) + `TestComputeDedupKeyDiscriminator` (discriminator
  changes key; None==legacy key). content-ingestion — `test_worker_prediction_pool_hold.py` (dedup fn
  opens+closes per call; NO write session open during snapshot + stream fetch) + client non-list/non-dict
  guards (events + trades) + `from_gamma_response` truncation (market + event). content-store — enum set
  updated. Suites: alert unit, content-ingestion unit, content-store unit (374 passed) all GREEN;
  `tests/architecture` — the 2 CI blockers now pass (2 remaining failures are pre-existing and unrelated:
  TOPO-LIFESPAN nlp-pipeline R22 + pytest-marker on nlp-pipeline chunk-search test). ruff check+format clean;
  mypy `services/alert/src` (2 files) + `services/content-ingestion/src` (4 files) clean.

## QA fixes (2026-07-10) — live-instance QA batch (knowledge-graph + content-ingestion + alert)

Live-instance QA of the running prediction pipeline surfaced 3 defects that made whole feature
paths silently dead. All fixed on `feat/prediction-data-activation`; one new corrective sub-wave
(**B5**) added under Sub-Plan B for the deeper-stream work-list seeder.

- **BUG 1 [P0] — polarity classifier model 404 → every exposure neutral/0.0.** The default
  `polarity_classifier_model_id` was `Qwen/Qwen2.5-0.5B-Instruct`, which is **not served** on this
  DeepInfra account: `/chat/completions` returns HTTP 404 (`model_not_found`), which
  `MarketPolarityClassifier` swallows into the resilience default `("neutral", 0.0)`. So the entire
  "against a company" bullish/bearish exposure signal (Wave C3) degraded to neutral with 0 confidence
  for every market. Fix: default to the SAME served model the S6 relevance-scoring worker uses in the
  live config — `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` (verified HTTP 200 with the current
  `KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY` from inside `worldview-knowledge-graph-1`). Changed the default in
  both `config.py` and the classifier constructor + added a comment noting the 0.5B variant is unserved.
  `KNOWLEDGE_GRAPH_POLARITY_CLASSIFIER_MODEL_ID` override still applies. Cost note: 8B is larger than
  0.5B (a small per-call cost bump), but a working classifier is strictly better than a 404→neutral degrade.

- **BUG 2 [P0] → new Wave B5 — deeper-stream (CLOB/trades/OI) work-lists never populated.** Migration
  0011 seeds the `polymarket_clob` / `polymarket_data_trades` (`config["markets"]`) and
  `polymarket_data_oi` (`config["condition_ids"]`) sources EMPTY, and nothing ever filled them, so those
  adapters logged `polymarket_*_no_*` and returned `[]` → the deeper streams produced ZERO rows forever.
  Fix (**Wave B5 — deeper-stream work-list seeder**): new
  `SeedPredictionStreamWorklistsUseCase` (content-ingestion application layer) derives the
  `{condition_id, token_ids}` work-list from the base Gamma `/markets` fetch results (which already carry
  each market's `conditionId` + `clobTokenIds`) and upserts it into the three source configs. The worker
  calls it after `_emit_synthetic_documents(results)` in its own short-lived, best-effort session (never
  fails the snapshot task). **Only OPEN markets**, **capped** at
  `CONTENT_INGESTION_PREDICTION_STREAM_WORKLIST_MAX_MARKETS` (default 500) to bound the deeper-stream
  fetch fan-out, **idempotent** (writes only when the derived list differs from the stored one), and
  **deduplicated** on `condition_id`. No cross-service DB read (R9) — the base adapter already holds the data.

- **BUG 5 [P1] — alert intelligence-consumer perma-unhealthy on idle topics.** The consumer only touched
  its Docker-healthcheck heartbeat FILE in `__init__` and after each processed message. Its instance is
  assigned only currently-empty topics (`market.prediction.signal.v1`, `intelligence.contradiction.v1`),
  so with 0 messages the file froze at boot and the healthcheck (300s freshness window) reported
  `unhealthy` forever even though the poll loop was alive (observed live: heartbeat age ~12,676s,
  container `unhealthy`). Fix: refresh the heartbeat file on every idle poll cycle too — extracted
  `_write_heartbeat_file()` and call it from the `_record_progress()` override (the base loop's BP-700
  per-poll tick) in addition to `_touch_heartbeat()`. The message-progress marker
  (`_last_progress_monotonic`) is intentionally left untouched by the idle path, preserving "last message
  processed" semantics; the poll-cycle watchdog already gated on `last_poll_monotonic`.

- **Tests (14 new):** knowledge-graph — `TestServedModelDefault` (config default != unserved 0.5B, ==
  served model; env override still applies; classifier constructor default served). content-ingestion —
  `test_seed_prediction_stream_worklists.py` (worklist mapping; only-open; cap; dedup; blank skip; writes
  all 3 configs; idempotent no-write on re-run; empty batch no-write; preserves other config keys). alert
  — idle poll cycle refreshes heartbeat file (+ message marker unchanged) and processed-message advances
  both. Suites GREEN: KG classifier (19), content-ingestion seeder (9) + worker/config (46), alert
  entrypoints (16). ruff 0.4.0 check+format clean; mypy `services/{knowledge-graph,content-ingestion,alert}/src`
  touched files clean.
