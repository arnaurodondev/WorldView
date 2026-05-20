---
id: PLAN-0090
title: Instrument Detail Page Ground-Up Redesign
prd: PRD-0088
status: active
created: 2026-05-19
updated: 2026-05-19
---

# PLAN-0090 — Instrument Detail Page Ground-Up Redesign

## Overview

**PRD**: [PRD-0088](../specs/0088-instrument-detail-page-ground-up-redesign.md)
**Scope**: `apps/worldview-web` — frontend only, zero backend changes
**Branch**: `fix/instrument-page-redesign`

**Strategy**: Option B — delete all `components/instrument/` visual components; rebuild from PRD-0088 spec. Keep unchanged: `lib/api/instruments.ts`, `lib/api/knowledge-graph.ts`, `lib/api/news.ts`, `lib/api/intelligence.ts`, `lib/api/dashboard.ts`, `lib/chart-adapter.ts`, `types/api.ts`, `lib/query/keys.ts` (extend only). The new component tree uses different directory names and filenames — no naming conflicts with old files during development.

**Execution order**: A → B → C → D → E (each wave leaves the page functional at its scope)

---

## Pre-Flight Gate Results

| Check | Result |
|-------|--------|
| No BLOCKING open questions | PASS — all 4 OQs in PRD §13 are DEFERRED |
| No unverified external API fields | PASS — all fields verified against `types/api.ts` |
| No active cross-plan conflicts | PASS — PLAN-0071 Phase 6.5 explicitly suspended |
| PRD recency | PASS — written 2026-05-19 (same day) |
| Architecture compliance | PASS — frontend only, R14 (S9 only) enforced |

---

## Name Verification Results

All API methods and query keys verified via grep:

| Name | File | Status |
|------|------|--------|
| `createGateway(t).getInstrumentPageBundle()` | `lib/api/instruments.ts:54` | EXISTS |
| `createGateway(t).getFundamentals()` | `lib/api/instruments.ts:260` | EXISTS |
| `createGateway(t).getFundamentalsSnapshot()` | `lib/api/instruments.ts:469` | EXISTS |
| `createGateway(t).getTechnicals()` | `lib/api/instruments.ts:381` | EXISTS |
| `createGateway(t).getShareStatistics()` | `lib/api/instruments.ts:395` | EXISTS |
| `createGateway(t).getIncomeStatement()` | `lib/api/instruments.ts:491` | EXISTS |
| `createGateway(t).getEarningsHistory()` | `lib/api/instruments.ts:429` | EXISTS |
| `createGateway(t).getInstrumentBrief()` | `lib/api/dashboard.ts:256` | EXISTS |
| `createGateway(t).getEntityGraph()` | `lib/api/knowledge-graph.ts:38` | EXISTS |
| `createGateway(t).getEntityNews()` | `lib/api/news.ts:52` | EXISTS |
| `useEntityIntelligence(entityId)` | `lib/api/intelligence.ts:89` | EXISTS |
| `qk.instruments.pageBundle(entityId)` | `lib/query/keys.ts:153` | EXISTS |
| `qk.instruments.ohlcv(id, tf)` | `lib/query/keys.ts:130` | EXISTS |
| `qk.instruments.fundamentals(id)` | `lib/query/keys.ts:132` | EXISTS |
| `qk.instruments.fundamentalsSnapshot(id)` | `lib/query/keys.ts:134` | EXISTS |
| `qk.instruments.technicals(id)` | `lib/query/keys.ts:138` | EXISTS |
| `qk.instruments.entityGraph(id, depth)` | `lib/query/keys.ts:140` | EXISTS |
| `qk.instruments.brief(id)` | `lib/query/keys.ts:128` | EXISTS |
| `qk.news.entity(entityId, params)` | `lib/query/keys.ts:177` | EXISTS |
| `qk.instruments.ownership(id)` | `lib/query/keys.ts:146` | EXISTS |
| `qk.instruments.shareStatistics(id)` | — | NEW — add in Wave A |
| `qk.instruments.incomeStatement(id)` | — | NEW — add in Wave A |
| `qk.instruments.earningsHistory(id)` | — | NEW — add in Wave A |
| `useChartSeries` | `components/instrument/chart/useChartSeries.ts` | EXISTS |
| `TimeframeToolbar` | `components/instrument/chart/TimeframeToolbar.tsx` | EXISTS |
| `ChartToolbar` | `components/instrument/ChartToolbar.tsx` | EXISTS |
| `SessionStatsStrip` | `components/instrument/SessionStatsStrip.tsx` | EXISTS |
| `EntityGraph` | `components/instrument/EntityGraph.tsx` | EXISTS |
| `ContradictionCard` | `components/instrument/intelligence/ContradictionCard.tsx` | EXISTS |

**NEW files** (created in this plan — not yet in repo):
- `lib/technicals.ts`
- `components/instrument/InstrumentPageClient.tsx`
- `components/instrument/header/InstrumentHeader.tsx`
- `components/instrument/header/WeekRangeMini.tsx`
- `components/instrument/brief/AiBriefBanner.tsx`
- `components/instrument/tabs/InstrumentTabs.tsx`
- `components/instrument/shared/MetricLabel.tsx`
- `components/instrument/shared/MetricValue.tsx`
- `components/instrument/shared/SectionDivider.tsx`
- `components/instrument/shared/DataTimestamp.tsx`
- `components/instrument/hooks/useInstrumentBundle.ts`
- `components/instrument/hooks/useMetricsTableData.ts`
- `components/instrument/hooks/useFinancialsTabData.ts`
- `components/instrument/hooks/useEntityNewsInfinite.ts`
- `components/instrument/hooks/useChartTechnicals.ts`
- `components/instrument/quote/QuoteTab.tsx`
- `components/instrument/quote/metrics/MetricsTable.tsx`
- `components/instrument/quote/metrics/MetricRow.tsx`
- `components/instrument/quote/metrics/MetricGroupDivider.tsx`
- `components/instrument/quote/metrics/WeekRangeBar.tsx`
- `components/instrument/quote/metrics/AnalystMiniBar.tsx`
- `components/instrument/financials/FinancialsTab.tsx`
- `components/instrument/financials/FlatMetricsGrid.tsx`
- `components/instrument/financials/MetricCell.tsx`
- `components/instrument/financials/IncomeStatementTable.tsx`
- `components/instrument/financials/EarningsBarChart.tsx`
- `components/instrument/financials/AnalystSidebar.tsx`
- `components/instrument/intelligence/IntelligenceTab.tsx` (rewrite)
- `components/instrument/intelligence/news/NewsColumn.tsx`
- `components/instrument/intelligence/news/NewsFilters.tsx`
- `components/instrument/intelligence/news/CompactArticleRow.tsx`
- `components/instrument/intelligence/graph/GraphColumn.tsx`
- `components/instrument/intelligence/graph/GraphToolbar.tsx`
- `components/instrument/intelligence/context/ContextPanel.tsx`
- `components/instrument/intelligence/context/NodeDetailCard.tsx`
- `components/instrument/intelligence/context/RelationsList.tsx`

---

## Wave Summary

| Wave | Title | Tasks | Effort | Depends On |
|------|-------|-------|--------|------------|
| A | Shared infrastructure + page skeleton | 6 tasks | 3–4h | none |
| B | Quote tab: chart + metrics table | 5 tasks | 3–4h | A |
| C | Financials tab: flat grid + sidebar | 4 tasks | 3–4h | A |
| D | Intelligence tab: graph + news + context | 5 tasks | 4–5h | A |
| E | Cleanup + unit tests + E2E | 4 tasks | 3–4h | B, C, D |

**Total**: ~16–21h estimated

---

## Wave A — Shared Infrastructure + Page Skeleton

**Goal**: Establish the new page shell (InstrumentPageClient, header, AI brief banner, 3-tab bar), shared primitive components, all new hooks, and query key additions. At the end of Wave A the instrument page renders: sticky header → brief banner → tab bar → empty tab placeholder for each of the 3 tabs. No tab content yet.

**Depends on**: none
**Architecture layer**: Frontend infrastructure / composition

### Pre-read
- `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx`
- `apps/worldview-web/lib/query/keys.ts` (lines 110–200)
- `apps/worldview-web/lib/api/instruments.ts` (lines 43–70, bundle method)
- `apps/worldview-web/lib/api/dashboard.ts` (lines 250–265, getInstrumentBrief)
- `apps/worldview-web/types/api.ts` (lines 197–285, Fundamentals + FundamentalsSnapshot)

---

#### T-A-01: Add missing query keys and create `lib/technicals.ts`

**Type**: impl
**depends_on**: none
**blocks**: [T-A-02, T-A-03, T-B-01, T-C-01]
**Target files**:
- `apps/worldview-web/lib/query/keys.ts` (extend instruments namespace)
- `apps/worldview-web/lib/technicals.ts` (NEW)

**What to build**:

**`lib/query/keys.ts`** — Add 3 missing keys inside the `instruments:` object, after the existing `ownership` entry:
```typescript
shareStatistics: (instrumentId: string) =>
  ["instruments", "detail", instrumentId, "share-statistics"] as const,
incomeStatement: (instrumentId: string) =>
  ["instruments", "detail", instrumentId, "income-statement"] as const,
earningsHistory: (instrumentId: string) =>
  ["instruments", "detail", instrumentId, "earnings-history"] as const,
```

**`lib/technicals.ts`** (NEW — 60 lines max):
```typescript
// lib/technicals.ts — Client-side technical indicator computation from OHLCV bars.
// WHY: RSI and ATR are not returned by any S9 endpoint; computing them client-side
// from the 1D OHLCV bars already fetched for the chart avoids an extra API call.

import type { OHLCVBar } from "@/types/api";

// computeRSI — 14-period Relative Strength Index.
// Returns null if fewer than period+1 bars are available.
export function computeRSI(bars: OHLCVBar[], period = 14): number | null

// computeATR — 14-period Average True Range.
// Returns null if fewer than period+1 bars are available.
export function computeATR(bars: OHLCVBar[], period = 14): number | null
```

