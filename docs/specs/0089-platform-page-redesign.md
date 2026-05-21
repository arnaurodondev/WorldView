---
id: PRD-0089
title: Platform-wide Bloomberg-Grade UI Redesign
status: active
created: 2026-05-20
locked: 2026-05-20
parent_design_corpus: docs/designs/0089/
decisions_index: docs/designs/0089/oq/_DECISIONS.md
supersedes_partial: PRD-0088 (instrument detail — extended, not replaced)
platform_state: pre-production
no_backfill: true
waves_shipped:
  - F1 (2026-05-20): design-system foundation — sharp corners, primitives catalogue, 4-tier animation policy. Branch `feat/plan-0089-f1`.
  - F1.1 (2026-05-20): close-out amendment — purged ~230 surviving off-token utilities (text-*, shadow-*, transition-*, duration-*, gap-*), shipped 3 dedicated architecture tests (animation-policy, empty-copy-dictionary, data-table-grid-scope), and activated the F1 lockdown describe block. Branch `feat/plan-0089-f1`.
  - F2 (2026-05-20): entity / instrument ID unification — collapsed the dual-id namespaces into a single canonical UUID per tradable security (`entity_id == instrument_id` for `entity_type = 'financial_instrument'`); non-tradable kinds keep an independent `entity_id`. Reused existing `canonical_entities.entity_type` column as the discriminator (no new `kind` column added). Deleted ~268 LOC of translation logic from `services/api-gateway/src/api_gateway/clients.py` (120 LOC Step 3 + ~148 LOC bundle Phase 1→2 re-read). Flipped frontend URLs from UUIDs to tickers (`/instruments/${TICKER}`) with case-canonical 301 + alias 301 middleware. M-017 invariant now enforced by CI (`services/knowledge-graph/tests/integration/test_m017_invariant.py`). Closed BP-342, BP-373, BP-374. New [ADR-F-16](../architecture/decisions/ADR-F-16-instrument-entity-id-unification.md) supersedes ADR-F-12 (PRD-0027 §1367). Branch `feat/plan-0089-f2`. Commits: `1dbf6d74, 4000ac1c, 3204e7bc, 2736e538, 26ba1ee7, be1d36c4, eeb97d1c, 1da9ae45, 503ab715, af4785a5, bea77cdc, 61ada182, 840e99b6`. 11 known deviations / follow-ups documented in the ADR (e.g. `make seed-verify-m017` sh-syntax bug; 631 legacy foreign canonicals from migration 0009; alias-301 deferred until S9 exposes unauthenticated alias endpoint).
  - W1 (2026-05-20): Global Shell — TopBar replaces the animated TopBarMarquee with a new IndexStrip (SPY/QQQ/IWM/VIX/DIA/TLT/^TNX/BTC-USD/GLD/USO), composes 17 information slots including the new always-visible PortfolioSwitcher chip (ROOT default per DISCUSS-1) with DemoBadge support. **Note**: W1 originally shipped a STATIC IndexStrip per DISCUSS-1 / V2; the W1.1 H-001 commit (461e81ca) restored the marquee per direct user feedback, so the shipped behaviour is now a 10-cell horizontally-scrolling marquee at 6s/cell (60s cycle), pause-on-hover, `prefers-reduced-motion`-safe via duplicate-pass hide. Plan §1 V2 + V20 (priority-drop) are therefore superseded — see W1.1 H-001 commit message for full justification. CollapsibleSidebar tightens to 200px (was 220) with hairline `border-border-subtle` dividers + multi-tab `storage` event sync. WatchlistPanel adopts `data-table-grid` (20px rows), trend-tinted Sparkline column, ticker-URL routing (C-08), server-driven FreshnessDot, ohlcvBatch fetch (FU-4.1), and the `mod+shift+w` add chord. StatusBar collapses to 22px (was 24) with the `border-border-subtle` top border, live WS dot from `useAlertStream().isConnected`, and `MARKET CLOSED` override on weekends (C-20). AskAiPanel adopts the F1 `InlineCitationAnchor` + `AiContentRail` primitives, deleting ~310 LOC of duplicate citation parsing. New stub routes `/indices/[ticker]` (`/watchlists` already existed as a full PLAN-0059 I-1 implementation). Layout adds skip-to-content link, sticky 24px ForceUpdateBanner above TopBar (C-25), Sonner Toaster at top-right z-60 (FU-10.3), and visibility-driven refetch-interval pause (C-22). Architecture tests extended to ban `border-white/[` and the three deleted marquee components. Branch `feat/plan-0089-w1`. Commits: `f7c5ab49 chore preflight, 929795c8 index-strip, 7597093a portfolio-switcher, 20ff6566 topbar, 0f8c7fc0 sidebar, 09eda1e6 watchlist + 2ce5700e followup, da20220f statusbar, 179c6ea8 askai, 798413c1 indices-stub, 10b0b326 layout, 29861453 cleanup, 10ed7188 arch-test, 6379cda5 e2e specs`. Deviations: /watchlists stub skipped (full page already existed at 196 LOC); `useIdleLock().locked` interpreted as `document.visibilityState === "hidden"` since the existing hook redirects on idle instead of exposing a locked flag.
