# PLAN-0053 — Polish & Advanced Features (Phase 5)

**Status**: draft
**PRD source**: `docs/audits/2026-04-28-qa-frontend-design-roadmap.md` (PART D, Phase 5)
**Created**: 2026-04-28
**Estimated effort**: 4 weeks (≈130h)
**Depends on**: PLAN-0049, PLAN-0050, PLAN-0051, PLAN-0052 (this is post-MVP polish)

## Goal

Post-MVP polish: universe expansion to 600+ symbols, institutional-grade portfolio analytics, drawing-tools persistence, full a11y audit, mobile responsive overhaul, feedback system Phase 3 (Linear webhook + sentiment analysis), inline charts in chat responses.

## Wave A — Universe Expansion to 600+ Symbols (~12h)

**Goal**: Replace ~80 hardcoded symbols with full S&P 500 + NDX-100 + Russell 1000 top + sector ETFs + crypto top 20.

### Tasks
- **T-A-1-01** (script) — `scripts/seed_instruments.py` fetches latest constituent CSVs from public sources (S&P, NASDAQ, Russell)
- **T-A-1-02** (schema) — Alembic data migration `0012_expand_to_sp500_nasdaq100_plus.py` in market-ingestion. Inserts polling_policies for ~600 symbols at T3 tier (infrequent) to control quota.
- **T-A-1-03** (impl) — Tier-promotion logic: when a watchlist or screener references a T3 symbol, promote to T2; T2 → T1 on heavy traffic
- **T-A-1-04** (test) — Smoke test: bulk fetch quotes for 50 symbols completes in <5s; check rate-limit headroom
- **T-A-1-05** (docs) — Document tier policy + how to add custom symbols in `docs/services/market-ingestion.md`

**Closes**: F-B-004
**Effort**: 12h

---

## Wave B — Institutional Portfolio Analytics (~32h)

**Goal**: Add the analytics professional portfolio managers expect.

