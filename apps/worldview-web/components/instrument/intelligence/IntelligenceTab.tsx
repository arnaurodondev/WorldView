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
// PLAN-0099 H: single-round-trip composite bundle. Hydrates per-widget
// TanStack caches (entity-detail, brief, depth=2 graph, paths, intelligence
// summary) so ContextPanel / GraphColumn / PathInsightsBlock / useEntityIntelligence
// render from cache without firing their own initial fetches on cold start.
// See the hook file for the exact-key hydration contract.
import { useEntityIntelligenceBundle } from "@/features/intelligence/hooks/useEntityIntelligenceBundle";

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
  // ── selectedEdgeId (Block I T-27) ────────────────────────────────────────
  // WHY lifted here (not in ContextPanel or GraphColumn): the edge selection
  // must be visible to both the graph (to highlight the clicked edge) and the
  // right panel (to render EdgeDetailCard). IntelligenceTab is the smallest
  // common parent for both children.
  // Clicking an edge also clears the node selection so the panel switches to
  // edge-detail mode (not node-detail + edge-detail simultaneously).
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);

  // PLAN-0099 H: fire the composite bundle ONCE on tab mount. The hook's
  // useEffect side-effect hydrates per-widget TanStack caches via
  // setQueryData under the EXACT keys each child reads. Children continue to
  // call their own useQuery hooks; TanStack returns the seeded data instantly
  // so the cold-start render skips 4 sequential network round-trips.
  // WHY we don't read the returned value: the bundle is purely an initial-
  // load optimisation — children own their own loading / error UI keyed off
  // their respective queries. If the bundle itself fails entirely (top-level
  // network error), each child's individual queryFn still fires as a fallback,
  // so the page still functions.
  useEntityIntelligenceBundle(entityId);

  return (
    // WHY grid grid-cols-14 (not 12): PRD-0088 W7 bumps the news rail from
    // 3/12 → 4/14 (≈28%), the graph from 6/12 → 7/14 (≈50%), and the context
    // rail stays at 3/14 (≈21%). The extra 2 columns give the graph column
    // more breathing room for the sigma.js canvas while keeping the news rail
    // wide enough for a DenseArticleRow (~200 px minimum). tailwind.config.ts
    // has the custom `gridTemplateColumns: { "14": "repeat(14, ...)" }` entry.
    // h-full + overflow-hidden lock the tab to the parent box
    // (InstrumentPageClient's `<div className="flex-1 min-h-0 overflow-hidden">`).
    // Each column then owns its own scroll context.
    <div className="grid grid-cols-14 h-full overflow-hidden">
      {/* ── LEFT: news rail (4/14 ≈ 28%) ────────────────────────────────────
          overflow-y-auto so the article list scrolls inside this column
          without lifting the whole tab. border-r separates from the graph. */}
      <div className="col-span-4 overflow-y-auto border-r border-border">
        <NewsColumn entityId={entityId} />
      </div>

      {/* ── CENTER: graph + brief (7/14 = 50%) ───────────────────────────────
          GraphColumn manages its own internal layout (brief on top, toolbar,
          graph fills remaining height) so this slot is just `flex flex-col`. */}
      <div className="col-span-7 flex flex-col">
        <GraphColumn
          entityId={entityId}
          selectedNodeId={selectedNodeId}
          onNodeSelect={(nodeId) => {
            setSelectedNodeId(nodeId);
            // WHY clear edge when a node is selected: the two selection modes
            // are mutually exclusive. Clicking a node should dismiss any open
            // EdgeDetailCard and show NodeDetailCard instead.
            setSelectedEdgeId(null);
          }}
          onEdgeSelect={(edgeId) => {
            setSelectedEdgeId(edgeId);
            // WHY clear node: edge-detail mode and node-detail mode are mutually
            // exclusive. Clicking an edge dismisses the open NodeDetailCard.
            setSelectedNodeId(null);
          }}
        />
      </div>

      {/* ── RIGHT: context panel (3/14 ≈ 22%) ─────────────────────────────────
          When selectedNodeId === null → entity-overview mode (EntityOverviewBlock
          + TopRelationsBlock + PathInsightsBlock + ContradictionsBlock +
          NarrativeHistoryDisclosure).
          When selectedNodeId !== null → node-detail mode + Back to overview.
          The panel does its own data fetching for entity detail and graph,
          keyed by entityId — see components/instrument/intelligence/context/
          ContextPanel.tsx for the canonical implementation contract. */}
      <div className="col-span-3 overflow-y-auto border-l border-border">
        <ContextPanel
          entityId={entityId}
          selectedNodeId={selectedNodeId}
          onClearSelection={() => {
            setSelectedNodeId(null);
            setSelectedEdgeId(null);
          }}
          selectedEdgeId={selectedEdgeId}
          onClearEdgeSelection={() => setSelectedEdgeId(null)}
          // Round-2 item 3: RelatedEntitiesPanel chips (inside ContextPanel)
          // select ticker-less nodes in-panel. Same mutual-exclusion rule as
          // the graph canvas: selecting a node dismisses any open edge detail.
          onNodeSelect={(nodeId) => {
            setSelectedNodeId(nodeId);
            setSelectedEdgeId(null);
          }}
        />
      </div>
    </div>
  );
}
