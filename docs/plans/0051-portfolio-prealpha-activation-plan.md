# PLAN-0051 — Portfolio + Pre-Alpha Activation (Phase 3)

**Status**: draft
**PRD source**: `docs/audits/2026-04-28-qa-frontend-design-roadmap.md` (PART D, Phase 3)
**Created**: 2026-04-28
**Estimated effort**: 4 weeks (≈140h)
**Depends on**: **PLAN-0049 complete** (alert schema + shared components); independent of PLAN-0050

## Goal

Activate the four "pre-alpha" pages (Screener, Workspace, Alerts, Chat) to functional MVP. Complete Portfolio enhancements (filters, exports, realized P&L, dividends fix). After this plan: Screener has real fundamental/technical filters, Workspace persists layouts and ships completed panel types, Alerts has full ACK/snooze/history/rule manager, Chat has slash commands + markdown.

## Scope (~35 tasks across 6 waves)

| Wave | Findings closed |
|------|-----------------|
| A — Portfolio Transactions + Realized P&L | F-P-007, F-P-010, F-P-011 |
| B — Screener filters + saved screens + columns + export | F-X-001, F-X-002, F-X-003, F-X-007, F-X-008, F-X-009, F-X-011 |
| C — Workspace persistence + panel completion + templates | F-X-101, F-X-102, F-X-103, F-X-104, F-X-105, F-X-106 |
| D — Alerts: ACK sync + history + rule manager + channels | F-X-203, F-X-204, F-X-205, F-X-206, F-X-207 |
| E — Chat: slash commands + markdown + thread search | F-X-301, F-X-304, F-X-305 |
| F — Portfolio MINOR sweep | F-P-002, F-P-003, F-P-004, F-P-005, F-P-006, F-P-012-28 (18 items) |

---

## Wave A — Portfolio Transactions Filters + Realized P&L (~22h)

### Tasks
- **T-A-1-01** (impl, M) — Date-range picker + ticker autocomplete + market filter + amount slider in TransactionsTable
- **T-A-1-02** (impl, M) — CSV export button (papaparse); pagination/virtualization (react-window for >200 rows); totals row (BUY cost / SELL proceeds / DIV income)
- **T-A-1-03** (impl, M) — Free-text search + clear-filters button
- **T-A-1-04** (backend, L) — S1 new endpoint `GET /v1/portfolio/realized-pnl?account_id&from&to` computing FIFO over full transaction history (including fully-closed positions)
- **T-A-1-05** (impl, S) — Wire realized P&L to PortfolioKPIStrip; show "approx." badge if backend unavailable
- **T-A-1-06** (impl, M) — F-P-010 SnapTrade DIV amount populated in adapter + log warning when amount ≤ 0 on DIVIDEND rows
- **T-A-1-07** (test) — Vitest + Playwright for filters/export/realized P&L

**Depends_on**: PLAN-0049 complete
**Closes**: F-P-007, F-P-010, F-P-011

---

## Wave B — Screener Activation (~30h)

### Tasks
- **T-B-2-01** (backend, M) — Verify S9 `/fundamentals/screen` accepts P/E, dividend yield, ROE, debt/equity, growth filters. Add if missing.
- **T-B-2-02** (impl, L) — Expand ScreenerFilterBar to collapsible panel with sections: Valuation (P/E, P/B, Div Yield, P/S), Profitability (ROE, gross/net/op margin), Growth (revenue/earnings YoY), Leverage (debt/equity, current ratio)
- **T-B-2-03** (impl, M) — Technical filters: above 50d MA, RSI band, volume vs 30d avg, distance from 52W high/low (compute client-side fallback if S9 unsupported)
- **T-B-2-04** (impl, M) — News & Signals filters: news velocity 7d, controversy score, recent earnings, insider activity
- **T-B-2-05** (impl, M) — Saved screens UI (localStorage MVP) + named load dialog
- **T-B-2-06** (impl, M) — Column customization (⚙ icon → checklist + drag reorder, persist to localStorage)
- **T-B-2-07** (impl, M) — Export dropdown (CSV via papaparse, Excel via xlsx, PDF via jspdf)
- **T-B-2-08** (impl, S) — Result count "X of Y match" indicator (requires S9 to return universe total)
- **T-B-2-09** (impl, M) — Inline mini-chart per row using batch OHLCV endpoint from PLAN-0049 (T-A-1-05)
- **T-B-2-10** (impl, S) — Pagination "Load More" button + result count
- **T-B-2-11** (test) — Vitest for filter combinations, saved screens, column persistence

**Depends_on**: PLAN-0049 (batch OHLCV endpoint)
**Closes**: F-X-001, F-X-002, F-X-003, F-X-004, F-X-007, F-X-008, F-X-009, F-X-010, F-X-011, F-X-012

---

## Wave C — Workspace Activation (~28h)

