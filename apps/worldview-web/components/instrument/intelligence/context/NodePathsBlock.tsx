/**
 * context/NodePathsBlock.tsx — paths from the selected node (W7 T-14)
 *
 * WHY THIS EXISTS: PRD-0089 W7 — when the analyst clicks a graph node, the
 * right rail switches to node-detail mode. NodePathsBlock surfaces multi-hop
 * paths that START from the selected node so the analyst can explore the
 * selected entity's graph neighbourhood without losing their exploration context.
 *
 * WHO USES IT: ContextPanel (node-detail mode, below RelationsList).
 * DATA SOURCE: GET /v1/entities/{selectedNodeId}/paths → EntityPathsResponse.
 * DESIGN REFERENCE: W7 design doc §5.6 (NodePathsBlock, 38px cards).
 *
 * WHY NO PORTFOLIO FILTER (unlike PathInsightsBlock):
 * When the user is in node-detail mode they are exploring a SPECIFIC node.
 * Filtering by portfolio holdings would hide relevant paths and defeat the
 * purpose of node exploration. All paths are shown, up to the 3-card limit.
 *
 * WHY FALLBACK NOTE "(paths to primary entity)":
 * Risk R-3 — the S9 /v1/entities/{id}/paths endpoint does NOT support a
 * `target_entity_id` query parameter. We cannot narrow paths to those that
 * specifically connect the selected node to the primary entity. Instead, we
 * fetch all paths from the selected node and add a parenthetical note so
 * the analyst understands the paths are node-egocentric, not bidirectional.
 */

"use client";
// WHY "use client": useEntityPaths uses TanStack Query hooks (browser-only).

import { useEntityPaths } from "@/lib/api/intelligence";
import { Skeleton } from "@/components/ui/skeleton";

export interface NodePathsBlockProps {
  /** The PRIMARY entity for the instrument page — used for display context. */
  readonly entityId: string;
  /** The SELECTED node whose paths are being explored. */
  readonly selectedNodeId: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function NodePathsBlock({ entityId: _entityId, selectedNodeId }: NodePathsBlockProps) {
  // WHY useEntityPaths(selectedNodeId): paths are fetched from the SELECTED node,
  // not the primary entity. The primary entityId is unused here (kept in props
  // for future target filtering if S9 adds support for target_entity_id).
  const { data, isLoading, isError } = useEntityPaths(selectedNodeId);

  const paths = (data?.paths ?? []).slice(0, 3);

  const sectionLabel = (
    // WHY "(paths to primary entity)": R-3 fallback note — S9 doesn't support
    // target_entity_id filter so we show all paths from the selected node.
    <span className="text-[9px] font-mono uppercase tracking-[0.1em] text-muted-foreground px-3 py-1 block">
      NODE PATHS{" "}
      <span className="normal-case text-[8px]">(paths to primary entity)</span>
    </span>
  );

  if (isLoading) {
    return (
      <div>
        {sectionLabel}
        <div className="px-3 py-1">
          <Skeleton className="h-[38px] w-full" />
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div>
        {sectionLabel}
        <p className="text-[11px] text-muted-foreground px-3 py-2">Path data unavailable.</p>
      </div>
    );
  }

  if (paths.length === 0) {
    return (
      <div>
        {sectionLabel}
        <p className="text-[11px] text-muted-foreground px-3 py-2">No paths discovered.</p>
      </div>
    );
  }

  return (
    <div>
      {sectionLabel}
      <div className="space-y-1 px-3">
        {paths.map((path) => {
          const pathLabel = path.path_nodes.map((n) => n.name).join(" → ");
          const relationTypes = Array.from(
            new Set(
              path.path_edges.map((e) => e.relation_type.toLowerCase().replace(/_/g, " ")),
            ),
          );

          return (
            <div
              key={path.insight_id}
              className="min-h-[38px] py-1 px-2 flex flex-col justify-center border border-border-subtle"
            >
              <span className="text-[11px] text-foreground/90 truncate w-full">{pathLabel}</span>
              <span className="text-[9px] text-muted-foreground mt-0.5">
                {path.hop_count} hop{path.hop_count !== 1 ? "s" : ""}{" "}
                · {relationTypes.slice(0, 3).join(", ")}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
