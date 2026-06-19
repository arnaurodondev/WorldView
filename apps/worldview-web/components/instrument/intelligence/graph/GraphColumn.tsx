/**
 * GraphColumn — PLAN-0090 T-D-04 / PLAN-0099 Wave 2 — centre canvas of the
 * Intelligence tab's investigation grid (PRD-0088 §6.9).
 * Renders: GraphToolbar → GraphStats → sigma.js entity graph.
 * Owns depth + typeFilters; selection (node OR edge) lives in the parent
 * IntelligenceTab so the SelectionDetailPanel below the canvas stays in sync.
 *
 * PLAN-0099 Wave 2 (investigation-page rework):
 *   - The AI brief moved OUT of this column into the left-rail EntityDossier —
 *     the centre column is now pure graph + inspector, Bloomberg-style.
 *   - selectedNodeId/selectedEdgeId are forwarded to EntityGraph so the canvas
 *     paints the trading-yellow selection highlight (FilterController reducers).
 *   - focusNodeId/focusNonce drive the "Focus graph here" camera animation
 *     requested from the node inspector.
 *
 * BUG FIX 1 (PLAN-0099 W4): GRAPH_TIMEOUT_MS was a flat 3000 ms for all depths.
 * The original comment itself said depth=3 takes 4-8s — so depth=3 always timed out.
 * Replaced with GRAPH_TIMEOUT_MS_BY_DEPTH: depth=1→1500ms, depth=2→4000ms, depth=3→8000ms.
 *
 * BUG FIX 2 (PLAN-0099 W4): When the KG returns exactly 1 node (the centre entity)
 * with 0 edges, `filteredGraph.nodes.length > 0` passed (it is 1), causing EntityGraph
 * to render a single blue dot with no edges — visually indistinguishable from a bug.
 * Added a dedicated "no connections" empty-state that triggers when nodes=1 and edges=0.
 */

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { Clock, Filter, Share2 } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
// Round-3 consolidation (DS §15.12): shared primitive + reserved copy keys
// replace the local components/instrument/shared/EmptyState.tsx fork.
import { EmptyState } from "@/components/primitives/EmptyState";
import { qk } from "@/lib/query/keys";
import { GraphToolbar } from "@/components/instrument/graph/GraphToolbar";
import { EntityGraphErrorBoundary } from "@/components/instrument/EntityGraphErrorBoundary";
import { GraphStats } from "./GraphStats";
import type { EntityGraph as EntityGraphData } from "@/types/api";

// Pane-count guard: treat a single node with 0 edges as an "empty" graph.
// WHY: the KG always returns the centre entity even when no relations have been
// ingested yet. Without this guard, EntityGraph renders a solitary blue dot
// which looks like a rendering bug rather than a data-gap state.
function isGraphEmpty(g: EntityGraphData | null): boolean {
  if (!g) return true;
  return g.nodes.length === 1 && (g.edges?.length ?? 0) === 0;
}

/**
 * GraphSkeleton — shape-matched placeholder for the sigma.js canvas slot.
 *
 * WHY a skeleton instead of the previous RefreshCw spinner (Round-3 item 4):
 * the polish-sprint rule is "no spinners, no blank areas, no layout shift" —
 * a centred 16px spinner reads as indeterminate chrome, while a full-bleed
 * pulsing surface with faux node dots tells the analyst exactly WHAT is
 * loading (a node-link canvas) and reserves its final footprint, so the
 * graph paints in-place with zero shift. The three dots echo the eventual
 * centre-entity + neighbours layout — pure decoration, hence aria-hidden
 * inside a role="status" wrapper that still announces loading politely.
 */
function GraphSkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading entity graph"
      data-testid="graph-skeleton"
      // Round-4 item 4: animation removed per DS §6.2 — skeletons are STATIC
      // by default; the faux node-dot geometry alone signals "graph loading".
      className="relative h-full w-full bg-muted/10"
    >
      <div aria-hidden className="absolute left-1/2 top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-muted/60" />
      <div aria-hidden className="absolute left-[30%] top-[32%] h-2 w-2 rounded-full bg-muted/40" />
      <div aria-hidden className="absolute left-[68%] top-[64%] h-2 w-2 rounded-full bg-muted/40" />
      <div aria-hidden className="absolute left-[62%] top-[28%] h-1.5 w-1.5 rounded-full bg-muted/30" />
      <div aria-hidden className="absolute left-[26%] top-[68%] h-1.5 w-1.5 rounded-full bg-muted/30" />
    </div>
  );
}

