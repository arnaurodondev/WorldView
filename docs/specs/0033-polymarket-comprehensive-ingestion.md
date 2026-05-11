# PRD-0033 — Polymarket Comprehensive Ingestion (Wave 2)

| Field | Value |
|---|---|
| **Created** | 2026-04-29 |
| **Owner** | Arnau Rodon |
| **Status** | DRAFT (ready for /plan) |
| **Supersedes** | Extends PRD-0019 (Polymarket Wave 1) |
| **Drives** | PLAN-0056 (separate plan, follows PLAN-0055) |
| **Affects services** | S4 content-ingestion (new adapters, new Avro), S6 nlp-pipeline (synthetic-document routing), S7 knowledge-graph (new entity types, new partitioned tables, new consumers), S9 api-gateway (new read endpoints), worldview-web (new UI surfaces — out of scope for this PRD) |
| **Doesn't affect** | S1 portfolio, S3 market-ingestion, S5 content-store, S8 rag-chat (downstream consumer in a follow-up) |

---

## 1. Context and motivation

### 1.1 Where Polymarket sits today

PRD-0019 (Wave 1, shipped) introduced a single S4 adapter that polls the Polymarket Gamma API `/markets` endpoint every 5 minutes, persists raw JSON to MinIO bronze, and publishes `market.prediction.v1` Avro events. Today there is **no consumer** of that topic. The data lands in three places:

1. MinIO bronze: `content-ingestion/polymarket/{Y}/{M}/{D}/{market_id}_{snapshot_at}.json`
2. Postgres `prediction_market_fetch_log` table (dedup metadata only — no business data)
3. Kafka topic `market.prediction.v1` (no consumer)

The dashboard renders Polymarket data from a sector-specific gateway shim that reads `prediction_market_fetch_log` joined to the latest Kafka payload — workable for a single widget, not a foundation for analysis.

### 1.2 What's missing

The platform currently captures only the snapshot of *currently-listed* markets. We are not capturing:

- **Historical price time-series per outcome** — required for any signal modelling (probability paths over time).
- **Event-level groupings** — Polymarket's `/events` endpoint clusters related markets (e.g., "2024 US Election" → child markets per candidate). Without this we can't reason about correlated markets.
- **Trade history** — `/trades` API gives anonymous fills; useful for liquidity/flow analysis.
- **Holder / open-interest data** — `/oi`, `/holders`; secondary priority.
- **Resolution events** — when a market settles, we need a durable record (resolved outcome, oracle timestamp, payout).

We are also not routing market questions through S6's NER pipeline, so Polymarket markets aren't linked to entities in the KG. A market like "Will Trump win the 2024 election?" should resolve to entities `Donald Trump` and `2024 US Presidential Election` and be linkable from those entity pages — today it isn't.

### 1.3 Why now

1. **Thesis differentiator** — prediction-market data is rare, well-priced, free, and uncorrelated with the news/fundamentals signals already in the platform.
2. **Free API surface** — all three Polymarket APIs (Gamma, CLOB, Data) are public, no auth required for read endpoints, with generous rate limits.
3. **The token IDs we need are already in our bronze** — every Gamma `/markets` response we already fetch contains `clobTokenIds` per outcome (verified in `services/content-ingestion/src/content_ingestion/domain/entities.py` parsing logic). No discovery cost.

---

## 2. API surface to ingest

### 2.1 Reality check (verified against docs)

URLs fetched and verified during PRD drafting:
- https://docs.polymarket.com/
- https://docs.polymarket.com/developers/CLOB/timeseries
- https://docs.polymarket.com/developers/gamma-markets-api/gamma-structure
- https://docs.polymarket.com/quickstart/introduction/rate-limits

### 2.2 Endpoint map

