# PLAN-0050 Strict QA — Iteration 1

**Date**: 2026-04-29
**Branch**: feat/content-ingestion-wave-a1
**Scope**: Wave C + D + E + F-remainder (waves A and B already QA'd in prior iterations)
**Auditor**: Strict QA Gate (automated multi-phase investigation)
**Verdict**: BLOCKING-FIXES-REQUIRED

---

## Summary

| Severity | Count |
|----------|-------|
| BLOCKING | 3 |
| CRITICAL | 4 |
| MAJOR    | 5 |
| MINOR    | 4 |
| NIT      | 2 |
| ENHANCE  | 8 |

---

## Validation Gate Output

### Frontend (apps/worldview-web)

```
pnpm typecheck  → PASS (0 errors)
pnpm lint       → PASS (0 ESLint errors; 1 pre-existing SECURITY warning: ws:// not wss:// in .env)
pnpm test       → PASS (51 test files, 630 tests, 0 failures)
pnpm audit      → 2 moderate vulnerabilities (postcss < 8.5.10 XSS; pre-existing, tracked)
```

### Backend

```
services/api-gateway   → 257 passed, 0 failed
services/market-data   → 535 passed, 0 failed
services/nlp-pipeline  → 551 passed, 0 failed
```

### Container State

All 59 containers healthy at audit start.
Three containers rebuilt and restarted during investigation:
- `worldview-api-gateway-1` (rebuilt — was running pre-Wave-B code; /v1/watchlists/{id}/insights returned 404 from live container despite route existing in source)
- `worldview-market-data-1` (rebuilt — was at migration 009; Wave D added migration 011; /v1/fundamentals/{id}/snapshot returned 500 from container pre-rebuild)
- `worldview-nlp-pipeline-1` (rebuilt — was at migration 0010; Wave E added migration 0011; /v1/news/top returned 500 from container pre-rebuild)

Post-rebuild migration status:
- market-data: upgraded to migration 011 ✓
- nlp-pipeline: upgraded to migration 0011 ✓

---

## Findings

### Finding F-Q1-01 — BLOCKING: Containers Running Pre-Wave Code; Migrations Not Applied Automatically

- **Severity**: BLOCKING
- **Wave**: C, D, E (all waves)
- **File**: `infra/compose/docker-compose.yml` (container lifecycle config)
- **Issue**: All three modified backend services (`api-gateway`, `market-data`, `nlp-pipeline`) were running Docker images built BEFORE the PLAN-0050 Wave C/D/E commits (container creation timestamps 2026-04-28T18:57–19:32, commits at 2026-04-29T10:56–11:08). The live platform was serving stale code: `GET /v1/watchlists/{id}/insights` → 404, `GET /v1/fundamentals/{id}/snapshot` → 500, `GET /v1/news/top` → 500. A rebuild + migration run was required.
- **Evidence**:
  - `docker inspect worldview-api-gateway-1 --format "{{.Created}}"` → `2026-04-28T19:32:21`
  - `docker exec worldview-market-data-1 python3 -m alembic current` → `009` (before rebuild)
  - `docker exec worldview-nlp-pipeline-1 python3 -m alembic current` → `0010` (before rebuild)
  - `curl .../v1/watchlists/{id}/insights` → `404 Not Found` (before rebuild, 200 after)
  - `curl .../v1/news/top` → `{"error":"internal_error"}` (before rebuild, 200 after)
- **Suggestion**: Add `make dev-rebuild` to the PLAN-0050 ship checklist. Consider making migrations auto-run on container start (they already do via the migrate containers — but the migrate container itself needs to be rebuilt to pick up the new migration files). The pre-commit hook or wave commit template should remind the implementer to rebuild affected services.
- **Confidence**: HIGH

---

### Finding F-Q1-02 — BLOCKING: `change_pct` Always Null in Watchlist Insights Response

- **Severity**: BLOCKING
- **Wave**: B
- **File**: `services/api-gateway/src/api_gateway/clients.py:639,721,745`
- **Issue**: `get_watchlist_insights` fetches live quotes from the internal market-data endpoint `/api/v1/quotes/{iid}`. The internal `QuoteResponse` schema has field `last` (not `price`) and has **no `change_pct` field** — those only exist on the S9 proxy's transformed output (the `_map_price_snapshot_to_quote` function). Result: `quote.get("change_pct")` always returns `None`. Every mover in the insights response shows `change_pct: null`, breaking the widget's gainers/losers sort and the `weighted_return_1d` aggregate (always null too).
- **Evidence**:
  ```
  # Live: S9 /v1/quotes/NVDA → {price: 209.53, change_pct: 0.0}  (S9-transformed)
  # Insights /api/v1/quotes/ direct → {last: "199.64", bid: null, ask: null}  (internal schema)
  # Result in insights response: {price: 199.64, change_pct: null}
  ```
  The internal `QuoteResponse` schema (`services/market-data/src/market_data/api/schemas/quotes.py:11-21`) has only `bid`, `ask`, `last`, `volume`, `timestamp`, `updated_at` — no `change_pct`.
- **Suggestion**: Either use the price-snapshot endpoint (`/internal/v1/price/{iid}`) which returns `price_change_pct`, OR call the same price-snapshot path that S9's quote proxy uses and apply `_map_price_snapshot_to_quote` in `get_watchlist_insights`. The internal quote endpoint is legacy and price-snapshot is the authoritative source.
- **Confidence**: HIGH

---

### Finding F-Q1-03 — BLOCKING: T-D-4-02 (EODHD Adapter Extension) Not Implemented — Snapshot Table Will Remain Empty in Production

- **Severity**: BLOCKING
- **Wave**: D
- **File**: `services/market-ingestion/` (no diff vs parent commit)
- **Issue**: Wave D plan task T-D-4-02 specifies "EODHD adapter in market-ingestion: extract above fields from EODHD financial endpoints." The git diff shows **zero market-ingestion service file changes** vs `40aa6c0`. The `instrument_fundamentals_snapshot` table is populated only by the manual one-time backfill script (`services/market-ingestion/scripts/backfill_fundamentals.py`), which reads existing JSONB data already in the DB. There is no continuous ingestion path: when EODHD fundamentals data updates (daily for most symbols), the snapshot table is **never refreshed**. All 10 snapshot fields currently show `null` in the live database (verified: `SELECT COUNT(*) ... WHERE eps_ttm IS NOT NULL` → 0 rows).
- **Evidence**:
  ```
  git diff 40aa6c0..HEAD -- services/market-ingestion/  →  (empty; no changes)
  curl .../v1/fundamentals/AAPL_ENTITY_ID/snapshot → {eps_ttm: null, beta: null, ..., updated_at: null}
  docker exec postgres psql -d market_data -c "SELECT COUNT(*) FROM instrument_fundamentals_snapshot" → 0
  ```
- **Suggestion**: Either: (a) wire the existing `FundamentalsTask` in `execute_task.py` to UPSERT into `instrument_fundamentals_snapshot` after each successful ingest cycle (computed fields are already extractable from the JSONB sections already stored), OR (b) schedule the backfill script as a daily cron task. Option (a) is architecturally correct; option (b) is a temporary band-aid. Without this, the D-3 Debt & Credit and Cash Flow sections will always show "—" in production.
- **Confidence**: HIGH

---

### Finding F-Q1-04 — CRITICAL: Duplicate "Debt / Equity" Row in FundamentalsTab

- **Severity**: CRITICAL
- **Wave**: D
- **File**: `apps/worldview-web/components/instrument/FundamentalsTab.tsx:464-465` and `565-569`
- **Issue**: The metric "Debt / Equity" is rendered **twice**: once in the "Balance Sheet" section (line 464, uses `fund.debt_to_equity`) and again in the new "Debt & Credit" section (line 566, also uses `fund.debt_to_equity`). This creates a data duplication visible to the user — a Bloomberg-grade finance UI should never repeat the same metric in two sections.
- **Evidence**:
  ```tsx
  // Balance Sheet section (line 464)
  <MetricRow label="Debt / Equity">
    <span className={getMetricClass(fund.debt_to_equity, 1.0, 2.0)}>
      {formatRatio(fund.debt_to_equity)}
    </span>
  </MetricRow>
  
  // Debt & Credit section (line 566)  ← duplicate
  <MetricRow label="Debt / Equity">
    <span className={getMetricClass(fund.debt_to_equity, 1.0, 2.0)}>
      {formatRatio(fund.debt_to_equity)}
    </span>
  </MetricRow>
  ```
- **Suggestion**: Remove the "Debt / Equity" row from either the "Balance Sheet" section (keep D/E in Debt & Credit alongside coverage and net debt) or remove it from Debt & Credit (keep it only in Balance Sheet). The Debt & Credit section should focus on the new snapshot fields (interest coverage, net debt/EBITDA, credit rating) — the pre-existing `debt_to_equity` from the main `Fundamentals` object doesn't belong in the snapshot-backed section.
- **Confidence**: HIGH

---

### Finding F-Q1-05 — CRITICAL: IntelligenceTab Entity Type Filter Chips Use Wrong Type Names; Selecting Any Chip Produces Empty Graph

- **Severity**: CRITICAL
- **Wave**: E
- **File**: `apps/worldview-web/components/instrument/IntelligenceTab.tsx:339`
- **Issue**: `ALL_ENTITY_TYPES` is hardcoded as `["company", "person", "event", "topic"]`. However, the actual entity types in the knowledge graph DB are `"financial_instrument"`, `"industry_group"`, `"sector"`, `"technology_theme"`, `"industry"`. When any entity type chip is selected, `filteredNodes` filters: `entityTypes.includes(node.type)` — since no node has type `"company"`, `"person"`, etc., the graph becomes **completely empty** when any chip is toggled. This is a silent data mismatch that makes the entity type filter appear broken.
- **Evidence**:
  ```
  # DB types:
  docker exec postgres psql -d intelligence_db -c "SELECT entity_type, COUNT(*) FROM canonical_entities GROUP BY entity_type"
  → financial_instrument (40), industry_group (27), sector (11), technology_theme (4), industry (1)
  
  # Graph node types from live API:
  GET /v1/entities/0195daad-.../graph?depth=1 → nodes[0].type = "sector"
  
  # IntelligenceTab hardcodes:
  const ALL_ENTITY_TYPES = ["company", "person", "event", "topic"]  ← none match
  ```
- **Suggestion**: Replace the hardcoded `ALL_ENTITY_TYPES` with the actual types present in the KG: `["financial_instrument", "sector", "industry_group", "technology_theme", "industry"]`. Better: fetch unique node types from the first successful graph query and populate the chips dynamically. Also add a "no results" empty-state message when filters produce zero nodes (currently the graph silently empties with no feedback).
- **Confidence**: HIGH

---

### Finding F-Q1-06 — CRITICAL: `timeWindow` Filter in IntelligenceTab Silently Has No Effect on Graph Data

- **Severity**: CRITICAL
- **Wave**: E
- **File**: `apps/worldview-web/components/instrument/IntelligenceTab.tsx:592`
- **Issue**: The `timeWindow` filter (7d / 30d / 90d / all) is displayed in the filter toolbar and stored in `graphFilters.timeWindow`. However, it is **never passed to the API call**: `getEntityGraph(entityId, graphFilters.depth)` — only `depth` is sent. The time window is not applied client-side either (no time-based filtering of edges or nodes). The filter UI is completely non-functional: selecting "7d" shows identical data to "all".
- **Evidence**:
  ```tsx
  // IntelligenceTab.tsx:591-596
  const { data: graphData } = useQuery({
    queryKey: ["entity-graph", entityId, graphFilters.depth],  // timeWindow NOT in key
    queryFn: () => createGateway(accessToken).getEntityGraph(entityId, graphFilters.depth),
    // graphFilters.timeWindow is NEVER passed
  ```
  Also: the `queryKey` doesn't include `timeWindow`, so changing the time window doesn't even trigger a refetch.
- **Suggestion**: (a) Add `time_window` as a query parameter to `GET /v1/entities/{id}/graph` in the gateway and pass it through to S7, OR (b) filter edges client-side by timestamp if graph edges carry a `timestamp`/`last_seen` field. At minimum, add `graphFilters.timeWindow` to the TanStack query key so a UI change triggers a re-render. As-is, the control is misleading to the user.
- **Confidence**: HIGH

---

### Finding F-Q1-07 — CRITICAL: `sentiment` and `impact_score` Fields Always Null in News API (No Enrichment Pipeline)

- **Severity**: CRITICAL
- **Wave**: E
- **File**: `services/nlp-pipeline/src/nlp_pipeline/` (domain models + DB migration)
- **Issue**: Wave E adds `sentiment` and `impact_score` columns to `document_source_metadata` (migration 0011) and the API correctly returns them. However, **no worker or pipeline actually populates these fields**. The `ArticleRelevanceScoringWorker` scores LLM relevance (`llm_relevance_score`) but does NOT write `sentiment`. The `PriceImpactWorker` writes to `article_impact_windows` but the convenience `impact_score` copy is never written to `document_source_metadata`. Result: all 2,921 articles in the live DB have `sentiment = NULL` and `impact_score = NULL`. The News tab sentiment pills and impact pills will never render.
- **Evidence**:
  ```sql
  SELECT COUNT(*), COUNT(sentiment) FROM document_source_metadata;
  →  2921  |  0
  ```
  ```
  GET /v1/news/top (20 articles):
  With sentiment: 0, With impact_score: 0
  ```
  The NLP pipeline unit tests mock the worker's output but don't assert that sentiment is written.
- **Suggestion**: The `ArticleRelevanceScoringWorker` should be extended to also classify sentiment (the LLM call already processes the article — adding a `sentiment` classification to the same prompt costs negligible extra latency). Alternatively, add a separate `SentimentClassifierWorker`. The `impact_score` convenience column should be written by the `PriceImpactWorker` after computing `article_impact_windows` rows.
- **Confidence**: HIGH

---

### Finding F-Q1-08 — MAJOR: Insights `price` Field Returns Wrong Value (Old Quote Cache vs Current)

- **Severity**: MAJOR
- **Wave**: B
- **File**: `services/api-gateway/src/api_gateway/clients.py:638-639`
- **Issue**: The insights endpoint calls `/api/v1/quotes/{iid}` on market-data (internal schema, `last` field). The NVDA mover shows `price: 199.64` while the S9 quote proxy shows `209.53` for the same instrument. The discrepancy is because the internal quote endpoint may be reading from a different source (raw quotes DB row vs. the price-snapshot computed path). The `last` field in the internal `QuoteResponse` is a raw bid/ask/last from the quote table, not the processed intraday close used by S9.
- **Evidence**:
  ```
  GET /v1/quotes/NVDA (S9 proxy) → {price: 209.53, source: "intraday_1h_close"}
  GET /v1/watchlists/{id}/insights → movers[NVDA].price = 199.64  ← stale
  ```
- **Suggestion**: Use the same price-snapshot endpoint that S9's quote proxy uses (`/internal/v1/price/{iid}`) to ensure consistency between the insights panel and the instrument's quote display. Alternatively, call S9's own `/v1/quotes/{iid}` endpoint (adding the gateway's own base URL) — though that adds a network hop.
- **Confidence**: MEDIUM (data staleness may explain some of the difference, but the field name mismatch with `change_pct` confirms the internal schema is being read differently)

