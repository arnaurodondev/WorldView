/**
 * components/portfolio/ConcentrationStrip.tsx — single-row HHI strip
 * (PLAN-0088 Wave E E-3).
 *
 * Anchored to the Herfindahl-Hirschman Index — the standard institutional
 * concentration measure (FactSet PORT-CONC, Bloomberg PORT, every risk-
 * attribution platform). Single row, three cells:
 *
 *     HHI 1,847 [moderate]  ·  TOP-3 71%  ·  N NAMES
 *
 * INTERPRETATION (industry standard, mirrored on the backend):
 *   HHI < 1,500 → diversified (green badge)
 *   HHI 1,500-2,499 → moderate (amber badge)
 *   HHI ≥ 2,500 → concentrated (red badge)
 *   no positions → empty (muted badge)
 *
 * WHY a strip + colored badge (not a treemap or pie): one number is more
 * actionable than a chart for "is my book too concentrated right now?". A
 * trader either is or isn't; the badge gives the verdict at a glance.
 *
 * DATA: GET /v1/portfolios/{id}/concentration → ConcentrationResponse.
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx → HoldingsTab top strips zone.
 * DESIGN REFERENCE: PLAN-0088 §Wave E task E-3, audit §2 wireframe row R-3.
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

// ── Props ────────────────────────────────────────────────────────────────────

export interface ConcentrationStripProps {
  /** Portfolio UUID. Null/undefined renders the loading skeleton. */
  portfolioId: string | null | undefined;
}

// ── Label-to-color mapping ───────────────────────────────────────────────────

/**
 * Map the backend label to a small inline badge style. We intentionally
 * keep colours muted — the strip is informational, not an alert. The
 * green/amber/red tonal hint comes from the existing `text-positive` /
 * `text-warning` / `text-negative` semantic tokens.
 */
function labelStyles(label: string): { caption: string; chip: string } {
  switch (label) {
    case "diversified":
      return {
        caption: "diversified",
        chip: "bg-positive/10 text-positive border-positive/30",
      };
    case "moderate":
      return {
        caption: "moderate",
        chip: "bg-warning/10 text-warning border-warning/30",
      };
    case "concentrated":
      return {
        caption: "concentrated",
        chip: "bg-negative/10 text-negative border-negative/30",
      };
    default:
      return {
        caption: "no positions",
        chip: "bg-muted/40 text-muted-foreground border-border",
      };
  }
}

// ── Component ────────────────────────────────────────────────────────────────

export function ConcentrationStrip({ portfolioId }: ConcentrationStripProps) {
  const { accessToken } = useAuth();

  // Concentration is portfolio-wide and changes only when the holdings
  // table changes — 5-minute staleTime aligns with the backend
  // Cache-Control hint on the proxy route.
  const { data, isLoading } = useQuery({
    enabled: Boolean(portfolioId && accessToken),
    queryKey: ["portfolio-concentration", portfolioId],
    queryFn: () => createGateway(accessToken!).getConcentration(portfolioId!),
    staleTime: 5 * 60 * 1000,
  });

  if (!portfolioId || isLoading) {
    return (
      <div className="flex h-7 items-stretch divide-x divide-border border-b border-border bg-card">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="flex-1 px-3 flex items-center gap-2">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-3 w-12" />
          </div>
        ))}
      </div>
    );
  }

  const styles = labelStyles(data?.label ?? "empty");

  return (
    <div className="flex h-7 items-stretch divide-x divide-border border-b border-border bg-card font-mono text-[11px]">
      {/* HHI cell: number + label badge. We use Number.toLocaleString so
          users see "1,847" not "1847" — matches the audit wireframe spec. */}
      <div className="flex-1 px-3 flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          HHI
        </span>
        <span className="tabular-nums text-foreground">
          {data?.hhi != null ? data.hhi.toLocaleString("en-US") : "—"}
        </span>
        <span
          className={cn(
            "ml-1 px-1.5 py-px rounded-sm border text-[9px] uppercase tracking-[0.06em]",
            styles.chip,
          )}
        >
          {styles.caption}
        </span>
      </div>

      {/* TOP-3 share — sum of the three largest position weights. The backend
          returns this as a 0-100 percent value so we render it directly with
          a '%' suffix; no fraction-to-percent scaling needed. */}
      <div className="flex-1 px-3 flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          TOP-3 SHARE
        </span>
        <span className="tabular-nums text-foreground">
          {data && data.positions_count > 0
            ? `${data.top_3_share_pct.toFixed(1)}%`
            : "—"}
        </span>
      </div>

      {/* Position count cell. Pluralisation is explicit so a 1-position
          portfolio doesn't read as "1 names". */}
      <div className="flex-1 px-3 flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          POSITIONS
        </span>
        <span className="tabular-nums text-foreground">
          {data?.positions_count ?? 0}{" "}
          {data?.positions_count === 1 ? "name" : "names"}
        </span>
      </div>
    </div>
  );
}