| API | Endpoint | Status today | This PRD adds | Priority |
|---|---|---|---|---|
| Gamma | `/markets` | ✅ in use (5-min poll) | — | shipped |
| Gamma | `/events` | ❌ unused | NEW poller (1-hour cadence) | P0 |
| Gamma | `/tags` | ❌ unused | NEW one-shot bootstrap (refresh weekly) | P1 |
| Gamma | `/series` | ❌ unused | NEW one-shot bootstrap (refresh weekly) | P2 |
| Gamma | `/public-search` | ❌ unused | not needed (we already have full market list) | skip |
| CLOB | `/prices-history` | ❌ unused | NEW per-token-id history puller (daily on backfill, 6h ongoing) | **P0 — primary signal source** |
| CLOB | `/book` / `/books` | ❌ unused | not needed for thesis (real-time order book) | skip |
| CLOB | `/price` / `/prices` | ❌ unused | covered by `/prices-history` for our needs | skip |
| CLOB | `/trades` (CLOB-side) | ❌ unused | covered by Data API equivalent | skip |
| Data | `/trades` | ❌ unused | NEW poller (per-market, 1-hour cadence, last-cursor) | P1 |
| Data | `/oi` (open interest) | ❌ unused | NEW per-market, daily | P2 |
| Data | `/holders` | ❌ unused | NEW per-market, weekly | P2 |
| Data | `/positions` | ❌ unused | per-wallet — out of scope (no wallet integration) | skip |
| Data | `/leaderboards` | ❌ unused | out of scope | skip |
| Data | `/activity` | ❌ unused | covered by `/trades` | skip |

### 2.3 Rate-limit budget

Polymarket limits (per docs):

| Bucket | Limit | Our planned consumption |
|---|---|---|
| Gamma global | 4,000 req/10s | < 50 req/10s |
| Gamma `/markets` | 300 req/10s | already running, 1 req/5min |
| Gamma `/events` | 500 req/10s | 1 req/hour |
| CLOB global | 9,000 req/10s | < 200 req/10s burst, < 50 sustained |
| CLOB `/prices-history` (in `/prices` bucket) | 500 req/10s | ~100 req/10s during backfill, ~10/10s steady |
| Data API global | 1,000 req/10s | < 50 req/10s |
| Data API `/trades` | 200 req/10s | < 30 req/10s |

Conclusion: total consumption is ≤ 5% of any rate-limit bucket. **No throttling required**, but each adapter MUST honor 429 responses with exponential backoff (treated as `Retryable`).

### 2.4 Historical data availability

Verified facts:
- **Open markets**: full history at 1m / 1h / 6h / 1d / 1w granularities via CLOB `/prices-history`.
- **Resolved markets**: granularity capped at ≥ 12 hours per Polymarket GitHub issue #216. Use `interval=1d`.
- **`/orderbook-history`**: stopped emitting snapshots Feb 20 2026 — DO NOT USE.
- **Backfill horizon**: Polymarket retains data indefinitely on their side. A 6-month backfill of `/prices-history?interval=1h` per active market returns roughly 4,380 datapoints (24 × 180). For ~3,000 active+recently-resolved markets, total backfill = ~13M rows — manageable but not trivial.

---

## 3. New entities and topics

### 3.1 New entity types in S7 KG

Two new `EntityType` values:

| Type | Cardinality | Source | Examples |
|---|---|---|---|
| `prediction_market` | per-market (≈ 2,000 active, ≈ 30,000 historical) | Gamma `/markets` | "Will Trump win 2024?", "Will BTC hit 100k by Dec 2025?" |
| `prediction_event` | per-event group (≈ 200 active) | Gamma `/events` | "2024 US Presidential Election", "2025 BTC Price Targets" |

Hierarchy:
```
prediction_event ── contains ──> prediction_market ── references ──> {ticker | macro | political_figure | ...}
                                                  ── has_outcome ──> outcome (no entity, stored on market)
```

Linking to existing entities:
- `prediction_market -[:references]-> {existing entity}` — produced by S6 NER on the synthetic document.
- `prediction_event -[:references]-> {existing entity}` — same path.
- `prediction_market -[:belongs_to]-> prediction_event` — produced by S4 directly from `event_id` in the Gamma response.

### 3.2 New Avro topics

| Topic | Purpose | Producer | Consumer |
|---|---|---|---|
| `market.prediction.history.v1` | One event per (token_id, snapshot_window) of price history | S4 PolymarketHistoryAdapter | S7 PredictionPriceHistoryConsumer |
| `market.prediction.event.v1` | One event per Polymarket Event group | S4 PolymarketEventAdapter | S7 PredictionEventConsumer |
| `market.prediction.trade.v1` | Trade-level events from Data API | S4 PolymarketTradesAdapter | S7 PredictionTradeConsumer |
| `market.prediction.oi.v1` | Daily open-interest snapshot | S4 PolymarketOIAdapter | S7 PredictionOIConsumer |

Existing `market.prediction.v1` (market snapshots) is **kept as-is** — no schema break. We add a **new consumer** that converts each market snapshot into a synthetic document for S6 NER (see §5).

