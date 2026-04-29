# PLAN-0050 — Dashboard & Instruments Polish (Phase 2)

**Status**: draft
**PRD source**: `docs/audits/2026-04-28-qa-frontend-design-roadmap.md` (PART D, Phase 2)
**Created**: 2026-04-28
**Estimated effort**: 3 weeks (≈110h)
**Depends on**: **PLAN-0049 complete** (structured brief, batch OHLCV, alert schema, shared components)

## Goal

Bring Dashboard and Instruments pages to Bloomberg/TradingView-grade depth: TradingView-style chart toolbar, fully populated fundamentals, entity-graph hover affordances, Intelligence-tab filters, real-time top-bar metrics, redesigned WatchlistMovers, Ask AI buttons, sentiment/impact-aware news.

## Scope (28 findings)

| Wave | Findings closed |
|------|-----------------|
| A — Top bar + Ask AI | F-D-008, F-D-009, F-D-026, F-I-018 |
| B — Watchlist Movers redesign + insights endpoint | F-D-004, F-B-007 |
| C — Chart toolbar + Volume submenu | F-I-002, F-I-019 |
| D — Fundamentals data backfill + sidebar metrics | F-I-003, F-I-011, F-I-012, F-I-013, F-I-014, F-I-015, F-B-012 |
| E — News tab + Entity graph + Intelligence filters | F-I-006, F-I-007, F-I-008, F-I-030 |
| F — Polish & MINOR sweep | F-D-005, F-D-007, F-D-011, F-D-013, F-D-018, F-D-027, F-I-005, F-I-009, F-I-010, F-I-017, F-I-022-29, F-I-031, F-I-032, F-I-033 |

## Codebase State Verification

| Reference | Actual state | Expected state | Delta |
|-----------|--------------|----------------|-------|
| `Fundamentals` Pydantic model (S3 / S9) | Lacks eps_ttm, beta, avg_volume_30d, operating_cash_flow, capex, free_cash_flow, fcf_margin, interest_coverage, net_debt_to_ebitda, credit_rating | All listed fields present | S3 schema migration + EODHD adapter extension |
| `EntityGraphPanel.tsx` hover handlers | Sets `hoveredNodeId` but no tooltip rendered | Render NodeTooltip + EdgeTooltip at mouse position | Add tooltip components |
| `IntelligenceTab.tsx` controls | Static graph, no filters | Filter toolbar (depth, relation type, entity type, time window, layout, confidence) | New IntelligenceFilters component + state hoisting |
| `ChartToolbar.tsx` | 4 controls (Vol/MA50/MA200/Fullscreen) | + RSI/MACD/Bollinger/ATR/Stochastic + drawing palette | Extend toolbar + DrawingTools layer |
| `WatchlistMoversWidget.tsx` | 1D/1W/1M change only | + per-watchlist return + sector concentration + news icon + alert dot | Refactor + new endpoint |
| `/v1/watchlists/{id}/insights` | Does not exist | Composite endpoint (S1+S3+S6+S7+S10) | New api-gateway route |
| `TopBar.tsx` portfolio metrics | Pre-computed props, 60s refetch | Real-time hook subscribed to quote refetch (15s) + Ask AI button | Hoist hook + add button + popover |
| `OverviewLayout.tsx` Ask AI | Not present | Floating button bottom-right with contextual chat | New component |
| `RankedArticle` type | No sentiment / market_impact fields | + sentiment, impact_score, time_grouping | S6 enrichment + frontend filters |

---

## Wave A — Top Bar Redesign + Ask AI (~14h)

**Goal**: Group portfolio metrics into a visual cluster on TopBar; add Ask AI floating button + popover with link-to-chat; make portfolio values real-time.

**Tasks**:
- T-A-1-01 (impl) — Wrap PORT/Day P&L/Total P&L in flex cluster with `bg-muted/20 border border-border/30 rounded-[2px]` on TopBar
- T-A-1-02 (impl) — `usePortfolioMetrics()` hook hoisted to layout, 15s refetch
- T-A-1-03 (impl) — `<AskAiButton>` + `<AskAiPopover>` with input field + "Make bigger →" link to `/chat`. Reuse existing `AskAiPanel.tsx`
- T-A-1-04 (impl) — `<InstrumentAskAiButton>` floating bottom-right in `OverviewLayout.tsx`. Context: ticker + price + 30d OHLCV + fundamentals + brief
- T-A-1-05 (test) — Vitest + Playwright for TopBar real-time updates + Ask AI flows

