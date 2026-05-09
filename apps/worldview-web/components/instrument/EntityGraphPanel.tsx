/**
 * components/instrument/EntityGraphPanel.tsx — SVG entity relationship graph (compact, depth=1)
 *
 * WHY THIS EXISTS: Knowledge graph visualisation helps analysts understand
 * second-order effects. If AAPL falls, the CEO (Tim Cook), competitors
 * (MSFT, GOOGL), and suppliers (TSMC, Foxconn) are all implicated. A graph
 * panel lets fund managers see these connections at a glance.
 *
 * WHY SVG (not sigma.js): This panel is the Overview sidebar — compact and
 * lightweight. The full interactive sigma.js graph lives in IntelligenceTab
 * (EntityGraph.tsx). SVG is deterministic, zero WebGL dependency, adequate
 * for a 320×280px compact sidebar graph.
 *
 * WHY depth=1 (direct neighbors only): The sidebar has limited space (~320px).
 * Depth=2 would clutter the SVG with 50+ nodes. Depth=1 gives 5–15 nodes —
 * just the directly connected entities. The full depth=2 graph is in Intelligence tab.
 *
 * WHY useQuery (not prop-drilling): Fetching here isolates the graph query
 * from the rest of the overview page data. The query caches for 10 min.
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx (Overview tab sidebar)
 * DATA SOURCE: S9 GET /v1/entities/{entityId}/graph?depth=1
 * DESIGN REFERENCE: PRD-0028 §6.5 Instrument Detail overview, State C entity graph
 */

"use client";
// WHY "use client": uses useQuery + useState for hover state and tooltip positioning.

import { useState, useRef } from "react";
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

// ── Tooltip state types ───────────────────────────────────────────────────────
// WHY separate NodeTooltip / EdgeTooltip types (not a union "active tooltip" type):
// the two tooltip shapes have different fields, and a union type would require
// a discriminant property everywhere we access them.  Parallel state is simpler.

/** State for a node hover tooltip: what to show + where to position it. */
interface NodeTooltipState {
  node: { id: string; label: string; type: string; degree: number };
  // WHY x/y as CSS pixel offsets from the container (not SVG coords):
  // The tooltip <div> uses CSS position:absolute relative to the wrapper div.
  // We convert SVG coordinates to container-relative pixel positions via
  // the SVG element's getBoundingClientRect().
  x: number;
  y: number;
}

/** State for an edge hover tooltip. */
interface EdgeTooltipState {
  edge: { label: string; weight: number };
  x: number;
  y: number;
}

