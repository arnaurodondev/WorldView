# PLAN-0071: Institutional UI Uplift — Adversarial Second-Pass Remediation

**Status:** IN PROGRESS
**Created:** 2026-05-04
**Owner:** Frontend Team

---

## Evidence Labels

All observations are labeled: [VERIFIED IN CODE], [VERIFIED VISUALLY], [INFERRED], or [NOT YET VERIFIED].

---

## Prior Audit Corrections

**Prior audit was WRONG on:**
- Tremor is NOT installed — not in package.json. Prior audit evaluated a non-existent library.
- GlobalSearch IS a full cmdk Command palette (Cmd+K, recent instruments, keyboard nav, categories). Claim it "is not a command palette" was incorrect.
- `text-amber-*` in AskAiPanel was already fixed in PLAN-0059-W0. `accent-ai` violet is already used.
- Claimed "Bloomberg-grade design token foundation" — overclaims. Tokens are strong in intent, but execution has verified gaps.

**Prior audit was TOO SOFT on:**
- AskAiPanel.tsx:144: `body: JSON.stringify({ message: query.trim() })` — ZERO context sent. Functionally blind.
- Chat page (/chat): generic two-panel chatbot, no financial differentiation.
- GlobalSearch: only one command ("Send Feedback"). Missing page nav, quick actions.

**Prior audit was TOO HARSH on:**
- AG Grid framed as needed for row performance — WRONG. DataTable handles virtualization. AG Grid needed for column features.

---

## Verified Weaknesses

### Critical
1. [VERIFIED IN CODE] `AskAiPanel.tsx:144` — context NEVER injected into API payload.
2. [VERIFIED VISUALLY] Chat page (`/chat`) — generic chatbot, no financial differentiation.
3. [VERIFIED IN CODE] `GlobalSearch.tsx` — only "Send Feedback" command. No page nav or quick actions.
4. [VERIFIED IN CODE] `IntelligenceTab.tsx:114` — `bg-green-500/15 text-green-400 border-green-500/30` bypasses design system.
5. [VERIFIED IN CODE] `confirm-dialog.tsx:109` — `bg-amber-500 text-white hover:bg-amber-600` bypasses design system.
6. [VERIFIED IN CODE] `sheet.tsx:58` — `p-6 shadow-lg` violates terminal panel spacing rules.

### High
7. [VERIFIED IN CODE] AG Grid not installed. DataTable missing: column pinning, grouped column headers, saved state, cell value flash.
8. [VERIFIED IN CODE] 52W Range and Volume screener columns are backend-pending placeholders.

### Medium
9. [VERIFIED IN CODE] Dashboard widgets lack shared PanelHeader primitive.
10. [NOT YET VERIFIED] WebSocket real-time price updates to OHLCV chart last bar.

---

## Verified Strengths

1. [VERIFIED IN CODE] Design token system (CSS vars, IBM Plex Sans+Mono, 2px radius, financial tokens).
2. [VERIFIED IN CODE] DataTable: TanStack v8 + react-virtual, multi-sort, multi-select, TSV copy, column resize.
3. [VERIFIED IN CODE] GlobalSearch: proper cmdk Command palette foundation.
4. [VERIFIED VISUALLY] Portfolio holdings page looks institutional with real data.
5. [VERIFIED IN CODE] OHLCV chart: Lightweight Charts v5, 7 indicators, drawing tools, volume profile.
6. [VERIFIED IN CODE] PLAN-0059 waves A, C, E, F complete; B, D partial.
7. [VERIFIED IN CODE] PLAN-0069 complete — text-xs→text-[11px], animate-pulse removed, strokeWidth standardized.

---

## Stack Decisions (Final)

| Technology | Decision |
|-----------|---------|
| Next.js 15 App Router | KEEP |
| TanStack Table v8 | KEEP for ≤200 row tables |
| AG Grid Community | ADD for finance tables (screener, holdings, financials) |
| TradingView Lightweight Charts v5 | KEEP |
| Tremor | DO NOT ADD — would conflict with token system |
| cmdk (via shadcn Command) | KEEP, extend with page nav + quick actions |
| react-resizable-panels v4 | KEEP, expand to instrument page split |
| framer-motion | DO NOT ADD YET |

---

## Phase 0 — Evidence Completion

**Goal:** Close open evidence gaps before implementation.

