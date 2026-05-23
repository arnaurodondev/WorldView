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

// WHY hex literal (not Tailwind): sigma WebGL reads hex/rgb from node attributes;
// CSS classes never reach the canvas. Mirrors --muted-foreground (#83838A) from globals.css.
const NODE_DEFAULT_COLOR = "#83838A";

// ── matchesRelFilter ──────────────────────────────────────────────────────────
// WHY pattern-based (not exact-match): relation labels vary by data source.
// "CEO_OF", "EXECUTIVE_CHAIR", "CHIEF_EXEC" all map to "executive".
export function matchesRelFilter(label: string, filter: RelationFilter): boolean {
  const upper = label.toUpperCase();
  switch (filter) {
    case "all": return true;
    case "executive":
      return upper.includes("CEO") || upper.includes("CFO") || upper.includes("CTO") ||
        upper.includes("COO") || upper.includes("CHAIR") || upper.includes("EXEC") ||
        upper.includes("OFFICER") || upper.includes("DIRECTOR");
    case "investor":
      return upper.includes("INVEST") || upper.includes("SHAREHOLDER") ||
        upper.includes("HOLDS") || upper.includes("OWNED");
    case "supplier":
      return upper.includes("SUPPL") || upper.includes("MANUFACTUR") || upper.includes("PRODUCES");
    case "customer":
      return upper.includes("CUSTOMER") || upper.includes("CLIENT") || upper.includes("USES");
    case "competitor":
      return upper.includes("COMPET") || upper.includes("RIVAL");
    default:
      return true;
  }
}

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
  /** Up to 3 evidence text snippets sourced from relation_evidence_raw (W7 T-19). */
  evidence_snippets: string[];
  x: number;
  y: number;
}

// ── GraphEvents ───────────────────────────────────────────────────────────────
// WHY separate: useRegisterEvents + useSigma are context hooks that only work
// when rendered as a descendant of <SigmaContainer>.

/** Full edge info emitted on click — all fields sourced from graphology edge attributes. */
export interface SelectedEdgeInfo {
  id: string;
  label: string;
  weight: number;
  evidence_snippets: string[];
  relation_summary?: string | null;
  sourceId: string;
  targetId: string;
  sourceLabel: string;
  targetLabel: string;
}

