# Alpaca Market-Data Sourcing — Investigation + Rollout Plan (2026-07-16)

**Branch:** `feat/alpaca-market-data`
**Status:** Investigated (prod, read-only). Adapter + routing already exist in code; the
daily gap is a **config/deploy + backfill** problem, not a missing-integration problem.
**Do NOT deploy from here** — the authoritative fix is a prod env-var flip + an in-cluster backfill Job.

---

## 1. TL;DR verdict

The operator's belief — "daily **and** intraday OHLCV should come from Alpaca" — is **already the
designed and (for intraday) live topology**. Alpaca is **not** missing:

- **Intraday (1m):** ALREADY sourced from Alpaca in prod (routing `alpaca:100,polygon:80`),
  batched, `provider_priority = 110`. 5m/15m/30m/1h/4h are **derived** from the Alpaca 1m
  series (also priority 110). This works today (~60k 1m bars, actively growing).
- **Daily (1d):** Alpaca is the **intended** primary (repo default `routing_ohlcv_eod =
  alpaca:100,eodhd:80`, migrations 0023/0024, adapter supports `1d`→`1Day` with `adjustment=all`),
  but **prod emits ZERO Alpaca daily bars**. Root cause is a **stale deployed env var** (below),
  not code.

**Alpaca is viable as the single daily+intraday source for the US-equity + crypto universe.**
It cannot serve indices/forex/non-US venues — those stay on EODHD/Yahoo permanently.

---

## 2. Current sourcing map (prod, `market_data_db.ohlcv_bars`, 2026-07-16)

| timeframe | source          | provider_priority | is_derived | rows    |
|-----------|-----------------|-------------------|-----------|---------|
| 1m        | alpaca          | 110               | no        | 60,503  |
| 5m        | derived         | 110               | yes       | 14,953  |
| 15m       | derived         | 110               | yes       | 5,271   |
| 30m       | derived         | 110               | yes       | 2,736   |
| 1h        | derived         | 110               | yes       | 1,468   |
| 4h        | derived         | 110               | yes       | 435     |
| **1d**    | **eodhd**       | **60**            | no        | 269,872 |
| **1d**    | **yahoo_finance** | **80**          | no        | 46,017  |

- Intraday: Alpaca → resampler. Healthy.
- Daily: 100% Yahoo (recent, priority 80) + EODHD (backfilled history, priority 60). **No Alpaca.**
- Provider→priority map (market-data `domain/enums.py`): alpaca=110, derived=110, polygon=100,
  yahoo_finance=80, eodhd=60. Upsert guard: `EXCLUDED.provider_priority >= ohlcv_bars.provider_priority`.

### Why no Alpaca daily (root cause — confirmed live)

Deployed env on `market-ingestion{,-scheduler,-worker}`:

```
MARKET_INGESTION_ROUTING_OHLCV_INTRADAY = alpaca:100,polygon:80     # correct
MARKET_INGESTION_ROUTING_OHLCV_EOD      = yahoo_finance:100,eodhd:80  # STALE — should be alpaca:100,eodhd:80
```

The routing cache is the source of truth at execution time (`execute_task._select_provider` →
`routing_cache.primary_for('ohlcv','1d')`). With `yahoo_finance:100` primary, **every** `1d`
task — even ones enqueued from the 96 `alpaca/ohlcv/1d` polling policies — is routed to Yahoo.
`ingestion_tasks.fetched_by_provider` confirms it: of the alpaca-routed 1d tasks, 180 were
`fetched_by=yahoo_finance` and 12 `eodhd`; **zero** actually fetched from Alpaca.

Direct probes (from a worker pod, prod Alpaca key, header auth) prove Alpaca daily itself is fine:
- `1Day` recent 2-day window → 2 adjusted bars (HTTP 200).
- `1Day` deep history → first available bar `2020-07-27` (≈6 years). Pre-2020-07 returns 0.

So the deployed adapter and Alpaca daily both work; only the routing env var is wrong.

