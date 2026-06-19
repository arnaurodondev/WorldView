# Frontend Functional QA — Deployed Container

- **Date:** 2026-06-18 (run against freshly-deployed container)
- **Frontend:** http://localhost:3001 (Next.js 15, production container)
- **Backend:** http://localhost:8000 (api-gateway / S9)
- **Method:** Playwright (chromium, headless), two viewport passes — **1920×1080** and **1440×900**, full-page screenshots
- **Capture script:** `apps/worldview-web/scripts/qa-capture.mjs` (standalone, NOT committed)
- **Screenshots:** `docs/audits/2026-06-16-frontend-qa/screenshots/` (41 PNGs; prefix `1920-` / `1440-`)
- **Raw per-page data:** `docs/audits/2026-06-16-frontend-qa/qa-data.json`

## Auth mechanism (discovered)

Dev Login is active (Zitadel not configured). The login page shows a **"Dev Login (no Zitadel)"** ghost button (`00-login-page.png`). `POST /api/v1/auth/dev-login` works through the frontend proxy and returns a real RS256 JWT for the seeded demo user (`demo@worldview.dev`).

**Caveat found:** dev-login returns the token in the body but sets **no httpOnly refresh cookie**, so AuthContext loses the session on every full page reload (the subsequent `POST /api/v1/auth/refresh` 401s and the client redirects to `/login`). This is fine for the real SPA (client-side nav preserves the in-memory token) but means a pure `page.goto()` QA harness cannot stay authenticated across reloads. The script handles this by intercepting `POST /api/v1/auth/refresh` and fulfilling it with a fresh dev-login token, giving a stable authenticated session. Worth noting as a fragility: a hard browser refresh in real local-dev use logs the user out.

---

## Summary table

| Area | Status | Evidence |
|------|--------|----------|
| Login / Dev Login | PASS | `00-login-page.png` |
| Dashboard | PASS | `1920-dashboard.png` |
| Portfolio | PASS | `1920-portfolio.png` |
| Chat | PASS | `1920-chat.png` |
| Watchlists | DEGRADED | `1920-watchlists.png` (member counts read 0) |
| Alerts | PASS | `1920-alerts.png` |
| News | PASS | `1920-news.png` |
| Instrument — Quote tab | PASS | `1920-instrument-AAPL-quote.png` |
| Instrument — Financials tab | PASS | `1920-instrument-AAPL-financials.png` |
| Instrument — Intelligence tab | DEGRADED | `1920-instrument-AAPL-intelligence.png` (graph empty, side rails skeleton) |
| **Screener — default grid** | **PASS** | `1920-screener-01-default.png` (50 rows, 669 total) |
| **Screener — Column Settings (L3/L4/L5 selectable)** | **PASS** | `02a` / `02c` |
| **Screener — Intelligence filters (no Backend-Pending)** | **PASS** | `03` |
| **Screener — Live Catalysts preset** | **DEGRADED (data)** | `04` (applies, 0 rows) |
| **Screener — NL search** | **FAIL (backend config)** | `05a` / `05b` (503) |
| `/indices` (bare) | N/A | `1920-indices.png` (404 — no such route; only `/indices/[ticker]`) |

---

## Detailed findings

### SCREENER (focus area) — the enhancements work end-to-end

**1. Default view — PASS.** `1920-screener-01-default.png`. AG Grid renders **50 visible rows** (virtualized; backend `total` = **669** instruments). Sectors, price, chg%, mkt cap, P/E, fundamentals, intelligence (News 7d), 52W range and 30-day sparklines all render with real data. Backend `POST /v1/fundamentals/screen` returns **200** with rich rows (verified directly).

