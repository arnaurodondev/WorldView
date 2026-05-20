/**
 * components/instrument/graph/GraphControls.tsx — Filter controls for the entity graph
 *
 * WHY EXTRACTED: The filter controls row (relation-type pills, edge-strength slider,
 * node search input, layout switcher) was embedded in EntityGraph.tsx. Extracting it
 * keeps EntityGraph.tsx under 400 lines and makes controls independently readable.
 *
 * PLAN-0059 Wave H-4: Added interactive filter controls:
 *   - Filter pills (by relationship category: all/executive/investor/supplier/customer/competitor)
 *   - Edge-strength slider (min weight threshold 0–100%)
 *   - Node search input (dims non-matching nodes in sigma via nodeReducer)
 *   - Layout switcher (force = ForceAtlas2, hierarchical = degree-tier layout)
 *
 * WHO USES IT: EntityGraph.tsx — never directly by pages.
 */

"use client";
// WHY "use client": uses event handlers and interactive state callbacks.

import { TrendingUp, Network } from "lucide-react";
import { Slider } from "@/components/ui/slider";

// ── Types ─────────────────────────────────────────────────────────────────────

// WHY "as const": gives a tuple literal type so RelationFilter is narrowly typed
// to the actual values ("all" | "executive" | ...) rather than string.
export const RELATION_TYPES = ["all", "executive", "investor", "supplier", "customer", "competitor"] as const;
export type RelationFilter = (typeof RELATION_TYPES)[number];

export interface GraphControlsProps {
  activeRelFilter: RelationFilter;
  minWeight: number;   // 0–100 integer (threshold percentage)
  searchQuery: string;
  layout: "force" | "hierarchical";
  edgeCount: number;
  /** Auto-applied strength floor threshold for dense graphs */
  denseGraphEdgeThreshold: number;
  onRelFilterChange: (filter: RelationFilter) => void;
  onMinWeightChange: (value: number) => void;
  onSearchQueryChange: (query: string) => void;
  onLayoutChange: (layout: "force" | "hierarchical") => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function GraphControls({
  activeRelFilter,
  minWeight,
  searchQuery,
  layout,
  edgeCount,
  denseGraphEdgeThreshold,
  onRelFilterChange,
  onMinWeightChange,
  onSearchQueryChange,
  onLayoutChange,
}: GraphControlsProps) {
  return (
    // WHY above SigmaContainer: controls must be interactive DOM elements;
    // placing them inside sigma's canvas div would cause z-index conflicts.
    // mb-2 gives 8px breathing room between controls and the graph frame.
    <div className="mb-2 flex flex-wrap items-center gap-2">

      {/* ── Relation-type filter pills ────────────────────────────────────── */}
      {/* WHY pills (not dropdown): pills let analysts see all options at once
          and toggle without opening a menu — critical for flow state in
          fast financial analysis. At max 6 pills they still fit on one row. */}
      <div className="flex gap-1" data-testid="filter-pills">
        {RELATION_TYPES.map((type) => {
          const isActive = activeRelFilter === type;
          return (
            <button
              key={type}
              onClick={() => onRelFilterChange(type)}
              data-testid={`filter-pill-${type}`}
              data-active={isActive}
              className={[
                // WHY rounded-[2px]: matches the terminal aesthetic — sharp corners
                // but 2px radius to avoid harsh 0px corners (Bloomberg convention).
                "capitalize rounded-[2px] border px-2 py-0.5 text-[10px] transition-colors",
                isActive
                  ? // WHY bg-primary/20: subtle primary fill — active state is clear
                    // without the pill looking like a full button press.
                    "bg-primary/20 text-primary border-primary/40"
                  : "text-muted-foreground border-border/40 hover:text-foreground hover:border-border/70",
              ].join(" ")}
            >
              {type}
            </button>
          );
        })}
      </div>

      {/* ── Edge-strength slider ───────────────────────────────────────────── */}
      {/* WHY min-weight filter: helps analysts focus on high-confidence edges
          (weight ≥ 0.7 = strong evidence) and filter out speculative relations
          that may be noisy in raw extraction output from S6. */}
      <div className="flex items-center gap-2" data-testid="strength-slider-container">
        <span className="whitespace-nowrap text-[10px] text-muted-foreground">
          Strength ≥ {minWeight}%
        </span>
        <Slider
          data-testid="strength-slider"
          value={[minWeight]}
          onValueChange={([v]) => onMinWeightChange(v ?? 0)}
          min={0}
          max={100}
          step={5}
          // WHY w-24: 96px is enough for precise control; wider wastes row space.
          className="w-24"
        />
      </div>

      {/* ── Node search input ──────────────────────────────────────────────── */}
      {/* WHY search dims (not hides): hiding nodes that have edges causes sigma
          to error on dangling endpoints. Dimming to the graph background hue
          keeps graph topology intact while directing analyst attention. */}
      <input
        value={searchQuery}
        onChange={(e) => onSearchQueryChange(e.target.value)}
        placeholder="Search nodes…"
        data-testid="node-search"
        className="h-7 rounded-[2px] border border-border/40 bg-card px-2 text-[11px] text-foreground placeholder:text-muted-foreground/50 focus:border-border focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      />

      {/* ── Layout switcher + camera reset ─────────────────────────────────── */}
      {/* WHY two layouts: force (FA2) surfaces organic clusters (useful for
          discovering communities); hierarchical reveals org structure (useful
          for exec/ownership analysis where tier matters). */}
      {/* WHY dense-graph badge: AAPL-scale graphs (128 edges) have an auto-
          applied 30% strength floor. The badge makes this visible so analysts
          don't wonder why they can't see all edges by default. */}
      <div className="ml-auto flex items-center gap-1">
        {edgeCount > denseGraphEdgeThreshold && (
          <span
            title={`Dense graph (${edgeCount} edges) — strength filter auto-applied`}
            className="rounded-[2px] bg-warning/15 px-1.5 py-0.5 font-mono text-[9px] text-warning"
          >
            {edgeCount} edges
          </span>
        )}
        <button
          onClick={() => onLayoutChange("force")}
          data-testid="layout-force"
          title="Force layout (ForceAtlas2)"
          className={[
            "rounded-[2px] border p-1 transition-colors",
            layout === "force"
              ? "border-primary/40 bg-primary/20 text-primary"
              : "border-border/40 text-muted-foreground hover:text-foreground hover:border-border/70",
          ].join(" ")}
        >
          <TrendingUp className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => onLayoutChange("hierarchical")}
          data-testid="layout-hierarchical"
          title="Hierarchical layout (degree-tier)"
          className={[
            "rounded-[2px] border p-1 transition-colors",
            layout === "hierarchical"
              ? "border-primary/40 bg-primary/20 text-primary"
              : "border-border/40 text-muted-foreground hover:text-foreground hover:border-border/70",
          ].join(" ")}
        >
          <Network className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
