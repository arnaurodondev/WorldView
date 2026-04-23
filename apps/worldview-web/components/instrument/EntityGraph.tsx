/**
 * components/instrument/EntityGraph.tsx — Full interactive entity knowledge graph (sigma.js / WebGL)
 *
 * WHY THIS EXISTS: The Intelligence tab needs a full depth=2 interactive graph so analysts
 * can explore second-order entity relationships (e.g., Tim Cook → Apple → TSMC → Samsung).
 * sigma.js renders via WebGL — 60fps pan/zoom/drag for graphs up to 500+ nodes.
 *
 * WHY sigma.js (ADR-F-08): The Overview sidebar SVG (EntityGraphPanel.tsx) is adequate for
 * compact depth=1 display. For depth=2 with 50–100 nodes, WebGL is necessary for smooth
 * interaction. ForceAtlas2 produces an organic, cluster-revealing layout.
 *
 * WHY NO "use client" HERE: next/dynamic with ssr:false in IntelligenceTab.tsx handles
 * client-side-only loading. Adding "use client" here would be redundant and could cause
 * double-boundary issues with the dynamic import boundary.
 *
 * WHY GraphLoader + GraphEvents are SEPARATE components: sigma hooks (useLoadGraph,
 * useRegisterEvents, useSigma) MUST be called inside <SigmaContainer> — they rely
 * on the sigma React Context. We hoist state via callbacks to the parent EntityGraph.
 *
 * WHO USES IT: components/instrument/IntelligenceTab.tsx (Intelligence tab, loaded via next/dynamic)
 * DATA SOURCE: S9 GET /v1/entities/{entityId}/graph?depth=2
 * DESIGN REFERENCE: PRD-0028 §6.5 Intelligence tab, ADR-F-08
 */

import React, { useEffect, useRef, useState, useCallback } from "react";
import { SigmaContainer, useRegisterEvents, useLoadGraph, useSigma } from "@react-sigma/core";
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
// WHY import sigma CSS: provides the sigma WebGL canvas sizing reset (canvas fills container).
// Without this, the canvas may not fill the container correctly on first render.
import "@react-sigma/core/lib/style.css";
import { useRouter } from "next/navigation";
import type { EntityGraph as EntityGraphData } from "@/types/api";

// ── Node type → color map ─────────────────────────────────────────────────────
// WHY these exact values: match the Bloomberg Dark design system palette.
// Using hex directly (not Tailwind classes) because sigma reads node attributes — not CSS.
// WHY #E8A317 for company: amber primary — publicly traded entities are the flagship node type.
const NODE_TYPE_COLORS: Record<string, string> = {
  company: "#E8A317", // amber primary (#E8A317) — publicly traded entities
  person:  "#26A69A", // teal-500 — executives, board members
  event:   "#F59E0B", // amber-500 — macro events, earnings releases
  topic:   "#818CF8", // indigo-400 — themes, sectors, concepts
  default: "#6B7585", // muted-foreground (#6B7585) — unknown / unclassified entity types
};

// ── Tooltip state types ───────────────────────────────────────────────────────

interface NodeTooltip {
  label: string;
  type: string;
  degree: number;
  // WHY x/y are DOM coordinates: sigma fires events with canvas-relative coordinates.
  // We position the tooltip div using these values (CSS left/top).
  x: number;
  y: number;
}

interface EdgeTooltip {
  label: string;
  weight: number;
  x: number;
  y: number;
}

// ── WebGL ErrorBoundary ───────────────────────────────────────────────────────
// WHY class component: React error boundaries can ONLY be class components.
// We need one because sigma.js attempts WebGL context creation, which throws
// in unsupported browsers (old Safari, Firefox with hardware acceleration off).

class GraphErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): { hasError: boolean } {
    // WHY: React calls this when a child throws during render.
    // We flip hasError to show the fallback UI.
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3 rounded border border-border/40 bg-card/50 p-8 text-center">
          <p className="text-sm font-medium text-muted-foreground">Graph unavailable</p>
          <p className="text-xs text-muted-foreground/60">
            WebGL is required for the entity graph visualization.
          </p>
          {/* WHY window.location.reload: simplest recovery — no state to preserve */}
          <button
            onClick={() => window.location.reload()}
            className="rounded border border-border/40 px-3 py-1 text-xs text-muted-foreground hover:border-border hover:text-foreground"
          >
            Reload page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// ── GraphEvents — sigma event registration (must live inside SigmaContainer) ──
// WHY separate: useRegisterEvents + useSigma are context hooks that only work
// when rendered as a descendant of <SigmaContainer>. Cannot call them in parent.

interface GraphEventsProps {
  centerEntityId: string;
  onNodeHover: (tooltip: NodeTooltip | null) => void;
  onEdgeHover: (tooltip: EdgeTooltip | null) => void;
}

function GraphEvents({ centerEntityId, onNodeHover, onEdgeHover }: GraphEventsProps) {
  const sigma = useSigma();
  const registerEvents = useRegisterEvents();
  const router = useRouter();

  useEffect(() => {
    registerEvents({
      enterNode: ({ node, event }) => {
        const graph = sigma.getGraph();
        const attrs = graph.getNodeAttributes(node);
        const degree = graph.degree(node);
        onNodeHover({
          label: attrs.label as string,
          type: attrs.nodeType as string,
          degree,
          // WHY event.x / event.y: sigma fires canvas-relative DOM coordinates.
          // We position the tooltip div relative to the container (position:relative)
          // using these values + a 12px / -8px offset to avoid cursor overlap.
          x: event.x,
          y: event.y,
        });
      },
      leaveNode: () => onNodeHover(null),

      enterEdge: ({ edge, event }) => {
        const graph = sigma.getGraph();
        const attrs = graph.getEdgeAttributes(edge);
        onEdgeHover({
          label: attrs.label as string,
          weight: attrs.weight as number,
          x: event.x,
          y: event.y,
        });
      },
      leaveEdge: () => onEdgeHover(null),

      clickNode: ({ node }) => {
        // WHY navigate: each graph node represents an entity. Clicking navigates
        // to that entity's instrument detail page — same URL pattern as current page.
        // We skip the center entity (clicking the center is a no-op).
        if (node !== centerEntityId) {
          router.push(`/instruments/${node}`);
        }
      },
    });
  }, [registerEvents, sigma, router, centerEntityId, onNodeHover, onEdgeHover]);

  // WHY returns null: this component exists only to register side-effect event
  // listeners; it renders nothing to the DOM.
  return null;
}

// ── GraphLoader — builds graphology graph and runs ForceAtlas2 ────────────────
// WHY separate: useLoadGraph must be inside <SigmaContainer> context.

interface GraphLoaderProps {
  data: EntityGraphData;
  centerEntityId: string;
}

function GraphLoader({ data, centerEntityId }: GraphLoaderProps) {
  const loadGraph = useLoadGraph();

  useEffect(() => {
    // WHY undirected + multi:false: knowledge graph edges are bidirectional
    // relationships (CEO_OF is the same relationship from either direction).
    // multi:false prevents duplicate edges between the same node pair.
    // allowSelfLoops:false — self-loops crash ForceAtlas2 (FK-001 known issue).
    const graph = new Graph({ type: "undirected", multi: false, allowSelfLoops: false });

    // ── Build nodes ──────────────────────────────────────────────────────────
    for (const node of data.nodes) {
      const isCenter = node.id === centerEntityId;

      // WHY 3-tier sizing: center entity (20) is visually dominant,
      // direct neighbors (10) are medium, depth-2 nodes (7) are small background.
      // node.size from API is an importance score: ≥2 = direct neighbor tier.
      const baseSize = isCenter ? 20 : (node.size ?? 1) >= 2 ? 10 : 7;

      const color = NODE_TYPE_COLORS[node.type] ?? NODE_TYPE_COLORS.default;

      graph.addNode(node.id, {
        label: node.label,
        // WHY nodeType (not type): sigma/graphology reserves the 'type' attribute
        // for node renderer type (e.g., "circle"). Storing entity type as nodeType
        // avoids conflicts with the renderer system.
        nodeType: node.type,
        // WHY random initial positions: ForceAtlas2 requires every node to have
        // initial x/y coordinates before it runs. Random positions spread nodes
        // evenly so FA2 converges from a good starting state.
        x: Math.random() * 100 - 50,
        y: Math.random() * 100 - 50,
        size: baseSize,
        color,
        // WHY borderColor: center node gets a white border to visually distinguish it
        // from depth-1 neighbors at a glance (Bloomberg "focused security" convention).
        borderColor: isCenter ? "#FFFFFF" : color,
        // WHY zIndex: center node paints on top of all edges and other nodes.
        zIndex: isCenter ? 10 : 1,
      });
    }

    // ── Build edges ──────────────────────────────────────────────────────────
    for (const edge of data.edges) {
      // WHY both-endpoint check: API may return edges to nodes not in the node list
      // (e.g., depth boundary trimming). Skipping prevents graphology errors.
      if (graph.hasNode(edge.source) && graph.hasNode(edge.target)) {
        // WHY hasEdge check: undirected graph with multi:false still needs this
        // guard because the API may return bidirectional duplicate edges.
        if (!graph.hasEdge(edge.source, edge.target)) {
          graph.addEdge(edge.source, edge.target, {
            id: edge.id,
            label: edge.label,
            weight: edge.weight,
            // WHY min 0.5px: very low weight edges still need to be visible.
            // Multiplied by 2 so weight=1.0 edges appear as 2px lines.
            size: Math.max(0.5, edge.weight * 2),
            color: "#1A2030", // muted (#1A2030) — dim edge color (highlighted on hover via GraphEvents)
          });
        }
      }
    }

    // ── Run ForceAtlas2 layout ────────────────────────────────────────────────
    // WHY synchronous (not worker): The worker variant is async and requires
    // a separate Worker file. Synchronous FA2 runs in <50ms for ≤100 nodes —
    // acceptable for our use case. Worker is only needed for 500+ node graphs.
    if (graph.order > 0) {
      // WHY inferSettings: automatically calibrates gravity, scaling, slow-down
      // based on graph density (order/edges ratio). We then override gravity
      // to a lower value to spread nodes more evenly across the canvas.
      const fa2Settings = forceAtlas2.inferSettings(graph);
      forceAtlas2.assign(graph, {
        iterations: 100,
        settings: {
          ...fa2Settings,
          gravity: 0.1,         // WHY low gravity: prevents all nodes collapsing to center
          adjustSizes: true,    // WHY adjustSizes: prevents node overlap by using node.size
          // WHY Barnes-Hut only for large graphs: the approximation improves O(n²)→O(n log n)
          // but introduces layout error at small scales. Only enable for 50+ nodes.
          barnesHutOptimize: graph.order > 50,
        },
      });
    }

    // Pass the constructed + laid-out graphology graph to sigma for rendering
    loadGraph(graph);
  }, [data, centerEntityId, loadGraph]);

  return null;
}

// ── NodeTooltipPanel ──────────────────────────────────────────────────────────
// WHY pointer-events-none: tooltip is informational only — it must not block
// mouse events from reaching the sigma canvas below it.

function NodeTooltipPanel({ tooltip }: { tooltip: NodeTooltip }) {
  return (
    <div
      className="pointer-events-none absolute z-50 rounded border border-border/50 bg-card px-3 py-2 shadow-lg"
      style={{ left: tooltip.x + 12, top: tooltip.y - 8 }}
    >
      <p className="text-xs font-medium text-foreground">{tooltip.label}</p>
      <p className="mt-0.5 text-[10px] capitalize text-muted-foreground">
        Type: {tooltip.type}
      </p>
      <p className="text-[10px] text-muted-foreground">
        Relationships: {tooltip.degree}
      </p>
    </div>
  );
}

// ── EdgeTooltipPanel ──────────────────────────────────────────────────────────

function EdgeTooltipPanel({ tooltip }: { tooltip: EdgeTooltip }) {
  // WHY replace underscores: relationship labels are stored as "CEO_OF", "COMPETES_WITH"
  // etc. Human-readable display replaces underscores with spaces and lower-cases.
  const displayLabel = tooltip.label.replace(/_/g, " ").toLowerCase();

  return (
    <div
      className="pointer-events-none absolute z-50 rounded border border-border/50 bg-card px-3 py-2 shadow-lg"
      style={{ left: tooltip.x + 12, top: tooltip.y - 8 }}
    >
      <p className="text-xs font-medium uppercase tracking-wider text-foreground">
        {displayLabel}
      </p>
      <p className="mt-0.5 text-[10px] text-muted-foreground">
        Strength: {tooltip.weight.toFixed(2)}
      </p>
    </div>
  );
}

// ── GraphLegend ───────────────────────────────────────────────────────────────
// WHY bottom-left: follows Bloomberg convention — controls/info at corners,
// main canvas area unobstructed. backdrop-blur-sm softens the legend against
// complex graph backgrounds.

function GraphLegend() {
  return (
    <div className="absolute bottom-2 left-2 z-10 flex flex-wrap gap-2 rounded border border-border/40 bg-card/80 px-2 py-1 backdrop-blur-sm">
      {Object.entries(NODE_TYPE_COLORS)
        .filter(([k]) => k !== "default") // WHY exclude default: "default" is not a real entity type
        .map(([type, color]) => (
          <div key={type} className="flex items-center gap-1">
            <div className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
            <span className="text-[9px] capitalize text-muted-foreground">{type}</span>
          </div>
        ))}
    </div>
  );
}

// ── Main EntityGraph component ────────────────────────────────────────────────

export interface EntityGraphProps {
  data: EntityGraphData;
  centerEntityId: string;
}

export function EntityGraph({ data, centerEntityId }: EntityGraphProps) {
  const [nodeTooltip, setNodeTooltip] = useState<NodeTooltip | null>(null);
  const [edgeTooltip, setEdgeTooltip] = useState<EdgeTooltip | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // WHY useCallback with []: the setState functions from useState are stable
  // (same reference across renders). useCallback with [] deps ensures the handler
  // references are also stable, preventing useEffect re-registration in GraphEvents.
  const handleNodeHover = useCallback((tooltip: NodeTooltip | null) => {
    setNodeTooltip(tooltip);
    setEdgeTooltip(null); // WHY clear edge tooltip: mutual exclusion — only one tooltip at a time
  }, []);

  const handleEdgeHover = useCallback((tooltip: EdgeTooltip | null) => {
    setEdgeTooltip(tooltip);
    setNodeTooltip(null);
  }, []);

  // ── Empty state ─────────────────────────────────────────────────────────────
  if (!data.nodes.length) {
    return (
      <div className="flex h-[460px] items-center justify-center rounded border border-border/40 bg-card/30 text-sm text-muted-foreground">
        No relationship data available
      </div>
    );
  }

  return (
    <GraphErrorBoundary>
      <div
        ref={containerRef}
        className="relative h-[460px] overflow-hidden rounded border border-border/40"
        // WHY inline style for background: Tailwind's bg-[#0A0E14] would work but
        // this makes the dark graph background explicit and visually consistent with
        // the rest of the dark theme (#0A0E14 is the app background token).
        style={{ background: "#0A0E14" }}
      >
        <SigmaContainer
          className="h-full w-full"
          settings={{
            // WHY circle/line: simplest node/edge renderers — no extra geometry overhead
            defaultNodeType: "circle",
            defaultEdgeType: "line",
            // WHY renderEdgeLabels:false: edge labels clutter the graph at depth=2.
            // Relationship types are shown in the hover tooltip instead.
            renderEdgeLabels: false,
            // WHY labelRenderedSizeThreshold 8: only show labels for nodes with
            // rendered size >= 8px. Depth-2 nodes (size=7) are too small to label;
            // direct neighbors (size=10) and center (size=20) get labels.
            // Avoids text clutter for dense depth=2 graphs.
            labelRenderedSizeThreshold: 8,
            labelColor: { color: "#6B7585" },
            labelFont: "IBM Plex Mono, monospace",
            labelSize: 10,
            labelWeight: "500",
            // WHY min/maxCameraRatio: allows full zoom-out to see the whole graph
            // and zoom-in to read individual node labels for dense areas.
            minCameraRatio: 0.1,
            maxCameraRatio: 10,
            // WHY allowInvalidContainer:true: prevents sigma from throwing when the
            // DOM element is briefly unmounted during React StrictMode double-invoke
            // or when the component is conditionally rendered.
            allowInvalidContainer: true,
          }}
          style={{ background: "#0A0E14" }}
        >
          {/* GraphLoader builds the graphology graph and passes it to sigma */}
          <GraphLoader data={data} centerEntityId={centerEntityId} />

          {/* GraphEvents registers hover/click listeners on the sigma instance */}
          <GraphEvents
            centerEntityId={centerEntityId}
            onNodeHover={handleNodeHover}
            onEdgeHover={handleEdgeHover}
          />
        </SigmaContainer>

        {/* Tooltips — rendered inside the container div so position:absolute
            is relative to the container (not the page). */}
        {nodeTooltip && <NodeTooltipPanel tooltip={nodeTooltip} />}
        {edgeTooltip && <EdgeTooltipPanel tooltip={edgeTooltip} />}

        {/* Legend — bottom-left corner */}
        <GraphLegend />

        {/* Controls hint — top-right corner, very small opacity text */}
        <div className="absolute right-2 top-2 z-10 rounded border border-border/40 bg-card/80 px-2 py-1 backdrop-blur-sm">
          <span className="text-[9px] text-muted-foreground/60">
            Scroll to zoom · Drag to pan · Click to navigate
          </span>
        </div>
      </div>
    </GraphErrorBoundary>
  );
}
