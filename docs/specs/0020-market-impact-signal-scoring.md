# PRD-0020 — Market-Impact Signal Scoring (Option A: Routing Score Extension)

> **Status**: Draft — 2026-04-06
> **Author**: Arnau Rodon
> **Services affected**: S6 (NLP Pipeline), `intelligence_db` (via `intelligence-migrations`), S9 (API Gateway)
> **Depends on**: PLAN-0015 complete (S8 infrastructure), PLAN-0019 (S3 has OHLCV data)
> **Plan**: PLAN-0020 (to be generated)

---

## 1. Problem Statement

Worldview's J4 (Signals/Events View) surfaces NLP-derived signals, but every signal is treated with equal weight. In practice, 50% of financial news articles have near-zero price impact; a handful drive significant market moves. Without a market-impact score, research analysts must manually triage every signal — a cognitive load that reduces the platform's value.

ZeroTerminal competitive research (2026-04-06) identified that their AI Signal Scoring engine (trained on 849K price-impact measurements, scoring 1–20) filters ~50% of headlines as noise and provides a ranked signal feed. This PRD implements an equivalent mechanism for worldview using our own ingested price and news data — no external ML service required.

**Option A (this PRD)**: Extend S6's Block 5 routing score with a new `price_impact` signal using retrospective OHLCV correlation. This requires minimal new infrastructure: a background labelling worker that computes price deltas, plus one new signal in the routing formula.

**Option B (future PRD)**: Dedicated `MarketImpactScorer` model in `ml-clients` — a trained classifier requiring a curated labelled dataset and a separate inference path. Documented in §7 AD-3 for future reference.

---

## 2. Target Users

| User | Workflow | Benefit |
|------|----------|---------|
| **Research Analysts** (J4) | Triaging signal feed | High-impact articles float to top; noise suppressed |
| **Quantitative Traders** (API) | Signal ranking for model input | `market_impact_score` field on signals API |
| **LLM Chat users** (J5) | "What were the most market-moving articles about Apple this week?" | S8 can filter/rank retrieval candidates by impact score |
| **Thesis Evaluators** | Evidence of data science integration | Demonstrates data-driven ML signal beyond NLP classification |

---

## 3. Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| F-01 | A background `PriceImpactLabellingWorker` computes price-impact windows for each processed article in the content store, using linked entity OHLCV data from S3 | MUST |
| F-02 | Price impact is computed as the maximum absolute percentage price change across ±30m, ±1h, ±2h, ±1D windows after article `published_at` | MUST |
| F-03 | Impact labels are stored in a new `article_price_impacts` table in `nlp_db` | MUST |
| F-04 | S6 Block 5 routing score gains a new `price_impact` signal weighted at 0.10 | MUST |
| F-05 | Block 5 routing weights are rebalanced to accommodate the new signal (total must remain 1.0) | MUST |
| F-06 | A `market_impact_score` field (0.0–1.0 normalised) is added to the `nlp.signal.detected.v1` Avro schema | MUST |
| F-07 | The `GET /api/v1/signals` endpoint in S6 returns `market_impact_score` on each signal | MUST |
| F-08 | Articles with no linked OHLCV entity default to `price_impact_score = 0.0` (no data = no impact signal) | MUST |
| F-09 | The labelling worker runs as an independent process (R22) on a 4-hour cycle | MUST |
| F-10 | Impact windows are only computed once price data is available for the post-publication window (minimum 1D delay) | MUST |
| F-11 | Option B (dedicated ML model) is documented as a future PRD with the labelled dataset from F-02 as its training input | SHOULD |

---

## 4. Non-Functional Requirements

| Attribute | Target |
|-----------|--------|
| Labelling latency | Articles receive impact labels within 25h of `published_at` (1D window + processing cycle) |
| Coverage | Articles with ≥1 resolved canonical entity with OHLCV data in S3 receive impact labels; ~60% estimated coverage |
| Correctness | Impact score is a retrospective fact, not a prediction — no false positives by construction |
| Throughput | Worker processes ~10K articles per 4-hour cycle at estimated 50ms per article (OHLCV lookup) |
| Backward compatibility | New `market_impact_score` field in `nlp.signal.detected.v1` added with Avro default `0.0` (R5 forward compatibility) |
| Routing weight rebalance | Must be validated: all 8 signal weights sum exactly to 1.0 (existing assertion in Block 5) |