**Depends_on**: PLAN-0049 complete
**Closes**: F-D-008, F-D-009, F-D-026, F-I-018

---

## Wave B — Watchlist Movers Redesign + Insights Endpoint (~16h)

**Goal**: Make WatchlistMoversWidget genuinely useful. Add 5 enhancements gated on new composite endpoint.

**Tasks**:
- T-B-2-01 (impl) — `GET /v1/watchlists/{id}/insights` in api-gateway. Composes S1 members + S3 returns + S7 sectors + S6 news + S10 alerts. Returns `{members_count, movers, sectors, news, alerts}`. Cache-Control max-age=60.
- T-B-2-02 (impl) — Per-watchlist weighted return summary row at top of widget
- T-B-2-03 (impl) — Sector concentration mini-bar (3-stacked horizontal bar)
- T-B-2-04 (impl) — News-of-the-day icon with badge count on top movers
- T-B-2-05 (impl) — Active-alert dot on members with triggered alerts
- T-B-2-06 (impl) — Single-biggest-news callout above gainers/losers split
- T-B-2-07 (test) — Insights endpoint contract test + frontend snapshot test

**Depends_on**: PLAN-0049 (alert schema), Wave A
**Closes**: F-D-004, F-B-007

---

## Wave C — TradingView-Style Chart Toolbar (~22h)

**Goal**: Bring the OHLCV chart up to TradingView density: 5+ indicators, drawing palette, volume submenu.

**Tasks**:
- T-C-3-01 (impl) — Indicator dropdown menu (RSI, MACD, Bollinger Bands, ATR, Stochastic, OBV, VWAP) backed by `lightweight-charts` series API
- T-C-3-02 (impl) — Left-side vertical drawing palette: trend line, horizontal level, rectangle, arrow, fib retracement, parallel channel, text annotation. Click-to-arm model. Persist annotations per instrument in IndexedDB.
- T-C-3-03 (impl) — Volume submenu: Base Volume, Volume MA20, Volume Profile, VWAP Line (each as individual series toggles)
- T-C-3-04 (impl) — Studies/annotations state schema in `lib/instrument-context.ts`
- T-C-3-05 (test) — Vitest for toolbar interactions; visual regression test via Playwright screenshot
- T-C-3-06 (docs) — Update `docs/ui/DESIGN_SYSTEM.md` with chart-toolbar pattern

**Depends_on**: none (independent of other waves)
**Closes**: F-I-002, F-I-019, F-I-020 (keyboard nav for drawing tools)

---

## Wave D — Fundamentals Backfill + Sidebar Metrics (~22h)

**Goal**: Wire every "—" placeholder in InstrumentKeyMetrics + FundamentalsTab to real data.

**Tasks**:
- T-D-4-01 (schema) — Alembic migration in market-data: add columns `eps_ttm`, `beta`, `avg_volume_30d`, `operating_cash_flow`, `capex`, `free_cash_flow`, `fcf_margin`, `interest_coverage`, `net_debt_to_ebitda`, `credit_rating` to `fundamentals` table. All nullable, no server_default (forward-compat).
- T-D-4-02 (impl) — EODHD adapter in market-ingestion: extract above fields from EODHD financial endpoints. Compute derived (eps_ttm = sum last 4Q net_income / shares_outstanding; fcf = operating_cf - capex; fcf_margin = fcf / revenue; net_debt_to_ebitda = (total_debt - cash) / ebitda; interest_coverage = ebit / interest_expense).
- T-D-4-03 (impl) — Backfill script `services/market-ingestion/scripts/backfill_fundamentals.py` for top 100 symbols
- T-D-4-04 (impl) — Wire fields end-to-end through S9 Fundamentals response. Remove all hardcoded "—" in InstrumentKeyMetrics.tsx, FundamentalsTab.tsx (Cash Flow + Debt/Credit sections)
- T-D-4-05 (impl) — Add `<DataTimestamp>` "as of" footer in metrics panel (closes F-I-009)
- T-D-4-06 (test) — Integration test: API returns populated fundamentals for AAPL/MSFT/NVDA after backfill

