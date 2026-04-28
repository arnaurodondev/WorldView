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
import { formatPercent } from "@/lib/utils";

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
        // WHY space-y-0.5 (was 1.5): each row is now ~18px tall (h-[18px] +
        // 2px gap) — matches the 22px data-row height the rest of the
        // terminal uses, minus the table border, so 12 sectors fit in
        // ~220px instead of ~330px. Density wins.
        <div className="space-y-0.5">
          {items.map((item) => (
            // WHY h-[18px]: aligns with the ALLOCATION row rhythm; tall
            // enough that the 4px bar centers cleanly without crowding.
            <div key={item.label} className="flex items-center gap-1.5 h-[18px]">
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
                  table's WEIGHT column bars (h-[3px]). */}
              <div className="flex-1 h-[4px] bg-border/40 rounded-[1px] overflow-hidden">
                {/* WHY bg-primary/40: use semantic primary at 40% opacity —
                    bars represent capital allocation (not loss/gain), so neutral
                    but still branded. bg-primary would imply interactivity. */}
                <div
                  className="h-full bg-primary/40 rounded-[1px]"
                  style={{ width: `${Math.min(item.pct, 100)}%` }}
                />
              </div>

              {/* Percentage label — tabular-nums keeps the column flush
                  regardless of digit count (e.g. 5.0% / 33.3% align at the
                  decimal). */}
              <span className="w-10 shrink-0 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
                {formatPercent(item.pct / 100)}
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
    <div className="border-t border-border pt-2 mt-2">
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
