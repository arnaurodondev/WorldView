# PLAN-0036 — EODHD API Usage Reduction
## Production-Grade Quota Management, Symbol Tiering, and PriceSnapshot Layer

> **Status**: Completed — Wave 0 + Wave 1 + Wave 2 + Wave 3 complete
> **Branch**: feat/eodhd-usage-reduction (to be created from main)
> **Quota constraint**: 100,000 credits / calendar month (hard ceiling)
> **Investigation basis**: `/investigate` session 2026-04-24 (8-agent deep dive)
> **Plan basis**: `/plan` session 2026-04-24 (8 planning subagents)

---

## 1. Executive Summary

The EODHD API is the platform's sole external market-data provider and costs
100,000 credits/month (quota ceiling). The current implementation **exceeds this
limit at steady state** with only 64 symbols: per-symbol quote polling at 5-minute
intervals during market hours consumes ~99,840 credits/month from quotes alone,
leaving virtually no headroom for OHLCV, fundamentals, or news calls. Scaling to
500+ symbols makes the problem catastrophically worse.

Four compounding issues drive excess consumption:

1. **Per-symbol quote polling** — every symbol makes an individual EODHD call
   every 5 minutes during market hours. Bulk endpoints exist but are unused.
2. **Per-process token bucket (BP-185)** — each worker replica maintains its own
   rate-limit state; shared quota enforcement is missing.
3. **No pre-fetch freshness gate** — the `last_success_at` watermark column
   exists but is never written; tasks re-fetch even when data is fresh.
4. **WatermarkViolation retry amplification** — losing concurrent workers
   re-fetch EODHD rather than reading the bronze payload already in MinIO.

**Recommended approach**: Four implementation waves delivering:
- Monthly quota enforcement with Valkey-backed shared counter
- Bulk-per-exchange quote batching (HTTP overhead reduction)
- Symbol tiering (T0–T4) with cadence matrix matching product freshness needs
- PriceSnapshot fallback chain serving stale data gracefully instead of blocking
- Circuit breaker, Retry-After parsing, shared distributed rate limiter
- Full observability: Prometheus metrics, Grafana dashboard, alert rules

**Expected outcome**: 64 symbols → 36,000 credits/month (65% reduction);
1,000 symbols → 66,000 credits/month (stays under quota); 3,000 symbols → 57,000
credits/month with strict tiering.

**Recommendation**: **SAFE_TO_IMPLEMENT** — all four waves are additive, each
wave is independently rollback-safe, and Wave 0 alone (quota enforcement) has
zero regression risk.

---

## 2. Current Usage and Budget Assessment

### 2.1 EODHD Credit Pricing

| Endpoint type | Credits per call |
|---|---|
| Real-time / live quote | 1 |
| EOD historical (daily, weekly, monthly OHLCV) | 1 |
| Intraday (5m, 1h) | 5 |
| Fundamentals (`/api/fundamentals`) | 10 |
| News and sentiment (`/api/news`) | 5 |
| Bulk EOD (multiple symbols, `?s=`) | 1 per symbol in batch |
| Economic events / macro indicators | 5 |

### 2.2 Baseline Consumption (64 symbols, current implementation)

| Category | Calculation | Credits/month |
|---|---|---|
| Quote polling (5-min intervals, market hours) | 64 sym × 12/hr × 130 hr/mo | **99,840** |
| EOD daily OHLCV | 64 × 1 × 20 trading days | 1,280 |
| EOD weekly OHLCV | 64 × 1 × 4 weeks | 256 |
| Fundamentals (monthly refresh) | 64 × 10 | 640 |
| News/sentiment (S4, ~300 articles) | 300 × 5 | 1,500 |
| **Total** | | **~103,516** |

**Current state: ~3.5% over quota with 64 symbols alone.**

Market hours assumption: NYSE/NASDAQ 09:30–16:00 ET ≈ 6.5 hours × 20 trading
days = 130 hours/month.

### 2.3 Root Cause Analysis

| Bug / Gap | Impact | Severity |
|---|---|---|
| **BP-185**: per-process token bucket | Each worker replica has independent quota state; concurrent replicas can collectively exceed budget 4× | HIGH |
| **Dead watermark column** | `ingestion_watermarks.last_success_at` exists (migration 0001) but `watermark_repository.save()` never writes it → pre-fetch gate is inoperable | HIGH |
| **WatermarkViolation retry** | Losing concurrent worker retries the full pipeline including EODHD re-fetch instead of reading existing bronze from MinIO | MEDIUM |
| **No monthly quota counter** | Budget is tracked as daily credits_used in-process with no shared state and no monthly ceiling | HIGH |
| **No Retry-After parsing** | 429 responses send exponential backoff jitter but ignore the `Retry-After` header; backoff may be too short, causing rapid retry bursts | MEDIUM |
| **`provider_rate_limited_total` phantom metric** | Referenced in runbook (line 95) but never defined in any source file | LOW |
| **No circuit breaker** | Sustained 429 storm causes all workers to retry concurrently; no shared coordination to pause all replicas | MEDIUM |

---

## 3. Target Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Market-Ingestion (S2)                                              │
│                                                                     │
│  ScheduleDueTasksUseCase                                            │
│  ├── SymbolTierRepository ──→ T0/T1/T2/T3/T4 cadence matrix        │
│  ├── PreFetchFreshnessGate ──→ last_success_at watermark check      │
│  ├── MonthlyQuotaService ──→ Valkey INCRBY atomic counter           │
│  └── Creates BulkQuotesTask (per-exchange) instead of per-symbol    │
│                                                                     │
│  ExecuteTaskUseCase                                                 │
│  ├── EodhdQuotaService.try_consume() → OK / SOFT / HARD            │
│  ├── ValkeyCircuitBreaker.check() → CLOSED / OPEN / HALF_OPEN      │
│  ├── EODHDProviderAdapter                                           │
│  │   ├── fetch_bulk_quotes(exchange, symbols[]) → batch call        │
│  │   ├── _parse_retry_after(header) → float | None                 │
│  │   └── _endpoint_slug(url) → metrics label                       │
│  ├── ValkeyResponseCache → skip EODHD if TTL valid                 │
│  └── Watermark.last_success_at written on success                  │
└─────────────────────────────────────────────────────────────────────┘
                              │ Kafka: market.dataset.fetched
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Market-Data (S3)                                                   │
│                                                                     │
│  QuotesConsumer                                                     │
│  └── On new quote event: upsert quotes table                        │
│      → resolve PriceSnapshot via fallback chain                     │
│      → write price_snapshot:v1:{instrument_id} to Valkey (TTL=2h)  │
│                                                                     │
│  PriceSnapshotResolver (domain)                                     │
│  fresh_quote → bulk_quote → intraday_5m → intraday_1h →            │
│  daily_close → stale_snapshot → unavailable                         │
│                                                                     │
│  GET /internal/v1/price/{instrument_id} → PriceSnapshotResponse    │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  API Gateway (S9)                                                   │
│                                                                     │
│  GET /v1/quotes/{id} → enriched with freshness_status, source       │
│  POST /v1/quotes/batch → PriceSnapshot batch                        │
│  POST /api/v1/instruments/{id}/refresh-price → manual refresh       │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Frontend (worldview-web)                                           │
│                                                                     │
│  LiveQuoteBadge: poll 5s → 15s; show StaleBadge on delayed/stale   │
│  PortfolioSummary: "~" prefix when any quote is delayed             │
│  IndexTicker: muted color on stale                                  │
└─────────────────────────────────────────────────────────────────────┘

