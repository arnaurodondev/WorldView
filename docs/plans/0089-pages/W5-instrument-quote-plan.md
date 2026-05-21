# W5 — Instrument Quote Tab Density — Plan

**PRD**: 0089 platform page redesign
**Design**: `docs/designs/0089/05-instrument-quote.md` (562 lines, iter-2 on PLAN-0090 baseline)
**Audit**: `docs/designs/0089/oq/05-instrument-quote-CORNERS-AUDIT.md` (44 corners)
**Sibling foundation**: F1 (shipped) / F2 (shipped) / W1 (in flight) / W2 (in flight) / W3 (Financials — planned)
**Status**: ready-to-execute (pending W3 amendment per §0.5)
**Estimated**: 7 engineer-days serial / 4.5 wall-clock with 1 backend + 1 frontend agent
**Branch**: `feat/plan-0089-w5` (off the W3 integration head)

---

## §0. Design deltas from `05-instrument-quote.md` (post-audit)

The design doc remains the source of truth for the **what** (layout, density, components). The 9 BLOCKING + 20 IMPORTANT + 15 NICE corners from the audit are resolved in-plan below.

### §0.1 — F1 (design system) alignment

| # | Corner | Design says | Plan locks |
|---|--------|-------------|------------|
| Δ1 | C-F1-01 | `MetricGrid4Col` row 22px | Cells = `90px × var(--row-h)` (default 20px from `data-table-grid`). 18px (`data-table-grid="dense"`) reserved for the 3 below-fold lists (insider/earnings/news). |
| Δ2 | C-F1-02 | `text-[9px]` labels | F1 floor = 10px. Use `text-[10px]` for MetricGrid labels and insider/news secondary text. 9px reserved for the section-tag micro-pill only. |
| Δ3 | C-F1-03 | `rounded-[2px]` panels | F1 locks rounded=0 globally (DISCUSS-3 + DISCUSS-11). All panel corners hard square. |
| Δ4 | C-F1-04 | No `data-table-grid` opt-in | Add `<div data-table-grid>` on `MetricGrid4Col`. Add `<div data-table-grid="dense">` on `InsiderActivityList` / `EarningsMiniList` / `RelatedHeadlinesList`. Drop manual `border-r border-border/30` — F1 supplies inner borders. |
| Δ5 | C-F1-05 | `border-border/30` dividers | Use `border-[hsl(var(--border-subtle))]`. |
| Δ6 | C-F1-06 | `border-b border-border/50` between right-rail cards | Use `border-t border-border-subtle` (FU-5.8 hairline group divider). |
| Δ7 | C-F1-07 | `text-foreground/80` and `/60` opacity tweaks | Use straight `text-foreground` for brief preview / about narrative. Opacity tweaks only for "absent data" `/50`, `/40`. |
| Δ8 | C-F1-08 | MetricRow still has `h-[22px]` hardcoded | First commit of Block B flips `MetricRow.tsx:18-19` from `h-[22px]` → no explicit height (parent `data-table-grid` supplies `--row-h`). |
| Δ9 | C-F1-09 | `transition-[transform]` on AiBriefBanner chevron | Drop transition; F1 animation-policy arch test forbids. Instant flip. |

### §0.2 — F2 (entity ID) alignment

| # | Corner | Design says | Plan locks |
|---|--------|-------------|------------|
| Δ10 | C-F2-01 | Peer click → `/instruments/{peer.entity_id}` | Peer click → `router.push('/instruments/' + peer.ticker)`. Reuse F2 `TickerLink` primitive if shipped; otherwise plain `<Link>`. Multi-class via dot per F2. |
| Δ11 | C-F2-02 | Components take `entityId` prop | Rename all `entityId` props on this wave's new components to `instrumentId`. Internal KG layer still uses entity_id, but the React surface is unified. (`AiBriefBanner` exception — kept as `entityId` for API compat until v1.1 refactor.) |
| Δ12 | C-F2-03 | Brief cache key has `:user_id` suffix | DISCUSS-7 lock drops `:user_id`. Backend dep T-S8-06 (this wave) ships the cache-key change. |

### §0.3 — W1 (global shell) alignment