---

> **🚨 Platform constraint — applies to every wave under this PRD.** No
> real instance is running. No production data, no live users, no backfill
> required. Schema migrations are schema-only. Reset = `docker compose down -v`.
> See `_DECISIONS.md §I` for the full implications.

# PRD-0089 — Platform-wide Bloomberg-Grade UI Redesign

> **Scope rule.** This PRD is the iteration anchor that pulls together the
> 11 per-page design docs in `docs/designs/0089/`. The detail lives in the
> design docs; this PRD captures cross-cutting decisions, the agreed
> contract, the consolidated open-question backlog, and the wave plan.

## 1. Problem

After PLAN-0090 shipped the instrument detail redesign, the user reviewed
every page on the live platform (`fix/ci-failures-cleanup` branch, post
my 2026-05-19 fixes) and flagged five class-of-defects:

1. **Information density is below the Bloomberg/Finviz/TradingView floor.**
   Row heights of 28–36px, generous `p-4` panel padding, fonts mostly
   `text-sm` (14px) or `text-base` (16px). A 1440×900 viewport surfaces
   ~10–15 metric cells where competitors surface 40–60.
2. **Real-estate is wasted on empty regions.** Specifically: the
   Financials right-sidebar shows the analyst consensus bar + 12-MO
   target then ~600px of black space. The Quote tab right-rail bottoms
   out after 28 rows and leaves ~300px unused.
3. **Context surfaces the user expects have disappeared.** The old
   instrument page rendered company description, sector, industry, and
   an AI-generated brief. PLAN-0090's T-E-01 deletion pass swept these
   out. The data is still in the backend bundle (`Instrument.description`,
   `gics_sector`, `gics_industry`) and a brief endpoint exists
   (`/v1/briefings/instrument/{id}`) but neither is wired into the new UI.
4. **User positions are not scannable on Portfolio Overview.** A
   hedge-fund PM lands on the page and cannot in 5 seconds answer:
   "What do I hold, what's working, what's broken?"
5. **Backend surfaces are produced but never rendered.** The audit in
   `00-backend-data-inventory.md` found 75 specific fields the backend
   exposes that no page currently displays — institutional holders,
   insider transactions, multi-hop entity paths, structured brief
   sections, contradictions, prediction-market bid/ask depth, etc.

The fix is not a single page redesign. It's a coordinated tightening of
the entire shell + every primary page, with rules every component
honours, and explicit restoration of the missing context surfaces.

## 2. Users

Same personas as PRD-0088 (hedge-fund PM, quant analyst, risk officer,
institutional trader) plus, for the post-MVP web build, the
sophisticated retail user who has Bloomberg/IBKR muscle memory but no
seat license. All four personas share one expectation: **density per
square inch is a feature, not a bug.**

## 3. Functional requirements

Each surface has its own functional spec — kept in the per-page design
doc to avoid this PRD becoming the world's largest file. The matrix
below summarises what each surface must do; refer to the design doc for
the layout, components, data sources, and visual numerics.

