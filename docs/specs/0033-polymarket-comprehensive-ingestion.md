# PRD-0033 — Prediction Markets: Activation, Signals & Enrichment (Wave 2)

| Field | Value |
|---|---|
| **Created** | 2026-04-29 |
| **Re-scoped** | 2026-07-09 (activation-first rewrite; see §0) |
| **Owner** | Arnau Rodon |
| **Status** | DRAFT (ready for /plan) |
| **Supersedes** | Extends PRD-0019 (Polymarket Wave 1, shipped) |
| **Drives** | PLAN-0056 (to be regenerated against this re-scope) |
| **Affects services** | S3 market-data (owns prediction storage — extended with price-history / trades / OI + polarity + delta signals), S4 content-ingestion (new adapters for the 4 deeper streams + synthetic-document emitter), S6 nlp-pipeline (unchanged — reused via synthetic docs), S7 knowledge-graph (`EventType.PREDICTION` temporal events + `entity_event_exposures` carrying polarity — no new entity nodes), alert service (new `prediction` signal subtype), S9 api-gateway (new read endpoints + brief leg), worldview-web (enhanced `/prediction-markets` page + chat) |
| **Doesn't affect** | S1 portfolio (read-only consumer of signals via existing alert surface), S2 market-ingestion, S5 content-store, S8 rag-chat internals (tool already exists; only grounding metadata extended) |

---

## 0. Re-scope note (2026-07-09)

This PRD was originally drafted (2026-04-29) as an **ingestion-first, greenfield** plan that
built six new prediction tables in S7 `intelligence_db` and treated `market.prediction.v1`
as having **no consumer**. Both premises are now false, and the product intent has sharpened.
This rewrite corrects them. See `docs/audits/2026-07-09-prediction-data-enhancement-investigation.md`
for the full current-state analysis that motivated the change.

**What changed and why:**

1. **`market.prediction.v1` already has a consumer.** S3 market-data consumes it and owns
   `prediction_markets` (current state) + `prediction_market_snapshots` (a TimescaleDB
   hypertable of per-outcome prices over time), plus a read API (`/prediction-markets`,
   `/{id}`, `/{id}/history`, `/categories`), the S9 proxy, a frontend page, a dashboard
   widget, and a chat tool (`get_prediction_markets`). MASTER_PLAN records S3 as the consumer.
   → **We extend S3, we do NOT rebuild storage in S7.** The original §3.4 (6 tables in
   `intelligence_db`) is **withdrawn**.

2. **Category + wrong-link work already shipped** (PLAN-0068 category backfill; commit
   `332586d03` centralized `buildPolymarketUrl` → canonical `/event/{slug}`). These are
   **not in scope** here.

3. **Product intent is activation, not raw ingestion.** Prediction data must be BOTH a
   user-facing surface (charts + chat + enhanced page) AND a signal output (a new/moving
   market against a tracked entity fires a signal that merges into the KG and reaches the
   user via alerts + brief). Raw ingestion of deeper Polymarket streams is subordinated to
   an **80/20 rule**: a stream is ingested only if it demonstrably (a) merges into the KG or
   a user-facing surface and (b) reaches the user. Streams that fail the bar are dropped.

**User-confirmed design decisions (2026-07-09):**
- Deeper market data (CLOB price-history, trades, OI) is **co-located in S3 market-data**,
  next to the existing prediction tables — not duplicated in S7.
- **All four deeper streams pass the 80/20 bar**: CLOB `/prices-history`, Gamma `/events`,
  Data `/trades`, Data `/oi` (surfacing justified per-stream in §4).
- Signal direction (**polarity**) is modelled: an LLM step at entity-link time classifies each
  `(market-outcome, entity)` pair as `bullish | bearish | neutral` for that entity, stored on
  the KG `references` relation. This is what turns "odds moved" into "odds moved *against* a
  holding".
- A prediction market is **unified with the existing temporal-event model** (`EventType.PREDICTION`
  in S7 `temporal_events`) so it appears on the entity timeline alongside earnings/macro events.
- Prediction signals route through the **existing alert engine** as a `prediction` signal
  subtype (not a bespoke alert subsystem).

---

## 1. Context and motivation

