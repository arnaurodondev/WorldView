/**
 * IntelligenceTab — PLAN-0090 T-D-04 — orchestrator for the Intelligence tab.
 *
 * WHY THIS EXISTS (PRD-0088 §6.9):
 * The new Intelligence tab is a 3-column grid:
 *   left  (col-span-3) : <NewsColumn />          — news rail
 *   center(col-span-6) : <GraphColumn />          — brief + graph
 *   right (col-span-3) : <ContextPanel />         — entity / node detail
 *
 * The previous IntelligenceTab.tsx (sibling file at ../IntelligenceTab.tsx) was a
 * single ~1330-line component that stacked summary cards, the graph and filters,
 * the brief and contradictions all in one vertical scroll. That mode does not
 * fit the redesign — the new layout puts the three views side-by-side so the
 * analyst can read news while exploring the graph and inspecting a node without
 * losing context.
 *
 * STATE OWNERSHIP — the only state in this file is `selectedNodeId: string|null`.
 * It is owned here (and not inside GraphColumn) so the right-hand ContextPanel
 * can read it AND the center GraphColumn can reflect it. Hoisting selection up
 * to the smallest common parent is the canonical React pattern; it also keeps
 * the children fully presentational and trivially testable.
 *
 * DATA FETCHING — this file is intentionally a thin layout. All gateway calls
 * live inside the children (GraphColumn owns brief+graph; NewsColumn owns
 * articles; ContextPanel owns entity detail). Past versions co-fetched here
 * and prop-drilled — that approach made the cache shape implicit and broke
 * whenever a child added a new field.
 *
 * WHY only `entityId` (instrumentId removed): every downstream child consumes
 * the KG entity id (S9 routes are entity-scoped). The instrumentId from the
 * page bundle is already cached by TanStack Query at the layout level so the
 * children that need it (e.g. quote/financials) read it independently.
 */

"use client";
// WHY "use client": useState plus useQuery-driven children all require the
// React client runtime. The whole tab is a client island.

import { useState } from "react";
import { NewsColumn } from "./news/NewsColumn";
import { GraphColumn } from "./graph/GraphColumn";
import { ContextPanel } from "./context/ContextPanel";

// ── Props ────────────────────────────────────────────────────────────────────
//
// WHY just entityId: see file header. The page-bundle hook already caches the
// instrument-level data so children that need an instrumentId can pull it from
// the query cache without prop-drilling.

export interface IntelligenceTabProps {
  /** Authoritative KG entity_id for the instrument being viewed. */
  readonly entityId: string;
}

export function IntelligenceTab({ entityId }: IntelligenceTabProps) {
  // ── Selected-node state (lifted up) ───────────────────────────────────────
  // WHY useState here (not inside GraphColumn): the right-hand ContextPanel
  // needs to know which node is selected to toggle between "entity overview"
  // and "node detail" modes. Lifting selection up to the smallest common
  // parent keeps the two children in sync without a context provider.
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  return (
    // WHY grid grid-cols-12: PRD-0088 §6.9 specifies a 12-column layout where
    // the news rail is 3/12 (≈25%), the graph is 6/12 (50%), and the context
    // rail is 3/12. h-full + overflow-hidden lock the tab to the parent box
    // (InstrumentPageClient's `<div className="flex-1 min-h-0 overflow-hidden">`).
    // Each column then owns its own scroll context.
    <div className="grid grid-cols-12 h-full overflow-hidden">
      {/* ── LEFT: news rail (3/12) ──────────────────────────────────────────
          overflow-y-auto so the article list scrolls inside this column
          without lifting the whole tab. border-r separates from the graph. */}
      <div className="col-span-3 overflow-y-auto border-r border-border">
        <NewsColumn instrumentId={entityId} />
      </div>

      {/* ── CENTER: graph + brief (6/12) ────────────────────────────────────
          GraphColumn manages its own internal layout (brief on top, toolbar,
          graph fills remaining height) so this slot is just `flex flex-col`. */}
      <div className="col-span-6 flex flex-col">
        <GraphColumn
          entityId={entityId}
          selectedNodeId={selectedNodeId}
          onNodeSelect={setSelectedNodeId}
        />
      </div>

      {/* ── RIGHT: context panel (3/12) ────────────────────────────────────
          When selectedNodeId === null → entity-overview mode.
          When selectedNodeId !== null → node-detail mode + Back to overview.
          The panel does its own data fetching for entity detail and graph,
          keyed by entityId — see components/instrument/intelligence/context/
          ContextPanel.tsx for the canonical implementation contract. */}
      <div className="col-span-3 overflow-y-auto border-l border-border">
        <ContextPanel
          entityId={entityId}
          selectedNodeId={selectedNodeId}
          onClearSelection={() => setSelectedNodeId(null)}
        />
      </div>
    </div>
  );
}