| # | Surface | Design doc | Density target | Key restorations |
|---|---------|-----------|----------------|------------------|
| FR-1 | Global shell (TopBar, sidebar, watchlist, status bar) | [01-global-shell.md](../designs/0089/01-global-shell.md) | 17 TopBar slots / 8-row watchlist | Watchlist sparklines; market-strip cells; chord scope contract |
| FR-2 | Dashboard | [02-dashboard.md](../designs/0089/02-dashboard.md) | 262 cells | "Top of Portfolio" mega-cell with positions table |
| FR-3 | Portfolio Overview | [03-portfolio-overview.md](../designs/0089/03-portfolio-overview.md) | 281 cells | 14-col holdings table, 22px rows, sparkline col |
| FR-4 | Portfolio Holdings drilldown + Tx ledger + Analytics | [04-portfolio-detail.md](../designs/0089/04-portfolio-detail.md) | 32 tx rows / 430 cells | Slide-over holding detail; full risk/attribution analytics tab |
| FR-5 | Instrument Quote tab | [05-instrument-quote.md](../designs/0089/05-instrument-quote.md) | 113 cells | AI brief (fix `null`-when-empty), CompanyAboutCard, peers, price levels |
| FR-6 | Instrument Financials tab | [06-instrument-financials.md](../designs/0089/06-instrument-financials.md) | 172 cells | 7-panel sidebar (Analyst/Target/Revisions/Beat-Miss/AI Brief/Company Snapshot/Targets-by-firm) |
| FR-7 | Instrument Intelligence tab | [07-instrument-intelligence.md](../designs/0089/07-instrument-intelligence.md) | 30 news + 10 relations + 3 paths | Structured brief; full right-rail (overview/relations/paths/contradictions); depth-adaptive timeout |
| FR-8 | Screener | [08-screener.md](../designs/0089/08-screener.md) | 20 rows × 12 cols | Filter chips + popover; preset bar; live result count |
| FR-9 | Workspace | [09-workspace-predictions-alerts.md §A](../designs/0089/09-workspace-predictions-alerts.md) | 220 cells across 4 panels | Crosshair-sync toggle; Ctrl+1..9 layout swaps |
| FR-10 | Predictions | [09-...md §B](../designs/0089/09-workspace-predictions-alerts.md) | 30 markets with sparkline | Right-drawer detail (576px) with history + bid/ask |
| FR-11 | Alerts | [09-...md §C](../designs/0089/09-workspace-predictions-alerts.md) | 33 rows + 3 group headers | Severity char badges + IBKR-style opt-in payload row |
| FR-12 | Chat / AI panel | [10-chat-ai.md](../designs/0089/10-chat-ai.md) | 40+ cells | Flat 11px text (no bubbles); inline `[cN]` anchors + hovercards; ContextRail for citations/contradictions |

**FR-13 — Shared.** A small set of reusable primitives (`TableRow22`,
`MetricCell11`, `Sparkline`, `SeverityCharBadge`, `BulkActionToolbar`,
`SectionDivider`, `MetricLabel`, `MetricValue`) is introduced once and
reused across every surface. Naming and props are defined in
§5 of `09-workspace-predictions-alerts.md` (the late agent that did the
cross-page rollup).

## 4. Non-functional requirements

| ID | Requirement | Measurable target |
|----|------------|-------------------|
| NFR-1 | Density floor | Every primary page surfaces ≥ 40 visible data cells above the fold at 1440×900 |
| NFR-2 | Typography ceiling | No `text-base` (16px) inside dense tables; default body 11px |
| NFR-3 | Row-height ceiling | Tabular row height ≤ 22px; ≤ 20px in transactions/ledgers; never 36px |
| NFR-4 | Padding ceiling | Container padding ≤ `p-3` (12px); table-cell padding ≤ `px-2` |
| NFR-5 | Palette compliance | Architecture test `__tests__/architecture/no-off-palette-colors.test.ts` must pass with no exceptions |
| NFR-6 | Animation policy | No animations on data surfaces (charts, tables, mini-bars). Transitions on layout-shift props banned. |
| NFR-7 | Chart-area utilisation | OHLCVChart's price scale must fit the actual range; volume sub-pane ≤ 20% of canvas height |
| NFR-8 | Cache reuse | No duplicate `useQuery` for the same logical resource across surfaces — TanStack `qk.*` cache must dedupe (Quote↔Financials sharing `fundamentals(id)`, Intelligence sharing `entityGraph(id, depth)`) |
| NFR-9 | Brief unavailability semantics | When no brief is cached, the AI brief banner must render an explicit affordance (`Generate`, `unavailable`, or `no news in last 90 days`) — never collapse to null silently |
| NFR-10 | Empty-state coverage | Every data surface specifies loading / error / empty as three distinct first-class states |
| NFR-11 | Hotkey scope contract | Chord listener honours a documented scope stack (modal > input > chart > table > page > global) — see `01-global-shell.md` §7 |
| NFR-12 | Type-decoupling watchdog | EODHD-verbatim PascalCase fields (`50DayMA`, `PercentInstitutions`, `EarningsShare`) MUST be referenced via the typed shape in `types/api.ts`. Any per-component string-key access requires a comment citing the audit. (See BP candidate in §11.) |

## 5. Out of scope (v1)

- **Mobile layouts.** Every page targets 1440×900+ desktop. Mobile is a separate spec.
- **Light mode.** Dark mode permanent (existing rule).
- **New backend services or major schema migrations.** v1 reuses existing endpoints; 5 new S9/S8 endpoint proposals (see §6.2) are deferrable.
- **Multi-portfolio comparison and consolidated household view.** Single active portfolio only.
- **Server-side preset persistence for the screener.** Local-storage only in v1; `POST /v1/screener/presets` deferred.
- **Per-firm analyst-target detail rows.** v1 shows aggregate consensus + counts; per-firm endpoint deferred.
- **Heavy graph visualisations beyond depth-2 force-directed.** Path-insight visuals are list-based v1; visual paths v2.
- **Workspace tab-stacking (multiple panels per slot).** Single panel per slot v1; stacking v1.1.