> **Clarification on synthetic-document path**: The `market.prediction.event.v1` topic is consumed exclusively by S7. The S6 NER pipeline is reached via the **existing** `content.article.raw.v1` topic — S4's new `SyntheticDocumentEmitter` produces `content.article.raw.v1` events (with `source_type='prediction_market'`), which S6 processes unchanged. S6 has **zero code changes** in this PRD.

### 3.3 New Avro schemas (sketches; full definitions in plan)

```avro
// market.prediction.history.v1.avsc
{
  "type": "record",
  "name": "PredictionMarketHistory",
  "namespace": "com.worldview",
  "fields": [
    {"name": "event_id", "type": "string"},          // UUIDv7
    {"name": "occurred_at", "type": "long", "logicalType": "timestamp-micros"},
    {"name": "schema_version", "type": "int", "default": 1},
    {"name": "market_id", "type": "string"},          // condition_id
    {"name": "outcome_token_id", "type": "string"},   // CLOB token ID
    {"name": "outcome_name", "type": ["null", "string"], "default": null},
    {"name": "interval", "type": "string"},            // "1h", "1d", "1w"
    {"name": "window_start_ts", "type": "long", "logicalType": "timestamp-micros"},
    {"name": "price", "type": "double"},               // implied probability 0-1
    {"name": "is_backfill", "type": "boolean", "default": false}
  ]
}
```

Other schemas follow identical envelope pattern; full definitions in PLAN-0056.

### 3.4 New DB tables (S7 — `intelligence_db` via `intelligence-migrations`)

> **Scope note**: The existing `prediction_market_fetch_log` table in S4's `content_ingestion_db` is **unchanged** — it stays in S4 as a dedup log for Gamma API poll cycles. The 6 new tables below all land in `intelligence_db` (S7 domain, managed by `intelligence-migrations`).

| Table | Partition | Key columns |
|---|---|---|
| `prediction_markets` | none | `condition_id PK, event_id, question, category, status, close_time, resolved_outcome, created_at, updated_at` |
| `prediction_market_outcomes` | none | `(condition_id, token_id) PK, outcome_name, last_price, last_volume_24h, updated_at` |
| `prediction_market_prices` | by month on `window_start_ts` | `(condition_id, token_id, interval, window_start_ts) PK, price, source` |
| `prediction_events` | none | `event_id PK, name, category, start_date, end_date, market_count, updated_at` |
| `prediction_market_trades` | by month | `(market_id, trade_id) PK, token_id, price, size_usd, side, ts` |
| `prediction_market_oi` | none (daily) | `(condition_id, snapshot_date) PK, total_oi_usd, total_volume_24h_usd` |

All tables are partitioned where they grow unboundedly (prices, trades). Same pattern as `chunk_embeddings` (PRD-0017) and `article_impact_windows` (PRD-0026).

### 3.5 Entity-graph relations (added to existing `relations` table)

| Relation type | Source | Target |
|---|---|---|
| `belongs_to_event` | `prediction_market` | `prediction_event` |
| `references` | `prediction_market` or `prediction_event` | any existing entity (via S6 NER) |
| `resolved_to` | `prediction_market` | `prediction_event` (when settled) |

No new relation columns — uses existing `relations` schema.

---

## 4. Data flow

### 4.1 End-to-end picture

```
                                    ┌───────────────────────────────────────────┐
[Gamma /markets] ─5min─►            │                                           │
[Gamma /events] ─1hr──►  S4 Adapters│ ──► outbox ──► Kafka                      │
[CLOB /prices-history] backfill+6h► │      │           │                        │
[Data /trades] ─1hr──►              │      │           │                        │
[Data /oi] ─daily─►                 │      ▼           ▼                        │
                                    └─MinIO bronze────────────────────────────  │
                                                       │                        │
                                                       ▼                        │
                              ┌─ market.prediction.v1 ──────────────────────────┘
                              │  (existing, market snapshots)
                              │
                              ▼
                    ┌─ NEW: S4 SyntheticDocumentEmitter
                    │     converts each market snapshot to a doc payload:
                    │     "Will Trump win 2024? Outcomes: Yes (62%) / No (38%). Closes 2024-11-05"
                    │     publishes content.article.raw.v1 (source_type='prediction_market')
                    │
                    ▼
              S6 nlp-pipeline (existing path, unchanged)
                    │     - sectioning: trivial (full text in 1 chunk)
                    │     - entity extraction: GLiNER on question + outcomes
                    │     - entity resolution: existing
                    │     - publishes nlp.article.enriched.v1
                    │
                    ▼
              S7 knowledge-graph (existing EnrichedArticleConsumer)
                    │     - creates relations (prediction_market) -[:references]-> (entity)
                    │     - existing flow, no changes needed
                    │
                    ├──► [also: NEW PredictionMarketUpserter]
                    │     consumes market.prediction.v1 directly to upsert
                    │     prediction_markets + prediction_market_outcomes
                    │
                    └──► [also: NEW PredictionPriceHistoryConsumer]
                          consumes market.prediction.history.v1 to upsert
                          prediction_market_prices
```

