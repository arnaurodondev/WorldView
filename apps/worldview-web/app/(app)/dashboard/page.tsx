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
 * WHY 4-ROW LAYOUT (PLAN-0048 E-1, amended Round 2 2026-06-10):
 *   Row 1 (col-12)                      : Morning Brief                — situational awareness
 *   Row 2 (col-2 · col-3 · col-4 · col-3): Market Clock · Market Snapshot · Sector Heatmap · AI Signals
 *   Row 3 (4 × col-3)                    : Portfolio Summary · Top Positions · Prediction Markets · Movers
 *   Row 4 (4 × col-3)                    : Econ Calendar · Earnings · Portfolio News · Recent Alerts
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
// Round 2 enhancement (2026-06-10): MarketClockWidget — US-equity session
// state (pre/regular/after/closed) + countdown, placed in Row 2 directly
// beside the Market Snapshot index strip so the session context sits next to
// the quotes it qualifies ("are these prices live or last close?").
import { MarketClockWidget } from "@/components/dashboard/MarketClockWidget";
// Round 2 enhancement: WatchlistQuickViewWidget — top-5 positions by value
// with live price, day P&L $ and a 5-day sparkline. Complements
// PortfolioSummary (totals) with a per-position "what moved today" scan.
import { WatchlistQuickViewWidget } from "@/components/dashboard/WatchlistQuickViewWidget";
import { SectorHeatmapWidget } from "@/components/dashboard/SectorHeatmapWidget";
// PLAN-0053 T-B-2-03: replaced direct WatchlistMoversWidget mount with the
// MoversWidgetTabs wrapper which hosts Holdings + Watchlist movers behind a
// tab toggle. The tab defaults to Holdings so users with a brokerage see
// their owned names first, but Watchlist remains one click away.
// ISSUE-3: MoversWidgetTabs moved to Row 3 (wider, more prominent placement)
// so all three tab views (MARKET / HOLDINGS / WATCHLIST) have enough vertical
// space to show meaningful list depth without crowding the Row 2 strip.
import { MoversWidgetTabs } from "@/components/dashboard/MoversWidgetTabs";
import { PortfolioSummary } from "@/components/dashboard/PortfolioSummary";
// ISSUE-3: AiSignalsWidget now occupies the Row 2 col-5 slot previously held
// by MoversWidgetTabs. The ML price-impact signals are compact (ticker + bar +
// score) and fit well in the 130px Row 2 height budget. PreMarketMoversWidget
// is removed — MoversWidgetTabs in Row 3 covers the universe-wide movers view
// (via its MARKET tab) without duplicating a standalone movers component.
import { AiSignalsWidget } from "@/components/dashboard/AiSignalsWidget";
import { PredictionMarketsWidget } from "@/components/dashboard/PredictionMarketsWidget";
import { EconomicCalendar } from "@/components/dashboard/EconomicCalendar";
import { EarningsCalendarWidget } from "@/components/dashboard/EarningsCalendarWidget";
import { PortfolioNewsWidget } from "@/components/dashboard/PortfolioNewsWidget";
import { RecentAlerts } from "@/components/dashboard/RecentAlerts";
// PLAN-0070 C-2: DashboardSnapshotPrefetcher is a thin client wrapper that fires
// useDashboardSnapshot() to warm the TanStack Query cache in one round-trip.
// Returns null — no visible UI. Individual widgets still own their own queries.
import { DashboardSnapshotPrefetcher } from "@/components/dashboard/DashboardSnapshotPrefetcher";
// F-2: single composite bundle hydrator — fires GET /v1/dashboard/bundle once
// and writes the legs into the per-widget TanStack caches via setQueryData so
// child widgets render WITHOUT firing their own initial fetches. Renders null.
import { DashboardBundleHydrator } from "@/components/dashboard/DashboardBundleHydrator";

// ── Page ──────────────────────────────────────────────────────────────────────

