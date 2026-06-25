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
 *   width columns separated by vertical dividers. The 2026-06-10 sprint added
 *   a `mode` prop to ContributorsStrip ("contributors" | "detractors") so each
 *   cell renders ONLY its own section — see the clipping-fix note below.
 *
 * WHY h-[124px] (was h-24/96px — 2026-06-10 clipping fix): each movers cell is
 * a 22px header + 4×22px rows = 110px; the recent-activity cell is 22px header
 * + 5×20px rows = 122px. The old 96px slot + overflow-hidden clipped real data
 * — most visibly the detractors column, which (in the old "both" layout)
 * rendered the contributors section first and pushed every real detractor row
 * below the fold, so the column showed only dashes.
 *
 * WHY divide-x divide-border: shadcn/ui divide utilities produce a single 1px
 * vertical separator between each flex child. Using divide-x is more correct
 * than adding border-r to individual cells because it avoids a trailing border
 * on the last cell — which would double up with the parent container's border.
 *
 * Layout: h-[124px] flex flex-row divide-x divide-border
 *   ├── Cell 1 (flex-1) — ContributorsStrip mode="contributors"
 *   ├── Cell 2 (flex-1) — ContributorsStrip mode="detractors"
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
     * WHY h-[124px] (was h-24 / 96px — 2026-06-10 clipping fix): the cell
     * content is 110px (movers: 22px header + 4×22px rows) / 122px (recent
     * activity: 22px header + 5×20px rows). The old 96px slot clipped BOTH —
     * and combined with ContributorsStrip rendering the contributors section
     * first, the detractors cell showed only dash rows (the real data sat
     * below the fold). 124px fits the tallest cell with a 2px margin.
     *
     * WHY keep overflow-hidden: defensive — if a future child grows past the
     * slot, clipping is still better than shifting the layout below. The
     * mode-scoped cells (below) guarantee real data is never in the clipped
     * region anymore.
     *
     * WHY border-b border-border: a bottom border visually closes the strip and
     * separates it from whatever comes after (e.g. a footer or a tab panel edge).
     */
    <div
      className="flex h-[124px] w-full flex-row divide-x divide-border overflow-hidden border-b border-border"
      data-testid="bottom-strip-cluster"
    >
      {/*
       * Cell 1 — Contributors (winners only).
       *
       * 2026-06-10 clipping fix: mode="contributors" renders ONLY the
       * contributors section (own header + 4 rows, 110px). The previous
       * workaround passed detractors=[] but ContributorsStrip still rendered
       * the full two-section "TOP MOVERS" layout (~220px) — the unused
       * detractors dash-section consumed slot height for nothing.
       * detractors=[] is still passed because the prop is required; mode
       * makes it inert.
       */}
      <div className="flex-1 overflow-hidden" data-testid="cell-contributors">
        <ContributorsStrip mode="contributors" contributors={contributors} detractors={[]} />
      </div>

      {/*
       * Cell 2 — Detractors (losers only).
       *
       * 2026-06-10 clipping fix (the root-caused render bug): in "both" mode
       * the contributors section rendered FIRST (~128px of header + sub-header
       * + dash rows), pushing the REAL detractor rows below the clipped fold —
       * the column showed only dashes. mode="detractors" renders the
       * detractors section alone at the top of the cell: nothing to clip.
       */}
      <div className="flex-1 overflow-hidden" data-testid="cell-detractors">
        <ContributorsStrip mode="detractors" contributors={[]} detractors={detractors} />
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
