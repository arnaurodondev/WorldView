/**
 * components/instrument/graph/SigmaInternalComponents.tsx
 * — Sigma context components that MUST be rendered inside <SigmaContainer>
 *
 * WHY THIS FILE EXISTS: sigma hooks (useLoadGraph, useSigma, useRegisterEvents)
 * are React context hooks that only work as descendants of <SigmaContainer>.
 * Grouping all sigma-internal components here keeps EntityGraph.tsx under 400 lines
 * while making the constraint visually explicit.
 *
 * COMPONENTS:
 *   - GraphLoader         — builds graphology graph + runs ForceAtlas2/hierarchical layout
 *   - FilterController    — pushes edge/nodeReducer into sigma on filter state change
 *   - CameraAutoFit       — auto-resets camera when centerEntityId changes
 *   - KeyboardResetListener — 'R' key shortcut to reset camera
 *   - CameraResetButton   — UI button to reset camera (uses useSigma context)
 *
 * WHO USES IT: EntityGraph.tsx — never directly by pages.
 */

import React, { useEffect } from "react";
import { useLoadGraph, useSigma, useRegisterEvents } from "@react-sigma/core";
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import { Maximize2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { ENTITY_TYPE_COLOR_MAP } from "@/lib/entity-types";
import type { EntityGraph as EntityGraphData } from "@/types/api";
import type { RelationFilter } from "./GraphControls";
// PLAN-0099 W4 FIX: import matchesRelFilter from graphFilterUtils — the SINGLE
// source of truth. This file previously kept its OWN copy of matchesRelFilter,
// so the FilterController (which gates which edges sigma renders) used the stale
// duplicate while the unit tests + GraphStats counting used the canonical one.
// Two divergent copies meant a fix in graphFilterUtils.ts (e.g. the investor /
// owns_stake_in miss) silently did NOT reach the canvas. Re-export it so the few
// external importers of `matchesRelFilter` from this module keep working.
import { matchesRelFilter } from "./graphFilterUtils";

export { matchesRelFilter };

// WHY hex literal (not Tailwind): sigma WebGL reads hex/rgb from node attributes;
// CSS classes never reach the canvas. Mirrors --muted-foreground (#83838A) from globals.css.
const NODE_DEFAULT_COLOR = "#83838A";

// ── NodeTooltip / EdgeTooltip types (shared with EntityGraph.tsx) ─────────────

export interface NodeTooltip {
  label: string;
  type: string;
  degree: number;
  x: number;
  y: number;
}

export interface EdgeTooltip {
  label: string;
  weight: number;
  x: number;
  y: number;
}

// ── GraphEvents ───────────────────────────────────────────────────────────────
// WHY separate: useRegisterEvents + useSigma are context hooks that only work
// when rendered as a descendant of <SigmaContainer>.

interface GraphEventsProps {
  centerEntityId: string;
  onNodeHover: (tooltip: NodeTooltip | null) => void;
  onEdgeHover: (tooltip: EdgeTooltip | null) => void;
  onNodeClick?: (nodeId: string, label: string, nodeType: string, degree: number,
    edges: Array<{label: string; weight: number; neighborId: string; neighborLabel: string}>) => void;
  /** Block I T-27: fires when the user clicks a graph edge.
   *  edgeId is the graphology internal edge key (same as GraphEdge.id from the
   *  API response — GraphLoader sets it via graph.addEdgeWithKey(edge.id, …)). */
  onEdgeClick?: (edgeId: string) => void;
}

export function GraphEvents({ centerEntityId, onNodeHover, onEdgeHover, onNodeClick, onEdgeClick }: GraphEventsProps) {
  const sigma = useSigma();
  const registerEvents = useRegisterEvents();
  const router = useRouter();

  useEffect(() => {
    registerEvents({
      enterNode: ({ node, event }) => {
        const graph = sigma.getGraph();
        const attrs = graph.getNodeAttributes(node);
        onNodeHover({ label: attrs.label as string, type: attrs.nodeType as string,
          degree: graph.degree(node), x: event.x, y: event.y });
      },
      leaveNode: () => onNodeHover(null),
      enterEdge: ({ edge, event }) => {
        const graph = sigma.getGraph();
        const attrs = graph.getEdgeAttributes(edge);
        onEdgeHover({ label: attrs.label as string, weight: attrs.weight as number, x: event.x, y: event.y });
      },
      leaveEdge: () => onEdgeHover(null),
      clickNode: ({ node }) => {
        if (node === centerEntityId) return;
        if (onNodeClick) {
          const graph = sigma.getGraph();
          const attrs = graph.getNodeAttributes(node);
          const edges = graph.edges(node).map((edgeKey) => {
            const ea = graph.getEdgeAttributes(edgeKey);
            const [src, tgt] = graph.extremities(edgeKey);
            const neighborId = src === node ? tgt : src;
            return { label: ea.label as string, weight: ea.weight as number,
              neighborId, neighborLabel: graph.getNodeAttributes(neighborId).label as string };
          });
          onNodeClick(node, attrs.label as string, attrs.nodeType as string, graph.degree(node), edges);
        } else {
          router.push(`/instruments/${node}`);
        }
      },
      // WHY clickEdge (Block I T-27): edge clicks open EdgeDetailCard in the
      // right rail. The edge key in graphology is set to edge.id from the API
      // payload (see GraphLoader.addEdgeWithKey), so sigma's edge key == API edge id.
      clickEdge: ({ edge }) => {
        if (onEdgeClick) {
          onEdgeClick(edge);
        }
      },
    });
  }, [registerEvents, sigma, router, centerEntityId, onNodeHover, onEdgeHover, onNodeClick, onEdgeClick]);

  return null;
}

// ── GraphLoader ───────────────────────────────────────────────────────────────
// Builds graphology graph and runs ForceAtlas2 or hierarchical layout.
// PLAN-0059 H-4: layout prop switches between force (ForceAtlas2) and hierarchical.

interface GraphLoaderProps {
  data: EntityGraphData;
  centerEntityId: string;
  layout: "force" | "hierarchical";
}

export function GraphLoader({ data, centerEntityId, layout }: GraphLoaderProps) {
  const loadGraph = useLoadGraph();

  useEffect(() => {
    // WHY undirected + multi:false: KG edges are bidirectional; multi:false prevents duplicates.
    // WHY allowSelfLoops:false: self-loops crash ForceAtlas2 (FK-001 known issue).
    const graph = new Graph({ type: "undirected", multi: false, allowSelfLoops: false });

    for (const node of data.nodes) {
      const isCenter = node.id === centerEntityId;
      // WHY 3-tier sizing: center (20) dominant, direct neighbors (10) medium, depth-2 (7) small.
      const baseSize = isCenter ? 20 : (node.size ?? 1) >= 2 ? 10 : 7;
      const color = ENTITY_TYPE_COLOR_MAP[node.type] ?? NODE_DEFAULT_COLOR;
      graph.addNode(node.id, {
        label: node.label,
        // WHY nodeType (not type): sigma/graphology reserves 'type' for renderer type (e.g., "circle").
        nodeType: node.type,
        x: Math.random() * 100 - 50,
        y: Math.random() * 100 - 50,
        size: baseSize,
        color,
        borderColor: isCenter ? "#FFFFFF" : color,
        zIndex: isCenter ? 10 : 1,
      });
    }

    for (const edge of data.edges) {
      if (graph.hasNode(edge.source) && graph.hasNode(edge.target) && edge.source !== edge.target) {
        if (!graph.hasEdge(edge.source, edge.target)) {
          // BUG FIX (PLAN-0099 Wave 2): use addEdgeWithKey(edge.id, …) — NOT
          // addEdge(). graphology's addEdge() auto-generates an internal key
          // ("geid_…"), so sigma's clickEdge handler was emitting that synthetic
          // key while the GraphEvents docstring (and every consumer) assumed
          // the key WAS the API-level GraphEdge.id. Result: edge clicks could
          // never be resolved back to a KG relation_id and the edge inspector
          // always fell into its "not found" branch. With addEdgeWithKey the
          // graphology key == GraphEdge.id == KG relation_id end-to-end.
          graph.addEdgeWithKey(edge.id, edge.source, edge.target, {
            label: edge.label, weight: edge.weight,
            size: Math.max(0.5, edge.weight * 2),
            color: "#18181B",
          });
        }
      }
    }

    if (graph.order > 0) {
      if (layout === "hierarchical") {
        const nodes = graph.nodes();
        const degrees = Object.fromEntries(nodes.map((n) => [n, graph.degree(n)]));
        const maxDeg = Math.max(...Object.values(degrees), 1);
        nodes.forEach((n, i) => {
          const tier = 1 - degrees[n] / maxDeg;
          const tierWidth = 100;
          const xOffset = ((i % Math.ceil(nodes.length / 5)) / Math.ceil(nodes.length / 5)) * tierWidth - tierWidth / 2;
          graph.setNodeAttribute(n, "x", xOffset);
          graph.setNodeAttribute(n, "y", tier * 100 - 50);
        });
      } else {
        // WHY synchronous FA2 (not worker): sync FA2 runs in <50ms for ≤100 nodes.
        // WHY inferSettings: calibrates gravity/scaling based on graph density.
        const fa2Settings = forceAtlas2.inferSettings(graph);
        forceAtlas2.assign(graph, {
          iterations: 100,
          settings: { ...fa2Settings, gravity: 0.1, adjustSizes: true, barnesHutOptimize: graph.order > 50 },
        });
      }
    }

    loadGraph(graph);
  }, [data, centerEntityId, layout, loadGraph]);

  return null;
}

// ── FilterController ──────────────────────────────────────────────────────────
// Pushes edge/nodeReducer into sigma on every filter state change.
// WHY dedicated child: sigma.setSettings() avoids destroying/recreating SigmaContainer
// (which would re-initialize WebGL). O(edges) per change — fast for interactive controls.

// WHY hex literals for the selection accent: sigma's WebGL pipeline reads node/
// edge colors from graph attributes — CSS variables and Tailwind classes never
// reach the canvas. #FFD60A mirrors --primary (Terminal Dark trading yellow,
// globals.css line ~109); if the design system retunes --primary this constant
// must follow (same contract as NODE_DEFAULT_COLOR above).
const SELECTION_ACCENT_HEX = "#FFD60A";

interface FilterControllerProps {
  activeRelFilter: RelationFilter;
  minWeight: number;
  searchQuery: string;
  graphData: EntityGraphData;
  /** PLAN-0099 Wave 2 — the node selected in the inspector (highlighted on canvas). */
  selectedNodeId?: string | null;
  /** PLAN-0099 Wave 2 — the edge selected in the inspector. Key == GraphEdge.id
   *  (guaranteed by the addEdgeWithKey fix in GraphLoader). */
  selectedEdgeId?: string | null;
  /** PLAN-0099 W4 FIX — reports how many edges remain visible after the
   *  pill/strength filters are applied, so the toolbar can show "X of Y edges".
   *  WHY: previously the relation pills + strength slider only HID edges inside
   *  sigma's reducer; the GraphStats strip (rendered by the parent column from
   *  the unfiltered graphData) never changed, so analysts perceived the pills as
   *  no-ops. Surfacing the post-filter count is the visible proof the filter
   *  applied. The search box only DIMS nodes (never hides), so it does not
   *  affect this edge count by design. */
  onVisibleEdgeCountChange?: (visible: number, total: number) => void;
}

export function FilterController({
  activeRelFilter,
  minWeight,
  searchQuery,
  selectedNodeId = null,
  selectedEdgeId = null,
  onVisibleEdgeCountChange,
}: FilterControllerProps) {
  const sigma = useSigma();

  // ── Report visible-edge count to the parent (pill/strength filter feedback) ──
  // WHY a separate effect (not folded into the reducer effect): the reducer is a
  // pure render-time function sigma calls per edge — calling setState from inside
  // it would fire on every frame. Here we count once per filter change. We count
  // an edge "visible" using the SAME predicate the edgeReducer uses below
  // (weight >= minWeight/100 AND matches the active relation filter) so the
  // toolbar count and the canvas can never disagree.
  useEffect(() => {
    if (!onVisibleEdgeCountChange) return;
    const graph = sigma.getGraph();
    let visible = 0;
    let total = 0;
    graph.forEachEdge((_edge, attrs) => {
      total += 1;
      const label = ((attrs.label as string) ?? "").toUpperCase();
      const weight = (attrs.weight as number) ?? 0;
      if (weight < minWeight / 100) return;
      if (activeRelFilter !== "all" && !matchesRelFilter(label, activeRelFilter)) return;
      visible += 1;
    });
    onVisibleEdgeCountChange(visible, total);
    // graphData identity changes when a new graph loads (depth/type filter), so
    // include sigma in deps to recount after GraphLoader swaps the graph.
  }, [sigma, activeRelFilter, minWeight, onVisibleEdgeCountChange]);

  useEffect(() => {
    // WHY selection lives INSIDE the same reducers as the filters (not a second
    // controller): sigma.setSettings replaces the whole reducer — two sibling
    // components each calling setSettings would silently clobber each other's
    // reducer (last-write-wins). Folding both concerns into one reducer keeps
    // a single source of truth for per-element render overrides.
    sigma.setSettings({
      edgeReducer: (edge: string, data: Record<string, unknown>) => {
        const label = (data.label as string ?? "").toUpperCase();
        const weight = (data.weight as number) ?? 0;
        // WHY minWeight / 100: slider stores 0–100, graph stores 0–1 weight
        if (weight < minWeight / 100) return { ...data, hidden: true };
        if (activeRelFilter !== "all" && !matchesRelFilter(label, activeRelFilter)) {
          return { ...data, hidden: true };
        }
        // ── Selected-edge highlight (PLAN-0099 Wave 2) ──────────────────────
        // Accent color + a 2px-min size bump so the selected relation is
        // findable even in a dense hairball. zIndex lifts it above siblings.
        if (selectedEdgeId && edge === selectedEdgeId) {
          return {
            ...data,
            hidden: false,
            color: SELECTION_ACCENT_HEX,
            size: Math.max(2, ((data.size as number) ?? 1) * 1.5),
            zIndex: 10,
          };
        }
        return { ...data, hidden: false };
      },
      nodeReducer: (node: string, data: Record<string, unknown>) => {
        // ── Selected-node highlight (PLAN-0099 Wave 2) ──────────────────────
        // WHY checked BEFORE the search dim: an explicitly selected node must
        // stay visible even if the analyst's search box would otherwise dim it.
        // highlighted:true gives sigma's label a contrasting background;
        // forceLabel guarantees the label paints regardless of the
        // labelRenderedSizeThreshold; the size bump (+40%) makes the selection
        // visible in peripheral vision without re-running the layout.
        if (selectedNodeId && node === selectedNodeId) {
          return {
            ...data,
            color: SELECTION_ACCENT_HEX,
            highlighted: true,
            forceLabel: true,
            size: ((data.size as number) ?? 7) * 1.4,
            zIndex: 11,
          };
        }
        if (!searchQuery) return data;
        const label = (data.label as string ?? "").toLowerCase();
        if (!label.includes(searchQuery.toLowerCase())) {
          // WHY #09090B (Terminal Dark --background): makes unmatched nodes nearly invisible
          // without fully hiding them (avoids dangling-edge errors in sigma).
          return { ...data, color: "#09090B", labelColor: "#09090B" };
        }
        return data;
      },
    });
    sigma.refresh();
  }, [sigma, activeRelFilter, minWeight, searchQuery, selectedNodeId, selectedEdgeId]);

  return null;
}

// ── FocusNodeController ───────────────────────────────────────────────────────
// PLAN-0099 Wave 2 — "Focus graph here" action from the node inspector.
// Animates the camera to centre on the requested node at a closer zoom ratio.

interface FocusNodeControllerProps {
  /** Node to centre the camera on, or null when no focus is requested. */
  focusNodeId: string | null;
  /** Monotonic counter — bumping it re-fires the focus animation even when the
   *  SAME node is focused twice in a row (useEffect dep on the id alone would
   *  no-op the second click after the analyst panned away). */
  focusNonce: number;
}

export function FocusNodeController({ focusNodeId, focusNonce }: FocusNodeControllerProps) {
  const sigma = useSigma();

  useEffect(() => {
    if (!focusNodeId) return;
    const graph = sigma.getGraph();
    if (!graph.hasNode(focusNodeId)) return;
    // WHY graph coords → camera state: sigma's camera works in normalised
    // graph space; getNodeAttributes x/y are the layout coordinates that
    // sigma normalises internally. viewportToFramedGraph round-trips are not
    // needed — sigma.getNodeDisplayData returns the framed position directly.
    const display = sigma.getNodeDisplayData(focusNodeId);
    if (!display) return;
    // ratio 0.4 ≈ "zoomed into the neighbourhood" — close enough to read the
    // node's local edges, far enough to keep 1-hop context on screen.
    sigma.getCamera().animate({ x: display.x, y: display.y, ratio: 0.4 }, { duration: 350 });
  }, [sigma, focusNodeId, focusNonce]);

  return null;
}

// ── CameraAutoFit ─────────────────────────────────────────────────────────────
// SA-3 (2026-05-10): auto-reset camera when entity changes so the new graph is visible.

export function CameraAutoFit({ centerEntityId }: { centerEntityId: string }) {
  const sigma = useSigma();
  const prevEntityRef = React.useRef<string>(centerEntityId);

  useEffect(() => {
    if (prevEntityRef.current !== centerEntityId) {
      prevEntityRef.current = centerEntityId;
      // WHY 150ms delay: lets GraphLoader finish building + FA2 before camera reset.
      const timer = setTimeout(() => { sigma.getCamera().animatedReset(); }, 150);
      return () => clearTimeout(timer);
    }
  }, [sigma, centerEntityId]);

  return null;
}

// ── KeyboardResetListener ─────────────────────────────────────────────────────
// SA-3 (2026-05-10): 'R' key shortcut for power users who switch entities frequently.

export function KeyboardResetListener() {
  const sigma = useSigma();

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      // WHY skip inputs: 'R' inside a search field should type the letter, not reset the graph.
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable) return;
      if (e.key === "r" || e.key === "R") { e.preventDefault(); sigma.getCamera().animatedReset(); }
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [sigma]);

  return null;
}

