/**
 * components/intelligence/tabs/PathsTab.tsx — Multi-hop path insights tab
 * (PLAN-0074 Wave H T-H-04)
 *
 * WHY THIS EXISTS:
 * Direct (1-hop) relations answer "who does X have a direct relationship with?"
 * Multi-hop paths answer "what surprising indirect connections exist?"
 * e.g., "Apple → Tim Cook → Goldman Sachs → Federal Reserve" — a path that
 * reveals macroeconomic exposure through board membership. These insights are
 * unique to worldview's KG traversal and not available in any other terminal.
 *
 * WHY CARDS (not table rows):
 * Path insights are rich objects: they have a hop count, four quality scores,
 * an LLM explanation, and a path visualization (entity pills → arrow → entity pills).
 * A table row can't hold all this without becoming unreadable. Cards give each
 * insight its own visual container with the path visualization as the focal element.
 *
 * WHY AUTO-REFETCH WHEN explanation_pending:
 * LLM explanation generation is async (queued after path scoring). We poll
 * every 3 seconds when any card has explanation_pending=true. As soon as the
 * last explanation arrives the refetch interval is cleared — no unnecessary polls.
 *
 * WHY HIGHLIGHT CARDS FOR selectedEntityId:
 * When the user clicks a node in the graph, paths containing that entity are
 * highlighted with a colored border so the analyst can see which paths
 * "pass through" the entity they're investigating.
 */

"use client";

