# PLAN-EODHD-DEDUP: S2/S7 EODHD API Deduplication Architecture

**Date**: 2026-04-19
**Author**: Claude Agent (Principal Architect investigation)
**Status**: DRAFT — awaiting decision
**Depends on**: PLAN-0018 (complete), audit report `docs/audits/2026-04-19-eodhd-api-optimization-report.md`

---

## 1. Current State Analysis

### 1.1 S2 (Market Ingestion) EODHD Usage

S2 is the platform's canonical market data ingestion service. It uses a **polling policy + task queue** architecture:

1. **SchedulerProcess** evaluates `PollingPolicy` rows every tick (default 60s).
2. When a policy is due, it creates an `IngestionTask` and enqueues it.
3. **WorkerProcess** claims tasks, executes a 5-step pipeline:
   - Fetch raw data from EODHD via `EODHDProviderAdapter`
   - Store raw bytes to MinIO bronze bucket
   - Canonicalize via `DefaultCanonicalSerializer`
   - Store canonical JSONL to MinIO canonical bucket
   - Short DB transaction: advance watermark, add to outbox, succeed task
4. **OutboxDispatcher** publishes `market.dataset.fetched` Kafka events (Avro, claim-check pattern).

**EODHD endpoints called by S2** (via `EODHDProviderAdapter`):

| Endpoint | Method | DatasetType enum | Frequency | API calls/req |
|----------|--------|-----------------|-----------|---------------|
| `GET /eod/{ticker}` | `fetch_ohlcv()` | `OHLCV` | 6h/12h/24h per ticker | 1 |
| `GET /real-time/{ticker}` | `fetch_quotes()` | `QUOTES` | 5min per ticker | 1 |
| `GET /fundamentals/{ticker}` | `fetch_fundamentals()` | `FUNDAMENTALS` | 24h per ticker | 10 |
| `GET /intraday/{ticker}` | `fetch_intraday()` | `OHLCV` | 1h/5m per ticker | 5 |
| `GET /calendar/earnings` | `fetch_earnings_calendar()` | `EARNINGS_CALENDAR` | 24h | 1 |
| `GET /economic-events` | `fetch_economic_events()` | `ECONOMIC_EVENTS` | 24h per country | 1 |
| `GET /macro-indicator/{country}` | `fetch_macro_indicator()` | `MACRO_INDICATOR` | Weekly per indicator | 10 |
| `GET /news` | `fetch_news_sentiment()` | `NEWS_SENTIMENT` | 6h per ticker | 5 |
| `GET /insider-transactions` | `fetch_insider_transactions()` | `INSIDER_TRANSACTIONS` | Daily per ticker | 10 |
| `GET /ust/{series}` | `fetch_yield_curve()` | `YIELD_CURVE` | Daily | 1 |
| `GET /historical-market-cap/{ticker}` | `fetch_historical_market_cap()` | `MARKET_CAP` | Weekly | 1 |

**S2 storage flow**: Raw JSON -> MinIO `market-bronze` -> canonical JSONL -> MinIO `market-canonical` -> `market.dataset.fetched` Kafka event (Avro, claim-check pointers to MinIO objects).

**Key observation**: S2 already fetches economic events, macro indicators, and insider transactions. It stores raw + canonical data in MinIO and publishes `market.dataset.fetched` events for all dataset types. The `dataset_type` field in the Avro schema distinguishes the payload type.

### 1.2 S7 (Knowledge Graph) EODHD Usage

S7 has its own independent `EodhDClient` class (`infrastructure/eodhd/client.py`) that calls EODHD directly. Three APScheduler cron-scheduled workers use this client:

| Worker | Class | Cron Schedule | Endpoint | Processing |
|--------|-------|--------------|----------|------------|
| 13D-6 | `EconomicEventsWorker` | Daily 06:00 UTC | `GET /economic-events` per country | Upserts `temporal_events` (MACRO, NATIONAL), links `entity_event_exposures` |
| 13D-7 | `MacroIndicatorWorker` | Sunday 03:00 UTC | `GET /macro-indicator/{ISO3}` per indicator | Patches `canonical_entities.metadata["macro_indicators"]`, produces `entity.dirtied.v1` |
| 13D-8 | `InsiderTransactionsWorker` | Monday 02:00 UTC | `GET /insider-transactions?code={ticker}.US` per instrument | Creates `has_executive` relations (company -> person entity) |

**S7 EODHD client**: Thin wrapper (`EodhDClient`) with error-tolerant `_get_list()` helper. Returns empty lists on HTTP errors instead of raising exceptions. No MinIO storage, no Kafka events -- data goes directly into `intelligence_db`.