### 1.1 Where prediction markets sit today (accurate baseline)

PRD-0019 (Wave 1, shipped 2026-04-09) delivered an end-to-end, read-only vertical:

- **S4 content-ingestion** polls the Polymarket **Gamma `/markets`** endpoint (~5-min cadence),
  stores raw JSON to MinIO bronze, dedups via `prediction_market_fetch_log`, and publishes
  `market.prediction.v1`.
- **S3 market-data** consumes that topic into `prediction_markets` (current state, upserted) and
  `prediction_market_snapshots` (TimescaleDB hypertable; per-poll `outcomes_prices`, `volume_24h`,
  `liquidity`). Ports: `PredictionMarketRepository`, `PredictionMarketSnapshotRepository`.
- **S3 read API**: `GET /prediction-markets`, `/{id}`, `/{id}/history`, `/categories`.
- **S9** proxies these; **worldview-web** renders a dashboard widget + a `/prediction-markets`
  page (canonical `/event/{slug}` links); **rag-chat** exposes `get_prediction_markets`.

So we already capture and serve a genuine price **time-series** (our polling density) and current
market metadata. What we have is a **read-only ornament**: it is displayed but never *operationalized*.

### 1.2 What's missing (the gap this PRD closes)

1. **No KG entity linking.** Market questions never run through S6 NER; `entity_ids`/`tickers` are
   empty. A market "Will NVDA exceed $200?" is not linked to the NVDA entity → cannot be found from
   the entity page, cannot inform chat about an entity, cannot drive a signal. **Biggest gap.**
2. **No signals / alerts.** A new market against a tracked company, or a large adverse probability
   swing, produces nothing. Prediction data is not a signal.
3. **No brief inclusion.** Portfolio-relevant odds never surface in the daily brief.
4. **Thin page.** `/prediction-markets` is a flat list — no probability chart (despite the history
   API existing), no event groupings, no entity links, no signal context.
5. **Shallow data.** Only Gamma snapshot metadata; no pre-ingestion price history, event groupings,
   order flow, or open interest — each of which has a concrete user/KG payoff (§4).
6. **`liquidity` stored but unexposed** in S3/S9 schemas (plumbed-but-unused).

### 1.3 Why now

- **Thesis differentiator.** Real-money prediction data is rare, well-priced, free, and
  uncorrelated with the news/fundamentals signals already in the platform — and, once linked to the
  KG, it becomes a *cross-domain* signal (the crowd pricing a risk about an entity you hold).
- **Free API surface.** All three Polymarket APIs (Gamma, CLOB, Data) are public, no auth, generous
  limits (§4.3).
- **The join key is already in bronze.** Every Gamma `/markets` response we already fetch contains
  `clobTokenIds` per outcome, so the CLOB history pull has no discovery cost.

---

## 2. Goals & non-goals

### 2.1 Goals

- **G1 — Merge prediction markets into the KG.** Every ingested market is entity-linked via S6 NER;
  `entity_event_exposures` link each market to referenced entities, carrying a per-entity **polarity**.
- **G2 — Prediction markets as temporal events.** Each linked market becomes an
  `EventType.PREDICTION` row on the entity timeline, carrying current implied probability.
- **G3 — Three signal types, score-gated, routed through the existing alert engine:**
  new-market-against-entity, material adverse move, resolution.
- **G4 — Enrich the user surfaces:** probability chart + event groupings + entity links + signal
  context on `/prediction-markets`; odds in chat with proper grounding; portfolio-relevant odds in
  the brief.
- **G5 — 80/20 deeper ingestion in S3:** CLOB price-history (backfill + finer granularity), Gamma
  events, Data trades, Data OI — each surfaced (§4), none ingested "just because".

### 2.2 Non-goals

- Rebuilding prediction storage in S7 (withdrawn — S3 owns it).
- Wallet-level data (`/positions`, `/leaderboards`), real-time WebSocket, order-book depth
  (`/book`) beyond what a signal needs, ML signal *training* (this PRD provides the substrate + a
  deterministic/LLM-labelled signal, not a learned model).
- Re-doing category normalization or link-building (shipped).

---

## 3. Functional requirements