### Tasks
- **T-C-3-01** (impl, S) — Verify WorkspaceContext.updateWorkspaceLayout() wired to onLayoutChanged callback; persist to localStorage; restore on mount
- **T-C-3-02** (audit, S) — Audit every PANEL_CATALOGUE entry for completeness
- **T-C-3-03** (impl, M) — Build `WorkspaceChartWidget.tsx` (lightweight chart for linked symbol, timeframe selector)
- **T-C-3-04** (impl, M) — Build `WorkspaceFundamentalsWidget`, `WorkspaceNewsPanel`, `WorkspacePortfolioPanel`, `WorkspaceBriefWidget` if missing OR remove from catalogue
- **T-C-3-05** (impl, M) — Symbol linking: color picker in panel header → SymbolLinkingContext → linked panels read symbol via hook → re-fetch
- **T-C-3-06** (impl, M) — 5 templates: Day Trader, Research, Swing Trader, News Junkie, Investor. "New from Template" dialog
- **T-C-3-07** (impl, M) — Share-via-URL: base64-encoded WorkspaceConfig in URL param; decode-and-restore on load
- **T-C-3-08** (impl, S) — Add-Panel dialog auto-closes after add (F-X-107)
- **T-C-3-09** (test) — Vitest + Playwright for layout persistence, symbol linking, template restore, URL share

**Depends_on**: PLAN-0049 complete (no other dep)
**Closes**: F-X-101, F-X-102, F-X-103, F-X-104, F-X-105, F-X-106, F-X-107

---

## Wave D — Alerts: Backend ACK + History + Rule Manager (~26h)

### Tasks
- **T-D-4-01** (schema) — Alembic migration in alert: add `acknowledged_at TIMESTAMPTZ`, `acknowledged_by_user_id UUID`, `snooze_until TIMESTAMPTZ` to alerts table (nullable, no server_default)
- **T-D-4-02** (impl, M) — S10 endpoints: `PATCH /v1/alerts/{id}/acknowledge`, `PATCH /v1/alerts/{id}/snooze` (body: until: datetime), `GET /v1/alerts/history` (filters: severity, entity, from, to, status, paginated)
- **T-D-4-03** (impl, S) — Frontend writes ACK/snooze to backend in addition to localStorage
- **T-D-4-04** (impl, M) — New "History" tab in /alerts: paginated table with severity/ticker/type/fired-at/dismissed-at/status columns; filters mirror backend params
- **T-D-4-05** (impl, M) — AlertDetailSheet "Suggested Actions" section: View Instrument / Add to Watchlist / Set Alert Rule / Open in Chat
- **T-D-4-06** (impl, M) — Rule Manager dialog (full CRUD): list rules, edit, delete; wire ⚙ Rules button
- **T-D-4-07** (impl, M) — Notification Preferences (in-app, email digest opt-in, browser push) — localStorage MVP
- **T-D-4-08** (test) — Vitest + Playwright for ACK sync, history, rule manager flow

**Depends_on**: PLAN-0049 complete (alert schema + shared components)
**Closes**: F-X-203, F-X-204, F-X-205, F-X-206, F-X-207

---

## Wave E — Chat Activation (~18h) — DONE 2026-04-29

### Tasks
- **T-E-5-01** (impl, M) — DONE — Slash command parser (`/portfolio`, `/quote SYM`, `/news SECTOR=tech`, `/watchlist NAME`, `/alerts`, `/screener`); render structured cards inline (no LLM round-trip). Files: `lib/chat/slash-commands.ts`, `components/chat/SlashCommandCard.tsx`, `components/chat/SlashCommandAutocomplete.tsx`.
- **T-E-5-02** (impl, M) — DONE — Migrated chat message rendering to `<MarkdownContent>` (assistant + streaming bubbles). Added `CopyableCodeBlock` (Copy button overlay on code blocks). Tables already had border-collapse + zebra rows from PLAN-0049.
- **T-E-5-03** (impl, S) — DONE — Search input above the thread list sidebar; debounced 200ms; client-side substring filter on title + last messages.
- **T-E-5-04** (impl, S) — DONE — Citation confidence bar (`components/chat/CitationBar.tsx`), green ≥0.7 / amber 0.4–0.7 / red <0.4, with hover tooltip + anchor scroll. Documented in `docs/ui/DESIGN_SYSTEM.md` §6.14.
- **T-E-5-05** (impl, S) — DONE — Context-aware 4-card starter set when `?entity_id=` is present.
- **T-E-5-06** (impl, S) — DONE — Inline rename via double-click; gateway method `updateThread`; new S9 proxy `PATCH /v1/threads/{id}`; S8 PATCH route + `UpdateThreadUseCase` + `ThreadRepository.update_title` (atomic ownership-filtered UPDATE, no TOCTOU). Optimistic UI with rollback.
- **T-E-5-07** (impl, S) — DONE — `lib/chat/export-thread.ts` (`threadToMarkdown` + `downloadThread`); Export button in chat header; filename `thread-<slug>-YYYYMMDD.md`.
- **T-E-5-08** (test) — DONE — 7 Vitest files / 35 new tests (slash-commands 11, slash-command-card 4, citation-bar 6, chat-thread-search 3, thread-rename 4, thread-export 4, context-aware-starters 2, +1 minor); 793 frontend tests pass overall. Backend: 2 new rag-chat unit tests (PATCH endpoint), 1 new api-gateway proxy test — 468/296 passing.