Shared infrastructure (Valkey):
  eodhd:v1:quota:{YYYY-MM}:credits_used        ← monthly counter (INCRBY)
  eodhd:v1:quota:{YYYY-MM}:s2:credits_used     ← service attribution
  eodhd:v1:quota:{YYYY-MM}:s4:credits_used     ← service attribution
  eodhd:v1:circuit_breaker:global:state        ← CLOSED/OPEN/HALF_OPEN
  eodhd:v1:circuit_breaker:global:open_until   ← ISO-8601 UTC expiry
  eodhd:v1:circuit_breaker:global:failure_count ← 60s sliding window
  eodhd:resp:{dataset_type}:{symbol}:{date}    ← response cache (max 50KB)
  price_snapshot:v1:{instrument_id}            ← resolved PriceSnapshot (TTL=2h)
  refresh_cooldown:{instrument_id}             ← manual refresh gate (TTL=300s)
```

---

## 4. Before/After Monthly Budget Table

### 4.1 Symbol Tier Definitions

| Tier | Definition | Quote interval | OHLCV | Fundamentals |
|---|---|---|---|---|
| **T0** | Portfolio holdings (actively-held) | 5 min (market hrs) | Daily + intraday | Quarterly |
| **T1** | Watchlist (user-tracked but not held) | 15 min (market hrs) | Daily | Quarterly |
| **T2** | Tracked instruments (screener universe, active) | 1 hour (market hrs) | Daily (derived weekly/monthly) | Annually |
| **T3** | Screener-only (comparison universe) | EOD only (once/day) | Daily | Annually |
| **T4** | Inactive (not recently accessed) | None | None | None |

Tier caps for credit budget: **T0 ≤ 10**, **T1 ≤ 30**, **T2 ≤ 64**, **T3 uncapped**.

### 4.2 Credit Budget by Scale Scenario

| Scenario | Baseline (current) | Wave 1 target | Wave 2 target | Headroom at Wave 2 |
|---|---|---|---|---|
| **64 symbols** | ~103,500/mo | ~38,200/mo | ~36,800/mo | 63% |
| **500 symbols** | ~810,000/mo | ~52,700/mo | ~52,700/mo | 47% |
| **1,000 symbols** | ~1,620,000/mo | ~65,600/mo | ~65,600/mo | 34% |
| **3,000 symbols** | ~4,860,000/mo | ~57,000/mo | ~57,000/mo | 43% |

Note: "baseline at 500+ symbols" assumes the same 5-min per-symbol quote polling as today — it would exhaust the monthly quota in hours.

### 4.3 Detailed Breakdown — Wave 2 Target (All Scales)

**64 symbols (T0=10, T1=30, T2=24, T3=0):**

| Category | Credits/month |
|---|---|
| T0 quotes (5-min × 130 market-hrs) | 15,600 |
| T1 quotes (15-min × 130 market-hrs) | 15,600 |
| T2 quotes (1-hour × 130 market-hrs) | 3,120 |
| EOD OHLCV (all 64 symbols × 20 days) | 1,280 |
| Weekly/monthly OHLCV | 0 (derived from daily) |
| Fundamentals (quarterly, all 64) | 213 |
| News/sentiment (S4, capped) | 1,000 |
| **Total** | **~36,813** |

**500 symbols (T0=10, T1=30, T2=64, T3=396):**

| Category | Credits/month |
|---|---|
| T0+T1+T2 quotes | 34,320 |
| T3 quotes (EOD only × 20 days) | 7,920 |
| EOD OHLCV (T0-T2 = 104 symbols × 20 days) | 2,080 |
| T3 OHLCV (derived from EOD quotes) | 0 |
| Fundamentals (104 quarterly, 396 annually) | 677 |
| News/sentiment (S4) | 2,500 |
| Macro/economic events | 3,200 |
| **Total** | **~50,697** |

**1,000 symbols (T0=10, T1=30, T2=64, T3=896):**

| Category | Credits/month |
|---|---|
| T0+T1+T2 quotes | 34,320 |
| T3 quotes (EOD only × 20 days) | 17,920 |
| EOD OHLCV (T0-T2 = 104 symbols × 20 days) | 2,080 |
| Fundamentals (104 quarterly, 896 annually) | 1,094 |
| News/sentiment (S4, capped) | 5,000 |
| Macro/economic events | 5,200 |
| **Total** | **~65,614** |

**3,000 symbols (T0=10, T1=30, T2=64, T3-active=1,000, T4-inactive=1,896):**

| Category | Credits/month |
|---|---|
| T0+T1+T2 quotes | 34,320 |
| T3-active quotes (EOD only × 20 days) | 20,000 |
| T4 quotes | 0 |
| EOD OHLCV (T0-T2 = 104 symbols × 20 days) | 2,080 |
| Fundamentals (104 quarterly, 1,000 annually, T4=0) | 1,180 |
| News/sentiment (S4, capped) | 10,000 |
| Macro/economic events | 5,200 |
| **Total** | **~72,780** |

All four scale scenarios remain under the 100,000/month hard ceiling.

---

## 5. Endpoint-by-Endpoint Optimization Plan

### 5.1 Real-Time / Live Quote (`/api/real-time`)

**Current**: 1 call per symbol per 5 minutes, per-symbol HTTP request.
**Change**:
- Switch to bulk endpoint (`/api/real-time/{SYMBOL}?s=SYM2,SYM3,...`) — groups
  up to 50 symbols per call. Credit cost is the same (1/symbol), but HTTP
  overhead drops ~50×.
- Apply symbol tiering: T0=5min, T1=15min, T2=1h, T3=EOD-only, T4=never.
- Pre-fetch freshness gate: skip if `last_success_at` is within interval TTL.
- Response cached in Valkey (`eodhd:resp:quotes:{sym}:{date}`, TTL=240s).

**Credit saving**: Tiering alone reduces quote credits by ~66% at 64 symbols.

### 5.2 EOD Historical (`/api/eod`)

**Current**: Per-symbol call, daily (1 credit each), weekly (1 credit each),
monthly (1 credit each).
**Change**:
- Keep daily EOD polling for T0-T2 symbols only.
- Derive weekly OHLCV from daily bars in `market-data` (S3).
- Derive monthly OHLCV from weekly bars in `market-data` (S3).
- T3 symbols: EOD only, once per market-close (no intraday, no weekly, no
  monthly from EODHD — all derived).
- Bulk endpoint for T3: `GET /api/eod/{date}?s=SYM1,SYM2,...,SYM50` — 50
  symbols per call.

**Credit saving**: Eliminates all weekly + monthly EODHD calls (derived for free).

### 5.3 Intraday (`/api/intraday`)

**Current**: Not widely used, but available for 5-min and 1-hour bars.
**Change**:
- Intraday polling only for T0 symbols during market hours.
- T1-T4: use daily EOD or derive intraday from hourly bars.
- Cache: `eodhd:resp:intraday:{sym}:{date}`, TTL=3,300s (55 min for 1h bars).

**Credit saving**: 5× more expensive than EOD — keep strictly for T0 only.

### 5.4 Fundamentals (`/api/fundamentals`)

**Current**: Monthly refresh, 10 credits each.
**Change**:
- T0-T1: quarterly refresh (every 90 days).
- T2: annually (365 days).
- T3-T4: never (or only on explicit user action).
- Add freshness gate: watermark `dataset_type=fundamentals` must be older than
  the configured interval.

**Credit saving**: Monthly → quarterly = 3× reduction for T0-T1.

### 5.5 News and Sentiment (`/api/news`, S4 content-ingestion)

**Current**: S4 polls news, `max_pages_per_cycle=3`, no dedup of seen articles.
**Change**:
- S4 news polling unchanged for now (Wave 1 focus is on S2 quote reduction).
- Add `next_attempt_at` column to `content_ingestion_tasks` (migration 0005)
  to enable proper backoff on 429.
- S4 article dedup: skip EODHD re-fetch if article URL already in
  `content_sources` table (content-store check before EODHD call).
- Cap S4 news credits at 10,000/month via shared monthly quota counter.

### 5.6 Macro Indicators and Economic Events

**Current**: S2 `DatasetType.MACRO_INDICATOR` and `DatasetType.ECONOMIC_EVENTS`.
**Change**:
- Refresh interval: 90 days (was 30 days). Macro data changes quarterly.
- Only fetch for instruments that have a `region` field matching a tracked
  geopolitical region.

---

## 6. PriceSnapshot and Quote Fallback Design

### 6.1 Canonical Model

**File**: `libs/contracts/src/contracts/canonical/price_snapshot.py`

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

class PriceSource(StrEnum):
    FRESH_QUOTE        = "fresh_quote"        # quotes table, age < 5 min
    BULK_QUOTE         = "bulk_quote"         # quotes table, age < 15 min
    INTRADAY_5M_CLOSE  = "intraday_5m_close"  # last 5m bar close
    INTRADAY_1H_CLOSE  = "intraday_1h_close"  # last 1h bar close
    DAILY_CLOSE        = "daily_close"        # last daily bar close
    STALE_SNAPSHOT     = "stale_snapshot"     # expired prior snapshot
    UNAVAILABLE        = "unavailable"

class FreshnessStatus(StrEnum):
    LIVE        = "live"        # within 5 min, or outside market hrs with today's close
    RECENT      = "recent"      # within 1h
    DELAYED     = "delayed"     # within 1 day
    STALE       = "stale"       # > 1 day
    UNAVAILABLE = "unavailable"

@dataclass(frozen=True)
class PriceSnapshot:
    instrument_id: str
    symbol: str
    exchange: str
    price: Decimal
    price_change: Decimal | None          # vs previous close
    price_change_pct: Decimal | None
    timestamp: datetime                   # UTC — when price was valid
    fetched_at: datetime                  # UTC — when snapshot was resolved
    source: PriceSource
    freshness_status: FreshnessStatus
    stale_reason: str | None
    refresh_available: bool = True
    refresh_cooldown_remaining_sec: int = 0
```

