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
  // PLAN-0053 T-A-1-02 (BP-291): the parent wrapper in PortfolioAnalyticsSection
  // applies ``min-h-[200px] bg-card`` to keep layout stable across data states.
  // Using ``h-full`` here previously stretched the skeleton container to fill
  // the full 200px black panel, leaving ~160px of empty dark space at the top
  // of the page — the user-reported "black widget overlay". Removing h-full
  // lets the skeleton items stack to their natural height (~40px); the parent
  // still reserves 200px for the loaded card.
  if (isLoading) {
    return (
      <div className="flex flex-col gap-2">
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
    // F-P-002 (PLAN-0051 W6): empty/error state must vertically center
    // inside the panel. Previously the message hugged the top so the
    // panel looked half-empty; the data-state version of this panel uses
    // ``h-full flex-col`` so the chrome height is fixed (parent grid
    // ``min-h-[200px]``). Centering the message inside that same min-h
    // keeps the panel feeling intentionally sized rather than collapsed
    // around a single line of copy.
    // WHY items-center justify-center on flex-1 sub-block: header stays
    // pinned at the top (so the user still sees "EXPOSURE"), and only
    // the empty-state copy centers in the remaining space.
    return (
      <div className="flex flex-col gap-2 h-full min-h-[180px]">
        <Header />
        <div className="flex flex-1 items-center justify-center">
          <InlineEmptyState message="Failed to load exposure." />
        </div>
      </div>
    );
  }

  const { invested, cash, gross_exposure_pct, prices_stale } = data;
  const total = invested + cash;

  // Empty portfolio → show empty state, not a 0-width bar.
  if (total <= 0) {
    // F-P-002: same vertical centering as the error branch — the empty
    // panel must visually match the populated panel's height so the row
    // doesn't shrink/jump when transitioning between states.
    return (
      <div className="flex flex-col gap-2 h-full min-h-[180px]">
        <Header />
        <div className="flex flex-1 items-center justify-center">
          <InlineEmptyState message="No positions to measure." />
        </div>
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
          two panels read as one consistent allocation visual language.
          F-P-026 (PLAN-0051 W6): colour-blind-safe encoding.
          Pre-fix the only difference between the Invested and Cash
          segments was the colour (yellow vs muted grey). For users with
          deuteranopia / protanopia / achromatopsia, both segments
          rendered as similar greys and they couldn't tell which was
          which. The fix adds a SOLID fill for "invested" and a
          DIAGONAL-STRIPE fill for "cash" so the two read as different
          shapes regardless of hue. The legend below now also uses the
          same pattern on the swatch + an explicit text label so the
          channel is fully redundant (colour, pattern, label). */}
      <div
        className="h-[6px] w-full rounded-[2px] overflow-hidden bg-border/40 flex"
        role="img"
        aria-label={`Invested ${investedPct.toFixed(1)}% / Cash ${cashPct.toFixed(1)}%`}
      >
        {/* Invested segment — primary yellow at 60% opacity, SOLID fill.
            Solid = "the active position" — visually heaviest. */}
        <div
          className="h-full bg-primary/60"
          style={{ width: `${investedPct}%` }}
        />
        {/* Cash segment — muted base + diagonal-stripe overlay so the
            shape differs from the invested segment for colour-blind users.
            WHY backgroundImage (not a Tailwind class): we want a custom
            stripe pattern at low opacity that stays inside the segment's
            tonal range (no new colour tokens). repeating-linear-gradient
            is the standard CSS pattern for this. */}
        <div
          className="h-full bg-muted-foreground/30"
          style={{
            width: `${cashPct}%`,
            backgroundImage:
              "repeating-linear-gradient(45deg, transparent 0px, transparent 2px, rgba(255,255,255,0.10) 2px, rgba(255,255,255,0.10) 3px)",
          }}
        />
      </div>

      {/* Legend / values row — small numerics under each segment.
          WHY tabular-nums on the values: the dollar amounts often differ in
          digit count (e.g. $1,234 vs $123,456) — without tabular-nums the
          right edge would jitter as the prices refresh. */}
      {/* F-P-026: legend swatches mirror the bar's encoding — solid for
          invested, diagonal-stripe for cash. Combined with the explicit
          text labels ("Invested" / "Cash") this gives users THREE
          redundant cues: colour, pattern, label. */}
      <div className="flex items-center justify-between text-[10px]">
        <span className="text-muted-foreground inline-flex items-center">
          <span
            className="inline-block w-2 h-2 mr-1 align-middle bg-primary/60 rounded-[1px]"
            aria-hidden="true"
          />
          <span className="font-sans">Invested</span>
          <span className="ml-1 font-mono tabular-nums">
            {formatPrice(invested)}
          </span>
        </span>
        <span className="text-muted-foreground inline-flex items-center">
          <span
            className="inline-block w-2 h-2 mr-1 align-middle bg-muted-foreground/30 rounded-[1px]"
            aria-hidden="true"
            style={{
              backgroundImage:
                "repeating-linear-gradient(45deg, transparent 0px, transparent 2px, rgba(255,255,255,0.10) 2px, rgba(255,255,255,0.10) 3px)",
            }}
          />
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
