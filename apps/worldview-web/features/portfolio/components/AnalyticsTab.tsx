/**
 * features/portfolio/components/AnalyticsTab.tsx
 *
 * WHY THIS EXISTS: Composes all analytics sub-components into the full analytics
 * tab layout. This component owns no data fetching — it wires URL state (nuqs)
 * to the period/benchmark selectors and passes the resolved values to each child.
 * Keeping composition here means each child is a pure "data-owning + rendering"
 * component while the tab handles layout and URL state.
 *
 * LAYOUT (12-column grid, per design spec §4.3):
 *   Row 1: Period selector pill row + Benchmark selector (h=28px sticky bar)
 *   Row 2: AnalyticsPerformanceChart (full width, 220px)
 *   Row 3: AnalyticsDrawdownChart (full width, 120px, shares x-axis semantically)
 *   Row 4: [AnalyticsRiskSidebar col-span-5] | [Attribution section col-span-7]
 *             Attribution section: tabs (Holding / Sector / Asset Class) + table
 *   Row 5: AnalyticsPeriodReturnsTable (full width)
 *
 * URL STATE (nuqs):
 *   ?analyticsPeriod=YTD — period selector; bookmarkable and deep-linkable
 *   ?analyticsBm=SPY     — benchmark selector; bookmarkable
 *   Both use parseAsString so any string is accepted without validation error
 *   (future benchmarks like QQQ or custom tickers won't break the URL parser).
 *
 * LOCAL STATE (useState):
 *   attribution dimension — not URL state because dimension preference is UX-only
 *   (Holding/Sector/AssetClass). The user doesn't bookmark "I always want sector
 *   attribution" — they switch it interactively. This matches the design spec §8
 *   "Attribution dimension state: local useState (not URL)".
 *
 * DESIGN REFERENCE: docs/designs/0089/04-portfolio-detail.md §4.3, §8
 */
"use client";
// WHY "use client": uses nuqs useQueryState (browser URL API) and useState.

import { useState } from "react";
import { useQueryState, parseAsString } from "nuqs";
import { useQuery } from "@tanstack/react-query";

// WHY useApiClient + qk + ExtendedRiskMetricsResponse (Wave G QA M-007):
// AnalyticsTab now reads `as_of` from the risk-metrics response so it can
// pass it to AnalyticsPeriodSelector for the DataFreshnessPill (design
// spec §4.3). The query reuses the same cache entry the sidebar consumes
// — TanStack dedups by key so this is not an extra fetch.
import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import type { ExtendedRiskMetricsResponse } from "@/types/api";

import { cn } from "@/lib/utils";
import { AnalyticsPeriodSelector } from "./AnalyticsPeriodSelector";
import { AnalyticsPerformanceChart } from "./AnalyticsPerformanceChart";
import { AnalyticsDrawdownChart } from "./AnalyticsDrawdownChart";
import { AnalyticsRiskSidebar } from "./AnalyticsRiskSidebar";
import { AnalyticsAttributionTable } from "./AnalyticsAttributionTable";
import { AnalyticsPeriodReturnsTable } from "./AnalyticsPeriodReturnsTable";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface AnalyticsTabProps {
  /** Resolved portfolio UUID from the parent layout. */
  portfolioId: string;
}

// ── Benchmark options ─────────────────────────────────────────────────────────

// WHY SPY-only for now: design spec §10 open question 1 resolved — benchmark
// dropdown is SPY-only for v1. QQQ/IWM/custom are deferred. The dropdown renders
// as disabled with a "Additional benchmarks in a future release" title so the
// user understands it's coming rather than thinking it's broken.
const BENCHMARKS = ["SPY"] as const;

// ── Attribution dimension tab config ─────────────────────────────────────────

const DIMENSIONS = [
  { key: "holding" as const,    label: "Holding" },
  { key: "sector" as const,     label: "Sector" },
  { key: "asset_class" as const, label: "Asset Class" },
];

// ── Component ─────────────────────────────────────────────────────────────────

