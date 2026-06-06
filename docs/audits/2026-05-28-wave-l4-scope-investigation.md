# Wave L-4 Scope Investigation — Analyst / Insider / Ownership / Short Rollups

**Audit date**: 2026-05-28
**Author**: backend research agent (read-only)
**Plan ref**: `docs/plans/0089-pages/I-screener-plan.md` §3.2 (Wave L-4)
**Scope**: 5 screener fields — `analyst_target_price`, `analyst_consensus_rating`,
`insider_net_buy_90d`, `institutional_ownership_pct`, `short_percent` —
plus derived `analyst_upside_pct` column.

**Headline finding**: 4 of the 5 fields are *already ingested and persisted*
(EODHD fundamentals → JSONB rows). The work is dominated by **rollup ETLs**
that project these into a screener-friendly column shape, **not** by new
provider integrations. Insider 90d is the only field requiring genuinely
new ingestion (the time-series endpoint is wired but only polls 3 tickers
and lands as passthrough envelopes — no consumer persists transaction rows).
Realistic effort is ~3 engineer-days, not the ~2 d in plan §3.2.

---

## §1. Source-data inventory

All 5 fields come from EODHD (the only provider already covering them at full
universe scale per `docs/references/eodhd-endpoints-reference.md`). Two
distinct EODHD endpoints supply them:

### 1.1 EODHD `/fundamentals/{TICKER}` (already wired, weekly poll, 10 credits)

Confirmed routed through `EodhdProvider.fetch_fundamentals`
(`services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/eodhd.py:192`)
and dispatched into sections by
`canonicalize.py:184-238`. Relevant sections for L-4:

| L-4 field | EODHD section / key | Cite |
|-----------|---------------------|------|
| `analyst_target_price` | `AnalystRatings.TargetPrice` and `Highlights.WallStreetTargetPrice` | `metric_extractor.py:93,183` |
| `analyst_consensus_rating` | `AnalystRatings.Rating` (1.0–5.0 scale; also `Buy/Hold/Sell/StrongBuy/StrongSell` vote counts) | `metric_extractor.py:96-106` |
| `institutional_ownership_pct` | `SharesStats.PercentInstitutions` (decimal, e.g. `0.605` = 60.5%) | `docs/references/eodhd-endpoints-reference.md:1891` |
| `short_percent` | `SharesStats.ShortPercentOfFloat` *or* `Technicals.ShortPercent` (decimal) | `docs/references/eodhd-endpoints-reference.md:183, 1894, 305` |

**Cost / cadence**: fundamentals endpoint costs **10 credits/call**
(`eodhd.py:223`). Polling interval is **weekly** for the entire fundamentals
bundle (`alembic/versions/0005…` → 604800 s), so these 4 fields refresh
piggybacked on the existing schedule — **zero additional credit cost** for
L-4.

### 1.2 EODHD `/insider-transactions` (already wired, weekly, 1 credit, US-only)

`EodhdProvider.fetch_insider_transactions`
(`eodhd.py:501-549`) returns the SEC Form 4 list (transactionDate, ownerName,
transactionCode P/S/A/D, transactionAmount, transactionPrice). Endpoint cost
**1 credit/call**; weekly poll cadence per `0006_weekly_insider_transactions.py`.

**Coverage gap (BLOCKER for `insider_net_buy_90d`)**:
1. The polling policy currently registers this endpoint for only 3 tickers
   (AAPL/TSLA/AMZN per migration `0006`’s commit message). The screener
   needs **universe-wide** insider data (~10k US instruments).
2. Insider data flows as a **passthrough envelope**
   (`canonicalize.py:23-65,_PASSTHROUGH_TYPES`) — there is **no consumer
   that persists individual transactions into a table**. The
   `insider_transactions_snapshot` table stores only the *embedded snapshot*
   from the fundamentals payload (`canonicalize.py:238`), which is a
   summary, not a transaction list.
3. EODHD coverage is **US companies only, past 1 year** per
   `eodhd-endpoints-reference.md:3999`.

### 1.3 Refresh trigger / time semantics

