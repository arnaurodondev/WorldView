/**
 * IntelligenceTab — PLAN-0099 Wave 2 — Bloomberg-investigation-page rework.
 *
 * WHY THIS LAYOUT (three-zone investigation grid, PRD spec):
 *
 *   ┌──────────┬──────────────────────────────┬───────────────┐
 *   │ DOSSIER  │  GRAPH CANVAS (toolbar+stats)│  NEWS         │
 *   │ identity │                              │  EVENTS       │
 *   │ brief    ├──────────────────────────────┤  CONTRADICT.  │
 *   │ top rels │  SELECTION INSPECTOR         │  NARRATIVE    │
 *   │ related  │  (node / edge / empty)       │               │
 *   ├──────────┴──────────────────────────────┴───────────────┤
 *   │ CHAT STRIP (entity-scoped, collapsible)                  │
 *   └──────────────────────────────────────────────────────────┘
 *
 *   - LEFT (3/14): EntityDossier — WHO the entity is (identity, description,
 *     aliases, AI brief, authority-ranked top relations, related chips).
 *   - CENTRE (7/14): the clickable graph + the inspector DIRECTLY BELOW it —
 *     clicking a node/edge opens its full dossier without the eye leaving
 *     the canvas. This replaces the old right-rail ContextPanel mode switch.
 *   - RIGHT (4/14): WHAT is happening — news feed, temporal events (NEW
 *     Wave-1 endpoint), contradictions, narrative history.
 *   - BOTTOM: the platform's entity-scoped chat (EntityChatPanel reuse),
 *     opened via the "Discuss" actions on the dossier / node inspector.
 *
 * STATE OWNERSHIP — this file owns ALL selection state:
 *   - selectedNodeId / selectedEdgeId: mutually exclusive (selecting one
 *     clears the other) — both the canvas highlight (GraphColumn →
 *     FilterController reducers) and the inspector read them, so they live in
 *     the smallest common parent.
 *   - focusNodeId + focusNonce: "Focus graph here" camera requests. The nonce
 *     re-fires the animation when the same node is focused twice.
 *   - chatOpen: whether the bottom chat strip is expanded.
 *
 * DATA FETCHING — still delegated to children; the PLAN-0099 H composite
 * bundle pre-warms the per-widget caches exactly as before (the dossier reads
 * the same ["entity-detail", id] / brief / graph keys the hydrator seeds).
 */

"use client";
// WHY "use client": useState + useQuery-driven children require the client runtime.

import { useCallback, useState } from "react";
import { MessageSquare, X } from "lucide-react";
import { SelectedEntityProvider } from "@/contexts/SelectedEntityContext";
import { EntityChatPanel } from "@/components/intelligence/EntityChatPanel";
import { EntityDossier } from "./dossier/EntityDossier";
import { GraphColumn } from "./graph/GraphColumn";
import { SelectionDetailPanel } from "./detail/SelectionDetailPanel";
import { NewsColumn } from "./news/NewsColumn";
import { EventsBlock } from "./events/EventsBlock";
import { ContradictionsBlock } from "./context/ContradictionsBlock";
import { NarrativeHistoryDisclosure } from "./context/NarrativeHistoryDisclosure";
// PLAN-0099 H: single-round-trip composite bundle. Hydrates per-widget
// TanStack caches (entity-detail, brief, depth=2 graph, paths, intelligence
// summary) so the dossier / graph / inspector render from cache without
// firing their own initial fetches on cold start.
import { useEntityIntelligenceBundle } from "@/features/intelligence/hooks/useEntityIntelligenceBundle";

// ── Props ────────────────────────────────────────────────────────────────────

export interface IntelligenceTabProps {
  /** Authoritative KG entity_id for the instrument being viewed. */
  readonly entityId: string;
}

// ── Shared chrome: thin accent-bar rail header ───────────────────────────────
// Same DenseMetricsGrid Round-1 pattern used by the dossier/events sections —
// duplicated locally (10 lines) instead of importing from the sibling-owned
// financials tree.
function RailHeader({ label }: { label: string }) {
  return (
    <div className="flex items-center border-b border-border border-l-2 border-l-primary bg-muted/20 h-[18px] px-2 shrink-0">
      <span className="text-[9px] uppercase tracking-widest text-muted-foreground/70 font-medium">
        {label}
      </span>
    </div>
  );
}