**Depends_on**: PLAN-0049 (MarkdownContent)
**Closes**: F-X-301, F-X-304, F-X-305, F-X-302, F-X-303, F-X-307, F-X-308

---

## Wave F — Portfolio MINOR Sweep (~16h) — STATUS: DONE 2026-04-29

All 21 polish items shipped. See `apps/worldview-web/__tests__/portfolio-wave-f-polish.test.tsx` (14 new tests) for the regression suite. Behaviour-changing fixes: F-P-002, F-P-003 (period hoist), F-P-004 (responsive), F-P-012 (Skeleton vs $0), F-P-013 (stable keys), F-P-014 (sector a11y), F-P-016 (copy guide), F-P-019 (safe-area), F-P-020 (skeleton 7-tile), F-P-021 (bg-popover tooltip), F-P-024 (debounce comment), F-P-025 (URL sort), F-P-026 (pattern encoding), F-P-027 (60s timeout escalation), F-P-028 (placeholder verification). Pure-CSS or comment-only fixes: F-P-005, F-P-006, F-P-015, F-P-017, F-P-022, F-P-023.

Bulk-close 18 MINOR/NIT portfolio findings.

**Tasks**:
- T-F-6-01 — F-P-002 ExposureBreakdown empty-state vertically centered
- T-F-6-02 — F-P-003 EquityCurveChart period state hoisted to page
- T-F-6-03 — F-P-004 RiskMetricsStrip mobile responsive (overflow scroll or 1-col stack)
- T-F-6-04 — F-P-005 Allocation row height aligned with table (pick 18px or 22px)
- T-F-6-05 — F-P-006 Document why no 1D button on equity curve (or add if snapshot frequency permits)
- T-F-6-06 — F-P-012 Day P&L tile zero vs null distinguished (skeleton on null)
- T-F-6-07 — F-P-013 Weight bar key stabilization (no flicker)
- T-F-6-08 — F-P-014 Sector bar a11y (aria-label, optional pattern)
- T-F-6-09 — F-P-015 Sticky table header padding alignment
- T-F-6-10 — F-P-016 Empty state copy guide
- T-F-6-11 — F-P-017 KPI tile padding consistency
- T-F-6-12 — F-P-019 Mobile safe-area
- T-F-6-13 — F-P-020 Loading skeleton matches responsive grid
- T-F-6-14 — F-P-021 Tooltip contrast in dark mode
- T-F-6-15 — F-P-022 Document final period set (no silent re-adds)
- T-F-6-16 — F-P-023 Divider border consistency
- T-F-6-17 — F-P-024 Watchlist search debounce (300-500ms)
- T-F-6-18 — F-P-025 Sort state persisted across tab switches (URL or sessionStorage)
- T-F-6-19 — F-P-026 Cash/Invested colorblind-safe encoding
- T-F-6-20 — F-P-027 Resolution badge timeout (60s → "resolution timeout — try re-adding")
- T-F-6-21 — F-P-028 Zero-qty/price row de-emphasis verification

**Depends_on**: Waves A-E
**Closes**: 21 portfolio findings

---

## Wave Tracker

| Wave | Tasks | Effort | Critical-path |
|------|-------|--------|--------------|
| A — Portfolio transactions + realized P&L | 7 | 22h | no |
| B — Screener activation | 11 | 30h | no |
| C — Workspace activation | 9 | 28h | no |
| D — Alerts ACK sync + history + rule manager | 8 | 26h | no |
| E — Chat activation | 8 | 18h | no |
| F — Portfolio MINOR sweep | 21 | 16h | no |
| **Total** | **64** | **140h ≈ 4 weeks** | — |

All waves independent of each other → fully parallelizable across worktrees. Critical sequencing: PLAN-0049 must complete first.

---

## Cross-Cutting

- **New endpoints**: `GET /v1/portfolio/realized-pnl`, `PATCH /v1/alerts/{id}/acknowledge`, `PATCH /v1/alerts/{id}/snooze`, `GET /v1/alerts/history`, `PATCH /v1/threads/{id}`
- **Schema additions**: alerts table gets `acknowledged_at`, `acknowledged_by_user_id`, `snooze_until` (Wave D)
- **Frontend types**: TransactionListItem (extended), SavedScreen, WorkspaceTemplate, AlertHistoryItem, NotificationPreferences
- **Docs**: alert.md, portfolio.md, api-gateway.md, ui/DESIGN_SYSTEM.md
- **New deps**: papaparse, xlsx, jspdf (export), react-window (virtualization), html2canvas (screenshot — for PLAN-0052 feedback system)

## Risk

- **Wave B** is highest-effort. Mitigate by shipping fundamental filters (P0) first; technical/news filters can split into a follow-up if S9 backend gaps surface.
- **Wave C** depends on auditing existing Workspace panel completeness — if many panels are stubs, scope balloons. Decision D-5 in audit: remove stubs from catalogue rather than ship "Coming Soon".
- **Wave D** alert ACK/snooze sync: requires careful migration of existing localStorage state to backend on first load (don't lose user's existing ACKs).