## 6. Technical design

### 6.1 Affected services

| Service | Changes | Reason |
|---------|---------|--------|
| **worldview-web (frontend)** | Major surgery on every primary page; new shared primitives; 5 new TanStack query keys; reworked `useMetricsTableData` (already done 2026-05-19), new `useFinancialsTabData` panels, `usePeerComparison`, `usePathInsights`, `useContradictions`, `useIntradayStats` | Entirety of this PRD |
| **api-gateway (S9)** | 5 OPTIONAL new endpoints (see §6.2). None required for v1 — they unblock specific cards but their absence is graceful |
| **portfolio (S1)** | 4 OPTIONAL endpoints (`twr`, `drawdown_series`, `attribution`, per-holding `value-history`) flagged by `04-portfolio-detail.md`. v1 derives client-side from `value-history` |
| **rag-chat (S8)** | 1 OPTIONAL endpoint for lazy AI-brief generation (`POST /v1/briefings/instrument/{id}/generate`). v1 shows `Generate` button that falls back to existing `GET` endpoint if brief was cached |
| All other services | No changes |

**The frontend is the only service that has to ship in v1.** All backend
additions are deferred and each card has a graceful fallback when its
optional endpoint is missing.

### 6.2 New endpoints (deferred — not blocking v1)

Documented in each per-page design doc. Consolidated here for the
`/plan` skill so future plans can pick them up:

| ID | Endpoint | Owner service | Source design doc | v1 fallback |
|----|----------|--------------|--------------------|-------------|
| B-Q-1 | `GET /v1/instruments/{id}/peers` | S2 / S9 | 05-instrument-quote §6.2 | Hide PeersStrip |
| B-Q-2 | `GET /v1/instruments/{id}/intraday-stats` | S2 | 05-instrument-quote §6.2 | Render existing SessionStatsStrip only |
| B-Q-3 | `GET /v1/instruments/{id}/multi-period-returns` | S2 | 05-instrument-quote §6.2 | Derive 1D from quote; hide other periods |
| B-Q-4 | `GET /v1/instruments/{id}/price-levels` | S2 | 05-instrument-quote §6.2 | Hide PriceLevelsCard |
| B-Q-5 | `POST /v1/briefings/instrument/{id}/generate` (lazy) | S8 | 05-instrument-quote §6.2 + 06-financials §6 | Render `Generate brief` CTA; existing GET if cached |
| B-F-1 | `GET /v1/instruments/{id}/analyst-targets` (per-firm) | S2 | 06-instrument-financials §6 | Hide TargetsByAnalyst panel |
| B-F-2 | `GET /v1/instruments/{id}/revisions?days=30` | S2 | 06-instrument-financials §6 | Hide RevisionsBlock |
| B-P-1 | `GET /v1/portfolios/{id}/twr` | S1 | 04-portfolio-detail §6 | Client-side compute from value-history |
| B-P-2 | `GET /v1/portfolios/{id}/risk-metrics?include=drawdown_series` | S1 | 04-portfolio-detail §6 | Client-side compute |
| B-P-3 | `GET /v1/portfolios/{id}/attribution` | S1 | 04-portfolio-detail §6 | Client-side compute (sector weighted return) |
| B-P-4 | `GET /v1/portfolios/{id}/holdings/{id}/value-history` | S1 | 04-portfolio-detail §6 | Skip per-holding curve in slide-over |
| B-D-1 | `GET /v1/dashboard/movers?period=1M` | S1/S2 | 02-dashboard §10 | Show 1D only |

Every endpoint above is OPTIONAL. The frontend renders a graceful
degradation (hide the card, or render a "—" placeholder) when the
endpoint isn't yet shipped.

### 6.3 No Kafka changes

No new events. No producer changes. No consumer changes. Existing
contracts honoured.

### 6.4 No DB changes

No new tables. No migrations. v1 reads from data that already exists in
postgres and is already exposed through S9.

### 6.5 Frontend domain model changes

No new domain types — all proposed shapes (TopMover, PeerInstrument,
PriceLevel, BeatMiss, AnalystRevision, etc.) are added to
`apps/worldview-web/types/api.ts` as response types when their backing
endpoint ships. Until then, components render placeholders.

### 6.6 Shared design tokens

The canonical token set is defined in `docs/designs/0089/_INDEX.md` and
copied below for ease of reading inside this PRD. Every component spec
in every per-page design doc references these tokens — no per-page
overrides allowed.

**Typography**

