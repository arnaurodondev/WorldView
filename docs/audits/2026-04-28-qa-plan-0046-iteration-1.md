# QA Audit — PLAN-0046 Portfolio Correctness & Analytics, Iteration 1

**Date**: 2026-04-28
**Auditor**: QA Lead (strict gate)
**Branch**: `feat/content-ingestion-wave-a1`
**Commits in scope**: f377f4a (W1) → 46d9a4e (W2) → 4275851 (W3) → 52e6b2a (W4) → 8686f77 (W5)
**DB head**: portfolio_db @ `0012` (verified)
**Stack**: 59 containers, all healthy at audit start

---

## Executive Verdict

**FAIL** — 4 BLOCKING / 5 CRITICAL / 9 MAJOR / 4 MINOR findings.

The plan moved the **schema and code** forward correctly: every migration is applied (0009–0012), all 5 new endpoints exist and respond, root portfolio is provisioned, and the new analytics components are wired into the page. But the user-facing experience is **broken in three of the five originally-targeted areas** (F-001 / F-002 / F-005) because data backfill, runtime config, and worker scheduling were not closed:

- **Snapshot worker** sleeps 6.7 hours from boot to first run — `portfolio_value_snapshots` is empty in the running stack, so the equity chart is permanently empty until 21:30 UTC. No on-startup catch-up.
- **Risk metrics** therefore returns nulls for everyone (n_returns=0). The "metric strip" displays "—" across all 5 tiles. The user sees a UI that **looks** finance-grade but **conveys no data**.
- **`transactions.amount`** column was added (good) but **0 of 289 rows are populated** because no re-sync has run and there is no migration backfill. Every existing DIVIDEND row still shows blank in the Total column — the original F-002 user complaint is not fixed in production data.
- **`watchlist_members` ticker/name/instrument_id** populate correctly only when the entity is in the local instruments cache. **All 13 seeded rows have NULL ticker** because the seed entity_ids don't match instruments. The plan promised a backfill script (T-46-2-01) — **it was never written**. The watchlist tab displays "—" for every ticker until the user manually re-adds each.
- **F-001 holdings drift**: 46 duplicate transaction groups remain in the DB. The `repair_holdings_after_replay_drift.py` script exists but was not run.

In short: the **platform** is plan-complete; the **product** is not. A user logging in today sees:
1. Empty equity chart with "no snapshots yet" message
2. Risk metrics strip with "—" everywhere
3. Dividend rows with no amounts
4. Watchlist tickers blank
5. Holdings still inflated

The **design-system polish** of the new components is good (heavy comments, font-mono tabular-nums, no AI fingerprints, real Skeleton/empty/error states). The **integration with live data** is what failed.

---

## Findings

### F-001 — Snapshot worker has zero startup catch-up; equity chart is empty for hours
- **Severity**: BLOCKING
- **Layer**: backend-correctness / scheduling
- **Where**: `services/portfolio/src/portfolio/workers/portfolio_snapshot_worker.py:254-280`
- **What**: Worker boots, computes seconds-until-21:30-UTC, sleeps that long. There is no `run_once(today)` call before the sleep, no backfill of missed days, no health probe that the snapshot table contains today's row. After every container restart the equity curve is empty for up to 24 hours.
- **Evidence**:
  ```
  portfolio-snapshot-worker-1 | sleep_seconds: 24193
  ```
  ```
  SELECT count(*) FROM portfolio_value_snapshots; →  0
  ```
  ```
  GET /v1/portfolios/{root}/value-history → {"points":[]}
  ```
- **Suggested fix**: At worker startup, check if today's row exists for each non-root portfolio; if not, run `run_once(today)` immediately, THEN enter the 21:30 schedule loop. Also: docker-compose entrypoint should run `backfill_portfolio_value_snapshots.py` once on the first deploy.
- **Auto-fixable**: YES (10-line patch + entrypoint hook)

