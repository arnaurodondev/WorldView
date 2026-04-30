# Worldview Frontend — Master Remediation Report
## Deep Investigation Across 5 Specialist Domains

**Date:** 2026-04-30
**Skill:** `/plan` (deep-investigation mode)
**Sources:** 5 parallel principal-architect investigations dispatched against the original 2026-04-29 institutional UI audit
**Stakeholder:** BlackRock-grade institutional credibility
**Repo state:** `feat/content-ingestion-wave-a1` (HEAD = `b4e513b2`)

---

## How To Read This Document

This master report consolidates **five deep investigations** dispatched in parallel — one per audit section. Each specialist verified the original audit's findings against current source, identified root causes, proposed institutional-grade long-term solutions, and surfaced issues the original audit missed. The total surface area: **~50,000 words** of investigation reduced into the prioritized fix list below.

**Document structure:**
1. **Executive Synthesis** — what the deep dive changes vs. the original audit
2. **Cross-Section Signals** — issues that span multiple specialist lenses (highest confidence)
3. **Section A — Codebase Architecture** (Principal Frontend Architect)
4. **Section B — Data Visualization** (Principal Financial Visualization Architect)
5. **Section C — Components & Interactions** (Principal Product Designer)
6. **Section D — Visual Design System** (Principal Visual Designer)
7. **Section E — Layout & IA / Search & Navigation** (Principal UX Architect)
8. **Newly Discovered Issues** (76 issues the original audit missed, by section)
9. **Master Roadmap** — sequenced waves, dependencies, parallelizable work
10. **Compounding Updates** — what the platform's living docs must absorb

**Severity legend:** CRITICAL (disqualifying for BlackRock demo) · MAJOR (institutional-credibility gap) · MINOR (polish) · NIT (cosmetic).
**Confidence legend:** HIGH (multi-agent / multi-source confirmation) · MEDIUM (single-agent with code evidence) · LOW (heuristic only).

---

# 1. Executive Synthesis

## 1.1 What the deep dive changed vs. the original audit

The original 2026-04-29 audit assigned **6.0/10 composite maturity** with 220 findings. The deep investigation changes that picture in five material ways:

1. **God-files have grown 10–15% in 5 days.** `lib/gateway.ts` 2,415→**2,657 LOC**, `types/api.ts` 1,214→**1,401 LOC**, `app/(app)/portfolio/page.tsx` 1,704→**1,739 LOC**, `app/(app)/chat/page.tsx` 1,242→**1,293 LOC**. **Drift is active**, not a static state. The architecture score should be **4.0, not 4.5**.
2. **Silent CRITICAL: `:root` and `.dark` blocks diverged on `--muted-foreground`.** A WCAG fix was applied to `:root` (55%) but not to `.dark` (46%). Since `.dark` is the active class, **the WCAG fix never shipped**. Every `text-muted-foreground` site in production is sub-AA right now. Audit-visual missed this entirely.
3. **No real-time, no observability, no brand identity.** Three foundational gaps the original audit understated: (a) no WebSocket quote stream — every cell polls, every tile freezes for 15s windows; (b) no Sentry/error monitoring — only `console.error`; (c) `public/` directory is empty — no favicon, no wordmark, no OG image, no apple-touch-icon. For BlackRock evaluation each is a category error.
4. **Workflow grammar was never defined.** The dead StatusBar shortcuts are not a "wire up missing handlers" task — they reflect that **navigation grammar (symbol+function+action) is undefined**. Promised-but-broken hotkeys actively destroy trust within the first 90 seconds of a demo.
5. **76 new issues** beyond the original 220, including: only **one** dynamic import in 250 components; **zero** `React.memo`/`useTransition`/`useDeferredValue`; UtcClock guaranteed hydration mismatch; **387** (not 112) gateway recreations; no idle-lock; no session-expired flow; no force-update flow; no print stylesheet; no internationalization; hardcoded USD.

## 1.2 Composite maturity (revised)

| Dimension | Original audit | Deep-dive revised | Notes |
|-----------|:-------------:|:-----------------:|-------|
| Layout & Information Architecture | 6.5 | **5.5** | Workflow grammar undefined; IA fragmented |
| Visual Design System | 7.2 | **6.5** | Silent WCAG drift; no token pipeline; no brand |
| Components & Interactions | 6.4 | **5.8** | shadcn defaults + parallel ad-hoc systems |
| Data Visualization | 6.2 | **6.0** | Polling-only; 4 formatters; 3 chart libs |
| Codebase Architecture | 4.5 | **4.0** | God-files growing; no codegen; no Sentry |
| Search & Navigation | 5.0 | **4.5** | Promises not honored; no command superset |
| **Composite** | **6.0 / 10** | **5.4 / 10** | "Polished consumer fintech, drifting." |

## 1.3 The single most damaging signal

**At market open during a demo, the screen does not visibly move.** Nothing flashes, nothing ticks, nothing increments. To a Bloomberg-trained eye this reads "frozen / broken" within 30 seconds — independently of how good the chrome looks. Closing this single gap (WebSocket quote stream + per-cell tick flash) is the highest-leverage action available.

## 1.4 The single highest-trust direction

**Workflow grammar is the deeper credibility lever than visuals.** Every benchmark (Bloomberg, Aladdin, Linear, Raycast, Superhuman) earns its institutional reputation through *keyboard-driven, command-driven, symbol-first* interaction grammar. Worldview's chrome is competitive; the absence of a working hotkey layer + command palette superset + persistent symbol input prevents the platform from feeling like a terminal. **3 weeks of focused workflow-grammar work** moves perception more than any other single investment.

---

# 2. Cross-Section Signals — Issues Flagged by Multiple Specialists

These are the highest-trust findings — independently surfaced by ≥2 specialist deep dives. All HIGH confidence.

| Signal | Sections flagging | Severity | Resolution wave |
|--------|-------------------|:--------:|:---------------:|
| **No WebSocket quote stream — entire app polls** | DataViz, Components | CRITICAL | W1 |
| **`#26A69A` is TradingView teal, not Bloomberg green** | Visual, DataViz | CRITICAL | W0 |
| **Heat scale uses retired Bloomberg Dark palette** | Visual, DataViz | CRITICAL | W0 |
| **Silent `:root`/`.dark` drift on `--muted-foreground` (WCAG)** | Visual (NEW) | CRITICAL | W0 (5min) |
| **Hand-typed `types/api.ts` drift risk (1,401 LOC, no codegen)** | Codebase, Components | CRITICAL | W1 |
| **Three different B/M/T compaction implementations** | DataViz, Components, Codebase | MAJOR | W1 |
| **God-pages `portfolio` (1,739) / `chat` (1,293) — actively growing** | Codebase, Layout | CRITICAL | W2 |
| **shadcn defaults (h-9, p-6, text-sm) shadowed by ad-hoc h-6/text-[11px]** | Visual, Components | MAJOR | W1 |
| **Three chart libraries (lightweight-charts + recharts + sigma)** | Codebase, DataViz | MAJOR | W3 |
| **Three dead npm dependencies** | Codebase, Components | MAJOR | W0 |
| **No URL state for filters/tabs/periods** | Codebase, Layout | CRITICAL | W1 |
| **TanStack Query keys scattered (169 declarations, no factory)** | Codebase, Components | MAJOR | W1 |
| **No `ContextMenu` primitive — right-click is a no-op everywhere** | Components, Layout | CRITICAL | W3 |
| **Dead StatusBar chord shortcuts (advertised, not wired)** | Layout, Components | CRITICAL | W1 |
| **No global symbol input (function-first vs symbol-first)** | Layout (NEW) | CRITICAL | W1 |
| **No command palette superset (`>action`/`?help`/`/saved`)** | Layout, Components | CRITICAL | W1 |
| **Hardcoded USD; multi-currency unsupported despite API returning currency** | DataViz (NEW), Codebase | CRITICAL | W1 |

**Read this table as the spine.** Every wave in §9 maps back to closing one or more of these signals.

---

# 3. Section A — Codebase Architecture (Principal Frontend Architect)

**Source report:** `Deep codebase investigation` deep agent, 2026-04-30
**Composite verdict:** Architecture score 4.0/10. God-files actively growing; no contract layer; no observability; React 19 hooks unused.

## 3.1 Verified findings (audit's F-CODE-001..010)

All 10 confirmed; **most worse than reported**:

| ID | Status | Evidence (file:LOC) |
|----|:------:|---------------------|
| F-CODE-001 | CRITICAL — **growing** | `lib/gateway.ts` 2,415→**2,657** (+10% in 5 days) |
| F-CODE-002 | CRITICAL — **growing** | `types/api.ts` 1,214→**1,401** (+15%) |
| F-CODE-003 | CRITICAL — **growing** | `app/(app)/portfolio/page.tsx` 1,704→**1,739** |
| F-CODE-004 | CRITICAL — **growing** | `app/(app)/chat/page.tsx` 1,242→**1,293** |
| F-CODE-005 | CRITICAL | URL state present in 5 sites (auth callback, alerts deep-link, chat) but missing in screener/portfolio/workspace/equity-period |
| F-CODE-006 | CRITICAL | 169 `queryKey:` declarations, no central factory |
| F-CODE-007 | CRITICAL | Confirmed: `/portfolio` waterfall is 5-deep |
| F-CODE-008 | CRITICAL | `AlertStreamContext.tsx:160-163` direct WS to S10:8010, token in URL |
| F-CODE-009 | CRITICAL | `lightweight-charts` + `recharts` + `sigma` + `graphology` all in package.json |
| F-CODE-010 | MAJOR | `react-grid-layout`, `react-resizable`, `@radix-ui/react-toast` all present + zero imports |

## 3.2 Strategic fix matrix