- Analyst target, consensus, inst-ownership, short %: **snapshots**
  (current value); refresh on the existing fundamentals weekly tick.
- `insider_net_buy_90d`: **rolling 90-day windowed aggregate** — must be
  recomputed daily (the window slides) or on-insert of new Form 4 rows.

---

## §2. Existing storage

### 2.1 What already exists

- `analyst_consensus` table (JSONB section) — populated by
  `FundamentalsRepository.upsert_analyst_consensus`
  (`fundamentals_repo.py:87`); FundamentalsConsumer route at
  `fundamentals_consumer.py:65,90`.
- `share_statistics` table (JSONB section) — populated by
  `upsert_share_statistics` (`fundamentals_repo.py:81`); contains the raw
  `PercentInstitutions`, `PercentInsiders`, `ShortPercentOfFloat`.
- `technicals_snapshot` table — contains `ShortPercent`, `Beta`, 52W highs
  (`fundamentals_consumer.py` dispatch). Note `metric_extractor.py:85-91`
  currently extracts only `beta`, `avg_volume_30d` — **not** the short %.
- `insider_transactions_snapshot` table (JSONB) — single-row snapshot from
  the fundamentals payload, not a time-series.
- `institutional_holders` and `fund_holders` tables (JSONB lists of top
  holders) — populated; used by `/v1/fundamentals/{id}/institutional-holders`
  (`fundamentals.py:474-489`).

### 2.2 Coverage in `fundamental_metrics` (the screener’s primary table)

`metric_extractor.py:92-105` already produces these `(metric, period_type, value)`
rows from the `ANALYST_CONSENSUS` section:

- `target_price` (numeric)
- `analyst_rating` (**text only** — `metric_extractor.py:96-100`, `text_only=True`)
- `analyst_buy`, `analyst_hold`, `analyst_sell`, `analyst_strong_buy`,
  `analyst_strong_sell` (numeric counts)

And from `HIGHLIGHTS`: `wall_street_target_price` (`metric_extractor.py:182-185`).

### 2.3 Gaps

- `institutional_ownership_pct`, `short_percent`, `insider_pct_holdings`
  are **NOT** in `metric_extractor.py` despite `share_statistics` /
  `technicals_snapshot` JSON containing them — must be added.
- `analyst_rating` is stored as `value_text` because EODHD returns it as
  string. For screener `min/max` to work it must be **stored as numeric**
  (1.0–5.0 scale) when parseable. Test `test_metric_extractor.py:475`
  already covers `"Rating": "2.5"` → text — confirming the regression risk.
- No `insider_net_buy_90d` aggregate anywhere.

---

## §3. Rollup ETL design

### 3.1 Per-field plan

| L-4 field | Source row | Aggregate | Target column |
|-----------|------------|-----------|---------------|
| `analyst_target_price` | `fundamental_metrics.metric='target_price'` (already extracted) OR `analyst_consensus.data->>'TargetPrice'` | latest `as_of_date` per instrument | `instrument_fundamentals_snapshot.analyst_target_price NUMERIC(18,4)` |
| `analyst_consensus_rating` | `analyst_consensus.data->>'Rating'` (cast to numeric); if non-numeric, derive from `(StrongBuy×1 + Buy×2 + Hold×3 + Sell×4 + StrongSell×5) / total` | latest | `instrument_fundamentals_snapshot.analyst_consensus_rating NUMERIC(4,2)` |
| `institutional_ownership_pct` | `share_statistics.data->>'PercentInstitutions'` (decimal 0–1, multiply ×100 to %) | latest | `instrument_fundamentals_snapshot.institutional_ownership_pct NUMERIC(6,3)` |
| `short_percent` | `share_statistics.data->>'ShortPercentOfFloat'` (decimal) OR `technicals_snapshot.data->>'ShortPercent'` | latest, prefer ShortPercentOfFloat | `instrument_fundamentals_snapshot.short_percent NUMERIC(6,3)` |
| `insider_net_buy_90d` | new `insider_transactions` table (must be created + populated) | `SUM(CASE code='P' THEN amount ELSE 0) - SUM(CASE code='S' THEN amount ELSE 0)` over last 90d | `instrument_fundamentals_snapshot.insider_net_buy_90d BIGINT` (share count; positive = net buying) |

