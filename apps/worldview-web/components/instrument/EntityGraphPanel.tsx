/**
 * components/instrument/EntityGraphPanel.tsx — SVG entity relationship graph
 *
 * WHY THIS EXISTS: Knowledge graph visualisation helps analysts understand
 * second-order effects. If AAPL falls, the CEO (Tim Cook), competitors
 * (MSFT, GOOGL), and suppliers (TSMC, Foxconn) are all implicated. A graph
 * panel lets fund managers see these connections at a glance.
 *
 * WHY SVG (not sigma.js): sigma.js is not in package.json and would add ~200KB.
 * For MVP, a simple radial SVG layout communicates the graph structure adequately.
 * The center entity is always the focus node; related entities radiate outward.
 * Color-coded by relationship type (company=blue, person=green, event=amber).
 *
 * WHY useQuery (not prop-drilling): The graph data is large (~50 nodes for
 * depth=2). Fetching it here avoids passing a huge payload through page.tsx.
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx (Overview tab sidebar)
 * DATA SOURCE: S9 GET /v1/entities/{entityId}/graph?depth=2
 * DESIGN REFERENCE: PRD-0028 §6.5 Instrument Detail overview, State C entity graph
 */

"use client";
// WHY "use client": uses useQuery + useState for hover state.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import type { GraphNode, GraphEdge } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface EntityGraphPanelProps {
  entityId: string;
  /** Entity name shown at the center node */
  centerLabel?: string;
}

// ── Node type colors ──────────────────────────────────────────────────────────
// WHY hex (not Tailwind): SVG fill attributes require hex values, not class names.
const NODE_COLORS: Record<string, { fill: string; stroke: string }> = {
  company: { fill: "#0A2A40", stroke: "#0EA5E9" },
  person:  { fill: "#0D2921", stroke: "#26A69A" },
  event:   { fill: "#2A1E06", stroke: "#F59E0B" },
  topic:   { fill: "#1A1A2E", stroke: "#818CF8" },
  default: { fill: "#1E2329", stroke: "#4B5563" },
};

// ── Layout helpers ─────────────────────────────────────────────────────────────

/**
 * computeRadialLayout — positions N nodes in a ring around a center point
 *
 * WHY radial: Simple, deterministic, no physics engine required.
 * The center node is always at (cx, cy). Related nodes form a ring.
 * If there are 2 rings (depth=2), we use two concentric rings.
 */
