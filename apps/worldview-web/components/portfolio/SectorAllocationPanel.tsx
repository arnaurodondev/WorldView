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

import { useState } from "react";
import { Treemap, ResponsiveContainer } from "recharts";

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
  /**
   * PLAN-0053 T-D-4-04: optional weighted-avg daily return (%) for this bucket.
   * When provided, the treemap colours tiles on a teal-to-red gradient. When
   * omitted, tiles fall back to a neutral primary tint so the chart still
   * renders meaningfully on portfolios where return data isn't computed yet.
   */
  dailyReturnPct?: number | null;
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

// ── Treemap helpers ──────────────────────────────────────────────────────────

/**
 * sectorTileColor — gradient from negative red → neutral muted → positive teal.
 *
 * WHY a continuous gradient (not 3 hard buckets):
 *   A 0.05% gain shouldn't look identical to a 5% gain. Continuous mapping
 *   gives the user a meaningful read on intensity at a glance.
 *
 * The lerp clamp at ±5% is tuned to typical daily moves — anything beyond
 * is rare enough that capping it at the most-saturated colour is the right
 * UX (extreme outliers visually pop without dominating the palette).
 */
function sectorTileColor(returnPct: number | null | undefined): string {
  if (returnPct == null) {
    // Unknown / missing return — neutral tint so the tile still renders but
    // doesn't communicate a directional signal.
    return "hsl(var(--primary) / 0.35)";
  }
  // Clamp into the [-5, +5] band; outside that we saturate.
  const clamped = Math.max(-5, Math.min(5, returnPct));
  const intensity = Math.abs(clamped) / 5; // 0..1
  // Use the design tokens — positive (teal-green) for gains, negative (red)
  // for losses. Opacity ramps from 25% to 90% based on intensity so small
  // moves still read as "barely there" while big moves dominate.
  const alpha = 0.25 + intensity * 0.65;
  if (clamped >= 0) {
    return `hsl(var(--positive) / ${alpha.toFixed(2)})`;
  }
  return `hsl(var(--negative) / ${alpha.toFixed(2)})`;
}

interface TreemapTileData {
  name: string;
  size: number;
  pct: number;
  dailyReturnPct: number | null | undefined;
}

/**
 * SectorTreemap — recharts-based treemap visualisation.
 *
 * WHY recharts (not d3-treemap directly): the codebase already pulls
 * recharts for the BarChart and equity-curve components — adding a second
 * tree-laying lib would be redundant weight. Recharts' Treemap is built on
 * d3-hierarchy under the hood and gives us the tile geometry for free.
 *
 * WHY a custom content renderer: the default content shows recharts' built-in
 * tile labels which don't render the dual percent + sector pattern well
 * inside small tiles. A custom shape lets us drop labels gracefully on
 * narrow tiles (≤80px wide) while keeping them on the larger ones.
 */
function SectorTreemap({ items }: { items: SectorAllocationItem[] }) {
  // recharts Treemap consumes `dataKey="size"` so we map our shape into
  // {name, size, pct, dailyReturnPct} — keeping pct + return on the node
  // so the custom tile renderer can colour and label without extra prop
  // drilling.
  const treemapData: TreemapTileData[] = items.map((it) => ({
    name: it.label,
    size: it.pct, // tile area driven by % of portfolio
    pct: it.pct,
    dailyReturnPct: it.dailyReturnPct,
  }));

  return (
    <div className="h-[220px] w-full" data-testid="sector-treemap">
      <ResponsiveContainer width="100%" height="100%">
        <Treemap
          data={treemapData}
          dataKey="size"
          stroke="hsl(var(--background))"
          // The default fill is overridden by our content renderer; setting
          // it here is a fallback for any rendering edge case.
          fill="hsl(var(--primary) / 0.4)"
          isAnimationActive={false}
          content={<TreemapTile />}
        />
      </ResponsiveContainer>
    </div>
  );
}

/**
 * TreemapTile — custom tile renderer for the recharts Treemap.
 *
 * WHY custom: the default tile content renders the name centred but ignores
 * tile size, so 1% slivers get a label that overflows. We branch on width
 * to either show name+pct, name only, or no label — the user can always
 * hover to see the full info.
 */