// WHY ssr:false: EntityGraph uses sigma.js (WebGL) which needs a browser.
// WHY the loading slot reuses GraphSkeleton: the dynamic-import gap and the
// query-loading gap must be visually indistinguishable (no spinner→skeleton
// flicker when both happen back-to-back on cold start).
const EntityGraph = dynamic(
  () => import("@/components/instrument/EntityGraph").then((m) => ({ default: m.EntityGraph })),
  { ssr: false, loading: () => <GraphSkeleton /> },
);

const GRAPH_STALE_MS = 10 * 60 * 1000;

// WHY depth-adaptive: PLAN-0090 hardcoded 3s which kills depth=3 on cold cache
// (AGE Cypher 3-hop takes 4-8s). Depth=1 uses a fast SQL JOIN so 1.5s suffices.
// Depth=2 is the default Intelligence tab view — 4s handles warm-cache AGE paths.
const GRAPH_TIMEOUT_MS_BY_DEPTH: Record<number, number> = {
  1: 1500,
  2: 4000,
  3: 8000,
};

export interface GraphColumnProps {
  entityId: string;
  selectedNodeId: string | null;
  onNodeSelect: (nodeId: string | null) => void;
  /** Optional callback for edge-click events (Block I T-27).
   *  When provided, a clicked edge fires onEdgeSelect(edgeId) and the parent
   *  IntelligenceTab switches the inspector to edge-detail mode. */
  onEdgeSelect?: (edgeId: string) => void;
  /** PLAN-0099 Wave 2: edge selected in the inspector — highlighted on canvas. */
  selectedEdgeId?: string | null;
  /** PLAN-0099 Wave 2: "Focus graph here" — node to centre the camera on. */
  focusNodeId?: string | null;
  /** Bump to re-fire the focus animation for the same node. */
  focusNonce?: number;
}