- P0-1: MIT project URL — user must provide GitHub URL before reuse work. Framework: `docs/audits/mit-source-evaluation.md`.
- P0-2: WebSocket chart update verification — confirm OHLCVChart.tsx subscribes to real-time prices.
- P0-3: Screenshot capture: AskAiPanel mid-response, GlobalSearch command list, screener 100+ rows, instrument page with data.
- P0-4: DataTable row height validation — 22px compact empirical check under extended use.

**Status:** PENDING (MIT URL not provided; P0-2 through P0-4 deferred)

---

## Phase 1 — Token Enforcement and Design QA Gate ✅ IN PROGRESS

**Goal:** Eliminate token violations. Make violations impossible to reintroduce.

- **P1-1:** Fix `IntelligenceTab.tsx:114` — `bg-green-500/15 text-green-400` → `bg-positive/10 text-positive border-positive/20`. Also fix `organization` (blue → accent-ai).
- **P1-2:** Fix `confirm-dialog.tsx:109` — `bg-amber-500` → `bg-warning text-background hover:bg-warning/90`.
- **P1-3:** Fix `sheet.tsx:58` — `p-6 shadow-lg` → `p-3` (remove shadow).
- **P1-4:** Add ESLint `no-restricted-syntax` bans: `text-amber-*`, `text-green-*`, `text-red-*`, `text-blue-*`, `bg-green-*`, `bg-red-*`, `bg-amber-*`, `rounded-xl`, `rounded-2xl`, `p-6` in app/components/features.
- **P1-5:** Create `docs/DESIGN_QA_GATE.md`.
- **P1-7:** Add `terminal` Tabs variant (underline indicator, no pill background).
- **P1-8:** Badge already has `positive`, `negative`, `warning` variants ✅.

**Files:** `IntelligenceTab.tsx`, `confirm-dialog.tsx`, `sheet.tsx`, `tabs.tsx`, `.eslintrc.json`, `docs/DESIGN_QA_GATE.md`

**Acceptance criteria:**
- `pnpm lint` passes with zero banned-color violations.
- Instrument page tabs show amber underline, no pill background.

---

## Phase 2 — AI Panel Context Injection and Chat Page Redesign

**Goal:** Make AskAiPanel context-aware. Redesign Chat page as analyst tool.

### 2A: Context injection [VERIFIED GAP: AskAiPanel.tsx:144]
- P2A-1: Extend chat API type in `lib/api/chat.ts` to accept `system_context?: string`.
- P2A-2: Update `AskAiPanel.tsx` props: add `entityId?`, `ticker?`, `price?`, `priceChangePct?`.
- P2A-3: In `handleSend()`, construct and include `system_context` when props present.
- P2A-4: Wire props from instrument page CompanyOverview query into AskAiPanel.
- P2A-5: Change panel header "Ask AI" → "ANALYST".

### 2B: Citation display
- P2B-1: Parse SSE response for citation markers. Render `[1][2]` superscripts + Sources section.

### 2C: Chat page redesign
- P2C-1: Add `MarketContextBanner` above thread list.
- P2C-2: Add portfolio-scoped suggested research questions to empty state.
- P2C-3: Add entity quick-chips above input in active thread.
- P2C-4: Replace generic empty state copy.
- P2C-5: Add source citation rendering in full Chat thread.

**Files:** `AskAiPanel.tsx`, `lib/api/chat.ts`, `app/(app)/instruments/[entityId]/page.tsx`, `app/(app)/chat/page.tsx`, `components/chat/`

---

## Phase 3 — GlobalSearch Command Palette Extension

**Goal:** Full command palette for core analyst workflows.

- P3-1: Add "Pages" CommandGroup: Dashboard (G+D), Screener (G+S), Portfolio (G+P), Alerts (G+A), Chat, Settings.
- P3-2: Add "Quick Actions" CommandGroup: New Alert, Refresh All, Open AI Panel.
- P3-3: Add entity type badge to search results (Company / ETF / Index / Crypto).
- P3-4: Focus management: Escape → focus back to TopBar trigger.
- P3-5: Add `aria-label="Command palette"`, `aria-live="polite"` to results count.

**Files:** `GlobalSearch.tsx`, `lib/command-actions.ts`

---

## Phase 4 — AG Grid Installation and Screener Migration

**Goal:** Install AG Grid; migrate screener to institutional column features.

**AG Grid Usage Policy:**
- USE when: column pinning required, grouped column headers required, cell flash on live update required, saved column state required, row count > 10,000.
- USE TanStack Table when: ≤200 rows, no column pinning needed (watchlist, alerts, transactions).