| Token | Size | Line height | Use |
|-------|------|-------------|-----|
| `text-[9px]`  | 9px  | 12px | Tertiary labels |
| `text-[10px]` | 10px | 14px | Group / column headers |
| `text-[11px]` | 11px | 16px | **Body default** (tables, rows) |
| `text-[12px]` | 12px | 18px | Section titles |
| `text-[13px]` | 13px | 20px | Page chrome |
| `text-[14px]` | 14px | 22px | One-off hero numbers (banned in tables) |

**Spacing**

| Token | px | Use |
|-------|---:|-----|
| `gap-1` / `p-1` |  4 | Inside dense rows |
| `gap-2` / `p-2` |  8 | Between section blocks |
| `gap-3` / `p-3` | 12 | Horizontal tab-content edges |
| `gap-4` / `p-4` | 16 | Panel max; banned for table cells |

**Color**: unchanged from `globals.css` Terminal Dark. New colors
introduced by any agent: zero.

### 6.7 Data flow (cross-cutting)

Cache-sharing matrix (the single most important architectural change is
making sibling surfaces share TanStack query keys so the user never
waits for the same data twice):

| Resource | Shared by | qk |
|----------|-----------|----|
| Page bundle | Instrument page Quote/Financials/Intelligence tabs | `qk.instruments.pageBundle(id)` |
| Full fundamentals (rich) | Quote MetricsTable, Financials FlatMetricsGrid | `qk.instruments.fundamentals(id)` |
| Technicals (envelope) | Quote MetricsTable, Financials FlatMetricsGrid | `qk.instruments.technicals(id)` |
| Share statistics | Quote MetricsTable, Financials FlatMetricsGrid | `qk.instruments.shareStatistics(id)` |
| OHLCV 1D | Chart, RSI/ATR cells (read-only via `enabled:false`) | `qk.instruments.ohlcv(id, "1D")` |
| Quote (live) | Header LiveQuoteBadge, Watchlist row | `qk.quotes.single(id)` |
| Entity graph | Intelligence GraphColumn + ContextPanel relations list | `qk.instruments.entityGraph(id, depth)` |
| Briefing | Quote AiBriefBanner, Intelligence StructuredBrief, Financials AI Brief panel | `qk.instruments.brief(id)` |
| News (entity) | Intelligence NewsColumn, Quote RelatedHeadlinesList, Dashboard PortfolioNewsCard | `qk.news.forEntity(id, params)` |
| Portfolio summary | Dashboard "Top of Portfolio", Portfolio Overview KPI strip, TopBar P&L | `qk.portfolios.summary(id)` |
| Portfolio holdings | Dashboard positions table, Portfolio Overview holdings table | `qk.portfolios.holdings(id)` |

NFR-8 enforces this — code review will reject any inline `useQuery`
that bypasses the `qk.*` registry.

## 7. Architecture & decisions

### 7.1 Why a single platform-wide PRD (and not 11 smaller ones)

Alternatives considered:
- **(A) 11 separate PRDs** — finest grain. Rejected: cross-cutting
  decisions (shared primitives, density tokens, cache-sharing matrix)
  would be relitigated 11 times. Surface boundaries leak (e.g. watchlist
  is global but referenced by every page).
- **(B) Single mega-PRD with all design detail inline** — rejected as
  unmaintainable. A 8000-line PRD is unreadable.
- **(C) Single PRD-0089 (this doc) + 11 design-doc references** —
  chosen. PRD is the contract. Design docs are the deep specs. The PRD
  is read end-to-end; the design docs are read on demand per surface.

### 7.2 Why "fix the spec, don't fix the frontend incrementally"

Alternatives:
- **(A) Per-defect patches** — risk: shipping fixes without a coherent
  density target means subsequent agent sessions diverge on row heights,
  font sizes, palette. PRD-0088's "design system" section ended up
  contradicted within weeks of writing it.
- **(B) New PRD with hard density floor + shared primitives** — chosen.

### 7.3 Why no animations on data

User memory `feedback_frontend_comments` + W6 chat polish memory
established that animations on layout-shift properties (chart Y-axis
range, table row insertion, mini-bar fill) are a recurring source of
jank in fast-refreshing financial UI. Banning them up-front avoids
re-fighting that battle on every component.

### 7.4 Why graceful degradation for new endpoints (v1)

The frontend is what the user is angry about. Shipping frontend density
fixes in v1 (without waiting on backend) means the user sees most of
the value in week 1. Backend additions ride later waves without blocking.

## 8. Security

- All new endpoints (when they ship) honour the existing OIDC auth +
  internal-JWT pattern (PRD-0025). No new auth surfaces.
- New frontend components do NOT introduce new ways to render
  user-controlled HTML. The `description` field rendered in the new
  `CompanyAboutCard` and `EntityOverviewBlock` is plain text from
  EODHD / S7 narrative output; render via `{text}` not
  `dangerouslySetInnerHTML`.
