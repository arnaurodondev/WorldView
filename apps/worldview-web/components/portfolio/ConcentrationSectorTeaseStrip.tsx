/**
 * ConcentrationSectorTeaseStrip — 22px row: HHI badge + top-3 sector preview.
 *
 * WHY THIS EXISTS: Bloomberg users expect HHI (Herfindahl-Hirschman Index) at a
 * glance as a concentration risk signal. The previous ConcentrationStrip was 28px
 * and showed only HHI without sector breakdown. This strip merges both signals.
 * WHO USES IT: portfolio overview page, between ExposureCurrencyStrip and PerformanceChartPanel.
 * DATA SOURCE: GET /v1/portfolios/{id}/concentration → ConcentrationResponse
 *   (shared TanStack cache with ConcentrationStrip via identical query key).
 *   bySector comes from parent (derived from holdings in usePortfolioData).
 * DESIGN REFERENCE: PRD-0089 W2 §4.4 / PLAN-0108 W3 T-3-03
 */
"use client";
// WHY "use client": uses TanStack Query (useQuery) which requires React context.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatPercentDirect } from "@/lib/utils";
import type { AllocationSlice } from "@/features/portfolio/lib/kpi";

interface ConcentrationSectorTeaseStripProps {
  portfolioId: string | null;
  /** Top sector slices (sorted by value desc) derived from holdings — passed from parent.
   *  WHY from parent: sectors are already computed in usePortfolioData; no extra fetch needed. */
  bySector: AllocationSlice[];
}

// ── HHI classification ────────────────────────────────────────────────────────
//
// WHY THESE THRESHOLDS (not the old < 1500 boundary):
//   PRD-0108 §T-3-03 mandates the US DOJ / EU merger-guidelines brackets:
//     < 1000  → "low"      (unconcentrated market, diversified portfolio)
//     1000–2500 → "moderate" (moderately concentrated)
//     ≥ 2500  → "high"     (highly concentrated, risk flag)
//   The previous code used < 1500 for "low" which was the older EC threshold;
//   DOJ 2010+ guidelines changed the lower boundary to 1500 for "unconcentrated"
//   but PRD-0108 explicitly uses the stricter 1000 cutoff for portfolio risk UX.

type HhiClass = "low" | "moderate" | "high";

function hhiClass(hhi: number): HhiClass {
  // < 1000 → diversified/low risk (green)
  if (hhi < 1000) return "low";
  // 1000–2499 → moderately concentrated (yellow)
  if (hhi < 2500) return "moderate";
  // ≥ 2500 → highly concentrated (red)
  return "high";
}

/**
 * hhiBadgeClasses — maps HHI class to Tailwind color tokens.
 * WHY inline map (not switch): readability + exhaustiveness at call site.
 * WHY these colors:
 *   - low     → emerald (positive / safe) consistent with gain color tokens
 *   - moderate → amber  (caution) consistent with alert WARNING tokens
 *   - high    → rose    (danger)  consistent with alert CRITICAL tokens
 */
const HHI_BADGE_CLASSES: Record<HhiClass, string> = {
  low: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30",
  moderate: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
  high: "bg-rose-500/15 text-rose-400 border border-rose-500/30",
};

