# Alert Signal Sources — Upstream Data/Event Map for 5 New Alert Types

**Date:** 2026-06-20
**Scope:** READ-ONLY investigation. For each of 5 requested alert types, map what upstream
signal the platform **already produces** that the alert service (S10) could consume to
evaluate the rule, and identify the GAP. This covers the **upstream signals only** — a
sibling agent covers the alert engine itself.
**Constraint reminder:** S10 consumes **Kafka events** or calls **internal REST** (R9: no
cross-service DB access).

---

## Executive Summary

| # | Alert signal | Source available today | Pattern S10 should use | Cheap or needs new emission? |
|---|--------------|------------------------|------------------------|------------------------------|
| 1 | **Stock price crosses X** | No price/quote/tick Kafka topic. Only `/internal/v1/price/{id}` + `/price/batch` REST; `market.dataset.fetched` is a batch claim-check, not per-instrument price | **PULL** — poll `/internal/v1/price/batch` (or PUSH from a new tick topic) | **NEEDS** new emission for true push; PULL works today with ~2–5 min latency |
| 2 | **Amount of news ≥ N** | `news_count_7d` computed in S6, exposed at `/internal/v1/instruments/{id}/news-rollup-7d`; per-article entity IDs flow on `nlp.article.enriched.v1` | **PULL** the rollup endpoint, **or PUSH** by counting `nlp.article.enriched.v1` | **CHEAP** — both an event (with entity IDs) and an API already exist |
| 3 | **Increase in news momentum** | Momentum (delta / delta_pct) computed query-time in S6 at `/api/v1/news/trending-entities`; not stored, not emitted | **PULL** the trending endpoint | **MOSTLY CHEAP** (API exists) but no event and no stored history → would need a new emitter for push |
| 4 | **Connection between two KG nodes** | `graph.state.changed.v1` flows (1924 msgs) and S10 **already consumes it**; `intelligence.contradiction.v1` exists but **0 messages ever emitted** | **PUSH** — already subscribed; needs payload enrichment to express "A↔B newly linked" | **CHEAP plumbing, GAP in semantics** — event signals "graph changed near X", not "A now connected to B" |
| 5 | **Fundamental metric crosses Y** | Fundamentals refresh ~every 6 days; only signal is `market.dataset.fetched` (dataset_type=fundamentals), a claim-check. No per-metric event. REST: `/api/v1/fundamentals/*` | **PULL** `/api/v1/fundamentals/timeseries` / `screen`, **or PUSH** off the dataset-fetched event then re-read | **NEEDS** new emission for clean push; coarse (multi-day) cadence regardless |

**Live Kafka topics confirmed** (`docker exec worldview-kafka-1 kafka-topics --list`): no
`market.quote.*`, `*.tick.*`, `*.ohlcv.*`, fundamentals-specific, news-count, or momentum
topic exists. Existing relevant topics: `market.dataset.fetched` (40,427 offsets — high
traffic), `graph.state.changed.v1` (1,924), `nlp.article.enriched.v1` (2,056),
`intelligence.contradiction.v1` (**0 — never emitted**), `intelligence.temporal_event.v1`,
`relation.type.proposed.v1`.

---

## Signal 1 — Stock price crosses X

**Where live/streaming price comes from**
- S2 (market-ingestion) polls EODHD `/api/real-time/:ticker`, stores quotes to MinIO
  (bronze + canonical), and publishes a **batch** `market.dataset.fetched` event
  (claim-check). S3 (market-data) `QuotesConsumer` materialises into the `quotes` table and
  caches in Valkey (60s TTL).
- **There is no per-instrument price-tick or quote Kafka topic.** `market.dataset.fetched`
  is a dataset-level claim-check (pointer to MinIO), keyed by `symbol` + `dataset_type`, not
  a streamed last-price. `market.instrument.updated` carries only capability flags
  (`has_ohlcv`/`has_quotes`/`has_fundamentals`), not prices.

**Cadence / latency**
- Adaptive poll by symbol tier: T0 ≈ 5 min base, freshness TTL = **240 s** (skips re-fetch
  if last success < 4 min). End-to-end "latest price" freshness ≈ **2–5 min**.
- Source: `services/market-ingestion/src/market_ingestion/domain/freshness.py` (quote TTL
  240s, line ~27); S3 cache TTL 60s in `api/routers/quotes.py`.

**Internal REST (what S10 can poll)**
- `GET /internal/v1/price/{instrument_id}` → `PriceSnapshotResponse` (enriched quote with
  OHLCV fallback, Valkey cache-aside). File:
  `services/market-data/src/market_data/api/routers/price_snapshot.py:169`.
- `POST /internal/v1/price/batch` (up to 50 instruments; `?include_missing=true` for explicit
  nulls). File: `price_snapshot.py:192`.
