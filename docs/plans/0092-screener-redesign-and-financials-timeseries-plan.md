---
id: PLAN-0092
title: Screener Redesign (W8) + FundamentalsTimeseriesChart (C-1)
prd: PRD-0089 / PLAN-0091 C-1 + F-2
status: draft
created: 2026-05-23
updated: 2026-05-23
---

# PLAN-0092 — Screener Redesign (W8) + FundamentalsTimeseriesChart (C-1)

## Overview

PRD reference: `docs/designs/0089/08-screener.md` (iter-2, 2026-05-23) and
`docs/designs/0089/06-instrument-financials.md` (iter-4, 2026-05-23)

Covers all remaining frontend + backend work from design docs 06 and 08:
1. **Backend complete** (already applied): `NLScreenerResponse.explanation` field + updated LLM system prompt (R-001 Option A fix in `schemas/screener.py` + `routes/market.py`)
2. **Wave A** — TypeScript types + backend unit tests for the explanation field
3. **Wave B** — `FundamentalsTimeseriesChart` component + keys.ts rename + Financials tab wiring
4. **Wave C** — Screener column additions (4 new default + 3 opt-in)
5. **Wave D** — Screener page structural redesign (PresetBar, FilterChipStrip, ScreenerHeader, FilterPanel refactor, ScreenerPage orchestrator reduction)
6. **Wave E** — NLScreenerInput + RowHoverToolbar + full integration

**Services affected**: `services/api-gateway` (tests), `apps/worldview-web`
**No DB migrations.** No new S9 endpoints in this plan (screener columns are echoed from existing screen response; FundamentalsTimeseriesChart uses existing `/v1/fundamentals/timeseries`).

## Sub-Plans

| Sub-Plan | Description | Depends On | Waves | Est. Effort |
|----------|-------------|------------|-------|-------------|
| A | Backend tests + TypeScript types for explanation | none (backend already done) | A | 1h |
| B | FundamentalsTimeseriesChart | A (keys.ts rename) | B | 2h |
| C | Screener column additions | A (TS types) | C | 1.5h |
| D | Screener page structural redesign | C (new columns already in ag-grid) | D | 3h |
| E | NLScreenerInput + RowHoverToolbar | D (redesigned page) | E | 2h |

**Total estimated effort**: ~9.5h

---

## Wave A: Backend tests + TypeScript types

**Goal**: Close the test gap for the `explanation` field shipped in the backend (already in code). Add the TypeScript type so the frontend can reference it type-safely.
**Depends on**: none
**Estimated effort**: 1h
**Architecture layer**: API (tests + types)

### Tasks

#### T-A-01: TypeScript `NLScreenerResponse` type + `gateway.ts` method

**Type**: impl
**depends_on**: none
**blocks**: [T-E-01]
**Target files**:
- `apps/worldview-web/types/api.ts`
- `apps/worldview-web/lib/gateway.ts`

**What to build**:
Add `NLScreenerResponse` interface to `types/api.ts` with the three fields the backend now returns. Add a `translateNLScreenerQuery(query: string)` method to the gateway client that calls `POST /v1/screener/nl-translate`.

**Interface** (from `schemas/screener.py`):
```ts
export interface NLScreenerResponse {
  /** Structured filter conditions; keys validated against screen/fields allowlist. */
  filters: Record<string, unknown>;
  /** Echo of the original user query. */
  natural_language_query: string;
  /** LLM-generated plain-English description of the screen (e.g. "Profitable tech stocks, P/E below 20"). */
  explanation: string;
}

export interface NLScreenerRequest {
  query: string;
}
```

**Gateway method** (add to `lib/gateway.ts`):
```ts
async translateNLScreenerQuery(query: string): Promise<NLScreenerResponse> {
  return this.post<NLScreenerResponse>("/v1/screener/nl-translate", { query });
}
```

