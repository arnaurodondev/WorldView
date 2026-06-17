# EODHD API-Quota Allocation Audit — 2026-06-16

**Service:** market-ingestion · **Quota:** EODHD hard 100,000 requests/day (recently exhausted)
**Scope:** validate the credit breakdown, find waste, fix the clear/low-risk items.
**Changes left UNCOMMITTED** (R42 — shared worktree, sibling sessions active).

---

## 1. Actual EODHD quota breakdown (steady state)

Enabled EODHD polling policies (`ingestion_db.polling_policies`, provider='eodhd', enabled):

| Category | Policies | Interval | Fetch/sym/day | Credit each | **Worst-case credits/day** | **Realistic credits/day** |
|---|---:|---:|---:|---:|---:|---:|
| **Fundamentals** (Tier-1 daily) | 481 | 1 day | 1 | 10 | 4,810 | ~800 (TTL 6d gates ~1/6) |
| **Fundamentals** (Tier-2 90d) | 48 | 90 day | 0.011 | 10 | 5 | ~5 |
| **OHLCV 1d** | 554 | 6 h | 4 | 1 | 2,216 | **~0 — routed to Yahoo** |
| **Quotes** | 6 | 5 min (mkt-hrs only) | ~78 | 1 | 1,728 | ~470 (6.5 h session) |
| **Economic events (macros)** | 6 | 1 day | 1 | 5 | 30 | ~30 |
| **Macro indicators** | 5 | 90 day | 0.011 | 5 | ~0 | ~0 |
| **Market cap** | 105 | 7 day | 0.14 | 1 | 15 | 15 |
| **Insider transactions** | 103 | 7 day | 0.14 | 1 | 15 | 15 |
| **Yield curve** | 3 | 1 day | 1 | 1 | 3 | 3 |
| **Earnings calendar** | 1 | 1 day | 1 | 1 | 1 | 1 |
| **News** | — | — | — | — | **0 (not in market-ingestion)** | 0 |

### Verdict on the user's mental model
- **"Most is fundamentals / macros / news"** — *Partly right.* Fundamentals **is** the #1 real EODHD cost (~800–4,800 credits/day; 10 credits each). **Macros are tiny** (~30/day). **News is NOT a market-ingestion EODHD cost** — news lives in **content-ingestion** (separate concern; the `eodhd news_sentiment` policies here are **disabled**). The big EODHD consumers in this service are **fundamentals** and **quotes**.
- **"OHLCV mostly from Alpaca, minor on EODHD"** — *Right in spirit, with a correction.* OHLCV **daily** is routed to **Yahoo Finance** (free), not Alpaca; **intraday 1m** is Alpaca. Either way **EODHD OHLCV ≈ 0 credits/day in steady state.** The 554 `eodhd ohlcv 1d` policies are a red herring: 100% of observed `ohlcv 1d` tasks resolve to `yahoo_finance` (live worker logs: 81/81). EODHD is only the **zero-bar failover** for daily.

---

## 2. Is recurring EODHD daily-OHLCV polling redundant given Alpaca/Yahoo?

**Yes — it is already effectively eliminated.** `routing_ohlcv_eod = "yahoo_finance:100,eodhd:80"` makes Yahoo the primary and EODHD a failover. Daily/weekly/monthly OHLCV does not burn EODHD credits except during a Yahoo outage. Market-data also *derives* 1w/1mo from daily, and the IntradayResamplingWorker derives 5m..1d from Alpaca 1m. So no recurring EODHD `1d` poll is needed for normal operation.

**Caveat (kept intentionally):** EODHD daily is the deep-history / adjusted-close failover. Yahoo daily covers split-adjusted close and multi-year history, so the failover is rarely needed — but keeping EODHD as failover (weight 80) is correct and cheap. **No change recommended to the routing config.** The real fix was the *scheduler over-charging* the EODHD budget for these Yahoo-bound tasks (see §3, Fix B).

---

## 3. Budget-correctness items

| Item | Status | Detail |
|---|---|---|
| **`for_eodhd()` defaults** (1000/10.0 vs live 10000/1.157) | **FIXED** | Factory under-provisioned burst 10x and over-provisioned refill ~8.6x. Fresh envs (and any code path that calls `get_or_create` before migration 0005 seeds the row) got a wrong bucket. Now `10_000 / 1.157` = real 100k/day. |
| **DailyBudgetTracker always "over budget"** | **CONFIRMED real — FLAGGED, not fixed** | Mis-modeled: `spent = burst − tokens` treats *instantaneous bucket depletion* as *cumulative daily spend*. A continuously-refilling bucket where consumption≈refill sits near-empty (live: 8–28 tokens of 10,000), so `spent ≈ 9,990 > allotted 8,500` → permanently negative headroom. It is **diagnostic-only** (exposed via `/internal` quota route, not a hard gate), so it misleads a dashboard but does not throttle traffic. A correct daily tracker needs a **cumulative counter** = the Valkey `EodhdQuotaService` (next item). Fixing it properly is coupled to wiring that service; doing it half-way would just move the lie. **Recommend** rebasing it on the Valkey monthly/daily counter once that is wired. |
| **Cross-replica monthly quota guard (Valkey `EodhdQuotaService`)** | **CONFIRMED unwired — FLAGGED** | `eodhd:v1:quota:YYYY-MM:credits_used` is empty; **no `eodhd*` keys exist in Valkey.** Root cause: the worker (`infrastructure/workers/worker.py`) constructs `ExecuteTaskUseCase(...)` at **both** sites **without** passing `quota_service=`, so it defaults to `None` and `pre_fetch_checks` skips Step 0 entirely. The class lives in `libs/messaging` (owned by a sibling session this sprint) — **not wired here to respect R42.** **Recommend** a follow-up: construct `EodhdQuotaService(valkey_client, hard_limit=100_000)` in the worker and pass it to both `ExecuteTaskUseCase` constructions. This is the only true *hard* 100k/day guard; until wired, the per-tick token bucket is the sole defense. |

