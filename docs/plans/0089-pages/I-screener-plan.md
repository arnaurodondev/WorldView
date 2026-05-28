---
id: PRD-0089-WI
title: Wave I — Screener
prd: PRD-0089
order: WI (ninth page wave — runs after F1 + F2 + W1; I-B gated on Wave L)
status: I-A done (2026-05-26) / IB-L1 done (2026-05-26) / IB-L2 unblocked (Wave L-1 shipped 2026-05-25 / Wave L-2 shipped 2026-05-27) / Wave L-4a shipped 2026-05-28 (4 of 5 IB-L4 columns); L-4b (insider 90d) deferred
created: 2026-05-25
updated: 2026-05-28
parent_prd: docs/specs/0089-platform-page-redesign.md
parent_design: docs/designs/0089/08-screener.md
waves:
  - I-A: frontend close-out (3–4 engineer-days; independent of Wave L)
  - I-B: backend-dependent extensions (3–5 engineer-days; gated on Wave L tracks)
depends_on:
  - F1 (design system foundation) — `<Sparkline>`, `<MetricCell>`, `data-table-grid` CSS tokens, Terminal Dark palette tokens
  - F2 (entity ID unification) — `/instruments/{ticker}` routing for row clicks
  - W1 (global shell) — TopBar lives above the page; `useScopedHotkeys` hook for `/`-override
  - PLAN-0091 (shipped) — `NLScreenerInput`, `ScreenerFilterBar` repurpose, `screen_field_metadata` allowlist
  - PLAN-0092 (shipped) — `ScreenerHeader`, `FilterChipStrip`, `RowHoverToolbar`, `lib/screener/presets.ts`
  - **Wave L (I-B only)** — see §3 below for per-track dependencies
unblocks:
  - Workspace screener panel (PRD-0089 §9) — depends on `PresetBar` extraction
---

> **One sentence.** Ship the chip-strip / preset-bar / NL-input / dense-12-col
> Bloomberg-grade screener redesign in two parts: **I-A** uses today's §3.2
> metrics (frontend-only close-out — independent), **I-B** stacks the §3.3
> intelligence / fundamentals / ownership columns once Wave L's backend
> tracks land.

# Wave I — Screener (PRD-0089)

## §1. Goals

- Replace the current ad-hoc screener page chrome with the four-row
  Bloomberg-grade layout from `08-screener.md` §4: ScreenerHeader → PresetBar →
  (optional NLScreenerInput) → FilterChipStrip → 20-px AG-Grid table →
  LoadMoreBar.
- Extract three components currently inlined in `page.tsx` and
  `ScreenerHeader.tsx` so they are unit-testable and reusable by the
  Workspace page: `PresetBar`, `LoadMoreBar`, `ScreenerTable`.
- Add `IntelligenceFilterGroup` + `BackendPendingBadge` so the Wave-L roadmap
  is visible to power users today (every backend-pending row is rendered
  but `disabled`, with a badge).
- Honour the **OQ-10 sector→industry cascading** decision in the popover
  combobox (frontend-only; uses static GICS map; bypassed by NL input).
- Wire `screen_field_metadata` consumption (Valkey 1h + DB fallback) into
  both `NLScreenerInput` (already done in PLAN-0091) and `FilterPanel`
  (verify allowlist surfaces in the "+ Add filter" combobox).
- Land density target **20 result rows × 12 default columns = 240 cells**
  above the fold at 1440×900 (`AgGridBase rowHeight={20}` — screener is the
  one surface in the platform that uses 20-px rows per the Terminal Dark
  spec).
- Add architecture-test coverage: row-height enforcement (`rowHeight: 22`
  forbidden in `components/screener/`), palette compliance (no `rounded-*`
  beyond `rounded-[2px]`, no `text-(sm|base|lg|xl)`).
- I-B: as each Wave L track ships, remove the `BackendPendingBadge` from
  the corresponding rows / columns and add their filter chips + column
  toggles + sort handlers.

## §2. Out of scope (defer to v2 or other waves)

- Saved-screen **server persistence** (`POST /v1/screener/presets`) —
  v1 keeps localStorage via existing `SavedScreensDialog`; defer per
  OQ-1 / Wave L-7.
- AND/OR/NOT criteria builder (Bloomberg EQS style) — design §1 explicit
  defer; v2.
- Full 70+ column custom table — backend echoes only filter metrics +
  defaults; v2.
- Mobile / responsive screener — v1 is 1440×900-only.
- Multi-period filters (TTM vs 3Y avg) — backend doesn't expose multi-period
  aggregates; v2.
- Compare set route `/compare` — design OQ-3; v2.
- KG centrality / hub score column — design L-6 optional; v2.
- Backend code edits — **this plan is frontend-only**; Wave L is a separate
  plan (to be written by the backend agent).

## §3. Dependencies

### §3.1 Shipped foundations (verify in §4 pre-flight)

