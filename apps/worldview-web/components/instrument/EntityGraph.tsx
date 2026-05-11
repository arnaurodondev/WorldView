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
 * PLAN-0059 Wave H-4: Added interactive filter controls:
 *   - Filter pills (by relationship category: all/executive/investor/supplier/customer/competitor)
 *   - Edge-strength slider (min weight threshold 0–100%)
 *   - Node search input (dims non-matching nodes in sigma via nodeReducer)
 *   - Layout switcher (force = ForceAtlas2, hierarchical = degree-tier layout)
 *   - FilterController: a dedicated sigma child component that pushes filter
 *     state into sigma.setSettings({ edgeReducer, nodeReducer }) on every change,
 *     bypassing React re-render of the heavy SigmaContainer.
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
import { TrendingUp, Network, Maximize2 } from "lucide-react";
import type { EntityGraph as EntityGraphData } from "@/types/api";
import { Slider } from "@/components/ui/slider";

// ── Dense-graph threshold ─────────────────────────────────────────────────────
// WHY 50 edges: graphs with >50 edges (like AAPL at 128) become unreadable with
// no filtering. Auto-applying a 30% strength floor removes the weakest-evidence
// edges and makes the graph immediately readable on first load.
// The user can then lower the threshold if they want to see all edges.
const DENSE_GRAPH_EDGE_THRESHOLD = 50;
const DENSE_GRAPH_AUTO_MIN_WEIGHT = 30; // percent

// ── Node type → color map ─────────────────────────────────────────────────────
// WHY these exact values: match the Midnight Pro palette (global.css --primary: #FFD60A).
// Using hex directly (not Tailwind classes) because sigma reads node attributes — not CSS.
// WHY #FFD60A for company: Bloomberg trading yellow — updated from old amber (#E8A317)
// which clashed with the Midnight Pro dark terminal palette.
// PLAN-0057 Wave F-1: delegate to the central entity-type palette so the graph,
// badges, and any future entity-detail page share one colour vocabulary.  The
// previous 4-way map (company/person/event/topic) silently rendered the 9 new
// canonical types (currency/regulator/location/…) in default grey.
import { ENTITY_TYPE_COLOR_MAP } from "@/lib/entity-types";

// WHY a hex literal (not a Tailwind class): sigma renders nodes to a WebGL
// canvas and reads the `color` attribute as a hex/rgb string — CSS classes
// never reach the canvas. The literal mirrors `--muted-foreground` (#83838A)
// from globals.css; if the token shifts, audit this constant manually.
const NODE_DEFAULT_COLOR = "#83838A";

// ── Filter pill types (PLAN-0059 Wave H-4) ───────────────────────────────────
// WHY "as const": gives a tuple literal type so RelationFilter is narrowly typed
// to the actual values ("all" | "executive" | ...) rather than string.
const RELATION_TYPES = ["all", "executive", "investor", "supplier", "customer", "competitor"] as const;
type RelationFilter = (typeof RELATION_TYPES)[number];