**Acceptance criteria**:
- [ ] `NLScreenerResponse` exported from `types/api.ts`
- [ ] `translateNLScreenerQuery` on gateway client, TypeScript compiles clean

---

#### T-A-02: api-gateway unit tests for `nl_screener_translate` with explanation

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**:
- `services/api-gateway/tests/routes/test_market.py` (or equivalent test for the NL endpoint)

**What to build**:
Unit tests for the updated `nl_screener_translate` endpoint covering:
- New two-key format: LLM returns `{"explanation": "...", "filters": {...}}` → response includes `explanation`
- Legacy flat format: LLM returns `{"pe_ratio": {"lte": 20}}` → explanation defaults to `""`
- `_unparseable` → 422
- Invalid field names → 422 with list of bad fields
- LLM service 502 → 502 propagated

**Tests to write**:
| Test | What it verifies | Type |
|------|-----------------|------|
| `test_nl_translate_new_format_returns_explanation` | explanation populated from two-key LLM response | unit |
| `test_nl_translate_legacy_format_explanation_empty` | flat filter dict → explanation="" | unit |
| `test_nl_translate_unparseable_returns_422` | `_unparseable` flag → 422 | unit |
| `test_nl_translate_invalid_fields_returns_422` | fields not in allowlist → 422 | unit |
| `test_nl_translate_llm_502_propagates` | S8 error → 502 | unit |

**Acceptance criteria**:
- [ ] ≥5 new tests pass
- [ ] `python -m pytest tests/ -k nl_screener -v` green

---

### Validation Gate — Wave A
- [ ] ruff + mypy clean on `api-gateway`
- [ ] `NLScreenerResponse` exported from `types/api.ts`; TypeScript compiles
- [ ] ≥5 new api-gateway tests passing

---

## Wave B: FundamentalsTimeseriesChart

**Goal**: Build the `FundamentalsTimeseriesChart` component and wire it into the Financials tab. Rename the stale `fundamentalsTimeseries(id, period)` key to `fundamentalsTimeseries(id, metric)`.
**Depends on**: Wave A (keys.ts rename)
**Estimated effort**: 2h
**Architecture layer**: Frontend (component + hook + layout)

### Pre-read (agent must read before starting)
- `docs/designs/0089/06-instrument-financials.md` §6.7 (visual spec + period_type table)
- `apps/worldview-web/lib/query/keys.ts` (line ~187 for current key)
- `apps/worldview-web/components/instrument/financials/FinancialsTab.tsx`
- `apps/worldview-web/components/instrument/financials/EarningsBarChart.tsx` (place chart after this)
- `apps/worldview-web/components/instrument/financials/PeerComparisonTable.tsx` (place chart before this)
- `services/market-data/src/market_data/api/routers/fundamental_metrics.py` lines 44-100 (endpoint params)

### Tasks

#### T-B-01: `FundamentalsTimeseriesChart` component (NEW)

**Type**: impl
**depends_on**: none
**blocks**: [T-B-03]
**Target files**:
- `apps/worldview-web/components/instrument/financials/FundamentalsTimeseriesChart.tsx` (NEW)
- `apps/worldview-web/components/instrument/financials/__tests__/FundamentalsTimeseriesChart.test.tsx` (NEW)

**What to build**:
A 280px × 80px SVG line chart (full left-column width via `w-full`) with a metric chip selector and period chips. Self-fetching via `qk.instruments.fundamentalsTimeseries`.

**Props**:
```ts
interface FundamentalsTimeseriesChartProps {
  instrumentId: string;
  defaultMetric?: string; // defaults to "pe_ratio"
}
```

