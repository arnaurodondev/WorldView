/**
 * components/portfolio/SectorAllocationPanel.tsx — Sector/type allocation bar charts
 *
 * WHY THIS EXISTS: Concentration risk is one of the most important portfolio metrics.
 * A sector bar chart lets the trader instantly see if they're overexposed to one
 * sector (e.g., 60% tech) without computing it from the holdings table manually.
 *
 * WHY horizontal bars (not pie): Pie charts require angle estimation, which humans
 * do poorly. Horizontal bars with percentage labels are easier to compare precisely
 * at a glance — preferred in professional financial UX (Bloomberg, Refinitiv).
 *
 * WHY two charts side-by-side (sector + type): Sector gives GICS-level view;
 * asset type (equity/ETF/cash) gives instrument-class view. Both together answer
 * "what kind of risk am I running?"
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx — Holdings tab, below the table
 * DATA SOURCE: Computed from SemanticHoldingsTable props (sectors + values)
 * DESIGN REFERENCE: PRD-0031 §8.3 Sector Allocation, Wave 4
 */

"use client";

import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { cn } from "@/lib/utils";
// F-307 fix (PLAN-0048 QA iter-1): allocation shares are NOT directional
// (a sector representing 100% of a portfolio has not "gained 100%"). Using
// formatPercent (which prepends "+") produced the visible category error
// "Equity +100.00%". Switch to formatPercentUnsigned for share displays.
import { formatPercentUnsigned } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface SectorAllocationItem {
  /** GICS sector name or asset type (e.g., "Information Technology", "Equity") */
  label: string;
  /** Total market value in this bucket */
  value: number;
  /** % of total portfolio value [0, 100] */
  pct: number;
}

export interface SectorAllocationPanelProps {
  /** By GICS sector — computed from fundamentals */
  bySector: SectorAllocationItem[];
  /** By asset type — computed from holding type or exchange */
  byType: SectorAllocationItem[];
}

// ── BarChart ──────────────────────────────────────────────────────────────────

/**
 * BarChart — compact horizontal bar chart for allocation data
 *
 * WHY no third-party chart library: recharts/victory would add ~50KB to the bundle
 * for 6 simple bars. CSS `width: pct%` achieves the same output with zero overhead.
 */
