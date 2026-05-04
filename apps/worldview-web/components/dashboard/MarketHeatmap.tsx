/**
 * components/dashboard/MarketHeatmap.tsx — GICS sector performance treemap
 *
 * WHY THIS EXISTS: Portfolio managers need instant macro context — which sectors
 * are moving today. Finviz/Bloomberg both feature this prominently for the same
 * reason: pattern recognition from color at a glance.
 *
 * PLAN-0059 H-3 + QA iter-1:
 *   - Migrated from a fixed grid (every cell same size) to a Bruls/Huijsen/
 *     van Wijk squarified treemap. Cell area ∝ instrument_count (best proxy
 *     until S9 returns market_cap_weight on the heatmap response).
 *   - Tiles are KEYBOARD-REACHABLE (regression fix from QA iter-1). Click /
 *     Enter / Space navigates to the screener filtered by sector.
 *   - Items array memoised so squarify doesn't re-run on every parent render.
 *   - Loading state replaced by single fade-in pulse (no relayout snap on data load).
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx
 * DATA SOURCE: S9 GET /v1/market/heatmap → S3 screener grouped by sector
 * DESIGN REFERENCE: PRD-0028 §6.5 Dashboard MarketHeatmap, DESIGN_SYSTEM.md HeatCell
 */

"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { heatCellColor } from "@/lib/utils";
import { SquarifiedTreemap, type SquarifiedTreemapItem } from "@/components/ui/squarified-treemap";
import type { HeatmapSector } from "@/types/api";

// ── Component ─────────────────────────────────────────────────────────────────

export function MarketHeatmap() {
  const { accessToken } = useAuth();
  const router = useRouter();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["market-heatmap"],
    queryFn: () => createGateway(accessToken).getMarketHeatmap(),
    enabled: !!accessToken,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  // Memoise items so the treemap doesn't see a fresh array reference each render
  // (would re-run squarify + remount every tile, losing hover transitions).
  const items: SquarifiedTreemapItem<HeatmapSector>[] = useMemo(() => {
    if (!data?.sectors) return [];
    return data.sectors.map((s) => ({
      id: s.name,
      weight: s.instrument_count > 0 ? s.instrument_count : 1,
      payload: s,
    }));
  }, [data]);

  if (isLoading) {
    // Single fade-in pulse — no relayout snap when real data arrives.
    return <div className="h-56 rounded-[2px] bg-muted/20" aria-busy="true" />;
  }

  if (isError || !data) {
    return (
      <p className="py-3 text-xs text-muted-foreground">
        Heatmap unavailable — sector data will appear once market data is ingested.
      </p>
    );
  }

  return (
    <div className="h-56">
      <SquarifiedTreemap<HeatmapSector>
        items={items}
        gap={2}
        minWidth={48}
        minHeight={28}
        ariaLabel="Sector performance treemap"
        renderTile={(cell) => <SectorTile sector={cell.item.payload} cellWidth={cell.width} />}
        getTileAriaLabel={(item) => {
          const s = item.payload;
          const change =
            s.change_pct !== null
              ? `${s.change_pct >= 0 ? "+" : ""}${s.change_pct.toFixed(2)} percent`
              : "no data";
          return `${s.name} sector, ${s.instrument_count} instruments, ${change}. Activate to view in screener.`;
        }}
        onTileClick={(item) => {
          // Drill-down: navigate to screener pre-filtered by sector. Existing
          // screener URL accepts a `sector` query param (kept generic to
          // survive screener filter-bar refactors).
          router.push(`/screener?sector=${encodeURIComponent(item.payload.name)}`);
        }}
      />
    </div>
  );
}

// ── Tile ──────────────────────────────────────────────────────────────────────

function SectorTile({ sector, cellWidth }: { sector: HeatmapSector; cellWidth: number }) {
  const { background, color } = heatCellColor(sector.change_pct);
  // Below ~70px, the abbreviation truncates and competes with the percentage —
  // hide it and lean on the aria-label + tooltip for full identification.
  const showLabel = cellWidth >= 70;
  return (
    <div
      className="flex h-full w-full flex-col items-center justify-center rounded-[2px] p-1 text-center"
      style={{ backgroundColor: background }}
      title={sector.name}
    >
      {showLabel && (
        <span className="truncate text-[10px] font-medium leading-tight" style={{ color }}>
          {abbreviateSector(sector.name)}
        </span>
      )}
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
  // Fallback uses first-word slice to avoid mid-word cuts ("Telecommunications" → "Telecommun").
  return abbreviations[name] ?? name.split(" ")[0]!.slice(0, 9);
}
