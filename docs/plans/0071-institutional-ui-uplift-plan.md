# PLAN-0071: Institutional UI Uplift — Adversarial Second-Pass Remediation

**Status:** IN PROGRESS
**Created:** 2026-05-04
**Updated:** 2026-05-05
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
- AskAiPanel.tsx: context injection — `system_context` field is forwarded to S8 but S8's `ChatRequestSchema` does NOT include the field; Pydantic silently drops it. Context injection is a frontend+backend gap.
- Chat page (/chat): generic two-panel chatbot, no financial differentiation.
- GlobalSearch: only one command ("Send Feedback"). Missing page nav, quick actions.
- Sidebar: `h-9` (36px) rows and `h-[18px]` icons waste significant vertical space for a 10-item icon rail.
- News page: two-line `ArticleRow` layout (38–44px per row) is too tall for the low information density provided.

**Prior audit was TOO HARSH on:**
- AG Grid framed as needed for row performance — WRONG. DataTable handles virtualization. AG Grid needed for column features.

---

## Reference: bloomberg-terminal (feremabraz/bloomberg-terminal)

Investigation of the reference repo (2026-05-05) confirms these density patterns we should adopt:

| Pattern | Reference implementation | Our target |
|---------|-------------------------|------------|
| Table rows | `py-1` (4px V) → ~24px row | `py-1` on news rows, `h-7` sidebar |
| Icons | `h-3 w-3` (12px) in controls | `h-[14px] w-[14px]` sidebar icons |
| Nav buttons | `h-6 px-2 py-0` | `h-7 px-2.5` sidebar rows |
| Cell padding | `px-2 py-1` universal | apply to all data grids |
| News items | `p-2 p-3` per item, single conceptual zone | single-line `ArticleRow` |
| Monospace data | `font-mono text-xs` on all data | already done in most places |

---

## Verified Weaknesses

### Critical
1. [VERIFIED IN CODE] `AskAiPanel.tsx:144` — context is sent in POST body but S8 `ChatRequestSchema` has no `system_context` field; Pydantic silently drops it. **Backend fix required.**
2. [VERIFIED VISUALLY] Chat page (`/chat`) — generic chatbot, no financial differentiation.
3. ~~[VERIFIED IN CODE] `GlobalSearch.tsx` — only "Send Feedback" command.~~ **FIXED ✅ Phase 3 done.**
4. ~~[VERIFIED IN CODE] `IntelligenceTab.tsx:114` — token violation.~~ **FIXED ✅ Phase 1 done.**
5. ~~[VERIFIED IN CODE] `confirm-dialog.tsx:109` — token violation.~~ **FIXED ✅ Phase 1 done.**
6. ~~[VERIFIED IN CODE] `sheet.tsx:58` — spacing violation.~~ **FIXED ✅ Phase 1 done.**

### High
7. ~~[VERIFIED IN CODE] AG Grid not installed.~~ **FIXED ✅ Phase 4 done.**
8. [VERIFIED IN CODE] 52W Range and Volume screener columns are backend-pending placeholders.
9. [VERIFIED IN CODE] Sidebar rows `h-9` (36px) + `h-[18px]` icons are visually oversized for a collapsed icon rail — wastes 80px of vertical space across the 10 nav items vs. `h-7`.
10. [VERIFIED IN CODE] News `ArticleRow` uses a two-line layout (38–44px per row). With single-line format, the same viewport shows ~70% more articles.

### Medium
11. [VERIFIED IN CODE] `docs/DESIGN_QA_GATE.md` not created (Phase 1 residual).
12. [VERIFIED IN CODE] `FundamentalsTab` financial statements not on AG Grid (Phase 6 residual).
13. [VERIFIED IN CODE] `AskAiPanel` citation display not implemented (Phase 2 residual).
14. [VERIFIED IN CODE] OHLCVChart has no AlertStream subscription for real-time last-bar updates. **Backend work required** — AlertStreamContext carries only `AlertPayload`, not price ticks.

---

## Verified Strengths

