/**
 * components/instrument/graph/GraphLegend.tsx — Entity type + edge legend for the graph
 *
 * WHY EXTRACTED: GraphLegend was an inner function inside EntityGraph.tsx. Moving it
 * to its own file keeps EntityGraph.tsx under 400 lines and makes the legend
 * independently testable and reusable.
 *
 * WHY bottom-left: follows Bloomberg convention — controls/info at corners,
 * main canvas area unobstructed. backdrop-blur-sm softens the legend against
 * complex graph backgrounds.
 *
 * PLAN-0057 Wave F-1: legend now reflects ONLY the entity types present in
 * the current graph data so analysts aren't shown 13+ swatches when most
 * graphs only have 4-5. Unknown types surface in the default grey so the
 * missing type is visible rather than silently absent.
 *
 * WHO USES IT: EntityGraph.tsx — never directly by pages.
 */

import React from "react";
import { ENTITY_TYPE_COLOR_MAP } from "@/lib/entity-types";
import type { EntityGraph as EntityGraphData } from "@/types/api";

// WHY hex literal (not a Tailwind class): sigma renders nodes to a WebGL
// canvas and reads the `color` attribute as a hex/rgb string — CSS classes
// never reach the canvas. The literal mirrors `--muted-foreground` (#83838A)
// from globals.css.
const NODE_DEFAULT_COLOR = "#83838A";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface GraphLegendProps {
  data: EntityGraphData;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function GraphLegend({ data }: GraphLegendProps) {
  const visibleTypes = React.useMemo(() => {
    const seen = new Set<string>();
    for (const node of data.nodes) seen.add(node.type);
    return Array.from(seen);
  }, [data.nodes]);

  return (
    <div className="absolute bottom-2 left-2 z-10 flex flex-wrap gap-2 rounded-[2px] border border-border/40 bg-card/80 px-2 py-1 backdrop-blur-sm">
      {visibleTypes.map((type) => {
        const color = ENTITY_TYPE_COLOR_MAP[type] ?? NODE_DEFAULT_COLOR;
        // PLAN-0057 types are snake_case — pretty-print for the legend.
        const label = type.replace(/_/g, " ");
        return (
          <div key={type} className="flex items-center gap-1">
            <div className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
            <span className="text-[9px] capitalize text-muted-foreground">{label}</span>
          </div>
        );
      })}
    </div>
  );
}
