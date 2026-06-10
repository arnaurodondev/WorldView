/**
 * app/(app)/portfolio/analytics/page.tsx — Analytics sub-page.
 *
 * WHY THIS EXISTS: The portfolio page has Holdings / Transactions / Analytics /
 * Watchlist tabs. This dedicated route renders AnalyticsTab at its own URL
 * (/portfolio/analytics) for deep-linking and for the E2E smoke tests that
 * verify all sub-routes are registered and don't 404.
 *
 * The "A" hotkey on /portfolio navigates here.
 *
 * WHO USES IT: PMs who want a full-height analytics view (TWR chart,
 * drawdown, period returns table, risk sidebar).
 * DATA SOURCE: Same as AnalyticsTab — fetches from S9 portfolio routes.
 * DESIGN REFERENCE: PRD-0089 W2 §4.20, docs/designs/0089/04-portfolio-detail.md §4.3
 */
"use client";
// WHY "use client": AnalyticsTab uses useQuery + recharts (browser DOM required).

import Link from "next/link";
import { AnalyticsTab } from "@/features/portfolio/components/AnalyticsTab";
import { usePortfolioData } from "@/features/portfolio/hooks/usePortfolioData";
import { useAuth } from "@/hooks/useAuth";

export default function PortfolioAnalyticsPage() {
  const { accessToken } = useAuth();
  // WHY selectedPeriod = "1D": same lock as the main page. The period is used
  // by usePortfolioData for the performance query; AnalyticsTab manages its
  // own period state internally (local useState).
  const selectedPeriod = "1D" as const;
  const { activePortfolioId } = usePortfolioData({ accessToken, selectedPeriod });

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      {/* Page header with back link */}
      <div className="flex h-[36px] shrink-0 items-center gap-3 border-b border-border bg-card px-3">
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

      {activePortfolioId ? (
        <AnalyticsTab portfolioId={activePortfolioId} />
      ) : (
        <div className="flex flex-1 items-center justify-center">
          <p className="font-mono text-[11px] text-muted-foreground">
            Select a portfolio to view analytics.
          </p>
        </div>
      )}
    </div>
  );
}
