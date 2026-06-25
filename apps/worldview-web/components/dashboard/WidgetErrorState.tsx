/**
 * components/dashboard/WidgetErrorState.tsx — named error state + Retry action
 *
 * WHY THIS EXISTS (Round-4 hardening, 2026-06-10): the Round-4 audit found
 * the dashboard's per-widget error handling had drifted into three tiers:
 *   1. Named EmptyState error + Retry (PredictionMarkets, Earnings, News) ✓
 *   2. Named EmptyState error WITHOUT Retry (AI Signals, Sector Heatmap)
 *   3. Bespoke muted text with no recovery path at all (TopMovers,
 *      EconomicCalendar, RecentAlerts) — or, worst, NO error branch so a
 *      failed fetch fell through to a misleading empty state
 *      (PortfolioSummary rendered "No portfolio yet" on a 500).
 * This component is the single tier going forward: the shared <EmptyState>
 * primitive (§15.12) with `condition="error"`, a named `dashboard.*-error`
 * copy key, and a Retry button wired to the failing query's refetch().
 *
 * WHY refetch() (not invalidateQueries): refetch re-runs THE failing query
 * only and flips its isFetching flag, which we surface as "Retrying…" so the
 * user gets in-flight feedback. Invalidate would also wake every other
 * observer of the key — overkill for a single-panel recovery action.
 *
 * WHY the ghost Button (not a bare <button>): matches the existing Retry
 * affordance shipped in PredictionMarketsWidget / EarningsCalendarWidget /
 * PortfolioNewsWidget (h-6 px-2 text-xs ghost) so all dashboard retry
 * buttons look identical — one recovery idiom across the surface.
 *
 * WHO USES IT: MarketSnapshotWidget, SectorHeatmapWidget, AiSignalsWidget,
 *   PortfolioSummary, WatchlistQuickViewWidget, TopMovers, EconomicCalendar,
 *   RecentAlerts (Round-4). Pre-Round-4 widgets that already had an
 *   error+Retry block keep their existing markup (R19: tests pin it).
 * DESIGN REFERENCE: DESIGN_SYSTEM §15.12 (EmptyState), Round-4 item 1.
 */

"use client";
// WHY "use client": renders an onClick Retry button — needs the client bundle.

import type { LucideIcon } from "lucide-react";

import { EmptyState } from "@/components/primitives/EmptyState";
import { Button } from "@/components/ui/button";

interface WidgetErrorStateProps {
  /** Named key into lib/copy/empty-states.ts (e.g. "dashboard.movers-error"). */
  readonly copyKey: string;
  /** Category icon — same glyph the widget's empty state uses, so error and
   *  empty read as two states of ONE panel, not two different panels. */
  readonly icon?: LucideIcon;
  /** Wired to the failing query's refetch(). */
  readonly onRetry: () => void;
  /** The query's isFetching — disables the button + swaps the label so the
   *  user sees the retry is in flight (Round-4 item 5: in-flight state must
   *  be communicated, never a dead-looking button). */
  readonly retrying?: boolean;
}

export function WidgetErrorState({
  copyKey,
  icon,
  onRetry,
  retrying = false,
}: WidgetErrorStateProps) {
  return (
    // WHY flex-1 + centering wrapper: every caller drops this into a
    // flex-col panel body — centering here (not at each call site) keeps the
    // call sites one-liners and guarantees identical placement everywhere.
    <div className="flex flex-1 items-center justify-center">
      <EmptyState
        condition="error"
        copyKey={copyKey}
        icon={icon}
        action={
          // WHY void: refetch() returns a promise nobody awaits here —
          // TanStack drives the state flags; the void marks that explicit.
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-xs"
            onClick={() => onRetry()}
            disabled={retrying}
          >
            {retrying ? "Retrying…" : "Retry"}
          </Button>
        }
      />
    </div>
  );
}
