/**
 * components/portfolio/ExposureBreakdown.tsx — Invested vs cash bar (PLAN-0046 W5 / T-46-5-05)
 *
 * WHY THIS EXISTS: A single horizontal stacked bar tells a portfolio manager
 * at a glance "what fraction of my book is at risk vs sitting in cash?".
 * Bloomberg PORT shows this as the "Asset Mix" panel; we render it as a
 * compact horizontal bar plus a headline gross-exposure %.
 *
 * WHY HORIZONTAL STACKED BAR (not pie / not two side-by-side bars):
 *   - Pies are angle-estimation traps (humans read them poorly).
 *   - Side-by-side bars hide the "they always sum to 100%" relationship.
 *   - Stacked horizontal makes the proportion immediately legible at the
 *     pixel level — same UX pattern as the SectorAllocationPanel weight bars.
 *
 * WHY V1 = INVESTED + CASH ONLY (no shorts): the plan defers shorts +
 * leverage to a future wave. ``net_exposure_pct`` is rendered separately
 * in the headline so the contract is forward-compatible.
 *
 * DATA SOURCE: S9 GET /v1/portfolios/{id}/exposure → S1 GetExposureUseCase.
 * S1 fetches current prices from S3 over REST (R9-compliant).
 *
 * EMPTY STATE: An empty portfolio returns invested === 0 → we render an
 * inline empty state rather than a zero-width bar (which would be confusing).
 */

"use client";
// WHY "use client": useQuery for fetching exposure; reactive re-render when
// the active portfolio id changes upstream.

import { useQuery } from "@tanstack/react-query";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatPrice, formatPercent } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface ExposureBreakdownProps {
  /** Portfolio UUID (or ROOT id for the aggregate view). */
  portfolioId: string;
}

// ── ExposureBreakdown ─────────────────────────────────────────────────────────

export function ExposureBreakdown({ portfolioId }: ExposureBreakdownProps) {
  const { accessToken } = useAuth();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["exposure", portfolioId],
    queryFn: () => createGateway(accessToken).getExposure(portfolioId),
    enabled: !!accessToken && !!portfolioId,
    // 30s — exposure depends on current prices which the dashboard already
    // refreshes every 15s. This panel doesn't need to be more aggressive.
    staleTime: 30_000,
  });

  // ── Loading skeleton ────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex flex-col gap-2 h-full">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-6 w-24" />
        <Skeleton className="h-3 w-full" />
        <div className="flex justify-between">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-3 w-16" />
        </div>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="flex flex-col gap-2 h-full">
        <Header />
        <InlineEmptyState message="Failed to load exposure." />
      </div>
    );
  }

  const { invested, cash, gross_exposure_pct, prices_stale } = data;
  const total = invested + cash;

  // Empty portfolio → show empty state, not a 0-width bar.
  if (total <= 0) {
    return (
      <div className="flex flex-col gap-2 h-full">
        <Header />
        <InlineEmptyState message="No positions to measure." />
      </div>
    );
  }

  // Compute pixel widths as percentages so the bar always sums to 100%.
  // WHY recompute here (instead of trusting gross_exposure_pct): the bar
  // shows invested vs cash as a *visual* proportion. ``gross_exposure_pct``
  // already represents that, but computing locally guards against any
  // future server-side change (e.g. adding shorts) breaking the visual.
  const investedPct = (invested / total) * 100;
  const cashPct = (cash / total) * 100;

  return (
    // WHY gap-1.5 (was gap-2): tighter vertical rhythm. The header / badge /
    // headline / bar / legend stack now reads as a single dense block of
    // related data rather than a list of loosely-spaced items. Matches the
    // KPI strip's gap-0.5 / py-1.5 density.
    <div className="flex flex-col gap-1.5 h-full">
      <Header />

      {/* F-016 (QA 2026-04-28): when one or more holdings fell back to
          cost basis (because live quotes were missing), surface a yellow
          "Prices stale" badge above the headline number. WHY a separate
          row (not inline next to "gross"): keeps the headline visual
          rhythm stable so users always read the percentage in the same
          place. */}
      {prices_stale && (
        <div
          role="status"
          aria-label="Some current prices are unavailable; showing cost basis"
          className="inline-flex items-center gap-1 self-start rounded-[2px] border border-warning/60 bg-warning/10 px-1.5 py-px text-[10px] uppercase tracking-[0.06em] text-warning font-mono"
        >
          {/* WHY uppercase + small caps: matches every other status pill in
              the app (badges in alerts, freshness dots in fundamentals). */}
          Prices stale
        </div>
      )}

      {/* Headline number — large, monospace, tabular-nums for stable layout.
          WHY text-[18px] (was 20px): one notch tighter brings the headline
          in line with the equity-curve cell's KPI numbers and keeps the
          panel content from feeling bottom-heavy. */}
      <div className="font-mono tabular-nums text-[18px] leading-none text-foreground">
        {formatPercent(gross_exposure_pct)}
        <span className="ml-1.5 text-[10px] uppercase tracking-[0.06em] text-muted-foreground align-middle">
          gross
        </span>
      </div>

      {/* Horizontal stacked bar — same visual idiom as SectorAllocationPanel.
          WHY h-[6px] (was 8px): matches the BarChart row bars exactly so the
          two panels read as one consistent allocation visual language. */}
      <div
        className="h-[6px] w-full rounded-[2px] overflow-hidden bg-border/40 flex"
        role="img"
        aria-label={`Invested ${investedPct.toFixed(1)}% / Cash ${cashPct.toFixed(1)}%`}
      >
        {/* Invested segment — primary yellow at 60% opacity */}
        <div
          className="h-full bg-primary/60"
          style={{ width: `${investedPct}%` }}
        />
        {/* Cash segment — muted (lower visual weight; cash is the "rest") */}
        <div
          className="h-full bg-muted-foreground/30"
          style={{ width: `${cashPct}%` }}
        />
      </div>

      {/* Legend / values row — small numerics under each segment.
          WHY tabular-nums on the values: the dollar amounts often differ in
          digit count (e.g. $1,234 vs $123,456) — without tabular-nums the
          right edge would jitter as the prices refresh. */}
      <div className="flex items-center justify-between text-[10px]">
        <span className="text-muted-foreground inline-flex items-center">
          <span className="inline-block w-2 h-2 mr-1 align-middle bg-primary/60 rounded-[1px]" />
          <span className="font-sans">Invested</span>
          <span className="ml-1 font-mono tabular-nums">
            {formatPrice(invested)}
          </span>
        </span>
        <span className="text-muted-foreground inline-flex items-center">
          <span className="inline-block w-2 h-2 mr-1 align-middle bg-muted-foreground/30 rounded-[1px]" />
          <span className="font-sans">Cash</span>
          <span className="ml-1 font-mono tabular-nums">
            {formatPrice(cash)}
          </span>
        </span>
      </div>
    </div>
  );
}

// ── Header ───────────────────────────────────────────────────────────────────

/**
 * Section header — extracted so all render branches share the same
 * "EXPOSURE" label rather than duplicating it across loading / error /
 * empty / data states.
 */
function Header() {
  return (
    <h3 className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-sans">
      Exposure
    </h3>
  );
}
