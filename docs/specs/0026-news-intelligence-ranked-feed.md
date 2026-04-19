# PRD-0026 — News Intelligence APIs: Ranked News Feed, Multi-Window Impact & LLM Relevance Scoring

> **Status**: Draft — revised 2026-04-12 (revise-prd: 3 blocking + 5 high issues fixed)
> **Author**: Arnau Rodon
> **Services affected**: S6 (NLP Pipeline), S9 (API Gateway), Frontend
> **Depends on**: PLAN-0020 complete (`article_price_impacts` table + `PriceImpactLabellingWorker` exist), PLAN-0021 complete (`AlertSeverity`, signal scoring pipeline complete)
> **Plan**: PLAN-0026 (to be generated)

---

## 1. Problem Statement

Worldview's intelligence pipeline has accumulated three distinct relevance signals for news articles:

1. **Routing score** (`routing_decisions.composite_score`) — a composite of 8 signals (entity density, source reliability, novelty, recency, watchlist, price impact, document type, extraction yield) computed in real-time at ingestion. Designed to route articles to the correct NLP processing tier (LIGHT/MEDIUM/DEEP), not for user display.

2. **Market impact score** (`article_price_impacts.impact_score`) — retrospective correlation between article publication and stock price movement. A factual, ground-truth signal, but carries a mandatory 25h lag (needs next-day OHLCV). Currently stored in a single-window flat table; no temporal granularity.

3. **No LLM relevance score** — articles routed to the LLM for deep extraction never produce a user-facing relevance estimate. The LLM's analysis is stored as embeddings and entity mentions, but its assessment of "how important is this article?" is discarded.

Despite having this data, the frontend surfaces news in undifferentiated chronological feeds — the same display for a routine quarterly filing and a CEO resignation. Research analysts must manually triage every article. The market-moving events are invisible.

Additionally, `article_price_impacts` is limited to a single daily OHLCV proxy per article. Storing multi-day impact windows (day_t0 through day_t5) would:
- Give a richer training dataset for future ML models (time-series features showing sustained vs transient impact)
- Enable the platform to distinguish a 1-day spike from a sustained trend

This PRD delivers:
1. A multi-window redesign of the price impact table (day_t0/t1/t2/t5, extensible to future intraday)
2. An `ArticleRelevanceScoringWorker` that uses Qwen2.5:3b (local LLM) to score MEDIUM/DEEP articles
3. A `display_relevance_score` combining all available signals, computed at query time
4. Two new S6 endpoints exposing scored news: global top-N feed and entity-scoped ranked feed
5. S9 proxy routes and frontend types to enable UI consumption
6. A UI requirements holding doc (`docs/ui/news-intelligence.md`) capturing decisions for the future UI PRD

---

## 2. Target Users

| User | Workflow | Benefit |
|------|----------|---------|
| **Research Analysts** (J3/J4) | Monitoring news feeds while multitasking | Most market-moving articles float to top; routine filings sink |
| **Retail Investors** (J3) | Checking company news before making a trade | Company detail page shows highest-impact news for the selected period |
| **Quantitative Traders** (API) | Building signals from news data | `display_relevance_score` + per-window impact scores as features |
| **ML Engineers** (future) | Training price-impact prediction models | Multi-window `article_impact_windows` table as a structured training dataset |
| **Thesis Evaluators** | Assessing system sophistication | Demonstrates data pipeline → scoring → ranked display as an end-to-end intelligence story |

---

## 3. Functional Requirements

### 3.1 Multi-Window Price Impact (extends PRD-0020)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-01 | Create new table `article_impact_windows` in `nlp_db` with one row per (article_id, entity_id, window_type) | MUST |
| F-02 | `window_type` values: `day_t0` (publication day), `day_t1` (next day), `day_t2` (2 days out), `day_t5` (5 trading days out) — all using daily OHLCV proxy | MUST |
| F-03 | `window_type` enum includes reserved future values: `intraday_1h`, `intraday_4h` — not computed now, schema only | SHOULD |
| F-04 | `data_quality` field (`daily_proxy` | `exact_intraday`) distinguishes daily approximation from future exact intraday data | MUST |
| F-05 | `impact_score` normalisation cap is configurable per window type: day_t0=5.0%, day_t1=5.0%, day_t2=7.5%, day_t5=10.0% | MUST |
| F-06 | Enhanced `PriceImpactLabellingWorker` computes all four daily windows per article/entity pair | MUST |
| F-07 | Window data becomes available progressively: day_t0 after 25h, day_t1 after 49h, day_t2 after 73h, day_t5 after 145h | MUST |
| F-08 | Existing `article_price_impacts` data is migrated to `article_impact_windows` (as `day_t0` rows) and the old table is dropped | MUST |
| F-09 | Each labelling cycle batch size remains 100 articles max; per-window `ON CONFLICT DO NOTHING` for idempotency | MUST |

### 3.2 LLM Relevance Scoring

| ID | Requirement | Priority |
|----|-------------|----------|
| F-10 | New `ArticleRelevanceScoringWorker` runs every 30 minutes as an independent process (R22) | MUST |
| F-11 | Worker scores MEDIUM and DEEP tier articles (from `routing_decisions.routing_tier`) using Qwen2.5:3b via Ollama | MUST |
| F-12 | Prompt uses `document_source_metadata.title` + `source_type`; no MinIO access required for v1 | MUST |
| F-13 | Prompt requests JSON response: `{"score": <float 0.0-1.0>, "reason": "<10-word max>"}` | MUST |
| F-14 | Score stored as `llm_relevance_score NUMERIC(6,4)` in `document_source_metadata`; timestamp in `llm_scored_at` | MUST |
| F-15 | LIGHT tier articles: `llm_relevance_score` stays NULL; their display score uses routing_score fallback only | MUST |
| F-16 | Worker processes newest articles first (ORDER BY `published_at DESC`) to prioritise fresh content | MUST |
| F-17 | JSON parse failure or Ollama unavailability: skip article, log warning, retry next cycle | MUST |
| F-18 | Ollama model `qwen2.5:3b` must be available in docker-compose (already present from S8 infrastructure) | MUST |

### 3.3 New Ranked News Endpoints

| ID | Requirement | Priority |
|----|-------------|----------|
| F-19 | New `GET /api/v1/news/top` endpoint in S6 returns globally top-N articles by `display_relevance_score` within a configurable time window | MUST |
| F-20 | `display_relevance_score` is computed at query time as a weighted combination of `market_impact_score`, `llm_relevance_score`, and `routing_score` (see §6.5 formula) | MUST |
| F-21 | `GET /api/v1/entities/{entity_id}/articles` is enhanced with scoring fields, `start_date`/`end_date` range params, `order_by` param, and pagination | MUST |
| F-22 | Both endpoints return `total` (COUNT(*) OVER() window function pattern per PRD-0017) | MUST |
| F-23 | Both endpoints use `ReadOnlyUnitOfWork` (R27) | MUST |
| F-24 | New index on `document_source_metadata(published_at DESC)` and `routing_decisions(doc_id)` for query performance | MUST |

### 3.4 S9 Gateway & Frontend

| ID | Requirement | Priority |
|----|-------------|----------|
| F-25 | S9 proxies `GET /api/v1/news/top` → S6 `GET /api/v1/news/top` | MUST |
| F-26 | S9 proxies `GET /api/v1/news/entity/{entity_id}` → S6 `GET /api/v1/entities/{entity_id}/articles` | MUST |
| F-27 | Frontend `gateway-client.ts` gains `RankedArticle` type and `getTopNews()` / `getEntityNews()` methods | MUST |
| F-28 | UI requirements captured in `docs/ui/news-intelligence.md` for the future UI PRD | MUST |

---

## 4. Non-Functional Requirements

| Attribute | Target |
|-----------|--------|
| `GET /api/v1/news/top` latency | < 200ms p95 with new indexes (LATERAL JOIN + CTE, 500K rows) |
| `GET /api/v1/entities/{entity_id}/articles` latency | < 150ms p95 (entity_mentions already indexed) |
| LLM scoring throughput | 50 articles/cycle × 30min cycles = 2,400 articles/day; 3B model ~0.5–1s/call |
| Multi-window labelling coverage | day_t0: ~100% of MEDIUM/DEEP articles within 25h; day_t5: available within 7 days |
| `article_impact_windows` table size | ~3M rows steady state (500K articles × ~4 windows × ~1.5 entities avg) |
| Backward compatibility | PRD-0020 `market_impact_score` field on `nlp.signal.detected.v1` event unchanged (still uses day_t0 impact_score) |
| Worker failure isolation | Each worker (labelling, LLM scoring) fails independently; main NLP pipeline unaffected |
| `data_quality` field | All rows computed from daily OHLCV marked `daily_proxy`; `exact_intraday` reserved for future |