### 3.2 Storage strategy

**Recommendation: extend `instrument_fundamentals_snapshot`** rather than
create a new table. The L-2 work already established this table as the
single source for screener `metrics: dict` output
(`fundamental_metrics_query.py:_SNAP_FIELDS`,
`fundamentals_snapshot.py:32`). Adding 5 nullable columns is forward-compat
(R11) and lets `query_screen` simply extend the existing
`outerjoin(snap, instr.id == snap.instrument_id)` clause already at
`fundamental_metrics_query.py:191`.

### 3.3 Refresh triggers

- **Snapshot fields (4 fields)**: extend the existing
  `fundamentals_snapshot_writer.py` flow. The FundamentalsConsumer
  receives `analyst_consensus` / `share_statistics` / `technicals_snapshot`
  records and is the natural insertion point — after `upsert_*` succeeds,
  emit/upsert into `instrument_fundamentals_snapshot` in the same UoW.
- **`insider_net_buy_90d`**: nightly cron + on-insert backfill.

### 3.4 New `insider_transactions` table (REQUIRED for `insider_net_buy_90d`)

Schema (target `market_data_db`, R24 OK since this is market-data’s domain):

```
CREATE TABLE insider_transactions (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  instrument_id       UUID NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
  transaction_date    DATE NOT NULL,
  report_date         DATE NOT NULL,
  owner_name          TEXT NOT NULL,
  owner_title         TEXT,
  transaction_code    CHAR(1) NOT NULL,        -- P/S/A/D/F/M/C/G/J/K/V
  transaction_amount  BIGINT NOT NULL,
  transaction_price   NUMERIC(18,4),
  acquired_disposed   CHAR(1),                 -- 'A' / 'D'
  post_txn_amount     BIGINT,
  sec_link            TEXT,
  ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (instrument_id, transaction_date, owner_name, transaction_code, transaction_amount)
);
CREATE INDEX ix_insider_txn_instrument_date ON insider_transactions(instrument_id, transaction_date DESC);
```

This new table + a `InsiderTransactionsConsumer` consuming the existing
passthrough envelope topic is the highest-risk piece of L-4.

---

## §4. Database / schema work

**Migration count: 2 net new** (both in `services/market-data/alembic/`):

1. **`025_l4_snapshot_columns_and_insider_txns.py`** —
   `ALTER TABLE instrument_fundamentals_snapshot ADD COLUMN`
   `analyst_target_price NUMERIC(18,4) NULL,`
   `analyst_consensus_rating NUMERIC(4,2) NULL,`
   `institutional_ownership_pct NUMERIC(6,3) NULL,`
   `short_percent NUMERIC(6,3) NULL,`
   `insider_net_buy_90d BIGINT NULL;`
   `+ CREATE TABLE insider_transactions ...` per §3.4.
2. **`026_seed_l4_screen_fields.py`** — idempotent INSERT into
   `screen_field_metadata` for the 5 new field names + 1 derived
   (`analyst_upside_pct`); mirror the template at
   `alembic/versions/024_seed_l2_snapshot_screen_fields.py:42-128`.

`app.py::_get_static_screen_fields` (`app.py:41,211`) MUST be updated in
lock-step with migration 026 — divergence will be silently overwritten
every 6 hours by the bootstrap refresh loop (warning at
`024_seed_l2_snapshot_screen_fields.py:25-31`).

**Forward-compat (R11)**: all new columns NULLABLE, no rename, no drop.

---

## §5. Frontend contract requirements (for I-B Block IB-L4)

Extend `ScreenFilterRequest` (`api/schemas/fundamental_metrics.py:28-60`)
and the `ScreenFilter` port dataclass
(`application/ports/repositories.py:51`):

```
analyst_target_price_min/max: float | None
analyst_consensus_rating_min/max: float | None   # 1.0-5.0
insider_net_buy_90d_min/max: float | None        # share count
institutional_ownership_pct_min/max: float | None # 0-100
short_percent_min/max: float | None              # 0-100
```