---

## 5. Out of Scope

- **Prediction of future price impact** (this is retrospective labelling only)
- **Option B ML model training** — deferred to a future PRD; this PRD creates the training data
- **Kalshi/Polymarket probability as impact signal** — deferred; interesting but adds cross-service dependency on PRD-0019
- **Intraday OHLCV** — worldview uses daily OHLCV (thesis constraint); ±30m/±1h windows use the daily OHLCV bar that contains the article timestamp as a proxy
- **Impact labelling for LIGHT-tier articles** — only MEDIUM and DEEP tier articles receive impact labels (they have resolved entities; LIGHT tier has no entity resolution)

---

## 6. Technical Design

### 6.1 Affected Services

| Service | Change Type | Summary |
|---------|-------------|---------|
| **S6 NLP Pipeline** | Block 5 weight rebalance + new signal + `market_impact_score` on signals | Add `price_impact` as 8th routing signal; add field to `SignalDetectedV1` Avro schema |
| **`intelligence-migrations`** | No change — `article_price_impacts` lives in `nlp_db` (owned by S6) | — |
| **S6 new process** | New `PriceImpactLabellingWorker` background process | Independent process per R22 |
| **S9 API Gateway** | No new endpoints — signals endpoint already proxied | Optional: sort signals by `market_impact_score DESC` as new default |

---

### 6.2 API Changes

#### GET /api/v1/signals (S6) — modified response

Existing endpoint; `market_impact_score` field added to each signal in the response.

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| *(existing fields)* | — | — | Unchanged |
| `market_impact_score` | float | no | 0.0–1.0 normalised market impact score (0.0 = no data or no impact) |

New optional query parameter:

| Param | Type | Required | Default | Validation | Description |
|-------|------|----------|---------|------------|-------------|
| `min_impact_score` | float | no | `0.0` | 0.0–1.0 | Filter signals with `market_impact_score ≥ value` |
| `order_by` | string | no | `"created_at"` | enum: `created_at`, `market_impact_score` | Sort order (DESC always) |

---

### 6.3 Event Changes

#### nlp.signal.detected.v1 — schema update

- **New field added** (forward-compatible per R5 — default value provided):

| Field | Type | Default | Nullable | Description |
|-------|------|---------|----------|-------------|
| `market_impact_score` | double | `0.0` | no | Normalised impact score 0.0–1.0. 0.0 = no OHLCV data for linked entities, or article predates 1D required data window. |

**Forward-compatibility**: existing consumers that do not read `market_impact_score` are unaffected. The field must be added to `nlp.signal.detected.v1.avsc` with `"default": 0.0`.

---

### 6.4 Database Changes

#### New table: `article_price_impacts` (`nlp_db`, owned by S6)

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `id` | UUID | no | `new_uuid7()` | PK | |
| `article_id` | UUID | no | — | UNIQUE NOT NULL | Logical FK to `content_store_db.documents.id` |
| `entity_id` | UUID | no | — | NOT NULL | Resolved canonical entity whose OHLCV was used |
| `symbol` | TEXT | no | — | NOT NULL | Ticker symbol used for OHLCV lookup |
| `published_at` | TIMESTAMPTZ | no | — | NOT NULL | Article publication time (UTC) |
| `ohlcv_date` | DATE | no | — | NOT NULL | OHLCV bar date that covers the published_at window |
| `price_open` | NUMERIC(18,8) | no | — | NOT NULL | Opening price of the covering OHLCV bar |
| `price_close` | NUMERIC(18,8) | no | — | NOT NULL | Closing price of the covering OHLCV bar |
| `price_delta_pct` | NUMERIC(10,6) | no | — | NOT NULL | `(close - open) / open * 100` |
| `next_day_delta_pct` | NUMERIC(10,6) | yes | `null` | — | Next-day close-to-close delta |
| `max_intraday_range_pct` | NUMERIC(10,6) | yes | `null` | — | `(high - low) / open * 100` for covering bar |
| `impact_score` | NUMERIC(6,4) | no | — | NOT NULL | Normalised 0.0–1.0 impact score |
| `computed_at` | TIMESTAMPTZ | no | `now()` | NOT NULL | When impact was computed |

