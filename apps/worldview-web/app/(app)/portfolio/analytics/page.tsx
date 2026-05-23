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
 *
 * WIRING: The context-menu "View Tax Lots" action (lib/command-actions.ts
 * id="view.tax-lots") navigates here with ?ticker=<TICKER>. The analytics page
 * reads that param and passes the matching instrument_id to HoldingLotsPanel
 * so the right-clicked holding is immediately selected in the dropdown.
 */
"use client";
// WHY "use client": usePortfolioData drives TanStack Query hooks (browser-only).
// useSearchParams is also a client-side hook (cannot be used in RSC).

import Link from "next/link";
import { useMemo } from "react";
import { useSearchParams } from "next/navigation";
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

  // WHY useSearchParams: the "View Tax Lots" context-menu action (command-actions.ts
  // id="view.tax-lots") navigates here with ?ticker=<TICKER> so the HoldingLotsPanel
  // pre-selects the right-clicked holding rather than defaulting to the largest
  // position. We resolve the ticker → instrument_id here because HoldingLotsPanel
  // uses instrument_id (not ticker) as its selection key.
  const searchParams = useSearchParams();
  const defaultInstrumentId = useMemo(() => {
    const ticker = searchParams?.get("ticker");
    if (!ticker) return null;
    // Find the holding whose ticker matches the URL param. Ticker matching is
    // case-insensitive to be safe against URL encoding differences.
    const matched = enrichedHoldings.find(
      (h) => h.ticker?.toLowerCase() === ticker.toLowerCase(),
    );
    return matched?.instrument_id ?? null;
  }, [searchParams, enrichedHoldings]);

  return (
    <div className="flex flex-col h-full min-h-0 overflow-y-auto bg-background">
      {/* Page header */}
      <div className="flex h-[36px] shrink-0 items-center border-b border-border bg-card px-3 gap-3 sticky top-0 z-10">
        <Link href="/portfolio" className="font-mono text-[10px] text-muted-foreground hover:text-foreground">← Portfolio</Link>
        <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">Analytics</span>
      </div>

      {/* DayPnLDistribution — 30-day Δ$ sparkline */}
      {activePortfolioId && <DayPnLDistribution portfolioId={activePortfolioId} />}

      {/* HoldingLotsPanel — FIFO tax-lot drilldown.
          WHY defaultInstrumentId: when the user arrives from the context-menu
          "View Tax Lots" action, defaultInstrumentId is already resolved to the
          right-clicked holding's instrument_id. When navigating directly (e.g.
          "A" hotkey), defaultInstrumentId is null and HoldingLotsPanel falls back
          to the largest-position heuristic — same behaviour as before this change. */}
      {activePortfolioId && (
        <HoldingLotsPanel
          portfolioId={activePortfolioId}
          holdings={enrichedHoldings}
          quotes={holdingsQuotes}
          defaultInstrumentId={defaultInstrumentId}
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
