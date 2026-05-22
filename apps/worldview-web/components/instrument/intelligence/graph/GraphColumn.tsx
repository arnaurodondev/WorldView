/**
 * GraphColumn — middle column of Intelligence tab (PRD-0088 §6.9 / W7 T-06).
 * Renders: StructuredBrief → GraphStats strip → GraphToolbar → sigma.js entity graph.
 * Owns depth + typeFilters; `selectedNodeId` lives in the parent IntelligenceTab.
 *
 * WHY DEPTH-ADAPTIVE TIMEOUT (T-06):
 * AGE Cypher traversal cost is roughly O(degree^depth). Depth=1 finishes in <500ms;
 * depth=2 in 1–4s; depth=3 in 4–8s on cold cache. A flat 3s timeout killed depth=3
 * before it had a chance to return. The new map gives depth=1 a 1.5s ceiling
 * (anything slower is a bug), depth=2 a 4s budget, depth=3 an 8s budget.
 *
 * WHY StructuredBrief (replacing MarkdownContent):
 * StructuredBrief renders the structured lead + section bullets with citation chips
 * that the W4 LLM pipeline already emits. Raw MarkdownContent over brief.narrative
 * lost the citation context entirely; analysts want to know which claims are sourced.
 *
 * WHY CLIENT-SIDE LATENCY:
 * S9 does not expose a backend-measured latency field on BriefingResponse. We
 * measure round-trip time client-side with performance.now() so the footer strip
 * shows the analyst how stale/fast the data is ("312 ms" vs "cached" feel).
 */

"use client";
// WHY "use client": useState, useRef, useEffect, useQuery — all browser-only.

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
import { formatDateTime } from "@/lib/utils";
import { GraphStats } from "./GraphStats";
import type { BriefingResponse, EntityGraph as EntityGraphData } from "@/types/api";

// WHY ssr:false: EntityGraph uses sigma.js (WebGL) — cannot run in Node.js.
const EntityGraph = dynamic(
  () => import("@/components/instrument/EntityGraph").then((m) => ({ default: m.EntityGraph })),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center">
        <RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" strokeWidth={1.5} />
      </div>
    ),
  },
);

const BRIEF_STALE_MS = 10 * 60 * 1000;
const GRAPH_STALE_MS = 10 * 60 * 1000;

// WHY per-depth budget: AGE traversal cost grows exponentially with depth.
// depth=1 budget is tight (any real delay = cold cache or infrastructure issue).
// depth=3 gets 8s because it's an advanced, expensive query.
const GRAPH_TIMEOUT_MS: Record<number, number> = { 1: 1500, 2: 4000, 3: 8000 };

export interface GraphColumnProps {
  readonly entityId: string;
  readonly selectedNodeId: string | null;
  readonly onNodeSelect: (nodeId: string | null) => void;
}

