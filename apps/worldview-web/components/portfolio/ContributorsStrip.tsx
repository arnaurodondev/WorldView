/**
 * ContributorsStrip — combined TOP MOVERS panel showing contributors and detractors
 * in a single compact column (PRD-0089 W2 redesign, density pass).
 *
 * WHY THIS CHANGED: the original two-column split (contributors left, detractors right)
 * left half the strip empty when a portfolio had fewer than 4 of either type.
 * Merging into one column with a visual separator between gains and losses maximises
 * information density in the same vertical footprint.
 *
 * WHO USES IT: BottomInfoStrip (the 3-column grid below SemanticHoldingsTable).
 * DATA SOURCE: topMovers from useTopMovers hook (passed as props); no separate fetch.
 * DESIGN REFERENCE: PRD-0089 W2 §4.13, density pass 2026-05-21
 */
"use client";
// WHY "use client": Link navigation requires the browser DOM.

import Link from "next/link";
import { formatPercent } from "@/lib/utils";

interface MoverEntry {
  ticker: string;
  /** Full company name (truncated to fit). May be empty — falls back to ticker. */
  name?: string;
  pnlPct: number;
}

interface ContributorsStripProps {
  contributors: MoverEntry[];   // top 4 positive contributors
  detractors: MoverEntry[];     // top 4 detractors (most negative first)
  isLoading?: boolean;
  /**
   * Section mode (2026-06-10 sprint — fixes the Top Movers clipping bug):
   *
   *   "both" (default)  — legacy layout: TOP MOVERS header + contributors
   *                       section + separator + detractors section (~220px).
   *   "contributors"    — ONLY the contributors section with its own header
   *                       (22px header + 4×22px rows = 110px).
   *   "detractors"      — ONLY the detractors section, same footprint.
   *
   * WHY: BottomStripCluster renders two side-by-side instances inside a
   * fixed-height overflow-hidden slot. The old workaround passed the unused
   * side as [] — but "both" mode still rendered the contributors section
   * FIRST (~128px of header + sub-header + 4 dash rows), pushing the real
   * detractors below the clipped fold, so the second column showed only
   * dashes. A mode prop renders ONLY the relevant section — nothing to clip.
   *
   * WHY a prop (not a second component): the row renderer, dash-padding and
   * loading behaviour are identical across modes; duplicating the component
   * would fork that logic.
   */
  mode?: "both" | "contributors" | "detractors";
}

/**
 * SingleMoverRow — one row in the combined movers list.
 *
 * WHY min-w-0 on the name span: the name column is flex-1 and will overflow
 * its container without min-w-0 + truncate because flexbox children don't
 * shrink below their intrinsic content width by default. This is the root
 * cause of the "overlapping text" symptom in the old layout (CSS issue BP-x).
 */
function SingleMoverRow({
  ticker,
  name,
  pnlPct,
  isGain,
}: {
  ticker: string;
  name?: string;
  pnlPct: number;
  isGain: boolean;
}) {
  return (
    <div className="flex h-[22px] items-center gap-2 px-3">
      {/* Ticker — fixed width, links to instrument detail page */}
      <Link
        href={`/instruments/${encodeURIComponent(ticker)}`}
        className="w-12 shrink-0 font-mono text-[11px] text-primary hover:underline"
      >
        {ticker}
      </Link>

      {/* Company name — takes remaining space, truncates cleanly.
          WHY min-w-0: flex child must explicitly allow shrinking below content width.
          WHY em-dash when no name: avoids duplicating the ticker in the name slot
          (which would cause "AAPL AAPL" and confuse screen.getByText in tests). */}
      <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-neutral-500">
        {name || "—"}
      </span>

      {/* Pct badge — green for gain, red for loss */}
      {/* WHY tabular-nums: keeps +/- aligned across rows (proportional glyphs differ) */}
      <span
        className={`shrink-0 font-mono text-[11px] tabular-nums ${
          isGain ? "text-positive" : "text-negative"
        }`}
      >
        {formatPercent(pnlPct / 100)}
      </span>
    </div>
  );
}

