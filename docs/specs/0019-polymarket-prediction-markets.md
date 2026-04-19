# PRD-0019 — Polymarket Prediction Markets Integration + EDGAR Market-Hours Polling

> **Status**: Draft — 2026-04-06
> **Author**: Arnau Rodon
> **Services affected**: S4 (Content Ingestion), S3 (Market Data), S9 (API Gateway), Frontend
> **Depends on**: PLAN-0015 (S8 infrastructure complete)
> **Plan**: PLAN-0019 (to be generated)

---

## 1. Problem Statement

Worldview's J4 (Signals/Events View) currently surfaces only news articles and NLP-derived signals. It lacks any view into market consensus on macro events, geopolitical outcomes, or company-specific probabilities. Prediction markets (real-money probabilistic bets) are unique alternative data: they aggregate the wisdom of incentivised participants and frequently lead traditional news by hours.

ZeroTerminal competitive research (2026-04-06) identified Polymarket as a high-value, zero-cost data source that is absent from Bloomberg Terminal and Refinitiv Eikon alike.

Separately, the SEC EDGAR adapter in S4 currently polls every 30 minutes regardless of time-of-day, introducing unnecessary lag during live market hours (09:30–16:00 ET). ZeroTerminal achieves a 2m 34s filing-to-alert lag by polling at 10-second intervals during market hours. We can close most of this gap with a scheduler-aware polling interval at negligible cost.

---

## 2. Target Users

| User | Workflow | Benefit |
|------|----------|---------|
| **Research Analysts** (J4) | Monitor event-driven signals across sources | See real-money probability alongside news context |
| **Retail Investors** (J4, J5) | Understand macro uncertainty | "What's the market probability of a rate cut?" answered with cited Polymarket data |
| **Quantitative Traders** (J1, API) | Alternative data signals | Probability time-series as input to models |
| **Thesis Evaluators** | Assess system breadth | Novel alternative data source demonstrates ingestion pipeline extensibility |

---

## 3. Functional Requirements

### 3.1 Polymarket Prediction Markets

| ID | Requirement | Priority |
|----|-------------|----------|
| F-01 | S4 polls Polymarket Gamma API every 5 minutes and produces market snapshots to `market.prediction.v1` | MUST |
| F-02 | S3 consumes `market.prediction.v1` and materialises prediction markets into `market_data_db` | MUST |
| F-03 | S3 maintains a full snapshot history (TimescaleDB hypertable) for probability time-series | MUST |
| F-04 | S3 exposes `GET /api/v1/prediction-markets` (list with filters) | MUST |
| F-05 | S3 exposes `GET /api/v1/prediction-markets/{market_id}` (detail + current prices) | MUST |
| F-06 | S3 exposes `GET /api/v1/prediction-markets/{market_id}/history` (time-series, paginated) | MUST |
| F-07 | S9 proxies all three S3 prediction-market endpoints with JWT auth | MUST |
| F-08 | Frontend J4 Signals view shows a "Prediction Markets" panel with live probability bars | MUST |
| F-09 | S4 deduplicates market snapshots by `(market_id, snapshot_at)` to avoid re-processing identical data | MUST |
| F-10 | Only `resolution_status = open` markets are polled continuously; resolved/cancelled markets are archived | SHOULD |
| F-11 | S4 stores raw Polymarket response verbatim in MinIO bronze layer | SHOULD |

### 3.2 EDGAR Market-Hours Polling Optimisation

| ID | Requirement | Priority |
|----|-------------|----------|
| F-12 | S4's SEC EDGAR adapter uses a 60-second polling interval during US market hours (09:30–16:00 ET, Monday–Friday) and a 30-minute interval otherwise | MUST |
| F-13 | Market-hours detection logic is configurable via env vars (`SEC_EDGAR_MARKET_HOURS_INTERVAL_SECONDS`, `SEC_EDGAR_OFF_HOURS_INTERVAL_SECONDS`) | SHOULD |
| F-14 | Market-hours detection is timezone-aware and DST-safe (use `zoneinfo.ZoneInfo("America/New_York")`) | MUST |

---

## 4. Non-Functional Requirements

| Attribute | Target |
|-----------|--------|
| Latency | S4 → Kafka < 10s after Polymarket Gamma API response; S3 materialisation < 5s after Kafka consume |
| Polling freshness | Prediction markets: 5-min staleness max; EDGAR (market hours): 60s; EDGAR (off-hours): 30min |
| Throughput | Polymarket: ~2,000 active markets × 1 snapshot/5min = 400 events/min (well within Kafka budget) |
| Cost | Polymarket Gamma API: free, no auth, 4,000 req/10s rate limit — trivially satisfied |
| Idempotency | Re-consuming the same `market.prediction.v1` event must produce identical DB state (UPSERT) |
| Observability | Metrics for poll success/failure, Kafka event count, S3 materialisation lag |
| Security | Polymarket requires no credentials; no secrets required for this integration |