// ── matchesRelFilter: maps a pill category to edge label patterns ─────────────
// WHY pattern-based (not exact-match): relation labels vary by data source.
// "CEO_OF", "EXECUTIVE_CHAIR", "CHIEF_EXEC" all map to "executive" because
// they all contain the relevant stems. Uppercase comparison avoids case drift.
function matchesRelFilter(label: string, filter: RelationFilter): boolean {
  const upper = label.toUpperCase();
  switch (filter) {
    case "all":
      return true;
    case "executive":
      // WHY these stems: covers CEO_OF, CFO_OF, CTO_OF, COO_OF, EXECUTIVE_CHAIR,
      // EXEC_DIRECTOR, OFFICER_OF, DIRECTOR_OF — all executive relationship types
      // used by the knowledge graph pipeline (S6 extraction).
      return (
        upper.includes("CEO") ||
        upper.includes("CFO") ||
        upper.includes("CTO") ||
        upper.includes("COO") ||
        upper.includes("CHAIR") ||
        upper.includes("EXEC") ||
        upper.includes("OFFICER") ||
        upper.includes("DIRECTOR")
      );
    case "investor":
      // WHY "HOLDS": covers HOLDS_STAKE, HOLDS_SHARES, HOLDS_POSITION
      return (
        upper.includes("INVEST") ||
        upper.includes("SHAREHOLDER") ||
        upper.includes("HOLDS") ||
        upper.includes("OWNED")
      );
    case "supplier":
      // WHY "MANUFACTUR" + "PRODUCES": supply chain edges use both naming conventions
      return upper.includes("SUPPL") || upper.includes("MANUFACTUR") || upper.includes("PRODUCES");
    case "customer":
      return upper.includes("CUSTOMER") || upper.includes("CLIENT") || upper.includes("USES");
    case "competitor":
      return upper.includes("COMPET") || upper.includes("RIVAL");
    default:
      // TypeScript exhaustiveness guard — should never reach here given the const union
      return true;
  }
}

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

export class GraphErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; errorMessage: string | null }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false, errorMessage: null };
  }

  static getDerivedStateFromError(error: Error): { hasError: boolean; errorMessage: string | null } {
    // WHY capture message: the sigma WebGL error and graphology data errors have
    // distinct messages — capturing helps diagnose "WebGL required" vs "UsageGraphError".
    return { hasError: true, errorMessage: error?.message ?? null };
  }

  override render() {
    if (this.state.hasError) {
      // WHY check "webgl" in message: if sigma threw a non-WebGL error (e.g., graphology
      // UsageGraphError from malformed data), show the actual message so the user knows
      // why the graph failed rather than blaming WebGL incorrectly.
      const isWebGLError =
        !this.state.errorMessage ||
        /webgl|context creation|rendering context/i.test(this.state.errorMessage);
      const displayMessage = isWebGLError
        ? "Graph unavailable — enable WebGL (hardware acceleration) in your browser."
        : `Graph unavailable: ${this.state.errorMessage}`;
      return (
        <div className="rounded-[2px] border border-border/40 bg-card/50 px-3 py-3">
          <p className="text-xs text-muted-foreground">{displayMessage}</p>
          {/* WHY window.location.reload: simplest recovery — no state to preserve */}
          <button
            onClick={() => window.location.reload()}
            className="mt-1.5 rounded-[2px] border border-border/40 px-3 py-1 text-xs text-muted-foreground hover:border-border hover:text-foreground"
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
  // WHY optional onNodeClick: when provided, clicking a node calls this callback
  // (for sidebar detail panel in IntelligenceTab). When absent, clicking navigates
  // to the entity's instrument page (original behavior in OverviewLayout sidebar).
  onNodeClick?: (nodeId: string, label: string, nodeType: string, degree: number, edges: Array<{label: string; weight: number; neighborId: string; neighborLabel: string}>) => void;
}

function GraphEvents({ centerEntityId, onNodeHover, onEdgeHover, onNodeClick }: GraphEventsProps) {
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
        if (node === centerEntityId) return;
        if (onNodeClick) {
          // Sidebar detail mode: collect connected edges for the detail panel
          const graph = sigma.getGraph();
          const attrs = graph.getNodeAttributes(node);
          const degree = graph.degree(node);
          const edges = graph.edges(node).map((edgeKey) => {
            const ea = graph.getEdgeAttributes(edgeKey);
            const [src, tgt] = graph.extremities(edgeKey);
            const neighborId = src === node ? tgt : src;
            const neighborAttrs = graph.getNodeAttributes(neighborId);
            return {
              label: ea.label as string,
              weight: ea.weight as number,
              neighborId,
              neighborLabel: neighborAttrs.label as string,
            };
          });
          onNodeClick(node, attrs.label as string, attrs.nodeType as string, degree, edges);
        } else {
          // Navigate mode: original behavior — go to entity instrument page
          router.push(`/instruments/${node}`);
        }
      },
    });
  }, [registerEvents, sigma, router, centerEntityId, onNodeHover, onEdgeHover, onNodeClick]);

  // WHY returns null: this component exists only to register side-effect event
  // listeners; it renders nothing to the DOM.
  return null;
}