function BarChart({
  items,
  title,
}: {
  items: SectorAllocationItem[];
  title: string;
}) {
  return (
    <div className="flex-1 min-w-0">
      {/* Chart title — ALL CAPS per terminal typography rules.
          WHY mb-1 (not mb-2): tighter density, matches the Bloomberg PORT
          allocation panel and the Risk strip header rhythm. The 4px gap
          between the label and the first bar still reads as separation
          without wasting vertical space. */}
      <div className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground mb-1">
        {title}
      </div>

      {items.length === 0 ? (
        <InlineEmptyState message="Sector data loading from fundamentals..." />
      ) : (
        // F-P-005 (PLAN-0051 W6): row height now matches the holdings
        // table exactly (22px). Pre-fix the allocation rows were h-[18px]
        // while the holdings table used h-[22px], producing a subtle
        // misalignment when the user scrolled from one panel to the next.
        // Picking 22px keeps the visual rhythm consistent across the
        // whole Holdings tab — same 22px row everywhere is the easier
        // pattern for the eye to scan.
        // WHY space-y-px (was 0.5): with the taller row we tighten the
        // gap so 12 sectors still fit in roughly the same footprint.
        <div className="space-y-px">
          {items.map((item) => (
            // F-P-005: h-[22px] matches the holdings table row height so
            // panels read as one unified rhythm. The 4px bar still
            // centers cleanly inside the taller row.
            //
            // F-P-013 (PLAN-0051 W6): React key is the bucket LABEL
            // (e.g. "Information Technology"), NOT the array index. WHY:
            // when allocations re-sort (largest first) on quote refresh,
            // index keys would force React to re-render every row and
            // the bars would briefly flicker as their widths re-animate.
            // Label is the natural stable identifier — a sector either
            // exists in the bucket list or it doesn't; its slot is fixed.
            <div key={item.label} className="flex items-center gap-1.5 h-[22px]">
              {/* Label — truncated to prevent overflow.
                  WHY w-28 (was w-32): saves 16px on the left so the bar
                  stretches further. Sector names like "Information
                  Technology" still fit at 11ch via truncation. */}
              <span className="w-28 shrink-0 text-[10px] text-muted-foreground truncate">
                {item.label}
              </span>

              {/* Bar track + fill.
                  WHY h-[4px] (was 6px): thinner bar reads as "data marker"
                  not "panel chrome" — same visual weight as the holdings
                  table's WEIGHT column bars (h-[3px]).
                  F-P-014 (PLAN-0051 W6): a11y. The bar by itself communicates
                  proportion via length only; assistive tech reading the row
                  needs an explicit label. ``role="img"`` + ``aria-label``
                  surfaces the bucket name and percentage to screen readers.
                  WHY also a CSS pattern fill on the inner bar: users with
                  colour-vision deficiency (deuteranopia ≈ 8% of men) struggle
                  to discriminate the primary/40 yellow tint against the muted
                  track. The diagonal-stripe pattern provides a non-colour
                  cue (pattern-vs-solid) that still reads correctly in
                  greyscale or under any hue rotation. */}
              <div
                className="flex-1 h-[4px] bg-border/40 rounded-[1px] overflow-hidden"
                role="img"
                aria-label={`Sector ${item.label}: ${item.pct.toFixed(1)}%`}
              >
                {/* WHY bg-primary/40: use semantic primary at 40% opacity —
                    bars represent capital allocation (not loss/gain), so neutral
                    but still branded. bg-primary would imply interactivity.
                    F-P-014: the inline ``backgroundImage`` adds a subtle
                    diagonal-stripe overlay so the bar is recognisable by
                    PATTERN as well as colour. The rgba is computed from the
                    primary token at low opacity so it composes cleanly on
                    the bg-primary/40 base. */}
                <div
                  className="h-full bg-primary/40 rounded-[1px]"
                  style={{
                    width: `${Math.min(item.pct, 100)}%`,
                    backgroundImage:
                      "repeating-linear-gradient(45deg, transparent 0px, transparent 3px, rgba(255,255,255,0.08) 3px, rgba(255,255,255,0.08) 4px)",
                  }}
                />
              </div>

              {/* Percentage label — tabular-nums keeps the column flush
                  regardless of digit count (e.g. 5.0% / 33.3% align at the
                  decimal). */}
              <span className="w-10 shrink-0 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
                {/* No "+" prefix — shares are non-directional (F-307). */}
                {formatPercentUnsigned(item.pct / 100)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── SectorAllocationPanel ─────────────────────────────────────────────────────

export function SectorAllocationPanel({
  bySector,
  byType,
}: SectorAllocationPanelProps) {
  // WHY don't render the panel at all when no data: the Holdings tab already
  // shows an InlineEmptyState for 0 holdings; this panel is secondary chrome
  // that only makes sense when there's data to visualise.
  if (bySector.length === 0 && byType.length === 0) {
    return null;
  }

  return (
    // WHY border-t: visually separates the allocation section from the holdings table
    // above it, without needing a full card/panel wrapper.
    // WHY pt-2 mt-2 (was pt-3 mt-3): terminal density — 8px gap above and
    // 8px padding inside is enough breathing room without the section
    // feeling like a separate card. Matches the rhythm of the rest of the
    // page where every gap is 8/12px, never 24px.
    // F-P-023 (PLAN-0051 W6): ``border-border/60`` — soft intra-tab
    // divider; the holdings table and the allocation panel sit inside
    // the same Holdings tab so the divider should be subtle, not the
    // hard between-panel ``border-border`` line we use above the KPI
    // strip.
    <div className="border-t border-border/60 pt-2 mt-2">
      {/* Section label.
          WHY mb-2 (was mb-3): tighter so the two BarCharts start closer to
          their parent label — the visual hierarchy still reads clearly
          because the BarChart's own "BY SECTOR" sub-label has its own mb-1. */}
      <div className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground mb-2">
        ALLOCATION
      </div>

      {/* Two charts side-by-side.
          WHY gap-4 (was gap-6): 16px column gap is plenty of separation at
          terminal density. 24px was leaving a noticeable empty band that
          made the panel feel half-empty. */}
      <div className={cn("flex gap-4")}>
        <BarChart items={bySector} title="BY SECTOR" />
        <BarChart items={byType} title="BY TYPE" />
      </div>
    </div>
  );
}
