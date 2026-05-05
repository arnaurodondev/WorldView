# PLAN-0068 — Earnings Calendar Pipeline + Prediction Market Category Fix

> **Status**: completed
> **Created**: 2026-05-03
> **Updated**: 2026-05-05
> **Owner**: Arnau Rodon
> **PRD**: N/A (targeted feature completion + bug fix)
> **Tracking**: `docs/plans/TRACKING.md`

---

## Overview

Two focused deliverables shipped as a single plan with three sub-plans:

1. **Earnings Calendar** — S2 already fetches earnings data from Finnhub via the
   `EARNINGS_CALENDAR` DatasetType and publishes it on `market.dataset.fetched`.
   However there is **no S7 consumer** that turns those Kafka messages into rows in
   `temporal_events`, no `CORPORATE` event type in the DB CHECK constraint, and no
   S9 endpoint or live frontend widget.  This plan wires the full pipeline.

2. **Prediction Market Category Fix** — All 102 currently-stored markets carry
   `category = 'sports'` because the Gamma API returns `"Sports"` (or similar) as
   a top-level `category` string for most markets, and earlier ingestion runs
   pre-date the PLAN-0053 normalisation logic.  The fix is a one-time DB backfill
   (UPDATE … CASE WHEN title LIKE …) plus unit tests that prevent regression.
   A new `/prediction-markets` dedicated page in the Next.js frontend completes
   the surface.

---

## Codebase State Table

| Area | Current State | Delta Needed |
|------|--------------|--------------|
| `intelligence-migrations` CHECK constraint | `ck_temporal_event_type` allows only 6 values (no `'corporate'`) | Migration `0018_add_corporate_event_type.py` to ALTER CONSTRAINT |
| `knowledge_graph.domain.enums.EventType` | 6 values; no `CORPORATE` | Add `CORPORATE = "corporate"` |
| S7 earnings consumer | Does not exist | New `EarningsCalendarDatasetConsumer` (mirrors `EconomicEventsDatasetConsumer`) |
| S7 earnings consumer entrypoint | Does not exist | `earnings_calendar_dataset_consumer_main.py` |
| S7 `docker-compose.yml` entry | No `earnings-calendar-dataset-consumer` container | Add service entry |
| S9 proxy route | No `/fundamentals/earnings-calendar` route | Add route proxying to S7 `GET /api/v1/temporal-events?event_type=corporate` |
| `EarningsCalendarWidget.tsx` | Static placeholder (no hooks, no data) | Convert to live `useQuery` component mirroring `EconomicCalendar.tsx` |
| `lib/gateway.ts` | `getEarningsCalendar()` method missing | Add method |
| `prediction_markets.category` column | 102 rows all `'sports'` | DB backfill UPDATE with title-keyword CASE |
| `/prediction-markets` page | Does not exist | New Next.js page with full filter UI |

---

## Sub-Plan A — Earnings Calendar: Backend Pipeline

**Scope**: intelligence-migrations (Alembic), S7 Knowledge Graph, S9 API Gateway
**Dependencies**: none
**Blocks**: Sub-plan B (frontend needs the endpoint)

---

### Wave A-1 — DB Migration + EventType Enum + S7 Consumer

**Goal**: Extend the `ck_temporal_event_type` CHECK constraint to allow `'corporate'`,
add `EventType.CORPORATE` to the domain enum, and create the
`EarningsCalendarDatasetConsumer` that consumes `market.dataset.fetched` WHERE
`dataset_type='earnings_calendar'` and upserts rows into `temporal_events`.

**Pre-read**:
- `services/intelligence-migrations/alembic/versions/0004_geopolitical_age_temporal_events.py` — CHECK constraint definition
- `services/intelligence-migrations/alembic/versions/` — latest version to find the head
- `services/knowledge-graph/src/knowledge_graph/domain/enums.py` — EventType enum
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/economic_events_dataset_consumer.py` — reference consumer pattern (nearly identical)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/temporal_event_repository.py` — upsert_by_natural_key signature
- `services/knowledge-graph/src/knowledge_graph/infrastructure/metrics/prometheus.py` — metric counter pattern

**Tasks**:

| # | ID | Task | Owner Service | Depends on |
|---|----|------|--------------|-----------|
| 1 | A-1-01 | Write `intelligence-migrations` Alembic migration `0018_add_corporate_event_type.py`: ALTER TABLE temporal_events DROP CONSTRAINT ck_temporal_event_type, ADD CONSTRAINT ck_temporal_event_type CHECK (event_type IN ('geopolitical','regulatory','macro','sanctions','natural_disaster','other','corporate')). Include downgrade that reverts to 7-value list. | intelligence-migrations | — |
| 2 | A-1-02 | Add `CORPORATE = "corporate"` to `EventType` StrEnum in `services/knowledge-graph/src/knowledge_graph/domain/enums.py`. Update `__all__` if present. | knowledge-graph | A-1-01 |
| 3 | A-1-03 | Create `EarningsCalendarDatasetConsumer` in `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/earnings_calendar_dataset_consumer.py`. Filter on `dataset_type='earnings_calendar'`. Parse Finnhub `earningsCalendar` list from NDJSON envelope. Upsert each event as `EventType.CORPORATE`, `EventScope.LOCAL`, linked to the instrument's canonical entity (lookup by ticker via `EntityRepository.find_by_ticker`). Skip rows where `epsEstimate` is None (unreleased). Natural-key: `(event_type='corporate', region=ticker, title=f"{company} Earnings ({period})", active_from::date)`. | knowledge-graph | A-1-02 |
| 4 | A-1-04 | Create `earnings_calendar_dataset_consumer_main.py` entrypoint (mirrors `economic_events_dataset_consumer_main.py`). Register consumer group `kg-earnings-calendar-dataset-group`. | knowledge-graph | A-1-03 |
| 5 | A-1-05 | Add Prometheus counter `s7_earnings_calendar_events_ingested_total` (label: `ticker`) in `prometheus.py`. Wire into consumer. | knowledge-graph | A-1-03 |
| 6 | A-1-06 | Add `earnings-calendar-dataset-consumer` service to `docker-compose.yml` (mirrors existing economic-events consumer entry). | infrastructure | A-1-04 |

**Validation Gate**:
```bash
cd services/intelligence-migrations && python -m pytest tests/ -v
cd services/knowledge-graph && python -m pytest tests/unit/consumers/ -v -k earnings
ruff check services/knowledge-graph/src && mypy services/knowledge-graph/src
```

**Break Impact**:

| If broken | Symptom | Blast radius |
|-----------|---------|-------------|
| A-1-01 migration fails | intelligence-migrations alembic upgrade fails | All services using intelligence_db blocked on startup |
| A-1-02 missing enum | Consumer crashes with `AttributeError: CORPORATE` | No earnings events ingested; S9 endpoint returns empty |
| A-1-03 missing dataset_type filter | Consumer processes ALL dataset.fetched messages | Wrong events written to temporal_events |
| A-1-06 missing docker-compose entry | Container never starts | Earnings pipeline never runs in dev |

**Regression Guardrails**:
- BP-180: asyncpg `CAST(:param AS TEXT) IS NULL` pattern — use this in any raw SQL with nullable params
- BP-122: Avro Confluent wire format — deserialize with `deserialize_confluent_avro` when `raw[0:1] == b"\x00"`
- BP-314: `mark_processed` must be called AFTER `uow.commit()`, not before
- BP-065: Fix ruff errors BEFORE `git add` to avoid stash conflict

---

### Wave A-2 — S9 Proxy Endpoint + S7 API Schema Validation

**Goal**: Add `GET /v1/fundamentals/earnings-calendar` to S9, which proxies to
S7's existing `GET /api/v1/temporal-events?event_type=corporate`. Validate that
the S7 `list_temporal_events` endpoint accepts `event_type=corporate` correctly.

**Pre-read**:
- `services/api-gateway/src/api_gateway/routes/proxy.py` lines 1240–1266 — `economic_calendar` as reference pattern (MUST register before `/{instrument_id}` routes)
- `services/knowledge-graph/src/knowledge_graph/api/temporal_events.py` — S7 endpoint
- `services/api-gateway/tests/` — existing proxy test pattern

**Tasks**:

| # | ID | Task | Owner Service | Depends on |
|---|----|------|--------------|-----------|
| 1 | A-2-01 | Add `GET /v1/fundamentals/earnings-calendar` route to `services/api-gateway/src/api_gateway/routes/proxy.py`. Must be registered BEFORE `/fundamentals/{instrument_id}` (same pattern as `economic-calendar`). Proxy to `GET /api/v1/temporal-events` with `event_type=corporate`. Pass through query params `from_date`, `to_date`, `limit`. | api-gateway | A-1-02 |
| 2 | A-2-02 | Add unit test in `services/api-gateway/tests/` that asserts: (a) the route returns 200 with mocked S7 response; (b) `event_type=corporate` is injected even when caller omits it; (c) route is not shadowed by `/{instrument_id}`. | api-gateway | A-2-01 |
| 3 | A-2-03 | Verify S7 `list_temporal_events` use case returns `CORPORATE` events correctly (add integration test in `services/knowledge-graph/tests/integration/` if missing, exercising the `event_type='corporate'` filter). | knowledge-graph | A-1-03 |

**Validation Gate**:
```bash
cd services/api-gateway && python -m pytest tests/ -v -k earnings
cd services/knowledge-graph && python -m pytest tests/integration/ -v -k "temporal" --timeout=30
ruff check services/api-gateway/src && mypy services/api-gateway/src
```

**Break Impact**:

| If broken | Symptom | Blast radius |
|-----------|---------|-------------|
| A-2-01 route registered after `/{instrument_id}` | `"earnings-calendar"` matched as instrument_id → 404/500 from S3 | Dashboard widget permanently broken |
| A-2-01 missing `event_type=corporate` injection | Returns ALL temporal events including macro/geopolitical | Widget shows wrong data |

**Regression Guardrails**:
- BP-340: EventType values are lowercase in DB — `event_type=corporate` not `CORPORATE`
- Existing `economic-calendar` endpoint pattern must not be modified

---

## Sub-Plan B — Earnings Calendar: Frontend

**Scope**: `apps/worldview-web`
**Dependencies**: Sub-plan A Wave A-2 (S9 endpoint must exist before wiring the gateway)
**Blocks**: nothing

---

### Wave B-1 — Live EarningsCalendarWidget + Gateway Method

**Goal**: Convert the static `EarningsCalendarWidget.tsx` into a live component that
calls `getEarningsCalendar()` from the gateway, rendering upcoming corporate earnings
events with date, ticker, and EPS estimate. Mirrors the `EconomicCalendar.tsx` pattern.

**Pre-read**:
- `apps/worldview-web/components/dashboard/EarningsCalendarWidget.tsx` — current static placeholder
- `apps/worldview-web/components/dashboard/EconomicCalendar.tsx` — reference live pattern
- `apps/worldview-web/lib/gateway.ts` — add `getEarningsCalendar()` method alongside `getEconomicCalendar()`
- `apps/worldview-web/types/api.ts` — add `EarningsEvent` and `EarningsCalendarResponse` types
- `apps/worldview-web/app/(app)/dashboard/page.tsx` — verify widget slot (Row 4, col-span-3)

**Tasks**:

| # | ID | Task | Owner | Depends on |
|---|----|------|-------|-----------|
| 1 | B-1-01 | Add `EarningsEvent` and `EarningsCalendarResponse` TypeScript types to `apps/worldview-web/types/api.ts`. Fields: `event_id`, `title`, `description`, `active_from`, `active_until`, `region` (ticker), `confidence`. | worldview-web | A-2-01 |
| 2 | B-1-02 | Add `getEarningsCalendar(params?: { from_date?: string; to_date?: string; limit?: number })` to `apps/worldview-web/lib/gateway.ts` and the `api/earnings-calendar.ts` API module. Proxies to `GET /v1/fundamentals/earnings-calendar`. | worldview-web | B-1-01 |
| 3 | B-1-03 | Rewrite `EarningsCalendarWidget.tsx` as a live `"use client"` component. Use `useQuery` with `staleTime: 10 * 60_000`. Show: date badge, company ticker/name from `region`, expected EPS from `description`. Show skeleton loading (3 rows × h-[22px]), muted error state, and "No upcoming earnings" empty state. Style mirrors §0.9 terminal row density standard. | worldview-web | B-1-02 |
| 4 | B-1-04 | Add Vitest unit test `__tests__/earnings-calendar-widget.test.tsx`: (a) renders skeleton while loading; (b) renders 3 events; (c) renders empty state when events=[]; (d) renders error state. Mock `createGateway`. | worldview-web | B-1-03 |

**Validation Gate**:
```bash
cd apps/worldview-web && pnpm test -- --run --reporter=verbose 2>&1 | tail -30
pnpm typecheck
pnpm lint
```