---

### Finding F-Q1-09 — MAJOR: FundamentalsTab Left Column Has Broken Indentation Creating Misleading Source Structure

- **Severity**: MAJOR
- **Wave**: D
- **File**: `apps/worldview-web/components/instrument/FundamentalsTab.tsx:336-641`
- **Issue**: The inner metric grid `<div className="grid grid-cols-2 gap-2 p-3 lg:grid-cols-3">` at line 336 is indented at the same level as its child `<Section>` components rather than being indented one level deeper. The D-3 Charts section (`<div className="space-y-2 p-3">`) at line 650 has inconsistent indentation vs. the grid div. While React renders correctly (div balance is 0, JSX is valid), the misleading indentation makes it appear the D-3 section is a sibling of the left column `div` rather than a child. This will cause confusion during future maintenance and was flagged by the div-depth analysis.
- **Evidence**: Div depth trace shows grid div opens at depth 3 (line 336), closes at depth 2 (line 641); D-3 section opens at depth 3 (line 650), closes at depth 2 (line 669); left column closes at depth 1 (line 680). Structurally correct but indentation doesn't reflect this.
- **Suggestion**: Fix indentation to match the actual nesting: the grid div and D-3 section should both be indented 2 levels inside the left column div. This is cosmetic to React but critical for maintainability.
- **Confidence**: HIGH

