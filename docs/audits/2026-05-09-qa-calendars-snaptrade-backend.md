# 2026-05-09 — QA: Calendars, SnapTrade & multi-source news (backend cascades)

**Author:** backend QA agent
**Branch:** `fix/backend-cascades-bundle`
**Scope:** Three user-reported cascades on the same date.

---

## Summary

| # | Cascade | Severity | Status |
|---|---------|----------|--------|
| 1 | Economic + Earnings calendars empty | CRITICAL — dashboard widgets dark | **FIXED LIVE** (consumers restarted, offsets reset) |
| 2 | SnapTrade transactions don't appear after connecting | HIGH — feature unusable without 4 h wait | **FIXED IN CODE** (auto-sync on activation) |
| 3 | Only Finnhub news flowing | HIGH — 2 of 4 sources never scheduled | **PARTIALLY FIXED** (SEC EDGAR seeded + builder bug fixed; EODHD news still blocked by demo key) |

Live database state after the fixes:

```text
intelligence_db.temporal_events:    corporate=10,981   macro=42        (were 0+0)
content_ingestion_db.sources:       finnhub=8  newsapi=2  polymarket=1  sec_edgar=3 (was 0)
```

---

## Cascade 1 — Calendars empty (`market_data_db.economic_events = 0`, `earnings_calendar = 0`)

### Diagnosis

The user report named `market_data_db.economic_events` and `earnings_calendar`, but
those tables are **not the source of truth for the dashboard widgets**.

S9 `GET /api/v1/fundamentals/earnings-calendar` and `…/economic-calendar` proxy
to S7 (knowledge-graph) which reads `intelligence_db.temporal_events` filtered
by `event_type IN ('corporate','macro')`. The market_data_db tables are unused
DDL leftovers from a pre-PRD-0018 schema and can be ignored.

The **real** flow is:

```text
market-ingestion-scheduler ─► EODHD adapter ─► MinIO bronze ─►
  market.dataset.fetched (Kafka) ─►
  KG dataset consumers ─► intelligence_db.temporal_events
```

Live trace showed:

* `ingestion_db.ingestion_tasks` had 1 successful `earnings_calendar` and 6
  successful `economic_events` fetches at 13:56 UTC. ✓
* MinIO bronze contained the canonical NDJSON envelopes. ✓
* `market.dataset.fetched` topic had ~280 messages across 6 partitions, 0 lag. ✓
* But `temporal_events` had only 1 row, `entity_event_exposures` had 0.

`docker logs worldview-knowledge-graph-economic-events-dataset-consumer-1`
revealed the real error:

```text
asyncpg.exceptions.UndefinedTableError: relation "temporal_events" does not exist
[SQL: INSERT INTO temporal_events (...)]
```

Root cause: the consumer was started at **2026-05-09 17:05:12**, before the
intelligence-migrations container ran (later, at **20:40:21**). Migration
**0037 `recreate_temporal_events_idempotent`** is the one that created
`temporal_events` in this volume — it had been missing since a backup-restore
incident documented in `docs/audits/2026-05-09-audit-P3-freshness.md`
(D-P3-002 / D-P3-003).

asyncpg cached the negative table lookup as a prepared statement, so even after
the migration created the table the existing connections kept getting
`UndefinedTableError`. All 4 calendar consumers
(`economic-events`, `earnings-calendar`, `insider-transactions`,
`macro-indicator`) were affected.

### Fix applied (live, no code change)

```bash
docker restart \
  worldview-knowledge-graph-economic-events-dataset-consumer-1 \
  worldview-knowledge-graph-earnings-calendar-dataset-consumer-1 \
  worldview-knowledge-graph-insider-transactions-dataset-consumer-1 \
  worldview-knowledge-graph-macro-indicator-dataset-consumer-1

# economic-events caught up immediately. earnings-calendar's offsets had
# already been committed at end-of-topic (the dropped messages had committed
# anyway via the retryable-error path), so we reset:
docker stop worldview-knowledge-graph-earnings-calendar-dataset-consumer-1
docker exec worldview-kafka-1 kafka-consumer-groups \
  --bootstrap-server localhost:9092 \
  --reset-offsets --to-earliest \
  --topic market.dataset.fetched \
  --group kg-earnings-calendar-dataset-group --execute
docker start worldview-knowledge-graph-earnings-calendar-dataset-consumer-1
```