**"ANALYST UPSIDE" is derived** (`target / current_price - 1`); the
frontend should compute it client-side from the already-returned
`analyst_target_price` + the existing quote-price column (no backend
column needed — the screener already LEFT JOINs latest quote via
`market_capitalization` extraction chain). For filtering by upside, do
**not** add a backend `analyst_upside_pct_min/max`; the screener does
not currently support derived-column filters, and adding one would
require materialising upside per row in `query_screen` plus a refresh
job to keep prices fresh. **Defer derived-column filtering to v2** and
document the limitation in the I-B chip strip (the chip is
display-only; sort-only works if frontend post-sorts the returned page).

If product insists on filterable upside in v1, add it as a
`fundamental_metrics` metric (`metric='analyst_upside_pct'`) refreshed
daily by a new worker that joins target_price × latest quote. **+0.5d**.

### 5.1 Display label decisions to confirm with product

- `analyst_consensus_rating` scale: EODHD returns 1.0 = StrongBuy …
  5.0 = StrongSell. Frontend should invert / colour-code accordingly.
- Stale-target guard: 8.x% of EODHD WallStreetTargetPrice values are
  >90 days old (anecdotal — verify post-deploy). Recommend storing
  `analyst_target_price_updated_at` alongside the value so the frontend
  can grey out targets older than e.g. 90 days. **+0.25d for the extra
  column.**

---

## §6. Test coverage requirements

| Test | File | Count |
|------|------|-------|
| `metric_extractor` extracts `analyst_rating` as numeric when castable | `tests/unit/test_metric_extractor.py` (extend) | 3 |
| `metric_extractor` extracts `institutional_ownership_pct`, `short_percent` from `share_statistics` JSON | new section in `test_metric_extractor.py` | 4 |
| Snapshot writer upserts L-4 columns from analyst/share-stats records | new `tests/unit/test_fundamentals_snapshot_writer_l4.py` | 5 |
| InsiderTransactionsConsumer parses Form 4 envelope, idempotent upsert, deduplication via UNIQUE | new `tests/unit/test_insider_transactions_consumer.py` | 6 |
| 90-day window backfill SQL produces correct net-buy per instrument | new `tests/unit/test_insider_net_buy_rollup.py` | 4 |
| `ScreenFilterRequest` accepts new 10 min/max fields; round-trip through `query_screen` produces correct WHERE | extend `tests/unit/test_screener_l1_l2.py` → `test_screener_l1_l2_l4.py` | 10 |
| Migration 025 up/down/up | `tests/integration/test_migration_025.py` | 1 |
| Migration 026 seeds 5 rows idempotently | `tests/integration/test_migration_026.py` | 1 |
| Integration: AAPL fundamentals payload → snapshot row with all 5 L-4 fields set | new `tests/integration/test_l4_e2e.py` | 1 |

Total ~35 new tests. Architecture test (`apps/worldview-web/__tests__/architecture/`) unchanged.

---

## §7. Risks / unknowns / blockers

### 7.1 BLOCKER (escalate before starting)

- **Insider 90d coverage**: EODHD covers US only, past year; passthrough
  envelope has no consumer; only 3 tickers currently polled. To deliver
  `insider_net_buy_90d` universe-wide we must:
  1. Re-register the `insider_transactions` polling policy for all US
     instruments (~6k symbols × weekly = 6k credits/wk = ~24k credits/mo).
     Verify against current EODHD plan’s monthly credit pool.
  2. Build the new consumer + table. (~1 d, single-handed.)
  3. Accept that non-US instruments will permanently show NULL in this
     column (documented limitation).

### 7.2 Medium risk

- **`analyst_rating` numeric vs text** — `metric_extractor.py:96-100` marks
  it `text_only=True`. Changing this risks a regression for any
  consumer reading `value_text`. Safer path: leave the existing metric as
  text and write a **new** numeric column directly into
  `instrument_fundamentals_snapshot.analyst_consensus_rating`,
  computed in the snapshot writer from numeric Rating *or* derived from
  vote counts.