| ID | Long-term solution | Best-in-class ref | Effort |
|----|--------------------|-------------------|:------:|
| F-CODE-001 | Split into `lib/api/{auth,instruments,portfolios,...}.ts` domain modules driven by `openapi-fetch` (~6KB gz). CI rule: any file in `lib/api/` >350 LOC fails build. | Vercel Commerce (per-domain modules); Stripe (`ts-rest`) | 1w |
| F-CODE-002 | Adopt `openapi-typescript`. Frontend regenerates `types/generated/api.ts` from S9 `/openapi.json` in CI; drift-fail gate. | GitHub octokit/openapi-types | 3d |
| F-CODE-003 | `features/portfolio/{components,hooks,queries,lib}/` decomposition. Pure functions to `lib/kpi.ts` + tests. Page becomes <100 LOC orchestrator. | Linear; Vercel Dashboard | 1w |
| F-CODE-004 | Extract `useChatStream(threadId)` hook (or adopt `@vercel/ai-sdk`'s `useChat`). Split into `<ThreadSidebar>`, `<ConversationView>`, `<MessageComposer>`. | Vercel AI SDK | 4d |
| F-CODE-005 | Adopt `nuqs@^2`. URL-state schema documented in `docs/ui/URL_STATE.md`. | Vercel Toolbar; Tremor | 3d |
| F-CODE-006 | Hierarchical key factory `lib/query/keys.ts`. CI rule bans inline `queryKey: ["string"]`. | TanStack Query official docs (Dorfmeister); Cal.com | 2d |
| F-CODE-007 | S9 page-bundle endpoints (`/v1/portfolios/{id}/page-bundle`) compose 5–12 internal calls server-side via `asyncio.gather`. Or move "above-the-fold" data to RSC + `<Suspense>` for sub-data. | Stripe Dashboard BFF; Linear `?include=` | 5d (BE+FE) |
| F-CODE-008 | S9 WebSocket proxy route (`/v1/alerts/stream`) with JWT in `Sec-WebSocket-Protocol` subprotocol header. Drop `NEXT_PUBLIC_WS_BASE_URL`. CSP `connect-src 'self'`. | Linear gateway; Cloudflare Workers | 3d |
| F-CODE-009 | Drop `recharts`. Migrate `EquityCurveChart`, `RevenueTrendSparklines`, `EarningsHistoryChart` to `lightweight-charts` + raw SVG sparklines. | TradingView own product | 3d |
| F-CODE-010 | `pnpm remove`; mount `sonner` `<Toaster>`; add `depcheck`+`knip` to CI. | Vercel; Sentry monorepo | 0.5d |

## 3.3 Cross-cutting architectural recommendations

- **Type-safe API client:** `openapi-typescript` + `openapi-fetch` (NOT tRPC — Python backend). Generated `types/generated/api.ts` becomes the contract.
- **Monorepo:** keep `pnpm workspaces`; add `turborepo` for cached builds + parallel tests (incremental adoption, NOT nx).
- **Build:** enable `experimental.reactCompiler: true` (auto-memoization); `optimizePackageImports: ["lucide-react", "@radix-ui/react-icons"]`; `compiler.removeConsole` in production.
- **Testing pyramid:** Vitest (existing 50 specs → expand to component + hook level), Playwright (existing 15 → +1 per critical journey), MSW for query integration tests, `axe-core/playwright` for a11y, Lighthouse CI per route, Storybook 8 + Chromatic for visual regression.
- **Error monitoring:** Sentry + `@sentry/nextjs` (~50KB gz lazy-loaded). Tag with `tenant_id`, `user_id`, `route`, `panel_id`. Replace all `console.error` with `Sentry.captureException`.
- **Observability:** Web Vitals → Sentry Performance; custom `performance.mark()` for institutional-critical timings.
- **CI/CD gates:** lint, typecheck, vitest, Playwright smoke, bundlewatch (>10% regression fails), Lighthouse CI (LCP < 2.5s), `depcheck`+`knip`, OpenAPI drift, `axe-core`, Chromatic.

## 3.4 Codebase issues newly discovered (see §8.1 for full detail)

- F-CODE-NEW-001 `tsconfig.json` missing `noUncheckedIndexedAccess`, `noImplicitOverride`, `exactOptionalPropertyTypes`, `verbatimModuleSyntax`
- F-CODE-NEW-002 **Only ONE dynamic import** in 250 .tsx files (audit overclaimed)
- F-CODE-NEW-003 **Zero** `React.memo`/`useTransition`/`useDeferredValue`/`use()` across the entire codebase
- F-CODE-NEW-004 `UtcClock` lazy-initializer guarantees hydration mismatch
- F-CODE-NEW-005 **387** (not 112) `createGateway` callsites
- F-CODE-NEW-006 67 raw `setInterval`/`setTimeout` — stale-closure risk
- F-CODE-NEW-007 77 (not 53) direct `localStorage.*` callsites
- F-CODE-NEW-008 Only 3 `<Suspense>` boundaries vs 40 ErrorBoundary — unbalanced
- F-CODE-NEW-009 21 `as any` / `: any` + `no-explicit-any` set to `warn` not `error`
- F-CODE-NEW-010 **No Sentry/error monitoring** (CRITICAL — entirely missed by audit)
- F-CODE-NEW-011 Permanent `'unsafe-inline'` in script-src AND style-src CSP
- F-CODE-NEW-012 250 .tsx files, 163 with `"use client"` (65%) — Server Components underused
- F-CODE-NEW-013 No internationalization (BlackRock APAC blocker)
- F-CODE-NEW-014 Turbopack/SWC config not tuned

## 3.5 Codebase wave summary

10 engineer-weeks for 2-engineer team, 6 waves. **Wave 0 (1w)** = quick wins (deps, sonner, ESLint, Sentry, hydration fixes). **Wave 1 (2w)** = contract spine (codegen, nuqs, query-key factory, storage). **Wave 2 (2w)** = decomposition (gateway, portfolio, chat). **Wave 3 (1w)** = perf (drop recharts, dynamic imports, React.memo, "use client" audit). **Wave 4 (1w)** = page bundles + WS proxy (BE+FE). **Wave 5 (2w)** = hardening (`noUncheckedIndexedAccess`, nonce CSP, Suspense, CI gates).

---

# 4. Section B — Data Visualization (Principal Financial Visualization Architect)

**Composite verdict:** 6.2/10. Strong primitives (OHLCV chart with 7 indicators, HeatCell 7-step scale, sigma WebGL graph) undermined by three structural fault lines: no tick stream, four parallel formatters, three chart engines.

## 4.1 Verified findings — F-DATAVIZ-001..024

All confirmed. Notable specifics from deep dive:

- **F-DATAVIZ-001 (No tick stream).** `AlertStreamContext.tsx:95-160` proves the WS pattern works — but no `useQuoteStream`. Audit's `getWsToken` (`lib/gateway.ts:292`) is consumed only by alerts. **Backend gap:** S9 has no `/v1/quotes/stream`; S2 (market-data) ingests Alpaca WS but doesn't republish to a Kafka topic the gateway can fan out from.
- **F-DATAVIZ-004 (Compact-number formatters).** Actually **FOUR** implementations, not three: `lib/utils.ts:formatVolume`, `lib/utils.ts:formatMarketCap`, `screener/ScreenerTable.tsx:formatCap` (line 69), `instrument/FundamentalSparkline.tsx:formatYAxisLabel` (line 101 — uses `toPrecision(3)`, fundamentally different rounding semantics), plus `dashboard/TopBets.tsx:formatVolume` (line 138) — duplicate name, different code.
- **F-DATAVIZ-010 (Multi-pane stacking).** `lightweight-charts@4.2.3` has no native pane support. **`lightweight-charts@5.0.0` (Nov 2024) added `pane:` parameter** but is a breaking API change (factory pattern: `chart.addCandlestickSeries(...)` → `chart.addSeries(CandlestickSeries, ...)`).
- **F-DATAVIZ-011 (Heatmap not squarified).** `MarketHeatmap.tsx:65-95` is `grid-cols-3 sm:grid-cols-4` — **every tile equal size, no proportional sizing whatsoever**. `SectorHeatmapWidget.tsx` uses `flex-basis: |change_pct|%` — also not squarified (Bruls/Huijsen/van Wijk 2000).

## 4.2 Real-Time Architecture (full design)

```
Alpaca WS → S2 quote-ingester
            └→ [Kafka quotes.tick.v1] → S9 fanout
                                        ├→ Valkey "last-tick" hash (REST fallback)
                                        └→ [WS /v1/quotes/stream] → Frontend
                                                                    ├→ TanStack Query setQueryData
                                                                    └→ FlashBus.emit(id, dir)
                                                                       └→ useTickFlash → bg-positive/30 450ms
```

**Avro schema `quotes.tick.v1`:** `{instrument_id: string, last: double, bid: double, ask: double, bid_size: int, ask_size: int, ts: timestamp-millis, exchange: string}`.

**WS protocol:** client→`{"action":"subscribe","ids":["AAPL","MSFT"]}`; server→`{"id":"AAPL","last":192.41,"chg":1.24,"chg_pct":0.0065,"ts":...}`. Heartbeat 15s; client times out after 30s.

**Frontend hooks:**
- `lib/realtime/quote-stream-provider.tsx` — single connection multiplexed via ref-counted subscriptions.
- `hooks/useQuoteStream(ids)` — subscribe/unsubscribe lifecycle.
- `hooks/useTickFlash(key, value)` — returns `"up"|"down"|null` for 450ms post-change. **Respects `prefers-reduced-motion`** (replaces bg-flash with 1px right-edge color bar).
- **Backpressure:** rAF-batch when more than 40 emits/s. **Visibility:** stops on `document.visibilityState !== "visible"`.

**Cells to convert (priority order):** `IndexTicker` (top bar — highest visibility) → `LiveQuoteBadge` → `WatchlistPanel` rows → `ScreenerTable` price/change → `PortfolioSummary` MTM values → `TopMovers`/`HoldingsMoversWidget`/`PreMarketMoversWidget` → `WorkspaceChartWidget` last-bar (special: append via `series.update`).

## 4.3 Multi-Pane Chart decision

| Option | Bundle delta | Migration | Verdict |
|--------|:------------:|:---------:|---------|
| `lightweight-charts@4` + manual `scaleMargins` (current) | 0 KB | 0 d | NOT VIABLE for >2 oscillators |
| **`lightweight-charts@5` (native panes)** | 0 KB | 2 d (rewrite ~14 series creation calls) | **RECOMMENDED** |
| Apache ECharts | +160 KB gz | 5+ d | Overkill |
| Highcharts Stock | +180 KB gz + commercial license | 5+ d | License cost |
| TradingView Charting Library | proprietary | 10+ d | Vendor lock-in |

**Adopted: lightweight-charts v5.** Layout: main pane 60% (price + MA + BB + VWAP), Pane 1 ~80px (RSI), Pane 2 ~80px (MACD), Pane 3 ~50px (Volume).

## 4.4 Squarified Treemap implementation

Full Bruls/Huijsen/van Wijk algorithm provided in deep-dive source report — `lib/treemap.ts` exports `squarify(nodes, bounds): TreemapRect[]`. ~80 LOC. Replaces both `MarketHeatmap.tsx` and `SectorHeatmapWidget.tsx`. Cell sizing proportional to **market cap** (macro picture); color from `heatCellColor(change_pct)` (after F-VISUAL-003 fix derives it from CSS variables).

## 4.5 Number-Formatting Module — `lib/format.ts` (definitive)

Replaces `lib/utils.ts` formatters + deletes 4 duplicates. Key invariants:
- **Sign always before glyph:** `+$100.00`, `-5.00%`. Never `$+100`.
- **Locale `en-US` only** (no bare `toLocaleString`).
- **All times UTC** with hardcoded month names.
- `null|undefined|NaN` renders as em-dash.
- **Currency-aware:** `formatCompactCurrency(v, {currency})` reads from `useUserContext().defaultCurrency` (sourced from S1 user profile). Mixed-currency portfolios show converted value with currency-of-record tooltip. **FX rates from new S2 endpoint `/v1/fx/rates`.**
- **FX-friendly:** `formatPrice(v)` adapts decimals — `>=1000: 2dp`, `>=1: 2dp` (or `8dp` for BTC/ETH), `>=0.01: 4dp`, `<0.01: 6dp`.
- **`formatBasisPoints(v)`** added: `+23 bps` for fixed-income.
- **`formatShares(v)`** drops `x` suffix (which is for ratios only); always uses `" sh"` suffix.

## 4.6 Color-Encoding Audit — manual color-blind simulation

Manual Coblis-algorithm simulation confirms: current `#26A69A` positive (luminance 140) vs `#EF5350` negative (luminance 140) **collapse to indistinguishable greys for deuteranope users**. Proposed `#00D26A` (L=192) vs `#FF3B5C` (L=96) yields delta-luminance 96 — clearly distinguishable. **Mandatory fix:** Add shape encoding (triangle-up/down) to every diverging color use via global `<DirectionGlyph value={x} />` component.

## 4.7 Sparkline Standardization

Single component `components/ui/Sparkline.tsx` (move + rename current `screener/MiniChart.tsx`). Three sizes: 60x16 (cell), 100x24 (card), 40x12 (chip). Pure SVG. Performance budget: 200 sparklines per screen, sub-16ms render. Memo invariant: identical `values` array reference yields no re-render. **Apply to:** `WatchlistPanel`, `WatchlistMoversWidget`, `TopMovers`, `HoldingsMoversWidget`, `PreMarketMoversWidget`, `PeerComparisonPanel`, `PortfolioSummary` top holdings.

## 4.8 Knowledge Graph

`EntityGraph.tsx:168-260` runs ForceAtlas2 once. Add: `graphology-layout-noverlap`, `graphology-layout-circular`, `@sigma/edge-curve`, `@sigma/node-image`. Toolbar: Companies/People/Events/Topics filter pills, edge-strength slider (0.30 default), search input, layout switcher (Force/Radial/Grid). Drill-down: single-click focus + 1-hop highlight, double-click navigate, right-click context, drag-pin override.

## 4.9 Data Viz issues newly discovered (23 new — see §8.2 for full detail)

Highlights:
- **NEW-001** Hardcoded USD; multi-currency unsupported despite API returning currency
- **NEW-009** No pre-market/after-hours session shading on charts
- **NEW-012** Options chain visualization absent (chain matrix, greeks heatmap, IV surface, GEX)
- **NEW-013** Order book / market depth ladder absent
- **NEW-014** Risk dashboard charts absent (VaR fan, rolling beta, factor radar)
- **NEW-015** Brinson-Fachler attribution absent
- **NEW-016** Underwater drawdown plot absent
- **NEW-017** Rolling correlation matrix absent
- **NEW-018** Sector rotation quadrant (RRG) absent
- **NEW-019** News sentiment overlay on price absent (S6 emits `composite_score` but unused)
- **NEW-021** Indicator parameters hardcoded (RSI=14, MACD=12,26,9, BB=20,2 — no settings popover)
- **NEW-023** No compliance watermark on charts (Aladdin signature)

## 4.10 Data Viz wave summary

**~28 engineer-days** in 4 waves. **DV-A (8d)** = credibility floor: tick stream + `lib/format.ts` + chart HUD + log scale + ResizeObserver rAF. **DV-B (6d)** = visual coherence: drop recharts, sparkline rollout, unified heatmap, drop pill backgrounds. **DV-C (8d)** = power features: lightweight-charts v5 multi-pane, squarified treemap, graph filters, compare overlay, annotations. **DV-D (6d)** = institutional polish: range selector, brush, underwater plot, rolling beta, Brinson, annotation cloud sync, print + watermark.

---

# 5. Section C — Components & Interactions (Principal Product Designer)

**Composite verdict:** 6.4/10. Six audit-CRITICAL findings all confirmed; 30+ additional component-level findings discovered. The collapse-into-one-investment thesis: **every duplicate (3 chart libs, 4 watchlist surfaces, 7 tables with their own headers, 5 inline form-state implementations) is a rederivation cost paid because the primitive did not exist.**

## 5.1 Verified findings — F-COMP-001..006 deepened

- **F-COMP-001 (Tick flash).** Two-layer architecture mandated: `FlashBus` (pub/sub keyed by `instrument_id:field`) + `useTickFlash(key, value)` hook. Bus is **separate** from React Query cache so a single tick multicasts to 6+ cells without each running its own diff. Bloomberg BLP terminal's "tick service" pattern.
- **F-COMP-002 (Context menu).** Six-category action taxonomy: Navigate / Watchlist / Alert / Trade / Copy/Export / View. Single Bloomberg-mnemonic letter hotkeys inside the menu (`D`=DES, `G`=GP, `N`=CN, `A`=alert, `W`=watchlist) match the global instrument-page mnemonics.
- **F-COMP-003 (Column controls).** `ScreenerTable`'s `ColumnSettingsPopover` already solves this; **lift to shared `components/data/ColumnSettings.tsx`** with `ColumnRegistry<TRow>` type. Persistence key `worldview-columns:portfolio-holdings` with schema version.
- **F-COMP-004 (Multi-sort).** `useSortStack<T>()` hook + render small numeric badge in headers. URL-state synced (`?sort=pnl:desc,ticker:asc`).
- **F-COMP-005 (Symbol disambiguation).** S9 enriches `/v1/instruments/search` response with `{primary_listing, mic, isin, cusip, country_iso2}`. Frontend groups by `Primary / Secondary / Other`.
- **F-COMP-006 (Command palette).** Three CommandGroups: Symbols / Actions / Recent. Actions registry `lib/command-actions.ts` (~30 entries).

## 5.2 Universal DataTable Spec (the single most important component)

**Why this is foundation work:** Worldview has 7 data tables. Each implements its own header, sort, virtualization, column logic. **A single `<DataTable>` removes ~3,000 LOC of duplication** and unlocks bulk-actions, freeze panes, sticky-footer totals, group-by aggregation, saved views, copy-as-TSV, search-within everywhere at once.

Full props interface in source report — supports: density variants (compact 22px / default 26px / comfortable 32px), virtualization (auto >200 rows), frozen columns + rows, multi-sort, multi-select with bulk-actions, inline edit, group-by aggregation, saved views per `savedViewKey`, exporters (csv/tsv/xlsx/pdf), context menu integration, FlashBus integration for live cells.

**Migration:** 7 tables consolidate to one `<DataTable>`. Net deletion: ~2,500 LOC. **Effort: 8 days.**

## 5.3 Universal Form Spec — RHF + Zod (CRITICAL — F-COMP-NEW-FORM-001)

**Verified gap:** Grep returns zero matches for `react-hook-form`. `package.json` lacks `react-hook-form`, `@hookform/resolvers`, `zod`. `AlertRuleBuilder.tsx:25` uses `useState`. `ScreenerFilterBar.tsx` (986 LOC, 4 useState) hand-rolls field state, validation, submit.

**Solution:** Adopt `react-hook-form@7.50` + `zod@3.23` + `@hookform/resolvers@3.3`. Build `<Form>`/`<FormField>` shell over shadcn `Input/Select/Checkbox` injecting density-aware sizing.

**Effort:** 1d primitive + 0.5–1d per form (8 forms ~ 6d total).

## 5.4 Form primitives (4 missing)

- **`<NumberInput>`** with `Intl.NumberFormat` display, parse-on-blur, scientific notation, TradingView shorthand (`1.5m`, `25b`), Up/Down arrows step (Shift x10, Cmd x100). **1.5d.**
- **`<DateRangePicker>`** with presets (1W/1M/MTD/QTD/YTD/1Y/ALL/Custom) via `react-day-picker@8`, full keyboard nav. **2d.**
- **`<TimePicker tz>`** always 24h with tz badge. **0.5d.**
- **`<MultiCombobox>`** over cmdk — type-ahead, virtualized at >=200 options, multi-select chips, async search, group-by, pinned favorites. **2d.**

## 5.5 ContextMenu Action Registry

Six categories: Navigate / Watchlist / Alert / Trade / Copy-Export / View. Registry shape `ContextAction = {id, label, category, icon, hotkey, appliesTo, visible, enabled, run}`. **Effort: 2d.**

## 5.6 Hotkey Manager + Conflict Resolution

`<HotkeyProvider>` with scope stack: `modal > input > chart > table > global`. 1.2s chord-reset window. Master hotkey table covers 60+ entries. Cheat-sheet overlay (`?`) auto-derives from registered bindings — no hand-maintained list. **Effort: 3d.**

## 5.7 Bulk Actions Pattern

DataTable `bulkActions={[...]}` prop. Sticky bottom bar visible when `selectedIds.size > 0`. Selection survives sort/filter.

## 5.8 Confirmation/Undo Pattern Library

Three-tier ladder: T1 soft-delete + 8s undo toast / T2 confirm AlertDialog + 1.5s delay / T3 typed-name confirm. `<DestructiveButton tier="T1|T2|T3" entityName?: string>`. **Effort: 1d primitive + 0.5d audit.**

## 5.9 Toast / Banner System

**Adopt `sonner@1.5`.** Mount `<Toaster>` in `app/(app)/layout.tsx`. **Five-level urgency taxonomy:** L1 inline hint / L2 toast / L3 inline alert / L4 system banner / L5 modal AlertDialog. **Effort: 1.5d.**

## 5.10 Mobile / Tablet Strategy (CRITICAL — F-COMP-NEW-MOBILE-001)

**Verified:** Zero responsive breakpoints below 1280px. PMs review portfolios on iPad in client meetings. Decision matrix per surface, breakpoint strategy 1280/1024/768/480, touch target >=44x44px on `pointer:coarse`, long-press auto-binds to ContextMenu, pull-to-refresh on `/dashboard|/portfolio|/screener`. **Effort: 5d.**

## 5.11 Components issues newly discovered (30+ — see §8.3)

Highlights: F-COMP-NEW-001 Combobox/MultiCombobox, NEW-002 Quick-edit popover, NEW-003 Drag-drop row reorder, NEW-004 CSV bulk import wizard (3-step Upload/Preview/Confirm), NEW-006 Sticky footer totals, NEW-007 Frozen rows, NEW-008 Grouped subtotals, NEW-009 Multi-row column headers, NEW-010 Saved views per table, NEW-011 Excel-like range selection, NEW-012 Copy as TSV, NEW-013 Search-within-table, NEW-014 Filter chip row, NEW-020 Icon-only button aria-label lint rule, NEW-022 Focus management/restore, NEW-023 Skeleton variants, NEW-024 EmptyState consolidation, NEW-026 Universal column-type renderers, NEW-028 Trade ticket slide-in, NEW-030 Keyboard nav in trees.

## 5.12 Components wave summary

**~47 dev-days** total in 7 waves: W1 Foundation primitives (8d), W2 Universal DataTable (10d), W3 Form layer (8d), W4 Confirm/Undo + Bulk (3d), W5 Polish & a11y (5d), W6 CSV Import + Trade Ticket + drag-drop (7d), W7 Mobile/Tablet/Print (6d).

**Required new dependencies:** `sonner`, `react-hook-form`, `@hookform/resolvers`, `zod`, `@radix-ui/react-context-menu`, `@radix-ui/react-hover-card`, `react-day-picker`, `@dnd-kit/sortable`, `@dnd-kit/core`, `papaparse`. ~85 KB gz total impact, offset by removing recharts (~80 KB) and three dead deps.

---

# 6. Section D — Visual Design System (Principal Visual Designer)

**Composite verdict:** 7.2/10 — top 5% in category for a Next.js + shadcn/ui project, but not an institutional design system. The system is a **dark-mode skin over default shadcn primitives** with three parallel implementations. **Six load-bearing files** (`app/globals.css`, `tailwind.config.ts`, `lib/utils.ts`, `components/ui/{button,input,tabs,dialog,select}.tsx`) — fixing them rebuilds the entire visual experience without touching one feature component.

## 6.1 Verified findings

| ID | Finding | Verified | Sev | Effort |
|----|---------|:--------:|:---:|:------:|
| F-VISUAL-001 | `--positive: #26A69A` is TradingView teal, not institutional green | YES | CRITICAL | 30min |
| F-VISUAL-002 | `--negative` and `--destructive` collide on `#EF5350` | YES | CRITICAL | 30min |
| F-VISUAL-003 | `heatCellColor()` returns retired Bloomberg Dark palette (forbidden by `globals.css:11`) | YES | CRITICAL | 2h |
| F-VISUAL-004/5/6 | Button/Input/Tabs default `h-9` consumer-SaaS scale | YES | MAJOR | 1h each |
| F-VISUAL-008 | Color-blind collapse: deuteranope luminance for current positive/negative is identical | YES | MAJOR | (covered by F-001/002) |
| F-VISUAL-011 | 10 type sizes in active use (210 occurrences of bracketed-pixel forms) | YES | MAJOR | 1d |
| F-VISUAL-013 | Icon stroke widths 0.75/1/1.5/2/2.5 mixed; lucide default leaks | YES | MAJOR | 4h |
| F-VISUAL-022 | `bg-amber-500/20` in AskAI panel bypasses tokens | YES | MAJOR | 30min |
| F-VISUAL-027 | `disabled:opacity-50` (388 sites) yields ~2:1 contrast — fails WCAG AA | YES | MAJOR | 2h |
| F-VISUAL-037 | Hero price `text-4xl` (36px) is Robinhood-grade | YES | MAJOR | 30min |
| F-VISUAL-039 | `GlobalSearch` input `h-12` is 2x rest of system | YES | MAJOR | 15min |

## 6.2 Newly discovered CRITICAL findings

### F-VISUAL-NEW-A — No token pipeline; `:root` and `.dark` blocks drift silently

**Verified at:** `app/globals.css:29-106` defines variables in `:root`; `app/globals.css:109-138` re-defines them in `.dark`. The blocks are textually duplicated, but `--muted-foreground: 55%` in `:root` (with a 9-line WCAG comment justifying the bump) **vs `46%` in `.dark`**. The fix from PLAN-0053 was applied to one block and not the other. **The active class is `.dark` — the WCAG fix never shipped.** Measured contrast of the live value: 4.27:1 — fails AA. Every `text-muted-foreground` site in the app is sub-AA right now.

**Long-term solution:** **Style Dictionary architecture.** Token source `apps/worldview-web/tokens/{core,semantic,component}/`; build emits `app/generated/tokens.css`, `lib/generated/tokens.ts`, `tokens/build/tailwind.tokens.cjs`. CI gate: `pnpm tokens:build && git diff --exit-code app/generated/ lib/generated/` fails if drift. Single edit point. Drift becomes impossible.

**Effort: 2 days.**

### F-VISUAL-NEW-B — Zero accessibility-mode coverage

**Verified:** Grep for `prefers-reduced-motion`, `forced-colors`, `@media print`, `prefers-contrast` returns **zero matches**.

**Impact:**
1. `prefers-reduced-motion`: All animations fire for users with vestibular disorders. WCAG 2.1 SC 2.3.3.
2. `forced-colors` (Windows High Contrast): ~6% of Windows enterprise users have this enabled. Currently every `bg-positive/10` becomes `Canvas`; every `border-border` becomes `CanvasText` (invisible). **Disqualifying for BlackRock — they have an enterprise accessibility committee.**
3. `prefers-contrast: more`: No high-contrast mode definition.
4. Print: `Cmd+P` from any page renders dark theme on white paper — pure black rectangles, illegible.

**Solution:** Four `@media` blocks in `globals.css` covering reduced-motion, forced-colors, prefers-contrast, print. **Effort: 1 day.**

### F-VISUAL-NEW-C — No brand identity

**Verified:** `apps/worldview-web/public/` is empty. No `favicon.ico`, no `icon.svg`, no `apple-touch-icon`, no `og-image.png`, no wordmark. Browser tab shows Vercel default globe.

**Impact for BlackRock demo:** Bookmarks bar shows default globe. Slack share has no preview. Print PDF has no header logo. This is the difference between "thesis project" and "product".

**Spec:** `public/{favicon.ico,icon.svg,icon-{16,32,180,192,512}.png,manifest.webmanifest,og-image.png}` + `brand/{worldview-mark.svg,worldview-wordmark.svg,brand-guide.pdf}`. Mark proposal: 4x4 grid of squares with one yellow square in top-right (terminal-cell metaphor). Wordmark: IBM Plex Sans 600, lowercase `worldview` with `o` replaced by filled yellow square.

**Effort: 1 day.**

### F-VISUAL-NEW-D — Color-space ambiguity (sRGB vs P3)

`#FFD60A` displayed on Apple Studio Display measures as `display-p3(0.987 0.836 0.071)` ~ visually `#FCD512` in sRGB — perceptual delta-E ~1.4. Brand color drifts.

**Solution:** Define both sRGB and P3 variants for saturated tokens via `@media (color-gamut: p3)`. **Effort: 4h.**

## 6.3 Color Palette Redesign (definitive table)

| Token | Current | Proposed | Rationale |
|-------|---------|----------|-----------|
| `--background` | `#09090B` | unchanged | Perfect — keep |
| `--card` | `#111113` | `#0F0F11` | Slight darken for surface-2 gap |
| `--surface-2` | `#18181B` | `#15151A` | True intermediate (was aliased to muted) |
| `--muted` | `#18181B` | `#1D1D23` | Hover/selected rows |
| `--surface-3` | `#27272A` | `#2D2D32` | Inputs, divider strong |
| `--border` | `#27272A` | `#222226` | Subtle row dividers |
| `--divider-strong` | (new) | `#34343A` | Panel boundaries |
| `--muted-foreground` | `#71717A` | `#83838A` | Bump to 5.42:1 (was 4.27 via .dark) |
| `--positive` | `#26A69A` | **`#00D26A`** | **Institutional green; AAA 9.18:1** |
| `--negative` | `#EF5350` | **`#FF3B5C`** | **Urgent red; 6.83:1** |
| `--destructive` | `#EF5350` | `#EF4444` | Split from negative |
| `--warning` | `#F59E0B` | `#FFB000` | Bloomberg amber |
| `--accent-ai` | (new) | `#A855F7` | Universal industry AI color (violet) |
| `--primary` | `#FFD60A` | unchanged | Bloomberg yellow — keep |

## 6.4 Typography Lock-in

6-size scale only — ban everything else via ESLint:

| Token | Size | Weight | Use |
|-------|:----:|:------:|-----|
| `text-key` | 10px | 500 | Column headers, axis labels (UPPERCASE 0.08em) |
| `text-data` | 11px | 400 | Data values, KPIs (font-mono tabular-nums) |
| `text-body` | 12px | 400 | Body text, descriptions |
| `text-title` | 14px | 500 | Card titles, primary buttons |
| `text-h2` | 18px | 600 | Page section headings |
| `text-hero` | 24px | 700 | Hero KPIs, instrument hero price |

**Banned:** `text-base` (16px consumer), `text-2xl`, `text-xl`, `text-4xl`, `text-[9px]` (illegible), bracketed `text-[Npx]` outside tokens. Codemod: `text-[11px] -> text-data`, `text-xs -> text-body`, `text-sm -> text-title`, `text-2xl -> text-h2`, `text-4xl -> text-hero` via jscodeshift (~210 sites).

## 6.5 Iconography Lock-in

`lib/icons.tsx` shim wraps lucide-react with `strokeWidth={1.5}` enforcement. ESLint rule bans direct `lucide-react` imports outside the shim. Three sizes only: 12px (data rows), 16px (toolbars/nav default), 20px (dialog/empty-states).

## 6.6 Slashed-zero financial convention (F-VISUAL-NEW-H)

```css
body, .font-mono, [class*="tabular-nums"] {
  font-feature-settings: "tnum" 1, "zero" 1, "ss01" 1, "salt" 1, "case" 1, "cv11" 1;
  font-variant-numeric: tabular-nums slashed-zero;
}
```

Disambiguates `0` from `O` (IBM 3270 era convention preserved by every institutional terminal).

## 6.7 Visual issues newly discovered (13 — see §8.4)

- **NEW-E** `::selection` unstyled (defaults to OS browser blue); 5min fix
- **NEW-F** Cursor system absent (no `crosshair` for chart, no `ew-resize` for resize handles)
- **NEW-G** Font weight over-shipping (loads 5 weights, only 4 used) — saves ~90KB
- **NEW-I** No GICS sector color table (sector identity color)
- **NEW-J** No asset-class color taxonomy (equity/bond/fx/commodity/crypto)
- **NEW-K** Animation easing left at Tailwind defaults (no institutional easing tokens)
- **NEW-L** Letter-spacing ad-hoc (388 `tracking-*` sites, no per-token assignment)
- **NEW-M** Two CSS-variable blocks drift (the `--muted-foreground` 55%/46% bug)

## 6.8 System taxonomies (full token tables in source report)

- **Status**: success / info / warning / error / neutral
- **Severity (alerts)**: critical / high / medium / low
- **Quality (data freshness)**: live / fresh / delayed / stale / na
- **Confidence (AI outputs)**: high / medium / low
- **GICS sectors**: 11 stable hue assignments at uniform OKLCH lightness 45% chroma 0.12 (no sector visually dominates the heatmap)
- **Asset classes**: equity / etf / bond / fx / commodity / crypto / index

## 6.9 Visual wave summary

**11 days** in 7 waves: W1 token surgery (1d) — closes F-001/002/003/022/027/NEW-M/NEW-E/NEW-H. W2 token pipeline (2d) — closes NEW-A. W3 accessibility coverage (1d) — closes NEW-B + 008. W4 brand identity (1d) — closes NEW-C. W5 UI primitive density (2d). W6 type+icon scale (2d). W7 system taxonomies (2d).

**W1 alone (1 day) closes the three CRITICAL audit findings + four self-discovered minor-but-pernicious ones.** W1+W2+W5 (5 days) achieves "BlackRock-credible visual system."

---

# 7. Section E — Layout & IA / Search & Navigation (Principal UX Architect)

**Composite verdict:** 5.5/10 (Layout) + 4.5/10 (Search/Nav). Workflow grammar was **never defined** — the dead StatusBar shortcuts are a symptom of an architectural absence, not a forgotten wire-up task.

## 7.1 Verified findings

All audit-CRITICAL findings (F-LAYOUT-001/002/003/004/026 + F-LAYOUT-033) confirmed at exact file:line evidence. Notable detail:

- **F-LAYOUT-001:** Grep across the entire frontend for `useHotkeys|addEventListener\(.keydown.|key === "g"` returns six files, all of which scope keys to a single component (cmdk's `Cmd+K` in `GlobalSearch.tsx`, `Esc` in `AskAiPanel.tsx`, chart-only keys in `OHLCVChart.tsx`). **No global chord listener exists.** `hooks/` directory contains 15 hooks; none are named `useGlobalHotkeys`/`useChord`/`useKeyboard`.
- **F-LAYOUT-002:** Both `Sidebar.tsx` (267 LOC, legacy 56px) and `CollapsibleSidebar.tsx` (358 LOC, current 48-340px drag-resizable) exist. `Sidebar.tsx` ships chord hints (line 207-237) that no one reads. Grep confirms zero current imports of `Sidebar.tsx`.

## 7.2 Navigation Grammar (the architectural foundation)

Three vocabularies, three input modes, **one registry**:

| Vocabulary | Input mode | Example | Backed by |
|------------|-----------|---------|-----------|
| **Symbol** | Type / paste / pill click | `AAPL` | S9 `/v1/search/instruments` |
| **Function** | Mnemonic / chord / `g x` | `g s` (Screener), `D` (Description on `/instruments/[id]`) | hotkey-registry |
| **Action** | `>` prefix in palette / chord | `>export csv`, `Cmd+E` | command-registry |

**Sentence:** `[symbol] + [function] + [action]?`:
- `AAPL` `D` -> AAPL Description
- `AAPL` `Tab` `CN` `Enter` -> AAPL News (Bloomberg classic)
- `>create alert AAPL` -> seeded AlertRuleBuilder
- `g s` -> /screener (no symbol)
- `Cmd+K` -> palette empty, choose

## 7.3 Hotkey Registry (full chord scheme)

**NAVIGATION** (chord prefix `g`): `g d/p/i/s/w/a/n/c/r/k/h/,` -> Dashboard/Portfolio/Instruments/Screener/Workspace/Alerts/News/Chat/Research/KnowledgeGraph/Help/Settings

**SYMBOL CONTEXT** (on `/instruments/[id]`): `d/g/f/n/h/r/e/o` -> Description/Chart/Fundamentals/News/Holdings/Peers/Earnings/Insider

**GLOBAL ACTIONS:** `Cmd+K` palette / `Shift+Cmd+P` actions-only / `/` focus search / `?` cheatsheet / `Esc` close / `Cmd+B` sidebar / `Cmd+.` statusbar / `Cmd+\` split-vertical / `Cmd+-` split-horizontal / `Shift+Cmd+W` close panel (NOT `Cmd+W` — browser owns) / `Cmd+1..9` focus panel / `Cmd+R` refresh / `Cmd+E` export CSV / `Shift+Cmd+E` export PDF / `Cmd+D` add to default watchlist / `Shift+Cmd+D` add to specific / `Cmd+Backslash+Backslash` detach panel / `Cmd+Enter` open palette result in new workspace panel (Bloomberg `<GO>`)

**TABLE** (when table focused): `j/k` row down/up / `Space` toggle select / `Shift+Space` range / `Enter` open primary / `Cmd+A` select all / `Cmd+Backspace` delete with confirm / `c` open context menu (mouse-less right-click)

**CHART** (when chart focused): `+/-` zoom / `arrows` pan / `l` log scale / `i` indicators / `c` compare picker / `m` markers picker

**Conflict resolution:** Scope precedence `modal > input > chart > table > global`. Inner-most scope handles first; bubbles up. `c` is owned by chart focus when chart is focused; otherwise table interpretation.

## 7.4 Three-mode Command Palette

**Input parser** (`lib/command-parser.ts`): query.startsWith("?") -> HelpMode; ">" -> ActionMode; "/" -> SavedScreenMode; ISIN/CUSIP regex -> SymbolMode(identifier); else -> SymbolMode(query).

**Empty state:** Three CommandGroups — Recent Symbols (5) / Recent Actions (3) / Suggested for {pathname} (3).

**Ranking:** Exact ticker match -> Prefix match -> Recent (decay weight 1/hours-since-used) -> Pinned by user -> Fuzzy (sift4 distance).

**Keyboard:** Up/Down navigate / `Tab` enter modifier mode (`AAPL Tab CN`) / `Enter` execute / `Cmd+Enter` execute as new workspace panel (Bloomberg `<GO>`) / `Opt+Enter` open in new browser tab (multi-monitor pop) / `Esc` close.

**AI search mode** (`>>` prefix): opens AI palette via S8 chat backend with intent classifier — falls back to chat if confidence <0.6.

## 7.5 Information Architecture Master Map

Every route defined, future-proofed for risk dashboards, options chains, trade blotter, compliance, CRM, admin, B2B org. See source report for complete tree. Highlights:

- `/portfolio/[id]/{holdings,transactions,performance,risk,optimize,scenarios}` (last three NEW)
- `/instruments/[id]/{overview,chart,fundamentals,news,holdings,peers,earnings,insider,options,filings}` (last two NEW)
- `/watchlists/[id]` (PROMOTED from 307 redirect)
- `/news/[id]`, `/news/feeds` (PROMOTED from 307 redirect)
- `/research/{notes,calendar,macro}` (NEW)
- `/risk/{portfolio,limits,breaches}` (NEW B2B)
- `/trade/{blotter,staging,fix}` (NEW post-MVP)
- `/compliance/{audit,restricted-list,disclosures}` (NEW B2B/audit)
- `/crm/{clients,meetings}` (NEW RIA mode)
- `/admin/{users,teams,permissions,billing,integrations,api-keys,audit-log}` (NEW B2B org)
- `/help/{shortcuts,docs,videos,changelog,status,feedback}` (NEW)

## 7.6 Workspace System Architecture

**Data model:** `Workspace` extended with `ownerId`, `orgId`, `visibility: "private"|"team"|"org"|"public-link"`, `shareToken?`, `permissions: Permission[]`, `version`, `lastOpenedAt`, `pinnedToSidebar`, `isTemplate`, `templateMetadata`.

**Persistence — three tiers:**
1. **localStorage** — instant read/write; source of truth for unsaved drafts.
2. **S9 `/v1/workspaces`** — durable, cross-device, background-sync 5s if online+dirty. Conflict resolution: last-write-wins by `updatedAt` + version vector; on 409 frontend shows "Workspace edited on another device — keep mine | take theirs | merge".
3. **S9 `/v1/workspaces/[id]/share?token=`** — public read-only token URLs (signed JWT).

**Sharing model:** Personal / Team (members read, admins write) / Org (all members read, designated editors write) / Public-link (unauthenticated read via shareToken — read-only embed) / Marketplace template (publishable opt-in copy, forks on consume).

**Marketplace (post-MVP):** `/workspace/templates` index + `/workspace/templates/[id]` preview. Tags by sector/role/region. Auto-generated screenshot. Curation: starred-by-team / starred-by-org / starred-by-worldview.

**Collaboration (post-MVP):** Y.js over `wss://gateway/v1/workspaces/[id]/collab`. Presence avatars in WorkspaceTabs. Cursors only on chart drawings + chat threads (not on dense panels — bad UX). Inline annotations pinned to chart timestamp / table row / news article. Activity log right-edge drawer (`Cmd+Shift+L`).

**Effort:** 5d MVP (private + share-link); +15d marketplace + collab.

## 7.7 Multi-Monitor Architecture

```
Browser tab "Main" (workspace WS-1)
  Each panel header has [📍 Pop out] [⛶ Maximize] [✕ Close]
  Click 📍 on Chart panel:
    window.open('/workspace/WS-1/panel/PANEL-42?detached=1', '_blank',
                'popup=yes,width=900,height=700')
                  ↓
  Detached window (workspace WS-1, panel PANEL-42)
    Minimal chrome | Just the panel | Same data subscriptions
    State sync: BroadcastChannel('worldview:ws:WS-1') in BOTH windows
      Main posts {type:"symbol-changed",symbol:"AAPL"}
      Detached subscribes -> updates panel data
      Detached posts {type:"chart-zoomed",range:...}
      Main optionally syncs (config-toggle)
```

**Components:** `hooks/useDetachedPanel.ts` (window.open with shared session cookie, BroadcastChannel subscriptions, beforeunload cleanup) / `hooks/useWindowRegistry.ts` (tracks all open windows for the workspace, "focus follows window") / `components/workspace/DetachedPanelShell.tsx` / `app/(app)/workspace/[id]/panel/[panelId]/page.tsx` (NEW route).

**Auth:** Same browser session = same cookies = same OIDC token. BroadcastChannel is same-origin only — perfect. Token refresh owned by Main; detached listen for `worldview:auth:token-refreshed`.

**Persistence of detached layout:** `localStorage["worldview:detached-windows:WS-1"] = [{panelId,x,y,w,h}]`. On main-tab reload: "Restore detached panels? (3)".

**Effort:** 5 days.

## 7.8 Notification & Alert IA

**Six-tier taxonomy:** SYSTEM / SECURITY / ALERTS / NEWS / WORKFLOW / MARKETING

**Six channels per-tier preference matrix** in `/settings/notifications`: in-app banner / in-app inbox / browser push / email / SMS / mobile push.

**Inbox surface (Linear-style)** at `/alerts/inbox` — primary destination. Left rail (220px) with Inbox/Today/This week/Snoozed/Archive + My Rules/Following/Muted. Center: stream of cards (unified across alerts + news mentions). Right (when item selected): detail drawer.

**TopBar bell** opens `/alerts/inbox` with unread count. Browser push and emails are *delivery channels* of the same alert objects.

## 7.9 Settings IA (eleven-route tree)

`/settings/{profile,preferences,appearance,notifications,shortcuts,data,security,integrations,api-keys,billing,feedback,danger}`. Two-column layout: left rail (200px) of categories grouped under "You/Account/App/Org" headers; right pane is the section. Settings categories themselves searchable (`Cmd+K` `>setting locale`).

`/admin/{users,teams,permissions,audit-log,sso,billing}` for org-admin only.

## 7.10 Onboarding Flow

```
First sign-in -> S9 GET /v1/users/me/onboarding-state
/onboarding/welcome      "What is Worldview?" 5s skip
/onboarding/role         PM | Analyst | Trader | Quant | Advisor | Student
/onboarding/region       US / EU / Asia
/onboarding/sample-portfolio    Y/N: load 5-position sample
/onboarding/watchlist    pick 5 from suggested-by-role
/onboarding/connect      optional: connect brokerage
/onboarding/done         redirects to /dashboard with coachmark tour
```

Coachmark tour (Driver.js): TopBar symbol entry / Sidebar resize hint / Workspace template hint / `Cmd+K` palette teach / `?` cheat sheet teach.

Empty product state for zero portfolios: hero "Connect a brokerage / Add holdings manually / Use sample portfolio" — no broken table.

## 7.11 Permissions & Compliance Architecture

**Roles (org-scoped):** org-owner / org-admin / compliance-officer / pm / analyst / trader / read-only / external.

**Enforcement:** Backend S9 reads X-Internal-JWT roles claim -> route-level RBAC decorator. Frontend `<RoleGate role="pm">` wraps mutating UI. Fail-closed: missing role yields disabled button with tooltip.

**Audit trail:** Every write -> append-only S10 audit log entry `{who, when, route, payload-hash}`. `/admin/audit-log` searchable, exportable, retention 7y for SEC compliance.

**Four-eye (PRD-future):** Trades over $X require second approver from team.

## 7.12 Mobile / Tablet IA

- 1024px (iPad Pro landscape): full desktop IA, 2-row chrome compresses
- 768px (iPad portrait): sidebar collapses to icon rail; statusbar drops to 1 line
- 600px (mobile landscape): workspace -> single-panel-stack mode (swipe between panels)
- 480px (mobile portrait): READ-ONLY MODE — no `/trade` routes, no AlertRuleBuilder create

PMs use mobile to *review*, not *trade*. Lean into that.

## 7.13 URL State Schema

```
/portfolio/[id]?tab=holdings&sort=marketValue:desc&filter=tech&period=ytd
/screener/[id]?filters=mcap:gt:1e10,sector:eq:tech&sort=peRatio:asc&page=2
/instruments/[id]?tab=chart&period=1Y&compare=SPY,QQQ&indicators=ma50,rsi&log=1
/workspace/[id]?panel=42&symbol=AAPL&link=yellow
/alerts/inbox?status=unread&tier=alerts&since=2026-04-29
/news?watchlist=tech-mega-caps&since=24h&min-relevance=0.7
```

**Library:** `nuqs` (typed search-params, server+client, batched updates). Every filter/sort/period is a URL param; tabs are URL params (not router segments) when ≤5 tabs (back-button-friendly). **Every URL is a shareable view.**

## 7.14 Browser Tab / Window Strategy

Multiple tabs of same app: `BroadcastChannel('worldview:tabs')` -> leader election. Leader owns: WS connection, token refresh, alert push registration. Followers subscribe via BroadcastChannel. On leader-tab close: re-elect.

Cross-tab sync: workspace edits broadcast on `worldview:ws:[id]`, watchlist edits on `worldview:wl:[id]`, auth token refresh on `worldview:auth`.

## 7.15 Layout/IA issues newly discovered (32 — see §8.5)

**CRITICAL:**
- **N-001** No idle timeout / auto-lock (regulatory in some jurisdictions)
- **N-002** No session-expired graceful handling (queries silently fail on token expiry)
- **N-003** No force-update flow (users on stale tabs hit broken APIs)

**MAJOR:**
- **N-004** No status bar context-aware layout (three-zone left/center/right)
- **N-005** No timezone selector
- **N-006** No currency selector (paired with FX layer)
- **N-007** No density toggle as user preference
- **N-008** No a11y settings panel (high-contrast, reduced-motion override, font-scale)
- **N-009** No print/export-page pattern
- **N-010** No share-this-page hotkey (`Shift+Cmd+S` "Copy share link")
- **N-011** No quick-add (FAB) pattern
- **N-012** No drag-drop between surfaces (screener row -> watchlist tab)
- **N-013** No recent-items / history
- **N-014** No saved-items / pins / bookmarks
- **N-015** No tags / labels
- **N-016** No versioning of saved screens / saved layouts
- **N-017** No cookie/analytics consent (GDPR/CCPA blocker)

**MINOR:** 14 additional items including incident banner, multi-tab session, org/team switcher, feature flags, language selector, quick-toggle settings tray, wizard primitive, detail-master vs split-pane standard, service status link, footer, breadcrumbs, action bar placement, "What's new" badge, keyboard hint on hover.

## 7.16 Layout/IA wave summary

**~5 weeks** (1 senior frontend + 0.5 designer):
- **W1 (1-2w) Workflow Grammar Foundation:** hotkey registry + cheat sheet, command palette superset, SymbolBar, delete legacy Sidebar, session handling, URL-state schema.
- **W2 (1w) IA Correctness:** promote /watchlists + /news, settings reorg to 11-route tree, timezone/currency/density/a11y settings.
- **W3 (1w) Workspace v2:** quad template + drag-tray + chord splits, multi-monitor pop-out, S9 sync.
- **W4 (1mo) Collaboration + Marketplace:** sharing, marketplace skeleton, comments + presence, B2B foundations.
- **W5 (1mo) Polish + Differentiators:** print views, share-link, FAB, drag-drop, tags/pins/recent, mobile/tablet pass, onboarding flow.

**Closing W1+W2 alone (3 weeks)** moves BlackRock perception from "polished consumer fintech" to "credible institutional terminal" — the workflow grammar gap is the single most damaging signal in a 30-second demo.

---

# 8. Newly Discovered Issues — Full Catalog

The deep investigation surfaced **76 issues the original audit missed**. Indexed by section.

## 8.1 Codebase (14 new)

| ID | Severity | Issue | Effort |
|----|:--------:|-------|:------:|
| F-CODE-NEW-001 | MAJOR | `tsconfig.json` missing `noUncheckedIndexedAccess`, `noImplicitOverride`, `exactOptionalPropertyTypes`, `verbatimModuleSyntax` | 1w (staged) |
| F-CODE-NEW-002 | CRITICAL | Only ONE dynamic import in 250 .tsx files — audit overclaimed by ~10x | 2d |
| F-CODE-NEW-003 | MAJOR | Zero `React.memo`/`useTransition`/`useDeferredValue`/`use()` across the entire codebase | 3d |
| F-CODE-NEW-004 | MAJOR | `UtcClock` lazy initializer guarantees hydration mismatch (server clock vs client clock) | 0.5d |
| F-CODE-NEW-005 | MAJOR | 387 `createGateway(token)` callsites recreate factory every render (audit said 112) | 3d |
| F-CODE-NEW-006 | MAJOR | 67 raw `setInterval`/`setTimeout` callsites — stale-closure risk | 1.5d |
| F-CODE-NEW-007 | MAJOR | 77 direct `localStorage.*` callsites bypass schema validation (audit said 53) | 3d |
| F-CODE-NEW-008 | MAJOR | Only 3 `<Suspense>` boundaries vs 40 ErrorBoundary — unbalanced | 2d |
| F-CODE-NEW-009 | MAJOR | `@typescript-eslint/no-explicit-any` set to `warn`, not `error`; 21 `as any`/`: any` | 1d |
| F-CODE-NEW-010 | CRITICAL | **No Sentry / error monitoring** — only `console.error` strings | 2d |
| F-CODE-NEW-011 | MAJOR | Permanent `'unsafe-inline'` in script-src AND style-src CSP | 3d |
| F-CODE-NEW-012 | MAJOR | 250 .tsx files, 163 with `"use client"` (65%) — Server Components underused | 5d |
| F-CODE-NEW-013 | MAJOR | No internationalization layer (BlackRock APAC blocker) | 1w foundation + 3w extraction |
| F-CODE-NEW-014 | MINOR | Turbopack readiness untested; no SWC config | 0.5d |

## 8.2 Data Visualization (23 new)

| ID | Severity | Issue |
|----|:--------:|-------|
| F-DATAVIZ-NEW-001 | CRITICAL | Hardcoded USD currency; multi-currency unsupported despite API returning currency |
| F-DATAVIZ-NEW-002 | MAJOR | No log/lin axis on `EquityCurveChart` |
| F-DATAVIZ-NEW-003 | MAJOR | No print/PDF export standard |
| F-DATAVIZ-NEW-004 | MINOR | No chart screenshot to clipboard |
| F-DATAVIZ-NEW-005 | MAJOR | Annotations local-only (IDB) — not synced cross-device |
| F-DATAVIZ-NEW-006 | MAJOR | No keyboard navigation on charts |
| F-DATAVIZ-NEW-007 | MINOR | No screen-reader sonification |
| F-DATAVIZ-NEW-008 | MAJOR | No color-blind audit (covered by manual sim — needs automated test) |
| F-DATAVIZ-NEW-009 | MAJOR | No pre-market / after-hours session shading |
| F-DATAVIZ-NEW-010 | MINOR | No weekend gap handling spec |
| F-DATAVIZ-NEW-011 | MAJOR | No volume profile orientation control (POC line, value-area shading) |
| F-DATAVIZ-NEW-012 | MAJOR (future) | Options chain visualization absent (matrix, greeks, IV surface, GEX) |
| F-DATAVIZ-NEW-013 | MAJOR (future) | Order book / market depth ladder absent |
| F-DATAVIZ-NEW-014 | MAJOR | Risk dashboard charts absent (VaR fan, rolling beta, factor radar) |
| F-DATAVIZ-NEW-015 | MAJOR | Brinson-Fachler attribution chart absent |
| F-DATAVIZ-NEW-016 | MAJOR | Underwater drawdown plot absent |
| F-DATAVIZ-NEW-017 | MAJOR | Rolling correlation matrix absent |
| F-DATAVIZ-NEW-018 | MAJOR | Sector rotation quadrant (RRG) absent |
| F-DATAVIZ-NEW-019 | MAJOR | News sentiment overlay on price absent (S6 emits `composite_score` unused) |
| F-DATAVIZ-NEW-020 | MAJOR | No streaming latency display in StatusBar |
| F-DATAVIZ-NEW-021 | MAJOR | Indicator parameters hardcoded (RSI=14, MACD=12,26,9, BB=20,2) — no settings popover |
| F-DATAVIZ-NEW-022 | MINOR (future) | No custom indicator builder |
| F-DATAVIZ-NEW-023 | MINOR | No compliance watermark on charts |

## 8.3 Components (30+ new — abridged)

**Form & input layer:** F-COMP-NEW-FORM-001 No RHF+Zod adoption (CRITICAL) · F-COMP-NEW-FORM-002 Inconsistent validation feedback · F-COMP-NEW-NUMBER-001 No NumberInput primitive · F-COMP-NEW-DATE-001 No DateRangePicker primitive · F-COMP-NEW-TIME-001 No TimePicker primitive

**Table primitives:** F-COMP-NEW-001 No Combobox/MultiCombobox · NEW-002 Quick-edit popover for cells · NEW-003 Drag-drop row reorder · NEW-004 CSV bulk import wizard · NEW-005 Pagination/virtualization decision matrix · NEW-006 Sticky footer totals · NEW-007 Frozen/pinned rows · NEW-008 Grouped subtotals · NEW-009 Multi-row column headers · NEW-010 Saved views per table · NEW-011 Excel-like range selection · NEW-012 Copy as TSV · NEW-013 Search-within-table (Cmd+F local) · NEW-014 Filter chip row + numeric range slider · NEW-015 Density toggle per table · NEW-016 Loading state on async cell actions · NEW-017 Inline error recovery / retry

**Decision matrices needed (codified in DESIGN_SYSTEM.md):** F-COMP-NEW-018 Tooltip vs Popover vs HoverCard · NEW-019 Sidesheet vs Modal vs Popover · NEW-021 Dialog stacking conventions · NEW-025 Confirm flow tier ladder

**Accessibility:** F-COMP-NEW-020 Icon-only button missing aria-label · NEW-022 Focus management / restore on close

**Polish:** F-COMP-NEW-023 Skeleton variants (`<RowSkeleton>`, `<CellSkeleton>`, `<ChartSkeleton>`) · NEW-024 EmptyState consolidation · NEW-026 Universal column-type renderers (`lib/table/renderers.tsx`) · NEW-027 Row-level annotations (Aladdin signature, post-MVP) · NEW-028 Trade ticket / quick-action slide-in · NEW-029 Print per-table view · NEW-030 Keyboard nav inside trees / nested lists · NEW-MOBILE-001 Mobile/tablet strategy below 1280px · NEW-TOAST-001 Toast/banner system · NEW-CONFIRM-001 Three-tier destructive-confirm ladder · NEW-UNDO-001 Undo bus · NEW-BULK-001 Bulk-action bar · NEW-PRINT-001 Print stylesheets · NEW-HOTKEY-001 No global hotkey infrastructure

## 8.4 Visual (13 new)

| ID | Severity | Issue |
|----|:--------:|-------|
| F-VISUAL-NEW-A | CRITICAL | No token pipeline; `:root` and `.dark` blocks drift silently |
| F-VISUAL-NEW-B | CRITICAL | Zero accessibility-mode coverage (reduced-motion, forced-colors, prefers-contrast, print) |
| F-VISUAL-NEW-C | CRITICAL | No brand identity (empty `public/`, no favicon, wordmark, OG image) |
| F-VISUAL-NEW-D | MAJOR | Color-space ambiguity (sRGB vs P3 — brand yellow drifts) |
| F-VISUAL-NEW-E | MINOR | `::selection` unstyled (defaults to OS browser blue) |
| F-VISUAL-NEW-F | MINOR | Cursor system absent (no `crosshair` for chart, no `ew-resize`) |
| F-VISUAL-NEW-G | MINOR | Font weight over-shipping (5 weights, 4 used — saves ~90KB) |
| F-VISUAL-NEW-H | MINOR | No `font-variant-numeric: slashed-zero` (financial convention) |
| F-VISUAL-NEW-I | MINOR | No GICS sector color table |
| F-VISUAL-NEW-J | MINOR | No asset-class color taxonomy |
| F-VISUAL-NEW-K | MINOR | Animation easing left at Tailwind defaults |
| F-VISUAL-NEW-L | MINOR | Letter-spacing ad-hoc (388 `tracking-*` sites, no per-token assignment) |
| F-VISUAL-NEW-M | NIT (silent CRITICAL) | `:root` vs `.dark` drift on `--muted-foreground` (55% vs 46% — WCAG fix never shipped) |

## 8.5 Layout / IA (32 new — N-001 through N-032)

| ID | Severity | Issue |
|----|:--------:|-------|
| N-001 | CRITICAL | No idle timeout / auto-lock (regulatory in some jurisdictions) |
| N-002 | CRITICAL | No session-expired graceful handling |
| N-003 | CRITICAL | No force-update flow when frontend ships breaking change |
| N-004 | MAJOR | StatusBar lacks three-zone layout (left/center/right) |
| N-005 | MAJOR | No timezone selector |
| N-006 | MAJOR | No currency selector (paired with FX layer) |
| N-007 | MAJOR | No user-preference density toggle |
| N-008 | MAJOR | No a11y settings panel |
| N-009 | MAJOR | No print/export-page pattern |
| N-010 | MAJOR | No share-this-page hotkey |
| N-011 | MAJOR | No quick-add (FAB) pattern |
| N-012 | MAJOR | No drag-drop between surfaces |
| N-013 | MAJOR | No recent-items / history |
| N-014 | MAJOR | No saved-items / pins / bookmarks |
| N-015 | MAJOR | No tags / labels system |
| N-016 | MAJOR | No versioning of saved screens / saved layouts |
| N-017 | MAJOR | No cookie/analytics consent (GDPR/CCPA blocker) |
| N-018 | MINOR | No incident/maintenance banner |
| N-019 | MINOR | No multi-tab session handling (sign out in one tab leaves others stale) |
| N-020 | MINOR | No org/team switcher (PRD-0025 prepared schema, no UI) |
| N-021 | MINOR | No feature-flag / experimentation primitive |
| N-022 | MINOR | No language selector stub |
| N-023 | MINOR | No quick-toggle settings tray |
| N-024 | MINOR | No wizard / multi-step IA primitive |
| N-025 | MINOR | Detail-master vs split-pane inconsistency |
| N-026 | MINOR | No service status link |
| N-027 | MINOR | Avatar/profile dropdown sparse |
| N-028 | NIT | Footer missing |
| N-029 | NIT | Breadcrumbs missing on deep routes |
| N-030 | NIT | Action bar placement on long forms |
| N-031 | NIT | No "What's new" badge on logo |
| N-032 | NIT | No keyboard hint on hover for buttons |

---

# 9. Master Roadmap — Sequenced Waves

The five specialist deep dives produce a combined 96 fix items spanning multiple architectural layers. The combined effort if naively summed is **~45 engineer-weeks**. Sequenced and parallelized across 2-3 engineers, **calendar time is ~16 weeks** to fully ship to BlackRock-credible.

The waves below are sequenced by dependency, not by which specialist produced them. Each wave leaves the codebase in a green state.

## 9.1 Wave 0 — Quick Wins & Foundations (1 week)

Zero dependencies, parallel-safe. Closes silent CRITICAL findings + sets foundation for everything.

| Item | Source | Effort |
|------|--------|:------:|
| Patch `globals.css` `.dark` block: `--muted-foreground: 240 4% 55%` (sync with `:root`) | F-VISUAL-NEW-M | 5min |
| Replace `--positive #26A69A` → `#00D26A`; replace `--negative #EF5350` → `#FF3B5C`; split `--destructive` → `#EF4444` | F-VISUAL-001/002 | 30min |
| Rewrite `lib/utils.ts:heatCellColor()` to derive from CSS vars (delete hardcoded retired palette) | F-VISUAL-003 | 2h |
| Add `--accent-ai #A855F7`; replace `bg-amber-*` AskAI hardcodes | F-VISUAL-022 | 30min |
| Add `disabled:` token replacements; remove blanket `disabled:opacity-50` | F-VISUAL-027 | 2h |
| Add `::selection` style; add slashed-zero font feature | F-VISUAL-NEW-E/H | 10min |
| Drop dead deps: `react-grid-layout`, `react-resizable`, `@radix-ui/react-toast`; mount `sonner` `<Toaster>` | F-CODE-010 / F-COMP-NEW-TOAST-001 | 0.5d |
| ESLint: `no-explicit-any` → `error`; bump `tsconfig.json` strict flags (stage 1) | F-CODE-NEW-009/001 | 1d |
| `next.config.ts`: enable React Compiler, `optimizePackageImports`, `compiler.removeConsole` prod | F-CODE-NEW-014 | 0.5d |
| Sentry wiring (`@sentry/nextjs`) — sourcemap upload, ErrorBoundary integration, Web Vitals | F-CODE-NEW-010 | 2d |
| Fix `UtcClock` hydration mismatch + similar (Date/random in client components) | F-CODE-NEW-004 | 0.5d |
| Add accessibility-mode CSS (`prefers-reduced-motion`, `forced-colors`, `prefers-contrast`, `@media print`) | F-VISUAL-NEW-B | 1d |
| Add minimum brand identity (favicon, icon.svg, og-image, manifest.webmanifest, wordmark.svg) | F-VISUAL-NEW-C | 1d |
| Delete legacy `Sidebar.tsx`; add CI guard | F-LAYOUT-002 | 30min |

**Wave 0 closes:** all three V-CRITICAL audit findings + four self-discovered minor-but-pernicious + dead deps + Sentry online before refactors land + a11y baseline + brand identity. **Demo-ready visual baseline reached at end of Week 1.**

## 9.2 Wave 1 — Workflow Grammar + Contract Spine (3 weeks)

Two parallel tracks. Track A is workflow grammar (Layout); Track B is data contract / state spine (Codebase).

**Track A — Workflow Grammar (1 engineer, 3 weeks):**
- Hotkey registry + `useChordHotkeys` + scope manager + cheat sheet overlay (`?`) → all reading from same source as StatusBar hints
- Three-mode command palette (Symbols / Actions / Recent) + `>` action mode + `?` help mode + AI search `>>` mode
- Persistent SymbolBar in StatusBar left edge — symbol-first `Tab+function` Bloomberg pattern
- Bloomberg-mnemonic per-page hotkeys on `/instruments/[id]` (D/G/F/N/H/R/E/O)
- Session expired flow + idle timeout / auto-lock + force-update flow + multi-tab sign-out broadcast (N-001/002/003/019)
- URL-state schema documented in `docs/ui/URL_STATE.md` + `nuqs` adoption on screener / portfolio / workspace / equity-period

**Track B — Contract Spine (1 engineer, 3 weeks):**
- `openapi-typescript` + `openapi-fetch` adoption; `types/generated/api.ts` from S9 `/openapi.json`; CI drift gate
- TanStack Query key factory `lib/query/keys.ts` (hierarchical); CI ban on inline `queryKey` literals
- `useApiClient()` provider — memoize gateway once per token (387 → 1)
- `useAuthedQuery` wrapper + `useInterval` Abramov pattern (eliminate 67 stale-closure risks)
- `lib/storage/safe-storage.ts` zod-validated wrapper; Zustand-persist for cross-feature UI prefs (replaces 4 hand-rolled contexts + 77 raw localStorage sites)
- `lib/format.ts` consolidation — replaces 4 formatters (USD-only → multi-currency aware via `useUserContext().currency`)

**Wave 1 closes:** F-LAYOUT-001/026/033, F-COMP-NEW-HOTKEY-001/006, F-CODE-002/005/006/016/019, F-CODE-NEW-005/006/007, F-DATAVIZ-004/NEW-001, N-001/002/003/019. The platform now has a coherent navigation grammar AND a typed contract.

## 9.3 Wave 2 — Decomposition + Real-Time (3 weeks)

**Track A — Real-Time (1 engineer, 2 weeks; backend dependency):**
- S2 quote-republisher → Kafka `quotes.tick.v1`
- S9 WebSocket `/v1/quotes/stream` route + S10 alerts WS proxy (kills CSP `unsafe` + token-in-URL)
- Frontend: `QuoteStreamProvider` + `useQuoteStream(ids)` + `FlashBus` + `useTickFlash`
- Apply tick-flash to: IndexTicker → LiveQuoteBadge → WatchlistPanel rows → ScreenerTable price/change → PortfolioSummary MTM → TopMovers → WorkspaceChartWidget last-bar
- StatusBar 3px connection-status dot (teal/amber/red)

**Track B — God-File Decomposition (2 engineers, 2-3 weeks):**
- Split `lib/gateway.ts` (2,657 LOC) into `lib/api/{auth,instruments,portfolios,watchlists,alerts,screener,chat,brokerage,markets}.ts` domain modules
- Decompose `app/(app)/portfolio/page.tsx` (1,739) into `features/portfolio/{components,hooks,queries,lib}/` — page becomes <100 LOC orchestrator
- Decompose `app/(app)/chat/page.tsx` (1,293) — extract `useChatStream(threadId)` hook (or adopt `@vercel/ai-sdk`'s `useChat`); split into `<ThreadSidebar>`, `<ConversationView>`, `<MessageComposer>`, `<CitationPanel>`
- Decompose `components/screener/ScreenerFilterBar.tsx` (986) — split into per-section + adopt `react-hook-form` + `zod`
- Decompose `components/dashboard/WatchlistMoversWidget.tsx` (800) — extract `useWatchlistMovers(period, sectorFilter)` hook

**Wave 2 closes:** F-CODE-001/003/004/008/012, F-DATAVIZ-001/002/021, F-COMP-001/NEW-FORM-001. **The single largest credibility gap (no real-time tick flash)** is closed. Demo can now run during market open without freezing.

## 9.4 Wave 3 — Universal Primitive Layer (3 weeks)

The component primitive consolidation that closes ~30 component findings at once.

- **Universal `<DataTable>`** (10d, 1 engineer): replaces 7 tables; ships density variants, virtualization, frozen columns/rows, multi-sort, multi-select + bulk actions, inline edit, group-by aggregation, sticky footer totals, saved views per table, copy-as-TSV, search-within, exporters (csv/tsv/xlsx/pdf), context menu integration, FlashBus integration. **Net deletion: ~2,500 LOC.**
- **Form layer** (8d, 1 engineer): `<Form>`/`<FormField>` over RHF+Zod; `<NumberInput>` with TradingView shorthand; `<DateRangePicker>` with presets; `<TimePicker tz>`; `<MultiCombobox>` over cmdk; `<QuickEditPopover>` for inline cell edits.
- **`<ContextMenu>` primitive** (1d) + Action Registry (1d): six categories × 24+ actions, single Bloomberg-mnemonic letter hotkeys.
- **Confirm/Undo Pattern Library** (1.5d): three-tier ladder (T1 soft + 8s undo / T2 confirm + 1.5s delay / T3 typed-name).
- **Skeleton variants** + EmptyState consolidation + universal column-type renderers (`lib/table/renderers.tsx`).
- **Density variants on UI primitives:** Button h-7 default (was h-9), Input h-7, Tabs flat with primary underline, Dialog `p-4 gap-2 max-w-md` default + three sizes; ESLint type-size whitelist (6 sizes only); `lib/icons.tsx` lucide stroke-1.5 shim.

**Wave 3 closes:** All audit-CRITICAL component findings + ~30 NEW component findings + F-VISUAL-004/005/006/011/013/037/039.

## 9.5 Wave 4 — Performance + Bundle + Testing (2 weeks)

- Drop `recharts` (~80KB gz); migrate `EquityCurveChart`, `RevenueTrendSparklines`, `EarningsHistoryChart` to `lightweight-charts` line series
- Universal `<Sparkline>` rollout to 7 panels (`WatchlistPanel`, `WatchlistMoversWidget`, `TopMovers`, `HoldingsMoversWidget`, `PreMarketMoversWidget`, `PeerComparisonPanel`, `PortfolioSummary`) — single batched fetch
- Dynamic imports for all heavy widgets (audit baseline of 1 → ~15+): all dialogs, EntityGraph, WorkspaceGrid, KnowledgeGraph, MarkdownRenderer, ScreenerFilterBar, PDF/Excel exports
- React 19 patterns: `React.memo` on row/cell leaves (ScreenerTable rows, SemanticHoldingsTable rows, IndexTicker, WatchlistItem, AlertItem); `useDeferredValue` on filter inputs; `useTransition` on tab switches; stable callbacks via `useCallback`
- Server Components audit: strip `"use client"` from 30-50 pure-render components (StatCard, MarkdownRenderer, ArticleListItem, CompanyOverviewSection, Headline)
- CI gates: `bundlewatch` (>10% regression fails), Lighthouse CI per route (LCP <1.8s), `depcheck`+`knip`, `axe-core/playwright`
- Storybook 8 + Chromatic for visual regression (top 25 primitives + 12 financial widgets)

**Performance budget enforced:**
| Metric | Target |
|--------|--------|
| LCP (Dashboard, Portfolio, Screener) | <1.8s |
| TTI (any page) | <2.5s |
| First-load JS / route | <220KB gz |
| Total JS for `/portfolio` | <380KB gz |
| Re-renders per 15s tick | <30 components |
| Long task per interaction | <50ms |

## 9.6 Wave 5 — Multi-Pane Charts + Workspace v2 (3 weeks)

- **lightweight-charts v5 upgrade** + multi-pane indicator layout (RSI, MACD, ATR, Stoch, OBV each in own pane)
- **OHLCV chart power features:** crosshair HUD, log scale toggle, compare overlay (rebased %), earnings/news/alert markers, range selector, Brush on EquityCurveChart
- **Squarified treemap** algorithm `lib/treemap.ts`; collapse `MarketHeatmap` + `SectorHeatmapWidget` into single component
- **Knowledge Graph filters/layout:** filter pills (Companies/People/Events/Topics), edge-strength slider, search input, layout switcher (Force/Radial/Grid)
- **Workspace v2:** Quad-symbol template + workspace-level SymbolBar + drag-tray "Add Panel" (replace modal) + chord splits (`Cmd+\`, `Cmd+-`)
- **Multi-monitor pop-out:** wire `Maximize2` button + `Pop out` icon; `window.open` detached panel route + BroadcastChannel sync + `localStorage["worldview:detached-windows:WS-1"]` persistence
- **Workspace S9 sync** (3-tier: localStorage + S9 durable + share-link)

## 9.7 Wave 6 — Hardening + IA Correctness (2 weeks)

- IA correctness: promote `/watchlists` to real hub; promote `/news` to feed; remove `/portfolio` watchlists tab; settings reorganized to 11-route tree
- User-preference panels: timezone, currency (with FX layer), density, a11y settings (high-contrast, reduced-motion override, font-scale), notifications matrix
- `tsconfig.json` stage 2: `noUncheckedIndexedAccess` (~300 expected errors)
- Nonce-based CSP via `middleware.ts` (replaces `'unsafe-inline'`)
- Suspense boundaries everywhere appropriate; `<RouteSuspense>` wrapper at each page boundary
- Idle timeout/auto-lock + session-expired graceful handling + force-update flow
- Print stylesheets per route + share-this-page hotkey + watermark on charts
- Cookie/analytics consent (GDPR/CCPA)
- Page-bundle endpoints (S9 `/v1/portfolios/{id}/page-bundle` etc.) — collapses 12-deep waterfalls

## 9.8 Wave 7 — Differentiators (4 weeks)

- Saved items / pins / tags / recent / search history
- Versioning of saved screens / saved layouts (append-only with "View history" drawer)
- Drag-drop between surfaces (screener row → watchlist; chart annotation → research note)
- Quick-add FAB pattern + bulk CSV import wizard + trade ticket slide-in
- Three-level visualization additions: underwater drawdown plot, rolling beta vs SPY, factor radar, Brinson-Fachler attribution
- News sentiment overlay on price charts (S6 `composite_score`)
- Annotation cloud sync (IDB → S9 `/v1/annotations`)
- B2B foundations: org switcher, audit log surface, role-gate, permissions
- Onboarding flow + coachmark tour
- Mobile/tablet pass (responsive 1280/1024/768/480 breakpoints, long-press, pull-to-refresh)
- Storybook component catalog (Chromatic visual regression)

## 9.9 Beyond roadmap — strategic deferred

- **F-CODE-NEW-013 Internationalization** (`next-intl` + RTL) — 1w foundation + 3w extraction. Pursue only if BlackRock APAC is real.
- **Options chain visualizations** (chain matrix, greeks heatmap, IV surface, GEX) — 4w.
- **Order book / market depth ladder** — 2w.
- **Custom indicator builder** — 3w.
- **Workspace marketplace** — 3w (post-Wave 5).
- **Multi-user collaboration** (Y.js presence, comments, mentions) — 4w.
- **FIX gateway monitor** + `/trade/blotter` + `/trade/staging` — 6w.

## 9.10 Effort summary

| Wave | Title | Calendar weeks (1 eng) | Calendar weeks (2 eng) | Calendar weeks (3 eng) |
|------|-------|:----------------------:|:----------------------:|:----------------------:|
| W0 | Quick wins & foundations | 1 | 0.5 | 0.5 |
| W1 | Workflow grammar + contract | 6 | 3 | 2 |
| W2 | Decomposition + real-time | 6 | 3 | 2 |
| W3 | Universal primitives | 5 | 3 | 2 |
| W4 | Performance + bundle | 3 | 2 | 1.5 |
| W5 | Multi-pane charts + Workspace v2 | 5 | 3 | 2 |
| W6 | Hardening + IA correctness | 4 | 2 | 1.5 |
| W7 | Differentiators | 6 | 4 | 3 |
| **Total** | | **36 weeks** | **20 weeks** | **14 weeks** |

**Recommended:** 2 engineers, 20 weeks = ~5 calendar months to BlackRock-credible (Waves 0-6); +1 month for differentiators (Wave 7).

**Minimum demo path:** W0 + W1 + W2 = 8 calendar weeks (2 engineers). After this, the platform has working keyboards, working real-time, working contract layer, decomposed god-files, brand identity, and accessibility baseline. The remaining waves are polish.

---

# 10. Compounding Updates — Living Documentation

The deep investigation surfaces patterns that must be absorbed into the platform's living documentation per CLAUDE.md compounding rules.

## 10.1 `docs/BUG_PATTERNS.md` additions

- **BP-NEW-A** Hand-typed API response interfaces drift silently from backend OpenAPI; always codegen via `openapi-typescript`. (Symptom: hand-typed `types/api.ts` grows ~15% per 5 days untouched.)
- **BP-NEW-B** Recomputed-array `queryKey` causes refetch storms; stabilize via `useStableArray` or normalize key fragments via `.join(',')`.
- **BP-NEW-C** Advertising chord shortcuts in StatusBar without wiring a global hotkey listener teaches users their muscle memory will fail — actively destroys trust within 30 seconds of demo.
- **BP-NEW-D** Polling-only quote UIs read as "frozen / broken" to institutional users within 30s of market-open demo; tick-flash + WS stream is the recognizable primitive.
- **BP-NEW-E** Color-vision: deuteranope luminance for `#26A69A` (140) ~ `#EF5350` (140) — both collapse to indistinguishable greys. Always pair color with shape encoding (`▲▼◆`).
- **BP-NEW-F** `useState(() => formatXxx(new Date()))` with App Router runs on server during SSR with server's clock; hydrates with client's clock — guaranteed mismatch. Use `useState("")` + `useEffect(() => setX(...))` or `dynamic({ssr:false})`.
- **BP-NEW-G** `:root` and `.dark` blocks are both edited and silently drift. Always migrate to single source via Style Dictionary; otherwise WCAG fixes never ship to the active theme.
- **BP-NEW-H** Lazy-initializer in `useState(() => ...)` runs on server during initial render — never use for browser-only state (Date, random, localStorage).
- **BP-NEW-I** UI primitive `default` size at consumer SaaS scale (h-9, p-6) when feature components shadow with bespoke compact constants — drift signal; institutional defaults are h-7 / p-4.

## 10.2 `.claude/review/heuristics/HIGH_RISK_PATTERNS.md` additions

- **HR-NEW-1** UI primitive default size at consumer SaaS scale when feature components shadow with bespoke compact constants → drift signal. Refactor primitive density.
- **HR-NEW-2** Multiple chart libraries in `package.json` (recharts + lightweight-charts + sigma) → bundle bloat + visual style drift. Pick one per role.
- **HR-NEW-3** Hardcoded hex values in `lib/utils.ts` formatters that bypass CSS variable tokens → palette migration will leave them stranded.
- **HR-NEW-4** Direct WebSocket connections from frontend to non-S9 services → CSP/auth/deployment fragility.
- **HR-NEW-5** `queryKey: ["literal-string"]` inline → unscalable invalidation; require central key factory.
- **HR-NEW-6** Pages over 500 LOC, especially under `app/(app)/*/page.tsx` → god-file forming.
- **HR-NEW-7** Multiple inline form-state implementations (`useState`-based forms with >3 fields) → adopt RHF+Zod.
- **HR-NEW-8** Function-key advertising in chrome (`<kbd>` glyphs) without registry-backed handler → broken promise pattern.
- **HR-NEW-9** Lazy initializer in `useState(() => browserApi())` in client components → hydration mismatch.
- **HR-NEW-10** Dual implementations of the same domain object (4 watchlist surfaces, 2 sidebars, 4 number formatters) → centralize via shared primitive.

## 10.3 `docs/ui/DESIGN_SYSTEM.md` updates

Sections to add or rewrite:
- §2 Color Palette: replace with full table from §6.3 (institutional green, urgent red, split destructive, AI accent violet, divider-strong, P3 variants).
- §3 Typography: lock 6-size scale (key/data/body/title/h2/hero); ban all others; ESLint whitelist.
- §3.4 Negative number convention (hyphen — Bloomberg) — explicit decision.
- §4 Iconography: lucide stroke-1.5 shim; three sizes only (12/16/20); ban hardcoded `text-amber-*`/`text-blue-*`.
- §4.5 Density variants: compact/default/comfortable on every primitive; row-h tokens.
- §5 Animation system: durations (instant/fast/base/slow/glacial); easings (out-quart/in-quart/in-out-quart/spring/linear); reduced-motion clamps.
- §6 Themes: dark default; light theme dormant (token-pipeline-ready); high-contrast via `prefers-contrast: more`; print via `@media print`; forced-colors.
- §7 Brand: mark, wordmark, favicon, OG image specs.
- §8 Number formatting standard: full `lib/format.ts` API; sign-before-glyph; en-US locale only; UTC times; null → em-dash.
- §9 Real-time tick-flash + freshness dot pattern (FlashBus + useTickFlash + StatusBar connection dot).
- §10 Hotkey scheme + chord conventions + scope precedence.
- §11 Status / Severity / Quality / Confidence color taxonomies.
- §12 GICS sector + Asset class color tables.
- §13 Decision matrices: Tooltip vs Popover vs HoverCard; Sidesheet vs Modal vs Popover; Confirm tier ladder T1/T2/T3.
- §14 URL state schema convention (every filter/tab/period in URL via `nuqs`).

## 10.4 `RULES.md` candidates

- Frontend → S9 only via REST or WS-via-S9-proxy. Direct WS to other services prohibited.
- All API responses typed via `types/generated/api.ts` (codegen). Hand-typing prohibited.
- All `queryKey` literals via `lib/query/keys.ts` factory. Inline string-array prohibited.
- All forms with >3 fields via `react-hook-form` + `zod`. Raw `useState` form state prohibited.
- All hotkeys via central registry; no orphan `addEventListener('keydown', ...)`.
- All numeric formatters via `lib/format.ts`; hardcoded `toLocaleString` prohibited.
- All localStorage access via `lib/storage/safe-storage.ts` zod-validated wrapper.
- No file in `lib/api/`, `app/(app)/*/page.tsx` over 350 LOC.
- All disabled UI uses explicit token (not `opacity-50`).
- All icons imported from `lib/icons.tsx` shim (not `lucide-react` directly).

## 10.5 `.claude/review/checklists/REVIEW_CHECKLIST.md` additions

- Has any new `setInterval`/`setTimeout` been introduced without `useInterval` hook?
- Has any new `localStorage.*` been introduced without `safe-storage.ts`?
- Has any new `queryKey` been introduced as inline string-array?
- Has any new hotkey/chord been advertised in chrome but not registered?
- Has any new color been introduced as hex literal vs CSS variable?
- Has any new hex color been added to `lib/utils.ts` instead of token-derived?
- Has any new page exceeded 500 LOC?
- Has any new dynamic import opportunity been missed (heavy widget/dialog imported statically)?
- Has any new Server Component opportunity been missed (`"use client"` on a pure-render component)?
- Has any color encoding been added without paired shape encoding (`▲▼◆`)?

## 10.6 CI gates to add (or strengthen)

| Gate | Tool | Fails on |
|------|------|----------|
| Lint | next-lint + eslint | any error |
| Type | tsc --noEmit | any error |
| Test | vitest run | any failure |
| E2E smoke | playwright --grep @smoke | any failure |
| Bundle size | @next/bundle-analyzer + bundlewatch | >10% regression on any route |
| Lighthouse | @lhci/cli | LCP > 1.8s, CLS > 0.1, Perf < 90 |
| Dead deps | depcheck + knip | any unused |
| OpenAPI drift | scripts/check-openapi-drift.ts | types/generated/api.ts out of sync with S9 |
| A11y | axe-core/playwright | any serious violation |
| Visual regression | Chromatic | any unreviewed diff |
| Token pipeline drift | scripts/check-tokens-drift.ts | app/generated/tokens.css out of sync with tokens/ |
| God-file ceiling | scripts/check-loc.sh | any file in lib/api/ > 350; any page.tsx > 500 |
| `any` count regression | scripts/count-any.ts | any new `as any` or `: any` |
| Hardcoded hex | scripts/scan-hex.ts | hex outside tokens/ + lightweight-charts |

## 10.7 Memory updates (auto-memory)

Patterns observed in this investigation that should propagate to future sessions:

- **God-files actively grow.** Lock with CI ceilings; refactor immediately when a page first crosses 500 LOC.
- **Audit reports go stale fast.** Re-verify file:LOC counts before acting on findings older than 1 week.
- **Specialist agents in parallel produce 5x the depth.** When the user asks to "deep investigate" any audit, dispatch 1 specialist per section in parallel, never serially.
- **`:root` vs `.dark` divergence is silent**; always grep both blocks when changing tokens, or migrate to Style Dictionary before further token edits.
- **Visual chrome can be deceiving.** A platform can score 7+ on visuals while scoring 4 on architecture; always re-evaluate composite via specialist lenses.

---

## Closing

The Worldview frontend is **closer to BlackRock-credible than the original audit suggested for visuals and product surface, but further on architecture**. The composite revision (5.4/10) reflects active drift more than the original audit (6.0/10) captured.

**The single most leveraged investment:** Wave 0 (1 week) + Wave 1 Track A (workflow grammar, 3 weeks) + Wave 2 Track A (real-time, 2 weeks) = **6 calendar weeks for 2 engineers** — closes the four signals that disqualify a demo within 90 seconds (frozen UI, dead hotkeys, broken muted-foreground contrast, no brand identity), AND establishes the contract spine that every subsequent wave depends on.

After Wave 0+1+2, every remaining wave (universal primitives, performance, multi-pane charts, IA correctness, differentiators) is polish — important polish, but the existential signals are closed.

**Sources:** Five parallel principal-architect deep investigations dispatched 2026-04-30. Each produced 8-12k words of evidence-backed remediation. The original audit `docs/audits/2026-04-29-qa-institutional-ui-audit-report.md` remains the canonical findings index. This master report is the canonical remediation plan.

— Auditor team: Codebase Architect / Visualization Architect / Product Designer / Visual Designer / UX Architect