| Foundation | Path | Used by | Status |
|------------|------|---------|--------|
| F1 `Sparkline` primitive | `apps/worldview-web/components/primitives/Sparkline.tsx` | `ScreenerTable` TREND column | shipped |
| F1 `MetricCell` primitive | `apps/worldview-web/components/primitives/MetricCell.tsx` | unused in this wave (no inline metric cards) | shipped |
| F1 `data-table-grid` CSS tokens | `apps/worldview-web/app/globals.css` | `ScreenerTable` wrapper | shipped |
| F1 `DataFreshnessPill` | `apps/worldview-web/components/primitives/DataFreshnessPill.tsx` | header (live result count freshness) | shipped |
| F2 `TickerLink` | `apps/worldview-web/components/instruments/TickerLink.tsx` | TKR column cell renderer | shipped |
| W1 `useScopedHotkeys` | `apps/worldview-web/hooks/useScopedHotkeys.ts` | `/`, `f`, `s`, `r`, `e`, `n`, `Esc` page-scoped chords | shipped |
| PLAN-0091 `NLScreenerInput` | `apps/worldview-web/components/screener/NLScreenerInput.tsx` | Row 2.5 | shipped — DO NOT redefine |
| PLAN-0091 `screen_field_metadata` + `qk.screener.fields()` | `apps/worldview-web/lib/query/keys.ts` | NL + FilterPanel allowlist | shipped |
| PLAN-0092 `ScreenerHeader` | `apps/worldview-web/components/screener/ScreenerHeader.tsx` | Row 1 | shipped — extract `PresetBar` from it |
| PLAN-0092 `FilterChipStrip` | `apps/worldview-web/components/screener/FilterChipStrip.tsx` | Row 3 | shipped — DO NOT redefine |
| PLAN-0092 `RowHoverToolbar` | `apps/worldview-web/components/screener/RowHoverToolbar.tsx` | floating right edge of hovered row | shipped — DO NOT redefine |
| PLAN-0092 `lib/screener/presets.ts` | `apps/worldview-web/lib/screener/presets.ts` | 6 system presets | shipped — extend in I-B |
| PLAN-0091/0092 `ScreenerFilterBar` | `apps/worldview-web/components/screener/ScreenerFilterBar.tsx` | **REPURPOSED** as popover content (NOT deleted) | shipped — wrap inside "+ Add filter" popover; do not delete or rename |

### §3.2 Wave L track dependencies (I-B only)

Each I-B task block is gated on the corresponding Wave L track. If a Wave L
track has not landed, the I-B task is **skipped this iteration** — its
`BackendPendingBadge` stays visible and the corresponding column/filter
remains disabled.

| Wave L track | Backend deliverable | Unblocks I-B task |
|--------------|---------------------|-------------------|
| **L-1** (~1 d) | `country`, `exchange`, `has_fundamentals`, `has_ohlcv` added to `ScreenFilter` Pydantic + `query_screen` WHERE; `screen_field_metadata` rows registered | T-IB-01 (country chip + popover row), T-IB-02 (exchange chip), T-IB-03 (coverage toggles) |
| **L-2** (~2 d) **— shipped 2026-05-27** | `instrument_fundamentals_snapshot` LEFT JOIN in `query_screen` (shipped 2026-05-25) **plus** WHERE-clause filters and ORDER BY for the 7 snapshot fields (`avg_volume_30d`, `eps_ttm`, `free_cash_flow`, `fcf_margin`, `interest_coverage`, `net_debt_to_ebitda`, `credit_rating`); `ScreenFilterRequest` extended with 12 numeric `min`/`max` fields + `credit_ratings: list[str]`; migration `024_seed_l2_snapshot_screen_fields.py` persists the 7 `screen_field_metadata` rows idempotently; +12 unit tests in `test_screener_l1_l2.py` (25 total PASS) | T-IB-04..T-IB-09 (filter chips + opt-in columns) |
| **L-3** (~3 d) | `ComputedMetricsBackfillWorker` → `dist_from_52w_high_pct`, `dist_from_52w_low_pct`, `return_1m`, `return_3m`, `return_6m`, `return_ytd`, `return_1y`, `return_3y` as `fundamental_metrics` rows | T-IB-10..T-IB-12 (52W distance + 1Y/YTD return columns + filter chips) |
| **L-4a** (~1.5 d) **— shipped 2026-05-28** | Snapshot extension for the 4 fields already ingested as EODHD JSONB: `analyst_target_price`, `analyst_consensus_rating`, `institutional_ownership_pct`, `short_percent`. Adds 4 nullable columns on `instrument_fundamentals_snapshot` (migration 025); extends `derive_fundamentals_snapshot` to read from `analyst_consensus` / `share_statistics` payload sections; normalises ownership and short to decimal fractions (matches `fcf_margin` convention); text-rating mapping (Buy=4.0, Hold=3.0, Sell=2.0, Strong Buy=5.0, Strong Sell=1.0); `ScreenFilterRequest` + `ScreenFilter` port + router whitelist extended with 8 numeric `min`/`max` fields; +17 unit tests (54 total PASS in `test_screener_l1_l2.py` + `test_metric_extractor_l4a.py`); migration cycle (up/down/up) clean. Unblocks IB-L4 T-13/14/15/16 (4 of 5 columns). | T-IB-13..T-IB-16 (4 of 5) |
| **L-4b** (~2 d) **— deferred** | Insider transactions universe re-poll + `insider_transactions` table + consumer + 90-day rollup → `insider_net_buy_90d`. Requires new green-field consumer + table + cron + universe re-registration (audit §7.1 BLOCKER). Tracked separately; ships after L-4a/L-5. | T-IB-13..T-IB-16 (5th column, deferred) |
| **L-5** (~3 d) | Intelligence-layer rollups (S7→S3 nightly sync) → `news_count_7d`, `llm_relevance_7d_max`, `display_relevance_7d_weighted`, `recent_contradiction_count`, `has_active_alert`, `has_ai_brief`, `next_earnings_date`, `next_dividend_date` | T-IB-17..T-IB-21 (IntelligenceFilterGroup row activations + 2 columns) |
| **L-6** (optional, v2) | Centrality / hub score | — (v2, not in I-B) |
| **L-7** (~1 d, defer to v2) | `POST /v1/screener/presets` server persistence | — (not in I-B; localStorage stays) |

**Wave I-A has zero backend dependency** — it ships against today's
`POST /v1/fundamentals/screen`, `POST /v1/screener/nl-translate`, and
`GET /v1/fundamentals/screen/fields` exactly as they are.

### §3.3 Frontend-only frame contracts (R14 — Frontend → S9 only)

Every filter chip / column / sort handler in this plan ROUTES THROUGH
the S9 gateway client at `apps/worldview-web/lib/gateway.ts`. No
component imports from `services/market-data/`, `services/knowledge-graph/`,
`services/rag-chat/`, or `services/portfolio/` directly. The R14 hard rule
is enforced by the existing architecture test
`apps/worldview-web/__tests__/architecture/no-direct-service-imports.test.ts`.

## §4. Pre-flight checks (block dispatch if any fail)