### F-002 — `portfolio_value_snapshots` empty in the live stack
- **Severity**: BLOCKING (downstream of F-001)
- **Layer**: backend-correctness / data
- **Where**: `portfolio_db.portfolio_value_snapshots`
- **What**: The plan's Wave 4 acceptance gate said: "Backfill script writes 252 rows for an active portfolio in <2 min". The script (`backfill_portfolio_value_snapshots.py`) exists but was **not run** as part of deploy, so the table contains 0 rows.
- **Evidence**: `SELECT count(*) FROM portfolio_value_snapshots;` → `0`
- **Suggested fix**: Run the backfill once: `docker compose exec portfolio python -m portfolio.scripts.backfill_portfolio_value_snapshots`. Add this to the deploy / `make seed` flow.
- **Auto-fixable**: YES (one command)

### F-003 — DIVIDEND `amount` column is 0/289 populated; user-visible bug from the original audit is NOT fixed in data
- **Severity**: BLOCKING
- **Layer**: backend-correctness / data
- **Where**: `portfolio_db.transactions.amount`
- **What**: F-002 in the original audit was the headline complaint: dividend rows show $0 total. PLAN-0046 W1 / T-46-1-01 added the column and the code path to capture `amount` from SnapTrade. **But no brokerage re-sync has happened**, so 0 of 289 transactions have `amount` populated. The TransactionsTable still displays "—" for every dividend Total. The frontend was code-changed correctly; the data was not.
- **Evidence**:
  ```
  SELECT count(*) FROM transactions WHERE amount IS NOT NULL; → 0
  Found 18 dividend rows in first 20: amount=None for all
  ```
- **Suggested fix**: Trigger brokerage re-sync for every connected user. For seeded data without a brokerage, the seed must be re-run with the updated SnapTrade fixture that carries `amount`. Add a smoke test that asserts at least one dividend has `amount IS NOT NULL` after seed.
- **Auto-fixable**: PARTIAL (re-seed is auto; live brokerage re-sync requires user action)

### F-004 — Holdings replay drift NOT cleaned up; 46 duplicate transaction groups remain
- **Severity**: BLOCKING
- **Layer**: backend-correctness / data
- **Where**: `portfolio_db.transactions`
- **What**: The plan's W1 / T-46-1-04 introduced `repair_holdings_after_replay_drift.py` to detect and zero out drift. The script exists but was not run; the DB still has 46 groups of duplicate transactions (same `instrument_id, executed_at, quantity, price`). Per the original audit, the user sees inflated quantities (8–10× broker truth). That hasn't changed.
- **Evidence**:
  ```sql
  SELECT COUNT(*) FROM (
    SELECT instrument_id, executed_at, quantity, price, COUNT(*) c
    FROM transactions GROUP BY instrument_id, executed_at, quantity, price
    HAVING COUNT(*) > 1
  ) sub;
  → 46
  ```
- **Suggested fix**: Run `python -m portfolio.scripts.repair_holdings_after_replay_drift --dry-run` then without dry-run for the affected portfolios.
- **Auto-fixable**: YES (one command, but requires sign-off because it mutates production data)

### F-005 — `watchlist_members` ticker/name/instrument_id are NULL for 100% of seeded rows
- **Severity**: CRITICAL
- **Layer**: backend-correctness / data
- **Where**: `portfolio_db.watchlist_members`
- **What**: T-46-2-01 promised "Existing rows backfilled by a separate script". **The script was not written**. All 13 seeded rows show NULL ticker/name. The watchlist tab UI shows "—" for every entry until the user manually deletes and re-adds each member.
- **Evidence**:
  ```
  SELECT count(*) FILTER (WHERE ticker IS NOT NULL), count(*) FROM watchlist_members;
  →  with_ticker=0  total=13
  ```
- **Suggested fix**: Write `services/portfolio/scripts/backfill_watchlist_member_denorm.py` that iterates `watchlist_members WHERE ticker IS NULL`, joins to `instruments` by `entity_id`, populates the three fields. Add to deploy hook.
- **Auto-fixable**: YES (script + run)