- **Stale targets**: doc references show some `WallStreetTargetPrice` rows
  cached >90d. Without a refresh-age guard, the screener could filter on
  stale data and surface dead names. Add `_updated_at` column or filter
  in the rollup ETL (drop targets older than 90d → NULL).
- **EODHD plan tier**: validate the current account supports
  `share_statistics` and `technicals_snapshot` sections in the bundled
  fundamentals call. Test live in dev before plan finalisation.

### 7.3 Low risk / minor unknowns

- `PercentInstitutions` units: EODHD doc example
  (`eodhd-endpoints-reference.md:1891`) shows `60.5` (already %), but
  `ShortPercentOfFloat` shows `0.008` (decimal). Confirm by reading a
  live AAPL payload before writing the migration — the snapshot writer
  must normalise to a single convention (recommend store as %).
- `analyst_consensus_rating` derivation when Rating field absent but
  vote counts present: define the formula in code + cite in the
  migration comment.

---

## §8. Effort estimate

| Block | Hours | Confidence |
|-------|-------|-----------|
| Migration 025 (schema) + 026 (seed) + `_get_static_screen_fields` update | 3 | high |
| Extend `metric_extractor.py` for institutional / short fields + unit tests | 3 | high |
| Snapshot writer extension (4 snapshot fields) + tests | 5 | high |
| New `InsiderTransactionsConsumer` + `insider_transactions` table + tests | 6 | medium |
| Re-register insider polling for full US universe (`polling_policies` migration) + verify credit budget | 3 | medium |
| `insider_net_buy_90d` rollup worker (nightly cron, 90d window) + tests | 4 | medium |
| `ScreenFilterRequest` + `ScreenFilter` port + `query_screen` WHERE/ORDER extensions + 10 unit tests | 4 | high |
| Integration test (`tests/integration/test_l4_e2e.py`) | 2 | medium |
| Docs: update `docs/services/market-data.md`, `MASTER_PLAN.md`, plan §3.2 amendment, `.claude-context.md` | 2 | high |
| Optional `analyst_upside_pct` as filterable metric (deferred unless mandatory) | +4 | medium |
| Optional `analyst_target_price_updated_at` staleness column | +2 | high |

**Total core (mandatory): ~32 h ≈ 4 engineer-days (confidence: medium-high).**
**Total with both optional add-ons: ~38 h ≈ 5 engineer-days.**

Plan §3.2 cites "~2 d" — this is **optimistic by ~1.5–2 d**, largely
because the insider 90d aggregate is a green-field consumer + table + cron
+ universe re-poll, not a simple column add. The 4 snapshot fields alone
are ~1.5 d and align with the original estimate; the insider work doubles
it.

### Recommended slicing

To keep PR sizes manageable and let I-B unblock progressively:

- **L-4a** (~1.5 d): the 4 snapshot fields + migrations + screener filters.
  Unblocks IB-L4 T-13/14/15/16 partially (4 of 5 columns).
- **L-4b** (~2 d): insider table + consumer + rollup + polling reroute.
  Unblocks the 5th column. Can ship a week later without blocking I-B
  start.

---

## Citations summary

- `services/market-data/src/market_data/infrastructure/db/metric_extractor.py:85-105,182-185`
- `services/market-data/src/market_data/infrastructure/db/repositories/fundamental_metrics_query.py:107-220,_SNAP_FIELDS`
- `services/market-data/src/market_data/infrastructure/db/models/fundamentals_snapshot.py:32-95`
- `services/market-data/src/market_data/application/ports/repositories.py:51-92`
- `services/market-data/src/market_data/api/schemas/fundamental_metrics.py:28-60`
- `services/market-data/src/market_data/app.py:41,211,297`
- `services/market-data/alembic/versions/024_seed_l2_snapshot_screen_fields.py` (template)
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/eodhd.py:192-237,501-549`
- `services/market-ingestion/src/market_ingestion/application/use_cases/strategies/canonicalize.py:184-238`
- `services/market-ingestion/alembic/versions/0006_weekly_insider_transactions.py`
- `docs/references/eodhd-endpoints-reference.md:151,181-184,262,302-305,1860-1894,3867-3999`
- `docs/plans/0089-pages/I-screener-plan.md:§3.2`