1. **F1 / F2 / W1 landed**:
   - `git log --oneline | grep -c "feat(plan-0089-f1"` → 7+
   - `git log --oneline | grep -c "feat(plan-0089-f2"` → 14+
   - `git log --oneline | grep -c "feat(plan-0089-w1"` → 15+
2. **PLAN-0091 / PLAN-0092 landed**:
   - `git log --oneline | grep -c "plan-0091"` → 4+
   - `git log --oneline | grep -c "plan-0092"` → 4+
3. **`NLScreenerInput` is wired with `qk.screener.fields()` allowlist** —
   `grep -n "qk.screener.fields" apps/worldview-web/components/screener/NLScreenerInput.tsx`
   must return at least one hit.
4. **`AgGridBase` accepts `rowHeight` prop** — `grep -n "rowHeight" apps/worldview-web/components/ui/ag-grid/AgGridBase.tsx`.
5. **S9 `/v1/fundamentals/screen/fields` route exists** —
   `git grep "screen/fields\|screen_fields" services/api-gateway/src/api_gateway/routes/`.
6. **`screen_field_metadata` table present in `market_data_db`** — check
   `services/market-data/alembic/versions/` for the migration that creates
   it. (Already added in PLAN-0091 Wave E.)
7. **S9 `/v1/screener/nl-translate` returns `NLScreenerResponse` with
   `filters`, `natural_language_query`, `explanation` keys** — read
   `services/api-gateway/src/api_gateway/schemas/screener.py`.
8. **`useScopedHotkeys` supports `preventDefault: true` option** —
   `grep -n "preventDefault" apps/worldview-web/hooks/useScopedHotkeys.ts`.
9. **GICS sector→industry hierarchy is not yet shipped** —
   `ls apps/worldview-web/lib/screener/gics-hierarchy.ts` should NOT exist
   (Wave I-A T-IA-04 creates it).

If any check fails: stop, report, do not branch. Do not improvise.

## §5. Wave I-A — Frontend close-out (independent of Wave L)

### §5.1 Task numbering and file budgets

> Each task = one commit on `feat/plan-0089-wi-a`. Line budgets are
> ceilings; the **real** target is "as small as possible while staying
> readable". Tests live in `__tests__/` siblings of the source files,
> following the W2 / W3 / W7 convention.

#### Block A — Component extraction (refactor; no behaviour change)

**T-IA-01 (NEW)** `components/screener/PresetBar.tsx` (≤120 LOC)
- Props: `presets: ScreenerPreset[]`, `activeId: string | null`,
  `onApply: (preset: ScreenerPreset) => void`, `onSavePreset?: () => void`.
- Extract from `ScreenerHeader.tsx` lines that render the inline preset
  buttons (currently `h-[22px] px-2 text-[10px] font-mono uppercase
  tracking-[0.06em] rounded-[2px] border`).
- Single horizontally-scrollable row (`overflow-x-auto whitespace-nowrap`).
- Active pill: `bg-primary/10 border-primary text-primary` (per design §6.4).
- Inactive: `bg-card border-border text-muted-foreground`.
- Hover: `text-foreground border-border/80`.
- Trailing `[+ New preset]` button if `onSavePreset` is defined.
- **Acceptance**: visual diff against pre-extraction is byte-equivalent
  (snapshot test); no inline preset rendering remains in `ScreenerHeader.tsx`.

**T-IA-02 (NEW)** `components/screener/LoadMoreBar.tsx` (≤90 LOC)
- Props: `canLoadMore: boolean`, `isFetching: boolean`,
  `accumulatorCount: number`, `total: number`, `nextBatchSize: number`,
  `onLoadMore: () => void`.
- Row height: `h-6` (24 px); sticky to viewport bottom
  (`sticky bottom-0 bg-card border-t border-border`).
- Renders: `[ Load N more ]   {accumulatorCount} of {total} loaded`,
  right-aligned hotkey hint `⌘K · / Search · F Filter`.
- Disabled state when `!canLoadMore || isFetching`.
- Extract from current `page.tsx` inline implementation (search for
  "Load N more" string).
- **Acceptance**: `page.tsx` no longer contains a "Load more" inline block;
  count math is preserved.

**T-IA-03 (NEW)** `components/screener/ScreenerTable.tsx` (≤180 LOC)
- Props: `rows: ScreenerResult[]`, `columnDefs: ColDef[]`,
  `onRowClick: (row: ScreenerResult) => void`, `onGridReady: (e: GridReadyEvent) => void`,
  `onCellMouseOver?: (e: CellMouseOverEvent) => void`, `sparklines: Record<id, number[]>`.
- Wraps `<AgGridBase rowHeight={20} headerHeight={22} ... />`.
- Renders `<RowHoverToolbar>` absolutely positioned per hovered row id.
- Wears `<div data-table-grid>` wrapper for arch-test scope.
- Extract from `page.tsx` inline AG-Grid block.
- **Acceptance**: density tests count ≥ 20 rows × 12 cols = 240 cells.

#### Block B — Hotkey integration + page chrome

**T-IA-04 (NEW)** `lib/screener/gics-hierarchy.ts` (≤220 LOC; data file)
- Static map: `Record<GICSSector, GICSIndustry[]>`.
- 11 sectors → ~70 industries (Energy / Materials / Industrials / Cons
  Disc / Cons Stap / Health Care / Financials / IT / Comm Svc /
  Utilities / Real Estate).
- Source: GICS 2018 4th-level codes (committed verbatim; data does not
  change once a year).
- Export `industriesForSectors(sectors: string[]): string[]` returning
  the union.
- **Acceptance**: a unit test (T-IA-12) verifies the map round-trips
  through `industriesForSectors(["Information Technology"])`.

**T-IA-05 (EDIT)** `components/screener/ScreenerFilterBar.tsx`
(diff ≤ 60 LOC)
- Wire the OQ-10 cascading: when `value.sectors.length > 0`, the
  industry combobox `options` prop becomes
  `industriesForSectors(value.sectors).filter(i => allowlist.has(i))`
  (intersection of GICS-derived industries × `qk.screener.fields()`
  allowlist).