| # | Requirement |
|---|---|
| FR-1 | S4 emits one **synthetic document** (`content.article.raw.v1`, `source_type='prediction_market'`) per market on first-sight and one on resolution; S6 NER links entities unchanged. |
| FR-2 | S7 creates one `temporal_events(event_type='prediction')` row per entity-linked market and one `entity_event_exposures` row per referenced entity (earnings pattern) — no new entity nodes. |
| FR-3 | At link time, an LLM step (`MarketPolarityClassifier`) classifies each `(market, referenced-entity)` polarity (`bullish/bearish/neutral`) and stores it on the `entity_event_exposures` row. |
| FR-4 | S7 upserts each entity-linked market as an `EventType.PREDICTION` `temporal_events` row (current implied probability + close date), mirroring the `EarningsCalendarDatasetConsumer` pattern. |
| FR-5 | S3 ingests the 4 deeper streams (CLOB prices-history, Gamma events, Data trades, Data OI) into new S3 tables co-located with `prediction_markets`; `liquidity` is exposed in S3+S9 schemas. |
| FR-6 | A **delta-signal worker** computes new-market / material-move / resolution signals, gated on entity-link + liquidity/volume floor + Δ threshold + polarity, and emits them to the alert engine as `signal_type='prediction'`. |
| FR-7 | S9 exposes read endpoints for markets/events/history/trades and `GET /entities/{id}/predictions`; the dashboard/brief snapshot gains a prediction leg. |
| FR-8 | `/prediction-markets` page renders a probability chart (history API), event groupings, entity links, and signal badges; chat odds carry `grounding_fields`. |
| FR-9 | Every signal is idempotent and score-gated; no signal fires for a market not linked to a tracked entity. |

---

## 4. Polymarket API surface to ingest (80/20)

### 4.1 Reality check (verified against docs during original drafting; unchanged)

- https://docs.polymarket.com/ · `/developers/CLOB/timeseries` · `/developers/gamma-markets-api/gamma-structure` · `/quickstart/introduction/rate-limits`

### 4.2 Endpoint map — each ingested stream justified by its user/KG payoff

| API | Endpoint | Today | This PRD | 80/20 justification (surface + KG) |
|---|---|---|---|---|
| Gamma | `/markets` | ✅ 5-min poll (S4→S3) | keep | baseline |
| Gamma | `/events` | ❌ | **ADD** (1-h) | Groups related markets (all 2028-candidate markets → one event). Powers page event-grouping UX + KG `belongs_to_event` hierarchy. Cheap, metadata-only. |
| CLOB | `/prices-history` | ❌ | **ADD** (backfill + 6-h) | Pre-ingestion probability history + finer granularity than our polling. Powers the page **probability chart** and "how did the odds move" in chat; feeds the **move-signal**. Primary temporal source. |
| Data | `/trades` | ❌ | **ADD** (1-h, per-market cursor) | Anonymous fills → order-flow. Surfaced as a "recent activity / flow" strip on the market detail and as a **conviction weight** on the move-signal (a move on real volume outranks a quote flicker). |
| Data | `/oi` | ❌ | **ADD** (daily) | Open interest = positioning/conviction, 1 row/market/day. Surfaced as a "conviction" stat on the market detail and as a secondary gate on signals. |
| Gamma | `/tags`, `/series` | ❌ | skip | category already normalized (PLAN-0068). |
| CLOB | `/book`, `/price(s)` | ❌ | skip | order-book depth not needed; `/prices-history` covers odds. |
| Data | `/holders`, `/positions`, `/leaderboards`, `/activity` | ❌ | skip | wallet-level / redundant; no user surface. |

### 4.3 Rate-limit budget (unchanged — total ≤ 5% of any bucket)

Gamma global 4,000/10s (we < 50), CLOB global 9,000/10s (< 200 burst / < 50 sustained), Data global
1,000/10s (< 50). **No throttling required**, but each adapter MUST honor 429 with exponential
backoff (`Retryable`).

### 4.4 Historical availability (verified)

