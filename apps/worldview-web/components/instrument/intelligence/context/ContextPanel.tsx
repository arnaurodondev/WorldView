/**
 * components/instrument/intelligence/context/ContextPanel.tsx — PLAN-0090 T-D-03
 *
 * WHY THIS EXISTS:
 * The Intelligence tab (PRD-0088 §6.9 + §6.10) has a right-side context panel
 * that toggles between TWO modes:
 *
 *   1. selectedNodeId == null → "Entity overview" — name, type badge,
 *      description, health-score badge for the page's primary entity.
 *
 *   2. selectedNodeId != null → "Node detail" — NodeDetailCard for the picked
 *      node + RelationsList of edges incident to that node.
 *
 * This component is the ORCHESTRATOR: it owns the data fetching (entity detail
 * + graph) and dispatches between the two modes. The child components stay
 * dumb/presentational so they remain easy to test and reuse.
 *
 * DATA SOURCES (via S9 proxy, R14):
 *   - GET /v1/entities/{id}             → EntityPublic (description, metadata)
 *   - GET /v1/entities/{id}/intelligence → EntityIntelligencePublic (health)
 *   - GET /v1/entities/{id}/graph        → EntityGraph (nodes + edges)
 *
 * WHY use the existing hooks instead of inlining fetch logic:
 * The intelligence hook already centralises cache keys, staleTime, and auth
 * token plumbing. Inlining a fetch here would duplicate that logic and risk
 * cache fragmentation (two different keys for the same data).
 */

"use client";
// WHY "use client": TanStack Query hooks and onClick callbacks require a
// browser. The whole Intelligence tab is already a client island; this just
// makes the boundary explicit.

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
import { useEntityIntelligence } from "@/lib/api/intelligence";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { NodeDetailCard } from "./NodeDetailCard";
import { RelationsList } from "./RelationsList";
import type { EntityGraph, GraphEdge, GraphNode } from "@/types/api";

/**
 * Props for ContextPanel.
 *
 * WHY entityId is required (no nullable):
 * The Intelligence tab cannot render at all without a primary entity. The
 * caller (IntelligenceTab) handles the "no entity" state at a higher level
 * and only mounts this component when an entityId is available.
 */
