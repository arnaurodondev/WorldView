# F1 Frontend Phase A Walkthrough Audit — PLAN-0087 Wave B

**Agent**: F1 (Frontend, VA-5 Phase A)
**Scope**: Phase A surfaces A1–A10 (PRD-0087 §2.1)
**Method**: Static code analysis + endpoint smoke against S9 gateway. **NO browser; no GUI available** — all "visual" findings are inferred from rendering paths in `apps/worldview-web/` source plus the data the surfaces will receive from S9.
**Container**: `worldview-web` on `localhost:3001`, S9 gateway on `localhost:8000`.
**Token**: dev-login JWT for `demo@worldview.local`.
**Auditor honesty caveat**: I cannot capture console errors, layout-shift events, or first-paint timings without a real browser. F1 was designed for Playwright; in this run I substituted the browser with curl + source reading. Two F1 deliverables (screenshots, console-error log) are not produced. Items below labelled **(static-only)** would normally be confirmed live.

---

## 1. Per-surface checklist

Legend: PASS (works as specified) · WARN (works but degraded data) · FAIL (broken / will be visibly wrong on demo path).

### A1 — Login (`/login`)

- **Route**: `apps/worldview-web/app/login/page.tsx`
- **Data path**: probes `/api/v1/auth/login` (302 vs 502), POST `/v1/auth/dev-login` if Zitadel absent
- **Layout components**: `LoginContent`, `Button`, dev-login affordance with amber accent
- **Endpoint**: `POST /v1/auth/dev-login` → 200, ~30ms (verified)
- **Status**: **PASS** (functional)
- **Notes**: dev-login button uses `border-amber-500/50 text-amber-500 hover:bg-amber-500/10` (`app/login/page.tsx:291`). PRD §3.1 HF-10 forbids off-palette colors but the dev-login affordance is intentionally non-token to mark it as a dev shortcut. Fine for demo.

### A2 — Dashboard (`/dashboard`)

- **Route**: `apps/worldview-web/app/(app)/dashboard/page.tsx`
- **Data path**: `DashboardSnapshotPrefetcher` → `GET /v1/dashboard/snapshot`; per-widget queries: `GET /v1/briefings/morning`, `GET /v1/market/heatmap?period=1D`, `GET /v1/market/top-movers?type=gainers&limit=10`, `GET /v1/market/top-movers?type=losers&limit=10`, `GET /v1/fundamentals/economic-calendar`, `GET /v1/fundamentals/earnings-calendar`, `GET /v1/signals/ai?limit=8`, `GET /v1/signals/prediction-markets`, `GET /v1/alerts/pending`, `GET /v1/news/top`, `GET /v1/portfolios/...` (PortfolioSummary)
- **Layout components**: 4-row 12-col grid; widgets `MorningBriefCard`, `MarketSnapshotWidget`, `SectorHeatmapWidget`, `MoversWidgetTabs`, `PortfolioSummary`, `PreMarketMoversWidget`, `PredictionMarketsWidget`, `EconomicCalendar`, `EarningsCalendarWidget`, `PortfolioNewsWidget`, `RecentAlerts`
- **Status**: **FAIL**
- **Findings**:
  - `GET /v1/fundamentals/economic-calendar` → **500** — `EconomicCalendar` widget will hit error fallback
  - `GET /v1/fundamentals/earnings-calendar` → **500** — `EarningsCalendarWidget` will hit error fallback
  - `GET /v1/briefings/morning` returns placeholder narrative `"Portfolio data is being synchronized with upstream services. Your morning briefing will be available shortly — please refresh in a few minutes."` with `cached:true`, `confidence:1.0`, `citations: []`, `sections: []`. Renders verbatim because the empty-state guard in `MorningBriefCard.tsx:225` only fires when **both** narrative and summary are empty. **HF-8** (brief contains placeholder body) and **HF-4** (visible "loading-like" message in primary tile)
  - `GET /v1/market/heatmap?period=1D` returns 8 of 11 sectors with `change_pct: null` and `instrument_count: 0`. Treemap will render mostly grey tiles. **HF-7-adjacent** (heatmap incomplete; A2 quality bar requires "all 11 GICS sectors")
  - `GET /v1/signals/prediction-markets` returns `{items: [], total: 0}` — `PredictionMarketsWidget` empty. **HF-4** (A2 bar: "prediction markets row populated")
  - `GET /v1/alerts/pending` returns `{alerts: [], total: 0}` — `RecentAlerts` empty. A2 bar: "alerts feed shows recent items". History endpoint has 2 alerts but they have `title:"Alert: price_above"`, `ticker:null`, `entity_name:null` → render as `"Alert: price_above"` (placeholder). **HF-4** + **HF-10** (visible placeholder copy)
  - `GET /v1/signals/ai?limit=8` returns `{signals: []}` — `AiSignals` widget empty
  - `GET /v1/dashboard/snapshot` p50 ≈ **2.16 s** for first call (likely missing cache/leg fan-out blocking). Two consecutive calls confirmed 2.15 s + 2.16 s. Dashboard cold load aggregate >2 s before per-widget queries even start. **SF-2** (1.5× target) and approaching **HF-9** (>4 s) once per-widget legs serialize
  - `_meta.partial: true` with `legs_failed: 1` — frontend reads `_meta.partial` but no UI surfaces this state to the user (no banner). **(static-only)**
  - `top_movers_keys` in snapshot is empty `[]` while standalone `/v1/market/top-movers` returns 8 results — shape mismatch between snapshot and per-widget endpoint. **WARN**: snapshot doesn't pre-warm the movers query so widgets refetch. Wasted budget.
  - `news/top` returns 8 articles but every article has `url:null`, `display_relevance_score: 0.0`, `primary_entity_id: null`, `primary_entity_symbol: null` → `MorningBriefCard` "Top Stories" chips will have no anchor target (filter at `MorningBriefCard.tsx:282` only keeps article citations with URLs). **HF-10** (chips render as inert text or hide entirely)
  - `losers` endpoint returns GOOGL with `daily_return: +0.000955` (positive in losers list — F-304 backend regression). `lib/api/dashboard.ts:151` filters this client-side, so visible result is OK but backend is wrong. **SF-5**