- Public variants: `GET /api/v1/quotes/{instrument_id}`, `GET /api/v1/quotes/latest`,
  `POST /api/v1/quotes/batch` (`api/routers/quotes.py`).

**Keying:** `instrument_id` (UUID). `quotes` table has no symbol column; resolve
ticker/symbol → `instrument_id` via S1/S9 first. `instruments.entity_id` optionally links to
the S7 entity.

**GAP:** No push stream for prices. A level-cross is inherently tick-driven, but the platform
only refreshes prices on a 2–5 min poll, so even a push event could not fire faster than the
ingest cadence.

**Recommendation (cleanest for S10): PULL.**
S10 polls `POST /internal/v1/price/batch` with the set of watched instruments on a short
cadence (e.g. 30–60 s) and evaluates the cross by comparing the new last-price against the
previous one it stored (the "cross" needs prev→curr, which only S10 has). This rides existing
infrastructure with no new upstream emission. A future push optimisation (new
`market.quote.ticked.v1` emitted by S2 per canonical row) is **optional** and bounded by the
same 2–5 min freshness — not worth it until intraday cadence tightens.

---

## Signal 2 — Amount of news ≥ N

**Where per-entity news counts live**
- `news_count_7d` = `COUNT(DISTINCT doc_id)` per entity over a trailing 7-day window from
  `entity_mentions`, computed in S6 by `GetNewsRollup7dUseCase`
  (`services/nlp-pipeline/src/nlp_pipeline/application/use_cases/news_rollup_7d.py`).
- Exposed at S6 internal REST:
  `GET /internal/v1/instruments/{instrument_id}/news-rollup-7d` →
  `{news_count_7d, llm_relevance_7d_max, display_relevance_7d_weighted}`
  (`api/routes/internal_news_rollup.py`; X-Internal-JWT required, read-replica per R27).
- Also materialised nightly into S3 `instrument_fundamentals_snapshot.news_count_7d` by
  `sync_intelligence_rollup` (a copy, ~12–18 h stale — do **not** use this for alerts).

**Window variants:** only **7d** today. No 24h/30d rollup endpoint yet (extension would be a
new S6 endpoint).

**Push option — already flowing:** `nlp.article.enriched.v1` (live, 2,056 offsets) carries
`resolved_entity_ids` (array of canonical entity UUIDs) per article — one event per article.
S10 could subscribe and increment a per-entity rolling count.
- Schema: `infra/kafka/schemas/nlp.article.enriched.v1.avsc` (field `resolved_entity_ids`).

**Cadence / latency**
- Event path: near-real-time (per article as enrichment completes).
- API path: query-time, ~100 ms, exact 7d window.

**Keying:** `entity_id` (= `instrument_id` for instrument-type entities).

**GAP:** None blocking. Only 7d window exists; other windows need a new S6 endpoint. The
push path requires S10 to maintain its own rolling counter (the event has no precomputed
count).

**Recommendation (cleanest for S10): PULL the rollup endpoint** for the threshold check
(`news_count_7d ≥ N`), evaluated on a schedule (e.g. hourly) per watched entity — simplest,
exact, no state to maintain. Use the `nlp.article.enriched.v1` **event as a trigger** (only
re-check entities that just received an article) to avoid blind polling. This is the cheapest
of the five: both an event and an API already exist.

---

## Signal 3 — Increase in news momentum

**What computes momentum**
- S6 `GetTrendingEntitiesUseCase`
  (`services/nlp-pipeline/src/nlp_pipeline/application/use_cases/trending_entities.py`):
  - `count` = articles for the entity in `[now-W, now]`
  - `prior_count` = articles in `[now-2W, now-W]`
  - `delta = count - prior_count`; `delta_pct = 100 * delta / max(prior_count, 1)`
  - Ranked by `delta_pct DESC, count DESC`, filtered by `min_count` (default 2).
  - Windows W ∈ {24, 72, 168} hours.
  - SQL: `infrastructure/nlp_db/repositories/trending_entities_query.py`.
- Exposed at `GET /api/v1/news/trending-entities?window_hours=&limit=&min_count=`
  (`api/routes/trending_entities.py:122`). Response includes per-entity `count`,
  `prior_count`, `delta`, `delta_pct`, `ticker`, `name`, `top_article`.

**Stored / emitted?** Neither. Momentum is computed **fresh per query**, not persisted, and
**no Kafka topic** carries it. There is no precomputed spike/delta history.

**Cadence / latency:** query-time only. Comparison window already encodes the "increase"
(curr vs prior), so the endpoint directly answers "is momentum up?".

**Keying:** `entity_id` (canonical UUID).