**S7 config**: `KNOWLEDGE_GRAPH_EODHD_API_KEY` (separate from S2's key), `KNOWLEDGE_GRAPH_EODHD_BASE_URL`.

### 1.3 Data Flow Comparison

**Economic Events**:
- S2: `fetch_economic_events()` -> MinIO bronze/canonical -> `market.dataset.fetched` (dataset_type=economic_events)
- S7: `get_economic_events()` -> upsert `temporal_events` + `entity_event_exposures` in `intelligence_db`
- **Overlap**: Both call `GET /economic-events` for partially overlapping country sets. S2 fetches 3 countries, S7 fetches 6.

**Macro Indicators**:
- S2: `fetch_macro_indicator()` -> MinIO bronze/canonical -> `market.dataset.fetched` (dataset_type=macro_indicator)
- S7: `get_macro_indicator()` -> patches `canonical_entities.metadata["macro_indicators"]`, produces `entity.dirtied.v1`
- **Overlap**: S2 fetches 5 indicators x 2 regions (10 calls); S7 fetches 6 indicators x 5 countries (30 calls). Different indicator sets and different country coverage.

**Insider Transactions**:
- S2: `fetch_insider_transactions()` -> MinIO bronze/canonical -> `market.dataset.fetched` (dataset_type=insider_transactions)
- S7: `get_insider_transactions()` -> creates `has_executive` relations, deduplicates officers, stores insider sentiment direction
- **Overlap**: S2 fetches daily for 3 tickers; S7 fetches weekly for ALL US instruments. S7's coverage is a superset.

---

## 2. Data Overlap Matrix

| EODHD Endpoint | S2 Calls | S7 Calls | S2 Frequency | S7 Frequency | API Calls/Req | S2 Countries/Tickers | S7 Countries/Tickers | Overlap Type |
|---------------|----------|----------|-------------|-------------|---------------|---------------------|---------------------|-------------|
| `GET /economic-events` | Yes | Yes | Daily | Daily 06:00 UTC | 1 | 3 countries (USA, DEU, GBR) | 6 countries (US, DE, GB, JP, CN, EU) | **Partial** (S7 is superset) |
| `GET /macro-indicator/{ISO3}` | Yes | Yes | Weekly | Weekly Sun 03:00 | 10 | 5 indicators x 2 regions = 10 | 6 indicators x 5 countries = 30 | **Partial** (different sets) |
| `GET /insider-transactions` | Yes | Yes | Daily (3 tickers) | Weekly Mon 02:00 (all US) | 10 | 3 specific tickers | All US instruments (~N) | **S7 superset** |

### Daily API Call Cost of Overlap

| Endpoint | S2 Daily Calls | S7 Daily Calls (amortized) | Combined | Deduped (S2 only) | Savings |
|----------|---------------|---------------------------|----------|-------------------|---------|
| Economic events | 3 | 6 | 9 | 6 (expand S2 to S7 countries) | 3 |
| Macro indicators | ~14/day (100/wk) | ~43/day (300/wk) | ~57/day | ~43/day (expand S2) | ~14 |
| Insider transactions | 30 | variable (N*10/7) | 30 + N*10/7 | N*10/7 | 30 |
| **TOTAL** | ~47 | ~49 + N*10/7 | ~96 + N*10/7 | ~49 + N*10/7 | ~47 |

At current seed scale (6 tickers, ~5 US instruments), the overlap is modest (~47 calls/day). However, the structural issue grows with the ticker universe: at 100 US instruments, S7 insider transactions alone contribute ~143 calls/day.

---

## 3. Option Analysis

### Option A: S2 as Single Source + Kafka Events

**Description**: S2 becomes the sole EODHD caller for all three overlapping endpoints. S7 deletes its `EodhDClient` and the three EODHD workers (13D-6, 13D-7, 13D-8). Instead, S7 consumes `market.dataset.fetched` events (which S2 already emits) and processes the data from the MinIO claim-check payload.

**Implementation**:
1. Expand S2 polling policies to cover S7's country/indicator sets:
   - Economic events: add JP, CN, EU countries to S2 polling
   - Macro indicators: add missing indicators and countries
   - Insider transactions: S2 already polls, but needs to expand to cover all US instruments (or S7 handles instrument discovery and triggers S2 via REST)
2. Create three new S7 Kafka consumers (or extend existing `FundamentalsDescriptionConsumer` pattern):
   - `EconomicEventsConsumer` subscribing to `market.dataset.fetched` WHERE `dataset_type=economic_events`
   - `MacroIndicatorConsumer` subscribing to `market.dataset.fetched` WHERE `dataset_type=macro_indicator`
   - `InsiderTransactionsConsumer` subscribing to `market.dataset.fetched` WHERE `dataset_type=insider_transactions`
3. Each consumer downloads the MinIO claim-check payload and processes it using the existing worker logic (upsert temporal events, patch metadata, create relations).
4. Delete `services/knowledge-graph/src/knowledge_graph/infrastructure/eodhd/` entirely.
5. Remove EODHD worker registration from `build_workers()` and the 3 cron jobs from `KnowledgeGraphScheduler`.
6. Remove `KNOWLEDGE_GRAPH_EODHD_API_KEY` and `KNOWLEDGE_GRAPH_EODHD_BASE_URL` from S7 config.

**LOC estimate**: ~800 lines changed (3 new consumers ~150 each, delete ~250 lines of EODHD client + workers, config changes ~50).

**Pros**:
- Eliminates duplicate API calls entirely
- Single API key management (S2 only)
- Single budget tracking point (S2's `ProviderBudget` entity)
- Leverages existing MinIO bronze/canonical storage (auditability)
- Leverages existing `market.dataset.fetched` Avro schema (no new topics needed)
- S7 gets data from MinIO (already proven pattern: `FundamentalsDescriptionConsumer` does this today)
- Aligns with MASTER_PLAN data flow: `EODHD -> S2 -> Kafka -> downstream`

**Cons**:
- S2 needs to know about S7's country/indicator/ticker requirements (coupling)
- Insider transactions at scale: S2 would need to poll ALL US instruments (S7 currently discovers these from `canonical_entities`). S2 lacks access to `intelligence_db` (R7). Requires either: (a) S7 sends instrument lists to S2 via REST, or (b) S2 maintains its own instrument discovery from `market.instrument.created` events.
- Adds latency: S7 processing is now async via Kafka instead of direct API call
- S2's `ExecuteTaskUseCase._canonicalize()` currently has no canonicalization logic for economic events, macro indicators, or insider transactions -- it would need to handle raw JSON passthrough for these dataset types

**Impact on existing tests**: Medium. S2 tests unaffected (new polling policies only). S7 test suite needs updates: ~50 tests across the 3 worker test files need to be rewritten as consumer tests. Existing consumer test patterns (`FundamentalsDescriptionConsumer`) provide templates.

**Migration risk**: Medium. The main risk is the instrument discovery gap for insider transactions. S2 does not know which instruments to poll for insider transactions because that knowledge lives in S7's `canonical_entities` table. Solving this requires either a REST endpoint on S7 or S2 maintaining its own instrument catalog.

**API budget savings**: 100% of duplicate calls eliminated. S7's 6 economic event calls become 3 additional S2 calls (net +3 for S2, -6 for S7). Macro indicators: S7's 300/week becomes 0 for S7 (S2 absorbs). Insider: S2 daily polling removed (S7 handles weekly via S2 data).

**Architectural alignment**: Strong. Matches the platform's canonical data flow (`EODHD -> S2 -> Kafka -> consumers`). Follows R7 (no cross-service DB), R8 (outbox pattern), R12 (claim-check). S7 already consumes `market.dataset.fetched` for fundamentals.

---

### Option B: Shared Valkey Cache Layer

**Description**: Both S2 and S7 check a Valkey key before calling EODHD. The first caller stores the raw response with a TTL. The second caller reads from cache.

**Implementation**:
1. Define a shared Valkey key convention: `eodhd:{endpoint}:{params_hash}` (e.g., `eodhd:economic-events:US:2026-04-19`)
2. Add a `CachedEodhDClient` wrapper in `libs/common/` or a new shared lib
3. Both S2's `EODHDProviderAdapter._get()` and S7's `EodhDClient._get_list()` check Valkey before HTTP

**LOC estimate**: ~300 lines (shared cache wrapper ~100, integration in S2 ~100, integration in S7 ~100).

**Pros**:
- Minimal code changes
- No service coupling -- each service remains independent
- No new Kafka topics or consumers
- TTL-based cache invalidation is simple

**Cons**:
- Introduces shared mutable state between services (Valkey key namespace coupling)
- Race condition: if both services start at the same instant, both miss cache and call EODHD
- Cache key design is fragile -- different parameter formats between S2 and S7 (S2 uses ISO-2 + date ranges, S7 uses ISO-2 + date objects)
- Does not reduce S7's EODHD API key dependency -- S7 still needs its own key as fallback
- Does not centralize budget tracking -- two services consuming from the same daily budget independently
- **Violates the spirit of R7**: shared Valkey state is a form of cross-service data coupling
- S2 returns `bytes` (raw HTTP response); S7 expects `list[dict]` (parsed JSON) -- cache format mismatch requires double serialization or a shared envelope format
- No auditability: cached responses are ephemeral (no MinIO storage for replay)

**Impact on existing tests**: Low. Existing tests continue to work with mock clients. New tests needed for the cache layer.

**Migration risk**: Low initial risk, but ongoing maintenance burden. Cache TTL tuning is non-trivial for data that updates at different cadences (economic events: daily, macro: annually, insider: filed within 2 business days).

**API budget savings**: ~50% of overlap (avoids second call when cache hits). Cache misses still result in duplicate calls. At best ~23 calls/day saved.

**Architectural alignment**: Weak. Shared Valkey state creates implicit coupling. Does not fit the event-driven architecture pattern. The MASTER_PLAN explicitly routes structured data through `S2 -> Kafka`, not through shared caches.

---

### Option C: Dedicated Data Fetcher Service

**Description**: Create a new lightweight service (or a `libs/eodhd-client` shared library) that handles ALL EODHD API calls. S2 and S7 delegate to this service via REST or Kafka.

**Implementation**:
1. New service: `services/eodhd-gateway/` with a simple REST API: `POST /fetch/economic-events`, `POST /fetch/macro-indicator`, etc.
2. Shared MinIO storage for all raw responses
3. Kafka events for downstream consumers
4. Centralized API key, budget tracking, rate limiting

**LOC estimate**: ~1,500 lines (new service scaffold ~500, REST API ~200, EODHD client ~300, MinIO storage ~200, config/tests ~300).

**Pros**:
- Clean separation of concerns (single responsibility: EODHD API management)
- Centralized API key, budget, rate limiting
- Single point of observability for EODHD API health
- Other future services can use it without adding EODHD dependencies

**Cons**:
- **Violates R16**: adding a new microservice requires an ADR and strong justification
- Significant operational overhead (new Docker container, health checks, monitoring, deployment)
- Thesis scope: another service to maintain for marginal benefit
- Over-engineering for the current scale (6 tickers, ~47 calls/day overlap)
- S2 already IS the canonical data ingestion service -- this duplicates S2's mission
- Additional network hop for every EODHD request (latency)

**Impact on existing tests**: High. Both S2 and S7 need to be refactored to call the new service instead of EODHD directly.

**Migration risk**: High. Introducing a new service in the critical data path creates a new single point of failure. If the EODHD gateway is down, both S2 and S7 are blocked.

**API budget savings**: 100% of duplicate calls eliminated (same as Option A).

**Architectural alignment**: Poor for thesis scope. The MASTER_PLAN already designates S2 as the market data ingestion layer. A separate EODHD gateway fragments that responsibility.

---

### Option D: S7 Consumes Existing S2 Kafka Topics (Recommended)

**Description**: S7 stops calling EODHD directly for the three overlapping endpoints and instead consumes the `market.dataset.fetched` events that S2 already publishes. S2's polling policies are expanded to cover S7's data requirements. S7 reuses the processing logic from its existing workers but rewires the data source from HTTP to Kafka.

This is a refined version of Option A, with a specific solution for the instrument discovery gap.

**Implementation** (6 steps):

**Step 1**: Expand S2 polling policies (migration seed data):
- Add economic events policies for countries JP, CN, EU (S2 currently covers USA, DEU, GBR)
- Add macro indicator policies: ensure 6 indicators x 5 countries = 30 policies (currently S2 has 5 indicators x 2 regions = 10)
- Insider transactions: keep S7's weekly schedule but route through S2 (see Step 3)

**Step 2**: Ensure S2's `ExecuteTaskUseCase._canonicalize()` handles these dataset types properly. Currently the method only has canonicalization paths for OHLCV, QUOTES, and FUNDAMENTALS. For the three new types, implement a "raw passthrough" canonical serializer that wraps the raw JSON response in a canonical envelope (adding `symbol`, `source`, `dataset_type` metadata) so it is self-describing when S7 downloads from MinIO.

**Step 3**: Instrument-triggered insider transactions via Kafka:
- S2 already consumes `market.instrument.created` events (the topic exists). Wire S2 to create insider transaction polling policies dynamically when new US instruments are discovered.
- Alternatively, S7 publishes a lightweight `graph.instrument.ticker.v1` Kafka event listing US tickers, which S2 consumes to update its insider transaction polling policies. This avoids R7 violations.
- **Simplest approach**: S2 already has insider transaction polling policies for specific tickers. Simply expand the seed to include all initially known tickers, and add a REST endpoint `POST /internal/v1/policies` on S2 that S9 or S7 can call to register new tickers.

**Step 4**: Create three new S7 consumers, following the proven `FundamentalsDescriptionConsumer` pattern:

```
EconomicEventsDatasetConsumer(BaseKafkaConsumer):
    topic: market.dataset.fetched
    group_id: kg-economic-events-dataset-group
    filter: dataset_type == "economic_events"
    processing: download MinIO -> parse JSON -> reuse EconomicEventsWorker._upsert_event() logic

MacroIndicatorDatasetConsumer(BaseKafkaConsumer):
    topic: market.dataset.fetched
    group_id: kg-macro-indicator-dataset-group
    filter: dataset_type == "macro_indicator"
    processing: download MinIO -> parse JSON -> reuse MacroIndicatorWorker._process_country() logic

InsiderTransactionsDatasetConsumer(BaseKafkaConsumer):
    topic: market.dataset.fetched
    group_id: kg-insider-transactions-dataset-group
    filter: dataset_type == "insider_transactions"
    processing: download MinIO -> parse JSON -> reuse InsiderTransactionsWorker._process_instrument() logic
```

**Step 5**: Deprecate and remove S7's direct EODHD usage:
- Delete `services/knowledge-graph/src/knowledge_graph/infrastructure/eodhd/` (client.py, __init__.py)
- Remove the 3 EODHD cron jobs from `KnowledgeGraphScheduler._register_jobs()`
- Remove EODHD worker instantiation from `build_workers()`
- Remove `eodhd_api_key`, `eodhd_base_url` from S7 config
- The worker files (`economic_events_worker.py`, `macro_indicator_worker.py`, `insider_transactions_worker.py`) can be refactored: keep the processing logic as pure functions, move the EODHD-specific wiring to the new consumers

**Step 6**: Update docs:
- `services/knowledge-graph/.claude-context.md`: remove EODHD worker references, add new consumer references
- `docs/services/knowledge-graph.md`: update process topology
- `docs/MASTER_PLAN.md`: update Kafka flow diagram

**LOC estimate**: ~700 lines changed.
- 3 new consumers: ~150 lines each = 450
- S2 canonical passthrough: ~50 lines
- S2 polling policy expansion: ~30 lines (seed migration)
- S7 deletions: ~400 lines removed (EodhDClient + 3 workers)
- Config/doc updates: ~100 lines
- Net: approximately -100 lines (reduction)

**Pros**:
- Eliminates 100% of duplicate EODHD API calls
- Single API key management (S2 only)
- Centralized budget tracking (S2's `ProviderBudget`)
- Raw data preserved in MinIO (auditability, replay capability)
- Follows proven pattern: S7 already consumes `market.dataset.fetched` for fundamentals
- No new Kafka topics needed (reuses existing `market.dataset.fetched` with filter on `dataset_type`)
- No new services (R16 compliance)
- Aligns perfectly with MASTER_PLAN: `EODHD -> S2 -> Kafka -> S7`
- S7 becomes a pure consumer of canonical data -- simpler, fewer external dependencies, easier to test

**Cons**:
- S2 polling policies need to cover S7's data requirements (manageable via seed migration)
- Adds ~200ms latency (Kafka propagation) compared to direct API calls -- acceptable since these are background enrichment jobs, not user-facing
- S2's `_canonicalize()` needs 3 new dataset type handlers (passthrough serializers)
- Insider transaction instrument discovery requires either (a) expanded seed, (b) REST-triggered policy creation, or (c) `market.instrument.created` consumption in S2

**Impact on existing tests**:
- S2: Low. New canonicalization paths need unit tests (~10 new tests). Polling policy seed changes are covered by migration tests.
- S7: Medium. ~30-50 existing worker tests need refactoring. The worker business logic (upsert, dedup, relation creation) stays the same -- only the data source changes from HTTP to Kafka/MinIO. New consumer tests (~15 per consumer = 45 total) follow `FundamentalsDescriptionConsumer` patterns.

**Migration risk**: Low-Medium.
- The processing logic stays identical (same upsert, same dedup, same relation creation)
- Consumers can be deployed alongside existing workers initially (dual-write validation)
- Feature flag: `KNOWLEDGE_GRAPH_EODHD_WORKERS_ENABLED=true/false` allows gradual cutover
- Rollback: re-enable workers and EODHD key in S7 config

**API budget savings**: 100% of S7's EODHD calls eliminated.
- Economic events: -6 calls/day (S7's 6 countries) -> S2 absorbs +3 (only 3 new countries) = net -3
- Macro indicators: -300 calls/week (S7's 30 indicator-country pairs) -> S2 absorbs +200 (20 new pairs) = net -100/week
- Insider transactions: variable but always net reduction since S7 no longer needs its own API key
- Total: ~47-100+ calls/day saved (grows with ticker universe)

**Architectural alignment**: Excellent. This is the canonical worldview pattern. S2 is the structured data ingestion layer; S7 is the knowledge graph builder. Data flows through Kafka, not direct API calls. S7 never talks to external APIs (only Gemini for descriptions, which is a different concern routed through `libs/ml-clients`).

---

## 4. Option Comparison Summary

| Criterion | Option A | Option B | Option C | Option D |
|-----------|----------|----------|----------|----------|
| API budget savings | 100% | ~50% | 100% | 100% |
| Implementation complexity | Medium | Low | High | Medium |
| LOC estimate | ~800 | ~300 | ~1,500 | ~700 |
| Test impact | Medium | Low | High | Medium |
| Migration risk | Medium | Low | High | Low-Medium |
| Architectural alignment | Strong | Weak | Poor | Excellent |
| New services needed | 0 | 0 | 1 | 0 |
| New Kafka topics needed | 0 | 0 | 1+ | 0 |
| Centralized budget | Yes | No | Yes | Yes |
| Auditability (MinIO) | Yes | No | Yes | Yes |
| Operational overhead | Low | Low | High | Low |

---

## 5. Recommended Architecture: Option D

**Option D (S7 Consumes Existing S2 Kafka Topics)** is the recommended approach because:

1. **It is the natural evolution of the existing architecture**. S7 already consumes `market.dataset.fetched` for fundamentals via `FundamentalsDescriptionConsumer`. Extending this pattern to economic events, macro indicators, and insider transactions is a proven, low-risk change.

2. **It eliminates 100% of duplicate calls** with no new infrastructure (no new services, no new Kafka topics, no shared caches).

3. **It centralizes API key and budget management** in S2, which already has the `ProviderBudget` entity, adaptive polling, and rate limit handling.

4. **It follows the MASTER_PLAN data flow** (`EODHD -> S2 -> Kafka -> S7`), which is the canonical pattern for all structured data in the platform.

5. **It simplifies S7** by removing its direct EODHD dependency. S7 becomes a pure event consumer and graph builder, with no external HTTP dependencies except Gemini (for descriptions, via `libs/ml-clients`).

---

## 6. Migration Plan

### Wave 1: S2 Canonical Passthrough (prerequisite)

**Goal**: Ensure S2 can store and emit economic events, macro indicators, and insider transactions data through its full pipeline.

**Tasks**:
1. Add passthrough canonicalization in `ExecuteTaskUseCase._canonicalize()` for `ECONOMIC_EVENTS`, `MACRO_INDICATOR`, and `INSIDER_TRANSACTIONS` dataset types. These are currently handled in `_fetch()` but the canonical serializer only supports OHLCV, QUOTES, and FUNDAMENTALS.
2. The passthrough format: wrap raw JSON in a canonical envelope `{"dataset_type": "...", "symbol": "...", "source": "eodhd", "payload": <raw_json>, "fetched_at": "..."}` as a single NDJSON line.
3. Add unit tests for the new canonicalization paths.
4. **Validation**: Run existing S2 test suite + verify `market.dataset.fetched` events are emitted for all 3 dataset types using integration tests.

**Files changed**:
- `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/canonical.py`
- `services/market-ingestion/tests/unit/test_execute_task.py` (new tests)

### Wave 2: S2 Polling Policy Expansion

**Goal**: S2 covers all data requirements that S7 currently fetches directly.

**Tasks**:
1. Create Alembic migration with new polling policies:
   - Economic events: add countries `JP`, `CN`, `EU` (S2 currently has `USA`, `DEU`, `GBR` -- these are set via the `country` field in the task symbol, e.g., `EVENTS.JP`)
   - Macro indicators: expand to 6 indicators x 5 countries = 30 policies (currently 5x2=10)
   - Insider transactions: expand to cover all initially seeded US tickers (current 3 + any new ones)
2. Align S2's economic event schedule with S7's: daily, target around 06:00 UTC.
3. Align S2's macro indicator schedule: weekly, Sunday.
4. Align S2's insider transaction schedule: weekly, Monday.
5. **Validation**: Observe `market.dataset.fetched` events in Kafka UI for all new dataset type + country/indicator combinations.

**Files changed**:
- `services/market-ingestion/alembic/versions/NNNN_expand_eodhd_policies.py` (new migration)

### Wave 3: S7 New Consumers

**Goal**: S7 processes EODHD data from Kafka instead of direct API calls.

**Tasks**:
1. Create `EconomicEventsDatasetConsumer` in `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/`:
   - Subscribes to `market.dataset.fetched`, filters on `dataset_type == "economic_events"`
   - Downloads MinIO payload via claim-check
   - Reuses parsing + upsert logic from `EconomicEventsWorker._upsert_event()`
   - Standalone entry point: `economic_events_dataset_consumer_main.py`
2. Create `MacroIndicatorDatasetConsumer`:
   - Subscribes to `market.dataset.fetched`, filters on `dataset_type == "macro_indicator"`
   - Downloads MinIO payload via claim-check
   - Reuses hash comparison + metadata patch logic from `MacroIndicatorWorker._process_country()`
   - Standalone entry point: `macro_indicator_dataset_consumer_main.py`
3. Create `InsiderTransactionsDatasetConsumer`:
   - Subscribes to `market.dataset.fetched`, filters on `dataset_type == "insider_transactions"`
   - Downloads MinIO payload via claim-check
   - Reuses officer dedup + relation upsert logic from `InsiderTransactionsWorker._process_instrument()`
   - Standalone entry point: `insider_transactions_dataset_consumer_main.py`
4. All consumers extend `BaseKafkaConsumer` (R20), implement `is_duplicate()` via Valkey (BP-124 pattern), and use `_NoOpUoW` or a real UoW as appropriate.
5. Unit tests for each consumer (~15 tests each).
6. **Validation**: Deploy consumers alongside existing workers. Compare `temporal_events`, `canonical_entities.metadata`, and `relations` table state between worker-produced and consumer-produced data.

**Files changed**:
- 3 new consumer files + 3 new entry point files (~450 lines)
- 3 new test files (~300 lines)

### Wave 4: Dual-Run Validation

**Goal**: Verify consumer output matches worker output before removing workers.

**Tasks**:
1. Add feature flag: `KNOWLEDGE_GRAPH_EODHD_WORKERS_ENABLED` (default: `true`).
2. Run both workers AND consumers simultaneously for 1-2 weeks.
3. Compare outputs:
   - Economic events: count of `temporal_events` rows should match
   - Macro indicators: `canonical_entities.metadata["macro_indicators"]` should match
   - Insider transactions: `has_executive` relation count should match
4. If outputs match: proceed to Wave 5. If not: debug and fix.

### Wave 5: Deprecate S7 EODHD Workers

**Goal**: Remove all direct EODHD usage from S7.

**Tasks**:
1. Set `KNOWLEDGE_GRAPH_EODHD_WORKERS_ENABLED=false` in all environments.
2. Remove from `KnowledgeGraphScheduler._register_jobs()`: `economic_events`, `macro_indicator`, `insider_transactions` cron jobs.
3. Remove from `build_workers()`: EODHD worker instantiation block (including httpx client and ConfluentDirectProducer).
4. Delete files:
   - `services/knowledge-graph/src/knowledge_graph/infrastructure/eodhd/client.py`
   - `services/knowledge-graph/src/knowledge_graph/infrastructure/eodhd/__init__.py`
   - `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/economic_events_worker.py`
   - `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/macro_indicator_worker.py`
   - `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/insider_transactions_worker.py`
5. Remove config fields: `eodhd_api_key`, `eodhd_base_url`, `economic_event_countries`, `macro_indicator_countries` from S7's `config.py`.
6. Update `docker-compose.yml`: remove `KNOWLEDGE_GRAPH_EODHD_API_KEY` env var from S7 containers.
7. Update docs: `.claude-context.md`, service docs, MASTER_PLAN.

**Files deleted**: ~600 lines removed.

### Wave 6: Cleanup and Budget Optimization

**Goal**: Finalize and optimize.

**Tasks**:
1. Remove the dual-run feature flag.
2. Remove S7 EODHD worker test files (replace with consumer tests from Wave 3).
3. Adjust S2's `ProviderBudget` token bucket settings to account for the expanded polling load.
4. Update `docs/audits/2026-04-19-eodhd-api-optimization-report.md` with final call counts.
5. Update `docs/plans/TRACKING.md`.

---

## 7. New Kafka Topics

**None required.** The existing `market.dataset.fetched` topic with its Avro schema already supports all needed dataset types via the `dataset_type` string field. S7 consumers will filter on this field:

- `dataset_type == "economic_events"`
- `dataset_type == "macro_indicator"`
- `dataset_type == "insider_transactions"`

The Avro schema (`infra/kafka/schemas/market.dataset.fetched.avsc`) carries claim-check pointers (`bronze_ref_*`, `canonical_ref_*`) to MinIO objects where the full data lives. No schema changes needed.

---

## 8. Risk Assessment

### Risk 1: Instrument Discovery for Insider Transactions (Medium)

**Risk**: S7 currently discovers US instruments from its own `canonical_entities` table. S2 does not have access to this table (R7). If S2 cannot determine which tickers to poll for insider transactions, coverage gaps will appear.

**Mitigation**:
- Short-term: Seed S2's insider transaction polling policies with all known US tickers. Manual updates as the universe grows.
- Medium-term: S2 consumes `market.instrument.created` events (the topic already exists) and auto-creates insider transaction polling policies for new US instruments.
- Long-term: S9 API gateway provides a `POST /internal/v1/market-ingestion/policies` endpoint that S7 (or any admin) can call to register new tickers.

### Risk 2: Canonical Format Compatibility (Low)

**Risk**: S7's workers currently parse raw EODHD JSON directly. The MinIO claim-check payload from S2 wraps the data in a canonical envelope. S7 consumers need to extract the raw data from this envelope.

**Mitigation**: The canonical passthrough format (Wave 1) should use a simple, documented envelope. S7 consumers extract `payload` from the envelope. Unit tests verify round-trip compatibility.

### Risk 3: Latency Increase (Low)

**Risk**: Worker-based processing is synchronous (cron fires, API call, process, done). Consumer-based processing adds Kafka propagation delay (~100-500ms) plus MinIO download time (~50-200ms).

**Mitigation**: These are background enrichment jobs with daily/weekly cadence. A few hundred milliseconds of additional latency is irrelevant. The data itself is not time-sensitive (economic events are reported the next day, macro indicators are annual data, insider transactions are filed within 2 business days).

### Risk 4: Consumer Group Lag During Migration (Low)

**Risk**: When the new S7 consumers first start, they will process all historical `market.dataset.fetched` events from the topic's earliest offset, potentially duplicating data already processed by the workers.

**Mitigation**:
- Set consumer group initial offset to `latest` (only process new events).
- S7's existing natural-key dedup (`ON CONFLICT DO NOTHING`) prevents duplicate `temporal_events` and `entity_event_exposures` rows.
- `has_executive` relations use advisory-lock upsert (idempotent).
- Macro indicator hash comparison prevents unnecessary updates.

### Risk 5: S2 Becomes Single Point of Failure for EODHD Data (Low)

**Risk**: If S2 goes down, no EODHD data flows to S7.

**Mitigation**: S2 is already the single point of failure for OHLCV, quotes, and fundamentals. This change does not meaningfully increase the blast radius. S2 has health checks, readiness probes, and exponential backoff. The data S7 needs is low-frequency (daily/weekly) -- a brief S2 outage simply delays enrichment by one cycle.

---

## 9. Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-04-19 | Option D selected | Best architectural alignment, proven pattern, no new infrastructure, 100% dedup |
| | Pending | User approval to proceed with implementation |

---

## Appendix A: File Inventory

### S2 Files Involved

| File | Change Type | Description |
|------|------------|-------------|
| `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py` | Modify | Add passthrough canonicalization for 3 dataset types |
| `services/market-ingestion/src/market_ingestion/infrastructure/adapters/canonical.py` | Modify | Add passthrough serializer methods |
| `services/market-ingestion/alembic/versions/NNNN_expand_eodhd_policies.py` | New | Seed migration for expanded polling policies |

### S7 Files Involved

| File | Change Type | Description |
|------|------------|-------------|
| `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/economic_events_dataset_consumer.py` | New | Consumes `market.dataset.fetched` for economic events |
| `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/economic_events_dataset_consumer_main.py` | New | Standalone entry point |
| `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/macro_indicator_dataset_consumer.py` | New | Consumes `market.dataset.fetched` for macro indicators |
| `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/macro_indicator_dataset_consumer_main.py` | New | Standalone entry point |
| `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/insider_transactions_dataset_consumer.py` | New | Consumes `market.dataset.fetched` for insider transactions |
| `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/insider_transactions_dataset_consumer_main.py` | New | Standalone entry point |
| `services/knowledge-graph/src/knowledge_graph/infrastructure/eodhd/client.py` | Delete (Wave 5) | Direct EODHD HTTP client |
| `services/knowledge-graph/src/knowledge_graph/infrastructure/eodhd/__init__.py` | Delete (Wave 5) | Package init |
| `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/economic_events_worker.py` | Refactor | Extract processing logic into shared functions; delete EODHD-specific wiring |
| `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/macro_indicator_worker.py` | Refactor | Extract processing logic into shared functions; delete EODHD-specific wiring |
| `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/insider_transactions_worker.py` | Refactor | Extract processing logic into shared functions; delete EODHD-specific wiring |
| `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py` | Modify | Remove EODHD cron jobs and worker wiring |
| `services/knowledge-graph/src/knowledge_graph/config.py` | Modify | Remove EODHD config fields |
