/**
 * context/TopRelationsBlock.tsx — top direct relations of the primary entity (W7 T-10)
 *
 * WHY THIS EXISTS: PRD-0089 W7 — when the analyst is in entity-overview mode, the
 * right rail surfaces the 10 strongest direct relations so they can quickly pivot
 * to exploring a specific neighbor without clicking through the sigma graph.
 * Clicking a relation row triggers node-detail mode (identical to clicking the
 * node directly in the graph).
 *
 * WHO USES IT: ContextPanel (entity-overview mode, below EntityOverviewBlock).
 * DATA SOURCE: GET /v1/entities/{id}/graph?depth=1 via S9 (same cache slot as
 *   ContextPanel's internal graph query — no extra network request when data is warm).
 * DESIGN REFERENCE: W7 design doc §5.2 (TopRelationsBlock, 18px rows).
 *
 * WHY INDEPENDENT DEPTH=1 FETCH (Δ7):
 * ContextPanel already fetches depth=1 for node selection. TopRelationsBlock reuses
 * the same qk.instruments.entityGraph(entityId, 1) key so TanStack Query de-dupes
 * the request — only one network call fires regardless of how many components
 * subscribe to this key.
 */

"use client";
// WHY "use client": useQuery + onClick callbacks require browser context.

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ArrowLeft, ArrowLeftRight } from "lucide-react";
import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { EntityGraph, GraphEdge, GraphNode } from "@/types/api";

export interface TopRelationsBlockProps {
  readonly entityId: string;
  /** How many top relations to show (by weight). */
  readonly limit?: number;
  /** Called when the user clicks a relation row — switches ContextPanel to node-detail mode. */
  readonly onNodeSelect: (nodeId: string) => void;
}

export function TopRelationsBlock({
  entityId,
  limit = 10,
  onNodeSelect,
}: TopRelationsBlockProps) {
  const gateway = useApiClient();

  // WHY depth=1 and staleTime=10min:
  // Δ7 — TopRelationsBlock fetches depth=1 independently; the cache key matches
  // GraphColumn's graphQuery so both share one network slot (same 10-min TTL).
  const { data: graph, isLoading, isError } = useQuery<EntityGraph | null>({
    queryKey: qk.instruments.entityGraph(entityId, 1),
    queryFn: () => gateway.getEntityGraph(entityId, 1),
    staleTime: 10 * 60 * 1000,
    enabled: !!entityId,
  });

  // Build a label lookup map so we can show the neighbor name in each row.
  const nodesById = useMemo<Record<string, GraphNode>>(() => {
    const m: Record<string, GraphNode> = {};
    for (const n of graph?.nodes ?? []) m[n.id] = n;
    return m;
  }, [graph]);

  // WHY no direction filter (F-158): the original .filter(e.source === entityId)
  // silently excluded all inbound edges (e.g. "TSMC is supplier_of Apple",
  // "Berkshire invested_in Apple"). Analysts missed half the graph context.
  // We now show outbound + inbound + lateral, sorted by direction priority then
  // weight, so the most "active" relationships appear first.
  //
  // Priority map: outbound=0 (entity acts) → inbound=1 (entity is acted upon)
  //               → lateral=2 (between non-center nodes, rare at depth=1)
  const DIRECTION_PRIORITY: Record<string, number> = { outbound: 0, inbound: 1, lateral: 2 };
  const topEdges = useMemo<GraphEdge[]>(() => {
    return (graph?.edges ?? [])
      .sort((a, b) => {
        const pa = DIRECTION_PRIORITY[a.direction ?? "outbound"] ?? 2;
        const pb = DIRECTION_PRIORITY[b.direction ?? "outbound"] ?? 2;
        if (pa !== pb) return pa - pb;
        return b.weight - a.weight; // within same direction, heaviest first
      })
      .slice(0, limit);
  // DIRECTION_PRIORITY is defined in this render scope but never changes — safe to omit.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, limit]);

  // ── Section label ─────────────────────────────────────────────────────────
  const sectionLabel = (
    <span className="text-[9px] font-mono uppercase tracking-[0.1em] text-muted-foreground px-3 py-1 block">
      TOP RELATIONS
    </span>
  );

  if (isLoading) {
    return (
      <div>
        {sectionLabel}
        {Array.from({ length: 6 }).map((_, i) => (
          // WHY 6 skeleton rows: gives the user a stable layout hint while loading.
          <div key={i} className="h-[18px] px-3 flex items-center gap-2 border-b border-border-subtle">
            <Skeleton className="h-2.5 flex-1" />
            <Skeleton className="h-2.5 w-14" />
            <Skeleton className="h-2.5 w-8" />
          </div>
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <div>
        {sectionLabel}
        <p className="text-[11px] text-muted-foreground px-3 py-2">Relations unavailable.</p>
      </div>
    );
  }

  if (topEdges.length === 0) {
    return (
      <div>
        {sectionLabel}
        <p className="text-[11px] text-muted-foreground px-3 py-2">No direct relations.</p>
      </div>
    );
  }

  return (
    <div>
      {sectionLabel}
      {topEdges.map((edge) => {
        // WHY neighborId depends on direction (F-158): for inbound edges the
        // primary entity is the TARGET — the node to navigate to is the SOURCE.
        // For outbound/lateral the neighbor is edge.target as before.
        const isInbound = edge.direction === "inbound";
        const neighborId = isInbound ? edge.source : edge.target;
        const neighbor = nodesById[neighborId];
        const neighborLabel = neighbor?.label ?? neighborId;
        // WHY toFixed(2): weight is [0,1]; 2 decimal places fits 3-char column width.
        const weightLabel = edge.weight.toFixed(2);

        return (
          <button
            key={edge.id}
            type="button"
            onClick={() => onNodeSelect(neighborId)}
            title={`${neighborLabel} — ${edge.label} (weight: ${weightLabel})`}
            className={cn(
              "w-full h-[18px] px-3 flex items-center gap-2 border-b border-border-subtle",
              "text-left hover:bg-muted/20 transition-color-only duration-100 cursor-pointer",
            )}
          >
            {/* Direction icon (F-158) — 10px arrow shows edge orientation.
                WHY display direction: "TSMC → Apple" (inbound supplier_of) is
                semantically opposite to "Apple → TSMC" (outbound). */}
            {edge.direction === "outbound" && (
              <ArrowRight
                className="h-[10px] w-[10px] shrink-0 text-muted-foreground/60"
                aria-label="outbound"
              />
            )}
            {edge.direction === "inbound" && (
              <ArrowLeft
                className="h-[10px] w-[10px] shrink-0 text-muted-foreground/60"
                aria-label="inbound"
              />
            )}
            {(edge.direction === "lateral" || edge.direction == null) && (
              <ArrowLeftRight
                className="h-[10px] w-[10px] shrink-0 text-muted-foreground/40"
                aria-label="lateral"
              />
            )}
            {/* Neighbor entity name — takes all remaining space */}
            <span className="flex-1 text-[11px] truncate text-foreground/90">{neighborLabel}</span>
            {/* Relation type — muted 9px label */}
            <span className="text-[9px] text-muted-foreground shrink-0 truncate max-w-[60px]">
              {edge.label.replace(/_/g, " ")}
            </span>
            {/* Weight — 3-char tabular-nums column */}
            <span className="text-[10px] font-mono tabular-nums text-muted-foreground w-[28px] text-right shrink-0">
              {weightLabel}
            </span>
          </button>
        );
      })}
    </div>
  );
}