---

## 5. Out of Scope

- **Kalshi** integration (deferred to PRD-0023)
- **Polymarket trading** (placing orders, filling markets) — read-only data access only
- **WebSocket Polymarket stream** — polling is sufficient for thesis; WebSocket adds complexity with minimal benefit
- **Entity linking** of prediction market questions to canonical KG entities — deferred to a future PRD (no current plan covers entity linking)
- **Alert generation** from prediction market probability moves — deferred to PRD-0021 (needs AlertSeverity first)
- **Frontend charting** of probability time-series — deferred; J4 panel shows current prices only in v1

---

## 6. Technical Design

### 6.1 Affected Services

| Service | Change Type | Summary |
|---------|-------------|---------|
| **S4 Content Ingestion** | New adapter + EDGAR scheduler fix | `PolymarketAdapter`, `PredictionMarketFetchResult`, new outbox topic, EDGAR interval logic |
| **S3 Market Data** | New consumer + DB tables + API endpoints | `PredictionMarketConsumer`, 2 new TimescaleDB tables, 3 new API routes |
| **S9 API Gateway** | New proxy routes | 3 prediction-market endpoints proxied to S3 |
| **Frontend** | New J4 panel component | `PredictionMarketsPanel` in Signals view |
| **Kafka / Avro** | New topic + schema | `market.prediction.v1` with `PredictionMarketSnapshot.avsc` |

---

### 6.2 API Changes

#### GET /api/v1/prediction-markets (S3)

- **Purpose**: List active prediction markets with current prices; supports filtering and pagination
- **Auth**: internal-only (S9 proxies this with JWT auth on the gateway side)
- **Query parameters**:

| Param | Type | Required | Default | Validation | Description |
|-------|------|----------|---------|------------|-------------|
| `status` | string | no | `open` | enum: `open`, `resolved`, `cancelled`, `all` | Filter by resolution status |
| `query` | string | no | — | max 200 chars, strip HTML | Full-text substring match on `question` |
| `limit` | int | no | `50` | 1–200 | Max items per page |
| `offset` | int | no | `0` | ≥0 | Skip N items |

- **Response** (200):

| Field | Type | Description |
|-------|------|-------------|
| `items` | `PredictionMarketSummary[]` | List of markets |
| `total` | int | Total matching markets |
| `limit` | int | Applied limit |
| `offset` | int | Applied offset |

`PredictionMarketSummary` fields:

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `market_id` | string | no | Polymarket condition_id |
| `question` | string | no | Market question text |
| `outcomes` | `OutcomePrice[]` | no | Current prices per outcome |
| `volume_24h` | float | yes | 24h trading volume (USD) |
| `close_time` | datetime (ISO-8601 UTC) | yes | Scheduled resolution time |
| `resolution_status` | string | no | `open` / `resolved` / `cancelled` |
| `resolved_answer` | string | yes | Winning outcome if resolved |
| `updated_at` | datetime | no | Last snapshot time |

`OutcomePrice` fields:

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `name` | string | no | Outcome label (e.g. "Yes", "No") |
| `token_id` | string | no | Polymarket CLOB token ID |
| `price` | float | no | Current probability (0.0–1.0) |

- **Error responses**: 422 (invalid query params)
- **Rate limit**: S9 applies 100 req/min per user

---

#### GET /api/v1/prediction-markets/{market_id} (S3)

- **Purpose**: Full detail for a single prediction market including current prices
- **Auth**: internal-only
- **Path params**:

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `market_id` | string | yes | Polymarket condition_id (URL-encoded) |

- **Response** (200): `PredictionMarketDetail` — all fields from `PredictionMarketSummary` plus:

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `description` | string | yes | Full market description from Polymarket |
| `created_at` | datetime | no | First seen in worldview |

> **Note**: `updated_at` (from `PredictionMarketSummary`) serves as the latest-snapshot timestamp — the consumer always sets it on each snapshot upsert. No separate `latest_snapshot_at` field is needed.

- **Error responses**: 404 (market_id not found)

---

#### GET /api/v1/prediction-markets/{market_id}/history (S3)

- **Purpose**: Time-series of probability snapshots for a market
- **Auth**: internal-only
- **Path params**: `market_id` (string, required)
- **Query parameters**:

| Param | Type | Required | Default | Validation | Description |
|-------|------|----------|---------|------------|-------------|
| `from` | datetime | no | 7 days ago | ISO-8601 UTC | Start of time range |
| `to` | datetime | no | now | ISO-8601 UTC | End of time range |
| `limit` | int | no | `500` | 1–2000 | Max snapshots |

- **Response** (200):

| Field | Type | Description |
|-------|------|-------------|
| `market_id` | string | Polymarket condition_id |
| `snapshots` | `SnapshotPoint[]` | Time-ordered probability snapshots |

`SnapshotPoint` fields:

