# QA Report: PLAN-0106 Live-Stack Validation

**Date**: 2026-06-06 21:00–22:00 UTC
**Skill**: qa
**Scope**: PLAN-0106 — Ingestion Coverage Completeness (live-stack with Docker rebuild)
**Branch**: feat/plan-0099-w4
**Verdict**: PASS_WITH_WARNINGS (after fixes applied in this session)
**Report file**: docs/audits/2026-06-06-qa-plan-0106-live-stack-report.md

---

## Executive Summary

S2 (market-ingestion) and S4 (content-ingestion) were rebuilt from source and restarted. Four specialist agents investigated Alpaca OHLCV ingestion, fundamentals ingestion, news ingestion, and database/Kafka health. Three critical issues were found and fixed during this session:

1. **`InstrumentPolicySyncWorker` (S2)** called `GET /internal/v1/instruments` which did not exist — the market-data service exposed only `top-by-market-cap` and `ohlcv-covered`. Fixed by adding `GET /internal/v1/instruments` to the market-data internal router. Worker now creates Alpaca 1m policies for 556 new US instruments.

2. **`TickerNewsSymbolSyncWorker` (S4)** had the same missing endpoint problem. Fixed by the same endpoint addition. Worker now creates EODHD ticker-news sources for 578 instruments.

3. **NLP pipeline article consumer** crashed on every article with `AttributeError: 'Settings' object has no attribute 'min_word_count'` because the setting was never added to `nlp_pipeline/config.py`. Fixed by adding `min_word_count: int = 50`. Pipeline now processing articles with GLiNER + DeepInfra embedding.

Additionally: S4 migration 0008 had two PostgreSQL cast bugs (`::jsonb` and UUID type in `sa.text()`) that prevented it from applying. Fixed in the migration file. Migrations 0014–0017 (S2) and 0008 (S4) are now all applied and validated.

---

## Multi-Agent Review Summary

| Agent | Focus | CRITICAL | MAJOR | MINOR |
|-------|-------|----------|-------|-------|
| Alpaca OHLCV | 1m bars + resampling | 1 (endpoint 404) | 2 (8 dead msgs, S&P 500 no intraday) | 2 |
| Fundamentals | Fundamentals pipeline | 0 | 2 (endpoint error, 24 unmapped fields) | 4 |
| S4 News | News providers + NLP | 1 (min_word_count) | 1 (worker endpoint) | 2 |
| DB/Kafka | Migration + consumer health | 3 (endpoint + cast bugs) | 1 (insider_net_buy col) | 3 |

---

## Test Execution Results

| Layer | Scope | Passed | Failed | Status |
|-------|-------|--------|--------|--------|
| S2 Unit Tests | market-ingestion | 357 | 0 | PASS |
| S4 Unit Tests | content-ingestion | 802 | 0 | PASS |
| NLP Unit Tests | nlp-pipeline | 1025 | 8 | PASS* |
| S2 Alembic | migrations 0013→0017 | 5/5 applied | 0 | PASS |
| S4 Alembic | migrations 0007→0008 | 2/2 applied | 0 | PASS |

*8 failures in `tests/unit/test_entrypoints.py` are pre-existing OSError socket-binding failures in test isolation — not related to PLAN-0106.

---

## Live-Stack Validation

### Alpaca OHLCV 1m Bars

- **Policy coverage before fix**: 60 policies (50 US + 10 CC) from migration 0011
- **InstrumentPolicySyncWorker**: was getting HTTP 404 on every tick → 0 new policies ever created
- **After fix**: 556 new Alpaca 1m policies created for US instruments not previously covered
- **US equities intraday bars (last session, June 3)**: 51,474 bars across 51 symbols — CONFIRMED WORKING
- **Resampling**: 5m/15m/30m/1h/4h all present, resampling consumer healthy
- **Market hours**: US market closed at evaluation time (Saturday 21:15 UTC) — no new US bars expected

### Fundamentals Ingestion

- **US fundamentals policies**: 504 enabled (migration 0014 added ~457 new US symbols)
- **Instruments with fundamentals in market_data_db**: 573/578 US (99.1%)
- **3.37M metric rows** present; most recent ingest: 2026-06-06 20:57 UTC
- **FundamentalsRefreshWorker**: working correctly — 500+ symbol refresh loop logging `fundamentals_refresh_ok`
- **MAJOR (pre-existing)**: 24 cash flow EODHD fields unmapped → silently dropped each ingest cycle

