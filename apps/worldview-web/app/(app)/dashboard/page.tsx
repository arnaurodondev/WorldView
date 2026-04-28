/**
 * app/(app)/dashboard/page.tsx — Main trading dashboard (Wave 7 redesign)
 *
 * WHY THIS EXISTS: The dashboard is the "home base" for institutional traders.
 * It aggregates all critical data streams (portfolio, alerts, news, macro events,
 * market context) into a single view so traders can assess their situation in
 * under 30 seconds at market open.
 *
 * WHY 12-COLUMN CSS GRID WITH gap-px:
 * A 12-column grid gives fine-grained control over asymmetric widget widths
 * (4+8, 4+5+3, 3+3+3+3). gap-px exposes the background color (#09090B) as
 * 1px hairline borders between panels — Bloomberg Terminal-style panel seams
 * without actual CSS borders on each cell.
 *
 * WHY 4-ROW TRADER MORNING ROUTINE LAYOUT:
 * Row 1: Morning Brief (situational awareness)
 * Row 2: Market Snapshot + Sector Heatmap (macro context)
 * Row 3: Portfolio + Top Movers + Prediction Markets (portfolio + signal scan)
 * Row 4: Econ Calendar + Earnings + News + Alerts (event-driven context)
 * This ordering mirrors how an institutional trader starts their day.
 *
 * WHY EACH WIDGET IS INDEPENDENT: Each widget fetches its own data via TanStack
 * Query. Loading failures in one widget don't block others — the trader still
 * sees the heatmap even if the briefing endpoint is down.
 *
 * WHY h-[calc(100vh-36px)]: fills exactly the viewport below the 36px topbar,
 * so the grid is flush with the shell edges. overflow-auto on the grid allows
 * scrolling on smaller screens.
 *
 * WHO USES IT: Authenticated users navigating to / or /dashboard
 * DATA SOURCES: Multiple S9 endpoints — see individual widget files
 * DESIGN REFERENCE: PRD-0031 §10 Dashboard, PLAN-0039 Wave 7
 */

import { MorningBriefCard } from "@/components/dashboard/MorningBriefCard";
import { MarketSnapshotWidget } from "@/components/dashboard/MarketSnapshotWidget";
import { SectorHeatmapWidget } from "@/components/dashboard/SectorHeatmapWidget";
import { PortfolioSummary } from "@/components/dashboard/PortfolioSummary";
import { PreMarketMoversWidget } from "@/components/dashboard/PreMarketMoversWidget";
import { PredictionMarketsWidget } from "@/components/dashboard/PredictionMarketsWidget";
import { AiSignalsWidget } from "@/components/dashboard/AiSignalsWidget";
import { EconomicCalendar } from "@/components/dashboard/EconomicCalendar";
import { EarningsCalendarWidget } from "@/components/dashboard/EarningsCalendarWidget";
import { PortfolioNewsWidget } from "@/components/dashboard/PortfolioNewsWidget";
import { RecentAlerts } from "@/components/dashboard/RecentAlerts";

// ── Page ──────────────────────────────────────────────────────────────────────

// WHY NO PAGE-LEVEL SKELETON / STAGGERED LOADING:
// Each widget manages its own loading state independently via TanStack Query.
// This is intentional — a page-level skeleton would block the entire dashboard
// until ALL endpoints respond, whereas per-widget skeletons let the trader see
// each panel the moment its data arrives.
// See V-5.4 audit (2026-04-19).