**GAP:** No event, no stored series. S10 must either poll the trending endpoint or cache its
own snapshots if it wants longer-baseline deltas than the built-in prior-window.

**Recommendation (cleanest for S10): PULL** `GET /api/v1/news/trending-entities`
(`window_hours=24`, large `limit`) on a schedule (e.g. hourly), and threshold on `delta_pct`
(and `count ≥ min_count` to suppress 1→2 noise). The endpoint's prior-window baseline already
expresses "increase", so S10 needs no historical store. A future
`nlp.entity.momentum.v1` hourly emitter would convert this to push and offload S6, but is not
required for v1. Mostly cheap (API exists); the only missing piece for push is an emitter.

---

## Signal 4 — Connection between two KG nodes

**What S7 emits today**
- `graph.state.changed.v1` — emitted via the S7 outbox in the graph-write block whenever
  relations/evidence/events are materialised for a document
  (`services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py:663`).
  Schema (`infra/kafka/schemas/graph.state.changed.v1.avsc`) carries:
  `primary_entity_id`, `affected_entity_ids[]`, `relation_ids[]`, `canonical_types[]`,
  `change_type` (`new_evidence | confidence_update | invalidation | contradiction`),
  `source_doc_id`, `is_backfill`. **Live: 1,924 offsets.**
- `intelligence.contradiction.v1` — emitted by the contradiction block
  (`application/blocks/contradiction.py:141`) with `subject_entity_id`, `claim_type`,
  `new_claim_id`, `contradicting_claim_id`, `contradiction_strength`,
  `affected_relation_ids[]`. **Live: 0 offsets — never emitted in this environment** (the
  contradiction pipeline produces nothing yet; consistent with the recently-fixed
  relation/contradiction work). The schema doc explicitly says "S10 uses is_backfill to
  suppress fan-out".
- `relation.type.proposed.v1` — novel relation types with no canonical mapping.

**S10 already consumes this.** `services/alert/.../consumers/intelligence_consumer.py`
subscribes to `nlp.signal.detected.v1`, `graph.state.changed.v1`, and
`intelligence.contradiction.v1`, routing `graph.state.changed` → `AlertType.GRAPH_CHANGE`
and `intelligence.contradiction` → `AlertType.CONTRADICTION`
(`intelligence_consumer_main.py:193`). So the **plumbing is already in place**.

**Cadence / latency:** push, near-real-time via S7 outbox dispatcher (fires as documents are
materialised into the graph).

**Keying:** `primary_entity_id` (partition key) + `affected_entity_ids[]`; relation identity
via `relation_ids[]`.

**GAP (semantic, not plumbing):** The event signals "the graph changed *around* entity X"
(`change_type=new_evidence`, plus the set of affected entities and relation IDs). It does
**not** explicitly assert "entity A is now newly connected to entity B" as a first-class
field. To fire a rule like *"alert when A becomes connected to B"*, S10 must either:
1. On each `graph.state.changed.v1`, check whether the watched pair (A,B) is in
   `affected_entity_ids` together with a new `relation_id`, then **confirm via an S7 API
   query** that the A↔B edge now exists (the event alone does not carry the subject→object
   pair of each new edge); or
2. Periodically query the S7 pairwise-path / relation API for the watched (A,B) pair.

**Recommendation (cleanest for S10): PUSH + confirm.** Subscribe to the already-flowing
`graph.state.changed.v1` (no new infra), use `affected_entity_ids` as a cheap pre-filter to
wake only on changes touching a watched entity, then **confirm the specific A↔B edge via an
S7 read** before firing. The lowest-effort upstream improvement (if exact pair-matching from
the event alone is desired) is to **enrich `graph.state.changed.v1` with the
subject/object pairs of newly-created edges** (add a forward-compatible
`new_edges: array<{subject_id, object_id, relation_type}>` field with a default). Note
`intelligence.contradiction.v1` is wired end-to-end but currently silent — depends on the
contradiction pipeline actually producing.

---

## Signal 5 — Fundamental metric crosses Y

**Where fundamentals live**
- S2 polls EODHD `/api/fundamentals/:ticker`; S3 `FundamentalsConsumer` materialises into
  ~18 section tables plus the flattened `fundamental_metrics`
  (`instrument_id, metric, period_type, as_of_date, value`) and the one-row-per-instrument
  `instrument_fundamentals_snapshot` (carries `pe_ratio`/`eps_ttm`/`analyst_target_price`
  etc.).
- Consumer: `services/market-data/.../consumers/fundamentals_consumer.py`.

**Cadence / latency:** freshness TTL = **518,400 s ≈ 6 days**
(`market-ingestion/.../freshness.py`). Refresh is opportunistic (scheduler-driven), no
dedicated intraday worker. Effective alert cadence is **multi-day** — fundamentals barely
move intraday, so this is by design.