### A3 — Search / Cmd-K → AAPL

- **Route**: global GlobalSearch + `/v1/search/instruments?q=…`
- **Data path**: `GET /v1/search/instruments?q=Apple&limit=5` → 200, 22 ms, returns `01900000-0000-7000-8000-000000001001` (AAPL)
- **Status**: **PASS**
- **Notes**: latency well under 300 ms target; one result returned. PRD A3 calls "instant suggestions" — would need live render to confirm focus/keyboard ergonomics (**static-only**).

### A4 — Instrument page (`/instruments/{entityId}`)

- **Route**: `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx`
- **Data path**: `GET /v1/instruments/{uuid}/page-bundle` (overview + ohlcv + technicals + insider + top_news), `GET /v1/briefings/instrument/{ent}` (subheader), `GET /v1/companies/{uuid}/overview`, `GET /v1/quotes/{uuid}`, `GET /v1/ohlcv/{uuid}?timeframe=1d`, plus tab-specific endpoints below
- **Layout components**: `CompactInstrumentHeader`, `InstrumentAISubheader`, `OverviewLayout`, `FundamentalsTab`, `NewsTab`, `IntelligenceTab`, `AnalystRail`
- **Status**: **FAIL**
- **Findings (header subsystem)**:
  - `GET /v1/instruments/{uuid}/page-bundle` returns `overview.quote: null` and `overview.fundamentals: null` (instrument metadata + ohlcv + technicals + insider all present). Header reads `overview?.quote?.price ?? null` → renders `—` for price/change/changePct (`page.tsx:263–265`); reads `fund?.market_cap`, `fund?.pe_ratio`, etc. → all `—`. **HF-4** ($0/—/null on populated tile). Standalone `/v1/quotes/{uuid}` returns `{price:213.85, change:1.50, change_pct:0.71}` — bundle leg failed silently. Likely contract-spine bug in S9 bundle composer.
- **Findings (Overview tab — chart)**:
  - `GET /v1/ohlcv/{uuid}?timeframe=1d` returns 63 bars (≥30 ✓). `OHLCVChart` should render. **PASS**
  - Chart imports `#0EA5E9` (sky-500), `#10B981` (emerald-500), `#38BDF8` (sky-400), `#84CC16` (lime-500) inside `components/instrument/OHLCVChart.tsx:567,651,678,699`. These are fixed indicator colors not aligned to the Bloomberg/Terminal-Dark palette — **HF-10** under strict polish reading; arguably acceptable for chart-internal indicator series since indicator color convention is universal. Recommend adding to "deferred polish" list.
