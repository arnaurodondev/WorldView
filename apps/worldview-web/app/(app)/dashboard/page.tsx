/**
 * app/(app)/dashboard/page.tsx — Main trading dashboard (9 widgets)
 *
 * WHY THIS EXISTS: The dashboard is the "home base" for institutional traders.
 * It aggregates all critical data streams (portfolio, alerts, news, macro events,
 * market context) into a single view so traders can assess their situation in
 * under 30 seconds at market open.
 *
 * WHY 3-COLUMN BASE + 4-COLUMN XL: Three columns is the sweet spot for lg screens;
 * four columns at xl+ breakpoint (≥1280px) maximises information density on wide
 * monitors — the typical finance desk setup. Full-width rows (brief, movers) span
 * all columns at every breakpoint so they scale naturally.
 *
 * WHY EACH WIDGET IS INDEPENDENT: Each widget fetches its own data via TanStack
 * Query. This means loading failures in one widget don't block others — the
 * trader still sees the heatmap even if the briefing endpoint is down.
 *
 * WHO USES IT: Authenticated users navigating to / or /dashboard
 * DATA SOURCES: Multiple S9 endpoints — see individual widget files
 * DESIGN REFERENCE: PRD-0028 §6.3.2 Dashboard Page, canvas State A (SL9kb)
 */

import { MorningBriefCard } from "@/components/dashboard/MorningBriefCard";
import { PortfolioSummary } from "@/components/dashboard/PortfolioSummary";
import { MarketHeatmap } from "@/components/dashboard/MarketHeatmap";
import { TopMovers } from "@/components/dashboard/TopMovers";
import { WatchlistNews } from "@/components/dashboard/WatchlistNews";
import { EconomicCalendar } from "@/components/dashboard/EconomicCalendar";
import { RecentAlerts } from "@/components/dashboard/RecentAlerts";
import { AiSignals } from "@/components/dashboard/AiSignals";
import { TopBets } from "@/components/dashboard/TopBets";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

// ── Page ──────────────────────────────────────────────────────────────────────

// WHY NO PAGE-LEVEL SKELETON / STAGGERED LOADING:
// Each widget manages its own loading state independently via TanStack Query.
// This is intentional — a page-level skeleton would block the entire dashboard
// until ALL endpoints respond, whereas per-widget skeletons let the trader see
// each panel the moment its data arrives. Staggered animation at the page level
// would require artificial delays that hurt time-to-interactive.
// See V-5.4 audit (2026-04-19).

export default function DashboardPage() {
  return (
    // WHY p-4 gap-3: tight but not cramped — finance terminal standard.
    // WHY gap-3 (not gap-4): saving 4px between every widget adds up to ~32px on
    // a 9-widget dashboard — nearly a full extra row of data at high density.
    // WHY xl:grid-cols-4: at ≥1280px (typical finance desk), 4 columns make full
    // use of horizontal space. Full-width rows auto-expand via xl:col-span-4.
    <div className="grid h-full grid-cols-1 gap-3 overflow-y-auto p-4 lg:grid-cols-3 xl:grid-cols-4">

      {/* ── Row 1: Morning Brief (full width at all breakpoints) ──────────── */}
      <Card className="lg:col-span-3 xl:col-span-4">
        <CardHeader className="pb-1 pt-2">
          <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Morning Brief
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-3">
          <MorningBriefCard />
        </CardContent>
      </Card>

      {/* ── Row 2: Portfolio Summary (2/3 lg, 3/4 xl) + Market Heatmap (1/4) */}
      <Card className="lg:col-span-2 xl:col-span-3">
        <CardHeader className="pb-1 pt-2">
          <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Portfolio
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-3">
          <PortfolioSummary />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-1 pt-2">
          <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Market Heatmap
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-3">
          <MarketHeatmap />
        </CardContent>
      </Card>

      {/* ── Row 3: Top Movers (full width at all breakpoints) ────────────── */}
      <Card className="lg:col-span-3 xl:col-span-4">
        <CardHeader className="pb-1 pt-2">
          <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Top Movers
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-3">
          <TopMovers />
        </CardContent>
      </Card>

      {/* ── Row 4: Watchlist News (2/3 lg, 3/4 xl) + Economic Calendar (1/4) */}
      <Card className="lg:col-span-2 xl:col-span-3">
        <CardHeader className="pb-1 pt-2">
          <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            News (48h)
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-3">
          <WatchlistNews />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-1 pt-2">
          <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Economic Calendar
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-3">
          <EconomicCalendar />
        </CardContent>
      </Card>

      {/* ── Row 5: Recent Alerts (1/3) + AI Signals (1/3) + top bets (1/3) ── */}
      <Card>
        <CardHeader className="pb-1 pt-2">
          <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Alerts
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-3">
          <RecentAlerts />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-1 pt-2">
          <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            AI Signals
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-3">
          <AiSignals />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-1 pt-2">
          <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Prediction Markets
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-3">
          <TopBets />
        </CardContent>
      </Card>

    </div>
  );
}
