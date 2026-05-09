/**
 * components/dashboard/TopBets.tsx — Prediction market odds widget
 *
 * WHY THIS EXISTS: Prediction markets (Polymarket, Kalshi) aggregate crowd
 * probability estimates for market-moving events. A hedge fund PM watching
 * "What is the probability of a Fed rate cut by June?" gets signal from
 * market-implied odds that's not in analyst reports.
 *
 * WHY PROBABILITY BAR: A percentage alone (42%) requires more cognitive work
 * than a visual bar. The bar gives instant "leaning yes" vs "leaning no"
 * without reading the number. Both are shown for precision.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx
 * DATA SOURCE: S9 GET /api/v1/signals/prediction-markets?limit=5&status=open
 * DESIGN REFERENCE: PRD-0028 §6.5 Dashboard TopBets
 */

"use client";
// WHY "use client": uses useQuery.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { safeExternalUrl } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

// ── Component ─────────────────────────────────────────────────────────────────

export function TopBets() {
  const { accessToken } = useAuth();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["prediction-markets-top"],
    queryFn: () => createGateway(accessToken).getPredictionMarkets({ status: "open", limit: 5 }),
    enabled: !!accessToken,
    // WHY 5min: prediction market odds don't change every second
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
  });

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="space-y-1">
            <Skeleton className="h-4 w-full" style={{ animationDelay: `${i * 50}ms` }} />
            <Skeleton className="h-2 w-full" style={{ animationDelay: `${i * 50}ms` }} />
          </div>
        ))}
      </div>
    );
  }

  // ── Error state ────────────────────────────────────────────────────────────
  // WHY muted (not destructive red): prediction market service offline is not a user error.
  if (isError) {
    return (
      // WHY text-xs (was text-sm): empty/error copy on dense dashboard tiles
      // matches the 12px Bloomberg standard. text-sm (14px) drifts toward
      // marketing-page typography. PLAN-0087 F-DENSITY-001.
      <p className="text-xs text-muted-foreground">
        Prediction markets unavailable — odds will appear once Polymarket data syncs.
      </p>
    );
  }

  const markets = data?.markets ?? [];

  if (markets.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">No open prediction markets</p>
    );
  }

  return (
    <div className="space-y-3">
      {markets.map((market) => {
        const yesPct = Math.round(market.yes_probability * 100);
        const closeDateStr = market.resolution_date
          ? new Date(market.resolution_date).toISOString().slice(0, 10)
          : null;

        return (
          <a
            key={market.market_id}
            href={safeExternalUrl(market.url)}
            target="_blank"
            rel="noopener noreferrer"
            className="block hover:opacity-80"
          >
            {/* Question — truncated to 80 chars */}
            <p className="line-clamp-2 text-xs font-medium text-foreground">
              {market.title.length > 80
                ? market.title.slice(0, 80) + "…"
                : market.title}
            </p>

            {/* Probability bar + stats row */}
            <div className="mt-1">
              {/* Visual bar: yes portion = primary color, no portion = muted */}
              {/* 2px: progress bars are rectangular UI elements — design system 2px policy */}
              <div className="flex h-1.5 overflow-hidden rounded-[2px] bg-muted">
                <div
                  className="h-full bg-primary"
                  style={{ width: `${yesPct}%` }}
                />
              </div>

              {/* Stats: YES%, Volume, Closes */}
              <div className="mt-0.5 flex items-center gap-3 text-[10px] text-muted-foreground">
                <span className="font-mono tabular-nums text-primary">
                  {yesPct}% YES
                </span>
                {market.volume_usd > 0 && (
                  <span className="font-mono tabular-nums">
                    Vol ${formatVolume(market.volume_usd)}
                  </span>
                )}
                {closeDateStr && (
                  <span className="ml-auto font-mono tabular-nums">
                    closes {closeDateStr}
                  </span>
                )}
                {/* WHY rounded-[2px]: design system mandates 2px radius everywhere; bare `rounded` = 4px default */}
                <span className="shrink-0 rounded-[2px] bg-muted px-1 text-[9px] uppercase">
                  {market.source}
                </span>
              </div>
            </div>
          </a>
        );
      })}
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** formatVolume — compact volume display ($1.2M, $500K) */
function formatVolume(usd: number): string {
  if (usd >= 1_000_000) return `${(usd / 1_000_000).toFixed(1)}M`;
  if (usd >= 1_000) return `${(usd / 1_000).toFixed(0)}K`;
  return usd.toFixed(0);
}