### F-006 — Risk metrics endpoint does not follow the standard error contract
- **Severity**: MAJOR
- **Layer**: api / consistency
- **Where**: S9 `services/api-gateway/src/api_gateway/routes/risk_metrics.py` (likely)
- **What**: Other portfolio endpoints (value-history, exposure) return `{"error_code": "PORTFOLIO_NOT_FOUND", "message": "...", "details": {}}`. Risk-metrics returns `{"detail": "Portfolio not found"}`. Inconsistent error shape breaks frontend error handlers that switch on `error_code`.
- **Evidence**:
  ```
  GET /v1/portfolios/{nonexistent}/value-history → {"error_code":"PORTFOLIO_NOT_FOUND",...}
  GET /v1/portfolios/{nonexistent}/risk-metrics → {"detail":"Portfolio not found"}
  ```
- **Suggested fix**: Use the same exception handler / error envelope as the other `/v1/portfolios/{id}/...` endpoints.
- **Auto-fixable**: YES

### F-007 — Exposure silently falls back to cost-basis when market-data quote 401s
- **Severity**: CRITICAL
- **Layer**: backend-correctness / observability
- **Where**: `services/portfolio/src/portfolio/infrastructure/market_data/current_price_client.py:69-75` + `services/portfolio/src/portfolio/application/use_cases/get_exposure.py:144`
- **What**: Portfolio service calls `POST /api/v1/quotes/batch` against market-data without authentication; market-data returns `401 Unauthorized`. The client logs a `warning` and returns an **empty dict**. The use case treats missing-keys as "no quote → fall back to `average_cost`" (line 144). The exposure response therefore reports **cost basis** as `invested`, mis-labelled as a current-market number. The user sees `gross_exposure_pct: 1.0` and `leverage: 1.0` — values that look plausible but actually reflect the buy price, not today's market value.
- **Evidence**:
  ```
  portfolio-1 | {"event": "HTTP Request: POST http://market-data:8003/api/v1/quotes/batch \"HTTP/1.1 401 Unauthorized\""}
  portfolio-1 | {"status": 401, "instrument_count": 17, "event": "current_price_unexpected_status", ...}
  GET /v1/portfolios/{demo}/exposure → invested=361277.38 (matches Σ qty*avg_cost — NOT live prices)
  ```
- **Suggested fix**: (a) Fix the auth — portfolio service must pass an internal-JWT to market-data. (b) On failure, return a partial response with a `prices_stale: true` flag, so the frontend can show a "stale" badge instead of pretending the number is live.
- **Auto-fixable**: PARTIAL (auth fix YES; protocol change requires schema decision)

### F-008 — EquityCurveChart references non-existent CSS variables `--color-positive` / `--color-negative`
- **Severity**: MAJOR
- **Layer**: frontend-code-quality
- **Where**: `apps/worldview-web/components/portfolio/EquityCurveChart.tsx:278`
- **What**: The chart line uses `stroke={isUp ? "var(--color-positive, #22d3aa)" : "var(--color-negative, #ef4444)"}`. The actual design tokens defined in `app/globals.css:81-82` are `--positive` (raw HSL triplet) and `--negative`, consumed via `hsl(var(--positive))`. There is no `--color-positive`. The `var()` resolves to the hex fallback every time, defeating the design-system token. If a theme ever flips palette, the chart line will not update.
- **Evidence**:
  ```css
  /* globals.css */
  --positive: 174 42% 40%;
  --negative: 0 63% 62%;
  ```
  ```ts
  // EquityCurveChart.tsx:278 — wrong token names
  stroke={isUp ? "var(--color-positive, #22d3aa)" : "var(--color-negative, #ef4444)"}
  ```
- **Suggested fix**: `stroke={isUp ? "hsl(var(--positive))" : "hsl(var(--negative))"}`.
- **Auto-fixable**: YES (one-line)