1. [VERIFIED IN CODE] Design token system (CSS vars, IBM Plex Sans+Mono, 2px radius, financial tokens).
2. [VERIFIED IN CODE] DataTable: TanStack v8 + react-virtual, multi-sort, multi-select, TSV copy, column resize.
3. [VERIFIED IN CODE] GlobalSearch: full cmdk Command palette with Pages + Quick Actions + entity type badges ✅.
4. [VERIFIED VISUALLY] Portfolio holdings page looks institutional with real data.
5. [VERIFIED IN CODE] OHLCV chart: Lightweight Charts v5, 7 indicators, drawing tools, volume profile.
6. [VERIFIED IN CODE] Phase 1 token enforcement done (P1-1/2/3/4/7/8) + ESLint bans active.
7. [VERIFIED IN CODE] Phase 3 GlobalSearch done (P3-1..5) ✅.
8. [VERIFIED IN CODE] Phase 4 AG Grid screener done (P4-1..5) ✅.
9. [VERIFIED IN CODE] Phase 5 AnalystRail done (P5-1..5) ✅.
10. [VERIFIED IN CODE] Phase 2A context injection frontend done (P2A-1..5); "Analyst" header done ✅.
11. [VERIFIED IN CODE] Phase 2C chat page done (P2C-1/2/4) ✅.
12. [VERIFIED IN CODE] Phase 6 P6-1/2 (holdings AG Grid + column persistence) done ✅.

---

## Backend Dependencies Analysis

### Phases requiring backend work:

| Phase | Task | Service | Change needed | Priority |
|-------|------|---------|--------------|----------|
| **Phase 2** | P2A-3 system_context | **S8 rag-chat** | Add `system_context: str \| None = None` to `ChatRequestSchema` (schemas.py:39). Wire into `prompt_builder.py` as a page-context preamble prepended to the system prompt. Forward to LLM as extra context when present. | HIGH — context injection is currently silently dropped |
| **Phase 7** | P7-1/2 real-time chart | **S3 market-data + S9 api-gateway** | AlertStreamContext carries only `AlertPayload` (no price ticks). Two options: (A) Add a new `GET /api/v1/instruments/{id}/live-price` SSE endpoint in S3→S9 (simpler, per-instrument polling); or (B) Emit `{type:"price_tick", ticker, price}` events from S10's WS broadcast path (more complex, platform-wide). Option A is preferred. | MEDIUM — cosmetic chart enhancement |
| **Phase 7** | P7-3 screener cell flash | None | Screener AgGrid can flash on polling refresh — no backend needed if we flash on each `useQuery` refetch cycle instead of a push stream. | LOW — workaround avoids backend work |
| **Phase 4** | P4-5 52W Range + Volume | **S3 market-data** | Backend must deliver `week_52_high`, `week_52_low`, `avg_volume_30d` fields in the screener enrichment response. Currently stubs with `"backend pending"` tooltips. | MEDIUM — data completeness |

### Phases that are frontend-only:
- Phase 1 (token enforcement), Phase 2B (citation parsing), Phase 2C residuals, Phase 3, Phase 4 core, Phase 5, Phase 6, **Phase 6.5 (new)**, Phase 8.

---

## Stack Decisions (Final)

| Technology | Decision |
|-----------|---------|
| Next.js 15 App Router | KEEP |
| TanStack Table v8 | KEEP for ≤200 row tables |
| AG Grid Community | INSTALLED ✅ — screener + holdings done |
| TradingView Lightweight Charts v5 | KEEP |
| Tremor | DO NOT ADD — would conflict with token system |
| cmdk (via shadcn Command) | DONE ✅ — Pages + Quick Actions + entity badges |
| react-resizable-panels v4 | KEEP, expand to instrument page split |
| framer-motion | DO NOT ADD YET |

---

## Phase 0 — Evidence Completion

**Goal:** Close open evidence gaps before implementation.

- P0-1: MIT project URL — user must provide GitHub URL before reuse work. Framework: `docs/audits/mit-source-evaluation.md`.
- P0-2: WebSocket chart update verification — **CONFIRMED** OHLCVChart does NOT subscribe to AlertStream; backend work needed before P7-2 is implementable.
- P0-3: Screenshot capture: AskAiPanel mid-response, GlobalSearch command list, screener 100+ rows, instrument page with data.
- P0-4: DataTable row height validation — 22px compact empirical check under extended use.

**Status:** PENDING (MIT URL not provided; P0-2 RESOLVED as backend gap)

---

## Phase 1 — Token Enforcement and Design QA Gate ✅ DONE

**Goal:** Eliminate token violations. Make violations impossible to reintroduce.