export function ConcentrationSectorTeaseStrip({
  portfolioId,
  bySector,
}: ConcentrationSectorTeaseStripProps) {
  const { accessToken } = useAuth();

  // WHY same query key as ConcentrationStrip ("portfolio-concentration", portfolioId):
  // TanStack Query deduplicates by reference-equal keys. Using the same key means
  // if ConcentrationStrip is already mounted, this component gets the cached result
  // for free without a second network request.
  const { data: conc } = useQuery({
    enabled: Boolean(portfolioId && accessToken),
    queryKey: ["portfolio-concentration", portfolioId],
    queryFn: () => createGateway(accessToken!).getConcentration(portfolioId!),
    staleTime: 5 * 60 * 1000,
  });

  // Top-3 sectors — capped so the strip doesn't overflow on narrow screens.
  // WHY slice(0, 3): bySector is pre-sorted by pct desc in usePortfolioData;
  // first 3 items are the largest exposures — most relevant for a tease strip.
  const top3 = bySector.slice(0, 3);

  return (
    <div className="flex h-[22px] shrink-0 items-center border-b border-border bg-card px-3 gap-3">
      {/* Section label — always visible regardless of data availability */}
      <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground">Concentration</span>

      {conc ? (
        <>
          {/* ── HHI numeric value + colored classification badge ──────────────
               WHY show the raw number alongside the badge:
                 - Number lets analysts cross-check against Bloomberg PORT/FactSet
                 - Badge gives instant visual signal without reading the number
               WHY null guard on hhi: when the catch-all mock returns {} or S9
               responds with an unexpected shape, hhi can be undefined — calling
               .toFixed() on undefined throws TypeError before the table renders. */}
          {conc.hhi != null ? (
            <span className="flex items-center gap-1.5">
              {/* Raw HHI index — monospaced for numerical alignment */}
              <span className="font-mono text-[11px] tabular-nums text-foreground">
                HHI {conc.hhi.toFixed(0)}
              </span>
              {/* Colored classification chip: low (green) / moderate (yellow) / high (red).
                  WHY rounded-[3px] not rounded-full: pill shape would clash with the
                  Bloomberg-style data-dense look; a slight corner radius is softer
                  than square but less playful than full-pill. */}
              <span
                className={`inline-flex items-center rounded-[3px] px-1 py-[1px] text-[9px] font-semibold uppercase leading-none ${HHI_BADGE_CLASSES[hhiClass(conc.hhi)]}`}
                // WHY data-testid: Vitest tests select by this attribute to avoid
                // coupling to presentation text that might be internationalized.
                data-testid="hhi-badge"
              >
                {hhiClass(conc.hhi)}
              </span>
            </span>
          ) : null}

          {/* ── Holdings count ─────────────────────────────────────────────────
               WHY positions_count from ConcentrationResponse (not bySector.length):
                 - bySector collapses holdings by sector; 10 holdings in Tech = 1 entry
                 - positions_count reflects actual number of distinct positions
               WHY "n names": terminal-trader vernacular (Bloomberg uses "names"
               for individual securities in a portfolio). */}
          {conc.positions_count != null && conc.positions_count > 0 ? (
            <>
              <span className="text-[10px] text-muted-foreground">·</span>
              <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                {conc.positions_count}{" "}
                <span className="text-[10px] normal-case">names</span>
              </span>
            </>
          ) : null}

          {/* ── Top-3 sector weights ───────────────────────────────────────────
               WHY formatPercentDirect (not formatPercent):
                 AllocationSlice.pct is produced by kpi.ts as (value / total) * 100,
                 i.e. already in percent scale (0-100). formatPercent multiplies by
                 100 again (expects 0-1 fraction) which would show "2500%" for a 25%
                 allocation. formatPercentDirect renders the value as-is with a sign. */}
          {top3.length > 0 && (
            <>
              <span className="text-[10px] text-muted-foreground">·</span>
              <span className="text-[10px] uppercase text-muted-foreground">Sectors:</span>
              {top3.map((s) => (
                <span key={s.label} className="font-mono text-[11px] tabular-nums text-foreground">
                  {/* WHY 4-char abbreviation: keeps the strip narrow at any viewport width.
                      TECH, HLTH, FINL are Bloomberg-standard sector codes. */}
                  {s.label.substring(0, 4).toUpperCase()}{" "}
                  {formatPercentDirect(s.pct, 1)}
                </span>
              ))}
            </>
          )}
        </>
      ) : (
        // Loading state or no concentration data — show sector tease alone if available
        // WHY still show sectors: bySector is derived locally from holdings so it's
        // often ready before the concentration API call resolves.
        top3.length > 0 ? (
          <>
            <span className="text-[10px] uppercase text-muted-foreground">Sectors:</span>
            {top3.map((s) => (
              <span key={s.label} className="font-mono text-[11px] tabular-nums text-foreground">
                {s.label.substring(0, 4).toUpperCase()} {formatPercentDirect(s.pct, 1)}
              </span>
            ))}
          </>
        ) : (
          // Nothing to show — em dash placeholder so the strip height is maintained.
          // WHY not null: an invisible div still takes h-[22px]; null would collapse it.
          <span className="text-[11px] font-mono text-muted-foreground">—</span>
        )
      )}
    </div>
  );
}