export default function DashboardPage() {
  return (
    // WHY grid-cols-12 gap-px bg-background:
    //   - 12 columns gives fine-grained asymmetric widths (4+8, 4+5+3, etc.)
    //   - gap-px (1px gap) exposes bg-background (#09090B) as hairline borders
    //     between panels — Bloomberg Terminal-style panel seams
    //   - overflow-auto: allows scrolling on smaller viewports where rows overflow
    // WHY h-[calc(100vh-36px)]: fills viewport below the 36px topbar exactly,
    //   grid cells stretch to fill with their own overflow-auto/hidden
    <div
      className="grid grid-cols-12 gap-px overflow-hidden bg-background"
      style={{ height: "calc(100vh - 36px)", gridTemplateRows: "auto 130px minmax(220px, 1fr) minmax(200px, 1fr)" }}
    >

      {/* ── Row 1: Morning Brief — full width ────────────────────────────── */}
      {/* WHY col-span-12: brief always spans all columns — it's the primary
          situational awareness widget and deserves full horizontal real estate.
          WHY border border-primary: the Morning Brief is the single most important
          widget — a yellow/amber accent border marks it visually as the primary
          intelligence signal, following Bloomberg Terminal's amber-on-black hierarchy. */}
      {/* WHY bg-background p-2: the brief card renders raw (no wrapper bg).
          Setting bg here makes the Row 1 band match all other row cells. p-2 gives
          the MorningBriefCard content breathing room within the border frame. */}
      <div className="col-span-12 border border-primary/60 bg-background p-2">
        <MorningBriefCard />
      </div>

      {/* ── Row 2: Market Snapshot (3) + Sector Heatmap (4) + Prediction Markets (5) ── */}
      {/* WHY 3+4+5 restructure (PLAN-0045 D-1):
          — PredictionMarkets moved from Row 3 col-span-2 to Row 2 col-span-5.
            At col-span-2 (~200px) market titles (40-80 chars) were truncated.
            At col-span-5 (~400px) they are fully readable.
          — MarketSnapshot shrinks from 4 → 3 (still fits 6 tickers at ~240px).
          — SectorHeatmap shrinks from 8 → 4 (2-column layout added in D-2 so
            all 11 sectors fit within 4 columns).
          WHY gridTemplateRows caps Row 2 at 130px: constant height for market context
          — headers + bars + values all fit; expanding this row wastes prime real estate. */}
      <div className="col-span-3 h-full border border-border/40">
        <MarketSnapshotWidget />
      </div>
      <div className="col-span-4 h-full border border-border/40">
        <SectorHeatmapWidget />
      </div>
      <div className="col-span-5 h-full border border-border/40">
        <PredictionMarketsWidget />
      </div>

      {/* ── Row 3: Portfolio (4) + Top Movers (4) + AI Signals (4) ─────────── */}
      {/* WHY 4+4+4 (PLAN-0045 D-1):
          — PredictionMarkets moved to Row 2; this frees 4 columns for Row 3.
          — AI Signals expands from col-span-2 to col-span-4 (more space for signal bars).
          — All three cells fill available height (minmax(220px, 1fr)) and scroll independently. */}
      <div className="col-span-4 h-full overflow-hidden border border-border/40">
        <PortfolioSummary />
      </div>
      <div className="col-span-4 h-full overflow-hidden border border-border/40">
        <PreMarketMoversWidget />
      </div>
      <div className="col-span-4 h-full overflow-hidden border border-border/40">
        <AiSignalsWidget />
      </div>

      {/* ── Row 4: Econ Calendar (3) + Earnings (3) + News (3) + Alerts (3) ─ */}
      {/* WHY symmetric 3+3+3+3: all four widgets are equally important context
          for end-of-morning review — no one panel deserves more space.
          WHY overflow-hidden: rows 3+4 are minmax(Npx, 1fr) — bounded height.
          overflow-hidden on the cell, overflow-y-auto inside the widget content
          area enables independent scrolling per panel without page-level overflow. */}
      <div className="col-span-3 h-full overflow-hidden border border-border/40">
        <EconomicCalendar />
      </div>
      <div className="col-span-3 h-full overflow-hidden border border-border/40">
        <EarningsCalendarWidget />
      </div>
      <div className="col-span-3 h-full overflow-hidden border border-border/40">
        <PortfolioNewsWidget />
      </div>
      <div className="col-span-3 h-full overflow-hidden border border-border/40">
        <RecentAlerts />
      </div>

    </div>
  );
}