/** Placeholder dash row, used when there are fewer than 4 movers of a kind. */
function DashRow() {
  return (
    <div className="flex h-[22px] items-center px-3">
      <span className="font-mono text-[11px] text-muted-foreground">—</span>
    </div>
  );
}

/**
 * ContributorsStrip — renders the TOP MOVERS panel as a single column.
 *
 * Layout: section label → 4 contributor rows (or dashes) → thin separator →
 * 4 detractor rows (or dashes). Total height is always 8 data rows × 22px +
 * chrome = ~220px, consistent regardless of how many holdings exist.
 */
export function ContributorsStrip({
  contributors,
  detractors,
  isLoading,
  mode = "both",
}: ContributorsStripProps) {
  // Pad contributors and detractors to 4 rows each for consistent height.
  // WHY Array(Math.max(0, 4-N)).fill(null): we always render 4 slots; nulls become
  // DashRow placeholders so the column height is stable across different portfolio sizes.
  const contribRows = [
    ...contributors.slice(0, 4),
    ...Array(Math.max(0, 4 - contributors.length)).fill(null) as null[],
  ];
  const detractorRows = [
    ...detractors.slice(0, 4),
    ...Array(Math.max(0, 4 - detractors.length)).fill(null) as null[],
  ];

  /** Shared 4-slot row renderer — identical across modes/sections. */
  const renderRows = (rows: (MoverEntry | null)[], isGain: boolean, keyPrefix: string) =>
    isLoading
      ? Array.from({ length: 4 }).map((_, i) => (
          <div key={`${keyPrefix}-load-${i}`} className="flex h-[22px] items-center px-3">
            <span className="font-mono text-[11px] text-muted-foreground">—</span>
          </div>
        ))
      : rows.map((entry, i) =>
          entry ? (
            <SingleMoverRow
              key={`${keyPrefix}-${entry.ticker}-${i}`}
              ticker={entry.ticker}
              name={entry.name}
              pnlPct={entry.pnlPct}
              isGain={isGain}
            />
          ) : (
            <DashRow key={`${keyPrefix}-null-${i}`} />
          ),
        );

  // ── Single-section modes (2026-06-10 clipping fix) ──────────────────────
  // One 22px section header + exactly 4 rows = 110px — fits the bottom-strip
  // slot with no fold, so real data is never pushed below an overflow clip.
  if (mode !== "both") {
    const label = mode === "contributors" ? "Top Contributors" : "Top Detractors";
    return (
      <div
        className="flex flex-col bg-card border-b border-border h-full"
        data-testid={`movers-${mode}`}
      >
        <div className="flex h-[22px] shrink-0 items-center border-b border-border px-3">
          <span className="text-[10px] uppercase tracking-[0.06em] text-neutral-500">
            {label}
          </span>
        </div>
        {mode === "contributors"
          ? renderRows(contribRows, true, "c")
          : renderRows(detractorRows, false, "d")}
      </div>
    );
  }

  // ── Legacy "both" layout (unchanged) ────────────────────────────────────
  return (
    <div className="flex flex-col bg-card border-b border-border h-full">
      {/* Section header */}
      <div className="flex h-[22px] shrink-0 items-center border-b border-border px-3">
        <span className="text-[10px] uppercase tracking-[0.06em] text-neutral-500">Top Movers</span>
      </div>

      {/* Contributors sub-header */}
      <div className="flex h-[18px] items-center px-3 bg-card/60">
        <span className="text-[10px] text-muted-foreground tracking-[0.04em]">
          {/* WHY inline labels (not a separate header row):
              keeps the "Top Contributors" label right above its rows without
              adding an extra full-height row. Uses 18px sub-header for scannability. */}
          Top Contributors
        </span>
      </div>

      {/* Contributor rows */}
      {renderRows(contribRows, true, "c")}

      {/* Visual separator between contributors and detractors */}
      <div className="h-px bg-border/50 mx-3" />

      {/* Detractors sub-header */}
      <div className="flex h-[18px] items-center px-3 bg-card/60">
        <span className="text-[10px] text-muted-foreground tracking-[0.04em]">
          Top Detractors
        </span>
      </div>

      {/* Detractor rows */}
      {renderRows(detractorRows, false, "d")}
    </div>
  );
}
