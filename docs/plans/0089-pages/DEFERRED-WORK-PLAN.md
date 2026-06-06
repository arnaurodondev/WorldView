---
id: PRD-0089-DEFERRED
title: PRD-0089 Deferred Work — Detailed Plan
prd: PRD-0089
created: 2026-05-28
status: planning (no work scheduled yet)
parent_prd: docs/specs/0089-platform-page-redesign.md
related:
  - docs/plans/0089-pages/I-screener-plan.md
  - docs/audits/2026-05-28-wave-l3-scope-investigation.md
  - docs/audits/2026-05-28-wave-l4-scope-investigation.md
  - docs/audits/2026-05-28-wave-l5-scope-investigation.md
estimated_total_effort: ~5 engineer-days (excluding L-4b universe budget approval)
---

# PRD-0089 Deferred Work — Detailed Plan

> **Purpose**: this is a planning + understanding document, not an implementation
> brief. It explains every item that is NOT in the `feat/plan-0099-w4` integration
> branch but is part of the PRD-0089 scope, why each one was deferred, what shape
> the work takes, and what shipping it actually requires.

## §0. Context — what already shipped vs what didn't

The session that produced `feat/plan-0099-w4` (HEAD `77d3d720`) shipped **all
five backend tracks** of Wave L (L-3 / L-4a / L-4b / L-5a / L-5c) plus the
**IB-L1, IB-L1-disclosure, IB-L2, IB-L2-polish, and fh-column-count-cap**
frontend deliverables. Migration chain is linear: `031 ← 030 ← 029 ← 028 ← 025`.
38 static screener fields registered. 5,500+ backend unit tests pass.

What shipped means that today the **screener backend** can:
- Read every field in §3.2 of `docs/plans/0089-pages/I-screener-plan.md` (39
  fields total: 12 base + 4 attribute + 7 fundamentals snapshot L-2 + 4 analyst
  L-4a + 8 returns L-3 + 1 insider L-4b + 2 calendar L-5c + 1 credit_rating).
- Filter, sort, and project all of them through `POST /v1/fundamentals/screen`.
- Surface field metadata via `GET /v1/fundamentals/screen/fields`.
- Compute the 8 derived return / 52W-distance metrics nightly at 02:00 UTC
  (`_computed_metrics_refresh_loop`, `ComputedMetricsBackfillWorker`).
- Compute the 90-day insider net-buy rollup nightly at 03:00 UTC
  (`_insider_rollup_loop`, `rollup_insider_90d`).
- Consume EODHD insider transaction Kafka events
  (`InsiderTransactionsConsumer`).
- Expose 4 internal intelligence-rollup REST endpoints behind
  `InternalJWTMiddleware`:
  - S6 `GET /internal/v1/instruments/{id}/news-rollup-7d`
  - S7 `GET /internal/v1/instruments/{id}/intelligence-rollup-7d`
  - S8 `GET /internal/v1/instruments/{id}/ai-brief-flag`
  - S10 `GET /internal/v1/instruments/{id}/active-alert-flag`

What did **not** ship and lives in this plan:

| # | Item | Effort | Blocker / status |
|---|------|--------|------------------|
| 1 | **L-5b** S3-side intelligence sync worker | ~3 d | Independent; ready to schedule |
| 2 | **IB-L3 / L-4 / L-5** frontend waves | ~3 d total | IB-L3 + IB-L4 unblocked; IB-L5 gated on §1 |
| 3 | **L-4b insider universe activation** | ~0.5 d + budget approval | Needs explicit EODHD credit-spend decision |
| 4 | **Migration 031 deploy-window sequencing** | ~10 min | Trivial runbook update |
| 5 | **L-3 production smoke test + runbook fill-in** | ~0.5 d | Needs staging deploy first |
| 6 | **Cross-session contamination commit (`c60c7810`)** | 0 (recommended: leave) | Cosmetic git history |

The rest of this document is one chapter per item.

---

## §1. L-5b — S3-side intelligence rollup sync worker

### §1.1 What it is

A **scheduled worker** in `services/market-data/` that runs nightly, iterates
the screener-universe instruments, calls the 4 internal endpoints shipped by
L-5a (one per upstream service), and writes the resulting 8 fields into
`services/market-data/`'s local database so the screener `WHERE` clause can
filter on them and the `SELECT` projection can return them as columns.

The 8 fields it materializes (per plan §3.2 L-5 row):

| Field | Source endpoint | Type |
|-------|----------------|------|
| `news_count_7d` | S6 `/news-rollup-7d` | `int` |
| `llm_relevance_7d_max` | S6 `/news-rollup-7d` | `float (0..1)` |
| `display_relevance_7d_weighted` | S6 `/news-rollup-7d` | `float (0..1)` |
| `recent_contradiction_count` | S7 `/intelligence-rollup-7d` | `int` |
| `has_active_alert` | S10 `/active-alert-flag` | `bool` |
| `has_ai_brief` | S8 `/ai-brief-flag` | `bool` |
| `next_earnings_date` | already in `instrument_fundamentals_snapshot` via L-5c | `date` |
| `next_dividend_date` | already in `instrument_fundamentals_snapshot` via L-5c | `date` |

Note: the last two (calendar dates) shipped with L-5c and are **already
materialized**. L-5b therefore only owns 6 of the 8 columns.

### §1.2 Why it matters