**2. Column Settings popover — PASS (the headline fix).** `1920-screener-02a-columns-popover-open.png` shows the popover open with the full column list. The script toggled **6 previously-unreachable columns ON** (1M RTN, 3M RTN, Analyst Tgt, Analyst Upside, Inst Own%, Brief Score) — all 6 checkboxes were found and flipped (`column toggles turned ON: 6`). `1920-screener-02c-grid-with-new-columns.png` shows the grid afterwards with the new **PERF/RETURNS, ANALYST, INTELLIGENCE** column groups visible and populated (NVDA/GOOGL etc. show real return %, analyst targets, ownership %). Grid row count stayed at 50 (1440 pass: 41) — toggling columns does not drop rows. **The IB-L3 returns / IB-L4 analyst+ownership / IB-L5 intelligence columns are now selectable and render data.**

   Backend field coverage (direct, limit=100): `return_1m` 98/100, `return_3m` 94/100, `return_1y` 93/100, `analyst_target_price` 93/100, `institutional_ownership_pct` 93/100, `news_count_7d` 100/100 non-null. Returns columns show real data.

**3. Intelligence filter group — PASS (no Backend-Pending badges).** `1920-screener-03-intelligence-filters.png` — the FILTERS panel opens and the filter groups render. **0 "Backend Pending" badges** detected on the page (previously these gated the intelligence rows). The intelligence filters (news_count_7d, contradictions, has_active_alert, etc.) are wired to live server-side fields (confirmed in `features/screener/lib/build-filters.ts` and by direct API calls below).
   - Note: my text-probe for the two calendar rows ("Upcoming Earnings / Dividend") returned 0 — the labels are rendered differently (likely "Earnings ≤ N" inside a collapsed sub-section), so this is a probe limitation, not necessarily a missing feature. The IB-L5c scalar fields `next_earnings_within_days` / `next_dividend_within_days` ARE mapped in build-filters.ts.

**4. Live Catalysts preset — applies correctly, but returns 0 rows (DATA gap).** `1920-screener-04-live-catalysts.png` — the **Live Catalysts chip is found and highlights active** (yellow border) when clicked; grid transitions 50 → **0 rows** and shows a clean empty state ("SCREENER 0 MATCH" / "No results match your filters — Adjust filters and apply"). The filter is applied correctly; it is the **data** that is empty:
   - Direct API with the exact preset body `{news_count_7d_min:5, has_active_alert:true, recent_contradiction_count_min:1}` → **0 results**.
   - Dropping only the contradiction clause (`news_count_7d_min:5 + has_active_alert:true`) → **7 results**.
   - Root cause: every instrument has `recent_contradiction_count: 0.0` — the KG contradiction rollup is empty universe-wide, so the `contradictions ≥ 1` clause matches nothing. The preset's own source comment acknowledges this ("until [the L-5b rollup worker] populates the snapshot universe-wide, the preset returns few/zero rows… that is the honest output"). **Verdict: feature works; data pipeline (KG contradiction rollup) is not populated, so the flagship preset is effectively empty.**

**5. NL search box — FAIL (backend not configured).** `1920-screener-05a-nl-typed.png` shows "large cap tech with PE under 30" typed into the NL box; `1920-screener-05b-nl-result.png` shows the grid unchanged (50 rows) and the error banner rendered. **`POST /v1/screener/nl-translate` returns 503** with body `{"detail":"NL screener not configured (missing API key)"}` (confirmed directly against :8000). The frontend behaves correctly — it surfaces the translate error and does not silently break — but the feature is **non-functional in this deployment** because the LLM API key is missing from the gateway env. This 503 fires on **every authenticated page** (the NL hook appears to warm up / the request is attempted), polluting the console network log site-wide.

### Instrument detail page