**Metric chip strip** (11 metrics, `text-[10px]` chips, horizontal scroll on overflow):
| Chip label | Backend metric | period_type |
|-----------|---------------|-------------|
| P/E | `pe_ratio` | QUARTERLY |
| P/B | `pb_ratio` | QUARTERLY |
| P/S | `price_sales_ttm` | QUARTERLY |
| EV/EBITDA | `enterprise_value_ebitda` | QUARTERLY |
| Fwd P/E | `forward_pe` | SNAPSHOT |
| Rev Growth | `quarterly_revenue_growth_yoy` | QUARTERLY |
| EPS Growth | `quarterly_earnings_growth_yoy` | QUARTERLY |
| Net Margin | `profit_margin` | QUARTERLY |
| Op Margin | `operating_margin_ttm` | QUARTERLY |
| ROE | `roe_ttm` | ANNUAL |
| Div Yield | `dividend_yield` | SNAPSHOT |

**Period chips**: 1Y / 3Y / 5Y — translate to `start_date` (today minus N years). Always pass `order=asc`.

**Fetch** (uses `qk.instruments.fundamentalsTimeseries(id, metric)` — after rename in T-B-02):
```ts
const { data, isLoading } = useQuery({
  queryKey: qk.instruments.fundamentalsTimeseries(instrumentId, selectedMetric),
  queryFn: () =>
    gateway.get<TimeseriesResponse>(
      `/v1/fundamentals/timeseries`,
      { instrument_id: instrumentId, metric: selectedMetric,
        period_type: PERIOD_TYPE_MAP[selectedMetric],
        start_date: periodStart, order: "asc" }
    ),
  staleTime: 60 * 60 * 1000, // 1h
});
```

**SVG line chart** (`h-[80px] w-full`):
- Polyline `stroke: var(--foreground) stroke-width: 1.5`, no fill
- 3 horizontal guide lines at 25/50/75% of Y range: `stroke: var(--border)`
- X-axis labels: `text-[9px] text-muted-foreground` at Jan of each visible year
- TTM annotation: `text-[9px] font-mono text-foreground` right-aligned on last data point
- 5Y avg dashed line: `stroke-dasharray: 4 2 stroke: var(--muted-foreground)/50`
- Section header: `text-[10px] uppercase tracking-[0.08em] text-muted-foreground` "METRIC HISTORY"

**States**:
- Loading: single `bg-muted/30 animate-pulse h-[80px] w-full rounded-none` skeleton
- Empty (data length = 0): `text-[11px] text-muted-foreground` centered "Historical data unavailable"
- Error: inline `text-[11px] text-muted-foreground` "Failed to load — retry"

**Tests**:
| Test | What it verifies | Type |
|------|-----------------|------|
| `renders loading skeleton` | skeleton visible while isLoading | unit |
| `renders empty state` | "Historical data unavailable" on empty array | unit |
| `renders SVG polyline` | polyline element present with >1 data points | unit |
| `metric chip switches data` | clicking P/B chip updates queryKey to `pb_ratio` | unit |
| `period chip updates start_date` | clicking 3Y computes correct start_date | unit |

**Acceptance criteria**:
- [ ] Chart renders P/E by default with 1Y period
- [ ] All 11 metric chips switch data without full component remount
- [ ] `period_type` and `order=asc` params sent correctly per metric
- [ ] Empty state + loading state render correctly
- [ ] ≥5 Vitest tests pass

---

#### T-B-02: Rename `fundamentalsTimeseries(id, period)` → `fundamentalsTimeseries(id, metric)` in keys.ts

**Type**: impl
**depends_on**: none
**blocks**: [T-B-01]
**Target files**:
- `apps/worldview-web/lib/query/keys.ts` (line ~187)
- Any file that calls `qk.instruments.fundamentalsTimeseries` — grep for it

**What to build**:
Rename the second parameter from `period` to `metric` and update the cache array slot name from `"fundamentals-ts", period` to `"fundamentals-ts", metric`. Then grep for all existing call sites and update them.

```ts
// Before:
fundamentalsTimeseries: (instrumentId: string, period: string) =>
  [QK_VERSION, "instruments", "detail", instrumentId, "fundamentals-ts", period] as const,

// After:
fundamentalsTimeseries: (instrumentId: string, metric: string) =>
  [QK_VERSION, "instruments", "detail", instrumentId, "fundamentals-ts", metric] as const,
```

