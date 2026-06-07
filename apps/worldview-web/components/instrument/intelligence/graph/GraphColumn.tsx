/**
 * GraphColumn — PLAN-0090 T-D-04 — middle column of Intelligence tab (PRD-0088 §6.9).
 * Renders: FULL AI brief → GraphToolbar → sigma.js entity graph.
 * Owns depth + typeFilters; `selectedNodeId` lives in the parent IntelligenceTab.
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
import { RefreshCw } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import { GraphToolbar } from "@/components/instrument/graph/GraphToolbar";
import { EntityGraphErrorBoundary } from "@/components/instrument/EntityGraphErrorBoundary";
import { StructuredBrief } from "@/components/brief/StructuredBrief";
import { GraphStats } from "./GraphStats";
import type { BriefingResponse, EntityGraph as EntityGraphData } from "@/types/api";

// Pane-count guard: treat a single node with 0 edges as an "empty" graph.
// WHY: the KG always returns the centre entity even when no relations have been
// ingested yet. Without this guard, EntityGraph renders a solitary blue dot
// which looks like a rendering bug rather than a data-gap state.
function isGraphEmpty(g: EntityGraphData | null): boolean {
  if (!g) return true;
  return g.nodes.length === 1 && (g.edges?.length ?? 0) === 0;
}

// WHY ssr:false: EntityGraph uses sigma.js (WebGL) which needs a browser.
const EntityGraph = dynamic(
  () => import("@/components/instrument/EntityGraph").then((m) => ({ default: m.EntityGraph })),
  { ssr: false, loading: () => <div className="flex h-full items-center justify-center"><RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" strokeWidth={1.5} /></div> },
);

const BRIEF_STALE_MS = 10 * 60 * 1000;
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
}

export function GraphColumn({ entityId, selectedNodeId, onNodeSelect }: GraphColumnProps) {
  const { accessToken } = useAuth();
  const [depth, setDepth] = useState<number>(2);
  const [typeFilters, setTypeFilters] = useState<string[]>([]);
  // WHY latencyRef + latencyMs state: we measure wall-clock time for the graph
  // fetch and surface it in GraphStats. The ref accumulates the raw measurement
  // (safe to mutate without triggering re-renders); the state copy drives the UI.
  const latencyRef = useRef<number | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);

  const { data: brief } = useQuery<BriefingResponse>({
    queryKey: qk.instruments.brief(entityId),
    queryFn: () => createGateway(accessToken).getInstrumentBrief(entityId),
    enabled: !!accessToken && !!entityId,
    staleTime: BRIEF_STALE_MS,
    retry: false, // brief 404s for cold instruments; retry just hammers LLM
  });

  // WHY AbortController inside queryFn: chain TanStack's unmount signal and add
  // a depth-adaptive deadline. Abort is translated to a typed Error for the UI.
  // WHY performance.now(): measures wall-clock time for the fetch so GraphStats
  // can surface it. Using performance.now() (not Date.now()) avoids clock drift.
  const { data: graphData, isLoading: graphLoading, isError, error: graphErr } = useQuery<EntityGraphData | null>({
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

  // WHY two separate empty-state branches:
  //   1. nodes.length === 0: type filter excluded everything → "No entities match filter."
  //   2. isGraphEmpty (nodes=1, edges=0): KG has centre node but no relations yet → "No connections found."
  //   3. Otherwise: render the graph.
  const hasTypeFilterMatch = filteredGraph !== null && filteredGraph.nodes.length === 0;
  const hasNoConnections = filteredGraph !== null && isGraphEmpty(filteredGraph);
  const hasGraph = filteredGraph !== null && !isGraphEmpty(filteredGraph) && filteredGraph.nodes.length > 0;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {brief?.narrative && (
        <div className="mx-3 mt-3">
          {/* WHY StructuredBrief with variant="compact": the GraphColumn center
              column is narrow — compact suppresses the confidence badge and
              uses smaller text than the full variant. We pass sections/lead/
              confidence directly from the BriefingResponse fields. */}
          <StructuredBrief
            sections={brief.sections ?? []}
            lead={brief.lead}
            confidence={brief.confidence}
            variant="compact"
            className="p-3 bg-card border border-border/50 rounded-[2px]"
          />
        </div>
      )}
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
        {/* Loading spinner */}
        {graphLoading && (
          <div className="flex h-full items-center justify-center">
            <RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" strokeWidth={1.5} />
          </div>
        )}

        {/* Depth-adaptive timeout message */}
        {isTimeout && (
          <div className="flex h-full items-center justify-center px-6 text-center text-[11px] text-muted-foreground">
            Graph timed out at depth {depth}. Try depth 1 or 2.
          </div>
        )}

        {/* Type filter left nothing to show */}
        {!graphLoading && !isTimeout && hasTypeFilterMatch && (
          <div className="flex h-full items-center justify-center px-6 text-center text-[11px] text-muted-foreground">
            No entities match the current type filter.
          </div>
        )}

        {/* BUG FIX 2: single-node (no edges) — knowledge graph hasn't ingested
            any connections for this entity yet. This is normal for cold instruments
            with few news articles. Show an informative message instead of a dot. */}
        {!graphLoading && !isTimeout && hasNoConnections && (
          <div className="flex h-full items-center justify-center px-6 text-center">
            <p className="text-[11px] text-muted-foreground leading-[1.6]">
              No connections found for this entity.
              The knowledge graph builds connections as news articles are ingested
              — check back later.
            </p>
          </div>
        )}

        {/* Normal graph render */}
        {!graphLoading && !isTimeout && hasGraph && (
          <EntityGraphErrorBoundary>
            <EntityGraph data={filteredGraph} centerEntityId={entityId} onNodeClick={handleNodeClick} />
          </EntityGraphErrorBoundary>
        )}
      </div>
    </div>
  );
}