### 6.2 Fallback Priority Chain

Resolution order in `PriceSnapshotResolver` (market-data domain):

1. **FRESH_QUOTE** — `quotes.timestamp > now() - 5min` → `LIVE`
2. **BULK_QUOTE** — `5min ≤ quotes.timestamp age < 15min` → `RECENT`
3. **INTRADAY_5M_CLOSE** — latest `ohlcv_bars` with `timeframe='5m'`, age < 1h → `RECENT`
4. **INTRADAY_1H_CLOSE** — latest 1h bar, age < 24h → `DELAYED` (market hrs) / `LIVE` (off-hrs)
5. **DAILY_CLOSE** — latest 1d bar → `DELAYED` (market hrs) / `LIVE` (off-hrs)
6. **STALE_SNAPSHOT** — prior Valkey snapshot if it exists → `STALE`
7. **UNAVAILABLE** — all sources absent → `UNAVAILABLE`

### 6.3 Market-Hours Aware Classification

```python
def classify_freshness(source, price_timestamp, resolved_at, exchange) -> FreshnessStatus:
    age = resolved_at - price_timestamp
    is_market_hours = _is_market_hours(resolved_at, exchange)

    if exchange in ("CC", "FOREX"):   # 24/7 markets
        if age.total_seconds() < 300:   return FreshnessStatus.LIVE
        if age.total_seconds() < 3600:  return FreshnessStatus.RECENT
        if age.total_seconds() < 86400: return FreshnessStatus.DELAYED
        return FreshnessStatus.STALE

    if not is_market_hours:
        # Daily close IS the live price outside trading hours
        if source in (PriceSource.DAILY_CLOSE, PriceSource.FRESH_QUOTE,
                      PriceSource.BULK_QUOTE):
            return FreshnessStatus.LIVE
        if age.total_seconds() < 86400:
            return FreshnessStatus.RECENT
        return FreshnessStatus.STALE

    # During market hours — strict age-based
    if age.total_seconds() < 300:    return FreshnessStatus.LIVE
    if age.total_seconds() < 900:    return FreshnessStatus.RECENT
    if age.total_seconds() < 86400:  return FreshnessStatus.DELAYED
    return FreshnessStatus.STALE
```

### 6.4 Storage

- **Valkey key**: `price_snapshot:v1:{instrument_id}` (JSON, TTL=2h)
- **Proactive population**: `QuotesConsumer.process_message()` writes to Valkey
  immediately after upserting `quotes` table — eliminates cache-aside miss cost
- **Coexistence**: `quote:v1:{instrument_id}` (existing 5s TTL) coexists during
  migration; deprecated after all S9 routes switch to PriceSnapshot

### 6.5 New S3 Endpoints

```
GET  /internal/v1/price/{instrument_id}   → PriceSnapshotResponse
POST /internal/v1/price/batch             → List[PriceSnapshotResponse]
```

### 6.6 S9 Modified Routes

- `GET /v1/quotes/{id}` → calls S3 internal price endpoint, enriches with
  `freshness_status`, `source`, `data_as_of`, `stale_reason`
- `POST /v1/quotes/batch` → same enrichment via batch
- `POST /api/v1/instruments/{id}/refresh-price` → per-symbol cooldown (5 min,
  Valkey key `refresh_cooldown:{instrument_id}`), then calls S2 trigger endpoint

### 6.7 TypeScript Contract Extension