**Depends_on**: PLAN-0049 (DataTimestamp component)
**Closes**: F-I-003, F-I-011, F-I-012, F-I-013, F-I-014, F-I-015, F-B-012

---

## Wave E — News Tab + Entity Graph + Intelligence Filters (~24h)

**Goal**: News tab gains relevance/sentiment/impact pills + filters; entity graph gets hover tooltips; Intelligence tab gets filter toolbar.

**Tasks**:
- T-E-5-01 (schema) — Add `sentiment` (enum: positive/negative/neutral/mixed), `impact_score` (float 0-1) to nlp-pipeline article enrichment. Avro schema bump if event-published; otherwise just DB column + API field.
- T-E-5-02 (impl) — `RankedArticle` type extended; gateway response includes sentiment + impact + entity chips
- T-E-5-03 (impl) — News tab UI: relevance gradient badge (amber→green), sentiment pill, impact pill, entity chips, time-grouping (TODAY / PAST 3 DAYS / PAST WEEK), source filter dropdown, sort dropdown
- T-E-5-04 (impl) — Entity graph hover tooltips: NodeTooltip ({name, type, degree, recent_news_count}) + EdgeTooltip ({relation_type, weight, source_citation}) — implement in EntityGraphPanel.tsx (Overview SVG) AND EntityGraph.tsx (Sigma.js Intelligence tab)
- T-E-5-05 (impl) — IntelligenceFilters toolbar above graph: depth slider (1-3), relation-type multi-select chips, entity-type filter, time-window filter, layout selector, confidence threshold
- T-E-5-06 (impl) — Stale-graph indicator after 24h (closes F-I-030)
- T-E-5-07 (test) — Vitest + Playwright for filter interactions and tooltip rendering

**Depends_on**: PLAN-0049 complete
**Closes**: F-I-006, F-I-007, F-I-008, F-I-030

---

## Wave F — MINOR Sweep + Polish (~12h)

Closes 18 MINOR/NIT findings in one bulk wave.

**Tasks**:
- T-F-6-01 — F-D-005 Predictions category filter pill row (replaces econOnly boolean)
- T-F-6-02 — F-D-007 Portfolio News fetch limit 4 → 15-20 with virtualization
- T-F-6-03 — F-D-011 Standardize widget inner padding to `px-3 py-2`
- T-F-6-04 — F-D-013 Refactor empty states to use `<DashboardEmptyState>`
- T-F-6-05 — F-D-018 Responsive breakpoints below 1024px (tablet stack layout)
- T-F-6-06 — F-D-027 Global "Refresh All" button via `queryClient.invalidateQueries()`
- T-F-6-07 — F-I-005 Trend sparkline axes (year ticks + right Y-axis)
- T-F-6-08 — F-I-010 52W bar vertical alignment in row 2
- T-F-6-09 — F-I-017 LiveQuoteBadge always-visible 3px dot
- T-F-6-10 — F-I-022 Session stats responsive
- T-F-6-11 — F-I-023 FundamentalSparkline showAxis wired
- T-F-6-12 — F-I-024 Skeleton matches 9-section layout
- T-F-6-13 — F-I-025 News date filter ARIA label
- T-F-6-14 — F-I-026 Search debounce 400ms → 250ms
- T-F-6-15 — F-I-027 OHLCV placeholder flicker fix
- T-F-6-16 — F-I-028 Right sidebar scroll unification
- T-F-6-17 — F-I-029 Click-to-copy ticker badge
- T-F-6-18 — F-I-031 / F-I-032 Mobile responsive baseline (warning page acceptable for thesis demo per D-6)
- T-F-6-19 — F-I-033 Error boundary around dynamic-imported EntityGraph
- T-F-6-20 — F-I-034 News article: same-tab vs new-tab user pref
- T-F-6-21 — F-I-035 Share/copy-link button on instrument header

