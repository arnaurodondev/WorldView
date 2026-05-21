/**
 * ConcentrationSectorTeaseStrip — 22px row: HHI label + top-3 sector preview.
 *
 * WHY THIS EXISTS: Bloomberg users expect HHI (Herfindahl-Hirschman Index) at a
 * glance as a concentration risk signal. The previous ConcentrationStrip was 28px
 * and showed only HHI without sector breakdown. This strip merges both signals.
 * WHO USES IT: portfolio overview page, between ExposureCurrencyStrip and PerformanceChartPanel.
 * DATA SOURCE: GET /v1/portfolios/{id}/concentration → ConcentrationResponse
 *   (shared TanStack cache with ConcentrationStrip via identical query key).
 *   bySector comes from parent (derived from holdings in usePortfolioData).
 * DESIGN REFERENCE: PRD-0089 W2 §4.4
 */
"use client";
// WHY "use client": uses TanStack Query (useQuery) which requires React context.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatPercent } from "@/lib/utils";
import type { AllocationSlice } from "@/features/portfolio/lib/kpi";

interface ConcentrationSectorTeaseStripProps {
  portfolioId: string | null;
  /** Top sector slices (sorted by value desc) derived from holdings — passed from parent.
   *  WHY from parent: sectors are already computed in usePortfolioData; no extra fetch needed. */
  bySector: AllocationSlice[];
}

// HHI threshold labels per EU competition law thresholds (widely adopted in
// portfolio analytics — FactSet PORT-CONC, Bloomberg PORT use the same brackets).
function hhiLabel(hhi: number): string {
  if (hhi < 1500) return "low";
  if (hhi < 2500) return "moderate";
  return "high";
}

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
  const top3 = bySector.slice(0, 3);

  return (
    <div className="flex h-[22px] shrink-0 items-center border-b border-border bg-card px-3 gap-3">
      <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground">Concentration</span>
      {conc ? (
        <>
          {/* WHY hhi (not hhi_index): ConcentrationResponse uses `hhi`, not `hhi_index`.
              The API shape comes from ConcentrationStrip which reads data.hhi.
              See types/api.ts ConcentrationResponse interface. */}
          <span className="font-mono text-[11px] tabular-nums text-foreground">
            HHI {conc.hhi.toFixed(0)}
            <span className="ml-1 text-muted-foreground text-[10px]">[{hhiLabel(conc.hhi)}]</span>
          </span>
          {top3.length > 0 && (
            <>
              <span className="text-[10px] text-muted-foreground">·</span>
              <span className="text-[10px] uppercase text-muted-foreground">Sectors:</span>
              {/* Each sector: 4-char abbreviation + pct. pct from AllocationSlice is
                  a 0-1 fraction so formatPercent (×100) scales it correctly. */}
              {top3.map((s) => (
                <span key={s.label} className="font-mono text-[11px] tabular-nums text-foreground">
                  {s.label.substring(0, 4).toUpperCase()} {formatPercent(s.pct)}
                </span>
              ))}
            </>
          )}
        </>
      ) : (
        // Loading or no data — show sector tease alone if available
        top3.length > 0 ? (
          <>
            <span className="text-[10px] uppercase text-muted-foreground">Sectors:</span>
            {top3.map((s) => (
              <span key={s.label} className="font-mono text-[11px] tabular-nums text-foreground">
                {s.label.substring(0, 4).toUpperCase()} {formatPercent(s.pct)}
              </span>
            ))}
          </>
        ) : (
          <span className="text-[11px] font-mono text-muted-foreground">—</span>
        )
      )}
    </div>
  );
}
