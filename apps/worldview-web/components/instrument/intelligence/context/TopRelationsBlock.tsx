/**
 * context/TopRelationsBlock.tsx — Top 10 direct relations for the context rail (PLAN-0099 W4)
 *
 * WHY THIS EXISTS: The Intelligence tab's right rail should give analysts a ranked
 * list of the primary entity's strongest direct connections. The graph canvas
 * (GraphColumn) shows the relations visually; TopRelationsBlock lists them in text
 * so analysts can scroll quickly without panning the canvas.
 *
 * WHY NO NEW NETWORK CALL:
 * The graph data is already fetched by ContextPanel (depth=1, staleTime=5min, cached
 * under ["entity-graph", entityId, 1, null]). We accept edges + nodes as props so this
 * block is purely derived from already-loaded data — zero extra latency.
 *
 * RANKING: edges sorted by weight (descending), then alphabetically by target label
 * as a stable tie-breaker. We show at most 10 — beyond 10 the analyst should use the
 * graph canvas or apply a type filter.
 *
 * INTERACTION: clicking a row fires onNodeSelect(edge.target | edge.source) so the
 * right panel switches to NodeDetailCard for that node. This mirrors the graph click
 * behaviour without requiring the canvas to be visible.
 *
 * DESIGN: 18px rows — matches DenseArticleRow height (the platform's "data-row" unit).
 * WHO USES IT: ContextPanel (entity-overview mode only).
 */

"use client";
// WHY "use client": onClick event handlers require a browser.

import { useMemo } from "react";
import type { GraphEdge, GraphNode } from "@/types/api";

export interface TopRelationsBlockProps {
  /** The primary entity being viewed (used to determine edge direction). */
  readonly entityId: string;
  /** Edge list from the depth=1 graph (already cached by ContextPanel). */
  readonly edges: GraphEdge[] | undefined;
  /** Node list from the same graph — used to resolve target names. */
  readonly nodes: GraphNode[] | undefined;
  /** Callback fired when the user clicks a relation row. Mirrors graph node-click. */
  readonly onNodeSelect: (nodeId: string) => void;
}

const MAX_RELATIONS = 10;

// ── Component ─────────────────────────────────────────────────────────────────

export function TopRelationsBlock({
  entityId,
  edges,
  nodes,
  onNodeSelect,
}: TopRelationsBlockProps) {
  // WHY nodesById: O(n) map built once so each edge lookup is O(1) not O(n).
  const nodesById = useMemo<Record<string, GraphNode>>(() => {
    if (!nodes) return {};
    const map: Record<string, GraphNode> = {};
    for (const n of nodes) map[n.id] = n;
    return map;
  }, [nodes]);

  // WHY sort by weight desc: stronger relations are more analytically relevant.
  // Tie-break alphabetically (label) so the list is stable across renders.
  const topEdges = useMemo<GraphEdge[]>(() => {
    if (!edges) return [];
    return [...edges]
      .sort((a, b) => {
        const wDiff = b.weight - a.weight;
        if (wDiff !== 0) return wDiff;
        // Stable tie-break: label alphabetically (label is the relation type, e.g. "competes_with")
        return a.label.localeCompare(b.label);
      })
      .slice(0, MAX_RELATIONS);
  }, [edges]);

  const sectionLabel = (
    // WHY uppercase tracking-[0.1em] mono: matches the platform's section header
    // convention (PathInsightsBlock, RelationsList, etc.) — 9-10px mono uppercase
    // is the "data section label" style throughout the Intelligence rail.
    <div className="px-3 h-[20px] flex items-center">
      {/* Round-3 item 2: label-level accent bar — uniform Round-1 section
          marker (see ContradictionsBlock header for the full rationale). */}
      <span className="border-l-2 border-l-primary pl-1.5 text-[9px] font-mono uppercase tracking-[0.1em] text-muted-foreground">
        Top Relations{topEdges.length > 0 ? ` · (${topEdges.length})` : ""}
      </span>
    </div>
  );

  if (!edges || topEdges.length === 0) {
    return (
      <div className="border-b border-border/40">
        {sectionLabel}
        <p className="px-3 pb-2 text-[11px] text-muted-foreground">
          No direct relations.
        </p>
      </div>
    );
  }

  return (
    <div className="border-b border-border/40">
      {sectionLabel}
      {topEdges.map((edge) => {
        // WHY resolve BOTH source and target: for depth=1 the centre entity is
        // always either source or target. The OTHER end is the related entity.
        const relatedId = edge.source === entityId ? edge.target : edge.source;
        const relatedNode = nodesById[relatedId];
        // Fallback: if the node isn't in the map yet, use the raw id truncated.
        const relatedLabel = relatedNode?.label ?? relatedId.slice(0, 12) + "…";

        // WHY lowercase replace /_/g: relation types from KG are snake_case
        // ("competes_with"). Display as "competes with" — reads naturally.
        const relType = edge.label.replace(/_/g, " ").toLowerCase();

        return (
          <button
            key={edge.id}
            type="button"
            onClick={() => onNodeSelect(relatedId)}
            // WHY h-[18px]: matches DenseArticleRow — 18px is the "data-row" unit.
            // px-3 aligns with the section label and ContextPanel padding.
            // hover:bg-muted/20: subtle hover state (same as PathInsightsBlock rows).
            className="w-full h-[18px] px-3 flex items-center gap-2 hover:bg-muted/20 cursor-pointer transition-colors duration-100"
            aria-label={`Select ${relatedLabel} (${relType})`}
          >
            {/* Target entity name — truncated to prevent overflow in narrow rail */}
            <span className="text-[11px] font-mono text-foreground/90 truncate flex-1 text-left">
              {relatedLabel}
            </span>

            {/* Relation type — muted 9px, shrinks before name */}
            <span className="shrink-0 text-[9px] text-muted-foreground lowercase">
              {relType}
            </span>

            {/* Edge weight — tabular-nums so values align as the list rerenders */}
            <span className="shrink-0 w-[30px] text-right text-[10px] font-mono tabular-nums text-muted-foreground/70">
              {edge.weight.toFixed(2)}
            </span>
          </button>
        );
      })}
    </div>
  );
}