**RSI algorithm**:
1. Compute daily changes: `delta[i] = bars[i].close - bars[i-1].close`
2. Separate gains (delta > 0) and losses (abs(delta) where delta < 0)
3. First avg gain = mean of gains[0..period-1]; first avg loss = mean of losses[0..period-1]
4. Subsequent: `avgGain = (prevAvgGain * (period-1) + currentGain) / period` (Wilder smoothing)
5. `RS = avgGain / avgLoss`; `RSI = 100 - (100 / (1 + RS))`
6. Return RSI of the last bar; return null if avgLoss === 0 (handle div-by-zero → return 100)

**ATR algorithm**:
1. True Range[i] = max(H-L, |H - prevClose|, |L - prevClose|)
2. ATR = Wilder smoothed average of TR over `period` bars
3. Return ATR of the last bar

**Tests to write** (inline unit tests in `lib/__tests__/technicals.test.ts`):
| Test | Verifies |
|------|----------|
| `test_computeRSI_returns_null_with_insufficient_bars` | bars.length < period+1 → null |
| `test_computeRSI_known_values_14_period` | 20 synthetic bars → RSI matches pre-computed value |
| `test_computeRSI_all_gains_returns_100` | all bars rising → RSI = 100 |
| `test_computeATR_returns_null_with_insufficient_bars` | bars.length < period+1 → null |
| `test_computeATR_known_values` | flat OHLC bars → ATR = 0 |

**Acceptance criteria**:
- [ ] `qk.instruments.shareStatistics`, `qk.instruments.incomeStatement`, `qk.instruments.earningsHistory` exist in keys.ts
- [ ] `computeRSI` and `computeATR` exported from `lib/technicals.ts`
- [ ] 5 unit tests pass (Vitest)
- [ ] `tsc --noEmit` passes

---

#### T-A-02: Create shared primitive components

**Type**: impl
**depends_on**: none
**blocks**: [T-A-04, T-B-01, T-C-01, T-D-01]
**Target files**: `apps/worldview-web/components/instrument/shared/` (4 NEW files)

**What to build**:

**`MetricLabel.tsx`** (max 30 lines):
- Props: `children: React.ReactNode`
- Renders: `<span className="text-[10px] uppercase tracking-wide text-muted-foreground truncate">` wrapping children
- Use case: all metric row/cell labels throughout the instrument page

**`MetricValue.tsx`** (max 50 lines):
- Props: `children: React.ReactNode; color?: "positive" | "negative" | "amber" | "muted" | "default"`
- Color map: `positive → text-positive`, `negative → text-negative`, `amber → text-amber-400`, `muted → text-muted-foreground`, `default → text-foreground`
- Renders: `<span className={\`text-[11px] font-mono tabular-nums \${colorClass}\`}>` wrapping children
- Null/undefined children → renders `<span className="text-[11px] font-mono tabular-nums text-muted-foreground/50">—</span>`

**`SectionDivider.tsx`** (max 30 lines):
- Props: `label?: string`
- Without label: `<div className="h-[1px] bg-border/30 col-span-3" />`
- With label: divider + `<div className="col-span-3 pt-3 pb-1 text-[10px] uppercase tracking-widest text-muted-foreground/50">{label}</div>`

**`DataTimestamp.tsx`** (max 30 lines):
- Props: `updatedAt: string | null; className?: string`
- Renders: `<p className="text-[10px] text-muted-foreground px-3 py-2">` + "Data as of {formatted date}" or "Data not yet available" if null
- Date format: "May 19, 2026" using `Intl.DateTimeFormat`

**Acceptance criteria**:
- [ ] All 4 files created with correct className patterns
- [ ] `MetricValue` renders "—" for null/undefined children
- [ ] `tsc --noEmit` passes

---

#### T-A-03: Create instrument page hooks

**Type**: impl
**depends_on**: [T-A-01]
**blocks**: [T-A-04, T-B-01, T-C-01, T-D-01]
**Target files**: `apps/worldview-web/components/instrument/hooks/` (5 NEW files)

**What to build**:

**`useInstrumentBundle.ts`** (max 40 lines):
```typescript
// WHY: Centralises the page-bundle fetch so InstrumentPageClient and
// any future page-level consumers share the same TanStack Query cache entry.
export function useInstrumentBundle(entityId: string) {
  const token = useAccessToken();
  return useQuery({
    queryKey: qk.instruments.pageBundle(entityId),
    queryFn: () => createGateway(token).getInstrumentPageBundle(entityId),
    staleTime: 5 * 60 * 1000,
    enabled: !!entityId,
  });
}
```

**`useMetricsTableData.ts`** (max 80 lines):
- Takes `instrumentId: string`
- Runs 3 queries in parallel: `getFundamentalsSnapshot`, `getTechnicals`, `getShareStatistics`
- Returns `{ snapshot, technicals, shareStats, isLoading, isError }` with unified loading/error state
- Query keys: `qk.instruments.fundamentalsSnapshot`, `qk.instruments.technicals`, `qk.instruments.shareStatistics` (new key from T-A-01)
- staleTime: 10min for snapshot, 5min for technicals, 60min for shareStats
- Each query: `enabled: !!instrumentId`

**`useFinancialsTabData.ts`** (max 100 lines):
- Takes `instrumentId: string`
- Runs 4 queries: `getFundamentals`, `getFundamentalsSnapshot`, `getIncomeStatement`, `getEarningsHistory`
- Also reads `getTechnicals` and `getShareStatistics` (re-uses MetricsTable keys — auto-deduped)
- Returns `{ fundamentals, snapshot, incomeStatement, earningsHistory, technicals, shareStats, isLoading }`
- staleTime: 5min (fundamentals), 10min (snapshot), 24h (incomeStatement, earningsHistory)

**`useEntityNewsInfinite.ts`** (max 60 lines):
```typescript
// WHY useInfiniteQuery: NewsColumn renders as an infinite-scroll list.
// Each page loads 20 articles at offset = pageParam * 20.
export function useEntityNewsInfinite(
  entityId: string,
  filters: { sentiment?: string; timeRange?: string } = {}
) {
  const token = useAccessToken();
  return useInfiniteQuery({
    queryKey: qk.news.entity(entityId, filters),
    queryFn: ({ pageParam = 0 }) =>
      createGateway(token).getEntityNews(entityId, {
        limit: 20,
        offset: pageParam * 20,
        sentiment: filters.sentiment,
      }),
    getNextPageParam: (lastPage, allPages) =>
      lastPage.articles.length === 20 ? allPages.length : undefined,
    staleTime: 5 * 60 * 1000,
    enabled: !!entityId,
  });
}
```

**`useChartTechnicals.ts`** (max 40 lines):
- Takes `bars: OHLCVBar[] | undefined`
- Computes `rsi = computeRSI(bars ?? [])` and `atr = computeATR(bars ?? [])` from `lib/technicals.ts`
- Returns `{ rsi: number | null; atr: number | null }`
- Memoized with `useMemo` on `bars` reference to avoid recomputing on every render
- No API calls — pure computation from OHLCV bars

**Acceptance criteria**:
- [ ] All 5 hooks created and exported
- [ ] `useMetricsTableData` uses correct staleTime values
- [ ] `useEntityNewsInfinite` uses `useInfiniteQuery` from `@tanstack/react-query`
- [ ] `useChartTechnicals` uses `useMemo` to avoid redundant computation
- [ ] `tsc --noEmit` passes

---

#### T-A-04: Build InstrumentHeader, WeekRangeMini, AiBriefBanner, InstrumentTabs

**Type**: impl
**depends_on**: [T-A-02, T-A-03]
**blocks**: [T-A-05]
**Target files**:
- `apps/worldview-web/components/instrument/header/InstrumentHeader.tsx` (NEW)
- `apps/worldview-web/components/instrument/header/WeekRangeMini.tsx` (NEW)
- `apps/worldview-web/components/instrument/brief/AiBriefBanner.tsx` (NEW)
- `apps/worldview-web/components/instrument/tabs/InstrumentTabs.tsx` (NEW)

**What to build** (PRD §6.4, §6.5, §6.6):

**`WeekRangeMini.tsx`** (max 50 lines):
- Props: `high: number | null; low: number | null; current: number | null`
- Renders: `<div className="relative w-[60px] h-[6px] bg-muted rounded-full">` with a fill `<div>` at computed percent
- `percent = high && low && current && high !== low ? ((current - low) / (high - low)) * 100 : 0`
- Fill: `<div style={{ width: \`\${Math.max(0, Math.min(100, percent))}%\` }} className="h-full bg-primary rounded-full" />`
- Clamps to [0, 100] — never overflows

**`InstrumentHeader.tsx`** (max 130 lines):
- Props: `instrument: Instrument; quote: Quote | null; fundamentals: Fundamentals | null`
- Structure: `<header className="sticky top-0 z-30 h-9 border-b border-border bg-background flex items-center px-3 gap-4">`
  - Left: back button (ChevronLeft, `size-4`), ticker `text-[13px] font-semibold font-mono tracking-wide`, exchange badge, company name `text-[11px] text-muted-foreground truncate max-w-[200px]`
  - Right (`ml-auto flex items-center gap-3`): price + change (colored), separator, "CAP" label + market cap, "VOL" label + daily_return as volume proxy, "P/E" label + pe_ratio, WeekRangeMini, LiveQuoteBadge (from existing `LiveQuoteBadge.tsx` — keep, do NOT delete in Wave A)
- Format helpers: use existing `formatCurrency`, `formatPercent` from `lib/format.ts` or `lib/utils.ts`
- All numbers: `font-mono tabular-nums`

**`AiBriefBanner.tsx`** (max 120 lines):
- Props: `entityId: string`
- Fetches brief via `useQuery({ queryKey: qk.instruments.brief(entityId), queryFn: () => createGateway(token).getInstrumentBrief(entityId), staleTime: 10 * 60 * 1000 })`
- Returns `null` when: loading && no data, or data is null/undefined (no loading skeleton visible)
- Collapsed state: `<div className="h-6 flex items-center gap-2 px-3 border-b border-border/50 bg-card cursor-pointer">`
  - ChevronRight icon (size-3, rotates 90° when expanded via `transition-transform`)
  - `BRIEF` label (10px, muted)
  - Brief text first 140 chars: `text-[11px] text-foreground/70 truncate flex-1`
  - Click → expand; sessionStorage key `wv:brief-collapsed:{entityId}` (default: collapsed)