- Open markets: 1m/1h/6h/1d/1w via CLOB `/prices-history`. Resolved markets: granularity ≥ 12 h →
  use `interval=1d` (GitHub issue #216). `/orderbook-history` stopped emitting Feb 20 2026 — DO NOT USE.
- Backfill horizon: Polymarket retains indefinitely. 6-month `/prices-history?interval=1h` ≈ 4,380
  points/market; ~3,000 active+recent markets ≈ ~13M rows (bounded; see §11).

---

## 5. Architecture — reuse, don't rebuild

The design rides the **same rails as news** (`document → S6 NER → KG relations + impact scoring →
score-gated alert → brief`), with **one addition news lacks**: a continuous price time-series (S3
snapshots) that makes a **material-move** trigger first-class.

```
                                deeper streams (CLOB/events/trades/OI)
[Gamma /markets] ─5min─►  S4 ──► market.prediction.v1 ───────────► S3 market-data
[Gamma /events]  ─1h──►  adapters ► market.prediction.event.v1 ──► S3 (prediction_events)
[CLOB history]  backfill+6h ► market.prediction.history.v1 ─────► S3 (prediction_market_prices)
[Data /trades]  ─1h──►             market.prediction.trade.v1 ───► S3 (prediction_market_trades)
[Data /oi]      ─daily► |          market.prediction.oi.v1 ──────► S3 (prediction_market_oi)
                        |
                        └─► NEW S4 SyntheticDocumentEmitter (per market, first-sight + resolution)
                              └─► content.article.raw.v1 (source_type='prediction_market')
                                    └─► S6 ArticleProcessingConsumer (UNCHANGED)
                                          └─► nlp.article.enriched.v1
                                                └─► S7 knowledge-graph:
                                                      • prediction_market/-event nodes
                                                      • temporal_events(prediction) + exposures + POLARITY (LLM)
                                                      • EventType.PREDICTION temporal_events
                                                                    │
                        S3 snapshots (price time-series) ───────────┤
                                                                    ▼
                                          NEW PredictionDeltaSignalWorker (in S3 or a small worker):
                                            new-market | material-move | resolution
                                            gated: entity-linked + liquidity/vol floor + Δ + polarity
                                                                    │
                                                                    ▼
                                            alert engine (signal_type='prediction') ──► alerts + brief + page badges
```

**Ownership split:**
- **S3 market-data** owns all raw prediction data (markets, snapshots, prices, events, trades, OI)
  and the move-signal computation (it has the time-series).
- **S7 knowledge-graph** owns the *graph projection*: `EventType.PREDICTION` temporal events +
  `entity_event_exposures` (carrying polarity) linking each market to referenced entities.
- **alert service** owns signal routing/gating/dedup as an existing surface.

---

## 6. Data model changes

### 6.1 S3 market-data — NEW tables (co-located; `market_data_db`, TimescaleDB)

> `prediction_markets` and `prediction_market_snapshots` **already exist** — unchanged except
> exposing `liquidity` (already stored) through the S3 read schema.

| Table (NEW) | Partition | Key columns |
|---|---|---|
| `prediction_market_prices` | monthly on `window_start_ts` | `(condition_id, token_id, interval, window_start_ts) PK, price, source, is_backfill` |
| `prediction_events` | none | `event_id PK, name, category, start_date, end_date, market_count, updated_at` |
| `prediction_market_trades` | monthly on `ts` | `(market_id, trade_id) PK, token_id, price, size_usd, side, ts` |
| `prediction_market_oi` | none (daily) | `(condition_id, snapshot_date) PK, total_oi_usd, total_volume_24h_usd` |

Add `event_id` (nullable FK) to the existing `prediction_markets` row (filled from Gamma `/events`).
Partitioning mirrors the existing `ohlcv_bars` hypertable pattern in S3.

### 6.2 S7 knowledge-graph — PREDICTION temporal events (NOT new entity nodes)

> **Model correction (from PLAN-0056 recon, 2026-07-09):** markets are modelled as **temporal events**,
> mirroring the shipped earnings pattern (`EarningsCalendarDatasetConsumer` + `EventType.CORPORATE`),
> **not** as new canonical-entity nodes. This avoids bloating `canonical_entities` with ~30k market
> rows and needs no entity-kind CHECK widening. (An earlier draft proposed `EntityType.prediction_market`
> / `prediction_event`; withdrawn — S7 entity kinds are a fixed DB CHECK of 11 values, and a market is
> an *event*, not an entity.)

- `EventType` (verified at `services/knowledge-graph/src/knowledge_graph/domain/enums.py:86`) gains
  `PREDICTION` (alongside `CORPORATE`; widen the `ck_temporal_event_type` CHECK via
  `intelligence-migrations`, mirroring `0018_add_corporate_event_type`).
- Each entity-linked market → one `temporal_events(event_type='prediction')` row (title = question,
  `active_until` = close_time, `confidence` = implied probability), plus one
  **`entity_event_exposures`** row per referenced entity (`exposure_type=DIRECTLY_AFFECTED`) — the exact
  earnings linkage mechanism. Gamma `/events` groupings are stored in S3 (`prediction_events` table),
  not as KG nodes; the temporal event carries the group id as metadata.

### 6.3 Polarity on the exposure (the one genuinely new modelling piece)

Each `entity_event_exposures` row (market ↔ entity) stores a **polarity** for that entity:
`bullish | bearish | neutral` + `polarity_confidence`. Two nullable columns are added to
`entity_event_exposures` (forward-compatible, defaulted) — **not** to the hot `relations` table, which
has no metadata column (its polarity lives on `relation_evidence_raw`). Polarity is computed **once at
link time** by an LLM classification step (§8.2, `MarketPolarityClassifier`) and reused by every
downstream signal — never recomputed per price tick.

### 6.4 Avro topics (envelope pattern identical to existing `market.prediction.v1`)

Six new topics. **Ingestion (produced by S4, consumed by S3):** `market.prediction.history.v1`,
`market.prediction.event.v1`, `market.prediction.trade.v1`, `market.prediction.oi.v1`. **Signals:**
`market.prediction.move.v1` (produced by S3 move detector, consumed by S7) and
`market.prediction.signal.v1` (produced by S7, consumed by the alert `IntelligenceConsumer`). Full
schemas in PLAN-0056 (§Z1). Existing `market.prediction.v1` is kept as-is (no schema break); S4
additionally feeds the synthetic-doc path via `content.article.raw.v1`.

---

## 7. The synthetic-document path (entity linking — reused verbatim from Wave-1 rails)

Unchanged in spirit from the original §5; it is the mechanism for G1. A market question is a
natural-language artifact, so route it through S6 to get entity extraction + resolution + KG relations
+ embeddings **for free**, with **zero S6 code change** (the existing `ArticleProcessingConsumer` at
`services/nlp-pipeline/.../article_consumer.py:399` accepts any `content.article.raw.v1`).

**Synthetic document shape** (S4 `SyntheticDocumentEmitter`): one doc per market on first-sight
(dedup on `external_id = "polymarket:<condition_id>"` via existing `article_fetch_log.url_hash UNIQUE`),
one on resolution. Body = question + outcomes with implied % + close date + category + event name.
**No LLM cost on price snapshots** — only first-sight metadata and resolution generate documents
(≈ 30,000 docs lifetime total vs. millions of snapshots).

---

## 8. Signal model

### 8.1 Three triggers (all gated; all `signal_type='prediction'`)

| Signal | Trigger | Gate | Source data |
|---|---|---|---|
| **new-market** | NER links a first-seen market to a **tracked** entity | entity tracked + liquidity/vol floor | S6 relations + S3 metadata |
| **material-move** | `Δ implied-probability` over a window exceeds threshold on an entity-linked market | entity tracked + liquidity/vol floor + `|Δ| ≥ τ` + trade-volume conviction | S3 `prediction_market_snapshots` / `_prices` time-series |
| **resolution** | market `status → resolved` on an entity-linked market | entity tracked | S3 status + S7 `resolved_to` |

Signals are **computed from** the time-series (not stored per tick); only gated signals persist and
route to the alert engine. Idempotency: `(condition_id, signal_type, window)` dedup key.

### 8.2 Direction — the "against a company" layer

Direction is a property of the `(market-outcome, entity)` pair and cannot come from price alone
("Will X miss earnings?" ↑ = bearish for X; "Will X's drug be approved?" ↑ = bullish). At link time,
an LLM step labels each referenced entity's polarity per outcome and stores it on the
`entity_event_exposures` row (§6.3). The **material-move** signal then reads polarity to classify the move as **adverse**
(bearish outcome rising, or bullish outcome falling for a held entity) vs favorable, and the alert
copy/severity reflects direction. This reuses the platform's existing news market-impact/sentiment
mental model (and may reuse the same relevance/impact worker infrastructure).

### 8.3 Noise control (non-negotiable)

Polymarket is dominated by sports/junk/illiquid markets. **Every** signal gates hard on:
(a) linked to a *tracked* entity (portfolio/watchlist/followed), (b) liquidity + 24-h volume floor,
(c) material Δ (for moves). Ungated markets still ingest and display, but never fire a signal.

---

## 9. User-facing surfaces

| Surface | Change |
|---|---|
| `/prediction-markets` page | Probability **chart** (history API), **event groupings**, **entity-link chips** (→ entity page), **signal badges** (adverse-move / new / resolved), liquidity + OI + recent-flow on detail. |
| Entity page | "Prediction markets referencing this entity" section (via `GET /entities/{id}/predictions`), on the temporal timeline as `PREDICTION` events. |
| Chat | `get_prediction_markets` gains `grounding_fields` on odds so the value-substantiation eval can verify them; entity-scoped queries ("what's the market saying about NVDA?") resolve through KG links. |
| Brief | Portfolio-relevant prediction signals (adverse moves, new markets, resolutions) included as a brief leg. |
| Alerts | `prediction` signal subtype in the existing alert engine; user-toggleable. |

---

## 10. Backfill horizons

| Stream | Initial | Configurable max | Rationale |
|---|---|---|---|
| CLOB `/prices-history` | **14 days** | 6 months | Bound signal/storage cost; validate then bump. |
| Data `/trades` | 14 days | 90 days | High volume; cap storage. |
| Data `/oi` | 14 days | 90 days | Daily snapshots; lightweight. |
| Gamma `/events`, `/markets` | snapshot only | n/a | No historical metadata upstream. |

Env vars (new): `CONTENT_INGESTION_POLYMARKET_HISTORY_BACKFILL_DAYS=14`,
`CONTENT_INGESTION_POLYMARKET_TRADES_BACKFILL_DAYS=14`, triggered by the existing
`CONTENT_INGESTION_BACKFILL_ON_STARTUP` mechanism.

---

## 11. S9 API surface (read-side; R27 ReadOnlyUnitOfWork)

| Method | Path | Returns |
|---|---|---|
| GET | `/v1/signals/prediction-markets` | list; filter `category`, `event_id`, `status`, `q`; **now includes `liquidity`** |
| GET | `/v1/signals/prediction-markets/{condition_id}` | market + outcomes + OI + latest flow |
| GET | `/v1/signals/prediction-markets/{condition_id}/history?interval=1h&since=` | price time-series |
| GET | `/v1/signals/prediction-markets/{condition_id}/trades?since=&limit=` | recent trades |
| GET | `/v1/signals/prediction-markets/events` / `/events/{event_id}` | event groupings + child markets |
| GET | `/v1/entities/{entity_id}/predictions` | markets referencing this entity (+ polarity), proxied to S7 |

> These **extend the shipped S9 `/v1/signals/prediction-markets/*` namespace** (do not introduce a
> parallel `/v1/predictions/*`). S9 proxies to the existing S3 `/api/v1/prediction-markets/*` routes;
> the entity-predictions route proxies to the new S7 endpoint (§6.2). Existing paths remain unchanged
> for the shipped frontend.

---

## 12. Test scenarios (delta from Wave 1)

- **S4 adapters:** events/history/trades/OI happy-path + 429 backoff + resolved-market `interval=1d`
  fallback; synthetic-doc emitted once per market (dedup), once on resolution.
- **S6 (no code change):** GLiNER extracts entities from question → `nlp.article.enriched.v1` carries
  mentions.
- **S7:** `EventType.PREDICTION` temporal-event upsert idempotent; one `entity_event_exposures` row per
  referenced entity; polarity persisted on the exposure.
- **Polarity classifier:** "Will X miss earnings?" → bearish-for-X; "Will X drug approved?" →
  bullish-for-X; unrelated entity → neutral.
- **Signal worker:** new-market fires only when entity tracked + above floor; material-move respects
  Δ threshold + polarity (adverse vs favorable) + volume conviction; resolution fires once; all
  idempotent on `(condition_id, signal_type, window)`.
- **E2E:** cold start `BACKFILL_DAYS=14` → ≥2,000 markets, ≥200k price rows, ≥50 distinct entity
  `references`; `GET /entities/{tracked_id}/predictions` returns ≥1 with polarity; adverse-move on a
  portfolio entity appears as an alert + brief line.

---

## 13. Operational concerns

- **Storage (steady state):** `prediction_market_prices` (1h) ≈ 17M rows/yr; `prediction_market_trades`
  ≈ 5M/yr (revisit); monthly partitions on both, drop after 2 years. MinIO bronze ≈ 50 GB/yr.
- **Failure modes:** Polymarket down → circuit breaker + `Retryable` backoff; wrong-granularity on
  resolved markets → auto `interval=1d` retry; backfill task storm → bounded by `WORKER_CONCURRENCY`
  + `claim_batch SKIP LOCKED`; **polarity LLM failure → default `neutral`** (signal still fires as
  non-directional, never blocks ingestion).
- **Observability:** `polymarket_adapter_polls_total{adapter,status}`,
  `polymarket_history_rows_inserted_total`, `polymarket_synthetic_documents_emitted_total`,
  `prediction_signals_emitted_total{signal_type,direction}`,
  `s3_prediction_consumer_lag_seconds{topic}`. New Grafana "Prediction Pipeline" board.

---

## 14. Architecture compliance

| Rule | Compliance |
|---|---|
| R5 outbox dual writes | ✅ every adapter writes DB + outbox in one tx |
| R6 UUIDv7 | ✅ event_id, doc_id, signal ids via `new_uuid7()` |
| R7 UTC-only timestamps | ✅ all `*_ts` are `timestamp-micros` UTC via `utc_now()` |
| R9 no cross-service DB | ✅ S4 produces; S3/S7/alert consume via Kafka |
| R11 forward-compat schemas | ✅ new topics; polarity fields defaulted |
| R16 API uses use cases | ✅ S9 → `GetPredictionMarket*UseCase` |
| R24 intelligence_db DDL | ✅ S7 changes via `intelligence-migrations`; S3 changes via S3 Alembic |
| R27 read replica for reads | ✅ read endpoints use `ReadOnlyUnitOfWork` (`prediction_market_snapshots_read`, etc.) |

---

## 15. Open questions

- **OQ-1 — Signal worker home.** Compute move-signals inside S3 market-data (owns the time-series) or
  in a small dedicated worker consuming S3's read replica? **Tentative:** in S3 (co-located with data,
  no cross-service read). Finalize in /plan.