### F-009 — Snapshot worker idle for 6.7 hours after restart with no progress signal in UI
- **Severity**: MAJOR
- **Layer**: frontend-ux / backend-coordination
- **Where**: `apps/worldview-web/components/portfolio/EquityCurveChart.tsx` empty state + worker behaviour
- **What**: When `points.length === 0`, the chart shows "No snapshots yet — the worker writes one per trading day." This is technically accurate but unhelpful: the worker won't run for 6+ hours. The user has no way to know "the system is working as intended" vs "the worker is broken". A finance-grade UI should expose:
  - last successful snapshot timestamp (NULL → "never")
  - next scheduled run time
  - "Trigger snapshot now" admin button (or auto-trigger on startup, see F-001)
- **Suggested fix**: Add a `GET /v1/portfolios/{id}/value-history` `metadata.last_snapshot_at` field; render a sub-line under the empty state: "Next snapshot: tonight 21:30 UTC".
- **Auto-fixable**: PARTIAL (requires API addition)

### F-010 — `Add Position` add-watchlist-member silently produces NULL ticker when instrument is unknown
- **Severity**: MAJOR
- **Layer**: backend-correctness / UX
- **Where**: `services/portfolio/src/portfolio/application/use_cases/watchlist.py:262-289`
- **What**: When the user adds a watchlist entity that doesn't match any local instrument (`instruments` table), the use case writes the row with NULL ticker/name/instrument_id and returns 201. The frontend gets back a member that will display as "—" forever. There's no warning to the user, no event emitted to trigger an instrument-fetch, and no retry mechanism.
- **Evidence**:
  ```
  POST /v1/watchlists/{id}/members {entity_id: "11111111-0099-..."} → 201
  Result row: ticker=NULL, name=NULL, instrument_id=NULL
  ```
- **Suggested fix**: Either (a) reject the add with a 400 if no instrument can be resolved, OR (b) emit a `watchlist_member_unresolved` event that triggers a delayed re-resolve job, OR (c) return the 201 but include a `resolution: "pending"` field so the frontend renders an inline "resolving…" badge.
- **Auto-fixable**: PARTIAL (requires UX decision)

### F-011 — Inconsistent endpoint shapes: `/v1/holdings/{id}` returns bare array, `/v1/portfolios` returns paginated envelope
- **Severity**: MAJOR
- **Layer**: api / consistency
- **Where**: S9 proxy `/v1/holdings/{portfolio_id}`
- **What**: `GET /v1/portfolios` returns `{"items":[...],"total":N,"limit":100,"offset":0}` (paginated envelope). `GET /v1/holdings/{id}` returns a bare `[…]` array with 17 items, no total. Mixing two shapes in the same domain forces gateway code to special-case each endpoint and prevents standard pagination components from working.
- **Suggested fix**: Standardise on the envelope shape across all list endpoints. Add `items / total / limit / offset` to holdings.
- **Auto-fixable**: YES (additive — keep the bare array as a fallback for compatibility)

### F-012 — `GET /v1/portfolios/{id}/transactions` does not exist; gateway has no proxy
- **Severity**: MAJOR
- **Layer**: api
- **Where**: S9 OpenAPI: only `/v1/transactions` exists, not `/v1/portfolios/{id}/transactions`
- **What**: The natural REST hierarchy `portfolios/{id}/transactions` is missing — clients must use the flat `/v1/transactions?portfolio_id=…` filter. No big deal in isolation, but the analytics endpoints DO use the nested form (`/portfolios/{id}/value-history`, `/exposure`, `/risk-metrics`). Inconsistent path style across the same resource.
- **Evidence**: `GET /v1/portfolios/{id}/transactions → 404`. OpenAPI confirms the route doesn't exist.
- **Suggested fix**: Either expose the nested form, or document the flat form as canonical and remove the `/portfolios/{id}/exposure` nested style. Pick one.
- **Auto-fixable**: PARTIAL (additive route)