Tasks:
- P4-1: `pnpm add ag-grid-react ag-grid-community` (Community — free).
- P4-2: Create `components/ui/ag-grid/AgGridBase.tsx` with terminal theme overrides.
- P4-3: Create `components/ui/ag-grid/ag-grid-theme.css`.
- P4-4: Migrate screener to AG Grid: pin TICKER column, add column state persistence.
- P4-5: Add 52W Range and Volume mock data stubs until backend delivers.

**Files:** `package.json`, `components/ui/ag-grid/`, `components/screener/`

---

## Phase 5 — Instrument Page Analyst Rail

**Goal:** Docked AnalystRail replacing floating AskAiPanel on instrument page.

- P5-1: Wrap instrument page in `PanelGroup` with `direction="horizontal"`.
- P5-2: Main content Panel + ResizeHandle + AnalystRail Panel (min=280px, default=320px, max=480px).
- P5-3: `AnalystRail` component: ANALYST header, chat thread, context summary strip.
- P5-4: Context summary strip: ticker + price + P/E + 52W range from CompanyOverview query.
- P5-5: Hide floating AskAiPanel trigger on instrument page when rail is open.

**Files:** `app/(app)/instruments/[entityId]/page.tsx`, `components/instrument/AnalystRail.tsx`

---

## Phase 6 — Portfolio Grid and Financial Tables Migration

**Goal:** Migrate portfolio holdings and financial statements to AG Grid.

- P6-1: Migrate `SemanticHoldingsTable` to AG Grid (pin TICKER, cell flash on live price update).
- P6-2: Add column state persistence for holdings (localStorage key: `worldview-holdings-cols`).
- P6-3: Migrate financial statements table (Income Statement / Balance Sheet / Cash Flow) to AG Grid.

**Files:** `components/portfolio/SemanticHoldingsTable.tsx`, `components/instrument/FinancialsTab.tsx`

---

## Phase 7 — Real-Time Price Updates

**Goal:** WebSocket price updates reach OHLCV chart last bar and AG Grid cell flash.

- P7-1: Verify OHLCVChart subscribes to AlertStreamContext for real-time price.
- P7-2: If not implemented: add `useEffect` in OHLCVChart to update last bar on price tick.
- P7-3: Wire `flashCells()` in AG Grid holdings/screener on each price tick.

**Files:** `components/instrument/OHLCVChart.tsx`, AG Grid grids

---

## Phase 8 — Visual QA, Accessibility, Performance, Polish

**Goal:** Pass the DESIGN_QA_GATE.md checklist.

- P8-1: Run lighthouse + axe on dashboard, instrument page, screener.
- P8-2: Verify all interactive elements have aria-labels.
- P8-3: Confirm no layout shift on data load (skeleton sizes match content).
- P8-4: Bundle size audit — confirm AG Grid Community ≤ 500KB gzipped.
- P8-5: Chromatic snapshot baseline for 5 highest-risk components.

---

## 48-Hour Action Plan (Quick Wins)

| # | Task | File | Time |
|---|------|------|------|
| 1 | Fix IntelligenceTab.tsx:114 token violation | `IntelligenceTab.tsx` | 15m |
| 2 | Fix confirm-dialog.tsx:109 token violation | `confirm-dialog.tsx` | 15m |
| 3 | Fix sheet.tsx:58 spacing violation | `sheet.tsx` | 10m |
| 4 | Add ESLint no-restricted-syntax bans | `.eslintrc.json` | 30m |
| 5 | Add terminal Tabs variant | `tabs.tsx` | 45m |
| 6 | Change AskAiPanel header "Ask AI" → "ANALYST" | `AskAiPanel.tsx` | 5m |
| 7 | Wire context injection into AskAiPanel POST body | `AskAiPanel.tsx`, `lib/api/chat.ts` | 2h |
| 8 | Add page navigation CommandGroup to GlobalSearch | `GlobalSearch.tsx` | 1h |
| 9 | Add entity type badge to search results | `GlobalSearch.tsx` | 30m |
| 10 | Add Quick Actions group to GlobalSearch | `GlobalSearch.tsx` | 30m |

**Total: ~5-6h of focused work**

---

## MIT Source Project

**Status:** BLOCKED — URL never provided. Cannot perform evaluation.
Framework ready at `docs/audits/mit-source-evaluation.md` once URL is confirmed.
