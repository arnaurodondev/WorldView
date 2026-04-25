/**
 * components/dashboard/PreMarketMoversWidget.tsx — Top gainers + losers side-by-side
 *
 * WHY THIS EXISTS: Traders scan for outliers every morning — stocks with unusual
 * daily moves signal events worth investigating. Showing gainers and losers
 * simultaneously (two columns) lets the trader assess both sides of the market
 * in a single scan, more efficiently than a tab-toggle approach.
 *
 * WHY TWO COLUMNS (not tabs): Unlike the full TopMovers widget that has pagination
 * and detail, this dashboard widget is read-only context. Two static columns fill
 * the col-span-5 cell and give equal visual weight to both directions.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 3, col-span-5)
 * DATA SOURCE: S9 GET /api/v1/market/top-movers via createGateway().getTopMovers()
 * DESIGN REFERENCE: PRD-0031 §10 Dashboard Wave 7
 */

"use client";
// WHY "use client": uses useQuery and useAuth.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { cn } from "@/lib/utils";
import type { Mover } from "@/types/api";

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * PreMarketMoversWidget — shows top 5 gainers | losers from getTopMovers().
 * Uses a single query and sorts client-side to avoid two round-trips.
 */
export function PreMarketMoversWidget() {
  const { accessToken } = useAuth();

  // WHY fetch gainers and get a combined list: getTopMovers returns one side at
  // a time. For the dashboard we need both — we make two queries (gainers + losers)
  // so each side can be independently cached and refetched.
  const { data: gainersData, isLoading: gainersLoading } = useQuery({
    queryKey: ["dashboard-top-movers-gainers"],
    queryFn: () => createGateway(accessToken).getTopMovers("gainers", 10),
    enabled: !!accessToken,
    // WHY 60_000: top movers is a real-time feed; 1-min refresh is appropriate
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const { data: losersData, isLoading: losersLoading } = useQuery({
    queryKey: ["dashboard-top-movers-losers"],
    queryFn: () => createGateway(accessToken).getTopMovers("losers", 10),
    enabled: !!accessToken,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const isLoading = gainersLoading || losersLoading;

  // Take top 5 from each side
  const gainers = (gainersData?.movers ?? []).slice(0, 5);
  const losers = (losersData?.movers ?? []).slice(0, 5);

  return (
    <div className="flex h-full flex-col bg-card">

      {/* ── Section header §0.9 pattern ──────────────────────────────────── */}
      <div className="flex h-6 shrink-0 items-center border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          TOP MOVERS
        </span>
      </div>

      {/* ── Sub-headers: GAINERS | LOSERS ─────────────────────────────────── */}
      {/* WHY separate sub-header row: makes the two-column split explicit at a
          glance without relying on color alone — supports color-blind traders */}
      <div className="flex shrink-0 border-b border-border/30">
        <div className="flex h-[22px] flex-1 items-center px-2">
          {/* WHY text-positive: column label signals green/up direction */}
          <span className="text-[10px] uppercase tracking-[0.08em] text-positive/70">
            GAINERS
          </span>
        </div>
        {/* WHY border-l: vertical hairline separates the two columns */}
        <div className="flex h-[22px] flex-1 items-center border-l border-border/30 px-2">
          <span className="text-[10px] uppercase tracking-[0.08em] text-negative/70">
            LOSERS
          </span>
        </div>
      </div>

      {/* ── Content area ──────────────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-auto">

        {/* Loading state */}
        {isLoading && (
          <div className="flex flex-1 gap-0">
            <div className="flex-1 divide-y divide-border/30">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex h-[22px] items-center gap-2 px-2">
                  <Skeleton className="h-3 w-[40px]" />
                  <Skeleton className="h-3 w-[40px]" />
                </div>
              ))}
            </div>
            <div className="flex-1 divide-y divide-border/30 border-l border-border/30">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex h-[22px] items-center gap-2 px-2">
                  <Skeleton className="h-3 w-[40px]" />
                  <Skeleton className="h-3 w-[40px]" />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Empty state — shown only when not loading and both lists are empty */}
        {!isLoading && gainers.length === 0 && losers.length === 0 && (
          <div className="flex-1 px-2">
            <InlineEmptyState message="Market mover data loading…" />
          </div>
        )}

        {/* ── Gainers column ─────────────────────────────────────────────── */}
        {!isLoading && (
          <div className="flex-1 divide-y divide-border/30">
            {gainers.map((mover) => (
              <MoverRow key={mover.instrument_id} mover={mover} side="gainer" />
            ))}
            {gainers.length === 0 && (
              <div className="px-2">
                <InlineEmptyState message="No gainers" />
              </div>
            )}
          </div>
        )}

        {/* ── Losers column ─────────────────────────────────────────────── */}
        {!isLoading && (
          <div className="flex-1 divide-y divide-border/30 border-l border-border/30">
            {losers.map((mover) => (
              <MoverRow key={mover.instrument_id} mover={mover} side="loser" />
            ))}
            {losers.length === 0 && (
              <div className="px-2">
                <InlineEmptyState message="No losers" />
              </div>
            )}
          </div>
        )}

      </div>

      {/* ── Footer ────────────────────────────────────────────────────────── */}
      <div className="shrink-0 border-t border-border/30 px-2 py-0.5">
        <span className="text-[10px] text-muted-foreground/60">
          prior session data
        </span>
      </div>

    </div>
  );
}

// ── MoverRow sub-component ────────────────────────────────────────────────────

interface MoverRowProps {
  mover: Mover;
  side: "gainer" | "loser";
}

/**
 * MoverRow — single mover entry: ticker + change%.
 * WHY change% only (not price): compact 22px rows don't have room for both.
 * Change% is the primary signal for scanning movers.
 */
function MoverRow({ mover, side }: MoverRowProps) {
  return (
    // WHY h-[22px]: §0 Terminal Quality Rules mandate 22px data rows
    <div className="flex h-[22px] items-center gap-2 px-2">

      {/* Ticker — fixed width for column alignment */}
      <span className="w-[40px] shrink-0 font-mono text-[11px] tabular-nums text-foreground">
        {mover.ticker}
      </span>

      {/* Change % — colored by direction */}
      <span
        className={cn(
          "font-mono text-[11px] tabular-nums",
          // WHY explicit side check rather than mover.change_pct sign:
          // the API already segregated gainers/losers by type; trust that.
          side === "gainer" ? "text-positive" : "text-negative",
        )}
      >
        {mover.change_pct >= 0 ? "+" : ""}
        {mover.change_pct.toFixed(2)}%
      </span>

    </div>
  );
}
