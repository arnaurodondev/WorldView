---
title: "PRD-0089 L-4b Insider Universe Activation — Investigation"
date: 2026-06-16
type: read-only investigation
worktree: worldview-wt-md-reliability
head: 2e447e8beaeb292188711460647fe578c9bb94c9
target: "docs/plans/0089-pages/DEFERRED-WORK-PLAN.md §3 (L-4b insider universe activation)"
status: read-only — no changes made
---

# PRD-0089 L-4b Insider Universe Activation — Investigation

> Read-only. Findings only. Live DB queried via `docker exec worldview-postgres-1 psql`.

## TL;DR

The DEFERRED-WORK-PLAN §3 is **materially stale**. Its core premise — "only a
hardcoded 3-ticker baseline (AAPL/TSLA/AMZN) is active, so `insider_net_buy_90d`
is non-null for ~3 tickers only" — is **no longer true**. Since 2026-06-06, a
separate migration (`0017_top100_insider_market_cap.py`, PLAN-0106 Wave E-1)
expanded the insider polling universe to the **top-100 S&P 500** at weekly
cadence. Live coverage today:

- **103 enabled** `insider_transactions` polling policies (100 distinct symbols).
- **95 distinct instruments** have rows in `insider_transactions` (1,563 rows).
- **39 instruments** have non-null `insider_net_buy_90d` in the snapshot table
  (out of 669 snapshot rows).

The `InsiderUniverseLoader` does exist and is NOT scheduled — but it is **not the
mechanism that expanded the universe**, and as written it would **fail at
runtime** (it INSERTs into a table named `sched_policies` that does not exist;
the real table is `polling_policies`). So §3's recommended "activate the loader"
path is doubly obsolete: the universe is already largely expanded by migration,
and the loader is buggy.

---

## Lens 1 — Does it exist / current state?

### Loader existence: YES (but unscheduled and buggy)

- File exists: `services/market-ingestion/src/market_ingestion/infrastructure/workers/insider_universe_loader.py`.
- Scheduling grep — **no matches** for `insider_universe`, `_insider_universe_refresh_loop`,
  or `INSIDER_UNIVERSE_REFRESH` in `app.py` or `config.py`. Confirmed NOT scheduled.
- In fact, `services/market-ingestion/src/market_ingestion/app.py` `lifespan()`
  has **no scheduled background loops of any kind** (no `create_task`, no `_loop`,
  no Worker scheduling). The only non-test references to the loader are inside its
  own module. It is invoke-only via
  `python -m market_ingestion.infrastructure.workers.insider_universe_loader`.

**Critical defect found**: the loader's `upsert_insider_policies()` SQL does
`INSERT INTO sched_policies (...)`, but:
- `to_regclass('public.sched_policies')` → **NULL** (table does not exist).
- The ORM model `polling_policy.py` declares `__tablename__ = "polling_policies"`.
- The sibling `instrument_policy_sync_worker.py` correctly INSERTs into
  `polling_policies`.