function computeRadialLayout(
  nodes: GraphNode[],
  edges: GraphEdge[],
  centerEntityId: string,
  cx: number,
  cy: number,
  innerRadius: number,
  outerRadius: number,
): { id: string; x: number; y: number; label: string; type: string }[] {
  // Partition nodes into: center, directly connected, rest
  const directNeighborIds = new Set<string>();
  for (const e of edges) {
    if (e.source === centerEntityId) directNeighborIds.add(e.target);
    if (e.target === centerEntityId) directNeighborIds.add(e.source);
  }

  const centerNode = nodes.find((n) => n.id === centerEntityId);
  const innerNodes = nodes.filter((n) => n.id !== centerEntityId && directNeighborIds.has(n.id));
  const outerNodes = nodes.filter((n) => n.id !== centerEntityId && !directNeighborIds.has(n.id));

  const result: { id: string; x: number; y: number; label: string; type: string }[] = [];

  if (centerNode) {
    result.push({ id: centerNode.id, x: cx, y: cy, label: centerNode.label, type: centerNode.type });
  }

  // Position inner ring nodes evenly spaced around the center
  innerNodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / Math.max(1, innerNodes.length) - Math.PI / 2;
    result.push({
      id: node.id,
      x: cx + innerRadius * Math.cos(angle),
      y: cy + innerRadius * Math.sin(angle),
      label: node.label,
      type: node.type,
    });
  });

  // Position outer ring nodes
  outerNodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / Math.max(1, outerNodes.length) - Math.PI / 4;
    result.push({
      id: node.id,
      x: cx + outerRadius * Math.cos(angle),
      y: cy + outerRadius * Math.sin(angle),
      label: node.label,
      type: node.type,
    });
  });

  return result;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function EntityGraphPanel({ entityId, centerLabel }: EntityGraphPanelProps) {
  const { accessToken } = useAuth();
  const router = useRouter();
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  const { data: graph, isLoading, isError } = useQuery({
    queryKey: ["entity-graph", entityId],
    queryFn: () => createGateway(accessToken).getEntityGraph(entityId, 2),
    enabled: !!accessToken && !!entityId,
    // WHY 10min: knowledge graph edges don't change frequently
    staleTime: 10 * 60_000,
  });

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) {
    return <Skeleton className="h-[280px] w-full rounded" />;
  }

  // ── Error / empty state ────────────────────────────────────────────────────
  if (isError || !graph || graph.nodes.length === 0) {
    return (
      <div className="flex h-[280px] items-center justify-center rounded border border-border/30 bg-card/50">
        <p className="text-xs text-muted-foreground">No relationship data</p>
      </div>
    );
  }

  // ── Layout computation ─────────────────────────────────────────────────────
  const WIDTH = 320;
  const HEIGHT = 280;
  const cx = WIDTH / 2;
  const cy = HEIGHT / 2;

  // Cap at 30 nodes to keep SVG performant; center node always included
  const cappedNodes = [
    graph.nodes.find((n) => n.id === entityId)!,
    ...graph.nodes.filter((n) => n.id !== entityId).slice(0, 29),
  ].filter(Boolean);

  const positions = computeRadialLayout(
    cappedNodes,
    graph.edges,
    entityId,
    cx,
    cy,
    90,   // inner ring radius
    140,  // outer ring radius
  );

  // Build a lookup for fast position access when rendering edges
  const posMap = new Map(positions.map((p) => [p.id, p]));

  return (
    <div className="overflow-hidden rounded border border-border/30 bg-card/30">
      {/* Legend */}
      <div className="flex flex-wrap gap-3 border-b border-border/30 px-3 py-1.5">
        {Object.entries(NODE_COLORS).filter(([k]) => k !== "default").map(([type, colors]) => (
          <div key={type} className="flex items-center gap-1">
            <div
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: colors.stroke }}
            />
            <span className="text-[9px] capitalize text-muted-foreground">{type}</span>
          </div>
        ))}
      </div>

      {/* SVG graph */}
      <svg
        width={WIDTH}
        height={HEIGHT}
        className="w-full"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`Entity relationship graph for ${centerLabel ?? entityId}`}
      >
        {/* Edges — render first so nodes paint on top */}
        {graph.edges.map((edge) => {
          const src = posMap.get(edge.source);
          const tgt = posMap.get(edge.target);
          if (!src || !tgt) return null;

          const isHighlighted =
            hoveredNodeId === edge.source || hoveredNodeId === edge.target;

          return (
            <line
              key={edge.id}
              x1={src.x}
              y1={src.y}
              x2={tgt.x}
              y2={tgt.y}
              stroke={isHighlighted ? "#4B5563" : "#2B3139"}
              strokeWidth={isHighlighted ? 1.5 : 0.75}
              strokeOpacity={isHighlighted ? 0.9 : 0.4}
            />
          );
        })}

        {/* Nodes */}
        {positions.map((node) => {
          const isCenter = node.id === entityId;
          const isHovered = hoveredNodeId === node.id;
          const colors = NODE_COLORS[node.type] ?? NODE_COLORS.default;

          // Truncate label for compact display inside SVG
          const displayLabel =
            node.label.length > 14 ? node.label.slice(0, 13) + "…" : node.label;

          return (
            <g
              key={node.id}
              transform={`translate(${node.x}, ${node.y})`}
              // WHY onClick: clicking a related entity navigates to its detail page
              onClick={() => {
                if (!isCenter) {
                  router.push(`/instruments/${node.id}`);
                }
              }}
              onMouseEnter={() => setHoveredNodeId(node.id)}
              onMouseLeave={() => setHoveredNodeId(null)}
              style={{ cursor: isCenter ? "default" : "pointer" }}
            >
              <circle
                r={isCenter ? 22 : isHovered ? 10 : 8}
                fill={colors.fill}
                stroke={colors.stroke}
                strokeWidth={isCenter ? 2.5 : isHovered ? 2 : 1}
              />
              <text
                textAnchor="middle"
                dy={isCenter ? "0.35em" : "2.6em"}
                fontSize={isCenter ? 9 : 7}
                fill={isHovered ? "#E5E7EB" : "#9CA3AF"}
                fontFamily="IBM Plex Mono, monospace"
                pointerEvents="none"
              >
                {displayLabel}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