- **Indexes**: `(article_id) UNIQUE`, `(entity_id, ohlcv_date)`, `(impact_score DESC)` partial on `impact_score > 0.3`
- **Partitioning**: none
- **Estimated rows**: ~500K total (historical backfill); ~5K/day steady state

---

### 6.5 Domain Model Changes

#### New entity: `ArticlePriceImpact` (frozen dataclass, S6)

- **Purpose**: Stores retrospective price-impact label for a processed article
- **Frozen**: yes

| Attribute | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| `id` | UUID | yes | UUIDv7 | Generated on creation |
| `article_id` | UUID | yes | UUIDv7 | Article from content store |
| `entity_id` | UUID | yes | UUIDv7 | Canonical entity used for price lookup |
| `symbol` | str | yes | 1–20 chars | Ticker symbol |
| `published_at` | datetime | yes | UTC-aware | Article publication time |
| `ohlcv_date` | date | yes | — | OHLCV bar date |
| `price_open` | Decimal | yes | > 0 | Opening price |
| `price_close` | Decimal | yes | > 0 | Closing price |
| `price_delta_pct` | Decimal | yes | — | `(close-open)/open*100`; can be negative |
| `next_day_delta_pct` | Decimal \| None | no | — | Optional next-day move |
| `max_intraday_range_pct` | Decimal \| None | no | — | Optional intraday volatility |
| `impact_score` | Decimal | yes | 0.0–1.0 | Normalised score |
| `computed_at` | datetime | yes | DB server default (`now()`) | When impact label was computed — set by Postgres, not the domain factory |

- **Invariants**: `published_at` is UTC-aware. `impact_score` in `[0.0, 1.0]`. `price_open > 0`, `price_close > 0`.
- **Factory**: `ArticlePriceImpact.compute(article_id, entity_id, symbol, published_at, ohlcv_bar)`

---

#### Impact Score Normalisation Formula

```
impact_score = min(1.0, abs(price_delta_pct) / IMPACT_NORMALISATION_CAP_PCT)
```

Where `IMPACT_NORMALISATION_CAP_PCT` defaults to `5.0` (configurable via `S6_IMPACT_NORMALISATION_CAP_PCT`).

Interpretation:
- A 0% price move → impact_score = 0.0
- A 5% price move → impact_score = 1.0
- A 10% price move → impact_score = 1.0 (capped)
- A 2.5% price move → impact_score = 0.5

This is intentionally simple and transparent. Option B (ML model) can replace this formula later.

If an article has multiple resolved entities, the maximum impact_score across all entities is used.

---

#### S6 Block 5 Routing Score — weight rebalance

Current weights (sum = 1.0):

| Signal | Current Weight |
|--------|---------------|
| `entity_density` | 0.30 |
| `source_reliability` | 0.20 |
| `novelty` | 0.15 |
| `recency` | 0.10 |
| `watchlist` | 0.10 |
| `document_type` | 0.10 |
| `extraction_yield` | 0.05 |
| **Total** | **1.00** |

New weights (sum = 1.0) with `price_impact` added:

| Signal | New Weight | Change |
|--------|-----------|--------|
| `entity_density` | 0.25 | -0.05 |
| `source_reliability` | 0.20 | — |
| `novelty` | 0.15 | — |
| `recency` | 0.10 | — |
| `watchlist` | 0.10 | — |
| `document_type` | 0.05 | -0.05 |
| `extraction_yield` | 0.05 | — |
| `price_impact` | **0.10** | **NEW** |
| **Total** | **1.00** | — |

**Rationale for entity_density reduction**: `price_impact` already correlates with entities (no impact without resolved entity), so entity_density is slightly redundant. Reducing `document_type` acknowledges that this heuristic is less discriminating than the actual price impact signal.

