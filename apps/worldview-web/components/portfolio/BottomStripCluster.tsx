/**
 * BottomStripCluster — three equal-width bottom-strip cells below SemanticHoldingsTable.
 *
 * WHY THIS EXISTS: The Holdings tab bottom area is divided into three equal
 * columns: contributors (top movers up), detractors (top movers down), and
 * recent activity. This cluster is a thin flex wrapper that avoids duplicating
 * the layout in page.tsx or HoldingsTab.tsx — those files are already large
 * and don't need to know the 3-column internal layout.
 *
 * WHY THREE SEPARATE CELLS (not one ContributorsStrip):
 *   The existing ContributorsStrip renders BOTH contributors AND detractors in
 *   a single column (redesigned in PRD-0089 W2 for density). For the bottom
 *   strip, the spec (PLAN-0108 W4-T404) requires three visually distinct equal-
 *   width columns separated by vertical dividers. Splitting contributors and
 *   detractors into their own ContributorsStrip instances (each receiving only
 *   one side) achieves this without modifying ContributorsStrip itself.
 *
 * WHY h-24 (96px): The bottom strip slot height is fixed in the Holdings tab
 * layout. 96px accommodates a header row (22px) + up to 3-4 compact data rows
 * at ~18-20px each before the fold. Fixing the height prevents the strip from
 * collapsing when the table above uses flex-1 to fill the remaining viewport.
 *
 * WHY divide-x divide-border: shadcn/ui divide utilities produce a single 1px
 * vertical separator between each flex child. Using divide-x is more correct
 * than adding border-r to individual cells because it avoids a trailing border
 * on the last cell — which would double up with the parent container's border.
 *
 * Layout: h-24 flex flex-row divide-x divide-border
 *   ├── Cell 1 (flex-1) — ContributorsStrip: contributors only, detractors=[]
 *   ├── Cell 2 (flex-1) — ContributorsStrip: detractors only, contributors=[]
 *   └── Cell 3 (flex-1) — RecentActivityStrip
 *
 * WHO USES IT: T-4-05 will wire this into HoldingsTab below SemanticHoldingsTable.
 * DATA SOURCE: contributors and detractors are derived externally by useTopMovers;
 *   RecentActivityStrip fetches its own data via TanStack Query.
 * DESIGN REFERENCE: PLAN-0108 W4-T404, PRD-0089 §4.1 bottom strip cluster.
 */

// WHY no "use client" here: BottomStripCluster is a pure layout wrapper with no
// hooks or event handlers. Its children (ContributorsStrip, RecentActivityStrip)
// each declare "use client" themselves — Next.js 15 will cascade the client
// boundary downward automatically without this file needing the directive.

import { ContributorsStrip } from "@/components/portfolio/ContributorsStrip";
import { RecentActivityStrip } from "@/components/portfolio/RecentActivityStrip";

// ── Types ──────────────────────────────────────────────────────────────────────

/**
 * MoverEntry — mirrors the interface used in ContributorsStrip and useTopMovers.
 *
 * WHY re-declared here (not imported from ContributorsStrip): ContributorsStrip
 * declares MoverEntry as a local (non-exported) interface. Importing it would
 * require exporting it from ContributorsStrip, which changes that module's
 * public API and risks merge conflicts with T-4-05. Redeclaring a structurally
 * identical interface here is safe — TypeScript uses structural typing so the
 * types are fully compatible at call sites.
 */
export interface MoverEntry {
  ticker: string;
  /** Full company name — may be undefined; falls back to an em-dash in the row. */
  name?: string;
  /** P&L percentage (e.g. 3.4 means +3.4%). Positive for contributors, negative for detractors. */
  pnlPct: number;
}

export interface BottomStripClusterProps {
  /** Active portfolio UUID, forwarded to RecentActivityStrip for its transaction query. */
  portfolioId: string;
  /** Top 4 positive movers, sorted best-first. Derived by useTopMovers. */
  contributors: MoverEntry[];
  /** Top 4 negative movers, sorted worst-first. Derived by useTopMovers. */
  detractors: MoverEntry[];
}

// ── Component ─────────────────────────────────────────────────────────────────

export function BottomStripCluster({
  portfolioId,
  contributors,
  detractors,
}: BottomStripClusterProps) {
  return (
    /*
     * Outer wrapper — fixed height, horizontal flex with dividers.
     *
     * WHY w-full: the strip must span the full width of SemanticHoldingsTable
     * above it. Without w-full the flex container collapses to its content width.
     *
     * WHY overflow-hidden: ContributorsStrip uses h-full which, if the inner
     * content overflows at certain viewport sizes, could push past the 96px
     * boundary and shift the layout below. overflow-hidden clips any surplus.
     *
     * WHY border-b border-border: a bottom border visually closes the strip and
     * separates it from whatever comes after (e.g. a footer or a tab panel edge).
     */
    <div
      className="flex h-24 w-full flex-row divide-x divide-border overflow-hidden border-b border-border"
      data-testid="bottom-strip-cluster"
    >
      {/*
       * Cell 1 — Contributors (winners only).
       *
       * WHY detractors={[]}: ContributorsStrip renders both sections (Contributors
       * sub-header + Detractors sub-header) in one column. Passing an empty array
       * for detractors renders dash rows in the detractors section — effectively
       * hiding the detractors section content while keeping the component's fixed
       * height contract. Cell 1 acts as a "contributors-only" panel this way.
       *
       * WHY NOT a custom "mode" prop on ContributorsStrip: adding a mode prop
       * would require modifying ContributorsStrip (violating T-4-04 scope) and
       * would still need dash-row padding for the unused section.
       */}
      <div className="flex-1 overflow-hidden" data-testid="cell-contributors">
        <ContributorsStrip contributors={contributors} detractors={[]} />
      </div>

      {/*
       * Cell 2 — Detractors (losers only).
       *
       * WHY contributors={[]}: mirror of Cell 1. The contributors section shows
       * dash rows while the detractors section shows real data. The header still
       * reads "Top Movers" — which is intentionally generic to avoid adding a
       * "Top Detractors Only" header variant to ContributorsStrip.
       */}
      <div className="flex-1 overflow-hidden" data-testid="cell-detractors">
        <ContributorsStrip contributors={[]} detractors={detractors} />
      </div>

      {/*
       * Cell 3 — Recent Activity.
       *
       * WHY portfolioId | null: RecentActivityStrip accepts `string | null | undefined`
       * so it can render a safe null state when no portfolio is selected. Here
       * portfolioId is guaranteed to be a string (required prop), but passing it
       * directly still satisfies RecentActivityStrip's wider type contract.
       */}
      <div className="flex-1 overflow-hidden" data-testid="cell-recent-activity">
        <RecentActivityStrip portfolioId={portfolioId} />
      </div>
    </div>
  );
}
