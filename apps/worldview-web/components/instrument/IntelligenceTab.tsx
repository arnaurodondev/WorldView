/**
 * components/instrument/IntelligenceTab.tsx — Intelligence tab: entity graph + AI brief + contradictions
 *
 * WHY THIS EXISTS: The Intelligence tab gives analysts a holistic view of an entity's
 * relationship network and conflicting signals in one place. Three sections:
 *
 * 1. Entity Knowledge Graph (sigma.js) — full depth=2 interactive WebGL graph showing
 *    how this entity connects to others: competitors, executives, suppliers, macro events.
 *    Replaces the compact Overview sidebar SVG for deeper exploration.
 *
 * 2. AI Intelligence Brief — AI-generated summary of recent developments, risk factors,
 *    and price-relevant signals (uses getInstrumentBrief S9 endpoint).
 *
 * 3. Detected Contradictions — NLP-extracted conflicting claims across recent articles.
 *    These are HIGH-signal for risk-aware investors and the unique worldview differentiator.
 *
 * LAYOUT (post-redesign):
 *   Two-column: main content (graph + brief + contradictions) on the left,
 *   a sticky right sidebar (270px) that shows clicked-node details or graph-level stats
 *   when nothing is selected. Clicking a node in the sigma graph calls onNodeClick which
 *   populates the sidebar — the sidebar replaces the default router.push navigation.
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx (Intelligence tab)
 * DATA SOURCES:
 *   - S9 GET /v1/entities/{entityId}/graph?depth=2 (entity graph)
 *   - S9 GET /v1/entities/{entityId}/contradictions (NLP contradictions)
 * DESIGN REFERENCE: PRD-0028 §6.5 Instrument Detail State C-4 Intelligence tab
 */

"use client";
// WHY "use client": uses useQuery for async data fetching, useState, sigma.js WebGL.

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { EntityDescriptionPanel } from "@/components/instrument/EntityDescriptionPanel";
import { EntityGraphErrorBoundary } from "@/components/instrument/EntityGraphErrorBoundary";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, RefreshCw, ChevronRight, ChevronDown, Clock, Network, ArrowUpRight, X } from "lucide-react";
import { MarkdownContent } from "@/components/ui/markdown-content";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { formatRelativeTime, cn } from "@/lib/utils";
import type { BriefingResponse, Contradiction } from "@/types/api";
import { useState, useMemo, useCallback } from "react";

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

// ── Props ─────────────────────────────────────────────────────────────────────

interface IntelligenceTabProps {
  entityId: string;
}

// ── SelectedNodeInfo — data passed from the graph on node click ───────────────
// WHY separate type (not EntityGraphNode): the sidebar needs pre-computed edge data
// (neighbor labels, relation types) that the raw graph node doesn't carry. GraphEvents
// assembles this from graphology's adjacency API and passes it here.
interface SelectedNodeInfo {
  nodeId: string;
  label: string;
  nodeType: string;
  degree: number;
  edges: Array<{
    label: string;
    weight: number;
    neighborId: string;
    neighborLabel: string;
  }>;
}

// ── Severity helpers ──────────────────────────────────────────────────────────
const SEVERITY_STYLES: Record<
  Contradiction["severity"],
  { icon: string; badge: string; text: string }
> = {
  HIGH: {
    icon: "text-negative",
    badge: "bg-destructive/15 text-negative",
    text: "HIGH",
  },
  MEDIUM: {
    icon: "text-warning",
    badge: "bg-warning/15 text-warning",
    text: "MED",
  },
  LOW: {
    icon: "text-muted-foreground",
    badge: "bg-muted text-muted-foreground",
    text: "LOW",
  },
};

// ── Node type → color mapping (mirrors sigma graph node colors) ───────────────
// WHY explicit map (not dynamic): these match the sigma node fill colors set in
// GraphLoader. Consistency between graph and sidebar is a deliberate design contract.
const NODE_TYPE_COLORS: Record<string, string> = {
  financial_instrument: "bg-primary/15 text-primary border-primary/30",
  // WHY arbitrary-value bg-[hsl(var(--accent-ai))]: --accent-ai is defined in
  // globals.css but not registered in tailwind.config.ts, so the shorthand
  // `bg-accent-ai/15` does not generate any class. The full var() form is the
  // pattern used elsewhere (InstrumentAskAiButton, AnalystRail) — keeps a
  // single design-token source while compiling to a real Tailwind utility.
  organization: "bg-[hsl(var(--accent-ai)/0.15)] text-[hsl(var(--accent-ai))] border-[hsl(var(--accent-ai)/0.30)]",
  // WHY tokens (was off-palette purple-500/orange-500): person reuses the
  // accent-ai violet (humans/AI share the violet semantic group); macro_event
  // uses the design-system --warning amber for "attention".
  person: "bg-[hsl(var(--accent-ai)/0.15)] text-[hsl(var(--accent-ai))] border-[hsl(var(--accent-ai)/0.30)]",
  macro_event: "bg-warning/15 text-warning border-warning/30",
  // product uses positive (green token) — intentional semantic match
  product: "bg-positive/10 text-positive border-positive/20",
};