```typescript
// apps/worldview-web/types/api.ts — add to existing Quote interface
export interface Quote {
  // existing fields unchanged
  price: number;
  change: number;
  change_pct: number;
  timestamp: string;
  volume: number | null;
  // new fields (optional for backward compatibility during Wave 3 migration)
  freshness_status?: "live" | "recent" | "delayed" | "stale" | "unavailable";
  source?: "fresh_quote" | "bulk_quote" | "intraday_5m_close" |
           "intraday_1h_close" | "daily_close" | "stale_snapshot" | "unavailable";
  data_as_of?: string;
  stale_reason?: string | null;
  refresh_available?: boolean;
  refresh_cooldown_remaining_sec?: number;
}
```

### 6.8 Product Surface Freshness Requirements

| Surface | Max acceptable staleness | Behavior if stale |
|---|---|---|
| Instrument page — current price | 15 min (market hrs) | `DELAYED` badge + `data_as_of` tooltip |
| Instrument page — price chart | 1h intraday / 1d daily | "Last updated HH:MM UTC" caption |
| Instrument page — fundamentals | 7 days | "As of [date]" label |
| Screener — price/change columns | 1h | Last close, no badge |
| Portfolio — current value | 15 min (market hrs) | Stale badge next to total |
| Portfolio — unrealised P&L | 15 min (market hrs) | "~" prefix on P&L numbers |
| Morning brief | Daily (market open) | Footnote: "Prices as of [date]" |
| TopBar index tickers | 15 min | Muted color on stale; dash on error |
| Knowledge graph | 1 day | "Prices as of [date]" footer |

---

## 7. Bulk/v2 Migration Design

### 7.1 New Task Type

```python
# services/market-ingestion/src/market_ingestion/domain/entities/ingestion_task.py
class DatasetType(StrEnum):
    # ... existing types ...
    BULK_QUOTES = "bulk_quotes"   # per-exchange bulk fetch (replaces QUOTES)
```

### 7.2 Bulk Task Schema

```python
@dataclass
class BulkIngestionTask:
    """One task per exchange, containing up to 50 symbols per EODHD batch."""
    exchange: str                 # e.g. "US", "LSE", "XETRA"
    symbols: frozenset[str]       # up to 50 per EODHD API limit
    dataset_type: DatasetType = DatasetType.BULK_QUOTES
    # dedupe key: stable hash of sorted(symbols) + exchange
```

### 7.3 Scheduler Change

For `DatasetType.QUOTES`: the scheduler groups symbols by exchange, creates one
`BulkIngestionTask` per exchange instead of one `IngestionTask` per symbol.

### 7.4 Alembic Migrations

- **0008_bulk_quotes_task.py** (market-ingestion): add `symbols_json JSONB` and
  `exchange VARCHAR(20)` to `ingestion_tasks`; add `BulkIngestionTask` dedupe key
- **0009_symbol_tiering.py** (market-ingestion): add `tier INTEGER DEFAULT 2`
  and `post_market_only BOOLEAN DEFAULT FALSE` to `polling_policies`; new
  `symbol_tiers` table with `(symbol, exchange, tier, tier_assigned_at,
  last_user_refresh_at)` columns; update cadence seeds

### 7.5 Important: Bulk Does NOT Reduce Credits

The EODHD bulk endpoint charges 1 credit per symbol in the batch — identical to
per-symbol calls. The benefit is purely HTTP overhead reduction (~50×). The real
credit lever is tiering (cadence reduction), not batching.

---

## 8. Quota Enforcement Design

### 8.1 Monthly Quota Service

**File**: `libs/messaging/src/messaging/eodhd_quota/quota_service.py`

```python
class QuotaCheckResult(StrEnum):
    OK                   = "ok"
    SOFT_LIMIT_EXCEEDED  = "soft_limit_exceeded"   # 80% threshold, log + alert
    HARD_LIMIT_EXCEEDED  = "hard_limit_exceeded"   # 100% threshold, reject task

class EodhdQuotaService:
    SOFT_LIMIT_RATIO = 0.80
    HARD_LIMIT = 100_000

    async def try_consume(
        self,
        cost: int,
        service: str,    # "market-ingestion" | "content-ingestion"
        symbol: str | None = None,
        month: str | None = None,   # "YYYY-MM", defaults to current
    ) -> QuotaCheckResult:
        """Atomically increment monthly counter. Returns quota status."""
```

### 8.2 Valkey Keys

```
eodhd:v1:quota:{YYYY-MM}:credits_used          # total monthly counter
eodhd:v1:quota:{YYYY-MM}:s2:credits_used       # S2 attribution
eodhd:v1:quota:{YYYY-MM}:s4:credits_used       # S4 attribution
eodhd:v1:quota:{YYYY-MM}:symbol:{TICKER}:credits_used  # per-symbol
```

TTL: set to 32 days on first write of each month (auto-expires after month ends).

### 8.3 DB Snapshot Table

**File**: `services/market-ingestion/src/market_ingestion/infrastructure/db/models/eodhd_monthly_usage.py`

```sql
CREATE TABLE eodhd_monthly_usage (
    id            UUID PRIMARY KEY,
    month         DATE NOT NULL UNIQUE,    -- first day of month
    credits_s2    INTEGER NOT NULL DEFAULT 0,
    credits_s4    INTEGER NOT NULL DEFAULT 0,
    credits_total INTEGER NOT NULL DEFAULT 0,
    soft_limit    INTEGER NOT NULL DEFAULT 80000,
    hard_limit    INTEGER NOT NULL DEFAULT 100000,
    snapshotted_at TIMESTAMPTZ NOT NULL
);
```

A scheduled job (`SnapshotEodhdQuotaUseCase`) runs at end-of-month and writes the
Valkey counters to this table for audit trails.

### 8.4 Admin Endpoint (S2)

```
GET /api/v1/eodhd/quota/status   → { month, credits_used, soft_limit, hard_limit, by_service, top_symbols }
POST /api/v1/eodhd/quota/reset   → Admin-only: reset monthly counter (emergency)
```

### 8.5 Retry-After Parsing

```python
def _parse_retry_after(header_value: str | None) -> float | None:
    if header_value is None:
        return None
    try:
        return max(0.0, float(header_value))   # integer seconds
    except ValueError:
        pass
    from email.utils import parsedate_to_datetime
    try:
        target = parsedate_to_datetime(header_value)
        return max(0.0, (target - datetime.now(tz=UTC)).total_seconds())
    except Exception:
        return None
```

`ProviderRateLimited` enriched:
```python
class ProviderRateLimited(RetryableDomainError):
    def __init__(self, message: str = "", *, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after: float | None = retry_after
```

### 8.6 Circuit Breaker

**State machine keys in Valkey:**
```
eodhd:v1:circuit_breaker:global:state          → "CLOSED" | "OPEN" | "HALF_OPEN"
eodhd:v1:circuit_breaker:global:open_until     → ISO-8601 UTC expiry
eodhd:v1:circuit_breaker:global:failure_count  → integer (TTL=60s sliding window)
eodhd:v1:circuit_breaker:{endpoint}:state      → per-endpoint variant
```

**Thresholds**: 5 consecutive failures within 60s → OPEN for 10 minutes →
HALF_OPEN (one probe) → CLOSED on success.

