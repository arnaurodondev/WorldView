/**
 * components/dashboard/TopMovers.tsx — Top gainers / losers widget
 *
 * WHY THIS EXISTS: Traders scan for outliers — stocks with unusual daily moves
 * signal events worth investigating. TopMovers surfaces these instantly without
 * requiring a screener query. Bloomberg's "Market Movers" screen is a direct analogue.
 *
 * WHY HORIZONTAL SCROLL (not table): Tiles fit more visual information per row
 * (ticker + price + %) at a glance. The scroll means we can show 10+ movers
 * without vertical space cost — good for a dashboard widget.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx
 * DATA SOURCE: S9 GET /api/v1/market/top-movers?type=gainers|losers&limit=10
 * DESIGN REFERENCE: PRD-0028 §6.5 Dashboard TopMovers
 */

"use client";
// WHY "use client": uses useQuery, useState for tab toggle.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatPrice, formatPercent, priceChangeClass } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

// ── Types ─────────────────────────────────────────────────────────────────────

type MoverType = "gainers" | "losers";

// ── Component ─────────────────────────────────────────────────────────────────

export function TopMovers() {
  const { accessToken } = useAuth();
  const router = useRouter();
  const [type, setType] = useState<MoverType>("gainers");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["top-movers", type],
    queryFn: () => createGateway(accessToken).getTopMovers(type, 10),
    enabled: !!accessToken,
    // WHY 60s: market movers are a macro view, not a real-time feed
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  return (
    <div>
      {/* Gainers / Losers tab toggle */}
      <div className="mb-3 flex gap-1">
        {(["gainers", "losers"] as MoverType[]).map((t) => (
          <button
            key={t}
            onClick={() => setType(t)}
            // 2px: design system mandates 2px radius everywhere; bare `rounded` = 4px default
            className={`rounded-[2px] px-2 py-0.5 text-xs font-medium capitalize transition-colors ${
              type === t
                ? t === "gainers"
                  ? "bg-positive/20 text-positive"
                  : "bg-negative/20 text-negative"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-20 shrink-0" style={{ animationDelay: `${i * 50}ms` }} />
          ))}
        </div>
      )}

      {/* Error state — WHY muted (not destructive red): "unavailable" is a
         transient backend issue, not a user error. Red alarming text makes the
         dashboard look broken; muted text with a retry prompt is professional. */}
      {isError && (
        <p className="text-sm text-muted-foreground">
          Market movers unavailable — data will appear when market data is ingested.
        </p>
      )}

      {/* Movers row — horizontal scroll */}
      {!isLoading && !isError && data && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {data.movers.map((mover) => (
            <button
              key={mover.instrument_id}
              onClick={() => {
                // WHY prefer entity_id over instrument_id: ADR-F-12 — the instrument detail
                // route is /instruments/[entityId] and the URL must use the stable entity_id.
                // instrument_id can change on exchange migrations; entity_id is permanent.
                // Fallback to instrument_id because the S9 overview endpoint accepts either
                // (confirmed in [entityId]/page.tsx comment: "accepts entity_id or instrument_id").
                const navId = mover.entity_id ?? mover.instrument_id;
                router.push(`/instruments/${navId}`);
              }}
              // WHY hover:bg-surface-3/40: surface-3 is a deeper elevation token than muted,
              // giving TopMover tiles a more pronounced lift on hover. This differentiates
              // them from flat list items and signals "clickable tile" in the dashboard grid.
              // WHY rounded-[2px]: design system mandates 2px radius everywhere; bare `rounded` = 4px default
              className="flex shrink-0 flex-col items-start rounded-[2px] border border-border bg-muted/30 p-2 hover:bg-surface-3/40"
              style={{ minWidth: "4.5rem" }}
            >
              {/* Ticker — large, font-mono */}
              <span className="font-mono text-[11px] font-medium tabular-nums text-foreground">
                {mover.ticker}
              </span>
              {/* Price */}
              <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
                {formatPrice(mover.price)}
              </span>
              {/* % change — colored */}
              <span className={`font-mono text-[11px] font-medium tabular-nums ${priceChangeClass(mover.change_pct)}`}>
                {formatPercent(mover.change_pct / 100)}
              </span>
            </button>
          ))}

          {data.movers.length === 0 && (
            <p className="text-sm text-muted-foreground">No data available</p>
          )}
        </div>
      )}
    </div>
  );
}
