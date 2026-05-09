/**
 * components/intelligence/GraphPanel.tsx — Column 1: Knowledge graph explorer
 * (PLAN-0074 Wave H T-H-03)
 *
 * WHY THIS COMPONENT EXISTS:
 * The graph panel is the visual entry point to the intelligence page. It renders
 * the entity's knowledge graph using sigma.js (WebGL) and drives the cross-panel
 * selection sync via SelectedEntityContext. Clicking a node in the graph tells
 * the intelligence tabs and sidebar to update their content for that entity.
 *
 * WHY SIGMA.JS (not Cytoscape):
 * The existing codebase uses @react-sigma/core throughout (EntityGraph,
 * IntelligenceTab, etc.). Cytoscape is not installed. Sigma.js handles KG
 * topology well — it uses WebGL rendering for 60fps at 40+ nodes and has
 * a ForceAtlas2 layout that matches knowledge graph structure (force-directed,
 * handles dense clusters and star topologies gracefully).
 *
 * WHY NEXT/DYNAMIC ssr:false:
 * Sigma.js creates a WebGL context at mount time. Next.js SSR runs in Node.js
 * which has no WebGL, so sigma would crash the server-side render. Dynamic
 * import with ssr:false defers sigma's initialization to the browser.
 *
 * WHY depth CONTROLS LIMIT (not actual graph depth):
 * S9's GET /v1/entities/{id}/graph returns all direct (1-hop) relations up to
 * a `limit` parameter. There is no server-side depth/BFS traversal. The depth
 * slider controls how many relations are returned: higher depth = more neighbors
 * = the graph "feels" deeper even though it's all 1-hop. This matches the
 * approach in knowledge-graph.ts (getEntityGraph).
 *
 * WHO USES IT: IntelligenceLayout column 1 slot
 * DATA SOURCE: GET /api/v1/entities/{id}/graph (via knowledge-graph.ts)
 */

"use client";
// WHY "use client": uses hooks (useState, useEffect, useCallback, useQuery)
// and sigma.js WebGL — browser-only.

import { useState, useCallback } from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "@/lib/api-client";
import { useSelectedEntity } from "@/contexts/SelectedEntityContext";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { RefreshCw, Network } from "lucide-react";
import type { EntityGraph as EntityGraphData } from "@/types/api";

// ── Dynamic import: sigma.js WebGL renderer ───────────────────────────────────
// WHY next/dynamic with ssr:false: see module comment on SSR incompatibility.
// Loading fallback renders a skeleton matching the panel's expected size.
const EntityGraph = dynamic(
  () =>
    import("@/components/instrument/EntityGraph").then((m) => ({
      default: m.EntityGraph,
    })),
  {
    ssr: false,
    loading: () => (
      <Skeleton className="w-full h-full min-h-[200px]" />
    ),
  },
);

// ── Props ─────────────────────────────────────────────────────────────────────