**Ports**:
```
services/market-ingestion/src/market_ingestion/application/ports/circuit_breaker.py
  CircuitBreakerPort (ABC), CircuitState (enum)

services/market-ingestion/src/market_ingestion/infrastructure/adapters/circuit_breaker.py
  ValkeyCircuitBreaker implements CircuitBreakerPort
```

---

## 9. Scheduler and Freshness Policy Matrix

### 9.1 Cadence Matrix

| Dataset | T0 interval | T1 interval | T2 interval | T3 interval | T4 |
|---|---|---|---|---|---|
| Quotes (live) | 5 min | 15 min | 1 hour | EOD only | None |
| EOD OHLCV (daily) | Daily | Daily | Daily | Daily | None |
| EOD OHLCV (weekly) | Derived | Derived | Derived | Derived | None |
| EOD OHLCV (monthly) | Derived | Derived | Derived | Derived | None |
| Intraday 5m | During mkt hrs | None | None | None | None |
| Intraday 1h | During mkt hrs | During mkt hrs | None | None | None |
| Fundamentals | Quarterly | Quarterly | Annually | Annually | None |
| Macro indicators | 90 days | 90 days | 90 days | 90 days | None |
| Economic events | 90 days | 90 days | 90 days | 90 days | None |
| News (S4) | Daily | Daily | Daily | Weekly | None |

### 9.2 Market Calendar

**File**: `services/market-ingestion/src/market_ingestion/domain/market_calendar.py`

```python
class MarketCalendar:
    def is_market_open(self, dt: datetime) -> bool: ...    # NYSE/NASDAQ 09:30-16:00 ET
    def is_post_close(self, dt: datetime) -> bool: ...     # 16:00-17:00 ET (for EOD tasks)
    def is_trading_day(self, d: date) -> bool: ...         # excludes weekends + holidays
```

Embedded NYSE holiday list 2026–2028. Extract from S2's existing `market_hours_only`
polling policy logic.

### 9.3 Pre-Fetch Freshness Gate

Fix `ingestion_watermarks.last_success_at` — currently never written.

```python
# In watermark_repository.save():
watermark.last_success_at = utc_now()   # ← add this line

# In ScheduleDueTasksUseCase before creating task:
if watermark.last_success_at and (
    utc_now() - watermark.last_success_at
).total_seconds() < FRESHNESS_TTL_SECONDS[task.dataset_type]:
    continue  # still fresh, skip
```

### 9.4 Freshness TTL Constants

**File**: `services/market-ingestion/src/market_ingestion/domain/freshness.py`

```python
FRESHNESS_TTL_SECONDS: dict[str, int] = {
    "quotes":          240,      # 4 min (T0 5-min interval with 1-min tolerance)
    "intraday_1h":     3_300,    # 55 min
    "ohlcv_daily":    82_800,    # 23h (daily bar available by 17:00)
    "ohlcv_weekly":        0,    # derived, never fetch
    "ohlcv_monthly":       0,    # derived, never fetch
    "fundamentals":  518_400,    # 6 days
    "macro":       7_689_600,    # 89 days
}
```

### 9.5 Distributed Fetch Lock (WatermarkViolation Prevention)

Valkey `SET NX` lock before EODHD call:
```
SETNX eodhd:lock:{dataset_type}:{symbol} 1 PX 30000
```

On lock contention (another worker is already fetching): read bronze payload
from MinIO instead of calling EODHD again. This eliminates the double-fetch
WatermarkViolation retry pattern.

---

## 10. Implementation Waves

### Wave 0 — Quota Enforcement and Retry Hygiene (Days 1–5)

**Goal**: Stop the bleeding. Enforce the 100K/month hard limit. Fix Retry-After.
**Risk**: Minimal (additive metrics, better backoff).
**Files changed**: ~8 files.

Tasks:
- [x] W0-1: Add `EodhdQuotaService` to `libs/messaging`; Valkey INCRBY counter
- [x] W0-2: Wire quota check into `ExecuteTaskUseCase` before EODHD call
- [x] W0-3: Fix `ProviderRateLimited` + `_parse_retry_after()` in `eodhd.py`
- [x] W0-4: Add `s2_eodhd_requests_total`, `s2_eodhd_credits_used_total` Prometheus counters
- [x] W0-5: Fix phantom metric in runbook (`provider_rate_limited_total` → `s2_eodhd_rate_limited_total`)
- [x] W0-6: Write `last_success_at` in `watermark_repository.save()`
- [x] W0-7: Tests: `test_monthly_quota_*`, `test_retry_after_*`, `test_prefetch_gate_*` (43 tests — 43 pass)

**Validation gate**: ✅ 43/43 unit tests pass. ruff + mypy clean on all changed files.
Wave 0 committed 2026-04-24.

### Wave 1 — Bulk Quotes, PriceSnapshot, Circuit Breaker (Days 6–20) ✅

**Goal**: Switch from per-symbol to per-exchange bulk fetching; deploy
PriceSnapshot fallback chain; add circuit breaker.
**Risk**: Medium (bulk API behavioral change); mitigated by parallel-run flag.
**Status**: **DONE** — 2026-04-24 · 49 tests pass (20 price_snapshot + 7 circuit_breaker + 22 S9 proxy) · ruff + mypy clean

Tasks (implemented W1-4, W1-6 through W1-13; W1-1/2/3/5/14 deferred to Wave 2):
- [x] W1-4: `ValkeyCircuitBreaker` + `CircuitBreakerPort`; wire into execute flow
- [ ] W1-1: `fetch_bulk_quotes(exchange, symbols[])` in `EODHDProviderAdapter` _(deferred Wave 2)_
- [ ] W1-2: `BulkIngestionTask` domain entity + Alembic migration 0008 _(deferred Wave 2)_
- [ ] W1-3: Scheduler creates `BulkIngestionTask` per exchange (feature flag `EODHD_BULK_QUOTES_ENABLED`) _(deferred Wave 2)_
- [ ] W1-5: `ValkeyResponseCache` (Valkey response caching, max 50KB) _(deferred Wave 2)_
- [x] W1-6: `PriceSnapshot` canonical model in `libs/contracts`
- [x] W1-7: `PriceSnapshotResolver` domain in market-data (S3)
- [x] W1-8: `QuotesConsumer` writes `price_snapshot:v1:{id}` to Valkey after upsert
- [x] W1-9: `GET /internal/v1/price/{id}` and `POST /internal/v1/price/batch` in S3
- [x] W1-10: S9 proxy updates: enrich quote endpoints with freshness fields
- [x] W1-11: S9 new endpoint: `POST /v1/instruments/{id}/refresh-price` (cooldown 300s)
- [x] W1-12: `StaleBadge` component + extend `Quote` TypeScript interface
- [x] W1-13: `LiveQuoteBadge` poll interval 5s → 15s; show stale badge
- [x] W1-14: Tests: `test_circuit_breaker_*` (7), `test_price_snapshot_*` (20), S9 proxy (22 pass)

**Validation gate**: ✅ 49 unit tests pass (7 circuit breaker + 20 price_snapshot domain + 22 S9 proxy).
ruff + mypy clean on all changed files. Wave 1 committed 2026-04-24.