// ── ContradictionCard sub-component ───────────────────────────────────────────
function ContradictionCard({
  item,
  isExpanded,
  onToggle,
}: {
  item: Contradiction;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const styles = SEVERITY_STYLES[item.severity];

  if (!isExpanded) {
    return (
      <div
        onClick={onToggle}
        className="flex items-center h-[22px] border-b border-border/30 hover:bg-muted/40 cursor-pointer"
        role="presentation"
      >
        <button
          type="button"
          className="w-full flex items-center h-[22px] px-2 gap-1.5 text-left"
          onClick={(e) => { e.stopPropagation(); onToggle(); }}
          aria-expanded={false}
          aria-label={`Expand contradiction: ${item.claim_a.slice(0, 40)}`}
        >
          <span className={`rounded-[2px] px-1 py-0 text-[9px] font-semibold uppercase ${styles.badge}`}>
            {styles.text}
          </span>
          <span className="text-[11px] text-foreground flex-1 truncate">
            {item.claim_a.slice(0, 60)}{item.claim_a.length > 60 ? "…" : ""}
          </span>
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground shrink-0">
            {formatRelativeTime(item.detected_at)}
          </span>
          <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" strokeWidth={1.5} />
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-[2px] border border-border/40 bg-card/60 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className={`rounded-[2px] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${styles.badge}`}>
          {styles.text}
        </span>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
            {formatRelativeTime(item.detected_at)}
          </span>
          <button onClick={onToggle} className="text-muted-foreground hover:text-foreground" aria-label="Collapse contradiction">
            <ChevronDown className="h-3 w-3" strokeWidth={1.5} />
          </button>
        </div>
      </div>
      <div className="space-y-2">
        <div className="rounded-[2px] bg-positive/5 p-2">
          <p className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">Claim A</p>
          <p className="text-[11px] text-foreground/80 leading-relaxed">&ldquo;{item.claim_a}&rdquo;</p>
          <p className="mt-1 text-[10px] text-muted-foreground">— {item.source_a}</p>
        </div>
        <div className="flex items-center justify-center">
          <AlertTriangle className={`h-3 w-3 ${styles.icon}`} strokeWidth={1.5} />
          <span className={`mx-1 text-[9px] font-semibold uppercase ${styles.icon}`}>vs</span>
          <AlertTriangle className={`h-3 w-3 ${styles.icon}`} strokeWidth={1.5} />
        </div>
        <div className="rounded-[2px] bg-negative/5 p-2">
          <p className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">Claim B</p>
          <p className="text-[11px] text-foreground/80 leading-relaxed">&ldquo;{item.claim_b}&rdquo;</p>
          <p className="mt-1 text-[10px] text-muted-foreground">— {item.source_b}</p>
        </div>
      </div>
    </div>
  );
}

// ── InstrumentBriefSection ────────────────────────────────────────────────────
const BRIEF_STALE_MS = 12 * 60 * 60 * 1000;

function InstrumentBriefSection({ entityId }: { entityId: string }) {
  const { accessToken } = useAuth();
  const { data: brief, isLoading, isError, error } = useQuery<BriefingResponse>({
    queryKey: ["instrument-brief", entityId],
    queryFn: () => createGateway(accessToken).getInstrumentBrief(entityId),
    enabled: !!accessToken && !!entityId,
    staleTime: 30 * 60 * 1000,
    retry: 2,
    retryDelay: 10_000,
  });

  return (
    <section className="p-3">
      <h3 className="mb-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground">AI Intelligence Brief</h3>
      {isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      )}
      {isError && !isLoading && (
        <div className="rounded-[2px] border border-border/30 bg-card/30 p-3 text-[11px] text-muted-foreground">
          {error instanceof Error && (error.message.includes("503") || error.message.includes("unavailable"))
            ? "Brief generating... check back in a few minutes."
            : "Intelligence brief unavailable."}
        </div>
      )}
      {!isLoading && !isError && brief && (
        <div>
          {Date.now() - new Date(brief.generated_at).getTime() > BRIEF_STALE_MS && (
            <div className="mb-2 flex items-center gap-1">
              <RefreshCw className="h-3 w-3 text-warning" />
              <span className="text-[11px] text-warning">Brief may be outdated</span>
            </div>
          )}
          <MarkdownContent size="compact">{brief.narrative}</MarkdownContent>
          <p className="mt-2 font-mono text-[10px] tabular-nums text-muted-foreground">
            Generated {new Date(brief.generated_at).toISOString().slice(0, 16).replace("T", " ")} UTC
          </p>
        </div>
      )}
      {!isLoading && !isError && !brief && (
        <div className="rounded-[2px] border border-border/30 bg-card/30 p-3 text-[11px] text-muted-foreground">
          No intelligence brief available for this entity yet.
        </div>
      )}
    </section>
  );
}

// ── GraphDetailSidebar — right panel showing node/edge info or graph stats ────
/**
 * WHY RIGHT SIDEBAR: Clicking a node in the sigma graph previously navigated away
 * to the entity's instrument page — this destroyed the analyst's context. Instead:
 * clicking a node populates this sidebar with the entity's relations and stats.
 * The "Open entity page" button allows deliberate navigation when the analyst
 * decides they want to drill down. This keeps the graph in view while exploring.
 *
 * When no node is selected: shows aggregate graph stats (entity count, edge count,
 * type breakdown) to help analysts understand the graph composition at a glance.
 */
function GraphDetailSidebar({
  selectedNode,
  graphData,
  onClearSelection,
}: {
  selectedNode: SelectedNodeInfo | null;
  graphData: { nodes: Array<{ id: string; label: string; type: string }>; edges: Array<{ source: string; target: string; label: string; weight: number }>; entity_id: string } | null | undefined;
  onClearSelection: () => void;
}) {
  const router = useRouter();

  // WHY unconditional: hooks cannot be inside conditionals. Both branches need these.
  const typeCounts = useMemo(() => {
    if (!graphData?.nodes?.length) return [] as Array<[string, number]>;
    const counts: Record<string, number> = {};
    for (const n of graphData.nodes) {
      const t = n.type ?? "unknown";
      counts[t] = (counts[t] ?? 0) + 1;
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [graphData]);

  const topNodes = useMemo(() => {
    if (!graphData?.nodes?.length || !graphData?.edges?.length) return [] as Array<{ id: string; label: string; type: string; degree: number }>;
    const degreeCounts: Record<string, number> = {};
    for (const e of graphData.edges) {
      degreeCounts[e.source] = (degreeCounts[e.source] ?? 0) + 1;
      degreeCounts[e.target] = (degreeCounts[e.target] ?? 0) + 1;
    }
    return graphData.nodes
      .map((n) => ({ ...n, degree: degreeCounts[n.id] ?? 0 }))
      .sort((a, b) => b.degree - a.degree)
      .slice(0, 5);
  }, [graphData]);

  // ── Selected node panel ──────────────────────────────────────────────────────
  if (selectedNode) {
    const typeStyle = NODE_TYPE_COLORS[selectedNode.nodeType] ?? "bg-muted/40 text-muted-foreground border-border/40";
    const sortedEdges = [...selectedNode.edges].sort((a, b) => b.weight - a.weight);

    return (
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-border/40">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">Entity Details</span>
          <button
            onClick={onClearSelection}
            className="rounded-[2px] p-0.5 text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
            aria-label="Clear node selection"
          >
            <X className="h-3 w-3" strokeWidth={1.5} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-4">
          {/* Entity name + type badge */}
          <div>
            <p className="text-[13px] font-medium text-foreground leading-snug mb-1.5">{selectedNode.label}</p>
            <span className={cn(
              "inline-flex items-center rounded-[2px] border px-1.5 py-0.5 text-[9px] uppercase tracking-wider font-medium",
              typeStyle,
            )}>
              {selectedNode.nodeType.replace(/_/g, " ")}
            </span>
          </div>

          {/* Stats grid */}
          <div className="grid grid-cols-2 gap-px rounded-[2px] overflow-hidden border border-border/30 bg-border/30">
            <div className="bg-card p-2">
              <p className="text-[9px] uppercase tracking-[0.06em] text-muted-foreground mb-0.5">Connections</p>
              <p className="font-mono text-[18px] tabular-nums text-foreground leading-none">{selectedNode.degree}</p>
            </div>
            <div className="bg-card p-2">
              <p className="text-[9px] uppercase tracking-[0.06em] text-muted-foreground mb-0.5">Relations</p>
              <p className="font-mono text-[18px] tabular-nums text-foreground leading-none">{selectedNode.edges.length}</p>
            </div>
          </div>

          {/* Edge list */}
          {sortedEdges.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground mb-1.5">Related Entities</p>
              <div className="rounded-[2px] border border-border/30 overflow-hidden">
                {sortedEdges.slice(0, 8).map((edge, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-2 px-2 py-1.5 border-b border-border/20 last:border-0 hover:bg-muted/20 transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      {/* WHY truncate: neighbor labels can be long company names */}
                      <p className="text-[11px] text-foreground truncate leading-tight">{edge.neighborLabel}</p>
                      <p className="text-[9px] text-muted-foreground uppercase tracking-[0.05em] mt-0.5">
                        {edge.label.replace(/_/g, " ")}
                      </p>
                    </div>
                    {/* Confidence as a percentage bar */}
                    <div className="shrink-0 flex flex-col items-end gap-0.5">
                      <span className="font-mono text-[9px] tabular-nums text-muted-foreground">
                        {(edge.weight * 100).toFixed(0)}%
                      </span>
                      <div className="w-10 h-0.5 bg-border/40 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-primary/60 rounded-full"
                          style={{ width: `${edge.weight * 100}%` }}
                        />
                      </div>
                    </div>
                  </div>
                ))}
                {sortedEdges.length > 8 && (
                  <div className="px-2 py-1 text-[10px] text-muted-foreground bg-card/40">
                    +{sortedEdges.length - 8} more relations
                  </div>
                )}
              </div>
            </div>
          )}

          {sortedEdges.length === 0 && (
            <p className="text-[11px] text-muted-foreground italic">No direct relations visible at current depth/filters.</p>
          )}
        </div>

        {/* Navigate button — pinned at bottom */}
        <div className="p-3 border-t border-border/40">
          <button
            onClick={() => router.push(`/instruments/${selectedNode.nodeId}`)}
            className="w-full flex items-center justify-center gap-1.5 rounded-[2px] border border-border/60 bg-card/60 px-3 py-1.5 text-[11px] text-foreground hover:bg-muted/40 hover:border-border transition-colors"
          >
            Open entity page
            <ArrowUpRight className="h-3 w-3" strokeWidth={1.5} />
          </button>
        </div>
      </div>
    );
  }

  // ── Default panel: graph-level stats ────────────────────────────────────────
  const nodeCount = graphData?.nodes?.length ?? 0;
  const edgeCount = graphData?.edges?.length ?? 0;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-3 py-2 border-b border-border/40">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">Graph Overview</span>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-4">

        {/* Graph size stats */}
        <div className="grid grid-cols-2 gap-px rounded-[2px] overflow-hidden border border-border/30 bg-border/30">
          <div className="bg-card p-2">
            <p className="text-[9px] uppercase tracking-[0.06em] text-muted-foreground mb-0.5">Entities</p>
            <p className="font-mono text-[18px] tabular-nums text-foreground leading-none">{nodeCount}</p>
          </div>
          <div className="bg-card p-2">
            <p className="text-[9px] uppercase tracking-[0.06em] text-muted-foreground mb-0.5">Relations</p>
            <p className="font-mono text-[18px] tabular-nums text-foreground leading-none">{edgeCount}</p>
          </div>
        </div>

        {/* Entity type breakdown */}
        {typeCounts.length > 0 && (
          <div>
            <p className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground mb-1.5">Entity Types</p>
            <div className="space-y-1.5">
              {typeCounts.map(([type, count]) => {
                const pct = nodeCount > 0 ? (count / nodeCount) * 100 : 0;
                const barStyle = NODE_TYPE_COLORS[type] ?? "bg-muted/40 text-muted-foreground border-border/40";
                return (
                  <div key={type}>
                    <div className="flex items-center justify-between mb-0.5">
                      <span className={cn(
                        "rounded-[2px] border px-1 text-[9px] uppercase tracking-wider",
                        barStyle,
                      )}>
                        {type.replace(/_/g, " ")}
                      </span>
                      <span className="font-mono text-[10px] tabular-nums text-muted-foreground">{count}</span>
                    </div>
                    <div className="h-0.5 w-full bg-border/30 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-primary/40 rounded-full transition-all duration-300"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Top nodes by connection count */}
        {topNodes.length > 0 && (
          <div>
            <p className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground mb-1.5">Most Connected</p>
            <div className="rounded-[2px] border border-border/30 overflow-hidden">
              {topNodes.map((node, i) => (
                <div key={node.id} className="flex items-center gap-2 px-2 py-1.5 border-b border-border/20 last:border-0">
                  <span className="font-mono text-[9px] tabular-nums text-muted-foreground/50 w-3">{i + 1}</span>
                  <span className="flex-1 text-[11px] text-foreground truncate">{node.label}</span>
                  <span className="font-mono text-[10px] tabular-nums text-muted-foreground shrink-0">{node.degree}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Hint text when graph is empty / still loading */}
        {nodeCount === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 py-8 text-center">
            <Network className="h-6 w-6 text-muted-foreground/30" strokeWidth={1} />
            <p className="text-[11px] text-muted-foreground/60">Graph loading...</p>
          </div>
        )}

        {/* Click-to-explore hint */}
        {nodeCount > 0 && (
          <p className="text-[10px] text-muted-foreground/50 italic leading-relaxed">
            Click any node in the graph to inspect its relations here.
          </p>
        )}
      </div>
    </div>
  );
}

// ── Intelligence filter types ─────────────────────────────────────────────────
type DepthValue = 1 | 2 | 3;
type TimeWindow = "7d" | "30d" | "90d" | "all";
type LayoutMode = "force" | "circular" | "hierarchical";

interface IntelligenceFilterState {
  depth: DepthValue;
  relationTypes: string[];
  entityTypes: string[];
  timeWindow: TimeWindow;
  layout: LayoutMode;
  confidenceThreshold: number;
}

const DEFAULT_FILTERS: IntelligenceFilterState = {
  depth: 2,
  relationTypes: [],
  entityTypes: [],
  timeWindow: "all",
  layout: "force",
  confidenceThreshold: 0.0,
};

const ALL_RELATION_TYPES = [
  "CEO_OF", "COMPETES_WITH", "SUPPLIER_OF", "PARTNER_OF",
  "OWNS", "ACQUIRED_BY", "BOARD_MEMBER_OF", "REPORTED",
] as const;

const GRAPH_STALE_MS = 24 * 60 * 60 * 1000;

// ── IntelligenceFilters toolbar ───────────────────────────────────────────────
function IntelligenceFilters({
  filters,
  onFiltersChange,
  availableEntityTypes,
}: {
  filters: IntelligenceFilterState;
  onFiltersChange: (f: IntelligenceFilterState) => void;
  availableEntityTypes: string[];
}) {
  function toggleArrayFilter(field: "relationTypes" | "entityTypes", value: string) {
    const current = filters[field];
    const next = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    onFiltersChange({ ...filters, [field]: next });
  }

  const isDirty =
    filters.depth !== DEFAULT_FILTERS.depth ||
    filters.relationTypes.length > 0 ||
    filters.entityTypes.length > 0 ||
    filters.timeWindow !== DEFAULT_FILTERS.timeWindow ||
    filters.layout !== DEFAULT_FILTERS.layout ||
    filters.confidenceThreshold !== DEFAULT_FILTERS.confidenceThreshold;

  return (
    <div className="border-b border-border/40 bg-card/30 px-3 py-2 space-y-2" aria-label="Graph filter controls">
      {/* Row 1: depth slider + layout + time window + reset */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1.5">
          <label htmlFor="graph-depth" className="text-[10px] text-muted-foreground uppercase tracking-[0.06em] shrink-0">
            Relations
          </label>
          <input
            id="graph-depth"
            type="range"
            min={1} max={3} step={1}
            value={filters.depth}
            onChange={(e) => onFiltersChange({ ...filters, depth: Number(e.target.value) as DepthValue })}
            className="h-1 w-16 accent-primary cursor-pointer"
            aria-label={`Graph depth: ${filters.depth}`}
          />
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground w-3">{filters.depth}</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-muted-foreground uppercase tracking-[0.06em] shrink-0">Layout</span>
          {(["force", "circular", "hierarchical"] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => onFiltersChange({ ...filters, layout: mode })}
              className={cn(
                "rounded-[2px] px-1.5 py-0.5 text-[9px] font-mono capitalize transition-colors",
                filters.layout === mode ? "bg-primary/20 text-primary" : "bg-muted text-muted-foreground hover:bg-muted/70",
              )}
              aria-pressed={filters.layout === mode}
            >{mode}</button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-muted-foreground uppercase tracking-[0.06em] shrink-0">Window</span>
          {(["7d", "30d", "90d", "all"] as const).map((w) => (
            <button
              key={w}
              onClick={() => onFiltersChange({ ...filters, timeWindow: w })}
              className={cn(
                "rounded-[2px] px-1.5 py-0.5 text-[9px] font-mono transition-colors",
                filters.timeWindow === w ? "bg-primary/20 text-primary" : "bg-muted text-muted-foreground hover:bg-muted/70",
              )}
              aria-pressed={filters.timeWindow === w}
            >{w}</button>
          ))}
        </div>
        {isDirty && (
          <button
            onClick={() => onFiltersChange(DEFAULT_FILTERS)}
            className="ml-auto text-[10px] text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Reset all graph filters"
          >Reset</button>
        )}
      </div>

      {/* Row 2: confidence threshold + entity type chips + relation type chips */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1.5 shrink-0">
          <label htmlFor="graph-confidence" className="text-[10px] text-muted-foreground uppercase tracking-[0.06em]">
            Confidence
          </label>
          <input
            id="graph-confidence"
            type="range"
            min={0} max={1} step={0.05}
            value={filters.confidenceThreshold}
            onChange={(e) => onFiltersChange({ ...filters, confidenceThreshold: parseFloat(e.target.value) })}
            className="h-1 w-20 accent-primary cursor-pointer"
            aria-label={`Confidence threshold: ${(filters.confidenceThreshold * 100).toFixed(0)}%`}
          />
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground w-6">
            {(filters.confidenceThreshold * 100).toFixed(0)}%
          </span>
        </div>
        <div className="flex items-center gap-1">
          {availableEntityTypes.length === 0 ? (
            <span className="text-[9px] text-muted-foreground/50 font-mono italic">loading types…</span>
          ) : (
            availableEntityTypes.map((type) => (
              <button
                key={type}
                onClick={() => toggleArrayFilter("entityTypes", type)}
                className={cn(
                  "rounded-[2px] px-1.5 py-0.5 text-[9px] font-mono capitalize transition-colors",
                  filters.entityTypes.includes(type) ? "bg-primary/20 text-primary" : "bg-muted text-muted-foreground hover:bg-muted/70",
                )}
                aria-pressed={filters.entityTypes.includes(type)}
              >{type.replace(/_/g, " ")}</button>
            ))
          )}
        </div>
        <div className="flex items-center gap-1 overflow-x-auto max-w-[220px]">
          {(ALL_RELATION_TYPES as readonly string[]).map((rel) => (
            <button
              key={rel}
              onClick={() => toggleArrayFilter("relationTypes", rel)}
              className={cn(
                "shrink-0 rounded-[2px] px-1.5 py-0.5 text-[9px] font-mono transition-colors",
                filters.relationTypes.includes(rel) ? "bg-positive/20 text-positive" : "bg-muted text-muted-foreground hover:bg-muted/70",
              )}
              aria-pressed={filters.relationTypes.includes(rel)}
              title={rel.replace(/_/g, " ")}
            >{rel.split("_").map((w) => w.slice(0, 3)).join("·")}</button>
          ))}
        </div>
      </div>
    </div>
  );
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

      {/* ── Left column: description + graph + brief + contradictions ─────────── */}
      <div className="flex-1 min-w-0 flex flex-col divide-y divide-border/40">

        {/* Entity description panel (PRD-0073 Worker 13J enrichment).
            WHY above the graph: analysts see the description first — it gives
            context before exploring the relationship graph below.
            The panel renders nothing when description is null (enrichment pending). */}
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

        {/* Contradictions */}
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
          {!isLoading && !isError && contradictions.length === 0 && (
            <p className="py-2 text-[11px] text-positive">No contradictions detected — signals are consistent.</p>
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
              <div className="flex items-center gap-4 h-[22px] px-0 mb-1">
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
      </div>

      {/* ── Right sidebar: node/edge detail panel ──────────────────────────── */}
      {/* WHY sticky-ish via self-start: the sidebar should stay visible while
          the analyst scrolls through brief/contradictions below the graph.
          A truly sticky sidebar requires the parent to have overflow:hidden which
          can break scroll — instead we use a fixed top/bottom so it feels sticky
          without overflow constraints. 270px is wide enough for entity labels
          without competing with the graph's 460px height. */}
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