export function AnalyticsTab({ portfolioId }: AnalyticsTabProps) {
  // ── URL state (nuqs) ──────────────────────────────────────────────────────
  // WHY parseAsString.withDefault: nuqs provides a null-safe default so the
  // component renders with "YTD" even on the first load without a URL param.
  // WHY "period" / "benchmark" (not "analyticsPeriod" / "analyticsBm"):
  // design §4.3 mandates deep-link URL parity with the other portfolio surfaces
  // (Overview, Holdings) which already use `?period=` and `?benchmark=` —
  // QA fix D2 (Wave G remediation).
  const [period, setPeriod] = useQueryState(
    "period",
    parseAsString.withDefault("YTD"),
  );
  const [benchmark, setBenchmark] = useQueryState(
    "benchmark",
    parseAsString.withDefault("SPY"),
  );

  // ── Local state ───────────────────────────────────────────────────────────
  // WHY useState (not nuqs): attribution dimension is a UI preference, not a
  // bookmarkable filter. Keeping it out of the URL prevents "noise" params that
  // don't need to round-trip through the location bar.
  const [attributionDimension, setAttributionDimension] = useState<
    "holding" | "sector" | "asset_class"
  >("holding");

  // ── Risk-metrics query (M-007: share cache with AnalyticsRiskSidebar) ────
  // WHY same key/staleTime as the sidebar: TanStack Query dedups requests by
  // queryKey across the React tree. Tab + sidebar share one in-flight fetch
  // and one cache entry; the only reason this hook exists at the tab level
  // is to surface `as_of` for the DataFreshnessPill in the controls bar.
  const apiClient = useApiClient();
  const { data: riskMetricsData } = useQuery({
    queryKey: qk.portfolios.riskMetrics(portfolioId),
    queryFn: () => apiClient.getRiskMetrics(portfolioId),
    enabled: !!portfolioId,
    staleTime: 300_000,
  });
  const lastUpdated =
    (riskMetricsData as ExtendedRiskMetricsResponse | undefined)?.as_of ?? null;

  return (
    <div className="flex flex-col gap-2 p-3">

      {/* ── Row 1: Controls bar ──────────────────────────────────────────── */}
      {/* WHY sticky top-0 z-10: the controls bar should stay visible when
          the user scrolls down through the charts. Same sticky pattern as the
          portfolio page header bar (h=[36px], z=10). */}
      <div className="flex items-center gap-3 h-[28px] sticky top-0 z-10 bg-background/95 backdrop-blur-sm py-1">
        {/* Period pills + freshness pill (M-007) */}
        <AnalyticsPeriodSelector
          value={period}
          onChange={setPeriod}
          lastUpdated={lastUpdated}
        />

        {/* Benchmark selector — v1 SPY-only (disabled, title explains why) */}
        <div className="flex items-center gap-1 ml-auto">
          <span className="text-[10px] font-mono text-muted-foreground uppercase tracking-wide">
            Benchmark
          </span>
          {/* WHY render as a disabled button group rather than a real select:
              single-option selects look like they have choices. A disabled pill
              matching the period selector's style communicates "one option now,
              more coming" — matching the design spec open question 1 resolution. */}
          <div
            title="Additional benchmarks in a future release"
            className="flex items-center gap-0.5"
          >
            {BENCHMARKS.map((bm) => (
              <button
                key={bm}
                onClick={() => setBenchmark(bm)}
                disabled={BENCHMARKS.length <= 1 && benchmark === bm}
                className={cn(
                  "text-[11px] font-mono px-2 py-0.5 rounded transition-colors",
                  benchmark === bm
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:text-foreground",
                  BENCHMARKS.length <= 1 && "opacity-60 cursor-not-allowed",
                )}
              >
                {bm}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Row 2: Performance chart ─────────────────────────────────────── */}
      {/* WHY border + rounded: every analytics section uses the same card
          container pattern (1px border-border, rounded-[2px]) for visual
          grouping. Matches the RiskMetricsStrip and ConcentrationStrip chrome. */}
      <div className="border border-border rounded-[2px] p-2">
        <div className="text-[10px] font-mono text-muted-foreground uppercase tracking-wide mb-1 px-1">
          Performance
        </div>
        <AnalyticsPerformanceChart
          portfolioId={portfolioId}
          period={period}
          benchmark={benchmark}
        />
      </div>

      {/* ── Row 3: Drawdown chart ─────────────────────────────────────────── */}
      {/* WHY separate card from performance chart: the design spec ASCII art
          shows them as stacked separate blocks sharing the x-axis range but
          not the same card container. This allows the drawdown chart to have
          its own "MAX DRAWDOWN" label row above it. */}
      <div className="border border-border rounded-[2px] p-2">
        <AnalyticsDrawdownChart
          portfolioId={portfolioId}
          period={period}
        />
      </div>

      {/* ── Row 4: Risk sidebar + Attribution ─────────────────────────────── */}
      {/* WHY 5+7 column split: the risk sidebar needs a fixed ~200px for 11
          tiles in 4 columns to be legible. At standard screen widths (1280+)
          this maps to roughly 5/12 of the available width. The attribution
          table gets the remaining 7/12 for the longer name strings. */}
      <div className="grid grid-cols-12 gap-2">
        {/* Risk sidebar */}
        <div className="col-span-12 lg:col-span-5 border border-border rounded-[2px] p-2">
          <div className="text-[10px] font-mono text-muted-foreground uppercase tracking-wide mb-2">
            Risk Metrics
          </div>
          {/* WHY no period prop (Wave G QA D10): the risk-metrics endpoint is
              lookback_days-keyed (90d default) and the qk.portfolios.riskMetrics
              key signature is `(portfolioId)` only — passing period was unused
              cargo. See AnalyticsRiskSidebar JSDoc for the full rationale. */}
          <AnalyticsRiskSidebar portfolioId={portfolioId} />
        </div>

        {/* Attribution section */}
        <div className="col-span-12 lg:col-span-7 border border-border rounded-[2px] p-2">
          {/* Attribution dimension tab bar */}
          <div className="flex items-center gap-1 mb-2">
            {DIMENSIONS.map((d) => (
              <button
                key={d.key}
                onClick={() => setAttributionDimension(d.key)}
                className={cn(
                  "text-[10px] font-mono px-2 py-0.5 rounded transition-colors",
                  attributionDimension === d.key
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:text-foreground",
                )}
              >
                {d.label}
              </button>
            ))}
          </div>

          {/* Attribution table for selected dimension */}
          <AnalyticsAttributionTable
            portfolioId={portfolioId}
            period={period}
            dimension={attributionDimension}
          />
        </div>
      </div>

      {/* ── Row 5: Period returns table ───────────────────────────────────── */}
      {/* WHY full width: the 4-column table needs room for period labels and
          return values. At 1/2 width it becomes cramped; full width gives each
          cell enough space to show "+12.84%" without truncation. */}
      <div className="border border-border rounded-[2px] p-2">
        <div className="text-[10px] font-mono text-muted-foreground uppercase tracking-wide mb-1">
          Period Returns
        </div>
        <AnalyticsPeriodReturnsTable portfolioId={portfolioId} />
      </div>

    </div>
  );
}
