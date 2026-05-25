/**
 * app/(app)/portfolio/analytics/page.tsx — Analytics tab page.
 *
 * WHY THIS PAGE EXISTS: Wave G of PRD-0089 replaces the original analytics
 * stub (which composed existing overview components) with a dedicated analytics
 * experience: TWR vs benchmark, drawdown chart, 11-tile risk sidebar,
 * attribution by holding/sector/asset-class, and period returns table.
 *
 * WHY portfolioId comes from useActivePortfolio (not URL params):
 * The portfolio section uses a context-based selection model (ActivePortfolioContext).
 * The TopBar PortfolioSwitcher writes to that context; reading from the same
 * context here means switching portfolios in the TopBar updates the analytics
 * view immediately — same as the portfolio overview page (F-DS-001, QA 2026-05-21).
 *
 * WHY this is a "use client" page: useActivePortfolio drives TanStack Query hooks
 * (browser-only). useActivePortfolio is a client-side context hook that cannot
 * run in a React Server Component.
 *
 * PRESERVED FROM ORIGINAL:
 *   - Back link ("← Portfolio")
 *   - Page header with "Analytics" label
 *   - activePortfolioId source pattern (same context read)
 *
 * REMOVED FROM ORIGINAL (moved to overview page):
 *   - DayPnLDistribution, HoldingLotsPanel, PositionBarHeat, RealizedPnLSparkline,
 *     DividendYTDStrip, PortfolioAnalyticsSection — these belonged on the overview.
 *     The analytics tab now focuses on performance analytics per design spec §4.3.
 *
 * DATA SOURCE: All data fetched by AnalyticsTab child components. This page is
 * a thin layout shell that resolves the active portfolioId and renders the header.
 *
 * DESIGN REFERENCE: docs/designs/0089/04-portfolio-detail.md §4.3
 */
"use client";
// WHY "use client": useActivePortfolio reads from a React Context; context
// consumers must be client components.

import Link from "next/link";
import { useActivePortfolio } from "@/contexts/ActivePortfolioContext";
import { AnalyticsTab } from "@/features/portfolio/components/AnalyticsTab";

export default function PortfolioAnalyticsPage() {
  // WHY useActivePortfolio (not usePortfolioData): this page only needs the
  // active portfolio ID — it does not need holdings, quotes, transactions, or
  // any of the other data orchestrated by usePortfolioData. Using the leaner
  // context hook avoids firing 9 queries just to get one value.
  const { activePortfolioId } = useActivePortfolio();

  return (
    <div className="flex flex-col h-full min-h-0 overflow-y-auto bg-background">
      {/* Page header — sticky so the "← Portfolio" link stays visible when
          the user scrolls through the charts. Same h-[36px] + border-b pattern
          as every other portfolio sub-page header for visual consistency. */}
      <div className="flex h-[36px] shrink-0 items-center border-b border-border bg-card px-3 gap-3 sticky top-0 z-20">
        <Link
          href="/portfolio"
          className="font-mono text-[10px] text-muted-foreground hover:text-foreground"
        >
          ← Portfolio
        </Link>
        <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
          Analytics
        </span>
      </div>

      {/* Main analytics content.
          WHY guard activePortfolioId: if no portfolio is selected (brand-new
          user or context not yet resolved) we show a loading hint rather than
          mounting AnalyticsTab with an empty string portfolioId — which would
          fire queries with an invalid ID and likely produce 400 errors. */}
      {activePortfolioId ? (
        <AnalyticsTab portfolioId={activePortfolioId} />
      ) : (
        <div className="flex items-center justify-center flex-1 text-[11px] text-muted-foreground font-mono">
          Loading portfolio…
        </div>
      )}
    </div>
  );
}