---

### Finding F-Q1-10 — MAJOR: OHLCVChart Has 15 `any`-Typed Refs Without Proper Type Guards

- **Severity**: MAJOR
- **Wave**: C
- **File**: `apps/worldview-web/components/instrument/OHLCVChart.tsx:222-264`
- **Issue**: All chart series refs are typed as `useRef<any>(null)` (15 refs total). These refs are used in 10+ `useEffect` hooks to call `.setData()`, `.applyOptions()`, `.setVisible()`, and `.removeSeries()`. The `eslint-disable-next-line @typescript-eslint/no-explicit-any` comments acknowledge the issue but don't mitigate the runtime risk: if lightweight-charts changes its API in a minor version (e.g., `setVisible` renamed to `setVisibility`), the TypeScript compiler will silently accept the call and only a runtime error will surface — at user interaction time, not at build time.
- **Evidence**: Lines 222-264 show 15 consecutive `// eslint-disable-next-line @typescript-eslint/no-explicit-any` blocks for `chartRef`, `seriesRef`, `volumeSeriesRef`, `ma50SeriesRef`, and all 11 indicator series refs.
- **Suggestion**: Import lightweight-charts TypeScript types: `IChartApi`, `ISeriesApi<"Candlestick">`, `ISeriesApi<"Line">`, `ISeriesApi<"Histogram">` from `lightweight-charts` (they are exported). Type the refs properly. This is achievable without breaking the dynamic import pattern by using `import type` at the module level.
- **Confidence**: HIGH