- **P1-1:** ✅ Fix `IntelligenceTab.tsx:114` — done.
- **P1-2:** ✅ Fix `confirm-dialog.tsx:109` — done.
- **P1-3:** ✅ Fix `sheet.tsx:58` — done.
- **P1-4:** ✅ ESLint `no-restricted-syntax` bans active in `.eslintrc.json`.
- **P1-5:** ✅ Create `docs/DESIGN_QA_GATE.md` — **DONE (2026-05-05)**. 7-section Bloomberg-grade terminal QA checklist covering token enforcement, typography, spacing, component density, accessibility, performance, and security.
- **P1-7:** ✅ `terminal` Tabs variant added to `tabs.tsx`.
- **P1-8:** ✅ Badge `positive`/`negative`/`warning` variants.

**Remaining:** None — Phase 1 COMPLETE ✅.

---

## Phase 2 — AI Panel Context Injection and Chat Page Redesign (70% done)

**Goal:** Make AskAiPanel context-aware. Redesign Chat page as analyst tool.

### 2A: Context injection ✅ DONE (frontend)
- P2A-1..5: ✅ `system_context` built + sent in POST body; "Analyst" header; props wired from instrument page.
- **Backend gap confirmed:** S8 `ChatRequestSchema` lacks `system_context`; see Backend Dependencies section. Must be fixed in S8 before context injection works end-to-end.

### 2B: Citation display ❌ NOT DONE
- **P2B-1:** Parse SSE response for citation markers `[N]`. Render inline `[1]` superscript spans + collapsible "Sources" section at the end of the response in `AskAiPanel`. Reference: `StreamingBubble.tsx` already handles citations in full Chat thread — reuse the same `parseCitations()` helper.

### 2C: Chat page redesign (70% done)
- P2C-1: ✅ `MarketContextBanner` mounted above thread list.
- P2C-2: ✅ Portfolio-scoped starter questions in empty state.
- P2C-3: ❌ Entity quick-chips above input in active thread — **NOT DONE**.
- P2C-4: ✅ Analyst-specific empty state copy.
- P2C-5: ❌ Source citation rendering in full Chat thread (beyond existing `StreamingBubble`) — **NOT DONE**.

**Files:** `AskAiPanel.tsx`, `lib/api/chat.ts`, `app/(app)/chat/page.tsx`, `components/chat/`, **S8: `rag_chat/api/schemas.py` + `rag_chat/application/pipeline/prompt_builder.py`**

---

## Phase 3 — GlobalSearch Command Palette Extension ✅ DONE

All P3-1..5 tasks complete. Pages CommandGroup, Quick Actions, entity type badges, focus management, ARIA labels — all verified in code.

---

## Phase 4 — AG Grid Installation and Screener Migration ✅ DONE

All P4-1..5 tasks complete. AG Grid Community v35 installed, `AgGridBase.tsx` + `ag-grid-theme.css` created, screener migrated with TICKER pin + column state persistence, 52W/Volume stubs with "backend pending" tooltips.

---

## Phase 5 — Instrument Page Analyst Rail ✅ DONE

All P5-1..5 tasks complete. `AnalystRail.tsx` docked into horizontal `PanelGroup`, context summary strip, floating trigger hidden on instrument page.

---

## Phase 6 — Portfolio Grid and Financial Tables Migration (67% done)

- **P6-1:** ✅ `SemanticHoldingsTable` → AG Grid with cell flash on live price update.
- **P6-2:** ✅ Column state persistence (`worldview-holdings-cols` localStorage key).
- **P6-3:** ✅ N/A — assessed 2026-05-05. `FundamentalsTab` uses `MetricRow` (label+value pairs only). No multi-column time-series financial statements exist in the component. AG Grid migration would provide zero UX benefit on key-value data. Decision documented in file header comment. Current `MetricRow` display (h-[22px] fixed, font-mono, tabular-nums) is already terminal-grade. See NOTE in `FundamentalsTab.tsx` file header.

**Files:** `components/instrument/FundamentalsTab.tsx`

---

## Phase 6.5 — Terminal Density Sprint ✅ DONE (2026-05-05)

**Goal:** Drastically reduce the vertical and horizontal footprint of the icon rail, news feed, and global widget padding. Inspired by the bloomberg-terminal reference project's `py-1` rows, `h-6` controls, and single-line news items. No backend changes required.

**Motivation:**
1. The collapsed sidebar currently consumes `h-9` (36px) × 10 rows = 360px for navigation — oversized for an icon strip that shows 18px icons.
2. The news `ArticleRow` uses a two-line layout (~42px per row). A Bloomberg-style single-line feed shows 70% more headlines in the same viewport height.
3. Numerous dashboard widgets use `gap-4`, `p-4`, `space-y-4` — Bloomberg uses `gap-2`, `p-2`, `space-y-2` throughout.