Without L-5b, Wave **I-B Block IB-L5** cannot ship — the 7
`IntelligenceFilterGroup` filter rows (`news count 7d`, `LLM relevance`,
`active alert`, `AI brief`, `contradictions`, `upcoming earnings`,
`upcoming dividend`) plus the 2 opt-in columns (`NEWS 7D`, `BRIEF SCORE`)
keep their `BackendPendingBadge` and remain disabled. Users see them in the
filter popover but cannot interact with them.

The frontend `BackendPendingBadge` removal in IB-L5 is purely a `backendReady`
boolean flip — but flipping it without L-5b in place would show empty data
everywhere (all instruments would appear to have `news_count_7d = 0`), which
is a **silent failure pattern** explicitly flagged by the user's memory
("Audit return values must be persisted").

### §1.3 R9 compliance — why the worker must live in S3

CLAUDE.md hard rule #9 (no cross-service DB access) means S3 cannot directly
JOIN tables owned by S6 / S7 / S10 / S8. The shipped L-5a endpoints are the
authorized cross-service contract surface; the worker is the consumer.

Three architecture options were considered in the audit
(`docs/audits/2026-05-28-wave-l5-scope-investigation.md` §3):

1. **Kafka events**: upstream services emit nightly rollup events;
   S3 consumes and materializes. Rejected: requires 4 new Avro schemas + 4
   new producers + handles backpressure poorly.
2. **Scheduled S3-side REST pulls**: the recommended option. Already done
   for L-5a (the endpoints exist); L-5b is just the consumer.
3. **Materialized view in `market_data_db`** populated by S3-owned worker
   calling upstream APIs. Effectively the same as #2 but with a denormalized
   intermediate layer; rejected as unnecessary.

L-5b implements option 2.

### §1.4 Current code references

- Lifespan task pattern to copy:
  `services/market-data/src/market_data/app.py:489` — `_screen_fields_refresh_loop`
  (the 6-hour static-field refresh loop) and
  `services/market-data/src/market_data/app.py:534` — `_computed_metrics_refresh_loop`
  (the daily 02:00 UTC worker for L-3, your closest analog).
- Snapshot table to extend:
  `services/market-data/src/market_data/infrastructure/db/models/fundamentals_snapshot.py`
  (currently has `next_earnings_date`, `next_dividend_date`, `insider_net_buy_90d`,
  plus the 4 L-4a + 7 L-2 columns; extend with the 6 new L-5b columns).
- HTTP client pattern: `services/market-data/src/market_data/infrastructure/clients/`
  (whatever sibling client exists for an upstream call — discover via
  `git grep -l "httpx.AsyncClient" services/market-data/src/`).
- Internal-JWT signing: `libs/observability/src/observability/internal_jwt.py`
  (existing pattern used by `InsiderUniverseLoader` for service-to-service
  authentication).

### §1.5 Proposed architecture

```
┌────────────────────────────────────────────────────────────────────┐
│ market-data service (S3)                                           │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │ lifespan task: _intelligence_rollup_loop (04:00 UTC)     │      │
│  │   (after L-3 02:00 + L-4b 03:00)                         │      │
│  └─────────────┬────────────────────────────────────────────┘      │
│                │                                                   │
│                ▼                                                   │
│  ┌────────────────────────────────────────────────────────┐        │
│  │ application/use_cases/sync_intelligence_rollup.py      │        │
│  │  - cursor-batched over instruments                     │        │
│  │  - for each batch:                                     │        │
│  │      asyncio.gather(                                   │        │
│  │        s6_client.get_news_rollup_7d(id),              │        │
│  │        s7_client.get_intelligence_rollup_7d(id),       │        │
│  │        s10_client.get_active_alert_flag(id),          │        │
│  │        s8_client.get_ai_brief_flag(id),               │        │
│  │      )                                                 │        │
│  │  - UPSERT into instrument_fundamentals_snapshot        │        │
│  │  - on per-endpoint failure: keep last_known + log     │        │
│  └─────────────┬──────────────────────────────────────────┘        │
│                │                                                   │
│                ▼                                                   │
│  instrument_fundamentals_snapshot (+ 6 new columns)                │
└────────────────────────────────────────────────────────────────────┘
            ▲           ▲           ▲           ▲
            │           │           │           │
   ┌────────┴────┐ ┌────┴────┐ ┌────┴───┐ ┌────┴────┐
   │ S6 nlp-pipe │ │ S7 KG   │ │ S10    │ │ S8 chat │
   │ /news-roll  │ │ /int-rl │ │ /alert │ │ /brief  │
   └─────────────┘ └─────────┘ └────────┘ └─────────┘
                    (L-5a endpoints, shipped)
```

### §1.6 Task breakdown (5 commits, ~3 engineer-days)

#### T-WL5B-01 — Extend `instrument_fundamentals_snapshot` with 6 new columns

- Add nullable columns to `services/market-data/src/market_data/infrastructure/db/models/fundamentals_snapshot.py`:
  - `news_count_7d: int | None`
  - `llm_relevance_7d_max: float | None`
  - `display_relevance_7d_weighted: float | None`
  - `recent_contradiction_count: int | None`
  - `has_active_alert: bool | None`
  - `has_ai_brief: bool | None`