---

### Finding F-Q1-11 — MAJOR: `DrawingCanvas` Does Not Handle Text Annotation Input (Missing Text Prompt UX)

- **Severity**: MAJOR
- **Wave**: C
- **File**: `apps/worldview-web/components/instrument/DrawingCanvas.tsx:198-300` (approx)
- **Issue**: The `TEXT` drawing tool is listed in `TOOL_ORDER` and `POINTS_REQUIRED` says it requires 1 click. The `commitAnnotation` function creates a `TextAnnotation` with `anchor` point and `text` field. However, there is **no UX for the user to input the text content** — the `TextAnnotation.text` field is never populated by the canvas (no prompt/dialog/inline input appears when the user clicks to place a text annotation). The annotation will be committed with an empty `text: ""`.
- **Evidence**: The `DrawingCanvas` component tracks `inProgress.points` and calls `commitAnnotation` when `points.length >= POINTS_REQUIRED["TEXT"] (= 1)`. The `commitAnnotation` function for the `TEXT` case creates `{ ...base, anchor: points[0], text: "" }` with no mechanism to receive text from the user before or after the click.
- **Suggestion**: After the user clicks the anchor point for a TEXT annotation, show an inline `<input type="text">` positioned at the click coordinates (absolute positioned over the SVG). On Enter/blur, commit the annotation with the typed text. On Escape, cancel the drawing. This matches TradingView's text annotation UX.
- **Confidence**: HIGH

