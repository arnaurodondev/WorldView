/**
 * components/instrument/IntelligenceTab.tsx — Instrument Intelligence tab (orchestrator)
 *
 * WHY THIS EXISTS:
 * The Intelligence tab on the instrument page surfaces "what does the platform
 * KNOW about this entity?" — distinct from price (Overview) and metrics
 * (Fundamentals). After 2026-05-09 redesign (audit: docs/audits/2026-05-09-qa-intelligence-tab-redesign.md)
 * it pulls the rich PLAN-0074 intelligence payload — health score, narrative,
 * confidence breakdown, source distribution, key metrics — and reuses the
 * dedicated Wave H components (`HealthScoreBadge`, `NarrativeCard`, etc.)
 * inline so analysts no longer see an empty/floppy graph-only view.
 *
 * SECTIONS (top → bottom):
 *
 * 1. Intelligence summary grid (IntelligenceSummarySection) — health badge,
 *    narrative card, evidence quality, source distribution, key metrics, trend.
 *
 * 2. Entity Knowledge Graph (EntityGraph sigma.js, unchanged from prior version).
 *    Filter toolbar (IntelligenceFilters) + right sidebar (GraphDetailSidebar).
 *
 * 3. AI Intelligence Brief (InstrumentBriefSection) — markdown brief from
 *    /v1/briefings/instrument/{id}. Shown only when data is available.
 *
 * 4. Detected Contradictions — NLP-extracted conflicting claims. Hidden when
 *    the contradictions array is empty.
 *
 * ARCHITECTURE:
 * This file is the orchestrator only — all rendering logic lives in:
 *   - intelligence/IntelligenceSummarySection.tsx
 *   - intelligence/IntelligenceFilters.tsx  (+ filter types/constants)
 *   - intelligence/GraphDetailSidebar.tsx   (+ SelectedNodeInfo type)
 *   - intelligence/ContradictionCard.tsx
 *   - intelligence/InstrumentBriefSection.tsx
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx (Intelligence tab)
 *
 * DATA SOURCES (all via S9 gateway):
 *   - GET /v1/entities/{entityId}/intelligence  (useEntityIntelligence)
 *   - GET /v1/entities/{entityId}/graph?depth=2 (entity graph)
 *   - GET /v1/entities/{entityId}/contradictions (NLP contradictions)
 *   - GET /v1/briefings/instrument/{entityId} (instrument AI brief)
 */

"use client";
// WHY "use client": uses useQuery for async data fetching, useState, sigma.js WebGL.

import dynamic from "next/dynamic";
import { EntityDescriptionPanel } from "@/components/instrument/EntityDescriptionPanel";
import { EntityGraphErrorBoundary } from "@/components/instrument/EntityGraphErrorBoundary";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Clock } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { Contradiction } from "@/types/api";
import { useState, useMemo, useCallback } from "react";
// Sub-components extracted into intelligence/ subdirectory (PLAN-0089 D-2)
import { IntelligenceSummarySection } from "@/components/instrument/intelligence/IntelligenceSummarySection";
import { IntelligenceFilters, DEFAULT_FILTERS } from "@/components/instrument/intelligence/IntelligenceFilters";
import type { IntelligenceFilterState } from "@/components/instrument/intelligence/IntelligenceFilters";
import { GraphDetailSidebar } from "@/components/instrument/intelligence/GraphDetailSidebar";
import type { SelectedNodeInfo } from "@/components/instrument/intelligence/GraphDetailSidebar";
import { ContradictionCard } from "@/components/instrument/intelligence/ContradictionCard";
import { InstrumentBriefSection } from "@/components/instrument/intelligence/InstrumentBriefSection";

// ── EntityGraph dynamic import (ssr:false) ────────────────────────────────────
// WHY next/dynamic with ssr:false: EntityGraph.tsx uses sigma.js which creates a
// WebGL context. SSR has no browser/WebGL environment.
const EntityGraph = dynamic(
  () => import("@/components/instrument/EntityGraph").then((m) => ({ default: m.EntityGraph })),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[460px] items-center justify-center rounded-[2px] border border-border/40 bg-card/30">
        <RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" strokeWidth={1.5} />
      </div>
    ),
  },
);