export function IntelligenceTab({ entityId }: IntelligenceTabProps) {
  // ── Selection state (canvas highlight + inspector, mutually exclusive) ────
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  // ── Focus requests ("Focus graph here") ───────────────────────────────────
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null);
  const [focusNonce, setFocusNonce] = useState(0);
  // ── Chat strip ─────────────────────────────────────────────────────────────
  // WHY closed by default: the chat eats 200px of vertical space; the
  // investigation grid is the primary surface. The "Discuss" actions and the
  // bottom strip toggle both open it on demand.
  const [chatOpen, setChatOpen] = useState(false);

  // PLAN-0099 H: fire the composite bundle ONCE on tab mount (see file header).
  useEntityIntelligenceBundle(entityId);

  // ── Selection handlers ─────────────────────────────────────────────────────
  // WHY useCallback: GraphColumn → EntityGraph threads these into sigma's
  // event registration effect; stable identities avoid re-registering
  // listeners on every parent render.
  const handleNodeSelect = useCallback((nodeId: string | null) => {
    setSelectedNodeId(nodeId);
    // Mutual exclusion: a node selection dismisses any open edge dossier.
    setSelectedEdgeId(null);
  }, []);

  const handleEdgeSelect = useCallback((edgeId: string) => {
    setSelectedEdgeId(edgeId);
    // Mutual exclusion: an edge selection dismisses any open node dossier.
    setSelectedNodeId(null);
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
  }, []);

  const handleFocusNode = useCallback((nodeId: string) => {
    setFocusNodeId(nodeId);
    // WHY a nonce: focusing the SAME node twice must re-fire the camera
    // animation (the analyst panned away); a bare id dep would no-op it.
    setFocusNonce((n) => n + 1);
  }, []);

  const openChat = useCallback(() => setChatOpen(true), []);

  return (
    // SelectedEntityProvider: EntityChatPanel reads anchorEntityId from this
    // context (chat is ALWAYS scoped to the page's anchor entity — never the
    // clicked node; see EntityChatPanel's module rationale).
    <SelectedEntityProvider anchorEntityId={entityId}>
      <div className="flex flex-col h-full overflow-hidden">
        {/* ── Investigation grid ─────────────────────────────────────────────
            grid-cols-14: dossier 3 (≈21%) · graph 7 (50%) · context 4 (≈29%).
            flex-1 min-h-0 so the chat strip below never pushes it off-screen. */}
        <div className="grid grid-cols-14 flex-1 min-h-0 overflow-hidden">
          {/* ── LEFT: entity dossier (3/14) ──────────────────────────────── */}
          <div className="col-span-3 overflow-y-auto border-r border-border">
            <EntityDossier
              entityId={entityId}
              // Top-relation rows open the EDGE inspector — the list-first
              // path to relation detail (same flow as a canvas edge click).
              onSelectRelation={handleEdgeSelect}
              // Related-entity chips select ticker-less nodes in the inspector.
              onSelectNode={(nodeId) => handleNodeSelect(nodeId)}
              onDiscuss={openChat}
            />
          </div>

          {/* ── CENTRE: graph canvas + selection inspector (7/14) ──────────
              The canvas takes ~58% of the column height, the inspector ~42% —
              enough for the edge dossier's evidence list to show 3-4 chunks
              before its internal scroll kicks in. */}
          <div className="col-span-7 flex flex-col min-h-0">
            <div className="flex-[3] min-h-0 flex flex-col">
              <GraphColumn
                entityId={entityId}
                selectedNodeId={selectedNodeId}
                onNodeSelect={handleNodeSelect}
                onEdgeSelect={handleEdgeSelect}
                selectedEdgeId={selectedEdgeId}
                focusNodeId={focusNodeId}
                focusNonce={focusNonce}
              />
            </div>
            <div className="flex-[2] min-h-0">
              <SelectionDetailPanel
                entityId={entityId}
                selectedNodeId={selectedNodeId}
                selectedEdgeId={selectedEdgeId}
                onClear={clearSelection}
                onSelectNode={(nodeId) => handleNodeSelect(nodeId)}
                onSelectRelation={handleEdgeSelect}
                onFocusNode={handleFocusNode}
                onDiscuss={openChat}
              />
            </div>
          </div>

          {/* ── RIGHT: news / events / contradictions / narrative (4/14) ───
              Split 50/50: the news feed keeps its own infinite scroll in the
              top half; the intelligence stack scrolls independently below so
              a long article list can never bury the events block. */}
          <div className="col-span-4 flex flex-col min-h-0 border-l border-border">
            <div className="flex-1 min-h-0 flex flex-col">
              <RailHeader label="News" />
              <div className="flex-1 min-h-0">
                <NewsColumn entityId={entityId} />
              </div>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto border-t border-border">
              {/* Wave-1 endpoint: entity-scoped temporal events. */}
              <EventsBlock entityId={entityId} />
              {/* Contradictions — component reuse; it owns its own
                  "CONTRADICTIONS [N]" header + named empty state. */}
              <div className="px-2 py-1 border-t border-border/40">
                <ContradictionsBlock entityId={entityId} limit={5} showHeader />
              </div>
              {/* Narrative history — collapsed accordion (component reuse). */}
              <div className="px-2 py-1 border-t border-border/40">
                <NarrativeHistoryDisclosure entityId={entityId} />
              </div>
            </div>
          </div>
        </div>

        {/* ── CHAT STRIP (platform chat reuse) ──────────────────────────────
            Closed: a 22px affordance row (keyboard-reachable). Open: the
            entity-scoped EntityChatPanel (its own 200/400px height + internal
            expand toggle) with a close control in the strip. */}
        {chatOpen ? (
          <div className="shrink-0 relative" data-testid="intel-chat-open">
            {/* Close control overlays the panel's own header row (right side,
                next to its expand chevron) — EntityChatPanel has no close
                affordance of its own and is reused unmodified. */}
            <button
              type="button"
              onClick={() => setChatOpen(false)}
              aria-label="Close chat"
              className="absolute right-8 top-1.5 z-10 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-[2px]"
            >
              <X className="h-3.5 w-3.5" strokeWidth={1.5} aria-hidden />
            </button>
            <EntityChatPanel entityId={entityId} />
          </div>
        ) : (
          <button
            type="button"
            onClick={openChat}
            data-testid="intel-chat-toggle"
            className="shrink-0 flex items-center gap-1.5 h-[22px] px-3 border-t border-border bg-muted/10 text-[9px] font-mono uppercase tracking-wider text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <MessageSquare className="h-3 w-3" strokeWidth={1.5} aria-hidden />
            Discuss this entity
          </button>
        )}
      </div>
    </SelectedEntityProvider>
  );
}
