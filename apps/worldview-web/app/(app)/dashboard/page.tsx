/**
 * app/(app)/dashboard/page.tsx — Main trading dashboard (PLAN-0048 Wave E layout)
 *
 * WHY THIS EXISTS: The dashboard is the "home base" for institutional traders.
 * It aggregates all critical data streams (portfolio, alerts, news, macro events,
 * market context) into a single view so traders can assess their situation in
 * under 30 seconds at market open.
 *
 * WHY 12-COLUMN CSS GRID:
 * A 12-column grid gives fine-grained control over asymmetric widget widths
 * (3+4+5, 4+4+4, 3+3+3+3). Using `grid grid-cols-12 gap-3` (12px gaps) gives
 * a clean panel-separator feel without 1px hairline seams from the previous
 * gap-px layout — Wave E spec calls for `grid grid-cols-12 gap-3`.
 *
 * WHY 4-ROW LAYOUT (PLAN-0048 E-1):
 *   Row 1 (col-12)              : Morning Brief                        — situational awareness
 *   Row 2 (col-3 · col-4 · col-5): Market Snapshot · Sector Heatmap (treemap, F-1) · Watchlist Movers
 *   Row 3 (col-4 · col-4 · col-4): Portfolio Summary · Prediction Markets · Top Movers (universe-wide, F-2)
 *   Row 4 (4 × col-3)            : Econ Calendar · Earnings · Portfolio News · Recent Alerts
 *
 * Rationale (matches user's "move predictions there instead" feedback):
 *  - The deprecated PortfolioGainersLosers widget is GONE — its data was a
 *    duplicate of the holdings table inside PortfolioSummary, so showing it
 *    twice on the same dashboard added cognitive load without value.
 *  - WatchlistMovers replaces market-wide movers in Row 2 (col-5) — wider
 *    cell shows the full ticker · name · price · % grid comfortably.
 *  - PredictionMarkets moves to Row 3 col-4 (the slot freed by removing
 *    PortfolioGainersLosers).
 *  - Universe-wide TopMovers (PreMarketMoversWidget — now sector-filterable
 *    after Wave F-2) takes the remaining Row 3 col-4.
 *
 * WHY EACH WIDGET IS INDEPENDENT: Each widget fetches its own data via
 * TanStack Query. Failures in one widget don't block others — the trader
 * still sees the heatmap even if the briefing endpoint is down.
 *
 * WHY h-[calc(100vh-36px)]: fills exactly the viewport below the 36px topbar,
 * so the grid is flush with the shell edges. overflow-auto on the grid allows
 * scrolling on smaller screens.
 *
 * WHY min-w-0 / min-h-0 on every cell: each cell hosts widgets with internal
 * flex containers (sparklines, tables, scroll lists). Without min-w-0 a
 * truncated child name can blow out its parent's width; without min-h-0 an
 * inner overflow-auto would push the panel taller than the row. Both are
 * the standard CSS-flex/grid escape hatches for "respect my bounds".
 *
 * WHO USES IT: Authenticated users navigating to / or /dashboard.
 * DATA SOURCES: Multiple S9 endpoints — see individual widget files.
 * DESIGN REFERENCE: PRD-0031 §10 Dashboard, PLAN-0048 Wave E (E-1).
 */

import { MorningBriefCard } from "@/components/dashboard/MorningBriefCard";
import { MarketSnapshotWidget } from "@/components/dashboard/MarketSnapshotWidget";
import { SectorHeatmapWidget } from "@/components/dashboard/SectorHeatmapWidget";
import { WatchlistMoversWidget } from "@/components/dashboard/WatchlistMoversWidget";
import { PortfolioSummary } from "@/components/dashboard/PortfolioSummary";
import { PreMarketMoversWidget } from "@/components/dashboard/PreMarketMoversWidget";
import { PredictionMarketsWidget } from "@/components/dashboard/PredictionMarketsWidget";
import { EconomicCalendar } from "@/components/dashboard/EconomicCalendar";
import { EarningsCalendarWidget } from "@/components/dashboard/EarningsCalendarWidget";
import { PortfolioNewsWidget } from "@/components/dashboard/PortfolioNewsWidget";
import { RecentAlerts } from "@/components/dashboard/RecentAlerts";

