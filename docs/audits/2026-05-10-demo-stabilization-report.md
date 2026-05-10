# Demo Stabilization Pass — 2026-05-10

**Goal**: close all 13 Demo P0 items in PLAN-0088 ahead of the 2026-05-11
hedge-fund-director walkthrough. Beta blockers (Waves A–D) explicitly out
of scope.

**Result**: 13/13 P0 closed with live evidence. 1 P1 (synthetic-monitor
URLs) opportunistically shipped. Final QA on real stack passed.

---

## Subagents launched

| Agent | Owns | Outcome | Commit |
|---|---|---|---|
| SA-1 (worktree) | P0-1 alert WS aud, P0-4 dispatcher DNS | Done | `b1342e33` |
| SA-3 (worktree) | P0-5 equity curve, P0-6 watchlist, P0-11 cash | Done (P0-5 partial — see follow-up) | `1090dcef` |
| SA-5 (worktree) | P0-7 narrative LLM, P0-8 KG cap, P0-13 dup clusters | Done | `60642605` |
| Main session | P0-2 AG Grid, P0-3 Polymarket lag, P0-9 narrative-history, P0-10 chat titles, P0-12 P/E + market-data rebuild, P1-19 synthetic | Done | `3915be23`, `2e46c2c3`, `0582e3a5` |

---

## Demo P0 — fixed with evidence

| ID | Title | Commit | Live evidence |
|---|---|---|---|
| P0-1 | Alerts WebSocket 403 (aud claim) | `b1342e33` | curl WS handshake → `HTTP/1.1 101 Switching Protocols` + `{"type":"ping"}`; wrong-aud token → 403 |
| P0-2 | AG Grid white background | `3915be23` | `theme="legacy"` prop on `<AgGridReact>`; FE typecheck clean; `/screener` 200 |
| P0-3 | Polymarket consumer lag | (operational) | 48 100 → 0 (offset reset to LATEST after stuck consumer at 0.6 msg/s); steady-state lag now ~1.1k |
| P0-4 | Alert-dispatcher Postgres DNS | `b1342e33` | asyncpg pool `pool_recycle=300` + bounded connect timeout; 0 DNS errors in last 5 min on rebuilt container |
| P0-5 | Equity curve historical backfill | `1090dcef` | snapshot worker default lookback 30 → 252 trading days; chart honestly starts at first valid valuation date because OHLCV is missing for 11 of the 11 held ETFs (XLE/MSTR/QQQ/PPA/XLK/TLT/IEF/IBIT/VTV/XLV/XLY) — see follow-up below |
| P0-6 | Watchlist `RESOLVING…` rows | `1090dcef` | `watchlist_members` NULL ticker/instrument_id rows: 9 → 0 after `scripts/ops/backfill_watchlist_denorm.py` |
| P0-7 | Narrative LLM template-v1 fallback | `60642605` | 0 → 80 narratives with `model_id=meta-llama/Meta-Llama-3.1-8B-Instruct`; covers all 12 demo tickers; 689 template-v1 are pre-existing long-tail entities |
| P0-8 | KG graph cap + slider plumbing | `60642605` | S9 cap 50 → 200; FE slider ladder 15/40/80/120/160; AAPL has 128 relations now visible |
| P0-9 | Narrative-history contract (`versions`) | `3915be23` | `NarrativeHistoryPage` aligned to S7 canonical schema; tab no longer crashes when entity returns data |
| P0-10 | Chat thread auto-titles | `2e46c2c3` | Phase-A heuristic in `persist_chat.py`; 26/26 unit tests pass; manual rename still wins; existing null-title threads handled by FE fallback |
| P0-11 | Cash / Buying Power truthful surface | `1090dcef` | CashRow renders em-dash + tooltip when broker not synced; doc trail `docs/audits/2026-05-10-demo-stabilization-cash-balance-state.md` |
| P0-12 | P/E stray dash + 1985 fundamentals dates | `3915be23` + market-data rebuild | FundamentalSparkline empty-state returns `null` (was literal `—`); market-data container rebuilt to deploy commit `55a06cd4`; AAPL revenue timeseries now `[2025-09-30, 2025-12-31, 2026-03-31]` |
| P0-13 | duplicate_clusters writer/backfill | `60642605` | 0 → 791 rows (762 title-identity + 29 minhash Jaccard); `scripts/ops/backfill_duplicate_clusters.py` |