---

## 5. Out of Scope

- **Intraday price impact windows** (5min, 15min, 1h, 4h) — requires intraday OHLCV data, not currently sourced; schema accommodates them
- **Fundamentals UI** — deferred to UI PRD (no display spec yet)
- **Watchlist-scoped news feed** — needs auth (PRD-0025) + watchlist (PRD-0022)
- **User alert threshold preferences** — needs auth, deferred to post-PRD-0025
- **Portfolio-scoped news** — needs PRD-0022/PRD-0025
- **Vector embedding re-ranking** — future PRD; entity mention-based filtering is sufficient for v1
- **Frontend implementation of news tabs** — types + API client only; UI implementation is the UI PRD's job
- **LLM reason field storage** — `reason` from LLM JSON response is logged but not persisted; only `score` is stored
- **Retroactive LLM scoring for all historical articles** — worker scores forward from deployment; historical backfill is a future operational task

---

## 6. Technical Design

### 6.1 Affected Services

| Service | Change Type | Summary |
|---------|-------------|---------|
| **S6 NLP Pipeline** | New table + 2 new columns + 2 modified/new workers + 2 new endpoints | Replace `article_price_impacts` → `article_impact_windows`; add `llm_relevance_score`/`llm_scored_at` to `document_source_metadata`; enhance `PriceImpactLabellingWorker`; new `ArticleRelevanceScoringWorker`; new `GET /api/v1/news/top`; enhanced `GET /api/v1/entities/{entity_id}/articles` |
| **`intelligence-migrations`** | No change | `article_impact_windows` lives in `nlp_db`, owned by S6 Alembic |
| **S9 API Gateway** | 2 new proxy routes | `GET /api/v1/news/top` and `GET /api/v1/news/entity/{entity_id}` |
| **Frontend** | New types + API client methods | `RankedArticle`, `RankedNewsResponse`, `getTopNews()`, `getEntityNews()` |

---

### 6.2 API Changes

#### GET /api/v1/news/top (S6 — new endpoint)

- **Purpose**: Returns globally top-N articles ranked by `display_relevance_score` within a rolling time window
- **Auth**: OIDC (validated by S9 via Zitadel JWKS); S9 forwards `X-Internal-JWT` (RS256, PRD-0025) to S6. S6 validates via `InternalJWTMiddleware` using S9's public key from `GET /internal/jwks`. Rate-limited at S9: 100 req/min per authenticated user.
- **Query parameters**:

  | Param | Type | Required | Default | Validation | Description |
  |-------|------|----------|---------|------------|-------------|
  | `hours` | int | no | `24` | 1–168 (7 days) | Look-back window from `now()` UTC |
  | `limit` | int | no | `20` | 1–100 | Page size |
  | `offset` | int | no | `0` | ≥ 0 | Pagination offset |
  | `min_display_score` | float | no | — | 0.0–1.0 | Exclude articles below threshold |
  | `routing_tier` | string | no | — | enum: `LIGHT`, `MEDIUM`, `DEEP` | Filter by NLP processing tier |

- **Response** (200):

  | Field | Type | Description |
  |-------|------|-------------|
  | `articles` | `RankedArticle[]` | Sorted list |
  | `total` | int | Total matching count (window function) |

- **RankedArticle schema**:

  | Field | Type | Nullable | Description |
  |-------|------|----------|-------------|
  | `article_id` | UUID | no | `doc_id` from `document_source_metadata` |
  | `title` | string | yes | Article title (null for some source types) |
  | `url` | string | yes | Original source URL |
  | `published_at` | string | yes | ISO-8601 UTC |
  | `source_type` | string | yes | `eodhd_news`, `finnhub`, `newsapi`, `sec_10k`, etc. |
  | `source_name` | string | yes | Human-readable provider (e.g., "EODHD") |
  | `routing_tier` | string | yes | `LIGHT`, `MEDIUM`, `DEEP` — from `routing_decisions` |
  | `routing_score` | float | yes | `composite_score` from `routing_decisions` |
  | `market_impact_score` | float | yes | `MAX(day_t0, day_t1)` from `article_impact_windows`; null if no windows computed yet |
  | `llm_relevance_score` | float | yes | LLM-assigned relevance; null for LIGHT tier or not yet scored |
  | `display_relevance_score` | float | no | Computed composite (see §6.5 formula); always present |
  | `primary_entity_id` | UUID | yes | Entity with highest impact_score (from `article_impact_windows`) |
  | `primary_entity_symbol` | string | yes | Ticker symbol of primary entity |
  | `impact_windows` | object | yes | Per-window scores: `{"day_t0": 0.72, "day_t1": 0.51, ...}` — null keys if window not computed |

- **Error responses**:
  - `400`: Invalid param (hours > 168, limit > 100, offset < 0, invalid enum value)
  - `422`: Malformed float for `min_display_score`
- **Rate limit**: 100 req/min (enforced at S9)

---

#### GET /api/v1/entities/{entity_id}/articles (S6 — enhanced)

- **Purpose**: Returns articles mentioning a specific canonical entity, ranked by `display_relevance_score`, with date range filtering
- **Auth**: OIDC via S9 (same `X-Internal-JWT` flow as above)
- **Path parameters**:

  | Param | Type | Required | Validation | Description |
  |-------|------|----------|------------|-------------|
  | `entity_id` | UUID | yes | valid UUIDv7 | Canonical entity ID |

- **Query parameters**:

  | Param | Type | Required | Default | Validation | Description |
  |-------|------|----------|---------|------------|-------------|
  | `start_date` | string | no | `now() - 7d` | ISO-8601 UTC datetime | Lower bound on `published_at` |
  | `end_date` | string | no | `now()` | ISO-8601 UTC, ≥ `start_date` | Upper bound on `published_at` |
  | `order_by` | string | no | `"display_relevance_score"` | enum: `display_relevance_score`, `published_at` | Sort field (DESC always) |
  | `limit` | int | no | `20` | 1–100 | Page size |
  | `offset` | int | no | `0` | ≥ 0 | Pagination offset |

- **Response** (200): `{ articles: RankedArticle[], total: int }` — same `RankedArticle` schema as above, without `primary_entity_*` fields (entity is already specified in path)

- **Error responses**:
  - `400`: `start_date > end_date`, limit > 100, invalid date format
  - `404`: No articles found for `entity_id` in the specified date range (returns `{"articles": [], "total": 0}` — not 404; empty result is valid)
  - `422`: Malformed UUID in path

---

#### S9 Proxy Routes (new)

| Frontend path | Proxied to S6 | Notes |
|---------------|---------------|-------|
| `GET /api/v1/news/top` | `GET /api/v1/news/top` | Direct pass-through; all query params forwarded |
| `GET /api/v1/news/entity/{entity_id}` | `GET /api/v1/entities/{entity_id}/articles` | Path rewrite: `/news/entity/{id}` → `/entities/{id}/articles` |

---

### 6.3 Event Changes

**No new Kafka events.** This PRD adds read-only query endpoints and background workers. No events are produced or consumed beyond what PRD-0020 established.

**Existing event compatibility**: `nlp.signal.detected.v1` continues to use `market_impact_score` from `article_impact_windows` where `window_type = 'day_t0'` (identical semantics to the old `article_price_impacts.impact_score`). S10's `IntelligenceConsumer` is unaffected.

---

### 6.4 Database Changes