// HF-10: per-route metadata replaces the generic root <title>. Each Phase-A
// surface needs its own title so browser tabs / bookmarks / window-history
// (and screen readers announcing page changes) identify the page distinctly.
// The dashboard is a server component, so the metadata export works in-place;
// client-component pages add a sibling `layout.tsx` that exports metadata.
export const metadata = { title: "Dashboard | Worldview" };

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
        height: "calc(100vh - var(--topbar-height))",
        // WHY the responsive gridTemplateRows is applied via inline style only
        // at >= lg: at smaller breakpoints the cells dictate their own height
        // via natural content + h-auto, and a fixed-row template would clip
        // them. Tailwind can't conditionally set inline styles, so we keep
        // the fixed template only at lg via CSS variable + media query? Easier:
        // omit the constraint here and rely on per-cell h-full/min-h-0 at lg.
        gridTemplateRows:
          "var(--dashboard-grid-rows, auto minmax(130px, max-content) minmax(220px, 1fr) minmax(200px, 1fr))",
      }}
    >
      {/* PLAN-0070 C-2: fires GET /v1/dashboard/snapshot to warm the TanStack
          Query cache in a single round-trip. Returns null — no visible UI. */}
      <DashboardSnapshotPrefetcher />
      {/* F-2: fires GET /v1/dashboard/bundle (newer composite) and hydrates
          per-widget caches so children skip their initial fetches. Returns null. */}
      <DashboardBundleHydrator />

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

      {/* ── Row 2: Market Clock (2) · Market Snapshot (3) · Sector Heatmap (4) · AI Signals (3) ── */}
      {/* WHY 2 + 3 + 4 + 3 (Round 2 enhancement, was 3 + 4 + 5):
            - MarketClockWidget at col-2 (~200px): the session clock is three
              short lines (HH:MM:SS · state · countdown) — the narrowest cell
              on the grid is enough, and placing it FIRST in the macro band
              means the trader reads "is the market open?" before any quote.
            - MarketSnapshot keeps col-3 (~290px): fits its 11 ticker rows.
            - SectorHeatmap keeps col-4 (~390px) for the wrapped tile grid.
            - AiSignalsWidget shrinks 5→3 (~290px): each signal row is just a
              ticker chip + 4px score bar + percentage — comfortably fits.
          WHY min-w-0 on every cell: each widget contains a flex layout with
          truncate-able children. Without min-w-0, flex children default to
          their min-content width and break the truncate.
          WHY border border-border/40: subtle 1px panel border preserves the
          original Bloomberg-style cell-seam aesthetic while gap-3 supplies
          the breathing room. */}
      {/* WHY NO border class on the clock cell: MarketClockWidget renders its
          OWN border because the border COLOR is the session indicator
          (positive=open, warning=extended hours, muted=closed) and is only
          known client-side after mount — the server-rendered cell can't pick it. */}
      <div className="col-span-1 md:col-span-2 lg:col-span-2 h-full min-w-0">
        <MarketClockWidget />
      </div>
      <div className="col-span-1 md:col-span-4 lg:col-span-3 h-full min-w-0 border border-border/40">
        <MarketSnapshotWidget />
      </div>
      <div className="col-span-1 md:col-span-3 lg:col-span-4 h-full min-w-0 border border-border/40">
        <SectorHeatmapWidget />
      </div>
      {/* ISSUE-3: AiSignalsWidget replaces MoversWidgetTabs here. The ML
          price-impact signals feed fits Row 2's 130px height budget — each
          row is just a ticker chip + score bar + percentage (no pagination
          needed for ≤6 signals). overflow-hidden prevents the score bars
          from bleeding outside the cell boundary. */}
      <div className="col-span-1 md:col-span-3 lg:col-span-3 h-full min-h-0 min-w-0 overflow-hidden border border-border/40">
        <AiSignalsWidget />
      </div>

      {/* ── Row 3: Portfolio (3) · Top Positions (3) · Prediction Markets (3) · MoversWidgetTabs (3) ── */}
      {/* WHY 3 + 3 + 3 + 3 (Round 2 enhancement, was 4 + 4 + 4):
            - WatchlistQuickViewWidget joins Row 3, so the three existing
              widgets each cede one column. Equal-weight cells: each is a
              different signal stream (your totals · your top positions ·
              prediction-market consensus · market movers).
            - Top Positions sits NEXT TO PortfolioSummary deliberately — both
              are "my money" panels; adjacency groups them Gestalt-style while
              the totals/positions split keeps each panel single-purpose.
            - MoversWidgetTabs at col-3 still fits its rows: ticker · name ·
              sparkline · price · % truncate gracefully via min-w-0 children.
          WHY overflow-hidden on each cell: rows 3 + 4 are minmax(Npx, 1fr)
          (bounded height). overflow-hidden on the cell + overflow-y-auto
          inside the widget content area enables independent scrolling per
          panel without page-level overflow. */}
      <div className="col-span-1 md:col-span-3 lg:col-span-3 h-full min-h-0 min-w-0 overflow-hidden border border-border/40">
        <PortfolioSummary />
      </div>
      {/* Round 2: top-5 positions by value — live price, day P&L $, 5-day
          sparkline. Shares the portfolios/holdings/quotes caches with
          PortfolioSummary (identical query keys) so it adds only ONE extra
          network request (the batched sparklines call). */}
      <div className="col-span-1 md:col-span-3 lg:col-span-3 h-full min-h-0 min-w-0 overflow-hidden border border-border/40">
        <WatchlistQuickViewWidget />
      </div>
      <div className="col-span-1 md:col-span-3 lg:col-span-3 h-full min-h-0 min-w-0 overflow-hidden border border-border/40">
        <PredictionMarketsWidget />
      </div>
      {/* ISSUE-3: MoversWidgetTabs moves here from Row 2 to get the full
          minmax(220px, 1fr) height budget (vs the fixed 130px in Row 2).
          This gives all three tab panes (MARKET / HOLDINGS / WATCHLIST)
          enough vertical space to show ≥8 movers without crowding.
          Round 1 foundation (2026-06-10): the MARKET tab now hosts the
          redesigned TopMovers (Gainers/Losers shadcn Tabs; rows with ticker ·
          name · 5-day sparkline · price · %chg) — PreMarketMoversWidget is
          fully unmounted. */}
      <div className="col-span-1 md:col-span-3 lg:col-span-3 h-full min-h-0 min-w-0 overflow-hidden border border-border/40">
        <MoversWidgetTabs />
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