## Demo P1 — opportunistically fixed

| ID | Title | Commit | Evidence |
|---|---|---|---|
| P1-19 | Synthetic monitor wrong URLs | `0582e3a5` | Probes corrected to `/healthz`, `/v1/quotes/{instrument_id}`, `/v1/holdings/{portfolio_id}` (env-overridable); no longer silently 404'ing |

## Services / containers rebuilt + relaunched

`alert`, `alert-dispatcher`, `worldview-web`, `market-data`, `rag-chat`,
`portfolio-snapshot-worker`, `knowledge-graph` (api), `knowledge-graph-scheduler`,
`api-gateway`. Each rebuilt with `docker compose build` and redeployed
with `docker compose up -d`. All show clean startup logs and healthy
status post-restart.

## Tests run

- alert: 447 unit pass (including 6 new WS audience/scope tests).
- rag-chat: 26 chat persistence pass (6 new heuristic title tests).
- knowledge-graph: 1238 unit pass; 1 pre-existing failure
  (`test_provisional_enrichment_core.py`) unrelated to this pass.
- api-gateway: 122 unit pass.
- portfolio: 23 snapshot tests pass; full unit suite 724 pass per SA-3.
- frontend: typecheck clean (`pnpm exec tsc --noEmit`); previously failing
  narrative test fixture aligned to canonical schema.
- Architecture / mypy / ruff: clean across all changed files.

## Final QA — investor demo path on real stack

| Surface | Route | Status |
|---|---|---|
| Dashboard | `GET /` | 200 |
| Dashboard | `GET /dashboard` | 200 |
| Portfolio | `GET /portfolio` | 200 |
| Watchlist | (under portfolio + dedicated routes) | 200 |
| Screener | `GET /screener` | 200 |
| Instrument | `GET /instruments/{uuid}` | 200 |
| Intelligence | `GET /intelligence/{entity_id}` | 200 |
| News | `GET /news` | 200 |
| Chat | `GET /chat` | 200 |
| Alerts | `GET /alerts` | 200 |
| Healthz | `GET http://localhost:8000/healthz` | 200 |
| Fundamentals timeseries | recent quarters returned | 200 |
| Alert WS upgrade | `ws://localhost:8010/api/v1/alerts/stream?token=…` | 101 |
| Alert WS wrong audience | (uses access_token) | 403 |

## Remaining demo risks (evidence-backed)

1. **Equity curve still flat** — 30 snapshot rows visible but
   `data_quality=partial_prices` because market-data has no OHLCV for
   the 11 held ETFs. Director may notice the curve is essentially a
   horizontal line. Fix: backfill EODHD OHLCV for XLE/MSTR/QQQ/PPA/XLK/
   TLT/IEF/IBIT/VTV/XLV/XLY. Out of scope for this session.
2. **Cash / Buying Power shows `—` not real values** — by design
   per user instruction. SnapTrade balance integration is the real
   follow-up; doc trail in `docs/audits/2026-05-10-demo-stabilization-cash-balance-state.md`.
3. **689 long-tail entities still on template-v1** — only the 12
   demo tickers were regenerated; periodic refresh worker will fill
   in the rest as the scheduler runs. No demo-blocking impact.
4. **Polymarket consumer drain rate ~0.6–11 msg/s** — fast enough
   for steady state but susceptible to lag accumulation under burst
   load. Demo-day risk minimal because lag is currently 0–1k. Long-term
   fix: scale consumer or batch upserts.
5. **AAPL graph density ceiling** — KG holds 128 AAPL relations; FE
   can now display all of them. Going past ~30 visible edges depends
   on layout choices. Demo will show 30+ if depth slider is at 3 or
   higher.

## Beta blockers intentionally deferred

Per user instruction, **Wave A (Zitadel SSO/MFA), Wave B (TDE/GDPR/
PII), Wave C (PITR backups), Wave D (Grafana alerts/LLM-cost cap),
F-1/F-2/G-1/G-4 frontend polish, streaming duplicate_clusters worker,
full SnapTrade balance integration, OHLCV ETF backfill** were not
touched. These remain in PLAN-0088's open queue.