- **Quote tab — PASS.** `1920-instrument-AAPL-quote.png`. Candlestick + volume chart, full metrics sidebar, header quote ($291.72 +0.95%, CAP $4.31T, P/E 35.47x).
- **Financials tab — PASS.** `1920-instrument-AAPL-financials.png`. Dense metrics grid (income statement, margins, growth) + analyst sidebar populated. A grey panel band appears lower-middle (likely an empty/loading sub-section — minor).
- **Intelligence tab — DEGRADED.** `1920-instrument-AAPL-intelligence.png`. Layout renders (DOSSIER rail, DEPTH/TYPE graph controls, central graph canvas, NEWS rail with TONE/POS/NEU/NEG, EVENTS rail) but the **entity graph canvas is empty** ("Select a node or edge to inspect") and the DOSSIER / NEWS / EVENTS side panels are stuck on **skeleton loaders** that did not resolve within the dwell time. Either slow KG/news fetch or no graph data for AAPL on this deployment.

### Other routes

- **Dashboard — PASS.** Very dense and fully populated: portfolio P&L, sector heatmap, holdings, news feed, economic calendar, movers.
- **Portfolio — PASS.** KPI strip, allocation donut, sector breakdown, holdings table with sparklines and P&L coloring.
- **Chat — PASS.** Thread rail with history, composer + suggested prompts, context panel.
- **Alerts — PASS.** Populated active-alert list (many MEDIUM-signal rows).
- **News — PASS.** Full headline feed with timestamps and tickers.
- **Watchlists — DEGRADED.** `1920-watchlists.png` lists 3 watchlists (Tech, EV & Clean Energy, E-Commerce) but the table shows **0 MEMBERS** for each, while the left sidebar WATCHLIST panel simultaneously shows AAPL/MSFT/GOOGL with live quotes. `member_count` is wrong/zero in the list response (the panel reads members from a different path). Also the top IndexStrip was blank on this particular load (resolution race).
- **`/indices` (bare path) — N/A.** Returns the app's clean 404 page. There is no `/indices` list route — only `/indices/[ticker]`. The `404 GET /indices` in the logs is the harness probing a non-route, not a regression.

---

## Console / network issues (cross-cutting)

Observed across the authenticated session (de-duplicated):

1. **`503 POST /api/v1/screener/nl-translate`** — on essentially **every authenticated page**. Cause: NL screener LLM API key missing in gateway env. High console-noise; the NL feature itself is dead until configured.
2. **`404 GET /indices`** — harness-only (no such route).
3. **`500 GET /api/v1/watchlists`** — appeared intermittently on one pass (dashboard/portfolio/etc.); direct call with a token returned 200, so this is **transient/timing** (likely a token-refresh race) rather than a hard failure. Correlates with the watchlists `member_count: 0` oddity — worth a closer look.
4. **`502 GET /api/v1/auth/login`** — fires once at login (the page probes the OIDC login endpoint to decide whether to offer Dev Login; 502 = OIDC not configured, which is expected and is exactly what triggers the Dev Login affordance).
5. **No uncaught JS `pageerror`s** were captured on any route — all console errors were failed-resource (HTTP) errors, not client exceptions.

No `500` was observed from the screener API (`POST /v1/fundamentals/screen` returned 200 throughout).

---

## Verdict

The screener enhancements are functionally **live**: the L3/L4/L5 columns are now reachable from Column Settings and render real data, the intelligence filters are wired with no Backend-Pending badges, and the Live Catalysts preset applies correctly. Two gaps are **backend/data**, not frontend:

- **NL search is dead (503, missing LLM API key)** — configure the gateway NL key. [highest-impact, site-wide console noise]
- **Live Catalysts returns 0 rows** because the KG `recent_contradiction_count` rollup is empty universe-wide — the flagship "intelligence-moat" preset shows nothing until that pipeline populates.

Smaller items: instrument **Intelligence tab graph/rails don't load** (DEGRADED), **watchlists member_count = 0** (+ intermittent `500 /watchlists`), and **dev-login sets no refresh cookie** (hard refresh logs the user out).

`returns_adjustment_quality` is **not present** in the `/v1/fundamentals/screen` response (neither top-level nor per-row) — if the frontend expects it, it is absent; returns columns themselves are well-populated (93–98% non-null) and render correctly.