- Add `intelligence_rollup_synced_at: datetime | None` so callers can see freshness.
- New alembic migration `032_add_l5b_intelligence_columns.py` chained from `031`.
  Idempotent (`ADD COLUMN IF NOT EXISTS`), R11 forward-compat (all nullable).

#### T-WL5B-02 — 4 typed HTTP clients

- New module `services/market-data/src/market_data/infrastructure/clients/intelligence_clients.py`.
- 4 classes: `S6NewsRollupClient`, `S7IntelligenceClient`, `S10AlertClient`, `S8BriefClient`.
- Each wraps `httpx.AsyncClient`, signs with internal JWT, parses response into
  a typed Pydantic model.
- **BP-235 trap**: every `httpx.AsyncClient` must explicitly set
  `timeout=httpx.Timeout(N)` when wrapped in `asyncio.wait_for`. httpx default
  5s fires before asyncio's outer timeout.
- Retry: 1 retry on 5xx / timeout; on second failure return `last_known_value`
  semantics (leave existing snapshot column unchanged).

#### T-WL5B-03 — Sync use case

- New file `services/market-data/src/market_data/application/use_cases/sync_intelligence_rollup.py`.
- `SyncIntelligenceRolloutOptions` dataclass: batch size (default 100), concurrency
  per upstream (default 4 parallel `gather`s), skip-if-fresh-within-hours
  (default 18 — stale-rollup is OK by 1 night).
- `SyncIntelligenceRolloutSummary`: per-upstream success / failure counters,
  per-instrument staleness counters.
- Cursor pattern mirroring `backfill_fundamental_metrics.py` and
  `computed_metrics_worker.py`.
- UPSERT into `instrument_fundamentals_snapshot` setting all 6 columns +
  `intelligence_rollup_synced_at = utc_now()`.

#### T-WL5B-04 — Lifespan task scheduling

- Add `_intelligence_rollup_loop` to `app.py` mirroring `_computed_metrics_refresh_loop`
  at line 534.
- Cadence: daily at **04:00 UTC** (after L-3 at 02:00 + L-4b at 03:00 — no
  contention with other refresh loops).
- 20-hour skip-guard.
- Env var: `INTELLIGENCE_ROLLUP_HOUR_UTC` (configurable per environment).
- Register in lifespan at the same call site as the other refresh loops
  (`app.py:451`).

#### T-WL5B-05 — Wire screener filters / sorts + lockstep

- Extend `ScreenFilterRequest` in
  `services/market-data/src/market_data/api/schemas/fundamental_metrics.py`:
  - `news_count_7d_{min,max}`
  - `llm_relevance_7d_max_{min,max}`
  - `display_relevance_7d_weighted_{min,max}`
  - `recent_contradiction_count_{min,max}`
  - `has_active_alert: bool | None`
  - `has_ai_brief: bool | None`
- Extend `query_screen` WHERE-clause builder + ORDER BY whitelist.
- Migration 032 also seeds 6 rows in `screen_field_metadata` (per the §3.2
  pattern; use `field_type='numeric'` or `'text'` per the CHECK; booleans get
  stored as `numeric` per BP-585).
- **LOCK-STEP**: append 6 entries to `_get_static_screen_fields()` in `app.py`
  (`services/market-data/src/market_data/app.py:42`), BYTE-IDENTICAL to the
  migration seeds — verified by a new `test_l5b_migration_lockstep.py`
  mirroring `test_l3_migration_lockstep.py`.

#### T-WL5B-06 — Tests + docs

- Unit tests:
  - `test_sync_intelligence_rollup.py`: each client mocked; success / partial-failure /
    all-failure scenarios; stale-fallback (assert previous snapshot column
    untouched).
  - `test_intelligence_clients.py`: timeout handling, retry budget,
    internal-JWT header presence, BP-235 timeout assertion.
- Integration test: spin up testcontainers Postgres, fake the 4 upstreams via
  `respx`, run the worker, assert 6 columns populated.
- Update `docs/plans/0089-pages/I-screener-plan.md` §3.2 L-5 row: "L-5b shipped (DATE)".
- New runbook `docs/runbooks/intelligence-rollup-worker.md`:
  - Schedule, expected runtime (estimate 30 min for 3000 instruments × 4
    upstream calls each at ~50ms = 30 min sequential, much less with batch
    concurrency 4).
  - Failure modes: upstream service down → soft-fail keeps last-known values;
    partial-failure logs WARNING; total-failure logs ERROR + skips that night.
  - Metrics to watch: `intelligence_rollup_synced_at` age across the universe.

### §1.7 Open architecture decisions (need a call before T-WL5B-01)

1. **Stale-data semantics**: when S6 is down for a night, do we (a) leave the
   previous `news_count_7d` value in place + log a WARNING, or (b) set to
   `NULL` so screener filters exclude the row? Audit recommends (a) — less
   surprising to the user — but it does mean stale data can persist invisibly
   if S6 stays down for days. Recommendation: ship with (a), add a freshness
   gauge column to the snapshot (`intelligence_rollup_synced_at`), surface
   "data is N hours stale" in the IB-L5 UI.
2. **`has_active_alert` freshness**: alerts can fire any time of day; a
   nightly rollup means a 12-hour latency. Audit raised the option of S3
   subscribing to the existing `alert.created.v1` Kafka topic for sub-nightly
   freshness. **Defer to v2** — ship L-5b with nightly first, watch the user
   complaints, then upgrade only if needed.