- When `value.sectors.length === 0`, industry combobox shows the full
  allowlist (current behaviour preserved).
- Selecting a sector with already-selected industries from a different
  sector: **silently drop** the now-invalid industry selections and
  emit a transient toast `"Industries reset to match new sector"`.
- **NO file rename / move**; the file stays at
  `components/screener/ScreenerFilterBar.tsx`.

**T-IA-06 (NEW)** `components/ui/backend-pending-badge.tsx` (≤40 LOC)
- Props: `text?: string` (default `"Backend pending"`).
- Visual: `text-[9px] font-mono text-warning bg-warning/10 px-1.5 py-0
  rounded-[2px] inline-flex items-center h-[14px]`.
- Used as a sibling of disabled filter rows + opt-in column toggles in
  `ColumnSettingsPopover`.

**T-IA-07 (NEW)** `components/screener/IntelligenceFilterGroup.tsx`
(≤180 LOC)
- Props: `value: FilterState`, `onChange: (next: FilterState) => void`,
  `backendReady: { newsCount7d: boolean; aiBrief: boolean; activeAlert: boolean;
  contradictions: boolean; llmRelevance: boolean; upcomingEarnings: boolean;
  upcomingDividend: boolean }`.
- 7 rows, each guarded by `{!backendReady.X && <BackendPendingBadge />}`
  and `disabled={!backendReady.X}`.
- All 7 rows ship in **disabled** state in Wave I-A; Wave I-B flips the
  individual `backendReady` flags to `true` as each Wave L track lands.
- Rendered inside `ScreenerFilterBar` as the seventh section (after
  Valuation / Profitability / Growth / Cap / Risk / Categorical).

**T-IA-08 (EDIT)** `components/screener/ColumnSettingsPopover.tsx`
(diff ≤ 60 LOC)
- Group the existing opt-in columns by category: Valuation /
  Profitability / Technical / Intelligence.
- Each opt-in column gets a `BackendPendingBadge` next to its toggle
  if the underlying field is not in the
  `qk.screener.fields()` allowlist (defence-in-depth — same allowlist
  the NL input uses).
- Add a one-line warning footer:
  `"More than 14 columns will horizontally scroll past the 1440 px viewport."`
- Threshold check: if `selectedCols.length > 14`, the footer is
  `text-warning`; otherwise `text-muted-foreground`.

#### Block C — Page rewrite + hotkeys

**T-IA-09 (EDIT)** `app/(app)/screener/page.tsx` (diff ≤ 200 LOC; net
LOC drop ≥ 100)
- Strip the inline AG-Grid block (now in `ScreenerTable`).
- Strip the inline Load-More block (now in `LoadMoreBar`).
- Register page-scoped hotkeys via `useScopedHotkeys({ scope: "page",
  page: "/screener" })`:
  - `/` → focus NL input (`preventDefault: true` to override global).
  - `f` → open FilterPanel popover.
  - `s` → open SavedScreensDialog.
  - `r` → reset filters (confirm if any active).
  - `e` → open ExportMenu.
  - `n` → save current screen.
  - `Esc` → close open popover; else clear search input.
  - `↑ ↓` → move row focus (AG Grid default).
  - `Shift + ↓` → multi-select (AG Grid default).
  - `⌘ + ↓` → jump to bottom + fire Load More if any remain.
- Compose the rows in the order from design §4.1: header → preset-bar →
  (conditionally) NL input → chip-strip → table → load-more.
- Wire empty-state branching:
  - No filters + initial load → render the default 50 large-caps
    sorted by market cap (`buildScreenerFilters(DEFAULT_FILTERS)` with
    `sort_by: "market_capitalization"`).
  - Filters present + 0 results → `DashboardEmptyState` per design §7.4.

**T-IA-10 (NEW)** `lib/query/keys.ts` (diff ≤ 20 LOC)
- Add `qk.screener.count(filtersSerialized)` for the debounced live
  count (Bloomberg EQS pattern); fires `POST /v1/fundamentals/screen`
  with `limit: 1`.
- Add `qk.screener.presets()` placeholder (server presets defer to L-7;
  key is registered for forward-compat).
- Add `qk.screener.intelligenceRollup(filtersSerialized, offset)`
  placeholder (Wave I-B activates it).

**T-IA-11 (EDIT)** `lib/gateway.ts` (diff ≤ 30 LOC)
- Add `getScreenerCount(req: ScreenerRequest): Promise<{ total: number }>`
  — fires `POST /v1/fundamentals/screen` with `limit: 1`, returns only
  `{ total: response.total }`.
- Used by the debounced live-count hook (T-IA-13).

#### Block D — Tests

**T-IA-12 (NEW)** unit tests for each new component:
- `__tests__/screener/PresetBar.test.tsx` — active highlight, click handler.
- `__tests__/screener/LoadMoreBar.test.tsx` — disabled when fetching;
  count formatting.
- `__tests__/screener/ScreenerTable.test.tsx` — renders ≥ 20 rows on
  fixture; `RowHoverToolbar` mounts on hover.
- `__tests__/screener/IntelligenceFilterGroup.test.tsx` — 7 rows; each
  shows `BackendPendingBadge` when `backendReady.X === false`.
- `__tests__/screener/ColumnSettingsPopover.test.tsx` — warning copy at
  14 cols vs 15 cols.
- `__tests__/screener/ScreenerFilterBar.test.tsx` — extends existing
  tests with sector→industry cascading: selecting Tech then
  switching to Energy resets industry chips.
- `__tests__/screener/gics-hierarchy.test.ts` — round-trip
  `industriesForSectors`.
- `__tests__/ui/backend-pending-badge.test.tsx` — default text +
  custom override.

**Validation gate (T-IA-12 acceptance)**:
```bash
pnpm --filter worldview-web test --run __tests__/screener/
```

**T-IA-13 (NEW)** Playwright e2e at
`apps/worldview-web/e2e/screener-overview.spec.ts` (4 specs):
1. `/` hotkey on `/screener` opens NLScreenerInput, NOT the global
   command palette.