### 4.2 Three independent data flows

1. **Structural**: Adapter → Kafka → S7 upserter → DB tables. No LLM, no NER.
2. **Semantic**: Adapter → SyntheticDocumentEmitter → `content.article.raw.v1` → S6 NER → S7 relations. Reuses existing news pipeline.
3. **Temporal**: CLOB history adapter → Kafka → S7 prices upserter → partitioned table.

These are independent: one can fail without the others. Idempotent upserts everywhere.

---

## 5. The synthetic-document path (key design decision)

### 5.1 Rationale

A Polymarket question is a natural-language artifact: `"Will Trump win the 2024 US Presidential Election?"`. Routing this through S6 gives us:

1. **Entity extraction for free** — GLiNER pulls `Donald Trump`, `2024 US Presidential Election`.
2. **Entity resolution for free** — S6's existing resolver maps these to canonical entities.
3. **Cross-domain links for free** — relations land in the same KG that holds news, fundamentals, and macro events.
4. **Embeddings for free** — Worker 13F can embed prediction-market questions for similarity search.

### 5.2 Synthetic document shape

When `PolymarketAdapter` produces a `PredictionMarketSnapshot`, a new `SyntheticDocumentEmitter` (in S4) constructs a `content.article.raw.v1` payload:

```python
{
  "doc_id": "<uuid7>",
  "source_type": "prediction_market",
  "source_name": "polymarket",
  "external_id": "polymarket:<condition_id>",
  "title": question,                    # "Will Trump win 2024?"
  "url": f"https://polymarket.com/market/{slug}",
  "published_at": close_time,          # the resolution date is the published_at
  "body": (
    f"{question}\n\n"
    f"Outcomes:\n"
    + "\n".join(f"- {o.name}: {o.price * 100:.1f}% (${o.volume_24h:,.0f} 24h vol)"
                for o in outcomes)
    + f"\n\nMarket closes {close_time.isoformat()}.\n"
    + f"Category: {category}.\n"
    + (f"Belongs to event: {event_name}\n" if event_id else "")
  ),
  "minio_bronze_key": <existing-key>,   # points to the same JSON we already store
  "metadata": {"polymarket_market_id": condition_id, "polymarket_event_id": event_id}
}
```

Key points:

- **One synthetic document per market, NOT per snapshot.** Emit only when the market is first seen, OR when the question text changes (rare but possible).
- **Dedup key**: `external_id = "polymarket:<condition_id>"`. The existing `article_fetch_log.url_hash UNIQUE` already prevents duplicates if we hash this external_id.
- **No LLM cost on snapshots.** Price snapshots don't generate documents — only first-seen market metadata does. So we generate ≈ 30,000 docs total across all of Polymarket history vs. otherwise N × snapshots = millions.
- **Re-emission on resolution**: when a market resolves, emit a *second* document with the resolution news (one per market, lifetime total = 2). Tag with `resolution_date` to differentiate.

### 5.3 What S6 does with it

Nothing special. The existing `ArticleProcessingConsumer` accepts any `content.article.raw.v1` event regardless of `source_type`. NER runs, entities resolve, `nlp.article.enriched.v1` is emitted, S7 creates relations. Zero S6 code change.

The only S6 consideration: the existing `ArticleRelevanceScoringWorker` will run on these documents too. That's fine — prediction markets *are* relevant to the entities they reference. The `display_relevance_score` formula handles them naturally.

---

## 6. Backfill horizons

Per user decision (open-question 2 in /investigate):

| Stream | Initial horizon | Configurable max | Rationale |
|---|---|---|---|
| Gamma `/markets` | snapshot only (no history) | n/a | Polymarket doesn't expose historical metadata |
| Gamma `/events` | snapshot only | n/a | same |
| CLOB `/prices-history` | **2 weeks at first deploy**; configurable to 6 months | 6 months | Bound LLM-derived signal cost; 2 weeks ≈ 336 hours of 1h data per token |
| Data `/trades` | 2 weeks initial | 90 days | Trade volume is high; cap to limit storage |
| Data `/oi` | 2 weeks initial | 90 days | Daily snapshots; lightweight |