// ── Page ──────────────────────────────────────────────────────────────────────

// WHY NO PAGE-LEVEL SKELETON / STAGGERED LOADING:
// Each widget manages its own loading state independently via TanStack Query.
// A page-level skeleton would block the entire dashboard until ALL endpoints
// respond, whereas per-widget skeletons let the trader see each panel the
// moment its data arrives. See V-5.4 audit (2026-04-19).

export default function DashboardPage() {
  return (
    // WHY grid grid-cols-12 gap-3 + gridTemplateRows:
    //   - 12 columns gives fine-grained asymmetric widths (Wave E spec).
    //   - gap-3 (12px) is the Wave E spec gap — wider than the previous
    //     gap-px to give the panels visible breathing room rather than
    //     hairline seams.
    //   - gridTemplateRows fixes Row 2 to 130px (constant macro-context band)
    //     and lets Rows 3 + 4 stretch via minmax(Npx, 1fr) so the dashboard
    //     fills the available viewport regardless of resolution.
    //   - overflow-auto on this container allows scrolling on small viewports
    //     where the row stack overflows the 100vh-36px height budget.
    // WHY p-3: gives the outermost panel-set the same 12px breathing margin
    // as the gaps between cells — visually centring the grid in the chrome.
    //
    // PLAN-0053 T-H-8-01: responsive breakpoints.
    //   - default (<md, mobile <768px): grid-cols-1 — every widget stacks.
    //   - md (≥768px, tablet): grid-cols-6 — two-up layout (12-col widgets
    //     halved). Row heights drop to auto so panels expand to natural
    //     content height instead of being clipped at 130px.
    //   - lg (≥1024px, desktop): grid-cols-12 — original Bloomberg-grade
    //     dense layout with fixed row sizes.
    // WHY two breakpoints (not one): tablet readers (e.g. iPad in landscape)
    // benefit from a 2-up layout that's still denser than a single column,
    // while mobile users get one widget per row for legibility.
    <div
      className="grid grid-cols-1 md:grid-cols-6 lg:grid-cols-12 gap-3 overflow-auto bg-background p-3"
      style={{
        height: "calc(100vh - 36px)",
        // WHY the responsive gridTemplateRows is applied via inline style only
        // at >= lg: at smaller breakpoints the cells dictate their own height
        // via natural content + h-auto, and a fixed-row template would clip
        // them. Tailwind can't conditionally set inline styles, so we keep
        // the fixed template only at lg via CSS variable + media query? Easier:
        // omit the constraint here and rely on per-cell h-full/min-h-0 at lg.
        gridTemplateRows:
          "var(--dashboard-grid-rows, auto 130px minmax(220px, 1fr) minmax(200px, 1fr))",
      }}
    >

      {/* ── Row 1: Morning Brief — full width ───────────────────────────── */}
      {/* WHY col-span-12: brief always spans all columns — it's the primary
          situational awareness widget and deserves full horizontal real
          estate.
          WHY border border-primary/60: the Morning Brief is the single most
          important widget — a yellow/amber accent border marks it visually
          as the primary intelligence signal, following Bloomberg Terminal's
          amber-on-black hierarchy.
          WHY p-2 inside the cell: the MorningBriefCard renders its own
          tight content with no padding; this gives it breathing room
          inside the accent frame. */}
      {/* PLAN-0053 T-H-8-01 responsive col-spans: each cell carries
          mobile→tablet→desktop variants. Pattern is `col-span-1 md:col-span-X
          lg:col-span-Y`. The mobile single-column stack (col-span-1) is the
          implicit fallback — every widget gets full row width. */}
      <div className="col-span-1 md:col-span-6 lg:col-span-12 min-w-0 border border-primary/60 bg-background p-2">
        <MorningBriefCard />
      </div>

      {/* ── Row 2: Market Snapshot (3) · Sector Heatmap (4) · Watchlist Movers (5) ── */}
      {/* WHY 3 + 4 + 5 (Wave E-1):
            - MarketSnapshot at col-3 (~230px) fits 6 ticker rows comfortably.
            - SectorHeatmap is now a TREEMAP (Wave F-1); col-4 (~310px) gives
              the wrapped tile grid enough horizontal room for 11 tiles.
            - WatchlistMovers at col-5 (~390px) is wide enough for a full
              ticker · name · price · % row in two parallel columns.
          WHY min-w-0 on every cell: each widget contains a flex layout with
          truncate-able children. Without min-w-0, flex children default to
          their min-content width and break the truncate.
          WHY border border-border/40: subtle 1px panel border preserves the
          original Bloomberg-style cell-seam aesthetic while gap-3 supplies
          the breathing room. */}
      <div className="col-span-1 md:col-span-3 lg:col-span-3 h-full min-w-0 border border-border/40">
        <MarketSnapshotWidget />
      </div>
      <div className="col-span-1 md:col-span-3 lg:col-span-4 h-full min-w-0 border border-border/40">
        <SectorHeatmapWidget />
      </div>
      {/* WHY overflow-hidden on this cell: WatchlistMoversWidget contains a
          scroll container (independent-scroll rule) — the cell itself must
          clip so the inner overflow-auto has a definite height. */}
      <div className="col-span-1 md:col-span-6 lg:col-span-5 h-full min-h-0 min-w-0 overflow-hidden border border-border/40">
        <WatchlistMoversWidget />
      </div>

      {/* ── Row 3: Portfolio (4) · Prediction Markets (4) · Top Movers (4) ── */}
      {/* WHY 4 + 4 + 4 (Wave E-1):
            - Equal-weight cells: each represents a different signal stream
              (your money · prediction-market consensus · universe-wide
              outliers). Symmetric layout signals "no panel is more
              important than the others — choose your view".
            - PredictionMarkets moved here from Row 2 to free col-5 for
              WatchlistMovers (per Wave E-1).
            - PreMarketMoversWidget (universe-wide TopMovers, sector-filterable
              via Wave F-2) is the remaining col-4 cell — duplicates the
              gainers/losers idiom of WatchlistMovers but for the full market.
          WHY overflow-hidden on each cell: rows 3 + 4 are minmax(Npx, 1fr)
          (bounded height). overflow-hidden on the cell + overflow-y-auto
          inside the widget content area enables independent scrolling per
          panel without page-level overflow. */}
      <div className="col-span-1 md:col-span-3 lg:col-span-4 h-full min-h-0 min-w-0 overflow-hidden border border-border/40">
        <PortfolioSummary />
      </div>
      <div className="col-span-1 md:col-span-3 lg:col-span-4 h-full min-h-0 min-w-0 overflow-hidden border border-border/40">
        <PredictionMarketsWidget />
      </div>
      <div className="col-span-1 md:col-span-6 lg:col-span-4 h-full min-h-0 min-w-0 overflow-hidden border border-border/40">
        <PreMarketMoversWidget />
      </div>

      {/* ── Row 4: Econ Calendar (3) · Earnings (3) · Portfolio News (3) · Recent Alerts (3) ── */}
      {/* WHY symmetric 3 + 3 + 3 + 3: all four widgets are equally important
          context for end-of-morning review — no one panel deserves more
          space.
          WHY overflow-hidden + min-h-0: independent-scroll rule (see Row 3
          rationale). */}
      <div className="col-span-1 md:col-span-3 lg:col-span-3 h-full min-h-0 min-w-0 overflow-hidden border border-border/40">
        <EconomicCalendar />
      </div>
      <div className="col-span-1 md:col-span-3 lg:col-span-3 h-full min-h-0 min-w-0 overflow-hidden border border-border/40">
        <EarningsCalendarWidget />
      </div>
      <div className="col-span-1 md:col-span-3 lg:col-span-3 h-full min-h-0 min-w-0 overflow-hidden border border-border/40">
        <PortfolioNewsWidget />
      </div>
      <div className="col-span-1 md:col-span-3 lg:col-span-3 h-full min-h-0 min-w-0 overflow-hidden border border-border/40">
        <RecentAlerts />
      </div>

    </div>
  );
}