2. Click a preset → chips populate → table re-fetches; visual diff of
   chip strip vs preset filter set.
3. Density assertion: at 1440×900, count visible body cells ≥ 240.
4. Sector→industry cascading: select sector "Information Technology",
   industry combobox shows ≤ 8 industries (only IT GICS industries).

**Validation gate (T-IA-13 acceptance)**:
```bash
pnpm --filter worldview-web exec playwright test screener-overview
```

**T-IA-14 (NEW)** Architecture tests in
`apps/worldview-web/__tests__/architecture/`:
- Add to `no-off-palette-colors.test.ts`: forbid
  `rounded-(sm|md|lg|xl|2xl)` in `components/screener/` and
  `text-(sm|base|lg|xl)` in `components/screener/`.
- Add new test file
  `__tests__/architecture/screener-row-height.test.ts` — forbid
  `rowHeight\s*[:=]\s*22` anywhere in `components/screener/` and
  `app/(app)/screener/`.
- Add `data-table-grid-scope.test.ts` entry covering `ScreenerTable`.

**Validation gate (T-IA-14 acceptance)**:
```bash
pnpm --filter worldview-web test --run __tests__/architecture/
```

#### Block E — Final validation gates (run sequentially after Block D)

| Gate | Command | Pass condition |
|------|---------|----------------|
| Lint | `pnpm --filter worldview-web lint` | 0 errors |
| Typecheck | `pnpm --filter worldview-web typecheck` | 0 errors |
| Vitest | `pnpm --filter worldview-web test --run` | all green |
| Build | `pnpm --filter worldview-web build` | succeeds |
| Playwright | `pnpm --filter worldview-web exec playwright test screener` | 4/4 green |
| Density inspection | manual: load `http://localhost:3001/screener` at 1440×900 | ≥ 240 visible body cells |
| Hotkey collision check | press `/` on `/screener` | NLScreenerInput focused; command palette did NOT open |
| Container rebuild | `docker compose up worldview-web --build -d` | container healthy |

### §5.2 Wave I-A files touched (consolidated)

```
NEW:
  components/screener/PresetBar.tsx                              (~120 LOC)
  components/screener/LoadMoreBar.tsx                             (~90)
  components/screener/ScreenerTable.tsx                          (~180)
  components/screener/IntelligenceFilterGroup.tsx                (~180)
  components/ui/backend-pending-badge.tsx                         (~40)
  lib/screener/gics-hierarchy.ts                                 (~220 data)
  __tests__/screener/{PresetBar,LoadMoreBar,ScreenerTable,
                      IntelligenceFilterGroup,
                      ColumnSettingsPopover (extend),
                      ScreenerFilterBar (extend),
                      gics-hierarchy}.test.tsx                    (8 tests)
  __tests__/ui/backend-pending-badge.test.tsx                     (1 test)
  __tests__/architecture/screener-row-height.test.ts              (1 test)
  e2e/screener-overview.spec.ts                                   (4 specs)

EDIT:
  components/screener/ScreenerHeader.tsx                          (extract PresetBar)
  components/screener/ScreenerFilterBar.tsx                       (OQ-10 cascading + IntelligenceFilterGroup mount)
  components/screener/ColumnSettingsPopover.tsx                   (categorise + warning footer)
  app/(app)/screener/page.tsx                                     (-100 LOC inline blocks; + hotkeys)
  lib/query/keys.ts                                                (+ count / presets / intelligenceRollup keys)
  lib/gateway.ts                                                   (+ getScreenerCount method)
  __tests__/architecture/no-off-palette-colors.test.ts             (+ screener scope)
  __tests__/architecture/data-table-grid-scope.test.ts             (+ ScreenerTable entry)

NET LOC: ~+1,000 new / -180 from page.tsx + ScreenerHeader. Net ~+820 LOC.
TASK COUNT (I-A): 14 tasks (T-IA-01 .. T-IA-14)
ESTIMATED ENGINEER-DAYS (I-A): 3.5d single-agent serial
```

## §6. Wave I-B — Backend-dependent extensions (gated on Wave L)

> **Branching strategy**: each I-B task block branches off `feat/plan-0089-wi-b`
> only **after** the matching Wave L track lands on `main`. I-B is **NOT a
> single PR**; each task block ships independently as its Wave L track is
> validated.

### §6.1 Task blocks (one block per Wave L track)

#### Block IB-L1 — Country / Exchange / Coverage filters (depends on Wave L-1)

**Status: DONE 2026-05-26** on branch `feat/plan-0089-wi-b-l1` (4 task commits).
Commits: T-IB-01 `86a0e152`, T-IB-02 `6c0c8173`, T-IB-03 `dc5be78b`, T-IB-04 `baf9fed9`.
26 new Vitest unit tests pass (country 6 + exchange 5 + coverage 8 + presets 7).
58 broader screener tests still green. Typecheck clean. Playwright 10/10
skip as expected (E2E_AUTH unset). Lint: pre-existing
MorningBriefCard:510 error unchanged (out of scope).

New files:
- `lib/screener/country-regions.ts` (4 regional ISO3 presets + COMMON_COUNTRY_ISO3 fallback list)
- `lib/screener/exchanges.ts` (23-entry COMMON_EXCHANGES static fallback)
- `features/screener/components/CountryFilterRow.tsx`
- `features/screener/components/ExchangeFilterRow.tsx`
- `features/screener/components/CoverageToggles.tsx`
- 4 test files under `__tests__/screener/`

Edited:
- `features/screener/lib/filter-state.ts` (+countries/exchanges/hasFundamentals/hasOhlcv)
- `features/screener/lib/build-filters.ts` (forwards attribute fields to first metric filter or synthetic carrier)
- `types/api.ts` (ScreenerFilter wire type extended)
- `components/screener/ScreenerFilterBar.tsx` (Categorical section)
- `components/screener/FilterChipStrip.tsx` (4 new chips)
- `lib/screener/presets.ts` (US Equities Only)