- No new token-storage surfaces. Access tokens continue to live only in
  React state (RULES.md R-frontend-2 unchanged).
- Hover-cards for `[cN]` citation anchors render text-only — no
  external URL fetches on hover.

## 9. Failure modes

| Mode | Affected surface | Strategy |
|------|------------------|----------|
| Brief endpoint returns 404 (no brief cached for entity) | Quote AiBriefBanner, Financials sidebar, Intelligence StructuredBrief | Render `Generate brief` CTA + `unavailable` state — NFR-9. NEVER collapse to null. |
| Entity-graph endpoint 504 at depth=3 | Intelligence GraphColumn | Depth-adaptive AbortController: 1500ms@d1 / 4000ms@d2 / 8000ms@d3. On timeout: render inline message "Graph too large at depth 3 — try depth 2" with one-click switch. |
| Snapshot endpoint sparse (most fields null) | Quote MetricsTable, Financials FlatMetricsGrid | Cells render "—" via MetricValue null-fallback. Rows are NOT hidden (layout stays stable). |
| Portfolio bundle endpoint returns no holdings | Dashboard top-of-portfolio, Portfolio Overview | Render brokerage-not-connected empty state with `Connect brokerage` CTA |
| Watchlist endpoint returns empty | Sidebar watchlist | Render `Add symbols` text-link (current behaviour) |
| News endpoint returns 0 articles | Intelligence NewsColumn, Quote RelatedHeadlines, Dashboard PortfolioNews | Render `No news in last 90 days` state |
| Chart `clientHeight = 0` at first paint | Quote OHLCVChart | Fallback to CHART_HEIGHT (280px) constant; ResizeObserver syncs once mount completes (fix already shipped 2026-05-19) |
| Live quote WebSocket disconnects | Header LiveQuoteBadge, Watchlist | Show grey freshness dot; switch to polling at 30s |
| `qk.instruments.fundamentals(id)` cache stale (>5min) | Quote MetricsTable, Financials FlatMetricsGrid | Background refetch; existing data stays rendered |
| Density target unreachable (e.g. mobile-ish viewport) | All pages | Out of scope — desktop-only v1 |

## 10. Scalability & performance budgets

| Metric | Budget |
|--------|--------|
| Page-bundle fetch on instrument page first paint | ≤ 800ms p95 |
| Quote tab time-to-data | ≤ 1.2s p95 (chart + MetricsTable populated) |
| Financials tab tab-switch latency | ≤ 200ms (cache-warmed) |
| Intelligence depth=2 graph render | ≤ 1.0s p95 |
| Intelligence depth=3 graph render | ≤ 3.0s p95 (timeout at 8s) |
| Screener filter change → result-count update | ≤ 250ms debounce + ≤ 400ms server |
| Dashboard cold load | ≤ 1.5s p95 with `qk.dashboard.snapshot` warm-up call |
| Bundle size growth (new components combined) | ≤ +60KB gzipped |
| TanStack query cache size | No global cap; per-key staleTime governs eviction |

## 11. Test strategy

| Layer | What we add |
|-------|-------------|
| Unit (Vitest + RTL) | One test per new component for null-data rendering ("—" or empty-state fallback); one test per new color-threshold helper |
| Integration (Vitest + MSW) | Cache-sharing — render two siblings reading the same key, assert single network call. One test per shared `qk.*` row in §6.7 |
| Architecture | Extend `__tests__/architecture/no-off-palette-colors.test.ts` to also ban inline `useQuery` outside hooks/ directory (NFR-8 enforcement) |
| Visual | Add 1 Playwright spec per primary page that opens the page against a seeded entity and asserts ≥ 40 cells visible (NFR-1) |
| Regression | Existing 1795-test suite must remain green |

### Specific tests to add

| Test | What it verifies |
|------|------------------|
| `CompanyAboutCard.test.tsx` | Renders description, sector, industry, employees, country; truncates description to 4 lines; "more" expand works |
| `StructuredBrief.test.tsx` | Renders headline + each `sections[].title` as h-row + each `bullets[]` as 11px row |
| `useMetricsTableData.test.tsx` | When `fundamentals` is null, snapshot's eps_ttm still renders (graceful partial) |
| `WatchlistRow.test.tsx` | Sparkline renders when 14 closes provided; "—" when missing |
| `DenseArticleRow.test.tsx` | 18px height; sentiment stripe color matches `sentiment_score` sign |
| `chord-scope-stack.test.tsx` | Q/F/I do NOT fire when input is focused; do NOT fire when modal is open |
| `cache-sharing.spec.ts` (integration) | Render `<Quote/>` then `<Financials/>` siblings — only one fetch for `qk.instruments.fundamentals` |
| `instrument-density.spec.ts` (Playwright) | After load, querySelectorAll on `[data-cell]` returns ≥ 40 in viewport |