interface GraphEventsProps {
  centerEntityId: string;
  onNodeHover: (tooltip: NodeTooltip | null) => void;
  onEdgeHover: (tooltip: EdgeTooltip | null) => void;
  onNodeClick?: (nodeId: string, label: string, nodeType: string, degree: number,
    edges: Array<{label: string; weight: number; neighborId: string; neighborLabel: string}>) => void;
  /** Called when the user clicks an edge — fires the full edge data from graphology attrs. */
  onEdgeClick?: (info: SelectedEdgeInfo) => void;
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
        onEdgeHover({
          label: attrs.label as string,
          weight: attrs.weight as number,
          evidence_snippets: (attrs.evidence_snippets as string[] | undefined) ?? [],
          x: event.x,
          y: event.y,
        });
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
          // PRD-0089 F2 step 11 (§6.6): prefer the ticker attribute over the
          // raw sigma node id (entity_id UUID). Falls back to UUID for
          // non-tradable nodes; the middleware will resolve via
          // resolve_security_id and 404 if there is no instrument.
          const ticker = sigma.getGraph().getNodeAttribute(node, "ticker") as
            | string
            | undefined;
          router.push(`/instruments/${ticker || node}`);
        }
      },
      clickEdge: ({ edge }) => {
        if (!onEdgeClick) return;
        const graph = sigma.getGraph();
        const attrs = graph.getEdgeAttributes(edge);
        const [src, tgt] = graph.extremities(edge);
        onEdgeClick({
          id: edge,
          label: (attrs.label as string | undefined) ?? "",
          weight: (attrs.weight as number | undefined) ?? 0,
          evidence_snippets: (attrs.evidence_snippets as string[] | undefined) ?? [],
          relation_summary: (attrs.relation_summary as string | null | undefined) ?? null,
          sourceId: src,
          targetId: tgt,
          sourceLabel: (graph.getNodeAttribute(src, "label") as string | undefined) ?? src,
          targetLabel: (graph.getNodeAttribute(tgt, "label") as string | undefined) ?? tgt,
        });
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
        // PRD-0089 F2 step 11 (§6.6): persist ticker on the graph attrs so the
        // clickNode handler can build a ticker-first URL without re-querying.
        // Undefined for non-tradable nodes (sectors/persons/events).
        ticker: node.ticker,
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
          graph.addEdge(edge.source, edge.target, {
            id: edge.id,
            label: edge.label,
            weight: edge.weight,
            // WHY store evidence_snippets on graphology attrs: EdgeTooltipPanel
            // reads them via sigma.getEdgeAttributes() in the enterEdge event
            // handler — avoids a separate lookup into the raw EntityGraph data.
            evidence_snippets: edge.evidence_snippets ?? [],
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

interface FilterControllerProps {
  activeRelFilter: RelationFilter;
  minWeight: number;
  searchQuery: string;
  graphData: EntityGraphData;
}

// WHY declare outside component: stable reference, avoids recreating in the edgeReducer
// closure. Mirrors DECAY_ALPHA in EntityGraph.tsx — must stay in sync.
const DECAY_ALPHA_MAP: Record<string, number> = {
  PERMANENT: 1.0, DURABLE: 1.0,
  SLOW: 0.7, MEDIUM: 0.7,
  FAST: 0.4, EPHEMERAL: 0.4,
};

function hexToRgba(hex: string, alpha: number): string {
  const clean = hex.replace("#", "");
  const r = parseInt(clean.substring(0, 2), 16);
  const g = parseInt(clean.substring(2, 4), 16);
  const b = parseInt(clean.substring(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

export function FilterController({ activeRelFilter, minWeight, searchQuery }: FilterControllerProps) {
  const sigma = useSigma();

  useEffect(() => {
    sigma.setSettings({
      edgeReducer: (edge: string, data: Record<string, unknown>) => {
        const label = (data.label as string ?? "").toUpperCase();
        const weight = (data.weight as number) ?? 0;
        // WHY minWeight / 100: slider stores 0–100, graph stores 0–1 weight
        if (weight < minWeight / 100) return { ...data, hidden: true };
        if (activeRelFilter !== "all" && !matchesRelFilter(label, activeRelFilter)) {
          return { ...data, hidden: true };
        }
        // WHY read decay_class from graphology attrs (not `data`):
        // `data` in edgeReducer is sigma's rendered state — the raw graphology
        // attribute decay_class is only available via sigma.getGraph().getEdgeAttributes().
        // We apply decay-based alpha so PERMANENT edges are visually dominant and
        // EPHEMERAL edges recede, helping analysts distinguish structural from transient ties.
        const attrs = sigma.getGraph().getEdgeAttributes(edge);
        const decayClass = (attrs.decay_class as string | undefined) ?? "MEDIUM";
        const alpha = DECAY_ALPHA_MAP[decayClass] ?? 0.7;
        const baseColor = (data.color as string | undefined) ?? "#71717A";
        const edgeColor = baseColor.startsWith("#") ? hexToRgba(baseColor, alpha) : baseColor;
        return { ...data, hidden: false, color: edgeColor };
      },
      nodeReducer: (node: string, data: Record<string, unknown>) => {
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
  }, [sigma, activeRelFilter, minWeight, searchQuery]);

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
    <div className="pointer-events-none absolute z-50 max-w-[280px] rounded-[2px] border border-border/50 bg-card px-3 py-2"
      style={{ left: tooltip.x + 12, top: tooltip.y - 8 }}>
      <p className="text-xs font-medium uppercase tracking-wider text-foreground">{displayLabel}</p>
      {/* WHY tabular-nums + font-mono: numeric weight value; tabular-nums prevents
          horizontal jitter as tooltip refreshes across different-weight edges. */}
      <p className="mt-0.5 font-mono text-[10px] tabular-nums text-muted-foreground">
        Strength: {tooltip.weight.toFixed(2)}
      </p>
      {/* WHY evidence snippets (T-19): surfaces the raw source text that supports
          this relation claim. Analysts can evaluate credibility without leaving
          the graph. Limited to 2 snippets to keep the tooltip compact. */}
      {tooltip.evidence_snippets.length > 0 && (
        <div className="mt-1.5 space-y-1 border-t border-border/30 pt-1.5">
          {tooltip.evidence_snippets.slice(0, 2).map((snippet, i) => (
            <p key={i} className="text-[9px] text-muted-foreground/80 leading-tight line-clamp-2">
              {`"${snippet}"`}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