---

## 4. Priority under quota pressure — do fundamentals/macros/news win over OHLCV?

**Before this fix: NO — OHLCV could starve fundamentals.** Two compounding problems:

1. **Priority inversion.** `polling_policies.priority` (used: `list_enabled()` orders by `priority DESC`): quotes=10, **ohlcv-1d=5**, **fundamentals=2**, macros=0. So OHLCV-daily is consumed by the scheduler's budget gate **before** fundamentals.
2. **Phantom charge.** `_apply_budgets` charged the **EODHD** token bucket for OHLCV-1d tasks using `task.provider` (= `eodhd`, the *requested* provider) — even though they resolve to **Yahoo** at execution and cost **zero** EODHD credits. ~2,216 phantom credits/day. Because the gate `break`s on first exhaustion, those phantom OHLCV charges could drain the bucket and **defer the genuinely-EODHD fundamentals tasks** ranked below them.

**After this fix (Fix B):** OHLCV daily/weekly/monthly bypasses the EODHD budget gate entirely (it's Yahoo-bound), so it can no longer drain EODHD tokens or starve fundamentals. Real EODHD demand (fundamentals/quotes) now has the full bucket. EODHD failover for OHLCV is still guarded downstream by the circuit breaker (and, once wired, the monthly quota service).

---

## What changed (applied)

**Fix A — `for_eodhd()` defaults → real quota**
- `services/market-ingestion/src/market_ingestion/domain/entities/provider_budget.py` — `for_eodhd()` now returns `burst_capacity=10_000`, `refill_rate=1.157` (100k/day) via `ClassVar` constants `EODHD_BURST_CAPACITY` / `EODHD_REFILL_RATE`.
- Test updated (intent preserved): `tests/domain/test_provider_budget.py::test_provider_default_eodhd` asserts 10_000 / 1.157 and the 100k/day identity.

**Fix B — scheduler stops phantom-charging EODHD for Yahoo-routed OHLCV**
- `services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py` — added `_YAHOO_ROUTED_EOD_TIMEFRAMES = {1d,1w,1mo,1M}`; in `_apply_budgets`, EODHD-provider OHLCV tasks on those timeframes are kept **without** consuming the EODHD bucket.
- Tests: `tests/application/test_schedule_tasks.py` — `test_budget_exhausted_limits_tasks` / `test_all_budgets_exhausted_no_tasks` retargeted to FUNDAMENTALS (genuinely EODHD-charged; intent preserved), plus two new regressions: `test_yahoo_routed_eod_ohlcv_bypasses_eodhd_budget`, `test_eod_ohlcv_does_not_drain_eodhd_tokens`.

**Validation**
- ruff@0.4.0 clean + format clean; mypy clean on both src files.
- `tests/application/test_schedule_tasks.py`, `tests/domain/test_provider_budget.py`, `tests/unit/use_cases/test_daily_budget_tracker.py`: all pass. Full `-m unit` suite green except one **pre-existing, unrelated** failure (`test_settings.py::test_settings_defaults`, `dispatcher_max_attempts` env leak — touches none of these files).
- Rebuilt + redeployed `market-ingestion-scheduler` and `market-ingestion-worker`; both `healthy`. New marker `_YAHOO_ROUTED_EOD_TIMEFRAMES` confirmed live in the running scheduler. Post-deploy: `scheduler_tick_complete budget_limited=0`, 2000 policies evaluated, **zero errors**, alpaca budget still consuming normally (proves the gate still works for non-skipped providers).

## Recommendations (follow-up decisions — not applied)
1. **Wire `EodhdQuotaService` into the worker** (pass `quota_service=` to both `ExecuteTaskUseCase` constructions in `worker.py`) — the only true hard 100k/day, cross-replica guard. Coordinate with the libs/messaging sibling session.
2. **Re-model `DailyBudgetTracker`** to read the Valkey cumulative counter (depends on #1); until then treat its headroom metric as unreliable. Consider replacing the misleading "cumulative spend" framing with honest *instantaneous bucket headroom* = `tokens / burst`.
3. **Raise fundamentals priority** above OHLCV (e.g. fundamentals→6) so that if any EODHD-charged contention remains, the 10-credit high-value calls win. Low-risk seed migration; deferred pending the priority-policy decision.