## 12. Migration / rollout

The current branch `fix/ci-failures-cleanup` already has PLAN-0090 +
the 2026-05-19 follow-up fixes (chart Y-axis, MetricsTable rich
fundamentals, header always-renders). PRD-0089 ships on top of that
state.

**Branch strategy**: cut a new branch `feat/plan-0089-platform-redesign`
off `fix/ci-failures-cleanup` after the PRD is approved. Per-wave PRs
to that integration branch; final merge to main.

**Wave order** (proposed — see /plan output for canonical):

| Wave | Scope | Why first | Backend deps |
|------|-------|-----------|--------------|
| A — Shared primitives + tokens | TableRow22, MetricCell11, Sparkline, SeverityCharBadge, DataFreshnessPill, SectionDivider; update DESIGN_SYSTEM.md | Every later wave depends on these | None |
| B — Global shell tightening | TopBar 32px, sidebar 200px, watchlist sparkline rows, status bar registry, chord scope stack | Affects every page | None |
| C — Instrument Financials sidebar | 7-panel sidebar with restored AI brief + company snapshot; address the screenshot's empty real-estate first | Highest-visibility user complaint | None (briefing endpoint exists) |
| D — Instrument Quote density | CompanyAboutCard, 4-col MetricGrid, peers/earnings/headlines mini-cards, AI brief always-render | Restores deleted context | B-Q-5 (optional; v1 uses GET cache) |
| E — Instrument Intelligence | StructuredBrief, full right-rail, depth-adaptive timeout | Closes intelligence emptiness | None |
| F — Portfolio Overview holdings table | 14-col table with sparkline, KPI mega-cell, performance chart panel | "Cannot see positions" complaint | None for v1 |
| G — Portfolio detail (slide-over + tx ledger + analytics) | Holding slide-over, 20px tx rows, full analytics tab | Drilldowns | None for v1 (client-side TWR) |
| H — Dashboard | Top of Portfolio mega-cell, 8-cell market strip, 12-col grid | Landing page | None |
| I — Screener | Filter chips + popover, preset bar, 12-col results table | Single-page surgery | None |
| J — Workspace + Predictions + Alerts | Three smaller surfaces bundled per design doc | Lower-priority secondaries | None |
| K — Chat polish | Flat 11px text, [cN] anchors + hovercard, ContextRail | Cross-cutting AI UX | None |
| L — Backend additions (B-Q-1..5, B-F-1..2, B-P-1..4, B-D-1) | All optional endpoints from §6.2 | Lights up the deferred cards | Per endpoint |
| M — QA + Playwright density gates | Visual regression + NFR-1 enforcement | Lock the density floor | None |

Waves A→C ship the user's biggest complaint surface fast. L is
gated on independent backend work and runs in parallel with M.

## 13. Observability

- Add a `data-density-cell-count` attribute to each `MetricCell` for
  automated counting in Playwright NFR-1 tests
- Add a Sentry breadcrumb when an AI brief endpoint 404s — currently
  silent; need visibility into how often briefs are missing
- Add a custom metric `frontend.empty_states_rendered_total{surface,reason}`
  so we can see which empty states fire in production
- Existing structlog/trace plumbing unchanged

## 14. Open questions (consolidated — 47 total from per-page docs)

Grouped by category. Each question lists the source design doc.
A first read by the user should focus on the **BLOCKING** subset.

### BLOCKING (must resolve before /plan)

| # | Question | Source |
|---|----------|--------|
| OQ-B1 | Default portfolio when user has multiple — most-recently-viewed vs primary flag vs prompt? | 02-dashboard §10, 03-portfolio-overview §10 |
| OQ-B2 | Watchlist endpoint contract for the sidebar (currently a stub) — `/v1/watchlists` returns array of `{id,name,member_count}` but no per-member quote payload — what's the v1 shape? | 01-global-shell §8 |
| OQ-B3 | The synthetic test entity `01900000-…001001` (AAPL) has 404 on KG endpoints because its `entity_id` is different from `instrument_id`. The frontend currently passes `instrument_id` into `/v1/entities/{id}/...` — is this a routing bug or by design? | 07-instrument-intelligence §10, plus my earlier diagnostic |
| OQ-B4 | "Generate brief" lazy endpoint (B-Q-5) — accept v1 with no lazy generation (only show cached) or block on it? | 05-instrument-quote §6.2, 06-financials §6 |
| OQ-B5 | Confirm density floor of 40 cells above-fold at 1440×900 is the right NFR-1 number — the agents over-shoot it (113-281), suggesting we could raise the floor | All design docs |