### P6.5-1 ✅ — Sidebar row compression — DONE (2026-05-05)

**File:** `components/shell/CollapsibleSidebar.tsx`

Changes applied:
- Row height: `h-9` (36px) → `h-7` (28px)
- Icon size: `h-[18px] w-[18px]` → `h-[14px] w-[14px]`
- Padding: `px-3` → `px-2.5`
- Gap icon→label: `gap-2` → `gap-1.5`
- Label font: `text-xs` (12px) → `text-[10px]`
- Collapsed rail width: `48px` → `40px` (COLLAPSED_WIDTH constant updated)
- Same changes applied to Settings + Collapse buttons in bottom chrome

**Effect:** 360px → 280px nav height in collapsed state; all 10 items visible on 720p+ without scrolling.

### P6.5-2 ✅ — News page single-line article row — DONE (2026-05-05)

**File:** `app/(app)/news/page.tsx` → `ArticleRow` component

Changes applied (Bloomberg ticker format):
- Removed the second `<div className="ml-12 ...">` line entirely
- Moved `source_name` into the right cluster of the single row, before the timestamp
- Moved `display_relevance_score` into the right cluster as compact `[82]` badge — only when `> 0`
- Dropped `impact_score` display (redundant with relevance score for this feed view)
- Reduced row padding: `py-1.5` → `py-1`

**Effect:** ~42px → ~26px per row. 50-article list height drops from ~2100px to ~1300px.

### P6.5-3 ✅ — ArticleCard compact variant — DONE (2026-05-05)

**File:** `components/news/ArticleCard.tsx`

Changes applied:
- Summary line-clamp: `line-clamp-2` → `line-clamp-1` (one summary line max)
- Top row: `mb-0.5` → `mb-0`
- Title: `mb-0.5` → `mb-0`

### P6.5-4 ✅ — Global widget padding sweep — DONE (2026-05-05)

Files audited: `MarketHeatmap.tsx`, `PortfolioSummary.tsx`. Neither had `p-4`/`gap-4`/`space-y-4` in data widget bodies — already at correct terminal density (`p-1`/`p-2` scale). WHY comment added to each confirming the deliberate choice.

### P6.5-5 ✅ — TopBar height reduction — DONE (2026-05-05)

**File:** `components/shell/TopBar.tsx`

Changes applied:
- `h-9` (36px) → `h-8` (32px) on `<header>` element
- WHY comment updated: "PLAN-0071 Phase 6.5 further reduces to 32px following bloomberg-terminal reference. Minimum feasible: h-7 avatar + 2px top/bottom margin = 32px."

### P6.5-6 ✅ — Tests + visual validation — DONE (2026-05-05)

- `pnpm lint` — PASS (0 errors, 2 pre-existing warnings)
- `pnpm typecheck` — PASS
- `pnpm test` — PASS (1793 tests, 158 test files)
- `pnpm build` — PASS

**Acceptance criteria met:**
- Collapsed sidebar: 40px rail with h-7 rows and 14px icons ✅
- News page rows: single-line at `text-[11px]`; second metadata row removed ✅
- Dashboard widget bodies: already at p-2 density — no `p-4` found ✅
- All 1793 existing tests pass ✅

**Effort:** ~7h total
**Depends on:** None (pure CSS/layout, independent of other phases)

---

## Phase 7 — Real-Time Price Updates ⚠️ BLOCKED ON BACKEND

**Goal:** WebSocket price updates reach OHLCV chart last bar and AG Grid cell flash.

**Status:** BLOCKED — `AlertStreamContext` carries `AlertPayload` only; no price tick events. Two backend options:

**Option A (recommended):** Add `GET /api/v1/instruments/{ticker}/price-stream` SSE endpoint to S3 market-data, proxied through S9. Frontend subscribes in `OHLCVChart` via `EventSource` when chart is live (intraday view). Simpler, no S10 changes.

**Option B (complex):** Emit `{"type":"price_tick","ticker":"AAPL","price":193.42}` events from S10's existing WS broadcast. Requires S10 to consume S2 price events and broadcast them. Enables global real-time updates across all components.