// recharts injects geometry props at runtime; types are declared loose to
// stay decoupled from internal recharts shapes.
interface TreemapTileProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  name?: string;
  pct?: number;
  dailyReturnPct?: number | null;
}
function TreemapTile(props: TreemapTileProps) {
  const { x = 0, y = 0, width = 0, height = 0, name, pct, dailyReturnPct } = props;
  const fill = sectorTileColor(dailyReturnPct);

  // Label visibility heuristics — derived from real-world tile rendering:
  //   - <60px width → no label (sliver)
  //   - <100px width → name only (one line)
  //   - otherwise → name + pct stacked
  const showLabel = width >= 60 && height >= 24;
  const showPct = width >= 100 && height >= 36;

  // Defensive: pct may be undefined on the synthetic root node injected by
  // recharts. Treat it as 0 for the label.
  const safePct = pct ?? 0;
  const safeName = name ?? "";
  const returnLabel =
    dailyReturnPct == null
      ? null
      : `${dailyReturnPct >= 0 ? "+" : ""}${dailyReturnPct.toFixed(2)}%`;

  return (
    <g>
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        fill={fill}
        stroke="hsl(var(--background))"
        strokeWidth={1}
      >
        <title>
          {`${safeName} — ${safePct.toFixed(1)}% of portfolio${
            returnLabel ? ` · ${returnLabel} today` : ""
          }`}
        </title>
      </rect>
      {showLabel && (
        <text
          x={x + 6}
          y={y + 14}
          fill="hsl(var(--foreground))"
          fontSize={10}
          fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
          fontWeight={600}
          // pointer-events:none so the title-tooltip on the rect still
          // surfaces even when the cursor is over the label text.
          style={{ pointerEvents: "none" }}
        >
          {safeName}
        </text>
      )}
      {showPct && (
        <text
          x={x + 6}
          y={y + 28}
          fill="hsl(var(--muted-foreground))"
          fontSize={9}
          fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
          style={{ pointerEvents: "none" }}
        >
          {safePct.toFixed(1)}%
          {returnLabel ? ` · ${returnLabel}` : ""}
        </text>
      )}
    </g>
  );
}

// ── SectorAllocationPanel ─────────────────────────────────────────────────────

export function SectorAllocationPanel({
  bySector,
  byType,
}: SectorAllocationPanelProps) {
  // PLAN-0053 T-D-4-04: view toggle between the legacy two-bar layout and
  // the new treemap. Default to "treemap" so users get the upgraded
  // experience by default — the toggle preserves the bar view for users
  // who prefer the old quantitative read (or are colour-blind on the
  // gradient — though the title-tooltip still surfaces the data).
  const [view, setView] = useState<"treemap" | "bars">("treemap");

  // WHY don't render the panel at all when no data: the Holdings tab already
  // shows an InlineEmptyState for 0 holdings; this panel is secondary chrome
  // that only makes sense when there's data to visualise.
  if (bySector.length === 0 && byType.length === 0) {
    return null;
  }

  return (
    // WHY border-t: visually separates the allocation section from the holdings table
    // above it, without needing a full card/panel wrapper.
    // F-P-023 (PLAN-0051 W6): ``border-border/60`` — soft intra-tab
    // divider; the holdings table and the allocation panel sit inside
    // the same Holdings tab so the divider should be subtle, not the
    // hard between-panel ``border-border`` line we use above the KPI
    // strip.
    <div className="border-t border-border/60 pt-2 mt-2">
      {/* Section label + view toggle */}
      <div className="mb-2 flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          ALLOCATION
        </div>
        <div className="flex gap-px">
          {(["treemap", "bars"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={cn(
                "px-1.5 text-[9px] font-mono uppercase transition-colors",
                view === v
                  ? "bg-primary/20 text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
              aria-pressed={view === v}
            >
              {v}
            </button>
          ))}
        </div>
      </div>

      {view === "treemap" ? (
        // WHY only show the sector treemap (not by-type as treemap too):
        // sector concentration is the canonical risk read; asset-type tends
        // to be a binary "mostly equity" answer that doesn't gain from a
        // treemap. Keeping the by-type bar visible alongside preserves the
        // signal at minimal screen cost.
        <div className="space-y-2">
          <SectorTreemap items={bySector} />
          {byType.length > 0 && (
            <div className="border-t border-border/40 pt-2">
              <BarChart items={byType} title="BY TYPE" />
            </div>
          )}
        </div>
      ) : (
        // Legacy two-bar layout — preserved for users who toggle off the
        // treemap view.
        <div className={cn("flex gap-4")}>
          <BarChart items={bySector} title="BY SECTOR" />
          <BarChart items={byType} title="BY TYPE" />
        </div>
      )}
    </div>
  );
}
