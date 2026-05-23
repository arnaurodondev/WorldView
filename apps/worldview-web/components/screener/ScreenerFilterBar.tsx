/**
 * components/screener/ScreenerFilterBar.tsx — Multi-section collapsible screener filter panel
 *
 * WHY THIS EXISTS: PLAN-0051 Wave B (T-B-2-02 / T-B-2-03 / T-B-2-04) replaces the
 * original 3-control filter bar (search / sector / cap tier) with a much larger
 * filter panel grouped into FIVE collapsible sub-sections:
 *
 * 1. Valuation — P/E, P/B, P/S, Dividend Yield (4 metrics, server-side)
 * 2. Profitability — ROE, Gross Margin, Net Margin, Operating Margin (4 metrics; gross margin = backend pending)
 * 3. Growth — Revenue YoY, Earnings YoY (2 metrics, server-side)
 * 4. Leverage — Debt/Equity, Current Ratio (2 metrics, both backend pending — see audit)
 * 5. Technical — Above 50d MA, RSI band, Volume vs 30d, 52W range (mostly client-side, see TODOs)
 * 6. News & Signals — News velocity 7d, Controversy, Recent earnings, Insider activity (all client-side TODO)
 *
 * Plus the existing top row (Search / Sector / Cap tier) which lives outside any section
 * because it is the primary filter most users adjust first.
 *
 * WHY EACH SECTION COLLAPSES: with up to ~16 inputs the panel would dominate the
 * viewport — terminals optimise for data density, not chrome. Each section header
 * shows a small badge counting *active* filters in that section so the user can
 * see at a glance where filters are set without expanding everything.
 *
 * WHY grid-template-rows ANIMATION (not max-height):
 * §0.5 of the design system bans animating `height` or `max-height` directly —
 * these trigger browser layout recalculation on every animation frame (expensive).
 * `grid-template-rows: 0fr → 1fr` is the approved pattern: it collapses/expands
 * cleanly with a CSS transition, no JS animation, no reflow cost.
 *
 * WHY APPLY BUTTON (not live filter):
 * The screener POST /v1/fundamentals/screen is a database query. Firing it on
 * every keystroke would hammer S9 unnecessarily. An explicit "Apply" button
 * gives the user control and batches the request.
 *
 * WHY SAVE SCREEN BUTTON IS A NO-OP HERE:
 * The Save Screen modal is implemented in PLAN-0051 Wave B Part 2 (T-B-2-05).
 * Part 1 only emits `onSaveScreen()` — the parent decides whether to wire it.
 *
 * BACKEND METRIC NAMES (authoritative — see docs/services/market-data.md):
 * The frontend MUST use the exact metric names from the `metric_extractor.py`
 * truth column. The seed names in `screen_field_metadata` are NOT correct (see
 * docs/audits/2026-04-29-screener-metric-gap.md). Names used here:
 * pe_ratio, pb_ratio, price_sales_ttm, dividend_yield,
 * roe_ttm, profit_margin, operating_margin_ttm,
 * quarterly_revenue_growth_yoy, quarterly_earnings_growth_yoy,
 * market_capitalization, beta.
 *
 * WHO USES IT: app/(app)/screener/page.tsx
 * DESIGN REFERENCE: PRD-0031 §7 Screener filter bar, §0.5 approved animations
 */

"use client";
// WHY "use client": uses useState for controlled inputs and per-section open/close state.
// The whole panel re-renders on every keystroke as the user types into number fields,
// which is fine because state is local — nothing crosses the network until Apply.

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from "@/components/ui/select";

// ── PLAN-0059 E-4 — extracted constants / types / sub-components / counts ─────
// The bar used to hold all of these inline (~310 LOC). They now live under
// `features/screener/`. Pure helpers `isSet` / `rangeCount` /
// `countActiveFiltersByGroup` are unit-tested in
// `features/screener/lib/__tests__/active-counts.test.ts` (18 tests).
import {
 GICS_SECTORS,
 CAP_TIERS,
 DEFAULT_FILTERS,
 type FilterState,
} from "@/features/screener/lib/filter-state";
import { countActiveFiltersByGroup } from "@/features/screener/lib/active-counts";
import { Section } from "@/features/screener/components/Section";
import { RangeInput } from "@/features/screener/components/RangeInput";

