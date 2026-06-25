/**
 * components/screener/ScreenerTableSkeleton.tsx — shape-matched loading skeleton
 * for the screener AG Grid (Round 3 enhancement sprint, item 4).
 *
 * WHY THIS EXISTS: the screener's loading state used to be a centered spinner
 * (route-level loading.tsx) and a blank grid (in-page isLoading). Both violate
 * the design-system skeleton rule: loading states must preview the SHAPE of the
 * content they replace so the layout doesn't jump when data lands. This
 * component renders:
 *
 *   - one header band  (20px tall — matches headerHeight={20} on the grid)
 *   - N data-row bands (20px pitch — matches rowHeight={20} on the grid)
 *   - per-column shimmer bars sized from SCREENER_AG_COL_WIDTHS, so the
 *     skeleton is COLUMN-SHAPED, not a generic full-width stripe stack.
 *
 * WHY 20px (not the §15.10 22px token): the screener is the ONE surface locked
 * to 20px rows by the T-IA-14 architecture guard
 * (__tests__/architecture/screener-row-height.test.ts) — 22px would drop it
 * below the "≥240 cells above the fold at 1440×900" acceptance gate. The
 * skeleton pitch MUST mirror the real grid pitch or the swap-in visibly jumps.
 *
 * WHY NO "use client": pure presentational markup — no hooks, no events — so
 * the same component serves both the route-level Suspense fallback
 * (app/(app)/screener/loading.tsx, a Server Component) and the client page's
 * in-query loading overlay.
 *
 * WHO USES IT:
 *   - app/(app)/screener/loading.tsx (route segment fallback)
 *   - app/(app)/screener/page.tsx    (overlay while the first query is in flight)
 */

import { cn } from "@/lib/utils";
import { SCREENER_AG_COL_WIDTHS } from "@/components/screener/ag-screener-columns";

// ── Skeleton column model ─────────────────────────────────────────────────────

/**
 * SKELETON_COLUMNS — the default-visible column layout the skeleton previews.
 *
 * WHY a hand-picked list (not deriving from loadColumnPrefs): the skeleton must
 * render on the SERVER (loading.tsx) where localStorage prefs don't exist. The
 * default-visible set is stable (pinned by lib/__tests__/screener-columns.test
 * "14 default-visible" assertions), so mirroring it statically is safe — and
 * widths still come from SCREENER_AG_COL_WIDTHS so a column-width change in the
 * real ColDef factory automatically reshapes the skeleton.
 *
 * `numeric` mirrors NUMERIC_COL_IDS membership: numeric columns right-align
 * their shimmer bar exactly like the real right-aligned cells, so the skeleton
 * reads as the same table, only blurred.
 */
const SKELETON_COLUMNS: ReadonlyArray<{ key: string; numeric: boolean }> = [
  { key: "ticker", numeric: false },
  { key: "name", numeric: false },
  { key: "sector", numeric: false },
  { key: "price", numeric: true },
  { key: "change", numeric: true },
  { key: "marketCap", numeric: true },
  { key: "pe", numeric: true },
  { key: "revenue", numeric: true },
  { key: "beta", numeric: true },
  { key: "news7d", numeric: true },
  { key: "briefScore", numeric: true },
  { key: "score", numeric: true },
  { key: "range52w", numeric: true },
  { key: "volume", numeric: true },
  { key: "sparkline", numeric: false },
];

// ── Props ─────────────────────────────────────────────────────────────────────

export interface ScreenerTableSkeletonProps {
  /**
   * Number of 20px data-row bands to render. Default 16 (~320px of rows —
   * enough to fill the visible grid area on a 900px-tall viewport without
   * rendering hundreds of useless DOM nodes).
   */
  rows?: number;
  /** Extra classes on the outer wrapper (e.g. positioning from the page). */
  className?: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ScreenerTableSkeleton({ rows = 16, className }: ScreenerTableSkeletonProps) {
  return (
    <div
      // WHY role="status" + aria-label: screen-reader users get one polite
      // "loading" announcement instead of a wall of unlabeled decorative divs.
      role="status"
      aria-label="Loading screener results"
      data-testid="screener-table-skeleton"
      // ROUND-4 (item 4 — DS §6.2 sweep): the wrapper previously carried
      // Tailwind's raw `animate-pulse`, which §6.2 BANS for skeletons
      // (fast consumer-app pulse + bypasses the reduced-motion semantics
      // maintained in globals.css). The skeleton is now STATIC, the §6.2
      // default tier — Bloomberg-style terminals use static loading bars;
      // finance users read animation as "something is streaming".
      // WHY NOT the `animate-skeleton-pulse` opt-in: that tier is reserved
      // for loads expected to exceed 2s (e.g. AI generation). The screener's
      // cold query is a paginated 50-row fundamentals scan that returns in
      // well under a second on the live stack (p95 FTS-era measurements put
      // comparable S9 reads <100ms) — nowhere near the 2s bar, so the
      // static default applies. Decision documented per the Round-4 spec.
      // overflow-hidden clips the fixed-width column row on narrow viewports
      // exactly like the real grid's horizontal overflow.
      className={cn("overflow-hidden bg-background", className)}
    >
      {/* ── Header band — mirrors headerHeight={20} + --ag-header-background ── */}
      <div
        data-testid="skeleton-header-row"
        className="flex h-5 items-center border-b border-border bg-card"
      >
        {SKELETON_COLUMNS.map((col) => (
          <div
            key={col.key}
            style={{ width: SCREENER_AG_COL_WIDTHS[col.key] }}
            className={cn(
              "flex h-full shrink-0 items-center px-1.5",
              col.numeric && "justify-end",
            )}
          >
            {/* Header shimmer: shorter + dimmer than cell bars — header labels
                are 10px ALL-CAPS vs 11px cell values in the real grid. */}
            <div className="h-1.5 w-3/5 rounded-[1px] bg-muted-foreground/20" />
          </div>
        ))}
      </div>

      {/* ── Data-row bands — 20px pitch (h-5 = 20px exactly) ──────────────── */}
      {Array.from({ length: rows }, (_, i) => (
        <div
          // WHY index keys are fine here: the list is static per render —
          // skeleton rows are never reordered/removed individually.
          key={i}
          data-testid="skeleton-data-row"
          className="flex h-5 items-center border-b border-border/40"
        >
          {SKELETON_COLUMNS.map((col) => (
            <div
              key={col.key}
              style={{ width: SCREENER_AG_COL_WIDTHS[col.key] }}
              className={cn(
                "flex h-full shrink-0 items-center px-1.5",
                col.numeric && "justify-end",
              )}
            >
              {/* WHY varying widths (4/5 vs 3/5 by parity): a uniform grid of
                  identical bars reads as a pattern, not as "rows of data".
                  Alternating bar lengths is the cheapest way to suggest real,
                  variable-length values. */}
              <div
                className={cn(
                  "h-2 rounded-[1px] bg-muted",
                  i % 2 === 0 ? "w-4/5" : "w-3/5",
                )}
              />
            </div>
          ))}
        </div>
      ))}

      {/* Visually-hidden text fallback for assistive tech. */}
      <span className="sr-only">Loading…</span>
    </div>
  );
}