### F-013 — `DELETE /v1/portfolios/{id}` has no S9 proxy; root delete-guard is unverifiable
- **Severity**: MAJOR
- **Layer**: api / plan-acceptance
- **Where**: S9 OpenAPI exposes `/v1/portfolios` GET/POST only — no DELETE
- **What**: PLAN-0046 W3 acceptance criterion #4 states: "Cannot delete root via DELETE /v1/portfolios/{id} — returns 400 with RootPortfolioNotArchivableError". This cannot be tested through the gateway because no DELETE proxy exists. The S1 service has the DELETE handler, but the gateway never forwards it. The "Delete button hidden for root" UX claim in W3 is also moot — there's no Delete button anywhere in the portfolio page.
- **Evidence**: `DELETE /v1/portfolios/{any} → 404` from gateway.
- **Suggested fix**: Either (a) add the gateway proxy and a UI Delete button (closes the loop), or (b) explicitly mark the root-guard acceptance criterion as N/A in TRACKING.md and remove the test claim from the plan.
- **Auto-fixable**: YES (add gateway proxy)

### F-014 — Risk metrics returns six metric fields without context — no `as_of`, no `data_quality` flag
- **Severity**: MAJOR
- **Layer**: api / observability
- **Where**: `GET /v1/portfolios/{id}/risk-metrics`
- **What**: Response is `{"drawdown_max":null, "volatility_annualized":null, ..., "n_returns":0}`. With `n_returns=0` it's clear nothing could be computed, but the response gives no other context — when was this computed, what was the lookback range used, what's the SPY benchmark date range? A finance-terminal endpoint should return an `as_of` timestamp and a `data_quality: { points: 0, lookback_days: 90, status: "insufficient_data" }` block so the UI can render a meaningful explanation instead of just "—".
- **Suggested fix**: Add `as_of`, `lookback_window: {from, to}`, and `data_quality.status` enum (`ok | insufficient_data | benchmark_unavailable`).
- **Auto-fixable**: YES (additive)

### F-015 — Risk metrics strip displays "—" across all 5 tiles with no explanation
- **Severity**: MAJOR
- **Layer**: frontend-ux
- **Where**: `apps/worldview-web/components/portfolio/RiskMetricsStrip.tsx`
- **What**: Per F-002 / F-009, the live stack has zero snapshots → all metrics are null. The strip renders five "—" cells. There's no inline message explaining *why* the metrics are unavailable. The Bloomberg-grade behaviour is to show a contextual hint: "Insufficient history (need ≥10 daily snapshots; have 0)".
- **Suggested fix**: Detect `n_returns === 0` from the response and render a single full-width hint row above/below the strip: "Risk metrics will appear after the first ~10 trading days of snapshots."
- **Auto-fixable**: YES

### F-016 — Exposure response is misleading when prices stale: cost basis labelled as `invested`
- **Severity**: CRITICAL
- **Layer**: api / data-integrity
- **Where**: `services/portfolio/src/portfolio/application/use_cases/get_exposure.py:144`
- **What**: When the quote service is unreachable (see F-007), `invested` silently equals `Σ quantity × avg_cost`, not market value. The frontend has no way to know. The exposure card prominently shows a `gross` percentage. With cost basis as the input, this number is meaningless during a market move.
- **Suggested fix**: Add `prices_stale: bool` and `prices_as_of: timestamp` to the response. Frontend renders a "stale" badge or yellow tint if true.
- **Auto-fixable**: YES (additive)

### F-017 — Snapshot worker schedule is fragile (single hard-coded UTC time, no holiday catch-up across multi-day outages)
- **Severity**: MAJOR
- **Layer**: backend-reliability
- **Where**: `services/portfolio/src/portfolio/workers/portfolio_snapshot_worker.py:217-231 + 254`
- **What**: Worker computes "seconds until next 21:30 UTC". If the worker is down for 3 days, on restart it sleeps until tomorrow 21:30 with no catch-up of the missed days. `is_trading_day` filters single days but the loop only runs once per wake-up. A backfill-on-startup-up-to-N-days hook would harden this.
- **Suggested fix**: On startup, iterate `today() - 30 days … today()`, check trading-day, run `run_once(d)` for any day missing a snapshot for any portfolio.
- **Auto-fixable**: YES