// Re-export FilterState + DEFAULT_FILTERS so existing call sites that import
// from `@/components/screener/ScreenerFilterBar` keep compiling unchanged.
export { DEFAULT_FILTERS, type FilterState } from "@/features/screener/lib/filter-state";

interface ScreenerFilterBarProps {
 /** Current open/collapsed state of the OUTER panel — parent-controlled to allow external toggle */
 isOpen: boolean;
 /** Toggle outer panel open/collapsed */
 onToggle: () => void;
 /** Called when user clicks "Apply" — parent fires the API query */
 onApply: (filters: FilterState) => void;
 /** Called when user clicks "Save Screen…" — Part 2 will open a modal here */
 onSaveScreen?: (filters: FilterState) => void;
 /** Total result count for display in the header row (response.total) */
 totalResults: number;
 /** Number of results currently loaded into the result list (response.count summed across pages) */
 loadedCount?: number;
 /** Whether the query is currently loading (initial isFetching) */
 isLoading: boolean;
}

// ── ScreenerFilterBar ─────────────────────────────────────────────────────────

export function ScreenerFilterBar({
 isOpen,
 onToggle,
 onApply,
 onSaveScreen,
 totalResults,
 loadedCount,
 isLoading,
}: ScreenerFilterBarProps) {
 // WHY local form state: filter values are pending until the user clicks Apply.
 // Storing them locally prevents partial filters from triggering API calls while
 // the user is still typing. Only onApply commits them to the parent.
 const [form, setForm] = useState<FilterState>(DEFAULT_FILTERS);

 // ── Per-section active counts (PLAN-0059 E-4 pure helper) ─────────────────
 // Single pass over FilterState produces all 6 section badge counts. Cheap
 // (≤30 boolean checks) so we don't memoise. Pinned by 18 unit tests in
 // features/screener/lib/__tests__/active-counts.test.ts.
 const counts = countActiveFiltersByGroup(form);
 const {
 valuation: valuationCount,
 profitability: profitabilityCount,
 growth: growthCount,
 leverage: leverageCount,
 technical: technicalCount,
 news: newsCount,
 } = counts;

 // ── Handlers ────────────────────────────────────────────────────────────────

 function handleApply() {
 onApply(form);
 }

 /**
 * handleReset — clears every filter back to DEFAULT_FILTERS.
 * Also commits the reset to the parent so the result list refreshes.
 */
 function handleReset() {
 setForm(DEFAULT_FILTERS);
 onApply(DEFAULT_FILTERS);
 }

 // WHY a generic patcher: every input writes a single field. A single setter
 // saves a function-per-field declaration (≈40 inline arrow functions) and
 // makes refactoring (renaming a field) a one-line change.
 function patch(p: Partial<FilterState>) {
 setForm((prev) => ({ ...prev, ...p }));
 }

 // ── Render ──────────────────────────────────────────────────────────────────

 return (
 <div className="shrink-0">
 {/* ── Header row with result count + filter toggle ───────────────── */}
 <div className="flex h-[36px] items-center justify-between border-b border-border px-2">
 <div className="flex items-center gap-2">
 {/* WHY font-mono: ADR-F-15 — section labels use IBM Plex Mono */}
 <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
 SCREENER
 </span>
 {/*
 * Result count — shown as "X of Y" when the loaded count differs from total
 * (i.e. the user has loaded a partial page via Load More). Otherwise just total.
 * 10px ALL CAPS muted, matching DESIGN_SYSTEM.md typography for chrome.
 */}
 <span
 className="font-mono text-[10px] tabular-nums uppercase tracking-[0.06em] text-muted-foreground"
 aria-label="Result count"
 >
 {isLoading
 ? "…"
 : loadedCount !== undefined && loadedCount < totalResults
 ? `${loadedCount.toLocaleString()} of ${totalResults.toLocaleString()} match`
 : `${totalResults.toLocaleString()} match`}
 </span>
 </div>

 <div className="flex items-center gap-2">
 <button
 aria-label="Close screener filters"
 aria-expanded={isOpen}
 aria-controls="screener-filter-panel"
 className="flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-foreground font-mono uppercase tracking-[0.06em]"
 onClick={onToggle}
 >
 Filters
 <ChevronDown
 className={cn(
 "h-3 w-3 transition-[transform] duration-150",
 isOpen && "rotate-180",
 )}
 aria-hidden
 strokeWidth={1.5}
 />
 </button>
 {/* Reset — visible in header for quick reset without opening the panel */}
 <button
 aria-label="Reset all filters"
 className="text-[10px] text-muted-foreground hover:text-foreground font-mono uppercase tracking-[0.06em]"
 onClick={handleReset}
 >
 Reset
 </button>
 </div>
 </div>

 {/* ── Collapsible filter form (outer container) ───────────────────── */}
 {/*
 * WHY grid overflow pattern: gridTemplateRows: "0fr"→"1fr" + overflow-hidden
 * on the outer, min-h-0 on inner. This is the §0.5 approved animation pattern.
 * The outer grid sets the visible height; the inner min-h-0 allows collapse to 0.
 */}
 <div
 id="screener-filter-panel"
 role="region"
 aria-label="Screener filters"
 className="grid overflow-hidden border-b border-border transition-[grid-template-rows] duration-200 ease-out"
 style={{ gridTemplateRows: isOpen ? "1fr" : "0fr" }}
 >
 <div className="overflow-hidden min-h-0">
 {/* ── Top row: search / sector / cap tier (always-visible primary filters) ── */}
 <div className="flex h-[36px] items-center gap-2 px-2 bg-background border-b border-border/60">
 <label htmlFor="screener-search" className="sr-only">
 Search instruments by name or ticker
 </label>
 <input
 id="screener-search"
 aria-label="Search instruments by name or ticker"
 type="text"
 autoComplete="off"
 placeholder="Ticker / name…"
 value={form.search}
 onChange={(e) => patch({ search: e.target.value })}
 className="h-7 w-32 px-2 text-[11px] font-mono bg-background border border-border rounded-[2px] text-foreground placeholder:text-muted-foreground/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary focus-visible:ring-offset-0"
 onKeyDown={(e) => e.key === "Enter" && handleApply()}
 />

 <label htmlFor="screener-sector" className="sr-only">
 Filter by GICS sector
 </label>
 <Select
 value={form.sector || "__all__"}
 onValueChange={(v) => patch({ sector: v === "__all__" ? "" : v })}
 >
 <SelectTrigger
 id="screener-sector"
 aria-label="Filter by GICS sector"
 className="h-7 w-40 text-[11px] rounded-[2px] border-border bg-background focus:ring-1 focus:ring-primary"
 >
 <SelectValue placeholder="All sectors" />
 </SelectTrigger>
 <SelectContent className="text-[11px]">
 <SelectItem value="__all__">All sectors</SelectItem>
 {GICS_SECTORS.map((s) => (
 <SelectItem key={s} value={s}>{s}</SelectItem>
 ))}
 </SelectContent>
 </Select>

 <div className="flex items-center gap-1" role="group" aria-label="Market cap tier">
 {CAP_TIERS.map(({ value, label, description }) => (
 <button
 key={value}
 aria-label={`${label} cap: ${description}`}
 aria-pressed={form.capTier === value}
 className={cn(
 "h-7 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border rounded-[2px] transition-colors",
 form.capTier === value
 ? "bg-primary/10 border-primary text-primary"
 : "bg-background border-border text-muted-foreground hover:text-foreground hover:border-border/80",
 )}
 onClick={() => patch({ capTier: value })}
 >
 {label}
 </button>
 ))}
 </div>
 </div>

 {/* ── VALUATION SECTION ────────────────────────────────────────── */}
 {/* Default open — most users start here. */}
 <Section title="Valuation" activeCount={valuationCount} defaultOpen>
 <div className="flex flex-col gap-1.5">
 <RangeInput
 label="P/E (TTM)"
 tooltip="Price ÷ Earnings (TTM). S&P 500 avg ≈ 20–25×. Below 15 may be undervalued; above 40 = high growth priced in."
 min={form.peMin} max={form.peMax}
 minPlaceholder="e.g. 10"
 maxPlaceholder="e.g. 50"
 onMin={(v) => patch({ peMin: v })}
 onMax={(v) => patch({ peMax: v })}
 />
 <RangeInput
 label="P/B"
 tooltip="Price ÷ Book Value. Below 1 = trades at discount to assets; above 5 = premium franchise. Sector-dependent."
 min={form.pbMin} max={form.pbMax}
 minPlaceholder="e.g. 0.5"
 maxPlaceholder="e.g. 5"
 onMin={(v) => patch({ pbMin: v })}
 onMax={(v) => patch({ pbMax: v })}
 />
 <RangeInput
 label="P/S (TTM)"
 tooltip="Price ÷ Revenue (TTM). Useful for pre-profit companies. SaaS median ≈ 5–10×."
 min={form.psMin} max={form.psMax}
 minPlaceholder="e.g. 1"
 maxPlaceholder="e.g. 10"
 onMin={(v) => patch({ psMin: v })}
 onMax={(v) => patch({ psMax: v })}
 />
 {/* WHY hint "decimal": dividend_yield is stored as decimal 0.015 = 1.5%.
 * Showing the hint avoids the common error of typing 1.5 expecting %. */}
 <RangeInput
 label="Dividend Yield"
 hint="decimal"
 tooltip="Annual dividends ÷ price %. 0% = growth stock; 3–5% = income stock; above 6% may signal risk."
 min={form.divYieldMin} max={form.divYieldMax}
 minPlaceholder="e.g. 0.01"
 maxPlaceholder="e.g. 0.06"
 onMin={(v) => patch({ divYieldMin: v })}
 onMax={(v) => patch({ divYieldMax: v })}
 />
 </div>
 </Section>

 {/* ── PROFITABILITY SECTION ────────────────────────────────────── */}
 <Section title="Profitability" activeCount={profitabilityCount}>
 <div className="flex flex-col gap-1.5">
 <RangeInput
 label="ROE (TTM)"
 hint="decimal"
 tooltip="Net income ÷ avg equity. Above 15% = strong capital efficiency. Buffett target: sustained above 20%."
 min={form.roeMin} max={form.roeMax}
 minPlaceholder="e.g. 0.05"
 maxPlaceholder="e.g. 0.30"
 onMin={(v) => patch({ roeMin: v })}
 onMax={(v) => patch({ roeMax: v })}
 />
 {/*
 * Gross margin — BACKEND_PENDING per audit: only `gross_profit_ttm` and
 * `revenue_ttm` are extracted; the ratio is not stored. Disabled with badge
 * so the UI shows our intent without hitting an empty WHERE clause.
 * FR-4.4: hidden unless NEXT_PUBLIC_ENABLE_PENDING_METRICS="true".
 */}
 {process.env.NEXT_PUBLIC_ENABLE_PENDING_METRICS === "true" && (
 <RangeInput
 label="Gross Margin"
 hint="decimal"
 disabled
 disabledReason="Backend pending — gross_margin not derived in fundamental_metrics"
 min={form.grossMarginMin} max={form.grossMarginMax}
 onMin={(v) => patch({ grossMarginMin: v })}
 onMax={(v) => patch({ grossMarginMax: v })}
 />
 )}
 <RangeInput
 label="Net Margin"
 hint="decimal"
 tooltip="Net income ÷ revenue. Above 20% = pricing power or moat; below 5% = commodity-like business."
 min={form.netMarginMin} max={form.netMarginMax}
 minPlaceholder="e.g. 0.05"
 maxPlaceholder="e.g. 0.40"
 onMin={(v) => patch({ netMarginMin: v })}
 onMax={(v) => patch({ netMarginMax: v })}
 />
 <RangeInput
 label="Op Margin"
 hint="decimal"
 tooltip="Operating income ÷ revenue. Strips one-time items; more comparable across capital structures than net margin."
 min={form.opMarginMin} max={form.opMarginMax}
 minPlaceholder="e.g. 0.05"
 maxPlaceholder="e.g. 0.35"
 onMin={(v) => patch({ opMarginMin: v })}
 onMax={(v) => patch({ opMarginMax: v })}
 />
 </div>
 </Section>

 {/* ── GROWTH SECTION ───────────────────────────────────────────── */}
 <Section title="Growth" activeCount={growthCount}>
 <div className="flex flex-col gap-1.5">
 <RangeInput
 label="Revenue YoY"
 hint="decimal"
 tooltip="Quarterly revenue vs same quarter prior year (decimal: 0.15 = +15%). Positive = growing business."
 min={form.revGrowthMin} max={form.revGrowthMax}
 onMin={(v) => patch({ revGrowthMin: v })}
 onMax={(v) => patch({ revGrowthMax: v })}
 />
 <RangeInput
 label="Earnings YoY"
 hint="decimal"
 tooltip="Quarterly EPS vs same quarter prior year. Accelerating positive growth = momentum signal."
 min={form.earningsGrowthMin} max={form.earningsGrowthMax}
 onMin={(v) => patch({ earningsGrowthMin: v })}
 onMax={(v) => patch({ earningsGrowthMax: v })}
 />
 </div>
 </Section>

 {/* ── LEVERAGE SECTION ─────────────────────────────────────────── */}
 {/* Both filters are BACKEND_PENDING — see audit. Disabled inputs make this clear. */}
 {/* FR-4.4: entire Leverage section hidden unless NEXT_PUBLIC_ENABLE_PENDING_METRICS="true"
 * because all its controls are backend-pending. Avoids confusing users with
 * inputs that look interactive but always no-op. */}
 {process.env.NEXT_PUBLIC_ENABLE_PENDING_METRICS === "true" && (
 <Section title="Leverage" activeCount={leverageCount}>
 <div className="flex flex-col gap-1.5">
 <RangeInput
 label="Debt/Equity"
 disabled
 disabledReason="Backend pending — ratio not derived"
 min={form.debtEquityMin} max={form.debtEquityMax}
 onMin={(v) => patch({ debtEquityMin: v })}
 onMax={(v) => patch({ debtEquityMax: v })}
 />
 <RangeInput
 label="Current Ratio"
 disabled
 disabledReason="Backend pending — ratio not derived"
 min={form.currentRatioMin} max={form.currentRatioMax}
 onMin={(v) => patch({ currentRatioMin: v })}
 onMax={(v) => patch({ currentRatioMax: v })}
 />
 </div>
 </Section>
 )}

 {/* ── TECHNICAL SECTION ────────────────────────────────────────── */}
 {/*
 * All controls below are CLIENT_FILTER unless tagged otherwise — the
 * parent page applies them post-fetch on the ScreenerResult[]. None of
 * RSI / 50d MA / 52W range / volume ratio is in fundamental_metrics today;
 * a future server endpoint would let us push them down (T-B-2-01 audit).
 */}
 <Section title="Technical" activeCount={technicalCount}>
 <div className="flex flex-col gap-1.5">
 {/* Above 50d MA — checkbox */}
 <label className="flex items-center gap-2 h-6">
 <input
 type="checkbox"
 aria-label="Filter to instruments above 50-day moving average"
 checked={form.above50dMa ?? false}
 onChange={(e) => patch({ above50dMa: e.target.checked || undefined })}
 className="h-3 w-3 accent-primary cursor-pointer"
 />
 <span className="text-[10px] font-mono uppercase tracking-[0.06em] text-muted-foreground">
 Above 50d MA
 </span>
 <span className="text-[9px] font-mono uppercase tracking-[0.06em] text-warning/70">
 client-side
 </span>
 </label>

 {/* RSI band — 0–100 */}
 <RangeInput
 label="RSI"
 hint="0–100"
 min={form.rsiMin} max={form.rsiMax}
 onMin={(v) => patch({ rsiMin: v })}
 onMax={(v) => patch({ rsiMax: v })}
 />

 {/* Volume vs 30d avg — discrete select */}
 <div className="flex items-center gap-2">
 <label
 htmlFor="vol-ratio"
 className="text-[10px] font-mono uppercase tracking-[0.06em] text-muted-foreground w-24 shrink-0"
 >
 Vol vs 30d
 </label>
 <Select
 value={form.volumeRatioMin?.toString() ?? "__off__"}
 onValueChange={(v) =>
 patch({ volumeRatioMin: v === "__off__" ? undefined : Number(v) })
 }
 >
 <SelectTrigger
 id="vol-ratio"
 aria-label="Volume relative to 30 day average"
 className="h-6 w-32 text-[11px] rounded-[2px] border-border bg-background focus:ring-1 focus:ring-primary"
 >
 <SelectValue placeholder="Off" />
 </SelectTrigger>
 <SelectContent className="text-[11px]">
 <SelectItem value="__off__">Off</SelectItem>
 <SelectItem value="1">≥ 1× (above avg)</SelectItem>
 <SelectItem value="1.5">≥ 1.5×</SelectItem>
 <SelectItem value="2">≥ 2× (heavy volume)</SelectItem>
 </SelectContent>
 </Select>
 <span className="text-[9px] font-mono uppercase tracking-[0.06em] text-warning/70">
 client-side
 </span>
 </div>

 {/*
 * Distance from 52W high — a single "max" input. "Within 5% of 52W high"
 * means dist ≤ 5% so we capture a *max* not a range.
 */}
 <div className="flex items-center gap-2">
 <label
 htmlFor="dist-high"
 className="text-[10px] font-mono uppercase tracking-[0.06em] text-muted-foreground w-24 shrink-0"
 >
 ≤ 52W High
 </label>
 <input
 id="dist-high"
 aria-label="Maximum distance from 52 week high in percent"
 type="number"
 step="any"
 placeholder="% max"
 value={form.distFrom52wHighMax ?? ""}
 onChange={(e) => {
 const n = Number(e.target.value);
 patch({
 distFrom52wHighMax:
 e.target.value.trim() === "" || !Number.isFinite(n) ? undefined : n,
 });
 }}
 className="h-6 w-20 px-1.5 text-[11px] font-mono tabular-nums bg-background border border-border rounded-[2px] text-foreground placeholder:text-muted-foreground/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
 />
 <span className="text-[9px] font-mono uppercase tracking-[0.06em] text-warning/70">
 client-side
 </span>
 </div>

 {/* Distance from 52W low — "≥ X%" min input */}
 <div className="flex items-center gap-2">
 <label
 htmlFor="dist-low"
 className="text-[10px] font-mono uppercase tracking-[0.06em] text-muted-foreground w-24 shrink-0"
 >
 ≥ 52W Low
 </label>
 <input
 id="dist-low"
 aria-label="Minimum distance from 52 week low in percent"
 type="number"
 step="any"
 placeholder="% min"
 value={form.distFrom52wLowMin ?? ""}
 onChange={(e) => {
 const n = Number(e.target.value);
 patch({
 distFrom52wLowMin:
 e.target.value.trim() === "" || !Number.isFinite(n) ? undefined : n,
 });
 }}
 className="h-6 w-20 px-1.5 text-[11px] font-mono tabular-nums bg-background border border-border rounded-[2px] text-foreground placeholder:text-muted-foreground/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
 />
 <span className="text-[9px] font-mono uppercase tracking-[0.06em] text-warning/70">
 client-side
 </span>
 </div>
 </div>
 </Section>

 {/* ── NEWS & SIGNALS SECTION ───────────────────────────────────── */}
 {/*
 * All four controls are CLIENT_FILTER TODO — the data lives in S6/S7
 * (signals + knowledge graph), not in the screener response. Until a
 * composed S9 endpoint exists, these inputs collect intent but apply
 * no filtering. Marked with "TODO: server" badges so the user
 * understands the limitation.
 */}
 <Section title="News & Signals" activeCount={newsCount}>
 <div className="flex flex-col gap-1.5">
 {/* News velocity 7d — min count */}
 <div className="flex items-center gap-2">
 <label
 htmlFor="news-velocity"
 className="text-[10px] font-mono uppercase tracking-[0.06em] text-muted-foreground w-24 shrink-0"
 >
 News 7d ≥
 </label>
 <input
 id="news-velocity"
 aria-label="Minimum news article count over the past 7 days"
 type="number"
 step="1"
 min="0"
 placeholder="count"
 value={form.newsVelocity7dMin ?? ""}
 onChange={(e) => {
 const n = Number(e.target.value);
 patch({
 newsVelocity7dMin:
 e.target.value.trim() === "" || !Number.isFinite(n) ? undefined : n,
 });
 }}
 className="h-6 w-20 px-1.5 text-[11px] font-mono tabular-nums bg-background border border-border rounded-[2px] text-foreground placeholder:text-muted-foreground/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
 />
 <span className="text-[9px] font-mono uppercase tracking-[0.06em] text-warning/70">
 TODO: server
 </span>
 </div>

 {/* Controversy score range */}
 {/* FR-4.4: hidden unless NEXT_PUBLIC_ENABLE_PENDING_METRICS="true".
 * The controversy score is backend-pending (lives in S6 signals);
 * showing a non-functional range input only confuses users. */}
 {process.env.NEXT_PUBLIC_ENABLE_PENDING_METRICS === "true" && (
 <RangeInput
 label="Controversy"
 hint="0–1"
 disabled
 disabledReason="Backend pending — controversy score lives in S6 signals; needs composed S9 endpoint"
 min={form.controversyMin} max={form.controversyMax}
 onMin={(v) => patch({ controversyMin: v })}
 onMax={(v) => patch({ controversyMax: v })}
 />
 )}

 {/* Recent earnings — discrete pill set */}
 <div className="flex items-center gap-2">
 <label
 htmlFor="recent-earnings"
 className="text-[10px] font-mono uppercase tracking-[0.06em] text-muted-foreground w-24 shrink-0"
 >
 Recent earnings
 </label>
 <Select
 value={form.recentEarningsDays?.toString() ?? "__off__"}
 onValueChange={(v) =>
 patch({
 recentEarningsDays:
 v === "__off__" ? undefined : (Number(v) as 7 | 30),
 })
 }
 >
 <SelectTrigger
 id="recent-earnings"
 aria-label="Filter to instruments with earnings in last N days"
 className="h-6 w-32 text-[11px] rounded-[2px] border-border bg-background focus:ring-1 focus:ring-primary"
 >
 <SelectValue placeholder="Off" />
 </SelectTrigger>
 <SelectContent className="text-[11px]">
 <SelectItem value="__off__">Off</SelectItem>
 <SelectItem value="7">Last 7 days</SelectItem>
 <SelectItem value="30">Last 30 days</SelectItem>
 </SelectContent>
 </Select>
 <span className="text-[9px] font-mono uppercase tracking-[0.06em] text-warning/70">
 TODO: server
 </span>
 </div>

 {/* Insider activity */}
 <div className="flex items-center gap-2">
 <label
 htmlFor="insider-activity"
 className="text-[10px] font-mono uppercase tracking-[0.06em] text-muted-foreground w-24 shrink-0"
 >
 Insider
 </label>
 <Select
 value={form.insiderActivity ?? "__off__"}
 onValueChange={(v) =>
 patch({
 insiderActivity:
 v === "__off__"
 ? undefined
 : (v as "BUYING" | "SELLING" | "BOTH"),
 })
 }
 >
 <SelectTrigger
 id="insider-activity"
 aria-label="Filter by insider transaction direction"
 className="h-6 w-32 text-[11px] rounded-[2px] border-border bg-background focus:ring-1 focus:ring-primary"
 >
 <SelectValue placeholder="Off" />
 </SelectTrigger>
 <SelectContent className="text-[11px]">
 <SelectItem value="__off__">Off</SelectItem>
 <SelectItem value="BUYING">Buying</SelectItem>
 <SelectItem value="SELLING">Selling</SelectItem>
 <SelectItem value="BOTH">Both</SelectItem>
 </SelectContent>
 </Select>
 <span className="text-[9px] font-mono uppercase tracking-[0.06em] text-warning/70">
 TODO: server
 </span>
 </div>
 </div>
 </Section>

 {/* ── BOTTOM TOOLBAR ──────────────────────────────────────────── */}
 <div className="flex h-[36px] items-center gap-2 px-2 bg-background">
 <button
 aria-label="Apply filters"
 className="h-7 px-3 text-[10px] font-mono uppercase tracking-[0.06em] bg-primary/10 border border-primary/60 text-primary rounded-[2px] hover:bg-primary/20 transition-colors"
 onClick={handleApply}
 >
 Apply
 </button>
 <button
 aria-label="Reset filters"
 className="h-7 px-3 text-[10px] font-mono uppercase tracking-[0.06em] bg-background border border-border text-muted-foreground rounded-[2px] hover:text-foreground hover:border-border/80 transition-colors"
 onClick={handleReset}
 >
 Reset
 </button>
 {/*
 * Save Screen… — Part 2 (T-B-2-05) opens a name dialog. Part 1 just emits
 * the callback if the parent provides one. When `onSaveScreen` is undefined
 * we hide the button entirely so it doesn't promise a feature we haven't shipped.
 */}
 {onSaveScreen && (
 <button
 aria-label="Save current screen"
 className="h-7 px-3 text-[10px] font-mono uppercase tracking-[0.06em] bg-background border border-border text-muted-foreground rounded-[2px] hover:text-foreground hover:border-border/80 transition-colors ml-auto"
 onClick={() => onSaveScreen(form)}
 >
 Save Screen…
 </button>
 )}
 </div>
 </div>
 </div>
 </div>
 );
}