export interface ContextPanelProps {
  /** The PRIMARY entity for the instrument page (UUIDv7). Drives the
   *  "entity overview" mode and the graph fetch. */
  entityId: string;
  /** The node the user clicked in the graph, or null for the overview mode.
   *  Owned by IntelligenceTab so the same selection state can drive graph
   *  highlighting and this panel together. */
  selectedNodeId: string | null;
  /** Clears the selection (sets selectedNodeId back to null), returning the
   *  panel to entity-overview mode. Called by NodeDetailCard's Back button. */
  onClearSelection: () => void;
  /** Optional class override (used by parent layout for width / borders). */
  className?: string;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * formatHealthScore — numeric health → "82%" style string.
 *
 * WHY a helper: used twice (badge value + aria-label). DRY + consistent
 * rounding rule (Math.round to integer percent, no trailing decimals).
 */
function formatHealthScore(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return "—";
  return `${Math.round(score * 100)}%`;
}

/**
 * healthTone — health [0,1] → color class for the badge.
 *
 * WHY three buckets (not a continuous gradient):
 * Finance dashboards reward FAST scanning. A 3-bucket signal (red / amber /
 * green) is instantly parseable; a continuous gradient forces the eye to
 * interpret. Thresholds chosen to match other badges in the codebase
 * (alert severity HIGH/MEDIUM/LOW use the same break points).
 */
function healthTone(score: number | null | undefined): string {
  if (score == null) return "text-muted-foreground bg-muted";
  // WHY semantic tokens (not raw Tailwind palette): the no-off-palette-colors
  // Vitest + ESLint rule (PLAN-0071 P1-4) banned `text-amber-*` / `text-emerald-*`
  // because those hex values drift from the --warning / --positive CSS variables
  // every time the design system is retuned. text-positive / text-warning /
  // text-negative resolve through globals.css → tailwind.config.ts.
  if (score >= 0.75) return "text-positive bg-positive/15";
  if (score >= 0.5) return "text-warning bg-warning/15";
  return "text-negative bg-negative/15";
}

// ── Component ────────────────────────────────────────────────────────────────

export function ContextPanel({
  entityId,
  selectedNodeId,
  onClearSelection,
  className,
}: ContextPanelProps) {
  const { accessToken } = useAuth();

  // ── Entity detail (name, type, description) ──────────────────────────────
  // WHY useQuery directly (not a hook wrapper): EntityDescriptionPanel uses
  // the exact same query key + staleTime — we re-use the cache slot. No need
  // for a custom hook just for this one component.
  const entityDetailQuery = useQuery({
    queryKey: ["entity-detail", entityId],
    queryFn: () => createGateway(accessToken).getEntityDetail(entityId),
    enabled: !!accessToken && !!entityId,
    // WHY 2 hours: descriptions are stable once written by Worker 13J (the
    // overnight sweep only updates enrichment_attempts/enriched_at).
    staleTime: 2 * 60 * 60 * 1000,
    retry: 1,
  });

  // ── Entity intelligence summary (health score) ───────────────────────────
  // WHY this hook: gives us health_score for the overview-mode badge. Reuses
  // the cache slot from /lib/api/intelligence.ts so other panels (sidebar)
  // see the same fetch result without re-firing.
  const intelligenceQuery = useEntityIntelligence(entityId);

  // ── Entity graph (nodes + edges for node-detail mode) ────────────────────
  // PLAN-0099 H / Agent D audit I1: REMOVED redundant depth=1 fetch.
  // Previously this component fired its OWN depth=1 graph fetch under the
  // cache key ["entity-graph", entityId, 1, null] in parallel with
  // GraphColumn's depth=2 fetch under qk.instruments.entityGraph(entityId, 2)
  // — two separate AGE queries on the backend for visually-overlapping data.
  //
  // FIX: subscribe to the SAME depth=2 cache slot that GraphColumn fills (and
  // that the H bundle hydrator pre-warms). Then derive depth-1 neighbours
  // by filtering the depth=2 graph to edges incident on the root entity.
  // This is purely a cache subscription — no queryFn / no network call:
  //   - On cold start, the bundle hydrator seeds this key before mount.
  //   - GraphColumn renders the same cache slot, so when the analyst changes
  //     the depth slider GraphColumn refetches and ContextPanel re-derives.
  //   - If for some reason the bundle/GraphColumn have not populated yet,
  //     `data` is undefined and the component renders its existing
  //     null-guard / loading UI (no spinner regression).
  // WHY queryFn: () => null (not a real fetcher): we INTENTIONALLY do not
  // own the fetch — GraphColumn does. Returning null when the cache is
  // truly empty matches the previous component's null-graph behaviour
  // (NodeDetailCard shows no relations until the cache fills).
  const graphQuery = useQuery<EntityGraph | null>({
    queryKey: qk.instruments.entityGraph(entityId, 2),
    queryFn: () => null,
    enabled: !!accessToken && !!entityId,
    staleTime: 5 * 60 * 1000,
    retry: 0,
  });

  // WHY no depth-1 derivation here (option-A from the audit):
  // nodesById and incidentEdges below operate over the SAME depth=2 graph
  // that GraphColumn renders, so when the analyst clicks a 2-hop node the
  // detail card resolves correctly. If a depth-1-only view is needed in
  // future, simply filter `graphQuery.data.edges` to edges incident on
  // `entityId` — no extra fetch required.

  // ── Derived: lookups for the selected node ───────────────────────────────
  // WHY useMemo on both:
  // Building the lookup is O(n) over edges. Without memo it would run on
  // every render (e.g., parent state changes elsewhere). The deps array
  // ensures it only re-runs when the graph itself changes.

  const nodesById = useMemo<Record<string, GraphNode>>(() => {
    const map: Record<string, GraphNode> = {};
    if (graphQuery.data?.nodes) {
      for (const node of graphQuery.data.nodes) {
        map[node.id] = node;
      }
    }
    return map;
  }, [graphQuery.data]);

  const selectedNode: GraphNode | null = useMemo(() => {
    if (!selectedNodeId) return null;
    return nodesById[selectedNodeId] ?? null;
  }, [selectedNodeId, nodesById]);

  const incidentEdges = useMemo<GraphEdge[]>(() => {
    if (!selectedNodeId || !graphQuery.data?.edges) return [];
    // WHY filter on BOTH source and target: a node's relations include edges
    // where it is either endpoint. Without checking both, we'd under-count
    // (e.g., "Apple has executive Tim Cook" stored as Apple→Cook would not
    // appear when Cook is selected).
    return graphQuery.data.edges.filter(
      (edge) => edge.source === selectedNodeId || edge.target === selectedNodeId,
    );
  }, [selectedNodeId, graphQuery.data]);

  // ── Loading skeleton ─────────────────────────────────────────────────────
  // WHY combine into one skeleton (vs. per-section): the panel is narrow
  // (~280 px), so a single skeleton block reads cleaner than three stacked
  // ones. Mirrors EntityDescriptionPanel's skeleton density.
  if (entityDetailQuery.isLoading || intelligenceQuery.isLoading) {
    return (
      <section
        className={cn("p-3 space-y-2", className)}
        aria-label="Context panel loading"
      >
        <div className="flex items-center gap-2 mb-2">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-4 w-16 rounded-[2px]" />
        </div>
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-2/3" />
      </section>
    );
  }

  // ── Node-detail mode ─────────────────────────────────────────────────────
  // WHY check selectedNode (not selectedNodeId): if the user clicked a node
  // that has since been removed from the graph (rare, but possible after a
  // refetch), we degrade gracefully to entity-overview rather than crashing
  // NodeDetailCard with `node={undefined}`.
  if (selectedNodeId && selectedNode) {
    return (
      <section
        className={cn("flex flex-col", className)}
        aria-label={`Detail for ${selectedNode.label}`}
      >
        <NodeDetailCard node={selectedNode} onBack={onClearSelection} />
        {/* WHY a thin separator: the two sub-sections share the same panel
            and need a visual divider so the eye does not blur them together.
            border-border/40 = same weight as RelationsList row borders. */}
        <div className="border-t border-border/40" />
        <RelationsList edges={incidentEdges} nodesById={nodesById} />
      </section>
    );
  }

  // ── Entity-overview mode (default / when selection is null) ──────────────
  const entity = entityDetailQuery.data;
  const intelligence = intelligenceQuery.data;

  // WHY a null-guard (not error UI): when an entity is too new, the detail
  // endpoint may not yet have a record. Showing nothing is consistent with
  // EntityDescriptionPanel (same data, same null behaviour).
  if (!entity) {
    return (
      <section
        className={cn("p-3", className)}
        aria-label="No entity context available"
      >
        <p className="text-[11px] text-muted-foreground italic">
          No entity context available.
        </p>
      </section>
    );
  }

  // WHY normalise type for display: KG entity_type uses snake_case
  // ("financial_instrument"). See NodeDetailCard for the same treatment.
  const typeLabel = entity.entity_type.replace(/_/g, " ");
  const healthScore = intelligence?.health_score ?? null;
  const healthLabel = formatHealthScore(healthScore);
  const healthClass = healthTone(healthScore);

  return (
    <section
      className={cn("p-3 space-y-3", className)}
      aria-label="Entity overview"
    >
      {/* ── Header: name + type badge + health badge ─────────────────────── */}
      <div className="flex items-center gap-2">
        <h3
          className="text-[12px] font-medium text-foreground leading-tight truncate"
          title={entity.canonical_name}
        >
          {entity.canonical_name}
        </h3>
        <span className="shrink-0 text-[9px] font-mono uppercase tracking-wider bg-muted text-muted-foreground px-1.5 py-0.5 rounded-[2px]">
          {typeLabel}
        </span>
        {/* WHY the health badge to the right: consistent with the rest of
            the platform (severity/quality indicators always trail the name).
            ml-auto pushes it to the row's end without flex tricks. */}
        <span
          className={cn(
            "ml-auto shrink-0 text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded-[2px] tabular-nums",
            healthClass,
          )}
          aria-label={`Health score ${healthLabel}`}
          title="Composite health: freshness + completeness + confidence"
        >
          {healthLabel}
        </span>
      </div>

      {/* ── Description ───────────────────────────────────────────────────
          WHY fallback string (not hiding the paragraph): the description
          slot has reserved vertical space; collapsing it would cause layout
          jump when the data later loads in (TanStack background refetch). */}
      <p className="text-[11px] text-foreground/80 leading-relaxed">
        {entity.description ?? "No description available."}
      </p>
    </section>
  );
}