**Acceptance criteria**:
- [ ] `grep -r "fundamentalsTimeseries" apps/worldview-web/` shows no remaining calls with `period` semantics
- [ ] TypeScript compiles clean

---

#### T-B-03: Wire `FundamentalsTimeseriesChart` into `FinancialsTab.tsx`

**Type**: impl
**depends_on**: [T-B-01, T-B-02]
**blocks**: none
**Target files**:
- `apps/worldview-web/components/instrument/financials/FinancialsTab.tsx`

**What to build**:
Import `FundamentalsTimeseriesChart` and place it in the left column between `EarningsBarChart` and `PeerComparisonTable` (per design doc §5.3 orchestrator ordering). Pass `instrumentId`.

**Left column ordering** (per design §5.3):
1. `DenseMetricsGrid`
2. `IncomeStatementTable`
3. `EarningsBarChart`
4. **`FundamentalsTimeseriesChart`** ← insert here
5. `PeerComparisonTable`
6. `InsiderTransactionsTable`
7. `InstitutionalHoldersTable`

**Acceptance criteria**:
- [ ] Chart visible on Financials tab in the correct position
- [ ] Playwright screenshot shows chart between EarningsBarChart and PeerComparisonTable

---

### Validation Gate — Wave B
- [ ] ruff + mypy clean (backend not touched)
- [ ] TypeScript compiles clean after keys.ts rename
- [ ] `qk.instruments.fundamentalsTimeseries` has `metric` param everywhere
- [ ] ≥5 Vitest tests for `FundamentalsTimeseriesChart`
- [ ] Chart renders on Financials tab (manual verification)

---

## Wave C: Screener column additions