### DEFERRED (can ship v1 with assumption + revisit later)

| # | Question | Source | Assumption v1 |
|---|----------|--------|---------------|
| OQ-D1 | Benchmark beyond SPY (QQQ, R2K, sector ETF) | 04-portfolio-detail | SPY only |
| OQ-D2 | Mobile collapse pattern | All | Out of scope |
| OQ-D3 | Brief banner border style (top-only / left-only / full) | 02-dashboard | Left-2px primary stripe |
| OQ-D4 | Crosshair-sync default ON or OFF in Workspace | 09-workspace | OFF (opt-in) |
| OQ-D5 | Workspace tab-stacking (multi-panel per slot) | 09-workspace | v1.1, not v1 |
| OQ-D6 | Screener preset persistence (local vs server) | 08-screener | Local |
| OQ-D7 | Watchlist add-flow UX (modal vs inline `+`) | 01-global-shell | Modal |
| OQ-D8 | Hover behaviour on holdings rows (highlight, no-op, sparkline expand) | 03-portfolio-overview | Highlight only |
| OQ-D9 | News sentiment dot source — daily_sentiments vs article-level sentiment_score | 02-dashboard, 07-intelligence | Article-level |
| OQ-D10 | Peer ranking heuristic (by sector + market cap proximity / by analyst-consensus correlation) | 05-instrument-quote | Sector + market cap |
| OQ-D11 | Pivot price-level formula (Camarilla / classic / Demark / S/R from technicals) | 05-instrument-quote | Classic |
| OQ-D12 | IPO baseline for instruments without 1Y/3Y/5Y returns | 05-instrument-quote | "—" |
| OQ-D13 | Brief generation rate-limit per user | 05-instrument-quote | 10/hr |
| OQ-D14 | StatusBar WebSocket dot — should it show every disconnect or only sustained drops > 5s? | 01-global-shell | Sustained > 5s |
| OQ-D15 | Slide-over behaviour at < `lg` viewport | 04-portfolio-detail | Full-screen replace |
| OQ-D16 | Attribution time aggregation (period vs daily-weighted) | 04-portfolio-detail | Period-end |
| OQ-D17 | CSV importer scope (just transactions vs lots vs holdings + transactions) | 04-portfolio-detail | Transactions only |
| OQ-D18 | ⌘\ collision with global shell command | 10-chat-ai | Chat ContextRail wins inside `/chat`; global wins elsewhere |
| OQ-D19 | AskAiPanel reuse strategy (lift into chat or keep separate) | 10-chat-ai | Keep separate; shared message-render primitives |
| OQ-D20 | Brief border style (top-only / left-only / full) | 05-instrument-quote | Top-only 1px |
| OQ-D21 | Default GraphColumn depth (1 or 2) | 07-intelligence | 2 |
| OQ-D22 | Animation on sparkline data update (none / 200ms fade) | All | None (per NFR-6) |
| OQ-D23–47 | Remaining 25 lower-priority OQs spread across design docs | various | Default decisions noted per-doc |

## 15. Estimation

| Wave | Engineer-days estimate (per /implement-ui prior data) |
|------|------|
| A — Primitives | 2-3 days |
| B — Global shell | 3-4 days |
| C — Financials sidebar | 2-3 days |
| D — Quote density | 3-4 days |
| E — Intelligence | 4-5 days |
| F — Portfolio Overview | 4-5 days |
| G — Portfolio detail | 5-6 days |
| H — Dashboard | 4-5 days |
| I — Screener | 4-5 days |
| J — Workspace+Predictions+Alerts | 4-5 days |
| K — Chat polish | 3-4 days |
| L — Backend additions (per endpoint, 13 endpoints, parallelisable) | 8-12 days |
| M — QA + Playwright density gates | 3-4 days |
| **Total (single engineer, serial)** | **49-65 engineer-days** |
| **Total (parallel agents per the dispatch pattern proven in PLAN-0090)** | **15-22 days** of wall-clock with 4-7 agents working in parallel per wave |

## 16. Implementation contract

Once OQ-B1..B5 are resolved and the user approves the per-page docs:

1. `/plan` decomposes this PRD into the 13 waves above. The output is
   `docs/plans/0089-platform-page-redesign-plan.md`.
2. `/implement-ui` per wave with explicit cherry-pick + commit discipline
   (the pattern we proved on PLAN-0090) — incremental commits per
   sub-task, never wait for wave-gate to commit.
3. Density floor (NFR-1) enforced in CI via Playwright spec added in
   wave M.

PRD-0089 is locked when this doc + 11 design docs + master `/plan` plan
file are all approved. From then on, design changes require a PRD-0089
amendment PR — no in-flight redesigns inside implementation waves.