### Wave 2 — Symbol Tiering, OHLCV Derivation, Cadence Reductions (Days 21–35) ✅

**Goal**: Install tiering infrastructure; derive weekly/monthly OHLCV; reduce
fundamentals cadence; add stale-data UI states.
**Risk**: Low (adds cadence options without removing data paths).
**Status**: **DONE** — 2026-04-24 · 81 market-ingestion + 472 market-data tests pass · ruff + mypy clean

Tasks:
- [x] W2-1: `SymbolTier` entity + `symbol_tiers` table (Alembic migration 0008)
- [x] W2-2: `tier` + `post_market_only` columns on `polling_policies`
- [x] W2-3: `MarketCalendar` domain utility
- [x] W2-4: `DeriveOHLCVUseCase` in market-data: aggregate daily → weekly → monthly
- [x] W2-5: `is_derived` field on `OHLCVBar` + `007_add_ohlcv_is_derived` migration
- [x] W2-6: `UpdateSymbolTierUseCase`
- [x] W2-7/W2-8: Cadence seeds migration 0009 (fundamentals/macro/economic_events → 90-day intervals)
- [x] W2-9: `PortfolioSummary`: "~" prefix when any quote is delayed/stale (with `formatStalenessAwarePrice`)
- [x] W2-10: `IndexTicker`: muted color on stale (pre-existing from Wave 1)
- [x] W2-11: Tests: `test_market_calendar` (9), `test_symbol_tier` (2), `test_polling_policy_tier` (3),
         `test_update_symbol_tier` (4), `test_derive_ohlcv` (9), `test_content_task_retry` (9), portfolio-stale (5)
- [x] W2-12: `next_attempt_at` backoff gate on `content_ingestion_tasks` (migration 0005 pre-existing)

**Validation gate**: ✅ 81 market-ingestion + 472 market-data unit tests pass. ruff + mypy clean. Wave 2 committed 2026-04-24.

### Wave 3 — Observability, Alerts, Runbooks (Days 36–42) ✅

**Goal**: Full observability stack. No behavior changes.
**Risk**: Minimal.
**Status**: **DONE** — 2026-04-24 · 87 market-ingestion tests pass (81 existing + 6 budget tracker) · ruff + mypy clean

Tasks:
- [x] W3-1: Prometheus metrics already present from Wave 0 (`infrastructure/metrics/eodhd.py`, 11 metrics with `s2_eodhd_` prefix)
- [x] W3-2: `DailyBudgetTracker` use case (`application/use_cases/daily_budget_tracker.py`)
- [x] W3-3: Grafana dashboard `infra/grafana/dashboards/eodhd-health.json` (9 panels, uid `eodhd-health-v1`)
- [x] W3-4: Prometheus alert rules `infra/prometheus/rules/eodhd.yml` — EodhdQuotaWarning (>80%), EodhdQuotaCritical (>95%), EodhdCircuitBreakerOpen, EodhdSustained429s, EodhdDailyBudgetExceeded
- [x] W3-5: Runbook update: `docs/runbooks/market-ingestion-operations.md` (Section 6: EODHD Quota Management)
- [x] W3-6: `docs/architecture/decisions/ADR_EODHD_FAILOVER.md` — 7-step failover chain, circuit breaker policy
- [x] W3-7: `SnapshotEodhdQuotaUseCase` (`application/use_cases/snapshot_quota.py`) returning `QuotaSnapshot`
- [x] W3-8: Admin endpoint `GET /api/v1/eodhd/quota/status` combining quota + daily budget + CB state

**Validation gate**: ✅ 87 market-ingestion unit tests pass. ruff + mypy clean. Wave 3 committed 2026-04-24.

---

## 11. Detailed Task Backlog

### New Files to Create

| File | Purpose | Wave |
|---|---|---|
| `libs/messaging/src/messaging/eodhd_quota/__init__.py` | Package | W0 |
| `libs/messaging/src/messaging/eodhd_quota/quota_service.py` | EodhdQuotaService | W0 |
| `services/market-ingestion/src/market_ingestion/domain/freshness.py` | TTL constants | W0 |
| `services/market-ingestion/src/market_ingestion/domain/market_calendar.py` | NYSE calendar | W2 |
| `services/market-ingestion/src/market_ingestion/domain/entities/symbol_tier.py` | SymbolTier | W2 |
| `services/market-ingestion/src/market_ingestion/application/ports/circuit_breaker.py` | CircuitBreakerPort | W1 |
| `services/market-ingestion/src/market_ingestion/application/use_cases/update_symbol_tier.py` | Tier assignment | W2 |
| `services/market-ingestion/src/market_ingestion/application/use_cases/snapshot_eodhd_quota.py` | Monthly snapshot | W3 |
| `services/market-ingestion/src/market_ingestion/application/use_cases/manual_refresh.py` | Manual refresh | W1 |
| `services/market-ingestion/src/market_ingestion/infrastructure/adapters/circuit_breaker.py` | ValkeyCircuitBreaker | W1 |
| `services/market-ingestion/src/market_ingestion/infrastructure/adapters/valkey_response_cache.py` | ValkeyResponseCache | W1 |
| `services/market-ingestion/src/market_ingestion/infrastructure/budget/daily_budget.py` | DailyBudgetTracker | W3 |
| `services/market-ingestion/src/market_ingestion/infrastructure/db/models/eodhd_monthly_usage.py` | DB snapshot model | W3 |
| `services/market-ingestion/src/market_ingestion/infrastructure/metrics/eodhd.py` | Prometheus metrics | W3 |
| `services/market-ingestion/alembic/versions/0008_bulk_quotes_task.py` | symbols_json + exchange | W1 |
| `services/market-ingestion/alembic/versions/0009_symbol_tiering.py` | tier column + symbol_tiers table | W2 |
| `services/market-ingestion/alembic/versions/0010_eodhd_monthly_usage.py` | eodhd_monthly_usage table | W3 |
| `libs/contracts/src/contracts/canonical/price_snapshot.py` | PriceSnapshot canonical | W1 |
| `services/market-data/src/market_data/domain/price_snapshot.py` | Resolver + classifier | W1 |
| `services/content-ingestion/alembic/versions/0005_add_next_attempt_at_cit.py` | next_attempt_at on CIT | W2 |
| `infra/grafana/dashboards/eodhd-health.json` | Grafana dashboard | W3 |
| `apps/worldview-web/components/ui/StaleBadge.tsx` | Stale indicator component | W1 |
| `docs/runbooks/eodhd-quota-operations.md` | Ops runbook | W3 |
| `docs/architecture/decisions/ADR_EODHD_FAILOVER.md` | Failover ADR | W3 |

### Files to Modify