| Field | Type | Description |
|-------|------|-------------|
| `snapshot_at` | datetime | UTC snapshot timestamp |
| `outcomes_prices` | object | `{ outcome_name: price, ... }` (e.g. `{"Yes": 0.72, "No": 0.28}`) |
| `volume_24h` | float \| null | Volume at snapshot time |

- **Error responses**: 404 (market_id not found), 400 (from > to), 422 (bad params)

---

#### S9 Gateway proxy routes (new)

| Method | Gateway Path | Proxied To |
|--------|-------------|-----------|
| GET | `/v1/signals/prediction-markets` | `S3 GET /api/v1/prediction-markets` |
| GET | `/v1/signals/prediction-markets/{market_id}` | `S3 GET /api/v1/prediction-markets/{market_id}` |
| GET | `/v1/signals/prediction-markets/{market_id}/history` | `S3 GET /api/v1/prediction-markets/{market_id}/history` |

All three: JWT auth required, 100 req/min per user, tenant isolation via `X-Tenant-ID` header forwarded to S3.

---

### 6.3 Event Changes

#### market.prediction.v1

- **Topic**: `market.prediction.v1`
- **Partition key**: `market_id` (ensures all snapshots for a market land on the same partition, preserving order)
- **Retention**: 30 days
- **Producers**: S4 (PolymarketAdapter via outbox)
- **Consumers**: S3 (PredictionMarketConsumer)
- **Avro schema** (`PredictionMarketSnapshot.avsc`):

| Field | Type | Default | Nullable | Description |
|-------|------|---------|----------|-------------|
| `event_id` | string | — | no | UUIDv7 event identifier |
| `event_type` | string | `"market.prediction.snapshot"` | no | Fixed event type |
| `schema_version` | int | `1` | no | Schema version |
| `occurred_at` | string | — | no | ISO-8601 UTC timestamp of snapshot |
| `market_id` | string | — | no | Polymarket condition_id |
| `source` | string | `"polymarket"` | no | Data source identifier |
| `question` | string | — | no | Market question text (max 2000 chars) |
| `description` | string | `""` | yes | Full market description |
| `outcomes` | array[OutcomeRecord] | `[]` | no | Outcomes with current prices |
| `volume_24h` | double | `null` | yes | 24h USDC trading volume |
| `liquidity` | double | `0.0` | yes | Current liquidity pool size |
| `close_time` | string | `null` | yes | ISO-8601 UTC scheduled close |
| `resolution_status` | string | `"open"` | no | `open` / `resolved` / `cancelled` |
| `resolved_answer` | string | `null` | yes | Winning outcome name if resolved |
| `minio_bronze_key` | string | `null` | yes | MinIO key for raw response |
| `correlation_id` | string | `null` | yes | Trace correlation ID |

`OutcomeRecord` nested type:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Outcome label ("Yes", "No", etc.) |
| `token_id` | string | Polymarket ERC-1155 token ID |
| `price` | double | Current probability price (0.0–1.0) |

---

### 6.4 Database Changes

#### New table: `prediction_markets` (`market_data_db`, owned by S3)

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `id` | UUID | no | `new_uuid7()` | PK | |
| `market_id` | TEXT | no | — | UNIQUE NOT NULL | Polymarket condition_id |
| `source` | TEXT | no | `'polymarket'` | NOT NULL | Data origin |
| `question` | TEXT | no | — | NOT NULL | Market question text |
| `description` | TEXT | yes | `null` | — | Full description |
| `outcomes` | JSONB | no | — | NOT NULL | `[{"name": str, "token_id": str}]` — outcome definitions (no prices) |
| `close_time` | TIMESTAMPTZ | yes | `null` | — | Scheduled resolution |
| `resolution_status` | VARCHAR(20) | no | `'open'` | NOT NULL | `open` / `resolved` / `cancelled` |
| `resolved_answer` | TEXT | yes | `null` | — | Winning outcome if resolved |
| `created_at` | TIMESTAMPTZ | no | `now()` | NOT NULL | First ingested |
| `updated_at` | TIMESTAMPTZ | no | `now()` | NOT NULL | Last metadata update |

- **Indexes**: `(market_id) UNIQUE`, `(resolution_status, updated_at DESC)` for active market list
- **Partitioning**: none (low cardinality — ~5,000 active markets total)
- **Estimated rows**: ~5,000 total

---

#### New table: `prediction_market_snapshots` (`market_data_db`, TimescaleDB hypertable)

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `id` | UUID | no | `new_uuid7()` | PK | |
| `market_id` | TEXT | no | — | NOT NULL | Logical FK to `prediction_markets.market_id` |
| `snapshot_at` | TIMESTAMPTZ | no | — | NOT NULL | UTC time of snapshot (hypertable dimension) |
| `outcomes_prices` | JSONB | no | — | NOT NULL | `{"Yes": 0.72, "No": 0.28}` |
| `volume_24h` | NUMERIC(20,4) | yes | `null` | — | 24h volume at snapshot time |
| `liquidity` | NUMERIC(20,4) | yes | `null` | — | Liquidity at snapshot time |
| `source_event_id` | TEXT | no | — | NOT NULL | Kafka event_id for tracing |

