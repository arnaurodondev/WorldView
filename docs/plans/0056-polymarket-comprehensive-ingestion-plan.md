---
id: PLAN-0056
title: "Prediction Markets: Activation, Signals & Enrichment (Wave 2)"
prd: PRD-0033
status: in-progress
created: 2026-05-01
updated: 2026-07-09
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

**Total: 6 sub-plans, 18 waves.** Keystone = Sub-Plan C (KG linking); signals (D) depend on it.

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

### Wave B1 — 4 clients + config settings + 4 adapters
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

### Wave B2 — SyntheticDocumentEmitter
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

### Wave B3 — worker routing + scheduler seeding + migration 0011 + env
**Layer**: config. **Effort**: 60m. **depends_on**: B1, B2.
- **T-B-3-01 (impl)** — Extend `worker._execute_polymarket_task` dispatch: map each new
  `ContentSourceType` → its client/adapter class.
- **T-B-3-02 (impl)** — Outbox dispatcher: map the 4 new outbox `event_type`s → their Avro serializers/topics.
- **T-B-3-03 (schema)** — content-ingestion migration `0011_seed_polymarket_wave2_sources.py`
  (`down_revision="0010_sec_edgar_cik_watchlist"`) seeding 4 new `sources` rows with per-adapter cadence.
- **T-B-3-04 (config)** — env vars `CONTENT_INGESTION_POLYMARKET_HISTORY_BACKFILL_DAYS=14`,
  `…TRADES_BACKFILL_DAYS=14` (+ `dev.local.env.example`, docker.env). Backfill gated by existing
  `CONTENT_INGESTION_BACKFILL_ON_STARTUP`.
**Tests**: routing dispatch per source type; scheduler seeds 4 sources; migration up/down (≥6).
**Guardrails**: R32 (0011 chained from verified 0010); compose-profile recreate gotcha (feedback memory).

---

# Sub-Plan C — S7 KG Activation (KEYSTONE)

**Goal**: turn NER-enriched synthetic docs into PREDICTION temporal events + entity exposures with
LLM-classified polarity, and expose them per entity. **Depends on**: B2 (synthetic docs flowing through
S6). Mirrors `EarningsCalendarDatasetConsumer` + `TemporalEventRepository.upsert_by_natural_key` +
`EntityEventExposureRepository.upsert`.

### Wave C1 — migration 0066: PREDICTION event type + exposure polarity
**Layer**: schema. **Effort**: 45m. **depends_on**: none (but verify HEAD per ⚠️ above).
- **T-C-1-01 (schema)** — intelligence-migrations `0066_prediction_event_type_and_exposure_polarity.py`
  (`revision="0066"`, `down_revision="0065"`): widen `ck_temporal_event_type` to include `'prediction'`
  (mirror `0018_add_corporate_event_type`); ALTER `entity_event_exposures` ADD `polarity varchar(20) null`,
  `polarity_confidence double precision null`. Downgrade drops prediction rows + columns.
**Tests**: migration up/down; CHECK accepts 'prediction'; columns present (≥3). **Guardrails**: R24
(intelligence_db DDL only via intelligence-migrations; S7 `ALEMBIC_ENABLED=false`), R32, ⚠️0066 collision note.

### Wave C2 — EventType.PREDICTION + PredictionEnrichedConsumer
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

### Wave C3 — MarketPolarityClassifier (LLM at link time)
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

### Wave C4 — S7 entity-predictions read API
**Layer**: API. **Effort**: 45m. **depends_on**: C2.
- **T-C-4-01 (impl)** — `GET /api/v1/entities/{entity_id}/predictions` (NEW) via a read-only use case on
  `ReadOnlyUnitOfWork`: join `entity_event_exposures`(polarity) → `temporal_events`(event_type='prediction')
  for the entity; return market_id, question, current implied prob, polarity, close_time. **R25/R27**.
**Tests**: returns linked markets w/ polarity; empty for unlinked entity (≥3). **Guardrails**: R27 ReadOnlyUoW.

---

# Sub-Plan D — Signals (S3 move → S7 signal → alert fanout)

**Goal**: fire score-gated prediction signals through the existing alert engine. **Depends on**: A
(snapshots/prices), C (exposures + polarity).

