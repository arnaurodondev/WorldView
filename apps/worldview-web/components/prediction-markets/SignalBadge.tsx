/**
 * components/prediction-markets/SignalBadge.tsx — honest market signal badge
 * (PLAN-0056 Wave E2, task 4).
 *
 * WHY THIS EXISTS: a trader scanning the list/detail needs a one-glance cue for
 * markets in a notable state. But a signal is only useful if it is TRUE — a
 * fabricated "moving" badge on a flat market is worse than no badge. So every
 * variant here is derived STRICTLY from data we actually hold:
 *
 *   • "resolved" / "closed"  ← driven by PredictionMarket.status. The list
 *     payload already carries status ("open"|"closed"|"resolved"), so this
 *     badge is exact on both list rows and the detail Sheet. It tells the
 *     trader the market is settled/closed and the odds are final.
 *
 *   • "moving"  ← DERIVED, only where we cheaply have history: the detail Sheet
 *     computes the YES-probability change (Δpp) across the loaded interval
 *     series and passes it in. If |Δ| ≥ a threshold we show a directional
 *     "MOVING ▲/▼ Npp" badge. This is a real, measured move from real bars —
 *     NOT a guess. List rows do NOT fetch per-row history, so they never show
 *     this badge (we refuse to invent a signal we can't substantiate there).
 *
 * There is deliberately NO "new" badge: the list payload has no reliable
 * created_at (only updated_at, which churns on every re-snapshot), so a "new"
 * flag would be dishonest. Documented in docs/apps/worldview-web.md.
 *
 * Colours come from the Midnight Pro tokens (bg-positive/bg-negative/bg-muted)
 * via Tailwind classes — this is HTML, not chart SVG, so CSS vars paint fine.
 */

import { cn } from "@/lib/utils";
import { TrendingUp, TrendingDown, CheckCircle2, Lock } from "lucide-react";
import type { PredictionMarket } from "@/types/api";

/**
 * Derive the status-driven signal from a market. Returns null for plain open
 * markets (no badge = no noise). Exported so tests + callers share the mapping.
 */
export function statusSignal(
  status: PredictionMarket["status"],
): "resolved" | "closed" | null {
  if (status === "resolved") return "resolved";
  if (status === "closed") return "closed";
  return null;
}

/** Threshold (percentage points) above which a YES-prob move is "material". */
export const MOVING_THRESHOLD_PP = 8;

interface SignalBadgeProps {
  /** Market status — drives the resolved/closed badge. */
  status: PredictionMarket["status"];
  /**
   * Optional measured YES-probability change in percentage points over the
   * loaded window. When |deltaPp| ≥ MOVING_THRESHOLD_PP a "moving" badge is
   * shown. Omit (undefined) on surfaces without history (list rows).
   */
  deltaPp?: number | null;
  className?: string;
}

/**
 * SignalBadge — renders the highest-priority honest signal, or nothing.
 *
 * Priority: resolved/closed (terminal state) outranks a live move, because a
 * settled market's move is history, not an actionable signal.
 */
export function SignalBadge({ status, deltaPp, className }: SignalBadgeProps) {
  const settled = statusSignal(status);

  if (settled === "resolved") {
    return (
      <span
        data-testid="signal-badge"
        data-signal="resolved"
        className={cn(
          "inline-flex items-center gap-1 rounded-[2px] bg-positive/15 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-positive",
          className,
        )}
      >
        <CheckCircle2 className="h-2.5 w-2.5" strokeWidth={2} aria-hidden />
        Resolved
      </span>
    );
  }

  if (settled === "closed") {
    return (
      <span
        data-testid="signal-badge"
        data-signal="closed"
        className={cn(
          "inline-flex items-center gap-1 rounded-[2px] bg-muted px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-muted-foreground",
          className,
        )}
      >
        <Lock className="h-2.5 w-2.5" strokeWidth={2} aria-hidden />
        Closed
      </span>
    );
  }

  // Live market: show a MOVING badge only when the measured move clears the bar.
  if (deltaPp != null && Math.abs(deltaPp) >= MOVING_THRESHOLD_PP) {
    const up = deltaPp >= 0;
    const Icon = up ? TrendingUp : TrendingDown;
    return (
      <span
        data-testid="signal-badge"
        data-signal="moving"
        className={cn(
          "inline-flex items-center gap-1 rounded-[2px] px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider",
          up ? "bg-positive/15 text-positive" : "bg-negative/15 text-negative",
          className,
        )}
      >
        <Icon className="h-2.5 w-2.5" strokeWidth={2} aria-hidden />
        {up ? "+" : ""}
        {Math.round(deltaPp)}pp
      </span>
    );
  }

  // Plain open market with no material move → no badge.
  return null;
}