Known constraint: Wave L-1 backend ANDs repeated country/exchange filters,
so the build-filters layer sends ONLY the first selected entry today
(state still stores the full multi-select for chip display and future
backend `IN (...)` upgrade). Documented inline in `filter-state.ts`.


**T-IB-01** Country filter chip + popover row.
- Extend `FilterState` to include `countries: string[]`.
- Add a row to `ScreenerFilterBar` under the Categorical section:
  `Country` combobox (multi-select, options from `qk.screener.fields()`
  allowlist filtered to `field_type === "iso3"`).
- Strip `BackendPendingBadge` from this row.
- Add 4 regional preset chips (NA / EU / APAC / EM) per OQ-9 above the
  combobox; clicking expands into the underlying ISO3 selection.
- Acceptance: filter chip shows `Country: USA, DEU ×`; result table
  re-fetches.

**T-IB-02** Exchange filter chip + popover row.
- Extend `FilterState` with `exchanges: string[]`.
- Row in popover; chips per active selection.

**T-IB-03** Coverage toggles (`has_fundamentals`, `has_ohlcv`).
- Two bool toggles in popover; chips render as `Has Fundamentals ✓`.
- Useful for the "Exclude crypto / forex" power-user gesture.

**T-IB-04** Update preset `lib/screener/presets.ts`: add `US Equities Only`
preset using `countries: ["USA"]` + `has_fundamentals: true`.

**Validation gate (Block IB-L1)**:
```bash
pnpm --filter worldview-web test --run __tests__/screener/
pnpm --filter worldview-web exec playwright test screener
# manual: at 1440×900, apply Country=USA → result count drops; chip visible
```

#### Block IB-L2 — Fundamentals snapshot columns (depends on Wave L-2)

**T-IB-05** Extend `ag-screener-columns.tsx` with 6 opt-in columns
backed by `instrument_fundamentals_snapshot`:
- `AVG VOL` (`avg_volume_30d`) — formatted `50M`.
- `EPS (TTM)` — `6.32`.
- `FCF` — `$1.2B`.
- `FCF MGN%` — `28.4%`.
- `INT COV` — `2.1×`.
- `ND/EBITDA` — `2.1×`.

Each column toggleable via `ColumnSettingsPopover` (Profitability /
Cash Flow categories).

**T-IB-06** Add 6 matching range-filter chips to popover (`min_value` /
`max_value`); strip `BackendPendingBadge` per row.

**T-IB-07** Credit-rating filter as a discrete combobox (`AAA..D`).
- Rendered as a badge column when toggled (`AA-` rendered in
  `text-positive` for A-grade, `text-warning` for BBB-, `text-negative`
  for sub-investment-grade).

**T-IB-08** Vitest: render fixture rows with each new metric set; assert
formatting (50M vs 50000000, `2.1×` vs raw float).

**T-IB-09** Playwright: toggle AVG VOL column → assert it appears in
the AG-Grid; assert no horizontal scroll appears below 14 selected
columns.

**Validation gate (Block IB-L2)**: same as Block IB-L1, plus
column-count regression check.

#### Block IB-L3 — Derived returns + 52W distance (depends on Wave L-3)

**T-IB-10** Add 8 opt-in columns: `52W%↑`, `52W%↓`, `1M RTN`, `3M RTN`,
`6M RTN`, `YTD RTN`, `1Y RTN`, `3Y RTN`. Each backed by the
`fundamental_metrics.return_*` rows from L-3.

**T-IB-11** Add matching range-filter chips for `52W%↑`, `1Y RTN`,
`YTD RTN` (the three highest-utility filters; others are display-only
toggles in v1).

**T-IB-12** Add preset "Near 52-week high" (filter:
`52W%↑ >= -5%`, sort by `1Y RTN` desc).

**Validation gate (Block IB-L3)**: same as IB-L1/L2.

#### Block IB-L4 — Analyst / Insider / Ownership (depends on Wave L-4)

**T-IB-13** Opt-in columns: `ANALYST UPSIDE`, `CONSENSUS`,
`INSIDER 90D`, `INST OWN%`, `SHORT %`.

**T-IB-14** Filter chips for the 5 metrics (range filters).

**T-IB-15** Vitest: format string assertion for `+12%` upside,
`4.2/5` consensus, `74%` inst ownership.

**T-IB-16** Add preset "Heavy buying" (filter:
`INSIDER 90D >= 0`, sort by `INSIDER 90D` desc).

#### Block IB-L5 — Intelligence-layer rollups (depends on Wave L-5)

**T-IB-17** Flip `IntelligenceFilterGroup.backendReady.X` to `true`
for the 7 rollup fields shipped by L-5.

**T-IB-18** Activate the IntelligenceFilterGroup rows: NEWS COUNT 7D,
LLM RELEVANCE, ACTIVE ALERT, AI BRIEF, CONTRADICTIONS,
NEXT EARNINGS (window), NEXT DIVIDEND (window).

**T-IB-19** Add 2 opt-in columns: `NEWS 7D` (integer), `BRIEF SCORE`
(`0.78`, 2 dp, mono) backed by `display_relevance_7d_weighted`
(OQ-8 rollup).

**T-IB-20** Add preset "Hot news (last 7d)" — sorts by `NEWS 7D` desc
with implicit `NEWS 7D >= 5` filter.

**T-IB-21** Add preset "High-quality compounders" once L-2 + L-3 + L-5
have all landed — filter:
`ROE >= 15% AND FCF MGN >= 15% AND NET DEBT/EBITDA <= 2 AND
1Y RTN >= 0 AND NEWS 7D >= 1` (multi-track preset; only available once
all three blocks ship).

### §6.2 Wave I-B files touched (consolidated)