// ── GraphLoader — builds graphology graph and runs layout ─────────────────────
// WHY separate: useLoadGraph must be inside <SigmaContainer> context.
// PLAN-0059 H-4: accepts `layout` prop to switch between force (ForceAtlas2)
// and hierarchical (degree-tier) layout algorithms.

interface GraphLoaderProps {
  data: EntityGraphData;
  centerEntityId: string;
  layout: "force" | "hierarchical";
}

function GraphLoader({ data, centerEntityId, layout }: GraphLoaderProps) {
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

      const color = ENTITY_TYPE_COLOR_MAP[node.type] ?? NODE_DEFAULT_COLOR;

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
      // WHY self-loop guard (edge.source !== edge.target): the API may return edges
      // where source and target are the same node (sentinel/null entity placeholder).
      // graphology throws "UsageGraphError: allowSelfLoops is false" in that case.
      if (graph.hasNode(edge.source) && graph.hasNode(edge.target) && edge.source !== edge.target) {
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
            // WHY hex literal (not token): sigma's WebGL renderer reads
            // hex strings on the node/edge data. #18181B mirrors --muted
            // (the elevated surface tone) from Terminal Dark globals.css.
            color: "#18181B",
          });
        }
      }
    }

    // ── Run layout ────────────────────────────────────────────────────────────
    if (graph.order > 0) {
      if (layout === "hierarchical") {
        // WHY degree-tier hierarchical: places high-degree nodes (hubs) at top,
        // low-degree nodes (leaves) at bottom. Creates a clear top-down hierarchy
        // that reveals organizational structure (e.g., parent companies on top,
        // subsidiaries below). Simple and deterministic — no extra library needed.
        const nodes = graph.nodes();
        // Compute degree for every node — more connections = higher importance tier
        const degrees = Object.fromEntries(nodes.map((n) => [n, graph.degree(n)]));
        const maxDeg = Math.max(...Object.values(degrees), 1); // guard against max=0

        nodes.forEach((n, i) => {
          // WHY 1 - (degree/maxDeg): degree=maxDeg → tier=0 (top), degree=0 → tier=1 (bottom)
          // WHY jitter: spread nodes within the same tier horizontally; modular index
          // spacing ensures they don't stack on top of each other.
          const tier = 1 - degrees[n] / maxDeg;
          const tierWidth = 100; // horizontal spread in sigma coordinates
          const xOffset = ((i % Math.ceil(nodes.length / 5)) / Math.ceil(nodes.length / 5)) * tierWidth - tierWidth / 2;
          graph.setNodeAttribute(n, "x", xOffset);
          graph.setNodeAttribute(n, "y", tier * 100 - 50);
        });
      } else {
        // WHY synchronous FA2 (not worker): The worker variant is async and requires
        // a separate Worker file. Synchronous FA2 runs in <50ms for ≤100 nodes —
        // acceptable for our use case. Worker is only needed for 500+ node graphs.

        // WHY inferSettings: automatically calibrates gravity, scaling, slow-down
        // based on graph density (order/edges ratio). We then override gravity
        // to a lower value to spread nodes more evenly across the canvas.
        const fa2Settings = forceAtlas2.inferSettings(graph);
        forceAtlas2.assign(graph, {
          iterations: 100,
          settings: {
            ...fa2Settings,
            gravity: 0.1,        // WHY low gravity: prevents all nodes collapsing to center
            adjustSizes: true,   // WHY adjustSizes: prevents node overlap by using node.size
            // WHY Barnes-Hut only for large graphs: the approximation improves O(n²)→O(n log n)
            // but introduces layout error at small scales. Only enable for 50+ nodes.
            barnesHutOptimize: graph.order > 50,
          },
        });
      }
    }

    // Pass the constructed + laid-out graphology graph to sigma for rendering
    loadGraph(graph);
  }, [data, centerEntityId, layout, loadGraph]);

  return null;
}