3. **`has_ai_brief` semantics**: the S8 endpoint returns true when a public
   brief exists in `user_briefs` keyed `entity_id == instrument_id`. Does
   "AI brief" mean "today's brief" or "any historical brief"? Audit
   recommends "today's" (per the morning-brief generation cadence). Confirm
   with product before T-WL5B-03.

### §1.8 Validation gate (pre-merge)

- ruff + mypy clean on `services/market-data/src/`
- 6 new screener fields registered + 6 new rows in `_get_static_screen_fields()`
- migration 032 cycle: up → down → up clean
- new lockstep test passes
- intelligence-rollup integration test against testcontainers Postgres passes
- full market-data unit suite still 893+ tests pass

### §1.9 Definition of done

- L-5b worker runs in staging for 1 week without ERROR-level logs
- `intelligence_rollup_synced_at` shows < 25 hours age for > 95% of instruments
- Manual screener query with `news_count_7d_min=5` returns instruments
- IB-L5 frontend (separate work — §2 of this plan) is unblocked

---

## §2. IB-L3 / IB-L4 / IB-L5 frontend waves

### §2.1 What they are

Three frontend waves that wire the 17 backend fields shipped in this session
(L-3, L-4a + L-4b, L-5a + L-5b after §1) into the screener UI as filter rows,
opt-in columns, and chip-strip surfaces. Each wave follows the IB-L2 pattern
shipped this session under `feat/plan-0089-wi-b-l2`.

| Wave | Fields | Source plan |
|------|--------|-------------|
| IB-L3 | 8 returns + 52W distance | `docs/plans/0089-pages/I-screener-plan.md` §6.1 Block IB-L3 |
| IB-L4 | 5 analyst/insider/ownership | `…` §6.1 Block IB-L4 |
| IB-L5 | 7 intelligence filters + 2 columns | `…` §6.1 Block IB-L5 |

### §2.2 Why each matters

- **IB-L3**: this is the most-requested screener feature for portfolio managers
  ("show me names within 5% of their 52-week high with positive 1Y RTN"). The
  data is now there; without this frontend wave it stays invisible.
- **IB-L4**: "INSIDER 90D ≥ $1M" + "ANALYST UPSIDE ≥ 15%" are the canonical
  alpha-discovery filters in Bloomberg EQS. Shipping these closes the
  feature-parity gap with the user's Bloomberg muscle memory.
- **IB-L5**: the intelligence-layer filters are the differentiator vs. Bloomberg
  — "show me names with news_count_7d ≥ 5 and at least one contradiction".
  Gated on §1 L-5b.

### §2.3 Reference implementation — IB-L2 (shipped, study this)

Every IB-L3/L4/L5 wave should look exactly like IB-L2's diff structure:

1. Add column defs to `apps/worldview-web/components/screener/ag-screener-columns.tsx`
   (one block per opt-in column, with `tabular-nums font-mono`,
   `bg-bull / bg-bear` for percent cells, etc.).
2. Add filter rows to `apps/worldview-web/components/screener/ScreenerFilterBar.tsx`
   (range inputs for numerics; multi-select for credit-rating-like discretes).
3. Extend `FilterState` in `apps/worldview-web/features/screener/lib/filter-state.ts`
   with new optional fields.
4. Extend `apps/worldview-web/features/screener/lib/build-filters.ts` to map
   `FilterState` → `ScreenFilterRequest`. **Critical**: field names must match
   the backend Pydantic schema BYTE-FOR-BYTE — prompt-input vs lookup mismatch
   is a silent-drop bug per the user's feedback memory.
5. Extend `apps/worldview-web/features/screener/lib/active-counts.ts` so the
   "active filter count" badge in the header reflects new chips.
6. Remove the `BackendPendingBadge` from the field's row in
   `IntelligenceFilterGroup.tsx` (only IB-L5) or `ScreenerFilterBar.tsx` row
   (IB-L3/L4).
7. Vitest: format assertion for each column, filter chip render, range
   propagation through `build-filters`.
8. Playwright: skip-aware E2E spec mirroring `screener-fundamentals-columns.spec.ts`.

### §2.4 IB-L3 — Returns + 52W distance (~1 engineer-day)

**Status**: unblocked (L-3 backend shipped in this session).

#### Fields

| Backend field | Header | Format | Default? | Filter |
|--------------|--------|--------|----------|--------|
| `dist_from_52w_high_pct` | `52W%↑` | percent_1 | opt-in | range |
| `dist_from_52w_low_pct` | `52W%↓` | percent_1 | opt-in | range |
| `return_1m` | `1M RTN` | percent_1 | opt-in | range |
| `return_3m` | `3M RTN` | percent_1 | opt-in | range |
| `return_6m` | `6M RTN` | percent_1 | opt-in | range |
| `return_ytd` | `YTD RTN` | percent_1 | opt-in | range |
| `return_1y` | `1Y RTN` | percent_1 | opt-in | range |
| `return_3y` | `3Y RTN` | percent_1 | opt-in | range |

#### Tasks

- T-IB3-01: 8 column defs in `ag-screener-columns.tsx` (Performance / Technical groups).
- T-IB3-02: 8 range-filter rows in `ScreenerFilterBar.tsx` under new "Performance"
  section.
