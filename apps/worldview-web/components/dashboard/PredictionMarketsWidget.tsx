/**
 * components/dashboard/PredictionMarketsWidget.tsx — Top prediction market odds
 *
 * WHY THIS EXISTS: Prediction markets (Polymarket) are increasingly used by
 * institutional traders as real-time probability signals for macro and
 * geopolitical events. Showing the top 3 open markets with their yes-probability
 * gives traders a quick pulse on market sentiment beyond price action.
 *
 * WHY TOP 3 ONLY (not all): The col-span-3 cell is compact. Three rows at
 * h-[22px] with a "View all" footer link is the right density — enough signal
 * to catch the user's attention without overwhelming the morning brief.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 3, col-span-3)
 * DATA SOURCE: S9 GET /v1/signals/prediction-markets via createGateway().getPredictionMarkets()
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

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * PredictionMarketsWidget — top 3 open prediction markets with yes-probability.
 */
export function PredictionMarketsWidget() {
  const { accessToken } = useAuth();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["dashboard-prediction-markets"],
    queryFn: () =>
      createGateway(accessToken).getPredictionMarkets({ status: "open", limit: 5 }),
    enabled: !!accessToken,
    // WHY 60_000: prediction market prices update continuously; 1-min refresh
    // keeps the probabilities reasonably fresh for dashboard context.
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  // Show only the first 3 markets on the dashboard
  const topMarkets = (data?.markets ?? []).slice(0, 3);
  const totalMarkets = data?.total ?? 0;

  return (
    <div className="flex h-full flex-col bg-card">

      {/* ── Section header §0.9 pattern ──────────────────────────────────── */}
      <div className="flex h-6 shrink-0 items-center border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          PREDICTION MARKETS
        </span>
      </div>

      {/* ── Loading state ─────────────────────────────────────────────────── */}
      {isLoading && (
        <div className="flex-1 divide-y divide-border/30">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="flex h-[22px] items-center gap-2 px-2">
              <Skeleton className="h-3 flex-1" style={{ animationDelay: `${i * 40}ms` }} />
              <Skeleton className="h-3 w-[40px]" />
            </div>
          ))}
        </div>
      )}

      {/* ── Error / empty state ────────────────────────────────────────────── */}
      {(isError || (!isLoading && topMarkets.length === 0)) && (
        <div className="flex-1 px-2">
          <InlineEmptyState message="Prediction market data loading…" />
        </div>
      )}

      {/* ── Market rows ───────────────────────────────────────────────────── */}
      {!isLoading && topMarkets.length > 0 && (
        <div className="flex-1 divide-y divide-border/30 overflow-auto">
          {topMarkets.map((market) => {
            const prob = market.yes_probability;

            // WHY color threshold: >0.6 positive signal (likely YES), <0.4 negative
            // (unlikely YES), otherwise neutral — matches trader convention on
            // Polymarket where >60% is considered a strong signal.
            const probColor =
              prob > 0.6
                ? "text-positive"
                : prob < 0.4
                  ? "text-negative"
                  : "text-muted-foreground";

            return (
              // WHY h-[22px]: §0 Terminal Quality Rules mandate 22px data rows
              <div
                key={market.market_id}
                className="flex h-[22px] items-center gap-1.5 px-2"
              >
                {/* Market title — truncated to fit single row */}
                <span
                  className="flex-1 truncate text-[11px] text-foreground"
                  title={market.title}
                >
                  {market.title}
                </span>

                {/* Yes probability — right-aligned, colored by magnitude */}
                {/* WHY font-mono tabular-nums: probability is a financial number */}
                <span
                  className={cn(
                    "shrink-0 font-mono text-[11px] tabular-nums",
                    probColor,
                  )}
                >
                  {(prob * 100).toFixed(0)}%
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Footer: View all link if more markets exist ───────────────────── */}
      {!isLoading && totalMarkets > 3 && (
        <div className="shrink-0 border-t border-border/30 px-2 py-0.5">
          {/* WHY text-primary: the "View all" link is the only interactive element —
              primary color distinguishes it from the muted footer note pattern */}
          <span className="font-mono text-[10px] tabular-nums text-primary/70">
            → View all ({totalMarkets})
          </span>
        </div>
      )}

    </div>
  );
}
