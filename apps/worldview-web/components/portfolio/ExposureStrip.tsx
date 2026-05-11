/**
 * components/portfolio/ExposureStrip.tsx — single-row exposure strip
 * (PLAN-0088 Wave E E-3; replaces ExposureBreakdown panel).
 *
 * The previous ExposureBreakdown panel was ~200 px tall — one bar, one
 * number. The audit (§1 row 8) flagged it as "C": useful, but enormously
 * over-presented. This strip compresses the same data into a 28 px row:
 *
 *     INV $33.9k (98%) · CASH $0 · LEV 1.0x · BETA-ADJ —
 *
 * INV / CASH / LEV come from GET /v1/portfolios/{id}/exposure (the same
 * endpoint as before). BETA-ADJ is a portfolio-weighted beta — the spec
 * for E-3 asks for a backend `compute_beta_exposure.py` use case, but the
 * implementation requires per-instrument betas which live in market-data
 * (S3) — a backend rollup would need a new HTTP port + adapter. For now
 * we render the field as an em-dash so the UI shape is locked; the value
 * lights up the moment a future backend wave adds it. The cleaner archi-
 * tectural option (S9 composition reading S3 fundamentals.beta + S1
 * holdings.weight) is documented in the wave plan for follow-up.
 *
 * COMPETITOR REFERENCE: FactSet PORT-EXP single-row exposure summary.
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx → HoldingsTab.
 * DESIGN REFERENCE: PLAN-0088 §Wave E task E-3, audit §2 wireframe row R-12.
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { formatPrice } from "@/lib/utils";

// ── Props ────────────────────────────────────────────────────────────────────

export interface ExposureStripProps {
  /** Portfolio UUID. Null/undefined renders the loading skeleton. */
  portfolioId: string | null | undefined;
}

// ── Component ────────────────────────────────────────────────────────────────

/**
 * Compact-USD formatter — "$33.9k" / "$1.2M" / "$932". Matches the wireframe.
 * WHY a tiny inline helper (not a shared util): the pattern is used here
 * and in ConcentrationStrip ONLY; pulling it into lib/utils would invite
 * over-use.
 */
function compactUsd(value: number): string {
  // Threshold pattern matches the existing OverviewSidebarMetrics + KPI
  // strip. Keep one decimal so a $33,887 reads "$33.9k" not "$34k" (the
  // extra precision is meaningful at portfolio scale).
  if (Math.abs(value) >= 1_000_000) {
    return `$${(value / 1_000_000).toFixed(1)}M`;
  }
  if (Math.abs(value) >= 1_000) {
    return `$${(value / 1_000).toFixed(1)}k`;
  }
  return formatPrice(value);
}

export function ExposureStrip({ portfolioId }: ExposureStripProps) {
  const { accessToken } = useAuth();

  const { data, isLoading } = useQuery({
    enabled: Boolean(portfolioId && accessToken),
    queryKey: ["portfolio-exposure-strip", portfolioId],
    queryFn: () => createGateway(accessToken!).getExposure(portfolioId!),
    staleTime: 30_000,
  });

  if (!portfolioId || isLoading) {
    return (
      <div className="flex h-7 items-stretch divide-x divide-border border-b border-border bg-card">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex-1 px-3 flex items-center gap-2">
            <Skeleton className="h-3 w-12" />
            <Skeleton className="h-3 w-16" />
          </div>
        ))}
      </div>
    );
  }

  // gross_exposure_pct is a fraction in [0, 1+] per the backend schema —
  // multiply by 100 for the percent display so we don't double-scale.
  const grossPct = (data?.gross_exposure_pct ?? 0) * 100;

  return (
    <div className="flex h-7 items-stretch divide-x divide-border border-b border-border bg-card font-mono text-[11px]">
      {/* INVESTED + percent. WHY no parens around the percent: matches the
          KPI-strip convention upstream (e.g. PortfolioKPIStrip Day P&L). */}
      <div className="flex-1 px-3 flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          INV
        </span>
        <span className="tabular-nums text-foreground">
          {compactUsd(data?.invested ?? 0)}
        </span>
        <span className="text-[10px] text-muted-foreground tabular-nums">
          {grossPct.toFixed(1)}%
        </span>
      </div>

      {/* CASH cell — value is always $0 in v1 (see audit §C-1). Field stays
          here so it lights up when broker cash sweeps land. */}
      <div className="flex-1 px-3 flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          CASH
        </span>
        <span className="tabular-nums text-foreground">
          {compactUsd(data?.cash ?? 0)}
        </span>
      </div>

      {/* LEVERAGE multiplier — 1.0x = no leverage. Decimal precision is
          intentional: 1.0x reads as 1.0x not 1, and 1.27x is meaningful
          info for a margin user. */}
      <div className="flex-1 px-3 flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          LEV
        </span>
        <span className="tabular-nums text-foreground">
          {(data?.leverage ?? 1).toFixed(2)}x
        </span>
      </div>

      {/* BETA-ADJUSTED exposure — placeholder until the backend ships
          ``compute_beta_exposure.py``. Em-dash with label keeps the field
          present so the UI doesn't reflow when the value lands. */}
      <div className="flex-1 px-3 flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          BETA-ADJ
        </span>
        <span className="tabular-nums text-muted-foreground">—</span>
      </div>
    </div>
  );
}