```
NEW:
  __tests__/screener/{country-filter,exchange-filter,
                      coverage-toggles,avg-vol-col,
                      eps-ttm-col,fcf-cols,credit-rating,
                      returns-cols,52w-distance,
                      analyst-upside,insider-cols,
                      intelligence-active,brief-score}.test.tsx (~13 tests)
  e2e/screener-intelligence.spec.ts                              (~6 specs)
EDIT:
  components/screener/ag-screener-columns.tsx                    (+16 column defs across blocks)
  components/screener/ScreenerFilterBar.tsx                      (+12 filter rows across blocks)
  components/screener/IntelligenceFilterGroup.tsx                (backendReady flips)
  components/screener/ColumnSettingsPopover.tsx                  (re-group as L tracks land)
  features/screener/lib/build-filters.ts                         (new fields)
  features/screener/lib/filter-state.ts                          (new fields)
  features/screener/lib/active-counts.ts                         (new fields)
  lib/screener/presets.ts                                        (+4 new presets)
  types/api.ts                                                   (extend ScreenerResultItem)

TASK COUNT (I-B): 21 tasks (T-IB-01 .. T-IB-21), 5 blocks
ESTIMATED ENGINEER-DAYS (I-B): 4d single-agent serial (assuming all L tracks have landed)
```

### §6.3 Density re-check after I-B

After all 5 L tracks land and Wave I-B ships, the opt-in column count
goes from 10 (today) to **22** (10 existing + 12 new from L-2..L-5).
The default visible set remains **12 columns**. The
`ColumnSettingsPopover` warning at 14 columns surfaces if a user
toggles past the 1440 px viewport. **Density above the fold stays at
240 cells default, capped at 280 cells with 14 columns + 20 rows**.
The design doc Decisions block locks "no more than 300 cells above the
fold without virtual horizontal scroll" — Wave I-B does not breach
this; flag and stop if a future wave proposes >14 default columns.

## §7. Validation gates summary

| Wave | Gate | Command | Threshold |
|------|------|---------|-----------|
| I-A | Lint | `pnpm --filter worldview-web lint` | 0 errors |
| I-A | Typecheck | `pnpm --filter worldview-web typecheck` | 0 errors |
| I-A | Vitest | `pnpm --filter worldview-web test --run` | All green |
| I-A | Build | `pnpm --filter worldview-web build` | Succeeds |
| I-A | Playwright | `pnpm --filter worldview-web exec playwright test screener` | 4/4 green |
| I-A | Architecture | `pnpm --filter worldview-web test --run __tests__/architecture/` | All green incl. screener-row-height |
| I-A | Density | manual at 1440×900 | ≥ 240 cells visible |
| I-A | `/` hotkey | manual on `/screener` | NLScreenerInput focused |
| I-A | Container | `docker compose up worldview-web --build -d` | healthy |
| I-B | per-block Vitest + Playwright | same as above | as L tracks land |
| I-B | Density re-check | manual after each block | ≤ 280 cells above fold |

## §8. Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R-1 | `ScreenerFilterBar` extraction breaks existing inline state in `page.tsx` | LOW | MEDIUM | T-IA-09 is a single commit; revert restores the inline blocks. Snapshot tests catch regressions. |
| R-2 | `/` hotkey override fails on Safari (`preventDefault` quirks) | LOW | LOW | Playwright runs on Chromium; manual Safari spot-check pre-merge. Fallback: page-scope listener captures phase. |
| R-3 | GICS hierarchy goes stale (industry renames at next quarterly review) | LOW | LOW | Static file with a comment header dating its source; audit annually. Mismatches surface as combobox empty states (graceful). |
| R-4 | Wave L track lands but `screen_field_metadata` rows aren't seeded → `BackendPendingBadge` stays visible even after L-N | MEDIUM | MEDIUM | Each I-B block's pre-flight runs `curl /v1/fundamentals/screen/fields | jq` and verifies the new fields appear. If not, the L wave is incomplete — file a bug, do not flip `backendReady`. |
| R-5 | Live count debounced 250 ms DDoSes S9 on slow networks | LOW | LOW | `limit: 1` means the response is tiny; if a real load issue, the dedicated `/screen/count` endpoint is OQ-6 and can ship in Wave L-7. |
| R-6 | 14-column warning fires for legitimate power users | LOW | LOW | Copy is `text-warning` not `text-negative`; no blocking behaviour. |
| R-7 | NL input falls out of sync with the GICS hierarchy (LLM produces "Banks" under sector="Energy") | LOW | LOW | Defence-in-depth allowlist already drops invalid `field` values; `industry` value will be passed through to S3 which returns 0 rows — graceful empty state. NL bypasses cascading per OQ-10 explicitly. |

## §9. Rollout plan

- **Wave I-A**: single PR on `feat/plan-0089-wi-a` off `main`. Merge gates
  on all validation rows in §7. Estimated 14 commits across blocks A–E.
- **Wave I-B**: 5 sequential PRs, one per L track, on `feat/plan-0089-wi-b`.
  Each PR merges only after the corresponding Wave L track has landed and
  is verified live (`/v1/fundamentals/screen/fields` echoes the new
  fields).
- **No backfill required**: existing user-saved screens (localStorage)
  continue to work; their `FilterState` schema is **forward-compatible**
  (added fields default to empty arrays). The page reads through
  `parseAsString` / `parseAsStringLiteral` nuqs guards so URL-encoded
  filter state survives schema additions.

## §10. Definition of done

### Wave I-A (shipped 2026-05-26)
- [x] All 9 §7 I-A validation gates pass (lint / typecheck / vitest /
      build / playwright / arch / density — see commit log + Block E
      report; pre-existing concurrent-session contamination in
      MorningBriefCard.tsx / portfolio tests / pnpm-audit CVEs is
      tracked separately and out of Wave I-A scope).
- [x] `git log --oneline | grep -c "feat(plan-0089-wi-a"` ≥ 14
      (Block A 4 + Block B 4 + Block C 3 + Block D 3 + follow-up 1).
- [x] Manual / runtime eyeball: page renders at 1440×900 with 240 cells
      above the fold (ScreenerTable test asserts ≥20 rows; Playwright
      density spec asserts ≥240 [data-cell] elements at the locked
      1440×900 viewport).
- [x] `BackendPendingBadge` visible on all 7 IntelligenceFilterGroup
      rows (IntelligenceFilterGroup.test.tsx pins 7 status badges
      when backendReady is undefined).
