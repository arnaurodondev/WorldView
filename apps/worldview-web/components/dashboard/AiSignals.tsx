/**
 * components/dashboard/AiSignals.tsx — AI-derived price impact signal widget
 *
 * WHY THIS EXISTS: S6 (NLP Pipeline) produces price-impact signal scores per article
 * (PRD-0020). This widget surfaces the latest signals: which entities have positive
 * or negative AI-assessed momentum based on news flow.
 *
 * WHY STUB EMPTY STATE: The signal endpoint currently returns an empty array
 * (stub — PRD-0026 completes the full signal pipeline). The empty state tells
 * the user what this widget will show, rather than silently showing nothing.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx
 * DATA SOURCE: S9 GET /api/v1/signals/ai?limit=8 → S6 signal scores
 * DESIGN REFERENCE: PRD-0028 §6.5 Dashboard AiSignals
 */

"use client";
// WHY "use client": uses useQuery.

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { priceChangeClass } from "@/lib/utils";

// ── Component ─────────────────────────────────────────────────────────────────

export function AiSignals() {
  const { accessToken } = useAuth();
  const router = useRouter();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["ai-signals"],
    queryFn: () => createGateway(accessToken).getAiSignals(8),
    enabled: !!accessToken,
    // WHY 5min: signal scores are computed from news batches, not real-time
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
  });

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex gap-2">
            <Skeleton className="h-5 w-12" style={{ animationDelay: `${i * 50}ms` }} />
            <Skeleton className="h-5 flex-1" style={{ animationDelay: `${i * 50}ms` }} />
            <Skeleton className="h-5 w-8" style={{ animationDelay: `${i * 50}ms` }} />
          </div>
        ))}
      </div>
    );
  }

  // ── Error state ────────────────────────────────────────────────────────────
  // WHY muted (not destructive red): NLP pipeline offline is not a user error.
  if (isError) {
    return (
      // WHY text-xs: dashboard tile empty/error copy → 12px (PLAN-0087 F-DENSITY-001).
      <p className="text-xs text-muted-foreground">
        AI signals unavailable — scores will appear once the NLP pipeline processes articles.
      </p>
    );
  }

  const signals = data?.signals ?? [];

  // ── Empty state — shown when S6 stub returns [] ────────────────────────────
  // WHY informative empty state: "no data" is ambiguous. Telling users
  // "this will show AI signals" sets expectations correctly.
  if (signals.length === 0) {
    return (
      <div className="flex h-16 items-center justify-center">
        <p className="text-center text-xs text-muted-foreground">
          Signal data coming soon.
          <br />
          <span className="text-[10px]">Powered by S6 NLP pipeline (PRD-0020)</span>
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {signals.map((signal) => {
        // Map POSITIVE/NEGATIVE/NEUTRAL to pct-equivalent for color class
        const pctEquiv = signal.label === "POSITIVE" ? 1 : signal.label === "NEGATIVE" ? -1 : 0;

        return (
          <button
            key={signal.signal_id}
            // PRD-0089 F2 step 11 (§6.6): ticker-first URL. Signals carry a
            // ticker for instrument-level signals (POSITIVE/NEGATIVE on an
            // equity); macro / sector signals may not. Falls back to UUID.
            onClick={() =>
              signal.entity_id &&
              router.push(`/instruments/${signal.ticker || signal.entity_id}`)
            }
            // WHY rounded-[2px]: design system mandates 2px radius everywhere; bare `rounded` = 4px default
            className="flex w-full items-center gap-2 rounded-[2px] px-1 py-0.5 hover:bg-muted/30"
          >
            {/* Ticker — monospace */}
            <span className="w-12 shrink-0 font-mono text-xs font-medium tabular-nums text-foreground">
              {signal.ticker ?? "—"}
            </span>

            {/* Score bar */}
            <div className="flex-1">
              {/* 2px: progress bars are rectangular UI elements, not circles — design system 2px policy */}
              <div className="h-1.5 w-full rounded-[2px] bg-muted">
                <div
                  className={`h-1.5 rounded-[2px] ${
                    signal.label === "POSITIVE"
                      ? "bg-positive"
                      : signal.label === "NEGATIVE"
                        ? "bg-negative"
                        : "bg-muted-foreground"
                  }`}
                  style={{ width: `${signal.score * 100}%` }}
                />
              </div>
            </div>

            {/* Label */}
            <span className={`shrink-0 text-[10px] font-medium ${priceChangeClass(pctEquiv)}`}>
              {signal.label.slice(0, 3)}
            </span>

            {/* Score */}
            <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
              {signal.score.toFixed(2)}
            </span>
          </button>
        );
      })}
    </div>
  );
}