export function GraphColumn({
  entityId,
  selectedNodeId,
  onNodeSelect,
  onEdgeSelect,
  selectedEdgeId = null,
  focusNodeId = null,
  focusNonce = 0,
}: GraphColumnProps) {
  const { accessToken } = useAuth();
  // Default to depth=1 (data-pipeline QA 2026-06-16): depth=2 AGE traversal on
  // hub entities (e.g. AAPL) exceeds the server's ~20s statement timeout → 504 →
  // the canvas fails-soft to EMPTY (the "75% black Intelligence tab" the QA
  // flagged). depth=1 returns ~33 nodes / ~40 edges in <1s, so the graph renders
  // immediately; the user can still step up to depth=2/3 via the depth control
  // (the per-depth timeout + "Reduce depth" recovery handle the deeper cases).
  const [depth, setDepth] = useState<number>(1);
  const [typeFilters, setTypeFilters] = useState<string[]>([]);
  // WHY latencyRef + latencyMs state: we measure wall-clock time for the graph
  // fetch and surface it in GraphStats. The ref accumulates the raw measurement
  // (safe to mutate without triggering re-renders); the state copy drives the UI.
  const latencyRef = useRef<number | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);

  // NOTE (PLAN-0099 Wave 2): the AI brief that used to render at the top of
  // this column moved to the left-rail EntityDossier (same qk.instruments.brief
  // cache slot — zero extra fetches). The centre column is graph-only now.

  // WHY AbortController inside queryFn: chain TanStack's unmount signal and add
  // a depth-adaptive deadline. Abort is translated to a typed Error for the UI.
  // WHY performance.now(): measures wall-clock time for the fetch so GraphStats
  // can surface it. Using performance.now() (not Date.now()) avoids clock drift.
  // Round-4 hardening (item 1b): refetch consumed by the new generic-error
  // branch below (non-timeout failures previously fell through every render
  // branch and left an empty bordered box).
  const { data: graphData, isLoading: graphLoading, isError, error: graphErr, refetch } = useQuery<EntityGraphData | null>({
    queryKey: qk.instruments.entityGraph(entityId, depth),
    queryFn: async ({ signal }) => {
      const ctrl = new AbortController();
      signal?.addEventListener("abort", () => ctrl.abort());
      // WHY depth-adaptive timeout: AGE Cypher 3-hop takes 4-8s on cold cache;
      // depth=1 SQL JOIN finishes in ~500ms. Flat 3s killed all depth=3 queries.
      const timeoutMs = GRAPH_TIMEOUT_MS_BY_DEPTH[depth] ?? 4000;
      const timer = setTimeout(() => ctrl.abort(), timeoutMs);
      const t0 = performance.now();
      try {
        const result = await createGateway(accessToken).getEntityGraph(entityId, depth);
        // Commit latency: measure after the await resolves successfully.
        const measured = Math.round(performance.now() - t0);
        latencyRef.current = measured;
        setLatencyMs(measured);
        return result;
      }
      catch (err) { if (ctrl.signal.aborted) throw new Error("GRAPH_TIMEOUT"); throw err; }
      finally { clearTimeout(timer); }
    },
    enabled: !!accessToken && !!entityId,
    staleTime: GRAPH_STALE_MS,
    retry: 0,
  });

  // WHY reset selection on entity change: a stale id from a previous entity
  // would point at a node that no longer exists in the new graph.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { onNodeSelect(null); }, [entityId]);

  const availableEntityTypes = useMemo<string[]>(() => {
    if (!graphData?.nodes?.length) return [];
    const s = new Set<string>();
    for (const n of graphData.nodes) if (n.type) s.add(n.type);
    return Array.from(s).sort();
  }, [graphData]);

  const filteredGraph = useMemo<EntityGraphData | null>(() => {
    if (!graphData) return null;
    if (typeFilters.length === 0) return graphData;
    const nodes = graphData.nodes.filter((n) => typeFilters.includes(n.type) || n.id === graphData.entity_id);
    const keep = new Set(nodes.map((n) => n.id));
    const edges = graphData.edges.filter((e) => keep.has(e.source) && keep.has(e.target));
    return { ...graphData, nodes, edges };
  }, [graphData, typeFilters]);

  // WHY adapter: collapse EntityGraph's 5-tuple to (id). Click-same deselects.
  const handleNodeClick = (id: string) => onNodeSelect(selectedNodeId === id ? null : id);
  const isTimeout = isError && graphErr instanceof Error && graphErr.message === "GRAPH_TIMEOUT";
  // Round-4 hardening (item 1b): non-timeout failures (S9 5xx, network drop,
  // auth hiccup) previously matched NO render branch — graphLoading=false,
  // isTimeout=false, filteredGraph=null — so the canvas slot rendered an
  // empty bordered box indistinguishable from a rendering bug.
  const isGenericError = isError && !isTimeout;

  // WHY two separate empty-state branches:
  //   1. nodes.length === 0: type filter excluded everything → "No entities match filter."
  //   2. isGraphEmpty (nodes=1, edges=0): KG has centre node but no relations yet → "No connections found."
  //   3. Otherwise: render the graph.
  const hasTypeFilterMatch = filteredGraph !== null && filteredGraph.nodes.length === 0;
  const hasNoConnections = filteredGraph !== null && isGraphEmpty(filteredGraph);
  const hasGraph = filteredGraph !== null && !isGraphEmpty(filteredGraph) && filteredGraph.nodes.length > 0;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="mx-3 mt-2">
        <GraphToolbar
          depth={depth}
          onDepthChange={setDepth}
          selectedEntityTypes={typeFilters}
          onEntityTypesChange={setTypeFilters}
          availableEntityTypes={availableEntityTypes}
        />
      </div>
      {/* Stats bar: node/edge counts + fetch latency */}
      {filteredGraph && !graphLoading && (
        <div className="mx-3 mt-1">
          <GraphStats
            nodeCount={filteredGraph.nodes.length}
            edgeCount={filteredGraph.edges?.length ?? 0}
            depth={depth}
            latencyMs={latencyMs}
          />
        </div>
      )}
      <div className="flex-1 min-h-0 mx-3 mb-3 mt-2 border border-border/40 rounded-[2px] overflow-hidden">
        {/* Loading — shape-matched skeleton (Round-3 item 4: no spinners).
            Fills the exact canvas slot so the graph paints with zero shift. */}
        {graphLoading && <GraphSkeleton />}

        {/* Depth-adaptive timeout — NAMED state (Round-1 requirement 4).
            Round-3 consolidation: copy now comes from the static registry key
            ("Graph query timed out" — the per-depth interpolation was
            generalised per DS §15.12; the active depth is already visible in
            the GraphToolbar + GraphStats directly above this slot). The
            registry's ctaLabel ("Reduce depth") is rendered as a REAL action:
            one click drops to the next-cheaper depth and refires the query —
            strictly better than the old hint that asked the user to find the
            depth control themselves. Hidden at depth 1 (nothing cheaper). */}
        {isTimeout && (
          <div className="flex h-full items-center justify-center">
            <EmptyState
              condition="error"
              copyKey="instrument.graph-timeout"
              icon={Clock}
              action={
                depth > 1 ? (
                  <button
                    type="button"
                    onClick={() => setDepth(depth - 1)}
                    className="font-mono text-[9px] uppercase tracking-wider text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-[2px]"
                  >
                    Reduce depth
                  </button>
                ) : undefined
              }
            />
          </div>
        )}

        {/* Generic (non-timeout) graph failure — NAMED per-section error with
            Retry (Round-4 item 1b). Scoped to the canvas slot only: the news
            rail and context panel keep working. Inline copy (not a registry
            key): the empty-state registry is a shared file owned by the
            platform agent; per-section error strings stay local. */}
        {isGenericError && (
          <div
            data-testid="graph-fetch-error"
            className="flex h-full flex-col items-center justify-center gap-1 px-3 text-center"
          >
            <p className="text-[12px] text-foreground">Couldn&apos;t load the entity graph</p>
            <p className="text-[11px] text-muted-foreground">
              The graph query failed — news and context are unaffected.
            </p>
            <button
              type="button"
              onClick={() => void refetch()}
              className="mt-1 font-mono text-[9px] uppercase tracking-wider text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-[2px]"
            >
              Retry
            </button>
          </div>
        )}

        {/* Type filter left nothing to show — named state with the obvious fix. */}
        {!graphLoading && !isTimeout && hasTypeFilterMatch && (
          <div className="flex h-full items-center justify-center">
            <EmptyState
              condition="empty-no-data"
              copyKey="instrument.graph-no-filter-matches"
              icon={Filter}
            />
          </div>
        )}

        {/* BUG FIX 2: single-node (no edges) — knowledge graph hasn't ingested
            any connections for this entity yet. This is normal for cold instruments
            with few news articles. Named state instead of a solitary dot. */}
        {!graphLoading && !isTimeout && hasNoConnections && (
          <div className="flex h-full items-center justify-center">
            <EmptyState
              condition="empty-no-data"
              copyKey="instrument.no-connections"
              icon={Share2}
            />
          </div>
        )}

        {/* Normal graph render */}
        {!graphLoading && !isTimeout && hasGraph && (
          <EntityGraphErrorBoundary>
            <EntityGraph
              data={filteredGraph}
              centerEntityId={entityId}
              onNodeClick={handleNodeClick}
              onEdgeClick={onEdgeSelect}
              // PLAN-0099 Wave 2: canvas reflects the inspector selection
              // (yellow highlight via FilterController reducers) and the
              // "Focus graph here" camera request from the node inspector.
              selectedNodeId={selectedNodeId}
              selectedEdgeId={selectedEdgeId}
              focusNodeId={focusNodeId}
              focusNonce={focusNonce}
            />
          </EntityGraphErrorBoundary>
        )}
      </div>
    </div>
  );
}