**Depends_on**: Waves A-E
**Closes**: 21 findings

---

## Wave Tracker

| Wave | Tasks | Effort | Critical-path |
|------|-------|--------|--------------|
| A — Top bar + Ask AI | 5 | 14h | yes |
| B — Watchlist Movers + insights endpoint | 7 | 16h | no |
| C — Chart toolbar | 6 | 22h | no |
| D — Fundamentals backfill | 6 | 22h | no |
| E — News + Graph + Intelligence | 7 | 24h | no |
| F — MINOR sweep | 21 | 12h | no |
| **Total** | **52** | **110h ≈ 3 weeks** | — |

Waves B, C, D, E are independent → parallelizable across multiple worktrees.

---

## Cross-Cutting

- **New endpoint**: `GET /v1/watchlists/{id}/insights` (Wave B)
- **Schema additions**: 10 fundamentals columns (Wave D), sentiment/impact on articles (Wave E)
- **Frontend types**: AlertSummary (PLAN-0049), RankedArticle, WatchlistInsights, BriefSection (already from PLAN-0049)
- **Docs**: api-gateway.md, market-data.md, nlp-pipeline.md, DESIGN_SYSTEM.md (chart toolbar)

## Risk

- **Wave C** (drawing tools) is highest-risk: persistence + WebGL interaction is non-trivial. Allocate full 22h. Fall back to indicators-only if drawing tools slip.
- **Wave D** depends on EODHD data quality — some fields may not be available on all instruments. Treat NULL gracefully.

---

## Ship Checklist (QA iter-1 operator notes — F-Q1-01)

These steps must be completed before merging to `main` or deploying to staging.

### API Gateway (S9)

- [ ] **F-Q1-02 / change_pct**: `GET /v1/watchlists/{id}/insights` now fetches price via `/internal/v1/price/{iid}` (PriceSnapshot endpoint). Verify `movers[*].change_pct` is non-null on a live watchlist after a full market-data seed cycle.
- [ ] **F-Q1-13 / mover sort**: `movers` are returned sorted by `|change_pct|` descending. Confirm the highest-magnitude mover is first in the response.
- [ ] **Smoke test**: `GET /v1/watchlists/{id}/insights` returns HTTP 200 with `members_count > 0` and `movers` array populated.

### Market Data (S3)

- [ ] **F-Q1-03 / snapshot ingestion**: After re-triggering a fundamentals fetch (or running `python scripts/backfill_fundamentals.py`), confirm `SELECT count(*) FROM instrument_fundamentals_snapshot` returns > 0 rows in `market_data` DB.
- [ ] **Continuous path**: Publish a `market.dataset.fetched` event with `dataset_type=fundamentals` via Kafka UI; verify FundamentalsConsumer logs `fundamentals_consumer.snapshot_upserted` and the row appears in `instrument_fundamentals_snapshot`.
- [ ] **Smoke test**: `GET /internal/v1/fundamentals/{instrument_id}/snapshot` returns non-null values for `eps_ttm` and/or `beta`.

### NLP Pipeline (S6)

- [ ] **F-Q1-07 / sentiment**: Verify `document_source_metadata.sentiment` is populated (not NULL) for articles scored after this deploy. SQL: `SELECT sentiment, count(*) FROM document_source_metadata WHERE llm_scored_at > now() - interval '1h' GROUP BY 1`.
- [ ] **Prompt regression**: Confirm ArticleRelevanceScoringWorker logs no `relevance_scoring.parse_error` entries (indicates LLM returning malformed JSON). Response shape: `{"score": float, "reason": "…", "sentiment": "positive"|"negative"|"neutral"|"mixed"}`.
- [ ] **Smoke test**: `GET /v1/news/top` via S9 returns articles with `sentiment` field set.

### General

- [ ] All unit tests pass: `python -m pytest services/api-gateway/tests services/market-data/tests/unit services/nlp-pipeline/tests/unit -v`
- [ ] Ruff + mypy clean across changed services
- [ ] `TRACKING.md` updated to mark affected waves as complete