### F-018 — `transactions.amount` migration has no backfill path even for re-syncable brokerages
- **Severity**: MAJOR
- **Layer**: data-migration
- **Where**: `alembic/versions/0009_add_transaction_amount.py`
- **What**: The plan acknowledges (T-46-1-01 "no backfill — historical dividends will populate on next sync") that historic transactions stay NULL. But there's no operator script to **trigger** the re-sync, and no documentation of which brokerages need it. For seed data that does not have a brokerage at all, the values are unrecoverable.
- **Suggested fix**: Add a one-shot script `services/portfolio/scripts/trigger_brokerage_resync.py` that enqueues a sync job for every active connection. Document the manual recovery in `docs/services/portfolio.md`. For seed data: regenerate the seed with `amount` populated.
- **Auto-fixable**: YES

### F-019 — No backfill script for `watchlist_member` denorm columns (T-46-2-01 promised but not delivered)
- **Severity**: MAJOR (functional bug; covered also by F-005)
- **Layer**: backend / scripts
- **Where**: `services/portfolio/scripts/` — only 3 scripts present, none for watchlist
- **What**: T-46-2-01 says: "Existing rows backfilled by a separate script (best-effort; user can re-add if missing)". The script doesn't exist. Acceptance criterion #3 of T-46-2-01 is unmet.
- **Suggested fix**: Write `backfill_watchlist_member_denorm.py`. Mirror the resolution logic from `AddWatchlistMemberUseCase`.
- **Auto-fixable**: YES

### F-020 — Cleanup script (`repair_holdings_after_replay_drift.py`) is operator-only with no automated trigger
- **Severity**: MINOR
- **Layer**: backend / ops
- **Where**: `services/portfolio/scripts/repair_holdings_after_replay_drift.py`
- **What**: The script exists but the operational guide hasn't been added to `docs/services/portfolio.md` (T-46-1-04 mentioned this). No CI run, no scheduled task, no Helm hook.
- **Suggested fix**: Document the recovery flow in `docs/services/portfolio.md` Operational Recovery section. Add to the `make seed` post-step or to a new `make repair` target.
- **Auto-fixable**: YES

### F-021 — Frontend does not surface the `kind` of a portfolio in the Holdings table or KPI strip
- **Severity**: MINOR
- **Layer**: frontend-ux
- **Where**: `apps/worldview-web/app/(app)/portfolio/page.tsx` + KPIStrip
- **What**: When the user is on "All Accounts" (root) versus a manual portfolio, the only visual cue is the "ALL" badge in the dropdown trigger. The KPI strip shows the same six tiles either way. A pro user should immediately know which scope they're looking at — the page header could include a small "Aggregating 3 portfolios" sub-line on root, or grey out the Add Position button more prominently than the current 40% opacity.
- **Suggested fix**: Below the page title "Portfolio", render a sub-line: "Viewing All Accounts — 3 portfolios, 17 unique positions" when on root.
- **Auto-fixable**: YES

### F-022 — `EquityCurveChart` "All" period uses a 3650-day sentinel; should be open-ended
- **Severity**: MINOR
- **Layer**: frontend-code-quality
- **Where**: `apps/worldview-web/components/portfolio/EquityCurveChart.tsx:71`
- **What**: `{ label: "All", days: 365 * 10 }` — a 10-year clamp is fine for v1 but users with old portfolios would silently lose data past that. The cleaner fix is to omit `from` entirely and have the server return everything (or to use a sentinel like `from=null`). Right now the API contract requires a numeric `from` — that's the deeper issue.
- **Suggested fix**: Make `from` optional on the value-history endpoint; "All" sends `?to=today` only.
- **Auto-fixable**: YES

### F-023 — `RiskMetricsStrip` does not honor design-system divider tokens (uses inline `border-r border-border`)
- **Severity**: MINOR
- **Layer**: frontend-code-quality
- **Where**: `apps/worldview-web/components/portfolio/RiskMetricsStrip.tsx:68 + 150`
- **What**: The Tile uses `border-r border-border last:border-r-0` (manual). The neighbouring `PortfolioKPIStrip.tsx:117` uses Tailwind `divide-x divide-border` which is the project convention. Two ways of doing the same thing across two components in the same folder. Code-review consistency drift.
- **Suggested fix**: Replace with `<div className="grid grid-cols-5 divide-x divide-border">…</div>`.
- **Auto-fixable**: YES