// ── FilterController — pushes filter state into sigma reducers ────────────────
// WHY a dedicated child component (not props on SigmaContainer settings):
// sigma.setSettings() lets us update edge/nodeReducer at any time without
// destroying and re-creating the SigmaContainer (which would re-initialize WebGL).
// Calling sigma.setSettings() + sigma.refresh() is O(edges) — fast enough for
// interactive filter controls (slider drag, pill click, keystroke).
//
// WHY inside SigmaContainer: useSigma() is a context hook — it must be a
// descendant of <SigmaContainer>. Cannot move this logic to the parent.

interface FilterControllerProps {
  activeRelFilter: RelationFilter;
  minWeight: number;   // 0–100 integer (threshold percentage)
  searchQuery: string;
  graphData: EntityGraphData;
}

function FilterController({ activeRelFilter, minWeight, searchQuery }: FilterControllerProps) {
  const sigma = useSigma();

  useEffect(() => {
    sigma.setSettings({
      // ── edgeReducer ──────────────────────────────────────────────────────────
      // Called by sigma for every edge before rendering. Returning { hidden: true }
      // removes the edge from the WebGL draw call — 0 cost for hidden edges.
      edgeReducer: (edge: string, data: Record<string, unknown>) => {
        const label = (data.label as string ?? "").toUpperCase();
        const weight = (data.weight as number) ?? 0;

        // WHY minWeight / 100: slider stores 0–100, graph stores 0–1 weight
        if (weight < minWeight / 100) return { ...data, hidden: true };

        // WHY activeRelFilter check AFTER weight: weight filter is cheaper
        // (arithmetic) so we short-circuit before the string includes() calls.
        if (activeRelFilter !== "all" && !matchesRelFilter(label, activeRelFilter)) {
          return { ...data, hidden: true };
        }

        return { ...data, hidden: false };
      },

      // ── nodeReducer ──────────────────────────────────────────────────────────
      // Called by sigma for every node before rendering. We dim non-matching
      // nodes by setting their color to near-invisible (matches the canvas bg).
      // WHY NOT hidden:true for non-matching nodes: hiding nodes that have edges
      // would cause sigma to error (dangling edge endpoints). Dimming keeps the
      // graph structure visible while making non-matches recede to background.
      nodeReducer: (node: string, data: Record<string, unknown>) => {
        if (!searchQuery) return data; // WHY early return: no search = no dimming

        const label = (data.label as string ?? "").toLowerCase();
        if (!label.includes(searchQuery.toLowerCase())) {
          // WHY #09090B (Terminal Dark --background): the graph canvas background
          // — using the token's hex makes unmatched nodes nearly invisible without
          // fully hiding them (avoids dangling-edge errors). Sigma reads hex from
          // node attrs, so the literal is required here.
          return { ...data, color: "#09090B", labelColor: "#09090B" };
        }
        return data;
      },
    });

    // WHY sigma.refresh(): setSettings alone does not re-render; refresh()
    // triggers a full sigma redraw applying the new reducers.
    sigma.refresh();
  }, [sigma, activeRelFilter, minWeight, searchQuery]);

  return null;
}

// ── NodeTooltipPanel ──────────────────────────────────────────────────────────
// WHY pointer-events-none: tooltip is informational only — it must not block
// mouse events from reaching the sigma canvas below it.

