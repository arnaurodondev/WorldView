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
 * PLAN-0059 Wave H-4: Added interactive filter controls:
 *   - Filter pills (by relationship category: all/executive/investor/supplier/customer/competitor)
 *   - Edge-strength slider (min weight threshold 0–100%)
 *   - Node search input (dims non-matching nodes in sigma via nodeReducer)
 *   - Layout switcher (force = ForceAtlas2, hierarchical = degree-tier layout)
 *
 * WHO USES IT: components/instrument/IntelligenceTab.tsx (Intelligence tab, loaded via next/dynamic)
 * DATA SOURCE: S9 GET /v1/entities/{entityId}/graph?depth=2
 * DESIGN REFERENCE: PRD-0028 §6.5 Intelligence tab, ADR-F-08
 *
 * SUB-COMPONENTS (extracted for PLAN-0089 D-3):
 *   - graph/GraphControls.tsx           — filter pills, strength slider, search, layout switcher
 *   - graph/GraphLegend.tsx             — entity type color legend (bottom-left corner)
 *   - graph/SigmaInternalComponents.tsx — GraphLoader, FilterController, GraphEvents,
 *                                          CameraAutoFit, KeyboardResetListener, CameraResetButton,
 *                                          NodeTooltipPanel, EdgeTooltipPanel
 */

import React, { useRef, useState, useCallback } from "react";
import { SigmaContainer } from "@react-sigma/core";
// WHY import sigma CSS: provides the sigma WebGL canvas sizing reset (canvas fills container).
import "@react-sigma/core/lib/style.css";
import type { EntityGraph as EntityGraphData } from "@/types/api";
import { GraphControls } from "./graph/GraphControls";
import type { RelationFilter } from "./graph/GraphControls";
import { GraphLegend } from "./graph/GraphLegend";
import {
  GraphEvents,
  GraphLoader,
  FilterController,
  CameraAutoFit,
  KeyboardResetListener,
  CameraResetButton,
  NodeTooltipPanel,
  EdgeTooltipPanel,
} from "./graph/SigmaInternalComponents";
import type { NodeTooltip, EdgeTooltip, SelectedEdgeInfo } from "./graph/SigmaInternalComponents";

// ── Dense-graph threshold ─────────────────────────────────────────────────────
// WHY 50 edges: graphs with >50 edges become unreadable with no filtering.
// Auto-applying a 30% strength floor makes AAPL-scale graphs readable on first load.
const DENSE_GRAPH_EDGE_THRESHOLD = 50;
const DENSE_GRAPH_AUTO_MIN_WEIGHT = 30; // percent

// ── WebGL ErrorBoundary ───────────────────────────────────────────────────────
// WHY class component: React error boundaries can ONLY be class components.
// sigma.js attempts WebGL context creation, which throws in unsupported browsers.