export function GraphColumn({ entityId, selectedNodeId, onNodeSelect }: GraphColumnProps) {
  const { accessToken } = useAuth();
  const [depth, setDepth] = useState<number>(2);
  const [typeFilters, setTypeFilters] = useState<string[]>([]);
  // WHY ref for latency: we measure performance.now() inside the queryFn
  // closure (browser-only) and need to read it in the data-change effect
  // without causing a re-render every fetch cycle.
  const graphFetchStartRef = useRef<number>(0);
  const [graphLatencyMs, setGraphLatencyMs] = useState<number | null>(null);

  const { data: brief } = useQuery<BriefingResponse>({
    queryKey: qk.instruments.brief(entityId),
    queryFn: () => createGateway(accessToken).getInstrumentBrief(entityId),
    enabled: !!accessToken && !!entityId,
    staleTime: BRIEF_STALE_MS,
    // WHY retry: false — brief 404s for instruments without a generated brief
    // (common for newly-added tickers). Retrying would hammer S8 LLM.
    retry: false,
  });

  // WHY AbortController inside queryFn: chain TanStack's unmount abort signal
  // AND add our depth-adaptive deadline. When the AbortController fires we
  // translate the error to a typed "GRAPH_TIMEOUT" string so the UI can show
  // a specific fallback rather than a generic "Something went wrong".
  const {
    data: graphData,
    isLoading: graphLoading,
    isError,
    error: graphErr,
  } = useQuery<EntityGraphData | null>({
    queryKey: qk.instruments.entityGraph(entityId, depth),
    queryFn: async ({ signal }) => {
      // Record start time for client-side latency measurement.
      graphFetchStartRef.current = performance.now();
      const timeout = GRAPH_TIMEOUT_MS[depth] ?? 4000;
      const ctrl = new AbortController();
      signal?.addEventListener("abort", () => ctrl.abort());
      const timer = setTimeout(() => ctrl.abort(), timeout);
      try {
        return await createGateway(accessToken).getEntityGraph(entityId, depth);
      } catch (err) {
        if (ctrl.signal.aborted) throw new Error("GRAPH_TIMEOUT");
        throw err;
      } finally {
        clearTimeout(timer);
      }
    },
    enabled: !!accessToken && !!entityId,
    staleTime: GRAPH_STALE_MS,
    retry: 0,
  });

  // WHY useEffect for latency: TanStack Query v5 removed onSuccess callbacks.
  // We react to `graphData` change in an effect instead.
  useEffect(() => {
    if (graphData !== undefined) {
      setGraphLatencyMs(Math.round(performance.now() - graphFetchStartRef.current));
      console.debug("[intelligence] graph.fetch", {
        entityId,
        depth,
        latencyMs: Math.round(performance.now() - graphFetchStartRef.current),
        nodeCount: graphData?.nodes?.length ?? 0,
        edgeCount: graphData?.edges?.length ?? 0,
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphData]);

  // WHY reset selection on entity change: a stale selectedNodeId from a previous
  // entity would point at a node that doesn't exist in the new graph payload.
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
    const nodes = graphData.nodes.filter(
      (n) => typeFilters.includes(n.type) || n.id === graphData.entity_id,
    );
    const keep = new Set(nodes.map((n) => n.id));
    const edges = graphData.edges.filter((e) => keep.has(e.source) && keep.has(e.target));
    return { ...graphData, nodes, edges };
  }, [graphData, typeFilters]);

  // WHY adapter: collapse EntityGraph's multi-field click to nodeId.
  // Clicking the same node deselects (toggles detail panel closed).
  const handleNodeClick = (id: string) => onNodeSelect(selectedNodeId === id ? null : id);
  const isTimeout = isError && graphErr instanceof Error && graphErr.message === "GRAPH_TIMEOUT";

  // Brief renders when structured content is available (lead or sections).
  // MarkdownContent over raw narrative is intentionally removed — it lost citation context.
  const hasBriefContent = !!(brief?.lead || (brief?.sections && brief.sections.length > 0));

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* ── AI Brief (StructuredBrief replaces raw MarkdownContent) ───────── */}
      {hasBriefContent && brief && (
        <div className="mx-3 mt-3 p-3 bg-card border border-border/50 rounded-[2px]">
          <div className="mb-1.5 flex items-baseline justify-between">
            <span className="text-[10px] font-mono uppercase tracking-[0.08em] text-muted-foreground">
              Intelligence Brief
            </span>
          </div>
          {/* WHY variant="compact": the brief panel is narrow (center column, ~600px).
              Compact omits the confidence badge and uses tighter typography. */}
          <StructuredBrief
            sections={brief.sections}
            lead={brief.lead}
            confidence={brief.confidence}
            variant="compact"
          />
          {/* WHY brief footer strip: the analyst needs to know when the brief was
              generated (freshness) and how long the fetch took (performance signal).
              generated_at comes from S8; latencyMs is client-side measured. */}
          <span className="mt-1.5 block text-[9px] font-mono text-muted-foreground">
            {formatDateTime(brief.generated_at)}{" "}
            · {graphLatencyMs !== null ? `${graphLatencyMs} ms` : "—"}
          </span>
        </div>
      )}

      {/* ── Graph stats strip (node count, edge count, depth, latency) ─────── */}
      <div className="mx-3 mt-2">
        <GraphStats
          nodeCount={filteredGraph?.nodes?.length ?? 0}
          edgeCount={filteredGraph?.edges?.length ?? 0}
          depth={depth}
          latencyMs={graphLatencyMs}
        />
      </div>

      {/* ── Toolbar (depth buttons + type filter) ─────────────────────────── */}
      <div className="mx-3 mt-1">
        <GraphToolbar
          depth={depth}
          onDepthChange={setDepth}
          selectedEntityTypes={typeFilters}
          onEntityTypesChange={setTypeFilters}
          availableEntityTypes={availableEntityTypes}
        />
      </div>

      {/* ── Sigma graph canvas ────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 mx-3 mb-3 mt-2 border border-border/40 rounded-[2px] overflow-hidden">
        {graphLoading && (
          <div className="flex h-full items-center justify-center">
            <RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" strokeWidth={1.5} />
          </div>
        )}
        {isTimeout && (
          <div className="flex h-full items-center justify-center px-6 text-center text-[11px] text-muted-foreground">
            Graph timed out at depth {depth}. Try depth 1 or 2.
          </div>
        )}
        {!graphLoading && !isTimeout && filteredGraph && filteredGraph.nodes.length > 0 && (
          <EntityGraphErrorBoundary>
            <EntityGraph
              data={filteredGraph}
              centerEntityId={entityId}
              onNodeClick={handleNodeClick}
            />
          </EntityGraphErrorBoundary>
        )}
        {!graphLoading && !isTimeout && filteredGraph && filteredGraph.nodes.length === 0 && (
          <div className="flex h-full items-center justify-center px-6 text-center text-[11px] text-muted-foreground">
            No entities match the current type filter.
          </div>
        )}
        {!graphLoading && !isTimeout && !filteredGraph && !isError && (
          <div className="flex h-full items-center justify-center px-6 text-center text-[11px] text-muted-foreground">
            No graph data available.
          </div>
        )}
      </div>
    </div>
  );
}