---

### Finding F-Q1-12 — MINOR: Wave F Tasks T-F-6-06 (Refresh All), T-F-6-08 (52W bar alignment), T-F-6-09 (LiveQuote dot), T-F-6-10, T-F-6-15, T-F-6-20, T-F-6-21 Not Implemented and Not Explicitly Closed in Plan

- **Severity**: MINOR
- **Wave**: F
- **File**: `docs/plans/0050-dashboard-instruments-polish-plan.md:128-151`
- **Issue**: The Wave F task list contains 21 items. The commit message for Wave F says "19/21 done; 2 explicit thesis-demo skips T-F-6-05/18". However, examining the code and the plan, the following tasks are also not present in the diff and not explicitly closed: T-F-6-06 (Global "Refresh All" button — `RefreshAllButton.test.tsx` exists and passes, and `RefreshAllButton.tsx` appears to exist from git log in PLAN-0049, so this may be pre-existing), T-F-6-08 (52W bar vertical alignment in row 2), T-F-6-09 (LiveQuoteBadge always-visible 3px dot), T-F-6-15 (OHLCV placeholder flicker), T-F-6-20 (same-tab vs new-tab preference for news links), T-F-6-21 (share/copy-link button). The TRACKING.md only marks "19/21 done" without identifying which 2 were skipped beyond T-F-6-05/T-F-6-18.
- **Evidence**: `git diff 40aa6c0..HEAD -- apps/worldview-web/components/instrument/52WeekRangeBar.tsx` → no changes. `git diff ... -- components/instrument/LiveQuoteBadge.tsx` → no LiveQuoteBadge changes visible.
- **Suggestion**: Update TRACKING.md and the plan to explicitly mark each unimplemented task as "deferred" with a forward reference to the next plan that will address them.
- **Confidence**: MEDIUM