export class GraphErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; errorMessage: string | null }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false, errorMessage: null };
  }

  static getDerivedStateFromError(error: Error): { hasError: boolean; errorMessage: string | null } {
    return { hasError: true, errorMessage: error?.message ?? null };
  }

  override render() {
    if (this.state.hasError) {
      const isWebGLError =
        !this.state.errorMessage ||
        /webgl|context creation|rendering context/i.test(this.state.errorMessage);
      const displayMessage = isWebGLError
        ? "Graph unavailable — enable WebGL (hardware acceleration) in your browser."
        : `Graph unavailable: ${this.state.errorMessage}`;
      return (
        <div className="rounded-[2px] border border-border/40 bg-card/50 px-3 py-3">
          <p className="text-xs text-muted-foreground">{displayMessage}</p>
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

// ── Main EntityGraph component ────────────────────────────────────────────────

export interface EntityGraphProps {
  data: EntityGraphData;
  centerEntityId: string;
  // WHY optional: when omitted the graph navigates to entity pages on click.
  // When provided (e.g. IntelligenceTab right sidebar) the host receives the
  // clicked node's data and renders the detail panel instead.
  onNodeClick?: (
    nodeId: string,
    label: string,
    nodeType: string,
    degree: number,
    edges: Array<{ label: string; weight: number; neighborId: string; neighborLabel: string }>,
  ) => void;
  /** Called when user clicks an edge — fires full edge info from graphology attrs. */
  onEdgeClick?: (info: SelectedEdgeInfo) => void;
  /** Node id currently selected by the parent — renders a yellow ring + size boost in sigma. */
  selectedNodeId?: string | null;
}

// Re-export for consumers (e.g. GraphColumn, IntelligenceTab)
export type { SelectedEdgeInfo };

export function EntityGraph({ data, centerEntityId, onNodeClick, onEdgeClick, selectedNodeId }: EntityGraphProps) {
  const [nodeTooltip, setNodeTooltip] = useState<NodeTooltip | null>(null);
  const [edgeTooltip, setEdgeTooltip] = useState<EdgeTooltip | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // ── PLAN-0059 H-4 filter state ────────────────────────────────────────────
  // WHY separate state atoms (not one object): React bails out on re-render when
  // the specific atom doesn't change — coarse-grained objects always re-render.
  const [activeRelFilter, setActiveRelFilter] = useState<RelationFilter>("all");
  // WHY lazy init for minWeight: if the graph is dense (>50 edges) auto-apply
  // a 30% strength floor so AAPL-scale graphs are readable on first load.
  const [minWeight, setMinWeight] = useState<number>(() =>
    data.edges.length > DENSE_GRAPH_EDGE_THRESHOLD ? DENSE_GRAPH_AUTO_MIN_WEIGHT : 0
  );
  const [searchQuery, setSearchQuery] = useState("");
  const [layout, setLayout] = useState<"force" | "hierarchical">("force");

  // WHY useCallback with []: stable references prevent useEffect re-registration in GraphEvents.
  const handleNodeHover = useCallback((tooltip: NodeTooltip | null) => {
    setNodeTooltip(tooltip);
    setEdgeTooltip(null); // mutual exclusion — only one tooltip at a time
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
      {/* ── Filter controls row (extracted to graph/GraphControls.tsx) ────── */}
      {/* WHY above SigmaContainer: controls must be interactive DOM elements;
          placing them inside sigma's canvas div would cause z-index conflicts. */}
      <GraphControls
        activeRelFilter={activeRelFilter}
        minWeight={minWeight}
        searchQuery={searchQuery}
        layout={layout}
        edgeCount={data.edges.length}
        denseGraphEdgeThreshold={DENSE_GRAPH_EDGE_THRESHOLD}
        onRelFilterChange={setActiveRelFilter}
        onMinWeightChange={setMinWeight}
        onSearchQueryChange={setSearchQuery}
        onLayoutChange={setLayout}
      />

      {/* ── Graph canvas container ────────────────────────────────────────── */}
      {/* WHY bg-background (not inline hex): Terminal Dark `--background` token resolves
          to #09090B; the Tailwind utility keeps a single source of truth. */}
      <div
        ref={containerRef}
        // WHY bg-background (was inline #0A0E14): the retired Bloomberg Dark
        // background hex; the Terminal Dark `--background` token now resolves
        // to #09090B and the graph wrapper inherits the canonical app surface
        // color via the Tailwind utility — no inline hex required on the div.
        // T-D-01 BUG 1 (black void below graph): added `h-full w-full` alongside
        // the legacy `min-h-[460px]` fallback. Previously this div was fixed at
        // `h-[460px]` regardless of its column, so the sigma canvas was painted
        // 460px tall while the grid cell stretched taller — the gap below the
        // canvas was the column background bleeding through as a black void.
        // `h-full` lets the wrapper expand to fill the column; `min-h-[460px]`
        // preserves the old minimum height for narrow layouts.
        className="relative h-full w-full min-h-[460px] overflow-hidden rounded-[2px] border border-border/40 bg-background"
      >
        <SigmaContainer
          className="h-full w-full"
          settings={{
            defaultNodeType: "circle",
            defaultEdgeType: "line",
            // WHY renderEdgeLabels:false: edge labels clutter depth=2 graphs.
            // Relationship types are shown in the hover tooltip instead.
            renderEdgeLabels: false,
            // WHY labelRenderedSizeThreshold 8: only show labels for nodes with
            // rendered size >= 8px. Depth-2 nodes (size=7) are too small to label.
            labelRenderedSizeThreshold: 8,
            // WHY hex literal: sigma's WebGL pipeline reads labelColor.color as hex;
            // CSS classes never reach it. #83838A mirrors --muted-foreground.
            labelColor: { color: "#83838A" },
            labelFont: "IBM Plex Mono, monospace",
            labelSize: 10,
            labelWeight: "500",
            minCameraRatio: 0.1,
            maxCameraRatio: 10,
            // WHY allowInvalidContainer:true: prevents sigma from throwing when the
            // DOM element is briefly unmounted during React StrictMode double-invoke.
            allowInvalidContainer: true,
            // WHY enableEdgeEvents:true: sigma 3.x defaults to false — without this
            // enterEdge/leaveEdge events never fire, making edge hover impossible.
            enableEdgeEvents: true,
          }}
          style={{ background: "hsl(var(--background))" }}
        >
          {/* All children below must live inside SigmaContainer for useSigma() context */}
          <GraphLoader data={data} centerEntityId={centerEntityId} layout={layout} />
          <GraphEvents
            centerEntityId={centerEntityId}
            onNodeHover={handleNodeHover}
            onEdgeHover={handleEdgeHover}
            onNodeClick={onNodeClick}
            onEdgeClick={onEdgeClick}
          />
          <FilterController
            activeRelFilter={activeRelFilter}
            minWeight={minWeight}
            searchQuery={searchQuery}
            graphData={data}
            selectedNodeId={selectedNodeId}
          />
          {/* SA-3 (2026-05-10): auto-fit camera when entity changes */}
          <CameraAutoFit centerEntityId={centerEntityId} />
          {/* SA-3 (2026-05-10): keyboard shortcut 'R' to reset camera */}
          <KeyboardResetListener />
          {/* CameraResetButton uses useSigma() — must be inside SigmaContainer */}
          <div className="absolute right-2 bottom-8 z-20">
            <CameraResetButton />
          </div>
        </SigmaContainer>

        {/* Tooltips — position:absolute relative to this container */}
        {nodeTooltip && <NodeTooltipPanel tooltip={nodeTooltip} />}
        {edgeTooltip && <EdgeTooltipPanel tooltip={edgeTooltip} />}

        {/* Legend — extracted to graph/GraphLegend.tsx (bottom-left corner) */}
        <GraphLegend data={data} />

        {/* Controls hint — top-right corner */}
        <div className="absolute right-2 top-2 z-10 flex items-center gap-1 rounded-[2px] border border-border/40 bg-card/80 px-2 py-1 backdrop-blur-sm">
          <span className="text-[9px] text-muted-foreground/60">Scroll · Drag · Click · R to fit</span>
        </div>
      </div>
    </GraphErrorBoundary>
  );
}
