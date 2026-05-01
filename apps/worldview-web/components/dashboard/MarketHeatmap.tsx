/**
 * components/dashboard/MarketHeatmap.tsx — GICS sector performance treemap
 *
 * WHY THIS EXISTS: Portfolio managers need instant macro context — which sectors
 * are moving today. The heatmap gives a visual distribution of market forces
 * without reading individual stock data. Finviz/Bloomberg both feature this
 * prominently for the same reason: pattern recognition from color at a glance.
 *
 * PLAN-0059 H-3: migrated from a fixed grid (every cell same size) to a true
 * Bruls/Huijsen/van Wijk squarified treemap (lib/treemap.ts) where cell area
 * is proportional to the sector's `instrument_count` (best proxy for sector
 * weight until S9 returns market_cap_weight on the heatmap response).
 *
 * WHY squarified (not flex grid): institutional treemaps communicate TWO axes
 * — direction (color) AND magnitude (size). Equal-cell grids miss the second
 * axis entirely. With squarify, Tech (largest sector by instrument count)
 * visually dominates while Materials (smallest) gets a smaller tile, matching
 * Finviz / Bloomberg conventions.
 *
 * WHY 7-STEP COLOR SCALE:
 * Linear interpolation deep red (−3%) → neutral → deep teal (+3%) maps the
 * typical daily range. Outside ±3% is clipped to max saturation.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx
 * DATA SOURCE: S9 GET /v1/market/heatmap → S3 screener grouped by sector
 * DESIGN REFERENCE: PRD-0028 §6.5 Dashboard MarketHeatmap, DESIGN_SYSTEM.md HeatCell
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { heatCellColor } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { SquarifiedTreemap } from "@/components/ui/squarified-treemap";
import type { HeatmapSector } from "@/types/api";

// ── Component ─────────────────────────────────────────────────────────────────

export function MarketHeatmap() {
  const { accessToken } = useAuth();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["market-heatmap"],
    queryFn: () => createGateway(accessToken).getMarketHeatmap(),
    enabled: !!accessToken,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <div className="grid grid-cols-3 gap-1 sm:grid-cols-4 h-56">
        {Array.from({ length: 11 }).map((_, i) => (
          <Skeleton key={i} className="h-full" style={{ animationDelay: `${i * 40}ms` }} />
        ))}
      </div>
    );
  }

  if (isError || !data) {
    return (
      <p className="py-3 text-xs text-muted-foreground">
        Heatmap unavailable — sector data will appear once market data is ingested.
      </p>
    );
  }

  // Treemap input: weight by instrument_count when present, fall back to 1
  // so flat-zero sectors still receive a visible tile.
  const items = data.sectors.map((s) => ({
    id: s.name,
    weight: s.instrument_count > 0 ? s.instrument_count : 1,
    payload: s,
  }));

  return (
    // Fixed 14rem (224px) height — keeps the treemap inside the dashboard
    // card without forcing a CLS jump after measurement.
    <div className="h-56">
      <SquarifiedTreemap
        items={items}
        gap={2}
        ariaLabel="Sector performance treemap"
        renderTile={(cell) => <SectorTile sector={cell.item.payload} />}
      />
    </div>
  );
}

// ── Tile ──────────────────────────────────────────────────────────────────────

function SectorTile({ sector }: { sector: HeatmapSector }) {
  const { background, color } = heatCellColor(sector.change_pct);
  return (
    <div
      className="flex h-full w-full flex-col items-center justify-center rounded-[2px] p-1 text-center"
      style={{ backgroundColor: background }}
      title={sector.name}
      aria-label={`${sector.name} sector, ${sector.instrument_count} instruments, ${
        sector.change_pct !== null
          ? `${sector.change_pct >= 0 ? "+" : ""}${sector.change_pct.toFixed(2)} percent`
          : "no data"
      }`}
    >
      <span className="truncate text-[10px] font-medium leading-tight" style={{ color }}>
        {abbreviateSector(sector.name)}
      </span>
      <span className="font-mono text-xs font-semibold tabular-nums" style={{ color }}>
        {sector.change_pct !== null
          ? `${sector.change_pct >= 0 ? "+" : ""}${sector.change_pct.toFixed(2)}%`
          : "—"}
      </span>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function abbreviateSector(name: string): string {
  const abbreviations: Record<string, string> = {
    "Information Technology": "Tech",
    "Health Care": "Health",
    "Consumer Discretionary": "Cons Disc",
    "Consumer Staples": "Cons Stpl",
    "Communication Services": "Comm Svcs",
    Financials: "Fins",
    Industrials: "Indus",
    Materials: "Matls",
    "Real Estate": "RE",
    Utilities: "Util",
    Energy: "Energy",
  };
  return abbreviations[name] ?? name.slice(0, 9);
}