---

### Finding F-Q1-13 — MINOR: Watchlist Insights Movers Not Sorted by `|change_pct|` — Widget Gainers/Losers Split Is Undefined

- **Severity**: MINOR
- **Wave**: B
- **File**: `services/api-gateway/src/api_gateway/clients.py:760-795`
- **Issue**: The `movers` array in the insights response is returned in watchlist-member order (whatever order `GET /api/v1/watchlists/{id}/members` returns), not sorted by absolute `change_pct`. The frontend `WatchlistMoversWidget` splits movers into gainers/losers by `change_pct > 0` / `< 0` but the top-N displayed are not guaranteed to be the best gainers and worst losers — they're just the first N members.
- **Evidence**: Live response shows 5 members in insertion order (NVDA, DIS, and others) with `change_pct: null` for all (due to F-Q1-02). Even if change_pct were populated, sorting should happen server-side.
- **Suggestion**: After building `movers_out`, sort by `change_pct` descending (gainers) and ascending (losers), return separate `top_gainers` and `top_losers` arrays rather than a single `movers` list. Alternatively, sort `movers_out` by `abs(change_pct) DESC` so the most moved instruments appear first.
- **Confidence**: HIGH (would manifest as soon as F-Q1-02 is fixed)

---

### Finding F-Q1-14 — MINOR: `pnpm audit` Reports 2 Moderate PostCSS Vulnerabilities (GHSA-qx2v-qp2m-jg93)

- **Severity**: MINOR
- **Wave**: F (polish sweep)
- **File**: `apps/worldview-web/package.json`
- **Issue**: `pnpm audit --audit-level=low` reports 2 moderate vulnerabilities in `postcss < 8.5.10` (XSS via unescaped `</style>` in CSS stringify output). Both paths: `apps__worldview-web>postcss` and `apps__worldview-web>next>postcss`. These are pre-existing (not introduced by PLAN-0050) but the Wave F polish sweep should have updated them.
- **Evidence**: `pnpm audit` output shows `2 vulnerabilities found — Severity: 2 moderate`.
- **Suggestion**: Run `pnpm update postcss` to upgrade to `>=8.5.10`. If Next.js pins postcss internally, open an upstream issue or apply an override in `package.json`: `"overrides": { "postcss": "^8.5.10" }`. Update `pnpm-lock.yaml` and commit.
- **Confidence**: HIGH

---

### Finding F-Q1-15 — MINOR: Misleading Indentation in FundamentalsTab.tsx Left-Column D-3 Section

