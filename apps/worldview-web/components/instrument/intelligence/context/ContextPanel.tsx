/**
 * context/ContextPanel.tsx — Intelligence right-rail orchestrator (W7 T-15)
 *
 * WHY THIS EXISTS:
 * The Intelligence tab right rail toggles between TWO modes driven by
 * `selectedNodeId`:
 *
 *   1. null → "Entity overview" — 5-block stack:
 *        EntityOverviewBlock → TopRelationsBlock → PathInsightsBlock
 *        → ContradictionsBlock → NarrativeHistoryDisclosure
 *
 *   2. non-null → "Node detail" — NodeDetailCard + RelationsList
 *      for the picked node, plus NodePathsBlock below.
 *
 * WHO OWNS SELECTION STATE: IntelligenceTab (parent). ContextPanel receives
 * selectedNodeId + onClearSelection + onNodeSelect as props so graph
 * highlighting and panel mode stay in sync without lifting further.
 *
 * WHY THIS STILL FETCHES GRAPH DATA:
 * NodeDetailCard + RelationsList (node-detail mode) need the sigma graph
 * to look up the selected node's label and incident edges. Entity-overview
 * blocks own their own data fetching internally — ContextPanel no longer
 * fetches entity detail or intelligence in overview mode.
 */

"use client";
// WHY "use client": useQuery + useMemo require browser context.

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import { cn } from "@/lib/utils";
import { SectionDivider } from "@/components/primitives/SectionDivider";
import { NodeDetailCard } from "./NodeDetailCard";
import { RelationsList } from "./RelationsList";
import { EntityOverviewBlock } from "./EntityOverviewBlock";
import { TopRelationsBlock } from "./TopRelationsBlock";
import { PathInsightsBlock } from "./PathInsightsBlock";
import { ContradictionsBlock } from "./ContradictionsBlock";
import { NarrativeHistoryDisclosure } from "./NarrativeHistoryDisclosure";
import { NodePathsBlock } from "./NodePathsBlock";
import type { EntityGraph, GraphEdge, GraphNode } from "@/types/api";

export interface ContextPanelProps {
  /** Primary entity for the instrument page (UUIDv7). */
  entityId: string;
  /** Node the user clicked in the graph, or null for entity-overview mode. */
  selectedNodeId: string | null;
  /** Returns the panel to entity-overview mode (clears graph selection). */
  onClearSelection: () => void;
  /** Switches to node-detail mode for the given node ID. Called by TopRelationsBlock rows. */
  onNodeSelect: (nodeId: string) => void;
  /** Optional class override for parent layout (width, border, scroll). */
  className?: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ContextPanel({
  entityId,
  selectedNodeId,
  onClearSelection,
  onNodeSelect,
  className,
}: ContextPanelProps) {
  const { accessToken } = useAuth();

  // Graph fetch — depth=1 only. Entity-overview blocks fetch their own data.
  // WHY still here: NodeDetailCard + RelationsList need the graph node lookup
  // and incident-edge list. qk.instruments.entityGraph(entityId, 1) de-dupes
  // with TopRelationsBlock (same key), so only one network request fires.
  const graphQuery = useQuery<EntityGraph | null>({
    queryKey: qk.instruments.entityGraph(entityId, 1),
    queryFn: () => createGateway(accessToken).getEntityGraph(entityId, 1),
    enabled: !!accessToken && !!entityId,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });

  // ── Derived: node lookup + incident edges for node-detail mode ────────────
  const nodesById = useMemo<Record<string, GraphNode>>(() => {
    const map: Record<string, GraphNode> = {};
    for (const node of graphQuery.data?.nodes ?? []) {
      map[node.id] = node;
    }
    return map;
  }, [graphQuery.data]);

  const selectedNode: GraphNode | null = useMemo(
    () => (selectedNodeId ? (nodesById[selectedNodeId] ?? null) : null),
    [selectedNodeId, nodesById],
  );

  const incidentEdges = useMemo<GraphEdge[]>(() => {
    if (!selectedNodeId || !graphQuery.data?.edges) return [];
    // WHY both source + target: a node is an endpoint in edges where it is
    // EITHER the origin or the destination.
    return graphQuery.data.edges.filter(
      (e) => e.source === selectedNodeId || e.target === selectedNodeId,
    );
  }, [selectedNodeId, graphQuery.data]);

  // ── Node-detail mode ──────────────────────────────────────────────────────
  // WHY check selectedNode (not selectedNodeId): if the graph refetched and
  // removed the node, degrade to entity-overview rather than crashing
  // NodeDetailCard with undefined.
  if (selectedNodeId && selectedNode) {
    return (
      <section
        className={cn("flex flex-col overflow-y-auto", className)}
        aria-label={`Detail for ${selectedNode.label}`}
      >
        <NodeDetailCard node={selectedNode} onBack={onClearSelection} />
        <div className="border-t border-border/40" />
        <RelationsList edges={incidentEdges} nodesById={nodesById} />
        <SectionDivider />
        {/* WHY NodePathsBlock below RelationsList: analyst has scanned the
            incident edges — multi-hop paths give next-level exploration. */}
        <NodePathsBlock entityId={entityId} selectedNodeId={selectedNodeId} />
      </section>
    );
  }

  // ── Entity-overview mode ──────────────────────────────────────────────────
  return (
    <section
      className={cn("flex flex-col overflow-y-auto", className)}
      aria-label="Entity overview"
    >
      <EntityOverviewBlock entityId={entityId} />
      <SectionDivider />
      {/* TopRelationsBlock fires onNodeSelect → switches to node-detail mode */}
      <TopRelationsBlock entityId={entityId} limit={10} onNodeSelect={onNodeSelect} />
      <SectionDivider />
      <PathInsightsBlock entityId={entityId} limit={3} />
      <SectionDivider />
      <ContradictionsBlock entityId={entityId} limit={5} />
      <SectionDivider />
      <NarrativeHistoryDisclosure entityId={entityId} />
    </section>
  );
}