| # | Corner | Design says | Plan locks |
|---|--------|-------------|------------|
| Δ13 | C-W1-01 | Sticky header 36px (existing InstrumentHeader) | The 36px is page-local (sits BELOW W1's 32px global TopBar). Verify InstrumentHeader doesn't conflict with W1 contextual slots; if it does, shave to 28px in T-23. |
| Δ14 | C-W1-02 | Hotkey `B` toggles brief expand | Confirm page-scoped hotkeys reset on route change. If yes, no conflict with W2's `B`. If not, re-map to `Shift+B`. Verify in T-26. |
| Δ15 | C-W1-04 | Hotkey `1`/`5`/`30` → chart timeframe ("already exists") | **FALSE**: OHLCVChart.tsx:108 only binds Escape. Ship the numeric chord in T-25 (new keydown handler on the chart). |
| Δ16 | C-W1-06 | `AiBriefBanner` v2 rewrite for lazy generation | **W5 owns** `useInstrumentBrief(instrumentId)` hook at `components/instrument/hooks/useInstrumentBrief.ts`. W3 plan amended to consume, not produce (see §0.5). |

### §0.4 — W2 / W3 cross-wave alignment

| # | Corner | Design says | Plan locks |
|---|--------|-------------|------------|
| Δ17 | C-CX-01 | `/v1/instruments/{id}/peers?limit=5` | **W5 owns `/peers` endpoint.** W3 plan amended to consume `qk.instruments.peers(id)`. Ship in T-S9-01 + T-S2-01. |
| Δ18 | C-CX-02 | MetricsTable refactor deferred to "plan W4" | No W4 exists. Delete legacy MetricsTable single-column rows in this wave once `MetricGrid4Col` is verified (no feature flag — one wave, one cutover). |
| Δ19 | C-CX-04 | EarningsMiniList = last 4 quarters | The existing `getEarningsHistory` returns ANNUAL records. Rename to "Recent Annual Earnings" in v1; quarterly variant deferred to v1.1. EarningsMiniList renders 4 most recent annual records with EPS actual / est / surprise %. |
| Δ20 | C-CX-05 | Headline click → `ArticleDetailModal` | **ArticleDetailModal does NOT exist.** Use route navigation: `router.push('/news/' + article.id)` (existing news detail route — verify in pre-flight; if missing, add stub in T-22). |
| Δ21 | C-CX-06 | Hover tooltip uses `DataFreshnessTooltip` | **DataFreshnessTooltip does NOT exist.** Use F1 `DataFreshnessPill` primitive in-place (compact form) or wrap with shadcn `<Tooltip>` showing source + timestamp. |
| Δ22 | C-CX-07 | PeersStrip + W3 PeerComparisonTable both render peers | Both consume same `qk.instruments.peers(id)`. No backend duplication. W5 renders 3 cols (P/E, mkt cap, 1Y return); W3 renders 9 cols. |

### §0.5 — Cross-wave amendments required to W3 plan

When W5 ships, the W3 plan (`docs/plans/0089-pages/W3-instrument-financials-plan.md`) must be amended:

1. **Remove T-S9-03** (peers proxy) — W5 ships it instead.
2. **Remove T-S2-04** (peers SQL endpoint) — W5 ships it.
3. **Remove T-05** (`useInstrumentBrief` hook) — W5 ships it; W3 just imports.
4. **Remove T-S8-05** (lazy POST endpoint) — W5 ships it; W3 just calls.
5. **T-22 AIBriefPanel** still imports `useInstrumentBrief` but no longer defines it.

This amendment is non-breaking if W5 lands before W3 starts implementation. If both branches diverge concurrently, resolve at merge by deleting the duplicate definitions in favor of the W5 versions.

### §0.6 — Backend reality

| # | Corner | Design says | Plan locks |
|---|--------|-------------|------------|
| Δ23 | C-BE-01 | B-Q-1 `/peers` | Ship in T-S9-01 + T-S2-01 + T-S2-tests. ~30 + 60 LOC. |
| Δ24 | C-BE-02 | B-Q-2 `/intraday-stats` | Ship in T-S9-02 (S9 wrapper that composes OHLCV bars + technicals_snapshot section). Computes VWAP, ATR(14), RSI(14), GAP %, premarket high/low, short-interest delta. ~120 LOC. |
| Δ25 | C-BE-03 | B-Q-3 `/multi-period-returns` | Ship in T-S9-03 (S9 wrapper reading OHLCV bars; 7 anchor periods: 1D/5D/1M/3M/6M/YTD/1Y/5Y). `(close[anchor] / close[now]) - 1`. Render `—` if insufficient history. ~80 LOC. |
| Δ26 | C-BE-04 | B-Q-4 `/price-levels` | Ship in T-S9-04 (S9 wrapper computing classic floor pivots from prior-day OHLCV: `pivot=(H+L+C)/3`, R1/R2/R3/S1/S2/S3 derived). Returns 9 levels + MA50/MA200 vs current. Camarilla deferred. ~70 LOC. |
| Δ27 | C-BE-05 | B-Q-5 lazy variant `?lazy=true` | DISCUSS-7 contract is `POST /v1/briefings/instrument/{id}/generate` + GET poll. NOT a query-param variant. Ship POST endpoint in T-S8-05 (idempotent — returns 202 + brief_id if generation enqueued, 200 + cached brief if exists). |
| Δ28 | C-BE-06 | `intradayStats` staleTime = 60s | Set to `60s` only for active market hours; for after-hours, 5min. Use `lastBarTimestamp` in queryKey to invalidate on new bar. |
| Δ29 | C-BE-07 | Sentiment open Q-1 | Use existing categorical `RankedArticle.sentiment` (5 buckets: positive/negative/neutral/mixed/null). No numeric score. Map to F1 colors: positive→`text-positive`, negative→`text-negative`, mixed→`text-warning`, neutral/null→`text-muted-foreground`. |

### §0.7 — Component design refinements

| # | Corner | Plan locks |
|---|--------|------------|
| Δ30 | C-NEW-01 (responsive rail) | Tailwind: `w-[320px] xl:w-[380px]`. Breakpoint `xl` = 1280px. |
| Δ31 | C-NEW-02 (flex → grid) | First commit of Block B flips `QuoteTab.tsx` root from `flex` to `grid grid-cols-[minmax(0,1fr)_320px] xl:grid-cols-[minmax(0,1fr)_380px]`. No new components in same commit. |
| Δ32 | C-NEW-03 (chart min-height) | Chart min-height 320px (was 440px); document in OHLCVChart props. Single commit in Block B. |
| Δ33 | C-NEW-06 (ticker truncation) | Peer ticker `min-w-[60px]` to fit BRK.B / BF.B. |
| Δ34 | C-NEW-07 (cell width math) | Right rail = 380px. Inner padding 8px each side → 364px usable. 4 × 90px cells + 4px gap = 364px. Math locks. (For 320px breakpoint: 4 × 76px = 304px + 16px padding.) |
| Δ35 | C-NEW-09 (ETF empty description) | `CompanyAboutCard` renders name + exchange + "Description not available" muted on null description. Test with SPY + AAPL fixtures. |
| Δ36 | C-NEW-10 (Founded field) | Verify `General.Founded` exists on S9 fundamentals response. If absent, drop the line; if present, render. Field path: `fundamentals.general?.Founded`. |
| Δ37 | C-NEW-11 (cell count per block) | **24 cells visible** in Statistics grid: 4 cols × 6 rows × 3 blocks. Wireframe `§4.3` density math is correct (12 cells visible from VALUATION + first row of margins). Lock at 24 total but only 12 in view above-fold. |
| Δ38 | C-NEW-12 (cache cascade) | Verify `qk.instruments.detail(id)` is a prefix of `qk.instruments.peers(id)`, `intradayStats(id)`, `multiPeriodReturns(id)`, `priceLevels(id)`. Add U-XX test that `Shift+R` invalidates all sub-keys in one cascade. |
| Δ39 | C-NEW-13 (peer prefetch throttle) | Hover prefetch on `pointerenter` with 200ms delay (debounced); cancel on `pointerleave`. |
| Δ40 | C-NEW-14 (MetricsTable cutover) | Delete legacy single-column `MetricRow` consumers in same wave as `MetricGrid4Col` lands. No feature flag. |
| Δ41 | C-NEW-15 (tab content inset) | Strip `p-3` from QuoteTab root → `p-0`. Each panel owns its inset. |
| Δ42 | C-NEW-16 (density gate) | Vitest density gate: `expect(visibleCells).toBeGreaterThanOrEqual(80)`. Target 113. |
| Δ43 | C-NEW-17 (Playwright e2e) | 4 e2e tests — see §6.2. |
| Δ44 | C-NEW-18 (brief rate-limit) | On 429 from POST `/generate`, render "BRIEF quota exceeded — retry in N min" muted with `Retry-After` header parsed. |

**Deferred to v1.1** (NICE corners not absorbed): C-CX-03 (top_news dedup with W2 — already shared key, just confirm staleTime), C-F1-07 promotion (opacity tweaks — defer to v1.1 audit), C-NEW-05 (entity_id internal prop kept), C-NEW-08 (132px math confirmed), C-NEW-10 (Founded field tested), C-NEW-19 (InstrumentTabs height verified inline).

---

## §1. Bloomberg-grade resemblance checks (acceptance gate)

After this wave lands, the page MUST:

1. Above-fold cell count ≥ 80 on 1440×900 (target: 113).
2. Right rail = 380px on `xl` viewports, 320px on `lg`. No 40% / 576px relic.
3. QuoteTab root is CSS Grid (not flex). No `p-3` outer inset.
4. AiBriefBanner is ALWAYS visible — never returns `null`. Lazy-generate flow GET → POST `/generate` → poll on 404.
5. `MetricGrid4Col` renders 24 cells (4 × 6) in Statistics — VALUATION (8) / MARGINS (8) / LEVERAGE+YIELD (8).
6. Snapshot grid + insider list + earnings list + news list all wear `data-table-grid` (20px) or `data-table-grid="dense"` (18px).
7. CompanyAboutCard renders sector + industry + HQ + employees (+ founded if available) + 3-line description with "more".
8. `gics_sector` micro-pill in InstrumentHeader next to company name.
9. MultiPeriodReturnsStrip renders 7 periods (1D/5D/1M/3M/YTD/1Y/5Y).
10. IntradayStatsBand renders 6 stats (VWAP / ATR / RSI / GAP / PREM / SI Δ).
11. BottomTripleStrip renders 3 columns: Peers (5 rows) / PriceLevels (7 rows) / WhatsMoving (3 rows).
12. Insider list shows top 5 transactions (18px rows).
13. Earnings list shows last 4 annual records with surprise % chip.
14. Related headlines list shows top 5 entity-tagged news with sentiment color dot.
15. Peer row click → `/instruments/{peer.ticker}` (F2 lock).
16. Peer row hover (200ms debounce) prefetches peer page-bundle.
17. Chart timeframe hotkeys `1` / `5` / `30` switch to 1D / 5D / 30D.
18. `Shift+R` cascades invalidation across all `qk.instruments.detail(id)` sub-keys.
19. `B` toggles brief expand; `D` toggles description expand.
20. No `rounded-*` on panels (F1 rounded=0 lock).
21. No `text-[9px]` body labels (F1 floor 10px).
22. Arch tests pass: `no-off-palette-colors`, `data-table-grid-scope`, `animation-policy`, `empty-copy-dictionary`, `no-rounded`.
23. Vitest density test: ≥ 80 visible cells in full QuoteTab render.
24. 4 Playwright e2e tests pass.
25. Brief banner handles 429 rate-limit with "quota exceeded — retry in N min".
26. ETF (SPY) renders gracefully — CompanyAboutCard shows "Description not available" muted, EarningsMiniList shows "No earnings history (ETF / fund)".

---

## §2. Pre-flight (verify before writing any code)

1. `git log --oneline -25` — confirm F1, F2 (and ideally W1) shipped.
2. `rg "MetricCell|Sparkline|DataFreshnessPill" apps/worldview-web/components/primitives/` — confirm F1 primitives.
3. `rg "TickerLink" apps/worldview-web/components/instruments/` — confirm F2 primitive; if absent, peer rows use plain `<Link>`.
4. `rg "qk.instruments.detail|qk.instruments.brief|qk.instruments.peers" apps/worldview-web/lib/query/keys.ts` — confirm namespace + brief key exists; peers key is new.
5. `rg "data-table-grid" apps/worldview-web/app/globals.css` — confirm CSS rules.
6. Read `apps/worldview-web/components/instrument/tabs/InstrumentTabs.tsx` — confirm `q`/`f`/`i` chord registration; check scope-on-route-change behavior.
7. `git grep "/peers\|/intraday-stats\|/multi-period-returns\|/price-levels" services/api-gateway/ services/market-data/` — confirm endpoints DO NOT exist (this wave ships them).
8. `git grep "briefings/instrument" services/api-gateway/src/api_gateway/routes/chat.py` — confirm GET endpoint; check whether POST `/generate` exists (DISCUSS-7 may have shipped it earlier).
9. `find apps/worldview-web -name "ArticleDetailModal*"` — confirm ZERO matches.
10. `find apps/worldview-web -name "DataFreshnessTooltip*"` — confirm ZERO matches.
11. `find apps/worldview-web/app -name "page.tsx" -path "*news*"` — confirm news detail route exists (for Δ20 fallback); if absent, T-22 ships stub.
12. Read `docs/plans/0089-pages/W3-instrument-financials-plan.md` §3 + §4 — confirm cross-wave amendments (§0.5) are still required at execution time.
13. Read `docs/designs/0089/05-instrument-quote.md` fully — the plan is layered on top.
14. Read `docs/designs/0089/oq/05-instrument-quote-CORNERS-AUDIT.md` for corner-by-corner rationale.

If any check fails, stop and report — don't improvise.

---

## §3. Backend dependencies (Wave 5 ships these)

| ID | Service | Change | LOC est. |
|----|---------|--------|----------|
| T-S2-01 | market-data | `GET /v1/instruments/{id}/peers?limit=5` — SQL: top-N market-cap peers in same `gics_industry`, 24h cache. Returns `[{instrument_id, ticker, name, market_cap, pe_ratio, return_1y, change_pct}]`. | ~80 |
| T-S2-02 | market-data | Verify `General.Founded` field surfaces on `/fundamentals/{id}` response (Δ36). If filtered out by serializer, expose it. | ~10 |
| T-S9-01 | api-gateway | Proxy `GET /v1/instruments/{id}/peers` → S2 `/peers` | ~20 |
| T-S9-02 | api-gateway | NEW `GET /v1/fundamentals/{id}/intraday-stats` — composes OHLCV bars + technicals_snapshot. Computes VWAP / ATR(14) / RSI(14) / GAP % / premarket high-low / SI Δ. | ~120 |
| T-S9-03 | api-gateway | NEW `GET /v1/fundamentals/{id}/multi-period-returns` — reads OHLCV bars, computes close-on-close returns over 7 anchor periods. Renders `—` for insufficient history. | ~80 |
| T-S9-04 | api-gateway | NEW `GET /v1/fundamentals/{id}/price-levels` — classic floor pivots from prior-day OHLCV. Returns 9 levels (R3/R2/R1/PIVOT/S1/S2/S3 + MA50/MA200) with arrow vs current price. | ~70 |
| T-S8-05 | rag-chat | NEW `POST /v1/briefings/instrument/{id}/generate` — idempotent: 200 + cached brief if exists, 202 + brief_id if enqueued. Rate-limit per user (60/hour) → 429 + Retry-After. (DISCUSS-7 lock.) | ~100 |
| T-S8-06 | rag-chat | Drop `:user_id` suffix from `briefing:instrument:v2:` cache key (DISCUSS-7). | ~5 |
| T-S9-07 | api-gateway | Tests for T-S9-01..04 (4 route tests in `tests/test_routes.py`) | ~80 |
| T-S2-08 | market-data | Tests for T-S2-01 (peer endpoint unit + integration) | ~80 |

**Total backend LOC**: ~645. **Estimated**: 2 days backend + 5 days frontend = 7 days serial. Parallelize: 1 backend agent + 1 frontend agent → ~4.5 days wall-clock.

---

## §4. File-by-file frontend change set (each sub-step = one commit)

### Block A — Foundation (primitives + hooks + keys)

**T-01 (EDIT)** `apps/worldview-web/lib/query/keys.ts` — add 4 new keys under `qk.instruments.*`:
- `peers: (id) => [QK_VERSION, "instruments", "detail", id, "peers"]`
- `intradayStats: (id, lastBarTs?) => [QK_VERSION, "instruments", "detail", id, "intraday-stats", lastBarTs ?? "live"]`
- `multiPeriodReturns: (id) => [QK_VERSION, "instruments", "detail", id, "multi-period-returns"]`
- `priceLevels: (id) => [QK_VERSION, "instruments", "detail", id, "price-levels"]`

**T-02 (EDIT)** `apps/worldview-web/lib/api/instruments.ts` — add 4 methods: `getPeers(id, limit=5)`, `getIntradayStats(id)`, `getMultiPeriodReturns(id)`, `getPriceLevels(id)`.

**T-03 (EDIT)** `apps/worldview-web/lib/api/dashboard.ts` (or wherever `getInstrumentBrief` lives) — add `triggerInstrumentBriefGeneration(id): Promise<{status: "queued"|"cached", brief_id?: string}>`. Calls POST `/v1/briefings/instrument/{id}/generate`. Handle 429 by parsing `Retry-After`.

**T-04 (NEW)** `apps/worldview-web/components/instrument/hooks/useInstrumentBrief.ts` — GET → 404 → POST `/generate` → poll GET every 30s up to 5 attempts → 429 handling → error fallback. Returns `{ data, status: "loading"|"generating"|"unavailable"|"ready"|"quota-exceeded", retryAfter? }`.

**T-05 (NEW)** `apps/worldview-web/components/instrument/hooks/useQuoteSidebarData.ts` — fetches `peers / intradayStats / multiPeriodReturns / priceLevels / insider / earnings / entityNews` in parallel via TanStack. Returns the merged object + per-resource isLoading.

### Block B — Layout pivot (flex → grid; chart shrink)

**T-06 (EDIT)** `apps/worldview-web/components/instrument/quote/QuoteTab.tsx` — root: `flex` → `grid grid-cols-[minmax(0,1fr)_320px] xl:grid-cols-[minmax(0,1fr)_380px]`. Strip `p-3` outer inset. ALL existing children rewired inside the grid; no new components in this commit. (Pure layout pivot.)

**T-07 (EDIT)** `apps/worldview-web/components/instrument/chart/OHLCVChart.tsx` — chart min-height 440px → 320px. Add `1`/`5`/`30` keydown chord (window-scoped, page-guarded — release on unmount).

**T-08 (EDIT)** `apps/worldview-web/components/instrument/quote/metrics/MetricRow.tsx` — drop `h-[22px]` hardcode. Parent `data-table-grid` supplies row height (Δ8).

### Block C — Strips (4 horizontal bands below the chart)

**T-09 (NEW)** `apps/worldview-web/components/instrument/quote/strips/MultiPeriodReturnsStrip.tsx` (≤110 LOC) — 7 cells, 22px height, semantic colors, `text-[10px]` labels, `text-[11px] font-mono tabular-nums` values. Fetches T-S9-03. `data-table-grid` parent.

**T-10 (NEW)** `apps/worldview-web/components/instrument/quote/strips/IntradayStatsBand.tsx` (≤130 LOC) — 6 cells, same density. Fetches T-S9-02. Hides PREM cell after-hours (Δ — design §7.4 empty state).

**T-11 (EDIT)** `apps/worldview-web/components/instrument/SessionStatsStrip.tsx` — verify 22px tight; no behavioral change.

### Block D — About card + sector pill

**T-12 (NEW)** `apps/worldview-web/components/instrument/quote/about/CompanyAboutCard.tsx` (≤160 LOC) — sector + industry + HQ + employees + (founded?) + 3-line description with "more" toggle. ETF empty state (Δ35). `data-table-grid` for the 5-row stat block; description below the grid.

**T-13 (EDIT)** `apps/worldview-web/components/instrument/header/InstrumentHeader.tsx` — add `gics_sector` micro-pill next to company name (1 line; `text-[10px] uppercase text-muted-foreground`).

### Block E — Right rail Statistics grid

**T-14 (NEW)** `apps/worldview-web/components/instrument/quote/metrics/MetricGrid4Col.tsx` (≤90 LOC) — generic 4×N grid, takes `cells: Array<{label, value, color}>`, wears `<div data-table-grid>`. Per-cell uses F1 `MetricCell` primitive.

**T-15 (EDIT)** `apps/worldview-web/components/instrument/quote/metrics/MetricsTable.tsx` — refactor: first 24 rows (valuation + margins + leverage/yield) → 3 × `MetricGrid4Col` blocks. Keep 52W bar + AnalystMiniBar + Target row + ownership section unchanged below.

### Block F — Right rail mini-cards (insider / earnings / news)

**T-16 (NEW)** `apps/worldview-web/components/instrument/quote/insider/InsiderActivityList.tsx` (≤140 LOC) — top 5 from `qk.instruments.ownership(id)` (page-bundle seed). 18px rows via `<div data-table-grid="dense">`.

**T-17 (NEW)** `apps/worldview-web/components/instrument/quote/earnings/EarningsMiniList.tsx` (≤130 LOC) — last 4 ANNUAL records from `getEarningsHistory` (Δ19). 18px rows. EPS actual / est / surprise % chip colored by sign.

**T-18 (NEW)** `apps/worldview-web/components/instrument/quote/news/RelatedHeadlinesList.tsx` (≤150 LOC) — top 5 from `getEntityNews(entityId)`. 18px rows. Sentiment dot (Δ29 — categorical mapping). Click → `router.push('/news/' + article.id)` (Δ20).

### Block G — Bottom triple strip

**T-19 (NEW)** `apps/worldview-web/components/instrument/quote/bottom/PeersStrip.tsx` (≤150 LOC) — 5 rows × {ticker (min-w-60px Δ33), P/E, mkt cap, 1Y return}. Fetches T-S9-01. Hover (200ms debounce) prefetches peer page-bundle (Δ39). Click → `/instruments/{peer.ticker}` (Δ10).

**T-20 (NEW)** `apps/worldview-web/components/instrument/quote/bottom/PriceLevelsStrip.tsx` (≤130 LOC) — 7 levels + MA50/MA200 with ↑/↓ vs current. Fetches T-S9-04.

**T-21 (NEW)** `apps/worldview-web/components/instrument/quote/bottom/WhatsMovingStrip.tsx` (≤110 LOC) — top 3 from `bundle.top_news` (zero extra fetch). Sentiment dot (Δ29). Click → news route.

**T-22 (NEW)** `apps/worldview-web/components/instrument/quote/bottom/BottomTripleStrip.tsx` (≤60 LOC) — pure 3-column layout wrapper hosting the 3 above.

### Block H — Brief banner + news route stub

**T-23 (EDIT)** `apps/worldview-web/components/instrument/brief/AiBriefBanner.tsx` — rewrite to use `useInstrumentBrief(id)` (T-04). Render "BRIEF · Generating…" (loading), "BRIEF · unavailable" (5xx + final timeout), "BRIEF · quota exceeded — retry in Nm" (429), "BRIEF · no news in last 90 days" (empty), preview text (success collapsed), full narrative (success expanded). Drop the `transition-[transform]` chevron (Δ9).

**T-24 (NEW conditional)** `apps/worldview-web/app/(app)/news/[id]/page.tsx` — stub article detail page (if pre-flight 11 shows absent). Renders title + body + source link from `getArticleById` (verify endpoint).

### Block I — Orchestrator wiring + hotkeys

**T-25 (EDIT)** `apps/worldview-web/components/instrument/quote/QuoteTab.tsx` — wire all new components into the 7-row left grid + right rail stack. Pass props through (`instrumentId`, `entityId` only where required). Replace existing `MetricsTable` rendering with new layout.

**T-26 (EDIT)** `apps/worldview-web/components/instrument/tabs/InstrumentTabs.tsx` — register Quote-tab-scoped chords `B` (brief expand), `D` (description expand), `P` (peers focus), `Shift+R` (refetch). Verify page-scope reset behavior (Δ14); if not page-scoped, prefix with `Shift+`.

**T-27 (EDIT)** `apps/worldview-web/components/instrument/InstrumentPageClient.tsx` — confirm AiBriefBanner still mounted; no behavioral change but bundle-seed insider key alignment.

### Block J — Arch tests + density gates + e2e

**T-28 (EDIT)** `apps/worldview-web/__tests__/architecture/data-table-grid-scope.test.ts` — verify Quote tab surfaces are in allowlist (already present per F1 §16.3).

**T-29 (NEW)** `apps/worldview-web/__tests__/instrument/quote-density.test.ts` — Vitest: render QuoteTab with mocks → assert ≥ 80 visible data cells (Δ42).

**T-30 (NEW)** unit tests for T-04, T-05, T-09..T-23 components — minimum 1 test per: empty / populated / error / interaction.

**T-31 (NEW)** `apps/worldview-web/e2e/instrument-quote.spec.ts` — 4 Playwright tests:
1. AAPL Quote tab renders ≥ 80 cells above-fold.
2. Peer row click → `/instruments/MSFT` (F2 ticker URL).
3. `Shift+R` cascades cache invalidation (verify network panel).
4. Brief banner lazy-generate flow (mock 404 → POST → 202 → poll → 200).

---

## §5. Hotkeys (Quote-tab scope only)

| Chord | Action | Scope |
|-------|--------|-------|
| `B` | Toggle brief banner expand | Quote tab |
| `D` | Toggle company description expand | Quote tab |
| `P` | Focus PeersStrip (arrow keys cycle; Enter navigates) | Quote tab |
| `1` / `5` / `30` | Chart timeframe → 1D / 5D / 30D | Quote tab |
| `Shift+R` | Invalidate `qk.instruments.detail(id)` cascade | Quote tab |
| `Esc` | Close any overlay / exit chart fullscreen | All tabs |

Tab-switch `q` / `f` / `i` remain owned by InstrumentTabs.

---

## §6. Tests

### 6.1 Unit (Vitest) — 18 tests

| # | File | Asserts |
|---|------|---------|
| U-1 | `__tests__/instrument/quote-density.test.ts` (T-29) | ≥ 80 cells in full QuoteTab render |
| U-2 | `components/instrument/hooks/__tests__/useInstrumentBrief.test.ts` | GET→404→POST→poll up to 5 attempts; 429 with Retry-After |
| U-3 | `components/instrument/hooks/__tests__/useQuoteSidebarData.test.ts` | 7 queries fire, shared cache dedup |
| U-4..U-7 | strips (MultiPeriodReturnsStrip, IntradayStatsBand, etc.) | renders 7 / 6 cells with semantic colors |
| U-8 | `quote/about/__tests__/CompanyAboutCard.test.tsx` | ETF empty / AAPL populated / "more" toggle |
| U-9 | `quote/metrics/__tests__/MetricGrid4Col.test.tsx` | renders 8 cells in 4×2; null cells show `—` |
| U-10..U-12 | mini-cards | renders 5/4/5 rows + empty states |
| U-13..U-15 | bottom strips (Peers, PriceLevels, WhatsMoving) | render + click + hover behaviors |
| U-16 | `brief/__tests__/AiBriefBanner.test.tsx` | lazy-generate flow integration |
| U-17 | `__tests__/instrument/cache-cascade.test.ts` | Shift+R invalidates all 4 sub-keys |
| U-18 | `header/__tests__/InstrumentHeader.test.tsx` | sector pill renders when gics_sector present |

### 6.2 Playwright e2e

T-31 above (4 tests).

### 6.3 Backend tests

| # | File | Asserts |
|---|------|---------|
| B-1 | `services/api-gateway/tests/test_routes.py` | `/peers` proxies to S2 |
| B-2 | `services/api-gateway/tests/test_routes.py` | `/intraday-stats` returns 6-field shape |
| B-3 | `services/api-gateway/tests/test_routes.py` | `/multi-period-returns` returns 7 anchor periods |
| B-4 | `services/api-gateway/tests/test_routes.py` | `/price-levels` returns 9 levels |
| B-5 | `services/market-data/tests/test_peers.py` | top-5 by market cap in same GICS industry, excludes self |
| B-6 | `services/rag-chat/tests/test_lazy_briefings.py` | POST `/generate` returns 202 + brief_id when missing, 200 + cached when present, 429 + Retry-After on rate-limit |

---

## §7. Acceptance criteria

The 26 checks in §1 are the gates.

---

## §8. Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R-1 | W3 plan still tries to ship `/peers` and `useInstrumentBrief` after this wave does | HIGH | HIGH | Amend W3 plan §3 + §4 BEFORE either wave starts implementation (see §0.5). If both branches diverge, resolve at merge by deleting W3 duplicates. |
| R-2 | T-S9-02 intraday-stats VWAP computation is wrong on partial-day bars | MEDIUM | MEDIUM | Use cumulative `Σ(price × volume) / Σ(volume)` formula; add B-2 test fixture with mid-day bar. |
| R-3 | T-S8-05 lazy generate enqueue job uses dual writes (DB + Kafka) without outbox | MEDIUM | HIGH | Use existing rag-chat outbox pattern. Verify before merging. |
| R-4 | Chart numeric chord 1/5/30 collides with W1 global numeric chords (e.g. tab switch) | LOW | MEDIUM | Pre-flight 6 verifies; if collision, gate on Quote tab scope. |
| R-5 | `/news/{id}` detail route does not exist | MEDIUM | LOW | T-24 ships stub. Stub reads `getArticleById` — verify endpoint exists in pre-flight 11. |
| R-6 | `General.Founded` field absent from S9 response | MEDIUM | LOW | Drop the line silently if null. T-S2-02 ships a 10-LOC fix if filter is the cause. |
| R-7 | Peer prefetch on hover bloats network panel during demo | LOW | LOW | 200ms debounce + cancel on pointerleave (Δ39). Only fires for sustained hover. |

---

## §9. Files touched (forecast)

**New** (~24):
- 11 components (strips + about + grid + mini-cards + bottom strips + triple wrapper)
- 2 hooks (`useInstrumentBrief`, `useQuoteSidebarData`)
- 1 stub route (news detail)
- 1 density test + 1 e2e spec + 6 backend test files

**Modified** (~10):
- QuoteTab.tsx (grid pivot + wiring, ~200 LOC net)
- OHLCVChart.tsx (min-height + hotkeys, ~30 LOC)
- MetricRow.tsx (drop h-[22px], ~3 LOC)
- AiBriefBanner.tsx (lazy-generate rewrite, ~80 LOC)
- InstrumentHeader.tsx (sector pill, ~5 LOC)
- MetricsTable.tsx (refactor to 3 MetricGrid4Col blocks, ~80 LOC)
- InstrumentTabs.tsx (chord registration, ~30 LOC)
- lib/query/keys.ts (4 new keys, ~10 LOC)
- lib/api/instruments.ts (4 new methods, ~50 LOC)
- lib/api/dashboard.ts (triggerInstrumentBriefGeneration, ~20 LOC)
- 4 backend route files (api-gateway routes + market-data peer query + rag-chat generate endpoint)

**Deleted** (~0):
- None — `MetricsTable` is refactored not deleted. Legacy `MetricRow` consumers in `MetricsTable.tsx` are replaced by `MetricGrid4Col` in T-15.

**Net LOC**: ~+2400 / -180.

---

## §10. Estimation

| Block | Days |
|-------|------|
| Backend (T-S2-01/02, T-S9-01/02/03/04, T-S8-05/06, B-1..6) | 2.0 |
| Block A — Foundation (T-01..05) | 0.5 |
| Block B — Layout pivot (T-06..08) | 0.5 |
| Block C — Strips (T-09..11) | 0.5 |
| Block D — About card + sector pill (T-12..13) | 0.5 |
| Block E — Right rail Statistics grid (T-14..15) | 0.75 |
| Block F — Mini-cards (T-16..18) | 1.0 |
| Block G — Bottom triple (T-19..22) | 0.75 |
| Block H — Brief banner + news route (T-23..24) | 0.5 |
| Block I — Orchestrator + hotkeys (T-25..27) | 0.25 |
| Block J — Arch tests + density gates + e2e (T-28..31) | 0.5 |
| Validation gate + QA + deploy | 0.25 |
| **Total serial** | **8.0** |
| Parallel wall-clock (1 backend + 1 frontend) | **4.5** |

---

## §11. Rollback plan

Per-commit revert. The ~36 commits are independent enough that any single one can be backed out. The riskiest:

- **T-06 (flex → grid pivot)** — if the layout breaks, this is the single commit to revert. Sub-component commits T-09..T-22 are independent and survive.
- **T-23 (AiBriefBanner rewrite)** — if the lazy-generate flow breaks, revert this commit and the banner falls back to the legacy `return null` behavior (the bug we're fixing, but not page-breaking).
- **T-15 (MetricsTable refactor)** — if the new grid breaks, revert and the legacy 26-row table renders.

If the entire wave needs to roll back, `git revert <first>..<last> --no-commit` and ship a single revert PR.

---

## §12. Out of scope (deferred to v1.1+)

- Camarilla pivots toggle (open Q-3).
- Manual peer override (FU-7.5 deferred to v1.1).
- Quarterly EarningsMiniList variant (Δ19 — v1 ships annual only).
- ArticleDetailModal (Δ20 — v1 routes to `/news/{id}` page).
- DataFreshnessTooltip dedicated primitive (Δ21 — v1 reuses DataFreshnessPill + shadcn Tooltip).
- Per-user brief generation rate-limit telemetry (open Q-5 — v1 ships fixed 60/hr; tune later).
- Sticky multi-period + intraday strips on scroll (open Q-6 — v1 non-sticky).
- Mobile / tablet stacked variant (open Q-7 — desktop only).
- Page-bundle expansion to include peers / intradayStats / etc. (§8.4 — defer; per-resource hooks are sufficient).

---

## §13. Definition of Done

1. All 26 acceptance checks in §1 pass.
2. All 18 unit tests + 4 e2e tests + 6 backend tests pass.
3. All 4 arch tests pass (`no-off-palette-colors`, `data-table-grid-scope`, `animation-policy`, `empty-copy-dictionary`).
4. `pnpm --filter worldview-web typecheck` + `lint` pass with zero errors.
5. Containers `worldview-web` + `api-gateway` + `market-data` + `rag-chat` rebuilt and healthy.
6. Live walk-through against `/instruments/AAPL` confirms: 113-cell density, lazy brief flow, peer prefetch, all 7 left-column rows, all 13 right-rail rows.
7. Live walk-through against `/instruments/SPY` (ETF) confirms graceful empty states (no description, no earnings).
8. W3 plan amendment (§0.5) applied — duplicate peer endpoint + brief hook removed.
9. Memory updated with W5 state.
10. Commit log clean (one commit per T-NN sub-step, ~36 commits).