### Tasks
- **T-B-2-01** (backend, L) — Contribution attribution endpoint (each holding's % contribution to total return over period)
- **T-B-2-02** (backend, L) — Drawdown chart data (peak-to-trough analysis with dates and depths)
- **T-B-2-03** (backend, M) — Correlation matrix endpoint (pairwise correlation of holdings over N days)
- **T-B-2-04** (backend, M) — Dividend timeline endpoint (historical + projected dividend income)
- **T-B-2-05** (backend, M) — Currency exposure (multi-currency portfolio split if user has international holdings)
- **T-B-2-06** (frontend, L) — Contribution chart component
- **T-B-2-07** (frontend, M) — Drawdown chart component
- **T-B-2-08** (frontend, L) — Correlation matrix heatmap component
- **T-B-2-09** (frontend, M) — Dividend timeline chart
- **T-B-2-10** (test) — Coverage for all new analytics endpoints + visualizations

**Closes**: F-P-018
**Effort**: 32h

---

## Wave C — Chart Drawing Tools Persistence + Custom Indicators (~22h)

**Goal**: Drawing tools from PLAN-0050 Wave C persist in IndexedDB; custom indicator config (parameters, colors).

### Tasks
- **T-C-3-01** (impl, M) — IndexedDB schema for chart annotations per `(user, instrument, timeframe)`
- **T-C-3-02** (impl, M) — Annotation serialization/restore on chart mount
- **T-C-3-03** (impl, M) — Indicator config persistence (RSI period, MACD signal, Bollinger stddev, etc.)
- **T-C-3-04** (impl, M) — Indicator color customization picker
- **T-C-3-05** (impl, M) — Save/load chart layout preset (named presets with all annotations + indicators)
- **T-C-3-06** (test) — Vitest for IndexedDB roundtrip + Playwright visual snapshot

**Effort**: 22h

---

## Wave D — Mobile Responsive Overhaul (~28h)

**Goal**: Full mobile support beyond Phase 1's "warning page". Per audit decision D-6: depending on thesis priorities, may stay scoped or expand.

### Tasks
- **T-D-4-01** (impl, M) — Dashboard responsive grid: stack widgets vertically below 1024px, prioritize Brief + Portfolio + Alerts on first viewport
- **T-D-4-02** (impl, M) — Instruments page mobile layout: collapsible sidebar, "Metrics" tab overlay, expandable header
- **T-D-4-03** (impl, M) — Portfolio page mobile: tabs become bottom-sheet, table horizontal-scroll with sticky ticker column
- **T-D-4-04** (impl, M) — Workspace mobile: single-panel view with swipe to switch panels
- **T-D-4-05** (impl, S) — Mobile safe-area for notched devices (env(safe-area-inset-*))
- **T-D-4-06** (impl, M) — Touch interactions: tap-to-select on charts, long-press for tooltips, swipe gestures on tabs
- **T-D-4-07** (test) — Playwright mobile viewport testing (iPhone 14, Pixel 7, iPad)

**Closes**: F-D-018, F-I-031, F-I-032, F-P-019
**Effort**: 28h

---

## Wave E — Accessibility Full Audit (WCAG 2.1 AA) (~18h)

**Goal**: Complete a11y audit across every page; fix all axe-core issues.

### Tasks
- **T-E-5-01** (audit) — Run axe-core via Playwright on every page; collect violations
- **T-E-5-02** (impl) — Fix color contrast issues (palette adjustments per F-D-012)
- **T-E-5-03** (impl) — ARIA labels on chart canvases, entity graphs, complex widgets (F-I-020, F-I-021, F-I-025)
- **T-E-5-04** (impl) — Keyboard navigation for entity graph (Tab, Enter, Arrow keys)
- **T-E-5-05** (impl) — Screen reader announcements for live data updates
- **T-E-5-06** (impl) — Focus management in modals/popovers
- **T-E-5-07** (impl) — `tabular-nums` utility class enforcement (F-D-017)
- **T-E-5-08** (impl) — Color-only encoding fixes (allocation/exposure bars per F-P-014, F-P-026)
- **T-E-5-09** (test) — axe-core CI gate

**Effort**: 18h

---

## Wave F — Performance & Cache Hardening (~10h)

### Tasks
- **T-F-6-01** — Audit `Cache-Control` headers across all GET endpoints; standardize 60s for live, 300s for bars, 3600s for fundamentals
- **T-F-6-02** — Verify all batch endpoints parallelize via asyncio.gather (no sequential N+1)
- **T-F-6-03** — TanStack Query `staleTime` review across all 30+ widgets; consolidate
- **T-F-6-04** — CDN caching layer (if not already on Vercel)
- **T-F-6-05** — Lighthouse audit per page; fix any regressions

**Effort**: 10h

---

## Wave G — Feedback System Phase 3 (~8h)

**Goal**: Linear/GitHub webhook integration + sentiment analysis on feedback comments + admin analytics.

### Tasks
- **T-G-7-01** — Linear webhook: bug-type submissions auto-create Linear issues
- **T-G-7-02** — Sentiment analysis on comment text (Hugging Face inference or OpenAI)
- **T-G-7-03** — Admin analytics: feedback volume trends, common tags, NPS rolling 30-day
- **T-G-7-04** — Email notification to admin team on critical feedback

**Effort**: 8h

---

## Wave Tracker

| Wave | Tasks | Effort |
|------|-------|--------|
| A — Universe expansion | 5 | 12h |
| B — Institutional analytics | 10 | 32h |
| C — Drawing tools persistence | 6 | 22h |
| D — Mobile responsive | 7 | 28h |
| E — A11y full audit | 9 | 18h |
| F — Performance & cache | 5 | 10h |
| G — Feedback Phase 3 | 4 | 8h |
| **Total** | **46** | **130h ≈ 4 weeks** |

All waves independent → fully parallelizable.

---

## Cross-Cutting

- **New endpoints**: contribution, drawdown, correlation, dividends, currency exposure (Wave B)
- **New deps**: axe-core (Wave E), HuggingFace inference SDK (Wave G)
- **CI gates**: Lighthouse perf budget, axe-core a11y budget

## Risk

- **Wave B analytics** is highest-effort and lowest-priority for thesis — can be cut to fit timeline
- **Wave D mobile** competes with desktop polish for attention — explicit scope decision needed (decision D-6 in audit recommended desktop-only for thesis)
- **Wave G external integrations** depend on third-party API availability (Linear, GitHub) — mock if unavailable

---

## Roadmap Closure

After PLAN-0053 completes, all 145 findings from the 2026-04-28 audit are closed.

**Total roadmap effort**: ~580h ≈ 14-18 weeks at 1 dev (or 7-9 weeks at 2 devs in parallel using worktrees).