**Behaviour when no impact label available**: `price_impact` signal returns `0.0` — contributes 0 to routing score. Articles without OHLCV data are not penalised; they behave as before with effectively 7 signals.

---

#### New process: `PriceImpactLabellingWorker` (S6)

```
services/nlp-pipeline/src/nlp_pipeline/workers/
└── price_impact_labelling_worker.py
```

Entry point: `python -m nlp_pipeline.workers.price_impact_labelling_worker`

**Process lifecycle**:
1. On startup: run `labelling_cycle()` immediately, then loop on `PRICE_IMPACT_CYCLE_SECONDS` (default: 14400 = 4h)
2. `labelling_cycle()`:
   a. Query `nlp_db.entity_mentions` joined with `nlp_db.document_source_metadata` for articles with `resolved_entity_id IS NOT NULL` and `published_at < now() - interval '25 hours'`, not yet in `article_price_impacts`
   b. For each article: for each resolved entity from step (a), call S3 `/api/v1/market-data/ohlcv/{symbol}?date={ohlcv_date}` (internal call)
   c. Compute `ArticlePriceImpact`
   d. INSERT into `nlp_db.article_price_impacts` (ON CONFLICT DO NOTHING for idempotency)
   e. Batch size: 100 articles per cycle iteration to bound memory

**Dependencies**:
- `nlp_db` (R/W via existing S6 UoW — reads `entity_mentions` + `document_source_metadata`; writes `article_price_impacts`)
- S3 internal OHLCV API (HTTP client, not direct DB per R7)

**Error handling**:
- S3 unavailable: skip article, log warning, retry next cycle
- Missing OHLCV data for entity: `impact_score = 0.0`, still creates row (marks as "no data available")
- DB write failure: exponential backoff, max 3 retries

---

### 6.6 Frontend Changes

No new pages. Signals feed in J4 updates to:
- Show `market_impact_score` as a small badge (e.g. "Impact: 0.82") on each signal card
- Support sorting by `market_impact_score DESC` via a dropdown

---

### 6.7 Data Flow

#### Retrospective Labelling Flow (background)

```
[PriceImpactLabellingWorker] (every 4h)
  → query nlp_db: articles published > 25h ago, not yet in article_price_impacts
  → for each article: get resolved entities from entity_mentions
    → for each entity: call S3 GET /api/v1/market-data/ohlcv/{symbol}?date=...
      → compute ArticlePriceImpact (open, close, delta, impact_score)
  → INSERT article_price_impacts ON CONFLICT DO NOTHING
```

#### Routing Score Integration (real-time, Block 5)

```
[Block 5 RoutingScoreComputer.compute()]
  → check article_price_impacts for this article_id
  → if found: price_impact_signal = article.impact_score (0.0–1.0)
  → if not found: price_impact_signal = 0.0 (no penalty)
  → routing_score += WEIGHT_PRICE_IMPACT * price_impact_signal
```

**Note**: For newly-ingested articles (< 25h old), `price_impact` will always be 0.0. This is correct — we do not have retrospective data yet. The signal becomes available on the next labelling cycle.

---

## 7. Architecture Decisions

### AD-1: Option A vs Option B

**Option A (this PRD)**: Extend existing Block 5 routing score with retrospective price-impact lookup.
- Pro: No new ML model, no training pipeline, immediately correct (retrospective facts)
- Pro: Creates labelled training dataset as a side effect
- Con: Retrospective only — cannot score articles whose price window hasn't elapsed yet
- Con: Signal is 0.0 for ≥25h after ingestion

**Option B (future PRD)**: Dedicated `MarketImpactScorer` model in `ml-clients` trained on the `article_price_impacts` table.
- Pro: Can score at ingestion time using text features (real-time classification)
- Pro: Can filter out noise *before* articles enter the pipeline
- Con: Requires training pipeline, labelled data (~100K rows minimum), evaluation framework
- Con: Model drift requires retraining

**Decision**: Option A now. The `article_price_impacts` table from this PRD becomes the training dataset for Option B.

### AD-2: OHLCV resolution strategy for ±30m/±1h windows