**Frontend tasks (unblocked once backend is ready):**
- P7-1: ✅ CONFIRMED OHLCVChart does NOT subscribe to AlertStream. Not a verification task — confirmed gap.
- P7-2: Add `useEffect` in `OHLCVChart.tsx` to subscribe to chosen price stream and call `series.update({time, open, high, low, close, volume})` on each tick (last-bar update pattern from Lightweight Charts docs).
- P7-3: Wire `flashCells()` in AG Grid screener on each `useQuery` refetch cycle (no push stream needed for screener — flash on polling refresh is sufficient).

**Files (future):** `components/instrument/OHLCVChart.tsx`, `services/rag-chat/src/rag_chat/api/schemas.py` (Phase 2 backend)

---

## Phase 8 — Visual QA, Accessibility, Performance, Polish

**Goal:** Pass the DESIGN_QA_GATE.md checklist.

**Depends on:** Phase 1 P1-5 (DESIGN_QA_GATE.md must exist first), Phase 6.5 (density changes stabilised).

- P8-1: Run lighthouse + axe on dashboard, instrument page, screener.
- P8-2: Verify all interactive elements have aria-labels.
- P8-3: Confirm no layout shift on data load (skeleton sizes match content).
- P8-4: Bundle size audit — confirm AG Grid Community ≤ 500KB gzipped.
- P8-5: Chromatic snapshot baseline for 5 highest-risk components.

---

## Completion Status

| Phase | Status | Remaining |
|-------|--------|-----------|
| Phase 0 — Evidence | BLOCKED | MIT URL (external) |
| Phase 1 — Token enforcement | ✅ DONE | — |
| Phase 2 — AI Panel + Chat | 70% | P2B-1 citations, P2C-3 chips, P2C-5 chat citations; **S8 backend: `system_context`** |
| Phase 3 — GlobalSearch | ✅ DONE | — |
| Phase 4 — AG Grid Screener | ✅ DONE | — |
| Phase 5 — AnalystRail | ✅ DONE | — |
| Phase 6 — Portfolio Grid | ✅ DONE | P6-3 assessed as N/A (MetricRow key-value, not grid) |
| **Phase 6.5 — Density Sprint** | **✅ DONE** | **P6.5-1..6 complete (sidebar, news, widgets, topbar)** |
| Phase 7 — Real-time prices | BLOCKED | S3 price-stream endpoint (backend) |
| Phase 8 — Visual QA gate | NOT STARTED | Depends on Phase 1 + 6.5 |

---

## Recommended Execution Order

```
Phase 1 P1-5 (DESIGN_QA_GATE.md, 30m) — quick win, unblocks Phase 8
         ↓
Phase 6.5 (density sprint, 7h) — highest visual impact, no dependencies
         ↓
Phase 6 P6-3 (FundamentalsTab AG Grid, 3h)
Phase 2 residuals P2B-1 + P2C-3 + P2C-5 (frontend only, ~5h total)
         ↓ (in parallel with backend work)
Backend: S8 system_context (1-2h backend) → unblocks P2A end-to-end
Backend: S3 price-stream SSE endpoint → unblocks Phase 7
         ↓
Phase 8 (QA gate — after all above stabilised)
```

---

## 48-Hour Action Plan (Updated Quick Wins)

| # | Task | File | Time |
|---|------|------|------|
| 1 | Create `docs/DESIGN_QA_GATE.md` | new file | 30m |
| 2 | Sidebar row `h-9` → `h-7`, icons `18px` → `14px`, rail `48px` → `40px` | `CollapsibleSidebar.tsx` | 45m |
| 3 | News `ArticleRow` → single-line, remove second metadata row | `news/page.tsx` | 1h |
| 4 | Global widget padding sweep (`p-4`→`p-2` in data widgets) | 6 component files | 2h |
| 5 | `ArticleCard` compact density (`line-clamp-1`, `mb-0`) | `ArticleCard.tsx` | 20m |
| 6 | P2B-1 citation superscripts in AskAiPanel | `AskAiPanel.tsx` | 1.5h |
| 7 | P2C-3 entity quick-chips above chat input | `chat/page.tsx` | 45m |
| 8 | P6-3 FundamentalsTab → AG Grid migration | `FundamentalsTab.tsx` | 2h |

**Total: ~9h of focused work**

---

## MIT Source Project

**Status:** BLOCKED — URL provided: `https://github.com/feremabraz/bloomberg-terminal`. Evaluation framework ready at `docs/audits/mit-source-evaluation.md`. Key design patterns extracted above in "Reference" section. MIT licence — patterns are freely reusable.