function NodeTooltipPanel({ tooltip }: { tooltip: NodeTooltip }) {
  return (
    <div
      className="pointer-events-none absolute z-50 rounded-[2px] border border-border/50 bg-card px-3 py-2"
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
      className="pointer-events-none absolute z-50 rounded-[2px] border border-border/50 bg-card px-3 py-2"
      style={{ left: tooltip.x + 12, top: tooltip.y - 8 }}
    >
      <p className="text-xs font-medium uppercase tracking-wider text-foreground">
        {displayLabel}
      </p>
      {/* WHY tabular-nums: the weight is a numeric value rendered to 2dp.
          tabular-nums prevents horizontal jitter as the tooltip refreshes
          across hovered edges with different weights — required by the
          Terminal Dark numeric-display rule (font-mono + tabular-nums for
          all numbers). */}
      <p className="mt-0.5 font-mono text-[10px] tabular-nums text-muted-foreground">
        Strength: {tooltip.weight.toFixed(2)}
      </p>
    </div>
  );
}

// ── GraphLegend ───────────────────────────────────────────────────────────────
// WHY bottom-left: follows Bloomberg convention — controls/info at corners,
// main canvas area unobstructed. backdrop-blur-sm softens the legend against
// complex graph backgrounds.

// PLAN-0057 Wave F-1: legend now reflects ONLY the entity types present in
// the current graph data so analysts aren't shown 13+ swatches when most
// graphs only have 4-5.  Unknown types surface in the default grey so the
// missing type is visible rather than silently absent.
function GraphLegend({ data }: { data: EntityGraphData }) {
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

// ── Main EntityGraph component ────────────────────────────────────────────────

export interface EntityGraphProps {
  data: EntityGraphData;
  centerEntityId: string;
  // WHY optional: when omitted the graph navigates to entity pages on click (default
  // behaviour). When provided (e.g. IntelligenceTab right sidebar) the host component
  // receives the clicked node's data and renders the detail panel instead.
  onNodeClick?: (
    nodeId: string,
    label: string,
    nodeType: string,
    degree: number,
    edges: Array<{ label: string; weight: number; neighborId: string; neighborLabel: string }>,
  ) => void;
}

// ── CameraResetButton — sigma hook to re-fit camera to the full graph ─────────
// WHY inside SigmaContainer: useSigma is a context hook — must be a descendant.
// Exposes a single "reset view" button that runs sigma.getCamera().animatedReset().
function CameraResetButton() {
  const sigma = useSigma();
  return (
    <button
      onClick={() => sigma.getCamera().animatedReset()}
      title="Reset camera to fit all nodes (R)"
      aria-label="Reset graph camera"
      className="rounded-[2px] border border-border/40 p-1 text-muted-foreground transition-colors hover:border-border/70 hover:text-foreground"
    >
      <Maximize2 className="h-3.5 w-3.5" />
    </button>
  );
}

// ── CameraAutoFit — auto-reset camera when the entity changes ─────────────────
// WHY separate component: useSigma is a context hook — must live inside
// SigmaContainer. We use a ref to compare the previous centerEntityId so the
// camera only resets when the anchor entity changes (not on every filter update).
//
// SA-3 UX improvement (2026-05-10): when the analyst navigates to a different
// entity (e.g., via the instrument page entity picker), the sigma camera preserves
// its previous position — the new graph renders off-screen. animatedReset() re-fits
// all nodes into view. We trigger on centerEntityId change only (not on every data
// refresh) to avoid disrupting in-progress panning.
function CameraAutoFit({ centerEntityId }: { centerEntityId: string }) {
  const sigma = useSigma();
  // Track previous entity so we only reset when it actually changes.
  const prevEntityRef = React.useRef<string>(centerEntityId);

  useEffect(() => {
    if (prevEntityRef.current !== centerEntityId) {
      prevEntityRef.current = centerEntityId;
      // Small delay lets GraphLoader finish building + FA2 before camera reset,
      // otherwise the reset fires while nodes are still at random positions.
      const timer = setTimeout(() => {
        sigma.getCamera().animatedReset();
      }, 150);
      return () => clearTimeout(timer);
    }
  }, [sigma, centerEntityId]);

  return null; // WHY null: this component is pure side-effect, renders nothing
}

// ── KeyboardResetListener — 'R' key resets graph camera ───────────────────────
// WHY inside SigmaContainer: useSigma context hook requirement.
// WHY 'R' (not Ctrl+R / Cmd+R): browser refresh is reserved; lowercase 'r' is
// unused in the sigma default bindings and follows Bloomberg keyboard navigation
// conventions where single-letter keys trigger view resets without modifier keys.
//
// SA-3 UX improvement (2026-05-10): keyboard shortcut for power users who switch
// entities frequently and need a fast way to re-center without reaching for the
// toolbar button. The listener only fires when the graph container has focus or
// no other interactive element is focused (guard: target is not an input/textarea).
function KeyboardResetListener() {
  const sigma = useSigma();

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      // WHY skip when target is an input: the 'R' key inside a search field
      // should type the letter, not reset the graph. Skip contenteditable too.
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable
      ) {
        return;
      }
      if (e.key === "r" || e.key === "R") {
        e.preventDefault();
        sigma.getCamera().animatedReset();
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [sigma]);

  return null; // WHY null: pure side-effect component
}