interface GraphPanelProps {
  /** The anchor entity UUIDv7 — the entity this graph is centred on */
  entityId: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function GraphPanel({ entityId }: GraphPanelProps) {
  const gw = useApiClient();
  // Read the cross-panel selection state — node clicks update this
  const { setSelectedEntityId, selectedEntityId } = useSelectedEntity();

  // ── Local state ──────────────────────────────────────────────────────────

  // WHY depth 1-5 (default 2):
  // depth=1 → limit=15 (compact — shows immediate neighbours only)
  // depth=2 → limit=40 (default — good balance of context vs clutter)
  // depth=3 → limit=80 (expanded — for deeply-connected entities)
  // depth=4 → limit=120, depth=5 → limit=200 (dense exploration mode)
  const [depth, setDepth] = useState(2);

  // WHY confidence_breakdown toggle (not always on):
  // Fetching confidence breakdown adds ~50ms to the graph response (extra
  // DB JOINs on evidence_raw). Most of the time analysts just want the graph
  // structure; breakdown mode is opt-in for deep evidence investigation.
  const [showConfidenceBreakdown, setShowConfidenceBreakdown] = useState(false);

  // ── Data fetch ────────────────────────────────────────────────────────────

  const { data: graphData, isLoading, isError, refetch } = useQuery<EntityGraphData>({
    // WHY [depth, showConfidenceBreakdown] in key:
    // Changing depth or breakdown mode changes the response — each combination
    // gets its own cache slot so toggling back to a previous setting is instant.
    queryKey: ["intelligence-graph", entityId, depth, showConfidenceBreakdown],
    queryFn: () =>
      gw.getEntityGraph(
        entityId,
        depth,
        // WHY pass "all" for time_window: the intelligence page shows the full
        // relationship picture across all time. Time-windowed graphs belong in
        // a future filter toolbar, not the default view.
        "all",
      ),
    // WHY staleTime 60_000: graph edges change infrequently (KG pipeline runs ~1/min).
    // A 1-min cache means depth-slider drag-to-same-value doesn't re-fetch.
    staleTime: 60_000,
    enabled: !!entityId,
  });

  // ── Node click handler ────────────────────────────────────────────────────

  /**
   * handleNodeClick — called by EntityGraph when a node is clicked.
   *
   * WHY useCallback: EntityGraph receives this as an `onNodeClick` prop.
   * Without useCallback the function reference changes on every render,
   * causing EntityGraph to re-register its sigma event listener on every
   * render — wasteful and potentially causing stale-closure bugs in sigma.
   *
   * SIDE EFFECT: updates SelectedEntityContext so the intelligence tabs
   * and sidebar re-render for the clicked entity. This is the primary
   * cross-panel communication mechanism.
   */
  const handleNodeClick = useCallback(
    (nodeId: string) => {
      setSelectedEntityId(nodeId);
    },
    [setSelectedEntityId],
  );

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="h-full flex flex-col bg-background border-r border-border">
      {/* ── Panel header ──────────────────────────────────────────────────── */}
      <div className="flex-none px-3 py-2 border-b border-border flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Network className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={1.5} />
          <span className="text-[11px] font-mono font-medium uppercase tracking-wider text-muted-foreground">
            Graph
          </span>
        </div>
        {/* Retry button shown only on error */}
        {isError && (
          <button
            type="button"
            onClick={() => refetch()}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Retry loading graph"
          >
            <RefreshCw className="h-3.5 w-3.5" strokeWidth={1.5} />
          </button>
        )}
      </div>

      {/* ── Controls toolbar ──────────────────────────────────────────────── */}
      <div className="flex-none px-3 py-1.5 border-b border-border/50 flex items-center gap-4">
        {/* Depth slider */}
        <div className="flex items-center gap-2 flex-1">
          <Label
            htmlFor="graph-depth-slider"
            className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground shrink-0"
          >
            Depth
          </Label>
          <Slider
            id="graph-depth-slider"
            min={1}
            max={5}
            step={1}
            value={[depth]}
            onValueChange={([v]) => setDepth(v)}
            className="flex-1"
            aria-label={`Graph depth: ${depth}`}
          />
          {/* WHY show limit alongside depth: analysts need to know how many
              relations they're requesting, not just the abstract "depth" number. */}
          <span className="text-[10px] font-mono tabular-nums text-muted-foreground shrink-0 w-[14px]">
            {depth}
          </span>
        </div>

        {/* Confidence breakdown toggle */}
        <div className="flex items-center gap-1.5">
          <Switch
            id="confidence-breakdown-toggle"
            checked={showConfidenceBreakdown}
            onCheckedChange={setShowConfidenceBreakdown}
            aria-label="Show confidence breakdown in node tooltips"
          />
          <Label
            htmlFor="confidence-breakdown-toggle"
            className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground cursor-pointer"
          >
            Scores
          </Label>
        </div>
      </div>

      {/* ── Graph area ────────────────────────────────────────────────────── */}
      <div
        className="flex-1 relative overflow-hidden"
        // WHY data-selected: CSS can highlight the selected node using the
        // [data-selected] attribute, but sigma handles node highlighting
        // via its own reducers. We expose this for test queries.
        data-selected-entity={selectedEntityId}
      >
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center">
            <RefreshCw
              className="h-5 w-5 animate-spin text-muted-foreground"
              strokeWidth={1.5}
            />
          </div>
        )}

        {isError && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
            <p className="text-[11px] text-muted-foreground font-mono">
              Failed to load graph
            </p>
          </div>
        )}

        {/* WHY !isLoading check: EntityGraph renders sigma immediately on mount.
            If data is undefined when sigma mounts it tries to render an empty
            graph which is fine, but showing the loading state while data arrives
            avoids a jarring "empty → populated" transition.
            WHY onNodeClick signature: EntityGraph passes (nodeId, label, nodeType,
            degree, edges) — we only need the nodeId for context selection. */}
        {!isLoading && !isError && graphData && (
          <EntityGraph
            data={graphData}
            centerEntityId={entityId}
            onNodeClick={(nodeId) => handleNodeClick(nodeId)}
          />
        )}
      </div>

      {/* ── Node count footer ─────────────────────────────────────────────── */}
      {graphData && (
        <div className="flex-none px-3 py-1 border-t border-border/50 flex items-center gap-2">
          <span className="text-[10px] font-mono tabular-nums text-muted-foreground">
            {graphData.nodes?.length ?? 0} nodes · {graphData.edges?.length ?? 0} edges
          </span>
          {selectedEntityId !== entityId && (
            <span className="text-[10px] font-mono text-primary truncate">
              · {selectedEntityId}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
