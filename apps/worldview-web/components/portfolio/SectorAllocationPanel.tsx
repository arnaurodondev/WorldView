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
 * PLAN-0059 H-3 (2026-05-02): Migrated off recharts `Treemap` component to the
 * new hand-rolled `SquarifiedTreemap` component (components/ui/squarified-treemap.tsx)
 * which uses the Bruls/Huijsen/van Wijk squarified algorithm from lib/treemap.ts.
 * WHY: recharts was the last remaining consumer of the library in worldview-web.
 * Removing it eliminates ~140KB gz from the main bundle. The squarified layout
 * also produces better aspect-ratio tiles than recharts' algorithm for financial
 * sector data (closer to 1:1 instead of the sliver problem at ~1% allocations).
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx — Holdings tab, below the table
 * DATA SOURCE: Computed from SemanticHoldingsTable props (sectors + values)
 * DESIGN REFERENCE: PRD-0031 §8.3 Sector Allocation, Wave 4
 */

"use client";
// WHY "use client": uses useState for the treemap/bars view toggle.

import { useMemo, useState } from "react";
// SquarifiedTreemap: hand-rolled Bruls/Huijsen/van Wijk layout component
// (replaces recharts Treemap — see file-level comment above)
import { SquarifiedTreemap, type SquarifiedTreemapItem } from "@/components/ui/squarified-treemap";

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
        // while the holdings table used h-[20px], producing a subtle
        // misalignment when the user scrolled from one panel to the next.
        // Picking 22px keeps the visual rhythm consistent across the
        // whole Holdings tab — same 22px row everywhere is the easier
        // pattern for the eye to scan.
        // WHY space-y-px (was 0.5): with the taller row we tighten the
        // gap so 12 sectors still fit in roughly the same footprint.
        <div className="space-y-px">
          {items.map((item) => (
            // F-P-005: h-[20px] matches the holdings table row height so
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
            <div key={item.label} className="flex items-center gap-1.5 h-[20px]">
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

/**
 * SectorTreemapTile — renders the content inside each squarified treemap cell.
 *
 * WHY a separate component (not inline renderTile): isolating the tile logic
 * keeps SectorTreemap's JSX readable and allows testing the tile rendering
 * independently.
 *
 * Label visibility heuristics — derived from real-world tile rendering:
 *   - <60px cell width  → no label (sliver — too narrow for any text)
 *   - <100px cell width → name only (one line; pct would crowd it)
 *   - ≥100px wide + ≥36px tall → name + pct stacked (full information)
 *
 * The return label (e.g. "+1.23% today") is appended to the pct line when
 * `dailyReturnPct` is non-null, matching the Bloomberg-style "sector tile"
 * convention where colour alone isn't enough for accessibility.
 */
function SectorTreemapTile({
  cellWidth,
  cellHeight,
  item,
}: {
  cellWidth: number;
  cellHeight: number;
  item: SectorAllocationItem;
}) {
  const fill = sectorTileColor(item.dailyReturnPct);
  const showLabel = cellWidth >= 60 && cellHeight >= 24;
  const showPct = cellWidth >= 100 && cellHeight >= 36;

  const returnLabel =
    item.dailyReturnPct == null
      ? null
      : `${item.dailyReturnPct >= 0 ? "+" : ""}${item.dailyReturnPct.toFixed(2)}%`;

  // WHY title attribute on the outer div: provides a browser-native tooltip
  // on hover, surfacing full sector name + pct + return for narrow tiles
  // where labels are hidden. CSS tooltip would require extra markup; the
  // native title is zero-cost and works everywhere.
  const tooltipText = `${item.label} — ${item.pct.toFixed(1)}% of portfolio${
    returnLabel ? ` · ${returnLabel} today` : ""
  }`;

  return (
    // WHY h-full w-full: the parent SquarifiedTreemap positions each cell
    // absolutely with exact pixel dimensions — the tile must fill its slot.
    <div
      className="relative h-full w-full overflow-hidden rounded-[1px]"
      style={{
        backgroundColor: fill,
        // 1px background-colour border between adjacent tiles so the
        // layout grid is legible even when colours are very close.
        boxShadow: "inset 0 0 0 1px hsl(var(--background))",
      }}
      title={tooltipText}
    >
      {showLabel && (
        // WHY font-mono: all financial data should use tabular-nums / mono
        // so the user can scan across tiles at a glance without the variable-
        // width text breaking the visual rhythm.
        <span
          className="absolute left-[5px] top-[5px] block max-w-full overflow-hidden text-ellipsis whitespace-nowrap font-mono text-[10px] font-semibold leading-tight text-foreground"
          style={{ pointerEvents: "none" }}
        >
          {item.label}
        </span>
      )}
      {showPct && (
        <span
          className="absolute left-[5px] top-[19px] block font-mono text-[9px] tabular-nums text-muted-foreground"
          style={{ pointerEvents: "none" }}
        >
          {/* WHY toFixed(1): one decimal place matches Bloomberg PORT's
              allocation display — enough precision without crowding. */}
          {item.pct.toFixed(1)}%{returnLabel ? ` · ${returnLabel}` : ""}
        </span>
      )}
    </div>
  );
}

/**
 * SectorTreemap — squarified treemap of portfolio sector allocation.
 *
 * PLAN-0059 H-3: uses SquarifiedTreemap (lib/treemap.ts Bruls/Huijsen/van Wijk
 * algorithm) instead of recharts Treemap. The squarified algorithm packs cells
 * to aspect ratio ≈1, so even a 1% sector still gets a recognisable tile
 * (instead of the recharts sliver problem at low allocations).
 *
 * WHY `useMemo` on items: SquarifiedTreemap memoises the squarify result by
 * reference equality of `items`. Without useMemo, a fresh array is passed on
 * every parent render and the treemap re-runs the layout on every keystroke
 * in the view-toggle row above.
 */
function SectorTreemap({ items }: { items: SectorAllocationItem[] }) {
  // Map our domain type to SquarifiedTreemapItem — `weight` drives the cell
  // area proportionally; `payload` carries the full item for the tile renderer.
  const treemapItems: SquarifiedTreemapItem<SectorAllocationItem>[] = useMemo(
    () =>
      items.map((it) => ({
        id: it.label, // stable key — sector names don't change within a render
        weight: it.pct, // tile area ∝ % of portfolio
        payload: it,
      })),
    [items],
  );

  return (
    // WHY h-[220px]: matches the prior recharts height exactly so the
    // Holdings tab layout doesn't shift when the component re-renders.
    // WHY data-testid="sector-treemap": existing portfolio tests target
    // this attribute — must be preserved (R19 never delete tests).
    <div className="h-[220px] w-full" data-testid="sector-treemap">
      <SquarifiedTreemap<SectorAllocationItem>
        items={treemapItems}
        gap={2}
        minWidth={32}
        minHeight={20}
        ariaLabel="Sector allocation treemap"
        renderTile={(cell) => (
          <SectorTreemapTile
            cellWidth={cell.width}
            cellHeight={cell.height}
            item={cell.item.payload}
          />
        )}
      />
    </div>
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