export function EntityGraph({ data, centerEntityId, onNodeClick }: EntityGraphProps) {
  const [nodeTooltip, setNodeTooltip] = useState<NodeTooltip | null>(null);
  const [edgeTooltip, setEdgeTooltip] = useState<EdgeTooltip | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // ── PLAN-0059 H-4 filter state ───────────────────────────────────────────────
  // WHY separate state atoms (not one object): React bails out on re-render when
  // the specific atom doesn't change — coarse-grained objects always re-render.
  const [activeRelFilter, setActiveRelFilter] = useState<RelationFilter>("all");
  // WHY lazy init for minWeight: if the graph is dense (>50 edges) auto-apply
  // a 30% strength floor so AAPL-scale graphs are readable on first load.
  // The analyst can always drag the slider back to 0 to see all edges.
  const [minWeight, setMinWeight] = useState<number>(() =>
    data.edges.length > DENSE_GRAPH_EDGE_THRESHOLD ? DENSE_GRAPH_AUTO_MIN_WEIGHT : 0
  );
  const [searchQuery, setSearchQuery] = useState("");
  const [layout, setLayout] = useState<"force" | "hierarchical">("force");

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
      <div className="flex h-[460px] items-center justify-center rounded-[2px] border border-border/40 bg-card/30 text-[11px] text-muted-foreground">
        No relationship data available
      </div>
    );
  }

  return (
    <GraphErrorBoundary>
      {/* ── Filter controls row (PLAN-0059 H-4) ─────────────────────────────── */}
      {/* WHY above SigmaContainer: controls must be interactive DOM elements;
          placing them inside sigma's canvas div would cause z-index conflicts.
          mb-2 gives 8px breathing room between controls and the graph frame. */}
      <div className="mb-2 flex flex-wrap items-center gap-2">

        {/* ── Relation-type filter pills ─────────────────────────────────────── */}
        {/* WHY pills (not dropdown): pills let analysts see all options at once
            and toggle without opening a menu — critical for flow state in
            fast financial analysis. At max 6 pills they still fit on one row. */}
        <div className="flex gap-1" data-testid="filter-pills">
          {RELATION_TYPES.map((type) => {
            const isActive = activeRelFilter === type;
            return (
              <button
                key={type}
                onClick={() => setActiveRelFilter(type)}
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
            onValueChange={([v]) => setMinWeight(v ?? 0)}
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
          onChange={(e) => setSearchQuery(e.target.value)}
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
          {data.edges.length > DENSE_GRAPH_EDGE_THRESHOLD && (
            <span
              title={`Dense graph (${data.edges.length} edges) — strength filter auto-applied`}
              className="rounded-[2px] bg-warning/15 px-1.5 py-0.5 font-mono text-[9px] text-warning"
            >
              {data.edges.length} edges
            </span>
          )}
          <button
            onClick={() => setLayout("force")}
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
            onClick={() => setLayout("hierarchical")}
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

      {/* ── Graph canvas container ────────────────────────────────────────────── */}
      <div
        ref={containerRef}
        // WHY bg-background (was inline #0A0E14): the retired Bloomberg Dark
        // background hex; the Terminal Dark `--background` token now resolves
        // to #09090B and the graph wrapper inherits the canonical app surface
        // color via the Tailwind utility — no inline hex required on the div.
        className="relative h-[460px] overflow-hidden rounded-[2px] border border-border/40 bg-background"
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
            // WHY hex literal #83838A: sigma's `labelColor.color` setting is read
            // by its WebGL pipeline; CSS classes never reach it. The hex mirrors
            // --muted-foreground from globals.css (Terminal Dark zinc-500.5).
            labelColor: { color: "#83838A" },
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
          // WHY inline style with var(...): SigmaContainer accepts inline
          // style only — applying bg-background to it doesn't reliably reach
          // the inner canvas. Using the CSS variable keeps a single source
          // of truth for the Terminal Dark --background hue.
          style={{ background: "hsl(var(--background))" }}
        >
          {/* GraphLoader builds the graphology graph and passes it to sigma.
              layout prop controls FA2 vs degree-tier positioning. */}
          <GraphLoader data={data} centerEntityId={centerEntityId} layout={layout} />

          {/* GraphEvents registers hover/click listeners on the sigma instance */}
          <GraphEvents
            centerEntityId={centerEntityId}
            onNodeHover={handleNodeHover}
            onEdgeHover={handleEdgeHover}
            onNodeClick={onNodeClick}
          />

          {/* FilterController pushes edge/nodeReducer into sigma on every filter
              state change — avoids destroying/recreating the SigmaContainer. */}
          <FilterController
            activeRelFilter={activeRelFilter}
            minWeight={minWeight}
            searchQuery={searchQuery}
            graphData={data}
          />

          {/* SA-3 (2026-05-10): auto-fit camera when entity changes so the new
              graph is visible without manual reset. Must be inside SigmaContainer
              for the useSigma() hook to work. */}
          <CameraAutoFit centerEntityId={centerEntityId} />

          {/* SA-3 (2026-05-10): keyboard shortcut 'R' to reset camera.
              Must be inside SigmaContainer for useSigma() context. */}
          <KeyboardResetListener />

          {/* CameraResetButton — rendered INSIDE SigmaContainer because it uses
              useSigma() context hook. Positioned absolute top-right within the
              canvas so it floats over the graph without interfering with mouse
              events (via z-20 above the hint overlay at z-10). */}
          <div className="absolute right-2 bottom-8 z-20">
            <CameraResetButton />
          </div>
        </SigmaContainer>

        {/* Tooltips — rendered inside the container div so position:absolute
            is relative to the container (not the page). */}
        {nodeTooltip && <NodeTooltipPanel tooltip={nodeTooltip} />}
        {edgeTooltip && <EdgeTooltipPanel tooltip={edgeTooltip} />}

        {/* Legend — bottom-left corner */}
        <GraphLegend data={data} />

        {/* Controls hint + camera reset — top-right corner */}
        {/* WHY CameraResetButton inside SigmaContainer context is hoisted outside:
            The button is DOM-level — we render it as a floating overlay on the canvas.
            The camera reset logic uses useSigma() which requires SigmaContainer context.
            We use a dedicated CameraResetButton component that renders the sigma hook
            INSIDE the SigmaContainer above — but we place its trigger in the overlay
            via the separate SigmaContainer child (declared above). The overlay here
            is purely a hint label. */}
        <div className="absolute right-2 top-2 z-10 flex items-center gap-1 rounded-[2px] border border-border/40 bg-card/80 px-2 py-1 backdrop-blur-sm">
          <span className="text-[9px] text-muted-foreground/60">
            Scroll · Drag · Click · R to fit
          </span>
        </div>
      </div>
    </GraphErrorBoundary>
  );
}