### Wave D1 — S3 PredictionMoveDetector worker
**Layer**: infrastructure. **Effort**: 75m. **depends_on**: A3.
- **T-D-1-01 (impl)** — `PredictionMoveDetector` (NEW) worker + `_main.py` in market-data: periodically
  scan `prediction_market_snapshots`/`_prices` per open market, compute Δ implied-probability over a
  window; **gate on liquidity + volume floor + |Δ|≥τ** (config env). On trigger emit
  `market.prediction.move.v1` (condition_id, token_id, prev/new price, delta, direction, liquidity, volume).
  Dedup per (market_id, token_id, window). **R9** (only its own DB). **R27** read replica for scans.
**Tests**: Δ above/below threshold; illiquid suppressed; dedup (≥5). **Guardrails**: BP-025 (worker cadence),
audit-return-persistence, config-driven thresholds (no hardcode).

### Wave D2 — S7 PredictionSignalEmitter
**Layer**: application. **Effort**: 75m. **depends_on**: C2, D1, Z1.
- **T-D-2-01 (impl)** — `PredictionSignalEmitter` (NEW): three triggers → `market.prediction.signal.v1`
  per affected **tracked** entity, computing `market_impact_score` (new-market: fixed base × confidence;
  material-move: scaled by |Δ| × liquidity; resolution: fixed) and reading `polarity` from the exposure:
  (1) **new-market** — on C2 exposure creation; (2) **material-move** — consume `market.prediction.move.v1`,
  join exposures by condition_id → one signal per linked entity; (3) **resolution** — on market status→resolved.
  Emits `subject_entity_id, market_id, trigger, market_impact_score, polarity, question, url`. Outbox (**R8**).
**Tests**: each trigger emits per-entity signal with correct score/polarity; no exposure → no signal (≥6).
**Guardrails**: R8 outbox; noise-gate (only tracked-linked entities); idempotency per (condition_id, trigger, window).

### Wave D3 — alert: subscribe + prediction type + rule toggle
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

### Wave E1 — S9 gateway routes + brief leg
**Layer**: API. **Effort**: 60m. **depends_on**: A4, C4.
- **T-E-1-01 (impl)** — Under existing `/v1/signals/prediction-markets/*` (`routes/intelligence.py`),
  add proxies: history `?interval=`, `/{id}/trades`, `/events`, `/events/{id}`, and expose `liquidity`/OI
  in the passthrough schemas (`schemas/prediction_markets.py`, `extra=allow`). Copy the `proxy_json_response`
  + `_auth_headers` pattern.
- **T-E-1-02 (impl)** — `GET /v1/entities/{id}/predictions` (NEW) proxy → S7 C4 endpoint.
- **T-E-1-03 (impl)** — Add a prediction leg to the morning-brief snapshot compose (`clients/dashboard.py`
  `_safe_market_data` pattern) — portfolio-relevant signals/odds; partial-failure-safe.
**Tests**: proxy routes + auth-required + brief leg partial-failure (≥6). **Guardrails**: gateway 401 guard,
`extra=allow` verbatim proxy.

### Wave E2 — frontend page enrichment
**Layer**: UI. **Effort**: 90m. **depends_on**: E1. **(use /implement-ui — heavy comments, shadcn/recharts, pnpm/vitest)**
- **T-E-2-01 (impl)** — `ProbabilityChart` (NEW, recharts `LineChart`, copy `EarningsBarChart` palette/tooltip
  pattern) + `usePredictionMarketHistory` TanStack hook + `gateway.getPredictionMarketHistory`; render on
  market detail with interval toggle.
- **T-E-2-02 (impl)** — Event groupings (fetch `/events`), entity-link chips (→ entity page, from
  `/entities/{id}/predictions` reverse or market payload), signal badges (adverse-move/new/resolved),
  liquidity/OI/recent-flow on detail. Extend `types/api.ts` `PredictionMarket` + `lib/api/prediction-markets.ts`.
**Tests**: Vitest — chart renders series, chips link, badges by signal, groupings (≥8). **Guardrails**:
frontend-comment-density (memory), CSS hsl(var()) no-paint (use hex in chart SVG), pnpm exact versions.

### Wave E3 — chat grounding
**Layer**: impl. **Effort**: 30m. **depends_on**: none.
- **T-E-3-01 (impl)** — In `handlers/market.py` (`~:2555`), set `grounding_fields` on the prediction
  `RetrievedItem` (per-outcome `{name}_probability`, `volume_24h`) mirroring `_grounding_fields_from_bars`,
  so the value-substantiation eval can verify odds (audit finding).
**Tests**: grounding_fields populated from outcomes/volume; empty-safe (≥3). **Guardrails**: numeric-grounding
(don't reintroduce phantom-citation refusal — see 2026-07-03 refusal audit).

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
