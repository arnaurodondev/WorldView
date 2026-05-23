/**
 * context/ContextPanel.tsx — Intelligence right-rail entity-overview (W7 T-15, revised)
 *
 * WHY ALWAYS OVERVIEW MODE:
 * Node/edge detail was moved to InlineSelectionPanel (below the sigma graph)
 * so the right rail is persistently useful context rather than switching away
 * when the analyst clicks a node. The right rail always renders:
 *   EntityOverviewBlock → TopRelationsBlock → PathInsightsBlock
 *   → ContradictionsBlock → NarrativeHistoryDisclosure
 *
 * WHY REMOVED selectedNodeId:
 * The old node-detail mode (NodeDetailCard + RelationsList) lives in
 * InlineSelectionPanel now. ContextPanel no longer needs graph data.
 *
 * WHO USES IT: IntelligenceTab (right column, col-span-5).
 */

"use client";
// WHY "use client": child components with hooks require browser context.

import { cn } from "@/lib/utils";
import { SectionDivider } from "@/components/primitives/SectionDivider";
import { EntityOverviewBlock } from "./EntityOverviewBlock";
import { TopRelationsBlock } from "./TopRelationsBlock";
import { PathInsightsBlock } from "./PathInsightsBlock";
import { ContradictionsBlock } from "./ContradictionsBlock";
import { NarrativeHistoryDisclosure } from "./NarrativeHistoryDisclosure";

export interface ContextPanelProps {
  /** Primary entity for the instrument page (UUIDv7). */
  entityId: string;
  /** Called when TopRelationsBlock row is clicked — sets selectedNodeId in parent
   *  so the graph visually highlights the node. */
  onNodeSelect?: (nodeId: string) => void;
  /** Optional class override for parent layout. */
  className?: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ContextPanel({ entityId, onNodeSelect, className }: ContextPanelProps) {
  return (
    <section
      className={cn("flex flex-col overflow-y-auto", className)}
      aria-label="Entity overview"
    >
      <EntityOverviewBlock entityId={entityId} />
      <SectionDivider />
      {/* TopRelationsBlock fires onNodeSelect → highlights node in graph */}
      <TopRelationsBlock
        entityId={entityId}
        limit={10}
        onNodeSelect={onNodeSelect ?? (() => {})}
      />
      <SectionDivider />
      <PathInsightsBlock entityId={entityId} limit={3} />
      <SectionDivider />
      <ContradictionsBlock entityId={entityId} limit={5} />
      <SectionDivider />
      <NarrativeHistoryDisclosure entityId={entityId} />
    </section>
  );
}