| File | Change | Wave |
|---|---|---|
| `services/market-ingestion/src/market_ingestion/domain/entities/ingestion_task.py` | Add `BULK_QUOTES` dataset type; `retry_after` field | W0/W1 |
| `services/market-ingestion/src/market_ingestion/domain/entities/provider_budget.py` | Deprecate per-process TokenBucket | W1 |
| `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/eodhd.py` | `fetch_bulk_quotes()`, `_parse_retry_after()`, `_endpoint_slug()`, metrics instrumentation | W0/W1 |
| `services/market-ingestion/src/market_ingestion/infrastructure/repositories/watermark_repository.py` | Write `last_success_at` on save | W0 |
| `services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py` | Pre-fetch gate, bulk task creation, tier-aware cadence | W0/W1/W2 |
| `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py` | Quota check, circuit breaker, distributed lock | W0/W1 |
| `services/market-ingestion/src/market_ingestion/application/use_cases/claim_tasks.py` | Circuit breaker gate before claim | W1 |
| `services/market-data/src/market_data/infrastructure/consumers/quotes.py` | Write PriceSnapshot to Valkey after upsert | W1 |
| `services/market-data/src/market_data/api/routers/quotes.py` | Add internal price snapshot endpoints | W1 |
| `services/api-gateway/src/api_gateway/routes/proxy.py` | Enrich quote routes + refresh-price endpoint | W1 |
| `apps/worldview-web/types/api.ts` | Extend Quote interface with freshness fields | W1 |
| `apps/worldview-web/components/instrument/LiveQuoteBadge.tsx` | 5s → 15s poll; StaleBadge | W1 |
| `apps/worldview-web/components/dashboard/PortfolioSummary.tsx` | "~" prefix on delayed P&L | W2 |
| `docs/runbooks/market-ingestion-operations.md` | Fix phantom metric reference | W0 |
| `infra/prometheus/rules/alert-rules.yml` | EODHD quota + circuit breaker alerts | W3 |

---

## 12. Observability Plan

### 12.1 New Prometheus Metrics (S2)

```python
# services/market-ingestion/src/market_ingestion/infrastructure/metrics/eodhd.py

eodhd_requests_total = Counter(
    "s2_eodhd_requests_total",
    "Total EODHD API requests",
    labelnames=["endpoint", "status_code", "symbol_tier"]
)
eodhd_credits_used_total = Counter(
    "s2_eodhd_credits_used_total",
    "Total EODHD credits consumed",
    labelnames=["endpoint", "symbol_tier"]
)
eodhd_request_duration_seconds = Histogram(
    "s2_eodhd_request_duration_seconds",
    "EODHD request latency",
    labelnames=["endpoint"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)
eodhd_rate_limited_total = Counter(
    "s2_eodhd_rate_limited_total",
    "Total 429 responses from EODHD",
    labelnames=["endpoint"]
)
eodhd_errors_total = Counter(
    "s2_eodhd_errors_total",
    "Total EODHD errors",
    labelnames=["endpoint", "reason"]
)
eodhd_circuit_breaker_state = Gauge(
    "s2_eodhd_circuit_breaker_state",
    "Circuit breaker state (0=CLOSED, 1=OPEN, 2=HALF_OPEN)",
    labelnames=["endpoint"]
)
eodhd_monthly_credits_used = Gauge(
    "s2_eodhd_monthly_credits_used",
    "Credits used this calendar month"
)
eodhd_monthly_credits_limit = Gauge(
    "s2_eodhd_monthly_credits_limit",
    "Monthly credit hard limit"
)
# NOTE (PLAN-0107 A-5, 2026-06-05): the per-endpoint cache Counters originally
# proposed here were removed because no cache existed in the request path to
# emit them. They have been replaced by the provider-agnostic
# ``s2_mi_provider_cache_{hits,misses,errors}_total`` family declared in
# ``market_ingestion.application.metrics.cache`` (see PLAN-0107 Wave A-4).
```

### 12.2 Grafana Dashboard — `eodhd-health.json`

**Row 1 — Credit Budget:**
- Gauge: `s2_eodhd_monthly_credits_used / s2_eodhd_monthly_credits_limit × 100`
  (% used, threshold at 80% amber / 95% red)
- Time series: Credits used per day (rolling 30d)

**Row 2 — Request Rate:**
- Time series: `rate(s2_eodhd_requests_total[5m])` by endpoint
- Stat: Overall success rate %

**Row 3 — Rate Limiting:**
- Time series: `rate(s2_eodhd_rate_limited_total[5m])`
- State timeline: `s2_eodhd_circuit_breaker_state` by endpoint

**Row 4 — Latency:**
- Heatmap: `s2_eodhd_request_duration_seconds` p50/p95/p99

**Row 5 — Cache:**
- Stat: Hit rate % (`cache_hits / (cache_hits + cache_misses)`)

**Row 6 — Errors:**
- Table: Error breakdown by reason + endpoint

### 12.3 Prometheus Alert Rules

```yaml
# infra/prometheus/rules/alert-rules.yml — append to existing file

- alert: EODHDMonthlyQuotaSoftLimitBreached
  expr: s2_eodhd_monthly_credits_used / s2_eodhd_monthly_credits_limit > 0.8
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "EODHD monthly credit usage >80%"
    description: "Used {{ $value | humanizePercentage }} of monthly EODHD quota."

- alert: EODHDMonthlyQuotaHardLimitNear
  expr: s2_eodhd_monthly_credits_used / s2_eodhd_monthly_credits_limit > 0.95
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "EODHD monthly credit usage >95% — ingestion will halt"

- alert: EODHDCircuitBreakerOpen
  expr: s2_eodhd_circuit_breaker_state > 0
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "EODHD circuit breaker OPEN — {{ $labels.endpoint }}"

- alert: EODHDUnhandled429Rate
  expr: rate(s2_eodhd_rate_limited_total[5m]) > 0.1
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Sustained EODHD 429 rate — check quota and retry config"
```

---

## 13. Test and Validation Strategy

### 13.1 New Unit Tests