// ── Node type colors ──────────────────────────────────────────────────────────
// WHY hex (not Tailwind): SVG fill attributes require hex values, not class names.
// WHY #FFD60A for company: Bloomberg trading yellow — updated from old amber (#E8A317)
// which clashed with the Midnight Pro dark terminal palette (global.css --primary: #FFD60A).
const NODE_COLORS: Record<string, { fill: string; stroke: string }> = {
  company: { fill: "#0A1A20", stroke: "#FFD60A" },  // Bloomberg yellow (#FFD60A) — publicly traded entities
  person:  { fill: "#0D2921", stroke: "#26A69A" },
  event:   { fill: "#2A1E06", stroke: "#F59E0B" },
  topic:   { fill: "#1A1A2E", stroke: "#818CF8" },
  // WHY hex literals (not tokens): this map is consumed by raw <circle> SVG
  // attributes which only accept hex/rgb strings. The fill/stroke mirror the
  // Terminal Dark `--card` (#111113) and `--muted-foreground` (#83838A) tokens.
  default: { fill: "#111113", stroke: "#83838A" },
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
  // PLAN-0050 Wave E T-E-5-04: hover tooltips for nodes and edges.
  // WHY separate state (not a single activeTooltip union): mutual exclusion is
  // enforced by clearing the other tooltip whenever one is set (see event handlers).
  const [nodeTooltip, setNodeTooltip] = useState<NodeTooltipState | null>(null);
  const [edgeTooltip, setEdgeTooltip] = useState<EdgeTooltipState | null>(null);
  // WHY svgRef: we need the SVG element's bounding rect to convert SVG-coordinate
  // mouse events (from onMouseEnter on SVG children) to container-relative pixels.
  const svgRef = useRef<SVGSVGElement>(null);

  const { data: graph, isLoading, isError } = useQuery({
    queryKey: ["entity-graph", entityId, 1],
    // WHY depth=1: Overview sidebar is compact (~320px). Depth=1 = direct neighbors only.
    // The full depth=2 interactive graph lives in the Intelligence tab (EntityGraph.tsx).
    queryFn: () => createGateway(accessToken).getEntityGraph(entityId, 1),
    enabled: !!accessToken && !!entityId,
    // WHY 10min: knowledge graph edges don't change frequently
    staleTime: 10 * 60_000,
  });

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) {
    return <Skeleton className="h-[280px] w-full rounded-[2px]" />;
  }

  // ── Error / empty state ────────────────────────────────────────────────────
  // WHY !graph.nodes guard: S9 may return {} (empty object, not null) for an entity
  // that has no graph data yet. {} is truthy so !graph passes, but {}.nodes is
  // undefined → undefined.length throws RangeError → crashes the whole instrument page.
  if (isError || !graph || !graph.nodes || graph.nodes.length === 0) {
    return (
      <div className="flex h-[280px] items-center justify-center rounded-[2px] border border-border/30 bg-card/50">
        <p className="text-xs text-muted-foreground">No relationship data</p>
      </div>
    );
  }

  // ── Layout computation ─────────────────────────────────────────────────────
  const WIDTH = 320;
  const HEIGHT = 280;
  const cx = WIDTH / 2;
  const cy = HEIGHT / 2;

  // Cap at 19 neighbor nodes (+ center = 20 total) — depth=1 gives fewer nodes
  // so this cap mostly acts as a safety guard for dense entity graphs.
  const cappedNodes = [
    graph.nodes.find((n) => n.id === entityId)!,
    ...graph.nodes.filter((n) => n.id !== entityId).slice(0, 19),
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

  // ── Degree map: count edges per node for tooltip display ─────────────────
  // WHY pre-compute: avoids a linear scan over all edges in every node's onMouseEnter.
  const degreeMap = new Map<string, number>();
  for (const edge of graph.edges) {
    degreeMap.set(edge.source, (degreeMap.get(edge.source) ?? 0) + 1);
    degreeMap.set(edge.target, (degreeMap.get(edge.target) ?? 0) + 1);
  }

  /**
   * Convert a mouse event position to container-relative pixel coordinates.
   *
   * WHY: SVG <g> elements fire onMouseEnter with clientX/clientY (viewport-absolute).
   * Our tooltip <div> uses position:absolute relative to the wrapper <div>.
   * Subtracting the container's bounding rect gives us the correct offset.
   */
  function toContainerCoords(e: React.MouseEvent): { x: number; y: number } {
    if (!svgRef.current) return { x: e.clientX, y: e.clientY };
    const rect = svgRef.current.getBoundingClientRect();
    return {
      x: e.clientX - rect.left + 12, // +12px: tooltip offsets right of cursor
      y: e.clientY - rect.top - 8,   // -8px: tooltip offset up from cursor
    };
  }

  return (
    // WHY position:relative: tooltips use position:absolute relative to this container.
    // The SVG viewBox coordinate system is fixed (320×280); the tooltip <div>s are
    // positioned in CSS-pixel space relative to this wrapper.
    <div className="relative overflow-hidden rounded-[2px] border border-border/30 bg-card/30">
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
        ref={svgRef}
        width={WIDTH}
        height={HEIGHT}
        className="w-full"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`Entity relationship graph for ${centerLabel ?? entityId}`}
        // WHY onMouseLeave on SVG: clears tooltips when the cursor leaves the SVG
        // entirely (in case a leaveEdge/leaveNode event was missed).
        onMouseLeave={() => { setNodeTooltip(null); setEdgeTooltip(null); }}
      >
        {/* Edges — render first so nodes paint on top */}
        {graph.edges.map((edge) => {
          const src = posMap.get(edge.source);
          const tgt = posMap.get(edge.target);
          if (!src || !tgt) return null;

          const isHighlighted =
            hoveredNodeId === edge.source || hoveredNodeId === edge.target;

          return (
            // WHY strokeWidth 12 on invisible path + visible line: the visible line
            // is 0.75–1.5px — too thin to reliably hover over. We layer an invisible
            // 12px hit-area line on top for the mouse events, then render the visible
            // thin line below. Both share the same key so React diffs them as a pair.
            // SIMPLER APPROACH: use pointer-events on a wider transparent stroke.
            <g key={edge.id}>
              <line
                x1={src.x}
                y1={src.y}
                x2={tgt.x}
                y2={tgt.y}
                // WHY hex literals: SVG stroke only accepts hex/rgb. The values
                // mirror Terminal Dark --muted-foreground (#83838A) when the
                // edge is highlighted and --muted (#18181B) when dimmed.
                stroke={isHighlighted ? "#83838A" : "#18181B"}
                strokeWidth={isHighlighted ? 1.5 : 0.75}
                strokeOpacity={isHighlighted ? 0.9 : 0.4}
              />
              {/* WHY invisible 12px stroke: makes the edge easier to hover — 0.75px
                  is almost impossible to hover precisely. The wide transparent
                  stroke catches mouse events and delegates to our handlers. */}
              <line
                x1={src.x}
                y1={src.y}
                x2={tgt.x}
                y2={tgt.y}
                stroke="transparent"
                strokeWidth={12}
                style={{ cursor: "crosshair" }}
                onMouseEnter={(e) => {
                  setNodeTooltip(null);
                  setEdgeTooltip({
                    edge: { label: edge.label, weight: edge.weight },
                    ...toContainerCoords(e),
                  });
                }}
                onMouseLeave={() => setEdgeTooltip(null)}
              />
            </g>
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
              onMouseEnter={(e) => {
                setHoveredNodeId(node.id);
                setEdgeTooltip(null);
                // Compute tooltip position in container-relative pixels.
                // WHY toContainerCoords: see helper above — converts clientX/clientY
                // to a CSS pixel offset from the container div.
                setNodeTooltip({
                  node: {
                    id: node.id,
                    label: node.label,
                    type: node.type,
                    degree: degreeMap.get(node.id) ?? 0,
                  },
                  ...toContainerCoords(e),
                });
              }}
              onMouseLeave={() => {
                setHoveredNodeId(null);
                setNodeTooltip(null);
              }}
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
                // WHY hex literals: SVG <text> fill needs hex/rgb. The values
                // mirror Terminal Dark --foreground (#E4E4E7) on hover and
                // --muted-foreground (#83838A) at rest.
                fill={isHovered ? "#E4E4E7" : "#83838A"}
                fontFamily="IBM Plex Mono, monospace"
                pointerEvents="none"
              >
                {displayLabel}
              </text>
            </g>
          );
        })}
      </svg>

      {/* ── Node hover tooltip ───────────────────────────────────────────────
          WHY pointer-events-none: the tooltip must not intercept mouse events —
          it's purely informational. Blocking mouse events would cause the tooltip
          to flicker as the cursor moves onto the tooltip div and triggers a leaveNode.
          WHY z-20 (not z-50): within this compact SVG panel there are no overlapping
          fixed/sticky elements; z-20 is sufficient and avoids z-index wars. */}
      {nodeTooltip && (
        <div
          className="pointer-events-none absolute z-20 rounded-[2px] border border-border/50 bg-card px-2.5 py-1.5 shadow-lg"
          style={{ left: nodeTooltip.x, top: nodeTooltip.y }}
          role="tooltip"
        >
          {/* Node name — truncated to 20 chars to fit compact panel */}
          <p className="text-[11px] font-medium text-foreground">
            {nodeTooltip.node.label.length > 20
              ? nodeTooltip.node.label.slice(0, 19) + "…"
              : nodeTooltip.node.label}
          </p>
          {/* Entity type — capitalised (e.g. "Company") */}
          <p className="mt-0.5 text-[10px] capitalize text-muted-foreground">
            {nodeTooltip.node.type}
          </p>
          {/* Degree — how many edges connect to this node */}
          <p className="text-[10px] text-muted-foreground">
            Connections: {nodeTooltip.node.degree}
          </p>
        </div>
      )}

      {/* ── Edge hover tooltip ───────────────────────────────────────────────
          WHY replace underscores: edge labels are stored as "CEO_OF", "COMPETES_WITH"
          (snake_case from the NLP pipeline). Human-readable display uses spaces. */}
      {edgeTooltip && (
        <div
          className="pointer-events-none absolute z-20 rounded-[2px] border border-border/50 bg-card px-2.5 py-1.5 shadow-lg"
          style={{ left: edgeTooltip.x, top: edgeTooltip.y }}
          role="tooltip"
        >
          <p className="text-[11px] font-medium uppercase tracking-wider text-foreground">
            {edgeTooltip.edge.label.replace(/_/g, " ").toLowerCase()}
          </p>
          <p className="mt-0.5 font-mono text-[10px] tabular-nums text-muted-foreground">
            Strength: {edgeTooltip.edge.weight.toFixed(2)}
          </p>
        </div>
      )}
    </div>
  );
}