#### New table: `article_impact_windows` (`nlp_db`, replaces `article_price_impacts`)

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `id` | UUID | no | `new_uuid7()` | PK | |
| `article_id` | UUID | no | — | NOT NULL | Logical FK to `document_source_metadata.doc_id` |
| `entity_id` | UUID | no | — | NOT NULL | Canonical entity used for OHLCV lookup |
| `symbol` | TEXT | no | — | NOT NULL | Ticker symbol |
| `published_at` | TIMESTAMPTZ | no | — | NOT NULL | Article publication time (UTC) |
| `window_type` | VARCHAR(20) | no | — | NOT NULL | See window_type enum below |
| `window_start` | TIMESTAMPTZ | no | — | NOT NULL | Window start UTC (for day_t0: midnight of article's OHLCV date) |
| `window_end` | TIMESTAMPTZ | no | — | NOT NULL | Window end UTC (for day_t0: midnight of next day) |
| `price_start` | NUMERIC(18,8) | no | — | NOT NULL | Open price at window start |
| `price_end` | NUMERIC(18,8) | no | — | NOT NULL | Close price at window end |
| `delta_pct` | NUMERIC(10,6) | no | — | NOT NULL | `(price_end - price_start) / price_start * 100`; may be negative |
| `high_pct` | NUMERIC(10,6) | yes | null | — | Max intraday high relative to `price_start` (for daily proxy: from OHLCV `high`) |
| `low_pct` | NUMERIC(10,6) | yes | null | — | Max intraday low relative to `price_start` (for daily proxy: from OHLCV `low`) |
| `volume` | NUMERIC(18,2) | yes | null | — | Volume in window (from OHLCV `volume`) |
| `impact_score` | NUMERIC(6,4) | no | — | NOT NULL | Normalised 0.0–1.0 using `data_quality`-specific cap |
| `normalisation_cap_pct` | NUMERIC(6,2) | no | — | NOT NULL | Cap used in normalisation (see per-window defaults) |
| `data_quality` | VARCHAR(20) | no | `'daily_proxy'` | NOT NULL | `daily_proxy` | `exact_intraday` |
| `computed_at` | TIMESTAMPTZ | no | `now()` | NOT NULL | When computed |

**Window type enum** (`window_type` values):

| Value | Description | Available Now | `normalisation_cap_pct` default |
|-------|-------------|---------------|--------------------------------|
| `day_t0` | Publication-day OHLCV bar (open → close) | YES | 5.0% (`S6_CAP_DAY_T0_PCT`) |
| `day_t1` | Following-day OHLCV bar (prev close → close) | YES (after 49h) | 5.0% (`S6_CAP_DAY_T1_PCT`) |
| `day_t2` | 2-day cumulative (close_t0 → close_t2) | YES (after 73h) | 7.5% (`S6_CAP_DAY_T2_PCT`) |
| `day_t5` | 5-trading-day cumulative (close_t0 → close_t5) | YES (after 145h) | 10.0% (`S6_CAP_DAY_T5_PCT`) |
| `intraday_1h` | True 1h window after publication | Future | TBD |
| `intraday_4h` | True 4h window after publication | Future | TBD |

**Indexes**:
- `(article_id, entity_id, window_type)` UNIQUE INDEX — idempotency constraint; required for `ON CONFLICT (article_id, entity_id, window_type) DO NOTHING`
- `(entity_id, window_type, published_at DESC)` — entity-scoped queries
- `(window_type, impact_score DESC)` PARTIAL on `window_type = 'day_t0'` — global top-news queries
- `(article_id)` — for JOIN from `document_source_metadata` queries

**Partitioning**: none (3M rows is manageable without partitioning for thesis scale)

**Estimated rows**: ~500K articles × 4 windows × 1.5 entities avg ≈ 3M rows at steady state

**Migration from `article_price_impacts`** (Alembic):
1. `CREATE TABLE article_impact_windows (...)`
2. `INSERT INTO article_impact_windows (...) SELECT ... FROM article_price_impacts WHERE price_open > 0` — map as `window_type = 'day_t0'`; filter `price_open > 0` to exclude zero-sentinel rows (from `ArticlePriceImpact.zero()` where OHLCV was unavailable — these represent "no data", not a valid measurement)
3. ~~Migrate `next_day_delta_pct` as day_t1 rows~~ — **NOT FEASIBLE**: `article_price_impacts` stores only the next-day delta percentage, not the open/close prices required by `article_impact_windows (price_start NOT NULL, price_end NOT NULL)`. The enhanced `PriceImpactLabellingWorker` will compute day_t1/t2/t5 windows forward from deployment.
4. `DROP TABLE article_price_impacts`

---

#### Modified table: `document_source_metadata` (`nlp_db`)

Two new nullable columns:

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `llm_relevance_score` | NUMERIC(6,4) | yes | null | — | 0.0–1.0 LLM-assigned score; null until `ArticleRelevanceScoringWorker` processes |
| `llm_scored_at` | TIMESTAMPTZ | yes | null | — | UTC timestamp when LLM scored this article |

- **Migration**: `ALTER TABLE document_source_metadata ADD COLUMN llm_relevance_score NUMERIC(6,4), ADD COLUMN llm_scored_at TIMESTAMPTZ` — both nullable, zero-downtime

**New indexes on `document_source_metadata`**:
- `(published_at DESC)` — for time-window queries in `GetTopNewsUseCase`
- `(llm_relevance_score DESC) WHERE routing_tier = 'MEDIUM' OR routing_tier = 'DEEP'` — for scoring worker prioritisation (requires `routing_tier` from JOIN with `routing_decisions`)

**Note**: `routing_score` and `routing_tier` are NOT added to `document_source_metadata`. They are already persisted in `routing_decisions.composite_score` and `routing_decisions.routing_tier` respectively, accessible via `doc_id` JOIN.

---

#### New index: `routing_decisions(doc_id)` (`nlp_db`)

```sql
CREATE INDEX CONCURRENTLY idx_routing_decisions_doc_id ON routing_decisions (doc_id);
```

Required to make the JOIN between `document_source_metadata` and `routing_decisions` efficient (currently `doc_id` has no index — only `decision_id` PK exists).

---

### 6.5 Domain Model Changes

#### New entity: `ArticleImpactWindow` (S6 domain, frozen)

- **Purpose**: One price-impact measurement for a specific article + entity + time window combination
- **Frozen**: yes

| Attribute | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| `id` | UUID | yes | UUIDv7 | Generated on creation |
| `article_id` | UUID | yes | UUIDv7 | Logical FK to document_source_metadata |
| `entity_id` | UUID | yes | UUIDv7 | Canonical entity |
| `symbol` | str | yes | 1–20 chars | Ticker |
| `published_at` | datetime | yes | UTC-aware | Article publication time |
| `window_type` | WindowType | yes | enum member | See WindowType enum |
| `window_start` | datetime | yes | UTC-aware | Window start |
| `window_end` | datetime | yes | UTC-aware | Window end; must be > window_start |
| `price_start` | Decimal | yes | > 0 | Open price at start |
| `price_end` | Decimal | yes | > 0 | Close price at end |
| `delta_pct` | Decimal | yes | — | Signed percentage change |
| `high_pct` | Decimal \| None | no | — | Optional; from OHLCV high |
| `low_pct` | Decimal \| None | no | — | Optional; from OHLCV low |
| `volume` | Decimal \| None | no | — | Optional; OHLCV volume |
| `impact_score` | Decimal | yes | 0.0–1.0 | `min(1.0, abs(delta_pct) / normalisation_cap_pct)` |
| `normalisation_cap_pct` | Decimal | yes | > 0 | Per-window cap (configurable) |
| `data_quality` | DataQuality | yes | enum member | `daily_proxy` or `exact_intraday` |
| `computed_at` | datetime | yes | DB default | Set by Postgres |

**Invariants**: `window_end > window_start`; `impact_score ∈ [0.0, 1.0]`; `price_start > 0`; `price_end > 0`

**Enums**:
```python
class WindowType(StrEnum):
    DAY_T0 = "day_t0"
    DAY_T1 = "day_t1"
    DAY_T2 = "day_t2"
    DAY_T5 = "day_t5"
    INTRADAY_1H = "intraday_1h"   # reserved, not computed yet
    INTRADAY_4H = "intraday_4h"   # reserved, not computed yet

class DataQuality(StrEnum):
    DAILY_PROXY = "daily_proxy"
    EXACT_INTRADAY = "exact_intraday"
```

**Factory**: `ArticleImpactWindow.compute(article_id, entity_id, symbol, published_at, window_type, ohlcv_bar, cap_pct)`

---

#### Modified entity: `DocumentSourceMetadata` (S6 domain)

Two new optional fields:

| Attribute | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| *(existing fields)* | — | — | Unchanged | — |
| `llm_relevance_score` | Decimal \| None | no | 0.0–1.0 if present | Null until LLM worker runs |
| `llm_scored_at` | datetime \| None | no | UTC-aware | Null until LLM worker runs |

---

#### New value object: `DisplayRelevanceScore` (S6 domain)

```python
@dataclass(frozen=True)
class DisplayRelevanceScore:
    """Composite relevance score for user-facing article ranking."""
    market_impact: float | None   # MAX(day_t0, day_t1) impact_score; None if no windows yet
    llm_relevance: float | None   # LLM score; None for LIGHT tier or unscored
    routing_score: float | None   # composite_score from routing_decisions; None if unavailable

    @property
    def value(self) -> float:
        """Compute weighted composite score.

        Uses explicit ``is not None`` checks to distinguish between
        "signal not yet available" (None) and "signal available but zero"
        (0.0). A zero market impact is a factual ground-truth signal and
        must not be treated identically to an unlabelled article.
        """
        mi = self.market_impact  # None = not yet labelled; 0.0 = genuinely zero movement
        llm = self.llm_relevance
        rs = self.routing_score or 0.0

        if mi is not None and mi > 0 and llm is not None:
            return 0.50 * mi + 0.40 * llm + 0.10 * rs
        if mi is not None and mi > 0:
            return 0.70 * mi + 0.30 * rs
        if llm is not None:
            return 0.60 * llm + 0.40 * rs
        # LIGHT tier / no scoring available yet; mi=0.0 (zero movement) falls here too
        return rs * 0.40
```

**Note**: computed at query time in the use case layer, not stored. The SQL equivalent (CASE expression) mirrors this logic for direct DB ordering.

**Rationale for weights**:
- Market impact (0.5 or 0.7): retrospective ground truth — "did the market actually react?" is the strongest signal
- LLM relevance (0.4 or 0.6): forward-looking expert estimate — valuable when market data is not yet available
- Routing score (0.1 or 0.3): system heuristic — weakest signal but always available; ensures LIGHT tier articles are not completely invisible
- Articles with only routing_score (LIGHT tier) are penalised to 0.4× — they are genuinely less informative than MEDIUM/DEEP articles

---

#### New process: `ArticleRelevanceScoringWorker` (S6)

```
services/nlp-pipeline/src/nlp_pipeline/workers/
└── article_relevance_scoring_worker.py
```

Entry point: `python -m nlp_pipeline.workers.article_relevance_scoring_worker`

**Process lifecycle**:
1. On startup: run `scoring_cycle()` immediately, then loop on `RELEVANCE_SCORING_CYCLE_SECONDS` (default: 1800 = 30min)
2. `scoring_cycle()` — **three phases (R24: no DB session held across Ollama calls)**:

   **Phase 1 — Read** (open session → close before HTTP):
   - Query: `document_source_metadata dsm JOIN routing_decisions rd ON rd.doc_id = dsm.doc_id`
     WHERE `dsm.llm_relevance_score IS NULL`
     AND `COALESCE(rd.final_routing_tier, rd.routing_tier) IN ('MEDIUM', 'DEEP')`
     ORDER BY `dsm.published_at DESC`
     LIMIT `RELEVANCE_SCORING_BATCH_SIZE` (default: 50)
   - Collect `[(doc_id, title, source_type)]` list; **close session**

   **Phase 2 — Score** (no open DB sessions):
   - For each article: build prompt from `title` + `source_type`
   - POST Ollama `/api/generate` with `{"model": "qwen2.5:3b", "prompt": "...", "format": "json", "stream": false}`
     (the `format: "json"` flag activates Ollama's constrained JSON output mode — more reliable than prompt instruction alone)
   - Timeout: `RELEVANCE_SCORING_TIMEOUT_SECONDS` (default 30s — allows for cold-start model loading on first call)
   - Parse response: `{"score": <float>, "reason": "<str>"}`
   - Collect `[(doc_id, clamped_score)]` pairs

   **Phase 3 — Write** (open new session → commit → close):
   - Batch UPDATE `document_source_metadata SET llm_relevance_score = :score, llm_scored_at = NOW()` for each scored article

   **Note on `COALESCE(rd.final_routing_tier, rd.routing_tier)`**: `routing_decisions` stores the initial tier in `routing_tier` and the novelty-corrected tier in `final_routing_tier` (set after Stage 2 novelty gate). An article initially classified as DEEP but downgraded to LIGHT by the novelty gate must be excluded from LLM scoring. Using only `routing_tier` would incorrectly score novelty-suppressed articles.

**LLM Prompt**:
```
System: You are a financial news relevance assessor. Rate the market impact of this news article from 0.0 to 1.0.

Scoring scale:
- 1.0: Major market event (CEO change, earnings surprise >20%, acquisition, regulatory ban, recall)
- 0.7-0.9: Significant news (quarterly earnings, analyst target changes, notable contracts, rating changes)
- 0.4-0.6: Moderate news (operational updates, minor partnerships, routine disclosures, sector trends)
- 0.1-0.3: Low impact (routine press releases, background articles, general commentary)
- 0.0: No financial market impact expected

Respond with ONLY valid JSON: {"score": <float 0.0-1.0>, "reason": "<max 10 words>"}

User: Title: {title}
Source: {source_type}
```

**Error handling**:
- Ollama unavailable: skip cycle, log `structlog` warning with `worker=article_relevance_scoring`
- JSON parse failure: skip article, log warning with `article_id`, `raw_response`
- Score out of range: clamp to [0.0, 1.0], log warning
- DB unavailable: exit with code 1 (Docker restart policy handles recovery)

**Config env vars**:

| Variable | Default | Description |
|----------|---------|-------------|
| `RELEVANCE_SCORING_CYCLE_SECONDS` | `1800` | Seconds between scoring cycles |
| `RELEVANCE_SCORING_BATCH_SIZE` | `50` | Articles per cycle |
| `RELEVANCE_SCORING_OLLAMA_URL` | `http://ollama:11434` | Ollama base URL |
| `RELEVANCE_SCORING_MODEL` | `qwen2.5:3b` | Ollama model name |
| `RELEVANCE_SCORING_TIMEOUT_SECONDS` | `30` | Per-article Ollama timeout (30s allows for cold-start model loading) |
| `S6_DISPLAY_WEIGHT_MARKET` | `0.50` | Weight for market_impact in full-signal formula |
| `S6_DISPLAY_WEIGHT_LLM` | `0.40` | Weight for llm_relevance in full-signal formula |
| `S6_DISPLAY_WEIGHT_ROUTING` | `0.10` | Weight for routing_score in full-signal formula (remaining weight distributed proportionally in partial-signal branches) |

---

#### Modified process: `PriceImpactLabellingWorker` (S6, extended)

Extends the worker defined in PRD-0020 to compute **all four daily windows** per article/entity pair instead of a single row.

**Changes**:
1. For each (article, entity) pair, compute windows: day_t0, day_t1, day_t2, day_t5
2. day_t0: available after `published_at + 25h`
3. day_t1: available after `published_at + 49h` (needs T+1 close)
4. day_t2: available after `published_at + 73h`
5. day_t5: available after `published_at + 145h` (5 trading days ≈ 145h including weekends)
6. Writes to `article_impact_windows` table (ON CONFLICT (article_id, entity_id, window_type) DO NOTHING)
7. A single labelling cycle queries articles where `published_at < now() - PRICE_IMPACT_MIN_AGE_HOURS` AND where at least one window is missing from `article_impact_windows`

**OHLCV API calls per article per window**:
- For day_t0: `GET /api/v1/market-data/ohlcv/{symbol}?date={publication_date}`
- For day_t1/t2/t5: `GET /api/v1/market-data/ohlcv/{symbol}?date={publication_date + N_days}`
- Throttled: `asyncio.sleep(0.05)` between calls; batch size 100 articles per cycle

---

### 6.6 Frontend Changes

Frontend changes in this PRD are **types and API client only**. The actual UI components (news tabs, impact badges, instrument news panels) are deferred to the UI PRD (`docs/ui/news-intelligence.md` captures requirements).

#### `apps/frontend/src/lib/gateway-client.ts` additions

```typescript
export interface ImpactWindows {
  day_t0: number | null;
  day_t1: number | null;
  day_t2: number | null;
  day_t5: number | null;
}

export interface RankedArticle {
  article_id: string;
  title: string | null;
  url: string | null;
  published_at: string | null;        // ISO-8601 UTC
  source_type: string | null;
  source_name: string | null;
  routing_tier: string | null;        // "LIGHT" | "MEDIUM" | "DEEP"
  routing_score: number | null;
  market_impact_score: number | null; // null if no windows yet
  llm_relevance_score: number | null; // null for LIGHT tier or unscored
  display_relevance_score: number;    // always present, 0.0-1.0
  primary_entity_id: string | null;   // top entity (global feed only)
  primary_entity_symbol: string | null; // top entity ticker (global feed only)
  impact_windows: ImpactWindows | null; // per-window scores
}

export interface RankedNewsResponse {
  articles: RankedArticle[];
  total: number;
}

export interface TopNewsParams {
  hours?: number;         // 1-168, default 24
  limit?: number;         // 1-100, default 20
  offset?: number;        // default 0
  min_display_score?: number; // 0.0-1.0
  routing_tier?: 'LIGHT' | 'MEDIUM' | 'DEEP';
}

export interface EntityNewsParams {
  start_date?: string;    // ISO-8601 UTC
  end_date?: string;      // ISO-8601 UTC
  order_by?: 'display_relevance_score' | 'published_at';
  limit?: number;
  offset?: number;
}
```

New methods on `gateway` object:

```typescript
getTopNews: (params?: TopNewsParams) =>
  request<RankedNewsResponse>(`/v1/news/top?${buildQuery(params)}`),

getEntityNews: (entityId: string, params?: EntityNewsParams) =>
  request<RankedNewsResponse>(`/v1/news/entity/${entityId}?${buildQuery(params)}`),
```

---

### 6.7 Data Flows

#### Flow A: Price Impact Window Labelling (background, every 4h)

```
[PriceImpactLabellingWorker] (every 4h)

Phase 1 — Read (release session before HTTP calls — R24):
  → Query nlp_db:
      SELECT DISTINCT em.doc_id, em.resolved_entity_id, em.mention_text AS symbol,
             dsm.published_at
      FROM entity_mentions em
      JOIN document_source_metadata dsm ON dsm.doc_id = em.doc_id
      WHERE em.resolved_entity_id IS NOT NULL
        AND em.mention_class = 'financial_instrument'
        AND dsm.published_at IS NOT NULL
        -- For each window type, include if due AND not yet computed:
        AND EXISTS (
          SELECT 1 FROM (VALUES
            ('day_t0', 25), ('day_t1', 49), ('day_t2', 73), ('day_t5', 145)
          ) AS w(window_type, min_hours)
          WHERE dsm.published_at < now() - make_interval(hours => w.min_hours)
            AND NOT EXISTS (
              SELECT 1 FROM article_impact_windows aiw
              WHERE aiw.article_id = em.doc_id
                AND aiw.entity_id = em.resolved_entity_id
                AND aiw.window_type = w.window_type
            )
        )
      LIMIT :batch_size
  → Collect [(doc_id, entity_id, symbol, published_at)] — close session

Phase 2 — HTTP (no open DB sessions):
  → For each (article, entity) pair, compute all missing windows:
      day_t0  (available after 25h):
        → bar_date = publication_date (same trading day)
        → GET /api/v1/market-data/ohlcv/{symbol}?start={bar_date}&end={bar_date}
        → price_start = bar.open, price_end = bar.close
        → delta_pct = (close - open) / open * 100

      day_t1  (available after 49h):
        → bar_date = publication_date + 1 trading day
        → GET /api/v1/market-data/ohlcv/{symbol}?start={bar_date}&end={bar_date}
        → price_start = bar.open, price_end = bar.close
        → delta_pct = (close - open) / open * 100

      day_t2  (available after 73h, cumulative from close_t0):
        → FIRST fetch day_t0 bar (or reuse if already fetched in this cycle)
          to get close_t0 = t0_bar.close  ← this is price_start for cumulative windows
        → bar_date_t2 = publication_date + 2 trading days
        → GET /api/v1/market-data/ohlcv/{symbol}?start={bar_date_t2}&end={bar_date_t2}
        → price_start = close_t0, price_end = t2_bar.close
        → delta_pct = (price_end - price_start) / price_start * 100

      day_t5  (available after 145h, cumulative from close_t0):
        → Reuse close_t0 from day_t2 fetch (or fetch day_t0 if not yet done)
        → bar_date_t5 = publication_date + 5 trading days
        → GET /api/v1/market-data/ohlcv/{symbol}?start={bar_date_t5}&end={bar_date_t5}
        → price_start = close_t0, price_end = t5_bar.close
        → delta_pct = (price_end - price_start) / price_start * 100

  → Skip any window where the target bar returns 404 (no OHLCV for that date)
  → Throttle: asyncio.sleep(0.1) between per-symbol HTTP calls (aligns with existing code)

Phase 3 — Write (open new session → batch INSERT → commit → close):
  → For each computed ArticleImpactWindow:
      INSERT article_impact_windows (...) ON CONFLICT (article_id, entity_id, window_type) DO NOTHING
  → Commit session
```

**Cumulative window note**: `day_t2` and `day_t5` measure the price change from the close of the publication day (`close_t0`) to the close of the target day. `price_start = close_t0` must be fetched from the day_t0 bar. If the day_t0 bar is unavailable (404), day_t2 and day_t5 cannot be computed for that article/entity — skip all cumulative windows.

#### Flow B: LLM Relevance Scoring (background, every 30min)

```
[ArticleRelevanceScoringWorker] (every 30min)
  → Query nlp_db: document_source_metadata dsm
      JOIN routing_decisions rd ON rd.doc_id = dsm.doc_id
      WHERE dsm.llm_relevance_score IS NULL
        AND rd.routing_tier IN ('MEDIUM', 'DEEP')
      ORDER BY dsm.published_at DESC
      LIMIT 50
  → For each article:
      → Build prompt: title + source_type
      → POST http://ollama:11434/api/generate (qwen2.5:3b, timeout 10s)
      → Parse JSON response: {"score": 0.X, "reason": "..."}
      → UPDATE document_source_metadata SET llm_relevance_score = score, llm_scored_at = NOW()
```

#### Flow C: Global Top News Query (request/response)

```
[Frontend] GET /api/v1/news/top?hours=24&limit=20
  ↓ S9 proxy → S6 GET /api/v1/news/top
[GetTopNewsUseCase (S6, ReadOnlyUoW)]
  → CTE 1: article_market_impact  (pivot all 4 windows per article)
      SELECT article_id,
             MAX(CASE WHEN window_type='day_t0' THEN impact_score ELSE NULL END) AS day_t0_score,
             MAX(CASE WHEN window_type='day_t1' THEN impact_score ELSE NULL END) AS day_t1_score,
             MAX(CASE WHEN window_type='day_t2' THEN impact_score ELSE NULL END) AS day_t2_score,
             MAX(CASE WHEN window_type='day_t5' THEN impact_score ELSE NULL END) AS day_t5_score,
             GREATEST(
               MAX(CASE WHEN window_type='day_t0' THEN impact_score ELSE NULL END),
               MAX(CASE WHEN window_type='day_t1' THEN impact_score ELSE NULL END)
             ) AS market_impact_score,  -- MAX(day_t0, day_t1) for display formula
      FROM article_impact_windows GROUP BY article_id

  → CTE 2: article_primary_entity  (entity with highest day_t0 impact per article)
      -- Uses DISTINCT ON to avoid invalid aggregate-in-FILTER syntax
      SELECT DISTINCT ON (article_id)
             article_id, entity_id AS primary_entity_id, symbol AS primary_entity_symbol
      FROM article_impact_windows
      WHERE window_type = 'day_t0'
      ORDER BY article_id, impact_score DESC NULLS LAST

  → Main query:
      WITH counts AS (
        SELECT dsm.doc_id, COUNT(*) OVER() AS total_count,
               ami.day_t0_score, ami.day_t1_score, ami.day_t2_score, ami.day_t5_score,
               ami.market_impact_score,
               rd.composite_score AS routing_score,
               COALESCE(rd.final_routing_tier, rd.routing_tier) AS effective_tier,
               -- display_relevance_score CASE mirrors DisplayRelevanceScore.value:
               CASE
                 WHEN ami.market_impact_score > 0 AND dsm.llm_relevance_score IS NOT NULL
                   THEN 0.50 * ami.market_impact_score + 0.40 * dsm.llm_relevance_score
                        + 0.10 * COALESCE(rd.composite_score, 0.0)
                 WHEN ami.market_impact_score > 0
                   THEN 0.70 * ami.market_impact_score
                        + 0.30 * COALESCE(rd.composite_score, 0.0)
                 WHEN dsm.llm_relevance_score IS NOT NULL
                   THEN 0.60 * dsm.llm_relevance_score
                        + 0.40 * COALESCE(rd.composite_score, 0.0)
                 ELSE COALESCE(rd.composite_score, 0.0) * 0.40
               END AS display_relevance_score
        FROM document_source_metadata dsm
        LEFT JOIN article_market_impact ami ON ami.article_id = dsm.doc_id
        LEFT JOIN routing_decisions rd ON rd.doc_id = dsm.doc_id
        WHERE dsm.published_at >= now() - :hours * interval '1 hour'
          AND (:routing_tier IS NULL OR COALESCE(rd.final_routing_tier, rd.routing_tier) = :routing_tier)
      )
      SELECT c.*, ape.primary_entity_id, ape.primary_entity_symbol
      FROM counts c
      LEFT JOIN article_primary_entity ape ON ape.article_id = c.doc_id
      WHERE (:min_display_score IS NULL OR c.display_relevance_score >= :min_display_score)
      ORDER BY display_relevance_score DESC, published_at DESC
      LIMIT :limit OFFSET :offset

  → Assemble RankedArticle list (impact_windows from day_t0..day_t5 fields)
  → Return {articles, total: total_count}
```

#### Flow D: Entity News Query (request/response)

```
[Frontend] GET /api/v1/news/entity/{entity_id}?start_date=...&end_date=...&limit=20
  ↓ S9 proxy path rewrite → S6 GET /api/v1/entities/{entity_id}/articles
[GetEntityArticlesUseCase (S6, ReadOnlyUoW)]

  → CTE 1: entity_article_ids
      SELECT DISTINCT em.doc_id AS article_id
      FROM entity_mentions em
      WHERE em.resolved_entity_id = :entity_id

  → CTE 2: article_windows  (identical pivot to Flow C — all 4 window types)
      SELECT article_id,
             MAX(CASE WHEN window_type='day_t0' THEN impact_score ELSE NULL END) AS day_t0_score,
             MAX(CASE WHEN window_type='day_t1' THEN impact_score ELSE NULL END) AS day_t1_score,
             MAX(CASE WHEN window_type='day_t2' THEN impact_score ELSE NULL END) AS day_t2_score,
             MAX(CASE WHEN window_type='day_t5' THEN impact_score ELSE NULL END) AS day_t5_score,
             GREATEST(
               MAX(CASE WHEN window_type='day_t0' THEN impact_score ELSE NULL END),
               MAX(CASE WHEN window_type='day_t1' THEN impact_score ELSE NULL END)
             ) AS market_impact_score
      FROM article_impact_windows
      WHERE article_id IN (SELECT article_id FROM entity_article_ids)
      GROUP BY article_id

  → Main query:
      SELECT dsm.doc_id, dsm.title, dsm.url, dsm.published_at, dsm.source_type, dsm.source_name,
             dsm.llm_relevance_score,
             rd.composite_score AS routing_score,
             COALESCE(rd.final_routing_tier, rd.routing_tier) AS effective_tier,
             aw.day_t0_score, aw.day_t1_score, aw.day_t2_score, aw.day_t5_score,
             aw.market_impact_score,
             -- same CASE formula as Flow C:
             CASE
               WHEN aw.market_impact_score > 0 AND dsm.llm_relevance_score IS NOT NULL
                 THEN 0.50 * aw.market_impact_score + 0.40 * dsm.llm_relevance_score
                      + 0.10 * COALESCE(rd.composite_score, 0.0)
               WHEN aw.market_impact_score > 0
                 THEN 0.70 * aw.market_impact_score + 0.30 * COALESCE(rd.composite_score, 0.0)
               WHEN dsm.llm_relevance_score IS NOT NULL
                 THEN 0.60 * dsm.llm_relevance_score + 0.40 * COALESCE(rd.composite_score, 0.0)
               ELSE COALESCE(rd.composite_score, 0.0) * 0.40
             END AS display_relevance_score,
             COUNT(*) OVER() AS total_count
      FROM entity_article_ids ea
      JOIN document_source_metadata dsm ON dsm.doc_id = ea.article_id
      LEFT JOIN article_windows aw ON aw.article_id = ea.article_id
      LEFT JOIN routing_decisions rd ON rd.doc_id = ea.article_id
      WHERE dsm.published_at BETWEEN :start_date AND :end_date
      ORDER BY
        CASE WHEN :order_by = 'published_at' THEN dsm.published_at END DESC,
        CASE WHEN :order_by != 'published_at' THEN display_relevance_score END DESC
      LIMIT :limit OFFSET :offset

  → Assemble RankedArticle list (no primary_entity_* fields — entity fixed by path param)
  → Return {articles, total: total_count}
```

---

## 7. Architecture Decisions

### AD-1: Multi-window table design — one row per window vs flat columns

**Option A (this PRD)**: One row per (article, entity, window_type) in `article_impact_windows`.
- Pro: Extensible — adding new window types requires no schema change
- Pro: Clean separation — each window is independently queryable and missing-window-aware
- Pro: ML-friendly — each window is a feature row; aggregate per article for training
- Con: More rows (3M vs 500K); queries need GROUP BY or LATERAL join for "best score"

**Option B**: Flat columns — `day_t0_score`, `day_t1_score`, `day_t2_score`, `day_t5_score` in one row.
- Pro: Simpler queries (single JOIN)
- Con: Adding intraday windows requires DDL change
- Con: Null columns for unavailable windows pollute the schema

**Decision**: Option A — extensibility for future intraday windows outweighs query simplicity. The LATERAL join pattern is already established in this codebase.

### AD-2: LLM scoring title-only vs full text

**Option A (this PRD)**: Use `title + source_type` only — no MinIO access.
- Pro: Zero latency penalty for storage retrieval; simpler worker
- Pro: 3B models perform better with concise prompts (< 128 tokens)
- Pro: Article titles in financial news are highly informative ("Apple CEO Tim Cook Steps Down")
- Con: Misses body context for ambiguous titles

**Option B**: Use title + first 400 chars from MinIO silver text.
- Pro: More context for ambiguous cases
- Con: Requires `minio_silver_key` column in `document_source_metadata` (additional migration); MinIO read adds ~50ms latency per article

**Decision**: Option A for v1. If scoring quality is insufficient, Option B can be added in a future wave by simply adding `minio_silver_key` to `document_source_metadata` and updating the worker.

### AD-3: `display_relevance_score` — stored vs computed at query time

**Option A (this PRD)**: Computed at query time via CASE expression in SQL.
- Pro: Always reflects latest signal availability (new LLM/market scores immediately visible)
- Pro: No stale scores; no re-computation needed when scores update
- Con: Slightly more complex query

**Option B**: Store computed score in a denormalised column, updated by triggers or workers.
- Pro: Simpler `ORDER BY score` query
- Con: Stale when component scores update; requires another worker or trigger

**Decision**: Option A — fresh computation at query time. With proper indexes, the CASE expression adds < 1ms. Staleness risk of Option B outweighs the marginal query simplification.

### AD-5: Score discontinuity when market data arrives

**Problem**: An article initially ranked by LLM score alone (`0.60*llm + 0.40*rs`) may score *lower* once its day_t0 market data arrives, if the market impact is small. Example: `llm=0.8, rs=0.5, market=0.05`:
- Before day_t0 arrives: `0.60*0.8 + 0.40*0.5 = 0.68`
- After day_t0 arrives: `0.50*0.05 + 0.40*0.8 + 0.10*0.5 = 0.395` — drops 43%

A high-LLM-scored article could visibly jump from rank 1 to rank 50 when market data confirms "this didn't move markets".

**Option A (this PRD)**: Accept the discontinuity. The market signal is ground truth — an article that the LLM rated highly but that failed to move markets *should* rank lower once we know. This is the system being more accurate, not less.

**Option B**: Add a floor: `score = MAX(new_formula, 0.8 × prev_formula_value)`. Requires storing or re-computing the pre-market score, adding complexity.

**Decision**: Option A — accept the discontinuity. The market signal is the strongest and most factual signal in the system. The 24–49h transition window means the ranking naturally shifts from "LLM-predicted importance" to "market-confirmed importance" as data arrives. This aligns with the thesis goal of demonstrating retrospective ground truth. Document for users: scores for articles < 48h old are LLM-estimated; scores for older articles incorporate market confirmation.

---

### AD-4: `routing_score` denormalization

`routing_decisions.composite_score` already persists the routing score per `doc_id`. Adding a duplicate column to `document_source_metadata` would be denormalization without benefit, since both tables are in `nlp_db` and the JOIN on `doc_id` (with the new index) is < 1ms.

**Decision**: No denormalization. JOIN `routing_decisions` at query time.

---

## 8. Security Analysis

| Threat | Mitigation |
|--------|-----------|
| SQL injection via `entity_id` path param | UUID validation at FastAPI router level; malformed UUIDs return 422 before reaching use case |
| Prompt injection via article title | LLM prompt is a SYSTEM instruction with fixed format; user-controlled input (title) is in USER section only; response validated as JSON with clamped float |
| LLM response poisoning (adversarial titles crafted to score 1.0) | Score is informational only; does not trigger any action (no alert threshold, no billing); impact bounded to article ranking position |
| Cross-tenant data leakage | Endpoints are read-only queries on `nlp_db`; no `tenant_id` filtering needed since `document_source_metadata` and `article_impact_windows` contain no PII and are public intelligence data |
| SSRF via Ollama URL config | `RELEVANCE_SCORING_OLLAMA_URL` is a server-side env var, not user-controlled |
| Rate limiting bypass | S9 enforces 100 req/min per authenticated user (OIDC JWT); S6 does not need its own rate limiting for these read endpoints |

---

## 9. Failure Modes

| Failure | Detection | Recovery |
|---------|-----------|---------|
| Ollama unavailable | `httpx.ConnectError` in scoring worker | Skip cycle, log warning. Articles remain unscored until next cycle; display falls back to routing_score |
| Ollama returns malformed JSON | `json.JSONDecodeError` | Skip article, log with `article_id` + `raw_response`. Retry next cycle |
| S3 OHLCV API unavailable (labelling) | `httpx.RequestError` | Skip article/window, log warning. Retry next 4h cycle; no data loss |
| Missing OHLCV for symbol or date | S3 returns 404 | Skip window for that article (no row inserted). Article may have fewer than 4 windows |
| `nlp_db` unavailable | Worker startup fails | Exit code 1; Docker restart policy recovers |
| article_impact_windows table missing after migration | IntegrityError on first INSERT | Alembic migration guards this; migration must succeed before workers start |
| `routing_decisions` has no row for a `doc_id` | LEFT JOIN returns NULL composite_score | DisplayRelevanceScore.value treats `routing_score=None` as 0.0; article still ranks on other signals |
| LLM returns score > 1.0 or < 0.0 | value out of domain | Clamp: `max(0.0, min(1.0, score))`. Log warning with `article_id`, `raw_score` |

---

## 10. Scalability

| Concern | Estimate | Mitigation |
|---------|----------|-----------|
| `article_impact_windows` growth | ~3M rows total; ~20K new rows/day (5K articles × 4 windows) | No partitioning needed at thesis scale; UNIQUE index prevents duplicates |
| Top news query on 500K `document_source_metadata` rows | Without index: full scan ~500ms. With `(published_at DESC)` index: ~5ms for 24h window | New index added in this PRD |
| LLM scoring backlog at deployment | ~50 articles/cycle × every 30min = 2,400/day. ~500K existing MEDIUM/DEEP articles = ~200 days to score all. Acceptable — fresh articles are prioritised (ORDER BY published_at DESC) | Worker already ordered by recency |
| Ollama single-threaded inference | Qwen2.5:3b on CPU ≈ 1s/call; 50 articles = ~50s per cycle. Well within 30min cycle | Acceptable; increase batch size if needed |
| OHLCV labelling backlog at deployment | 4 windows × 500K articles × N calls each = 2M+ calls. Throttled at 10 calls/s (asyncio.sleep(0.1) between calls — aligned with existing code) ≈ ~56 hours for full backfill. Note: day_t2/t5 require an extra day_t0 call per article if not cached | One-time; normal operation is ~20K rows/day |

---

## 11. Test Strategy

### Unit Tests (S6)

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_article_impact_window_compute_day_t0` | `delta_pct = (close-open)/open*100`; `impact_score = min(1.0, abs(delta_pct)/5.0)` | HIGH |
| `test_article_impact_window_impact_score_capped` | 10% delta with 5.0 cap → `impact_score = 1.0` | HIGH |
| `test_article_impact_window_negative_delta` | `-3% delta → impact_score = 0.6` (abs value used) | HIGH |
| `test_article_impact_window_window_end_after_start` | `window_end <= window_start` raises `ValueError` | HIGH |
| `test_display_relevance_score_all_signals` | market=0.8, llm=0.6, routing=0.5 → `0.5*0.8+0.4*0.6+0.1*0.5=0.69` | HIGH |
| `test_display_relevance_score_market_only` | market=0.8, llm=None, routing=0.5 → `0.7*0.8+0.3*0.5=0.71` | HIGH |
| `test_display_relevance_score_llm_only` | market=0.0, llm=0.7, routing=0.4 → `0.6*0.7+0.4*0.4=0.58` | HIGH |
| `test_display_relevance_score_routing_only` | market=0.0, llm=None, routing=0.6 → `0.6*0.4=0.24` | HIGH |
| `test_display_relevance_score_no_signals` | all None/0.0 → `0.0` | HIGH |
| `test_labelling_worker_computes_all_four_windows` | Article aged 200h → all 4 windows created | HIGH |
| `test_labelling_worker_defers_day_t1_if_too_soon` | Article aged 30h → only day_t0 created | HIGH |
| `test_labelling_worker_idempotent_multi_window` | Run twice → no duplicate rows (ON CONFLICT) | HIGH |
| `test_relevance_worker_parses_valid_json` | `{"score": 0.75, "reason": "CEO change"}` → `llm_relevance_score = 0.75` | HIGH |
| `test_relevance_worker_clamps_out_of_range_score` | `{"score": 1.5}` → clamped to `1.0` | HIGH |
| `test_relevance_worker_skips_on_json_error` | `"not json"` → article skipped, no DB update | HIGH |
| `test_relevance_worker_skips_light_tier` | LIGHT tier article not in query results | HIGH |
| `test_window_type_enum_reserved_values` | `intraday_1h` and `intraday_4h` in WindowType without raising | MEDIUM |
| `test_display_relevance_score_zero_market_vs_none` | `market=0.0` (labeled zero) falls through to LLM-only branch (not treated as "not available") | HIGH |
| `test_labelling_worker_cumulative_window_uses_t0_close` | day_t2 `price_start = close_t0` (not open_t2); uses t0 bar for baseline | HIGH |
| `test_labelling_worker_skips_cumulative_if_t0_unavailable` | day_t0 returns 404 → day_t2 and day_t5 also skipped | HIGH |
| `test_relevance_worker_uses_effective_routing_tier` | Article with `routing_tier='DEEP', final_routing_tier='LIGHT'` excluded from scoring | HIGH |
| `test_relevance_worker_r24_no_session_during_ollama` | Worker releases DB session before HTTP calls (verify via session factory mock) | HIGH |
| `test_migration_excludes_zero_sentinel_rows` | `price_open=0` rows NOT migrated to article_impact_windows | HIGH |

### Integration Tests (S6)

| Test | Infrastructure | What It Verifies |
|------|---------------|-----------------|
| `test_top_news_endpoint_returns_ranked_articles` | Postgres | `GET /api/v1/news/top` returns articles in `display_relevance_score DESC` order |
| `test_top_news_endpoint_time_window_filter` | Postgres | Articles outside `hours` window excluded |
| `test_top_news_endpoint_min_display_score_filter` | Postgres | Articles below threshold excluded |
| `test_top_news_endpoint_pagination` | Postgres | `total` reflects full count; `offset` correctly pages |
| `test_entity_articles_endpoint_date_range` | Postgres | `start_date`/`end_date` params filter correctly |
| `test_entity_articles_endpoint_order_by_published_at` | Postgres | `order_by=published_at` returns newest first |
| `test_entity_articles_endpoint_unresolved_entity` | Postgres | Unknown `entity_id` → empty `articles`, `total=0` |
| `test_labelling_worker_end_to_end_all_windows` | Postgres + wiremock (S3) | Worker computes day_t0/t1/t2/t5 for aged article |
| `test_relevance_scoring_worker_updates_score` | Postgres + Ollama mock | Worker updates `llm_relevance_score` in `document_source_metadata` |
| `test_migration_article_price_impacts_to_windows` | Postgres | Alembic migration correctly migrates existing rows |

### Contract Tests

| Test | What It Verifies |
|------|-----------------|
| `test_article_impact_windows_unique_constraint` | Duplicate (article_id, entity_id, window_type) raises `IntegrityError` |
| `test_display_relevance_score_formula_consistency` | Python `DisplayRelevanceScore.value` matches SQL CASE expression output for all signal combinations |

---

## 12. Migration Plan

### Step 1: Alembic — `nlp_db` schema changes (S6)

One new Alembic revision with the following operations in order:

```sql
-- 1. Create article_impact_windows
CREATE TABLE article_impact_windows (...);

-- 2. Migrate data from article_price_impacts (day_t0 rows only)
--    WHERE price_open > 0 excludes zero-sentinel rows (ArticlePriceImpact.zero())
INSERT INTO article_impact_windows (
  id, article_id, entity_id, symbol, published_at,
  window_type, window_start, window_end,
  price_start, price_end, delta_pct, high_pct, low_pct, volume,
  impact_score, normalisation_cap_pct, data_quality, computed_at
)
SELECT
  gen_random_uuid(),
  article_id, entity_id, symbol, published_at,
  'day_t0',
  DATE_TRUNC('day', published_at)::TIMESTAMPTZ,
  DATE_TRUNC('day', published_at)::TIMESTAMPTZ + INTERVAL '1 day',
  price_open, price_close, price_delta_pct, max_intraday_range_pct, NULL, NULL,
  impact_score, 5.0, 'daily_proxy', computed_at
FROM article_price_impacts
WHERE price_open > 0;  -- skip zero-sentinel rows (ArticlePriceImpact.zero() has price_open=0)

-- 3. [REMOVED] day_t1 migration is not feasible: article_price_impacts.next_day_delta_pct
--    stores only a percentage delta, not the price_start/price_end required by
--    article_impact_windows. The PriceImpactLabellingWorker will compute day_t1/t2/t5
--    windows forward from deployment using live OHLCV data.

-- 4. Drop old table
DROP TABLE article_price_impacts;

-- 5. Add new columns to document_source_metadata
ALTER TABLE document_source_metadata
  ADD COLUMN llm_relevance_score NUMERIC(6,4),
  ADD COLUMN llm_scored_at TIMESTAMPTZ;

-- 6. New indexes
CREATE INDEX CONCURRENTLY idx_dsm_published_at
  ON document_source_metadata (published_at DESC);
CREATE INDEX CONCURRENTLY idx_routing_decisions_doc_id
  ON routing_decisions (doc_id);
CREATE UNIQUE INDEX idx_article_impact_windows_unique
  ON article_impact_windows (article_id, entity_id, window_type);
  -- UNIQUE required: ON CONFLICT (article_id, entity_id, window_type) DO NOTHING needs a unique constraint
CREATE INDEX idx_article_impact_windows_entity
  ON article_impact_windows (entity_id, window_type, published_at DESC);
CREATE INDEX idx_article_impact_windows_day_t0_score
  ON article_impact_windows (impact_score DESC)
  WHERE window_type = 'day_t0';
```

### Step 2: Code — Update `PriceImpactLabellingWorker`

- Extend to compute day_t1/t2/t5 windows
- Switch from writing to `article_price_impacts` → `article_impact_windows`
- Update `ArticlePriceImpactRepository` → new `ArticleImpactWindowRepository`

### Step 3: Code — New `ArticleRelevanceScoringWorker`

- New process with config vars
- Update docker-compose.yml to add new process entry for S6
- Update `services/nlp-pipeline/src/nlp_pipeline/app.py` or worker entrypoints

### Step 4: Code — New S6 endpoints

- `GetTopNewsUseCase` (new)
- `GetEntityArticlesUseCase` (modify existing)
- New router: `api/routes/news.py` with `GET /api/v1/news/top`
- Modify `api/routes/signals.py` to use enhanced entity articles use case

### Step 5: S9 — New proxy routes

- Add `GET /api/v1/news/top` → S6 in `services/api-gateway/`
- Add `GET /api/v1/news/entity/{entity_id}` → S6 `/entities/{entity_id}/articles`

### Step 6: Frontend — Types + API client

- Add types to `gateway-client.ts`
- Add `getTopNews()` and `getEntityNews()` methods

### Step 7: Update `nlp.signal.detected.v1` producer

- S6's signal emission currently reads from `article_price_impacts`. Must update to read from `article_impact_windows WHERE window_type = 'day_t0'` for the `market_impact_score` field.

### Deployment order

1. Run Alembic migration (creates new table, migrates data, drops old table)
2. Deploy S6 (new workers + endpoints + updated signal emission)
3. Deploy S9 (new proxy routes)
4. Deploy frontend (new types — no visible UI change until UI PRD)

---

## 13. Observability

| Metric | Labels | Description |
|--------|--------|-------------|
| `s6_impact_windows_computed_total` | `window_type`, `status={success,no_ohlcv,error}` | Windows computed per labelling cycle |
| `s6_impact_labelling_cycle_duration_seconds` | — | Duration of each 4h labelling cycle |
| `s6_llm_relevance_scored_total` | `status={success,parse_error,timeout,skip}` | LLM scoring results per cycle |
| `s6_llm_relevance_cycle_duration_seconds` | — | Duration of each 30min scoring cycle |
| `s6_llm_relevance_score_histogram` | — | Distribution of `llm_relevance_score` values (detect model drift) |
| `s6_display_relevance_score_histogram` | `signal_combo={all,market_only,llm_only,routing_only}` | Coverage of scoring signals |
| `s6_top_news_query_duration_seconds` | — | `GET /api/v1/news/top` query time |
| `s6_entity_articles_query_duration_seconds` | — | `GET /api/v1/entities/{entity_id}/articles` query time |

### Log fields

- LLM worker: `service=nlp-pipeline`, `worker=article_relevance_scoring`, `article_id`, `llm_score`, `raw_reason` (first 50 chars)
- Labelling worker: `service=nlp-pipeline`, `worker=price_impact_labelling`, `article_id`, `entity_id`, `window_type`, `impact_score`, `delta_pct`

---

## 14. Open Questions

| ID | Question | Classification | Resolution |
|----|----------|---------------|------------|
| OQ-001 | LLM model quality: is Qwen2.5:3b sufficiently accurate for financial relevance scoring? Consider benchmarking on 50 known-impact articles before v1 launch. | DEFERRED | Verify during testing; fallback = routing_score if quality is poor |
| OQ-002 | `display_relevance_score` weights (0.5/0.4/0.1, 0.7/0.3, etc.) — are these the right values? | DEFERRED | Confirmed as reasonable starting point; can be tuned via config vars in future |
| OQ-003 | Should the LLM worker backfill historical articles (100K+ MEDIUM/DEEP articles)? | DEFERRED | No for v1; worker runs forward from deployment; historical backfill is a manual operational task |
| OQ-004 | UI: impact badge display style (SeverityBadge reuse vs new ImpactBar component) | DEFERRED | Captured in `docs/ui/news-intelligence.md`; resolved when UI PRD is written |
| OQ-005 | UI: default time window for "Top News" tab (24h vs 48h) | DEFERRED | Captured in `docs/ui/news-intelligence.md` |
| OQ-006 | Should `display_relevance_score` weights be configurable via env vars? | **RESOLVED** | Yes — `S6_DISPLAY_WEIGHT_MARKET` (0.50), `S6_DISPLAY_WEIGHT_LLM` (0.40), `S6_DISPLAY_WEIGHT_ROUTING` (0.10) added to §6.5 worker config table. These apply to the full-signal branch; partial-signal branches scale proportionally. Add to `pydantic-settings` class for S6. |

---

## 15. Effort Estimation

| Area | Waves | Complexity |
|------|-------|-----------|
| Alembic migration (`article_impact_windows` + `document_source_metadata` additions + indexes) | 1 wave | Medium |
| Enhanced `PriceImpactLabellingWorker` (multi-window) + updated repository | 1 wave | Medium |
| New `ArticleRelevanceScoringWorker` + Ollama client + config | 1 wave | Medium |
| New `GetTopNewsUseCase` + `GET /api/v1/news/top` router | 1 wave | Medium |
| Enhanced `GetEntityArticlesUseCase` + updated router | 0.5 wave | Low-Medium |
| S9 proxy routes (2 routes) | 0.5 wave | Low |
| Update `nlp.signal.detected.v1` producer (read from new table) | 0.5 wave | Low |
| Frontend types + API client methods | 0.5 wave | Low |
| Tests + docs | 1 wave | Medium |
| **Total** | **~7 waves** | — |
