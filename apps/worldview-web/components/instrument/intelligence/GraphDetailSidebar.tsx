/**
 * components/instrument/intelligence/GraphDetailSidebar.tsx
 *
 * WHY THIS EXISTS:
 * Extracted from IntelligenceTab.tsx (was lines 576-869) so the tab orchestrator
 * stays under 400 lines while each concern lives in a focused file.
 *
 * The sidebar has two visual modes:
 *
 *   SELECTED NODE: Displays entity name, type badge, EntityDescriptionPanel,
 *   connection/relation stats, and a scrollable list of related entities with
 *   confidence bars and evidence snippets. A pinned "Open entity page" button
 *   enables deliberate navigation.
 *
 *   DEFAULT (no selection): Shows aggregate graph stats (entity count, edge
 *   count, type breakdown, most-connected nodes) so analysts understand the
 *   graph composition at a glance.
 *
 * WHY RIGHT SIDEBAR (not a modal): clicking a node in the sigma graph previously
 * navigated away — this destroyed the analyst's context. The sidebar keeps the
 * graph in view while the analyst explores node details.
 *
 * WHO USES IT: components/instrument/IntelligenceTab.tsx
 */

"use client";

import { useRouter } from "next/navigation";
import { X, ArrowUpRight, Network } from "lucide-react";
import { cn } from "@/lib/utils";
import { useMemo } from "react";
import { EntityDescriptionPanel } from "@/components/instrument/EntityDescriptionPanel";
import type { GraphEdge } from "@/types/api";

// ── SelectedNodeInfo ──────────────────────────────────────────────────────────
// WHY separate type (not EntityGraphNode): the sidebar needs pre-computed edge
// data (neighbor labels, relation types) that the raw graph node doesn't carry.
// GraphEvents assembles this from graphology's adjacency API and passes it here.
export interface SelectedNodeInfo {
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

// ── Props ─────────────────────────────────────────────────────────────────────

interface GraphDetailSidebarProps {
  selectedNode: SelectedNodeInfo | null;
  // WHY GraphEdge[] (not inline type): GraphEdge carries evidence_snippets and
  // relation_summary which we render in the node-detail panel (ISSUE-6).
  graphData: { nodes: Array<{ id: string; label: string; type: string }>; edges: GraphEdge[]; entity_id: string } | null | undefined;
  onClearSelection: () => void;
}

// ── GraphDetailSidebar ────────────────────────────────────────────────────────

export function GraphDetailSidebar({ selectedNode, graphData, onClearSelection }: GraphDetailSidebarProps) {
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

    // WHY plain object (not useMemo): hooks cannot be called inside conditionals.
    // The graphData.edges scan is O(edges) which is cheap (≤200 items max).
    // Join on source/target to retrieve evidence_snippets from raw GraphEdge
    // objects (not available in the graphology adjacency copy). (ISSUE-6, 2026-05-10)
    const evidenceByNeighbor: Record<string, string[]> = {};
    if (graphData?.edges) {
      for (const e of graphData.edges) {
        if (e.source === selectedNode.nodeId || e.target === selectedNode.nodeId) {
          const neighborId = e.source === selectedNode.nodeId ? e.target : e.source;
          if (e.evidence_snippets?.length) {
            evidenceByNeighbor[neighborId] = e.evidence_snippets.slice(0, 2);
          }
        }
      }
    }

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

        {/* WHY space-y-3 (was space-y-4): tighter 12px vertical rhythm matches
            the surrounding gap-3 grid. PLAN-0087 F-DENSITY-002. */}
        <div className="flex-1 overflow-y-auto p-3 space-y-3">
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

          {/* WHY EntityDescriptionPanel here (ISSUE-6, 2026-05-10): when an analyst
              clicks a node in the sigma graph they want to know "who is this entity?"
              before seeing its relations list. The panel fetches GET /v1/entities/{id}
              (cached 2h by TanStack Query) and renders description + completeness bar.
              Renders null when the entity has no enrichment yet — no visual gap. */}
          <EntityDescriptionPanel
            entityId={selectedNode.nodeId}
            className="rounded-[2px] border border-border/30 bg-card/30 -mx-3 px-3"
          />

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
                {sortedEdges.slice(0, 8).map((edge, i) => {
                  // WHY look up by neighborId: graphology adjacency only carries
                  // label/weight; evidence_snippets come from graphData.edges.
                  const snippets = evidenceByNeighbor[edge.neighborId] ?? [];
                  return (
                    <div
                      key={i}
                      className="flex flex-col gap-1 px-2 py-1.5 border-b border-border/20 last:border-0 hover:bg-muted/20 transition-colors"
                    >
                      <div className="flex items-start gap-2">
                        <div className="flex-1 min-w-0">
                          {/* WHY truncate: neighbor labels can be long company names */}
                          <p className="text-[11px] text-foreground truncate leading-tight">{edge.neighborLabel}</p>
                          {/* WHY font-medium on relation type (ISSUE-6): analysts scan
                              HOW entities are connected; bolder text speeds scanning. */}
                          <p className="text-[9px] text-muted-foreground uppercase tracking-[0.05em] mt-0.5 font-medium">
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
                      {/* WHY evidence snippets (ISSUE-6): surface the raw text that
                          produced this relation. Capped at 2 snippets (matching the
                          evidence_snippets_limit=2 param sent in getEntityGraph). */}
                      {snippets.length > 0 && (
                        <div className="space-y-0.5">
                          {snippets.map((snippet, si) => (
                            <p
                              key={si}
                              className="text-[9px] text-muted-foreground/70 leading-relaxed pl-1 border-l border-border/40 italic"
                            >
                              {snippet.length > 120 ? `${snippet.slice(0, 120)}…` : snippet}
                            </p>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
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

      {/* WHY space-y-3: 12px rhythm — see PLAN-0087 F-DENSITY-002. */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">

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
          <div className="flex flex-col items-center justify-center gap-2 py-4 text-center">
            <Network className="h-5 w-5 text-muted-foreground/30" strokeWidth={1} />
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