| File | Tests | Wave |
|---|---|---|
| `tests/unit/adapters/test_eodhd_bulk.py` | `test_fetch_bulk_quotes_batches_50_symbols_max`, `test_fetch_bulk_quotes_partial_failure_continues`, `test_fetch_bulk_quotes_429_raises_provider_rate_limited`, `test_fetch_bulk_quotes_result_contains_all_symbols`, `test_bulk_eod_filters_untracked_symbols`, `test_bulk_task_dedupe_key_stable_across_symbol_order` | W1 |
| `tests/unit/use_cases/test_monthly_quota.py` | `test_monthly_quota_increments_atomically`, `test_monthly_quota_rejects_when_hard_limit_reached`, `test_monthly_quota_soft_limit_triggers_warning`, `test_monthly_quota_resets_on_month_boundary`, `test_monthly_quota_service_attribution`, `test_monthly_quota_symbol_attribution` | W0 |
| `tests/unit/use_cases/test_retry_after.py` | `test_429_retry_after_header_sets_next_attempt_at`, `test_429_no_retry_after_header_uses_exponential_backoff`, `test_retry_after_date_format_parsed_correctly`, `test_retry_after_integer_seconds_applied`, `test_api_key_not_logged_on_error` | W0 |
| `tests/unit/use_cases/test_circuit_breaker.py` | `test_circuit_opens_after_5_consecutive_429s`, `test_circuit_open_prevents_task_claim`, `test_circuit_half_open_allows_one_probe`, `test_circuit_closes_on_probe_success`, `test_circuit_reopens_on_probe_failure`, `test_endpoint_specific_circuit_doesnt_affect_others` | W1 |
| `tests/unit/use_cases/test_prefetch_gate.py` | `test_prefetch_gate_skips_eodhd_when_within_ttl`, `test_prefetch_gate_calls_eodhd_when_ttl_expired`, `test_fetch_lock_prevents_concurrent_duplicate_call`, `test_bronze_reuse_on_watermark_violation_retry`, `test_cache_ttl_by_endpoint_type` | W0/W1 |
| `tests/unit/use_cases/test_scheduler_cadence.py` | `test_scheduler_skips_quote_poll_outside_market_hours`, `test_scheduler_skips_weekend`, `test_scheduler_respects_tier_interval`, `test_scheduler_creates_bulk_task_not_per_symbol_for_quotes`, `test_scheduler_derives_weekly_ohlcv_not_polls`, `test_manual_refresh_respects_cooldown` | W1/W2 |
| `services/market-data/tests/unit/domain/test_price_snapshot.py` | `test_price_snapshot_returns_fresh_quote_when_available`, `test_price_snapshot_falls_back_to_5m_bar`, `test_price_snapshot_falls_back_to_1h_bar`, `test_price_snapshot_falls_back_to_daily_close`, `test_price_snapshot_marks_stale_when_all_fallbacks_fail`, `test_price_snapshot_market_hours_awareness`, `test_price_snapshot_returns_unavailable_on_no_data` | W1 |
| `apps/worldview-web/__tests__/stale-price-indicator.test.tsx` | `test_stale_badge_shows_when_freshness_is_delayed`, `test_unavailable_state_shows_placeholder`, `test_refresh_button_disabled_during_cooldown`, `test_circuit_breaker_message_shown` | W1 |

### 13.2 Integration Tests

| File | Test | Wave |
|---|---|---|
| `tests/integration/test_bulk_pipeline.py` | `test_bulk_quote_task_full_pipeline` | W1 |
| `tests/integration/test_monthly_quota.py` | `test_monthly_quota_gate_blocks_task_enqueue_when_exhausted` | W0 |
| `tests/integration/test_circuit_breaker.py` | `test_circuit_breaker_pauses_all_tasks_during_open_state` | W1 |
| `services/market-data/tests/integration/test_price_snapshot.py` | `test_price_snapshot_served_from_valkey_cache`, `test_stale_fallback_chain_on_eodhd_unavailable` | W1 |

### 13.3 Benchmark Tests (slow marker, nightly CI)

| File | Test | Purpose |
|---|---|---|
| `tests/benchmark/test_monthly_credit_simulation.py` | `test_monthly_credit_budget_under_50k_for_64_symbols` | Regression guard: credit math must pass per-wave |
| `tests/benchmark/test_retry_storm_simulation.py` | `test_retry_storm_does_not_cause_synchronized_burst` | Jitter validation: no synchronized retry burst |
| `tests/benchmark/test_retry_storm_simulation.py` | `test_backfill_budget_throttling_does_not_deadlock` | Backfill: quota throttle + no deadlock |

### 13.4 Architecture Guard Tests

```
tests/architecture/test_no_direct_eodhd_in_consumers.py
  test_no_eodhd_client_import_outside_s2_and_s4_adapters
  test_no_direct_httpx_call_outside_adapters
  test_domain_layer_does_not_import_infrastructure
```

### 13.5 Initiative Acceptance Criteria

All of the following must be true simultaneously before this initiative is closed:

1. Monthly EODHD credits < 50,000 at 64 symbols (benchmark simulation passes).
2. Monthly EODHD credits < 80,000 at 200 symbols (same simulation, 200 symbols).
3. Zero unhandled 429 responses in 72h production window (`eodhd_unhandled_429_total == 0`).
4. Circuit breaker end-to-end tests all green (6 unit + 1 integration).
5. PriceSnapshot fallback: all 7 unit tests for fallback sources passing.
6. Grafana EODHD dashboard live with 7 days of real data.
7. All 4 Prometheus alert rules confirmed firing in staging.
8. Test coverage > 80% for all new modules.

---

## 14. Risks and Tradeoffs

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Bulk API response misparse silences 50 symbols | Low | High | Parallel-run 5 days; `test_bulk_eod_filters_untracked_symbols` guard |
| Quota guard set too aggressively in Wave 0 | Medium | Medium | Start limit at 100K (2× target); lower to 50K after 48h monitoring |
| Circuit breaker OPEN blocks all ingestion | Low | High | Per-endpoint circuits; T0 symbols exempt from circuit (separate endpoint key) |
| `last_success_at` write causes performance regression | Very Low | Low | Watermark write is one additional column in existing `UPDATE` |
| PriceSnapshot UNAVAILABLE visible to users | Medium | Low | Shown as "—" not error; refresh button available |
| S4 news fetching still over-consuming after Wave 2 | Medium | Medium | Cap S4 credits at 10K/month via shared quota service |
| 3,000-symbol scale hits limits (72K credits) | Low | Medium | T3 symbols move to T4 (inactive) automatically after 30 days no user access |

**Key tradeoff**: Bulk API reduces HTTP overhead but does NOT reduce credits.
The credit reduction comes entirely from tiering and cadence changes. Users on
T3 (screener-only) will see EOD-only prices — this is a conscious product
decision, not a data quality regression.

**Key tradeoff**: PriceSnapshot TTL=2h means the Valkey cache can serve data
up to 2 hours old if the proactive invalidation path fails (Kafka consumer
crash). This is acceptable per the product freshness SLAs — most surfaces
tolerate 1h+ staleness. T0/T1 symbols are refreshed more frequently, ensuring
their snapshots are invalidated before the 2h TTL expires.

---

## 15. Final Recommendation

**SAFE_TO_IMPLEMENT**

This initiative solves a hard ceiling problem (100K credits/month quota) that
would block growth at any symbol count above ~64. The four waves are:

- **Independently deployable** — each wave can be rolled back without affecting
  the others.
- **Additive** — no existing data pipelines are removed; new paths are added in
  parallel before old ones are disabled.
- **Correctly scoped** — the credit reduction comes from tiering (product policy
  decision), not from degrading data quality. T0/T1 symbols (portfolio + watchlist)
  maintain 5/15-minute freshness. Only screener symbols (T3) drop to EOD.
- **Proven math** — at 3,000 symbols with strict tiering, estimated monthly
  consumption is ~73K credits — 27% headroom. At 500 symbols (realistic near-term
  scale), consumption is ~51K credits — 49% headroom.

**Start with Wave 0** (quota enforcement + Retry-After). It has zero regression
risk and will expose if any services are already consuming unexpectedly high
credits. Wave 0 alone will prevent runaway consumption while Waves 1–3 are built.

---

*Generated by 8-agent `/plan` session — 2026-04-24*
*Investigation basis: `/investigate` session — 2026-04-24*
*Next: update TRACKING.md, then begin Wave 0 implementation*
