/**
 * components/dashboard/MarketHeatmap.tsx — GICS sector performance grid
 *
 * WHY THIS EXISTS: Portfolio managers need instant macro context — which sectors
 * are moving today. The heatmap gives a visual distribution of market forces
 * without reading individual stock data. Finviz/Bloomberg both feature this
 * prominently for the same reason: pattern recognition from color at a glance.
 *
 * WHY 7-STEP COLOR SCALE:
 * Linear interpolation from deep red (−3%) → neutral (#1A2030) → deep teal (+3%)
 * maps the typical daily range. Outside ±3% is clipped to max saturation.
 * Intermediates: step at ±1%, ±2%. 7 steps avoids visual noise from continuous gradients.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx
 * DATA SOURCE: S9 GET /api/v1/market/heatmap → S3 screener grouped by sector
 * DESIGN REFERENCE: PRD-0028 §6.5 Dashboard MarketHeatmap, DESIGN_SYSTEM.md HeatCell
 */

"use client";
// WHY "use client": uses useQuery for data fetching.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { heatCellColor } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

// ── Component ─────────────────────────────────────────────────────────────────

export function MarketHeatmap() {
  const { accessToken } = useAuth();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["market-heatmap"],
    queryFn: () => createGateway(accessToken).getMarketHeatmap(),
    enabled: !!accessToken,
    // WHY 60s: heatmap is a macro view; sub-minute refresh would be noise
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="grid grid-cols-3 gap-1 sm:grid-cols-4">
        {Array.from({ length: 11 }).map((_, i) => (
          <Skeleton key={i} className="h-14" style={{ animationDelay: `${i * 40}ms` }} />
        ))}
      </div>
    );
  }

  // ── Error state ────────────────────────────────────────────────────────────
  // WHY muted (not destructive red): backend service offline is not a user error.
  if (isError || !data) {
    return (
      <div className="flex h-24 items-center justify-center">
        <p className="text-sm text-muted-foreground">
          Heatmap unavailable — sector data will appear once market data is ingested.
        </p>
      </div>
    );
  }

  return (
    // WHY 3 cols on mobile, 4 on sm+: 11 GICS sectors need 3 rows minimum
    <div className="grid grid-cols-3 gap-1 sm:grid-cols-4">
      {data.sectors.map((sector) => {
        const { background, color } = heatCellColor(sector.change_pct);

        return (
          <div
            key={sector.name}
            className="flex min-h-[3.5rem] flex-col items-center justify-center rounded p-1 text-center"
            style={{ backgroundColor: background }}
          >
            {/* Sector name — abbreviated to fit tight cell */}
            <span
              className="truncate text-[10px] font-medium leading-tight"
              style={{ color }}
              title={sector.name}
            >
              {abbreviateSector(sector.name)}
            </span>
            {/* Percentage change — the most important data point */}
            <span
              className="font-mono text-xs font-semibold tabular-nums"
              style={{ color }}
            >
              {sector.change_pct !== null
                ? `${sector.change_pct >= 0 ? "+" : ""}${sector.change_pct.toFixed(2)}%`
                : "—"}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * abbreviateSector — shorten GICS sector names for heatmap cells
 * WHY: cells are only ~80px wide; full names like "Consumer Discretionary" overflow
 */
function abbreviateSector(name: string): string {
  const abbreviations: Record<string, string> = {
    "Information Technology": "Tech",
    "Health Care": "Health",
    "Consumer Discretionary": "Cons Disc",
    "Consumer Staples": "Cons Stpl",
    "Communication Services": "Comm Svcs",
    "Financials": "Fins",
    "Industrials": "Indus",
    "Materials": "Matls",
    "Real Estate": "RE",
    "Utilities": "Util",
    "Energy": "Energy",
  };
  return abbreviations[name] ?? name.slice(0, 9);
}