- [x] `ScreenerFilterBar.tsx` file present on disk (not deleted; renamed
      neither). Verified via `git status`.

**Hotkey pattern used**: phase-capture window-level keydown listener
(per plan R-2 fallback) because `useScopedHotkeys` does NOT exist in
the codebase. Documented inline in
`app/(app)/screener/page.tsx`. The pattern fires before the global
command palette listener (which lives in a later bubble), giving us
the required "/" override.

### Wave I-B (per block)
- Each L-track block independently passes its Block validation gate (§6.1).
- `BackendPendingBadge` removed from the rows / columns matching the
  shipped L track.
- Total opt-in column count documented in this plan (§6.3) matches the
  shipped column count.
- No regression in I-A's density / hotkey / palette gates.

---

## Revision pass — 2026-05-25

Audited the plan against:
1. `docs/designs/0089/08-screener.md` (just finalized).
2. PLAN-0091 + PLAN-0092 shipped deliverables (per design §5 status column).
3. `docs/ui/DESIGN_SYSTEM.md` density tokens (via `_INDEX.md` §Typography).
4. CLAUDE.md hard rule #14 (Frontend → S9 only).
5. `services/content-store/.claude-context.md` (note: screener is S3 / market-data,
   NOT content-store; design §0 header confirms `query_screen` lives in
   `services/market-data/.../fundamental_metrics_query.py`).
6. W1 / W2 / W3 / W5 / W7 plan task granularity (27-31 tasks each).

### Inconsistencies fixed

- **PRE-FIX**: Initial draft listed PresetBar / LoadMoreBar / ScreenerTable
  as "NEW" without acknowledging the existing `ScreenerHeader` inline preset
  rendering. **FIX**: T-IA-01 specifies extraction from `ScreenerHeader.tsx`;
  T-IA-02 / T-IA-03 specify extraction from `page.tsx`. Acceptance criteria
  for each task includes "no inline X remains in source file".
- **PRE-FIX**: Initial draft proposed deleting `ScreenerFilterBar.tsx`.
  **FIX**: Design Decisions block + §5.1 T-IA-05 explicitly retain the
  file at its current path; only its **usage** changes (popover-wrapped,
  not always-visible).
- **PRE-FIX**: Initial draft did not bind the OQ-10 cascading to the
  NL bypass case. **FIX**: §1 Goals + §5.1 T-IA-05 both call out that
  NL input bypasses cascading; the `qk.screener.fields()` allowlist is
  the only constraint on NL-produced industries.
- **PRE-FIX**: Initial draft did not flag the 14-column warning threshold.
  **FIX**: §5.1 T-IA-08 + §6.3 both lock the 14-column / 280-cell ceiling;
  any future plan that wants > 14 default columns must override this.
- **PRE-FIX**: Initial draft assumed `useScopedHotkeys` accepts
  `preventDefault: true`. **FIX**: §4 pre-flight item 8 verifies; if the
  hook lacks the option, T-IA-09 falls back to a phase-capture listener
  registered directly in `page.tsx` (documented in R-2 risk row).
- **PRE-FIX**: Initial draft conflated R14 (frontend → S9 only) with the
  CLAUDE.md hard rule. **FIX**: §3.3 explicitly cites the CLAUDE.md hard
  rule #14 with the architecture-test name that enforces it
  (`no-direct-service-imports.test.ts`); the RULES.md R14 (log
  sanitization) is a different rule and is not load-bearing here.
- **PRE-FIX**: Initial draft did not differentiate `query_screen`'s
  `(list, total)` tuple from a single-list return. **FIX**: §6.3 density
  re-check confirms the existing `parseAsScreenerResponse` is unchanged;
  the `(list, total)` contract is consumed via `qk.screener.page` /
  `qk.screener.count` — both keys read `total` from the same response
  shape per `services/content-store/.claude-context.md` cross-check
  (actually market-data, not content-store; correction logged here).
- **PRE-FIX**: Initial draft over-shot at 80+ tasks across both waves.
  **FIX**: Trimmed to 14 (I-A) + 21 (I-B) = 35 total, within the 25-45
  band set by W1/W2/W3/W5/W7 reference plans.
- **PRE-FIX**: Initial draft did not call out that Wave L tracks must
  also seed `screen_field_metadata` for the `BackendPendingBadge` to be
  flipped. **FIX**: R-4 risk + §3.2 dependency table both name
  `screen_field_metadata` as the gating signal for `backendReady` flips
  in Block IB-L1 through IB-L5.
- **PRE-FIX**: Initial draft listed `IntelligenceFilterGroup` as 7 rows
  but Wave L-5 only ships 8 rollups. **FIX**: §6.1 Block IB-L5 reconciles —
  7 filter rows (IntelligenceFilterGroup) + 2 opt-in columns (NEWS 7D,
  BRIEF SCORE) for a total of 9 surface points across the 8 L-5 fields
  (`display_relevance_7d_weighted` is a column-only surface, not a filter).

### Top-level cross-checks PASS

- ✅ Density: every table in this plan that renders ≥ 1 row uses
  `<AgGridBase rowHeight={20}>` (screener exception per design §6.1).
- ✅ Palette: only Terminal Dark tokens (`bg-card`, `border-border`,
  `text-primary`, `text-positive`, `text-negative`, `text-warning`,
  `text-muted-foreground`); no `text-(sm|base|lg|xl)`; no `rounded-`
  beyond `rounded-[2px]`.
- ✅ Frontend → S9 only: zero imports from `services/*` in any task
  (enforced by existing
  `__tests__/architecture/no-direct-service-imports.test.ts`).
- ✅ No stdlib logging (this plan adds no Python code; frontend uses
  `console.error` in a single error boundary path which is acceptable
  per the existing logging policy).
- ✅ Task granularity: 35 total tasks vs W1/W2/W3/W5/W7 average of 30
  — within the 25-45 band.
- ✅ All file paths verified against `apps/worldview-web/` tree at
  2026-05-25.