**Break Impact**:

| If broken | Symptom | Blast radius |
|-----------|---------|-------------|
| B-1-02 gateway method missing | Widget throws at runtime | Dashboard Row 4 shows error |
| B-1-03 missing `"use client"` | `useQuery` SSR crash | Dashboard page fails to render |
| B-1-04 test missing | R19 violation — tests required for every behavior change | CI fail |

**Regression Guardrails**:
- BP-300: `isMountedRef` not needed here (no WebSocket), but avoid `useEffect` data fetch — use `useQuery`
- Exact pnpm versions — never add `^` prefixes (project pnpm enforcement rule)
- All new Tailwind classes must exist in the design system palette (no hex colors inline)

---

## Sub-Plan C — Prediction Markets: Category Backfill + Dedicated Page

**Scope**: `services/market-data` (backfill), `apps/worldview-web` (new page)
**Dependencies**: none (independent of Sub-plans A and B)
**Blocks**: nothing

---

### Wave C-1 — Category Backfill Migration

**Goal**: Fix the root cause of all 102 markets showing `category = 'sports'`. The
Gamma API returns `"Sports"` in the `category` field for most open prediction markets,
and the S3 consumer's `_normalize_category` call correctly lowercases this to `'sports'`.
The problem is that the Gamma API sometimes returns `"Sports"` even for non-sports
markets (wrong categorization on Polymarket's side), and historical rows were
persisted before the title-keyword heuristic was added.

The fix is a SQL backfill that re-runs the title-keyword heuristic against existing
rows and updates them to the correct canonical bucket. New ingestion already
uses the correct `from_gamma_response` logic.

**Pre-read**:
- `services/market-data/src/market_data/infrastructure/db/repositories/prediction_market_repo.py` — upsert COALESCE pattern
- `services/market-data/alembic/versions/` — latest migration to find the head
- `services/content-ingestion/src/content_ingestion/domain/entities.py` lines 300–403 — `_TITLE_HEURISTIC_RULES` (must mirror exactly in SQL CASE)
- `services/market-data/tests/unit/` — test structure

**Tasks**:

| # | ID | Task | Owner Service | Depends on |
|---|----|------|--------------|-----------|
| 1 | C-1-01 | Write market-data Alembic migration `014_recategorize_prediction_markets.py`: one-shot `UPDATE prediction_markets SET category = CASE WHEN lower(question) LIKE ANY(ARRAY['%fed%','%rate%','%inflation%','%gdp%','%cpi%','%fomc%','%payroll%','%recession%','%tariff%','%fiscal%','%monetary%','%pmi%']) THEN 'macro' WHEN lower(question) LIKE ANY(ARRAY['%election%','%president%','%senate%','%congress%','%vote%','%primary%']) THEN 'politics' WHEN lower(question) LIKE ANY(ARRAY['%nba%','%nfl%','%mlb%','%nhl%','%superbowl%','%super bowl%','%world cup%','%olympics%','%f1%','%fifa%','%uefa%']) THEN 'sports' WHEN lower(question) LIKE ANY(ARRAY['%bitcoin%','%ethereum%','%btc%','%eth%','%crypto%','%solana%']) THEN 'crypto' ELSE 'general' END WHERE category = 'sports' OR category IS NULL`. Include a no-op downgrade (data migration). | market-data | — |
| 2 | C-1-02 | Add a unit test `tests/unit/test_category_backfill_migration.py` that instantiates a fresh in-memory test DB, inserts 5 synthetic rows with titles matching macro/politics/sports/crypto/general, runs the migration SQL, and asserts correct category assignments. | market-data | C-1-01 |
| 3 | C-1-03 | Add a unit test that verifies `_normalize_category` and `_categorize_by_title` in content-ingestion agree with the SQL CASE keywords (no divergence between server-side Python logic and the SQL backfill). Can be a simple parameterized test using the same keyword lists. | content-ingestion | — |

**Validation Gate**:
```bash
cd services/market-data && python -m pytest tests/unit/test_category_backfill_migration.py -v
cd services/content-ingestion && python -m pytest tests/unit/ -v -k category
ruff check services/market-data/src && mypy services/market-data/src
```

**Break Impact**:

| If broken | Symptom | Blast radius |
|-----------|---------|-------------|
| C-1-01 SQL LIKE patterns wrong | Remaining rows stay as 'sports' | Category filter pills show wrong counts |
| C-1-01 no downgrade | `alembic downgrade` fails | Deployment rollback blocked |
| C-1-03 divergence test fails | Python and SQL use different keywords | Fresh ingestion produces different categories than backfill |

**Regression Guardrails**:
- BP-126: NOT NULL columns in migrations must have `server_default` — category column is already nullable, no issue
- BP-180: no raw asyncpg parameter typing issues in migration (use raw SQL strings in Alembic op.execute())
- Existing `COALESCE(EXCLUDED.category, prediction_markets.category)` upsert logic must not be changed — it is correct

---

### Wave C-2 — /prediction-markets Frontend Page

**Goal**: Create a dedicated `/prediction-markets` page that shows all open markets
with full filter/sort UI (category pills + search + sort by yes-probability / volume /
close time). The `PredictionMarketsWidget`'s "→ View all" link already points to this
route.

**Pre-read**:
- `apps/worldview-web/components/dashboard/PredictionMarketsWidget.tsx` — all category/sparkline/countdown logic to reuse
- `apps/worldview-web/app/(app)/screener/page.tsx` — reference for a full-page data table structure
- `apps/worldview-web/app/(app)/` — existing pages for layout reference
- `apps/worldview-web/lib/gateway.ts` — `getPredictionMarkets()` and `getPredictionMarketCategories()` already exist

**Tasks**:

| # | ID | Task | Owner | Depends on |
|---|----|------|-------|-----------|
| 1 | C-2-01 | Create `apps/worldview-web/app/(app)/prediction-markets/page.tsx`. "use client" component. Render a full-page terminal-density list of all open prediction markets (paginated: 25 per page with Load More). Reuse `categorize()` from `PredictionMarketsWidget.tsx` (extract to `lib/prediction-markets.ts`) and the category pill row. Add a search input (client-side filter on title). Sort controls: yes-probability (default, desc), volume, close time. Columns: category chip | title | YES% | NO% | Δ24h | closes in | volume. | worldview-web | — |
| 2 | C-2-02 | Extract shared utilities from `PredictionMarketsWidget.tsx` to `apps/worldview-web/lib/prediction-markets.ts`: `categorize()`, `formatCountdown()`, `MACRO_KEYWORDS`, `POLITICS_KEYWORDS`, `SPORTS_KEYWORDS`, `CRYPTO_KEYWORDS`, `Category` type. Update `PredictionMarketsWidget.tsx` to import from the shared module. | worldview-web | — |
| 3 | C-2-03 | Add `prediction-markets` to the navigation. Add a sidebar nav entry in the icon rail (or add to the secondary navigation if the rail is full). Use `BarChart2` icon. | worldview-web | C-2-01 |
| 4 | C-2-04 | Add Vitest unit test `__tests__/prediction-markets-page.test.tsx`: (a) renders skeleton while loading; (b) renders market rows after data loads; (c) category pill filters work (clicking "macro" hides non-macro rows); (d) search filters by title. | worldview-web | C-2-01 |
| 5 | C-2-05 | Add Vitest unit test `__tests__/prediction-markets-utils.test.ts`: parameterized tests for `categorize()` covering all 5 categories + edge cases (empty string, mixed-case). | worldview-web | C-2-02 |

**Validation Gate**:
```bash
cd apps/worldview-web && pnpm test -- --run --reporter=verbose 2>&1 | tail -30
pnpm typecheck
pnpm lint
pnpm build 2>&1 | tail -20
```

**Break Impact**:

| If broken | Symptom | Blast radius |
|-----------|---------|-------------|
| C-2-01 missing `"use client"` | `useQuery` crash in SSR | `/prediction-markets` returns 500 |
| C-2-02 failed extraction | `PredictionMarketsWidget.tsx` broken | Dashboard widget blank |
| C-2-03 broken nav entry | No way to navigate to the page | Feature effectively hidden |
| C-2-04/05 tests missing | R19 violation | CI fail |

**Regression Guardrails**:
- BP-328/329/330: RHF/Zod not needed here (no form submission), but use existing `createGateway` pattern
- The `PredictionMarketsWidget.tsx` MUST continue to work after C-2-02 refactor — run its existing tests
- Tailwind class allowlist: no hex colors, use design system tokens only

---

## Dependency Graph

```
A-1 (migration + consumer) ──► A-2 (S9 proxy) ──► B-1 (frontend widget)
                                                   (parallel safe)
C-1 (backfill migration) ─────────────────────────────────────────────────┐
C-2 (prediction-markets page) ──────────────────────────────────────────── ┘
(C-1 and C-2 are independent of each other; run in parallel)
```

**Critical path**: A-1 → A-2 → B-1

**Parallelizable**:
- C-1 ∥ C-2 ∥ A-1 (all start from zero)
- B-1 must wait for A-2

---

## Effort Estimate

| Sub-plan | Waves | Tasks | Estimated effort |
|----------|-------|-------|-----------------|
| A — Earnings backend | 2 | 9 | ~6h |
| B — Earnings frontend | 1 | 4 | ~3h |
| C — Predictions fix + page | 2 | 8 | ~5h |
| **Total** | **5** | **21** | **~14h** |

---

## Execution Order Recommendation

**Session 1** (backend, 1 dev): A-1-01 through A-1-06 → A-2-01 through A-2-03
**Session 2** (frontend, 1 dev, after Session 1): B-1-01 through B-1-04
**Session 3** (independent, any order): C-1-01 through C-1-03 then C-2-01 through C-2-05

Sessions 1 and 3 can run in parallel.

---

## New Files Created

### Backend
- `services/intelligence-migrations/alembic/versions/0018_add_corporate_event_type.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/earnings_calendar_dataset_consumer.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/earnings_calendar_dataset_consumer_main.py`
- `services/knowledge-graph/tests/unit/consumers/test_earnings_calendar_dataset_consumer.py`
- `services/market-data/alembic/versions/014_recategorize_prediction_markets.py`
- `services/market-data/tests/unit/test_category_backfill_migration.py`

### Frontend
- `apps/worldview-web/lib/prediction-markets.ts` (extracted from widget)
- `apps/worldview-web/app/(app)/prediction-markets/page.tsx`
- `apps/worldview-web/__tests__/earnings-calendar-widget.test.tsx`
- `apps/worldview-web/__tests__/prediction-markets-page.test.tsx`
- `apps/worldview-web/__tests__/prediction-markets-utils.test.ts`

### Modified Files
- `services/intelligence-migrations/alembic/env.py` (add migration to chain)
- `services/knowledge-graph/src/knowledge_graph/domain/enums.py` (add CORPORATE)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/metrics/prometheus.py` (new counter)
- `services/knowledge-graph/docker-compose.yml` (new consumer service)
- `services/api-gateway/src/api_gateway/routes/proxy.py` (new route)
- `apps/worldview-web/types/api.ts` (EarningsEvent types)
- `apps/worldview-web/lib/gateway.ts` (getEarningsCalendar)
- `apps/worldview-web/components/dashboard/EarningsCalendarWidget.tsx` (convert to live)
- `apps/worldview-web/components/dashboard/PredictionMarketsWidget.tsx` (import from shared lib)

---

## Wave Status

### Sub-plan A — Earnings Calendar Backend ✅
- [x] **Wave A-1** — DB Migration + EventType Enum + S7 Consumer (`done`)
  **Status**: **DONE** — 2026-05-03 · 31 tests pass · ruff + mypy clean
- [x] **Wave A-2** — S9 Proxy Endpoint (`done`)
  **Status**: **DONE** — 2026-05-03 · 6 tests pass · ruff + mypy clean

### Sub-plan B — Earnings Calendar Frontend ✅
- [x] **Wave B-1** — Live EarningsCalendarWidget + Gateway Method (`done`)
  **Status**: **DONE** — 2026-05-03 · 6 new tests + 31 dashboard tests pass · typecheck clean · lint clean

### Sub-plan C — Prediction Markets ✅
- [x] **Wave C-1** — Category Backfill Migration (`done`)
  **Status**: **DONE** — 2026-05-03 · 40 market-data + 56 content-ingestion tests pass · ruff clean
- [x] **Wave C-2** — /prediction-markets Frontend Page ✅
  **Status**: **DONE** — 2026-05-05 · 9 page tests + 34 utils tests pass · sidebar 12 tests pass · typecheck clean · lint clean
  Note: page.tsx was created as BP-383 bug fix; C-2 completed the shared lib extraction (lib/prediction-markets.ts), nav entry (BarChart2 in CollapsibleSidebar), and full test coverage.