### F-024 — Latency notes (informational, not an issue)
- **Severity**: NIT
- **Layer**: api / performance
- **What**: All measured endpoints respond in <50ms p99 for the seeded data. value-history 22ms, exposure 30ms, risk-metrics 48ms, watchlist members 10ms. Within budget.

---

## Block-by-Block Summary

### Block 1 — F-001..F-005 verification
| Original | Code | Schema | Data | UX | Verdict |
|----------|------|--------|------|----|---------|
| F-001 holdings drift | ✅ snapshot path landed | ✅ | ❌ 46 dup groups | ❌ user still sees inflated qty | NOT FIXED |
| F-002 DIV amount | ✅ adapter reads `amount` | ✅ column added | ❌ 0/289 populated | ❌ blank Total still | NOT FIXED |
| F-003 watchlist members | ✅ endpoint exists | ✅ denorm cols added | ❌ 0/13 ticker populated | ❌ shows "—" everywhere | PARTIAL |
| F-004 root portfolio | ✅ kind + provisioning | ✅ kind enum + unique idx | ✅ All Accounts seeded | ✅ ALL badge present | FIXED (small UX nits in F-013/F-021) |
| F-005 analytics | ✅ 3 endpoints + 4 components | ✅ snapshot table | ❌ 0 snapshots, no data | ❌ all "—" / empty chart | NOT FIXED |

### Block 2 — Frontend visual quality
- **No AI fingerprints found** — no gradient text, no decorative shadows, no `transition-bounce`, no `border-l-2` decorative stripes.
- **All numeric cells use `font-mono tabular-nums`** consistently.
- **Empty / loading / error states** are present in all three new components. ✅
- **One token bug**: F-008 (CSS var name).
- **One consistency drift**: F-023 (divide-x vs border-r).
- Heavy inline comments per the user-instruction memory. ✅

### Block 3 — UX gaps still amateur
- F-009 (worker idle no signal), F-015 (no metric-strip explanation), F-021 (no scope hint on root)
- The dashboard `PortfolioSummary`, KPI strip — these were not in PLAN-0046's scope but are visually consistent with the new analytics section.
- Date format: ISO `2026-04-28` used everywhere. ✅
- No compact-million formatting on prices (361,277.38 is shown in full). Acceptable for v1 but a "$361.3K / $1.2M" toggle is a known finance-terminal UX upgrade.

### Block 4 — Backend correctness sanity
- DB head: 0012 ✅
- Migrations 0009 / 0010 / 0011 / 0012 all applied ✅
- Tables exist and have expected shape ✅
- 17 holdings on Demo, 0 on Test/Test2, root fans out correctly ✅
- 0 snapshots (F-002 BLOCKING)
- 46 duplicate transaction groups (F-004 BLOCKING)

### Block 5 — Container logs scrub
- portfolio: `current_price_unexpected_status: 401` warnings — F-007
- api-gateway: clean except OIDC discovery warning (expected for dev)
- portfolio-snapshot-worker: `started` then `sleeping(24193)` — F-001
- worldview-web: clean

---

## Plan Acceptance Criterion Audit

Cross-referencing PLAN-0046 acceptance criteria against the live stack:

| Wave | Criterion | Live Status |
|------|-----------|-------------|
| W1 T-46-1-01 | Re-sync brokerage → DIV row shows correct cash amount | ❌ no re-sync; 0/18 div rows have amount |
| W1 T-46-1-02 | `get_account_positions` port + impl + unit test | ✅ (code) — not exercised in live |
| W1 T-46-1-03 | After sync, holdings.qty = SnapTrade qty | ❌ not verified live |
| W1 T-46-1-04 | Repair script idempotent + dry-run | ✅ (code) — not run |
| W1 Validation | Manual: holdings match TastyTrade UI exactly | ❌ NOT DONE |
| W1 Validation | Manual: dividend rows show non-zero amounts | ❌ NOT DONE |
| W2 T-46-2-01 | Migration adds 3 cols nullable + forward-compat | ✅ |
| W2 T-46-2-01 | AddMember resolves at add-time | ⚠️ only when instrument exists; silent NULL otherwise |
| W2 T-46-2-01 | Existing rows backfilled by a script | ❌ SCRIPT NOT WRITTEN |
| W2 T-46-2-02 | GET /watchlists/{id}/members returns 200 | ✅ |
| W2 Validation | Add a symbol → row appears in <500ms | ✅ for known instruments |
| W3 T-46-3-01 | All existing portfolios get kind='manual' | ✅ |
| W3 T-46-3-02 | New user → root created | ⚠️ not exercised live (only existing user has root) |
| W3 T-46-3-02 | Cannot DELETE root | ❌ untestable through gateway (no DELETE proxy) |
| W3 T-46-3-04 | Default-select root on first load | ✅ (code) |
| W3 T-46-3-04 | Delete button disabled with tooltip | ❌ no Delete button in UI at all |
| W4 T-46-4-01 | Idempotent upsert verified | ⚠️ unit-test only; no live data |
| W4 T-46-4-02 | Worker runs once at scheduled time | ⚠️ schedule fires 21:30 UTC; no startup catch-up |
| W4 T-46-4-04 | Backfill writes 252 rows in <2 min | ❌ NOT RUN |
| W4 Validation | Manual: rows in `portfolio_value_snapshots` | ❌ TABLE EMPTY |
| W5 T-46-5-01 | Returns sorted ascending | ✅ (with empty array) |
| W5 T-46-5-02 | Handles empty portfolio (zeros not NaN) | ✅ |
| W5 T-46-5-03 | Sharpe within 0.01 of reference | ⚠️ unit-test claim; no live data to verify |
| W5 T-46-5-04 | Chart renders with real data | ❌ no real data |
| W5 T-46-5-06 | null metrics show "—" not "NaN" | ✅ |

**Of 25 verifiable criteria: 12 ✅, 6 ⚠️, 7 ❌.**

---

## Required Actions Before Sign-Off

In priority order:

1. **Run the snapshot backfill** — `python -m portfolio.scripts.backfill_portfolio_value_snapshots`. This unblocks the equity chart, risk metrics, and value-history responses.
2. **Add startup catch-up to PortfolioSnapshotWorker** — eliminates the 6.7-hour empty-chart window on every restart (F-001/F-017).
3. **Run the holdings drift repair** — `python -m portfolio.scripts.repair_holdings_after_replay_drift`. Closes F-004.
4. **Trigger brokerage re-sync** (or regenerate seed with `amount`) — closes F-003.
5. **Write `backfill_watchlist_member_denorm.py`** + run it — closes F-005/F-019.
6. **Fix the CSS var name** in EquityCurveChart — F-008 (one-line).
7. **Standardise the risk-metrics error envelope** — F-006.
8. **Wire portfolio service auth to market-data** — F-007/F-016 (exposure misleadingly shows cost basis).
9. **Decide on DELETE-portfolio gateway proxy + UI** — F-013.
10. **Add `as_of` and `data_quality` to risk-metrics response** — F-014/F-015 (explanatory empty state).

---

## Verdict

**FAIL** — four BLOCKING findings (F-001, F-002, F-003, F-004), each independently sufficient to fail sign-off. The plan delivered a strong code/schema layer but skipped the data-side closeout. The user-facing pain reported in the original 2026-04-28-qa-plan-0044-followup-report is **still present** in the live stack for three of the five issues that PLAN-0046 was created to address.

**Recommended path**: do NOT close PLAN-0046 yet. Cut a small follow-up wave **PLAN-0046.1 — Live Data Closeout** with the 10 actions above. Most are 1–2 hour tasks; the whole closeout fits in a single working day.
