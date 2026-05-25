/**
 * ExposureCurrencyStrip — single h-[22px] density row combining exposure + leverage.
 *
 * WHY THIS EXISTS: Bloomberg PORT header shows exposure summary and leverage in
 * one compact row. Previous layout used a 120px ExposureStrip + separate card.
 * This 22px strip delivers the same information at 5× less vertical cost.
 * WHO USES IT: app/(app)/portfolio/page.tsx directly above ConcentrationSectorTeaseStrip.
 * DATA SOURCE: GET /v1/portfolios/{id}/exposure → ExposureResponse (via useExposure hook)
 * DESIGN REFERENCE: PRD-0089 W2 §4.3
 */
"use client";
// WHY "use client": uses TanStack Query hook (useExposure) which requires React context.

import { useExposure } from "@/hooks/useExposure";
import { formatPrice, formatPercent } from "@/lib/utils";

interface ExposureCurrencyStripProps {
  portfolioId: string | null;
}

export function ExposureCurrencyStrip({ portfolioId }: ExposureCurrencyStripProps) {
  // useExposure calls useAuth() internally — no need to pass the token here.
  const { data: exposure, isLoading } = useExposure(portfolioId);

  if (!portfolioId) return null;

  return (
    <div className="flex h-[22px] shrink-0 items-center border-b border-border bg-card px-3 gap-3">
      <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground">Exposure</span>
      {isLoading ? (
        <span className="text-[11px] font-mono text-muted-foreground">—</span>
      ) : exposure ? (
        <>
          {/* INV = invested amount; WHY show absolute + pct: traders need both the
              $ amount to size new trades and the % for allocation math. net_exposure_pct
              is a 0-1 fraction from the API — formatPercent multiplies by 100 internally. */}
          <span className="font-mono text-[11px] tabular-nums text-foreground">
            INV {formatPrice(exposure.invested)}
            <span className="ml-1 text-muted-foreground">({formatPercent(exposure.net_exposure_pct)})</span>
          </span>
          <span className="text-[10px] text-muted-foreground">·</span>
          <span className="font-mono text-[11px] tabular-nums text-foreground">
            CASH {formatPrice(exposure.cash)}
          </span>
          <span className="text-[10px] text-muted-foreground">·</span>
          {/* LEV = leverage ratio; >1.0x indicates margin use (rare for cash accounts) */}
          <span className="font-mono text-[11px] tabular-nums text-foreground">
            LEV {exposure.leverage.toFixed(2)}×
          </span>
          {exposure.prices_stale && (
            <span className="text-[10px] text-muted-foreground">(stale prices)</span>
          )}
        </>
      ) : (
        <span className="text-[11px] font-mono text-muted-foreground">—</span>
      )}
    </div>
  );
}