// ── Constants ─────────────────────────────────────────────────────────────────

const GRAPH_STALE_MS = 24 * 60 * 60 * 1000;

// ── Props ─────────────────────────────────────────────────────────────────────

interface IntelligenceTabProps {
  entityId: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function IntelligenceTab({ entityId }: IntelligenceTabProps) {
  const { accessToken } = useAuth();

  const [severityFilter, setSeverityFilter] = useState<"HIGH" | "MEDIUM" | "LOW" | null>(null);
  const [graphFilters, setGraphFilters] = useState<IntelligenceFilterState>(DEFAULT_FILTERS);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // WHY SelectedNodeInfo | null: null = nothing selected → sidebar shows graph stats.
  // Set by handleNodeClick which is passed to EntityGraph.onNodeClick.
  const [selectedNode, setSelectedNode] = useState<SelectedNodeInfo | null>(null);

  // ── Entity graph query ──────────────────────────────────────────────────────
  const { data: graphData, dataUpdatedAt: graphUpdatedAt } = useQuery({
    queryKey: ["entity-graph", entityId, graphFilters.depth, graphFilters.timeWindow],
    queryFn: () => createGateway(accessToken).getEntityGraph(entityId, graphFilters.depth, graphFilters.timeWindow),
    enabled: !!accessToken && !!entityId,
    staleTime: 10 * 60_000,
  });

  // ── Dynamic entity types ────────────────────────────────────────────────────
  const availableEntityTypes = useMemo<string[]>(() => {
    if (!graphData?.nodes?.length) return [];
    const typeSet = new Set<string>();
    for (const node of graphData.nodes) { if (node.type) typeSet.add(node.type); }
    return Array.from(typeSet).sort();
  }, [graphData]);

  // ── Contradictions query ────────────────────────────────────────────────────
  const { data: resp, isLoading, isError } = useQuery({
    queryKey: ["contradictions", entityId],
    queryFn: () => createGateway(accessToken).getContradictions(entityId),
    enabled: !!accessToken && !!entityId,
    staleTime: 10 * 60_000,
  });

  // ── Client-side graph filtering ─────────────────────────────────────────────
  const filteredGraphData = useMemo(() => {
    if (!graphData) return graphData;
    const { relationTypes, entityTypes, confidenceThreshold } = graphFilters;
    const filteredEdges = graphData.edges.filter((edge) => {
      if (edge.weight < confidenceThreshold) return false;
      if (relationTypes.length > 0 && !relationTypes.includes(edge.label)) return false;
      return true;
    });
    const reachableIds = new Set<string>([graphData.entity_id]);
    for (const e of filteredEdges) { reachableIds.add(e.source); reachableIds.add(e.target); }
    const filteredNodes = graphData.nodes.filter(
      (node) => reachableIds.has(node.id) && (entityTypes.length === 0 || entityTypes.includes(node.type)),
    );
    return { ...graphData, nodes: filteredNodes, edges: filteredEdges };
  }, [graphData, graphFilters]);

  const isGraphStale = graphUpdatedAt > 0 && Date.now() - graphUpdatedAt > GRAPH_STALE_MS;
  const graphAgeHours = graphUpdatedAt > 0 ? Math.floor((Date.now() - graphUpdatedAt) / (60 * 60 * 1000)) : 0;

  // ── Node click handler — populates the right sidebar ────────────────────────
  // WHY useCallback with stable deps: passed as prop to EntityGraph which feeds it
  // into a sigma useEffect dep array. Without useCallback it would re-register sigma
  // event listeners on every render.
  const handleNodeClick = useCallback((
    nodeId: string,
    label: string,
    nodeType: string,
    degree: number,
    edges: SelectedNodeInfo["edges"],
  ) => {
    setSelectedNode({ nodeId, label, nodeType, degree, edges });
  }, []);

  // ── Contradictions data ─────────────────────────────────────────────────────
  const contradictions = resp?.contradictions ?? [];
  const SEVERITY_ORDER: Record<Contradiction["severity"], number> = { HIGH: 0, MEDIUM: 1, LOW: 2 };
  const sorted = [...contradictions].sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);
  const filtered = sorted.filter((c) => !severityFilter || c.severity === severityFilter);