Backfill triggered by the same `CONTENT_INGESTION_BACKFILL_ON_STARTUP=true` env var defined in PLAN-0055 Sub-Plan A (T-A-1-03, T-A-1-04). Two new env vars:

```
CONTENT_INGESTION_POLYMARKET_HISTORY_BACKFILL_DAYS=14   # initial; bump to 180 once validated
CONTENT_INGESTION_POLYMARKET_TRADES_BACKFILL_DAYS=14    # initial; bump to 90 once validated
```

---

## 7. S9 API surface (read-side)

New endpoints in api-gateway (proxied to S7 read-replica via R27 ReadOnlyUnitOfWork):

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/predictions/markets` | Paginated list, filter by `category`, `event_id`, `status`, `q` (text search) |
| GET | `/api/v1/predictions/markets/{condition_id}` | Single market with current outcomes |
| GET | `/api/v1/predictions/markets/{condition_id}/history?interval=1h&since=...` | Price time-series |
| GET | `/api/v1/predictions/markets/{condition_id}/trades?since=...&limit=100` | Recent trades |
| GET | `/api/v1/predictions/events` | Paginated list |
| GET | `/api/v1/predictions/events/{event_id}` | Event with child markets |
| GET | `/api/v1/entities/{entity_id}/predictions` | Markets/events that reference this entity (via KG relations) |

Out-of-scope for this PRD: dashboard widgets, screener integration, alerts on prediction-market deltas. Separate UI PRD will follow.

---

## 8. Test scenarios

### 8.1 S4 adapter tests

| Scenario | Expected |
|---|---|
| Gamma `/markets` returns 200 with N markets | N events emitted, N rows in fetch_log, N MinIO objects |
| Gamma returns same market twice in two pollings | Second poll: 0 events emitted (dedup on `(market_id, snapshot_at)`) |
| CLOB `/prices-history` returns 1000 datapoints | 1000 events to `market.prediction.history.v1` |
| Resolved market with `interval=1h` requested | Adapter detects 410/error, retries with `interval=1d` |
| Polymarket returns 429 | Adapter backs off exponentially, marks task Retryable |
| `/events` returns event with child market_ids that don't exist yet in `prediction_markets` | Event row created; market FK is nullable + filled when market arrives |

### 8.2 S6 synthetic-document tests

| Scenario | Expected |
|---|---|
| First sighting of market `"Will Trump win 2024?"` | One `content.article.raw.v1` emitted; `external_id="polymarket:<cid>"` |
| Same market in next poll | Zero new documents emitted (`url_hash UNIQUE`) |
| Market question changes (rare) | New document emitted with new external_id suffix |
| GLiNER extracts `Donald Trump` from question | `nlp.article.enriched.v1` carries entity mention; S7 creates `references` relation |

### 8.3 S7 consumer tests

| Scenario | Expected |
|---|---|
| `market.prediction.v1` snapshot arrives for new market | `prediction_markets` row INSERTed, outcomes upserted |
| Same market arrives again | UPDATE last_volume_24h, no new row |
| Market resolves (status → "resolved") | `resolved_outcome` populated, `resolved_to` relation created |
| `market.prediction.history.v1` arrives | `prediction_market_prices` row INSERTed; replay (same key) is no-op |
| Event group arrives before its child markets | Event row created; markets get `belongs_to_event` relation as they arrive |

### 8.4 E2E tests

| Scenario | Expected |
|---|---|
| Cold start with `BACKFILL_ON_STARTUP=true`, `BACKFILL_DAYS=14` | Within 30 minutes, 2,000+ markets in `prediction_markets`, 200,000+ rows in `prediction_market_prices`, KG `references` relations to ≥ 50 distinct entities |
| Query `/api/v1/entities/{donald_trump_id}/predictions` | Returns ≥ 1 prediction market (assuming live Polymarket has political markets at test time) |
| Query `/api/v1/predictions/markets/{cid}/history?interval=1h&since=7d_ago` | Returns 168 datapoints |

---

## 9. Operational concerns

### 9.1 Storage cost

Estimated rows per year (steady state):

| Table | Rows/year |
|---|---|
| `prediction_markets` | ~50,000 (incl. resolved) |
| `prediction_market_outcomes` | ~120,000 (avg 2.4 outcomes/market) |
| `prediction_market_prices` (1h interval) | 2,000 markets × 24 × 365 = ~17M/year |
| `prediction_market_trades` | ~5M/year (estimate; revisit after first month) |
| `prediction_events` | ~5,000 |

Monthly partitions on prices and trades — drop after 2 years (retention policy in PLAN-0056). MinIO bronze: ~50 GB/year.

### 9.2 Failure modes

| Mode | Detection | Handling |
|---|---|---|
| Polymarket API down | 5xx for 10+ consecutive polls | structlog WARN; circuit breaker via existing `CircuitBreakerPort`; tasks marked Retryable, backoff |
| `/prices-history` returns wrong granularity (closed market with 1h request) | API returns 400 or empty | adapter retries with `interval=1d` automatically |
| Synthetic document with question that triggers PII detection | unlikely; questions are public | no special handling, treat as normal article |
| Backfill task storm at startup | 30,000+ tasks enqueued instantly | rate-limit by `WORKER_CONCURRENCY`; tasks claimed FIFO via `claim_batch SKIP LOCKED` |

### 9.3 Observability

Metrics to add:
- `polymarket_adapter_polls_total{adapter=,status=}` (counter)
- `polymarket_markets_active` (gauge — set at end of each `/markets` poll)
- `polymarket_history_rows_inserted_total` (counter)
- `polymarket_synthetic_documents_emitted_total` (counter)
- `s7_prediction_consumer_lag_seconds{topic=}` (gauge — Kafka offset lag)

Grafana board: new "Polymarket Pipeline" with one row per adapter, one row per consumer, one row for synthetic-doc throughput.

---

## 10. Out of scope for this PRD

- Dashboard widgets / UI surfaces (separate UI PRD)
- Alerting on prediction-market deltas (separate alert-rule PRD)
- Polymarket-aware chat tooling (PRD-0026 follow-up)
- ML signal training (separate research PRD; this PRD only provides the data substrate)
- Wallet-level data (`/positions`, `/leaderboards`)
- WebSocket integration (we poll; live updates are nice-to-have but not required for thesis)

---

## 11. Architecture compliance check

| Rule | Compliance |
|---|---|
| R5 outbox for dual writes | ✅ — every adapter writes DB + outbox in one tx |
| R6 UUIDv7 for IDs | ✅ — `event_id`, `doc_id`, KG primary keys |
| R7 UTC-only timestamps | ✅ — all `*_ts` fields are `timestamp-micros` UTC |
| R9 no cross-service DB | ✅ — S4 produces, S7 consumes via Kafka |
| R11 forward-compat schemas | ✅ — new topics, defaults on optional fields |
| R12 domain layer independence | ✅ — adapters live in infrastructure/ |
| R14 frontend → S9 only | ✅ — no direct frontend call to S4/S7 |
| R24 intelligence_db DDL | ✅ — new tables in `intelligence-migrations` |
| R25 API uses use cases | ✅ — S9 endpoints call `GetPredictionMarketUseCase` etc. |
| R27 read-only use cases on read replica | ✅ — read endpoints use `ReadOnlyUnitOfWork` |

---

## 12. Open questions

OQ-1: Resolution-event re-emission: when a market resolves, do we emit *one* synthetic document for the resolution, or two (one for the question + one for the resolution)? **Tentative**: two — they're semantically distinct events with different `published_at`.

OQ-2: Should `prediction_event` entities live in the existing `canonical_entities` table or a separate one? **Tentative**: same table; the existing table supports heterogeneous entity types via `entity_type` column.

OQ-3: When a Polymarket category like "Politics > 2024 Election" is encountered, should we create category entities or use Polymarket's native category strings as enum tags? **Tentative**: tags on `prediction_event`; no entity creation. Categories are a closed set we don't need to relate.

These are not blocking — `/plan` can proceed and finalize during implementation if user has no preference.

---

## 13. Compounding entries

After implementation, the following are expected to be added:
- BUG_PATTERNS.md: new pattern around CLOB closed-market granularity 410/empty response.
- `services/content-ingestion/.claude-context.md`: 4 new adapters, 4 new topics.
- `services/knowledge-graph/.claude-context.md`: 2 new entity types, 6 new tables.
- `docs/services/content-ingestion.md` and `docs/services/knowledge-graph.md`: full new section per service.
- `docs/MASTER_PLAN.md`: prediction-market data flow diagram added.