### Verification

```text
intelligence_db.temporal_events: corporate=10,981  macro=42
```

Dashboard widgets populate correctly via S9.

### Remaining work (NOT applied here)

* **Hardening**: the 17:05 race shouldn't recur on a clean stack because
  `intelligence-migrations` is declared as a `depends_on` for the consumers.
  But migrations occasionally re-run on `make dev` after a volume tweak; the
  consumers should detect a `UndefinedTableError` and re-bootstrap their pool
  (or retry with exponential back-off) instead of treating it as retryable
  forever. Track as new BP candidate (BP-442 — to be assigned).
* **Cleanup**: drop the unused `market_data_db.economic_events` and
  `market_data_db.earnings_calendar` tables — they confused the user report.
  Suggest in next QA pass.

---

## Cascade 2 — SnapTrade transactions don't appear after connecting

### Diagnosis

`portfolio_db.brokerage_connections`:

```text
2 active connections, both portfolio_id = Demo Portfolio,
last_synced_at = NULL, brokerage_name = ''
```

`docker logs worldview-portfolio-brokerage-sync-1`:

```text
2026-05-09 13:46:54 brokerage_sync_worker_started cycle_seconds=14400
[no further log lines in 7 hours]
```

The worker's algorithm:

1. On startup → run `sync_cycle()` immediately.
2. Inside `sync_cycle()` → `list_active_or_error()` → returned 0 rows
   (the connections were created later, at 20:13 and 20:15).
3. Sleep `brokerage_sync_cycle_seconds` (default **14 400 s = 4 h**).