So if an operator ran the loader today it would raise
`UndefinedTableError: relation "sched_policies" does not exist`. The loader's
docstring also repeatedly refers to `sched_policies`. This is a copy-paste from
an older table name that was renamed to `polling_policies`. **The loader has
never run successfully against this schema.** (Worth a BP entry: "loader/worker
SQL references a table name that was renamed; never exercised in CI because the
loader is operator-only and untested against a real DB.")

### What actually expanded the universe

Migration `0017_top100_insider_market_cap.py` (Revises 0016, Create Date
2026-06-06, PLAN-0106 Wave E-1) seeds weekly (`604800`s) `insider_transactions`
+ `market_cap` policies for the top-100 S&P 500 by market cap. This is why the
live `created_at` histogram shows **100 insider policies created on 2026-06-06**
plus the original 3 from the seed migration (`0002_initial_seeds.py:352`, created
2026-05-09). The seed baseline is daily (`86400`s) for AAPL/TSLA/AMZN; migration
0017 adds the weekly top-100. (There is also `0006_weekly_insider_transactions.py`
in the chain.)

### Live coverage numbers (queried 2026-06-16)

| Metric | DB | Value |
|--------|----|-------|
| `instrument_fundamentals_snapshot` rows with `insider_net_buy_90d IS NOT NULL` | market_data_db | **39** |
| `instrument_fundamentals_snapshot` total rows | market_data_db | 669 |
| `insider_transactions` total rows | market_data_db | 1,563 |
| `insider_transactions` distinct instruments | market_data_db | **95** |
| `polling_policies` insider_transactions, total / distinct symbol / enabled | ingestion_db | 103 / 100 / 103 |
| insider policies created 2026-05-09 (seed) | ingestion_db | 3 |
| insider policies created 2026-06-06 (migration 0017) | ingestion_db | 100 |
| insider policy cadence | ingestion_db | 100% weekly (604800s) |
| OHLCV-covered universe (distinct enabled ohlcv symbols, proxy for loader target) | ingestion_db | ~654 |

Note the coverage funnel: 100 policies → 95 instruments with raw transactions →
only **39** with a computed `insider_net_buy_90d`. The 95→39 gap is the more
interesting current question (the 90d rollup, `rollup_insider_90d` at 03:00 UTC,
only populates the snapshot when there are transactions in the trailing 90-day
window with usable amounts; many of the 95 have older or amount-less filings).
The §3 "3 tickers" framing should be replaced with "39 non-null today, 95 with
raw data, 100 policies enabled."

### Table-name correction for the plan

§3.1 / §3.6 refer to `sched_policies` throughout. The real table is
`polling_policies` (ingestion_db). The plan inherited the same wrong name the
loader uses.

---

## Lens 2 — Root cause + current budget reality

### Root cause (as documented) is partly OBE

§3.3 says activation is gated on a ~13k credits/month EODHD spend decision for
weekly polling of ~3000 instruments. Reality check:

1. **The universe was already expanded** (to top-100, weekly) by a *migration*
   on 2026-06-06 — i.e. the credit-spend decision was effectively made for the
   top-100 slice without going through §3's "budget-owner approval first" gate.
   This is itself a process finding: a side-effect credit-spend happened via
   migration, exactly the "silent side effect" §3.3 warned against.
2. The loader's "~3000 instruments" assumption is stale. The actual OHLCV-covered
   universe in this environment is **~654 instruments**, not 3000. Weekly polling
   of 654 ≈ 654 calls/week ≈ ~2,800 credits/month at 1 credit/call — roughly the
   plan's "monthly cadence at 3000" figure, i.e. ~4.6x cheaper than the headline
   13k. Universe-wide activation here is far more affordable than §3 implies.

### EODHD quota reality in this environment

- `provider_budgets` (ingestion_db) holds a **token-bucket rate limiter**, not the
  EODHD monthly plan credit count: `eodhd` row = `max_tokens=10000`,
  `refill_rate_per_second≈1.157` (≈100k tokens/day capacity),
  `current_tokens≈6909`. This governs burst/throughput, not monthly API credits.
- The actual EODHD monthly **API-credit plan limit is external** (EODHD account
  side) and is not tracked in any local table. The memory notes a recent quota
  exhaustion episode (DeepInfra key rotation context, plus general "platform
  recently had quota exhaustion"), so the external EODHD plan headroom is the real
  constraint and cannot be read from the DB here.
- Config: `eodhd_api_key` defaults to `"demo"` (demo = 3 legacy endpoints only;
  a `_warn_demo_eodhd_key` validator warns). Production uses
  `MARKET_INGESTION_EODHD_API_KEY`. `routing_insider_transactions = "eodhd:100"`
  so insider polling is 100% EODHD-routed.

### Loader mechanism (confirmed)

`fetch_ohlcv_covered_symbols()` pages `GET /internal/v1/instruments/ohlcv-covered`
(endpoint confirmed live: `services/market-data/src/market_data/api/routers/internal_instruments.py:189`,
backed by `query_ohlcv_covered`), signs an internal RS256 JWT
(`sub=system:insider-universe-loader`), then `upsert_insider_policies()` would
UPSERT one weekly (604800s) policy per (symbol, exchange) with **`enabled=FALSE`**
and `ON CONFLICT ... DO NOTHING`. Two things to flag vs. the plan:
- It targets the wrong table (`sched_policies`) — would error (Lens 1).
- It inserts **disabled** policies, so even if the table name were fixed, a
  second "enable" step would be required before any polling happens. §3 does not
  mention this — it assumes running the loader is sufficient.

**Is weekly affordable now?** For the *actual* ~654 OHLCV-covered universe: yes,
comfortably — ~2.8k credits/month, well under the 13k headline. For a future
3000-instrument universe, weekly is the 13k figure and the budget decision still
matters. The top-100 slice already live is ~430 credits/month (100 × ~4.3
weeks), negligible.

---

## Lens 3 — UI handling of sparse coverage

§3.2 correctly notes that an `INSIDER 90D` column showing values for only a
handful of tickers "looks like a bug." With 39/669 non-null today, this is real.

Recommendations (consistent with §2.5's existing guidance and the credit-rating
precedent):

1. **Null sentinel, never zero.** Render `null` / missing as the em-dash `—`
   sentinel (same as credit rating), NOT `$0` or `0`. `insider_net_buy_90d=0`
   is a *legitimate distinct value* (insiders net-flat) and must be visually
   distinguishable from "no data." This is the load-bearing rule: zero ≠ unknown.
   This matches the user's "prompt input vs lookup mismatch / silent-drop"
   sensitivity — a `0` fallback for missing data is a silent-failure pattern.
2. **Coverage indicator.** Add a column-header affordance (small "coverage: 39 of
   669" tooltip, or a faint header badge) so the sparsity is *explained* rather
   than read as breakage. Bloomberg EQS shows blanks without alarm because users
   expect partial coverage; an explicit indicator gets us there faster.
3. **Filter semantics.** When a user applies `insider_net_buy_90d_min = 1_000_000`,
   rows with NULL must be **excluded** (not treated as 0 and excluded "by
   accident", and definitely not included). Make the WHERE clause
   `insider_net_buy_90d IS NOT NULL AND insider_net_buy_90d >= :min`, and consider
   surfacing "N of M instruments have insider data" in the result chrome so a
   "3 results" outcome reads as coverage-limited, not filter-too-tight.
4. **Sort.** NULLs sort last (`NULLS LAST`) in both directions so the populated
   names are always reachable at the top.
5. **Opt-in, not default.** Keep `INSIDER 90D` an opt-in column (as §2.5 plans)
   until coverage is broad, so the default grid isn't dominated by em-dashes.

---

## Lens 4 — Bloomberg-competitive angle + recommended cadence

### What universe-wide coverage unlocks

Insider-flow screening is a canonical Bloomberg EQS alpha filter ("net insider
buying ≥ $1M over 90d," "cluster buying," "insider buy/sell ratio"). Form 4
cluster buying is one of the better-documented retail-accessible alpha signals.
With coverage limited to 39–100 mega-caps, the screener can only answer "are
insiders buying AAPL?" — which is exactly where insider signal is *weakest*
(mega-cap insider trades are dominated by scheduled 10b5-1 sales and option
exercises, low signal). The alpha lives in **mid-cap / under-covered names**,
where a single director's open-market buy is material. So universe-wide coverage
is not a nice-to-have polish item — it is what makes the filter *competitive at
all* vs. Bloomberg, and potentially *differentiated* if combined with the
platform's news/intelligence rollups ("insider buying + positive news momentum
+ no analyst coverage").

### Cheapest credible-coverage path (cadence tradeoff)

EODHD insider-transactions = 1 credit/call. For this environment's actual
universe (~654 OHLCV-covered, not the plan's stale 3000):

| Universe | Cadence | ~Calls/month | ~Credits/month | Verdict |
|----------|---------|--------------|----------------|---------|
| Top-100 (live now) | Weekly | ~430 | ~430 | Already running; negligible |
| ~654 OHLCV-covered | Weekly | ~2,830 | ~2,830 | **Recommended** — affordable, near-real-time |
| ~654 OHLCV-covered | Monthly | ~654 | ~654 | Fallback if EODHD plan is tight |
| 3000 (future growth) | Weekly | ~13,000 | ~13,000 | The plan's headline; needs budget sign-off |
| 3000 (future growth) | Monthly | ~3,100 | ~3,100 | Budget-friendly compromise at scale |

**Recommended cadence: weekly, scoped to the OHLCV-covered universe (~654 today).**
Form 4 filings land within 2 business days; weekly captures all with acceptable
analytical lag. At ~2.8k credits/month this is affordable and avoids the 13k
sticker shock, which only materializes at a 3000-instrument universe that does
not exist in this environment yet.

**A cheaper tiered alternative** if EODHD plan headroom is the binding
constraint: **portfolio + watchlist + top-N-by-market-cap weekly; long tail
monthly.** This concentrates the near-real-time budget on names the user actually
holds or follows (where a stale insider signal is most costly) and lets the long
tail refresh monthly. Implementation = two cadences in `polling_policies`
(`base_interval_sec` 604800 vs ~2.6M). This is the cheapest path to *credible*
coverage and aligns spend with attention.

---

## Recommendations to update §3 of DEFERRED-WORK-PLAN

1. **Rewrite the premise.** Replace "only 3 tickers (AAPL/TSLA/AMZN)" with the
   live reality: top-100 already enabled via migration 0017 (2026-06-06); 39
   non-null / 95 with raw data / 100 policies enabled. The 0.5-day "activate the
   loader" framing is obsolete for the top-100 slice.
2. **Fix the table-name bug before any "activate the loader" recommendation.**
   The loader INSERTs into `sched_policies` which does not exist; rename to
   `polling_policies` and add a real DB-backed test. Without this, Option A/C in
   §3.4 cannot work. (Candidate new bug-pattern entry.)
3. **Note the disabled-insert.** The loader writes `enabled=FALSE`; activation
   needs a separate enable step. §3.4 should say so.
4. **Re-scope the budget figures** to the actual ~654 OHLCV-covered universe
   (~2.8k credits/month weekly), not the stale ~3000 / 13k headline.
5. **Investigate the 95→39 rollup gap** as the real remaining coverage lever —
   more instruments have raw insider data than have a computed
   `insider_net_buy_90d`. This is likely a higher-leverage fix than re-running
   the loader.
6. **Flag the process gap:** migration 0017 spent EODHD credits as a side effect
   without going through §3.5's "budget-owner approval first" gate — exactly the
   silent side-effect the plan warned against. Worth a runbook note that
   credit-spending universe expansions should not ship as bare migrations.

---

## Files / artifacts referenced

- `services/market-ingestion/src/market_ingestion/infrastructure/workers/insider_universe_loader.py` (exists; unscheduled; `sched_policies` bug at line ~171)
- `services/market-ingestion/src/market_ingestion/app.py` (lifespan has no scheduled loops)
- `services/market-ingestion/src/market_ingestion/config.py` (`routing_insider_transactions="eodhd:100"`, demo-key default)
- `services/market-ingestion/alembic/versions/0002_initial_seeds.py:352` (3-ticker daily seed)
- `services/market-ingestion/alembic/versions/0006_weekly_insider_transactions.py`
- `services/market-ingestion/alembic/versions/0017_top100_insider_market_cap.py` (the real universe expansion, 2026-06-06)
- `services/market-ingestion/src/market_ingestion/infrastructure/db/models/polling_policy.py` (`__tablename__="polling_policies"`)
- `services/market-data/src/market_data/api/routers/internal_instruments.py:189` (`/internal/v1/instruments/ohlcv-covered` — confirmed live)
- `services/market-data/src/market_data/application/use_cases/get_ohlcv_covered.py`
- DB: `market_data_db.insider_transactions`, `market_data_db.instrument_fundamentals_snapshot`, `ingestion_db.polling_policies`, `ingestion_db.provider_budgets`
