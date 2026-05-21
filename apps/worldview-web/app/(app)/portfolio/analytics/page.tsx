/**
 * app/(app)/portfolio/analytics/page.tsx — Analytics sub-page stub.
 *
 * WHY THIS EXISTS: W2 moves the analytics components (HoldingLotsPanel,
 * DayPnLDistribution, RealizedPnLSparkline, DividendYTDStrip, PositionBarHeat,
 * PortfolioAnalyticsSection) off the /portfolio overview to keep the overview
 * at 1-screen density. The "A" hotkey navigates here from /portfolio.
 * WHO USES IT: PMs who want deep P&L analysis, sector heat, lots breakdown.
 * DATA SOURCE: Same data as HoldingsTab — usePortfolioData orchestrator.
 * DESIGN REFERENCE: PRD-0089 W2 §4.21, V16
 */
"use client";
// WHY "use client": usePortfolioData drives TanStack Query hooks (browser-only).

import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import { usePortfolioData } from "@/features/portfolio/hooks/usePortfolioData";
import { HoldingLotsPanel } from "@/components/portfolio/HoldingLotsPanel";
import { DayPnLDistribution } from "@/components/portfolio/DayPnLDistribution";
import { RealizedPnLSparkline } from "@/components/portfolio/RealizedPnLSparkline";
import { DividendYTDStrip } from "@/components/portfolio/DividendYTDStrip";
import { PositionBarHeat } from "@/components/portfolio/PositionBarHeat";
import { PortfolioAnalyticsSection } from "@/components/portfolio/PortfolioAnalyticsSection";

export default function PortfolioAnalyticsPage() {
  const { accessToken } = useAuth();
  // WHY selectedPeriod = "1D": same lock as the main page (T-B-2-07).
  const selectedPeriod = "1D" as const;
  const {
    activePortfolioId,
    enrichedHoldings,
    holdingsQuotes,
    kpi,
  } = usePortfolioData({ accessToken, selectedPeriod });

  return (
    <div className="flex flex-col h-full min-h-0 overflow-y-auto bg-background">
      {/* Page header */}
      <div className="flex h-[36px] shrink-0 items-center border-b border-border bg-card px-3 gap-3 sticky top-0 z-10">
        <Link href="/portfolio" className="font-mono text-[10px] text-muted-foreground hover:text-foreground">← Portfolio</Link>
        <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">Analytics</span>
      </div>

      {/* DayPnLDistribution — 30-day Δ$ sparkline */}
      {activePortfolioId && <DayPnLDistribution portfolioId={activePortfolioId} />}

      {/* HoldingLotsPanel — FIFO tax-lot drilldown */}
      {activePortfolioId && (
        <HoldingLotsPanel
          portfolioId={activePortfolioId}
          holdings={enrichedHoldings}
          quotes={holdingsQuotes}
        />
      )}

      {/* PositionBarHeat — weight × pnl% mini-bars */}
      <PositionBarHeat
        holdings={enrichedHoldings}
        quotes={holdingsQuotes}
        totalValue={kpi.totalValue}
      />

      {/* RealizedPnLSparkline — cumulative realised + ST/LT split */}
      {activePortfolioId && <RealizedPnLSparkline portfolioId={activePortfolioId} />}

      {/* DividendYTDStrip — YTD · forward yield · next ex-date */}
      {activePortfolioId && <DividendYTDStrip portfolioId={activePortfolioId} />}

      {/* PortfolioAnalyticsSection — equity curve + risk metrics */}
      {activePortfolioId && (
        <PortfolioAnalyticsSection portfolioId={activePortfolioId} />
      )}
    </div>
  );
}
