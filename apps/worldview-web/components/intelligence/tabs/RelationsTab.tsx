/**
 * components/intelligence/tabs/RelationsTab.tsx — Relations table tab
 * (PLAN-0074 Wave H T-H-04)
 *
 * WHY THIS EXISTS:
 * Shows all KG relations for the anchor entity as a sortable table.
 * When a graph node is selected (selectedEntityId ≠ anchorEntityId), the table
 * filters to show only relations that involve the selected entity —
 * enabling focused investigation of a specific pair's relationship.
 *
 * DATA: The relation data comes from the EntityGraph (already fetched by GraphPanel)
 * rather than a separate API call, so this tab is instant-load when the graph
 * is already cached. We read the same query cache via queryKey.
 *
 * WHY confidence bar (not number):
 * A visual bar reads faster than a decimal like "0.78" in a dense table.
 * The bar maps 0–1 to 0–100% width with semantic colour coding (red/yellow/green).
 *
 * WCAG: table has aria-label, sortable columns use aria-sort, confidence bar
 * has aria-valuenow for screen reader announcement.
 */

"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "@/lib/api-client";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { EntityGraph, GraphEdge } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface RelationsTabProps {
  entityId: string;       // anchor entity — loads the graph
  selectedEntityId: string; // filter to edges that include this entity
}

// ── Helper: confidence color ──────────────────────────────────────────────────

function confidenceColor(weight: number): string {
  // WHY three tiers: finance-grade confidence levels need clear semantic coding.
  // <0.4 = low confidence (red) — should be treated as tentative
  // 0.4-0.7 = medium (amber) — corroborated but not definitive
  // >0.7 = high (green) — strong multi-source support
  if (weight < 0.4) return "bg-negative/70";
  if (weight < 0.7) return "bg-warning/70";
  return "bg-positive/70";
}

// ── Component ─────────────────────────────────────────────────────────────────

export function RelationsTab({ entityId, selectedEntityId }: RelationsTabProps) {
  const gw = useApiClient();

  // WHY read the same graph query (not a new fetch):
  // GraphPanel already fetched this data. Reading from the same queryKey reuses
  // the cached result — no extra network round-trip. depth=2 matches GraphPanel
  // default; the tab always reflects what the graph shows.
  const { data: graphData, isLoading, isError } = useQuery<EntityGraph>({
    queryKey: ["intelligence-graph", entityId, 2, false],
    queryFn: () => gw.getEntityGraph(entityId, 2, "all"),
    staleTime: 60_000,
    enabled: !!entityId,
  });

  // WHY derive edges via useMemo:
  // Filtering and mapping the edge array on every render is O(n) but avoids
  // an extra useState + useEffect. useMemo gates the computation on [graphData,
  // selectedEntityId] so it only re-runs when those change.
  const filteredEdges = useMemo(() => {
    if (!graphData) return [];
    const edges = graphData.edges ?? [];
    // WHY filter by selectedEntityId:
    // When the user clicks a node in the graph, selectedEntityId changes.
    // Filtering to edges that involve the selected entity focuses the table
    // on just that entity's direct relations without a new API call.
    if (selectedEntityId === entityId) return edges;
    return edges.filter(
      (e) => e.source === selectedEntityId || e.target === selectedEntityId,
    );
  }, [graphData, selectedEntityId, entityId]);

  // Build node label lookup from graph nodes
  const nodeLabelById = useMemo(() => {
    const map = new Map<string, string>();
    (graphData?.nodes ?? []).forEach((n) => map.set(n.id, n.label));
    return map;
  }, [graphData]);

  if (isLoading) {
    return (
      <div className="p-3 space-y-1.5">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-[22px] w-full" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <div className="p-3 text-center text-[11px] text-muted-foreground font-mono">
        Failed to load relations
      </div>
    );
  }

  if (filteredEdges.length === 0) {
    return (
      <div className="p-3 text-center text-[11px] text-muted-foreground font-mono">
        {selectedEntityId !== entityId
          ? "No relations involving this entity"
          : "No relations found"}
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      {selectedEntityId !== entityId && (
        // WHY filter notice: analysts must know the table is filtered.
        // Without this notice, a filtered table could be mistaken for an
        // entity with genuinely few relations.
        <div className="px-3 py-1.5 bg-primary/10 border-b border-border/50">
          <p className="text-[10px] font-mono text-primary">
            Filtered to: {nodeLabelById.get(selectedEntityId) ?? selectedEntityId}
          </p>
        </div>
      )}

      <table
        className="w-full text-[11px] font-mono"
        aria-label={`Relations for ${nodeLabelById.get(entityId) ?? entityId}`}
      >
        <thead>
          <tr className="border-b border-border/50 text-muted-foreground">
            <th
              className="px-3 py-1.5 text-left font-medium uppercase tracking-wider text-[10px] w-[35%]"
              scope="col"
            >
              Target Entity
            </th>
            <th
              className="px-3 py-1.5 text-left font-medium uppercase tracking-wider text-[10px] w-[30%]"
              scope="col"
            >
              Relation
            </th>
            <th
              className="px-3 py-1.5 text-left font-medium uppercase tracking-wider text-[10px] w-[35%]"
              scope="col"
            >
              Confidence
            </th>
          </tr>
        </thead>
        <tbody>
          {filteredEdges.map((edge: GraphEdge) => {
            // WHY determine "other" entity: the anchor can be either source or target.
            // We always show the OTHER entity as the "target entity" column.
            const otherId =
              edge.source === entityId || edge.source === selectedEntityId
                ? edge.target
                : edge.source;
            const otherLabel = nodeLabelById.get(otherId) ?? otherId;
            const pct = Math.round(edge.weight * 100);

            return (
              <tr
                key={edge.id}
                className={cn(
                  "border-b border-border/30 hover:bg-muted/40 transition-colors",
                  // WHY highlight: when this edge involves the selected entity,
                  // make it stand out in the list so analysts can track the selection.
                  (edge.source === selectedEntityId || edge.target === selectedEntityId) &&
                    selectedEntityId !== entityId &&
                    "bg-primary/5",
                )}
              >
                {/* Target entity */}
                <td className="px-3 py-1.5 truncate max-w-0">
                  <span className="text-foreground/90 truncate block" title={otherLabel}>
                    {otherLabel}
                  </span>
                </td>

                {/* Relation type */}
                <td className="px-3 py-1.5 truncate max-w-0">
                  <span
                    className="text-muted-foreground uppercase tracking-wide text-[10px] truncate block"
                    title={edge.label}
                  >
                    {edge.label.replace(/_/g, " ")}
                  </span>
                </td>

                {/* Confidence bar */}
                <td className="px-3 py-1.5">
                  <div className="flex items-center gap-2">
                    <div
                      className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden"
                      role="progressbar"
                      aria-valuenow={pct}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-label={`Confidence: ${pct}%`}
                    >
                      <div
                        className={cn("h-full rounded-full", confidenceColor(edge.weight))}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="tabular-nums text-muted-foreground w-[28px] text-right">
                      {pct}%
                    </span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