- **Unique constraint**: `(market_id, snapshot_at)` — prevents duplicate snapshots
- **Indexes**: `(market_id, snapshot_at DESC)` for time-series queries; standard TimescaleDB chunk index on `snapshot_at`
- **Partitioning**: TimescaleDB hypertable on `snapshot_at`, 7-day chunks
- **Compression**: TimescaleDB compress after 30 days (outcomes_prices JSONB compresses well)
- **Estimated rows**: ~2,000 active markets × 288 snapshots/day (5-min interval) = ~576K rows/day

**Migration note**: Add to S3's Alembic migrations. Use `op.execute("SELECT create_hypertable(...)")`.

---

#### New table: `prediction_market_fetch_log` (`content_ingestion_db`, owned by S4)

Used for per-cycle deduplication: the adapter skips markets where `(market_id, snapshot_at)` already exists.

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `id` | UUID | no | — | PK | App-generated UUIDv7 (no server default) |
| `source_id` | UUID | yes | `null` | FK → `sources(id)` | Nullable to allow standalone test inserts |
| `market_id` | TEXT | no | — | NOT NULL | Polymarket condition_id |
| `snapshot_at` | TIMESTAMPTZ | no | — | NOT NULL | Rounded-to-minute fetch timestamp |
| `resolution_status` | VARCHAR(20) | no | `'open'` | NOT NULL | `open` / `resolved` / `cancelled` |
| `fetched_at` | TIMESTAMPTZ | no | — | NOT NULL | Actual fetch time |
| `created_at` | TIMESTAMPTZ | no | `now()` | NOT NULL | Row creation time |

- **Unique constraint**: `(market_id, snapshot_at)` — primary deduplication key
- **Indexes**: `(source_id, fetched_at)` for source-level audit queries
- **Partitioning**: none (low volume — ~2,000 rows/5-min cycle × 288 cycles/day = ~576K rows/day at max; prune old rows via scheduled job)
- **Migration**: S4 Alembic `0004_add_prediction_market_fetch_log.py`

---

#### S4: new outbox topic routing

S4's existing `outbox_events.topic` column (TEXT, default `'content.article.raw.v1'`) will have a new possible value: `'market.prediction.v1'`. No schema migration needed — the column is already `TEXT` with no CHECK constraint.

---

### 6.5 Domain Model Changes

#### S4: New SourceType value

```python
class SourceType(StrEnum):
    EODHD = "eodhd"
    SEC_EDGAR = "sec_edgar"
    FINNHUB = "finnhub"
    NEWSAPI = "newsapi"
    MANUAL = "manual"
    POLYMARKET = "polymarket"   # NEW
```

**Impact**: The `sources` table `source_type` column stores this as a TEXT value — no DB migration needed. Existing enum validation in the domain layer must allow the new value.

---

#### S4: New entity — `PredictionMarketFetchResult` (frozen dataclass)

- **Purpose**: Represents one polled snapshot from Polymarket Gamma API
- **Frozen**: yes (immutable after creation)

| Attribute | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| `id` | UUID | yes | UUIDv7 | Generated on creation |
| `source_type` | SourceType | yes | `SourceType.POLYMARKET` | Always Polymarket |
| `market_id` | str | yes | 1–200 chars | Polymarket condition_id |
| `question` | str | yes | 1–2000 chars | Market question |
| `description` | str \| None | no | — | Optional description |
| `outcomes` | list[OutcomeSnapshot] | yes | len ≥ 2 | Outcome definitions + prices |
| `volume_24h` | float \| None | no | ≥ 0.0 if present | 24h volume (absent from some markets) |
| `liquidity` | float \| None | no | — | Liquidity pool |
| `close_time` | datetime \| None | no | UTC-aware if not None | Scheduled close |
| `resolution_status` | str | yes | `open`/`resolved`/`cancelled` | Market status |
| `resolved_answer` | str \| None | no | — | Winner if resolved |
| `raw_bytes` | bytes | yes | len > 0 | Raw Gamma API response |
| `fetched_at` | datetime | yes | UTC-aware | Fetch timestamp |
| `minio_bronze_key` | str \| None | no | — | MinIO key set by adapter after storage; `None` if MinIO write failed |

- **Invariants**: `fetched_at` is UTC-aware. `outcomes` has ≥2 members. Sum of outcome prices ≈ 1.0 (soft check; Polymarket AMMs may not be perfectly balanced).
- **Factory**: `PredictionMarketFetchResult.from_gamma_response(raw_response, fetched_at)` — sets `minio_bronze_key=None`; adapter sets it after MinIO storage by constructing a new instance (replace pattern, since frozen).

> **Implementation note**: `PredictionMarketFetchResult` is frozen. The adapter calls `dataclasses.replace(result, minio_bronze_key=key)` after MinIO storage to produce an updated copy before passing to the use case.