- **Severity**: MINOR (see also F-Q1-09 above — related)
- **Wave**: D
- **File**: `apps/worldview-web/components/instrument/FundamentalsTab.tsx:643-680`
- **Issue**: The comment `{/* ── D-3 Charts & Tables ───...*/}` at line 643 is indented at 8 spaces (same level as the closing `</div>` of the metric grid at line 641), making it look like D-3 is outside the left column. The actual left column closing `</div>` is at line 680. The source structure is functionally correct but visually confusing during code review.
- **Suggestion**: Re-indent lines 643-679 to 10 spaces (matching the depth of the grid div children) to reflect they are still inside the left-column `overflow-y-auto` div.
- **Confidence**: HIGH

---

### Finding F-Q1-16 — NIT: `FundamentalsTab` Data Quality Footer Renders `Updated undefined` When `fund.updated_at` Is Null

- **Severity**: NIT
- **Wave**: D
- **File**: `apps/worldview-web/components/instrument/FundamentalsTab.tsx:677-678`
- **Issue**: The footer line `Data sourced from S3 fundamentals pipeline · Updated {formatRelativeTime(fund.updated_at)}` will render "Updated undefined" or "Updated NaN" if `fund.updated_at` is null or undefined — which is common for instruments with partial fundamentals coverage.
- **Evidence**: The `Fundamentals` type has `updated_at: string | null`. `formatRelativeTime(null)` may not return "—" gracefully.
- **Suggestion**: Add a null guard: `Updated {fund.updated_at ? formatRelativeTime(fund.updated_at) : "—"}`.
- **Confidence**: HIGH

---

### Finding F-Q1-17 — NIT: `DrawingCanvas` `id` Generation Uses `Date.now() + Math.random()` (Non-UUIDv7)

- **Severity**: NIT
- **Wave**: C
- **File**: `apps/worldview-web/lib/instrument-context.ts:199` (approx, in `commitAnnotation`)
- **Issue**: The annotation `id` is generated as `` `ann-${Date.now()}-${Math.random().toString(36).slice(2, 8)}` ``. The repo rule (Rule 6) requires UUIDv7 for all IDs via `common.ids.new_uuid7()`. While this is a frontend-only ID (never sent to the backend), using a non-standard ID scheme is inconsistent and the `new_uuid7` equivalent for the browser is available from the `common` library or via `crypto.randomUUID()`.
- **Suggestion**: Replace with `crypto.randomUUID()` (Web Cryptography API, available in all modern browsers) or a `nanoid()` call for a compact URL-safe ID. The current approach has low collision probability but is non-standard.
- **Confidence**: MEDIUM

---

## Container Validation Log

| Container | Action | Result |
|-----------|--------|--------|
| worldview-api-gateway-1 | Rebuilt + restarted | Healthy; `/v1/watchlists/{id}/insights` now returns 200 |
| worldview-market-data-1 | Rebuilt + alembic upgrade head | Migration 009→011 applied; `/v1/fundamentals/{id}/snapshot` returns 200 with all-null fields |
| worldview-nlp-pipeline-1 | Rebuilt + alembic upgrade head | Migration 0010→0011 applied; `/v1/news/top` returns 200 (sentiment=null, impact=null for all articles) |

### Endpoint Hit Log

| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /v1/watchlists/{id}/insights` | 200 | Before rebuild: 404. After: returns correct shape but `change_pct: null` for all movers (F-Q1-02) |
| `GET /v1/fundamentals/{id}/snapshot` | 200 | Before rebuild: 500. After: returns shape with all 10 fields null (no backfill run; F-Q1-03) |
| `GET /v1/news/top` | 200 | Before rebuild: 500. After: 20 articles, all with `sentiment: null, impact_score: null` (F-Q1-07) |
| `GET /v1/entities/{id}/articles` | 404 | Seed entity IDs don't match KG entity IDs (different UUID space) |
| `GET /v1/entities/{id}/graph` | 200 | Returns 1 node of type "sector" for test entity |
| `GET /v1/search/instruments` | 200 | Works correctly |
| `GET /v1/quotes/{id}` | 200 | Returns `{price: 209.53, change_pct: 0.0}` correctly via S9 proxy |

---

## Enhancement Opportunities

1. **E-01: Indicator parameter editing UI** — The chart toolbar supports 7 indicators with hardcoded periods (RSI=14, MACD=12/26/9, etc.). TradingView allows analysts to click an indicator's label on the chart to open a parameter editor (RSI period, MACD fast/slow/signal). This would make the toolbar Bloomberg-grade. Tracked as future PLAN-0053 work.

2. **E-02: Drawing tool keyboard shortcuts** — TradingView and Bloomberg both support keyboard shortcuts for arming drawing tools (T = trend line, H = horizontal level, etc.). The current implementation is click-only. Add `useEffect` hotkey listeners bound to the tool IDs.

3. **E-03: Graph node drill-through on click** — The SVG `EntityGraphPanel` in the Overview sidebar has `router.push()` on node click (navigates to instrument). The full `EntityGraph.tsx` (Sigma.js, Intelligence tab) should also support click-to-navigate — currently it likely doesn't (not verified in source, but the sigma.js graph has no `onClick` for node navigation in the diff).

4. **E-04: Sentiment trend over time** — The News tab shows individual article sentiment pills but no aggregate sentiment trend. A 7-day sentiment histogram (count of POS/NEG articles per day) above the article list would let analysts spot market-sentiment shifts at a glance. This is a 2-3 hour addition to NewsTab.

5. **E-05: Confidence threshold slider feedback** — When the user sets confidence threshold to >0.5, the graph may become very sparse. There's no feedback about how many edges were filtered. Adding a "Showing N of M relations above threshold X" count would prevent confusion.

6. **E-06: DataTimestamp footer on InstrumentKeyMetrics** — T-D-4-05 closed F-I-009 (DataTimestamp footer in metrics panel), but the timestamp is only shown in `FundamentalsTab`. The `InstrumentKeyMetrics` sidebar (Overview tab) also shows fundamental data but has no "as of" footer. Closing the loop here requires adding DataTimestamp to InstrumentKeyMetrics too.

7. **E-07: Empty annotation count in DrawingPalette** — The DrawingPalette code comment at line 170-173 mentions showing an annotation count at the bottom to confirm persistence, but no count is rendered (the comment exists but the JSX is empty). Implement: render `{annotations.length > 0 && <span className="...">{annotations.length}</span>}` at the palette bottom.

8. **E-08: News source filter "All Sources" dynamic count** — The source filter dropdown in NewsTab shows static source names. It should show article counts per source: "Reuters (4)", "Bloomberg (3)", etc., to help analysts quickly select the most relevant source. This is client-side (data is already fetched) and requires no API changes.

---

## Recommendation

**DO NOT SHIP** the current state of PLAN-0050 as complete.

Three BLOCKING issues require fixes before the QA loop closes:

1. **F-Q1-01** (container rebuild hygiene) — Document in the ship checklist; no code fix needed.
2. **F-Q1-02** (`change_pct` always null) — Fix `get_watchlist_insights` to call the price-snapshot endpoint instead of the internal quote endpoint, or remap the `QuoteResponse` fields correctly.
3. **F-Q1-03** (snapshot table always empty) — Wire the EODHD ingestion task to UPSERT into `instrument_fundamentals_snapshot` on each ingest cycle, or document the manual backfill step as explicitly required for the thesis demo.

Four CRITICAL issues require fixes:

4. **F-Q1-04** (duplicate Debt/Equity row) — Remove one instance.
5. **F-Q1-05** (entity type filter produces empty graph) — Fix `ALL_ENTITY_TYPES` to match actual KG types.
6. **F-Q1-06** (`timeWindow` filter does nothing) — Pass `time_window` to API or add client-side temporal filtering of edges, and add it to the query key.
7. **F-Q1-07** (sentiment/impact_score never populated) — Extend the `ArticleRelevanceScoringWorker` to write sentiment, and the `PriceImpactWorker` to write the convenience `impact_score` column.

After fixing these 7 BLOCKING+CRITICAL items, re-run QA iteration 2.