- T-IB3-03: `FilterState` + `build-filters` + `active-counts` updates.
- T-IB3-04: Vitest — format assertions: `0.124 → "+12.4%"`,
  `-0.034 → "−3.4%"`, `null → "—"`; sign-coloring (positive bull green,
  negative bear red).
- T-IB3-05: Playwright `screener-returns-cols.spec.ts` (skip-aware under
  `E2E_AUTH`).
- T-IB3-06: TRACKING + plan §6.1 IB-L3 row marked done; remove `BackendPendingBadge`
  from any preset that referenced these fields.

#### Validation

`pnpm typecheck && pnpm lint && pnpm vitest run components/screener/ features/screener/lib/`

### §2.5 IB-L4 — Analyst / Insider / Ownership (~1 engineer-day)

**Status**: unblocked (L-4a + L-4b shipped in this session).

#### Fields

| Backend field | Header | Format | Notes |
|--------------|--------|--------|-------|
| `analyst_target_price` | `ANALYST TGT` | currency_2 | absolute USD |
| (derived: `target / price - 1`) | `ANALYST UPSIDE` | percent_1 | **client-side** computed |
| `analyst_consensus_rating` | `CONSENSUS` | decimal_2 (1-5 scale) | post-mitigation: higher=bullish |
| `insider_net_buy_90d` | `INSIDER 90D` | currency_compact | USD; positive = net buying |
| `institutional_ownership_pct` | `INST OWN%` | percent_1 | stored as fraction |
| `short_percent` | `SHORT %` | percent_1 | stored as fraction |

#### Special items

1. **`ANALYST UPSIDE` is a derived field** — backend does not expose it as a
   column. Compute client-side as `(analyst_target_price / price) - 1`.
   Sort cannot be backend-driven; either (a) client-side sort by computed
   value, (b) defer to L-4-extension where the backend exposes a derived
   column.
2. **Consensus rating semantics**: the mitigation commit unified scale so
   higher = more bullish across both text and numeric inputs. Color the
   cell `text-bull` when ≥ 4, `text-bear` when ≤ 2, `text-muted-foreground`
   otherwise.
3. **Insider universe gap**: until §3 of this plan (L-4b universe
   activation), `insider_net_buy_90d` is non-null for only 3 tickers
   (AAPL/TSLA/AMZN). Frontend should NOT render zero for unknown — render
   `—` (the same null sentinel the credit rating uses).

#### Tasks

- T-IB4-01: 5 backend column defs + 1 derived column.
- T-IB4-02: 5 range-filter rows (no filter for ANALYST UPSIDE in v1 since
  derived).
- T-IB4-03: `FilterState` + `build-filters` + `active-counts`.
- T-IB4-04: Vitest — consensus tone classifier, insider compact-currency
  formatter (`+$1.2M` / `−$340K` / `—`), upside derivation when
  `analyst_target_price IS NULL` returns `—`.
- T-IB4-05: Playwright `screener-analyst-cols.spec.ts`.
- T-IB4-06: TRACKING + plan §6.1 IB-L4 row.

### §2.6 IB-L5 — Intelligence rollups (~1 engineer-day)

**Status**: GATED on §1 L-5b.

#### Fields

| Backend field | Surface | Default? |
|--------------|---------|----------|
| `news_count_7d` | `NEWS 7D` column + filter | opt-in column, filter in IntelligenceFilterGroup |
| `llm_relevance_7d_max` | filter only | row in IntelligenceFilterGroup |
| `display_relevance_7d_weighted` | `BRIEF SCORE` column + filter | opt-in column |
| `recent_contradiction_count` | filter only | row in IntelligenceFilterGroup |
| `has_active_alert` | boolean toggle | row in IntelligenceFilterGroup |
| `has_ai_brief` | boolean toggle | row in IntelligenceFilterGroup |
| `next_earnings_date` (window) | `next_earnings_within_days` filter | row (already L-5c) |
| `next_dividend_date` (window) | `next_dividend_within_days` filter | row (already L-5c) |

#### Tasks

- T-IB5-01: 2 column defs (NEWS 7D, BRIEF SCORE) in `ag-screener-columns.tsx`.
- T-IB5-02: Flip 7 `backendReady` flags in `IntelligenceFilterGroup.tsx` to
  `true` — this removes 7 `BackendPendingBadge` instances and unlocks the rows.
- T-IB5-03: Wire the 7 filter rows' state → `FilterState`.
- T-IB5-04: Stale-rollup UX: read `intelligence_rollup_synced_at` from the
  screener response (need to confirm L-5b plumbs this through `ScreenResult`);
  render a "data N hours stale" tooltip on the IntelligenceFilterGroup header
  when age > 25 hours.
- T-IB5-05: Vitest — IntelligenceFilterGroup row enablement, stale-tooltip
  threshold, boolean toggle round-trips.
- T-IB5-06: Playwright `screener-intelligence-filters.spec.ts`.
- T-IB5-07: TRACKING + plan §6.1 IB-L5 row.

### §2.7 Cross-wave considerations

- After all three waves, the opt-in column count grows from current 6
  (L-2 fundamentals snapshot) to 6 + 8 (L-3) + 5 (L-4) + 2 (L-5) = 21 opt-in
  columns. Plan §6.3 caps default-visible at 14 — this is already enforced
  by `fh-column-count-cap`. ColumnSettingsPopover's existing warning at >14
  selected stays load-bearing.