Since worldview uses **daily** OHLCV (not intraday), we cannot compute true ±30m or ±1h windows. Instead:
- "Within-day impact": use `(close - open) / open` of the OHLCV bar whose date contains `published_at`
- "Next-day impact": `(next_day_close - today_close) / today_close`
- These are proxies, not exact windows — documented in code and this PRD

**Implication**: The impact_score is a daily-granularity signal. Option B with intraday data (if sourced in future) would be more precise.

### AD-3: Option B design notes (for future PRD)

Future `MarketImpactScorer` design:
- Input: article text, entity_density, source_type, published_at (weekday/time)
- Output: `market_impact_probability` (0.0–1.0)
- Training data: `article_price_impacts` table (label: `impact_score > 0.3`)
- Model: LightGBM or similar (small, CPU-fast) served via `ml-clients.MarketImpactClient`
- Serving: `ml-clients` exposes `predict_batch(articles: list[ArticleFeatures]) -> list[float]`
- Integration: Block 4.5 (new block between NER and routing score) — runs before Block 5

---

## 8. Security Analysis

| Threat | Mitigation |
|--------|-----------|
| Cross-service DB access for OHLCV | Worker uses S3 REST API, not direct DB query (R7) |
| Price data poisoning | S3 OHLCV comes from EODHD (trusted external source); no user-supplied input in impact computation |
| Worker CPU exhaustion | Batch size capped at 100; 4h cycle; `asyncio.sleep()` between batches |
| SQL injection via symbol field | Symbol comes from resolved canonical entities in `nlp_db` — internal trusted data |

---

## 9. Failure Modes

| Failure | Detection | Recovery |
|---------|-----------|---------|
| S3 OHLCV API unavailable | `httpx.RequestError` → skip article, log warning | Retry on next 4h cycle; no data loss |
| Missing OHLCV for symbol | S3 returns 404 for symbol | `impact_score = 0.0`, create row with `price_delta_pct = 0` |
| `nlp_db` unavailable | Worker startup fails | Exit with code 1, Docker Compose restart policy restarts |
| Block 5 routing score assertion fails | `AssertionError: weights != 1.0` | Unit test catches this before deployment |
| Historical backfill overwhelms S3 | 500K articles × 1 req each = high S3 load | Throttle: `asyncio.sleep(0.1)` between batches; max 100 req/batch |

---

## 10. Scalability

| Concern | Estimate | Mitigation |
|---------|----------|-----------|
| `article_price_impacts` table growth | ~5K rows/day steady state | No partitioning needed; index on `impact_score DESC` for ranking queries |
| Backfill duration | ~500K existing articles / (100 articles/batch × ~1s/batch) ≈ 1.4 hours | Run backfill as one-off job on deployment; ongoing cycles are fast |
| S3 OHLCV lookup volume | ~100 lookups/cycle minimum | S3 `/api/v1/market-data/ohlcv` is a cached read endpoint; acceptable load |

---

## 11. Test Strategy