- Expanded state: `<div className="px-3 py-2 border-b border-border/50 bg-card max-h-[120px] overflow-y-auto">`
  - Full brief text: `text-[11px] leading-[1.5] text-foreground/80 whitespace-pre-wrap`
  - Timestamp: `text-[10px] text-muted-foreground mt-1`

**`InstrumentTabs.tsx`** (max 80 lines):
- Props: `activeTab: "quote" | "financials" | "intelligence"; onTabChange: (tab) => void`
- Structure: `<div className="h-8 border-b border-border flex items-end px-3 gap-6">`
- Each tab button: `text-[11px] font-medium uppercase tracking-wide pb-1.5` + `border-b-2 border-primary text-foreground` (active) or `border-b-2 border-transparent text-muted-foreground hover:text-foreground/70` (inactive)
- Tab labels: QUOTE | FINANCIALS | INTELLIGENCE
- Keyboard mnemonics via `useChordHotkeys` (existing hook): Q → quote, F → financials, I → intelligence
  - IMPORTANT: scope these to the instrument page only. Use the same `useHotkeyScope` / hotkeyRegistry pattern as existing page.tsx.

**Acceptance criteria**:
- [ ] Header is 36px (h-9), sticky, all fields display with correct typography
- [ ] WeekRangeMini fill stays within [0, 100]% even if price outside 52W range
- [ ] Banner hides entirely when brief is null (no empty banner space)
- [ ] Banner expand/collapse toggle works; state persisted in sessionStorage
- [ ] Tab bar renders 3 tabs; Q/F/I mnemonics fire onTabChange
- [ ] All numbers use `font-mono tabular-nums`

---

#### T-A-05: Create InstrumentPageClient and simplify page.tsx

**Type**: impl
**depends_on**: [T-A-03, T-A-04]
**blocks**: [T-B-01, T-C-01, T-D-01]
**Target files**:
- `apps/worldview-web/components/instrument/InstrumentPageClient.tsx` (NEW)
- `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx` (MODIFY)

**What to build**:

**`InstrumentPageClient.tsx`** (max 200 lines):
```typescript
"use client";
// InstrumentPageClient — root client component for /instruments/[entityId].
// Fetches the page bundle, seeds TanStack Query caches for child components,
// and renders the 3-layer shell: InstrumentHeader + AiBriefBanner + InstrumentTabs + tab content.
```
- `const { data: bundle, isLoading, isError } = useInstrumentBundle(entityId)`
- On bundle load: call `queryClient.setQueryData(qk.instruments.overview(instrumentId), bundle.overview)` etc. (mirror existing cache-seeding pattern from old page.tsx)
  - Seed: overview → `qk.instruments.overview`, technicals → `qk.instruments.technicals`, insider → `qk.instruments.ownership`
  - Do NOT seed fundamentals (known shape mismatch — see PRD §6.3)
- `const [activeTab, setActiveTab] = useState<"quote" | "financials" | "intelligence">("quote")`
- Loading state: full-page skeleton (3 sections: header skeleton 36px, banner skeleton 24px, content skeleton fills viewport)
- Error state: centered error message with retry button
- If `entityId === "undefined"` → `router.replace("/instruments")` (preserve existing guard)
- Renders: `<InstrumentHeader>` + `<AiBriefBanner>` + `<InstrumentTabs>` + tab content area
- Tab content: `{activeTab === "quote" && <QuoteTabPlaceholder />}` etc. (placeholder div with "Coming in Wave B/C/D" for now — real content added in subsequent waves)
- `localStorage` panel layout: REMOVE (no resizable panels in new design)
- Keyboard scope: `<HotkeyScope scope="page" page="/instruments/" bindings={bindings} />` wrapping whole component

**`page.tsx`** (SIMPLIFY — target ~20 lines):
```typescript
// Server component — validates entityId, renders client boundary.
// SSR renders the static shell (no data fetching here).
import { InstrumentPageClient } from "@/components/instrument/InstrumentPageClient";

export default async function InstrumentDetailPage({ params }: { params: { entityId: string } }) {
  return <InstrumentPageClient entityId={params.entityId} />;
}
// layout.tsx generates the <title> tag — no metadata generation needed here.
```

**Acceptance criteria**:
- [ ] Page loads without errors on `/instruments/[valid-entityId]`
- [ ] Header shows ticker/price/key stats from bundle
- [ ] Banner shows collapsed brief text (or is hidden if brief null)
- [ ] 3 tabs render; switching works; Q/F/I hotkeys work
- [ ] Tab content areas show placeholder text (not blank/white)
- [ ] Redirect works for `entityId === "undefined"`
- [ ] `tsc --noEmit` passes

---

#### T-A-06: Unit tests for Wave A components