Secondary staleness: `schedule_tasks.py` still documents/handles EOD as Yahoo-primary
(`_YAHOO_ROUTED_EOD_TIMEFRAMES`, budget pre-charge skip). The budget-skip is still correct
(Alpaca is free, don't pre-charge EODHD), but the comments name the wrong provider.

---

## 3. Alpaca viability

| Question | Finding |
|----------|---------|
| Keys present in prod? | **Yes.** `MARKET_INGESTION_ALPACA_API_KEY` (len 26), `..._SECRET_KEY` (len 44) in `market-ingestion-secrets`. Valid — 1m ingestion + daily probes succeed. |
| Feed | `iex` (free). SIP (paid) not configured/needed. IEX volume is understated (~3% of consolidated) but close matches EODHD/Yahoo within ~0.04% — acceptable for charts (per migration 0023 note). |
| Timeframes | `1Min/5Min/15Min/30Min/1Hour/4Hour/1Day` all supported by the adapter (`_TIMEFRAME_MAP`). Daily uses `adjustment=all` (split/dividend adjusted); intraday raw. Config-driven via that map. |
| Historical depth | Daily back to **~2020-07-27** (~6y). 1m ~ trailing window. Enough for all daily surfaces (1D…5Y). |
| Coverage of 561 instruments | Alpaca serves **US equities/ETFs (`US`, 530) + crypto (`CC`, 10)** = **540** instruments. It does **NOT** serve `INDX` (10), `FOREX` (1), `SHG` (1), blank-exchange (9) = ~21 instruments → stay on EODHD/Yahoo. |
| Rate limits | Free ≈ 200 req/min; unlimited monthly. Batch endpoint = up to 1000 symbols/call for intraday. Daily backfill = 1 request/symbol. No credit cost. |

**Verdict:** Alpaca can be the single daily+intraday source for the **540 US+crypto** instruments.
Indices/forex remain EODHD/Yahoo. This matches PLAN-0036's final topology.

---

## 4. Coverage gap (secondary issue)

Only **96** instruments (86 `US` + 10 `CC`) currently have `alpaca` polling policies (both 1m and 1d).
The other ~444 US equities have **no** Alpaca policy → their daily comes from EODHD, their intraday
is absent. Alpaca can cover all 530 US equities; the policy seed is just incomplete.

---

## 5. Rollout plan

### Step A — Flip the routing env var (the actual fix; ops/deploy)
Set on `market-ingestion`, `market-ingestion-scheduler`, `market-ingestion-worker` (via the private
`worldview-config` GitOps repo, since the value is injected as a plain env var, not from the repo):

```
MARKET_INGESTION_ROUTING_OHLCV_EOD = alpaca:100,eodhd:80
```

Effect: `1d` tasks route to Alpaca first; EODHD is the zero-bar failover (correct for the ~21
non-Alpaca instruments, which return 0 from Alpaca and fail over to EODHD automatically). No code
change — this is already the repo default in `config.py`.

### Step B — Backfill the daily archive from Alpaca (code: this branch)
New script **`market_ingestion.scripts.backfill_alpaca_daily_ohlcv`** (added here). Mirrors the
existing EODHD backfill but:
- Fetches daily from **Alpaca** → produced bars carry `source='alpaca'` → **priority 110**, which
  **supersedes** the incumbent Yahoo (80) and EODHD (60) rows on the normal upsert guard. (The
  existing EODHD backfill lands at 60 and *cannot* overwrite Yahoo — this is why an Alpaca backfill
  is required.)
- Filters to **Alpaca-eligible** instruments (`US`/`CC` only); indices/forex are skipped.
- **No credit budget** (Alpaca is free); resumable Valkey cursor `s2:v1:alpaca_ohlcv_backfill:cursor`;
  single-flight advisory lock; `--dry-run`; default horizon 6y (`~2020-07-27`→today).
- Same produce pipeline as the live worker (synthetic task → `execute_with_prefetched_result` →
  outbox `MarketDatasetFetched` → market-data OHLCV consumer upsert). Idempotent + re-runnable.

Run in-cluster as a K8s Job (a detached `kubectl exec` dies on pod-roll):
```
python -m market_ingestion.scripts.backfill_alpaca_daily_ohlcv --years 6 --resume
```
Sizing: 540 symbols × 1 request ≈ 540 requests, ~1500 daily bars/symbol ≈ ~800k daily bars total,
zero credits, a few minutes of wall-clock (rate-limit gated at ~200 req/min → ~3 min).

### Step C — Seed Alpaca policies for the full US universe (migration; follow-up)
Add an Alembic migration (market-ingestion) inserting `alpaca/ohlcv/1m` + `alpaca/ohlcv/1d` policies
for **all** `US` equities (extend the 86→530) and confirm the 10 `CC`. Mirror migrations 0011/0023
(deterministic ULIDs, `ON CONFLICT DO NOTHING`, 1d cadence 86400s, 1m priority 100). Leave
INDX/FOREX/SHG on EODHD. This is a separate small change, not in this branch.

### Step D — Stale-comment cleanup (optional, low-risk)
Update `schedule_tasks.py` `_YAHOO_ROUTED_EOD_TIMEFRAMES` naming/comments to reflect Alpaca-primary
EOD (keep the EODHD budget pre-charge skip — still correct). Cosmetic; no behavior change.

---

## 6. Migration story for existing Yahoo/EODHD daily bars

- **No delete needed.** After Step A + Step B, Alpaca daily bars (priority 110) overwrite the
  Yahoo (80) and EODHD (60) rows in place on the upsert guard for every covered date ≥ ~2020-07-27.
- **Pre-2020-07-27 dates:** Alpaca has no bars → the existing Yahoo/EODHD rows remain (acceptable;
  they were the only source anyway).
- **Non-Alpaca instruments (INDX/FOREX/SHG, ~21):** Alpaca returns 0 → zero-bar failover keeps
  EODHD; their existing bars are untouched. This is by design.
- **Ongoing:** once Step A is live, the daily scheduler polls Alpaca each session for covered
  symbols (priority 110), so the series stays Alpaca-authoritative without further backfills.

---

## 7. What needs provisioning / rebuild

- **Alpaca credentials:** already provisioned (present + working). No new keys needed for IEX.
  SIP (paid) only if real-time/consolidated volume becomes a requirement — not needed now.
- **market-ingestion rebuild:** only for Steps B/C/D (new script + migration + comment). Step A
  (the actual daily fix) needs **no rebuild** — just the env-var change + a rollout restart.
- **market-data rebuild:** none. Its priority map already ranks alpaca=110 above yahoo/eodhd.

---

## 8. Delivered on this branch (`feat/alpaca-market-data`)

- `services/market-ingestion/src/market_ingestion/scripts/backfill_alpaca_daily_ohlcv.py` — resumable,
  Alpaca-sourced, priority-110 daily backfill (Steps B).
- `services/market-ingestion/tests/test_backfill_alpaca_daily_ohlcv.py` — 13 unit tests (horizon,
  eligibility filter, resume cursor, dedupe, dry-run fetch-nothing, produce-path claims task +
  provider=ALPACA, zero-bar checkpoint). All pass; ruff clean.
- This plan.

**Not done here (needs deploy / prod-write, out of read-only scope):** Step A env flip, Step B
Job execution, Step C policy-seed migration, Step D comment cleanup.
