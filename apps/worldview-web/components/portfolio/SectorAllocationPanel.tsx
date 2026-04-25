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
      {/* Chart title — ALL CAPS per terminal typography rules */}
      <div className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground mb-2">
        {title}
      </div>

      {items.length === 0 ? (
        <InlineEmptyState message="Sector data loading from fundamentals..." />
      ) : (
        <div className="space-y-1.5">
          {items.map((item) => (
            <div key={item.label} className="flex items-center gap-2">
              {/* Label — truncated to prevent overflow */}
              <span className="w-32 shrink-0 text-[10px] text-muted-foreground truncate">
                {item.label}
              </span>

              {/* Bar track + fill */}
              <div className="flex-1 h-[6px] bg-border/40 rounded-[1px] overflow-hidden">
                {/* WHY bg-positive/30: use semantic positive color at 30% opacity —
                    bars represent capital allocation (not loss/gain), so neutral
                    but still branded. bg-primary would imply interactivity. */}
                <div
                  className="h-full bg-primary/40 rounded-[1px]"
                  style={{ width: `${Math.min(item.pct, 100)}%` }}
                />
              </div>

              {/* Percentage label */}
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
    <div className="border-t border-border pt-3 mt-3">
      {/* Section label */}
      <div className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground mb-3">
        ALLOCATION
      </div>

      {/* Two charts side-by-side */}
      <div className={cn("flex gap-6")}>
        <BarChart items={bySector} title="BY SECTOR" />
        <BarChart items={byType} title="BY TYPE" />
      </div>
    </div>
  );
}