### Unit Tests (S6)

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_impact_score_normalisation_zero` | `0% delta → impact_score = 0.0` | HIGH |
| `test_impact_score_normalisation_at_cap` | `5% delta → impact_score = 1.0` | HIGH |
| `test_impact_score_normalisation_exceeds_cap` | `10% delta → impact_score = 1.0 (capped)` | HIGH |
| `test_impact_score_normalisation_partial` | `2.5% delta → impact_score ≈ 0.5` | HIGH |
| `test_block5_weights_sum_to_one` | New weight set sums to exactly 1.0 | HIGH |
| `test_block5_price_impact_zero_when_no_label` | Article with no `article_price_impacts` row → price_impact_signal = 0.0 | HIGH |
| `test_block5_price_impact_uses_max_across_entities` | Article with 2 entities, scores 0.3 and 0.7 → uses 0.7 | HIGH |
| `test_article_price_impact_invariants` | `impact_score < 0` raises `ValueError` | HIGH |
| `test_labelling_worker_skips_articles_under_min_age` | Articles published < 25h ago are excluded | HIGH |
| `test_labelling_worker_idempotent` | Running twice on same articles → no duplicate rows | HIGH |

### Integration Tests (S6)

| Test | Infrastructure | What It Verifies |
|------|---------------|-----------------|
| `test_price_impact_labelling_worker_end_to_end` | Postgres + wiremock (S3 OHLCV API mock) | Worker fetches unlabelled articles, calls S3, inserts `article_price_impacts` rows |
| `test_labelling_worker_handles_missing_ohlcv` | Postgres + wiremock (S3 returns 404) | Worker creates row with `impact_score = 0.0` |
| `test_signals_api_returns_market_impact_score` | Postgres | `GET /api/v1/signals` response includes `market_impact_score` field |
| `test_signals_api_filter_by_min_impact` | Postgres | `min_impact_score=0.5` filters correctly |

### Contract Tests

| Test | What It Verifies |
|------|-----------------|
| `test_signal_detected_v1_backward_compatible` | Adding `market_impact_score` with default `0.0` passes Avro compatibility check |
| `test_signal_detected_v1_serialisation` | Signal with `market_impact_score=0.75` serialises/deserialises correctly |

---

## 12. Migration Plan

1. **Alembic**: Add `article_price_impacts` table to `nlp_db` in a new migration.
2. **Avro**: Update `nlp.signal.detected.v1.avsc` with `market_impact_score` field (default 0.0). Register with Schema Registry before deploying S6.
3. **Config**: Add `S6_IMPACT_NORMALISATION_CAP_PCT=5.0`, `PRICE_IMPACT_CYCLE_SECONDS=14400`, `PRICE_IMPACT_MIN_AGE_HOURS=25`, and `S6_MARKET_DATA_INTERNAL_URL=http://market-data:8003` to S6 env.
4. **Backfill**: On first worker startup, it automatically backlabels all unlabelled articles older than 25h. Estimated 1.4h for 500K articles. No manual intervention needed.
5. **Deployment order**: Deploy S6 with new `PriceImpactLabellingWorker` process after S3 OHLCV API is confirmed healthy.

---

## 13. Observability

| Metric | Labels | Description |
|--------|--------|-------------|
| `s6_price_impact_labels_computed_total` | `status={success,no_ohlcv,error}` | Labelling worker throughput |
| `s6_price_impact_cycle_duration_seconds` | — | Time per 4h labelling cycle |
| `s6_routing_score_price_impact_histogram` | — | Distribution of `price_impact` signal values |

### Log fields

- Worker: `service=nlp-pipeline`, `worker=price_impact_labelling`, `article_id`, `entity_id`, `impact_score`
- Block 5: `price_impact_signal`, `price_impact_source={label,no_data}`

---

## 14. Open Questions

| ID | Question | Owner | Deadline |
|----|----------|-------|----------|
| OQ-001 | ~~Should LIGHT-tier articles (no entity resolution) have `impact_score=0.0` or be excluded from `article_price_impacts` entirely?~~ **Resolved 2026-04-09**: LIGHT-tier articles are excluded automatically — the worker's `resolved_entity_id IS NOT NULL` filter on `entity_mentions` ensures only articles with resolved entities are processed. No routing tier filter needed. | Arnau | **Resolved** |
| OQ-002 | Should the weight rebalance be A/B tested, or applied globally? For thesis: apply globally. | Arnau | Confirmed: global |
| OQ-003 | Future Option B: what minimum labelled dataset size before training? Suggested: 10K rows with impact_score > 0.0 (non-trivial moves) | Arnau | Future PRD |

---

## 15. Effort Estimation

| Area | Waves | Complexity |
|------|-------|-----------|
| `article_price_impacts` DB table + Alembic migration | 0.5 wave | Low |
| `PriceImpactLabellingWorker` + S3 HTTP client | 1.5 waves | Medium |
| Block 5 weight rebalance + `price_impact` signal | 1 wave | Low-Medium |
| `nlp.signal.detected.v1` Avro schema update | 0.5 wave | Low |
| S6 API `market_impact_score` field + filter | 0.5 wave | Low |
| Frontend signal card badge | 0.5 wave | Low |
| Tests + docs | 1 wave | Medium |
| **Total** | **~5.5 waves** | — |