  return (
    // WHY flex (not grid): left column grows to fill available width; right sidebar
    // is a fixed 270px. Grid would require a named template; flex is simpler here.
    <div className="flex min-h-0">

      {/* ── Left column: summary + graph + brief + contradictions ─────────── */}
      <div className="flex-1 min-w-0 flex flex-col divide-y divide-border/40">

        {/* PLAN-0074 rich intelligence summary — health badge, narrative card,
            confidence breakdown, source distribution, key metrics, trend
            sparkline, and a deep-link to the standalone /intelligence page. */}
        <IntelligenceSummarySection entityId={entityId} />

        {/* Entity description panel (PRD-0073 Worker 13J enrichment).
            WHY below summary: the LLM-generated narrative in
            IntelligenceSummarySection supersedes the static description for
            most entities. Renders nothing when description is null. */}
        <EntityDescriptionPanel entityId={entityId} />

        {/* Entity Knowledge Graph section */}
        <section className="p-3">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">Entity Knowledge Graph</h3>
            <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
              depth {graphFilters.depth} · {filteredGraphData?.nodes?.length ?? 0} entities
            </span>
          </div>

          {/* Filter toolbar */}
          <div className="mb-2">
            <IntelligenceFilters
              filters={graphFilters}
              onFiltersChange={setGraphFilters}
              availableEntityTypes={availableEntityTypes}
            />
          </div>

          {/* Stale indicator */}
          {isGraphStale && (
            <div className="mb-2 flex items-center gap-2 rounded-[2px] border border-warning/30 bg-warning/5 px-3 py-1.5">
              <Clock className="h-3 w-3 shrink-0 text-warning" aria-hidden="true" strokeWidth={1.5} />
              <span className="text-[11px] text-warning">
                Graph last updated {graphAgeHours}h ago — newer relations may not be reflected.
              </span>
            </div>
          )}

          {/* Graph canvas */}
          {filteredGraphData ? (
            <>
              {filteredGraphData.nodes.length === 0 ? (
                <div className="flex h-[460px] items-center justify-center rounded-[2px] border border-border/40 bg-card/30">
                  <p className="text-[11px] text-muted-foreground">
                    No nodes match the current filters.{" "}
                    <button
                      onClick={() => setGraphFilters(DEFAULT_FILTERS)}
                      className="text-primary underline underline-offset-2 hover:no-underline"
                    >Reset filters</button>
                  </p>
                </div>
              ) : (
                <EntityGraphErrorBoundary>
                  <EntityGraph
                    data={filteredGraphData}
                    centerEntityId={entityId}
                    onNodeClick={handleNodeClick}
                  />
                </EntityGraphErrorBoundary>
              )}
            </>
          ) : (
            <div className="flex h-[460px] items-center justify-center rounded-[2px] border border-border/40 bg-card/30">
              <RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" strokeWidth={1.5} />
            </div>
          )}
        </section>

        {/* AI brief */}
        <InstrumentBriefSection entityId={entityId} />

        {/* Contradictions — only mount when we have something to show.
            WHY conditional <section>: when there are zero contradictions we
            also drop the divide-y border line and 12px padding above. */}
        {(isLoading || isError || contradictions.length > 0) && (
        <section className="p-3">
          {isLoading && (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="space-y-2 rounded-[2px] border border-border/40 p-3">
                  <div className="flex justify-between">
                    <Skeleton className="h-4 w-12" />
                    <Skeleton className="h-4 w-16" />
                  </div>
                  <Skeleton className="h-12 w-full" />
                  <Skeleton className="h-12 w-full" />
                </div>
              ))}
            </div>
          )}
          {isError && !isLoading && (
            <p className="text-[11px] text-muted-foreground">Could not load intelligence data. Try again shortly.</p>
          )}
          {!isLoading && !isError && contradictions.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">Detected Contradictions</h3>
                <span className="rounded-[2px] bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
                  {contradictions.length} found
                </span>
              </div>
              {/* Temporal histogram */}
              {(() => {
                const now = Date.now();
                const WEEK_MS = 7 * 24 * 60 * 60 * 1000;
                const buckets = Array.from({ length: 8 }, (_, i) => ({
                  weekAgo: i,
                  count: contradictions.filter((c) => {
                    const age = now - new Date(c.detected_at).getTime();
                    return age >= i * WEEK_MS && age < (i + 1) * WEEK_MS;
                  }).length,
                })).reverse();
                const maxCount = Math.max(1, ...buckets.map((b) => b.count));
                return (
                  <div className="flex items-end gap-px h-[30px] mb-2">
                    {buckets.map((b, i) => (
                      <div key={i} className="flex-1 flex items-end justify-center" title={`${b.count} signals ${b.weekAgo === 0 ? "this week" : `${b.weekAgo}w ago`}`}>
                        <div className="w-full bg-primary/30 hover:bg-primary/60 cursor-pointer transition-colors" style={{ height: `${Math.max(2, (b.count / maxCount) * 28)}px` }} />
                      </div>
                    ))}
                  </div>
                );
              })()}
              {/* Severity filter strip */}
              <div className="flex items-center gap-2 h-[22px] px-0 mb-1">
                {(["HIGH", "MEDIUM", "LOW"] as const).map((sev) => {
                  const count = contradictions.filter((c) => c.severity === sev).length;
                  return (
                    <button
                      key={sev}
                      onClick={() => setSeverityFilter((f) => (f === sev ? null : sev))}
                      className={cn(
                        "font-mono text-[10px] tabular-nums",
                        sev === "HIGH"
                          ? severityFilter === "HIGH" ? "text-negative font-medium" : "text-negative/60"
                          : sev === "MEDIUM"
                          ? severityFilter === "MEDIUM" ? "text-warning font-medium" : "text-warning/60"
                          : severityFilter === "LOW" ? "text-muted-foreground font-medium" : "text-muted-foreground/60",
                      )}
                    >{sev} {count}</button>
                  );
                })}
                {severityFilter && (
                  <button onClick={() => setSeverityFilter(null)} className="text-[10px] text-muted-foreground hover:text-foreground ml-auto">
                    Clear filter
                  </button>
                )}
              </div>
              {/* Contradiction rows */}
              {filtered.map((item) => (
                <ContradictionCard
                  key={item.contradiction_id}
                  item={item}
                  isExpanded={expandedId === item.contradiction_id}
                  onToggle={() => setExpandedId((id) => id === item.contradiction_id ? null : item.contradiction_id)}
                />
              ))}
            </div>
          )}
        </section>
        )}
      </div>

      {/* ── Right sidebar: node/edge detail panel ──────────────────────────── */}
      {/* WHY sticky-ish via self-start: the sidebar should stay visible while
          the analyst scrolls through brief/contradictions below the graph.
          270px is wide enough for entity labels without competing with the
          graph's 460px height. */}
      <aside
        className="w-[270px] shrink-0 border-l border-border/40 bg-card/10 flex flex-col"
        // WHY min-h-0: prevents flex children from overflowing the aside boundary
        // in Firefox when the content is taller than the container.
        style={{ minHeight: 0 }}
      >
        <GraphDetailSidebar
          selectedNode={selectedNode}
          graphData={filteredGraphData}
          onClearSelection={() => setSelectedNode(null)}
        />
      </aside>
    </div>
  );
}