So the next cycle is at **17:46 UTC** (didn't pick anything up yet — connections
hadn't been created), then **21:46 UTC** (would pick them up).

The **`/brokerage-connections/{id}/callback` endpoint** in the API
(`services/portfolio/src/portfolio/api/routes/brokerage_connections.py:140`)
transitions the entity to `ACTIVE` but **does NOT enqueue a sync**. The frontend
also does not call the existing `POST /brokerage-connections/{id}/sync`
endpoint after the OAuth callback (see
`apps/worldview-web/app/(app)/portfolio/brokerage/callback/page.tsx:120`).

Result: a freshly connected user must wait up to 4 hours before any
transaction or holding appears. Exactly the user-reported symptom.

### Fix applied

`services/portfolio/src/portfolio/api/routes/brokerage_connections.py`

The activation route now schedules `_run_single_sync` as a FastAPI
`BackgroundTask` immediately after `ActivateBrokerageConnectionUseCase`
returns `status='active'`. The 200 response is unchanged; the sync runs
out-of-band and any failure is swallowed inside `_run_single_sync` (logged
via structlog). Existing 134 unit tests in
`tests/unit/test_brokerage_*.py` still pass.

### Verification

* Unit-test sweep: 134/134 pass (`pytest tests/unit -k brokerage -q`).
* Behavioural verification deferred: requires a real SnapTrade Connection
  Portal session — staging only. Smoke test: after a fresh connect, expect
  `last_synced_at` to be populated within ~30 s instead of within 4 h.

### Remaining work (planned, not implemented)

* **UX feature: portfolio selection in the connect flow.**
  `ConnectBrokerageModal` already accepts a `portfolioId` prop and the API
  already accepts `portfolio_id` in the body — the limitation is that the
  demo seed has only one portfolio (`Demo Portfolio`). Two work items:
  1. Replace `portfolioId={activePortfolioId}` (single-portfolio assumption)
     with a `<Select>` listing all owned portfolios + a "+ New Portfolio"
     option that opens `CreatePortfolioDialog` first.
  2. Add a query in `/portfolio/page.tsx` to ensure the user has at least
     one portfolio (auto-create one named "My Portfolio" if zero, otherwise
     prompt).

  These are pure frontend changes — no backend work needed. Suggest a small
  PR (`feat/select-target-portfolio-in-connect-modal`).

* **Worker restart for code change to take effect**: the route fix needs a
  rebuild of the `portfolio` container. The currently-running container will
  still rely on the 4 h cadence. Run `make dev-rebuild SVC=portfolio`
  (or equivalent) after merging.

---

## Cascade 3 — Multi-source news ingestion (only Finnhub flowing)

### Diagnosis

Live `nlp_db.document_source_metadata`:

```text
eodhd_news        276   created_at=2026-05-09 16:01  (stale demo fixture)
finnhub           234   created_at=2026-05-09 20:38  ✓ live
finnhub_news      126   created_at=2026-05-09 16:01  (older finnhub schema)
financial          41   created_at=2026-05-09 16:01
earnings_transcript 21   created_at=2026-05-09 16:01
sec_10k            14   created_at=2026-05-09 16:01  (stale demo fixture)
sec_8k             12   created_at=2026-05-09 16:01  (stale demo fixture)
```

`content_ingestion_db.content_ingestion_tasks` (live cadence):

```text
finnhub  / Finnhub-{8 tickers}    succeeded 167-178 each
newsapi  / NewsAPI-{2 queries}    succeeded 173+175       ← contradicts user's "only Finnhub"
polymarket / Polymarket           succeeded 168
```

**Adapters present**: `eodhd`, `finnhub`, `newsapi`, `polymarket`,
`sec_edgar` — all 5 wired in `WorkerProcess._build_adapter`.

**Sources seeded** (the table the scheduler reads to decide what to fetch):

```text
finnhub       8 enabled
newsapi       2 enabled
polymarket    1 enabled
eodhd         0 enabled  (intentionally disabled — demo key returns HTTP 403)
sec_edgar     0 enabled  ← THE BUG
```

Root cause: `scripts/seed_demo_data.py::seed_content_ingestion_db` seeds
Finnhub + NewsAPI + Polymarket + (disabled-)EODHD sources, but **never
seeds an SEC EDGAR source row**. The SEC adapter exists, the worker can
build it, the scheduler would create tasks if it found a row — there
just isn't one.

User's "only Finnhub flows" perception is partially correct:
* SEC EDGAR: never flowed (no source row)
* EODHD news: blocked by demo key, intentional
* NewsAPI: was already flowing — user may not have noticed because the
  NewsAPI articles are stored under `source_type='financial'` /
  `'eodhd_news'` etc. (see PRD-0026 §3 — `source_type` reflects the
  *content type* not the API source)

Bonus root-cause discovered while wiring SEC: the worker's adapter
builder always passes `rate_limiter=` to every non-newsapi adapter
(`worker.py:380`), but `SECEdgarAdapter.__init__` does not accept that
kwarg. Once SEC sources were seeded, every task FAILED with:

```text
SECEdgarAdapter.__init__() got an unexpected keyword argument 'rate_limiter'
```

This bug had been latent ever since the SEC adapter was added — it would
have surfaced the moment anyone enabled SEC sources.

### Fixes applied

1. `scripts/seed_demo_data.py`: seed three SEC EDGAR sources
   (`SEC-EDGAR-10K`, `SEC-EDGAR-10Q`, `SEC-EDGAR-8K`) with form-specific
   configs. The split lets each form be scheduled/disabled independently.

2. `services/content-ingestion/src/content_ingestion/infrastructure/workers/worker.py`:
   group `sec_edgar` together with `newsapi` in the no-`rate_limiter`
   branch of `_build_adapter` (SEC adapter does its own pacing via
   `provider_cfg.market_hours_interval_seconds`).

3. `services/content-ingestion/tests/unit/test_worker_process.py`:
   added `TestBuildAdapterKwargs` parametrised over all 4 source types
   (`eodhd`, `finnhub`, `newsapi`, `sec_edgar`), asserting that
   `rate_limiter` is passed only to the two that accept it. The test
   was verified to FAIL on the pre-fix code (sec_edgar branch),
   guaranteeing it catches the regression.

4. Live DB applied: 3 rows inserted into `content_ingestion_db.sources`
   so the running scheduler picks them up immediately. The first
   scheduled tasks failed with the rate_limiter TypeError (proving the
   adapter-builder bug is real); they were then requeued with
   `status='queued'` and will succeed on the next worker rebuild.

### Verification

```text
content_ingestion_db.sources:    sec_edgar=3 (enabled)
unit tests:                      4/4 new + 8/8 pre-existing = 12/12 PASS
ruff format / check:             clean
```

### Remaining work

* **EODHD news**: blocked at the API-key level. The demo
  `CONTENT_INGESTION_EODHD_API_KEY=demo` returns HTTP 403 on `/news`
  and `/market-sentiment`. To unblock:
  - Provision a paid EODHD key with `News API` add-on
    (~ $50/month for Fundamentals + News), set
    `CONTENT_INGESTION_EODHD_API_KEY` in `worldview-config`, run
    `make fetch-secrets && docker compose up -d --build content-ingestion-worker`,
    then re-enable EODHD sources via:
    `UPDATE sources SET enabled = true WHERE source_type = 'eodhd';`
  - The SEC `User-Agent` env var
    (`CONTENT_INGESTION_SEC_EDGAR_USER_AGENT`) is already set; no key
    needed for SEC.

* **Worker rebuild required for the rate-limiter fix.** The currently-running
  `content-ingestion-worker` container has the buggy `_build_adapter` code.
  Run `docker compose up -d --build content-ingestion-worker` (or
  `make dev-rebuild SVC=content-ingestion`) so the seeded SEC tasks
  succeed instead of failing in a loop.

---

## Files changed

| File | Change |
|------|--------|
| `services/portfolio/src/portfolio/api/routes/brokerage_connections.py` | Auto-schedule `_run_single_sync` as a `BackgroundTask` after activation |
| `services/content-ingestion/src/content_ingestion/infrastructure/workers/worker.py` | Group `sec_edgar` with `newsapi` in the no-`rate_limiter` adapter branch |
| `services/content-ingestion/tests/unit/test_worker_process.py` | New `TestBuildAdapterKwargs` regression class (4 parametrised cases) |
| `scripts/seed_demo_data.py` | Seed `SEC-EDGAR-10K`, `…-10Q`, `…-8K` sources |
| `docs/audits/2026-05-09-qa-calendars-snaptrade-backend.md` | This document |

## Live operations performed

1. `docker restart` of 4 KG calendar consumers (no code change).
2. Kafka offset reset to earliest for `kg-earnings-calendar-dataset-group`.
3. SQL `INSERT` of 3 SEC EDGAR rows into `content_ingestion_db.sources`.
4. SQL `UPDATE … SET status='queued'` on the 3 SEC tasks that failed with
   the rate_limiter TypeError so they're ready to retry after rebuild.

## Bugs to add to `docs/BUG_PATTERNS.md` (next QA pass)

* **BP-442 (proposed)**: KG dataset consumers must reset asyncpg prepared-statement
  cache when receiving `UndefinedTableError`, or refuse-to-start until a
  smoke INSERT succeeds. Cause: stale negative table lookup persists across
  schema migrations applied after the consumer connects.
* **BP-443 (proposed)**: `WorkerProcess._build_adapter` must use a per-source
  kwargs dispatch table instead of an `if newsapi else default` ladder; any
  new adapter that doesn't accept `rate_limiter` silently breaks all of its
  tasks. (Test added; structural refactor still pending.)