---

#### S4: New entity — `OutcomeSnapshot` (frozen dataclass)

| Attribute | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| `name` | str | yes | 1–100 chars | Outcome label |
| `token_id` | str | yes | 1–200 chars | ERC-1155 token ID |
| `price` | float | yes | 0.0–1.0 inclusive | Current probability |

---

#### S3: New entity — `PredictionMarket` (mutable dataclass)

- **Purpose**: Represents a prediction market's metadata and latest state

| Attribute | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| `id` | UUID | yes | UUIDv7 | Internal ID |
| `market_id` | str | yes | 1–200 chars | Polymarket condition_id |
| `source` | str | yes | `"polymarket"` | Data origin |
| `question` | str | yes | 1–2000 chars | Market question |
| `description` | str \| None | no | — | Full description |
| `outcomes` | list[dict] | yes | len ≥ 2 | `[{"name": str, "token_id": str}]` |
| `close_time` | datetime \| None | no | UTC-aware | Scheduled resolution |
| `resolution_status` | str | yes | enum | `open`/`resolved`/`cancelled` |
| `resolved_answer` | str \| None | no | — | Winner if resolved |
| `created_at` | datetime | yes | UTC-aware | First ingested |
| `updated_at` | datetime | yes | UTC-aware | Last updated |

---

#### S3: New entity — `PredictionMarketSnapshot` (frozen dataclass)

| Attribute | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| `id` | UUID | yes | UUIDv7 | Internal ID |
| `market_id` | str | yes | 1–200 chars | Logically links to `PredictionMarket` |
| `snapshot_at` | datetime | yes | UTC-aware | Snapshot timestamp |
| `outcomes_prices` | dict[str, float] | yes | len ≥ 2, values 0.0–1.0 | `{"Yes": 0.72, "No": 0.28}` |
| `volume_24h` | Decimal \| None | no | ≥ 0 | 24h volume |
| `liquidity` | Decimal \| None | no | ≥ 0 | Liquidity |
| `source_event_id` | str | yes | UUIDv7 | Kafka event_id for idempotency |

- **Invariants**: `snapshot_at` is UTC-aware. `outcomes_prices` has ≥2 entries.

---

#### S4: New adapter — `PolymarketAdapter`

```
infrastructure/adapters/polymarket/
├── client.py       # PolymarketClient: wraps Gamma API HTTP calls
└── adapter.py      # PolymarketAdapter(SourceAdapter): fetch, dedup, outbox write
```

- **Base class**: `SourceAdapter` (existing ABC)
- **Client method**: `fetch_active_markets(limit: int = 500, next_cursor: str | None) -> GammaMarketsPage`
- **Gamma API endpoint**: `GET https://gamma-api.polymarket.com/markets?active=true&limit={limit}&next_cursor={cursor}`
- **Pagination**: cursor-based (Gamma API returns `next_cursor`); adapter iterates until no next_cursor or watermark check
- **Dedup strategy**: Skip markets where `(market_id, snapshot_at)` already exists in `prediction_market_fetch_log`
- **Rate limit**: No explicit rate limiting needed (Gamma API: 4000 req/10s; we generate <1 req/s)
- **Outbox topic**: `'market.prediction.v1'` (set on each outbox record, not the default)

---

#### S4: EDGAR market-hours aware scheduler

In `infrastructure/adapters/sec_edgar/adapter.py`, method `calculate_next_run_time()`:

```python
from zoneinfo import ZoneInfo
NY_TZ = ZoneInfo("America/New_York")

def _is_market_hours(self, now_utc: datetime) -> bool:
    now_ny = now_utc.astimezone(NY_TZ)
    return (
        now_ny.weekday() < 5          # Monday=0 … Friday=4
        and time(9, 30) <= now_ny.time() <= time(16, 0)
    )

def calculate_next_run_time(self, now_utc: datetime) -> datetime:
    interval = (
        self.settings.market_hours_interval_seconds
        if self._is_market_hours(now_utc)
        else self.settings.off_hours_interval_seconds
    )
    return now_utc + timedelta(seconds=interval)
```

New env vars (nested settings under `CONTENT_INGESTION_SEC_EDGAR__`):

| Env Var | Default | Description |
|---------|---------|-------------|
| `CONTENT_INGESTION_SEC_EDGAR__MARKET_HOURS_INTERVAL_SECONDS` | `60` | Polling interval during 09:30–16:00 ET weekdays |
| `CONTENT_INGESTION_SEC_EDGAR__OFF_HOURS_INTERVAL_SECONDS` | `1800` | Polling interval outside market hours |

---

#### S3: New consumer — `PredictionMarketConsumer`

```
services/market-data/src/market_data/consumers/
└── prediction_market_consumer.py   # PredictionMarketConsumer(BaseKafkaConsumer)
```