- **OQ-2 — Polarity model.** Which model/prompt for the `(market, entity)` polarity classifier?
  **Tentative:** reuse the news relevance/impact classifier stack (DeepInfra), new prompt in
  `libs/prompts`. Cheap (≈30k lifetime calls, one per market-entity link).
- **OQ-3 — "Tracked entity" definition for signal gating.** Portfolio holdings only, or
  portfolio + watchlist + followed entities? **Tentative:** union of all three; configurable floor.
- **OQ-4 — Resolution re-emission.** One synthetic doc on resolution or two (question + resolution)?
  **Tentative:** two — distinct `published_at`. (Carried from original OQ-1.)

None are blocking; `/plan` can proceed and finalize.

---

## 16. Compounding entries (expected post-implementation)

- BUG_PATTERNS.md: CLOB closed-market granularity 410/empty; "plumbed-but-unused" resolution
  (liquidity/slug precedent).
- `services/market-data/.claude-context.md`: 4 new tables + 4 new consumers + signal worker.
- `services/knowledge-graph/.claude-context.md`: 2 new entity types, `PREDICTION` event type,
  polarity on `entity_event_exposures`.
- `docs/services/market-data.md`, `docs/services/knowledge-graph.md`, `docs/apps/worldview-web.md`.
- `docs/MASTER_PLAN.md`: prediction-market signal flow diagram.
