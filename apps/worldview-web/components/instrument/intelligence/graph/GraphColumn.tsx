/**
 * GraphColumn — PLAN-0090 T-D-04 — middle column of Intelligence tab (PRD-0088 §6.9).
 * Renders: FULL AI brief → GraphToolbar → sigma.js entity graph.
 * Owns depth + typeFilters; `selectedNodeId` lives in the parent IntelligenceTab.
 * WHY 3 s timeout: AGE Cypher at depth=3 commonly takes 4-8 s on cold cache;
 * > 3 s leaves the analyst on a blank canvas. Abort → typed GRAPH_TIMEOUT error.
 */

"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { RefreshCw } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import { GraphToolbar } from "@/components/instrument/graph/GraphToolbar";
import { EntityGraphErrorBoundary } from "@/components/instrument/EntityGraphErrorBoundary";
import { MarkdownContent } from "@/components/ui/markdown-content";
import type { BriefingResponse, EntityGraph as EntityGraphData } from "@/types/api";

// WHY ssr:false: EntityGraph uses sigma.js (WebGL) which needs a browser.
const EntityGraph = dynamic(
  () => import("@/components/instrument/EntityGraph").then((m) => ({ default: m.EntityGraph })),
  { ssr: false, loading: () => <div className="flex h-full items-center justify-center"><RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" strokeWidth={1.5} /></div> },
);

const BRIEF_STALE_MS = 10 * 60 * 1000;
const GRAPH_STALE_MS = 10 * 60 * 1000;
const GRAPH_TIMEOUT_MS = 3000;

export interface GraphColumnProps {
  entityId: string;
  selectedNodeId: string | null;
  onNodeSelect: (nodeId: string | null) => void;
}

export function GraphColumn({ entityId, selectedNodeId, onNodeSelect }: GraphColumnProps) {
  const { accessToken } = useAuth();
  const [depth, setDepth] = useState<number>(2);
  const [typeFilters, setTypeFilters] = useState<string[]>([]);

  const { data: brief } = useQuery<BriefingResponse>({
    queryKey: qk.instruments.brief(entityId),
    queryFn: () => createGateway(accessToken).getInstrumentBrief(entityId),
    enabled: !!accessToken && !!entityId,
    staleTime: BRIEF_STALE_MS,
    retry: false, // brief 404s for cold instruments; retry just hammers LLM
  });

  // WHY AbortController inside queryFn: chain TanStack's unmount signal and add
  // our 3 s deadline. Abort is translated to a typed Error for the UI.
  const { data: graphData, isLoading: graphLoading, isError, error: graphErr } = useQuery<EntityGraphData | null>({
    queryKey: qk.instruments.entityGraph(entityId, depth),
    queryFn: async ({ signal }) => {
      const ctrl = new AbortController();
      signal?.addEventListener("abort", () => ctrl.abort());
      const timer = setTimeout(() => ctrl.abort(), GRAPH_TIMEOUT_MS);
      try { return await createGateway(accessToken).getEntityGraph(entityId, depth); }
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

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {brief?.narrative && (
        <div className="mx-3 mt-3 p-3 bg-card border border-border/50 rounded-[2px]">
          <div className="mb-2 flex items-baseline justify-between">
            <span className="text-[10px] font-mono uppercase tracking-[0.08em] text-muted-foreground">Intelligence Brief</span>
            <span className="font-mono text-[10px] tabular-nums text-muted-foreground">{new Date(brief.generated_at).toISOString().slice(0, 16).replace("T", " ")} UTC</span>
          </div>
          <div className="text-[11px] leading-[1.6] text-foreground/80"><MarkdownContent size="compact">{brief.narrative}</MarkdownContent></div>
        </div>
      )}
      <div className="mx-3 mt-2"><GraphToolbar depth={depth} onDepthChange={setDepth} selectedEntityTypes={typeFilters} onEntityTypesChange={setTypeFilters} availableEntityTypes={availableEntityTypes} /></div>
      <div className="flex-1 min-h-0 mx-3 mb-3 mt-2 border border-border/40 rounded-[2px] overflow-hidden">
        {graphLoading && <div className="flex h-full items-center justify-center"><RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" strokeWidth={1.5} /></div>}
        {isTimeout && <div className="flex h-full items-center justify-center px-6 text-center text-[11px] text-muted-foreground">Graph timed out at depth {depth}. Try depth 1 or 2.</div>}
        {!graphLoading && !isTimeout && filteredGraph && filteredGraph.nodes.length > 0 && (
          <EntityGraphErrorBoundary><EntityGraph data={filteredGraph} centerEntityId={entityId} onNodeClick={handleNodeClick} /></EntityGraphErrorBoundary>
        )}
        {!graphLoading && !isTimeout && filteredGraph && filteredGraph.nodes.length === 0 && (
          <div className="flex h-full items-center justify-center px-6 text-center text-[11px] text-muted-foreground">No entities match the current type filter.</div>
        )}
      </div>
    </div>
  );
}