- **Extends**: `BaseKafkaConsumer` (R20)
- **Topic**: `market.prediction.v1`
- **Consumer group**: `market-data-prediction-markets`
- **Idempotency key**: `source_event_id` checked against `idempotency` table
- **Processing logic**:
  1. Deserialise Avro event
  2. Idempotency check
  3. UPSERT `prediction_markets` (metadata) with `updated_at = now()`
  4. INSERT `prediction_market_snapshots` ON CONFLICT (market_id, snapshot_at) DO NOTHING
  5. Mark idempotency record

---

### 6.6 Frontend Changes

#### New component: `PredictionMarketsPanel` (J4 Signals view)

- **Location**: `apps/frontend/src/components/signals/PredictionMarketsPanel.tsx`
- **Data source**: `GET /api/v1/signals/prediction-markets?status=open&limit=20`
- **Refresh interval**: 5 minutes (client-side polling via React Query `refetchInterval`)
- **Layout**: Card list, each card shows:
  - Market question (truncated at 120 chars)
  - Probability bar (Yes in green, No in red, proportional)
  - Percentage labels (e.g. "72% Yes · 28% No")
  - Volume indicator (24h USD volume, abbreviated)
  - Close time if set (relative: "closes in 3 days")
- **Sorting**: by volume_24h DESC (highest-activity markets first)
- **Empty state**: "No active prediction markets" placeholder
- **Loading state**: 3 skeleton card rows
- **TypeScript types**:
  - `PredictionMarketSummary` (mirrors API response)
  - `OutcomePrice` (name, token_id, price)

---

### 6.7 Data Flow

#### Prediction Market Ingestion Flow

```
[Polymarket Gamma API]
  ↓ HTTP GET (5-min interval, cursor-paginated)
[S4 PolymarketAdapter.fetch_active_markets()]
  ↓ PredictionMarketFetchResult per market
[S4: write prediction_market_fetch_log + outbox_event] ← single DB tx (R8)
  ↓ OutboxDispatcher
[Kafka: market.prediction.v1]
  ↓ PredictionMarketConsumer (S3)
[S3: UPSERT prediction_markets + INSERT prediction_market_snapshots] ← single DB tx
  ↓ (idempotency record)
[S3 API: /api/v1/prediction-markets/**]
  ↓ S9 proxy
[Frontend: PredictionMarketsPanel ← 5-min React Query poll]
```

#### OutcomePrice[] Assembly (S3 API)

The `prediction_markets` table stores outcome **definitions** (`[{name, token_id}]` — no prices). Current prices are in `prediction_market_snapshots.outcomes_prices` (`{outcome_name: price}`). The S3 use cases assemble `OutcomePrice[]` as follows:

```
GetPredictionMarketUseCase / ListPredictionMarketsUseCase:
  1. Fetch PredictionMarket (outcomes = [{name, token_id}])
  2. Fetch latest PredictionMarketSnapshot for the market
     → outcomes_prices = {"Yes": 0.72, "No": 0.28}
  3. Build OutcomePrice list:
     [{name: o["name"], token_id: o["token_id"], price: outcomes_prices.get(o["name"], 0.0)}
      for o in market.outcomes]
```

For the list endpoint, the repository uses a SQL subquery to fetch the latest snapshot's `outcomes_prices` per market in a single query (avoids N+1).

#### EDGAR Market-Hours Flow

```
[S4 Scheduler] → calls SecEdgarAdapter.calculate_next_run_time(now_utc)
  → _is_market_hours(now_utc)?
    YES: next_run = now + 60s
    NO:  next_run = now + 1800s
  → stores next_run_at in source_adapter_state
[S4 Scheduler wakes at next_run_at] → polls EDGAR EFTS
```

---

## 7. Architecture Decisions

### AD-1: Polymarket in S4 vs new service

**Options considered**:
- A) New S11 service dedicated to alternative data sources
- B) Add Polymarket adapter to S4 (Content Ingestion)
- C) Add Polymarket adapter to S3 (Market Data)

**Decision**: B — S4 as the unified external data poller.

**Rationale**: S4's role is fetching from external sources on schedule. Adding a new service violates R16 (requires ADR). S3 is a read service and should not poll external APIs directly. S4's outbox pattern naturally produces to any Kafka topic. The only downside is that `SourceType.POLYMARKET` looks unusual next to text sources — mitigated by clearly separating the `prediction_market_fetch_log` table from `article_fetch_log`.

### AD-2: S3 as materialisation target

**Options considered**:
- A) S7 (Knowledge Graph) — prediction markets have entity relationships
- B) S3 (Market Data) — prediction markets are market data (probability prices)
- C) New `intelligence_db` table owned by `intelligence-migrations`

**Decision**: B — S3 as the materialisation target.

**Rationale**: Prediction market probabilities are structurally identical to prices: a time-series of numerical values tied to a market identifier. S3 already has TimescaleDB, hypertables, and the pattern for serving time-series reads. Entity linking (associating market questions to canonical entities) is deferred to PRD-0020 and can be added to `intelligence_db` at that point.