- The `BACKEND_PENDING_KEYS` set in `ColumnSettingsPopover.tsx` is currently
  empty (IB-L2 emptied it). Stays empty after IB-L3/L4 — every field is
  backend-ready. After IB-L5, also empty.

---

## §3. L-4b insider universe activation

### §3.1 What it is

The L-4b backend shipped two universe-management pieces:

1. **`InsiderUniverseLoader`** in `services/market-ingestion/src/market_ingestion/infrastructure/workers/insider_universe_loader.py`
   — an operator-callable worker that pages the new market-data internal
   endpoint `GET /internal/v1/instruments/ohlcv-covered`, then UPSERTs
   `sched_policies` rows for each ticker telling the EODHD insider polling
   system to fetch that instrument's transactions.
2. The pre-existing hardcoded 3-ticker baseline in
   `services/market-ingestion/alembic/versions/0002_initial_seeds.py:352`
   that still ships in the seed migration: `["AAPL", "TSLA", "AMZN"]`.

The loader exists in code but is **not scheduled** anywhere. It has to be
explicitly invoked by an operator (e.g., `python -m market_ingestion.scripts.run_insider_universe_loader`,
or via a manual `kubectl run`).

### §3.2 Why it matters

- The `insider_net_buy_90d` column populated by the L-4b worker pulls from
  the `insider_transactions` table, which is fed by the EODHD insider-
  transactions consumer, which is fed by the market-ingestion EODHD insider
  poller, which is gated by `sched_policies` entries.
- Today, only 3 instruments have `sched_policies` entries for insider
  transactions. So the `insider_transactions` table has rows for those 3
  instruments only. So `insider_net_buy_90d` is non-null for AAPL / TSLA /
  AMZN only.
- IB-L4 frontend (§2.5) showing `INSIDER 90D` column for all instruments
  but only ~3 having values is a poor UX — it looks like a bug.
- A screener filter `insider_net_buy_90d_min = 1_000_000` will return ~3
  candidates instead of the universe-wide hit list it should produce.

### §3.3 Why it was deferred — EODHD credit budget

Activating the loader means **all** OHLCV-covered instruments (~3000 today,
growing) get weekly insider polling. EODHD pricing per the audit
(`docs/audits/2026-05-28-wave-l4-scope-investigation.md` §7.1):

| Universe size | Cadence | Monthly EODHD credits |
|--------------|---------|----------------------|
| 3000 | Weekly (Mon morning) | ~13,000 |
| 3000 | Monthly | ~3,100 |
| 3000 | Quarterly | ~1,030 |

The audit recommends weekly — insider-transaction value lives in being
quasi-real-time. But ~13k credits/month is a non-trivial spend increase
that should not happen silently as a side effect of merging an integration
PR.

### §3.4 What activating it looks like (the actual work)

The decision is the gating item, not the implementation. Implementation is
either:

**Option A — Schedule as lifespan task in market-ingestion**

- Add `_insider_universe_refresh_loop` to `services/market-ingestion/src/market_ingestion/app.py`,
  modelled on existing scheduled tasks in that service.
- Cadence: weekly (e.g., Mon 06:00 UTC).
- Calls `InsiderUniverseLoader.run()` (the existing method).
- The loader internally calls market-data's `/internal/v1/instruments/ohlcv-covered`,
  pages the result, upserts `sched_policies`.
- Env var: `INSIDER_UNIVERSE_REFRESH_HOUR_UTC` and `INSIDER_UNIVERSE_REFRESH_DAY_OF_WEEK`.
- ~2 hours of work + tests.

**Option B — Document as ops runbook**

- Write `docs/runbooks/insider-universe-loader.md` describing how to invoke
  manually.
- The ops team runs it before each release / as part of a quarterly review.
- Zero credit auto-spend; manual cadence.
- ~30 min of work, all documentation.

**Option C — Hybrid**

- Schedule but gate behind an env var that defaults to OFF in all environments.
- Operator flips it on in staging first, observes credit burn, then enables
  in prod.
- ~2 hours of work + 1 hour of staging observation.

### §3.5 Recommended sequencing

1. **Get budget-owner approval first** for the ~13k credits/month spend
   (or pick a slower cadence). This is the gating step; do not skip.
2. Implement Option C (gated schedule). Defaults to OFF.
3. After approval, flip the env var ON in staging, monitor `sched_policies`
   row count growth + EODHD response codes for 1 week.
4. Enable in prod.
5. IB-L4 frontend (§2.5) can ship in parallel — the field will start
   populating universe-wide as the loader runs.

### §3.6 Files affected

- `services/market-ingestion/src/market_ingestion/app.py` (add scheduled task)
- `services/market-ingestion/src/market_ingestion/config.py` (add env vars)
- `services/market-ingestion/src/market_ingestion/infrastructure/workers/insider_universe_loader.py`
  (already exists; no change unless adding telemetry)
- New runbook `docs/runbooks/insider-universe-loader.md`
- New tests for the scheduled task

---

## §4. Migration 031 deploy-window sequencing

### §4.1 What it is

Migration `031_extend_field_type_check.py` (shipped in
`feat/plan-0089-wl-5c-fix-date-type`) does three things in sequence:

1. `ALTER TABLE screen_field_metadata DROP CONSTRAINT ck_screen_field_metadata_field_type;`
2. `ALTER TABLE screen_field_metadata ADD CONSTRAINT ck_screen_field_metadata_field_type CHECK (field_type IN ('numeric', 'text', 'date'));`
3. `UPDATE screen_field_metadata SET field_type = 'date' WHERE field_name IN ('next_earnings_date', 'next_dividend_date');`

Between steps 1 and 2 there is a brief window (milliseconds) where the
constraint is dropped. If another connection tries to write to
`screen_field_metadata` with `field_type = 'invalid'` during that
millisecond, the row is accepted.

### §4.2 Why it matters

- In practice this is a near-zero-impact issue because the only writers to
  `screen_field_metadata` are (a) alembic migrations (serialized via
  alembic's own advisory lock), and (b) the `_screen_fields_refresh_loop`
  that runs every 6 hours and only inserts known-valid field_types from
  `_get_static_screen_fields()`.
- The risk window for a bad write is bounded by the duration between the
  DROP and ADD CONSTRAINT statements (microseconds in Postgres) AND by a
  concurrent writer attempting an invalid value. Unless a malicious or
  buggy migration is racing it, you will never observe a bad row.
- However, the existing deploy runbook does not warn about it. A future
  operator running migrations across many services in parallel might
  introduce contention.

### §4.3 The fix

This is just a runbook note, not code work. Add to the existing market-data
deploy runbook (`docs/services/market-data.md` or wherever the migrate
section lives) a one-line entry:

> Migration 031 briefly drops the `ck_screen_field_metadata_field_type`
> CHECK constraint between DROP and ADD. Run it during a quiet window
> (no concurrent screener field refresh) or accept the millisecond risk —
> the `_screen_fields_refresh_loop` only writes known-good values so
> contention is effectively zero in normal operation.

### §4.4 Files affected

- `docs/services/market-data.md` (or `docs/runbooks/migrations.md` if it exists)
- ~10 minutes of work

---

## §5. L-3 production smoke test + runbook fill-in

### §5.1 What it is

The L-3 `ComputedMetricsBackfillWorker` runs nightly at 02:00 UTC and
computes 8 metrics × ~3000 instruments × ~1100 daily-bar lookbacks via three
LATERAL JOINs each. The session shipped:

- The BP-180 cast fix that makes the worker actually write rows (previously
  it silently completed with `metrics_written=0`).
- A perf smoke test (`tests/integration/test_computed_metrics_worker_perf.py`)
  that runs against testcontainers Postgres with 50 instruments × 800 bars
  and asserts wall-clock < 30s.
- A runbook (`docs/runbooks/computed-metrics-worker.md`) with placeholders
  for the production wall-clock and the `fallback_adjusted_close_count`
  baseline.

### §5.2 Why it matters

- The 30-second testcontainers budget is a smoke threshold, not a production
  target. Production wall-clock at 3000 × 1100 bars is expected to be 5-15
  minutes but has never been measured.
- The lifespan task has a 20-hour skip-guard: if a previous run is still
  going (or its completion timestamp is < 20 hours ago), the next run is
  skipped. If production runs take > 20 hours due to a bad index plan or
  scaling change, the daily refresh silently stops. There is no alert today.
- The `fallback_adjusted_close_count` metric tracks instruments where
  `adjusted_close IS NULL` and the worker fell back to `close`. A high
  fallback rate indicates a corporate-actions / split-adjustment data
  gap upstream. Without a baseline, we cannot tell if the count is
  "normal" or anomalous.

### §5.3 The work

Three small follow-ups, all post-staging-deploy:

#### T-WL3-FILL-01 — Run the worker once in staging, capture numbers

- After the integration PR merges and a staging deploy, manually trigger
  `_computed_metrics_refresh_loop` (or wait for the 02:00 UTC scheduled
  run) and capture from structlog:
  - Wall-clock from start → finish
  - `instruments_processed`
  - `metrics_written` (should be ~8 × instruments_processed)
  - `fallback_adjusted_close_count`
- Write those numbers into `docs/runbooks/computed-metrics-worker.md` so
  future operators have baselines.

#### T-WL3-FILL-02 — Add Prometheus / alert metric

- Currently the worker logs the summary at INFO. There is no Prometheus
  gauge or counter exposing it.
- Add a counter `computed_metrics_worker_runs_total{outcome="success|skipped|failed"}`
  and a gauge `computed_metrics_worker_last_success_timestamp_utc_seconds`.
- Wire an alert: if `time() - last_success > 26 * 3600` then fire (allows
  2 hours of slack for a slow run).
- ~2 hours.

#### T-WL3-FILL-03 — EXPLAIN ANALYZE the slowest LATERAL JOIN

- The `return_1y` SQL (252-day lookback) is the deepest LATERAL JOIN. Run
  `EXPLAIN ANALYZE` against the production-shaped DB and verify the
  `(instrument_id, bar_date DESC)` index is being used.
- If the planner picks a sequential scan, add a hint or a
  partial index for `bar_date > NOW() - INTERVAL '270 days'`.
- Document the EXPLAIN output in the runbook for future regression-checking.
- ~2 hours.

### §5.4 Definition of done

- Runbook contains real numbers, not placeholder text.
- Prometheus alert wired.
- EXPLAIN ANALYZE output checked in.
- The worker has run cleanly in staging for 5 consecutive nights.

---

## §6. Cross-session contamination commit (`c60c7810`)

### §6.1 What it is

Commit `c60c7810` on `feat/plan-0099-w4` has the subject:

> feat(plan-0089-wi-a): T-IA-05+07 mount IntelligenceFilterGroup + GICS cascade scaffold

But its diff also includes `services/rag-chat/tests/unit/test_app_deploy_token_cache_flush.py`
(+133 lines), which is a legitimate PLAN-0097 W4 test for the
`_maybe_flush_completion_cache` function. The test was meant to be in commit
`8906009f` (`feat(rag-chat,libs/messaging): PLAN-0097 W4 T-W4-04 — deploy-version cache flush on startup`)
but it ended up in `c60c7810` due to a pre-commit hook stash/restore race
(BP-590 / BP-065) while two parallel Claude sessions were committing.

### §6.2 Why it matters (or doesn't)

- The test content is correct and useful. Deleting it loses real PLAN-0097
  test coverage.
- The commit subject is misleading: it says "GICS cascade scaffold" but the
  diff has a rag-chat test in it.
- `git bisect` and `git log -p <path>` will show the rag-chat test as
  "added by the GICS commit", which is confusing for a future archaeologist
  but does not affect runtime behavior.
- A `git revert c60c7810` would also revert the legitimate
  `IntelligenceFilterGroup.tsx` work, breaking everything downstream.

### §6.3 Options

**Option A — Leave as-is (recommended)**

- Cost: 0 minutes. Cosmetic git history mess.
- Risk: an operator running `git log services/rag-chat/tests/unit/test_app_deploy_token_cache_flush.py`
  will see the screener commit attributed. Confusing but not harmful.

**Option B — Interactive rebase to split the commit**

- Cost: ~30 min + risk of rewriting shared history.
- Requires force-push if the branch was already pushed.
- Could break sibling branches that descend from `c60c7810`.
- Since `feat/plan-0099-w4` is the only descendant and has not been pushed
  yet, this is technically safe. But it changes 30+ commit SHAs downstream
  of `c60c7810`.
- Not worth the risk for a cosmetic issue.

**Option C — File a `docs/audits/` note**

- Cost: ~5 min.
- Write a one-paragraph entry in
  `docs/audits/2026-05-28-cross-session-commit-contamination.md` documenting
  the incident, the commit SHA, and the file that should logically belong
  to commit `8906009f`.
- Future archaeologists running `git log` see a confused attribution; they
  also find the audit note explaining it.
- This is the lowest-cost meaningful improvement.

### §6.4 Recommendation

**Pick Option C.** The audit note is a 5-minute write, leaves history intact,
and prevents the "why is this rag-chat test in a screener commit?" question
from becoming a small mystery in 6 months. Take no other action.

### §6.5 Files affected (if Option C)

- New file `docs/audits/2026-05-28-cross-session-commit-contamination.md`
- ~5 min of work

---

## §7. Recommended scheduling order

| Order | Item | Effort | Blocking? |
|-------|------|--------|-----------|
| 1 | §4 Migration 031 runbook note | 10 min | Pre-deploy nice-to-have |
| 2 | §6 Cross-session audit note | 5 min | Pre-merge nice-to-have |
| 3 | §3 L-4b insider universe — get budget approval | external | Decision-only |
| 4 | §5.1 L-3 staging smoke + runbook fill | 30 min in staging | After integration PR merges |
| 5 | §5.2 L-3 Prometheus alert | 2 hours | Pre-prod cutover |
| 6 | §5.3 L-3 EXPLAIN ANALYZE | 2 hours | Pre-prod cutover |
| 7 | §3 L-4b universe activation (Option C) | 2 hours | After §3 step 3 (approval) |
| 8 | §1 L-5b sync worker | 3 engineer-days | Unblocks IB-L5 |
| 9 | §2.4 IB-L3 frontend | 1 engineer-day | Independent |
| 10 | §2.5 IB-L4 frontend | 1 engineer-day | Best after §3 ships |
| 11 | §2.6 IB-L5 frontend | 1 engineer-day | After §8 (L-5b) ships |

**Critical path to "full IB-L5 in production"**: §1 → §2.6 = 4 engineer-days.

**Critical path to "IB-L3 + IB-L4 in production"** (skipping intelligence
layer for now): §3 approval → §2.4 + §2.5 = 2 engineer-days + 1 budget
decision.

**Lowest-effort path to "screener UI feels complete"**: skip §1 + §2.6, ship
IB-L3 + IB-L4 only, leave IB-L5 disabled with `BackendPendingBadge` for now.
Users see a richer screener and the intelligence-layer gap is a single
visible "coming soon" pill rather than seeming broken. ~2 engineer-days of
frontend work after the §3 budget decision.

---

## §8. Definition of done for ALL of PRD-0089 Wave I

Every item in §1–6 closes plus:

- All 39 backend screener fields have IB-L\* frontend surfaces.
- Zero `BackendPendingBadge` instances render in `IntelligenceFilterGroup` or
  `ColumnSettingsPopover` at default render.
- Plan §10 Wave I-B Definition of Done can be checked off (one §10 entry per
  block; today the `IntelligenceFilterGroup` row is the last open
  acceptance criterion).
- `docs/plans/TRACKING.md` PRD-0089 row reflects all 9 sub-waves shipped.