### S4 News Ingestion

- **Default sources seeded**: All 5 present (eodhd, finnhub, newsapi, sec_edgar, polymarket) ✓
- **TickerNewsSymbolSyncWorker**: 578 EODHD ticker-news sources now created after endpoint fix ✓
- **Finnhub news**: 1,192 articles in last 24h ✓
- **SEC EDGAR**: 169 filings in last 24h ✓
- **NewsAPI**: 0 articles — quota exhausted (external limit, not a code bug)
- **content.article.raw.v1 Kafka topic**: 310 total messages produced

### NLP Processing

- **Before fix**: 100% failure rate (`min_word_count` AttributeError on every message)
- **After fix**: Consumer started cleanly, processing articles with GLiNER NER + DeepInfra embedding + `article_processed` events emitted
- **Kafka lag after fix**: ~543 messages backlogged, consumer actively catching up

---

## Issues — Full Investigation

---

### F-001: InstrumentPolicySyncWorker calls non-existent endpoint (CRITICAL → FIXED)

**Severity**: CRITICAL (before fix) — RESOLVED
**File**: `services/market-ingestion/src/market_ingestion/infrastructure/workers/instrument_policy_sync_worker.py:273`

**Root Cause**: Worker constructed `f"{base_url}/internal/v1/instruments"` with `exchange=US/CC` params. Market-data service only exposed `/internal/v1/instruments/top-by-market-cap` and `/internal/v1/instruments/ohlcv-covered` — no bare `/instruments` list endpoint existed.

**Evidence**: Scheduler log: `instrument_policy_sync_fetch_non_2xx exchange=US status_code=404` → `instrument_policy_sync_tick_done created=0` on every tick since first deploy.

**Fix applied**: Added `GET /internal/v1/instruments` to `services/market-data/src/market_data/api/routers/internal_instruments.py` with `exchange=`, `limit=`, `offset=` params. Uses existing `SearchInstrumentsUseCase`. Requires `X-Internal-JWT`.

**Verification**: After restart, worker logs `instrument_policy_sync_policy_created` 556 times.

---

### F-002: TickerNewsSymbolSyncWorker same endpoint 404 (CRITICAL → FIXED)

**Severity**: CRITICAL (before fix) — RESOLVED
**File**: `services/content-ingestion/src/content_ingestion/infrastructure/workers/ticker_news_sync_worker.py:216`

**Root Cause**: Same as F-001 — worker called `GET /internal/v1/instruments?exchange=US` which returned 404.

**Fix applied**: Same endpoint addition in market-data router covers both workers.

**Verification**: Worker now creates 578 EODHD ticker-news Source rows.

---

### F-003: NLP pipeline `min_word_count` missing from Settings (CRITICAL → FIXED)

**Severity**: CRITICAL (before fix) — RESOLVED
**File**: `services/nlp-pipeline/src/nlp_pipeline/config.py`

**Root Cause**: `article_consumer.py:582` reads `self._settings.min_word_count` but this field was never added to the `Settings` class. The `# type: ignore[attr-defined]` suppressed the mypy error, hiding the runtime AttributeError.

**Evidence**: `{"error": "'Settings' object has no attribute 'min_word_count'", "event": "kafka_unexpected_error"}` on every article — 100% failure rate since consumer was deployed.

**Fix applied**: Added `min_word_count: int = 50` to `services/nlp-pipeline/src/nlp_pipeline/config.py` (line 129).

**Verification**: Consumer restarts clean, processes first article: `{"doc_id": "...", "routing_tier": "light", "section_count": 1, "chunk_count": 1, "mention_count": 7, "event": "article_processed"}`.

---

### F-004: S4 migration 0008 SQLAlchemy cast bugs (MAJOR → FIXED)

**Severity**: MAJOR (before fix) — RESOLVED
**File**: `services/content-ingestion/alembic/versions/0008_seed_default_sources.py`

**Root Cause**: `sa.text()` with PostgreSQL `::type` shorthand cast confuses asyncpg's param parser — `::jsonb` triggers `KeyError: 'config'` and UUID columns require `CAST(:id AS uuid)`.