import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "@/lib/api-client";
import { useEntityPaths } from "@/lib/api/intelligence";
import { Skeleton } from "@/components/ui/skeleton";
import { RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
// PLAN-0112 T-5-03: the headline metric is now "weirdness" with a four-part
// sub-score breakdown (reliability / unexpectedness / semantic distance / novelty)
// replacing the old harmonic/diversity/surprise display.
import { WeirdnessBreakdown } from "@/components/intelligence/WeirdnessBreakdown";
import type { PathInsightPublic, PathNodePublic, PathEdgePublic } from "@/types/intelligence";
import type { EntityGraph } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface PathsTabProps {
  entityId: string;
  selectedEntityId: string;
}

// ── PathVisualization sub-component ───────────────────────────────────────────

/**
 * PathVisualization — renders the inline node pill → arrow → node pill sequence.
 *
 * WHY inline flex (not SVG):
 * The path visualization is a simple linear sequence. CSS flex layout handles
 * overflow (wrapped pills on narrow screens) better than a fixed-dimension SVG.
 * Pill + arrow + pill is a well-understood UI pattern for "A relates to B" flows.
 */
function PathVisualization({
  nodes,
  edges,
  selectedEntityId,
}: {
  nodes: PathNodePublic[];
  edges: PathEdgePublic[];
  selectedEntityId: string;
}) {
  return (
    <div
      className="flex flex-wrap items-center gap-1 my-2"
      aria-label="Path visualization"
    >
      {nodes.map((node, i) => (
        <div key={node.entity_id} className="flex items-center gap-1">
          {/* Entity pill */}
          <span
            className={cn(
              "inline-block rounded-[2px] px-2 py-0.5 text-[10px] font-mono font-medium border",
              // WHY amber highlight for selected entity:
              // The selected entity pill uses the primary (amber) color so the
              // analyst can instantly see which node in the path they're
              // investigating via the graph.
              node.entity_id === selectedEntityId
                ? "bg-primary/20 text-primary border-primary/40"
                : "bg-muted/60 text-foreground/80 border-border/60",
            )}
            title={`${node.name} (${node.entity_type})`}
          >
            {node.name}
          </span>

          {/* Arrow between nodes — render after each node except the last */}
          {i < edges.length && (
            <div className="flex items-center gap-0.5">
              <div className="h-px w-4 bg-border/60" />
              <span
                className="text-[9px] text-muted-foreground uppercase tracking-wider"
                title={edges[i].relation_type}
              >
                {edges[i].relation_type.replace(/_/g, " ").slice(0, 10)}
              </span>
              {/* WHY right-arrow: standard "flows to" convention in knowledge graphs */}
              <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true">
                <path d="M0 4h6M4 1l3 3-3 3" stroke="currentColor" strokeWidth="1.5" fill="none" className="text-border/60" />
              </svg>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── PathCard sub-component ────────────────────────────────────────────────────

function PathCard({
  insight,
  selectedEntityId,
}: {
  insight: PathInsightPublic;
  selectedEntityId: string;
}) {
  const containsSelected = insight.path_nodes.some(
    (n) => n.entity_id === selectedEntityId,
  );
  // PLAN-0112: the headline is "weirdness". The backend mirrors weirdness into
  // `composite_score`, so we prefer the explicit `weirdness` field but fall back
  // to `composite_score` for old rows where `weirdness` is null/absent (R5 back-
  // compat) — they are the same number when both are present.
  const weirdness = insight.weirdness ?? insight.composite_score;
  const pct = Math.round(weirdness * 100);

  return (
    <div
      className={cn(
        "rounded-[2px] border p-3 mb-2 mx-3",
        // WHY border highlight for selected entity path:
        // Paths that contain the graph's selected entity are highlighted
        // with a primary (amber) border — visual cross-panel linking.
        containsSelected
          ? "border-primary/40 bg-primary/5"
          : "border-border/50 bg-card/40",
      )}
      role="article"
      aria-label={`${insight.hop_count}-hop path, weirdness ${pct}%`}
    >
      {/* ── Card header ──────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {/* Hop count badge */}
          <span className="inline-block rounded-[2px] px-1.5 py-0.5 bg-muted text-muted-foreground text-[10px] font-mono font-medium uppercase">
            {insight.hop_count}hop
          </span>
          {/* Computed at timestamp */}
          <span className="text-[10px] font-mono text-muted-foreground tabular-nums">
            {new Intl.DateTimeFormat("en-US", {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            }).format(new Date(insight.computed_at))}
          </span>
        </div>

        {/* Weirdness headline bar (relabelled from "composite score"). */}
        <div className="flex items-center gap-1.5">
          {/* WHY a "WEIRD" label here (not on the old composite bar): the metric
              changed meaning; an explicit label keeps the relabel unambiguous. */}
          <span className="text-[8px] font-mono uppercase tracking-wider text-muted-foreground">
            weird
          </span>
          <div
            className="w-[48px] h-1.5 bg-muted rounded-full overflow-hidden"
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`Weirdness: ${pct}%`}
          >
            <div
              className="h-full rounded-full bg-primary"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-[10px] font-mono tabular-nums text-muted-foreground">
            {pct}%
          </span>
        </div>
      </div>

      {/* ── Path visualization ───────────────────────────────────────────── */}
      <PathVisualization
        nodes={insight.path_nodes}
        edges={insight.path_edges}
        selectedEntityId={selectedEntityId}
      />

      {/* ── Weirdness sub-score breakdown (replaces harmonic/diversity/surprise).
          Fields may be null on pre-PLAN-0112 rows → WeirdnessBreakdown renders
          "—" for those, so the relabel is back-compatible. */}
      <WeirdnessBreakdown
        reliability={insight.reliability}
        unexpectedness={insight.unexpectedness}
        semantic_distance={insight.semantic_distance}
        novelty={insight.novelty}
        className="mt-2"
      />

      {/* ── LLM explanation ─────────────────────────────────────────────── */}
      {insight.explanation_pending ? (
        // WHY spinner + "Generating":
        // The analyst just triggered or is waiting for LLM explanation generation.
        // A spinner communicates that the system is working, not frozen.
        <div className="flex items-center gap-1.5 mt-2 text-[11px] text-muted-foreground">
          <RefreshCw className="h-3 w-3 animate-spin" strokeWidth={1.5} />
          <span className="font-mono">Generating explanation…</span>
        </div>
      ) : insight.llm_explanation ? (
        <p className="mt-2 text-[11px] text-foreground/80 leading-relaxed border-t border-border/30 pt-2">
          {insight.llm_explanation}
        </p>
      ) : null}
    </div>
  );
}

// ── PathsTab component ────────────────────────────────────────────────────────

export function PathsTab({ entityId, selectedEntityId }: PathsTabProps) {
  const gw = useApiClient();
  const { data, isLoading, isError, refetch } = useEntityPaths(entityId);

  // WHY read graph cache for node labels:
  // The "Filtered to:" banner shows the selected entity's name, not its UUID.
  // We read from the same queryKey as RelationsTab/EvidenceTab — guaranteed
  // cache hit (no extra network fetch) when GraphPanel is mounted. FR-3.2 MED-009.
  const { data: graphData } = useQuery<EntityGraph | null>({
    queryKey: ["intelligence-graph", entityId, 2, false],
    queryFn: () => gw.getEntityGraph(entityId, 2, "all"),
    staleTime: 60_000,
    enabled: !!entityId,
  });

  // Build node label lookup — same pattern as RelationsTab and EvidenceTab
  const nodeLabelById = useMemo(() => {
    const map = new Map<string, string>();
    (graphData?.nodes ?? []).forEach((n) => map.set(n.id, n.label));
    return map;
  }, [graphData]);

  // WHY auto-refetch when any path has explanation_pending:
  // LLM explanation generation is async. After the user triggers a path
  // analysis, some paths will have explanation_pending=true for ~10-30s.
  // We poll every 3s to pick up explanations as they complete. Clearing
  // the interval when no paths are pending avoids unnecessary S9 load.
  useEffect(() => {
    if (!data) return;
    const hasPending = data.paths.some((p) => p.explanation_pending);
    if (!hasPending) return;
    const interval = setInterval(() => void refetch(), 3_000);
    // WHY cleanup: clear the interval when the component unmounts or when
    // the data updates (the effect re-runs and either re-schedules or skips).
    return () => clearInterval(interval);
  }, [data, refetch]);

  if (isLoading) {
    return (
      <div className="p-3 space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-[80px] w-full" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <div className="p-3 text-center text-[11px] text-muted-foreground font-mono">
        Failed to load path insights
      </div>
    );
  }

  if (!data || data.paths.length === 0) {
    return (
      <div className="p-3 text-center text-[11px] text-muted-foreground font-mono">
        No path insights computed yet
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      {/* WHY "Filtered to:" banner:
          When a graph node is selected, cards highlight paths containing that entity.
          This banner provides symmetric visual feedback (matching RelationsTab and
          EvidenceTab) so the analyst knows the graph selection is active. FR-3.2 MED-009. */}
      {selectedEntityId !== entityId && (
        <div className="px-3 py-1.5 bg-primary/10 border-b border-border/50">
          <p className="text-[10px] font-mono text-primary">
            Filtered to: {nodeLabelById.get(selectedEntityId) ?? selectedEntityId}
          </p>
        </div>
      )}

      <div className="py-2">
      {/* Freshness indicator */}
      {data.freshness_ts && (
        <p className="px-3 pb-2 text-[10px] font-mono text-muted-foreground">
          Computed:{" "}
          {new Intl.DateTimeFormat("en-US", {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          }).format(new Date(data.freshness_ts))}
          {" · "}
          {data.total} total paths
        </p>
      )}

      {data.paths.map((insight: PathInsightPublic) => (
        <PathCard
          key={insight.insight_id}
          insight={insight}
          selectedEntityId={selectedEntityId}
        />
      ))}
      </div>
    </div>
  );
}