### AD-3: Separate `prediction_market_fetch_log` from `article_fetch_log`

**Decision**: Separate table.

**Rationale**: `article_fetch_log` deduplicates by `url_hash` (SHA-256 of URL), which is meaningless for prediction markets. Prediction markets are deduplicated by `(market_id, snapshot_at)`. Reusing `article_fetch_log` would require making `url_hash` nullable or adding a composite key override — both are worse than a clean separate table.

---

## 8. Security Analysis

| Threat | Mitigation |
|--------|-----------|
| Polymarket API response injection | All market data is stored in JSONB and never interpolated into SQL or LLM prompts without sanitisation |
| SSRF via market `description` field | Description field is stored as-is; never used as a URL |
| Unbounded market data volume | Polymarket poll is capped at 500 markets per cursor page; total active market count ~5,000 — finite and manageable |
| Tenant data isolation | S3 prediction markets are global (non-tenant-scoped) market data, not user-specific. No tenant isolation needed. S9 still requires JWT auth to access. |
| Rate limit abuse on S9 endpoints | Standard S9 100 req/min per user. History endpoint has `limit` capped at 2000 to bound response size. |
| No API key for Polymarket | No secrets to manage. Upside: no credential leak risk. Downside: no auth = IP-based rate limit. Mitigated by polling ≤2 req/5min. |

---

## 9. Failure Modes

| Failure | Detection | Recovery |
|---------|-----------|---------|
| Polymarket Gamma API unavailable | S4 adapter error → `source_adapter_state.error_count++`; exponential backoff; max_backoff = 30min | Auto-recovery when API returns; last snapshot remains valid (staleness acceptable) |
| Kafka unavailable | S4 outbox write fails → stays in `outbox_events` as pending; retried by dispatcher on recovery | At-least-once guarantee; S3 consumer idempotent via `(market_id, snapshot_at)` UNIQUE constraint |
| S3 DB unavailable | Consumer lag increases; `pending_alerts` in Kafka topic (30-day retention) | Auto-recovery; no data loss within retention window |
| Malformed Polymarket response | `PredictionMarketFetchResult.from_gamma_response()` raises `ValidationError` → DLQ | DLQ admin UI for inspection; adapter continues with other markets |
| TimescaleDB chunk creation failure | Hypertable may fail on first insert if extension not installed | Handled by Alembic migration pre-check: `SELECT create_hypertable` only if extension present |
| EDGAR during market hours, high poll frequency | Risk: EDGAR EFTS rate limit (undocumented) | Rate-limit 60s interval is conservative; if 429 received, fall back to 30min via error_count logic |

---

## 10. Scalability

| Concern | Estimate | Mitigation |
|---------|----------|-----------|
| `prediction_market_snapshots` row growth | ~576K rows/day at 5-min polling for 2,000 markets | TimescaleDB compression after 30 days; 7-day chunks; data retention policy: keep 90 days, archive older |
| S4 Polymarket polling overhead | ~10 cursor pages × 1 HTTP req/page = ~10 req per 5-min cycle | Negligible; async HTTP with connection pooling |
| S3 history query latency | 500 snapshots per market over 7 days is typical fetch | `(market_id, snapshot_at DESC)` index covers this; TimescaleDB chunk exclusion reduces scan |
| Kafka consumer lag | If S3 is slow, lag grows | Single consumer handles ~400 events/min easily; S3 batch insert if needed |

---

## 11. Test Strategy

### Unit Tests (S4)

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_polymarket_client_parses_gamma_response` | `PolymarketClient.parse_markets_page()` correctly maps Gamma API JSON to `PredictionMarketFetchResult` list | HIGH |
| `test_outcome_snapshot_price_bounds` | `OutcomeSnapshot` with `price < 0` or `price > 1` raises `ValueError` | HIGH |
| `test_polymarket_adapter_dedup_skips_existing` | Adapter skips markets already in `prediction_market_fetch_log` for same snapshot time | HIGH |
| `test_polymarket_fetch_result_invariants` | `from_gamma_response()` with empty `outcomes` raises `ValueError` | HIGH |
| `test_edgar_is_market_hours_tue_10am_et` | Returns `True` for 10:00 ET Tuesday | HIGH |
| `test_edgar_is_market_hours_sat_noon_et` | Returns `False` for Saturday noon | HIGH |
| `test_edgar_is_market_hours_dst_transition` | Correct behaviour on DST switch day (second Sunday of March) | MEDIUM |
| `test_edgar_calculate_next_run_market_hours` | `calculate_next_run_time()` during market hours uses `market_hours_interval_seconds` | HIGH |
| `test_edgar_calculate_next_run_off_hours` | Uses `off_hours_interval_seconds` at 18:00 ET | HIGH |

### Unit Tests (S3)

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_prediction_market_snapshot_invariants` | `snapshot_at` without tzinfo raises `ValueError` | HIGH |
| `test_prediction_markets_list_filters_by_status` | `FakeRepository.list(status="resolved")` returns only resolved markets | HIGH |
| `test_prediction_market_history_pagination` | History use case respects `limit` and `from`/`to` range | HIGH |