// ── CameraResetButton ─────────────────────────────────────────────────────────
// WHY inside SigmaContainer: useSigma is a context hook — must be a descendant.

export function CameraResetButton() {
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

// ── NodeTooltipPanel ──────────────────────────────────────────────────────────
// WHY pointer-events-none: tooltip is informational only — must not block sigma canvas.

export function NodeTooltipPanel({ tooltip }: { tooltip: NodeTooltip }) {
  return (
    <div className="pointer-events-none absolute z-50 rounded-[2px] border border-border/50 bg-card px-3 py-2"
      style={{ left: tooltip.x + 12, top: tooltip.y - 8 }}>
      <p className="text-xs font-medium text-foreground">{tooltip.label}</p>
      <p className="mt-0.5 text-[10px] capitalize text-muted-foreground">Type: {tooltip.type}</p>
      <p className="text-[10px] text-muted-foreground">Relationships: {tooltip.degree}</p>
    </div>
  );
}

// ── EdgeTooltipPanel ──────────────────────────────────────────────────────────

export function EdgeTooltipPanel({ tooltip }: { tooltip: EdgeTooltip }) {
  const displayLabel = tooltip.label.replace(/_/g, " ").toLowerCase();
  return (
    <div className="pointer-events-none absolute z-50 rounded-[2px] border border-border/50 bg-card px-3 py-2"
      style={{ left: tooltip.x + 12, top: tooltip.y - 8 }}>
      <p className="text-xs font-medium uppercase tracking-wider text-foreground">{displayLabel}</p>
      {/* WHY tabular-nums + font-mono: numeric weight value; tabular-nums prevents
          horizontal jitter as tooltip refreshes across different-weight edges. */}
      <p className="mt-0.5 font-mono text-[10px] tabular-nums text-muted-foreground">
        Strength: {tooltip.weight.toFixed(2)}
      </p>
    </div>
  );
}