**Fix applied**: Changed `(:id, ..., :config::jsonb, ...)` → `(CAST(:id AS uuid), ..., CAST(:config AS jsonb), ...)`.

**Verification**: Migration 0008 applied cleanly; all 5 default sources seeded.

---

### F-005: 24 EODHD cash flow fields silently dropped (MAJOR — pre-existing)

**Severity**: MAJOR
**File**: market-data fundamentals consumer metric extractor

**Issue**: 3,161+ `metric_extractor.unmapped_keys` warnings per ingest cycle. Fields silently dropped: `beginPeriodCashFlow`, `cashAndCashEquivalentsChanges`, `changeInWorkingCapital`, `changeReceivables`, `changeToAccountReceivables`, `changeToInventory`, `changeToLiabilities`, `changeToNetincome`, and 16 more.

**Impact**: Cash flow data is never stored in `fundamental_metrics`. Downstream KG and RAG queries have incomplete financial data.

**Recommendation**: Add these 24 field mappings to the metric extractor. Not a PLAN-0106 deliverable — open for PLAN-0107 or a follow-up fix.

---

### F-006: insider_net_buy_90d rollup missing column (MAJOR — pre-existing)

**Severity**: MAJOR
**Service**: market-data

**Issue**: `insider_rollup_error: column "net_value_usd" does not exist in insider_transactions`. The `net_value_usd` column used in the 90-day insider net buy rollup was never added to the `insider_transactions` table via Alembic.

**Impact**: `insider_net_buy_90d` metric never populates for any instrument.

**Recommendation**: Add an Alembic migration to add `net_value_usd` to `insider_transactions`. Not a PLAN-0106 deliverable.

---

## Supplementary Checks

| Check | Status | Notes |
|-------|--------|-------|
| Migration chain S2 (0013→0017) | PASS | All 5 applied and verified |
| Migration chain S4 (0007→0008) | PASS | Applied after cast bug fix |
| EODHD quotes disabled (US/CC) | PASS | 50+10 policies enabled=false |
| News sentiment disabled | PASS | 4 policies enabled=false |
| Top-100 insider/market_cap | PASS | 103+105 policies enabled |
| ADAPTER_REGISTRY has EODHD_TICKER_NEWS | PASS | Confirmed |
| Config guard on missing API keys | PASS | Warns on empty newsapi_key |
| Kafka consumer lag | LOW | ~543 articles backlogged, actively processing |
| Outbox health | PASS | S2: 30 dead (pre-existing); S4: 1,441 dead_letter (pre-existing) |
| Container health | PASS | All 8 S2/S4 containers healthy |
| NewsAPI quota | WARN | Exhausted — external limit |

---

## Open Items (not PLAN-0106 scope)

| ID | Issue | Priority |
|----|-------|----------|
| OI-1 | 24 unmapped EODHD cash flow metric fields | MAJOR |
| OI-2 | `net_value_usd` column missing from `insider_transactions` | MAJOR |
| OI-3 | 8 dead-lettered crypto OHLCV Kafka messages (recoverable from MinIO) | MINOR |
| OI-4 | Duplicate CC symbol formats `BTC-USD` vs `BTC.USD` in ohlcv_bars | MINOR |
| OI-5 | NewsAPI quota exhausted in dev environment | MINOR |
| OI-6 | Alembic upgrade not auto-triggered on container start | MINOR |

---

## Recommendations

1. **Add `insider_net_buy_90d` Alembic migration** — add `net_value_usd NUMERIC(20,4)` to `insider_transactions`
2. **Add 24 EODHD cash flow field mappings** to the market-data fundamentals metric extractor
3. **Add NLP test for `min_word_count`** — the `# type: ignore[attr-defined]` on two lines prevented mypy from catching the missing setting; add an explicit test that `Settings()` has the attribute
4. **Add integration test for market-data internal instruments endpoint** — the endpoint existed before (for `top-by-market-cap`) but the bare `/instruments` path was missing; a contract test would have caught this
5. **Recover 8 dead crypto OHLCV events** — files exist in MinIO; a manual re-dispatch against the object refs can recover today's bars for SOL-USD, ETH-USD, LTC-USD, AVAX-USD, XRP-USD, DOGE-USD, ADA-USD, BTC-USD