### Integration Tests (S4)

| Test | Infrastructure | What It Verifies |
|------|---------------|-----------------|
| `test_polymarket_adapter_pipeline_end_to_end` | Postgres + wiremock (Gamma API mock) | Adapter fetch → `prediction_market_fetch_log` row + `outbox_events` row in single tx |
| `test_polymarket_adapter_idempotent_repoll` | Postgres | Same markets polled twice → exactly 1 fetch log row per (market_id, snapshot_at) |
| `test_edgar_market_hours_polling_interval` | Postgres | Scheduler writes correct `next_run_at` based on mocked clock |

### Integration Tests (S3)

| Test | Infrastructure | What It Verifies |
|------|---------------|-----------------|
| `test_prediction_market_consumer_upserts_metadata` | Postgres + Kafka | Event consumed → `prediction_markets` row upserted |
| `test_prediction_market_consumer_inserts_snapshot` | Postgres + Kafka | Event consumed → `prediction_market_snapshots` row inserted |
| `test_prediction_market_consumer_idempotent` | Postgres + Kafka | Same event consumed twice → 1 snapshot row |
| `test_prediction_markets_list_api` | Postgres | `GET /api/v1/prediction-markets` returns paginated results |
| `test_prediction_market_history_api` | Postgres (TimescaleDB) | `GET /api/v1/prediction-markets/{id}/history` returns time-ordered snapshots |

### Contract Tests

| Test | What It Verifies |
|------|-----------------|
| `test_prediction_market_snapshot_avro_schema` | `PredictionMarketSnapshot` Avro schema is valid and forward-compatible |
| `test_prediction_market_snapshot_serialisation` | Sample event serialises/deserialises correctly via fastavro |

---

## 12. Migration Plan

1. **S4 migration**: Add `prediction_market_fetch_log` table in a new Alembic migration. Add `POLYMARKET` to `SourceType` enum (Python only — DB stores TEXT, no migration needed).
2. **S3 migration**: Add `prediction_markets` and `prediction_market_snapshots` tables. Ensure TimescaleDB extension is installed (it is, per existing `market_data_db` setup). Call `create_hypertable` via `op.execute()`.
3. **Avro schema**: Register `PredictionMarketSnapshot.avsc` with Confluent Schema Registry before S4 deployment.
4. **Deployment order**: S3 consumer must be deployed before S4 starts producing (consumer first). Otherwise Kafka messages accumulate safely within 30-day retention.

---

## 13. Observability

### S4 new metrics

| Metric | Labels | Description |
|--------|--------|-------------|
| `s4_polymarket_polls_total` | `status={success,error}` | Total Polymarket poll cycles |
| `s4_polymarket_markets_fetched_total` | — | Total unique markets fetched per poll |
| `s4_polymarket_markets_skipped_total` | `reason={duplicate,resolved}` | Markets skipped during dedup |

### S3 new metrics

| Metric | Labels | Description |
|--------|--------|-------------|
| `s3_prediction_market_events_consumed_total` | `status={success,error,duplicate}` | Consumer throughput |
| `s3_prediction_market_snapshots_total` | — | Cumulative snapshot rows |
| `s3_prediction_market_api_requests_total` | `endpoint,status_code` | API request rate |

### Log fields

- S4: `source_type=polymarket`, `market_id`, `outcomes_count`, `resolution_status`
- S3: `service=market-data`, `market_id`, `snapshot_at`, `consumer_group`

---

## 14. Open Questions

| ID | Question | Owner | Deadline |
|----|----------|-------|----------|
| OQ-001 | ~~Should prediction markets be tenant-scoped in future?~~ **RESOLVED**: Global (non-tenant-scoped) — prediction markets are market data, not user-specific. See §8 Security Analysis. | Arnau | — |
| OQ-002 | Polymarket markets can be paused mid-life. Should paused markets be polled or skipped? | Arnau | Wave A-1 |
| OQ-003 | TimescaleDB compression may conflict with testcontainers in integration tests (no TimescaleDB extension). Should integration tests use real Docker or mock the hypertable? | Arnau | Wave A-2 |

---

## 15. Effort Estimation

| Area | Waves | Estimated Complexity |
|------|-------|---------------------|
| S4: PolymarketAdapter + fetch log table + outbox routing | 2 waves | Medium |
| S4: EDGAR market-hours polling | 0.5 wave (fold into Wave A-1) | Low |
| Avro schema + Schema Registry | 0.5 wave | Low |
| S3: Consumer + DB tables + API endpoints | 2 waves | Medium |
| S9: Proxy routes | 0.5 wave | Low |
| Frontend: PredictionMarketsPanel | 1 wave | Medium |
| **Total** | **~6.5 waves** | — |
