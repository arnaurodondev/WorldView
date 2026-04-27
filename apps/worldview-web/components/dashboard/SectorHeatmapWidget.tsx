/**
 * components/dashboard/SectorHeatmapWidget.tsx — Sector performance horizontal bars
 *
 * WHY THIS EXISTS: Portfolio managers need instant macro context — which sectors
 * are moving today. The heatmap gives a visual distribution of market forces
 * without reading individual stock data. This widget replaces the old grid-style
 * MarketHeatmap for the dashboard Row 2 slot with a horizontal bar format that
 * is more space-efficient in the wider (col-span-8) dashboard cell.
 *
 * WHY HORIZONTAL BARS (not color cells): The wider col-span-8 slot suits bar
 * charts better than the square tile grid used in the old MarketHeatmap widget.
 * Bars communicate relative magnitude across sectors at a glance — the length
 * encodes the absolute change, the color encodes direction.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 2, col-span-8)
 * DATA SOURCE: S9 GET /v1/market/heatmap → createGateway().getMarketHeatmap()
 * DESIGN REFERENCE: PRD-0031 §10 Dashboard Wave 7
 */

"use client";
// WHY "use client": uses useQuery for data fetching, useAuth for the token,
// and useState for the period selector.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { cn } from "@/lib/utils";
import type { HeatmapSector } from "@/types/api";

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * SectorHeatmapWidget — GICS sector performance as horizontal fill bars.
 * Shows sector name, bar fill (proportional to magnitude), and % change value.
 */
// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * WHY period selector: sector performance over different horizons tells different
 * stories — 1D is today's rotation, 1W shows a weekly trend, 1M captures the
 * monthly momentum shift. Local state for now; future wave will wire to S9 param.
 */
type SectorPeriod = "1D" | "1W" | "1M";