**Goal**: Add the 4 new default columns and 3 opt-in columns to the screener without touching page layout (that's Wave D).
**Depends on**: Wave A (TS types)
**Estimated effort**: 1.5h
**Architecture layer**: Frontend (data layer + column definitions)

### Pre-read
- `apps/worldview-web/components/screener/ag-screener-columns.tsx`
- `apps/worldview-web/components/screener/ColumnSettingsPopover.tsx`
- `docs/designs/0089/08-screener.md` §3.4 (column specs + color rules)

### Tasks

#### T-C-01: 4 new default columns in `ag-screener-columns.tsx`

**Type**: impl
**depends_on**: none
**blocks**: [T-D-05]
**Target files**:
- `apps/worldview-web/components/screener/ag-screener-columns.tsx`

**What to build**:
Add 4 new `ColDef` entries and replace the existing "REVENUE" column with "REV YoY":

| Column | Field | Format fn | Color rule |
|--------|-------|-----------|------------|
| FWD PE | `forward_pe` | `toFixed(1) + "×"` | `text-foreground`; `—` if null |
| DIV Y% | `dividend_yield` | `(v * 100).toFixed(2) + "%"` | `text-foreground`; `—` if null |
| ROE% | `roe_ttm` | `(v * 100).toFixed(1) + "%"` | positive (>15) / negative (<0) / foreground |
| REV YoY | `quarterly_revenue_growth_yoy` | `(v>0?"+":"") + (v*100).toFixed(1) + "%"` | positive (>0) / negative (<0) / foreground |

Remove existing "REVENUE" (`revenue`) column entirely (absolute revenue is not useful on the screener).

Column pixel widths from design §4.1: FWD PE=64, DIV Y=64, ROE=64, REV YoY=76.

**Tests**:
| Test | What it verifies | Type |
|------|-----------------|------|
| `formats forward_pe null as dash` | null → `"—"` | unit |
| `formats roe_ttm positive green` | >0.15 → positive class | unit |
| `formats quarterly_revenue_growth sign` | positive has `+` prefix | unit |
| `formats dividend_yield percent` | 0.0245 → "2.45%" | unit |

---

#### T-C-02: 3 opt-in columns + `ColumnSettingsPopover` registration

**Type**: impl
**depends_on**: none
**blocks**: [T-D-05]
**Target files**:
- `apps/worldview-web/components/screener/ag-screener-columns.tsx`
- `apps/worldview-web/components/screener/ColumnSettingsPopover.tsx`

**What to build**:
Add 3 more `ColDef` entries (hidden by default via `hide: true`), registered in `ColumnSettingsPopover` under an "Optional" section:

| Column | Field | Format | Notes |
|--------|-------|--------|-------|
| OP MGN% | `operating_margin_ttm` | `(v*100).toFixed(1)+"%"` | green if >20 |
| EV/EBITDA | `enterprise_value_ebitda` | `toFixed(1)+"×"` | text-foreground |
| AVG VOL | `avg_volume_30d` | `formatVolume(v)` | text-foreground; note: backend must add this field to screen response; render `—` until available |

In `ColumnSettingsPopover`, add an "OPTIONAL COLUMNS" section below the existing list with these three. Each has a toggle that calls AG Grid's `setColumnVisible`.

**Acceptance criteria**:
- [ ] Opening `ColumnSettingsPopover` shows an "OPTIONAL COLUMNS" section with 3 items
- [ ] Toggling a column shows/hides it in the AG Grid table

---

### Validation Gate — Wave C
- [ ] TypeScript compiles clean
- [ ] ≥4 Vitest tests for column formatters
- [ ] No existing tests broken (REVENUE column removed — update any test that references it)
- [ ] Optional columns visible in ColumnSettingsPopover

---

## Wave D: Screener page structural redesign

**Goal**: Decompose `screener/page.tsx` (currently 410 lines) into extracted components matching the design doc. Replaces `ScreenerFilterBar.tsx` with `FilterChipStrip.tsx` + `FilterPanel.tsx` popover.
**Depends on**: Wave C (new columns already in ag-grid colDefs)
**Estimated effort**: 3h
**Architecture layer**: Frontend (page + composition components)

### Pre-read
- `apps/worldview-web/app/(app)/screener/page.tsx` (full file — understand current structure)
- `apps/worldview-web/components/screener/ScreenerFilterBar.tsx` (to be replaced/deleted)
- `docs/designs/0089/08-screener.md` §4 layout, §5 component breakdown, §6 visual spec, §7 interaction, §8 data fetching

### Tasks

#### T-D-01: `ScreenerHeader.tsx` (NEW)

**Type**: impl
**depends_on**: none
**blocks**: [T-D-05]
**Target files**:
- `apps/worldview-web/components/screener/ScreenerHeader.tsx` (NEW ~80 lines)

**What to build**:
Row 1 — page title + live result count + buttons. Extracted from the existing inline toolbar in `page.tsx`.

```ts
interface ScreenerHeaderProps {
  total: number;
  loaded: number;
  isLive: boolean;
  columns: ColumnState[];
  onColumnsChange: (cols: ColumnState[]) => void;
  rows: ScreenerResult[];
  exportColumns: ColDef[];
  onOpenSaved: () => void;
}
```

Renders: `"SCREENER • {loaded} / {total} match"` at `text-[10px] uppercase` + live dot + `ColumnSettingsPopover` + `SavedScreensDialog` trigger + `ExportMenu`.

---

#### T-D-02: `PresetBar.tsx` + `lib/screener/presets.ts` (NEW)

**Type**: impl
**depends_on**: none
**blocks**: [T-D-05]
**Target files**:
- `apps/worldview-web/components/screener/PresetBar.tsx` (NEW ~120 lines)
- `apps/worldview-web/lib/screener/presets.ts` (NEW ~120 lines)

**What to build**:
Row 2 — horizontally scrollable pill list of saved presets. `presets.ts` exports 6 system presets as `FilterState` literals:

| Preset | Filters |
|--------|---------|
| Quality stocks | `roe_ttm >= 0.15, profit_margin >= 0.10, debt_equity <= 1.0` |
| Cheap & growing | `pe_ratio <= 20, quarterly_revenue_growth_yoy >= 0.10` |
| High dividend | `dividend_yield >= 0.03` |
| Top by score | sort by `market_impact_score desc` |
| Recent earnings | filter by upcoming earnings (date filter) |
| Heavy buying | `insider_buy_90d > 0` (stub — renders disabled with "data pending" tooltip) |

Pill styling from design §6.4: `rounded-[2px]`, h=22px, `bg-card border border-border text-muted-foreground` default; `bg-primary/10 border-primary text-primary` for active preset.

---

#### T-D-03: `FilterChipStrip.tsx` (NEW — replaces `ScreenerFilterBar.tsx`)

**Type**: impl
**depends_on**: none
**blocks**: [T-D-05]
**Target files**:
- `apps/worldview-web/components/screener/FilterChipStrip.tsx` (NEW ~140 lines)

**What to build**:
Row 3 — one chip per active filter from `FilterState`, an "+ Add filter" combobox trigger, `Save…` and `Reset` action buttons.

```ts
interface FilterChipStripProps {
  filters: FilterState;
  onRemove: (field: string) => void;
  onAddFilter: () => void;
  onSave: () => void;
  onReset: () => void;
}
```

Chip styling from design §6.4: `rounded-[2px]`, h=20px, `bg-primary/10 border-primary/60 text-primary`. Label includes operator inline (`P/E ≤ 25`). Trailing `×` (lucide X, 12px) removes the filter. Clicking the chip body opens `FilterPanel` scrolled to that section.

---

#### T-D-04: `FilterPanel.tsx` refactor

**Type**: impl
**depends_on**: none
**blocks**: [T-D-03, T-D-05]
**Target files**:
- `apps/worldview-web/components/screener/FilterPanel.tsx` (REFACTOR existing)

**What to build**:
Refactor the existing `ScreenerFilterBar` 6-section filter grid into a popover-compatible component. Keep the `Section` + `RangeInput` sub-components. Drop the toolbar wrapper. Add `open` + `onOpenChange` props so it mounts inside a Radix `Popover.Content`. The popover slides in below Row 3 with `max-h-[220px]` overflow-y-auto.

Panel animates via `grid-template-rows: 0fr → 1fr`, 150ms ease-out (DESIGN_SYSTEM §0.5 approved).

---

#### T-D-05: `ScreenerPage` orchestrator reduction

**Type**: impl
**depends_on**: [T-D-01, T-D-02, T-D-03, T-D-04]
**blocks**: [T-E-03]
**Target files**:
- `apps/worldview-web/app/(app)/screener/page.tsx` (REWRITE — reduce from 410 → ~250 lines)
- `apps/worldview-web/components/screener/ScreenerFilterBar.tsx` (DELETE)

**What to build**:
Replace the existing monolith with the extracted components. Page owns: `appliedFilters`, `offset`, `accumulator`, AG Grid ref. Renders: `ScreenerHeader` → `PresetBar` → `FilterChipStrip` (→ `FilterPanel` popover) → AG Grid / `ScreenerTable` → `LoadMoreBar`.

Delete `ScreenerFilterBar.tsx` entirely after migration.

Wire live result count: debounced 250ms `POST /v1/fundamentals/screen` with `limit: 1` using `qk.screener.count(filters)`, update count in `ScreenerHeader` continuously as user adjusts FilterPanel.

**Hotkeys** (via `useScopedHotkeys`, registered on mount):
- `/` — open/focus `NLScreenerInput` (overrides global handler; see design §7.1)
- `f` — open FilterPanel popover
- `s` — open SavedScreensDialog
- `r` — reset filters (confirm if any set)
- `e` — open ExportMenu
- `n` — save current screen
- `Esc` — close open popovers

**Acceptance criteria**:
- [ ] `page.tsx` ≤ 250 lines
- [ ] `ScreenerFilterBar.tsx` deleted
- [ ] All existing screener Vitest tests pass (update import paths where needed)
- [ ] Live count debounced 250ms visible in ScreenerHeader while FilterPanel open

---

### Validation Gate — Wave D
- [ ] TypeScript compiles clean
- [ ] All existing screener tests pass (after updating for deleted `ScreenerFilterBar`)
- [ ] `ScreenerFilterBar.tsx` no longer exists in the repo
- [ ] `page.tsx` ≤ 250 lines
- [ ] Screener page renders correctly in dev server (manual smoke test)
- [ ] All hotkeys work (manual: `/`, `f`, `r`, `Esc`)

---

## Wave E: NLScreenerInput + RowHoverToolbar

**Goal**: Add the NL screener bar and the hover-row mini-toolbar, completing the full W8 design.
**Depends on**: Wave D (redesigned page), Wave A (TypeScript types)
**Estimated effort**: 2h
**Architecture layer**: Frontend (feature components + integration)

### Pre-read
- `docs/designs/0089/08-screener.md` §4.1a (NL input visual spec), §7 (hover behaviour), §8.5 (mutation code)
- `apps/worldview-web/app/(app)/screener/page.tsx` (current state after Wave D)
- `apps/worldview-web/lib/gateway.ts` (`translateNLScreenerQuery` from T-A-01)
- `apps/worldview-web/lib/query/keys.ts` (`qk.screener.fields()`)

### Tasks

#### T-E-01: `NLScreenerInput.tsx` (NEW)

**Type**: impl
**depends_on**: [T-A-01]
**blocks**: [T-E-03]
**Target files**:
- `apps/worldview-web/components/screener/NLScreenerInput.tsx` (NEW ~120 lines)
- `apps/worldview-web/components/screener/__tests__/NLScreenerInput.test.tsx` (NEW)

**What to build**:
Row 2.5 (conditionally visible — hidden when not active). A 28px input bar with placeholder, explanation line, and auto-populated filter chips.

```ts
interface NLScreenerInputProps {
  onFiltersApplied: (filters: ScreenerFilter[]) => void;
}
```

**Visual** (from design §4.1a):
- Input bar: `bg-input border border-border/40 rounded-[2px]` h=28px; placeholder `text-[10px] text-muted-foreground`
- Submit `[→]` button: 22×22px `bg-primary/10 hover:bg-primary/20 text-primary` flush right
- "Interpreted as:" line (16px): `text-[10px] font-mono text-muted-foreground`; populated from `data.explanation`
- Filter chips below: same styling as `FilterChipStrip` chips; `Apply` button right-aligned
- Error: `text-[10px] text-negative font-mono` "Could not translate — try being more specific"

**Mutation** (from design §8.5):
```ts
const [explanation, setExplanation] = useState("");

const nlTranslateMutation = useMutation({
  mutationFn: (query: string) => gateway.translateNLScreenerQuery(query),
  onSuccess: (data) => {
    setExplanation(data.explanation ?? "");
    const allowedFields = queryClient.getQueryData<string[]>(qk.screener.fields()) ?? [];
    const safeFilters = data.filters.filter(
      (f) => allowedFields.includes(f.field),
    );
    onFiltersApplied(safeFilters);
  },
});
```

NL is **additive**: existing filters in `FilterChipStrip` survive; NL chips are appended.

**Security**: Skip rendering chips for fields not in `qk.screener.fields()` cache (allowlist guard).

**Tests**:
| Test | What it verifies | Type |
|------|-----------------|------|
| `renders placeholder` | input visible with correct placeholder | unit |
| `shows explanation on success` | explanation text appears after mutation success | unit |
| `skips chips for unlisted fields` | allowlist guard filters unknown fields | unit |
| `shows error on 422` | error message visible on mutation error | unit |
| `disables submit while in-flight` | button disabled during pending mutation | unit |

---

#### T-E-02: `RowHoverToolbar.tsx` (NEW)

**Type**: impl
**depends_on**: none
**blocks**: [T-E-03]
**Target files**:
- `apps/worldview-web/components/screener/RowHoverToolbar.tsx` (NEW ~80 lines)

**What to build**:
A floating 3-button cluster that appears on row hover (100ms fade-in) overlaid on the right edge of the hovered row. Uses `position: absolute`, right-pinned. Does NOT consume a column slot.

```ts
interface RowHoverToolbarProps {
  instrumentId: string;
  ticker: string;
  onWatch: (id: string) => void;
  onAlert: (id: string) => void;
  onCompare: (id: string) => void;
}
```

Buttons: `+ Watch` → `POST /v1/watchlists/{id}/items`; `⚐ Alert` → opens existing Create Alert dialog pre-filled; `Compare` → toast "AAPL added to compare set (N)" (session-scoped).

Implemented as an AG Grid `rowMouseOver` event that updates a `hoveredRowId` ref; toolbar mounts absolutely over the row.

---

#### T-E-03: Wire NLScreenerInput + RowHoverToolbar into page

**Type**: impl
**depends_on**: [T-E-01, T-E-02, T-D-05]
**blocks**: none
**Target files**:
- `apps/worldview-web/app/(app)/screener/page.tsx`

**What to build**:
- Import `NLScreenerInput` and render it as Row 2.5 (between `PresetBar` and `FilterChipStrip`). Toggled visible by the `/` hotkey (registered in Wave D) or by a "NL search" affordance in `FilterChipStrip`.
- Wire `RowHoverToolbar` into `ScreenerTable` via `rowMouseOver` event.
- Connect `NLScreenerInput.onFiltersApplied` to the page's `setFilters` callback (NL chips appended to existing `FilterState`).

**Acceptance criteria**:
- [ ] Pressing `/` shows the NL input bar
- [ ] Typing a query and pressing Enter calls `POST /v1/screener/nl-translate`
- [ ] Explanation line populated from `data.explanation`
- [ ] Filter chips auto-populated; Apply merges with existing filters
- [ ] Row hover shows the 3-button toolbar fading in at 100ms
- [ ] `+ Watch` button calls watchlist endpoint

---

### Validation Gate — Wave E
- [ ] TypeScript compiles clean
- [ ] ≥5 Vitest tests for `NLScreenerInput`
- [ ] NL flow works end-to-end in dev server (manual): type → explanation appears → chips auto-populate → Apply
- [ ] Hover toolbar appears on row hover
- [ ] All existing screener tests still pass
- [ ] Architecture test passes (no off-palette colors)

---

## Execution Order

```
A (backend tests + TS types) — 1h
     └─ B (FundamentalsTimeseriesChart) — 2h    [independent of C/D/E]
     └─ C (screener columns) — 1.5h             [independent of B/D/E]
          └─ D (page redesign) — 3h             [needs C for colDefs]
               └─ E (NLInput + hover toolbar) — 2h
```

Waves B and C can run in parallel after A completes.

---

## Regression Guardrails

- All existing `ag-screener-columns.tsx` tests must pass after REVENUE column removal (update assertions)
- `qk.instruments.fundamentalsTimeseries` rename: grep for all call sites before committing (`grep -rn "fundamentalsTimeseries" apps/`)
- `ScreenerFilterBar.tsx` deletion: confirm no import anywhere (`grep -rn "ScreenerFilterBar" apps/`)
- `explanation` field: backend is forwards-compatible (`extra="allow"`) — old frontend (without `explanation`) ignores the field gracefully
- NL allowlist guard: must be tested with a mock that returns a field name NOT in the fields cache
