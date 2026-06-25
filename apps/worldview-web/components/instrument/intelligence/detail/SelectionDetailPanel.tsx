/**
 * detail/SelectionDetailPanel.tsx — the inspector below the graph canvas
 * (PLAN-0099 Wave 2, Bloomberg-investigation-page rework).
 *
 * WHY THIS EXISTS (replaces the right-rail ContextPanel's mode switch):
 * The clickable graph is the centrepiece of the reworked Intelligence tab.
 * Clicking a NODE or an EDGE on the canvas must open the full detail of that
 * entity / relation — and the natural place for that detail is directly
 * UNDER the canvas (eye stays on the graph; the panel reads like a terminal
 * "inspector" pane), not in a far-away right rail.
 *
 * THREE MODES (edge > node > empty — edge first because selecting an edge
 * clears the node id in the parent; checking node first would shadow it):
 *   1. selectedEdgeId  → <EdgeInspector/>  (GET /v1/relations/{id} dossier)
 *   2. selectedNodeId  → <NodeInspector/>  (enriched entity dossier)
 *   3. neither         → NAMED empty state ("Select a node or edge…") —
 *      the panel is never blank (Round-1 requirement 4).
 *
 * KEYBOARD: Esc clears the selection (registered here — the inspector is the
 * surface the selection opens, so it owns the dismissal shortcut). The X
 * button in the header is the pointer/per-a11y path.
 *
 * WHO USES IT: IntelligenceTab (centre column, below GraphColumn).
 */

"use client";
// WHY "use client": keyboard listener + interactive children.

import { useEffect, useMemo } from "react";
import { MousePointerClick, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { qk } from "@/lib/query/keys";
import { EdgeInspector } from "./EdgeInspector";
import { NodeInspector } from "./NodeInspector";
import type { EntityGraph, GraphNode } from "@/types/api";

// ── Props ────────────────────────────────────────────────────────────────────

export interface SelectionDetailPanelProps {
  /** Root entity of the page — locates the graph cache slot for node lookup. */
  readonly entityId: string;
  /** Node selected on the canvas / via chips, or null. */
  readonly selectedNodeId: string | null;
  /** Edge selected on the canvas / via top-relation rows, or null. */
  readonly selectedEdgeId: string | null;
  /** Clears BOTH selections (Esc / X). */
  readonly onClear: () => void;
  /** Walk the inspector to another node (edge endpoint pills). */
  readonly onSelectNode: (nodeId: string) => void;
  /** Walk the inspector to a relation (node top-relation rows). */
  readonly onSelectRelation: (relationId: string) => void;
  /** "Focus graph here" passthrough to the canvas camera. */
  readonly onFocusNode: (nodeId: string) => void;
  /** Opens the entity chat strip. */
  readonly onDiscuss: () => void;
  /** Graph depth currently rendered — locates the cache slot (default 2). */
  readonly graphDepth?: number;
}

// ── Component ────────────────────────────────────────────────────────────────

export function SelectionDetailPanel({
  entityId,
  selectedNodeId,
  selectedEdgeId,
  onClear,
  onSelectNode,
  onSelectRelation,
  onFocusNode,
  onDiscuss,
  graphDepth = 2,
}: SelectionDetailPanelProps) {
  const queryClient = useQueryClient();
  const hasSelection = !!selectedEdgeId || !!selectedNodeId;

  // ── Esc clears the selection ───────────────────────────────────────────────
  // WHY window-level (not onKeyDown on the panel): the analyst's focus is
  // usually on the sigma canvas when they want to dismiss — requiring focus
  // inside this panel would make Esc feel broken. Inputs are excluded so Esc
  // inside the chat textarea / search field keeps its native meaning.
  useEffect(() => {
    if (!hasSelection) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable) {
        return;
      }
      onClear();
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [hasSelection, onClear]);

  // ── Resolve the selected node from the graph cache ────────────────────────
  // Passive read of the SAME depth-keyed slot GraphColumn fills — zero new
  // network. getQueryData (not useQuery) is safe here because the parent
  // re-renders this panel on every selection change, and node payloads inside
  // a cached graph are immutable between refetches.
  const selectedNode: GraphNode | null = useMemo(() => {
    if (!selectedNodeId) return null;
    const graph = queryClient.getQueryData<EntityGraph | null>(
      qk.instruments.entityGraph(entityId, graphDepth),
    );
    return graph?.nodes.find((n) => n.id === selectedNodeId) ?? null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNodeId, entityId, graphDepth, queryClient]);

  return (
    <section
      className="flex flex-col h-full min-h-0 border-t border-border"
      aria-label="Selection inspector"
      data-testid="selection-detail-panel"
    >
      {/* ── Header: accent bar + mode label + clear (X) ─────────────────────
          The accent-bar header is the house section marker (DenseMetricsGrid
          Round-1 pattern); the label names the current mode so the analyst
          always knows WHAT the panel below is describing. */}
      <div className="flex items-center justify-between border-b border-border border-l-2 border-l-primary bg-muted/20 h-[18px] px-2 shrink-0">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/70 font-medium">
          {selectedEdgeId ? "Inspector · Relation" : selectedNodeId ? "Inspector · Entity" : "Inspector"}
        </span>
        {hasSelection && (
          <button
            type="button"
            onClick={onClear}
            aria-label="Clear selection"
            title="Clear selection (Esc)"
            className="text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-[2px]"
          >
            <X className="h-3 w-3" strokeWidth={1.5} aria-hidden />
          </button>
        )}
      </div>

      {/* ── Body: scrolls independently so a 25-row evidence list never grows
          the panel and pushes the canvas off-screen. ───────────────────── */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {/* MODE 1 — edge dossier. Checked FIRST (see file header). */}
        {selectedEdgeId ? (
          <EdgeInspector relationId={selectedEdgeId} onSelectNode={onSelectNode} />
        ) : selectedNodeId ? (
          /* MODE 2 — node dossier. graphNode is null for off-graph selections
             (edge endpoint pills whose entity is outside the rendered graph) —
             the inspector then renders from the entity-detail fetch instead of
             dead-ending (the "Focus graph" action hides itself in that case). */
          <NodeInspector
            nodeId={selectedNodeId}
            graphNode={selectedNode}
            onSelectRelation={onSelectRelation}
            onFocusNode={onFocusNode}
            onDiscuss={onDiscuss}
          />
        ) : (
          /* MODE 3 — named empty state. The inspector is NEVER blank. */
          <div
            role="status"
            data-testid="inspector-empty"
            className="flex h-full flex-col items-center justify-center gap-1 px-3 py-4 text-center"
          >
            <MousePointerClick
              className="size-4 text-muted-foreground/60"
              strokeWidth={1.5}
              aria-hidden
            />
            <p className="text-[12px] text-foreground">Select a node or edge to inspect</p>
            <p className="text-[11px] text-muted-foreground">
              Click a node for the entity dossier, an edge for the relation evidence — or pick a top
              relation from the left rail.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