export function SectorHeatmapWidget() {
  const { accessToken } = useAuth();

  // WHY default "1D": the most critical time period at market open is today's
  // session. Longer periods are informative context but secondary.
  const [period, setPeriod] = useState<SectorPeriod>("1D");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["sector-heatmap-widget"],
    queryFn: () => createGateway(accessToken).getMarketHeatmap(),
    enabled: !!accessToken,
    // WHY 300_000 (5min): sector performance is a macro view; sub-minute refresh
    // would be noise. 5 min ensures fresh enough data while reducing S9 load.
    staleTime: 300_000,
    refetchInterval: 300_000,
  });

  return (
    // WHY flex flex-col h-full: fills grid cell height, header stays fixed at top
    // WHY bg-background: consistent with all other dashboard widgets.
    <div className="flex h-full flex-col bg-background">

      {/* ── Section header §0.9 pattern with period selector ─────────────── */}
      <div className="flex h-6 shrink-0 items-center justify-between border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          SECTOR PERFORMANCE
        </span>
        {/* WHY right side shows period buttons + count together:
            period buttons are small (9px) and don't visually compete with the
            sector count. The count disappears behind the buttons intentionally —
            it's secondary info. If both are needed, a future wave can split them. */}
        <div className="flex items-center gap-2">
          {/* Sector count — font-mono for numerical alignment */}
          {data?.sectors && (
            <span className="font-mono text-[10px] text-muted-foreground/60">
              {data.sectors.length} sectors
            </span>
          )}
          {/* Period selector — same pattern as PreMarketMoversWidget */}
          <div className="flex gap-px">
            {(["1D", "1W", "1M"] as const).map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={cn(
                  "px-1.5 text-[9px] font-mono uppercase transition-colors",
                  period === p
                    ? "bg-primary/20 text-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
                aria-pressed={period === p}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Loading state ─────────────────────────────────────────────────── */}
      {isLoading && (
        <div className="flex-1 divide-y divide-border/30">
          {Array.from({ length: 8 }).map((_, i) => (
            // WHY h-[22px]: matches the loaded row height so layout doesn't jump
            <div key={i} className="flex h-[22px] items-center gap-2 px-2">
              <Skeleton className="h-3 w-[120px]" style={{ animationDelay: `${i * 40}ms` }} />
              <Skeleton className="h-1 flex-1" style={{ animationDelay: `${i * 40 + 20}ms` }} />
              <Skeleton className="h-3 w-[50px]" style={{ animationDelay: `${i * 40 + 40}ms` }} />
            </div>
          ))}
        </div>
      )}

      {/* ── Error state ───────────────────────────────────────────────────── */}
      {/* WHY separate from empty: an API/network failure (isError) is fundamentally
          different from "data returned but empty" (!data). Institutional users need
          to know if the feed is down vs. if no data exists yet. Conflating them with
          a single message hides the distinction a trader relies on for triage. */}
      {isError && (
        <div className="flex-1 px-2">
          <InlineEmptyState message="Sector data failed to load — check connection" />
        </div>
      )}

      {/* ── No-data state (data undefined, no error) ──────────────────────── */}
      {!isLoading && !isError && !data && (
        <div className="flex-1 px-2">
          <InlineEmptyState message="Sector data unavailable" />
        </div>
      )}

      {/* ── Sector bar rows ────────────────────────────────────────────────── */}
      {!isLoading && data?.sectors && data.sectors.length === 0 && (
        <div className="flex-1 px-2">
          <InlineEmptyState message="No sector data yet — market data ingestion pending" />
        </div>
      )}

      {!isLoading && data?.sectors && data.sectors.length > 0 && (
        // WHY divide-y divide-border/30: hairline separators between rows
        <div className="flex-1 divide-y divide-border/30 overflow-auto">
          {data.sectors.map((sector) => (
            <SectorRow key={sector.name} sector={sector} />
          ))}
        </div>
      )}

    </div>
  );
}

// ── SectorRow sub-component ───────────────────────────────────────────────────

/**
 * SectorRow — single sector bar with name, fill bar, and % value.
 *
 * WHY separate sub-component: keeps the list map clean and the bar calculation
 * logic testable in isolation.
 */
function SectorRow({ sector }: { sector: HeatmapSector }) {
  const changePct = sector.change_pct;

  // ── Bar width calculation ──────────────────────────────────────────────────
  // WHY max 3% maps to 100% bar width: typical intraday sector moves are ±1–3%.
  // Beyond ±3% is extreme — clipping at 100% prevents the bar from dominating.
  const maxMagnitude = 3;
  const barWidthPct =
    changePct !== null
      ? Math.min(100, (Math.abs(changePct) / maxMagnitude) * 100)
      : 0;

  const isPositive = changePct !== null && changePct >= 0;
  const isNegative = changePct !== null && changePct < 0;

  return (
    // WHY h-[22px]: §0 Terminal Quality Rules mandate 22px data rows
    <div className="flex h-[22px] items-center gap-2 px-2">

      {/* Sector name — fixed width so bars align vertically */}
      <span className="w-[120px] shrink-0 text-[11px] text-foreground">
        {abbreviateSector(sector.name)}
      </span>

      {/* Bar container — fills available space */}
      {/* WHY h-1 bg-muted/30: thin 4px bar on muted track, terminal-dense */}
      <div className="relative h-1 flex-1 bg-muted/30">
        {/* Bar fill — color and width reflect direction/magnitude */}
        {changePct !== null && (
          <div
            className={cn(
              "absolute left-0 top-0 h-full",
              // WHY bg-positive/30 and bg-negative/20: the /30 and /20 opacities
              // give a visible but not aggressive fill — we're in a dark terminal
              // where high-saturation fills compete with text legibility.
              isPositive ? "bg-positive/30" : "bg-negative/20",
            )}
            style={{ width: `${barWidthPct}%` }}
          />
        )}
      </div>

      {/* Percentage value — right-aligned, colored by direction */}
      <span
        className={cn(
          "w-[50px] shrink-0 text-right font-mono text-[11px] tabular-nums",
          isPositive ? "text-positive" : isNegative ? "text-negative" : "text-muted-foreground",
        )}
      >
        {changePct !== null
          ? `${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%`
          : "—"}
      </span>

    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * abbreviateSector — shorten GICS sector names for compact row display
 * WHY: sector names like "Consumer Discretionary" would overflow the 120px label
 */
function abbreviateSector(name: string): string {
  const abbreviations: Record<string, string> = {
    "Information Technology": "Tech",
    "Health Care": "Health Care",
    "Consumer Discretionary": "Cons Disc",
    "Consumer Staples": "Cons Staples",
    "Communication Services": "Comm Svcs",
    Financials: "Financials",
    Industrials: "Industrials",
    Materials: "Materials",
    "Real Estate": "Real Estate",
    Utilities: "Utilities",
    Energy: "Energy",
  };
  return abbreviations[name] ?? name.slice(0, 15);
}