- **Findings (News tab)**:
  - `GET /v1/news/entity/{ent}` (where ent is AAPL's entity_id `11111111-0001-7000-8000-000000000001`) → **404** `{"detail":"Entity not found"}`. NewsTab will show empty state. PRD A4 bar: "News tab shows recent ranked articles with relevance scores". **HF-4** (visible "no news" where data exists in news/top)
- **Findings (Fundamentals tab)**:
  - `FundamentalsTab` consumes `bundle?.overview?.fundamentals` as `initialData`, then issues its own `GET /v1/fundamentals/{instrumentId}` query. Bundle returns `null`, but standalone is at risk too — needs verification. **WARN**
  - `FundamentalsTab.tsx` has only 1 `tabular-nums` occurrence vs the screener's pervasive use. PRD §3.3: "tabular-nums alignment" required for numbers. **HF-10 / SF-1**
- **Findings (Intelligence tab)**:
  - `GET /v1/entities/{ent}/intelligence` → **500 internal_error** for AAPL. **HF-1** (any 500 on Phase A path)
  - `GET /v1/entities/{ent}/narratives` → 200 but `versions: []` — confirms D-INIT-2 (no narratives). Intelligence tab will show empty narrative
  - `GET /v1/entities/{ent}/paths` → 200 but `paths: []`, `total: 0` — empty path summaries
  - `GET /v1/entities/{ent}/graph` → 200 but **only 4 nodes / 3 edges** for Apple Inc. PRD HF-7 demands ≥10 nodes for AAPL/MSFT/OPENAI/NVIDIA/META. MSFT (entity ...0002) returns only 6 nodes / 5 edges. **HF-7 confirmed**
  - `IntelligenceTab.tsx:115` uses `bg-orange-500/15 text-orange-400 border-orange-500/30` for `macro_event` chip class. Off-token color (Tailwind orange not in palette tokens). **HF-10** (off-palette)
- **Findings (instrument brief subheader)**:
  - `GET /v1/briefings/instrument/{ent}` → **429 Rate limit exceeded** on consecutive calls (single user). Suggests aggressive default rate limit on this route. Demo risk during click-around.

### A5 — Chat empty state (`/chat`)

- **Route**: `apps/worldview-web/app/(app)/chat/page.tsx`
- **Data path**: `GET /v1/threads` → 200, returns 5+ pre-existing threads with `title: null` for all
- **Layout components**: `ScrollArea`, `MessageBubble`, `ThreadItem`, `STARTER_QUESTIONS` array (`features/chat/lib/starters.ts`)
- **Status**: **PASS_WITH_WARNINGS**
- **Findings**:
  - `STARTER_QUESTIONS` are present and well-phrased. **PASS**
  - Existing threads in DB all have `title: null`. ThreadItem will show `PLACEHOLDER_THREAD_TITLE = "New conversation"` for every prior thread. Acceptable empty state, but on a populated dashboard 5 identical "New conversation" rows looks broken. **HF-10**
  - Tool-list / tool-catalog accessibility (PRD A5 bar) **(static-only)** — cannot confirm without live render.

### A6 — Chat news prompt: "What's the latest on NVDA?"

- **Route**: `POST /v1/chat/stream` (SSE)
- **Data path**: traced via `useChatStream` hook (`features/chat/hooks/useChatStream.ts` referenced from `chat/page.tsx:108`)
- **Status**: **STATIC-ONLY** (cannot run an SSE prompt without a browser harness in this audit)
- **Findings**:
  - Citation rendering pipeline exists (citations array → red/yellow/green bar with anchor scroll). **(static-only)**
  - `news/top` and `news/relevant` populated, so the news tool likely has data to retrieve. But all article URLs are `null` (see A2) — citations will exist as `[N1]` but NOT clickable. **HF-3** risk + **HF-4**: "citations valid and clickable" bar will fail.

### A7 — Chat intelligence prompt: "Show me the entity graph around OpenAI"

- **Status**: **STATIC-ONLY** but high-risk
- **Findings**:
  - Underlying `/v1/entities/{id}/intelligence` is **500** for AAPL; if same pattern for OpenAI's entity, the `get_entity_intelligence` tool fails. **HF-1 / HF-6**
  - `/v1/entities/{id}/paths` returns `[]` (D-INIT-2 lineage) — `get_entity_paths` will return "no paths". The chat answer will fall back to a verbal description with no real data. PRD A7 bar: "narrative + path summaries; no fabricated entities" — model may hallucinate to fill the gap. **HF-3 risk**

### A8 — Chat compare prompt: "Compare Apple and Microsoft revenue and margin"

- **Status**: **STATIC-ONLY**
- **Findings**:
  - Underlying tool is `compare_entities` (PLAN-0081). Cannot verify without invoking the chat stream. **STATIC-ONLY**
  - Backing data: `bundle.overview.fundamentals: null` for AAPL — if `compare_entities` reads from the same fundamentals path, comparison will return blanks. **HF-3 / HF-4 risk**

### A9 — Screener (`/screener`)

- **Route**: `apps/worldview-web/app/(app)/screener/page.tsx`
- **Data path**: `POST /v1/fundamentals/screen` with `{filters:[{metric, op, value}]}`, `GET /v1/fundamentals/screen/fields`
- **Status**: **WARN**
- **Findings**:
  - `screen/fields` → 200, list populated. **PASS**
  - `POST /v1/fundamentals/screen` with `{metric:"market_cap", op:"gt", value:500_000_000_000}` → 200 but `results: []`, `total: 0`. Screener with the demo's textbook filter (Tech > $500B) returns **zero rows**. **HF-4** (A9 bar: "results non-empty")
  - **Note on schema**: an early attempt with `field` (instead of `metric`) returned 422 — backend uses `metric` param. The frontend code at `features/screener/lib/build-filters.ts` should be confirmed to emit `metric` (**static-only** — not yet read).
  - AG Grid columns use proper `tabular-nums` (`ag-screener-columns.tsx:60,83,93,102,116`). **PASS** on density/typography
  - Empty-state copy uses `DashboardEmptyState` import — content unverified. **(static-only)**

### A10 — Alerts (`/alerts`)

- **Route**: `apps/worldview-web/app/(app)/alerts/page.tsx`
- **Data path**: `GET /v1/alerts/pending`, `GET /v1/alerts/history`, `GET /v1/news/relevant?limit=20`, `GET /v1/news/top?hours=72&limit=20`
- **Layout components**: `AlertsList`, `AlertHistoryTab`, `ArticleCard`, category filter chips
- **Status**: **FAIL**
- **Findings**:
  - `pending: 0` (empty alerts feed). PRD A10 bar: "View recent alerts; severity badges correct; titles human-readable"
  - `history: 2 alerts` but `title: "Alert: price_above"` and `"Alert: price_below"`, both with `ticker: null`, `entity_name: null`. PRD §3.1 HF-10 explicitly forbids placeholder titles like `"LOW SIGNAL alert"` — these are exactly that pattern. **HF-10 confirmed**.
  - Alert deep-link to instrument requires `entity_id`, present in payload but with no ticker/name. UX shows a UUID-only link. **(static-only)**

---

## 2. Endpoint smoke matrix

```
Endpoint                                          Code  Latency   Bytes
GET /v1/dashboard/snapshot                        200   2.158 s   5503    ⚠ slow + _meta.partial
GET /v1/briefings/morning                         200   0.007 s    390    ⚠ placeholder narrative
GET /v1/market/heatmap?period=1D                  200   0.031 s    725    ⚠ 8/11 sectors null
GET /v1/market/top-movers?type=gainers&limit=10   200   0.010 s   1442    ⚠ price field absent
GET /v1/market/top-movers?type=losers&limit=10    200   0.084 s   1442    ⚠ GOOGL +0.09% in losers
GET /v1/fundamentals/economic-calendar            500   0.011 s     26    ✗ HF-1
GET /v1/fundamentals/earnings-calendar            500   0.011 s     26    ✗ HF-1
GET /v1/signals/ai?limit=8                        200   0.010 s     14    ⚠ empty signals
GET /v1/signals/prediction-markets                200   0.008 s     44    ⚠ empty items
GET /v1/alerts/pending                            200   0.008 s     45    ⚠ empty alerts
GET /v1/alerts/history                            200   0.009 s   1210    ⚠ placeholder titles
GET /v1/news/top                                  200   0.007 s   5609    ⚠ url=null × all
GET /v1/news/relevant?limit=20                    200   0.008 s   5631    ⚠ url=null × all
GET /v1/search/instruments?q=Apple                200   0.009 s    302    ✓
GET /v1/instruments/{uuid}/page-bundle            200   0.041 s  10127    ⚠ quote+fundamentals null
GET /v1/companies/{uuid}/overview                 200   0.026 s   8737    ✓
GET /v1/quotes/{uuid}                             200   0.007 s    406    ✓
GET /v1/ohlcv/{uuid}?timeframe=1d                 200   0.009 s  16218    ✓ 63 bars
GET /v1/entities/{ent}/intelligence               500   0.012 s     26    ✗ HF-1
GET /v1/entities/{ent}/graph                      200   0.010 s   1188    ⚠ 4 nodes (HF-7 fail)
GET /v1/entities/{ent}/narratives                 200   0.008 s     85    ⚠ empty (D-INIT-2)
GET /v1/entities/{ent}/paths                      200   0.004 s     93    ⚠ empty
GET /v1/news/entity/{ent}                         404   0.007 s     29    ✗ "Entity not found"
GET /v1/threads                                   200   0.010 s   1446    ⚠ all titles null
GET /v1/fundamentals/screen/fields                200   0.006 s   2203    ✓
POST /v1/fundamentals/screen (cap>500B)           200   0.016 s     56    ⚠ 0 results
GET /v1/briefings/instrument/{ent}                429   0.003 s     31    ⚠ rate-limit on idle
```

p95 over 25 calls = **~2.16 s** (driven entirely by `/dashboard/snapshot`); without that outlier, p95 ≈ 84 ms.

---

## 3. Console-error proxies (static analysis)

In the absence of live console access, these source patterns will surface as user-visible errors or alerts under the conditions observed above:

| Location | Trigger | Symptom |
|----------|---------|---------|
| `app/error.tsx`, `app/not-found.tsx` | Unhandled errors at page level | Full-page error UI (good fallback) |
| `MorningBriefCard.tsx:189–215` | TanStack Query `isError=true` | "Morning brief unavailable." or "Brief generating…" |
| `MorningBriefCard.tsx:225–235` | brief.narrative + summary both empty | "AI brief unavailable — system initializing" |
| `[entityId]/page.tsx:226–238` | `instrument` falsy after bundle fetch | "Instrument not found." with go-back link |
| `[entityId]/page.tsx:79–83` | `entityId === "undefined"` slug | router replace to `/instruments` (good guard) |
| `EconomicCalendar.tsx` | 500 on `/v1/fundamentals/economic-calendar` | TanStack `isError`, widget fallback (**static-only**) |
| `EarningsCalendarWidget.tsx` | 500 on `/v1/fundamentals/earnings-calendar` | widget fallback (**static-only**) |
| `IntelligenceTab.tsx` | 500 on `/v1/entities/{id}/intelligence` | tab error state (**static-only**) |
| `NewsTab` | 404 on `/v1/news/entity/{id}` | empty news (**static-only**) |
| `lib/api/_client.ts` | non-2xx | throws `GatewayError(status,…)` — every widget catches via TanStack |

Network errors will be surfaced through TanStack Query's `isError` flag. None are unhandled at the React root, so the page does not white-screen, but the cumulative dashboard impression at first paint is "broken / placeholder" — exactly the demo failure mode HF-4/HF-10 forbid.

---

## 4. Off-palette / non-token findings (file:line)

- `app/login/page.tsx:291` — `border-amber-500/50 text-amber-500 hover:bg-amber-500/10` (intentional dev-shortcut signal; INFO)
- `components/instrument/IntelligenceTab.tsx:115` — `bg-orange-500/15 text-orange-400 border-orange-500/30` (HF-10, real off-palette)
- `components/instrument/OHLCVChart.tsx:567,651,678,699` — chart indicator hex colors `#0EA5E9 #10B981 #38BDF8 #84CC16` (chart-internal; record as deferred polish)
- `components/instrument/ChartToolbar.tsx:209–210` — `text-sky-500` (matches chart MA200 line; coupled to OHLCVChart)
- `components/instrument/FundamentalsTab.tsx:149–151,175–176` — comments only (the actual class is `text-warning`); INFO

No `rounded-md/lg/xl` violations found in dashboard/instrument/alerts/chat/screener component folders. `rounded-full` usages are all 1.5–2 px status dots — acceptable.

---

## 5. Other static notes

- `[entityId]/page.tsx` correctly routes `undefined` slug back to `/instruments` (guard against broken link generators).
- `lib/api/dashboard.ts:151` already filters movers client-side (gainers > 0, losers < 0), so the GOOGL-in-losers backend leak is masked at render. Backend should still be flagged.
- `MorningBriefCard.tsx:282–294` filters citations to article-with-URL — given `news/top` returns `url:null` for all articles, "Top Stories" chips will render as nothing (or fall back to non-clickable text), failing PRD A2 bar "citations clickable".
- `bundlewatch.config.json`, `playwright.config.ts`, `qa-iter*.mjs` exist — Playwright harness is present but no run was executed in this audit.

---

## 6. Defect rows

```yaml
- id: D-F1-001
  va: VA-5
  surface: A2
  severity: HF-1
  status: open
  agent: F1
  found_at: 2026-05-09T17:30Z
  reproduce: |
    TOKEN=$(curl -fsS -X POST http://localhost:8000/v1/auth/dev-login \
      -H 'content-type: application/json' \
      -d '{"email":"demo@worldview.local"}' | jq -r .access_token)
    curl -i -H "authorization: Bearer $TOKEN" \
      http://localhost:8000/v1/fundamentals/economic-calendar
  evidence:
    - http_status: 500
    - body: '{"error":"internal_error"}'
    - frontend_consumer: components/dashboard/EconomicCalendar.tsx
  root_cause: |
    Unknown — S9 returns generic internal_error. Likely upstream S7 temporal_events
    transform mismatch (BP-370 lineage) or asyncpg cast bug (BP-180).
  fix_decision: TBD
  spawned_plan: null
  fix_commit: null

- id: D-F1-002
  va: VA-5
  surface: A2
  severity: HF-1
  status: open
  agent: F1
  found_at: 2026-05-09T17:30Z
  reproduce: |
    curl -i -H "authorization: Bearer $TOKEN" \
      http://localhost:8000/v1/fundamentals/earnings-calendar
  evidence:
    - http_status: 500
    - body: '{"error":"internal_error"}'
    - frontend_consumer: components/dashboard/EarningsCalendarWidget.tsx
  root_cause: |
    Same 500 surface as economic-calendar — likely shared transformer in S9
    fundamentals route. Investigate services/api-gateway/src/api_gateway/routes/fundamentals.py.
  fix_decision: TBD

- id: D-F1-003
  va: VA-2
  surface: A4-intelligence-tab
  severity: HF-1
  status: open
  agent: F1
  found_at: 2026-05-09T17:30Z
  reproduce: |
    ENT=11111111-0001-7000-8000-000000000001  # AAPL
    curl -i -H "authorization: Bearer $TOKEN" \
      http://localhost:8000/v1/entities/$ENT/intelligence
  evidence:
    - http_status: 500
    - body: '{"error":"internal_error"}'
    - frontend_consumer: components/instrument/IntelligenceTab.tsx
    - related_defect: D-INIT-2 (zero entity_narrative_versions)
  root_cause: |
    /v1/entities/{id}/intelligence is a composed bundle endpoint (PLAN-0080). Likely
    fails because narratives table empty and the composer has no graceful fallback for
    null narrative versions.
  fix_decision: TBD

- id: D-F1-004
  va: VA-8
  surface: A2
  severity: HF-8
  status: open
  agent: F1
  found_at: 2026-05-09T17:30Z
  reproduce: |
    curl -s -H "authorization: Bearer $TOKEN" \
      http://localhost:8000/v1/briefings/morning | jq .
    # narrative === "Portfolio data is being synchronized with upstream services.
    #               Your morning briefing will be available shortly — please refresh
    #               in a few minutes."
    # citations: []   sections: []   cached: true   confidence: 1.0
  evidence:
    - api_payload: /tmp/brief.json
    - render_path: MorningBriefCard.tsx renders narrative non-empty → bypasses empty-state
  root_cause: |
    S8 morning brief is returning a hard-coded placeholder string when portfolio
    sync has not completed. The frontend's empty-state guard (line 225) only
    fires when narrative AND summary are both empty — non-empty placeholder
    text bypasses the guard. Either S8 must return an actual error code (so
    the error path renders "Brief generating…") or the frontend must detect
    this specific placeholder string.
  fix_decision: TBD

- id: D-F1-005
  va: VA-9
  surface: A2-heatmap
  severity: HF-7
  status: open
  agent: F1
  found_at: 2026-05-09T17:30Z
  reproduce: |
    curl -s -H "authorization: Bearer $TOKEN" \
      "http://localhost:8000/v1/market/heatmap?period=1D" | jq '.sectors[] | {name, change_pct, instrument_count}'
  evidence: |
    8 of 11 sectors have change_pct=null and instrument_count=0; only Consumer
    Discretionary, Financials, and Information Technology have data.
  root_cause: |
    Likely tied to D-INIT-3 (only 12 instruments seeded). PRD A2 quality bar
    requires "treemap, all 11 GICS sectors". Treemap will render with 8 grey
    tiles — visibly broken.
  fix_decision: TBD

- id: D-F1-006
  va: VA-2
  surface: A4-kg-tab, A7
  severity: HF-7
  status: open
  agent: F1
  found_at: 2026-05-09T17:30Z
  reproduce: |
    curl -s -H "authorization: Bearer $TOKEN" \
      http://localhost:8000/v1/entities/11111111-0001-7000-8000-000000000001/graph \
      | jq '{nodes:(.nodes|length), edges:(.edges|length)}'
    # AAPL → {nodes:4, edges:3}
    # MSFT → {nodes:6, edges:5}
  evidence: |
    PRD §3.1 HF-7 demands ≥10 nodes for AAPL/MSFT/OPENAI/NVDA/META.
    Both AAPL and MSFT are below the bar.
  root_cause: |
    KG only has 18 relations total (D-INIT-2 baseline). Demo path will look
    visibly empty.
  fix_decision: TBD

- id: D-F1-007
  va: VA-11
  surface: A4-header
  severity: HF-4
  status: open
  agent: F1
  found_at: 2026-05-09T17:30Z
  reproduce: |
    INS=01900000-0000-7000-8000-000000001001
    curl -s -H "authorization: Bearer $TOKEN" \
      http://localhost:8000/v1/instruments/$INS/page-bundle \
      | jq '{quote: .overview.quote, fund_keys: (.overview.fundamentals | type)}'
    # quote: null
    # fund_keys: "null"
    # but standalone /v1/quotes/$INS returns {price:213.85, change:1.50, ...}
    # and /v1/companies/$INS/overview returns full fundamentals
  evidence: |
    Bundle composer drops the quote and fundamentals legs even though both
    upstream endpoints succeed individually.
  root_cause: |
    S9 page-bundle composer (services/api-gateway, /v1/instruments/{id}/page-bundle)
    has a leg that swallows quote + fundamentals. Frontend renders "—" for
    price/change/marketCap/PE on the most prominent header on the demo path.
  fix_decision: TBD

- id: D-F1-008
  va: VA-5
  surface: A4-news-tab
  severity: HF-4
  status: open
  agent: F1
  found_at: 2026-05-09T17:30Z
  reproduce: |
    ENT=11111111-0001-7000-8000-000000000001
    curl -i -H "authorization: Bearer $TOKEN" \
      http://localhost:8000/v1/news/entity/$ENT
    # 404 {"detail":"Entity not found"}
  evidence: |
    /v1/news/entity/{ent} proxies to S6 NLP /api/v1/entities/{id}/articles.
    S6 returns 404 — entity_id (KG canonical) is not registered in nlp_db
    document_entity_links.
  root_cause: |
    Entity ID mapping mismatch between intelligence_db and nlp_db. The KG
    canonical entity for AAPL has no linked documents in nlp_db.
  fix_decision: TBD

- id: D-F1-009
  va: VA-1
  surface: A2-news, A6 (citations)
  severity: HF-3
  status: open
  agent: F1
  found_at: 2026-05-09T17:30Z
  reproduce: |
    curl -s -H "authorization: Bearer $TOKEN" http://localhost:8000/v1/news/top \
      | jq '.articles[] | {title, url, primary_entity_id, primary_entity_symbol}'
    # url: null   primary_entity_id: null   primary_entity_symbol: null  for ALL articles
  evidence: |
    All 8 returned articles have null URLs and null entity binding. Citations
    in the morning brief and chat answers will not be clickable, failing PRD
    HF-3 "every citation must resolve to a real article".
  root_cause: |
    S6 article ingestion not populating url field; entity linking pipeline
    not writing primary_entity_id back to article rows.
  fix_decision: TBD

- id: D-F1-010
  va: VA-9
  surface: A2-prediction-markets
  severity: HF-4
  status: open
  agent: F1
  found_at: 2026-05-09T17:30Z
  reproduce: |
    curl -s -H "authorization: Bearer $TOKEN" \
      http://localhost:8000/v1/signals/prediction-markets | jq .
    # {"items":[],"total":0,"limit":50,"offset":0}
  evidence: |
    A2 quality bar: "prediction markets row populated". Widget will be empty.
  root_cause: |
    Polymarket adapter not running, OR data not ingested for the demo window.
    Tied to D-INIT-1 (consumers were in Created state at boot).
  fix_decision: TBD

- id: D-F1-011
  va: VA-5
  surface: A2-alerts, A10
  severity: HF-10
  status: open
  agent: F1
  found_at: 2026-05-09T17:30Z
  reproduce: |
    curl -s -H "authorization: Bearer $TOKEN" \
      http://localhost:8000/v1/alerts/history | jq '.alerts[] | {alert_id, title, ticker, entity_name, signal_label}'
    # All rows: title="Alert: price_above" / "Alert: price_below"
    #          ticker=null   entity_name=null
  evidence: |
    AlertsList will render rows whose primary text is the placeholder
    "Alert: price_above". PRD HF-10 explicitly names this pattern as a hard fail.
  root_cause: |
    Alert producer (chat tool create_alert from PLAN-0082) writes the alert
    without resolving entity_id → ticker/entity_name. The S10 alert read path
    does not enrich with entity metadata.
  fix_decision: TBD

- id: D-F1-012
  va: VA-9
  surface: A9-screener
  severity: HF-4
  status: open
  agent: F1
  found_at: 2026-05-09T17:30Z
  reproduce: |
    curl -s -X POST -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
      -d '{"limit":10,"offset":0,"filters":[{"metric":"market_cap","op":"gt","value":500000000000}]}' \
      "http://localhost:8000/v1/fundamentals/screen?limit=10&offset=0"
    # {"results":[],"total":0,"count":0}
  evidence: |
    PRD A9 demo step: "filter sector=Technology, market_cap>500B; results non-empty".
    With only 12 seeded instruments, no fundamentals rows clear the filter.
  root_cause: |
    Tied to D-INIT-3 (instrument seed shortfall) AND missing fundamentals rows
    (market_cap not stored on the 12 seeded instruments).
  fix_decision: TBD

- id: D-F1-013
  va: VA-11
  surface: A2-snapshot
  severity: SF-2
  status: open
  agent: F1
  found_at: 2026-05-09T17:30Z
  reproduce: |
    time curl -s -H "authorization: Bearer $TOKEN" \
      http://localhost:8000/v1/dashboard/snapshot > /dev/null
    # ~2.16 s consistently across 2 cold and 1 warm call
  evidence: |
    Two consecutive measurements: 2.158 s, 2.165 s. _meta: {partial:true, legs_failed:1}.
  root_cause: |
    One leg (likely briefings or alerts/recent given 404s) is not failing fast —
    fan-out is bounded by the slowest leg. Per-widget queries fire AFTER the
    snapshot resolves, so total cold dashboard load is snapshot + max(per-widget).
    Approaching HF-9 (>4 s).
  fix_decision: TBD

- id: D-F1-014
  va: VA-5
  surface: A4-intelligence-tab
  severity: HF-10
  status: open
  agent: F1
  found_at: 2026-05-09T17:30Z
  reproduce: |
    grep -n 'orange-500\|orange-400' apps/worldview-web/components/instrument/IntelligenceTab.tsx
    # IntelligenceTab.tsx:115:  macro_event: "bg-orange-500/15 text-orange-400 border-orange-500/30",
  evidence: |
    Off-palette Tailwind orange used for macro_event chip.
  root_cause: |
    Code uses raw Tailwind utility instead of design-system token (e.g., text-warning
    or a new --accent-macro token).
  fix_decision: fix-now

- id: D-F1-015
  va: VA-5
  surface: A5-chat
  severity: HF-10
  status: open
  agent: F1
  found_at: 2026-05-09T17:30Z
  reproduce: |
    curl -s -H "authorization: Bearer $TOKEN" \
      http://localhost:8000/v1/threads | jq '.threads[] | {thread_id, title}'
    # All rows: title: null
  evidence: |
    Every existing thread has title: null. ThreadItem renders the placeholder
    "New conversation" for all of them — sidebar is full of identical labels.
  root_cause: |
    Post-stream PATCH that should set the LLM-generated title (chat/page.tsx
    docstring §44) is not running OR is failing silently.
  fix_decision: TBD

- id: D-F1-016
  va: VA-8
  surface: A4-ai-subheader
  severity: SF-2
  status: open
  agent: F1
  found_at: 2026-05-09T17:30Z
  reproduce: |
    ENT=11111111-0001-7000-8000-000000000001
    for i in 1 2 3; do
      curl -s -o /dev/null -w '%{http_code}\n' -H "authorization: Bearer $TOKEN" \
        http://localhost:8000/v1/briefings/instrument/$ENT
    done
    # 429 429 429
  evidence: |
    Single user, three sequential calls within 5 s, all return 429.
  root_cause: |
    Rate-limit middleware on /v1/briefings/instrument/{id} is set tight enough
    to fire on idle. During demo click-around the AI subheader will repeatedly
    show "Rate limited" toast.
  fix_decision: TBD

- id: D-F1-017
  va: VA-5
  surface: A4-fundamentals-tab
  severity: HF-10
  status: open
  agent: F1
  found_at: 2026-05-09T17:30Z
  reproduce: |
    grep -c 'tabular-nums' apps/worldview-web/components/instrument/FundamentalsTab.tsx
    # 1
  evidence: |
    Only one tabular-nums occurrence across a 800+-line dense numerical
    grid. PRD §3.3: "tabular-nums alignment" required for all numeric grids.
  root_cause: |
    Class missing on most number-rendering spans in FundamentalsTab.
  fix_decision: fix-now

- id: D-F1-018
  va: VA-7
  surface: A2-movers
  severity: SF-5
  status: open
  agent: F1
  found_at: 2026-05-09T17:30Z
  reproduce: |
    curl -s -H "authorization: Bearer $TOKEN" \
      "http://localhost:8000/v1/market/top-movers?type=losers&limit=10" \
      | jq '.results[] | {ticker, daily_return: .metrics.daily_return}'
    # GOOGL with daily_return=+0.000955 in losers list (and similar leaks)
  evidence: |
    F-304 backend regression. Frontend filters at lib/api/dashboard.ts:151,
    so this is masked at render but indicates the screener-sort upstream is
    unstable.
  root_cause: |
    S3 screener sort is unstable across daily_return ties or near-zero values.
  fix_decision: defer
```

---

## 7. Summary

- **Hard fails on Phase A path**: 12 (HF-1 ×3, HF-3 ×1, HF-4 ×4, HF-7 ×2, HF-8 ×1, HF-10 ×4 — note D-F1-014/015/017 are HF-10 polish, listed once each above)
- **Soft fails**: 2 (SF-2 ×2 perf/rate-limit, SF-5 ×1 backend regression)
- **Most demo-blocking**: D-F1-007 (instrument header `quote+fundamentals` null in bundle), D-F1-004 (morning brief renders placeholder body), D-F1-006 (KG <10 nodes), D-F1-003 (intelligence endpoint 500), D-F1-001/002 (calendar 500s), D-F1-011 (alert placeholder titles)
- **All findings here are root-cause adjacent to D-INIT-1..D-INIT-4** in the register: empty intelligence DB, 12-instrument seed shortfall, and missing consumer state at boot. Fixing those baselines collapses ~half of these defects without per-widget surgery.

Sequence the triage so the seed/baseline fixes (D-INIT-3/4) land before the per-widget UI fixes — otherwise we'll be debugging frontend fallbacks that are correctly handling empty data.