**Type**: test
**depends_on**: [T-A-01, T-A-02, T-A-04]
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/shared/__tests__/`, `apps/worldview-web/lib/__tests__/`

**Tests to write**:

| Test | File | What It Verifies |
|------|------|-----------------|
| `test_MetricValue_renders_dash_for_null` | `shared/__tests__/MetricValue.test.tsx` | null children → "—" text |
| `test_MetricValue_applies_positive_color` | same | color="positive" → text-positive class |
| `test_MetricValue_applies_negative_color` | same | color="negative" → text-negative class |
| `test_WeekRangeMini_clamps_to_zero` | `header/__tests__/WeekRangeMini.test.tsx` | price < low → 0% fill |
| `test_WeekRangeMini_clamps_to_100` | same | price > high → 100% fill |
| `test_WeekRangeMini_null_renders_zero` | same | null inputs → 0% fill, no crash |
| `test_computeRSI_insufficient_bars_returns_null` | `lib/__tests__/technicals.test.ts` | < 15 bars → null |
| `test_computeATR_insufficient_bars_returns_null` | same | < 15 bars → null |

**Acceptance criteria**:
- [ ] All 8 tests pass (`pnpm test`)
- [ ] No `any` type usage in test files

### Validation Gate — Wave A
- [ ] `pnpm tsc --noEmit` — zero errors
- [ ] `pnpm test` — all existing tests pass + 13 new tests pass
- [ ] Page renders without runtime errors on `/instruments/[entityId]`
- [ ] Header visible; brief banner visible/hidden correctly; tab switching works

### Architecture Compliance — Wave A
- [ ] R14: All API calls in hooks use `createGateway(token)` → S9 only
- [ ] ADR-F-15: `font-mono tabular-nums` on every numeric value in Header and Banner
- [ ] `useInfiniteQuery` from `@tanstack/react-query` (not a custom implementation)
- [ ] No `any` type assertions in new files

### Break Impact — Wave A
| Broken file | Why | Fix |
|-------------|-----|-----|
| Old `page.tsx` logic | Replaced by `InstrumentPageClient.tsx` | Addressed in T-A-05 |
| Old hotkey mnemonics (D/F/N/I → DES/FA/News/Intel) | Replaced by Q/F/I in InstrumentTabs | Remove old hotkeyScope binding from InstrumentPageClient |

### Regression Guardrails — Wave A
- **BP-379** (FundamentalsTab cache shape mismatch): Do NOT attempt to seed `qk.instruments.fundamentals` from bundle in cache-priming — bundle returns `FundamentalsSectionResponse`, but `getFundamentals()` returns `Fundamentals`. This mismatch is documented and intentional.
- **BP-023/BP-127** (ruff version pinning): This is a TypeScript-only wave; no Python files touched.

---

## Wave B — Quote Tab: Chart Refactor + MetricsTable

**Goal**: Build the complete Quote tab. After Wave B, switching to QUOTE shows the OHLCV chart on the left and the 26-row dense MetricsTable on the right. The scroll-to-1985 bug is fixed.

**Depends on**: Wave A
**Architecture layer**: Frontend — Tab 1

### Pre-read
- `apps/worldview-web/components/instrument/chart/useChartSeries.ts`
- `apps/worldview-web/components/instrument/OHLCVChart.tsx`
- `apps/worldview-web/components/instrument/ChartToolbar.tsx`
- `apps/worldview-web/components/instrument/SessionStatsStrip.tsx`
- `apps/worldview-web/types/api.ts` (Fundamentals, FundamentalsSnapshot, TechnicalsData, ShareStatisticsData, lines 197–354)
- PRD-0088 §6.7 (MetricsTable full field specification)

---

#### T-B-01: Refactor OHLCVChart and fix scroll-to-1985 bug

**Type**: impl
**depends_on**: [T-A-05]
**blocks**: [T-B-03]
**Target files**:
- `apps/worldview-web/components/instrument/chart/OHLCVChart.tsx` (REFACTOR, target ≤180 lines)
- `apps/worldview-web/components/instrument/SessionStatsStrip.tsx` (MODIFY for density)

**What to build**:

**OHLCVChart.tsx refactor**:
- Keep: lightweight-charts canvas div, resize observer, `useChartSeries` hook integration
- Remove: `DrawingPalette`, `DrawingCanvas`, `CrosshairHUD`, `ComparePopover`, `VolumeProfileOverlay` — do NOT render these in the new OHLCVChart (deferred per PRD §5)
- Remove: compare overlay state (`showCompareInput`, `compareInput`, `compareInstrumentId`)
- Keep: `timeframe` state, `showMA50`, `showMA200`, `showVolume`, `indicators` state (for RSI/MACD overlays — passed to `useChartSeries`)
- Renders only: `<TimeframeToolbar>` + `<ChartToolbar>` + `<div ref={chartContainerRef} className="flex-1 min-h-0">`
- Props: `instrumentId: string; initialBars?: OHLCVBar[]`

**Scroll-to-1985 bug fix** (in `useChartSeries.ts`):
- **Root cause**: `hasScrolledToRealTime.current = true` is set in the `initChart()` path before bars are loaded, preventing `scrollToRealTime()` from firing when bars actually arrive.
- **Fix**: Find the `initChart()` function in `useChartSeries.ts`. Locate where `hasScrolledToRealTime.current = true` is set prematurely. Remove that premature assignment. Only set `hasScrolledToRealTime.current = true` AFTER `chart.scrollToRealTime()` is actually called with real data.
- **Verify fix**: After applying, chart must render with the most recent bars visible on the right edge (not scrolled to 1985).

**SessionStatsStrip.tsx** — Enforce 22px density:
- Current: unknown padding. Target: `h-[22px] flex items-center gap-4 px-3 border-t border-border/50 bg-background`
- Labels `text-[10px] uppercase text-muted-foreground`, values `text-[11px] font-mono tabular-nums`
- Show: O H L C Vol. High in `text-positive`, Low in `text-negative`. All others default.

**Acceptance criteria**:
- [ ] OHLCVChart ≤180 lines
- [ ] Chart renders with most recent bars visible on right edge (no scroll to 1985)
- [ ] No DrawingPalette/DrawingCanvas/CrosshairHUD rendered
- [ ] SessionStatsStrip is exactly 22px height
- [ ] `tsc --noEmit` passes

---

#### T-B-02: Build MetricRow, MetricGroupDivider, WeekRangeBar, AnalystMiniBar

**Type**: impl
**depends_on**: [T-A-02]
**blocks**: [T-B-03]
**Target files**: `apps/worldview-web/components/instrument/quote/metrics/` (4 NEW files)

**What to build**:

**`MetricRow.tsx`** (max 60 lines):
- Props: `label: string; value?: React.ReactNode; color?: MetricValueColor; className?: string`
- Renders: `<div className={\`flex items-center justify-between h-[22px] px-3 \${className}\`}>`
  - Left: `<MetricLabel>{label}</MetricLabel>`
  - Right: `<MetricValue color={color}>{value ?? null}</MetricValue>`
- Import MetricLabel, MetricValue from `@/components/instrument/shared`
- Export type `MetricValueColor = "positive" | "negative" | "amber" | "muted" | "default"`

**`MetricGroupDivider.tsx`** (max 20 lines):
- No props
- Renders: `<div className="h-[1px] bg-border/30 mx-3 my-0.5" />`

**`WeekRangeBar.tsx`** (max 60 lines):
- Props: `high: number | null; low: number | null; current: number | null`
- Renders inside a `h-[22px] flex items-center px-3` row:
  - Low label: `text-[9px] font-mono text-muted-foreground`
  - Bar: `<div className="flex-1 mx-2 relative h-[4px] bg-muted rounded-full">` with fill `<div style={{ width }} className="h-full bg-primary rounded-full absolute left-0">`
  - High label: same style
- Percent clamp [0, 100]; null → 0%

**`AnalystMiniBar.tsx`** (max 80 lines):
- Props: `strongBuy: number | null; buy: number | null; hold: number | null; sell: number | null; strongSell: number | null`
- Computes total = sum of non-null counts; each segment width = count/total * 100%
- Renders: `<div className="flex-1 flex h-[4px] rounded-full overflow-hidden gap-px">`
  - Buy segment (buy+strongBuy): `bg-positive`
  - Hold segment: `bg-amber-400`
  - Sell segment (sell+strongSell): `bg-negative`
- Below bar: `"28B · 10H · 2S"` string in `text-[10px] font-mono text-muted-foreground`
- Null counts treated as 0. If total === 0: render empty bar, no crash.

**Acceptance criteria**:
- [ ] MetricRow renders correctly for null value (shows "—" via MetricValue)
- [ ] WeekRangeBar fill never exceeds container width
- [ ] AnalystMiniBar segments are proportional; no crash on all-null input
- [ ] `tsc --noEmit` passes

---

#### T-B-03: Build MetricsTable

**Type**: impl
**depends_on**: [T-A-03, T-B-02]
**blocks**: [T-B-04]
**Target files**: `apps/worldview-web/components/instrument/quote/metrics/MetricsTable.tsx` (NEW)

**What to build** (PRD §6.7.2 — full field specification):

`MetricsTable.tsx` (max 200 lines):
- Props: `instrumentId: string; fundamentals: Fundamentals | null; quote: Quote | null`
- Fetches: `const { snapshot, technicals, shareStats } = useMetricsTableData(instrumentId)`
- Renders: `<div className="w-full h-full flex flex-col border-l border-border overflow-y-auto">`
  - Header: `<div className="flex items-center h-7 px-3 border-b border-border/50 bg-card/50">STATISTICS</div>` (10px text)
  - 26 MetricRow entries + 5 MetricGroupDivider + 2 special rows (WeekRangeBar, AnalystMiniBar)

**Complete row list** (from PRD §6.7.2 table):
```
[divider group: VALUATION]
MetricRow "MARKET CAP"  → formatMarketCap(fundamentals?.market_cap)
MetricRow "P/E"         → formatRatio(fundamentals?.pe_ratio)         color: pe_ratio > 50 → red, > 30 → amber
MetricRow "FWD P/E"     → formatRatio(fundamentals?.forward_pe)       color: forward_pe > 40 → red, > 25 → amber
MetricRow "EPS TTM"     → formatCurrency(snapshot?.eps_ttm)           color: positive/negative by sign
MetricRow "P/S"         → formatRatio(fundamentals?.price_to_sales)
MetricRow "P/B"         → formatRatio(fundamentals?.price_to_book)
MetricRow "EV/EBITDA"   → formatRatio(fundamentals?.ev_to_ebitda)
[MetricGroupDivider]

[divider group: MARGINS]
MetricRow "GROSS MARGIN" → formatPercent(fundamentals?.gross_margin)  color: > 40% → positive, 20-40% → default
MetricRow "OPER MARGIN"  → formatPercent(fundamentals?.operating_margin) color: > 20% → positive, 10-20% → default
MetricRow "NET MARGIN"   → formatPercent(fundamentals?.net_margin)    color: > 15% → positive, < 0 → negative
MetricRow "ROE"          → formatPercent(fundamentals?.roe)           color: > 15% → positive, < 0 → negative
MetricRow "ROA"          → formatPercent(fundamentals?.roa)           color: > 10% → positive, < 0 → negative
[MetricGroupDivider]

[divider group: LEVERAGE]
MetricRow "DEBT/EQUITY"   → formatRatio(fundamentals?.debt_to_equity) + "x"  color: > 3 → red, > 1.5 → amber
MetricRow "CURRENT RATIO" → formatRatio(fundamentals?.current_ratio) + "x"   color: < 1 → red, < 1.5 → amber
[MetricGroupDivider]

[divider group: YIELD]
MetricRow "DIV YIELD" → formatPercent(fundamentals?.dividend_yield)  color: > 3% → positive, 1-3% → default
MetricRow "BETA"      → snapshot?.beta?.toFixed(2) ?? null           color: > 2.5 → red, > 1.5 → amber
[MetricGroupDivider]

[divider group: 52W RANGE]
MetricRow "52W HIGH" → formatCurrency(fundamentals?.week_52_high)
MetricRow "52W LOW"  → formatCurrency(fundamentals?.week_52_low)
WeekRangeBar (full-width in 22px row) using high/low/current

[MetricGroupDivider]

[divider group: OWNERSHIP]
MetricRow "AVG VOL 30D"  → formatVolume(snapshot?.avg_volume_30d)
MetricRow "SHORT %"      → formatPercent(technicals?.short_percent)  color: > 10% → red, > 5% → amber
MetricRow "INST OWN"     → formatPercent(shareStats?.percent_institutions)
MetricRow "INSIDER OWN"  → formatPercent(shareStats?.percent_insiders)
[MetricGroupDivider]

[divider group: TREND]
MetricRow "MA 50"  → formatCurrency(technicals?.["50_day_ma"])  + arrow indicator (↑/↓ based on price vs MA)
MetricRow "MA 200" → formatCurrency(technicals?.["200_day_ma"]) + arrow indicator
[MetricGroupDivider]

[divider group: CONSENSUS]
AnalystMiniBar (full-width in 22px + 16px rows)
MetricRow "TARGET" → formatCurrency(fundamentals?.analyst_target_price) + % upside vs current price
```

**Format helpers** — use existing helpers from `lib/format.ts` or `lib/utils.ts`:
- `formatCurrency(n)`: "$1.23" or "—" for null
- `formatPercent(n)`: "12.3%" for decimal (0.123) or "—"
- `formatRatio(n)`: "36.0" or "—"
- `formatMarketCap(n)`: "$3.07T" / "$430B" / "$12M" based on magnitude
- `formatVolume(n)`: "62.3M" / "1.2B" based on magnitude

**Acceptance criteria**:
- [ ] MetricsTable renders all 26 data rows + 5 dividers
- [ ] Color coding matches PRD spec for P/E, ROE, Beta, Debt/Equity, Short%
- [ ] WeekRangeBar row and AnalystMiniBar row display inline (not collapsing to 0 height)
- [ ] All values use `font-mono tabular-nums`
- [ ] Loading state: all rows show "—" until data arrives (no skeleton needed)
- [ ] `tsc --noEmit` passes

---

#### T-B-04: Build QuoteTab orchestrator

**Type**: impl
**depends_on**: [T-A-05, T-B-01, T-B-03]
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/quote/QuoteTab.tsx` (NEW)

**What to build** (PRD §6.7):

`QuoteTab.tsx` (max 200 lines):
- Props: `instrumentId: string; entityId: string; fundamentals: Fundamentals | null; quote: Quote | null; initialBars?: OHLCVBar[]`
- Layout: `<div className="flex h-full overflow-hidden">`
  - Left: `<div className="flex flex-col min-w-0 flex-1">`
    - `<OHLCVChart instrumentId={instrumentId} initialBars={initialBars} />`
    - `<SessionStatsStrip instrumentId={instrumentId} />`
  - Right: `<MetricsTable instrumentId={instrumentId} fundamentals={fundamentals} quote={quote} />`
    - Fixed width: `className="w-[40%] flex-shrink-0"`
- Update `InstrumentPageClient.tsx` to render `<QuoteTab ...>` when `activeTab === "quote"` (replace placeholder)

**Session stats integration**:
- `SessionStatsStrip` needs to know the last OHLCV bar. Pass `initialBars` as prop or let SessionStatsStrip fetch its own data via `qk.instruments.ohlcv` (already in cache from bundle seed).
- Recommended: SessionStatsStrip reads from TanStack Query cache (auto-populated by OHLCVChart's own fetch).

**Acceptance criteria**:
- [ ] Quote tab renders: chart left 60%, MetricsTable right 40%
- [ ] Chart and MetricsTable are independently scrollable/non-overlapping
- [ ] Tab switch to FINANCIALS/INTELLIGENCE shows correct placeholder
- [ ] `tsc --noEmit` passes

---

#### T-B-05: Unit tests for Wave B components

**Type**: test
**depends_on**: [T-B-02, T-B-03]
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/quote/metrics/__tests__/`

| Test | What It Verifies |
|------|-----------------|
| `test_MetricRow_renders_null_as_dash` | null value → "—" rendered |
| `test_MetricRow_applies_color_class` | color prop → correct CSS class |
| `test_MetricGroupDivider_renders_hr` | renders divider div with border class |
| `test_WeekRangeBar_clamps_below_zero` | price < low → 0% fill width |
| `test_WeekRangeBar_clamps_above_100` | price > high → 100% fill width |
| `test_AnalystMiniBar_proportional` | 30B/10H/5S → buy segment 66.6%, hold 22.2%, sell 11.1% |
| `test_AnalystMiniBar_all_null_no_crash` | all-null inputs → no error, empty bar |
| `test_MetricsTable_renders_MARKET_CAP_label` | "MARKET CAP" label present |

**Acceptance criteria**:
- [ ] 8 tests pass; `pnpm test`

### Validation Gate — Wave B
- [ ] `pnpm tsc --noEmit` — zero errors
- [ ] `pnpm test` — all Wave A + Wave B tests pass (13 + 8 = 21 new tests minimum)
- [ ] QUOTE tab renders chart + MetricsTable in browser
- [ ] Chart viewport shows recent bars (not 1985)
- [ ] MetricsTable shows ≥ 20 non-dash values for a real instrument (AAPL, MSFT)
- [ ] All numeric values use monospace tabular-nums font

### Architecture Compliance — Wave B
- [ ] ADR-F-15: every value in MetricsTable uses `font-mono tabular-nums`
- [ ] MetricsTable ≤ 200 lines
- [ ] `useMetricsTableData` hook is the only data-fetch call in MetricsTable (no inline `useQuery`)
- [ ] OHLCVChart ≤ 180 lines after refactor

### Break Impact — Wave B
| Broken file | Why | Fix |
|-------------|-----|-----|
| `InstrumentPageClient.tsx` | QuoteTab placeholder replaced with real component | Done in T-B-04 |
| Old `SessionStatsStrip.tsx` | Modified for density | Done in T-B-01 |

### Regression Guardrails — Wave B
- **Scroll-to-1985 bug** (existing BP): fix must be confirmed by visual inspection in browser. After fix, chart must scroll to real-time on initial render.
- **Format helpers**: Do not invent new `formatCurrency`/`formatPercent` functions. Check `lib/format.ts` and `lib/utils.ts` first; use existing ones.

---

## Wave C — Financials Tab: FlatMetricsGrid + IncomeStatementTable + AnalystSidebar

**Goal**: Build the complete Financials tab. After Wave C, FINANCIALS tab shows the 45-metric flat grid + 4-year income statement + earnings chart, with analyst sidebar.

**Depends on**: Wave A
**Architecture layer**: Frontend — Tab 2

### Pre-read
- PRD-0088 §6.8 (complete FlatMetricsGrid specification — all 8 groups, 45 metrics)
- `apps/worldview-web/types/api.ts` (lines 356–384, EarningsRecord + IncomeStatementData shapes)
- `apps/worldview-web/lib/api/instruments.ts` (getIncomeStatement, getEarningsHistory)

---

#### T-C-01: Build FlatMetricsGrid and MetricCell

**Type**: impl
**depends_on**: [T-A-01, T-A-02]
**blocks**: [T-C-03]
**Target files**:
- `apps/worldview-web/components/instrument/financials/MetricCell.tsx` (NEW)
- `apps/worldview-web/components/instrument/financials/FlatMetricsGrid.tsx` (NEW)

**What to build**:

**`MetricCell.tsx`** (max 60 lines):
- Props: `label: string; value?: React.ReactNode; color?: MetricValueColor`
- Renders: `<div className="flex flex-col gap-0 py-0.5">` (36px total: 14px label + 22px value)
  - `<dt><MetricLabel>{label}</MetricLabel></dt>`
  - `<dd><MetricValue color={color}>{value ?? null}</MetricValue></dd>`

**`FlatMetricsGrid.tsx`** (max 200 lines):
- Props: `instrumentId: string`
- Fetches: `const { fundamentals, snapshot, technicals, shareStats } = useFinancialsTabData(instrumentId)`
- RSI/ATR: `const ohlcvQuery = useQuery({ queryKey: qk.instruments.ohlcv(instrumentId, "1D"), enabled: false })` — reads from cache only (already populated by OHLCVChart). Then `const { rsi, atr } = useChartTechnicals(ohlcvQuery.data?.bars)`
- Layout: `<dl className="grid grid-cols-3 gap-x-6 px-4 py-3">`

**All 8 groups with exact field mappings** (from PRD §6.8.1):

Group VALUATION: P/E Ratio, Forward P/E, Price/Sales, Price/Book, EV/EBITDA, Market Cap
Group PROFITABILITY: Gross Margin, Operating Margin, Net Margin, ROE, ROA, FCF Margin
Group GROWTH: Revenue YoY, Earnings YoY, EPS TTM
Group BALANCE SHEET: Debt/Equity, Current Ratio, Quick Ratio, Interest Coverage, Net Debt/EBITDA
Group CASH FLOW: Operating CF, CapEx, Free Cash Flow
Group DIVIDENDS: Dividend Yield, Payout Ratio
Group OWNERSHIP: Shares Outstanding, Float, Institutional%, Insider%, Short%, Short Ratio
Group TECHNICALS: Beta, 52W High, 52W Low, MA 50, MA 200, RSI(14), ATR(14)

Each group preceded by: `<SectionDivider label="VALUATION" />` (col-span-3)

Field source table (all from PRD §6.8.1):
- VALUATION: `fundamentals.pe_ratio`, `fundamentals.forward_pe`, `fundamentals.price_to_sales`, `fundamentals.price_to_book`, `fundamentals.ev_to_ebitda`, `fundamentals.market_cap`
- PROFITABILITY: `fundamentals.gross_margin`, `fundamentals.operating_margin`, `fundamentals.net_margin`, `fundamentals.roe`, `fundamentals.roa`, `snapshot.fcf_margin`
- GROWTH: `fundamentals.revenue_growth_yoy`, `fundamentals.earnings_growth_yoy`, `snapshot.eps_ttm`
- BALANCE SHEET: `fundamentals.debt_to_equity`, `fundamentals.current_ratio`, `fundamentals.quick_ratio`, `snapshot.interest_coverage`, `snapshot.net_debt_to_ebitda`
- CASH FLOW: `snapshot.operating_cash_flow`, `snapshot.capex`, `snapshot.free_cash_flow`
- DIVIDENDS: `fundamentals.dividend_yield`, `fundamentals.payout_ratio`
- OWNERSHIP: `shareStats.shares_outstanding`, `shareStats.shares_float`, `shareStats.percent_institutions`, `shareStats.percent_insiders`, `technicals.short_percent`, `technicals.short_ratio`
- TECHNICALS: `snapshot.beta`, `fundamentals.week_52_high`, `fundamentals.week_52_low`, `technicals["50_day_ma"]`, `technicals["200_day_ma"]`, `rsi` (computed), `atr` (computed)

**Acceptance criteria**:
- [ ] FlatMetricsGrid renders all 8 group headers
- [ ] ≥ 40 MetricCell elements rendered (some may show "—" if data null)
- [ ] RSI/ATR read from OHLCV cache (no new API call)
- [ ] `tsc --noEmit` passes

---

#### T-C-02: Build IncomeStatementTable and EarningsBarChart

**Type**: impl
**depends_on**: [T-A-01]
**blocks**: [T-C-03]
**Target files**:
- `apps/worldview-web/components/instrument/financials/IncomeStatementTable.tsx` (NEW)
- `apps/worldview-web/components/instrument/financials/EarningsBarChart.tsx` (NEW)

**What to build**:

**`IncomeStatementTable.tsx`** (max 120 lines):
- Props: `instrumentId: string`
- Fetches: `useQuery({ queryKey: qk.instruments.incomeStatement(instrumentId), queryFn: () => createGateway(token).getIncomeStatement(instrumentId), staleTime: 24 * 60 * 60 * 1000 })`
- Parses `FundamentalsSectionResponse` → extracts income statement records, sorts by year desc, takes last 4
- Renders `<table className="w-full text-[11px]">`:
  - `<thead>`: FY column headers (e.g., "FY24 FY23 FY22 FY21") — `text-[10px] font-mono text-muted-foreground`
  - `<tbody>` rows: Revenue, Gross Profit, EBIT, Net Income, EPS — all `font-mono tabular-nums` right-aligned
- Loading state: skeleton table
- Empty state: "Income statement not available." `text-[11px] text-muted-foreground`

**`EarningsBarChart.tsx`** (max 120 lines):
- Props: `instrumentId: string`
- Fetches: `useQuery({ queryKey: qk.instruments.earningsHistory(instrumentId), queryFn: () => createGateway(token).getEarningsHistory(instrumentId), staleTime: 24 * 60 * 60 * 1000 })`
- Renders using recharts (already a project dependency — import `BarChart, Bar, XAxis, ResponsiveContainer` from `recharts`)
- Dual bars: `eps_actual` (solid, beat=`bg-positive`/miss=`bg-negative`) and `eps_estimate` (outline stroke only)
- Chart height: 80px; no legend; X-axis: fiscal year labels; Y-axis: hidden
- Empty state: hidden (no chart rendered)

**Acceptance criteria**:
- [ ] IncomeStatementTable renders 4-column table for real instrument
- [ ] EarningsBarChart renders for real instrument with ≥ 4 years of data
- [ ] No new dependencies added (uses existing recharts)
- [ ] `tsc --noEmit` passes

---

#### T-C-03: Build AnalystSidebar and FinancialsTab orchestrator

**Type**: impl
**depends_on**: [T-A-05, T-C-01, T-C-02]
**blocks**: none
**Target files**:
- `apps/worldview-web/components/instrument/financials/AnalystSidebar.tsx` (NEW)
- `apps/worldview-web/components/instrument/financials/FinancialsTab.tsx` (NEW)

**What to build**:

**`AnalystSidebar.tsx`** (max 120 lines):
- Props: `fundamentals: Fundamentals | null; updatedAt: string | null`
- **Analyst consensus section**: header "ANALYST CONSENSUS" (10px, px-3 py-1.5)
  - `AnalystMiniBar` (imported from quote/metrics) with fundamentals analyst counts
  - Count text: `"{buy+strong_buy}B · {hold}H · {sell+strong_sell}S"` in `text-[10px] font-mono text-muted-foreground`
  - Target price: `fundamentals.analyst_target_price` in `text-[13px] font-mono font-semibold`
  - "Based on {total} analysts": `text-[10px] text-muted-foreground`
- `<DataTimestamp updatedAt={updatedAt} />` at bottom

**`FinancialsTab.tsx`** (max 200 lines):
- Props: `instrumentId: string; fundamentals: Fundamentals | null`
- Fetches: `const { fundamentals: fullFund, snapshot, incomeStatement, earningsHistory, technicals, shareStats } = useFinancialsTabData(instrumentId)`
- Layout: `<div className="flex h-full overflow-hidden">`
  - Left: `<div className="flex-1 min-w-0 overflow-y-auto">`
    - `<FlatMetricsGrid instrumentId={instrumentId} />`
    - Section divider "INCOME STATEMENT"
    - `<IncomeStatementTable instrumentId={instrumentId} />`
    - Section divider "EARNINGS HISTORY"
    - `<EarningsBarChart instrumentId={instrumentId} />`
  - Right: `<div className="w-[280px] flex-shrink-0 border-l border-border overflow-y-auto">`
    - `<AnalystSidebar fundamentals={fullFund} updatedAt={fullFund?.updated_at ?? null} />`
- Update `InstrumentPageClient.tsx` to render `<FinancialsTab ...>` when `activeTab === "financials"`

**Acceptance criteria**:
- [ ] FINANCIALS tab shows all 3 sections (grid, income statement, earnings chart)
- [ ] Right sidebar shows analyst consensus mini bar and target price
- [ ] Layout: scrollable left column, fixed 280px sidebar
- [ ] `tsc --noEmit` passes

---

#### T-C-04: Unit tests for Wave C components

**Type**: test
**depends_on**: [T-C-01, T-C-03]
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/financials/__tests__/`

| Test | What It Verifies |
|------|-----------------|
| `test_FlatMetricsGrid_renders_valuation_label` | "VALUATION" section header present |
| `test_FlatMetricsGrid_renders_all_8_group_labels` | All 8 SectionDivider labels present |
| `test_MetricCell_renders_dash_for_null` | null → "—" via MetricValue |
| `test_AnalystSidebar_renders_consensus_bar` | AnalystMiniBar rendered when counts non-null |

**Acceptance criteria**:
- [ ] 4 tests pass; `pnpm test`

### Validation Gate — Wave C
- [ ] `pnpm tsc --noEmit` — zero errors
- [ ] `pnpm test` — all prior tests + 4 new pass
- [ ] FINANCIALS tab renders in browser: flat grid visible, sidebar visible
- [ ] All 8 group labels visible when scrolling

### Architecture Compliance — Wave C
- [ ] ADR-F-15: all MetricCell values use `font-mono tabular-nums`
- [ ] FlatMetricsGrid ≤ 200 lines
- [ ] No inline `useQuery` in FlatMetricsGrid — data fetched via `useFinancialsTabData` hook only
- [ ] No new npm packages (recharts already installed)

### Break Impact — Wave C
| Broken file | Why | Fix |
|-------------|-----|-----|
| `InstrumentPageClient.tsx` | FinancialsTab placeholder replaced | Done in T-C-03 |

### Regression Guardrails — Wave C
- **Data null guards**: All fundamentals fields are nullable. Every MetricCell must safely receive `null` and render "—". Do not assume any field is non-null.
- **Income statement parse**: `FundamentalsSectionResponse.records` has `.section` and `.data` fields. Parse income statement data from `rec.data` where `rec.section === "income_statement"` or equivalent. Read existing `getIncomeStatement` implementation in `lib/api/instruments.ts` to understand the section key names.

---

## Wave D — Intelligence Tab: EntityGraph Fixes + NewsColumn + ContextPanel

**Goal**: Build the complete Intelligence tab with the 3-column layout. Fix all 3 entity graph bugs. After Wave D, all 3 tabs are fully functional.

**Depends on**: Wave A
**Architecture layer**: Frontend — Tab 3

### Pre-read
- `apps/worldview-web/components/instrument/EntityGraph.tsx` (current implementation — find and read it)
- `apps/worldview-web/components/instrument/intelligence/ContradictionCard.tsx` (keep this)
- `apps/worldview-web/lib/api/knowledge-graph.ts` (getEntityGraph method, lines 38–90)
- `apps/worldview-web/lib/api/intelligence.ts` (useEntityIntelligence hook, lines 89–125)
- PRD-0088 §6.9 (Intelligence tab 3-column specification)
- Memory note: `project_age_cypher_fix_2026_05_11.md` — entity graph bug history
- Memory note: `project_graph_bugs_2026_05_11.md` — depth timeout, node panel, black void bugs

---

#### T-D-01: Fix EntityGraph bugs and add GraphToolbar

**Type**: impl
**depends_on**: [T-A-02]
**blocks**: [T-D-04]
**Target files**:
- `apps/worldview-web/components/instrument/EntityGraph.tsx` (FIX — in-place)
- `apps/worldview-web/components/instrument/intelligence/graph/GraphToolbar.tsx` (NEW)

**What to build**:

**EntityGraph.tsx bug fixes** (3 bugs from PRD §6.9.2):

**Bug 1 — Black void below graph**:
- Find the root div wrapping the sigma.js canvas. Add `className="h-full w-full"` — ensure no fixed height is set on the container div that would leave a gap.
- The parent in `GraphColumn` will be `flex-1 flex flex-col` — EntityGraph must fill this space.

**Bug 2 — Depth=3 504 timeout**:
- `getEntityGraph()` in `lib/api/knowledge-graph.ts` has a `limitByDepth` map. At depth=3, limit=80 nodes. The timeout comes from AGE Cypher query on the backend.
- Frontend fix: set a client-side timeout on the graph query. If the query hasn't returned in 3000ms, cancel and show a "Depth 3 timed out — try depth 1 or 2" message.
- Implementation: use `AbortController` in the `useQuery` queryFn, or use `queryOptions: { retry: 0 }` + `timeout: 3000` pattern.
- After timeout: show `<div className="flex items-center justify-center h-full text-[11px] text-muted-foreground">Graph timed out at depth 3. Try depth 1 or 2.</div>`

**Bug 3 — Node panel never populates (S9 drops edge fields)**:
- The entity graph API in `lib/api/knowledge-graph.ts` receives edge data but the `relation_summary` field may not be mapped/returned.
- Read the `getEntityGraph` response mapping in `knowledge-graph.ts`. Find where edge data is transformed. If `rel.relation_summary` or `edge.relation_summary` is being dropped in the mapping, preserve it.
- If the field is not in the current `GraphEdge` type in `types/api.ts`, add it: `relation_summary: string | null`.
- Existing `ContradictionCard` and detail panels reference this field — ensure it flows through.

**EntityGraph refactor** (max 200 lines after fixes):
- Remove any fixed `height` prop or hardcoded pixel height
- Accept: `depth: number; typeFilters: string[]` props (controlled from parent `GraphColumn`)
- Expose: `onNodeSelect: (nodeId: string | null) => void` prop — fires when a node is clicked or deselected
- `useQuery` for graph data with `qk.instruments.entityGraph(entityId, depth)`

**`GraphToolbar.tsx`** (max 80 lines):
- Props: `depth: number; onDepthChange: (d: number) => void; typeFilters: string[]; onTypeFiltersChange: (f: string[]) => void`
- Renders: `<div className="h-7 border-b border-border flex items-center px-3 gap-4">`
  - "DEPTH" label (10px muted) + shadcn Slider (1–3, step 1)
  - "TYPE" label + shadcn DropdownMenu with checkboxes for relationship types (types come from graph data — unique `rel_type` values)
  - Fullscreen button: ChevronUp icon, triggers `window.requestFullscreen()` on graph container

**Acceptance criteria**:
- [ ] EntityGraph fills its container height (no black void)
- [ ] Depth=3 shows error/timeout message gracefully without crashing
- [ ] `relation_summary` field preserved in edge data (check type + mapping)
- [ ] `onNodeSelect` fires when node clicked
- [ ] GraphToolbar depth slider changes graph depth on change
- [ ] `tsc --noEmit` passes

---

#### T-D-02: Build NewsColumn with CompactArticleRow

**Type**: impl
**depends_on**: [T-A-03]
**blocks**: [T-D-04]
**Target files**:
- `apps/worldview-web/components/instrument/intelligence/news/NewsFilters.tsx` (NEW)
- `apps/worldview-web/components/instrument/intelligence/news/CompactArticleRow.tsx` (NEW)
- `apps/worldview-web/components/instrument/intelligence/news/NewsColumn.tsx` (NEW)

**What to build**:

**`NewsFilters.tsx`** (max 60 lines):
- Props: `timeRange: string; onTimeRangeChange: (v: string) => void; sentiment: string | null; onSentimentChange: (v: string | null) => void`
- Renders: `<div className="h-8 border-b border-border flex items-center px-3 gap-4">`
  - Time filter tabs: ALL | TODAY | 3D | 1W (underline tab style, text-[10px] uppercase)
  - Separator `|` muted
  - Sentiment toggle pills: POS | NEU | NEG (same tab style, right side)
  - Active tab: `border-b-2 border-primary text-foreground`; inactive: `text-muted-foreground`

**`CompactArticleRow.tsx`** (max 80 lines):
- Props: `article: RankedArticle` (type from `types/api.ts` — check existing news types for RankedArticle or NewsArticle shape)
- Renders: `<div className="h-7 flex items-center gap-2 px-3 hover:bg-muted/20 cursor-pointer border-b border-border/20">`
  - Sentiment dot: `<div className="w-1.5 h-1.5 rounded-full flex-shrink-0 {sentimentClass}">` — color per FR-10
  - Time: `text-[10px] font-mono text-muted-foreground w-[30px] flex-shrink-0`
  - Source: `text-[10px] text-muted-foreground truncate w-[60px] flex-shrink-0`
  - Headline: `text-[11px] truncate flex-1`
  - Impact: `text-[10px] font-mono tabular-nums text-muted-foreground w-[30px] text-right`
- onClick: `window.open(article.url, "_blank", "noopener,noreferrer")`
- Sentiment color map: positive → `bg-positive`, negative → `bg-negative`, neutral/mixed → `bg-muted-foreground/50`
- Impact format: `article.impact_score` (0-100) formatted as integer; "—" if null

**`NewsColumn.tsx`** (max 120 lines):
- Props: `entityId: string`
- Local state: `timeRange: "all" | "day" | "3d" | "1w" = "all"`, `sentiment: string | null = null`
- Fetches: `const { data, fetchNextPage, hasNextPage, isFetchingNextPage } = useEntityNewsInfinite(entityId, { sentiment, timeRange })`
- Flatten pages: `const articles = data?.pages.flatMap(p => p.articles) ?? []`
- Infinite scroll: detect scroll near bottom → call `fetchNextPage()` (use `IntersectionObserver` on a sentinel div at bottom of list)
- Empty state: `text-[11px] text-muted-foreground text-center py-8` "No articles for this entity."
- Loading skeleton: 5 skeleton rows of height h-7

**Acceptance criteria**:
- [ ] CompactArticleRow is 28px (h-7) height
- [ ] Headline truncates cleanly at 1 line
- [ ] Sentiment dot shows correct color for each sentiment value
- [ ] NewsColumn scrolls infinitely; next page loads when scrolled to bottom
- [ ] Filter changes re-fetch with new params
- [ ] `tsc --noEmit` passes

---

#### T-D-03: Build ContextPanel, NodeDetailCard, RelationsList

**Type**: impl
**depends_on**: [T-A-02]
**blocks**: [T-D-04]
**Target files**:
- `apps/worldview-web/components/instrument/intelligence/context/NodeDetailCard.tsx` (NEW)
- `apps/worldview-web/components/instrument/intelligence/context/RelationsList.tsx` (NEW)
- `apps/worldview-web/components/instrument/intelligence/context/ContextPanel.tsx` (NEW)

**What to build** (PRD §6.9.3):

**`NodeDetailCard.tsx`** (max 80 lines):
- Props: `node: GraphNode; onBack: () => void` (GraphNode from knowledge-graph types)
- Renders: back button + entity name + type badge + description + confidence score
- All text: labels 10px, values 11px, confidence `font-mono tabular-nums`

**`RelationsList.tsx`** (max 80 lines):
- Props: `edges: GraphEdge[]` (edges connected to selected node)
- Each edge row: `<div className="flex items-start gap-2 py-1.5 border-b border-border/30">`
  - Relation type badge: `text-[9px] uppercase bg-muted/30 px-1 rounded-[2px]`
  - Target entity name: `text-[11px]`
  - `relation_summary`: `text-[10px] text-muted-foreground italic line-clamp-2` — "No summary available." if null
- Empty: hidden (don't render the component if edges.length === 0)

**`ContextPanel.tsx`** (max 120 lines):
- Props: `entityId: string; selectedNodeId: string | null; onBack: () => void; graph: GraphResponse | null; intelligence: EntityIntelligencePublic | null`
- Import: `import type { EntityIntelligencePublic } from "@/types/intelligence"`
- When `selectedNodeId === null` (entity overview mode):
  - Header "ENTITY OVERVIEW"
  - Entity type from intelligence data
  - First 3 sentences of `intelligence.narrative` as description
  - Health score badge (colored per FR-10 thresholds: green >70, amber 40-70, red <40)
  - Evidence quality rows (High/Medium/Low as mini progress bars)
  - Contradictions: render `<ContradictionCard>` (existing component from `intelligence/ContradictionCard.tsx`) for the first 2 contradictions (query from `useQuery` for `qk.instruments.contradictions(entityId)`)
- When `selectedNodeId !== null` (node selected):
  - Find node in `graph.nodes` where `node.id === selectedNodeId`
  - Render `<NodeDetailCard node={selectedNode} onBack={onBack} />`
  - Find edges connected to selectedNode
  - Render `<RelationsList edges={connectedEdges} />`

**Acceptance criteria**:
- [ ] ContextPanel shows entity overview when no node selected
- [ ] ContextPanel shows NodeDetailCard when node selected (clicking Back deselects)
- [ ] RelationsList shows relation_summary when available; "No summary available." when null
- [ ] Contradictions render (if data available)
- [ ] `tsc --noEmit` passes

---

#### T-D-04: Build GraphColumn and IntelligenceTab orchestrator

**Type**: impl
**depends_on**: [T-A-03, T-A-05, T-D-01, T-D-02, T-D-03]
**blocks**: none
**Target files**:
- `apps/worldview-web/components/instrument/intelligence/graph/GraphColumn.tsx` (NEW)
- `apps/worldview-web/components/instrument/intelligence/IntelligenceTab.tsx` (NEW — rewrites existing)

**What to build** (PRD §6.9.2 and §6.9):

**`GraphColumn.tsx`** (max 150 lines):
- Props: `entityId: string; selectedNodeId: string | null; onNodeSelect: (id: string | null) => void`
- Local state: `depth: number = 2; typeFilters: string[] = []`
- Fetches: `const { data: brief } = useQuery({ queryKey: qk.instruments.brief(entityId), queryFn: ... staleTime: 10min })`
- Fetches: `const { data: intelligence } = useEntityIntelligence(entityId)`
- Renders:
  - AI Brief card (always expanded — full text, not collapsible; this is the Intelligence tab full view)
    - `<div className="mx-3 mt-3 p-3 bg-card border border-border/50 rounded-[2px]">`
    - Header row: "INTELLIGENCE BRIEF" + health score badge inline
    - Brief text: `text-[11px] leading-[1.6] text-foreground/80`
    - Timestamp
  - `<GraphToolbar depth={depth} onDepthChange={setDepth} ... />`
  - `<EntityGraph entityId={entityId} depth={depth} typeFilters={typeFilters} onNodeSelect={onNodeSelect} />`

**`IntelligenceTab.tsx`** (max 200 lines — NEW, replaces old version):
- Props: `instrumentId: string; entityId: string`
- State: `selectedNodeId: string | null = null`
- Fetches: `const { data: graph } = useQuery({ queryKey: qk.instruments.entityGraph(entityId, 2), ... })`
- Fetches: `const { data: intelligence } = useEntityIntelligence(entityId)`
- Layout: `<div className="flex h-full overflow-hidden">`
  - Left (w-[30%]): `<NewsColumn entityId={entityId} />`
  - Center (flex-1): `<GraphColumn entityId={entityId} selectedNodeId={selectedNodeId} onNodeSelect={setSelectedNodeId} />`
  - Right (w-[25%]): `<ContextPanel entityId={entityId} selectedNodeId={selectedNodeId} onBack={() => setSelectedNodeId(null)} graph={graph} intelligence={intelligence} />`
- Update `InstrumentPageClient.tsx` to render `<IntelligenceTab ...>` when `activeTab === "intelligence"`

**Acceptance criteria**:
- [ ] INTELLIGENCE tab renders 3 columns: news | graph+brief | context
- [ ] Clicking a graph node updates ContextPanel to show NodeDetailCard
- [ ] Clicking Back in NodeDetailCard returns to entity overview
- [ ] Brief card shows full text (expanded, not collapsed) on Intelligence tab
- [ ] `tsc --noEmit` passes

### Validation Gate — Wave D
- [ ] `pnpm tsc --noEmit` — zero errors
- [ ] `pnpm test` — all prior tests pass
- [ ] All 3 tabs functional in browser
- [ ] Graph renders without black void
- [ ] Depth=1 and depth=2 graph render without timeout
- [ ] NewsColumn shows compact article rows; scroll to bottom loads more
- [ ] Clicking a node shows node detail; Back returns to overview

### Architecture Compliance — Wave D
- [ ] R14: All API calls go through `createGateway(token)` → S9
- [ ] ADR-F-15: impact score in CompactArticleRow uses `font-mono tabular-nums`
- [ ] EntityGraph ≤ 200 lines after fix
- [ ] IntelligenceTab ≤ 200 lines

### Break Impact — Wave D
| Broken file | Why | Fix |
|-------------|-----|-----|
| `InstrumentPageClient.tsx` | Intelligence placeholder replaced | Done in T-D-04 |
| Old `types/api.ts` GraphEdge type | `relation_summary` field added | Done in T-D-01 |

### Regression Guardrails — Wave D
- **OQ-1 guard**: `relation_summary` may be null in real API responses. `RelationsList` must render "No summary available." gracefully — do not throw when null.
- **OQ-4 guard**: Depth=3 504 timeout handling implemented in T-D-01. If `getEntityGraph` throws a timeout/network error, show the timeout message — do not show a generic error boundary.
- **Entity graph black void (existing BP)**: Confirmed fix in T-D-01: `h-full w-full` on the sigma canvas container. Visually verify in browser before marking Wave D complete.

---

## Wave E — Cleanup + Unit Tests + E2E Tests

**Goal**: Delete all deprecated component files, write missing unit tests, write new Playwright E2E tests. After Wave E, the codebase is clean (no dead code), all tests pass, TypeScript is clean.

**Depends on**: Waves B, C, D complete (all tabs functional)
**Architecture layer**: Testing + cleanup

### Pre-read
- PRD-0088 §11 (Test strategy — all specified tests)
- PRD-0088 §8 (Break surface — list of files to delete)
- Existing Playwright tests in `apps/worldview-web/playwright/` or `tests/` — read to understand test patterns

---

#### T-E-01: Delete deprecated component files

**Type**: impl
**depends_on**: none (but run after B/C/D are complete)
**blocks**: [T-E-04]
**Target files**: all deprecated files listed in PRD-0088 §6.10 "Files to DELETE"

**What to build**:
Delete ALL of the following (verify no imports remain before deleting each):
```
components/instrument/InstrumentAISubheader.tsx
components/instrument/AnalystRail.tsx
components/instrument/PerformanceBar.tsx
components/instrument/OverviewLayout.tsx
components/instrument/OverviewSidebar.tsx
components/instrument/FundamentalsTab.tsx
components/instrument/InstrumentKeyMetrics.tsx
components/instrument/NewsTab.tsx
components/instrument/IntelligenceTab.tsx  ← OLD (replaced by new)
components/instrument/InstrumentTopNews.tsx
components/instrument/OverviewInsiderStrip.tsx
components/instrument/FundamentalSparkline.tsx
components/instrument/EntityGraphPanel.tsx
components/instrument/InsiderTransactionsTable.tsx
components/instrument/AnalystConsensusStrip.tsx
components/instrument/RevenueTrendSparklines.tsx
components/instrument/IncomeStatementFY.tsx
components/instrument/AnalystTargetSparkline.tsx
components/instrument/MarketPositionPanel.tsx
components/instrument/PeerComparisonPanel.tsx
components/instrument/ShortInterestRow.tsx
components/instrument/FundamentalsTopNews.tsx
components/instrument/InstrumentBriefPanel.tsx
components/instrument/intelligence/InstrumentBriefSection.tsx
components/instrument/intelligence/IntelligenceSummarySection.tsx
components/instrument/intelligence/IntelligenceFilters.tsx
components/instrument/intelligence/GraphDetailSidebar.tsx
components/instrument/TechnicalSnapshot.tsx
components/instrument/OwnershipSnapshotPanel.tsx
components/instrument/SplitsDividendsPanel.tsx
components/instrument/EarningsHistoryChart.tsx
components/instrument/52WeekRangeBar.tsx
components/instrument/CompactInstrumentHeader.tsx
components/instrument/DrawingPalette.tsx
components/instrument/DrawingCanvas.tsx
components/instrument/CrosshairHUD.tsx
components/instrument/VolumeProfileOverlay.tsx
components/instrument/graph/GraphControls.tsx
components/instrument/graph/GraphLegend.tsx
components/instrument/graph/SigmaInternalComponents.tsx
components/instrument/fundamentals/FundamentalsMetricsGrid.tsx
components/instrument/fundamentals/fundamentals-helpers.ts
components/instrument/EntityDescriptionPanel.tsx
components/instrument/InstrumentAskAiButton.tsx
components/instrument/EntityGraphErrorBoundary.tsx
```

**Procedure**:
1. For each file: `grep -rn "from.*<filename>" apps/worldview-web/` — verify zero imports before deleting
2. Delete the file
3. After all deletions: run `pnpm tsc --noEmit` — must produce zero errors

**Note**: `LiveQuoteBadge.tsx` is KEPT (used by InstrumentHeader). `ChartToolbar.tsx`, `TimeframeToolbar.tsx`, `chart/useChartSeries.ts`, `chart/createChartSeries.ts`, `SessionStatsStrip.tsx`, `EntityGraph.tsx` are all KEPT (refactored in-place).

**Acceptance criteria**:
- [ ] All listed files deleted
- [ ] Zero import references to deleted files in the codebase
- [ ] `pnpm tsc --noEmit` zero errors after deletions

---

#### T-E-02: Write remaining unit tests

**Type**: test
**depends_on**: [T-E-01]
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/**/__tests__/`

**Tests to write** (completing PRD §11 test matrix):

| Test | File | What It Verifies |
|------|------|-----------------|
| `test_AiBriefBanner_hides_when_brief_null` | `brief/__tests__/AiBriefBanner.test.tsx` | null brief → banner not rendered |
| `test_AiBriefBanner_expands_on_click` | same | click → expanded; second click → collapsed |
| `test_CompactArticleRow_positive_sentiment_dot` | `news/__tests__/CompactArticleRow.test.tsx` | positive sentiment → green dot class |
| `test_CompactArticleRow_renders_impact_score` | same | impact_score 82 → "82" text rendered |
| `test_CompactArticleRow_handles_null_impact` | same | null impact_score → "—" |
| `test_AnalystMiniBar_empty_on_all_zero_counts` | (already in T-B-05 — skip if done) | |
| `test_FlatMetricsGrid_reads_rsi_from_cache` | `financials/__tests__/FlatMetricsGrid.test.tsx` | RSI renders when OHLCV bars in cache |
| `test_IncomeStatementTable_renders_4_columns` | `financials/__tests__/IncomeStatementTable.test.tsx` | 4 year columns rendered |
| `test_WeekRangeMini_renders_yellow_fill` | (already in T-A-06 — skip if done) | |

**Acceptance criteria**:
- [ ] ≥ 6 new tests from the list above (some may already exist from Wave A/B/C tasks)
- [ ] All tests pass: `pnpm test`
- [ ] Total new test count: ≥ 29 (across all waves)

---

#### T-E-03: Write Playwright E2E tests

**Type**: test
**depends_on**: [T-E-01]
**blocks**: [T-E-04]
**Target files**: `apps/worldview-web/e2e/` or `apps/worldview-web/tests/e2e/` (find existing E2E directory)

**Tests to write** (from PRD §11):

| Test | What It Verifies |
|------|-----------------|
| `test_instrument_page_quote_tab_chart_visible` | QUOTE tab: chart canvas rendered without scrolling to 1985; chart container visible |
| `test_instrument_header_shows_ticker` | Header contains ticker text |
| `test_instrument_metrics_table_has_rows` | QUOTE tab: at least 20 text elements matching "MARKET CAP", "P/E", etc. |
| `test_financials_tab_flat_grid_visible` | Click FINANCIALS → "VALUATION" text visible |
| `test_intelligence_tab_news_column_visible` | Click INTELLIGENCE → at least 1 article row visible |
| `test_ai_brief_banner_toggle` | Brief banner: click expands, click again collapses |
| `test_tab_keyboard_mnemonic_f` | Press F → FINANCIALS tab active |

Use `page.goto("/instruments/[test-entityId]")` with a known test entity. Follow existing E2E patterns in the project.

**Acceptance criteria**:
- [ ] All 7 E2E tests pass against the dev server (`pnpm dev`)
- [ ] Tests use page objects or helper functions (not raw `page.locator` chains throughout)

---

#### T-E-04: Final TypeScript check + docs update

**Type**: docs + config
**depends_on**: [T-E-01, T-E-02, T-E-03]
**blocks**: none
**Target files**:
- `docs/ui/DESIGN_SYSTEM.md` (add new components to catalogue)
- `apps/worldview-web/README.md` (update if instrument page is mentioned)

**What to build**:

**`docs/ui/DESIGN_SYSTEM.md`** updates:
- Add `AiBriefBanner` to component catalogue (description + props summary)
- Add `CompactArticleRow` (28px compact article row)
- Add `MetricRow` (22px data row — canonical for instrument metrics)
- Add `MetricsTable` (26-row dense sidebar table pattern — replaces 9-section card pattern)
- Update density table: MetricRow 22px, CompactArticleRow 28px

**Final validation**:
- `pnpm tsc --noEmit` → 0 errors
- `pnpm lint` (or `eslint`) → 0 errors
- `pnpm test` → all tests pass
- `pnpm build` → build succeeds (no runtime import errors)

**Acceptance criteria**:
- [ ] `pnpm build` succeeds with no errors
- [ ] `pnpm tsc --noEmit` → 0 errors
- [ ] DESIGN_SYSTEM.md updated with 4 new component entries
- [ ] No references to deleted files anywhere in codebase

### Validation Gate — Wave E
- [ ] `pnpm build` — successful production build
- [ ] `pnpm tsc --noEmit` — zero errors
- [ ] `pnpm test` — all ≥ 29 new tests pass
- [ ] `pnpm test:e2e` — all 7 E2E tests pass
- [ ] Zero references to deleted component files in any `.ts` / `.tsx` file

### Architecture Compliance — Wave E
- [ ] No `// @ts-ignore` or `// @ts-expect-error` in new files
- [ ] No `any` type assertions without explicit comment justification
- [ ] DESIGN_SYSTEM.md updated

### Break Impact — Wave E
| Broken file | Why | Fix |
|-------------|-----|-----|
| Old E2E tests for `/instruments/[id]` | Old component selectors no longer exist | Done in T-E-03 (full rewrite) |

### Regression Guardrails — Wave E
- **Import verification before delete**: Run grep before deleting each file. Skipping this causes TypeScript build failures. Do it mechanically, not from memory.
- **pnpm build check**: Run `pnpm build` at the end of Wave E, not just `tsc`. Next.js build catches additional errors (missing `"use client"` directives, server component violations) that `tsc` misses.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Entity graph sigma.js integration breaks after EntityGraph refactor | Medium | High | Keep EntityGraph nearly intact — only add `h-full w-full` and fix the `hasScrolledToRealTime` + relation_summary issues |
| `getEarningsHistory` / `getIncomeStatement` section key names mismatch | Medium | Medium | Read existing implementation in `instruments.ts` before building consumers |
| RSI/ATR from OHLCV cache miss (chart not yet loaded when Financials tab opened first) | Low | Low | `useQuery({ enabled: false })` reads from cache; if miss, shows "—" gracefully |
| Playwright E2E flakiness on chart render timing | Medium | Low | Add `waitForSelector` on chart canvas before asserting |

## Compounding Updates Required

After implementing this plan:
- **BUG_PATTERNS.md**: Add: "component file import not checked before deletion causes TypeScript build failure"
- **DESIGN_SYSTEM.md**: Add 4 new component catalogue entries (Wave E, T-E-04)
- **STANDARDS.md**: Add: "FlatMetricsGrid / MetricsTable pattern — use flat metric cells at 22px, not section cards, for dense data display"
