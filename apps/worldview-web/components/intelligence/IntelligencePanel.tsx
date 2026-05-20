/**
 * components/intelligence/IntelligencePanel.tsx — Column 2: Tabbed intelligence view
 * (PLAN-0074 Wave H T-H-04)
 *
 * WHY THIS COMPONENT EXISTS:
 * The intelligence panel is the analytical core of the intelligence page. It
 * presents four views of the entity's knowledge graph data, each focused on a
 * different analytical question:
 *
 *   Relations tab  — "What does the KG know about this entity?"
 *   Evidence tab   — "What evidence backs those relations?"
 *   Paths tab      — "What surprising multi-hop connections exist?"
 *   Narratives tab — "How has the AI summary evolved over time?"
 *
 * WHY TABS (not separate pages/sections):
 * Each view is useful independently and has different load times. Tabs let
 * the analyst switch contexts without losing their state (active filter, scroll
 * position) in other views. Sections stacked vertically would require too much
 * scrolling — the terminal UI should be scannable, not a long-form document.
 *
 * WHY FILTER BY selectedEntityId:
 * When the user clicks a node in the graph (e.g., Tim Cook in Apple's graph),
 * the Relations and Evidence tabs filter to show only relations involving Tim Cook.
 * This cross-panel sync (via SelectedEntityContext) lets analysts investigate a
 * specific relation without leaving the page.
 *
 * WHO USES IT: IntelligenceLayout column 2 slot
 * DATA SOURCES: Multiple S9 endpoints via lib/api/intelligence.ts
 */

"use client";
// WHY "use client": uses hooks and reads SelectedEntityContext.

import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { RelationsTab } from "@/components/intelligence/tabs/RelationsTab";
import { EvidenceTab } from "@/components/intelligence/tabs/EvidenceTab";
import { PathsTab } from "@/components/intelligence/tabs/PathsTab";
import { NarrativeHistoryTab } from "@/components/intelligence/tabs/NarrativeHistoryTab";
import { useSelectedEntity } from "@/contexts/SelectedEntityContext";

// ── Props ─────────────────────────────────────────────────────────────────────

interface IntelligencePanelProps {
  /** The anchor entity UUIDv7 — used by all tabs as the primary entity */
  entityId: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function IntelligencePanel({ entityId }: IntelligencePanelProps) {
  // WHY read selectedEntityId here (not in each tab):
  // All four tabs share the same cross-panel selection. Reading it here and
  // passing as a prop to each tab centralises the context dependency — tabs
  // are pure presentation components that don't need to know about the context.
  const { selectedEntityId } = useSelectedEntity();

  return (
    <div className="h-full flex flex-col bg-background border-r border-border">
      <Tabs
        defaultValue="relations"
        className="flex flex-col h-full"
      >
        {/* ── Tab bar ──────────────────────────────────────────────────────── */}
        {/* WHY terminal variant: Bloomberg-style underline tabs (see tabs.tsx) */}
        <TabsList
          variant="terminal"
          className="flex-none px-3 w-full justify-start"
          aria-label="Intelligence analysis views"
        >
          <TabsTrigger variant="terminal" value="relations" aria-controls="tab-relations">
            Relations
          </TabsTrigger>
          <TabsTrigger variant="terminal" value="evidence" aria-controls="tab-evidence">
            Evidence
          </TabsTrigger>
          <TabsTrigger variant="terminal" value="paths" aria-controls="tab-paths">
            Paths
          </TabsTrigger>
          <TabsTrigger variant="terminal" value="narratives" aria-controls="tab-narratives">
            Narratives
          </TabsTrigger>
        </TabsList>

        {/* ── Tab content panels ────────────────────────────────────────────── */}
        {/* WHY flex-1 overflow-hidden on TabsContent wrapper:
            Each tab's content needs to fill the remaining height below the tab bar.
            The inner content (ScrollArea or virtual list) handles its own overflow.
            Without flex-1, the panel would collapse to zero height. */}

        <TabsContent
          value="relations"
          id="tab-relations"
          className="flex-1 overflow-hidden mt-0"
        >
          <RelationsTab
            entityId={entityId}
            selectedEntityId={selectedEntityId}
          />
        </TabsContent>

        <TabsContent
          value="evidence"
          id="tab-evidence"
          className="flex-1 overflow-hidden mt-0"
        >
          <EvidenceTab
            entityId={entityId}
            selectedEntityId={selectedEntityId}
          />
        </TabsContent>

        <TabsContent
          value="paths"
          id="tab-paths"
          className="flex-1 overflow-hidden mt-0"
        >
          <PathsTab
            entityId={entityId}
            selectedEntityId={selectedEntityId}
          />
        </TabsContent>

        <TabsContent
          value="narratives"
          id="tab-narratives"
          className="flex-1 overflow-hidden mt-0"
        >
          {/* WHY selectedEntityId passed here: NarrativeHistoryTab now shows the
              "Filtered to:" banner for graph selection parity with the other tabs.
              FR-3.2 MED-009. */}
          <NarrativeHistoryTab entityId={entityId} selectedEntityId={selectedEntityId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