**Emitted as event?** No fundamentals-specific event. The only signal of a refresh is
`market.dataset.fetched` with `dataset_type="fundamentals"` (a claim-check pointing to MinIO;
high-volume topic, 40,427 offsets across all dataset types). `instrument_fundamentals_snapshot.updated_at`
is bumped on materialisation but is DB-only (cross-service DB read is forbidden by R9).

**Internal REST (what S10 can poll)**
- `GET /api/v1/fundamentals/timeseries?instrument_id=&metric=pe_ratio` — historical series
  for one metric.
- `POST /api/v1/fundamentals/screen` — threshold filters across metrics (e.g.
  `pe_ratio_min/max`) returning matching instruments.
- `GET /api/v1/fundamentals/metrics/{instrument_id}` — available metric names.
- `POST /api/v1/fundamentals/batch` — up to 25 tickers.
- Files: `api/routers/fundamental_metrics.py`, `api/routers/fundamentals.py`.

**Keying:** `instrument_id` (UUID).

**GAP:** No per-metric "value changed / crossed" event. To express "P/E crosses 30", S10
needs prev→curr for the metric (only S10 holds the previous value across refreshes).

**Recommendation (cleanest for S10): event-triggered PULL.** Subscribe to
`market.dataset.fetched`, filter to `dataset_type="fundamentals"`, resolve `symbol` →
`instrument_id`, then **read the metric via `GET /api/v1/fundamentals/timeseries`** (or
`/metrics`) and compare against the last value S10 stored to detect the cross. This fires only
when fundamentals actually refresh (no wasteful polling) and rides existing topics + APIs. If
the dataset-fetched filter proves too coarse, the clean upstream addition is a
`market.fundamental.updated.v1` event (`instrument_id`, `metric`, `old_value`, `new_value`,
`period_type`) emitted by the S3 `FundamentalsConsumer` after materialisation — but this is an
optimisation, not a blocker. Cadence is fundamentally coarse (~6 days) regardless of pattern.

---

## Cheap vs. needs-new-upstream-emission

**Cheap (signal already flows — minimal upstream work):**
- **Signal 2 (news ≥ N):** both `nlp.article.enriched.v1` (with `resolved_entity_ids`) and
  the `/internal/v1/instruments/{id}/news-rollup-7d` endpoint exist.
- **Signal 4 (KG connection):** `graph.state.changed.v1` flows and S10 **already subscribes**;
  only a semantic confirm-query (or a small forward-compatible payload field) is needed.
- **Signal 3 (momentum):** the `/api/v1/news/trending-entities` endpoint already computes the
  delta; PULL works today (event/push would need a new emitter, optional).

**Needs new upstream emission for clean push (PULL works today as fallback):**
- **Signal 1 (price cross):** no price stream — S10 polls `/internal/v1/price/batch`; bounded
  by 2–5 min ingest cadence either way.
- **Signal 5 (fundamental cross):** no per-metric event — S10 triggers off
  `market.dataset.fetched (fundamentals)` then re-reads via fundamentals REST; ~6-day cadence.

---

## Key file references

- Topic constants: `libs/messaging/src/messaging/topics.py`
- Schemas: `infra/kafka/schemas/{graph.state.changed.v1,intelligence.contradiction.v1,nlp.article.enriched.v1,market.dataset.fetched,market.instrument.updated,relation.type.proposed.v1}.avsc`
- S10 intelligence consumer (already subscribes graph/contradiction): `services/alert/src/alert/infrastructure/messaging/consumers/intelligence_consumer.py`, `intelligence_consumer_main.py:193`
- Price (S3): `services/market-data/src/market_data/api/routers/price_snapshot.py`, `api/routers/quotes.py`
- Fundamentals (S3): `services/market-data/src/market_data/api/routers/fundamental_metrics.py`, `.../consumers/fundamentals_consumer.py`
- Freshness/cadence (S2): `services/market-ingestion/src/market_ingestion/domain/freshness.py`
- News count (S6): `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/news_rollup_7d.py`, `api/routes/internal_news_rollup.py`
- Momentum (S6): `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/trending_entities.py`, `api/routes/trending_entities.py:122`
- KG emission (S7): `services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py:663`, `application/blocks/contradiction.py:141`

## Live verification (2026-06-20)

- Kafka topics confirmed via `docker exec worldview-kafka-1 kafka-topics --list`; no price/quote/tick/ohlcv/fundamentals-specific/news-count/momentum topic exists.
- Offsets (cumulative): `market.dataset.fetched`=40,427; `graph.state.changed.v1`=1,924; `nlp.article.enriched.v1`=2,056; `intelligence.contradiction.v1`=**0** (never emitted in this environment).
